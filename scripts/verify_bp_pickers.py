"""Browser regression: BP custom hero pickers and per-section time window.

No fixture/mock: reads the local workbench.
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"


def pick(page, section, action, hero):
    selector = f'#{section} [data-bpl-pick="{action}"][data-bpl-pick-hero="{hero}"]'
    page.locator(selector).click()
    page.wait_for_timeout(250)


def check(width, height):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3', '1')")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/#bp", wait_until="domcontentloaded")
        page.wait_for_selector(".bpl-page .bpl-sections", timeout=30000)
        page.evaluate("document.querySelector('.tour-layer')?.remove()")
        page.wait_for_selector("#bpl-combos .bpl-picker", timeout=30000)
        assert page.locator("#bpl-combos .bpl-picker-prompt").count() == 1
        pick(page, "bpl-combos", "combo", "小乔")
        pick(page, "bpl-combos", "combo", "张飞")
        page.wait_for_function(
            "() => document.querySelector('#bpl-combos .bpl-custom-combo .bpl-combo-cell')?.innerText.includes('小乔')",
            timeout=30000)
        combo_text = page.locator("#bpl-combos .bpl-custom-combo").inner_text()
        assert "张飞" in combo_text
        assert "命中局数" in combo_text

        # Per-section time control stays near the same section.
        page.locator('#bpl-combos [data-bpl-section-days="7"]').click()
        page.wait_for_function(
            "() => document.querySelector('#bpl-combos [data-bpl-section-days=\"7\"]')?.getAttribute('aria-pressed') === 'true'",
            timeout=30000)
        page.wait_for_timeout(500)
        assert page.locator("#bpl-combos").evaluate(
            "(el) => el.getBoundingClientRect().top < el.ownerDocument.documentElement.clientHeight")

        # Counter picker: clear then choose one hero.
        page.locator('#bpl-counters [data-bpl-picker-details="counter"] summary').click()
        page.wait_for_timeout(150)
        page.locator('#bpl-counters [data-bpl-picker-clear="counter"]').click()
        pick(page, "bpl-counters", "counter", "小乔")
        page.wait_for_timeout(800)
        assert page.locator('#bpl-counters .bpl-picker-chip').count() == 1

        # Stability picker: clear then choose two heroes (scrim view).
        page.locator('[data-bpl-view="scrim"]').click()
        page.wait_for_selector('#bpl-stability [data-bpl-picker-details="stability"]', timeout=30000)
        page.locator('#bpl-stability [data-bpl-picker-details="stability"] summary').click()
        page.wait_for_timeout(150)
        page.locator('#bpl-stability [data-bpl-picker-clear="stability"]').click()
        pick(page, "bpl-stability", "stability", "小乔")
        pick(page, "bpl-stability", "stability", "张飞")
        page.wait_for_timeout(1200)
        assert page.locator('#bpl-stability .bpl-picker-chip').count() == 2

        assert len(errors) == 0, errors
        assert page.locator(".bpl-page").evaluate(
            "(el) => el.scrollWidth <= el.clientWidth + 3")
        browser.close()


if __name__ == "__main__":
    check(1440, 900)
    check(390, 844)
    print("BP custom picker + section time window browser regression: PASS")
