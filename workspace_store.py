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
from datetime import date as _date, datetime as _datetime
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
  status TEXT NOT NULL DEFAULT 'active',
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

/* 统一采集上下文：一次勾选 = 一个批次，携带本队/对手/对局类型。 */
CREATE TABLE IF NOT EXISTS capture_batches (
  id TEXT PRIMARY KEY,
  competition_id TEXT,
  own_team_id TEXT,
  opponent_team_id TEXT,
  match_type TEXT NOT NULL DEFAULT 'training',
  camp_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  notes TEXT,
  report TEXT,
  created_at REAL NOT NULL,
  updated_at REAL,
  actor TEXT
);

/* 双匹配池：按 playerId 聚合的 own/enemy 昵称池，昵称只作展示与匹配线索。 */
CREATE TABLE IF NOT EXISTS player_nickname_pool (
  id TEXT PRIMARY KEY,
  side TEXT NOT NULL,
  player_id TEXT,
  nickname TEXT NOT NULL,
  account_id TEXT,
  match_key TEXT,
  lane TEXT,
  source TEXT NOT NULL DEFAULT 'camp',
  confidence TEXT NOT NULL DEFAULT 'medium',
  seen_at TEXT,
  created_at REAL NOT NULL,
  UNIQUE(side, nickname, account_id)
);
CREATE INDEX IF NOT EXISTS idx_nickname_pool_player ON player_nickname_pool(player_id);
CREATE INDEX IF NOT EXISTS idx_nickname_pool_nick ON player_nickname_pool(nickname, side);

/* 匹配规则集：游戏名 → 选手 ID 的确定映射。own 用 scope=''；
   enemy 用 scope=对手战队 id，换队/换人靠「异常」交教练改，不静默覆盖。 */
CREATE TABLE IF NOT EXISTS matching_rules (
  id TEXT PRIMARY KEY,
  side TEXT NOT NULL,
  nickname TEXT NOT NULL,
  player_id TEXT NOT NULL,
  team_id TEXT NOT NULL DEFAULT '',
  scope TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  notes TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(side, nickname, scope)
);
CREATE INDEX IF NOT EXISTS idx_matching_rules_side ON matching_rules(side, nickname);

CREATE TABLE IF NOT EXISTS player_team_history (
  player_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  source TEXT,
  membership_id TEXT,
  relation_type TEXT NOT NULL DEFAULT 'formal',
  roster_role TEXT NOT NULL DEFAULT 'starter',
  actor TEXT,
  undone_at REAL,
  notes TEXT,
  PRIMARY KEY(player_id, team_id, start_date)
);

/* 4.0 账号—选手的**时间化**关系。player_accounts 仍是"当前映射"快表，
   本表记录生效区间与单局覆盖：同一个账号先后由不同选手使用、同一选手换号、
   某局身份纠错都在这里留痕；历史对局文件一律不改。 */
CREATE TABLE IF NOT EXISTS account_player_links (
  link_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL DEFAULT 'camp',
  account_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  game_match_key TEXT,
  side TEXT,
  status TEXT NOT NULL DEFAULT 'confirmed',
  source TEXT,
  actor TEXT,
  undone_at REAL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_links_account ON account_player_links(account_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_account_links_player ON account_player_links(player_id);

/* 重复选手人工合并：留镜像与撤销依据，不物理删除、不重写历史出场。 */
CREATE TABLE IF NOT EXISTS identity_merge_logs (
  merge_id TEXT PRIMARY KEY,
  from_player_id TEXT NOT NULL,
  to_player_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'applied',
  detail TEXT NOT NULL DEFAULT '{}',
  actor TEXT,
  undone_at REAL,
  created_at REAL NOT NULL
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
  date TEXT NOT NULL,          -- 训练起始（赛事卡片「训练起始」，按对局的训练日期比对）
  end_date TEXT,               -- 训练结束（赛事卡片「训练结束」）
  formal_from TEXT,            -- 正式比赛起（与训练时间独立的时间口径）
  formal_to TEXT,              -- 正式比赛止
  opponent_team_id TEXT,
  team_ids TEXT NOT NULL DEFAULT '[]',
  head_coach TEXT,
  assistant_coach TEXT,
  data_analyst TEXT,
  staff TEXT NOT NULL DEFAULT '[]',
  own_player_ids TEXT NOT NULL DEFAULT '[]',
  key_match_keys TEXT NOT NULL DEFAULT '[]',
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
  date TEXT,                   -- 比赛发生日期
  recorded_date TEXT,          -- 录入日期（训练赛归集口径；缺省回退 date）
  match_type TEXT,             -- training / formal，与赛事归属是独立维度
  in_trial INTEGER DEFAULT 0,           -- 试训对局：必须排除在赛事归集外（NULL=未指定）
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
  competition_id TEXT,
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
  date TEXT,                   -- 比赛发生日期
  recorded_date TEXT,          -- 录入日期（训练赛归集口径；缺省回退 date）
  match_type TEXT,             -- training / formal，与赛事归属是独立维度
  in_trial INTEGER DEFAULT 0,           -- 试训对局：必须排除在赛事归集外（NULL=未指定）
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
  competition_id TEXT,
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
CREATE INDEX IF NOT EXISTS idx_records_competition ON match_records(competition_id);
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
  -- 按槽位唯一：同一选手的多个小号可以在同一局各占一个位置。
  PRIMARY KEY(match_key, side, slot)
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

/* 训练系列赛（V2.0）：独立于单局的关系实体，原始对局数据不改动。
   确认编组时才把 series_id/game_no 写回 match_records/matches 的既有列，
   供旧查询兼容；删除系列赛只清关系列，不动对局本身。 */
CREATE TABLE IF NOT EXISTS training_series (
  id TEXT PRIMARY KEY,
  best_of INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',
  ruleset_id TEXT NOT NULL DEFAULT 'scrim-global-team',
  opponent TEXT,
  opponent_team_id TEXT,
  session TEXT,
  schedule_id TEXT,
  version TEXT,
  start_at TEXT,
  end_at TEXT,
  completion_mode TEXT NOT NULL DEFAULT 'standard',
  completion TEXT NOT NULL DEFAULT 'open',
  notes TEXT,
  competition_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL,
  updated_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_series_start ON training_series(start_at);
CREATE INDEX IF NOT EXISTS idx_series_session ON training_series(session);

/* 一局只能归属一个系列赛：match_key 全局 UNIQUE，重复确认直接被约束拦下。 */
CREATE TABLE IF NOT EXISTS training_series_games (
  series_id TEXT NOT NULL,
  match_key TEXT NOT NULL UNIQUE,
  game_index INTEGER NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(series_id, match_key)
);
CREATE INDEX IF NOT EXISTS idx_series_games_series ON training_series_games(series_id);
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


class SeriesConflict(ValueError):
    """一局对局已被别的系列赛占用；带出占用清单供接口转 409。"""

    def __init__(self, occupied):
        self.occupied = occupied  # [(match_key, series_id), ...]
        text = '；'.join(f'{key} 已属于 {sid}' for key, sid in occupied)
        super().__init__(text or '对局已被其他系列赛占用')


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
                if 'status' not in existing:
                    connection.execute("ALTER TABLE players ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            except sqlite3.Error as error:
                self.schema_warnings.append(f'players 迁移: {error}')
            # 4.0 时间化身份：旧库 player_team_history 只加列，不重建（PK 不变）。
            try:
                cols = {row[1] for row in connection.execute('PRAGMA table_info(player_team_history)')}
                for column, ddl in {
                    'membership_id': 'TEXT',
                    'relation_type': "TEXT NOT NULL DEFAULT 'formal'",
                    'roster_role': "TEXT NOT NULL DEFAULT 'starter'",
                    'actor': 'TEXT',
                    'undone_at': 'REAL',
                    'notes': 'TEXT',
                }.items():
                    if cols and column not in cols:
                        connection.execute(f'ALTER TABLE player_team_history ADD COLUMN {column} {ddl}')
                if cols:
                    connection.execute('CREATE INDEX IF NOT EXISTS idx_membership_id '
                                       'ON player_team_history(membership_id)')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'player_team_history 迁移: {error}')
            # 系列赛关系列（V2.0）：旧库的 match_records 可能没有 series_id/game_no，
            # 有 match_key 结构的按需补列；matches 若是存 JSON body 的旧表（无
            # match_key）则跳过，写回时按 PRAGMA 动态判断可用表。
            for table in ('match_records', 'matches'):
                try:
                    cols = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
                    if 'match_key' not in cols:
                        continue
                    if 'series_id' not in cols:
                        connection.execute(f'ALTER TABLE {table} ADD COLUMN series_id TEXT')
                    if 'game_no' not in cols:
                        connection.execute(f'ALTER TABLE {table} ADD COLUMN game_no INTEGER')
                except sqlite3.Error as error:
                    self.schema_warnings.append(f'{table} 系列赛列迁移: {error}')
            # 赛事归属：对局直连 competition_id（旧库补列）。
            # 归集与双时间口径所需列：录入日期 / 比赛类型 / 试训标记（全部可选，旧数据回退 date/training/0）。
            for table in ('match_records', 'matches'):
                try:
                    cols = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
                    if 'match_key' not in cols:
                        continue
                    if 'competition_id' not in cols:
                        connection.execute(f'ALTER TABLE {table} ADD COLUMN competition_id TEXT')
                    for column, ddl in {
                        'recorded_date': 'TEXT',
                        'match_type': 'TEXT',
                        'in_trial': 'INTEGER DEFAULT 0',
                        'formal_link': 'TEXT',
                    }.items():
                        if column not in cols:
                            connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
                except sqlite3.Error as error:
                    self.schema_warnings.append(f'{table} 赛事列迁移: {error}')
            # 匹配保存丢人：旧主键 (match_key,team_id,player_id) 会让同一选手的
            # 第二个小号 INSERT OR REPLACE 掉第一人，10 人只剩 9 人。
            # 改成按槽位唯一，并保留旧数据（迁移只在主键不含 slot 时跑一次）。
            try:
                pk_cols = {row[1] for row in connection.execute(
                    'PRAGMA table_info(match_rosters)') if row[5]}
                if pk_cols and 'slot' not in pk_cols:
                    connection.execute(
                        'ALTER TABLE match_rosters RENAME TO match_rosters_old_pk')
                    connection.execute(
                        'CREATE TABLE match_rosters ('
                        'match_key TEXT NOT NULL, team_id TEXT NOT NULL, '
                        'player_id TEXT NOT NULL, account_id TEXT, '
                        'side TEXT NOT NULL, slot INTEGER NOT NULL, hero TEXT, '
                        'is_sub INTEGER NOT NULL DEFAULT 0, '
                        'is_trial INTEGER NOT NULL DEFAULT 0, '
                        'PRIMARY KEY(match_key, side, slot))')
                    connection.execute(
                        'INSERT OR REPLACE INTO match_rosters '
                        '(match_key,team_id,player_id,account_id,side,slot,hero,is_sub,is_trial) '
                        'SELECT match_key,team_id,player_id,account_id,side,slot,hero,is_sub,is_trial '
                        'FROM match_rosters_old_pk')
                    connection.execute('DROP TABLE match_rosters_old_pk')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'match_rosters 主键迁移: {error}')
            # 一次性清理：老版本删队只把 teams 标 archived，覆盖层/规则/昵称池
            # 还留着记录，导致删完后战队档案仍从缓存里复活。
            try:
                archived = [row[0] for row in connection.execute(
                    "SELECT id FROM teams WHERE status='archived'")]
                for team_id in archived:
                    for sql, params in (
                        ('DELETE FROM team_clusters WHERE key=?', (team_id,)),
                        ('DELETE FROM matching_rules WHERE team_id=? OR scope=?',
                         (team_id, team_id)),
                    ):
                        try:
                            connection.execute(sql, params)
                        except sqlite3.Error:
                            pass
                    try:
                        player_ids = [row[0] for row in connection.execute(
                            'SELECT id FROM players WHERE team_id=?', (team_id,))]
                        for player_id in player_ids:
                            connection.execute(
                                'DELETE FROM player_nickname_pool WHERE player_id=?',
                                (player_id,))
                    except sqlite3.Error:
                        pass
            except sqlite3.Error as error:
                self.schema_warnings.append(f'归档战队残留清理: {error}')
            # 赛事域（M1）：系列赛赛事归属冗余列，旧库补列。
            try:
                series_cols = {row[1] for row in connection.execute('PRAGMA table_info(training_series)')}
                if series_cols and 'competition_id' not in series_cols:
                    connection.execute('ALTER TABLE training_series ADD COLUMN competition_id TEXT')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'training_series 赛事列迁移: {error}')
            # 比赛实体增强字段（教练组 / 本队选手 / 参赛队伍 / 关键对局等）。
            # formal_from/formal_to：正式比赛起止，独立于训练起止 date/end_date。
            try:
                existing = {row[1] for row in connection.execute('PRAGMA table_info(competitions)')}
                for column, ddl in {
                    'end_date': 'TEXT',
                    'formal_from': 'TEXT',
                    'formal_to': 'TEXT',
                    'team_ids': "TEXT NOT NULL DEFAULT '[]'",
                    'head_coach': 'TEXT',
                    'assistant_coach': 'TEXT',
                    'data_analyst': 'TEXT',
                    'staff': "TEXT NOT NULL DEFAULT '[]'",
                    'own_player_ids': "TEXT NOT NULL DEFAULT '[]'",
                    'key_match_keys': "TEXT NOT NULL DEFAULT '[]'",
                }.items():
                    if column not in existing:
                        connection.execute(f'ALTER TABLE competitions ADD COLUMN {column} {ddl}')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'competitions 增强字段迁移: {error}')
            # 4.0 归档纠错：把拉错的局（排位/巅峰赛等）标为排除，保留原记录以便撤销。
            # 只加两列，不改对局本身；所有归集查询统一在 _all_match_rows 过滤。
            try:
                existing = {row[1] for row in connection.execute('PRAGMA table_info(match_records)')}
                if existing:
                    if 'excluded_at' not in existing:
                        connection.execute('ALTER TABLE match_records ADD COLUMN excluded_at TEXT')
                    if 'excluded_reason' not in existing:
                        connection.execute('ALTER TABLE match_records ADD COLUMN excluded_reason TEXT')
            except sqlite3.Error as error:
                self.schema_warnings.append(f'match_records 归档纠错字段迁移: {error}')
            # 赛事域打通：旧系列赛即使对局已按窗口归档，也可能没有赛事归属，
            # 导致大场/跨局页按当前赛事筛选时整批消失。按同一归集口径回填。
            try:
                for series in connection.execute('SELECT id, competition_id FROM training_series').fetchall():
                    if series['competition_id']:
                        continue
                    keys = [row['match_key'] for row in connection.execute(
                        'SELECT match_key FROM training_series_games WHERE series_id=?', (series['id'],)).fetchall()]
                    comps = self._match_competitions(connection, keys)
                    if comps:
                        connection.execute('UPDATE training_series SET competition_id=? WHERE id=?',
                                           (next(iter(comps)), series['id']))
            except sqlite3.Error as error:
                self.schema_warnings.append(f'series 赛事归属回填: {error}')
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

    def own_team_id(self) -> str:
        """本队战队的稳定 ID（本队页填队名时由 identity_service 写入）。"""
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT value FROM workspace_meta WHERE key='own_team_id'").fetchone()
            return str(row['value']) if row and row['value'] else ''
        finally:
            connection.close()

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
        """合并战队：源队归档，主数据里仍挂在源队的选手改挂目标队。

        只动 players.team_id（教练登记的当前归属）；营地逐局面板里的历史出场
        一个字节都不改。选手真的转会到别的队，由教练在「对手归属」里改挂，
        并队不会替他做转会判断，也不会把两拨人并成一套当前阵容。
        """
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

    def delete_team(self, team_id, *, actor=None):
        """删除对手战队：战队卡下架，名下选手连同账号映射一起删除，不留野生 ID。"""
        team_id = str(team_id or '').strip()
        if not team_id:
            raise ValueError('缺少战队 id')
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            # 本队战队是主数据，下面挂着全部本队选手 ID 与账号映射。它曾因
            # 「对方战队」页没过滤而被当成对手显示，误点删除会连本队 ID 一起清掉。
            # 前端过滤之外，这里必须兜底拒绝。
            own = connection.execute(
                "SELECT value FROM workspace_meta WHERE key='own_team_id'").fetchone()
            if own and str(own['value'] or '') == team_id:
                raise ValueError('这是本队战队，不能删除；本队选手 ID 都挂在它下面')
            team = connection.execute('SELECT name FROM teams WHERE id=?', (team_id,)).fetchone()
            if team is None:
                raise ValueError('战队不存在')
            rows = connection.execute('SELECT id, name FROM players WHERE team_id=?', (team_id,)).fetchall()
            player_ids = [row['id'] for row in rows]

            def safe(sql, params=()):
                """老库可能没有某张表；删队不该因为缺表而整笔回滚。"""
                try:
                    connection.execute(sql, params)
                    return True
                except sqlite3.Error:
                    return False

            for player_id in player_ids:
                safe('DELETE FROM player_accounts WHERE player_id=?', (player_id,))
            # 级联清掉所有按 player_id / team_id 存的下游数据。以前只删 players
            # 和 player_accounts，覆盖层、昵称池、阵容、规则里的记录全留下，
            # 用户看到的就是「战队卡删了，档案/匹配里还有」。
            for player_id in player_ids:
                safe('DELETE FROM player_nickname_pool WHERE player_id=?', (player_id,))
                safe('DELETE FROM match_rosters WHERE player_id=?', (player_id,))
                safe('DELETE FROM player_team_history WHERE player_id=?', (player_id,))
                safe('DELETE FROM account_player_links WHERE player_id=?', (player_id,))
                safe('DELETE FROM team_roster_versions WHERE player_id=?', (player_id,))
            safe('DELETE FROM match_rosters WHERE team_id=?', (team_id,))
            safe('DELETE FROM matching_rules WHERE team_id=? OR scope=?', (team_id, team_id))
            safe('DELETE FROM team_roster_versions WHERE team_id=?', (team_id,))
            safe('DELETE FROM team_relations WHERE team_id=? OR related_team_id=?',
                 (team_id, team_id))
            safe('DELETE FROM team_aliases WHERE team_id=?', (team_id,))
            safe('DELETE FROM team_clusters WHERE key=?', (team_id,))
            for table in ('capture_batches', 'competitions', 'schedules'):
                safe(f'UPDATE {table} SET opponent_team_id=NULL WHERE opponent_team_id=?',
                     (team_id,))
            for row in rows:
                connection.execute('DELETE FROM players WHERE id=?', (row['id'],))
                self._log(connection, 'player', row['id'], 'deleted', row['name'], None, 'manual', actor)
            connection.execute(
                "UPDATE teams SET status='archived', revision=revision+1 WHERE id=?", (team_id,))
            self._log(connection, 'team', team_id, 'delete', team['name'], 'archived', 'manual', actor)
            connection.commit()
            return {'ok': True, 'id': team_id, 'playersDeleted': len(rows)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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

    # ---- 匹配规则集：游戏名 → 选手 ID 的确定映射 -------------------------
    @staticmethod
    def _rule_row(row):
        item = {key: row[key] for key in row.keys()}
        return {
            'id': item['id'], 'side': item['side'], 'nickname': item['nickname'],
            'playerId': item['player_id'], 'teamId': item.get('team_id') or '',
            'scope': item.get('scope') or '', 'enabled': bool(item.get('enabled', 1)),
            'notes': item.get('notes') or '', 'createdAt': item.get('created_at'),
            'updatedAt': item.get('updated_at'),
        }

    def list_matching_rules(self, side=None):
        self.ensure_schema()
        connection = self.connect()
        try:
            if side in ('own', 'enemy'):
                rows = connection.execute(
                    'SELECT * FROM matching_rules WHERE side=? ORDER BY nickname, scope',
                    (side,)).fetchall()
            else:
                rows = connection.execute(
                    'SELECT * FROM matching_rules ORDER BY side, nickname, scope').fetchall()
        finally:
            connection.close()
        return [self._rule_row(row) for row in rows]

    def save_matching_rule(self, *, rule_id=None, side=None, nickname='', player_id='',
                           team_id='', scope=None, enabled=True, notes='', actor=None):
        side = str(side or '').strip()
        if side not in ('own', 'enemy'):
            raise ValueError('规则阵营只能是 own 或 enemy')
        nickname = str(nickname or '').strip()
        player_id = str(player_id or '').strip()
        if not nickname or not player_id:
            raise ValueError('游戏名和选手 ID 都不能为空')
        team_id = str(team_id or '').strip()
        scope = str(scope if scope is not None else (team_id if side == 'enemy' else '')).strip()
        now = time.time()
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            rule_id = str(rule_id or '').strip()
            existing = None
            if rule_id:
                existing = connection.execute(
                    'SELECT * FROM matching_rules WHERE id=?', (rule_id,)).fetchone()
            if not existing:
                existing = connection.execute(
                    'SELECT * FROM matching_rules WHERE side=? AND nickname=? AND scope=?',
                    (side, nickname, scope)).fetchone()
            if existing:
                connection.execute(
                    'UPDATE matching_rules SET side=?, nickname=?, player_id=?, team_id=?, '
                    'scope=?, enabled=?, notes=?, updated_at=? WHERE id=?',
                    (side, nickname, player_id, team_id, scope, 1 if enabled else 0,
                     str(notes or '')[:500], now, existing['id']))
                result_id = existing['id']
                verb = 'updated'
            else:
                result_id = 'rule-' + uuid.uuid4().hex[:10]
                connection.execute(
                    'INSERT INTO matching_rules(id, side, nickname, player_id, team_id, scope, '
                    'enabled, notes, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (result_id, side, nickname, player_id, team_id, scope, 1 if enabled else 0,
                     str(notes or '')[:500], now, now))
                verb = 'created'
            # 规则就是「游戏名 → 选手ID」的权威绑定。选手档案页的 name_to_member
            # 只读 player_nickname_pool，不读 matching_rules；以前只建规则时档案页
            # 一直显示未匹配。这里在同一事务里把规则同步进昵称池，两处同源。
            if enabled:
                connection.execute(
                    'DELETE FROM player_nickname_pool WHERE side=? AND nickname=?',
                    (side, nickname))
                connection.execute(
                    'INSERT INTO player_nickname_pool(id, side, player_id, nickname, '
                    'account_id, match_key, lane, source, confidence, seen_at, created_at) '
                    "VALUES(?,?,?,?,NULL,NULL,NULL,'manual','manual',NULL,?)",
                    (uuid.uuid4().hex[:16], side, player_id, nickname, now))
            self._log(connection, 'matching_rule', result_id, verb, nickname, None, 'manual', actor)
            connection.commit()
            row = connection.execute(
                'SELECT * FROM matching_rules WHERE id=?', (result_id,)).fetchone()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise ValueError(f'规则已存在，不能重复：{error}') from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self._rule_row(row)

    def delete_matching_rule(self, rule_id, *, actor=None):
        rule_id = str(rule_id or '').strip()
        if not rule_id:
            raise ValueError('缺少规则 ID')
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM matching_rules WHERE id=?', (rule_id,)).fetchone()
            if not row:
                connection.rollback()
                return {'ok': True, 'deleted': 0}
            connection.execute('DELETE FROM matching_rules WHERE id=?', (rule_id,))
            self._log(connection, 'matching_rule', rule_id, 'deleted', row['nickname'],
                      None, 'manual', actor)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {'ok': True, 'deleted': 1}

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
                     enemy_cluster_id=None, schedule_id=None, competition_id=None, own_side=None, winner=None,
                     score=None, duration=None, reviewer=None, status=None, tags=None,
                     notes=None, source='camp', recorded_date=None, match_type=None, in_trial=None):
        """写入/合并一局记录。status/tags 传 None 表示「本次不改」。

        部分更新（例如营地只回填日期与胜负）不能把人工确认过的 status 重置回
        draft，也不能清空 tags，所以 ON CONFLICT 分支用 COALESCE 保留旧值。

        归集维度（全部可选，旧调用方无需改）：
          recorded_date 录入日期（训练赛归集口径，缺省回退 date）；
          match_type    training/formal，与赛事归属独立；
          in_trial      试训对局标记，归集时必须排除。
        """
        if not match_key:
            raise ValueError('缺少 match_key')
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO match_records(match_key, date, recorded_date, match_type, in_trial, '
                'session, series_id, game_no, mode, rules, '
                'version, own_team_id, enemy_team_id, enemy_cluster_id, schedule_id, competition_id, own_side, winner, '
                'score, duration, reviewer, status, tags, notes, source) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,\'draft\'),COALESCE(?,\'[]\'),?,?) '
                'ON CONFLICT(match_key) DO UPDATE SET '
                'date=COALESCE(excluded.date, match_records.date), '
                'recorded_date=COALESCE(excluded.recorded_date, match_records.recorded_date), '
                'match_type=COALESCE(excluded.match_type, match_records.match_type), '
                'in_trial=COALESCE(excluded.in_trial, match_records.in_trial), '
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
                'competition_id=COALESCE(excluded.competition_id, match_records.competition_id), '
                'own_side=COALESCE(excluded.own_side, match_records.own_side), '
                'winner=COALESCE(excluded.winner, match_records.winner), '
                'score=COALESCE(excluded.score, match_records.score), '
                'duration=COALESCE(excluded.duration, match_records.duration), '
                'reviewer=COALESCE(excluded.reviewer, match_records.reviewer), '
                'status=COALESCE(?, match_records.status), '
                'tags=COALESCE(?, match_records.tags), '
                'notes=COALESCE(excluded.notes, match_records.notes), '
                'revision=match_records.revision+1',
                (match_key, date, recorded_date, match_type,
                 int(bool(in_trial)) if in_trial is not None else None,
                 session, series_id, game_no, mode, rules, version, own_team_id,
                 enemy_team_id, enemy_cluster_id, schedule_id, competition_id, own_side, winner,
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
                # 以前 teamId 为空就整行丢弃：本队未设或候选行没带 teamId 时，
                # 已命中的选手直接不落库。玩家 ID 才是必需项。
                if not row.get('playerId'):
                    continue
                team_id = str(row.get('teamId') or '').strip()
                if not team_id:
                    side = str(row.get('side') or 'blue')
                    team_id = (self.own_team_id() if side == 'blue' else '') or 'team-unassigned'
                connection.execute(
                    'INSERT OR REPLACE INTO match_rosters(match_key, team_id, player_id, account_id, '
                    'side, slot, hero, is_sub, is_trial) VALUES(?,?,?,?,?,?,?,?,?)',
                    (match_key, team_id, row['playerId'], row.get('accountId'),
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

    def competition_matches(self, competition_id, limit=200):
        """直连归属到赛事的对局（match_records.competition_id），供赛事页与分析过滤共用。

        旧库没有 match_records/competition_id 时返回空列表，而不是抛错中断请求。
        """
        connection = self.connect()
        try:
            sql = 'SELECT * FROM match_records WHERE competition_id=? ORDER BY date, match_key'
            params = [competition_id]
            if limit is not None:
                sql += ' LIMIT ?'
                params.append(int(limit))
            rows = connection.execute(sql, params).fetchall()
        except sqlite3.Error:
            return []
        finally:
            connection.close()
        return [{key: row[key] for key in row.keys()} for row in rows]

    # ---------------------------------------------------------------- 赛事归集与双时间口径
    # 设计要点（docs/重构蓝图_白金画廊交互.md §3.5.3）：
    # - 训练赛按【训练日期 date】落入赛事的训练起止 date~end_date（缺省回退 date）；
    # - 正式比赛按【发生日期 date】落入独立的正式比赛起止 formal_from~formal_to 范围；
    # - 全部在查询时计算，改赛事时间后归属自然重算，不写死在对局上；
    # - 试训对局 in_trial=1 一律排除；key_match_keys / competition_id 手动挂载作为补充；
    # - 「赛事」与「训练赛/正式赛」是独立维度，分别用 match_type 过滤。
    TRAINING = 'training'
    FORMAL = 'formal'

    @staticmethod
    def _mfield(row, name, default=None):
        value = row.get(name, default) if isinstance(row, dict) else default
        return default if value is None else value

    @staticmethod
    def _date_bounds(start, end):
        """归一化日期区间；只有一端时另一端留空表示无界。结束早于开始时交换。"""
        start = str(start or '').strip()
        end = str(end or '').strip()
        if start and end and end < start:
            start, end = end, start
        return (start, end) if (start or end) else None

    @classmethod
    def _in_window(cls, value, bounds):
        if not bounds or not value:
            return False
        low, high = bounds
        return (not low or value >= low) and (not high or value <= high)

    @classmethod
    def _match_type(cls, row):
        """显式 match_type 优先；旧数据按 session 文本推断，默认训练赛。"""
        value = str(cls._mfield(row, 'match_type', '') or '').strip().lower()
        if value in (cls.TRAINING, cls.FORMAL):
            return value
        session = str(cls._mfield(row, 'session', '') or '')
        if '正式' in session or 'formal' in session.lower():
            return cls.FORMAL
        return cls.TRAINING

    @classmethod
    def _recorded_date(cls, row):
        return str(cls._mfield(row, 'recorded_date', '') or cls._mfield(row, 'date', '') or '').strip()

    @classmethod
    def _training_date(cls, row):
        """训练赛日期口径：对局本身的 date，而不是入库时间 recorded_date。

        赛事卡片的「训练起始 / 训练结束」就是拿这个日期去比的。
        """
        return str(cls._mfield(row, 'date', '') or '').strip()

    @classmethod
    def _collect_bounds(cls, competition):
        """训练起止窗口：end_date 缺省时按单日窗口处理，避免旧数据无限吞并后续录入。"""
        start = competition.get('date')
        return cls._date_bounds(start, competition.get('end_date') or start)

    def _all_match_rows(self):
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM match_records WHERE excluded_at IS NULL OR excluded_at = '' "
                'ORDER BY date, match_key').fetchall()
            return [{key: row[key] for key in row.keys()} for row in rows]
        except sqlite3.Error:
            return []
        finally:
            connection.close()

    @staticmethod
    def _competition_manual_keys(competition):
        raw = competition.get('key_match_keys') if isinstance(competition, dict) else None
        try:
            keys = json.loads(raw or '[]')
        except (TypeError, ValueError):
            keys = []
        return {str(key) for key in keys} if isinstance(keys, list) else set()

    @staticmethod
    def _limit(items, limit):
        if limit is None:
            return items
        try:
            return items[:max(0, int(limit))]
        except (TypeError, ValueError):
            return items

    def _aggregated_item(self, row, aggregation):
        item = dict(row)
        item.update({
            'recordedDate': self._recorded_date(row),
            'trainingDate': self._training_date(row),
            'matchType': self._match_type(row),
            'inTrial': bool(self._mfield(row, 'in_trial', 0)),
            'aggregation': aggregation,  # window / manual / direct / unfiled
        })
        return item

    def competition_training_matches(self, competition_id, limit=None):
        """按赛事查训练赛：训练日期落入训练起始/结束 + 手动挂载 + 直连，排除试训对局。

        改赛事时间后无需回写对局，本查询立即反映新归属。
        """
        competition = self.get_competition(competition_id)
        if not competition:
            return []
        window = self._collect_bounds(competition)
        manual = self._competition_manual_keys(competition)
        result = []
        for row in self._all_match_rows():
            if self._mfield(row, 'in_trial', 0) or self._match_type(row) != self.TRAINING:
                continue
            key = str(self._mfield(row, 'match_key', '') or '')
            direct_id = str(self._mfield(row, 'competition_id', '') or '')
            direct = direct_id == competition_id
            # 赛事域 P0：直连归属其他赛事的对局，不进本赛事的窗口/手动口径，
            # 避免同一局同时落在两个赛事的 scope 里（跨域双归属）。
            if direct_id and not direct:
                continue
            # 双通道统一：已被 official-entry 转正的速记占位行，让位给正牌对局。
            if str(self._mfield(row, 'formal_link', '') or ''):
                continue
            mounted = key in manual
            if not (direct or mounted or self._in_window(self._training_date(row), window)):
                continue
            result.append(self._aggregated_item(
                row, 'direct' if direct else ('manual' if mounted else 'window')))
        result.sort(key=lambda item: (item['recordedDate'], str(item.get('match_key') or '')))
        return self._limit(result, limit)

    # ---------------------------------------------------- 归档纠错（删除 / 撤销）
    @staticmethod
    def _now_iso():
        return _datetime.now().astimezone().isoformat(timespec='seconds')

    def exclude_match(self, match_key, reason=''):
        """把拉错的局从所有归集视图里移除；记录留库，可原样撤销。"""
        key = str(match_key or '').strip()
        if not key:
            raise ValueError('缺少对局键')
        connection = self.connect()
        try:
            cursor = connection.execute(
                'UPDATE match_records SET excluded_at=?, excluded_reason=? WHERE match_key=?',
                (self._now_iso(), str(reason or '').strip()[:200], key))
            connection.commit()
            if not cursor.rowcount:
                raise ValueError('找不到该对局')
            return {'matchKey': key, 'excluded': True, 'reason': str(reason or '')}
        finally:
            connection.close()

    def restore_match(self, match_key):
        """撤销排除：对局按既有日期/归属规则重新回到归档区。"""
        key = str(match_key or '').strip()
        if not key:
            raise ValueError('缺少对局键')
        connection = self.connect()
        try:
            cursor = connection.execute(
                "UPDATE match_records SET excluded_at=NULL, excluded_reason=NULL WHERE match_key=?",
                (key,))
            connection.commit()
            if not cursor.rowcount:
                raise ValueError('找不到该对局')
            return {'matchKey': key, 'excluded': False}
        finally:
            connection.close()

    def excluded_matches(self, limit=200):
        """已排除列表，供「撤销」面板读取。"""
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT match_key, date, session, excluded_at, excluded_reason "
                'FROM match_records WHERE excluded_at IS NOT NULL AND excluded_at != "" '
                'ORDER BY excluded_at DESC LIMIT ?', (limit,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            return []
        finally:
            connection.close()

    def competition_scope_keys(self, competition_id, kinds=('training', 'formal')):
        # 赛事分析域的对局键集合（M1 统一 scope 层）：训练赛口径（直连 U 归集
        # 窗口 U 手动挂载）U 正赛口径（formal 窗口）。所有分析取「当前赛事
        # 有哪些局」一律走这里，不得各自另造过滤口径（方案文档 §4）。
        keys = set()
        if not competition_id:
            return keys
        if 'training' in kinds:
            keys |= {str(row.get('match_key') or '')
                     for row in self.competition_training_matches(competition_id, limit=None)}
        if 'formal' in kinds:
            keys |= {str(row.get('match_key') or '')
                     for row in self.competition_formal_matches(competition_id, limit=None)}
        return keys

    # ---------------------------------------------------- 统一采集上下文与双匹配池
    def create_capture_batch(self, *, competition_id=None, own_team_id=None,
                             opponent_team_id=None, match_type='training',
                             camp_user_id=None, notes='', actor='coach', batch_id=None):
        if match_type not in ('training', 'formal'):
            raise ValueError('对局类型只能是 training / formal')
        batch_id = str(batch_id or 'cap-' + uuid.uuid4().hex[:12])
        now = time.time()
        connection = self.connect()
        try:
            connection.execute(
                'INSERT INTO capture_batches(id, competition_id, own_team_id, opponent_team_id, '
                'match_type, camp_user_id, notes, created_at, actor) VALUES(?,?,?,?,?,?,?,?,?)',
                (batch_id, str(competition_id or '') or None, str(own_team_id or '') or None,
                 str(opponent_team_id or '') or None, match_type,
                 str(camp_user_id or '') or None, str(notes or ''), now, actor))
            connection.commit()
        finally:
            connection.close()
        return self.get_capture_batch(batch_id)

    def get_capture_batch(self, batch_id):
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM capture_batches WHERE id=?',
                                     (str(batch_id),)).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def list_capture_batches(self, competition_id=None, limit=100):
        connection = self.connect()
        try:
            if competition_id:
                rows = connection.execute(
                    'SELECT * FROM capture_batches WHERE competition_id=? '
                    'ORDER BY created_at DESC LIMIT ?', (str(competition_id), int(limit))).fetchall()
            else:
                rows = connection.execute(
                    'SELECT * FROM capture_batches ORDER BY created_at DESC LIMIT ?',
                    (int(limit),)).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def update_capture_batch(self, batch_id, *, status=None, report=None, notes=None):
        current = self.get_capture_batch(batch_id)
        if current is None:
            raise ValueError('采集批次不存在')
        connection = self.connect()
        try:
            connection.execute(
                'UPDATE capture_batches SET status=COALESCE(?,status), '
                'report=COALESCE(?,report), notes=COALESCE(?,notes), updated_at=? WHERE id=?',
                (status, json.dumps(report, ensure_ascii=False) if report is not None else None,
                 notes, time.time(), str(batch_id)))
            connection.commit()
        finally:
            connection.close()
        return self.get_capture_batch(batch_id)

    def upsert_nickname_entries(self, rows):
        """rows: [{side, playerId, nickname, accountId, matchKey, lane, confidence, seenAt}]"""
        saved = 0
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            for row in rows or []:
                side = str(row.get('side') or '')
                nickname = str(row.get('nickname') or '').strip()
                if side not in ('own', 'enemy') or not nickname:
                    continue
                # UNIQUE(side,nickname,account_id) 里的 account_id 是 NULL 时
                # SQLite 不去重：同一昵称会被反复插入，多数票解析被污染。
                # 匹配写入传的 accountId 固定为空，先按 (side,nickname) 清旧行。
                connection.execute(
                    'DELETE FROM player_nickname_pool WHERE side=? AND nickname=?',
                    (side, nickname))
                connection.execute(
                    'INSERT INTO player_nickname_pool(id, side, player_id, nickname, account_id, '
                    'match_key, lane, source, confidence, seen_at, created_at) '
                    "VALUES(?,?,?,?,?,?,?,'camp',?,?,?) "
                    'ON CONFLICT(side, nickname, account_id) DO UPDATE SET '
                    'player_id=COALESCE(excluded.player_id, player_nickname_pool.player_id), '
                    'match_key=excluded.match_key, seen_at=excluded.seen_at',
                    (uuid.uuid4().hex[:16], side, str(row.get('playerId') or '') or None,
                     nickname, str(row.get('accountId') or '') or None,
                     str(row.get('matchKey') or '') or None, str(row.get('lane') or '') or None,
                     str(row.get('confidence') or 'medium'), str(row.get('seenAt') or '') or None,
                     time.time()))
                saved += 1
            if saved:
                # 让跨局向量的指纹跟着变：匹配成功后旧缓存不能继续挂游戏名。
                self._log(connection, 'player', str(rows[0].get('playerId') or '') or 'matching',
                          'matching', None, saved, 'camp', None, None, '匹配与编组保存')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return saved

    def nickname_pool(self, side=None, player_id=None, nickname=None):
        sql = 'SELECT * FROM player_nickname_pool WHERE 1=1'
        params = []
        if side:
            sql += ' AND side=?'; params.append(str(side))
        if player_id:
            sql += ' AND player_id=?'; params.append(str(player_id))
        if nickname:
            sql += ' AND nickname=?'; params.append(str(nickname))
        sql += ' ORDER BY seen_at DESC, created_at DESC'
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]
        finally:
            connection.close()

    def find_nickname_player(self, nickname, side=None):
        rows = self.nickname_pool(side=side, nickname=str(nickname or '').strip())
        counts = {}
        for row in rows:
            if row['player_id']:
                counts[row['player_id']] = counts.get(row['player_id'], 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    def stamp_capture_context(self, match_keys, *, match_type=None,
                              own_team_id=None, enemy_team_id=None, own_side=None,
                              competition_id=None, source='camp-context'):
        """把采集上下文回填到权威对局表；缺日期的对局保持 draft，不猜时间。"""
        saved = 0
        connection = self.connect()
        try:
            for key in match_keys or []:
                row = connection.execute(
                    'SELECT date, competition_id FROM match_records WHERE match_key=?',
                    (str(key),)).fetchone()
                if row is None:
                    continue
                connection.execute(
                    'UPDATE match_records SET '
                    'match_type=COALESCE(?, match_type), own_team_id=COALESCE(?, own_team_id), '
                    'enemy_team_id=COALESCE(?, enemy_team_id), own_side=COALESCE(?, own_side), '
                    'competition_id=COALESCE(?, competition_id), source=?, '
                    'revision=revision+1 WHERE match_key=?',
                    (str(match_type or '') or None,
                     str(own_team_id or '') or None, str(enemy_team_id or '') or None,
                     str(own_side or '') or None, str(competition_id or '') or None,
                     source, str(key)))
                saved += 1
            connection.commit()
        finally:
            connection.close()
        return saved

    # ---------------------------------------------------- 4.0 时间化身份关系
    MEMBERSHIP_RELATIONS = ('trial', 'formal', 'loan')
    MEMBERSHIP_ROLES = ('starter', 'sub')
    DEFAULT_LANES = ('对抗路', '打野', '中路', '发育路', '游走')

    @staticmethod
    def _iso(value, field, allow_empty=False):
        text = str(value or '').strip()
        if not text:
            if allow_empty:
                return ''
            raise ValueError(f'缺少{field}')
        try:
            return _date.fromisoformat(text).isoformat()
        except ValueError as error:
            raise ValueError(f'{field}日期格式无效，应为 YYYY-MM-DD') from error

    def add_membership(self, player_id, team_id, *, valid_from, valid_to=None,
                       relation_type='formal', roster_role='starter', actor='coach', notes=''):
        """新增一段选手—战队关系（试训 / 转正 / 转会）。不重写历史对局。"""
        if relation_type not in self.MEMBERSHIP_RELATIONS:
            raise ValueError('人员关系只能是 trial / formal / loan')
        if roster_role not in self.MEMBERSHIP_ROLES:
            raise ValueError('阵容角色只能是 starter / sub')
        start = self._iso(valid_from, '生效日期')
        end = self._iso(valid_to, '结束日期', allow_empty=True)
        if end and end < start:
            raise ValueError('结束日期不能早于生效日期')
        connection = self.connect()
        membership_id = uuid.uuid4().hex[:16]
        try:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT 1 FROM players WHERE id=?', (str(player_id),)).fetchone() is None:
                raise ValueError('选手不存在')
            if connection.execute('SELECT 1 FROM teams WHERE id=?', (str(team_id),)).fetchone() is None:
                raise ValueError('战队不存在')
            # 同一选手当前关系先收口：新关系生效日即旧关系结束日。
            if not end:
                connection.execute(
                    "UPDATE player_team_history SET end_date=?, notes=COALESCE(notes,'') "
                    'WHERE player_id=? AND (end_date IS NULL OR end_date=\'\') AND undone_at IS NULL',
                    (start, str(player_id)))
            try:
                connection.execute(
                    'INSERT INTO player_team_history(player_id, team_id, start_date, end_date, '
                    'source, membership_id, relation_type, roster_role, actor, notes) '
                    "VALUES(?,?,?,?,'manual',?,?,?,?,?)",
                    (str(player_id), str(team_id), start, end or None, membership_id,
                     relation_type, roster_role, actor, str(notes or '')))
            except sqlite3.IntegrityError as error:
                raise ValueError('该选手在此日期已有同一战队的归属记录') from error
            if not end:
                connection.execute('UPDATE players SET team_id=?, revision=revision+1 WHERE id=?',
                                   (str(team_id), str(player_id)))
            self._log(connection, 'player', str(player_id), 'membership', None,
                      f'{team_id}@{start}({relation_type}/{roster_role})', 'manual', actor)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {'membershipId': membership_id, 'playerId': str(player_id), 'teamId': str(team_id),
                'validFrom': start, 'validTo': end or None,
                'relationType': relation_type, 'rosterRole': roster_role}

    def list_memberships(self, player_id=None, team_id=None, at_date=None, include_undone=False):
        sql = 'SELECT * FROM player_team_history WHERE 1=1'
        params = []
        if player_id:
            sql += ' AND player_id=?'; params.append(str(player_id))
        if team_id:
            sql += ' AND team_id=?'; params.append(str(team_id))
        if at_date:
            day = self._iso(at_date, '查询日期')
            sql += " AND start_date<=? AND (end_date IS NULL OR end_date='' OR end_date>=?)"
            params += [day, day]
        if not include_undone:
            sql += ' AND undone_at IS NULL'
        sql += ' ORDER BY start_date, team_id'
        connection = self.connect()
        try:
            rows = connection.execute(sql, params).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item['validFrom'] = item.pop('start_date')
                item['validTo'] = item.pop('end_date')
                out.append(item)
            return out
        finally:
            connection.close()

    def undo_membership(self, membership_id):
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM player_team_history WHERE membership_id=? AND undone_at IS NULL',
                (str(membership_id),)).fetchone()
            if row is None:
                raise ValueError('归属记录不存在或已撤销')
            connection.execute('UPDATE player_team_history SET undone_at=? WHERE membership_id=?',
                               (time.time(), str(membership_id)))
            if not row['end_date']:
                previous = connection.execute(
                    "SELECT team_id FROM player_team_history WHERE player_id=? AND membership_id<>? "
                    "AND undone_at IS NULL AND (end_date IS NULL OR end_date='' OR end_date<=?) "
                    'ORDER BY start_date DESC LIMIT 1',
                    (row['player_id'], str(membership_id), row['start_date'])).fetchone()
                if previous:
                    connection.execute('UPDATE players SET team_id=?, revision=revision+1 WHERE id=?',
                                       (previous['team_id'], row['player_id']))
            self._log(connection, 'player', row['player_id'], 'membership:undo',
                      str(membership_id), None, 'manual', 'coach')
            connection.commit()
            return {'membershipId': str(membership_id), 'undone': True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_account_link(self, account_id, player_id, *, valid_from, valid_to=None,
                         game_match_key=None, side=None, actor='coach', update_current=True):
        """时间化账号—选手映射；当前有效且非单局覆盖时同步 player_accounts 快表。"""
        account_id = str(account_id or '').strip()
        player_id = str(player_id or '').strip()
        if not account_id or not player_id:
            raise ValueError('缺少游戏账号或选手')
        start = self._iso(valid_from, '生效日期')
        end = self._iso(valid_to, '结束日期', allow_empty=True)
        if end and end < start:
            raise ValueError('结束日期不能早于生效日期')
        link_id = uuid.uuid4().hex[:16]
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT 1 FROM players WHERE id=?', (player_id,)).fetchone() is None:
                raise ValueError('选手不存在')
            connection.execute(
                'INSERT INTO account_player_links(link_id, platform, account_id, player_id, '
                'valid_from, valid_to, game_match_key, side, status, source, actor, created_at) '
                "VALUES(?,'camp',?,?,?,?,?,?,'confirmed','manual',?,?)",
                (link_id, account_id, player_id, start, end or None,
                 str(game_match_key or '') or None, str(side or '') or None,
                 actor, time.time()))
            self._log(connection, 'player', player_id, 'account-link', None,
                      f'{account_id}@{start}', 'manual', actor)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if update_current and not end and not game_match_key:
            self.map_account(account_id, player_id=player_id, seen_at=start, actor=actor)
        return {'linkId': link_id, 'accountId': account_id, 'playerId': player_id,
                'validFrom': start, 'validTo': end or None}

    def list_account_links(self, account_id=None, player_id=None, at_date=None,
                           game_match_key=None, include_undone=False):
        sql = 'SELECT * FROM account_player_links WHERE 1=1'
        params = []
        if account_id:
            sql += ' AND account_id=?'; params.append(str(account_id))
        if player_id:
            sql += ' AND player_id=?'; params.append(str(player_id))
        if game_match_key:
            sql += ' AND game_match_key=?'; params.append(str(game_match_key))
        if at_date:
            day = self._iso(at_date, '查询日期')
            sql += " AND valid_from<=? AND (valid_to IS NULL OR valid_to='' OR valid_to>=?)"
            params += [day, day]
        if not include_undone:
            sql += ' AND undone_at IS NULL'
        sql += ' ORDER BY valid_from DESC'
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]
        finally:
            connection.close()

    def resolve_player_at(self, account_id, *, at_date=None, game_match_key=None):
        """按「单局覆盖 → 时间化区间 → 当前映射」解析身份，供身份匹配与分析共用。"""
        account_id = str(account_id or '').strip()
        if not account_id:
            return None
        if game_match_key:
            row = self.list_account_links(account_id=account_id, game_match_key=game_match_key)
            if row:
                return self._resolved(row[0], 'game')
        day = self._iso(at_date, '查询日期') if at_date else None
        if day:
            # 单局覆盖不能参与按日期解析，否则一次身份纠错会污染整段时间。
            rows = [item for item in self.list_account_links(account_id=account_id, at_date=day)
                    if not item['game_match_key']]
            if rows:
                return self._resolved(rows[0], 'time')
        connection = self.connect()
        try:
            row = connection.execute(
                'SELECT player_id, nickname FROM player_accounts '
                "WHERE platform='camp' AND account_id=?", (account_id,)).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return {'playerId': row['player_id'], 'source': 'current', 'linkId': None,
                'nickname': row['nickname'], 'accountId': account_id}

    def _resolved(self, link, source):
        player = None
        connection = self.connect()
        try:
            row = connection.execute('SELECT id, name, team_id FROM players WHERE id=?',
                                     (link['player_id'],)).fetchone()
            if row:
                player = dict(row)
        finally:
            connection.close()
        return {'playerId': link['player_id'], 'source': source, 'linkId': link['link_id'],
                'validFrom': link['valid_from'], 'validTo': link['valid_to'],
                'gameMatchKey': link['game_match_key'], 'accountId': link['account_id'],
                'name': player['name'] if player else '', 'teamId': player['team_id'] if player else ''}

    def undo_account_link(self, link_id):
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM account_player_links WHERE link_id=? AND undone_at IS NULL',
                (str(link_id),)).fetchone()
            if row is None:
                raise ValueError('账号映射不存在或已撤销')
            connection.execute('UPDATE account_player_links SET undone_at=? WHERE link_id=?',
                               (time.time(), str(link_id)))
            if not row['valid_to'] and not row['game_match_key']:
                previous = connection.execute(
                    'SELECT player_id FROM account_player_links WHERE account_id=? AND link_id<>? '
                    "AND undone_at IS NULL AND (valid_to IS NULL OR valid_to='') "
                    'ORDER BY valid_from DESC LIMIT 1',
                    (row['account_id'], str(link_id))).fetchone()
                if previous:
                    connection.execute(
                        "UPDATE player_accounts SET player_id=? WHERE platform='camp' AND account_id=?",
                        (previous['player_id'], row['account_id']))
                else:
                    connection.execute(
                        "DELETE FROM player_accounts WHERE platform='camp' AND account_id=?",
                        (row['account_id'],))
            self._log(connection, 'player', row['player_id'], 'account-link:undo',
                      str(link_id), None, 'manual', 'coach')
            connection.commit()
            return {'linkId': str(link_id), 'undone': True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def batch_create_role_players(self, team_id, *, prefix=None, valid_from=None,
                                  relation_type='formal', actor='coach'):
        """对手一键建档：按五个分路生成可识别的本地选手 ID；已存在则复用。"""
        team_id = str(team_id or '')
        start = self._iso(valid_from, '生效日期') if valid_from else time.strftime('%Y-%m-%d')
        connection = self.connect()
        try:
            team = connection.execute('SELECT id, name FROM teams WHERE id=?', (team_id,)).fetchone()
        finally:
            connection.close()
        if team is None:
            raise ValueError('战队不存在')
        label = str(prefix or team['name'] or team_id).strip()
        result = []
        for lane in self.DEFAULT_LANES:
            name = f'{label}·{lane}'
            found = self.find_player(name, team_id=team_id)
            if found:
                player_id = found['id']
                created = False
            else:
                player_id = self.upsert_player(None, team_id=team_id, name=name,
                                               position=lane, actor=actor)
                created = True
            if not self.list_memberships(player_id=player_id, team_id=team_id, at_date=start):
                self.add_membership(player_id, team_id, valid_from=start,
                                    relation_type=relation_type, roster_role='starter', actor=actor,
                                    notes='一键生成分路 ID')
            result.append({'playerId': player_id, 'name': name, 'position': lane, 'created': created})
        return {'teamId': team_id, 'teamName': team['name'], 'players': result}

    def merge_players(self, from_player_id, to_player_id, *, actor='coach'):
        """人工合并重复身份：只搬映射与关系，历史出场记录不改写；可撤销。"""
        source, target = str(from_player_id), str(to_player_id)
        if source == target:
            raise ValueError('不能把选手合并到自己')
        connection = self.connect()
        merge_id = uuid.uuid4().hex[:16]
        try:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(
                'SELECT id, name, aliases, status, team_id FROM players WHERE id IN (?,?)',
                (source, target)).fetchall()
            by_id = {row['id']: dict(row) for row in rows}
            if source not in by_id or target not in by_id:
                raise ValueError('选手不存在')
            accounts = [row['id'] for row in connection.execute(
                'SELECT id FROM player_accounts WHERE player_id=?', (source,)).fetchall()]
            links = [row['link_id'] for row in connection.execute(
                'SELECT link_id FROM account_player_links WHERE player_id=? AND undone_at IS NULL',
                (source,)).fetchall()]
            memberships = [dict(row) for row in connection.execute(
                'SELECT membership_id, end_date, notes FROM player_team_history '
                'WHERE player_id=? AND undone_at IS NULL', (source,)).fetchall()]
            detail = {'sourceName': by_id[source]['name'], 'sourceAliases': by_id[source]['aliases'],
                      'sourceStatus': by_id[source]['status'], 'targetAliases': by_id[target]['aliases'],
                      'accounts': accounts, 'links': links, 'memberships': memberships,
                      'sourceTeamId': by_id[source]['team_id']}
            # 目标已有同一账号时删掉来源的快表行（时间化 link 仍保留可撤销）。
            for account_row in connection.execute(
                    'SELECT id, platform, account_id FROM player_accounts WHERE player_id=?',
                    (source,)).fetchall():
                clash = connection.execute(
                    'SELECT 1 FROM player_accounts WHERE platform=? AND account_id=? AND player_id<>?',
                    (account_row['platform'], account_row['account_id'], source)).fetchone()
                if clash:
                    connection.execute('DELETE FROM player_accounts WHERE id=?', (account_row['id'],))
                else:
                    connection.execute('UPDATE player_accounts SET player_id=? WHERE id=?',
                                       (target, account_row['id']))
            connection.execute('UPDATE account_player_links SET player_id=? WHERE player_id=?',
                               (target, source))
            connection.execute(
                "UPDATE player_team_history SET end_date=?, notes=COALESCE(notes,'')||? "
                'WHERE player_id=? AND undone_at IS NULL AND (end_date IS NULL OR end_date=\'\')',
                (time.strftime('%Y-%m-%d'), f' → 合并入 {target}', source))
            aliases = [by_id[source]['name'], source]
            try:
                current = json.loads(by_id[target]['aliases'] or '[]')
                if not isinstance(current, list):
                    current = []
            except (TypeError, ValueError):
                current = []
            merged = current + [item for item in aliases if item not in current]
            connection.execute('UPDATE players SET aliases=?, revision=revision+1 WHERE id=?',
                               (json.dumps(merged, ensure_ascii=False), target))
            connection.execute("UPDATE players SET status='archived', revision=revision+1 WHERE id=?",
                               (source,))
            connection.execute(
                'INSERT INTO identity_merge_logs(merge_id, from_player_id, to_player_id, status, '
                'detail, actor, created_at) VALUES(?,?,?,?,?,?,?)',
                (merge_id, source, target, 'applied',
                 json.dumps(detail, ensure_ascii=False), actor, time.time()))
            self._log(connection, 'player', source, 'mergedInto', None, target, 'merge', actor)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {'mergeId': merge_id, 'fromPlayerId': source, 'toPlayerId': target,
                'movedAccounts': len(detail['accounts']), 'movedLinks': len(detail['links'])}

    def undo_merge(self, merge_id):
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                "SELECT * FROM identity_merge_logs WHERE merge_id=? AND status='applied'",
                (str(merge_id),)).fetchone()
            if row is None:
                raise ValueError('合并记录不存在或已撤销')
            detail = json.loads(row['detail'] or '{}')
            source, target = row['from_player_id'], row['to_player_id']
            for account_id in detail.get('accounts', []):
                connection.execute('UPDATE player_accounts SET player_id=? WHERE id=?', (source, account_id))
            connection.execute('UPDATE account_player_links SET player_id=? WHERE player_id=?',
                               (source, target))
            for item in detail.get('memberships', []):
                connection.execute(
                    'UPDATE player_team_history SET end_date=?, notes=? WHERE membership_id=?',
                    (item.get('end_date'), item.get('notes'), item['membership_id']))
            connection.execute('UPDATE players SET aliases=?, status=?, revision=revision+1 WHERE id=?',
                               (detail.get('sourceAliases', '[]'), detail.get('sourceStatus', 'active'),
                                source))
            connection.execute('UPDATE players SET aliases=?, revision=revision+1 WHERE id=?',
                               (detail.get('targetAliases', '[]'), target))
            connection.execute('UPDATE identity_merge_logs SET status=?, undone_at=? WHERE merge_id=?',
                               ('undone', time.time(), str(merge_id)))
            self._log(connection, 'player', source, 'mergedInto:undo', target, None,
                      'merge', 'coach')
            connection.commit()
            return {'mergeId': str(merge_id), 'undone': True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def unfiled_series(self, limit=200):
        # 未归属赛事的系列赛（存量批量归属工具的数据源）。
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT * FROM training_series WHERE competition_id IS NULL '
                "ORDER BY COALESCE(start_at, '') DESC LIMIT ?", (int(limit),)).fetchall()
            result = []
            for row in rows:
                brief = self._series_brief(row)
                brief['games'] = self._series_games(connection, row['id'])
                result.append(brief)
            return result
        finally:
            connection.close()

    def archive_preview(self, competition_id):
        """赛季切换向导第一步：归档收尾检查 + 配置继承清单。"""
        competition = self.get_competition(competition_id)
        if not competition:
            raise ValueError('赛事不存在')
        unconfirmed = [item for item in self.list_series(competition=competition_id, limit=500)
                       if item.get('status') != 'confirmed']
        unfiled_matches = [row for row in self._all_match_rows()
                           if self._match_type(row) == self.TRAINING
                           and not self._mfield(row, 'competition_id')
                           and self._in_window(self._training_date(row),
                                               self._collect_bounds(competition))]
        return {'competition': competition,
                'unconfirmedSeries': [{'id': item['id'], 'opponent': item['opponent']}
                                      for item in unconfirmed],
                'unfiledMatches': len(unfiled_matches),
                'config': {'staff': competition.get('staff'),
                           'ownPlayerIds': competition.get('own_player_ids'),
                           'format': competition.get('format'),
                           'stage': competition.get('stage')}}

    def archive_and_inherit(self, competition_id, next_competition):
        """赛季切换向导第二步：归档旧赛事 + 创建新赛事并继承配置。"""
        from rules_effective import resolve_doc
        import json as _json
        competition = self.get_competition(competition_id)
        if not competition:
            raise ValueError('赛事不存在')
        if competition.get('status') == 'archived':
            raise ValueError('赛事已归档')
        next_name = str(next_competition.get('name') or '').strip()
        if not next_name:
            raise ValueError('新赛事必须有名称')
        new_id = self.save_competition(
            name=next_name, date=next_competition.get('date'),
            end_date=next_competition.get('end_date'),
            formal_from=next_competition.get('formalFrom'),
            formal_to=next_competition.get('formalTo'),
            stage=competition.get('stage'), format=competition.get('format'),
            status='planned', owner=competition.get('owner'),
            team_ids=None, head_coach=competition.get('head_coach'),
            assistant_coach=competition.get('assistant_coach'),
            data_analyst=competition.get('data_analyst'),
            staff=_json(competition.get('staff'), '[]') if False else None,
            own_player_ids=competition.get('own_player_ids'))
        # 规则中心条目复制：effective.eventId 换成新赛事
        try:
            facts = Path(bp_facts.FACTS)
            for file_name, list_key in (('rules_counters.json', None),):
                doc_path = facts / file_name
                if not doc_path.is_file():
                    continue
                doc = json.loads(doc_path.read_text(encoding='utf-8'))
                entries = (doc.get('heroPairs') or []) + (doc.get('comboPairs') or [])
                copied = 0
                for entry in entries:
                    eff = entry.get('effective') or {}
                    if str(eff.get('eventId') or '') == competition_id:
                        entry['id'] = entry['id'] + f"-{new_id}"
                        entry['effective'] = {**eff, 'eventId': new_id}
                        entry['revision'] = 0
                        copied += 1
                if copied:
                    doc['revision'] = int(doc.get('revision') or 0) + 1
                    doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
        except Exception:  # noqa: BLE001 - 复制失败不阻断归档
            pass
        self.save_competition(competition_id, name=competition.get('name'),
                              date=competition.get('date'),
                              end_date=competition.get('end_date'),
                              status='archived')
        return {'archived': competition_id, 'next': new_id}

    def bulk_assign_series(self, series_ids, competition_id):
        # 存量系列批量归属：逐个走 update_series 的校验口径（混编/冲突不掩盖）。
        assigned, failed = [], []
        for series_id in series_ids or []:
            try:
                self.update_series(series_id, competition_id=competition_id)
                assigned.append(series_id)
            except ValueError as error:
                failed.append({'seriesId': series_id, 'error': str(error)})
        return {'assigned': assigned, 'failed': failed}

    def save_formal_match(self, *, date, opponent=None, enemy_team_id=None, score=None,
                          winner=None, own_side=None, competition_id=None,
                          lineup=None, with_bp=False, source='manual', match_key=None):
        # 正式比赛数据录入（结果级 / 阵容级；BP 顺序级后续走 bp_overrides）。
        # - match_type='formal' 硬标记；competition_id 缺省按 formal 窗口匹配赛事；
        # - 去重：同对手 + 同日期 + 同比分指纹 → 返回已存在对局（营地同步优先）；
        # - 对手自动进对手库（teams.upsert_team）。
        if not date:
            raise ValueError('正赛必须有日期')
        opponent = str(opponent or '').strip()
        if not opponent and not enemy_team_id:
            raise ValueError('对手不能为空')
        if not enemy_team_id:
            # 对手库按名称去重：同名对手复用同一个建档，去重指纹才稳定。
            known = self.search_teams(opponent, limit=1)
            enemy_team_id = known[0]['id'] if known else self.upsert_team(name=opponent)
        candidates = (self.competition_formal_matches(competition_id, limit=None) if competition_id
                      else [row for row in self._all_match_rows()
                            if self._match_type(row) == self.FORMAL])
        score_text = str(score or '')
        for row in candidates:
            stored_score = str(row.get('score') or '')
            # upsert_match 会把 score JSON 序列化（"3:1" 带引号落库），比对前剥掉。
            if stored_score.startswith('"') and stored_score.endswith('"'):
                stored_score = stored_score[1:-1]
            if (str(row.get('enemy_team_id') or '') == str(enemy_team_id or '')
                    and str(row.get('date') or '') == str(date)
                    and stored_score == score_text):
                return {'matchKey': row.get('match_key'), 'dedup': True,
                        'competitionId': row.get('competition_id')}
        if not competition_id:
            for competition in self.list_competitions():
                if competition.get('status') == 'archived':
                    continue
                window = self._date_bounds(
                    competition.get('formal_from') or competition.get('date'),
                    competition.get('formal_to') or competition.get('end_date')
                    or competition.get('date'))
                if self._in_window(str(date), window):
                    competition_id = competition.get('id')
                    break
        if not competition_id:
            raise ValueError('没有可归属的赛事：先配置赛事的正式比赛范围，或显式选择赛事。')
        depth = 'bp' if with_bp else ('lineup' if lineup else 'result')
        notes = json.dumps({'formalEntry': {'depth': depth, 'lineup': lineup or []}},
                           ensure_ascii=False) if (lineup or with_bp) else ''
        match_key = match_key or 'm-formal-' + time.strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:4]
        self.upsert_match(match_key, date=date, competition_id=competition_id,
                          enemy_team_id=enemy_team_id, score=score, winner=winner,
                          own_side=own_side, match_type='formal', source=source,
                          notes=notes)
        return {'matchKey': match_key, 'dedup': False, 'depth': depth,
                'competitionId': competition_id}

    def pending_formal_entries(self, limit=50):
        """待补全的速记行：结果级/阵容级占位，等 official-entry 转正。"""
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM match_records WHERE match_type='formal' AND source='manual' "
                'AND formal_link IS NULL ORDER BY date DESC LIMIT ?', (int(limit),)).fetchall()
        finally:
            connection.close()
        result = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            try:
                entry = (json.loads(item.get('notes') or '') or {}).get('formalEntry') or {}
            except (TypeError, ValueError):
                entry = {}
            item['formalEntry'] = entry
            result.append(item)
        return result

    def link_formal_entry(self, entry_key, canonical_key):
        """速记占位转正：formal_link 指向正牌对局（bundle/channel），scope 让位。"""
        connection = self.connect()
        try:
            cursor = connection.execute(
                'UPDATE match_records SET formal_link=? '
                'WHERE match_key=? AND formal_link IS NULL',
                (canonical_key, entry_key))
            linked = cursor.rowcount > 0
            connection.commit()
        finally:
            connection.close()
        return linked

    def _window_competition_for(self, row):
        """对局按赛事卡片的训练起止落在哪个赛事；直连优先，窗口/手动兜底。

        系列赛编组此前只看直连列，导致「训练赛已归档到赛事、系列赛却没有赛事
        归属」，进而被大场/跨局页的当前赛事筛选整批排除。这里补齐同一口径。
        """
        direct = str(self._mfield(row, 'competition_id', '') or '').strip()
        if direct:
            return direct
        if self._mfield(row, 'in_trial', 0) or self._match_type(row) != self.TRAINING:
            return None
        key = str(self._mfield(row, 'match_key', '') or '').strip()
        date = self._training_date(row)
        candidates = []
        for comp in self.list_competitions():
            if key in self._competition_manual_keys(comp) or self._in_window(date, self._collect_bounds(comp)):
                candidates.append(comp)
        # 多个窗口重叠时取起始日最近（最具体）的赛事，保证结果稳定。
        candidates.sort(key=lambda c: str(c.get('date') or ''), reverse=True)
        return candidates[0]['id'] if candidates else None

    def _match_competitions(self, connection, keys):
        # 对局键 → 赛事集合；直连列 + 训练起止/手动挂载，供编组推导赛事归属。
        comps = set()
        for table in self._series_relation_tables(connection):
            try:
                cols = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            except sqlite3.Error:
                continue
            if 'competition_id' not in cols or 'match_key' not in cols:
                continue
            for key in keys:
                try:
                    row = connection.execute(
                        f'SELECT competition_id FROM {table} WHERE match_key=?', (key,)).fetchone()
                except sqlite3.Error:
                    row = None
                if row and row['competition_id']:
                    comps.add(str(row['competition_id']))
        for key in keys:
            try:
                row = connection.execute(
                    'SELECT * FROM match_records WHERE match_key=?', (key,)).fetchone()
            except sqlite3.Error:
                row = None
            if not row:
                continue
            item = {col: row[col] for col in row.keys()}
            comp = self._window_competition_for(item)
            if comp:
                comps.add(comp)
        return comps

    def competition_formal_matches(self, competition_id, limit=None):
        """赛事正式比赛范围：formal_from~formal_to（缺省回退训练起止）+ 类型为 formal。"""
        competition = self.get_competition(competition_id)
        if not competition:
            return []
        window = self._date_bounds(
            competition.get('formal_from') or competition.get('date'),
            competition.get('formal_to') or competition.get('end_date') or competition.get('date'))
        manual = self._competition_manual_keys(competition)
        result = []
        for row in self._all_match_rows():
            if self._mfield(row, 'in_trial', 0) or self._match_type(row) != self.FORMAL:
                continue
            key = str(self._mfield(row, 'match_key', '') or '')
            direct_id = str(self._mfield(row, 'competition_id', '') or '')
            direct = direct_id == competition_id
            # 赛事域 P0：与训练赛口径同一条排除规则。
            if direct_id and not direct:
                continue
            # 双通道统一：已被 official-entry 转正的速记占位行，让位给正牌对局。
            if str(self._mfield(row, 'formal_link', '') or ''):
                continue
            mounted = key in manual
            if not (direct or mounted or self._in_window(
                    str(self._mfield(row, 'date', '') or '').strip(), window)):
                continue
            result.append(self._aggregated_item(
                row, 'direct' if direct else ('manual' if mounted else 'window')))
        result.sort(key=lambda item: (str(item.get('date') or ''), str(item.get('match_key') or '')))
        return self._limit(result, limit)

    def unfiled_training_matches(self, limit=None):
        """未归档训练赛：训练日期不在任何赛事训练起止内、也未被手动挂载。"""
        rows = self._all_match_rows()
        covered = set()
        for competition in self.list_competitions():
            window = self._collect_bounds(competition)
            manual = self._competition_manual_keys(competition)
            for row in rows:
                if self._mfield(row, 'in_trial', 0) or self._match_type(row) != self.TRAINING:
                    continue
                key = str(self._mfield(row, 'match_key', '') or '')
                if (str(self._mfield(row, 'competition_id', '') or '') == competition['id']
                        or key in manual
                        or self._in_window(self._training_date(row), window)):
                    covered.add(key)
        result = [self._aggregated_item(row, 'unfiled') for row in rows
                  if not self._mfield(row, 'in_trial', 0)
                  and self._match_type(row) == self.TRAINING
                  and str(self._mfield(row, 'match_key', '') or '') not in covered]
        result.sort(key=lambda item: (item['recordedDate'], str(item.get('match_key') or '')))
        return self._limit(result, limit)

    def overlapping_competitions(self, start, end, exclude_id=None):
        """时间窗口重叠检查（训练起止 / 正式比赛范围任一重叠即算），仅供提示。"""
        target = self._date_bounds(start, end)
        if not target:
            return []
        result = []
        for competition in self.list_competitions():
            if exclude_id and competition.get('id') == exclude_id:
                continue
            for label, bounds in (
                ('training', self._collect_bounds(competition)),
                ('formal', self._date_bounds(competition.get('formal_from'), competition.get('formal_to'))),
            ):
                if bounds and target[0] <= bounds[1] and bounds[0] <= target[1]:
                    result.append({'id': competition['id'], 'name': competition['name'],
                                   'window': label, 'start': bounds[0], 'end': bounds[1]})
                    break
        return result

    # ---------------------------------------------------------------- 系列赛（V2.0）
    # 设计约束（docs/series_builder.md）：系列赛是独立于单局的关系实体；
    # 确认编组只写关系列（series_id/game_no），原始对局数据一律不动。
    SERIES_BEST_OF = (3, 5, 7)
    SERIES_STATUSES = ('confirmed', 'needs_review')
    SERIES_COMPLETION_MODES = ('standard', 'fixed')
    SERIES_COMPLETIONS = ('completed', 'open', 'interrupted', 'incomplete')

    @staticmethod
    def _series_brief(row):
        """training_series 行 → 对外 JSON（camelCase，与前端字段一致）。"""
        try:
            competition_id = row['competition_id'] if 'competition_id' in row.keys() else None
        except (TypeError, ValueError):
            competition_id = None
        return {
            'id': row['id'], 'bestOf': row['best_of'], 'status': row['status'],
            'competitionId': competition_id,
            'rulesetId': row['ruleset_id'], 'opponent': row['opponent'],
            'opponentTeamId': row['opponent_team_id'], 'session': row['session'],
            'scheduleId': row['schedule_id'], 'version': row['version'],
            'startAt': row['start_at'], 'endAt': row['end_at'],
            'completionMode': row['completion_mode'], 'completion': row['completion'],
            'notes': row['notes'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
        }

    @staticmethod
    def _series_games(connection, series_id):
        rows = connection.execute(
            'SELECT match_key, game_index FROM training_series_games WHERE series_id=? '
            'ORDER BY game_index', (series_id,)).fetchall()
        return [{'matchKey': row['match_key'], 'gameIndex': row['game_index']} for row in rows]

    @staticmethod
    def _normalize_games(games):
        """['key',...] / [{'matchKey','gameIndex'?}] → 按 game_index 排列的 [(key, index)]。

        没给局序就按传入顺序编 G1..Gn；给了就必须恰好是连续 1..n——中间缺号
        意味着采集缺局，要教练先补齐或改自动编排，不静默补号冒充完整 BO。"""
        normalized = []
        for item in games or []:
            if isinstance(item, str):
                normalized.append((item.strip(), None))
            elif isinstance(item, dict):
                key = str(item.get('matchKey') or item.get('key') or '').strip()
                if not key:
                    raise ValueError('局次缺少 matchKey')
                index = item.get('gameIndex')
                normalized.append((key, int(index) if index else None))
            else:
                raise ValueError('局次格式不正确')
        if not normalized:
            raise ValueError('系列赛至少需要一局对局')
        keys = [key for key, _ in normalized]
        if len(set(keys)) != len(keys):
            raise ValueError('同一局不能在一次编组里出现两次')
        explicit = [(key, index) for key, index in normalized if index is not None]
        if explicit and len(explicit) != len(normalized):
            raise ValueError('局序要么全部指定，要么全部自动编排，不能混用')
        if explicit:
            if sorted(index for _, index in explicit) != list(range(1, len(normalized) + 1)):
                raise ValueError('局序必须是连续的 G1..Gn，缺号请先补齐或改为自动编排')
            return normalized
        return [(key, index) for index, (key, _) in enumerate(normalized, 1)]

    def _check_membership(self, connection, keys, *, exclude_series=None):
        """一局只能归属一个系列赛；冲突带出占用清单，接口转 409。"""
        occupied = []
        for key in keys:
            row = connection.execute(
                'SELECT match_key, series_id FROM training_series_games WHERE match_key=?',
                (key,)).fetchone()
            if row and row['series_id'] != exclude_series:
                occupied.append((row['match_key'], row['series_id']))
        if occupied:
            raise SeriesConflict(occupied)
        return occupied

    @staticmethod
    def _series_relation_tables(connection):
        """能写 series_id/game_no 的表：必须有 match_key + series_id 列。

        部分老库的 matches 是存 JSON body 的旧表（id/revision/body，无
        match_key），建表语句会被跳过——这类表不参与关系写回，也不改其结构。"""
        usable = []
        for table in ('match_records', 'matches'):
            try:
                cols = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            except sqlite3.Error:
                continue
            if 'match_key' in cols and 'series_id' in cols:
                usable.append(table)
        return usable

    @staticmethod
    def _match_dates(connection, keys):
        """从可用关系表取对局日期，用于系列赛起止兜底。"""
        dates = []
        tables = Workspace._series_relation_tables(connection) or ['match_records']
        for key in keys:
            for table in tables:
                try:
                    row = connection.execute(
                        f'SELECT date FROM {table} WHERE match_key=?', (key,)).fetchone()
                except sqlite3.Error:
                    row = None
                if row and row['date']:
                    dates.append(str(row['date']))
                    break
        return sorted(dates)

    def _sync_match_series(self, connection, assignments, cleared=()):
        """确认编组后把 series_id/game_no 写回 match_records 与 matches 的既有列
        （旧查询兼容）；移出的局置回 NULL。只改关系列，不 bump revision：
        对局内容没变，关系变化已由 change_log 记录。表按实际结构动态判断。"""
        for table in self._series_relation_tables(connection):
            for key, (series_id, game_no) in assignments.items():
                connection.execute(
                    f'UPDATE {table} SET series_id=?, game_no=? WHERE match_key=?',
                    (series_id, game_no, key))
            for key in cleared:
                connection.execute(
                    f'UPDATE {table} SET series_id=NULL, game_no=NULL WHERE match_key=?', (key,))

    def create_series(self, *, best_of, games, ruleset_id=None, opponent=None,
                      opponent_team_id=None, session=None, schedule_id=None, version=None,
                      completion_mode=None, completion=None, status=None, notes=None,
                      start_at=None, end_at=None, series_id=None, competition_id=None,
                      actor=None):
        """创建并确认一个系列赛。games 全量校验后一次写入；支持显式传
        series_id（撤销删除时按原 ID 重建）。"""
        from series_engine import RULESETS  # 规则集注册表在引擎里，延迟导入避免加载静态大表
        if int(best_of) not in self.SERIES_BEST_OF:
            raise ValueError('赛制只支持 BO3 / BO5 / BO7')
        if games and len(games) > int(best_of):
            raise ValueError(f'BO{int(best_of)} 最多 {int(best_of)} 局，当前给了 {len(games)} 局')
        if ruleset_id and ruleset_id not in RULESETS:
            raise ValueError(f'未知规则集：{ruleset_id}')
        if completion_mode and completion_mode not in self.SERIES_COMPLETION_MODES:
            raise ValueError(f'未知执行方式：{completion_mode}')
        if completion and completion not in self.SERIES_COMPLETIONS:
            raise ValueError(f'未知完赛状态：{completion}')
        if status and status not in self.SERIES_STATUSES:
            raise ValueError(f'未知系列赛状态：{status}')
        ordered = self._normalize_games(games)
        connection = self.connect()
        batch_id = uuid.uuid4().hex[:12]
        try:
            self._check_membership(connection, [key for key, _ in ordered])
            # 赛事域（M1）：一个系列只归一个赛事。归属优先取所选对局的直连赛事，
            # 混编（对局分属不同赛事）直接报错，不允许靠猜。
            comp_ids = self._match_competitions(connection, [key for key, _ in ordered])
            if len(comp_ids) > 1:
                raise ValueError('所选对局分属不同赛事，请先统一归属再编组。')
            if competition_id and comp_ids and competition_id not in comp_ids:
                raise ValueError('所选对局已归属其他赛事，无法编入该赛事。')
            competition_id = competition_id or (next(iter(comp_ids)) if comp_ids else None)
            now = time.time()
            series_id = series_id or 'ts-' + time.strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:4]
            if connection.execute('SELECT 1 FROM training_series WHERE id=?', (series_id,)).fetchone():
                raise ValueError(f'系列赛 ID 已存在：{series_id}')
            if not start_at or not end_at:
                dates = self._match_dates(connection, [key for key, _ in ordered])
                start_at = start_at or (dates[0] if dates else None)
                end_at = end_at or (dates[-1] if dates else None)
            connection.execute(
                'INSERT INTO training_series(id, best_of, status, ruleset_id, opponent, '
                'opponent_team_id, session, schedule_id, version, start_at, end_at, '
                'completion_mode, completion, notes, competition_id, created_at, updated_at, updated_by) '
                'VALUES(?,?,COALESCE(?,\'confirmed\'),COALESCE(?,\'scrim-global-team\'),'
                '?,?,?,?,?,?,?,COALESCE(?,\'standard\'),COALESCE(?,\'open\'),?,?,?,?,?)',
                (series_id, int(best_of), status, ruleset_id, opponent, opponent_team_id,
                 session, schedule_id, version, start_at, end_at, completion_mode, completion,
                 notes, competition_id, now, now, actor))
            for key, index in ordered:
                connection.execute(
                    'INSERT INTO training_series_games(series_id, match_key, game_index, created_at) '
                    'VALUES(?,?,?,?)', (series_id, key, index, now))
            assignments = {key: (series_id, index) for key, index in ordered}
            self._sync_match_series(connection, assignments)
            self._log(connection, 'series', series_id, 'games', None,
                      json.dumps([{'matchKey': key, 'gameIndex': index} for key, index in ordered],
                                 ensure_ascii=False),
                      'series-builder', actor=actor, batch_id=batch_id)
            for key, index in ordered:
                self._log(connection, 'match', key, 'series_id', None,
                          f'{series_id}#G{index}', 'series-builder', actor=actor, batch_id=batch_id)
            connection.commit()
        finally:
            connection.close()
        return self.get_series(series_id)

    def update_series(self, series_id, *, best_of=None, games=None, ruleset_id=None,
                      opponent=None, opponent_team_id=None, session=None, schedule_id=None,
                      version=None, completion_mode=None, completion=None, status=None,
                      notes=None, competition_id=None, actor=None):
        """修改赛制/局序/成员/标注。games 传了就全量替换（调序、增删、拆分、
        合并都走这一条）；opponent 等 None 表示「本次不改」。"""
        from series_engine import RULESETS
        current = self.get_series(series_id)
        if not current:
            raise ValueError(f'系列赛不存在：{series_id}')
        best_of = int(best_of) if best_of is not None else current['bestOf']
        if best_of not in self.SERIES_BEST_OF:
            raise ValueError('赛制只支持 BO3 / BO5 / BO7')
        if ruleset_id and ruleset_id not in RULESETS:
            raise ValueError(f'未知规则集：{ruleset_id}')
        if completion_mode and completion_mode not in self.SERIES_COMPLETION_MODES:
            raise ValueError(f'未知执行方式：{completion_mode}')
        if completion and completion not in self.SERIES_COMPLETIONS:
            raise ValueError(f'未知完赛状态：{completion}')
        if status and status not in self.SERIES_STATUSES:
            raise ValueError(f'未知系列赛状态：{status}')
        connection = self.connect()
        batch_id = uuid.uuid4().hex[:12]
        try:
            old_games = [(g['matchKey'], g['gameIndex']) for g in current['games']]
            replaced = self._normalize_games(games) if games is not None else None
            if replaced is not None and len(replaced) > best_of:
                raise ValueError(f'BO{best_of} 最多 {best_of} 局，当前给了 {len(replaced)} 局')
            keys = [key for key, _ in (replaced or old_games)]
            self._check_membership(connection, keys, exclude_series=series_id)
            new_competition = None
            if replaced is not None:
                # 赛事域（M1）：换局后按新对局重推赛事归属，混编报错。
                comp_ids = self._match_competitions(connection, [key for key, _ in replaced])
                if len(comp_ids) > 1:
                    raise ValueError('所选对局分属不同赛事，请先统一归属再编组。')
                if competition_id and comp_ids and competition_id not in comp_ids:
                    raise ValueError('所选对局已归属其他赛事，无法编入该赛事。')
                new_competition = competition_id or (next(iter(comp_ids)) if comp_ids else None)
            elif competition_id is not None:
                comp_ids = self._match_competitions(connection, keys)
                if comp_ids and competition_id not in comp_ids:
                    raise ValueError('系列赛现有对局已归属其他赛事，无法改归属。')
            fields, params = [], []
            for column, value in (
                    ('best_of', best_of), ('ruleset_id', ruleset_id), ('opponent', opponent),
                    ('opponent_team_id', opponent_team_id), ('session', session),
                    ('schedule_id', schedule_id), ('version', version),
                    ('completion_mode', completion_mode), ('completion', completion),
                    ('status', status), ('notes', notes)):
                if value is not None:
                    fields.append(f'{column}=?')
                    params.append(value)
            if replaced is not None:
                fields.append('competition_id=?')
                params.append(new_competition)
            elif competition_id is not None:
                fields.append('competition_id=?')
                params.append(competition_id)
            fields.append('updated_at=?')
            params.append(time.time())
            params.append(series_id)
            connection.execute(
                f'UPDATE training_series SET {", ".join(fields)} WHERE id=?', params)
            cleared = []
            assignments = {key: (series_id, index) for key, index in (replaced or old_games)}
            if replaced is not None:
                connection.execute('DELETE FROM training_series_games WHERE series_id=?', (series_id,))
                now = time.time()
                for key, index in replaced:
                    connection.execute(
                        'INSERT INTO training_series_games(series_id, match_key, game_index, created_at) '
                        'VALUES(?,?,?,?)', (series_id, key, index, now))
                new_keys = {key for key, _ in replaced}
                cleared = [key for key, _ in old_games if key not in new_keys]
                self._log(connection, 'series', series_id, 'games',
                          json.dumps([{'matchKey': k, 'gameIndex': i} for k, i in old_games],
                                     ensure_ascii=False),
                          json.dumps([{'matchKey': k, 'gameIndex': i} for k, i in replaced],
                                     ensure_ascii=False),
                          'series-builder', actor=actor, batch_id=batch_id)
                self._sync_match_series(connection, assignments, cleared)
                for key in cleared:
                    self._log(connection, 'match', key, 'series_id', f'{series_id}', None,
                              'series-builder', actor=actor, batch_id=batch_id)
                for key, index in replaced:
                    if (key, index) not in old_games:
                        self._log(connection, 'match', key, 'series_id', None,
                                  f'{series_id}#G{index}', 'series-builder',
                                  actor=actor, batch_id=batch_id)
            else:
                self._log(connection, 'series', series_id, 'updated', None, None,
                          'series-builder', actor=actor, batch_id=batch_id)
            connection.commit()
        finally:
            connection.close()
        return self.get_series(series_id)

    def delete_series(self, series_id, *, actor=None):
        """删除编组关系，保留全部原始对局；返回被释放的 match_key 列表。"""
        current = self.get_series(series_id)
        if not current:
            raise ValueError(f'系列赛不存在：{series_id}')
        connection = self.connect()
        batch_id = uuid.uuid4().hex[:12]
        try:
            keys = [g['matchKey'] for g in current['games']]
            connection.execute('DELETE FROM training_series_games WHERE series_id=?', (series_id,))
            connection.execute('DELETE FROM training_series WHERE id=?', (series_id,))
            self._sync_match_series(connection, {}, cleared=keys)
            self._log(connection, 'series', series_id, 'deleted',
                      json.dumps(current['games'], ensure_ascii=False), None,
                      'series-builder', actor=actor, batch_id=batch_id)
            for key in keys:
                self._log(connection, 'match', key, 'series_id', f'{series_id}', None,
                          'series-builder', actor=actor, batch_id=batch_id)
            connection.commit()
        finally:
            connection.close()
        return keys

    def get_series(self, series_id):
        connection = self.connect()
        try:
            row = connection.execute(
                'SELECT * FROM training_series WHERE id=?', (series_id,)).fetchone()
            if not row:
                return None
            brief = self._series_brief(row)
            brief['games'] = self._series_games(connection, series_id)
            return brief
        finally:
            connection.close()

    def list_series(self, *, date_from=None, date_to=None, session=None, opponent=None,
                    best_of=None, status=None, completion=None, competition=None, limit=500):
        """按筛选条件列系列赛；系列赛级指标一律按 start_at（开赛日）归档，
        防止一组 BO 被时间窗口切成两半。"""
        where, params = [], []
        if date_from:
            where.append('COALESCE(end_at, start_at) >= ?')
            params.append(str(date_from))
        if date_to:
            where.append('COALESCE(start_at, end_at) <= ?')
            params.append(str(date_to))
        if session:
            where.append('session = ?')
            params.append(session)
        if opponent:
            where.append('opponent LIKE ?')
            params.append(f'%{opponent}%')
        if best_of:
            where.append('best_of = ?')
            params.append(int(best_of))
        if status:
            where.append('status = ?')
            params.append(status)
        if completion:
            where.append('completion = ?')
            params.append(completion)
        connection = self.connect()
        try:
            if competition:
                # 赛事域：直连归属的组 + 开赛日落在本赛事窗口、且无归属的组。
                # 后者是营地采集对局没在权威表登记时编组的兜底：当时 create_series
                # 推不出赛事，系列赛 competition_id 为空，会被整组排除在大场/跨场
                # 之外（赛训组反馈「编组了但分析页没有」的第二个漏点）。这里只读
                # 按窗口判定，不改库、不产生写副作用。
                extra = []
                comp = self.get_competition(competition)
                if comp:
                    bounds = self._collect_bounds(comp)
                    for row in connection.execute(
                            "SELECT id, competition_id, start_at FROM training_series "
                            "WHERE competition_id IS NULL OR competition_id = ''"):
                        start = str(row['start_at'] or '').strip()
                        if not start or not self._in_window(start, bounds):
                            continue
                        if self._window_competition_for({'date': start}) == competition:
                            extra.append(str(row['id']))
                if extra:
                    marks = ','.join('?' for _ in extra)
                    where.append(f"(competition_id = ? OR id IN ({marks}))")
                    params.append(competition)
                    params.extend(extra)
                else:
                    where.append('competition_id = ?')
                    params.append(competition)
            sql = 'SELECT * FROM training_series'
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY COALESCE(start_at, \'\') DESC, id DESC LIMIT ?'
            params.append(int(limit))
            # 赛事域（P2-1）：GET 不再有写副作用；归属回填在写路径
            # （create/update/bulk_assign）与赛事页归属工具完成。
            rows = connection.execute(sql, params).fetchall()
            result = []
            for row in rows:
                brief = self._series_brief(row)
                brief['games'] = self._series_games(connection, row['id'])
                result.append(brief)
            return result
        finally:
            connection.close()

    def series_index(self):
        """match_key → {seriesId, bestOf, gameIndex, seriesStart} 一次查全。

        跨局分析按赛制 / 局序筛选时要给每局贴上系列赛属性；逐 key 查会变成
        N+1（几百局就是几百次查询），这里一次 JOIN 拿完。
        """
        connection = self.connect()
        try:
            rows = connection.execute(
                'SELECT g.match_key, g.game_index, s.id AS series_id, s.best_of, s.start_at '
                'FROM training_series_games g JOIN training_series s ON s.id = g.series_id'
            ).fetchall()
        finally:
            connection.close()
        return {
            str(row['match_key']): {
                'seriesId': row['series_id'],
                'bestOf': row['best_of'],
                'gameIndex': row['game_index'],
                'seriesStart': row['start_at'],
            }
            for row in rows
        }

    def series_for_matches(self, match_keys):
        """match_key → {seriesId, gameIndex}；编组页标红冲突局、跨局分析
        反查所属系列赛都用它。"""
        keys = [str(key) for key in match_keys or []]
        mapping = {}
        if not keys:
            return mapping
        connection = self.connect()
        try:
            for key in keys:
                row = connection.execute(
                    'SELECT series_id, game_index FROM training_series_games WHERE match_key=?',
                    (key,)).fetchone()
                if row:
                    mapping[key] = {'seriesId': row['series_id'], 'gameIndex': row['game_index']}
            return mapping
        finally:
            connection.close()


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
                         stage=None, format=None, status=None, owner=None, notes=None,
                         end_date=None, team_ids=None, head_coach=None, assistant_coach=None,
                         data_analyst=None, staff=None, own_player_ids=None, key_match_keys=None,
                         formal_from=None, formal_to=None, collect_from=None, collect_to=None):
        """写入/合并比赛。status 传 None 表示保留原状态，不重置回 planned。

        列表/集合字段（team_ids/staff/own_player_ids/key_match_keys）以 JSON 字符串落库；
        传 None 表示保留原值（兼容旧调用方与局部更新）。

        双时间口径（新增字段全部可选，旧库/旧调用方不受影响）：
          date/end_date        训练起止（赛事卡片「训练起始 / 训练结束」，按训练日期比对）；
                               collect_from/collect_to 为其别名；
          formal_from/formal_to 正式比赛起止。传 None 保留原值，传 '' 清空。
        """
        name = str(name or '').strip()
        if not name:
            raise ValueError('比赛必须有名称')
        if collect_from is not None:
            date = collect_from
        if collect_to is not None:
            end_date = collect_to
        if not date:
            raise ValueError('比赛必须有日期')
        competition_id = competition_id or 'comp-' + uuid.uuid4().hex[:10]
        def pack(value, default='[]'):
            if value is None:
                return default
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)
        team_ids = pack(team_ids)
        staff = pack(staff)
        own_player_ids = pack(own_player_ids)
        key_match_keys = pack(key_match_keys)
        connection = self.connect()
        try:
            # 赛事生命周期（P2-2）：archived 只读——除非本次明确重开
            #（status 改回 planned/ongoing），其余编辑一律拒绝。
            existing = connection.execute(
                'SELECT status FROM competitions WHERE id=?', (competition_id,)).fetchone()
            if existing and existing[0] == 'archived' and status not in ('planned', 'ongoing'):
                raise ValueError('赛事已归档（只读）：先在状态里改回「筹备中/进行中」再编辑。')
            connection.execute(
                'INSERT INTO competitions(id, name, date, end_date, formal_from, formal_to, '
                'opponent_team_id, team_ids, '
                'head_coach, assistant_coach, data_analyst, staff, own_player_ids, key_match_keys, '
                'stage, format, status, owner, notes, created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,\'planned\'),?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET name=excluded.name, date=excluded.date, '
                'end_date=COALESCE(excluded.end_date, competitions.end_date), '
                'formal_from=COALESCE(excluded.formal_from, competitions.formal_from), '
                'formal_to=COALESCE(excluded.formal_to, competitions.formal_to), '
                'opponent_team_id=excluded.opponent_team_id, team_ids=COALESCE(excluded.team_ids, competitions.team_ids), '
                'head_coach=COALESCE(excluded.head_coach, competitions.head_coach), '
                'assistant_coach=COALESCE(excluded.assistant_coach, competitions.assistant_coach), '
                'data_analyst=COALESCE(excluded.data_analyst, competitions.data_analyst), '
                'staff=COALESCE(excluded.staff, competitions.staff), '
                'own_player_ids=COALESCE(excluded.own_player_ids, competitions.own_player_ids), '
                'key_match_keys=COALESCE(excluded.key_match_keys, competitions.key_match_keys), '
                'stage=excluded.stage, format=excluded.format, '
                'status=COALESCE(?,competitions.status), owner=excluded.owner, '
                'notes=excluded.notes, updated_at=?, revision=competitions.revision+1',
                (competition_id, name, date, end_date, formal_from, formal_to,
                 opponent_team_id, team_ids,
                 head_coach, assistant_coach, data_analyst, staff, own_player_ids, key_match_keys,
                 stage, format, status, owner, notes, time.time(), status, time.time()))
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

    def delete_competition(self, competition_id):
        """删除比赛本体；训练课/对局仅解除归属，不删除记录本身。"""
        connection = self.connect()
        try:
            connection.execute('UPDATE schedules SET competition_id=NULL WHERE competition_id=?',
                               (competition_id,))
            # 尽力解绑对局（两张表结构可能不同，逐表按存在列处理）。
            for table in ('match_records', 'matches'):
                cols = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
                if 'competition_id' in cols:
                    connection.execute(
                        f'UPDATE {table} SET competition_id=NULL WHERE competition_id=?',
                        (competition_id,))
            connection.execute('DELETE FROM competitions WHERE id=?', (competition_id,))
            connection.commit()
            return connection.total_changes > 0
        finally:
            connection.close()

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
        # 优先直连归属（match_records.competition_id）；老数据仍走训练课启发式兜底。
        try:
            direct = self.connect()
            direct_rows = direct.execute(
                'SELECT match_key FROM match_records WHERE competition_id=? '
                'ORDER BY date, match_key', (competition_id,)).fetchall()
            direct.close()
            for row in direct_rows:
                key = row[0]
                if key in seen:
                    continue
                seen.add(key)
                matches.append({'match_key': key, 'competitionDirect': True})
        except sqlite3.Error:
            pass
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
                'SELECT match_key,date,session,enemy_team_id,own_side,winner,score,duration,status,'
                'excluded_at,excluded_reason '
                'FROM match_records ORDER BY date DESC, match_key LIMIT ?', (max(1, min(500, limit)),)).fetchall()
            meta = {}
            try:
                meta_rows = connection.execute('SELECT match_key,body FROM match_meta').fetchall()
            except sqlite3.OperationalError:
                meta_rows = []
            for key, body in meta_rows:
                try:
                    value = json.loads(body or '{}')
                except (TypeError, ValueError):
                    value = {}
                if isinstance(value, dict):
                    meta[key] = value
            team_names = {}
            try:
                team_names = {str(row[0]): str(row[1] or '').strip()
                              for row in connection.execute('SELECT id, name FROM teams')}
            except sqlite3.Error:
                team_names = {}
        finally:
            connection.close()
        out = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            extra = meta.get(item.get('match_key') or '') or {}
            item['opponent'] = str(extra.get('opponent') or '').strip()
            if not item.get('enemy_team_id'):
                item['enemy_team_id'] = str(extra.get('opponentTeamId') or '').strip() or None
            # 匹配页确认过 enemy_team_id 后，队名由战队主数据统一给出；
            # match_meta 里没写自由文本时这里不能再留空，否则别处显示「对手未标注」。
            enemy_id = str(item.get('enemy_team_id') or '').strip()
            if enemy_id and team_names.get(enemy_id):
                item['opponent'] = team_names[enemy_id]
            out.append(item)
        return out

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
