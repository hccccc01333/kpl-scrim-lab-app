"""Browser acceptance for one-match collection channels (isolated DB)."""
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
    raise SystemExit('缺少示例截图，跳过通道浏览器验收')
OUT.mkdir(exist_ok=True)
env = dict(os.environ, TRAINING_PORT='8771',
           TRAINING_DB=str(OUT / f'channel-browser-{uuid.uuid4().hex}.sqlite3'),
           PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8771'
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
        # Seed demo screenshots and upload one replay through the real APIs.
        demo = page.request.post(base + '/api/postgame/demo', timeout=240000).json()
        assert len(demo['images']) == 7
        replay_bytes = Path(ROOT / 'data/replays/samples/20261028_135516.abc').read_bytes()
        abc = page.request.post(base + '/api/replays/files?name=sample.abc', data=replay_bytes).json()
        page.request.post(base + '/api/replays/import', data={'abcFileId': abc['id']})
        table = OUT / 'channel-table.csv'
        table.write_text((ROOT / 'web/capture-guide/match-example.csv').read_text(encoding='utf-8-sig')
                         .replace('EXAMPLE-请替换', 'browser-match').replace('2026-11-04', '2026-06-17'),
                         encoding='utf-8')
        report = ROOT / 'data/replays/video_ocr/2a7206b09ea8cc35.json'
        page.goto(base + '/#channels')
        page.get_by_role('heading', name='采集通道').wait_for()
        page.locator('#channel-date').fill('2026-06-17')
        page.locator('#channel-opponent').fill('通道验收对手')
        page.locator('#channel-session').fill('通道验收 · 第 1 局')
        page.locator('#channel-create').click()
        page.wait_for_url('**#channel/*', timeout=30000)
        page.get_by_role('heading', name='2026-06-17 · 通道验收 · 第 1 局 · vs 通道验收对手').wait_for()
        # Four source ports.
        page.locator('#channel-table').set_input_files(str(table))
        page.wait_for_function('document.body.innerText.includes("表格已解析")', timeout=30000)
        page.wait_for_function('document.body.innerText.includes("粒度 match_player")', timeout=30000)
        page.locator('#channel-video').set_input_files(str(report))
        page.wait_for_function('document.body.innerText.includes("录像报告已解析")', timeout=30000)
        page.wait_for_function('document.body.innerText.includes("1/11 份")', timeout=30000)
        # Select the 14:26 screenshot group (sorted after the dated 01 group).
        options = page.evaluate('Array.from(document.querySelectorAll("#channel-shot-group option")).map(o => ({value:o.value,text:o.textContent}))')
        target = next(item for item in options if '5 页' in item['text'])
        page.locator('#channel-shot-group').select_option(value=target['value'])
        page.locator('#attach-shot').click()
        page.wait_for_function('document.body.innerText.includes("截图组已关联")', timeout=30000)
        page.locator('#channel-replay').select_option(index=1)
        page.locator('#attach-replay').click()
        page.wait_for_function('document.body.innerText.includes("回放已关联")', timeout=30000)
        page.wait_for_function('document.querySelectorAll(".channel-draft-table tbody tr").length === 10', timeout=30000)
        page.locator('[data-draft-side="left"][data-draft-slot="0"][data-draft-field="rating"]').fill('9.9')
        page.locator('#save-draft-edits').click()
        page.wait_for_function('document.body.innerText.includes("草稿修订已保存")', timeout=30000)
        page.wait_for_function('document.body.innerText.includes("待审核")', timeout=30000)
        page.locator('#channel-reviewer').fill('教练甲')
        page.locator('#channel-review').click()
        page.wait_for_function('document.body.innerText.includes("审核完成")', timeout=30000)
        page.wait_for_function('!document.querySelector("#channel-save").disabled', timeout=30000)
        page.locator('#channel-save').click()
        page.wait_for_function('document.body.innerText.includes("已保存")', timeout=30000)
        assert page.locator('.channel-log').count() >= 5
        page.screenshot(path=str(OUT / 'channel-page-desktop.png'), full_page=True)
        assert not errors, errors
        browser.close()
        print(json.dumps({'channelsPage': 'passed', 'sourcePorts': 4, 'draftPlayers': 10,
                          'review': 'passed', 'saved': 'passed', 'errors': errors}, ensure_ascii=False))
finally:
    process.terminate()
    process.wait(timeout=10)
