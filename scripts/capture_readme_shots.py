#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture README screenshots from a running workbench.

    python scripts/capture_readme_shots.py --base http://127.0.0.1:8766 \
        --out docs/images

Every page is captured at 1440x900. The shots contain only the synthetic
demo dataset, never real match data.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = [
    ('01-overview', '#overview', 4500),
    ('02-capture', '#capture', 4000),
    ('03-matches', '#matches', 4000),
    ('04-players', '#players', 4500),
    ('05-team', '#team', 4500),
    ('06-heroes', '#heroes', 4500),
    ('07-topics', '#topics', 5000),
    ('08-depth', '#depth', 5500),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--out', default='docs/images')
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900},
                                device_scale_factor=2)
        for name, route, wait in SHOTS:
            page.goto(args.base + '/studio' + route, wait_until='load')
            page.wait_for_timeout(wait)
            target = out / f'{name}.png'
            page.screenshot(path=str(target))
            print('shot', target.name)
        browser.close()


if __name__ == '__main__':
    main()
