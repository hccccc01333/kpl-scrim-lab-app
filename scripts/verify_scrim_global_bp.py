"""Browser regression: 征召 BP is 18-hand, and the strategy sandbox can
complete a full 20-action draft.

No fixture/mock: the evidence source is read from the local workbench.
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"


def check(width, height):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script(
            "localStorage.setItem('training-tour-complete-v3', '1')")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/#bp", wait_until="domcontentloaded")
        page.wait_for_selector(".bpl-page .bpl-sections", timeout=20000)
        page.evaluate("document.querySelector('.tour-layer')?.remove()")
        page.get_by_role("button", name="BP 策略模拟", exact=False).click()
        page.wait_for_selector("#bpl-simulate [data-bpl-sim-candidate]", timeout=20000)
        text = page.locator("#bpl-simulate").inner_text()
        assert "18 手" in text, text[:300]

        for turn in range(18):
            candidates = page.locator("#bpl-simulate [data-bpl-sim-candidate]")
            candidates.first.wait_for(timeout=15000)
            candidates.first.click()
            page.wait_for_function(
                """(n) => {
                    const done = document.querySelector('#bpl-simulate')?.innerText || '';
                    if (done.includes('本局 BP 已完成')) return true;
                    return document.querySelectorAll('#bpl-simulate .bpl-sim-event').length >= n;
                }""",
                arg=turn + 1, timeout=15000)

        page.wait_for_selector("#bpl-simulate .bpl-empty", timeout=15000)
        assert "本局 BP 已完成" in page.locator("#bpl-simulate").inner_text()
        assert len(errors) == 0, errors
        assert page.locator(".bpl-page").evaluate(
            "(el) => el.scrollWidth <= el.clientWidth + 3")
        browser.close()


if __name__ == "__main__":
    check(1440, 900)
    check(390, 844)
    print("Scrim 18-hand rule + full BP sandbox browser regression: PASS")
