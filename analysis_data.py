"""Read-only analysis dataset across workbench records, match bundles and sheet imports.

No writes and no cloud calls. Aggregated sheet tables stay separate; per-minute
rates use sum(value)/sum(valid minutes), not an average of per-match rates.
"""
import json
import math
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from pathlib import Path

import official_economy

MATCH_SCHEMA = 'kpl-match-data-v1'
IMPORT_SCHEMA = 'kpl-sheet-import-v1'
DEFAULT_SOURCES = ('db', 'bundle')
ALL_SOURCES = ('db', 'bundle', 'sheet')
RESULT_NAMES = {'win': '胜', 'loss': '负', 'draw': '平', 'unknown': '未知'}
LANES = ('对抗路', '打野', '中路', '发育路', '游走')


def _kda_value(player):
    kills, deaths, assists = player.get('kills'), player.get('deaths'), player.get('assists')
    if kills is None or deaths is None or assists is None:
        return None
    return (kills + assists) / max(1, deaths)


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().lower().replace(',', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:k|万|w|%)?', text):
        return None
    multiplier = 1000 if text.endswith('k') else 10000 if text.endswith(('万', 'w')) else 1
    value = float(text.rstrip('k万w%')) * multiplier
    return value if math.isfinite(value) else None


# 营地昵称常夹带零宽字符（如「信则\u2060\u2061有\u2062」），按可见文本认领前先清洗；
# 与 depth_api 的清洗规则保持一致，避免同名选手在列表页 / 深度分析里分成两个人。
_ZERO_WIDTH = {code: None for code in
               (*range(0x200b, 0x2010), *range(0x2060, 0x2065), 0xfeff, *range(0xfe00, 0xfe10))}


def clean(text):
    return str(text or '').translate(_ZERO_WIDTH).strip()


# 营地 / 表格里偶尔会把分路存成 0–4；统一在入口换成中文路名，界面不再出现「分路 0」。
_LANE_BY_CODE = {'0': '对抗路', '1': '中路', '2': '发育路', '3': '打野', '4': '游走'}


def lane_name(value):
    # 注意 clean() 会把 0 当 falsy 吞掉，所以数值分路码要先转字符串
    text = str(value) if isinstance(value, (int, float)) else clean(value)
    if text.endswith('.0'):
        text = text[:-2]
    return _LANE_BY_CODE.get(text, text)


def _cjk(text):
    return re.sub(r'[^\u4e00-\u9fff]', '', str(text or ''))


def same_hero(a, b):
    left, right = _cjk(a), _cjk(b)
    if not left or not right:
        return False
    if left == right:
        return True
    return len(left) == len(right) >= 2 and sum(x != y for x, y in zip(left, right)) == 1


def overlap(left, right):
    used, count = set(), 0
    for hero in left:
        for index, other in enumerate(right):
            if index not in used and same_hero(hero, other):
                used.add(index)
                count += 1
                break
    return count


def date_key(text):
    text = clean(text)
    match = re.fullmatch(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2}).*', text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}", True
    match = re.fullmatch(r'(\d{1,2})[-/](\d{1,2}).*', text)
    if match:
        return f"{int(match.group(1)):02d}-{int(match.group(2)):02d}", False
    return None, False


def _sort_date(text):
    value, full = date_key(text)
    if value is None:
        return '9999'
    return value if full else f'0000-{value}'


def _minutes(seconds):
    return seconds / 60.0 if isinstance(seconds, (int, float)) and seconds > 0 else None


def _metric(player, key):
    value = player.get(key)
    if value is None:
        return None
    if key in ('kills', 'deaths', 'assists'):
        parsed = number(value)
        return int(parsed) if parsed is not None and parsed.is_integer() else parsed
    return number(value)


def _result_for(camp, winner, scores):
    if winner:
        return 'win' if camp == winner else 'loss'
    if scores:
        left, right = number(scores.get('blue')), number(scores.get('red'))
        if camp in ('blue', 'red') and left is not None and right is not None:
            if left == right:
                return 'draw'
            return 'win' if (camp == 'blue' and left > right) or (camp == 'red' and right > left) else 'loss'
        left, right = number(scores.get('left')), number(scores.get('right'))
        if camp in ('left', 'right') and left is not None and right is not None:
            if left == right:
                return 'draw'
            return 'win' if (camp == 'left' and left > right) or (camp == 'right' and right > left) else 'loss'
    return 'unknown'


def _is_seed_title(title):
    """验证脚本写入的对局标题固定带「验证数据」前缀，用于隔离测试样本。"""
    text = clean(title)
    return text.startswith('验证数据') or '排位验证' in text


def _complete(player):
    keys = ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken')
    return all(player.get(key) is not None for key in keys)


class AnalysisRepository:
    def __init__(self, db_path, matches_dir, imports_dir, official_dir=None):
        self.db_path = Path(db_path)
        self.matches_dir = Path(matches_dir)
        self.imports_dir = Path(imports_dir)
        # 正式比赛包可能早于官方回放入库；读取时从同一数据目录的
        # official_replays 兜底，避免所有分析都要求先重写 bundle。
        self.official_dir = (Path(official_dir) if official_dir
                             else self.matches_dir.parent / 'official_replays')
        self._data = None
        # 单进程内多个线程可能同时走 v3 的 TTL 刷新与 /api/reload；
        # 双检锁保证只构建一次，也不会读到半成品缓存。
        self._lock = threading.Lock()

    def get(self):
        data = self._data
        if data is not None:
            return data
        with self._lock:
            if self._data is None:
                self._data = self._load()
            return self._data

    def invalidate(self):
        with self._lock:
            self._data = None

    # ---------- loading ----------
    def _load(self):
        warnings = []
        roster, team_name, db_matches, drafts, aliases, profile = self._load_db(warnings)
        bundles = self._load_bundles(warnings)
        matches, links = self._unify(db_matches, bundles, warnings)
        sheet_matches, imports, aggregates = self._load_imports(warnings)
        # 表格导入的局也吃「本队阵营」覆盖层与昵称绑定：教练在单局页标了蓝/红，
        # 下一层才能算胜负、比分与本队/对手两侧；以前这两步只跑在 db/bundle 上。
        combined = matches + sheet_matches
        self._apply_match_meta(combined, self._load_match_meta(warnings))
        self._apply_aliases(combined, aliases, roster, (profile.get('enemyAliases') or {}))
        rows = self._flat_rows(matches, warnings)
        # 表格行按需加入；默认 source=db,bundle。
        sheet_rows = self._sheet_flat_rows(sheet_matches, warnings)
        data = {
            'teamName': team_name,
            'profile': profile,
            'roster': roster,
            'aliases': aliases,
            'matches': matches,
            'rows': rows,
            'sheetMatches': sheet_matches,
            'sheetRows': sheet_rows,
            'links': links,
            'imports': imports,
            'aggregates': aggregates,
            'drafts': drafts,
            'warnings': list(dict.fromkeys(warnings)),
        }
        return data

    @staticmethod
    def _apply_aliases(matches, aliases, roster, enemy_aliases=None):
        """Bind 昵称到稳定选手 ID；只影响分析视图，不改原始比赛。

        本队昵称走 aliases，对手昵称走 enemy_aliases：
        同一个昵称可能在不同对局出现在两侧，必须按阵营分开映射。
        """
        enemy_aliases = enemy_aliases or {}
        for match in matches:
            own = match.get('ownCamp') or match.get('ownSide')
            if not own and match.get('source') == 'sheet' and aliases:
                # 导入时没选本队阵营：用已认领的本队昵称反推；两侧都能命中就不猜。
                hits = {'blue': 0, 'red': 0}
                for player in match.get('players', []):
                    camp = player.get('camp')
                    if camp in hits and (player.get('label') or '') in aliases:
                        hits[camp] += 1
                if hits['blue'] and not hits['red']:
                    own = 'blue'
                elif hits['red'] and not hits['blue']:
                    own = 'red'
                if own:
                    match['ownCamp'] = own
                    match['ownSide'] = 'left' if own == 'blue' else 'right'
            for player in match.get('players', []):
                player['rawLabel'] = player.get('label') or ''
                if player.get('playerId') or not own:
                    continue
                camp = player.get('camp') or player.get('side')
                is_own = not camp or camp == own
                table = aliases if is_own else enemy_aliases
                player_id = table.get(player.get('label') or '')
                if player_id and player_id in roster:
                    player['playerId'] = player_id
                    player['label'] = roster[player_id]
                    player['bound'] = True

    def _load_db(self, warnings):
        if not self.db_path.is_file():
            warnings.append('未找到工作台数据库，仅使用录像数据包/表格。')
            return {}, None, [], 0, {}, {}
        try:
            connection = sqlite3.connect(f'file:{self.db_path.as_posix()}?mode=ro', uri=True)
            connection.row_factory = sqlite3.Row
            settings_row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            settings = json.loads(settings_row[0]) if settings_row else {'teamName': '', 'roster': []}
            roster_members = settings.get('roster', [])
            own_team = (settings.get('teamName') or '').strip()

            def identity_label(player):
                """身份标签：跨战队时带前缀，例如「重庆狼队.小胖」。

                同一名选手的大小号通过 aliases 归到同一条名单记录，标签只写一次。
                """
                name = clean(player.get('name') or player.get('id') or '')
                team = clean(player.get('team') or '')
                if team and team != own_team and name and not name.startswith(team + '.'):
                    return f'{team}.{name}'
                return name

            roster = {player['id']: identity_label(player) for player in roster_members}
            aliases = settings.get('aliases') if isinstance(settings.get('aliases'), dict) else {}
            profile = {
                'teamName': settings.get('teamName') or '',
                'coach': clean(settings.get('coach')),
                'season': clean(settings.get('season')),
                'organization': clean(settings.get('organization')),
                'rosterMigratedAt': settings.get('rosterMigratedAt') or '',
                'teams': settings.get('teams') if isinstance(settings.get('teams'), list) else [],
                'enemyAliases': settings.get('enemyAliases') if isinstance(settings.get('enemyAliases'), dict) else {},
                'members': [{
                    'id': player.get('id'),
                    'name': player.get('name') or player.get('id'),
                    'label': identity_label(player),
                    'realName': player.get('realName') or '',
                    'position': lane_name(player.get('position')),
                    'team': player.get('team') or '',
                    'tags': player.get('tags') or [],
                    'number': player.get('number'),
                    'campUserId': str(player.get('campUserId') or ''),
                    'archived': bool(player.get('archived')),
                } for player in roster_members],
            }
            matches, drafts = [], 0
            for row in connection.execute('SELECT body FROM matches'):
                body = json.loads(row[0])
                if body.get('status') != 'confirmed':
                    drafts += 1
                    continue
                matches.append(self._db_match(body, roster))
            connection.close()
            return roster, settings.get('teamName'), matches, drafts, aliases, profile
        except (sqlite3.Error, json.JSONDecodeError, KeyError) as error:
            warnings.append(f'工作台数据库读取失败：{error}')
            return {}, None, [], 0, {}, {}

    def _load_match_meta(self, warnings):
        """人工补录的比赛档案（对手、时长、赛果等），以覆盖层形式生效。

        原始数据包/记录不改写；补录内容单独存放，可随时撤回。
        """
        if not self.db_path.is_file():
            return {}
        try:
            connection = sqlite3.connect(f'file:{self.db_path.as_posix()}?mode=ro', uri=True)
            try:
                rows = connection.execute('SELECT match_key, body FROM match_meta').fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return {}
        meta = {}
        for key, body in rows:
            try:
                value = json.loads(body)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                meta[key] = value
        return meta

    @staticmethod
    def _apply_match_meta(matches, meta):
        if not meta:
            return
        text_fields = ('opponent', 'session', 'title', 'version', 'mode', 'venue', 'note')
        for match in matches:
            patch = meta.get(match.get('key'))
            if not patch:
                continue
            for key in text_fields:
                if key in patch:
                    match[key] = clean(patch.get(key))
            if 'duration' in patch:
                minutes = number(patch.get('duration'))
                match['duration'] = int(round(minutes * 60)) if minutes and minutes > 0 else None
            camp = patch.get('ownCamp')
            if camp in ('blue', 'red'):
                # 教练可以指定本队这一局在蓝方还是红方。胜负**不能**按比分（击杀数）
                # 重算：王者荣耀的胜负由拆水晶决定，实测有 25:26 蓝方获胜这类局。
                # winnerCamp 保持营地/官方回放的真值；缺失就留空，等教练在补录里
                # 明确 win/loss（下方 result 分支）——缺失不捏造。
                match['ownCamp'] = camp
                match['ownSide'] = 'left' if camp == 'blue' else 'right'
            result = patch.get('result')
            if result in ('win', 'loss', 'draw') and match.get('ownCamp') in ('blue', 'red'):
                own = match['ownCamp']
                match['winnerCamp'] = {'win': own, 'loss': 'red' if own == 'blue' else 'blue',
                                       'draw': None}[result]
            # 10 分钟经济：营地那条链路拿不到逐人金币，只能由教练在工作台手填。
            # 存在覆盖层里（不动原始数据包），键是「阵营-槽位」，值为整数金币。
            gold10 = patch.get('gold10')
            if isinstance(gold10, dict):
                cleaned = {}
                for name, value in gold10.items():
                    try:
                        # 不能叫 number：那会遮蔽模块级的 number()，导致上面的
                        # 时长换算（minutes = number(...)）抛 UnboundLocalError。
                        gold_value = int(float(value))
                    except (TypeError, ValueError):
                        continue
                    if 0 <= gold_value <= 100000:
                        cleaned[str(name)] = gold_value
                if cleaned:
                    match['gold10'] = cleaned
            match['metaFields'] = sorted(patch.keys())

    def _db_match(self, body, roster):
        duration = number(body.get('duration'))
        duration_seconds = int(round(duration * 60)) if duration else None
        side_map = {'left': 'left', 'right': 'right'}
        players = []
        for player in body.get('players', []):
            side = player.get('side')
            if side not in side_map:
                continue
            players.append({
                'playerId': player.get('playerId'),
                'label': roster.get(player.get('playerId')) or clean(player.get('label')) or player.get('playerId') or player.get('hero'),
                'camp': side_map[side],
                'side': side,
                'slot': player.get('slot'),
                'hero': clean(player.get('hero')),
                'position': lane_name(player.get('position')),
                'kills': _metric(player, 'kills'),
                'deaths': _metric(player, 'deaths'),
                'assists': _metric(player, 'assists'),
                'gold': _metric(player, 'gold'),
                'damage': _metric(player, 'damage'),
                'taken': _metric(player, 'taken'),
                'participation': _metric(player, 'participation'),
                'rating': _metric(player, 'rating'),
                'cs': _metric(player, 'cs'), 'jungleGold': _metric(player, 'jungleGold'),
                'control': _metric(player, 'control'), 'healing': _metric(player, 'healing'),
                'towerDamage': _metric(player, 'towerDamage'),
                'damageConversion': _metric(player, 'damageConversion'),
                'takenPerDeath': _metric(player, 'takenPerDeath'),
                'finalSource': 'db', 'partial': False, 'process': None,
                'equipment': player.get('equipment'),
            })
        own = body.get('side')
        winner = body.get('winner')
        return {
            'key': f"db-{body.get('id')}", 'dbId': body.get('id'), 'bundleKey': None,
            'sources': ['db'], 'source': 'db',
            'date': body.get('date'), 'dateText': body.get('date'),
            'duration': duration_seconds, 'opponent': clean(body.get('opponent')),
            'session': clean(body.get('session')), 'version': clean(body.get('version')),
            'mode': None, 'title': None, 'ownSide': own, 'ownCamp': own,
            'winner': winner, 'scores': body.get('scores') or {},
            'players': players,
            'bp': body.get('bp') or '', 'events': body.get('events') or [],
            'focusIds': body.get('focusIds') or [],
            'process': None,
            'warnings': [], 'status': body.get('status'),
        }

    def _load_bundles(self, warnings):
        result = []
        if not self.matches_dir.is_dir():
            return result
        for path in sorted(self.matches_dir.glob('*.json')):
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as error:
                warnings.append(f'数据包读取失败 {path.name}：{error}')
                continue
            if not isinstance(value, dict) or value.get('schema') != MATCH_SCHEMA:
                continue
            match = value.get('match') or {}
            date = match.get('date') or {}
            players = []
            raw_players = value.get('players', [])
            hero_counts = Counter(clean(player.get('hero')) for player in raw_players)
            camp_lanes = (match.get('campBp') or {}).get('lanes') or {}
            for player in raw_players:
                final = player.get('final') or {}
                process = player.get('process') or {}
                hero = clean(player.get('hero'))
                # position=0（对抗路）是合法值，不能用 or 兜底，否则被当 falsy 吞掉
                position = player.get('position')
                if position is None or position == '':
                    position = camp_lanes.get(hero) if hero_counts[hero] == 1 else None
                players.append({
                    'playerId': None, 'label': clean(player.get('nickname')) or player.get('hero') or player.get('key'),
                    'camp': player.get('camp'), 'side': player.get('camp'), 'slot': player.get('slot'),
                    'hero': hero, 'position': lane_name(position),
                    'kills': number(final.get('kills')), 'deaths': number(final.get('deaths')),
                    'assists': number(final.get('assists')), 'gold': number(final.get('totalGold')),
                    'damage': number(final.get('damage')), 'taken': number(final.get('taken')),
                    'participation': number(final.get('participation')), 'rating': number(final.get('rating')),
                    'cs': number(final.get('cs')), 'jungleGold': number(final.get('jungleGold')),
                    'control': number(final.get('control')), 'healing': number(final.get('healing')),
                    'towerDamage': number(final.get('towerDamage')),
                    'damageConversion': number(final.get('damageConversion')),
                    'takenPerDeath': number(final.get('takenPerDeath')),
                    'finalSource': final.get('source') or 'bundle',
                    'partial': bool(final.get('partial', not final.get('complete', False))),
                    'process': process,
                    'equipment': final.get('equipmentCandidates'),
                })
            follow_camps = []
            for source in value.get('sources', []):
                camp = (source.get('followPlayer') or {}).get('camp')
                if camp:
                    follow_camps.append(camp)
            own_camp = follow_camps[0] if len(set(follow_camps)) == 1 else None
            official = match.get('officialReplay') or {}
            camp_backed = bool(match.get('campBp')) or str(official.get('id') or '').startswith('camp-')
            camp_backed = camp_backed or any(
                ((source.get('channelSources') or {}).get('statuses') or {}).get('camp') == 'parsed'
                for source in value.get('sources', []))
            timeline = (value.get('team') or {}).get('timeline') or []
            if not timeline:
                # 回放在对局保存之后才挂上时，旧 bundle 的 timeline 会是空的；
                # 直接读官方经济，避免要求用户重新入库一次。
                timeline = official_economy.from_bundle(self.official_dir, value)
            result.append({
                'key': match.get('key') or path.stem,
                'dbId': None, 'bundleKey': match.get('key') or path.stem,
                'sources': ['bundle'], 'source': 'bundle',
                'campBacked': camp_backed,
                'date': date.get('text'), 'dateText': date.get('text'),
                # 数据包可能缺顶层 duration；官方回放 normalized 有同口径的
                # durationSec（秒），缺失时兜底，否则按分钟聚合的指标分母塌缩
                # （GPM/DPM 曾因此虚高数倍且无任何提示）。
                'duration': match.get('duration')
                            or official_economy.duration_from_bundle(self.official_dir, value),
                'opponent': match.get('opponent'), 'session': match.get('session'),
                'version': None, 'mode': match.get('mode'),
                'title': match.get('title'), 'ownSide': own_camp,
                'ownCamp': own_camp or match.get('ownCamp'),
                # winner 保持原有口径（数据包默认不由面板冒充胜负）；
                # winnerCamp 是营地/官方回放自带的真实胜负，BP 聚合优先读它。
                'winner': None, 'winnerCamp': match.get('winnerCamp'),
                'campBp': match.get('campBp'),
                # 营地官方回放的摘要（id / 胜负 / 团队金币）。单局详情要按 id 找回
                # camp_details 里的派生卡片（视野价值、经济转有效伤害等），
                # 所以这里随详情一并带出，而不是让前端再猜一次 gameSeq。
                'officialReplay': official,
                'scores': match.get('scores') or {},
                'players': players, 'process': {
                    'timeline': timeline,
                    'scoreboardSnapshots': (value.get('team') or {}).get('scoreboardSnapshots') or [],
                    'killEvents': (value.get('team') or {}).get('killEvents') or [],
                },
                'warnings': value.get('warnings') or [],
                'status': 'bundle', 'bp': match.get('bp'),
            })
        return result

    def _unify(self, db_matches, bundles, warnings):
        used, links, result = set(), [], []
        for bundle in bundles:
            candidates = []
            b_heroes = [player['hero'] for player in bundle['players'] if player['hero']]
            b_date, b_full = date_key(bundle.get('date'))
            for db in db_matches:
                if db['key'] in used:
                    continue
                d_heroes = [player['hero'] for player in db['players'] if player['hero']]
                if overlap(b_heroes, d_heroes) < 8:
                    continue
                d_date, d_full = date_key(db.get('date'))
                if b_date and d_date:
                    if b_full and d_full and b_date != d_date:
                        continue
                    if b_date[-5:] != d_date[-5:]:
                        continue
                if db.get('duration') and bundle.get('duration'):
                    if abs(db['duration'] - bundle['duration']) > 3:
                        continue
                candidates.append(db)
            if len(candidates) != 1:
                if len(candidates) > 1:
                    warnings.append(f"录像 {bundle['key']} 同时匹配多条本机记录，未自动关联。")
                result.append(bundle)
                continue
            db = candidates[0]
            used.add(db['key'])
            merged = self._merge_linked(db, bundle)
            links.append({'dbKey': db['key'], 'bundleKey': bundle['key']})
            result.append(merged)
        result.extend(db for db in db_matches if db['key'] not in used)
        return result, links

    def _merge_linked(self, db, bundle):
        merged = json.loads(json.dumps(db, ensure_ascii=False))
        merged['sources'] = ['db', 'bundle']
        merged['campBacked'] = bundle.get('campBacked', False)
        if bundle.get('campBp'):
            merged['campBp'] = bundle['campBp']
        merged['bundleKey'] = bundle['key']
        merged['process'] = bundle['process']
        merged['bundleWarnings'] = bundle.get('warnings', [])
        merged['title'] = bundle.get('title')
        merged['mode'] = bundle.get('mode')
        merged['warnings'] = list(dict.fromkeys((db.get('warnings') or []) + (bundle.get('warnings') or [])))
        b_blue = [p['hero'] for p in bundle['players'] if p.get('camp') == 'blue']
        b_red = [p['hero'] for p in bundle['players'] if p.get('camp') == 'red']
        db_left = [p['hero'] for p in db['players'] if p.get('side') == 'left']
        db_right = [p['hero'] for p in db['players'] if p.get('side') == 'right']
        direct = overlap(db_left, b_blue) + overlap(db_right, b_red)
        swapped = overlap(db_left, b_red) + overlap(db_right, b_blue)
        camp_map = {'left': 'blue', 'right': 'red'} if direct >= swapped else {'left': 'red', 'right': 'blue'}
        if direct == swapped == 0:
            camp_map = {}
        merged['campMap'] = camp_map
        if db.get('ownSide') in camp_map:
            merged['ownCamp'] = camp_map[db['ownSide']]
        if db.get('winner'):
            merged['winnerCamp'] = camp_map.get(db['winner'], db['winner'])
        for player in merged['players']:
            player['camp'] = camp_map.get(player['side'], player['side'])
            matches = [candidate for candidate in bundle['players']
                       if same_hero(player['hero'], candidate['hero'])
                       and camp_map.get(player['side'], player['side']) == candidate.get('camp')]
            if len(matches) != 1:
                matches = [candidate for candidate in bundle['players']
                           if same_hero(player['hero'], candidate['hero'])]
            if len(matches) != 1:
                continue
            source = matches[0]
            player['process'] = source.get('process')
            player['bundleLabel'] = source.get('label')
            if not player.get('position'):
                player['position'] = source.get('position')
            for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken', 'participation', 'rating'):
                if player.get(key) is None and source.get(key) is not None:
                    player[key] = source[key]
                    player['finalSource'] = 'mixed'
            player['partial'] = not _complete(player)
        return merged

    # ---------- sheet imports ----------
    def _load_imports(self, warnings):
        imports, aggregates, sheet_matches = [], [], []
        if not self.imports_dir.is_dir():
            return sheet_matches, imports, aggregates
        for path in sorted(self.imports_dir.glob('*/manifest.json')):
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as error:
                warnings.append(f'表格清单读取失败 {path.parent.name}：{error}')
                continue
            if manifest.get('schema') != IMPORT_SCHEMA:
                continue
            import_id = path.parent.name
            entry = {'id': import_id, 'source': manifest.get('source'),
                     'profileSource': manifest.get('profileSource'),
                     'sheets': manifest.get('sheets') or [],
                     'quality': manifest.get('quality') or {},
                     'warnings': manifest.get('warnings') or [],
                     'createdAt': manifest.get('createdAt')}
            imports.append(entry)
            for sheet in entry['sheets']:
                rows_file = path.parent / sheet.get('rowsFile', '')
                if sheet.get('aggregated'):
                    aggregates.append({'importId': import_id, 'name': sheet.get('name'),
                                       'grain': sheet.get('grain'), 'rowCount': sheet.get('rowCount'),
                                       'rowsFile': str(rows_file), 'columns': sheet.get('metrics'),
                                       'source': entry['source']})
                    continue
                if sheet.get('grain') != 'match_player':
                    continue
                rows = self._read_jsonl(rows_file, warnings)
                sheet_matches.extend(self._sheet_matches_for(import_id, sheet, rows, entry, warnings))
        return sheet_matches, imports, aggregates

    def _read_jsonl(self, path, warnings, limit=200_000):
        rows = []
        if not Path(path).is_file():
            return rows
        try:
            with Path(path).open(encoding='utf-8') as handle:
                for line in handle:
                    if line.strip():
                        rows.append(json.loads(line))
                        if len(rows) >= limit:
                            warnings.append(f'{Path(path).name} 行数超过 {limit}，只读取前 {limit} 行。')
                            break
        except (OSError, json.JSONDecodeError) as error:
            warnings.append(f'表格行读取失败 {Path(path).name}：{error}')
        return rows

    def _sheet_matches_for(self, import_id, sheet, rows, entry, warnings):
        groups = defaultdict(list)
        for row in rows:
            keys = row.get('keys') or {}
            match_key = keys.get('matchId') or keys.get('matchNo')
            if not match_key:
                date = keys.get('date') or (row.get('dimensions') or {}).get('date')
                if date:
                    match_key = str(date)
            if not match_key:
                continue
            groups[str(match_key)].append(row)
        if not groups:
            warnings.append(f'表格 {import_id}/{sheet.get("name")} 缺少对局ID/场次号，未纳入单局分析。')
            return []
        if all(not ((row.get('keys') or {}).get('matchId') or (row.get('keys') or {}).get('matchNo'))
               for row in rows if (row.get('keys') or {}).get('date')):
            warnings.append(f'表格 {import_id}/{sheet.get("name")} 只有日期没有对局ID/场次号，'
                            f'同一天的多个对局可能被合并。')
        result = []
        for match_key, group in groups.items():
            players = []
            for row in group:
                keys, dimensions, metrics = row.get('keys') or {}, row.get('dimensions') or {}, row.get('metrics') or {}
                def metric(name):
                    item = metrics.get(name)
                    return item.get('value') if isinstance(item, dict) else None
                label = clean(keys.get('player')) or keys.get('hero') or '未知队员'
                player = {
                    'playerId': None, 'label': label,
                    'camp': keys.get('side') or dimensions.get('side') or 'unknown',
                    'side': keys.get('side') or dimensions.get('side') or 'unknown',
                    'slot': keys.get('slot'), 'hero': clean(keys.get('hero')),
                    # 单局表的分路/对手/训练组/本队阵营由 infer_profile 归到 keys（模板 18 列都走 keys），
                    # 只有胜负在 dimensions；这里两处都读，避免表格入库后分路和对手整列丢失。
                    'position': lane_name(keys.get('position') or dimensions.get('position')),
                    'kills': metric('kills'), 'deaths': metric('deaths'), 'assists': metric('assists'),
                    'gold': metric('gold') or metric('avgGold'), 'damage': metric('damage') or metric('avgDamage'),
                    'taken': metric('taken') or metric('avgTaken'),
                    'participation': metric('participation'), 'rating': metric('rating'),
                    'result': ('win' if dimensions.get('win') == 1 else 'loss')
                    if dimensions.get('win') in (0, 1) else None,
                    'finalSource': 'sheet', 'process': None,
                }
                player['partial'] = not _complete(player)
                players.append(player)
            first = group[0]
            keys, dimensions = first.get('keys') or {}, first.get('dimensions') or {}
            duration = None
            for row in group:
                item = (row.get('metrics') or {}).get('duration')
                if isinstance(item, dict) and item.get('value') is not None:
                    duration = item['value']
                    break
            # 表格里没有营地的终局比分，用双方击杀合计还原；胜负优先取「胜负」列，
            # 缺失时才按比分比较。本队阵营取表格的「本队阵营」列，缺了就留空、不猜。
            scores = {}
            for camp in ('blue', 'red'):
                values = [player['kills'] for player in players if player['camp'] == camp]
                if len(values) == 5 and all(isinstance(value, (int, float)) for value in values):
                    scores[camp] = int(sum(values))
            results = {'blue': set(), 'red': set()}
            for player in players:
                if player.get('result') in ('win', 'loss'):
                    results[player['camp']].add(player['result'])
            outcomes = {camp: next(iter(values)) for camp, values in results.items() if len(values) == 1}
            winner = None
            if outcomes.get('blue') == 'win' and outcomes.get('red') == 'loss':
                winner = 'blue'
            elif outcomes.get('red') == 'win' and outcomes.get('blue') == 'loss':
                winner = 'red'
            if winner is None and scores.get('blue') is not None and scores.get('red') is not None \
                    and scores['blue'] != scores['red']:
                winner = 'blue' if scores['blue'] > scores['red'] else 'red'
            own = str(keys.get('ownSide') or sheet.get('ownSide') or '').strip().lower()
            own = own if own in ('blue', 'red') else None
            result.append({
                'key': f'sheet-{import_id[:8]}-{sheet.get("name")}-{match_key}',
                'dbId': None, 'bundleKey': None, 'sources': ['sheet'], 'source': 'sheet',
                'date': keys.get('date') or dimensions.get('date'), 'dateText': keys.get('date') or dimensions.get('date'),
                'duration': duration, 'opponent': keys.get('opponent') or dimensions.get('opponent') or '',
                'session': dimensions.get('session') or keys.get('session') or '',
                'version': dimensions.get('version') or keys.get('version') or '',
                'mode': None, 'title': entry.get('source', {}).get('name'),
                'ownSide': ('left' if own == 'blue' else 'right') if own else None,
                'ownCamp': own, 'winner': winner, 'scores': scores,
                'players': players, 'process': None,
                'warnings': ['表格来源，可能与本机记录重复；未自动去重。'],
                'status': 'sheet',
            })
        return result

    # ---------- flat metrics ----------
    def _flat_rows(self, matches, warnings):
        rows = []
        for match in matches:
            minutes = _minutes(match.get('duration'))
            team_totals = {}
            for camp in {player.get('camp') for player in match['players']}:
                members = [player for player in match['players'] if player.get('camp') == camp]
                totals = {}
                for key in ('kills', 'gold', 'damage', 'taken'):
                    values = [member.get(key) for member in members]
                    totals[key] = sum(values) if len(members) == 5 and all(value is not None for value in values) else None
                team_totals[camp] = {'players': len(members), 'totals': totals,
                                     'complete': len(members) == 5 and all(totals[key] is not None for key in totals)}
            match['teamTotals'] = team_totals
            for player in match['players']:
                camp = player.get('camp')
                totals = team_totals.get(camp, {}).get('totals', {})
                kills, deaths, assists = player.get('kills'), player.get('deaths'), player.get('assists')
                kda = (kills + assists) / max(1, deaths) if all(value is not None for value in (kills, deaths, assists)) else None
                complete = _complete(player)
                partial = bool(player.get('partial')) or not complete
                full = not partial
                row = {
                    'matchKey': match['key'], 'sources': match['sources'], 'source': match['source'],
                    'campBacked': bool(match.get('campBacked')),
                    'date': match.get('date'), 'dateKey': date_key(match.get('date'))[0],
                    'dateFull': date_key(match.get('date'))[1],
                    'duration': match.get('duration'), 'minutes': minutes,
                    'opponent': match.get('opponent') or '', 'session': match.get('session') or '',
                    'version': match.get('version') or '', 'mode': match.get('mode') or '',
                    'title': match.get('title') or '',
                    'seed': _is_seed_title(match.get('title')),
                    'playerId': player.get('playerId'),
                    # 本队昵称不再带阵营令牌：本机记录写 left/right、数据包写 blue/red，
                    # 同一个昵称会因为来源不同被拆成两条「选手」。
                    'playerKey': player.get('playerId') or (
                        f"label:{clean(player.get('label'))}"
                        if camp and camp == match.get('ownCamp')
                        else f"label:{camp}:{clean(player.get('label'))}"),
                    'label': clean(player.get('label')) or player.get('hero') or '未知队员',
                    'rawLabel': player.get('rawLabel') or player.get('label'),
                    'bound': bool(player.get('playerId')),
                    'camp': camp, 'hero': player.get('hero') or '',
                    'position': lane_name(player.get('position')),
                    'kills': kills, 'deaths': deaths, 'assists': assists,
                    'gold': player.get('gold'), 'damage': player.get('damage'),
                    'taken': player.get('taken'),
                    'participation': player.get('participation')
                    if player.get('participation') is not None
                    else (round((kills + assists) / totals['kills'] * 100, 1)
                          if totals.get('kills') and kills is not None and assists is not None else None),
                    'participationComputed': player.get('participation') is None
                    and totals.get('kills') is not None and kills is not None and assists is not None,
                    'rating': player.get('rating'), 'kda': round(kda, 3) if kda is not None else None,
                    'kdaPerfect': bool(deaths == 0 and kills is not None and assists is not None),
                    'gpm': round(player['gold'] / minutes, 2) if full and player.get('gold') is not None and minutes else None,
                    'dpm': round(player['damage'] / minutes, 2) if full and player.get('damage') is not None and minutes else None,
                    'tpm': round(player['taken'] / minutes, 2) if full and player.get('taken') is not None and minutes else None,
                    'goldShare': round(player['gold'] / totals['gold'] * 100, 2)
                    if full and player.get('gold') is not None and totals.get('gold') else None,
                    'damageShare': round(player['damage'] / totals['damage'] * 100, 2)
                    if full and player.get('damage') is not None and totals.get('damage') else None,
                    'takenShare': round(player['taken'] / totals['taken'] * 100, 2)
                    if full and player.get('taken') is not None and totals.get('taken') else None,
                    'finalSource': player.get('finalSource') or 'unknown',
                    'partial': partial,
                    'full': full,
                    'complete': complete,
                    'isOwn': None,
                    'result': player.get('result') or _result_for(
                        camp, match.get('winnerCamp') or match.get('winner'), match.get('scores')),
                    'process': player.get('process') or {},
                    # B 组扩展终局值：营地 battledetail 实测优先，缺失保持 None，
                    # 由 studio_analysis 在明确标记 derivedFields 后才允许派生。
                    'cs': number(player.get('cs')),
                    'jungleGold': number(player.get('jungleGold')),
                    'control': number(player.get('control')),
                    'healing': number(player.get('healing')),
                    'towerDamage': number(player.get('towerDamage')),
                    'damageConversion': number(player.get('damageConversion')),
                    'takenPerDeath': number(player.get('takenPerDeath')),
                }
                own = match.get('ownCamp')
                row['isOwn'] = bool(own and camp == own)
                rows.append(row)
        return rows

    def _sheet_flat_rows(self, sheet_matches, warnings):
        # 复用相同的指标口径，但保持 source=sheet；默认过滤不包含它。
        return self._flat_rows(sheet_matches, warnings)

    # ---------- query ----------
    def _selected_rows(self, filters):
        sources = filters.get('sources') or DEFAULT_SOURCES
        sources = [source for source in sources if source in ALL_SOURCES] or list(DEFAULT_SOURCES)
        rows = list(self.get()['rows'])
        if 'sheet' in sources:
            rows += self.get()['sheetRows']
        rows = [row for row in rows if row['source'] in sources]
        warnings = []
        if filters.get('from') or filters.get('to'):
            partial = sum(1 for row in rows if not row.get('dateFull'))
            if partial:
                warnings.append(f'{partial} 行只有月日，日期筛选会排除这些行。')
        def keep(row):
            if filters.get('campOnly') and not row.get('campBacked'):
                return False
            if filters.get('excludeSeeds') and row.get('seed'):
                return False
            if filters.get('from') and row.get('dateKey') and row['dateKey'] < filters['from']:
                return False
            if filters.get('to') and row.get('dateKey') and row['dateKey'] > filters['to']:
                return False
            if filters.get('player') and filters['player'] not in (row.get('playerKey'), row.get('playerId'), row.get('label')):
                return False
            if filters.get('hero') and row.get('hero') != filters['hero']:
                return False
            if filters.get('position') and row.get('position') != filters['position']:
                return False
            if filters.get('opponent') and filters['opponent'].strip().lower() not in (row.get('opponent') or '').lower():
                return False
            if filters.get('session') and filters['session'].strip().lower() not in (row.get('session') or '').lower():
                return False
            if filters.get('version') and filters['version'].strip().lower() not in (row.get('version') or '').lower():
                return False
            if filters.get('result') and row.get('result') != filters['result']:
                return False
            if filters.get('camp') and row.get('camp') != filters['camp']:
                return False
            return True
        return [row for row in rows if keep(row)], warnings

    def _selected_matches(self, filters):
        rows, warnings = self._selected_rows(filters)
        keys = {row['matchKey'] for row in rows}
        matches = [match for match in self.get()['matches'] + self.get()['sheetMatches']
                   if match['key'] in keys]
        return matches, warnings

    def _aggregate_rows(self, filters):
        rows, warnings = self._selected_rows(filters)
        if filters.get('ownOnly'):
            rows = [row for row in rows if row.get('isOwn')]
        if filters.get('includePartial'):
            return rows, warnings
        return [row for row in rows if row.get('full')], warnings

    def filters(self):
        data = self.get()
        rows = data['rows'] + data['sheetRows']
        players = {}
        for row in rows:
            key = row['playerKey']
            players.setdefault(key, {'key': key, 'label': row['label'],
                                     'bound': row['bound'], 'sources': set()})
            players[key]['sources'].add(row['source'])
        player_list = [{'key': item['key'], 'label': item['label'], 'bound': item['bound'],
                        'sources': sorted(item['sources'])} for item in players.values()]
        return {
            'dates': sorted({row['date'] for row in rows if row.get('date')}, reverse=True),
            'players': sorted(player_list, key=lambda item: (not item['bound'], item['label'])),
            'heroes': sorted({row['hero'] for row in rows if row.get('hero')}),
            'opponents': sorted({row['opponent'] for row in rows if row.get('opponent')}),
            'sessions': sorted({row['session'] for row in rows if row.get('session')}),
            'versions': sorted({row['version'] for row in rows if row.get('version')}),
            'sources': [{'key': 'db', 'label': '本机记录'}, {'key': 'bundle', 'label': '录像数据包'},
                        {'key': 'sheet', 'label': '表格导入'}],
            'results': [{'key': key, 'label': label} for key, label in RESULT_NAMES.items()],
        }

    def overview(self, filters, include_top=True):
        rows, filter_warnings = self._selected_rows(filters)
        matches, _ = self._selected_matches(filters)
        own_results = {}
        for row in rows:
            if row.get('isOwn'):
                own_results[row['matchKey']] = row['result']
        wins = sum(1 for result in own_results.values() if result == 'win')
        decided = sum(1 for result in own_results.values() if result in ('win', 'loss'))
        players = {row['playerKey'] for row in rows}
        heroes = {row['hero'] for row in rows if row['hero']}
        timeline = sum(1 for match in matches if (match.get('process') or {}).get('timeline'))
        snapshots = sum(1 for match in matches if (match.get('process') or {}).get('scoreboardSnapshots'))
        pov = sum(1 for match in matches
                  if any((player.get('process') or {}).get('pov') for player in match['players']))
        complete_matches = sum(1 for match in matches
                               if match['players'] and all(_complete(player) and not player.get('partial')
                                                           for player in match['players']))
        partial_rows = sum(1 for row in rows if row.get('partial'))
        unknown_opponent = sum(1 for match in matches if not match.get('opponent'))
        if partial_rows and not filters.get('includePartial'):
            filter_warnings.append(f'{partial_rows} 行是过程/部分数据，未计入队员/英雄/团队统计；'
                                   f'可勾选“包含部分数据”查看快照。')
        result = {
            'teamName': self.get()['teamName'],
            'coach': (self.get().get('profile') or {}).get('coach') or '',
            'season': (self.get().get('profile') or {}).get('season') or '',
            'matches': len(matches), 'decided': decided, 'wins': wins,
            'winRate': round(wins / decided * 100, 1) if decided else None,
            'players': len(players), 'heroes': len(heroes),
            # 本队口径：首页和英雄页要的是「我们自己的」，不含对手。
            'ownPlayers': len({row['label'] for row in rows if row.get('isOwn') and row.get('label')}),
            'ownHeroes': len({row['hero'] for row in rows if row.get('isOwn') and row['hero']}),
            'boundPlayers': len({row['playerId'] for row in rows if row.get('isOwn') and row.get('playerId')}),
            'rows': len(rows), 'sources': filters.get('sources') or list(DEFAULT_SOURCES),
            'coverage': {'timelineMatches': timeline, 'scoreboardMatches': snapshots,
                         'povMatches': pov, 'completeMatches': complete_matches,
                         'partialRows': partial_rows, 'unknownOpponentMatches': unknown_opponent},
            'inventory': {'dbMatches': sum(1 for match in self.get()['matches'] if 'db' in match['sources']),
                          'bundleMatches': sum(1 for match in self.get()['matches'] if 'bundle' in match['sources']),
                          'sheetMatches': len(self.get()['sheetMatches']),
                          'imports': len(self.get()['imports']),
                          'aggregateTables': len(self.get()['aggregates']),
                          'drafts': self.get()['drafts']},
            'dataQuality': self._data_quality(matches),
            'profile': self.get().get('profile') or {},
            'warnings': list(dict.fromkeys(self.get()['warnings'] + filter_warnings)),
        }
        if include_top:
            result['topPlayers'] = self.player_stats(filters)[:5]
            result['topHeroes'] = self.hero_stats(filters)[:5]
        return result

    @staticmethod
    def _is_seed_match(match):
        return _is_seed_title(match.get('title'))

    def _data_quality(self, matches):
        """档案体检：教练打开就能看到「哪些数字是可信的、哪些还缺」。

        只报事实，不估算；每项都给出分母，避免拿 0 场当 0%。
        """
        total = len(matches)
        checks = []

        def add(key, label, missing, hint):
            checks.append({'key': key, 'label': label, 'ok': max(0, total - missing),
                           'missing': missing, 'total': total, 'hint': hint})

        add('opponent', '对手', sum(1 for m in matches if not m.get('opponent')),
            '对手决定交手记录与对手英雄，缺失时这些页面为空')
        add('duration', '时长', sum(1 for m in matches if not m.get('duration')),
            '没有时长就无法换算分均经济/输出，也判断不了经济差的时间位置')
        add('curve', '经济差', sum(
            1 for m in matches
            if not ((m.get('process') or {}).get('timeline') and m.get('duration'))),
            '需要「经济时间轴 + 时长」同时具备，才算得出 10 分钟领先、经济转折')
        add('lane', '分路', sum(
            1 for m in matches
            if not any(p.get('position') for p in m.get('players', []))),
            '没有分路就无法做同位置对位，只能看个人总量')
        own_unbound = 0
        for match in matches:
            own = match.get('ownCamp') or match.get('ownSide')
            for player in match.get('players', []):
                camp = player.get('camp') or player.get('side')
                if own and camp and camp != own:
                    continue
                if not player.get('playerId'):
                    own_unbound += 1
                    break
        add('identity', '选手绑定', own_unbound,
            '未绑定的昵称会拆散个人数据，无法跨局对比')
        seeded = sum(1 for m in matches if self._is_seed_match(m))
        quality_score = None
        if total:
            quality_score = round(sum(item['ok'] for item in checks) / (len(checks) * total) * 100)
        return {
            'score': quality_score,
            'total': total,
            'seedMatches': seeded,
            'checks': checks,
        }

    def player_stats(self, filters):
        rows, _ = self._aggregate_rows(filters)
        groups = defaultdict(list)
        for row in rows:
            groups[row['playerKey']].append(row)
        result = []
        for key, items in groups.items():
            matches = {item['matchKey'] for item in items}
            wins = sum(1 for item in items if item['result'] == 'win')
            decided = sum(1 for item in items if item['result'] in ('win', 'loss'))
            k = [item['kills'] for item in items if item['kills'] is not None]
            d = [item['deaths'] for item in items if item['deaths'] is not None]
            a = [item['assists'] for item in items if item['assists'] is not None]
            full_items = [item for item in items if item.get('full')]
            # 按分钟聚合的指标必须分子分母同样本：只统计「数值和时长都存在」的行，
            # 否则时长缺失的局会把它们的数值摊进别人的分母里（GPM/DPM 曾因此虚高）。
            gold_minutes = [(item['gold'], item['minutes']) for item in full_items
                            if item['minutes'] and item['gold'] is not None]
            damage_minutes = [(item['damage'], item['minutes']) for item in full_items
                              if item['minutes'] and item['damage'] is not None]
            taken_minutes = [(item['taken'], item['minutes']) for item in full_items
                             if item['minutes'] and item['taken'] is not None]
            gold = [g for g, _m in gold_minutes]
            damage = [d for d, _m in damage_minutes]
            taken = [v for v, _m in taken_minutes]
            minutes = sum(m for _g, m in gold_minutes)
            minutes_damage = sum(m for _d, m in damage_minutes)
            minutes_taken = sum(m for _v, m in taken_minutes)
            shares = [item['goldShare'] for item in items if item['goldShare'] is not None]
            damage_shares = [item['damageShare'] for item in items if item['damageShare'] is not None]
            taken_shares = [item['takenShare'] for item in items if item['takenShare'] is not None]
            participation = [item['participation'] for item in items if item['participation'] is not None]
            ratings = [item['rating'] for item in items if item['rating'] is not None]
            heroes = Counter(item['hero'] for item in items if item['hero'])
            last = max((item['dateKey'] for item in items if item['dateKey']), default=None)
            result.append({
                'playerKey': key, 'playerId': items[0].get('playerId'),
                'label': items[0]['label'], 'bound': items[0]['bound'],
                'matches': len(matches), 'wins': wins, 'decided': decided,
                'winRate': round(wins / decided * 100, 1) if decided else None,
                'kills': sum(k), 'deaths': sum(d), 'assists': sum(a), 'kdaSamples': min(len(k), len(d), len(a)),
                'kda': round((sum(k) + sum(a)) / max(1, sum(d)), 2) if k and d and a else None,
                'kdaPerfectMatches': sum(1 for item in items if item.get('kdaPerfect')),
                'gpm': round(sum(gold) / minutes, 1) if gold and minutes else None,
                'gpmMinutes': round(minutes, 1),
                'dpm': round(sum(damage) / minutes_damage, 1) if damage and minutes_damage else None,
                'tpm': round(sum(taken) / minutes_taken, 1) if taken and minutes_taken else None,
                'goldShare': round(sum(shares) / len(shares), 1) if shares else None,
                'goldShareSamples': len(shares),
                'damageShare': round(sum(damage_shares) / len(damage_shares), 1) if damage_shares else None,
                'takenShare': round(sum(taken_shares) / len(taken_shares), 1) if taken_shares else None,
                'participation': round(sum(participation) / len(participation), 1) if participation else None,
                'participationSamples': len(participation),
                'rating': round(sum(ratings) / len(ratings), 2) if ratings else None,
                'heroes': [{'hero': hero, 'matches': count} for hero, count in heroes.most_common()],
                'positions': sorted({item['position'] for item in items if item['position']}),
                'sources': sorted({item['source'] for item in items}),
                'fullRows': len(full_items),
                'partialRows': sum(1 for item in items if item['partial']),
                'lastDate': last,
            })
        return sorted(result, key=lambda row: (-row['matches'], -(row['winRate'] or 0), row['label']))

    def player_board(self, filters):
        """教练视角的选手页：名单、未认领昵称、状态与搭档一次返回。

        名单取自建档，位置优先用名单字段；未认领昵称不进入名单与状态，
        只按来源昵称统计。状态用营地评分，近 3 场与此前 3 场对比，
        少于 6 场评分不给趋势结论。
        """
        rows, warnings = self._aggregate_rows(filters)
        stats = self.player_stats(filters)
        profile = self.get().get('profile') or {}
        team = (profile.get('teamName') or '').strip()
        members = [member for member in profile.get('members', [])
                   if not member.get('archived')
                   and (not member.get('team') or member.get('team') == team)]
        by_player = defaultdict(list)
        for row in rows:
            if row.get('playerId'):
                by_player[row['playerId']].append(row)
        stat_by_id = {item['playerId']: item for item in stats if item.get('playerId')}
        roster = []
        for member in members:
            items = by_player.get(member['id'], [])
            summary = stat_by_id.get(member['id']) or {}
            lane = member.get('position') or ''
            if not lane and items:
                counts = Counter(row.get('position') for row in items if row.get('position'))
                lane = counts.most_common(1)[0][0] if counts else ''
            roster.append({
                'id': member['id'],
                'label': member.get('label') or member.get('name') or member['id'],
                'position': lane,
                'games': summary.get('matches') or 0,
                'wins': summary.get('wins') or 0,
                'decided': summary.get('decided') or 0,
                'winRate': summary.get('winRate'),
                'kda': summary.get('kda'),
                'gpm': summary.get('gpm'),
                'dpm': summary.get('dpm'),
                'participation': summary.get('participation'),
                'lastDate': summary.get('lastDate'),
                'heroes': (summary.get('heroes') or [])[:4],
                'played': bool(summary.get('matches')),
            })
        form = []
        for summary in stats:
            if not (summary.get('bound') and summary.get('playerId')):
                continue
            items = sorted(by_player.get(summary['playerId'], []),
                           key=lambda row: (row.get('dateKey') or '', row['matchKey']))
            ratings = [row['rating'] for row in items if row.get('rating') is not None]
            entry = {'id': summary['playerId'], 'label': summary['label'],
                     'games': summary.get('matches') or 0, 'samples': len(ratings),
                     'available': False, 'reason': '评分不足 6 场'}
            if len(ratings) >= 6:
                prior, recent = ratings[-6:-3], ratings[-3:]
                prior_mean, recent_mean = sum(prior) / 3, sum(recent) / 3
                delta = recent_mean - prior_mean
                entry.update({'available': True, 'reason': '',
                              'prior': round(prior_mean, 1), 'recent': round(recent_mean, 1),
                              'delta': round(delta, 1),
                              'tone': 'up' if delta >= 0.5 else 'down' if delta <= -0.5 else 'flat'})
            form.append(entry)
        pairs = [item for item in self.pairs(filters).get('pairs', []) if item['games'] >= 3][:6]
        unbound = sorted((item for item in stats if not item.get('bound')),
                         key=lambda item: (-item['matches'], item['label']))
        unbound_keys = {item['playerKey'] for item in unbound}
        played = sum(1 for item in roster if item['played'])
        return {
            'teamName': team,
            'players': stats,
            'roster': roster,
            'form': form,
            'pairs': pairs,
            'unbound': [{'label': item['label'], 'games': item['matches'],
                         'lastDate': item['lastDate']} for item in unbound],
            'summary': {
                'matches': len({row['matchKey'] for row in rows}),
                'roster': len(roster),
                'played': played,
                'bench': len(roster) - played,
                'unbound': len(unbound),
                'unboundGames': len({row['matchKey'] for row in rows
                                     if row['playerKey'] in unbound_keys}),
                'rising': sum(1 for item in form if item.get('tone') == 'up'),
                'falling': sum(1 for item in form if item.get('tone') == 'down'),
                'formReady': sum(1 for item in form if item.get('available')),
            },
            'warnings': warnings,
        }

    def player_trend(self, player_key, filters):
        rows, warnings = self._aggregate_rows(filters)
        items = [row for row in rows if row['playerKey'] == player_key]
        items.sort(key=lambda row: (_sort_date(row.get('date')), row['matchKey']))
        return {'playerKey': player_key,
                'label': items[0]['label'] if items else player_key,
                'points': [{
                    'matchKey': row['matchKey'], 'date': row['date'], 'opponent': row['opponent'],
                    'result': row['result'], 'hero': row['hero'],
                    'kills': row['kills'], 'deaths': row['deaths'], 'assists': row['assists'],
                    'kda': row['kda'], 'gold': row['gold'], 'gpm': row['gpm'],
                    'damage': row['damage'], 'dpm': row['dpm'],
                    'participation': row['participation'], 'rating': row['rating'],
                    'partial': row['partial'], 'source': row['source'],
                } for row in items],
                'warnings': warnings}

    def hero_stats(self, filters):
        rows, _ = self._aggregate_rows(filters)
        if filters.get('ownOnly'):
            rows = [row for row in rows if row.get('isOwn')]
        groups = defaultdict(list)
        for row in rows:
            if row['hero']:
                groups[row['hero']].append(row)
        result = []
        for hero, items in groups.items():
            wins = sum(1 for item in items if item['result'] == 'win')
            decided = sum(1 for item in items if item['result'] in ('win', 'loss'))
            k = [item['kills'] for item in items if item['kills'] is not None]
            d = [item['deaths'] for item in items if item['deaths'] is not None]
            a = [item['assists'] for item in items if item['assists'] is not None]
            full_items = [item for item in items if item.get('full')]
            gold_minutes = [(item['gold'], item['minutes']) for item in full_items
                            if item['minutes'] and item['gold'] is not None]
            damage_minutes = [(item['damage'], item['minutes']) for item in full_items
                              if item['minutes'] and item['damage'] is not None]
            gold = [g for g, _m in gold_minutes]
            damage = [d for d, _m in damage_minutes]
            minutes = sum(m for _g, m in gold_minutes)
            minutes_damage = sum(m for _d, m in damage_minutes)
            result.append({
                'hero': hero, 'picks': len(items), 'wins': wins, 'decided': decided,
                'winRate': round(wins / decided * 100, 1) if decided else None,
                'fullPicks': len(full_items), 'partialPicks': len(items) - len(full_items),
                'kda': round((sum(k) + sum(a)) / max(1, sum(d)), 2) if k and d and a else None,
                'gpm': round(sum(gold) / minutes, 1) if gold and minutes else None,
                'dpm': round(sum(damage) / minutes_damage, 1) if damage and minutes_damage else None,
                'players': sorted({item['label'] for item in items}),
                'positions': sorted({item['position'] for item in items if item.get('position')}),
                'matches': sorted({item['matchKey'] for item in items}),
            })
        return sorted(result, key=lambda row: (-row['picks'], -(row['winRate'] or 0), row['hero']))

    def team_stats(self, filters):
        matches, _ = self._selected_matches(filters)
        own_matches = [match for match in matches
                       if match.get('ownCamp') and any(player.get('camp') == match['ownCamp'] for player in match['players'])]
        wins = sum(1 for match in own_matches
                   if _result_for(match.get('ownCamp'), match.get('winnerCamp') or match.get('winner'),
                                  match.get('scores')) == 'win')
        decided = sum(1 for match in own_matches
                      if _result_for(match.get('ownCamp'), match.get('winnerCamp') or match.get('winner'),
                                     match.get('scores')) in ('win', 'loss'))
        totals = {'gold': [], 'kills': [], 'damage': [], 'taken': [], 'goldDiff': []}
        full_matches = 0
        for match in own_matches:
            own_camp = match.get('ownCamp')
            own_players = [player for player in match.get('players', []) if player.get('camp') == own_camp]
            team_full = len(own_players) == 5 and all(
                player.get('full', _complete(player) and not player.get('partial')) for player in own_players)
            if team_full:
                full_matches += 1
            own_total = (match.get('teamTotals') or {}).get(own_camp, {})
            other = next((camp for camp in (match.get('teamTotals') or {}) if camp != own_camp), None)
            other_total = (match.get('teamTotals') or {}).get(other, {})
            if team_full and own_total.get('complete'):
                for key in ('gold', 'kills', 'damage', 'taken'):
                    if own_total['totals'].get(key) is not None:
                        totals[key].append(own_total['totals'][key])
                if other_total.get('complete') and own_total['totals'].get('gold') is not None and other_total['totals'].get('gold') is not None:
                    totals['goldDiff'].append(own_total['totals']['gold'] - other_total['totals']['gold'])
        opponents = defaultdict(lambda: {'matches': 0, 'wins': 0, 'decided': 0})
        for match in own_matches:
            name = match.get('opponent') or '未知对手'
            bucket = opponents[name]
            bucket['matches'] += 1
            result = _result_for(match.get('ownCamp'), match.get('winnerCamp') or match.get('winner'),
                                 match.get('scores'))
            if result in ('win', 'loss'):
                bucket['decided'] += 1
                bucket['wins'] += result == 'win'
        side = Counter(match.get('ownCamp') for match in own_matches if match.get('ownCamp'))
        return {
            'available': bool(own_matches), 'matches': len(own_matches), 'fullMatches': full_matches,
            'wins': wins, 'decided': decided,
            'winRate': round(wins / decided * 100, 1) if decided else None,
            'avgGold': round(sum(totals['gold']) / len(totals['gold']), 1) if totals['gold'] else None,
            'avgKills': round(sum(totals['kills']) / len(totals['kills']), 1) if totals['kills'] else None,
            'avgDamage': round(sum(totals['damage']) / len(totals['damage']), 1) if totals['damage'] else None,
            'avgTaken': round(sum(totals['taken']) / len(totals['taken']), 1) if totals['taken'] else None,
            'avgGoldDiff': round(sum(totals['goldDiff']) / len(totals['goldDiff']), 1) if totals['goldDiff'] else None,
            'side': dict(side),
            'opponents': [{'name': name, **bucket,
                           'winRate': round(bucket['wins'] / bucket['decided'] * 100, 1) if bucket['decided'] else None}
                          for name, bucket in sorted(opponents.items(), key=lambda item: -item[1]['matches'])],
            'samples': {'gold': len(totals['gold']), 'goldDiff': len(totals['goldDiff'])},
        }

    def matches(self, filters):
        matches, warnings = self._selected_matches(filters)
        result = []
        for match in matches:
            own_camp = match.get('ownCamp')
            own, enemy = self._camp_totals(match, own_camp)
            result.append({
                'key': match['key'], 'date': match.get('date'), 'dateText': match.get('dateText'),
                'opponent': match.get('opponent'), 'session': match.get('session'),
                'version': match.get('version'), 'duration': match.get('duration'),
                'mode': match.get('mode'), 'title': match.get('title'),
                'sources': match.get('sources'), 'source': match.get('source'),
                'ownCamp': own_camp,
                'result': _result_for(own_camp, match.get('winnerCamp') or match.get('winner'), match.get('scores')),
                'scores': match.get('scores'), 'players': len(match.get('players', [])),
                'complete': all(_complete(player) for player in match.get('players', [])),
                'hasTimeline': bool((match.get('process') or {}).get('timeline')),
                'hasScoreboard': bool((match.get('process') or {}).get('scoreboardSnapshots')),
                'hasPov': any((player.get('process') or {}).get('pov') for player in match.get('players', [])),
                'warnings': len(match.get('warnings') or []),
                'isSeed': self._is_seed_match(match),
                'own': own, 'enemy': enemy,
                'goldDiff': self._final_gold_diff(match, own_camp),
                'missing': self._match_gaps(match),
                'heroes': [player.get('hero') for player in match.get('players', [])
                           if player.get('hero') and (player.get('camp') or player.get('side')) == own_camp][:5],
            })
        return {'matches': result, 'warnings': warnings}

    @staticmethod
    def _camp_totals(match, own_camp):
        """本队/对手五项合计；只用来做卡片摘要，不参与正式统计。"""
        def totals(camp):
            players = [p for p in match.get('players', [])
                       if camp and (p.get('camp') or p.get('side')) == camp]
            if not players:
                return None
            out = {'kills': 0, 'deaths': 0, 'assists': 0, 'gold': 0, 'damage': 0, 'games': len(players)}
            for player in players:
                for key in ('kills', 'deaths', 'assists', 'gold', 'damage'):
                    value = player.get(key)
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        out[key] += value
            out['kda'] = round((out['kills'] + out['assists']) / max(1, out['deaths']), 2)
            return out
        enemy_camp = {'blue': 'red', 'red': 'blue'}.get(own_camp)
        return totals(own_camp), totals(enemy_camp)

    @staticmethod
    def _final_gold_diff(match, own_camp):
        timeline = (match.get('process') or {}).get('timeline') or []
        if own_camp not in ('blue', 'red'):
            return None
        last = None
        for point in timeline:
            try:
                blue, red = float(point.get('blueGold')), float(point.get('redGold'))
            except (TypeError, ValueError):
                continue
            if math.isfinite(blue) and math.isfinite(red):
                last = (blue - red) if own_camp == 'blue' else (red - blue)
        return None if last is None else round(last)

    @staticmethod
    def _match_gaps(match):
        """这场「教练想问但答不了」的问题，按影响排序。"""
        gaps = []
        if not match.get('opponent'):
            gaps.append('对手')
        if not match.get('duration'):
            gaps.append('时长')
        if not (match.get('process') or {}).get('timeline'):
            gaps.append('经济时间轴')
        own = match.get('ownCamp') or match.get('ownSide')
        positions = [p for p in match.get('players', []) if p.get('position')]
        if not positions:
            gaps.append('分路')
        for player in match.get('players', []):
            camp = player.get('camp') or player.get('side')
            if own and camp and camp != own:
                continue
            if not player.get('playerId'):
                gaps.append('选手绑定')
                break
        return gaps


    def match_detail(self, key):
        for match in self.get()['matches'] + self.get()['sheetMatches']:
            if match['key'] == key:
                detail = json.loads(json.dumps(match, ensure_ascii=False))
                own_camp = detail.get('ownCamp')
                winner = detail.get('winnerCamp') or detail.get('winner')
                detail['result'] = _result_for(own_camp, winner, detail.get('scores'))
                for player in detail.get('players', []):
                    player['result'] = player.get('result') or _result_for(
                        player.get('camp'), winner, detail.get('scores'))
                    player['kda'] = ((player.get('kills') or 0) + (player.get('assists') or 0)) / max(1, player.get('deaths') or 0) \
                        if all(player.get(key) is not None for key in ('kills', 'deaths', 'assists')) else None
                return detail
        return None

    # ---------- 深度分析：对位 / 画像 / 协同 / 过程 ----------
    # 口径见 README.md；缺数据保持缺省，不做估算。

    @staticmethod
    def _series_stats(values):
        if not values:
            return None
        n = len(values)
        mean = sum(values) / n
        variance = sum((value - mean) ** 2 for value in values) / n
        ordered = sorted(values)
        return {'n': n, 'mean': round(mean, 2), 'std': round(variance ** 0.5, 2),
                'floor': round(ordered[0], 2), 'ceil': round(ordered[-1], 2)}

    def lane_matchups(self, filters):
        """对线质量聚合：同分路双方都确认且各一人时，才生成终局经济差对照。"""
        matches, warnings = self._selected_matches(filters)
        positions = {lane: {'position': lane, 'n': 0, 'diffSum': 0, 'ahead': 0,
                            'aheadKnown': 0, 'aheadWins': 0, 'kdaDiffSum': 0.0, 'kdaDiffN': 0}
                     for lane in LANES}
        rows = []
        for match in matches:
            # 营地 bundle 用 blue/red，录入 db 用 left/right：统一到 left/right 再对齐
            own_camp = {'blue': 'left', 'red': 'right'}.get(match.get('ownCamp'), match.get('ownCamp'))
            if match.get('source') not in ('db', 'bundle') or own_camp not in ('left', 'right'):
                continue
            own_players, enemy_players = {}, {}
            for player in match['players']:
                lane = player.get('position')
                if lane not in positions:
                    continue
                target = own_players if player.get('camp') in (own_camp, {'left': 'blue', 'right': 'red'}[own_camp]) else enemy_players
                target.setdefault(lane, player)
            win = None
            # 数据包的 winner 固定为 None（不冒充胜负），真实胜负在 winnerCamp 里
            raw_winner = match.get('winner') or match.get('winnerCamp')
            match_winner = {'blue': 'left', 'red': 'right'}.get(raw_winner, raw_winner)
            if match_winner in ('left', 'right'):
                win = match_winner == own_camp
            for lane in LANES:
                own, enemy = own_players.get(lane), enemy_players.get(lane)
                if not own or not enemy or own.get('gold') is None or enemy.get('gold') is None:
                    continue
                diff = own['gold'] - enemy['gold']
                entry = positions[lane]
                entry['n'] += 1
                entry['diffSum'] += diff
                ahead = diff > 0
                if ahead:
                    entry['ahead'] += 1
                    if win is not None:
                        entry['aheadKnown'] += 1
                        entry['aheadWins'] += 1 if win else 0
                own_kda, enemy_kda = _kda_value(own), _kda_value(enemy)
                kda_diff = own_kda - enemy_kda if own_kda is not None and enemy_kda is not None else None
                if kda_diff is not None:
                    entry['kdaDiffSum'] += kda_diff
                    entry['kdaDiffN'] += 1
                rows.append({
                    'matchKey': match['key'], 'dbId': match.get('dbId'),
                    'date': match.get('date'), 'opponent': match.get('opponent') or '',
                    'position': lane, 'diff': diff, 'ahead': ahead, 'win': win,
                    'ownHero': own.get('hero') or '', 'enemyHero': enemy.get('hero') or '',
                    'ownLabel': own.get('label') or '', 'enemyLabel': enemy.get('label') or '',
                    'kdaDiff': round(kda_diff, 2) if kda_diff is not None else None,
                })
        out_positions = []
        for lane in LANES:
            entry = positions[lane]
            if not entry['n']:
                continue
            out_positions.append({
                'position': lane, 'n': entry['n'],
                'avgDiff': round(entry['diffSum'] / entry['n'], 0),
                'aheadRate': round(entry['ahead'] / entry['n'] * 100, 1),
                'winWhenAhead': round(entry['aheadWins'] / entry['aheadKnown'] * 100, 1)
                                if entry['aheadKnown'] else None,
                'avgKdaDiff': round(entry['kdaDiffSum'] / entry['kdaDiffN'], 2) if entry['kdaDiffN'] else None,
            })
        rows.sort(key=lambda row: (row.get('date') or ''), reverse=True)
        return {'positions': out_positions, 'rows': rows[:400], 'warnings': warnings}

    def profiles(self, filters):
        """队员资源画像：占比 vs 同位置基线、稳定性（均值/离散/地板/近期）。"""
        rows, warnings = self._selected_rows(filters)
        own = [row for row in rows if row.get('isOwn')]
        baselines = []
        for lane in LANES:
            lane_rows = [row for row in own if row.get('position') == lane and row.get('full')]
            if not lane_rows:
                continue

            def avg(key, _rows=lane_rows):
                values = [row.get(key) for row in _rows if row.get(key) is not None]
                return round(sum(values) / len(values), 1) if values else None

            baselines.append({'position': lane, 'n': len(lane_rows),
                              'goldShare': avg('goldShare'), 'damageShare': avg('damageShare'),
                              'takenShare': avg('takenShare'), 'dpm': avg('dpm'), 'tpm': avg('tpm'),
                              'kda': avg('kda'), 'participation': avg('participation')})
        baseline_map = {item['position']: item for item in baselines}
        metric_keys = ('kda', 'deaths', 'gold', 'damage', 'taken', 'participation', 'rating',
                       'gpm', 'dpm', 'tpm', 'goldShare', 'damageShare', 'takenShare')
        grouped = {}
        for row in own:
            if not row.get('bound'):
                continue
            entry = grouped.setdefault(row['playerKey'], {'label': row['label'], 'positions': {}, 'rows': []})
            if row.get('position'):
                entry['positions'][row['position']] = entry['positions'].get(row['position'], 0) + 1
            entry['rows'].append(row)
        players_out = []
        for key, entry in grouped.items():
            rows_p = entry['rows']
            metrics = {}
            for metric_key in metric_keys:
                series = sorted((row.get('dateKey') or '', row.get(metric_key)) for row in rows_p
                                if row.get(metric_key) is not None)
                stats = self._series_stats([value for _, value in series])
                if stats:
                    recent = [value for _, value in series][-5:]
                    stats['recent'] = round(sum(recent) / len(recent), 2)
                    stats['recentN'] = len(recent)
                metrics[metric_key] = stats
            main_position = max(entry['positions'], key=entry['positions'].get) if entry['positions'] else None
            deviations = {}
            base = baseline_map.get(main_position)
            if base:
                for share in ('goldShare', 'damageShare', 'takenShare'):
                    if metrics.get(share) and base.get(share) is not None:
                        deviations[share] = round(metrics[share]['mean'] - base[share], 1)
            players_out.append({'key': key, 'label': entry['label'], 'games': len(rows_p),
                                'mainPosition': main_position, 'positions': entry['positions'],
                                'metrics': metrics, 'deviations': deviations})
        players_out.sort(key=lambda item: -item['games'])
        hero_rows = {}
        for row in own:
            if row.get('hero') and row.get('kda') is not None:
                hero_rows.setdefault(row['hero'], []).append(row)
        hero_baselines = [{'hero': hero, 'n': len(hrows),
                           'kda': round(sum(item['kda'] for item in hrows) / len(hrows), 2)}
                          for hero, hrows in hero_rows.items()]
        hero_base_map = {item['hero']: item for item in hero_baselines}
        combos = {}
        for row in own:
            if row.get('bound') and row.get('hero') and row.get('kda') is not None:
                combos.setdefault((row['playerKey'], row['label'], row['hero']), []).append(row['kda'])
        comfort = []
        for (key, label, hero), kdas in combos.items():
            base = hero_base_map.get(hero)
            if base and len(kdas) >= 2 and base['n'] >= 2:
                mean = sum(kdas) / len(kdas)
                comfort.append({'playerKey': key, 'player': label, 'hero': hero, 'n': len(kdas),
                                'kda': round(mean, 2), 'baseline': base['kda'],
                                'delta': round(mean - base['kda'], 2)})
        comfort.sort(key=lambda item: abs(item['delta']), reverse=True)
        return {'baselines': baselines, 'players': players_out[:40],
                'heroBaselines': sorted(hero_baselines, key=lambda item: -item['n'])[:20],
                'comfort': comfort[:24], 'warnings': warnings}

    def pairs(self, filters):
        """本队两人同场协同：同场次数与胜负；配对基于绑定的队员身份。"""
        rows, warnings = self._selected_rows(filters)
        own = [row for row in rows if row.get('isOwn') and row.get('bound')]
        by_match = {}
        for row in own:
            by_match.setdefault(row['matchKey'], []).append(row)
        pairs = {}
        for match_rows in by_match.values():
            if len(match_rows) < 2:
                continue
            win = next((row.get('result') for row in match_rows if row.get('result') in ('win', 'loss')), None)
            items = sorted({row['playerKey']: row for row in match_rows}.values(), key=lambda row: row['playerKey'])
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    key = f"{a['playerKey']}|{b['playerKey']}"
                    entry = pairs.setdefault(key, {
                        'a': {'key': a['playerKey'], 'label': a['label'], 'position': a.get('position') or ''},
                        'b': {'key': b['playerKey'], 'label': b['label'], 'position': b.get('position') or ''},
                        'games': 0, 'wins': 0})
                    entry['games'] += 1
                    if win == 'win':
                        entry['wins'] += 1
        out = []
        for entry in pairs.values():
            entry['winRate'] = round(entry['wins'] / entry['games'] * 100, 1) if entry['games'] else None
            out.append(entry)
        out.sort(key=lambda item: -item['games'])
        return {'pairs': out, 'warnings': warnings}

    def process(self, filters):
        """时段分析：只统计时间轴覆盖 ≥60% 且本队阵营已知的比赛。"""
        scan_filters = dict(filters)
        scan_filters['includePartial'] = True
        matches, warnings = self._selected_matches(scan_filters)
        landmarks = (120, 240, 300, 600, 900)
        per_match = []
        agg = {'leadAt10Games': 0, 'leadAt10Wins': 0,
               'diffAt': {str(t): {'sum': 0, 'n': 0} for t in landmarks},
               'phases': {'early': {'sum': 0, 'n': 0}, 'mid': {'sum': 0, 'n': 0}, 'late': {'sum': 0, 'n': 0}},
               'comebacks': 0, 'blownLeads': 0, 'killTempoSum': 0.0, 'killTempoN': 0}
        for match in matches:
            timeline = (match.get('process') or {}).get('timeline') or []
            own = match.get('ownCamp')
            if len(timeline) < 2 or own not in ('blue', 'red'):
                continue
            duration = match.get('duration')
            if duration is None or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                continue
            points = []
            for point in timeline:
                try:
                    t = float(point.get('gameTime'))
                except (TypeError, ValueError):
                    continue
                blue, red = point.get('blueGold'), point.get('redGold')
                try:
                    blue, red = float(blue), float(red)
                except (TypeError, ValueError):
                    continue
                if not all(math.isfinite(v) for v in (t, blue, red)) or not 0 <= t <= duration or min(blue, red) < 0:
                    continue
                points.append((t, (blue - red) if own == 'blue' else (red - blue)))
            if len(points) < 2:
                continue
            points = sorted(dict(points).items())
            first_t, last_t = points[0][0], points[-1][0]
            duration = match.get('duration')
            coverage = (last_t - first_t) / duration if duration else None
            if duration and coverage < 0.6:
                continue

            def diff_at(t):
                if t < first_t or t > last_t:
                    return None
                for observed_t, diff in points:
                    if t == observed_t:
                        return diff
                for idx in range(1, len(points)):
                    t0, d0 = points[idx - 1]
                    t1, d1 = points[idx]
                    if t0 < t < t1:
                        if t1 - t0 > 120:
                            return None
                        return d0 + (d1 - d0) * (t - t0) / (t1 - t0)
                return None

            winner = match.get('winnerCamp') or match.get('winner')
            win = (winner == own) if winner in ('blue', 'red') else None
            diff_at_map = {str(t): diff_at(t) for t in landmarks}
            # 王者三段口径：0–4 前期 / 4–10 中期 / 10+ 后期。
            early = diff_at_map['240'] - points[0][1] if diff_at_map['240'] is not None else None
            mid = diff_at_map['600'] - diff_at_map['240'] if all(diff_at_map[k] is not None for k in ('240', '600')) else None
            late = points[-1][1] - diff_at_map['600'] if last_t > 600 and diff_at_map['600'] is not None else None
            sign_flips = 0
            last_sign = 0
            for _, diff in points:
                sign = 1 if diff > 0 else -1 if diff < 0 else 0
                if sign and last_sign and sign != last_sign:
                    sign_flips += 1
                if sign:
                    last_sign = sign
            kill_points = []
            final_scores = match.get('scores') or {}
            for point in timeline:
                try:
                    t, blue_kills, red_kills = float(point['gameTime']), float(point['blueKills']), float(point['redKills'])
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(math.isfinite(v) for v in (t, blue_kills, red_kills)) or not first_t <= t <= last_t or min(blue_kills, red_kills) < 0:
                    continue
                if any(isinstance(final_scores.get(camp), (int,float)) and value > final_scores[camp] for camp,value in [('blue',blue_kills),('red',red_kills)]):
                    continue
                kill_points.append((t, blue_kills, red_kills))
            kill_points.sort()
            kills_per_minute = None
            kills_source = None
            if len(kill_points) >= 2:
                monotonic = all(all(right[i] >= left[i] for i in (1,2)) for left,right in zip(kill_points,kill_points[1:]))
                elapsed = (kill_points[-1][0] - kill_points[0][0]) / 60
                if monotonic and elapsed > 0:
                    kills_per_minute = (sum(kill_points[-1][1:]) - sum(kill_points[0][1:])) / elapsed
                    kills_source = 'timeline'
            if kills_per_minute is None:
                # 营地官方回放只提供约 30 秒一个点的团队金币，timeline 的
                # blueKills/redKills 常为空；终局比分是双方真实击杀数（不是
                # 事件条数），配合结算时长可算整局击杀率。仅作为回退口径，
                # 有时间轴击杀快照时仍优先用 timeline。
                duration = number(match.get('duration'))
                blue_kills = number(final_scores.get('blue')) if final_scores.get('blue') is not None else number(final_scores.get('left'))
                red_kills = number(final_scores.get('red')) if final_scores.get('red') is not None else number(final_scores.get('right'))
                if (duration and duration > 0 and blue_kills is not None and red_kills is not None
                        and blue_kills >= 0 and red_kills >= 0):
                    kills_per_minute = (blue_kills + red_kills) / (duration / 60)
                    kills_source = 'final-score'
            lead_at_10 = diff_at_map['600'] > 0 if diff_at_map['600'] is not None else None
            entry = {
                'key': match['key'], 'date': match.get('date'), 'opponent': match.get('opponent') or '',
                'win': win, 'coverage': round(coverage * 100, 1) if coverage is not None else None,
                'points': [[round(t), round(d)] for t, d in points[::max(1, len(points) // 40)]],
                'diffAt': {str(t): round(diff_at_map[str(t)]) if diff_at_map[str(t)] is not None else None for t in landmarks},
                'phases': {'early': round(early) if early is not None else None, 'mid': round(mid) if mid is not None else None,
                           'late': round(late) if late is not None else None},
                'leadAt10': lead_at_10, 'signFlips': sign_flips,
                'finalDiff': round(points[-1][1]), 'observedEnd': last_t, 'observedStart': first_t, 'perspective': 'own-minus-enemy',
                'duration': match.get('duration'),
                'killsPerMinute': round(kills_per_minute, 2) if kills_per_minute is not None else None,
                'killsPerMinuteSource': kills_source,
            }
            per_match.append(entry)
            for t in landmarks:
                if diff_at_map[str(t)] is None:
                    continue
                agg['diffAt'][str(t)]['sum'] += diff_at_map[str(t)]
                agg['diffAt'][str(t)]['n'] += 1
            for phase, value in (('early', early), ('mid', mid), ('late', late)):
                if value is None:
                    continue
                agg['phases'][phase]['sum'] += value
                agg['phases'][phase]['n'] += 1
            if lead_at_10 and win is not None:
                agg['leadAt10Games'] += 1
                agg['leadAt10Wins'] += 1 if win else 0
            if diff_at_map['600'] is not None and diff_at_map['600'] < 0 and win is True:
                agg['comebacks'] += 1
            if diff_at_map['600'] is not None and diff_at_map['600'] > 0 and win is False:
                agg['blownLeads'] += 1
            if kills_per_minute is not None:
                agg['killTempoSum'] += kills_per_minute
                agg['killTempoN'] += 1
        per_match.sort(key=lambda item: (item.get('date') or ''), reverse=True)
        aggregate = {
            'games': len(per_match),
            'leadAt10Conversion': round(agg['leadAt10Wins'] / agg['leadAt10Games'] * 100, 1)
                                  if agg['leadAt10Games'] else None,
            'leadAt10Games': agg['leadAt10Games'],
            'avgDiffAt': {t: round(value['sum'] / value['n']) if value['n'] else None
                          for t, value in agg['diffAt'].items()},
            'landmarkSamples': {t:value['n'] for t,value in agg['diffAt'].items()},
            'avgPhases': {phase: round(value['sum'] / value['n']) if value['n'] else None
                          for phase, value in agg['phases'].items()},
            'phaseSamples': {phase: value['n'] for phase, value in agg['phases'].items()},
            'comebacks': agg['comebacks'], 'blownLeads': agg['blownLeads'],
            'avgKillsPerMinute': round(agg['killTempoSum'] / agg['killTempoN'], 2) if agg['killTempoN'] else None,
        }
        return {'gate': '时间轴覆盖 ≥ 60%', 'matches': per_match[:60], 'aggregate': aggregate,
                'dataQuality': self._data_quality(matches),
                'warnings': warnings}

    def bp_summary(self, filters):
        """BP 聚合：人工手序录入优先、营地名单兜底，两类来源不混算手序。

        营地 battledetail 给的是终局 ban/pick 名单（无 1–5 楼顺序、无一手方），
        所以名单类指标（禁用/选用频率、阵容、分路、对手习惯）自动出；
        手序效果与先后手只使用比赛校对页人工填写的 match.bp。
        旧字段（bans / ownPicks / orderEffect / opponents）保持原形状。
        """
        from bp_camp import merge_bp_sources
        matches, warnings = self._selected_matches(filters)
        SIDE = {'blue': 'left', 'red': 'right', 'left': 'left', 'right': 'right'}
        bans, own_picks, enemy_picks, pick_counts = {}, {}, {}, {}
        order_effect = {order: {'n': 0, 'wins': 0} for order in range(1, 6)}
        opponents, pairs, compositions, lane_stats, first_pick_effect = {}, {}, {}, {}, {}
        sides = {side: {'side': side, 'bans': 0, 'picks': 0, 'matches': 0, 'wins': 0}
                 for side in ('left', 'right')}
        hero_meta, match_rows = {}, []
        totals = {'bans': 0, 'picks': 0, 'decided': 0, 'wins': 0}
        camp_matches = manual_matches = 0

        def add_pick(target, hero, win):
            entry = target.setdefault(hero, {'hero': hero, 'count': 0, 'wins': 0,
                                            'decided': 0, 'winRate': None})
            entry['count'] += 1
            if win is not None:
                entry['decided'] += 1
                entry['wins'] += 1 if win else 0
            return entry

        def rate(wins, n):
            return round(wins / n * 100, 1) if n else None

        def note_lane(hero, kind):
            lane = hero_meta.get(hero, {}).get('lane') or '未分路'
            bucket = lane_stats.setdefault(lane, {'lane': lane, 'bans': 0, 'picks': 0,
                                                  'heroes': {}})
            bucket[kind] += 1
            bucket['heroes'][hero] = bucket['heroes'].get(hero, 0) + 1

        for match in matches:
            camp_bp = match.get('campBp')
            record = (merge_bp_sources(None, camp_bp, match) if filters.get('campFirst') else None)
            if record is None:
                record = merge_bp_sources(match.get('bp'), camp_bp, match)
            elif match.get('bp'):
                manual = merge_bp_sources(match['bp'], None, match)
                if manual and manual['pickOrderKnown']:
                    names = {side: {entry['name']: entry for entry in record['picks'][side]}
                             for side in ('left', 'right')}
                    ordered = {side: [entry['name'] for entry in manual['picks'][side]]
                               for side in ('left', 'right')}
                    if all(len(ordered[side]) == 5 and set(ordered[side]) == names[side].keys()
                           for side in ('left', 'right')):
                        record['picks'] = {side: [names[side][name] for name in ordered[side]]
                                           for side in ('left', 'right')}
                        record['pickOrderKnown'] = True
                        record['firstPick'] = manual['firstPick']
            if not record:
                continue
            camp_matches += record['source'] == 'camp'
            manual_matches += record['pickOrderKnown']
            for name, value in record['heroMeta'].items():
                current = hero_meta.setdefault(name, {'id': None, 'icon': None, 'lane': None})
                for key in ('id', 'icon', 'lane'):
                    if value.get(key) and not current.get(key):
                        current[key] = value[key]
            # 跨局补齐：本局被 ban 的英雄可能在别的局出场，那里才有分路/头像。
            for group in (record['bans'], record['picks']):
                for entries in group.values():
                    for entry in entries:
                        meta = hero_meta.get(entry['name']) or {}
                        for key in ('id', 'icon', 'lane'):
                            if not entry.get(key):
                                entry[key] = meta.get(key)
            own_side = SIDE.get(match.get('ownCamp')) or record['ownSide']
            winner = (SIDE.get(match.get('winnerCamp') or match.get('winner'))
                      or record['winnerSide'])
            win = winner == own_side if winner and own_side else None
            if winner:
                for side in ('left', 'right'):
                    sides[side]['matches'] += 1
                sides[winner]['wins'] += 1
                totals['decided'] += 1
                totals['wins'] += 1 if win else 0

            for side in ('left', 'right'):
                entries = record['bans'][side]
                sides[side]['bans'] += len(entries)
                totals['bans'] += len(entries)
                for item in entries:
                    hero = item['name']
                    entry = bans.setdefault(hero, {'hero': hero, 'total': 0, 'byLeft': 0,
                                                   'byRight': 0, 'leftN': 0, 'leftWins': 0,
                                                   'rightN': 0, 'rightWins': 0})
                    entry['total'] += 1
                    entry['byLeft' if side == 'left' else 'byRight'] += 1
                    if winner is not None:
                        entry[f'{side}N'] += 1
                        entry[f'{side}Wins'] += 1 if winner == side else 0
                    note_lane(hero, 'bans')

            enemy_side = 'right' if own_side == 'left' else 'left' if own_side else None
            for side in ('left', 'right'):
                entries = record['picks'][side]
                sides[side]['picks'] += len(entries)
                totals['picks'] += len(entries)
                for index, item in enumerate(entries, start=1):
                    hero = item['name']
                    pick_counts[hero] = pick_counts.get(hero, 0) + 1
                    note_lane(hero, 'picks')
                    if side == own_side:
                        add_pick(own_picks, hero, win)
                        if record['pickOrderKnown'] and win is not None:
                            bucket = order_effect.get(index)
                            if bucket:
                                bucket['n'] += 1
                                bucket['wins'] += 1 if win else 0
                    elif side == enemy_side:
                        add_pick(enemy_picks, hero, win)

            own_names = [item['name'] for item in (record['picks'].get(own_side) or [])] if own_side else []
            if len(own_names) == 5:
                key = ' · '.join(sorted(own_names))
                comp = compositions.setdefault(key, {'heroes': sorted(own_names), 'count': 0,
                                                     'wins': 0, 'decided': 0})
                comp['count'] += 1
                if win is not None:
                    comp['decided'] += 1
                    comp['wins'] += 1 if win else 0
            for i, a in enumerate(own_names):
                for b in own_names[i + 1:]:
                    left, right = sorted((a, b))
                    pair = pairs.setdefault((left, right), {'a': left, 'b': right, 'n': 0,
                                                            'wins': 0, 'decided': 0})
                    pair['n'] += 1
                    if win is not None:
                        pair['decided'] += 1
                        pair['wins'] += 1 if win else 0

            if own_side and enemy_side:
                opponent = match.get('opponent') or ''
                habits = opponents.setdefault(opponent, {'opponent': opponent, 'matches': 0,
                                                         'bans': {}, 'picks': {}})
                habits['matches'] += 1
                for item in record['bans'][enemy_side]:
                    habits['bans'][item['name']] = habits['bans'].get(item['name'], 0) + 1
                for item in record['picks'][enemy_side]:
                    habits['picks'][item['name']] = habits['picks'].get(item['name'], 0) + 1

            if record['firstPick'] and own_side and win is not None:
                label = '我方一手' if record['firstPick'] == own_side else '对手一手'
                bucket = first_pick_effect.setdefault(label, {'label': label, 'n': 0, 'wins': 0})
                bucket['n'] += 1
                bucket['wins'] += 1 if win else 0

            match_rows.append({
                'key': match.get('key'), 'date': match.get('date'),
                'dateText': match.get('dateText') or match.get('date'),
                'opponent': match.get('opponent') or '', 'session': match.get('session') or '',
                'title': match.get('title') or '', 'duration': record['duration'],
                'mapName': record['mapName'], 'gameSeq': record['gameSeq'],
                'source': record['source'], 'pickOrderKnown': record['pickOrderKnown'],
                'firstPick': record['firstPick'], 'ownSide': own_side,
                'winnerSide': winner,
                'result': ('win' if win else 'loss') if win is not None else 'unknown',
                'bans': record['bans'], 'picks': record['picks'],
                'banSlots': record.get('banSlots') or {}, 'pickSlots': record.get('pickSlots') or {},
                'teamStats': record['teamStats'], 'scores': match.get('scores') or {},
            })

        ban_list = []
        for entry in bans.values():
            ban_list.append({**entry, 'count': entry['total'],
                             'leftWinRate': rate(entry['leftWins'], entry['leftN']),
                             'rightWinRate': rate(entry['rightWins'], entry['rightN'])})
        ban_list.sort(key=lambda item: -item['total'])
        for target in (own_picks, enemy_picks):
            for entry in target.values():
                entry['winRate'] = rate(entry['wins'], entry['decided'])
        pick_list = sorted(own_picks.values(), key=lambda item: -item['count'])
        enemy_list = sorted(enemy_picks.values(), key=lambda item: -item['count'])

        def heroes_with_meta(items):
            return [{'name': name, 'count': count,
                     **(hero_meta.get(name) or {})} for name, count in items]

        habit_list = []
        for entry in opponents.values():
            bans_top = sorted(entry['bans'].items(), key=lambda kv: -kv[1])[:8]
            picks_top = sorted(entry['picks'].items(), key=lambda kv: -kv[1])[:8]
            habit_list.append({**entry, 'bans': bans_top, 'picks': picks_top,
                               'banHeroes': heroes_with_meta(bans_top),
                               'pickHeroes': heroes_with_meta(picks_top)})
        habit_list.sort(key=lambda item: -item['matches'])

        lane_list = []
        for bucket in lane_stats.values():
            lane_list.append({**bucket,
                              'heroes': sorted(bucket['heroes'].items(), key=lambda kv: -kv[1])[:6]})
        lane_list.sort(key=lambda item: -(item['bans'] + item['picks']))

        pressure = []
        for hero in set(bans) | set(pick_counts):
            b, p = bans.get(hero, {}).get('total', 0), pick_counts.get(hero, 0)
            pressure.append({'hero': hero, 'bans': b, 'picks': p,
                             'banRate': rate(b, b + p), 'appearance': b + p})
        pressure.sort(key=lambda item: (-item['bans'], -item['picks']))

        comp_list = sorted(compositions.values(), key=lambda item: -item['count'])
        for item in comp_list:
            item['winRate'] = rate(item['wins'], item['decided'])
        pair_list = sorted(pairs.values(), key=lambda item: -item['n'])
        for item in pair_list:
            item['winRate'] = rate(item['wins'], item['decided'])
        for side in sides.values():
            side['winRate'] = rate(side['wins'], side['matches'])
        first_pick_list = sorted(first_pick_effect.values(), key=lambda item: item['label'])
        for item in first_pick_list:
            item['winRate'] = rate(item['wins'], item['n'])
        totals['heroes'] = len(hero_meta)
        linked_seqs = {row['gameSeq'] for row in match_rows if row['gameSeq']}
        pending_camp = 0
        detail_dir = self.db_path.parent / 'camp_details'
        if detail_dir.is_dir():
            try:
                pending_camp = max(0, len(list(detail_dir.glob('*.json'))) - len(linked_seqs))
            except OSError:
                pass
        sample_warning = None
        if totals['decided'] and totals['wins'] == totals['decided']:
            sample_warning = ('当前有胜负的 BP 对局全部为胜局，胜率类指标受样本选择偏差影响，'
                              '不能据此判断英雄强弱。')
        return {
            'sampleWarning': sample_warning, 'pendingCampMatches': pending_camp,
            'matchesWithBp': len(match_rows),
            'campBpMatches': camp_matches, 'manualBpMatches': manual_matches,
            'bans': ban_list[:30], 'ownPicks': pick_list[:30],
            'enemyPicks': enemy_list[:30],
            'orderEffect': [{'order': order, **value} for order, value in order_effect.items()],
            'opponents': habit_list[:20],
            'heroMeta': hero_meta, 'matches': match_rows[:40],
            'compositions': comp_list[:20], 'pairs': pair_list[:30],
            'lanes': lane_list, 'pressure': pressure[:30],
            'sides': sides, 'firstPickEffect': first_pick_list,
            'totals': totals,
            'sourceNote': ('禁用/选用名单默认来自营地 battledetail 自动同步（终局名单，'
                           '不含 pick 手序与一手方）；比赛校对页人工填写的 BP 优先，'
                           '且只有人工数据参与手序与先后手统计。'),
            'warnings': warnings,
        }

    def objectives(self, filters):
        """资源事件聚合：暴君/主宰/风暴龙王控制率、塔数差、一塔归属与胜负的描述性关系。"""
        def avg(values):
            return round(sum(values) / len(values), 1) if values else None

        matches, warnings = self._selected_matches(filters)
        types = ('tyrant', 'dominator', 'storm')
        per_type = {kind: {'own': 0, 'enemy': 0, 'matches': 0, 'ratesWin': [], 'ratesLoss': []}
                    for kind in types}
        towers = {'own': 0, 'enemy': 0, 'matches': 0, 'diffWin': [], 'diffLoss': []}
        first_tower = {'own': 0, 'enemy': 0, 'winsWhenOwn': 0, 'ownKnown': 0}
        rows = []
        for match in matches:
            if match.get('source') != 'db' or match.get('ownCamp') not in ('left', 'right'):
                continue
            events = match.get('events') or []
            if not events:
                continue
            own_side, enemy_side = match['ownCamp'], ('right' if match['ownCamp'] == 'left' else 'left')
            win = (match.get('winner') == own_side) if match.get('winner') in ('left', 'right') else None

            def count(kind, side):
                return sum(1 for event in events if event.get('type') == kind and event.get('side') == side)

            entry = {'matchKey': match['key'], 'date': match.get('date'),
                     'opponent': match.get('opponent') or '', 'win': win,
                     'counts': {}, 'towerDiff': None, 'firstTower': None}
            for kind in types:
                own_count, enemy_count = count(kind, own_side), count(kind, enemy_side)
                if own_count or enemy_count:
                    per_type[kind]['own'] += own_count
                    per_type[kind]['enemy'] += enemy_count
                    per_type[kind]['matches'] += 1
                    rate = own_count / (own_count + enemy_count) * 100
                    if win is not None:
                        (per_type[kind]['ratesWin'] if win else per_type[kind]['ratesLoss']).append(rate)
                entry['counts'][kind] = [own_count, enemy_count]
            tower_own, tower_enemy = count('tower', own_side), count('tower', enemy_side)
            if tower_own or tower_enemy:
                towers['own'] += tower_own
                towers['enemy'] += tower_enemy
                towers['matches'] += 1
                entry['towerDiff'] = tower_own - tower_enemy
                if win is not None:
                    (towers['diffWin'] if win else towers['diffLoss']).append(tower_own - tower_enemy)
            first = next((event for event in events if event.get('type') == 'firstTower'), None)
            if first:
                entry['firstTower'] = 'own' if first.get('side') == own_side else 'enemy'
                if entry['firstTower'] == 'own':
                    first_tower['own'] += 1
                    if win is not None:
                        first_tower['winsWhenOwn'] += 1 if win else 0
                        first_tower['ownKnown'] += 1
                else:
                    first_tower['enemy'] += 1

            rows.append(entry)
        aggregate = {}
        for kind in types:
            entry = per_type[kind]
            total = entry['own'] + entry['enemy']
            aggregate[kind] = {'own': entry['own'], 'enemy': entry['enemy'], 'matches': entry['matches'],
                               'ownRate': round(entry['own'] / total * 100, 1) if total else None,
                               'rateWhenWin': avg(entry['ratesWin']), 'rateWhenLoss': avg(entry['ratesLoss'])}
        aggregate['towers'] = {'own': towers['own'], 'enemy': towers['enemy'], 'matches': towers['matches'],
                               'avgDiff': round((towers['own'] - towers['enemy']) / towers['matches'], 1) if towers['matches'] else None,
                               'diffWhenWin': avg(towers['diffWin']), 'diffWhenLoss': avg(towers['diffLoss'])}
        aggregate['firstTower'] = {**first_tower,
                                   'winRateWhenOwnFirst': round(first_tower['winsWhenOwn'] / first_tower['ownKnown'] * 100, 1)
                                   if first_tower['ownKnown'] else None}
        rows.sort(key=lambda row: (row.get('date') or ''), reverse=True)
        return {'aggregate': aggregate, 'rows': rows[:120], 'warnings': warnings}

    def scouting(self, filters):
        """对手侦察档案：交锋记录、对手英雄池、阵营偏好。"""
        matches, warnings = self._selected_matches(filters)
        opponents = {}
        for match in matches:
            if match.get('source') != 'db' or match.get('ownCamp') not in ('left', 'right'):
                continue
            name = match.get('opponent') or ''
            entry = opponents.setdefault(name, {'opponent': name or '对手未知', 'matches': 0, 'wins': 0,
                                                'decided': 0, 'sides': {'left': 0, 'right': 0},
                                                'enemyHeroes': {}, 'ownHeroes': {}})
            entry['matches'] += 1
            entry['sides'][match['ownCamp']] += 1
            win = (match.get('winner') == match['ownCamp']) if match.get('winner') in ('left', 'right') else None
            if win is not None:
                entry['decided'] += 1
                entry['wins'] += 1 if win else 0
            enemy_camp = 'right' if match['ownCamp'] == 'left' else 'left'
            for player in match['players']:
                hero = player.get('hero')
                if not hero:
                    continue
                if player.get('camp') == enemy_camp:
                    entry['enemyHeroes'][hero] = entry['enemyHeroes'].get(hero, 0) + 1
                else:
                    entry['ownHeroes'][hero] = entry['ownHeroes'].get(hero, 0) + 1
        out = []
        for entry in opponents.values():
            out.append({**entry,
                        'winRate': round(entry['wins'] / entry['decided'] * 100, 1) if entry['decided'] else None,
                        'enemyHeroes': sorted(entry['enemyHeroes'].items(), key=lambda kv: -kv[1])[:10],
                        'ownHeroes': sorted(entry['ownHeroes'].items(), key=lambda kv: -kv[1])[:10]})
        out.sort(key=lambda item: -item['matches'])
        return {'opponents': out, 'warnings': warnings}

    def imports(self):
        return {'imports': self.get()['imports'], 'aggregates': self.get()['aggregates'],
                'warnings': self.get()['warnings']}

    def import_rows(self, import_id, sheet, limit=500, offset=0):
        path = None
        for entry in self.get()['imports']:
            if entry['id'] != import_id:
                continue
            for item in entry['sheets']:
                if item.get('name') == sheet:
                    path = Path(self.imports_dir) / import_id / item.get('rowsFile', '')
                    break
        if path is None or not path.is_file():
            return None
        rows = self._read_jsonl(path, [], limit=200000)
        return {'rows': rows[offset:offset + limit], 'total': len(rows),
                'aggregated': bool(rows and rows[0].get('aggregated'))}

    def sources(self):
        data = self.get()
        return {
            'teamName': data['teamName'],
            'db': {'confirmed': sum(1 for match in data['matches'] if 'db' in match['sources']),
                   'drafts': data['drafts']},
            'bundles': {'count': sum(1 for match in data['matches'] if 'bundle' in match['sources']),
                        'linked': sum(1 for match in data['matches'] if len(match['sources']) == 2)},
            'imports': data['imports'], 'aggregates': data['aggregates'],
            'warnings': data['warnings'],
        }
