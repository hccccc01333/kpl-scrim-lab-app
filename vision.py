"""Offline icon retrieval. Similarity is a ranking score, never a probability."""
from functools import lru_cache
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
OCR_VERSION = 'scoreboard-v3-name-first'


@lru_cache(maxsize=1)
def catalog():
    path = ROOT / 'resources' / 'catalog.json'
    if not path.exists():
        return {'entries': [], 'notice': '本机图标库尚未准备，可继续手工录入。'}
    return json.loads(path.read_text(encoding='utf-8'))


def prepare_image(data):
    image = Image.open(io.BytesIO(data)).convert('RGB')
    arr = np.array(image)
    rows = np.where((arr.min(axis=2) < 225).mean(axis=1) > .55)[0]
    top, bottom = (int(rows[0]), int(rows[-1]) + 1) if len(rows) else (0, image.height)
    image = image.crop((0, top, image.width, bottom))
    # v1.5: 不再把横屏截图压到 1600 宽——按显示精度读数的数值列对分辨率敏感。
    # 只对极端大图限幅，避免内存失控；普通手机截图（<=3200 宽）全程原分辨率。
    if image.width > 3200:
        image = image.resize((3200, round(image.height * 3200 / image.width)), Image.Resampling.LANCZOS)
    return image, {'top': top, 'bottom': bottom}


def crop_box(image, box):
    if not isinstance(box, list) or len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not np.isfinite(v) for v in box):
        raise ValueError('裁剪区域格式错误')
    x1, y1, x2, y2 = box
    if not 0 <= x1 < x2 <= 1 or not 0 <= y1 < y2 <= 1:
        raise ValueError('裁剪区域越界')
    coords = (round(x1*image.width), round(y1*image.height), round(x2*image.width), round(y2*image.height))
    if coords[2] <= coords[0] or coords[3] <= coords[1]:
        raise ValueError('裁剪区域太小')
    return image.crop(coords)


def descriptor(image):
    pixels = np.asarray(image.resize((24, 24)), dtype=np.float32) / 255
    y, x = np.mgrid[-1:1:24j, -1:1:24j]
    pixels = pixels[(x*x+y*y) < .72]
    # Ignore round icon frames, compare central artwork and color distribution.
    centered = (pixels-pixels.mean()) / max(float(pixels.std()), .08)
    vector = centered.flatten()
    vector /= max(float(np.linalg.norm(vector)), .001)
    hist = np.concatenate([np.histogram(pixels[:, i], bins=8, range=(0, 1))[0] for i in range(3)]).astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), .001)
    return vector, hist


@lru_cache(maxsize=1)
def official_index():
    result = {'hero': [], 'equipment': []}
    for entry in catalog()['entries']:
        if not entry.get('icon'):
            continue
        icons = entry.get('variants') or [entry['icon']]
        for icon in icons:
            path = ROOT / 'resources' / 'icons' / Path(icon).name
            if path.exists():
                with Image.open(path) as im:
                    result[entry['kind']].append(({**entry, 'icon': icon}, *descriptor(im.convert('RGB'))))
    return result


def rank_icon(image, kind, learned=()):
    vector, hist = descriptor(image)
    candidates = list(official_index().get(kind, [])) + list(learned)
    by_name = {}
    for entry, other_vector, other_hist in candidates:
        similarity = float(.78 * (np.dot(vector, other_vector)+1)/2 + .22 * np.dot(hist, other_hist))
        row = {'id': entry['id'], 'name': entry['name'], 'icon': entry.get('icon'),
               'similarity': round(min(1, max(0, similarity)), 4),
               'source': 'reviewed' if entry.get('reviewed') else 'official'}
        if row['name'] not in by_name or similarity > by_name[row['name']]['similarity']:
            by_name[row['name']] = row
    return sorted(by_name.values(), key=lambda r: -r['similarity'])[:5]


def visual_regions(image, kind, learned=None):
    learned = learned or {}
    regions = []
    for side, offset in [('left', 0), ('right', .435)]:
        for slot in range(5):
            specs = [('hero', 0, [.064+offset, .276+slot*.119, .135+offset, .310+slot*.119])]
            if kind == 'score':
                for index in range(6):
                    x, y = .246+offset+index*.033, .265+slot*.119
                    specs.append(('equipment', index, [x-.014, y-.032, x+.014, y+.032]))
            for region_kind, index, box in specs:
                candidates = rank_icon(crop_box(image, box), region_kind, learned.get(region_kind, [])) if region_kind == 'equipment' else []
                # Broad visual rankings were misleading on real screenshots: abstain.
                reliable = bool(candidates and candidates[0]['similarity'] >= .94 and (len(candidates)<2 or candidates[0]['similarity']-candidates[1]['similarity'] >= .06))
                regions.append({'side': side, 'slot': slot, 'kind': region_kind, 'index': index,
                                'box': [round(v, 5) for v in box],
                                'status': 'reference' if reliable else 'unreadable',
                                'candidates': candidates[:1] if reliable else []})
    return regions
