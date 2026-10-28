"""Exercise a real browser against an isolated local database (no user data)."""
import json
import io
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
env = dict(os.environ, TRAINING_PORT='8767', TRAINING_DB=str(OUT / f'browser-{uuid.uuid4().hex}.sqlite3'), PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8767'
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(base+'/api/state', timeout=1)
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
        page.goto(base)
        page.get_by_role('heading', name='把每一场训练，变成下一场的进步').wait_for()
        page.screenshot(path=str(OUT/'overview-desktop.png'), full_page=True)
        page.locator('nav a[data-page="roster"]').click()
        for name in ('青山', '归舟', '长风', '听雨', '明川'):
            page.locator('#new-player').fill(name)
            page.locator('#add-player').click()
            page.wait_for_function('document.querySelector("#new-player")?.value === ""')
        page.locator('nav a[data-page="matches"]').click()
        page.get_by_role('link', name='录入训练赛').click()
        page.locator('#image-file').set_input_files('D:/caches/temp/codex-clipboard-dfbc8fc2-dcd3-4543-b74f-81a9052dfd4d.png')
        page.get_by_role('button', name='填入空白字段').wait_for(timeout=60000)
        page.get_by_role('button', name='填入空白字段').click()
        assert page.locator('[data-player="right-0"][data-key="damage"]').input_value() == '103.9k'
        page.get_by_role('button', name='图标核对', exact=True).click()
        page.locator('#icon-row').select_option('right-0')
        page.locator('#icon-query').fill('小乔')
        page.locator('[data-entry="hero-106"]').click()
        page.screenshot(path=str(OUT/'icon-review-desktop.png'), full_page=True)
        page.locator('#apply-icons').click()
        assert page.locator('[data-player="right-0"][data-key="hero"]').input_value() == '小乔'
        page.locator('[data-meta="date"]').fill('2026-10-28')
        page.locator('[data-meta="opponent"]').fill('浏览器验收对手')
        page.locator('[data-meta="side"]').select_option('right')
        page.locator('[data-meta="winner"]').select_option('right')
        page.locator('[data-meta="session"]').fill('验收训练 · 第 1 局')
        s = page.request.get(base+'/api/state').json()
        for i, hero in enumerate(('小乔','马超','后羿','弈星','大乔')):
            if i:
                page.locator(f'[data-player="right-{i}"][data-key="hero"]').fill(hero)
            page.locator(f'[data-player="right-{i}"][data-key="playerId"]').select_option(s['settings']['roster'][i]['id'])
        page.locator('#reviewed').check()
        page.locator('#confirm-match').click()
        page.wait_for_function('document.querySelector("#save-hint")?.textContent.includes("已保存")')
        s = page.request.get(base+'/api/state').json()
        assert s['summary']['games'] == 1 and s['summary']['wins'] == 1, s['summary']
        assert s['summary']['heroes'][0]['damageSamples'] == 1
        assert len(s['matches'][0]['iconReviews']) == 1
        page.screenshot(path=str(OUT/'editor-desktop.png'), full_page=True)
        page.locator('nav a[data-page="analysis"]').click()
        page.locator('#analysis-table tbody').wait_for()
        assert page.locator('#analysis-table tbody tr').count() == 5
        page.locator('#filter-player').select_option(s['settings']['roster'][0]['id'])
        page.wait_for_function('document.querySelectorAll("#analysis-table tbody tr").length===1')
        page.get_by_role('button', name='逐局查看').click()
        page.locator('#drilldown a').wait_for()
        page.screenshot(path=str(OUT/'analysis-desktop.png'), full_page=True)
        # Confirm the backup contains original image bytes and survives a merge restore.
        backup = page.request.get(base+'/api/backup').json()
        assert backup['images'][0]['data']
        restored = page.request.post(base+'/api/restore', data=backup).json()
        assert restored == {'added':0, 'skipped':1}, restored
        # Page reload must rebuild statistics from SQLite, not in-memory fixtures.
        page.reload()
        page.locator('#analysis-table tbody').wait_for()
        assert page.request.get(base+'/api/state').json()['summary']['games'] == 1
        # Reopen a saved game: cached results and review actions must return without rerunning OCR.
        page.goto(base+'/#edit/'+s['matches'][0]['id'])
        page.get_by_role('button', name='图标核对', exact=True).wait_for()
        page.locator('.page-correction summary').click()
        page.locator('[data-page-score="left"]').fill('17')
        page.locator('#save-draft').click()
        page.wait_for_function('document.querySelector("#save-hint")?.textContent.includes("已保存")')
        page.locator('#reviewed').check()
        page.locator('#confirm-match').click()
        page.wait_for_function('document.querySelector("#save-hint")?.textContent.includes("已保存")')
        # A score-page fixture independently exercises the six equipment slots.
        score_upload = page.request.post(base+'/api/images?name=score-page.png', data=Path('D:/caches/temp/codex-clipboard-63fc833f-fa9d-45aa-b350-bc7e56033fec.png').read_bytes(), headers={'Content-Type':'image/png'}).json()['id']
        score_ocr = page.request.post(base+f'/api/images/{score_upload}/ocr', timeout=60000).json()
        assert len(score_ocr['visuals']) == 70
        page.get_by_role('link', name='返回比赛档案').click()
        page.get_by_role('link', name='录入训练赛').click()
        page.locator('#image-file').set_input_files('D:/caches/temp/codex-clipboard-63fc833f-fa9d-45aa-b350-bc7e56033fec.png')
        page.get_by_role('button', name='图标核对', exact=True).wait_for(timeout=60000)
        page.get_by_role('button', name='图标核对', exact=True).click()
        page.locator('[data-kind="equipment"]').click()
        assert page.locator('.icon-region').count() == 6
        page.locator('#icon-query').fill('碎星锤')
        page.locator('.icon-region').first.locator('[data-entry]').first.click()
        page.screenshot(path=str(OUT/'equipment-review-desktop.png'), full_page=True)
        page.locator('#apply-icons').click()
        assert page.locator('[data-player="left-0"][data-key="equipment"]').input_value()
        page.locator('#save-draft').click()
        page.wait_for_function('document.querySelector("#save-hint")?.textContent.includes("已保存")')
        # A recompressed image is only used to test retrieval, never saved as a second game.
        stream = io.BytesIO()
        Image.open('D:/caches/temp/codex-clipboard-dfbc8fc2-dcd3-4543-b74f-81a9052dfd4d.png').convert('RGB').save(stream, format='JPEG', quality=94)
        new_image = page.request.post(base+'/api/images?name=recognition-check.jpg', data=stream.getvalue(), headers={'Content-Type':'image/jpeg'}).json()['id']
        recognition = page.request.post(base+f'/api/images/{new_image}/ocr', timeout=60000).json()
        region = next(r for r in recognition['visuals'] if r['side']=='right' and r['slot']==0)
        assert region['method'] == 'printed-name', region
        assert all(c['source'] == 'name-ocr' for c in region['candidates']), region
        assert not any(c['name'] == '妲己' for c in region['candidates']), region
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button', name='图标核对', exact=True).click()
        page.screenshot(path=str(OUT/'icon-review-mobile.png'), full_page=True)
        assert page.locator('.icon-review-dialog').evaluate('(node)=>node.getBoundingClientRect().width <= window.innerWidth')
        page.locator('.icon-review-dialog [data-close]').click()
        page.locator('nav a[data-page="overview"]').click()
        page.get_by_role('heading', name='把每一场训练，变成下一场的进步').wait_for()
        page.screenshot(path=str(OUT/'overview-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflows mobile viewport'
        assert not errors, errors
        browser.close()
        print(json.dumps({'browser':'passed', 'confirmedGames':1, 'consoleErrors':errors, 'screenshots':str(OUT)}, ensure_ascii=False))
finally:
    process.terminate()
    process.wait(timeout=10)
