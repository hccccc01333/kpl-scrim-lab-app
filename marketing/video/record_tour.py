#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录一段「逐功能、慢速、完整」的演示（1440x900），并记录每个镜头的时间点。

    python marketing/video/record_tour.py

要点：
  · 每个页面先等内容真的渲染完（没有「正在…」占位）
  · 滚动是小步慢速的，让整块内容都过一遍
  · 每个功能停留 ~7 秒
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
RAW = HERE / ".raw"

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

BUSY = ("正在", "加载中", "读取中", "汇总各局", "稍候")


class Recorder:
    def __init__(self):
        self.t0 = None
        self.shots = []
        self.open = None

    def begin(self):
        self.t0 = time.time()

    def now(self):
        return time.time() - self.t0

    def shot(self, module, feature):
        t = self.now()
        if self.open:
            self.open["end"] = round(t - 0.1, 3)
            self.shots.append(self.open)
        self.open = {"module": module, "feature": feature, "start": round(t + 0.03, 3)}

    def close(self):
        if self.open:
            self.open["end"] = round(self.now(), 3)
            self.shots.append(self.open)
            self.open = None


def glide(page, x, y, steps=26, pause=0.008):
    page.mouse.move(x, y, steps=steps)
    time.sleep(pause)


def wait_ready(page, max_s=14.0):
    """等页面把「正在…」的占位换成真实内容。"""
    t0 = time.time()
    calm = 0
    while time.time() - t0 < max_s:
        try:
            txt = page.inner_text("body")[:6000]
        except Exception:
            txt = ""
        if any(k in txt for k in BUSY):
            calm = 0
        else:
            calm += 1
            if calm >= 3:
                return True
        time.sleep(0.35)
    return False


def slow_scroll(page, dist, step=80, delay=0.085, pause=0.9):
    moved = 0
    while moved < dist:
        page.mouse.wheel(0, step)
        moved += step
        time.sleep(delay)
    time.sleep(pause)


def dismiss(page):
    for label in ("下次再说", "知道了"):
        try:
            el = page.get_by_text(label, exact=True).first
            if el.is_visible(timeout=300):
                el.click(force=True)
                time.sleep(0.35)
                return
        except Exception:
            continue


def nav(page, label, hash_, x=900, y=560):
    try:
        el = page.get_by_text(label, exact=True).first
        box = el.bounding_box()
        if box:
            glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
            time.sleep(0.25)
            el.click(timeout=2500)
            time.sleep(1.6)
            wait_ready(page)
            glide(page, x, y, steps=20)
            return
    except Exception:
        pass
    page.goto(page.url.split("#")[0] + "#" + hash_, wait_until="domcontentloaded")
    time.sleep(1.6)
    wait_ready(page)


def tab(page, label, y=320):
    try:
        el = page.get_by_text(label, exact=True).first
        box = el.bounding_box()
        if box:
            glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=16)
            time.sleep(0.2)
            el.click(timeout=2500)
            time.sleep(1.4)
            wait_ready(page)
            glide(page, 880, y, steps=18)
            return
    except Exception:
        pass
    time.sleep(1.4)
    wait_ready(page)


CURRENT_SEG = [0]
_shot_orig = Recorder.shot


def _shot(self, module, feature):
    _shot_orig(self, module, feature)
    if self.open:
        self.open["seg"] = CURRENT_SEG[0]


Recorder.shot = _shot


def seg_overview_ingest(page, base, rec):
    page.goto(base + "#overview", wait_until="domcontentloaded")
    wait_ready(page)
    dismiss(page)

    rec.shot("首页", "总览")
    glide(page, 1150, 380, steps=30)
    time.sleep(2.4)
    slow_scroll(page, 440, step=70, delay=0.09, pause=1.2)
    time.sleep(2.2)

    rec.shot("首页", "最近对局")
    glide(page, 820, 700, steps=20)
    slow_scroll(page, 320, step=64, delay=0.09, pause=1.4)
    time.sleep(2.6)

    rec.shot("采集", "营地连接")
    nav(page, "采集", "ingest", 880, 480)
    time.sleep(2.2)
    slow_scroll(page, 300, step=60, delay=0.09, pause=1.2)
    time.sleep(2.0)

    rec.shot("采集", "截图 OCR")
    page.goto(base + "#shots", wait_until="domcontentloaded")
    wait_ready(page)
    time.sleep(1.0)
    glide(page, 900, 600, steps=22)
    slow_scroll(page, 620, step=66, delay=0.09, pause=1.4)
    time.sleep(2.0)

    rec.shot("采集", "录屏 OCR")
    page.goto(base + "#videos", wait_until="domcontentloaded")
    wait_ready(page)
    time.sleep(1.0)
    glide(page, 900, 540, steps=20)
    slow_scroll(page, 620, step=66, delay=0.09, pause=1.4)
    time.sleep(2.0)

    rec.shot("采集", "对局审查")
    nav(page, "采集", "ingest", 880, 480)
    time.sleep(1.0)
    slow_scroll(page, 760, step=70, delay=0.09, pause=1.6)
    time.sleep(2.4)


def seg_matches(page, base, rec):
    page.goto(base + "#matches", wait_until="domcontentloaded")
    wait_ready(page)
    dismiss(page)
    time.sleep(0.8)

    rec.shot("对局", "对局档案")
    glide(page, 860, 600, steps=22)
    slow_scroll(page, 360, step=66, delay=0.09, pause=1.2)
    time.sleep(2.2)

    rec.shot("对局", "单局详情")
    box = None
    try:
        link = page.locator("a[href*='match/mock-']").first
        link.scroll_into_view_if_needed(timeout=4000)
        time.sleep(0.5)
        box = link.bounding_box()
    except Exception:
        box = None
    if box:
        glide(page, box["x"] + 320, box["y"] + 14, steps=24)
        time.sleep(0.4)
        page.mouse.click(box["x"] + 320, box["y"] + 14)
    else:
        key = page.evaluate(
            """async () => {
                 const r = await fetch('/api/matches?limit=200');
                 const j = await r.json();
                 const items = j.items || j.matches || [];
                 const m = items.find(x => String(x.key || '').startsWith('mock-'));
                 return m ? m.key : null;
               }""")
        page.goto(base + (f"#match/{key}" if key else "#matches"), wait_until="domcontentloaded")
    time.sleep(1.4)
    wait_ready(page)
    time.sleep(0.8)
    glide(page, 960, 760, steps=20)
    slow_scroll(page, 900, step=74, delay=0.09, pause=1.4)
    time.sleep(2.4)

    for name in ("跨局分析", "智能找局", "训练纪录", "版本对比"):
        rec.shot("对局", name)
        tab(page, name)
        time.sleep(1.0)
        slow_scroll(page, 560, step=70, delay=0.09, pause=1.4)
        time.sleep(2.0)


def seg_players_heroes(page, base, rec):
    page.goto(base + "#players", wait_until="domcontentloaded")
    wait_ready(page)
    dismiss(page)
    time.sleep(0.8)

    rec.shot("选手", "选手档案")
    glide(page, 860, 520, steps=20)
    slow_scroll(page, 420, step=68, delay=0.09, pause=1.3)
    time.sleep(2.0)

    for name in ("名单与状态", "选手与位置"):
        rec.shot("选手", name)
        tab(page, name)
        time.sleep(1.0)
        slow_scroll(page, 480, step=70, delay=0.09, pause=1.3)
        time.sleep(2.0)

    rec.shot("英雄", "英雄榜")
    nav(page, "英雄", "heroes", 860, 540)
    time.sleep(1.0)
    slow_scroll(page, 620, step=70, delay=0.09, pause=1.4)
    time.sleep(2.0)

    for name in ("英雄对比", "英雄组合"):
        rec.shot("英雄", name)
        tab(page, name)
        time.sleep(1.0)
        slow_scroll(page, 420, step=70, delay=0.09, pause=1.3)
        time.sleep(2.0)


def seg_rest(page, base, rec):
    page.goto(base + "#bp", wait_until="domcontentloaded")
    wait_ready(page)
    dismiss(page)
    time.sleep(0.8)

    rec.shot("BP", "BP 概览")
    glide(page, 860, 560, steps=20)
    slow_scroll(page, 560, step=70, delay=0.09, pause=1.4)
    time.sleep(2.2)

    rec.shot("战队", "战队档案")
    nav(page, "战队", "teams", 860, 560)
    time.sleep(1.0)
    slow_scroll(page, 420, step=70, delay=0.09, pause=1.3)
    time.sleep(2.0)

    rec.shot("战队", "战队风格")
    tab(page, "战队风格")
    time.sleep(1.0)
    slow_scroll(page, 360, step=70, delay=0.09, pause=1.3)
    time.sleep(2.0)

    rec.shot("赛训", "训练计划")
    nav(page, "赛训", "plan", 860, 560)
    time.sleep(1.0)
    slow_scroll(page, 520, step=70, delay=0.09, pause=1.4)
    time.sleep(2.0)

    rec.shot("数据来源", "覆盖与缺失")
    nav(page, "数据来源", "sources", 860, 560)
    time.sleep(1.2)
    slow_scroll(page, 360, step=70, delay=0.09, pause=1.4)
    time.sleep(2.4)


SEGMENTS = [
    seg_overview_ingest,
    seg_matches,
    seg_players_heroes,
    seg_rest,
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8791/")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    rec = Recorder()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for idx, fn in enumerate(SEGMENTS, start=1):
            CURRENT_SEG[0] = idx
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(RAW),
                record_video_size={"width": 1440, "height": 900},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            rec.begin()
            page = ctx.new_page()
            page.add_init_script(CURSOR)
            t0 = time.time()
            fn(page, args.base, rec)
            rec.close()
            print(f"seg{idx} {round(time.time() - t0, 1)}s", flush=True)
            time.sleep(1.5)
            video = page.video.path()
            ctx.close()
            target = RAW / f"tour-{idx}.webm"
            target.unlink(missing_ok=True)
            Path(video).rename(target)
        browser.close()

    (RAW / "shots.json").write_text(
        json.dumps({"shots": rec.shots}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("shots:", len(rec.shots))


if __name__ == "__main__":
    main()
