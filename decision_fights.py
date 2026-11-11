"""团战执行与人员协同（决策台 P0-3）。

所有数据只从 ``decision_facts`` 的统一事实表读取；指标一律**我方视角**：

- 到位延迟 ``arrivalLagSec`` = 参战时刻 − 团战开始时刻（保留 1 位小数）。
- ``arrivalDiff`` = 我方最早到达 − 敌方最早到达，**负 = 我方先到**。
- ``advStart`` = 团战开始 3 秒内双方到达人数差（我方 − 敌方）。
- ``killDiff`` = 我方击杀 − 敌方击杀；没有击杀记录（0 击杀）时 ``killDiff/won`` 为 None，
  不把「没打起来」判成输。
- ``lateJoins`` = 我方在开始 5 秒之后才到的人数。

边界：只做描述（到位/人数/交换），不判断指挥失误，不宣称因果。
缺失参战时间的人跳过并计入 ``missingParticipants``，不用 0 假填。
"""
from __future__ import annotations

import math

import decision_facts

EARLY_WINDOW_SEC = 3.0
LATE_JOIN_SEC = 5.0
ENOUGH_BUCKET = 8
DEFAULT_LIMIT = 120
MAX_LIMIT = 500
BUCKET_MIN = -5
BUCKET_MAX = 5
MEMBER_STAT_KEYS = ('kills', 'deaths', 'assists', 'hurt', 'taken', 'heal',
                    'hardCtrl', 'softCtrl', 'beginHP', 'endHP', 'ultimates')


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _num(value)
    return int(number) if number is not None else None


def _split_game_ref(game):
    """``game`` 支持 ``seq`` 或 ``seq::fightId``（也接受 ``seq#fightId``）。"""
    text = str(game or '').strip()
    if not text:
        return None, None
    for separator in ('::', '#'):
        if separator in text:
            seq, _, fight_id = text.partition(separator)
            return seq.strip() or None, fight_id.strip() or None
    return text, None


def _camp_side(camp, own_code):
    if camp not in ('1', '2') or own_code not in ('1', '2'):
        return None
    return 'own' if camp == own_code else 'enemy'


def _beginner_side(own_count, enemy_count):
    if own_count > enemy_count:
        return 'own'
    if enemy_count > own_count:
        return 'enemy'
    if own_count or enemy_count:
        return 'tie'
    return None


def _row_sort_key(record):
    """损失优先：击杀差升序（负得越多越前）、开局人数差升序、开始时间升序。"""
    kill_diff = record.get('killDiff')
    advance = record.get('advStart')
    return (
        0 if kill_diff is not None else 1,
        kill_diff if kill_diff is not None else 0,
        advance if advance is not None else 0,
        record.get('startSec') or 0.0,
        record.get('game') or '',
        record.get('fightId') or '',
    )


# ---------------------------------------------------------------------------
# 单场团战
# ---------------------------------------------------------------------------
def _fight_members(game, fight, start, own_code):
    """参战成员明细；缺时间/缺阵营的 participant 跳过并计入 missing。"""
    details = {}
    for item in fight.get('details') or []:
        obj_id = str(item.get('objID') or '')
        if obj_id and obj_id not in details:
            details[obj_id] = item

    member_rows, missing = [], 0
    beginner = {'own': 0, 'enemy': 0}
    obj_to_player = game.get('objToPlayer') or {}
    heroes = game.get('heroes') or {}
    lanes = game.get('lanes') or {}

    for participant in fight.get('participants') or []:
        moment = _num(participant.get('timeSec'))
        camp = str(participant.get('camp') or '')
        side = _camp_side(camp, own_code)
        if moment is None or side is None:
            missing += 1
            continue
        obj_id = str(participant.get('objID') or '')
        player = obj_to_player.get(obj_id) or ''
        is_beginner = 1 if _int(participant.get('beginner')) == 1 else 0
        beginner[side] += is_beginner
        detail = details.get(obj_id) or {}
        member = {
            'objId': obj_id,
            'player': player,
            'hero': heroes.get(player) or '',
            'lane': lanes.get(player) or '',
            'camp': side,
            'campCode': camp,
            'arrivalLagSec': round(moment - start, 1),
            'joinOrder': None,
            'beginner': is_beginner,
        }
        for key in MEMBER_STAT_KEYS:
            member[key] = _int(detail.get(key))
        member_rows.append((moment, camp, member))

    member_rows.sort(key=lambda item: (item[0], item[1], item[2]['objId']))
    for order, row in enumerate(member_rows, 1):
        row[2]['joinOrder'] = order
    return [row[2] for row in member_rows], missing, beginner


def _fight_record(game, base, raw, own_code):
    """团战行：我方视角的关键指标 + 成员明细（rows 输出时会去掉 members）。"""
    start = base['startSec']
    members, member_missing, beginner = _fight_members(game, raw, start, own_code)
    own_lags = [member['arrivalLagSec'] for member in members if member['camp'] == 'own']
    avg_lag = round(decision_facts.mean(own_lags), 1) if own_lags else None
    record = {
        'game': game.get('id'),
        'label': game.get('label') or '',
        'date': game.get('date') or '',
        'opponentId': game.get('opponentId'),
        'opponentName': game.get('opponentName') or '',
        'result': game.get('result'),
        'ownCamp': game.get('ownCamp'),
        'enemyCamp': game.get('enemyCamp'),
        'fightId': base['fightId'],
        'startSec': start,
        'endSec': base['endSec'],
        'duration': base['duration'],
        'phase': decision_facts.phase_of(start),
        'timeLabel': decision_facts.clock(start),
        'ownParticipants': base['ownParticipants'],
        'enemyParticipants': base['enemyParticipants'],
        'missingParticipants': max(member_missing, base['missingParticipants']),
        'arrivalDiff': base['arrivalDiff'],
        'advStart': base['advStart'],
        'ownKills': base['ownKills'],
        'enemyKills': base['enemyKills'],
        'killDiff': base['killDiff'],
        'won': base['won'],
        'lateJoins': base['lateJoins'],
        'firstSide': base['firstSide'],
        'firstKillerSide': _side_of_camp(raw.get('firstKillerCamp'), game.get('ownCamp')),
        'beginnerSide': _beginner_side(beginner['own'], beginner['enemy']),
        'avgArrivalLagSec': avg_lag,
        'members': members,
    }
    return record


def _selected_detail(record):
    detail = dict(record)
    detail['arrivalBars'] = [{
        'player': member['player'],
        'hero': member['hero'],
        'lane': member['lane'],
        'camp': member['camp'],
        'from': 0,
        'to': member['arrivalLagSec'],
    } for member in record.get('members') or []]
    return detail


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def _opening_buckets(records):
    counters = {advance: {'n': 0, 'wins': 0, 'decided': 0}
                for advance in range(BUCKET_MIN, BUCKET_MAX + 1)}
    unbucketed = 0
    for record in records:
        advance = record.get('advStart')
        bucket = counters.get(advance)
        if bucket is None:
            unbucketed += 1
            continue
        bucket['n'] += 1
        if record.get('killDiff') is not None:
            bucket['decided'] += 1
            if record.get('won'):
                bucket['wins'] += 1
    buckets = []
    for advance in range(BUCKET_MIN, BUCKET_MAX + 1):
        bucket = counters[advance]
        enough = bucket['n'] >= ENOUGH_BUCKET
        buckets.append({
            'advStart': advance,
            'n': bucket['n'],
            'wins': bucket['wins'],
            'decided': bucket['decided'],
            'winRate': round(bucket['wins'] / bucket['n'] * 100, 1) if bucket['n'] else None,
            'enough': enough,
        })
    return buckets, unbucketed


def _heat(records):
    counts = {}
    skipped = 0
    for record in records:
        kill_diff = record.get('killDiff')
        if kill_diff is None:
            skipped += 1
            continue
        key = (record.get('advStart'), kill_diff)
        cell = counts.setdefault(key, {'count': 0, 'ownWins': 0})
        cell['count'] += 1
        if record.get('won'):
            cell['ownWins'] += 1
    cells = []
    for (advance, kill_diff), cell in sorted(counts.items(),
                                             key=lambda item: (item[0][0], item[0][1])):
        cells.append({
            'x': advance,
            'y': kill_diff,
            'count': cell['count'],
            'ownWins': cell['ownWins'],
            'rate': round(cell['ownWins'] / cell['count'] * 100, 1),
        })
    advance_values = [cell['x'] for cell in cells]
    kill_values = [cell['y'] for cell in cells]
    return {
        'cells': cells,
        'max': max((cell['count'] for cell in cells), default=0),
        'skippedKillDiff': skipped,
        'xRange': [min(advance_values), max(advance_values)] if cells else [BUCKET_MIN, BUCKET_MAX],
        'yRange': [min(kill_values), max(kill_values)] if cells else None,
    }


def _first_arrival_counts(records):
    counts = {'own': 0, 'enemy': 0, 'tie': 0, 'none': 0}
    for record in records:
        side = record.get('firstSide')
        counts[side if side in ('own', 'enemy', 'tie') else 'none'] += 1
    return counts


def _side_of_camp(camp, own_camp):
    """把回放阵营码转成我方视角；未知返回 None。"""
    camp = str(camp or '')
    own_code = '1' if own_camp == 'blue' else ('2' if own_camp == 'red' else None)
    if not camp or not own_code:
        return None
    if camp == own_code:
        return 'own'
    return 'enemy'


def _opener_counts(records):
    """先手方统计：用 firstKillerCamp（首个击杀方）与 beginner 标记。"""
    counts = {'own': 0, 'enemy': 0, 'none': 0}
    beginner = {'own': 0, 'enemy': 0, 'tie': 0, 'none': 0}
    for record in records:
        side = record.get('firstKillerSide')
        counts[side if side in ('own', 'enemy') else 'none'] += 1
        side = record.get('beginnerSide')
        beginner[side if side in ('own', 'enemy', 'tie') else 'none'] += 1
    return counts, beginner


def _wipes(games):
    rows = []
    for game in games:
        for wipe in decision_facts.wipes(game):
            item = dict(wipe)
            item['game'] = game.get('id')
            item['label'] = game.get('label') or ''
            rows.append(item)
    rows.sort(key=lambda item: (item.get('game') or '', item.get('t') or 0.0))
    sides = {'own': 0, 'enemy': 0}
    for item in rows:
        if item.get('side') in sides:
            sides[item['side']] += 1
    return rows, sides


def _summary(records, games):
    own_lags = []
    for record in records:
        for member in record.get('members') or []:
            if member['camp'] == 'own':
                own_lags.append(member['arrivalLagSec'])
    own_participants = sum(record.get('ownParticipants') or 0 for record in records)
    late_joins = sum(record.get('lateJoins') or 0 for record in records)
    buckets, unbucketed = _opening_buckets(records)
    wipe_rows, wipe_sides = _wipes(games)
    first_killer, beginner = _opener_counts(records)
    return {
        'fights': len(records),
        'avgArrivalLagSec': round(decision_facts.mean(own_lags), 1) if own_lags else None,
        'lateJoins': late_joins,
        'lateJoinRate': round(late_joins / own_participants * 100, 1)
                        if own_participants else None,
        'ownParticipants': own_participants,
        'firstArrival': _first_arrival_counts(records),
        'firstArrivalNote': '本批回放的团战开始时刻就是最早参战时刻，firstArrival 多为 tie，'
                            '先手请改看 firstKiller / beginner。',
        'firstKiller': first_killer,
        'beginner': beginner,
        'openingBuckets': buckets,
        'unbucketedAdvStart': unbucketed,
        'heat': _heat(records),
        'wipes': len(wipe_rows),
        'wipeSides': wipe_sides,
        'wipeNote': '团灭指一方 5 人全部阵亡；同秒击杀不推断先后。',
        'wipeRows': wipe_rows[:20],
        'ownKills': sum(record.get('ownKills') or 0 for record in records),
        'enemyKills': sum(record.get('enemyKills') or 0 for record in records),
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _unavailable(filters, games, coverage, reason, note=''):
    return {
        'available': False,
        'reason': reason,
        'filters': filters,
        'summary': None,
        'rows': [],
        'selected': None,
        'coverage': coverage,
        'note': note or ('团战数据不足时不画看似完整的图；缺失参战时间的人不会被补成 0。'),
    }


def fight_report(facts, *, game=None, opponent=None, date_from=None, date_to=None,
                 result=None, side=None, limit=120):
    """团战执行报告：我方视角的到位、开局人数差、击杀交换与成员明细。"""
    facts = facts or {}
    seq_ref, fight_ref = _split_game_ref(game)
    try:
        limit_value = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit_value = DEFAULT_LIMIT
    side_value = side if side in ('own', 'enemy') else None
    filters = {
        'game': seq_ref,
        'fightId': fight_ref,
        'opponent': opponent or None,
        'dateFrom': date_from or None,
        'dateTo': date_to or None,
        'result': result or None,
        'side': side_value,
        'limit': limit_value,
    }
    note = ('团战指标统一按我方视角：arrivalDiff<0 表示我方先到；advStart 为团战开始 '
            f'{int(EARLY_WINDOW_SEC)} 秒内到达人数差（我方−敌方）；迟到指开始 '
            f'{int(LATE_JOIN_SEC)} 秒后才到。击杀差为 0 击杀的团战不计胜负。'
            '本批回放的 startSec 就是最早参战时刻，arrivalDiff/firstSide 无区分度，'
            '先手看 firstKillerSide/beginnerSide。以上只用于复盘描述，不判断指挥失误。')

    games = decision_facts.filter_games(
        facts, game=seq_ref, opponent=opponent, date_from=date_from, date_to=date_to,
        result=result)

    raw_fights = sum(len(item.get('fights') or []) for item in games)
    fight_games = sum(1 for item in games if item.get('fights'))
    coverage = {
        'games': len(games),
        'fightGames': fight_games,
        'fights': raw_fights,
        'analyzedFights': 0,
        'skippedFights': 0,
        'missingParticipants': 0,
        'opponents': len({item.get('opponentId') for item in games if item.get('opponentId')}),
        'calibrated': bool((facts.get('coverage') or {}).get('calibrated')),
    }

    if not games:
        reason = '没有符合筛选条件的对局（需要已配对终局面板的官方回放）。'
        if not (facts.get('order') or []):
            reason = '当前没有可分析的回放对局：' + reason
        return _unavailable(filters, games, coverage, reason, note)
    if raw_fights == 0:
        return _unavailable(filters, games, coverage,
                            '所选对局没有团战段（battles.fights 为空），无法复盘团战执行。', note)

    records = []
    skipped_fights = 0
    missing_total = 0
    for item in games:
        own_code = decision_facts.CAMP_CODE_REV.get(item.get('ownCamp'))
        raw_index = {}
        for raw in item.get('fights') or []:
            start = _num(raw.get('startSec'))
            if start is None:
                continue
            key = (str(raw.get('fightId') or ''), round(start, 1))
            raw_index.setdefault(key, raw)
        for base in decision_facts.fight_events(item):
            raw = raw_index.get((base['fightId'], base['startSec']))
            if raw is None:
                raw = {'participants': [], 'details': []}
            missing_total += base.get('missingParticipants') or 0
            if (base.get('ownParticipants') or 0) + (base.get('enemyParticipants') or 0) <= 0:
                skipped_fights += 1
                continue
            records.append(_fight_record(item, base, raw, own_code))

    coverage['analyzedFights'] = len(records)
    coverage['skippedFights'] = skipped_fights
    coverage['missingParticipants'] = missing_total

    if not records:
        reason = (f'所选 {len(games)} 局对局里 {raw_fights} 场团战都缺少参战时间，'
                  '无法计算到位与人数差。')
        return _unavailable(filters, games, coverage, reason, note)

    records.sort(key=_row_sort_key)
    rows = []
    for record in records:
        row = dict(record)
        row.pop('members', None)
        rows.append(row)
    limited_rows = rows[:limit_value]

    pool = records
    if fight_ref:
        pool = [record for record in pool if record.get('fightId') == fight_ref]
    selected = _selected_detail(pool[0]) if pool else None
    selected_reason = None
    if selected is None:
        selected_reason = f'没有找到团战「{fight_ref}」的参战记录。' if fight_ref \
            else '没有可展示的团战明细。'

    return {
        'available': True,
        'filters': filters,
        'summary': _summary(records, games),
        'rows': limited_rows,
        'selected': selected,
        'selectedReason': selected_reason,
        'coverage': coverage,
        'note': note,
    }
