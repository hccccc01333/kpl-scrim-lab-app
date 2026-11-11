"""Smoke-test the unified platform shell: home, capture entry, analysis and compatibility routes."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
PORT = '8772'
BASE = f'http://127.0.0.1:{PORT}'
env = dict(os.environ, TRAINING_PORT=PORT,
           TRAINING_DB=str(OUT / f'platform-{uuid.uuid4().hex}.sqlite3'),
           PYTHONIOENCODING='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
report = {'checks': [], 'errors': []}


def check(name, condition, detail=''):
    report['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
    if not condition:
        report['errors'].append(f'{name}: {detail}')


try:
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + '/api/studio/workspace', timeout=1)
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Test server did not start')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page_errors = []
        page.on('pageerror', lambda error: page_errors.append(str(error)))

        page.goto(BASE + '/studio', wait_until='networkidle')
        page.wait_for_selector('.product-intro', timeout=15000)
        check('总览标题', '每一场训练' in page.locator('.product-intro h1').inner_text())
        nav_labels = page.locator('#navigation .nav-item').all_inner_texts()
        check('一级导航', nav_labels == ['首页', '比赛', '战队', '选手', '英雄', 'BP', '对比', '数据'], str(nav_labels))
        check('不再显示步骤编号', page.locator('#navigation .stage-number').count() == 0)
        check('窄屏导入按钮存在', page.locator('.product-import').count() == 1)
        check('总览不显示二级导航', page.locator('#subnavigation').is_hidden())
        check('真实比赛或首局引导', page.locator('.match-spotlight').count() == 1)
        check('三个分析方向', page.locator('.product-explore .home-card').count() == 3)
        check('赛训概况', page.locator('.product-statline > a').count() == 4)
        check('比赛列表或空态', page.locator('.product-recent').count() == 1)
        check('功能地图', page.locator('.home-directory .directory-group').count() == 8
              and page.locator('.home-directory .directory-link').count() == 38)
        page.screenshot(path=str(OUT / 'platform-home.png'), full_page=False)

        page.locator('#navigation .nav-group:last-child .nav-menu-toggle').click()
        check('导航按钮展开', page.locator('#navigation .nav-group:last-child .nav-menu').is_visible())
        check('全部子页可见', page.locator('#navigation .nav-menu-link').count() == 36)
        page.locator('#navigation a.nav-item[href="#capture"]').click()
        page.wait_for_selector('.capture-page', timeout=10000)
        check('采集页标题', page.locator('h1').inner_text() == '采集')
        check('采集二级导航', page.locator('#subnavigation a').all_inner_texts() == ['采集', '采集通道', '批量导入', '截图采集', '录屏采集', '回放文件', '数据集', '数据清洗', '字段与来源', '统计实验', '模型实验'])
        check('采集直接建局', page.locator('#capture-create-form').count() == 1)
        page.locator('#capture-create-form button').click()
        page.wait_for_selector('#capture-create-status:has-text("至少填写")')
        check('空采集不创建通道', '#capture' in page.url and page.locator('#capture-create-status').is_visible())
        page.locator('#capture-opponent').fill('界面回归测试对手')
        def reject_create(route):
            if route.request.method == 'POST':
                route.fulfill(status=503, content_type='application/json', body='{"detail":"temporary failure"}')
            else:
                route.continue_()
        page.route('**/api/channels', reject_create)
        page.locator('#capture-create-form button').click()
        page.wait_for_selector('#capture-create-status:has-text("创建失败")')
        check('创建失败保留输入并可重试', page.locator('#capture-opponent').input_value() == '界面回归测试对手' and page.locator('#capture-create-form button').is_enabled())
        page.unroute('**/api/channels', reject_create)
        page.locator('#capture-create-form button').click()
        page.wait_for_selector('#meta-opponent', timeout=15000)
        check('创建后进入本局并保留对手', page.locator('#meta-opponent').input_value() == '界面回归测试对手' and '#channel/' in page.url)
        page.goto(BASE + '/studio#capture', wait_until='networkidle')
        page.wait_for_selector('.capture-steps', timeout=15000)
        check('采集三步', page.locator('.capture-steps > div').count() == 3)
        check('六类采集来源卡片', page.locator('.capture-sources > .capture-source').count() == 6)
        check('唯一必采标签', page.locator('.capture-sources .tag.amber').count() == 1)
        check('推荐主路径标签', page.locator('.capture-sources .tag.blue').count() == 1)
        check('五份采集说明', page.locator('[data-guide]').count() == 5)
        check('审核双合规口径可见', '审核门槛' in page.locator('.capture-page').inner_text())
        page.screenshot(path=str(OUT / 'platform-capture.png'), full_page=False)

        page.locator('#navigation a.nav-item[href="#matches"]').click()
        page.wait_for_selector('h1:text("比赛档案")', timeout=10000)
        check('比赛二级导航', page.locator('#subnavigation a').all_inner_texts() == ['比赛档案', '精选对局', '训练纪录', '对局工作区', '手工录入'])

        page.locator('#navigation a.nav-item[href="#team"]').click()
        page.wait_for_selector('.team-summary', timeout=15000)
        check('战队二级导航', page.locator('#subnavigation a').all_inner_texts() == ['团队复盘','数据看板','训练跟踪','战队名单','前期与优势转化','经济转折','训练组汇总','分析报告'])
        check('按功能进入战队', page.locator('#navigation .nav-item.active').inner_text() == '战队')

        page.get_by_role('link', name='数据看板', exact=True).click()
        page.wait_for_selector('h1:text("数据看板")', timeout=10000)
        check('数据看板入口', page.locator('#subnavigation a.active').inner_text() == '数据看板')

        page.goto(BASE + '/studio#training', wait_until='networkidle')
        page.wait_for_selector('h1:text("训练跟踪")', timeout=15000)
        check('旧训练跟踪深链', page.locator('#subnavigation a.active').inner_text() == '训练跟踪')

        page.set_viewport_size({'width':390, 'height':844})
        page.goto(BASE + '/studio#stats', wait_until='networkidle')
        page.wait_for_selector('#stats-band', timeout=15000)
        page.wait_for_timeout(800)
        check('数据看板窄屏不横向溢出', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'))
        page.set_viewport_size({'width':1440, 'height':1000})

        page.goto(BASE + '/studio#desk', wait_until='networkidle')
        page.wait_for_selector('.desk-grid', timeout=15000)
        check('对局工作区深链', page.locator('#subnavigation a.active').inner_text() == '对局工作区')

        page.goto(BASE + '/studio#datasets', wait_until='networkidle')
        page.wait_for_selector('h1:text("数据集")', timeout=10000)
        check('清洗入口保留', page.locator('a[href="#clean"]').count() >= 1)

        page.goto(BASE + '/studio#clean', wait_until='networkidle')
        page.wait_for_selector('h1:text("数据清洗")', timeout=10000)
        check('旧清洗深链', page.locator('#subnavigation a.active').inner_text() == '数据清洗')

        page.goto(BASE + '/studio#sources', wait_until='networkidle')
        page.wait_for_selector('h1:text("字段与来源")', timeout=10000)
        check('字段来源归入数据', page.locator('#navigation .nav-item.active').inner_text() == '数据')

        page.goto(BASE + '/studio#identity', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('身份绑定页', page.locator('.page-facts').count() == 1
              and (page.locator('[data-alias-label]').count() >= 1 or page.locator('.empty-state').count() >= 1))
        team_options = page.locator('#identity-team-preset option').all_inner_texts()
        check('自定义战队选项', any('自定义战队' in item for item in team_options), str(team_options[:3]))

        page.goto(BASE + '/studio#import', wait_until='networkidle')
        page.wait_for_selector('.import-panel', timeout=15000)
        check('批量导入页', page.locator('#import-file').count() == 1)

        page.goto(BASE + '/studio#topics/player_form', wait_until='networkidle')
        page.wait_for_selector('#topic-run', timeout=15000)
        check('功能直接进入分析', page.locator('h1').inner_text() == '近期状态与稳定性' and page.locator('.topic-card').count() == 0)
        check('分析功能归选手', page.locator('#navigation .nav-item.active').inner_text() == '选手')

        page.goto(BASE + '/studio#lab', wait_until='networkidle')
        page.wait_for_selector('.scenario-card', timeout=15000)
        page.wait_for_timeout(1800)
        check('分析场景卡', page.locator('.scenario-card').count() == 6)
        check('分析默认出结果', page.locator('#result-output').inner_text().strip() not in ('', '正在准备默认分析…'))
        check('高级设置默认折叠', page.locator('.lab-advanced').evaluate('(el) => !el.open'))
        page.locator('.scenario-card[data-method="trend"]').click()
        page.wait_for_timeout(1200)
        check('场景卡切换', page.locator('.scenario-card.active strong').inner_text() == '看趋势')

        page.goto(BASE + '/studio#models', wait_until='networkidle')
        page.wait_for_selector('.scenario-card', timeout=15000)
        check('模型场景卡', page.locator('.scenario-card').count() == 2)

        page.goto(BASE + '/studio#heroes', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        # 提示条的业务规则是「样本 < 3 局才提示」，不能硬编码成「必须恰好 1 条」：
        # 测试库里已确认的比赛数会随前面的用例变化，>=3 局时本就不该出现。
        facts = page.locator('.page-facts').first.inner_text()
        found = re.search(r'(\d+)\s*局', facts)
        match_count = int(found.group(1)) if found else None
        notes = page.locator('.sample-note').count()
        expected = 1 if match_count is not None and match_count < 3 else 0
        check('英雄页样本提示', notes == expected,
              f'{match_count} 局时提示条 {notes} 条（期望 {expected} 条）')
        check('英雄页数据折叠', page.locator('.raw-fold').count() == 2)
        check('英雄页筛选折叠', page.locator('.page-filter').evaluate('(el) => !el.open'))
        check('英雄页下一步', page.locator('.next-card').count() == 3)

        page.goto(BASE + '/studio#matches', wait_until='networkidle')
        page.wait_for_selector('.match-toolbar', timeout=15000)
        check('比赛卡片入口', page.locator('.match-toolbar').count() == 1)
        check('比赛表格折叠', page.locator('details.raw-fold').evaluate('(el) => !el.open'))

        page.goto(BASE + '/studio#datasets', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('数据集空态', page.locator('.empty-state').count() >= 1)

        page.goto(BASE + '/studio#reports', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('分析报告空态', page.locator('.empty-state').count() >= 1)

        page.goto(BASE + '/studio#team', wait_until='networkidle')
        page.wait_for_selector('.team-summary', timeout=15000)
        check('团队摘要', page.locator('.team-summary .team-kpi').count() == 4)
        check('团队标签页', page.locator('.team-tabs .tab').count() == 5)
        check('团队筛选折叠', page.locator('.page-filter').evaluate('(el) => !el.open'))

        page.goto(BASE + '/studio#compare', wait_until='networkidle')
        page.wait_for_selector('.compare-toolbar', timeout=15000)
        check('对比工具栏', page.locator('.compare-toolbar').count() == 1)
        check('对比输出', page.locator('.compare-entity').count() >= 2
              or page.locator('#compare-output .empty-state').count() >= 1)

        page.goto(BASE + '/studio#featured', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('精选对局页', page.locator('.page-facts').count() == 1)

        page.goto(BASE + '/studio#records', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('训练纪录卡', page.locator('.record-card').count() >= 1)

        page.goto(BASE + '/studio#bp', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('BP 页', page.locator('.page-facts').count() == 1)

        page.goto(BASE + '/studio#combos', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        check('组合页', page.locator('.page-facts').count() == 1)

        page.goto(BASE + '/studio?nav=directory#analysis', wait_until='networkidle')
        page.wait_for_selector('.feature-directory', timeout=15000)
        check('旧分析链接成为功能目录', page.locator('h1').inner_text() == '全部功能' and page.locator('.feature-directory-group').count() == 7)
        for route, group in [('players','选手'),('heroes','英雄'),('bp','BP'),('compare/hero','对比'),('models','数据'),('datasets','数据'),('roster','战队'),('identity','选手')]:
            page.goto(BASE + '/studio?nav=' + route + '#' + route, wait_until='networkidle')
            page.wait_for_selector('#content h1', timeout=15000)
            check('功能归属 ' + route, page.locator('#navigation .nav-item.active').inner_text() == group)
        page.goto(BASE + '/studio?nav=compare#compare/hero', wait_until='networkidle')
        page.wait_for_selector('.compare-toolbar', timeout=15000)
        check('英雄对比导航选中', page.locator('#subnavigation a.active').inner_text() == '英雄对比')
        page.locator('[data-compare-kind="player"]').click()
        page.wait_for_url('**#compare/player')
        page.wait_for_selector('#subnavigation a.active:has-text("选手对比")')
        check('对比切换同步路径', page.locator('[data-compare-kind="player"]').evaluate('(el)=>el.classList.contains("active")'))

        page.goto(BASE + '/studio#overview', wait_until='networkidle')
        page.wait_for_selector('.product-intro', timeout=15000)
        page.locator('#global-search').fill('英雄')
        page.wait_for_timeout(400)
        check('全局搜索', page.locator('.search-result').count() >= 1)

        page.goto(BASE + '/studio#heroes', wait_until='networkidle')
        page.wait_for_selector('.page-facts', timeout=15000)
        if page.locator('.hero-card').count():
            href = page.locator('.hero-card').first.get_attribute('href')
            page.goto(BASE + '/studio' + href, wait_until='networkidle')
            page.wait_for_selector('.entity-kpi', timeout=15000)
            check('英雄详情与雷达', page.locator('.entity-kpi').count() == 6 and page.locator('.radar-wrap').count() == 1)

        if page.locator('.next-card[href^="#compare/hero/"]').count():
            wanted = page.locator('h1').inner_text()
            page.locator('.next-card[href^="#compare/hero/"]').click()
            page.wait_for_selector('.compare-toolbar', timeout=15000)
            check('英雄详情对比保留对象', page.locator('#compare-a').input_value() == wanted)
            check('英雄详情对比保留类型', page.locator('[data-compare-kind="hero"]').evaluate('(el)=>el.classList.contains("active")'))

        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE + '/studio', wait_until='networkidle')
        page.wait_for_selector('.product-intro', timeout=10000)
        check('窄屏导入可点击', page.locator('.product-import').is_visible())
        check('窄屏不横向溢出', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        check('不展示旧品牌标识', page.locator('.brand,.brand-mark').count() == 0)
        check('无 JavaScript 错误', not page_errors, '; '.join(page_errors[:5]))
        page.screenshot(path=str(OUT / 'platform-home-mobile.png'), full_page=False)
        browser.close()
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    (OUT / 'platform-page-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

for item in report['checks']:
    print(('通过' if item['ok'] else '失败'), item['name'], item.get('detail', ''))
for error in report['errors']:
    print('错误:', error, file=sys.stderr)
raise SystemExit(0 if not report['errors'] else 1)
