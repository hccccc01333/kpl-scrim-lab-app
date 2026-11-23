"""生成官网的 Noto Sans SC 子集（展示 + 正文），三个字重。

与旧版 noto-serif-sc.woff2（宋体，单一 500 字重）相比：
- 思源黑体是现代产品官网常用的无衬线体，标题更有力量、更清晰；
- 400 / 500 / 700 三个字重，标题可以真正加粗；
- 只保留网站 HTML 里出现的字符 + 拉丁 + 标点，单字重约 300 KB。

用法：python scripts/build_website_sans_fonts.py
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
FILES = {
    400: ('NotoSansCJKsc-Regular.otf', 'noto-sans-sc-regular.woff2'),
    500: ('NotoSansCJKsc-Medium.otf', 'noto-sans-sc-medium.woff2'),
    700: ('NotoSansCJKsc-Bold.otf', 'noto-sans-sc-bold.woff2'),
}
LICENSE = ('https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE',
           'noto-sans-sc-OFL.txt')

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
    # emoji（如 ☕）由系统 emoji 字体渲染，CJK 子集无需收录
    missing = sorted(c for c in chars if ord(c) not in cmap and ord(c) < 0x1F000 and c != '☕')
    return dst.stat().st_size, len(cmap), missing


def main() -> int:
    chars = site_chars()
    print(f'官网字符数：{len(chars)}（非 ASCII {sum(1 for c in chars if ord(c) > 127)}）')
    lic_src, lic_name = LICENSE
    download(lic_name, lic_src, 1000).replace(ASSETS / lic_name)
    all_missing: set[str] = set()
    for weight, (remote, local) in FILES.items():
        src = download(remote, BASE + urllib.parse.quote(remote), 1_000_000)
        size, glyphs, missing = build(src, ASSETS / local, chars)
        all_missing.update(missing)
        print(f'{local}: {size / 1024:.1f} KB / {glyphs} glyphs / 缺字 {len(missing)}')
    if all_missing:
        print(f'缺字（全部字重）: {"".join(sorted(all_missing))}')
    return 0 if not all_missing else 1


if __name__ == '__main__':
    sys.exit(main())
