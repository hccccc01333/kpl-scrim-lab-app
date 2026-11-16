"""生成官网的 Noto Serif SC 子集（展示字体）。

官网标题用宋体，但整包 CJK 衬线有 16 MB。这里只保留页面真正出现的字符：
1. 读取 `website/src/*.html` 里所有非 ASCII 字符；
2. 加上英文/数字与中文标点（标题里可能出现 BP、V3、→）；
3. 下载 OFL 授权的 NotoSerifCJKsc-Medium（缓存到 .cache/fonts/）；
4. 子集输出 `website/src/assets/noto-serif-sc.woff2`，并打印缺字检查。

改完网站文案后重跑一次：python scripts/build_website_fonts.py
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
TARGET = SRC / 'assets' / 'noto-serif-sc.woff2'
REMOTE = 'NotoSerifCJKsc-Medium.otf'
BASE = 'https://raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/SimplifiedChinese/'

# 标题可能用到的符号与拉丁字符（字重由 Medium 单一实例承担）。
EXTRA = ''.join(chr(c) for c in range(0x20, 0x7F))
PUNCT = '·—…、。，？！「」『』（）《》〈〉“”‘’：；·／％→←↑↓≈'


def download(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.is_file() and target.stat().st_size > 1_000_000:
        return target
    url = BASE + urllib.parse.quote(name)
    print(f'下载 {url}')
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    target.write_bytes(data)
    print(f'  -> {target} ({len(data) / 1024 / 1024:.1f} MB)')
    return target


def site_chars() -> set[str]:
    chars: set[str] = set(EXTRA) | set(PUNCT)
    for path in sorted(SRC.glob('*.html')):
        text = path.read_text(encoding='utf-8')
        chars.update(text)
    # 只保留可排版字符
    return {c for c in chars if not c.isspace() and ord(c) >= 0x20}


def build(src: Path, dst: Path, chars: set[str]) -> tuple[int, int, int, list[str]]:
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
    missing = sorted(c for c in chars if ord(c) not in cmap)
    cjk = sum(1 for code in cmap if 0x3400 <= code <= 0x9FFF)
    return dst.stat().st_size, len(cmap), cjk, missing


def main() -> int:
    chars = site_chars()
    print(f'官网字符数：{len(chars)}（其中非 ASCII {sum(1 for c in chars if ord(c) > 127)}）')
    src = download(REMOTE)
    size, glyphs, cjk, missing = build(src, TARGET, chars)
    print(f'{TARGET.name}: {size / 1024:.1f} KB / {glyphs} glyphs / CJK {cjk}')
    print(f'缺字 {len(missing)}: {"".join(missing[:24])}')
    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
