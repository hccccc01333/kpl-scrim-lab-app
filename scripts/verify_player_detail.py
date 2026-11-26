"""选手详情页的回归自查：切片交互 + 赛季量级压测。

用法：
    python scripts/verify_player_detail.py                 # 交互自查（默认数据）
    python scripts/verify_player_detail.py --stress        # 额外注入 612 局/43 天/126 英雄压测
    python scripts/verify_player_detail.py --player 信则有 --base http://127.0.0.1:8766

只读本地已启动的工作台，不改任何数据（压测用 Playwright 拦截接口响应，不落盘）。
退出码非 0 表示有失败项，可直接接进 CI。

背景：这一版把「每张卡各自一个分路下拉」换成了吸顶切片条，
图宽也改成按栏数反推。这个脚本盯的就是这两件事没退回旧毛病：
横向溢出、切片不联动、树图点击不生效、控制台报错。
"""
import argparse
import json
import random
import re
import sys
import time

from playwright.sync_api import sync_playwright

LANES = ['对抗路', '打野', '中路', '发育路', '游走']

OVERFLOW_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('.pv-panel, .pdx-card, .pv-tm, .pv-colwrap')) {
    const r = el.getBoundingClientRect();
    if (el.scrollWidth - Math.round(r.width) > 2) out.push(String(el.className).slice(0, 30));
  }
  return out;
}"""

HIT_JS = 'el => el.innerText.replace(/\\s+/g, " ").trim()'


def day_add(day, n):
    import datetime as dt
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def build_big(detail, replicas):
    """把 8 天 102 局扩成 ~45 天 600 局、100+ 个英雄，模拟一个赛季的数据量。"""
    rows = detail.get('rows') or []
    meta = detail.get('heroMeta') or {}
    heroes = list(meta.keys()) or ['项羽']
    rnd = random.Random(20261117)
    out = []
    for k in range(replicas):
        for r in rows:
            item = dict(r)
            day = str(r.get('day') or r.get('at') or '')[:10]
            item['day'] = day_add(day, 7 * k) if day else day
            item['at'] = (item['day'] + str(r.get('at') or '')[10:]) if r.get('at') else item['day']
            if k and rnd.random() < 0.55:
                hero = rnd.choice(heroes)
                item['hero'] = hero
                item['heroDefaultLane'] = (meta.get(hero) or {}).get('lane') or item.get('heroDefaultLane')
            if rnd.random() < 0.12:
                item['lane'] = rnd.choice(LANES)
            item['gameId'] = f"{r.get('gameId')}-{k}"
            item['rating'] = round(max(0.0, min(16.0, (r.get('rating') or 8) + rnd.uniform(-1.4, 1.4))), 1)
            item['result'] = 'win' if rnd.random() < 0.55 else 'loss'
            item['mvp'] = rnd.random() < 0.18
            out.append(item)
    big = dict(detail)
    big['rows'] = out
    return big, len(out)


def with_kpl_metric_fixture(body):
    """给浏览器回归注入详细 KPL 字段，不依赖本地是否已全量回填。"""
    body = dict(body)
    fields = ['winRate', 'heroWinRate', 'kda', 'participation', 'assists',
              'gpm', 'dpm', 'hdpm', 'dtpm', 'taken']
    body['fields'] = fields
    lanes = dict(body.get('lanes') or {})
    for cell in lanes.values():
        games = cell.get('games') or 0
        cell['samples'] = {'winRate': games, 'heroWinRate': cell.get('heroWinSamples') or 0,
                           'kda': games, 'participation': games, 'assists': games,
                           'gpm': games, 'dpm': games, 'hdpm': games, 'dtpm': games, 'taken': games}
        cell.update({'kda': 3.2, 'participation': 72.5, 'assists': 6.4,
                     'gpm': 620, 'dpm': 780, 'hdpm': 510, 'dtpm': 1150, 'taken': 16800})
    body['lanes'] = lanes
    return body


class Checker:
    def __init__(self):
        self.failed = 0
        self.passed = 0

    def check(self, name, cond, detail=''):
        if cond:
            self.passed += 1
            print(f'PASS {name}' + (f'  [{detail}]' if detail else ''))
        else:
            self.failed += 1
            print(f'FAIL {name}' + (f'  [{detail}]' if detail else ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--player', default='信则有')
    ap.add_argument('--stress', action='store_true', help='注入赛季量级数据再跑一遍')
    ap.add_argument('--replicas', type=int, default=6)
    args = ap.parse_args()
    url = f"{args.base}/#playerdetail/{args.player}"
    ck = Checker()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.add_init_script("try{localStorage.setItem('training-tour-complete-v3','1');"
                             "localStorage.setItem('pdx.fold','[]');}catch(e){}")
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:200]))
        page.on('console', lambda m: errs.append(f'console:{m.text[:160]}') if m.type == 'error' else None)

        state = {'detail': None}

        def handle_kpl_baseline(route):
            resp = route.fetch()
            body = with_kpl_metric_fixture(resp.json())
            route.fulfill(response=resp, body=json.dumps(body, ensure_ascii=False))

        page.route('**/api/v3/kpl/lane-baseline*', handle_kpl_baseline)
        if args.stress:
            def handle(route):
                resp = route.fetch()
                body = resp.json()
                if state['detail'] is None:
                    state['detail'], n = build_big(body, args.replicas)
                    days = len({r['day'] for r in state['detail']['rows']})
                    heroes = len({r['hero'] for r in state['detail']['rows']})
                    print(f'— 压测数据：{n} 局 / {days} 个训练日 / {heroes} 个英雄')
                    route.fulfill(response=resp, body=json.dumps(state['detail'], ensure_ascii=False))
                else:
                    route.fulfill(response=resp, body=json.dumps(state['detail'], ensure_ascii=False))
            page.route('**/api/v3/player-detail*', handle)

        t0 = time.time()
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_selector('.pdx-scope', timeout=45000)
        page.wait_for_timeout(1500)
        print(f'— 首屏 {time.time() - t0:.1f}s')

        hit = lambda: page.eval_on_selector('.pdx-hit', HIT_JS)
        over = lambda: page.evaluate(OVERFLOW_JS)

        card_count = page.eval_on_selector_all('.pdx-card', 'e => e.length')
        ck.check('首屏分析卡完整', card_count >= 8, card_count)
        ck.check('首屏无横向溢出', not over(), over())

        lanes = page.eval_on_selector('[data-pdx-select="lane"]', 'el => [...el.options].map(o => o.value)')
        page.select_option('[data-pdx-select="lane"]', lanes[1])
        page.wait_for_timeout(400)
        ck.check('分路切片生效', '清除切片' in hit(), hit())
        ck.check('切片后无横向溢出', not over(), over())

        heroes = page.eval_on_selector('[data-pdx-select="hero"]',
                                       'el => [...el.options].map(o => o.value).filter(Boolean)')
        page.select_option('[data-pdx-select="hero"]', heroes[0])
        page.wait_for_timeout(400)
        ck.check('英雄切片生效（只剩 1 个英雄）', '1 英雄' in hit(), hit())
        ck.check('切片写进 URL', 'hero=' in page.url, page.url.split('?')[-1][:60])

        page.select_option('[data-pdx-select="res"]', 'win')
        page.wait_for_timeout(350)
        ck.check('结果切片生效（当前样本筛空）', '0 局' in hit(), hit())

        page.click('.pdx-hit .pv-reset')
        page.wait_for_timeout(400)
        ck.check('清除切片恢复全量', '清除切片' not in hit(), hit())

        page.select_option('[data-pdx-select="benchSource"]', 'kpl')
        page.wait_for_timeout(350)
        kpl_metrics = page.eval_on_selector(
            '[data-pdx-select="bench"]', 'el => [...el.options].map(o => o.value)')
        ck.check('KPL 对标开放详细指标', all(key in kpl_metrics for key in
                 ('participation', 'assists', 'dtpm', 'taken')), kpl_metrics)
        for value, label in (('participation', '参团率'), ('assists', '助攻'), ('dtpm', '分均承伤')):
            page.select_option('[data-pdx-select="bench"]', value)
            page.wait_for_timeout(250)
            selected = page.eval_on_selector(
                '[data-pdx-select="bench"]', 'el => el.selectedOptions[0].textContent')
            chart = page.get_by_role('img', name=re.compile(rf'^{label}：本人'))
            ck.check(f'KPL {label}图表联动', selected == label and chart.count() == 1,
                     f'{selected} / charts={chart.count()}')
        page.select_option('[data-pdx-select="benchSource"]', '')
        page.wait_for_timeout(300)

        tile = page.query_selector('.pv-tm-tile[data-pdx-set]')
        if ck.check('树图方块是按钮', tile is not None) and tile:
            name = tile.get_attribute('data-pdx-set').split(':', 1)[1]
            tile.click()
            page.wait_for_timeout(400)
            val = page.eval_on_selector('[data-pdx-select="hero"]', 'el => el.value')
            ck.check('点树图切到该英雄', val == name, f'{val} vs {name}')

        page.click('[data-hero-scroll="3"]')
        page.wait_for_timeout(700)
        ck.check('模块跳转改变滚动位置', page.evaluate('() => window.scrollY') > 200)

        if args.stress:
            # 门槛筛空：挑一个出场最少的英雄（下拉最后一项），再要求 ≥5 局
            page.select_option('[data-pdx-select="range"]', 'all')
            page.select_option('[data-pdx-select="lane"]', '全部')
            last = page.eval_on_selector('[data-pdx-select="hero"]',
                                         'el => { const o = [...el.options].pop(); return [o.value, o.textContent]; }')
            import re as _re
            games = int((_re.search(r'(\d+) 局', last[1]) or [0, 99])[1])
            if last[0] and games < 5:
                page.select_option('[data-pdx-select="hero"]', last[0])
                page.wait_for_timeout(300)
                page.select_option('[data-pdx-select="min"]', '5')
                page.wait_for_timeout(350)
                ck.check('门槛筛空时给空状态', page.query_selector('.pv-empty2') is not None,
                         f'{last[1]} × 门槛 ≥5 局')
            page.select_option('[data-pdx-select="hero"]', '')
            page.select_option('[data-pdx-select="min"]', '1')
            page.wait_for_timeout(400)
            ck.check('赛季量级下仍无横向溢出', not over(), over())
            page.screenshot(path='.screenshots/pd/pd-stress.png', full_page=True)

        ck.check('无 JS 报错', not errs, errs[:3])
        browser.close()

    print(f'\n通过 {ck.passed} 项，失败 {ck.failed} 项')
    return 0 if ck.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
