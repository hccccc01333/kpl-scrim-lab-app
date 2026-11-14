"""Browser regression: actual scrim next-action API + interactive BO global BP.

The BP research summary is fixture-backed to avoid requiring local scrim
records; the rule/catalog endpoint is NOT mocked and uses repo runtime.
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_bp_interactions import fixture  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"


def check(width, height):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3', '1')")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        report = fixture()
        page.route("**/api/v3/bp-intelligence*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(report, ensure_ascii=False)))
        page.goto(BASE + "/#bp", wait_until="domcontentloaded")
        page.get_by_text("BP 情报研究").wait_for(timeout=20000)
        page.locator("[data-bpi-view='sandbox']").first.click()
        page.get_by_text("训练赛 · BO 全局 BP 合法选禁沙盘").wait_for(timeout=12000)
        page.locator(".bpi-scrim-herolist button").first.wait_for(timeout=12000)
        assert page.locator(".bpi-scrim-stage").inner_text().find("第 1 手") >= 0
        for turn in range(15):
            page.locator(".bpi-scrim-herolist button").first.wait_for(timeout=12000)
            page.locator(".bpi-scrim-herolist button").first.click()
            page.wait_for_function(
                "(n) => document.querySelectorAll('.bpi-scrim-history-steps > span').length === n",
                arg=turn + 1, timeout=12000)
        page.locator(".bpi-scrim-finished").wait_for(timeout=12000)
        assert page.locator(".bpi-scrim-history-steps > span").count() == 15

        page.locator("[data-bpi-scrim-next-game]").click()
        page.wait_for_function(
            "() => document.querySelector('[data-bpi-scrim-game]').value === '2'",
            timeout=12000)
        page.locator(".bpi-scrim-herolist button").first.wait_for(timeout=12000)
        prior_own = page.locator("[data-bpi-scrim-history-own]").input_value()
        prior_enemy = page.locator("[data-bpi-scrim-history-enemy]").input_value()
        assert len(prior_own.split("，")) == 5 and len(prior_enemy.split("，")) == 5
        used_own = prior_own.split("，")[0]

        # Ban five unrelated late heroes; previously picked heroes must still
        # be blocked at the sixth action even if they were not banned this game.
        for turn in range(5):
            page.locator(".bpi-scrim-herolist button").last.wait_for(timeout=12000)
            page.locator(".bpi-scrim-herolist button").last.click()
            page.wait_for_function(
                "(n) => document.querySelectorAll('.bpi-scrim-history-steps > span').length === n",
                arg=turn + 1, timeout=12000)
        page.locator(".bpi-scrim-herolist button").first.wait_for(timeout=12000)
        page.locator("[data-bpi-scrim-search]").fill(used_own)
        assert page.locator(".bpi-scrim-herolist button").count() == 0
        assert "没有匹配的合法英雄" in page.locator(
            "[data-bpi-scrim-candidates]").inner_text()
        assert not errors, errors
        assert page.locator(".bpi").evaluate(
            "(el) => el.scrollWidth <= el.clientWidth + 3")
        browser.close()


if __name__ == "__main__":
    check(1440, 900)
    check(390, 844)
    print("Scrim BO3 global BP next-action and 15-turn browser regression: PASS")
