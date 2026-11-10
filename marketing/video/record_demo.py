#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Playwright 驱动真实界面录屏，剪成「功能演示」短片。

    python marketing/video/record_demo.py            # 录 + 合成
    python marketing/video/record_demo.py --keep     # 保留中间文件

产出：marketing/video/out/KPL赛训工具-功能演示.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
RAW = HERE / ".raw"
OUT = HERE / "out"
FONT_B = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Bold.ttf"
FONT_R = r"C:\Windows\Fonts\HarmonyOS_Sans_SC_Regular.ttf"

CURSOR = """
(() => {
  const boot = () => {
    if (document.getElementById('demo-cursor') || !document.documentElement) return;
    const style = document.createElement('style');
    style.textContent = `
      #demo-cursor{position:fixed;left:0;top:0;width:22px;height:22px;border-radius:50%;
        background:rgba(12,26,22,.45);border:2.5px solid rgba(255,255,255,.95);
        box-shadow:0 3px 12px rgba(0,0,0,.35);pointer-events:none;z-index:2147483647;
        transform:translate(-40px,-40px);transition:transform .04s linear}
      #demo-cursor.click{animation:dc .3s ease-out}
      @keyframes dc{0%{box-shadow:0 0 0 0 rgba(23,182,154,.8)}
        100%{box-shadow:0 0 0 24px rgba(23,182,154,0)}}
    `;
    document.documentElement.appendChild(style);
    const dot = document.createElement('div');
    dot.id = 'demo-cursor';
    document.documentElement.appendChild(dot);
  };
  boot();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  setInterval(boot, 400);
  document.addEventListener('mousemove', (e) => {
    const d = document.getElementById('demo-cursor');
    if (d) d.style.transform = `translate(${e.clientX - 11}px, ${e.clientY - 11}px)`;
  }, true);
  document.addEventListener('mousedown', () => {
    const d = document.getElementById('demo-cursor');
    if (d) { d.classList.remove('click'); void d.offsetWidth; d.classList.add('click'); }
  }, true);
})();
"""


def glide(page, x, y, steps=20, pause=0.01):
    page.mouse.move(x, y, steps=steps)
    time.sleep(pause)


def dismiss(page):
    for label in ("下次再说", "知道了"):
        try:
            el = page.get_by_text(label, exact=True).first
            if el.is_visible(timeout=300):
                el.click(force=True)
                time.sleep(0.3)
                return
        except Exception:
            continue


def nav(page, label, x):
    """点顶部导航，失败就退回 hash 跳转。"""
    try:
        el = page.get_by_text(label, exact=True).first
        box = el.bounding_box()
        if box:
            glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=16)
            time.sleep(0.25)
            el.click(timeout=2500)
            time.sleep(2.6)
            return
    except Exception:
        pass
    page.goto(page.url.split("#")[0] + "#" + x, wait_until="domcontentloaded")
    time.sleep(2.6)


def tab(page, label, pause=2.4):
    try:
        el = page.get_by_text(label, exact=True).first
        box = el.bounding_box()
        if box:
            glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=14)
            time.sleep(0.2)
            el.click(timeout=2500)
            time.sleep(pause)
            return
    except Exception:
        pass
    time.sleep(pause)


def scenario(page, base):
    page.goto(base + "#overview", wait_until="domcontentloaded")
    time.sleep(3.0)
    dismiss(page)
    glide(page, 1180, 520, steps=24)
    time.sleep(1.0)

    nav(page, "采集", "ingest")
    glide(page, 900, 600, steps=18)
    for _ in range(3):
        page.mouse.wheel(0, 340)
        time.sleep(0.45)
    time.sleep(0.8)

    nav(page, "对局", "matches")
    glide(page, 860, 620, steps=18)
    link = page.locator("a[href*='match/mock-']").first
    link.scroll_into_view_if_needed()
    time.sleep(0.7)
    box = link.bounding_box()
    glide(page, box["x"] + 320, box["y"] + 16, steps=20)
    time.sleep(0.4)
    page.mouse.click(box["x"] + 320, box["y"] + 16)
    time.sleep(3.6)
    glide(page, 980, 800, steps=14)
    for _ in range(6):
        page.mouse.wheel(0, 300)
        time.sleep(0.4)
    time.sleep(0.8)

    tab(page, "跨局分析", 2.8)
    glide(page, 900, 700, steps=14)
    time.sleep(0.6)
    for _ in range(2):
        page.mouse.wheel(0, 280)
        time.sleep(0.4)

    nav(page, "选手", "players")
    tab(page, "名单与状态", 2.6)
    tab(page, "选手对比", 2.8)
    time.sleep(0.6)

    nav(page, "英雄", "heroes")
    glide(page, 900, 600, steps=14)
    for _ in range(2):
        page.mouse.wheel(0, 260)
        time.sleep(0.4)
    time.sleep(0.5)

    nav(page, "BP", "bp")
    time.sleep(0.8)
    nav(page, "战队", "teams")
    time.sleep(0.8)
    nav(page, "赛训", "plan")
    time.sleep(0.6)
    nav(page, "数据来源", "sources")
    time.sleep(1.6)


def record(base: str):
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(RAW),
            record_video_size={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = ctx.new_page()
        page.add_init_script(CURSOR)
        time.sleep(0.6)
        scenario(page, base)
        video = page.video.path()
        ctx.close()
        browser.close()
    return video


def card(title, sub, foot, path):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), (7, 16, 14))
    d = ImageDraw.Draw(img)
    for x in range(0, W + 1, 120):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 6))
    for y in range(0, H + 1, 120):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 6))
    ft = ImageFont.truetype(FONT_B, 64)
    fs = ImageFont.truetype(FONT_R, 28)
    ff = ImageFont.truetype(FONT_R, 20)
    w = d.textlength(title, font=ft)
    d.text(((W - w) / 2, 470), title, font=ft, fill=(244, 248, 246))
    w2 = d.textlength(sub, font=fs)
    d.text(((W - w2) / 2, 574), sub, font=fs, fill=(127, 224, 192))
    w3 = d.textlength(foot, font=ff)
    d.text(((W - w3) / 2, 940), foot, font=ff, fill=(104, 128, 121))
    img.save(path)


def build(body: str, keep=False):
    RAW.mkdir(parents=True, exist_ok=True)
    intro, outro = RAW / "intro.png", RAW / "outro.png"
    card("KPL 赛训工具", "功能演示 · 真实界面操作",
         "本片数据为合成演示数据，不含任何真实对局", intro)
    card("hccccc01333.github.io/kpl-scrim-lab-site", "Windows 10 / 11 · 内置运行时 · 免费",
         "数据不出本机，一个 data 目录就是完整备份", outro)

    body_mp4 = OUT / "_body.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", body,
                    "-vf", "fps=30,scale=1920:1080:flags=lanczos",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(body_mp4)], check=True)

    seg = OUT / "_seg.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", "3.2", "-i", str(intro),
        "-loop", "1", "-t", "4.6", "-i", str(outro),
        "-i", str(body_mp4),
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p,fade=t=in:st=0:d=0.8,fade=t=out:st=2.7:d=0.5[v0];"
        "[1:v]fps=30,format=yuv420p,fade=t=in:st=0:d=0.7,fade=t=out:st=4.0:d=0.6[v2];"
        "[2:v]fps=30,format=yuv420p[v1];"
        "[v0][v1][v2]concat=n=3:v=1:a=0[out]",
        "-map", "[out]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", str(seg)], check=True)

    final = OUT / "KPL赛训工具-功能演示.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(seg),
        "-i", str(ROOT_AUDIO), "-filter_complex",
        "[1:a]volume=-19dB,afade=t=in:st=0:d=2.5,afade=t=out:st=%d:d=3[a]"
        % max(3, int(duration_of(seg)) - 3),
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", str(final)], check=True)
    for tmp in (body_mp4, seg):
        tmp.unlink(missing_ok=True)
    return final


ROOT_AUDIO = HERE.parents[0] / ".." / "dist" / "scrim-promo-v6" / "mix.wav"


def duration_of(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8791/")
    args = ap.parse_args()

    t0 = time.time()
    webm = record(args.base)
    print("recorded", round(time.time() - t0, 1), "s", os.path.getsize(webm) // 1024, "KB")
    final = build(webm, args.keep)
    print("done", final, round(os.path.getsize(final) / 1e6, 1), "MB",
          "duration", round(duration_of(final), 1), "s")
