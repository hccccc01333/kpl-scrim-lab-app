"""UI uplift regression check: console errors, overflow, and control sizing.

Usage:
    python scripts/uplift_check.py --out .audit-shots/uplift-check.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ROUTES = [
    'overview', 'competitions', 'team-profile', 'opponents', 'ingest', 'matching',
    'match-notes', 'matches', 'biggame', 'cross', 'teams', 'playerarchive',
    'playercompare', 'metrics-observe', 'heroes', 'herocompare', 'teamheroes',
    'lanemetrics', 'comboperf', 'bp', 'coach', 'rules', 'combo-pool',
    'grade-rules', 'lineup-tags', 'snapshot-center', 'sources', 'docs', 'source-health',
]

MEASURE = """() => {
  const res = {small: [], overflow: 0, controls: 0, minH: 999, minFont: 999};
  const width = document.documentElement.clientWidth;
  res.overflow = document.documentElement.scrollWidth - width;
  document.querySelectorAll('#content button, #content .control, #content select, #content input:not([type=hidden])').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const c = getComputedStyle(el);
    const fs = parseFloat(c.fontSize);
    res.controls++;
    res.minH = Math.min(res.minH, Math.round(r.height));
    res.minFont = Math.min(res.minFont, fs);
    if (r.height < 40 || fs < 14) {
      res.small.push({
        text: (el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 24),
        h: Math.round(r.height), fs, cls: (typeof el.className === 'string' ? el.className : '').slice(0, 40)
      });
    }
  });
  res.small = res.small.slice(0, 8);
  return res;
}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.audit-shots/uplift-check.json')
    ap.add_argument('--routes', nargs='*', default=None)
    args = ap.parse_args()

    out = (ROOT / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    routes = args.routes or ROUTES
    report = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors: list[str] = []
        page.on('pageerror', lambda e: errors.append(str(e)[:200]))
        for route in routes:
            errors.clear()
            entry = {'route': route}
            try:
                page.goto(f'{args.base}/#{route}', wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(1600)
                entry.update(page.evaluate(MEASURE))
            except Exception as exc:  # noqa: BLE001
                entry['fatal'] = str(exc)[:200]
            entry['errors'] = list(errors)
            report.append(entry)
        browser.close()

    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for e in report:
        flag = '!!' if e.get('errors') or e.get('fatal') or e.get('overflow', 0) > 2 else '  '
        print(f"{flag} {e['route']:18} controls={e.get('controls', 0):3} "
              f"minH={e.get('minH', '-'):>3} minFont={e.get('minFont', '-')} "
              f"small={len(e.get('small', []))} overflow={e.get('overflow', '?')} err={len(e['errors'])}")
    print('report:', out)


if __name__ == '__main__':
    main()
