"""V3 全站回归：所有一级/二级路由渲染、报错、请求失败。"""
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


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        bad = 0
        print(f"{'路由':<14}{'h1':<22}{'内容':>7}{'错误':>7}结论")
        print("-" * 74)
        for name, route in ROUTES:
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)[:90]))
            try:
                page.goto(f"{BASE}/v3/{route}", wait_until="load", timeout=25000)
                page.wait_for_timeout(2200)
                info = page.evaluate(
                    """() => ({
                        h1: (document.querySelector('#content h1')?.textContent || '').trim().slice(0, 20),
                        len: (document.querySelector('#content')?.innerHTML || '').length,
                        failed: document.querySelector('#content .empty')?.textContent?.slice(0, 40) || '',
                    })"""
                )
                broken = info["len"] < 300 or errs
                if broken:
                    bad += 1
                print(f"{name:<14}{info['h1'] or '—':<22}{info['len']:>7}{len(errs):>7}"
                      f"{'FAIL ' + '; '.join(errs)[:40] if broken else 'OK'}")
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"{name:<14}{'—':<22}{'—':>7}{'—':>7}FAIL {str(exc)[:40]}")
            page.close()
        browser.close()
        print("-" * 74)
        print(f"共 {len(ROUTES)} 条，失败 {bad} 条")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
