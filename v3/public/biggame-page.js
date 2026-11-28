/* 大场分析（2026-11 重做）
 *
 * 单位是「大场」：列表页把已确认的 BO3/5/7 排成卡片；点进去是单场页。
 * 单场页只留教练会用的六块：信息卡、大场走势、阶段与资源、选手状态、
 * BP 判断、历史相似阵容。挖掘结论/局面形态/逐局对比/调整回应/BP 消耗/
 * 败局恢复/方法与口径都不再出现。
 *
 * 统计口径与 caveat 由 series_engine / series_insight 提供；本文件只做
 * 筛选、排版和交互，不在前端重算结论。
 */

import { fmt } from './cross-analytics.js';
import {
  gameWord, renderPhase, renderBp, renderBoHabit, renderOverview, renderCompSystem,
} from './biggame-insight.js?v=20261126coach2';
import { glyph } from './ui-icons.js';

const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

/* 赛事域（M1）：大场页自带取数，统一在这里补当前赛事参数。 */
const currentCompetitionId = () => {
  try { return localStorage.getItem('training-current-competition') || ''; } catch { return ''; }
};
const scopedSeriesUrl = (path) => {
  const competition = currentCompetitionId();
  if (!competition) return path;
  return `${path}${path.includes('?') ? '&' : '?'}competition=${encodeURIComponent(competition)}`;
};

const RANGE_OPTIONS = [['all', '全部时间'], ['7', '近 7 天'], ['30', '近 30 天'], ['custom', '自定义']];
const BO_OPTIONS = [['', '全部赛制'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']];
const STATUS_OPTIONS = [['', '全部状态'], ['confirmed', '已确认'], ['needs_review', '待核实']];
const COMPLETION_OPTIONS = [['', '全部完赛状态'], ['completed', '已完赛'], ['open', '未完赛'],
  ['interrupted', '中断'], ['incomplete', '采集不完整']];
const STATUS_LABEL = { confirmed: '已确认', needs_review: '待核实' };
const COMPLETION_LABEL = { completed: '已完赛', open: '未完赛', interrupted: '中断', incomplete: '采集不完整' };
/* 单字符对手名（如占位 "D"）当队名渲染会像评级字母，统一回落到待补。 */
const opponentLabel = (value) => {
  const name = String(value || '').trim();
  return name.length <= 1 ? '对手待补' : name;
};
const DEFAULT_RANGE = 'all';

const num = (v) => typeof v === 'number' && Number.isFinite(v);
const pct100 = (v) => (num(v) ? `${Math.round(v)}%` : '—');
const pct1 = (v) => (num(v) ? `${Number(v).toFixed(1)}%` : '—');
const signed = (v, digits = 0) => (num(v) ? fmt.signed(v, digits) : '—');
const fixed = (v, digits = 1) => (num(v) ? fmt.fixed(v, digits) : '—');
const count = (v) => (num(v) ? fmt.count(v) : '—');
const dur = (v) => (num(v) && v > 0 ? fmt.duration(v) : '—');
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
const mean = (list) => {
  const values = (list || []).filter(num);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
};

export function createBigGamePage(h) {
  const { esc, fmt: format } = h;
  let generation = 0;
  let controller = null;
  /* 复制等操作的反馈同时读给屏幕阅读器，失败不能冒充成功。 */
  let liveNode = null;
  const announce = (message) => {
    if (!liveNode || !liveNode.isConnected) {
      liveNode = document.createElement('div');
      liveNode.setAttribute('role', 'status');
      liveNode.setAttribute('aria-live', 'polite');
      liveNode.style.cssText = 'position:fixed;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap';
      document.body.append(liveNode);
    }
    liveNode.textContent = message;
  };
  const state = {
    allSeries: [], attention: [], rulesets: [], latestDate: '',
    navSeries: [], navLoaded: false,
    loaded: false, loading: false, error: '',
    detailId: '', detail: null, detailLoading: false, detailError: '',
    comboPool: undefined, rulesCounters: undefined, rulesCombos: undefined,
  };
  const scope = { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '', session: '', status: '', completion: '' };
  /* 单场页的视图状态：切局次/阶段/对比窗口都只重绘，不重新取数。 */
  const ui = {
    phase: 'mid', window: 'd30',
    boWindow: '90', boScope: 'opp', boSlot: 1, baseMode: 'format', module: 'overview',
    boIncludeOtherEvents: false,
    bpGame: '', bpOpen: {}, metricGroup: 'all', overviewView: 'games', poolOutcomeScope: 'all',
    /* BO 习惯楼层板：当前局次、双方已选 Ban、选中的楼层、折叠展开状态。 */
    boBoard: { game: 0, bans: { blue: [], red: [] }, pick: null, open: {} },
  };

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
    /* 赛事域：URL 带 event= 时切换当前赛事（分享链接直达某个分析域）。 */
    const event = params.get('event');
    if (event) {
      try { localStorage.setItem('training-current-competition', event); } catch {}
    }
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
    const event = currentCompetitionId();
    if (event) params.set('event', event);
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
      ? `${scope.from || '起'} ~ ${scope.to || '今'}` : range];
    if (scope.bo) bits.push(`BO${scope.bo}`);
    if (scope.opponent) bits.push(scope.opponent);
    if (scope.session) bits.push(scope.session);
    if (scope.status) bits.push(STATUS_LABEL[scope.status] || scope.status);
    if (scope.completion) bits.push(COMPLETION_LABEL[scope.completion] || scope.completion);
    return bits.filter(Boolean).join(' · ');
  }

  function filteredSeries() {
    const [from, to] = scopeBounds();
    return state.allSeries.filter((s) => {
      const day = seriesDate(s);
      if (from && day && day < from) return false;
      if (to && day && day > to) return false;
      if (scope.bo && String(s.bestOf) !== scope.bo) return false;
      if (scope.opponent && String(s.opponent || '') !== scope.opponent) return false;
      if (scope.session && String(s.session || '') !== scope.session) return false;
      if (scope.status && String(s.status || '') !== scope.status) return false;
      if (scope.completion && String(s.completion || '') !== scope.completion) return false;
      return true;
    });
  }

  function uniq(key) {
    return [...new Set(state.allSeries.map((s) => String(s[key] || '').trim()).filter(Boolean))]
      .sort((a, b) => String(a).localeCompare(String(b), 'zh-CN'));
  }

  function deriveSummary(series) {
    const totals = { series: series.length, completed: 0, seriesWins: 0, seriesLosses: 0, games: 0, gameWins: 0 };
    let close = 0; let sweep = 0; let missing = 0; let fixedMode = 0; let invalid = 0; let totalGames = 0;
    const scoreDist = new Map();
    for (const s of series) {
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      if (us > them) totals.seriesWins += 1; else if (them > us) totals.seriesLosses += 1;
      if (s.completion === 'completed') totals.completed += 1;
      if (String(s.completionMode || '') === 'fixed') fixedMode += 1;
      if (!scoreValid(s)) invalid += 1;
      const games = gameResults(s);
      totals.games += games.length;
      totals.gameWins += games.filter((g) => g.result === 'win').length;
      totalGames += Number(s.bestOf) || 0;
      const key = `${us}:${them}`;
      scoreDist.set(key, (scoreDist.get(key) || 0) + 1);
      if (Math.abs(us - them) === 1 && (us || them)) close += 1;
      if ((us === 0 || them === 0) && (us || them)) sweep += 1;
      missing += (s.coverage?.missingGames || []).length;
    }
    const seriesDecided = totals.seriesWins + totals.seriesLosses;
    return {
      totals: {
        ...totals,
        seriesWinRate: seriesDecided ? totals.seriesWins / seriesDecided * 100 : null,
        gameWinRate: totals.games ? totals.gameWins / totals.games * 100 : null,
        avgGames: series.length ? totals.games / series.length : null,
      },
      scoreDist: [...scoreDist.entries()].map(([label, n]) => ({ label, n }))
        .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label)),
      close, sweep, missing, fixed: fixedMode, invalid,
    };
  }

  /* ── 取数 ─────────────────────────────────────────────────── */
  async function loadAll() {
    const gen = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.loading = true;
    state.error = '';
    paintLoading('正在汇总大场…');
    try {
      const response = await fetch(scopedSeriesUrl(`${API_BASE}/api/cross/series-summary`), { signal: controller.signal, cache: 'no-store' });
      if (gen !== generation) return;
      if (!response.ok) throw new Error(`系列赛汇总 ${response.status}`);
      const payload = await response.json();
      state.allSeries = payload.series || [];
      state.attention = payload.summary?.attention || [];
      state.rulesets = payload.rulesets || [];
      state.latestDate = state.allSeries.map(seriesDate).filter(Boolean).sort().pop() || '';
      state.loaded = true;
    } catch (error) {
      if (gen !== generation) return;
      state.error = String((error && error.message) || error);
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
    state.comboPool = undefined;
    state.rulesCounters = undefined;
    state.rulesCombos = undefined;
    ui.bpGame = '';
    ui.bpOpen = {};
    ui.boSlot = 1;
    paintLoading('正在读取大场明细…');
    try {
      const analysisBase = scopedSeriesUrl(`${API_BASE}/api/series/${encodeURIComponent(id)}/analysis`);
      const analysisUrl = ui.boIncludeOtherEvents
        ? `${analysisBase}${analysisBase.includes('?') ? '&' : '?'}includeOtherEvents=1`
        : analysisBase;
      const [response, poolResponse, counterResponse, comboRuleResponse] = await Promise.all([
        fetch(analysisUrl, {
          signal: controller.signal, cache: 'no-store',
        }),
        fetch(`${API_BASE}/api/v3/custom-combos`, {
          signal: controller.signal, cache: 'no-store',
        }).catch(() => null),
        fetch(scopedSeriesUrl(`${API_BASE}/api/v3/rules-center/counters`), {
          signal: controller.signal, cache: 'no-store',
        }).catch(() => null),
        fetch(scopedSeriesUrl(`${API_BASE}/api/v3/rules-center/combos`), {
          signal: controller.signal, cache: 'no-store',
        }).catch(() => null),
      ]);
      if (gen !== generation) return;
      if (!response.ok) throw new Error(`大场明细 ${response.status}`);
      state.detail = await response.json();
      state.comboPool = poolResponse?.ok ? await poolResponse.json().catch(() => null) : null;
      state.rulesCounters = counterResponse?.ok ? await counterResponse.json().catch(() => null) : null;
      state.rulesCombos = comboRuleResponse?.ok ? await comboRuleResponse.json().catch(() => null) : null;
    } catch (error) {
      if (gen !== generation) return;
      state.detailError = String((error && error.message) || error);
    }
    state.detailLoading = false;
    if (isCrossRoute() && detailIdOf() === id) {
      paint(detailHtml());
      requestAnimationFrame(updateBpSubnav);
    }
    if (state.detail && !state.navLoaded) loadNavSeries();
  }

  async function loadNavSeries() {
    if (state.navLoaded) return;
    state.navLoaded = true;
    try {
      const response = await fetch(scopedSeriesUrl(`${API_BASE}/api/series`), { cache: 'no-store' });
      if (!response.ok) throw new Error(`系列赛 ${response.status}`);
      const payload = await response.json();
      state.navSeries = (payload.series || []).slice().sort((a, b) =>
        String(b.startAt || '').localeCompare(String(a.startAt || '')));
      if (isCrossRoute() && detailIdOf() && state.detail) repaintDetail();
    } catch {
      state.navLoaded = false;
    }
  }

  function navNeighbors(id) {
    const list = state.navSeries || [];
    const index = list.findIndex((item) => String(item.id) === String(id));
    if (index < 0) return { prev: null, next: null };
    return { prev: list[index - 1] || null, next: list[index + 1] || null };
  }

  /* ── 列表页 ───────────────────────────────────────────────── */
  function scopeBarHtml() {
    const seg = (list, current, attr) => `<div class="bgx-seg" role="group">${list.map(([key, label]) =>
      `<button type="button" class="bgx-seg-btn" ${attr}="${key}" aria-pressed="${String(current) === key}">${esc(label)}</button>`).join('')}</div>`;
    const select = (key, label, list, value, emptyLabel) => {
      const options = list.map((item) => {
        const name = Array.isArray(item) ? item[1] : item;
        const val = Array.isArray(item) ? item[0] : item;
        return `<option value="${esc(val)}"${val === value ? ' selected' : ''}>${esc(name)}</option>`;
      }).join('');
      return `<label class="bgx-field"><span>${esc(label)}</span><select class="bgx-select" data-cx="${key}">
        <option value="">${esc(emptyLabel)}</option>${options}</select></label>`;
    };
    return `<div class="bgx-scope">
      <label class="bgx-field"><span>时间</span></label>${seg(RANGE_OPTIONS, scope.range, 'data-cx-range')}
      ${scope.range === 'custom' ? `<span class="bgx-field"><input type="date" class="bgx-select" data-cx-date="from" value="${esc(scope.from)}" aria-label="开始日期"><i class="bgx-quiet">→</i><input type="date" class="bgx-select" data-cx-date="to" value="${esc(scope.to)}" aria-label="结束日期"></span>` : ''}
      <span class="bgx-quiet" style="inline-size:1px;block-size:18px;background:var(--bgx-line)"></span>
      <label class="bgx-field"><span>赛制</span></label>${seg(BO_OPTIONS, scope.bo, 'data-cx-bo')}
      ${select('opponent', '对手', uniq('opponent'), scope.opponent, '全部对手')}
      ${select('status', '状态', STATUS_OPTIONS, scope.status, '全部状态')}
      ${select('completion', '完赛', COMPLETION_OPTIONS, scope.completion, '全部完赛状态')}
      ${scopeActive() ? `<button type="button" class="bgx-btn control" data-cx-clear>${glyph('refresh', { label: '清除筛选', size: 18 })} 清除筛选</button>` : ''}
      <span class="bgx-scope-meta">当前范围 <b>${esc(scopeLabel())}</b> · 按大场统计</span>
    </div>`;
  }

  function scoreHtml(us, them, outcome = '', prefix = 'bgx-score') {
    return `<span class="${prefix} ${outcome}" aria-label="本队 ${us} 比 ${them} 对手"><b>${us}</b><i>:</i><b>${them}</b></span>`;
  }

  function teamCard(s) {
    const games = gameResults(s);
    const us = Number(s.score?.us) || 0;
    const them = Number(s.score?.them) || 0;
    const valid = scoreValid(s);
    const oppRaw = String(s.opponent || '').trim();
    const oppTbd = oppRaw.length <= 1;
    const opp = opponentLabel(oppRaw);
    /* 队名始终显示：卡片的主角是「跟谁打」，占位文案要弱化为标签，不当大标题。 */
    const oppName = esc(opp);
    const oppClass = oppTbd ? ' is-tbd' : '';
    const outcome = us > them ? 'is-win' : them > us ? 'is-loss' : '';
    /* 结论先于过程被读到：和单场页用同一套判词，不另造一套说法。 */
    const verdict = verdictText(s, games, { us, them });
    return `<a class="bgx-team-card ${outcome}" href="#biggame/${encodeURIComponent(s.id)}${scopeQuery()}">
      <div class="bgx-team-top">
        <span>${esc((seriesDate(s) || '—').slice(5))} · BO${esc(String(s.bestOf || '—'))}${s.completionMode === 'fixed' ? ' · 固定打满' : ''}</span>
        <span class="bgx-status bgx-status--${esc(s.completion || 'open')}${s.completion === 'completed' ? ' is-done' : ''}">${esc(COMPLETION_LABEL[s.completion] || s.completion || '—')}${s.status === 'needs_review' ? ' · 待核实' : ''}</span>
      </div>
      <div class="bgx-scoreline">
        <b class="bgx-side-name${oppClass}">${oppName}</b>
        ${scoreHtml(us, them, outcome)}
        <span class="bgx-outcome ${outcome}">${us > them ? '战胜' : them > us ? '不敌' : '对阵'}${valid ? '' : ' · 比分异常'}</span>
      </div>
      <p class="bgx-verdict-line">${esc(verdict)}</p>
      <div class="bgx-team-foot bgx-team-foot--primary">
        <b>${glyph('matches', { label: '进入大场', size: 18 })} ${s.completion === 'completed' ? `已完赛 ${us}:${them} · 查看复盘` : '进入大场'}</b>
      </div>
    </a>`;
  }

  function listHtml() {
    if (state.error) {
      return `<div class="page bgx-page"><section class="bgx-empty">${glyph('warning', { label: '读取失败', size: 28 })}<h2>读不到大场</h2><p>${esc(state.error)}</p><button type="button" class="bgx-btn control" data-cx-retry>${glyph('refresh', { label: '重试', size: 18 })} 重试</button></section></div>`;
    }
    if (!state.allSeries.length) {
      return `<div class="page bgx-page"><section class="bgx-empty">${glyph('bp', { label: '系列赛编组', size: 28 })}<h1>还没有已确认的大场</h1><p>先到系列赛编组确认 BO3/5/7 关系。</p><a class="bgx-btn is-primary control" href="#series-builder">${glyph('bp', { label: '去编组', size: 18 })} 去系列赛编组</a></section></div>`;
    }
    const series = filteredSeries();
    if (!series.length) {
      return `<div class="page bgx-page">${scopeBarHtml()}<section class="bgx-empty">${glyph('refresh', { label: '清除筛选', size: 28 })}<h2>当前范围没有大场</h2><button type="button" class="bgx-btn is-primary control" data-cx-clear>${glyph('refresh', { label: '清除筛选', size: 18 })} 清除筛选</button></section></div>`;
    }
    const sum = deriveSummary(series);
    const t = sum.totals;
    const cards = series.map((s) => teamCard(s)).join('');
    return `<div class="page bgx-page">
      <header class="bgx-list-head">
        <div>
          <h1>${esc(String(t.series))} 场已确认的大场，<em><span class="du-win">${t.seriesWins} 胜</span> <span class="du-loss">${t.seriesLosses} 负</span></em></h1>
        </div>
        <div class="bgx-list-kpis">
          <div class="bgx-list-kpi"><span>大场胜率</span><b>${pct100(t.seriesWinRate)}</b></div>
          <div class="bgx-list-kpi"><span>小局胜率</span><b>${pct100(t.gameWinRate)}</b></div>
          <div class="bgx-list-kpi"><span>待核实</span><b>${series.filter((s) => s.status === 'needs_review').length}<i> 场</i></b></div>
        </div>
      </header>
      ${scopeBarHtml()}
      <div class="bgx-grid">${cards}</div>
    </div>`;
  }

  /* ── 单场页 ───────────────────────────────────────────────── */
  function verdictText(series, games, score) {
    const us = Number(score?.us) || 0;
    const them = Number(score?.them) || 0;
    const bestOf = Number(series.bestOf) || games.length;
    const results = games.map((g) => g.result).filter((r) => r === 'win' || r === 'loss');
    const full = games.length >= bestOf;
    if (!scoreValid(series)) return `比分 ${us}:${them} 与 BO${bestOf} 赛制不一致，先核实编组或规则集，再谈逆转或零封。`;
    const decided = us >= Math.ceil(bestOf / 2) || them >= Math.ceil(bestOf / 2);
    if (!decided && series.completion !== 'completed') {
      return `系列赛进行中：目前 ${us}:${them}，已记录 ${games.length} 局。`;
    }
    if (decided) {
      // 已经分出胜负：按标准 BO 读，别说「固定打满」。
      if (us > them) {
        if (them === 0) return `直落 ${us} 局拿下，没有给对手任何一局。`;
        if (results[0] === 'loss') return `先丢一局，随后连扳 ${us} 局完成逆转。`;
        return `以大场 ${us}:${them} 拿下。`;
      }
      if (us === 0) return `被直落 ${them} 局，没有拿到一局。`;
      if (results[0] === 'win') return `先赢一局，随后被连扳 ${them} 局。`;
      return `以大场 ${us}:${them} 落败。`;
    }
    if (series.completionMode === 'fixed') return `打满 ${games.length} 局，${us} 胜 ${them} 负。`;
    if (us > them) {
      if (them === 0) return `直落 ${us} 局拿下，没有给对手任何一局。`;
      if (results[0] === 'loss') return `先丢${them ? '一局' : ''}，随后连扳 ${us} 局完成逆转${full ? '，打满全局数' : ''}。`;
      return `以大场 ${us}:${them} 拿下${full ? '，打满全局数' : ''}。`;
    }
    if (them > us) {
      if (us === 0) return `被直落 ${them} 局，没有拿到一局。`;
      if (results[0] === 'win') return `先赢一局，随后被连扳 ${them} 局。`;
      return `以大场 ${us}:${them} 落败${full ? '，打满全局数' : ''}。`;
    }
    return '系列赛未分胜负，先确认比分或采集完整性。';
  }

  function heroHtml(data, games, score, insight) {
    const series = data.series || {};
    const us = Number(score?.us) || 0;
    const them = Number(score?.them) || 0;
    const valid = scoreValid(series);
    const durations = games.map((g) => g.duration).filter(num);
    const at10s = games.map((g) => g.at10).filter(num);
    const med10 = at10s.length ? fmt.median(at10s) : null;
    const leads = games.filter((g) => num(g.at10) && g.at10 > 0);
    const rule = series.ruleset?.name || series.rulesetId || '规则集未设置';
    const duplicates = (insight?.quality?.duplicates || []);
    const dupText = duplicates.length
      ? `过程数据里发现 ${duplicates.length} 组完全相同的局（${duplicates.slice(0, 2).map((g) => g.gameIndexes.map((i) => `第${'一二三四五六七'[i - 1] || i}把`).join('/')).join('、')}），先核实采集或编组。`
      : '';
    const tags = [
      `BO${series.bestOf || '—'}`,
      String(series.startAt || games[0]?.date || '').slice(0, 10),
      COMPLETION_LABEL[series.completion] || series.completion || '—',
      rule,
      series.status === 'needs_review' ? '编组待核实' : '编组已确认',
    ].filter(Boolean);
    const kpi = (label, value, sub) => `<div class="bgx-hero-kpi"><span>${esc(label)}</span><b>${value}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</div>`;
    return `<header class="bgx-hero">
      <div class="bgx-hero-main">
        <p class="bgx-eyebrow">大场分析 <i>/</i> 大场 <i>/</i> ${esc(String(series.bestOf ? `BO${series.bestOf}` : '赛制未设置'))}</p>
        <div class="bgx-hero-score">
          ${scoreHtml(us, them, us > them ? 'is-win' : them > us ? 'is-loss' : '', 'bgx-hero-digits')}
          <span class="bgx-hero-outcome"><span>${us > them ? '战胜' : them > us ? '不敌' : '对阵'}</span><b>${esc(opponentLabel(series.opponent))}</b></span>
        </div>
        <p class="bgx-hero-verdict">${valid ? esc(verdictText(series, games, score)) : `<b class="bgx-warn">比分异常：</b>${esc(verdictText(series, games, score))}`}</p>
        <div class="bgx-hero-tags">${tags.map((tag) => `<span class="bgx-chip">${esc(tag)}</span>`).join('')}</div>
      </div>
      <div class="bgx-hero-side">
        ${kpi('小局', count(games.length), `${games.filter((g) => g.result === 'win').length} 胜 ${games.filter((g) => g.result === 'loss').length} 负`)}
        ${kpi('场均时长', durations.length ? dur(mean(durations)) : '—', durations.length ? `${durations.length} 局有记录` : '缺时长')}
        ${kpi('10′ 中位', signed(med10), at10s.length ? `${at10s.length} 局有过程` : '缺 10 分钟过程')}
        ${kpi('10′ 领先', `${leads.length}/${games.length}`, leads.length ? `守住 ${leads.filter((g) => g.result === 'win').length} 局` : '没有领先局')}
      </div>
      <div class="bgx-hero-games">${games.map((game) => {
        const cls = game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : '';
        const own = (game.heroesOwn || []).slice(0, 5);
        const foe = (game.heroesFoe || []).slice(0, 5);
        return `<a class="bgx-hero-game ${cls}" href="#match/${encodeURIComponent(game.matchKey)}" title="进入这一局的复盘">
          <span class="bgx-hero-game-head"><b>${esc(gameWord(game.displayIndex || game.gameIndex))}</b><em>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em></span>
          <span class="bgx-hero-game-val"><i>10′</i>${num(game.at10) ? signed(game.at10) : '—'}</span>
          <span class="bgx-hero-game-meta"><span>时长 ${dur(game.duration)}</span></span>
          ${own.length || foe.length ? `<span class="bgx-hero-lineup"><span>我</span><div>${own.map((hero) => h.portrait(hero, 'bgx-hero-face')).join('')}</div></span>
          <span class="bgx-hero-lineup is-foe"><span>敌</span><div>${foe.map((hero) => h.portrait(hero, 'bgx-hero-face')).join('')}</div></span>`
            : '<span class="bgx-hero-game-meta"><span>阵容待补</span></span>'}
        </a>`;
      }).join('')}</div>
      ${dupText ? `<p class="bgx-hero-note"><b>数据质量</b>${esc(dupText)}</p>` : ''}
    </header>`;
  }

  function cardShell(id, inner) {
    return `<section class="bgx-card" id="bgx-${esc(id)}">${inner}</section>`;
  }

  function detailHtml() {
    if (state.detailError) {
      return `<div class="page bgx-page"><a class="bgx-back" href="#biggame${scopeQuery()}">${glyph('home', { label: '返回列表', size: 18 })} 返回大场列表</a><section class="bgx-empty">${glyph('warning', { label: '读取失败', size: 28 })}<h2>读不到这场大场</h2><p>${esc(state.detailError)}</p></section></div>`;
    }
    const data = state.detail;
    if (!data) return `<div class="page bgx-page"><div class="loading">正在读取大场明细…</div></div>`;
    const series = data.series || {};
    // 只展示真正打过的局：BO7 四比零就是四局，不能把七个空槽摆出来。
    const games = (data.games || [])
      .filter((game) => game.result === 'win' || game.result === 'loss')
      .slice()
      .sort((a, b) => (Number(a.gameIndex) || 0) - (Number(b.gameIndex) || 0))
      .map((game, index) => ({ ...game, displayIndex: index + 1 }));
    const score = data.score || series.score || { us: 0, them: 0 };
    const insight = data.insight || {};
    const back = `#biggame${scopeQuery()}`;
    const { prev, next } = navNeighbors(series.id);
    const dateOf = (item) => String(item?.startAt || '').slice(5);
    const detailBar = `<div class="bgx-detail-bar">
      <a class="bgx-back" href="${back}">${glyph('home', { label: '返回列表', size: 18 })} 返回大场列表</a>
      <div class="bgx-detail-neighbors">
        ${prev ? `<a href="#biggame/${encodeURIComponent(prev.id)}${scopeQuery()}" title="上一场：${esc(prev.opponent || '')} ${esc(String(prev.startAt || '').slice(0, 10))}">← ${esc(prev.opponent || '上一场')} ${esc(dateOf(prev))}</a>` : ''}
        ${next ? `<a href="#biggame/${encodeURIComponent(next.id)}${scopeQuery()}" title="下一场：${esc(next.opponent || '')} ${esc(String(next.startAt || '').slice(0, 10))}">${esc(next.opponent || '下一场')} ${esc(dateOf(next))} →</a>` : ''}
      </div>
      <div class="bgx-detail-actions">
        ${currentCompetitionId() ? `<span class="bgx-chip" title="当前赛事">${esc((() => { try { return localStorage.getItem('training-current-competition-name') || ''; } catch { return ''; } })())}</span>` : ''}
        <button type="button" class="bgx-btn control" data-bgx-copy>${glyph('export', { label: '复制链接', size: 18 })} 复制链接</button>
        <button type="button" class="bgx-btn control" data-bgx-print>${glyph('book', { label: '打印', size: 18 })} 打印</button>
      </div>
    </div>`;
    const moduleKey = ['overview', 'bp', 'comp', 'exec'].includes(ui.module) ? ui.module : 'overview';
    const modules = [
      ['overview', '01', '总览与对比', 'chart'],
      ['bp', '02', 'BP 博弈', 'bp'],
      ['comp', '03', '阵容体系', 'heroes'],
      ['exec', '04', '执行与资源', 'heatmap'],
    ];
    const nav = `<nav class="rpt-nav" aria-label="分析模块">${modules.map(([key, index, label, icon]) =>
      `<button type="button" class="rpt-nav-item" data-bgx-module="${key}" aria-current="${key === moduleKey}">
        <span>${index}</span>${glyph(icon, { label, size: 18 })}<b>${esc(label)}</b>
      </button>`).join('')}</nav>`;
    let body = '';
    if (moduleKey === 'overview') {
      body = `<section class="rpt-module" id="bgx-overview">
        ${cardShell('overview', renderOverview(insight, ui, { esc, fmt, portrait: h.portrait }))}
      </section>`;
    } else if (moduleKey === 'bp') {
      const bpNav = `<nav class="bgv-subnav" aria-label="BP 页内导航">
        <button type="button" class="is-on" data-bp-jump="games">${glyph('matches', { label: '逐局 BP', size: 18 })} 逐局 BP</button>
        <button type="button" data-bp-jump="habit">${glyph('clock', { label: 'BO 习惯', size: 18 })} BO 习惯</button>
      </nav>`;
      body = `<section class="rpt-module" id="bgx-bp">
        ${bpNav}
        <div id="bgx-bp-games" class="bgv-bp-anchor">${cardShell('bp', renderBp(insight, ui, { esc, fmt, portrait: h.portrait, comboPool: state.comboPool }))}</div>
        <div id="bgx-bp-habit" class="bgv-bp-anchor">${renderBoHabit(insight, ui, { esc, fmt, portrait: h.portrait, comboPool: state.comboPool, rulesCounters: state.rulesCounters, rulesCombos: state.rulesCombos, boBoard: ui.boBoard })}</div>
      </section>`;
    } else if (moduleKey === 'comp') {
      body = `<section class="rpt-module" id="bgx-comp">
        ${cardShell('comp', renderCompSystem(insight, ui, {
          esc, fmt, portrait: h.portrait,
          ownName: h.teamName?.() || '本队', foeName: series.opponent || '对手',
        }))}
      </section>`;
    } else if (moduleKey === 'exec') {
      body = `<section class="rpt-module" id="bgx-exec">
        ${cardShell('phase', renderPhase(insight, ui, { esc, fmt }))}
      </section>`;
    }
    const rule = series.ruleset?.name || series.rulesetId || '规则集未设置';
    return `<div class="page bgx-page bgx-detail bgx-report">
      ${detailBar}
      ${heroHtml(data, games, score, insight)}
      <div class="rpt-layout">
        <aside class="rpt-rail">
          <div class="rpt-rail-meta">
            <span>BO${esc(String(series.bestOf || '—'))} · ${esc(String(series.startAt || '').slice(0, 10))}</span>
            <b>${esc(opponentLabel(series.opponent))}</b>
            <small>${esc(rule)} · ${count(games.length)} 局</small>
          </div>
          ${nav}
        </aside>
        <main class="rpt-main">
          ${body}
        </main>
      </div>
    </div>`;
  }

  /* ── 渲染与事件 ───────────────────────────────────────────── */
  function paint(html) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = html;
  }

  function scrollToBp(key) {
    const node = document.getElementById(`bgx-bp-${key}`);
    if (!node) return;
    const nav = document.querySelector('.bgv-subnav');
    if (nav) nav.querySelectorAll('[data-bp-jump]').forEach((button) => {
      button.classList.toggle('is-on', button.dataset.bpJump === key);
    });
    node.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function updateBpSubnav() {
    if (ui.module !== 'bp') return;
    const nav = document.querySelector('.bgv-subnav');
    if (!nav) return;
    const line = Math.max(nav.getBoundingClientRect().bottom + 18, window.innerHeight * 0.34);
    let active = 'games';
    for (const key of ['games', 'habit']) {
      const node = document.getElementById(`bgx-bp-${key}`);
      if (node && node.getBoundingClientRect().top <= line) active = key;
    }
    nav.querySelectorAll('[data-bp-jump]').forEach((button) => {
      button.classList.toggle('is-on', button.dataset.bpJump === active);
    });
  }

  function paintLoading(text) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = `<div class="page bgx-page"><div class="loading">${esc(text)}</div></div>`;
  }

  function repaintDetail() {
    if (!isCrossRoute() || !state.detail || !detailIdOf()) return;
    paint(detailHtml());
    document.dispatchEvent(new CustomEvent('route:repainted'));
    requestAnimationFrame(updateBpSubnav);
  }

  function ensure(force = false) {
    if (!isCrossRoute()) return;
    readScope();
    const detailId = detailIdOf();
    if (detailId) {
      if (force || state.detailId !== detailId || !state.detail) loadDetail(detailId);
      else if (state.detail) paint(detailHtml());
      return;
    }
    if (force || !state.loaded) loadAll();
    else paint(listHtml());
  }

  function render() {
    return '<div class="page bgx-page" data-bgx-root><div class="loading">正在汇总系列赛…</div></div>';
  }

  function onClick(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const target = event.target;
    const rangeBtn = target.closest('[data-cx-range]');
    if (rangeBtn) {
      scope.range = rangeBtn.dataset.cxRange;
      if (scope.range !== 'custom') { scope.from = ''; scope.to = ''; }
      syncScopeUrl(); paint(listHtml()); return;
    }
    const boBtn = target.closest('[data-cx-bo]');
    if (boBtn) { scope.bo = boBtn.dataset.cxBo; syncScopeUrl(); paint(listHtml()); return; }
    if (target.closest('[data-cx-clear]')) {
      Object.assign(scope, { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '', session: '', status: '', completion: '' });
      syncScopeUrl(); paint(listHtml()); return;
    }
    if (target.closest('[data-cx-retry]')) { state.loaded = false; loadAll(); return; }
    const copyBtn = target.closest('[data-bgx-copy]');
    if (copyBtn) {
      const text = location.href;
      const show = (message) => {
        announce(message);
        if (!copyBtn.isConnected) return;
        copyBtn.textContent = message;
        clearTimeout(copyBtn._copyTimer);
        copyBtn._copyTimer = setTimeout(() => {
          if (copyBtn.isConnected) copyBtn.textContent = '复制链接';
        }, 1600);
      };
      const fallback = () => {
        const area = document.createElement('textarea');
        area.value = text; area.style.position = 'fixed'; area.style.opacity = '0';
        document.body.append(area); area.select();
        let ok = false;
        try { ok = document.execCommand('copy'); } catch { ok = false; }
        area.remove();
        show(ok ? '已复制' : '复制失败，请手动复制地址栏链接');
      };
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(() => show('已复制')).catch(fallback);
      else fallback();
      return;
    }
    if (target.closest('[data-bgx-print]')) {
      document.querySelectorAll('details[data-bp-card]').forEach((node) => { node.open = true; });
      window.print();
      return;
    }
    // 单场页的视图切换：不重新取数，只换视图。
    const bpJump = target.closest('[data-bp-jump]');
    if (bpJump) { scrollToBp(bpJump.dataset.bpJump); return; }
    const bpGame = target.closest('[data-bp-game]');
    if (bpGame) {
      const id = bpGame.dataset.bpGame || '';
      ui.bpGame = id;
      if (id) ui.bpOpen[id] = true;
      else ui.bpOpen = {};
      repaintDetail();
      requestAnimationFrame(() => scrollToBp('games'));
      return;
    }
    const overviewView = target.closest('[data-bgv-view]');
    if (overviewView) {
      /* 赢局/输局视角只换呈现，保持滚动位置，教练不用重新找刚才那一行。 */
      const wanted = overviewView.dataset.bgvView;
      ui.overviewView = ['games', 'win', 'loss'].includes(wanted) ? wanted : 'games';
      const y = window.scrollY;
      repaintDetail();
      window.scrollTo(0, y);
      return;
    }
    const expandBtn = target.closest('[data-bgv-expand]');
    if (expandBtn) {
      /* 行展开就地切换 DOM，避免整页重绘带来的卡顿与焦点丢失。 */
      const panel = document.getElementById(expandBtn.dataset.bgvExpand || '');
      const open = expandBtn.getAttribute('aria-expanded') === 'true';
      expandBtn.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (panel) panel.hidden = open;
      return;
    }
    const gameCell = target.closest('[data-bgv-game]');
    if (gameCell && gameCell.closest('.bgv-board-scroll')) {
      const board = gameCell.closest('.bgv-board-scroll');
      const index = gameCell.dataset.bgvGame;
      const active = board.querySelector(`[data-bgv-game="${index}"].is-col-active`);
      board.querySelectorAll('[data-bgv-game].is-col-active').forEach((node) => node.classList.remove('is-col-active'));
      if (!active) {
        board.querySelectorAll('[data-bgv-game]').forEach((node) => {
          if (node.dataset.bgvGame === index) node.classList.add('is-col-active');
        });
      }
      return;
    }
    const metricGroup = target.closest('[data-bgv-group]');
    if (metricGroup) {
      ui.metricGroup = metricGroup.dataset.bgvGroup || 'all';
      repaintDetail();
      return;
    }
    const poolOutcome = target.closest('[data-bgx-pool-outcome]');
    if (poolOutcome) {
      ui.poolOutcomeScope = ['all', 'own', 'foe'].includes(poolOutcome.dataset.bgxPoolOutcome)
        ? poolOutcome.dataset.bgxPoolOutcome : 'all';
      repaintDetail();
      return;
    }
    const bohCell = target.closest('[data-boh-cell]');
    if (bohCell) {
      const side = bohCell.dataset.side === 'red' ? 'red' : 'blue';
      const kind = bohCell.dataset.kind;
      const index = Number(bohCell.dataset.index) || 0;
      const board = ui.boBoard;
      if (board.game !== (ui.boSlot || 1)) {
        board.game = ui.boSlot || 1;
        board.bans = { blue: [], red: [] };
        board.pick = null;
        board.open = {};
      }
      if (kind === 'ban') {
        const list = board.bans[side];
        const at = list.indexOf(index);
        if (at >= 0) list.splice(at, 1); else list.push(index);
        board.pick = null;
      } else {
        const same = board.pick && board.pick.side === side && board.pick.index === index;
        board.pick = same ? null : { side, index };
        board.bans = { blue: [], red: [] };
      }
      const y = window.scrollY;
      repaintDetail();
      window.scrollTo(0, y);
      return;
    }
    const bohStep = target.closest('[data-boh-step]');
    if (bohStep) {
      const best = Number(state.detail?.insight?.boBp?.bestOf) || 7;
      ui.boSlot = Math.min(best, Math.max(1, (ui.boSlot || 1) + Number(bohStep.dataset.bohStep || 0)));
      ui.boBoard = { game: 0, bans: { blue: [], red: [] }, pick: null, open: {} };
      repaintDetail();
      requestAnimationFrame(() => scrollToBp('habit'));
      return;
    }
    if (target.closest('[data-bgx-boreset]')) {
      Object.assign(ui, { boScope: 'opp', boWindow: '90', boSlot: 1 });
      ui.boBoard = { game: 0, bans: { blue: [], red: [] }, pick: null, open: {} };
      repaintDetail();
      return;
    }
    const phaseBtn = target.closest('[data-bgx-phase]');
    if (phaseBtn) { ui.phase = phaseBtn.dataset.bgxPhase; repaintDetail(); return; }
    const boWindow = target.closest('[data-bgx-bowindow]');
    if (boWindow) { ui.boWindow = boWindow.dataset.bgxBowindow; repaintDetail(); return; }
    const boScope = target.closest('[data-bgx-boscope]');
    if (boScope) { ui.boScope = boScope.dataset.bgxBoscope === 'all' ? 'all' : 'opp'; repaintDetail(); return; }
    const boOther = target.closest('[data-bgx-boother]');
    if (boOther) {
      // 赛事域：对手习惯类分析允许显式跨赛事积累（默认关，卡片上明示）。
      ui.boIncludeOtherEvents = !ui.boIncludeOtherEvents;
      if (state.detailId) loadDetail(state.detailId);
      return;
    }
    const boSlot = target.closest('[data-bgx-boslot]');
    if (boSlot) {
      ui.boSlot = Number(boSlot.dataset.bgxBoslot) || 1;
      ui.boBoard = { game: 0, bans: { blue: [], red: [] }, pick: null, open: {} };
      repaintDetail();
      return;
    }
    const intentToggle = target.closest('[data-boh-intent-toggle]');
    if (intentToggle) {
      const panel = intentToggle.parentElement?.querySelector('.bgv-boh-intent-panel');
      const open = intentToggle.getAttribute('aria-expanded') === 'true';
      /* 同一列一次只展开一层，避免几层面板把列撑得过长。 */
      if (!open) {
        intentToggle.closest('.bgv-boh-col')
          ?.querySelectorAll('[data-boh-intent-toggle][aria-expanded="true"]')
          .forEach((other) => {
            if (other === intentToggle) return;
            other.setAttribute('aria-expanded', 'false');
            other.parentElement?.querySelector('.bgv-boh-intent-panel')?.setAttribute('hidden', '');
          });
      }
      intentToggle.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (panel) panel.hidden = open;
      return;
    }
    const moduleBtn = target.closest('[data-bgx-module]');
    if (moduleBtn) {
      ui.module = moduleBtn.dataset.bgxModule;
      try { history.replaceState(null, '', `#biggame/${encodeURIComponent(detailIdOf())}${scopeQuery()}`); } catch { /* ignore */ }
      /* 页签是就地换内容，别把教练带回页面顶部；跟 BP 棋盘点格一样保住滚动位置。 */
      const y = window.scrollY;
      repaintDetail();
      window.scrollTo(0, y);
      return;
    }
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
    const baseNode = event.target.closest('[data-bgv-base]');
    if (baseNode) { ui.baseMode = baseNode.value; repaintDetail(); return; }
    const node = event.target.closest('[data-cx]');
    if (!node) return;
    const key = node.dataset.cx;
    if (key === 'opponent') scope.opponent = node.value;
    else if (key === 'session') scope.session = node.value;
    else if (key === 'status') scope.status = node.value;
    else if (key === 'completion') scope.completion = node.value;
    syncScopeUrl(); paint(listHtml());
  }

  function bind() {
    if (!bind.done) {
      bind.done = true;
      document.addEventListener('click', onClick);
      document.addEventListener('change', onChange);
      document.addEventListener('competition:selected', () => {
        // 赛事域（M1）：切赛事即切分析域——清空筛选与缓存的大场明细后重载。
        Object.assign(scope, {
          range: DEFAULT_RANGE, from: '', to: '',
          bo: '', opponent: '', session: '', status: '', completion: '',
        });
        Object.assign(ui, {
          phase: 'mid', window: 'd30', boWindow: '90', boScope: 'opp', boSlot: 1,
          baseMode: 'format', module: 'overview',
          boIncludeOtherEvents: false,
          bpGame: '', bpOpen: {}, metricGroup: 'all', overviewView: 'games', poolOutcomeScope: 'all',
          boBoard: { game: 0, bans: { blue: [], red: [] }, pick: null, open: {} },
        });
        state.detailId = '';
        state.detail = null;
        state.navLoaded = false;
        if (isCrossRoute()) {
          const id = detailIdOf();
          if (id) loadDetail(id);
          else { state.loaded = false; loadAll(); }
        } else loadAll();
      });
      let raf = 0;
      document.addEventListener('scroll', () => {
        if (ui.module !== 'bp' || raf) return;
        raf = requestAnimationFrame(() => { raf = 0; updateBpSubnav(); });
      }, { passive: true });
      document.addEventListener('toggle', (event) => {
        const node = event.target;
        if (node && node.matches && node.matches('details[data-bp-card]')) {
          ui.bpOpen[node.dataset.bpCard] = node.open;
        }
        /* 楼层板的三块折叠各自记忆开合，重绘后仍保持用户展开的状态。 */
        if (node && node.matches && node.matches('details[data-boh-fold]')) {
          ui.boBoard.open[node.dataset.bohFold] = node.open;
        }
      }, true);
      document.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const toggle = event.target?.closest?.('[data-boh-intent-toggle]');
        if (!toggle) return;
        event.preventDefault();
        toggle.click();
      });
      document.addEventListener('keydown', (event) => {
        if (ui.module !== 'bp' || !state.detail) return;
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target?.tagName)) return;
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        const board = document.querySelector('.bgv-boh');
        if (!board) return;
        const rect = board.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        const best = Number(state.detail?.insight?.boBp?.bestOf) || 7;
        const next = Math.min(best, Math.max(1, (ui.boSlot || 1) + (event.key === 'ArrowRight' ? 1 : -1)));
        if (next === ui.boSlot) return;
        event.preventDefault();
        ui.boSlot = next;
        repaintDetail();
        requestAnimationFrame(() => scrollToBp('habit'));
      });
    }
    ensure(true);
  }

  return { render, bind };
}
