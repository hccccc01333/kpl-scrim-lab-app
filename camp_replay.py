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

from paths import data_root

ROOT = Path(__file__).resolve().parent
STORE = Path(os.environ.get('CAMP_REPLAY_DIR', data_root() / 'official_replays'))
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


# 分享链接里「营地账号 ID」的字段名（大小写不敏感）。roleId /
# uniqueRoleId / toAppRoleId 是游戏角色 ID，绝不能拿去查战绩列表。
CAMP_USER_ID_KEYS = ('userid', 'frienduserid', 'shareuserid', 'campuserid')


def extract_camp_user_id(url: str) -> dict:
    """从营地网页链接里提取营地账号 ID，供「登记同步选手」使用。

    与 parse_link 分开：登记选手只需要 userId，不需要 gameseq / 服务器参数，
    也不该受对局模式（battleType）、页面路径（mp-redirect / battle-replay）
    或 KPL/beta 标记影响。开房间征召等未实测模式的链接因此同样可用。
    parse_link 仍严格服务于导入官方回放，那里必须拿到完整的回放参数。
    """
    parsed = urllib.parse.urlparse(str(url or '').strip())
    host = (parsed.netloc or '').lower()
    if host.endswith('servicewechat.com') or host.endswith('weixin.qq.com'):
        raise CampReplayError('这是微信小程序跳转链，不是营地网页链接；'
                              '请在浏览器里打开后再复制地址栏链接。')
    if host and not (host == 'camp.qq.com' or host.endswith('.camp.qq.com')):
        raise CampReplayError('只接受 camp.qq.com 的营地链接')
    lower = {key.lower(): values[-1] for key, values in
             urllib.parse.parse_qs(parsed.query).items() if values}
    user_id = next((lower[key] for key in CAMP_USER_ID_KEYS if lower.get(key)), '')
    if not re.fullmatch(r'\d{5,15}', user_id or ''):
        raise CampReplayError(
            '链接里没有 userId（营地 ID）；请用微信分享的 mp-redirect 链接，'
            '或直接填 5–15 位数字营地 ID。roleId / playerid 是角色 ID，不能代替。')
    return {'userId': user_id,
            'gameSeq': lower.get('gameseq'),
            'battleType': lower.get('battletype'),
            'pvpType': lower.get('pvptype')}


def extract_share_game(url: str) -> dict:
    """从营地分享链接里提取「这一局」的完整身份，供直接补拉对局详情。

    白名单登记只认 userId，但教练贴链接往往是为了「链接里的这一局」。营地
    ``morebattlelist`` 对部分账号返回空列表（隐私、未绑定大区角色、非好友），
    而分享链接本身带着 gameSeq / gameSvrId / relaySvrId，可以直接查
    ``battledetail``。这里把这几项一起解析出来；缺任何一项都标
    ``complete=False``，调用方仍可只用 userId 登记选手。

    只做解析，不发请求；短链请先用 :func:`expand_short_link` 展开。
    """
    parsed = urllib.parse.urlparse(str(url or '').strip())
    host = (parsed.netloc or '').lower()
    if host.endswith('servicewechat.com') or host.endswith('weixin.qq.com'):
        raise CampReplayError('这是微信小程序跳转链，不是营地网页链接；'
                              '请在浏览器里打开后再复制地址栏链接。')
    if host and not (host == 'camp.qq.com' or host.endswith('.camp.qq.com')):
        raise CampReplayError('只接受 camp.qq.com 的营地链接')
    lower = {key.lower(): values[-1] for key, values in
             urllib.parse.parse_qs(parsed.query).items() if values}

    def pick(*names):
        for name in names:
            value = str(lower.get(name) or '').strip()
            if value:
                return value
        return ''

    user_id = pick(*CAMP_USER_ID_KEYS)
    game_seq = pick('gameseq')
    game_svr = pick('gamesvrentity', 'gamesvr', 'gamesvrid')
    relay_svr = pick('relaysvrentity', 'relaysvr', 'relaysvrid')
    battle_type = pick('battletype')
    pvp_type = pick('pvptype')
    role_id = pick('roleid', 'uniqueroleid', 'toapproleid')
    acnt_camp = pick('acntcamp')
    complete = bool(re.fullmatch(r'\d{3,20}', game_seq)
                    and re.fullmatch(r'-?\d{1,20}', game_svr)
                    and re.fullmatch(r'-?\d{1,20}', relay_svr))
    return {
        'userId': user_id if re.fullmatch(r'\d{5,15}', user_id) else '',
        'gameSeq': game_seq,
        'gameSvrId': game_svr,
        'relaySvrId': relay_svr,
        'battleType': battle_type if battle_type.isdigit() else '',
        'pvpType': pvp_type if pvp_type.isdigit() else '',
        'roleId': role_id if re.fullmatch(r'\d{3,20}', role_id) else '',
        'acntCamp': acnt_camp if acnt_camp in ('1', '2') else '',
        'complete': complete,
    }


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
    battles = _battles(data)
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
        'battles': battles,
        'players': players,
        'positions': {'perSecond': True,
                      'pointsPerPlayer': max([position['points'] for position in positions] + [0]),
                      'players': len(positions),
                      'note': '每人逐秒坐标；不是逐秒金币。'},
        'warnings': [
            '官方回放金币是约30秒一个点，不是1秒；不能生成1秒金币曲线。',
            '有逐秒位置，但没有逐秒金币/KDA。',
            '没有逐人全局原始输出/承伤/总经济；battles.battleDetail 只有团战窗口内的逐人值，终局仍以赛后截图为准。',
        ],
    }
    if link['kind'] == 'kpl':
        normalized['warnings'].append('这是 KPL 比赛接口结果，不是训练赛。')
    return normalized, positions


def _battles(data):
    """Team fights, hero kills and death positions from the raw response.

    ``keyEventArr`` rows with ``eventType == 'battle'`` carry ``battle`` and
    ``battleDetail`` instead of ``dtData``.  ``battle.killInfo`` is the per-kill
    hero ledger (victim, killer, camp, millisecond time); it matches the final
    panel kill totals in every sampled game.  ``battleDetail`` holds per-fight
    per-player damage / taken / control / KDA.  Earlier versions read ``dtData``
    for every key event, flattening all 504 fights to ``timeSec=0, kills=[]``.

    Account ids are deliberately not copied into ``playerMap``: callers join
    on (game, camp, hero) and use their own anonymous identity mapping.
    """
    obj_map = {}
    for item in data.get('playBaseInfoArr') or []:
        obj = str(item.get('inBattleObjID') or '')
        if not obj:
            continue
        obj_map[obj] = {'heroId': _int(item.get('heroID')),
                        'hero': '', 'camp': str(item.get('acntCamp') or '')}
    info_by_play = {str(p.get('playerId')): p for p in data.get('matchInfo') or []}
    for item in data.get('playBaseInfoArr') or []:
        obj = str(item.get('inBattleObjID') or '')
        if obj not in obj_map:
            continue
        info = info_by_play.get(str(item.get('playID') or '')) or {}
        obj_map[obj]['hero'] = info.get('heroName') or ''
        obj_map[obj]['kills'] = _int(info.get('killCnt'))
        obj_map[obj]['deaths'] = _int(info.get('deadCnt'))
        obj_map[obj]['assists'] = _int(info.get('assistCnt'))

    fights = []
    for event in data.get('keyEventArr') or []:
        battle = event.get('battle')
        if not isinstance(battle, dict):
            continue
        kills = [{'timeSec': round(_int(k.get('time')) / 1000, 3),
                  'victimCamp': str(k.get('camp') or ''),
                  'victim': str(k.get('objID') or ''),
                  'killerCamp': str(k.get('killerCamp') or ''),
                  'killer': str(k.get('killerObjID') or '')}
                 for k in battle.get('killInfo') or []]
        details = [{
            'fightId': str(row.get('fightId') or ''),
            'objID': str(row.get('objID') or ''), 'camp': str(row.get('camp') or ''),
            'support': _int(row.get('isSupport')),
            'kills': _int(row.get('killCnt')), 'deaths': _int(row.get('deadCnt')),
            'assists': _int(row.get('assistCnt')),
            'hurt': _int(row.get('hurtTotal')), 'taken': _int(row.get('behurtTotal')),
            'heal': _int(row.get('therapicTotal')),
            'hardCtrl': _int(row.get('hardctrlTotal')),
            'softCtrl': _int(row.get('softctrlTotal')),
            'lowHP': _int(row.get('lowHP')), 'beginHP': _int(row.get('beginHP')),
            'endHP': _int(row.get('endHP')),
            'ultimates': _int(row.get('ultimateskillCnt')),
        } for row in event.get('battleDetail') or []]
        fights.append({
            'fightId': str(battle.get('fightId') or ''),
            'startSec': round(_int(battle.get('startTime')) / 1000, 3),
            'endSec': round(_int(battle.get('endTime')) / 1000, 3),
            'firstKillerCamp': str(battle.get('firstKillerCamp') or ''),
            'camp1': _int(battle.get('camp1MemNum')),
            'camp2': _int(battle.get('camp2MemNum')),
            'participants': [{'objID': str(p.get('objID') or ''),
                              'camp': str(p.get('camp') or ''),
                              'timeSec': round(_int(p.get('time')) / 1000, 3),
                              'beginner': _int(p.get('isBeginner'))}
                             for p in battle.get('joinMemInfo') or []],
            'kills': kills, 'details': details,
        })

    deaths = []
    for item in data.get('playBaseInfoArr') or []:
        for point in item.get('deathPosArr') or []:
            deaths.append({'objID': str(item.get('inBattleObjID') or ''),
                           'camp': str(item.get('acntCamp') or ''),
                           'heroId': _int(item.get('heroID')),
                           'x': _int(point.get('coordX')),
                           'y': _int(point.get('coordY')),
                           'timeSec': round(_int(point.get('time')), 3)})
    return {'schema': 'camp-battles-v1',
            'source': 'raw.json keyEventArr[eventType=battle].battle/battleDetail + playBaseInfoArr.deathPosArr',
            'fights': fights, 'deaths': deaths, 'playerMap': obj_map,
            'counts': {'fights': len(fights),
                       'heroKills': sum(len(f['kills']) for f in fights),
                       'fightRows': sum(len(f['details']) for f in fights),
                       'deathPoints': len(deaths)}}


def _key_event(event):
    if event.get('eventType') == 'battle' and isinstance(event.get('battle'), dict):
        battle = event['battle']
        return {'eventType': 'battle',
                'timeSec': round(_int(battle.get('startTime')) / 1000, 3),
                'endSec': round(_int(battle.get('endTime')) / 1000, 3),
                'fightId': battle.get('fightId'),
                'killerCamp': battle.get('firstKillerCamp'),
                'killCount': len(battle.get('killInfo') or []),
                'kills': []}
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


def link_from_entry(entry, camp_user_id=''):
    """营地战局列表的一条 → 官方回放链接参数。

    列表接口 ``morebattlelist`` 自带 `gameSeq` / `gameSvrId` / `relaySvrId`，
    另有一条 `analyseUrl`（查询串里有 `gameseq`、`relaysvrentity`、`playerid`，
    但**没有** `gamesvrentity`）。所以从清单直接拼参数即可，不需要教练逐局
    再粘一次回放链接——这正是「只给一个链接就该自动爬回放」缺的那一步。

    `playerid` 取 analyseUrl 里的值（接口不校验它），取不到就退回营地账号 ID。
    """
    entry = entry if isinstance(entry, dict) else {}
    game_seq = str(entry.get('gameSeq') or '').strip()
    game_svr = str(entry.get('gameSvrId') or '').strip()
    relay_svr = str(entry.get('relaySvrId') or '').strip()
    if not re.fullmatch(r'\d{3,20}', game_seq):
        raise CampReplayError('这条战局没有有效的 gameSeq，无法拉取官方回放')
    if not re.fullmatch(r'-?\d{1,20}', game_svr) or not re.fullmatch(r'-?\d{1,20}', relay_svr):
        raise CampReplayError('这条战局缺少 gameSvrId / relaySvrId，无法拉取官方回放')
    player_id = ''
    analyse = str(entry.get('analyseUrl') or '')
    if analyse:
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(analyse).query)
            player_id = next((values[-1] for key, values in query.items()
                              if key.lower() == 'playerid' and values), '')
        except ValueError:
            player_id = ''
    player_id = str(player_id or camp_user_id or '').strip()
    if not re.fullmatch(r'\d{5,20}', player_id):
        raise CampReplayError('这条战局没有可用的 playerid，无法拉取官方回放')
    kind = 'kpl' if str(entry.get('kplMatchFlag') or '') == '1' else 'personal'
    return {'kind': kind, 'gameSeq': game_seq, 'gameSvr': game_svr,
            'relaySvr': relay_svr, 'playerId': player_id,
            'eId': None, 'mId': None,
            # battleType / pvpType 只在列表里，接口返回里没有，随 meta 保存。
            'battleType': str(entry.get('battleType') or '') or None,
            'pvpType': str(entry.get('pvpType') or '') or None,
            'url': analyse or ''}


def import_entry(entry, force=False, camp_user_id=''):
    """按战局列表条目直接导入官方回放（一条链接都不用给）。"""
    return import_link_dict(link_from_entry(entry, camp_user_id), force=force)


def import_link(url, force=False):
    if is_short_link(url):
        url = expand_short_link(url)
    return import_link_dict(parse_link(url), force=force)


def import_link_dict(link, force=False):
    """解析好的链接 → 落盘；同一 gameseq 已存在且不 force 时走缓存。"""
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
