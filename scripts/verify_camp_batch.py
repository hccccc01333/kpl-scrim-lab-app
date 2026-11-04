"""Browser acceptance for the camp share-link batch import (isolated DB)."""
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
env = dict(os.environ, TRAINING_PORT='8772',
           TRAINING_DB=str(OUT / f'camp-batch-{uuid.uuid4().hex}.sqlite3'),
           PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8772'
try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/state', timeout=1)
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Test server did not start')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1020})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/studio#channels')
        page.wait_for_selector('#camp-batch-text', timeout=20000)
        assert page.locator('text=批量导入营地分享链接').count() == 1

        page.fill('#camp-batch-text',
                  'https://cu.qq.com/3tuABL90\n这个不是链接的中文行')
        page.click('#camp-batch-run')
        page.wait_for_selector('#camp-batch-result table', timeout=90000)
        row_text = page.locator('#camp-batch-result tbody tr').first.inner_text()
        assert '1793606215' in row_text, row_text
        assert '蓝方胜' in row_text, row_text

        page.click('#camp-batch-result [data-camp-create]')
        page.wait_for_selector('#camp-batch-result .tag:has-text("已建局")', timeout=30000)
        channels = page.request.get(base + '/api/channels').json()
        assert channels['channels'], 'channel was not created'
        channel_id = channels['channels'][0]['id']
        detail = page.request.get(base + '/api/channels/' + channel_id).json()
        official = detail.get('official') or {}
        assert official.get('id') == 'camp-1793606215', official
        assert not errors, errors
        print('camp batch import: OK · channel', channel_id[:8],
              '· official', official.get('id'))
        browser.close()
finally:
    process.terminate()
