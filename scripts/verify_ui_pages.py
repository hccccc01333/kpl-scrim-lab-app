"""统一平台逐页截图验收 + 版面探针 + 交互抽查。

覆盖「下一轮」清单里的数据集、数据清洗、字段与来源、批量导入、分析报告、
统计实验、模型实验、身份绑定、战队名单、对手档案（含下钻页），外加筛选 /
下钻 / 弹窗 / 打印四类交互。

用法（需 Python 3.12 环境，已装 playwright）：
    python scripts/verify_ui_pages.py
    python scripts/verify_ui_pages.py --desktop-only
    python scripts/verify_ui_pages.py --only datasets,clean
    python scripts/verify_ui_pages.py --no-interactions

独立端口 + 临时比赛库 + 临时研究结果库（STUDIO_RESULTS_DB），自带少量样本数据，
不读写用户数据、不依赖 OCR 夹具。输出 test-results/ui-pages-report.json 与
test-results/ui-pages/ 下的截图。有 critical 问题时退出码 1，可接入 CI。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'test-results'
SHOTS = OUT / 'ui-pages'
REPORT = OUT / 'ui-pages-report.json'

# (hash, 文件名, 中文名)。对手档案走 #team 的 scouting 标签，单独处理
PAGES = [
    ('#datasets', 'datasets', '数据集'),
    ('#clean', 'clean', '数据清洗'),
    ('#sources', 'sources', '字段与来源'),
    ('#import', 'import', '批量导入'),
    ('#lab', 'lab', '统计实验'),
    ('#models', 'models', '模型实验'),
    ('#identity', 'identity', '身份绑定'),
    ('#roster', 'roster', '战队名单'),
    ('#team', 'team-scouting', '对手档案'),
]

VIEWPORTS = [
    ('desktop', {'width': 1440, 'height': 900}),
    ('mobile', {'width': 390, 'height': 844}),
]

READY = """() => {
  const main = document.querySelector('#content');
  const t = (main ? main.innerText : '').trim();
  if (/^(正在读取|正在打开|正在获取|加载中|正在加载|loading)/i.test(t)) return false;
  return t.length >= 60;
}"""

# 版面探针：把上一轮人工发现的四类排版 bug 变成可自动复验的信号。
# 输出的是「可疑项」，不直接判 fail；配合截图人工确认。
LAYOUT_PROBE = r"""() => {
  const main = document.querySelector('#content');
  if (!main) return {issues: ['no_main'], squeezed: 0, clipped: 0, stretched: 0,
                     offscreen: 0, table_misalign: 0, uneven_cards: 0, card_clip: 0};
  const issues = [];
  const vw = window.innerWidth;
  let squeezed = 0, clipped = 0, stretched = 0, offscreen = 0, card_clip = 0;
  const samples = {squeezed: [], clipped: [], stretched: [], offscreen: [], card_clip: []};
  const skipTag = new Set(['TABLE','THEAD','TBODY','TR','SELECT','INPUT','SVG','PATH']);
  for (const el of main.querySelectorAll('h1,h2,h3,h4,strong,b,span,td,th,button,a,p,label,small')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    const txt = (el.innerText || '').trim();
    // 中文标题被挤成竖排：窄而高、字数不多、非竖排书写模式
    if (/[\u4e00-\u9fa5]/.test(txt) && txt.length >= 2 && txt.length <= 14 &&
        r.width < 32 && r.height > r.width * 1.8 &&
        cs.writingMode === 'horizontal-tb' && !skipTag.has(el.tagName)) {
      squeezed++;
      if (samples.squeezed.length < 4) samples.squeezed.push(txt.slice(0, 14));
    }
    // 文本被容器裁掉（排除有意 ellipsis 与可滚动表格）
    if (cs.overflowX === 'hidden' && el.clientWidth > 40 &&
        el.scrollWidth > el.clientWidth + 6 && !skipTag.has(el.tagName) &&
        cs.textOverflow !== 'ellipsis') {
      clipped++;
      if (samples.clipped.length < 4) samples.clipped.push(
        el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 24));
    }
    // 栅格/弹性容器里的按钮被拉成整列宽
    if (el.tagName === 'BUTTON' && r.width > 320) {
      const p = el.parentElement;
      if (p && p.clientWidth > 0 && r.width > p.clientWidth * 0.94) {
        stretched++;
        if (samples.stretched.length < 4) samples.stretched.push(
          (el.id ? '#' + el.id : '') + '.' + (el.className || '').toString().slice(0, 24) +
          ':' + txt.slice(0, 10) + ':' + Math.round(r.width));
      }
    }
    // 元素右边界越过视口；横向可滚动容器（表格等）内的越界属正常，不算缺陷
    if (r.right > vw + 3 && r.width < vw * 1.5 &&
        cs.position !== 'fixed' && !skipTag.has(el.tagName)) {
      let p = el.parentElement, scrollable = false;
      while (p && p !== main) {
        const pcs = getComputedStyle(p);
        if (/(auto|scroll)/.test(pcs.overflowX) && p.scrollWidth > p.clientWidth + 4) {
          scrollable = true; break;
        }
        p = p.parentElement;
      }
      if (!scrollable) {
        offscreen++;
        if (samples.offscreen.length < 4) samples.offscreen.push(
          el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 24));
      }
    }
  }
  // 表头与首行数值列的 text-align 一致性
  let table_misalign = 0;
  for (const table of main.querySelectorAll('table')) {
    const heads = Array.from(table.querySelectorAll('thead th'));
    const firstRow = table.querySelector('tbody tr');
    if (!heads.length || !firstRow) continue;
    const cells = Array.from(firstRow.querySelectorAll('td'));
    heads.forEach((th, i) => {
      if (!cells[i]) return;
      const a = getComputedStyle(th).textAlign, b = getComputedStyle(cells[i]).textAlign;
      if (a !== b && (a === 'right' || b === 'right')) table_misalign++;
    });
  }
  // 卡片内文字越过卡片右边界（如对手卡片胜率数字被裁）
  for (const card of main.querySelectorAll('.opponent-card,.research-card,.scenario-card,.next-card,.home-card')) {
    const cr = card.getBoundingClientRect();
    if (cr.width < 40) continue;
    for (const child of card.querySelectorAll('b,strong,span,h3,em')) {
      const r = child.getBoundingClientRect();
      if (r.width > 0 && r.right > cr.right + 1) {
        card_clip++;
        if (samples.card_clip.length < 4) samples.card_clip.push(
          (card.className || '').split(' ')[0] + '>' + child.tagName.toLowerCase() +
          ':' + (child.innerText || '').trim().slice(0, 12));
        break;
      }
    }
  }
  // 同一网格里的卡片高度是否齐平（排除明确设了 auto 的容器）
  let uneven_cards = 0;
  for (const grid of main.querySelectorAll('.research-card-grid,.capture-sources,.next-grid,.opponent-grid,.scenario-grid,.home-card-grid')) {
    const cs = getComputedStyle(grid);
    if (!cs.display.includes('grid') || cs.alignItems === 'stretch') continue;
    const kids = Array.from(grid.children).filter(k => k.getBoundingClientRect().height > 20);
    if (kids.length < 2) continue;
    const hs = kids.map(k => k.getBoundingClientRect().height);
    if (Math.max(...hs) - Math.min(...hs) > 10) uneven_cards++;
  }
  const doc = document.documentElement;
  const overflow_x = doc.scrollWidth > vw + 2;
  if (overflow_x) issues.push('overflow_x');
  if (squeezed) issues.push('squeezed_text');
  if (clipped) issues.push('clipped_text');
  if (stretched) issues.push('stretched_button');
  if (offscreen) issues.push('offscreen_element');
  if (table_misalign) issues.push('table_misalign');
  if (uneven_cards) issues.push('uneven_cards');
  if (card_clip) issues.push('card_clip');
  return {issues, squeezed, clipped, stretched, offscreen,
          table_misalign, uneven_cards, card_clip, overflow_x,
          scroll_width: doc.scrollWidth, inner_width: vw,
          content_len: (main.innerText || '').trim().length,
          error_banner: /无法连接本地服务|Internal Server Error|not valid JSON|读取失败|加载失败/i.test(main.innerText || ''),
          has_heading: !!main.querySelector('h1'),
          has_panel: !!main.querySelector('.panel, .research-card, .empty-state'),
          samples};
}"""


def api(base, method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw.strip().startswith(('{', '[')) else raw


def wait_server(base, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + '/api/state', timeout=1)
            return True
        except OSError:
            time.sleep(0.15)
    return False


def seed(base):
    """造少量真实记录，让卡片网格、下钻、弹窗与筛选都有对象可点。"""
    notes = []
    roster = [{'id': str(i), 'name': n, 'position': p} for i, (n, p) in enumerate(
        [('青山', '对抗路'), ('归舟', '打野'), ('长风', '中路'),
         ('听雨', '发育路'), ('明川', '游走')])]
    api(base, 'PUT', '/api/settings', {'teamName': '验收样本队', 'roster': roster})

    heroes = ['孙悟空', '吕布', '小乔', '后羿', '张飞', '李白', '妲己', '廉颇', '鲁班七号', '貂蝉']
    opponents = ['星河战队', '北境战队', '晨曦战队']
    created = 0
    start = datetime(2026, 10, 18).date()
    for g in range(6):
        date = (start + timedelta(days=g * 3)).isoformat()
        winner = 'right' if g % 3 != 1 else 'left'
        players = []
        for side in ('left', 'right'):
            for i in range(5):
                row = {
                    'side': side, 'slot': i,
                    'playerId': str(i) if side == 'right' else '',
                    'hero': heroes[(g + i + (0 if side == 'right' else 5)) % len(heroes)],
                    'kills': str(2 + (g + i) % 6), 'deaths': str(1 + (g + i) % 4),
                    'assists': str(3 + (g + i) % 9),
                    'gold': '%d' % (9000 + g * 700 + i * 420),
                    'damage': '%dk' % (38 + (g + i) % 22),
                    'taken': '%dk' % (24 + (g + i) % 16),
                    'participation': '%d%%' % (48 + (g + i) % 40),
                    'rating': '%.1f' % (6.2 + (g + i) % 10 * 0.35),
                }
                players.append(row)
        match = {
            'id': 'ui-seed-%02d' % g, 'status': 'confirmed', 'reviewed': True,
            'side': 'right', 'winner': winner, 'date': date,
            'opponent': opponents[g % len(opponents)],
            'scores': {'left': '', 'right': ''}, 'imageIds': [], 'players': players,
        }
        try:
            api(base, 'POST', '/api/matches', match)
            created += 1
        except urllib.error.HTTPError as exc:
            notes.append('样本比赛 %d 未入库: HTTP %s %s' % (
                g, exc.code, exc.read().decode('utf-8', 'replace')[:120]))
    notes.append('样本比赛 %d/6 局' % created)

    # 报告卡片：走备份恢复接口，结构满足 kpl-studio-backup-v1 校验
    def result(method, matches, rows):
        return {'schema': 'kpl-studio-result-v1', 'status': 'ok',
                'meta': {'engineVersion': 'studio-1', 'method': method,
                         'metrics': ['gold'], 'rows': len(rows), 'inputRows': len(rows),
                         'matches': matches, 'fingerprint': 'ui-seed-fp',
                         'duplicates': [], 'generatedAt': datetime.now().isoformat(),
                         'warnings': []},
                'columns': ['label', 'mean'], 'rows': rows,
                'spec': {'method': method}}

    reports = [
        {'id': 'ui-seed-report-1', 'title': '前期经济节奏复盘',
         'note': '验收用样本：10 月训练赛六局的前期经济差。',
         'createdAt': '2026-11-01T10:00:00',
         'result': result('describe', 6, [{'label': '本队', 'mean': 11800},
                                          {'label': '对手', 'mean': 11240}])},
        {'id': 'ui-seed-report-2', 'title': '输出与经济相关性',
         'note': '验收用样本：检验输出占比与经济占比的关系。',
         'createdAt': '2026-11-03T16:30:00',
         'result': result('correlation', 6, [{'label': 'pearson', 'mean': 0.71},
                                            {'label': 'spearman', 'mean': 0.68}])},
    ]
    try:
        from studio_pipeline import fingerprint
        ds_rows = [{'matchKey': 'ui-seed-%02d' % g, 'label': roster[g % 5]['name'],
                    'gold': 9000 + g * 700, 'damage': 38000 + g * 1500} for g in range(6)]
        body = {'schema': 'kpl-prepared-dataset-v1', 'rows': ds_rows,
                'fingerprint': fingerprint(ds_rows), 'exploratory': False,
                'before': {'rows': 6, 'matches': 6}, 'after': {'rows': 6, 'matches': 6},
                'rules': {'trim': True, 'deduplicate': True}, 'logs': []}
        datasets = [{'id': 'ui-seed-dataset-1', 'title': '十月训练赛清洗快照',
                     'createdAt': '2026-11-02T09:00:00', 'body': body}]
    except Exception as exc:
        datasets = []
        notes.append('数据集样本构造跳过: %s' % str(exc)[:120])
    try:
        restored = api(base, 'POST', '/api/studio/restore',
                       {'schema': 'kpl-studio-backup-v1', 'datasets': datasets,
                        'reports': reports})
        notes.append('研究报告 %d 条 / 数据集 %d 条' % (
            restored.get('added', 0), (restored.get('datasets') or {}).get('added', 0)))
    except urllib.error.HTTPError as exc:
        notes.append('研究记录恢复失败: HTTP %s %s' % (
            exc.code, exc.read().decode('utf-8', 'replace')[:160]))
    try:
        api(base, 'POST', '/api/analysis/reload', {})
    except Exception as exc:
        notes.append('分析数据刷新跳过: %s' % str(exc)[:100])
    return notes


def attach_errors(page):
    bucket = {'js_errors': [], 'console_errors': [], 'http_errors': []}
    page.on('pageerror', lambda e: bucket['js_errors'].append(str(e)[:300]))
    page.on('console', lambda m: bucket['console_errors'].append(m.text[:200])
            if m.type == 'error' else None)
    page.on('response', lambda r: bucket['http_errors'].append('%s %s' % (
        r.status, r.url.split('/api/')[-1][:120]))
        if r.status >= 400 and '/api/' in r.url else None)
    return bucket


def audit_page(context, base, route, slug, label, vp_name, take_shot):
    page = context.new_page()
    bucket = attach_errors(page)
    try:
        page.goto(base + '/studio' + route, wait_until='domcontentloaded', timeout=25000)
        # 先等主内容就绪，否则标签栏还没渲染，点击会静默落空
        try:
            page.wait_for_function(READY, timeout=9000)
        except Exception:
            pass
        if route in ('#lab', '#models'):
            # 统计/模型实验的高级设置是主要操作区，展开后再截图验收
            adv = page.locator('.lab-advanced')
            if adv.count():
                adv.first.evaluate('e => e.open = true')
                page.wait_for_timeout(350)
        if route == '#team':
            # 对手档案：切到 scouting 标签，并确认激活态，避免把默认「经济节奏」页当对手档案验收
            tab = page.locator('[data-team-tab="scouting"]')
            if tab.count():
                tab.first.click()
                try:
                    page.wait_for_function(
                        "() => !!document.querySelector('[data-team-tab=\"scouting\"].active')",
                        timeout=6000)
                except Exception:
                    pass
                page.wait_for_timeout(450)
        try:
            page.wait_for_function(READY, timeout=9000)
        except Exception:
            pass
        page.wait_for_timeout(250)
        layout = page.evaluate(LAYOUT_PROBE)
        case = {'route': route, 'slug': slug, 'label': label, 'viewport': vp_name,
                **layout, **bucket}
        if take_shot:
            SHOTS.mkdir(parents=True, exist_ok=True)
            name = '%s-%s.png' % (vp_name, slug)
            try:
                page.screenshot(path=str(SHOTS / name), full_page=True)
                case['screenshot'] = str((SHOTS / name).relative_to(ROOT))
            except Exception as exc:
                case['shot_error'] = str(exc)[:150]
        # critical = 客观故障；版面探针项只作 warn，需人工看图确认
        critical = []
        if bucket['js_errors']:
            critical.append('js_error')
        if bucket['http_errors']:
            critical.append('http_error')
        if layout['error_banner']:
            critical.append('error_banner')
        if layout['overflow_x']:
            critical.append('overflow_x')
        if layout['content_len'] < 60:
            critical.append('blank_page')
        if not layout['has_heading']:
            critical.append('no_heading')
        case['critical'] = critical
        case['status'] = 'critical' if critical else 'warn' if layout['issues'] else 'pass'
        return case
    finally:
        page.close()


DOM_SUMMARY = """() => {
  const main = document.querySelector('#content');
  const text = (main ? main.innerText : '').trim().replace(/\\s+/g, ' ');
  const links = Array.from(main ? main.querySelectorAll('a[href]') : []);
  return {
    text: text.slice(0, 260),
    links: links.length,
    hrefs: links.slice(0, 10).map(a => a.getAttribute('href')),
    buttons: main ? main.querySelectorAll('button').length : 0,
    ids: ['filter-from','apply-filters','detail-dialog','detail-body']
      .filter(i => !!document.getElementById(i))
  };
}"""


def skip(reason):
    """跳过不算通过：单独标记，并附 DOM 摘要以便排查是选择器还是数据问题。"""
    return {'skip': True, 'detail': reason}


def check(name, fn, page=None):
    def dom():
        try:
            return page.evaluate(DOM_SUMMARY) if page else None
        except Exception:
            return None
    try:
        detail = fn()
        if isinstance(detail, dict) and detail.get('skip'):
            return {'name': name, 'ok': True, 'skipped': True,
                    'detail': detail['detail'], 'dom': dom()}
        return {'name': name, 'ok': True, 'skipped': False, 'detail': detail}
    except Exception as exc:
        return {'name': name, 'ok': False, 'skipped': False,
                'detail': str(exc)[:300], 'dom': dom()}


def interactions(context, base, take_shot):
    results = []
    page = context.new_page()
    bucket = attach_errors(page)
    SHOTS.mkdir(parents=True, exist_ok=True)

    def goto(route):
        page.goto(base + '/studio' + route, wait_until='domcontentloaded', timeout=25000)
        page.wait_for_function(READY, timeout=9000)
        page.wait_for_timeout(250)

    def shot(name):
        if take_shot:
            page.screenshot(path=str(SHOTS / name), full_page=False)

    # 1) 筛选：高级设置里改日期并应用，确认筛选状态回填且页面无报错
    def do_filter():
        goto('#lab')
        adv = page.locator('.lab-advanced')
        if adv.count() and not adv.first.evaluate('e => e.open'):
            adv.first.evaluate('e => e.open = true')
            page.wait_for_timeout(200)
        box = page.locator('#filter-from')
        if not box.count():
            return skip('本页无 #filter-from，需确认高级设置展开方式')
        box.fill('2026-10-20')
        page.locator('#apply-filters').click()
        page.wait_for_timeout(600)
        value = page.locator('#filter-from').input_value()
        if value != '2026-10-20':
            raise AssertionError('筛选状态未回填：%r' % value)
        shot('interaction-filter.png')
        return '日期筛选 2026-10-20 应用后状态回填正常'
    results.append(check('筛选：统计实验日期筛选', do_filter, page))

    # 2) 下钻：选手列表 → 选手详情；英雄列表 → 英雄详情
    def do_drill(kind):
        root = '#players' if kind == 'player' else '#heroes'
        goto(root)
        link = page.locator('a[href^="#%s/"]' % kind).first
        if not link.count():
            return skip('%s 列表无 a[href^="#%s/"]' % (root, kind))
        href = link.get_attribute('href')
        link.click()
        page.wait_for_timeout(700)
        if not page.url.split('#')[-1].startswith(kind + '/'):
            raise AssertionError('未进入详情：%s / %s' % (page.url, href))
        heading = page.locator('#content h1').first.inner_text().strip()
        if not heading:
            raise AssertionError('详情标题为空')
        shot('interaction-%s-drill.png' % kind)
        return '%s → %s，标题「%s」' % (root, href, heading[:32])
    results.append(check('下钻：选手详情', lambda: do_drill('player'), page))
    results.append(check('下钻：英雄详情', lambda: do_drill('hero'), page))

    # 3) 下钻：团队复盘 → 对手档案标签 → 对手下钻
    def do_opponent():
        goto('#team')
        tab = page.locator('[data-team-tab="scouting"]')
        if tab.count():
            tab.first.click()
            page.wait_for_timeout(400)
        card = page.locator('a[href^="#opponent/"]').first
        if not card.count():
            return skip('对手档案标签下无 a[href^="#opponent/"]')
        href = card.get_attribute('href')
        card.click()
        page.wait_for_timeout(700)
        if 'opponent/' not in page.url:
            raise AssertionError('未进入对手档案下钻：%s' % page.url)
        shot('interaction-opponent-drill.png')
        return '团队复盘 → %s' % href
    results.append(check('下钻：对手档案', do_opponent, page))

    # 4) 弹窗：分析报告页已从导航移除，详情弹窗由单局页承载
    def do_dialog():
        return skip('分析报告已移除，详情弹窗改由单局页承载')
    results.append(check('弹窗：分析报告详情', do_dialog, page))

    # 5) 打印：打印媒体下隐藏导航与按钮、正文保留、无横向溢出
    def do_print():
        goto('#team')
        page.emulate_media(media='print')
        page.wait_for_timeout(300)
        hidden = page.evaluate("""() => {
          const sel = ['.app-navigation','.topbar','.heading-actions','.footer'];
          return sel.map(s => {
            const e = document.querySelector(s);
            return {s, present: !!e, display: e ? getComputedStyle(e).display : 'absent'};
          });
        }""")
        shown = [h['s'] for h in hidden
                 if h['present'] and h['display'] not in ('none', 'absent')]
        if shown:
            raise AssertionError('打印样式未隐藏：%s' % ','.join(shown))
        probe = page.evaluate(LAYOUT_PROBE)
        if probe['overflow_x']:
            raise AssertionError('打印视图横向溢出 %d > %d' % (
                probe['scroll_width'], probe['inner_width']))
        if probe['content_len'] < 60:
            raise AssertionError('打印视图正文丢失')
        shot('interaction-print.png')
        page.emulate_media(media='screen')
        return '导航/按钮已隐藏，正文 %d 字，无横向溢出' % probe['content_len']
    results.append(check('打印：分析报告打印样式', do_print, page))

    page.close()
    return {'cases': results, 'js_errors': bucket['js_errors'],
            'console_errors': bucket['console_errors'],
            'http_errors': bucket['http_errors']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='')
    ap.add_argument('--desktop-only', action='store_true')
    ap.add_argument('--no-shots', action='store_true')
    ap.add_argument('--no-interactions', action='store_true')
    ap.add_argument('--only', default='', help='只跑指定 slug，逗号分隔')
    ap.add_argument('--server-log', action='store_true',
                    help='把服务端 stderr 写入 test-results/ui-pages-server.log 便于排查 500')
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    pages = PAGES
    if args.only:
        wanted = [x.strip() for x in args.only.split(',') if x.strip()]
        pages = [p for p in PAGES if p[1] in wanted]

    server = None
    base = args.base.rstrip('/')
    if not base:
        # 与 verify_platform_page.py(8772)、verify_frontend.py(8771) 错开，便于并行回归
        base = 'http://127.0.0.1:8773'
        tag = uuid.uuid4().hex[:10]
        db = OUT / ('ui-pages-%s.sqlite3' % tag)
        results_db = OUT / ('ui-pages-studio-%s.sqlite3' % tag)
        env = dict(os.environ, TRAINING_PORT='8773', TRAINING_DB=str(db),
                   STUDIO_RESULTS_DB=str(results_db), TRAINING_ALLOW_REMOTE='',
                   PYTHONIOENCODING='utf-8')
        log_stream = (open(OUT / 'ui-pages-server.log', 'w', encoding='utf-8')
                      if args.server_log else subprocess.DEVNULL)
        server = subprocess.Popen(
            [sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT), env=env,
            stdout=log_stream, stderr=log_stream,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not wait_server(base):
            server.terminate()
            raise SystemExit('验收服务未能启动：%s' % base)

    seed_notes = []
    try:
        try:
            seed_notes = seed(base)
        except Exception as exc:
            seed_notes = ['样本数据构造异常：%s' % str(exc)[:200]]
        print('样本数据：%s' % '；'.join(seed_notes), flush=True)

        viewports = VIEWPORTS[:1] if args.desktop_only else VIEWPORTS
        cases = []
        inter = {'cases': [], 'js_errors': [], 'console_errors': [], 'http_errors': []}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for vp_name, vp in viewports:
                context = browser.new_context(viewport=vp, device_scale_factor=1)
                for idx, (route, slug, label) in enumerate(pages, 1):
                    case = audit_page(context, base, route, slug, label, vp_name,
                                      not args.no_shots)
                    cases.append(case)
                    print('[%s %d/%d] %-16s %-9s %s' % (
                        vp_name, idx, len(pages), slug, case['status'],
                        ','.join(case['issues']) or case['critical'] or 'ok'), flush=True)
                if not args.no_interactions and vp_name == 'desktop':
                    inter = interactions(context, base, not args.no_shots)
                    for item in inter['cases']:
                        state = 'FAIL' if not item['ok'] else 'SKIP' if item.get('skipped') else 'PASS'
                        print('[交互] %-24s %-4s %s' % (
                            item['name'], state, str(item['detail'])[:110]), flush=True)
                        if state != 'PASS':
                            print('       DOM: %s' % json.dumps(
                                item.get('dom'), ensure_ascii=False)[:420], flush=True)
                context.close()
            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()

    critical = sum(1 for c in cases if c['critical'])
    failed_inter = sum(1 for c in inter['cases'] if not c['ok'])
    summary = {
        'pages': len(pages), 'cases': len(cases),
        'pass': sum(1 for c in cases if c['status'] == 'pass'),
        'warn': sum(1 for c in cases if c['status'] == 'warn'),
        'critical': critical,
        'js_errors': sum(1 for c in cases if c['js_errors']) + len(inter['js_errors']),
        'http_errors': sum(1 for c in cases if c['http_errors']) + len(inter['http_errors']),
        'error_banners': sum(1 for c in cases if c.get('error_banner')),
        'overflow': sum(1 for c in cases if c['overflow_x']),
        'layout_signals': {k: sum(1 for c in cases if c.get(k))
                           for k in ('squeezed', 'clipped', 'stretched', 'offscreen',
                                     'table_misalign', 'uneven_cards', 'card_clip')},
        'interactions': len(inter['cases']), 'interaction_failed': failed_inter,
        'interaction_skipped': sum(1 for c in inter['cases'] if c.get('skipped')),
        'interaction_passed': sum(1 for c in inter['cases']
                                  if c['ok'] and not c.get('skipped')),
    }
    report = {'generated_at': datetime.now().isoformat(timespec='seconds'),
              'base': base, 'viewports': [v[0] for v in viewports],
              'seed_notes': seed_notes, 'summary': summary,
              'cases': cases, 'interactions': inter}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding='utf-8')
    print('\n汇总：%s' % json.dumps(summary, ensure_ascii=False))
    print('报告：%s' % REPORT)
    return 1 if critical or failed_inter else 0


if __name__ == '__main__':
    sys.exit(main())
