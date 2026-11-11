"""一次性审计截图：抓主路径几个页面，供视觉评审。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".audit-shots"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:8766"

PAGES = [
    ("studio-home", "/studio#home"),
    ("studio-capture", "/studio#capture"),
    ("studio-matches", "/studio#matches"),
    ("studio-players", "/studio#players"),
    ("studio-heroes", "/studio#heroes"),
    ("studio-compare", "/studio#compare"),
    ("studio-depth", "/studio#analysis"),
    ("workbench", "/"),
]


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        for name, route in PAGES:
            try:
                page.goto(BASE + route, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1200)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
                print(f"OK   {name}  <- {route}")
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {name}  <- {route}  {exc}")

        browser.close()

    if errors:
        print("\n--- console errors ---")
        for e in dict.fromkeys(errors):
            print(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
