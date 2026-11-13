"""赛训决策台 · 统一分析事实表（阶段 1）。

把三类数据接成同一批可直接查询的对局实体：

  终局面板  data/camp_details/<seq>.json      → PanelRow（逐人逐局，A 级）
  官方回放  data/official_replays/camp-*/     → Game（经济/事件/团战/死亡/位置，B 级）
  对手身份  team_clusters / workspace DB      → Opponent（按对面五人签名聚合）

口径（与 README.md 一致）：

- 只有「能判定我方阵营」的回放局进入 ``order``；其余只计入覆盖计数，不参与分析。
- 经济点按索引均匀铺到时间轴（约 30 秒），标 ``approx``，不假装精确。
- 位置在 ``map_calibration`` 可用时换算到 0–1（地图宽度），否则保持原值并标 relative。
- 缺失位置用 ``[0, 0]`` 占位（与仓库既有位置口径一致），消费方必须跳过；不用 0 补真实值。
- 年份：面板 ``startTime`` 只有「月-日 时:分」时补当前年份（仓库既有口径），不猜测具体日期。
- 所有派生指标缺失返回 None，不返回 0 假值。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import map_calibration

try:  # 对手身份聚合是可选的：没有 team_clusters 也能出事实表（用于单测）
    import team_clusters
except Exception:  # pragma: no cover - 只在极端缺模块时触发
    team_clusters = None

PHASES = ((0, 240, '对线期'), (240, 600, '发育期'), (600, None, '后期'))
LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}
CAMP_CODE = {'1': 'blue', '2': 'red'}
CAMP_CODE_REV = {'blue': '1', 'red': '2'}
OBJECTIVE_NAMES = {'8': '暗影主宰', '9': '暴君', '17': '暗影暴君'}
STRUCTURE_IDS = {'10', '20'}
R_NEAR = 22.0  # 近身半径（相对单位，与 analysis_space 同口径）


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _clean(value):
    return str(value or '').replace('\u2060', '').replace('\x00', '').strip()


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def phase_of(seconds):
    """对线 0–4 分钟 / 发育 4–10 分钟 / 后期 10 分钟以后（教练确认口径）。"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return ''
    for low, high, label in PHASES:
        if value >= low and (high is None or value < high):
            return label
    return ''


def clock(seconds):
    """秒数 → m:ss；无效返回 '—'。"""
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return '—'
    return f'{total // 60}:{total % 60:02d}'


def time_at(index, count, duration):
    if not count or count <= 1:
        return 0.0
    return float(index) * float(duration) / float(count - 1)


def value_at(seconds, series, duration):
    """线性插值；越界夹到端点，不抛异常。"""
    if not series or not duration or duration <= 0:
        return None
    count = len(series)
    if count == 1:
        return float(series[0])
    position = max(0.0, min(float(count - 1), float(seconds) / float(duration) * (count - 1)))
    low = int(math.floor(position))
    high = min(count - 1, low + 1)
    ratio = position - low
    return float(series[low]) * (1 - ratio) + float(series[high]) * ratio


def percentile(values, q):
    numbers = sorted(float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    position = (len(numbers) - 1) * max(0.0, min(100.0, float(q))) / 100.0
    low = int(math.floor(position))
    high = min(len(numbers) - 1, low + 1)
    weight = position - low
    return numbers[low] * (1 - weight) + numbers[high] * weight


def median(values):
    return percentile(values, 50)


def mean(values):
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return sum(numbers) / len(numbers) if numbers else None


def wilson(success, total, z=1.96):
    """Wilson 区间，返回百分数 (low, high)；样本 0 返回 (None, None)。"""
    if not total or total <= 0:
        return None, None
    phat = success / total
    denominator = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin) * 100, min(1.0, center + margin) * 100


def objective_name(event):
    """事件 → 资源/建筑的中文名。dtType=1 资源，dtType=2 建筑（沿用 v1.5.22 口径）。"""
    event = event or {}
    dt_type = str(event.get('dtType') or '')
    dt_id = str(event.get('dtId') or '')
    if dt_type == '1':
        return OBJECTIVE_NAMES.get(dt_id, '野区资源')
    if dt_type == '2':
        return '水晶' if dt_id in STRUCTURE_IDS else '防御塔'
    return '事件'


def format_objective(event, own_camp=None):
    """把回放事件整理成决策台统一格式；不把未知阵营猜成我方。"""
    event = event or {}
    dt_type = str(event.get('dtType') or '')
    kind = 'resource' if dt_type == '1' else ('building' if dt_type == '2' else 'other')
    side = None
    winner = str(event.get('killerCamp') or '')
    holder = str(event.get('dtCamp') or '')
    if own_camp and CAMP_CODE_REV.get(own_camp):
        own_code = CAMP_CODE_REV[own_camp]
        if winner:
            side = 'own' if winner == own_code else 'enemy'
        elif holder:
            side = 'own' if holder == own_code else 'enemy'
    return {
        'name': objective_name(event),
        'kind': kind,
        'camp': side or 'unknown',
        't': _float(event.get('timeSec')),
    }


def _parse_start(raw, year):
    """营地 startTime 有两种：'11-02 13:47' 与 '2026-11-02 13:47'。"""
    text = _clean(raw)
    full = re.match(r'^(\d{4})-(\d{2})-(\d{2})', text)
    if full:
        return f'{full.group(1)}-{full.group(2)}-{full.group(3)}', text
    short = re.match(r'^(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}:\d{2}))?', text)
    if short:
        month, day = int(short.group(1)), int(short.group(2))
        clock_part = short.group(3) or ''
        start = f'{month:02d}-{day:02d}' + (f' {clock_part}' if clock_part else '')
        return f'{int(year):04d}-{month:02d}-{day:02d}', start
    return '', text


def _lane(code):
    number = _int(code)
    return LANES.get(number, '') if number is not None else ''


# ---------------------------------------------------------------------------
# 终局面板
# ---------------------------------------------------------------------------
def _role_row(seq, side, own_camp, own_win, role, *, date, start, duration, minutes,
              opponent_id, opponent_name):
    basic = role.get('basicInfo') or {}
    stats = role.get('battleStats') or {}
    records = role.get('battleRecords') or {}
    hero = ((records.get('usedHero') or {}).get('heroName')) or ''
    participation = _float(stats.get('joinGamePercent'))
    return {
        'seq': seq,
        'date': date,
        'start': start,
        'camp': side,
        'side': 'own' if side == own_camp else 'enemy',
        'opponentId': opponent_id,
        'opponentName': opponent_name,
        'won': (side == own_camp) == own_win,
        'minutes': minutes,
        'playerId': _clean(basic.get('playerId')),
        'name': _clean(basic.get('roleName')),
        'lane': _lane(records.get('position')),
        'hero': _clean(hero),
        'kills': _int(stats.get('killCnt')),
        'deaths': _int(stats.get('deadCnt')),
        'assists': _int(stats.get('assistCnt')),
        'gold': _int(stats.get('money')),
        'heroDamage': _int(stats.get('totalHeroHurtCnt')),
        'damage': _int(stats.get('totalHurtCnt')),
        'taken': _int(stats.get('totalBehurtCnt')),
        'participation': round(participation * 100, 1) if participation is not None else None,
        'towerDamage': _int(stats.get('buildingDamage')),
        'control': _int(stats.get('ctrlTime')),
        'heal': _int(stats.get('healCnt')),
        'cs': _int(stats.get('killSoldier')),
        'jungleGold': _int(stats.get('monsterCoin')),
        'grade': _float(stats.get('gradeGame')),
        'durationSec': duration,
    }


def load_panels(camp_dir, *, year=None):
    """读终局面板。返回 ({seq: PanelMeta}, [PanelRow, ...])。"""
    year = year or datetime.now().year
    panels, rows = {}, []
    camp_dir = Path(camp_dir)
    if not camp_dir.is_dir():
        return panels, rows
    for path in sorted(camp_dir.glob('*.json')):
        payload = read_json(path)
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            continue
        head = data.get('head') or {}
        battle = data.get('battle') or {}
        own_camp = CAMP_CODE.get(str(head.get('acntCamp') or ''))
        if own_camp is None:
            continue
        seq = path.stem
        date, start = _parse_start(battle.get('startTime') or battle.get('dtEventTime'), year)
        used = _float(battle.get('usedTime'))
        duration = used if used is not None and used > 0 else 0.0
        minutes = round(duration / 60, 2) if duration else 0.0
        own_win = bool(head.get('gameResult'))
        enemy_camp = 'red' if own_camp == 'blue' else 'blue'
        panel = {
            'seq': seq, 'own': own_camp, 'enemy': enemy_camp,
            'start': start, 'date': date, 'duration': duration,
            'map': _clean(battle.get('mapName')), 'win': own_win,
            'ownRoster': [], 'enemyRoster': [],
            'bans': {'blue': [], 'red': []},
            'picks': {'blue': [], 'red': []},
        }
        for team_key, side in (('blueTeam', 'blue'), ('redTeam', 'red')):
            team = data.get(team_key) or {}
            for field, target in (('banHeros', 'bans'), ('pickHeros', 'picks')):
                names = []
                for item in team.get(field) or []:
                    name = _clean((item or {}).get('heroName') if isinstance(item, dict) else item)
                    if name:
                        names.append(name)
                panel[target][side] = names
        for side_key, side in (('blueRoles', 'blue'), ('redRoles', 'red')):
            for role in data.get(side_key) or []:
                row = _role_row(seq, side, own_camp, own_win, role,
                                date=date, start=start, duration=duration, minutes=minutes,
                                opponent_id=None, opponent_name=None)
                rows.append(row)
                (panel['ownRoster'] if side == own_camp else panel['enemyRoster']).append(row)
        panels[seq] = panel
    return panels, rows


# ---------------------------------------------------------------------------
# 对手身份（对面五人签名 → 战队名）
# ---------------------------------------------------------------------------
def _opponent_signature(panel):
    ids = sorted(item['playerId'] for item in panel['enemyRoster'] if item.get('playerId'))
    digest = hashlib.sha1('|'.join(ids).encode('utf-8')).hexdigest()
    return 'team-' + digest[:12]


def _opponent_names(camp_dir, panels, db_path):
    """优先用 team_clusters + workspace DB 的显示名；访问不到时用稳定序号兜底。"""
    names = {}
    merges = {}
    if team_clusters is not None:
        try:
            listed = team_clusters.list_teams(camp_dir, db_path) if db_path else None
            if isinstance(listed, dict):
                for team in listed.get('teams') or []:
                    display = _clean(team.get('displayName') or team.get('name'))
                    if display:
                        names[team.get('id')] = display
        except Exception:  # pragma: no cover - 查询失败不阻塞分析
            names = {}
    # 兜底：按首次出现顺序编号
    ordered = sorted({_opponent_signature(p) for p in panels.values()},
                     key=lambda key: min((panels[seq]['start'] or panels[seq]['date'])
                                         for seq, panel in panels.items()
                                         if _opponent_signature(panel) == key))
    for index, key in enumerate(ordered, 1):
        names.setdefault(key, f'待命名战队 #{index}')
    return names, merges


# ---------------------------------------------------------------------------
# 官方回放
# ---------------------------------------------------------------------------
def _player_index(normalized, panel):
    """回放 objID ↔ playerId ↔ 面板昵称/分路。"""
    players = normalized.get('players') or []
    battles = normalized.get('battles') or {}
    player_map = battles.get('playerMap') or {}

    hero_to_player = {}
    for player in players:
        key = (str(player.get('camp') or ''), player.get('heroId'))
        if player.get('playerId'):
            hero_to_player.setdefault(key, str(player.get('playerId')))

    obj_to_player, obj_to_camp = {}, {}
    for obj_id, info in player_map.items():
        camp = str(info.get('camp') or '')
        obj_to_camp[str(obj_id)] = camp
        player_id = hero_to_player.get((camp, info.get('heroId')))
        if player_id:
            obj_to_player[str(obj_id)] = player_id

    roster = {}  # (side, hero) -> {'name','lane'}
    if panel:
        for row in panel['ownRoster']:
            roster[('own', row['hero'])] = row
        for row in panel['enemyRoster']:
            roster[('enemy', row['hero'])] = row

    enriched = []
    for player in players:
        player_id = str(player.get('playerId') or '')
        if not player_id:
            continue
        camp = str(player.get('camp') or '')
        side = 'own' if panel and camp == CAMP_CODE_REV.get(panel['own']) else 'enemy'
        hero = _clean(player.get('hero'))
        panel_row = roster.get((side, hero)) or {}
        enriched.append({
            'playerId': player_id,
            'hero': hero,
            'camp': camp,
            'side': side,
            'name': panel_row.get('name') or '',
            'lane': panel_row.get('lane') or '',
        })
    return enriched, obj_to_player, obj_to_camp, player_map


def _normalize_positions(positions_payload, calibration):
    series = {}
    for player in (positions_payload or {}).get('players') or []:
        player_id = str(player.get('playerId') or '')
        arr = player.get('posArr') or []
        if not player_id or not isinstance(arr, list):
            continue
        converted = []
        for point in arr:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                converted.append([0, 0])
                continue
            x, y = _float(point[0]), _float(point[1])
            if x is None or y is None or (x == 0 and y == 0):
                converted.append([0, 0])
                continue
            if calibration and calibration.get('calibrated'):
                normalized = map_calibration.normalize((x, y), calibration)
                converted.append([round(normalized[0], 4), round(normalized[1], 4)]
                                 if normalized else [0, 0])
            else:
                converted.append([x, y])
        series[player_id] = converted
    return series


def _load_replay(folder, panel, panels, opponent_names, calibration, seq_to_opponent):
    normalized = read_json(Path(folder) / 'normalized.json')
    if not isinstance(normalized, dict):
        return None, 'normalized.json 缺失或损坏'
    match = normalized.get('match') or {}
    duration = _float(match.get('durationSec')) or 0.0
    if duration <= 0:
        return None, '回放缺少时长'
    seq = Path(folder).name.split('camp-')[-1]
    own_camp = panel.get('own') if panel else None
    if own_camp is None:
        return None, '回放没有配到终局面板，无法判定我方阵营'
    win_camp = CAMP_CODE.get(str(match.get('winCamp') or ''))
    result = None if win_camp is None else ('win' if win_camp == own_camp else 'loss')

    raw_diff = [_float(value) for value in ((normalized.get('economy') or {}).get('diff') or [])]
    # 采样索引 → 时间轴。缺失点保留原来的时间位置（不能删掉后重排，
    # 否则后面的经济点会整体前移，掉点窗口的经济差会算错时间段）。
    samples = [(round(time_at(index, len(raw_diff), duration), 1), value)
               for index, value in enumerate(raw_diff) if value is not None]
    own_diff = [value if own_camp == 'blue' else -value for _, value in samples]
    times = [moment for moment, _ in samples]

    events = (normalized.get('events') or {})
    key_events = events.get('key') if isinstance(events.get('key'), list) else []
    extended = events.get('extended') if isinstance(events.get('extended'), list) else []
    battles = normalized.get('battles') or {}
    fights = battles.get('fights') if isinstance(battles.get('fights'), list) else []
    deaths = battles.get('deaths') if isinstance(battles.get('deaths'), list) else []

    players, obj_to_player, obj_to_camp, player_map = _player_index(normalized, panel)
    lanes = {item['playerId']: item['lane'] for item in players if item['lane']}
    heroes = {item['playerId']: item['hero'] for item in players if item['hero']}
    camp_players = {'1': [], '2': []}
    for item in players:
        camp_players.setdefault(item['camp'], []).append(item['playerId'])
    positions = _normalize_positions(read_json(Path(folder) / 'positions.json'), calibration)
    has_positions = any(any(point and (point[0] or point[1]) for point in arr)
                        for arr in positions.values()) if positions else False

    opponent_id = seq_to_opponent.get(seq)
    opponent_name = opponent_names.get(opponent_id) or ''
    label = f'{panel["date"][5:7]}/{panel["date"][8:10]} · 对阵 {opponent_name}'.strip()
    if label.endswith('对阵'):
        label = f'{panel["date"][5:7]}/{panel["date"][8:10]} · 对局 {seq}'
    return {
        'id': seq,
        'label': label,
        'date': panel.get('date') or '',
        'start': panel.get('start') or '',
        'opponentId': opponent_id,
        'opponentName': opponent_name,
        'ownCamp': own_camp,
        'enemyCamp': 'red' if own_camp == 'blue' else 'blue',
        'winner': win_camp,
        'result': result,
        'duration': duration,
        'diff': [value for value in raw_diff if value is not None],
        'ownDiff': own_diff,
        'times': times,
        'approx': True,
        'events': key_events,
        'extended': extended,
        'fights': fights,
        'deaths': deaths,
        'positions': positions,
        'relative': not bool(calibration and calibration.get('calibrated')),
        'players': players,
        'objToPlayer': obj_to_player,
        'objToCamp': obj_to_camp,
        'playerMap': player_map,
        'lanes': lanes,
        'heroes': heroes,
        'campPlayers': camp_players,
        'hasPositions': has_positions,
        'hasFights': bool(fights),
        'hasEvents': bool(key_events),
        'hasEconomy': bool(own_diff),
        'mapWidth': _float((calibration or {}).get('width')),
        'fightsNote': None if fights else '本局没有团战段（battles.fights 为空）',
    }, None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def data_signature(replays_dir, camp_dir, db_path=None, data_dir=None):
    """扫盘签名：目录内文件数量 + 最大 mtime。用于 API 缓存。

    positions.json 与地图定标文件都参与签名——否则只改位置/定标时，
    /api/decision/* 会一直返回旧 facts。
    """
    def scan(directory, pattern):
        path = Path(directory)
        if not path.is_dir():
            return (0, 0.0)
        count, latest = 0, 0.0
        for item in path.glob(pattern):
            try:
                latest = max(latest, item.stat().st_mtime)
            except OSError:
                continue
            count += 1
        return count, round(latest, 3)

    camp = scan(camp_dir, '*.json')
    replay_files = scan(replays_dir, 'camp-*/normalized.json')
    positions = scan(replays_dir, 'camp-*/positions.json')
    calibration = (0, 0.0)
    if data_dir:
        file_path = Path(data_dir) / map_calibration.CALIBRATION_FILE
        if file_path.is_file():
            try:
                calibration = (1, round(file_path.stat().st_mtime, 3))
            except OSError:
                calibration = (1, 0.0)
    db = (0, 0.0)
    if db_path and Path(db_path).is_file():
        try:
            db = (1, round(Path(db_path).stat().st_mtime, 3))
        except OSError:
            db = (1, 0.0)
    return (camp, replay_files, positions, calibration, db)


def load_facts(replays_dir, camp_dir, data_dir=None, db_path=None, *, now=None):
    """加载统一事实表。所有分析模块只读这个返回值。"""
    year = (now or datetime.now()).year
    calibration = map_calibration.load(data_dir) if data_dir else None
    panels, rows = load_panels(camp_dir, year=year)

    names, merges = _opponent_names(camp_dir, panels, db_path)
    seq_to_opponent = {seq: _opponent_signature(panel) for seq, panel in panels.items()}
    for seq, opponent_id in seq_to_opponent.items():
        for row in rows:
            if row['seq'] == seq:
                row['opponentId'] = opponent_id
                row['opponentName'] = names.get(opponent_id, '')

    games = {}
    errors = []
    replay_games = 0
    replays_dir = Path(replays_dir)
    for folder in sorted(replays_dir.glob('camp-*')) if replays_dir.is_dir() else []:
        replay_games += 1
        seq = folder.name.split('camp-')[-1]
        game, error = _load_replay(folder, panels.get(seq), panels, names, calibration,
                                   seq_to_opponent)
        if error:
            errors.append({'game': seq, 'reason': error})
            continue
        games[seq] = game

    order = sorted(games, key=lambda seq: (games[seq]['start'] or games[seq]['date'] or '', seq))
    wins = sum(1 for seq in order if games[seq]['result'] == 'win')
    losses = sum(1 for seq in order if games[seq]['result'] == 'loss')
    position_games = sum(1 for seq in order if games[seq]['hasPositions'])
    fight_games = sum(1 for seq in order if games[seq]['hasFights'])
    dates = sorted({game['date'] for game in games.values() if game['date']})

    # 对手聚合
    opponent_groups = defaultdict(lambda: {'id': '', 'name': '', 'seqs': [], 'replayGames': 0})
    for seq, panel in panels.items():
        opponent_id = seq_to_opponent.get(seq)
        if not opponent_id:
            continue
        group = opponent_groups[opponent_id]
        group['id'] = opponent_id
        group['name'] = names.get(opponent_id, '')
        group['seqs'].append(seq)
        if seq in games:
            group['replayGames'] += 1
    opponents = sorted(opponent_groups.values(),
                       key=lambda item: (-item['replayGames'], item['name']))
    for opponent in opponents:
        opponent['seqs'].sort()

    coverage = {
        'panelGames': len(panels),
        'panelRows': len(rows),
        'replayGames': replay_games,
        'pairedGames': len(order),
        'games': len(order),
        'withResult': wins + losses,
        'wins': wins,
        'losses': losses,
        'positionGames': position_games,
        'fightGames': fight_games,
        'fights': sum(len(games[seq]['fights']) for seq in order),
        'deaths': sum(len(games[seq]['deaths']) for seq in order),
        'events': sum(len(games[seq]['events']) for seq in order),
        'dateRange': [dates[0], dates[-1]] if dates else [],
        'calibrated': bool(calibration and calibration.get('calibrated')),
        'calibrationNote': '坐标已按本批位置分位定标；距离单位为地图宽度。'
                           if calibration and calibration.get('calibrated')
                           else '坐标未定标，距离为回放相对单位。',
        'opponents': {
            'total': len(opponents),
            'replayOpponents': sum(1 for item in opponents if item['replayGames'] > 0),
            'with3Games': sum(1 for item in opponents if item['replayGames'] >= 3),
        },
        'identity': {
            'playersWithNickname': sum(1 for row in rows if row['name']),
            'namedOpponents': sum(1 for item in opponents
                                  if item['name'] and not item['name'].startswith('待命名')),
        },
        'errors': len(errors),
    }

    bounds = position_bounds(games.values())
    return {
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'coverage': coverage,
        'calibration': calibration,
        'positionBounds': bounds,
        'games': games,
        'order': order,
        'panels': panels,
        'rows': rows,
        'opponents': opponents,
        'seqToOpponent': seq_to_opponent,
        'opponentNames': names,
        'labels': {seq: games[seq]['label'] for seq in order},
        'errors': errors,
        'notes': [
            '经济点按采样索引均匀铺到时间轴（约 30 秒一点），页面显示为近似时间。',
            '位置坐标在定标可用时为地图宽度比例；否则为回放相对单位，不能直接当米/格。',
            '每名对手目前多为 1 局回放，对手习惯类结论只做单局观察，不外推。',
            '未命名选手/对手保留营地昵称，不强行归到某个身份。',
        ],
    }


# ---------------------------------------------------------------------------
# 过滤与常用视图
# ---------------------------------------------------------------------------
def filter_games(facts, *, game=None, opponent=None, date_from=None, date_to=None, result=None):
    """按范围过滤有回放且能判定阵营的对局；未知参数值直接过滤为空。"""
    selected = []
    for seq in facts.get('order') or []:
        item = facts['games'][seq]
        if game and str(game) != seq:
            continue
        if opponent:
            if opponent not in (item.get('opponentId'), item.get('opponentName')):
                continue
        if result and item.get('result') != result:
            continue
        if date_from and (item.get('date') or '') < date_from:
            continue
        if date_to and (item.get('date') or '') > date_to:
            continue
        selected.append(item)
    return selected


def game_roster(game):
    """回放局的我方/敌方五人（带昵称、英雄、分路）。"""
    roster = {'own': [], 'enemy': []}
    for item in game.get('players') or []:
        roster.setdefault(item['side'], []).append(item)
    for side in roster:
        roster[side].sort(key=lambda item: (item.get('lane') or 'zz', item.get('hero') or ''))
    return roster


def objective_events(game, *, kinds=('resource', 'building')):
    """回放关键事件里取资源/建筑，附我方视角。"""
    out = []
    for event in game.get('events') or []:
        formatted = format_objective(event, game.get('ownCamp'))
        if formatted['kind'] in kinds and formatted['t'] is not None:
            formatted['dtId'] = str((event or {}).get('dtId') or '')
            out.append(formatted)
    out.sort(key=lambda item: item['t'])
    return out


def death_events(game):
    """死亡事件 + 同阵营最近队友距离（定标后单位为地图宽度）。"""
    own_camp = game.get('ownCamp')
    players = game.get('players') or []
    by_camp = defaultdict(list)
    for item in players:
        by_camp[item['camp']].append(item['playerId'])
    side_of_camp = {}
    if own_camp:
        side_of_camp[CAMP_CODE_REV[own_camp]] = 'own'
        side_of_camp['2' if own_camp == 'blue' else '1'] = 'enemy'
    map_width = _float(game.get('mapWidth'))
    near_limit = (R_NEAR / map_width) if map_width else R_NEAR
    out = []
    for death in game.get('deaths') or []:
        camp = str(death.get('camp') or '')
        t = _float(death.get('timeSec'))
        if t is None:
            continue
        obj_id = str(death.get('objID') or '')
        player_id = game.get('objToPlayer', {}).get(obj_id) or ''
        mates = [pid for pid in by_camp.get(camp, []) if pid != player_id]
        point = _position_at(game, player_id, int(round(t)))
        nearest, near_count = None, 0
        for mate in mates:
            other = _position_at(game, mate, int(round(t)))
            if point and other:
                distance = math.dist(point, other)
                nearest = distance if nearest is None else min(nearest, distance)
                if distance <= near_limit:
                    near_count += 1
        out.append({
            't': round(float(t), 1),
            'objId': obj_id,
            'player': player_id,
            'hero': _hero_of(game, obj_id),
            'side': side_of_camp.get(camp, 'unknown'),
            'x': _float(death.get('x')),
            'y': _float(death.get('y')),
            'nearestAllyDist': round(nearest, 4) if nearest is not None else None,
            'nearAllies': near_count,
            'isolated': None if nearest is None else bool(nearest > near_limit),
        })
    return out


def player_points(game, player_id, *, until=240, step=5):
    """按秒取某名选手的位置轨迹，跳过缺失点；返回 [(t, x, y), ...]。"""
    arr = (game.get('positions') or {}).get(str(player_id)) or []
    points = []
    for second in range(0, min(int(until), len(arr)), max(1, int(step))):
        point = arr[second]
        if not point or (point[0] == 0 and point[1] == 0):
            continue
        points.append((float(second), float(point[0]), float(point[1])))
    return points


def position_bounds(games):
    """未定标时的坐标范围，用于把相对坐标归一化到 0–1（不改变 distanceUnit 口径）。"""
    xs, ys = [], []
    for game in games:
        if not game.get('relative'):
            continue
        for arr in (game.get('positions') or {}).values():
            for point in arr or []:
                if not point or (point[0] == 0 and point[1] == 0):
                    continue
                xs.append(float(point[0]))
                ys.append(float(point[1]))
    if not xs or not ys:
        return None
    return {'xMin': min(xs), 'xMax': max(xs), 'yMin': min(ys), 'yMax': max(ys)}


def _position_at(game, player_id, second):
    arr = (game.get('positions') or {}).get(player_id) or []
    if second < 0 or second >= len(arr):
        return None
    point = arr[second]
    if not point or (point[0] == 0 and point[1] == 0):
        return None
    return (float(point[0]), float(point[1]))


def _hero_of(game, obj_id):
    player_id = game.get('objToPlayer', {}).get(str(obj_id))
    return (game.get('heroes') or {}).get(player_id, '') if player_id else ''


def fight_events(game):
    """团战整理，我方视角。返回 [{fightId,startSec,endSec,duration,ownParticipants,...}]。"""
    own_camp = game.get('ownCamp')
    own_code = CAMP_CODE_REV.get(own_camp)
    enemy_code = '2' if own_code == '1' else '1'
    out = []
    for fight in game.get('fights') or []:
        start = _float(fight.get('startSec'))
        end = _float(fight.get('endSec'))
        if start is None:
            continue
        participants = fight.get('participants') or []
        arrival = {'1': [], '2': []}
        for participant in participants:
            moment = _float(participant.get('timeSec'))
            if moment is None:
                continue
            arrival.setdefault(str(participant.get('camp') or ''), []).append(moment)
        own_arrivals = sorted(arrival.get('1' if own_code == '1' else '2', []))
        enemy_arrivals = sorted(arrival.get('1' if enemy_code == '1' else '2', []))
        kills = fight.get('kills') or []
        own_kills = sum(1 for kill in kills if str(kill.get('killerCamp') or '') == own_code)
        enemy_kills = sum(1 for kill in kills if str(kill.get('killerCamp') or '') == enemy_code)
        own_early = sum(1 for moment in own_arrivals if moment <= start + 3)
        enemy_early = sum(1 for moment in enemy_arrivals if moment <= start + 3)
        out.append({
            'fightId': str(fight.get('fightId') or ''),
            'startSec': round(float(start), 1),
            'endSec': round(float(end), 1) if end is not None else None,
            'duration': round(max(0.0, (end or start) - start), 1),
            'ownParticipants': len(own_arrivals),
            'enemyParticipants': len(enemy_arrivals),
            'missingParticipants': max(0, len(participants) - len(own_arrivals) - len(enemy_arrivals)),
            'arrivalDiff': round(own_arrivals[0] - enemy_arrivals[0], 1)
                            if own_arrivals and enemy_arrivals else None,
            'advStart': own_early - enemy_early,
            'ownKills': own_kills,
            'enemyKills': enemy_kills,
            'killDiff': own_kills - enemy_kills if kills else None,
            'won': (own_kills - enemy_kills > 0) if kills else None,
            'lateJoins': sum(1 for moment in own_arrivals if moment > start + 5),
            'firstSide': None if not (own_arrivals and enemy_arrivals)
                         else ('own' if own_arrivals[0] < enemy_arrivals[0]
                               else ('enemy' if enemy_arrivals[0] < own_arrivals[0] else 'tie')),
            'ownCamp': own_camp,
        })
    return out


def wipes(game):
    """团灭：一方 5 人全部阵亡（同秒歧义不推断先后）。"""
    own_code = CAMP_CODE_REV.get(game.get('ownCamp'))
    rows = []
    for fight in game.get('fights') or []:
        details = fight.get('details') or []
        counts = Counter()
        for detail in details:
            if _int(detail.get('deaths')) and _int(detail.get('deaths')) > 0:
                counts[str(detail.get('camp') or '')] += 1
        own_dead = counts.get(own_code, 0)
        enemy_code = '2' if own_code == '1' else '1'
        enemy_dead = counts.get(enemy_code, 0)
        if max(own_dead, enemy_dead) >= 5:
            rows.append({
                'fightId': str(fight.get('fightId') or ''),
                't': round(float(fight.get('startSec') or 0), 1),
                'side': 'own' if own_dead >= 5 else 'enemy',
                'note': '同秒击杀不推断先后',
            })
    return rows
