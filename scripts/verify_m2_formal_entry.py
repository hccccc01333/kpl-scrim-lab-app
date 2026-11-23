# M2/M3 UI 验收：正赛录入（阵容级）+ 存量归属 + boBp 跨赛事开关（用后可留档）
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
DATA = Path(r'D:\tmp\kpl-m1\data')
OUT = ROOT / 'test-results' / 'm2-acceptance'
OUT.mkdir(parents=True, exist_ok=True)

env = dict(os.environ, KPL_DATA_DIR=str(DATA), TRAINING_PORT='8782', PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8782'
report = {}


def post(path, payload):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    return json.load(urllib.request.urlopen(req))


try:
    for _ in range(150):
        try:
            urllib.request.urlopen(base + '/api/state', timeout=1)
            break
        except OSError:
            time.sleep(0.2)

    import sqlite3
    conn = sqlite3.connect(DATA / 'training.sqlite3')
    conn.row_factory = sqlite3.Row
    comps = [dict(r) for r in conn.execute(
        'SELECT id,name FROM competitions ORDER BY date LIMIT 2')]
    conn.close()
    comp_a, comp_b = comps[0]['id'], comps[1]['id']

    # 1) 正赛录入（阵容级）：用不同的对手名避免撞上历史去重
    stamp = str(int(time.time()))[-6:]
    saved = post('/api/studio/workspace/formal-matches', {
        'date': '2026-12-05', 'opponent': f'验收对手{stamp}', 'score': '2:3',
        'winner': 'red', 'competitionId': comp_a,
        'lineup': ['我方,对抗路,张飞', '对方,中路,貂蝉'],
    })
    report['formalSaved'] = {'dedup': saved['dedup'], 'depth': saved['depth'],
                             'competitionId': saved['competitionId']}
    conn = sqlite3.connect(DATA / 'training.sqlite3')
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT match_type, notes FROM match_records WHERE match_key=?',
                       (saved['matchKey'],)).fetchone()
    conn.close()
    report['formalRow'] = {'matchType': row['match_type'],
                           'depth': json.loads(row['notes'] or '{}').get('formalEntry', {}).get('depth')}

    # 2) 选分析语料里的对局建两个赛事的系列（boBp 需要向量）
    analysis_keys = [m.get('key') for m in json.load(urllib.request.urlopen(
        base + '/api/analysis/matches')).get('matches') or []][:6]
    post(f'/api/studio/workspace/competitions/{comp_a}/matches', {'matchKeys': analysis_keys[:3]})
    post(f'/api/studio/workspace/competitions/{comp_b}/matches', {'matchKeys': analysis_keys[3:6]})
    series_a = post('/api/series', {'bestOf': 3, 'games': analysis_keys[:3]})['series']

    # 3) boBp API：默认同赛事口径
    body_ins = json.load(urllib.request.urlopen(
        base + f"/api/series/{series_a['id']}/analysis?competition={comp_a}")).get('insight', {})
    bb = body_ins.get('boBp') or {}
    report['boBpApi'] = {'available': bb.get('available'),
                         'currentGames': len((bb.get('current') or {}).get('games') or []),
                         'history': len(bb.get('history') or [])}

    # 4) UI：boBp 开关 + 赛事 chip
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 950})
        scoped = []
        page.on('request', lambda r: scoped.append(r.url) if 'competition=' in r.url else None)
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.goto(base + '/#competitions', wait_until='load')
        page.wait_for_timeout(3000)
        report['opsPanel'] = page.locator('[data-comp-ops-body]').count()
        page.goto(base + '/#competitions', wait_until='load')
        page.wait_for_timeout(1500)
        page.evaluate(f"localStorage.setItem('training-current-competition', '{comp_a}')")
        page.goto(base + f"/#biggame/{series_a['id']}", wait_until='load')
        page.wait_for_timeout(3500)
        page.click('[data-bgx-module="bp"]')
        page.wait_for_timeout(1500)
        toggle = page.locator('[data-bgx-boother]')
        report['boToggle'] = toggle.count()
        if toggle.count():
            toggle.click()
            page.wait_for_timeout(1800)
            report['boToggleOn'] = toggle.get_attribute('aria-pressed')
        report['chip'] = page.locator('.bgx-chip').count()
        report['scopedRequests'] = sum('competition=' in u for u in scoped)
        report['pageErrors'] = errs[:3]
        if page.locator('#bgx-bp-habit').count():
            page.locator('#bgx-bp-habit').screenshot(path=str(OUT / '03-boh-toggle.png'))
        browser.close()
    report['PASS'] = (report['formalSaved']['depth'] == 'lineup'
                      and report['boBpApi']['available'] is True
                      and report.get('boToggleOn') == 'true')
finally:
    process.terminate()

print(json.dumps(report, ensure_ascii=False, indent=1))
print('shots:', OUT)
