"""生成 v3 界面的现代中文无衬线字体子集（Noto Sans SC 400 / 500 / 700）。

背景：v3 的 `--font` 是 `Manrope + "Microsoft YaHei UI"`——Windows 回退到雅黑，
字重层级糊、字形旧（2026 年教练观感反馈「字体不好看」）。这里打包 OFL 授权的
Noto Sans SC（思源黑体同源），子集化后落到 `v3/public/media/`，静态资源自动带
stamp（server.py `_v3_asset_stamp` 覆盖 v3/public/**），无新增配置。

子集口径与 scripts/build_client_fonts.py 一致：ASCII / 常用标点 / 全角 / 箭头等
区间 + GB2312 一级汉字（3755 字）+ v3 前端源码里实际出现的全部非 ASCII 字符
（保住新文案字形）。数字字形仍由 Manrope 提供（排在 font 栈最前）。

用法：
    python scripts/build_v3_fonts.py            # 首次会下载 OTF（缓存到 .cache/fonts/）
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CACHE = ROOT / '.cache' / 'fonts'
TARGET = ROOT / 'v3' / 'public' / 'media'
# Noto Sans SC：notofonts 官方仓库的 Variable/OTF 均可；这里用静态 OTF（子集化更稳）
BASE = 'https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/'
FILES = {
    400: ('NotoSansCJKsc-Regular.otf', 'noto-sans-sc-regular.woff2'),
    500: ('NotoSansCJKsc-Medium.otf', 'noto-sans-sc-medium.woff2'),
    700: ('NotoSansCJKsc-Bold.otf', 'noto-sans-sc-bold.woff2'),
}
LICENSE = ('https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE',
           'noto-sans-sc-OFL.txt')
# 与界面搭配的标点/符号区间；汉字用 GB2312 一级 + v3 源码字符补齐。
RANGES = [
    (0x0020, 0x007E),   # ASCII
    (0x00A0, 0x00FF),   # Latin-1 supplement
    (0x2000, 0x206F),   # general punctuation（— – ‘ ’ “ ” … ·）
    (0x20A0, 0x20BF),   # currency
    (0x2190, 0x21FF),   # arrows
    (0x2200, 0x22FF),   # math（≈ ≤ ≥ ≠）
    (0x25A0, 0x25FF),   # geometric shapes（■ ● ▲）
    (0x3000, 0x303F),   # CJK punctuation
    (0xFE30, 0xFE4F),   # CJK compatibility forms
    (0xFF00, 0xFFEF),   # fullwidth forms
]


def download(url: str, target: Path, min_size: int = 1_000_000) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > min_size:
        return target
    print(f'下载 {url}')
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    target.write_bytes(data)
    print(f'  -> {target} ({len(data) / 1024 / 1024:.1f} MB)')
    return target


def gb2312_level1() -> set[int]:
    """GB2312 一级汉字 3755 个。"""
    chars = set()
    for high in range(0xB0, 0xD8):
        for low in range(0xA1, 0xFF):
            try:
                char = bytes((high, low)).decode('gb2312')
            except UnicodeDecodeError:
                continue
            chars.add(ord(char))
    return chars


def v3_chars() -> set[int]:
    """v3 前端源码里出现的全部非 ASCII 字符。"""
    chars = set()
    public = ROOT / 'v3' / 'public'
    for path in list(public.rglob('*.js')) + list(public.rglob('*.html')):
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
    points |= v3_chars()
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


def main() -> int:
    points = codepoints()
    TARGET.mkdir(parents=True, exist_ok=True)
    license_path = TARGET / LICENSE[1]
    if not license_path.exists():
        try:
            download(LICENSE[0], license_path, min_size=1_000)
        except OSError as exc:  # noqa: BLE001 - 许可文件下载失败不阻塞字体构建
            print(f'[WARN] OFL 许可文件下载失败：{exc}')
    total = 0
    for _weight, (name, out_name) in FILES.items():
        src = download(BASE + urllib.parse.quote(name), CACHE / name)
        dst = TARGET / out_name
        size, glyphs = build(src, dst, points)
        total += size
        print(f'{out_name}: {size / 1024:.0f} KB · {glyphs} 字形')
    print(f'共 {total / 1024 / 1024:.1f} MB -> {TARGET}')
    print('下一步：v3/public/style.css 的 --font 加 "Noto Sans SC"，@font-face 指向这三个文件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
