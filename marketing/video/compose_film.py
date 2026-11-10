#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把录好的 tour.webm + shots.json 合成「项目介绍片」：
左边是模块与功能清单，右边画面按功能逐个弹出、停住、缩回。

    python marketing/video/compose_film.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
RAW = HERE / ".raw"
OUT = HERE / "out"

W, H = 1920, 1080
SRC_W, SRC_H = 1440, 900
FPS = 30

PANEL = (510, 108, 1860, 952)          # 1350 x 844，正好 16:10
INTRO, OUTRO = 4.0, 6.5

C_BG = (9, 20, 17)
C_INK = (244, 248, 246)
C_MUTED = (150, 174, 166)
C_DIM = (96, 120, 112)
C_MINT = (127, 224, 192)

FONT_B = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
FONT_R = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"

MODULES = [
    ("首页", ["总览", "最近对局"]),
    ("采集", ["营地连接", "截图 OCR", "录屏 OCR", "对局审查"]),
    ("对局", ["对局档案", "单局详情", "跨局分析", "智能找局", "训练纪录", "版本对比"]),
    ("选手", ["选手档案", "名单与状态", "选手与位置", "选手对比"]),
    ("英雄", ["英雄榜", "英雄对比", "英雄组合"]),
    ("BP", ["BP 概览"]),
    ("战队", ["战队档案", "战队风格"]),
    ("赛训", ["训练计划"]),
    ("数据来源", ["覆盖与缺失"]),
]
CHAPTER = {name: i + 1 for i, (name, _) in enumerate(MODULES)}
FEATURES = dict(MODULES)
TAGLINE = {
    "首页": "一屏看完训练总量",
    "采集": "四种来源进同一条链路",
    "对局": "单局、跨局、找局与版本",
    "选手": "谁在打，状态往哪走",
    "英雄": "105 个英雄，谁该进池子",
    "BP": "禁用习惯与优先级",
    "战队": "对手是谁，比什么都重要",
    "赛训": "训练计划、目标与报告",
    "数据来源": "每个字段都能回到出处",
}


def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def ease(p):
    return 1 - (1 - p) ** 3


@lru_cache(maxsize=1024)
def tline(s, size, bold=True, color=C_INK, tracking=0):
    font = ImageFont.truetype(FONT_B if bold else FONT_R, size)
    pad = int(size * 0.45)
    if tracking:
        widths = [font.getlength(ch) for ch in s]
        w = sum(widths) + tracking * (len(s) - 1) + pad * 2
    else:
        w = font.getlength(s) + pad * 2
    img = Image.new("RGBA", (int(w), int(size * 1.55) + pad), (0, 0, 0, 0))
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


def put(canvas, tile, x, y, alpha=1.0):
    if alpha <= 0.004 or tile is None:
        return
    if alpha < 0.996:
        tile = tile.copy()
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(tile, (int(x), int(y)))


@lru_cache(maxsize=4)
def background(light=False):
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W + 1, 120):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 5))
    for y in range(0, H + 1, 120):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 5))
    small = Image.new("L", (48, 27), 0)
    px = small.load()
    for j in range(27):
        for i in range(48):
            dx = (i - 23.5) / 23.5
            dy = (j - 13.5) / 13.5
            px[i, j] = int(150 * min(1.0, (dx * dx + dy * dy) ** 0.5 / 1.2) ** 2)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), small.resize((W, H), Image.BICUBIC))
    return img.convert("RGBA")


PW = PANEL[2] - PANEL[0]
PH = PANEL[3] - PANEL[1]


@lru_cache(maxsize=1)
def shadow_tile():
    pad = 60
    img = Image.new("L", (PW + pad * 2, PH + pad * 2), 0)
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + PW, pad + PH],
                                          radius=18, fill=210)
    img = img.filter(ImageFilter.GaussianBlur(26))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.putalpha(img)
    return out


@lru_cache(maxsize=1)
def panel_mask():
    m = Image.new("L", (PW, PH), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, PW - 1, PH - 1], radius=14, fill=255)
    return m


def draw_left(canvas, module, feature, t_local):
    idx = CHAPTER[module]
    x = 96
    a = ease(clamp(t_local / 0.5))
    put(canvas, tline(f"{idx:02d}", 20, True, C_MINT, 3), x, 128, a)
    put(canvas, tline(module, 62, True, C_INK), x - 4, 166, a)
    put(canvas, tline(TAGLINE[module], 20, False, C_MUTED), x, 264, a * 0.95)

    feats = FEATURES[module]
    top = 348
    step = 58
    for i, name in enumerate(feats):
        active = name == feature
        aa = ease(clamp((t_local - 0.1 - i * 0.05) / 0.4))
        y = top + i * step
        if active:
            put(canvas, tline("▍", 22, True, C_MINT), x - 2, y + 2, aa)
        color = C_MINT if active else C_DIM
        put(canvas, tline(name, 24 if not active else 26, active, color), x + 24, y, aa)


def draw_panel(canvas, frame, alpha, scale, dy):
    if alpha <= 0.004:
        return
    w, h = int(PW * scale), int(PH * scale)
    img = frame.resize((w, h), Image.LANCZOS)
    mask = panel_mask().resize((w, h), Image.LANCZOS)
    tile = img.convert("RGBA")
    tile.putalpha(mask)
    x = int(PANEL[0] + (PW - w) // 2)
    y = int(PANEL[1] + (PH - h) // 2 + dy)

    sh = shadow_tile()
    sw = int(sh.width * scale)
    shh = int(sh.height * scale)
    sh = sh.resize((sw, shh), Image.BILINEAR)
    canvas.alpha_composite(sh, (x - int(60 * scale), y - int(60 * scale) + int(12 * scale)))
    if alpha < 0.996:
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(tile, (x, y))


def intro_card(lt):
    c = background().copy()
    d = ImageDraw.Draw(c)
    a = ease(clamp(lt / 0.8))
    put(c, tline("KPL 赛训工具", 76, True, C_INK), 96, 430, a)
    put(c, tline("项目介绍 · 逐功能演示", 30, False, C_MINT), 96, 540,
        ease(clamp((lt - 0.4) / 0.7)))
    d.rectangle([96, 512, 96 + int(120 * a), 513], fill=C_MINT)
    put(c, tline("本片所有对局、队名、选手均为合成演示数据", 20, False, C_DIM),
        96, 940, ease(clamp((lt - 0.9) / 0.7)))
    return c


def outro_card(lt):
    c = background().copy()
    a = ease(clamp(lt / 0.7))
    put(c, tline("KPL 赛训工具", 60, True, C_INK), 96, 300, a)
    put(c, tline("本机运行 · 数据不出机器 · 一个 data 目录就是完整备份", 26, False, C_MUTED),
        96, 396, ease(clamp((lt - 0.3) / 0.7)))
    steps = [("01", "下载", "GitHub Releases / zip 带运行时"),
             ("02", "解压", "双击「启动工作台.bat」"),
             ("03", "打开", "浏览器自动开本地工作台")]
    for i, (num, k, v) in enumerate(steps):
        aa = ease(clamp((lt - 0.8 - i * 0.25) / 0.5))
        y = 520 + i * 96
        put(c, tline(num, 20, True, C_MINT, 2), 96, y + 4, aa)
        put(c, tline(k, 32, True, C_INK), 160, y, aa)
        put(c, tline(v, 20, False, C_MUTED), 300, y + 10, aa)
    put(c, tline("hccccc01333.github.io/kpl-scrim-lab-site", 28, False, C_INK),
        96, 880, ease(clamp((lt - 2.0) / 0.6)))
    put(c, tline("Windows 10 / 11 · 免费用于个人与教学", 20, False, C_DIM),
        96, 936, ease(clamp((lt - 2.4) / 0.6)))
    return c


class FrameSource:
    """按时间取样：源是 25fps，成片是 30fps，按源帧号推进。"""

    def __init__(self, path: Path):
        fps, _ = probe(path)
        self.fps = fps or 25.0
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, bufsize=SRC_W * SRC_H * 3 * 4)
        self.n = SRC_W * SRC_H * 3
        self.idx = -1
        self.frame = None
        self.ended = False

    def at(self, t: float):
        want = int(t * self.fps)
        while self.idx < want and not self.ended:
            buf = self.proc.stdout.read(self.n)
            if len(buf) < self.n:
                self.ended = True
                break
            self.idx += 1
            self.frame = Image.frombytes("RGB", (SRC_W, SRC_H), buf)
        return self.frame

    def close(self):
        try:
            self.proc.stdout.close()
            self.proc.kill()
        except Exception:
            pass


def probe(path: Path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True).stdout
    try:
        data = json.loads(out)
    except ValueError:
        return 25.0, 0.0
    fps = 25.0
    streams = data.get("streams") or [{}]
    rate = streams[0].get("avg_frame_rate") or "25/1"
    if "/" in rate:
        a, b = rate.split("/")
        try:
            fps = float(a) / float(b or 1)
        except (ValueError, ZeroDivisionError):
            fps = 25.0
    try:
        dur = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return fps, dur


class Sources:
    """顺序取帧：同一时刻只开一个分段的解码器。"""

    def __init__(self):
        self.seg = None
        self.src = None

    def at(self, seg, t):
        if seg != self.seg:
            if self.src:
                self.src.close()
            path = RAW / f"tour-{seg}.webm"
            if not path.exists():
                return None
            self.src = FrameSource(path)
            self.seg = seg
        return self.src.at(t) if self.src else None

    def close(self):
        if self.src:
            self.src.close()


LEAD = 0.9      # 跳过每段开头的加载/空壳
TAIL = 0.25


def build_timeline(shots):
    tl = []
    acc = 0.0
    for s in shots:
        a = float(s["start"]) + LEAD
        b = float(s["end"]) - TAIL
        d = max(2.0, b - a)
        s = dict(s, src_start=a)
        tl.append((acc, acc + d, s))
        acc += d
    return tl, acc


def shot_at(tl, lt):
    for a, b, s in tl:
        if a <= lt < b:
            return s, a
    return None, 0.0


def preview(times):
    data = json.loads((RAW / "shots.json").read_text(encoding="utf-8"))
    tl, body_dur = build_timeline(data["shots"])
    outdir = HERE / "preview"
    outdir.mkdir(exist_ok=True)
    srcs = Sources()
    for target in sorted(float(t) for t in times):
        if target < INTRO:
            canvas = intro_card(target)
        else:
            lt = target - INTRO
            s, a = shot_at(tl, lt)
            frame = srcs.at(s["seg"], s["src_start"] + (lt - a)) if s else None
            canvas = background().copy()
            if s and frame is not None:
                local = lt - a
                dur = s["end"] - s["start"]
                din, dout = 0.5, 0.36
                if local < din:
                    p = ease(local / din)
                    alpha, scale, dy = p, 0.94 + 0.06 * p, 20 * (1 - p)
                elif local > dur - dout:
                    p = ease(clamp((local - (dur - dout)) / dout))
                    alpha, scale, dy = 1 - p, 1 - 0.045 * p, 0
                else:
                    alpha, scale, dy = 1.0, 1.0, 0
                draw_left(canvas, s["module"], s["feature"], local)
                draw_panel(canvas, frame, alpha, scale, dy)
        path = outdir / f"p{target:05.1f}.png"
        canvas.convert("RGB").save(path)
        print("saved", path)
    srcs.close()


def main():
    data = json.loads((RAW / "shots.json").read_text(encoding="utf-8"))
    tl, body_dur = build_timeline(data["shots"])
    total = INTRO + body_dur + OUTRO
    out_path = OUT / "KPL赛训工具-项目介绍.mp4"
    OUT.mkdir(parents=True, exist_ok=True)

    n_frames = int(total * FPS)
    enc = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{W}x{H}",
        "-framerate", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / "_v.mp4")],
        stdin=subprocess.PIPE)

    srcs = Sources()
    idx = 0
    for f in range(n_frames):
        t = f / FPS
        if t < INTRO:
            canvas = intro_card(t)
        elif t < INTRO + body_dur:
            lt = t - INTRO
            s, a = shot_at(tl, lt)
            if s is None:
                canvas = background()
            else:
                frame = srcs.at(s["seg"], s["src_start"] + (lt - a))
                canvas = background().copy()
                if frame is not None:
                    local = lt - a
                    dur = s["end"] - s["start"]
                    din, dout = 0.5, 0.36
                    if local < din:
                        p = ease(local / din)
                        alpha, scale, dy = p, 0.94 + 0.06 * p, 20 * (1 - p)
                    elif local > dur - dout:
                        p = ease(clamp((local - (dur - dout)) / dout))
                        alpha, scale, dy = 1 - p, 1 - 0.045 * p, 0
                    else:
                        alpha, scale, dy = 1.0, 1.0, 0
                    draw_left(canvas, s["module"], s["feature"], local)
                    draw_panel(canvas, frame, alpha, scale, dy)
        else:
            canvas = outro_card(t - INTRO - body_dur)
        enc.stdin.write(canvas.convert("RGB").tobytes())
        idx += 1
        if idx % 300 == 0:
            print(f"frame {idx}/{n_frames}", flush=True)
    enc.stdin.close()
    enc.wait()
    srcs.close()

    dur = idx / FPS
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / "_v.mp4"),
        "-i", str(HERE.parents[0] / ".." / "dist" / "scrim-promo-v6" / "mix.wav"),
        "-filter_complex",
        f"[1:a]volume=-6dB,afade=t=in:st=0:d=2.5,afade=t=out:st={max(1, dur - 4):.1f}:d=4[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    (OUT / "_v.mp4").unlink(missing_ok=True)
    print("done", out_path, round(dur, 1), "s", round(out_path.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        preview(sys.argv[2].split(","))
    else:
        sys.exit(main())
