"""工作台全页面截图（真实数据），输出到 test-results/workbench-shots/。"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results' / 'workbench-shots'
OUT.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, TRAINING_PORT='8781', PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8781'
try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/state', timeout=1)
            break
        except OSError:
            time.sleep(.1)
    channel_id = ''
    try:
        with urllib.request.urlopen(base + '/api/channels', timeout=3) as response:
            channels = json.loads(response.read().decode('utf-8')).get('channels') or []
            channel_id = channels[0].get('id', '') if channels else ''
    except OSError:
        pass
    shots = [
        ('01-overview', base + '/studio', 3500),
        ('02-channels-camp-sync', base + '/studio#channels', 7000),
        ('03-capture', base + '/studio#capture', 4000),
        ('04-recordings', base + '/studio#recordings', 4000),
        ('05-camp-insights', (ROOT / 'data/camp_reports/camp-insights-540599032.html').as_uri(), 2500),
    ]
    if channel_id:
        shots.insert(3, ('03-channel-detail', base + f'/studio#channel/{channel_id}', 5000))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 980})
        for name, url, wait in shots:
            page.goto(url, wait_until='load')
            page.wait_for_timeout(wait)
            page.screenshot(path=str(OUT / f'{name}.png'), full_page=False)
            print('shot', name)
        browser.close()
    print('done', OUT)
finally:
    process.terminate()
