/* 跨局分析（2026-11-15 · 系列赛级）
 *
 * 这一页的单位是「大场」：把多场已确认的 BO3/5/7 放在一起看。
 * 四段：概述（描述）/ 赛中（赛中归因）/ 赛后（赛后归因）/ 英雄和 BP。
 * 单场 BO 是独立模块 #biggame（大场分析），不嵌在本页。
 *
 * 数据：系列赛汇总 + 各局向量；范围/赛制/对手/训练组/状态在前端过滤，
 * 选中大场的 seriesId 圈定小局，再交给 cross-analytics 做赛中/赛后/BP 统计。
 */

import { analyzeCohort, fmt } from './cross-analytics.js';
import { renderViz } from './cross-viz.js';

const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

const RANGE_OPTIONS = [['all', '全部时间'], ['7', '近 7 天'], ['30', '近 30 天'], ['custom', '自定义']];
const BO_OPTIONS = [['', '全部赛制'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']];
const STATUS_OPTIONS = [['', '全部状态'], ['confirmed', '已确认'], ['needs_review', '待核实']];
const COMPLETION_OPTIONS = [['', '全部完赛状态'], ['completed', '已完赛'], ['open', '未完赛'],
  ['interrupted', '中断'], ['incomplete', '采集不完整']];
const STATUS_LABEL = { confirmed: '已确认', needs_review: '待核实' };
const ATTENTION_LABEL = { 'losing-streak': '连败收尾', 'after-loss-flat': '败局后未改善', 'late-drop': '后段掉速', 'needs-review': '编组待核实', interrupted: '中断' };
const COMPLETION_LABEL = { completed: '已完赛', open: '未完赛', interrupted: '中断', incomplete: '采集不完整' };
const DEFAULT_RANGE = 'all';
const SECTIONS = [
  { key: 'overview', num: '01', label: '概述', note: '跨局描述：样本构成、比分与局序结构、分布、对手、覆盖' },
  { key: 'ingame', num: '02', label: '赛中', note: '用赛中数据做归因，不做描述' },
  { key: 'postgame', num: '03', label: '赛后', note: '用赛后面板做归因' },
  { key: 'draft', num: '04', label: '英雄和 BP', note: '重点：英雄池、组合、ban、消耗' },
];

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const pct100 = (v) => (num(v) ? `${Math.round(v)}%` : '—');
const rateText = (k, n) => (n ? `${k}/${n}（${Math.round(k / n * 100)}%）` : '样本不足');
const ciText = (ci) => (ci ? `${fmt.pct(ci[0])}–${fmt.pct(ci[1])}` : '—');
const isDate = (text) => /^\d{4}-\d{2}-\d{2}$/.test(String(text || ''));
const isoAddDays = (iso, days) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
const seriesDate = (s) => String(s.startAt || s.endAt || (s.games || [])[0]?.date || '').slice(0, 10);
const gameResults = (s) => (s.games || []).filter((g) => g.result === 'win' || g.result === 'loss')
  .slice().sort((a, b) => (Number(a.gameIndex) || 0) - (Number(b.gameIndex) || 0));
const scoreValid = (s) => {
  const bestOf = Number(s.bestOf) || 3;
  const max = s.completionMode === 'fixed' ? bestOf : Math.ceil(bestOf / 2);
  return (Number(s.score?.us) || 0) <= max && (Number(s.score?.them) || 0) <= max;
};

export function createCrossPage(h) {
  const { esc } = h;
  let root = null;
  let generation = 0;
  let controller = null;
  const state = {
    allSeries: [], attention: [], rulesets: [], latestDate: '', vectors: [], vectorsError: false, section: 'overview',
    loaded: false, loading: false, error: '',
    detailId: '', detail: null, detailLoading: false, detailError: '',
  };
  const scope = { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '', session: '', status: '', completion: '' };
  const vizViews = {};

  /* ── 地址与范围 ───────────────────────────────────────────── */
  function readScope() {
    const query = String(location.hash || '').split('?')[1] || '';
    const params = new URLSearchParams(query);
    const pick = (key, allowed, fallback) => (allowed.includes(params.get(key) || '') ? (params.get(key) || '') : fallback);
    scope.range = pick('range', RANGE_OPTIONS.map(([k]) => k), DEFAULT_RANGE);
    scope.bo = pick('bo', ['3', '5', '7'], '');
    scope.status = pick('status', ['confirmed', 'needs_review'], '');
    scope.completion = pick('completion', ['completed', 'open', 'interrupted', 'incomplete'], '');
    state.section = pick('view', SECTIONS.map((x) => x.key), 'overview');
    scope.opponent = String(params.get('opp') || '');
    scope.session = String(params.get('sess') || '');
    scope.from = isDate(params.get('from')) ? params.get('from') : '';
    scope.to = isDate(params.get('to')) ? params.get('to') : '';
    if (scope.range !== 'custom' && scope.from && scope.to) scope.range = 'custom';
    if (scope.range !== 'custom') { scope.from = ''; scope.to = ''; }
  }

  function scopeQuery() {
    const params = new URLSearchParams();
    if (scope.range !== DEFAULT_RANGE) params.set('range', scope.range);
    if (scope.range === 'custom') {
      if (scope.from) params.set('from', scope.from);
      if (scope.to) params.set('to', scope.to);
    }
    if (scope.bo) params.set('bo', scope.bo);
    if (scope.opponent) params.set('opp', scope.opponent);
    if (scope.session) params.set('sess', scope.session);
    if (scope.status) params.set('status', scope.status);
    if (scope.completion) params.set('completion', scope.completion);
    if (state.section && state.section !== 'overview') params.set('view', state.section);
    const query = params.toString();
    return query ? `?${query}` : '';
  }

  function routeParts() {
    return String(location.hash || '').replace(/^#/, '').split('?')[0].split('/');
  }

  function detailIdOf() {
    const parts = routeParts();
    return parts[0] === 'cross' && parts[1] === 'series' && parts[2] ? decodeURIComponent(parts[2]) : '';
  }

  function isCrossRoute() {
    return routeParts()[0] === 'cross';
  }

  function syncScopeUrl() {
    const detailId = detailIdOf();
    const path = detailId ? `#cross/series/${encodeURIComponent(detailId)}` : '#cross';
    try { history.replaceState(null, '', `${path}${scopeQuery()}`); } catch { /* 嵌入式浏览器禁 replaceState */ }
  }

  function scopeBounds() {
    if (scope.range === 'custom') return [scope.from, scope.to];
    if (scope.range === 'all' || !state.latestDate) return ['', ''];
    const days = scope.range === '7' ? 7 : 30;
    return [isoAddDays(state.latestDate, -(days - 1)), state.latestDate];
  }

  function scopeActive() {
    return !!(scope.range !== DEFAULT_RANGE || scope.bo || scope.opponent || scope.session || scope.status || scope.completion);
  }

  function scopeLabel() {
    const range = (RANGE_OPTIONS.find(([key]) => key === scope.range) || ['', '全部时间'])[1];
    const bits = [scope.range === 'custom' && (scope.from || scope.to)
      ? `${scope.from || '最早'} → ${scope.to || '最新'}` : range];
    if (scope.bo) bits.push(`BO${scope.bo}`);
    if (scope.opponent) bits.push(scope.opponent);
    if (scope.session) bits.push(scope.session);
    if (scope.status) bits.push(STATUS_LABEL[scope.status] || scope.status);
    if (scope.completion) bits.push(COMPLETION_LABEL[scope.completion] || scope.completion);
    return bits.join(' · ');
  }

  function filteredSeries() {
    const [from, to] = scopeBounds();
    return (state.allSeries || []).filter((s) => {
      const day = seriesDate(s);
      if ((from || to) && !day) return false;
      if (from && day < from) return false;
      if (to && day > to) return false;
      if (scope.bo && Number(s.bestOf) !== Number(scope.bo)) return false;
      if (scope.opponent && String(s.opponent || '').trim() !== scope.opponent) return false;
      if (scope.session && String(s.session || '').trim() !== scope.session) return false;
      if (scope.status && s.status !== scope.status) return false;
      if (scope.completion && s.completion !== scope.completion) return false;
      return true;
    }).sort((a, b) => String(seriesDate(b)).localeCompare(String(seriesDate(a))));
  }

  function selectedVectors(series) {
    const ids = new Set((series || []).map((s) => s.id));
    return (state.vectors || []).filter((v) => ids.has(v.seriesId));
  }

  function uniq(key) {
    return [...new Set((state.allSeries || []).map((s) => String(s[key] || '').trim()).filter(Boolean))].sort();
  }

  /* ── 多场汇总：所有口径都从过滤后的系列赛重算 ───────────────── */
  function deriveSummary(series) {
    const totals = { series: series.length, completed: 0, seriesWins: 0, seriesLosses: 0, games: 0, gameWins: 0 };
    const seq = new Map();
    const cons = new Map();
    const after = [];
    const dist = new Map();
    const boMix = new Map();
    let close = 0, sweep = 0, missing = 0, fixed = 0, invalid = 0, needsReview = 0;
    for (const s of series) {
      if (s.completion === 'completed') totals.completed += 1;
      if (s.completionMode === 'fixed') fixed += 1;
      if (!scoreValid(s)) invalid += 1;
      if (s.status === 'needs_review') needsReview += 1;
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      if (us > them) totals.seriesWins += 1;
      else if (them > us) totals.seriesLosses += 1;
      if (us || them) {
        const key = `${us}:${them}`;
        dist.set(key, (dist.get(key) || 0) + 1);
        if (Math.abs(us - them) === 1) close += 1;
        if (us === 0 || them === 0) sweep += 1;
      }
      boMix.set(Number(s.bestOf) || 3, (boMix.get(Number(s.bestOf) || 3) || 0) + 1);
      missing += (s.coverage?.missingGames || []).length;
      const games = gameResults(s);
      totals.games += games.length;
      totals.gameWins += games.filter((g) => g.result === 'win').length;
      games.forEach((g, i) => {
        const index = Number(g.gameIndex) || i + 1;
        const bucket = seq.get(index) || { gameIndex: index, results: [], at10: [] };
        bucket.results.push(g.result);
        if (num(g.at10)) bucket.at10.push(g.at10);
        seq.set(index, bucket);
        const c = cons.get(index) || { gameIndex: index, us: [], foe: [] };
        if (num(g.usedUsCount)) c.us.push(g.usedUsCount);
        if (num(g.usedFoeCount)) c.foe.push(g.usedFoeCount);
        cons.set(index, c);
        if (i > 0 && games[i - 1].result === 'loss') {
          after.push({
            nextResult: g.result,
            at10Delta: num(games[i - 1].at10) && num(g.at10) ? g.at10 - games[i - 1].at10 : null,
          });
        }
      });
    }
    const decided = totals.seriesWins + totals.seriesLosses;
    const gameSequence = [...seq.values()].sort((a, b) => a.gameIndex - b.gameIndex).map((b) => {
      const wins = b.results.filter((r) => r === 'win').length;
      return {
        gameIndex: b.gameIndex, n: b.results.length, wins,
        winRate: b.results.length ? wins / b.results.length * 100 : null,
        medianAt10: b.at10.length ? fmt.median(b.at10) : null,
        at10Samples: b.at10.length,
      };
    });
    const consumption = [...cons.values()].sort((a, b) => a.gameIndex - b.gameIndex).map((c) => ({
      gameIndex: c.gameIndex,
      avgUsedUs: c.us.length ? c.us.reduce((a, b) => a + b, 0) / c.us.length : null,
      avgUsedFoe: c.foe.length ? c.foe.reduce((a, b) => a + b, 0) / c.foe.length : null,
      n: c.us.length,
    }));
    const nextWins = after.filter((p) => p.nextResult === 'win').length;
    const deltas = after.map((p) => p.at10Delta).filter(num);
    return {
      totals: {
        ...totals,
        seriesWinRate: decided ? totals.seriesWins / decided * 100 : null,
        gameWinRate: totals.games ? totals.gameWins / totals.games * 100 : null,
        ci: decided ? fmt.wilson(totals.seriesWins, decided) : null,
        avgGames: series.length ? totals.games / series.length : null,
      },
      gameSequence, consumption,
      afterLoss: {
        n: after.length, nextWins,
        nextWinRate: after.length ? nextWins / after.length * 100 : null,
        medianAt10Delta: deltas.length ? fmt.median(deltas) : null,
        deltaSamples: deltas.length,
      },
      scoreDist: [...dist.entries()].map(([label, n]) => ({ label, n })).sort((a, b) => b.n - a.n),
      boMix: [...boMix.entries()].sort((a, b) => a[0] - b[0]),
      close, sweep, missing, fixed, invalid, needsReview,
    };
  }

  /* ── 取数 ─────────────────────────────────────────────────── */
  async function loadAll() {
    const gen = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.loading = true;
    state.error = '';
    paintLoading('正在汇总大场与赛中数据…');
    try {
      const [summaryResponse, vectorResponse] = await Promise.all([
        fetch(`${API_BASE}/api/cross/series-summary`, { signal: controller.signal, cache: 'no-store' }),
        fetch(`${API_BASE}/api/cross/vectors?source=db%2Cbundle&validation=1`, { signal: controller.signal, cache: 'no-store' }),
      ]);
      if (gen !== generation) return;
      if (!summaryResponse.ok) throw new Error(`系列赛汇总 ${summaryResponse.status}`);
      const payload = await summaryResponse.json();
      state.allSeries = payload.series || [];
      state.attention = payload.summary?.attention || [];
      state.rulesets = payload.rulesets || [];
      state.latestDate = state.allSeries.map(seriesDate).filter(Boolean).sort().pop() || '';
      state.vectorsError = !vectorResponse.ok;
      state.vectors = vectorResponse.ok ? ((await vectorResponse.json()).vectors || []) : [];
      state.loaded = true;
    } catch (error) {
      if (gen !== generation) return;
      state.error = String(error && error.message || error);
    }
    state.loading = false;
    if (isCrossRoute() && !detailIdOf()) paint(listHtml());
  }

  async function loadDetail(id) {
    const gen = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.detailId = id;
    state.detailLoading = true;
    state.detailError = '';
    state.detail = null;
    paintLoading('正在读取大场明细…');
    try {
      const response = await fetch(`${API_BASE}/api/series/${encodeURIComponent(id)}/analysis`, {
        signal: controller.signal, cache: 'no-store',
      });
      if (gen !== generation) return;
      if (!response.ok) throw new Error(`大场明细 ${response.status}`);
      state.detail = await response.json();
    } catch (error) {
      if (gen !== generation) return;
      state.detailError = String(error && error.message || error);
    }
    state.detailLoading = false;
    if (isCrossRoute() && detailIdOf() === id) paint(detailHtml());
  }

  /* ── 页头 / 范围条 ─────────────────────────────────────────── */
  function winRateText(value) {
    return num(value) ? `${Math.round(value)}%` : '—';
  }

  function heroForm(series) {
    const list = series.slice(0, 18).reverse();
    if (list.length < 2) return '';
    const diffs = list.map((s) => (Number(s.score?.us) || 0) - (Number(s.score?.them) || 0));
    const max = Math.max(1, ...diffs.map((v) => Math.abs(v)));
    const cols = list.map((s, i) => {
      const diff = diffs[i];
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      const tone = diff > 0 ? 'is-win' : diff < 0 ? 'is-loss' : 'is-draw';
      const h = (8 + Math.abs(diff) / max * 44).toFixed(1);
      const title = `${seriesDate(s)} ${s.opponent || '对手待补'} ${us}:${them}`;
      return `<a class="xc-form-col ${tone}" href="#biggame/${encodeURIComponent(s.id)}" title="${esc(title)}">
        <span class="xc-form-up">${diff > 0 ? `<i style="height:${h}px"></i>` : ''}</span>
        <span class="xc-form-down">${diff < 0 ? `<i style="height:${h}px"></i>` : ''}</span>
      </a>`;
    }).join('');
    return `<div class="xc-form">
      <div class="xc-form-caption"><span>大场净胜走势</span><span>最近 ${list.length} 场 · 点击看大场</span></div>
      <div class="xc-form-rail">${cols}</div>
      <div class="xc-form-axis"><span>${esc((seriesDate(list[0]) || '—').slice(5))}</span><span>${esc((seriesDate(list[list.length - 1]) || '—').slice(5))}</span></div>
    </div>`;
  }

  function recentFive(series) {
    const list = series.slice(0, 5);
    if (!list.length) return '';
    return `<div class="xc-recent">
      <div class="xc-recent-head"><span>最近大场</span><span>${list.length} 场</span></div>
      ${list.map((s) => {
        const us = Number(s.score?.us) || 0;
        const them = Number(s.score?.them) || 0;
        const tone = us > them ? 'is-win' : them > us ? 'is-loss' : 'is-draw';
        return `<a class="xc-recent-row ${tone}" href="#biggame/${encodeURIComponent(s.id)}">
          <b>${us}:${them}</b>
          <span>${esc(s.opponent || '对手待补')}</span>
          <small>${esc((seriesDate(s) || '—').slice(5))}</small>
        </a>`;
      }).join('')}
    </div>`;
  }

  function headHtml(sum, series) {
    const t = sum.totals;
    const boText = sum.boMix.length === 1 ? `BO${sum.boMix[0][0]}` : 'BO';
    const title = t.series ? `${t.series} 场 ${boText}，${t.seriesWins} 胜 ${t.seriesLosses} 负` : '当前范围没有系列赛';
    const rate = num(t.seriesWinRate) ? Math.round(t.seriesWinRate) : null;
    const bits = [];
    if (t.games) bits.push(`小局 <b>${t.gameWins}–${t.games - t.gameWins}</b>`);
    if (t.games) bits.push(`场均 <b>${fmt.fixed(t.avgGames, 1)}</b> 局`);
    if (t.series) bits.push(`打满 <b>${sum.close}</b> 场`);
    if (t.series) bits.push(`零封 <b>${sum.sweep}</b> 场`);
    if (sum.invalid) bits.push(`<b class="is-warn">${sum.invalid}</b> 场比分待核实`);
    return `<header class="xc-mast">
      <div class="xc-mast-top">
        <span class="xc-mast-eyebrow">跨局分析 <i>/</i> 多场 BO <i>/</i> ${esc(scopeLabel())}</span>
        <nav class="xc-mast-links">
          <a href="#biggame">大场分析 <span>↗</span></a>
          <a href="#series-builder">系列赛编组 <span>↗</span></a>
        </nav>
      </div>
      <div class="xc-mast-main">
        <div class="xc-mast-copy">
          <h1>${title}</h1>
          <p>${bits.map((bit) => `<span>${bit}</span>`).join('')}</p>
        </div>
        <div class="xc-rate">
          <span>大场胜率</span>
          <div class="xc-rate-num"><b>${rate === null ? '—' : rate}</b>${rate === null ? '' : '<em>%</em>'}</div>
          <div class="xc-rate-meter"><i style="width:${Math.max(0, Math.min(100, rate || 0))}%"></i><u></u></div>
          <div class="xc-rate-scale"><span>0</span><span>50</span><span>100</span></div>
        </div>
      </div>
      <div class="xc-mast-foot">
        ${heroForm(series)}
        ${recentFive(series)}
      </div>
    </header>`;
  }

  function scopeBarHtml(sum) {
    const seg = (list, current, attr) => `<div class="xc-seg">${list.map(([key, label]) =>
      `<button type="button" class="xc-segbtn" ${attr}="${key}" aria-pressed="${String(current) === key}">${esc(label)}</button>`).join('')}</div>`;
    const select = (key, label, list, value, emptyLabel) => `<label class="xc-filter"><span>${label}</span><select data-cx="${key}"${list.length ? '' : ' disabled'}>
      <option value="">${esc(emptyLabel)}</option>${list.map((item) => `<option value="${esc(item)}"${item === value ? ' selected' : ''}>${esc(item)}</option>`).join('')}</select></label>`;
    return `<div class="xc-command">
      <div class="xc-command-row">
        <div class="xc-scope">
          <div class="xc-filter is-seg"><span>时间</span>${seg(RANGE_OPTIONS, scope.range, 'data-cx-range')}</div>
          ${scope.range === 'custom' ? `<div class="xc-dates"><input type="date" data-cx-date="from" value="${esc(scope.from)}" aria-label="开始日期"><i>→</i><input type="date" data-cx-date="to" value="${esc(scope.to)}" aria-label="结束日期"></div>` : ''}
          <div class="xc-filter is-seg"><span>赛制</span>${seg(BO_OPTIONS, scope.bo, 'data-cx-bo')}</div>
          ${select('opponent', '对手', uniq('opponent'), scope.opponent, '全部对手')}
          ${select('session', '训练组', uniq('session'), scope.session, '全部训练组')}
          <label class="xc-filter"><span>状态</span><select data-cx="status">${STATUS_OPTIONS.map(([key, label]) => `<option value="${key}"${key === scope.status ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
          <label class="xc-filter"><span>完赛</span><select data-cx="completion">${COMPLETION_OPTIONS.map(([key, label]) => `<option value="${key}"${key === scope.completion ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
          ${scopeActive() ? '<button type="button" class="xc-clear" data-cx-clear>清除筛选</button>' : ''}
        </div>
        <div class="xc-command-meta">${sum ? `<b>${sum.totals.series}</b> 场 · <b>${sum.totals.games}</b> 局` : ''}</div>
      </div>
      <div class="xc-tabs-row">
        <nav class="xc-tabs" aria-label="跨局分析分区">
          ${SECTIONS.map((section) => `<button type="button" class="xc-tab${section.key === state.section ? ' is-active' : ''}" data-cx-section-link="${section.key}"><b>${section.num}</b><span>${esc(section.label)}</span></button>`).join('')}
        </nav>
        <span class="xc-tabs-meta">${esc(scopeActive() ? scopeLabel() : '全量对局')}</span>
      </div>
    </div>`;
  }

  /* ── 通用块 ─────────────────────────────────────────────────── */
  function module({ id, span = 6, kicker = '', title = '', meta = '', body = '', tone = '' }) {
    return `<article class="xc-mod is-${span}${tone ? ` is-${tone}` : ''}" id="xc-${esc(id)}">
      <div class="xc-mod-head">
        <div class="xc-mod-copy">
          ${kicker ? `<span class="xc-mod-kicker">${esc(kicker)}</span>` : ''}
          ${title ? `<h3>${title}</h3>` : ''}
        </div>
        ${meta ? `<span class="xc-mod-meta">${meta}</span>` : ''}
      </div>
      ${body ? `<div class="xc-mod-body">${body}</div>` : ''}
    </article>`;
  }

  function statement(label, text, meta = '') {
    return `<div class="xc-statement">
      <span class="xc-statement-label">${esc(label)}</span>
      <p>${text}</p>
      ${meta ? `<span class="xc-statement-meta">${meta}</span>` : ''}
    </div>`;
  }

  function sectionHead(key, meta) {
    const section = SECTIONS.find((x) => x.key === key);
    return `<header class="xc-sec-head">
      <span class="xc-sec-num">${section.num}</span>
      <h2>${esc(section.label)}</h2>
      <span class="xc-sec-meta">${meta || ''}</span>
    </header>`;
  }

  function emptyVector(text) {
    return `<p class="xc-muted">${esc(text)}</p>`;
  }

  /* 单场大场分析仍复用这个卡片壳；列表页不再使用。 */
  function card({ id, span = 6, kicker, sample, title, lede = '', chart = null, body = '', note = '', method = '' }) {
    return `<article class="xc-card xc-span-${span}" id="xc-${esc(id)}">
      <div class="xc-card-head"><span class="xc-kicker">${esc(kicker)}</span>${sample ? `<span class="xc-badge">${esc(sample)}</span>` : ''}</div>
      <h3 class="xc-card-title">${title}</h3>
      ${lede ? `<p class="xc-card-lede">${lede}</p>` : ''}
      ${chart ? `<div class="xc-card-chart">${renderViz({ ...chart, id: chart.id || id }, { view: (key) => vizViews[key] || 'a' })}</div>` : ''}
      ${body}
    </article>`;
  }

  /* ── 概述 ───────────────────────────────────────────────────── */
  function overviewStatement(sum, a, series) {
    const t = sum.totals;
    if (sum.invalid) {
      return statement('概述', `${sum.invalid} 场比分与赛制对不上，先把编组核实，再谈胜率。`, `${t.series} 场 · ${t.games} 局`);
    }
    const recent = series.slice(0, 5);
    const recentWins = recent.filter((s) => (Number(s.score?.us) || 0) > (Number(s.score?.them) || 0)).length;
    const recentLosses = recent.filter((s) => (Number(s.score?.them) || 0) > (Number(s.score?.us) || 0)).length;
    let text = `${t.series} 场 BO 拿下 <em>${t.seriesWins}</em> 场，小局 <em>${t.gameWins}</em> 胜 <em>${t.games - t.gameWins}</em> 负，${sum.close} 场打到决胜局。`;
    if (recent.length >= 3) text += ` 最近 ${recent.length} 场 <em>${recentWins}</em> 胜 <em>${recentLosses}</em> 负。`;
    return statement('概述', text, `${t.completed}/${t.series} 场已完赛 · ${sum.sweep} 场零封 · ${sum.needsReview} 场待核实`);
  }

  function recordModule(sum) {
    const t = sum.totals;
    const max = Math.max(1, ...sum.scoreDist.map((x) => x.n));
    const dist = sum.scoreDist.length ? sum.scoreDist.map((x) => {
      const [us, them] = x.label.split(':').map(Number);
      const tone = us > them ? 'is-win' : them > us ? 'is-loss' : 'is-draw';
      return `<div class="xc-score-row ${tone}">
        <b>${esc(x.label)}</b>
        <i><span style="width:${(x.n / max * 100).toFixed(1)}%"></span></i>
        <small>${x.n} 场</small>
      </div>`;
    }).join('') : emptyVector('还没有已确认的比分。');
    return module({
      id: 'overview-record', span: 8, kicker: '大场战绩', meta: `${t.series} 场 / ${t.games} 局`,
      title: `${t.seriesWins} 胜 ${t.seriesLosses} 负，小局 ${t.gameWins} 胜 ${t.games - t.gameWins} 负`,
      body: `<div class="xc-duo">
        <div class="xc-duo-item"><span>大场</span><div><b class="is-win">${t.seriesWins}</b><i>:</i><b class="is-loss">${t.seriesLosses}</b></div></div>
        <div class="xc-duo-item"><span>小局</span><div><b class="is-win">${t.gameWins}</b><i>:</i><b class="is-loss">${t.games - t.gameWins}</b></div></div>
        <div class="xc-duo-item"><span>胜率</span><div class="is-rate">${winRateText(t.seriesWinRate)}</div></div>
      </div>
      <div class="xc-score-dist">${dist}</div>`,
    });
  }

  function sequenceModule(sum) {
    const seq = sum.gameSequence;
    const cols = seq.map((g) => {
      const rate = num(g.winRate) ? g.winRate : 0;
      return `<div class="xc-seq-col${g.n < 3 ? ' is-thin' : ''}">
        <span class="xc-seq-pct">${num(g.winRate) ? `${Math.round(g.winRate)}%` : '—'}</span>
        <i class="xc-seq-track"><b class="${rate >= 50 ? 'is-win' : 'is-loss'}" style="height:${Math.max(2, Math.min(100, rate))}%"></b><u></u></i>
        <span class="xc-seq-g">G${g.gameIndex}</span>
        <small>${g.n} 局</small>
      </div>`;
    }).join('');
    return module({
      id: 'overview-sequence', span: 4, kicker: '局序', meta: `${sum.totals.games} 小局`,
      title: '同一个局序跨多场 BO 汇总',
      body: `<div class="xc-seq">${cols || emptyVector('还没有带局序的小局。')}</div>`,
    });
  }

  function opponentRows(series) {
    const map = new Map();
    for (const s of series) {
      const name = String(s.opponent || '').trim() || '对手待补';
      const e = map.get(name) || { name, series: 0, wins: 0, losses: 0, games: 0, gameWins: 0, close: 0 };
      e.series += 1;
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      if (us > them) e.wins += 1; else if (them > us) e.losses += 1;
      const games = gameResults(s);
      e.games += games.length;
      e.gameWins += games.filter((g) => g.result === 'win').length;
      if (Math.abs(us - them) === 1 && (us || them)) e.close += 1;
      map.set(name, e);
    }
    return [...map.values()].sort((a, b) => b.series - a.series);
  }

  function opponentModule(series) {
    const items = opponentRows(series);
    const body = items.map((x, index) => {
      const decided = x.wins + x.losses;
      const rate = decided ? x.wins / decided * 100 : 0;
      return `<div class="xc-opp-row">
        <span class="xc-opp-rank">${String(index + 1).padStart(2, '0')}</span>
        <div class="xc-opp-name"><b>${esc(x.name)}</b><span>小局 ${x.gameWins}/${x.games} · 打满 ${x.close}</span></div>
        <div class="xc-opp-score"><b class="is-win">${x.wins}</b><i>:</i><b class="is-loss">${x.losses}</b></div>
        <i class="xc-opp-bar"><b style="width:${rate.toFixed(1)}%"></b></i>
        <em class="xc-opp-rate">${winRateText(decided ? rate : null)}</em>
      </div>`;
    }).join('');
    return module({
      id: 'overview-opponents', span: 4, kicker: '对手', meta: `${items.length} 个`,
      title: items.length ? `${esc(items[0].name)} 打得最多` : '还没有对手样本',
      body: body || emptyVector('当前范围没有对手。'),
    });
  }

  function distributionModule(a) {
    if (!a || !a.total) return module({ id: 'overview-dist', span: 4, kicker: '小局分布', title: '没有可读的小局分布', body: emptyVector('缺过程与面板数据。') });
    const risk = a.risk;
    const items = [
      { label: '时长', data: risk.duration, unit: 'sec' },
      { label: '10′ 经济差', data: risk.at10, unit: 'gold' },
      { label: '终局经济差', data: risk.final, unit: 'gold' },
    ].filter((item) => num(item.data?.p50));
    const value = (v, unit) => (unit === 'sec' ? fmt.duration(v) : fmt.signed(v));
    const rows = items.map((item) => {
      const { p10, p50, p90, n } = item.data;
      const lo = item.unit === 'gold' ? Math.min(0, p10) : p10;
      const hi = item.unit === 'gold' ? Math.max(0, p90) : p90;
      const span = Math.max(1, hi - lo);
      const at = (v) => Math.max(0, Math.min(100, (v - lo) / span * 100));
      return `<div class="xc-range-row">
        <div class="xc-range-top"><span>${esc(item.label)}</span><b>${esc(value(p50, item.unit))}</b><small>${n} 局</small></div>
        <i class="xc-range-track">
          ${item.unit === 'gold' ? `<u style="left:${at(0).toFixed(1)}%"></u>` : ''}
          <span style="left:${at(p10).toFixed(1)}%;width:${Math.max(1, at(p90) - at(p10)).toFixed(1)}%"></span>
          <b style="left:${at(p50).toFixed(1)}%"></b>
        </i>
        <div class="xc-range-ends"><span>${esc(value(p10, item.unit))}</span><span>${esc(value(p90, item.unit))}</span></div>
      </div>`;
    }).join('');
    return module({
      id: 'overview-dist', span: 4, kicker: '小局分布', meta: `${a.total} 局`,
      title: '常见值与中间 80% 的范围',
      body: `<div class="xc-ranges">${rows}</div>`,
    });
  }

  function sampleModule(sum, series, a) {
    const dates = series.map(seriesDate).filter(Boolean).sort();
    const span = dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0].slice(5) : `${dates[0].slice(5)} → ${dates[dates.length - 1].slice(5)}`) : '—';
    const opponents = new Set(series.map((s) => String(s.opponent || '').trim() || '对手待补')).size;
    const boTotal = sum.boMix.reduce((total, [, n]) => total + n, 0);
    const mix = boTotal ? `<div class="xc-mix">${sum.boMix.map(([bestOf, n]) => `<i class="is-bo${bestOf}" style="flex:${n}" title="BO${bestOf} ${n} 场"></i>`).join('')}</div>
      <div class="xc-mix-legend">${sum.boMix.map(([bestOf, n]) => `<span><i class="is-bo${bestOf}"></i>BO${bestOf} <b>${n}</b></span>`).join('')}</div>` : '<p class="xc-muted">没有赛制样本</p>';
    const cover = a && a.total ? [
      ['经济', a.coverage.econ], ['回放事件', a.coverage.first], ['阵容', a.coverage.lineup], ['选手面板', a.coverage.players],
    ].map(([label, n]) => `<div class="xc-cover-row"><span>${label}</span><i><b style="width:${(n / a.total * 100).toFixed(1)}%"></b></i><em>${n}/${a.total}</em></div>`).join('') : '';
    return module({
      id: 'overview-sample', span: 4, kicker: '样本', meta: `${opponents} 个对手`,
      title: `${span} · ${sum.totals.games} 小局`,
      body: `<div class="xc-sample">
        <div class="xc-sample-dates"><b>${span}</b><span>${sum.totals.completed}/${sum.totals.series} 场已完赛</span></div>
        ${mix}
        <div class="xc-cover">${cover}</div>
      </div>`,
    });
  }

  function attentionList(attention, limit = 10) {
    const items = (attention || []).slice(0, limit);
    if (!items.length) return emptyVector('当前范围没有需要优先处理的信号。');
    return `<ol class="xc-attn-list">${items.map((item, index) => `<li class="xc-attn">
      <span class="xc-attn-num">${String(index + 1).padStart(2, '0')}</span>
      <div class="xc-attn-copy">
        <div class="xc-attn-title"><b>${esc(item.title || '需要关注')}</b><span>${esc(ATTENTION_LABEL[item.kind] || '')}</span></div>
        <p>${esc(item.detail || '')}</p>
        <div class="xc-attn-links">
          ${item.seriesId ? `<a href="#biggame/${encodeURIComponent(item.seriesId)}${scopeQuery()}">看大场 →</a>` : ''}
          ${(item.links || []).slice(0, 3).map((key) => `<a href="#match/${encodeURIComponent(key)}">局 ${esc(String(key).slice(-6))}</a>`).join('')}
        </div>
      </div>
    </li>`).join('')}</ol>`;
  }

  function attentionModule(sum, attention) {
    return module({
      id: 'overview-attention', span: 12, kicker: '本轮关注', meta: `${(attention || []).length} 条`,
      title: (attention || []).length ? '先看这些大场信号' : '当前范围没有异常信号',
      body: attentionList(attention),
    });
  }

  function logModule(series, attention) {
    const attnCount = new Map();
    for (const item of attention || []) if (item.seriesId) attnCount.set(item.seriesId, (attnCount.get(item.seriesId) || 0) + 1);
    const rows = series.map((s) => {
      const games = gameResults(s);
      const mini = games.map((g) => `<i class="xc-mini ${g.result === 'win' ? 'is-win' : 'is-loss'}" title="G${g.gameIndex} ${g.result === 'win' ? '胜' : '负'}"></i>`).join('');
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      const tone = us > them ? 'is-win' : them > us ? 'is-loss' : 'is-draw';
      return `<a class="xc-log-row" href="#biggame/${encodeURIComponent(s.id)}${scopeQuery()}">
        <span class="xc-log-date">${esc((seriesDate(s) || '—').slice(5))}</span>
        <span class="xc-log-opp"><b>${esc(s.opponent || '对手待补')}</b>${s.status === 'needs_review' ? '<em>待核实</em>' : ''}</span>
        <span class="xc-log-bo">BO${esc(String(s.bestOf || '—'))}</span>
        <span class="xc-log-score ${tone}">${us}:${them}</span>
        <span class="xc-log-games">${mini || '—'}</span>
        <span class="xc-log-attn">${attnCount.get(s.id) ? `<i>${attnCount.get(s.id)}</i>` : ''}</span>
        <span class="xc-log-go">↗</span>
      </a>`;
    }).join('');
    return module({
      id: 'overview-log', span: 12, kicker: '系列赛日志', meta: `${series.length} 场`,
      title: '逐场进入大场分析',
      body: `<div class="xc-log">
        <div class="xc-log-head"><span>日期</span><span>对手</span><span>赛制</span><span>比分</span><span>逐局</span><span></span><span></span></div>
        ${rows}
      </div>`,
    });
  }

  function overviewCards(sum, series, a, attention) {
    return `${recordModule(sum)}${sequenceModule(sum)}${opponentModule(series)}${distributionModule(a)}${sampleModule(sum, series, a)}${attentionModule(sum, attention)}${logModule(series, attention)}`;
  }

  /* ── 赛中 ───────────────────────────────────────────────────── */
  function ingameStatement(a) {
    if (!a || !a.total) return statement('赛中', '这批大场没有可读的赛中过程。', '先确认回放与过程数据是否挂上');
    const lead = a.path.lead;
    const shrink = lead.shrink.value;
    return statement('赛中',
      `10 分钟领先 1,000 金的 <em>${lead.n}</em> 局里赢下 <em>${lead.wins}</em> 局；其中 <em>${fmt.pct(shrink)}</em> 的优势在终局前被收窄。`,
      `4 分钟领先率 ${fmt.pct(a.early.at4.leadRate)} · 多打少胜率 ${fmt.pct(a.fight.adv.rate.value)} · 大优被翻 ${fmt.pct(a.risk.throw.value)}`);
  }

  function phaseLedger(path) {
    return `<div class="xc-phase-ledger">
      <div class="xc-phase-head"><span>阶段净增</span><b>赢局</b><b>输局</b></div>
      ${path.phase.map((p) => `<div class="xc-phase-row"><span>${esc(p.label)}</span><b class="is-win">${fmt.signed(p.win)}</b><b class="is-loss">${fmt.signed(p.loss)}</b></div>`).join('')}
    </div>`;
  }

  function ingameCards(a) {
    if (!a || !a.total) return module({ id: 'ingame-empty', span: 12, kicker: '赛中', title: '没有可用的赛中数据', body: emptyVector('先确认对局是否已关联回放与过程数据。') });
    const path = a.path;
    const early = a.early;
    const lane = a.lane;
    const obj = a.objective;
    const fight = a.fight;
    const risk = a.risk;
    const earlyItems = [
      { label: '一血率', value: early.blood.rate, unit: 'pct', n: early.blood.n, sub: `${early.blood.own}/${early.blood.n}` },
      { label: '一龙率', value: early.dragon.rate, unit: 'pct', n: early.dragon.n, sub: `${early.dragon.own}/${early.dragon.n}` },
      { label: '一塔率', value: early.tower.rate, unit: 'pct', n: early.tower.n, sub: `${early.tower.own}/${early.tower.n}` },
      { label: '4 分钟领先率', value: early.at4.leadRate, unit: 'pct', n: early.at4.n, sub: `${early.at4.n} 局` },
      { label: '打野过河', value: early.jungle.cross, unit: 'pct', n: early.jungle.n, sub: '0–10 分钟' },
      { label: '深入野区', value: early.jungle.deep, unit: 'pct', n: early.jungle.n, sub: '0–10 分钟' },
      { label: '反野 / 场', value: early.jungle.anti, unit: 'count1', n: early.jungle.n, sub: 'BUFF 事件' },
      { label: '被反野 / 场', value: early.jungle.stolen, unit: 'count1', n: early.jungle.n, sub: 'BUFF 事件' },
    ];
    const metrics = earlyItems.map((item) => `<div class="xc-metric">
      <span>${esc(item.label)}</span>
      <b>${item.unit === 'pct' ? fmt.pct(item.value) : fmt.fixed(item.value, 1)}</b>
      <small>${esc(item.sub)}</small>
    </div>`).join('');
    return `${module({
      id: 'ingame-path', span: 12, kicker: '赛中 · 经济路径', meta: `${a.total} 局`, tone: 'ink',
      title: `10′ 常见 <em>${fmt.signed(risk.at10.p50)}</em>，终局 <em>${fmt.signed(risk.final.p50)}</em>`,
      body: `${renderViz({ type: 'path', id: 'ingame-path-viz', checkpoints: path.checkpoints, phase: path.phase }, { view: (key) => vizViews[key] || 'a' })}
        ${phaseLedger(path)}`,
    })}${module({
      id: 'ingame-early', span: 7, kicker: '赛中 · 前期节奏', meta: `${early.firstN} 局有事件`,
      title: '一血、一龙、一塔与野区主动',
      body: `<div class="xc-metrics">${metrics}</div>`,
    })}${module({
      id: 'ingame-risk', span: 5, kicker: '赛中 · 领先守成', meta: `${risk.at10.n} 局有 10′ 差`,
      title: `大优被翻 ${fmt.pct(risk.throw.value)}，大劣翻盘 ${fmt.pct(risk.comeback.value)}`,
      body: `<div class="xc-twin">
        <div><span>大优被翻</span><b class="is-loss">${fmt.pct(risk.throw.value)}</b><small>${risk.throw.k}/${risk.throw.n} 局</small></div>
        <div><span>大劣翻盘</span><b class="is-win">${fmt.pct(risk.comeback.value)}</b><small>${risk.comeback.k}/${risk.comeback.n} 局</small></div>
      </div>
      <div class="xc-facts">
        <span>10 分钟落后 <b>${fmt.pct(risk.behind.value)}</b></span>
        <span>超长局 <b>${fmt.pct(risk.long.value)}</b></span>
        <span>终局崩盘 <b>${fmt.pct(risk.blowLoss.value)}</b></span>
      </div>`,
    })}${module({
      id: 'ingame-lane', span: 7, kicker: '赛中 · 五路对位', meta: `${Math.max(0, ...lane.lanes.map((x) => x.n))} 局`,
      title: lane.best && lane.floor ? `${lane.best.lane} 最稳，${lane.floor.lane} 下限最低` : '五路对位',
      body: renderViz({ type: 'laneRange', id: 'ingame-lane-viz', lanes: lane.lanes }, { view: (key) => vizViews[key] || 'a' }),
    })}${module({
      id: 'ingame-obj', span: 5, kicker: '赛中 · 资源兑现', meta: `${obj.n} 局`,
      title: `控龙率 ${fmt.pct(obj.dragon.rate)}`,
      body: `${renderViz({ type: 'funnel', id: 'ingame-obj-viz', steps: obj.steps }, { view: (key) => vizViews[key] || 'a' })}
        <div class="xc-facts">
          <span>10′ 领先胜率 <b>${obj.steps[0]?.n ? fmt.pct(obj.steps[0].wins / obj.steps[0].n) : '—'}</b></span>
          <span>落后翻盘 <b>${fmt.pct(obj.comeback.rate.value)}</b></span>
          <span>推塔 <b>${fmt.fixed(obj.tower.own, 1)} / ${fmt.fixed(obj.tower.foe, 1)}</b></span>
        </div>`,
    })}${module({
      id: 'ingame-fight', span: 12, kicker: '赛中 · 团战结构', meta: `${fight.decided.n} 波有击杀`,
      title: `团战胜率 ${fmt.pct(fight.decided.value)}，多打少 ${fmt.pct(fight.adv.rate.value)}`,
      body: renderViz({ type: 'fight', id: 'ingame-fight-viz', ...fight }, { view: (key) => vizViews[key] || 'a' }),
    })}`;
  }

  /* ── 赛后 ───────────────────────────────────────────────────── */
  function postgameStatement(a) {
    if (!a || !a.total) return statement('赛后', '这批大场没有可读的赛后面板。', '先补齐十人结算');
    const top = a.drivers[0];
    return statement('赛后',
      top ? `赢输差得最明显的是<em>${top.label}</em>：赢局 ${top.winText}，输局 ${top.lossText}。` : '赛后差得最大的项目样本不足。',
      a.players.length ? `${a.players[0].name} 分均 ${fmt.fixed(a.players[0].gpm, 0)} 金币 · ${a.players[0].games} 局` : '选手面板不足');
  }

  function driverRows(drivers) {
    const rows = drivers.slice(0, 8).map((d) => {
      const w = Math.abs(num(d.win) ? d.win : 0);
      const l = Math.abs(num(d.loss) ? d.loss : 0);
      const total = Math.max(1e-9, w + l);
      const winW = w / total * 50;
      const lossW = l / total * 50;
      return `<div class="xc-driver-row">
        <div class="xc-driver-label"><b>${esc(d.label)}</b><small>${d.n} 局</small></div>
        <span class="xc-driver-val is-loss">${esc(d.lossText)}</span>
        <i class="xc-driver-track"><b class="is-loss" style="width:${lossW.toFixed(1)}%"></b><b class="is-win" style="width:${winW.toFixed(1)}%"></b><u></u></i>
        <span class="xc-driver-val is-win">${esc(d.winText)}</span>
      </div>`;
    }).join('');
    return `<div class="xc-drivers">${rows}</div>
      <div class="xc-driver-legend"><span><i class="is-loss"></i>输局</span><span><i class="is-win"></i>赢局</span></div>`;
  }

  function rosterList(players) {
    if (!players.length) return emptyVector('选手面板不足 3 局。');
    const rows = players.slice(0, 12).map((p, index) => `<div class="xc-roster-row">
      <span class="xc-roster-rank">${String(index + 1).padStart(2, '0')}</span>
      <div class="xc-roster-who"><b>${esc(p.name)}</b><small>${esc(p.pos)} · ${p.games} 局</small></div>
      <b class="xc-roster-gpm">${fmt.fixed(p.gpm, 0)}</b>
      <span class="xc-roster-dpm">${fmt.fixed(p.dpm, 0)}</span>
      <span class="xc-roster-part"><i><b style="width:${Math.max(0, Math.min(100, (p.part || 0) * 100)).toFixed(1)}%"></b></i>${fmt.pct(p.part)}</span>
      <span class="xc-roster-death">${fmt.fixed(p.deaths, 1)}</span>
    </div>`).join('');
    return `<div class="xc-roster">
      <div class="xc-roster-head"><span></span><span>选手</span><span>分均经济</span><span>分均输出</span><span>参团</span><span>死亡</span></div>
      ${rows}
    </div>`;
  }

  function laneList(lanes) {
    if (!lanes.length) return emptyVector('分路样本不足。');
    return `<div class="xc-lane-list">
      <div class="xc-lane-head"><span>分路</span><span>常见差</span><span>最差 10%</span><span>领先率</span><span>领先胜率</span><span>落后胜率</span></div>
      ${lanes.map((x) => `<div class="xc-lane-row">
        <b>${esc(x.lane)}</b>
        <em class="${(x.med || 0) >= 0 ? 'is-win' : 'is-loss'}">${fmt.signed(x.med)}</em>
        <span>${fmt.signed(x.p10)}</span>
        <span>${fmt.pct(x.aheadRate)}</span>
        <span>${x.winAhead.n ? fmt.pct(x.winAhead.value) : '—'}</span>
        <span>${x.winBehind.n ? fmt.pct(x.winBehind.value) : '—'}</span>
      </div>`).join('')}
    </div>`;
  }

  function postgameCards(a, attention) {
    if (!a || !a.total) return module({ id: 'postgame-empty', span: 12, kicker: '赛后', title: '没有可用的赛后数据', body: emptyVector('先补齐十人结算面板。') });
    const keys = new Set(['final', 'km', 'duration', 'deaths', ...LANES.map((lane) => `lane:${lane}`)]);
    const drivers = a.drivers.filter((d) => keys.has(d.key));
    const players = a.players;
    const lane = a.lane.lanes;
    const risk = a.risk;
    return `${module({
      id: 'post-drivers', span: 12, kicker: '赛后 · 赢输驱动', meta: `${drivers[0] ? drivers[0].n : 0} 局覆盖`,
      title: drivers[0] ? `${drivers[0].label}把赢局和输局分得最开` : '赛后样本不足',
      body: drivers.length ? driverRows(drivers) : emptyVector('胜负样本不足。'),
    })}${module({
      id: 'post-players', span: 7, kicker: '赛后 · 选手执行', meta: `${players.length} 人`,
      title: players.length ? `${players[0].name} 分均 ${fmt.fixed(players[0].gpm, 0)} 金币` : '选手面板不足',
      body: rosterList(players),
    })}${module({
      id: 'post-lanes', span: 5, kicker: '赛后 · 五路结果', meta: `${Math.max(0, ...lane.map((x) => x.n))} 局`,
      title: '同位置的常见差与下限',
      body: laneList(lane),
    })}${module({
      id: 'post-risk', span: 7, kicker: '赛后 · 结果分布', meta: `${risk.final.n} 局`,
      title: `终局常见 ${fmt.signed(risk.final.p50)}，时长常见 ${fmt.duration(risk.duration.p50)}`,
      body: renderViz({ type: 'distribution', id: 'post-risk-viz', items: [
        { label: '终局经济差', ...risk.final, unit: 'gold' },
        { label: '时长', ...risk.duration, unit: 'sec' },
      ] }, { view: (key) => vizViews[key] || 'a' }),
    })}${module({
      id: 'post-attention', span: 5, kicker: '赛后 · 需要关注', meta: `${(attention || []).length} 条`,
      title: '带证据的异常信号',
      body: attentionList(attention, 5),
    })}`;
  }

  /* ── 英雄和 BP ──────────────────────────────────────────────── */
  function draftStatement(a) {
    if (!a || !a.total) return statement('英雄和 BP', '这批大场没有可读的阵容。', '先补齐十人面板或 BP 名单');
    const comp = a.draft.comps[0];
    const hero = a.draft.heroes[0];
    const ban = a.draft.bansFoe[0];
    return statement('英雄和 BP',
      comp ? `最常用「<em>${esc(comp.tag)}</em>」${comp.games} 局，胜率 <em>${fmt.pct(comp.rate.value)}</em>${hero ? `；英雄池第一是 <em>${esc(hero.hero)}</em>` : ''}。` : (hero ? `出场最多 <em>${esc(hero.hero)}</em>（${hero.games} 局）。` : '英雄样本不足。'),
      `${ban ? `对手最常 ban ${ban.hero} · ` : ''}${a.coverage.comp} 局有体系标签 · ${a.draft.heroes.length} 个英雄`);
  }

  function lineup(d) {
    if (!d.signature.length) return emptyVector('没有五路名单。');
    return `<div class="xc-lineup">${d.signature.map((s) => {
      const top = s.heroes[0];
      return `<div class="xc-lineup-lane">
        <span class="xc-lineup-lane-name">${esc(s.lane)}</span>
        <b class="xc-lineup-hero">${esc(top?.hero || '—')}</b>
        <small>${top ? `${top.games} 局` : '无名单'}${s.heroes.find((x) => x.arch)?.arch ? ` · ${esc(s.heroes.find((x) => x.arch).arch)}` : ''}</small>
        <div class="xc-lineup-chips">${s.heroes.slice(0, 4).map((x) => `<span>${esc(x.hero)}<i>${x.games}</i></span>`).join('')}</div>
      </div>`;
    }).join('')}</div>`;
  }

  function compRows(comps) {
    if (!comps.length) return emptyVector('阵容功能标签缺数据。');
    const max = Math.max(1, ...comps.map((c) => c.games));
    return `<div class="xc-comp-list">${comps.slice(0, 6).map((c) => `<div class="xc-comp-row">
      <b>${esc(c.tag)}</b>
      <i><span style="width:${(c.games / max * 100).toFixed(1)}%"></span></i>
      <span>${c.games} 局</span>
      <em>${c.decided ? fmt.pct(c.rate.value) : '—'}</em>
    </div>`).join('')}</div>`;
  }

  function heroRank(items, mode, baseline) {
    if (!items.length) return emptyVector('英雄样本不足。');
    return `<div class="xc-hero-rank">${items.slice(0, 12).map((x) => {
      const rate = mode === 'own' ? x.shrunk : x.rate;
      const pos = num(rate) ? Math.max(0, Math.min(100, rate * 100)) : null;
      return `<div class="xc-hero-rank-row">
        <b class="xc-hero-rank-name">${esc(x.hero)}</b>
        <span class="xc-hero-rank-games">${x.games} 局</span>
        <i class="xc-hero-track">${num(baseline) ? `<u style="left:${Math.max(0, Math.min(100, baseline)).toFixed(1)}%"></u>` : ''}${pos === null ? '' : `<b class="dot ${rate >= 0.5 ? 'is-win' : 'is-loss'}" style="left:${pos.toFixed(1)}%"></b>`}</i>
        <em class="${rate >= 0.5 ? 'is-win' : 'is-loss'}">${fmt.pct(rate)}</em>
        <small>10′ ${fmt.signed(x.at10)}</small>
      </div>`;
    }).join('')}</div>`;
  }

  function pairVisual(pairs, tone) {
    if (!pairs.length) return emptyVector('同组合达到 3 局的样本还不够。');
    return `<div class="xc-pair-list">${pairs.map((p) => {
      const rate = (p.rate || 0) * 100;
      const base = (p.otherRate || 0) * 100;
      const lift = p.lift || 0;
      return `<div class="xc-pair-row">
        <b>${esc(p.label)}</b>
        <span class="xc-pair-record">${p.wins}/${p.n}</span>
        <i class="xc-pair-track"><u style="left:${Math.max(0, Math.min(100, base)).toFixed(1)}%"></u><span style="left:${Math.min(rate, base).toFixed(1)}%;width:${Math.max(0.8, Math.abs(rate - base)).toFixed(1)}%"></span><b class="${tone}" style="left:${Math.max(0, Math.min(100, rate)).toFixed(1)}%"></b></i>
        <em class="${lift >= 0 ? 'is-win' : 'is-loss'}">${lift >= 0 ? '+' : '−'}${Math.round(Math.abs(lift) * 100)}pp</em>
      </div>`;
    }).join('')}</div>`;
  }

  function opponentHeroStats(vectors) {
    const map = new Map();
    for (const v of vectors) {
      for (const hero of (v.heroesFoe || [])) {
        const e = map.get(hero) || { hero, games: 0, wins: 0, decided: 0, at10: [] };
        e.games += 1;
        if (v.result === 'win') e.wins += 1;
        if (v.result === 'win' || v.result === 'loss') e.decided += 1;
        if (num(v.at10)) e.at10.push(v.at10);
        map.set(hero, e);
      }
    }
    return [...map.values()].filter((e) => e.games >= 2).sort((a, b) => b.games - a.games).slice(0, 12)
      .map((e) => ({ ...e, rate: e.decided ? e.wins / e.decided : null, at10: e.at10.length ? fmt.median(e.at10) : null }));
  }

  function playerHeroStats(vectors) {
    const map = new Map();
    for (const v of vectors) {
      for (const p of (v.pl || [])) {
        if (p.camp !== v.camp || !p.name || !p.hero) continue;
        const key = `${p.name}|${p.hero}|${p.pos || ''}`;
        const e = map.get(key) || { name: p.name, hero: p.hero, pos: p.pos || '', games: 0, wins: 0, decided: 0 };
        e.games += 1;
        if (v.result === 'win') e.wins += 1;
        if (v.result === 'win' || v.result === 'loss') e.decided += 1;
        map.set(key, e);
      }
    }
    return [...map.values()].filter((e) => e.games >= 3).sort((a, b) => b.games - a.games).slice(0, 12);
  }

  function draftCards(a, sum, vectors) {
    if (!a || !a.total) return module({ id: 'draft-empty', span: 12, kicker: '英雄和 BP', title: '没有可用的英雄 / BP 数据', body: emptyVector('先补齐十人面板或 BP 名单。') });
    const d = a.draft;
    const oppHeroes = opponentHeroStats(vectors);
    const playerHeroes = playerHeroStats(vectors);
    const bestPair = d.pairs.best[0];
    return `${module({
      id: 'draft-signature', span: 7, kicker: '英雄和 BP · 阵容', meta: `${d.coverage.comp} 局有标签`,
      title: '五路签名',
      body: lineup(d),
    })}${module({
      id: 'draft-comps', span: 5, kicker: '英雄和 BP · 体系', meta: `${d.comps.length} 套`,
      title: d.comps.length ? `「${d.comps[0].tag}」出现最多` : '体系标签',
      body: compRows(d.comps),
    })}${module({
      id: 'draft-heroes', span: 6, kicker: '英雄和 BP · 我方英雄池', meta: `${d.heroes.length} 个英雄`,
      title: d.heroes[0] ? `${d.heroes[0].hero} 出场最多` : '我方英雄池',
      body: heroRank(d.heroes, 'own', sum.totals.gameWinRate),
    })}${module({
      id: 'draft-opp-heroes', span: 6, kicker: '英雄和 BP · 对手英雄', meta: `${oppHeroes.length} 个常见`,
      title: oppHeroes.length ? `对手常拿 ${oppHeroes.slice(0, 3).map((x) => x.hero).join(' / ')}` : '对手英雄样本不足',
      body: heroRank(oppHeroes, 'opp'),
    })}${module({
      id: 'draft-pairs', span: 7, kicker: '英雄和 BP · 双人组合', meta: `${d.pairs.n} 组达到 3 局`,
      title: bestPair ? `「${bestPair.label}」比不带它高 ${Math.round(Math.abs(bestPair.lift || 0) * 100)} 个百分点` : '组合样本还不够',
      body: d.pairs.best.length || d.pairs.worst.length ? `<div class="xc-pair-split">
        <div><h4 class="is-win">更顺</h4>${pairVisual(d.pairs.best, 'is-win')}</div>
        <div><h4 class="is-loss">更吃力</h4>${pairVisual(d.pairs.worst, 'is-loss')}</div>
      </div>` : emptyVector('同组合达到 3 局的样本还不够。'),
    })}${module({
      id: 'draft-sides', span: 5, kicker: '英雄和 BP · 蓝红方与 ban', meta: `${d.coverage.bans} 局可拆 ban`,
      title: '蓝红方与 ban 位',
      body: `<div class="xc-sides">${d.sides.map((s) => `<div class="xc-side ${s.side}">
        <span>${s.side === 'blue' ? '蓝方' : '红方'}</span>
        <b>${s.wins}<i>–</i>${s.n - s.wins}</b>
        <em>${fmt.pct(s.rate.value)}</em>
        <small>10′ ${fmt.signed(s.at10)}</small>
      </div>`).join('')}</div>
      <div class="xc-bans">
        <div><h4>我们 ban</h4>${d.bansOwn.slice(0, 4).map((b) => `<div class="xc-ban-row"><span>${esc(b.hero)}</span><em>${b.games} 次</em></div>`).join('') || '<p class="xc-muted">没有数据</p>'}</div>
        <div><h4>对手 ban 我们</h4>${d.bansFoe.slice(0, 4).map((b) => `<div class="xc-ban-row"><span>${esc(b.hero)}</span><em>${b.games} 次 · 我们 ${b.rate.n ? fmt.pct(b.rate.value) : '—'}</em></div>`).join('') || '<p class="xc-muted">没有数据</p>'}</div>
      </div>`,
    })}${module({
      id: 'draft-consumption', span: 5, kicker: '英雄和 BP · 全局消耗', meta: `${sum.consumption.reduce((s, c) => s + c.n, 0)} 局`,
      title: sum.consumption.length ? `到 G${sum.consumption[sum.consumption.length - 1].gameIndex}，我方平均已用 ${fmt.fixed(sum.consumption[sum.consumption.length - 1].avgUsedUs, 1)} 个` : 'BP 消耗',
      body: sum.consumption.length ? `<div class="xc-cons">${sum.consumption.map((c, i) => {
        const prev = sum.consumption[i - 1];
        const add = prev && num(c.avgUsedUs) && num(prev.avgUsedUs) ? c.avgUsedUs - prev.avgUsedUs : null;
        return `<div class="xc-cons-row">
          <span class="xc-cons-g">G${c.gameIndex}</span>
          <i class="xc-cons-track"><b class="is-win" style="width:${Math.min(100, (c.avgUsedUs || 0) / 15 * 100).toFixed(1)}%"></b></i>
          <i class="xc-cons-track"><b class="is-loss" style="width:${Math.min(100, (c.avgUsedFoe || 0) / 15 * 100).toFixed(1)}%"></b></i>
          <b class="xc-cons-val">${fmt.fixed(c.avgUsedUs, 1)}<em> / ${fmt.fixed(c.avgUsedFoe, 1)}</em></b>
          <small>${num(add) ? `+${fmt.fixed(add, 1)}` : '—'}</small>
        </div>`;
      }).join('')}</div>` : emptyVector('没有可读的阵容账本。'),
    })}${module({
      id: 'draft-comfort', span: 7, kicker: '英雄和 BP · 选手英雄舒适度', meta: `${playerHeroes.length} 组达到 3 局`,
      title: playerHeroes.length ? `${playerHeroes[0].name} 的 ${playerHeroes[0].hero} 出场最多` : '选手与英雄组合',
      body: playerHeroes.length ? `<div class="xc-comfort">${playerHeroes.map((x) => `<div class="xc-comfort-tile">
        <span>${esc(x.name)}</span>
        <b>${esc(x.hero)}</b>
        <small>${esc(x.pos)} · ${x.games} 局</small>
        <em class="${x.wins >= x.decided - x.wins ? 'is-win' : 'is-loss'}">${fmt.pct(x.decided ? x.wins / x.decided : null)}</em>
      </div>`).join('')}</div>` : emptyVector('选手与同一个英雄达到 3 局的样本还不够。'),
    })}`;
  }

  /* ── 页面 ───────────────────────────────────────────────────── */
  function listHtml() {
    if (state.error) return `<div class="page xc-page"><section class="xc-blank"><h1>读不到跨局数据</h1><p>${esc(state.error)}</p><button type="button" class="xc-btn" data-cx-retry>重试</button></section></div>`;
    if (!state.allSeries.length) {
      return `<div class="page xc-page xc-series-page">${scopeBarHtml(null)}<section class="xc-blank"><h1>还没有已确认的系列赛</h1><p>跨局分析以「多场 BO」为单位；先到系列赛编组确认 BO3/5/7。</p><a class="xc-btn primary" href="#series-builder">去系列赛编组 →</a></section></div>`;
    }
    const series = filteredSeries();
    if (!series.length) {
      return `<div class="page xc-page xc-series-page">${scopeBarHtml(null)}<section class="xc-blank"><h1>当前范围没有系列赛</h1><p>放宽时间或清除赛制、对手、状态筛选。</p><button type="button" class="xc-btn primary" data-cx-clear>清除筛选</button></section></div>`;
    }
    const sum = deriveSummary(series);
    const ids = new Set(series.map((s) => s.id));
    const attention = (state.attention || []).filter((item) => ids.has(item.seriesId));
    const vectors = selectedVectors(series);
    const a = analyzeCohort(vectors);
    const sectionMeta = {
      overview: `${sum.totals.series} 场 · ${sum.totals.games} 局`,
      ingame: `${a.total} 局有过程`,
      postgame: `${a.total} 局有面板`,
      draft: `${a.draft.heroes.length} 个英雄`,
    };
    return `<div class="page xc-page xc-series-page">
      ${headHtml(sum, series)}
      ${scopeBarHtml(sum)}
      <section class="xc-section" id="xc-sec-overview" data-cx-section="overview"${state.section === 'overview' ? '' : ' hidden'}>
        ${sectionHead('overview', sectionMeta.overview)}
        ${overviewStatement(sum, a, series)}
        <div class="xc-grid">${overviewCards(sum, series, a, attention)}</div>
      </section>
      <section class="xc-section" id="xc-sec-ingame" data-cx-section="ingame"${state.section === 'ingame' ? '' : ' hidden'}>
        ${sectionHead('ingame', sectionMeta.ingame)}
        ${ingameStatement(a)}
        ${state.vectorsError ? '<div class="xc-section-note">各局向量没取到，赛中分析暂不可用。</div>' : ''}
        <div class="xc-grid">${ingameCards(a)}</div>
      </section>
      <section class="xc-section" id="xc-sec-postgame" data-cx-section="postgame"${state.section === 'postgame' ? '' : ' hidden'}>
        ${sectionHead('postgame', sectionMeta.postgame)}
        ${postgameStatement(a)}
        ${state.vectorsError ? '<div class="xc-section-note">各局向量没取到，赛后分析暂不可用。</div>' : ''}
        <div class="xc-grid">${postgameCards(a, attention)}</div>
      </section>
      <section class="xc-section" id="xc-sec-draft" data-cx-section="draft"${state.section === 'draft' ? '' : ' hidden'}>
        ${sectionHead('draft', sectionMeta.draft)}
        ${draftStatement(a)}
        ${state.vectorsError ? '<div class="xc-section-note">各局向量没取到，英雄和 BP 暂不可用。</div>' : ''}
        <div class="xc-grid">${draftCards(a, sum, vectors)}</div>
      </section>
    </div>`;
  }

  /* ── 单场大场分析 ─────────────────────────────────────────── */
  function detailChart(games) {
    const rows = games.filter((g) => num(g.at10) || num(g.finalDiff));
    if (rows.length < 2) return '<p class="xc-muted">过程数据不足，画不出逐局走势。</p>';
    const H = 190, W = 1000;
    const vals = rows.flatMap((g) => [g.at10, g.finalDiff]).filter(num);
    const max = Math.max(1000, ...vals.map((v) => Math.abs(v)));
    const xOf = (i) => 30 + (i / Math.max(1, rows.length - 1)) * 940;
    const yOf = (v) => H / 2 - (v / max) * (H / 2 - 24);
    const line = (key, cls) => {
      const d = rows.map((g, i) => (num(g[key]) ? `${i ? 'L' : 'M'}${xOf(i).toFixed(1)},${yOf(g[key]).toFixed(1)}` : '')).filter(Boolean).join(' ');
      return d ? `<path class="line ${cls}" d="${d}" stroke-width="2.2" fill="none" vector-effect="non-scaling-stroke"/>` : '';
    };
    const dots = rows.map((g, i) => {
      if (!num(g.at10)) return '';
      return `<a class="xv-dot ${g.result === 'win' ? 'win' : g.result === 'loss' ? 'loss' : 'na'}" style="left:${(xOf(i) / W * 100).toFixed(2)}%;top:${(yOf(g.at10) / H * 100).toFixed(2)}%" href="#match/${encodeURIComponent(g.matchKey)}" title="G${g.gameIndex} · 10′ ${fmt.signed(g.at10)}"></a>`;
    }).join('');
    return `<div class="xv-chartwrap">
      <div class="xv-chartbox" style="height:${H}px"><svg class="xv-shape" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        ${Array.from({ length: 5 }, (_, i) => `<line class="grid" x1="0" x2="${W}" y1="${H * i / 4}" y2="${H * i / 4}" vector-effect="non-scaling-stroke"/>`).join('')}
        <line class="zero" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>
        ${line('at10', 'winline')}${line('finalDiff', 'roll')}
      </svg><span class="xv-y-lab top">${fmt.signed(max)}</span><span class="xv-y-lab mid">0</span><span class="xv-y-lab bottom">${fmt.signed(-max)}</span>${dots}</div>
      <div class="xv-axis">${rows.map((g) => `<span>G${g.gameIndex}</span>`).join('')}</div>
      <div class="xv-legend"><span><i class="win"></i>10 分钟</span><span><i class="roll"></i>终局</span></div>
    </div>`;
  }

  function miniGames(games) {
    return `<div class="xc-games">${games.map((g) => {
      const res = g.result === 'win' ? 'win' : g.result === 'loss' ? 'loss' : 'na';
      return `<a class="xc-gcard ${res}" href="#match/${encodeURIComponent(g.matchKey)}">
        <b>G${g.gameIndex}</b><span>${res === 'win' ? '胜' : res === 'loss' ? '负' : '—'}</span>
        <small>${num(g.at10) ? `10′ ${fmt.signed(g.at10)}` : '无过程'}</small>
        <small>${fmt.duration(g.duration)}</small>
      </a>`;
    }).join('')}</div>`;
  }

  function verdictText(series, games, score) {
    const us = Number(score?.us) || 0, them = Number(score?.them) || 0;
    const bestOf = Number(series.bestOf) || games.length;
    const results = games.map((g) => g.result).filter((r) => r === 'win' || r === 'loss');
    const full = games.length >= bestOf;
    if (!scoreValid(series)) return `比分 ${us}:${them} 与 BO${bestOf} 赛制不一致，先核实编组/规则集，再谈逆转或零封。`;
    if (series.completionMode === 'fixed') {
      return `固定打满 ${games.length} 局，${us} 胜 ${them} 负。`;
    }
    if (us > them) {
      if (them === 0) return `直落 ${us} 局拿下；没有给对手任何一局。`;
      if (results[0] === 'loss') return `先丢一局，随后连扳 ${us} 局完成逆转。`;
      return `以大场 ${us}:${them} 拿下${full ? '，打满全局数' : ''}。`;
    }
    if (them > us) {
      if (us === 0) return `被直落 ${them} 局；没有拿到一局。`;
      if (results[0] === 'win') return `先赢一局，随后被连扳 ${them} 局。`;
      return `以大场 ${us}:${them} 落败${full ? '，打满全局数' : ''}。`;
    }
    return '系列赛未分胜负，先确认比分或采集完整性。';
  }

  function detailHtml() {
    if (state.detailError) return `<div class="page xc-page"><a class="xc-back" href="#cross${scopeQuery()}">← 返回跨局分析</a><section class="xc-blank"><h1>读不到这场大场</h1><p>${esc(state.detailError)}</p></section></div>`;
    const data = state.detail;
    if (!data) return `<div class="page xc-page"><div class="loading">正在读取大场明细…</div></div>`;
    const series = data.series || {};
    const games = (data.games || []).slice().sort((a, b) => (Number(a.gameIndex) || 0) - (Number(b.gameIndex) || 0));
    const score = data.score || series.score || { us: 0, them: 0 };
    const us = Number(score.us) || 0, them = Number(score.them) || 0;
    const resultWord = us > them ? '战胜' : us < them ? '不敌' : '对阵';
    const durations = games.map((g) => g.duration).filter(num);
    const at10s = games.map((g) => g.at10).filter(num);
    const verdict = verdictText(series, games, score);
    const rule = series.ruleset?.name || series.rulesetId || '规则集未设置';
    const back = `#cross${scopeQuery()}`;
    const transitions = games.filter((g) => g.gameIndex > 1);
    const adjustments = transitions.map((g) => {
      const adj = g.adjustment || {};
      const resp = (data.opponentResponse || []).find((r) => Number(r.gameIndex) === Number(g.gameIndex)) || {};
      const chips = (arr, cls = '') => (arr || []).map((x) => `<span class="xc-hero-pill ${cls}">${esc(x)}</span>`).join('') || '<span class="xc-muted">无</span>';
      return `<div class="xc-transition">
        <div class="xc-transition-head"><b>G${g.gameIndex - 1} → G${g.gameIndex}</b><span>${esc(adj.changeLabel || '对照缺失')}</span></div>
        <div class="xc-transition-grid">
          <div><small>我方新增</small><div class="xc-hero-chips">${chips(adj.newOwn, 'new')}</div></div>
          <div><small>我方移出</small><div class="xc-hero-chips">${chips(adj.droppedOwn, 'out')}</div></div>
          <div><small>对方新增</small><div class="xc-hero-chips">${chips(resp.newFoe, 'new')}</div></div>
          <div><small>对方移出</small><div class="xc-hero-chips">${chips(resp.droppedFoe, 'out')}</div></div>
        </div>
        <p class="xc-muted">${adj.compChanged ? '我方体系标签变化；' : ''}${resp.compChanged ? '对方体系标签变化；' : ''}${(resp.banRepeat || []).length ? `对方重复 ban：${esc(resp.banRepeat.join('、'))}` : ''}${!adj.compChanged && !resp.compChanged && !(resp.banRepeat || []).length ? '没有观察到明显的体系/ban 调整。' : ''}</p>
      </div>`;
    }).join('');
    const ledgerRows = games.map((g) => {
      const bp = (data.bpLedger?.perGame || []).find((x) => Number(x.gameIndex) === Number(g.gameIndex)) || {};
      const newOwn = (g.adjustment || {}).newOwn || [];
      return `<tr><td class="num">G${g.gameIndex}</td><td class="num">${fmt.count(bp.usedUsCount)}</td><td class="num">${fmt.count(bp.usedFoeCount)}</td><td>${esc(newOwn.join('、') || '—')}</td><td class="num">${fmt.count((bp.blockUs || []).length)}</td></tr>`;
    }).join('');
    const afterPairs = (data.afterLoss?.pairs || []).map((p) => `<div class="xc-pair-card">
      <b>G${p.fromGame} → G${p.toGame}</b><span class="${p.nextResult === 'win' ? 'win' : 'loss'}">${p.nextResult === 'win' ? '下一局胜' : '下一局负'}</span>
      <small>${num(p.at10Delta) ? `10′ 变化 ${fmt.signed(p.at10Delta)}` : '缺过程数据，不比较经济差'}</small>
    </div>`).join('');
    const responseRows = (data.opponentResponse || []).map((r) => `<tr><td class="num">G${r.gameIndex}</td><td>${esc((r.newFoe || []).join('、') || '—')}</td><td>${esc((r.droppedFoe || []).join('、') || '—')}</td><td>${r.compChanged ? '是' : '否'}</td><td>${esc((r.banRepeat || []).join('、') || '—')}</td></tr>`).join('');
    const caveats = (data.caveats || []).map((c) => `<li>${esc(c)}</li>`).join('');
    const coverage = data.coverage || {};
    return `<div class="page xc-page xc-series-detail">
      <a class="xc-back" href="${back}">← 返回跨局分析</a>
      <header class="xc-head xc-detail-head">
        <div class="xc-head-main">
          <p class="xc-eyebrow">大场分析 <i>/</i> BO${esc(String(series.bestOf || '—'))} <i>/</i> ${esc(String(series.startAt || games[0]?.date || '—'))} <i>/</i> ${esc(COMPLETION_LABEL[series.completion] || series.completion || '—')}</p>
          <h1 class="xc-title">${scoreValid(series) ? `${us}:${them} ${resultWord}` : `比分 ${us}:${them} 待核实`} ${esc(series.opponent || '对手待补')} <span class="xc-title-ci">${esc(rule)}</span></h1>
          <p class="xc-sub">${games.length} 局 · ${durations.length ? `平均 ${fmt.duration(fmt.mean(durations))}` : '缺时长'} · ${at10s.length ? `10 分钟差 ${fmt.signed(fmt.median(at10s))}` : '缺 10 分钟过程'} · ${series.completionMode === 'fixed' ? '固定打满' : '标准决胜'} · ${scoreValid(series) ? '' : '比分与赛制不一致 · '}${series.status === 'needs_review' ? '编组待核实' : '编组已确认'}</p>
          <div class="xc-coverage"><span class="xc-cov"><b>${fmt.count(games.length)}</b> 小局</span><span class="xc-cov"><b>${fmt.count(coverage.withVector || 0)}</b> 有向量</span><span class="xc-cov"><b>${fmt.count(coverage.orderKnownGames || 0)}</b> 有手序</span><span class="xc-cov"><b>${fmt.count(coverage.at10Games || 0)}</b> 有 10 分钟</span></div>
        </div>
        <div class="xc-head-actions"><a class="xc-btn" href="#series-builder">去编组中心 →</a></div>
      </header>
      <div class="xc-cards">
        <article class="xc-card xc-span-12">
          <div class="xc-card-head"><span class="xc-kicker">系列赛结论</span><span class="xc-badge">${games.length} 局</span></div>
          <h3 class="xc-card-title">${esc(verdict)}</h3>
          ${miniGames(games)}
          ${detailChart(games)}
          <p class="xc-card-note">点任意一局进入单局复盘；线是 10 分钟经济差与终局经济差，本队减对手。</p>
        </article>
        ${card({ id: 'detail-games', span: 12, kicker: '逐局对比', sample: `${games.length} 局`, title: '每一局的结果、经济差与阵容', lede: '调整按终局阵容口径；没有 BP 手序时，不推断先后手针对。', body: `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th>结果</th><th class="num">时长</th><th class="num">10′差</th><th class="num">终局差</th><th>我方体系</th><th>对方体系</th><th>调整</th><th>复盘</th></tr></thead><tbody>${games.map((g) => `<tr><td class="num">G${g.gameIndex}</td><td><b class="${g.result === 'win' ? 'win' : 'loss'}">${g.result === 'win' ? '胜' : g.result === 'loss' ? '负' : '—'}</b></td><td class="num">${fmt.duration(g.duration)}</td><td class="num">${fmt.signed(g.at10)}</td><td class="num">${fmt.signed(g.finalDiff)}</td><td>${esc(g.compOwn || '—')}</td><td>${esc(g.compFoe || '—')}</td><td>${esc(g.adjustment?.changeLabel || '—')}</td><td><a href="#match/${encodeURIComponent(g.matchKey)}">打开 →</a></td></tr>`).join('')}</tbody></table></div>` })}
        ${card({ id: 'detail-adjust', span: 7, kicker: '调整与对手回应', sample: `${transitions.length} 次过渡`, title: transitions.length ? '每一局之间改了什么' : '没有可对照的连续局', lede: '我方新增/移出、对方新增/移出与重复 ban；终局阵容口径。', body: adjustments || '<p class="xc-muted">只有一局，或缺少阵容。</p>', method: '相邻两局对比终局阵容；有手序才谈「针对顺序」，这里不做先后手推断。' })}
        ${card({ id: 'detail-ledger', span: 5, kicker: '全局 BP 消耗', sample: `${ledgerRows ? games.length : 0} 局`, title: esc(rule), lede: '每局累计曾选与我方不可再选；跨局复用按规则集检查。', body: ledgerRows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th class="num">我</th><th class="num">敌</th><th>本局新增</th><th class="num">我方已锁</th></tr></thead><tbody>${ledgerRows}</tbody></table></div><p class="xc-card-note">${esc(series.ruleset?.note || '')}</p>` : '<p class="xc-muted">没有阵容账本。</p>', method: '累计曾选按系列赛推进；规则集以本场设置为准；检测到复用会写在覆盖说明里。' })}
        ${card({ id: 'detail-afterloss', span: 6, kicker: '败局恢复', sample: `${(data.afterLoss?.pairs || []).length} 对`, title: data.afterLoss?.n ? `下一局赢 ${data.afterLoss.nextWins}/${data.afterLoss.n}（${pct100(data.afterLoss.nextWinRate)}）` : '没有输局后的下一局', lede: data.afterLoss?.deltaSamples ? `下一局 10 分钟差常见变化 ${fmt.signed(data.afterLoss.medianAt10Delta)}（${data.afterLoss.deltaSamples} 对）` : '缺过程数据，不比较经济差。', body: `${afterPairs || '<p class="xc-muted">没有可对照的连败过渡。</p>'}${data.compSwitch?.pairs ? `<div class="xc-risk-grid"><div class="xc-risk"><span>体系延续后</span><b>${pct100(data.compSwitch.continued?.winRate)}</b><small>${data.compSwitch.continued?.nextWins || 0}/${data.compSwitch.continued?.n || 0} 次</small></div><div class="xc-risk"><span>体系切换后</span><b>${pct100(data.compSwitch.switched?.winRate)}</b><small>${data.compSwitch.switched?.nextWins || 0}/${data.compSwitch.switched?.n || 0} 次</small></div></div>` : ''}`, note: '调整与下一局胜负是关联，不是因果。' })}
        ${card({ id: 'detail-response', span: 6, kicker: '对手回应', sample: `${(data.opponentResponse || []).length} 次`, title: responseRows ? '对手逐局的新增/移出与禁用' : '没有可读的对手调整', lede: '只有终局名单时，这里显示的是「换人」，不是「第几手针对」。', body: responseRows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th>新增</th><th>移出</th><th>换体系</th><th>重复 ban</th></tr></thead><tbody>${responseRows}</tbody></table></div>` : '<p class="xc-muted">阵容缺失，无法对照。</p>' })}
        ${card({ id: 'detail-coverage', span: 12, kicker: '覆盖与口径', sample: `${coverage.games || games.length} 局`, title: '这场大场能回答什么、不能回答什么', lede: `向量 ${coverage.withVector || 0} 局 · 明细 ${coverage.withDetail || 0} 局 · 手序 ${coverage.orderKnownGames || 0} 局 · 过程 ${coverage.processKnownGames || 0} 局 · 10 分钟 ${coverage.at10Games || 0} 局`, body: (caveats || !scoreValid(series)) ? `<ul class="xc-caveats-list">${scoreValid(series) ? '' : `<li>比分 ${us}:${them} 与 BO${series.bestOf || '—'} 赛制不一致：先核实编组、赛制或规则集，本页不据此下大场结论。</li>`}${caveats}</ul>` : '<p class="xc-muted">没有额外口径警示。</p>' })}
      </div>
      <p class="xc-source"><b>数据</b> 系列赛编组 + 各局向量/明细；大场结论只在这组 BO 内成立，不跨系列赛外推。</p>
    </div>`;
  }

  function updateSectionNav() {
    if (!isCrossRoute()) return;
    const sections = [...document.querySelectorAll('[data-cx-section]')];
    if (!sections.length) return;
    const marker = window.scrollY + 150;
    let active = sections[0];
    for (const section of sections) {
      if (section.offsetTop <= marker) active = section;
    }
    document.querySelectorAll('[data-cx-section-link]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.cxSectionLink === active.dataset.cxSection);
    });
  }

  function switchViz(id, key) {
    vizViews[id] = key;
    const wrap = [...document.querySelectorAll('[data-xc-viz]')].find((el) => el.dataset.xcViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-xc-view-btn]').forEach((b) => b.classList.toggle('is-on', b.dataset.xcViewBtn === key));
    wrap.querySelectorAll('.xv-view').forEach((v) => {
      const on = v.dataset.xcView === key;
      v.hidden = !on;
    });
  }

  function showVizTip(target, event) {
    const wrap = target.closest('[data-xc-viz]');
    if (!wrap) return;
    const tip = wrap.querySelector('.xv-tip');
    if (!tip) return;
    tip.textContent = target.dataset.xcTip || '';
    tip.hidden = false;
    const box = wrap.querySelector('.xv-stage')?.getBoundingClientRect();
    if (!box) return;
    tip.style.left = `${Math.max(8, Math.min(event.clientX - box.left + 12, Math.max(8, box.width - 260)))}px`;
    tip.style.top = `${Math.max(6, Math.min(event.clientY - box.top - 36, Math.max(6, box.height - 48)))}px`;
  }

  function hideVizTips() {
    document.querySelectorAll('.xv-tip').forEach((t) => { t.hidden = true; });
  }

  /* ── 渲染与事件 ───────────────────────────────────────────── */
  function paint(html) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = html;
    requestAnimationFrame(() => {
      document.querySelectorAll('[data-cx-section]').forEach((s) => { s.hidden = s.dataset.cxSection !== state.section; });
    });
  }

  function paintLoading(text) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = `<div class="page xc-page"><div class="loading">${esc(text)}</div></div>`;
  }

  function ensure(force = false) {
    if (!isCrossRoute()) return;
    readScope();
    const legacy = routeParts();
    if (legacy[0] === 'cross' && legacy[1] === 'series' && legacy[2]) {
      location.replace(`#biggame/${encodeURIComponent(decodeURIComponent(legacy[2]))}${scopeQuery()}`);
      return;
    }
    const detailId = detailIdOf();
    if (detailId) {
      if (force || state.detailId !== detailId || (!state.detail && !state.detailLoading)) loadDetail(detailId);
      else if (state.detail) paint(detailHtml());
      return;
    }
    if (force || !state.loaded) loadAll();
    else paint(listHtml());
  }

  function render() {
    return '<div class="page xc-page" data-cx-root><div class="loading">正在汇总系列赛…</div></div>';
  }

  function bind(node) {
    root = node;
    if (!bind.done) {
      bind.done = true;
      document.addEventListener('click', onClick);
      document.addEventListener('change', onChange);
      document.addEventListener('mousemove', (event) => {
        if (!isCrossRoute()) return;
        const tip = event.target.closest ? event.target.closest('[data-xc-tip]') : null;
        if (tip) showVizTip(tip, event); else hideVizTips();
      });
      document.addEventListener('mouseleave', hideVizTips);
    }
    ensure(true);
  }

  function onClick(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const rangeBtn = event.target.closest('[data-cx-range]');
    if (rangeBtn) { scope.range = rangeBtn.dataset.cxRange; if (scope.range !== 'custom') { scope.from = ''; scope.to = ''; } syncScopeUrl(); paint(listHtml()); return; }
    const boBtn = event.target.closest('[data-cx-bo]');
    if (boBtn) { scope.bo = boBtn.dataset.cxBo; syncScopeUrl(); paint(listHtml()); return; }
    if (event.target.closest('[data-cx-clear]')) {
      Object.assign(scope, { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '', session: '', status: '', completion: '' });
      syncScopeUrl(); paint(listHtml()); return;
    }
    if (event.target.closest('[data-cx-retry]')) { state.loaded = false; loadAll(); return; }
    const sectionBtn = event.target.closest('[data-cx-section-link]');
    if (sectionBtn) {
      state.section = sectionBtn.dataset.cxSectionLink;
      document.querySelectorAll('[data-cx-section]').forEach((s) => { s.hidden = s.dataset.cxSection !== state.section; });
      document.querySelectorAll('[data-cx-section-link]').forEach((b) => b.classList.toggle('is-active', b === sectionBtn));
      syncScopeUrl();
      const bar = document.querySelector('.xc-toolbar');
      if (bar) bar.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const viewBtn = event.target.closest('[data-xc-view-btn]');
    if (viewBtn) { switchViz(viewBtn.dataset.xcVizId, viewBtn.dataset.xcViewBtn); return; }
  }

  function onChange(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const dateNode = event.target.closest('[data-cx-date]');
    if (dateNode) {
      if (dateNode.dataset.cxDate === 'from') scope.from = dateNode.value;
      if (dateNode.dataset.cxDate === 'to') scope.to = dateNode.value;
      if (scope.from || scope.to) scope.range = 'custom';
      syncScopeUrl(); paint(listHtml()); return;
    }
    const node = event.target.closest('[data-cx]');
    if (!node) return;
    const key = node.dataset.cx;
    if (key === 'opponent') scope.opponent = node.value;
    else if (key === 'session') scope.session = node.value;
    else if (key === 'status') scope.status = node.value;
    else if (key === 'completion') scope.completion = node.value;
    syncScopeUrl(); paint(listHtml());
  }

  return { render, bind };
}
