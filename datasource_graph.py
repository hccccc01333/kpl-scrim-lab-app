"""赛事数据图谱（只读）：把某个赛事范围内的后端表、数据池与 ID 关联画成可体检的图。

给赛训组和开发者用：一眼看到「赛事 → 战队池 / 选手池 / 对局池」之间的线是不是真的连着，
哪条线断了、哪个 ID 指向已删除的实体、哪里改了名没全局同步。所有查询只读，不改任何数据。

约定：
- 表的中文名、字段含义统一放这里，前端只负责画。
- JSON 字符串数组字段（team_ids / own_player_ids / key_match_keys ...）必须 loads 后逐项核对。
- 真实库有历史残留列（event_cycle_id 等），一律按 PRAGMA 判断列是否存在后再取。
- team_clusters 与 teams 是两套 ID：cluster 由营地面板算 SHA1 得到，靠 mergedInto / 别名对接，
  所以「cluster-only」算提示而不是断链。
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

TABLE_LABELS = {
    'competitions': '赛事',
    'teams': '战队主数据',
    'team_clusters': '对手聚类池',
    'team_aliases': '战队别名映射',
    'team_relations': '战队关系',
    'players': '选手主数据',
    'player_accounts': '选手游戏账号',
    'player_team_history': '选手战队历史',
    'account_player_links': '账号 ↔ 选手关系',
    'player_nickname_pool': '选手昵称池',
    'identity_merge_logs': '身份合并记录',
    'team_roster_versions': '阵容版本',
    'match_records': '对局记录',
    'matches': '对局快照（旧）',
    'match_meta': '对局覆盖层',
    'match_rosters': '对局十人阵容',
    'training_series': '系列赛',
    'training_series_games': '系列赛 ↔ 对局',
    'schedules': '训练课 / 排期',
    'session_match_links': '训练课 ↔ 对局',
    'channels': '采集通道',
    'capture_batches': '采集批次',
    'focus_items': '重点关注',
    'change_log': '变更审计',
    'settings': '工作台设置',
    'profiles.json': '本队选手档案',
    'event_cycles': '赛事周期（已下线）',
    'bp': 'BP 快照',
    'training': '训练记录',
    'provenance': '数据来源溯源',
    'prefill_fields': '待确认字段',
    'workspace_meta': '工作区元数据',
}

# 一个实体最多带几个样例，避免接口体积随库增长
SAMPLE_LIMIT = 8


def _loads(raw, default=None):
    """安全地解开 JSON 字符串数组；坏数据退化为空数组，不让整页 500。"""
    if default is None:
        default = []
    try:
        value = json.loads(raw or '[]')
        return value if isinstance(value, (list, dict)) else default
    except (TypeError, ValueError):
        return default


def _obj(row):
    return dict(row) if row is not None else None


def _short(value, size=40):
    text = str(value if value is not None else '')
    return text if len(text) <= size else text[:size - 1] + '…'


def build(db_path, competition_id='', scope_keys=None):
    """返回赛事范围内的图谱数据。competition_id 为空时取第一场赛事。"""
    path = Path(db_path)
    connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    now = time.time()
    issues = []
    edges = []

    def issue(level, code, title, detail, count=1, samples=None, field=''):
        issues.append({
            'level': level, 'code': code, 'title': title, 'detail': detail,
            'count': count, 'field': field,
            'samples': [str(x) for x in (samples or [])[:SAMPLE_LIMIT]],
        })

    def edge(kind, source, target, label, ok=True, detail='', field='', empty=False, weak=False):
        # empty（还没数据）和 weak（文本匹配，不是 ID 绑定）都不算断链，别让红箭头误报。
        edges.append({
            'id': f'e{len(edges) + 1}', 'kind': kind, 'source': source,
            'target': target, 'label': label, 'ok': bool(ok), 'empty': bool(empty),
            'weak': bool(weak), 'detail': detail, 'field': field,
        })

    def columns(table):
        try:
            return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        except sqlite3.Error:
            return []

    def has(table, column):
        return column in columns(table)

    def all_rows(table, order=''):
        try:
            sql = f'SELECT * FROM "{table}"' + (f' ORDER BY {order}' if order else '')
            return [_obj(row) for row in connection.execute(sql)]
        except sqlite3.Error:
            return []

    # ---------- 表清单：所有表都要出现在「库清单」里，带行数与范围内行数 ----------
    table_names = []
    try:
        table_names = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    except sqlite3.Error:
        pass
    rows_by_table = {}
    for name in table_names:
        try:
            rows_by_table[name] = all_rows(name)
        except sqlite3.Error:
            rows_by_table[name] = []

    competitions = rows_by_table.get('competitions', [])
    teams = rows_by_table.get('teams', [])
    players = rows_by_table.get('players', [])
    clusters = rows_by_table.get('team_clusters', [])
    records = rows_by_table.get('match_records', [])
    series = rows_by_table.get('training_series', [])
    series_games = rows_by_table.get('training_series_games', [])
    schedules = rows_by_table.get('schedules', [])
    session_links = rows_by_table.get('session_match_links', [])
    rosters = rows_by_table.get('match_rosters', [])
    metas = rows_by_table.get('match_meta', [])
    aliases = rows_by_table.get('team_aliases', [])
    histories = rows_by_table.get('player_team_history', [])
    logs = rows_by_table.get('change_log', [])

    # 本队选手档案在 data/profiles.json，不在 SQLite 里：这是「本队」页真正的数据源。
    profile_path = Path(db_path).parent / 'profiles.json'
    profile_doc = {}
    if profile_path.is_file():
        try:
            profile_doc = json.loads(profile_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile_doc = {}
    profile_own = profile_doc.get('own') if isinstance(profile_doc.get('own'), list) else []
    profile_rows = [{'id': p.get('id'), 'name': p.get('realName') or p.get('matchId'),
                     'position': p.get('mainLane'), 'camp_user_id': p.get('matchId'),
                     'source': 'profiles.json'} for p in profile_own if isinstance(p, dict)]
    rows_by_table['profiles.json'] = profile_rows
    if 'profiles.json' not in table_names:
        table_names.append('profiles.json')

    # 本队资料在 settings 里，战队/选手主数据在 teams / players 里。
    # 图必须同时看这两边，才能发现「资料填了但没落库」这种真正的后端断链。
    settings_doc = {}
    for item in rows_by_table.get('settings', []):
        if str(item.get('id')) == '1':
            settings_doc = _loads(item.get('body'), {}) or {}
    own_name = str(settings_doc.get('teamName') or '').strip()
    own_roster = settings_doc.get('roster') if isinstance(settings_doc.get('roster'), list) else []
    meta_doc = {str(item.get('key')): item.get('value') for item in rows_by_table.get('workspace_meta', [])}

    comp = next((c for c in competitions if str(c.get('id')) == str(competition_id)), None) if competition_id else (competitions[0] if competitions else None)
    cid = str(comp.get('id') or '') if comp else ''

    team_ids = {str(t.get('id')) for t in teams}
    # 删除战队只是把 teams 归档，team_clusters 里的聚类会留下来；
    # 这些已下架的战队不该再出现在对手聚类池里。
    archived_team_ids = {str(t.get('id')) for t in teams if str(t.get('status') or '') == 'archived'}
    player_ids = {str(p.get('id')) for p in players}
    cluster_ids = {str(c.get('key')) for c in clusters}
    record_keys = {str(r.get('match_key')) for r in records}
    series_ids = {str(s.get('id')) for s in series}

    declared_teams = [str(x) for x in _loads(comp.get('team_ids') if comp else None)]
    declared_players = [str(x) for x in _loads(comp.get('own_player_ids') if comp else None)]
    declared_matches = [str(x) for x in _loads(comp.get('key_match_keys') if comp else None)]
    opponent_team_id = str(comp.get('opponent_team_id') or '') if comp else ''

    # 本队战队：优先用工作区记录的稳定 ID，退而按当前队名找； archived 不算。
    own_team_id = str(meta_doc.get('own_team_id') or '')
    own_team = next((t for t in teams if str(t.get('id')) == own_team_id), None) if own_team_id else None
    if own_team is None and own_name:
        own_team = next((t for t in teams
                         if str(t.get('name')) == own_name and str(t.get('status')) != 'archived'), None)
    if own_team is not None:
        own_team_id = str(own_team.get('id'))

    # ---------- 赛事范围：统一口径由调用方传入（Workspace.competition_scope_keys） ----------
    scoped_series = [s for s in series if str(s.get('competition_id') or '') == cid]
    scoped_series_ids = {str(s.get('id')) for s in scoped_series}
    scoped_series_keys = {str(g.get('match_key')) for g in series_games
                          if str(g.get('series_id') or '') in scoped_series_ids}
    direct_keys = {str(r.get('match_key')) for r in records
                   if str(r.get('competition_id') or '') == cid}
    passed_keys = {str(k) for k in (scope_keys or []) if k}
    scoped_match_keys = set(declared_matches) | scoped_series_keys | direct_keys | passed_keys
    scoped_matches = [r for r in records if str(r.get('match_key')) in scoped_match_keys]
    scoped_schedules = [s for s in schedules if str(s.get('competition_id') or '') == cid]
    scoped_schedule_ids = {str(s.get('id')) for s in scoped_schedules}
    scoped_links = [l for l in session_links if str(l.get('schedule_id') or '') in scoped_schedule_ids]
    scoped_meta = [m for m in metas if str(m.get('match_key')) in scoped_match_keys]
    scoped_rosters = [r for r in rosters if str(r.get('match_key')) in scoped_match_keys]

    # 战队：本队 + 声明的 + 赛事对手 + 范围内对局/系列赛引用的
    referenced_team_ids = set(declared_teams)
    if own_team_id:
        referenced_team_ids.add(own_team_id)
    if opponent_team_id:
        referenced_team_ids.add(opponent_team_id)
    for item in scoped_matches:
        for field in ('own_team_id', 'enemy_team_id'):
            value = str(item.get(field) or '')
            if value:
                referenced_team_ids.add(value)
    for item in scoped_series:
        value = str(item.get('opponent_team_id') or '')
        if value:
            referenced_team_ids.add(value)
    # 归档的战队/选手不再算作池子里的活数据；被引用只报问题，不混进池子。
    scoped_teams = [t for t in teams
                    if str(t.get('id')) in referenced_team_ids
                    and str(t.get('status')) != 'archived']

    # 选手：本队档案 + 声明的 + 范围内对局阵容里的 + 挂在范围内战队下的
    referenced_player_ids = set(declared_players)
    for member in own_roster:
        value = str(member.get('id') or '').strip()
        if value:
            referenced_player_ids.add(value)
    for member in profile_rows:
        value = str(member.get('id') or '').strip()
        if value:
            referenced_player_ids.add(value)
    for item in scoped_rosters:
        value = str(item.get('player_id') or '')
        if value:
            referenced_player_ids.add(value)
    referenced_players = [p for p in players
                          if str(p.get('id')) in referenced_player_ids
                          or str(p.get('team_id')) in referenced_team_ids]
    archived_referenced = [p for p in referenced_players if str(p.get('status')) == 'archived']
    scoped_players = [p for p in referenced_players if str(p.get('status')) != 'archived']

    # 资料里填了、但 players 表没有的选手：以「未落库」的幽灵项显示，方便一眼看出断链
    own_roster_ids_of_players = {str(m.get('id') or '') for m in own_roster if m.get('id')}
    player_items = [{
        'id': str(p.get('id')), 'label': str(p.get('name') or '未命名选手'),
        'status': str(p.get('status') or 'active'),
        'detail': str(p.get('position') or ''),
        'badges': (['赛事声明'] if str(p.get('id')) in declared_players else [])
                  + (['本队'] if str(p.get('id')) in own_roster_ids_of_players else []),
        'fields': {'id': str(p.get('id')), 'name': str(p.get('name') or ''),
                   'team_id': str(p.get('team_id') or ''),
                   'camp_user_id': str(p.get('camp_user_id') or '')},
    } for p in scoped_players]
    own_roster_ids = {str(p.get('id')) for p in players} | {str(x.get('id')) for x in player_items}
    player_names = {str(p.get('name') or '').strip() for p in players}
    player_camp_ids = {str(p.get('camp_user_id') or '').strip() for p in players}

    def already_landed(member):
        camp_id = str(member.get('camp_user_id') or '').strip()
        name = str(member.get('name') or '').strip()
        return (bool(camp_id) and camp_id in player_camp_ids) or (bool(name) and name in player_names)

    for member in own_roster + profile_rows:
        member_id = str(member.get('id') or '').strip()
        if not member_id or member_id in own_roster_ids or already_landed(member):
            continue
        player_items.append({
            'id': member_id, 'label': str(member.get('name') or member_id),
            'status': 'active', 'detail': str(member.get('position') or ''),
            'badges': ['本队档案', '未落库'],
            'fields': {'id': member_id, 'name': str(member.get('name') or ''),
                       'camp_user_id': str(member.get('camp_user_id') or '')},
        })

    # 名字 → 战队 ID（含别名），用于文本对手的改名/未同步检测
    name_map = {}
    for team in teams:
        tid = str(team.get('id'))
        for name in [team.get('name'), team.get('short_name')] + _loads(team.get('aliases')):
            if name and str(name).strip():
                name_map.setdefault(str(name).strip(), tid)

    def current_name(value):
        """文本队名 → 当前主数据里的正式名；返回 (显示名, 是否为旧名)。"""
        key = str(value or '').strip()
        tid = name_map.get(key)
        if not tid:
            return key, False
        row = next((t for t in teams if str(t.get('id')) == tid), None)
        if row and str(row.get('name') or '').strip() != key:
            return str(row.get('name')).strip(), True
        return key, False

    alias_map = {}
    for item in aliases:
        alias_map[str(item.get('old_id') or '')] = str(item.get('team_id') or '')

    # ---------- 边：赛事声明的池 ----------
    for field, label, refs, target_ids, target_pool in (
        ('team_ids', '参赛战队池', declared_teams, team_ids, 'teams'),
        ('own_player_ids', '本队选手池', declared_players, player_ids, 'players'),
        ('key_match_keys', '关键对局', declared_matches, record_keys, 'matches'),
    ):
        broken = [x for x in refs if x not in target_ids]
        edge('declared', 'competition', target_pool, label, ok=not broken, empty=not refs,
             detail=f'{len(refs)} 项声明', field=field)
        if not refs:
            issue('warn', 'empty_pool', f'{label}是空的',
                  '赛事没有声明这一项，按 ID 画不出线；相关页面可能因此为空。', field=field)
        if broken:
            issue('error', 'broken_ref', f'{label}里有失效 ID',
                  f'{len(broken)} 个 ID 在目标表里找不到（指向已删除或从未建档的实体）。',
                  len(broken), broken)
    if opponent_team_id:
        ok = opponent_team_id in team_ids
        edge('declared', 'competition', 'teams', '指定对手战队', ok=ok, field='opponent_team_id')
        if not ok:
            issue('error', 'broken_ref', '赛事指定的对手战队不存在',
                  f'ID {opponent_team_id} 在战队主数据里找不到。', 1, [opponent_team_id])

    # 本队资料 → 战队池 / 选手池：这两条线是「填了就该落库」的硬约束。
    edge('declared', 'settings', 'teams', '本队战队', ok=own_team is not None,
         empty=not own_name, detail=own_name or '', field='teamName')
    missing_own_players = [m for m in own_roster
                           if str(m.get('id') or '') and str(m.get('id')) not in player_ids]
    edge('declared', 'settings', 'players', '本队选手档案', ok=not missing_own_players,
         empty=not own_roster, detail=f'{len(own_roster)} 人', field='roster')
    if own_name and own_team is None:
        issue('error', 'own_team_missing', '本队战队填了但没进战队池',
              f'本队资料里写的是「{own_name}」，但 teams 表里没有这支战队。'
              '正常的链路是：本队页填名字 → 自动落到战队池，现在这一步断了。', 1, [own_name])
    if missing_own_players:
        issue('error', 'own_players_missing', '本队选手填了但没进选手池',
              f'{len(missing_own_players)} 名选手在本队资料里，但 players 表里没有对应记录。',
              len(missing_own_players), [str(m.get('name') or m.get('id')) for m in missing_own_players])

    missing_profile_players = [p for p in profile_rows
                               if str(p.get('id')) not in player_ids and not already_landed(p)]
    edge('declared', 'profiles.json', 'players', '本队选手档案', ok=not missing_profile_players,
         empty=not profile_rows, detail=f'{len(profile_rows)} 人', field='own')
    if missing_profile_players:
        issue('error', 'own_players_missing', '本队选手档案还没落进选手池',
              f'{len(missing_profile_players)} 名选手在 data/profiles.json 里，但 players 主数据表没有对应记录；'
              '图上按未落库显示。', len(missing_profile_players),
              [str(p.get('name') or p.get('id')) for p in missing_profile_players])

    # ---------- 边：赛事 ← 系列赛 / 对局 / 训练课（真实业务范围） ----------
    edge('reverse', 'series', 'competition', '系列赛归属',
         empty=not scoped_series, detail=f'{len(scoped_series)} 个系列赛', field='competition_id')
    direct = [r for r in scoped_matches if str(r.get('competition_id') or '') == cid]
    indirect = [r for r in scoped_matches if str(r.get('competition_id') or '') != cid]
    edge('reverse', 'matches', 'competition', '对局直连', empty=not scoped_matches,
         detail=f'{len(direct)} 局直连 / {len(indirect)} 局间接', field='competition_id')
    if indirect:
        issue('warn', 'indirect_scope', '对局只通过系列赛归属赛事',
              f'{len(indirect)} 局的 competition_id 为空，靠系列赛关系表才归到当前赛事；'
              '直连查询（赛事页的「对局」页签）会看不到这些局。', len(indirect),
              [r.get('match_key') for r in indirect])
    edge('reverse', 'sessions', 'competition', '训练课归属',
         empty=not scoped_schedules, detail=f'{len(scoped_schedules)} 个训练课', field='competition_id')
    edge('relation', 'series_games', 'matches', '系列赛包含对局',
         empty=not scoped_series_keys, detail=f'{len(scoped_series_keys)} 条关系')
    broken_series_games = [g for g in series_games
                           if str(g.get('series_id')) in scoped_series_ids
                           and str(g.get('match_key')) not in record_keys]
    if broken_series_games:
        issue('error', 'broken_ref', '系列赛指向不存在的对局',
              f'{len(broken_series_games)} 条关系里的 match_key 在对局记录里找不到。',
              len(broken_series_games), [g.get('match_key') for g in broken_series_games])
    edge('relation', 'session_links', 'matches', '训练课挂对局', empty=not scoped_links,
         detail=f'{len(scoped_links)} 条关系')

    # ---------- 边：对局 → 战队 / 聚类 / 覆盖层 ----------
    orphan_team = [r for r in scoped_matches
                   if str(r.get('enemy_team_id') or '') and str(r.get('enemy_team_id')) not in team_ids]
    edge('reference', 'matches', 'teams', '对局对手战队 ID',
         ok=not orphan_team, detail=f'{len(scoped_matches)} 局', field='enemy_team_id')
    if orphan_team:
        issue('error', 'orphan_ref', '对局的对手战队 ID 指向空战队',
              f'{len(orphan_team)} 局的 enemy_team_id 在 teams 表里找不到。',
              len(orphan_team), [r.get('enemy_team_id') for r in orphan_team])
    orphan_cluster = [r for r in scoped_matches
                      if str(r.get('enemy_cluster_id') or '') and str(r.get('enemy_cluster_id')) not in cluster_ids]
    if orphan_cluster:
        issue('error', 'orphan_ref', '对局的聚类 ID 指向空聚类',
              f'{len(orphan_cluster)} 局的 enemy_cluster_id 在 team_clusters 里找不到。',
              len(orphan_cluster), [r.get('enemy_cluster_id') for r in orphan_cluster])
    edge('reference', 'matches', 'clusters', '对局对手聚类',
         empty=not any(r.get('enemy_cluster_id') for r in scoped_matches),
         detail=f'{len([r for r in scoped_matches if r.get("enemy_cluster_id")])} 局',
         field='enemy_cluster_id')

    # 文本对手：能按名字/别名解析就是通的；走别名才是「改名没同步」
    text_names = []
    for item in scoped_matches:
        meta = next((m for m in scoped_meta if str(m.get('match_key')) == str(item.get('match_key'))), None)
        name = str((meta or {}).get('opponent') or item.get('opponent') or '').strip()
        if name:
            text_names.append(name)
    for item in scoped_series:
        name = str(item.get('opponent') or '').strip()
        if name:
            text_names.append(name)
    unresolved = [n for n in text_names if n not in name_map]
    via_alias = [n for n in text_names if n in name_map and not any(
        str(t.get('name')) == n for t in teams)]
    edge('text', 'matches', 'teams', '文本对手 → 战队',
         ok=not unresolved, weak=True, empty=not text_names,
         detail=f'{len(text_names)} 个对手名', field='opponent')
    if unresolved:
        issue('warn', 'text_opponent', '对手只有文本、没有战队 ID',
              f'{len(unresolved)} 处对手名无法对应到战队主数据；改名或合并时不会自动同步。',
              len(unresolved), unresolved)
    if via_alias:
        issue('warn', 'name_not_synced', '改名没有全局同步',
              '有些地方还写着旧队名（只能靠别名认出来），说明改名没有把所有引用一起更新。'
              '图里的队名已按当前主数据纠正显示，但原始字段仍是旧值。',
              len(via_alias), [f'{n} → {current_name(n)[0]}' for n in via_alias])

    # ---------- 边：选手 → 战队；战队别名 / 合并链 ----------
    orphan_players = [p for p in players
                      if str(p.get('team_id') or '') and str(p.get('team_id')) not in team_ids]
    edge('reference', 'players', 'teams', '选手所属战队',
         ok=not orphan_players, empty=not players, detail=f'{len(players)} 人', field='team_id')
    if orphan_players:
        issue('error', 'orphan_ref', '选手挂在已不存在的战队上',
              f'{len(orphan_players)} 名选手的 team_id 指向已删除/归档后不可见的战队。',
              len(orphan_players), [f'{p.get("name")} → {p.get("team_id")}' for p in orphan_players])
    if archived_referenced:
        issue('warn', 'archived_ref', '归档选手仍被引用',
              '这些选手状态是 archived，已经从选手池里剔除；若仍被对局或战队引用，统计口径会不一致。',
              len(archived_referenced), [p.get('name') for p in archived_referenced])
    broken_alias = [(a.get('old_id'), a.get('team_id')) for a in aliases
                    if str(a.get('team_id') or '') not in team_ids]
    edge('relation', 'aliases', 'teams', '旧 ID → 现战队',
         ok=not broken_alias, empty=not aliases, detail=f'{len(aliases)} 条映射')
    if broken_alias:
        issue('error', 'broken_ref', '别名映射指向空战队',
              f'{len(broken_alias)} 条旧 ID 映射的 team_id 找不到。',
              len(broken_alias), [x[1] for x in broken_alias])

    merged_cluster = []
    cluster_items = []
    for item in clusters:
        key = str(item.get('key'))
        if key in archived_team_ids:
            continue
        body = _loads(item.get('body'), {})
        into = str(body.get('mergedInto') or '')
        state = 'merged' if into else 'active'
        if key not in team_ids:
            cluster_items.append({'id': key, 'label': str(body.get('name') or key),
                                  'status': state, 'detail': f'合并到 {into}' if into else '仅聚类，未建主数据',
                                  'badges': ['已合并' if into else '未建档'],
                                   'fields': {'id': key, 'name': str(body.get('name') or ''), 'mergedInto': into}})
            if into and into not in team_ids:
                merged_cluster.append((key, into))
            elif into:
                edge('relation', 'clusters', 'teams', f'{key} 已合并', ok=True, detail=into)
            else:
                issue('info', 'cluster_only', '聚类没有对应战队主数据',
                      '这类对手是营地阵容聚类出来的，还没在战队池里建档；不是断链，但按 ID 找不到它。',
                      1, [key])
        else:
            cluster_items.append({'id': key, 'label': str(body.get('name') or key),
                                  'status': state, 'detail': '', 'badges': [], 'fields': {'id': key, 'name': str(body.get('name') or ''), 'mergedInto': into}})
    if merged_cluster:
        issue('error', 'broken_ref', '合并目标战队不存在',
              f'{len(merged_cluster)} 个聚类的 mergedInto 指向空战队，合并链是断的。',
              len(merged_cluster), [x[1] for x in merged_cluster])

    # 重名战队：按名字连线会串线，必须按 ID
    name_counts = {}
    for team in teams:
        key = str(team.get('name') or '').strip()
        if key:
            name_counts.setdefault(key, []).append(str(team.get('id')))
    dup_names = {k: v for k, v in name_counts.items() if len(v) > 1}
    if dup_names:
        issue('warn', 'duplicate_name', '战队池里有重名',
              '同名战队有多条主数据，按名字找战队会串线；请确认是否该合并。',
              len(dup_names), [f'{k}（{len(v)} 条）' for k, v in dup_names.items()])

    # 变更审计引用已删除实体：只提示，不算断链
    deleted_refs = []
    for log in logs[-40:]:
        entity_id = str(log.get('entity_id') or '')
        entity_type = str(log.get('entity_type') or '')
        if not entity_id:
            continue
        exists = (entity_id in team_ids if entity_type in ('team', 'cluster') else
                  entity_id in player_ids if entity_type == 'player' else
                  entity_id in series_ids if entity_type == 'series' else
                  entity_id in record_keys if entity_type in ('match', 'game') else None)
        if exists is False:
            deleted_refs.append(f'{entity_type}:{entity_id}')
    if deleted_refs:
        issue('info', 'deleted_ref', '变更记录里有已删除的实体',
              '这些 ID 在审计日志里还有，但实体已经删掉；属于历史留痕，不是断链。',
              len(deleted_refs), deleted_refs)

    unbound = [p for p in scoped_players if not str(p.get('camp_user_id') or '').strip()]
    if unbound:
        issue('warn', 'unbound_player', '选手没有游戏 ID 映射',
              '营地再爬到也认不出这些人，选手数据会散在昵称里。', len(unbound),
              [p.get('name') for p in unbound])
    drafts = [r for r in scoped_matches if str(r.get('status')) == 'draft']
    if drafts:
        issue('warn', 'draft_match', '范围内还有草稿对局',
              '草稿局不进入分析快照，统计页会看不到它们。', len(drafts),
              [r.get('match_key') for r in drafts])

    # ---------- 池：每个池列出实体，实体上挂它自己的链接状态 ----------
    def team_badges(team):
        tid = str(team.get('id'))
        badges = []
        if str(team.get('status')) == 'archived':
            badges.append('已归档')
        if tid in declared_teams:
            badges.append('赛事声明')
        if tid == opponent_team_id:
            badges.append('指定对手')
        if tid in {str(s.get('opponent_team_id')) for s in scoped_series}:
            badges.append('系列赛对手')
        return badges

    def player_badges(player):
        pid = str(player.get('id'))
        badges = []
        if pid in declared_players:
            badges.append('赛事声明')
        if str(player.get('status')) == 'archived':
            badges.append('已归档')
        if not str(player.get('camp_user_id') or '').strip():
            badges.append('无游戏ID')
        return badges

    def match_badges(record):
        key = str(record.get('match_key'))
        badges = []
        if str(record.get('competition_id') or '') == cid:
            badges.append('直连赛事')
        elif key in scoped_series_keys:
            badges.append('系列赛归属')
        if str(record.get('status')) == 'draft':
            badges.append('草稿')
        if key in declared_matches:
            badges.append('关键局')
        return badges

    team_items = [{'id': str(t.get('id')), 'label': str(t.get('name') or '未命名战队'),
                   'status': str(t.get('status') or 'active'),
                   'detail': f'别名 {len(_loads(t.get("aliases")))} 个' if _loads(t.get('aliases')) else '',
                   'badges': team_badges(t) + (['本队'] if str(t.get('id')) == own_team_id else []),
                   'fields': {'id': str(t.get('id')), 'name': str(t.get('name') or ''),
                              'short_name': str(t.get('short_name') or ''),
                              'aliases': [str(x) for x in _loads(t.get('aliases'))]}}
                  for t in scoped_teams]
    if own_name and own_team is None:
        team_items.append({'id': 'settings:' + own_name, 'label': own_name,
                           'status': 'active', 'detail': '本队资料已填，战队主数据里没有',
                           'badges': ['本队', '未落库']})

    pools = [
        {
            'key': 'teams', 'label': '战队池', 'table': 'teams',
            'total': len(teams), 'scoped': len(team_items),
            'note': '本队 + 赛事声明的参赛战队、指定对手，以及范围内对局/系列赛引用到的战队。归档队不算在池内。',
            'items': team_items,
        },
        {
            'key': 'players', 'label': '选手池', 'table': 'players',
            'total': len(players), 'scoped': len(player_items),
            'note': '本队选手档案 + 赛事声明 + 范围内对局阵容与战队下挂的选手。归档选手不进池。',
            'items': player_items,
        },
        {
            'key': 'matches', 'label': '对局池', 'table': 'match_records',
            'total': len(records), 'scoped': len(scoped_matches),
            'note': '直连赛事 + 系列赛关系表 + 赛事窗口归集 + 手动挂载的并集。',
            'items': [{'id': str(r.get('match_key')),
                       'label': current_name(_short(next((m.get('opponent') for m in scoped_meta
                                             if str(m.get('match_key')) == str(r.get('match_key'))), '')
                                       or r.get('session') or '对手未标注'))[0],
                       'status': str(r.get('status') or ''),
                       'detail': str(r.get('date') or ''), 'badges': match_badges(r), 'fields': {'id': str(r.get('match_key')), 'match_key': str(r.get('match_key')), 'series_id': str(r.get('series_id') or ''), 'competition_id': str(r.get('competition_id') or ''), 'schedule_id': str(r.get('schedule_id') or ''), 'own_team_id': str(r.get('own_team_id') or ''), 'enemy_team_id': str(r.get('enemy_team_id') or ''), 'enemy_cluster_id': str(r.get('enemy_cluster_id') or ''), 'opponent': _short(next((m.get('opponent') for m in scoped_meta if str(m.get('match_key')) == str(r.get('match_key'))), ''))}}
                      for r in scoped_matches],
        },
        {
            'key': 'series', 'label': '系列赛池', 'table': 'training_series',
            'total': len(series), 'scoped': len(scoped_series),
            'note': '赛事归属主要靠这张表；断掉的话赛事下面的局就散了。',
            'items': [{'id': str(s.get('id')),
                       'label': current_name(s.get('opponent'))[0] or '未命名系列赛',
                       'status': str(s.get('status') or ''),
                       'detail': f"{len([g for g in series_games if str(g.get('series_id')) == str(s.get('id'))])} 局",
                       'badges': ['当前赛事'] + (['旧名'] if current_name(s.get('opponent'))[1] else []), 'fields': {'id': str(s.get('id')), 'opponent': str(s.get('opponent') or ''), 'opponent_team_id': str(s.get('opponent_team_id') or ''), 'competition_id': str(s.get('competition_id') or ''), 'schedule_id': str(s.get('schedule_id') or '')}}
                      for s in scoped_series],
        },
        {
            'key': 'clusters', 'label': '对手聚类池', 'table': 'team_clusters',
            'total': len(clusters), 'scoped': len(cluster_items),
            'note': '营地按阵容算出来的对手身份；和 teams 是两套 ID，靠 mergedInto / 别名对接。',
            'items': cluster_items,
        },
        {
            'key': 'sessions', 'label': '训练课', 'table': 'schedules',
            'total': len(schedules), 'scoped': len(scoped_schedules),
            'note': '赛事范围内的训练课，通过对局关系表挂到具体局。',
            'items': [{'id': str(s.get('id')), 'label': str(s.get('session') or s.get('date') or '未命名训练课'),
                       'status': '', 'detail': str(s.get('date') or ''), 'badges': [],
                        'fields': {'id': str(s.get('id')), 'name': str(s.get('session') or ''), 'competition_id': str(s.get('competition_id') or '')}}
                      for s in scoped_schedules],
        },
    ]

    # ---------- 关系模型（Power BI 风格）：字段级连线 + 单个实体的下钻 ----------
    def table_label(name):
        return TABLE_LABELS.get(name, name)

    def cell_values(value):
        if isinstance(value, (list, tuple)):
            return [str(x).strip() for x in value if str(x).strip()]
        text = str(value or '').strip()
        return [text] if text else []

    def values_of(table, column):
        virtual = {
            ('settings', 'teamName'): [own_name],
            ('profiles.json', 'name'): [str(r.get('name') or '') for r in profile_rows],
            ('profiles.json', 'camp_user_id'): [str(r.get('camp_user_id') or '') for r in profile_rows],
        }
        if (table, column) in virtual:
            return {v for v in virtual[(table, column)] if v}
        values = set()
        for row in rows_by_table.get(table, []):
            values.update(cell_values(row.get(column)))
        return values

    def row_label(table, row):
        for field in ('name', 'realName', 'opponent', 'match_key', 'session', 'key', 'id'):
            value = row.get(field)
            if value and str(value).strip():
                return str(value).strip()
        return '—'

    def matching_rows(table, column, value):
        out = []
        for row in rows_by_table.get(table, []):
            if value in cell_values(row.get(column)):
                out.append({'id': str(row.get('id') or row.get('match_key') or row.get('key') or ''),
                            'label': row_label(table, row), 'table': table})
        return out

    # (起点表, 起点字段, 终点表, 终点字段, 基数, 类型, 说明)
    relation_specs = [
        ('teams', 'id', 'players', 'team_id', '1:N', 'ID', '战队 → 队下选手'),
        ('teams', 'name', 'training_series', 'opponent', '1:N', '文本', '战队名 → 系列赛文本对手'),
        ('teams', 'short_name', 'training_series', 'opponent', '1:N', '文本', '战队简称 → 系列赛对手'),
        ('teams', 'aliases', 'training_series', 'opponent', 'N:N', '文本', '旧名别名 → 系列赛对手'),
        ('teams', 'id', 'training_series', 'opponent_team_id', '1:N', 'ID', '战队 → 系列赛指定对手'),
        ('teams', 'id', 'match_records', 'enemy_team_id', '1:N', 'ID', '战队 → 对局对手'),
        ('teams', 'id', 'match_records', 'own_team_id', '1:N', 'ID', '战队 → 对局本队'),
        ('teams', 'id', 'team_aliases', 'team_id', '1:N', 'ID', '战队 → 旧 ID 映射'),
        ('team_clusters', 'mergedInto', 'teams', 'id', 'N:1', 'ID', '聚类合并目标 → 战队'),
        ('players', 'id', 'match_rosters', 'player_id', '1:N', 'ID', '选手 → 10 人阵容里的位置'),
        ('players', 'id', 'player_accounts', 'player_id', '1:N', 'ID', '选手 → 游戏账号'),
        ('players', 'id', 'player_nickname_pool', 'player_id', '1:N', 'ID', '选手 → 营地昵称映射'),
        ('player_nickname_pool', 'player_id', 'players', 'id', 'N:1', 'ID', '营地昵称 → 选手主数据'),
        ('match_rosters', 'player_id', 'players', 'id', 'N:1', 'ID', '阵容里的选手 ID → 选手池'),
        ('match_rosters', 'team_id', 'teams', 'id', 'N:1', 'ID', '阵容里的战队 ID → 战队池'),
        ('players', 'team_id', 'teams', 'id', 'N:1', 'ID', '选手 → 所属战队'),
        ('match_records', 'match_key', 'match_rosters', 'match_key', '1:N', 'ID', '对局 → 阵容里的 10 个名字'),
        ('match_records', 'match_key', 'training_series_games', 'match_key', '1:N', 'ID', '对局 → 系列赛关系'),
        ('match_records', 'series_id', 'training_series', 'id', 'N:1', 'ID', '对局 → 系列赛'),
        ('match_records', 'competition_id', 'competitions', 'id', 'N:1', 'ID', '对局 → 赛事'),
        ('training_series', 'id', 'training_series_games', 'series_id', '1:N', 'ID', '系列赛 → 包含的对局'),
        ('training_series', 'competition_id', 'competitions', 'id', 'N:1', 'ID', '系列赛 → 赛事'),
        ('training_series', 'opponent_team_id', 'teams', 'id', 'N:1', 'ID', '系列赛 → 战队'),
        ('training_series', 'schedule_id', 'schedules', 'id', 'N:1', 'ID', '系列赛 → 训练课'),
        ('schedules', 'competition_id', 'competitions', 'id', 'N:1', 'ID', '训练课 → 赛事'),
        ('settings', 'teamName', 'teams', 'name', '1:1', '文本', '本队资料 → 战队池'),
        ('profiles.json', 'name', 'players', 'name', '1:1', '文本', '本队选手档案 → 选手池'),
        ('profiles.json', 'camp_user_id', 'players', 'camp_user_id', '1:1', 'ID', '档案游戏 ID → 选手账号'),
    ]

    relationships = []
    for from_table, from_col, to_table, to_col, card, kind, label in relation_specs:
        left = values_of(from_table, from_col)
        right = values_of(to_table, to_col)
        matched = left & right
        state = 'linked' if matched else ('empty' if not left or not right else 'broken')
        relationships.append({
            'from': {'table': from_table, 'label': table_label(from_table), 'column': from_col},
            'to': {'table': to_table, 'label': table_label(to_table), 'column': to_col},
            'cardinality': card, 'kind': kind, 'label': label, 'state': state,
            'count': len(matched),
            'fromRows': len(left), 'toRows': len(right),
        })

    # 单实体下钻：从池子里的每个实体出发，按同一套关系规格找它的上下游。
    entity_links = []
    for pool in pools:
        for item in pool['items'][:200]:
            fields = item.get('fields') or {}
            links = []
            for from_table, from_col, to_table, to_col, card, kind, label in relation_specs:
                if from_table == pool['table']:
                    for value in cell_values(fields.get(from_col)):
                        targets = matching_rows(to_table, to_col, value)
                        if targets:
                            links.append({'direction': 'out', 'cardinality': card, 'kind': kind,
                                          'label': label, 'value': value,
                                          'via': f'{table_label(from_table)}.{from_col} → {table_label(to_table)}.{to_col}',
                                          'peers': targets[:12], 'total': len(targets)})
                if to_table == pool['table']:
                    for value in cell_values(fields.get(to_col)):
                        sources = matching_rows(from_table, from_col, value)
                        if sources:
                            links.append({'direction': 'in', 'cardinality': card, 'kind': kind,
                                          'label': label, 'value': value,
                                          'via': f'{table_label(from_table)}.{from_col} → {table_label(to_table)}.{to_col}',
                                          'peers': sources[:12], 'total': len(sources)})
            entity_links.append({
                'pool': pool['key'], 'poolLabel': pool['label'],
                'id': item['id'], 'label': item['label'], 'links': links,
            })

    tables = []
    scoped_counts = {
        'competitions': 1 if comp else 0, 'teams': len(team_items), 'players': len(player_items),
        'team_clusters': len(cluster_items), 'match_records': len(scoped_matches),
        'training_series': len(scoped_series), 'schedules': len(scoped_schedules),
        'training_series_games': len([g for g in series_games
                                      if str(g.get('series_id')) in scoped_series_ids]),
        'session_match_links': len(scoped_links), 'match_meta': len(scoped_meta),
        'match_rosters': len(scoped_rosters), 'change_log': len(logs),
    }
    for name in table_names:
        cols = columns(name)
        if name == 'profiles.json':
            cols = ['id', 'name', 'position', 'camp_user_id']
        elif name == 'settings':
            cols = ['id', 'teamName', 'roster']
        tables.append({
            'name': name, 'label': TABLE_LABELS.get(name, name),
            'rows': len(rows_by_table.get(name, [])),
            'scopedRows': scoped_counts.get(name, 0),
            'cols': cols[:14],
            'key': cols[0] if cols else '',
        })
    connection.close()

    level_count = {'error': 0, 'warn': 0, 'info': 0}
    for item in issues:
        level_count[item['level']] = level_count.get(item['level'], 0) + 1
    issues.sort(key=lambda x: {'error': 0, 'warn': 1, 'info': 2}.get(x['level'], 3))

    return {
        'ok': True,
        'generatedAt': datetime.fromtimestamp(now, timezone.utc).astimezone().isoformat(timespec='seconds'),
        'competitionId': cid,
        'competitions': [{'id': str(c.get('id')), 'name': str(c.get('name') or '未命名赛事'),
                          'status': str(c.get('status') or '')} for c in competitions],
        'competition': ({
            'id': cid, 'name': str(comp.get('name') or '未命名赛事'),
            'status': str(comp.get('status') or ''),
            'date': str(comp.get('date') or ''), 'endDate': str(comp.get('end_date') or ''),
            'declaredTeams': len(declared_teams), 'declaredPlayers': len(declared_players),
            'declaredMatches': len(declared_matches),
            'scopedMatches': len(scoped_matches), 'scopedSeries': len(scoped_series),
        } if comp else None),
        'tables': tables,
        'pools': pools,
        'edges': edges,
        'relationships': relationships,
        'entityLinks': entity_links,
        'issues': issues,
        'summary': {
            'tableCount': len(tables),
            'rowTotal': sum(len(rows_by_table.get(n, [])) for n in table_names),
            'scopedRows': sum(scoped_counts.values()),
            'errors': level_count.get('error', 0),
            'warnings': level_count.get('warn', 0),
            'infos': level_count.get('info', 0),
            'healthy': level_count.get('error', 0) == 0 and level_count.get('warn', 0) == 0,
        },
    }
