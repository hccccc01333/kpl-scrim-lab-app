"""Audit 'line rhythm': variable-width chips/badges that break visual columns.

Finds sibling rows where nominally identical small boxes have very different
widths, and rows where a following text node shifts with the box width.

Usage:
    python scripts/line_rhythm_audit.py --out .audit-shots/rhythm-audit.json
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
  const out = [];
  const ok = e => { const r=e.getBoundingClientRect(); return r.width>20 && r.height>14 && getComputedStyle(e).visibility!=='hidden'; };
  const key = e => {
    let c = typeof e.className==='string' ? e.className.trim().split(/\\s+/)[0] : '';
    return c.replace(/\\d/g,'#').slice(0,32);
  };
  for (const parent of document.querySelectorAll('#content *')) {
    const pc=getComputedStyle(parent);
    if (pc.display!=='flex' && pc.display!=='grid') continue;
    if (pc.flexDirection==='column') continue;
    const kids=[...parent.children].filter(ok).filter(k=>{
      const r=k.getBoundingClientRect();
      return r.width>=40 && r.width<=180 && r.height>=18 && r.height<=54;
    });
    if (kids.length<3) continue;
    const tops=kids.map(k=>Math.round(k.getBoundingClientRect().top));
    if (Math.max(...tops)-Math.min(...tops)>4) continue;
    const groups={};
    for (const k of kids) { const g=key(k); (groups[g] ||= []).push(k); }
    for (const [g, items] of Object.entries(groups)) {
      if (items.length<3) continue;
      const ws=items.map(k=>Math.round(k.getBoundingClientRect().width));
      const spread=Math.max(...ws)-Math.min(...ws);
      if (spread<8) continue;
      out.push({ parent:String(parent.className).slice(0,36), group:g,
        n:items.length, spread, widths:ws.slice(0,10),
        texts:items.slice(0,6).map(k=>(k.textContent||'').trim().slice(0,12)) });
    }
  }
  return out.sort((a,b)=>b.spread-a.spread).slice(0,12);
}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.audit-shots/rhythm-audit.json')
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
                page.wait_for_timeout(2500)
                res = page.evaluate(AUDIT)
                res = {'route': route, 'groups': res}
                report.append(res)
                print(f'{route:18} groups={len(res["groups"])} maxSpread={max([g["spread"] for g in res["groups"]], default=0)}')
            except Exception as exc:  # noqa: BLE001
                print(route, 'ERR', str(exc)[:80])
        b.close()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('report:', out)


if __name__ == '__main__':
    main()
