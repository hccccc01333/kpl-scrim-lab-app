"""One match, one collection channel.

A channel is the stable unit for collecting a match.  The four raw sources are
attachments: table, video OCR reports, screenshots and replay files.  This
module only builds candidate drafts and bundles; it never confirms a match or
writes a formal record.
"""
import math
import re
from bp_camp import POSITION_LANES
from camp_time import camp_times
from collection_contract import CONTRACT, PAGE_TYPES, PAGE_NAMES
from datetime import datetime, timezone

SCHEMA = 'kpl-collection-channel-v1'
BUNDLE_SCHEMA = 'kpl-match-data-v1'
SOURCES = ('table', 'video', 'screenshot', 'replay', 'camp')
CORE_FIELDS = ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken', 'participation', 'rating')
# B 组终局扩展指标。键名沿用 README.md 契约与
# studio_analysis.METRICS，不用营地原名，保证下游跨局聚合能直接消费。
# 来源有两条，同口径合并：
# - 营地 battledetail 的 battleStats（killSoldier / monsterCoin / ...）；
# - 赛后截图对应页的识别结果（输出=damageConversion、生存=takenPerDeath、
#   发育=jungleGold/cs、团队=control/healing/towerDamage），字段名与截图同名。
# 这些是「增强字段」：缺失不阻止审核、不计入 complete/partial 与 missing，
# 但会进 draft.coverage 供采集覆盖展示；bundle.final 的键保持不变。
CAMP_EXTENDED_FIELDS = ('cs', 'jungleGold', 'control', 'healing',
                        'towerDamage', 'damageConversion', 'takenPerDeath')
ALL_FIELDS = CORE_FIELDS + CAMP_EXTENDED_FIELDS
# 营地原生键 → 契约键。hurtTransRate / behurtPerDeath 可能是小数，
# 统一走 _camp_number 解析，不能按整数处理。
# 「输出 / 承伤」在契约里的口径是**对英雄输出 / 对英雄承伤**（见 README.md），
# 与赛后截图「输出 / 承伤」页、本局十人表一致；营地 totalHurtCnt / totalBehurtCnt
# 含兵线野怪，拿它进 damage / taken 会让每个选手都和截图/表格对不上。
# 总伤害仍保留在 camp_details 原始数据里，决策台等直接读营地面板的地方自己取 totalHurtCnt。
CAMP_STAT_MAP = {
    'killCnt': 'kills', 'deadCnt': 'deaths', 'assistCnt': 'assists',
    'money': 'gold',
    'totalHeroHurtCnt': 'damage', 'totalBeheroHurtCnt': 'taken',
    'killSoldier': 'cs', 'monsterCoin': 'jungleGold', 'ctrlTime': 'control',
    'healCnt': 'healing', 'buildingDamage': 'towerDamage',
    'hurtTransRate': 'damageConversion', 'behurtPerDeath': 'takenPerDeath',
}
FIELD_LABELS = {
    'hero': '英雄', 'kills': '击杀', 'deaths': '死亡', 'assists': '助攻',
    'gold': '总经济', 'damage': '输出', 'taken': '承伤',
    'participation': '参团率', 'rating': '评分',
    'cs': '补刀', 'jungleGold': '野怪经济', 'control': '控制效果',
    'healing': '治疗量', 'towerDamage': '对塔伤害',
    'damageConversion': '伤害转化比', 'takenPerDeath': '每死承伤',
}


def _camp_number(value):
    """营地 battleStats 的数值几乎都是字符串（'38' / '0.5' / '26792'）。
    统一转成 int/float，非数值原样返回，避免小数变成字符串混进下游统计。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(',', '')
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return value
    if not math.isfinite(number):
        return value
    return int(number) if number.is_integer() else number


_DISPLAY_UNIT_RE = re.compile(r'^(-?\d+(?:\.\d+)?)\s*([kK千万wW])\s*$')
_DISPLAY_PERCENT_RE = re.compile(r'^(-?\d+(?:\.\d+)?)\s*%\s*$')


def _display_tolerance(field):
    """画面读数只保证到显示精度；返回允许的误差（显示档位的半步长/截断宽度）。

    截图和表格草稿保留 ``raw`` 原文，这里只看原文判断精度：

    - ``66.1k`` → 100 一档，四舍五入 → 半步长 50；``1.2万`` → 1000 一档 → 500；
    - ``48%`` → 整数百分比，既可能四舍五入也可能截断 → 允许 1 个百分点；
      ``48.5%`` → 允许 0.1；
    - ``8697`` 这种精确值不设容忍，差 1 仍然算冲突。
    """
    raw = str((field or {}).get('raw') or '').strip().replace(',', '')
    match = _DISPLAY_UNIT_RE.match(raw)
    if match:
        number, unit = match.group(1), match.group(2)
        scale = 1000 if unit in ('k', 'K') else 10000
        decimals = len(number.split('.')[1]) if '.' in number else 0
        return scale / (10 ** decimals) / 2
    match = _DISPLAY_PERCENT_RE.match(raw)
    if match:
        number = match.group(1)
        decimals = len(number.split('.')[1]) if '.' in number else 0
        return 1 / (10 ** decimals)
    return 0.0


def _same_as_displayed(field, value, key=None):
    """两个来源是否是同一个数：完全相等，或差距落在画面显示精度内。

    例：截图读 ``66.1k``（66100）与营地面板 ``66056``、``48%`` 与 ``48.1``、
    ``6.2k`` 与 ``6191`` 都是同一个读数，不记冲突；差一个档位以上才算真不一致。
    参团率不论原文带不带 ``%``，1 个百分点以内都按同一读数处理。
    """
    current = (field or {}).get('value')
    if current == value:
        return True
    if current is None or value is None:
        return False
    try:
        current_number, incoming_number = float(current), float(value)
    except (TypeError, ValueError):
        return False
    tolerance = _display_tolerance(field)
    if key == 'participation':
        tolerance = max(tolerance, 1.0)
    return tolerance > 0 and abs(current_number - incoming_number) <= tolerance


def now():
    return datetime.now(timezone.utc).isoformat()


def blank(match=None):
    match = match or {}
    return {
        'schema': SCHEMA,
        'id': None,
        'createdAt': now(),
        'updatedAt': now(),
        # 录入方式：camp = 王者营地链接/同步；ocr = 赛后截图/录屏识别新录入。
        # 旧通道没有这个键，由 entry_mode() 按已挂素材推断，保持兼容。
        'entry': {'mode': '', 'primary': ''},
        'match': {
            'date': str(match.get('date') or ''), 'opponent': str(match.get('opponent') or ''),
            'session': str(match.get('session') or ''), 'version': str(match.get('version') or ''),
            'mode': str(match.get('mode') or ''), 'durationSec': match.get('durationSec'),
            'scores': match.get('scores') or {'left': None, 'right': None},
            'ownSide': str(match.get('ownSide') or ''),
            'winner': str(match.get('winner') or ''),
        },
        'sources': {
            'table': {'status': 'missing', 'files': [], 'rows': [], 'summary': None},
            'video': {'status': 'missing', 'required': 0, 'files': [], 'roster': [], 'summary': None},
            'screenshot': {'status': 'missing', 'imageIds': [], 'group': None, 'summary': None},
            'replay': {'status': 'missing', 'replayId': None, 'roster': [], 'summary': None},
            'camp': {'status': 'missing', 'gameSeq': None, 'players': [], 'ban': None, 'summary': None},
        },
        'draft': {'players': [], 'match': match, 'conflicts': [], 'missing': [], 'coverage': {}},
        'review': {'status': 'unreviewed', 'reviewedBy': '', 'reviewedAt': '', 'notes': ''},
        'saved': {'status': 'not-saved', 'bundleKey': None, 'savedAt': ''},
        'changeLog': [],
    }


def append_log(channel, action, actor=None, detail=None):
    channel.setdefault('changeLog', []).append({
        'at': now(), 'action': action, 'actor': actor or 'local', 'detail': detail or {},
    })
    channel['updatedAt'] = now()


ENTRY_MODES = ('camp', 'ocr')
OCR_MISSING = '截图/录屏：七页截图或一段完整录屏，至少先齐一样'


def entry_mode(channel):
    """这条通道走「营地同步」还是「截图/录屏 OCR 新录入」。

    显式 ``entry.mode`` 优先；旧通道没有这个键，按素材推断：有 official 链接
    就是营地通道，否则已挂截图/录屏就视为 OCR 录入（这样没有营地链接的存量
    通道不会再被「必采王者营地链接」卡死）。
    """
    entry = channel.get('entry') or {}
    explicit = str(entry.get('mode') or '').strip().lower()
    if explicit in ENTRY_MODES:
        return explicit
    if (channel.get('official') or {}).get('id'):
        return 'camp'
    sources = channel.get('sources') or {}
    screenshot = sources.get('screenshot') or {}
    video = sources.get('video') or {}
    if screenshot.get('imageIds') or video.get('files'):
        return 'ocr'
    return 'camp'


def _ocr_complete_condition(video, page_types):
    """OCR 录入两条一级素材路径：七页截图齐全，或一段能读出十人阵容的录屏。"""
    screenshot_ok = len(page_types) >= 7
    video_ok = len(video.get('files') or []) > 0 and len(video.get('roster') or []) >= 10
    return screenshot_ok, video_ok


def _ocr_missing_message(shot_count, page_types, video):
    """OCR 通道缺素材时给出下一步动作；缺页时点名缺哪几页。"""
    if shot_count:
        detail = f'（截图当前 {min(shot_count, 7)}/7 页'
        missing_pages = [PAGE_NAMES[page] for page in PAGE_TYPES if page not in page_types]
        if missing_pages:
            detail += '，缺：' + '、'.join(missing_pages)
        detail += '）'
    elif video.get('files'):
        detail = f'（录屏只识别出 {len(video.get("roster") or [])}/10 人阵容）'
    else:
        detail = ''
    return OCR_MISSING + detail


def source_status(channel):
    """素材齐备度。营地通道以 official 链接为必采；OCR 录入通道不要求链接。"""
    sources = channel.get('sources') or {}
    table, video, screenshot, replay, camp = [sources.get(key) or {} for key in SOURCES]
    files_video = len(video.get('files') or [])
    page_types = {page.get('pageType') for page in (screenshot.get('group') or {}).get('pages') or []}
    shot_count = len(screenshot.get('imageIds') or [])
    official = bool((channel.get('official') or {}).get('id'))
    mode = entry_mode(channel)
    statuses = {
        'official': 'completed' if official else 'missing',
        'camp': camp.get('status') or 'missing',
        'table': table.get('status') or 'missing',
        'video': 'completed' if files_video else 'missing',
        # 七张截图必须覆盖七种页面类型；同页重复不满足兜底条件。
        'screenshot': 'completed' if len(page_types) >= 7 else 'partial' if shot_count else 'missing',
        'replay': replay.get('status') or 'missing',
    }
    missing = []
    if mode == 'ocr':
        # OCR 新录入是独立的一等路径：不要求营地链接，截图七页或十人录屏任一即可。
        screenshot_ok, video_ok = _ocr_complete_condition(video, page_types)
        if not (screenshot_ok or video_ok):
            missing.append(_ocr_missing_message(shot_count, page_types, video))
        required = {key: 0 for key in ('official', 'camp', 'table', 'video', 'screenshot', 'replay')}
        required_sources = []
    else:
        # 表格按王者营地赛后口径人工抄录，可以单独作为本局的十人面板来源：
        # 旧局（营地只保留一个月回放）拿不到回放时，不再强制要求 official。
        table_ok = statuses['table'] in ('parsed', 'completed') and len(table.get('rows') or []) >= 10
        if not official and not table_ok:
            missing.append('王者营地：请提取并关联本局网页回放链接')
        else:
            # 双合规路径：营地自动流（camp 详情）或传统手动流（七图+录屏）任一即可审核；
            # 本局十人表校验通过时同样算齐。
            camp_ok = statuses['camp'] == 'parsed'
            legacy_ok = statuses['screenshot'] == 'completed' and files_video
            if not camp_ok and not legacy_ok and not table_ok:
                missing.append('营地十人面板：在「营地自动同步」后于本页导入；'
                               '或补齐七张截图与一段录屏，或导入本局十人表')
        required = {'official':1,'camp':0,'table':0,'video':0,'screenshot':0,'replay':0}
        required_sources = CONTRACT['requiredSources']
    return {'policyVersion': CONTRACT['version'], 'statuses': statuses, 'complete': not missing,
            'mode': mode,
            'counts': {'official': int(official), 'camp': int(bool(camp.get('gameSeq'))),
                       'table':len(table.get('files') or []), 'video':files_video,
                       'screenshot':shot_count, 'replay':int(bool(replay.get('replayId')))},
            'required': required,
            'requiredSources': required_sources, 'optionalSources': CONTRACT['optionalSources'],
            'missing':missing}


def require_collection(channel):
    status = source_status(channel)
    if not status['complete']:
        raise ValueError('必采材料未齐：' + '；'.join(status['missing']))


def invalidate_review(channel, actor=None):
    if (channel.get('review') or {}).get('status') == 'reviewed':
        channel['review'] = {**channel['review'], 'status': 'unreviewed', 'reviewedAt': ''}
        append_log(channel, 'review-invalidated', actor, {'reason': 'source or match changed'})


def update_match(channel, values, actor=None):
    invalidate_review(channel, actor)
    match = channel.setdefault('match', {})
    before = {key: match.get(key) for key in values}
    for key, value in values.items():
        if key in ('date', 'opponent', 'session', 'version', 'mode', 'ownSide', 'winner'):
            match[key] = str(value or '').strip()
        elif key == 'durationSec':
            match[key] = int(value) if value not in (None, '') else None
        elif key == 'scores':
            match['scores'] = value if isinstance(value, dict) else {'left': None, 'right': None}
        elif key == 'bp':
            from bp_input import validate_bp
            match['bp'] = validate_bp(value)
    append_log(channel, 'update-match', actor, {'before': before, 'after': values})
    rebuild(channel)


def _side_opposite(side):
    return 'right' if side == 'left' else 'left' if side == 'right' else ''


def derive_winner(own_side, result):
    """按「我方阵营 + 赛后页胜负」推出胜方：win→我方，loss→对面。"""
    result = str(result or '').strip().lower()
    if own_side not in ('left', 'right') or result not in ('win', 'loss'):
        return ''
    return own_side if result == 'win' else _side_opposite(own_side)


def _match_gametime(match, group_match):
    """采集页行展示兼容键 gametime：'MM-DD HH:MM'（没读到时间就只写日期）。"""
    date = str((match or {}).get('date') or (group_match or {}).get('date') or '').strip()
    clock = str((group_match or {}).get('time') or '').strip()
    full = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', date)
    month_day = f'{full.group(2)}-{full.group(3)}' if full else date
    if not month_day:
        return clock
    return f'{month_day} {clock}' if clock else month_day


def _match_gameresult(match):
    """采集页行展示兼容键 gameresult：我方胜=1、我方负=2、未知=0。"""
    own_side, winner = (match or {}).get('ownSide'), (match or {}).get('winner')
    if own_side in ('left', 'right') and winner in ('left', 'right'):
        return 1 if winner == own_side else 2
    return 0


def attach_screenshot(channel, group, image_ids, actor=None):
    invalidate_review(channel, actor)
    ids = [str(value) for value in image_ids]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('截图列表为空或重复')
    source = channel['sources']['screenshot']
    source.update({'status': 'parsed', 'imageIds': ids, 'group': group,
                   'summary': _screenshot_summary(group), 'uploadedAt': now(), 'parsedAt': now()})
    match = group.get('match') or {}
    channel_match = channel.setdefault('match', {})
    if match.get('date') and not channel_match.get('date'):
        channel_match['date'] = match['date']
    if match.get('durationSec') and not channel_match.get('durationSec'):
        channel_match['durationSec'] = match['durationSec']
    if match.get('mode') and not channel_match.get('mode'):
        channel_match['mode'] = str(match['mode'])
    # 赛后截图合并结果的比分键是 score（左/右双列），此前误读成 scores，
    # 导致比分从来没写进 channel.match.scores。
    score = match.get('score') or {}
    scores = channel_match.get('scores') or {}
    if (score.get('left') is not None or score.get('right') is not None) \
            and not any(scores.get(key) is not None for key in ('left', 'right')):
        channel_match['scores'] = {'left': score.get('left'), 'right': score.get('right')}
    if entry_mode(channel) == 'ocr':
        # 王者营地赛后截图左列 = 我方。没显式指定时按左列补 POV，再按胜负推胜方；
        # 只补空值，不覆盖人工/营地已写的阵营与胜负。
        if not channel_match.get('ownSide'):
            channel_match['ownSide'] = 'left'
        if not channel_match.get('winner'):
            winner = derive_winner(channel_match.get('ownSide'), match.get('result'))
            if winner:
                channel_match['winner'] = winner
    # 采集流水按 gametime / gameresult 展示每行；只补空值。
    if not channel_match.get('gametime'):
        gametime = _match_gametime(channel_match, match)
        if gametime:
            channel_match['gametime'] = gametime
    if channel_match.get('gameresult') in (None, ''):
        channel_match['gameresult'] = _match_gameresult(channel_match)
    append_log(channel, 'attach-screenshot', actor, {'imageIds': ids, 'pages': len(group.get('pages') or [])})
    rebuild(channel)


def attach_replay(channel, replay_id, report, actor=None):
    invalidate_review(channel, actor)
    header = report.get('header') or {}
    mvp = report.get('mvpScore') or {}
    roster = []
    for block in (report.get('blocks') or []):
        if not block.get('heroName'):
            continue
        roster.append({
            'hero': block['heroName'], 'heroId': block.get('heroId'),
            'camp': _replay_camp(block.get('camp')),
            'slot': block.get('position') if block.get('position') is not None else block.get('order'),
            'order': block.get('order'),
            'nickname': block.get('name'),
            'entityId': block.get('entityId'),
            'bot': bool(block.get('bot')),
            'rating': block.get('score'),
        })
    versions = header.get('versions') or []
    builds = header.get('builds') or []
    replay_date = _date_from_filename(report.get('abcFileName') or '')
    match = channel.setdefault('match', {})
    if replay_date and not match.get('date'):
        match['date'] = replay_date
    if (versions or builds) and not match.get('version'):
        match['version'] = ' / '.join(versions + builds)
    source = channel['sources']['replay']
    source.update({
        'status': 'parsed', 'replayId': replay_id, 'roster': roster,
        'match': {'date': replay_date, 'versions': versions, 'builds': builds,
                  'mapType': header.get('mapType'), 'mapId': header.get('mapId'),
                  'recorder': _identity_name(header.get('nickname') or header.get('userName')),
                  'localHero': header.get('localHeroName'),
                  'totalFrameNum': header.get('totalFrameNum'),
                  'frameRecords': (report.get('frames') or {}).get('records')},
        'result': {'winningCamp': mvp.get('winningCamp'),
                   'winMvp': mvp.get('winMvp'),
                   'loseMvp': mvp.get('loseMvp') or []},
        'summary': {'blocks': len(roster), 'versions': versions,
                    'localHero': header.get('localHeroName'),
                    'winningCamp': mvp.get('winningCamp'),
                    'winMvp': (mvp.get('winMvp') or {}).get('nickname'),
                    'loseMvp': (mvp.get('loseMvp') or [{}])[0].get('nickname') if mvp.get('loseMvp') else None,
                    'totalFrameNum': header.get('totalFrameNum'),
                    'frameRecords': (report.get('frames') or {}).get('records')},
        'uploadedAt': now(), 'parsedAt': now(),
    })
    append_log(channel, 'attach-replay', actor, {'replayId': replay_id, 'heroes': len(roster)})
    rebuild(channel)


def _fill_match_from_table(channel, rows):
    """表格是旧局唯一来源时，把比赛级字段（日期/对手/时长/比分/胜负）补进通道。"""
    table_rows = [row for row in rows if row.get('grain') == 'match_player']
    if not table_rows:
        return
    match = channel.setdefault('match', {})
    first = table_rows[0].get('keys') or {}
    if not match.get('date') and first.get('date'):
        match['date'] = str(first['date'])[:10]
    if not match.get('opponent') and first.get('opponent'):
        match['opponent'] = str(first['opponent'])
    durations = {((row.get('metrics') or {}).get('duration') or {}).get('value')
                 for row in table_rows}
    durations.discard(None)
    if not match.get('durationSec') and len(durations) == 1:
        try:
            match['durationSec'] = int(next(iter(durations)))
        except (TypeError, ValueError):
            pass
    if not match.get('scores'):
        totals = {}
        for camp in ('blue', 'red'):
            values = [((row.get('metrics') or {}).get('kills') or {}).get('value')
                      for row in table_rows if (row.get('keys') or {}).get('side') == camp]
            if len(values) == 5 and all(isinstance(value, (int, float)) for value in values):
                totals[camp] = int(sum(values))
        if len(totals) == 2:
            match['scores'] = totals
    if not match.get('winner'):
        wins = {'blue': set(), 'red': set()}
        for row in table_rows:
            outcome = (row.get('dimensions') or {}).get('win')
            if outcome in (0, 1):
                wins[(row.get('keys') or {}).get('side')].add(outcome)
        if wins['blue'] == {1} and wins['red'] == {0}:
            match['winner'] = 'left'
        elif wins['blue'] == {0} and wins['red'] == {1}:
            match['winner'] = 'right'


def attach_table(channel, file_info, parsed, actor=None):
    invalidate_review(channel, actor)
    rows = parsed.get('rows') or []
    # 表格自带「本队阵营」时，顺手补齐通道的本队视角；已有（营地详情给的）不覆盖。
    own = next((row['keys'].get('ownSide') for row in rows
                if isinstance(row.get('keys'), dict) and row['keys'].get('ownSide')), None)
    if own in ('blue', 'red') and not (channel.get('match') or {}).get('ownSide'):
        channel.setdefault('match', {})['ownSide'] = 'left' if own == 'blue' else 'right'
    _fill_match_from_table(channel, rows)
    source = channel['sources']['table']
    files = source.setdefault('files', [])
    files.append({**file_info, 'uploadedAt': now(), 'parsedAt': now(), 'status': 'parsed'})
    source.update({'status': 'parsed', 'summary': {
        'files': len(files), 'grain': parsed.get('grain'), 'rows': len(rows),
        'quality': parsed.get('quality') or {}, 'warnings': parsed.get('warnings') or [],
    }})
    source['rows'] = (source.get('rows') or []) + rows
    append_log(channel, 'attach-table', actor, {'file': file_info.get('name'), 'rows': len(rows)})
    rebuild(channel)


def attach_video(channel, file_info, report, actor=None):
    invalidate_review(channel, actor)
    source = channel['sources']['video']
    files = source.setdefault('files', [])
    files.append({**file_info, 'uploadedAt': now(), 'parsedAt': now(), 'status': 'parsed'})
    lineups = report.get('lineups') or {}
    roster = []
    for camp in ('blue', 'red'):
        for index, player in enumerate(lineups.get(camp) or []):
            if not player.get('hero'):
                continue
            # 部分引擎不给 slot：按加载页行序（阵营内 0–4）保留槽位，草稿才能对齐。
            slot = player.get('slot')
            roster.append({'hero': player['hero'], 'nickname': player.get('nickname'),
                           'camp': camp, 'slot': slot if slot is not None else index})
    source.update({'status': 'completed', 'required': 1,
                   'roster': roster,
                   'process': {
                       'scenes': report.get('scenes') or [],
                       'timeline': report.get('timeline') or [],
                       'scoreboardSnapshots': (report.get('scoreboard') or {}).get('snapshots') or [],
                       'killEvents': report.get('killEvents') or [],
                   },
                   'warnings': report.get('warnings') or [],
                   'summary': {'files': len(files), 'required': 1,
                               'heroes': len(roster), 'coverage': report.get('coverage') or {}}})
    # 录屏 POV 阵营 = 本队阵营：blue → 截图左侧，red → 右侧。只补空值，
    # 不覆盖营地/人工已确认的 ownSide。
    pov = report.get('pov') or {}
    camp = str(pov.get('camp') or '').strip().lower()
    if camp in ('blue', 'red') and not channel.setdefault('match', {}).get('ownSide'):
        channel['match']['ownSide'] = 'left' if camp == 'blue' else 'right'
    append_log(channel, 'attach-video', actor, {'file': file_info.get('name'), 'files': len(files)})
    rebuild(channel)


def attach_official(channel, official_id, meta, normalized, actor=None):
    """Attach a required Camp public replay as the official process source.

    It enriches the bundle's team timeline/events/positions but never replaces
    the screenshot's final fields.
    """
    invalidate_review(channel, actor)
    match = normalized.get('match') or {}
    economy = normalized.get('economy') or {}
    events = normalized.get('events') or {}
    positions = normalized.get('positions') or {}
    channel['official'] = {
        'id': official_id, 'schema': normalized.get('schema'),
        'kind': (normalized.get('source') or {}).get('kind'),
        'source': {'gameSeq': meta.get('gameSeq'), 'gameSvr': meta.get('gameSvr'),
                   'relaySvr': meta.get('relaySvr'), 'playerId': meta.get('playerId')},
        'match': match, 'economy': economy, 'events': events,
        'positions': {**positions,
                      'file': ((meta.get('files') or {}).get('positions'))},
        'warnings': normalized.get('warnings') or [],
        'attachedAt': now(),
    }
    append_log(channel, 'attach-official', actor,
               {'officialId': official_id, 'kind': (normalized.get('source') or {}).get('kind'),
                'goldPoints': match.get('goldPoints')})
    rebuild(channel)


def apply_draft(channel, players, actor=None):
    """Apply manual edits to the draft while preserving before/after in the log."""
    if not isinstance(players, list) or not players:
        raise ValueError('草稿修订为空')
    invalidate_review(channel, actor)
    before = _draft_snapshot(channel)
    for item in players:
        side, slot = item.get('side'), item.get('slot')
        target = next((player for player in (channel.get('draft') or {}).get('players', [])
                       if player.get('side') == side and player.get('slot') == slot), None)
        if target is None:
            raise ValueError('草稿选手位置无效')
        edit = channel.setdefault('draftEdits', {}).setdefault(f'{side}-{slot}', {})
        if 'hero' in item:
            hero = str(item.get('hero') or '').strip()
            edit['hero'] = hero or None
        for key, value in (item.get('fields') or {}).items():
            if key not in ALL_FIELDS:
                continue
            if value in (None, ''):
                edit.setdefault('fields', {})[key] = None
                continue
            try:
                parsed = float(str(value).replace(',', '').replace('%', ''))
            except (TypeError, ValueError):
                raise ValueError(f'{FIELD_LABELS.get(key, key)} 不是有效数值')
            if parsed < 0:
                raise ValueError(f'{FIELD_LABELS.get(key, key)} 不能为负数')
            edit.setdefault('fields', {})[key] = parsed if not parsed.is_integer() else int(parsed)
        target['conflicts'] = []
    rebuild(channel)
    after = _draft_snapshot(channel)
    append_log(channel, 'edit-draft', actor, {'changes': _draft_diff(before, after)})


def _draft_snapshot(channel):
    return [{'side': player.get('side'), 'slot': player.get('slot'), 'hero': player.get('hero'),
             'fields': {key: field.get('value') for key, field in (player.get('fields') or {}).items()}}
            for player in (channel.get('draft') or {}).get('players', [])]


def _draft_diff(before, after):
    changes = []
    for old, new in zip(before, after):
        for key in ('hero',):
            if old.get(key) != new.get(key):
                changes.append({'side': new.get('side'), 'slot': new.get('slot'), 'field': key,
                                'before': old.get(key), 'after': new.get(key)})
        fields = set(old.get('fields') or {}) | set(new.get('fields') or {})
        for key in fields:
            old_value = (old.get('fields') or {}).get(key)
            new_value = (new.get('fields') or {}).get(key)
            if old_value != new_value:
                changes.append({'side': new.get('side'), 'slot': new.get('slot'), 'field': key,
                                'before': old_value, 'after': new_value})
    return changes


def set_review(channel, reviewed_by, notes='', actor=None):
    reviewed_by = str(reviewed_by or '').strip()
    if not reviewed_by:
        raise ValueError('请填写复核人')
    require_collection(channel)
    channel['review'] = {'status': 'reviewed', 'reviewedBy': reviewed_by,
                         'reviewedAt': now(), 'notes': str(notes or '')}
    append_log(channel, 'review', actor or reviewed_by, {'notes': notes})
    rebuild(channel)


def rebuild(channel):
    channel['draft'] = _build_draft(channel)
    channel['sourceStatus'] = source_status(channel)
    channel['updatedAt'] = now()


def _screenshot_summary(group):
    match = group.get('match') or {}
    return {'pageTypes': [page.get('pageType') for page in (group.get('pages') or [])],
            'players': len(group.get('players') or []),
            'score': match.get('score') or {},
            'date': match.get('date'), 'durationSec': match.get('durationSec'),
            'coverage': group.get('coverage') or {}, 'warnings': group.get('warnings') or []}


def _build_draft(channel):
    screenshot = channel['sources'].get('screenshot') or {}
    group = screenshot.get('group') or {}
    players = []
    for row in group.get('players') or []:
        fields = {}
        for key in ALL_FIELDS:
            if key == 'rating':
                # Ratings live at player level in postgame_ocr, not in fields.
                field = row.get('rating')
            else:
                # 截图字段名与契约键：damage/taken 对应输出页/生存页的
                # damageDealt/damageTaken，其余扩展指标（cs/jungleGold/...）
                # 截图直接同名。
                source_key = {'damage': 'damageDealt', 'taken': 'damageTaken'}.get(key, key)
                field = (row.get('fields') or {}).get(source_key)
            if field and field.get('value') is not None:
                fields[key] = {'value': field['value'], 'raw': field.get('raw'),
                               'source': 'screenshot', 'confidence': field.get('confidence')}
        players.append({
            'side': row.get('side'), 'slot': row.get('slot'),
            'nickname': (row.get('nickname') or {}).get('value'),
            'hero': (row.get('hero') or {}).get('value'),
            'heroStatus': row.get('heroStatus') or 'unreadable',
            'heroCandidates': row.get('heroCandidates') or [],
            'fields': fields, 'conflicts': [],
            'sources': ['screenshot'] if fields else [],
        })
    if not players:
        for side in ('left', 'right'):
            for slot in range(5):
                players.append({'side': side, 'slot': slot, 'nickname': None, 'hero': None,
                                'heroStatus': 'unreadable', 'heroCandidates': [],
                                'fields': {}, 'conflicts': [], 'sources': []})
    _seed_table_identity(players, channel)
    _merge_table(players, channel)
    _merge_video_identity(players, channel)
    _merge_replay_identity(players, channel)
    _merge_replay_rating(players, channel)
    _merge_camp(players, channel)
    _resolve_heroes(players, _roster(channel))
    _apply_manual(players, channel)
    match = channel.get('match') or {}
    replay = (channel['sources'].get('replay') or {}).get('match') or {}
    draft_match = {
        'date': match.get('date'), 'opponent': match.get('opponent'),
        'session': match.get('session'), 'version': match.get('version'),
        'mode': match.get('mode'), 'durationSec': match.get('durationSec'),
        'startedAt': match.get('startedAt'), 'eventAt': match.get('eventAt'),
        'scores': match.get('scores') or {'left': None, 'right': None},
        'ownSide': match.get('ownSide'), 'winner': match.get('winner'),
        'replay': replay, 'bp': match.get('bp'),
        'result': (channel['sources'].get('replay') or {}).get('result') or {},
    }
    conflicts = []
    for player in players:
        conflicts.extend(player.get('conflicts') or [])
    # 覆盖统计含扩展指标（截图/营地任一来源有值即计入）；缺失清单仍只看
    # hero + 核心必填，扩展字段缺了不挡审核。
    coverage = {key: sum(1 for player in players if player['fields'].get(key)) for key in ALL_FIELDS}
    coverage['hero'] = sum(1 for player in players if player.get('hero'))
    missing = []
    for key in ('hero',) + CORE_FIELDS:
        count = sum(1 for player in players
                    if (player.get('hero') if key == 'hero' else player['fields'].get(key)))
        if count < 10:
            missing.append({'field': key, 'label': FIELD_LABELS[key], 'missing': 10 - count, 'covered': count})
    return {'players': players, 'match': draft_match, 'conflicts': conflicts,
            'missing': missing, 'coverage': coverage}


def _apply_manual(players, channel):
    edits = channel.get('draftEdits') or {}
    for player in players:
        edit = edits.get(f'{player.get("side")}-{player.get("slot")}')
        if not edit:
            continue
        if 'hero' in edit:
            player['hero'] = edit['hero'] or None
            player['heroStatus'] = 'manual' if edit['hero'] else 'unreadable'
            player['heroSource'] = 'manual'
        for key, value in (edit.get('fields') or {}).items():
            if key not in ALL_FIELDS:
                continue
            if value is None:
                player['fields'].pop(key, None)
            else:
                player['fields'][key] = {'value': value, 'raw': str(value),
                                         'source': 'manual', 'confidence': None}


def _normalize_name(value):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]', '', str(value or '').lower())


def _identity_name(value):
    return re.sub(r'[\u200b-\u200f\u2060\ufeff\ufe0e\ufe0f]', '', str(value or '')).strip() or None


def _replay_camp(value):
    return 'blue' if value == 1 else 'red' if value == 2 else None


def _side_from_camp(value):
    return 'left' if value == 'blue' else 'right' if value == 'red' else None


def _date_from_filename(name):
    match = re.search(r'(\d{4})(\d{2})(\d{2})_', str(name or ''))
    if not match:
        return None
    return f'{match.group(1)}-{match.group(2)}-{match.group(3)}'


def _seed_table_identity(players, channel):
    """A single-game table with explicit sides can establish its own row order."""
    if any(player.get('hero') or player.get('nickname') for player in players):
        return
    rows = [row for row in (channel['sources'].get('table') or {}).get('rows') or []
            if row.get('grain') == 'match_player' and not row.get('aggregated')]
    match_ids = {(row.get('keys') or {}).get('matchId') or (row.get('keys') or {}).get('matchNo') for row in rows}
    if len(match_ids) > 1:
        return
    groups = {'left': [], 'right': []}
    for row in rows:
        keys = row.get('keys') or {}
        side = keys.get('side') or (row.get('dimensions') or {}).get('side')
        side = {'blue': 'left', 'red': 'right', 'left': 'left', 'right': 'right'}.get(side)
        if side:
            groups[side].append(row)
    if any(len(group) != 5 for group in groups.values()):
        return
    for side, group in groups.items():
        identities = [(row.get('keys') or {}).get('hero') or (row.get('keys') or {}).get('player') for row in group]
        if not all(identities) or len(set(identities)) != 5:
            return
    for side, group in groups.items():
        for slot, row in enumerate(group):
            target = next(player for player in players if player['side'] == side and player['slot'] == slot)
            keys = row.get('keys') or {}
            target.update(hero=keys.get('hero'), nickname=keys.get('player'),
                          position=keys.get('position') or None,
                          heroStatus='table', heroSource='table')


def attach_camp_detail(channel, game_seq, detail, official_players=None, actor=None):
    """营地登录态详情（battledetail）：BP、十人面板与出装，数值来源标 camp。

    official_players 来自公开回放接口的 matchInfo（playerId→heroName），
    用于把营地十人对到英雄名；没有时只填昵称，英雄待 official 关联后补。
    """
    invalidate_review(channel, actor)
    data = (detail or {}).get('data') or {}
    head = data.get('head') or {}
    official_players = official_players or []
    by_player_id = {str(item.get('playerId')): item for item in official_players
                    if item.get('playerId') is not None}
    # 公开接口的 matchInfo 身份字段被脱敏（roleId/userId 为 0），playerId 与
    # 营地详情不是同一体系；阵营内顺序（blue 5 人 / red 5 人）是同局一一对应的。
    official_by_camp = {'blue': [], 'red': []}
    for item in official_players:
        camp_code = str(item.get('camp') or item.get('acntcamp') or '')
        camp_key = {'1': 'blue', '2': 'red', 'blue': 'blue', 'red': 'red'}.get(camp_code)
        if camp_key:
            official_by_camp[camp_key].append(item)
    players, ban, team_gold, ban_names = [], {}, {}, {}
    for roles_key, camp in (('blueRoles', 'blue'), ('redRoles', 'red')):
        roles = data.get(roles_key) or []
        if len(roles) != 5:
            raise ValueError(f'{camp} 阵营人数异常（{len(roles)}，应为 5）')
        team = data.get(f'{camp}Team') or {}
        ban[camp] = [item.get('heroId') for item in (team.get('banHeros') or []) if item.get('heroId')]
        try:
            from hero_catalog import hero_names as _hero_id_names
            ban_names[camp] = _hero_id_names(ban[camp])
        except Exception:
            ban_names[camp] = []
        team_gold[camp] = team.get('money')
        for index, role in enumerate(roles):
            basic = role.get('basicInfo') or {}
            stats = role.get('battleStats') or {}
            battle_record = role.get('battleRecords') or {}
            used_hero = battle_record.get('usedHero') or {}
            position = POSITION_LANES.get(_camp_number(battle_record.get('position')))
            official_match = by_player_id.get(str(basic.get('playerId') or ''))
            if official_match is None and len(official_by_camp.get(camp) or []) == 5:
                official_match = official_by_camp[camp][index]
            fields = {}
            for src, dst in CAMP_STAT_MAP.items():
                value = _camp_number(stats.get(src))
                if value is not None:
                    fields[dst] = value
            participation = _camp_number(stats.get('joinGamePercent'))
            if participation is not None:
                fields['participation'] = round(float(participation) * 100, 1)
            rating = _camp_number(stats.get('gradeGame'))
            if rating is not None:
                fields['rating'] = float(rating)
            players.append({'camp': camp, 'slot': index,
                            'playerId': str(basic.get('playerId') or ''),
                            'nickname': _identity_name(basic.get('roleName')),
                            'hero': used_hero.get('heroName') or (official_match or {}).get('heroName') or (official_match or {}).get('hero'),
                            'heroId': used_hero.get('heroId') or (official_match or {}).get('heroId'),
                            'position': position,
                            'stats': fields})
    # 本人阵营：head.acntCamp（1=蓝 / 2=红）→ 通道的 ownSide
    head_camp = str(head.get('acntCamp') or '')
    match = channel.setdefault('match', {})
    if head_camp in ('1', '2') and not match.get('ownSide'):
        match['ownSide'] = 'left' if head_camp == '1' else 'right'
    # 营地列表的 dtEventTime 是记录发送时间；减 usedTime 得到开赛时间。
    # 只补空值：人工填写的日期/时间优先，不被营地覆盖。
    times = camp_times(detail)
    if times:
        for key in ('startedAt', 'eventAt'):
            if times.get(key) and not match.get(key):
                match[key] = times[key]
        if times.get('date') and not match.get('date'):
            match['date'] = times['date']
    if sum(1 for player in players if player['stats']) != 10:
        raise ValueError('营地详情的十人面板不完整，拒绝入库')
    # 人头比：团队击杀 = 本阵营五人 killCnt 之和（未手工填写时自动补）
    def _team_kills(roles):
        total = 0
        for role in roles or []:
            stats = role.get('battleStats') or {}
            try:
                total += int(float(stats.get('killCnt') or 0))
            except (TypeError, ValueError):
                pass
        return total
    scores = channel.setdefault('match', {}).setdefault('scores', {'left': None, 'right': None})
    if scores.get('left') is None and scores.get('right') is None:
        blue_kills = _team_kills(data.get('blueRoles'))
        red_kills = _team_kills(data.get('redRoles'))
        if blue_kills or red_kills:
            scores['left'], scores['right'] = blue_kills, red_kills
    source = channel['sources'].setdefault('camp', {})
    # 名单口径 BP：营地同时给 banHeros / pickHeros（终局名单，无手序、无一手方）。
    # 与人工校对录入的 match.bp 分开存，避免把阵容冒充 1–5 楼手序。
    from bp_camp import parse_camp_bp
    camp_bp = parse_camp_bp(detail, game_seq)
    pick_names = ({'blue': [item['name'] for item in camp_bp['picks']['left']],
                   'red': [item['name'] for item in camp_bp['picks']['right']]}
                  if camp_bp else {'blue': [], 'red': []})
    source.update({'status': 'parsed', 'gameSeq': str(game_seq),
                   'mapName': head.get('mapName'),
                   'players': players, 'ban': ban, 'banNames': ban_names,
                   'pickNames': pick_names, 'bp': camp_bp,
                   'teamGold': team_gold, 'times': times,
                   'attachedAt': now(), 'parsedAt': now()})
    append_log(channel, 'attach-camp', actor,
               {'gameSeq': game_seq, 'players': len(players),
                'gold': team_gold})
    rebuild(channel)


def _merge_camp(players, channel):
    """营地详情的数值按 昵称/英雄 匹配进草稿；与截图/表格的冲突保留待核对。"""
    rows = (channel['sources'].get('camp') or {}).get('players') or []
    for row in rows:
        side = _side_from_camp(row.get('camp'))
        if not side:
            continue
        target = _replay_target(players, row, side)
        if target is None:
            continue
        nickname = _identity_name(row.get('nickname'))
        if nickname and not target.get('nickname'):
            target['nickname'] = nickname
            target['sources'] = list(dict.fromkeys(target['sources'] + ['camp']))
        if row.get('hero') and not target.get('hero'):
            target['hero'] = row['hero']
            target['heroStatus'] = 'exact'
            target['heroSource'] = 'camp'
            target['sources'] = list(dict.fromkeys(target['sources'] + ['camp']))
        if row.get('position'):
            target['position'] = row['position']
        for key, value in (row.get('stats') or {}).items():
            if key not in ALL_FIELDS or value is None:
                continue
            current = target['fields'].get(key)
            # 显示精度内的差异（66.1k ↔ 66056、48% ↔ 48.1）不是冲突；
            # 真不一致才留痕，并把来源值都写明（营地值原先没带来源标签）。
            if (current and current.get('source') in ('screenshot', 'table')
                    and not _same_as_displayed(current, value, key)):
                conflict = {'side': target['side'], 'slot': target['slot'], 'field': key,
                            'camp': value}
                conflict[current.get('source')] = current.get('value')
                target['conflicts'].append(conflict)
            target['fields'][key] = {'value': value, 'raw': str(value),
                                     'source': 'camp', 'confidence': 'high'}
            target['sources'] = list(dict.fromkeys(target['sources'] + ['camp']))


def _merge_table(players, channel):
    rows = (channel['sources'].get('table') or {}).get('rows') or []
    for row in rows:
        keys = row.get('keys') or {}
        hero = _normalize_name(keys.get('hero'))
        nickname = _normalize_name(keys.get('player'))
        side = keys.get('side') or (row.get('dimensions') or {}).get('side')
        side = {'blue': 'left', 'red': 'right', 'left': 'left', 'right': 'right'}.get(side)
        candidates = [player for player in players if (not side or player.get('side') == side)
                      and ((hero and _normalize_name(player.get('hero')) == hero)
                           or (nickname and _normalize_name(player.get('nickname')) == nickname))]
        if len(candidates) != 1:
            continue
        target = candidates[0]
        if not target.get('position') and keys.get('position'):
            target['position'] = keys.get('position')
        for key, metric in (row.get('metrics') or {}).items():
            if key not in CORE_FIELDS or not isinstance(metric, dict) or not metric.get('valid'):
                continue
            value = metric.get('value')
            if value is None:
                continue
            current = target['fields'].get(key)
            if current is None:
                target['fields'][key] = {'value': value, 'raw': metric.get('raw'),
                                         'source': 'table', 'confidence': None}
                target['sources'] = list(dict.fromkeys(target['sources'] + ['table']))
            elif not _same_as_displayed(current, value, key):
                # 表格是精确值，截图可能只有 8.7k / 48% 的显示精度；同屏读数不算冲突。
                target['conflicts'].append({'side': target['side'], 'slot': target['slot'], 'field': key,
                                            'screenshot': current.get('value'), 'table': value})


def _video_roster_slots(roster):
    """录屏十人 roster 的阵营内槽位：优先行自带 slot，缺省按该阵营出现顺序。"""
    counters = {'blue': 0, 'red': 0}
    result = []
    for item in roster:
        camp = item.get('camp')
        order = counters.get(camp, 0)
        counters[camp] = order + 1
        slot = item.get('slot')
        result.append((item, slot if slot is not None else order))
    return result


def _merge_video_identity(players, channel):
    roster = (channel['sources'].get('video') or {}).get('roster') or []
    # 1) 已有英雄、缺昵称的行：按英雄名从 roster 补昵称（截图/表格补采场景）。
    for player in players:
        if player.get('nickname') or not player.get('hero'):
            continue
        match = next((item for item in roster if item.get('hero')
                      and _normalize_name(item['hero']) == _normalize_name(player.get('hero'))), None)
        if match and match.get('nickname'):
            player['nickname'] = match['nickname']
            player['sources'] = list(dict.fromkeys(player['sources'] + ['video']))
    # 2) 完全没有身份的空行（录屏新录入时没有截图组）：按 roster 的阵营 + 槽位
    #    补英雄/昵称。只填空行，不覆盖截图/表格/阵容页已确认的身份。
    by_side_slot = {}
    for item, slot in _video_roster_slots(roster):
        side = _side_from_camp(item.get('camp'))
        if side and item.get('hero') and (side, slot) not in by_side_slot:
            by_side_slot[(side, slot)] = item
    for player in players:
        if player.get('hero') or player.get('nickname'):
            continue
        item = by_side_slot.get((player.get('side'), player.get('slot')))
        if item is None:
            continue
        player['hero'] = item['hero']
        player['heroStatus'] = 'exact'
        player['heroSource'] = 'video'
        if item.get('nickname'):
            player['nickname'] = item['nickname']
        player['sources'] = list(dict.fromkeys(player['sources'] + ['video']))


def _replay_target(players, item, side):
    """Match replay roster to screenshot rows by nickname/hero, never only by row order."""
    candidates = [player for player in players if player.get('side') == side]
    nickname = item.get('nickname')
    if nickname:
        target = next((player for player in candidates if player.get('nickname')
                       and _normalize_name(player['nickname']) == _normalize_name(nickname)), None)
        if target is not None:
            return target
    hero = item.get('hero')
    if hero:
        target = next((player for player in candidates if player.get('hero')
                       and _normalize_name(player['hero']) == _normalize_name(hero)), None)
        if target is not None:
            return target
    return next((player for player in candidates if player.get('slot') == item.get('slot')), None)


def _merge_replay_identity(players, channel):
    """Fill missing identity from the replay roster using nickname/hero first."""
    roster = (channel['sources'].get('replay') or {}).get('roster') or []
    for item in roster:
        side = _side_from_camp(item.get('camp'))
        if not side:
            continue
        target = _replay_target(players, item, side)
        if target is None:
            continue
        nickname = _identity_name(item.get('nickname'))
        if nickname:
            # Replay names come from the game file; prefer them over small OCR errors.
            target['nickname'] = nickname
            target['sources'] = list(dict.fromkeys(target['sources'] + ['replay']))
        if item.get('hero'):
            target['hero'] = item['hero']
            target['heroStatus'] = 'exact'
            target['heroSource'] = 'replay'
            target['sources'] = list(dict.fromkeys(target['sources'] + ['replay']))
        target['replayEntityId'] = item.get('entityId')
        target['replayBot'] = item.get('bot')


def _merge_replay_rating(players, channel):
    """Fill the only final per-player field the replay can provide: rating."""
    roster = (channel['sources'].get('replay') or {}).get('roster') or []
    for item in roster:
        side = _side_from_camp(item.get('camp'))
        rating = item.get('rating')
        if not side or rating is None:
            continue
        target = _replay_target(players, item, side)
        if target is None or target['fields'].get('rating') is not None:
            continue
        target['fields']['rating'] = {'value': rating, 'raw': str(rating),
                                      'source': 'replay', 'confidence': 'high'}
        target['sources'] = list(dict.fromkeys(target['sources'] + ['replay']))


def _roster(channel):
    names = []
    for item in (channel['sources'].get('replay') or {}).get('roster') or []:
        if item.get('hero'):
            names.append(item['hero'])
    for item in (channel['sources'].get('video') or {}).get('roster') or []:
        if item.get('hero'):
            names.append(item['hero'])
    for row in (channel['sources'].get('table') or {}).get('rows') or []:
        hero = (row.get('keys') or {}).get('hero')
        if hero:
            names.append(hero)
    return list(dict.fromkeys(name for name in names if name))


def _resolve_heroes(players, roster):
    if not roster:
        return
    known = list(dict.fromkeys(roster))
    assigned = {player['hero'] for player in players if player.get('hero') in known}
    for player in players:
        if player.get('hero') in known:
            player['heroStatus'] = player.get('heroStatus') or 'exact'
            player['heroSource'] = 'source'
            continue
        candidates = [item.get('name') for item in (player.get('heroCandidates') or []) if item.get('name')]
        choice = next((name for name in candidates if name in known and name not in assigned), None)
        if choice:
            player['hero'] = choice
            player['heroStatus'] = 'roster-candidate'
            player['heroSource'] = 'roster-candidate'
            assigned.add(choice)
    missing = [player for player in players if not player.get('hero')]
    remaining = [name for name in known if name not in assigned]
    if len(missing) == 1 and len(remaining) == 1:
        missing[0]['hero'] = remaining[0]
        missing[0]['heroStatus'] = 'roster-elimination'
        missing[0]['heroSource'] = 'roster-elimination'


def bundle(channel):
    require_collection(channel)
    if (channel.get('review') or {}).get('status') != 'reviewed':
        raise ValueError('请先完成人工审核')
    draft = channel.get('draft') or {}
    match = draft.get('match') or {}
    players = []
    for player in draft.get('players') or []:
        fields = player.get('fields') or {}
        camp = 'blue' if player.get('side') == 'left' else 'red'
        final = {
            'source': 'channel', 'partial': any(not fields.get(key) for key in CORE_FIELDS),
            'kills': (fields.get('kills') or {}).get('value'),
            'deaths': (fields.get('deaths') or {}).get('value'),
            'assists': (fields.get('assists') or {}).get('value'),
            'totalGold': (fields.get('gold') or {}).get('value'),
            'damage': (fields.get('damage') or {}).get('value'),
            'taken': (fields.get('taken') or {}).get('value'),
            'participation': (fields.get('participation') or {}).get('value'),
            'rating': (fields.get('rating') or {}).get('value'),
            'complete': all((fields.get(key) or {}).get('value') is not None for key in CORE_FIELDS),
        }
        # B 组扩展字段随 bundle 一起落盘，供跨局聚合消费；缺失保持 None，
        # 不估算补数，也不影响上面的 complete/partial 判定。
        for key in CAMP_EXTENDED_FIELDS:
            final[key] = (fields.get(key) or {}).get('value')
        players.append({
            'key': f'{camp}-{player.get("slot")}', 'camp': camp, 'side': camp,
            'slot': player.get('slot'), 'panelSlot': player.get('slot'),
            'hero': player.get('hero'), 'heroId': player.get('heroId'),
            'position': player.get('position'),
            'heroStatus': player.get('heroStatus'),
            'heroSource': player.get('heroSource'), 'nickname': player.get('nickname'),
            'nicknameRaw': player.get('nickname'), 'nicknameConfidence': None,
            'replayEntityId': player.get('replayEntityId'),
            'replayBot': player.get('replayBot'),
            'final': final, 'process': {},
            'sources': sorted({field.get('source') for field in fields.values() if field.get('source')}),
        })
    own_side = match.get('ownSide')
    winner_side = match.get('winner')
    camp_map = {'left': 'blue', 'right': 'red'}
    own_camp = camp_map.get(own_side)
    winner_camp = camp_map.get(winner_side)
    # 未手工指定胜负时，用官方回放的 winCamp（'1'=蓝 / '2'=红）推断
    if not winner_camp:
        win_code = str(((channel.get('official') or {}).get('match') or {}).get('winCamp') or '')
        if win_code in ('1', '2'):
            winner_camp = 'blue' if win_code == '1' else 'red'
    scores = dict(match.get('scores') or {})
    if 'left' in scores or 'right' in scores:
        scores.setdefault('blue', scores.get('left'))
        scores.setdefault('red', scores.get('right'))
    match_body = {
        'key': f'channel-{channel.get("id")}',
        'title': ' · '.join(value for value in (match.get('session'), f'vs {match.get("opponent")}' if match.get('opponent') else None) if value) or '采集通道',
        'mode': match.get('mode'), 'date': _date_parts(match.get('date')),
        'startTime': match.get('startedAt') or None,
        'duration': match.get('durationSec'), 'scores': scores,
        'ownSide': own_side or None, 'ownCamp': own_camp,
        'winner': winner_camp, 'winnerCamp': winner_camp,
        'identity': {'confidence': 'manual-review', 'checks': {}, 'warnings': []},
        'videoCoverage': None, 'bp': match.get('bp'),
        # 营地名单口径 BP 单独带出，供跨局聚合；人工 bp 优先、它作兜底。
        'campBp': (channel.get('sources', {}).get('camp') or {}).get('bp'),
        'opponent': match.get('opponent'), 'session': match.get('session'),
    }
    replay_result = (channel.get('sources', {}).get('replay') or {}).get('result') or {}
    if winner_camp:
        replay_result = {**replay_result, 'winningCamp': winner_camp}
    if replay_result:
        match_body['result'] = replay_result
    if match.get('replay'):
        match_body['replay'] = match['replay']
    channel_source = {'kind': 'channel', 'file': f'channel-{channel.get("id")}',
                      'sha256': None, 'channelSources': source_status(channel)}
    if own_camp:
        recorder = ((channel.get('sources', {}).get('replay') or {}).get('match') or {}).get('recorder')
        channel_source['followPlayer'] = {'camp': own_camp, **({'nickname': recorder} if recorder else {})}
    video = (channel.get('sources', {}).get('video') or {})
    process = video.get('process') or {}
    scenes = process.get('scenes') or []
    if scenes:
        first = min(float(scene.get('start') or 0) for scene in scenes)
        last = max(float(scene.get('end') or 0) for scene in scenes)
        game = sum(float(scene.get('end') or 0) - float(scene.get('start') or 0)
                   for scene in scenes if scene.get('type') == 'game')
        if last > first:
            match_body['videoCoverage'] = {
                'start': round(first, 3), 'end': round(last, 3),
                'ratio': round(max(0, min(1, game / (last - first))), 3),
            }
    official = channel.get('official') or {}
    official_economy = official.get('economy') or {}
    official_timeline = []
    for index, (blue, red) in enumerate(zip(official_economy.get('blue') or [],
                                            official_economy.get('red') or [])):
        official_timeline.append({'gameTime': 30 * (index + 1),
                                  'blueGold': blue, 'redGold': red,
                                  'blueKills': None, 'redKills': None,
                                  'goldDiff': blue - red,
                                  'source': 'official-30s'})
    if official:
        official_match = official.get('match') or {}
        official_positions = official.get('positions') or {}
        match_body['officialReplay'] = {
            'id': official.get('id'), 'kind': official.get('kind'),
            'winCamp': official_match.get('winCamp'),
            'teams': official_match.get('teams'), 'score': official_match.get('score'),
            'teamGold': official_match.get('teamGold'),
            'goldPoints': official_match.get('goldPoints'),
            'goldIntervalSecApprox': official_match.get('goldIntervalSecApprox'),
            'events': official_match.get('keyEvents'),
            'positions': {'perSecond': official_positions.get('perSecond'),
                          'pointsPerPlayer': official_positions.get('pointsPerPlayer'),
                          'file': official_positions.get('file')},
        }
    warnings = _bundle_warnings(channel)
    generic = ('OCR 只读取画面可见文字', '顶部金币是团队累计经济',
               '逐人经济只在打开记分板时可见', '英雄名以加载页印刷文字为准',
               '识别结果保留原文与置信度', 'Mimo 精读不可用')
    for warning in video.get('warnings') or []:
        if warning.startswith(generic) or warning in warnings:
            continue
        warnings.append(warning)
    if own_camp:
        warnings.append('本队阵营来自回放/录制 POV：blue = 截图左侧；截图本身只描述左右布局。')
    else:
        warnings.append('截图/表格阵营只按 left/right 映射为 blue/red 用于分析展示，不代表真实红蓝方。')
    if official and official_timeline:
        warnings.append('官方回放金币为约30秒一个点；有1秒位置，但没有1秒金币。')
    team = {'timeline': official_timeline or process.get('timeline') or [],
            'scoreboardSnapshots': process.get('scoreboardSnapshots') or [],
            'killEvents': process.get('killEvents') or []}
    if official_timeline:
        team['timelineSource'] = 'official-30s'
        team['recordingTimeline'] = process.get('timeline') or []
    if official:
        team['officialEvents'] = official.get('events') or {}
        team['positions'] = official.get('positions') or {}
    return {
        'schema': BUNDLE_SCHEMA,
        'generatedAt': now(),
        'match': match_body,
        'sources': [channel_source],
        'roster': {'blue': [player for player in players if player['camp'] == 'blue'],
                   'red': [player for player in players if player['camp'] == 'red']},
        'team': team,
        'players': players,
        'coverage': draft.get('coverage') or {},
        'warnings': warnings,
    }


def _bundle_warnings(channel):
    """已入库比赛只留「字段缺失」这类复核可见性提示。

    跨来源冲突是采集/复核阶段的事（草稿 ``draft.conflicts`` 仍保留在通道里，
    供工作台核对），不再写进单局数据包：入库后的对局页只做复盘，不重复展示
    采集阶段的来源冲突。显示精度的差异（66.1k ↔ 66056）此前被误报成冲突，
    根因已在 ``_merge_camp`` / ``_merge_table`` 里修掉。
    """
    warnings = []
    draft = channel.get('draft') or {}
    for item in draft.get('missing') or []:
        warnings.append(f'{item.get("label")} 缺失 {item.get("missing")}/10')
    return warnings


def _date_parts(value):
    match = re.fullmatch(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', str(value or ''))
    if not match:
        return {'year': None, 'month': None, 'day': None, 'text': value or None}
    year, month, day = (int(part) for part in match.groups())
    return {'year': year, 'month': month, 'day': day,
            'text': f'{year}-{month:02d}-{day:02d}'}
