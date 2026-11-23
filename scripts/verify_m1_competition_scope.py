# M1 验收脚本：隔离库（KPL_DATA_DIR 指向临时副本）+ Playwright 走查（用后可留档）
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
TMP = Path(r'D:\tmp\kpl-m1')
DATA = TMP / 'data'
OUT = ROOT / 'test-results' / 'm1-acceptance'
OUT.mkdir(parents=True, exist_ok=True)

if not (DATA / 'training.sqlite3').exists():
    DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / 'data' / 'training.sqlite3', DATA / 'training.sqlite3')
    shutil.copytree(ROOT / 'data' / 'matches', DATA / 'matches', dirs_exist_ok=True)
    for name in ('imports', 'official_replays', 'camp_details', 'builds', 'recordings'):
        (DATA / name).mkdir(exist_ok=True)

env = dict(os.environ if (os := __import__('os')) else {}, KPL_DATA_DIR=str(DATA),
           TRAINING_PORT='8781', PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8781'
report = {}
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
    keys = [r['match_key'] for r in conn.execute(
        'SELECT match_key FROM match_records ORDER BY date LIMIT 6')]
    conn.close()
    comp_a, comp_b = comps[0]['id'], comps[1]['id']

    def post(path, payload):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        return json.load(urllib.request.urlopen(req))

    # 归属：前 3 局 → 赛事A，后 3 局 → 赛事B（方案 §10.1 的「赛事 2 只挂少量」）
    post(f'/api/studio/workspace/competitions/{comp_a}/matches', {'matchKeys': keys[:3]})
    post(f'/api/studio/workspace/competitions/{comp_b}/matches', {'matchKeys': keys[3:6]})
    existing = json.load(urllib.request.urlopen(base + '/api/series')).get('series') or []
    def _series_for(cid):
        found = [s for s in existing if s.get('competitionId') == cid]
        if found:
            return found[0]
        games = keys[:3] if cid == comp_a else keys[3:6]
        return post('/api/series', {'bestOf': 3, 'games': games})['series']
    series_a = _series_for(comp_a)
    series_b = _series_for(comp_b)
    report['seriesA'] = {'id': series_a['id'], 'competitionId': series_a['competitionId']}
    report['seriesB'] = {'id': series_b['id'], 'competitionId': series_b['competitionId']}

    ob = json.load(urllib.request.urlopen(base + f'/api/studio/workspace/onboarding?competition={comp_a}'))
    report['onboarding'] = {k: ob[k] for k in ('matchCount', 'confirmedSeries', 'confirmedGames', 'corpusThreshold')}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 950})
        hits = []
        page.on('request', lambda r: hits.append(r.url) if 'competition=' in r.url else None)
        page.goto(base + '/#overview', wait_until='load')
        page.wait_for_timeout(4000)
        slot = page.locator('#onboarding-slot')
        report['card'] = {'visible': slot.is_visible(), 'text': slot.inner_text()[:180]}
        page.locator('#onboarding-slot').screenshot(path=str(OUT / '01-card.png'))
        # 选赛事 A
        page.goto(base + '/#competitions', wait_until='load')
        page.wait_for_timeout(2500)
        page.evaluate(f"localStorage.setItem('training-current-competition', '{comp_a}')")
        page.goto(base + '/#overview', wait_until='load')
        page.wait_for_timeout(2500)
        report['topbar'] = page.locator('[data-competition-context]').inner_text()
        # 大场分析：列表只应出现赛事 A 的系列
        page.goto(base + '/#biggame', wait_until='load')
        page.wait_for_timeout(3500)
        body = page.locator('#content').inner_text()
        report['biggame'] = {
            'seriesAVisible': series_a['id'] in body or 'BO3' in body,
            'urlsScoped': sum('competition=' in u for u in hits),
        }
        page.screenshot(path=str(OUT / '02-biggame-comp-a.png'))
        # 切赛事 B：列表换成 B 的系列
        page.goto(base + '/#competitions', wait_until='load')
        page.wait_for_timeout(2000)
        page.evaluate(f"localStorage.setItem('training-current-competition', '{comp_b}')")
        page.goto(base + '/#overview', wait_until='load')
        page.wait_for_timeout(2500)
        page.goto(base + '/#biggame', wait_until='load')
        page.wait_for_timeout(3500)
        report['biggameB'] = {'urlsScoped': sum('competition=' in u for u in hits)}
        page.screenshot(path=str(OUT / '03-biggame-comp-b.png'))
        page.goto(base + '/#cross', wait_until='load')
        page.wait_for_timeout(4000)
        report['cross'] = {'urlsScoped': sum('competition=' in u for u in hits)}
        browser.close()
    report['PASS'] = (report['seriesA']['competitionId'] == comp_a
                      and report['seriesB']['competitionId'] == comp_b
                      and report['card']['visible'] and report['topbar'] != '切换赛事')
finally:
    process.terminate()

print(json.dumps(report, ensure_ascii=False, indent=1))
print('shots:', OUT)
