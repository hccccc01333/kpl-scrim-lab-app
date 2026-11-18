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
3. **兜底显示名**：「待命名战队 #N」，N 按首次出现时间排序，只用于显示，不落库。
   选手占位名是「待命名选手 #N」，两者前缀不同，避免混用。
   教练改完名立刻全量生效，历史对局不用批量改。
4. **合并分两级**：5 人完全相同 → 自动同一 cluster；3–4 人重合 → 只给"建议合并"，
   必须人工确认，避免把轮换阵容误判成同一支队。前后两段时间不重叠、只剩
   2 个老队员，也算「阵容更替」候选，同样只提示不自动合并。
5. **并队只并战队，不并名单**：被并进来的 cluster 的所有历史选手都保留，
   但「当前阵容」只按最近 ROSTER_WINDOW 局逐位置选出场最多的人（最多 5 人），
   更早出场的记成「曾效力」。对方转会 / 离队导致同期阵容不同，不会把
   7–8 个人塞进一套阵容里。

对外只暴露 list_teams / rename_team / merge_team 三个入口。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
import unicodedata
from pathlib import Path

import team_style

# 重合几个人才提示"可能是同一支队"（整队 5 人，3 人以上才给建议）
SUGGEST_OVERLAP = 3
# 但如果是「前后两段时间不重叠、只留了 2 个老队员」，多半是同一支战队换人
# （转会 / 离队 / 大轮换），也该给人工确认的机会。
SUGGEST_ROSTER_MIN = 2
SUGGEST_MAX = 24
# 「当前阵容」取最近几局按位置出场最多的人；更早的选手进「曾效力」。
ROSTER_WINDOW = 5

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
    """「待命名战队 #N」是显示兜底，不是主数据里的真实队名。"""
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
    """逐局读出「我方 / 对面」两侧阵容。读不出的局跳过，不猜测。

    104 个面板约 0.35 秒（每个文件都要 json 解析），而战队列表、BP 汇总、
    选手看板、训练台账都要这份结果；按目录指纹缓存 2 秒，目录里新增/改动
    一局就自动重读。返回列表的浅拷贝，调用方可以安心 replace / append。
    """
    camp_dir = Path(camp_dir)
    stamp = _camp_dir_fingerprint(camp_dir)
    cached = _PANELS_CACHE
    if stamp is not None and cached['stamp'] == stamp and cached['dir'] == str(camp_dir):
        return list(cached['panels'])
    panels = _load_panels_uncached(camp_dir)
    if stamp is not None:
        cached.update(stamp=stamp, dir=str(camp_dir), panels=panels)
    return list(panels)


# 面板目录指纹缓存：一次 (数量, 最新 mtime) 扫描约 9ms，比重新解析 104 个
# 面板便宜一个数量级；指纹每次都重扫，所以新增/改动一局立刻可见。
_PANELS_CACHE = {'dir': None, 'stamp': None, 'panels': []}


def _camp_dir_fingerprint(camp_dir) -> tuple | None:
    try:
        count, latest = 0, 0
        with os.scandir(camp_dir) as entries:
            for entry in entries:
                if not entry.name.endswith('.json'):
                    continue
                try:
                    latest = max(latest, entry.stat().st_mtime_ns)
                except OSError:
                    continue
                count += 1
        return (count, latest)
    except OSError:
        return None


def clear_panels_cache() -> None:
    """写入口（新增/改营地面板）后主动丢弃缓存，下一次读必定重解析。"""
    _PANELS_CACHE.update(stamp=None, panels=[])


def _load_panels_uncached(camp_dir) -> list[dict]:
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
        enemy_win = (not win) if isinstance(win, bool) else None
        own_roster = _roster(own_roles)
        enemy_roster = _roster(enemy_roles)
        # 队伍口径的终局合计（击杀/经济/推塔/控龙/胜负）在 blueTeam / redTeam 里；
        # 缺这段时退回十人面板求和，控龙没有来源就留 None，不拿 0 冒充。
        own_stats = _camp_team_stats(data.get(f'{own}Team')) or _roster_stats(own_roster, win)
        enemy_stats = _camp_team_stats(data.get(f'{enemy}Team')) or _roster_stats(enemy_roster, enemy_win)
        panels.append({
            'seq': path.stem,
            'own': own,
            'enemy': enemy,
            'start': clean_name(battle.get('startTime')),
            'duration': battle.get('usedTime') or head.get('durationSec'),
            'map': clean_name(battle.get('mapName')),
            'win': win,
            'own_roster': own_roster,
            'enemy_roster': enemy_roster,
            'own_stats': own_stats,
            'enemy_stats': enemy_stats,
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


# 营地 blueTeam / redTeam 的五个龙字段；口径见 team_style：控龙 = 五项之和
DRAGON_KEYS = ('ldragon1', 'ldragon2', 'bdragon1', 'bdragon2', 'bdragon3')


def _camp_team_stats(team) -> dict | None:
    """blueTeam / redTeam → 队伍终局合计；字段缺失返回 None（不是 0）。"""
    if not isinstance(team, dict) or not team:
        return None
    kills = _int(team.get('killCnt'))
    deaths = _int(team.get('deadCnt'))
    assists = _int(team.get('assistCnt'))
    gold = _int(team.get('money'))
    towers = _int(team.get('towerCnt'))
    # 控龙必须 5 个字段齐全才相加：少一个就宁可空着，不让分母少一条龙。
    dragons = None
    if all(key in team and team.get(key) is not None for key in DRAGON_KEYS):
        dragons = sum(_int(team.get(key)) or 0 for key in DRAGON_KEYS)
    win = team.get('gameResult')
    return {
        'kills': kills, 'deaths': deaths, 'assists': assists, 'gold': gold,
        'towers': towers, 'dragons': dragons,
        'win': win if isinstance(win, bool) else None,
    }


def _roster_stats(roster, win) -> dict | None:
    """没有 blueTeam / redTeam 时的兜底：用十人面板求和，控龙留 None。"""
    if not roster:
        return None

    def total(key):
        values = [player.get(key) for player in roster if player.get(key) is not None]
        return sum(values) if values else None

    return {
        'kills': total('kills'), 'deaths': total('deaths'), 'assists': total('assists'),
        'gold': total('gold'), 'towers': total('towers'), 'dragons': None,
        'win': win if isinstance(win, bool) else None,
    }


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
        _accumulate(totals, panel['enemy_roster'])
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
            right_ids = set(right['players'])
            shared = left_ids & right_ids
            if not shared or len(shared) >= 5:
                continue
            # 两段交手时间不重叠 = 更像是同一支队前后换人，而不是同时轮换。
            sequential = bool(
                (left['lastSeen'] and right['firstSeen'] and left['lastSeen'] <= right['firstSeen'])
                or (right['lastSeen'] and left['firstSeen'] and right['lastSeen'] <= left['firstSeen']))
            if len(shared) < SUGGEST_OVERLAP and not (sequential and len(shared) >= SUGGEST_ROSTER_MIN):
                continue
            suggestions.append({
                'from': left['id'], 'into': right['id'], 'overlap': len(shared),
                'players': sorted(shared),
                'kind': 'roster-change' if sequential else 'overlap',
                'changedFrom': len(left_ids - right_ids),
                'changedInto': len(right_ids - left_ids),
            })
    suggestions.sort(key=lambda item: (-item['overlap'], item['kind'] != 'roster-change', item['from']))
    return {'clusters': clusters, 'suggestions': suggestions[:SUGGEST_MAX]}


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


def record_alias(db_path, key, old_name, current_name=''):
    """改名/合并后把旧队名登记为别名，历史自由文本由解析层折成当前队名。

    只在 team_clusters 覆盖层里存一份，不复制队名、不改历史对局。
    """
    import opponent_identity
    key = str(key or '')
    if not key:
        return
    overrides = load_overrides(db_path)
    body = overrides.get(key) or {}
    aliases = opponent_identity.merge_alias(body.get('aliases'), old_name,
                                            current_name or body.get('name'))
    if aliases and aliases != opponent_identity._alias_list(body.get('aliases')):
        save_override(db_path, key, {'aliases': aliases})
        opponent_identity.clear_cache()
    # 工作区主数据也留一份：战队分析表单里的 aliases 与覆盖层不脱节。
    try:
        connection = sqlite3.connect(str(db_path))
        try:
            row = connection.execute('SELECT aliases FROM teams WHERE id=?', (key,)).fetchone()
            if row is not None:
                try:
                    existing = json.loads(row[0] or '[]')
                except (TypeError, ValueError):
                    existing = []
                merged = opponent_identity.merge_alias(
                    list(existing) + list(aliases), old_name,
                    current_name or body.get('name'))
                if merged != opponent_identity._alias_list(existing):
                    connection.execute(
                        'UPDATE teams SET aliases=?, revision=revision+1 WHERE id=?',
                        (json.dumps(merged, ensure_ascii=False), key))
                    connection.commit()
        finally:
            connection.close()
    except sqlite3.Error:
        pass


def _previous_name(db_path, key):
    """重命名前的真实队名：工作区优先，覆盖层兜底。"""
    workspace_name = clean_name((load_workspace_teams(db_path).get(key) or {}).get('name'))
    if workspace_name and not is_placeholder(workspace_name):
        return workspace_name
    override_name = clean_name((load_overrides(db_path).get(key) or {}).get('name'))
    return override_name if override_name and not is_placeholder(override_name) else ''


def rename_team(db_path, key, name=None, coach=None, *, sync_workspace=True):
    """命名同时写工作区主数据与兼容覆盖层。

    工作区 `teams` 是权威来源；覆盖层保留给旧版本和未迁移数据，读取时只作兜底。
    旧队名登记为别名：全站逐局视图读解析层，改名自然同步，不用批量改历史对局。
    """
    cleaned_name = clean_name(name) if name is not None else None
    cleaned_coach = clean_name(coach) if coach is not None else None
    previous = _previous_name(db_path, str(key)) if cleaned_name else ''
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
    if previous and previous != cleaned_name:
        record_alias(db_path, key, previous, cleaned_name)
    return body


def merge_team(db_path, source, target, *, sync_workspace=True):
    """把 source 并进 target：覆盖层跟随，工作区同步归档并改挂选手。"""
    if not source or not target or source == target:
        raise ValueError('合并来源和目标不能相同')
    source_name = _previous_name(db_path, str(source))
    target_name = _previous_name(db_path, str(target))
    body = save_override(db_path, source, {'mergedInto': target})
    if sync_workspace:
        from workspace_store import Workspace
        Workspace(db_path).ensure_schema().merge_teams(source, target)
    if source_name and source_name != target_name:
        record_alias(db_path, target, source_name, target_name)
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
            # 批量改名同样把旧队名留成别名，历史文本自动归一到新队名。
            import opponent_identity
            old_name = clean_name((row['name'] if row else '') or body.get('name'))
            body['aliases'] = opponent_identity.merge_alias(
                body.get('aliases'), old_name, item['name'])
            body['name'] = item['name']
            if item['coach'] is not None:
                body['coach'] = item['coach']
            connection.execute(
                f'INSERT INTO {TABLE}(key, body, updated_at) VALUES(?,?,strftime(\'%s\',\'now\')) '
                'ON CONFLICT(key) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at',
                (item['id'], json.dumps(body, ensure_ascii=False)))
            workspace_row = connection.execute('SELECT aliases FROM teams WHERE id=?',
                                               (item['id'],)).fetchone()
            if workspace_row is not None:
                try:
                    existing = json.loads(workspace_row['aliases'] or '[]')
                except (TypeError, ValueError):
                    existing = []
                merged = opponent_identity.merge_alias(
                    list(existing) + list(body['aliases']), old_name, item['name'])
                connection.execute('UPDATE teams SET aliases=? WHERE id=?',
                                   (json.dumps(merged, ensure_ascii=False), item['id']))
        connection.commit()
        opponent_identity.clear_cache()
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
    """对手战队列表：既有字段保持不变，额外挂 `style`（§2.1）。"""
    return _list_teams(load_panels(camp_dir), db_path, own_name)


def _ordered_games(item, *, reverse=False):
    return sorted(item.get('games') or [],
                  key=lambda game: (str(game.get('start') or ''), str(game.get('seq') or '')),
                  reverse=reverse)


def _players_from_games(item, panel_index):
    """一支战队（含被并进来的 cluster）全部历史出场选手，按逐局面板重算。

    不复用 build() 里按 cluster 聚合的 players：并队后那些字典直接合并会把
    不同时期的人混在一起，也拿不到合并后的首末出场时间。
    """
    out = {}
    for game in _ordered_games(item):
        panel = panel_index.get(str(game.get('seq')))
        if not panel:
            continue
        start = str(game.get('start') or '')
        for player in panel.get('enemy_roster') or []:
            pid = str(player.get('id') or '')
            if not pid:
                continue
            record = out.get(pid)
            if record is None:
                record = out[pid] = {
                    'id': pid, 'name': clean_name(player.get('name')),
                    'lane': player.get('lane') or '', 'games': 0,
                    'firstSeen': start, 'lastSeen': start,
                    'recentGames': 0, 'active': False, 'current': False,
                    'status': 'former',
                }
            record['games'] += 1
            if not record['name'] and player.get('name'):
                record['name'] = clean_name(player['name'])
            if not record['lane'] and player.get('lane'):
                record['lane'] = player['lane']
            if start:
                if not record['firstSeen'] or start < record['firstSeen']:
                    record['firstSeen'] = start
                if start > record['lastSeen']:
                    record['lastSeen'] = start
    return out


def _current_roster(item, panel_index, players):
    """当前五人 = 最近 ROSTER_WINDOW 局里每个位置出场最多的人。

    同局出场数打平时以「更靠后的一局」为准：战队换人之后，新阵容不会被
    老队员按名字排序挤掉。缺位置就少一个，不拿别的位置补数。
    """
    recent = _ordered_games(item, reverse=True)[:ROSTER_WINDOW]
    recent_panels = [panel_index[str(game.get('seq'))] for game in recent
                     if str(game.get('seq')) in panel_index]
    recent_counter = {}
    lane_pool = {}
    for order, panel in enumerate(recent_panels):
        for player in panel.get('enemy_roster') or []:
            pid = str(player.get('id') or '')
            if not pid:
                continue
            recent_counter[pid] = recent_counter.get(pid, 0) + 1
            lane = player.get('lane') or ''
            record = lane_pool.get((lane, pid))
            if record is None:
                record = lane_pool[(lane, pid)] = {
                    'id': pid, 'name': clean_name(player.get('name')),
                    'lane': lane, 'games': 0, 'newest': order}
            record['games'] += 1
            record['newest'] = min(record['newest'], order)
            if not record['name'] and player.get('name'):
                record['name'] = clean_name(player['name'])
    for pid, count in recent_counter.items():
        record = players.get(pid)
        if record is not None:
            record['active'] = True
            record['recentGames'] = count
    current = []
    for lane in LANES.values():
        candidates = [record for (candidate_lane, _), record in lane_pool.items()
                      if candidate_lane == lane]
        if not candidates:
            continue
        candidates.sort(key=lambda record: (-record['games'], record['newest'],
                                            record['name'] or ''))
        row = candidates[0]
        pid = row['id']
        entry = dict(players.get(pid) or {})
        entry.update({'id': pid, 'name': row['name'] or entry.get('name') or '',
                      'lane': lane, 'active': True, 'current': True,
                      'status': 'current', 'recentGames': row['games']})
        current.append(entry)
        if pid in players:
            players[pid]['current'] = True
    return current, set(recent_counter)


def _apply_roster_status(item, panel_index):
    """给战队挂上当前阵容 / 轮换 / 曾效力三档，并标出阵容是否更替过。"""
    players = _players_from_games(item, panel_index)
    current, recent_ids = _current_roster(item, panel_index, players)
    current_ids = {str(player.get('id')) for player in current}
    for pid, record in players.items():
        if pid in current_ids:
            record['status'] = 'current'
        elif pid in recent_ids:
            record['status'] = 'rotation'
        else:
            record['status'] = 'former'
    rank = {'current': 0, 'rotation': 1, 'former': 2}
    ordered = sorted(players.values(),
                     key=lambda p: (rank[p['status']], -(p.get('games') or 0), p.get('name') or ''))
    item['players'] = ordered                       # 全量历史名单，当前五人排最前
    item['currentPlayers'] = current                # 页面上显示的当前五人
    item['rotationPlayers'] = [p for p in ordered if p['status'] == 'rotation']
    item['formerPlayers'] = [p for p in ordered if p['status'] == 'former']
    item['rosterWindow'] = min(ROSTER_WINDOW, len(item.get('games') or []))
    item['rosterChanged'] = bool(item['formerPlayers'])


def _list_teams(panels, db_path, own_name='') -> dict:
    built = build(panels)
    overrides = load_overrides(db_path)
    workspace_index = load_workspace_teams(db_path)
    # 合并：被并走的 cluster 不再单独出现，局数并入目标
    clusters = {item['id']: dict(item) for item in built['clusters']}
    # 多次合并（A→B→C）时直接并到最终目标，避免按覆盖层写入顺序把 A 的局
    # 并进一个已经归档的 B 而丢掉；与 opponent_identity 的解析链同一口径。
    try:
        import opponent_identity
        canonical = opponent_identity.resolve_names(db_path)['canonical']
    except Exception:  # noqa: BLE001 - 解析不可用时退回单层合并
        canonical = {}
    for key, override in overrides.items():
        target = str(override.get('mergedInto') or '')
        if target:
            target = canonical.get(target, target)
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
            # 选手名单不在这里合并：并队后按「合并后的全部对局」重算，
            # 当前五人只看最近几局，早期的人进「曾效力」。见 _apply_roster_status。
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
        display = name or f'待命名战队 #{index}'
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
    names = {item['id']: item['displayName'] for item in teams}
    for suggestion in built['suggestions']:
        source = clusters.get(suggestion['from'], {})
        target = clusters.get(suggestion['into'], {})
        if source.get('merged') or target.get('merged'):
            continue
        suggestions.append({
            'from': suggestion['from'], 'into': suggestion['into'], 'overlap': suggestion['overlap'],
            'fromNumber': numbers.get(suggestion['from']),
            'intoNumber': numbers.get(suggestion['into']),
            # 未命名的聚类以前显示成空的「→」，教练不知道要合并哪两支。
            'fromName': names.get(suggestion['from']) or '',
            'intoName': names.get(suggestion['into']) or '',
            'kind': suggestion.get('kind') or 'overlap',
            'changedFrom': suggestion.get('changedFrom') or 0,
            'changedInto': suggestion.get('changedInto') or 0,
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
    # 阵容：按面板逐局重算，合并多套阵容后才看得出轮换。
    panel_index = {str(panel['seq']): panel for panel in panels}
    for item in teams:
        picked = [panel_index[str(seq)] for seq in item.get('seqs') or []
                  if str(seq) in panel_index]
        item['roster'] = _team_roster(picked, 'enemy')
        _apply_roster_status(item, panel_index)
    # 风格：与 team_deep 共用 team_style 的同一套算法（含同池 33/66 分位），
    # 逐局双向进池，所以列表页与详情页的点位不会互相打架。
    style_index = team_style.build_index(panels)
    for item in teams:
        records = [style_index['enemy'][seq] for seq in item.get('seqs') or []
                   if seq in style_index['enemy']]
        item['style'] = team_style.style(records, style_index)
    own = {'name': clean_name(own_name), 'matches': len(panels), 'wins': wins, 'losses': losses,
           'winRate': round(wins / (wins + losses) * 100, 1) if wins + losses else None,
           'metrics': own_metrics, 'percentiles': _percentiles(own_metrics, pool),
           'roster': _team_roster(panels, 'own'),
           'style': team_style.style(style_index['own'], style_index)}
    return {
        'own': own,
        'teams': teams,
        'suggestions': suggestions,
        'summary': {'teams': len(teams), 'named': len(teams) - pending, 'pending': pending,
                    'games': games, 'unclustered': len(panels) - games},
        'warnings': [] if panels else ['没有读到营地十人面板，无法聚类对手。'],
    }


def team_brief(camp_dir, db_path, team_id='', name='', limit=3) -> dict | None:
    """训练课用的对手简报：最近交手、常用英雄、禁用习惯、关键选手。"""
    data = list_teams(camp_dir, db_path)
    team = next((item for item in data.get('teams', []) if item['id'] == team_id), None)
    if team is None and name:
        team = next((item for item in data.get('teams', [])
                     if item.get('displayName') == name or item.get('name') == name), None)
    if team is None:
        return None
    panels = {panel['seq']: panel for panel in load_panels(camp_dir)}
    bans = Counter()
    try:
        from bp_camp import parse_camp_bp
        for seq in team.get('seqs') or []:
            panel = panels.get(seq)
            path = Path(camp_dir) / f'{seq}.json'
            if panel is None or not path.is_file():
                continue
            try:
                detail = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            bp = parse_camp_bp(detail, seq)
            if not bp:
                continue
            own_side = bp.get('ownSide')
            if own_side not in ('left', 'right'):
                own_side = 'left' if panel.get('own') == 'blue' else 'right'
            enemy_side = 'right' if own_side == 'left' else 'left'
            for entry in (bp.get('bans') or {}).get(enemy_side, []):
                hero = clean_name(entry.get('name'))
                if hero:
                    bans[hero] += 1
    except (ImportError, OSError, ValueError):
        pass
    lane_order = {lane: index for index, lane in enumerate(('对抗路', '打野', '中路', '发育路', '游走'))}
    # 关键选手只给当前五人：历史出场过的人不该挤进训练课的对手简报。
    players = sorted(team.get('currentPlayers') or team.get('players') or [],
                     key=lambda player: (lane_order.get(player.get('lane'), 99),
                                         -(player.get('games') or 0), player.get('name') or ''))
    recent = sorted(team.get('games') or [],
                    key=lambda game: str(game.get('start') or ''), reverse=True)[:max(1, min(5, limit))]
    return {
        'id': team['id'],
        'name': team.get('displayName') or team.get('name') or '未命名对手',
        'named': bool(team.get('named')),
        'matches': team.get('matches') or 0,
        'wins': team.get('wins') or 0,
        'losses': team.get('losses') or 0,
        'winRate': team.get('winRate'),
        'lastSeen': team.get('lastSeen') or '',
        'recent': recent,
        'players': players,
        'formerCount': len(team.get('formerPlayers') or []),
        'rosterWindow': team.get('rosterWindow') or 0,
        'heroes': (team.get('heroes') or [])[:5],
        'bans': [{'hero': hero, 'games': count} for hero, count in bans.most_common(5)],
    }


def _accumulate(totals, roster) -> None:
    """把一侧五人面板累加进队伍合计。

    参团率是逐人百分比，先累加有值的样本再取平均；缺失不按 0 参与，
    避免一个人没记录就把全队参团率拉低。
    """
    for player in roster or []:
        for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'heroDamage', 'taken',
                    'control', 'heal', 'towers'):
            totals[key] += player.get(key) or 0
        if player.get('participation') is not None:
            totals['participation'] += player['participation']
            totals['participationN'] += 1


def _own_totals(panels) -> dict:
    totals = _new_record({})
    for panel in panels:
        minutes = (panel['duration'] or 0) / 60
        totals['games'] += 1
        totals['seconds'] += minutes * 60
        _accumulate(totals, panel['own_roster'])
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
    participation_n = totals.get('participationN') or 0
    return {
        'winRate': round(wins / decided * 100, 1) if decided else None,
        'gpm': round(totals['gold'] / minutes) if minutes else None,
        'dpm': round(totals['heroDamage'] / minutes) if minutes else None,
        'dtpm': round(totals['taken'] / minutes) if minutes else None,
        'kda': round((totals['kills'] + totals['assists']) / deaths, 2) if deaths else None,
        'towerPerGame': round(totals['towers'] / games, 2),
        # 风格页要用的原始量：全部来自同一份营地合计，不引入新来源、不补猜。
        'duration': round(totals['seconds'] / games) if games else None,
        'killsPerGame': round(totals['kills'] / games, 1) if games else None,
        'deathsPerGame': round(totals['deaths'] / games, 1) if games else None,
        'assistsPerGame': round(totals['assists'] / games, 1) if games else None,
        'killsPerMin': round(totals['kills'] / minutes, 3) if minutes else None,
        'assistsPerMin': round(totals['assists'] / minutes, 3) if minutes else None,
        'controlPerMin': round(totals['control'] / minutes, 1) if minutes else None,
        'participation': round(totals['participation'] / participation_n * 100, 1) if participation_n else None,
        'conversion': round(totals['heroDamage'] / totals['gold'] * 100, 1) if totals['gold'] else None,
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
        'control', 'heal', 'towers', 'participation', 'participationN', 'wins', 'decided')


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


# ---------------------------------------------------------------- 阵容
def _team_roster(panels, side='enemy') -> dict:
    """一套阵容的读法：位置池、五人组变体与稳定度。

    同一 cluster 的五人组按定义固定；只有把多套阵容合并成一支队之后才会出现轮换，
    所以这里按面板逐局重算，而不是复用聚合计数。字段缺失记 0，不补猜。
    """
    roster_key = f'{side}_roster'
    lane_players: dict[tuple, dict] = {}
    heroes: dict[tuple, Counter] = {}
    lineups: dict[str, dict] = {}
    lane_counts: dict[str, list] = {}
    for panel in panels:
        minutes = (panel['duration'] or 0) / 60
        roster = panel.get(roster_key) or []
        per_game = Counter(item.get('lane') or '' for item in roster)
        for lane in LANES.values():
            lane_counts.setdefault(lane, []).append(per_game.get(lane, 0))
        ids = sorted(str(item['id']) for item in roster if item.get('id'))
        lineup_key = '|'.join(ids) or panel['seq']
        lineup = lineups.setdefault(lineup_key, {
            'ids': ids, 'names': [], 'games': 0, 'wins': 0, 'losses': 0,
            'firstSeen': None, 'lastSeen': None})
        lineup['games'] += 1
        if panel['win'] is True:
            lineup['wins'] += 1
        elif panel['win'] is False:
            lineup['losses'] += 1
        start = panel.get('start') or ''
        if start:
            if lineup['firstSeen'] is None or start < lineup['firstSeen']:
                lineup['firstSeen'] = start
            if lineup['lastSeen'] is None or start > lineup['lastSeen']:
                lineup['lastSeen'] = start
        if not lineup['names']:
            lineup['names'] = [clean_name(item.get('name')) for item in roster]
        for player in roster:
            pid = str(player.get('id') or '')
            if not pid:
                continue
            lane = player.get('lane') or ''
            record = lane_players.get((pid, lane))
            if record is None:
                record = lane_players[(pid, lane)] = _new_record({
                    'id': pid, 'name': clean_name(player.get('name')), 'lane': lane})
                heroes[(pid, lane)] = Counter()
            if not record['name'] and player.get('name'):
                record['name'] = clean_name(player.get('name'))
            _add(record, player, minutes, panel['win'])
            if player.get('hero'):
                heroes[(pid, lane)][clean_name(player['hero'])] += 1

    lane_rows = []
    for lane in LANES.values():
        rows = []
        for (pid, player_lane), record in lane_players.items():
            if player_lane != lane:
                continue
            item = _finish(record)
            rows.append({
                'id': item['id'], 'name': item['name'], 'lane': lane,
                'games': item['games'], 'wins': item['wins'], 'decided': item['decided'],
                'winRate': item['winRate'], 'kills': item['kills'], 'deaths': item['deaths'],
                'assists': item['assists'], 'kda': item['kda'], 'gpm': item['gpm'],
                'dpm': item['dpm'], 'dtpm': item['dtpm'], 'participation': item['participation'],
                'heroes': [{'hero': hero, 'games': count}
                           for hero, count in heroes[(pid, lane)].most_common(4)],
            })
        rows.sort(key=lambda item: (-item['games'], item['name'] or ''))
        lane_rows.append({'lane': lane, 'players': rows})

    total = sum(item['games'] for item in lineups.values())
    top = max((item['games'] for item in lineups.values()), default=0)
    # 同一局同一个位置出现两人是营地位置字段的重复，不是轮换；单独标出来，不混进轮换数。
    anomalies = [lane for lane, counts in lane_counts.items() if max(counts, default=0) > 1]
    rotation = 0
    for lane in LANES.values():
        players = {pid for (pid, player_lane) in lane_players if player_lane == lane}
        if len(players) > 1 and lane not in anomalies:
            rotation += 1
    return {
        'games': len(panels),
        'lanes': lane_rows,
        'lineups': sorted(lineups.values(), key=lambda item: (-item['games'], item['firstSeen'] or '')),
        'stability': round(top / total * 100) if total else None,
        'rotation': rotation,
        'anomalies': anomalies,
        'players': len({pid for pid, _ in lane_players}),
    }


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


def account_team_index(camp_dir, db_path) -> dict:
    """敌方账号 → 聚类战队 id（含合并）。

    身份对照页用它在命名前显示「这个号当时属于哪支队」，只读、不比战绩，
    所以不走 list_teams 那套完整指标计算。
    """
    overrides = load_overrides(db_path)
    index = {}
    for panel in load_panels(camp_dir):
        team_id = signature(panel)
        merged = overrides.get(team_id, {}).get('mergedInto')
        if merged:
            team_id = merged
        for player in panel['enemy_roster']:
            if player['id']:
                index.setdefault(player['id'], team_id)
    for key, body in overrides.items():
        if key.startswith('player:'):
            team_id = body.get('teamId')
            if team_id:
                index[key.split(':', 1)[1]] = team_id
    return index


def _mapped_accounts(db_path) -> dict:
    """账号 → 选手/战队的已命名映射；读不到就按未命名处理。"""
    try:
        from workspace_store import Workspace
        return Workspace(db_path).account_index()
    except Exception:
        return {}


def opponent_players(camp_dir, db_path):
    """列出所有对手选手及其当前归属。

    命名过的账号显示真实选手名与战队（`player_accounts` 是唯一口径），
    未命名的仍按阵营签名聚类归组，名字就用营地昵称。
    返回 {teams:[{id,displayName,players:[...]}], unassigned:[...], players:[...]}
    """
    panels = load_panels(camp_dir)
    overrides = load_overrides(db_path)
    accounts = _mapped_accounts(db_path)
    teams = list_teams(camp_dir, db_path)

    seen = {}
    for panel in panels:
        team_id = signature(panel)
        for player in panel['enemy_roster']:
            if not player['id']:
                continue
            record = seen.setdefault(player['id'], {
                'id': player['id'], 'name': player['name'], 'games': 0,
                'defaultTeam': team_id, 'teams': [], 'lanes': set(),
            })
            record['games'] += 1
            # 选手转会 / 离队后会在别的战队出现：默认归属跟最近一次出场走，
            # 早先待过的队记进 formerTeams，历史不清空。
            if not record['teams'] or record['teams'][-1] != team_id:
                record['teams'].append(team_id)
            record['defaultTeam'] = team_id
            if not record['name'] and player['name']:
                record['name'] = player['name']
            if player.get('lane'):
                record['lanes'].add(player['lane'])

    by_id = {team['id']: team for team in teams['teams']}
    buckets = {team['id']: [] for team in teams['teams']}
    unassigned = []

    # 命名过的选手可能已经挂在工作区新建的战队上：这些队不在聚类结果里，补进来。
    extras = {}
    for mapped in accounts.values():
        team_id = mapped.get('teamId')
        if team_id and team_id not in by_id:
            extras[team_id] = {'id': team_id,
                               'displayName': mapped.get('teamName') or '未命名战队',
                               'named': bool(mapped.get('teamName'))}
            buckets.setdefault(team_id, [])

    for player_id, record in seen.items():
        mapped = accounts.get(player_id) or {}
        override = overrides.get(player_key(player_id), {})
        team_id = mapped.get('teamId') or override.get('teamId') or record['defaultTeam']
        # 战队被合并走时，跟随合并链到最终目标战队（可能有多次合并）。
        if team_id not in by_id and team_id not in extras:
            try:
                import opponent_identity
                canonical = opponent_identity.resolve_names(db_path)['canonical']
                team_id = canonical.get(team_id, team_id)
            except Exception:  # noqa: BLE001 - 解析失败退回单层兜底
                merged = overrides.get(team_id, {}).get('mergedInto')
                team_id = merged if merged in by_id else None
            if team_id not in by_id and team_id not in extras:
                team_id = None
        item = {
            'id': player_id,
            'name': mapped.get('name') or record['name'] or player_id,
            'nickname': record['name'],
            'mapped': bool(mapped),
            'playerId': mapped.get('playerId') or '',
            'position': mapped.get('position') or '',
            'games': record['games'], 'lanes': sorted(record['lanes']),
            'defaultTeam': record['defaultTeam'], 'teamId': team_id,
            'formerTeams': [t for t in record['teams'][:-1] if t != team_id],
            'transferred': len({t for t in record['teams']}) > 1,
            'manual': bool(mapped or override.get('teamId')),
        }
        if team_id and team_id in buckets:
            buckets[team_id].append(item)
        else:
            unassigned.append(item)

    for group in buckets.values():
        group.sort(key=lambda row: (-row['games'], row['name']))

    order = [{'id': team['id'], 'displayName': team['displayName'],
              'named': team['named'], 'players': buckets[team['id']]} for team in teams['teams']]
    order += [{'id': item['id'], 'displayName': item['displayName'], 'named': item['named'],
               'players': buckets[item['id']]}
              for item in extras.values() if buckets.get(item['id'])]
    order.sort(key=lambda group: (not group['named'], group['displayName']))
    return {
        'teams': order,
        'unassigned': unassigned,
        'total': len(seen),
        'named': sum(1 for mapped in accounts.values() if mapped.get('teamId')),
        'warnings': teams.get('warnings') or [],
    }


# ---------------------------------------------------------------- 按对手的训练台账
def _match_index(matches_dir) -> dict:
    """营地面板 seq → 对局档案里的完整日期。

    营地详情只有「MM-DD HH:MM」，没有年份；对局档案里带完整日期。
    能对上就用完整日期，对不上就退回营地日期，不猜年份。
    """
    index = {}
    if not matches_dir:
        return index
    root = Path(matches_dir)
    if not root.is_dir():
        return index
    for path in root.glob('*.json'):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        match = body.get('match') if isinstance(body, dict) else None
        if not isinstance(match, dict):
            continue
        seq = str((match.get('campBp') or {}).get('gameSeq') or '')
        if not seq:
            continue
        date = match.get('date') or {}
        text = date.get('text') if isinstance(date, dict) else ''
        index[seq] = {'date': str(text or ''), 'title': clean_name(match.get('title')),
                      'session': clean_name(match.get('session')),
                      'key': str(match.get('key') or path.stem)}
    return index


def _parse_goals(raw) -> list[dict]:
    """训练目标在库里是 JSON 字符串：兼容纯字符串与 {label,target,status} 两种写法。"""
    if isinstance(raw, list):
        value = raw
    else:
        try:
            value = json.loads(raw or '[]')
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    goals = []
    for item in value:
        if isinstance(item, dict) and clean_name(item.get('label')):
            goals.append({'label': clean_name(item.get('label')),
                          'target': clean_name(item.get('target')),
                          'status': str(item.get('status') or 'pending')})
        elif isinstance(item, str) and item.strip():
            goals.append({'label': clean_name(item), 'target': '', 'status': 'pending'})
    return goals


def team_training(camp_dir, db_path, schedules=None, matches_dir=None) -> dict:
    """按对手汇总训练台账。

    - 「训练课」来自工作区 schedules：只有填了 opponent_team_id 才挂到对手，
      带训练目标、复盘状态和赛制；
    - 没有登记计划的交手日按「交手日」归集，只写日期、局数、胜负、时长，
      不伪造训练目标，也不把交手日说成训练课。
    """
    data = list_teams(camp_dir, db_path)
    teams = data.get('teams') or []
    match_index = _match_index(matches_dir)

    rows = [dict(item) for item in (schedules or []) if isinstance(item, dict)]
    by_team: dict[str, list] = {}
    unassigned = []
    for row in rows:
        team_id = str(row.get('opponent_team_id') or '').strip()
        if team_id:
            by_team.setdefault(team_id, []).append(row)
        else:
            unassigned.append({
                'id': row.get('id') or '', 'date': str(row.get('date') or ''),
                'startTime': row.get('start_time') or '', 'session': row.get('session') or '',
                'format': row.get('format') or '', 'status': row.get('status') or 'planned',
                'goals': _parse_goals(row.get('goals')),
            })

    def same_day(day, date) -> bool:
        if not day or not date:
            return False
        if len(day) == 10 and len(date) == 10:
            return day == date
        return day[-5:] == date[-5:]

    def summarize(games) -> dict:
        wins = sum(1 for game in games if game['win'] is True)
        losses = sum(1 for game in games if game['win'] is False)
        durations = [game['duration'] for game in games
                     if isinstance(game['duration'], (int, float)) and game['duration'] > 0]
        return {'matches': len(games), 'wins': wins, 'losses': losses,
                'duration': round(sum(durations) / len(durations)) if durations else None}

    out_teams = []
    for team in teams:
        games = []
        for game in team.get('games') or []:
            seq = str(game.get('seq') or '')
            info = match_index.get(seq) or {}
            day = info.get('date') or str(game.get('start') or '')[:5]
            games.append({'seq': seq, 'start': str(game.get('start') or ''), 'day': day,
                          'win': game.get('win'), 'duration': game.get('duration'),
                          'map': game.get('map') or '',
                          'session': info.get('session') or '', 'matchKey': info.get('key') or ''})

        sessions = []
        used = set()
        for plan in by_team.get(team['id'], []):
            date = str(plan.get('date') or '')
            picked = [game for game in games if same_day(game['day'], date)]
            used.update(game['seq'] for game in picked)
            sessions.append({
                'id': str(plan.get('id') or ''), 'source': 'plan', 'date': date,
                'time': plan.get('start_time') or '', 'session': plan.get('session') or '',
                'format': plan.get('format') or '', 'rules': plan.get('rules') or '',
                'version': plan.get('version') or '', 'status': plan.get('status') or 'planned',
                'notes': plan.get('notes') or '', 'goals': _parse_goals(plan.get('goals')),
                'reviewStatus': plan.get('review_status') or '',
                'review': plan.get('review') or '',
                'games': picked, **summarize(picked),
            })

        buckets: dict[str, list] = {}
        for game in games:
            if game['seq'] in used:
                continue
            buckets.setdefault(game['day'], []).append(game)
        for day, group in buckets.items():
            group.sort(key=lambda game: game['start'])
            sessions.append({
                'id': '', 'source': 'camp', 'date': day,
                'time': group[0]['start'][6:] if group and len(group[0]['start']) > 6 else '',
                'session': group[0].get('session') or '', 'format': '', 'rules': '', 'version': '',
                'status': '', 'notes': '', 'goals': [], 'reviewStatus': '', 'review': '',
                'games': group, **summarize(group),
            })

        sessions.sort(key=lambda item: (item['date'] if len(item['date']) == 10 else '0000-' + item['date'],
                                        item['time'] or ''), reverse=True)
        plans = [item for item in sessions if item['source'] == 'plan']
        goals = [goal for item in plans for goal in item['goals']]
        out_teams.append({
            'id': team['id'], 'name': team.get('name') or '', 'displayName': team.get('displayName'),
            'named': bool(team.get('named')), 'coach': team.get('coach') or '',
            'matches': team.get('matches') or 0, 'wins': team.get('wins') or 0,
            'losses': team.get('losses') or 0, 'winRate': team.get('winRate'),
            'lastSeen': team.get('lastSeen') or '',
            'sessions': sessions, 'sessionCount': len(sessions),
            'planCount': len(plans), 'goalCount': len(goals),
            'goalsDone': sum(1 for goal in goals if goal['status'] == 'achieved'),
            'reviewed': sum(1 for item in plans if item['reviewStatus'] == 'done'),
            'lastSession': sessions[0]['date'] if sessions else '',
        })

    # 有训练课的排前，其次按最近一次训练 / 交手日期；同一天的按队名稳定排序。
    out_teams.sort(key=lambda item: (item['planCount'] > 0,
                                     item['lastSession'] or item['lastSeen'] or '',
                                     item['displayName'] or ''), reverse=True)
    summary = {
        'teams': len(out_teams),
        'withPlans': sum(1 for item in out_teams if item['planCount']),
        'plans': sum(item['planCount'] for item in out_teams),
        'goals': sum(item['goalCount'] for item in out_teams),
        'goalsDone': sum(item['goalsDone'] for item in out_teams),
        'reviewed': sum(item['reviewed'] for item in out_teams),
        'sessions': sum(item['sessionCount'] for item in out_teams),
        'unassigned': len(unassigned),
    }
    return {'teams': out_teams, 'unassigned': unassigned, 'summary': summary,
            'warnings': data.get('warnings') or []}


# ---------------------------------------------------------------- 战队详情（逐局）
# 契约见 docs/team_page_v2.md §2.2：一屏给前端六段分析要的全部原料。
# 只读营地面板 + 已有的 BP 解析，不补猜禁选顺序，也不给逐局加时间轴。
def _hero_label(hero, lane) -> dict:
    """英雄 + 实际分路 → 打法类型；表的语义见 hero_archetypes。"""
    import hero_archetypes
    return hero_archetypes.describe(hero, lane)


def _deep_players(roster, minutes) -> list:
    """十人面板 → 前端逐人卡；经济占比按「已记录的队友经济合计」算，缺谁不补 0。"""
    known = [player for player in roster or [] if player.get('gold') is not None]
    gold_total = sum(player['gold'] for player in known)
    rows = []
    for player in roster or []:
        label = _hero_label(player.get('hero'), player.get('lane'))
        gold = player.get('gold')
        rows.append({
            'id': player.get('id') or '',
            'name': player.get('name') or '',
            'lane': player.get('lane') or label.get('lane') or '',
            'hero': player.get('hero') or '',
            'archetype': label.get('archetype'),
            'kills': player.get('kills'),
            'deaths': player.get('deaths'),
            'assists': player.get('assists'),
            'gold': gold,
            'heroDamage': player.get('heroDamage'),
            'taken': player.get('taken'),
            'control': player.get('control'),
            'heal': player.get('heal'),
            'participation': player.get('participation'),
            'towers': player.get('towers'),
            'goldShare': (round(gold / gold_total * 100, 1)
                          if gold is not None and gold_total else None),
            'minutes': minutes,
        })
    return rows


def _deep_picks(roster, hero_meta) -> list:
    """出场阵容：英雄 + 十人面板里的真实分路（不是营地 ban/pick 名单里的默认分路）。"""
    rows, seen = [], set()
    for player in roster or []:
        hero = player.get('hero')
        if not hero or hero in seen:
            continue
        seen.add(hero)
        label = _hero_label(hero, player.get('lane'))
        rows.append({
            'name': hero,
            'lane': label.get('lane') or player.get('lane') or '',
            'archetype': label.get('archetype'),
            'icon': (hero_meta.get(hero) or {}).get('icon'),
        })
    return rows


def _deep_bans(entries) -> list:
    rows, seen = [], set()
    for entry in entries or []:
        entry = entry or {}
        name = entry.get('name')
        if not name or name in seen:
            continue
        seen.add(name)
        label = _hero_label(name, entry.get('lane'))
        rows.append({'name': name, 'lane': label.get('lane') or '',
                     'archetype': label.get('archetype'), 'icon': entry.get('icon')})
    return rows


def _deep_stats(stats) -> dict:
    stats = stats or {}
    return {key: stats.get(key) for key in
            ('kills', 'deaths', 'assists', 'gold', 'towers', 'dragons', 'win')}


def _deep_game(camp_dir, panel, style_index) -> dict:
    seq = str(panel.get('seq') or '')
    try:
        detail = json.loads((Path(camp_dir) / f'{seq}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        detail = {}
    try:
        from bp_camp import parse_camp_bp
        bp = parse_camp_bp(detail, seq) or {}
    except (ImportError, ValueError):
        bp = {}
    own_side = bp.get('ownSide')
    if own_side not in ('left', 'right'):
        own_side = 'left' if panel.get('own') == 'blue' else 'right'
    enemy_side = 'right' if own_side == 'left' else 'left'
    hero_meta = bp.get('heroMeta') or {}
    duration = panel.get('duration')
    minutes = round(duration / 60, 1) if isinstance(duration, (int, float)) and duration else None
    own_stats, enemy_stats = panel.get('own_stats'), panel.get('enemy_stats')
    win = panel.get('win')
    opponent_win = (enemy_stats or {}).get('win')
    if opponent_win is None and isinstance(win, bool):
        opponent_win = not win
    start = panel.get('start') or ''
    sides = {
        'own': {'players': _deep_players(panel.get('own_roster'), minutes),
                'picks': _deep_picks(panel.get('own_roster'), hero_meta),
                'bans': _deep_bans((bp.get('bans') or {}).get(own_side)),
                'stats': _deep_stats(own_stats)},
        'enemy': {'players': _deep_players(panel.get('enemy_roster'), minutes),
                  'picks': _deep_picks(panel.get('enemy_roster'), hero_meta),
                  'bans': _deep_bans((bp.get('bans') or {}).get(enemy_side)),
                  'stats': _deep_stats(enemy_stats)},
    }
    hero_info = {}
    for side in ('own', 'enemy'):
        # ban 名单里的英雄常常只在这一局出现，先用 ban 行的分路兜底，
        # 再用出场行覆盖——逐手矩阵需要的分路/类型尽量不留空。
        for entry in sides[side]['bans']:
            hero_info.setdefault(entry['name'], {'lane': entry.get('lane') or '',
                                                 'archetype': entry.get('archetype') or ''})
    for entry in sides['own']['picks'] + sides['enemy']['picks']:
        hero_info[entry['name']] = {'lane': entry.get('lane') or '',
                                    'archetype': entry.get('archetype') or ''}
    for side in ('own', 'enemy'):
        sides[side]['lineup'] = lineup_structure(sides[side]['picks'])
    return {
        'seq': seq, 'start': start, 'day': team_style.day_label(start),
        'duration': duration, 'map': panel.get('map') or '',
        'win': win, 'opponentWin': opponent_win, 'ownSide': panel.get('own'),
        'sides': sides,
        'style': team_style.game_style(style_index['enemy'].get(seq),
                                       style_index['thresholds']),
        'draft': _draft_block(bp, own_side, hero_info),
    }


def _draft_block(bp, own_side, hero_info=None) -> dict:
    """逐手事件标准化为 own / enemy 视角；没有顺序时 events 为空。

    额外给出每侧按手序排好的 ban / pick 列表（带分路与打法类型），
    前端才能做「第 1-5 手 ban / pick」的分布分析；顺序来源不透明确时
    由 orderAssumed 标注，展示层需照抄这个前提，不把它当逐手核验。
    """
    info = hero_info or {}

    def label(hero):
        row = info.get(hero) or {}
        return {'lane': row.get('lane') or '', 'archetype': row.get('archetype') or ''}

    events = []
    for event in (bp.get('draftEvents') or []):
        camp = str(event.get('camp') or '')
        if camp not in ('1', '2'):
            continue
        # 营地 camp：1=left，2=right；ownSide 决定 own/enemy。
        known_own = (camp == '1' and own_side == 'left') or (camp == '2' and own_side == 'right')
        hero = event.get('hero')
        row = label(hero)
        events.append({
            'order': event.get('order'),
            'action': event.get('action'),
            'side': 'own' if known_own else 'enemy',
            'hero': hero,
            'lane': row['lane'],
            'archetype': row['archetype'],
        })
    ordered = {'own': {'ban': [], 'pick': []}, 'enemy': {'ban': [], 'pick': []}}
    for event in sorted(events, key=lambda item: item.get('order') or 0):
        action = event.get('action')
        side = event.get('side')
        if action in ('ban', 'pick') and side in ordered:
            ordered[side][action].append({key: event[key] for key in ('hero', 'lane', 'archetype')})
    return {
        'known': bool(bp.get('pickOrderKnown') and events),
        'events': events,
        'ordered': ordered,
        'orderSource': bp.get('orderSource') or '',
        'orderAssumed': bool(bp.get('orderAssumed')),
        'banCount': bp.get('banCount') or {},
    }


# 核 / 前排 / 控制的结构口径（赛训组 2026-11 复盘会）：
#   核 = 战边 / 刺野 / 战野 / 法核 / 游射 / 呆射；坦边、坦野、工具人、辅助不分核。
#   控 = 英雄能力表「控制」维度计数；只统计已收录英雄，未收录英雄单列不猜。
CORE_ARCHETYPES = ('战边', '刺野', '战野', '法核', '游射', '呆射')


def lineup_structure(picks) -> dict:
    """五路阵容结构：核数 / 控数 / 前排 / 功能标签；缺表的英雄单独计数。

    只做结构描述，不评价强弱；未收录能力的英雄会让控数偏低，
    因此同时给出 known 与 total，展示层必须把覆盖率一起写出来。
    """
    import hero_capabilities
    rows = [pick for pick in picks or [] if pick.get('name')]
    cores = []
    for pick in rows:
        archetype = pick.get('archetype') or ''
        if archetype in CORE_ARCHETYPES:
            cores.append({'hero': pick.get('name'), 'lane': pick.get('lane') or '', 'type': archetype})
    heroes = [pick.get('name') for pick in rows]
    caps = hero_capabilities.lineup_capabilities(heroes)
    known = sum(1 for hero in heroes if hero in hero_capabilities.HERO_CAPABILITIES)
    return {
        'cores': len(cores),
        'coreList': cores,
        'controls': caps['控制'],
        'front': caps['前排'],
        'engage': caps['开团'],
        'peel': caps['保护'] + caps['反开'],
        'damage': caps['爆发'] + caps['持续输出'],
        'known': known,
        'total': len(rows),
        'tags': hero_capabilities.functional_tags(heroes),
    }


def _count_rows(counter, total, limit=6) -> list:
    return [{'key': key, 'games': games,
             'share': round(games / total * 100, 1) if total else None}
            for key, games in counter.most_common(limit)]


def _bp_lane_rows(counter, total, limit=5) -> list:
    """分路分布；未标注单列，避免把未知分路并进其他分路。"""
    rows = [{'key': key, 'games': n,
             'share': round(n / total * 100, 1) if total else None}
            for key, n in counter.most_common() if key][:limit]
    labeled = sum(row['games'] for row in rows)
    if total and labeled < total:
        rows.append({'key': '未标注', 'games': total - labeled,
                     'share': round((total - labeled) / total * 100, 1)})
    return rows


def _bp_order_block(games) -> dict:
    """BP 顺序分析：首抢、首 ban、ban→首抢响应、ban 与胜负的条件关联。

    只统计 pickOrderKnown 的局；不做因果推断，结果表是条件关联。
    """
    import lineup_stats
    known = [g for g in games if (g.get('draft') or {}).get('known')
             and (g.get('draft') or {}).get('events')]
    total = len(known)
    verified = sum(1 for g in known if not (g.get('draft') or {}).get('orderAssumed'))
    assumed = total - verified
    if not total:
        return {'knownGames': 0, 'totalGames': len(games), 'eventsKnown': False,
                'verifiedGames': 0, 'assumedGames': 0}
    first_lanes, first_heroes = Counter(), Counter()
    own_first_ban, enemy_first_ban = Counter(), Counter()
    own_ban_slots = [Counter() for _ in range(5)]
    enemy_ban_slots = [Counter() for _ in range(5)]
    own_slot_games = [0] * 5
    enemy_slot_games = [0] * 5
    responses = defaultdict(lambda: {'games': 0, 'lanes': Counter(), 'heroes': Counter()})
    outcomes = defaultdict(lambda: {'games': 0, 'oppWins': 0})
    outcome_games = [g for g in games
                     if any((ban or {}).get('name') for ban in ((g.get('sides') or {}).get('own') or {}).get('bans') or [])]
    for game in outcome_games:
        for ban in ((game.get('sides') or {}).get('own') or {}).get('bans') or []:
            hero = (ban or {}).get('name')
            if not hero:
                continue
            outcome = outcomes[hero]
            outcome['games'] += 1
            if game.get('opponentWin') is True:
                outcome['oppWins'] += 1
    for game in known:
        events = sorted(game['draft']['events'], key=lambda e: e.get('order') or 0)
        enemy_picks = [e for e in events if e.get('action') == 'pick' and e.get('side') == 'enemy']
        first_enemy_hero, first_enemy_lane = '', ''
        if enemy_picks:
            first_enemy_hero = enemy_picks[0].get('hero') or ''
            first_enemy_lane = next((p.get('lane') for p in (game.get('sides', {}).get('enemy', {}).get('picks') or [])
                                     if p.get('name') == first_enemy_hero), '') or ''
            if first_enemy_hero:
                first_heroes[first_enemy_hero] += 1
                first_lanes[first_enemy_lane] += 1
        own_bans = [e.get('hero') for e in events if e.get('action') == 'ban' and e.get('side') == 'own']
        enemy_bans = [e.get('hero') for e in events if e.get('action') == 'ban' and e.get('side') == 'enemy']
        if own_bans and own_bans[0]:
            own_first_ban[own_bans[0]] += 1
        if enemy_bans and enemy_bans[0]:
            enemy_first_ban[enemy_bans[0]] += 1
        for slot, hero in enumerate(own_bans[:5]):
            own_slot_games[slot] += 1
            if hero:
                own_ban_slots[slot][hero] += 1
        for slot, hero in enumerate(enemy_bans[:5]):
            enemy_slot_games[slot] += 1
            if hero:
                enemy_ban_slots[slot][hero] += 1
        for hero in own_bans:
            if not hero:
                continue
            response = responses[hero]
            response['games'] += 1
            if first_enemy_hero:
                response['heroes'][first_enemy_hero] += 1
                response['lanes'][first_enemy_lane] += 1
    base_wins = sum(1 for g in known if g.get('opponentWin') is True)
    base_rate = base_wins / total * 100 if total else None
    outcome_base_wins = sum(1 for g in outcome_games if g.get('opponentWin') is True)
    outcome_base_rate = outcome_base_wins / len(outcome_games) * 100 if outcome_games else None
    response_rows = []
    for hero, row in sorted(responses.items(), key=lambda kv: -kv[1]['games'])[:6]:
        if row['games'] < 3:
            continue
        response_rows.append({
            'hero': hero, 'games': row['games'],
            'lanes': _bp_lane_rows(row['lanes'], row['games']),
            'heroes': _count_rows(row['heroes'], row['games'], 3),
        })
    outcome_rows = []
    for hero, row in sorted(outcomes.items(), key=lambda kv: -kv[1]['games']):
        if row['games'] < 4:
            continue
        rate = row['oppWins'] / row['games'] * 100
        outcome_rows.append({
            'hero': hero, 'games': row['games'], 'oppWins': row['oppWins'],
            'rate': round(rate, 1), 'delta': round(rate - outcome_base_rate, 1) if outcome_base_rate is not None else None,
            'wilson': [round(x, 1) for x in lineup_stats.wilson(row['oppWins'], row['games'])],
        })
        if len(outcome_rows) >= 6:
            break
    return {
        'knownGames': total,
        'totalGames': len(games),
        'eventsKnown': True,
        'verifiedGames': verified,
        'assumedGames': assumed,
        'baseRate': round(base_rate, 1),
        'banOutcomeGames': len(outcome_games),
        'banOutcomeBaseRate': round(outcome_base_rate, 1) if outcome_base_rate is not None else None,
        'firstPicks': {
            'lanes': _bp_lane_rows(first_lanes, total),
            'heroes': _count_rows(first_heroes, total, 6),
        },
        'firstBans': {
            'own': _count_rows(own_first_ban, total, 4),
            'enemy': _count_rows(enemy_first_ban, total, 4),
        },
        'banSlots': {
            'own': [{'slot': i + 1, 'games': own_slot_games[i],
                     'heroes': _count_rows(own_ban_slots[i], own_slot_games[i], 2)}
                    for i in range(5) if own_slot_games[i]],
            'enemy': [{'slot': i + 1, 'games': enemy_slot_games[i],
                       'heroes': _count_rows(enemy_ban_slots[i], enemy_slot_games[i], 2)}
                      for i in range(5) if enemy_slot_games[i]],
        },
        'banResponse': response_rows,
        'banOutcome': outcome_rows,
    }


def _kpl_hit(kind, heroes, row, record) -> dict:
    opp_games = record.get('oppGames') or 0
    opp_wins = record.get('oppWins') or 0
    return {
        'kind': kind, 'heroes': list(heroes),
        'n': row.get('n'), 'wins': row.get('wins'), 'wr': row.get('wr'),
        'year': row.get('year'), 'teams': row.get('teams') or [],
        # 交手口径：我们与该队交手时这组英雄出现的场数 / 该对手赢下的场数
        'oppGames': opp_games, 'oppWins': opp_wins,
        'oppWinRate': round(opp_wins / opp_games * 100, 1) if opp_games else None,
    }


def _kpl_section(games) -> dict:
    """对手实际拿过的组合命中 KPL 组合表：双人 / 三人 / 整套阵容。"""
    import bp_facts
    from itertools import combinations
    index = bp_facts.kpl_index()
    pair_games, trio_games, lineup_games = {}, {}, {}
    for game in games:
        picks = ((game.get('sides') or {}).get('enemy') or {}).get('picks') or []
        heroes = sorted({pick.get('name') for pick in picks if pick.get('name')})
        enemy_win = game.get('opponentWin')
        for size, bucket in ((2, pair_games), (3, trio_games)):
            for group in combinations(heroes, size):
                record = bucket.setdefault(group, {'oppGames': 0, 'oppWins': 0})
                record['oppGames'] += 1
                if enemy_win is True:
                    record['oppWins'] += 1
        if len(heroes) == 5:
            record = lineup_games.setdefault(tuple(heroes), {'oppGames': 0, 'oppWins': 0})
            record['oppGames'] += 1
            if enemy_win is True:
                record['oppWins'] += 1

    hits = []
    for kind, bucket, table in (('pair', pair_games, index['pairs']),
                                ('trio', trio_games, index['trios'])):
        for heroes, record in bucket.items():
            row = table.get(heroes)
            if not row:
                continue
            hits.append(_kpl_hit(kind, heroes, row, record))
    hits.sort(key=lambda hit: (-hit['oppGames'], -(hit['n'] or 0), -len(hit['heroes'])))

    lineup = None
    best = None
    for heroes, record in lineup_games.items():
        row = index['lineups'].get(heroes)
        if not row:
            continue
        score = (record['oppGames'], row.get('n') or 0)
        if best is None or score > best[0]:
            best = (score, row, record, heroes)
    if best:
        lineup = _kpl_hit('lineup', best[3], best[1], best[2])
        lineup.pop('kind', None)
    else:
        lineup = {'heroes': [], 'n': None, 'wins': None, 'wr': None, 'year': None,
                  'teams': [], 'oppGames': 0, 'oppWins': None, 'oppWinRate': None}

    return {
        'source': index.get('source') or 'KPL 官方赛事',
        'games': index.get('games'),
        'sinceYear': index.get('sinceYear'),
        'updatedAt': index.get('updatedAt'),
        'windowStart': index.get('windowStart'),
        'windowEnd': index.get('windowEnd'),
        'hits': hits,
        'lineup': lineup,
    }


def _own_lane_players(panels) -> list:
    """本队五路名册：按「选手 + 分路」聚合全部面板，每路取局数最多的人。

    给「分路对位」用：name / lane / games 必有，另附 §2.4 需要的分均经济、
    分均输出、分均承伤、参团率、场均推塔、分均控制/治疗与 raw 累计值。
    """
    records: dict[tuple, dict] = {}
    heroes: dict[tuple, Counter] = {}
    for panel in panels or []:
        minutes = (panel.get('duration') or 0) / 60
        for player in panel.get('own_roster') or []:
            pid = str(player.get('id') or '')
            if not pid:
                continue
            group = (pid, player.get('lane') or '')
            record = records.get(group)
            if record is None:
                record = records[group] = _new_record({
                    'id': pid, 'name': clean_name(player.get('name')),
                    'lane': player.get('lane') or ''})
                heroes[group] = Counter()
            if not record['name'] and player.get('name'):
                record['name'] = clean_name(player['name'])
            _add(record, player, minutes, panel.get('win'))
            if player.get('hero'):
                heroes[group][clean_name(player['hero'])] += 1

    totals_keys = ('seconds', 'gold', 'kills', 'deaths', 'assists', 'damage',
                   'heroDamage', 'taken', 'control', 'heal', 'towers')
    rows = []
    for group, record in records.items():
        item = _finish(record)
        rows.append({
            'id': item['id'], 'name': item['name'], 'lane': item['lane'],
            'games': item['games'], 'winRate': item['winRate'],
            'kills': item['kills'], 'deaths': item['deaths'], 'assists': item['assists'],
            'kda': item['kda'], 'gpm': item['gpm'], 'dpm': item['dpm'], 'dtpm': item['dtpm'],
            'participation': item['participation'],
            'controlPerMin': item['controlPerMin'], 'healPerMin': item['healPerMin'],
            'towerPerGame': round(item['towers'] / item['games'], 2) if item['games'] else None,
            'heroes': [{'hero': hero, 'games': count}
                       for hero, count in heroes[group].most_common(4)],
            'totals': {name: record.get(name) for name in totals_keys},
        })

    # 每路只留出场最多的人：轮换/补位不会把同路两个人混进一张对位卡。
    # 输出顺序用页面展示顺序（对抗路 / 打野 / 中路 / 发育路 / 游走）。
    lane_order = {lane: index for index, lane in enumerate(
        ('对抗路', '打野', '中路', '发育路', '游走'))}
    best: dict[str, dict] = {}
    for row in rows:
        lane = row['lane'] or ''
        current = best.get(lane)
        if current is None or row['games'] > current['games'] or (
                row['games'] == current['games']
                and (row['name'] or '') < (current['name'] or '')):
            best[lane] = row
    return sorted(best.values(),
                  key=lambda row: (lane_order.get(row['lane'], 99), -row['games'],
                                   row['name'] or ''))


def _enemy_lineup_games(games) -> list:
    """deep games → 被研究战队视角的 lineup_stats 输入。

    team_deep 的 games 是本队视角：win=本队胜负、sides.enemy 才是被研究战队
    的阵容；红蓝方取对手阵营（docs/team_dossier_p0.md §2.5）。players / stats
    / oppStats / oppPicks 供 P2 的资源对照与对抗矩阵使用。
    """
    rows = []
    for game in games or []:
        enemy = (game.get('sides') or {}).get('enemy') or {}
        own = (game.get('sides') or {}).get('own') or {}
        own_side = game.get('ownSide')
        enemy_side = 'red' if own_side == 'blue' else 'blue' if own_side == 'red' else None
        rows.append({
            'seq': game.get('seq'),
            'win': game.get('opponentWin'),
            'side': enemy_side,
            'picks': enemy.get('picks') or [],
            'oppPicks': own.get('picks') or [],
            'players': [{'lane': p.get('lane'), 'gold': p.get('gold'),
                         'heroDamage': p.get('heroDamage'), 'taken': p.get('taken')}
                        for p in enemy.get('players') or []],
            'stats': enemy.get('stats') or {},
            'oppStats': own.get('stats') or {},
        })
    return rows


def _lineups_block(games) -> dict:
    """lineups 总块（§2.5 + P2 增量）：签名 / 组合 / 资源对照 / 对抗矩阵。"""
    import lineup_stats
    lu_games = _enemy_lineup_games(games)
    block = lineup_stats.team_lineups(lu_games)
    block['resources'] = lineup_stats.lineup_resources(lu_games)
    block['matchups'] = lineup_stats.matchup_matrix(lu_games)
    return block


DEMO_SERIES_PATH = Path(__file__).resolve().parent / 'data' / 'facts' / 'demo_series.json'


def load_demo_series(path=None) -> list:
    """演示系列赛定义（data/facts/demo_series.json）；缺文件返回空。"""
    p = Path(path) if path else DEMO_SERIES_PATH
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [s for s in data.get('series') or [] if isinstance(s, dict)]


def series_analysis(games, series_defs) -> list:
    """演示系列赛的 BO 演变分析（docs/team_dossier_p0.md §7.3）。

    规则口径 = 征召 draft-18：全局 BP 跨局禁复用，征召默认无巅峰对决；
    手序见 bp_formats.DRAFT_18.schedule（本分析只依赖每局选人集合，不依赖手序）。
    games 项来自 team-deep（对手=被研究战队视角）；不在系列赛定义里的 seq 跳过。
    """
    import hero_archetypes
    import lineup_stats
    by_seq = {str(g.get('seq')): g for g in games or []}
    laned = hero_archetypes.HERO_ARCHETYPES
    out = []
    for sdef in series_defs or []:
        rows = []
        used: set = set()
        prev_sig = prev_win = None
        score = {'wins': 0, 'losses': 0}
        for gref in sdef.get('games') or []:
            game = by_seq.get(str((gref or {}).get('seq')))
            if not game:
                continue
            picks = ((game.get('sides') or {}).get('enemy') or {}).get('picks') or []
            heroes = [p.get('name') for p in picks if p.get('name')]
            win = game.get('opponentWin')
            if win is True:
                score['wins'] += 1
            elif win is False:
                score['losses'] += 1
            sig = lineup_stats.signature_of(picks)
            new_heroes = [h for h in heroes if h not in used]
            used |= set(heroes)
            # 剩余可组类型组合（上限）：全英雄池 − 已用，按各分路可用的主类型数求积
            remaining_types = {lane: set() for lane in hero_archetypes.LANES}
            for hero in hero_archetypes.HERO_LABEL_META:
                if hero in used:
                    continue
                for lane, archetype in laned.get(hero, {}).items():
                    if lane in remaining_types:
                        remaining_types[lane].add(archetype)
            legal = 1
            for lane in hero_archetypes.LANES:
                legal *= max(1, len(remaining_types[lane]))
            adjust = adjust_ctx = None
            if prev_sig is not None and sig is not None:
                if sig == prev_sig:
                    adjust = '同体系'
                else:
                    lanes_changed = [hero_archetypes.LANES[i] for i in range(5)
                                     if sig[i] != prev_sig[i]]
                    adjust = '换体系：' + '、'.join(lanes_changed)
            if prev_win is not None:
                adjust_ctx = '赢后' if prev_win else '输后'
            rows.append({
                'gameNo': (gref or {}).get('gameNo'),
                'seq': str(game.get('seq') or ''),
                'matchKey': game.get('matchKey') or '',
                'win': win,
                'side': game.get('side'),
                'signature': list(sig) if sig else None,
                'heroes': heroes,
                'newHeroes': new_heroes,
                'usedCount': len(used),
                'legalCombos': legal,
                'adjust': adjust,
                'adjustContext': adjust_ctx,
            })
            prev_sig, prev_win = sig, win
        if not rows:
            continue
        rank = any(str((row or {}).get('ruleProfile') or '') == 'rank-20'
                   for row in games or [])
        rule_id = 'rank-20' if rank else 'draft-18'
        slots = 20 if rank else 18
        ban_text = '5+5 同时 Ban' if rank else '4 Ban'
        out.append({
            'seriesId': sdef.get('seriesId'),
            'bo': sdef.get('bo'),
            'label': sdef.get('label'),
            'demo': True,
            'rule': {'id': rule_id, 'slots': slots,
                     'note': f'全局 BP 跨局禁复用；每局 {ban_text} + 10 Pick（手序见 bp_formats）'},

            'score': score,
            'games': rows,
        })
    return out


_SEQ_KEY_CACHE: dict = {'stamp': None, 'map': {}}


def series_index(db_path) -> dict:
    """{match key: {'id','bestOf','gameNo'}}——训练系列赛登记表。

    营地面板本身没有赛制字段；只有赛训组在「系列赛」里登记过 BO，
    这里才给得出 BO3/BO5/BO7。查不到就是未知，不按局数猜赛制。
    """
    path = Path(db_path)
    if not path.is_file():
        return {}
    try:
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = connection.execute(
            'SELECT g.match_key, g.series_id, g.game_index, s.best_of '
            'FROM training_series_games g '
            'LEFT JOIN training_series s ON s.id = g.series_id').fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    out = {}
    for match_key, series_id, game_no, best_of in rows:
        if not match_key:
            continue
        out[str(match_key)] = {
            'id': str(series_id or ''),
            'bestOf': int(best_of) if isinstance(best_of, (int, float)) else None,
            'gameNo': int(game_no) if isinstance(game_no, (int, float)) else None,
        }
    return out


def seq_match_key_index(matches_dir) -> dict:
    """{campBp.gameSeq: 通道 key}——把营地局号映射到单局复盘的 match key。

    mtime 指纹缓存：目录未变时直接复用，避免每次 team-deep 全量重扫。
    """
    folder = Path(matches_dir)
    try:
        stamp = tuple(sorted((p.name, p.stat().st_mtime_ns)
                             for p in folder.glob('channel-*.json')))
    except OSError:
        stamp = ()
    if _SEQ_KEY_CACHE['stamp'] != stamp:
        mapping: dict[str, str] = {}
        for path in folder.glob('channel-*.json'):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            match = data.get('match') or {}
            seq = str((match.get('campBp') or {}).get('gameSeq') or '')
            key = str(match.get('key') or '')
            if seq and key:
                mapping[seq] = key
        _SEQ_KEY_CACHE['stamp'] = stamp
        _SEQ_KEY_CACHE['map'] = mapping
    return _SEQ_KEY_CACHE['map']


def team_deep(camp_dir, db_path, team_id) -> dict | None:
    """战队详情全量结构（§2.2 + lineups，见 docs/team_dossier_p0.md §2.5）。

    战队不存在（聚类里没有这个 id）返回 None，由路由转 404；
    能读到战队但缺字段时照常返回结构，值一律 None，让前端显示「证据不足」。
    """
    camp_dir = Path(camp_dir)
    panels = load_panels(camp_dir)
    data = _list_teams(panels, db_path)
    team = next((item for item in data.get('teams') or [] if item['id'] == team_id), None)
    if team is None:
        return None
    style_index = team_style.build_index(panels)
    panel_index = {str(panel.get('seq')): panel for panel in panels}
    games = [_deep_game(camp_dir, panel_index[seq], style_index)
             for seq in team.get('seqs') or [] if seq in panel_index]
    games.sort(key=lambda game: game.get('start') or '', reverse=True)
    seq_keys = seq_match_key_index(Path(camp_dir).parent / 'matches')
    series = series_index(db_path)
    for game in games:
        match_key = seq_keys.get(str(game.get('seq') or '')) or ''
        game['matchKey'] = match_key
        hit = series.get(match_key) or None
        game['series'] = hit
        game['bo'] = (hit or {}).get('bestOf')
    import ban_analysis
    import hero_archetypes
    import lineup_stats
    own = data.get('own') or {}
    bp_order = _bp_order_block(games)
    warnings = list(data.get('warnings') or [])
    if not games:
        warnings.append('没有读到该战队的营地终局面板。')
    empty_style = team_style.style([], style_index)
    bo_counts = Counter(game.get('bo') for game in games if game.get('bo'))
    bo_known = sum(bo_counts.values())
    draft_known = sum(1 for game in games if (game.get('draft') or {}).get('known'))
    return {
        'team': {key: team.get(key) for key in (
            'id', 'displayName', 'name', 'named', 'coach', 'matches', 'wins', 'losses',
            'winRate', 'firstSeen', 'lastSeen', 'players', 'currentPlayers',
            'rotationPlayers', 'formerPlayers', 'rosterWindow', 'rosterChanged',
            'heroes', 'metrics', 'percentiles', 'style')},
        'own': {'name': own.get('name') or '', 'matches': own.get('matches') or 0,
                'wins': own.get('wins') or 0, 'losses': own.get('losses') or 0,
                'winRate': own.get('winRate'),
                'players': _own_lane_players(panels),
                'metrics': own.get('metrics') or {},
                'percentiles': own.get('percentiles') or {},
                'style': own.get('style') or empty_style},
        'games': games,
        'lineups': _lineups_block(games),
        'bpOrder': bp_order,
        'banMatchup': ban_analysis.ban_matchup(games),
        'banReplacement': ban_analysis.replacement_structure(games, bp_order.get('banOutcome')),
        'poolDepth': ban_analysis.pool_depth(games),
        'series': series_analysis(games, load_demo_series()),
        'style': team.get('style') or empty_style,
        'taxonomy': hero_archetypes.taxonomy(),
        # 时间窗与赛制是两个筛选维度；覆盖度写进 meta，前端据实标注样本，
        # 不能把「没登记 BO」的局当成某个赛制。
        'coverage': {
            'games': len(games),
            'boKnown': bo_known,
            'boCounts': {str(bo): count for bo, count in sorted(bo_counts.items())},
            'draftKnown': draft_known,
            'draftVerified': int(bp_order.get('verifiedGames') or 0),
            'firstSeen': min((game.get('start') or '' for game in games), default=''),
            'lastSeen': max((game.get('start') or '' for game in games), default=''),
        },
        'kpl': _kpl_section(games),
        'meta': {
            'source': '营地终局面板',
            'days': 30,
            'thresholds': {'sample': team_style.SAMPLE_MIN,
                           'quadrantShare': team_style.QUADRANT_SHARE},
            'warnings': warnings,
            'limits': list(team_style.MISSING),
        },
    }

