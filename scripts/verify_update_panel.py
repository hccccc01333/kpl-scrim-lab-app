"""工作台更新提示的前端回归检查（Playwright，自带 mock，不依赖更新清单）。

覆盖：
1. 发现新版本：右下角卡片、版本/说明/按钮；
2. 「稍后」：本次会话内不再自动出现（刷新后仍不出现），新会话重新提示；
3. 立即更新：POST /api/update/apply → 轮询 /api/health 等待新版本；
4. 选择本地更新包：POST /api/update/stage → POST /api/update/restart → 轮询健康检查；
5. 版本过旧（blocked）：引导下载完整包；
6. 已是最新 / 检查失败 / 源码模式：页脚手动检查只提示，不打扰；
7. 离线静默：自动检查失败不弹任何东西。

用法（先启动工作台，CI 里在 server 起来后跑）：
    python scripts/verify_update_panel.py --base http://127.0.0.1:8766
    python scripts/verify_update_panel.py --base http://127.0.0.1:8766 --no-shots

输出 test-results/update-panel-report.json 与 test-results/update-panel/*.png；
有失败时退出码 1。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
SHOTS = OUT / 'update-panel'
REPORT = OUT / 'update-panel-report.json'

PATCH_URL = 'https://example.com/releases/download/v9.9.9/patch-9.9.9.zip'
FULL_URL = 'https://example.com/releases/download/v9.9.9/full.zip'

AVAILABLE = {
    'ok': True,
    'currentVersion': '1.6.2',
    'latestVersion': '1.6.3',
    'updateAvailable': True,
    'blocked': False,
    'minVersion': '1.5.32',
    'releaseDate': '2026-11-12',
    'notes': ['修复更新提示在刷新后重复出现的问题', '统计只采集匿名安装 ID'],
    'patch': {'url': PATCH_URL, 'sha256': 'a' * 64, 'size': 700000},
    'full': {'url': FULL_URL, 'sha256': 'b' * 64, 'size': 82 * 1024 * 1024},
    'sourceMode': False,
    'source': 'https://example.com/update.json',
}
LATEST = dict(AVAILABLE, latestVersion='1.6.2', updateAvailable=False, patch=None, full=None)
BLOCKED = dict(AVAILABLE, latestVersion='1.7.0', blocked=True, minVersion='1.6.3')
SOURCE_MODE = dict(AVAILABLE, sourceMode=True)
USAGE_ENABLED = {
    'ok': True, 'enabled': True, 'envDisabled': False, 'optout': False,
    'installId': '0123456789abcdef0123456789abcdef',
    'lastPingAt': '2026-11-11T08:00:00+00:00', 'periodHours': 20,
}
USAGE_DISABLED = dict(USAGE_ENABLED, enabled=False, optout=True)
TOUR_INIT = "localStorage.setItem('training-tour-complete-v3', '1');"
NOTICE_INIT = "localStorage.setItem('kpl-telemetry-notice-v1', '1');"


class Case:
    def __init__(self, name: str):
        self.name = name
        self.suppress_notice = True
        self.state = {
            'check': None,
            'apply': None,
            'stage': None,
            'restart': None,
            'status': None,
            'health': None,
            'usageStatus': None,
            'usageOptout': None,
            'usageOptin': None,
            'calls': [],
            'usageCalls': [],
            'healthCalls': 0,
            'checkCalls': 0,
        }
        self.issues: list[str] = []

    def fail(self, message: str) -> None:
        self.issues.append(message)


def _json(route, payload, status: int = 200) -> None:
    route.fulfill(status=status, content_type='application/json',
                  body=json.dumps(payload, ensure_ascii=False))


def _health_payload(state) -> dict:
    source = state.get('health')
    if callable(source):
        source = source(state['healthCalls'])
    if isinstance(source, list):
        source = source[min(state['healthCalls'], len(source) - 1)]
    return source or {'ok': True, 'version': '1.6.3'}


def install_routes(page, case: Case) -> None:
    state = case.state

    def on_update(route):
        path = urlsplit(route.request.url).path
        if path.startswith('/api/usage/'):
            state['usageCalls'].append(path)
            if path == '/api/usage/status':
                payload = state.get('usageStatus')
            elif path == '/api/usage/optout':
                payload = state.get('usageOptout') or state.get('usageStatus')
                if payload:
                    state['usageStatus'] = payload
            elif path == '/api/usage/optin':
                payload = state.get('usageOptin') or state.get('usageStatus')
                if payload:
                    state['usageStatus'] = payload
            else:
                payload = {'ok': False}
            if payload is None:
                _json(route, {'ok': False, 'detail': 'unexpected'}, 404)
            else:
                _json(route, payload)
            return
        state['calls'].append(path)
        if path == '/api/update/check':
            state['checkCalls'] += 1
            payload = state.get('check')
        elif path == '/api/update/apply':
            payload = state.get('apply')
        elif path == '/api/update/stage':
            payload = state.get('stage')
        elif path == '/api/update/restart':
            payload = state.get('restart')
        elif path == '/api/update/status':
            payload = state.get('status')
        else:
            payload = {'ok': False}
        if payload is None:
            _json(route, {'ok': False, 'detail': 'unexpected'}, 500)
        else:
            _json(route, payload)

    def on_health(route):
        state['healthCalls'] += 1
        _json(route, _health_payload(state))

    page.route('**/api/update/**', on_update)
    page.route('**/api/usage/**', on_update)
    page.route('**/api/health', on_health)


def wait_banner(page, timeout: int = 12000) -> bool:
    try:
        page.wait_for_selector('.update-card', state='visible', timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def card_text(page) -> str:
    return page.locator('.update-card').inner_text()


def run_case(browser, base: str, case: Case, shots: bool) -> None:
    context = browser.new_context(viewport={'width': 1360, 'height': 900})
    page = context.new_page()
    script = TOUR_INIT + (NOTICE_INIT if getattr(case, 'suppress_notice', True)
                          else "Object.defineProperty(navigator, 'webdriver', {get: () => false});")
    page.add_init_script(script)
    errors: list[str] = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    install_routes(page, case)
    try:
        page.goto(base, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_selector('[data-action="check-update"]', timeout=20000)
        case.run(page)
        if errors:
            case.fail(f'页面 JS 报错：{errors[:2]}')
        if shots:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f'{case.name}.png'), full_page=False)
    except Exception as exc:  # noqa: BLE001
        case.fail(f'用例异常：{exc}')
    finally:
        context.close()


def case_available(browser, base: str, shots: bool) -> Case:
    case = Case('available')
    case.state['check'] = AVAILABLE

    def run(page):
        if not wait_banner(page):
            case.fail('没有出现更新卡片')
            return
        text = card_text(page)
        for needle in ('v1.6.3', '当前 v1.6.2', '立即更新', '选择本地更新包', '稍后'):
            if needle not in text:
                case.fail(f'卡片缺少「{needle}」')
        if page.locator('.update-notes li').count() < 2:
            case.fail('更新说明没有渲染')
        if page.locator('.update-notes a').count() != 1:
            case.fail('缺少完整更新说明链接')
        if page.locator('[data-update="now"]').is_hidden():
            case.fail('立即更新按钮不可见')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_dismiss(browser, base: str, shots: bool) -> Case:
    case = Case('dismiss')
    case.state['check'] = AVAILABLE

    def run(page):
        if not wait_banner(page):
            case.fail('没有出现更新卡片')
            return
        page.click('[data-update="later"]')
        page.wait_for_timeout(300)
        if page.locator('.update-card').is_visible():
            case.fail('点「稍后」后卡片没有关闭')
        stored = page.evaluate("() => sessionStorage.getItem('kpl-update-dismissed')")
        if stored != '1.6.3':
            case.fail(f'会话内没有记住稍后的版本：{stored}')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(2600)
        if page.locator('.update-card').is_visible():
            case.fail('刷新后仍重复弹出')
        # 新会话（新的浏览器上下文）应该重新提醒
        fresh = browser.new_context(viewport={'width': 1360, 'height': 900})
        try:
            probe = fresh.new_page()
            probe.add_init_script(TOUR_INIT + NOTICE_INIT)
            install_routes(probe, case)
            probe.goto(base, wait_until='domcontentloaded')
            if not wait_banner(probe):
                case.fail('新会话没有重新提示更新')
        finally:
            fresh.close()

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_blocked(browser, base: str, shots: bool) -> Case:
    case = Case('blocked')
    case.state['check'] = BLOCKED

    def run(page):
        if not wait_banner(page):
            case.fail('没有出现更新卡片')
            return
        text = card_text(page)
        if '最低支持版本' not in text:
            case.fail('过旧版本没有说明最低支持版本')
        link = page.locator('.update-card a.update-extra', has_text='下载完整包')
        if link.count() != 1:
            case.fail('缺少下载完整包入口')
        elif 'releases/download' not in link.first.get_attribute('href', timeout=3000):
            case.fail('下载完整包链接不对')
        if page.locator('[data-update="now"]').is_visible():
            case.fail('过旧版本不应该显示一键更新')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_apply(browser, base: str, shots: bool) -> Case:
    case = Case('apply')
    case.state['check'] = AVAILABLE
    case.state['apply'] = {'ok': True, 'restarting': True, 'pending': {'version': '1.6.3'}}
    # 故意让健康检查停留在旧版本：页面会一直显示“正在重启”，测试结束后关掉上下文即可，
    # 避免触发真实页面刷新导致断言竞态。
    case.state['health'] = {'ok': True, 'version': '1.6.2'}

    def run(page):
        if not wait_banner(page):
            case.fail('没有出现更新卡片')
            return
        page.click('[data-update="now"]')
        page.wait_for_timeout(4200)
        if '/api/update/apply' not in case.state['calls']:
            case.fail('没有请求 /api/update/apply')
        if case.state['healthCalls'] < 1:
            case.fail('没有轮询 /api/health')
        body = page.locator('.update-card').inner_text()
        if '重启' not in body and '已更新' not in body:
            case.fail(f'更新过程没有进度反馈：{body[:80]}')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_local_package(browser, base: str, shots: bool) -> Case:
    case = Case('local-package')
    case.state['check'] = AVAILABLE
    case.state['stage'] = {'ok': True, 'pending': {'version': '1.6.3'}}
    case.state['restart'] = {'ok': True, 'restarting': True}
    case.state['health'] = {'ok': True, 'version': '1.6.2'}
    tmpdir = Path(tempfile.mkdtemp(prefix='kpl-update-ui-'))
    patch = tmpdir / 'patch-1.6.3.zip'
    patch.write_bytes(b'PK\x05\x06' + b'\x00' * 18)

    def run(page):
        if not wait_banner(page):
            case.fail('没有出现更新卡片')
            return
        page.set_input_files('[data-update-file]', str(patch))
        page.wait_for_timeout(4200)
        if '/api/update/stage' not in case.state['calls']:
            case.fail('没有请求 /api/update/stage')
        if '/api/update/restart' not in case.state['calls']:
            case.fail('没有请求 /api/update/restart')
        if case.state['healthCalls'] < 1:
            case.fail('没有轮询 /api/health')

    case.run = run
    run_case(browser, base, case, shots)
    try:
        patch.unlink(missing_ok=True)
        tmpdir.rmdir()
    except OSError:
        pass
    return case


def case_latest(browser, base: str, shots: bool) -> Case:
    case = Case('latest')
    case.state['check'] = LATEST

    def run(page):
        page.wait_for_timeout(2600)
        if page.locator('.update-card').is_visible():
            case.fail('已是最新时不应弹卡片')
        page.click('[data-action="check-update"]')
        try:
            page.wait_for_selector('.update-toast', state='visible', timeout=5000)
        except Exception:  # noqa: BLE001
            case.fail('手动检查没有提示结果')
            return
        if '已是最新版本' not in page.locator('.update-toast').inner_text():
            case.fail('手动检查提示不正确')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_offline(browser, base: str, shots: bool) -> Case:
    case = Case('offline')

    def on_update(route):
        path = urlsplit(route.request.url).path
        case.state['calls'].append(path)
        _json(route, {'ok': False, 'reason': 'offline'}, 503)

    def run(page):
        page.wait_for_timeout(2800)
        if page.locator('.update-card').is_visible():
            case.fail('离线自动检查不应弹卡片')
        page.click('[data-action="check-update"]')
        try:
            page.wait_for_selector('.update-toast', state='visible', timeout=5000)
        except Exception:  # noqa: BLE001
            case.fail('手动检查失败没有提示')
            return
        if '检查更新失败' not in page.locator('.update-toast').inner_text():
            case.fail('失败提示不正确')

    case.run = run
    context_case = case
    # 该用例需要把 check 也改成 503，单独装路由
    context = browser.new_context(viewport={'width': 1360, 'height': 900})
    page = context.new_page()
    page.add_init_script(TOUR_INIT + NOTICE_INIT)
    errors: list[str] = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    page.route('**/api/update/**', on_update)
    try:
        page.goto(base, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_selector('[data-action="check-update"]', timeout=20000)
        run(page)
        if errors:
            context_case.fail(f'页面 JS 报错：{errors[:2]}')
        if shots:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f'{case.name}.png'))
    except Exception as exc:  # noqa: BLE001
        context_case.fail(f'用例异常：{exc}')
    finally:
        context.close()
    return case


def case_source_mode(browser, base: str, shots: bool) -> Case:
    case = Case('source-mode')
    case.state['check'] = SOURCE_MODE

    def run(page):
        page.wait_for_timeout(2600)
        if page.locator('.update-card').is_visible():
            case.fail('源码模式不应自动弹更新卡片')
        page.click('[data-action="check-update"]')
        try:
            page.wait_for_selector('.update-toast', state='visible', timeout=5000)
        except Exception:  # noqa: BLE001
            case.fail('源码模式手动检查没有提示')
            return
        if '源码模式' not in page.locator('.update-toast').inner_text():
            case.fail('源码模式提示不正确')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_usage_notice(browser, base: str, shots: bool) -> Case:
    """首次打开必须看到匿名统计说明；点「保持开启」后本次不再弹，刷新也不再弹。"""
    case = Case('usage-notice')
    case.suppress_notice = False
    case.state['usageStatus'] = USAGE_ENABLED

    def run(page):
        try:
            page.wait_for_selector('.usage-dialog[open]', timeout=12000)
        except Exception:  # noqa: BLE001
            case.fail('首次打开没有出现匿名使用统计说明')
            return
        text = page.locator('.usage-card').inner_text()
        for needle in ('匿名使用统计', '会上报', '不会上报', '安装 ID', '关闭匿名统计'):
            if needle not in text:
                case.fail(f'说明里缺少「{needle}」')
        if shots:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / 'usage-notice.png'))
        page.click('[data-usage="keep"]')
        page.wait_for_timeout(300)
        if page.locator('.usage-dialog[open]').count():
            case.fail('点「继续使用」后说明没有关闭')
        stored = page.evaluate("() => localStorage.getItem('kpl-telemetry-notice-v1')")
        if stored != '1':
            case.fail('没有记住「已看过说明」')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(2800)
        if page.locator('.usage-dialog[open]').count():
            case.fail('刷新后又重复弹出说明')

    case.run = run
    run_case(browser, base, case, shots)
    return case


def case_usage_optout(browser, base: str, shots: bool) -> Case:
    """关闭 / 重新开启匿名统计：按钮要真的打到接口，页脚入口随时可再打开。"""
    case = Case('usage-optout')
    case.suppress_notice = False
    case.state['usageStatus'] = USAGE_ENABLED
    case.state['usageOptout'] = USAGE_DISABLED
    case.state['usageOptin'] = USAGE_ENABLED

    def run(page):
        try:
            page.wait_for_selector('.usage-dialog[open]', timeout=12000)
        except Exception:  # noqa: BLE001
            case.fail('首次打开没有出现匿名使用统计说明')
            return
        page.click('[data-usage="toggle"]')
        page.wait_for_timeout(700)
        if '/api/usage/optout' not in case.state['usageCalls']:
            case.fail('关闭统计没有请求 /api/usage/optout')
        if '已关闭' not in page.locator('[data-usage-state]').inner_text():
            case.fail('关闭后状态没有变成已关闭')
        page.click('[data-usage="close"]')
        page.wait_for_timeout(300)
        page.click('[data-action="usage-info"]')
        try:
            page.wait_for_selector('.usage-dialog[open]', timeout=5000)
        except Exception:  # noqa: BLE001
            case.fail('页脚「匿名统计」没有重新打开说明')
            return
        if '重新开启匿名统计' not in page.locator('.usage-card').inner_text():
            case.fail('关闭后没有提供重新开启入口')
        page.click('[data-usage="toggle"]')
        page.wait_for_timeout(700)
        if '/api/usage/optin' not in case.state['usageCalls']:
            case.fail('重新开启没有请求 /api/usage/optin')
        if '已开启' not in page.locator('[data-usage-state]').inner_text():
            case.fail('重新开启后状态没有变成已开启')

    case.run = run
    run_case(browser, base, case, shots)
    return case


CASES = [case_available, case_dismiss, case_blocked, case_apply,
         case_local_package, case_latest, case_offline, case_source_mode,
         case_usage_notice, case_usage_optout]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='工作台更新提示前端回归检查')
    parser.add_argument('--base', default='http://127.0.0.1:8766',
                        help='已启动的工作台地址')
    parser.add_argument('--no-shots', action='store_true', help='不保存截图')
    parser.add_argument('--only', help='只跑指定用例，逗号分隔')
    args = parser.parse_args(argv)
    base = args.base.rstrip('/')
    try:
        with urllib.request.urlopen(base + '/api/health', timeout=5) as response:
            if not json.loads(response.read().decode('utf-8')).get('ok'):
                raise ValueError('health 未返回 ok')
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f'工作台不可用（{base}）：{exc}', file=sys.stderr)
        return 2

    only = {item.strip() for item in (args.only or '').split(',') if item.strip()}
    selected = [factory for factory in CASES
                 if not only or factory.__name__.replace('case_', '') in only]
    started = time.time()
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for factory in selected:
                case = factory(browser, base, not args.no_shots)
                status = 'PASS' if not case.issues else 'FAIL'
                print(f'[{status}] {case.name}' + ('' if not case.issues else ' — ' + '；'.join(case.issues)))
                if case.issues:
                    failures.append({'case': case.name, 'issues': case.issues})
        finally:
            browser.close()
    summary = {
        'generatedAt': time.strftime('%Y-%m-%d %H:%M:%S'),
        'base': base,
        'elapsedSeconds': round(time.time() - started, 1),
        'total': len(selected),
        'passed': len(selected) - len(failures),
        'failed': len(failures),
        'failures': failures,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                      encoding='utf-8')
    print(f"\n{summary['passed']}/{summary['total']} 通过，用时 {summary['elapsedSeconds']}s")
    print(f'报告：{REPORT}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
