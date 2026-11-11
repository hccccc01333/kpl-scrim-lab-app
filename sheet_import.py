"""导入赛训组已有的表格：先画像，再映射，最后落盘为原始+规范化两层。

支持 CSV/TSV 与 XLSX/XLSM。导入器不会把聚合字段当成单局字段，也不会把
百分比/场均值重新求和；未识别的列原样保留在 raw 里。
"""
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = 'kpl-sheet-import-v1'
PROFILE_VERSION = 1
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 200_000

GRAINS = ('match_player', 'match_team', 'event', 'aggregate_player',
          'aggregate_team', 'aggregate_hero', 'match_wide')
AGGREGATE_GRAINS = {'aggregate_player', 'aggregate_team', 'aggregate_hero'}
KEY_FIELDS = {'date', 'matchId', 'matchNo', 'session', 'period', 'player', 'playerId',
              'hero', 'team', 'opponent', 'side', 'ownSide', 'position', 'event', 'time', 'frame'}
DIMENSION_FIELDS = {'session', 'period', 'opponent', 'position', 'team', 'side',
                    'event', 'skill', 'equipment', 'runes', 'win'}
METRIC_FIELDS = {'kills', 'deaths', 'assists', 'kda', 'gold', 'gpm', 'damage', 'dpm',
                 'taken', 'tpm', 'avgGold', 'avgDamage', 'avgTaken', 'participation',
                 'damageShare', 'goldShare', 'takenShare', 'rating', 'winRate',
                 'games', 'wins', 'losses', 'duration', 'towers', 'objectives',
                 'level', 'hp', 'frame', 'x', 'y'}
AGGREGATE_ONLY = {'winRate', 'games', 'wins', 'losses', 'avgGold', 'avgDamage', 'avgTaken'}

# field -> (measureKind, unit, low, high)
FIELD_META = {
    'kills': ('total', 'count', 0, 500),
    'deaths': ('total', 'count', 0, 500),
    'assists': ('total', 'count', 0, 500),
    'kda': ('ratio', 'ratio', 0, 100),
    'gold': ('total', 'amount', 0, 10_000_000),
    'damage': ('total', 'amount', 0, 10_000_000),
    'taken': ('total', 'amount', 0, 10_000_000),
    'gpm': ('average', 'amount/minute', 0, 100_000),
    'dpm': ('average', 'amount/minute', 0, 100_000),
    'tpm': ('average', 'amount/minute', 0, 100_000),
    'avgGold': ('average', 'amount', 0, 1_000_000),
    'avgDamage': ('average', 'amount', 0, 1_000_000),
    'avgTaken': ('average', 'amount', 0, 1_000_000),
    'participation': ('percentage', 'percent', 0, 100),
    'damageShare': ('percentage', 'percent', 0, 100),
    'goldShare': ('percentage', 'percent', 0, 100),
    'takenShare': ('percentage', 'percent', 0, 100),
    'rating': ('total', 'score', 0, 100),
    'winRate': ('percentage', 'percent', 0, 100),
    'win': ('outcome', 'outcome', 0, 1),
    'games': ('count', 'count', 0, 100_000),
    'wins': ('count', 'count', 0, 100_000),
    'losses': ('count', 'count', 0, 100_000),
    'duration': ('total', 'seconds', 0, 7200),
    'towers': ('count', 'count', 0, 100),
    'objectives': ('count', 'count', 0, 100),
    'level': ('total', 'count', 0, 30),
    'hp': ('total', 'amount', 0, 1_000_000),
    'frame': ('count', 'count', 0, 10_000_000),
    'x': ('coordinate', 'coordinate', -1_000_000, 1_000_000),
    'y': ('coordinate', 'coordinate', -1_000_000, 1_000_000),
}

ALIASES = {
    'date': ['日期', '比赛日期', '对局日期', '开赛日期', 'date', 'day'],
    'matchId': ['对局id', '比赛id', '局id', '场次id', '对局编号', 'matchid', 'match_id',
                'gameid', 'game_id', 'battleid'],
    'matchNo': ['第几场', '场次号'],
    'session': ['赛事', '赛段', '训练赛', '比赛名称', '阶段', 'session', 'eventname'],
    'period': ['周期', '统计周期', '时间段', '版本', 'period', 'stage'],
    'player': ['选手', '队员', '玩家', '昵称', '队员昵称', '选手昵称', '用户名',
               'player', 'playername', 'nickname'],
    'playerId': ['选手id', '队员id', '玩家id', 'playerid', 'player_id'],
    'hero': ['英雄', '使用英雄', '英雄名称', 'hero', 'heroid'],
    'team': ['队伍', '战队', '队伍名称', '战队名称', '我方', 'team'],
    'opponent': ['对手', '敌方', '对方', 'opponent', 'enemy'],
    'side': ['阵营', '红蓝', '红蓝方', 'side', 'camp'],
    'ownSide': ['本队阵营', '本队', '我方阵营', 'ownside', 'ourside'],
    'position': ['位置', '分路', '对位', 'position', 'role', 'lane'],
    'event': ['事件', '事件类型', '行为', 'action', 'event'],
    'time': ['时间', '时刻', '秒', '比赛时间', 'time', 'timestamp', 'elapsed'],
    'frame': ['帧', '帧号', 'frame', 'framenum'],
    'skill': ['技能', '技能id', 'skill', 'skillid'],
    'equipment': ['装备', '出装', 'equipment', 'items'],
    'runes': ['铭文', 'runes'],
    'win': ['胜负', '结果', '输赢', 'win', 'result', 'victory'],
    'kills': ['击杀', '击杀数', 'kill', 'kills', 'k'],
    'deaths': ['死亡', '死亡数', 'death', 'deaths', 'd'],
    'assists': ['助攻', '助攻数', 'assist', 'assists', 'a'],
    'kda': ['kda', 'k/d/a'],
    'gold': ['经济', '金币', '总经济', '经济量', 'gold', 'goldearned'],
    'gpm': ['分均经济', '每分钟经济', 'gpm', 'goldpermin', 'goldperminute'],
    'damage': ['输出', '伤害', '对英雄伤害', '输出伤害', 'damage', 'herodamage'],
    'dpm': ['分均伤害', '每分钟伤害', 'dpm', 'damagepermin'],
    'taken': ['承伤', '承受伤害', '承伤量', 'taken', 'damagetaken'],
    'tpm': ['分均承伤', '每分钟承伤', 'tpm', 'takenpermin'],
    'avgGold': ['场均经济', '平均经济', 'avggold'],
    'avgDamage': ['场均伤害', '平均伤害', 'avgdamage'],
    'avgTaken': ['场均承伤', '平均承伤', 'avgtaken'],
    'participation': ['参团率', '参团', 'participation', 'killparticipation'],
    'damageShare': ['输出占比', '伤害占比', 'damageshare'],
    'goldShare': ['经济占比', 'goldshare'],
    'takenShare': ['承伤占比', 'takenshare'],
    'rating': ['评分', '综合评分', 'rating', 'score'],
    'winRate': ['胜率', 'winrate', 'win_rate'],
    'games': ['场次', '局数', '出场次数', 'games', 'matches', 'count'],
    'wins': ['胜场', '胜场数', 'wins'],
    'losses': ['负场', '负场数', 'losses'],
    'duration': ['时长', '比赛时长', '游戏时长', 'duration', 'gametime'],
    'towers': ['推塔', '摧毁防御塔', 'towers'],
    'objectives': ['暴君', '主宰', '龙', '中立资源', 'objectives'],
    'level': ['等级', 'level'],
    'hp': ['血量', '生命', 'hp'],
    'x': ['x', 'x坐标', 'posx'],
    'y': ['y', 'y坐标', 'posy'],
}
class SheetImportError(ValueError):
    """表格无法读取或 profile 不合法。"""


def compact_name(text):
    value = unicodedata.normalize('NFKC', str(text or '')).strip().lower()
    value = re.sub(r'[\s_\-/\\()（）\[\]{}<>《》【】:：,，.。;；\'"“”%]+', '', value)
    return value


ALIAS_LOOKUP = {}
for field, names in ALIASES.items():
    for name in names:
        ALIAS_LOOKUP.setdefault(compact_name(name), field)


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value != value:
        return None
    return value


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(',', '').replace('，', '')
    match = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*([kK万wW]?)', text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    multiplier = {'k': 1000, 'K': 1000, '万': 10000, 'w': 10000, 'W': 10000}.get(unit, 1)
    value = number * multiplier
    return int(value) if float(value).is_integer() else value


def _date_value(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or '').strip()
    if not text:
        return None
    text = text.replace('年', '-').replace('月', '-').replace('日', '')
    match = re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?', text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.fullmatch(r'(\d{4})(\d{2})(\d{2})', text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:[ T].*)?', text)
    if match:
        return f"{int(match.group(3)):04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    match = re.fullmatch(r'(\d{1,2})[-/.](\d{1,2})(?:[ T].*)?', text)
    if match:
        return f"{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return None


def _date_like(value):
    return _date_value(value) is not None


def _percent_like(value):
    if isinstance(value, str) and '%' in value:
        return True
    return False


def _win_loss(value):
    text = compact_name(value)
    if text in ('胜', '胜方', '赢', '胜利', 'win', 'w', '1', 'true'):
        return 1
    if text in ('负', '败', '输', '失败', 'loss', 'l', '0', 'false'):
        return 0
    return None


def profile_values(values):
    values = [value for value in values if value not in (None, '')]
    numbers = percents = dates = outcomes = 0
    for value in values:
        if isinstance(value, (datetime, date)):
            dates += 1
            continue
        if _percent_like(value):
            percents += 1
            continue
        if _date_like(value):
            dates += 1
            continue
        if _number(value) is not None:
            numbers += 1
        elif _win_loss(value) is not None:
            outcomes += 1
    return {'count': len(values), 'numbers': numbers, 'percents': percents,
            'dates': dates, 'outcomes': outcomes,
            'examples': [str(_json_value(value)) for value in values[:3]]}


def _field_kind(field):
    if field in METRIC_FIELDS:
        return 'metric'
    if field in DIMENSION_FIELDS:
        return 'dimension'
    return 'key'


def suggest_field(header, values):
    compact = compact_name(header)
    stats = profile_values(values)
    if '时间' in compact or '时刻' in compact or compact in ('time', 'timestamp'):
        if stats['dates'] > stats['numbers']:
            return {'field': 'date', 'confidence': 0.8, 'kind': 'key',
                    'note': '列名含“时间”，按日期值判断为日期'}
        return {'field': 'time', 'confidence': 0.7, 'kind': 'key',
                'note': '列名含“时间”，按数值/事件判断为局内时间'}
    field = ALIAS_LOOKUP.get(compact)
    if field:
        return {'field': field, 'confidence': 0.95, 'kind': _field_kind(field)}
    # 带前缀的列（如“蓝方上单_击杀”）用最长别名匹配，作为低置信候选。
    candidates = [(len(alias), field) for alias, field in ALIAS_LOOKUP.items()
                  if len(alias) >= 2 and alias in compact]
    if candidates:
        _, field = max(candidates)
        return {'field': field, 'confidence': 0.65, 'kind': _field_kind(field),
                'note': '按列名中的关键词识别'}
    # 后缀/前缀启发：率、均、分均、占比、总
    if '占比' in compact:
        field = {'输出': 'damageShare', '伤害': 'damageShare', '经济': 'goldShare',
                 '承伤': 'takenShare'}.get(compact.split('占比')[0].strip(), None)
        if field:
            return {'field': field, 'confidence': 0.8, 'kind': 'metric',
                    'note': '按“占比”识别'}
    if '分均' in compact or '每分钟' in compact:
        field = {'经济': 'gpm', '伤害': 'dpm', '承伤': 'tpm'}.get(compact.replace('分均', '').replace('每分钟', ''), None)
        if field:
            return {'field': field, 'confidence': 0.8, 'kind': 'metric'}
    if '场均' in compact or '平均' in compact:
        field = {'经济': 'avgGold', '伤害': 'avgDamage', '承伤': 'avgTaken'}.get(
            compact.replace('场均', '').replace('平均', ''), None)
        if field:
            return {'field': field, 'confidence': 0.8, 'kind': 'metric'}
    if '率' in compact:
        field = {'胜': 'winRate', '参团': 'participation'}.get(compact.replace('率', ''), None)
        if field:
            return {'field': field, 'confidence': 0.75, 'kind': 'metric'}
    if stats['numbers'] and stats['numbers'] >= stats['count'] * 0.8:
        return {'field': f'extra.{compact or "列"}', 'confidence': 0.2, 'kind': 'metric',
                'note': '未识别数值列，保留为扩展字段'}
    return {'field': f'extra.{compact or "列"}', 'confidence': 0.2, 'kind': 'dimension',
            'note': '未识别列，保留为扩展字段'}


def _column_profiles(sheet):
    result = []
    for index, header in enumerate(sheet['header']):
        values = [row[index] for row in sheet['rows'] if index < len(row)]
        suggestion = suggest_field(header, values)
        stats = profile_values(values)
        kind = suggestion['kind']
        measure_kind, unit = (FIELD_META.get(suggestion['field'], ('raw', 'raw', None, None))[:2]
                              if kind == 'metric' and suggestion['field'] in FIELD_META
                              else (None, None))
        result.append({'index': index, 'header': header, 'field': suggestion['field'],
                       'confidence': suggestion['confidence'], 'kind': kind,
                       'measureKind': measure_kind, 'unit': unit,
                       'valueProfile': stats, 'note': suggestion.get('note')})
    return result


def _detect_wide(columns):
    suffixes = ('击杀', '死亡', '助攻', '经济', '输出', '承伤', '参团率', '评分', '英雄')
    prefixes = Counter()
    for column in columns:
        header = str(column['header'])
        for suffix in suffixes:
            if suffix in header:
                prefix = re.split(suffix, header)[0].strip(' _-')
                if prefix:
                    prefixes[prefix] += 1
    detected = [prefix for prefix, count in prefixes.items() if count >= 3]
    return detected


def infer_grain(columns):
    fields = {column['field'] for column in columns if column.get('field')}
    wide = _detect_wide(columns)
    has_match = bool(fields & {'date', 'matchId', 'matchNo'})
    has_player = bool(fields & {'player', 'playerId'})
    has_hero = 'hero' in fields
    has_team = bool(fields & {'team', 'side'})
    has_kda = bool(fields & {'kills', 'deaths', 'assists', 'kda'})
    has_damage = bool(fields & {'gold', 'damage', 'taken'})
    match_metrics = has_kda or has_damage or bool(fields & {
        'gpm', 'dpm', 'tpm', 'rating', 'duration', 'participation',
        'damageShare', 'goldShare', 'takenShare'})
    aggregate = bool(fields & {'winRate', 'games', 'wins', 'losses', 'avgGold',
                               'avgDamage', 'avgTaken'})
    event = bool(fields & {'event', 'time', 'frame', 'skill', 'x', 'y'})
    scores = {}
    reasons = {}
    if event and len(fields & {'event', 'time', 'frame'}) >= 1:
        scores['event'] = 4 + (1 if fields & {'event', 'time'} else 0)
        reasons['event'] = '存在事件/时间/帧/坐标列'
    if has_match and (has_player or has_hero) and match_metrics:
        scores['match_player'] = 6
        reasons['match_player'] = '存在对局键 + 选手/英雄 + 单局 KDA/经济/伤害'
    if has_match and has_team and (match_metrics or 'win' in fields):
        scores['match_team'] = 5
        reasons['match_team'] = '存在对局键 + 队伍/阵营 + 单局指标'
    if aggregate and has_player:
        scores['aggregate_player'] = 5
        reasons['aggregate_player'] = '存在胜率/场次/场均指标 + 选手'
    if aggregate and has_hero:
        scores['aggregate_hero'] = 4
        reasons['aggregate_hero'] = '存在胜率/场次/场均指标 + 英雄'
    if aggregate and has_team:
        scores['aggregate_team'] = 4
        reasons['aggregate_team'] = '存在胜率/场次/场均指标 + 队伍'
    if wide:
        scores['match_wide'] = 7
        reasons['match_wide'] = f'检测到重复前缀：{", ".join(wide[:5])}'
    if not scores:
        scores['unknown'] = 0
        reasons['unknown'] = '未识别出对局键或统计粒度'
    candidates = [{'grain': grain, 'score': score, 'reason': reasons.get(grain, '')}
                  for grain, score in sorted(scores.items(), key=lambda item: -item[1])]
    return candidates, wide


def rebuild_profile(sheet, base, mapping):
    """Rebuild an inferred profile after a user-specified header -> field mapping."""
    columns = []
    for column in base.get('columns', []):
        header = column['header']
        field = str((mapping or {}).get(header, column.get('field', '')) or '').strip()
        if field in ('', '__ignore__'):
            field = 'extra.' + (compact_name(header) or 'column')
        if field in METRIC_FIELDS:
            kind = 'metric'
        elif field in DIMENSION_FIELDS:
            kind = 'dimension'
        elif field in KEY_FIELDS:
            kind = 'key'
        else:
            kind = 'extra'
        meta = FIELD_META.get(field, ('raw', 'raw', None, None))
        columns.append({'header': header, 'field': field, 'confidence': 1.0, 'kind': kind,
                        'measureKind': meta[0] if kind == 'metric' else None,
                        'unit': meta[1] if kind == 'metric' else None})
    keys, metrics, dimensions = {}, {}, {}
    for column in columns:
        field, header = column['field'], column['header']
        if field in KEY_FIELDS:
            keys.setdefault(field, header)
        elif field in METRIC_FIELDS:
            meta = FIELD_META.get(field, ('raw', 'raw', None, None))
            unit = meta[1]
            if field == 'duration' and ('分钟' in header or 'min' in compact_name(header)):
                unit = 'minutes'
            spec = {'column': header, 'kind': meta[0], 'unit': unit}
            if base.get('grain') in ('match_player', 'match_team') and field in AGGREGATE_ONLY:
                spec['aggregate'] = True
            metrics[field] = spec
        elif field in DIMENSION_FIELDS:
            dimensions[field] = header
    unique = [] if base.get('grain') == 'event' else [
        field for field in keys if field in
        {'date', 'matchId', 'matchNo', 'side', 'team', 'player', 'playerId', 'hero',
         'period', 'session'}]
    profile = {'profileVersion': PROFILE_VERSION, 'sheet': sheet['name'],
               'grain': base.get('grain', 'unknown'), 'keys': keys, 'metrics': metrics,
               'dimensions': dimensions, 'uniqueBy': unique, 'inferred': False,
               'columns': columns}
    if base.get('wide'):
        profile['wide'] = base['wide']
    warnings = []
    if not metrics and profile['grain'] != 'match_wide':
        warnings.append('没有识别到指标列。')
    if profile['grain'] == 'unknown':
        warnings.append('未识别统计粒度，请检查列映射。')
    if profile['grain'] == 'match_wide':
        warnings.append('宽表需要补充 wide.players 映射后才能拆成一行一名队员。')
    profile['warnings'] = warnings
    profile['unmappedColumns'] = [column['header'] for column in columns
                                  if column['field'] not in keys
                                  and column['field'] not in metrics
                                  and column['field'] not in dimensions]
    return profile


def infer_profile(sheet):
    columns = _column_profiles(sheet)
    fields = {column['field'] for column in columns}
    # 单局表里的“场次”更可能是场次号；跨局表里的“场次”才是场次数。
    if fields & {'date', 'matchId', 'matchNo'} and fields & {'player', 'playerId', 'hero', 'team'}:
        for column in columns:
            if column['field'] == 'games' and compact_name(column['header']) == '场次':
                column['field'], column['kind'], column['confidence'] = 'matchNo', 'key', 0.5
                column['note'] = '单局表中的“场次”按场次号处理'
    candidates, wide = infer_grain(columns)
    grain = candidates[0]['grain'] if candidates else 'unknown'
    used = set()

    def wide_column(column):
        return grain == 'match_wide' and any(prefix in str(column['header']) for prefix in wide)

    keys = {}
    preferred = {
        'match_player': ['date', 'matchId', 'matchNo', 'session', 'opponent', 'team',
                         'side', 'ownSide', 'position', 'player', 'playerId', 'hero'],
        'match_team': ['date', 'matchId', 'matchNo', 'session', 'opponent', 'team', 'side'],
        'event': ['date', 'matchId', 'session', 'opponent', 'time', 'frame', 'event',
                  'player', 'hero', 'skill'],
        'aggregate_player': ['period', 'session', 'date', 'team', 'position', 'player',
                             'playerId', 'hero'],
        'aggregate_team': ['period', 'session', 'date', 'team'],
        'aggregate_hero': ['period', 'session', 'date', 'hero'],
        'match_wide': ['date', 'matchId', 'matchNo', 'session', 'opponent'],
    }.get(grain, [])
    for field in preferred:
        matches = [column for column in columns if column['field'] == field
                   and column['index'] not in used and not wide_column(column)]
        if matches:
            best = max(matches, key=lambda column: column['confidence'])
            keys[field] = best['header']
            used.add(best['index'])
    metrics = {}
    for column in columns:
        if column['index'] in used or column['kind'] != 'metric' or wide_column(column):
            continue
        if column['field'] not in METRIC_FIELDS:
            continue
        meta = FIELD_META.get(column['field'], ('raw', 'raw', None, None))
        unit = meta[1]
        if column['field'] == 'duration' and ('分钟' in column['header'] or 'min' in compact_name(column['header'])):
            unit = 'minutes'
        spec = {'column': column['header'], 'kind': meta[0], 'unit': unit}
        if grain in ('match_player', 'match_team') and column['field'] in AGGREGATE_ONLY:
            spec['aggregate'] = True
        metrics[column['field']] = spec
        used.add(column['index'])
    dimensions = {}
    for column in columns:
        if column['index'] in used or column['kind'] != 'dimension' or wide_column(column):
            continue
        if column['field'] in DIMENSION_FIELDS:
            dimensions[column['field']] = column['header']
            used.add(column['index'])
    if grain == 'event':
        unique = []
    else:
        unique = [field for field in keys if field in
                  {'date', 'matchId', 'matchNo', 'side', 'team', 'player', 'playerId', 'hero',
                   'period', 'session'}]
    profile = {'profileVersion': PROFILE_VERSION, 'sheet': sheet['name'], 'grain': grain,
               'keys': keys, 'metrics': metrics, 'dimensions': dimensions,
               'uniqueBy': unique, 'inferred': True}
    aggregate_metrics = [field for field, spec in metrics.items() if spec.get('aggregate')]
    if aggregate_metrics:
        profile['warnings'] = [f'单局表中出现跨局聚合列：{", ".join(aggregate_metrics)}；'
                               f'已标 aggregate=true，不要按单局累加。']
    if grain == 'match_wide':
        profile['wide'] = {'detectedPrefixes': wide, 'players': []}
    warnings = []
    if grain == 'unknown':
        warnings.append('未识别统计粒度，请手工指定 grain 和列映射。')
    if grain == 'match_wide':
        warnings.append('宽表需要补充 wide.players 映射后才能拆成一行一名队员。')
    low = [column['header'] for column in columns if column['confidence'] < 0.6]
    if low:
        warnings.append(f'以下列未高置信识别：{", ".join(low[:8])}')
    if not metrics and grain != 'match_wide':
        warnings.append('没有识别到指标列。')
    warnings = profile.pop('warnings', []) + warnings
    profile['warnings'] = warnings
    profile['columns'] = [{key: column[key] for key in ('header', 'field', 'confidence',
                                                        'kind', 'measureKind', 'unit')}
                          for column in columns]
    profile['unmappedColumns'] = [column['header'] for column in columns
                                  if column['field'] not in set(profile['keys'])
                                  and column['field'] not in metrics
                                  and column['field'] not in dimensions]
    return profile


def _lookup(sheet, name):
    text = str(name or '').strip()
    for index, header in enumerate(sheet['header']):
        if str(header).strip() == text:
            return index
    target = compact_name(text)
    matches = [index for index, header in enumerate(sheet['header']) if compact_name(header) == target]
    if len(matches) == 1:
        return matches[0]
    raise SheetImportError(f'找不到列：{name}')


def _parse_kda(value):
    text = str(value).strip()
    match = re.fullmatch(r'(\d{1,3})\s*/\s*(\d{1,3})\s*/\s*(\d{1,3})', text)
    if not match:
        return None
    return [int(match.group(1)), int(match.group(2)), int(match.group(3))]


def _parse_duration(value, unit):
    if isinstance(value, (int, float)):
        if unit == 'minutes':
            return value * 60
        return value
    text = str(value).strip()
    match = re.fullmatch(r'(\d{1,3})\s*[:：]\s*(\d{2})', text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    number = _number(text)
    if number is None:
        return None
    return number * 60 if unit == 'minutes' else number


def parse_measure(field, value, spec=None):
    spec = spec or {}
    kind, unit, low, high = FIELD_META.get(field, ('raw', 'raw', None, None))
    kind = spec.get('kind', kind)
    unit = spec.get('unit', unit)
    result = {'raw': _json_value(value), 'kind': kind, 'unit': unit, 'valid': True}
    if value in (None, ''):
        result['value'] = None
        result['missing'] = True
        return result
    if field == 'kda':
        parsed = _parse_kda(value)
        if parsed is not None:
            result['value'] = parsed
            result['valid'] = all(0 <= item <= 500 for item in parsed)
            return result
    if field == 'win':
        outcome = _win_loss(value)
        result['value'] = outcome
        result['valid'] = outcome is not None
        if outcome is None:
            result['note'] = '无法识别胜负'
        return result
    if kind == 'percentage':
        text = str(value).strip()
        has_percent = '%' in text
        number = _number(text.replace('%', '').strip())
        if number is None:
            result['valid'] = False
            result['note'] = '百分比无法解析'
            return result
        if not has_percent and number <= 1 and spec.get('scale') != 'percent':
            number *= 100
            result['sourceScale'] = 'ratio'
        if isinstance(number, float) and number.is_integer():
            number = int(number)
        result['value'] = number
        result['valid'] = 0 <= number <= 100
        if not result['valid']:
            result['note'] = '百分比超出 0–100'
        return result
    if field == 'duration':
        number = _parse_duration(value, spec.get('unit'))
        result['value'] = number
        result['valid'] = number is not None and (high is None or number <= high)
        if number is None:
            result['note'] = '时长无法解析'
        elif number > 7200:
            result['note'] = '时长超出 7200 秒'
        return result
    number = _number(value)
    result['value'] = number
    if number is None:
        result['valid'] = False
        result['note'] = '数值无法解析'
    elif low is not None and number < low or high is not None and number > high:
        result['valid'] = False
        result['note'] = f'超出范围 {low}–{high}'
    return result


def _normalize_key(field, value):
    if value in (None, ''):
        return None
    if field == 'date':
        return _date_value(value) or str(value).strip()
    if field in ('side', 'ownSide'):
        text = compact_name(value)
        if text in ('蓝', '蓝方', '蓝色', 'blue', 'b', '1'):
            return 'blue'
        if text in ('红', '红方', '红色', 'red', 'r', '2'):
            return 'red'
        return str(value).strip()
    if field == 'win':
        return _win_loss(value)
    if field in ('time',):
        return _parse_duration(value, 'seconds')
    if field == 'frame':
        number = _number(value)
        return int(number) if number is not None else str(value).strip()
    return unicodedata.normalize('NFKC', str(value)).strip()


def _row_signature(keys, unique):
    values = [keys.get(field) for field in unique]
    if all(value in (None, '') for value in values):
        return None
    return tuple(str(value) if value is not None else '' for value in values)


def apply_profile(sheet, profile):
    if profile.get('profileVersion', PROFILE_VERSION) != PROFILE_VERSION:
        raise SheetImportError('不支持的 profileVersion')
    grain = profile.get('grain')
    if grain not in GRAINS:
        raise SheetImportError(f'不支持的 grain：{grain}')
    keys_map = profile.get('keys') or {}
    metrics_map = profile.get('metrics') or {}
    dimensions_map = profile.get('dimensions') or {}
    if not isinstance(keys_map, dict) or not isinstance(metrics_map, dict):
        raise SheetImportError('profile 的 keys/metrics 必须是对象')
    for name in list(keys_map.values()) + list(dimensions_map.values()):
        _lookup(sheet, name)
    for spec in metrics_map.values():
        column = spec.get('column') if isinstance(spec, dict) else spec
        _lookup(sheet, column)
    wide_players = []
    if grain == 'match_wide':
        wide_players = profile.get('wide', {}).get('players') or []
        if not wide_players:
            raise SheetImportError('match_wide 需要在 profile.wide.players 中提供队员列映射')
        for player in wide_players:
            for name in (player.get('columns') or {}).values():
                _lookup(sheet, name)
    rows, quality = [], {'rows': 0, 'missingKeys': 0, 'duplicates': 0,
                         'invalidMetrics': 0, 'unmappedColumns': len(profile.get('unmappedColumns') or [])}
    warnings = []
    seen = set()
    unique = profile.get('uniqueBy') or [field for field in keys_map
                                         if field in {'date', 'matchId', 'matchNo', 'side', 'team',
                                                      'player', 'playerId', 'hero', 'period', 'session'}]
    for row_index, row in enumerate(sheet['rows'], start=2):
        raw = {header: _json_value(row[index]) if index < len(row) else None
               for index, header in enumerate(sheet['header'])}
        if grain == 'match_wide':
            base_keys = {field: _normalize_key(field, row[_lookup(sheet, column)])
                         for field, column in keys_map.items()}
            base_dimensions = {field: _normalize_key(field, row[_lookup(sheet, column)])
                               for field, column in dimensions_map.items()}
            for player_index, player in enumerate(wide_players):
                player_keys = dict(base_keys)
                player_keys['side'] = player.get('side')
                player_keys['slot'] = player.get('slot')
                player_metrics = {}
                for field, column in (player.get('columns') or {}).items():
                    value = row[_lookup(sheet, column)]
                    if field in KEY_FIELDS:
                        player_keys[field] = _normalize_key(field, value)
                    else:
                        parsed = parse_measure(field, value,
                                               {'kind': FIELD_META.get(field, ('raw',))[0]})
                        player_metrics[field] = parsed
                        if not parsed['valid']:
                            quality['invalidMetrics'] += 1
                merged_raw = dict(raw)
                merged_raw['_playerSlot'] = player.get('slot')
                rows.append({'rowNumber': row_index, 'playerIndex': player_index, 'grain': grain,
                             'aggregated': False, 'raw': merged_raw, 'keys': player_keys,
                             'dimensions': dict(base_dimensions), 'metrics': player_metrics})
                quality['rows'] += 1
            continue
        keys = {field: _normalize_key(field, row[_lookup(sheet, column)])
                for field, column in keys_map.items()}
        dimensions = {field: _normalize_key(field, row[_lookup(sheet, column)])
                      for field, column in dimensions_map.items()}
        metrics = {}
        for field, spec in metrics_map.items():
            column = spec.get('column') if isinstance(spec, dict) else spec
            parsed = parse_measure(field, row[_lookup(sheet, column)], spec if isinstance(spec, dict) else None)
            metrics[field] = parsed
            if not parsed['valid']:
                quality['invalidMetrics'] += 1
        if any(value in (None, '') for value in keys.values()):
            quality['missingKeys'] += 1
        signature = _row_signature(keys, unique)
        duplicate = signature is not None and signature in seen
        if duplicate:
            quality['duplicates'] += 1
        elif signature is not None:
            seen.add(signature)
        rows.append({'rowNumber': row_index, 'grain': grain,
                     'aggregated': grain in AGGREGATE_GRAINS,
                     'raw': raw, 'keys': keys, 'dimensions': dimensions,
                     'metrics': metrics, 'duplicate': duplicate})
        quality['rows'] += 1
    required = {
        'match_player': (('player', 'hero'), ('date', 'matchId', 'matchNo')),
        'match_team': (('team', 'side'), ('date', 'matchId', 'matchNo')),
        'event': (('event',), ('time', 'frame')),
        'aggregate_player': (('player', 'hero'), ()),
        'aggregate_team': (('team',), ()),
        'aggregate_hero': (('hero',), ()),
    }.get(grain, ((), ()))
    for group in required:
        if group and not any(field in keys_map for field in group):
            warnings.append(f'{grain} 缺少必需键：{" / ".join(group)}')
    if quality['missingKeys']:
        warnings.append(f'{quality["missingKeys"]} 行存在空键。')
    if quality['duplicates']:
        warnings.append(f'{quality["duplicates"]} 行键值重复；未自动去重。')
    if quality['invalidMetrics']:
        warnings.append(f'{quality["invalidMetrics"]} 个指标超出范围或无法解析。')
    if grain in AGGREGATE_GRAINS:
        warnings.append('这是跨局聚合表；不要把这些行再按单局相加。')
    return {'rows': rows, 'quality': quality, 'warnings': warnings}


def _read_csv(path):
    data = path.read_bytes()
    text = None
    for encoding in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SheetImportError('CSV 编码无法识别（尝试 UTF-8/GB18030/UTF-16）')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',\t;')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = []
    for row in reader:
        rows.append([cell for cell in row])
        if len(rows) > MAX_ROWS + 50:
            raise SheetImportError(f'CSV 行数超过 {MAX_ROWS}')
    return rows


def _read_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise SheetImportError('读取 XLSX 需要 openpyxl；请运行 安装依赖.bat') from error
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheets = []
    try:
        for worksheet in workbook.worksheets:
            rows = []
            for row in worksheet.iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) > MAX_ROWS + 50:
                    raise SheetImportError(f'{worksheet.title} 行数超过 {MAX_ROWS}')
            sheets.append((worksheet.title, rows))
    finally:
        workbook.close()
    return sheets


def _build_sheet(name, raw_rows, warnings):
    rows = [[None if cell == '' else cell for cell in row] for row in raw_rows]
    while rows and all(cell in (None, '') for cell in rows[0]):
        rows.pop(0)
    if not rows:
        raise SheetImportError(f'{name} 没有表头或数据')
    width = max(len(row) for row in rows)
    header = []
    counts = Counter()
    for index in range(width):
        value = rows[0][index] if index < len(rows[0]) else None
        text = str(value).strip() if value not in (None, '') else f'列{index + 1}'
        counts[text] += 1
        header.append(text if counts[text] == 1 else f'{text} ({counts[text]})')
    if counts and any(count > 1 for count in counts.values()):
        warnings.append(f'{name}: 表头有重名，已加序号区分')
    body = []
    for row in rows[1:]:
        if all(cell in (None, '') for cell in row):
            continue
        body.append(row + [None] * (width - len(row)))
    if len(body) > MAX_ROWS:
        raise SheetImportError(f'{name} 行数超过 {MAX_ROWS}')
    return {'name': name, 'header': header, 'rows': body, 'warnings': warnings}


def read_workbook(path):
    path = Path(path)
    if not path.is_file():
        raise SheetImportError('文件不存在')
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise SheetImportError(f'文件超过 {MAX_BYTES // 1024 // 1024} MB 上限')
    suffix = path.suffix.lower()
    warnings = []
    if suffix in ('.csv', '.tsv', '.txt'):
        raw = _read_csv(path)
        sheets = [('CSV', raw)]
    elif suffix in ('.xlsx', '.xlsm'):
        sheets = _read_xlsx(path)
    elif suffix == '.xls':
        raise SheetImportError('旧版 .xls 请先另存为 .xlsx 或 CSV')
    else:
        raise SheetImportError('仅支持 CSV/TSV/XLSX/XLSM')
    result = []
    for name, rows in sheets:
        result.append(_build_sheet(name, rows, list(warnings)))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'source': {'name': path.name, 'size': size, 'sha256': digest,
                       'format': suffix.lstrip('.')}, 'sheets': result}


def _slug(name):
    value = re.sub(r'[^\w\u4e00-\u9fff-]+', '_', str(name)).strip('_')
    return value[:40] or 'sheet'


def write_staging(source, sheets, profiles, out_dir, profile_source='provided'):
    out = Path(out_dir)
    rows_dir = out / 'rows'
    rows_dir.mkdir(parents=True, exist_ok=True)
    manifest_sheets = []
    total_quality = {'rows': 0, 'missingKeys': 0, 'duplicates': 0, 'invalidMetrics': 0}
    warnings = []
    for index, sheet in enumerate(sheets):
        profile = profiles.get(sheet['name'])
        if not profile:
            raise SheetImportError(f'缺少工作表 {sheet["name"]} 的 profile')
        applied = apply_profile(sheet, profile)
        rows_file = rows_dir / f'{index + 1:02d}-{_slug(sheet["name"])}.jsonl'
        with rows_file.open('w', encoding='utf-8') as handle:
            for row in applied['rows']:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        manifest_sheets.append({
            'name': sheet['name'], 'grain': profile.get('grain'),
            'aggregated': profile.get('grain') in AGGREGATE_GRAINS,
            'rowCount': len(applied['rows']),
            'keys': profile.get('keys', {}),
            'metrics': list((profile.get('metrics') or {}).keys()),
            'dimensions': list((profile.get('dimensions') or {}).keys()),
            'unmappedColumns': profile.get('unmappedColumns', []),
            'ownSide': profile.get('ownSide') or '',
            'rowsFile': str(rows_file.relative_to(out)).replace('\\', '/'),
            'quality': applied['quality'],
        })
        for key in total_quality:
            total_quality[key] += applied['quality'].get(key, 0)
        warnings += [f'{sheet["name"]}: {warning}' for warning in applied['warnings']]
    manifest = {
        'schema': SCHEMA,
        'createdAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': source,
        'profileSource': profile_source,
        'sheets': manifest_sheets,
        'profile': profiles,
        'quality': total_quality,
        'warnings': list(dict.fromkeys(warnings)),
    }
    (out / 'profile.json').write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def load_profiles(path, sheets):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise SheetImportError('profile 必须是 JSON 对象')
    if 'sheets' in value:
        profiles = value['sheets']
    elif value.get('sheet'):
        profiles = {value['sheet']: value}
    elif len(sheets) == 1:
        profiles = {sheets[0]['name']: value}
    else:
        raise SheetImportError('profile 没有 sheet 字段，且工作簿有多个工作表；请分别指定')
    if not isinstance(profiles, dict):
        raise SheetImportError('profile.sheets 必须是对象')
    return profiles


def render_preview(workbook):
    lines = [f"文件：{workbook['source']['name']}  {workbook['source']['size']} 字节  "
             f"sha256 {workbook['source']['sha256'][:16]}"]
    for sheet in workbook['sheets']:
        profile = infer_profile(sheet)
        lines.append(f"\n[{sheet['name']}] {len(sheet['rows'])} 行 × {len(sheet['header'])} 列  "
                     f"推断粒度：{profile['grain']}")
        if profile.get('keys'):
            lines.append('  键：' + '  '.join(f'{key}={value}' for key, value in profile['keys'].items()))
        if profile.get('metrics'):
            lines.append('  指标：' + '  '.join(
                f"{key}={spec.get('column')}({spec.get('kind')})"
                for key, spec in profile['metrics'].items()))
        if profile.get('dimensions'):
            lines.append('  维度：' + '  '.join(f'{key}={value}' for key, value in profile['dimensions'].items()))
        if profile.get('unmappedColumns'):
            lines.append('  未映射列：' + '、'.join(profile['unmappedColumns'][:10]))
        for warning in profile.get('warnings', []):
            lines.append(f'  注意：{warning}')
    return '\n'.join(lines)
