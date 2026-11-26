/* 英雄板块新增的三个独立页签（与「英雄榜 / 英雄对比」并列）
   ① 本队英雄详情 createHeroUsagePage
      本队选手逐英雄：使用次数 / 训练赛胜率 / 对对手胜率 / KPL 胜率 / 环比；
      点一行在行下展开「我方选手用这个英雄」的近 3 / 7 天胜率折线。
   ② 分路英雄指标 createLaneMetricsPage
      先选分路再点英雄，按规则中心的分路 × 字段指标显示当前值、环比（统一 %）、
      达标档位与异常；顶部一句「我方{分路}使用英雄{英雄}」。
   ③ 英雄组合表现 createComboCardsPage
      组合池名单，本队选手近 3 / 7 / 30 天的组合胜率与场次，卡片式。

   三个页面共用 /api/v3/team-hero-insight 一次汇总的只读数据，各自只负责展示。 */

import { glyph } from './ui-icons.js';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const es = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n0 = (v) => isNum(v) ? Math.round(v).toLocaleString('zh-CN') : '—';
const n2 = (v) => isNum(v) ? v.toFixed(2) : '—';
const pc = (v) => isNum(v) ? `${v.toFixed(1)}%` : '—';
const signedPc = (v) => isNum(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%` : '—';
const shortDay = (s) => String(s || '').slice(5).replace('-', '/');
const LANE_ORDER = ['对抗路', '打野·坦野', '打野·野核', '中路', '发育路', '游走'];
const PERIODS = [3, 7, 30];
const GRADE_CLS = { elite: 'elite', good: 'good', pass: 'pass', low: 'low' };

/* 环比：涨绿、跌红、持平灰；没有上期就留 —。单位一律 %，不写 pp。 */
function change(v) {
  if (!isNum(v)) return '<span class="thd-chg is-none">—</span>';
  const dir = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
  const arrow = v > 0 ? '↑' : v < 0 ? '↓' : '→';
  return `<span class="thd-chg is-${dir}">${arrow} ${signedPc(v)}</span>`;
}
const seg = (values, current, attr, suffix = '天') => `<div class="thd-seg" role="group">${values.map((d) =>
  `<button type="button" ${attr}="${d}" class="${current === d ? 'is-on' : ''}">${d} ${suffix}</button>`).join('')}</div>`;
/* 标题下的说明小字已移除：标题与按钮本身要能一眼看懂；sub 仅保留入参兼容调用方。 */
const intro = (title, sub) => `<div class="page-intro"><div><h1>${glyph('heroes', { size: 20 })}${es(title)}</h1></div>
  <div class="intro-actions"><button class="control" data-action="refresh">${glyph('refresh', { size: 18 })}刷新数据</button></div></div>`;
const toolbar = (period, note) => `<div class="thd-toolbar"><span class="thd-toolbar-label">时间范围</span>
  ${seg(PERIODS, period, 'data-thd-period')}<span class="thd-toolbar-note">${es(note)}</span></div>`;

/* 行点击后重绘整个页面：窗口滚动位置保持不变，展开态放在各自 state 里。 */
function makeRerender(selector, renderFn) {
  let page = null;
  return {
    bind() { page = document.querySelector(selector); },
    rerender() {
      if (!page) this.bind();
      if (!page) return;
      page.outerHTML = renderFn(null);
      page = document.querySelector(selector);
    },
  };
}

/* ── ① 本队英雄详情 ─────────────────────────────────────────────────── */
export function createHeroUsagePage({ esc: E = es, portrait = () => '' } = {}) {
  const state = { data: null, period: 7, openHero: '', trendDays: 7 };
  const rows = () => state.data?.heroRows || [];
  const data = () => state.data || {};

  function chart(row) {
    const points = (row?.trend7 || []).slice(-state.trendDays);
    if (points.filter((p) => isNum(p.winRate)).length < 2) {
      return `<div class="thd-chart-empty">${glyph('chart', { size: 18 })}这个窗口还没有足够的对局画趋势</div>`;
    }
    const W = 660, H = 190, L = 44, R = 16, T = 18, B = 34;
    const iw = W - L - R, ih = H - T - B;
    const X = (i) => L + i / (points.length - 1) * iw;
    const Y = (v) => T + (1 - v / 100) * ih;
    const segments = [];
    let run = [];
    points.forEach((p, i) => {
      if (isNum(p.winRate)) run.push(`${X(i).toFixed(1)},${Y(p.winRate).toFixed(1)}`);
      else if (run.length) { segments.push(run.join(' ')); run = []; }
    });
    if (run.length) segments.push(run.join(' '));
    const grid = [0, 50, 100].map((v) => `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" class="thd-grid"/>
      <text x="${L - 9}" y="${Y(v) + 4}" class="thd-axis" text-anchor="end">${v}%</text>`).join('');
    const labels = points.map((p, i) => `<text x="${X(i).toFixed(1)}" y="${H - 12}" class="thd-axis" text-anchor="middle">${shortDay(p.date)}</text>`).join('');
    const dots = points.map((p, i) => isNum(p.winRate)
      ? `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.winRate).toFixed(1)}" r="3.6" class="thd-dot"><title>${shortDay(p.date)} · ${pc(p.winRate)}（${p.wins || 0} 胜 / ${p.games || 0} 次）</title></circle>` : '').join('');
    return `<svg class="thd-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${E(row.hero)}近 ${state.trendDays} 天胜率趋势">
      ${grid}<line x1="${L}" y1="${Y(50)}" x2="${W - R}" y2="${Y(50)}" class="thd-ref"/>
      ${segments.map((s) => `<polyline points="${s}" class="thd-line"/>`).join('')}${dots}${labels}</svg>`;
  }

  function render(value) {
    if (value) state.data = value;
    if (!state.data) return '<div class="page"><div class="loading">正在汇总本队英雄详情…</div></div>';
    const w = data().window || {};
    const list = rows().slice().sort((a, b) => {
      const ag = a.byPeriod?.[String(state.period)]?.current?.games || 0;
      const bg = b.byPeriod?.[String(state.period)]?.current?.games || 0;
      return bg - ag || b.games - a.games || String(a.hero).localeCompare(String(b.hero), 'zh-CN');
    });
    const body = list.map((r) => {
      const p = r.byPeriod?.[String(state.period)] || {};
      const cur = p.current || {};
      const open = state.openHero === r.hero;
      return `<div class="thd-row-wrap${open ? ' is-open' : ''}">
        <button type="button" class="thd-row" data-thd-hero="${E(r.hero)}" aria-expanded="${open}">
          <span class="thd-hero-cell">${portrait(r.hero, 'thd-face')}<span><b>${E(r.hero)}</b><small>${E(r.lane || '位置未知')}</small></span></span>
          <span class="thd-num"><b>${n0(cur.games)}</b><small>次</small></span>
          <span class="thd-num"><b>${pc(cur.winRate)}</b><small>训练赛</small></span>
          <span class="thd-num thd-kpl"><b>${pc(r.kplWinRate)}</b><small>KPL</small></span>
          <span class="thd-change">${change(p.change)}<small>环比</small></span>
          <span class="thd-caret" aria-hidden="true">${open ? '▴' : '▾'}</span>
        </button>
        ${open ? `<div class="thd-expand">
          <div class="thd-expand-col"><h4>本队选手使用 ${E(r.hero)}</h4>
            <table class="thd-mini-table"><thead><tr><th>选手</th><th>使用</th><th>训练胜率</th><th>近 7 天环比</th></tr></thead><tbody>
            ${(r.players || []).map((x) => `<tr><th>${E(x.name)}</th><td>${n0(x.games)}</td><td>${pc(x.winRate)}</td><td>${change(x.change)}</td></tr>`).join('')
              || '<tr><td colspan="4">暂无选手使用记录。</td></tr>'}</tbody></table></div>
          <div class="thd-expand-col"><div class="thd-chart-head"><h4>胜率趋势 · ${E(r.hero)}</h4>
            <div class="thd-seg" role="group" aria-label="趋势天数">${[3, 7].map((d) => `<button type="button" data-thd-trend="${d}" class="${state.trendDays === d ? 'is-on' : ''}">近 ${d} 天</button>`).join('')}</div></div>
            ${chart(r)}</div></div>` : ''}
      </div>`;
    }).join('');
    return `<div class="page thd-page thd-usage-page">
      ${intro('本队英雄详情', '自家选手每个英雄用了多少次、胜率如何、环比有没有下降；点开一行看近期胜率趋势。')}
      ${toolbar(state.period, `窗口截至 ${data().anchor || '—'}${w[state.period] ? ` · 从 ${w[state.period]} 起` : ''}`)}
      <section class="thd-section">
        <header class="thd-section-head"><div><span class="thd-kicker">01 / 英雄</span><h2>${glyph('heroes', { size: 18 })}本队英雄使用明细</h2></div>
          <span class="thd-section-count">${list.length} 个英雄 · ${n0(data().sources?.panels)} 条本队面板</span></header>
        <div class="thd-table-head"><span>英雄 / 分路</span><span>使用次数</span><span>训练赛胜率</span><span>KPL 胜率</span><span>环比</span><span></span></div>
        <div class="thd-rows">${body || `<div class="thd-empty">${glyph('heroes', { size: 18 })}当前范围没有本队英雄使用记录</div>`}</div>
      </section>
      <p class="thd-source">数据来源：本机营地十人面板；KPL 胜率取自官方赛程本地缓存。缺数据的项显示「—」，不补造数字。</p>
    </div>`;
  }
  const ctl = makeRerender('.thd-usage-page', render);
  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.thd-usage-page')) return;
    const p = t.closest('[data-thd-period]');
    if (p) { state.period = Number(p.dataset.thdPeriod); ctl.rerender(); return; }
    const h = t.closest('[data-thd-hero]');
    if (h) { state.openHero = state.openHero === h.dataset.thdHero ? '' : h.dataset.thdHero; ctl.rerender(); return; }
    const d = t.closest('[data-thd-trend]');
    if (d) { state.trendDays = Number(d.dataset.thdTrend); ctl.rerender(); }
  });
  const baseRender = render;
  return { render: (v) => { const html = baseRender(v); queueMicrotask(() => ctl.bind()); return html; } };
}

/* ── ② 分路英雄指标 ─────────────────────────────────────────────────── */
export function createLaneMetricsPage({ esc: E = es, portrait = () => '' } = {}) {
  const state = { data: null, period: 7, lane: '', openHero: '' };
  const laneData = () => state.data?.laneHeroes || {};
  const lanes = () => LANE_ORDER.filter((k) => (laneData()[k] || []).length)
    .concat(Object.keys(laneData()).filter((k) => !LANE_ORDER.includes(k) && (laneData()[k] || []).length));
  const laneLabel = (k) => k === '游走' ? '游走（辅助）' : k;

  function render(value) {
    if (value) state.data = value;
    if (!state.data) return '<div class="page"><div class="loading">正在读取规则中心与分路指标…</div></div>';
    if (!state.lane || !(laneData()[state.lane] || []).length) state.lane = lanes()[0] || '';
    const list = laneData()[state.lane] || [];
    const open = list.find((x) => x.hero === state.openHero);
    const p = open?.byPeriod?.[String(state.period)] || {};
    const tabs = lanes().map((k) => `<button type="button" data-thd-lane="${E(k)}" class="${state.lane === k ? 'is-on' : ''}">${E(laneLabel(k))}<small>${(laneData()[k] || []).length}</small></button>`).join('');
    const chips = list.map((r) => {
      const m = r.byPeriod?.[String(state.period)]?.metrics || [];
      const ok = m.filter((x) => ['elite', 'good', 'pass'].includes(x.level)).length;
      return `<button type="button" class="thd-lane-hero${state.openHero === r.hero ? ' is-on' : ''}" data-thd-lane-hero="${E(r.hero)}">
        ${portrait(r.hero, 'thd-face')}<b>${E(r.hero)}</b><small>${n0(r.byPeriod?.[String(state.period)]?.games)} 局 · ${ok} 项达标</small></button>`;
    }).join('');
    const metrics = (p.metrics || []).map((m) => {
      const value = m.unit === '%' ? pc(m.value)
        : isNum(m.value) ? `${n2(m.value)}${m.unit ? ` <em>${E(m.unit)}</em>` : ''}` : '—';
      const prev = m.unit === '%' ? pc(m.previous) : (isNum(m.previous) ? n2(m.previous) : '—');
      const low = m.level === 'low';
      return `<tr class="${low ? 'is-low' : ''}"><th>${E(m.label)}${m.estimate ? '<small>参考阈值</small>' : ''}</th>
        <td class="thd-value">${value}</td><td class="thd-prev">${prev}</td><td>${change(m.change)}</td>
        <td><span class="thd-grade is-${GRADE_CLS[m.level] || 'none'}">${E(m.grade || '无数据')}</span>${low ? '<span class="thd-warn">异常</span>' : ''}</td></tr>`;
    }).join('');
    const panel = open ? `<div class="thd-metric-panel">
      <div class="thd-metric-head"><div><span class="thd-kicker">我方${E(laneLabel(state.lane))}</span><h3>${glyph('heroes', { size: 18 })}使用英雄 ${E(open.hero)}</h3></div>
        <span class="thd-section-count">${n0(p.games)} 次使用</span></div>
      <div class="thd-metric-scroll"><table class="thd-metric-table"><thead><tr><th>指标</th><th>当前值</th><th>上期</th><th>环比</th><th>达标情况</th></tr></thead>
        <tbody>${metrics || '<tr><td colspan="5">这个窗口没有可计算的指标。</td></tr>'}</tbody></table></div></div>`
      : `<div class="thd-empty-state">${glyph('heroes', { size: 20 })}<b>还没有选中英雄</b><span>点上方英雄卡片展开指标</span></div>`;
    return `<div class="page thd-page thd-lane-page">
      ${intro('分路英雄指标', '选分路 → 点英雄，看我方选手用这个英雄时各项指标最近有没有达标、有没有异常。')}
      ${toolbar(state.period, `窗口截至 ${E(state.data.anchor || '—')} · 规则版本 r${E(state.data.rulesRevision ?? '—')}`)}
      <section class="thd-section">
        <header class="thd-section-head"><div><span class="thd-kicker">02 / 分路</span><h2>${glyph('chart', { size: 18 })}分路 × 英雄指标达标</h2></div></header>
        <div class="thd-lane-tabs" role="group" aria-label="选择分路">${tabs || `<span class="thd-empty">${glyph('heroes', { size: 16 })}暂无分路数据</span>`}</div>
        <div class="thd-lane-heroes">${chips || `<span class="thd-empty">${glyph('heroes', { size: 16 })}该分路暂无英雄使用记录</span>`}</div>
        ${panel}
      </section>
      <p class="thd-source">指标、阈值与达标档位来自规则中心；控制时长、对位经济差等营地卡片指标缺数据时显示「—」，不用其他口径兜底。</p>
    </div>`;
  }
  const ctl = makeRerender('.thd-lane-page', render);
  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.thd-lane-page')) return;
    const p = t.closest('[data-thd-period]');
    if (p) { state.period = Number(p.dataset.thdPeriod); ctl.rerender(); return; }
    const l = t.closest('[data-thd-lane]');
    if (l) { state.lane = l.dataset.thdLane; state.openHero = ''; ctl.rerender(); return; }
    const h = t.closest('[data-thd-lane-hero]');
    if (h) { state.openHero = state.openHero === h.dataset.thdLaneHero ? '' : h.dataset.thdLaneHero; ctl.rerender(); }
  });
  const baseRender = render;
  return { render: (v) => { const html = baseRender(v); queueMicrotask(() => ctl.bind()); return html; } };
}

/* ── ③ 英雄组合表现 ─────────────────────────────────────────────────── */
export function createComboCardsPage({ esc: E = es, portrait = () => '' } = {}) {
  const state = { data: null, period: 7, expanded: false };
  const all = () => state.data?.combos || [];

  function render(value) {
    if (value) state.data = value;
    if (!state.data) return '<div class="page"><div class="loading">正在读取组合池与本队对局…</div></div>';
    const list = all();
    const shown = state.expanded ? list : list.slice(0, 12);
    const cards = shown.map((c) => {
      const p = c.byPeriod?.[String(state.period)] || {};
      const cur = p.current || {};
      const strength = c.strength === 'strong' ? '强联动' : c.strength === 'weak' ? '弱联动' : '';
      return `<article class="thd-combo-card">
        <div class="thd-combo-top"><span>${E(c.kindLabel || (c.kind === 'trios' ? '三人体系' : '双人组合'))}</span>
          ${strength ? `<span class="thd-strength is-${E(c.strength)}">${strength}</span>` : ''}</div>
        <div class="thd-combo-heroes">${(c.heroes || []).map((h, i) => `${i ? '<i>+</i>' : ''}${portrait(h, 'thd-face')}<b>${E(h)}</b>`).join('')}</div>
        ${c.name ? `<p class="thd-combo-name">${E(c.name)}</p>` : ''}
        <div class="thd-combo-nums"><div><b>${pc(cur.winRate)}</b><span>胜率</span></div><div><b>${n0(cur.games)}</b><span>场次</span></div>
          <div>${change(p.change)}<span>环比</span></div></div></article>`;
    }).join('');
    return `<div class="page thd-page thd-combo-page">
      ${intro('英雄组合表现', '范围是本队选手；组合名单按赛训组组合池，看近几天这些组合的胜率和场次。')}
      ${toolbar(state.period, `窗口截至 ${E(state.data.anchor || '—')} · ${state.data.comboBuiltin ? '组合池尚未保存，当前用内置名单' : '组合池已保存的名单'}`)}
      <section class="thd-section">
        <header class="thd-section-head"><div><span class="thd-kicker">03 / 组合</span><h2>${glyph('compare', { size: 18 })}本队选手英雄组合</h2></div>
          <span class="thd-section-count">共 ${list.length} 组</span></header>
        <div class="thd-combo-grid">${cards || `<div class="thd-empty">${glyph('compare', { size: 18 })}组合池里还没有组合</div>`}</div>
        ${list.length > 12 ? `<button type="button" class="thd-more" data-thd-combo-more>${glyph(state.expanded ? 'ban' : 'heroes', { size: 18 })}${state.expanded ? '收起' : `展开全部 ${list.length} 个组合`}</button>` : ''}
      </section>
      <p class="thd-source">组合名单来自赛训组组合池；场次与胜率取本队选手在营地面板里同时用到该组合英雄的对局。未命中的组合仍显示，场次为 0。</p>
    </div>`;
  }
  const ctl = makeRerender('.thd-combo-page', render);
  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.thd-combo-page')) return;
    const p = t.closest('[data-thd-period]');
    if (p) { state.period = Number(p.dataset.thdPeriod); ctl.rerender(); return; }
    if (t.closest('[data-thd-combo-more]')) { state.expanded = !state.expanded; ctl.rerender(); }
  });
  const baseRender = render;
  return { render: (v) => { const html = baseRender(v); queueMicrotask(() => ctl.bind()); return html; } };
}
