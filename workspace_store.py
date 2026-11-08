"""工作区数据模型：按 docs/analysis_fields_matrix.md 第 4 节建表。

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
  created_by TEXT,
  created_at REAL NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date);

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
                    coach=None, analyst=None, notes=None, status='active', first_seen=None,
                    parent_team_id=None, source='manual', actor=None):
        if not name or not str(name).strip():
            raise ValueError('战队名不能为空')
        team_id = team_id or 'team-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
            if row is None:
                connection.execute(
                    'INSERT INTO teams(id, name, short_name, aliases, league, coach, analyst, notes, '
                    'status, first_seen, parent_team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
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
                    'analyst=COALESCE(?,analyst), notes=COALESCE(?,notes), status=?, '
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
    def upsert_player(self, player_id=None, *, team_id, name, position=None, aliases=None,
                      camp_user_id=None, role='main', match_name=None, source='manual', actor=None):
        if not team_id:
            raise ValueError('选手必须归属战队')
        if not name or not str(name).strip():
            raise ValueError('选手名不能为空')
        player_id = player_id or 'player-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO players(id, team_id, name, match_name, position, aliases, camp_user_id, role) '
                'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET team_id=excluded.team_id, '
                'name=excluded.name, match_name=COALESCE(excluded.match_name, players.match_name), '
                'position=COALESCE(excluded.position, players.position), aliases=excluded.aliases, '
                'camp_user_id=COALESCE(excluded.camp_user_id, players.camp_user_id), role=excluded.role, '
                'revision=players.revision+1',
                (player_id, team_id, name.strip(), match_name, position, _json(aliases, []),
                 camp_user_id, role))
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
            out.append(item)
        return out

    def migrate_roster(self, roster, *, own_team_name='', actor=None):
        """把旧 settings.roster 一次性迁入 players；保留旧 id，跳过明确重复项。"""
        if not isinstance(roster, list):
            raise ValueError('旧名单格式无效')
        if not roster:
            return {'found': 0, 'imported': 0, 'skipped': 0, 'teamsCreated': 0, 'warnings': []}
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

            imported, skipped, warnings = 0, 0, []
            positions = {'对抗路', '打野', '中路', '发育路', '游走'}
            for member in roster:
                if not isinstance(member, dict):
                    skipped += 1
                    continue
                if member.get('archived'):
                    skipped += 1
                    continue
                player_id = str(member.get('id') or '').strip()
                name = str(member.get('name') or member.get('label') or '').strip()
                if not player_id or not name:
                    skipped += 1
                    continue
                raw_team = str(member.get('team') or '').strip()
                team_id = own_id if not raw_team or raw_team == own_team_name else ensure_team(raw_team)
                position = str(member.get('position') or '').strip()
                if position not in positions:
                    position = None
                camp = str(member.get('campUserId') or '').strip()
                key = (team_id, name, position or '')
                if player_id in by_id or (camp and camp in by_camp) or key in by_key:
                    skipped += 1
                    continue
                connection.execute(
                    'INSERT INTO players(id, team_id, name, position, camp_user_id, role) '
                    'VALUES(?,?,?,?,?,?)',
                    (player_id, team_id, name, position, camp or None, 'main'))
                self._log(connection, 'player', player_id, 'created', None, name, 'migrate-roster', actor)
                by_id.add(player_id)
                by_key.add(key)
                if camp:
                    by_camp.add(camp)
                imported += 1
            if skipped:
                warnings.append(f'{skipped} 名旧成员因重复、已存在或缺少名称被跳过。')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {'found': len(roster), 'imported': imported, 'skipped': skipped,
                'teamsCreated': teams_created, 'warnings': warnings}

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

    # ---------------------------------------------------------------- 结构化对局
    def upsert_match(self, match_key, *, date=None, session=None, series_id=None, game_no=None,
                     mode=None, rules=None, version=None, own_team_id=None, enemy_team_id=None,
                     enemy_cluster_id=None, schedule_id=None, own_side=None, winner=None,
                     score=None, duration=None, reviewer=None, status='draft', tags=None,
                     notes=None, source='camp'):
        if not match_key:
            raise ValueError('缺少 match_key')
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO match_records(match_key, date, session, series_id, game_no, mode, rules, '
                'version, own_team_id, enemy_team_id, enemy_cluster_id, schedule_id, own_side, winner, '
                'score, duration, reviewer, status, tags, notes, source) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
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
                'status=excluded.status, tags=excluded.tags, '
                'notes=COALESCE(excluded.notes, match_records.notes), '
                'revision=match_records.revision+1',
                (match_key, date, session, series_id, game_no, mode, rules, version, own_team_id,
                 enemy_team_id, enemy_cluster_id, schedule_id, own_side, winner,
                 _json(score, None) if score is not None else None, duration, reviewer, status,
                 _json(tags, []), notes, source))
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
                      session=None, format=None, rules=None, version=None, status='planned',
                      notes=None, created_by=None):
        if not date:
            raise ValueError('约训必须有日期')
        schedule_id = schedule_id or 'sch-' + uuid.uuid4().hex[:10]
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO schedules(id, date, start_time, opponent_team_id, session, format, rules, '
                'version, status, notes, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET date=excluded.date, start_time=excluded.start_time, '
                'opponent_team_id=excluded.opponent_team_id, session=excluded.session, '
                'format=excluded.format, rules=excluded.rules, version=excluded.version, '
                'status=excluded.status, notes=excluded.notes, revision=schedules.revision+1',
                (schedule_id, date, start_time, opponent_team_id, session, format, rules, version,
                 status, notes, created_by, time.time()))
            connection.commit()
        finally:
            connection.close()
        return schedule_id

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
