"""工作区数据模型：按 README.md 第 4 节建表。

设计约束（与规格一致）：
- 主键用稳定 ID，不用名称；改名/合并只写覆盖层，历史不动。
- 缺失字段存 NULL，不存 0；派生指标一律可复算。
- 每次人工修改写 change_log，可批量撤销。
- synthetic=1 的验证数据默认不进生产统计。

用法：
    from workspace_store import Workspace
    ws = Workspace(db_path)
    ws.ensure_schema()
    ws.upsert_team(id='team-x', name='青岚', coach='张教练')
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  short_name TEXT,
  aliases TEXT NOT NULL DEFAULT '[]',
  league TEXT,
  coach TEXT,
  analyst TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  first_seen TEXT,
  parent_team_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name);
CREATE INDEX IF NOT EXISTS idx_teams_status ON teams(status);

CREATE TABLE IF NOT EXISTS team_roster_versions (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL,
  name TEXT,
  player_ids TEXT NOT NULL DEFAULT '[]',
  start_date TEXT,
  end_date TEXT,
  is_current INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_roster_versions_team ON team_roster_versions(team_id);

CREATE TABLE IF NOT EXISTS team_relations (
  from_team_id TEXT NOT NULL,
  to_team_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  note TEXT,
  PRIMARY KEY(from_team_id, to_team_id, relation)
);

CREATE TABLE IF NOT EXISTS players (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL,
  name TEXT NOT NULL,
  match_name TEXT,
  position TEXT,
  positions TEXT NOT NULL DEFAULT '[]',
  aliases TEXT NOT NULL DEFAULT '[]',
  camp_user_id TEXT,
  role TEXT NOT NULL DEFAULT 'main',
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);

CREATE TABLE IF NOT EXISTS player_accounts (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'camp',
  account_id TEXT NOT NULL,
  nickname TEXT,
  camp_user_id TEXT,
  first_seen TEXT,
  last_seen TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0,
  shared INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at REAL NOT NULL,
  UNIQUE(platform, account_id)
);
CREATE INDEX IF NOT EXISTS idx_accounts_player ON player_accounts(player_id);

CREATE TABLE IF NOT EXISTS player_team_history (
  player_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  source TEXT,
  PRIMARY KEY(player_id, team_id, start_date)
);

CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  start_time TEXT,
  opponent_team_id TEXT,
  session TEXT,
  series_id TEXT,
  format TEXT,
  rules TEXT,
  version TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  notes TEXT,
  goals TEXT NOT NULL DEFAULT '[]',
  review TEXT,
  review_status TEXT NOT NULL DEFAULT '',
  attendance TEXT NOT NULL DEFAULT '[]',
  competition_id TEXT,
  created_by TEXT,
  created_at REAL NOT NULL,
  updated_at REAL,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date);
CREATE INDEX IF NOT EXISTS idx_schedules_competition ON schedules(competition_id);

/* 比赛（赛事）是赛训的中心：训练计划、训练课、对局都挂在比赛下。
   与 schedules 分开建表，避免把「一场比赛」和「一次训练」混成同一种记录。 */
CREATE TABLE IF NOT EXISTS competitions (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  date TEXT NOT NULL,
  opponent_team_id TEXT,
  stage TEXT,
  format TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  owner TEXT,
  notes TEXT,
  created_at REAL NOT NULL,
  updated_at REAL,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_competitions_date ON competitions(date);

CREATE TABLE IF NOT EXISTS session_match_links (
  schedule_id TEXT NOT NULL,
  match_key TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(schedule_id, match_key)
);
CREATE INDEX IF NOT EXISTS idx_session_links_schedule ON session_match_links(schedule_id);

CREATE TABLE IF NOT EXISTS team_aliases (
  old_id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
  match_key TEXT PRIMARY KEY,
  date TEXT,
  session TEXT,
  series_id TEXT,
  game_no INTEGER,
  mode TEXT,
  rules TEXT,
  version TEXT,
  own_team_id TEXT,
  enemy_team_id TEXT,
  enemy_cluster_id TEXT,
  schedule_id TEXT,
  own_side TEXT,
  winner TEXT,
  score TEXT,
  duration INTEGER,
  reviewer TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  tags TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  source TEXT NOT NULL DEFAULT 'camp',
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_matches_enemy ON matches(enemy_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_session ON matches(session);

CREATE TABLE IF NOT EXISTS match_records (
  match_key TEXT PRIMARY KEY,
  date TEXT,
  session TEXT,
  series_id TEXT,
  game_no INTEGER,
  mode TEXT,
  rules TEXT,
  version TEXT,
  own_team_id TEXT,
  enemy_team_id TEXT,
  enemy_cluster_id TEXT,
  schedule_id TEXT,
  own_side TEXT,
  winner TEXT,
  score TEXT,
  duration INTEGER,
  reviewer TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  tags TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  source TEXT NOT NULL DEFAULT 'camp',
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_records_date ON match_records(date);
CREATE INDEX IF NOT EXISTS idx_records_enemy ON match_records(enemy_team_id);
CREATE INDEX IF NOT EXISTS idx_records_session ON match_records(session);

CREATE TABLE IF NOT EXISTS match_rosters (
  match_key TEXT NOT NULL,
  team_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  account_id TEXT,
  side TEXT NOT NULL,
  slot INTEGER NOT NULL,
  hero TEXT,
  is_sub INTEGER NOT NULL DEFAULT 0,
  is_trial INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(match_key, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS bp (
  match_key TEXT PRIMARY KEY,
  bans TEXT NOT NULL DEFAULT '{}',
  picks TEXT NOT NULL DEFAULT '{}',
  pick_order TEXT NOT NULL DEFAULT '[]',
  first_pick TEXT,
  bp_coach TEXT,
  comp_tags TEXT NOT NULL DEFAULT '[]',
  notes TEXT
);

CREATE TABLE IF NOT EXISTS training (
  session_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  intervention TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT,
  player_ids TEXT NOT NULL DEFAULT '[]',
  metric TEXT NOT NULL,
  target REAL,
  review TEXT,
  revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS provenance (
  match_key TEXT NOT NULL,
  field TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium',
  synthetic INTEGER NOT NULL DEFAULT 0,
  confirmed_by TEXT,
  updated_at REAL NOT NULL,
  PRIMARY KEY(match_key, field)
);

CREATE TABLE IF NOT EXISTS prefill_fields (
  match_key TEXT NOT NULL,
  field TEXT NOT NULL,
  value TEXT,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  generated_at REAL NOT NULL,
  synthetic INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(match_key, field)
);

CREATE TABLE IF NOT EXISTS change_log (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  source TEXT NOT NULL,
  actor TEXT,
  batch_id TEXT,
  reason TEXT,
  created_at REAL NOT NULL,
  undone_at REAL,
  undo_of TEXT,
  revision INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_entity ON change_log(entity_type, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_change_batch ON change_log(batch_id);

CREATE TABLE IF NOT EXISTS workspace_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
"""


def _json(value, default):
    if value is None:
        return json.dumps(default, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _loads(value, default=None):
    """把库里存的 JSON 文本读回 Python 值；坏数据退回 default，不抛。"""
    try:
        return json.loads(value) if value else ([] if default is None else default)
    except (TypeError, ValueError):
        return [] if default is None else default


PLAYER_PLACEHOLDER_PREFIX = '待命名选手 #'
LEGACY_PLAYER_PLACEHOLDERS = {'新选手', '未命名', '未命名选手', '选手'}


def is_placeholder_player(name) -> bool:
    """选手占位名与战队占位名（待命名战队 #N）分开识别。"""
    text = str(name or '').strip()
    return text in LEGACY_PLAYER_PLACEHOLDERS or text.startswith(PLAYER_PLACEHOLDER_PREFIX)


class Workspace:
    def __init__(self, db_path):
        self.db_path = Path(db_path)

    # ---------------------------------------------------------------- 基础设施
    def connect(self):
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def ensure_schema(self):
        """逐条执行建表语句：旧库里已有同名但结构不同的表（如 matches 存 JSON body）时不中断，
        只跳过该条并记入 self.schema_warnings。"""
        connection = self.connect()
        self.schema_warnings = []
        try:
            for statement in SCHEMA.split(';'):
                sql = statement.strip()
                if not sql:
                    continue
                try:
                    connection.execute(sql)
                except sqlite3.Error as error:
                    self.schema_warnings.append(f'{error}: {sql.splitlines()[0][:60]}')
            # 旧库的 schedules 没有训练课复盘字段：按需补列，不重建表。
            try:
                existing = {row[1] for row in connection.execute('PRAGMA table_info(schedules)')}
                for column, ddl in {
                    'goals': "TEXT NOT NULL DEFAULT '[]'",
                    'review': 'TEXT',
                    'review_status': "TEXT NOT NULL DEFAULT ''",
                    'attendance': "TEXT NOT NULL DEFAULT '[]'",
                    'competition_id': 'TEXT',
                    'updated_at': 'REAL',
                }.items():
                    if column not in existing:
                        connection.execute(f'ALTER TABLE schedules ADD COLUMN {column} {ddl}')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'schedules 迁移: {error}')
            # 选手位置多选：position 仍存主位置（下游按单值用），positions 存全部位置。
            try:
                existing = {row[1] for row in connection.execute('PRAGMA table_info(players)')}
                if 'positions' not in existing:
                    connection.execute("ALTER TABLE players ADD COLUMN positions TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.Error as error:
                self.schema_warnings.append(f'players 迁移: {error}')
            connection.commit()
        finally:
            connection.close()
        return self

    def _log(self, connection, entity_type, entity_id, field, old, new, source, actor=None,
             batch_id=None, reason=None):
        connection.execute(
            'INSERT INTO change_log(id, entity_type, entity_id, field, old_value, new_value, '
            'source, actor, batch_id, reason, created_at, revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)',
            (uuid.uuid4().hex[:16], entity_type, entity_id, field,
             None if old is None else str(old), None if new is None else str(new),
             source, actor, batch_id, reason, time.time()))

    # ---------------------------------------------------------------- 战队
    def upsert_team(self, team_id=None, *, name, short_name=None, aliases=None, league=None,
                    coach=None, analyst=None, notes=None, status=None, first_seen=None,
                    parent_team_id=None, source='manual', actor=None):
        """写入/合并战队。status 传 None 表示「本次不改」，避免改名把归档队重新激活。"""
        if not name or not str(name).strip():
            raise ValueError('战队名不能为空')
        team_id = team_id or 'team-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
            if row is None:
                connection.execute(
                    'INSERT INTO teams(id, name, short_name, aliases, league, coach, analyst, notes, '
                    'status, first_seen, parent_team_id) '
                    'VALUES(?,?,?,?,?,?,?,?,COALESCE(?,\'active\'),?,?)',
                    (team_id, name.strip(), short_name, _json(aliases, []), league, coach, analyst,
                     notes, status, first_seen, parent_team_id))
            else:
                patch = {'name': name.strip(), 'short_name': short_name, 'league': league,
                         'coach': coach, 'analyst': analyst, 'notes': notes, 'status': status,
                         'first_seen': first_seen, 'parent_team_id': parent_team_id}
                for field, value in patch.items():
                    if value is not None and str(row[field] or '') != str(value):
                        self._log(connection, 'team', team_id, field, row[field], value, source, actor)
                connection.execute(
                    'UPDATE teams SET name=?, short_name=COALESCE(?,short_name), '
                    'aliases=COALESCE(?,aliases), league=COALESCE(?,league), coach=COALESCE(?,coach), '
                    'analyst=COALESCE(?,analyst), notes=COALESCE(?,notes), status=COALESCE(?,status), '
                    'first_seen=COALESCE(?,first_seen), parent_team_id=COALESCE(?,parent_team_id), '
                    'revision=revision+1 WHERE id=?',
                    (name.strip(), short_name, _json(aliases, None) if aliases is not None else None,
                     league, coach, analyst, notes, status, first_seen, parent_team_id, team_id))
            connection.commit()
        finally:
            connection.close()
        return team_id

    def list_teams(self, *, status='active', include_archived=False):
        connection = self.connect()
        try:
            query = 'SELECT * FROM teams'
            params = []
            if not include_archived:
                query += ' WHERE status=?'
                params.append(status)
            rows = connection.execute(query + ' ORDER BY name', params).fetchall()
        finally:
            connection.close()
        return [self._team_row(row) for row in rows]

    def search_teams(self, q='', limit=20):
        connection = self.connect()
        try:
            pattern = f'%{q.strip()}%'
            rows = connection.execute(
                "SELECT * FROM teams WHERE name LIKE ? OR aliases LIKE ? OR IFNULL(coach,'') LIKE ? "
                'ORDER BY name LIMIT ?', (pattern, pattern, pattern, limit)).fetchall()
        finally:
            connection.close()
        return [self._team_row(row) for row in rows]

    @staticmethod
    def _team_row(row):
        item = {key: row[key] for key in row.keys()}
        item['aliases'] = json.loads(item.get('aliases') or '[]')
        return item

    def merge_teams(self, source_id, target_id, *, actor=None):
        """合并战队：选手改挂目标队，源队归档；历史记录保留。"""
        if source_id == target_id:
            raise ValueError('不能合并到自己')
        connection = self.connect()
        try:
            connection.execute('UPDATE players SET team_id=? WHERE team_id=?', (target_id, source_id))
            connection.execute(
                "UPDATE teams SET status='archived', revision=revision+1 WHERE id=?", (source_id,))
            self._log(connection, 'team', source_id, 'mergedInto', None, target_id, 'merge', actor)
            connection.commit()
        finally:
            connection.close()
        return target_id

    # ---------------------------------------------------------------- 选手
    def upsert_player(self, player_id=None, *, team_id, name, position=None, positions=None,
                      aliases=None, camp_user_id=None, role='main', match_name=None,
                      source='manual', actor=None):
        if not team_id:
            raise ValueError('选手必须归属战队')
        if not name or not str(name).strip():
            raise ValueError('选手名不能为空')
        # 位置可多选：第一个是主位置，写进 position（下游仍按单值用），全量进 positions。
        slots = [str(x).strip() for x in (positions or []) if str(x).strip()]
        if slots:
            position = slots[0]
        player_id = player_id or 'player-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            if aliases is None:
                # 不传别名就保留原样：改名/改位置不该把换号合并的别名冲掉。
                row = connection.execute('SELECT aliases FROM players WHERE id=?',
                                         (player_id,)).fetchone()
                if row is not None:
                    aliases = json.loads(row['aliases'] or '[]')
            if positions is None:
                # 没传就沿用库里已有的；新选手退回「只有主位置」。
                row = connection.execute('SELECT positions FROM players WHERE id=?',
                                         (player_id,)).fetchone()
                if row is not None and (row['positions'] or '').strip() not in ('', '[]'):
                    try:
                        slots = json.loads(row['positions'])
                    except (TypeError, ValueError):
                        slots = [position] if position else []
                else:
                    slots = [position] if position else []
            connection.execute(
                'INSERT INTO players(id, team_id, name, match_name, position, positions, aliases, camp_user_id, role)'
                ' VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET team_id=excluded.team_id, '
                'name=excluded.name, match_name=COALESCE(excluded.match_name, players.match_name), '
                'position=COALESCE(excluded.position, players.position), positions=excluded.positions, '
                'aliases=excluded.aliases, '
                'camp_user_id=COALESCE(excluded.camp_user_id, players.camp_user_id), role=excluded.role, '
                'revision=players.revision+1',
                (player_id, team_id, name.strip(), match_name, position, _json(slots, []),
                 _json(aliases, []), camp_user_id, role))
            connection.commit()
        finally:
            connection.close()
        return player_id

    def list_players(self, team_id=None):
        connection = self.connect()
        try:
            if team_id:
                rows = connection.execute('SELECT * FROM players WHERE team_id=? ORDER BY name',
                                          (team_id,)).fetchall()
            else:
                rows = connection.execute('SELECT * FROM players ORDER BY team_id, name').fetchall()
        finally:
            connection.close()
        out = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            item['aliases'] = json.loads(item.get('aliases') or '[]')
            try:
                item['positions'] = json.loads(item.get('positions') or '[]')
            except (TypeError, ValueError):
                item['positions'] = []
            out.append(item)
        return out

    def migrate_roster(self, roster, *, own_team_name='', actor=None):
        """把旧 settings.roster 一次性迁入 players；保留旧 id，跳过明确重复项。"""
        if not isinstance(roster, list):
            raise ValueError('旧名单格式无效')
        if not roster:
            return {'found': 0, 'imported': 0, 'skipped': 0, 'teamsCreated': 0,
                    'warnings': [], 'renamed': {}, 'placeholders': 0}
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            teams = {row['name']: row['id'] for row in
                     connection.execute("SELECT id, name FROM teams WHERE status='active'")}
            teams_created = 0

            def ensure_team(name):
                nonlocal teams_created
                name = str(name or '').strip()
                if not name:
                    name = '未命名战队'
                existing = teams.get(name)
                if existing:
                    return existing
                team_id = 'team-' + uuid.uuid4().hex[:10]
                connection.execute('INSERT INTO teams(id, name) VALUES(?,?)', (team_id, name))
                teams[name] = team_id
                teams_created += 1
                return team_id

            own_id = 'team-own'
            own = connection.execute("SELECT id FROM teams WHERE id='team-own'").fetchone()
            if own is None:
                if own_team_name and own_team_name in teams:
                    own_id = teams[own_team_name]
                else:
                    connection.execute('INSERT INTO teams(id, name) VALUES(?,?)',
                                       (own_id, own_team_name or '我方战队'))
                    teams[own_team_name or '我方战队'] = own_id
                    teams_created += 1

            existing = connection.execute(
                'SELECT id, team_id, name, position, camp_user_id FROM players').fetchall()
            by_id = {row['id'] for row in existing}
            by_camp = {row['camp_user_id'] for row in existing if row['camp_user_id']}
            by_key = {(row['team_id'], row['name'], row['position'] or '') for row in existing}
            placeholder_count = 0
            for row in existing:
                name = str(row['name'] or '')
                if name.startswith(PLAYER_PLACEHOLDER_PREFIX):
                    try:
                        placeholder_count = max(placeholder_count,
                                                int(name[len(PLAYER_PLACEHOLDER_PREFIX):].strip()))
                    except ValueError:
                        pass

            imported, skipped, warnings, placeholders = 0, 0, [], 0
            renamed = {}
            positions = {'对抗路', '打野', '中路', '发育路', '游走'}
            for member in roster:
                if not isinstance(member, dict):
                    skipped += 1
                    continue
                if member.get('archived'):
                    skipped += 1
                    continue
                player_id = str(member.get('id') or '').strip()
                original_name = str(member.get('name') or member.get('label') or '').strip()
                if not player_id or not original_name:
                    skipped += 1
                    continue
                raw_team = str(member.get('team') or '').strip()
                team_id = own_id if not raw_team or raw_team == own_team_name else ensure_team(raw_team)
                position = str(member.get('position') or '').strip()
                if position not in positions:
                    position = None
                camp = str(member.get('campUserId') or '').strip()
                key = (team_id, original_name, position or '')
                if player_id in by_id or (camp and camp in by_camp) or key in by_key:
                    skipped += 1
                    continue
                placeholder = is_placeholder_player(original_name)
                display_name = original_name
                if placeholder:
                    placeholder_count += 1
                    display_name = f'{PLAYER_PLACEHOLDER_PREFIX}{placeholder_count}'
                    placeholders += 1
                    renamed[player_id] = display_name
                connection.execute(
                    'INSERT INTO players(id, team_id, name, position, camp_user_id, role) '
                    'VALUES(?,?,?,?,?,?)',
                    (player_id, team_id, display_name, position, camp or None, 'main'))
                self._log(connection, 'player', player_id, 'created', None, display_name,
                          'migrate-roster', actor)
                by_id.add(player_id)
                by_key.add(key)
                by_key.add((team_id, display_name, position or ''))
                if camp:
                    by_camp.add(camp)
                imported += 1
            if skipped:
                warnings.append(f'{skipped} 名旧成员因重复、已存在或缺少名称被跳过。')
            if placeholders:
                warnings.append(f'{placeholders} 名旧占位选手已改名为「{PLAYER_PLACEHOLDER_PREFIX}N」，'
                                '与战队占位名分开。')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {'found': len(roster), 'imported': imported, 'skipped': skipped,
                'teamsCreated': teams_created, 'warnings': warnings,
                'renamed': renamed, 'placeholders': placeholders}

    def alias_player(self, player_id, alias):
        """把一个昵称挂到选手名下（换号合并），返回是否新增。"""
        alias = str(alias or '').strip()
        if not alias:
            return False
        connection = self.connect()
        try:
            row = connection.execute('SELECT aliases FROM players WHERE id=?', (player_id,)).fetchone()
            if row is None:
                raise ValueError('选手不存在')
            aliases = json.loads(row['aliases'] or '[]')
            if alias in aliases:
                return False
            aliases.append(alias)
            connection.execute('UPDATE players SET aliases=?, revision=revision+1 WHERE id=?',
                               (_json(aliases, []), player_id))
            self._log(connection, 'player', player_id, 'aliases', row['aliases'], _json(aliases, []), 'manual')
            connection.commit()
        finally:
            connection.close()
        return True

    # ---------------------------------------------------------------- 游戏账号 ↔ 选手
    # 营地爬到的十人面板只有 playerId + 游戏昵称（roleName）；教练把它对上真实选手后，
    # 这条映射写进 player_accounts，之后同一账号再出现就直接认人，不用重复命名。
    ACCOUNT_PLATFORM = 'camp'

    def _account_rows(self, connection, *, account_id=None, player_id=None, team_id=None):
        query = ('SELECT a.id, a.player_id, a.platform, a.account_id, a.nickname, a.camp_user_id,'
                 ' a.first_seen, a.last_seen, a.is_primary, a.shared, a.source, a.confidence,'
                 ' p.name AS player_name, p.position AS player_position, p.positions AS player_positions,'
                 ' p.team_id AS team_id, t.name AS team_name'
                 ' FROM player_accounts a LEFT JOIN players p ON p.id = a.player_id'
                 ' LEFT JOIN teams t ON t.id = p.team_id')
        clauses, params = [], []
        if account_id:
            clauses.append('a.account_id = ?')
            params.append(str(account_id))
        if player_id:
            clauses.append('a.player_id = ?')
            params.append(str(player_id))
        if team_id:
            clauses.append('p.team_id = ?')
            params.append(str(team_id))
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        rows = connection.execute(query, params).fetchall()
        out = [{key: row[key] for key in row.keys()} for row in rows]
        out.sort(key=lambda item: (item.get('team_name') or '', item.get('player_name') or ''))
        return out

    def list_accounts(self, *, account_id=None, player_id=None, team_id=None):
        """游戏账号映射表：一条记录 = 一个营地账号（游戏 ID）挂在哪名选手、哪支战队。"""
        connection = self.connect()
        try:
            return self._account_rows(connection, account_id=account_id, player_id=player_id,
                                      team_id=team_id)
        finally:
            connection.close()

    def account_index(self, platform=ACCOUNT_PLATFORM):
        """账号 ID → {playerId, name, position, teamId, teamName, nickname}。

        读取侧（营地面板、对手归属）用它一次解析全部映射，避免逐条查库。
        """
        connection = self.connect()
        try:
            rows = self._account_rows(connection)
        finally:
            connection.close()
        index = {}
        for row in rows:
            if row.get('platform') != platform:
                continue
            index[str(row['account_id'])] = {
                'accountId': str(row['account_id']), 'nickname': row.get('nickname') or '',
                'playerId': row.get('player_id') or '', 'name': row.get('player_name') or '',
                'position': row.get('player_position') or '',
                'positions': _loads(row.get('player_positions') or '[]'), 'teamId': row.get('team_id') or '',
                'teamName': row.get('team_name') or '', 'source': row.get('source') or 'manual',
            }
        return index

    def map_account(self, account_id, *, player_id, nickname=None, platform=ACCOUNT_PLATFORM,
                    source='manual', confidence='high', camp_user_id=None, seen_at=None,
                    actor=None):
        """把一个营地账号挂到选手名下；换绑时旧账号关系被覆盖并留痕。

        同一账号只能属于一名选手（UNIQUE(platform, account_id)），重绑是显式操作，
        不会自动猜测；解绑走 :meth:`unmap_account`。
        """
        account_id = str(account_id or '').strip()
        player_id = str(player_id or '').strip()
        if not account_id:
            raise ValueError('缺少游戏账号 ID')
        if not player_id:
            raise ValueError('缺少选手 ID')
        stamp = str(seen_at or time.strftime('%Y-%m-%d'))
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            player = connection.execute(
                'SELECT id, name, team_id FROM players WHERE id=?', (player_id,)).fetchone()
            if player is None:
                raise ValueError('选手不存在')
            previous = connection.execute(
                'SELECT id, player_id, nickname FROM player_accounts WHERE platform=? AND account_id=?',
                (platform, account_id)).fetchone()
            if previous is None:
                primary = connection.execute(
                    'SELECT COUNT(*) FROM player_accounts WHERE player_id=? AND platform=? AND is_primary=1',
                    (player_id, platform)).fetchone()[0]
                connection.execute(
                    'INSERT INTO player_accounts(id, player_id, platform, account_id, nickname,'
                    ' camp_user_id, first_seen, last_seen, is_primary, shared, source, confidence,'
                    ' created_at) VALUES(?,?,?,?,?,?,?,?,?,0,?,?,?)',
                    (uuid.uuid4().hex[:16], player_id, platform, account_id,
                     str(nickname or '').strip() or None, camp_user_id or None,
                     stamp, stamp, 0 if primary else 1, source, confidence, time.time()))
                self._log(connection, 'player', player_id, 'account:' + account_id, None,
                          str(nickname or account_id), source, actor)
            else:
                connection.execute(
                    'UPDATE player_accounts SET player_id=?, nickname=COALESCE(?, nickname),'
                    ' camp_user_id=COALESCE(?, camp_user_id), last_seen=? WHERE id=?',
                    (player_id, str(nickname or '').strip() or None, camp_user_id or None,
                     stamp, previous['id']))
                if previous['player_id'] != player_id:
                    self._log(connection, 'player', player_id, 'account:' + account_id,
                              previous['player_id'], player_id, source, actor)
            connection.commit()
            return {'accountId': account_id, 'playerId': player_id,
                    'teamId': player['team_id'], 'name': player['name']}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def unmap_account(self, account_id, *, platform=ACCOUNT_PLATFORM, actor=None):
        """解除账号绑定（认错人 / 换号）。选手记录与历史对局都不动。"""
        account_id = str(account_id or '').strip()
        if not account_id:
            raise ValueError('缺少游戏账号 ID')
        connection = self.connect()
        try:
            row = connection.execute(
                'SELECT id, player_id FROM player_accounts WHERE platform=? AND account_id=?',
                (platform, account_id)).fetchone()
            if row is None:
                return {'accountId': account_id, 'removed': False}
            connection.execute('DELETE FROM player_accounts WHERE id=?', (row['id'],))
            self._log(connection, 'player', row['player_id'], 'account:' + account_id,
                      row['player_id'], None, 'manual', actor)
            connection.commit()
            return {'accountId': account_id, 'removed': True, 'playerId': row['player_id']}
        finally:
            connection.close()

    def delete_player(self, player_id, *, actor=None):
        """删除选手：连同他的游戏账号映射一起删掉，之后同名游戏 ID 回到「待命名」。

        历史对局是只读的原始营地文件，不会被改写；重命名/删人的影响只落在身份层。
        """
        player_id = str(player_id or '').strip()
        if not player_id:
            raise ValueError('缺少选手 ID')
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT name, team_id FROM players WHERE id=?', (player_id,)).fetchone()
            if row is None:
                raise ValueError('选手不存在')
            accounts = connection.execute(
                'SELECT account_id FROM player_accounts WHERE player_id=?', (player_id,)).fetchall()
            connection.execute('DELETE FROM player_accounts WHERE player_id=?', (player_id,))
            connection.execute('DELETE FROM players WHERE id=?', (player_id,))
            self._log(connection, 'player', player_id, 'deleted', row['name'], None, 'manual', actor)
            for account in accounts:
                self._log(connection, 'player', player_id, 'account:' + account['account_id'],
                          account['account_id'], None, 'manual', actor)
            connection.commit()
            return {'playerId': player_id, 'name': row['name'], 'accounts': len(accounts)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_player(self, name, *, team_id=None):
        """按选手名找一条记录（可限定战队）；用于命名时复用已有选手，不重复建。"""
        name = str(name or '').strip()
        if not name:
            return None
        connection = self.connect()
        try:
            if team_id:
                row = connection.execute(
                    'SELECT id, name, team_id, position FROM players'
                    ' WHERE name=? AND team_id=? ORDER BY id LIMIT 1',
                    (name, team_id)).fetchone()
            else:
                row = connection.execute(
                    'SELECT id, name, team_id, position FROM players WHERE name=? ORDER BY id LIMIT 1',
                    (name,)).fetchone()
            return {key: row[key] for key in row.keys()} if row else None
        finally:
            connection.close()

    def ensure_team_named(self, name, *, aliases=None, coach=None, actor=None):
        """按队名找到或新建一支战队，返回 team_id（命名选手时顺手落战队主数据）。"""
        name = str(name or '').strip()
        if not name:
            raise ValueError('请填写战队名称')
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT id FROM teams WHERE name=? AND status='active' ORDER BY id LIMIT 1",
                (name,)).fetchone()
            if row is not None:
                return row['id']
        finally:
            connection.close()
        return self.upsert_team(None, name=name, aliases=aliases, coach=coach, source='manual', actor=actor)

    # ---------------------------------------------------------------- 结构化对局
    def upsert_match(self, match_key, *, date=None, session=None, series_id=None, game_no=None,
                     mode=None, rules=None, version=None, own_team_id=None, enemy_team_id=None,
                     enemy_cluster_id=None, schedule_id=None, own_side=None, winner=None,
                     score=None, duration=None, reviewer=None, status=None, tags=None,
                     notes=None, source='camp'):
        """写入/合并一局记录。status/tags 传 None 表示「本次不改」。

        部分更新（例如营地只回填日期与胜负）不能把人工确认过的 status 重置回
        draft，也不能清空 tags，所以 ON CONFLICT 分支用 COALESCE 保留旧值。
        """
        if not match_key:
            raise ValueError('缺少 match_key')
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO match_records(match_key, date, session, series_id, game_no, mode, rules, '
                'version, own_team_id, enemy_team_id, enemy_cluster_id, schedule_id, own_side, winner, '
                'score, duration, reviewer, status, tags, notes, source) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,\'draft\'),COALESCE(?,\'[]\'),?,?) '
                'ON CONFLICT(match_key) DO UPDATE SET '
                'date=COALESCE(excluded.date, match_records.date), '
                'session=COALESCE(excluded.session, match_records.session), '
                'series_id=COALESCE(excluded.series_id, match_records.series_id), '
                'game_no=COALESCE(excluded.game_no, match_records.game_no), '
                'mode=COALESCE(excluded.mode, match_records.mode), '
                'rules=COALESCE(excluded.rules, match_records.rules), '
                'version=COALESCE(excluded.version, match_records.version), '
                'own_team_id=COALESCE(excluded.own_team_id, match_records.own_team_id), '
                'enemy_team_id=COALESCE(excluded.enemy_team_id, match_records.enemy_team_id), '
                'enemy_cluster_id=COALESCE(excluded.enemy_cluster_id, match_records.enemy_cluster_id), '
                'schedule_id=COALESCE(excluded.schedule_id, match_records.schedule_id), '
                'own_side=COALESCE(excluded.own_side, match_records.own_side), '
                'winner=COALESCE(excluded.winner, match_records.winner), '
                'score=COALESCE(excluded.score, match_records.score), '
                'duration=COALESCE(excluded.duration, match_records.duration), '
                'reviewer=COALESCE(excluded.reviewer, match_records.reviewer), '
                'status=COALESCE(?, match_records.status), '
                'tags=COALESCE(?, match_records.tags), '
                'notes=COALESCE(excluded.notes, match_records.notes), '
                'revision=match_records.revision+1',
                (match_key, date, session, series_id, game_no, mode, rules, version, own_team_id,
                 enemy_team_id, enemy_cluster_id, schedule_id, own_side, winner,
                 _json(score, None) if score is not None else None, duration, reviewer, status,
                 _json(tags, None) if tags is not None else None, notes, source,
                 status, _json(tags, None) if tags is not None else None))
            connection.commit()
        finally:
            connection.close()
        return match_key

    def upsert_rosters(self, match_key, rosters):
        """rosters: [{teamId, playerId, side, slot, hero, isSub, isTrial}]"""
        connection = self.connect()
        try:
            connection.execute('DELETE FROM match_rosters WHERE match_key=?', (match_key,))
            for row in rosters:
                if not row.get('teamId') or not row.get('playerId'):
                    continue
                connection.execute(
                    'INSERT OR REPLACE INTO match_rosters(match_key, team_id, player_id, account_id, '
                    'side, slot, hero, is_sub, is_trial) VALUES(?,?,?,?,?,?,?,?,?)',
                    (match_key, row['teamId'], row['playerId'], row.get('accountId'),
                     row.get('side') or 'blue', int(row.get('slot') or 0), row.get('hero'),
                     1 if row.get('isSub') else 0, 1 if row.get('isTrial') else 0))
            connection.commit()
        finally:
            connection.close()

    def upsert_bp(self, match_key, *, bans=None, picks=None, pick_order=None, first_pick=None,
                  bp_coach=None, comp_tags=None, notes=None):
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO bp(match_key, bans, picks, pick_order, first_pick, bp_coach, comp_tags, notes) '
                'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(match_key) DO UPDATE SET '
                'bans=excluded.bans, picks=excluded.picks, pick_order=excluded.pick_order, '
                'first_pick=COALESCE(excluded.first_pick, bp.first_pick), '
                'bp_coach=COALESCE(excluded.bp_coach, bp.bp_coach), '
                'comp_tags=excluded.comp_tags, notes=COALESCE(excluded.notes, bp.notes)',
                (match_key, _json(bans, {}), _json(picks, {}), _json(pick_order, []),
                 first_pick, bp_coach, _json(comp_tags, []), notes))
            connection.commit()
        finally:
            connection.close()

    def list_matches(self, limit=200):
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT * FROM match_records ORDER BY date DESC, match_key DESC LIMIT ?', (limit,)).fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    # ---------------------------------------------------------------- 约训
    def save_schedule(self, schedule_id=None, *, date, start_time=None, opponent_team_id=None,
                      session=None, format=None, rules=None, version=None, status=None,
                      notes=None, created_by=None, competition_id=None):
        """写入/合并约训。status 传 None 表示保留原状态，不重置回 planned。"""
        if not date:
            raise ValueError('约训必须有日期')
        schedule_id = schedule_id or 'sch-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO schedules(id, date, start_time, opponent_team_id, session, format, rules, '
                'version, status, notes, competition_id, created_by, created_at) '
                'VALUES(?,?,?,?,?,?,?,?,COALESCE(?,\'planned\'),?,?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET date=excluded.date, start_time=excluded.start_time, '
                'opponent_team_id=excluded.opponent_team_id, session=excluded.session, '
                'format=excluded.format, rules=excluded.rules, version=excluded.version, '
                'status=COALESCE(?,schedules.status), notes=excluded.notes, '
                'competition_id=excluded.competition_id, revision=schedules.revision+1',
                (schedule_id, date, start_time, opponent_team_id, session, format, rules, version,
                 status, notes, competition_id, created_by, time.time(), status))
            connection.commit()
        finally:
            connection.close()
        return schedule_id

    # ---------------------------------------------------------------- 比赛
    def save_competition(self, competition_id=None, *, name, date, opponent_team_id=None,
                         stage=None, format=None, status=None, owner=None, notes=None):
        """写入/合并比赛。status 传 None 表示保留原状态，不重置回 planned。"""
        name = str(name or '').strip()
        if not name:
            raise ValueError('比赛必须有名称')
        if not date:
            raise ValueError('比赛必须有日期')
        competition_id = competition_id or 'comp-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO competitions(id, name, date, opponent_team_id, stage, format, status, '
                'owner, notes, created_at) VALUES(?,?,?,?,?,?,COALESCE(?,\'planned\'),?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET name=excluded.name, date=excluded.date, '
                'opponent_team_id=excluded.opponent_team_id, stage=excluded.stage, '
                'format=excluded.format, status=COALESCE(?,competitions.status), owner=excluded.owner, '
                'notes=excluded.notes, updated_at=?, revision=competitions.revision+1',
                (competition_id, name, date, opponent_team_id, stage, format, status,
                 owner, notes, time.time(), status, time.time()))
            connection.commit()
        finally:
            connection.close()
        return competition_id

    def list_competitions(self):
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT c.*, '
                ' (SELECT COUNT(*) FROM schedules s WHERE s.competition_id=c.id) AS session_count, '
                ' (SELECT COUNT(DISTINCT l.match_key) FROM schedules s '
                '    JOIN session_match_links l ON l.schedule_id=s.id '
                '    WHERE s.competition_id=c.id) AS linked_count '
                'FROM competitions c ORDER BY c.date DESC, c.created_at DESC').fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def get_competition(self, competition_id):
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM competitions WHERE id=?',
                                     (competition_id,)).fetchone()
        finally:
            connection.close()
        return {key: row[key] for key in row.keys()} if row else None

    def competition_detail(self, competition_id):
        """比赛聚合：比赛本身 + 挂在其下的训练课 + 这些训练课关联的对局。

        对局匹配沿用 session_matches（手工关联 → 日期+对手 → 日期+训练组 → 日期），
        与训练课页同口径。返回原始 team/player 列表供前端显示对手与选手信息。
        """
        competition = self.get_competition(competition_id)
        if not competition:
            return None
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT * FROM schedules WHERE competition_id=? ORDER BY date, start_time',
                (competition_id,)).fetchall()
        finally:
            connection.close()
        schedules = [{key: row[key] for key in row.keys()} for row in rows]
        matches, seen = [], set()
        for schedule in schedules:
            for match in self.session_matches(schedule)['matches']:
                key = match.get('match_key')
                if key in seen:
                    continue
                seen.add(key)
                matches.append(match)
        matches.sort(key=lambda item: (str(item.get('date') or ''), str(item.get('match_key') or '')))
        return {'competition': competition, 'schedules': schedules, 'matches': matches,
                'teams': self.list_teams(), 'players': self.list_players()}

    def list_schedules(self, *, status=None):
        connection = self.connect()
        try:
            if status:
                rows = connection.execute('SELECT * FROM schedules WHERE status=? ORDER BY date DESC, start_time',
                                          (status,)).fetchall()
            else:
                rows = connection.execute('SELECT * FROM schedules ORDER BY date DESC, start_time').fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def get_schedule(self, schedule_id):
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM schedules WHERE id=?', (schedule_id,)).fetchone()
        finally:
            connection.close()
        return {key: row[key] for key in row.keys()} if row else None

    def session_matches(self, schedule):
        """按 schedule_id → 日期+对手 → 日期+训练组 → 日期 的顺序找这场训练课的对局。"""
        if not schedule:
            return {'matches': [], 'reason': 'none'}
        schedule_id = str(schedule.get('id') or '').strip()
        schedule_date = str(schedule.get('date') or '').strip()
        opponent = str(schedule.get('opponent_team_id') or '').strip()
        session = str(schedule.get('session') or '').strip()
        connection = self.connect()
        try:
            def query(where, params):
                rows = connection.execute(
                    'SELECT match_key,date,session,enemy_team_id,own_side,winner,score,duration,status '
                    'FROM match_records WHERE ' + where + ' ORDER BY date, match_key', params).fetchall()
                return [{key: row[key] for key in row.keys()} for row in rows]

            if schedule_id:
                manual_keys = [row[0] for row in connection.execute(
                    'SELECT match_key FROM session_match_links WHERE schedule_id=?', (schedule_id,))]
                if manual_keys:
                    marks = ','.join('?' for _ in manual_keys)
                    rows = connection.execute(
                        'SELECT match_key,date,session,enemy_team_id,own_side,winner,score,duration,status '
                        f'FROM match_records WHERE match_key IN ({marks}) ORDER BY date, match_key',
                        manual_keys).fetchall()
                    return {'matches': [{key: row[key] for key in row.keys()} for row in rows],
                            'reason': 'manual'}
                rows = query('schedule_id=?', (schedule_id,))
                if rows:
                    return {'matches': rows, 'reason': 'schedule'}
            if schedule_date and opponent:
                rows = query('date=? AND enemy_team_id=?', (schedule_date, opponent))
                if rows:
                    return {'matches': rows, 'reason': 'date_opponent'}
            if schedule_date and session:
                rows = query('date=? AND session=?', (schedule_date, session))
                if rows:
                    return {'matches': rows, 'reason': 'date_session'}
            if schedule_date:
                rows = query('date=?', (schedule_date,))
                if rows:
                    return {'matches': rows, 'reason': 'date'}
        finally:
            connection.close()
        return {'matches': [], 'reason': 'none'}

    def available_matches(self, limit=200):
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT match_key,date,session,enemy_team_id,own_side,winner,score,duration,status '
                'FROM match_records ORDER BY date DESC, match_key LIMIT ?', (max(1, min(500, limit)),)).fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def manual_session_keys(self, schedule_id):
        connection = self.connect()
        try:
            return [row[0] for row in connection.execute(
                'SELECT match_key FROM session_match_links WHERE schedule_id=? ORDER BY match_key',
                (schedule_id,))]
        finally:
            connection.close()

    def save_session_links(self, schedule_id, match_keys, *, actor=None):
        if not isinstance(match_keys, list) or len(match_keys) > 200:
            raise ValueError('一次最多关联 200 局')
        keys = []
        for key in match_keys:
            value = str(key or '').strip()
            if value and value not in keys:
                keys.append(value)
        connection = self.connect()
        try:
            if connection.execute('SELECT 1 FROM schedules WHERE id=?', (schedule_id,)).fetchone() is None:
                raise ValueError('训练课不存在')
            known = {row[0] for row in connection.execute('SELECT match_key FROM match_records')}
            keys = [key for key in keys if key in known]
            connection.execute('DELETE FROM session_match_links WHERE schedule_id=?', (schedule_id,))
            for key in keys:
                connection.execute(
                    'INSERT INTO session_match_links(schedule_id, match_key, created_at) VALUES(?,?,?)',
                    (schedule_id, key, time.time()))
            self._log(connection, 'schedule', schedule_id, 'session_match_links', None,
                      json.dumps(keys, ensure_ascii=False), 'manual', actor)
            connection.commit()
        finally:
            connection.close()
        return keys

    def unmapped_opponents(self):
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT enemy_team_id, COUNT(*) AS matches, MIN(date) AS first_date, MAX(date) AS last_date '
                'FROM match_records WHERE IFNULL(enemy_team_id, "") != "" '
                'AND enemy_team_id NOT IN (SELECT id FROM teams) '
                'GROUP BY enemy_team_id ORDER BY matches DESC, enemy_team_id').fetchall()
        finally:
            connection.close()
        return [{'oldId': row['enemy_team_id'], 'matches': row['matches'],
                 'firstDate': row['first_date'], 'lastDate': row['last_date']} for row in rows]

    def map_opponent(self, old_id, team_id, *, actor=None):
        old_id = str(old_id or '').strip()
        team_id = str(team_id or '').strip()
        if not old_id or not team_id:
            raise ValueError('缺少旧对手 ID 或目标战队')
        connection = self.connect()
        try:
            team = connection.execute(
                "SELECT id, name FROM teams WHERE id=? AND status='active'", (team_id,)).fetchone()
            if team is None:
                raise ValueError('目标战队不存在')
            connection.execute(
                'INSERT INTO team_aliases(old_id, team_id, created_at) VALUES(?,?,?) '
                'ON CONFLICT(old_id) DO UPDATE SET team_id=excluded.team_id, created_at=excluded.created_at',
                (old_id, team_id, time.time()))
            updated = connection.execute(
                'UPDATE match_records SET enemy_team_id=? WHERE enemy_team_id=?',
                (team_id, old_id)).rowcount
            for table in ('matches', 'match_rosters'):
                try:
                    connection.execute(f'UPDATE {table} SET enemy_team_id=? WHERE enemy_team_id=?',
                                       (team_id, old_id)) if table == 'matches' else \
                        connection.execute(f'UPDATE {table} SET team_id=? WHERE team_id=?',
                                           (team_id, old_id))
                except sqlite3.Error:
                    pass
            self._log(connection, 'team', team_id, 'opponent_alias', old_id, team_id, 'manual', actor)
            connection.commit()
        finally:
            connection.close()
        return {'oldId': old_id, 'teamId': team_id, 'updated': updated}

    def inbox(self):
        today = time.strftime('%Y-%m-%d')
        connection = self.connect()
        try:
            pending = connection.execute('SELECT COUNT(*) FROM prefill_fields').fetchone()[0]
            unnamed = connection.execute(
                "SELECT COUNT(*) FROM teams WHERE status='active' AND name LIKE '待命名%'").fetchone()[0]
            try:
                # 没有游戏账号映射的选手，营地爬到了也认不出人。
                unbound = connection.execute(
                    'SELECT COUNT(*) FROM players p WHERE NOT EXISTS '
                    '(SELECT 1 FROM player_accounts a WHERE a.player_id = p.id)').fetchone()[0]
            except sqlite3.Error:
                unbound = connection.execute(
                    "SELECT COUNT(*) FROM players WHERE IFNULL(camp_user_id, '') = ''").fetchone()[0]
            session_rows = connection.execute(
                "SELECT id,date,opponent_team_id,review_status FROM schedules "
                "WHERE date<=? AND IFNULL(status,'') NOT IN ('cancelled','completed') "
                "AND IFNULL(review_status,'') != 'done' ORDER BY date, id LIMIT 8", (today,)).fetchall()
            sessions = connection.execute(
                "SELECT COUNT(*) FROM schedules WHERE date<=? AND IFNULL(status,'') NOT IN ('cancelled','completed') "
                "AND IFNULL(review_status,'') != 'done'", (today,)).fetchone()[0]
            teams = [{'id': row['id'], 'name': row['name']} for row in connection.execute(
                "SELECT id,name FROM teams WHERE status='active' ORDER BY name")]
            legacy = 0
            try:
                settings_row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
                if settings_row:
                    roster = json.loads(settings_row[0]).get('roster') or []
                    player_ids = {row[0] for row in connection.execute('SELECT id FROM players')}
                    legacy = sum(1 for member in roster
                                 if isinstance(member, dict) and not member.get('archived')
                                 and str(member.get('id') or '') not in player_ids)
            except (sqlite3.Error, TypeError, ValueError):
                legacy = 0
            unmapped = connection.execute(
                'SELECT enemy_team_id, COUNT(*) AS matches FROM match_records '
                'WHERE IFNULL(enemy_team_id, "") != "" AND enemy_team_id NOT IN (SELECT id FROM teams) '
                'GROUP BY enemy_team_id ORDER BY matches DESC').fetchall()
        finally:
            connection.close()
        groups = [
            {'key': 'pending', 'label': '待确认字段', 'count': pending,
             'note': '版本 / 规则 / 训练组等需要核实', 'href': '#pending'},
            {'key': 'unnamed', 'label': '战队待命名', 'count': unnamed,
             'note': '显示为「待命名战队 #N」', 'href': '#setup'},
            {'key': 'legacy', 'label': '旧名单未迁移', 'count': legacy,
             'note': '旧档案成员还没进入选手主数据', 'href': '#setup'},
            {'key': 'sessions', 'label': '训练课待复盘', 'count': sessions,
             'note': '已过日期但还没有标记已复盘', 'href': '#plan',
             'items': [{'label': f"{row['date']} · {row['id']}", 'href': f'#session/{row["id"]}',
                        'id': row['id'], 'date': row['date']} for row in session_rows]},
            {'key': 'unmapped', 'label': '对局对手未映射', 'count': sum(row['matches'] for row in unmapped),
             'note': '历史对手 ID 不在当前战队表，需要映射', 'href': '#matches',
             'items': [{'oldId': row['enemy_team_id'], 'matches': row['matches']} for row in unmapped]},
            {'key': 'unbound', 'label': '选手未绑定游戏ID', 'count': unbound,
             'note': '没有游戏ID映射的选手，营地再爬到也认不出人', 'href': '#setup'},
        ]
        groups = [group for group in groups if group['count']]
        return {'total': sum(group['count'] for group in groups), 'groups': groups, 'teams': teams}

    def save_session_review(self, schedule_id, *, goals=None, review=None, review_status=None,
                            attendance=None, actor=None):
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM schedules WHERE id=?', (schedule_id,)).fetchone()
            if row is None:
                raise ValueError('训练课不存在')
            if review_status not in (None, '', 'pending', 'done'):
                raise ValueError('复盘状态无效')
            patch = {}
            if goals is not None:
                patch['goals'] = _json(goals if isinstance(goals, list) else [], [])
            if review is not None:
                patch['review'] = str(review)
            if review_status is not None:
                patch['review_status'] = review_status
            if attendance is not None:
                patch['attendance'] = _json(attendance if isinstance(attendance, list) else [], [])
            if not patch:
                return self.get_schedule(schedule_id)
            assignments = ', '.join(f'{key}=?' for key in patch)
            connection.execute(
                f'UPDATE schedules SET {assignments}, updated_at=?, revision=revision+1 WHERE id=?',
                (*patch.values(), time.time(), schedule_id))
            if review_status == 'done' and row['status'] not in ('cancelled', 'completed'):
                connection.execute("UPDATE schedules SET status='completed' WHERE id=?", (schedule_id,))
            changed = ', '.join(patch.keys())
            self._log(connection, 'schedule', schedule_id, changed,
                      None, json.dumps({k: patch[k] for k in patch}, ensure_ascii=False),
                      'session-review', actor)
            connection.commit()
        finally:
            connection.close()
        return self.get_schedule(schedule_id)

    # ---------------------------------------------------------------- 训练干预
    def save_training(self, session_id=None, *, goal, intervention, start_date, end_date=None,
                      player_ids=None, metric, target=None, review=None):
        if not goal or not metric:
            raise ValueError('训练目标与指标必填')
        session_id = session_id or 'tr-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO training(session_id, goal, intervention, start_date, end_date, player_ids, '
                'metric, target, review) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET '
                'goal=excluded.goal, intervention=excluded.intervention, start_date=excluded.start_date, '
                'end_date=excluded.end_date, player_ids=excluded.player_ids, metric=excluded.metric, '
                'target=excluded.target, review=excluded.review, revision=training.revision+1',
                (session_id, goal, intervention, start_date, end_date, _json(player_ids, []),
                 metric, target, review))
            connection.commit()
        finally:
            connection.close()
        return session_id

    def list_training(self):
        connection = self.connect()
        try:
            rows = connection.execute('SELECT * FROM training ORDER BY start_date DESC').fetchall()
        finally:
            connection.close()
        out = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            item['player_ids'] = json.loads(item.get('player_ids') or '[]')
            out.append(item)
        return out

    # ---------------------------------------------------------------- 预填与待确认
    PREFILL_FIELDS = ('enemy_team_id', 'session', 'version', 'rules', 'pick_order')

    def add_prefill(self, match_key, field, value=None, *, source='placeholder',
                    confidence='low', synthetic=0):
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO prefill_fields(match_key, field, value, source, confidence, rule_version, '
                'generated_at, synthetic) VALUES(?,?,?,?,?,?,?,?) '
                'ON CONFLICT(match_key, field) DO UPDATE SET value=excluded.value, '
                'source=excluded.source, confidence=excluded.confidence, '
                'generated_at=excluded.generated_at',
                (match_key, field, None if value is None else str(value), source, confidence,
                 'v1', time.time(), int(synthetic)))
            connection.commit()
        finally:
            connection.close()

    def list_prefill(self, match_key=None):
        connection = self.connect()
        try:
            if match_key:
                rows = connection.execute(
                    'SELECT * FROM prefill_fields WHERE match_key=?', (match_key,)).fetchall()
            else:
                rows = connection.execute('SELECT * FROM prefill_fields').fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def confirm_prefills(self, items, *, actor=None):
        """批量确认待补字段：同一事务，任何一项失败全部回滚。"""
        if not isinstance(items, list) or not items:
            raise ValueError('没有需要确认的字段')
        if len(items) > 200:
            raise ValueError('一次最多确认 200 项')
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            confirmed = []
            for index, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    raise ValueError(f'第 {index} 项格式无效')
                match_key = str(item.get('matchKey') or '').strip()
                field = str(item.get('field') or '').strip()
                value = item.get('value')
                if not match_key or not field:
                    raise ValueError(f'第 {index} 项缺少对局或字段')
                if value is None or (not isinstance(value, list) and str(value).strip() == ''):
                    raise ValueError(f'第 {index} 项缺少值')
                row = connection.execute('SELECT * FROM match_records WHERE match_key=?',
                                         (match_key,)).fetchone()
                if row is None:
                    raise ValueError(f'第 {index} 项对局不存在：{match_key}')
                old = row[field] if field in row.keys() else None
                if field == 'enemy_team_id':
                    team = connection.execute('SELECT id FROM teams WHERE id=? OR name=?',
                                              (str(value), str(value))).fetchone()
                    if team is None:
                        raise ValueError(f'第 {index} 项战队不存在：{value}')
                    value = team['id']
                    connection.execute('UPDATE match_records SET enemy_team_id=?, revision=revision+1 '
                                       'WHERE match_key=?', (value, match_key))
                elif field in ('session', 'version', 'rules'):
                    connection.execute(f'UPDATE match_records SET {field}=?, revision=revision+1 '
                                       'WHERE match_key=?', (value, match_key))
                elif field == 'pick_order':
                    connection.execute(
                        'INSERT INTO bp(match_key, pick_order) VALUES(?,?) '
                        'ON CONFLICT(match_key) DO UPDATE SET pick_order=excluded.pick_order',
                        (match_key, _json(value, [])))
                else:
                    raise ValueError(f'第 {index} 项不支持确认字段：{field}')
                self._log(connection, 'match', match_key, field, old, value, 'confirm', actor)
                connection.execute(
                    'INSERT INTO provenance(match_key, field, source, confidence, synthetic, confirmed_by, '
                    'updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(match_key, field) DO UPDATE SET '
                    'source=excluded.source, confidence=excluded.confidence, '
                    'confirmed_by=excluded.confirmed_by, updated_at=excluded.updated_at',
                    (match_key, field, 'manual', 'high', 0, actor, time.time()))
                connection.execute('DELETE FROM prefill_fields WHERE match_key=? AND field=?',
                                   (match_key, field))
                confirmed.append({'matchKey': match_key, 'field': field,
                                  'value': value if field != 'pick_order' else json.loads(_json(value, []))})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return confirmed

    def confirm_prefill(self, match_key, field, value, *, actor=None):
        """确认一个待补字段：写 match_records（或 bp）并列 provenance。"""
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM match_records WHERE match_key=?',
                                     (match_key,)).fetchone()
            if row is None:
                raise ValueError('对局不存在')
            old = row[field] if field in row.keys() else None
            if field == 'enemy_team_id':
                team = connection.execute('SELECT id FROM teams WHERE id=? OR name=?',
                                          (str(value), str(value))).fetchone()
                if team is None:
                    raise ValueError('战队不存在，请先在对手归属里建档')
                value = team['id']
                connection.execute('UPDATE match_records SET enemy_team_id=?, revision=revision+1 '
                                   'WHERE match_key=?', (value, match_key))
            elif field in ('session', 'version', 'rules'):
                connection.execute(f'UPDATE match_records SET {field}=?, revision=revision+1 '
                                   'WHERE match_key=?', (value, match_key))
            elif field == 'pick_order':
                connection.execute(
                    'INSERT INTO bp(match_key, pick_order) VALUES(?,?) '
                    'ON CONFLICT(match_key) DO UPDATE SET pick_order=excluded.pick_order',
                    (match_key, _json(value, [])))
            else:
                raise ValueError('不支持确认该字段')
            self._log(connection, 'match', match_key, field, old, value, 'confirm', actor)
            connection.execute(
                'INSERT INTO provenance(match_key, field, source, confidence, synthetic, confirmed_by, '
                'updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(match_key, field) DO UPDATE SET '
                'source=excluded.source, confidence=excluded.confidence, '
                'confirmed_by=excluded.confirmed_by, updated_at=excluded.updated_at',
                (match_key, field, 'manual', 'high', 0, actor, time.time()))
            connection.execute('DELETE FROM prefill_fields WHERE match_key=? AND field=?',
                               (match_key, field))
            connection.commit()
        finally:
            connection.close()
        return value

    # ---------------------------------------------------------------- 审计
    def change_log(self, entity_type=None, entity_id=None, limit=100):
        connection = self.connect()
        try:
            if entity_type and entity_id:
                rows = connection.execute(
                    'SELECT * FROM change_log WHERE entity_type=? AND entity_id=? ORDER BY created_at DESC LIMIT ?',
                    (entity_type, entity_id, limit)).fetchall()
            else:
                rows = connection.execute(
                    'SELECT * FROM change_log ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]
