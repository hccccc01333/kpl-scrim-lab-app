"""Evaluate the unified platform at 500-match scale.

Creates an isolated database, starts a local server, measures API and browser
pages, and writes test-results/scale/report.json. No user data is touched.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results' / 'scale'
OUT.mkdir(parents=True, exist_ok=True)
DB = OUT / 'scale.sqlite3'
PORT = '8778'
BASE = f'http://127.0.0.1:{PORT}'
COUNT = int(os.environ.get('SCALE_COUNT', '500'))


def build_database():
    sys.path.insert(0, str(ROOT))
    from tests.test_analysis_data import db_match, ROSTER, OWN, ENEMY, C_BLUE, C_RED, D_BLUE, D_RED
    if DB.exists():
        DB.unlink()
    matches_dir = OUT / 'matches'
    imports_dir = OUT / 'imports'
    for folder in (matches_dir, imports_dir):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
    results = OUT / 'results.sqlite3'
    if results.exists():
        results.unlink()
    connection = sqlite3.connect(DB)
    connection.executescript('''
      CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
    ''')
    connection.execute('INSERT INTO settings VALUES (1,?)',
                       (json.dumps({'teamName': '规模测试队', 'roster': ROSTER}, ensure_ascii=False),))
    own_sets = [OWN, C_BLUE, D_BLUE]
    enemy_sets = [ENEMY, C_RED, D_RED]
    start = date(2026, 1, 1)
    for index in range(COUNT):
        day = start + timedelta(days=index % 300)
        opponent = f'对手{index % 40 + 1:02d}'
        side = 'left' if index % 2 == 0 else 'right'
        winner = side if index % 4 else ('right' if side == 'left' else 'left')
        body = db_match(f'scale-{index:04d}', day.isoformat(), opponent, side, winner,
                        900 + (index * 37) % 900, own_sets[index % 3], enemy_sets[(index + 1) % 3])
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           (body['id'], json.dumps(body, ensure_ascii=False)))
    connection.commit()
    connection.close()
    return matches_dir, imports_dir, results


def start_server(matches_dir, imports_dir, results):
    env = dict(os.environ, TRAINING_PORT=PORT, TRAINING_DB=str(DB),
               ANALYSIS_MATCHES=str(matches_dir), ANALYSIS_IMPORTS=str(imports_dir),
               STUDIO_RESULTS_DB=str(results), PYTHONIOENCODING='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT), env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(600):
        try:
            urllib.request.urlopen(BASE + '/api/health', timeout=2)
            return process
        except OSError:
            time.sleep(.2)
    process.terminate()
    raise RuntimeError('规模测试服务未启动')


def main():
    from playwright.sync_api import sync_playwright
    if os.environ.get('SCALE_REUSE') == '1':
        matches_dir, imports_dir, results = OUT / 'matches', OUT / 'imports', OUT / 'results.sqlite3'
        if not DB.is_file():
            raise SystemExit('scale.sqlite3 不存在；先运行一次不设 SCALE_REUSE 的评测')
    else:
        matches_dir, imports_dir, results = build_database()
    server = start_server(matches_dir, imports_dir, results)
    report = {'count': COUNT, 'api': {}, 'pages': {}, 'checks': [], 'errors': []}

    def check(name, condition, detail=''):
        report['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
        if not condition:
            report['errors'].append(f'{name}: {detail}')

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(120000)
            page_errors = []
            page.on('pageerror', lambda error: page_errors.append(str(error)))

            started = time.perf_counter()
            data = page.request.get(BASE + '/api/studio/view/matches?source=db,bundle,sheet&limit=24&offset=0').json()
            report['api']['matchesPage'] = round((time.perf_counter() - started) * 1000)
            check('API 总数', data.get('total') == COUNT, str(data.get('total')))
            check('API 分页 24', len(data.get('matches', [])) == 24, str(len(data.get('matches', []))))

            started = time.perf_counter()
            searched = page.request.get(BASE + '/api/studio/view/matches?source=db,bundle,sheet&q=%E5%AF%B9%E6%89%8B07&limit=24').json()
            report['api']['matchSearch'] = round((time.perf_counter() - started) * 1000)
            check('API 搜索', 0 < searched.get('total', 0) < COUNT, str(searched.get('total')))

            started = time.perf_counter()
            page.goto(BASE + '/studio#matches', wait_until='domcontentloaded')
            page.wait_for_selector('.match-card', timeout=60000)
            report['pages']['matches'] = round((time.perf_counter() - started) * 1000)
            check('比赛页首屏 24 张', page.locator('.match-card').count() == 24, str(page.locator('.match-card').count()))
            check('加载更多按钮', page.locator('#match-load').is_visible())
            started = time.perf_counter()
            page.locator('#match-load').click()
            page.wait_for_timeout(1200)
            report['pages']['matchesMore'] = round((time.perf_counter() - started) * 1000)
            check('加载更多 48 张', page.locator('.match-card').count() == 48, str(page.locator('.match-card').count()))

            page.locator('#match-search').fill('对手07')
            page.wait_for_timeout(1000)
            check('比赛页搜索', page.locator('.match-card').count() > 0 and page.locator('.match-card').count() < 30)

            for name, path, selector in (('heroes', '/studio#heroes', '.hero-card'),
                                          ('players', '/studio#players', '.hero-card'),
                                          ('records', '/studio#records', '.record-card'),
                                          ('featured', '/studio#featured', '.page-heading')):
                started = time.perf_counter()
                page.goto(BASE + path, wait_until='domcontentloaded')
                page.wait_for_selector(selector, timeout=60000)
                report['pages'][name] = round((time.perf_counter() - started) * 1000)
                check(f'{name} 页面', page.locator(selector).count() >= 1)

            page.goto(BASE + '/studio#overview', wait_until='domcontentloaded')
            page.wait_for_selector('.home-hero', timeout=15000)
            page.locator('#global-search').fill('对手01')
            page.wait_for_timeout(900)
            check('全局搜索比赛', page.locator('.search-result').count() >= 1)

            check('无 JavaScript 错误', not page_errors, '; '.join(page_errors[:5]))
            report['consoleErrors'] = page_errors
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    for item in report['checks']:
        print(('通过' if item['ok'] else '失败'), item['name'], item.get('detail', ''))
    print(json.dumps({'apiMs': report['api'], 'pageMs': report['pages'], 'errors': report['errors']}, ensure_ascii=False))
    raise SystemExit(0 if not report['errors'] else 1)


if __name__ == '__main__':
    main()
