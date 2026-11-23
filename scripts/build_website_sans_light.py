"""生成 Noto Sans SC Light (300) 子集，供细体标题使用。

复用 build_website_sans_fonts.py 的字符集合与裁剪逻辑。
用法：python scripts/build_website_sans_light.py
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'website' / 'src'
CACHE = ROOT / '.cache' / 'fonts'
ASSETS = SRC / 'assets'

BASE = 'https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/'
REMOTE = 'NotoSansCJKsc-Light.otf'
LOCAL = 'noto-sans-sc-light.woff2'

EXTRA = ''.join(chr(c) for c in range(0x20, 0x7F))
PUNCT = '·—…、。，？！「」『』（）《》〈〉“”‘’：；·／％→←↑↓≈°✓'


def download(name: str, url: str, min_size: int) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.is_file() and target.stat().st_size > min_size:
        return target
    print(f'下载 {url}')
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    target.write_bytes(data)
    print(f'  -> {target.name} ({len(data) / 1024 / 1024:.1f} MB)')
    return target


def site_chars() -> set[str]:
    chars: set[str] = set(EXTRA) | set(PUNCT)
    for path in sorted(SRC.glob('*.html')):
        chars.update(path.read_text(encoding='utf-8'))
    for path in [SRC / 'assets' / 'site.js']:
        if path.exists():
            chars.update(path.read_text(encoding='utf-8'))
    return {c for c in chars if not c.isspace() and ord(c) >= 0x20}


def build(src: Path, dst: Path, chars: set[str]) -> tuple[int, int, list[str]]:
    options = subset.Options()
    options.flavor = 'woff2'
    options.layout_features = ['*']
    options.name_IDs = ['*']
    options.name_languages = ['*']
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables += ['DSIG']
    font = subset.load_font(str(src), options, dontLoadGlyphNames=True)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes={ord(c) for c in chars})
    subsetter.subset(font)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(dst), options)
    cmap = set(font.getBestCmap())
    missing = sorted(c for c in chars if ord(c) not in cmap and ord(c) < 0x1F000 and c != '☕')
    return dst.stat().st_size, len(cmap), missing


def main() -> int:
    chars = site_chars()
    print(f'官网字符数：{len(chars)}（非 ASCII {sum(1 for c in chars if ord(c) > 127)}）')
    src = download(REMOTE, BASE + urllib.parse.quote(REMOTE), 1_000_000)
    size, glyphs, missing = build(src, ASSETS / LOCAL, chars)
    print(f'{LOCAL}: {size / 1024:.1f} KB / {glyphs} glyphs / 缺字 {len(missing)}')
    if missing:
        print(f'缺字: {"".join(sorted(missing))}')
    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
