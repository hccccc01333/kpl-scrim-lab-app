"""Smoke-check the replay player page in a real browser.

Starts from an already running workbench (``python server.py``), opens
``/static/player.html?replay=<id>``, waits for the decoded state document to
render, checks the structural bits, scrubs the timeline and writes a screenshot.

    python scripts/verify_replay_player.py --base http://127.0.0.1:8766 \
        --replay <abc-sha256> [--shot test-results/replay-player.png]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8766")
    parser.add_argument("--replay", required=True)
    parser.add_argument("--shot", default="test-results/replay-player.png")
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    url = f"{args.base}/static/player.html?replay={args.replay}"
    errors: list[str] = []
    result: dict = {"url": url, "ok": False}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda message: message.type == "error" and errors.append(message.text))
        page.on("pageerror", lambda error: errors.append(str(error)))
        started = time.time()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(".rp-root, .rp-error", timeout=args.timeout_ms)
        result["elapsedSec"] = round(time.time() - started, 2)

        result["errorBox"] = page.locator(".rp-error").count()
        if result["errorBox"]:
            result["errorText"] = page.locator(".rp-error").first.inner_text()
        else:
            result["chips"] = page.locator(".rp-chip").count()
            result["cards"] = page.locator(".rp-card").count()
            result["charts"] = page.locator(".rp-chart canvas").count()
            result["eventsRendered"] = page.locator("[data-events] li").count()
            result["gaps"] = page.locator(".rp-gaps li").count()
            clock_before = page.locator(".rp-clock").inner_text()
            page.locator(".rp-range").fill("300")
            page.locator(".rp-range").dispatch_event("input")
            page.wait_for_timeout(400)
            clock_after = page.locator(".rp-clock").inner_text()
            result["clockBefore"] = clock_before
            result["clockAfter"] = clock_after
            page.locator('[data-act="toggle"]').click()
            page.wait_for_timeout(1200)
            result["playingClock"] = page.locator(".rp-clock").inner_text()
            first_card = page.locator(".rp-card").first
            result["firstCardLevel"] = first_card.locator('[data-f="lv"]').inner_text()
            result["firstCardSpend"] = first_card.locator('[data-f="gs"]').inner_text()

        shot = ROOT / args.shot
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=True)
        result["screenshot"] = str(shot)
        browser.close()

    result["consoleErrors"] = errors[:10]
    result["ok"] = (not result.get("errorBox")
                    and result.get("chips") == 10
                    and result.get("cards") == 10
                    and not errors)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
