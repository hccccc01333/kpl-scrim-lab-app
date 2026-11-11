"""OCR for the current tabbed Honor of Kings post-game screenshot.

The old two-column screenshots are handled by :mod:`ocr`.  This module is for
the newer post-game UI with the bottom tabs 战绩 / 数据 / 输出 / 生存 / 发育 /
团队.  It only emits fields declared in :mod:`screenshot_schema`; uncertain
hero names stay candidates and are never silently accepted.
"""
import io
import re

import numpy as np
from PIL import Image, ImageOps

import ocr
from hero_names import resolve_name
from screenshot_schema import (FIELD_UNITS, PAGE_ORDER, PLAYER_LABELS, SCHEMA,
                               SHARE_FIELDS, TABS)
from vision import catalog, prepare_image

OCR_VERSION = 'postgame-tabbed-v3'
DATE_RE = re.compile(r'20\d{2}/\d{1,2}/\d{1,2}')
TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
RATING_RE = re.compile(r'^\d{1,2}\.\d$')
KDA_RE = re.compile(r'^(\d{1,3})/(\d{1,3})/(\d{1,3})$')
TITLE_RE = re.compile(r'(?:金牌|银牌|铜牌)(?:对抗路|打野|中路|发育路|游走)')
INT_RE = re.compile(r'^\d{1,3}$')
GOLD_TOKEN_RE = re.compile(r'^\d{3,6}$')
BIG_RE = re.compile(r'^(\d{1,6}(?:\.\d+)?)([kK万])?$')
RATIO_RE = re.compile(r'^(?:\d+(?:\.\d+)?|\.\d+)$')
PERCENT_RE = re.compile(r'^(\d{1,3}(?:\.\d+)?)%$')

# Value and share rows are consistently offset from the large rating number.
# Offsets are fractions of the prepared image height.
PROFILE_COLUMNS = {
    'kda': [
        {'field': 'kills', 'header': '击败', 'kind': 'int', 'share': 'killsShare',
         'value_dy': -.015, 'share_dy': .025, 'value_dx': -.02, 'share_dx': .06},
        {'field': 'deaths', 'header': '死亡', 'kind': 'int', 'share': 'deathsShare',
         'value_dy': -.015, 'share_dy': .025, 'value_dx': -.02, 'share_dx': .06},
        {'field': 'assists', 'header': '助攻', 'kind': 'int', 'share': 'assistsShare',
         'value_dy': -.015, 'share_dy': .025, 'value_dx': -.02, 'share_dx': .06},
    ],
    'data': [
        {'field': 'damageDealt', 'header': '输出伤害', 'kind': 'big', 'share': 'outputShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .03},
        {'field': 'damageTaken', 'header': '承受伤害', 'kind': 'big', 'share': 'takenShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .03},
        {'field': 'gold', 'header': '总经济', 'kind': 'big', 'share': 'goldShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .03},
        {'field': 'participation', 'header': '参团率', 'kind': 'percent', 'share': None,
         'value_dy': .021, 'share_dy': None, 'value_dx': .03},
    ],
    'output': [
        {'field': 'damageDealt', 'header': '输出伤害', 'kind': 'big', 'share': 'outputShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .093},
        {'field': 'damageConversion', 'header': '伤害转化比', 'kind': 'ratio', 'share': None,
         'value_dy': -.014, 'share_dy': None, 'value_dx': -.01},
    ],
    'survival': [
        {'field': 'damageTaken', 'header': '承受伤害', 'kind': 'big', 'share': 'takenShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .095},
        {'field': 'takenPerDeath', 'header': '每死承伤', 'kind': 'big', 'share': None,
         'value_dy': -.014, 'share_dy': None, 'value_dx': -.01},
    ],
    'farming': [
        {'field': 'gold', 'header': '总经济', 'kind': 'big', 'share': 'goldShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .054},
        {'field': 'jungleGold', 'header': '野怪经济', 'kind': 'big', 'share': 'jungleShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .054},
        {'field': 'cs', 'header': '补刀数', 'kind': 'int', 'share': 'csShare',
         'value_dy': -.014, 'share_dy': .021, 'value_dx': -.01, 'share_dx': .054},
    ],
    'team': [
        {'field': 'participation', 'header': '参团率', 'kind': 'percent', 'share': None,
         'value_dy': .025, 'share_dy': None, 'value_dx': .03},
        {'field': 'control', 'header': '控制效果', 'kind': 'int', 'share': 'controlShare',
         'value_dy': -.014, 'share_dy': .025, 'value_dx': -.012, 'share_dx': .03},
        {'field': 'healing', 'header': '治疗量', 'kind': 'big', 'share': 'healingShare',
         'value_dy': -.014, 'share_dy': .025, 'value_dx': -.012, 'share_dx': .03},
        {'field': 'towerDamage', 'header': '对塔伤害', 'kind': 'big', 'share': 'towerShare',
         'value_dy': -.014, 'share_dy': .025, 'value_dx': -.012, 'share_dx': .03},
    ],
}

PAGE_ORDER_INDEX = {page: index for index, page in enumerate(PAGE_ORDER)}


def recognize(data, name=None, include_tokens=False, engine='rapid', on_stage=None,
              mimo_mode='columns'):
    """Recognize one tabbed post-game screenshot.

    ``data`` is raw image bytes.  The returned dictionary is a candidate
    extraction, not a confirmed match record.  ``engine='mimo'`` runs the fast
    layout pass first, then refines the page with the local Xiaomi-OCR-0 model;
    the default stays fast so uploads and tests do not block for minutes.
    """
    image, crop = prepare_image(data)
    source_image = None
    try:
        original = Image.open(io.BytesIO(data)).convert('RGB')
        source_image = original.crop((0, crop.get('top', 0), original.width, crop.get('bottom', original.height)))
    except (OSError, ValueError):
        source_image = None
    width, height = image.size
    tokens = _normalize_tokens(ocr.detect_tokens(image), width, height)
    warnings = []
    page = classify_page(tokens)
    match = read_match(tokens, image, warnings)
    rows = find_rows(tokens, warnings)
    column_readings = _column_readings(image, source_image, rows)
    players = []
    for side in ('left', 'right'):
        for slot, row in enumerate(rows.get(side) or []):
            players.append(read_player(image, tokens, row, side, slot, page, warnings, source_image,
                                       column_readings.get((side, slot)) or []))
    if page == 'unknown':
        warnings.append('未识别分页布局；保留原始 token，未写入任何字段。')
    if len(players) != 10:
        warnings.append(f'识别到 {len(players)} 个选手行，正常赛后页应为 10 行。')
    if match.get('score') and page in ('data', 'output', 'survival', 'farming'):
        warnings.append('该页提供比分，但日期、时长和胜负只在战绩页；不能单独归档。')
    if page == 'kda' and not match.get('date'):
        warnings.append('该战绩页没有日期/时长，需与同一局战绩页或赛训表关联。')
    if page == 'score':
        warnings.append('新版战绩页装备图标未纳入 v1；装备名称需人工核对。')
    _validate_scores(match, players, page, warnings)
    coverage = _coverage(players)
    quality = image_quality(image, raw=data)
    for warning in quality.get('warnings') or []:
        warnings.append(f'采集质量：{warning}')
    output = {
        'schema': SCHEMA,
        'version': OCR_VERSION,
        'layout': OCR_VERSION,
        'file': name,
        'pageType': page,
        'tab': TABS.get(page),
        'match': match,
        'players': players,
        'coverage': coverage,
        'quality': quality,
        'warnings': _dedupe(warnings),
        'crop': crop,
        'imageSize': [width, height],
        'engine': {'layout': 'rapidocr-onnxruntime', 'mode': 'rapid'},
    }
    if include_tokens:
        output['tokens'] = tokens
    if engine in ('mimo', 'hybrid'):
        from postgame_mimo import refine
        output = refine(data, output, name=name, on_stage=on_stage, mode=mimo_mode)
    return output


JPEG_BASE_75 = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55]


def _estimate_jpeg_quality(raw):
    """从亮度量化表估算 JPEG 有效画质（0-100）；非 JPEG 或表缺失返回 None。

    依据 IJG 约定反推：q=100-50×(当前表/基准表)（低频段均值）。聊天工具转发
    非原图通常按 70-80 再压缩，实测估算误差 ±0.2。
    """
    try:
        image = Image.open(io.BytesIO(raw))
    except Exception:
        return None
    if (image.format or '').upper() != 'JPEG':
        return None
    try:
        luma = (image.quantization or {}).get(0)
    except Exception:
        return None
    if not luma or len(luma) < len(JPEG_BASE_75):
        return None
    ratio = (sum(int(v) for v in luma[:len(JPEG_BASE_75)]) / len(JPEG_BASE_75)
             / (sum(JPEG_BASE_75) / len(JPEG_BASE_75)))
    if ratio <= 0:
        return None
    return round(max(1.0, min(100.0, 100 - 50 * ratio)), 1)


def image_quality(image, raw=None):
    """Non-blocking capture checks.  They never reject a screenshot."""
    width, height = image.size
    pixels = np.asarray(image.convert('L'), dtype=np.float32)
    lap = (-4 * pixels + np.roll(pixels, 1, 0) + np.roll(pixels, -1, 0)
           + np.roll(pixels, 1, 1) + np.roll(pixels, -1, 1))
    blur = float(lap[1:-1, 1:-1].var()) if width > 2 and height > 2 else 0.0
    warnings = []
    if width < 1280:
        warnings.append(f'宽度 {width}px 低于建议的 1280px，小字可能读不出。')
    if height < 600:
        warnings.append(f'高度 {height}px 偏低，建议保留完整页头和表格。')
    if blur < 60:
        warnings.append(f'画面清晰度偏低（清晰度 {blur:.0f}），建议重新截图。')
    ratio = width / height if height else 0
    if not 1.2 <= ratio <= 3.4:
        warnings.append(f'宽高比 {ratio:.2f} 非常规，可能被裁切；请确认列头完整。')
    jpeg_quality = _estimate_jpeg_quality(raw) if raw else None
    if jpeg_quality is not None and jpeg_quality < 82:
        warnings.append(f'这张图疑似经微信/QQ 等聊天软件压缩（估算画质 {jpeg_quality:.0f}），'
                        '小字识别容易出错；建议手机端勾选「原图」或用文件方式重传。')
    return {'width': width, 'height': height, 'blur': round(blur, 1),
            'aspect': round(ratio, 3), 'jpegQuality': jpeg_quality,
            'warnings': warnings}


def _normalize_tokens(raw, width, height):
    tokens = []
    for box, text, confidence in raw:
        tokens.append({
            'text': str(text).strip(),
            'confidence': float(confidence),
            'box': [[round(float(x) / width, 5), round(float(y) / height, 5)] for x, y in box],
        })
    return tokens


def _center(token):
    box = token['box']
    return (sum(point[0] for point in box) / 4, sum(point[1] for point in box) / 4)


def _x(token):
    return _center(token)[0]


def _y(token):
    return _center(token)[1]


def _text(token):
    return token.get('text') or ''


def _compact(text):
    return re.sub(r'\s+', '', str(text or ''))


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _has(tokens, label):
    return any(label in _text(token) for token in tokens)


def classify_page(tokens):
    if _has(tokens, '控制效果') and _has(tokens, '治疗量') and _has(tokens, '对塔伤害'):
        return 'team'
    if _has(tokens, '每死承伤'):
        return 'survival'
    if _has(tokens, '野怪经济') or _has(tokens, '补刀数'):
        return 'farming'
    if _has(tokens, '伤害转化比'):
        return 'output'
    if _has(tokens, '击败') and _has(tokens, '死亡') and _has(tokens, '助攻'):
        return 'kda'
    if all(_has(tokens, label) for label in ('输出伤害', '承受伤害', '总经济', '参团率')):
        return 'data'
    if _has(tokens, '胜利') or _has(tokens, '失败'):
        return 'score'
    if any(KDA_RE.match(_compact(_text(token))) for token in tokens):
        return 'score'
    return 'unknown'


def read_match(tokens, image, warnings):
    match = {'date': None, 'time': None, 'durationSec': None, 'mode': None,
             'result': None, 'score': {'left': None, 'right': None}}
    date_token = None
    for token in tokens:
        text = _compact(_text(token))
        found = DATE_RE.search(text)
        if not found or _y(token) > .2:
            continue
        date_token = token
        values = re.findall(r'\d+', found.group(0))
        match['date'] = '-'.join([values[0], values[1].zfill(2), values[2].zfill(2)])
        before = text[:found.start()]
        after = text[found.end():]
        durations = re.findall(r'(\d{1,2}):(\d{2})', before)
        if durations:
            minutes, seconds = durations[-1]
            match['durationSec'] = int(minutes) * 60 + int(seconds)
        mode = re.sub(r'\d{1,2}:\d{2}', '', before).strip()
        mode = mode.replace('胜利', '').replace('失败', '').strip()
        if mode and '未开始匹配' not in mode:
            match['mode'] = mode
        clock = re.search(r'(\d{1,2}):(\d{2})', after)
        if clock:
            match['time'] = f'{int(clock.group(1)):02d}:{clock.group(2)}'
        break
    if date_token and match['durationSec'] is None:
        for token in tokens:
            if _y(token) < .12 and _x(token) < _x(date_token) and TIME_RE.match(_text(token)):
                hours, minutes = _text(token).split(':')
                match['durationSec'] = int(hours) * 60 + int(minutes)
                break
    if date_token and match['time'] is None:
        for token in tokens:
            if _y(token) < .12 and _x(token) > _x(date_token) and TIME_RE.match(_text(token)):
                hours, minutes = _text(token).split(':')
                match['time'] = f'{int(hours):02d}:{minutes}'
                break
    if not match['mode']:
        for token in tokens:
            text = _compact(_text(token))
            if _y(token) < .12 and any(word in text for word in ('排位', '巅峰', '训练', '大乱斗', '快速')):
                if '未开始匹配' not in text:
                    match['mode'] = text
                    break
    for token in tokens:
        text = _compact(_text(token))
        if _y(token) < .15 and text in ('胜利', '失败'):
            match['result'] = 'win' if text == '胜利' else 'loss'
            break
    scores = _read_scores(tokens, image)
    match['score'] = scores
    return match


def _read_scores(tokens, image):
    candidates = []
    for token in tokens:
        text = _compact(_text(token))
        if _y(token) < .1 and .3 < _x(token) < .7 and INT_RE.match(text):
            value = int(text)
            if 0 <= value <= 200:
                candidates.append(token)
    scores = {'left': None, 'right': None}
    for side, target in (('left', .42), ('right', .58)):
        found = [token for token in candidates if (side == 'left') == (_x(token) < .5)]
        if found:
            best = min(found, key=lambda token: abs(_x(token) - target))
            if abs(_x(best) - target) < .09:
                scores[side] = int(_compact(_text(best)))
    if scores['left'] is None:
        value = _read_cell_value(image, .41, .03, kind='int', width=.06, height=.07)
        if value is not None:
            scores['left'] = value
    if scores['right'] is None:
        value = _read_cell_value(image, .585, .03, kind='int', width=.06, height=.07)
        if value is not None:
            scores['right'] = value
    if scores['left'] is not None and scores['right'] is not None and scores['left'] == scores['right']:
        # Equal scores are legitimate; no warning needed.
        pass
    return scores


def find_rows(tokens, warnings):
    result = {}
    for side, band in (('left', (.09, .22)), ('right', (.55, .70))):
        items = [token for token in tokens
                 if RATING_RE.match(_compact(_text(token)))
                 and band[0] <= _x(token) <= band[1] and .1 <= _y(token) <= .98]
        clusters = []
        for token in sorted(items, key=_y):
            if clusters and abs(_y(token) - _y(clusters[-1][-1])) <= .018:
                clusters[-1].append(token)
            else:
                clusters.append([token])
        rows = []
        for cluster in clusters:
            best = max(cluster, key=lambda token: token['confidence'])
            rows.append({'side': side, 'rating': float(_compact(_text(best))),
                         'y': _y(best), 'token': best})
        rows.sort(key=lambda row: row['y'])
        if len(rows) != 5:
            warnings.append(f'{side} 侧识别到 {len(rows)} 个评分行（应为 5 行）；缺失行不补猜。')
        if len(rows) > 5:
            rows = rows[:5]
        gaps = [rows[i + 1]['y'] - rows[i]['y'] for i in range(len(rows) - 1)]
        gap = sorted(gaps)[len(gaps) // 2] if gaps else .12
        for index, row in enumerate(rows):
            row['slot'] = index
            row['top'] = row['y'] - gap / 2
            row['bottom'] = row['y'] + gap / 2
        result[side] = rows
    return result


def read_player(image, tokens, row, side, slot, page, warnings, source_image=None, column_hero_readings=None):
    row_tokens = _row_tokens(tokens, row, side)
    nickname = _read_nickname(row_tokens, row, side)
    hero, hero_status, hero_candidates, readings = _read_hero(image, row_tokens, row, side, source_image, column_hero_readings)
    title = _read_title(row_tokens)
    mvp = any(_compact(_text(token)) == 'MVP' for token in row_tokens)
    rating_token = row['token']
    player = {
        'side': side,
        'slot': slot,
        'nickname': nickname,
        'hero': hero,
        'heroStatus': hero_status,
        'heroCandidates': hero_candidates,
        'heroReadings': readings,
        'rating': _field(rating_token, float(_compact(_text(rating_token)))),
        'title': title,
        'mvp': mvp,
        'fields': {},
        'shares': {},
        'sources': [page],
    }
    if page == 'score':
        fields = _read_score_fields(image, row_tokens, row)
        player['fields'].update(fields)
    elif page in PROFILE_COLUMNS:
        fields, shares = _read_columns(image, row_tokens, tokens, row, side, page)
        player['fields'].update(fields)
        player['shares'].update(shares)
    return player


def _row_tokens(tokens, row, side):
    items = []
    for token in tokens:
        x, y = _x(token), _y(token)
        if not (row['top'] <= y <= row['bottom']):
            continue
        if side == 'left' and x >= .5:
            continue
        if side == 'right' and x < .5:
            continue
        items.append(token)
    items = _normalize_row_percentages(items)
    return sorted(items, key=_x)


def _normalize_row_percentages(tokens):
    """Join '80' + '%' and repair OCR's reversed '%6' form."""
    items = []
    pending = None
    for token in sorted(tokens, key=_x):
        text = _text(token).replace('>', '').strip()
        repaired = bool(re.fullmatch(r'%\d{1,3}', text))
        text = re.sub(r'^%(\d{1,3})$', r'\1%', text)
        if text == '%' and pending is not None and pending.get('_number') is not None:
            merged = {
                'text': f"{pending['_number']}%",
                'confidence': min(pending['confidence'], token['confidence']),
                'box': _union_box(pending['box'], token['box']),
                '_repaired': True,
            }
            items = [item for item in items if item is not pending]
            items.append(merged)
            pending = None
            continue
        copy = dict(token)
        copy['text'] = text
        if repaired:
            copy['_repaired'] = True
        items.append(copy)
        if INT_RE.match(text):
            pending = copy
            copy['_number'] = text
        elif text.endswith('%'):
            pending = None
        else:
            pending = None
    for item in items:
        item.pop('_number', None)
    return items


def _union_box(a, b):
    xs = [point[0] for point in a + b]
    ys = [point[1] for point in a + b]
    return [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]]


def _read_nickname(tokens, row, side):
    if side == 'left':
        low, high = .08, .49
    else:
        low, high = .60, .99
    candidates = []
    for token in tokens:
        text = _compact(_text(token))
        x, y = _x(token), _y(token)
        if not (low <= x <= high and row['y'] - .09 <= y <= row['y'] - .005):
            continue
        if not (2 <= len(text) <= 24) or token['confidence'] < .5:
            continue
        if INT_RE.match(text) or PERCENT_RE.match(text) or BIG_RE.match(text) or RATIO_RE.match(text):
            continue
        if TITLE_RE.search(text) or text in ('MVP', '返回队伍', '双方', '对位', '未开始匹配'):
            continue
        if any(symbol in text for symbol in ('+', '(', ')', '（', '）', '/', '%')):
            continue
        if text in {entry['name'] for entry in catalog()['entries'] if entry['kind'] == 'hero'}:
            continue
        clean = _clean_nickname(text)
        if len(clean) < 2 or TITLE_RE.search(clean):
            continue
        score = len(clean) * 2 - abs(y - (row['y'] - .055)) * 30 + token['confidence']
        candidates.append((score, clean, token))
    if not candidates:
        return None
    _, clean, token = max(candidates, key=lambda item: (item[0], item[2]['confidence']))
    return _field(token, clean)


def _clean_nickname(text):
    text = str(text or '').strip().strip('*')
    text = re.sub(r'^\d{1,3}(?=[\u4e00-\u9fffA-Za-z])', '', text)
    text = re.sub(r'\s+', '', text)
    return text.strip('*')


def _column_readings(image, source_image, rows):
    """Read the printed hero-name column as a strip; rows are scored by y."""
    result = {}
    source = source_image or image
    width, height = source.size
    for side in ('left', 'right'):
        side_rows = rows.get(side) or []
        if not side_rows:
            continue
        x1, x2 = (0.0, 0.13) if side == 'left' else (0.49, 0.63)
        y1 = min(row['top'] for row in side_rows)
        y2 = max(row['bottom'] for row in side_rows)
        box = (round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        area = source.crop(box)
        for scale in (2, 3):
            enlarged = area.resize((area.width * scale, area.height * scale), Image.Resampling.LANCZOS)
            for raw_box, text, confidence in ocr.detect_tokens(enlarged):
                value = _compact(str(text))
                # 不同版本的 rapidocr 置信度类型不一致（float / numpy / str），统一转一次再比。
                try:
                    score = float(confidence)
                except (TypeError, ValueError):
                    score = 0.0
                if not (1 <= len(value) <= 8) or score < .4:
                    continue
                if INT_RE.match(value) or RATING_RE.match(value) or PERCENT_RE.match(value):
                    continue
                if value in ('MVP', 'MVP辅助') or TITLE_RE.search(value):
                    continue
                center_x = sum(point[0] for point in raw_box) / 4 / enlarged.width
                center_y = sum(point[1] for point in raw_box) / 4 / enlarged.height
                absolute_x = x1 + center_x * (x2 - x1)
                if (side == 'left' and absolute_x > .10) or (side == 'right' and absolute_x > .57):
                    continue
                absolute_y = y1 + center_y * (y2 - y1)
                row = min(side_rows, key=lambda item: abs(item['y'] - absolute_y))
                if abs(row['y'] - absolute_y) > (row['bottom'] - row['top']) * .65:
                    continue
                result.setdefault((side, row['slot']), []).append({
                    'raw': value, 'confidence': float(confidence), 'variant': f'column-{scale}',
                    'box': [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                })
    return result


def _read_hero(image, tokens, row, side, source_image=None, column_hero_readings=None):
    entries = catalog()['entries']
    low, high = (.0, .14) if side == 'left' else (.49, .63)
    readings = []
    for token in tokens:
        text = _compact(_text(token))
        x, y = _x(token), _y(token)
        if not (low <= x <= high and row['y'] - .005 <= y <= row['y'] + .07):
            continue
        if not (2 <= len(text) <= 8) or token['confidence'] < .35:
            continue
        if text in ('MVP', '银牌', '金牌', '铜牌') or TITLE_RE.search(text):
            continue
        if any(symbol in text for symbol in ('+', '(', ')', '（', '）', '/', '%')):
            continue
        if INT_RE.match(text) or RATING_RE.match(text) or BIG_RE.match(text):
            continue
        readings.append({'raw': text, 'confidence': token['confidence'],
                          'variant': 'full-frame', 'box': token['box']})
    for column in (column_hero_readings or []):
        if all(column['raw'] != reading['raw'] for reading in readings):
            readings.append(column)
    result = resolve_name(readings, entries)
    if result['accepted'] is None:
        targeted = _read_hero_label(image, row, side, source_image)
        if targeted:
            readings.append(targeted)
            result = resolve_name(readings, entries)
    candidates = list(result['candidates'])
    for reading in readings:
        raw = re.sub(r'[^\u4e00-\u9fff]', '', reading['raw'])
        if not raw:
            continue
        for entry in entries:
            if entry['kind'] != 'hero':
                continue
            if raw == entry['name']:
                continue
            if len(raw) < len(entry['name']) and entry['name'].startswith(raw):
                candidates.append({'id': entry['id'], 'name': entry['name'], 'icon': entry.get('icon'),
                                   'source': 'name-prefix', 'distance': len(entry['name']) - len(raw),
                                   'raw': reading['raw'], 'textConfidence': reading['confidence'],
                                   'evidence': reading['raw'], 'needsReview': True})
    seen = set()
    unique = []
    for candidate in sorted(candidates, key=lambda item: (item['distance'], -item['textConfidence'], item['name'])):
        if candidate['name'] in seen:
            continue
        seen.add(candidate['name'])
        unique.append(candidate)
    accepted = result['accepted']
    fuzzy = False
    if not accepted:
        exact = [item for item in unique if item['distance'] == 0 and item['textConfidence'] >= .7]
        accepted = exact[0] if len(exact) == 1 else None
    if not accepted:
        accepted = _unique_fuzzy(unique)
        fuzzy = accepted is not None
    hero = None
    status = 'unreadable'
    if accepted:
        source = next((reading for reading in readings if reading['raw'] == accepted['raw']), None)
        box = source.get('box') if source else None
        hero = {'value': accepted['name'], 'raw': accepted['raw'],
                'confidence': accepted['textConfidence'], 'box': box}
        status = 'auto-matched' if fuzzy else 'exact'
    elif unique:
        status = 'uncertain'
    return hero, status, unique[:5], readings


def _unique_fuzzy(candidates):
    """Accept a single high-confidence near/prefix match, never a guess among peers."""
    if not candidates:
        return None
    top = candidates[0]
    if top.get('distance') != 1 or top.get('textConfidence', 0) < .55:
        return None
    raw = re.sub(r'[^一-鿿]', '', str(top.get('raw') or ''))
    if not raw:
        return None
    if len(raw) == 1:
        matches = [candidate for candidate in candidates if candidate['name'].startswith(raw)]
        if len(matches) != 1:
            return None
    near = [candidate for candidate in candidates[1:]
            if candidate['distance'] <= 1 and candidate['name'] != top['name']]
    if near and max(candidate.get('textConfidence', 0) for candidate in near) >= top.get('textConfidence', 0) - .12:
        return None
    return top


def _read_hero_label(image, row, side, source_image=None):
    image = source_image or image
    width, height = image.size
    x1, x2 = (0, .14) if side == 'left' else (.49, .63)
    y1, y2 = row['y'] - .005, row['y'] + .065
    box = (round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    area = image.crop(box)
    readings = []
    for scale in (4, 8):
        enlarged = area.resize((area.width * scale, area.height * scale), Image.Resampling.LANCZOS)
        for variant, candidate in (('raw', enlarged), ('gray', ImageOps.autocontrast(enlarged.convert('L')).convert('RGB'))):
            found = ocr.read_line(candidate)
            if found:
                text = _compact(str(found[0][0]))
                confidence = float(found[0][1])
                if 2 <= len(text) <= 8 and confidence >= .35:
                    readings.append((confidence, text, variant))
    if not readings:
        return None
    confidence, text, variant = max(readings, key=lambda item: (item[0], len(item[1])))
    text = _compact(text)
    if not (2 <= len(text) <= 8) or confidence < .4:
        return None
    if any(symbol in text for symbol in ('+', '(', ')', '（', '）', '/', '%')):
        return None
    return {'raw': text, 'confidence': confidence, 'variant': f'targeted-{variant}',
            'box': [[round(x1, 5), round(y1, 5)], [round(x2, 5), round(y1, 5)],
                    [round(x2, 5), round(y2, 5)], [round(x1, 5), round(y2, 5)]]}


def _read_title(tokens):
    for token in tokens:
        match = TITLE_RE.search(_compact(_text(token)))
        if match:
            return _field(token, match.group(0))
    return None


def _glyph_read(image, box, scales=(6, 10)):
    """Otsu 定位字形包围盒后回原图紧裁重读，返回 [(text, confidence), ...]。

    深色底上的细小数字（对塔伤害的 0、右队战绩行的 KDA）常规整框重读容易
    失败或被相邻列污染；先自适应二值化找前景包围盒，再从原图裁出带反锯齿
    的紧贴区域放大识别。只在常规读取失败后调用。
    """
    if not box:
        return None
    crop = image.crop(box)
    gray = np.asarray(crop.convert('L'), dtype=np.float32)
    if gray.size < 16:
        return None
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = float((np.arange(256) * hist).sum())
    sum_b = weight_b = 0.0
    threshold, best_var = 0, -1.0
    for level in range(256):
        weight_b += hist[level]
        if not weight_b:
            continue
        weight_f = total - weight_b
        if not weight_f:
            break
        sum_b += level * hist[level]
        mean_b, mean_f = sum_b / weight_b, (sum_all - sum_b) / weight_f
        var = weight_b * weight_f * (mean_b - mean_f) ** 2
        if var > best_var:
            best_var, threshold = var, level
    bright = gray >= threshold
    dark = ~bright
    # 结算页数值是深底亮字；前景占比异常说明整框偏亮/偏暗，换极性再试。
    fg = bright if .004 <= float(bright.mean()) <= .4 else dark
    ys, xs = np.where(fg)
    if not len(xs):
        return None
    width, height = crop.size
    pad_x, pad_y = max(1, round(width * .02)), max(1, round(height * .08))
    x1, x2 = max(0, int(xs.min()) - pad_x), min(width, int(xs.max()) + pad_x + 1)
    y1, y2 = max(0, int(ys.min()) - pad_y), min(height, int(ys.max()) + pad_y + 1)
    tight = crop.crop((x1, y1, x2, y2))
    results = []
    for scale in scales:
        big = tight.resize((tight.width * scale, tight.height * scale), Image.Resampling.LANCZOS)
        for variant in (big, ImageOps.autocontrast(big)):
            for text, confidence in ocr.read_line(variant) or []:
                text = _compact(str(text))
                if text:
                    results.append((text, float(confidence)))
    results.sort(key=lambda item: -item[1])
    return results


def _parse_kda_text(text):
    """解析 KDA 文本并做合理性门限（MVP 徽章粘连可能产生 78/1/79243）。"""
    match = KDA_RE.match(_compact(text))
    if not match:
        return None
    kills, deaths, assists = (int(value) for value in match.groups())
    if kills > 40 or deaths > 40 or assists > 60:
        return None
    return kills, deaths, assists


def _kda_field_plausible(key, value):
    if value is None:
        return False
    if key == 'gold':
        return 200 <= value <= 40000
    if key == 'assists':
        return 0 <= value <= 60
    return 0 <= value <= 40


def _token_box_region(token, pad=.004):
    xs = [p[0] for p in token['box']]
    ys = [p[1] for p in token['box']]
    return (max(0, min(xs) - pad), max(0, min(ys) - pad), max(xs) + pad, max(ys) + pad)


def _frac_box(image, region):
    """归一化坐标区域 → 像素包围盒。"""
    width, height = image.size
    x1, y1, x2, y2 = region
    return (max(0, round(x1 * width)), max(0, round(y1 * height)),
            min(width, round(x2 * width)), min(height, round(y2 * height)))


def _glyph_crosscheck_int(image, token, parsed):
    """整页检测偶尔把细小字形读反（w1920 下曾以 0.97 置信度把 6 读成 9）。

    对检测框做字形级紧框重读：只有全部高置信变体一致给出另一个单位数时才
    采信，token 原值进 originalValue 供审查对照；其余情况维持 token 结果。
    """
    glyph = _glyph_read(image, _frac_box(image, _token_box_region(token, pad=.002)))
    digits = {text for text, confidence in (glyph or [])
              if len(text) == 1 and text.isdigit() and confidence >= .85}
    if len(digits) == 1:
        value = int(next(iter(digits)))
        if value != parsed:
            raw, confidence = next((text, conf) for text, conf in glyph if text == str(value))
            return {'value': value, 'raw': raw, 'confidence': confidence,
                    'box': token['box'], 'originalValue': parsed,
                    'correctedBy': 'glyph-vote'}
    return _field(token, parsed)


def _read_score_fields(image, tokens, row):
    fields = {}
    left = _x(row['token']) < .5
    kda_x1, kda_x2 = (.30, .44) if left else (.772, .875)
    gold_x1, gold_x2 = (.39, .47) if left else (.838, .965)
    line = row['y'] - .05

    # v1.5: 行内干净 token 优先。MVP 徽章偶尔把 KDA 和经济粘连成一个坏
    # token（78/1/79243），先尝试标准 KDA 正则，失败再走合并拆分。
    kda_token = gold_token = None
    for token in tokens:
        text = _compact(_text(token))
        if not (kda_x1 <= _x(token) <= gold_x2) or abs(_y(token) - line) > .04:
            continue
        if '/' in text and kda_token is None:
            kda_token = token
        if GOLD_TOKEN_RE.match(text) and gold_token is None and _x(token) >= gold_x1:
            gold_token = token
    if kda_token is not None or gold_token is not None:
        line = _y(kda_token or gold_token)
    kills = deaths = assists = gold = None
    kda_token_is_merged = False
    if kda_token is not None:
        parsed = _parse_kda_text(_text(kda_token))
        if parsed:
            kills, deaths, assists = parsed
        else:
            # KDA 与经济粘连成一个 token（5/0/88697）：按已知拆分规则展开。
            split = _split_kda_gold(_compact(_text(kda_token)))
            if split and split['kills'] <= 40 and split['deaths'] <= 40 and split['assists'] <= 60:
                kills, deaths, assists = split['kills'], split['deaths'], split['assists']
                if 200 <= split['gold'] <= 40000:
                    gold = split['gold']
                    kda_token_is_merged = True
    if gold_token is not None:
        value = int(_compact(_text(gold_token)))
        if 200 <= value <= 40000:
            gold = value

    # 行内 token 解析不全 → 字形级重读（KDA 区右边界卡到经济 token 之前，
    # 避免金色数字首位混进 KDA 读成 2/7/25）。
    kda_rescue = gold_rescue = None
    if kills is None:
        if kda_token is not None:
            region = _token_box_region(kda_token)
            if gold_token is not None:
                region = (region[0], region[1],
                          min(region[2], min(p[0] for p in gold_token['box']) - .003),
                          region[3])
        else:
            region = (kda_x1, line - .024, min(kda_x2, gold_x1 - .003), line + .024)
        for text, confidence in (_glyph_read(image, _frac_box(image, region)) or []):
            parsed = _parse_kda_text(text)
            if parsed:
                kills, deaths, assists = parsed
                kda_rescue = (text, confidence)
                break
    if gold is None and gold_token is None:
        region_x1 = gold_x1
        if kda_token is not None:
            region_x1 = max(region_x1, max(p[0] for p in kda_token['box']) + .003)
        region = (region_x1, line - .022, gold_x2, line + .022)
        for text, confidence in (_glyph_read(image, _frac_box(image, region)) or []):
            match = re.fullmatch(r'\d{3,6}', text)
            if match and 200 <= int(text) <= 40000:
                gold = int(text)
                gold_rescue = (text, confidence)
                break

    rescued = {}
    if kills is not None:
        if kda_rescue:
            raw, confidence, box = kda_rescue[0], kda_rescue[1], None
        elif kda_token is not None:
            raw, confidence, box = _text(kda_token), kda_token['confidence'], kda_token['box']
        else:
            raw, confidence, box = f'{kills}/{deaths}/{assists}', 0.0, None
        for key, value in zip(('kills', 'deaths', 'assists'), (kills, deaths, assists)):
            rescued[key] = {'value': value, 'raw': raw,
                            'confidence': confidence, 'box': box}
    if gold is not None:
        if gold_rescue:
            raw, confidence, box = gold_rescue[0], gold_rescue[1], None
        elif gold_token is not None:
            raw, confidence, box = _text(gold_token), gold_token['confidence'], gold_token['box']
        elif kda_token_is_merged and kda_token is not None:
            raw, confidence, box = _text(kda_token), kda_token['confidence'], kda_token['box']
        else:
            raw, confidence, box = str(gold), 0.0, None
        rescued['gold'] = {'value': gold, 'raw': raw,
                           'confidence': confidence, 'box': box}

    # 原链路兜底：行内合并拆分 → 合并读拆分 → 定点分列读。
    legacy = {}
    for token in tokens:
        parsed = _split_kda_gold(_compact(_text(token)))
        if parsed:
            for key, value in parsed.items():
                legacy[key] = {'value': value, 'raw': _text(token),
                               'confidence': token['confidence'], 'box': token['box']}
            break
    if not legacy:
        combined = _read_cell_text(image, (kda_x1 + gold_x2) / 2, row['y'] - .06,
                                   width=gold_x2 - kda_x1, height=.04)
        if combined:
            parsed = _split_kda_gold(combined[0])
            if parsed:
                for key in ('kills', 'deaths', 'assists', 'gold'):
                    legacy[key] = {'value': parsed[key], 'raw': combined[0],
                                   'confidence': combined[1], 'box': combined[2]}
    if not legacy:
        kda_mid_x1, kda_mid_x2 = (.31, .405) if left else (.80, .875)
        gold_mid_x1, gold_mid_x2 = (.395, .45) if left else (.88, .95)
        y = row['y'] - .06
        kda_text = _read_cell_text(image, (kda_mid_x1 + kda_mid_x2) / 2, y,
                                   width=kda_mid_x2 - kda_mid_x1, height=.035)
        gold_text = _read_cell_text(image, (gold_mid_x1 + gold_mid_x2) / 2, y,
                                    width=gold_mid_x2 - gold_mid_x1, height=.035)
        if kda_text:
            parsed = _parse_kda_text(kda_text[0])
            if parsed:
                for key, value in zip(('kills', 'deaths', 'assists'), parsed):
                    legacy[key] = {'value': value, 'raw': _compact(kda_text[0]),
                                   'confidence': kda_text[1], 'box': kda_text[2]}
        if gold_text:
            match = BIG_RE.match(_compact(gold_text[0]))
            if match:
                value = _big_value(match)
                if value is not None:
                    legacy['gold'] = {'value': value, 'raw': match.group(0),
                                      'confidence': gold_text[1], 'box': gold_text[2]}

    # 按字段合并：字形/token 级结果优先，原链路补缺；每个值过合理性门限。
    for key in ('kills', 'deaths', 'assists', 'gold'):
        if key in rescued:
            fields[key] = rescued[key]
            continue
        candidate = legacy.get(key)
        if candidate is None or not _kda_field_plausible(key, candidate['value']):
            continue
        fields[key] = candidate
    return fields


def _split_kda_gold(text):
    """Split the score row's compact KDA+gold token, e.g. 9/4/1313171.

    The last assist digit and the first gold digit are printed adjacently and
    OCR often joins them.  Try every legal split and reject implausible gold
    totals (the screenshot's four-digit/五位数 gold band).  JPEG 压缩偶尔在
    尾部粘出一个幽灵数字（2/7/2+5828 → 2/7/258280），因此同时给截掉 1-2 位
    尾部的文本打分选全局最优；助攻用小值先验（>20 少见）。
    """
    text = _compact(text)
    best = None
    for trim in (0, 1, 2):
        trimmed = text[:len(text) - trim] if trim else text
        match = re.match(r'^(\d{1,3})/(\d{1,3})/(\d{3,7})$', trimmed)
        if not match:
            continue
        kills, deaths, rest = match.groups()
        for length in (1, 2, 3):
            if len(rest) <= length + 2:
                continue
            assist = int(rest[:length])
            gold_text = rest[length:]
            if assist > 100 or len(gold_text) < 3 or len(gold_text) > 6:
                continue
            gold = int(gold_text)
            score = 0
            if 2000 <= gold <= 30000:
                score += 4
            if 4000 <= gold <= 20000:
                score += 2
            if len(gold_text) in (4, 5):
                score += 1
            if assist <= 20:
                score += 2
            elif assist > 40:
                score -= 3
            if gold < 1000:
                score -= 2
            candidate = (score, -trim, -length, int(kills), int(deaths), assist, gold)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    return {'kills': best[3], 'deaths': best[4], 'assists': best[5], 'gold': best[6]}


def _read_columns(image, row_tokens, all_tokens, row, side, page):
    profile = PROFILE_COLUMNS[page]
    return _read_columns_with_profile(image, row_tokens, all_tokens, row, side, profile)


def _read_columns_with_profile(image, row_tokens, all_tokens, row, side, profile):
    fields = {}
    shares = {}
    headers = _find_headers(all_tokens, row, side, profile)
    if any(header is None for header in headers):
        return fields, shares
    for column, header in zip(profile, headers):
        value_y = row['y'] + column['value_dy']
        value_x = header['x'] + column.get('value_dx', -.01)
        candidates = []
        for token in row_tokens:
            x, y = _x(token), _y(token)
            if not (abs(x - value_x) <= .045 and abs(y - value_y) <= .04):
                continue
            parsed = _parse_metric(_text(token), column['kind'])
            if parsed is None:
                continue
            candidates.append((abs(y - value_y) + abs(x - value_x), -token['confidence'], token, parsed))
        if candidates:
            distance, _, token, parsed = min(candidates, key=lambda item: (item[0], item[1]))
            # v1.5: 明显偏离预期位置或低置信度的 token 先与定点直读互核，防串列
            # （昵称行的 ③ 徽章曾顶替没检测到的击败数 2）。阈值不能太紧——
            # 正常 token 也可能偏离 0.02 左右，互核裁剪框容易蹭到邻近列。
            cell = None
            if distance > .03 or token['confidence'] < .85:
                cell = _read_cell_metric(image, value_x, value_y, kind=column['kind'])
            if cell is None and column['kind'] == 'ratio' and _compact(_text(token)).startswith('.'):
                probe = _read_cell_text(image, value_x, value_y, width=.05, height=.025)
                cell_value = _parse_metric(probe[0], 'ratio') if probe else None
                if cell_value is not None:
                    cell = {'value': cell_value, 'raw': probe[0],
                            'confidence': probe[1], 'box': probe[2]}
            if cell is not None:
                fields[column['field']] = cell
            elif column['kind'] == 'int' and len(_compact(_text(token))) == 1:
                # 只对单位数 token 做字形互核：多位数被重读成单位数属于重读失败，
                # 不能当成翻转依据。
                fields[column['field']] = _glyph_crosscheck_int(image, token, parsed)
            else:
                fields[column['field']] = _field(token, parsed)
        else:
            cell = _read_cell_metric(image, value_x, value_y, kind=column['kind'])
            if cell:
                fields[column['field']] = cell
        share_name = column.get('share')
        if not share_name:
            continue
        share_y = row['y'] + column['share_dy']
        share_x = header['x'] + column.get('share_dx', .03)
        share_candidates = []
        for token in row_tokens:
            x, y = _x(token), _y(token)
            if not (abs(x - share_x) <= .045 and abs(y - share_y) <= .04):
                continue
            parsed = _parse_metric(_text(token), 'percent')
            if parsed is None:
                continue
            share_candidates.append((abs(y - share_y) + abs(x - share_x), -token['confidence'], token, parsed))
        if share_candidates:
            _, _, token, parsed = min(share_candidates, key=lambda item: (item[0], item[1]))
            if token.get('_repaired'):
                cell = _read_cell_text(image, share_x, share_y, width=.05, height=.02)
                cell_value = _parse_metric(cell[0], 'percent') if cell else None
                if cell_value is not None:
                    shares[share_name] = {'value': cell_value, 'raw': cell[0],
                                          'confidence': cell[1], 'box': cell[2]}
                    continue
            shares[share_name] = _field(token, parsed)
        else:
            cell = _read_cell_metric(image, share_x, share_y, kind='percent', width=.05)
            if cell:
                shares[share_name] = cell
    return fields, shares


def _find_headers(tokens, row, side, profile):
    top = row['top']
    low, high = (.1, .49) if side == 'left' else (.5, .99)
    headers = []
    for column in profile:
        found = [token for token in tokens
                 if column['header'] in _compact(_text(token))
                 and low <= _x(token) <= high and _y(token) < top - .005]
        if not found:
            headers.append(None)
            continue
        token = max(found, key=lambda item: (item['confidence'], -_y(item)))
        headers.append({'text': column['header'], 'x': _x(token), 'token': token})
    return headers


def _parse_metric(text, kind):
    text = _compact(text).replace('>', '')
    if kind == 'percent':
        match = PERCENT_RE.match(text)
        return None if not match else round(float(match.group(1)), 1)
    if kind == 'int':
        # 细小 0 字形常被识别成字母 O（对塔伤害列），仅限整型列做映射。
        text = text.replace('O', '0').replace('o', '0')
        match = INT_RE.match(text)
        return None if not match else int(text)
    if kind == 'ratio':
        match = RATIO_RE.match(text)
        return None if not match else float(text)
    match = BIG_RE.match(text)
    if not match:
        return None
    return _big_value(match)


def _big_value(match):
    try:
        number = float(match.group(1))
    except (TypeError, ValueError):
        return None
    suffix = (match.group(2) or '').lower()
    if suffix == 'k':
        number *= 1000
    elif suffix == '万':
        number *= 10000
    return int(round(number))


def _read_cell_text(image, x, y, width=.06, height=.024):
    box = _crop_box(image, x, y, width, height)
    if not box:
        return None
    area = image.crop(box)
    area = area.resize((area.width * 5, area.height * 5), Image.Resampling.LANCZOS)
    found = ocr.read_line(area)
    if not found or float(found[0][1]) < .5:
        gray = ImageOps.autocontrast(area.convert('L')).convert('RGB')
        found = ocr.read_line(gray) or found
    if not found:
        return None
    text = _compact(str(found[0][0]))
    if not text:
        return None
    return text, float(found[0][1]), _box_to_list(box, image.size)


def _read_cell_value(image, x, y, kind, width=.06, height=.024):
    result = _read_cell_text(image, x, y, width=width, height=height)
    value = _parse_metric(result[0], kind) if result else None
    if value is None and kind == 'big' and result:
        # A one-decimal display can lose its trailing zero (1.0 -> 1).
        value = _parse_metric(result[0] + '.0', kind) if INT_RE.match(result[0]) else None
    if value is None:
        # v1.5: 常规重读失败 → 字形级救援（深底细小 0、低对比 KDA）。
        box = _crop_box(image, x, y, width, height)
        for text, confidence in (_glyph_read(image, box) or []):
            value = _parse_metric(text, kind)
            if value is None and kind == 'big':
                value = _parse_metric(text + '.0', kind) if INT_RE.match(text) else None
            if value is not None:
                return value
    return value


def _read_cell_metric(image, x, y, kind, width=.06, height=.024):
    """定点直读 + 字形变体投票。

    JPEG 压缩的振铃会把细字重影或粘出幽灵数字（7→77、1→51、11→211、
    66%→99%），单一读取难以稳定；对同一裁剪框收集常规直读与字形变体的
    全部可解析候选，按出现次数取多数，平票时保留常规直读。
    """
    result = _read_cell_text(image, x, y, width=width, height=height)
    box = _crop_box(image, x, y, width, height)
    candidates = []
    if result:
        value = _parse_metric(result[0], kind)
        if value is None and kind == 'big':
            value = _parse_metric(result[0] + '.0', kind) if INT_RE.match(result[0]) else None
        if value is not None:
            candidates.append((value, result[0], result[1]))
    for text, confidence in (_glyph_read(image, box) or []):
        value = _parse_metric(text, kind)
        if value is None and kind == 'big':
            value = _parse_metric(text + '.0', kind) if INT_RE.match(text) else None
        if value is not None:
            candidates.append((value, text, confidence))
    if not candidates:
        return None
    counts = {}
    for value, _, _ in candidates:
        counts[value] = counts.get(value, 0) + 1
    top = max(counts.values())
    tied = [value for value, count in counts.items() if count == top]
    best_value = candidates[0][0] if candidates[0][0] in tied else tied[0]
    raw, confidence = next((raw, conf) for value, raw, conf in candidates if value == best_value)
    return {'value': best_value, 'raw': raw, 'confidence': confidence,
            'box': _box_to_list(box, image.size)}


def _crop_box(image, x, y, width, height):
    image_width, image_height = image.size
    box = (round((x - width / 2) * image_width), round((y - height / 2) * image_height),
           round((x + width / 2) * image_width), round((y + height / 2) * image_height))
    box = (max(0, box[0]), max(0, box[1]),
           min(image_width, box[2]), min(image_height, box[3]))
    if box[2] - box[0] < 3 or box[3] - box[1] < 3:
        return None
    return box


def _box_to_list(box, image_size):
    width, height = image_size
    x1, y1, x2, y2 = box
    return [[round(x1 / width, 5), round(y1 / height, 5)],
            [round(x2 / width, 5), round(y1 / height, 5)],
            [round(x2 / width, 5), round(y2 / height, 5)],
            [round(x1 / width, 5), round(y2 / height, 5)]]


def _field(token, value):
    return {'value': value, 'raw': _text(token), 'confidence': token['confidence'],
            'box': token['box']}


def _coverage(players):
    coverage = {}
    for field in ('nickname', 'hero', 'rating'):
        coverage[field] = sum(1 for player in players if player.get(field))
    for field in PLAYER_LABELS:
        if field in ('nickname', 'hero', 'rating'):
            continue
        if field == 'title':
            coverage[field] = sum(1 for player in players if player.get('title'))
        elif field == 'mvp':
            coverage[field] = sum(1 for player in players if player.get('mvp'))
        else:
            coverage[field] = sum(1 for player in players if field in player['fields'])
    for field in SHARE_FIELDS:
        coverage[field] = sum(1 for player in players if field in player['shares'])
    return coverage


def _validate_scores(match, players, page, warnings):
    score = match.get('score') or {}
    if score.get('left') is None or score.get('right') is None:
        return
    if page not in ('score', 'kda'):
        return
    for side in ('left', 'right'):
        kills = [player['fields'].get('kills') for player in players if player['side'] == side]
        if all(kills):
            total = sum(item['value'] for item in kills)
            if total != score[side]:
                warnings.append(f'{side} 侧五人击杀合计 {total} 与比分 {score[side]} 不符。')


# ---------------------------------------------------------------------------
# Merge multiple tabs of the same match.  Different matches must stay separate.

def merge_pages(results, name=None):
    """Group pages by match evidence and return a list of merged bundles."""
    clusters = []
    for result in results:
        for cluster in clusters:
            if _same_match(cluster[0], result):
                cluster.append(result)
                break
        else:
            clusters.append([result])
    return [_merge_cluster(cluster, name if len(clusters) == 1 else None) for cluster in clusters]


def _same_match(a, b):
    a_match, b_match = a.get('match') or {}, b.get('match') or {}
    if a_match.get('date') and b_match.get('date') and a_match['date'] != b_match['date']:
        return False
    if a_match.get('durationSec') and b_match.get('durationSec') and \
            a_match['durationSec'] != b_match['durationSec']:
        return False
    a_score, b_score = a_match.get('score') or {}, b_match.get('score') or {}
    overlap = _roster_overlap(a, b)
    if a_score.get('left') is not None and b_score.get('left') is not None:
        if a_score != b_score:
            return False
        if a_match.get('date') and b_match.get('date') and a_match['date'] == b_match['date']:
            return True
        return overlap >= 5
    return overlap >= 7


def _roster_overlap(a, b):
    if not a.get('players') or not b.get('players'):
        return 0
    overlap = 0
    for left in a['players']:
        right = next((item for item in b['players']
                      if item['side'] == left['side'] and item['slot'] == left['slot']), None)
        if not right:
            continue
        left_name = _nickname_value(left)
        right_name = _nickname_value(right)
        if left_name and right_name and left_name.lower() == right_name.lower():
            overlap += 1
        elif left.get('hero') and right.get('hero') and left['hero']['value'] == right['hero']['value']:
            overlap += 1
        elif left.get('rating') and right.get('rating') and abs(left['rating']['value'] - right['rating']['value']) < .01:
            overlap += .5
    return overlap


def _nickname_value(player):
    field = player.get('nickname')
    return field.get('value') if field else None


def _merge_cluster(cluster, name):
    cluster = sorted(cluster, key=lambda result: PAGE_ORDER_INDEX.get(result.get('pageType'), 99))
    # The KDA tab is the authoritative KDA view; the equipment score page can
    # misread its small KDA column and must not override it.
    player_pages = sorted(cluster, key=lambda result: (
        0 if result.get('pageType') == 'kda' else 1 if result.get('pageType') == 'score' else 2,
        PAGE_ORDER_INDEX.get(result.get('pageType'), 99)))
    base = _empty_bundle(cluster)
    for result in cluster:
        _merge_match(base['match'], result.get('match') or {}, result.get('pageType'), base['warnings'])
        base['pages'].append({'file': result.get('file'), 'pageType': result.get('pageType'),
                              'tab': result.get('tab'), 'imageId': result.get('imageId'),
                              'imageName': result.get('imageName')})
    for result in player_pages:
        for player in result.get('players') or []:
            target = next((item for item in base['players']
                           if item['side'] == player['side'] and item['slot'] == player['slot']), None)
            if target is None:
                target = {'side': player['side'], 'slot': player['slot']}
                base['players'].append(target)
            _merge_player(target, player, result.get('pageType'), base['warnings'])
    base['players'].sort(key=lambda item: (item['side'] != 'left', item['slot']))
    _reconcile_kda(base['players'], base['match'], base['warnings'], base)
    for player in base['players']:
        gold = (player.get('fields') or {}).get('gold')
        if not gold:
            continue
        # 战绩页的精确经济没读出来、只挂上数据/发育页的 k 值时，明确告诉教练
        # 这是千位精度，不是识别错误。
        if re.search(r'[kK万]', str(gold.get('raw') or '')):
            base['warnings'].append(
                f"{player['side']} {player['slot'] + 1} 经济为千位精度（{gold.get('raw')}，"
                '战绩页精确值没读出），分析用前建议核对')
    base['coverage'] = {
        'players': len(base['players']),
        'byField': _merged_coverage(base['players']),
        'pages': len(base['pages']),
    }
    qualities = [result.get('quality') for result in cluster if result.get('quality')]
    if qualities:
        base['quality'] = {
            'minBlur': min(item.get('blur', 0) for item in qualities),
            'minWidth': min(item.get('width', 0) for item in qualities),
            'warnings': _dedupe([warning for item in qualities
                                 for warning in item.get('warnings') or []]),
        }
    base['checklist'] = build_checklist(base['players'], base['pages'], base['match'])
    base['warnings'] = _dedupe(base['warnings'])
    if name:
        base['file'] = name
    _validate_merged(base)
    return base


REQUIRED_PAGES = (('战绩', ('score', 'kda'), '日期 / 时长 / 胜负 / KDA / 经济'),
                  ('数据', ('data',), '输出 / 承伤 / 经济 / 参团率'),
                  ('团队', ('team',), '参团率 / 控制 / 治疗 / 对塔'))
RECOMMENDED_PAGES = (('输出', ('output',), '输出伤害 / 伤害转化比'),
                     ('生存', ('survival',), '承受伤害 / 每死承伤'),
                     ('发育', ('farming',), '总经济 / 野怪经济 / 补刀数'))


def build_checklist(players, pages, match):
    """Explain what is still missing before this group is safe to hand off."""
    present = {page.get('pageType') for page in pages}
    missing_required, missing_recommended = [], []
    present_labels = []
    for label, kinds, detail in REQUIRED_PAGES:
        if present & set(kinds):
            present_labels.append(label)
        else:
            missing_required.append({'page': label, 'detail': detail})
    for label, kinds, detail in RECOMMENDED_PAGES:
        if present & set(kinds):
            present_labels.append(label)
        else:
            missing_recommended.append({'page': label, 'detail': detail})
    hero_missing = [f'{_side_name(player["side"])}{player["slot"] + 1}'
                    for player in players if not player.get('hero')]
    nickname_missing = sum(1 for player in players if not player.get('nickname'))
    match_missing = []
    for key, label in (('date', '日期'), ('durationSec', '时长'), ('result', '胜负')):
        if match.get(key) is None:
            match_missing.append(label)
    notes = []
    if missing_required:
        notes.append('缺少必采页：' + '、'.join(item['page'] for item in missing_required) + '。')
    if len(players) != 10:
        notes.append(f'当前 {len(players)} 人，正常赛后页应为 10 人。')
    if hero_missing:
        notes.append(f'{len(hero_missing)} 个英雄未确认：' + '、'.join(hero_missing) + '。')
    if match_missing:
        notes.append('比赛信息缺少：' + '、'.join(match_missing) + '。')
    if missing_recommended:
        notes.append('建议补采：' + '、'.join(item['page'] for item in missing_recommended) + '。')
    return {
        'required': [item[0] for item in REQUIRED_PAGES],
        'recommended': [item[0] for item in RECOMMENDED_PAGES],
        'present': present_labels,
        'missingRequired': missing_required,
        'missingRecommended': missing_recommended,
        'complete': not missing_required,
        'readyForDraft': not missing_required and len(players) == 10,
        'players': len(players),
        'heroMissing': hero_missing,
        'nicknameMissing': nickname_missing,
        'matchMissing': match_missing,
        'notes': notes,
    }


def _side_name(side):
    return '左' if side == 'left' else '右'


def _empty_bundle(cluster):
    return {
        'schema': SCHEMA,
        'version': OCR_VERSION,
        'file': None,
        'match': {'date': None, 'time': None, 'durationSec': None, 'mode': None,
                  'result': None, 'score': {'left': None, 'right': None}},
        'players': [],
        'pages': [],
        'coverage': {},
        'warnings': [],
    }


def _merge_match(target, source, page, warnings):
    for key in ('date', 'time', 'durationSec', 'mode', 'result'):
        value = source.get(key)
        if value is None:
            continue
        if target.get(key) is None:
            target[key] = value
        elif target[key] != value:
            warnings.append(f'{page} 页的 {key} 与其他页冲突：{target[key]} / {value}')
    source_score = source.get('score') or {}
    for side in ('left', 'right'):
        value = source_score.get(side)
        if value is None:
            continue
        if target['score'].get(side) is None:
            target['score'][side] = value
        elif target['score'][side] != value:
            warnings.append(f'{page} 页的比分与其他页冲突：{target["score"][side]} / {value}')


def _merge_player(target, source, page, warnings):
    for key in ('nickname', 'hero', 'rating', 'title'):
        value = source.get(key)
        if value is None:
            continue
        if target.get(key) is None:
            target[key] = value
        elif key == 'hero' and target[key].get('value') != value.get('value'):
            warnings.append(f'{page} 页英雄冲突：{target[key].get("value")} / {value.get("value")}')
        elif key == 'rating' and target[key].get('value') != value.get('value'):
            warnings.append(f'{page} 页评分冲突：{target[key].get("value")} / {value.get("value")}')
    if source.get('mvp'):
        target['mvp'] = True
    if source.get('heroStatus') == 'exact':
        target['heroStatus'] = 'exact'
    elif source.get('heroStatus') == 'auto-matched' and target.get('heroStatus') not in ('exact',):
        target['heroStatus'] = 'auto-matched'
    elif source.get('heroStatus') == 'uncertain' and target.get('heroStatus') not in ('exact', 'auto-matched'):
        target['heroStatus'] = 'uncertain'
    elif source.get('heroStatus') == 'manual' and target.get('heroStatus') not in ('exact', 'auto-matched'):
        target['heroStatus'] = 'manual'
    if source.get('heroCandidates'):
        target.setdefault('heroCandidates', [])
        seen = {item['name'] for item in target['heroCandidates']}
        for candidate in source['heroCandidates']:
            if candidate['name'] not in seen:
                target['heroCandidates'].append(candidate)
                seen.add(candidate['name'])
    for group in ('fields', 'shares'):
        target.setdefault(group, {})
        for field, value in (source.get(group) or {}).items():
            if field not in target[group]:
                target[group][field] = value
            elif target[group][field].get('value') != value.get('value'):
                current = target[group][field]
                if _same_rounded_measure(current, value, field):
                    if _rounded_measure(current) and not _rounded_measure(value):
                        precise = dict(value)
                        precise['agreement'] = 'rounded'
                        target[group][field] = precise
                    else:
                        current['agreement'] = 'rounded'
                else:
                    warnings.append(f'{page} 页 {field} 冲突：'
                                    f'{current.get("value")} / {value.get("value")}')
    target.setdefault('sources', [])
    if page not in target['sources']:
        target['sources'].append(page)


def _rounded_measure(field):
    raw = str((field or {}).get('raw') or '')
    return bool(re.search(r'\d(?:\.\d+)?\s*[kK万]', raw))


def _same_rounded_measure(a, b, field):
    """8.7k vs 8697 is display precision, not a data conflict."""
    if FIELD_UNITS.get(field) != 'unit':
        return False
    if not (_rounded_measure(a) or _rounded_measure(b)):
        return False
    try:
        left, right = float(a.get('value')), float(b.get('value'))
    except (TypeError, ValueError):
        return False
    return abs(left - right) <= max(2, .015 * max(abs(left), abs(right)))


def _reconcile_kda(players, match, warnings, bundle):
    """Use the KDA page's percentage shares and the score to repair tiny OCR misreads.

    Example: right row 1 kills read as 7 but its kills share is 17% of a 6-kill
    team; the apportioned value is 1.  Original values stay in ``originalValue``.
    """
    score = (match or {}).get('score') or {}
    if score.get('left') is None or score.get('right') is None:
        return
    corrections = []
    for side in ('left', 'right'):
        side_players = [player for player in players if player.get('side') == side]
        if len(side_players) != 5:
            continue
        for stat, share_key in (('kills', 'killsShare'), ('deaths', 'deathsShare')):
            pairs = []
            for player in side_players:
                field = (player.get('fields') or {}).get(stat)
                share = (player.get('shares') or {}).get(share_key)
                if not field or not share or share.get('value') is None:
                    pairs = []
                    break
                pairs.append((player, field, share))
            if len(pairs) != 5:
                continue
            shares = [share['value'] for _, _, share in pairs]
            if not 95 <= sum(shares) <= 105:
                continue
            if stat == 'kills':
                total = score[side]
            else:
                total = _infer_kda_total([field['value'] for _, field, _ in pairs], shares)
            if total is None:
                continue
            expected = _apportion_kda(total, shares)
            changed = False
            for (player, field, share), target_value in zip(pairs, expected):
                current = field.get('value')
                if current is None or target_value == current:
                    continue
                if abs(target_value - current) > 15:
                    # v1.5: 差距过大时，若当前值与自己的占比自相矛盾（JPEG 鬼影
                    # 可让两页读出同一个 51），而摊算值自洽，则仍采信摊算。
                    share_ratio = float(share['value']) / 100
                    current_broken = abs(float(current) / total - share_ratio) > .03
                    target_sound = abs(float(target_value) / total - share_ratio) <= .03
                    if not (current_broken and target_sound):
                        warnings.append(f'{side} {player["slot"] + 1} {stat} 按占比推算为 '
                                        f'{target_value}，与识别 {current} 差异过大，保留原值')
                        continue
                field['originalValue'] = current
                field['value'] = target_value
                field['correctedBy'] = f'{share_key}-share'
                field['share'] = share
                corrections.append(f'{side} {player["slot"] + 1} {stat} '
                                   f'{current}→{target_value}')
                changed = True
            if changed:
                warnings.append(f'{side} 侧 {stat} 已按页面占比与团队比分校正；'
                                f'原值保留在 originalValue。')
    if corrections:
        bundle['reconciliation'] = {
            'kda': corrections,
            'note': '按 KDA 页占比与比分校正；原值保留在字段 originalValue。',
        }


def _infer_kda_total(values, shares):
    candidates = []
    for value, share in zip(values, shares):
        if value is None or share is None or share <= 0:
            continue
        total = round(float(value) * 100 / float(share))
        if 0 <= total <= 120:
            candidates.append(total)
    if not candidates:
        return None
    candidates.sort()
    return candidates[len(candidates) // 2]


def _apportion_kda(total, shares):
    quotas = [float(total) * float(share) / 100 for share in shares]
    result = [int(value) for value in quotas]
    remainder = int(total) - sum(result)
    order = sorted(range(len(quotas)), key=lambda index: quotas[index] - result[index],
                   reverse=True)
    while remainder > 0:
        for index in order:
            if remainder <= 0:
                break
            result[index] += 1
            remainder -= 1
    while remainder < 0:
        for index in reversed(order):
            if remainder >= 0:
                break
            if result[index] > 0:
                result[index] -= 1
                remainder += 1
    return result


def _merged_coverage(players):
    coverage = {}
    for field in ('nickname', 'hero', 'rating'):
        coverage[field] = sum(1 for player in players if player.get(field))
    for field in PLAYER_LABELS:
        if field in ('nickname', 'hero', 'rating'):
            continue
        if field == 'title':
            coverage[field] = sum(1 for player in players if player.get('title'))
        elif field == 'mvp':
            coverage[field] = sum(1 for player in players if player.get('mvp'))
        else:
            coverage[field] = sum(1 for player in players if field in (player.get('fields') or {}))
    for field in SHARE_FIELDS:
        coverage[field] = sum(1 for player in players if field in (player.get('shares') or {}))
    return coverage


def _validate_merged(bundle):
    score = bundle['match'].get('score') or {}
    if score.get('left') is None or score.get('right') is None:
        return
    for side in ('left', 'right'):
        kills = [player.get('fields', {}).get('kills') for player in bundle['players']
                 if player['side'] == side]
        if all(kills):
            total = sum(item['value'] for item in kills)
            if total != score[side]:
                bundle['warnings'].append(
                    f'{side} 侧合成后五人击杀合计 {total} 与比分 {score[side]} 不符。')
