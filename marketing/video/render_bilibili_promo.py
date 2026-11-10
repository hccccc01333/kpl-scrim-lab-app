#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站宣传片渲染器（1920x1080 / 30fps / 88s）。

用法：
    python render_bilibili_promo.py --preview 3,9,19,27,37,47,57,67,75,84
    python render_bilibili_promo.py --render            # 输出成片 mp4

画面全部由 PIL 直接绘制：深绿底 + 网格 + 真实界面截图 + 硬字幕。
音频用 dist/scrim-promo-v6/mix.wav（Scott Buckley《Neon》，CC-BY 4.0），
剪辑时做过增益与淡入淡出。
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

FONT_B = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
FONT_R = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"
FONT_MONO = r"C:\Windows\Fonts\consola.ttf"

C_BG = (13, 37, 33)
C_INK = (244, 248, 246)
C_MUTED = (150, 174, 166)
C_DIM = (104, 128, 121)
C_MINT = (127, 224, 192)
C_SAND = (232, 199, 156)
C_CARD = (22, 52, 46)
C_LINE = (255, 255, 255, 26)


# ---------------------------------------------------------------- 基础工具

def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def seg(t, start, dur):
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in(p):
    return p ** 3


def ease_io(p):
    return 3 * p * p - 2 * p * p * p


@lru_cache(maxsize=2048)
def tline(s, size, bold=True, color=C_INK, tracking=0):
    """把一行字渲染成 RGBA 小图（缓存）。"""
    font = ImageFont.truetype(FONT_B if bold else FONT_R, size)
    pad = int(size * 0.45)
    if tracking:
        widths = [font.getlength(ch) for ch in s]
        w = int(sum(widths) + tracking * (len(s) - 1)) + pad * 2
    else:
        w = int(font.getlength(s)) + pad * 2
    h = int(size * 1.55) + pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tracking:
        x = pad
        for ch, cw in zip(s, widths):
            d.text((x, pad * 0.5), ch, font=font, fill=color + (255,))
            x += cw + tracking
    else:
        d.text((pad, pad * 0.5), s, font=font, fill=color + (255,))
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def put(canvas, tile, x, y, alpha=1.0, anchor="lt"):
    if alpha <= 0.004 or tile is None:
        return
    if anchor == "ct":
        x -= tile.width / 2
    elif anchor == "rt":
        x -= tile.width
    x, y = int(round(x)), int(round(y))
    if alpha < 0.996:
        tile = tile.copy()
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(tile, (x, y))


def text(canvas, s, size, x, y, color=C_INK, bold=True, alpha=1.0,
         anchor="lt", tracking=0):
    put(canvas, tline(s, size, bold, color, tracking), x, y, alpha, anchor)


def solid(canvas, box, color):
    """半透明实心矩形（必须走 alpha_composite，ImageDraw 在 RGBA 上是覆盖不是混合）。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    if x1 <= x0 or y1 <= y0 or color[3] == 0:
        return
    canvas.alpha_composite(Image.new("RGBA", (x1 - x0, y1 - y0), color), (x0, y0))


def rule(canvas, x, y, w, color=(255, 255, 255, 40), h=1):
    solid(canvas, [x, y, x + w, y + h], color)


@lru_cache(maxsize=8)
def make_bg():
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W + 1, 80):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 5))
    for y in range(0, H + 1, 80):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 5))
    small = Image.new("L", (64, 36), 0)
    px = small.load()
    for j in range(36):
        for i in range(64):
            dx = (i - 31.5) / 31.5
            dy = (j - 17.5) / 17.5
            r = min(1.0, math.hypot(dx, dy) / 1.32)
            px[i, j] = int(168 * (r ** 2.2))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0),
              small.resize((W, H), Image.BICUBIC))
    return img.convert("RGBA")


@lru_cache(maxsize=64)
def _shadow(w, h, radius, blur, strength):
    pad = blur * 2
    img = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    ImageDraw.Draw(img).rounded_rectangle(
        [pad, pad, pad + w, pad + h], radius=radius, fill=strength)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.putalpha(img)
    return out


@lru_cache(maxsize=32)
def load_img(path):
    return Image.open(path).convert("RGB")


def cover_crop(im, ar, focus=(0.5, 0.5), zoom=1.0):
    iw, ih = im.size
    src_ar = iw / ih
    if src_ar > ar:
        ch = ih / zoom
        cw = ch * ar
    else:
        cw = iw / zoom
        ch = cw / ar
    cx, cy = iw * focus[0], ih * focus[1]
    x0 = clamp(cx - cw / 2, 0, iw - cw)
    y0 = clamp(cy - ch / 2, 0, ih - ch)
    return im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))


def shot(canvas, path, box, alpha=1.0, zoom=1.0, focus=(0.5, 0.5),
         radius=14, shadow=0.55, border=1.0):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    if alpha <= 0.004 or w <= 4 or h <= 4:
        return
    im = load_img(os.path.join(ROOT, path))
    crop = cover_crop(im, w / h, focus, zoom).resize((w, h), Image.LANCZOS)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    tile = crop.convert("RGBA")
    tile.putalpha(mask)

    if shadow > 0:
        sh = _shadow(w, h, radius, 26, int(255 * shadow * alpha))
        canvas.alpha_composite(sh, (x0 - 52, y0 - 52 + 18))

    if alpha < 0.996:
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(tile, (x0, y0))

    d = ImageDraw.Draw(canvas, "RGBA")
    if border > 0:
        canvas.alpha_composite(_outline(w, h, radius, int(26 * alpha * border)), (x0, y0))


@lru_cache(maxsize=16)
def _outline(w, h, radius, alpha):
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                                            outline=(255, 255, 255, alpha), width=1)
    return layer


def pill(canvas, s, size, x, y, alpha=1.0, color=C_MUTED, bg=(255, 255, 255, 16),
         border=(255, 255, 255, 34), anchor="lt", padx=22, pady=11):
    tile = tline(s, size, False, color, 0)
    w, h = tile.width + padx * 2, tile.height + pady * 2
    if anchor == "ct":
        x -= w / 2
    elif anchor == "rt":
        x -= w
    x, y = int(x), int(y)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=bg[:3] + (int(bg[3] * alpha),),
                        outline=border[:3] + (int(border[3] * alpha),), width=1)
    layer.alpha_composite(tile, (padx, pady))
    if alpha < 0.996:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(layer, (x, y))
    return w


def kicker(canvas, s, alpha=1.0, x=148, y=132):
    """小节标签：一条竖线 + 字距拉开的标题。"""
    solid(canvas, [x, y + 6, x + 3, y + 34], C_MINT[:3] + (int(255 * alpha),))
    text(canvas, s, 21, x + 18, y + 8, C_MINT, True, alpha, tracking=5)


def card(canvas, box, alpha=1.0, fill=(255, 255, 255, 12), border=(255, 255, 255, 26),
         radius=14):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    if w <= 2 or h <= 2 or alpha <= 0.004:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=radius,
        fill=fill[:3] + (int(fill[3] * alpha),),
        outline=border[:3] + (int(border[3] * alpha),), width=1)
    canvas.alpha_composite(layer, (x0, y0))


# ---------------------------------------------------------------- 分镜

SCENES = []


def scene(dur):
    def deco(fn):
        SCENES.append((dur, fn))
        return fn
    return deco


ASSET = "marketing/video/shots/"
M = ASSET + "m/"


def module_scene(kicker_text, title, items, side="right", step=2.4, tail=1.8):
    """一侧是功能清单（当前项高亮），另一侧跟着换截图。"""
    n = len(items)
    dur = n * step + tail
    left = side == "right"          # 文字在左，图在右
    tx = 148 if left else 1282
    panel = [680, 168, 1848, 900] if left else [72, 168, 1240, 900]

    def draw(c, t):
        kicker(c, kicker_text, ease_out(seg(t, 0.15, 0.5)), x=tx, y=132)
        text(c, title, 34, tx, 196, C_INK, True, ease_out(seg(t, 0.3, 0.6)))

        idx = min(n - 1, int(max(0.0, t - 0.8) / step))
        for i, (name, desc, _img) in enumerate(items):
            a = ease_out(seg(t, 0.7 + i * 0.12, 0.45))
            if a <= 0:
                continue
            active = i == idx
            y = 316 + i * 92
            if active:
                solid(c, [tx - 22, y + 2, tx - 18, y + 60],
                      (127, 224, 192, int(255 * a)))
            text(c, name, 27, tx, y, C_MINT if active else C_MUTED, True, a)
            text(c, desc, 19, tx, y + 40, C_INK if active else C_DIM, False, a)

        path = items[idx][2]
        local = max(0.0, t - 0.8 - idx * step)
        a = ease_out(clamp(local / 0.38)) if idx else ease_out(seg(t, 0.5, 0.8))
        shot(c, M + path, panel, a, zoom=1.0 + 0.02 * clamp(local / step),
             focus=(0.5, 0.38), radius=14, shadow=0.5)

    draw.__scenes_dur = dur
    return dur, draw


@scene(5.5)
def s0_hook(c, t):
    text(c, "赛训组的工作，", 46, W / 2, 392, C_MUTED, False,
         ease_out(seg(t, 0.15, 0.7)), "ct")
    text(c, "不该只有一张 Excel。", 66, W / 2, 470, C_INK, True,
         ease_out(seg(t, 1.6, 0.8)), "ct")


@scene(7.5)
def s1_collect(c, t):
    kicker(c, "采集", ease_out(seg(t, 0.15, 0.5)))
    text(c, "四种来源，同一条链路。", 52, 148, 196, C_INK, True, ease_out(seg(t, 0.4, 0.6)))

    rows = [("营地链接", "扫码授权，增量拉十人面板，不走 OCR"),
            ("七页截图", "同一局七张结算图，本机 OCR 出候选值"),
            ("整段录屏", "1 倍速整局，逐帧抽帧识别"),
            ("表格 xlsx", "字段契约校验，对不上直接拦下")]
    for i, (name, desc) in enumerate(rows):
        a = ease_out(seg(t, 0.9 + i * 0.28, 0.5))
        if a <= 0:
            continue
        y = 320 + i * 118
        solid(c, [148, y + 4, 152, y + 74], C_MINT[:3] + (int(255 * a),))
        text(c, name, 34, 180, y, C_INK, True, a)
        text(c, desc, 22, 180, y + 46, C_MUTED, False, a)

    text(c, "后续所有页面，都从这四条来路里取数。", 21, 148, 900, C_DIM, False,
         ease_out(seg(t, 2.6, 0.6)))

    # 右侧：四条来源汇到同一条链路
    flow = [("同一份草稿", "来源并列，冲突不合并"),
            ("逐项校对", "候选值确认后才成为记录"),
            ("正式统计", "审核通过，写进单局数据包")]
    for i, (name, desc) in enumerate(flow):
        a = ease_out(seg(t, 2.2 + i * 0.45, 0.55))
        if a <= 0:
            continue
        y = 330 + i * 170
        card(c, [1180, y, 1800, y + 124], a)
        text(c, name, 28, 1212, y + 26, C_INK, True, a)
        text(c, desc, 18, 1212, y + 72, C_MUTED, False, a)
        if i:
            solid(c, [1488, y - 46, 1490, y - 6], (127, 224, 192, int(120 * a)))


# ---- 各模块：文字清单 + 一页一图 -------------------------------------

D, F = module_scene(
    "对局", "单局看，也跨局看。",
    [("对局档案", "按日期、对手、版本、训练组筛", "matches-archive.png"),
     ("跨局分析", "一局一块，同口径重算", "matches-cross.png"),
     ("智能找局", "按条件把历史里的局翻出来", "matches-find.png"),
     ("训练纪录", "极值卡与均值偏离", "matches-records.png"),
     ("版本对比", "同一套指标跨版本对照", "matches-version.png")],
    side="right")
scene(D)(F)

D, F = module_scene(
    "BP", "BP 不是猜的。",
    [("BP 概览", "禁用榜、优先级、版本答案", "bp-overview.png"),
     ("战队 BP", "每个对手的禁用与选人习惯", "bp-team.png"),
     ("教练档案", "教练带过的阵容与胜率", "bp-coach.png")],
    side="left")
scene(D)(F)

D, F = module_scene(
    "英雄", "105 个英雄，谁该进池子。",
    [("英雄榜", "出场、胜率、分档与协同", "heroes-rank.png"),
     ("英雄对比", "两个英雄并排看数据", "heroes-compare.png"),
     ("英雄组合", "双人 / 三人组合的协同加成", "heroes-combo.png")],
    side="right")
scene(D)(F)

D, F = module_scene(
    "选手", "谁在打，状态往哪走。",
    [("选手档案", "跨局趋势、英雄池、稳健偏差", "players-archive.png"),
     ("名单与状态", "本期出场、可跨局比较的人", "players-status.png"),
     ("选手与位置", "分路指标：分均、经济转输出", "players-lanes.png"),
     ("选手对比", "同位置两人并排对位", "players-compare.png")],
    side="left")
scene(D)(F)

D, F = module_scene(
    "战队", "对手是谁，比什么都重要。",
    [("战队档案", "五项得分、阵容、英雄池、逐局", "teams-profile.png"),
     ("战队风格", "节奏 / 团战 / 运营 / 后期分位", "teams-style.png"),
     ("战队阵容", "五人组、位置池与轮换", "teams-lineup.png"),
     ("战队训练", "按对手汇总训练课与交手", "teams-training.png")],
    side="right")
scene(D)(F)

D, F = module_scene(
    "赛训", "训练不是打完就完。",
    [("训练计划", "排期、目标、出勤与复盘状态", "plan-schedule.png"),
     ("数据准备", "建档、对手归属、待确认字段", "plan-prep.png"),
     ("复盘与报告", "训练课报告、周报，可导 PDF", "plan-report.png")],
    side="left")
scene(D)(F)

D, F = module_scene(
    "数据来源", "每个字段，都能回到出处。",
    [("来源库存", "营地 / 官方回放 / 表格 / 录屏覆盖多少", "sources.png")],
    side="right")
scene(D + 2.0)(F)


@scene(8.0)
def s9_trust(c, t):
    kicker(c, "数据口径", ease_out(seg(t, 0.15, 0.5)))
    text(c, "每个数字都标来源。", 42, 148, 190, C_INK, True, ease_out(seg(t, 0.4, 0.6)))
    text(c, "四档标签一直挂在界面里，从可靠到不可靠。", 21, 148, 252, C_MUTED, False,
         ease_out(seg(t, 0.8, 0.6)))

    tags = [("文件解码", 320, 148), ("引擎实测", 320, 372),
            ("UI 采样", 392, 148), ("估算", 392, 372)]
    for i, (name, y, x) in enumerate(tags):
        a = ease_out(seg(t, 1.0 + i * 0.2, 0.45))
        if a > 0:
            pill(c, name, 22, x, y + (1 - a) * 8, a, C_MINT,
                 (127, 224, 192, 16), (127, 224, 192, 62))

    text(c, "对不上并列显示，不取平均；缺失留空，不补零。", 21, 148, 500, C_MUTED, False,
         ease_out(seg(t, 2.0, 0.6)))

    a = ease_out(seg(t, 1.3, 0.8))
    if a > 0:
        card(c, [860, 176, 1790, 800], a)
        text(c, "数据不出本机", 46, 908, 232, C_INK, True, a)
        text(c, "没有账号体系，没有云端。", 22, 908, 330, C_MUTED, False, a)
        text(c, "一个 data 目录拷走，", 22, 908, 386, C_MUTED, False, a)
        text(c, "就是一次完整备份。", 22, 908, 426, C_MUTED, False, a)
        text(c, "更新只换程序文件，不动 data/。", 22, 908, 500, C_MUTED, False, a)
        pill(c, "127.0.0.1:8766", 20, 908, 610, a, C_MINT,
             (127, 224, 192, 14), (127, 224, 192, 52))


@scene(8.5)
def s10_end(c, t):
    text(c, "KPL 赛训工具", 58, W / 2, 190, C_INK, True,
         ease_out(seg(t, 0.2, 0.7)), "ct")
    steps = [("01", "下载", "GitHub Releases / zip 带运行时"),
             ("02", "解压", "双击「启动工作台.bat」"),
             ("03", "打开", "浏览器自动开本地工作台")]
    bw, gap = 500, 36
    for i, (num, k, v) in enumerate(steps):
        a = ease_out(seg(t, 0.7 + i * 0.3, 0.5))
        if a <= 0:
            continue
        xx = 148 + i * (bw + gap)
        yy = 320 + (1 - a) * 16
        card(c, [xx, yy, xx + bw, yy + 206], a)
        text(c, num, 22, xx + 32, yy + 28, C_MINT, True, a)
        text(c, k, 36, xx + 32, yy + 66, C_INK, True, a)
        text(c, v, 19, xx + 32, yy + 142, C_MUTED, False, a)

    text(c, "Windows 10 / 11 · 内置运行时 · 不需要管理员权限 · 个人与教学免费",
         24, 148, 610, C_MUTED, False, ease_out(seg(t, 2.0, 0.6)))
    text(c, "hccccc01333.github.io/kpl-scrim-lab-site", 28, 148, 678, C_INK, False,
         ease_out(seg(t, 2.6, 0.6)))
    text(c, "本片所有对局、队名、选手均为合成演示数据", 20, 148, 742, C_DIM, False,
         ease_out(seg(t, 3.2, 0.6)))
    text(c, "它不替你下结论，只把事实准备好。", 32, W / 2, 880, C_MINT, True,
         ease_out(seg(t, 3.9, 0.7)), "ct")


# ---------------------------------------------------------------- 渲染

FADE = 0.42
TOTAL = sum(d for d, _ in SCENES)


def scene_bounds():
    out, acc = [], 0.0
    for d, fn in SCENES:
        out.append((acc, acc + d, fn))
        acc += d
    return out


BOUNDS = scene_bounds()


def render_frame(T):
    idx = 0
    for i, (a, b, _) in enumerate(BOUNDS):
        if a <= T < b:
            idx = i
            break
    else:
        idx = len(BOUNDS) - 1
    a, b, fn = BOUNDS[idx]
    lt = T - a
    canvas = make_bg().copy()
    fn(canvas, lt)
    env = min(ease_out(clamp(lt / FADE)), ease_out(clamp((b - T) / FADE)))
    if env < 0.999:
        black = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * (1 - env))))
        canvas.alpha_composite(black)
    return canvas.convert("RGB")


def preview(times):
    os.makedirs(os.path.join(HERE, "preview"), exist_ok=True)
    for t in times:
        img = render_frame(t)
        p = os.path.join(HERE, "preview", f"t{t:05.1f}.png")
        img.save(p)
        print("saved", p)


def render(out_path, start=0.0, end=None, audio=True):
    end = TOTAL if end is None else end
    n0, n1 = int(round(start * FPS)), int(round(end * FPS))
    frames = n1 - n0
    tmp_video = os.path.join(HERE, "out", "_video.mp4")
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp_video]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    last = -1
    for i in range(frames):
        img = render_frame((n0 + i) / FPS)
        proc.stdin.write(img.tobytes())
        pct = int(100 * i / max(1, frames - 1))
        if pct != last and pct % 5 == 0:
            print(f"render {pct}%  ({i}/{frames})", flush=True)
            last = pct
    proc.stdin.close()
    proc.wait()

    if not audio:
        os.replace(tmp_video, out_path)
        return out_path

    src_audio = os.path.join(ROOT, "dist", "scrim-promo-v6", "mix.wav")
    dur = end - start
    fade_out_at = max(0.1, dur - 3.2)
    cmd2 = ["ffmpeg", "-y", "-loglevel", "error",
            "-i", tmp_video,
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src_audio,
            "-filter:a", f"afade=t=in:st=0:d=2.2,afade=t=out:st={fade_out_at:.2f}:d=3.2,"
                         f"volume=2.8dB,alimiter=limit=0.94",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart", out_path]
    subprocess.run(cmd2, check=True)
    os.remove(tmp_video)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=str, default="")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float, default=None)
    ap.add_argument("--out", type=str, default=os.path.join(HERE, "out", "KPL赛训工具-B站宣传片-v3.mp4"))
    args = ap.parse_args()

    print(f"scenes={len(SCENES)} total={TOTAL:.1f}s frames={int(TOTAL * FPS)}")
    if args.preview:
        preview([float(x) for x in args.preview.split(",")])
    if args.render:
        p = render(args.out, args.start, args.end, audio=(args.start == 0.0))
        print("done", p, round(os.path.getsize(p) / 1e6, 1), "MB")
