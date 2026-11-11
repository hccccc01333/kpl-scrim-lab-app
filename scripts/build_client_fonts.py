"""生成 Electron 客户端的中文衬线字体子集（Noto Serif SC 400 / 700）。

背景：仓库里的 `noto-serif-sc.woff2` 只有 146 个字形（140 个汉字）且
默认实例是 ExtraLight(200)，而客户端标题大面积使用 `--serif` + 600/700 字重，
导致大量汉字回退系统宋体、再叠加合成粗体，标题字形与字重不一致。

本脚本：
1. 下载 OFL 授权的 NotoSerifCJKsc-Regular/Bold（首次缓存到 .cache/fonts/）。
2. 子集包含：ASCII / 拉丁补充 / 常用标点 / 中文标点 / 全角字符 / 箭头 /
   客户端源码里用到的全部非 ASCII 字符 / GB2312 一级汉字（3755 字）。
3. 输出 woff2 到 client/src/renderer/src/assets/fonts/。

用法：python scripts/build_client_fonts.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache' / 'fonts'
TARGET = ROOT / 'client' / 'src' / 'renderer' / 'src' / 'assets' / 'fonts'
BASE = 'https://raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/SimplifiedChinese/'
FILES = {
    'regular': ('NotoSerifCJKsc-Regular.otf', 'noto-serif-sc-regular.woff2'),
    'bold': ('NotoSerifCJKsc-Bold.otf', 'noto-serif-sc-bold.woff2'),
}
# 与标题搭配的标点/符号范围；CJK 汉字用 GB2312 一级 + 源码字符补齐。
RANGES = [
    (0x0020, 0x007E),   # ASCII
    (0x00A0, 0x00FF),   # Latin-1 supplement
    (0x2000, 0x206F),   # general punctuation（— – ‘ ’ “ ” … ·）
    (0x20A0, 0x20BF),   # currency
    (0x2190, 0x21FF),   # arrows（→ ← ↑ ↓）
    (0x2200, 0x22FF),   # math（≈ ≤ ≥ ≠）
    (0x25A0, 0x25FF),   # geometric shapes（■ ● ▲）
    (0x3000, 0x303F),   # CJK punctuation
    (0xFE30, 0xFE4F),   # CJK compatibility forms
    (0xFF00, 0xFFEF),   # fullwidth forms
]


def download(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.is_file() and target.stat().st_size > 1_000_000:
        return target
    url = BASE + urllib.parse.quote(name)
    print(f'下载 {url}')
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    target.write_bytes(data)
    print(f'  -> {target} ({len(data) / 1024 / 1024:.1f} MB)')
    return target


def gb2312_level1() -> set[int]:
    """GB2312 一级汉字 3755 个（按拼音序，覆盖现代汉语常用字）。"""
    chars = set()
    for high in range(0xB0, 0xD8):
        for low in range(0xA1, 0xFF):
            try:
                char = bytes((high, low)).decode('gb2312')
            except UnicodeDecodeError:
                continue
            chars.add(ord(char))
    return chars


def source_chars() -> set[int]:
    """客户端源码里出现的所有非 ASCII 字符（保住新文案的字形）。"""
    chars = set()
    for path in list((ROOT / 'client' / 'src' / 'renderer' / 'src').rglob('*.tsx')) + \
            list((ROOT / 'client' / 'src' / 'renderer' / 'src').rglob('*.ts')):
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            continue
        chars.update(ord(ch) for ch in text if ord(ch) > 0x7F)
    return chars


def codepoints() -> set[int]:
    points = set()
    for low, high in RANGES:
        points.update(range(low, high + 1))
    points |= gb2312_level1()
    points |= source_chars()
    # 去掉控制/代理区
    return {p for p in points if 0x20 <= p <= 0x10FFFF and not 0xD800 <= p <= 0xDFFF}


def build(src: Path, dst: Path, unicodes: set[int]) -> tuple[int, int]:
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
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(dst), options)
    cmap = font.getBestCmap()
    return dst.stat().st_size, len(cmap)


def verify(path: Path, _expected: set[int]) -> dict:
    import unicodedata

    from fontTools.ttLib import TTFont
    font = TTFont(path)
    cmap = set(font.getBestCmap())
    readable = {code for code in source_chars()
                if unicodedata.category(chr(code)) not in {'Cc', 'Cf', 'Zs', 'Zl', 'Zp'}}
    missing_source = sorted(readable - cmap)
    missing_gb = sorted(gb2312_level1() - cmap)
    cjk = sum(1 for code in cmap if 0x4E00 <= code <= 0x9FFF)
    return {
        'file': path.name,
        'bytes': path.stat().st_size,
        'glyphs': len(cmap),
        'cjk': cjk,
        'missingSource': len(missing_source),
        'missingSourceSample': ''.join(chr(c) for c in missing_source[:20]),
        'missingGb2312Level1': len(missing_gb),
    }


def main() -> int:
    unicodes = codepoints()
    print(f'目标字符数：{len(unicodes):,}')
    report = []
    for key, (remote, local) in FILES.items():
        src = download(remote)
        dst = TARGET / local
        size, glyphs = build(src, dst, unicodes)
        print(f'{local}: {size / 1024 / 1024:.2f} MB / {glyphs} glyphs')
        report.append(verify(dst, unicodes))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 只允许 ↵ 这类靠系统字体回退的符号；汉字（含 GB2312 一级）必须全覆盖。
    covered = all(item['missingGb2312Level1'] == 0 and item['missingSource'] <= 1
                  for item in report)
    print('覆盖检查:', 'OK' if covered else '有缺字，请检查源码字符集')
    return 0 if covered else 1


if __name__ == '__main__':
    sys.exit(main())
