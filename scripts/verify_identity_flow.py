"""身份对照的端到端巡检：命名 → 改名 → 解绑 → 删除，一处命名处处生效。

对着一个**隔离实例**跑（别指向教练的真实库）：

    set KPL_DATA_DIR=D:\\tmp\\kpl-demo\\data
    set TRAINING_PORT=8772
    python server.py

    python scripts/verify_identity_flow.py --base http://127.0.0.1:8772

会依次检查：身份对照表渲染与筛选、命名本队账号、改名、解绑、重新命名后删除、
对手账号命名后「对手归属」显示真名、选手认领/名单页无 500 与控制台报错。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def open_setup(page, base, filter_key=None):
    page.goto(f'{base}/#setup')
    page.reload(wait_until='networkidle')
    page.locator('[data-sx-id-row]:visible').first.wait_for()
    if filter_key:
        page.click(f'[data-sx-id-chip="{filter_key}"]')
        page.wait_for_timeout(250)
    page.locator('[data-sx-anchor="identity"]').scroll_into_view_if_needed()


def run(base, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3','1')")
        page.on('console', lambda m: errors.append(f'console:{m.type}:{m.text}') if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(f'pageerror:{e}'))
        page.on('response', lambda r: errors.append(f'http:{r.status}:{r.url}') if r.status >= 500 else None)

        open_setup(page, base)
        print('身份对照行数:', page.locator('[data-sx-id-row]').count())
        print('筛选:', page.locator('.sx-chips').first.inner_text().replace('\n', ' '))
        page.screenshot(path=str(out_dir / '01-identity-block.png'))

        page.click('[data-sx-id-chip="enemy"]')
        page.wait_for_timeout(250)
        print('对手筛选可见行:', page.locator('[data-sx-id-row]:visible').count())
        page.fill('[data-sx-id-search]', '凤雏')
        page.wait_for_timeout(250)
        print('搜索 凤雏 可见行:', page.locator('[data-sx-id-row]:visible').count())
        page.fill('[data-sx-id-search]', '')

        # 命名本队账号（顺手建一支测试队）
        open_setup(page, base, 'unmapped')
        row = page.locator('[data-sx-id-row][data-state="unmapped"]:visible').first
        print('命名:', row.locator('.sx-id-gid b').inner_text())
        row.locator('[data-sx-id-open]').click()
        page.wait_for_selector('#sx-identity-dialog[open]')
        page.screenshot(path=str(out_dir / '02-dialog.png'))
        page.fill('#sx-identity-dialog [name="name"]', '巡检选手甲')
        page.select_option('#sx-identity-dialog [name="position"]', '发育路')
        page.select_option('#sx-identity-dialog [name="teamId"]', index=0)
        page.fill('#sx-identity-dialog [name="teamName"]', '巡检测试队')
        page.click('#sx-identity-dialog button[type=submit]')
        page.wait_for_timeout(1300)

        open_setup(page, base, 'mapped')
        mapped = page.locator('[data-sx-id-row][data-state="mapped"]:visible')
        print('命名后已命名行:', mapped.count())
        print('行内容:', ' | '.join(x for x in mapped.first.inner_text().split('\n') if x.strip()))
        page.screenshot(path=str(out_dir / '03-after-naming.png'))

        # 改名
        mapped.first.locator('[data-sx-id-open]').click()
        page.wait_for_selector('#sx-identity-dialog[open]')
        page.fill('#sx-identity-dialog [name="name"]', '巡检选手乙')
        page.click('#sx-identity-dialog button[type=submit]')
        page.wait_for_timeout(1300)
        open_setup(page, base, 'mapped')
        print('改名后:', ' | '.join(x for x in page.locator('[data-sx-id-row][data-state="mapped"]:visible').first.inner_text().split('\n') if x.strip()))

        # 解绑
        page.once('dialog', lambda d: d.accept())
        page.locator('[data-sx-id-row][data-state="mapped"]:visible [data-sx-id-unmap]').first.click()
        page.wait_for_timeout(1300)
        open_setup(page, base, 'mapped')
        print('解绑后已命名行:', page.locator('[data-sx-id-row][data-state="mapped"]:visible').count())

        # 对手命名 → 对手归属显示真名
        open_setup(page, base, 'enemy')
        enemy = page.locator('[data-sx-id-row][data-state="unmapped"][data-side="enemy"]:visible').first
        enemy.locator('[data-sx-id-open]').click()
        page.wait_for_selector('#sx-identity-dialog[open]')
        page.fill('#sx-identity-dialog [name="name"]', '巡检对手甲')
        page.select_option('#sx-identity-dialog [name="position"]', '打野')
        page.click('#sx-identity-dialog button[type=submit]')
        page.wait_for_timeout(1300)

        page.goto(f'{base}/#ownership', wait_until='networkidle')
        page.wait_for_selector('.sx-own-group')
        print('对手归属命名按钮:', page.locator('.sx-own-player [data-sx-id-open]').count())
        page.screenshot(path=str(out_dir / '04-ownership.png'))

        # 删除选手（回身份对照删掉巡检对手）
        open_setup(page, base, 'mapped')
        page.once('dialog', lambda d: d.accept())
        page.locator('[data-sx-id-row][data-state="mapped"]:visible [data-sx-id-delete]').first.click()
        page.wait_for_timeout(1300)
        open_setup(page, base, 'mapped')
        print('删除后已命名行:', page.locator('[data-sx-id-row][data-state="mapped"]:visible').count())

        page.goto(f'{base}/#identity', wait_until='networkidle')
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / '05-identity-page.png'))
        page.goto(f'{base}/#players', wait_until='networkidle')
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / '06-players.png'))
        browser.close()
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='身份对照端到端巡检（跑在隔离实例上）')
    parser.add_argument('--base', default='http://127.0.0.1:8772')
    parser.add_argument('--out', default='.screenshots/identity')
    args = parser.parse_args()
    problems = run(args.base.rstrip('/'), Path(args.out))
    print('\n控制台 / 5xx 报错:', len(problems))
    for item in problems[:12]:
        print(' ', item)
    sys.exit(1 if problems else 0)
