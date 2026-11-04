"""Browser check for the runtime-data import flow using synthetic fixtures only."""
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
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'tests'))
from replay_fixtures import abc_fixture

PORT = 8768
BASE = f'http://127.0.0.1:{PORT}'
env = dict(os.environ, TRAINING_PORT=str(PORT), TRAINING_DB=str(OUT / f'runtime-browser-{uuid.uuid4().hex}.sqlite3'), PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def runtime_rows():
    rows = [{'type': 'meta', 'schema': 'kpl-runtime-v1', 'source': 'browser-fixture'}]
    players = []
    for slot in range(5):
        players.append({'playerId': f'b{slot + 1}', 'heroId': 101 + slot, 'camp': 'blue', 'slot': slot,
                        'kills': 2 if slot == 0 else 1, 'deaths': 1, 'assists': 3,
                        'gold': 1200 - slot * 100, 'exp': 2400 - slot * 100,
                        'damageDealt': 6000 - slot * 500, 'damageTaken': 3000 - slot * 200})
    for slot in range(5):
        players.append({'playerId': f'r{slot + 1}', 'heroId': 201 + slot, 'camp': 'red', 'slot': slot,
                        'kills': 0, 'deaths': 1, 'assists': 0, 'gold': 500, 'exp': 1000,
                        'damageDealt': 1000, 'damageTaken': 1000})
    for frame, time in ((0, 0), (120, 120)):
        scaled = []
        for player in players:
            scaled.append({**player, **{key: int(player[key] * (0 if frame == 0 else 1))
                                        for key in ('kills', 'deaths', 'assists', 'gold', 'exp', 'damageDealt', 'damageTaken')}})
        rows.append({'type': 'frame', 'frame': frame, 'time': time, 'players': scaled})
    rows.extend([
        {'type': 'event', 'frame': 30, 'time': 30, 'event': 'skill_use', 'playerId': 'b1', 'camp': 'blue'},
        {'type': 'event', 'frame': 31, 'time': 31, 'event': 'skill_hit', 'playerId': 'b1', 'camp': 'blue'},
        {'type': 'event', 'frame': 32, 'time': 32, 'event': 'kill', 'playerId': 'b1', 'targetId': 'r1', 'camp': 'blue'},
    ])
    return ('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n').encode()


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

        uploaded = page.request.post(BASE + '/api/replays/files?name=fixture.abc', data=abc_fixture()).json()
        imported = page.request.post(BASE + '/api/replays/import', data={'abcFileId': uploaded['id']}).json()
        replay_id = imported['report']['id']
        runtime_file = OUT / 'runtime-browser-fixture.jsonl'
        runtime_file.write_bytes(runtime_rows())

        page.goto(BASE + '/#replays')
        page.get_by_role('heading', name='回放文件实验室').wait_for()
        page.locator('[data-replay-detail]').first.click()
        page.get_by_role('heading', name='运行时赛训数据').wait_for()
        page.locator('#runtime-file').set_input_files(str(runtime_file))
        page.get_by_role('button', name='导入并分析').click()
        page.get_by_role('heading', name='队员指标').wait_for()
        text = page.locator('#replay-detail').inner_text()
        for expected in ('运行时赛训数据', 'b1', '5,000', '队员指标', '经济与击杀时间轴'):
            assert expected in text, (expected, text)
        assert page.locator('.runtime-table tbody tr').count() == 10
        assert page.locator('#runtime-upload').count() == 0
        assert page.locator(f'a[href="/api/replays/{replay_id}/runtime/file"]').count() == 1
        runtime = page.request.get(BASE + f'/api/replays/{replay_id}/runtime').json()
        assert runtime['analysis']['coverage']['frames'] == 2
        assert runtime['analysis']['teams']['blue']['totals']['gold'] == 5000
        page.screenshot(path=str(OUT / 'replay-runtime-desktop.png'), full_page=True)

        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflows mobile viewport'
        page.screenshot(path=str(OUT / 'replay-runtime-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
        print(json.dumps({'browser': 'passed', 'replay': replay_id, 'runtimeFrames': 2,
                          'consoleErrors': errors, 'screenshots': str(OUT)}, ensure_ascii=False))
finally:
    process.terminate()
    process.wait(timeout=10)
