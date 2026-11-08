"""全站页面审计：逐路由截图 + 控制台错误 + 横向溢出 + 空内容。

用法：
    python scripts/audit_pages.py --base http://127.0.0.1:8766 --out .screenshots/audit-v1
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

ROUTES = [
    ('setup', '#setup'), ('home', '#overview'), ('capture', '#capture'),
    ('profile', '#profile'), ('identity', '#identity'), ('matches', '#matches'),
    ('recordings', '#recordings'), ('teams', '#teams'), ('opponents', '#opponents'),
    ('pending', '#pending'), ('effect', '#effect'), ('plan', '#plan'),
    ('ref-picks', '#ref/picks.html'), ('ref-teams', '#ref/teams.html'),
    ('h2h', '#h2h'), ('opprofile', '#opprofile'), ('ref-players', '#ref/players.html'),
    ('ref-compare-player', '#ref/compare-player.html'),
    ('ref-heroperf', '#ref/hero-performance.html'), ('ref-heroes', '#ref/heroes.html'),
    ('ref-combos', '#ref/combos.html'), ('coach', '#coach'),
    ('ref-teambp', '#ref/team-bp.html'), ('ref-bp', '#ref/bp.html'),
    ('ref-bpstudio', '#ref/bp-studio.html'), ('ref-compare', '#ref/compare.html'),
    ('ref-compare-team', '#ref/compare-team.html'),
    ('ref-compare-lane', '#ref/compare-lane.html'), ('versions', '#versions'),
    ('econ', '#econ'), ('space', '#space'), ('ref-series', '#ref/series.html'),
    ('ref-query', '#ref/query.html'), ('ref-find', '#ref/find.html'),
    ('ref-honors', '#ref/honors.html'),
]

OVERFLOW = """() => {
  const width = document.documentElement.clientWidth;
  const scroll = document.documentElement.scrollWidth;
  const wide = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > width + 2 && r.height > 0) {
      wide.push((el.className && typeof el.className === 'string' ? el.className : el.tagName).slice(0, 40));
    }
  });
  return {width, scroll, overflow: scroll - width, wide: [...new Set(wide)].slice(0, 5)};
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.screenshots/audit-v1')
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    args = ap.parse_args()

    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': args.width, 'height': args.height})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)[:160]))

        for name, route in ROUTES:
            errors.clear()
            entry = {'name': name, 'route': route}
            try:
                page.goto(args.base + '/' + route, wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(3200)
                # 读 iframe 内的正文（参考站页面）
                frame_text = page.evaluate("""() => {
                  const f = document.querySelector('.refsite-frame');
                  if (!f) return null;
                  try { return f.contentDocument ? f.contentDocument.body.innerText.slice(0, 200) : null; }
                  catch (e) { return 'cross-origin'; }
                }""")
                body = page.evaluate("() => (document.querySelector('#content') || document.body).innerText")
                entry['chars'] = len(body or '')
                entry['preview'] = re.sub(r'\s+', ' ', (body or ''))[:120]
                entry['overflow'] = page.evaluate(OVERFLOW)
                entry['errors'] = list(errors)
                entry['frame'] = (frame_text or '')[:120]
                page.screenshot(path=str(out / f'{name}.png'), full_page=True)
            except Exception as exc:  # noqa: BLE001
                entry['fatal'] = str(exc)[:200]
            report.append(entry)

        browser.close()

    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for entry in report:
        flag = '!!' if entry.get('fatal') or entry.get('errors') or entry.get('overflow', {}).get('overflow', 0) > 2 else '  '
        print(f"{flag} {entry['name']:22} chars={entry.get('chars', 0):6} "
              f"overflow={entry.get('overflow', {}).get('overflow', '?')} err={len(entry.get('errors', []))}")


if __name__ == '__main__':
    main()
