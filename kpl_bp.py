"""KPL 官方赛事 BP 抓取 → 本地事实表（自建管线，替代外部离线数据包）。

三层职责，互不越界：

* 抓取：KPL 官方公开接口（赛季列表 / 赛程 / 小局列表 / 单局快照），keep-alive 串行，
  单局失败指数退避重试，仍失败就跳过并计入 manifest，绝不整轮崩。
* 落盘：`data/kpl/bp_games.jsonl`（一行一局、按 battleId 追加式去重，临时文件 + 原子替换）、
  `data/kpl/manifest.json`（窗口 / 赛季 / 错误统计）。
* 聚合：`data/facts/kpl_combos.json`（同队同场 5 个 pick 的两两 / 三三 / 整阵容组合的
  场次与胜率），供 `bp_facts.py` 的「赛事命中」消费。

组合口径与旧版 `scripts/build_bp_facts.py --kpl <外部jsonl>` 保持一致：
同队同场 pick 先按英雄名去重（排序）再组合；`n`=出现局数，`wins`=这些局的胜局，
`wr`=wins/n*100 保留 1 位，`year`=该组合最近出现的年份；`minGames` 只卡双人 / 三人，
整阵容（lineups）出现过 1 次就保留。`teams` 按 pick 方队伍聚合、按 n 倒序最多 5 支。

接口语义（2026-11 实测 + `battle_player_list` 十人交叉校验）：
`bp_list[].is_ban_or_pick == 1` 是**选用（pick）**，`== 0` 是**禁用（ban）**，顺序即 BP 顺序。
契约文档第一版曾把这两个值写反，代码以实测为准。

BP 完整性（契约 v1.1，见 `docs/kpl_bp_pipeline.md` §1）：
* `bpMode="full"`：`bp_list` 完整（两侧各 5 pick + 同数 ban），picks 用 BP 顺序，bans 可用；
* `bpMode="blind"`：**巅峰对决盲选**——系列赛打满的最后一局按规则盲选，官方 `bp_list` 为空或不完整，
  这不是数据缺失。picks 取十人面板，`bansKnown=false`、`pickOrderKnown=false`，照常进组合统计；
* `bpMode="partial"`：非巅峰对决但 `bp_list` 缺失/不全，picks 同样由十人面板兜底；
* 只有十人面板都不全（不足 10 人 / 两侧各不足 5 人）才记 `invalid`，整局丢弃。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA_KPL = ROOT / 'data' / 'kpl'
GAMES_PATH = DATA_KPL / 'bp_games.jsonl'
MANIFEST_PATH = DATA_KPL / 'manifest.json'
FACTS_PATH = ROOT / 'data' / 'facts' / 'kpl_combos.json'

API_BASE = 'https://prod.comp.smoba.qq.com/leaguesite'
URL_LEAGUES = API_BASE + '/leagues/open'
URL_MATCHES = API_BASE + '/matches/open'
URL_MATCH_BATTLES = API_BASE + '/match/battles/open'
URL_BATTLE = API_BASE + '/battle/open'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
HEADERS = {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://pvp.qq.com/',
}

SCHEMA_GAME = 'kpl-bp-game-v1'
SCHEMA_MANIFEST = 'kpl-bp-manifest-v1'
SCHEMA_COMBOS = 'bp-kpl-combos-v1'
SOURCE_LABEL = 'KPL 官方赛事'
SOURCE = 'kpl-official'

BP_MODE_FULL = 'full'
BP_MODE_BLIND = 'blind'
BP_MODE_PARTIAL = 'partial'
BP_MODES = (BP_MODE_FULL, BP_MODE_BLIND, BP_MODE_PARTIAL)

# 十人面板兜底时的英雄顺序：按分路排（盲选局没有选人顺序，用分路顺序保证确定性）
LANE_ORDER = ('对抗路', '打野', '中路', '发育路', '游走')

DEFAULT_SINCE_YEAR = 2024
DEFAULT_MIN_GAMES = 3
DEFAULT_SLEEP = 0.1
MAX_TEAMS = 5
RETRY_ATTEMPTS = 4          # 单次请求最多尝试次数（首次 + 3 次指数退避重试）
RETRY_BACKOFF = 1.0         # 首次退避秒数，之后 2x
REQUEST_TIMEOUT = 20
FLUSH_EVERY = 200           # 每抓多少局把缓冲落一次盘（中断最多丢一批）
PICK_FLAG = 1               # is_ban_or_pick == 1 是选用（实测，见模块 docstring）
MIN_BANS_PER_SIDE = 4       # 2024+ 赛季每边至少 4 ban（2024 是 4 ban/边，2025+ 是 5 ban/边）

COMBOS_NOTE = ('场次 = 该组合在 KPL 同队同场出现过的局数；胜率 = 这些局的胜率。不含版本换算。')


class KplBpError(RuntimeError):
    """抓取管线不可继续（例如赛季列表拿不到）。"""


class BattleParseError(ValueError):
    """单局快照无法解析成事实行；`.reason` 给 manifest 统计用。"""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = str(reason)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def make_session():
    """官方接口专用 Session：直连（trust_env=False），带 Referer / 浏览器 UA。"""
    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)
    return session


def _atomic_write_text(path, text):
    """临时文件 + 原子替换，避免中断留下半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, payload):
    """事实表 / manifest 统一走原子写（不缩进，和旧版产物风格一致）。"""
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False))


def api_get(session, url, params=None, *, attempts=RETRY_ATTEMPTS, timeout=REQUEST_TIMEOUT,
            backoff=RETRY_BACKOFF, sleep=time.sleep, log=None):
    """GET 一个官方接口，失败按指数退避重试；最终失败返回 None（绝不抛网络异常）。"""
    attempts = max(1, int(attempts))
    last_error = ''
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get('code') == 200:
                return payload
            last_error = f'code={payload.get("code") if isinstance(payload, dict) else "?"}'
        except Exception as exc:                       # 网络 / JSON / HTTP 全部吞掉重试
            last_error = f'{type(exc).__name__}: {exc}'
        if attempt + 1 < attempts:
            wait = backoff * (2 ** attempt)
            if log:
                log(f'  retry {attempt + 1}/{attempts - 1} in {wait:.1f}s ({last_error})')
            sleep(wait)
    if log:
        log(f'  give up: {last_error}')
    return None


# ---------------------------------------------------------------------------
# 接口抓取
# ---------------------------------------------------------------------------

def fetch_leagues(session, *, log=None):
    payload = api_get(session, URL_LEAGUES, log=log)
    if not payload:
        raise KplBpError('赛季列表接口不可用：' + URL_LEAGUES)
    rows = payload.get('results') or []
    return rows if isinstance(rows, list) else []


def fetch_matches(session, league_id, *, log=None):
    payload = api_get(session, URL_MATCHES, {'league_id': str(league_id)}, log=log)
    rows = (payload or {}).get('results') or []
    return rows if isinstance(rows, list) else []


def fetch_match_battles(session, match_id, *, log=None):
    """`match/battles/open`：赛程里小局列表缺失时的兜底。"""
    payload = api_get(session, URL_MATCH_BATTLES, {'match_id': str(match_id)}, log=log)
    rows = (payload or {}).get('results') or []
    return rows if isinstance(rows, list) else []


def fetch_battle(session, battle_id, *, log=None):
    """单局快照（含 bp_list）；失败重试后返回 None，由调用方计入 manifest 错误数。"""
    return api_get(session, URL_BATTLE, {'battle_id': str(battle_id)}, log=log)


# ---------------------------------------------------------------------------
# 解析：单局快照 → 事实行
# ---------------------------------------------------------------------------

def split_bp(bp_list):
    """把官方 `bp_list` 拆成 picks / bans，键为 camp 字符串 `"1"` / `"2"`，保留 BP 顺序。

    实测语义：`is_ban_or_pick == 1` 是选用，`== 0` 是禁用。
    """
    picks = {'1': [], '2': []}
    bans = {'1': [], '2': []}
    for item in bp_list or []:
        if not isinstance(item, dict):
            continue
        try:
            camp = int(item.get('camp') or 0)
            kind = int(item.get('is_ban_or_pick') or 0)
        except (TypeError, ValueError):
            continue
        if camp not in (1, 2):
            continue
        hero = str(item.get('hero_name') or '').strip()
        if not hero:
            continue
        bucket = picks if kind == PICK_FLAG else bans
        bucket[str(camp)].append(hero)
    return picks, bans


def _battle_data(payload):
    """把接口信封 / data 字典 / 裸快照统一成 data 字典。"""
    if not isinstance(payload, dict):
        return None
    data = payload.get('data')
    if isinstance(data, dict):
        return data
    if 'bp_list' in payload or 'camp1' in payload:
        return payload
    return None


def picks_match_players(data, picks):
    """硬校验：bp_list 的 pick 英雄集合必须等于同 camp 十人面板的实际英雄集合。

    这是防「pick/ban 语义被接口改掉」的保险丝（契约 §0 要求）。十人面板不完整时放行，
    老局可能没有完整的 battle_player_list。
    """
    players = data.get('battle_player_list') or []
    if len(players) < 10:
        return True
    for camp in ('1', '2'):
        actual = {str(row.get('hero_name') or '').strip()
                  for row in players if str(row.get('camp') or '') == camp}
        actual.discard('')
        if len(actual) != 5 or actual != set(picks.get(camp) or []):
            return False
    return True


def _player_rows(data):
    """十人面板 → `{"1": [{hero, player, position}], "2": [...]}`（按接口顺序）。"""
    grouped = {'1': [], '2': []}
    for row in data.get('battle_player_list') or []:
        camp = str(row.get('camp') or '')
        if camp not in grouped:
            continue
        hero = str(row.get('hero_name') or '').strip()
        if not hero:
            continue
        grouped[camp].append({
            'hero': hero,
            'player': str(row.get('player_name') or row.get('actual_player_name') or '').strip(),
            'position': str(row.get('position_desc') or '').strip(),
        })
    return grouped


def _team(row):
    row = row if isinstance(row, dict) else {}
    return {
        'teamId': str(row.get('team_id') or ''),
        'team': str(row.get('team_name') or ''),
        'abbr': str(row.get('team_abbreviation') or ''),
    }


def _league_id(match, league):
    if isinstance(league, dict) and league.get('league_id') is not None:
        return str(league.get('league_id'))
    return str((match or {}).get('league_id') or '')


def _league_year(match, league):
    try:
        year = int((league or {}).get('year') or 0)
    except (TypeError, ValueError):
        year = 0
    if year:
        return year
    start = str((match or {}).get('start_time') or '')
    return int(start[:4]) if start[:4].isdigit() else 0


def _players_complete(players):
    """十人面板是否完整：两侧各 5 人且英雄不重复（picks 的权威来源）。"""
    for camp in ('1', '2'):
        rows = players.get(camp) or []
        heroes = {str(row.get('hero') or '') for row in rows}
        heroes.discard('')
        if len(rows) != 5 or len(heroes) != 5:
            return False
    return True


def _picks_from_players(players):
    """十人面板 → picks（按分路顺序排列，保证确定性；盲选局本来就没有选人顺序）。"""
    picks = {}
    for camp in ('1', '2'):
        rows = list(players.get(camp) or [])

        def sort_key(row):
            position = str(row.get('position') or '')
            order = LANE_ORDER.index(position) if position in LANE_ORDER else len(LANE_ORDER)
            return (order, str(row.get('hero') or ''))

        picks[camp] = [str(row.get('hero') or '') for row in sorted(rows, key=sort_key)]
    return picks


def _bp_is_complete(picks, bans, bp_list):
    """bp_list 是否是一条完整 BP：两侧各 5 pick、ban 数相同且 >= 4、总条数自洽。

    2024 赛季 4 ban/边（18 条），2025+ 5 ban/边（20 条）；条数对不上（如 19 条）就算不完整。
    """
    if len(picks['1']) != 5 or len(picks['2']) != 5:
        return False
    ban1, ban2 = len(bans['1']), len(bans['2'])
    if ban1 != ban2 or ban1 < MIN_BANS_PER_SIDE:
        return False
    return len(bp_list or []) == ban1 + ban2 + 10


def _last_battle_id(match):
    """一场比赛里最后一小局的 battleId（优先按 battle_seq，缺 seq 时按赛程顺序）。"""
    entries = [entry for entry in (match or {}).get('match_battle_video_list') or []
               if isinstance(entry, dict) and entry.get('battle_id')]
    if not entries:
        return ''

    def seq(entry):
        try:
            return int(entry.get('battle_seq') or 0)
        except (TypeError, ValueError):
            return 0

    if any(seq(entry) for entry in entries):
        entries = sorted(entries, key=lambda entry: (seq(entry), str(entry.get('battle_id') or '')))
    return str(entries[-1].get('battle_id') or '')


def is_decider_game(match, battle_id):
    """巅峰对决判定：该局是系列赛最后一局，且系列赛打满（比分和 == bo、分差 1）。

    盲选规则只在「打满的最后一局」生效：BO7 打到 3:3 的第 7 局 / BO5 打到 2:2 的第 5 局。
    """
    battle_id = str(battle_id or '')
    if not battle_id or not match:
        return False
    if battle_id != _last_battle_id(match):
        return False
    camp1 = match.get('camp1') or {}
    camp2 = match.get('camp2') or {}
    try:
        score1 = int(camp1.get('score') or 0)
        score2 = int(camp2.get('score') or 0)
        bo = int(match.get('bo') or 0)
    except (TypeError, ValueError):
        return False
    if bo <= 0:
        return False
    return (score1 + score2) == bo and abs(score1 - score2) == 1


def parse_battle(payload, *, battle_id='', match=None, league=None, game_seq=0,
                 fetched_at=None, strict_players=True):
    """单局快照 → `kpl-bp-game-v1` 一行；解析不了抛 `BattleParseError(reason)`。

    picks 的权威来源是 `battle_player_list`（十人面板）：
    * `bp_list` 完整 → 用 BP 顺序取 picks/bans，并与十人面板强制校验（不一致 → `mismatch`）；
    * `bp_list` 不完整 → picks 用十人面板兜底；是巅峰对决最后一局记 `blind`，否则记 `partial`，
      两者 `bansKnown=false`、`pickOrderKnown=false`，照常入库进组合统计；
    * 十人面板也不全 → `invalid`（唯一真正拿不到的情况）。
    """
    match = match or {}
    league = league or {}
    data = _battle_data(payload)
    if not data:
        raise BattleParseError('no-data')
    try:
        status = int(data.get('status') or 0)
    except (TypeError, ValueError):
        status = 0
    if status != 2:
        raise BattleParseError('not-finished')
    players = _player_rows(data)
    if not _players_complete(players):
        raise BattleParseError('invalid')
    picks_from_players = _picks_from_players(players)
    bp_picks, bp_bans = split_bp(data.get('bp_list'))
    effective_id = str(data.get('battle_id') or battle_id)
    if _bp_is_complete(bp_picks, bp_bans, data.get('bp_list')):
        if strict_players and not picks_match_players(data, bp_picks):
            raise BattleParseError('mismatch')
        picks, bans = bp_picks, bp_bans
        bp_mode, bans_known, pick_order_known = BP_MODE_FULL, True, True
    else:
        picks = picks_from_players
        bans = {'1': [], '2': []}
        bans_known, pick_order_known = False, False
        bp_has_picks = len(bp_picks['1']) == 5 and len(bp_picks['2']) == 5
        bp_mode = BP_MODE_BLIND if (is_decider_game(match, effective_id) and not bp_has_picks) \
            else BP_MODE_PARTIAL
    try:
        win_camp = int(data.get('win_camp') or 0)
    except (TypeError, ValueError):
        win_camp = 0
    if win_camp not in (1, 2):
        raise BattleParseError('no-win-camp')
    camp1 = _team(data.get('camp1'))
    camp2 = _team(data.get('camp2'))
    start_time = str(match.get('start_time') or '')
    try:
        seq = int(data.get('battle_seq') or game_seq or 0)
    except (TypeError, ValueError):
        seq = 0
    return {
        'schema': SCHEMA_GAME,
        'battleId': str(data.get('battle_id') or battle_id),
        'matchId': str(match.get('match_id') or ''),
        'leagueId': _league_id(match, league),
        'leagueName': str(league.get('league_name') or ''),
        'year': _league_year(match, league),
        'stage': str(match.get('match_stage_desc') or match.get('match_stage_name') or ''),
        'startTime': start_time,
        'date': start_time[:10],
        'gameSeq': seq,
        'camp1': camp1,
        'camp2': camp2,
        'winCamp': win_camp,
        'winner': camp1['team'] if win_camp == 1 else camp2['team'],
        'bpMode': bp_mode,
        'bansKnown': bans_known,
        'pickOrderKnown': pick_order_known,
        'picks': picks,
        'bans': bans,
        'players': players,
        'fetchedAt': fetched_at or now_iso(),
    }


# ---------------------------------------------------------------------------
# 落盘：jsonl 增量存储 + manifest
# ---------------------------------------------------------------------------

class GameStore:
    """`data/kpl/bp_games.jsonl` 的追加式去重存储。

    * 普通模式：启动时读已有 battleId 建 set；新局进缓冲，`flush()` 用
      「旧内容 + 新行 → 临时文件 → 原子替换」写回，重复执行不会重复写行。
    * refresh 模式：把已有行读进内存，重新抓到的同 battleId 覆盖旧行，`flush()` 整体重写。
    """

    def __init__(self, path, *, refresh=False):
        self.path = Path(path)
        self.refresh = bool(refresh)
        self._ids = set()
        self._rows = {}
        self._order = []
        self._buffer = []
        self._base_text = ''
        self._load()

    def _load(self):
        try:
            self._base_text = self.path.read_text(encoding='utf-8')
        except OSError:
            self._base_text = ''
        for line in self._base_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            battle_id = str((row or {}).get('battleId') or '')
            if not battle_id:
                continue
            if battle_id not in self._ids:
                self._order.append(battle_id)
            self._ids.add(battle_id)
            if self.refresh:
                self._rows[battle_id] = row

    @property
    def ids(self):
        return self._ids

    @property
    def pending(self):
        return len(self._buffer)

    def __len__(self):
        return len(self._ids)

    def add(self, game):
        """新增一局；battleId 已存在（非 refresh）返回 False。"""
        battle_id = str((game or {}).get('battleId') or '')
        if not battle_id:
            return False
        if battle_id in self._ids and not self.refresh:
            return False
        if self.refresh:
            if battle_id not in self._ids:
                self._order.append(battle_id)
            self._ids.add(battle_id)
            self._rows[battle_id] = game
            return True
        self._ids.add(battle_id)
        self._buffer.append(game)
        return True

    def flush(self):
        """把缓冲落到磁盘，返回本次写出的行数。"""
        if self.refresh:
            rows = [self._rows[key] for key in self._order if key in self._rows]
            text = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
            _atomic_write_text(self.path, text)
            return len(rows)
        if not self._buffer:
            return 0
        addition = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in self._buffer)
        base = self._base_text
        if base and not base.endswith('\n'):
            base += '\n'
        text = base + addition
        _atomic_write_text(self.path, text)
        self._base_text = text
        written = len(self._buffer)
        self._buffer = []
        return written


def load_games(path=GAMES_PATH):
    """读 jsonl（跳过坏行），按文件顺序返回事实行列表。"""
    path = Path(path)
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('battleId'):
            rows.append(row)
    return rows


def load_manifest(path=MANIFEST_PATH):
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def select_leagues(leagues, since_year=DEFAULT_SINCE_YEAR, only=None):
    """按年份 + 赛季过滤；`only` 支持 league_id 精确匹配或 league_name 子串。"""
    tokens = []
    for item in only or []:
        for token in str(item).replace('，', ',').split(','):
            token = token.strip()
            if token:
                tokens.append(token)
    selected = []
    for row in leagues or []:
        try:
            year = int((row or {}).get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        if year and year < since_year:
            continue
        league_id = str((row or {}).get('league_id') or '')
        name = str((row or {}).get('league_name') or '')
        if tokens and not any(token == league_id or token in name for token in tokens):
            continue
        selected.append(row)
    selected.sort(key=lambda item: (int(item.get('year') or 0), str(item.get('league_id') or '')))
    return selected


def build_manifest(games, *, since_year=DEFAULT_SINCE_YEAR, stats=None, previous=None,
                   crawled_league_ids=None, generated_at=None):
    """从 jsonl 事实行重建 manifest（幂等：重复跑结果一致，只有时间戳变化）。"""
    now = generated_at or now_iso()
    previous_leagues = {str(row.get('leagueId')): row
                        for row in (previous or {}).get('leagues') or []}
    crawled = {str(item) for item in (crawled_league_ids or [])}
    by_league = {}
    for game in games:
        league_id = str(game.get('leagueId') or '')
        if not league_id:
            continue
        try:
            year = int(game.get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        record = by_league.get(league_id)
        if record is None:
            record = by_league[league_id] = {
                'leagueId': league_id,
                'leagueName': str(game.get('leagueName') or ''),
                'year': year, 'matches': set(), 'games': 0,
            }
        record['games'] += 1
        record['year'] = max(record['year'], year)
        if game.get('matchId'):
            record['matches'].add(str(game['matchId']))
    leagues = []
    for league_id in sorted(by_league, key=lambda key: (by_league[key]['year'], key)):
        record = by_league[league_id]
        previous_row = previous_leagues.get(league_id) or {}
        if crawled and league_id not in crawled:
            crawled_at = previous_row.get('crawledAt') or now
        else:
            crawled_at = now
        leagues.append({
            'leagueId': league_id,
            'leagueName': record['leagueName'],
            'year': record['year'],
            'matches': len(record['matches']),
            'games': record['games'],
            'crawledAt': crawled_at,
        })
    dates = sorted(str(game.get('date') or '') for game in games if game.get('date'))
    stats = stats or {}
    modes = {BP_MODE_FULL: 0, BP_MODE_BLIND: 0, BP_MODE_PARTIAL: 0}
    for game in games:
        mode = str(game.get('bpMode') or BP_MODE_FULL)
        if mode not in modes:
            mode = BP_MODE_FULL
        modes[mode] += 1
    return {
        'schema': SCHEMA_MANIFEST,
        'updatedAt': now,
        'sinceYear': int(since_year),
        'games': len(games),
        'windowStart': dates[0] if dates else '',
        'windowEnd': dates[-1] if dates else '',
        'full': modes[BP_MODE_FULL],
        'blind': modes[BP_MODE_BLIND],
        'partial': modes[BP_MODE_PARTIAL],
        'invalid': int(stats.get('invalid') or 0),
        'leagues': leagues,
        'errors': int(stats.get('errors') or 0),
        'errorBattleIds': list(stats.get('errorBattleIds') or [])[:200],
    }


def backfill_game_modes(games):
    """给早期抓的行补齐 / 校正 `bpMode` 系列字段；返回 `(rows, changed)`。

    早期版本只校验 picks 5/5，`bp_list` 里 ban 缺失（如 19 条）的局也会被当成完整 BP 存下来。
    这里按新口径校正：ban 数不等或不足 4 个的「full」一律降级 `partial`（bans 清空、flags=false）；
    早期行都是正常 BP，缺字段时按 full 补。
    """
    changed = 0
    rows = []
    for game in games:
        bans = game.get('bans') or {}
        ban1 = len(bans.get('1') or [])
        ban2 = len(bans.get('2') or [])
        bans_complete = ban1 == ban2 and ban1 >= MIN_BANS_PER_SIDE
        mode = game.get('bpMode')
        needs_fix = mode is None or (mode == BP_MODE_FULL and not bans_complete)
        if not needs_fix:
            rows.append(game)
            continue
        new_mode = BP_MODE_FULL if bans_complete else BP_MODE_PARTIAL
        row = {}
        for key, value in game.items():
            if key in ('bpMode', 'bansKnown', 'pickOrderKnown'):
                continue
            if key == 'picks':
                row['bpMode'] = new_mode
                row['bansKnown'] = bans_complete
                row['pickOrderKnown'] = bans_complete
            if key == 'bans' and new_mode != BP_MODE_FULL:
                value = {'1': [], '2': []}
            row[key] = value
        if 'bpMode' not in row:            # 异常行没有 picks 键时补在末尾
            row['bpMode'] = new_mode
            row['bansKnown'] = bans_complete
            row['pickOrderKnown'] = bans_complete
        rows.append(row)
        changed += 1
    return rows, changed


# ---------------------------------------------------------------------------
# 抓取编排
# ---------------------------------------------------------------------------

def _battle_entries(match, session, *, log=None):
    """一场比赛的小局列表：优先赛程里的 `match_battle_video_list`，缺失再查小局接口。"""
    entries = list(match.get('match_battle_video_list') or [])
    if not entries and match.get('match_id'):
        entries = fetch_match_battles(session, match.get('match_id'), log=log)
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        battle_id = str(entry.get('battle_id') or '')
        if not battle_id:
            continue
        try:
            seq = int(entry.get('battle_seq') or 0)
        except (TypeError, ValueError):
            seq = 0
        rows.append((battle_id, seq))
    rows.sort(key=lambda item: (item[1], item[0]))
    return rows


def crawl_games(session, store, *, since_year=DEFAULT_SINCE_YEAR, only_leagues=None,
                limit=0, sleep=DEFAULT_SLEEP, refresh=False, dry_run=False,
                strict_players=True, log=print, sleep_fn=time.sleep):
    """按赛季 → 赛程 → 小局顺序抓取；只抓已完赛（status==2），battleId 已存在则跳过。

    返回统计 dict（含错误 battleId 列表），写盘由调用方决定（dry_run 时完全不写）。
    """
    limit = max(0, int(limit or 0))
    sleep = max(0.0, float(sleep or 0.0))
    stats = {
        'sinceYear': int(since_year),
        'selectedLeagueIds': [],
        'leagues': 0, 'matches': 0, 'gamesPlanned': 0,
        'skippedExisting': 0, 'pending': 0,
        'fetched': 0, 'added': 0,
        'errors': 0, 'invalid': 0, 'mismatch': 0,
        'full': 0, 'blind': 0, 'partial': 0,
        'errorBattleIds': [],
        'invalidBattleIds': [],
    }

    leagues = fetch_leagues(session, log=log)
    selected = select_leagues(leagues, since_year, only_leagues)
    stats['leagues'] = len(selected)
    stats['selectedLeagueIds'] = [str(row.get('league_id') or '') for row in selected]
    if not selected:
        return stats
    if log:
        log(f'赛季 {len(selected)} 个（sinceYear={since_year}）：'
            + '、'.join(str(row.get('league_name') or row.get('league_id')) for row in selected))

    plan = []
    for league in selected:
        try:
            matches = fetch_matches(session, league.get('league_id'), log=log)
        except KplBpError as exc:          # 单个赛季失败不影响其它赛季
            if log:
                log(f'  赛季 {league.get("league_id")} 赛程失败：{exc}')
            continue
        if log:
            log(f'  赛季 {league.get("league_id")} {league.get("league_name")}: '
                f'{len(matches)} 场')
        for match in matches:
            try:
                status = int(match.get('status') or 0)
            except (TypeError, ValueError):
                status = 0
            if status != 2:                # 只抓已完赛
                continue
            stats['matches'] += 1
            for battle_id, seq in _battle_entries(match, session, log=log):
                plan.append((league, match, battle_id, seq))
        if sleep:
            sleep_fn(sleep)

    stats['gamesPlanned'] = len(plan)
    pending = [item for item in plan if refresh or item[2] not in store.ids]
    stats['skippedExisting'] = len(plan) - len(pending)
    if limit:
        pending = pending[:limit]
    stats['pending'] = len(pending)
    if log:
        log(f'小局 {stats["gamesPlanned"]} 个：已存在 {stats["skippedExisting"]}，'
            f'待抓 {len(pending)}' + ('（dry-run 不抓）' if dry_run else ''))
    if dry_run:
        return stats

    total = len(pending)
    fetched_at = now_iso()
    started = time.time()
    for index, (league, match, battle_id, seq) in enumerate(pending, 1):
        payload = fetch_battle(session, battle_id, log=log)
        if payload is None:
            stats['errors'] += 1
            stats['errorBattleIds'].append(battle_id)
        else:
            stats['fetched'] += 1
            try:
                game = parse_battle(payload, battle_id=battle_id, match=match, league=league,
                                    game_seq=seq, fetched_at=fetched_at,
                                    strict_players=strict_players)
            except BattleParseError as exc:
                if exc.reason == 'invalid':        # 连十人面板都不全，才是真拿不到
                    stats['invalid'] += 1
                    stats['invalidBattleIds'].append(battle_id)
                else:                              # mismatch / no-data / no-win-camp 等解析失败
                    stats['errors'] += 1
                    stats['errorBattleIds'].append(battle_id)
                    if exc.reason == 'mismatch':
                        stats['mismatch'] += 1
                if log and (stats['invalid'] + stats['errors']) <= 5:
                    log(f'  {battle_id} 跳过（{exc.reason}）')
            else:
                mode = str(game.get('bpMode') or BP_MODE_FULL)
                if mode not in BP_MODES:
                    mode = BP_MODE_FULL
                stats[mode] += 1
                if store.add(game):
                    stats['added'] += 1
        if store.pending >= FLUSH_EVERY:
            store.flush()
        if sleep:
            sleep_fn(sleep)
        if log and (index % 200 == 0 or index == total):
            elapsed = max(time.time() - started, 1e-6)
            rate = index / elapsed
            log(f'  [{index}/{total}] +{stats["added"]} full={stats["full"]} '
                f'blind={stats["blind"]} partial={stats["partial"]} '
                f'err={stats["errors"]} invalid={stats["invalid"]} {rate:.1f} 局/秒')
    store.flush()
    if log:
        log(f'抓取完成：新增 {stats["added"]}（full={stats["full"]} blind={stats["blind"]} '
            f'partial={stats["partial"]}），错误 {stats["errors"]}，'
            f'invalid {stats["invalid"]}，mismatch {stats["mismatch"]}')
    return stats


# ---------------------------------------------------------------------------
# 聚合：组合事实表
# ---------------------------------------------------------------------------

def _side_heroes(game, camp):
    picks = (game.get('picks') or {}).get(camp) or []
    return sorted({str(hero).strip() for hero in picks if str(hero or '').strip()})


def _iter_game_sides(game):
    """产出 (camp, 队伍名, 去重排序后的英雄列表, 是否获胜)。"""
    try:
        win_camp = int(game.get('winCamp') or 0)
    except (TypeError, ValueError):
        win_camp = 0
    for camp in ('1', '2'):
        heroes = _side_heroes(game, camp)
        if not heroes:
            continue
        team = str((game.get('camp' + camp) or {}).get('team') or '')
        yield camp, team, heroes, 1 if win_camp == int(camp) else 0


def _bump(store, key, year, team, won):
    record = store.get(key)
    if record is None:
        record = store[key] = {'n': 0, 'wins': 0, 'year': 0, 'teams': {}}
    record['n'] += 1
    record['wins'] += won
    record['year'] = max(record['year'], year)
    if team:
        team_row = record['teams'].get(team)
        if team_row is None:
            team_row = record['teams'][team] = {'n': 0, 'wins': 0}
        team_row['n'] += 1
        team_row['wins'] += won


def _pack(store, *, size=None, min_n=1):
    rows = []
    for heroes, record in store.items():
        if record['n'] < min_n:
            continue
        teams = sorted(record['teams'].items(), key=lambda item: (-item[1]['n'], item[0]))
        row = {'heroes': list(heroes), 'n': record['n'], 'wins': record['wins'],
               'wr': round(record['wins'] / record['n'] * 100, 1),
               'year': record['year']}
        if size is not None:
            row['size'] = size
        row['teams'] = [{'team': team, 'n': value['n'], 'wins': value['wins']}
                        for team, value in teams[:MAX_TEAMS]]
        rows.append(row)
    rows.sort(key=lambda item: (-item['n'], item['heroes']))
    return rows


def build_combos(games, *, since_year=DEFAULT_SINCE_YEAR, min_games=DEFAULT_MIN_GAMES):
    """同队同场 5 个 pick → 双人 / 三人 / 整阵容组合的场次与胜率。

    与旧版口径一致：先按英雄名去重再排序组合；`minGames` 只过滤双人 / 三人，
    整阵容出现过 1 次就保留。
    """
    pairs, trios, lineups = {}, {}, {}
    included = 0
    for game in games:
        try:
            year = int(game.get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        if year and year < since_year:
            continue
        included += 1
        for _camp, team, heroes, won in _iter_game_sides(game):
            for i in range(len(heroes)):
                for j in range(i + 1, len(heroes)):
                    _bump(pairs, (heroes[i], heroes[j]), year, team, won)
                    for k in range(j + 1, len(heroes)):
                        _bump(trios, (heroes[i], heroes[j], heroes[k]), year, team, won)
            if len(heroes) == 5:
                _bump(lineups, tuple(heroes), year, team, won)
    return {
        'games': included,
        'pairs': _pack(pairs, size=2, min_n=min_games),
        'trios': _pack(trios, size=3, min_n=min_games),
        'lineups': _pack(lineups, min_n=1),
    }


def build_facts(games, *, since_year=DEFAULT_SINCE_YEAR, min_games=DEFAULT_MIN_GAMES,
                generated_at=None):
    """生成 `data/facts/kpl_combos.json`（schema 保持 `bp-kpl-combos-v1`，只增不改）。"""
    combos = build_combos(games, since_year=since_year, min_games=min_games)
    included = []
    for game in games:
        try:
            year = int(game.get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        if year and year < since_year:
            continue
        included.append(game)
    dates = sorted(str(game.get('date') or '') for game in included if game.get('date'))
    leagues = {}
    for game in included:
        league_id = str(game.get('leagueId') or '')
        if not league_id:
            continue
        try:
            year = int(game.get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        record = leagues.get(league_id)
        if record is None or year > record[0]:
            leagues[league_id] = (year, str(game.get('leagueName') or ''))
    ordered = [leagues[key] for key in sorted(leagues, key=lambda k: (leagues[k][0], k))]
    return {
        'schema': SCHEMA_COMBOS,
        'source': SOURCE,
        'sinceYear': int(since_year),
        'games': combos['games'],
        'minGames': int(min_games),
        'updatedAt': generated_at or now_iso(),
        'windowStart': dates[0] if dates else '',
        'windowEnd': dates[-1] if dates else '',
        'leagueCount': len(leagues),
        'leagueNames': [name for _year, name in ordered],
        'note': COMBOS_NOTE,
        'pairs': combos['pairs'],
        'trios': combos['trios'],
        'lineups': combos['lineups'],
    }


# ---------------------------------------------------------------------------
# 高层入口（CLI 调用）
# ---------------------------------------------------------------------------

def run_crawl(*, since_year=DEFAULT_SINCE_YEAR, only_leagues=None, limit=0,
              sleep=DEFAULT_SLEEP, refresh=False, dry_run=False, build=True,
              min_games=DEFAULT_MIN_GAMES, games_path=GAMES_PATH,
              manifest_path=MANIFEST_PATH, facts_path=FACTS_PATH,
              strict_players=True, session=None, log=print, sleep_fn=time.sleep):
    """抓取 → 增量落盘 → 重建 manifest →（默认）重建 facts。返回汇总 dict。"""
    session = session or make_session()
    store = GameStore(games_path, refresh=refresh)
    result = {'gamesPath': str(games_path), 'dryRun': bool(dry_run)}
    stats = crawl_games(session, store, since_year=since_year, only_leagues=only_leagues,
                        limit=limit, sleep=sleep, refresh=refresh, dry_run=dry_run,
                        strict_players=strict_players, log=log, sleep_fn=sleep_fn)
    result['crawl'] = stats
    if dry_run:
        return result

    store.flush()
    games = load_games(games_path)
    games, backfilled = backfill_game_modes(games)
    if backfilled:                         # 老数据补齐 bpMode / bansKnown / pickOrderKnown
        _atomic_write_text(games_path, ''.join(
            json.dumps(game, ensure_ascii=False) + '\n' for game in games))
        if log:
            log(f'回填 bpMode/bansKnown/pickOrderKnown：{backfilled} 行')
    manifest = build_manifest(games, since_year=since_year, stats=stats,
                              previous=load_manifest(manifest_path),
                              crawled_league_ids=stats.get('selectedLeagueIds'))
    write_json(manifest_path, manifest)
    result['manifest'] = {key: manifest[key] for key in
                          ('games', 'windowStart', 'windowEnd', 'full', 'blind', 'partial',
                           'invalid', 'errors', 'updatedAt')}
    result['manifest']['leagues'] = len(manifest['leagues'])
    if build:
        facts = build_facts(games, since_year=since_year, min_games=min_games)
        write_json(facts_path, facts)
        result['facts'] = {
            'games': facts['games'], 'pairs': len(facts['pairs']),
            'trios': len(facts['trios']), 'lineups': len(facts['lineups']),
            'windowStart': facts['windowStart'], 'windowEnd': facts['windowEnd'],
            'leagueCount': facts['leagueCount'], 'updatedAt': facts['updatedAt'],
        }
    return result
