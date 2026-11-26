"""PPT-style layout audit: nested frames, row alignment, vertical text alignment.

Reports per route:
  - deepest chain of visible-bordered ancestors (nested boxes)
  - rows of >=2 sibling "boxes" whose top edges differ (ragged alignment)
  - cards whose direct children use wildly uneven gaps

Usage:
    python scripts/ppt_audit.py --out .audit-shots/ppt-audit.json
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

AUDIT = """() => {
  const out = { deep: [], ragged: [], gapMess: [] };
  const visible = e => {
    const r = e.getBoundingClientRect();
    return r.width > 24 && r.height > 16 && getComputedStyle(e).visibility !== 'hidden';
  };
  const interactive = e => e.matches('button, .control, input, select, textarea, a, [role=button], table, thead, tbody, tr, th, td');
  const bordered = e => {
    if (interactive(e)) return false;
    const c = getComputedStyle(e);
    if (c.borderStyle === 'none' || c.borderWidth === '0px') return false;
    const transparent = v => v === 'transparent' || v.endsWith(', 0)');
    if (transparent(c.borderTopColor) && transparent(c.borderLeftColor)) return false;
    return parseFloat(c.borderTopWidth) + parseFloat(c.borderLeftWidth) > 0;
  };
  // 1. nested frames
  for (const e of document.querySelectorAll('#content *')) {
    if (!visible(e) || !bordered(e)) continue;
    let depth = 1, p = e.parentElement;
    while (p && p.id !== 'content') {
      if (visible(p) && bordered(p) && !interactive(p)) depth++;
      p = p.parentElement;
    }
    if (depth >= 3) {
      out.deep.push({ cls: String(e.className).slice(0, 48), depth,
        chain: [e, ...(() => { const a=[]; let q=e.parentElement; while(q && q.id!=='content'){ if(visible(q)&&bordered(q)) a.push(q); q=q.parentElement; } return a; })()]
          .slice(0, 4).map(x => String(x.className).slice(0, 28)) });
    }
  }
  // 2. ragged rows of sibling boxes (same parent, similar size, tops differ)
  for (const parent of document.querySelectorAll('#content *')) {
    const pc = getComputedStyle(parent);
    if (pc.display !== 'flex' && pc.display !== 'grid') continue;
    if (pc.flexDirection === 'column' || pc.gridTemplateColumns.split(' ').length <= 1) continue;
    const kids = [...parent.children].filter(visible).filter(k => {
      const r = k.getBoundingClientRect();
      return r.width >= 40 && r.width <= 420 && r.height >= 24 && r.height <= 260;
    });
    if (kids.length < 3) continue;
    const tops = kids.map(k => Math.round(k.getBoundingClientRect().top));
    const spread = Math.max(...tops) - Math.min(...tops);
    if (spread >= 6) out.ragged.push({ parent: String(parent.className).slice(0, 44),
      n: kids.length, spread, kids: kids.slice(0, 4).map(k => String(k.className).slice(0, 28)) });
  }
  // 3. uneven gaps inside a card
  for (const e of document.querySelectorAll('#content .section, #content .card, #content .panel')) {
    const kids = [...e.children].filter(visible);
    if (kids.length < 2) continue;
    const gaps = [];
    for (let i = 1; i < kids.length; i++) {
      gaps.push(Math.round(kids[i].getBoundingClientRect().top - kids[i-1].getBoundingClientRect().bottom));
    }
    if (Math.max(...gaps) - Math.min(...gaps) >= 14) out.gapMess.push({
      cls: String(e.className).slice(0, 44), gaps: gaps.slice(0, 6) });
  }
  out.deep = out.deep.sort((a,b) => b.depth - a.depth).slice(0, 6);
  out.ragged = out.ragged.sort((a,b) => b.spread - a.spread).slice(0, 8);
  out.gapMess = out.gapMess.slice(0, 8);
  return out;
}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.audit-shots/ppt-audit.json')
    ap.add_argument('--routes', nargs='*', default=None)
    args = ap.parse_args()
    out = (ROOT / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    report = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={'width': 1440, 'height': 900})
        for route in args.routes or ROUTES:
            try:
                page.goto(f'{args.base}/#{route}', wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2600)
                res = page.evaluate(AUDIT)
                res['route'] = route
                report.append(res)
                print(f"{route:18} deep={len(res['deep'])} ragged={len(res['ragged'])} gaps={len(res['gapMess'])}")
            except Exception as exc:  # noqa: BLE001
                print(route, 'ERR', str(exc)[:80])
        b.close()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('report:', out)


if __name__ == '__main__':
    main()
