"""Import a public Honor of Kings Camp replay link.

The Camp web replay calls one of three public endpoints:

* ``/game/battleanalyze/old``       personal replay
* ``/game/kplbattleanalyze/old``    KPL match
* ``/game/betabattleanalyze/old``   beta replay

The response is public JSON.  It contains final KDA/ratings, about one team
gold point every 30 seconds, per-second positions and event lists.  It does raw
damage/taken/gold only at team level, and it never contains one-second gold.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STORE = Path(os.environ.get('CAMP_REPLAY_DIR', ROOT / 'data' / 'official_replays'))
SCHEMA = 'camp-replay-v1'
API_HOST = 'https://kohcamp.qq.com'
ENDPOINTS = {
    'personal': '/game/battleanalyze/old',
    'kpl': '/game/kplbattleanalyze/old',
    'beta': '/game/betabattleanalyze/old',
}
MAX_BYTES = 4 * 1024 * 1024


class CampReplayError(ValueError):
    """The link, endpoint or payload cannot be used."""


# 微信里分享营地战绩，复制出来的是这类短链。302 一跳就落到公开的
# camp.qq.com/h5/webdist/mp-redirect/ 页面，参数都在地址里，不需要登录。
SHORT_HOSTS = ('cu.qq.com', 'url.cn', 'wxaurl.cn', 'w.url.cn')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_short_link(url):
    host = urllib.parse.urlsplit(str(url or '').strip()).netloc.lower()
    return any(host == item or host.endswith('.' + item) for item in SHORT_HOSTS)


def expand_short_link(url, timeout=15):
    """展开分享短链，返回真实地址。只跟随一跳。"""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        str(url).strip(), method='GET',
        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 Chrome/120 Safari/537.36'})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.geturl()
    except urllib.error.HTTPError as error:
        location = error.headers.get('Location')
        if not location:
            raise CampReplayError(f'短链没有跳转目标（HTTP {error.code}）') from error
        return urllib.parse.urljoin(str(url), location)
    except urllib.error.URLError as error:
        raise CampReplayError(f'无法连接短链服务：{error.reason}') from error
    except OSError as error:
        raise CampReplayError(f'短链读取失败：{error}') from error


def parse_link(url):
    parsed = urllib.parse.urlparse(str(url or '').strip())
    host = (parsed.netloc or '').lower()
    if host.endswith('servicewechat.com') or host.endswith('weixin.qq.com'):
        raise CampReplayError('这是微信小程序跳转链，不是营地网页回放链接。请提供 '
                              'camp.qq.com/h5/webdist/battle-replay/...?gameseq=... 的链接。')
    if host and not (host == 'camp.qq.com' or host.endswith('.camp.qq.com')):
        raise CampReplayError('只接受 camp.qq.com 的营地回放链接')
    query = urllib.parse.parse_qs(parsed.query)
    lower = {key.lower(): values[-1] for key, values in query.items() if values}

    def pick(*names):
        for name in names:
            if lower.get(name.lower()):
                return lower[name.lower()]
        return None

    game_seq = pick('gameseq', 'gameSeq')
    game_svr = pick('gamesvrentity', 'gameSvr', 'gameSvrId', 'gamesvrid')
    relay_svr = pick('relaysvrentity', 'relaySvr', 'relaySvrId', 'relaysvrid')
    player_id = pick('playerid', 'playerId', 'userId', 'userid')
    kpl_flag = pick('kplMatchFlag')
    beta_flag = pick('betaFlag')
    e_id = pick('eId')
    m_id = pick('mId')
    # 分享链接（mp-redirect）会带模式标记，接口返回里没有，只能从地址保留
    battle_type = pick('battleType')
    pvp_type = pick('pvpType')
    if not game_seq or not re.fullmatch(r'\d{3,20}', game_seq):
        raise CampReplayError('链接缺少有效的 gameseq')
    if not game_svr or not relay_svr:
        raise CampReplayError('链接缺少 gamesvrentity 或 relaysvrentity')
    if not player_id:
        player_id = 'undefined'
    kind = 'kpl' if (str(kpl_flag or '') == '1' or (e_id and m_id)) else \
        'beta' if str(beta_flag or '') == '1' else 'personal'
    if kind == 'personal' and player_id in ('undefined', 'null', ''):
        raise CampReplayError('个人回放链接缺少 playerid')
    return {'kind': kind, 'gameSeq': game_seq, 'gameSvr': game_svr,
            'relaySvr': relay_svr, 'playerId': player_id,
            'eId': e_id, 'mId': m_id,
            'battleType': battle_type, 'pvpType': pvp_type, 'url': url}


def payload_for(link):
    payload = {'cSystem': 'unknown', 'h5Get': 1, 'gameSeq': link['gameSeq'],
               'gameSvr': link['gameSvr'], 'playerId': link['playerId'],
               'relaySvr': link['relaySvr']}
    if link['kind'] == 'kpl':
        if not (link.get('eId') and link.get('mId')):
            raise CampReplayError('KPL 链接缺少 eId/mId')
        payload['eId'] = link['eId']
        payload['mId'] = link['mId']
    return payload


def fetch(link, timeout=30):
    endpoint = ENDPOINTS[link['kind']]
    body = json.dumps(payload_for(link), ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        API_HOST + endpoint, data=body, method='POST',
        headers={
            'content-type': 'application/json',
            'h5get': '1',
            'noencrypt': '1',
            'accept': 'application/json, text/plain, */*',
            'accept-encoding': 'identity',
            'referer': 'https://camp.qq.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/120 Safari/537.36',
        })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise CampReplayError(f'营地接口 HTTP {error.code}') from error
    except urllib.error.URLError as error:
        raise CampReplayError(f'无法连接营地接口：{error.reason}') from error
    except OSError as error:
        raise CampReplayError(f'营地接口读取失败：{error}') from error
    if len(data) > MAX_BYTES:
        raise CampReplayError('营地接口返回过大，已拒绝')
    try:
        value = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CampReplayError('营地接口没有返回 JSON') from error
    if not isinstance(value, dict) or value.get('returnCode') not in (0, '0'):
        message = value.get('returnMsg') if isinstance(value, dict) else ''
        raise CampReplayError(f'营地接口拒绝：{message or "未知错误"}')
    data_body = value.get('data')
    if not isinstance(data_body, dict) or not data_body:
        raise CampReplayError('营地接口返回空数据')
    return value, data_body


def normalize(payload, link):
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CampReplayError('接口缺少 data')
    key_events = [_key_event(event) for event in data.get('keyEventArr') or []]
    extended = []
    for block in data.get('extendEventArr') or []:
        for event in block.get('eventList') or []:
            extended.append(_extended_event(block, event))
    positions = []
    for item in (data.get('reportData') or {}).get('playerPosInfo') or []:
        positions.append({'playerId': item.get('playerID'),
                          'points': len(item.get('posArr') or []),
                          'posArr': item.get('posArr') or []})
    players = []
    for item in data.get('matchInfo') or []:
        players.append({
            'playerId': item.get('playerId'), 'camp': item.get('acntcamp'),
            'hero': item.get('heroName'), 'heroId': item.get('heroId'),
            'kills': _int(item.get('killCnt')), 'deaths': _int(item.get('deadCnt')),
            'assists': _int(item.get('assistCnt')),
            'ratings': {'grow': item.get('newGrow'), 'battle': item.get('newBattle'),
                        'survive': item.get('newSurvive'),
                        'hurtHero': item.get('newHurtHero'),
                        'kda': item.get('newKDA')},
            'defeatAcntRatio': item.get('defeatAcntRatio'),
        })
    gold_blue = data.get('camp1GoldArr') or []
    gold_red = data.get('camp2GoldArr') or []
    duration = max([event['timeSec'] for event in key_events] +
                   [position['points'] for position in positions] + [0])
    teams = data.get('teamMatchInfo')
    normalized = {
        'schema': SCHEMA,
        'source': {
            'kind': link['kind'], 'api': API_HOST + ENDPOINTS[link['kind']],
            'gameSeq': link['gameSeq'], 'gameSvr': link['gameSvr'],
            'relaySvr': link['relaySvr'], 'playerId': link['playerId'],
            'eId': link.get('eId'), 'mId': link.get('mId'), 'url': link['url'],
        },
        'match': {
            'teams': _teams(teams),
            'score': _score(teams),
            'winCamp': data.get('winCamp'),
            'durationSec': round(duration, 1),
            'teamGold': {'blue': data.get('camp1Gold'), 'red': data.get('camp2Gold')},
            'goldPoints': len(gold_blue), 'goldIntervalSecApprox': 30,
            'keyEvents': len(key_events), 'extendedEvents': len(extended),
            'equipmentEvents': len(data.get('equipEvent') or []),
        },
        'economy': {'blue': gold_blue, 'red': gold_red,
                    'diff': data.get('ecoDistance') or [],
                    'note': '官方回放接口只提供约30秒一个点的团队金币。'},
        'events': {'key': key_events, 'extended': extended,
                   'equipment': data.get('equipEvent') or []},
        'players': players,
        'positions': {'perSecond': True,
                      'pointsPerPlayer': max([position['points'] for position in positions] + [0]),
                      'players': len(positions),
                      'note': '每人逐秒坐标；不是逐秒金币。'},
        'warnings': [
            '官方回放金币是约30秒一个点，不是1秒；不能生成1秒金币曲线。',
            '有逐秒位置，但没有逐秒金币/KDA。',
            '没有逐人原始输出/承伤/总经济；终局仍以赛后截图为准。',
        ],
    }
    if link['kind'] == 'kpl':
        normalized['warnings'].append('这是 KPL 比赛接口结果，不是训练赛。')
    return normalized, positions


def _key_event(event):
    dt = event.get('dtData') or {}
    return {'eventType': event.get('eventType'),
            'timeSec': round(_int(dt.get('killTime')) / 1000, 3),
            'dtType': dt.get('dtType'), 'dtId': dt.get('dtID'),
            'dtCamp': dt.get('dtCamp'), 'killerCamp': dt.get('killerCamp'),
            'killerId': dt.get('killerId'),
            'kills': [{'camp': item.get('camp'), 'killerId': item.get('killerId'),
                       'hurtTotal': item.get('hurtTotal')}
                      for item in (dt.get('kills') or [])]}


def _extended_event(block, event):
    dt = event.get('dtData') or {}
    return {'timeSec': round(_int(block.get('eventTime')) / 1000, 3),
            'eventType': event.get('eventType'), 'dtType': dt.get('dtType'),
            'dtId': dt.get('dtID'), 'dtCamp': dt.get('dtCamp'),
            'killerCamp': dt.get('killerCamp'), 'killerId': dt.get('killerId')}


def _teams(value):
    if not isinstance(value, dict):
        return None
    return [{'camp': '1', 'name': value.get('teamTitle1'), 'score': value.get('score1'),
             'id': value.get('teamId1')},
            {'camp': '2', 'name': value.get('teamTitle2'), 'score': value.get('score2'),
             'id': value.get('teamId2')}]


def _score(value):
    if not isinstance(value, dict):
        return None
    return {'blue': value.get('score1'), 'red': value.get('score2')}


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def import_link(url, force=False):
    if is_short_link(url):
        url = expand_short_link(url)
    link = parse_link(url)
    replay_id = f'camp-{link["gameSeq"]}'
    folder = STORE / replay_id
    meta_path = folder / 'meta.json'
    if meta_path.is_file() and not force:
        return {'id': replay_id, 'meta': _read_json(meta_path), 'cached': True}
    payload, data = fetch(link)
    normalized, positions = normalize(payload, link)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / 'raw.json'
    normalized_path = folder / 'normalized.json'
    positions_path = folder / 'positions.json'
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    normalized_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')
    if positions:
        positions_path.write_text(json.dumps(
            {'schema': 'camp-replay-positions-v1', 'players': positions},
            ensure_ascii=False), encoding='utf-8')
    meta = {
        'id': replay_id, 'kind': link['kind'], 'gameSeq': link['gameSeq'],
        'gameSvr': link['gameSvr'], 'relaySvr': link['relaySvr'],
        'playerId': link['playerId'], 'fetchedAt': time.time(),
        'battleType': link.get('battleType'), 'pvpType': link.get('pvpType'),
        'match': normalized['match'], 'warnings': normalized['warnings'],
        'files': {'raw': raw_path.name, 'normalized': normalized_path.name,
                  'positions': positions_path.name if positions else None},
        'sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'id': replay_id, 'meta': meta, 'normalized': normalized, 'cached': False}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def list_replays():
    if not STORE.is_dir():
        return []
    result = []
    for folder in STORE.iterdir():
        if not folder.is_dir():
            continue
        meta = _read_json(folder / 'meta.json')
        if isinstance(meta, dict) and meta.get('id'):
            result.append(meta)
    result.sort(key=lambda item: item.get('fetchedAt') or 0, reverse=True)
    return result


def read_meta(replay_id):
    if not re.fullmatch(r'camp-\d{3,20}', str(replay_id or '')):
        raise CampReplayError('官方回放 ID 无效')
    meta = _read_json(STORE / replay_id / 'meta.json')
    if not isinstance(meta, dict):
        raise CampReplayError('官方回放不存在')
    return meta


def read_normalized(replay_id):
    meta = read_meta(replay_id)
    value = _read_json(STORE / replay_id / 'normalized.json')
    if not isinstance(value, dict):
        raise CampReplayError('官方回放数据不存在')
    return meta, value


def positions_path(replay_id):
    meta = read_meta(replay_id)
    name = (meta.get('files') or {}).get('positions')
    if not name:
        return None
    path = STORE / replay_id / name
    return path if path.is_file() else None
