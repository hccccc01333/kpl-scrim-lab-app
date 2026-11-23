#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture README / website screenshots from a running V3 workbench.

    python scripts/capture_readme_shots.py --base http://127.0.0.1:8766 \
        --out docs/images

V3 是唯一入口：所有页面都是同一个 HTML 应用上的 hash 路由（``#matches``、
``#players`` …），不再经过 V1 的 ``/studio#...``。截图只包含
``scripts/seed_demo_data.py`` 灌进去的合成演示数据，不含任何真实对局。

文件编号沿用历史命名，方便 README 与官网引用：

    02 采集        03 对局档案    04 选手档案    05 战队分析
    06 英雄榜      07 BP 概览     08 精选对局    09 单局复盘    11 跨局分析

首图 ``readme-hero.png`` 取对局档案（浅色主题，与 v3.0 视觉体系一致）：首页在没有
「本周」对局的新实例上会先弹空库引导，不适合当首图，所以 README 的首屏换成对局档案。

单局复盘用 ``{match}`` 占位：默认挑第一场有经济时间轴且数据完整的对局，
需要固定某一局时加 ``--match mock-903973``。

建议先起一个隔离实例，避免把演示数据写进自己的库（路径要全部指向隔离目录，
否则营地补建通道会读到本机真实面板）：

    set KPL_DATA_DIR=...\\demo
    set TRAINING_PORT=8790
    set TRAINING_DB=%KPL_DATA_DIR%\\training.sqlite3
    set ANALYSIS_MATCHES=%KPL_DATA_DIR%\\matches
    set ANALYSIS_OFFICIAL=%KPL_DATA_DIR%\\official_replays
    python server.py
    python scripts/seed_demo_data.py --base http://127.0.0.1:8790 --with-camp
    python scripts/capture_readme_shots.py --base http://127.0.0.1:8790 --out docs/images
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

# 首次访问会弹使用教程，截图前把它标记为已完成。
TOUR_FLAG = "localStorage.setItem('training-tour-complete-v3','1')"
# 全部截图统一用默认浅色主题：v3.0 起视觉体系就是白灰极简，深色只作为可选项。

DEFAULT_VIEWPORT = {'width': 1440, 'height': 900}
HERO_VIEWPORT = {'width': 1500, 'height': 938}

SHOTS = [
    # name 产物名 / route 路由 / wait 等待毫秒 / height 视口高（默认 900）/ guard 命中这句就跳过
    {'name': '02-capture', 'route': '#ingest', 'wait': 7000},
    {'name': '03-matches', 'route': '#matches', 'wait': 4000},
    {'name': '04-players', 'route': '#players', 'wait': 7000},
    {'name': '05-team', 'route': '#teams', 'wait': 4000},
    {'name': '06-heroes', 'route': '#heroes', 'wait': 7000},
    {'name': '07-topics', 'route': '#bp', 'wait': 3000, 'demo': True},
    # 精选对局一页放不下 900 高：加高视口把下半截拍进来
    {'name': '08-depth', 'route': '#featured', 'wait': 4000, 'height': 1200},
    {'name': '09-match', 'route': '#match/{match}', 'wait': 5000},
    # 跨局分析以「已确认的系列赛」为单位；演示实例没有编组时别把好图覆盖成空态
    {'name': '11-cross', 'route': '#cross', 'wait': 4000, 'guard': '还没有已确认的系列赛'},
]


def pick_match(base: str) -> str:
    """挑第一场有经济时间轴、数据完整的演示对局。"""
    with urllib.request.urlopen(f'{base}/api/matches?limit=200', timeout=30) as response:
        payload = json.load(response)
    rows = payload.get('matches', payload) if isinstance(payload, dict) else payload
    for row in rows:
        if row.get('hasTimeline') and row.get('complete'):
            return str(row['key'])
    if rows:
        return str(rows[0]['key'])
    raise SystemExit('这个实例里没有对局：先跑 scripts/seed_demo_data.py')


def dismiss_dialog(page) -> None:
    """新实例第一次打开会弹「先把第一局拿进来」，挡住页面中心。"""
    try:
        if page.evaluate("document.querySelector('dialog[open]') !== null"):
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
            if page.evaluate("document.querySelector('dialog[open]') !== null"):
                page.click("dialog[open] [data-action='close']", timeout=2000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def shoot(page, base: str, route: str, wait: int, target: Path, guard: str = '',
          demo: bool = False) -> None:
    page.goto(f'{base}/{route}', wait_until='load')
    page.wait_for_timeout(wait)
    dismiss_dialog(page)
    if demo and page.locator('[data-bps-demo]').count():
        # 空库实例的 BP 页只有空态；先载入模拟数据，再切到 KPL 20 手展示完整界面。
        page.click('[data-bps-demo]')
        page.wait_for_timeout(2000)
        if page.locator('[data-bps-mode="kpl"]').count():
            page.click('[data-bps-mode="kpl"]')
            page.wait_for_timeout(1500)
    body = page.inner_text('body')
    if guard and guard in body:
        print(f'跳过 {target.name}：这个实例里还是「{guard}」，先补数据再拍')
        return
    if '数据读取失败' in body:
        print(f'注意：{target.name} 页面出现「数据读取失败」，先修数据再截图')
    page.screenshot(path=str(target))
    print('shot', target.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--out', default='docs/images')
    parser.add_argument('--scale', type=float, default=2, help='设备像素比，默认 2（2880×1800）')
    parser.add_argument('--only', default='', help='只拍这几张，逗号分隔，例如 09-match,11-cross；hero 表示首图')
    parser.add_argument('--match', default='', help='指定单局复盘的对局 key')
    parser.add_argument('--no-hero', action='store_true', help='不重做 README 首图')
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip('/')
    only = {name.strip() for name in args.only.split(',') if name.strip()}
    match_key = args.match or pick_match(base)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 首图：浅色对局档案，单独一个 context，避免主题污染逐页截图。
        hero_target = out / 'readme-hero.png'
        if not args.no_hero and (not only or 'hero' in only):
            context = browser.new_context(viewport=HERO_VIEWPORT, device_scale_factor=args.scale)
            context.add_init_script(TOUR_FLAG)
            page = context.new_page()
            raw = out / '.hero-raw.png'
            page.goto(f'{base}/#matches', wait_until='load')
            page.wait_for_timeout(5000)
            dismiss_dialog(page)
            page.screenshot(path=str(raw))
            context.close()
            from build_readme_diagrams import frame_image
            frame_image(raw, hero_target, HERO_VIEWPORT['width'])
            raw.unlink(missing_ok=True)
            print('hero', hero_target.name)

        context = browser.new_context(viewport=DEFAULT_VIEWPORT, device_scale_factor=args.scale)
        context.add_init_script(TOUR_FLAG)
        page = context.new_page()
        for shot in SHOTS:
            if only and shot['name'] not in only:
                continue
            page.set_viewport_size({'width': DEFAULT_VIEWPORT['width'],
                                    'height': shot.get('height', DEFAULT_VIEWPORT['height'])})
            shoot(page, base, shot['route'].format(match=match_key), shot['wait'],
                  out / f"{shot['name']}.png", shot.get('guard', ''),
                  demo=bool(shot.get('demo')))
        context.close()
        browser.close()


if __name__ == '__main__':
    main()
