"""V3 全站回归：所有一级/二级路由渲染、报错、请求失败。

空态判定：`#content` 里有可见的 `.empty` 文案时算正常空态（例如
「当前范围没有可用的教练记录」），不再因为 innerHTML 短而报失败。
没有内容也没有空态说明、或页面抛 JS 异常，仍然判 FAIL。
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
ROUTES = [
    ("overview", "#overview"), ("ingest", "#ingest"), ("capture", "#capture"),
    ("matches", "#matches"), ("query", "#query"), ("featured", "#featured"),
    ("records", "#records"), ("versions", "#versions"), ("economy", "#economy"),
    ("tempo", "#tempo"), ("teams", "#teams"), ("opponents", "#opponents"),
    ("h2h", "#h2h"), ("coach", "#coach"), ("players", "#players"),
    ("identity", "#identity"), ("compare", "#compare"), ("bp", "#bp"),
    ("heroes", "#heroes"), ("combos", "#combos"), ("setup", "#setup"),
    ("pending", "#pending"), ("plan", "#plan"), ("effect", "#effect"),
    ("reports", "#reports"), ("sources", "#sources"),
]

CONTENT_MIN = 300


def classify(info: dict, errors: list[str]) -> tuple[str, str]:
    """把一次页面探测结果归成 (类型, 说明)。类型：正常 / 空态 / FAIL。"""
    if errors:
        return "FAIL", "; ".join(errors)[:60]
    empty_text = str(info.get("emptyText") or "").strip()
    loading_text = str(info.get("loadingText") or "").strip()
    length = int(info.get("len") or 0)
    if length < CONTENT_MIN and not empty_text:
        reason = "加载未完成：" + loading_text if loading_text else "空页（无内容且无空态说明）"
        return "FAIL", reason[:60]
    if info.get("emptyOnly") or (length < CONTENT_MIN and empty_text):
        return "空态", empty_text[:40]
    return "正常", ""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        bad = 0
        empty_states = 0
        print(f"{'路由':<14}{'h1':<22}{'内容':>7}{'错误':>7}  {'类型':<6}说明")
        print("-" * 88)
        for name, route in ROUTES:
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)[:90]))
            try:
                page.goto(f"{BASE}/v3/{route}", wait_until="load", timeout=25000)
                page.wait_for_timeout(2200)
                info = page.evaluate(
                    r"""() => {
                        const box = document.querySelector('#content');
                        const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
                        const visible = (el) => el.getClientRects().length > 0;
                        /* 详情路由（#identity / #match 等）没带 ID 时渲染的是
                           .offline-card「需要…ID」，那也是一种正常空态，
                           不算页面挂掉。 */
                        const texts = box ? [...box.querySelectorAll('.empty, .offline-card')]
                            .filter(visible).map((el) => clean(el.textContent)).filter(Boolean) : [];
                        const loading = texts.filter((text) => /^(正在|加载)/.test(text));
                        const empties = texts.filter((text) => !/^(正在|加载)/.test(text));
                        const pageText = clean(box ? box.textContent : '');
                        const emptyChars = empties.reduce((sum, text) => sum + text.length, 0);
                        return {
                            h1: clean(box ? box.querySelector('h1')?.textContent : '').slice(0, 20),
                            len: box ? box.innerHTML.length : 0,
                            emptyText: empties.join(' / ').slice(0, 80),
                            loadingText: loading.join(' / ').slice(0, 80),
                            emptyOnly: empties.length > 0 && pageText.length - emptyChars < 40,
                        };
                    }"""
                )
                kind, detail = classify(info, errs)
                if kind == "FAIL":
                    bad += 1
                elif kind == "空态":
                    empty_states += 1
                print(f"{name:<14}{info['h1'] or '—':<22}{info['len']:>7}{len(errs):>7}  {kind:<6}{detail}")
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"{name:<14}{'—':<22}{'—':>7}{'—':>7}  {'FAIL':<6}{str(exc)[:50]}")
            page.close()
        browser.close()
        print("-" * 88)
        print(f"共 {len(ROUTES)} 条，失败 {bad} 条，空态 {empty_states} 条")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
