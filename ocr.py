"""Local screenshot OCR. Candidates only: no silent writes to match records."""
import re
import threading
import numpy as np
from PIL import Image, ImageOps
from hero_names import resolve_name
from vision import OCR_VERSION, catalog, prepare_image, visual_regions

_engine = None
_lock = threading.RLock()


def get_engine():
    """Return the shared local OCR engine (model load is lazy and expensive)."""
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def detect_tokens(image):
    """Run full-page text detection on an already prepared PIL image."""
    with _lock:
        raw, _ = get_engine()(np.array(image))
    return raw or []


def read_line(image):
    """Read one tightly cropped line; 返回 [(text, confidence), ...]。

    引擎在关闭检测时的返回结构随版本变化：rapidocr-onnxruntime <= 1.3 返回
    ``(box, text, score)`` 三元组，1.4.x 只返回 ``(text, score)``。这里两种都
    接受，统一成两元组，调用方（ocr.read_crop_line / postgame_ocr 的紧裁读取）
    一律按 (text, confidence) 取。
    """
    with _lock:
        found, _ = get_engine()(np.array(image), use_det=False, use_cls=False)
    result = []
    for item in found or []:
        record = list(item) if not isinstance(item, (str, bytes)) else [item]
        if len(record) >= 3:
            text, confidence = record[1], record[2]
        elif len(record) == 2:
            text, confidence = record[0], record[1]
        else:
            continue
        try:
            result.append((str(text), float(confidence)))
        except (TypeError, ValueError):
            continue
    return result


def recognize(data, learned=None):
    image, crop = prepare_image(data)
    width, height = image.size
    raw = detect_tokens(image)
    tokens = []
    for box, text, confidence in raw or []:
        tokens.append({'text': text, 'confidence': float(confidence),
                       'box': [[round(float(x) / width, 5), round(float(y) / height, 5)] for x, y in box]})
    texts = ' '.join(t['text'] for t in tokens)
    kind = 'data' if '输出伤害' in texts and '承受伤害' in texts else 'score' if ('胜利' in texts or '失败' in texts or '/' in texts) else 'unknown'
    output = {'kind': kind, 'tokens': tokens, 'scores': {}, 'players': [], 'warnings': [], 'meta': {},
              'version': OCR_VERSION, 'visuals': [], 'template': '赛后双列五行', 'crop': crop}
    if kind == 'unknown' or not 1.65 < width / height < 2.7:
        output['kind'] = 'unknown'
        output['warnings'].append('未匹配赛后双列面板，保留原始文字供核对，不自动填表。')
        return output

    def center(token):
        return tuple(sum(p[i] for p in token['box']) / 4 for i in (0, 1))

    def at(x, y, dx=.024, dy=.023, pattern=None):
        ts = [t for t in tokens if abs(center(t)[0]-x) < dx and abs(center(t)[1]-y) < dy
              and (not pattern or re.fullmatch(pattern, t['text'].strip(), re.I))]
        return min(ts, key=lambda t: abs(center(t)[0]-x)+abs(center(t)[1]-y)) if ts else None

    def crop_tokens(x1, y1, x2, y2):
        crop = image.crop((round(x1*width), round(y1*height), round(x2*width), round(y2*height)))
        crop = crop.resize((crop.width * 4, crop.height * 4))
        found = detect_tokens(crop)
        return sorted(found, key=lambda r: sum(p[0] for p in r[0])/4)

    def read_crop_line(x1, y1, x2, y2):
        crop = image.crop((round(x1*width), round(y1*height), round(x2*width), round(y2*height)))
        crop = crop.resize((crop.width*4, crop.height*4))
        found = read_line(crop)
        return found[0] if found else None

    for side, x in [('left', .424), ('right', .578)]:
        t = at(x, .05, .035, .045, r'\d{1,3}')
        if not t:
            found = crop_tokens(x-.025, .012, x+.025, .09)
            digits = [(r[1], float(r[2])) for r in found if re.fullmatch(r'\d{1,3}', r[1])]
            if len(digits) == 1:
                t = {'text': digits[0][0], 'confidence': digits[0][1]}
        if t:
            output['scores'][side] = t['text']
    date_match = re.search(r'(20\d{2})/(\d{1,2})/(\d{1,2})', texts)
    if date_match:
        output['meta']['date'] = '-'.join([date_match[1], date_match[2].zfill(2), date_match[3].zfill(2)])
    # A duration and a clock can coexist: only read the one before the date.
    header = texts.split(date_match[0])[0] if date_match else ''
    duration = re.search(r'(\d{1,2}):(\d{2})', header)
    if duration:
        output['meta']['duration'] = str(round(int(duration[1])+int(duration[2])/60, 3))
    entries = catalog()['entries']
    hero_names = {e['name'] for e in entries if e['kind'] == 'hero'}
    name_results = {}
    for side, offset in [('left', 0), ('right', .435)]:
        for i in range(5):
            p = {'side': side, 'slot': i, 'fields': {}}
            def put(key, token):
                if token:
                    p['fields'][key] = {'value': token['text'], 'raw': token['text'], 'confidence': token['confidence'], 'box': token.get('box')}
            names = [t for t in tokens if t['text'] in hero_names and t['confidence'] >= .75
                     and .059+offset < center(t)[0] < .145+offset
                     and .276+i*.119 < center(t)[1] < .32+i*.119]
            readings = [{'raw': t['text'], 'confidence':t['confidence'], 'variant':'full-frame'} for t in names]
            # Isolate the tiny printed label; avoid the face and next player row.
            for label, x2, y1, y2 in [('tight',.108,.279,.301), ('wide',.135,.276,.310), ('gray',.108,.280,.307)]:
                box = (.064+offset, y1+i*.119, x2+offset, y2+i*.119)
                area = image.crop(tuple(round(v*(width if j%2==0 else height)) for j,v in enumerate(box)))
                area = area.resize((area.width*8,area.height*8), Image.Resampling.LANCZOS)
                if label == 'gray':
                    area = ImageOps.autocontrast(area.convert('L')).convert('RGB')
                found = read_line(area)
                if found:
                    readings.append({'raw':found[0][0], 'confidence':float(found[0][1]), 'variant':label})
            name_result = resolve_name(readings, entries)
            name_results[(side,i)] = name_result
            if name_result['accepted']:
                accepted = name_result['accepted']
                put('hero', {'text':accepted['name'], 'confidence':accepted['textConfidence'],
                             'box':[[.064+offset,.276+i*.119],[.135+offset,.310+i*.119]]})
            put('rating', at(.182+offset, .266+i*.119, .026, .027, r'\d{1,2}\.\d'))
            if kind == 'data':
                y = .252 + i*.119
                for key, x in [('damage', .247), ('taken', .308), ('gold', .369)]:
                    put(key, at(x+offset, y, .025, .018, r'\d+(?:\.\d+)?[kK万]?'))
                put('participation', at(.46+offset, y+.032, .022, .018, r'\d{1,3}%'))
            else:
                y = .215+i*.119
                found = read_crop_line(.325+offset, y-.024, .395+offset, y+.025)
                joined = found[0] if found else ''
                digits = re.findall(r'\d+', joined)
                if len(digits) == 3 and all(int(v) <= 100 for v in digits):
                    conf = float(found[1])
                    for key, value in zip(('kills', 'deaths', 'assists'), digits):
                        p['fields'][key] = {'value': value, 'raw': joined, 'confidence': conf,
                                            'box': [[.326+offset, y-.021], [.400+offset, y+.023]]}
                found = read_crop_line(.3985+offset, y-.022, .442+offset, y+.022)
                if found and re.fullmatch(r'\d{3,6}', found[0]):
                    put('gold', {'text': found[0], 'confidence': float(found[1])})
            output['players'].append(p)
    output['visuals'] = visual_regions(image, kind, learned)
    for region in output['visuals']:
        if region['kind'] == 'hero':
            result = name_results[(region['side'],region['slot'])]
            region.update({'candidates':result['candidates'],'readings':result['readings'],'status':result['status'], 'method':'printed-name'})
    output['warnings'].append('英雄优先读取头像下方的名字，不使用默认皮肤头像判断身份。文字近似匹配必须人工确认；装备缺乏充分匹配证据时不提供猜测结果，保留未知。')
    return output
