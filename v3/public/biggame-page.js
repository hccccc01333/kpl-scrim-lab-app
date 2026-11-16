/* 跨局分析（2026-11-15 · 系列赛级）
 *
 * 这一页的单位是「大场」：把多场已确认的 BO3/5/7 放在一起看。
 * - 多场 BO：大场战绩、局序表现、败局后下一局、全局 BP 消耗、对手、关注清单、系列赛列表。
 * - 单场 BO：#biggame/<id> 是独立的大场分析界面（逐局走势、挖掘结论、调整与回应、
 *   BP 价值、选手状态、历史对照、覆盖）。
 *
 * 统计口径与 caveat 由 series_engine / series_insight 提供；本文件只做筛选、排版和图表。
 * 数据一次取全，范围/赛制/对手/训练组/状态在前端过滤，避免每次切换都重算。
 */

import { fmt } from './cross-analytics.js';
import { renderInsightCards } from './biggame-insight.js';

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

export function createBigGamePage(h) {
  const { esc } = h;
  let root = null;
  let generation = 0;
  let controller = null;
  const state = {
    allSeries: [], attention: [], rulesets: [], latestDate: '',
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
    const query = params.toString();
    return query ? `?${query}` : '';
  }

  function routeParts() {
    return String(location.hash || '').replace(/^#/, '').split('?')[0].split('/');
  }

  function detailIdOf() {
    const parts = routeParts();
    return parts[0] === 'biggame' && parts[1] ? decodeURIComponent(parts[1]) : '';
  }

  function isCrossRoute() {
    return routeParts()[0] === 'biggame';
  }

  function syncScopeUrl() {
    const detailId = detailIdOf();
    const path = detailId ? `#biggame/${encodeURIComponent(detailId)}` : '#biggame';
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
    let close = 0, sweep = 0, missing = 0, fixed = 0, invalid = 0;
    for (const s of series) {
      if (s.completion === 'completed') totals.completed += 1;
      if (s.completionMode === 'fixed') fixed += 1;
      if (!scoreValid(s)) invalid += 1;
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
      close, sweep, missing, fixed, invalid,
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
      const summaryResponse = await fetch(`${API_BASE}/api/cross/series-summary`, { signal: controller.signal, cache: 'no-store' });
      if (gen !== generation) return;
      if (!summaryResponse.ok) throw new Error(`系列赛汇总 ${summaryResponse.status}`);
      const payload = await summaryResponse.json();
      state.allSeries = payload.series || [];
      state.attention = payload.summary?.attention || [];
      state.rulesets = payload.rulesets || [];
      state.latestDate = state.allSeries.map(seriesDate).filter(Boolean).sort().pop() || '';
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
  function headHtml(sum, series) {
    const t = sum.totals;
    const title = t.series
      ? `${t.series} 场已确认 BO，${t.seriesWins} 胜 ${t.seriesLosses} 负`
      : '还没有已确认的大场';
    const bits = [];
    if (t.games) bits.push(`小局 <b>${t.gameWins} 胜 ${t.games - t.gameWins} 负</b>（${pct100(t.gameWinRate)}）`);
    if (t.games) bits.push(`场均 <b>${fmt.fixed(t.avgGames, 1)}</b> 局`);
    if (t.series) bits.push(`${t.completed} 场已完赛`);
    if (t.series) bits.push(`${series.filter((s) => s.status === 'needs_review').length} 场待核实`);
    const cov = [
      ['大场', t.series], ['小局', t.games], ['已完赛', t.completed],
      ['打满', sum.close], ['零封', sum.sweep],
    ].map(([label, value]) => `<span class="xc-cov"><b>${fmt.count(value)}</b> ${label}</span>`).join('');
    return `<header class="xc-head xc-hero xc-bg-hero">
      <div class="xc-head-main">
        <p class="xc-eyebrow">大场分析 <i>/</i> 单场 BO <i>/</i> ${esc(scopeLabel())}</p>
        <h1 class="xc-title">${title}</h1>
        <p class="xc-sub">${bits.join(' · ') || '先完成系列赛编组，再进入单场大场分析。'}</p>
        <div class="xc-coverage">${cov}</div>
      </div>
      <div class="xc-head-actions"><a class="xc-btn" href="#series-builder">系列赛编组 →</a></div>
    </header>`;
  }

  function scopeBarHtml() {
    const seg = (list, current, attr) => `<div class="xc-seg" role="group">${list.map(([key, label]) =>
      `<button type="button" class="xc-segbtn" ${attr}="${key}" aria-pressed="${String(current) === key}">${esc(label)}</button>`).join('')}</div>`;
    const select = (key, label, list, value, emptyLabel) => `<label class="xc-field xc-select"><span>${label}</span><select data-cx="${key}"${list.length ? '' : ' disabled'}>
      <option value="">${esc(emptyLabel)}</option>${list.map((item) => `<option value="${esc(item)}"${item === value ? ' selected' : ''}>${esc(item)}</option>`).join('')}</select></label>`;
    return `<div class="xc-toolbar xc-series-toolbar"><div class="xc-scope">
      <div class="xc-fields">
        <div class="xc-field"><span>时间</span>${seg(RANGE_OPTIONS, scope.range, 'data-cx-range')}
          ${scope.range === 'custom' ? `<div class="xc-dates"><input type="date" data-cx-date="from" value="${esc(scope.from)}" aria-label="开始日期"><i>→</i><input type="date" data-cx-date="to" value="${esc(scope.to)}" aria-label="结束日期"></div>` : ''}
        </div>
        <div class="xc-field"><span>赛制</span>${seg(BO_OPTIONS, scope.bo, 'data-cx-bo')}</div>
        ${select('opponent', '对手', uniq('opponent'), scope.opponent, '全部对手')}
        ${select('session', '训练组', uniq('session'), scope.session, '全部训练组')}
        <label class="xc-field xc-select"><span>状态</span><select data-cx="status">${STATUS_OPTIONS.map(([key, label]) => `<option value="${key}"${key === scope.status ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
        <label class="xc-field xc-select"><span>完赛</span><select data-cx="completion">${COMPLETION_OPTIONS.map(([key, label]) => `<option value="${key}"${key === scope.completion ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
        ${scopeActive() ? '<button type="button" class="xc-clear" data-cx-clear>清除</button>' : ''}
      </div>
      <div class="xc-scope-meta"><span>当前范围 <b>${esc(scopeLabel())}</b></span><span>按大场统计；同一 BO 内小局不作为独立实验</span></div>
    </div></div>`;
  }

  /* ── 卡片 ─────────────────────────────────────────────────── */
  function card({ id, span = 6, kicker, sample, title, lede = '', chart = null, body = '', note = '', method = '' }) {
    return `<article class="xc-card xc-span-${span}" id="xc-${esc(id)}">
      <div class="xc-card-head"><span class="xc-kicker">${esc(kicker)}</span>${sample ? `<span class="xc-badge">${esc(sample)}</span>` : ''}</div>
      <h3 class="xc-card-title">${title}</h3>
      ${lede ? `<p class="xc-card-lede">${lede}</p>` : ''}
      ${chart ? `<div class="xc-card-chart">${renderViz({ ...chart, id: chart.id || id }, { view: (key) => vizViews[key] || 'a' })}</div>` : ''}
      ${body}
      ${note ? `<p class="xc-card-note">${note}</p>` : ''}
      <div class="xc-card-foot">${method ? `<details class="xc-method"><summary>口径</summary><p>${esc(method)}</p></details>` : '<span></span>'}</div>
    </article>`;
  }

  function barRow(label, value, sub, tone = '') {
    return `<div class="xc-bar-row">
      <span class="xc-bar-label">${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ''}</span>
      <i class="xc-bar-track"><b class="${tone}" style="width:${Math.max(1, Math.min(100, num(value) ? value : 0)).toFixed(1)}%"></b></i>
      <em class="xc-bar-val">${pct100(value)}</em>
    </div>`;
  }

  /* ── 多场模块 ─────────────────────────────────────────────── */
  function recordCard(sum) {
    const t = sum.totals;
    const maxDist = Math.max(1, ...sum.scoreDist.map((x) => x.n));
    const dist = sum.scoreDist.length ? sum.scoreDist.map((x) => {
      const [us, them] = x.label.split(':').map(Number);
      return `<div class="xc-scorebar">
        <span>${esc(x.label)}</span>
        <i><b class="${us > them ? 'win' : 'loss'}" style="width:${(x.n / maxDist * 100).toFixed(1)}%"></b></i>
        <em>${x.n} 场</em>
      </div>`;
    }).join('') : '<p class="xc-muted">还没有已确认的比分。</p>';
    return card({
      id: 'series-record', span: 12, kicker: '大场战绩', sample: `${t.series} 场系列赛`,
      title: t.series ? `大场 ${t.seriesWins} 胜 ${t.seriesLosses} 负，小局 ${t.gameWins} 胜 ${t.games - t.gameWins} 负` : '当前范围没有系列赛',
      lede: t.series ? `场均 ${fmt.fixed(t.avgGames, 1)} 局；${sum.close} 场分差 1 局，${sum.sweep} 场零封。大场胜率 ${pct100(t.seriesWinRate)}，小局胜率 ${pct100(t.gameWinRate)}。${sum.fixed ? `其中 ${sum.fixed} 场固定打满，比分是小局比分。` : ''}${sum.invalid ? ` ${sum.invalid} 场比分与赛制不一致，已在列表标出，先核实编组。` : ''}` : '先到「系列赛编组」确认 BO 关系。',
      body: `<div class="xc-kpis">
        <div class="xc-kpi"><span>大场胜率</span><b>${pct100(t.seriesWinRate)}</b><small>${rateText(t.seriesWins, t.seriesWins + t.seriesLosses)}${t.ci ? ` · 可信 ${ciText(t.ci)}` : ''}</small></div>
        <div class="xc-kpi"><span>小局胜率</span><b>${pct100(t.gameWinRate)}</b><small>${rateText(t.gameWins, t.games)}</small></div>
        <div class="xc-kpi"><span>场均局数</span><b>${fmt.fixed(t.avgGames, 1)}</b><small>${t.games} 小局 / ${t.series} 场</small></div>
        <div class="xc-kpi"><span>打满 / 零封</span><b>${sum.close} / ${sum.sweep}</b><small>分差 1 局 / 一方 0 胜</small></div>
      </div>
      <div class="xc-scorebars">${dist}</div>`,
      method: '大场=已确认的 BO3/5/7；大场胜率只算分出胜负的系列赛，小局胜率只算有结果的小局；同一 BO 内小局不视为独立实验。',
    });
  }

  function sequenceCard(sum) {
    const rows = sum.gameSequence.map((g) => barRow(`G${g.gameIndex}`, g.winRate,
      `${g.wins}/${g.n} 局 · ${g.at10Samples ? `10′ ${fmt.signed(g.medianAt10)}` : '无过程数据'}`,
      (g.winRate || 0) >= 50 ? 'win' : 'loss')).join('');
    return card({
      id: 'series-sequence', span: 7, kicker: '局序表现', sample: `${sum.totals.games} 小局`,
      title: sum.gameSequence.length ? `G1 到 G${sum.gameSequence[sum.gameSequence.length - 1].gameIndex} 的胜率` : '还没有可读的局序',
      lede: '同一个局序跨多场 BO 汇总；G4 以后只有 BO5/BO7 才有样本。',
      body: rows ? `<div class="xc-bars">${rows}</div>` : '<p class="xc-muted">还没有带局序的小局。</p>',
      method: '按系列赛内 gameIndex 汇总；胜率分母是该局序下有结果的小局；10 分钟差只算有过程数据的局。',
    });
  }

  function afterLossCard(sum) {
    const a = sum.afterLoss;
    return card({
      id: 'series-after-loss', span: 5, kicker: '败局后下一局', sample: `${a.n} 次`,
      title: a.n ? `输局后的下一局赢下 ${a.nextWins}/${a.n}（${pct100(a.nextWinRate)}）` : '这批 BO 没有「输局后的下一局」',
      lede: a.deltaSamples ? `下一局的 10 分钟经济差典型变化 ${fmt.signed(a.medianAt10Delta)} 金币（${a.deltaSamples} 对可比较）。` : '缺少可比较的过程数据，不比较经济差。',
      body: a.n ? `<div class="xc-risk-grid">
        <div class="xc-risk"><span>下一局胜率</span><b>${pct100(a.nextWinRate)}</b><small>${a.nextWins}/${a.n} 次</small></div>
        <div class="xc-risk"><span>10 分钟差变化</span><b>${fmt.signed(a.medianAt10Delta)}</b><small>${a.deltaSamples} 对</small></div>
      </div>` : '<p class="xc-muted">没有输局后的下一局，或结果缺失。</p>',
      note: '这是关联，不是「调整导致胜利」的因果证据。',
      method: '同一系列赛内，上一局输、下一局有结果时计一对；10 分钟差变化只算两局都有过程数据的对。',
    });
  }

  function consumptionCard(sum) {
    const rows = sum.consumption.map((c, i) => {
      const prev = sum.consumption[i - 1];
      const add = prev && num(c.avgUsedUs) && num(prev.avgUsedUs) ? c.avgUsedUs - prev.avgUsedUs : null;
      return `<div class="xc-cons-row">
        <span>G${c.gameIndex}</span>
        <div class="xc-cons-bars">
          <i class="xc-bar-track"><b class="win" style="width:${Math.min(100, (c.avgUsedUs || 0) / 15 * 100).toFixed(1)}%"></b></i>
          <i class="xc-bar-track"><b class="loss" style="width:${Math.min(100, (c.avgUsedFoe || 0) / 15 * 100).toFixed(1)}%"></b></i>
        </div>
        <span class="xc-cons-val">我 ${fmt.fixed(c.avgUsedUs, 1)} · 敌 ${fmt.fixed(c.avgUsedFoe, 1)}</span>
        <small>${num(add) ? `本局约新增 ${fmt.fixed(add, 1)} 个` : '—'}</small>
      </div>`;
    }).join('');
    return card({
      id: 'series-consumption', span: 6, kicker: '全局 BP 消耗', sample: `${sum.consumption.reduce((s, c) => s + c.n, 0)} 局`,
      title: sum.consumption.length ? `到 G${sum.consumption[sum.consumption.length - 1].gameIndex}，我方平均已用 ${fmt.fixed(sum.consumption[sum.consumption.length - 1].avgUsedUs, 1)} 个英雄` : '还没有 BP 消耗数据',
      lede: '同一 BO 内跨局累计曾选；绿=我方，红=对方。规则集不同时只作横向参照。',
      body: rows ? `<div class="xc-cons">${rows}</div><div class="xc-legend"><span><i class="win"></i>我方</span><span><i class="loss"></i>对方</span></div>` : '<p class="xc-muted">没有可读的阵容。</p>',
      method: '按系列赛内 gameIndex 取累计曾选人数；未编组/名单缺失的局不进分母；规则集以各系列赛设置为准。',
    });
  }

  function opponentCard(series) {
    const map = new Map();
    for (const s of series) {
      const name = String(s.opponent || '').trim() || '对手待补';
      const e = map.get(name) || { name, series: 0, wins: 0, losses: 0, games: 0, gameWins: 0, close: 0, last: '' };
      e.series += 1;
      const us = Number(s.score?.us) || 0, them = Number(s.score?.them) || 0;
      if (us > them) e.wins += 1; else if (them > us) e.losses += 1;
      const g = gameResults(s);
      e.games += g.length; e.gameWins += g.filter((x) => x.result === 'win').length;
      if (Math.abs(us - them) === 1 && (us || them)) e.close += 1;
      e.last = [e.last, seriesDate(s)].filter(Boolean).sort().pop() || '';
      map.set(name, e);
    }
    const items = [...map.values()].sort((a, b) => b.series - a.series);
    const rows = items.map((x) => `<tr>
      <td><b>${esc(x.name)}</b></td><td class="num">${x.series}</td><td class="num">${x.wins}/${x.losses}</td>
      <td class="num">${pct100(x.wins + x.losses ? x.wins / (x.wins + x.losses) * 100 : null)}</td>
      <td class="num">${x.gameWins}/${x.games}</td><td class="num">${x.close}</td><td class="num">${esc(x.last.slice(5) || '—')}</td>
    </tr>`).join('');
    return card({
      id: 'series-opponents', span: 6, kicker: '对手', sample: `${items.length} 个对手`,
      title: items.length ? `对 ${esc(items[0].name)} 的系列赛最多（${items[0].series} 场）` : '还没有对手样本',
      lede: '以「大场」为单位看对手：大场胜率、小局比分、打满的场次。',
      body: rows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th>对手</th><th class="num">大场</th><th class="num">胜/负</th><th class="num">大场胜率</th><th class="num">小局</th><th class="num">分差1</th><th class="num">最近</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="xc-muted">没有可比较的对手。</p>',
      method: '按对手名分组；大场胜率只算分出胜负的系列赛；小局只算有结果的小局；分差 1 局=打满或接近打满。',
    });
  }

  function attentionCard(attention) {
    const items = (attention || []).slice(0, 10);
    const body = items.length ? `<div class="xc-attns">${items.map((item) => `<div class="xc-attn">
      <div class="xc-attn-head"><b>${esc(item.title || '需要关注')}</b><span>${esc(ATTENTION_LABEL[item.kind] || '')}</span></div>
      <p>${esc(item.detail || '')}</p>
      <div class="xc-attn-links">
        ${item.seriesId ? `<a href="#biggame/${encodeURIComponent(item.seriesId)}${scopeQuery()}">大场分析 →</a>` : ''}
        ${(item.links || []).slice(0, 4).map((key) => `<a href="#match/${encodeURIComponent(key)}">局 ${esc(String(key).slice(-6))}</a>`).join('')}
      </div>
    </div>`).join('')}</div>${attention.length > items.length ? `<p class="xc-muted">还有 ${attention.length - items.length} 条，进入对应大场查看。</p>` : ''}` : '<p class="xc-muted">当前范围没有明确异常信号。样本不足时不报。</p>';
    return card({
      id: 'series-attention', span: 12, kicker: '本轮需要关注', sample: `${attention.length} 条`,
      title: items.length ? `先看这 ${items.length} 条大场信号` : '没有需要优先处理的大场信号',
      lede: '只列有明确证据的信号：连败收尾、输局后未见改善、编组待核实等。',
      body,
      method: '由 series_engine.build_attention 生成；每条都带系列赛与大场下钻入口。',
    });
  }

  function seriesListCard(series, attention) {
    const attnCount = new Map();
    for (const a of attention || []) if (a.seriesId) attnCount.set(a.seriesId, (attnCount.get(a.seriesId) || 0) + 1);
    const rows = series.map((s) => {
      const games = gameResults(s);
      const mini = games.map((g) => `<b class="xc-mini-game ${g.result === 'win' ? 'win' : 'loss'}" title="G${g.gameIndex} ${g.result === 'win' ? '胜' : '负'}${num(g.at10) ? ` · 10′ ${fmt.signed(g.at10)}` : ''}">G${g.gameIndex}</b>`).join('');
      const us = Number(s.score?.us) || 0, them = Number(s.score?.them) || 0;
      return `<tr>
        <td class="num">${esc((seriesDate(s) || '—').slice(5))}</td>
        <td><b>${esc(s.opponent || '对手待补')}</b>${s.status === 'needs_review' ? ' <span class="xc-warn">待核实</span>' : ''}</td>
        <td>BO${esc(String(s.bestOf || '—'))}${s.completionMode === 'fixed' ? ' <span class="xc-muted">固定打满</span>' : ''}${scoreValid(s) ? '' : ' <span class="xc-warn">比分异常</span>'}</td>
        <td class="num"><b class="${scoreValid(s) ? '' : 'xc-warn'}">${us}:${them}</b></td>
        <td>${esc(COMPLETION_LABEL[s.completion] || s.completion || '—')}</td>
        <td class="num">${games.length}</td>
        <td><span class="xc-mini-games">${mini || '—'}</span></td>
        <td class="num">${attnCount.get(s.id) || 0}</td>
        <td><a href="#biggame/${encodeURIComponent(s.id)}${scopeQuery()}">大场分析 →</a></td>
      </tr>`;
    }).join('');
    return card({
      id: 'series-list', span: 12, kicker: '系列赛列表', sample: `${series.length} 场`,
      title: series.length ? `${series.length} 场已确认 BO，点进任一场看逐局调整` : '当前范围没有已确认的系列赛',
      lede: '列表按开赛日倒序；G1/G2/G3 的颜色就是逐局胜负。',
      body: rows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">日期</th><th>对手</th><th>赛制</th><th class="num">比分</th><th>完赛</th><th class="num">局数</th><th>局序</th><th class="num">关注</th><th>入口</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="xc-muted">先到「系列赛编组」确认 BO 关系，跨局分析才会有单位。页面不会把未编组的局硬凑成系列赛。</p>',
      note: '「大场分析」是独立界面，不复用这里的汇总表。',
      method: '系列赛来自 training_series；比分按有结果的小局计算；未编组对局不进入本页。',
    });
  }

  function listHtml() {
    if (state.error) return `<div class="page xc-page"><section class="xc-blank"><h1>读不到大场</h1><p>${esc(state.error)}</p><button type="button" class="xc-btn" data-cx-retry>重试</button></section></div>`;
    if (!state.allSeries.length) {
      return `<div class="page xc-page">${scopeBarHtml()}<section class="xc-blank"><h1>还没有已确认的大场</h1><p>大场分析以已确认的 BO3/5/7 为单位；先到系列赛编组确认 BO 关系。</p><a class="xc-btn primary" href="#series-builder">去系列赛编组 →</a></section></div>`;
    }
    const series = filteredSeries();
    if (!series.length) {
      return `<div class="page xc-page">${scopeBarHtml()}<section class="xc-blank"><h1>当前范围没有大场</h1><p>放宽时间或清除赛制/对手/状态筛选。</p><button type="button" class="xc-btn primary" data-cx-clear>清除筛选</button></section></div>`;
    }
    const sum = deriveSummary(series);
    const ids = new Set(series.map((s) => s.id));
    const attention = (state.attention || []).filter((a) => ids.has(a.seriesId));
    const attnCount = new Map();
    for (const a of attention) if (a.seriesId) attnCount.set(a.seriesId, (attnCount.get(a.seriesId) || 0) + 1);
    const cards = series.map((s) => bigCard(s, attnCount.get(s.id) || 0)).join('');
    return `<div class="page xc-page xc-bg-page">
      ${headHtml(sum, series)}
      ${scopeBarHtml()}
      <div class="xc-bg-grid">${cards}</div>
      <p class="xc-source"><b>大场</b> 已确认的 BO3/5/7；比分异常或编组待核实的场次已标出。点任一场进入单场分析。</p>
    </div>`;
  }

  function bigCard(s, attnCount) {
    const games = gameResults(s);
    const us = Number(s.score?.us) || 0, them = Number(s.score?.them) || 0;
    const valid = scoreValid(s);
    const mini = games.map((g) => `<b class="xc-mini-game ${g.result === 'win' ? 'win' : 'loss'}" title="G${g.gameIndex} ${g.result === 'win' ? '胜' : '负'}${num(g.at10) ? ` · 10′ ${fmt.signed(g.at10)}` : ''}">G${g.gameIndex}</b>`).join('');
    return `<a class="xc-bigcard ${valid ? '' : 'is-warn'}" href="#biggame/${encodeURIComponent(s.id)}${scopeQuery()}">
      <div class="xc-bigcard-top"><span>${esc((seriesDate(s) || '—').slice(5))}</span><span>BO${esc(String(s.bestOf || '—'))}${s.completionMode === 'fixed' ? ' · 固定打满' : ''}</span></div>
      <h3>${esc(s.opponent || '对手待补')}</h3>
      <div class="xc-bigcard-score"><b class="${us > them ? 'win' : them > us ? 'loss' : ''}">${us}:${them}</b><span>${esc(COMPLETION_LABEL[s.completion] || s.completion || '—')}</span></div>
      <div class="xc-mini-games">${mini || '—'}</div>
      <div class="xc-bigcard-foot">
        <span>${valid ? '' : '<b class="xc-warn">比分异常</b>'}${s.status === 'needs_review' ? ' <b class="xc-warn">待核实</b>' : ''}${attnCount ? ` <b class="xc-warn">${attnCount} 条关注</b>` : ''}</span>
        <b>进入大场分析 →</b>
      </div>
    </a>`;
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

  function gameVisual(games) {
    return `<div class="xc-game-list">${games.map((g) => `<a class="xc-game-row" href="#match/${encodeURIComponent(g.matchKey)}">
      <b class="xc-game-no">G${g.gameIndex}</b>
      <span class="xc-game-res ${g.result === 'win' ? 'win' : 'loss'}">${g.result === 'win' ? '胜' : g.result === 'loss' ? '负' : '—'}</span>
      <span class="xc-game-metric">${fmt.duration(g.duration)}</span>
      <span class="xc-game-metric"><small>10′</small>${fmt.signed(g.at10)}</span>
      <span class="xc-game-metric"><small>终局</small>${fmt.signed(g.finalDiff)}</span>
      <span class="xc-game-comp">${esc(g.compOwn || '—')}<i>vs</i>${esc(g.compFoe || '—')}</span>
      <span class="xc-game-adj">${esc(g.adjustment?.changeLabel || '—')}</span>
      <em>→</em>
    </a>`).join('')}</div>`;
  }

  function swapsVisual(transitions, responses) {
    if (!transitions.length) return '<p class="xc-muted">只有一局，或缺少阵容。</p>';
    const rows = transitions.map((g) => {
      const adj = g.adjustment || {};
      const resp = (responses || []).find((item) => Number(item.gameIndex) === Number(g.gameIndex)) || {};
      const groups = [
        ['我方新增', adj.newOwn, 'is-in'],
        ['我方移出', adj.droppedOwn, 'is-out'],
        ['对方新增', resp.newFoe, 'is-in'],
        ['对方移出', resp.droppedFoe, 'is-out'],
      ];
      const changed = groups.some(([, list]) => (list || []).length);
      const groupHtml = groups.map(([label, list, cls]) => `<div class="si-swap-group"><small>${label}</small><div class="si-swap-chips">${(list || []).length
        ? list.map((name) => `<span class="si-swap-chip ${cls}">${esc(name)}</span>`).join('')
        : '<span class="si-swap-empty">无</span>'}</div></div>`).join('');
      const notes = [];
      if (adj.compChanged) notes.push('我方体系标签变化');
      if (resp.compChanged) notes.push('对方体系标签变化');
      if ((resp.banRepeat || []).length) notes.push(`对手重复 ban：${resp.banRepeat.join('、')}`);
      if (!changed && !notes.length) notes.push('没有观察到明显的体系/ban 调整');
      return `<div class="si-swap">
        <div class="si-swap-head"><b>G${g.gameIndex - 1} → G${g.gameIndex}</b><span>${esc(adj.changeLabel || '对照缺失')}</span></div>
        ${changed ? `<div class="si-swap-grid">${groupHtml}</div>` : '<p class="si-swap-note">双方阵容没有变化。</p>'}
        ${notes.length ? `<p class="si-swap-note">${esc(notes.join('；'))}。</p>` : ''}
      </div>`;
    }).join('');
    return `<div class="si-swaps">${rows}</div>`;
  }

  function bpVisual(games, perGame) {
    const rows = games.map((g) => {
      const bp = (perGame || []).find((x) => Number(x.gameIndex) === Number(g.gameIndex)) || {};
      const usedUs = Number(bp.usedUsCount) || 0;
      const usedFoe = Number(bp.usedFoeCount) || 0;
      const max = Math.max(10, usedUs, usedFoe);
      const newOwn = (g.adjustment || {}).newOwn || [];
      const locked = (bp.blockUs || []).length;
      return `<div class="si-ledger-row">
        <b>G${g.gameIndex}</b>
        <div class="si-ledger-bars">
          <i><b style="width:${(usedUs / max * 100).toFixed(1)}%"></b></i>
          <i class="is-foe"><b style="width:${(usedFoe / max * 100).toFixed(1)}%"></b></i>
        </div>
        <span class="si-ledger-count">我 ${fmt.count(usedUs)} · 敌 ${fmt.count(usedFoe)}</span>
        <div class="si-ledger-new">${newOwn.length
          ? newOwn.map((name) => `<span class="si-swap-chip is-in">${esc(name)}</span>`).join('')
          : '<span class="si-swap-empty">无新增</span>'}${locked ? `<span class="si-ledger-foot">本局后我方已锁 ${fmt.count(locked)}</span>` : ''}</div>
      </div>`;
    }).join('');
    return `<div class="si-ledger">${rows}</div>
      <p class="si-ledger-foot">两行＝每局累计曾选；chip＝本局新增。</p>`;
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
    if (state.detailError) return `<div class="page xc-page"><a class="xc-back" href="#biggame${scopeQuery()}">← 返回大场列表</a><section class="xc-blank"><h1>读不到这场大场</h1><p>${esc(state.detailError)}</p></section></div>`;
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
    const back = `#biggame${scopeQuery()}`;
    const transitions = games.filter((g) => g.gameIndex > 1);
    const adjustments = swapsVisual(transitions, data.opponentResponse || []);
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
    const insight = data.insight || null;
    const si = renderInsightCards(data, { card, esc, fmt, num, pct100, scopeQuery });
    const conclusionCard = si.flow ? '' : `<article class="xc-card xc-span-12">
      <div class="xc-card-head"><span class="xc-kicker">系列赛结论</span><span class="xc-badge">${games.length} 局</span></div>
      <h3 class="xc-card-title">${esc(verdict)}</h3>
      ${miniGames(games)}
      ${detailChart(games)}
      <p class="xc-card-note">点任意一局进入单局复盘；线是 10 分钟经济差与终局经济差，本队减对手。</p>
    </article>`;
    const afterLossCard = (data.afterLoss?.n || data.compSwitch?.pairs) ? card({ id: 'detail-afterloss', span: 12, kicker: '败局恢复', sample: `${(data.afterLoss?.pairs || []).length} 对`, title: data.afterLoss?.n ? `下一局赢 ${data.afterLoss.nextWins}/${data.afterLoss.n}（${pct100(data.afterLoss.nextWinRate)}）` : '没有输局后的下一局', lede: data.afterLoss?.deltaSamples ? `下一局 10 分钟差典型变化 ${fmt.signed(data.afterLoss.medianAt10Delta)}（${data.afterLoss.deltaSamples} 对）` : '缺过程数据，不比较经济差。', body: `<div class="si-afterloss-body">${afterPairs || '<p class="xc-muted">没有可对照的连败过渡。</p>'}${data.compSwitch?.pairs ? `<div class="xc-risk-grid"><div class="xc-risk"><span>体系延续后</span><b>${pct100(data.compSwitch.continued?.winRate)}</b><small>${data.compSwitch.continued?.nextWins || 0}/${data.compSwitch.continued?.n || 0} 次</small></div><div class="xc-risk"><span>体系切换后</span><b>${pct100(data.compSwitch.switched?.winRate)}</b><small>${data.compSwitch.switched?.nextWins || 0}/${data.compSwitch.switched?.n || 0} 次</small></div></div>` : ''}</div>`, note: '调整与下一局胜负是关联，不是因果。' }) : '';
    const corpusBadge = insight?.available && insight?.sample?.corpusGames
      ? `<span class="xc-cov"><b>${fmt.count(insight.sample.corpusGames)}</b> 历史语料</span>` : '';
    return `<div class="page xc-page xc-series-detail">
      <a class="xc-back" href="${back}">← 返回大场列表</a>
      <header class="xc-head xc-hero xc-detail-head">
        <div class="xc-head-main">
          <p class="xc-eyebrow">大场分析 <i>/</i> BO${esc(String(series.bestOf || '—'))} <i>/</i> ${esc(String(series.startAt || games[0]?.date || '—'))} <i>/</i> ${esc(COMPLETION_LABEL[series.completion] || series.completion || '—')}</p>
          <h1 class="xc-title">${scoreValid(series) ? `${us}:${them} ${resultWord}` : `比分 ${us}:${them} 待核实`} ${esc(series.opponent || '对手待补')} <span class="xc-title-ci">${esc(rule)}</span></h1>
          <p class="xc-sub">${games.length} 局 · ${durations.length ? `平均 ${fmt.duration(fmt.mean(durations))}` : '缺时长'} · ${at10s.length ? `10 分钟差 ${fmt.signed(fmt.median(at10s))}` : '缺 10 分钟过程'} · ${series.completionMode === 'fixed' ? '固定打满' : '标准决胜'} · ${scoreValid(series) ? '' : '比分与赛制不一致 · '}${series.status === 'needs_review' ? '编组待核实' : '编组已确认'}</p>
          <div class="xc-coverage"><span class="xc-cov"><b>${fmt.count(games.length)}</b> 小局</span><span class="xc-cov"><b>${fmt.count(coverage.withVector || 0)}</b> 有向量</span><span class="xc-cov"><b>${fmt.count(coverage.orderKnownGames || 0)}</b> 有手序</span><span class="xc-cov"><b>${fmt.count(coverage.at10Games || 0)}</b> 有 10 分钟</span>${corpusBadge}</div>
        </div>
        <div class="xc-head-actions xc-head-side">${miniGames(games)}<a class="xc-btn" href="#series-builder">去编组中心 →</a></div>
      </header>
      <div class="xc-cards">
        ${si.digest || ''}
        ${conclusionCard}
        ${si.flow || ''}
        ${si.phase || ''}
        ${si.shape || ''}
        ${si.players || ''}
        ${card({ id: 'detail-games', span: 12, kicker: '逐局对比', sample: `${games.length} 局`, title: '每一局的结果、经济差与阵容', lede: '调整按终局阵容口径；没有 BP 手序时，不推断先后手针对。', body: gameVisual(games), note: data.afterLoss?.n ? '' : '本场没有「输局后的下一局」可对照。' })}
        ${si.draft || ''}
        ${card({ id: 'detail-adjust', span: 7, kicker: '调整与对手回应', sample: `${transitions.length} 次过渡`, title: transitions.length ? '每一局之间改了什么' : '没有可对照的连续局', lede: '我方新增/移出、对方新增/移出与重复 ban；终局阵容口径。', body: adjustments, method: '相邻两局对比终局阵容；有手序才谈「针对顺序」，这里不做先后手推断。' })}
        ${card({ id: 'detail-ledger', span: 5, kicker: '全局 BP 消耗', sample: `${ledgerRows ? games.length : 0} 局`, title: esc(rule), lede: '每局累计曾选与我方不可再选；跨局复用按规则集检查。', body: bpVisual(games, data.bpLedger?.perGame || []) + `<p class="xc-card-note">${esc(series.ruleset?.note || '')}</p>`, method: '累计曾选按系列赛推进；规则集以本场设置为准；检测到复用会写在覆盖说明里。' })}
        ${afterLossCard}
        ${si.similar || ''}
      </div>
      ${si.methods || card({ id: 'detail-coverage', span: 12, kicker: '覆盖与口径', sample: `${coverage.games || games.length} 局`, title: '这场大场能回答什么、不能回答什么', lede: `向量 ${coverage.withVector || 0} 局 · 明细 ${coverage.withDetail || 0} 局 · 手序 ${coverage.orderKnownGames || 0} 局 · 过程 ${coverage.processKnownGames || 0} 局 · 10 分钟 ${coverage.at10Games || 0} 局`, body: (caveats || !scoreValid(series)) ? `<ul class="xc-caveats-list">${scoreValid(series) ? '' : `<li>比分 ${us}:${them} 与 BO${series.bestOf || '—'} 赛制不一致：先核实编组、赛制或规则集，本页不据此下大场结论。</li>`}${caveats}</ul>` : '<p class="xc-muted">没有额外口径警示。</p>' })}
      <p class="xc-source"><b>数据</b> 系列赛编组 + 各局向量/明细；大场结论只在这组 BO 内成立，不跨系列赛外推。</p>
    </div>`;
  }

  /* ── 渲染与事件 ───────────────────────────────────────────── */
  function paint(html) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = html;
  }

  function paintLoading(text) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = `<div class="page xc-page"><div class="loading">${esc(text)}</div></div>`;
  }

  function ensure(force = false) {
    if (!isCrossRoute()) return;
    readScope();
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
