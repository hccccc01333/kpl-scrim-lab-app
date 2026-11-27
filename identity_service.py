"""身份唯一的写入口：游戏账号 → 选手 → 战队。

为什么要单独一个模块：这块以前散在五处——营地白名单写 `camp_config.json`、
选手认领写 `settings.aliases`（昵称字符串）、建档写 `settings.roster` + `players`、
对手归属写 `team_clusters` 覆盖层、战队命名同时写 `teams` 和覆盖层。
同一个人在不同页面能叫不同名字，删了也不会一起删。

现在只有这一份逻辑：

* **写** 只走这里，落到 `player_accounts`（账号 → 选手）+ `players`（选手 → 战队）+ `teams`。
* **读** 只认这三张表；`settings.aliases` / `team_clusters` 覆盖层只作历史兜底读取，不再新增写入。
* **命名** = 建/找战队 → 建/找选手 → 绑定账号，三步在事务里完成，任一步失败整体回滚。
* **删除** = 选手连同他的账号映射一起删，那个游戏账号回到「待命名」；历史对局文件不改。
* 不做转会、不做离队状态：人走了就删，回来了再命名一次。

对外函数全部返回可 JSON 化的小字典，接口层不做业务判断。
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing

from workspace_store import Workspace, is_placeholder_player

POSITIONS = ('对抗路', '打野', '中路', '发育路', '游走')
PLATFORM = 'camp'
PLACEHOLDER_TEAM = re.compile(r'^待命名')


def _text(value, limit=40):
    return str(value or '').strip()[:limit]


def _check_position(position):
    position = _text(position, 10)
    if position and position not in POSITIONS:
        raise ValueError('位置只能是：' + ' / '.join(POSITIONS))
    return position


def _check_positions(positions):
    """位置可多选：去重保序，第一个就是主位置；空值忽略。"""
    if positions is None:
        return None
    if isinstance(positions, str):
        positions = [positions]
    slots = []
    for item in positions or []:
        value = _check_position(item)
        if value and value not in slots:
            slots.append(value)
    return slots


def _fetch_player(ws, player_id):
    with closing(ws.connect()) as connection:
        row = connection.execute(
            'SELECT id, name, team_id, position FROM players WHERE id=?', (player_id,)).fetchone()
    return dict(row) if row else None


def _fetch_team(ws, team_id):
    with closing(ws.connect()) as connection:
        row = connection.execute(
            "SELECT id, name, aliases FROM teams WHERE id=? AND status='active'", (team_id,)).fetchone()
    return dict(row) if row else None


def resolve_team(ws, *, team_id=None, team_name=None, coach=None):
    """命名时落到哪支战队：优先显式 id，其次按名字找/建；两者都没有就不许命名。

    建档页「写个新队名顺手建队」和对手归属「就用当前这支」都走这里，
    避免一处建队、另一处又建一支同名的。
    """
    team_id = _text(team_id, 60)
    team_name = _text(team_name)
    if team_id:
        row = _fetch_team(ws, team_id)
        if row is None:
            raise ValueError('战队不存在或已归档，请刷新后重选')
        if team_name and team_name != _text(row['name']):
            ws.upsert_team(team_id, name=team_name, coach=coach, source='manual')
            return {'id': team_id, 'name': team_name}
        return {'id': team_id, 'name': _text(row['name'])}
    if not team_name:
        raise ValueError('请选择所属战队，或填写一个新的战队名')
    if PLACEHOLDER_TEAM.match(team_name):
        raise ValueError('「待命名战队」不是真队名，请填写真实战队名称')
    return {'id': ws.ensure_team_named(team_name, coach=coach), 'name': team_name}


def _drop_team_alias(db_path, team_id, old_name):
    """改名后不再保留旧名：旧名只会越攒越多，制造重名和串线。"""
    ws = Workspace(db_path)
    row = _fetch_team(ws, team_id)
    if row is None:
        return
    # _fetch_team 只 SELECT id,name；直接 row['aliases'] 会 KeyError，
    # 让整次改名事务失败——表现就是「改了名但别处还是旧名」。
    try:
        aliases = json.loads(row.get('aliases') or '[]')
    except (TypeError, ValueError, KeyError):
        aliases = []
    kept = [a for a in aliases if str(a) != str(old_name)]
    if kept != aliases:
        ws.upsert_team(team_id, name=row['name'], aliases=kept, source='manual', actor='coach')


def _sync_team_name_refs(db_path, old_name, new_name):
    """改名 = 全局换名：文本字段直接更新，不再靠旧名别名兜底。"""
    old_name, new_name = str(old_name or ''), str(new_name or '')
    if not old_name or old_name == new_name:
        return
    connection = sqlite3.connect(db_path)
    try:
        connection.execute('UPDATE training_series SET opponent=? WHERE opponent=?',
                           (new_name, old_name))
        # 赛训计划的对手也是自由文本队名，以前漏掉，改完名计划里仍是旧队。
        try:
            connection.execute('UPDATE scrim_plans SET opponent=? WHERE opponent=?',
                               (new_name, old_name))
        except sqlite3.Error:
            pass
        # 老数据里对手名也直接写在 matches.body（不是 match_meta 覆盖层）。
        # 只同步覆盖层时，删掉旧名别名后这些对局就永远停在旧队名。
        for table, key_col in (('matches', 'id'), ('match_meta', 'match_key')):
            try:
                rows = connection.execute(
                    f'SELECT {key_col}, body FROM {table}').fetchall()
            except sqlite3.Error:
                continue
            for key, body in rows:
                try:
                    doc = json.loads(body)
                except (TypeError, ValueError):
                    continue
                changed = False
                for field in ('opponent', 'opponentTeam', 'opponentName', 'team', 'teamName'):
                    if doc.get(field) == old_name:
                        doc[field] = new_name
                        changed = True
                if changed:
                    connection.execute(
                        f'UPDATE {table} SET body=? WHERE {key_col}=?',
                        (json.dumps(doc, ensure_ascii=False), key))
        # 采集通道正文里的对手名藏在 body.match 下；列表接口会按权威名覆盖，
        # 但单条详情/标题直接读原始正文，漏掉它改名后详情仍是旧名。
        try:
            channel_rows = connection.execute('SELECT id, body FROM channels').fetchall()
        except sqlite3.Error:
            channel_rows = []
        for key, body in channel_rows:
            try:
                doc = json.loads(body)
            except (TypeError, ValueError):
                continue
            match = doc.get('match') if isinstance(doc, dict) else None
            if not isinstance(match, dict):
                continue
            changed = False
            for field in ('opponent', 'opponentTeam', 'opponentName', 'teamName'):
                if match.get(field) == old_name:
                    match[field] = new_name
                    changed = True
            if changed:
                connection.execute('UPDATE channels SET body=? WHERE id=?',
                                   (json.dumps(doc, ensure_ascii=False), key))
        connection.commit()
    finally:
        connection.close()


def sync_own_team(db_path, *, name, coach=None, actor='coach'):
    """本队资料里的队名 → teams 主数据。

    产品约定：本队页填完队名，战队池里就要出现这支战队。稳定 ID 存在
    workspace_meta.own_team_id，改名时保留旧名作别名，历史引用仍能认出来。
    """
    name = _text(name, 50)
    if not name:
        raise ValueError('请填写战队名称')
    ws = Workspace(db_path).ensure_schema()
    connection = ws.connect()
    try:
        row = connection.execute(
            "SELECT value FROM workspace_meta WHERE key='own_team_id'").fetchone()
        tid = str(row['value']) if row else ''
        current = connection.execute(
            'SELECT id, name, aliases FROM teams WHERE id=?', (tid,)).fetchone() if tid else None
        if current is None:
            current = connection.execute(
                'SELECT id, name, aliases FROM teams WHERE name=? ORDER BY id LIMIT 1',
                (name,)).fetchone()
    finally:
        connection.close()
    aliases = []
    if current is not None:
        tid = str(current['id'])
        try:
            aliases = json.loads(current['aliases'] or '[]')
        except (TypeError, ValueError):
            aliases = []
        old_name = str(current['name'] or '')
        aliases = [a for a in aliases if str(a) != old_name]
        ws.upsert_team(tid, name=name, aliases=aliases, source='manual', actor=actor)
        _sync_team_name_refs(db_path, old_name, name)
    else:
        tid = ws.upsert_team(None, name=name, source='manual', actor=actor)
    connection = ws.connect()
    try:
        connection.execute(
            "INSERT INTO workspace_meta(key, value, updated_at) VALUES('own_team_id', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (tid, time.time()))
        connection.commit()
    finally:
        connection.close()
    return {'id': tid, 'name': name}


def save_player(db_path, *, player_id=None, name, position=None, positions=None, team_id=None,
                team_name=None, camp_user_id=None, role='main', aliases=None, actor='coach'):
    """新增或编辑一名选手（不涉及游戏账号时用；建档页「添加选手」走这里）。"""
    name = _text(name)
    if not name:
        raise ValueError('请填写选手名称')
    if is_placeholder_player(name):
        raise ValueError('「待命名选手」不是真名，请填写选手 ID 或常用名')
    slots = _check_positions(positions)
    position = (slots[0] if slots else _check_position(position))
    ws = Workspace(db_path).ensure_schema()
    existing = _fetch_player(ws, _text(player_id, 60)) if player_id else None
    if existing is not None:
        if team_id or team_name:
            target = resolve_team(ws, team_id=team_id, team_name=team_name)
        else:
            row = _fetch_team(ws, existing['team_id'])
            target = {'id': existing['team_id'], 'name': _text(row['name']) if row else ''}
        ws.upsert_player(existing['id'], team_id=target['id'], name=name,
                         position=position or existing['position'], positions=slots,
                         camp_user_id=camp_user_id,
                         aliases=aliases, role=role or 'main', actor=actor)
        return {'ok': True, 'playerId': existing['id'], 'name': name, 'teamId': target['id'],
                'teamName': target['name'], 'created': False}
    target = resolve_team(ws, team_id=team_id, team_name=team_name)
    found = ws.find_player(name, team_id=target['id'])
    if found is not None:
        # 同队同名就是同一个人：只补位置，不重复建。
        ws.upsert_player(found['id'], team_id=target['id'], name=name,
                         position=position or found['position'], positions=slots,
                         camp_user_id=camp_user_id,
                         aliases=aliases, role=role or 'main', actor=actor)
        return {'ok': True, 'playerId': found['id'], 'name': name, 'teamId': target['id'],
                'teamName': target['name'], 'created': False}
    new_id = ws.upsert_player(None, team_id=target['id'], name=name, position=position,
                              positions=slots, camp_user_id=camp_user_id, aliases=aliases,
                              role=role or 'main',
                              actor=actor)
    return {'ok': True, 'playerId': new_id, 'name': name, 'teamId': target['id'],
            'teamName': target['name'], 'created': True}


def name_account(db_path, *, account_id=None, nickname='', player_id=None, name=None, position=None,
                 positions=None, team_id=None, team_name=None, coach=None, default_team_id=None,
                 actor='coach'):
    """给一个游戏账号命名 / 改名 / 归队——所有页面的「命名」都调这一个。

    - 账号已经绑过选手：就地改这名选手的名字、位置、战队（同一选手的其它账号一起生效）。
    - 显式传了 player_id：把账号改绑到这名选手。
    - 都没传：按「选手名 + 战队」找已有选手，找不到才新建。
    - `default_team_id` 是「本队侧账号不填战队时的默认值」，由调用方决定（本队档案）。
    """
    account_id = _text(account_id, 40)
    nickname = _text(nickname, 60)
    name = _text(name)
    slots = _check_positions(positions)
    position = (slots[0] if slots else _check_position(position))
    ws = Workspace(db_path).ensure_schema()

    existing_account = None
    if account_id:
        rows = ws.list_accounts(account_id=account_id)
        existing_account = rows[0] if rows else None

    explicit_player = _fetch_player(ws, _text(player_id, 60)) if player_id else None
    if player_id and explicit_player is None:
        raise ValueError('选择的本队选手不存在，请刷新后重选')

    if explicit_player is not None:
        current = explicit_player
    elif existing_account is not None:
        current = _fetch_player(ws, existing_account['player_id'])
        if current is None:
            raise ValueError('这个游戏账号原先绑的选手已被删除，请重新命名')
    else:
        current = None

    created = False
    if current is not None:
        if not name:
            name = _text(current['name'])
        target = resolve_team(ws, team_id=team_id, team_name=team_name, coach=coach) \
            if (team_id or team_name) else None
        ws.upsert_player(current['id'], team_id=(target['id'] if target else current['team_id']),
                         name=name, position=position or current['position'], positions=slots,
                         actor=actor)
        player_id = current['id']
        team_id_final = target['id'] if target else current['team_id']
    else:
        if not name:
            raise ValueError('请填写选手名称（游戏 ID 不能直接当选手 ID）')
        if not team_id and not team_name and default_team_id:
            team_id = default_team_id
        target = resolve_team(ws, team_id=team_id, team_name=team_name, coach=coach)
        found = ws.find_player(name, team_id=target['id'])
        if found is not None:
            player_id = found['id']
            ws.upsert_player(player_id, team_id=target['id'], name=name,
                             position=position or found['position'], positions=slots, actor=actor)
        else:
            player_id = ws.upsert_player(None, team_id=target['id'], name=name, position=position,
                                         positions=slots, actor=actor)
            created = True
        team_id_final = target['id']

    if account_id:
        ws.map_account(account_id, player_id=player_id, nickname=nickname, actor=actor)
        # 昵称也并进选手别名，历史按昵称匹配的旧路径仍然认得这是谁。
        if nickname and nickname != name:
            ws.alias_player(player_id, nickname)
    return {'ok': True, 'accountId': account_id, 'playerId': player_id, 'name': name,
            'teamId': team_id_final, 'rebound': existing_account is not None, 'created': created}


def unmap_account(db_path, account_id, *, actor='coach'):
    """把一个游戏账号从选手身上摘下来（认错人 / 换号），选手其它账号不动。"""
    account_id = _text(account_id, 40)
    if not account_id:
        raise ValueError('缺少游戏账号 ID')
    return Workspace(db_path).ensure_schema().unmap_account(account_id, actor=actor)


def delete_player(db_path, player_id, *, actor='coach'):
    """删除选手 = 选手 + 他的全部游戏账号映射；这些游戏账号回到「待命名」。"""
    player_id = _text(player_id, 60)
    if not player_id:
        raise ValueError('缺少选手 ID')
    return Workspace(db_path).ensure_schema().delete_player(player_id, actor=actor)


def rename_team(db_path, team_id, *, name=None, coach=None, actor='coach'):
    """战队命名的唯一入口：`teams` 是权威，兼容覆盖层只做镜像。"""
    import team_clusters
    team_id = _text(team_id, 60)
    if not team_id:
        raise ValueError('缺少战队 id')
    name = _text(name) if name is not None else None
    if name == '':
        raise ValueError('战队名不能为空')
    coach = _text(coach) if coach is not None else None
    if name:
        ws = Workspace(db_path).ensure_schema()
        if PLACEHOLDER_TEAM.match(name) and not _allow_placeholder_unchanged(ws, team_id, name):
            raise ValueError('「待命名战队」不是真队名，请填写真实战队名称')
        with closing(ws.connect()) as connection:
            clash = connection.execute(
                "SELECT name FROM teams WHERE name=? AND id<>? AND status='active'",
                (name, team_id)).fetchone()
        if clash is not None:
            raise ValueError(f'队名已存在：{name}，请改别的名字或先合并战队')
    previous_name = ''
    if name:
        row = _fetch_team(Workspace(db_path), team_id)
        previous_name = str(row['name'] or '') if row else ''
    team_clusters.rename_team(db_path, team_id, name, coach)
    if name and previous_name and previous_name != name:
        _drop_team_alias(db_path, team_id, previous_name)
        _sync_team_name_refs(db_path, previous_name, name)
    return {'ok': True, 'id': team_id, 'name': name, 'coach': coach}


def _allow_placeholder_unchanged(ws, team_id, name):
    """占位名不能当真实队名用，但「原样保存」不算改名（比如只改教练）。"""
    if not team_id or not name or not PLACEHOLDER_TEAM.match(name):
        return bool(name)
    row = _fetch_team(ws, team_id)
    return bool(row and _text(row['name']) == name)


def save_team(db_path, *, team_id=None, name, short_name=None, coach=None, status='active',
              aliases=None, league=None, first_seen=None, actor='coach'):
    """新建 / 编辑战队主数据；也走同一份 teams，覆盖层同步镜像。"""
    import team_clusters
    name = _text(name)
    if not name:
        raise ValueError('请填写战队名称')
    ws = Workspace(db_path).ensure_schema()
    team_id = _text(team_id, 60) or None
    if PLACEHOLDER_TEAM.match(name) and not _allow_placeholder_unchanged(ws, team_id, name):
        raise ValueError('「待命名战队」不是真队名，请填写真实战队名称')
    previous_name, previous_aliases = '', []
    with closing(ws.connect()) as connection:
        if team_id is None:
            same = connection.execute(
                "SELECT id FROM teams WHERE name=? AND status='active' ORDER BY id LIMIT 1",
                (name,)).fetchone()
            if same is not None:
                raise ValueError(f'战队已存在：{name}')
        else:
            clash = connection.execute(
                "SELECT name FROM teams WHERE name=? AND id<>? AND status='active'",
                (name, team_id)).fetchone()
            if clash is not None:
                raise ValueError(f'队名已存在：{name}，请改别的名字或先合并战队')
            old = connection.execute('SELECT name, aliases FROM teams WHERE id=?',
                                     (team_id,)).fetchone()
            if old is not None:
                previous_name = _text(old['name'])
                try:
                    previous_aliases = json.loads(old['aliases'] or '[]')
                except (TypeError, ValueError):
                    previous_aliases = []
    # 改名不再留旧名：旧名只会越攒越多，制造重名；引用处直接换成新名。
    merged_aliases = [item for item in (aliases if isinstance(aliases, list) else previous_aliases)
                      if str(item) != str(previous_name)]
    team_id = ws.upsert_team(team_id, name=name, short_name=short_name, aliases=merged_aliases,
                             league=league, coach=coach, status=status or 'active',
                             first_seen=first_seen, source='manual', actor=actor)
    if status != 'archived':
        team_clusters.save_override(db_path, team_id, {'name': name, 'coach': coach})
        _sync_team_name_refs(db_path, previous_name, name)
    return {'ok': True, 'id': team_id, 'name': name}
