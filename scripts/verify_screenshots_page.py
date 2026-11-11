"""Browser acceptance for the new screenshot capture channel (isolated DB)."""
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
OUT = ROOT / 'test-results'
SAMPLES = ROOT / 'data' / 'screenshots' / 'samples'
if not (SAMPLES / '01-score.png').is_file():
    raise SystemExit('缺少 data/screenshots/samples 真实截图，跳过浏览器验收')

OUT.mkdir(exist_ok=True)
env = dict(os.environ, TRAINING_PORT='8768',
           TRAINING_DB=str(OUT / f'capture-browser-{uuid.uuid4().hex}.sqlite3'),
           PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8768'
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
        page = browser.new_page(viewport={'width': 1500, 'height': 1020}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/#screenshots')
        page.get_by_role('heading', name='截图采集').wait_for()
        assert page.locator('[data-slot-card]').count() == 7
        for key, filename in (
                ('score', '01-score.png'), ('kda', '02-kda.png'), ('farming', '03-farming.png'),
                ('survival', '04-survival.png'), ('data', '05-data.png'),
                ('output', '06-output.png'), ('team', '07-team.png')):
            page.locator(f'[data-slot-file="{key}"]').set_input_files(str(SAMPLES / filename))
            page.wait_for_function(
                'key => document.querySelector(`[data-slot-card=\"${key}\"] .tag`)?.textContent.includes("已采集")',
                arg=key, timeout=180000)
        page.wait_for_function('document.querySelectorAll(".capture-group").length === 3', timeout=120000)
        page.wait_for_function('document.querySelectorAll(".capture-image-row, .capture-group").length >= 3', timeout=60000)
        assert page.locator('.capture-group').count() == 3, page.locator('.capture-group').count()
        assert page.locator('.capture-player').count() == 30, page.locator('.capture-player').count()
        assert page.locator('.capture-analysis').count() == 3, page.locator('.capture-analysis').count()
        assert page.locator('.capture-team').count() == 6, page.locator('.capture-team').count()
        assert page.locator('.capture-compare-row').count() > 0
        assert page.locator('.capture-rank-row').count() > 0
        if not page.locator('.capture-player-details').first.evaluate('(element) => element.open'):
            page.locator('.capture-player-details summary').first.click()
        page.locator('[data-hero-edit]').first.select_option(label='武则天')
        page.wait_for_function('document.body.innerText.includes("英雄已修正为 武则天")', timeout=30000)
        assert '武则天' in page.locator('.capture-group').first.inner_text()
        texts = [page.locator('.capture-group').nth(i).inner_text() for i in range(3)]
        assert any('14 : 26' in text for text in texts), texts
        assert any('33 : 34' in text for text in texts), texts
        assert any('团队' in text for text in texts), texts
        assert page.locator('.capture-page').count() == 7, page.locator('.capture-page').count()
        with page.expect_download() as download:
            page.locator('[data-export-group]').first.click()
        export_path = OUT / 'capture-group.json'
        download.value.save_as(str(export_path))
        exported = json.loads(export_path.read_text(encoding='utf-8'))
        assert exported['schema'] == 'kpl-postgame-screenshot-v1'
        assert exported['pages'] and exported['players']
        page.screenshot(path=str(OUT / 'screenshots-page-desktop.png'), full_page=True)
        page.on('dialog', lambda dialog: dialog.accept())
        match_group = page.locator('.capture-group').filter(has_text='14 : 26')
        match_group.locator('[data-draft-group]').click()
        page.wait_for_url('**#edit/*', timeout=30000)
        page.get_by_role('button', name='保存草稿').wait_for(timeout=30000)
        assert page.locator('[data-player="left-0"][data-key="kills"]').input_value() == '2'
        assert page.locator('[data-player="left-0"][data-key="damage"]').input_value() == '59200'
        page.screenshot(path=str(OUT / 'capture-draft-editor.png'), full_page=True)
        assert not errors, errors
        browser.close()
        print(json.dumps({'screenshotsPage': 'passed', 'fixedSlots': 7, 'groups': 3, 'players': 30,
                          'pages': 7, 'draftEditor': 'passed', 'errors': errors}, ensure_ascii=False))
finally:
    process.terminate()
    process.wait(timeout=10)
