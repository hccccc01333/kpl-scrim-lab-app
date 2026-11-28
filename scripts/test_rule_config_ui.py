"""Behavioral regression checks for the five audited rule-configuration pages.

Run against a local server: python scripts/test_rule_config_ui.py
All API writes are intercepted; this test never changes project data.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = os.environ.get("RULE_CONFIG_TEST_BASE", "http://127.0.0.1:8766").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEROES = [f"英雄{i:02d}" for i in range(1, 21)]
META = {
    "icons": {name: f"/catalog/icons/hero-{i}.png" for i, name in enumerate(HEROES, 1)},
    "heroTypes": {name: {"游走": "辅助"} for name in HEROES},
}


def grade_fixture():
    subjects = {}
    for subject in ("对抗路", "发育路", "中路", "打野·坦野", "打野·野核", "游走"):
        subjects[subject] = {
            "metric": {"label": "测试指标", "direction": "up", "thresholds": [0, 0, 0], "active": True, "unit": "分"},
        }
        if subject in ("对抗路", "发育路", "中路"):
            subjects[subject]["cs"] = {
                "label": "补刀", "direction": "up", "thresholds": [10, 8, 6], "active": True,
                "unit": "个", "minuteStandard": {"18": 8},
            }
    subjects["游走"]["missing"] = {
        "label": "未配置指标", "direction": "down", "thresholds": [None, None, None], "active": False, "unit": "分",
    }
    return {"revision": 1, "saved": True, "subjects": subjects, "defaults": subjects}


def install_routes(page):
    posts: list[tuple[str, dict]] = []
    grade = grade_fixture()
    tags = [{"id": "tag-1", "name": "测试阵容", "heroes": HEROES[:5], "note": "", "source": "manual", "createdAt": "2026-01-01T00:00:00Z"}]
    docs = {
        "hero_tags": {"revision": 1, "heroes": {"英雄01": {"id": "h1", "name": "英雄01", "defaultLane": "游走", "defaultType": "辅助", "lanes": {}, "matrix": {}}}},
        "counters": {"revision": 1, "heroPairs": [], "comboPairs": []},
        "misc": {"revision": 1, "entries": []},
    }
    competitions = [
        {"id": "active", "name": "进行中赛事", "date": "2099-01-01", "end_date": "2099-01-02"},
        {"id": "ended", "name": "已结束赛事", "date": "2020-01-01", "end_date": "2020-01-02"},
    ]

    def handler(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        body = request.post_data_json if method in ("POST", "PUT", "DELETE") and request.post_data else None
        if method in ("POST", "PUT", "DELETE"):
            posts.append((path, body))
        if path == "/api/metadata/icons":
            payload = META
        elif path == "/api/v3/custom-combos":
            payload = body or {"revision": 1, "pairs": [{"id": "p1", "name": "双人测试", "heroes": HEROES[:2], "strength": "strong"}], "trios": []}
            if method == "GET":
                payload = {"revision": 1, "pairs": [{"id": "p1", "name": "双人测试", "heroes": HEROES[:2], "strength": "strong"}], "trios": []}
        elif path == "/api/v3/grade-rules":
            payload = body or grade
            if method == "GET":
                payload = grade
        elif path == "/api/v3/lineup-tags/meta":
            payload = {"heroes": HEROES, "lanes": {name: ["游走"] for name in HEROES}, "defaults": []}
        elif path == "/api/v3/lineup-tags":
            if method == "POST" and isinstance(body, dict) and isinstance(body.get("tags"), list):
                tags[:] = body["tags"]
            payload = body or {"revision": 1, "tags": tags}
            if method == "GET":
                payload = {"revision": 1, "tags": tags}
        elif path == "/api/studio/workspace/competitions":
            payload = {"competitions": competitions}
        elif path.startswith("/api/v3/rules-center/"):
            kind = path.rsplit("/", 1)[-1]
            payload = body.get("doc", body) if isinstance(body, dict) and method != "GET" else docs.get(kind, {"revision": 1})
        elif path == "/api/v3/rule-snapshots":
            payload = body or {"competitions": {}}
        else:
            payload = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    page.route("**/api/**", handler)
    return posts


def open_harness(page):
    index = open(os.path.join(ROOT, "v3/public/index.html"), encoding="utf-8").read()
    links = "\n".join(
        f'<link rel="stylesheet" href="{href.split("?")[0]}">'
        for href in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', index)
    )
    page.route("**/__rule_config_test__", lambda route: route.fulfill(
        status=200, content_type="text/html",
        body=f"<!doctype html><html><head>{links}</head><body><div id='content'><div id='root'></div></div></body></html>",
    ))
    page.goto(f"{BASE}/__rule_config_test__")
    page.set_viewport_size({"width": 1440, "height": 900})


def mount(page, module, factory, **options):
    page.evaluate("""async ({module, factory, options}) => {
      const mod = await import(`/static/${module}.js?test=${Date.now()}`);
      window.pageModule = mod[factory]({API_BASE: '', ...options});
      window.pageModule.mount(document.querySelector('#root'));
    }""", {"module": module, "factory": factory, "options": options})
    page.wait_for_function("window.pageModule && (!window.pageModule.state || !('ready' in window.pageModule.state) || window.pageModule.state.ready === true)")


def assert_visible(page, selector):
    assert page.locator(selector).is_visible(), f"not visible: {selector}"


def test_combo(page):
    mount(page, "combo-pool", "createComboPoolPage", getMetadata=lambda: META)
    assert page.locator("[data-cp-submit]").is_disabled()
    assert "选 2 个" in page.locator("[data-cp-form-hint]").inner_text()
    assert page.locator("[data-cp-cancel-edit]").is_hidden()
    assert page.locator(".cp-lanes [data-cp-lane-pick]").count() == 0
    assert page.locator(".cp-lane-actions [data-cp-lane-pick]").count() == 1
    assert page.locator("[data-cp-grid].cp-grid--bounded").count() == 1
    assert page.locator("[data-cp-filter-grid].cp-grid--bounded").count() == 1
    assert_visible(page, "[data-cp-start-pick]")
    page.locator("[data-cp-start-pick]").click()
    assert page.locator("[data-cp-search]").evaluate("el => el === document.activeElement")
    page.locator("[data-cp-hero='英雄01']").click()
    page.locator("[data-cp-hero='英雄02']").click()
    assert page.locator("[data-cp-submit]").is_enabled()
    assert page.locator("[data-cp-submit]").get_attribute("aria-describedby")
    page.locator("[data-cp-edit='p1']").click()
    assert_visible(page, "[data-cp-cancel-edit]")
    page.locator("[data-cp-cancel-edit]").click()
    assert page.locator("[data-cp-cancel-edit]").is_hidden()
    assert page.locator("[data-cp-submit]").is_disabled()
    columns = page.locator("[data-cp-grid]").evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length")
    assert columns <= 8, f"hero grid has {columns} columns"


def test_grade(page, posts):
    mount(page, "grade-rules", "createGradeRulesPage")
    zero = page.locator("[data-gr-th='metric'][data-gr-index='0']")
    missing = page.locator("[data-gr-th='missing'][data-gr-index='0']")
    assert zero.input_value() == "0"
    assert missing.input_value() == ""
    assert missing.get_attribute("placeholder") == "未配置"
    assert "卓越 ≤ 达标" in page.locator("[data-gr-th='missing']").first.locator("xpath=ancestor::tr").inner_text()
    zero.fill("4")
    assert "有未保存更改" in page.locator("[data-gr-rev]").inner_text()
    assert page.locator("[data-gr-save]").is_enabled()
    page.locator("[data-gr-only-active]").check()
    page.locator("[data-gr-all-on]").click()
    assert page.locator("[data-gr-active='metric']").is_checked()
    assert page.locator("[data-gr-active='missing']").is_checked()
    page.locator("[data-gr-all-off]").click()
    assert not page.locator("[data-gr-only-active]").is_checked()
    assert page.locator("[data-gr-tbody] tr").count() == 2
    before = len([p for p in posts if p[0] == "/api/v3/grade-rules"])
    page.locator("[data-gr-save]").click()
    page.wait_for_timeout(100)
    assert len([p for p in posts if p[0] == "/api/v3/grade-rules"]) == before
    assert "未配置" in page.locator("[data-gr-status]").inner_text()
    for index, value in enumerate(("0", "1", "2")):
        page.locator(f"[data-gr-th='missing'][data-gr-index='{index}']").fill(value)
    page.locator("[data-gr-save]").click()
    page.wait_for_function("document.querySelector('[data-gr-rev]')?.textContent.includes('已保存')")
    sent = [p[1] for p in posts if p[0] == "/api/v3/grade-rules"][-1]
    assert sent["subjects"]["游走"]["missing"]["thresholds"] == [0, 1, 2]
    assert all(isinstance(v, (int, float)) for rule in sent["subjects"]["游走"].values() for v in rule["thresholds"])


def test_lineup(page, posts):
    mount(page, "lineup-tags", "createLineupTagsPage")
    assert_visible(page, "[data-lt-save]")
    box = page.locator("[data-lt-save]").bounding_box()
    assert box and box["y"] + box["height"] <= 900, f"submit below first screen: {box}"
    assert page.locator("[data-lt-save]").get_attribute("form")
    assert page.locator(".lt-save").evaluate("el => el.compareDocumentPosition(document.querySelector('.lt-existing')) & Node.DOCUMENT_POSITION_FOLLOWING")
    assert page.locator(".lt-lead-actions [data-lt-snapshot]").count() == 1
    assert page.locator(".lt-editor-actions [data-lt-save]").count() == 1
    before_submit = len([p for p in posts if p[0] == "/api/v3/lineup-tags"])
    page.locator("[data-lt-name]").fill("未选英雄测试")
    page.locator("[data-lt-save]").click()
    assert "需要恰好 5 个英雄" in page.locator("[data-lt-status]").inner_text()
    assert len([p for p in posts if p[0] == "/api/v3/lineup-tags"]) == before_submit
    page.locator("[data-lt-edit='tag-1']").click()
    assert_visible(page, "[data-lt-cancel-edit]")
    page.locator("[data-lt-cancel-edit]").click()
    assert page.locator("[data-lt-cancel-edit]").is_hidden()
    before = len([p for p in posts if p[0] == "/api/v3/lineup-tags"])
    page.locator("[data-lt-delete='tag-1']").click()
    assert page.locator("[data-lt-dialog]").is_visible()
    assert "立即保存" in page.locator("[data-lt-dialog-text]").inner_text()
    assert len([p for p in posts if p[0] == "/api/v3/lineup-tags"]) == before
    page.locator("[data-lt-dialog] button[value='cancel']").click()
    assert len([p for p in posts if p[0] == "/api/v3/lineup-tags"]) == before
    page.locator("[data-lt-delete='tag-1']").click()
    page.locator("[data-lt-dialog] button[value='delete']").click()
    page.wait_for_function("() => window.pageModule.state.tags.length === 0")
    assert len([p for p in posts if p[0] == "/api/v3/lineup-tags"]) == before + 1


def test_rules(page, posts):
    mount(page, "rules-center", "createRulesCenter")
    page.wait_for_function("() => ['hero_tags','counters','misc'].every(k => window.pageModule.state.docs[k])")
    for kind in ("hero_tags", "counters", "misc"):
        panel = page.locator(f"[data-rc-save='{kind}']").locator("xpath=ancestor::section[contains(@class,'rc-panel')]")
        assert panel.locator(".rc-read-actions").count() == 1
        assert panel.locator(".rc-save-actions").count() == 1
        assert panel.locator(f"[data-rc-snapshot='{kind}']").count() == 1
        assert panel.locator(f"[data-rc-save-state='{kind}']").count() == 1
    page.locator("[data-rc-edit-hero='英雄01']").click()
    page.locator("[data-rc-dialog-body] [data-f='name']").fill("英雄01改")
    page.locator("[data-rc-dialog-submit]").click()
    assert "有未保存更改" in page.locator("[data-rc-save-state='hero_tags']").inner_text()
    assert_visible(page, "[data-rc-tab='hero-tags'] [data-rc-tab-dirty]")
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("[data-rc-tab='counters']").click()
    page.wait_for_function("window.pageModule.state.active === 'counters'")
    page.locator("[data-rc-tab='hero-tags']").click()
    page.wait_for_function("window.pageModule.state.active === 'hero-tags'")
    assert "有未保存更改" in page.locator("[data-rc-save-state='hero_tags']").inner_text()
    page.locator("[data-rc-save='hero_tags']").click()
    page.wait_for_function("document.querySelector('[data-rc-save-state=\"hero_tags\"]')?.textContent.includes('已保存')")
    page.locator("[data-rc-del-hero='英雄01改']").click()
    assert page.locator("[data-rc-dialog]").is_visible()
    assert "确认删除" in page.locator("[data-rc-dialog-submit]").inner_text()
    assert page.evaluate("window.pageModule.state.docs.hero_tags.heroes['英雄01改'].defaultLane") == "游走"
    page.locator("[data-rc-dialog-cancel]").click()
    assert page.evaluate("window.pageModule.state.docs.hero_tags.heroes['英雄01改'].defaultLane") == "游走"
    page.locator("[data-rc-del-hero='英雄01改']").click()
    page.locator("[data-rc-dialog-submit]").click()
    assert page.evaluate("Object.keys(window.pageModule.state.docs.hero_tags.heroes).length") == 0
    assert "有未保存更改" in page.locator("[data-rc-save-state='hero_tags']").inner_text()


def test_snapshot(page, posts):
    page.evaluate("localStorage.clear()")
    mount(page, "snapshot-center", "createSnapshotCenter")
    page.wait_for_function("document.querySelectorAll('.sc-card').length === 2")
    assert not page.locator("[data-sc-how]").get_attribute("open")
    assert page.locator("[data-sc-packall]").is_disabled()
    assert "未选择赛事" in page.locator("[data-sc-packall-help]").inner_text()
    ended = page.locator(".sc-card.is-ended")
    assert ended.locator(".sc-ended-empty").count() == 1
    assert ended.locator(".sc-module").count() == 0
    assert ended.locator(".sc-progress").count() == 0
    page.evaluate("localStorage.setItem('training-current-competition', 'active'); localStorage.setItem('training-current-competition-name', '进行中赛事')")
    page.evaluate("window.pageModule.rerender()")
    assert page.locator("[data-sc-packall]").is_enabled()
    before = len([p for p in posts if p[0] == "/api/v3/rule-snapshots"])
    page.locator("[data-sc-expired-packall='ended']").click()
    assert page.locator("[data-sc-dialog]").is_visible()
    assert len([p for p in posts if p[0] == "/api/v3/rule-snapshots"]) == before
    page.locator("[data-sc-cancel]").click()
    assert len([p for p in posts if p[0] == "/api/v3/rule-snapshots"]) == before
    page.locator("[data-sc-expired-packall='ended']").click()
    page.locator("[data-sc-confirm]").click()
    page.wait_for_function("document.querySelector('[data-sc-status]')?.textContent.includes('已用当下六类规则归档')")
    written = [body["module"] for path, body in posts if path == "/api/v3/rule-snapshots" and body]
    assert len(written) == 6 and len(set(written)) == 6


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, test in (
                ("combo-pool", test_combo),
                ("grade-rules", test_grade),
                ("lineup-tags", test_lineup),
                ("rules-center", test_rules),
                ("snapshot-center", test_snapshot),
            ):
                page = browser.new_page()
                posts = install_routes(page)
                open_harness(page)
                if name in ("grade-rules", "lineup-tags", "rules-center", "snapshot-center"):
                    test(page, posts)
                else:
                    test(page)
                print(f"PASS {name}")
                page.close()
        finally:
            browser.close()
    print("rule configuration UI: all behavioral assertions passed")


if __name__ == "__main__":
    main()
