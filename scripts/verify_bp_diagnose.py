"""Browser regression: 己方英雄诊断 N01–N16 on KPL and scrim.

No fixture/mock: reads the local workbench. Checks that KPL explicitly marks
missing player/replay stats, scrim uses camp per-player stats, and the page has
no JS errors or horizontal overflow at desktop and 390px.
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"


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
        page.locator('[data-bpl-view="diagnose"]').click()
        page.wait_for_selector("[data-bpl-diagnose-hero]", timeout=30000)
        page.wait_for_timeout(1200)

        text = page.locator(".bpl-page").inner_text()
        for needle in ("N01", "N02", "N03", "N04", "N05", "N06", "N07",
                       "N08", "N09", "N10", "N11", "N12", "N13", "N14",
                       "N15", "N16"):
            assert needle in text, needle
        assert "当前来源没有逐人表现" in text or "KDA" in text
        assert "没有回放经济曲线" in text or "经济检查点" in text

        # Specific enemy lineup becomes an explicit N02 block.
        page.locator("[data-bpl-diagnose-enemy]").fill("敖隐,钟馗")
        page.locator("[data-bpl-diagnose-run]").click()
        page.wait_for_selector("#bpl-diagnosePerf .bpl-diag-lineup-stat", timeout=30000)

        # Scrim: camp per-player stats should be usable.
        page.locator('[data-bpl-source="scrim"]').click()
        page.wait_for_function(
            "() => document.body.innerText.includes('训练赛 · 营地面板')"
            " && document.querySelectorAll('[data-bpl-view]').length === 5",
            timeout=30000)
        page.locator('[data-bpl-view="diagnose"]').click()
        page.wait_for_selector("[data-bpl-diagnose-hero]", timeout=30000)
        page.wait_for_function(
            "() => /KDA/.test(document.querySelector('#bpl-diagnoseAttribution')?.innerText || '')",
            timeout=30000)
        scrim_text = page.locator("#bpl-diagnoseAttribution").inner_text()
        assert "KDA" in scrim_text, scrim_text[:300]
        assert "参团率" in scrim_text, scrim_text[:300]

        assert len(errors) == 0, errors
        assert page.locator(".bpl-page").evaluate(
            "(el) => el.scrollWidth <= el.clientWidth + 3")
        browser.close()


if __name__ == "__main__":
    check(1440, 900)
    check(390, 844)
    print("BP hero diagnosis N01-N16 browser regression: PASS")
