"""Render the application icon from the V3 brand mark.

The mark in ``v3/public/media/mark.svg`` is three rounded bars (teal / coral /
teal).  This script redraws the same geometry on a dark rounded square and
writes a multi-resolution ``app.ico`` plus a PNG for docs and store pages.

Run:  python packaging/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT_ICO = HERE / 'app.ico'
OUT_PNG = HERE / 'app-256.png'

CANVAS = 1024
RADIUS = 224
BG_TOP = (27, 44, 75)
BG_BOTTOM = (14, 23, 38)
TEAL = (42, 143, 139)
CORAL = (240, 138, 108)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]

# Geometry copied from mark.svg (viewBox 0 0 40 40).
BARS = [
    (3, 13, 8, 21, TEAL),
    (16, 5, 8, 29, CORAL),
    (29, 15, 8, 19, TEAL),
]


def vertical_gradient(size: int, top, bottom) -> Image.Image:
    image = Image.new('RGB', (1, size))
    for y in range(size):
        ratio = y / max(size - 1, 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        image.putpixel((0, y), color)
    return image.resize((size, size), Image.BILINEAR)


def draw_icon() -> Image.Image:
    canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    mask = Image.new('L', (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, CANVAS - 1, CANVAS - 1), radius=RADIUS, fill=255)
    canvas.paste(vertical_gradient(CANVAS, BG_TOP, BG_BOTTOM), (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    # Scale the 40-unit art into a 620 px square, centred.
    scale = 620 / 40
    offset = (CANVAS - 620) / 2
    for x, y, w, h, color in BARS:
        box = (offset + x * scale, offset + y * scale,
               offset + (x + w) * scale, offset + (y + h) * scale)
        draw.rounded_rectangle(box, radius=30, fill=(*color, 255))
    return canvas


def main() -> int:
    icon = draw_icon()
    icon.resize((256, 256), Image.LANCZOS).save(OUT_PNG, 'PNG')
    icon.save(OUT_ICO, 'ICO', sizes=ICO_SIZES)
    print(f'图标：{OUT_ICO}（{OUT_ICO.stat().st_size / 1024:.0f} KB，'
          f'{len(ICO_SIZES)} 个尺寸）')
    print(f'预览：{OUT_PNG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
