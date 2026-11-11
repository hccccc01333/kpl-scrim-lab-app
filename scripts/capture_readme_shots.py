#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture README / website screenshots from a running V3 workbench.

    python scripts/capture_readme_shots.py --base http://127.0.0.1:8766 \
        --out docs/images

V3 是唯一入口：所有页面都是同一个 HTML 应用上的 hash 路由（``#matches``、
``#players`` …），不再经过 V1 的 ``/studio#...``。截图只包含
``scripts/seed_demo_data.py`` 灌进去的合成演示数据，不含任何真实对局。

文件编号沿用历史命名（01–08），方便 README 与官网引用：

    01 首页        02 导入表格    03 对局档案    04 名单与状态
    05 战队档案    06 英雄榜      07 BP 概览     08 训练纪录

建议先起一个隔离实例，避免把演示数据写进自己的库：

    set TRAINING_PORT=8790
    set TRAINING_DB=...\\demo\\training.sqlite3
    python server.py
    python scripts/seed_demo_data.py --base http://127.0.0.1:8790
    python scripts/capture_readme_shots.py --base http://127.0.0.1:8790 --out docs/images
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

# 首次访问会弹使用教程，截图前把它标记为已完成。
TOUR_FLAG = "localStorage.setItem('training-tour-complete-v3','1')"

SHOTS = [
    ('01-overview', '#overview', 4500),
    ('02-capture', '#capture', 4000),
    ('03-matches', '#matches', 4000),
    ('04-players', '#players', 4500),
    ('05-team', '#teams', 4500),
    ('06-heroes', '#heroes', 4500),
    ('07-topics', '#bp', 4000),
    ('08-depth', '#records', 4500),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--out', default='docs/images')
    parser.add_argument('--scale', type=float, default=2, help='设备像素比，默认 2（2880×1800）')
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip('/')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900},
                                      device_scale_factor=args.scale)
        context.add_init_script(TOUR_FLAG)
        page = context.new_page()
        for name, route, wait in SHOTS:
            page.goto(f'{base}/{route}', wait_until='load')
            page.wait_for_timeout(wait)
            if '数据读取失败' in page.inner_text('body'):
                print(f'注意：{name} 页面出现「数据读取失败」，先修数据再截图')
            target = out / f'{name}.png'
            page.screenshot(path=str(target))
            print('shot', target.name)
        browser.close()


if __name__ == '__main__':
    main()
