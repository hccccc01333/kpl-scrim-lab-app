"""验证 V2 界面在 V1 服务下的 /v3 子路径里能正常渲染。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parents[1] / ".audit-shots" / "merged"
BASE = "http://127.0.0.1:8811"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()

        failed: list[tuple[str, int]] = []
        errors: list[str] = []
        page.on("response", lambda r: failed.append((r.url, r.status)) if r.status >= 400 else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))

        for route, name in [("/v3/", "v3-overview"), ("/v3/#matches", "v3-matches"),
                            ("/v3/#players", "v3-players")]:
            page.goto(BASE + route, wait_until="load", timeout=30000)
            page.wait_for_timeout(3000)
            try:
                b = page.get_by_role("button", name="稍后再看")
                if b.count():
                    b.first.click(timeout=1500)
                    page.wait_for_timeout(400)
            except Exception:
                pass
            page.screenshot(path=str(OUT / f"{name}.png"))
            info = page.evaluate(
                """() => ({
                    title: document.title,
                    h1: (document.querySelector('#app h1')?.textContent || '').trim().slice(0, 30),
                    len: (document.querySelector('#app')?.innerHTML || '').length,
                    nav: Array.from(document.querySelectorAll('.nav a, header nav a')).length,
                })"""
            )
            print(f"{route:<16} title={info['title']!r:<22} h1={info['h1']!r:<14} app={info['len']:>6} nav={info['nav']}")

        print(f"\n失败请求 {len(failed)}：")
        for u, s in dict.fromkeys(failed):
            print(f"  {s}  {u.replace(BASE, '')}")
        print(f"JS 异常 {len(errors)}：")
        for e in dict.fromkeys(errors):
            print("  ", e)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
