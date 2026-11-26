#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选手详情页视觉回归：黑白杂志感、扁平层级、吸顶与窄屏适配。

用法：
    python scripts/verify_player_detail_visual.py http://127.0.0.1:8766
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8766').rstrip('/')
PLAYER = '信则有'
SHOT_DIR = Path('.screenshots') / 'pd'


def rgb(value: str) -> tuple[int, int, int]:
    nums = re.findall(r'\d+(?:\.\d+)?', value or '')
    if len(nums) < 3:
        raise AssertionError(f'无法解析颜色：{value!r}')
    return tuple(round(float(n)) for n in nums[:3])


def run(width: int, height: int) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3','1');")
        errors: list[str] = []
        page.on('pageerror', lambda error: errors.append(str(error)[:180]))
        page.goto(f"{BASE}/#playerdetail/{PLAYER}", wait_until='domcontentloaded')
        page.get_by_role('heading', name=PLAYER, exact=True).wait_for(timeout=40000)
        page.locator('.pdx-scope').wait_for(state='visible', timeout=40000)
        page.evaluate('() => window.scrollTo(0, 0)')

        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 3, f'{width}px 文档横向溢出 {overflow}px'

        header = page.locator('.hero-masthead')
        header_bg = rgb(header.evaluate("el => getComputedStyle(el).backgroundColor"))
        assert header_bg == (32, 34, 39), f'页头不是深墨色：{header_bg}'
        assert header.evaluate("el => getComputedStyle(el).boxShadow") == 'none'

        kpi = page.locator('.hero-kpi')
        columns = kpi.evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length")
        expected = 6 if width > 1100 else 3 if width > 720 else 2
        assert columns == expected, f'{width}px KPI 列数 {columns}，期望 {expected}'
        cells = page.locator('.hero-kpi-cell')
        assert cells.count() == 6
        assert cells.nth(0).evaluate("el => getComputedStyle(el).borderRightWidth") == '1px'
        assert cells.nth(5).evaluate("el => getComputedStyle(el).borderRightWidth") == '0px'

        section_style = page.locator('.hero-detail-grid > .section').first.evaluate(
            "el => { const c = getComputedStyle(el); return {background: c.backgroundColor,"
            "border: c.borderTopWidth, radius: c.borderRadius, shadow: c.boxShadow}; }")
        assert section_style == {'background': 'rgba(0, 0, 0, 0)', 'border': '0px',
                                 'radius': '0px', 'shadow': 'none'}, section_style
        card_style = page.locator('.pdx-card').first.evaluate(
            "el => { const c = getComputedStyle(el); return {border: c.borderTopWidth, radius: c.borderRadius}; }")
        panel_style = page.locator('.pv-panel').first.evaluate(
            "el => { const c = getComputedStyle(el); return {border: c.borderTopWidth, radius: c.borderRadius}; }")
        assert card_style == {'border': '0px', 'radius': '0px'}, card_style
        assert panel_style == {'border': '1px', 'radius': '12px' if width > 720 else '10px'}, panel_style

        page.get_by_role('heading', name='01 / 同分路对比', exact=True).wait_for(state='attached')
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / f'refined-{width}-top.png'), full_page=False)
        page.evaluate('() => window.scrollTo(0, 520)')
        page.wait_for_timeout(120)
        sticky = page.evaluate("""() => {
          const desk = document.querySelector('.desk-bar');
          const dock = document.querySelector('.pdx-dock');
          if (!desk || !dock) return null;
          return {deskBottom: desk.getBoundingClientRect().bottom,
                  dockTop: dock.getBoundingClientRect().top};
        }""")
        assert sticky is not None, '缺少工作栏或切片条，无法验证吸顶'
        assert sticky['dockTop'] >= sticky['deskBottom'] - 1, sticky

        assert not errors, f'{width}px 有 JS 异常：{errors[:3]}'
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / f'refined-{width}.png'), full_page=False)
        print(f'{width}×{height}: 视觉层级 / KPI / 吸顶 / 溢出  ok')
        browser.close()


def main() -> int:
    run(1440, 900)
    run(390, 844)
    print(f'选手详情页视觉回归通过，截图：{SHOT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
