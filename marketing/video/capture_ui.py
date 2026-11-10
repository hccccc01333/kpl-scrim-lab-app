#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按「视口」抓图：每个功能一屏，1440x900 @2x。

用法：python marketing/video/capture_ui.py
前置：127.0.0.1:8791 上跑着灌好合成演示数据的实例。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "shots"

# (hash, 定位文字, 再向上偏移, 文件名)
JOBS = [
    ("#ingest", "营地连接", 150, "ingest-camp"),
    ("#ingest", "截图 / 录屏 OCR", 120, "ingest-ocr"),
    ("#ingest", "对局审查", 120, "ingest-review"),
    ("#shots", None, 0, "shots"),
    ("#videos", None, 0, "videos"),
    ("#review/b58d561859b94ce5a9048456f62d5f05", None, 0, "review"),
    ("#review/b58d561859b94ce5a9048456f62d5f05", "变更记录", 260, "review-audit"),
    ("#match/mock-903425", None, 0, "match-top"),
    ("#match/mock-903425", "十人面板", 120, "match-players"),
    ("#cross", None, 0, "cross"),
    ("#bp", None, 0, "bp"),
    ("#players", None, 0, "players"),
    ("#depth", None, 0, "depth"),
    ("#sources", None, 0, "sources"),
]

DISMISS = ["下次再说", "知道了"]


def dismiss(page):
    for label in DISMISS:
        try:
            el = page.get_by_text(label, exact=True).first
            if el.is_visible(timeout=500):
                el.click(force=True)
                page.wait_for_timeout(400)
                return
        except Exception:
            continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8791/")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=2, locale="zh-CN",
                                  timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        for hash_, anchor, offset, name in JOBS:
            if only and name not in only:
                continue
            page.goto(args.base + hash_, wait_until="domcontentloaded")
            page.wait_for_timeout(2600)
            dismiss(page)
            if anchor:
                try:
                    box = page.get_by_text(anchor, exact=True).first.bounding_box()
                    if box:
                        sy = page.evaluate("window.scrollY")
                        page.evaluate(f"window.scrollTo(0, {max(0, box['y'] + sy - offset)})")
                        page.wait_for_timeout(700)
                except Exception as exc:
                    print(f"  ! anchor {anchor}: {exc}")
            page.wait_for_timeout(400)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path))
            print(f"{name:16s} {path.stat().st_size // 1024:5d} KB")
        browser.close()


if __name__ == "__main__":
    main()
