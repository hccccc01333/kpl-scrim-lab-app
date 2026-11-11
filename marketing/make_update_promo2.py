#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书 · 1.5.32 更新（带真实界面截图版）。

左侧一句「更新了什么」，右侧/下方是真界面，字和图对得上。

    python marketing/make_update_promo2.py
产出：marketing/covers/update-1.5.32/*.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1242, 1656
M = 88
SHOTS = Path(__file__).resolve().parent / "covers" / "_shots"
OUT = Path(__file__).resolve().parent / "covers" / "update-1.5.32"

BOLD = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
REG = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"

INK = (22, 33, 30)
MUTED = (96, 116, 108)
DIM = (142, 166, 155)
GREEN = (18, 63, 56)
MINT = (127, 224, 192)
MINT_SOFT = (205, 236, 222)
PILL_BG = (223, 240, 233)
LINE = (198, 216, 207)
CARD = (255, 255, 255)


def font(p, s):
    return ImageFont.truetype(p, s)


def base():
    top, bot = (219, 237, 229), (236, 242, 238)
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(
            int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
    glow = Image.new("L", (200, 200), 0)
    gd = glow.load()
    for y in range(200):
        for x in range(200):
            dx = (x - 100) / 100
            dy = (y - 100) / 100
            gd[x, y] = int(70 * (1 - min(1.0, math.hypot(dx, dy))) ** 2)
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0),
              glow.resize((W, H), Image.BICUBIC))
    return img


def pill(d, xy, text, f, fg=GREEN, bg=PILL_BG, padx=22, pady=11):
    x, y = xy
    tw = d.textlength(text, font=f)
    h = f.size + pady * 2
    d.rounded_rectangle([x, y, x + tw + padx * 2, y + h], radius=h // 2, fill=bg)
    d.text((x + padx, y + pady - f.size * 0.13), text, font=f, fill=fg)


def headline(d, lines, y, size=74, lead=1.26, marks=()):
    f = font(BOLD, size)
    for i, line in enumerate(lines):
        ly = y + int(i * size * lead)
        for (li, s, e) in marks:
            if li != i:
                continue
            x0 = M + d.textlength(line[:s], font=f)
            w = d.textlength(line[s:e], font=f)
            d.rounded_rectangle([x0 - 8, ly + size * 0.02, x0 + w + 8, ly + size * 1.12],
                                radius=10, fill=MINT_SOFT)
        d.text((M, ly), line, font=f, fill=INK)


def body(d, lines, y, size=27, lead=1.6, color=MUTED):
    f = font(REG, size)
    for i, line in enumerate(lines):
        d.text((M, y + int(i * size * lead)), line, font=f, fill=color)


def shot_card(img, d, name, crop, y=None, width=None, radius=18):
    """把界面的某一段贴进圆角卡片。crop=(x0,y0,x1,y1) 用源图像素。"""
    src = Image.open(SHOTS / name).convert("RGB")
    x0, y0, x1, y1 = crop
    piece = src.crop((x0, y0, x1, y1))
    w = width or (W - M * 2)
    h = int(piece.height * w / piece.width)
    piece = piece.resize((w, h), Image.LANCZOS)
    yy = y if y is not None else 300
    # 阴影
    sh = Image.new("L", (w + 60, h + 60), 0)
    ImageDraw.Draw(sh).rounded_rectangle([30, 30, w + 30, h + 30], radius=radius, fill=150)
    sh = sh.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(18))
    img.paste(Image.new("RGB", sh.size, (0, 0, 0)), (M - 30, yy - 30), sh)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.paste(piece, (M, yy), mask)
    d.rounded_rectangle([M, yy, M + w - 1, yy + h - 1], radius=radius, outline=LINE, width=2)
    return yy + h


def footer(d, left, right="KPL 赛训工具 · v1.5.32"):
    d.line([(M, H - 128), (W - M, H - 128)], fill=LINE, width=1)
    d.text((M, H - 102), left, font=font(REG, 21), fill=MUTED)
    fw = d.textlength(right, font=font(REG, 21))
    d.text((W - M - fw, H - 102), right, font=font(REG, 21), fill=MUTED)


def value_bar(img, d, text, y=1210, size=27):
    d.rounded_rectangle([M, y, W - M, y + 96], radius=18, fill=GREEN)
    d.text((M + 32, y + 30), text, font=font(BOLD, size), fill=(244, 248, 246))


def bullets(d, y, rows, size=25):
    """rows: [(标签, 说明)]"""
    for i, (k, v) in enumerate(rows):
        yy = y + i * 62
        d.rounded_rectangle([M, yy + 8, M + 7, yy + 30], radius=3, fill=MINT)
        d.text((M + 24, yy), k, font=font(BOLD, size), fill=GREEN)
        kw = d.textlength(k, font=font(BOLD, size))
        d.text((M + 24 + kw + 16, yy + 2), v, font=font(REG, size - 2), fill=INK)


# ---------------------------------------------------------------- cards

def c1_cover():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "v1.5.32 · 大版本更新", font(BOLD, 25))
    headline(d, ["这套阵容，", "KPL 打过几次？"], 176, 92, marks=[(1, 0, 3)])
    body(d, ["以前教练只能凭感觉说「被克制」。现在能查。",
             "1.3.0 → 1.5.32，四件事：BP、对位、跨局、五路。"], 470, 27)

    end = shot_card(img, d, "bp.png", (0, 40, 2880, 1500), y=596)
    d.text((M, end + 34), "本局 BP 复盘：赛事命中 2 组，KPL 出现过", font=font(BOLD, 26), fill=GREEN)
    d.text((M, end + 78), "（坐实结论的是样本，不是形容词）", font=font(REG, 23), fill=MUTED)
    x = M
    for tag in ("BP 命中", "大盘对位", "跨局五页", "五路分开"):
        tw = d.textlength(tag, font=font(BOLD, 24)) + 44
        d.rounded_rectangle([x, end + 150, x + tw, end + 196], radius=23, outline=GREEN, width=2)
        d.text((x + 22, end + 160), tag, font=font(BOLD, 24), fill=GREEN)
        x += tw + 16
    footer(d, "数据为合成演示 · 真实界面")
    return img


def c2_bp():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "更新 01 / BP", font(BOLD, 24))
    headline(d, ["BP 不再是", "「我觉得被克制」"], 176, 72, marks=[(1, 2, 6)])
    body(d, ["本局双方的组合，去 KPL 2024 年以来的 picks 里对一遍。"], 380, 26)

    end = shot_card(img, d, "bp.png", (0, 760, 2880, 1620), y=470)
    bullets(d, end + 36, [
        ("赛事命中", "安琪拉 + 马可波罗 11 局，胜率 18.2%"),
        ("组合加成", "搭档加成 0 点的组合，直接标出来"),
        ("无样本", "没样本就写「KPL 没出现过」，不硬凑"),
    ], 24)
    value_bar(img, d, "以前：感觉被克制。现在：11 局 18.2%，查得到。")
    footer(d, "口径：KPL picks + 自训样本分开标")
    return img


def c3_vs():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "更新 02 / 对位", font(BOLD, 24))
    headline(d, ["对位压制，", "换成千强大盘。"], 176, 80, marks=[(1, 0, 5)])
    body(d, ["不再拿自家 3 局当结论：看的是「超额胜率」——",
             "实际对位胜率减去两个英雄各自基准算出的期望值。"], 380, 26)

    end = shot_card(img, d, "bp.png", (0, 1180, 2880, 1800), y=510)
    bullets(d, end + 36, [
        ("995 组", "巅峰千强同分路对位，样本 ≥200 局"),
        ("超额胜率", "≥ +2 个点判我方占优，≤ −2 判吃亏"),
        ("无大盘样本", "直接写出来，同时保留本局实际经济差"),
    ], 24)
    value_bar(img, d, "减去英雄基准，才知道是真吃亏还是本来弱。")
    footer(d, "数据：巅峰千强 matchup + hero_daily")
    return img


def c4_cross():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "更新 03 / 跨局", font(BOLD, 24))
    headline(d, ["跨局，拆成五页。", "一局一个点。"], 176, 74)
    body(d, ["这段时间 / BP 与阵容 / 五路与人 / 资源与团战 / 对手；",
             "每张卡底部「看这 N 局」展开，可导 CSV。"], 380, 26)

    end = shot_card(img, d, "cross.png", (0, 300, 2880, 1620), y=470)
    bullets(d, end + 34, [
        ("75 局 45 胜 30 负", "一个月的训练量放在一起重算"),
        ("45 : 30", "口径写在结论下方，样本不足直接说"),
    ], 24)
    value_bar(img, d, "一页塞不下一个月的训练，那就拆开看。")
    footer(d, "阶段口径：0–4 / 4–10 / 10 分钟后")
    return img


def c5_lane():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "更新 04 / 五路", font(BOLD, 24))
    headline(d, ["五路分开看，", "谁在赢很清楚。"], 176, 76, marks=[(1, 0, 3)])
    body(d, ["同一套十人表衡量五个位置是没有意义的。",
             "打野看野区、游走看控制、发育看 10 分钟经济。"], 380, 26)

    end = shot_card(img, d, "players2.png", (0, 260, 2880, 1580), y=486)
    bullets(d, end + 34, [
        ("打野", "分均 +79 金、胜率 77%，五路最能拉差距"),
        ("发育路", "分均 +114 金，领先最多的一路"),
        ("游走", "领先最少 +36 金——最容易忽略的一路"),
    ], 24)
    value_bar(img, d, "同一个数字，换个位置就是另一件事。")
    footer(d, "数据为合成演示 · 五路分均经济差")
    return img


def c6_how():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 96), "怎么更新", font(BOLD, 24))
    headline(d, ["已经装了的，", "打开就会提示。"], 176, 82)
    body(d, ["更新清单先读 Gitee（国内直连），失败再回 GitHub。",
             "数据和 camp_auth 不在更新范围，比赛记录不会被覆盖。"], 400, 26)

    rows = [("已装旧版", "右上角检查更新 → 自动下载增量包"),
            ("国内下载", "gitee.com/Rainfun42/kpl-scrim-lab-app/releases"),
            ("海外下载", "github.com/hccccc01333/kpl-scrim-lab-app/releases"),
            ("官网", "hccccc01333.github.io/kpl-scrim-lab-site")]
    y = 560
    for i, (k, v) in enumerate(rows):
        yy = y + i * 112
        d.text((M, yy), k, font=font(BOLD, 30), fill=GREEN)
        d.text((M, yy + 42), v, font=font(REG, 24), fill=MUTED)

    d.rounded_rectangle([M, 1080, W - M, 1210], radius=16, fill=CARD, outline=LINE, width=1)
    d.rounded_rectangle([M, 1080, M + 8, 1210], radius=4, fill=MINT)
    d.text((M + 30, 1104), "个人 / 教学 / 非营利免费；", font=font(REG, 25), fill=INK)
    d.text((M + 30, 1148), "俱乐部采购、付费服务、商业集成需单独授权。", font=font(REG, 25), fill=INK)
    footer(d, "Windows 10 / 11 · 免环境 · 不要管理员权限")
    return img


CARDS = [
    ("1-封面", c1_cover),
    ("2-BP", c2_bp),
    ("3-对位", c3_vs),
    ("4-跨局", c4_cross),
    ("5-五路", c5_lane),
    ("6-怎么更新", c6_how),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in CARDS:
        p = OUT / f"{name}.png"
        fn().save(p, optimize=True)
        print(p.name, f"{p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
