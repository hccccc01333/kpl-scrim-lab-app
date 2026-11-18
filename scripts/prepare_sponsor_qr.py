"""把微信收款码海报裁成官网可直接用的方形二维码图。

用法：
    python scripts/prepare_sponsor_qr.py
    python scripts/prepare_sponsor_qr.py --src 海报.png --out 输出.png

输入是微信「收款码」保存下来的绿色海报（上标题、中间白卡片、底部品牌），
输出去掉绿色底板与底部品牌，只留白卡片上的二维码，并补足标准静区。

二维码里是 ``wxp://`` 开头的个人收钱链接，所以本脚本不打印解码内容，
只报尺寸与是否可解码。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / 'docs' / 'afdian' / 'wechat-pay-poster.png'
DEFAULT_OUT = ROOT / 'website' / 'src' / 'assets' / 'img' / 'sponsor-wechat.png'

# 白卡片在海报纵向的粗略位置：用这段窗口找卡片，避开顶部标题和底部品牌条。
CARD_WINDOW = (0.12, 0.78)
# 二维码标准静区是 4 个模块；不知道模块大小时按边长 8.5% 兜底（约 5 个模块）。
QUIET_RATIO = 0.085


def white_bbox(white: np.ndarray) -> tuple[int, int, int, int]:
    """白色像素的包围盒 (x0, y0, x1, y1)，右/下为开区间。"""
    ys, xs = np.nonzero(white)
    if not len(xs):
        raise SystemExit('没找到白卡片：确认输入是微信收款码海报，且没有裁剪过')
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def card_bounds(rgb: np.ndarray) -> tuple[int, int, int, int]:
    """白卡片包围盒：只在中间窗口里找，避免把底部整条白底当成卡片。"""
    height = rgb.shape[0]
    top, bottom = int(height * CARD_WINDOW[0]), int(height * CARD_WINDOW[1])
    white = np.zeros(rgb.shape[:2], dtype=bool)
    white[top:bottom] = rgb[top:bottom].min(axis=2) > 225
    return white_bbox(white)


def qr_square(rgb: np.ndarray, card: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """卡片里二维码的正方形边长与左上角。

    昵称文字在二维码下方，纵向包围盒会比边长长，所以边长取较短边；
    左上角就是二维码左上角（卡片内二维码上方没有别的东西）。
    """
    x0, y0, x1, y1 = card
    dark = np.zeros(rgb.shape[:2], dtype=bool)
    dark[y0:y1, x0:x1] = rgb[y0:y1, x0:x1].max(axis=2) < 120
    ys, xs = np.nonzero(dark)
    if not len(xs):
        raise SystemExit('卡片里没找到二维码')
    side = int(min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))
    return int(xs.min()), int(ys.min()), side


def shrink(image: Image.Image, colors: int) -> Image.Image:
    """海报是 JPEG 存出来的，二维码边上全是压缩噪点，PNG 会白白多出一倍体积。

    调色板化把这些噪点收敛成几十种颜色，二维码仍然锐利，文件小一半。
    """
    if colors >= 256:
        return image
    return image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                          dither=Image.Dither.NONE)


def decode_ok(image: Image.Image) -> str:
    """用 opencv 复检（没装就跳过，不影响出图）。只报长度，不报内容。"""
    try:
        import cv2
    except ImportError:
        return '跳过解码复检（未安装 opencv）'
    value, _points, _straight = cv2.QRCodeDetector().detectAndDecode(
        cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    return f'可解码 {len(value)} 字节' if value else '解码失败'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--src', type=Path, default=DEFAULT_SRC, help='微信收款码海报')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT, help='输出的方形二维码 PNG')
    ap.add_argument('--colors', type=int, default=96,
                    help='调色板颜色数（256 表示不降色，默认 96）')
    args = ap.parse_args()

    if not args.src.is_file():
        raise SystemExit(f'找不到海报：{args.src}')

    source = Image.open(args.src).convert('RGB')
    rgb = np.asarray(source)
    card = card_bounds(rgb)
    x, y, side = qr_square(rgb, card)
    quiet = max(round(side * QUIET_RATIO), 8)

    # 静区不能越过卡片边：卡片外是绿底。
    left = max(card[0], x - quiet)
    top = max(card[1], y - quiet)
    right = min(card[2], x + side + quiet)
    bottom = min(card[3], y + side + quiet)
    crop = source.crop((left, top, right, bottom))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out = shrink(crop, args.colors)
    out.save(args.out, 'PNG', optimize=True)
    print(f'海报 {source.width}×{source.height} · 卡片 {card[2] - card[0]}×{card[3] - card[1]}')
    print(f'二维码边长 {side}px · 静区 {quiet}px · 输出 {crop.width}×{crop.height}')
    print(f'{args.out.relative_to(ROOT)} · {args.out.stat().st_size // 1024} KB · {decode_ok(crop)}')


if __name__ == '__main__':
    sys.exit(main())
