#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按模块把每个二级页面都截一张（1440x900 @2x），供功能巡览式宣传片使用。

    python marketing/video/capture_modules.py [--only matches,bp]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "shots" / "m"

JOBS = [
    ("#matches", "对局档案", "matches-archive"),
    ("#matches", "跨局分析", "matches-cross"),
    ("#matches", "智能找局", "matches-find"),
    ("#matches", "精选对局", "matches-picks"),
    ("#matches", "训练纪录", "matches-records"),
    ("#matches", "版本对比", "matches-version"),
    ("#bp", "BP 概览", "bp-overview"),
    ("#bp", "战队 BP", "bp-team"),
    ("#bp", "教练档案", "bp-coach"),
    ("#heroes", "英雄榜", "heroes-rank"),
    ("#heroes", "英雄对比", "heroes-compare"),
    ("#heroes", "英雄组合", "heroes-combo"),
    ("#players", "选手档案", "players-archive"),
    ("#players", "名单与状态", "players-status"),
    ("#players", "选手与位置", "players-lanes"),
    ("#players", "选手对比", "players-compare"),
    ("#teams", "战队档案", "teams-profile"),
    ("#teams", "战队风格", "teams-style"),
    ("#teams", "战队阵容", "teams-lineup"),
    ("#teams", "战队训练", "teams-training"),
    ("#plan", "训练计划", "plan-schedule"),
    ("#plan", "数据准备", "plan-prep"),
    ("#plan", "复盘与报告", "plan-report"),
    ("#sources", None, "sources"),
]


def dismiss(page):
    for label in ("下次再说", "知道了"):
        try:
            el = page.get_by_text(label, exact=True).first
            if el.is_visible(timeout=400):
                el.click(force=True)
                page.wait_for_timeout(350)
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
        for hash_, tab, name in JOBS:
            if only and not any(k in name for k in only):
                continue
            page.goto(args.base + hash_, wait_until="domcontentloaded")
            page.wait_for_timeout(2400)
            dismiss(page)
            if tab:
                try:
                    page.get_by_text(tab, exact=True).first.click(timeout=4000)
                    page.wait_for_timeout(2000)
                except Exception as exc:
                    print(f"  ! {name}: tab {tab} -> {type(exc).__name__}")
                    continue
            dismiss(page)
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(f"{name:18s} ok")
        browser.close()


if __name__ == "__main__":
    main()
