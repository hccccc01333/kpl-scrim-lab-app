"""Read-only browser verification of the celadon interface against a running workbench.

No fixtures are seeded and no server write endpoints are called.
Example: python scripts/verify_celadon_ui.py --base http://127.0.0.1:8792
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROUTES = (
    'overview', 'matches', 'teams', 'playerarchive', 'heroes', 'bp', 'cross', 'biggame',
    'featured', 'versions', 'series-builder', 'ingest', 'capture', 'shots',
    'videos', 'replays', 'plan', 'reports', 'setup', 'sources', 'coach',
    'combos', 'playercompare', 'herocompare',
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--out', type=Path, default=Path('.cache/celadon-ui-check'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    views = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3','1');if(!localStorage.getItem('training-rebuild-theme'))localStorage.setItem('training-rebuild-theme','light')")
        page.on('pageerror', lambda error: failures.append(str(error)))

        def goto(route: str) -> None:
            page.goto(args.base.rstrip('/') + '/#' + route)
            page.wait_for_function("!document.querySelector('.ui-loading-page')", timeout=30000)
            page.wait_for_timeout(250)
            if page.locator('#filters[open]').count():
                page.locator('#filters [data-action=close]').first.click()

        goto('overview')
        page.locator('.pbr-celadon-art').wait_for()
        assert page.locator('.pbr-celadon-art').evaluate('(e) => e.complete && e.naturalWidth > 0')
        page.locator('[data-ui-search]').focus()
        page.keyboard.press('Control+k')
        assert page.locator('#ui-command').evaluate('(e) => e.open')
        assert page.locator('#ui-command input').evaluate('(e) => e === document.activeElement')
        page.locator('#ui-command input').fill('不存在的页面xyz')
        assert page.locator('.ui-command-result').count() == 0
        page.locator('[data-clear-command]').click()
        assert page.locator('.ui-command-result').count() > 0
        page.keyboard.press('Escape')
        assert not page.locator('#ui-command').evaluate('(e) => e.open')
        assert page.locator('[data-ui-search]').evaluate('(e) => e === document.activeElement')
        page.keyboard.press('Control+k')
        page.locator('#ui-command input').fill('战队')
        page.keyboard.press('Enter')
        page.wait_for_url('**/#teams')
        assert not page.locator('#ui-command').evaluate('(e) => e.open')

        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('.menu-button').click()
        assert page.locator('#ui-navigation').evaluate('(e) => e.open && e.contains(document.activeElement)')
        page.keyboard.press('Escape')
        page.wait_for_function("document.querySelector('.menu-button').getAttribute('aria-expanded') === 'false'")
        page.locator('.menu-button').click()
        page.set_viewport_size({'width': 1100, 'height': 900})
        page.wait_for_function("!document.querySelector('#ui-navigation').open")

        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('.theme-button').click()
        assert page.locator('html').get_attribute('data-theme') == 'dark'
        page.reload()
        assert page.locator('html').get_attribute('data-theme') == 'dark'
        page.locator('.theme-button').click()

        for route in ROUTES:
            goto(route)
            assert page.locator('#content').inner_text().strip(), route
            for width in (1440, 1024, 768, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                actual = page.evaluate('document.documentElement.scrollWidth')
                views.append({'route': route, 'width': width, 'scrollWidth': actual})
                if actual > width + 1:
                    failures.append(f'{route} at {width}px overflows to {actual}px')
            page.set_viewport_size({'width': 1440, 'height': 1000})

        # A failed secondary request must leave the summary and its recovery control available.
        page.route('**/api/briefing?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
        goto('overview')
        page.locator('.pbr-error').wait_for(timeout=25000)
        assert page.locator('.pbr-title').is_visible()
        page.unroute('**/api/briefing?*')
        page.locator('.pbr-error [data-pbr-retry]').click()
        page.locator('.pbr-hero').wait_for(timeout=25000)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(args.out / 'desktop.png'))

        page.emulate_media(reduced_motion='reduce')
        assert page.evaluate("getComputedStyle(document.querySelector('.pbr-celadon-art')).animationName") == 'none'
        page.set_viewport_size({'width': 390, 'height': 844})
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(args.out / 'mobile.png'))
        browser.close()
    report = {'views': views, 'failures': failures, 'checks': ['routes', 'responsive overflow', 'search', 'keyboard focus', 'native Escape', 'drawer resize', 'theme persistence', 'brief API failure and retry', 'reduced motion']}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'celadon UI: {len(views)} route/viewport checks and all interaction checks passed')


if __name__ == '__main__':
    main()
