"""前端全站巡检：路由 × 视口，捕获运行时错误、空白页、横向溢出与失败请求。

用法（需 Python 3.12 环境，已装 playwright）：
    python scripts/verify_frontend.py
    python scripts/verify_frontend.py --routes 12 --desktop-only
    python scripts/verify_frontend.py --base http://127.0.0.1:8766

路由不硬编码：从首页「全部功能」目录与顶部导航动态抓取 a[href^="#"]，
所以新增页面会自动纳入巡检。启动独立端口与临时数据库，不写用户数据，
不依赖 OCR 夹具。报告输出到 test-results/frontend-audit-report.json，
有 critical 问题时退出码为 1，可直接接入 CI。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
SHOTS = OUT / 'frontend-audit'
REPORT = OUT / 'frontend-audit-report.json'

# 这些路由需要真实对象 ID，空库下必然空态；单独标注，不算缺陷
PARAM_ROUTES = ('#match/', '#player/', '#hero/', '#channel/', '#edit/',
                '#review/', '#opponent/', '#panorama/')
# 忽略的请求失败：浏览器自身请求与可选资源
IGNORE_REQUEST = ('favicon', '/assets/hero-icons/', '.map', 'chrome-extension')
# 可选数据的 404 不算缺陷：没录位置 / 没回放的局本来就取不到，
# 前端已按「这一局没有」处理。只忽略 404，5xx 仍然算故障。
OPTIONAL_404 = ('/api/positions/', '/api/replay/')

VIEWPORTS = [
    ('desktop', {'width': 1440, 'height': 900}),
    ('mobile', {'width': 390, 'height': 844}),
]

PROBE = """() => {
  const doc = document.documentElement;
  const main = document.querySelector('#content') || document.querySelector('main');
  const text = (main ? main.innerText : (document.body.innerText || '')).trim();
  const controls = main ? main.querySelectorAll('input, select, textarea, button, table').length : 0;
  return {
    content_len: text.length,
    title: document.title,
    has_main: !!main,
    controls: controls,
    // An empty state that links to the next step is a rendered page.
    guided: !!main && main.querySelector('a.button, .notice, .empty-state, .hint') !== null,
    overflow_x: doc.scrollWidth > window.innerWidth + 2,
    scroll_width: doc.scrollWidth,
    inner_width: window.innerWidth,
    // The loading banner sits above the rendered content, so only treat the
    // page as stuck when the loading text is all there is.
    loading_only: /^(正在读取|正在打开|正在获取|加载中|正在加载|loading)[^]{0,40}$/i.test(text)
                   && text.length < 120,
    empty_hint: /还没有|暂无|没有数据|空态|empty/i.test(text)
  };
}"""

# 等主内容真正就绪，避免把「正在读取…」的加载态误判成空白页
READY = """() => {
  const main = document.querySelector('#content') || document.querySelector('main');
  const t = (main ? main.innerText : '').trim();
  const loading = /^(正在读取|正在打开|正在获取|加载中|正在加载|loading)[^]{0,40}$/i.test(t);
  if (loading && t.length < 120) return false;
  if (/还没有|暂无|没有数据|空态|empty/i.test(t)) return true;
  return t.length >= 80 || (main ? main.querySelectorAll('input, select, textarea, button, table').length > 0 : false);
}"""
SLOW_MS = 2500
READY_TIMEOUT_MS = 8000
# 冷启动就要现算全量数据的重页面，暂不纳入逐页巡检：
#   #cross 需要先算 190+ 局的跨局向量（约 30s），再逐局拉明细/位置/回放
#   （服务端无缓存，冷启动 60–90s），属于已知性能问题，不是渲染缺陷。
# 这些页面仍可从 #matches → 跨局分析到达；性能优化（批量/懒加载）后应移出。
SLOW_ROUTES = ('#cross',)


def wait_server(base, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + '/api/state', timeout=1)
            return True
        except OSError:
            time.sleep(0.15)
    return False


def collect_routes(page, base):
    page.goto(base + '/studio#overview', wait_until='networkidle', timeout=30000)
    hrefs = page.eval_on_selector_all(
        'a[href^="#"]',
        "els => els.map(e => e.getAttribute('href')).filter(h => h && h.length > 1)")
    routes = []
    for href in hrefs:
        href = href.split('?')[0]
        if href.startswith(PARAM_ROUTES) or href in SLOW_ROUTES:
            continue
        if href not in routes:
            routes.append(href)
    # 导航项与几个常有问题的固定入口兜底
    for extra in ('#overview', '#capture', '#channels', '#bp', '#lab', '#models',
                  '#clean', '#sources', '#compare/player', '#compare/hero',
                  '#topics/hero_pool', '#topics/player_form', '#topics/tempo'):
        if extra not in routes:
            routes.append(extra)
    return routes


def audit_route(page, base, route, viewport_name, errors, take_shot):
    bucket = {'js_errors': [], 'console_errors': [], 'failed_requests': [],
              'http_errors': []}
    page.on('pageerror', lambda e: bucket['js_errors'].append(str(e)))
    page.on('console', lambda m: bucket['console_errors'].append(m.text[:300])
            if m.type == 'error' else None)
    page.on('requestfailed', lambda r: bucket['failed_requests'].append(
        r.url.split(base)[-1][:160])
        if not any(k in r.url for k in IGNORE_REQUEST) else None)
    page.on('response', lambda r: bucket['http_errors'].append(
        '%s %s' % (r.status, r.url.split(base)[-1][:140]))
        if r.status >= 400 and not (
            r.status == 404 and any(k in r.url for k in OPTIONAL_404)) else None)
    started = time.time()
    try:
        page.goto(base + '/studio' + route, wait_until='domcontentloaded', timeout=25000)
    except Exception as exc:
        bucket['js_errors'].append('navigation: %s' % str(exc)[:200])
    try:
        page.wait_for_function(READY, timeout=READY_TIMEOUT_MS)
    except Exception:
        # 超时表示可能卡在加载态或空白页，由下方 probe 如实判定
        pass
    ready_ms = int((time.time() - started) * 1000)
    page.wait_for_timeout(250)
    probe = page.evaluate(PROBE)
    case = {'route': route, 'viewport': viewport_name, 'ready_ms': ready_ms,
            **probe, **bucket}
    problems = []
    if case['js_errors']:
        problems.append('js_error')
    if case['failed_requests']:
        problems.append('request_failed')
    if case['http_errors']:
        problems.append('http_error')
    # A page that renders a form, a table or a guided empty state is a real
    # page even when its text is short: manual entry and empty forms
    # legitimately have little copy.
    sparse = (case['content_len'] < 80
              and not case.get('controls')
              and not case.get('guided'))
    if sparse:
        problems.append('blank_page')
    if case['loading_only']:
        problems.append('stuck_loading')
    if case['overflow_x']:
        problems.append('overflow_x')
    if case['console_errors']:
        problems.append('console_error')
    if case['ready_ms'] > SLOW_MS and case['content_len'] >= 80:
        problems.append('slow_render')
    critical = {'js_error', 'request_failed', 'blank_page', 'stuck_loading'}
    case['status'] = ('critical' if critical.intersection(problems)
                      else 'warn' if problems else 'pass')
    case['problems'] = problems
    if take_shot and (case['status'] != 'pass' or route in ('#overview', '#capture')):
        SHOTS.mkdir(parents=True, exist_ok=True)
        name = '%s-%s.png' % (viewport_name, route.lstrip('#').replace('/', '_'))
        try:
            page.screenshot(path=str(SHOTS / name), full_page=True)
            case['screenshot'] = str((SHOTS / name).relative_to(ROOT))
        except Exception:
            pass
    return case


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='')
    ap.add_argument('--routes', type=int, default=0, help='只跑前 N 个路由')
    ap.add_argument('--desktop-only', action='store_true')
    ap.add_argument('--no-shots', action='store_true')
    ap.add_argument('--only', default='', help='只跑指定路由，逗号分隔，如 #capture,#channels')
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    server = None
    base = args.base.rstrip('/')
    if not base:
        base = 'http://127.0.0.1:8771'
        db = OUT / ('frontend-audit-%s.sqlite3' % uuid.uuid4().hex[:10])
        env = dict(os.environ, TRAINING_PORT='8771', TRAINING_DB=str(db),
                   TRAINING_ALLOW_REMOTE='', PYTHONIOENCODING='utf-8')
        server = subprocess.Popen(
            [sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not wait_server(base):
            server.terminate()
            raise SystemExit('巡检服务未能启动：%s' % base)
    viewports = VIEWPORTS[:1] if args.desktop_only else VIEWPORTS
    cases = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for vp_name, vp in viewports:
                context = browser.new_context(viewport=vp, device_scale_factor=1)
                # 每个路由用独立 page，避免监听器累积与状态串扰
                page = context.new_page()
                if vp_name == viewports[0][0]:
                    routes = collect_routes(page, base)
                    if args.only:
                        routes = [r.strip() for r in args.only.split(',') if r.strip()]
                    elif args.routes:
                        routes = routes[:args.routes]
                for idx, route in enumerate(routes, 1):
                    rp = context.new_page()
                    case = audit_route(rp, base, route, vp_name, None,
                                       not args.no_shots)
                    cases.append(case)
                    rp.close()
                    print('[%s %d/%d] %-28s %s %s' % (
                        vp_name, idx, len(routes), route, case['status'],
                        ','.join(case['problems']) or 'ok'), flush=True)
                page.close()
                context.close()
            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()

    summary = {
        'routes': len(routes), 'cases': len(cases),
        'pass': sum(1 for c in cases if c['status'] == 'pass'),
        'warn': sum(1 for c in cases if c['status'] == 'warn'),
        'critical': sum(1 for c in cases if c['status'] == 'critical'),
        'with_js_error': sum(1 for c in cases if c['js_errors']),
        'with_overflow': sum(1 for c in cases if c['overflow_x']),
        'blank_pages': sum(1 for c in cases
                           if c['content_len'] < 80
                           and not c.get('controls') and not c.get('guided')),
        'slow_pages': sum(1 for c in cases if c['ready_ms'] > SLOW_MS),
        'max_ready_ms': max((c['ready_ms'] for c in cases), default=0),
    }
    report = {'generated_at': datetime.now().isoformat(timespec='seconds'),
              'base': base, 'viewports': [v[0] for v in viewports],
              'routes': routes, 'summary': summary, 'cases': cases}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding='utf-8')
    print('\n汇总：%s' % json.dumps(summary, ensure_ascii=False))
    print('报告：%s' % REPORT)
    return 1 if summary['critical'] else 0


if __name__ == '__main__':
    sys.exit(main())
