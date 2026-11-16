#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""战队页 v2 浏览器验收脚本（QA 独立验收，只读，不改产品代码）。

契约：docs/team_page_v2.md

用法（Windows，项目根目录）：
    .venv-oss\\Scripts\\python.exe scripts\\verify_team_page.py --out .screenshots/team-v2
    .venv-oss\\Scripts\\python.exe scripts\\verify_team_page.py --desktop --mobile --out .screenshots/team-v2
    # 改造前基线：只记录现状，不因断言失败返回非 0
    .venv-oss\\Scripts\\python.exe scripts\\verify_team_page.py --baseline --out .screenshots/team-v2-before
    # 对临时服务验收
    .venv-oss\\Scripts\\python.exe scripts\\verify_team_page.py --base http://127.0.0.1:8799 --out .audit-shots/team-v2-8799

检查内容：
  1. 浏览器（playwright / chromium，禁用缓存）打开 #team/<teamId>，1440 桌面 + 390 手机两种宽度；
  2. console error / pageerror / 失败请求（4xx/5xx）收集；
  3. 全页 + 关键段截图；
  4. 页面文本断言：v3 五段存在、已删除面板不存在、统计禁词不存在、分路对位不出现 KDA；
  5. 交互冒烟：英雄池分路筛选、四象限时间窗，断言区域文本或 class 变化；
  6. 页面布局：无横向溢出；
  7. 数据自检：GET /api/v3/team-deep 校验经济占比合计≈100%、四象限与逐局一致、窗口计数、
     窗口下界=锚点-(N-1) 天、KPL 命中 oppGames/oppWins 与 games 内对手 picks 一致、
     own.players 五路聚合、缺字段 null 不用 0。
  8. 用户重点专项：分路对位不出现 KDA、游走路不出现分均经济/分均输出、资源分配不用 pp、
     样本 < 3 局不给胜率结论。

输出：
  <out>/report.json   机器可读结果（含每条断言的实际证据）
  <out>/summary.txt   人类可读摘要（UTF-8，控制台乱码时以文件为准）

退出码：0 = 无失败断言（--baseline 恒为 0）；1 = 有失败断言；2 = 脚本自身异常。
"""
import argparse
import json
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEAM = 'team-6f8df5bf4a0b'
DEFAULT_BASE = 'http://127.0.0.1:8766'

QUADRANTS = ['单核进攻', '多点进攻', '保核运营', '多线牵制']
WINDOWS = ['7', '15', '30', 'all']
WINDOW_LABELS = {'7': '最近 7 天', '15': '最近 15 天', '30': '最近 30 天', 'all': '全部'}

# v3 五段（2026-11-14 设计对齐首页后的结构；docs/team_page_v2.md §0.1）
NEW_SECTIONS = [
    '样本与整体',
    '选人模式',
    '阵容组合',
    '打法与资源',
    '对位与关联',
    '变化与异常',
    '证据与方法',
]
# 打法段内的内容标记（缺失只告警）
PROFILE_MARKERS = ['团队风格四象限', '输出与承伤结构', '资源与对位']
# 必须消失的旧面板 / 旧套层（契约 §1 删除 + P1 收编：体系胜率旧三元组并入阵容体系）
REMOVED_TOKENS = [
    '交手走势', '节奏与终结', '赛前洞察',
    '经济投入', '输出转化',
    '基础层', '中级层', '高级层',
    'BASIC', 'INTERMEDIATE', 'ADVANCED',
    '体系表现', '阵容对抗', '证据与职业参照',
]
# 硬性禁词（契约 §3）
BANNED_TERMS = ['pp', '百分点', 'HHI', '分位', '协同值']
# 额外统计术语（只告警）
EXTRA_TERMS = ['显著性', '归一化', 'p 值', 'p值', '标准差']

# 与战队页 v2 无关、且改造前就存在的环境噪音（更新检查端点在当前数据目录返回 404）
NOISE_URL_MARKERS = ['/api/update/check']

# 段落内的子面板标题（QA 定位用：现为区块内卡片标题）
PANEL_SUBTITLES = ['边野组合', '资源与对位', '结果关联', '变化与异常', '团队风格四象限', '分路对位', '英雄使用', '主力体系', 'KPL 职业参照']

# 截图用的关键段（标题, 文件名）
SHOT_SECTIONS = [
    ('样本与整体', 'section-overview'),
    ('选人模式', 'section-heroes'),
    ('阵容组合', 'section-lineups'),
    ('打法与资源', 'section-style'),
    ('对位与关联', 'section-evidence'),
    ('变化与异常', 'section-change'),
]

# 交互冒烟：(断言 id, 段落标题, 候选 chip 文本, 候选 data-td-* 属性, 说明)
INTERACTIONS = [
    ('interaction.preference_lane', '英雄使用', ['打野'],
     ['data-td-chip'],
     '英雄池：点分路 chip「打野」'),
    ('interaction.style_window', '团队风格四象限', ['7 天', '7天'],
     ['data-td-chip'],
     '四象限：切到时间窗「7 天」'),
    ('interaction.style_window_all', '团队风格四象限', ['全部'],
     ['data-td-chip'],
     '四象限：切到时间窗「全部」'),
]

READY_JS = r"""() => {
  const main = document.querySelector('#content') || document.body;
  const t = (main.innerText || '');
  if (/正在(读取|打开|获取|加载)|加载中|loading/i.test(t)) return false;
  return t.replace(/\s+/g, '').length >= 400;
}"""

MARK_JS = r"""(titles) => {
  document.querySelectorAll('[data-qa-panel]').forEach((el) => el.removeAttribute('data-qa-panel'));
  const norm = (s) => (s || '').replace(/[\s\u00a0]+/g, '').replace(/[·•・|｜/／]/g, '');
  const clsOf = (el) => String(el.className || '');
  const isHeadLike = (el) => /(?:^|\s)\S*-?head(?:\s|$)/.test(clsOf(el));
  const isPanelLike = (el) => {
    const cls = clsOf(el);
    if (/(?:^|\s)\S*-?head(?:\s|$)/.test(cls)) return false;
    if (/(?:^|\s)\S*-?note(?:\s|$)/.test(cls)) return false;
    return /(?:^|\s)(?:tm|td|tst|tpl|page)?-?panel(?:\s|$)/.test(cls);
  };
  const climb = (start) => {
    let box = null;
    for (let el = start; el && el !== document.body; el = el.parentElement) {
      if (el.tagName === 'ARTICLE' || el.tagName === 'SECTION' || el.tagName === 'DETAILS') { box = el; break; }
      if (isPanelLike(el)) { box = el; break; }
    }
    return box;
  };
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')];
  const out = {found: {}, missing: []};
  for (const title of titles) {
    const tc = norm(title);
    if (!tc) continue;
    let box = null;
    const hit = headings.find((h) => {
      const hc = norm(h.innerText);
      return hc && (hc.includes(tc) || tc.includes(hc));
    });
    if (hit) {
      box = climb(hit.parentElement);
    } else {
      const cands = [...document.querySelectorAll('article,section,[class*="panel"],[class*="section"]')]
        .filter((el) => {
          if (isHeadLike(el)) return false;
          const t = norm(el.innerText);
          return t.includes(tc) && t.length < 8000;
        })
        .sort((a, b) => ((a.innerText || '').length - (b.innerText || '').length));
      box = cands[0] || null;
    }
    if (!box || box.hasAttribute('data-qa-panel')) { out.missing.push(title); continue; }
    box.setAttribute('data-qa-panel', title);
    const r = box.getBoundingClientRect();
    out.found[title] = {
      tag: box.tagName,
      cls: String(box.className || '').slice(0, 120),
      height: Math.round(r.height),
    };
  }
  return out;
}"""

SNAPSHOT_JS = r"""(title) => {
  const panel = document.querySelector('[data-qa-panel="' + title + '"]');
  if (!panel) return null;
  const active = [...panel.querySelectorAll('[aria-pressed="true"],[aria-selected="true"],[aria-current],[class*="is-active"],[class*="active"]')]
    .map((e) => (e.innerText || '').trim().slice(0, 24))
    .filter(Boolean);
  return {text: (panel.innerText || '').trim(), active: active};
}"""

CHIP_JS = r"""(args) => {
  const title = args.title;
  const texts = args.texts || [];
  const attrs = args.attrs || [];
  const panel = document.querySelector('[data-qa-panel="' + title + '"]');
  if (!panel) return {found: false, reason: 'panel-not-found'};
  const norm = (s) => (s || '').replace(/[\s\u00a0]+/g, '');
  const want = texts.map(norm);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const pool = [];
  for (const attr of attrs) {
    for (const el of panel.querySelectorAll('[' + attr + ']')) pool.push({el: el, by: attr});
  }
  for (const el of panel.querySelectorAll('button,a,[role="tab"],[role="button"],label')) pool.push({el: el, by: 'clickable'});
  let exact = null, partial = null;
  for (const item of pool) {
    if (!visible(item.el)) continue;
    const t = norm(item.el.innerText || item.el.textContent || '');
    if (!t) continue;
    for (const w of want) {
      if (t === w) { if (!exact) exact = item; }
      else if (t.includes(w)) { if (!partial) partial = item; }
    }
  }
  const pick = exact || partial;
  if (!pick) return {found: false, reason: 'chip-not-found', attrs: attrs};
  pick.el.setAttribute('data-qa-chip', '1');
  return {
    found: true,
    by: pick.by,
    text: (pick.el.innerText || '').trim().slice(0, 80),
    cls: String(pick.el.className || ''),
    pressed: pick.el.getAttribute('aria-pressed'),
    selected: pick.el.getAttribute('aria-selected'),
    current: pick.el.getAttribute('aria-current'),
  };
}"""

CARD_JS = r"""(args) => {
  const panel = document.querySelector('[data-qa-panel="' + args.title + '"]');
  if (!panel) return null;
  const lane = args.lane || '';
  const metricWords = ['分均', '参团', '承伤', '控制', '治疗', '经济', '输出', '推塔'];
  let best = null;
  for (const el of panel.querySelectorAll('article,li,div,section')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 3000) continue;
    const firstLine = t.split('\n').map((s) => s.trim()).filter(Boolean)[0] || '';
    if (!firstLine.includes(lane)) continue;
    if (!metricWords.some((w) => t.includes(w))) continue;
    if (!best || t.length < best.t.length) best = {t: t, cls: String(el.className || '').slice(0, 100)};
  }
  return best;
}"""

HEADINGS_JS = r"""() => [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
  .map((h) => (h.innerText || '').trim().replace(/\s+/g, ' '))
  .filter(Boolean)"""

OVERFLOW_JS = r"""() => {
  const de = document.documentElement;
  const cw = Math.max(de.clientWidth, window.innerWidth || 0);
  const sw = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0);
  const bad = [];
  for (const el of document.querySelectorAll('#content *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 1 && r.height > 1 && r.right > cw + 2) {
      const t = (el.innerText || '').trim().slice(0, 28);
      let par = el.parentElement, scrollable = false, clipped = false, scrollCls = '';
      while (par && par !== document.body) {
        const cs = getComputedStyle(par);
        const canScroll = (cs.overflowX === 'auto' || cs.overflowX === 'scroll');
        const tooWide = par.scrollWidth > par.clientWidth + 2;
        if (canScroll && tooWide) { scrollable = true; scrollCls = String(par.className || '').slice(0, 60); break; }
        if (cs.overflowX === 'hidden' && tooWide) { clipped = true; scrollCls = String(par.className || '').slice(0, 60); }
        par = par.parentElement;
      }
      bad.push({tag: el.tagName, cls: String(el.className || '').slice(0, 70),
                right: Math.round(r.right), text: t, scrollable: scrollable,
                clipped: clipped, container: scrollCls});
      if (bad.length >= 12) break;
    }
  }
  return {clientWidth: cw, scrollWidth: sw, overflow: sw - cw, offenders: bad};
}"""

QUAD_HINT_JS = r"""(title) => {
  const panel = document.querySelector('[data-qa-panel="' + title + '"]');
  if (!panel) return null;
  let chart = null;
  for (const el of panel.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 2) {
      chart = el;
      break;
    }
  }
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'
      && parseFloat(cs.opacity || '1') > 0.05;
  };
  const hints = [...panel.querySelectorAll('*')].filter((el) => {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 40) return false;
    if (!/(滑动|横向|左右滚|左右移|拖动|可滚动|滚动查看)/.test(t)) return false;
    return visible(el);
  }).map((el) => ({tag: el.tagName, cls: String(el.className || '').slice(0, 60),
                   text: (el.innerText || '').trim().slice(0, 40)}));
  const attrHints = [];
  if (chart) {
    for (const el of [chart, ...chart.querySelectorAll('[aria-label],[title]')]) {
      const a = el.getAttribute('aria-label') || el.getAttribute('title') || '';
      if (/(滑动|横向|滚动)/.test(a)) attrHints.push(a.slice(0, 60));
    }
  }
  return chart
    ? {scrollW: chart.scrollWidth, clientW: chart.clientWidth,
       cls: String(chart.className || '').slice(0, 80), hints: hints, attrHints: attrHints}
    : {scrollW: 0, clientW: 0, cls: '', hints: [], attrHints: []};
}"""

TEAM_DOM_JS = r"""() => {
  const out = {};
  const norm = (s) => (s || '').replace(/\s+/g, '');
  const sectionByTitle = (needle) => [...document.querySelectorAll('section')].find((sec) => {
    return [sec.querySelector('h2'), ...sec.querySelectorAll('h3')].some((h) => {
      const t = norm(h && (h.innerText || h.textContent));
      return t && t.includes(norm(needle));
    });
  }) || null;
  // KPL / 体系资源都在折叠块里，先展开再读文本（只读探测，不改页面业务状态）
  document.querySelectorAll('.tp-page details').forEach((d) => { d.open = true; });
  const heroes = sectionByTitle('选人模式');
  out.likes = heroes ? {
    cards: [...heroes.querySelectorAll('[data-tp-hero-lane]')].map((el) => el.dataset.tpHeroLane),
    bars: 0,
  } : null;
  out.bp = {lanes: [...document.querySelectorAll('.tp-ban-stack-legend span')].map((r) => (r.innerText || '').trim()).filter(Boolean).slice(0, 5)};
  out.duel = [...document.querySelectorAll('.tp-duel')].map((card) => ({
    lane: (card.querySelector('header b')?.innerText || '').trim(),
    metrics: [...card.querySelectorAll('.tp-duel-label')].map((x) => (x.innerText || '').trim()),
  }));
  const style = sectionByTitle('团队风格四象限');
  out.style = style ? {text: (style.textContent || '')} : null;
  const res = sectionByTitle('资源与对位');
  out.resource = res ? {
    metrics: [],
    lanes: [...res.querySelectorAll('.tp-res-table tbody tr td:first-child')].map((el) => (el.innerText || '').trim()),
    table: !!res.querySelector('.tp-res-table'),
    laneDiff: !!res.querySelector('.tp-res-table th:nth-child(3)'),
  } : null;
  const kpl = [...document.querySelectorAll('details')].find((d) => (d.querySelector('summary')?.innerText || '').includes('KPL'));
  if (kpl) kpl.open = true;
  out.kpl = kpl ? {text: (kpl.innerText || '').trim()} : null;
  out.text = (document.querySelector('.tp-page')?.innerText || '');
  out.heroLinks = [...document.querySelectorAll('.tp-hero, .tp-face')].map((a) => a.getAttribute('href') || '').filter(Boolean);
  out.systems = document.querySelectorAll('.tp-sig-row.is-system').length;
  out.library = !!document.querySelector('.tp-library');
  out.fiveRows = document.querySelectorAll('.tp-five-row').length;
  out.samples = document.querySelectorAll('.tp-sample').length;
  out.scope = !!document.querySelector('.tp-scope');
  out.filterButtons = document.querySelectorAll('.tp-page [data-action="filter"]').length;
  out.copySummary = (document.querySelector('[data-tp-copy]')?.dataset.tpSummary || '').length;
  out.demo = (document.querySelector('.tp-page')?.innerText || '').includes('演示');
  out.edge = document.querySelectorAll('.tp-edge-cell:not(.is-empty)').length;
  out.lift = document.querySelectorAll('.tp-lift').length;
  out.resourceBars = document.querySelectorAll('.tp-res-table .tp-mini').length;
  out.spark = !!document.querySelector('.tp-spark');
  const bpCard = [...document.querySelectorAll('.tp-card')].find((card) => (card.querySelector('h3')?.innerText || '').trim() === 'BP 时序');
  out.bpOrder = !!document.querySelector('.tp-bpo');
  out.bpOrderText = bpCard?.innerText || '';
  out.bpBanSlots = bpCard ? bpCard.querySelectorAll('.tp-bpo-bseq-row').length : 0;
  const cardByTitle = (title) => [...document.querySelectorAll('.tp-card')].find((card) => (card.querySelector('h3')?.innerText || '').trim() === title);
  const banPoolCard = cardByTitle('Ban × 英雄池');
  const banShapeCard = cardByTitle('Ban 形状');
  const replacementCard = cardByTitle('Ban 后的替代结构');
  const poolDepthCard = cardByTitle('英雄池深度 · 五路');
  out.banPool = {
    panels: document.querySelectorAll('.tp-scatter-panel').length,
    dots: document.querySelectorAll('.tp-scat-dot').length,
    text: banPoolCard?.innerText || '',
  };
  out.banShape = {
    stacks: document.querySelectorAll('.tp-ban-stack').length,
    splits: document.querySelectorAll('.tp-target-mini').length,
    waste: document.querySelectorAll('.tp-waste > a').length,
    text: banShapeCard?.innerText || '',
  };
  out.replacement = {
    rows: replacementCard ? replacementCard.querySelectorAll('.tp-repl-table tbody tr').length : 0,
    cells: document.querySelectorAll('.tp-repl-matrix > i').length,
    text: replacementCard?.innerText || '',
  };
  out.poolDepth = {
    rows: poolDepthCard ? poolDepthCard.querySelectorAll('.tp-pool-table tbody tr').length : 0,
    kpl: poolDepthCard ? poolDepthCard.querySelectorAll('.tp-pool-backups small').length : 0,
    text: poolDepthCard?.innerText || '',
  };
  const banOutcomeCard = cardByTitle('Ban 与结果');
  out.banOutcomeRows = banOutcomeCard ? banOutcomeCard.querySelectorAll('tbody tr').length : 0;
  out.banOutcomeText = banOutcomeCard?.innerText || '';
  const rulesCard = [...document.querySelectorAll('.tp-card')].find((card) => (card.querySelector('h3')?.innerText || '').trim() === '结果关联');
  out.rules = rulesCard ? rulesCard.querySelectorAll('tbody tr:not(.is-group)').length : 0;
  const changeSec = document.getElementById('tp-change');
  out.change = !!changeSec;
  out.changeRows = changeSec ? changeSec.querySelectorAll('.tp-table tbody tr').length : 0;
  out.outliers = document.querySelectorAll('.tp-outlier').length;
  const quad = document.querySelector('.tp-quad');
  out.quad = quad ? {
    width: quad.viewBox?.baseVal?.width || 0,
    dots: [...quad.querySelectorAll('.tp-qdot:not(.is-own)')].map((d) => ({cx: parseFloat(d.getAttribute('cx')), cy: parseFloat(d.getAttribute('cy'))})),
  } : null;
  return out;
}"""

INIT_SCRIPT = r"""try {
  localStorage.setItem('training-tour-complete-v3', '1');
} catch (e) {}
"""

STABLE_CSS = r"""
*, *::before, *::after { animation: none !important; transition: none !important; }
html { scroll-behavior: auto !important; }
"""


# --------------------------------------------------------------------------- 报告
class Report:
    def __init__(self, base, team, out, modes, baseline):
        self.base = base
        self.team = team
        self.out = out
        self.modes = modes
        self.baseline = baseline
        self.started = datetime.now().isoformat(timespec='seconds')
        self.items = []
        self.modes_data = {}
        self.api_raw_path = None
        self.notes = []
        self.team_matches = None

    def add(self, ident, category, ok, detail, evidence=None, severity='fail'):
        self.items.append({
            'id': ident,
            'category': category,
            'severity': severity,
            'ok': bool(ok),
            'detail': detail,
            'evidence': evidence,
        })

    def warn(self, ident, category, ok, detail, evidence=None):
        self.add(ident, category, ok, detail, evidence, severity='warn')

    @property
    def failures(self):
        return [x for x in self.items if x['severity'] == 'fail' and not x['ok']]

    @property
    def warnings(self):
        return [x for x in self.items if x['severity'] == 'warn' and not x['ok']]

    @property
    def passed(self):
        return [x for x in self.items if x['ok']]

    def summary(self):
        return {
            'result': 'FAIL' if self.failures else 'PASS',
            'total': len(self.items),
            'passed': len(self.passed),
            'failed': len(self.failures),
            'warnings': len(self.warnings),
            'baseline': self.baseline,
        }


def compact(text):
    return re.sub(r'[\s\u00a0]+', '', text or '')


def title_compact(text):
    return re.sub(r'[·•・|｜/／]', '', compact(text))


def lines_with(text, needle, limit=6):
    return [ln.strip()[:180] for ln in (text or '').splitlines() if needle in ln][:limit]


def diff_lines(before, after, limit=4):
    b = [ln.strip() for ln in (before or '').splitlines() if ln.strip()]
    a = [ln.strip() for ln in (after or '').splitlines() if ln.strip()]
    out = [ln for ln in b if ln not in a][:limit]
    if not out:
        out = ['（文本行一致，仅 class / aria 状态变化）']
    return out[:limit]


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _window_quadrant_counts(games, anchor_raw, days, year):
    """按窗口统计四象限局数；days=None 表示全部。返回 {象限: 局数} 或 None。"""
    anchor = _date_of(anchor_raw, year) if days else None
    if days and anchor is None:
        return None
    lower = anchor - timedelta(days=max(0, days - 1)) if days else None
    counts = {q: 0 for q in QUADRANTS}
    for game in games:
        if days:
            day = _date_of(game.get('day') or game.get('start'), year, anchor)
            if day is None or not (lower <= day <= anchor):
                continue
        q = (game.get('style') or {}).get('quadrant')
        if q in counts:
            counts[q] += 1
    return counts


# --------------------------------------------------------------------------- API 自检
def http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8', errors='replace')
        return resp.status, json.loads(body)


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_day(value):
    """解析 'MM-DD HH:MM' / 'YYYY-MM-DD ...'，返回 (year|None, month, day)。"""
    if not isinstance(value, str):
        return None
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', value)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)', value)
    if m:
        return (None, int(m.group(1)), int(m.group(2)))
    return None


def _default_year(games):
    for game in games:
        parsed = _parse_day(game.get('start') or game.get('day'))
        if parsed and parsed[0]:
            return parsed[0]
    return datetime.now().year


def _date_of(raw, year, anchor=None):
    parsed = _parse_day(raw)
    if not parsed:
        return None
    y, m, d = parsed
    try:
        value = datetime(y or year, m, d).date()
    except ValueError:
        return None
    if not y and anchor is not None and value > anchor:
        try:
            value = datetime(year - 1, m, d).date()
        except ValueError:
            return None
    return value


def _window_game_count(games, anchor_raw, days, year):
    """窗口 = [锚点-(N-1) 天, 锚点]（契约 2026-11-13 更新）。"""
    anchor = _date_of(anchor_raw, year)
    if anchor is None:
        return None
    lower = anchor - timedelta(days=max(0, days - 1))
    count = 0
    for game in games:
        day = _date_of(game.get('day') or game.get('start'), year, anchor)
        if day is None:
            continue
        if lower <= day <= anchor:
            count += 1
    return count


def check_api(report, base, team, api_timeout):
    path = '/api/v3/team-deep?team=' + urllib.parse.quote(team)
    url = base.rstrip('/') + path
    try:
        status, data = http_get_json(url, timeout=api_timeout)
    except urllib.error.HTTPError as exc:
        report.add('data.api_status', 'data', False,
                   'GET %s 返回 HTTP %s（期望 200）' % (path, exc.code),
                   {'url': url, 'status': exc.code})
        return
    except Exception as exc:  # noqa: BLE001
        report.add('data.api_status', 'data', False,
                   'GET %s 请求失败：%s' % (path, exc), {'url': url})
        return

    report.add('data.api_status', 'data', status == 200,
               'GET %s 返回 HTTP %s' % (path, status), {'url': url, 'status': status})
    raw_path = report.out / 'team-deep.json'
    write_json(raw_path, data)
    report.api_raw_path = str(raw_path)

    # 顶层字段
    top_keys = ['team', 'own', 'games', 'style', 'taxonomy', 'kpl', 'bpOrder',
                'banMatchup', 'banReplacement', 'poolDepth', 'meta']
    missing = [k for k in top_keys if k not in data]
    report.add('data.top_keys', 'data', not missing,
               '顶层字段齐全' if not missing else '顶层字段缺失：%s' % ', '.join(missing),
               {'keys': sorted(data.keys()), 'missing': missing})

    team_obj = data.get('team') or {}
    if _num(team_obj.get('matches')):
        report.team_matches = team_obj.get('matches')
    games = data.get('games') or []
    style = data.get('style') or {}
    report.add('data.games_present', 'data', len(games) >= 1,
               'games 有 %d 条' % len(games), {'games': len(games)})

    # BP 顺序来源：核验局 + 按名单假设局，必须能对上 knownGames，避免把假设当核验。
    bp_order = data.get('bpOrder') or {}
    if bp_order.get('eventsKnown'):
        known = bp_order.get('knownGames')
        verified = bp_order.get('verifiedGames')
        assumed = bp_order.get('assumedGames')
        provenance_ok = (_num(known) and _num(verified) and _num(assumed)
                         and verified + assumed == known)
        report.add('data.bp_order_provenance', 'data', provenance_ok,
                   'BP 顺序来源可对账：有顺序 %s 局 = 核验 %s + 按名单假设 %s' % (known, verified, assumed)
                   if provenance_ok else 'BP 顺序来源缺失或对不上（known=%s verified=%s assumed=%s）' % (known, verified, assumed),
                   {'knownGames': known, 'verifiedGames': verified, 'assumedGames': assumed})
    else:
        report.add('data.bp_order_provenance', 'data', True,
                   '该队没有可用 BP 顺序，跳过来源对账', {'eventsKnown': False})

    bm = data.get('banMatchup') or {}
    br = data.get('banReplacement') or {}
    pd = data.get('poolDepth') or {}
    ban_analysis_ok = (bm.get('games') and len((bm.get('theirBansVsOurPool') or {}).get('points') or []) >= 5
                       and len((bm.get('ourBansVsTheirPool') or {}).get('points') or []) >= 5
                       and len(br.get('rows') or []) >= 3
                       and len((br.get('matrix') or {}).get('rows') or []) >= 3
                       and len(pd.get('lanes') or []) == 5)
    report.add('data.ban_analysis', 'data', ban_analysis_ok,
               'Ban 分析块齐全（双向散点 / 替代矩阵 / 五路池深）' if ban_analysis_ok
               else 'Ban 分析块不完整',
               {'matchupGames': bm.get('games'), 'replacementRows': len(br.get('rows') or []),
                'matrixRows': len((br.get('matrix') or {}).get('rows') or []),
                'poolLanes': len(pd.get('lanes') or [])})

    ban_rows = bp_order.get('banOutcome') or []
    if ban_rows:
        ban_games = bp_order.get('banOutcomeGames')
        ban_base = bp_order.get('banOutcomeBaseRate')
        sample_ok = _num(ban_games) and _num(ban_base)
        report.add('data.ban_outcome_sample', 'data', sample_ok,
                   'Ban 与结果样本 %s 局、基线 %s%%（只用终局 ban 名单，不要求手序）' % (ban_games, ban_base)
                   if sample_ok else 'Ban 与结果缺少样本量或基线（games=%s base=%s）' % (ban_games, ban_base),
                   {'games': ban_games, 'baseRate': ban_base})
    else:
        report.add('data.ban_outcome_sample', 'data', True,
                   '没有 ≥4 局的 ban 条件，跳过', {'rows': 0})

    # 逐局结构
    struct_bad = []
    for idx, game in enumerate(games):
        sides = game.get('sides') or {}
        for side in ('own', 'enemy'):
            block = sides.get(side) or {}
            for field in ('players', 'picks', 'bans', 'stats'):
                if not isinstance(block.get(field), list if field != 'stats' else dict):
                    struct_bad.append('games[%d].sides.%s.%s 缺失或类型错误' % (idx, side, field))
            if not block.get('players'):
                struct_bad.append('games[%d].sides.%s.players 为空' % (idx, side))
        if not isinstance(game.get('style'), dict):
            struct_bad.append('games[%d].style 缺失' % idx)
    report.add('data.game_structure', 'data', not struct_bad,
               '逐局双方 players/picks/bans/stats/style 齐全' if not struct_bad else '逐局结构有问题',
               {'problems': struct_bad[:12]})

    # 经济占比合计 ≈ 100%
    share_bad, share_ok, share_evidence = [], 0, []
    for idx, game in enumerate(games):
        for side in ('own', 'enemy'):
            block = ((game.get('sides') or {}).get(side) or {})
            players = block.get('players') or []
            shares = [p.get('goldShare') for p in players if isinstance(p, dict)]
            nums = [s for s in shares if _num(s)]
            if not nums:
                continue
            share_ok += 1
            total = sum(nums)
            if abs(total - 100) > 1.0:
                share_bad.append({'game': idx, 'side': side, 'sum': round(total, 2), 'shares': nums})
            if len(share_evidence) < 6:
                share_evidence.append({'game': idx, 'side': side, 'sum': round(total, 2)})
    report.add('data.goldshare_100', 'data', share_ok > 0 and not share_bad,
               ('%d 个“局×方”经济占比合计≈100%%' % share_ok) if share_ok and not share_bad
               else ('没有可校验的 goldShare（全为 null）' if not share_ok else '经济占比合计异常'),
               {'checked': share_ok, 'bad': share_bad[:8], 'sample': share_evidence})

    # 顶层 style 与 team.style 一致
    style_match = style == (team_obj.get('style') or {})
    report.add('data.style_matches_team', 'data', style_match,
               '顶层 style 与 team.style 一致' if style_match else '顶层 style 与 team.style 不一致',
               {'top_style_keys': sorted(style.keys()) if isinstance(style, dict) else style,
                'team_style_keys': sorted((team_obj.get('style') or {}).keys())})

    # 逐局象限合法
    bad_q = [{'game': i, 'quadrant': (g.get('style') or {}).get('quadrant')}
             for i, g in enumerate(games)
             if (g.get('style') or {}).get('quadrant') is not None
             and (g.get('style') or {}).get('quadrant') not in QUADRANTS]
    report.add('data.game_quadrants', 'data', not bad_q,
               '逐局 quadrant 合法' if not bad_q else '逐局 quadrant 取值非法', {'bad': bad_q[:8]})

    # 窗口计数：counts 合计 = 窗口局数；all 窗口计数与逐局统计一致
    windows = style.get('windows') or {}
    win_bad, win_evidence = [], {}
    for key in WINDOWS:
        w = windows.get(key)
        if not isinstance(w, dict):
            win_bad.append('windows.%s 缺失' % key)
            continue
        counts = w.get('counts') or {}
        if not isinstance(counts, dict):
            win_bad.append('windows.%s.counts 类型错误' % key)
            continue
        total = sum(v for v in counts.values() if _num(v))
        win_evidence[key] = {'games': w.get('games'), 'counts_sum': total, 'counts': counts}
        if not _num(w.get('games')):
            win_bad.append('windows.%s.games 不是数字' % key)
        elif total != w.get('games'):
            win_bad.append('windows.%s counts 合计 %s ≠ games %s' % (key, total, w.get('games')))
    report.add('data.window_counts', 'data', not win_bad,
               '四象限窗口计数合计 = 局数' if not win_bad else '窗口计数不自洽',
               {'bad': win_bad, 'windows': win_evidence})

    wall = windows.get('all') or {}
    if _num(wall.get('games')) and wall.get('games') == len(games):
        tally = {q: 0 for q in QUADRANTS}
        for game in games:
            q = (game.get('style') or {}).get('quadrant')
            if q in tally:
                tally[q] += 1
        counts = wall.get('counts') or {}
        mismatch = {q: {'按局统计': tally[q], '接口counts': counts.get(q)} for q in QUADRANTS
                    if counts.get(q) != tally[q]}
        report.add('data.window_all_tally', 'data', not mismatch,
                   'all 窗口四象限计数与逐局 style 一致' if not mismatch else 'all 窗口计数与逐局统计不一致',
                   {'mismatch': mismatch, 'games': len(games)})
    else:
        report.warn('data.window_all_tally', 'data', True,
                    'all 窗口局数(%s) ≠ games 条数(%d)，跳过逐局计数对照'
                    % (wall.get('games'), len(games)), {})

    # 窗口下界 = 锚点-(N-1) 天（契约 2026-11-13 更新）
    anchor_raw = style.get('anchor') or team_obj.get('lastSeen')
    year = _default_year(games)
    range_bad, range_evidence = [], {}
    for key in ('7', '15', '30'):
        w = windows.get(key) or {}
        expected_n = _window_game_count(games, anchor_raw, int(key), year)
        range_evidence[key] = {'anchor': anchor_raw, 'expected': expected_n, 'api_games': w.get('games')}
        if expected_n is None:
            range_bad.append('无法解析锚点/日期，窗口 %s 无法校验' % key)
        elif w.get('games') != expected_n:
            range_bad.append('windows.%s.games=%s，按「锚点-(N-1) 天」计算应为 %s'
                             % (key, w.get('games'), expected_n))
    range_evidence['all'] = {'expected': len(games), 'api_games': wall.get('games')}
    if wall.get('games') != len(games):
        range_bad.append('windows.all.games=%s，应为全部 %s 局' % (wall.get('games'), len(games)))
    report.add('data.window_ranges', 'data', not range_bad,
               '窗口下界=锚点-(N-1) 天，局数吻合' if not range_bad else '窗口日期范围与局数不吻合',
               {'bad': range_bad, 'evidence': range_evidence, 'anchor': anchor_raw, 'year': year})

    # 各窗口四象限计数必须与 games[].style 的逐局象限一致
    tally_bad = []
    for key in WINDOWS:
        w = windows.get(key) or {}
        expected_counts = _window_quadrant_counts(
            games, anchor_raw, None if key == 'all' else int(key), year)
        api_counts = w.get('counts') or {}
        if expected_counts is None:
            tally_bad.append('无法解析锚点/日期，窗口 %s 象限计数无法校验' % key)
            continue
        diff = {q: {'按局统计': expected_counts[q], '接口counts': api_counts.get(q)}
                for q in QUADRANTS if api_counts.get(q) != expected_counts[q]}
        if diff:
            tally_bad.append({'window': key, 'diff': diff})
    report.add('data.window_tally', 'data', not tally_bad,
               '各窗口四象限计数与 games[].style 一致' if not tally_bad
               else '窗口四象限计数与逐局 style 不一致',
               {'bad': tally_bad[:6], 'anchor': anchor_raw, 'year': year})

    # main 取窗口逻辑（30 天足够取 30，否则全部）
    main = style.get('main') or {}
    w30 = windows.get('30') or {}
    expected_key = '30' if _num(w30.get('games')) and w30.get('games') >= 3 else 'all'
    expected = windows.get(expected_key) or {}
    main_bad = []
    if main.get('quadrant') != expected.get('quadrant'):
        main_bad.append('main.quadrant=%r，期望取 windows.%s.quadrant=%r'
                        % (main.get('quadrant'), expected_key, expected.get('quadrant')))
    if _num(main.get('share')) and _num(expected.get('share')) and abs(main['share'] - expected['share']) > 0.2:
        main_bad.append('main.share=%s 与 windows.%s.share=%s 不一致'
                        % (main.get('share'), expected_key, expected.get('share')))
    report.add('data.style_main', 'data', not main_bad,
               'main 窗口回落逻辑正确（期望取 %s）' % expected_key if not main_bad else 'main 窗口逻辑不一致',
               {'expected_window': expected_key, 'main': main, 'problems': main_bad})

    # 缺字段 null 而非 0
    null_bad = []
    for i, game in enumerate(games):
        st = game.get('style') or {}
        if (st.get('x') is None or st.get('y') is None) and st.get('quadrant') is not None:
            null_bad.append('games[%d] x/y 缺失但 quadrant=%r' % (i, st.get('quadrant')))
        for side in ('own', 'enemy'):
            for p in (((game.get('sides') or {}).get(side) or {}).get('players') or []):
                if not isinstance(p, dict):
                    continue
                if _num(p.get('gold')) and p.get('gold') > 0 and p.get('goldShare') == 0:
                    null_bad.append('games[%d].%s 选手 %s 有经济但 goldShare=0' % (i, side, p.get('name')))
    report.add('data.null_not_zero', 'data', not null_bad,
               '缺字段用 null / 未用 0 冒充' if not null_bad else '发现用 0 冒充缺字段',
               {'problems': null_bad[:10]})

    # own.players：本队五路选手聚合（契约 2026-11-13 更新）
    own_obj = data.get('own') or {}
    own_players = own_obj.get('players') or []
    own_lanes = [p.get('lane') for p in own_players if isinstance(p, dict)]
    missing_lanes = [lane for lane in ('对抗路', '打野', '中路', '发育路', '游走')
                     if lane not in own_lanes]
    core_bad = []
    for idx, player in enumerate(own_players):
        if not isinstance(player, dict):
            core_bad.append('own.players[%d] 不是对象' % idx)
            continue
        for field in ('name', 'lane', 'games'):
            if player.get(field) in (None, ''):
                core_bad.append('own.players[%d] 缺 %s' % (idx, field))
    report.add('data.own_players', 'data',
               bool(own_players) and not missing_lanes and not core_bad,
               'own.players 五路齐全（name/lane/games 均有）'
               if own_players and not missing_lanes and not core_bad
               else ('own.players 缺失' if not own_players
                     else ('own.players 缺分路：%s' % '、'.join(missing_lanes)
                           if missing_lanes else 'own.players 缺 name/lane/games')),
               {'count': len(own_players), 'lanes': own_lanes,
                'missing_lanes': missing_lanes, 'problems': core_bad[:10]})
    if own_players:
        field_bad = []
        per_min_keys = ('gpm', 'dpm', 'dtpm', 'goldPerMin', 'damagePerMin', 'takenPerMin',
                        'participation', 'killsPerMin', 'assistsPerMin', 'controlPerMin',
                        'healPerMin', 'goldShare', 'share')
        for idx, player in enumerate(own_players):
            if not isinstance(player, dict):
                continue
            if not any(_num(player.get(k)) for k in per_min_keys):
                field_bad.append('own.players[%d] 缺分均数据' % idx)
        report.warn('data.own_players_fields', 'data', not field_bad,
                    'own.players 分均数据齐全' if not field_bad else 'own.players 分均数据缺失',
                    {'problems': field_bad[:8],
                     'keys': sorted({k for p in own_players if isinstance(p, dict) for k in p})})

    # team.players 五路选手条（契约 §1 A，只告警）
    team_players = team_obj.get('players') or []
    team_lanes = [p.get('lane') for p in team_players if isinstance(p, dict)]
    missing_team_lanes = [lane for lane in ('对抗路', '打野', '中路', '发育路', '游走')
                          if lane not in team_lanes]
    report.warn('data.team_players', 'data',
                bool(team_players) and not missing_team_lanes,
                'team.players 五路齐全' if team_players and not missing_team_lanes
                else ('team.players 缺失' if not team_players
                      else 'team.players 缺分路：%s' % '、'.join(missing_team_lanes)),
                {'count': len(team_players), 'lanes': team_lanes})

    # KPL 命中（契约 2026-11-13 更新：字段为 oppGames / oppWins / oppWinRate）
    # 语义：我们与该队交手里这组英雄出现的局数 / 这些局对手赢了几场 / 对手胜率。
    kpl = data.get('kpl') or {}
    hits = kpl.get('hits') or []
    kpl_bad, kpl_legacy, kpl_evidence = [], [], []

    def _opp_field(entry, name):
        legacy = {'oppGames': 'ourGames', 'oppWins': 'ourWins', 'oppWinRate': 'ourWinRate'}[name]
        if name in entry:
            return entry.get(name)
        if legacy in entry:
            return entry.get(legacy)
        return None

    def _combo_games(heroes):
        rows = []
        for game in games:
            picks = ((game.get('sides') or {}).get('enemy') or {}).get('picks') or []
            names = {p.get('name') for p in picks if isinstance(p, dict)}
            if set(heroes) <= names:
                opp_win = game.get('opponentWin')
                if opp_win is None and game.get('win') is not None:
                    opp_win = not game.get('win')
                rows.append({'opponentWin': bool(opp_win)})
        return rows

    def _check_kpl_entry(entry, label):
        heroes = entry.get('heroes') or []
        if not heroes:
            kpl_bad.append('%s 缺少 heroes' % label)
            return
        rows = _combo_games(heroes)
        actual_games = len(rows)
        actual_wins = sum(1 for row in rows if row['opponentWin'])
        if 'oppGames' not in entry:
            kpl_legacy.append('%s 仍用旧字段名（应为 oppGames/oppWins/oppWinRate）' % label)
        opp_games = _opp_field(entry, 'oppGames')
        opp_wins = _opp_field(entry, 'oppWins')
        if opp_games != actual_games:
            kpl_bad.append({'label': label, 'heroes': heroes, 'oppGames': opp_games, '按 games 统计': actual_games})
        if opp_wins != actual_wins:
            kpl_bad.append({'label': label, 'heroes': heroes, 'oppWins': opp_wins, '按 games 统计': actual_wins})
        opp_rate = _opp_field(entry, 'oppWinRate')
        expected_rate = round(actual_wins / actual_games * 100, 1) if actual_games else None
        rate_ok = (opp_rate is None and expected_rate is None) or (
            _num(opp_rate) and expected_rate is not None and abs(opp_rate - expected_rate) <= 0.2)
        kpl_evidence.append({'label': label, 'heroes': heroes, 'oppGames': opp_games,
                             'oppWins': opp_wins, 'oppWinRate': opp_rate,
                             '按 games 统计': {'games': actual_games, 'wins': actual_wins,
                                               'rate': expected_rate}, 'rate_ok': rate_ok})
        if not rate_ok:
            report.warn('data.kpl_opp_win_rate', 'data', False,
                        'KPL 条目 oppWinRate 与 oppWins/oppGames 不一致', {'entry': kpl_evidence[-1]})

    for hit in hits:
        _check_kpl_entry(hit, 'hit')
    lineup = kpl.get('lineup') or {}
    if lineup.get('heroes'):
        _check_kpl_entry(lineup, 'lineup')
    report.add('data.kpl_hits', 'data', not kpl_bad,
               'KPL 命中的 oppGames/oppWins 与 games 内对手 picks 一致' if not kpl_bad
               else 'KPL 命中 oppGames/oppWins 与 games 统计不一致',
               {'bad': kpl_bad[:8], 'sample': kpl_evidence[:8], 'hits': len(hits)})
    if kpl_legacy:
        report.warn('data.kpl_legacy_fields', 'data', False,
                    'KPL 命中仍使用旧字段名', {'entries': kpl_legacy[:8]})

    # KPL 数据结构（只告警）
    kpl_fields = ['source', 'games', 'sinceYear', 'updatedAt', 'hits']
    missing_kpl = [f for f in kpl_fields if f not in kpl]
    report.warn('data.kpl_fields', 'data', not missing_kpl,
                'KPL 字段齐全' if not missing_kpl else 'KPL 字段缺失：%s' % ', '.join(missing_kpl), {})

    # meta / taxonomy（只告警）
    meta = data.get('meta') or {}
    limits = meta.get('limits') or []
    report.warn('data.meta_limits', 'data',
                bool(meta.get('source')) and isinstance(limits, list) and len(limits) >= 3,
                'meta.source / limits 齐全' if limits else 'meta.limits 缺失',
                {'source': meta.get('source'), 'days': meta.get('days'),
                 'thresholds': meta.get('thresholds'), 'limits': limits,
                 'warnings': meta.get('warnings')})
    taxonomy = data.get('taxonomy') or {}
    groups = taxonomy.get('groups') or {}
    report.warn('data.taxonomy', 'data', len(groups) >= 5 and bool(taxonomy.get('lanes')),
                'taxonomy 五路分组齐全' if len(groups) >= 5 else 'taxonomy.groups 不足五路',
                {'lanes': taxonomy.get('lanes'), 'groups': sorted(groups.keys())})

    # 平均类指标出现 0 → 可能用 0 冒充缺失（只告警；winRate 0 是真实值，排除）
    metrics = team_obj.get('metrics') or {}
    zero_metrics = [k for k, v in metrics.items()
                    if _num(v) and v == 0 and k != 'winRate'
                    and (team_obj.get('matches') or 0) > 0]
    report.warn('data.metrics_zero', 'data', not zero_metrics,
                '平均类指标没有 0 值' if not zero_metrics else '平均类指标出现 0，可能用 0 冒充缺失',
                {'team.matches': team_obj.get('matches'), 'zero': zero_metrics})

    # 由页面断言使用的关键事实落盘，方便人工复核
    report.notes.append('team.matches=%s games=%d style.main=%s'
                        % (team_obj.get('matches'), len(games),
                           json.dumps(style.get('main'), ensure_ascii=False)))


# --------------------------------------------------------------------------- studio/teams 抽查
# 改造前 teams[]/own 的既有字段（契约要求只增不减）
LEGACY_TEAM_KEYS = ['coach', 'displayName', 'firstSeen', 'games', 'heroes', 'id',
                    'lastSeen', 'losses', 'matches', 'metrics', 'name', 'named',
                    'number', 'percentiles', 'players', 'roster', 'seqs', 'winRate', 'wins']
LEGACY_OWN_KEYS = ['losses', 'matches', 'metrics', 'name', 'percentiles', 'roster', 'winRate', 'wins']


def check_studio_teams(report, base, api_timeout):
    path = '/api/studio/teams'
    url = base.rstrip('/') + path
    started = time.time()
    try:
        status, data = http_get_json(url, timeout=api_timeout)
    except urllib.error.HTTPError as exc:
        report.add('data.studio_teams_status', 'data', False,
                   'GET %s 返回 HTTP %s' % (path, exc.code), {'url': url})
        return
    except Exception as exc:  # noqa: BLE001
        report.add('data.studio_teams_status', 'data', False,
                   'GET %s 请求失败：%s' % (path, exc), {'url': url})
        return
    elapsed_ms = int((time.time() - started) * 1000)
    report.add('data.studio_teams_status', 'data', status == 200,
               'GET %s 返回 HTTP %s' % (path, status), {'url': url, 'status': status})
    report.warn('data.studio_teams_latency', 'data', elapsed_ms < 2000,
                '/api/studio/teams 响应 %dms' % elapsed_ms,
                {'elapsed_ms': elapsed_ms, 'warn_threshold_ms': 2000})

    teams = data.get('teams') or []
    own = data.get('own') or {}
    report.add('data.studio_teams_count', 'data', len(teams) >= 1,
               'teams 共 %d 支' % len(teams), {'teams': len(teams)})

    # 既有字段未变（只增不减）
    key_bad = []
    for idx, team in enumerate(teams):
        missing = [k for k in LEGACY_TEAM_KEYS if k not in team]
        if missing:
            key_bad.append({'team': team.get('id'), 'missing': missing})
    own_missing = [k for k in LEGACY_OWN_KEYS if k not in own]
    report.add('data.studio_teams_legacy_keys', 'data', not key_bad and not own_missing,
               'teams[]/own 既有字段未丢失' if not key_bad and not own_missing
               else '既有字段丢失',
               {'bad': key_bad[:6], 'own_missing': own_missing,
                'checked': len(teams), 'legacy_keys': LEGACY_TEAM_KEYS})

    # 每支队与 own 都有 style（§2.1 结构）
    no_style = [t.get('id') for t in teams if not isinstance(t.get('style'), dict)]
    own_style_ok = isinstance(own.get('style'), dict)
    report.add('data.studio_teams_style', 'data', not no_style and own_style_ok,
               'teams[] 与 own 均有 style' if not no_style and own_style_ok
               else '缺少 style：%d 支 / own=%s' % (len(no_style), own_style_ok),
               {'missing_style_teams': no_style[:8], 'own_style': own_style_ok})

    # style 结构抽样：windows 四键 + main/pool
    style_bad = []
    for team in teams[:]:
        st = team.get('style')
        if not isinstance(st, dict):
            continue
        windows = st.get('windows') or {}
        miss = [k for k in WINDOWS if not isinstance(windows.get(k), dict)]
        if miss:
            style_bad.append({'team': team.get('id'), 'missing_windows': miss})
        if not isinstance(st.get('main'), dict):
            style_bad.append({'team': team.get('id'), 'missing': 'main'})
        if not isinstance(st.get('pool'), dict):
            style_bad.append({'team': team.get('id'), 'missing': 'pool'})
    report.add('data.studio_teams_style_shape', 'data', not style_bad,
               'style 结构（windows 7/15/30/all + main + pool）齐全' if not style_bad
               else 'style 结构不完整',
               {'bad': style_bad[:8], 'teams_checked': len(teams)})

    # 目标战队在列表中且带 style
    target = next((t for t in teams if t.get('id') == report.team), None)
    report.add('data.studio_teams_target', 'data', target is not None,
               '目标战队 %s 在 teams 列表中' % report.team,
               {'found': target is not None})
    if target is not None:
        report.notes.append('studio/teams: teams=%d own.style=%s target.style.main=%s'
                            % (len(teams), own_style_ok,
                               json.dumps((target.get('style') or {}).get('main'), ensure_ascii=False)))


# --------------------------------------------------------------------------- 浏览器验收
def make_context(browser, mode):
    if mode == 'desktop':
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900},
                                  device_scale_factor=1, locale='zh-CN')
    else:
        ctx = browser.new_context(viewport={'width': 390, 'height': 844},
                                  device_scale_factor=2, is_mobile=True, has_touch=True,
                                  locale='zh-CN')
    ctx.set_extra_http_headers({
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
    })
    return ctx


def collect_events(page, base, bucket):
    def on_console(msg):
        if msg.type == 'error':
            bucket['console_errors'].append({'text': msg.text[:500]})

    def on_pageerror(exc):
        bucket['pageerrors'].append({'text': str(exc)[:800]})

    def on_response(resp):
        try:
            status = resp.status
            url = resp.url
        except Exception:  # noqa: BLE001
            return
        if status >= 400 and url.startswith(base):
            if 'favicon' in url:
                return
            bucket['failed_requests'].append({'status': status, 'url': url[:300]})

    def on_requestfailed(req):
        failure = req.failure or ''
        bucket['request_failures'].append({'url': req.url[:300], 'failure': str(failure)[:300]})

    page.on('console', on_console)
    page.on('pageerror', on_pageerror)
    page.on('response', on_response)
    page.on('requestfailed', on_requestfailed)


def mark_panels(page, titles):
    try:
        return page.evaluate(MARK_JS, titles)
    except Exception as exc:  # noqa: BLE001
        return {'found': {}, 'missing': titles, 'error': str(exc)}


def find_panel(page, title):
    loc = page.locator('[data-qa-panel="%s"]' % title)
    try:
        return loc if loc.count() else None
    except Exception:  # noqa: BLE001
        return None


def snapshot(page, title):
    try:
        return page.evaluate(SNAPSHOT_JS, title)
    except Exception:  # noqa: BLE001
        return None


def find_chip(page, title, texts, attrs):
    try:
        return page.evaluate(CHIP_JS, {'title': title, 'texts': texts, 'attrs': attrs})
    except Exception as exc:  # noqa: BLE001
        return {'found': False, 'reason': 'evaluate-error: %s' % exc}


def clear_chips(page):
    try:
        page.evaluate("() => document.querySelectorAll('[data-qa-chip]')"
                      ".forEach((el) => el.removeAttribute('data-qa-chip'))")
    except Exception:  # noqa: BLE001
        pass


def click_chip(page):
    loc = page.locator('[data-qa-chip="1"]')
    try:
        loc.first.scroll_into_view_if_needed(timeout=2000)
    except Exception:  # noqa: BLE001
        pass
    try:
        loc.first.click(timeout=4000)
        return 'playwright-click'
    except Exception:  # noqa: BLE001
        try:
            clicked = page.evaluate(
                "() => { const el = document.querySelector('[data-qa-chip=\"1\"]');"
                " if (!el) return false; el.click(); return true; }")
            return 'js-click' if clicked else 'click-failed'
        except Exception:  # noqa: BLE001
            return 'click-failed'


def take_screenshot(page, locator, path):
    try:
        if locator is not None:
            locator.scroll_into_view_if_needed(timeout=2500)
            page.wait_for_timeout(250)
            locator.screenshot(path=str(path), timeout=15000)
        else:
            page.screenshot(path=str(path), full_page=False)
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            page.screenshot(path=str(path), full_page=False)
            return True
        except Exception:  # noqa: BLE001
            return False


def text_assertions(report, page, page_text, headings, mode):
    tc = title_compact(page_text)

    # 1) 新段落存在
    missing_sections = [t for t in NEW_SECTIONS if title_compact(t) not in tc]
    report.add('structure.new_sections', 'structure', not missing_sections,
               '新段落齐全（%d/%d）' % (len(NEW_SECTIONS) - len(missing_sections), len(NEW_SECTIONS))
               if not missing_sections else '缺少新段落：%s' % '、'.join(missing_sections),
               {'missing': missing_sections, 'headings': headings[:40]})

    # 2) 旧面板 / 旧套层不出现
    present_old = [t for t in REMOVED_TOKENS if compact(t) in compact(page_text)
                   or (t.isascii() and t.lower() in (page_text or '').lower())]
    report.add('structure.removed_panels', 'structure', not present_old,
               '旧面板/旧套层未出现' if not present_old else '仍出现已删除内容：%s' % '、'.join(present_old),
               {'present': present_old,
                'snippets': {t: lines_with(page_text, t, 2) for t in present_old if t.isascii() or True}})

    # 3) 禁词
    raw = page_text or ''
    banned_hits = {}
    for term in BANNED_TERMS:
        if term == 'pp':
            hits = [ln.strip()[:160] for ln in raw.splitlines()
                    if re.search(r'(?<![A-Za-z])pp(?![A-Za-z])', ln, re.I)]
        else:
            hits = lines_with(raw, term)
        if hits:
            banned_hits[term] = hits[:4]
    report.add('copy.banned_terms', 'copy', not banned_hits,
               '禁词（%s）未出现' % ' / '.join(BANNED_TERMS) if not banned_hits
               else '出现禁词：%s' % '、'.join(banned_hits.keys()),
               {'hits': banned_hits})

    extra_hits = {}
    for term in EXTRA_TERMS:
        hits = lines_with(raw, term, 3)
        if hits:
            extra_hits[term] = hits
    report.warn('copy.extra_terms', 'copy', not extra_hits,
                '额外统计术语未出现' if not extra_hits else '出现额外统计术语：%s' % '、'.join(extra_hits.keys()),
                {'hits': extra_hits})

    # 4) 分路对位不出现 KDA
    lane_panel_text = None
    lane_loc = find_panel(page, '分路对位')
    if lane_loc is not None:
        try:
            lane_panel_text = lane_loc.first.inner_text()
        except Exception:  # noqa: BLE001
            lane_panel_text = None
    if lane_panel_text is None:
        report.warn('copy.lane_no_kda', 'copy', True, '未找到「分路对位」区域，跳过 KDA 检查', {})
    else:
        kda_hits = [ln.strip()[:160] for ln in lane_panel_text.splitlines() if re.search('KDA', ln, re.I)]
        report.add('copy.lane_no_kda', 'copy', not kda_hits,
                   '分路对位不含 KDA' if not kda_hits else '分路对位出现 KDA',
                   {'hits': kda_hits[:6],
                    'panel_text_len': len(lane_panel_text)})
    page_kda = [ln.strip()[:160] for ln in raw.splitlines() if re.search(r'\bKDA\b', ln, re.I)]
    report.warn('copy.page_kda', 'copy', not page_kda,
                '整页未出现 KDA' if not page_kda else '整页仍出现 KDA（契约要求改称「对抗」）',
                {'hits': page_kda[:8]})

    # 4b) 用户重点：游走路不能出现分均经济 / 分均输出
    if lane_panel_text is not None:
        walk_card = page.evaluate(CARD_JS, {'title': '分路对位', 'lane': '游走'})
        if not walk_card:
            report.warn('copy.walk_lane_metrics', 'copy', True,
                        '未能在分路对位中定位「游走」卡片，跳过游走指标检查', {})
        else:
            walk_text = walk_card.get('t') or ''
            disallowed = [w for w in ('分均经济', '分均输出') if w in walk_text]
            allowed = [w for w in ('分均承伤', '参团率', '分均控制', '分均治疗') if w in walk_text]
            report.add('copy.walk_lane_metrics', 'copy', not disallowed,
                       '游走路未出现分均经济/分均输出' if not disallowed
                       else '游走路出现不该有的指标：%s' % '、'.join(disallowed),
                       {'card_cls': walk_card.get('cls'), 'disallowed': disallowed,
                        'allowed_present': allowed, 'card_text': walk_text[:600]})
            report.warn('copy.walk_lane_allowed', 'copy', len(allowed) >= 2,
                        '游走路指标：%s' % '、'.join(allowed) if allowed
                        else '游走路未见承伤/参团/控制/治疗指标',
                        {'allowed_present': allowed})
    else:
        report.warn('copy.walk_lane_metrics', 'copy', True,
                    '未找到分路对位区域，跳过游走指标检查', {})

    # 4c) 用户重点：资源分配不能用 pp / 统计术语
    res_loc = find_panel(page, '资源与对位')
    if res_loc is None:
        report.warn('copy.resource_no_stats', 'copy', True,
                    '未找到「资源与对位」区域，跳过统计术语检查', {})
    else:
        try:
            res_text = res_loc.first.inner_text()
        except Exception:  # noqa: BLE001
            res_text = ''
        res_hits = {}
        for term in BANNED_TERMS:
            if term == 'pp':
                hits = [ln.strip()[:140] for ln in res_text.splitlines()
                        if re.search(r'(?<![A-Za-z])pp(?![A-Za-z])', ln, re.I)]
            else:
                hits = lines_with(res_text, term)
            if hits:
                res_hits[term] = hits[:4]
        report.add('copy.resource_no_stats', 'copy', not res_hits,
                   '资源与对位未使用 pp/统计术语' if not res_hits
                   else '资源与对位出现统计术语：%s' % '、'.join(res_hits.keys()),
                   {'hits': res_hits, 'panel_text_len': len(res_text)})

    # 4d) 用户重点：样本 < 3 局不能出现胜率结论
    if report.team_matches is not None and report.team_matches < 3:
        def _winrate_conclusions(text, scope):
            out = []
            for ln in (text or '').splitlines():
                s = ln.strip()
                if '胜率' not in s or not re.search(r'\d+(?:\.\d+)?\s*%', s):
                    continue
                if any(x in s for x in ('样本', '证据不足', '单局', 'KPL', '官方', '参考')):
                    continue
                if scope == '对位与关联' and not any(x in s for x in ('对手胜率', '交手', '我们')):
                    continue
                out.append(s[:160])
            return out

        scope_ids = {'打法与资源': 'system', '选人模式': 'bp', '证据与方法': 'combos'}
        for title, scope_id in scope_ids.items():
            loc = find_panel(page, title)
            ident = 'copy.no_winrate_%s' % scope_id
            if loc is None:
                report.warn(ident, 'copy', True,
                            '未找到「%s」区域，跳过胜率结论检查' % title, {})
                continue
            try:
                panel_text = loc.first.inner_text()
            except Exception:  # noqa: BLE001
                panel_text = ''
            hits = _winrate_conclusions(panel_text, title)
            report.add(ident, 'copy', not hits,
                       '%s：样本 %s 局未给胜率结论' % (title, report.team_matches) if not hits
                       else '%s：样本仅 %s 局却出现胜率结论' % (title, report.team_matches),
                       {'hits': hits[:6], 'team_matches': report.team_matches,
                        'panel_text_len': len(panel_text)})
    else:
        report.warn('copy.no_winrate_system', 'copy', True,
                    '未取得样本局数或样本≥3，跳过「样本<3 不给胜率结论」检查',
                    {'team_matches': report.team_matches})

    # 5) 打法画像内容标记（标题可能改写，只告警）
    missing_profile = [t for t in PROFILE_MARKERS if compact(t) not in compact(raw)]
    report.warn('copy.profile_markers', 'copy', not missing_profile,
                '打法画像标记齐全' if not missing_profile else '打法画像缺少标记：%s' % '、'.join(missing_profile),
                {'missing': missing_profile})

    # 6) 样本话术（该战队 1 局，必须提示单局参考）
    report.add('copy.sample_note', 'copy', '样本' in raw,
               '页面含样本说明' if '样本' in raw else '页面没有任何样本说明',
               {'sample_lines': lines_with(raw, '样本', 5)})
    if report.team_matches is not None and report.team_matches < 3:
        thin_ok = any(t in raw for t in ('单局参考', '样本不足', '证据不足'))
        report.add('copy.single_game_note', 'copy', thin_ok,
                   '样本不足话术存在' if thin_ok else '1 局样本未提示「单局参考/样本不足/证据不足」',
                   {'lines': [ln.strip() for ln in raw.splitlines()
                              if any(t in ln for t in ('单局参考', '样本不足', '证据不足'))][:6]})
    else:
        report.warn('copy.single_game_note', 'copy', True,
                    '样本 ≥3 局，跳过「单局参考」话术检查', {'team_matches': report.team_matches})

    # 7) 代理指标标注（契约 §3 只告警）
    proxy_ok = ('终局面板' in raw) or ('代理' in raw)
    report.warn('copy.proxy_label', 'copy', proxy_ok,
                '有终局面板代理标注' if proxy_ok else '未见「终局面板/代理」标注',
                {'lines': [ln.strip()[:160] for ln in raw.splitlines()
                           if ('终局' in ln or '代理' in ln)][:6]})
    seq_ok = any(t in raw for t in ('20 手模板', '显式手序', '禁选顺序'))
    report.warn('copy.no_pick_order_note', 'copy', seq_ok,
                '有手序口径说明（模板/显式）' if seq_ok else '未见手序口径说明',
                {'lines': lines_with(raw, '手序', 4) + lines_with(raw, '禁选顺序', 4)})
    per_game_ok = '逐局识别' in raw
    report.warn('copy.per_game_note', 'copy', per_game_ok,
                '有「逐局识别」说明' if per_game_ok else '未见「逐局识别」说明',
                {'lines': lines_with(raw, '逐局', 5)})

    # 8) 四象限时间窗 chips（只告警，交互另测）
    style_loc = find_panel(page, '团队风格四象限')
    if style_loc is not None:
        try:
            style_text = style_loc.first.inner_text()
        except Exception:  # noqa: BLE001
            style_text = ''
        present = [w for w in ('7天', '15天', '30天') if compact(w) in compact(style_text)]
        report.warn('copy.style_windows', 'copy', len(present) >= 2,
                    '四象限时间窗：%s' % '、'.join(present) if present else '四象限未见 7/15/30 天时间窗',
                    {'present': present})
    else:
        report.warn('copy.style_windows', 'copy', True, '未找到「团队风格四象限」区域，跳过窗口检查', {})


def interaction_assertions(report, page, mode):
    for ident, title, texts, attrs, desc in INTERACTIONS:
        mark_panels(page, NEW_SECTIONS + PANEL_SUBTITLES)
        before = snapshot(page, title)
        if before is None:
            report.add(ident, 'interaction', False, '%s：未找到「%s」区域' % (desc, title),
                       {'panel': title})
            continue
        chip = find_chip(page, title, texts, attrs)
        if not chip.get('found'):
            report.add(ident, 'interaction', False,
                       '%s：在「%s」内未找到目标 chip %r' % (desc, title, texts),
                       {'panel': title, 'chip_search': chip, 'attrs': attrs})
            continue
        how = click_chip(page)
        page.wait_for_timeout(800)
        clear_chips(page)
        mark_panels(page, NEW_SECTIONS + PANEL_SUBTITLES)
        after = snapshot(page, title)
        chip_after = find_chip(page, title, texts, attrs)
        clear_chips(page)
        if after is None:
            report.add(ident, 'interaction', False, '%s：点击后「%s」区域消失' % (desc, title),
                       {'chip': chip, 'click': how})
            continue
        text_changed = (before.get('text') or '') != (after.get('text') or '')
        active_before = before.get('active') or []
        active_after = after.get('active') or []
        active_changed = active_before != active_after
        chip_state_before = {k: chip.get(k) for k in ('cls', 'pressed', 'selected', 'current')}
        chip_state_after = {k: chip_after.get(k) for k in ('cls', 'pressed', 'selected', 'current')}
        chip_changed = chip_state_before != chip_state_after
        ok = text_changed or active_changed or chip_changed
        evidence = {
            'panel': title,
            'chip_clicked': chip.get('text'),
            'match_by': chip.get('by'),
            'click_method': how,
            'text_changed': text_changed,
            'active_changed': active_changed,
            'chip_state_changed': chip_changed,
            'before_len': len(before.get('text') or ''),
            'after_len': len(after.get('text') or ''),
            'active_before': active_before[:8],
            'active_after': active_after[:8],
            'chip_before': chip_state_before,
            'chip_after': chip_state_after,
            'removed_lines': diff_lines(before.get('text'), after.get('text')),
            'added_lines': diff_lines(after.get('text'), before.get('text')),
        }
        detail = '%s：%s' % (desc, '面板文本/class 有变化' if ok
                             else '点击后目标区域文本与 class 均未变化')
        report.add(ident, 'interaction', ok, detail, evidence)


def runtime_assertions(report, mode, bucket, base):
    console_errors = bucket['console_errors']
    pageerrors = bucket['pageerrors']
    failed_requests = bucket['failed_requests']
    request_failures = bucket['request_failures']

    # 已知环境噪音（更新检查 404）：单列告警，不计入战队页 v2 验收失败
    noise = [r for r in failed_requests if any(m in r['url'] for m in NOISE_URL_MARKERS)]
    real_http_fail = [r for r in failed_requests if r not in noise]
    generic_net = [e for e in console_errors if 'Failed to load resource' in (e.get('text') or '')]
    other_console = [e for e in console_errors if e not in generic_net]
    # 仅当失败请求全部是已知噪音时，忽略浏览器为这些 404 打印的通用网络错误
    noise_console = generic_net if (noise and not real_http_fail and not other_console) else []
    real_console = [e for e in console_errors if e not in noise_console]
    if noise:
        report.warn('runtime.known_noise_%s' % mode, 'runtime', False,
                    '已知环境噪音（与战队页无关）：%d 条 %s'
                    % (len(noise), ', '.join(sorted({r['url'] for r in noise})[:3])),
                    {'noise': noise[:6], 'ignored_console': noise_console[:4]})

    report.add('runtime.console_%s' % mode, 'runtime', not real_console,
               '无 console error' if not real_console else 'console error %d 条' % len(real_console),
               {'errors': real_console[:12], 'ignored_noise': noise_console[:4]})
    report.add('runtime.pageerror_%s' % mode, 'runtime', not pageerrors,
               '无 pageerror' if not pageerrors else 'pageerror %d 条' % len(pageerrors),
               {'pageerrors': pageerrors[:8]})

    # 4xx/5xx：忽略 favicon 与已知噪音；其余视为失败
    report.add('runtime.http_%s' % mode, 'runtime', not real_http_fail,
               '无失败请求（4xx/5xx）' if not real_http_fail else '失败请求 %d 条' % len(real_http_fail),
               {'failed_requests': real_http_fail[:12], 'ignored_noise': noise[:6]})
    fatal_req = [r for r in request_failures if 'ERR_ABORTED' not in (r.get('failure') or '')]
    report.add('runtime.requestfailed_%s' % mode, 'runtime', not fatal_req,
               '无异常中断请求' if not fatal_req else '请求中断 %d 条' % len(fatal_req),
               {'request_failures': request_failures[:12], 'fatal': fatal_req[:8]})


def layout_assertions(report, mode, overflow):
    """页面级横向溢出必须为 0；容器内横向滚动允许；被 overflow:hidden 裁掉且无法滚动的内容算失败。"""
    offenders = overflow.get('offenders') or []
    page_overflow = overflow.get('overflow', 0)
    ok = page_overflow <= 4
    report.add('layout.no_overflow_%s' % mode, 'layout', ok,
               '页面级无横向溢出（scrollWidth=%s / clientWidth=%s）'
               % (overflow.get('scrollWidth'), overflow.get('clientWidth'))
               if ok else '页面级横向溢出：scrollWidth=%s / clientWidth=%s'
               % (overflow.get('scrollWidth'), overflow.get('clientWidth')),
               {'overflow_px': page_overflow, 'offenders': offenders[:10]})

    scrollable = [x for x in offenders if x.get('scrollable')]
    clipped = [x for x in offenders if x.get('clipped') and not x.get('scrollable')]
    if scrollable:
        report.warn('layout.inner_scroll_%s' % mode, 'layout', True,
                    '存在容器内横向滚动（允许）：%s'
                    % ', '.join(sorted({str(x.get('container')) for x in scrollable})[:4]),
                    {'scrollable': scrollable[:8]})
    report.add('layout.clipped_content_%s' % mode, 'layout', not clipped,
               '没有内容被裁切且无法滚动查看' if not clipped
               else '有内容被 overflow:hidden 裁切且无法滚动查看：%d 处' % len(clipped),
               {'clipped': clipped[:10]})


def mobile_collapse_assertion(report, page, mode):
    info = page.evaluate("""() => ({
      height: document.documentElement.scrollHeight,
      bodies: [...document.querySelectorAll('.tp-sec-body')].map((b) => getComputedStyle(b).display),
      toggles: [...document.querySelectorAll('[data-tp-toggle]')].map((b) => b.textContent),
    })""")
    bodies = info.get('bodies') or []
    collapsed = len(bodies) >= 2 and bodies[0] != 'none' and all(b == 'none' for b in bodies[1:])
    short = (info.get('height') or 0) < 6000
    report.add('layout.mobile_collapse_%s' % mode, 'layout', collapsed and short,
               '移动端默认折叠 02–05，页面高度 %s px' % info.get('height') if collapsed and short
               else '移动端折叠异常：bodies=%s height=%s' % (bodies, info.get('height')),
               info)
    if bodies:
        try:
            toggle = page.locator('[data-tp-toggle]').nth(1)
            toggle.click(timeout=4000)
            page.wait_for_timeout(300)
            opened = page.evaluate("() => getComputedStyle(document.querySelectorAll('.tp-sec-body')[1]).display")
            report.add('interaction.mobile_section_toggle', 'interaction', opened != 'none',
                       '移动端段头「展开」可打开内容' if opened != 'none'
                       else '点击「展开」后内容仍未显示', {'display': opened})
        except Exception as exc:  # noqa: BLE001
            report.add('interaction.mobile_section_toggle', 'interaction', False,
                       '移动端段头展开失败：%s' % exc, {})


def quadrant_hint_assertion(report, page, mode):
    info = page.evaluate(QUAD_HINT_JS, '团队风格四象限')
    if not info:
        report.warn('layout.quadrant_scroll_hint_%s' % mode, 'layout', True,
                    '未找到团队风格四象限区域，跳过滚动提示检查', {})
        return
    scrolls = info.get('scrollW', 0) > info.get('clientW', 0) + 2
    hints = info.get('hints') or []
    attr_hints = info.get('attrHints') or []
    has_hint = bool(hints or attr_hints)
    if not scrolls:
        report.warn('layout.quadrant_scroll_hint_%s' % mode, 'layout', True,
                    '四象限图无需横向滚动（scrollW=%s / clientW=%s）'
                    % (info.get('scrollW'), info.get('clientW')), info)
        return
    report.add('layout.quadrant_scroll_hint_%s' % mode, 'layout', has_hint,
               '四象限图可横向滚动且有可见提示' if has_hint
               else '四象限图在窄屏需横向滚动（scrollW=%s / clientW=%s），但没有可见滚动提示'
               % (info.get('scrollW'), info.get('clientW')),
               info)


def manual_dom_assertions(report, page):
    """用户最在意的点：分路对位指标、资源分配控件、四象限读法、喜欢什么布局、KPL 空阵容/年份。"""
    try:
        dom = page.evaluate(TEAM_DOM_JS)
    except Exception as exc:  # noqa: BLE001
        report.add('copy.dom_probe', 'copy', False, '页面结构探测失败：%s' % exc, {})
        return

    # G 分路对位：五卡、各分路指标、发育路首项、游走只看承伤/参团/控制/治疗
    duel = {row.get('lane'): row.get('metrics') or [] for row in (dom.get('duel') or [])}
    expected = {
        '对抗路': ['分均承伤', '参团率', '场均推塔', '分均经济'],
        '打野': ['分均经济', '参团率', '场均击杀参与', '队伍控龙'],
        '中路': ['分均输出', '分均经济', '参团率'],
        '发育路': ['分均经济', '分均输出', '参团率'],
        '游走': ['分均承伤', '参团率', '分均控制', '分均治疗'],
    }
    duel_bad = []
    for lane, metrics in expected.items():
        got = duel.get(lane)
        if not got:
            duel_bad.append('%s：缺少卡片' % lane)
            continue
        if got != metrics:
            duel_bad.append('%s：指标为 %s，契约要求 %s' % (lane, got, metrics))
        if 'KDA' in ''.join(got) or '击杀死亡比' in ''.join(got):
            duel_bad.append('%s：出现 KDA/击杀死亡比' % lane)
    report.add('copy.duel_lane_metrics', 'copy', not duel_bad,
               '五路对位指标符合契约（游走仅承伤/参团/控制/治疗，发育路首项分均经济）'
               if not duel_bad else '分路对位指标不符合契约',
               {'problems': duel_bad[:8], 'duel': duel})

    # D 资源与对位：五路份额 + 同位置对位差
    res = dom.get('resource') or {}
    res_bad = []
    if res.get('lanes') != ['对抗路', '打野', '中路', '发育路', '游走']:
        res_bad.append('分路=%s' % res.get('lanes'))
    if not res.get('table'):
        res_bad.append('缺少资源对位表')
    if not res.get('laneDiff'):
        res_bad.append('缺少对位差列')
    report.add('copy.resource_controls', 'copy', not res_bad,
               '资源与对位：五路份额 + 同位置对位差齐全' if not res_bad
               else '资源与对位结构缺失', {'problems': res_bad, 'resource': res})

    # C 英雄池：五条分路行（类型胶囊 + 英雄胶囊）
    likes = dom.get('likes') or {}
    likes_cards = likes.get('cards') or []
    likes_bad = []
    if sorted(likes_cards) != sorted(['对抗路', '打野', '中路', '发育路', '游走']):
        likes_bad.append('分路行=%s' % likes_cards)
    report.add('copy.likes_layout', 'copy', not likes_bad,
               '英雄池：5 个分路行齐全' if not likes_bad
               else '英雄池布局不符合要求', {'problems': likes_bad, 'likes': likes})

    # E 四象限：轴方向读法 + 单局样本话术 + 队伍推塔口径
    style_text = (dom.get('style') or {}).get('text') or ''
    axis_ok = all(t in style_text for t in ('单核', '多核', '打架', '运营'))
    dir_ok = ('经济分配' in style_text) and ('终局面板' in style_text or '代理' in style_text)
    report.add('copy.quadrant_axes', 'copy', axis_ok and dir_ok,
               '四象限轴可读（单核/多核、打架/运营 + 终局面板代理标注）'
               if axis_ok and dir_ok else '四象限轴文案不完整',
               {'axis_ok': axis_ok, 'dir_ok': dir_ok,
                'lines': [ln.strip()[:160] for ln in style_text.splitlines()
                          if any(k in ln for k in ('单核', '多核', '打架', '运营', '终局'))][:8]})
    classify_ok = ('暂不归类' in style_text) or ('单局参考' in style_text)
    report.warn('copy.quadrant_no_classify_wording', 'copy', classify_ok,
                '四象限有「暂不归类 / 单局参考」话术' if classify_ok
                else '四象限未出现「暂不归类 / 单局参考」话术',
                {'has_wording': classify_ok})
    proxy_ok = '终局面板' in style_text
    report.warn('copy.team_towers_note', 'copy', proxy_ok,
                '四象限标注终局面板代理' if proxy_ok else '四象限未标注终局面板代理',
                {'lines': [ln.strip()[:200] for ln in style_text.splitlines()
                          if '推塔' in ln or '口径' in ln or '终局' in ln][:8]})

    # H Ban 形状：分路 / 类型图例
    bp_rows = (dom.get('bp') or {}).get('lanes') or []
    report.add('copy.bp_lane_chips', 'copy', len(bp_rows) >= 4,
               'Ban 分路/类型图例可用（%d 项）' % len(bp_rows) if len(bp_rows) >= 4
               else 'Ban 分路/类型图例缺失：%s' % bp_rows, {'rows': bp_rows[:12]})

    # I 阵容组合：空 lineup 证据不足 + 年份不带千分位
    kpl_text = (dom.get('kpl') or {}).get('text') or ''
    kpl_bad = []
    if not kpl_text:
        kpl_bad.append('未找到 KPL 职业参照区域')
    elif re.search(r'2[,，]\d{3}', kpl_text):
        kpl_bad.append('年份出现千分位（如 2,026）')
    report.add('copy.kpl_empty_and_year', 'copy', not kpl_bad,
               'KPL 参照：区域存在，年份无千分位' if not kpl_bad
               else 'KPL 参照文案/年份格式问题', {'problems': kpl_bad,
                                                 'text': kpl_text[:400]})

    # J 英雄头像可跳转（v3.1）
    hero_links = dom.get('hero_links') or dom.get('heroLinks') or []
    bad_links = [h for h in hero_links if not h.startswith('#hero/')]
    report.add('copy.hero_links', 'copy', len(hero_links) >= 20 and not bad_links,
               '英雄头像可点进英雄详情（%d 个链接）' % len(hero_links) if hero_links and not bad_links
               else '英雄头像链接缺失或不是 #hero/：%d 个，异常 %d' % (len(hero_links), len(bad_links)),
               {'count': len(hero_links), 'bad': bad_links[:6]})

    # K 未标注口径（v3.1）：不再出现「待分类」，并解释未标注来源
    page_text = dom.get('text') or ''
    no_pending = '待分类' not in page_text
    explains = ('未标注' not in page_text) or ('英雄分类表' in page_text)
    report.add('copy.unlabeled_wording', 'copy', no_pending and explains,
               '类型缺标统一写「未标注」并说明来源' if no_pending and explains
               else '仍出现「待分类」或未解释「未标注」',
               {'has_pending': not no_pending, 'has_unlabeled': '未标注' in page_text,
                'explains': explains})

    # L 四象限点位不贴边（v3.1：5% 内缩 + 抖动）
    quad = dom.get('quad') or {}
    dots = quad.get('dots') or []
    qw = quad.get('width') or 0
    edge = []
    if qw > 0:
        for dot in dots:
            cx = dot.get('cx') or 0
            if cx < qw * 0.02 or cx > qw * 0.98:
                edge.append(round(cx, 1))
    report.add('layout.quadrant_not_edge', 'layout', len(dots) >= 5 and not edge,
               '四象限 %d 个点均在画布内（远离左右边框）' % len(dots) if len(dots) >= 5 and not edge
               else '四象限点位不足或贴边：%d 个点，贴边 %d' % (len(dots), len(edge)),
               {'dots': len(dots), 'edge': edge[:8], 'width': qw})

    # M 阵容收口：主力体系 3 条 + 体系库折叠 + 五人阵容去重
    systems_ok = (dom.get('systems') or 0) == 3 and bool(dom.get('library')) and (dom.get('fiveRows') or 0) == 0
    report.add('copy.lineups_top3', 'copy', systems_ok,
               '阵容体系：主力体系 3 条 + 体系库折叠，五人阵容已并入' if systems_ok
               else '阵容收口异常：systems=%s library=%s fiveRows=%s' % (dom.get('systems'), dom.get('library'), dom.get('fiveRows')),
               {'systems': dom.get('systems'), 'library': dom.get('library'), 'fiveRows': dom.get('fiveRows')})

    # N 演示数据隐藏
    report.add('copy.demo_hidden', 'copy', not dom.get('demo'),
               '演示系列赛已隐藏' if not dom.get('demo') else '页面仍出现「演示」系列赛',
               {'demo': dom.get('demo')})

    # O 数据范围：不再放会误导的全站筛选按钮，改为页头口径说明
    scope_ok = bool(dom.get('scope')) and (dom.get('filterButtons') or 0) == 0
    report.add('copy.data_scope', 'copy', scope_ok,
               '页头写明「全部营地数据」，不再放无效的数据范围按钮' if scope_ok
               else '口径说明/数据范围按钮处理异常',
               {'scope': dom.get('scope'), 'filterButtons': dom.get('filterButtons')})

    # P 样本量视觉编码 + 摘要复制
    samples_ok = (dom.get('samples') or 0) >= 5
    report.add('copy.sample_badges', 'copy', samples_ok,
               '胜率带样本量标签（%d 处）' % dom.get('samples') if samples_ok
               else '胜率缺少样本量标签（%s 处）' % dom.get('samples'),
               {'samples': dom.get('samples')})
    copy_ok = (dom.get('copySummary') or 0) >= 80
    report.add('copy.copy_summary', 'copy', copy_ok,
               '页头有「复制摘要」且内容完整' if copy_ok
               else '「复制摘要」缺失或内容过短（%s）' % dom.get('copySummary'),
               {'length': dom.get('copySummary')})

    # Q 分析/挖掘：边野频率、关联规则、资源对位、变化异常
    edge_ok = (dom.get('edge') or 0) >= 3
    report.add('copy.edge_patterns', 'copy', edge_ok,
               '边野组合矩阵可用（%s 个非空格）' % dom.get('edge') if edge_ok
               else '边野组合矩阵缺失（%s 个非空格）' % dom.get('edge'),
               {'cells': dom.get('edge')})
    rules_ok = (dom.get('rules') or 0) >= 4
    report.add('copy.association_rules', 'copy', rules_ok,
               '结果关联表可用（%s 条 ≥4 局条件）' % dom.get('rules') if rules_ok
               else '结果关联表缺失或条件不足（%s 条）' % dom.get('rules'),
               {'rows': dom.get('rules')})
    change_ok = bool(dom.get('change')) and (dom.get('changeRows') or 0) >= 4
    report.add('copy.change_anomaly', 'copy', change_ok,
               '变化与异常：前后段对照 + 离群局' if change_ok
               else '变化与异常卡缺失（rows=%s）' % dom.get('changeRows'),
               {'rows': dom.get('changeRows'), 'outliers': dom.get('outliers')})
    lane_diff_ok = bool((dom.get('resource') or {}).get('laneDiff'))
    report.add('copy.resource_lane_diff', 'copy', lane_diff_ok,
               '资源卡含同位置对位差' if lane_diff_ok else '资源卡缺少对位差列',
               {'resource': dom.get('resource')})

    # S BP 时序与 ban 结果（draftEvents 22/25 局）
    bp_text = dom.get('bpOrderText') or ''
    bp_order_ok = (bool(dom.get('bpOrder')) and (dom.get('bpBanSlots') or 0) >= 5
                   and 'ban 顺序' in bp_text and '第一手' in bp_text and '显式' in bp_text)
    report.add('copy.bp_order', 'copy', bp_order_ok,
               'BP 时序卡可读（第一手 / ban 顺序 %s 手 / 显式手序标注）' % dom.get('bpBanSlots')
               if bp_order_ok else 'BP 时序卡缺失或 ban 顺序不完整（%s 手）' % dom.get('bpBanSlots'),
               {'bpOrder': dom.get('bpOrder'), 'banSlots': dom.get('bpBanSlots')})
    ban_text = dom.get('banOutcomeText') or ''
    ban_outcome_ok = (dom.get('banOutcomeRows') or 0) >= 3 and '对手战绩' in ban_text
    report.add('copy.ban_outcome', 'copy', ban_outcome_ok,
               'Ban 与结果条件关联表可用（%s 行，含对手战绩）' % dom.get('banOutcomeRows')
               if ban_outcome_ok else 'Ban 与结果表缺失（%s 行）' % dom.get('banOutcomeRows'),
               {'rows': dom.get('banOutcomeRows'), 'hasRecord': '对手战绩' in ban_text})

    # T 双向 ban×英雄池 / Ban 形状 / 替代结构 / 池深度
    pool = dom.get('banPool') or {}
    pool_ok = ((pool.get('panels') or 0) >= 2 and (pool.get('dots') or 0) >= 20
               and all(term in (pool.get('text') or '') for term in ('针对率', '命中率', '随机期望')))
    report.add('copy.ban_pool', 'copy', pool_ok,
               '双向 Ban×英雄池可用（%s 图 / %s 点）' % (pool.get('panels'), pool.get('dots'))
               if pool_ok else '双向 Ban×英雄池缺失（图 %s / 点 %s）' % (pool.get('panels'), pool.get('dots')),
               {'panels': pool.get('panels'), 'dots': pool.get('dots')})

    shape = dom.get('banShape') or {}
    shape_ok = ((shape.get('stacks') or 0) >= 3 and (shape.get('splits') or 0) >= 4
                and (shape.get('waste') or 0) >= 1
                and all(term in (shape.get('text') or '') for term in ('分路', '低使用率', '前 ', '后 ')))
    report.add('copy.ban_shape', 'copy', shape_ok,
               'Ban 形状可用（%s 条堆叠 / %s 组边时间 / %s 条低使用）' % (shape.get('stacks'), shape.get('splits'), shape.get('waste'))
               if shape_ok else 'Ban 形状缺失（堆叠 %s / 边时间 %s / 低使用 %s）' % (shape.get('stacks'), shape.get('splits'), shape.get('waste')),
               {'stacks': shape.get('stacks'), 'splits': shape.get('splits'), 'waste': shape.get('waste')})

    repl = dom.get('replacement') or {}
    repl_ok = ((repl.get('rows') or 0) >= 4 and (repl.get('cells') or 0) >= 10
               and all(term in (repl.get('text') or '') for term in ('有效替代', '同类型', '主要类型转移')))
    report.add('copy.replacement_structure', 'copy', repl_ok,
               'Ban 替代结构可用（%s 行 / %s 矩阵格）' % (repl.get('rows'), repl.get('cells'))
               if repl_ok else 'Ban 替代结构缺失（%s 行 / %s 格）' % (repl.get('rows'), repl.get('cells')),
               {'rows': repl.get('rows'), 'cells': repl.get('cells')})

    depth = dom.get('poolDepth') or {}
    depth_ok = (depth.get('rows') == 5 and (depth.get('kpl') or 0) >= 3
                and '有效' in (depth.get('text') or '') and 'KPL' in (depth.get('text') or ''))
    report.add('copy.pool_depth', 'copy', depth_ok,
               '五路池深度可用（%s 路 / %s 条 KPL）' % (depth.get('rows'), depth.get('kpl'))
               if depth_ok else '五路池深度缺失（%s 路 / %s 条 KPL）' % (depth.get('rows'), depth.get('kpl')),
               {'rows': depth.get('rows'), 'kpl': depth.get('kpl')})

    # R 可视化编码：边野矩阵 / 资源小条 / 关联提升点 / 滚动胜率
    visual_ok = (dom.get('edge') or 0) >= 3 and (dom.get('lift') or 0) >= 4 and (dom.get('resourceBars') or 0) >= 10 and bool(dom.get('spark'))
    report.add('copy.visual_encoding', 'copy', visual_ok,
               '可视化编码齐全（边野格 %s / 提升点 %s / 资源条 %s / 滚动线 %s）' % (dom.get('edge'), dom.get('lift'), dom.get('resourceBars'), dom.get('spark'))
               if visual_ok else '可视化编码缺失（边野格 %s / 提升点 %s / 资源条 %s / 滚动线 %s）' % (dom.get('edge'), dom.get('lift'), dom.get('resourceBars'), dom.get('spark')),
               {'edge': dom.get('edge'), 'lift': dom.get('lift'), 'resourceBars': dom.get('resourceBars'), 'spark': dom.get('spark')})


def run_mode(report, browser, mode, args, out):
    mode_out = out if mode == 'desktop' else out
    ctx = make_context(browser, mode)
    page = ctx.new_page()
    page.add_init_script(INIT_SCRIPT)
    bucket = {'console_errors': [], 'pageerrors': [], 'failed_requests': [], 'request_failures': []}
    collect_events(page, args.base.rstrip('/'), bucket)
    url = '%s/#team/%s' % (args.base.rstrip('/'), args.team)
    screenshots = []
    headings = []
    page_text = ''
    mode_info = {'url': url, 'viewport': None}

    try:
        page.set_default_timeout(30000)
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.add_style_tag(content=STABLE_CSS)
        viewport = page.viewport_size or {}
        mode_info['viewport'] = viewport
        try:
            page.wait_for_function(READY_JS, timeout=args.timeout)
        except Exception:  # noqa: BLE001
            report.warn('runtime.ready_%s' % mode, 'runtime', False,
                        '页面在 %dms 内未达到就绪条件（可能仍在加载）' % args.timeout, {})
        try:
            page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        # 新页面数据渲染可能晚于 networkidle：等新段落出现（旧页面会超时，可接受）
        try:
            page.wait_for_function(
                "() => (document.querySelector('#content') || document.body).innerText"
                ".replace(/\\s+/g, '').includes('证据与方法')", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(700)

        headings = page.evaluate(HEADINGS_JS)
        page_text = page.evaluate(
            "() => ((document.querySelector('#content') || document.body).innerText || '').trim()")
        body_len = len(compact(page_text))
        (out / ('%s-page-text.txt' % mode)).write_text(page_text, encoding='utf-8')
        mark_info = mark_panels(page, NEW_SECTIONS + PANEL_SUBTITLES)
        mode_info['panels'] = mark_info

        # 全页截图
        full = out / ('%s-full.png' % mode)
        try:
            page.screenshot(path=str(full), full_page=True, timeout=30000)
            screenshots.append(str(full))
        except Exception as exc:  # noqa: BLE001
            report.warn('runtime.fullshot_%s' % mode, 'runtime', False,
                        '全页截图失败：%s' % exc, {})
        mode_info['page_text_len'] = body_len

        if mode == 'desktop':
            # 关键段截图
            for title, slug in SHOT_SECTIONS:
                loc = find_panel(page, title)
                shot = out / ('desktop-%s.png' % slug)
                if loc is not None:
                    ok = take_screenshot(page, loc.first, shot)
                else:
                    # 打法画像缺失时退回首屏，保证有对照图
                    ok = take_screenshot(page, None, shot)
                if ok:
                    screenshots.append(str(shot))
                else:
                    report.warn('runtime.section_shot_%s' % slug, 'runtime', False,
                                '关键段截图失败：%s' % title, {})
        else:
            # 手机端关键段：四象限 + 分路对位（响应式重点）
            for title, slug in (('团队风格四象限', 'style'), ('分路对位', 'lanes')):
                loc = find_panel(page, title)
                if loc is not None:
                    shot = out / ('mobile-section-%s.png' % slug)
                    if take_screenshot(page, loc.first, shot):
                        screenshots.append(str(shot))

        # 布局
        overflow = page.evaluate(OVERFLOW_JS)
        layout_assertions(report, mode, overflow)
        if mode == 'mobile':
            quadrant_hint_assertion(report, page, mode)
            mobile_collapse_assertion(report, page, mode)

        # 文案 / 结构断言（只在桌面跑，避免重复计数；若只跑手机则退化到手机）
        if mode == 'desktop' or args.desktop is False:
            text_assertions(report, page, page_text, headings, mode)
            manual_dom_assertions(report, page)

        # 交互冒烟（桌面）
        if mode == 'desktop':
            interaction_assertions(report, page, mode)

        # 交互后再看一眼有没有新增错误
        page.wait_for_timeout(400)
    except Exception as exc:  # noqa: BLE001
        report.add('runtime.crash_%s' % mode, 'runtime', False,
                   '浏览器验收执行异常：%s' % exc,
                   {'traceback': traceback.format_exc()[-1500:]})
    finally:
        runtime_assertions(report, mode, bucket, args.base.rstrip('/'))
        mode_info['console'] = bucket
        mode_info['screenshots'] = screenshots
        mode_info['headings'] = headings
        report.modes_data[mode] = mode_info
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    return mode_info


# --------------------------------------------------------------------------- 输出
def write_outputs(report):
    payload = {
        'meta': {
            'script': 'scripts/verify_team_page.py',
            'contract': 'docs/team_page_v2.md',
            'base': report.base,
            'team': report.team,
            'url': '%s/#team/%s' % (report.base.rstrip('/'), report.team),
            'startedAt': report.started,
            'finishedAt': datetime.now().isoformat(timespec='seconds'),
            'modes': report.modes,
            'baseline': report.baseline,
            'out': str(report.out),
        },
        'summary': report.summary(),
        'assertions': report.items,
        'modes': report.modes_data,
        'notes': report.notes,
        'api_raw': report.api_raw_path,
    }
    write_json(report.out / 'report.json', payload)

    lines = []
    lines.append('战队页 v2 验收报告')
    lines.append('=' * 60)
    lines.append('时间：%s' % report.started)
    lines.append('URL ：%s/#team/%s' % (report.base.rstrip('/'), report.team))
    lines.append('模式：%s%s' % ('/'.join(report.modes), '（基线记录，失败不计退出码）' if report.baseline else ''))
    s = report.summary()
    lines.append('结果：%s  通过 %d / 失败 %d / 告警 %d（共 %d 条断言）'
                 % (s['result'], s['passed'], s['failed'], s['warnings'], s['total']))
    lines.append('')
    if report.failures:
        lines.append('失败明细：')
        for item in report.failures:
            lines.append('- [%s] %s' % (item['id'], item['detail']))
    else:
        lines.append('失败明细：无')
    lines.append('')
    if report.warnings:
        lines.append('告警：')
        for item in report.warnings:
            lines.append('- [%s] %s' % (item['id'], item['detail']))
    else:
        lines.append('告警：无')
    lines.append('')
    lines.append('断言全量（PASS/FAIL/WARN）：')
    for item in report.items:
        flag = 'PASS' if item['ok'] else ('FAIL' if item['severity'] == 'fail' else 'WARN')
        lines.append('[%s] %-34s %s' % (flag, item['id'], item['detail']))
    lines.append('')
    lines.append('控制台 / 网络：')
    for mode, info in report.modes_data.items():
        bucket = info.get('console') or {}
        lines.append('- %s：console error %d、pageerror %d、失败请求 %d、中断请求 %d'
                     % (mode, len(bucket.get('console_errors') or []),
                        len(bucket.get('pageerrors') or []),
                        len(bucket.get('failed_requests') or []),
                        len(bucket.get('request_failures') or [])))
    lines.append('')
    lines.append('截图（%d 张）：' % sum(len(i.get('screenshots') or []) for i in report.modes_data.values()))
    for mode, info in report.modes_data.items():
        for path in info.get('screenshots') or []:
            lines.append('- %s' % path)
    if report.notes:
        lines.append('')
        lines.append('关键事实：')
        for note in report.notes:
            lines.append('- %s' % note)
    lines.append('')
    lines.append('机器可读结果：%s' % (report.out / 'report.json'))
    (report.out / 'summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description='战队页 v2 浏览器验收（只读）')
    ap.add_argument('--base', default=DEFAULT_BASE, help='服务地址，默认 %s' % DEFAULT_BASE)
    ap.add_argument('--team', default=DEFAULT_TEAM, help='战队 ID，默认 %s' % DEFAULT_TEAM)
    ap.add_argument('--out', default='.screenshots/team-v2', help='输出目录')
    ap.add_argument('--desktop', dest='desktop', action='store_true', help='跑 1440 桌面（默认）')
    ap.add_argument('--mobile', dest='mobile', action='store_true', help='跑 390 手机（默认）')
    ap.add_argument('--no-desktop', dest='desktop', action='store_false')
    ap.add_argument('--no-mobile', dest='mobile', action='store_false')
    ap.add_argument('--baseline', action='store_true', help='基线模式：记录现状，断言失败也退出 0')
    ap.add_argument('--timeout', type=int, default=20000, help='页面就绪等待毫秒，默认 20000')
    ap.add_argument('--api-timeout', type=int, default=60, help='API 请求超时秒，默认 60')
    ap.add_argument('--skip-api', action='store_true', help='跳过 /api/v3/team-deep 数据自检')
    ap.add_argument('--api-only', action='store_true', help='只跑 API 数据自检（team-deep + studio/teams），不开浏览器')
    ap.set_defaults(desktop=True, mobile=True)
    args = ap.parse_args()

    modes = []
    if args.desktop:
        modes.append('desktop')
    if args.mobile:
        modes.append('mobile')
    if not modes:
        ap.error('--desktop 与 --mobile 不能同时关闭')

    out = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    report = Report(args.base, args.team, out, modes, args.baseline)
    print('verify_team_page: base=%s team=%s modes=%s out=%s'
          % (args.base, args.team, ','.join(modes), out))

    if not args.skip_api:
        try:
            check_api(report, args.base, args.team, args.api_timeout)
        except Exception as exc:  # noqa: BLE001
            report.add('data.api_crash', 'data', False, 'API 自检异常：%s' % exc,
                       {'traceback': traceback.format_exc()[-1200:]})
        try:
            check_studio_teams(report, args.base, args.api_timeout)
        except Exception as exc:  # noqa: BLE001
            report.add('data.studio_teams_crash', 'data', False,
                       '/api/studio/teams 自检异常：%s' % exc,
                       {'traceback': traceback.format_exc()[-1200:]})

    if args.api_only:
        write_outputs(report)
        for item in report.items:
            flag = 'PASS' if item['ok'] else ('FAIL' if item['severity'] == 'fail' else 'WARN')
            print('[%s] %s' % (flag, item['id']))
        s = report.summary()
        print('RESULT: %s (pass=%d fail=%d warn=%d) api-only=%s'
              % (s['result'], s['passed'], s['failed'], s['warnings'], True))
        print('report: %s' % (out / 'report.json'))
        return 1 if report.failures else 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for mode in modes:
                    run_mode(report, browser, mode, args, out)
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        report.add('runtime.browser_crash', 'runtime', False,
                   '浏览器启动/运行异常：%s' % exc, {'traceback': traceback.format_exc()[-1500:]})

    write_outputs(report)

    for item in report.items:
        flag = 'PASS' if item['ok'] else ('FAIL' if item['severity'] == 'fail' else 'WARN')
        print('[%s] %s' % (flag, item['id']))
    s = report.summary()
    print('RESULT: %s (pass=%d fail=%d warn=%d) baseline=%s'
          % (s['result'], s['passed'], s['failed'], s['warnings'], report.baseline))
    print('report: %s' % (out / 'report.json'))
    print('summary: %s' % (out / 'summary.txt'))

    if report.baseline:
        return 0
    return 1 if report.failures else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
