"""回放录屏 OCR：只读取画面中可见的文字，不推算未显示的状态。

适配 16:9 固定布局的本地回放录屏：回放列表 → 加载页 → 对局 HUD。
所有字段保留原始文本与置信度；缺失即 None，不补零，不进入正式统计。
"""
import hashlib
import json
import os
import re
import subprocess
import threading
from collections import Counter
from datetime import datetime, timezone

import numpy as np

import media_tools
from PIL import Image

from vision import catalog, rank_icon

SCHEMA = 'kpl-video-ocr-v1'
LAYOUT_16X9 = 'replay-hud-16x9-v1'
LAYOUT_20X9 = 'replay-hud-20x9-v1'
LAYOUT = LAYOUT_16X9
REFERENCE_16X9 = (1600, 900)
REFERENCE_20X9 = (1600, 720)
REFERENCE = REFERENCE_16X9
SAMPLE_WIDTH = 1600
MAX_SAMPLES = 2400
MAX_SCOREBOARD_ROWS = 5

# 1600x900 参考坐标。HUD 按宽度等比缩放；非 16:9 时给出警告但不硬拒绝。
ROI_16X9 = {
    'clock_top': (756, 0, 836, 28),
    'kill_blue': (732, 8, 774, 52),
    'kill_red': (824, 8, 868, 52),
    'gold_blue': (576, 4, 674, 54),
    'gold_red': (928, 4, 1024, 54),
    'outer_blue_dragon': (478, 10, 504, 48),
    'outer_blue_tower': (540, 10, 566, 48),
    'outer_red_tower': (1060, 10, 1086, 48),
    'outer_red_dragon': (1128, 10, 1154, 48),
    'kda': (388, 774, 474, 808),
    'selected_gold': (1140, 756, 1200, 790),
    'stats': (492, 716, 728, 752),
    'runes': (742, 758, 1115, 795),
    'equip_slot0': (795, 700, 840, 748),
    'level': (402, 742, 430, 776),
    'bottom_clock': (472, 826, 566, 866),
    'total_duration': (1040, 848, 1110, 884),
    'side_left': (0, 270, 165, 880),
    'side_right': (1435, 270, 1600, 880),
    'list_menu': (195, 20, 305, 65),
    'list_entry': (180, 410, 460, 560),
    'center_vs': (670, 360, 930, 540),
    'postgame_result': (650, 0, 950, 90),
    'postgame_buttons': (600, 780, 1000, 900),
    'score_probe': (540, 196, 810, 246),
    'score_blue_kda': (548, 198, 736, 244),
    'score_red_kda': (1306, 198, 1470, 244),
    'score_blue_gold': (744, 198, 800, 244),
    'score_red_gold': (1498, 198, 1566, 244),
    'score_blue_name': (170, 198, 480, 253),
    'score_red_name': (930, 198, 1240, 253),
}
ROI = dict(ROI_16X9)

# 20:9 录屏按 960x432 样本校准，再换算到 1600x720 参考系。
ROI_20X9 = {
    'clock_top': (720, 0, 880, 36),
    'kill_blue': (730, 0, 800, 45),
    'kill_red': (825, 0, 900, 45),
    'gold_blue': (575, 0, 660, 45),
    'gold_red': (875, 0, 990, 48),
    'outer_blue_dragon': (520, 0, 560, 40),
    'outer_blue_tower': (560, 0, 600, 40),
    'outer_red_tower': (990, 0, 1030, 40),
    'outer_red_dragon': (1030, 0, 1070, 40),
    'kda': (0, 0, 1, 1),
    'selected_gold': (0, 0, 1, 1),
    'stats': (0, 0, 1, 1),
    'runes': (0, 0, 1, 1),
    'equip_slot0': (0, 0, 1, 1),
    'level': (0, 0, 1, 1),
    'bottom_clock': (0, 0, 1, 1),
    'total_duration': (0, 0, 1, 1),
    'side_left': (0, 190, 190, 650),
    'side_right': (1410, 190, 1600, 650),
    'list_menu': (180, 15, 330, 70),
    'list_entry': (180, 300, 500, 500),
    'center_vs': (720, 300, 880, 420),
    'postgame_result': (700, 0, 900, 60),
    'postgame_buttons': (600, 600, 1100, 720),
    'score_probe': (0, 0, 1, 1),
    'score_blue_kda': (0, 0, 1, 1),
    'score_red_kda': (0, 0, 1, 1),
    'score_blue_gold': (0, 0, 1, 1),
    'score_red_gold': (0, 0, 1, 1),
    'score_blue_name': (0, 0, 1, 1),
    'score_red_name': (0, 0, 1, 1),
}
SCORE_ROW_STEP = 123
LOADING_CENTERS = (296, 546, 796, 1046, 1296)
LOADING_CENTERS_20X9 = (400, 600, 800, 1000, 1200)
LOADING_NAME = {'blue': (262, 334), 'red': (755, 834)}
LOADING_NAME_20X9 = {'blue': (235, 300), 'red': (610, 690)}
LOADING_HALF = (40, 55, 70)
LOADING_HALF_20X9 = (65, 80, 95)
SIDE_ROW_CENTERS = (303, 416, 528, 641, 753)
SIDE_ROW_CENTERS_20X9 = (242, 332, 422, 512, 602)
TEAM_PANEL_ROW_START = 699
TEAM_PANEL_ROW_STEP = 39
TEAM_PANEL_ROW_HEIGHT = 34
TEAM_PANEL_KDA = {'blue': (420, 525), 'red': (1074, 1180)}
TEAM_PANEL_GOLD = {'blue': (533, 586), 'red': (1013, 1065)}
TEAM_PANEL_ROW_START_20X9 = 565
TEAM_PANEL_ROW_STEP_20X9 = 31
TEAM_PANEL_ROW_HEIGHT_20X9 = 26
TEAM_PANEL_KDA_20X9 = {'blue': (470, 560), 'red': (995, 1070)}
TEAM_PANEL_GOLD_20X9 = {'blue': (560, 625), 'red': (900, 995)}
SUPPORTS_SELECTED = True
SUPPORTS_SCOREBOARD = True
SUPPORTS_TOTAL_DURATION = True
SUPPORTS_OUTER = True

_LAYOUT_STATE = (
    'LAYOUT', 'REFERENCE', 'ROI', 'SCORE_ROW_STEP', 'LOADING_CENTERS',
    'LOADING_NAME', 'LOADING_HALF', 'SIDE_ROW_CENTERS',
    'TEAM_PANEL_ROW_START', 'TEAM_PANEL_ROW_STEP', 'TEAM_PANEL_ROW_HEIGHT',
    'TEAM_PANEL_KDA', 'TEAM_PANEL_GOLD', 'SUPPORTS_SELECTED',
    'SUPPORTS_SCOREBOARD', 'SUPPORTS_TOTAL_DURATION', 'SUPPORTS_OUTER',
)


def set_layout(width, height):
    """Select the fixed-layout profile for a video and return the previous state."""
    global LAYOUT, REFERENCE, ROI, LOADING_CENTERS, LOADING_NAME, LOADING_HALF
    global SIDE_ROW_CENTERS, TEAM_PANEL_ROW_START, TEAM_PANEL_ROW_STEP
    global TEAM_PANEL_ROW_HEIGHT, TEAM_PANEL_KDA, TEAM_PANEL_GOLD
    global SUPPORTS_SELECTED, SUPPORTS_SCOREBOARD, SUPPORTS_TOTAL_DURATION, SUPPORTS_OUTER
    saved = {name: globals()[name] for name in _LAYOUT_STATE}
    ratio = width / height if height else 0
    if 1.95 <= ratio <= 2.55:
        LAYOUT = LAYOUT_20X9
        REFERENCE = REFERENCE_20X9
        ROI = dict(ROI_20X9)
        LOADING_CENTERS = LOADING_CENTERS_20X9
        LOADING_NAME = dict(LOADING_NAME_20X9)
        LOADING_HALF = LOADING_HALF_20X9
        SIDE_ROW_CENTERS = SIDE_ROW_CENTERS_20X9
        TEAM_PANEL_ROW_START = TEAM_PANEL_ROW_START_20X9
        TEAM_PANEL_ROW_STEP = TEAM_PANEL_ROW_STEP_20X9
        TEAM_PANEL_ROW_HEIGHT = TEAM_PANEL_ROW_HEIGHT_20X9
        TEAM_PANEL_KDA = dict(TEAM_PANEL_KDA_20X9)
        TEAM_PANEL_GOLD = dict(TEAM_PANEL_GOLD_20X9)
        SUPPORTS_SELECTED = False
        SUPPORTS_SCOREBOARD = False
        SUPPORTS_TOTAL_DURATION = False
        SUPPORTS_OUTER = True
    else:
        LAYOUT = LAYOUT_16X9
        REFERENCE = REFERENCE_16X9
        ROI = dict(ROI_16X9)
        LOADING_CENTERS = (296, 546, 796, 1046, 1296)
        LOADING_NAME = {'blue': (262, 334), 'red': (755, 834)}
        LOADING_HALF = (40, 55, 70)
        SIDE_ROW_CENTERS = (303, 416, 528, 641, 753)
        TEAM_PANEL_ROW_START = 699
        TEAM_PANEL_ROW_STEP = 39
        TEAM_PANEL_ROW_HEIGHT = 34
        TEAM_PANEL_KDA = {'blue': (420, 525), 'red': (1074, 1180)}
        TEAM_PANEL_GOLD = {'blue': (533, 586), 'red': (1013, 1065)}
        SUPPORTS_SELECTED = True
        SUPPORTS_SCOREBOARD = True
        SUPPORTS_TOTAL_DURATION = True
        SUPPORTS_OUTER = True
    return saved


def restore_layout(saved):
    globals().update(saved)


_engine = None
_engine_lock = threading.Lock()
# 布局是模块级全局量；两次 analyze_video 并发会互相覆盖坐标。
# 这里用一把锁把「选布局 → 分析 → 还原」串行化，宁可慢一点也不能读错裁剪框。
_layout_lock = threading.RLock()


class VideoOCRError(ValueError):
    """录屏无法读取或布局不支持。"""


def _engine_instance():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def _px(box, size):
    sx = size[0] / REFERENCE[0]
    sy = size[1] / REFERENCE[1]
    x1, y1, x2, y2 = box
    return (max(0, round(x1 * sx)), max(0, round(y1 * sy)),
            min(size[0], round(x2 * sx)), min(size[1], round(y2 * sy)))


def _tokens(image, box, scale=6, det=False, white=None, color=None):
    """OCR 一个区域；``white``/``color`` 用颜色掩码隔离半透明文字。"""
    x1, y1, x2, y2 = _px(box, image.size)
    if x2 <= x1 or y2 <= y1:
        return []
    crop = image.crop((x1, y1, x2, y2))
    if white is not None or color is not None:
        pixels = np.asarray(crop.convert('RGB')).astype(np.int16)
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        if color == 'blue':
            mask = (blue > 110) & (blue > red + 30) & (green > 60)
        elif color == 'red':
            mask = (red > 110) & (red > green + 30) & (red > blue + 10)
        else:
            mask = pixels.min(axis=2) > white
        crop = Image.fromarray((mask.astype(np.uint8) * 255))
    crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
    engine = _engine_instance()
    array = np.asarray(crop)
    if det:
        found, _ = engine(array)
        result = []
        for points, text, confidence in found or []:
            xs = [p[0] / scale + x1 for p in points]
            ys = [p[1] / scale + y1 for p in points]
            result.append({'text': text.strip(), 'confidence': float(confidence),
                           'box': [min(xs) / image.width, min(ys) / image.height,
                                   max(xs) / image.width, max(ys) / image.height]})
        return result
    found, _ = engine(array, use_det=False, use_cls=False)
    if not found:
        return []
    text, confidence = found[0]
    return [{'text': text.strip(), 'confidence': float(confidence),
             'box': [x1 / image.width, y1 / image.height, x2 / image.width, y2 / image.height]}]


def _best(tokens, parser, min_confidence=0.3):
    best = None
    for token in tokens:
        value = parser(token['text'])
        if value is None or token['confidence'] < min_confidence:
            continue
        if best is None or token['confidence'] > best['confidence']:
            best = {'raw': token['text'], 'value': value, 'confidence': round(token['confidence'], 3)}
    return best


def _field(tokens, parser, min_confidence=0.3):
    value = _best(tokens, parser, min_confidence)
    return value or {'raw': None, 'value': None, 'confidence': None}


_CLOCK = re.compile(r'^(\d{1,2})\s*[:：]\s*(\d{2})')
_GOLD = re.compile(r'(\d+(?:\.\d+)?)\s*([kK万]?)')
_KDA = re.compile(r'^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})$')
_COUNT = re.compile(r'^\d{1,2}$')
_DURATION = re.compile(r'^(\d{1,3})\s*[:：]\s*(\d{2})$')
_DATETIME = re.compile(r'(\d{1,2})\s*/\s*(\d{1,2})\s*(\d{1,2})\s*[:：]\s*(\d{2})')


def parse_clock(text):
    match = _CLOCK.match(text.strip())
    if not match:
        return None
    minutes, seconds = int(match[1]), int(match[2])
    if seconds >= 60 or minutes > 180:
        return None
    return minutes * 60 + seconds


def parse_gold(text):
    compact = re.sub(r'\s+', '', text)
    compact = re.sub(r'(?<=\d)[:：](?=\d)', '.', compact)
    match = _GOLD.search(compact)
    if not match:
        return None
    end = match.end()
    if end < len(compact) and compact[end].isdigit():
        return None
    unit = {'k': 1000, 'K': 1000, '万': 10000}.get(match[2], 1)
    value = float(match[1]) * unit
    if not 0 <= value <= 300000:
        return None
    return int(round(value))


def parse_count(text):
    value = text.strip()
    if len(value) > 1 and value.startswith('0'):
        return None
    return int(value) if _COUNT.fullmatch(value) and int(value) <= 99 else None


def parse_kda(text):
    match = _KDA.fullmatch(text.strip())
    return [int(match[1]), int(match[2]), int(match[3])] if match else None


def parse_level(text):
    value = text.strip()
    if value in ('↑', '1', 'l', 'I', '|'):
        return 1
    return int(value) if _COUNT.fullmatch(value) and 1 <= int(value) <= 30 else None


def parse_stat_number(text):
    # 单项属性为 0 时字形是一个小圆圈，识别模型会给出句号类结果。
    value = text.strip()
    if value in ('。', '.', '·', '•', 'o', 'O', '0'):
        return 0
    return int(value) if re.fullmatch(r'\d{1,4}', value) and int(value) <= 9999 else None


def parse_runes(text):
    raw = (text or '').strip()
    entries = []
    for part in re.split(r'[、，,]', raw):
        match = re.match(r'\s*(\d{1,2})\s*([^\d\s].*?)\s*$', part)
        if not match:
            continue
        name = match[2].strip('：:')
        if name:
            entries.append({'count': int(match[1]), 'name': name, 'raw': part.strip(),
                            'partial': part.strip().endswith(('：', ':'))})
    if not entries:
        return None
    return {'raw': raw, 'entries': entries,
            'truncated': raw.endswith(('：', ':', '、')) or entries[-1]['partial']}


def parse_duration(text):
    match = _DURATION.fullmatch(text.strip())
    if not match:
        return None
    minutes, seconds = int(match[1]), int(match[2])
    return minutes * 60 + seconds if seconds < 60 else None


def parse_datetime(text):
    for match in _DATETIME.finditer(text):
        month, day, hour, minute = (int(value) for value in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60:
            return {'month': month, 'day': day, 'hour': hour, 'minute': minute,
                    'text': f'{month:02d}-{day:02d} {hour:02d}:{minute:02d}'}
    return None


def normalize_mode(text):
    value = text.strip()
    value = value.replace('陕谷', '峡谷').replace('陕谷一', '峡谷—')
    value = re.sub(r'^峡谷\s*[-—一]\s*', '峡谷—', value)
    return value


def match_hero_name(text, entries, confidence):
    """印刷名优先：精确同名才接受，单字差只作为候选。"""
    cleaned = re.sub(r'[^\u4e00-\u9fff]', '', text or '')
    candidates = []
    if 1 <= len(cleaned) <= 6:
        for entry in entries:
            name = entry['name']
            if cleaned == name:
                distance = 0
            elif len(cleaned) >= 2 and len(cleaned) == len(name) \
                    and sum(a != b for a, b in zip(cleaned, name)) == 1:
                distance = 1
            else:
                continue
            candidates.append({'id': entry['id'], 'name': name, 'distance': distance})
        candidates.sort(key=lambda row: (row['distance'], row['name']))
    threshold = 0.72 if len(cleaned) >= 2 else 0.8
    accepted = None
    if candidates and candidates[0]['distance'] == 0 and confidence >= threshold:
        accepted = candidates[0]['name']
    nearest = [c for c in candidates if candidates and c['distance'] == candidates[0]['distance']]
    # 单字差可能有多个同长英雄（孙膜→孙权/孙策/孙膑），不唯一时不猜。
    guess = nearest[0]['name'] if not accepted and len(nearest) == 1 and confidence >= 0.35 else None
    return {'raw': cleaned or None, 'confidence': round(float(confidence), 3),
            'status': 'exact' if accepted else 'candidate' if guess else 'unknown',
            'name': accepted, 'guess': guess,
            'candidates': candidates[:4]}


def split_doubled_name(text):
    """加载页两行同名时 OCR 常合并成一个词（如“影影”）。"""
    value = re.sub(r'\s+', '', text or '')
    if len(value) == 2 and value[0] == value[1]:
        return value[0], value[1]
    if len(value) >= 4 and len(value) % 2 == 0 and value[:len(value) // 2] == value[len(value) // 2:]:
        return value[:len(value) // 2], value[len(value) // 2:]
    return value, ''


def _hero_entries():
    return [e for e in catalog()['entries'] if e['kind'] == 'hero']


def _reading_rank(raw, confidence, entries):
    if not raw:
        return -1, 0, None
    match = match_hero_name(raw, entries, confidence)
    if match['status'] == 'exact':
        rank = 3
    elif match['status'] == 'candidate':
        nearest = [c for c in match['candidates'] if c['distance'] == match['candidates'][0]['distance']]
        rank = 2 if len(nearest) == 1 else 1
    else:
        rank = 0
    return rank, confidence, match


def _read_loading_card(image, center, y1, y2, camp, entries):
    half_hero, half_color, half_nick = LOADING_HALF
    raw = _best(_tokens(image, (center - half_hero, y1 + 4, center + half_hero, y1 + 35), scale=8),
                lambda text: text or None, 0.2)
    colored = _best(_tokens(image, (center - half_color, y1 + 4, center + half_color, y1 + 35), scale=8, color=camp),
                    lambda text: text or None, 0.2)
    nick = _best(_tokens(image, (center - half_nick, y1 + 37, center + half_nick, y2), scale=8),
                 lambda text: text or None, 0.2)
    choices = [item for item in (raw, colored) if item]
    best = max(choices, key=lambda item: _reading_rank(item['raw'], item['confidence'], entries)[:2]) \
        if choices else None
    hero_text = best['raw'] if best else ''
    nick_text = nick['raw'] if nick else ''
    if hero_text and not nick_text:
        first, second = split_doubled_name(hero_text)
        if second:
            hero_text, nick_text = first, second
    return {'heroRaw': hero_text or None,
            'heroConfidence': round(float(best['confidence']), 3) if best else None,
            'nicknameRaw': nick_text or None,
            'nicknameConfidence': round(float(nick['confidence']), 3) if nick else None}


def _loading_score(candidate):
    return sum(2 if row.get('hero') else 1 if row.get('heroGuess') else 0
               for camp in ('blue', 'red') for row in candidate[camp])


def read_loading(image):
    entries = _hero_entries()
    result = {'blue': [], 'red': []}
    for camp in ('blue', 'red'):
        y1, y2 = LOADING_NAME[camp]
        for slot, center in enumerate(LOADING_CENTERS):
            card = _read_loading_card(image, center, y1, y2, camp, entries)
            hero = match_hero_name(card['heroRaw'] or '', entries, card['heroConfidence'] or 0)
            result[camp].append({
                'slot': slot, 'camp': camp,
                'heroRaw': card['heroRaw'], 'heroConfidence': card['heroConfidence'],
                'hero': hero['name'], 'heroGuess': hero['guess'], 'heroStatus': hero['status'],
                'heroCandidates': hero['candidates'],
                'nicknameRaw': card['nicknameRaw'], 'nicknameConfidence': card['nicknameConfidence'],
                'nickname': (card['nicknameRaw'] or '').strip() or None,
            })
    return result


def _group_lines(tokens, tolerance=0.013):
    rows = []
    for token in tokens:
        center = (token['box'][1] + token['box'][3]) / 2
        for row in rows:
            if abs(row['y'] - center) <= tolerance:
                row['tokens'].append(token)
                row['y'] = (row['y'] * (len(row['tokens']) - 1) + center) / len(row['tokens'])
                break
        else:
            rows.append({'y': center, 'tokens': [token]})
    result = []
    for row in rows:
        chosen = sorted(row['tokens'], key=lambda t: t['box'][0])
        result.append({'text': ''.join(t['text'] for t in chosen).replace(' ', ''),
                       'confidence': min(t['confidence'] for t in chosen),
                       'y': row['y']})
    return sorted(result, key=lambda row: row['y'])


def read_match(image):
    lines = _group_lines(_tokens(image, ROI['list_entry'], scale=3, det=True))
    mode_line = next((line for line in lines if '赛' in line['text'] or '峡谷' in line['text']), None)
    date_line = next((line for line in lines if parse_datetime(line['text'])), None)
    title_line = next((line for line in lines if line not in (mode_line, date_line)
                       and 2 <= len(line['text']) <= 12 and '本地' not in line['text']
                       and not re.search(r'\d{1,2}\s*/\s*\d{1,2}', line['text'])), None)
    mode = None
    if mode_line:
        mode = {'raw': mode_line['text'], 'value': normalize_mode(mode_line['text']),
                'confidence': round(mode_line['confidence'], 3)}
    title = None
    if title_line:
        title = {'raw': title_line['text'], 'value': title_line['text'],
                 'confidence': round(title_line['confidence'], 3)}
    date = None
    if date_line:
        parsed = parse_datetime(date_line['text'])
        if parsed:
            date = {'raw': date_line['text'], 'value': parsed,
                    'confidence': round(date_line['confidence'], 3)}
    return {'mode': mode, 'title': title, 'date': date}


def read_side_names(image):
    result = {'blue': [], 'red': []}
    for camp, box in (('blue', ROI['side_left']), ('red', ROI['side_right'])):
        tokens = _tokens(image, box, scale=3, det=True)
        rows = []
        for center in SIDE_ROW_CENTERS:
            y_center = center / REFERENCE[1]
            matching = [t for t in tokens
                        if abs((t['box'][1] + t['box'][3]) / 2 - y_center) < 0.028
                        and 1 <= len(re.sub(r'\s+', '', t['text'])) <= 10
                        and '点击' not in t['text']]
            if matching:
                best = max(matching, key=lambda t: (t['confidence'], len(t['text'])))
                rows.append({'nickname': best['text'].strip(),
                             'confidence': round(best['confidence'], 3), 'box': best['box']})
            else:
                rows.append(None)
        result[camp] = rows
    return result


def _white_groups(image, box, threshold=85, gap=7, min_width=4):
    x1, y1, x2, y2 = _px(box, image.size)
    pixels = np.asarray(image.crop((x1, y1, x2, y2)).convert('RGB')).astype(np.int16)
    mask = pixels.min(axis=2) > threshold
    columns = mask.any(axis=0)
    runs, start = [], None
    for index, value in enumerate(columns):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append([start, index])
            start = None
    if start is not None:
        runs.append([start, len(columns)])
    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= gap:
            merged[-1][1] = run[1]
        else:
            merged.append(list(run))
    return [(x1 + a, y1, x1 + b, y2) for a, b in merged if b - a >= min_width]


def _stat_icons(image):
    x1, y1, x2, y2 = _px((495, 714, 736, 754), image.size)
    pixels = np.asarray(image.crop((x1, y1, x2, y2)).convert('RGB')).astype(np.int16)
    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    masks = ((red > 140) & (green > 55) & (green < 140) & (blue < 90) & (red > blue + 60),
             (red > 120) & (blue > 140) & (green < 120) & (blue > green + 40))
    icons = []
    for mask in masks:
        columns = mask.any(axis=0)
        runs, start = [], None
        for index, value in enumerate(columns):
            if value and start is None:
                start = index
            elif not value and start is not None:
                runs.append([start, index])
                start = None
        if start is not None:
            runs.append([start, len(columns)])
        merged = []
        for run in runs:
            if merged and run[0] - merged[-1][1] <= 4:
                merged[-1][1] = run[1]
            else:
                merged.append(list(run))
        icons += [(x1 + a, x1 + b) for a, b in merged if b - a >= 4]
    icons.sort()
    # 最右侧的金币袋图标不属于四项属性。
    icons = [pair for pair in icons if pair[1] <= x1 + 235]
    return icons if len(icons) == 4 else None


def read_stats(image):
    icons = _stat_icons(image)
    if icons is None:
        return None
    boxes = []
    for index, (_, right) in enumerate(icons):
        end = icons[index + 1][0] - 3 if index + 1 < len(icons) else 730
        boxes.append((right + 1, 716, end, 752))
    values = []
    for box in boxes:
        token = _best(_tokens(image, box, scale=10, white=80), parse_stat_number, 0.25)
        values.append(token)
    if any(v is None for v in values):
        groups = _white_groups(image, ROI['stats'])
        if len(groups) != 4:
            return None
        values = []
        for group in groups:
            token = _best(_tokens(image, group, scale=10, white=85), parse_stat_number, 0.25)
            values.append(token)
        if any(v is None for v in values):
            return None
    return {
        'attack': {'raw': values[0]['raw'], 'value': values[0]['value'], 'confidence': values[0]['confidence']},
        'armor': {'raw': values[1]['raw'], 'value': values[1]['value'], 'confidence': values[1]['confidence']},
        'magicAttack': {'raw': values[2]['raw'], 'value': values[2]['value'], 'confidence': values[2]['confidence']},
        'magicResist': {'raw': values[3]['raw'], 'value': values[3]['value'], 'confidence': values[3]['confidence']},
    }


def read_topbar(image, clock=None):
    if clock is None:
        clock = _field(_tokens(image, ROI['clock_top'], scale=8, det=True), parse_clock, 0.4)
    blue = {
        'kills': _field(_tokens(image, ROI['kill_blue'], scale=8), parse_count, 0.35),
        'gold': _field(_tokens(image, ROI['gold_blue'], scale=6), parse_gold, 0.4),
    }
    red = {
        'kills': _field(_tokens(image, ROI['kill_red'], scale=8), parse_count, 0.35),
        'gold': _field(_tokens(image, ROI['gold_red'], scale=6), parse_gold, 0.4),
    }
    return {'clock': clock, 'blue': blue, 'red': red}


def read_outer_counters(image):
    """顶部两侧的团队累计计数：左侧蓝方为龙、塔，右侧红方为塔、龙。"""
    return {
        'blueDragon': _field(_tokens(image, ROI['outer_blue_dragon'], scale=8), parse_count, 0.5),
        'blueTower': _field(_tokens(image, ROI['outer_blue_tower'], scale=8), parse_count, 0.5),
        'redTower': _field(_tokens(image, ROI['outer_red_tower'], scale=8), parse_count, 0.5),
        'redDragon': _field(_tokens(image, ROI['outer_red_dragon'], scale=8), parse_count, 0.5),
    }


def _read_team_kda(image, box):
    """团队面板的 KDA 比记分板更小；白色阈值为 60 时最容易保住斜杠。"""
    variants = []
    for white in (None, 60, 70, 80, 95):
        for token in _tokens(image, box, scale=8, white=white):
            value = normalize_kda_text(token['text'])
            if value is not None:
                variants.append({'raw': token['text'], 'value': value,
                                 'confidence': round(float(token['confidence']), 3),
                                 'variant': 'raw' if white is None else f'white{white}'})
    return _consensus_kda(variants)


def _team_panel_row(image, camp, index):
    y = TEAM_PANEL_ROW_START + index * TEAM_PANEL_ROW_STEP
    kda_box = (TEAM_PANEL_KDA[camp][0], y, TEAM_PANEL_KDA[camp][1], y + TEAM_PANEL_ROW_HEIGHT)
    gold_box = (TEAM_PANEL_GOLD[camp][0], y, TEAM_PANEL_GOLD[camp][1], y + TEAM_PANEL_ROW_HEIGHT)
    kda = _read_team_kda(image, kda_box)
    gold = _best(_tokens(image, gold_box, scale=8), parse_gold, 0.25)
    return {'camp': camp, 'slot': index,
            'kda': kda['value'] if kda else None, 'kdaRaw': kda['raw'] if kda else None,
            'gold': gold['value'] if gold else None, 'goldRaw': gold['raw'] if gold else None,
            'confidence': min(kda['confidence'], gold['confidence']) if kda and gold else None}


def read_team_panel(image):
    """团队面板：双方各 5 行，逐人 KDA 与累计金币；行序按队伍槽位。

    首行作为开关门控，避免每个游戏帧都为 10 行做 OCR；蓝红各试一次，
    防止某一路首行偶发读不出就丢掉整秒。
    """
    first_blue = _team_panel_row(image, 'blue', 0)
    first_red = _team_panel_row(image, 'red', 0)
    blue_ready = first_blue['kda'] is not None and first_blue['gold'] is not None
    red_ready = first_red['kda'] is not None and first_red['gold'] is not None
    if not blue_ready and not red_ready:
        return None
    blue = [first_blue] + [_team_panel_row(image, 'blue', index) for index in range(1, 5)]
    red = [first_red] + [_team_panel_row(image, 'red', index) for index in range(1, 5)]
    readable = sum(1 for row in blue + red if row['kda'] is not None and row['gold'] is not None)
    if readable < 8:
        return None
    return {'blue': blue, 'red': red, 'readableRows': readable, 'complete': readable == 10}



def read_runes(image):
    token = _best(_tokens(image, ROI['runes'], scale=4),
                  lambda text: text if re.search(r'\d', text) else None, 0.5)
    if not token:
        return None
    parsed = parse_runes(token['raw'])
    if parsed:
        parsed['confidence'] = token['confidence']
    return parsed


def read_equipment(image):
    slots = []
    for index in range(6):
        x1 = ROI['equip_slot0'][0] + index * 60
        box = (x1, ROI['equip_slot0'][1], x1 + 45, ROI['equip_slot0'][3])
        crop = image.crop(_px(box, image.size))
        value = float(np.asarray(crop.convert('HSV'))[:, :, 2].mean())
        filled = value > 85
        status, candidates = ('empty' if not filled else 'unreadable'), []
        if filled:
            ranked = rank_icon(crop, 'equipment')
            top = ranked[0] if ranked else None
            margin = ranked[0]['similarity'] - ranked[1]['similarity'] if len(ranked) > 1 else 0
            if top and top['similarity'] >= 0.80 and margin >= 0.08:
                status, candidates = 'candidate', ranked[:2]
        slots.append({'index': index, 'filled': filled, 'status': status, 'candidates': candidates})
    return {'slots': slots, 'filled': sum(1 for slot in slots if slot['filled']),
            'note': '图标相似度只作候选；未达到 0.80/0.08 不提供名称。'}


def read_selected(image, include_stats=True):
    return {
        'kda': _field(_tokens(image, ROI['kda'], scale=10, white=85), parse_kda, 0.4),
        'gold': _field(_tokens(image, ROI['selected_gold'], scale=8, white=95), parse_gold, 0.4),
        'level': _field(_tokens(image, ROI['level'], scale=14, white=105), parse_level, 0.4),
        'stats': read_stats(image) if include_stats else None,
        'runes': read_runes(image) if include_stats else None,
        'equipment': read_equipment(image) if include_stats else None,
    }


def read_total_duration(image):
    return _field(_tokens(image, ROI['total_duration'], scale=8), parse_duration, 0.5)


def _digits_only(text):
    value = re.sub(r'\D', '', text or '')
    return int(value) if 1 <= len(value) <= 5 else None


def _scoreboard_probe(image):
    token = _best(_tokens(image, ROI['score_probe'], scale=6),
                  lambda text: text if re.search(r'\d\s*/\s*\d', text)
                  and len(re.findall(r'\d', text)) >= 4 else None, 0.4)
    return token


def _score_row(image, box):
    token = _best(_tokens(image, box, scale=8), _digits_only, 0.25)
    return token


def normalize_kda_text(text):
    value = re.sub(r'\s+', '', text or '')
    value = value.replace('／', '/').replace('．', '.').replace('：', ':')
    value = re.sub(r'[.:·•]', '/', value)
    parts = value.split('/')
    if len(parts) != 3:
        return None
    digits = []
    for part in parts:
        if part.isdecimal() and 1 <= len(part) <= 2:
            digits.append(int(part))
        elif len(part) == 1 and part in 'OoDQB':
            digits.append(0)
        elif len(part) == 1 and part in 'Il|':
            digits.append(1)
        else:
            return None
    return digits


def _consensus_kda(readings):
    if not readings:
        return None
    counts = Counter(tuple(row['value']) for row in readings)
    def rank(key):
        return counts[key], max(row['confidence'] for row in readings if tuple(row['value']) == key)
    best_value = max(counts, key=rank)
    best = max((row for row in readings if tuple(row['value']) == best_value),
               key=lambda row: row['confidence'])
    return {'raw': best['raw'], 'value': best['value'], 'confidence': best['confidence'],
            'variants': [dict(row) for row in readings]}


def _read_score_kda(image, box):
    variants = []
    for white in (None, 95, 80):
        for token in _tokens(image, box, scale=8, white=white):
            value = normalize_kda_text(token['text'])
            if value is not None:
                variants.append({'raw': token['text'], 'value': value,
                                 'confidence': round(float(token['confidence']), 3),
                                 'variant': 'raw' if white is None else f'white{white}'})
    return _consensus_kda(variants)


def _dedupe_repeated_name(text):
    """记分板名字会印两遍，整行 OCR 可能读成“百里守约百里守约”。"""
    if len(text) >= 2 and len(text) % 2 == 0 and text[:len(text) // 2] == text[len(text) // 2:]:
        return text[:len(text) // 2]
    return text


def _full_line_names(image, box):
    """整行 OCR 补充分字结果：半透明名字逐字检测时会拆成单字。"""
    names = []
    for token in _tokens(image, box, scale=4, det=False):
        text = re.sub(r'\s+', '', token['text'] or '')
        if not (1 <= len(text) <= 20 and all('\u4e00' <= char <= '\u9fff' for char in text)):
            continue
        names.append(text)
        deduped = _dedupe_repeated_name(text)
        if deduped != text:
            names.append(deduped)
    return names


def _read_score_identity(image, y, camp, pool, entries):
    """记分板行序会变（可能按金币排序），必须按印刷名字认人，不能按行号。"""
    box = ROI['score_blue_name'] if camp == 'blue' else ROI['score_red_name']
    tokens = _tokens(image, (box[0], y, box[2], y + 55), scale=3, det=True)
    texts = []
    for token in sorted(tokens, key=lambda token: -token['confidence']):
        text = re.sub(r'\s+', '', token['text'])
        if 1 <= len(text) <= 10 and all('\u4e00' <= char <= '\u9fff' for char in text):
            texts.append(text)
    full_names = _full_line_names(image, (box[0], y, box[2], y + 55))
    for text in texts:
        for row in pool:
            if row.get('nickname') and text == row['nickname']:
                return row, 'nickname-exact'
    for text in texts:
        if len(text) >= 2:
            for row in pool:
                if row.get('nickname') and text in row['nickname']:
                    return row, 'nickname-partial'
    hero_names = {entry['name'] for entry in entries}
    for text in texts:
        if text in hero_names:
            matches = [row for row in pool if text in (row.get('hero'), row.get('heroGuess'))]
            if len(matches) == 1:
                return matches[0], 'hero-exact'
    for text in full_names:
        for row in pool:
            if row.get('nickname') and text == row['nickname']:
                return row, 'nickname-exact'
    for text in full_names:
        if text in hero_names:
            matches = [row for row in pool if text in (row.get('hero'), row.get('heroGuess'))]
            if len(matches) == 1:
                return matches[0], 'hero-exact'
    for text in full_names:
        if len(text) >= 4:
            matches = [row for row in pool
                       if row.get('nickname') and len(row['nickname']) >= 2
                       and row['nickname'] in text]
            if len(matches) == 1:
                return matches[0], 'nickname-partial'
    for text in texts:
        if len(text) >= 2:
            matches = [row for row in pool
                       if (row.get('nickname') and len(row['nickname']) == len(text)
                           and sum(a != b for a, b in zip(text, row['nickname'])) == 1)]
            if len(matches) == 1:
                return matches[0], 'nickname-fuzzy'
    for text in texts:
        if len(text) >= 2:
            matches = [row for row in pool
                       if any(value and len(value) == len(text)
                              and sum(a != b for a, b in zip(text, value)) == 1
                              for value in (row.get('hero'), row.get('heroGuess')))]
            if len(matches) == 1:
                return matches[0], 'hero-fuzzy'
    return None, None


def _validate_kda(rows, kills, opponent_kills):
    if kills is None or opponent_kills is None:
        return {'valid': False, 'reason': '缺少顶部击杀，无法校验', 'inferred': 0}
    parsed = [row for row in rows if row]
    kills_sum = sum(row['value'][0] for row in parsed)
    deaths_sum = sum(row['value'][1] for row in parsed)
    inferred = 0
    if len(parsed) < len(rows):
        # 缺失行的 K/D 只有在团队 K/D 已被其余行对齐时才能确定为 0；助攻无法推断。
        if kills_sum == kills and deaths_sum == opponent_kills:
            for index, row in enumerate(rows):
                if not row:
                    rows[index] = {'raw': None, 'value': [0, 0, None], 'confidence': None, 'inferred': True}
                    inferred += 1
        else:
            return {'valid': False, 'reason': '存在未读出的行，且 K/D 合计与顶部不一致', 'inferred': 0}
    kills_total = sum(row['value'][0] for row in rows)
    deaths_total = sum(row['value'][1] for row in rows)
    valid = kills_total == kills and deaths_total == opponent_kills
    return {'valid': valid, 'reason': None if valid else 'K/D 合计与顶部击杀不一致',
            'kills': kills_total, 'deaths': deaths_total, 'inferred': inferred}


def read_scoreboard(image, topbar, lineups):
    probe = _scoreboard_probe(image)
    if not probe:
        return None
    blue_rows, red_rows, blue_kda, red_kda = [], [], [], []
    for index in range(MAX_SCOREBOARD_ROWS):
        y = 198 + index * SCORE_ROW_STEP
        blue_rows.append(_score_row(image, (ROI['score_blue_gold'][0], y, ROI['score_blue_gold'][2], y + 46)))
        red_rows.append(_score_row(image, (ROI['score_red_gold'][0], y, ROI['score_red_gold'][2], y + 46)))
        blue_kda.append(_read_score_kda(image, (ROI['score_blue_kda'][0], y, ROI['score_blue_kda'][2], y + 46)))
        red_kda.append(_read_score_kda(image, (ROI['score_red_kda'][0], y, ROI['score_red_kda'][2], y + 46)))
    blue_kills = (topbar['blue']['kills'] or {}).get('value')
    red_kills = (topbar['red']['kills'] or {}).get('value')
    blue_check = _validate_kda(blue_kda, blue_kills, red_kills)
    red_check = _validate_kda(red_kda, red_kills, blue_kills)
    snapshot = {
        'probe': {'raw': probe['raw'], 'confidence': probe['confidence']},
        'blue': {'rows': blue_rows, 'kdaRows': blue_kda, 'kdaValid': blue_check['valid'],
                 'kdaReason': blue_check['reason'], 'kdaInferred': blue_check.get('inferred', 0),
                 'kdaKills': blue_check.get('kills'), 'kdaDeaths': blue_check.get('deaths'),
                 'sum': None, 'team': (topbar['blue']['gold'] or {}).get('value'), 'valid': False},
        'red': {'rows': red_rows, 'kdaRows': red_kda, 'kdaValid': red_check['valid'],
                'kdaReason': red_check['reason'], 'kdaInferred': red_check.get('inferred', 0),
                'kdaKills': red_check.get('kills'), 'kdaDeaths': red_check.get('deaths'),
                'sum': None, 'team': (topbar['red']['gold'] or {}).get('value'), 'valid': False},
        'valid': False,
        'kdaValidated': blue_check['valid'] and red_check['valid'],
        'blueKills': blue_kills, 'redKills': red_kills,
    }
    for camp, rows in (('blue', blue_rows), ('red', red_rows)):
        values = [row['value'] if row else None for row in rows]
        summary = snapshot[camp]
        summary['values'] = values
        if any(value is None for value in values):
            summary['reason'] = '存在未读出的行'
            continue
        summary['sum'] = sum(values)
        team = summary['team']
        if team is not None:
            if all(value <= team * 1.5 for value in values) and abs(summary['sum'] - team) <= max(60, team * 0.06):
                summary['valid'] = True
                summary['difference'] = summary['sum'] - team
            else:
                summary['reason'] = '与顶部团队金币不一致'
        else:
            summary['reason'] = '缺少顶部团队金币，无法校验'
    snapshot['valid'] = snapshot['blue']['valid'] and snapshot['red']['valid']
    if snapshot['valid']:
        entries = _hero_entries()
        players = []
        for camp, summary, kda_rows in (('blue', snapshot['blue'], blue_kda),
                                        ('red', snapshot['red'], red_kda)):
            pool = [row for row in lineups.get(camp, []) if row.get('slot') is not None]
            identities = []
            for row_index in range(MAX_SCOREBOARD_ROWS):
                identity, method = _read_score_identity(
                    image, 198 + row_index * SCORE_ROW_STEP, camp, pool, entries)
                if identity is not None:
                    pool.remove(identity)
                identities.append((identity, method))
            unmatched = [index for index, (identity, _) in enumerate(identities) if identity is None]
            if len(unmatched) == 1 and len(pool) == 1:
                identities[unmatched[0]] = (pool[0], 'elimination')
            for row_index, (identity, method) in enumerate(identities):
                value = summary['values'][row_index]
                kda_row = kda_rows[row_index] if row_index < len(kda_rows) else None
                nickname = None
                if identity and identity.get('nickname') and (
                        identity.get('nicknameConfidence') is None or identity['nicknameConfidence'] >= 0.6):
                    nickname = identity['nickname']
                player = {'camp': camp, 'row': row_index,
                          'slot': identity.get('slot') if identity else None,
                          'hero': (identity.get('hero') or identity.get('heroGuess')) if identity else None,
                          'nickname': nickname,
                          'identity': method,
                          'gold': value,
                          'kda': kda_row['value'] if kda_row else None,
                          'kdaInferred': bool(kda_row and kda_row.get('inferred')),
                          'kdaValidated': summary['kdaValid']}
                if summary['kdaValid'] and kda_row:
                    player['kills'], player['deaths'], player['assists'] = kda_row['value']
                players.append(player)
        snapshot['players'] = players
    return snapshot


def _refine_scoreboard_kda(path, snapshot, info):
    """KDA 行被底部面板遮挡或淡出时，在快照前后 1.4 秒内重扫缺失行。"""
    missing = {camp: [index for index, row in enumerate(snapshot[camp]['kdaRows']) if not row]
               for camp in ('blue', 'red')}
    if not any(missing.values()):
        return False
    collected = {camp: {index: [] for index in missing[camp]} for camp in ('blue', 'red')}
    for _, image in _iter_window(path, snapshot['videoTime'] - 0.7, 1.4, 5, info):
        if not _scoreboard_probe(image):
            continue
        for camp in ('blue', 'red'):
            for index in missing[camp]:
                y = 198 + index * SCORE_ROW_STEP
                box = (ROI[f'score_{camp}_kda'][0], y, ROI[f'score_{camp}_kda'][2], y + 46)
                reading = _read_score_kda(image, box)
                if reading:
                    collected[camp][index].append(reading)
    changed = False
    for camp in ('blue', 'red'):
        for index, readings in collected[camp].items():
            if readings:
                snapshot[camp]['kdaRows'][index] = _consensus_kda(readings)
                changed = True
    if not changed:
        return False
    blue_kills, red_kills = snapshot.get('blueKills'), snapshot.get('redKills')
    blue_check = _validate_kda(snapshot['blue']['kdaRows'], blue_kills, red_kills)
    red_check = _validate_kda(snapshot['red']['kdaRows'], red_kills, blue_kills)
    for camp, check in (('blue', blue_check), ('red', red_check)):
        summary = snapshot[camp]
        summary['kdaValid'] = check['valid']
        summary['kdaReason'] = check['reason']
        summary['kdaInferred'] = check.get('inferred', 0)
        summary['kdaKills'] = check.get('kills')
        summary['kdaDeaths'] = check.get('deaths')
    snapshot['kdaValidated'] = blue_check['valid'] and red_check['valid']
    for player in snapshot.get('players', []):
        summary = snapshot[player['camp']]
        kda_row = summary['kdaRows'][player['row']]
        player['kda'] = kda_row['value'] if kda_row else None
        player['kdaInferred'] = bool(kda_row and kda_row.get('inferred'))
        player['kdaValidated'] = summary['kdaValid']
        if player['kdaValidated'] and kda_row:
            player['kills'], player['deaths'], player['assists'] = kda_row['value']
        else:
            for key in ('kills', 'deaths', 'assists'):
                player.pop(key, None)
    return True


def _match_score(match):
    if not match:
        return -1
    score = 0.0
    if match.get('title'):
        score += 2 + len(match['title']['value']) / 10 + match['title']['confidence']
    if match.get('mode'):
        score += 2
    if match.get('date'):
        score += 2
    return score


def _classify(image):
    clock = _best(_tokens(image, ROI['clock_top'], scale=8, det=True), parse_clock, 0.4)
    if clock:
        return 'game', clock
    result = _tokens(image, ROI['postgame_result'], scale=3, det=True)
    if any(('胜利' in token['text'] or '失败' in token['text']) for token in result):
        return 'postgame', None
    buttons = _tokens(image, ROI['postgame_buttons'], scale=2, det=True)
    if any(('返回大厅' in token['text'] or '再看一局' in token['text']
            or '返回房间' in token['text']) for token in buttons):
        return 'postgame', None
    vs = _tokens(image, ROI['center_vs'], scale=2)
    if vs and vs[0]['confidence'] >= 0.5 and re.search(r'VS', vs[0]['text'], re.I):
        return 'loading', None
    menu = _tokens(image, ROI['list_menu'], scale=3)
    if menu and menu[0]['confidence'] >= 0.5 and re.search(r'本地|回放|观战', menu[0]['text']):
        return 'replay_list', None
    return 'unknown', None


def probe_video(path):
    if not os.path.isfile(path):
        raise VideoOCRError('视频文件不存在')
    command = [media_tools.ffprobe(), '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height,avg_frame_rate,codec_name',
               '-show_entries', 'format=duration,size', '-of', 'json', path]
    try:
        output = subprocess.run(command, capture_output=True, check=True)
    except FileNotFoundError as error:
        raise VideoOCRError('需要 ffprobe；请安装 ffmpeg 并加入 PATH') from error
    except subprocess.CalledProcessError as error:
        raise VideoOCRError('ffprobe 无法读取该视频') from error
    try:
        data = json.loads(output.stdout.decode('utf-8'))
        stream = data['streams'][0]
        duration = float(data['format']['duration'])
        width, height = int(stream['width']), int(stream['height'])
        numerator, denominator = (stream.get('avg_frame_rate') or '0/1').split('/')
        fps = float(numerator) / float(denominator) if float(denominator) else None
    except (KeyError, IndexError, ValueError) as error:
        raise VideoOCRError('视频流信息不完整') from error
    if width < 640 or height < 360:
        raise VideoOCRError('录屏分辨率过低，HUD 文字无法可靠读取')
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'name': os.path.basename(path), 'path': os.path.abspath(path),
            'size': int(data['format'].get('size', os.path.getsize(path))),
            'duration': round(duration, 3), 'width': width, 'height': height,
            'fps': round(fps, 3) if fps else None, 'sha256': digest.hexdigest(),
            'codec': stream.get('codec_name')}


def _open_frame_stream(command):
    """启动 ffmpeg 帧流子进程，并在后台线程持续读 stderr。

    stderr 管道不排空时，损坏视频每秒都可能输出解码错误：管道写满后
    ffmpeg 阻塞在写 stderr 上，调用方读 stdout 就永远等不到数据——
    整个 OCR 单 worker 队列会永久卡死。返回 (process, stderr_text)。
    """
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as error:
        raise VideoOCRError('需要 ffmpeg；请安装并加入 PATH') from error
    chunks = []

    def drain():
        try:
            for chunk in iter(lambda: process.stderr.read(65536), b''):
                chunks.append(chunk)
        except (OSError, ValueError):
            pass

    threading.Thread(target=drain, name='ffmpeg-stderr', daemon=True).start()

    def stderr_text():
        return b''.join(chunks).decode('utf-8', 'replace').strip()

    return process, stderr_text


def iter_frames(path, fps, info=None):
    info = info or probe_video(path)
    height = max(2, round(info['height'] * SAMPLE_WIDTH / info['width'] / 2) * 2)
    command = [media_tools.ffmpeg(), '-v', 'error', '-i', path,
               '-vf', f'fps={fps},scale={SAMPLE_WIDTH}:{height}',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    process, stderr_text = _open_frame_stream(command)
    size = SAMPLE_WIDTH * height * 3
    index = 0
    try:
        while index < MAX_SAMPLES:
            buffer = process.stdout.read(size)
            if len(buffer) < size:
                break
            frame = np.frombuffer(buffer, dtype=np.uint8).reshape(height, SAMPLE_WIDTH, 3)
            yield round(index / fps, 3), Image.fromarray(frame)
            index += 1
    finally:
        process.stdout.close()
        process.wait()
        message = stderr_text()
        if index == 0 and process.returncode not in (0, 1):
            raise VideoOCRError(f'ffmpeg 解码失败：{message[:200]}')


def _iter_window(path, start, duration, fps, info):
    """短窗口重扫：只用于记分板快照附近的补充读取。"""
    height = max(2, round(info['height'] * SAMPLE_WIDTH / info['width'] / 2) * 2)
    command = [media_tools.ffmpeg(), '-v', 'error', '-ss', f'{max(0, start):.3f}', '-t', f'{duration:.3f}',
               '-i', path, '-vf', f'fps={fps},scale={SAMPLE_WIDTH}:{height}',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    process, stderr_text = _open_frame_stream(command)
    size = SAMPLE_WIDTH * height * 3
    index = 0
    try:
        while index < 60:
            buffer = process.stdout.read(size)
            if len(buffer) < size:
                break
            frame = np.frombuffer(buffer, dtype=np.uint8).reshape(height, SAMPLE_WIDTH, 3)
            yield round(start + index / fps, 3), Image.fromarray(frame)
            index += 1
    finally:
        process.stdout.close()
        process.wait()
        stderr_text()


def _scenes(points, duration):
    scenes = []
    for point in points:
        if scenes and scenes[-1]['type'] == point['scene']:
            scenes[-1]['end'] = point['time']
        else:
            scenes.append({'type': point['scene'], 'start': point['time'], 'end': point['time']})
    for index, scene in enumerate(scenes):
        scene['end'] = scenes[index + 1]['start'] if index + 1 < len(scenes) else duration
    # 1–2 秒的识别空档通常是技能特效遮住计时器，并入前一场景而不是单列。
    for index in range(1, len(scenes) - 1):
        if scenes[index]['type'] == 'unknown' and scenes[index]['end'] - scenes[index]['start'] < 3:
            scenes[index]['type'] = scenes[index - 1]['type']
    merged = []
    for scene in scenes:
        if merged and merged[-1]['type'] == scene['type']:
            merged[-1]['end'] = scene['end']
        else:
            merged.append(dict(scene))
    for scene in merged:
        scene['start'] = round(scene['start'], 3)
        scene['end'] = round(scene['end'], 3)
    return merged


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def build_time_mapping(samples):
    pairs = [(s['videoTime'], s['gameTime']) for s in samples if s['gameTime'] is not None]
    if not pairs:
        return {'offset': None, 'speed': None, 'segments': [], 'stalls': [], 'jumps': [], 'samples': 0}
    offsets = [game - video for video, game in pairs]
    offset = round(_median(offsets), 3)
    rates, stalls, jumps = [], [], []
    for (pv, pg), (cv, cg) in zip(pairs, pairs[1:]):
        dv, dg = cv - pv, cg - pg
        if dv <= 0:
            continue
        if dg == 0 and dv >= 2:
            stalls.append({'start': round(pv, 2), 'end': round(cv, 2), 'seconds': round(dv, 2)})
        elif dg / dv > 2.5:
            jumps.append({'start': round(pv, 2), 'end': round(cv, 2), 'delta': round(dg - dv, 2)})
        else:
            rates.append((pv, cv, dg / dv))
    segments = []
    for start, end, rate in rates:
        previous_rate = segments[-1]['rates'][-1] if segments else None
        if segments and abs(previous_rate - rate) <= 0.08 and abs(segments[-1]['end'] - start) <= 3:
            segments[-1]['end'] = end
            segments[-1]['rates'].append(rate)
        else:
            segments.append({'start': start, 'end': end, 'rates': [rate]})
    for segment in segments:
        segment['rate'] = round(_median(segment['rates']), 3)
        segment.pop('rates')
    speed = round(_median([row[2] for row in rates]), 3) if rates else None
    return {'offset': offset, 'speed': speed, 'segments': segments,
            'stalls': stalls, 'jumps': jumps, 'samples': len(pairs)}


def _stabilize_counters(samples):
    """团队击杀与团队经济都是累计值，回退读数按误读丢弃，原文仍保留。"""
    last = {'blue': {'kills': None, 'gold': None}, 'red': {'kills': None, 'gold': None}}
    dropped = 0
    for sample in samples:
        for camp in ('blue', 'red'):
            for key in ('kills', 'gold'):
                reading = sample[camp][key]
                value = reading.get('value')
                if value is None:
                    continue
                previous = last[camp][key]
                if previous is not None and value < previous:
                    reading['suspect'] = True
                    reading['note'] = '低于前值，按误读丢弃'
                    reading['value'] = None
                    dropped += 1
                else:
                    last[camp][key] = value
    return dropped


def _kill_events(samples):
    events, last = [], {'blue': None, 'red': None}
    for sample in samples:
        if sample['gameTime'] is None:
            continue
        for camp in ('blue', 'red'):
            reading = sample[camp]['kills']
            value = reading['value'] if reading else None
            if value is None:
                continue
            if last[camp] is None:
                last[camp] = value
            elif value > last[camp]:
                events.append({'gameTime': sample['gameTime'], 'camp': camp,
                               'delta': value - last[camp], 'after': value,
                               'precision': 'sample'})
                last[camp] = value
    return events


def _selection_segments(samples):
    segments = []
    previous = None
    for sample in samples:
        selected = sample.get('selected')
        if not selected:
            continue
        level = (selected.get('level') or {}).get('value')
        kda = (selected.get('kda') or {}).get('value')
        stats = selected.get('stats')
        gold = (selected.get('gold') or {}).get('value')
        switch = previous is None
        if previous is not None:
            previous_level, previous_kda, previous_stats, previous_gold = previous
            if level is not None and previous_level is not None and level < previous_level:
                switch = True
            if kda and previous_kda and any(cur < prev for cur, prev in zip(kda, previous_kda)):
                switch = True
            if stats and previous_stats and level is not None and previous_level is not None:
                jump = max(abs(stats[key]['value'] - previous_stats[key]['value']) / max(1, previous_stats[key]['value'])
                           for key in ('attack', 'armor', 'magicResist'))
                if jump > 0.3 and level <= previous_level + 1:
                    switch = True
            # 可用金币下降可能只是买装备；只有同时换了 KDA 才当作观战目标切换。
            if gold is not None and previous_gold is not None and gold < previous_gold * 0.85 \
                    and kda and previous_kda and kda != previous_kda:
                switch = True
        if switch:
            segments.append({'start': sample['videoTime'], 'end': sample['videoTime'],
                             'samples': 0, 'levelFirst': level, 'levelLast': level,
                             'kdaFirst': kda, 'kdaLast': kda,
                             'goldFirst': (selected.get('gold') or {}).get('value'),
                             'goldLast': (selected.get('gold') or {}).get('value'),
                             'stats': stats, 'hero': None})
        segment = segments[-1]
        segment['end'] = sample['videoTime']
        segment['samples'] += 1
        segment['levelLast'] = level if level is not None else segment['levelLast']
        segment['kdaLast'] = kda if kda else segment['kdaLast']
        if (selected.get('gold') or {}).get('value') is not None:
            segment['goldLast'] = selected['gold']['value']
        if stats:
            segment['stats'] = stats
        if selected.get('runes'):
            segment['runes'] = selected['runes']
        if selected.get('equipment'):
            segment['equipment'] = selected['equipment']
        previous = (level, kda, stats, (selected.get('gold') or {}).get('value'))
    for segment in segments:
        segment['start'] = round(segment['start'], 2)
        segment['end'] = round(segment['end'], 2)
    return segments


def _downsample(timeline, limit=120):
    if len(timeline) <= limit:
        return timeline
    step = (len(timeline) - 1) / (limit - 1)
    return [timeline[round(index * step)] for index in range(limit)]


def _compact_sample(video_time, topbar, selected=None):
    sample = {'videoTime': round(video_time, 3),
              'gameTime': topbar['clock']['value'],
              'clock': topbar['clock'],
              'blue': {'kills': topbar['blue']['kills'], 'gold': topbar['blue']['gold']},
              'red': {'kills': topbar['red']['kills'], 'gold': topbar['red']['gold']}}
    if selected:
        readable = any((selected.get(key) or {}).get('value') is not None
                       for key in ('kda', 'gold', 'level')) \
            or bool(selected.get('stats') or selected.get('runes')
                    or (selected.get('equipment') or {}).get('filled'))
        if readable:
            sample['selected'] = selected
    return sample


def _merge_lineups(loading, side_names):
    entries = {'blue': [], 'red': []}
    for camp in ('blue', 'red'):
        cards = loading.get(camp, []) if loading else []
        names = side_names.get(camp, []) if side_names else []
        used = set()
        for card in cards:
            nickname = card.get('nickname')
            match = None
            for index, row in enumerate(names):
                if index in used or not row:
                    continue
                if nickname and row['nickname'] == nickname:
                    match = index
                    break
            if match is None and nickname:
                for index, row in enumerate(names):
                    if index in used or not row:
                        continue
                    if len(nickname) >= 2 and len(row['nickname']) == len(nickname) \
                            and sum(a != b for a, b in zip(row['nickname'], nickname)) == 1:
                        match = index
                        break
            if match is not None:
                used.add(match)
                card['panelSlot'] = match
                card['nicknameMatch'] = 'exact' if names[match]['nickname'] == nickname else 'fuzzy'
                card['nickname'] = card.get('nickname') or names[match]['nickname']
            else:
                card['panelSlot'] = None
                card['nicknameMatch'] = None
            entries[camp].append(card)
        # 五人加载页与五条侧栏各剩一个未匹配项时，它们只能是同一名队员。
        unmatched_cards = [card for card in cards if card.get('panelSlot') is None]
        unmatched_side = [index for index, row in enumerate(names) if index not in used and row]
        if len(cards) >= 5 and len(unmatched_cards) == 1 and len(unmatched_side) == 1:
            unmatched_cards[0]['panelSlot'] = unmatched_side[0]
            unmatched_cards[0]['nicknameMatch'] = 'elimination'
            used.add(unmatched_side[0])
        # 加载页已有五人时，侧栏多出的一个未匹配名字更可能是同一人的误读，不再补第六行。
        if len(cards) >= 5:
            names = []
        for index, row in enumerate(names):
            if index in used or not row:
                continue
            entries[camp].append({'slot': None, 'camp': camp, 'panelSlot': index,
                                  'nickname': row['nickname'], 'nicknameRaw': row['nickname'],
                                  'nicknameConfidence': row['confidence'],
                                  'heroRaw': None, 'hero': None, 'heroGuess': None,
                                  'heroStatus': 'unknown', 'heroCandidates': [],
                                  'nicknameMatch': 'side-only'})
        def order(row):
            slot = row.get('panelSlot')
            return (slot is None, slot if slot is not None else 9,
                    row.get('slot') if row.get('slot') is not None else 9)
        entries[camp].sort(key=order)
    return entries


def _near_name(raw, name):
    return len(raw) == len(name) >= 2 and sum(a != b for a, b in zip(raw, name)) == 1


def cross_check_abc(report, abc_path):
    """用同一局的 .abc 十人英雄集合补全 OCR 未读出的英雄。

    .abc 只提供英雄 ID/名称，不确认阵营；阵营分组来自录屏。前五/后五的
    顺序与游戏内侧栏一致属于本样本的推断，因此补全结果标记为交叉核对。
    """
    from pathlib import Path
    from replay_parser import inspect_replay
    path = Path(abc_path)
    if not path.is_file():
        raise VideoOCRError('找不到 .abc 文件')
    try:
        probe = inspect_replay(path.read_bytes())
    except (OSError, ValueError) as error:
        return {'status': 'error', 'note': f'.abc 未通过只读解析：{error}'}
    roster = [block['heroName'] for block in probe.get('blocks', []) if block.get('heroName')]
    if len(roster) != 10:
        return {'status': 'unavailable', 'note': '未从 .abc 读到十名英雄，未做补全'}
    lineups = report['lineups']
    known = {row['hero'] for camp in ('blue', 'red') for row in lineups[camp] if row.get('hero')}
    resolved = []
    # 1) 单字差候选在 .abc 集合里唯一时才补。
    for camp in ('blue', 'red'):
        for row in lineups[camp]:
            if row.get('hero') or not row.get('heroRaw'):
                continue
            matches = [name for name in set(roster) - known if _near_name(row['heroRaw'], name)]
            if len(matches) == 1:
                row['hero'], row['heroStatus'], row['heroSource'] = matches[0], 'cross-checked', 'abc-distance'
                known.add(matches[0])
                resolved.append({'camp': camp, 'slot': row.get('slot'), 'raw': row['heroRaw'],
                                 'hero': matches[0], 'method': 'abc-distance'})
    # 2) .abc 前五/后五与两侧已知英雄一致时，按顺序补剩余的未知行。
    first, second = roster[:5], roster[5:]
    blue_known = {row['hero'] for row in lineups['blue'] if row.get('hero')}
    red_known = {row['hero'] for row in lineups['red'] if row.get('hero')}
    if blue_known <= set(first) and red_known <= set(second):
        for camp, group, known_side in (('blue', first, blue_known), ('red', second, red_known)):
            unknown = [row for row in lineups[camp] if not row.get('hero')]
            remaining = [name for name in group if name not in known_side]
            if len(unknown) == 1 and len(remaining) == 1:
                row = unknown[0]
                row['hero'], row['heroStatus'], row['heroSource'] = remaining[0], 'cross-checked', 'abc-order'
                known.add(remaining[0])
                resolved.append({'camp': camp, 'slot': row.get('slot'), 'raw': row.get('heroRaw'),
                                 'hero': remaining[0], 'method': 'abc-order'})
    assigned = {row['hero'] for camp in ('blue', 'red') for row in lineups[camp] if row.get('hero')}
    matched = assigned == set(roster)
    if report.get('pov') and not report['pov'].get('hero'):
        for camp in ('blue', 'red'):
            for row in lineups[camp]:
                if row.get('nickname') == report['pov'].get('nickname') and row.get('hero'):
                    report['pov']['hero'] = row['hero']
                    report['pov']['heroStatus'] = row.get('heroStatus')
                    report['pov']['heroSource'] = row.get('heroSource')
    for snapshot in report.get('scoreboard', {}).get('snapshots', []):
        for player in snapshot.get('players', []):
            for row in lineups.get(player['camp'], []):
                if row.get('slot') == player['slot'] and row.get('hero'):
                    player['hero'] = row['hero']
    for panel in report.get('teamPanel', {}).get('samples', []):
        for camp in ('blue', 'red'):
            by_panel = {row.get('panelSlot'): row for row in lineups.get(camp, [])}
            for player in panel.get(camp, []):
                row = by_panel.get(player.get('slot'))
                if not row:
                    continue
                if row.get('hero') or row.get('heroGuess'):
                    player['hero'] = row.get('hero') or row.get('heroGuess')
                if row.get('nickname'):
                    player['nickname'] = row['nickname']
    report['coverage']['lineupHeroes'] = sum(
        1 for camp in ('blue', 'red') for row in lineups[camp] if row.get('hero') or row.get('heroGuess'))
    result = {'status': 'matched' if matched else 'mismatch', 'file': path.name,
              'heroes': roster, 'resolved': resolved,
              'missing': sorted(set(roster) - assigned), 'extra': sorted(assigned - set(roster)),
              'campOrder': 'inferred' if resolved and any(r['method'] == 'abc-order' for r in resolved) else 'unknown',
              'note': '.abc 只读解析，不写数据库；阵营分组来自录屏，前五/后五顺序为推断。'}
    if not any(row.get('heroStatus') == 'candidate' for camp in ('blue', 'red') for row in lineups[camp]):
        report['warnings'] = [warning for warning in report['warnings'] if '仅差一个字' not in warning]
    if matched:
        report['warnings'].append(
            '已用同局 .abc 的十人英雄集合交叉核对；未读出的英雄按集合与侧栏顺序补全，仍需人工确认。')
    else:
        report['warnings'].append('录屏阵容与 .abc 十人集合不一致，未采用补全结果。')
    return result


def _coverage(samples, lineups, snapshots):
    def count(path):
        total = 0
        for sample in samples:
            value = sample
            for key in path:
                value = (value or {}).get(key) if isinstance(value, dict) else None
            if value not in (None, ''):
                total += 1
        return total
    heroes = sum(1 for camp in ('blue', 'red') for row in lineups[camp] if row.get('hero') or row.get('heroGuess'))
    return {'samples': len(samples),
            'clock': count(('clock', 'value')),
            'blueKills': count(('blue', 'kills', 'value')),
            'redKills': count(('red', 'kills', 'value')),
            'blueGold': count(('blue', 'gold', 'value')),
            'redGold': count(('red', 'gold', 'value')),
            'selectedPanel': sum(1 for s in samples if s.get('selected')),
            'selectedStats': sum(1 for s in samples if (s.get('selected') or {}).get('stats')),
            'selectedEquipment': sum(1 for s in samples if (s.get('selected') or {}).get('equipment')),
            'selectedRunes': sum(1 for s in samples if (s.get('selected') or {}).get('runes')),
            'lineupHeroes': heroes,
            'scoreboardSnapshots': len([s for s in snapshots if s.get('valid')]),
            'scoreboardKdaValid': len([s for s in snapshots if s.get('valid') and s.get('kdaValidated')]),
            'scoreboardRejected': len([s for s in snapshots if not s.get('valid')])}


def _hero_label(row):
    if row.get('hero'):
        return row['hero']
    if row.get('heroGuess'):
        return row['heroGuess'] + '?'
    return '英雄?'


def _nickname_label(row):
    nickname = row.get('nickname')
    confidence = row.get('nicknameConfidence')
    if nickname and (confidence is None or confidence >= 0.6):
        return nickname
    return '昵称?'


def analyze_video(path, fps=1.0, progress=None, evidence_dir=None):
    if not 0.2 <= fps <= 10:
        raise VideoOCRError('采样帧率需在 0.2–10 之间')
    info = probe_video(path)
    with _layout_lock:
        saved = set_layout(info['width'], info['height'])
        try:
            return _analyze_video(path, fps, progress, evidence_dir, info)
        finally:
            restore_layout(saved)


def _analyze_video(path, fps, progress, evidence_dir, info):
    warnings = []
    if LAYOUT == LAYOUT_20X9:
        warnings.append('录屏为 20:9 长屏布局，已使用 20:9 校准；底部团队面板可能被裁切。')
    elif abs(info['width'] / info['height'] - 16 / 9) > 0.02:
        warnings.append('录屏不是 16:9，固定布局坐标可能偏移。')
    if info.get('fps') and info['fps'] < 24:
        warnings.append('录屏帧率低于 24fps，小字识别率可能下降。')
    points, samples, snapshots = [], [], []
    loading, loading_frame, list_frame, match = None, None, None, None
    side_candidates, total_duration, outer = [], None, None
    total_readings = []
    score_frame, last_game = None, None
    team_panel_samples, team_panel_frame = [], None
    panel_fallback_frames = []
    postgame_frames = []
    last_postgame = None
    loading_tries = 0
    for video_time, image in iter_frames(path, fps, info):
        scene, clock = _classify(image)
        points.append({'time': video_time, 'scene': scene})
        if scene == 'postgame':
            if last_postgame is None or video_time - last_postgame >= 4:
                postgame_frames.append((video_time, image.copy()))
                last_postgame = video_time
            continue
        if scene == 'replay_list':
            # 列表页开头可能被“确定观看”弹窗遮住，逐帧取信息最完整的一张。
            candidate = read_match(image)
            if _match_score(candidate) > _match_score(match):
                match = candidate
                list_frame = image
        elif scene == 'loading' and loading_tries < 2:
            loading_tries += 1
            candidate = read_loading(image)
            readable = _loading_score(candidate)
            previous = _loading_score(loading) if loading else -1
            if readable > previous:
                loading, loading_frame = candidate, image
        elif scene == 'game':
            last_game = image
            topbar = read_topbar(image, clock)
            if topbar['clock']['value'] is None:
                continue
            selected = read_selected(image, include_stats=len(samples) % 5 == 0) \
                if SUPPORTS_SELECTED else {}
            samples.append(_compact_sample(video_time, topbar, selected))
            panel = read_team_panel(image)
            if panel:
                panel['videoTime'] = round(video_time, 3)
                panel['gameTime'] = topbar['clock']['value']
                team_panel_samples.append(panel)
                if team_panel_frame is None:
                    team_panel_frame = image
            elif LAYOUT == LAYOUT_20X9 and len(panel_fallback_frames) < 6:
                # 20:9 长屏的底部面板更矮；快速 OCR 读不出时每 60 秒留一帧给 Mimo。
                # 开局前 20 秒常有“选中英雄”面板而非团队面板，不取样。
                game_time = topbar['clock']['value']
                if isinstance(game_time, int) and 20 <= game_time <= 3600 and (
                        not panel_fallback_frames
                        or video_time - panel_fallback_frames[-1][0] >= 60):
                    panel_fallback_frames.append((round(video_time, 3),
                                                  game_time, image.copy()))
            if len(samples) in (1, 11):
                side_candidates.append(image)
            if outer is None and SUPPORTS_OUTER:
                outer = read_outer_counters(image)
            # 回放总时长在开局前几秒会从 00:00 递增到真实长度，取前 6 次读数的最大值。
            if SUPPORTS_TOTAL_DURATION and len(total_readings) < 6:
                value = read_total_duration(image)['value']
                if value:
                    total_readings.append(value)
                    total_duration = max(total_readings)
            snapshot = read_scoreboard(image, topbar, loading or {'blue': [], 'red': []}) \
                if SUPPORTS_SCOREBOARD else None
            if snapshot:
                snapshot['videoTime'] = round(video_time, 3)
                snapshot['gameTime'] = topbar['clock']['value']
                previous = snapshots[-1] if snapshots else None
                if not previous or previous.get('valid') != snapshot.get('valid') or \
                        previous.get('blue', {}).get('values') != snapshot['blue'].get('values') or \
                        previous.get('red', {}).get('values') != snapshot['red'].get('values'):
                    snapshots.append(snapshot)
                    if snapshot.get('valid') and score_frame is None:
                        score_frame = image
        if progress and len(points) % 30 == 0:
            progress(len(points), info['duration'])
    if not samples:
        raise VideoOCRError('未识别到对局画面（顶部计时器未出现）')
    side_names, best_side = None, -1
    for frame in side_candidates:
        names = read_side_names(frame)
        score = sum(1 for camp in ('blue', 'red') for row in names[camp] if row)
        if score > best_side:
            side_names, best_side = names, score
    lineups = _merge_lineups(loading, side_names)
    for panel in team_panel_samples:
        for camp in ('blue', 'red'):
            by_slot = {row.get('slot'): row for row in lineups.get(camp, [])}
            by_panel = {row.get('panelSlot'): row for row in lineups.get(camp, [])}
            for player in panel[camp]:
                row = by_panel.get(player['slot']) or by_slot.get(player['slot'])
                player['hero'] = (row or {}).get('hero') or (row or {}).get('heroGuess')
                player['nickname'] = (row or {}).get('nickname')
                player['identity'] = 'slot-order'
    if team_panel_samples:
        incomplete = sum(1 for panel in team_panel_samples if not panel['complete'])
        if incomplete:
            warnings.append(f'团队面板有 {incomplete}/{len(team_panel_samples)} 个样本未读全 10 行。')
    for snapshot in snapshots:
        if snapshot.get('valid') and not snapshot.get('kdaValidated'):
            _refine_scoreboard_kda(path, snapshot, info)
    title = ((match or {}).get('title') or {}).get('value')
    pov = None
    if title:
        for camp in ('blue', 'red'):
            for row in lineups[camp]:
                if row.get('nickname') == title:
                    pov = {'camp': camp, 'slot': row.get('panelSlot'), 'nickname': title,
                           'hero': row.get('hero'), 'heroGuess': row.get('heroGuess'),
                           'heroStatus': row.get('heroStatus')}
                    break
    if not loading:
        warnings.append('未读到加载页，英雄身份只能依赖游戏内侧栏文字；本布局侧栏只显示昵称。')
    if any(row.get('heroStatus') == 'candidate' for camp in ('blue', 'red') for row in lineups[camp]):
        warnings.append('有英雄名与目录仅差一个字，已列为候选，需人工核对。')
    dropped = _stabilize_counters(samples)
    mapping = build_time_mapping(samples)
    if mapping['offset'] is None:
        warnings.append('没有可用的画面时钟，时间轴未建立。')
    if mapping['speed'] is not None and abs(mapping['speed'] - 1) > 0.02:
        warnings.append(f"录屏播放速度约 {mapping['speed']}x，分均指标不可直接按视频时长计算。")
    if mapping['stalls']:
        warnings.append('检测到画面时钟停顿，暂停期间的视频时间不能当作比赛时间。')
    if mapping['jumps']:
        warnings.append('检测到画面时钟跳变，时间轴在跳变处不连续。')
    timeline = []
    for sample in samples:
        if sample['gameTime'] is None:
            continue
        blue_gold = sample['blue']['gold']['value']
        red_gold = sample['red']['gold']['value']
        timeline.append({'videoTime': sample['videoTime'], 'gameTime': sample['gameTime'],
                         'blueKills': sample['blue']['kills']['value'],
                         'redKills': sample['red']['kills']['value'],
                         'blueGold': blue_gold, 'redGold': red_gold,
                         'goldDiff': blue_gold - red_gold if blue_gold is not None and red_gold is not None else None})
    timeline = _downsample(timeline)
    last_clock = max((s['gameTime'] for s in samples if s['gameTime'] is not None), default=None)
    if total_duration is not None and last_clock is not None and total_duration <= last_clock:
        total_duration = None
        warnings.append('总时长读数与画面时钟冲突，未采用该值。')
    if total_duration and last_clock is not None and last_clock < total_duration - 2:
        warnings.append(f'录像在对局 {last_clock // 60:02d}:{last_clock % 60:02d} 结束，'
                        f'未覆盖完整回放（总时长 {total_duration // 60:02d}:{total_duration % 60:02d}）。')
    segments = _selection_segments(samples)
    if len(segments) > 1:
        warnings.append('底部面板在录制中切换了观战目标，已按等级/KDA/属性变化分段；英雄身份未由画面文字唯一确认。')
    if dropped:
        warnings.append(f'顶部击杀/团队金币出现 {dropped} 处回退读数，已按误读丢弃并保留原文。')
    if snapshots and not any(snapshot.get('valid') for snapshot in snapshots):
        warnings.append('记分板读数未通过团队金币校验，本次不采用逐人经济快照。')
    warnings = list(dict.fromkeys([
        'OCR 只读取画面可见文字；未显示的输出伤害、承伤等字段不能从本录屏得到。',
        '顶部金币是团队累计经济（按 k 取整），底部金币是所选英雄的当前可用金币，语义不同。',
        '逐人经济只在打开记分板时可见；快照仅在双方合计与顶部团队金币相符时采用。',
        '英雄名以加载页印刷文字为准，单字差近似名只作候选。',
        '识别结果保留原文与置信度，正式使用前需人工核对。',
        *warnings,
    ]))
    valid = [s for s in snapshots if s.get('valid')]
    invalid = [s for s in snapshots if not s.get('valid')][:2]
    snapshots = sorted(valid + invalid, key=lambda s: s['videoTime'])
    if postgame_frames:
        warnings.append(f'录像包含 {len(postgame_frames)} 个赛后页采样；终局字段仍建议用赛后截图核对。')
    if LAYOUT == LAYOUT_20X9:
        warnings.append('20:9 录屏的底部团队面板更矮，快速 OCR 可能只读到部分行；'
                        '已保留关键帧，可用 Mimo 精读或赛后截图核对。')
    postgame_evidence, panel_evidence = [], []
    report = {
        'schema': SCHEMA, 'layout': LAYOUT,
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'video': info,
        'sampleFps': fps,
        'scenes': _scenes(points, info['duration']),
        'match': match or {},
        'replayDuration': total_duration,
        'pov': pov,
        'lineups': lineups,
        'timeMapping': mapping,
        'timeline': timeline,
        'killEvents': _kill_events(samples),
        'selection': {'segments': segments,
                      'note': '面板跟随观战目标；段内读数不代表同一名队员。'},
        'scoreboard': {'snapshots': snapshots,
                       'note': '逐人累计经济快照；未打开记分板的时段没有逐人经济。'},
        'teamPanel': {'detected': bool(team_panel_samples),
                      'samples': team_panel_samples,
                      'frames': panel_evidence,
                      'note': '面板整局打开时逐秒读取双方十人 KDA/累计金币；行序按队伍槽位，金币不是可用金币。'},
        'postgame': {'frames': postgame_evidence,
                     'note': '录像末尾的赛后页只作为证据帧；固定字段仍以截图采集为准。'},
        'topCounters': outer,
        'samples': samples,
        'coverage': _coverage(samples, lineups, snapshots),
        'warnings': warnings,
    }
    report['coverage']['teamPanelSamples'] = len(team_panel_samples)
    report['coverage']['postgameFrames'] = len(postgame_frames)
    report['coverage']['teamPanelFrames'] = len(panel_fallback_frames)
    if evidence_dir:
        os.makedirs(evidence_dir, exist_ok=True)
        for name, frame in (('01-replay-list.png', list_frame), ('02-loading.png', loading_frame),
                            ('03-hud-first.png', side_candidates[0] if side_candidates else last_game),
                            ('04-scoreboard.png', score_frame), ('05-hud-last.png', last_game),
                            ('06-team-panel.png', team_panel_frame)):
            if frame is not None:
                frame.save(os.path.join(evidence_dir, name))
        for index, (video_time, game_time, frame) in enumerate(panel_fallback_frames, 1):
            name = f'06-team-panel-{index:02d}.png'
            frame.save(os.path.join(evidence_dir, name))
            panel_evidence.append({'videoTime': video_time, 'gameTime': game_time, 'name': name})
        for index, (video_time, frame) in enumerate(postgame_frames[:8], 1):
            name = f'07-postgame-{index:02d}.png'
            frame.save(os.path.join(evidence_dir, name))
            postgame_evidence.append({'videoTime': round(video_time, 3), 'name': name})
    return report


def render_summary(report):
    labels = {'replay_list': '回放列表', 'loading': '加载', 'game': '对局',
              'postgame': '赛后页', 'unknown': '未知'}
    lines = []
    video = report['video']
    lines.append(f"视频：{video['name']}  {video['duration']}s  {video['width']}x{video['height']}")
    scenes = ' / '.join(f"{labels.get(scene['type'], scene['type'])} {scene['start']:.0f}-{scene['end']:.0f}s"
                        for scene in report['scenes'])
    lines.append(f'阶段：{scenes}')
    match = report.get('match') or {}
    title = (match.get('title') or {}).get('value')
    mode = (match.get('mode') or {}).get('value')
    date = ((match.get('date') or {}).get('value') or {}).get('text')
    if title or mode or date:
        pov = report.get('pov') or {}
        pov_text = ''
        if pov:
            hero = pov.get('hero') or (pov['heroGuess'] + '?' if pov.get('heroGuess') else '英雄未知')
            pov_text = f"  POV {pov.get('nickname')}({hero})"
        lines.append(f"比赛：{title or '标题未知'} · {mode or '模式未知'} · {date or '日期未知'}{pov_text}")
    for camp, label in (('blue', '蓝方'), ('red', '红方')):
        rows = report['lineups'].get(camp, [])
        text = '  '.join(f"{_hero_label(row)}({_nickname_label(row)})" for row in rows) or '无'
        lines.append(f'阵容{label}：{text}')
    mapping = report['timeMapping']
    if mapping.get('offset') is not None:
        first = min((s['gameTime'] for s in report['samples'] if s['gameTime'] is not None), default=0)
        last = max((s['gameTime'] for s in report['samples'] if s['gameTime'] is not None), default=0)
        total = report.get('replayDuration')
        total_text = f" / 总时长 {total // 60:02d}:{total % 60:02d}" if total else ''
        lines.append(f"对局：{first // 60:02d}:{first % 60:02d} → {last // 60:02d}:{last % 60:02d}{total_text}"
                     f"（{mapping['samples']} 个时钟点，速度 {mapping['speed'] or '?'}x）")
    last_timeline = report['timeline'][-1] if report['timeline'] else None
    if last_timeline:
        gold_point = next((point for point in reversed(report['timeline'])
                           if point['blueGold'] is not None and point['redGold'] is not None), None)
        gold = (f"蓝 {gold_point['blueGold']} 金 / 红 {gold_point['redGold']} 金"
                if gold_point else '金币未读全')
        kills = (f"{last_timeline['blueKills']}:{last_timeline['redKills']}"
                 if last_timeline['blueKills'] is not None and last_timeline['redKills'] is not None
                 else '未读全')
        lines.append(f"结束时：{gold}，击杀 {kills}")
    events = report['killEvents']
    if events:
        lines.append('击杀变化：' + '；'.join(
            f"{e['gameTime'] // 60:02d}:{e['gameTime'] % 60:02d} {'蓝' if e['camp'] == 'blue' else '红'}+{e['delta']}"
            for e in events[:12]))
    snapshots = [snapshot for snapshot in report['scoreboard']['snapshots'] if snapshot.get('valid')]
    snapshot = snapshots[-1] if snapshots else None
    if snapshot:
        blue, red = snapshot['blue'], snapshot['red']
        flag = '金币/K/D 已校验' if snapshot.get('kdaValidated') else '金币已校验'
        lines.append(f"记分板 {snapshot['gameTime'] // 60:02d}:{snapshot['gameTime'] % 60:02d}："
                     f"蓝 {blue['sum']}/{blue['team']}，红 {red['sum']}/{red['team']}（{flag}）")
        for camp, label in (('blue', '蓝'), ('red', '红')):
            players = [p for p in snapshot.get('players', []) if p['camp'] == camp]
            parts = []
            for player in players:
                name = player['nickname'] or player['hero'] or ('#' + str(player['slot']))
                if player.get('kdaValidated') and player.get('kda'):
                    kda = '/'.join('-' if value is None else str(value) for value in player['kda'])
                    parts.append(f"{name} {kda} {player['gold']}")
                else:
                    parts.append(f"{name} {player['gold']}")
            lines.append(f"  逐人{label}：{'  '.join(parts) or '未关联'}")
    coverage = report['coverage']
    lines.append(f"记分板覆盖：有效金币快照 {coverage.get('scoreboardSnapshots', 0)}，"
                 f"K/D 已校验 {coverage.get('scoreboardKdaValid', 0)}")
    panel_samples = (report.get('teamPanel') or {}).get('samples') or []
    if panel_samples:
        sample = panel_samples[0]
        parts = []
        for camp, label in (('blue', '蓝'), ('red', '红')):
            rows = []
            for player in sample.get(camp, []):
                kda = player.get('kda')
                kda_text = '/'.join('-' if value is None else str(value) for value in kda) if kda else '?'
                name = player.get('hero') or ('#' + str(player['slot']))
                rows.append(f"{name} {kda_text} {player.get('gold') if player.get('gold') is not None else '?'}")
            parts.append(f"{label} {'  '.join(rows)}")
        stamp = f"{sample['gameTime'] // 60:02d}:{sample['gameTime'] % 60:02d}"
        lines.append(f"团队面板（{len(panel_samples)} 个样本，首个 {stamp}）：{'；'.join(parts)}")
    segments = report['selection']['segments']
    if segments:
        parts = []
        for index, segment in enumerate(segments, 1):
            kda = segment.get('kdaLast')
            kda_text = '/'.join(map(str, kda)) if kda else '?'
            parts.append(f"#{index} {segment['start']:.0f}-{segment['end']:.0f}s L{segment.get('levelLast') or '?'} {kda_text}")
        lines.append('底部面板：' + '；'.join(parts))
        runes_sample = next((sample for sample in report['samples']
                             if (sample.get('selected') or {}).get('runes')), None)
        if runes_sample:
            runes = runes_sample['selected']['runes']
            text = '、'.join(f"{entry['count']}{entry['name']}" for entry in runes['entries'])
            lines.append(f"铭文（本地面板 {runes_sample['videoTime']:.0f}s）：{text}"
                         + ('（末尾被裁切）' if runes.get('truncated') else ''))
        equipment_sample = next((sample for sample in report['samples']
                                 if ((sample.get('selected') or {}).get('equipment') or {}).get('filled')), None)
        if equipment_sample:
            equipment = equipment_sample['selected']['equipment']
            filled = [slot for slot in equipment['slots'] if slot['filled']]
            names = [slot['candidates'][0]['name'] + '?' for slot in filled if slot.get('candidates')]
            text = f"{len(filled)}/6 槽" + (f"，候选 {'、'.join(names)}" if names else '，图标未达命名阈值')
            lines.append(f"装备（底部面板 {equipment_sample['videoTime']:.0f}s）：{text}")
    check = report.get('abcCheck')
    if check:
        lines.append(f".abc 核对：{check['status']} · 补全 {len(check.get('resolved', []))} 名")
    lines.append(f"覆盖：时钟 {coverage['clock']}/{coverage['samples']}，蓝金 {coverage['blueGold']}，"
                 f"红金 {coverage['redGold']}，面板 {coverage['selectedPanel']}，"
                 f"铭文样本 {coverage.get('selectedRunes', 0)}，装备样本 {coverage.get('selectedEquipment', 0)}，"
                 f"阵容英雄 {coverage['lineupHeroes']}/10")
    for warning in report['warnings']:
        lines.append(f'注意：{warning}')
    return '\n'.join(lines)
