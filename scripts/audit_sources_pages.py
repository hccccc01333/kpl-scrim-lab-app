"""验证三个素材页：渲染、字段、报错、挂载控件是否就位（不执行写操作）。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parents[1] / ".audit-shots" / "sources"
BASE = "http://127.0.0.1:8811"
PAGES = [("#shots", "shots"), ("#videos", "videos"), ("#replays", "replays")]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        for hash_, name in PAGES:
            page = ctx.new_page()
            errors: list[str] = []
            failed: list[tuple[str, int]] = []
            page.on("pageerror", lambda e: errors.append(str(e)[:180]))
            page.on("console", lambda m: errors.append("console:" + m.text[:140]) if m.type == "error" else None)
            page.on("response", lambda r: failed.append((r.url, r.status)) if r.status >= 400 else None)

            page.goto(f"{BASE}/v3/{hash_}", wait_until="load", timeout=30000)
            page.wait_for_timeout(3200)
            try:
                b = page.get_by_role("button", name="稍后再看")
                if b.count():
                    b.first.click(timeout=1500)
            except Exception:
                pass

            info = page.evaluate(
                """() => ({
                    h1: (document.querySelector('#content h1')?.textContent || '').trim(),
                    tabs: Array.from(document.querySelectorAll('.secondary-wrap a')).map(a => a.textContent.trim()),
                    cards: document.querySelectorAll('#content .shot-card').length,
                    players: document.querySelectorAll('#content .shot-player').length,
                    stats: document.querySelectorAll('#content .stats-band > div').length,
                    selects: document.querySelectorAll('#content select').length,
                    actions: Array.from(document.querySelectorAll('[data-source-action]')).map(b => b.textContent.trim()).slice(0, 6),
                })"""
            )
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print(f"\n=== {hash_} ===")
            print(f"  h1={info['h1']!r} 统计格={info['stats']} 卡片={info['cards']} 选手/条目={info['players']} 下拉={info['selects']}")
            print(f"  页签: {' / '.join(info['tabs'])}")
            print(f"  操作: {info['actions']}")
            if failed:
                print(f"  失败请求: {dict.fromkeys(failed)}")
            if errors:
                print(f"  JS 异常: {list(dict.fromkeys(errors))[:3]}")
            if not failed and not errors:
                print("  无失败请求、无 JS 异常")
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
