"""Smoke-test the in-workbench data-analysis page (#stats) in Chromium."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
PORT = '8768'
BASE = f'http://127.0.0.1:{PORT}'


def wait_ready(timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + '/api/analysis/overview', timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(.4)
    return False


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TRAINING_PORT=PORT)
    server = subprocess.Popen([sys.executable, str(ROOT / 'server.py')],
                              cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    report = {'base': BASE, 'checks': [], 'errors': []}
    try:
        if not wait_ready():
            print('分析服务启动失败', file=sys.stderr)
            return 2
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.goto(BASE + '/#stats', wait_until='networkidle')
            page.wait_for_selector('#overview-cards .card', timeout=15000)

            def check(name, condition, detail=''):
                report['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
                if not condition:
                    report['errors'].append(f'{name}: {detail}')

            check('标题', page.locator('h1').inner_text() == '数据看板')
            check('导航入口', page.locator('#navigation .nav-item.active').inner_text() == '战队'
                  and page.locator('#subnavigation a.active').inner_text() == '数据看板')
            check('总览卡片', page.locator('#overview-cards .card').count() >= 4)
            check('近期状态模块', page.locator('#stats-body :text("近期状态")').count() >= 1)
            page.screenshot(path=str(OUT / 'analysis-overview.png'), full_page=True)

            page.locator('#f-partial').check()
            page.locator('#apply').click()
            page.wait_for_timeout(900)
            page.locator('#stats-tabs button[data-tab="players"]').click()
            page.wait_for_timeout(400)
            rows = page.locator('#players-table tbody tr')
            check('队员表', rows.count() >= 10, f'{rows.count()} 行')
            if rows.count():
                rows.first.click()
                page.wait_for_timeout(900)
                check('队员趋势', page.locator('#player-detail #player-chart svg').count() == 1)
                check('队员逐场表', page.locator('#player-detail table tbody tr').count() >= 1)

            page.locator('#stats-tabs button[data-tab="matches"]').click()
            page.wait_for_timeout(300)
            match_rows = page.locator('#matches-table tbody tr')
            check('比赛列表', match_rows.count() >= 1, f'{match_rows.count()} 行')
            if match_rows.count():
                match_rows.first.click()
                page.wait_for_timeout(1200)
                detail = page.locator('#match-detail')
                check('比赛详情', detail.locator('text=十人终局').count() >= 1)
                check('经济图', detail.locator('#match-chart svg').count() == 1)
                coverage = page.request.get(BASE + '/api/analysis/overview').json().get('coverage', {})
                if coverage.get('scoreboardMatches'):
                    check('记分板', detail.locator('text=记分板快照').count() >= 1)
                if coverage.get('povMatches'):
                    check('POV', detail.locator('text=POV 面板段').count() >= 1)
                page.screenshot(path=str(OUT / 'analysis-match.png'), full_page=True)

            page.locator('#stats-tabs button[data-tab="matchups"]').click()
            page.wait_for_timeout(1200)
            check('对线模块', page.locator('#matchups-body').count() >= 1
                  and ('对线' in page.locator('#matchups-body').inner_text()))
            page.screenshot(path=str(OUT / 'analysis-matchups.png'), full_page=True)

            page.locator('#stats-tabs button[data-tab="process"]').click()
            page.wait_for_timeout(1200)
            check('过程模块', page.locator('#process-body').count() >= 1)
            page.screenshot(path=str(OUT / 'analysis-process.png'), full_page=True)

            page.locator('#stats-tabs button[data-tab="capture"]').click()
            page.wait_for_timeout(1200)
            check('采集候选模块', page.locator('.capture-rank-item').count() >= 1)
            page.screenshot(path=str(OUT / 'analysis-capture.png'), full_page=True)

            page.locator('#stats-tabs button[data-tab="sources"]').click()
            page.wait_for_timeout(600)
            check('数据源卡片', page.locator('#source-cards .card').count() >= 3)
            page.screenshot(path=str(OUT / 'analysis-sources.png'), full_page=True)
            browser.close()
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        (OUT / 'analysis-page-report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for check in report['checks']:
        print(('通过' if check['ok'] else '失败'), check['name'], check.get('detail', ''))
    for error in report['errors']:
        print('错误:', error, file=sys.stderr)
    return 0 if not report['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
