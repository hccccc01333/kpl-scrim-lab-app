#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BP 页冒烟：有数据看版式，没数据看空态，两种情况都不许报错或横向溢出。

    python scripts/verify_bp_shell.py http://127.0.0.1:8766

为什么单独一条：``bp`` 路由先后换过两版 DOM（``.bpi-*`` 情报面板、``.bpl-*``
旧概览），对应的两条浏览器回归脚本还在 CI 里等这些已经不存在的选择器，
于是每次提交都红。这条只盯现在真正渲染的 ``.bps`` 页面：

1. 打开 ``#bp``，页面必须落到「有数据」或「空态」之一，不许停在骨架；
2. 不许有 JS 异常，也不许出现横向溢出（窄屏 390 再验一次）；
3. 空态里点「载入模拟数据」必须能渲染出完整 BP 界面。
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8766').rstrip('/')
TOUR = "localStorage.setItem('training-tour-complete-v3', '1')"


def settle(page, timeout: int = 25000) -> str:
    """等到骨架消失，返回 'data' 或 'empty'。"""
    page.wait_for_function(
        """() => {
            const root = document.querySelector('#content');
            if (!root) return false;
            if (root.querySelector('.bps-console, .bps-sticky')) return true;
            if (root.querySelector('.bps-unavailable')) return true;
            if (root.querySelector('.bps-empty')) return true;
            return false;
        }""",
        timeout=timeout)
    if page.locator('.bps-unavailable').count():
        return 'empty'
    return 'data'


def run(width: int, height: int) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.add_init_script(TOUR)
        errors: list[str] = []
        page.on('pageerror', lambda err: errors.append(str(err)[:140]))
        page.goto(f'{BASE}/#bp', wait_until='domcontentloaded')
        kind = settle(page)
        assert not errors, f'BP 页面有 JS 异常：{errors}'
        box = page.locator('#content')
        assert box.count() > 0, 'BP 页面没有渲染到 #content'
        if kind == 'empty':
            assert page.locator('.bps-unavailable').is_visible(), '空态没有显示出来'
            assert page.get_by_text('还没有可分析的 BP 记录').is_visible(), '空态缺标题'
            assert page.locator('[data-bps-demo]').count() == 1, '空态缺「载入模拟数据」入口'
            assert page.locator('a[href="#ingest"]').count() >= 1, '空态缺「去采集」入口'
        else:
            assert page.locator('.bps-console').count() >= 1, '有数据时控制台没渲染'
        overflow = page.evaluate(
            "() => { const el = document.querySelector('#content');"
            " return el ? el.scrollWidth - el.clientWidth : 0; }")
        assert overflow <= 3, f'{width}px 下 BP 页面横向溢出 {overflow}px'
        print(f'{width}×{height}: {kind}  ok（错误 0）')
        browser.close()
        return kind


def main() -> int:
    kinds = {run(1440, 900), run(390, 844)}
    assert len(kinds) == 1, f'宽窄屏渲染结果不一致：{kinds}'
    kind = kinds.pop()
    if kind == 'empty':
        # 空态里的模拟数据入口要真的能用，否则教练只能看到一句「还没有」。
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.add_init_script(TOUR)
            page.goto(f'{BASE}/#bp', wait_until='domcontentloaded')
            settle(page)
            page.locator('[data-bps-demo]').click()
            # 点完之后旧空态还在 DOM 里（重取期间不闪骨架），所以直接等控制台出现。
            page.wait_for_selector('.bps-console', timeout=40000)
            assert page.locator('.bps-console').count() >= 1, '载入模拟数据后没渲染出 BP 界面'
            print('空态 → 载入模拟数据：ok')
            browser.close()
    print('BP 页面冒烟通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
