"""Regression for coach-facing BP priorities and multi-round tree interactions.

Uses deterministic intercepted API data, not fabricated production results;
actual research outcomes are independently tested from Python source rows.
Requires an already-running V3 server and Playwright chromium.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"


def evidence(i):
    return {"id": "sample-" + str(i), "date": "2026-11-13",
            "team": "本队", "enemy": "对手A",
            "source": "scrim", "result": True,
            "matchId": "sample-" + str(i), "processMatchKey": ""}


def fixture():
    nodes = [
        {"id": 0, "parent": None, "actor": None, "action": None,
         "hero": None, "depth": 0, "games": 5, "decided": 5,
         "wins": 3, "evidence": [evidence(0)]},
        {"id": 1, "parent": 0, "actor": "team", "action": "ban",
         "hero": "朵莉亚", "depth": 1, "games": 4, "decided": 4,
         "wins": 3, "evidence": [evidence(1)]},
        {"id": 2, "parent": 0, "actor": "team", "action": "ban",
         "hero": "大乔", "depth": 1, "games": 1, "decided": 1,
         "wins": 0, "evidence": [evidence(2)]},
        {"id": 3, "parent": 1, "actor": "enemy", "action": "ban",
         "hero": "亚连", "depth": 2, "games": 4, "decided": 4,
         "wins": 3, "evidence": [evidence(1)]},
        {"id": 4, "parent": 3, "actor": "enemy", "action": "pick",
         "hero": "夏洛特", "depth": 3, "games": 4, "decided": 4,
         "wins": 3, "evidence": [evidence(1)]},
        {"id": 5, "parent": 4, "actor": "team", "action": "pick",
         "hero": "马超", "depth": 4, "games": 4, "decided": 4,
         "wins": 3, "evidence": [evidence(1)]},
    ]
    return {
        "schema": "bp-research-v1", "source": "scrim", "team": "本队",
        "teams": [{"name": "本队", "games": 5}],
        "scope": {"games": 5, "orderedGames": 5, "playerGames": 0,
                  "decided": 5, "wins": 3, "winRate": 60.0},
        "picks": [], "bans": [], "pairs": [], "trios": [], "players": [],
        "findings": [], "limitations": [],
        "bpStudies": {
            "draftTree": {"orderedGames": 5, "indexedGames": 5,
                          "limited": False, "nodes": nodes},
            "priorities": [{
                "kind": "relative-preference", "level": "重点",
                "title": "对手特别偏爱：马超",
                "detail": "该战队使用 5/5 局；与其他战队对照已通过筛查。",
                "action": "提前准备限制或放出时的 BP 路径。",
                "evidence": [evidence(1)],
            }],
            "version": {"options": [], "coverage": {"games": 5, "knownGames": 0}},
            "twoStep": [],
        },
    }


def check(width, height):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script("localStorage.setItem('training-tour-complete-v3', '1')")
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        sample = fixture()
        page.route("**/api/v3/bp-intelligence*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=__import__("json").dumps(sample, ensure_ascii=False)))
        page.goto(BASE + "/#bp", wait_until="domcontentloaded")
        page.wait_for_selector(".bpi-view-tabs", timeout=20000)
        page.get_by_text("赛前关注优先级").wait_for(timeout=9000)
        assert page.get_by_text("对手特别偏爱：马超").is_visible()
        page.locator("[data-bpi-view='sandbox']").first.click()
        page.get_by_text("完整 BP 历史决策树").wait_for(timeout=9000)
        assert page.locator("[data-bpi-tree-node='1']").count() == 1
        page.locator("[data-bpi-tree-node='1']").click()
        assert "朵莉亚" in page.locator(".bpi-tree-path").inner_text()
        page.locator("[data-bpi-tree-node='3']").last.click()
        assert "亚连" in page.locator(".bpi-tree-path").inner_text()
        page.locator("[data-bpi-tree-back]").click()
        assert "亚连" not in page.locator(".bpi-tree-path").inner_text()
        page.locator("[data-bpi-tree-reset]").click()
        assert page.locator(".bpi-tree-path button").count() == 0
        assert not errors, "BP runtime errors: " + "; ".join(errors)
        assert page.locator(".bpi").count() > 0
        assert page.locator(".bpi").evaluate(
            "(el) => el.scrollWidth <= el.clientWidth + 3"), "BP horizontal overflow"
        browser.close()


if __name__ == "__main__":
    check(1440, 900)
    check(390, 844)
    print("BP coach priority + multi-round draft interaction regression: PASS")
