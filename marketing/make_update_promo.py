#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书「版本更新 × 宣传」图文（1242x1656）。

不是公告体，是「这次更新解决了什么」：每条都用 以前 / 现在 对照，
中间插一页可收藏的干货，封面用结果而不是版本号。

    python marketing/make_update_promo.py
产出：marketing/covers/update-1.5.30-promo/*.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1242, 1656
M = 88
OUT = Path(__file__).resolve().parent / "covers" / "update-1.5.30-promo"

BOLD = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
REG = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"

INK = (22, 33, 30)
MUTED = (96, 116, 108)
DIM = (140, 166, 155)
GREEN = (18, 63, 56)
MINT = (127, 224, 192)
MINT_SOFT = (205, 236, 222)
PILL_BG = (223, 240, 233)
LINE = (196, 214, 205)
BG_TOP = (219, 237, 229)
BG_BOT = (234, 241, 236)


def font(path, size):
    return ImageFont.truetype(path, size)


def base(dark=False):
    if dark:
        top, bot = (16, 34, 30), (9, 22, 19)
    else:
        top, bot = BG_TOP, BG_BOT
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(
            int(top[0] + (bot[0] - top[0]) * k),
            int(top[1] + (bot[1] - top[1]) * k),
            int(top[2] + (bot[2] - top[2]) * k)))
    glow = Image.new("L", (200, 200), 0)
    gd = glow.load()
    for y in range(200):
        for x in range(200):
            dx = (x - 100) / 100
            dy = (y - 100) / 100
            gd[x, y] = int((44 if dark else 80) * (1 - min(1.0, math.hypot(dx, dy))) ** 2)
    img.paste(Image.new("RGB", (W, H), (120, 200, 175) if dark else (255, 255, 255)),
              (0, 0), glow.resize((W, H), Image.BICUBIC))
    return img


def pill(d, xy, text, f, fg=GREEN, bg=PILL_BG, padx=24, pady=12):
    x, y = xy
    tw = d.textlength(text, font=f)
    h = f.size + pady * 2
    d.rounded_rectangle([x, y, x + tw + padx * 2, y + h], radius=h // 2, fill=bg)
    d.text((x + padx, y + pady - f.size * 0.14), text, font=f, fill=fg)


def headline(d, lines, y, size=84, lead=1.26, marks=(), color=INK):
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
        d.text((M, ly), line, font=f, fill=color)


def body(d, lines, y, size=30, lead=1.6, color=MUTED):
    f = font(REG, size)
    for i, line in enumerate(lines):
        d.text((M, y + int(i * size * lead)), line, font=f, fill=color)


def before_after(d, y, rows, gap=170):
    """rows: [(以前, 现在)]"""
    f_b = font(BOLD, 33)
    f_n = font(BOLD, 35)
    for i, (before, after) in enumerate(rows):
        yy = y + i * gap
        d.text((M, yy), "以前", font=font(BOLD, 22), fill=DIM)
        d.text((M + 84, yy - 8), before, font=f_b, fill=MUTED)
        d.text((M, yy + 58), "现在", font=font(BOLD, 22), fill=(90, 150, 128))
        d.text((M + 84, yy + 48), after, font=f_n, fill=INK)
        if i < len(rows) - 1:
            d.line([(M, yy + gap - 44), (W - M, yy + gap - 44)], fill=(226, 236, 230), width=1)


def numbers(d, y, items, color=GREEN):
    colw = (W - M * 2) // len(items)
    for i, (num, label) in enumerate(items):
        x = M + i * colw
        d.text((x, y), num, font=font(BOLD, 62), fill=color)
        d.text((x, y + 84), label, font=font(REG, 23), fill=MUTED)
        if i:
            d.line([(x - 24, y + 8), (x - 24, y + 112)], fill=LINE, width=1)


def note_box(d, y, lines, size=26, fill=(255, 255, 255)):
    f = font(REG, size)
    pad = 24
    h = pad * 2 + len(lines) * int(size * 1.6)
    d.rounded_rectangle([M, y, W - M, y + h], radius=16, fill=fill, outline=LINE, width=1)
    d.rounded_rectangle([M, y, M + 8, y + h], radius=4, fill=MINT)
    for i, line in enumerate(lines):
        d.text((M + 30, y + pad + i * size * 1.6), line, font=f, fill=INK)
    return h


def footer(d, left, right="KPL 赛训工具 · v1.5.30"):
    d.line([(M, H - 132), (W - M, H - 132)], fill=LINE, width=1)
    d.text((M, H - 106), left, font=font(REG, 22), fill=MUTED)
    fw = d.textlength(right, font=font(REG, 22))
    d.text((W - M - fw, H - 106), right, font=font(REG, 22), fill=MUTED)


# ---------------------------------------------------------------- cards

def c1_cover():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "v1.5.30 · 更新", font(BOLD, 26))
    headline(d, ["这次更新，", "把「感觉」", "换成了数字。"], 214, 88,
             marks=[(2, 3, 5)])
    body(d, ["1.3.0 → 1.5.30，三十次更新里最值得说的四件事：",
             "BP、对位、跨局、回放。"], 576, 29)

    d.rounded_rectangle([M, 700, W - M, 1150], radius=26, fill=(255, 255, 255),
                        outline=LINE, width=1)
    rows = [("BP", "这套阵容 KPL 打过几次"),
            ("对位", "减去英雄基准，谁真的吃亏"),
            ("跨局", "75 局放在一起，一局一个点"),
            ("回放", "控龙率、反野、切 C 都能看了")]
    for i, (k, v) in enumerate(rows):
        y = 744 + i * 96
        d.text((M + 44, y), k, font=font(BOLD, 32), fill=GREEN)
        d.text((M + 168, y + 4), v, font=font(REG, 26), fill=MUTED)

    numbers(d, 1214, [("4,586", "局 KPL"), ("995", "组对位"), ("220", "个字段")])
    footer(d, "数据：KPL picks + 巅峰千强 + 回放事件")
    return img


def c2_today():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "为什么做这次更新", font(BOLD, 26))
    d.text((M, 196), "教练的原话：", font=font(BOLD, 52), fill=INK)

    # 引语块
    d.rounded_rectangle([M, 292, M + 8, 500], radius=4, fill=MINT)
    d.text((M + 40, 292), "「我知道有问题，", font=font(BOLD, 62), fill=GREEN)
    d.text((M + 40, 386), "  但我拿不出数。」", font=font(BOLD, 62), fill=GREEN)

    body(d, ["这不是教练的问题，是工具的问题——",
             "赛训数据一直在，只是到不了能复盘的状态。"], 560, 28)

    before_after(d, 688, [
        ("这局 BP 感觉被克制", "这套组合 KPL 打过 40 次，胜率多少"),
        ("对线好像打不过", "减去英雄基准，超额胜率 −6 个点"),
        ("这个人最近状态差", "近 5 局分均经济掉了 12%"),
        ("这波团输在少人", "那一波 4 打 5，伤害占比 38%"),
    ], gap=140)
    footer(d, "本片数据均为合成演示")
    return img


def c3_method():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "顺便送一页干货", font(BOLD, 26))
    headline(d, ["教练复盘，", "先看这 3 个数。"], 214, 84, marks=[(1, 3, 6)])
    body(d, ["不是胜率，也不是 KDA——是三件最容易被跳过的事。"], 470, 29)

    items = [("10 分钟经济差", "对线期结束那一刻，钱差多少；这一条基本决定后面 10 分钟"),
             ("控龙率", "暴君 / 暗影暴君 / 暗影主宰谁在拿；控龙率低于 40% 的局很少赢"),
             ("掉点位置", "人死在哪、死后经济掉了多少；连续两次同一片野区，就是视野问题")]
    y = 560
    for i, (k, v) in enumerate(items):
        d.text((M, y), f"{i+1:02d}", font=font(BOLD, 26), fill=DIM)
        d.text((M + 66, y - 8), k, font=font(BOLD, 42), fill=INK)
        for j, line in enumerate(v.split("；")):
            d.text((M + 66, y + 54 + j * 38), line + ("；" if j == 0 and "；" in v else ""),
                   font=font(REG, 24), fill=MUTED)
        y += 190

    note_box(d, 1180, ["这三个数，工具的「单局复盘」一页里都有。",
                       "翻到第 4 张，看这次更新怎么把它们做进去。"])
    footer(d, "口径：赛训组 2026-11 反馈")
    return img


def c4_bp():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "更新 01 / BP", font(BOLD, 26))
    headline(d, ["「被克制」这三个字，", "终于能查了。"], 214, 76, marks=[(0, 1, 4)])
    body(d, ["以前只能凭感觉；现在把本局的二人 / 三人组合，", "去 KPL 2024 年以来的 picks 里对一遍。"], 420, 28)

    before_after(d, 540, [
        ("凭印象说「这组合被克」", "4,586 局里查得到场次与胜率"),
        ("不知道这套阵容强不强", "组合卡：钟馗 + 项羽 4 局 100%"),
        ("对位吃亏说不清", "995 组大盘对位，带超额胜率"),
    ], gap=160)

    numbers(d, 1060, [("4,586", "局可判定"), ("3,386", "双人组合"), ("10,495", "三人组合")])
    note_box(d, 1216, ["超额胜率 = 实际对位胜率 − 两个英雄基准算出的期望胜率。",
                       "瑶对位 47% 可能不是被克制，是她本来胜率就低。"], size=23)
    footer(d, "数据：KPL picks + 巅峰千强 matchup")
    return img


def c5_cross():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "更新 02 / 跨局", font(BOLD, 26))
    headline(d, ["一页塞不下", "一个月的训练。", "那就拆成四页。"], 190, 74)
    body(d, ["以前跨局页什么都往里堆，看完还是不知道结论。", "现在按「你在问什么」分：这段时间 / BP 与阵容 / 五路与人 / 对手。"], 506, 27)

    rows = [("一屏十几个图表", "一局一个点，按开赛时间排开"),
            ("不知道哪一局出了问题", "异常局单独列：超长、逆风翻、领先被翻"),
            ("导出要手工抄", "「看这 N 局」展开后直接导 CSV"),
            ("钱是从哪段挣的说不出", "按 0–4 / 4–10 / 10 分钟后分段")]
    before_after(d, 650, rows, gap=140)
    footer(d, "口径：教练定义的三个阶段")
    return img


def c6_replay():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "更新 03 / 回放", font(BOLD, 26))
    headline(d, ["回放接进来，", "输的那波团", "终于看得见。"], 190, 78, marks=[(2, 0, 5)])
    body(d, ["官方回放同步时自动补齐，不用你单独传文件。"], 470, 28)

    rows = [("资源控制", "暴君 / 暗影暴君 / 暗影主宰 / 防御塔 + 控龙率"),
            ("事件详情", "每波团战的参战者、伤害量与占比"),
            ("反野与被反", "按 BUFF 事件算归属，不靠猜"),
            ("切 C 与击杀账本", "谁杀了谁、对位经济差多少")]
    y = 560
    for i, (k, v) in enumerate(rows):
        yy = y + i * 130
        d.rounded_rectangle([M, yy + 6, M + 8, yy + 52], radius=4, fill=MINT)
        d.text((M + 28, yy), k, font=font(BOLD, 34), fill=INK)
        d.text((M + 28, yy + 52), v, font=font(REG, 25), fill=MUTED)

    note_box(d, 1170, ["没有回放的局整块隐藏，不补 0。",
                       "营地复盘里的中文评述也一并接进来了。"])
    footer(d, "数据：官方回放 + 营地 battledetail")
    return img


def c7_plan():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "更新 04 / 赛训", font(BOLD, 26))
    headline(d, ["赛训板块，", "从「计划」", "改成比赛。"], 200, 80)
    body(d, ["训练课按比赛排：目标、出勤、复盘状态都挂在那一局上。"], 536, 28)

    before_after(d, 620, [
        ("训练计划是一张表", "训练课直接挂对局，点开就是那一局"),
        ("目标达没达成靠人记", "绑定指标 + 目标值，保存时自动判定"),
        ("复盘做没做没人知道", "复盘覆盖率进看板，周报里直接列"),
        ("报告要自己拼", "训练课报告、周报，可导 PDF"),
    ], gap=150)
    footer(d, "口径：metrics_registry 统一登记")
    return img


def c8_how():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "谁适合用", font(BOLD, 26))
    headline(d, ["不是给所有人用的。", "带队的才用得上。"], 214, 78)
    body(d, ["如果你每周要看好几场训练赛、要给队员讲清楚哪里亏了——", "这套东西省的就是你抄数和核对的时间。"], 420, 28)

    rows = [("适合", "KPL / 次级联赛 / 城市赛 / 青训的赛训组"),
            ("不适合", "想一键出结论、不想核对数据的人"),
            ("系统", "Windows 10 / 11，免环境，不要管理员权限"),
            ("数据", "全部在本机，一个 data 目录就是完整备份")]
    y = 540
    for i, (k, v) in enumerate(rows):
        yy = y + i * 106
        d.text((M, yy), k, font=font(BOLD, 30), fill=GREEN)
        d.text((M + 120, yy + 4), v, font=font(REG, 25), fill=MUTED)

    note_box(d, 1000, [
        "已经装了的：打开工作台 → 右上角检查更新",
        "国内下载：gitee.com/Rainfun42/kpl-scrim-lab-app/releases",
        "海外下载：github.com/hccccc01333/kpl-scrim-lab-app/releases",
        "官网：hccccc01333.github.io/kpl-scrim-lab-site",
    ], size=23)
    footer(d, "个人 / 教学 / 非营利免费 · 商用需授权")
    return img


CARDS = [
    ("1-封面", c1_cover),
    ("2-为什么更新", c2_today),
    ("3-干货三个数", c3_method),
    ("4-BP", c4_bp),
    ("5-跨局", c5_cross),
    ("6-回放", c6_replay),
    ("7-赛训", c7_plan),
    ("8-谁适合用", c8_how),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in CARDS:
        p = OUT / f"{name}.png"
        fn().save(p, optimize=True)
        print(p.name, f"{p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
