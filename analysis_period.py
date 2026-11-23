"""赛训周期简报引擎（docs/period_brief.md）。

把「周期窗口 + 上期等长窗口」的同一套事实表切片压成首页需要的一块数据：

- 周期：today / week / month / custom；上期一律取等长紧邻区间（month 按自然日
  回退、月末截断）。custom 参数非法时抛 ``ValueError``，由 API 层转 400。
- 候选信号：lead_hold / comeback / fight_arrival / fight_trade / objective /
  comp / roster / coverage，每项都算「本期值 / 上期值 / 样本 / 方向」；
  数据不够就跳过，不补 0、不造假。
- 指标与发现：发现按「变化幅度 × 样本权重 × 证据权重」排序，同 kind 与同主题
  各留 1 条，最多 3 条；指标最多 4 条（没有可比变化时取 3 个整期水平项）。
- 文案：只用赛训语言；小样本写「仅作本批观察」；下钻链接携带当前筛选。

所有计算只读 ``match_facts.load_facts`` 的返回值与既有 analysis_* 报告，
不写盘、不重新扫盘（事实表加载与缓存由 briefing_api 负责）。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

import match_facts

PERIOD_KINDS = ('today', 'week', 'month', 'custom')
EXTRA_PERIOD_KINDS = ('recent', 'days')
PERIOD_LABELS = {'today': '今日', 'week': '本周', 'month': '本月', 'custom': '自定义'}
CUR_WORDS = {'today': '今日', 'week': '本周', 'month': '本月', 'custom': '本期',
             'recent': '最近这批', 'days': '最近'}
PREV_WORDS = {'today': '昨天', 'week': '上周同期', 'month': '上月同期', 'custom': '上一周期',
              'recent': '前几场', 'days': '前一批'}
PREV_SHORT = {'today': '昨天', 'week': '上周', 'month': '上月', 'custom': '上期',
              'recent': '前几场', 'days': '前一批'}
RECENT_MAX = 20           # 「最近 N 场」N 上限
DAYS_MAX = 30             # 「最近 D 天」D 上限

MIN_SAMPLE = 3            # 比较类结论的最小样本（docs/period_brief.md §2.1）
COMPARABLE_EPS = 0.5      # 小于这个变化视为「基本持平」
FINDING_MIN_SCORE = 2.0   # 低于这个分值不占发现卡
LEAD_AT10 = 1000          # 十分钟经济领先阈值（与 analysis_economy.SIGNIFICANT_LEAD 同口径）
DEFAULT_SOURCE = 'db,bundle'
RANK_MIN_PEERS = 5        # 同期对手少于这个数就不给排名（避免 2/3 这种假精确）
RANK_TIERS = ((75.0, 'lead', '领先'), (25.0, 'mid', '中等'), (0.0, 'behind', '落后'))
WATCH_LIMIT = 50          # 复盘区每个筛选字段最多给 50 局（前端横向滚动；不再固定 3 局）
WATCH_NUM_LIMIT = 4       # 复盘卡最多给 4 个数字

KIND_ORDER = {
    'advantage': 0, 'fight': 1, 'objective': 2, 'lineup': 3, 'coverage': 4,
}


# ---------------------------------------------------------------------------
# 周期窗口
# ---------------------------------------------------------------------------
def _month_last_day(day):
    return date(day.year + (1 if day.month == 12 else 0),
                1 if day.month == 12 else day.month + 1, 1) - timedelta(days=1)


def _range_label(start, end):
    """MM-DD ~ MM-DD（契约里的 rangeLabel）。"""
    return f'{start.isoformat()[5:]} ~ {end.isoformat()[5:]}'


def parse_period(kind='week', *, today=None, date_from=None, date_to=None):
    """返回本期与上期窗口；custom 参数非法时抛 ValueError。"""
    today = today or date.today()
    kind = str(kind or 'week').strip().lower()
    if kind not in PERIOD_KINDS:
        raise ValueError('period 只能取 today/week/month/custom')
    if kind == 'today':
        start = end = today
    elif kind == 'week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif kind == 'month':
        start = today.replace(day=1)
        end = _month_last_day(start)
    else:
        if not date_from or not date_to:
            raise ValueError('custom 必须同时提供 from 与 to（YYYY-MM-DD）')
        try:
            start = date.fromisoformat(str(date_from).strip())
            end = date.fromisoformat(str(date_to).strip())
        except ValueError as error:
            raise ValueError('from/to 须为 YYYY-MM-DD') from error
        if start > end:
            raise ValueError('开始日期不能晚于结束日期')

    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    if kind == 'today':
        prev_start = prev_end
    elif kind == 'week':
        # 上周同进度：上周一 ~ 上周的今天，不拿上周未来的周末比本周
        prev_start = start - timedelta(days=7)
        prev_end = prev_start + timedelta(days=today.weekday())
    elif kind == 'month':
        prev_start = prev_end.replace(day=1)
        # 上月同进度：上月 1 日 ~ 上月第 today.day 天（月末截断）
        prev_end = min(prev_start + timedelta(days=today.day - 1),
                       _month_last_day(prev_start))
    else:
        # 自定义范围与上一等长区间比较
        prev_start = prev_end - timedelta(days=days - 1)

    return {
        'kind': kind,
        'label': PERIOD_LABELS[kind],
        'from': start.isoformat(),
        'to': end.isoformat(),
        'rangeLabel': _range_label(start, end),
        'days': days,
        'prev': {
            'label': PREV_WORDS[kind],
            'shortLabel': PREV_SHORT[kind],
            'from': prev_start.isoformat(),
            'to': prev_end.isoformat(),
            'rangeLabel': _range_label(prev_start, prev_end),
            'days': (prev_end - prev_start).days + 1,
            # 周/月按相同进度截断；今日与自定义本身就是等长区间。
            'sameProgress': kind in ('week', 'month'),
        },
    }


def _period_cur_word(window):
    """本期口播词：本周/本月/最近这批/最近…（窗口自带优先）。"""
    window = window or {}
    return window.get('curWord') or CUR_WORDS.get(window.get('kind'), '本期')


def _period_prev_word(window):
    window = window or {}
    return window.get('prevWord') or PREV_WORDS.get(window.get('kind'), '上一周期')


def _period_title_word(window):
    window = window or {}
    return window.get('titleWord') or _period_cur_word(window)


def _extra_window(facts, kind, *, today, opponent=None, recent_n=5, days=3):
    """「最近 N 场 / 最近 D 天」窗口：需要事实表才能知道最新一批在哪。

    返回 ``(window, cur, prev)``；一条有日期的回放都没有时返回 ``None``。
    """
    all_games = _collect_games(facts, '0001-01-01', '9999-12-31', opponent)
    if not all_games:
        return None
    if kind == 'recent':
        n = max(1, min(RECENT_MAX, int(recent_n)))
        cur = all_games[-n:]
        prev = all_games[max(0, len(all_games) - 2 * n):len(all_games) - n]
        start = date.fromisoformat(cur[0]['date'])
        end = date.fromisoformat(cur[-1]['date'])
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=max(0, (end - start).days))
        label = f'最近 {n} 场'
        prev_label = f'前 {n} 场'
        window = {
            'kind': 'recent', 'label': label,
            'from': cur[0]['date'], 'to': cur[-1]['date'],
            'rangeLabel': _range_label(start, end), 'days': (end - start).days + 1,
            'n': n,
            'curWord': '最近这批', 'prevWord': prev_label, 'titleWord': label,
            'prev': {
                'label': prev_label, 'shortLabel': prev_label,
                'from': (prev[0]['date'] if prev else prev_start.isoformat()),
                'to': (prev[-1]['date'] if prev else prev_end.isoformat()),
                'rangeLabel': (f"{prev[0]['date'][5:]} ~ {prev[-1]['date'][5:]}"
                               if prev else _range_label(prev_start, prev_end)),
                'days': (end - start).days + 1, 'sameProgress': False,
            },
        }
        return window, cur, prev

    d = max(1, min(DAYS_MAX, int(days)))
    latest = date.fromisoformat(all_games[-1]['date'])
    start = latest - timedelta(days=d - 1)
    end = latest
    start_iso, end_iso = start.isoformat(), end.isoformat()
    cur = [item for item in all_games if start_iso <= item['date'] <= end_iso]
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=d - 1)
    prev = [item for item in all_games
            if prev_start.isoformat() <= item['date'] <= prev_end.isoformat()]
    label = f'最近 {d} 天'
    prev_label = f'前 {d} 天'
    window = {
        'kind': 'days', 'label': label,
        'from': start_iso, 'to': end_iso,
        'rangeLabel': _range_label(start, end), 'days': d,
        'd': d,
        'curWord': '最近', 'prevWord': prev_label, 'titleWord': label,
        'prev': {
            'label': prev_label, 'shortLabel': prev_label,
            'from': prev_start.isoformat(),
            'to': prev_end.isoformat(),
            'rangeLabel': _range_label(prev_start, prev_end),
            'days': d, 'sameProgress': False,
        },
    }
    return window, cur, prev


def _extra_empty_window(kind, *, today, recent_n=5, days=3):
    """最近 N 场 / D 天一条对局都没有时的窗口（给空态用）。"""
    if kind == 'recent':
        n = max(1, min(RECENT_MAX, int(recent_n)))
        label = f'最近 {n} 场'
        return {
            'kind': 'recent', 'label': label,
            'from': today.isoformat(), 'to': today.isoformat(),
            'rangeLabel': _range_label(today, today), 'days': 1, 'n': n,
            'curWord': '最近这批', 'prevWord': f'前 {n} 场', 'titleWord': label,
            'prev': {'label': f'前 {n} 场', 'shortLabel': f'前 {n} 场',
                     'from': today.isoformat(), 'to': today.isoformat(),
                     'rangeLabel': _range_label(today, today),
                     'days': 1, 'sameProgress': False},
        }
    d = max(1, min(DAYS_MAX, int(days)))
    start = today - timedelta(days=d - 1)
    label = f'最近 {d} 天'
    return {
        'kind': 'days', 'label': label,
        'from': start.isoformat(), 'to': today.isoformat(),
        'rangeLabel': _range_label(start, today), 'days': d, 'd': d,
        'curWord': '最近', 'prevWord': f'前 {d} 天', 'titleWord': label,
        'prev': {'label': f'前 {d} 天', 'shortLabel': f'前 {d} 天',
                 'from': (start - timedelta(days=d)).isoformat(),
                 'to': (start - timedelta(days=1)).isoformat(),
                 'rangeLabel': _range_label(start - timedelta(days=d),
                                            start - timedelta(days=1)),
                 'days': d, 'sameProgress': False},
    }


# ---------------------------------------------------------------------------
# 对局集合（面板为准，回放做过程分析）
# ---------------------------------------------------------------------------
def _game_label(day, opponent_name, seq):
    """证据标签：11-04 · 对阵 #29（不编造队名；未命名对手保留系统序号）。"""
    text = str(day or '')
    head = f'{text[5:7]}-{text[8:10]}' if len(text) >= 10 else text
    name = str(opponent_name or '').strip()
    for prefix in ('待命名战队', '待命名队伍', '待命名'):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
            break
    if name:
        return f'{head} · 对阵 {name}'.strip()
    return f'{head} · 对局 {seq}'.strip(' ·')


def _collect_games(facts, start, end, opponent=None):
    """按日期/对手取事实表里「有回放且能判定阵营」的对局（周期口径以此为准）。"""
    games = facts.get('games') or {}
    panels = facts.get('panels') or {}
    seq_to_opponent = facts.get('seqToOpponent') or {}
    names = facts.get('opponentNames') or {}
    out = []
    seen = set()
    for seq in facts.get('order') or []:
        game = games.get(seq)
        if not isinstance(game, dict):
            continue
        day = str(game.get('date') or '')
        if not day or day < start or day > end:
            continue
        opponent_id = str(game.get('opponentId') or seq_to_opponent.get(seq) or '')
        opponent_name = str(game.get('opponentName') or names.get(opponent_id) or '')
        if opponent and opponent not in (opponent_id, opponent_name):
            continue
        # 重复记录：同一天、同一开赛时间、同一时长、同一对手视为同一局，
        # 保留先出现的一条（事实表顺序里带回放的在前）。
        signature = (day, str(game.get('start') or ''),
                     round(float(game.get('duration') or 0)), opponent_id)
        if signature in seen:
            continue
        seen.add(signature)
        result = game.get('result') if game.get('result') in ('win', 'loss') else None
        out.append({
            'seq': str(seq),
            'date': day,
            'start': str(game.get('start') or ''),
            'result': result,
            'hasReplay': True,
            'hasTimeline': bool(game.get('hasEconomy') or game.get('hasEvents')
                                or game.get('hasFights')),
            'opponentId': opponent_id,
            'opponentName': opponent_name,
            'label': _game_label(day, opponent_name, seq),
            'panel': panels.get(seq),
            'game': game,
        })
    out.sort(key=lambda item: (item['date'], item['start'], item['seq']))
    return out


def _collect_panel_only(facts, start, end, opponent=None, *, exclude=()):
    """只有终局面板、没有回放的局；只用于数据覆盖，不参与过程类指标。"""
    panels = facts.get('panels') or {}
    seq_to_opponent = facts.get('seqToOpponent') or {}
    names = facts.get('opponentNames') or {}
    out = []
    for seq, panel in panels.items():
        if seq in exclude or not isinstance(panel, dict):
            continue
        day = str(panel.get('date') or '')
        if not day or day < start or day > end:
            continue
        opponent_id = str(seq_to_opponent.get(seq) or '')
        opponent_name = str(names.get(opponent_id) or '')
        if opponent and opponent not in (opponent_id, opponent_name):
            continue
        out.append({
            'seq': str(seq),
            'date': day,
            'start': str(panel.get('start') or ''),
            'result': 'win' if panel.get('win') is True else (
                'loss' if panel.get('win') is False else None),
            'hasReplay': False,
            'hasTimeline': False,
            'opponentId': opponent_id,
            'opponentName': opponent_name,
            'label': _game_label(day, opponent_name, seq),
            'panel': panel,
            'game': None,
        })
    out.sort(key=lambda item: (item['date'], item['start'], item['seq']))
    return out


def _record(entries):
    wins = sum(1 for item in entries if item['result'] == 'win')
    losses = sum(1 for item in entries if item['result'] == 'loss')
    decided = wins + losses
    return {
        'wins': wins,
        'losses': losses,
        'decided': decided,
        # 无法判定胜负的局：只在战绩里报「未判定」，不进任何胜率分母
        'unknown': max(0, len(entries) - decided),
        'winRate': round(wins / decided * 100, 1) if decided else None,
    }


def _entry_index(entries):
    return {item['seq']: item for item in entries}


# ---------------------------------------------------------------------------
# 周期内的一次性分析结果（同一次请求只算一遍）
# ---------------------------------------------------------------------------
def _advantage_games(entries):
    """从事实表的经济序列算每局优势保持量（与 analysis_economy 旧口径一致）。

    经济点按采样索引均匀铺到时间轴（约 30 秒一个），全部视为近似值。
    """
    games = []
    for item in entries:
        game = item['game']
        if not game:
            continue
        own = [float(value) for value in (game.get('ownDiff') or [])
               if isinstance(value, (int, float))]
        times = game.get('times') or []
        duration = float(game.get('duration') or 0)
        if len(own) < 2 or not times or duration <= 0:
            continue
        peak = max(own)
        peak_index = own.index(peak)
        tail = own[peak_index:]
        low = min(tail)
        low_index = peak_index + tail.index(low)
        low_at = float(times[low_index]) if low_index < len(times) else None
        lead_at10 = (match_facts.value_at(600, own, duration)
                     if duration + 1e-9 >= 600 else None)
        games.append({
            'game': item['seq'],
            'label': item['label'],
            'date': item['date'],
            'opponentName': item['opponentName'],
            'result': item['result'],
            'maxLead': round(peak),
            'maxLeadAt': round(float(times[peak_index]), 1),
            'drawdown': round(max(0.0, peak - low)),
            'drawdownAt': round(low_at, 1) if low_at is not None else None,
            'drawdownAtClock': match_facts.clock(low_at) if low_at is not None else None,
            'leadAt10': round(lead_at10) if lead_at10 is not None else None,
            'comeback': bool(peak >= LEAD_AT10 and item['result'] == 'loss'),
            'approx': True,
        })
    return games


def _fight_rows(entries):
    """把回放团战摊平成按时间排序的行（含所属对局与人数差/击杀差）。"""
    rows = []
    for item in entries:
        game = item['game']
        if not game:
            continue
        for fight in match_facts.fight_events(game):
            row = dict(fight)
            row['game'] = item['seq']
            row['label'] = item['label']
            rows.append(row)
    rows.sort(key=lambda row: (row['game'], row['startSec']))
    return rows


def _lineups(facts, entries):
    """seq → {分路: 英雄}（只取我方；面板行自带分路，比 pick 顺序可靠）。"""
    allowed = {item['seq'] for item in entries}
    out = defaultdict(dict)
    for row in facts.get('rows') or []:
        if not isinstance(row, dict) or row.get('side') != 'own':
            continue
        seq = str(row.get('seq') or '')
        if seq not in allowed:
            continue
        lane = str(row.get('lane') or '').strip()
        hero = str(row.get('hero') or '').strip()
        if lane and hero and lane not in out[seq]:
            out[seq][lane] = hero
    return dict(out)


def _build_context(facts, window, cur, prev, *, opponent, source, validation,
                   cur_panel_only=(), prev_panel_only=()):
    return {
        'facts': facts,
        'cur': cur,
        'prev': prev,
        'cur_panel_only': list(cur_panel_only),
        'prev_panel_only': list(prev_panel_only),
        'cur_index': _entry_index(cur),
        'prev_index': _entry_index(prev),
        'cur_advantage': _advantage_games(cur),
        'prev_advantage': _advantage_games(prev),
        'cur_fights': _fight_rows(cur),
        'prev_fights': _fight_rows(prev),
        'cur_lineups': _lineups(facts, cur),
        'prev_lineups': _lineups(facts, prev),
        'window': window,
        'cur_word': _period_cur_word(window),
        'prev_word': _period_prev_word(window),
        'prev_short': (window.get('prev') or {}).get('shortLabel') or _period_prev_word(window),
        'filters': {
            'from': window['from'], 'to': window['to'], 'opponent': opponent,
            'source': source, 'validation': validation,
        },
    }


# ---------------------------------------------------------------------------
# 文案 / 方向小工具
# ---------------------------------------------------------------------------
def _tone(change, *, higher_is_better=True, eps=COMPARABLE_EPS):
    if change is None:
        return 'none'
    if abs(change) < eps:
        return 'flat'
    better = change > 0 if higher_is_better else change < 0
    return 'up' if better else 'down'


def _rate(wins, total):
    return round(wins / total * 100, 1) if total else None


def _ratio_change(cur, prev):
    if prev is None or cur is None:
        return None
    # 契约 §2.1：计数/均值类用相对变化，分母至少为 1
    return (float(cur) - float(prev)) / max(abs(float(prev)), 1.0) * 100


def _score(candidate):
    change = candidate.get('change')
    if change is not None:
        weight = 0.5 if min(candidate['sample'], candidate['prevSample']) < MIN_SAMPLE else 1.0
        evidence_weight = 1.0 + 0.1 * max(0, min(len(candidate['evidence']), 2) - 1)
        return abs(float(change)) * weight * evidence_weight
    return float(candidate.get('severity') or 0.0) * 0.3


def _destination(base, filters, *, kind='hash'):
    params = [('from', filters['from']), ('to', filters['to'])]
    if filters.get('opponent'):
        params.append(('opponent', filters['opponent']))
    params.append(('source', filters.get('source') or DEFAULT_SOURCE))
    params.append(('validation', filters.get('validation') or '0'))
    return f'#{base}?{urlencode(params)}'


def _evidence(item, note, *, t=None, approx=False):
    return {
        'game': item['seq'],
        'label': item['label'],
        'note': note,
        't': t,
        'approx': bool(approx),
    }


def _pair_stats(left_label, left_wins, left_total, right_label, right_wins,
                right_total, *, unit='局'):
    """展开卡里并排的两组条件胜率：label + 百分比 + 分子分母。

    两组都必须是同一口径（同一批局或同一批团战），否则「低 37 个百分点」
    就是拿不同样本硬比。没有样本的一侧给「—」，不编造 0%。
    """
    def side(label, wins, total):
        rate = _rate(wins, total) if total else None
        return {
            'label': label,
            'value': _fmt_pct(rate) if rate is not None else '—',
            'fraction': f'{wins} 胜 / {total} {unit}' if total else '—',
            'ratio': rate,
        }
    return {'left': side(left_label, left_wins, left_total),
            'right': side(right_label, right_wins, right_total)}


STATUS_BY_TONE = {
    'down': '重点复盘', 'up': '有所改善', 'flat': '持续观察', 'none': '持续观察',
}
CATEGORY_BY_ID = {
    'fight_arrival': '团战协同', 'fight_trade': '团战交换',
    'roster': '发育路', 'lead_hold': '领先兑现', 'comeback': '优势保持',
    'objective': '龙塔资源', 'comp': '阵容体系', 'coverage': '数据覆盖',
}


def _finish(candidate, ctx, *, deep):
    candidate['primary_destination'] = f'#match/{quote(str(candidate["evidence"][0]["game"]))}' \
        if candidate['evidence'] else None
    candidate['deep_destination'] = _destination(deep, ctx['filters'])
    candidate['score'] = round(_score(candidate), 3)
    candidate.setdefault('counterexamples', [])
    candidate.setdefault('numbers', [])
    candidate.setdefault('title', candidate['label'])
    candidate.setdefault('conclusion', '')
    candidate.setdefault('limitation', '')
    candidate.setdefault('severity', 0.0)
    return candidate


# ---------------------------------------------------------------------------
# 候选信号
# ---------------------------------------------------------------------------
def _led_stats(games):
    led = [game for game in (games or [])
           if game.get('leadAt10') is not None and game['leadAt10'] >= LEAD_AT10]
    wins = sum(1 for game in led if game.get('result') == 'win')
    return {'total': len(led), 'wins': wins,
            'rate': _rate(wins, len(led)), 'games': led}


def _cand_lead_hold(ctx):
    cur = _led_stats(ctx['cur_advantage'])
    if cur['total'] < 1:
        return None
    prev = _led_stats(ctx['prev_advantage'])
    change = None
    if cur['rate'] is not None and prev['rate'] is not None:
        change = cur['rate'] - prev['rate']
    tone = _tone(change)
    if prev['total'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur['wins'] - prev['wins']
        delta = (f'多拿下 {diff} 局' if diff > 0
                 else f'少拿下 {-diff} 局' if diff < 0 else '拿下局数持平')
    lost = sorted([game for game in cur['games'] if game.get('result') == 'loss'],
                  key=lambda game: -abs(game.get('drawdown') or 0))
    evidence = []
    for game in lost[:2]:
        evidence.append(_evidence(
            {'seq': str(game['game']), 'label': _game_label(game.get('date'), game.get('opponentName'), game['game'])},
            f"10 分钟领先 {int(game.get('leadAt10') or 0):,}，最终告负", t=600, approx=True))
    # 两种条件对位：十分钟领先 ≥1000 的局 vs 未达到的局，各自最终胜率。
    other = [game for game in ctx['cur_advantage']
             if game.get('leadAt10') is None or game['leadAt10'] < LEAD_AT10]
    other_wins = sum(1 for game in other if game.get('result') == 'win')
    cur_lost = cur['total'] - cur['wins']
    prev_lost = prev['total'] - prev['wins']
    if prev['total'] == 0:
        title = '本批十分钟领先后的兑现情况'
    elif cur_lost > 0 and cur_lost == prev_lost:
        # 两期未兑现局数相同，不能只凭胜率变化写成「丢掉优势的局变多了」。
        title = f"十分钟领先后，仍有 {cur_lost} 局未兑现"
    else:
        title = {'up': '十分钟领先后的兑现变好了',
                 'down': '十分钟领先后，丢掉优势的局变多了',
                 'flat': '十分钟领先后的兑现基本持平'}.get(tone, '十分钟领先后的兑现情况')
    conclusion = (f"本期 {cur['total']} 局十分钟经济领先 ≥1000，赢下 {cur['wins']} 局；"
                  + (f"{ctx['prev_word']} {prev['total']} 局赢下 {prev['wins']} 局。"
                     if prev['total'] else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'lead_hold', 'kind': 'advantage', 'theme': 'advantage',
        'label': '十分钟领先兑现', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['wins']}/{cur['total']}"},
            {'label': '上期', 'value': f"{prev['wins']}/{prev['total']}" if prev['total'] else '—'},
        ],
        'valueText': f"{cur['wins']}/{cur['total']}",
        'prevValueText': f"{prev['wins']}/{prev['total']}" if prev['total'] else None,
        'deltaText': delta, 'tone': tone,
        'sample': cur['total'], 'prevSample': prev['total'],
        'enough': cur['total'] >= MIN_SAMPLE and prev['total'] >= MIN_SAMPLE,
        'note': '十分钟时经济领先 ≥1000 的局，最终赢下几局',
        'change': change, 'changeKind': 'rate',
        'severity': 0.0 if cur['rate'] is None else max(0.0, 100 - cur['rate']),
        'evidence': evidence,
        'limitation': f"样本 {cur['total']} 局；经济点为约 30 秒一个的近似值，仅作本批观察。",
        'pair': _pair_stats('十分钟领先局胜率', cur['wins'], cur['total'],
                            '未建立领先局胜率', other_wins, len(other)),
        'foldSummary': f"领先 ≥1000 共 {cur['total']} 局，赢下 {cur['wins']} 局 · 最近本批对比",
        'stats': [
            {'label': '本期兑现', 'value': f"{cur['wins']}/{cur['total']}"},
            {'label': '上期兑现', 'value': f"{prev['wins']}/{prev['total']}" if prev['total'] else '—'},
        ],
        'advice': '回看丢掉优势的局，定位 10 分钟后第一次掉点的时间和资源交换，再决定是否继续压塔。',
    }
    return _finish(candidate, ctx, deep='matches')


def _comeback_stats(games):
    led = [game for game in (games or [])
           if game.get('maxLead') is not None and game['maxLead'] >= LEAD_AT10]
    comebacks = [game for game in led if game.get('comeback')]
    return {'total': len(led), 'comebacks': len(comebacks),
            'rate': _rate(len(comebacks), len(led)),
            'avgDrawdown': match_facts.mean([game.get('drawdown') for game in led]),
            'led': led, 'rows': comebacks}


def _cand_comeback(ctx):
    cur = _comeback_stats(ctx['cur_advantage'])
    if cur['total'] < 1:
        return None
    prev = _comeback_stats(ctx['prev_advantage'])
    change = None
    if cur['rate'] is not None and prev['rate'] is not None:
        change = cur['rate'] - prev['rate']  # 越高越差
    tone = _tone(change, higher_is_better=False)
    if prev['total'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur['comebacks'] - prev['comebacks']
        delta = (f'被翻盘多 {diff} 局' if diff > 0
                 else f'被翻盘少 {-diff} 局' if diff < 0 else '被翻盘局数持平')
    evidence = []
    for game in cur['rows'][:2]:
        evidence.append(_evidence(
            {'seq': str(game['game']), 'label': _game_label(game.get('date'), game.get('opponentName'), game['game'])},
            f"领先 {int(game.get('maxLead') or 0):,} 金币，"
            f"{game.get('drawdownAtClock') or ''} 时被打回去 {int(game.get('drawdown') or 0):,}",
            t=game.get('drawdownAt'), approx=True))
    counter = []
    for game in sorted([item for item in cur['led'] if not item.get('comeback')],
                       key=lambda item: (item.get('drawdown') or 0))[:2]:
        counter.append(_evidence(
            {'seq': str(game['game']), 'label': _game_label(game.get('date'), game.get('opponentName'), game['game'])},
            f"领先 {int(game.get('maxLead') or 0):,} 金币，守住了",
            t=game.get('maxLeadAt'), approx=True))
    if prev['total'] == 0:
        title = f"领先 1000 金币，输掉 {cur['comebacks']} 局"
    else:
        title = {'down': '领先后被翻盘的局变多了',
                 'up': '领先后被翻盘的局变少了',
                 'flat': '领先后被翻盘的比重基本持平'}.get(tone, '领先后被翻盘的比重变化')
    avg = cur['avgDrawdown']
    conclusion = (f"本期 {cur['total']} 局曾领先 1000 金币以上，其中 {cur['comebacks']} 局最后输了"
                  + (f"；输之前平均被打回去 {round(avg):,} 金币。" if avg is not None else '。')
                  + (f"{ctx['prev_word']} {prev['total']} 局里 {prev['comebacks']} 局。"
                     if prev['total'] else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'comeback', 'kind': 'advantage', 'theme': 'advantage',
        'label': '领先后的被翻盘', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['comebacks']}/{cur['total']}"},
            {'label': '上期', 'value': f"{prev['comebacks']}/{prev['total']}" if prev['total'] else '—'},
        ],
        'valueText': f"{cur['comebacks']}/{cur['total']}",
        'prevValueText': f"{prev['comebacks']}/{prev['total']}" if prev['total'] else None,
        'deltaText': delta, 'tone': tone,
        'sample': cur['total'], 'prevSample': prev['total'],
        'enough': cur['total'] >= MIN_SAMPLE and prev['total'] >= MIN_SAMPLE,
        'note': '曾领先 ≥1000 的局里，最终被翻盘的局数；平均回撤指达到最大领先后跌回去的金额',
        'change': change, 'changeKind': 'rate',
        'severity': cur['rate'] or 0.0,
        'evidence': evidence, 'counterexamples': counter,
        'limitation': '回撤是结果描述，不是因果；样本不足时只作本批观察。',
    }
    return _finish(candidate, ctx, deep='matches')


def _arrival_stats(rows):
    behind = [row for row in rows
              if row.get('advStart') is not None and row['advStart'] <= -1
              and row.get('killDiff') is not None]
    even = [row for row in rows
            if row.get('advStart') is not None and row['advStart'] >= 0
            and row.get('killDiff') is not None]
    behind_wins = sum(1 for row in behind if row.get('won'))
    even_wins = sum(1 for row in even if row.get('won'))
    own_participants = sum(row.get('ownParticipants') or 0 for row in rows)
    late = sum(row.get('lateJoins') or 0 for row in rows)
    behind_rate = _rate(behind_wins, len(behind))
    even_rate = _rate(even_wins, len(even))
    gap = (even_rate - behind_rate
           if behind_rate is not None and even_rate is not None else None)
    return {
        'behind': behind, 'even': even,
        'behindWins': behind_wins, 'evenWins': even_wins,
        'behindRate': behind_rate, 'evenRate': even_rate, 'gap': gap,
        'lateRate': round(late / own_participants * 100, 1) if own_participants else None,
        'decided': len(behind) + len(even),
    }


def _cand_fight_arrival(ctx):
    cur = _arrival_stats(ctx['cur_fights'])
    if not cur['behind'] or not cur['even'] or cur['gap'] is None:
        return None
    prev = _arrival_stats(ctx['prev_fights'])
    change = (cur['gap'] - prev['gap']
              if prev['gap'] is not None and prev['behind'] and prev['even'] else None)
    tone = _tone(change, higher_is_better=False)
    if prev['decided'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur['gap'] - (prev['gap'] or 0)
        delta = (f'落后团的胜率差扩大 {diff:.1f} 个百分点' if diff > 0
                 else f'落后团的胜率差缩小 {-diff:.1f} 个百分点' if diff < 0
                 else '落后团的胜率差持平')
    lost = sorted([row for row in cur['behind'] if not row.get('won')],
                  key=lambda row: (row.get('killDiff') or 0, row['startSec']))
    evidence = []
    for row in lost[:2]:
        evidence.append(_evidence(
            {'seq': row['game'], 'label': row['label']},
            f"开打时就少 {abs(int(row['advStart']))} 人，团战 "
            f"{row.get('ownKills', 0)}:{row.get('enemyKills', 0)} 打输",
            t=row['startSec'], approx=False))
    counter = []
    for row in [item for item in cur['behind'] if item.get('won')][:2]:
        counter.append(_evidence(
            {'seq': row['game'], 'label': row['label']},
            f"少 {abs(int(row['advStart']))} 人还赢下团战", t=row['startSec'], approx=False))
    # 本条只比较同一批团战里「少人 / 齐人」两种口径的胜率，不拿频次变化当结论。
    title = (f"少人接团胜率明显低于齐人团"
             if cur['gap'] >= 10 else '少人接团与齐人接团胜率接近')
    late_text = f"{cur['lateRate']:.1f}%" if cur['lateRate'] is not None else '—'
    conclusion = (f"本期 {len(cur['behind'])} 波团战开打时就少人，赢 {cur['behindWins']} 波；"
                  f"人齐的 {len(cur['even'])} 波赢 {cur['evenWins']} 波，"
                  f"胜率低 {cur['gap']:.1f} 个百分点。"
                  f"另有 {late_text} 的人次在开打 5 秒后才赶到。"
                  + (f"{ctx['prev_word']}少人团战 {len(prev['behind'])} 波赢 {prev['behindWins']} 波，"
                     f"胜率差 {prev['gap']:.1f} 个百分点。"
                     if prev['gap'] is not None else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'fight_arrival', 'kind': 'fight', 'theme': 'fight',
        'label': '团战到位与人数', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['behindWins']}/{len(cur['behind'])} 波"},
            {'label': '上期',
             'value': f"{prev['behindWins']}/{len(prev['behind'])} 波" if prev['behind'] else '—'},
        ],
        'valueText': f"{cur['behindWins']}/{len(cur['behind'])}",
        'prevValueText': (f"{prev['behindWins']}/{len(prev['behind'])}"
                          if prev['behind'] else None),
        'deltaText': delta, 'tone': tone,
        'sample': cur['decided'], 'prevSample': prev['decided'],
        'enough': cur['decided'] >= MIN_SAMPLE and prev['decided'] >= MIN_SAMPLE,
        'note': '开局 3 秒人数落后（≤-1）与不落后的团战胜率；迟到率按开始 5 秒后才到的人次占比',
        'change': change, 'changeKind': 'rate',
        'severity': max(0.0, cur['gap']),
        'evidence': evidence, 'counterexamples': counter,
        'limitation': '团战数据来自回放，只描述到位与结果的关系，不判断指挥失误；仅作本批观察。',
        'pair': _pair_stats('少人接团胜率', cur['behindWins'], len(cur['behind']),
                            '人员齐整胜率', cur['evenWins'], len(cur['even']), unit='波'),
        'foldSummary': f"开局少人团 {len(cur['behind'])} 波，人齐团 {len(cur['even'])} 波 · 最近本批对比",
        'stats': [
            {'label': '少人接团', 'value': f"{cur['behindRate']:.1f}%",
             'title': f"{cur['behindWins']} 胜 / {len(cur['behind'])} 波"},
            {'label': '齐人接团', 'value': f"{cur['evenRate']:.1f}%",
             'title': f"{cur['evenWins']} 胜 / {len(cur['even'])} 波"},
        ],
        'advice': '优先检查开团前的人员位置、支援距离，以及关键队员未到场时的开团决策。',
    }
    return _finish(candidate, ctx, deep='matches')


def _trade_stats(rows):
    decided = [row for row in rows if row.get('killDiff') is not None]
    total = sum(row['killDiff'] for row in decided)
    return {
        'decided': decided,
        'avg': round(total / len(decided), 2) if decided else None,
    }


def _cand_fight_trade(ctx):
    cur = _trade_stats(ctx['cur_fights'])
    if not cur['decided'] or cur['avg'] is None:
        return None
    prev = _trade_stats(ctx['prev_fights'])
    change = _ratio_change(cur['avg'], prev['avg'])
    tone = _tone(change, eps=5.0)
    bad = sorted([row for row in cur['decided'] if row['killDiff'] <= -2],
                 key=lambda row: (row['killDiff'], row['startSec']))
    if prev['decided'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = (cur['avg'] or 0) - (prev['avg'] or 0)
        if abs(diff) < 0.1:
            delta = '场均击杀差持平'
        elif diff > 0:
            delta = f'场均击杀差多 {diff:.1f}'
        else:
            delta = f'场均击杀差少 {-diff:.1f}'
    evidence = []
    for row in bad[:2]:
        evidence.append(_evidence(
            {'seq': row['game'], 'label': row['label']},
            f"团战击杀 {row.get('ownKills', 0)}:{row.get('enemyKills', 0)}（差 {int(row['killDiff'])}）",
            t=row['startSec'], approx=False))
    counter = []
    for row in sorted(cur['decided'], key=lambda item: -item['killDiff'])[:2]:
        if row['killDiff'] > 0:
            counter.append(_evidence(
                {'seq': row['game'], 'label': row['label']},
                f"团战击杀 {row.get('ownKills', 0)}:{row.get('enemyKills', 0)}",
                t=row['startSec'], approx=False))
    if prev['decided'] == 0:
        title = '本批团战的击杀交换情况'
    else:
        title = {'up': '团战的击杀交换变好了',
                 'down': '团战的击杀交换变差了',
                 'flat': '团战的击杀交换基本持平'}.get(tone, '团战的击杀交换变化')
    conclusion = (f"本期 {len(cur['decided'])} 场有击杀的团战，场均击杀差 {cur['avg']:+.2f}；"
                  + (f"{ctx['prev_word']}场均 {prev['avg']:+.2f}。"
                     if prev['avg'] is not None else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'fight_trade', 'kind': 'fight', 'theme': 'fight',
        'label': '团战击杀交换', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['avg']:+.2f}"},
            {'label': '上期', 'value': f"{prev['avg']:+.2f}" if prev['avg'] is not None else '—'},
        ],
        'valueText': f"{cur['avg']:+.2f}",
        'prevValueText': f"{prev['avg']:+.2f}" if prev['avg'] is not None else None,
        'deltaText': delta, 'tone': tone,
        'sample': len(cur['decided']), 'prevSample': len(prev['decided']),
        'enough': (len(cur['decided']) >= MIN_SAMPLE
                   and len(prev['decided']) >= MIN_SAMPLE),
        'note': '团战击杀差（我方 − 对方）的场均值；0 击杀的团战不计胜负',
        'change': change, 'changeKind': 'ratio',
        'severity': max(0.0, -(cur['avg'] or 0) * 20),
        'evidence': evidence, 'counterexamples': counter,
        'limitation': '只统计回放里有击杀判定的团战；仅作本批观察。',
    }
    return _finish(candidate, ctx, deep='matches')


def _objective_stats(entries):
    own_total = enemy_total = games = converted = 0
    rows = []
    for item in entries:
        game = item['game']
        if not game:
            continue
        events = [event for event in match_facts.objective_events(game)
                  if event['kind'] in ('resource', 'building')]
        own = [event for event in events if event['camp'] == 'own']
        enemy = [event for event in events if event['camp'] == 'enemy']
        games += 1
        own_total += len(own)
        enemy_total += len(enemy)
        wins = [fight for fight in match_facts.fight_events(game)
                if fight.get('killDiff') is not None and fight['killDiff'] > 0]
        game_converted = 0
        for fight in wins:
            end = fight.get('endSec')
            if end is None:
                continue
            if any(event['t'] >= end for event in own
                   if event['t'] is not None and event['t'] <= end + 120):
                game_converted += 1
        converted += game_converted
        rows.append({'entry': item, 'own': len(own), 'enemy': len(enemy),
                     'converted': game_converted})
    return {
        'games': games, 'own': own_total, 'enemy': enemy_total,
        'avg': round(own_total / games, 1) if games else None,
        'converted': converted, 'rows': rows,
    }


def _cand_objective(ctx):
    cur = _objective_stats(ctx['cur'])
    if not cur['games'] or cur['avg'] is None:
        return None
    prev = _objective_stats(ctx['prev'])
    change = _ratio_change(cur['avg'], prev['avg'])
    tone = _tone(change, eps=5.0)
    if prev['games'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = (cur['avg'] or 0) - (prev['avg'] or 0)
        delta = (f'每局多拿 {diff:.1f} 个' if diff > 0.05
                 else f'每局少拿 {-diff:.1f} 个' if diff < -0.05 else '每局数量持平')
    ahead_wins = ahead_total = behind_wins = behind_total = 0
    for row in cur['rows']:
        result = row['entry'].get('result')
        if result not in ('win', 'loss'):
            continue
        if row['own'] >= row['enemy']:
            ahead_total += 1
            ahead_wins += result == 'win'
        else:
            behind_total += 1
            behind_wins += result == 'win'
    behind = sorted([row for row in cur['rows'] if row['own'] < row['enemy']],
                    key=lambda row: (row['own'] - row['enemy'], row['entry']['date']))
    evidence = []
    for row in behind[:2]:
        item = row['entry']
        evidence.append(_evidence(
            item, f"我方 {row['own']} 个、对手 {row['enemy']} 个资源/塔",
            t=None, approx=False))
    counter = []
    for row in sorted(cur['rows'], key=lambda row: -row['own'])[:2]:
        if row['own'] > row['enemy']:
            counter.append(_evidence(
                row['entry'], f"我方 {row['own']} 个、对手 {row['enemy']} 个资源/塔"))
    if prev['games'] == 0:
        title = '本批资源/塔的获取情况'
    elif ahead_total < behind_total:
        title = '本期龙塔争夺占优局数偏少'
    else:
        title = {'up': '龙塔争夺的收益变好了',
                 'down': '龙塔争夺的收益变差了',
                 'flat': '龙塔争夺的收益基本持平'}.get(tone, '龙塔争夺的收益变化')
    total = cur['own'] + cur['enemy']
    conclusion = (f"本期每局拿到 {cur['avg']:.1f} 个资源/塔（我方 {cur['own']}、对手 {cur['enemy']}），"
                  f"团战后 120 秒内转成推塔/控龙 {cur['converted']} 次；"
                  + (f"{ctx['prev_word']}每局 {prev['avg']:.1f} 个。"
                     if prev['avg'] is not None else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'objective', 'kind': 'objective', 'theme': 'objective',
        'label': '龙塔资源收益', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['avg']:.1f} 个/局"},
            {'label': '上期', 'value': f"{prev['avg']:.1f} 个/局" if prev['avg'] is not None else '—'},
        ],
        'valueText': f"{cur['avg']:.1f} 个/局",
        'prevValueText': f"{prev['avg']:.1f} 个/局" if prev['avg'] is not None else None,
        'deltaText': delta, 'tone': tone,
        'sample': cur['games'], 'prevSample': prev['games'],
        'enough': cur['games'] >= MIN_SAMPLE and prev['games'] >= MIN_SAMPLE,
        'note': '每局拿到的资源/建筑数（龙、塔等）；龙团后 120 秒内转为推塔/控龙另计',
        'change': change, 'changeKind': 'ratio',
        'severity': max(0.0, (cur['enemy'] - cur['own']) / total * 100) if total else 0.0,
        'evidence': evidence, 'counterexamples': counter,
        'limitation': '资源/建筑来自回放关键事件；敌方阵营未知的事件不计入双方；仅作本批观察。',
        'pair': _pair_stats('我方龙塔占优局胜率', ahead_wins, ahead_total,
                            '我方龙塔落后局胜率', behind_wins, behind_total),
        'foldSummary': f"我方龙塔占优 {ahead_total} 局、落后 {behind_total} 局 · 最近本批对比",
        'stats': [
            {'label': '占优局', 'value': f"{ahead_total}/{cur['games']}"},
            {'label': '落后局', 'value': f"{behind_total}/{cur['games']}"},
        ],
        'advice': '对照落后局的龙团时间点，先确认是视野缺失还是决策犹豫，再安排提前站位。',
    }
    return _finish(candidate, ctx, deep='matches')


def _comp_stats(lineups, entries):
    pairs = []
    for item in entries:
        lineup = lineups.get(item['seq']) or {}
        jungle = lineup.get('打野')
        mid = lineup.get('中路')
        if jungle and mid:
            pairs.append((item, tuple(sorted((jungle, mid)))))
    if not pairs:
        return None
    counter = Counter(pair for _, pair in pairs)
    top, count = counter.most_common(1)[0]
    return {
        'pairs': pairs, 'counter': counter, 'top': top, 'topCount': count,
        'games': len(pairs), 'distinct': len(counter),
        'share': round(count / len(pairs) * 100, 1),
        'rows': [item for item, pair in pairs if pair == top],
    }


def _cand_comp(ctx):
    cur = _comp_stats(ctx['cur_lineups'], ctx['cur'])
    if not cur or cur['games'] < 1:
        return None
    prev = _comp_stats(ctx['prev_lineups'], ctx['prev'])
    change = (cur['share'] - prev['share']) if prev and prev['games'] else None
    tone = _tone(change)
    if not prev or prev['games'] == 0:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur['share'] - prev['share']
        delta = ('更集中在同一套组合' if diff > COMPARABLE_EPS
                 else '组合更分散' if diff < -COMPARABLE_EPS else '集中度持平')
    evidence = []
    for item in cur['rows'][:2]:
        evidence.append(_evidence(
            item, f"中野 {cur['top'][0]} + {cur['top'][1]}", t=None, approx=False))
    counter = []
    for pair, _count in cur['counter'].most_common(3):
        if pair == cur['top']:
            continue
        item = next((entry for entry, entry_pair in cur['pairs'] if entry_pair == pair), None)
        if item is not None:
            counter.append(_evidence(item, f"另一套中野 {pair[0]} + {pair[1]}"))
        if len(counter) >= 2:
            break
    if not prev or prev['games'] == 0:
        title = '本批中野组合的使用情况'
    else:
        title = {'up': '阵容更集中在中野',
                 'down': '阵容更分散了',
                 'flat': '中野组合的集中度基本持平'}.get(tone, '中野组合的集中度变化')
    conclusion = (f"本期 {cur['games']} 局用了 {cur['distinct']} 套中野组合，"
                  f"最多的一套「{cur['top'][0]} + {cur['top'][1]}」出现 {cur['topCount']} 局；"
                  + (f"{ctx['prev_word']} {prev['games']} 局用了 {prev['distinct']} 套，"
                     f"最多的一套 {prev['topCount']} 局。"
                     if prev and prev['games'] else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'comp', 'kind': 'comp', 'theme': 'lineup',
        'label': '阵容体系集中度', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{cur['topCount']}/{cur['games']} 局"},
            {'label': '上期',
             'value': f"{prev['topCount']}/{prev['games']} 局" if prev and prev['games'] else '—'},
        ],
        'valueText': f"{cur['topCount']}/{cur['games']} 局",
        'prevValueText': (f"{prev['topCount']}/{prev['games']} 局"
                          if prev and prev['games'] else None),
        'deltaText': delta, 'tone': tone,
        'sample': cur['games'], 'prevSample': prev['games'] if prev else 0,
        'enough': (prev is not None and cur['games'] >= MIN_SAMPLE
                   and prev['games'] >= MIN_SAMPLE),
        'note': '按中野双人组统计阵容集中度；同一套组合出现越多，体系越集中',
        'change': change, 'changeKind': 'rate',
        'severity': 0.0,
        'evidence': evidence, 'counterexamples': counter,
        'limitation': '只按中野双人组归类，不评价英雄强度；仅作本批观察。',
    }
    # 阵容组合专题页已删除，证据回对局列表（保留周期范围）。
    return _finish(candidate, ctx, deep='bp')


def _farm_death_rows(facts, entries):
    """我方发育路单局阵亡 ≥3 的面板行（终局面板口径，逐局逐人）。"""
    allowed = {item['seq'] for item in entries}
    rows = []
    for row in facts.get('rows') or []:
        if not isinstance(row, dict) or row.get('side') != 'own':
            continue
        if str(row.get('seq') or '') not in allowed:
            continue
        if (row.get('lane') or '') != '发育路':
            continue
        deaths = row.get('deaths')
        if isinstance(deaths, int) and deaths >= 3:
            rows.append(row)
    return rows


def _cand_roster(ctx):
    games = len(ctx['cur'])
    death_rows = _farm_death_rows(ctx['facts'], ctx['cur'])
    seqs = []
    for row in death_rows:
        seq = str(row.get('seq') or '')
        if seq and seq not in seqs:
            seqs.append(seq)
    if games < 1 or not seqs:
        return None
    prev_games = len(ctx['prev'])
    prev_seqs = {str(row.get('seq') or '')
                 for row in _farm_death_rows(ctx['facts'], ctx['prev'])}
    cur_share = round(len(seqs) / games * 100, 1)
    prev_share = round(len(prev_seqs) / prev_games * 100, 1) if prev_games else None
    change = (cur_share - prev_share) if prev_share is not None else None
    tone = _tone(change, higher_is_better=False)
    if not prev_games:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur_share - prev_share
        delta = (f'发育路死亡偏多的局占比多 {diff:.1f} 个百分点' if diff > 0
                 else f'发育路死亡偏多的局占比少 {-diff:.1f} 个百分点' if diff < 0
                 else '发育路死亡偏多的局占比持平')
    index = ctx['cur_index']
    evidence = []
    for row in sorted(death_rows, key=lambda item: -(item.get('deaths') or 0)):
        entry = index.get(str(row.get('seq') or ''))
        if not entry:
            continue
        who = row.get('name') or row.get('hero') or '发育路'
        note = f"{who} 一局死 {row.get('deaths')} 次"
        if isinstance(row.get('gold'), int):
            note += f"，结束时经济 {row['gold']:,} 金币"
        evidence.append(_evidence(entry, note))
        if len(evidence) >= 2:
            break
    # 两种条件对位：发育路单局死亡 ≥3 的局 vs 不足 3 次的局，各自胜率。
    deaths_by_seq = {}
    for row in death_rows:
        seq = str(row.get('seq') or '')
        deaths_by_seq[seq] = max(deaths_by_seq.get(seq, 0), row.get('deaths') or 0)
    worst = max(death_rows, key=lambda row: row.get('deaths') or 0) if death_rows else None
    heroes = []
    for row in sorted(death_rows, key=lambda item: -(item.get('deaths') or 0)):
        hero = row.get('hero')
        if hero and hero not in heroes:
            heroes.append(hero)
        if len(heroes) >= 4:
            break
    high_wins = high_total = low_wins = low_total = 0
    for entry in ctx['cur']:
        if entry.get('result') not in ('win', 'loss'):
            continue
        if deaths_by_seq.get(str(entry.get('seq') or ''), 0) >= 3:
            high_total += 1
            high_wins += entry['result'] == 'win'
        else:
            low_total += 1
            low_wins += entry['result'] == 'win'
    diff_games = len(prev_seqs) - len(seqs) if prev_games else 0
    if not prev_games:
        title = f"{len(seqs)} 局里发育路一局死 3 次以上"
    elif diff_games > 0:
        title = f'发育路高死亡对局减少 {diff_games} 场'
    elif diff_games < 0:
        title = f'发育路高死亡对局增加 {-diff_games} 场'
    else:
        title = '发育路高死亡对局数基本持平'
    conclusion = (f"本期 {games} 局里有 {len(seqs)} 局，发育路一局死 3 次以上"
                  f"（共 {len(death_rows)} 人次）；"
                  + (f"{ctx['prev_word']} {prev_games} 局里 {len(prev_seqs)} 局。"
                     if prev_games else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'roster', 'kind': 'roster', 'theme': 'lineup',
        'label': '发育路死亡波动', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{len(seqs)}/{games} 局"},
            {'label': '上期', 'value': f"{len(prev_seqs)}/{prev_games} 局" if prev_games else '—'},
        ],
        'valueText': f"{len(seqs)}/{games} 局",
        'prevValueText': f"{len(prev_seqs)}/{prev_games} 局" if prev_games else None,
        'deltaText': delta, 'tone': tone,
        'sample': games, 'prevSample': prev_games,
        'enough': games >= MIN_SAMPLE and prev_games >= MIN_SAMPLE,
        'note': '发育路（射手位）单局死亡 ≥3 的局占比；死亡数来自终局面板',
        'change': change, 'changeKind': 'rate',
        'severity': cur_share,
        'evidence': evidence,
        'limitation': '只描述分路死亡数量，不评价选手；仅作本批观察。',
        'pair': _pair_stats('发育路高死亡局胜率', high_wins, high_total,
                            '发育路低死亡局胜率', low_wins, low_total),
        'player': ({
            'name': (worst.get('nickname') or worst.get('name')
                     or worst.get('hero') or '发育路'),
            'hero': worst.get('hero') or '', 'lane': '发育路',
            'deaths': worst.get('deaths'),
        } if death_rows else None),
        'foldSummary': f"单局死亡 ≥3 次共 {len(death_rows)} 人次，最近本批对比",
        'stats': [
            {'label': '本期高死亡', 'value': f"{len(seqs)}/{games} 局"},
            {'label': '上期高死亡', 'value': f"{len(prev_seqs)}/{prev_games} 局" if prev_games else '—'},
        ],
        'advice': '回看高死亡局的死亡回放，先看被抓前的兵线位置与视野，再定保护或换线策略。',
        'heroes': heroes,
    }
    return _finish(candidate, ctx, deep='players')


def _cand_coverage(ctx):
    entries = ctx['cur']
    panel_only = ctx['cur_panel_only']
    games = len(entries)
    panel_games = games + len(panel_only)
    if panel_games < 1:
        return None
    timeline = sum(1 for item in entries if item['hasTimeline'])
    missing = len(panel_only)
    missing_timeline = games - timeline
    prev_games = len(ctx['prev'])
    prev_panel_games = prev_games + len(ctx['prev_panel_only'])
    prev_missing = len(ctx['prev_panel_only'])
    cur_share = round(missing / panel_games * 100, 1)
    prev_share = (round(prev_missing / prev_panel_games * 100, 1)
                  if prev_panel_games else None)
    change = (cur_share - prev_share) if prev_share is not None else None
    tone = _tone(change, higher_is_better=False)
    if not prev_panel_games:
        delta = f'{ctx["prev_short"]}暂无可比数据'
    else:
        diff = cur_share - prev_share
        delta = (f'缺回放占比多 {diff:.1f} 个百分点' if diff > 0
                 else f'缺回放占比少 {-diff:.1f} 个百分点' if diff < 0
                 else '缺回放占比持平')
    evidence = []
    for item in panel_only:
        evidence.append(_evidence(item, '只有终局面板、没有比赛过程'))
        if len(evidence) >= 2:
            break
    if not prev_panel_games:
        title = f"本批有 {missing} 局只有面板、没有过程"
    else:
        title = {'down': '缺回放的局变多了',
                 'up': '缺回放的局变少了',
                 'flat': '缺回放的比重基本持平'}.get(tone, '缺回放的比重变化')
    conclusion = (f"本期面板 {panel_games} 局里 {games} 局有回放、{missing} 局只有面板"
                  + (f"，{missing_timeline} 局回放缺时间轴" if missing_timeline else '')
                  + '；'
                  + (f"{ctx['prev_word']} {prev_panel_games} 局里 {prev_missing} 局缺回放。"
                     if prev_panel_games else f"{ctx['prev_short']}暂无可比数据。"))
    candidate = {
        'id': 'coverage', 'kind': 'coverage', 'theme': 'coverage',
        'label': '数据覆盖', 'title': title, 'conclusion': conclusion,
        'numbers': [
            {'label': '本期', 'value': f"{missing}/{panel_games} 局"},
            {'label': '上期',
             'value': f"{prev_missing}/{prev_panel_games} 局" if prev_panel_games else '—'},
        ],
        'valueText': f"{missing}/{panel_games} 局",
        'prevValueText': (f"{prev_missing}/{prev_panel_games} 局"
                          if prev_panel_games else None),
        'deltaText': delta, 'tone': tone,
        'sample': panel_games, 'prevSample': prev_panel_games,
        'enough': panel_games >= MIN_SAMPLE and prev_panel_games >= MIN_SAMPLE,
        'note': '有面板无回放的局数；缺时间轴（回放没有经济/事件）另计',
        'change': change, 'changeKind': 'rate',
        'severity': cur_share,
        'evidence': evidence,
        'limitation': '覆盖不足会限制过程类结论；补回放后本卡自动消失。',
    }
    return _finish(candidate, ctx, deep='sources')


CANDIDATES = (
    _cand_lead_hold, _cand_comeback, _cand_fight_arrival, _cand_fight_trade,
    _cand_objective, _cand_comp, _cand_roster, _cand_coverage,
)

LEVEL_PRIORITY = ('lead_hold', 'fight_arrival', 'objective', 'comp', 'roster',
                  'coverage', 'comeback', 'fight_trade')


def build_candidates(ctx):
    out = []
    for builder in CANDIDATES:
        try:
            candidate = builder(ctx)
        except Exception:  # noqa: BLE001 - 单个信号算不出来不影响整张简报
            candidate = None
        if candidate:
            out.append(candidate)
    return out


# ---------------------------------------------------------------------------
# 指标与发现
# ---------------------------------------------------------------------------
def _metric(candidate):
    return {
        'id': candidate['id'],
        'label': candidate['label'],
        'valueText': candidate['valueText'],
        'prevValueText': candidate['prevValueText'],
        'deltaText': candidate['deltaText'],
        'tone': candidate['tone'],
        'sample': candidate['sample'],
        'prevSample': candidate['prevSample'],
        'enough': bool(candidate['enough']),
        'note': candidate['note'],
    }


def select_metrics(candidates):
    """有可比变化时取变化最大的 4 个；否则取 3 个整期水平项。"""
    comparables = [item for item in candidates
                   if item.get('change') is not None
                   and abs(float(item['change'])) >= COMPARABLE_EPS]
    if comparables:
        ranked = sorted(comparables, key=lambda item: (-item['score'], item['id']))
        return [_metric(item) for item in ranked[:4]]
    chosen = []
    by_id = {item['id']: item for item in candidates}
    for candidate_id in LEVEL_PRIORITY:
        candidate = by_id.get(candidate_id)
        if candidate and candidate['sample'] >= 1:
            chosen.append(candidate)
        if len(chosen) >= 3:
            break
    if not chosen:
        chosen = sorted(candidates, key=lambda item: -item['sample'])[:3]
    return [_metric(item) for item in chosen if item['sample'] >= 1]


def select_findings(candidates, *, exclude_kinds=()):
    """同 kind 至多 1 条、同主题至多 1 条，按价值分排序；不固定条数（前端区块内滚动）。

    首页不展示 coverage（只有面板 / 缺回放）这类数据质量提醒：
    它属于底部「数据覆盖」，不是教练要看的比赛内容。
    """
    excluded = set(exclude_kinds)
    pool = [item for item in candidates
            if item['kind'] not in excluded
            and item['sample'] >= 2 and item['evidence']
            and item['score'] >= FINDING_MIN_SCORE]
    pool.sort(key=lambda item: (-item['score'], KIND_ORDER.get(item['kind'], 9), item['id']))
    out, kinds, themes = [], set(), set()
    for item in pool:
        if item['kind'] in kinds or item['theme'] in themes:
            continue
        out.append({
            'id': (f"{item['id']}_{item['tone']}"
                   if item['tone'] in ('up', 'down', 'flat') else item['id']),
            'kind': item['kind'],
            'title': item['title'],
            'conclusion': item['conclusion'],
            'numbers': list(item['numbers'])[:2],
            'stats': list(item.get('stats') or [])[:2],
            'n': item['sample'],
            'enough': bool(item['enough']),
            'evidence': item['evidence'][:2],
            'counterexamples': item['counterexamples'][:2],
            'primary_destination': item['primary_destination'],
            'deep_destination': item['deep_destination'],
            'limitation': item['limitation'],
            'statusTag': ('样本较少' if not item['enough']
                          else STATUS_BY_TONE.get(item['tone'], '持续观察')),
            'categoryTag': CATEGORY_BY_ID.get(item['id'], '本批观察'),
            'foldSummary': item.get('foldSummary') or item.get('note') or '',
            'advice': item.get('advice') or '',
            'pair': item.get('pair'),
            'player': item.get('player'),
            'heroes': list(item.get('heroes') or []),
        })
        kinds.add(item['kind'])
        themes.add(item['theme'])
    return out


# ---------------------------------------------------------------------------
# 摘要 / 覆盖 / 下一场 / 空态
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 首页指标：本期训练赛总览（过程指标留在对局分析页，不搬上首页）
# ---------------------------------------------------------------------------
LANE_ORDER = {'对抗路': 0, '中路': 1, '发育路': 2, '打野': 3, '游走': 4}


def _mmss(seconds):
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ''
    total = int(seconds)
    return f'{total // 60}:{total % 60:02d}'


def _k(value):
    """经济差写成完整金币数（教练不需要自己换算 k）。"""
    if value is None:
        return ''
    return f'{"+" if value >= 0 else "-"}{abs(value):,.0f} 金币'


@lru_cache(maxsize=1)
def _hero_icon_map():
    """英雄名 → /catalog/icons/hero-<id>.png；目录缺失时返回空表，前端退回首字。"""
    path = Path(__file__).resolve().parent / 'resources' / 'catalog.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    entries = payload.get('entries') if isinstance(payload, dict) else payload
    return {
        str(entry.get('name')): str(entry.get('icon') or '')
        for entry in (entries or [])
        if entry.get('kind') == 'hero' and entry.get('name') and entry.get('icon')
    }


def _team_totals(panel):
    """终局面板里我方/对手的团队总量（没有面板就是 None，不补 0）。"""
    panel = panel if isinstance(panel, dict) else {}
    own = [row for row in (panel.get('ownRoster') or []) if isinstance(row, dict)]
    enemy = [row for row in (panel.get('enemyRoster') or []) if isinstance(row, dict)]

    def total(rows, key):
        values = [row.get(key) for row in rows]
        values = [value for value in values if isinstance(value, (int, float))]
        return sum(values) if values else None

    own_gold, enemy_gold = total(own, 'gold'), total(enemy, 'gold')
    own_damage, enemy_damage = total(own, 'heroDamage'), total(enemy, 'heroDamage')
    return {
        'goldDiff': ((own_gold - enemy_gold)
                     if own_gold is not None and enemy_gold is not None else None),
        'damagePct': (round(own_damage / (own_damage + enemy_damage) * 100, 1)
                      if own_damage and enemy_damage
                      and own_damage + enemy_damage > 0 else None),
    }


def _objective_losses(game):
    """对手拿到的关键龙 / 推掉的防御塔；没有事件数据就是 0。"""
    dragons = towers = 0
    for event in game.get('events') or []:
        item = match_facts.format_objective(event, game.get('ownCamp'))
        if item['camp'] != 'enemy':
            continue
        if item['kind'] == 'resource' and item['name'] in DRAGON_NAMES:
            dragons += 1
        elif item['kind'] == 'building' and item['name'] == '防御塔':
            towers += 1
    return dragons, towers


def _game_stats(game, panel=None):
    """一局里教练复盘必看的几个直白数字（只读回放事实表 + 终局面板）。"""
    duration = game.get('duration')
    own_diff = [value for value in (game.get('ownDiff') or [])
                if isinstance(value, (int, float))]
    at10 = (match_facts.value_at(600, own_diff, duration)
            if own_diff and duration else None)
    camp_of = game.get('objToCamp') or {}
    own_num = match_facts.CAMP_CODE_REV.get(str(game.get('ownCamp') or ''))
    deaths = sum(1 for event in (game.get('deaths') or [])
                 if own_num and camp_of.get(str(event.get('objID') or '')) == own_num)
    icons = _hero_icon_map()

    def roster_of(side):
        players = [item for item in (game.get('players') or [])
                   if item.get('side') == side]
        players.sort(key=lambda item: LANE_ORDER.get(item.get('lane'), 9))
        out = []
        for item in players:
            hero = str(item.get('hero') or '')
            if not hero:
                continue
            final = item.get('final') or {}
            out.append({
                'name': hero,
                'player': str(item.get('nickname') or ''),
                'lane': str(item.get('lane') or ''),
                'icon': icons.get(hero, ''),
                'kills': final.get('kills'),
                'deaths': final.get('deaths'),
                'assists': final.get('assists'),
                'gold': final.get('totalGold'),
                'participation': final.get('participation'),
            })
        return out

    roster_players = roster_of('own')
    foe_players = roster_of('enemy')
    peak = max(own_diff) if own_diff else None
    low = min(own_diff) if own_diff else None
    # 领先被打回去：从最高点跌到最低点的金额（没有经济曲线就是 0）
    drawdown = 0
    if own_diff and peak is not None:
        drawdown = max(0.0, peak - min(own_diff[own_diff.index(peak):]))
    fights = match_facts.fight_events(game)
    decided_fights = [fight for fight in fights if fight.get('won') is not None]
    team = _team_totals(panel)
    dragons_lost, towers_lost = _objective_losses(game)
    return {
        'duration': duration,
        'at10': at10,
        'peak': peak,
        'low': low,
        'drawdown': drawdown,
        'deaths': deaths,
        'fights': len(game.get('fights') or []),
        'fightTotal': len(decided_fights),
        'fightLosses': sum(1 for fight in decided_fights if not fight.get('won')),
        'goldDiff': team.get('goldDiff'),
        'damagePct': team.get('damagePct'),
        'dragonsLost': dragons_lost,
        'towersLost': towers_lost,
        'roster': ' · '.join(item['name'] for item in roster_players),
        'rosterPlayers': roster_players,
        'foePlayers': foe_players,
    }


WATCH_TAIL = {
    'deficit': '先看这几波怎么被拉开',
    'deaths': '先看这几波是怎么被抓的',
    'giveback': '先看优势是怎么丢的',
    'fight': '先看开团前的站位和人手',
    'at10': '先看开局这几分钟',
    'duration': '先看哪几波拖住了节奏',
    'dragon': '先看龙团前的站位和优先目标',
    'tower': '先看塔是怎么掉的',
    'gold': '先看经济是从哪一波开始被拉开的',
    'damage': '先看团战时的输出环境',
}


def _watch_core(field, stats):
    """这局在这项上的主句，只用这局自己的数字。"""
    if field == 'deaths':
        return f"我方掉点 {stats['deaths']} 次"
    if field == 'giveback':
        return (f"领先最多 {abs(stats['peak']):,.0f} 金币，"
                f"后来被反超到落后 {abs(stats['low']):,.0f} 金币")
    if field == 'fight':
        return f"打输 {stats['fightLosses']} 波团战"
    if field == 'at10':
        at10 = stats.get('at10')
        if at10 is None:
            return ''
        return f"10 分钟{'领先' if at10 >= 0 else '落后'} {abs(at10):,.0f} 金币"
    if field == 'duration':
        # 时长已经写在 pace 里，不重复。
        return ''
    if field == 'dragon':
        return f"关键龙被对手拿到 {stats.get('dragonsLost') or 0} 条"
    if field == 'tower':
        return f"被对手推掉 {stats.get('towersLost') or 0} 座塔"
    if field == 'gold':
        diff = stats.get('goldDiff')
        if diff is None:
            return ''
        return (f"结束时经济{'领先' if diff >= 0 else '落后'} "
                f"{abs(diff):,.0f} 金币")
    if field == 'damage':
        pct = stats.get('damagePct')
        if pct is None:
            return ''
        return f"团队输出只占 {pct:.1f}%"
    low = stats.get('low')
    if low is not None and low < 0:
        return f"最多落后 {abs(low):,.0f} 金币"
    at10 = stats.get('at10')
    if at10 is not None:
        return f"10 分钟{'领先' if at10 >= 0 else '落后'} {abs(at10):,.0f} 金币"
    return ''


def _watch_sentence(stats, lost, longest, shortest, field='deficit', result=None):
    """用这局自己的数字说一句「为什么值得看」，不写术语、不写免责。"""
    duration = stats['duration']
    minutes = int(duration) // 60 if isinstance(duration, (int, float)) and duration > 0 else 0
    if not minutes:
        return '本期打的一局，可回看完整过程。'
    if longest and shortest and longest != shortest and duration == longest:
        pace = f'本期最长的一局，打了 {minutes} 分钟'
    elif longest and shortest and longest != shortest and duration == shortest:
        pace = f'本期最短的一局，{minutes} 分钟就结束'
    else:
        pace = f'打了 {minutes} 分钟'
    core = _watch_core(field, stats)
    # 落后翻盘的局，复盘重点是「怎么翻回来」；被翻盘的局，重点是「优势怎么丢的」。
    if field == 'deficit' and result == 'win':
        tail = '最后翻回来了，先看中段怎么被拉开、后期怎么打回来'
    elif field == 'deficit' and (stats.get('peak') or 0) >= WATCH_COMEBACK_MIN:
        tail = '先看优势是怎么丢的'
    else:
        tail = WATCH_TAIL.get(field) or ('后面没守住，先看后期' if lost else '可回看完整过程')
    return f'{pace}，{core}，{tail}。' if core else f'{pace}，{tail}。'


def _own_heroes(entries):
    counts = Counter()
    for item in entries:
        for player in (item.get('game') or {}).get('players') or []:
            if player.get('side') == 'own' and player.get('hero'):
                counts[str(player['hero'])] += 1
    return counts


# ---------------------------------------------------------------------------
# 首页赛训指标：基本盘 + 比率 + 逐条资源控制率
# ---------------------------------------------------------------------------
DRAGON_NAMES = ('暗影主宰', '暴君', '暗影暴君')
# 逐条展示的资源名。旧版把它们合成「关键龙控制率」，看不出到底是哪种龙。
OBJECTIVE_NAMES = ('暴君', '暗影暴君', '主宰', '暗影主宰')
OBJECTIVE_MID = {'暴君': 'tyrant_rate', '暗影暴君': 'elder_dragon_rate',
                 '主宰': 'baron_rate', '暗影主宰': 'elder_baron_rate'}
DYNAMIC_VALUE = {'dragon': 40, 'first_tower': 30, 'behind_comeback': 20, 'lead_drawdown': 10}


def _at10(game):
    """十分钟经济差（我方视角，金）；10 分钟内结束或没有经济曲线给 None。"""
    own = [value for value in (game.get('ownDiff') or [])
           if isinstance(value, (int, float))]
    duration = game.get('duration')
    if not own or not isinstance(duration, (int, float)) or duration < 600:
        return None
    return match_facts.value_at(600, own, duration)


def _pct(part, total):
    return round(part / total * 100, 1) if total else None


def _fmt_pct(value):
    return f'{value:.1f}%' if value is not None else '—'


def _fmt_econ(value):
    if value is None:
        return '—'
    return f'{"+" if value >= 0 else "-"}{abs(value):,.0f} 金币'


def _metric_card(*, mid, label, valueText, prevValueText, sample, prevSample, total,
                 change, changeKind, higherIsBetter, note, href, enough, unit='局',
                 valueSub=None, rank=None, share=None):
    """8 项指标统一结构：本期 / 上期 / 变化 / 有效数据量 / 口径 / 同批排名。"""
    coverage = (f'{sample}/{max(total, sample)} {unit}' if total
                else f'{sample} {unit}')
    # 条：有排名就画同批百分位（能横向比较），没有排名就画本项比例。
    bar = None
    if rank and isinstance(rank.get('percentile'), (int, float)):
        bar = {'pct': round(float(rank['percentile']), 1),
               'tier': rank.get('tier') or 'mid', 'mode': 'rank'}
    elif share is not None:
        bar = {'pct': max(0.0, min(100.0, round(float(share), 1))),
               'tier': '', 'mode': 'value'}
    if sample == 0:
        deltaText, tone = '本期暂无数据', 'none'
    elif prevValueText is None:
        deltaText, tone = '上期暂无可比数据', 'none'
    elif change is None:
        deltaText, tone = '与上期持平', 'flat'
    elif changeKind == 'pp':
        deltaText = f'{change:+.1f} 个百分点'
        tone = _tone(change, higher_is_better=higherIsBetter, eps=0.05)
    elif changeKind == 'econ':
        deltaText = f'{change:+,.0f} 金币'
        tone = _tone(change, higher_is_better=higherIsBetter, eps=1.0)
    else:
        deltaText = f'{change:+.0f} 场'
        tone = _tone(change, higher_is_better=higherIsBetter, eps=0.5)
    return {
        'id': mid, 'label': label,
        'valueText': valueText,
        'valueSub': valueSub,
        'prevValueText': prevValueText,
        'deltaText': deltaText, 'tone': tone,
        'sample': sample, 'prevSample': prevSample,
        'total': max(total, sample), 'prevTotal': max(prevSample, 0),
        'coverage': coverage,
        'enough': bool(enough),
        'note': note, 'href': href,
        'rank': rank,
        'bar': bar,
    }


def _fight_summary(entries):
    wins = total = 0
    for item in entries:
        game = item.get('game')
        if not game:
            continue
        for fight in match_facts.fight_events(game):
            if fight.get('won') is None:
                continue
            total += 1
            if fight['won']:
                wins += 1
    return wins, total


def _objective_summary(entries):
    """关键龙归属与首塔归属，只统计阵营明确的事件。"""
    dragons = {'own': 0, 'enemy': 0}
    towers = {'own': 0, 'enemy': 0}
    for item in entries:
        game = item.get('game')
        if not game:
            continue
        events = match_facts.objective_events(game)
        for event in events:
            if (event.get('kind') == 'resource'
                    and event.get('name') in DRAGON_NAMES
                    and event.get('camp') in ('own', 'enemy')):
                dragons[event['camp']] += 1
        first = next((event for event in events
                      if event.get('kind') == 'building'
                      and event.get('name') == '防御塔'
                      and event.get('camp') in ('own', 'enemy')), None)
        if first:
            towers[first['camp']] += 1
    return dragons, towers


def _objective_by_name(entries):
    """逐条资源的归属统计：{名称: {'own': n, 'enemy': n}}。

    与 _objective_summary 的合并口径分开，避免改到「关键龙控制率」的历史口径。
    """
    out = {name: {'own': 0, 'enemy': 0} for name in OBJECTIVE_NAMES}
    for item in entries:
        game = item.get('game')
        if not game:
            continue
        for event in match_facts.objective_events(game):
            name = event.get('name')
            camp = event.get('camp')
            if (event.get('kind') == 'resource' and name in out
                    and camp in ('own', 'enemy')):
                out[name][camp] += 1
    return out


def _first_blood_summary(entries):
    """一血归属：每局最早的死亡事件，死的那一方丢掉一血。

    只认阵营明确、有时间戳的死亡事件；一局里找不到任何可判定死亡就不进分母。
    """
    own = 0
    enemy = 0
    for item in entries:
        game = item.get('game')
        if not game:
            continue
        own_camp = game.get('ownCamp')
        if not own_camp:
            continue
        side_of = {match_facts.CAMP_CODE_REV.get(own_camp): 'own'}
        side_of['2' if own_camp == 'blue' else '1'] = 'enemy'
        earliest = None
        for death in game.get('deaths') or []:
            try:
                seconds = float(death.get('timeSec'))
            except (TypeError, ValueError):
                continue
            side = side_of.get(str(death.get('camp') or ''))
            if side is None:
                continue
            if earliest is None or seconds < earliest[0]:
                earliest = (seconds, side)
        if earliest is None:
            continue
        # 我方先死 = 对面拿到一血，反之亦然。
        if earliest[1] == 'own':
            enemy += 1
        else:
            own += 1
    return {'own': own, 'enemy': enemy}


def _peer_rows(entries, panel_only=()):
    """把每局镜头翻到对面，按对手聚合成同口径数据，作为排名基准。

    只做「同一局、另一个视角」的镜像，不引入外部数据：十分钟我方领先
    −2k，对面就是 +2k；团战我方没赢，就是对面赢了。只有终局面板的局
    没有过程数据，但能补上对手的胜负记录，保证胜率分母一样长。
    """
    peers = {}
    for item in list(entries) + list(panel_only):
        game = item.get('game') or {}
        key = str(item.get('opponentId') or '')
        if not key:
            continue
        row = peers.get(key)
        if row is None:
            row = peers[key] = {
                'id': key, 'name': item.get('opponentName') or '',
                'games': 0, 'decided': 0, 'wins': 0,
                'at10': [], 'lead': 0, 'leadHold': 0,
                'fightWins': 0, 'fightTotal': 0,
                'dragons': 0, 'dragonTotal': 0,
                'towers': 0, 'towerTotal': 0,
            }
        row['games'] += 1
        result = item.get('result')
        if result in ('win', 'loss'):
            row['decided'] += 1
            if result == 'loss':
                row['wins'] += 1
        if not game:
            continue
        value = _at10(game)
        if value is not None:
            row['at10'].append(-value)
            if -value > 0:
                row['lead'] += 1
                if result == 'loss':
                    row['leadHold'] += 1
        fights = [fight for fight in match_facts.fight_events(game)
                  if fight.get('won') is not None]
        row['fightTotal'] += len(fights)
        row['fightWins'] += sum(1 for fight in fights if not fight.get('won'))
        dragons, towers = _objective_summary([item])
        row['dragons'] += dragons['enemy']
        row['dragonTotal'] += dragons['own'] + dragons['enemy']
        if towers['own'] or towers['enemy']:
            row['towerTotal'] += 1
            if towers['enemy']:
                row['towers'] += 1
    return [row for row in peers.values() if row['games']]


def _peer_metric(row, mid):
    """对手在某一项上的同口径值；口径不成立返回 None。"""
    if mid == 'win_rate':
        return _pct(row['wins'], row['decided'])
    if mid == 'lead_rate':
        return _pct(row['lead'], len(row['at10']))
    if mid == 'lead_hold_rate':
        return _pct(row['leadHold'], row['lead'])
    if mid == 'lead_econ':
        return match_facts.mean(row['at10'])
    if mid == 'fight_rate':
        return _pct(row['fightWins'], row['fightTotal'])
    if mid == 'dragon_rate':
        return _pct(row['dragons'], row['dragonTotal'])
    if mid == 'first_tower_rate':
        return _pct(row['towers'], row['towerTotal'])
    return None


def _rank_of(mid, value, peers, *, minimum=RANK_MIN_PEERS):
    """在「本期一起训练的战队」里排名：x/xx + 百分位 + 领先/中等/落后。"""
    if value is None or not peers:
        return None
    values = [item for item in (_peer_metric(row, mid) for row in peers)
              if item is not None]
    if len(values) < minimum:
        return None
    better = sum(1 for item in values if item > value + 1e-9)
    equal = sum(1 for item in values if abs(item - value) <= 1e-9)
    below = sum(1 for item in values if item < value - 1e-9)
    total = len(values) + 1
    percentile = round((below + 0.5 * equal) / (total - 1) * 100, 1)
    tier, tier_text = RANK_TIERS[-1][1], RANK_TIERS[-1][2]
    for threshold, key, text in RANK_TIERS:
        if percentile >= threshold:
            tier, tier_text = key, text
            break
    return {
        'pos': better + 1, 'total': total,
        'percentile': percentile,
        'tier': tier, 'tierText': tier_text,
        'text': f'{tier_text} {better + 1}/{total}',
        'peers': len(values),
    }


def _dynamic_metrics(ctx, entries, prev_entries, at10_rows, prev_at10, has_prev, link,
                     peers=()):
    """动态两项：先看有效样本是否够，再看赛训价值，不看变化幅度。

    四项候选都生成卡片（没数据就给「本期暂无数据」），只取前 2 项；
    排序按「样本达标 > 有样本 > 赛训价值 > 样本量」，变化幅度不参与。
    """
    out = []
    cur_dragons, cur_towers = _objective_summary(entries)
    prev_dragons, prev_towers = _objective_summary(prev_entries)

    dragon_total = cur_dragons['own'] + cur_dragons['enemy']
    prev_dragon_total = prev_dragons['own'] + prev_dragons['enemy']
    rate = _pct(cur_dragons['own'], dragon_total) if dragon_total else None
    prev_rate = _pct(prev_dragons['own'], prev_dragon_total) if prev_dragon_total else None
    out.append((DYNAMIC_VALUE['dragon'], dragon_total, _metric_card(
        mid='dragon_rate', label='关键龙控制率',
        valueText=f"{cur_dragons['own']}/{dragon_total}" if dragon_total else '—',
        valueSub=_fmt_pct(rate) if rate is not None else None,
        prevValueText=(f"{prev_dragons['own']}/{prev_dragon_total}（{_fmt_pct(prev_rate)}）"
                       if prev_dragon_total and prev_rate is not None else None),
        sample=dragon_total, prevSample=prev_dragon_total, total=dragon_total,
        change=(rate - prev_rate) if rate is not None and prev_rate is not None else None,
        changeKind='pp', higherIsBetter=True, unit='个',
        note='暗影主宰 / 暴君 / 暗影暴君里我方拿到的比例',
        href=link(), enough=dragon_total >= MIN_SAMPLE, share=rate,
        rank=_rank_of('dragon_rate', rate, peers))))

    tower_total = cur_towers['own'] + cur_towers['enemy']
    prev_tower_total = prev_towers['own'] + prev_towers['enemy']
    rate = _pct(cur_towers['own'], tower_total) if tower_total else None
    prev_rate = _pct(prev_towers['own'], prev_tower_total) if prev_tower_total else None
    out.append((DYNAMIC_VALUE['first_tower'], tower_total, _metric_card(
        mid='first_tower_rate', label='一塔率',
        valueText=f"{cur_towers['own']}/{tower_total}" if tower_total else '—',
        valueSub=_fmt_pct(rate) if rate is not None else None,
        prevValueText=(f"{prev_towers['own']}/{prev_tower_total}（{_fmt_pct(prev_rate)}）"
                       if prev_tower_total and prev_rate is not None else None),
        sample=tower_total, prevSample=prev_tower_total, total=tower_total,
        change=(rate - prev_rate) if rate is not None and prev_rate is not None else None,
        changeKind='pp', higherIsBetter=True,
        note='每局第一座防御塔由我方拿到的比例',
        href=link(), enough=tower_total >= MIN_SAMPLE, share=rate,
        rank=_rank_of('first_tower_rate', rate, peers))))

    def behind(rows):
        rows = [(item, value) for item, value in rows
                if value < 0 and item.get('result') in ('win', 'loss')]
        wins = sum(1 for item, _ in rows if item.get('result') == 'win')
        return wins, len(rows)

    cur_cb_wins, cur_cb_total = behind(at10_rows)
    prev_cb_wins, prev_cb_total = behind(prev_at10)
    rate = _pct(cur_cb_wins, cur_cb_total) if cur_cb_total else None
    prev_rate = _pct(prev_cb_wins, prev_cb_total) if prev_cb_total else None
    out.append((DYNAMIC_VALUE['behind_comeback'], cur_cb_total, _metric_card(
        mid='behind_comeback', label='十分钟落后翻盘率',
        valueText=f"{cur_cb_wins}/{cur_cb_total}" if cur_cb_total else '—',
        valueSub=_fmt_pct(rate) if rate is not None else None,
        prevValueText=(f"{prev_cb_wins}/{prev_cb_total}（{_fmt_pct(prev_rate)}）"
                       if prev_cb_total and prev_rate is not None else None),
        sample=cur_cb_total, prevSample=prev_cb_total, total=cur_cb_total,
        change=(rate - prev_rate) if rate is not None and prev_rate is not None else None,
        changeKind='pp', higherIsBetter=True,
        note='10 分钟落后但最终赢下的比例',
        href=link(), enough=cur_cb_total >= MIN_SAMPLE, share=rate,
        rank=_rank_of('behind_comeback', rate, peers))))

    drawdowns = [game.get('drawdown') for game in ctx.get('cur_advantage') or []
                 if (game.get('maxLead') or 0) >= LEAD_AT10]
    prev_drawdowns = [game.get('drawdown') for game in ctx.get('prev_advantage') or []
                      if (game.get('maxLead') or 0) >= LEAD_AT10]
    avg_drawdown = match_facts.mean(drawdowns)
    prev_avg_drawdown = match_facts.mean(prev_drawdowns)
    out.append((DYNAMIC_VALUE['lead_drawdown'], len(drawdowns), _metric_card(
        mid='lead_drawdown', label='领先后经济回撤',
        valueText=_fmt_econ(-avg_drawdown) if avg_drawdown is not None else '—',
        prevValueText=(_fmt_econ(-prev_avg_drawdown)
                       if prev_avg_drawdown is not None else None),
        sample=len(drawdowns), prevSample=len(prev_drawdowns), total=len(drawdowns),
        change=(prev_avg_drawdown - avg_drawdown)
               if prev_avg_drawdown is not None and avg_drawdown is not None else None,
        changeKind='econ', higherIsBetter=True,
        note='领先 ≥1000 的局，从最高点跌回去的平均金额（越少越好）',
        href=link(), enough=len(drawdowns) >= MIN_SAMPLE)))

    out.sort(key=lambda item: (item[2]['sample'] >= MIN_SAMPLE,
                               item[2]['sample'] > 0, item[0], item[1]), reverse=True)
    return [card for _, _, card in out]


def _objective_metrics(entries, prev_entries, has_prev, link):
    """一塔率 + 四种资源各自的控制率，全部按「我方拿到 / 总出现数」计。"""
    out = []
    cur_towers, prev_towers = _objective_summary(entries), _objective_summary(prev_entries)
    specs = [('first_tower_rate', '一塔率', cur_towers[1]['own'],
              cur_towers[1]['own'] + cur_towers[1]['enemy'],
              prev_towers[1]['own'], prev_towers[1]['own'] + prev_towers[1]['enemy'],
              '每局第一座防御塔由我方拿到的比例')]
    cur_by = _objective_by_name(entries)
    prev_by = _objective_by_name(prev_entries)
    for name in OBJECTIVE_NAMES:
        cur, prev = cur_by[name], prev_by[name]
        specs.append((OBJECTIVE_MID[name], f'{name}控制率', cur['own'],
                      cur['own'] + cur['enemy'], prev['own'],
                      prev['own'] + prev['enemy'], f'{name}由我方拿到的比例'))
    for mid, label, own, total, prev_own, prev_total, note in specs:
        rate = _pct(own, total) if total else None
        prev_rate = _pct(prev_own, prev_total) if prev_total else None
        out.append(_metric_card(
            mid=mid, label=label,
            valueText=f'{own}/{total}' if total else '—',
            valueSub=_fmt_pct(rate) if rate is not None else None,
            prevValueText=(f'{prev_own}/{prev_total}（{_fmt_pct(prev_rate)}）'
                           if prev_total and prev_rate is not None else None),
            sample=total, prevSample=prev_total, total=total,
            change=(rate - prev_rate) if rate is not None and prev_rate is not None else None,
            changeKind='pp', higherIsBetter=True, unit='个',
            note=note, href=link(), enough=total >= MIN_SAMPLE, share=rate))
    return out


def build_scrim_metrics(ctx, record, panel_only=()):
    """基本盘 + 比率 + 资源控制率。仅终局面板的局只进战绩，不进时间轴指标。"""
    entries = list(ctx.get('cur') or [])
    prev_entries = list(ctx.get('prev') or [])
    panel_only = list(panel_only or ())
    prev_panel_only = list(ctx.get('prev_panel_only') or ())
    total = len(entries) + len(panel_only)
    filters = ctx.get('filters') or {}
    prev_record = _record(prev_entries + prev_panel_only)
    has_prev = bool(prev_entries or prev_panel_only)

    def link():
        return _destination('matches', filters)

    at10_rows = [(item, _at10(item.get('game') or {})) for item in entries]
    at10_rows = [(item, value) for item, value in at10_rows if value is not None]
    prev_at10 = [(item, _at10(item.get('game') or {})) for item in prev_entries]
    prev_at10 = [(item, value) for item, value in prev_at10 if value is not None]
    process_total = len(entries)
    peers = _peer_rows(entries, panel_only)

    def lead_stats(rows):
        lead = [(item, value) for item, value in rows if value > 0]
        decided = [(item, value) for item, value in lead
                   if item.get('result') in ('win', 'loss')]
        wins = sum(1 for item, _ in decided if item.get('result') == 'win')
        return lead, decided, wins

    lead, _, _ = lead_stats(at10_rows)
    prev_lead, _, _ = lead_stats(prev_at10)

    value = f"{record['wins']} 胜 {record['losses']} 负"
    if record['unknown']:
        value += f" · {record['unknown']} 局未判定"
    prev_value = (f"{prev_record['wins']} 胜 {prev_record['losses']} 负"
                  if has_prev else None)

    lead_rate = _pct(len(lead), len(at10_rows))
    prev_lead_rate = _pct(len(prev_lead), len(prev_at10)) if prev_at10 else None
    econ_mean = match_facts.mean([item for _, item in at10_rows])
    prev_econ_mean = match_facts.mean([item for _, item in prev_at10]) if prev_at10 else None

    metrics = [
        _metric_card(
            mid='record', label='本期战绩', valueText=value, prevValueText=prev_value,
            sample=record['decided'], prevSample=prev_record['decided'], total=total,
            change=(record['wins'] - prev_record['wins']) if has_prev else None,
            changeKind='count', higherIsBetter=True,
            note='含仅有终局面板的局；未判定胜负的不进胜率分母',
            href=link(), enough=True, share=record['winRate']),
        _metric_card(
            mid='lead_rate', label='十分钟领先率',
            valueText=(f"{len(lead)}/{len(at10_rows)}" if at10_rows else '—'),
            valueSub=_fmt_pct(lead_rate) if lead_rate is not None else None,
            prevValueText=(f"{len(prev_lead)}/{len(prev_at10)}（{_fmt_pct(prev_lead_rate)}）"
                           if prev_at10 and prev_lead_rate is not None else None),
            sample=len(at10_rows), prevSample=len(prev_at10), total=total,
            change=(lead_rate - prev_lead_rate
                    if (lead_rate is not None and prev_lead_rate is not None) else None),
            changeKind='pp', higherIsBetter=True,
            note='10 分钟时经济领先的局占比；只算有经济曲线的局',
            href=link(), enough=len(at10_rows) >= MIN_SAMPLE,
            share=lead_rate,
            rank=_rank_of('lead_rate', lead_rate, peers)),
        _metric_card(
            mid='lead_econ', label='十分钟经济差',
            valueText=_fmt_econ(econ_mean),
            prevValueText=(_fmt_econ(prev_econ_mean)
                           if prev_econ_mean is not None else None),
            sample=len(at10_rows), prevSample=len(prev_at10), total=total,
            change=((econ_mean - prev_econ_mean)
                    if (econ_mean is not None and prev_econ_mean is not None) else None),
            changeKind='econ', higherIsBetter=True,
            note='10 分钟时我方领先 / 落后的金币，取平均',
            href=link(), enough=len(at10_rows) >= MIN_SAMPLE,
            rank=_rank_of('lead_econ', econ_mean, peers)),
    ]

    fight_wins, fight_total = _fight_summary(entries)
    prev_fight_wins, prev_fight_total = _fight_summary(prev_entries)
    fight_rate = _pct(fight_wins, fight_total)
    prev_fight_rate = _pct(prev_fight_wins, prev_fight_total) if prev_fight_total else None
    metrics.append(_metric_card(
        mid='fight_rate', label='团战胜率',
        valueText=f'{fight_wins}/{fight_total}' if fight_total else '—',
        valueSub=_fmt_pct(fight_rate) if fight_rate is not None else None,
        prevValueText=(f'{prev_fight_wins}/{prev_fight_total}（{_fmt_pct(prev_fight_rate)}）'
                       if prev_fight_total and prev_fight_rate is not None else None),
        sample=fight_total, prevSample=prev_fight_total, total=fight_total,
        change=(fight_rate - prev_fight_rate
                if (fight_rate is not None and prev_fight_rate is not None) else None),
        changeKind='pp', higherIsBetter=True, unit='波',
        note='按每波团战的击杀结果统计，不是按局',
        href=link(), enough=fight_total >= MIN_SAMPLE,
        share=fight_rate,
        rank=_rank_of('fight_rate', fight_rate, peers)))

    blood = _first_blood_summary(entries)
    prev_blood = _first_blood_summary(prev_entries)
    blood_total = blood['own'] + blood['enemy']
    prev_blood_total = prev_blood['own'] + prev_blood['enemy']
    blood_rate = _pct(blood['own'], blood_total)
    prev_blood_rate = _pct(prev_blood['own'], prev_blood_total) if prev_blood_total else None
    metrics.append(_metric_card(
        mid='first_blood_rate', label='一血率',
        valueText=f"{blood['own']}/{blood_total}" if blood_total else '—',
        valueSub=_fmt_pct(blood_rate) if blood_rate is not None else None,
        prevValueText=(f"{prev_blood['own']}/{prev_blood_total}（{_fmt_pct(prev_blood_rate)}）"
                       if prev_blood_total and prev_blood_rate is not None else None),
        sample=blood_total, prevSample=prev_blood_total, total=blood_total,
        change=(blood_rate - prev_blood_rate
                if (blood_rate is not None and prev_blood_rate is not None) else None),
        changeKind='pp', higherIsBetter=True,
        note='每局第一次击杀由我方拿到的比例',
        href=link(), enough=blood_total >= MIN_SAMPLE,
        share=blood_rate))

    metrics.extend(_objective_metrics(entries, prev_entries, has_prev, link))
    # 上期局数是本期的 2 倍以上时，「少赢 N 场」只是在比训练量；
    # 战绩卡只保留上期战绩，不再给这个假差值（摘要句已改比胜率）。
    if has_prev and record['decided'] and prev_record['decided']:
        low, high = sorted((record['decided'], prev_record['decided']))
        if high >= 2 * low:
            record_metric = next((m for m in metrics if m['id'] == 'record'), None)
            if record_metric:
                record_metric['deltaText'] = ''
                record_metric['tone'] = 'none'
    return metrics


def build_overview_metrics(ctx):
    """首页三张卡：这期打了多少、练了什么、哪几局要先回看。

    每卡一个总览数字 + 一句教练语言补充 + 一个下钻入口；不做周期对比、
    不写「暂不可比」，也不放领先兑现 / 团战到位 / 龙塔收益这类派生指标。
    """
    entries = list(ctx.get('cur') or [])
    if not entries:
        return []
    games = len(entries)
    record = _record(entries)
    filters = ctx.get('filters') or {}

    def link(page):
        return _destination(page, filters)

    days = sorted({str(item.get('date') or '')[:10] for item in entries
                   if item.get('date')})
    span = (f'{days[0][5:]} ~ {days[-1][5:]}' if len(days) > 1
            else (days[0][5:] if days else ctx['window']['rangeLabel']))
    hero_counts = _own_heroes(entries)
    top2 = hero_counts.most_common(2)
    top_hero, top_games = top2[0] if top2 else ('', 0)
    hero_value = f'{top_hero} · {top_games} 局' if top_hero else '—'
    second = f'，其次 {top2[1][0]} {top2[1][1]} 局' if len(top2) > 1 else ''
    hero_sub = (f'我方五路用了 {len(hero_counts)} 个英雄{second}' if hero_counts
                else '本期还没有英雄记录')
    day_count = len(days) or 1
    game_sub = f'{span} · {day_count} 天 · 日均 {max(1, round(games / day_count))} 局'
    losses = record['losses']
    lost_games = [item for item in entries if item.get('result') == 'loss']
    behind = sum(1 for item in lost_games
                 if (_game_stats(item.get('game') or {})
                     .get('at10') or 0) < -1000)
    if losses and behind:
        loss_sub = f'{record["wins"]} 胜 {losses} 负 · {behind} 局在 10 分钟就落后'
    elif losses:
        loss_sub = f'{record["wins"]} 胜 {losses} 负 · 先看这 {losses} 局'
    else:
        loss_sub = f'{record["wins"]} 胜 0 负 · 本期没有失利'

    def metric(mid, label, value, sub, note, page):
        return {
            'id': mid, 'label': label,
            'valueText': value, 'prevValueText': '', 'deltaText': '',
            'tone': 'none', 'sample': games, 'prevSample': 0, 'enough': True,
            'note': note, 'subText': sub, 'href': link(page),
        }

    return [
        metric('games', '本期训练赛', f'{games} 局', game_sub,
               '按营地终局面板与官方回放收录', 'matches'),
        metric('hero_pool', '最常用英雄', hero_value, hero_sub,
               '本期我方五路出场过的英雄', 'bp'),
        metric('losses', '输掉的局', f'{losses} 局', loss_sub,
               '训练赛里优先回看的局', 'matches'),
    ]


WATCH_FIELDS = (
    ('deficit', '最多落后', '全场最多落后多少金币', '金币'),
    ('deaths', '我方掉点', '我方掉点次数', '次'),
    ('giveback', '领先被反超', '领先 1000 金币以上、后来被反超', '金币'),
    ('fight', '团战打输', '打输的团战波数', '波'),
    ('at10', '10 分钟经济差', '10 分钟时我方领先 / 落后的金币', '金币'),
    ('duration', '时长', '这局打了多久', '时间'),
    ('dragon', '关键龙丢失', '被对手拿到的暗影主宰 / 暴君', '条'),
    ('tower', '被推塔', '被对手推掉的防御塔', '座'),
    ('gold', '终局经济差', '结束时我方与对手的金币差', '金币'),
    ('damage', '团队输出占比', '我方五人英雄输出占双方输出的比例', '%'),
)

# 卡片默认显示这四项；赛训组可以在页面上自己换（后端只给默认值）。
WATCH_DEFAULT_DISPLAY = ('deficit', 'at10', 'deaths', 'duration')

# 「最多落后」组只收落后 ≥1000 金币的局：-75 这类噪声不该占「最值得复盘」。
WATCH_MIN_DEFICIT = 1000
# 落后 3000 以上翻回来 / 领先 3000 以上被打回去，才在卡上标「翻盘 / 被翻盘」。
WATCH_COMEBACK_MIN = 3000

# 某个字段在这期一局都没有时给教练看的空态句。
WATCH_EMPTY = {
    'deficit': '本期没有落后 1000 金币以上的局。',
    'deaths': '本期没有掉点的局。',
    'giveback': '本期没有被反超的局。',
    'fight': '本期没有打输团战的局。',
    'at10': '本期没有十分钟落后的局。',
    'duration': '本期还没有可统计时长的局。',
    'dragon': '本期没有丢掉关键龙的局。',
    'tower': '本期没有被推塔的局。',
    'gold': '本期没有结束时经济落后的局。',
    'damage': '本期还没有输出占比偏低的局。',
}


MOMENT_LIMIT = 3             # 复盘卡最多给的「关键时间点」数量


def _watch_moments(item, stat, field):
    """这局值得回看的关键时间点（0–3 个，按时间排序）。

    只用回放事实：经济曲线的最低点 / 领先被反超、被对手拿到的关键龙、
    被推塔、打输的团战、我方掉点。没有事实就不编，返回空数组。
    """
    game = item.get('game') or {}
    own = [value for value in (game.get('ownDiff') or [])
           if isinstance(value, (int, float))]
    times = game.get('times') or []
    own_num = match_facts.CAMP_CODE_REV.get(str(game.get('ownCamp') or ''))
    camp_of = game.get('objToCamp') or {}

    def make(seconds, label):
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            return None
        text = match_facts.clock(seconds)
        if not text or text == '—':
            return None
        return {'t': round(float(seconds), 1), 'clock': text, 'label': label}

    candidates = []
    if own and times:
        low_index = min(range(len(own)), key=lambda index: own[index])
        if own[low_index] < 0 and low_index < len(times):
            candidates.append(('deficit', make(
                times[low_index], f'最多落后 {abs(own[low_index]):,.0f}')))
        peak_index = max(range(len(own)), key=lambda index: own[index])
        if own[peak_index] >= LEAD_AT10:
            for index in range(peak_index + 1, len(own)):
                if own[index] < 0:
                    candidates.append(('giveback', make(
                        times[index] if index < len(times) else None, '领先被反超')))
                    break
        at10 = stat.get('at10')
        if at10 is not None:
            candidates.append(('at10', make(600, f'10 分钟 {_k(at10)}')))

    dragon_moment = tower_moment = None
    for event in game.get('events') or []:
        goal = match_facts.format_objective(event, game.get('ownCamp'))
        if goal.get('camp') != 'enemy':
            continue
        if (dragon_moment is None and goal.get('kind') == 'resource'
                and goal.get('name') in DRAGON_NAMES):
            dragon_moment = make(event.get('timeSec'), f"丢{goal.get('name')}")
        elif (tower_moment is None and goal.get('kind') == 'building'
              and goal.get('name') == '防御塔'):
            tower_moment = make(event.get('timeSec'), '被推塔')
    candidates.append(('dragon', dragon_moment))
    candidates.append(('tower', tower_moment))

    for fight in match_facts.fight_events(game):
        if fight.get('won') is False and (fight.get('killDiff') or 0) <= -2:
            candidates.append(('fight', make(
                fight.get('startSec'),
                f"团战 {fight.get('ownKills')}:{fight.get('enemyKills')}")))
            break

    death_times = sorted(
        float(event.get('timeSec')) for event in (game.get('deaths') or [])
        if isinstance(event.get('timeSec'), (int, float)) and own_num
        and camp_of.get(str(event.get('objID') or '')) == own_num)
    if death_times:
        nth = min(len(death_times), 3)
        candidates.append(('deaths', make(
            death_times[nth - 1], f'第 {nth} 次掉点')))

    # 当前字段的时间点优先，再按时间顺序补;# 同一时刻同一句只留一个。
    candidates = [row for row in candidates if row[1]]
    candidates.sort(key=lambda row: (0 if row[0] == field else 1, row[1]['t']))
    picked, seen = [], set()
    for _kind, moment in candidates:
        key = (moment['t'], moment['label'])
        if key in seen:
            continue
        seen.add(key)
        picked.append(moment)
        if len(picked) >= MOMENT_LIMIT:
            break
    picked.sort(key=lambda moment: moment['t'])
    return picked


def _watch_value(field, stats):
    """这一局在某个复盘字段上的展示值。

    ``severity`` 决定这局进不进该字段的「异常」组（None = 有值但不算异常，
    例如十分钟领先、团战没输）；``label`` / ``value`` 是卡片上直接显示的文字。
    没有这项数据的局返回 None（不补 0）。
    """
    if field == 'deficit':
        low = stats.get('low')
        if low is None:
            return None
        return {'severity': -low if low <= -WATCH_MIN_DEFICIT else None,
                'label': '最多落后', 'value': _k(low)}
    if field == 'deaths':
        deaths = stats.get('deaths') or 0
        return {'severity': deaths if deaths > 0 else None,
                'label': '我方掉点', 'value': f'{deaths} 次'}
    if field == 'giveback':
        peak, low = stats.get('peak'), stats.get('low')
        if peak is None or low is None or peak < LEAD_AT10 or low >= 0:
            return None
        back = peak - low
        return {'severity': back, 'label': '领先被反超',
                'value': f'-{back:,.0f} 金币'}
    if field == 'fight':
        losses = stats.get('fightLosses') or 0
        return {'severity': losses if losses > 0 else None,
                'label': '团战打输', 'value': f'{losses} 波'}
    if field == 'at10':
        at10 = stats.get('at10')
        if at10 is None:
            return None
        return {'severity': -at10 if at10 < 0 else None,
                'label': '10 分钟经济差', 'value': _k(at10)}
    if field == 'duration':
        duration = stats.get('duration')
        if not isinstance(duration, (int, float)) or duration <= 0:
            return None
        return {'severity': duration, 'label': '时长', 'value': _mmss(duration)}
    if field == 'dragon':
        lost = stats.get('dragonsLost') or 0
        return {'severity': lost if lost > 0 else None,
                'label': '关键龙丢失', 'value': f'{lost} 条'}
    if field == 'tower':
        lost = stats.get('towersLost') or 0
        return {'severity': lost if lost > 0 else None,
                'label': '被推塔', 'value': f'{lost} 座'}
    if field == 'gold':
        diff = stats.get('goldDiff')
        if diff is None:
            return None
        return {'severity': -diff if diff < 0 else None,
                'label': '终局经济差', 'value': _k(diff)}
    if field == 'damage':
        pct = stats.get('damagePct')
        if pct is None:
            return None
        return {'severity': 50 - pct if pct < 50 else None,
                'label': '团队输出占比', 'value': f'{pct:.1f}%'}
    return None


def _watch_focus(field, stats):
    """某一项上这局的严重度与主数字；这项不成立的局不进该组。"""
    value = _watch_value(field, stats)
    if not value or value.get('severity') is None:
        return None
    return (value['severity'], value['label'], value['value'])


def _watch_values(stats):
    """卡片上所有可显示字段（顺序同 WATCH_FIELDS），前端按自己的选择取用。"""
    values = []
    for field, _label, _note, _unit in WATCH_FIELDS:
        value = _watch_value(field, stats)
        if value:
            values.append({'id': field, 'label': value['label'],
                           'value': value['value']})
    return values


def _watch_numbers(field, stats):
    """兼容旧消费方：当前字段排第一高亮，再补默认显示的其余字段，最多 4 个。"""
    numbers = []
    seen = set()

    def add(field_id, focus=False):
        if field_id in seen:
            return
        value = _watch_value(field_id, stats)
        if not value:
            return
        seen.add(field_id)
        numbers.append({'label': value['label'], 'value': value['value'],
                        'focus': bool(focus)})

    add(field, True)
    for field_id in WATCH_DEFAULT_DISPLAY:
        if len(numbers) >= WATCH_NUM_LIMIT:
            break
        add(field_id)
    return numbers[:WATCH_NUM_LIMIT]


def _watch_review_type(item, stat, field):
    """一张名片只贴一个复盘类型，不用红绿表达严重程度。"""
    peak, low = stat.get('peak'), stat.get('low')
    duration = stat.get('duration') or 0
    if (isinstance(peak, (int, float)) and peak >= 1000
            and isinstance(low, (int, float)) and low <= -1000):
        return '领先转落后'
    if item.get('result') == 'win' and isinstance(low, (int, float)) and low <= -1000:
        return '逆风追回'
    if isinstance(low, (int, float)) and low <= -5000:
        return '大劣势局'
    if duration and duration <= 400:
        return '快速结束'
    return _watch_field_label(field)


def _watch_field_label(field):
    for key, label, _note, _unit in WATCH_FIELDS:
        if key == field:
            return label
    return field


def _watch_problem(field, stat):
    """一句话说清这局为什么值得复盘，优先讲「怎么变的」而不是最大数值。"""
    peak, low = stat.get('peak'), stat.get('low')
    if field in ('deficit', 'giveback', 'gold'):
        if (isinstance(peak, (int, float)) and peak >= 1000
                and isinstance(low, (int, float)) and low <= -1000):
            return f"从领先 {peak:,.0f} 变成落后 {abs(low):,.0f}"
    return _watch_core(field, stat) or _watch_sentence_tail(stat)


def _watch_sentence_tail(stat):
    low = stat.get('low')
    if isinstance(low, (int, float)) and low < 0:
        return f"最多落后 {abs(low):,.0f} 金币"
    return ''


def _watch_review_score(stat):
    """复盘价值：多维度叠加，不再只按「落后最多」排。"""
    low, peak = stat.get('low'), stat.get('peak')
    score = 0.0
    if isinstance(low, (int, float)) and low < 0:
        score += abs(low) / 100
    if isinstance(peak, (int, float)) and isinstance(low, (int, float)) and peak >= 1000 > low:
        score += 6
    score += (stat.get('deaths') or 0) * 1.5
    score += (stat.get('fightLosses') or 0) * 3
    score += (stat.get('dragonsLost') or 0) * 2
    score += (stat.get('towersLost') or 0)
    duration = stat.get('duration') or 0
    if duration and duration <= 420:
        score += (420 - duration) / 30
    at10 = stat.get('at10')
    if isinstance(at10, (int, float)) and at10 < 0:
        score += abs(at10) / 200
    pct = stat.get('damagePct')
    if isinstance(pct, (int, float)) and pct < 50:
        score += (50 - pct) / 3
    return round(score, 2)


def _watch_card(item, stat, field, longest, shortest):
    result = item.get('result') if item.get('result') in ('win', 'loss') else None
    lost = result == 'loss'
    low, peak = stat.get('low'), stat.get('peak')
    result_tag = ''
    if result == 'win' and isinstance(low, (int, float)) and low <= -WATCH_COMEBACK_MIN:
        result_tag = '翻盘'
    elif result == 'loss' and isinstance(peak, (int, float)) and peak >= WATCH_COMEBACK_MIN:
        result_tag = '被翻盘'
    focus = next((item for item in _watch_values(stat) if item['id'] == field), None)
    return {
        'id': f"watch_{item['seq']}_{field}",
        'kind': 'loss' if lost else 'win',
        'resultTag': result_tag,
        'field': field,
        'title': item['label'],
        'start': str(item.get('start') or ''),
        'conclusion': _watch_sentence(stat, lost, longest, shortest, field, result=result),
        'numbers': _watch_numbers(field, stat),
        'values': _watch_values(stat),
        'moments': _watch_moments(item, stat, field),
        'rosterText': stat['roster'],
        'rosterPlayers': stat['rosterPlayers'],
        'foePlayers': stat.get('foePlayers') or [],
        'problem': _watch_problem(field, stat),
        'reviewType': _watch_review_type(item, stat, field),
        'reviewScore': _watch_review_score(stat),
        'reviewTail': WATCH_TAIL.get(field, ''),
        'focusLabel': (focus or {}).get('label', ''),
        'focusValue': (focus or {}).get('value', ''),
        'n': 1,
        'enough': True,
        'evidence': [{'game': item['seq'], 'label': '这局过程', 'note': ''}],
        'counterexamples': [],
        'primary_destination': f'#match/{item["seq"]}',
        'deep_destination': '',
        'limitation': '',
    }


def _attach_finding_matches(findings, ctx):
    """给每条发现补上展开后才用的关联对局：真实阵容、时间、复盘入口。

    标签不在后端读：前端 match-tags.js 已按 data-tag-key 自动填充 .tagrow，
    这里只给对局唯一 id，保持标签由同一份匹配数据驱动。
    """
    entries = list(ctx.get('cur') or [])
    by_seq = {str(item.get('seq') or ''): item for item in entries}
    by_label = {}
    for item in entries:
        by_label.setdefault(str(item.get('label') or ''), item)
    for finding in findings:
        rows = []
        for evidence in list(finding.get('evidence') or [])[:2]:
            key = str(evidence.get('game') or '')
            entry = by_seq.get(key) or by_label.get(str(evidence.get('label') or ''))
            if not entry:
                continue
            stat = _game_stats(entry.get('game') or {}, entry.get('panel'))
            rows.append({
                'id': str(entry.get('seq') or key),
                'label': str(evidence.get('label') or entry.get('label') or ''),
                'time': str(entry.get('start') or '')[:5],
                'note': str(evidence.get('note') or ''),
                't': evidence.get('t'),
                'rosterPlayers': stat.get('rosterPlayers') or [],
                'foePlayers': stat.get('foePlayers') or [],
            })
            if len(rows) >= 2:
                break
        finding['relatedMatches'] = rows


def build_watch_groups(ctx):
    """复盘区：按 10 个可选字段各排一组「这期最值得看的 3 局」。

    赛训组先选自己关心的那一项（落后最深 / 掉点最多 / 优势被打回 / 团战打输 /
    十分钟落后 / 时长 / 丢龙 / 被推塔 / 终局经济 / 输出占比），再看这一项上最差的局；
    排序与取数都在后端，前端只切换分组、只决定卡片上显示哪四个字段。
    """
    entries = list(ctx.get('cur') or [])
    if not entries:
        return {'field': None, 'fields': [], 'display': list(WATCH_DEFAULT_DISPLAY)}
    stats = [(item, _game_stats(item.get('game') or {}, item.get('panel')))
             for item in entries]
    durations = [stat['duration'] for _, stat in stats
                 if isinstance(stat['duration'], (int, float)) and stat['duration'] > 0]
    longest = max(durations) if durations else None
    shortest = min(durations) if durations else None
    fields = []
    for field, label, note, unit in WATCH_FIELDS:
        rows = []
        for item, stat in stats:
            focus = _watch_focus(field, stat)
            if focus is None:
                continue
            rows.append((focus[0], str(item.get('date') or ''), str(item.get('seq') or ''),
                         item, stat))
        rows.sort(key=lambda row: row[:3], reverse=True)
        cards = [_watch_card(item, stat, field, longest, shortest)
                 for _, _, _, item, stat in rows[:WATCH_LIMIT]]
        fields.append({
            'id': field, 'label': label, 'note': note, 'unit': unit,
            'count': len(rows), 'items': cards,
            'empty': WATCH_EMPTY.get(field, f'本期没有{label}的局。'),
        })
    default = next((item for item in fields if item['items']), fields[0] if fields else None)
    if default:
        # 首页默认那组按复盘价值排：领先被翻、掉点多、资源丢得多、时长异常叠加，
        # 而不是只按「落后最多」一个数字，否则四张卡会变成同一个维度的重复。
        group = next((item for item in fields if item['id'] == default['id']), None)
        if group:
            group['items'].sort(key=lambda card: -card['reviewScore'])
    return {'field': default['id'] if default else None, 'fields': fields,
            'display': list(WATCH_DEFAULT_DISPLAY)}


def _sentence(window, record, prev_record, entries=()):
    """首页战况只说一件事：本期多少局、几胜几负、胜率多少。

    不写日期区间、不跟上期对比——本期指标表里已经逐项给了上期与变化，
    顶部再来一句「比上月同期…」既重复又让字号忽大忽小。
    """
    cur_word = _period_cur_word(window)
    base = (f"{cur_word} {record['decided']} 局训练赛，"
            f"{record['wins']} 胜 {record['losses']} 负")
    if record.get('unknown'):
        base += f"、{record['unknown']} 局未判定"
    rate = record.get('winRate')
    if rate is not None:
        base += f"，胜率 {_fmt_pct(rate)}"
    return f"{base}。", 'none'


def _coverage(entries, record, window, panel_only=()):
    replay = sum(1 for item in entries if item['hasReplay'])
    timeline = sum(1 for item in entries if item['hasTimeline'])
    panel_games = len(entries) + len(panel_only)
    opponents = len({item['opponentId'] for item in entries if item['opponentId']})
    if not entries:
        # 只有终局面板时 summary 里仍然有局数，这里不能写成「还没有对局」，
        # 否则首页一句战况说「本月 31 局」、数据覆盖说「本月还没有对局」，自相矛盾。
        if panel_only:
            note = f"{_period_cur_word(window)}还没有可看比赛过程的对局"
        else:
            note = f"{_period_cur_word(window)}还没有对局"
    else:
        note = f"本期 {len(entries)} 局有比赛过程"
        if panel_only:
            note += f"，另有 {len(panel_only)} 局只有终局面板"
    return {
        'games': len(entries),
        'decided': record['decided'],
        'withReplay': replay,
        'withTimeline': timeline,
        'panelGames': panel_games,
        'versions': [],
        'opponents': opponents,
        'dateLabel': window['rangeLabel'],
        'note': note,
    }


def _all_game_dates(facts):
    counts = Counter()
    for game in (facts.get('games') or {}).values():
        if isinstance(game, dict) and game.get('date'):
            counts[str(game['date'])] += 1
    return counts


def fallback_hint(facts, before):
    """最近一批有回放的最近区间与局数（本期 0 局时的快捷入口）。"""
    counts = _all_game_dates(facts)
    if not counts:
        return None
    dates = sorted(counts)
    pool = [day for day in dates if day < before] or dates
    latest = pool[-1]
    start = latest
    while True:
        previous = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        if previous not in counts:
            break
        start = previous
    games = sum(counts[day] for day in counts if start <= day <= latest)
    return {
        'from': start,
        'to': latest,
        'label': _range_label(date.fromisoformat(start), date.fromisoformat(latest)),
        'games': games,
    }


def _next_payload(rows, today, team_names=None):
    if rows is None:
        return {'available': False,
                'note': '训练安排暂不可读（没有工作区数据库）', 'items': []}
    today_iso = today.isoformat()
    names = team_names or {}
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = str(row.get('date') or '')
        if not day or day < today_iso:
            continue
        if str(row.get('status') or '').lower() in ('cancelled', 'canceled', 'done',
                                                    'completed', 'finished'):
            continue
        opponent_id = str(row.get('opponent_team_id') or '')
        opponent = str(names.get(opponent_id) or '').strip()
        if not opponent:
            opponent = '待命名战队' if opponent_id else ''
        note = (row.get('notes') or row.get('session') or row.get('format')
                or '训练赛')
        items.append({
            'date': day,
            'time': str(row.get('start_time') or ''),
            'opponent': opponent,
            'note': str(note),
        })
    items.sort(key=lambda item: (item['date'], item['time']))
    if not items:
        return {'available': False, 'note': '还没有登记下一场约训', 'items': []}
    return {'available': True, 'note': None, 'items': items[:2]}


def _empty_payload(window, *, reason, fallback, today, schedule_rows, team_names,
                   prev_record=None):
    entries = []
    coverage = _coverage(entries, {'decided': 0}, window, ())
    next_payload = _next_payload(schedule_rows, today, team_names)
    prev_meta = (window.get('prev') or {}) if isinstance(window, dict) else {}
    prev_record = prev_record or {'wins': 0, 'losses': 0, 'decided': 0, 'winRate': None}
    empty_note = None
    if prev_record.get('decided'):
        prev_label = prev_meta.get('label') or '上一周期'
        prev_range = prev_meta.get('rangeLabel') or ''
        empty_note = (f"{prev_label}（{prev_range}）有 {prev_record['decided']} 局，"
                      f"{prev_record['wins']} 胜 {prev_record['losses']} 负。")
    return {
        'available': False,
        'reason': reason,
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'period': window,
        'fallback_hint': fallback,
        'empty_note': empty_note,
        'coverage': coverage,
        'record': {'wins': 0, 'losses': 0, 'decided': 0, 'winRate': None,
                   'prev': prev_record},
        'summary': {'sentence': None, 'tone': 'none', 'note': reason},
        'metrics': [],
        'findings': [],
        'watch': [],
        'watchField': None,
        'watchFields': [],
        'watchDisplayFields': [],
        'next': next_payload,
        'sources': {'replay': 0, 'panel': 0,
                    'schedule': len(next_payload['items']),
                    'note': '来源：官方回放 + 营地终局面板'},
        'notes': ['训练赛与正式比赛未区分，按来源筛选查看。',
                  '简报口径来自官方回放与营地终局面板；source/validation 只用于下钻时与其他页一致。'],
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_briefing(facts, *, period_kind='week', date_from=None, date_to=None,
                   opponent=None, source=DEFAULT_SOURCE, validation='0',
                   today=None, schedule_rows=None, team_names=None,
                   classic_metrics=False, recent_n=5, days=3):
    """生成首页周期简报（只读）。custom / recent / days 参数非法时抛 ValueError。"""
    facts = facts if isinstance(facts, dict) else {}
    today = today or date.today()
    source_text = _normalize_source(source)
    validation_text = '1' if str(validation).strip() in ('1', 'true') else '0'

    extra = False
    prev = None
    kind = str(period_kind or 'week').strip().lower()
    if kind in EXTRA_PERIOD_KINDS:
        extra = True
        picked = _extra_window(facts, kind, today=today, opponent=opponent,
                               recent_n=recent_n, days=days)
        if picked is None:
            window = _extra_empty_window(kind, today=today,
                                         recent_n=recent_n, days=days)
            cur, prev = [], []
        else:
            window, cur, prev = picked
        # 「最近 N 场」只数有回放的局；「最近 D 天」把只有面板的局并进战绩。
        cur_panel_only = []
        if kind == 'days':
            cur_panel_only = _collect_panel_only(
                facts, window['from'], window['to'], opponent,
                exclude={item['seq'] for item in cur})
    else:
        window = parse_period(period_kind, today=today,
                              date_from=date_from, date_to=date_to)
        cur = _collect_games(facts, window['from'], window['to'], opponent)
        # 只有终局面板的局也算本期有数据：它们参与战绩，但不参与时间轴指标。
        cur_panel_only = _collect_panel_only(
            facts, window['from'], window['to'], opponent,
            exclude={item['seq'] for item in cur})

    if not cur and not cur_panel_only:
        if not (facts.get('panels') or {}):
            reason = '还没有对局数据：先在「采集」里导入营地终局面板或官方回放。'
        else:
            reason = f"{_period_cur_word(window)}还没有对局（{window['rangeLabel']}）。"
        if prev is None:
            prev_empty = _collect_games(
                facts, window['prev']['from'], window['prev']['to'], opponent)
            prev_empty_panel = _collect_panel_only(
                facts, window['prev']['from'], window['prev']['to'], opponent,
                exclude={item['seq'] for item in prev_empty})
        else:
            prev_empty, prev_empty_panel = prev, []
        return _empty_payload(
            window, reason=reason, fallback=fallback_hint(facts, window['from']),
            today=today, schedule_rows=schedule_rows, team_names=team_names,
            prev_record=_record(prev_empty + prev_empty_panel))

    if prev is None:
        prev = _collect_games(facts, window['prev']['from'], window['prev']['to'], opponent)
        prev_panel_only = _collect_panel_only(
            facts, window['prev']['from'], window['prev']['to'], opponent,
            exclude={item['seq'] for item in prev})
    else:
        prev_panel_only = []
        if kind == 'days':
            prev_panel_only = _collect_panel_only(
                facts, window['prev']['from'], window['prev']['to'], opponent,
                exclude={item['seq'] for item in prev})
    record = _record(cur + cur_panel_only)
    prev_record = _record(prev + prev_panel_only)
    # 首页主卡用「最近 12 局」的胜负序列做 form guide；只放有胜负的局，按日期从旧到新。
    form_games = sorted(
        [item for item in (cur + cur_panel_only) if item.get('result') in ('win', 'loss')],
        key=lambda item: (str(item.get('date') or ''), str(item.get('seq') or '')))
    record['form'] = [
        {'result': item['result'],
         'date': str(item.get('date') or '')[:10],
         'opponent': str(item.get('opponentName') or '')}
        for item in form_games[-12:]
    ]
    coverage = _coverage(cur, record, window, cur_panel_only)
    sentence, tone = _sentence(window, record, prev_record, cur + cur_panel_only)

    ctx = _build_context(facts, window, cur, prev, opponent=opponent,
                         source=source_text, validation=validation_text,
                         cur_panel_only=cur_panel_only,
                         prev_panel_only=prev_panel_only)
    candidates = build_candidates(ctx)
    # 首页指标只报本期训练赛总览；旧的过程类候选仍用于「值得关注的变化」下钻，
    # classic_metrics 供底层口径回归使用，接口永远走默认。
    watch = {'field': None, 'fields': []}
    if classic_metrics:
        metrics, findings = select_metrics(candidates), select_findings(candidates)
    else:
        metrics = build_scrim_metrics(ctx, record, cur_panel_only)
        findings = select_findings(candidates, exclude_kinds=('coverage',))
        _attach_finding_matches(findings, ctx)
        watch = build_watch_groups(ctx)

    note = '训练赛战绩来自营地终局面板，比赛过程以官方回放为准。'

    notes = []
    if cur_panel_only:
        notes.append(f'{len(cur_panel_only)} 局只有终局面板，只参与战绩，不参与时间轴指标。')
    missing = sum(1 for item in cur if not item.get('hasTimeline'))
    if missing:
        notes.append(f'{missing} 局缺少完整过程数据，相关指标按有效局数计算。')
    if record['unknown']:
        notes.append(f"{record['unknown']} 局未判定胜负，不计入胜率。")

    watch_fields = watch.get('fields') or []
    watch_field = watch.get('field')
    watch_items = next((item['items'] for item in watch_fields
                        if item['id'] == watch_field), [])
    next_payload = _next_payload(schedule_rows, today, team_names)
    payload = {
        'available': True,
        'reason': None,
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'period': window,
        'fallback_hint': None,
        'coverage': coverage,
        'record': {
            'wins': record['wins'], 'losses': record['losses'],
            'decided': record['decided'], 'unknown': record['unknown'],
            'winRate': record['winRate'],
            'form': list(record.get('form') or []),
            'prev': dict(prev_record),
        },
        'summary': {'sentence': sentence, 'tone': tone, 'note': note},
        'metrics': metrics,
        'findings': findings,
        'watch': watch_items,
        'watchField': watch_field,
        'watchFields': watch_fields,
        'watchDisplayFields': list(watch.get('display') or WATCH_DEFAULT_DISPLAY),
        'next': next_payload,
        'sources': {
            'replay': coverage['withReplay'],
            'panel': coverage['panelGames'],
            'schedule': len(next_payload['items']),
            'note': '来源：官方回放 + 营地终局面板',
        },
        'notes': notes,
    }
    if not classic_metrics:
        period_word = _period_title_word(window)
        payload['findingsTitle'] = f'{period_word}重点发现'
        payload['findingsCountText'] = f'{len(findings)} 项发现'
        payload['findingsEmpty'] = f'{period_word}没有需要单独展开的变化。'
        payload['watchTitle'] = '重点复盘'
        payload['watchCountText'] = f'发现 {len(watch_items)} 场值得关注的对局'
        payload['watchEmpty'] = f'{period_word}没有可复盘的比赛过程。'
        payload['watchNote'] = '按「{}」从差到好排 · 点开看完整过程'.format(
            next((item['label'] for item in watch_fields
                  if item['id'] == watch_field), '最多落后'))
        payload['rankNote'] = '排名对比本期一起训练的对手，同一口径计算'
    return payload


def _normalize_source(source):
    parts = []
    for item in str(source or '').split(','):
        value = item.strip().lower()
        if value and value.isalnum() and value not in parts:
            parts.append(value)
    return ','.join(parts) if parts else DEFAULT_SOURCE


def bucket_key(iso_date, unit="week"):
    """把 YYYY-MM-DD 映射成自然周（返回该 ISO 周的周一）/ 自然月的分桶键。

    unit='week' → 'W2026-W45'；unit='month' → 'M2026-11'。
    其他 unit 返回原日期本身（day 口径）。非法日期返回 None，不猜。
    """
    if not iso_date:
        return None
    try:
        day = date.fromisoformat(str(iso_date)[:10])
    except (TypeError, ValueError):
        return None
    if unit == "month":
        return f"M{day.year}-{day.month:02d}"
    if unit == "week":
        monday = day - timedelta(days=day.weekday())
        iso_year, iso_week, _ = day.isocalendar()
        return f"W{iso_year}-W{iso_week:02d}-{monday.isoformat()}"
    return day.isoformat()


def bucket_rows(rows, date_field, unit="week"):
    """把带日期字段的行按自然周/月分桶。

    返回 [{key, start, end, rows}] 按时间升序；无日期/非法日期的行进
    'undated' 桶并放在最后——绝不丢弃样本，也绝不猜日期。
    """
    buckets = defaultdict(list)
    for row in rows or []:
        key = bucket_key((row or {}).get(date_field), unit)
        buckets[key if key else "undated"].append(row)
    out = []
    for key, items in buckets.items():
        if key == "undated":
            out.append({"key": "undated", "start": None, "end": None, "rows": items})
            continue
        dates = sorted(date.fromisoformat(str(r.get(date_field))[:10]) for r in items)
        out.append({"key": key, "start": dates[0].isoformat(),
                    "end": dates[-1].isoformat(), "rows": items})
    out.sort(key=lambda b: (b["key"] == "undated", b["key"] or ""))
    return out
