#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三种风格的静帧样张（1920x1080），同一段内容，只比风格。

    python marketing/style_samples.py   ->  marketing/style-samples/*.png
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "marketing" / "style-samples"

SANS_B = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
SANS_R = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"
SERIF_B = r"C:\Windows\Fonts\Source Han Serif SC Heavy (TrueType).ttf"
SERIF_R = r"C:\Windows\Fonts\STZHONGS.TTF"

SHOT = ROOT / "docs" / "images" / "09-match.png"


def font(path, size):
    return ImageFont.truetype(path, size)


def text(d, s, f, xy, fill, anchor="la", tracking=0):
    x, y = xy
    if not tracking:
        d.text((x, y), s, font=f, fill=fill, anchor=anchor)
        return
    # 手写字距：逐字排
    widths = [f.getlength(ch) for ch in s]
    total = sum(widths) + tracking * (len(s) - 1)
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    for ch, w in zip(s, widths):
        d.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
        x += w + tracking


def cover(im, w, h):
    iw, ih = im.size
    scale = max(w / iw, h / ih)
    im = im.resize((int(iw * scale) + 1, int(ih * scale) + 1), Image.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


# ---------------------------------------------------------------- A 电影感

def frame_cinema():
    img = Image.new("RGB", (W, H), (4, 8, 7))
    d = ImageDraw.Draw(img)

    # 竖向渐变 + 中央冷光
    for y in range(H):
        k = y / H
        c = (int(10 - 5 * k), int(18 - 9 * k), int(16 - 8 * k))
        d.line([(0, y), (W, y)], fill=c)
    glow = Image.new("L", (64, 36), 0)
    gx = glow.load()
    for y in range(36):
        for x in range(64):
            dx = (x - 31.5) / 31.5
            dy = (y - 21.0) / 21.0
            r = min(1.0, (dx * dx + dy * dy) ** 0.5)
            gx[x, y] = int(58 * (1 - r) ** 2.4)
    img.paste(Image.new("RGB", (W, H), (86, 168, 148)), (0, 0),
              glow.resize((W, H), Image.BICUBIC))

    # 电影画幅黑边
    d.rectangle([0, 0, W, 138], fill=(0, 0, 0))
    d.rectangle([0, H - 138, W, H], fill=(0, 0, 0))

    text(d, "单 局 复 盘", font(SANS_R, 19), (W / 2, 286), (127, 224, 192), "ma", tracking=4)
    text(d, "22 : 3", font(SANS_R, 268), (W / 2, 470), (245, 248, 246), "mm", tracking=6)
    d.rectangle([W / 2 - 54, 648, W / 2 + 54, 649], fill=(127, 224, 192))
    text(d, "一崩到底的那一局，输在第 12 分钟", font(SANS_R, 30), (W / 2, 686),
         (146, 170, 162), "ma")

    # 颗粒
    noise = Image.effect_noise((W, H), 14).convert("L")
    img = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), img,
                          noise.point(lambda v: int(max(0, v - 118) * 0.35)))

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 138], fill=(0, 0, 0))
    d.rectangle([0, H - 138, W, H], fill=(0, 0, 0))
    text(d, "KPL 赛训工具", font(SANS_R, 14), (96, H - 84), (74, 98, 90), "la", tracking=2)
    text(d, "合成演示数据", font(SANS_R, 14), (W - 96, H - 84), (74, 98, 90), "ra")
    return img


# ---------------------------------------------------------------- B 杂志

def frame_editorial():
    paper = (245, 242, 234)
    ink = (24, 24, 22)
    grey = (120, 116, 106)
    accent = (18, 92, 74)
    img = Image.new("RGB", (W, H), paper)
    d = ImageDraw.Draw(img)

    m = 96
    text(d, "KPL 赛训工具", font(SANS_R, 17), (m, 62), grey, tracking=3)
    text(d, "单局复盘", font(SANS_R, 17), (m + 210, 62), grey, tracking=3)
    text(d, "01", font(SERIF_B, 46), (W - m, 40), ink, "ra")

    d.rectangle([m, 108, W - m, 109], fill=(24, 24, 22))

    text(d, "一句结论，", font(SERIF_R, 84), (m, 168), ink)
    text(d, "三块证据。", font(SERIF_R, 84), (m, 274), ink)

    d.rectangle([m, 430, m + 64, 431], fill=accent)
    body = ["22 : 3，一崩到底。", "输在哪一分钟、哪一波团、谁先掉点，", "三块证据摆在同一页。"]
    for i, line in enumerate(body):
        text(d, line, font(SANS_R, 24), (m, 470 + i * 40), grey)

    # 右侧版面：截图 + 图注
    sx, sy, sw, sh = 1010, 168, 814, 508
    shot = Image.open(SHOT).convert("RGB")
    shot = cover(shot, sw, sh)
    img.paste(shot, (sx, sy))
    d.rectangle([sx, sy, sx + sw, sy + sh], outline=(24, 24, 22), width=2)

    text(d, "图 01", font(SANS_R, 16), (sx, sy + sh + 18), accent, tracking=2)
    text(d, "单局页：结论卡、阶段对比、十人面板", font(SANS_R, 18), (sx + 62, sy + sh + 16), grey)

    d.rectangle([m, H - 132, W - m, H - 131], fill=(24, 24, 22))
    text(d, "2026 · 赛训数据平台", font(SANS_R, 15), (m, H - 108), grey, tracking=2)
    text(d, "所有对局、队名、选手均为合成演示数据", font(SANS_R, 15), (W / 2, H - 108),
         grey, "ma")
    text(d, "— 01 —", font(SANS_R, 15), (W - m, H - 108), grey, "ra")
    return img


# ---------------------------------------------------------------- C 数据

def frame_data():
    bg = (10, 20, 18)
    img = Image.new("RGB", (W, H), bg)
    # 网格要走 alpha 合成，直接 draw 到 RGB 上会忽略透明度
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W + 1, 120):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 7))
    for y in range(0, H + 1, 120):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 7))
    img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")
    d = ImageDraw.Draw(img)

    text(d, "单局 · 数据视图", font(SANS_R, 18), (96, 84), (127, 224, 192), tracking=3)
    text(d, "一局的经济，是怎么被拉开的", font(SANS_B, 46), (96, 128), (245, 248, 246))

    kpis = [("22", "3", "比分", (232, 199, 156)),
            ("+2,589", "", "终局经济差", (127, 224, 192)),
            ("24:31", "", "对局时长", (245, 248, 246))]
    x = 96
    for i, (big, small, cap, color) in enumerate(kpis):
        text(d, big, font(SANS_B, 84), (x, 248), color)
        w = font(SANS_B, 84).getlength(big)
        if small:
            text(d, " : " + small, font(SANS_B, 84), (x + w, 248), (245, 248, 246))
        text(d, cap, font(SANS_R, 17), (x, 352), (140, 162, 154), tracking=1)
        x += 330

    # 柱状：分阶段经济差（负值向下）
    base_y, bar_h = 452, 210
    d.line([(96, base_y), (1010, base_y)], fill=(74, 92, 86), width=1)
    data = [("0–4", 0.30), ("4–10", 0.55), ("10–16", 0.44),
            ("16–20", 0.72), ("20–24", 0.96)]
    bw, gap = 108, 70
    for i, (label, ratio) in enumerate(data):
        bx = 96 + i * (bw + gap)
        h = int(bar_h * ratio)
        d.rectangle([bx, base_y, bx + bw, base_y + h], fill=(232, 199, 156))
        d.rectangle([bx, base_y, bx + bw, base_y + 3], fill=(245, 248, 246))
        text(d, label, font(SANS_R, 16), (bx, base_y + bar_h + 24), (150, 170, 162))
    text(d, "分阶段经济差（本队 − 对手，负值）", font(SANS_R, 16), (96, base_y + bar_h + 74),
         (120, 142, 134))

    # 右侧截图
    sx, sy, sw, sh = 1090, 200, 734, 460
    shot = cover(Image.open(SHOT).convert("RGB"), sw, sh)
    img.paste(shot, (sx, sy))
    d.rectangle([sx, sy, sx + sw, sy + sh], outline=(74, 92, 86), width=1)
    text(d, "SOURCE / 营地面板 + 回放事件", font(SANS_R, 14), (sx, sy + sh + 18),
         (120, 142, 134), tracking=2)
    text(d, "KPL 赛训工具", font(SANS_R, 15), (96, H - 60), (120, 142, 134), tracking=2)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("a-cinema", frame_cinema),
                     ("b-editorial", frame_editorial),
                     ("c-data", frame_data)]:
        path = OUT / f"{name}.png"
        fn().save(path)
        print(path.name, f"{os.path.getsize(path)/1024:.0f} KB")


if __name__ == "__main__":
    main()
