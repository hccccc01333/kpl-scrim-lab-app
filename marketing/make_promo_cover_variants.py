#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书「宣传」封面方向样张（1242x1656）。

    python marketing/make_promo_cover_variants.py
产出：marketing/covers/promo-variants/*.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1242, 1656
M = 88
OUT = Path(__file__).resolve().parent / "covers" / "promo-variants"

BOLD = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
REG = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"
SERIF = r"C:\Windows\Fonts\STZHONGS.TTF"

INK = (22, 33, 30)
MUTED = (96, 116, 108)
GREEN = (18, 63, 56)
MINT = (127, 224, 192)
MINT_SOFT = (205, 236, 222)
PILL_BG = (223, 240, 233)
LINE = (196, 214, 205)


def font(path, size):
    return ImageFont.truetype(path, size)


def base(dark=False):
    top = (16, 34, 30) if dark else (219, 237, 229)
    bot = (9, 22, 19) if dark else (234, 241, 236)
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(
            int(top[0] + (bot[0] - top[0]) * k),
            int(top[1] + (bot[1] - top[1]) * k),
            int(top[2] + (bot[2] - top[2]) * k),
        ))
    glow = Image.new("L", (200, 200), 0)
    gd = glow.load()
    for y in range(200):
        for x in range(200):
            dx = (x - 100) / 100
            dy = (y - 100) / 100
            r = min(1.0, math.hypot(dx, dy))
            gd[x, y] = int((46 if dark else 80) * (1 - r) ** 2)
    img.paste(Image.new("RGB", (W, H), (120, 200, 175) if dark else (255, 255, 255)),
              (0, 0), glow.resize((W, H), Image.BICUBIC))
    return img


def pill(d, xy, text, f, fg=GREEN, bg=PILL_BG, padx=24, pady=12):
    x, y = xy
    tw = d.textlength(text, font=f)
    h = f.size + pady * 2
    d.rounded_rectangle([x, y, x + tw + padx * 2, y + h], radius=h // 2, fill=bg)
    d.text((x + padx, y + pady - f.size * 0.14), text, font=f, fill=fg)
    return tw + padx * 2


def headline(d, lines, y, size=86, lead=1.24, marks=(), color=INK):
    f = font(BOLD, size)
    for i, line in enumerate(lines):
        ly = y + int(i * size * lead)
        for (li, s, e) in marks:
            if li != i:
                continue
            x0 = M + d.textlength(line[:s], font=f)
            w = d.textlength(line[s:e], font=f)
            d.rounded_rectangle([x0 - 8, ly + size * 0.02, x0 + w + 8, ly + size * 1.12],
                                radius=10, fill=MINT_SOFT if color == INK else (32, 70, 60))
        d.text((M, ly), line, font=f, fill=color)


def body(d, lines, y, size=30, lead=1.6, color=MUTED):
    f = font(REG, size)
    for i, line in enumerate(lines):
        d.text((M, y + int(i * size * lead)), line, font=f, fill=color)


def footnote(d, left, right="KPL 赛训工具"):
    d.line([(M, H - 132), (W - M, H - 132)], fill=LINE, width=1)
    d.text((M, H - 106), left, font=font(REG, 23), fill=MUTED)
    fw = d.textlength(right, font=font(REG, 23))
    d.text((W - M - fw, H - 106), right, font=font(REG, 23), fill=MUTED)


def card_a():
    """痛点钩子。"""
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "赛训 · 复盘", font(BOLD, 27))
    headline(d, ["训练赛打完，", "教练组在抄 KDA。"], 250, 86, marks=[(1, 5, 8)])
    body(d, ["十个人、五个指标、五十个数，", "一个个从截图里敲进表格。"], 520, 32)

    d.rounded_rectangle([M, 700, W - M, 1120], radius=26, fill=(255, 255, 255), outline=LINE, width=1)
    rows = [("七页截图", "结算面板、数据页、团队页"),
            ("整段录屏", "1 倍速，几百兆"),
            ("手填表格", "教练自己按格子填"),
            ("营地链接", "详情只留最近一个月")]
    for i, (k, v) in enumerate(rows):
        y = 740 + i * 92
        d.text((M + 44, y), k, font=font(BOLD, 32), fill=INK)
        d.text((M + 240, y + 6), v, font=font(REG, 25), fill=MUTED)
        if i < 3:
            d.line([(M + 44, y + 68), (W - M - 44, y + 68)], fill=(232, 240, 235), width=1)

    body(d, ["抄和核对，占掉八成时间。"], 1180, 34, color=INK)
    footnote(d, "问题不是没有数据，是数据到不了能复盘的状态")
    return img


def card_b():
    """干货钩子。"""
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "复盘方法", font(BOLD, 27))
    headline(d, ["教练复盘，", "先看这 3 个数。"], 236, 88, marks=[(1, 3, 6)])
    body(d, ["不是胜率，也不是 KDA。", "是一局里最容易被忽略的三件事。"], 500, 32)

    items = [("10 分钟经济差", "对线期结束那一刻，钱差多少"),
             ("控龙率", "暴君、暗影暴君、暗影主宰，谁在拿"),
             ("掉点位置", "人死在哪、之后经济怎么走")]
    for i, (k, v) in enumerate(items):
        y = 660 + i * 190
        d.text((f"{i+1:02d}",) and (M, y), f"{i+1:02d}", font=font(BOLD, 28), fill=(150, 178, 166))
        d.text((M + 70, y - 8), k, font=font(BOLD, 44), fill=INK)
        d.text((M + 70, y + 56), v, font=font(REG, 26), fill=MUTED)

    body(d, ["这三件事，工具能在一页里摆出来。"], 1270, 30, color=GREEN)
    footnote(d, "一页看完一局，复盘会直接投屏")
    return img


def card_c():
    """结果钩子（深色）。"""
    img = base(dark=True)
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "工具", font(BOLD, 27), fg=(200, 240, 226), bg=(30, 58, 51))
    headline(d, ["七页截图进去，", "一页结论出来。"], 246, 88,
             marks=[(1, 0, 4)], color=(244, 248, 246))
    body(d, ["本机识别 · 逐项确认 · 每个数字标明来源"],
         520, 32, color=(150, 178, 166))

    d.rounded_rectangle([M, 690, W - M, 1150], radius=26, fill=(12, 26, 22),
                        outline=(52, 84, 74), width=1)
    rows = [("识别", "候选值，不直接入库"),
            ("校对", "缺字段、冲突、越界，逐条拦"),
            ("入库", "审核通过才进正式统计"),
            ("复盘", "单局 / 跨局 / 选手 / BP")]
    for i, (k, v) in enumerate(rows):
        y = 736 + i * 96
        d.text((M + 44, y), k, font=font(BOLD, 30), fill=MINT)
        d.text((M + 200, y + 4), v, font=font(REG, 25), fill=(176, 200, 190))

    body(d, ["数据不出本机，一个 data 目录就是完整备份。"],
         1210, 28, color=(150, 178, 166))
    footnote(d, "Windows 10 / 11 · 免环境 · 个人与教学免费")
    return img


CARDS = [("A-痛点", card_a), ("B-干货", card_b), ("C-结果", card_c)]

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in CARDS:
        p = OUT / f"{name}.png"
        fn().save(p, optimize=True)
        print(p.name, f"{p.stat().st_size // 1024} KB")
