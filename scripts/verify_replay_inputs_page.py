"""Browser check for the decoded hero input timeline in the replay lab."""
import os
import struct
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
sys.path.insert(0, str(ROOT / 'tests'))
from replay_fixtures import inputs_5v5_fixture

PORT = 8769
BASE = f'http://127.0.0.1:{PORT}'
env = dict(os.environ, TRAINING_PORT=str(PORT), TRAINING_DB=str(OUT / f'replay-inputs-browser-{uuid.uuid4().hex}.sqlite3'),
           PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def packed_move(unit, seq, sign, mag):
    return struct.pack('>H', unit << 11 | seq << 9 | sign << 8 | mag)


def commands():
    rows = []
    for frame in range(10):
        unit, sign, mag = (8, 0, 60 + frame * 3) if frame % 2 == 0 else (9, 1, 40 + frame)
        rows.append(bytes([1, 0x12]) + packed_move(unit, frame % 4, sign, mag))
    rows.append(bytes([1, 0x13, 0x40]))                                    # attack by unit 8
    rows.append(bytes([1, 0x02, 0x03, 0xE9, 0x85, 0x04, 0x57, 0, 0, 0, 8, 0]))  # BUYEQUIP entity 1001
    return tuple(rows)


try:
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + '/api/state', timeout=1)
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Test server did not start')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1020}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        data = inputs_5v5_fixture(commands())
        uploaded = page.request.post(BASE + '/api/replays/files?name=inputs-browser.abc', data=data).json()
        imported = page.request.post(BASE + '/api/replays/import', data={'abcFileId': uploaded['id']}).json()
        assert imported.get('changed'), imported
        replay_id = imported['report']['id']

        page.goto(BASE + '/#replays')
        page.get_by_role('heading', name='回放文件实验室').wait_for()
        page.locator('[data-replay-detail]').first.click()
        page.get_by_role('heading', name='英雄输入时间轴').wait_for()
        page.wait_for_selector('#input-summary table tbody tr')
        assert page.locator('#input-summary table tbody tr').count() == 10
        text = page.locator('#input-summary').inner_text()
        for expected in ('蓝方', '红方', '移动', '未解帧'):
            assert expected in text, (expected, text)
        page.wait_for_selector('#input-chart svg path')
        chart_text = page.locator('#input-chart').inner_text()
        assert '帧' in chart_text and '方向角' in chart_text, chart_text
        assert '15 帧/秒' in chart_text, chart_text
        summary = page.request.get(BASE + f'/api/replays/{replay_id}/inputs').json()
        assert summary['status'] == 'decoded', summary['status']
        assert summary['fullyParsedFrames'] == 12
        assert summary['timeBase']['framesPerSecond'] == 15
        assert summary['timeBase']['estimatedBattleSeconds'] == 0.3  # fixture's only buy sits at frame 12
        hero = page.request.get(BASE + f'/api/replays/{replay_id}/inputs?unit=9').json()['hero']
        assert hero['moves'] and hero['moves'][0][1] < 0, hero['moves'][:2]
        page.screenshot(path=str(OUT / 'replay-inputs-desktop.png'), full_page=True)

        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflows mobile viewport'
        page.screenshot(path=str(OUT / 'replay-inputs-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
        print(f'{{"browser": "passed", "replay": "{replay_id}", "frames": 12, "screenshots": "{OUT}"}}')
finally:
    process.terminate()
    process.wait(timeout=10)
