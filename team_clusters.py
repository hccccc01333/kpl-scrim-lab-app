"""对手战队聚类：把营地十人面板里"对面这 5 个人"聚成战队。

为什么需要
----------
营地详情只记录「这一局对面 5 个 playerId」，没有人告诉平台他们属于哪个战队。
过去靠 match.opponent 自由文本，绝大多数为空，于是分析页只能显示"对手未知"。

做法
----
1. **身份来自阵容签名**：把对面 5 个 playerId 排序后哈希，得到不可变的 cluster id。
   重导入、改名、合并都不会改变它；原始比赛数据一个字节都不动。
2. **人工决策单独存放**：命名 / 教练 / 合并写进 team_clusters 表，覆盖层生效。
3. **兜底显示名**：「待命名对手 #N」，N 按首次出现时间排序，只用于显示，不落库。
   教练改完名立刻全量生效，历史对局不用批量改。
4. **合并分两级**：5 人完全相同 → 自动同一 cluster；3–4 人重合 → 只给"建议合并"，
   必须人工确认，避免把轮换阵容误判成同一支队。

对外只暴露 list_teams / rename_team / merge_team 三个入口。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

# 重合几个人才提示"可能是同一支队"（整队 5 人，3 人以上才给建议）
SUGGEST_OVERLAP = 3

# 营地 position 编码 → 中文路名（与 bp_camp.POSITION_LANES 同源）
LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}

TABLE = 'team_clusters'


# ---------------------------------------------------------------- 文本清洗
def clean_name(value) -> str:
    """去掉零宽字符与首尾空白。营地昵称里混着 U+2060 这类字符，直接显示会串位。"""
    if value is None:
        return ''
    text = str(value)
    text = ''.join(char for char in text
                   if unicodedata.category(char) != 'Cf')
    return ' '.join(text.split())


def is_placeholder(name) -> bool:
    """「待命名对手 #N」是显示兜底，不是主数据里的真实队名。"""
    text = clean_name(name)
    return not text or text.startswith('待命名')


def load_workspace_teams(db_path) -> dict:
    """读取工作区战队表。战队名的权威来源是 workspace_store.teams；覆盖层只做兼容。"""
    path = Path(db_path)
    if not path.is_file():
        return {}
    try:
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute('SELECT id, name, coach, status FROM teams').fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return {row['id']: {'name': row['name'], 'coach': row['coach'], 'status': row['status']}
            for row in rows}


def _sid(player_id) -> str:
    return str(player_id or '').strip()


# ---------------------------------------------------------------- 读取面板
def _camp_key(value) -> str | None:
    return {'1': 'blue', '2': 'red', 'blue': 'blue', 'red': 'red'}.get(str(value or ''))


def load_panels(camp_dir) -> list[dict]:
    """逐局读出「我方 / 对面」两侧阵容。读不出的局跳过，不猜测。"""
    camp_dir = Path(camp_dir)
    panels = []
    if not camp_dir.is_dir():
        return panels
    for path in sorted(camp_dir.glob('*.json')):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            continue
        head = data.get('head') or {}
        own = _camp_key(head.get('acntCamp'))
        if own not in ('blue', 'red'):
            continue
        enemy = 'red' if own == 'blue' else 'blue'
        own_roles = data.get(f'{own}Roles') or []
        enemy_roles = data.get(f'{enemy}Roles') or []
        if len(enemy_roles) != 5:
            continue
        battle = data.get('battle') or {}
        # 胜负：head.gameResult 是「本人这一局是否获胜」，营地详情没有独立的 match 段
        result = head.get('gameResult')
        win = result if isinstance(result, bool) else None
        panels.append({
            'seq': path.stem,
            'own': own,
            'enemy': enemy,
            'start': clean_name(battle.get('startTime')),
            'duration': battle.get('usedTime') or head.get('durationSec'),
            'map': clean_name(battle.get('mapName')),
            'win': win,
            'own_roster': _roster(own_roles),
            'enemy_roster': _roster(enemy_roles),
        })
    panels.sort(key=lambda item: (item['start'] or '', item['seq']))
    return panels


def _roster(roles) -> list[dict]:
    out = []
    for role in roles:
        role = role or {}
        basic = role.get('basicInfo') or {}
        records = role.get('battleRecords') or {}
        stats = role.get('battleStats') or {}
        hero = (records.get('usedHero') or {}).get('heroName')
        out.append({
            'id': _sid(basic.get('playerId')),
            'name': clean_name(basic.get('roleName')),
            'hero': clean_name(hero),
            'lane': LANES.get(_int(records.get('position')), ''),
            'kills': _int(stats.get('killCnt')),
            'deaths': _int(stats.get('deadCnt')),
            'assists': _int(stats.get('assistCnt')),
            'gold': _int(stats.get('money')),
            'damage': _int(stats.get('totalHurtCnt')),
            # 对英雄伤害：totalHurtCnt 含兵线/野怪，做"分均输出"会把量级放大 4 倍
            'heroDamage': _int(stats.get('totalHeroHurtCnt')),
            'taken': _int(stats.get('totalBehurtCnt')),
            'control': _int(stats.get('ctrlTime')),
            'heal': _int(stats.get('healCnt')),
            'participation': _float(stats.get('joinGamePercent')),
            'towers': _int(stats.get('towerCnt')),
            'grade': _float(stats.get('gradeGame')),
        })
    return out


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 聚类
def signature(panel) -> str:
    ids = sorted(item['id'] for item in panel['enemy_roster'] if item['id'])
    digest = hashlib.sha1('|'.join(ids).encode('utf-8')).hexdigest()
    return 'team-' + digest[:12]


def build(panels) -> dict:
    """纯计算：把面板聚成战队，返回 {clusters: [...], suggestions: [...]}。"""
    groups: dict[str, dict] = {}
    for panel in panels:
        key = signature(panel)
        group = groups.setdefault(key, {
            'id': key, 'seqs': [], 'matches': 0, 'wins': 0, 'losses': 0,
            'firstSeen': None, 'lastSeen': None, 'heroes': {},
            'players': {}, 'games': [],
            'totals': _new_record({}),
        })
        group['seqs'].append(panel['seq'])
        group['games'].append({'seq': panel['seq'], 'start': panel['start'] or '',
                               'win': panel['win'], 'map': panel['map'],
                               'duration': panel['duration']})
        minutes = (panel['duration'] or 0) / 60
        # 队伍口径：每局只累加一次时间，五人数据相加得队内合计
        totals = group['totals']
        totals['games'] += 1
        totals['seconds'] += minutes * 60
        for player in panel['enemy_roster']:
            for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'heroDamage', 'taken', 'control', 'heal', 'towers'):
                totals[key] += player.get(key) or 0
        group['matches'] += 1
        if panel['win'] is True:
            group['wins'] += 1
        elif panel['win'] is False:
            group['losses'] += 1
        start = panel['start'] or ''
        if start and (group['firstSeen'] is None or start < group['firstSeen']):
            group['firstSeen'] = start
        if start and (group['lastSeen'] is None or start > group['lastSeen']):
            group['lastSeen'] = start
        for player in panel['enemy_roster']:
            if not player['id']:
                continue
            record = group['players'].setdefault(player['id'], {
                'id': player['id'], 'name': player['name'], 'lane': player['lane'], 'games': 0})
            record['games'] += 1
            if not record['name'] and player['name']:
                record['name'] = player['name']
            if not record.get('lane') and player['lane']:
                record['lane'] = player['lane']
            if player['hero']:
                group['heroes'][player['hero']] = group['heroes'].get(player['hero'], 0) + 1

    clusters = list(groups.values())
    # 编号只用于显示：按首次出现时间排，稳定不重排
    clusters.sort(key=lambda item: (item['firstSeen'] or '9999', item['id']))

    suggestions = []
    for index, left in enumerate(clusters):
        left_ids = set(left['players'])
        for right in clusters[index + 1:]:
            shared = left_ids & set(right['players'])
            if SUGGEST_OVERLAP <= len(shared) < 5:
                suggestions.append({'from': left['id'], 'into': right['id'], 'overlap': len(shared),
                                    'players': sorted(shared)})
    return {'clusters': clusters, 'suggestions': suggestions}


# ---------------------------------------------------------------- 人工决策
def _connect(db_path):
    connection = sqlite3.connect(str(db_path))
    connection.execute(
        f'CREATE TABLE IF NOT EXISTS {TABLE} (key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
    return connection


def load_overrides(db_path) -> dict:
    path = Path(db_path)
    if not path.is_file():
        return {}
    try:
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        try:
            rows = connection.execute(f'SELECT key, body FROM {TABLE}').fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    out = {}
    for key, body in rows:
        try:
            value = json.loads(body)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            out[key] = value
    return out


def save_override(db_path, key, patch: dict):
    overrides = load_overrides(db_path)
    body = {**overrides.get(key, {}), **{k: v for k, v in patch.items() if v is not None}}
    connection = _connect(db_path)
    try:
        connection.execute(
            f'INSERT INTO {TABLE}(key, body, updated_at) VALUES(?,?,strftime(\'%s\',\'now\')) '
            'ON CONFLICT(key) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at',
            (key, json.dumps(body, ensure_ascii=False)))
        connection.commit()
    finally:
        connection.close()
    return body


def rename_team(db_path, key, name=None, coach=None, *, sync_workspace=True):
    """命名同时写工作区主数据与兼容覆盖层。

    工作区 `teams` 是权威来源；覆盖层保留给旧版本和未迁移数据，读取时只作兜底。
    """
    cleaned_name = clean_name(name) if name is not None else None
    cleaned_coach = clean_name(coach) if coach is not None else None
    body = save_override(db_path, key, {'name': cleaned_name, 'coach': cleaned_coach})
    if sync_workspace and (cleaned_name or cleaned_coach is not None):
        from workspace_store import Workspace
        workspace = Workspace(db_path).ensure_schema()
        if cleaned_name:
            workspace.upsert_team(key, name=cleaned_name, coach=cleaned_coach, source='manual')
        elif cleaned_coach is not None:
            existing = next((team for team in workspace.list_teams(include_archived=True)
                             if team['id'] == key), None)
            if existing:
                workspace.upsert_team(key, name=existing['name'], coach=cleaned_coach, source='manual')
    return body


def merge_team(db_path, source, target, *, sync_workspace=True):
    """把 source 并进 target：覆盖层跟随，工作区同步归档并改挂选手。"""
    if not source or not target or source == target:
        raise ValueError('合并来源和目标不能相同')
    body = save_override(db_path, source, {'mergedInto': target})
    if sync_workspace:
        from workspace_store import Workspace
        Workspace(db_path).ensure_schema().merge_teams(source, target)
    return body


def rename_many(db_path, items, *, actor=None) -> dict:
    """批量命名：一个事务内写工作区主数据和覆盖层。"""
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError('请选择 1–200 支战队')
    cleaned = []
    seen_ids, seen_names = set(), set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f'第 {index} 项格式无效')
        key = str(item.get('id') or '').strip()
        name = clean_name(item.get('name'))
        coach = clean_name(item.get('coach')) if item.get('coach') is not None else None
        if not key:
            raise ValueError(f'第 {index} 项缺少战队 id')
        if not name:
            raise ValueError(f'第 {index} 项缺少队名')
        if len(name) > 40:
            raise ValueError(f'第 {index} 项队名过长')
        if key in seen_ids:
            raise ValueError(f'第 {index} 项重复出现同一支战队')
        if name in seen_names:
            raise ValueError(f'第 {index} 项队名重复：{name}')
        seen_ids.add(key)
        seen_names.add(name)
        cleaned.append({'id': key, 'name': name, 'coach': coach})

    from workspace_store import Workspace
    workspace = Workspace(db_path).ensure_schema()
    connection = workspace.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        for item in cleaned:
            conflict = connection.execute(
                "SELECT id FROM teams WHERE name=? AND id<>? AND status='active'",
                (item['name'], item['id'])).fetchone()
            if conflict is not None:
                raise ValueError(f'队名已存在：{item["name"]}')
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS {TABLE} (key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
        for item in cleaned:
            row = connection.execute('SELECT name, coach FROM teams WHERE id=?',
                                     (item['id'],)).fetchone()
            if row is None:
                connection.execute('INSERT INTO teams(id, name, coach) VALUES(?,?,?)',
                                   (item['id'], item['name'], item['coach']))
                workspace._log(connection, 'team', item['id'], 'created', None, item['name'],
                               'rename-batch', actor)
            else:
                if row['name'] != item['name']:
                    workspace._log(connection, 'team', item['id'], 'name', row['name'],
                                   item['name'], 'rename-batch', actor)
                if item['coach'] is not None and (row['coach'] or '') != item['coach']:
                    workspace._log(connection, 'team', item['id'], 'coach', row['coach'],
                                   item['coach'], 'rename-batch', actor)
                connection.execute(
                    'UPDATE teams SET name=?, coach=COALESCE(?, coach), revision=revision+1 '
                    'WHERE id=?', (item['name'], item['coach'], item['id']))
            override_row = connection.execute(f'SELECT body FROM {TABLE} WHERE key=?',
                                              (item['id'],)).fetchone()
            try:
                body = json.loads(override_row['body']) if override_row else {}
            except (TypeError, ValueError):
                body = {}
            body['name'] = item['name']
            if item['coach'] is not None:
                body['coach'] = item['coach']
            connection.execute(
                f'INSERT INTO {TABLE}(key, body, updated_at) VALUES(?,?,strftime(\'%s\',\'now\')) '
                'ON CONFLICT(key) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at',
                (item['id'], json.dumps(body, ensure_ascii=False)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {'ok': True, 'updated': len(cleaned), 'items': cleaned}


def reconcile_workspace(db_path, *, dry_run=False) -> dict:
    """把历史覆盖层与工作区主数据对账，兼容旧数据。

    - 覆盖层有真实队名、工作区缺失或仍是占位名 → 写入工作区。
    - 工作区有真实队名、覆盖层缺失或不同 → 回写覆盖层。
    只补名/教练，不动合并关系，也不覆盖工作区已有的真实名字。
    """
    workspace = load_workspace_teams(db_path)
    overrides = load_overrides(db_path)
    changes = []
    for key, override in overrides.items():
        real_name = clean_name(override.get('name'))
        if not real_name:
            continue
        current = workspace.get(key)
        if not current or is_placeholder(current.get('name')):
            changes.append({'key': key, 'action': 'workspace_name',
                            'old': current.get('name') if current else None,
                            'new': real_name})
            if not dry_run:
                from workspace_store import Workspace
                Workspace(db_path).ensure_schema().upsert_team(
                    key, name=real_name, coach=clean_name(override.get('coach')) or None,
                    source='reconcile')
    for key, team in workspace.items():
        real_name = clean_name(team.get('name'))
        if not real_name or is_placeholder(real_name):
            continue
        override = overrides.get(key, {})
        if clean_name(override.get('name')) != real_name or \
                clean_name(override.get('coach')) != clean_name(team.get('coach')):
            changes.append({'key': key, 'action': 'override',
                            'old': clean_name(override.get('name')) or None, 'new': real_name})
            if not dry_run:
                save_override(db_path, key, {'name': real_name,
                                             'coach': clean_name(team.get('coach')) or None})
    return {'ok': True, 'dryRun': dry_run, 'changes': changes, 'count': len(changes)}


# ---------------------------------------------------------------- 对外组装
def list_teams(camp_dir, db_path, own_name='') -> dict:
    panels = load_panels(camp_dir)
    built = build(panels)
    overrides = load_overrides(db_path)
    workspace_index = load_workspace_teams(db_path)
    # 合并：被并走的 cluster 不再单独出现，局数并入目标
    clusters = {item['id']: dict(item) for item in built['clusters']}
    for key, override in overrides.items():
        target = override.get('mergedInto')
        if target and target in clusters and key in clusters and target != key:
            host = clusters[target]
            guest = clusters[key]
            host['matches'] += guest['matches']
            host['wins'] += guest['wins']
            host['losses'] += guest['losses']
            host['seqs'] = host['seqs'] + guest['seqs']
            host['games'] = host['games'] + guest['games']
            host['firstSeen'] = min(filter(None, [host['firstSeen'], guest['firstSeen']]), default=None)
            host['lastSeen'] = max(filter(None, [host['lastSeen'], guest['lastSeen']]), default=None)
            for hero, count in guest['heroes'].items():
                host['heroes'][hero] = host['heroes'].get(hero, 0) + count
            host['players'].update({k: v for k, v in guest['players'].items() if k not in host['players']})
            for key, value in guest['totals'].items():
                host['totals'][key] = host['totals'].get(key, 0) + value
            guest['merged'] = True
    live = [item for item in clusters.values() if not item.get('merged')]
    live.sort(key=lambda item: (item['firstSeen'] or '9999', item['id']))

    teams = []
    pending = 0
    for index, item in enumerate(live, start=1):
        override = overrides.get(item['id'], {})
        workspace_team = workspace_index.get(item['id'], {})
        workspace_name = clean_name(workspace_team.get('name'))
        override_name = clean_name(override.get('name'))
        name = workspace_name if workspace_name and not is_placeholder(workspace_name) else override_name
        coach = clean_name(workspace_team.get('coach')) or clean_name(override.get('coach'))
        display = name or f'待命名对手 #{index}'
        if not name:
            pending += 1
        decided = item['wins'] + item['losses']
        teams.append({
            'id': item['id'],
            'name': name,
            'coach': coach,
            'displayName': display,
            'named': bool(name),
            'number': index,
            'matches': item['matches'],
            'wins': item['wins'],
            'losses': item['losses'],
            'winRate': round(item['wins'] / decided * 100, 1) if decided else None,
            'firstSeen': item['firstSeen'],
            'lastSeen': item['lastSeen'],
            'players': sorted(item['players'].values(), key=lambda p: (-p['games'], p['name'] or '')),
            'heroes': [{'hero': hero, 'games': games}
                       for hero, games in sorted(item['heroes'].items(), key=lambda kv: -kv[1])[:8]],
            'games': sorted(item['games'], key=lambda game: game['start'], reverse=True),
            'seqs': item['seqs'],
        })

    suggestions = []
    numbers = {item['id']: item['number'] for item in teams}
    for suggestion in built['suggestions']:
        source = clusters.get(suggestion['from'], {})
        target = clusters.get(suggestion['into'], {})
        if source.get('merged') or target.get('merged'):
            continue
        suggestions.append({
            'from': suggestion['from'], 'into': suggestion['into'], 'overlap': suggestion['overlap'],
            'fromNumber': numbers.get(suggestion['from']),
            'intoNumber': numbers.get(suggestion['into']),
            'fromName': overrides.get(suggestion['from'], {}).get('name') or '',
            'intoName': overrides.get(suggestion['into'], {}).get('name') or '',
        })

    games = sum(item['matches'] for item in teams)
    wins = sum(item['wins'] for item in teams)
    losses = sum(item['losses'] for item in teams)

    # ---- 可对比指标：每支队用同一套口径算，再转成分位 ----
    totals_by_id = {item['id']: item.get('totals') or {} for item in live}
    metrics = {item['id']: _team_metrics(item, totals_by_id.get(item['id'], {})) for item in teams}
    own_metrics = _team_metrics(None, _own_totals(panels))
    for item in teams:
        item['metrics'] = metrics[item['id']]
    pool = [value for value in metrics.values() if value]
    for item in teams:
        item['percentiles'] = _percentiles(item['metrics'], pool)
    own = {'name': clean_name(own_name), 'matches': len(panels), 'wins': wins, 'losses': losses,
           'winRate': round(wins / (wins + losses) * 100, 1) if wins + losses else None,
           'metrics': own_metrics, 'percentiles': _percentiles(own_metrics, pool)}
    return {
        'own': own,
        'teams': teams,
        'suggestions': suggestions,
        'summary': {'teams': len(teams), 'named': len(teams) - pending, 'pending': pending,
                    'games': games, 'unclustered': len(panels) - games},
        'warnings': [] if panels else ['没有读到营地十人面板，无法聚类对手。'],
    }


def _own_totals(panels) -> dict:
    totals = _new_record({})
    for panel in panels:
        minutes = (panel['duration'] or 0) / 60
        totals['games'] += 1
        totals['seconds'] += minutes * 60
        for player in panel['own_roster']:
            for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'heroDamage', 'taken', 'control', 'heal', 'towers'):
                totals[key] += player.get(key) or 0
        if panel['win'] is True:
            totals['wins'] += 1
            totals['decided'] += 1
        elif panel['win'] is False:
            totals['decided'] += 1
    return totals


def _team_metrics(item, totals) -> dict:
    if not totals or not totals.get('games'):
        return {}
    minutes = totals['seconds'] / 60
    games = totals['games']
    deaths = totals['deaths']
    decided = totals['decided'] if item is None else (item['wins'] + item['losses'])
    wins = totals['wins'] if item is None else item['wins']
    return {
        'winRate': round(wins / decided * 100, 1) if decided else None,
        'gpm': round(totals['gold'] / minutes) if minutes else None,
        'dpm': round(totals['heroDamage'] / minutes) if minutes else None,
        'dtpm': round(totals['taken'] / minutes) if minutes else None,
        'kda': round((totals['kills'] + totals['assists']) / deaths, 2) if deaths else None,
        'towerPerGame': round(totals['towers'] / games, 2),
    }


def _percentiles(metrics, pool) -> dict:
    """分位：在该指标上超过多少比例的对手战队。样本缺失返回 None，不按 0 参与。"""
    if not metrics:
        return {}
    out = {}
    for key, value in metrics.items():
        values = [item[key] for item in pool if item.get(key) is not None]
        if value is None or not values:
            out[key] = None
            continue
        out[key] = round(sum(1 for other in values if other <= value) / len(values) * 100)
    return out


# ---------------------------------------------------------------- 逐人 / 逐英雄
_ACC = ('games', 'seconds', 'kills', 'deaths', 'assists', 'gold', 'damage', 'heroDamage', 'taken',
        'control', 'heal', 'towers', 'participation', 'wins', 'decided')


def _new_record(base: dict) -> dict:
    record = {key: 0 for key in _ACC}
    record.update(base)
    return record


def _add(record, player, minutes, win):
    record['games'] += 1
    record['seconds'] += minutes * 60
    for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'heroDamage', 'taken', 'control', 'heal', 'towers'):
        value = player.get(key)
        if value is not None:
            record[key] += value
    if player.get('participation') is not None:
        record['participation'] += player['participation']
    if win is True:
        record['wins'] += 1
        record['decided'] += 1
    elif win is False:
        record['decided'] += 1


def _finish(record):
    games = record['games'] or 1
    minutes = record['seconds'] / 60
    deaths = record['deaths']
    out = dict(record)
    out.update({
        'kills': round(record['kills'] / games, 1),
        'deaths': round(deaths / games, 1),
        'assists': round(record['assists'] / games, 1),
        'kda': round((record['kills'] + record['assists']) / deaths, 2) if deaths else None,
        'gpm': round(record['gold'] / minutes, 0) if minutes else None,
        'dpm': round(record['heroDamage'] / minutes, 0) if minutes else None,
        # 总伤害口径（含兵线野怪）：与本站既有「分均输出」定义一致，跨来源对比时用它
        'dpmTotal': round(record['damage'] / minutes, 0) if minutes else None,
        'dtpm': round(record['taken'] / minutes, 0) if minutes else None,
        'controlPerMin': round(record['control'] / minutes, 1) if minutes else None,
        'healPerMin': round(record['heal'] / minutes, 0) if minutes else None,
        'participation': round(record['participation'] / games * 100, 1),
        'winRate': round(record['wins'] / record['decided'] * 100, 1) if record['decided'] else None,
    })
    return out


def compare(camp_dir, team_id=None, min_games=3) -> dict:
    """逐人 / 逐英雄统计：我方与对手用同一套口径，按分路可对齐。

    只使用营地十人面板里真实存在的战斗字段；字段缺失记 0，不补猜。
    """
    panels = load_panels(camp_dir)
    if team_id:
        panels = [panel for panel in panels if signature(panel) == team_id]

    players = {'own': {}, 'enemy': {}}
    heroes = {'own': {}, 'enemy': {}}
    lanes: dict[str, dict] = {}

    for panel in panels:
        minutes = (panel['duration'] or 0) / 60
        for side, roster in (('own', panel['own_roster']), ('enemy', panel['enemy_roster'])):
            for player in roster:
                if not player.get('id'):
                    continue
                record = players[side].setdefault(
                    player['id'], _new_record({'id': player['id'], 'name': player['name'],
                                               'lane': player['lane'], 'teamId': signature(panel)}))
                if not record['name'] and player['name']:
                    record['name'] = player['name']
                if not record.get('lane') and player['lane']:
                    record['lane'] = player['lane']
                _add(record, player, minutes, panel['win'])

                if player.get('hero'):
                    hero = heroes[side].setdefault(
                        player['hero'], _new_record({'hero': player['hero'], 'lane': player['lane']}))
                    _add(hero, player, minutes, panel['win'])

                if player.get('lane'):
                    lane = lanes.setdefault(player['lane'], {'own': {}, 'enemy': {}})
                    lane_record = lane[side].setdefault(player['id'], _new_record(
                        {'id': player['id'], 'name': player['name'], 'lane': player['lane']}))
                    _add(lane_record, player, minutes, panel['win'])

    def board(rows, key):
        out = [_finish(record) for record in rows.values()]
        out.sort(key=lambda item: (-item['games'], item.get(key) or ''))
        return out

    lane_rows = []
    for lane, sides in lanes.items():
        own = max(sides['own'].values(), key=lambda item: item['games'], default=None)
        enemy = max(sides['enemy'].values(), key=lambda item: item['games'], default=None)
        lane_rows.append({
            'lane': lane,
            'own': _finish(own) if own else None,
            'enemy': _finish(enemy) if enemy else None,
        })
    order = {name: index for index, name in enumerate(LANES.values())}
    lane_rows.sort(key=lambda item: order.get(item['lane'], 99))

    return {
        'teamId': team_id,
        'games': len(panels),
        'players': {'own': board(players['own'], 'name'), 'enemy': board(players['enemy'], 'name')},
        'heroes': {'own': board(heroes['own'], 'hero'), 'enemy': board(heroes['enemy'], 'hero')},
        'lanes': lane_rows,
        'combos': _combos_from(panels, min_games=min_games, limit=12),
        # 三人组门槛更高：5 局以下基本是噪声
        'combos3': _combos_from(panels, min_games=max(5, min_games), limit=12, size=3),
        'pool': _depth_from(panels),
        'warnings': [] if panels else ['当前范围没有可读的营地面板。'],
    }


# ---------------------------------------------------------------- 阵容组合
def _combos_from(panels, min_games=2, limit=30, size=2) -> dict:
    """同队同局的英雄组合，用「协同加成」区分真化学反应与强英雄堆叠。

    size=2 为双人组、size=3 为三人组。
    协同 = 组合胜率 − 各英雄单独胜率均值。
    正值说明这组搭配本身有价值；负值说明只是把各自都强的英雄放在一起。
    出场不足 min_games 的组合不参与排序，只在计数里体现。
    """
    from itertools import combinations

    def collect(side):
        hero = {}
        combo = {}
        for panel in panels:
            roster = panel['enemy_roster'] if side == 'enemy' else panel['own_roster']
            picked = sorted({item['hero'] for item in roster if item['hero']})
            win = panel['win']
            for name in picked:
                record = hero.setdefault(name, {'games': 0, 'decided': 0, 'wins': 0})
                record['games'] += 1
                if win is not None:
                    record['decided'] += 1
                    record['wins'] += 1 if win else 0
            for group in combinations(picked, size):
                record = combo.setdefault(group, {'games': 0, 'decided': 0, 'wins': 0})
                record['games'] += 1
                if win is not None:
                    record['decided'] += 1
                    record['wins'] += 1 if win else 0
        rates = {name: (item['wins'] / item['decided'] * 100 if item['decided'] else None)
                 for name, item in hero.items()}
        rows = []
        for group, item in combo.items():
            if item['decided'] == 0:
                continue
            win_rate = item['wins'] / item['decided'] * 100
            parts = [rate for rate in (rates.get(name) for name in group) if rate is not None]
            expected = sum(parts) / len(parts) if parts else None
            rows.append({
                'heroes': list(group),
                'games': item['games'],
                'decided': item['decided'],
                'wins': item['wins'],
                'winRate': round(win_rate, 1),
                'expected': round(expected, 1) if expected is not None else None,
                'synergy': round(win_rate - expected, 1) if expected is not None else None,
                'small': item['games'] < min_games,
            })
        # 先按「样本是否达标」分档，再按协同排序：避免 1 局 100% 的组合霸榜
        rows.sort(key=lambda row: (row['small'], -(row['synergy'] if row['synergy'] is not None else -999),
                                    -row['games']))
        return rows if limit is None else rows[:limit], len(combo)

    own_rows, own_total = collect('own')
    enemy_rows, enemy_total = collect('enemy')
    return {
        'games': len(panels),
        'minGames': min_games,
        'size': size,
        'own': {'combos': own_rows, 'pairs': own_total},
        'enemy': {'combos': enemy_rows, 'pairs': enemy_total},
    }


def combos(camp_dir, team_id=None, min_games=2, limit=30) -> dict:
    panels = load_panels(camp_dir)
    if team_id:
        panels = [panel for panel in panels if signature(panel) == team_id]
    result = _combos_from(panels, min_games=min_games, limit=limit)
    return {'teamId': team_id, **result,
            'warnings': [] if panels else ['当前范围没有可读的营地面板。']}


def _depth_from(panels) -> dict:
    """英雄池深度：有效英雄数 = 1 / HHI。

    比"用过 N 个英雄"抗噪：只玩 2 个英雄轮换的 20 个英雄池，HHI 很高、有效数很低。
    """
    def depth(side):
        counts = {}
        for panel in panels:
            roster = panel['enemy_roster'] if side == 'enemy' else panel['own_roster']
            for item in roster:
                if item['hero']:
                    counts[item['hero']] = counts.get(item['hero'], 0) + 1
        total = sum(counts.values())
        if not total:
            return {'heroes': 0, 'picks': 0, 'hhi': None, 'effective': None}
        hhi = sum((value / total) ** 2 for value in counts.values())
        return {'heroes': len(counts), 'picks': total, 'hhi': round(hhi, 4),
                'effective': round(1 / hhi, 1)}

    return {'own': depth('own'), 'enemy': depth('enemy'), 'games': len(panels)}


def hero_pool_depth(camp_dir, team_id=None) -> dict:
    panels = load_panels(camp_dir)
    if team_id:
        panels = [panel for panel in panels if signature(panel) == team_id]
    result = _depth_from(panels)
    return {**result, 'teamId': team_id,
            'warnings': [] if panels else ['当前范围没有可读的营地面板。']}


def partners(camp_dir, hero, side='own', min_games=3, limit=8) -> dict:
    """某个英雄的搭档协同：只保留包含它的双人组合。

    和 combos() 同一套算法，区别是这里按「指定英雄」过滤并只返回搭档，
    方便在英雄详情页直接回答"这个英雄配谁"。
    """
    panels = load_panels(camp_dir)
    result = _combos_from(panels, min_games=min_games, limit=None)
    rows = [row for row in result[side]['combos'] if hero in row['heroes']]
    rows.sort(key=lambda row: (row['small'],
                               -(row['synergy'] if row['synergy'] is not None else -999),
                               -row['games']))
    for row in rows:
        row['partner'] = row['heroes'][1] if row['heroes'][0] == hero else row['heroes'][0]
    return {
        'hero': hero, 'side': side, 'games': len(panels), 'minGames': min_games,
        'partners': rows[:limit],
        'pairs': len(rows),
        'warnings': [] if panels else ['当前范围没有可读的营地面板。'],
    }


def combo_sets(camp_dir, min_games=3) -> dict:
    """一次给出双人 / 三人两套组合，给 BP 页这类需要同时展示的场景用。"""
    panels = load_panels(camp_dir)
    return {
        'games': len(panels),
        'pairs': _combos_from(panels, min_games=min_games, limit=None, size=2),
        'trios': _combos_from(panels, min_games=max(5, min_games), limit=None, size=3),
        'warnings': [] if panels else ['当前范围没有可读的营地面板。'],
    }


# ---------------------------------------------------------------- 对手选手归属
def player_key(player_id):
    return f'player:{player_id}'


def assign_player(db_path, player_id, team_id):
    """把某名对手选手归到指定战队（覆盖层，不改原始面板）。team_id 为空表示恢复默认。"""
    if not player_id:
        raise ValueError('缺少选手 id')
    return save_override(db_path, player_key(player_id), {'teamId': team_id or None})


def opponent_players(camp_dir, db_path):
    """列出所有对手选手及其当前归属。

    默认归属来自阵营签名聚类；教练手动指派过则以覆盖层为准。
    返回 {teams:[{id,displayName,players:[...]}], unassigned:[...], players:[...]}
    """
    panels = load_panels(camp_dir)
    overrides = load_overrides(db_path)
    teams = list_teams(camp_dir, db_path)

    seen = {}
    for panel in panels:
        for player in panel['enemy_roster']:
            if not player['id']:
                continue
            record = seen.setdefault(player['id'], {
                'id': player['id'], 'name': player['name'], 'games': 0,
                'defaultTeam': signature(panel), 'lanes': set(),
            })
            record['games'] += 1
            if not record['name'] and player['name']:
                record['name'] = player['name']
            if player.get('lane'):
                record['lanes'].add(player['lane'])

    by_id = {team['id']: team for team in teams['teams']}
    buckets = {team['id']: [] for team in teams['teams']}
    unassigned = []

    for player_id, record in seen.items():
        override = overrides.get(player_key(player_id), {})
        team_id = override.get('teamId') or record['defaultTeam']
        # 战队被合并走时，跟随到目标战队
        if team_id not in by_id:
            merged = overrides.get(team_id, {}).get('mergedInto')
            team_id = merged if merged in by_id else None
        item = {
            'id': player_id, 'name': record['name'] or player_id,
            'games': record['games'], 'lanes': sorted(record['lanes']),
            'defaultTeam': record['defaultTeam'], 'teamId': team_id,
            'manual': bool(override.get('teamId')),
        }
        if team_id and team_id in buckets:
            buckets[team_id].append(item)
        else:
            unassigned.append(item)

    for group in buckets.values():
        group.sort(key=lambda row: (-row['games'], row['name']))

    return {
        'teams': [{'id': team['id'], 'displayName': team['displayName'],
                   'named': team['named'], 'players': buckets[team['id']]}
                  for team in teams['teams']],
        'unassigned': unassigned,
        'total': len(seen),
        'warnings': teams.get('warnings') or [],
    }
