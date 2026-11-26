"""Capture workbench route screenshots for the UI uplift audit.

Usage:
    python scripts/uplift_shots.py --out .audit-shots/uplift-before
    python scripts/uplift_shots.py --out .audit-shots/uplift-after --routes overview matches teams
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTES = [
    'overview', 'ingest', 'capture', 'matches', 'featured', 'biggame',
    'teams', 'teamtraining', 'playerarchive', 'playercompare', 'metrics-observe',
    'heroes', 'herocompare', 'teamheroes', 'lanemetrics', 'comboperf',
    'bp', 'coach', 'cross', 'match-notes', 'reports', 'rules', 'combo-pool',
    'grade-rules', 'lineup-tags', 'matching', 'series-builder', 'competitions',
    'datasource', 'source-health', 'snapshot-center',
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.audit-shots/uplift')
    ap.add_argument('--routes', nargs='*', default=None)
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    ap.add_argument('--wait', type=int, default=1800)
    args = ap.parse_args()

    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    routes = args.routes or DEFAULT_ROUTES

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': args.width, 'height': args.height})
        for route in routes:
            try:
                page.goto(f'{args.base}/#{route}', wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(args.wait)
                page.screenshot(path=str(out / f'{route}.png'), full_page=False)
                print('shot', route)
            except Exception as exc:  # noqa: BLE001
                print('FAIL', route, str(exc)[:160])
        browser.close()
    print('done', out)


if __name__ == '__main__':
    main()
