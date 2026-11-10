#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书「版本更新」图文（1242x1656，3:4）。

    python marketing/make_update_cards.py
产出：marketing/covers/update-1.5.30/*.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1242, 1656
M = 88
OUT = Path(__file__).resolve().parent / "covers" / "update-1.5.30"

BOLD = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
REG = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"

BG_TOP = (219, 237, 229)
BG_BOT = (234, 241, 236)
INK = (22, 33, 30)
MUTED = (96, 116, 108)
GREEN = (18, 63, 56)
MINT = (127, 224, 192)
MINT_SOFT = (205, 236, 222)
PILL_BG = (223, 240, 233)
LINE = (196, 214, 205)


def font(path, size):
    return ImageFont.truetype(path, size)


def base():
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(
            int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * k),
            int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * k),
            int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * k),
        ))
    glow = Image.new("L", (240, 240), 0)
    gd = glow.load()
    for y in range(240):
        for x in range(240):
            dx = (x - 120) / 120
            dy = (y - 120) / 120
            r = min(1.0, math.hypot(dx, dy))
            gd[x, y] = int(90 * (1 - r) ** 2)
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0),
              glow.resize((W, H), Image.BICUBIC))
    return img


def pill(d, xy, text, f, fg=GREEN, bg=PILL_BG, padx=26, pady=13):
    x, y = xy
    tw = d.textlength(text, font=f)
    h = f.size + pady * 2
    d.rounded_rectangle([x, y, x + tw + padx * 2, y + h], radius=h // 2, fill=bg)
    d.text((x + padx, y + pady - f.size * 0.14), text, font=f, fill=fg)
    return tw + padx * 2, h


def headline(d, lines, y, size=78, lead=1.28, marks=()):
    """marks: [(line_index, start, end)] 给某段文字加薄荷底色。"""
    f = font(BOLD, size)
    for i, line in enumerate(lines):
        ly = y + int(i * size * lead)
        dx = M
        for (li, s, e) in marks:
            if li != i:
                continue
            pre = line[:s]
            mid = line[s:e]
            x0 = dx + d.textlength(pre, font=f)
            w = d.textlength(mid, font=f)
            d.rounded_rectangle([x0 - 8, ly + size * 0.02, x0 + w + 8, ly + size * 1.12],
                                radius=10, fill=MINT_SOFT)
        d.text((dx, ly), line, font=f, fill=INK)


def body(d, lines, y, size=30, lead=1.62, color=MUTED):
    f = font(REG, size)
    for i, line in enumerate(lines):
        d.text((M, y + int(i * size * lead)), line, font=f, fill=color)


def chips(d, y, items, size=26):
    f = font(BOLD, size)
    x = M
    for s in items:
        tw = d.textlength(s, font=f)
        w = tw + 52
        h = size + 30
        d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, outline=GREEN, width=2)
        d.ellipse([x + 20, y + h / 2 - 5, x + 30, y + h / 2 + 5], fill=GREEN)
        d.text((x + 40, y + 15 - size * 0.14), s, font=f, fill=GREEN)
        x += w + 18


def numbers(d, y, items):
    """items: [(大数字, 说明)]，三列。"""
    colw = (W - M * 2) // len(items)
    for i, (num, label) in enumerate(items):
        x = M + i * colw
        d.text((x, y), num, font=font(BOLD, 64), fill=GREEN)
        d.text((x, y + 86), label, font=font(REG, 24), fill=MUTED)
        if i:
            d.line([(x - 26, y + 10), (x - 26, y + 118)], fill=LINE, width=1)


def items_list(d, y, rows, size=30):
    f = font(BOLD, size)
    fr = font(REG, size - 2)
    for i, (k, v) in enumerate(rows):
        yy = y + i * 96
        d.rounded_rectangle([M, yy + 8, M + 8, yy + 8 + size + 12], radius=4, fill=MINT)
        d.text((M + 26, yy), k, font=f, fill=INK)
        d.text((M + 26, yy + size + 20), v, font=fr, fill=MUTED)


def footer(d, left, right="Windows 10 / 11 · v1.5.30"):
    d.line([(M, H - 132), (W - M, H - 132)], fill=LINE, width=1)
    d.text((M, H - 106), left, font=font(REG, 24), fill=MUTED)
    fw = d.textlength(right, font=font(REG, 24))
    d.text((W - M - fw, H - 106), right, font=font(REG, 24), fill=MUTED)


def note_box(d, y, text, size=26):
    f = font(REG, size)
    pad = 26
    w = W - M * 2
    lines = text.split("\n")
    h = pad * 2 + len(lines) * int(size * 1.55)
    d.rounded_rectangle([M, y, M + w, y + h], radius=16, fill=(255, 255, 255),
                        outline=LINE, width=1)
    d.rounded_rectangle([M, y, M + 8, y + h], radius=4, fill=MINT)
    for i, line in enumerate(lines):
        d.text((M + 30, y + pad + i * size * 1.55), line, font=f, fill=INK)
    return h


# ---------------------------------------------------------------- cards

def card_cover():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "1.3.0  →  1.5.30", font(BOLD, 28))
    headline(d, ["两个版本之间，", "加了三十次更新。"], 236, 82, marks=[(1, 2, 4)])
    body(d, ["识别 · 回放 · 分路 · 跨局 · BP · 赛训"], 470, 30)

    d.rounded_rectangle([M, 560, W - M, 1180], radius=28, fill=(255, 255, 255),
                        outline=LINE, width=1)
    rows = [("01", "识别", "93.6% → 100%，压缩图会提示重传"),
            ("02", "回放", "控龙率、事件伤害占比、反野、切 C"),
            ("03", "分路", "每个位置只看自己该看的指标"),
            ("04", "跨局 & BP", "四个页签；组合卡 + 大盘对位 + 赛事命中")]
    for i, (num, k, v) in enumerate(rows):
        y = 596 + i * 140
        d.text((M + 46, y), num, font=font(BOLD, 26), fill=(140, 170, 158))
        d.text((M + 120, y - 6), k, font=font(BOLD, 40), fill=INK)
        d.text((M + 120, y + 56), v, font=font(REG, 25), fill=MUTED)
        if i < 3:
            d.line([(M + 46, y + 112), (W - M - 46, y + 112)], fill=(232, 240, 235), width=1)

    chips(d, 1234, ["Windows · 免环境", "数据不出本机"])
    footer(d, "hccccc01333.github.io/kpl-scrim-lab-site")
    return img


def card_ocr():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "01 / 识别", font(BOLD, 26))
    headline(d, ["截图识别，", "从 93.6% 到 100%。"], 226, 80)
    body(d, ["220 个数值字段的人工标注基准；压缩、降分辨率这类劣化条件下，",
             "捆绑级（七页合并）仍守住 98%+。"], 442)

    numbers(d, 566, [("220", "个人工标注字段"), ("100%", "干净原图"), ("98%+", "劣化图")])

    d.rounded_rectangle([M, 726, W - M, 900], radius=20, fill=GREEN)
    d.text((M + 40, 762), "微信 / QQ 转发会把图压到 70–80 画质", font=font(BOLD, 30),
           fill=(244, 248, 246))
    d.text((M + 40, 818), "识别前就提示你：勾「原图」，或者用文件方式重传。",
           font=font(REG, 26), fill=MINT)

    note_box(d, 950, "OCR 出的是候选值，逐项确认才入库。\n"
                     "识别错一个数比没有数更危险，所以这一步不省。")
    footer(d, "基准：scripts/eval_ocr_accuracy.py · 本地跑")
    return img


def card_replay():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "02 / 回放", font(BOLD, 26))
    headline(d, ["回放接进来，", "单局多了一整层。"], 226, 80)
    body(d, ["官方回放同步时自动补齐，不再要你单独传文件。"], 442)

    rows = [("资源控制", "暴君 / 暗影暴君 / 暗影主宰 / 防御塔 + 控龙率"),
            ("事件详情", "每波团战的参战者、伤害量与占比"),
            ("反野与被反", "按 BUFF 事件算归属，不靠猜"),
            ("切 C 与击杀账本", "谁杀了谁、对位经济差多少")]
    items_list(d, 560, rows, 29)

    note_box(d, 1046, "没有回放的局整块隐藏，不补 0；\n"
                      "营地复盘里的中文评述也一并接进来。")
    footer(d, "数据：官方回放 + 营地 battledetail")
    return img


def card_lane():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "03 / 分路", font(BOLD, 26))
    headline(d, ["每个位置，", "只看自己该看的。"], 226, 80)
    body(d, ["分路指标集：不再用一张十人表衡量五个位置。"], 442)

    rows = [("打野", "野怪经济、反野次数、过河时间占比"),
            ("游走", "控制时长、治疗量、每死承伤"),
            ("对抗路", "对塔伤害、分均经济、死亡数"),
            ("发育路", "10 分钟经济、分均输出、参团率")]
    items_list(d, 560, rows, 29)

    note_box(d, 1046, "分路评估按教练的 Excel 口径落：680 / 700 / 740 分档，\n"
                      "死亡超过 2 次标红——先看红，再看数。")
    footer(d, "口径：docs/ 下分路指标说明")
    return img


def card_cross():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "04 / 跨局", font(BOLD, 26))
    headline(d, ["跨局拆成四页，", "一局一个点。"], 226, 78)
    body(d, ["原来一页塞下所有东西，现在按「你在问什么」拆开。",
             "共性改成散点：一局一个点，按开赛时间横向排开。"], 442)

    rows = [("这段时间", "一局一点；赢的局输的局差在哪、钱是哪一段挣的"),
            ("BP 与阵容", "禁用习惯、阵容构成、英雄账本"),
            ("五路与人", "分路指标、选手榜、位置对位"),
            ("对手", "按对手名分组：胜负、10 分钟差、时长")]
    items_list(d, 600, rows, 29)

    note_box(d, 1046, "阶段口径回到教练定义的三段：0–4 对线 / 4–10 发育 / 10 分钟后；\n"
                      "「看这 N 局」展开后可导出 CSV。")
    footer(d, "口径：教练 2026-11-10 反馈")
    return img


def card_bp():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "05 / BP", font(BOLD, 26))
    headline(d, ["这套阵容，", "KPL 打过几次。"], 226, 80)
    body(d, ["本局双方的二人 / 三人组合，去 KPL 2024 年以来的 picks 里对一遍；",
             "对位压制改用巅峰千强同分路大盘，看超额胜率。"], 442)

    numbers(d, 566, [("4,586", "局可判定"), ("3,386", "双人组合"), ("995", "组同分路对位")])

    d.rounded_rectangle([M, 726, W - M, 900], radius=20, fill=GREEN)
    d.text((M + 40, 762), "钟馗 + 项羽 · 4 局 100%", font=font(BOLD, 30), fill=(244, 248, 246))
    d.text((M + 40, 812), "本队 10 组双人里，3 组在 KPL 出现过", font=font(REG, 26), fill=MINT)

    note_box(d, 950, "瑶对位 47% 可能不是被克制——她本来胜率就低。\n"
                     "减去两个英雄的基准，才看得出谁真的吃亏。")
    footer(d, "数据：KPL picks + 巅峰千强 matchup")
    return img


def card_plan():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "06 / 赛训", font(BOLD, 26))
    headline(d, ["赛训板块，", "从计划改成比赛。"], 226, 80)
    body(d, ["训练课按比赛排：目标、出勤、复盘状态都挂在那一局上。"], 442)

    rows = [("训练课", "按日期 + 对手关联对局，可手动挂局"),
            ("目标", "绑定指标 + 目标值，保存时自动判定达成"),
            ("报告", "训练课报告、周报，可导 PDF"),
            ("看板", "近 8 周训练负荷、目标达成环、复盘覆盖率")]
    items_list(d, 560, rows, 29)

    note_box(d, 1046, "胜率和场均时长只作为「对局上下文」，\n"
                      "赛训主 KPI 是训练过程——这是教练组自己的要求。")
    footer(d, "口径：metrics_registry 统一登记")
    return img


def card_how():
    img = base()
    d = ImageDraw.Draw(img)
    pill(d, (M, 104), "怎么更新", font(BOLD, 26))
    headline(d, ["已经装了的，", "打开就会提示。"], 226, 80)
    body(d, ["更新清单先读 Gitee（国内直连），失败再回 GitHub。",
             "数据与 camp_auth 不在更新范围，比赛记录不会被覆盖。"], 442)

    rows = [("已装旧版", "右上角检查更新 → 自动下载增量包"),
            ("新用户 · 国内", "gitee.com/Rainfun42/kpl-scrim-lab-app/releases"),
            ("新用户 · 海外", "github.com/hccccc01333/kpl-scrim-lab-app/releases"),
            ("官网", "hccccc01333.github.io/kpl-scrim-lab-site")]
    items_list(d, 620, rows, 25)

    note_box(d, 1058, "个人 / 教学 / 非营利免费；\n"
                      "俱乐部采购、付费服务、商业集成需单独授权。")
    footer(d, "本图文数据均为合成演示数据")
    return img


CARDS = [
    ("1-封面", card_cover),
    ("2-识别", card_ocr),
    ("3-回放", card_replay),
    ("4-分路", card_lane),
    ("5-跨局", card_cross),
    ("6-BP", card_bp),
    ("7-赛训", card_plan),
    ("8-怎么更新", card_how),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in CARDS:
        p = OUT / f"{name}.png"
        fn().save(p, optimize=True)
        print(p.name, f"{p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
