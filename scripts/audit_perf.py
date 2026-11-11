"""一次性性能/健康审计：页面请求量、体积、失败请求、渲染耗时。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / ".audit-shots"
OUT.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8766"

ROUTES = ["/studio#home", "/studio#capture", "/studio#matches", "/studio#heroes", "/studio#compare", "/studio#analysis"]


def main() -> int:
    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for route in ROUTES:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = ctx.new_page()
            reqs: list[tuple[str, int]] = []
            fails: list[tuple[str, int]] = []

            def on_resp(r):
                try:
                    body = r.body()
                    n = len(body)
                except Exception:
                    n = 0
                reqs.append((r.url, n))
                if r.status >= 400:
                    fails.append((r.url, r.status))

            page.on("response", on_resp)
            try:
                page.goto(BASE + route, wait_until="load", timeout=25000)
                page.wait_for_timeout(2500)
                dcl = page.evaluate("performance.timing.domContentLoadedEventEnd - performance.timing.navigationStart")
                load = page.evaluate("performance.timing.loadEventEnd - performance.timing.navigationStart")
            except Exception as exc:  # noqa: BLE001
                report.append({"route": route, "error": str(exc)[:200]})
                ctx.close()
                continue

            total = sum(n for _, n in reqs)
            biggest = sorted(reqs, key=lambda x: -x[1])[:5]
            report.append({
                "route": route,
                "requests": len(reqs),
                "bytes": total,
                "kb": round(total / 1024, 1),
                "dcl_ms": dcl,
                "load_ms": load,
                "failed": fails,
                "biggest": [[u.replace(BASE, ""), round(n / 1024, 1)] for u, n in biggest],
            })
            ctx.close()
        browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=1))
    (OUT / "perf.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
