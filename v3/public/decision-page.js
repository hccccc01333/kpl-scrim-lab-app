/* 赛训决策台（工作台网页端 #decision/<tab>）。
 *
 * 四个工作区直接内嵌在工作台里，不再跳客户端：
 *   赛后复盘 review / 赛前备战 prep / 选手研究 player / 训练验证 training
 *
 * 数据全部来自 /api/decision/*（后端已完成）与 /api/v3/effect，本文件不重复算业务口径：
 *   - 只做取数、排版、画 SVG 图与空态说明；
 *   - 每张图/表都写明有效样本 n，小样本或没数据时给具体原因，不补 0、不画假图；
 *   - 时间统一 m:ss，近似经济点标「≈」；只陈述证据，不写因果结论；
 *   - 所有请求带 AbortController + 世代号，切页/切 tab 不写回旧 DOM；失败给页面内重试。
 *
 * 页面壳：标题 + 数据范围栏 + 覆盖条 + 四 tab + 当前工作区。
 * 切 tab 只重挂当前区（history.pushState 同步 #decision/<tab>），刷新后保持当前 tab。
 */
export function createDecisionPage({ esc, fmt, pct, diff, time, icon, route, API_BASE, currentQuery }) {
  /* ── 常量 ─────────────────────────────────────────────────────── */
  const TABS = [
    { id: 'review', label: '赛后复盘', hint: '本局经济差 · 关键链' },
    { id: 'prep', label: '赛前备战', hint: '对手开局路线' },
    { id: 'player', label: '选手研究', hint: '资源分配复核' },
    { id: 'training', label: '训练验证', hint: '干预前后对照' },
  ];
  const TAB_IDS = TABS.map((item) => item.id);
  const TAB_LABEL = Object.fromEntries(TABS.map((item) => [item.id, item.label]));
  const RESULT_TEXT = { win: '胜', loss: '负', draw: '平', unknown: '未知' };
  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  const LANE_CLASS = { 对抗路: 'lane-1', 打野: 'lane-2', 中路: 'lane-3', 发育路: 'lane-4', 游走: 'lane-5', 辅助: 'lane-5' };
  const EVENT_LABEL = { death: '死亡', fight: '团战', objective: '资源', other: '事件' };
  const KIND_TEXT = { high_gold_low_damage: '高经济低输出', low_gold_high_damage: '低经济高输出', lane_death: '发育路死亡偏多' };
  const ANOMALY_LIMIT = 8;
  const CHAIN_LIMIT = 6;

  /* ── 小工具 ───────────────────────────────────────────────────── */
  const has = (value) => typeof value === 'number' && Number.isFinite(value);
  const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const plain = (value) => String(value ?? '').trim();
  const signed = (value, digits = 0) => (has(value) ? (value > 0 ? '+' : '') + fmt(value, digits) : '—');
  const gold = (value, digits = 0) => (has(value) ? signed(value, digits) + ' 金' : '—');
  const approxTime = (value) => (has(value) && value >= 0 ? '≈' + time(value) : '—');
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const resultText = (result) => RESULT_TEXT[result] || '—';
  const resultTone = (result) => (result === 'win' ? 'own' : result === 'loss' ? 'foe' : 'muted');
  const laneClass = (lane) => LANE_CLASS[lane] || 'lane-5';
  const isAbort = (error) => Boolean(error) && (error.name === 'AbortError' || error.code === 20);
  const isNarrow = () => {
    try { return window.matchMedia('(max-width: 760px)').matches; } catch { return false; }
  };
  function median(values) {
    const list = listOf(values).filter((value) => has(value)).sort((a, b) => a - b);
    if (!list.length) return null;
    const middle = Math.floor(list.length / 2);
    return list.length % 2 ? list[middle] : (list[middle - 1] + list[middle]) / 2;
  }
  function axisAmount(value) {
    const abs = Math.abs(value);
    if (abs >= 1000) return (value / 1000).toFixed(abs >= 10000 ? 0 : 1) + 'k';
    return String(Math.round(value));
  }
  /* 坐标刻度取整：1 / 2 / 2.5 / 5 × 10^k，避免出现 7.4k、-3.8k 这种不好读的格子。 */
  function niceStep(raw) {
    if (!(raw > 0)) return 1;
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const ratio = raw / power;
    const factor = ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 2.5 ? 2.5 : ratio <= 5 ? 5 : 10;
    return factor * power;
  }
  function niceTicks(low, high, target = 5) {
    const step = niceStep((high - low) / Math.max(1, target - 1));
    const start = Math.floor(low / step) * step;
    const end = Math.ceil(high / step) * step;
    const ticks = [];
    for (let value = start; value <= end + step * 0.001; value += step) {
      ticks.push(Math.abs(value) < step / 1000 ? 0 : Number(value.toFixed(6)));
    }
    return ticks.length > 9 ? ticks.filter((_, index) => index % 2 === 0) : ticks;
  }
  const badge = (label, tone = 'warn') => `<span class="dx-badge${tone ? ' is-' + tone : ''}">${esc(label)}</span>`;
  const note = (html, cls = '') => `<p class="dx-note${cls ? ' ' + cls : ''}">${html}</p>`;

  /* ── 状态（每次 mount 重置；切 tab 不重挂页面） ───────────────── */
  const state = {
    gen: 0,
    container: null,
    tab: 'review',
    catalog: null,
    scope: { from: '', to: '', opponent: '', result: '' },
    game: '',
    prepOpponent: '',
    prepOpponentInUrl: false,
    prepLane: '',
    playerLane: '',
  selectedPlayerPoint: null,
    urlGame: '',
    cache: new Map(),
    catalogAbort: null,
    tabAbort: null,
  };

  /* ── 通用 DOM 片段 ────────────────────────────────────────────── */
  function block(title, body, { noteText = '', action = '', cls = '', slot = '' } = {}) {
    return `<section class="section dx-block${slot ? ' dx-slot-' + slot : ''}${cls ? ' ' + cls : ''}">
      <div class="dx-block-head"><div class="dx-block-copy"><h2>${esc(title)}</h2>${noteText ? `<p>${noteText}</p>` : ''}</div>${action ? `<div class="dx-block-action">${action}</div>` : ''}</div>
      <div class="dx-block-body">${body}</div>
    </section>`;
  }
  function emptyCard(title, reason = '', actionHtml = '') {
    return `<div class="dx-empty"><b>${esc(title)}</b>${reason ? `<span>${reason}</span>` : ''}${actionHtml ? `<div class="dx-empty-action">${actionHtml}</div>` : ''}</div>`;
  }
  function readableError(error) {
    const message = plain(error && error.message);
    if (!message) return '接口暂时读不到数据，稍后重试即可。';
    if (/Failed to fetch|NetworkError|Load failed|Network request failed/i.test(message)) {
      return '与工作台的连接中断了，恢复后点重试即可。';
    }
    return message.length > 160 ? message.slice(0, 160) + '…' : message;
  }
  function errorCard(title, error, retryKind = 'tab') {
    /* 目录接口失败时没有工作区可重挂，重试必须走整页刷新（data-dx-refresh）。 */
    const attr = retryKind === 'refresh' ? 'data-dx-refresh' : 'data-dx-retry';
    return `<div class="dx-error" role="alert"><b>${esc(title)}</b><span>${esc(readableError(error))}</span><button type="button" class="control" ${attr}>${icon('refresh')} 重试</button></div>`;
  }
  function metrics(items) {
    return `<div class="dx-metrics">${items.map((item) => `<div class="dx-metric${item.tone ? ' is-' + item.tone : ''}">
      <span>${esc(item.label)}</span><strong>${item.value}</strong>${item.noteText ? `<small>${esc(item.noteText)}</small>` : ''}</div>`).join('')}</div>`;
  }
  function table(head, rows, cls = '') {
    return `<div class="dx-table-wrap"><table class="dx-table${cls ? ' ' + cls : ''}"><thead><tr>${head.map((cell) => `<th>${esc(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  const pctCell = (value) => (has(value) ? pct(value) : '—');
  const sampleCell = (enough, okText = '可用') => (enough === false ? badge('样本不足') : `<span class="dx-ok">${esc(okText)}</span>`);

  /* ── 数据请求（缓存 / abort / 不写回旧 DOM） ─────────────────── */
  function scopeQuery(extra = {}) {
    const params = new URLSearchParams();
    if (state.scope.from) params.set('from', state.scope.from);
    if (state.scope.to) params.set('to', state.scope.to);
    if (state.scope.opponent) params.set('opponent', state.scope.opponent);
    if (state.scope.result) params.set('result', state.scope.result);
    for (const [key, value] of Object.entries(extra)) {
      if (value === '' || value === null || value === undefined) continue;
      params.set(key, String(value));
    }
    const search = params.toString();
    return search ? '?' + search : '';
  }
  async function requestJson(path, search, signal, useCache = true) {
    const url = API_BASE + path + (search || '');
    if (useCache && state.cache.has(url)) return state.cache.get(url);
    const response = await fetch(url, { signal, cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) {
      let detail = '';
      try {
        const body = await response.json();
        detail = plain(body && (body.detail || body.reason));
      } catch { /* 非 JSON 错误体忽略 */ }
      const error = new Error(detail || `接口返回 ${response.status}`);
      error.status = response.status;
      throw error;
    }
    const body = await response.json();
    if (useCache) state.cache.set(url, body);
    return body;
  }
  const aliveOf = (gen, controller) => () => gen === state.gen
    && Boolean(state.container && state.container.isConnected)
    && !controller.signal.aborted;

  /* ── 页面壳 ───────────────────────────────────────────────────── */
  function opponentsSorted() {
    return [...listOf(state.catalog && state.catalog.opponents)]
      .filter((item) => item && (num(item.replayGames) || 0) > 0)
      .sort((a, b) => (num(b.replayGames) || 0) - (num(a.replayGames) || 0)
        || String(a.name || '').localeCompare(String(b.name || ''), 'zh'));
  }
  function scopeSummaryText() {
    const parts = [];
    if (state.scope.from || state.scope.to) parts.push(`${state.scope.from || '起'} → ${state.scope.to || '今'}`);
    if (state.scope.result === 'win') parts.push('只看胜局');
    if (state.scope.result === 'loss') parts.push('只看负局');
    if (state.scope.opponent) {
      const hit = opponentsSorted().find((item) => item.id === state.scope.opponent);
      parts.push(`对手 ${hit ? hit.name || hit.id : state.scope.opponent}`);
    }
    return parts.length ? parts.join(' · ') : '全部已关联回放';
  }
  function pageHead() {
    return `<div class="page-intro dx-intro">
      <div class="dx-hero-copy">
        <span class="dx-kicker">DECISION DESK <i></i> 赛训决策台</span>
        <h1>赛训决策台</h1>
        <p>先看证据，再决定练什么。所有「为什么输」都是候选事件，不宣称因果。</p>
      </div>
      <div class="intro-actions">
        <a class="control" href="#effect">训练效果页 ${icon('arrow')}</a>
        <button type="button" class="control icon-control" data-dx-action="refresh" aria-label="刷新决策数据" title="刷新决策数据">${icon('refresh')}</button>
      </div>
    </div>`;
  }
  function coverageBar(catalog) {
    const coverage = (catalog && catalog.coverage) || {};
    const items = [
      { label: '完整回放', value: `${fmt(num(coverage.pairedGames) ?? num(coverage.games))} 局`, noteText: `回放文件 ${fmt(coverage.replayGames)} 局` },
      { label: '终局面板', value: `${fmt(coverage.panelGames)} 局`, noteText: `${fmt(coverage.panelRows)} 行 · 逐人终局` },
      { label: '坐标', value: coverage.calibrated ? '已定标' : '未定标', noteText: coverage.calibrationNote || '位置按回放相对单位' },
      { label: '胜负', value: `${fmt(coverage.wins)} 胜 ${fmt(coverage.losses)} 负`, noteText: `可判胜负 ${fmt(coverage.withResult)} 局 · 团战 ${fmt(coverage.fights)} 场` },
      { label: '对手样本', value: `${fmt(coverage.opponents && coverage.opponents.replayOpponents)} 个有回放`, noteText: `3 局以上 ${fmt(coverage.opponents && coverage.opponents.with3Games)} 个 · 共 ${fmt(coverage.opponents && coverage.opponents.total)} 个` },
    ];
    return `<div class="dx-coverage" aria-label="数据覆盖">${items.map((item) => `<div class="dx-cover-item">
      <span>${esc(item.label)}</span><strong>${item.value}</strong><small>${esc(item.noteText)}</small></div>`).join('')}</div>`;
  }
  function scopeBar(catalog) {
    const dateRange = listOf(catalog && catalog.coverage && catalog.coverage.dateRange);
    const min = dateRange.length ? ` min="${esc(dateRange[0])}"` : '';
    const max = dateRange.length ? ` max="${esc(dateRange[dateRange.length - 1])}"` : '';
    const opponents = opponentsSorted();
    const resultOptions = [['', '全部结果'], ['win', '只取胜局'], ['loss', '只取负局']];
    const active = Boolean(state.scope.from || state.scope.to || state.scope.opponent || state.scope.result);
    return `<div class="dx-scope-bar" role="group" aria-label="数据范围">
      <label class="dx-field"><span>从</span><input type="date" data-dx-scope="from" aria-label="开始日期" value="${esc(state.scope.from)}"${min}${max}></label>
      <label class="dx-field"><span>到</span><input type="date" data-dx-scope="to" aria-label="结束日期" value="${esc(state.scope.to)}"${min}${max}></label>
      <label class="dx-field"><span>对手</span><select data-dx-scope="opponent" aria-label="对手">
        <option value="">全部对手</option>${opponents.map((item) => `<option value="${esc(item.id)}"${item.id === state.scope.opponent ? ' selected' : ''}>${esc(item.name || item.id)}（回放 ${fmt(item.replayGames)} 局）</option>`).join('')}
      </select></label>
      <label class="dx-field"><span>结果</span><select data-dx-scope="result" aria-label="结果">
        ${resultOptions.map(([value, label]) => `<option value="${esc(value)}"${value === state.scope.result ? ' selected' : ''}>${label}</option>`).join('')}
      </select></label>
      <button type="button" class="control" data-dx-action="reset-scope"${active ? '' : ' hidden'}>清除范围</button>
      <span class="dx-scope-state" data-dx-scope-state>当前范围：${esc(scopeSummaryText())}</span>
      <span class="dx-scope-error" data-dx-scope-error role="alert" hidden></span>
    </div>`;
  }
  function tabsBar() {
    return `<nav class="dx-tabs" role="tablist" aria-label="决策台页签">${TABS.map((item) => `<button type="button" role="tab" class="dx-tab${item.id === state.tab ? ' is-active' : ''}" data-dx-tab="${item.id}" aria-selected="${item.id === state.tab}"><b>${esc(item.label)}</b><small>${esc(item.hint)}</small></button>`).join('')}</nav>`;
  }
  function renderShell(gen) {
    const container = state.container;
    if (!container || gen !== state.gen || !container.isConnected) return;
    const catalog = state.catalog || {};
    const generated = catalog.generatedAt ? `数据生成 ${catalog.generatedAt} · ` : '';
    container.innerHTML = `<div class="page dx-page" data-dx-page="${state.tab}">
      ${pageHead()}
      ${coverageBar(catalog)}
      ${scopeBar(catalog)}
      ${tabsBar()}
      <div class="dx-workspace" data-dx-workspace data-dx-panel="${state.tab}" aria-busy="true"><div class="dx-loading">正在读取${esc(TAB_LABEL[state.tab])}数据…</div></div>
      <p class="dx-foot">${esc(generated)}口径：${esc(listOf(catalog.notes).join(' '))} 所有「为什么输」都是候选事件，不宣称因果；样本 n 始终可见，小样本只做观察。</p>
    </div>`;
    loadTab();
  }
  function renderShellError(error) {
    const container = state.container;
    if (!container) return;
    container.innerHTML = `<div class="page dx-page">
      ${pageHead()}
      <section class="section dx-block"><div class="dx-block-body">${errorCard('决策数据暂时读不到', error, 'refresh')}</div></section>
    </div>`;
  }
  function syncControls() {
    const container = state.container;
    if (!container) return;
    container.querySelectorAll('[data-dx-scope]').forEach((node) => {
      const key = node.dataset.dxScope;
      try { node.value = state.scope[key] || ''; } catch { /* 选项不存在时忽略 */ }
    });
    container.querySelectorAll('[data-dx-prep-opponent]').forEach((node) => {
      try { node.value = state.prepOpponent || ''; } catch { /* 选项不存在时忽略 */ }
    });
    const stateNode = container.querySelector('[data-dx-scope-state]');
    if (stateNode) stateNode.textContent = '当前范围：' + scopeSummaryText();
    const reset = container.querySelector('[data-dx-action="reset-scope"]');
    if (reset) reset.hidden = !(state.scope.from || state.scope.to || state.scope.opponent || state.scope.result);
    container.querySelectorAll('[data-dx-tab]').forEach((node) => {
      const active = node.dataset.dxTab === state.tab;
      node.classList.toggle('is-active', active);
      node.setAttribute('aria-selected', String(active));
    });
    const page = container.querySelector('.dx-page');
    if (page) page.dataset.dxPage = state.tab;
    const workspace = container.querySelector('[data-dx-workspace]');
    if (workspace) workspace.dataset.dxPanel = state.tab;
  }
  function showScopeError(message) {
    const node = state.container && state.container.querySelector('[data-dx-scope-error]');
    if (!node) return;
    node.textContent = message || '';
    node.hidden = !message;
  }

  /* ── 目录 / 工作区加载 ────────────────────────────────────────── */
  function defaultGameId(games) {
    const losses = listOf(games).filter((game) => game && game.result === 'loss');
    const hit = losses.length ? losses[losses.length - 1] : listOf(games)[listOf(games).length - 1];
    return hit ? String(hit.id) : '';
  }
  function applyRouteDefaults(catalog) {
    const games = listOf(catalog && catalog.games);
    const gameHit = games.some((game) => String(game.id) === state.urlGame);
    state.game = gameHit ? state.urlGame : defaultGameId(games);
    /* 赛前备战默认落到「某个对手」而不是整批聚合：本机每个对手只有 1 局回放，
       单对手视图能让「样本不足，仅单局观察」的提示真正成立。 */
    if (state.tab === 'prep') {
      let opponent = '';
      try {
        opponent = new URLSearchParams(location.hash.split('?')[1] || '').get('opponent') || '';
      } catch { opponent = ''; }
      if (opponent && opponentsSorted().some((item) => item.id === opponent)) {
        state.prepOpponent = opponent;
        state.prepOpponentInUrl = true;
      }
    }
    if (!state.prepOpponent && gameHit) {
      const game = games.find((item) => String(item.id) === state.urlGame);
      if (game && game.opponentId) state.prepOpponent = game.opponentId;
    }
    if (!state.prepOpponent) {
      const first = opponentsSorted()[0];
      if (first && first.id) state.prepOpponent = first.id;
    }
  }
  async function loadCatalog(gen) {
    const container = state.container;
    if (!container) return;
    try {
      const catalog = await requestJson('/api/decision/catalog', '', state.catalogAbort.signal, false);
      if (gen !== state.gen || !container.isConnected) return;
      state.catalog = catalog;
      applyRouteDefaults(catalog);
      renderShell(gen);
    } catch (error) {
      if (isAbort(error) || gen !== state.gen || !container.isConnected) return;
      renderShellError(error);
    }
  }
  async function loadTab() {
    const gen = state.gen;
    const container = state.container;
    const workspace = container && container.querySelector('[data-dx-workspace]');
    if (!workspace) return;
    state.tabAbort?.abort();
    const controller = new AbortController();
    state.tabAbort = controller;
    workspace.setAttribute('aria-busy', 'true');
    workspace.dataset.dxPanel = state.tab;
    workspace.innerHTML = `<div class="dx-loading">正在读取${esc(TAB_LABEL[state.tab])}数据…</div>`;
    const alive = aliveOf(gen, controller);
    let html = '';
    try {
      if (state.tab === 'review') html = await reviewHtml(controller.signal);
      else if (state.tab === 'prep') html = await prepHtml(controller.signal);
      else if (state.tab === 'player') html = await playerHtml(controller.signal);
      else html = await trainingHtml(controller.signal);
    } catch (error) {
      if (!alive() || isAbort(error)) return;
      workspace.innerHTML = `<div class="dx-stack">${block(TAB_LABEL[state.tab], errorCard('这一页暂时读不到数据', error))}</div>`;
      workspace.setAttribute('aria-busy', 'false');
      return;
    }
    if (!alive()) return;
    workspace.innerHTML = `<div class="dx-stack">${html}</div>`;
    workspace.setAttribute('aria-busy', 'false');
    syncControls();
  }
  function refreshAll() {
    const container = state.container;
    if (!container) return;
    state.cache.clear();
    state.catalogAbort?.abort();
    state.tabAbort?.abort();
    state.catalog = null;
    const gen = ++state.gen;
    state.catalogAbort = new AbortController();
    const workspace = container.querySelector('[data-dx-workspace]');
    if (workspace) {
      workspace.setAttribute('aria-busy', 'true');
      workspace.innerHTML = '<div class="dx-loading">正在刷新决策数据…</div>';
    }
    loadCatalog(gen);
  }

  /* ── 图表：经济差时间轴 ───────────────────────────────────────── */
  function eventKind(kind) {
    const text = String(kind || '').toLowerCase();
    if (/death|kill|阵亡|死亡/.test(text)) return 'death';
    if (/fight|battle|团/.test(text)) return 'fight';
    if (/objective|resource|tower|buff|资源|塔/.test(text)) return 'objective';
    return 'other';
  }
  function economyChart(series, chains, duration) {
    const times = listOf(series && series.times);
    const values = listOf(series && series.ownDiff).length ? series.ownDiff : listOf(series && series.rawDiff);
    const points = [];
    times.forEach((t, index) => {
      const value = num(values[index]);
      if (num(t) !== null && value !== null) points.push({ t, v: value });
    });
    points.sort((a, b) => a.t - b.t);
    if (points.length < 2) {
      return `<div class="dx-chart-empty">这一局没有可画的经济时间轴：缺官方回放经济采样（至少 2 个点），不补 0。</div>`;
    }
    const narrow = isNarrow();
    const W = narrow ? 380 : 700;
    const H = narrow ? 220 : 195;
    const pad = narrow ? { l: 40, r: 8, t: 12, b: 26 } : { l: 48, r: 12, t: 14, b: 26 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;
    const lastPoint = points[points.length - 1];
    const x1 = Math.max(num(duration) && duration > 0 ? duration : lastPoint.t, lastPoint.t, 1);
    const rawLow = Math.min(0, ...points.map((point) => point.v));
    const rawHigh = Math.max(0, ...points.map((point) => point.v));
    const span = rawHigh - rawLow || 1000;
    const yTicks = niceTicks(rawLow - span * 0.12, rawHigh + span * 0.12, 6);
    const low = yTicks[0];
    const high = yTicks[yTicks.length - 1];
    const px = (value) => pad.l + (value / x1) * plotW;
    const py = (value) => pad.t + ((high - value) / (high - low)) * plotH;
    const line = points.map((point, index) => `${index ? 'L' : 'M'}${px(point.t).toFixed(1)},${py(point.v).toFixed(1)}`).join(' ');
    const area = `${line} L${px(lastPoint.t).toFixed(1)},${py(0).toFixed(1)} L${px(points[0].t).toFixed(1)},${py(0).toFixed(1)} Z`;
    const stepX = narrow ? 120 : 300;
    const xTicks = [];
    for (let t = Math.ceil(0 / stepX) * stepX; t < x1; t += stepX) {
      if (t < (narrow ? 30 : 90) || x1 - t < (narrow ? 30 : 90)) continue;
      xTicks.push(t);
      if (xTicks.length >= 8) break;
    }
    const windows = [];
    const events = [];
    const seen = new Set();
    listOf(chains).slice(0, CHAIN_LIMIT).forEach((chain, index) => {
      const start = num(chain && chain.start);
      const end = num(chain && chain.end);
      if (start !== null) windows.push({ start, end: end === null ? start : end, index });
      let picked = 0;
      for (const candidate of listOf(chain && chain.candidates)) {
        const t = num(candidate && candidate.t) ?? num(candidate && candidate.timeSec);
        if (t === null) continue;
        const kind = eventKind(candidate && candidate.kind);
        if (kind === 'other') continue;
        const key = kind + ':' + Math.round(t / 6);
        if (seen.has(key)) continue;
        seen.add(key);
        events.push({ t, kind, index, label: plain(candidate.text) || plain(candidate.label) || '候选事件' });
        picked += 1;
        if (picked >= 3) break;
      }
    });
    events.sort((a, b) => a.t - b.t);
    const eventNodes = events.slice(0, 24).map((event) => {
      const ex = px(clamp(event.t, 0, x1));
      const title = `${EVENT_LABEL[event.kind]} · ≈${time(event.t)} · ${event.label}`;
      return `<g class="dx-econ-ev is-${event.kind}" data-dx-chain="${event.index}" tabindex="0" role="button" aria-label="跳到第 ${event.index + 1} 段关键链"><title>${esc(title)}</title><rect class="dx-econ-ev-hit" x="${(ex - 7).toFixed(1)}" y="${pad.t}" width="14" height="${plotH}"/><line x1="${ex.toFixed(1)}" x2="${ex.toFixed(1)}" y1="${pad.t}" y2="${H - pad.b}"/><circle cx="${ex.toFixed(1)}" cy="${(H - pad.b + 7).toFixed(1)}" r="3"/></g>`;
    }).join('');
    return `<div class="dx-chart dx-econ-chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="我方视角经济差时间轴，${points.length} 个近似采样点，最后 ${approxTime(lastPoint.t)} 时经济差 ${diff(lastPoint.v)} 金">
        ${yTicks.map((value) => `<line class="dx-grid" x1="${pad.l}" x2="${W - pad.r}" y1="${py(value).toFixed(1)}" y2="${py(value).toFixed(1)}"/><text class="dx-axis" x="${pad.l - 6}" y="${(py(value) + 3).toFixed(1)}" text-anchor="end">${value === 0 ? '0' : axisAmount(value)}</text>`).join('')}
        ${xTicks.map((t) => `<line class="dx-grid is-faint" x1="${px(t).toFixed(1)}" x2="${px(t).toFixed(1)}" y1="${pad.t}" y2="${H - pad.b}"/><text class="dx-axis" x="${px(t).toFixed(1)}" y="${H - 10}" text-anchor="middle">${time(t)}</text>`).join('')}
        ${windows.map((window) => `<rect class="dx-econ-window" x="${Math.min(px(window.start), px(window.end)).toFixed(1)}" y="${pad.t}" width="${Math.max(2, Math.abs(px(window.end) - px(window.start))).toFixed(1)}" height="${plotH}"><title>候选损失窗口 ≈${time(window.start)}–${time(window.end)}</title></rect>`).join('')}
        <line class="dx-zero" x1="${pad.l}" x2="${W - pad.r}" y1="${py(0).toFixed(1)}" y2="${py(0).toFixed(1)}"/>
        <path class="dx-econ-area" d="${area}"/>
        <path class="dx-econ-line" d="${line}"/>
        <circle class="dx-econ-dot" cx="${px(lastPoint.t).toFixed(1)}" cy="${py(lastPoint.v).toFixed(1)}" r="3.4"/>
        ${eventNodes}
        <text class="dx-axis is-title" x="${pad.l}" y="${H - 10}">0:00</text>
        <text class="dx-axis is-title" x="${W - pad.r}" y="${H - 10}" text-anchor="end">≈${time(lastPoint.t)}</text>
      </svg>
      <div class="dx-chart-foot"><span class="dx-legend">
        <i class="dx-swatch is-line"></i>我方经济差
        <i class="dx-swatch is-window"></i>候选损失窗口
        <i class="dx-swatch is-death"></i>死亡
        <i class="dx-swatch is-fight"></i>团战
        <i class="dx-swatch is-objective"></i>资源
      </span><span>≈ 经济点约 30 秒一个（${points.length} 个采样）· 点标记跳到对应链卡</span></div>
    </div>`;
  }

  /* ── 图表：经济分位带（胜 / 负 / 全部） ───────────────────────── */
  function bandChart(bands, opts = {}) {
    const split = Boolean(opts.split);
    const defs = [
      { key: 'win', label: '胜局', tone: 'own' },
      { key: 'loss', label: '负局', tone: 'foe' },
      { key: 'all', label: '全部', tone: 'accent' },
    ];
    const series = defs.map((def) => ({ ...def, points: [] }));
    const byKey = Object.fromEntries(series.map((item) => [item.key, item]));
    let maxMinute = 1;
    for (const band of listOf(bands)) {
      if (!band || typeof band !== 'object') continue;
      const minute = num(band.minute) ?? (num(band.seconds) !== null ? band.seconds / 60 : null);
      if (minute === null || minute < 0) continue;
      maxMinute = Math.max(maxMinute, minute);
      for (const item of series) {
        let source = band[item.key];
        if (!source && item.key === 'all') {
          const fallback = { n: band.n, p25: band.p25, p50: band.p50, p75: band.p75 };
          if (has(fallback.p25) || has(fallback.p50) || has(fallback.p75)) source = fallback;
        }
        if (!source || typeof source !== 'object') continue;
        const n = num(source.n) ?? num(item.key === 'win' ? band.nWin : item.key === 'loss' ? band.nLoss : band.nAll) ?? 0;
        if (!(n > 0)) continue;
        const p25 = num(source.p25);
        const p50 = num(source.p50);
        const p75 = num(source.p75);
        if (p25 === null && p50 === null && p75 === null) continue;
        byKey[item.key].points.push({ minute, n, p25, p50, p75 });
      }
    }
    const usable = series
      .map((item) => ({ ...item, points: item.points.sort((a, b) => a.minute - b.minute) }))
      .filter((item) => item.points.length >= 2);
    if (!usable.length) {
      return `<div class="dx-chart-empty">当前范围胜局 / 负局样本还不足以画分位带；不画空白坐标轴。</div>`;
    }
    const narrow = isNarrow();
    const W = narrow ? 380 : split ? 540 : 900;
    const H = narrow ? 225 : split ? 205 : 160;
    const pad = narrow ? { l: 40, r: 8, t: 12, b: 28 } : { l: split ? 46 : 50, r: 14, t: 12, b: 26 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;
    const rangeValues = usable.flatMap((item) => item.points.flatMap((point) => [point.p25, point.p75]))
      .filter((value) => has(value));
    const rawLow = Math.min(0, ...rangeValues);
    const rawHigh = Math.max(0, ...rangeValues);
    const span = rawHigh - rawLow || 1000;
    const yTicks = niceTicks(rawLow - span * 0.1, rawHigh + span * 0.1, 6);
    const low = yTicks[0];
    const high = yTicks[yTicks.length - 1];
    const px = (minute) => pad.l + (minute / maxMinute) * plotW;
    const py = (value) => pad.t + ((high - value) / (high - low)) * plotH;
    const step = maxMinute <= 20 ? 5 : 10;
    const xTicks = [];
    for (let minute = 0; minute <= maxMinute; minute += step) xTicks.push(minute);
    if (xTicks[xTicks.length - 1] !== maxMinute) xTicks.push(maxMinute);
    const segments = (points, valid) => {
      const chunks = [];
      let current = [];
      for (const point of points) {
        if (valid(point)) current.push(point);
        else if (current.length) { chunks.push(current); current = []; }
      }
      if (current.length) chunks.push(current);
      return chunks;
    };
    const drawn = usable.map((item) => {
      const areaChunks = segments(item.points, (point) => point.p25 !== null && point.p75 !== null).map((chunk) => {
        const top = chunk.map((point) => `${px(point.minute).toFixed(1)},${py(point.p75).toFixed(1)}`);
        const bottom = [...chunk].reverse().map((point) => `${px(point.minute).toFixed(1)},${py(point.p25).toFixed(1)}`);
        return `<path class="dx-band-area" d="M${top.join(' L')} L${bottom.join(' L')} Z"/>`;
      }).join('');
      const lineChunks = segments(item.points, (point) => point.p50 !== null).map((chunk) => `<path class="dx-band-line" d="${chunk.map((point, index) => `${index ? 'L' : 'M'}${px(point.minute).toFixed(1)},${py(point.p50).toFixed(1)}`).join(' ')}"/>`).join('');
      const hits = item.points.map((point) => `<circle class="dx-band-hit" cx="${px(point.minute).toFixed(1)}" cy="${py(point.p50 ?? point.p25 ?? 0).toFixed(1)}" r="7"><title>${esc(`${item.label} · ${Math.round(point.minute)}′ · n=${point.n} · P25 ${signed(point.p25)} / P50 ${signed(point.p50)} / P75 ${signed(point.p75)}`)}</title></circle>`).join('');
      return `<g class="dx-band tone-${item.tone}">${areaChunks}${lineChunks}${hits}</g>`;
    }).join('');
    const legend = usable.map((item) => {
      const counts = item.points.map((point) => point.n).filter((value) => value > 0);
      const minN = Math.min(...counts);
      const maxN = Math.max(...counts);
      return `<span class="dx-legend-item tone-${item.tone}"><i class="dx-swatch is-band"></i>${esc(item.label)} · n=${fmt(minN)}${minN === maxN ? '' : '–' + fmt(maxN)}</span>`;
    }).join('');
    return `<div class="dx-chart dx-band-chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="经济分位带：胜局、负局与全部对局的我方经济差 P25–P75 与 P50">
        ${yTicks.map((value) => `<line class="dx-grid" x1="${pad.l}" x2="${W - pad.r}" y1="${py(value).toFixed(1)}" y2="${py(value).toFixed(1)}"/><text class="dx-axis" x="${pad.l - 6}" y="${(py(value) + 3).toFixed(1)}" text-anchor="end">${value === 0 ? '0' : axisAmount(value)}</text>`).join('')}
        ${xTicks.map((minute) => `<line class="dx-grid is-faint" x1="${px(minute).toFixed(1)}" x2="${px(minute).toFixed(1)}" y1="${pad.t}" y2="${H - pad.b}"/><text class="dx-axis" x="${px(minute).toFixed(1)}" y="${H - 10}" text-anchor="middle">${Math.round(minute)}′</text>`).join('')}
        <line class="dx-zero" x1="${pad.l}" x2="${W - pad.r}" y1="${py(0).toFixed(1)}" y2="${py(0).toFixed(1)}"/>
        ${drawn}
      </svg>
      <div class="dx-chart-foot"><span class="dx-legend">${legend}</span><span>每档至少 1 局才画；阴影=P25–P75，实线=P50；≈ 经济点约 30 秒一个</span></div>
    </div>`;
  }

  /* ── 图表：开局热区 ───────────────────────────────────────────── */
  function routePoints(route) {
    const source = listOf(route && route.representative && route.representative.points).length
      ? route.representative.points
      : listOf(route && route.points).length ? route.points : listOf(route && route.route);
    const out = [];
    for (const point of source) {
      if (Array.isArray(point)) {
        if (point.length >= 3) {
          const x = num(point[1]);
          const y = num(point[2]);
          if (x !== null && y !== null) out.push([x, y]);
        } else {
          const x = num(point[0]);
          const y = num(point[1]);
          if (x !== null && y !== null) out.push([x, y]);
        }
      } else if (point && typeof point === 'object') {
        const x = num(point.x);
        const y = num(point.y);
        if (x !== null && y !== null) out.push([x, y]);
      }
    }
    return out;
  }
  function heatChart(heat, routes) {
    const cells = listOf(heat && heat.cells).filter((cell) => cell && has(cell.x) && has(cell.y) && has(cell.n) && cell.n > 0);
    if (!cells.length) {
      return `<div class="dx-chart-empty">这一批没有可画的开局热区：缺位置采样（positions.json），不补 0。</div>`;
    }
    const narrow = isNarrow();
    const size = narrow ? 340 : 400;
    const grid = has(heat.grid) && heat.grid >= 2 ? Math.min(40, heat.grid) : 20;
    const cell = size / grid;
    const ceiling = Math.max(1, num(heat.max) || Math.max(...cells.map((item) => item.n)));
    const xOf = (value) => clamp(value, 0, 1) * size;
    const yOf = (value) => (1 - clamp(value, 0, 1)) * size;
    const gridLines = [];
    for (let index = 1; index < grid; index += 1) {
      gridLines.push(`<line class="dx-heat-grid" x1="${(index * cell).toFixed(1)}" x2="${(index * cell).toFixed(1)}" y1="0" y2="${size}"/>`);
      gridLines.push(`<line class="dx-heat-grid" x1="0" x2="${size}" y1="${(index * cell).toFixed(1)}" y2="${(index * cell).toFixed(1)}"/>`);
    }
    const zoneLines = [1, 2].map((index) => `<line class="dx-heat-zone" x1="${(index * size / 3).toFixed(1)}" x2="${(index * size / 3).toFixed(1)}" y1="0" y2="${size}"/><line class="dx-heat-zone" x1="0" x2="${size}" y1="${(index * size / 3).toFixed(1)}" y2="${(index * size / 3).toFixed(1)}"/>`).join('');
    const cellNodes = cells.map((item) => `<rect class="dx-heat-cell" x="${(item.x * cell).toFixed(1)}" y="${((grid - 1 - item.y) * cell).toFixed(1)}" width="${cell.toFixed(1)}" height="${cell.toFixed(1)}" fill-opacity="${(0.08 + Math.pow(item.n / ceiling, 0.65) * 0.72).toFixed(3)}"><title>(${item.x}, ${item.y}) · ${item.n} 个位置采样点</title></rect>`).join('');
    const routeNodes = listOf(routes).map((item, index) => {
      const points = routePoints(item);
      if (points.length < 2) return '';
      const d = points.map(([x, y], pointIndex) => `${pointIndex ? 'L' : 'M'}${xOf(x).toFixed(1)},${yOf(y).toFixed(1)}`).join(' ');
      const id = `route-${index}`;
      const label = `${item.lane || '分路未知'} · ${num(item.count) ?? 0} 次`;
      return `<g class="dx-heat-route ${laneClass(item.lane)}" data-dx-route="${id}"><path d="${d}"/><circle cx="${xOf(points[0][0]).toFixed(1)}" cy="${yOf(points[0][1]).toFixed(1)}" r="2.6"/><title>${esc(label)}</title></g>`;
    }).join('');
    const scale = `<div class="dx-heat-head"><span class="dx-heat-scale">少 <i class="is-low"></i><i class="is-mid"></i><i class="is-high"></i> 多</span><span class="dx-muted">x → 右 · y → 上 · ${grid}×${grid} 计数格</span></div>`;
    return `<div class="dx-chart dx-heat-chart">${scale}
      <svg viewBox="0 0 ${size} ${size}" role="img" aria-label="开局 0–4 分钟位置热区与代表路线叠加">
        <rect class="dx-heat-bg" x="0" y="0" width="${size}" height="${size}"/>
        ${gridLines.join('')}${zoneLines}
        ${cellNodes}
        ${routeNodes}
      </svg>
    </div>`;
  }

  /* ── 图表：资源四象限散点 ─────────────────────────────────────── */
  function quadrantChart(players, quadrant, selectedIndex = null) {
    const points = [];
    listOf(players).forEach((player, index) => {
      if (!player) return;
      const x = num(player.goldShare);
      const y = num(player.heroDamageShare);
      if (x === null || y === null) return;
      points.push({
        index,
        x,
        y,
        lane: player.lane,
        name: player.name || player.playerId || `选手 ${index + 1}`,
        hero: player.hero,
        gpm: num(player.gpm),
        deaths: num(player.deaths),
        towerShare: num(player.towerShare),
        quadrant: player.quadrant,
        source: [player.date, player.opponentName ? '对阵 ' + player.opponentName : '', resultText(player.result)].filter(Boolean).join(' · '),
      });
    });
    if (!points.length) {
      return `<div class="dx-chart-empty">当前筛选没有同时具备经济占比与英雄伤害占比的样本；不画空白四象限。</div>`;
    }
    const narrow = isNarrow();
    const W = narrow ? 380 : 660;
    const H = narrow ? 320 : 350;
    const pad = narrow ? { l: 42, r: 12, t: 16, b: 40 } : { l: 48, r: 16, t: 18, b: 44 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;
    const xMax = Math.max(30, Math.max(...points.map((point) => point.x)) * 1.12);
    const yMax = Math.max(30, Math.max(...points.map((point) => point.y)) * 1.12);
    const px = (value) => pad.l + clamp(value / xMax, 0, 1) * plotW;
    const py = (value) => pad.t + (1 - clamp(value / yMax, 0, 1)) * plotH;
    const midX = num(quadrant && quadrant.xSplit) ?? median(points.map((point) => point.x)) ?? 20;
    const midY = num(quadrant && quadrant.ySplit) ?? median(points.map((point) => point.y)) ?? 20;
    const towerMax = Math.max(0, ...points.map((point) => point.towerShare || 0));
    const radius = (point) => {
      if (!towerMax || !point.towerShare || point.towerShare <= 0) return 3.6;
      return 3 + Math.sqrt(point.towerShare / towerMax) * 4.8;
    };
    const lanes = [...new Set(points.map((point) => point.lane || '未标注'))];
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => `<line class="dx-grid is-faint" x1="${pad.l}" x2="${W - pad.r}" y1="${(pad.t + ratio * plotH).toFixed(1)}" y2="${(pad.t + ratio * plotH).toFixed(1)}"/><line class="dx-grid is-faint" x1="${(pad.l + ratio * plotW).toFixed(1)}" x2="${(pad.l + ratio * plotW).toFixed(1)}" y1="${pad.t}" y2="${H - pad.b}"/>`).join('');
    const dots = points.map((point) => {
      const title = `${point.name}${point.hero ? ' · ' + point.hero : ''} · ${point.lane || '分路未标注'} · 经济占比 ${pct(point.x)} · 伤害占比 ${pct(point.y)} · GPM ${fmt(point.gpm, 1)} · 死亡 ${fmt(point.deaths)} · 推塔占比 ${pct(point.towerShare)}${point.source ? ' · ' + point.source : ''}`;
      const selected = selectedIndex === point.index ? ' is-selected' : '';
      return `<g class="dx-quad-point ${laneClass(point.lane)}${selected}" data-dx-point="${point.index}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title><circle cx="${px(point.x).toFixed(1)}" cy="${py(point.y).toFixed(1)}" r="${radius(point).toFixed(1)}"/></g>`;
    }).join('');
    const xAxis = [0, 0.25, 0.5, 0.75, 1].map((ratio) => `<text class="dx-axis" x="${(pad.l + ratio * plotW).toFixed(1)}" y="${(H - pad.b + 14).toFixed(1)}" text-anchor="middle">${Math.round(ratio * xMax)}%</text>`).join('');
    const yAxis = [0, 0.25, 0.5, 0.75, 1].map((ratio) => `<text class="dx-axis" x="${pad.l - 6}" y="${(pad.t + ratio * plotH + 3).toFixed(1)}" text-anchor="end">${Math.round((1 - ratio) * yMax)}%</text>`).join('');
    const legend = lanes.map((lane) => `<span class="dx-legend-item ${laneClass(lane)}"><i class="dx-swatch is-dot"></i>${esc(lane)}</span>`).join('');
    return `<div class="dx-chart dx-quad-chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="经济占比与英雄伤害占比四象限散点，共 ${points.length} 人次">
        ${grid}
        <line class="dx-quad-mid" x1="${px(midX).toFixed(1)}" x2="${px(midX).toFixed(1)}" y1="${pad.t}" y2="${H - pad.b}"/>
        <line class="dx-quad-mid" x1="${pad.l}" x2="${W - pad.r}" y1="${py(midY).toFixed(1)}" y2="${py(midY).toFixed(1)}"/>
        <text class="dx-axis is-quad" x="${(px(midX) + 4).toFixed(1)}" y="${(pad.t + 10).toFixed(1)}">高输出</text>
        <text class="dx-axis is-quad" x="${(px(midX) - 4).toFixed(1)}" y="${(pad.t + 10).toFixed(1)}" text-anchor="end">低输出</text>
        <text class="dx-axis is-quad" x="${(pad.l + 4).toFixed(1)}" y="${(py(midY) - 4).toFixed(1)}">低经济</text>
        <text class="dx-axis is-quad" x="${(W - pad.r - 4).toFixed(1)}" y="${(py(midY) - 4).toFixed(1)}" text-anchor="end">高经济</text>
        ${dots}
        <line class="dx-quad-axis" x1="${pad.l}" x2="${W - pad.r}" y1="${H - pad.b}" y2="${H - pad.b}"/>
        <line class="dx-quad-axis" x1="${pad.l}" x2="${pad.l}" y1="${pad.t}" y2="${H - pad.b}"/>
        ${xAxis}${yAxis}
        <text class="dx-axis is-title" x="${(pad.l + plotW / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">经济占比（%）</text>
        <text class="dx-axis is-title" x="12" y="${(pad.t + plotH / 2).toFixed(1)}" text-anchor="middle" transform="rotate(-90 12 ${(pad.t + plotH / 2).toFixed(1)})">英雄伤害占比（%）</text>
      </svg>
      <div class="dx-chart-foot"><span class="dx-legend">${legend}<span class="dx-legend-note">点大小＝推塔占比</span></span><span>n=${fmt(points.length)} 人次 · 中位线 ${pct(midX)} / ${pct(midY)} · 点击/回车看详情</span></div>
    </div>`;
  }

  /* ── 赛后复盘 ─────────────────────────────────────────────────── */
  function reviewHead(game, loss, advantage, advGame) {
    const games = listOf(state.catalog && state.catalog.games);
    const select = `<label class="dx-field"><span>复盘对局</span><select data-dx-game aria-label="选择复盘对局">${games.map((item) => `<option value="${esc(item.id)}"${String(item.id) === String(state.game) ? ' selected' : ''}>${esc(item.label || item.id)} · ${esc(resultText(item.result))}</option>`).join('')}</select></label>`;
    const meta = game
      ? `<span class="dx-toolbar-meta">${esc(game.date || '日期未知')} · ${esc(game.opponent || '对手待命名')} · ${time(game.duration)} · 回放${game.hasEconomy ? '含经济点' : '缺经济点'} · ${game.hasFights ? '含团战' : '缺团战'} · ${game.hasPositions ? '含位置' : '缺位置'}</span>`
      : '<span class="dx-toolbar-meta">这一局不在当前数据目录里，先在上面选一局。</span>';
    const link = game ? `<a class="control" href="${esc(route('match', game.id))}">打开单局复盘 ${icon('arrow')}</a>` : '';
    const adv = advGame || {};
    const lossSummary = (loss && loss.summary) || {};
    const metricItems = [
      {
        label: '本局最大领先',
        value: esc(gold(adv.maxLead)),
        noteText: has(adv.maxLeadAt) ? `≈${time(adv.maxLeadAt)} 见顶` : '本局没有可用经济点',
      },
      {
        label: '峰值后回撤',
        value: has(adv.drawdown) ? esc(fmt(adv.drawdown)) + ' 金' : '—',
        noteText: has(adv.drawdownAt) ? `≈${time(adv.drawdownAt)} 触底` : '从最高点回落到最低点',
      },
      {
        label: '领先时长',
        value: esc(time(adv.leadDurationSec)),
        noteText: '经济差 ≥ +500 的累计时长',
      },
      {
        label: '首次兑现',
        value: esc(time(adv.conversionSec)),
        noteText: '领先 ≥1000 到下一个我方资源 / 塔',
      },
      {
        label: '10 分钟经济差',
        value: esc(gold(adv.leadAt10)),
        noteText: adv.leadAt10Bucket ? esc(String(adv.leadAt10Bucket)) : '不足 10 分钟的局不给该指标',
      },
      {
        label: '本局结局',
        value: adv.comeback ? '被翻盘' : esc(resultText(game && game.result)),
        noteText: adv.comeback ? '曾领先 ≥1000 且最终告负' : '描述性结果，不评价指挥',
      },
    ];
    const windowLine = loss && loss.available
      ? `<span class="dx-toolbar-meta">本局损失窗口 ${fmt(lossSummary.windows)} 个${has(loss.game && loss.game.threshold) ? ` · 阈值 ${fmt(loss.game.threshold)} 金` : ''}${lossSummary.enough === false ? ' · 样本 <10 只做观察' : ''}</span>`
      : `<span class="dx-toolbar-meta">本局损失窗口：${esc((loss && loss.reason) || '暂不可用')}</span>`;
    return `<section class="section dx-block dx-slot-head">
      <div class="dx-block-body">
        <div class="dx-toolbar">${select}${meta}${link}</div>
        <div class="dx-toolbar dx-toolbar-sub">${windowLine}<span class="dx-toolbar-meta">时间与经济点均为近似值（≈ 30 秒一个采样点）</span></div>
        ${metrics(metricItems)}
      </div>
    </section>`;
  }
  function chainKind(kind) {
    const mapped = eventKind(kind);
    return mapped === 'other' ? '事件' : EVENT_LABEL[mapped];
  }
  function chainsHtml(chains, lossGame) {
    if (!chains.length) {
      return `<div class="dx-sub-empty">这一局没有达到阈值的损失窗口：经济差没有出现显著下滑，或者缺经济采样。</div>`;
    }
    const cards = chains.slice(0, CHAIN_LIMIT).map((chain, index) => {
      const start = num(chain && chain.start);
      const end = num(chain && chain.end);
      const delta = num(chain && chain.delta);
      const evidence = listOf(chain && chain.evidence)[0];
      const evidenceText = typeof evidence === 'string' ? plain(evidence) : plain(evidence && evidence.text);
      const firstCandidate = listOf(chain && chain.candidates)[0];
      const summaryText = evidenceText || plain(firstCandidate && firstCandidate.text) || '窗口内没有可列出的候选事件';
      const candidates = listOf(chain && chain.candidates).slice(0, 8).map((candidate) => {
        const t = num(candidate && candidate.t) ?? num(candidate && candidate.timeSec);
        const label = plain(candidate && candidate.text) || plain(candidate && candidate.label) || '候选事件';
        return `<li><span class="dx-cand-time">${t === null ? '—' : '≈' + time(t)}</span><em class="dx-cand-kind is-${eventKind(candidate && candidate.kind)}">${esc(chainKind(candidate && candidate.kind))}</em><span class="dx-cand-text">${esc(label)}</span></li>`;
      }).join('');
      const total = listOf(chain && chain.candidates).length;
      return `<details class="dx-chain" id="dx-chain-${index}" data-dx-chain-card="${index}">
        <summary>
          <span class="dx-chain-top">
            <span class="dx-chain-time">${start === null ? '时间未知' : '≈' + time(start) + '–' + time(end === null ? start : end)}</span>
            <span class="dx-tag is-warn">${esc((chain && (chain.typeLabel || chain.type)) || '未分类')}</span>
            <span class="dx-chain-delta${has(delta) && delta < 0 ? ' is-neg' : ''}">${esc(diff(delta))} 金</span>
            <span class="dx-chain-phase">${esc((chain && chain.phase) || '阶段未知')}</span>
            <span class="dx-chain-count">候选 ×${fmt(total)}</span>
          </span>
          <span class="dx-chain-ev" title="${esc(summaryText)}">${esc(summaryText)}</span>
        </summary>
        <div class="dx-chain-body">
          <ul class="dx-cand-list">${candidates || '<li class="dx-muted">窗口内没有找到可列出的候选事件，只保留经济损失本身。</li>'}</ul>
          <div class="dx-chain-foot">
            <span>${total > 8 ? `共 ${fmt(total)} 条候选，显示前 8 条。` : ''}关联范围 = 窗口 ±60 秒；只列候选事件，不证明因果。</span>
            <a href="${esc(route('match', (lossGame && lossGame.id) || state.game))}">回到这一局 ${icon('arrow')}</a>
          </div>
        </div>
      </details>`;
    }).join('');
    return `<div class="dx-chains">${cards}</div>`;
  }
  function advantageTables(advantage) {
    const buckets = listOf(advantage && advantage.buckets);
    const bucketRows = buckets.map((bucket) => [
      esc(bucket.bucket || bucket.label || `${fmt(bucket.low)} ~ ${fmt(bucket.high)}`),
      fmt(bucket.n),
      fmt(bucket.wins),
      pctCell(bucket.winRate),
      sampleCell(bucket.enough),
    ]);
    const games = [...listOf(advantage && advantage.games)]
      .filter((game) => num(game && game.drawdown) !== null)
      .sort((a, b) => (num(b.drawdown) || 0) - (num(a.drawdown) || 0))
      .slice(0, 8);
    const drawRows = games.map((game) => {
      const id = String((game && (game.id || game.game)) || '');
      return [
        id ? `<a href="${esc(route('match', id))}">${esc(game.label || id)}</a>` : '—',
        `<span class="dx-result is-${resultTone(game.result)}">${esc(resultText(game.result))}</span>`,
        esc(gold(game.maxLead)),
        has(game.drawdown) ? esc(fmt(game.drawdown)) + ' 金' : '—',
        game.comeback ? badge('被翻盘') : '—',
      ];
    });
    return {
      bucketTable: bucketRows.length
        ? table(['分桶', 'n', '胜', '胜率', '样本'], bucketRows)
        : '<div class="dx-sub-empty">当前范围没有 10 分钟分桶样本。</div>',
      drawTable: drawRows.length
        ? table(['对局', '结果', '最大领先', '回撤', '翻盘'], drawRows)
        : '<div class="dx-sub-empty">当前范围没有可算回撤的对局。</div>',
    };
  }
  function advantageSummaryLine(advantage) {
    const summary = (advantage && advantage.summary) || {};
    const coverage = (advantage && advantage.coverage) || {};
    const ci = has(summary.comebackCiLow) || has(summary.comebackCiHigh)
      ? `Wilson ${pct(summary.comebackCiLow)}–${pct(summary.comebackCiHigh)}`
      : '';
    const item = (label, value) => `<span><i>${esc(label)}</i><b>${value}</b></span>`;
    return `<div class="dx-sumline">
      ${item('曾领先 ≥1000', `${fmt(summary.ledGames)} 局`)}
      ${item('翻盘率（样本内观察）', `${pct(summary.comebackRate)}（${fmt(summary.comebacks)}/${fmt(summary.ledGames)}）`)}
      ${item('平均最大领先', gold(summary.avgMaxLead))}
      ${item('平均峰值后回撤', has(summary.avgDrawdown) ? fmt(summary.avgDrawdown) + ' 金' : '—')}
      ${item('平均兑现时间', time(summary.avgConversionSec))}
    </div>
    ${note(`范围内 ${fmt(summary.games)} 局（有经济点 ${fmt(coverage.economyGames)} 局），其中 ${fmt(summary.ledGames)} 局曾领先 ≥1000；中位最大领先 ${gold(summary.medianMaxLead)}，最大回撤 ${fmt(summary.maxDrawdown)} 金，兑现 n=${fmt(summary.conversionN)}${ci ? '，' + ci : ''}。占比与时间为近似值。`)}`;
  }
  function advantageBlock(advantage) {
    const summary = (advantage && advantage.summary) || {};
    const sampleNote = summary.enough === false
      ? badge('样本不足 · 只做观察')
      : `<span class="dx-ok">样本可用 · n=${fmt(summary.ledGames)} 局</span>`;
    const { bucketTable, drawTable } = advantageTables(advantage);
    const drawTotal = listOf(advantage && advantage.games).filter((game) => num(game && game.drawdown) !== null).length;
    const band = bandChart(advantage.bands, { split: !isNarrow() });
    const body = `${advantageSummaryLine(advantage)}
      <div class="dx-adv-grid">
        <div class="dx-adv-tables">
          <h3 class="dx-subhead">10 分钟经济差分桶</h3>${bucketTable}
          <details class="dx-details"><summary>回撤排行（前 8 / 共 ${fmt(drawTotal)} 局）· 展开看单局与翻盘</summary>${drawTable}</details>
        </div>
        <div class="dx-adv-band">
          <h3 class="dx-subhead">经济分位带 · 胜 / 负 / 全部</h3>${band}
          ${note(esc(advantage.note || '按分钟插值我方经济差的分位；n=0 的档不画。') + ' 翻盘率是样本内观察，不证明因果。')}
        </div>
      </div>`;
    return block('优势保持与回撤（跨局）', body, {
      noteText: '最大领先 / 峰值后回撤 / 领先时长 / 首次兑现；不足 10 局只做观察，不给稳定预测。',
      action: sampleNote,
      slot: 'advantage',
    });
  }
  async function reviewHtml(signal) {
    const gameId = state.game;
    const [lossResult, advResult] = await Promise.allSettled([
      requestJson('/api/decision/loss', scopeQuery({ game: gameId }), signal),
      requestJson('/api/decision/advantage', scopeQuery(), signal),
    ]);
    const loss = lossResult.status === 'fulfilled' ? lossResult.value : null;
    const lossError = lossResult.status === 'rejected' ? lossResult.reason : null;
    const advantage = advResult.status === 'fulfilled' ? advResult.value : null;
    const advantageError = advResult.status === 'rejected' ? advResult.reason : null;
    const games = listOf(state.catalog && state.catalog.games);
    const game = games.find((item) => String(item.id) === String(gameId)) || null;
    const lossGame = loss && loss.game;
    const chains = listOf(lossGame && lossGame.chains).length ? lossGame.chains : listOf(loss && loss.rows);
    const advGame = listOf(advantage && advantage.games).find((item) => String(item.id ?? item.game) === String(gameId)) || null;
    const blocks = [reviewHead(game, loss, advantage, advGame)];
    /* 本局：经济差时间轴 + 关键链候选 */
    let reviewBody = '';
    if (lossError) {
      reviewBody = errorCard('本局经济与关键链读取失败', lossError);
    } else if (!loss || loss.available === false) {
      reviewBody = emptyCard('这一局没有可用的复盘数据', esc((loss && loss.reason) || '缺官方回放或经济采样。'));
    } else {
      const timeline = economyChart(lossGame && lossGame.series, chains, lossGame && lossGame.duration);
      reviewBody = `<div class="dx-review-grid">
        <div class="dx-review-chart"><h3 class="dx-subhead">经济差时间轴 · 我方视角</h3>${timeline}</div>
        <div class="dx-review-chains"><h3 class="dx-subhead">关键链候选 · ${fmt(chains.length)} 段</h3>${chainsHtml(chains, lossGame || game || { id: gameId })}</div>
      </div>${note(esc((loss && loss.note) || '经济点按索引均匀铺到时间轴；关键链只列候选事件，不证明因果。'))}`;
    }
    blocks.push(block('本局经济差与关键链', reviewBody, {
      noteText: '阴影为候选损失窗口；时间轴上的死亡 / 团战 / 资源标记可点，跳到对应链卡。',
      slot: 'review',
    }));
    /* 跨局：优势保持与回撤 + 分位带（同块左右排，控制单页高度） */
    if (advantageError) {
      blocks.push(block('优势保持与回撤', errorCard('优势分析读取失败', advantageError), { slot: 'advantage' }));
    } else if (!advantage || advantage.available === false) {
      blocks.push(block('优势保持与回撤', emptyCard('当前范围没有可用的优势分析', esc((advantage && advantage.reason) || '缺胜负面板或经济点。')), { slot: 'advantage' }));
    } else {
      blocks.push(advantageBlock(advantage));
    }
    return blocks.join('');
  }

  /* ── 赛前备战 ─────────────────────────────────────────────────── */
  function prepToolbar(opening) {
    const selected = (opening && opening.selected) || {};
    const opponents = opponentsSorted();
    const opponentSelect = `<label class="dx-field"><span>研究对手</span><select data-dx-prep-opponent aria-label="选择对手">
      <option value="">全部对手（本批）</option>${opponents.map((item) => `<option value="${esc(item.id)}"${item.id === state.prepOpponent ? ' selected' : ''}>${esc(item.name || item.id)}（回放 ${fmt(item.replayGames)} 局）</option>`).join('')}
    </select></label>`;
    const laneSelect = `<label class="dx-field"><span>分路</span><select data-dx-prep-lane aria-label="对手分路">
      <option value="">全部分路</option>${LANES.map((lane) => `<option value="${esc(lane)}"${lane === state.prepLane ? ' selected' : ''}>${esc(lane)}</option>`).join('')}
    </select></label>`;
    const sample = num(selected.replayGames) ?? 0;
    const isAll = !selected.id;
    const sampleBadge = isAll
      ? badge('整批对手聚合')
      : selected.enough === false || sample < 3 ? badge('样本不足 · 仅单局观察') : `<span class="dx-ok">回放 ${fmt(sample)} 局</span>`;
    const selectedText = selected.name || '全部对手（本批）';
    return `<div class="dx-toolbar">${opponentSelect}${laneSelect}${sampleBadge}<span class="dx-toolbar-meta">当前：${esc(selectedText)} · 回放 ${fmt(selected.replayGames)} 局 · 有位置 ${fmt(selected.positionGames)} 局</span></div>`;
  }
  function routeCard(route, index) {
    const routeId = `route-${index}`;
    const count = num(route && route.count) ?? 0;
    const points = routePoints(route);
    const enough = route && route.enough !== false && count >= 3;
    const zones = listOf(route && route.zoneSequence);
    const next = (route && route.nextObjective) || {};
    const rep = (route && route.representative) || {};
    return `<button type="button" class="dx-route-card" data-dx-route-card="${routeId}" aria-pressed="false">
      <span class="dx-route-head"><b>${esc((route && route.lane) || '分路未知')}</b><span class="dx-route-count">${fmt(count)} 次</span>${enough ? '' : badge('样本不足')}</span>
      <span class="dx-route-zones">${zones.length ? esc(zones.join(' → ')) : '路线分区未提供'}</span>
      <span class="dx-route-meta">代表路线：${esc(rep.name || rep.player || '选手')} · ${esc(rep.hero || '英雄未标注')}${rep.label ? ' · ' + esc(rep.label) : ''}</span>
      <span class="dx-route-meta">后续首个资源：${esc(next.name || '—')}${has(next.minutes) ? ` · ${fmt(next.minutes, 1)} 分` : ''}${num(next.count) !== null ? `（${fmt(next.count)} 局）` : ''}${points.length ? ` · 路线点 ${fmt(points.length)} 个` : ''}</span>
    </button>`;
  }
  function bpSummaryCard(bp) {
    if (!bp || bp.available === false) return '';
    const suggestions = listOf(bp.team && bp.team.suggestions).slice(0, 2);
    const bans = listOf(bp.bans && bp.bans.overall).slice(0, 4);
    const thinLanes = listOf(bp.team && bp.team.thinLanes);
    const coverage = bp.coverage || {};
    const chips = [
      bans.length ? `对手常禁：${bans.map((item) => item.hero).join(' / ')}` : '',
      thinLanes.length ? `可用池偏薄：${thinLanes.join(' / ')}` : '',
      `${fmt(coverage.panelGames)} 局面板 · 稳定样本 ${fmt(coverage.players)} 人（另有 ${fmt(coverage.rotatedPlayers)} 个轮换昵称）`,
    ].filter(Boolean);
    return `<div class="dx-bp-summary">
      <div class="dx-bp-head"><b>BP 抗针对 · 本周补练建议</b><a href="#bpcounter">看完整 BP 抗针对 ${icon('arrow')}</a></div>
      ${suggestions.length ? `<ul>${suggestions.map((text) => `<li>${esc(text)}</li>`).join('')}</ul>` : '<p class="dx-note">当前没有触发补练建议；去 BP 页看完整英雄池。</p>'}
      <div class="dx-bp-chips">${chips.map((text) => `<span>${esc(text)}</span>`).join('')}</div>
    </div>`;
  }

  async function prepHtml(signal) {
    const query = new URLSearchParams();
    if (state.scope.from) query.set('from', state.scope.from);
    if (state.scope.to) query.set('to', state.scope.to);
    if (state.prepOpponent) query.set('opponent', state.prepOpponent);
    if (state.prepLane) query.set('lane', state.prepLane);
    const bpQuery = new URLSearchParams();
    if (state.scope.from) bpQuery.set('from', state.scope.from);
    if (state.scope.to) bpQuery.set('to', state.scope.to);
    if (state.prepOpponent) bpQuery.set('opponent', state.prepOpponent);
    query.set('side', 'enemy');
    const [opening, bp] = await Promise.all([
      requestJson('/api/decision/opening', '?' + query.toString(), signal),
      requestJson('/api/decision/bp', '?' + bpQuery.toString(), signal).catch(() => null),
    ]);
    const bpCard = bpSummaryCard(bp);
    if (!opening || opening.available === false) {
      return `${bpCard}${block('赛前备战 · 对手开局观察', prepToolbar(opening) + emptyCard('当前范围没有可用的开局观察', esc((opening && opening.reason) || '缺位置采样（positions.json）。')), { noteText: '只统计平台收录的回放，不能推断对手全部习惯。', slot: 'prep' })}`;
    }
    const selected = opening.selected || {};
    const coverage = opening.coverage || {};
    const heat = opening.heat || {};
    const allRoutes = listOf(opening.routes);
    /* 聚合视图可能有上百个路线簇：按出现次数取前 8 条，避免把页面拉成几千像素。
       完整条数写在标题里，不隐藏「还有多少」。 */
    const routes = [...allRoutes].sort((a, b) => (num(b.count) || 0) - (num(a.count) || 0)).slice(0, 8);
    const routeTotal = allRoutes.length;
    const sample = num(selected.games) ?? num(selected.replayGames) ?? 0;
    const banner = selected.enough === false || sample < 3
      ? `<div class="dx-banner is-warn">该对手当前只有 ${fmt(num(selected.replayGames) ?? sample)} 局回放：下面是单局路线观察，不输出固定开局套路。</div>`
      : '';
    const coverageChips = metrics([
      { label: '路线簇', value: `${fmt(routeTotal)} 个`, noteText: `原始路线 ${fmt(coverage.routes)} 条 · 跳过 ${fmt(coverage.skippedRoutes)} 条` },
      { label: '本批对局', value: `${fmt(coverage.games)} 局`, noteText: `有位置 ${fmt(coverage.positionGames)} 局` },
      { label: '热区采样', value: `${fmt(heat.total)} 点`, noteText: `${fmt(heat.games)} 局 · 0–4 分钟` },
      { label: '坐标', value: coverage.calibrated ? '已定标' : '未定标', noteText: coverage.calibrated ? '单位=地图宽度比例' : '相对坐标，只做同批比较' },
    ]);
    const heatBody = `<div class="dx-heat-layout">
      <div class="dx-heat-col">
        ${heatChart(heat, routes)}
        ${note(esc(coverage.calibrated ? '坐标按本批位置分位定标；九宫格只是方位描述，不代表草丛或视野。' : '坐标未定标：位置为回放相对坐标并归一化到 0–1，只用于同批对局之间的相对比较。'))}
      </div>
      <div class="dx-route-col">
        <div class="dx-route-list-head"><span>路线簇 · 共 ${fmt(routeTotal)} 个${routeTotal > routes.length ? `，按次数展示前 ${routes.length} 个` : ''}</span><span class="dx-muted">点卡片在地图上高亮</span></div>
        <div class="dx-route-list">${routes.map(routeCard).join('') || '<div class="dx-sub-empty">当前筛选下还没有成簇的路线。</div>'}</div>
      </div>
    </div>`;
    return `${bpCard}${banner}${block('赛前备战 · 对手开局观察', prepToolbar(opening) + coverageChips + heatBody + note(esc(listOf(opening.notes).join(' ') || '仅收录本批回放；每名对手样本不足时只做单局观察。')), {
      noteText: '开局 0–4 分钟对手位置热区与代表路线；只描述本批收录回放，不能推断全部习惯。',
      slot: 'prep',
    })}`;
  }

  /* ── 选手研究 ─────────────────────────────────────────────────── */
  function anomalyKind(anomaly) {
    const kind = String((anomaly && anomaly.kind) || '');
    if (KIND_TEXT[kind]) return KIND_TEXT[kind];
    if (/death/i.test(kind)) return '发育路死亡偏多';
    if (/gold|damage/i.test(kind)) return '高经济低输出';
    return '待复核';
  }
  function anomalyList(anomalies) {
    const list = listOf(anomalies);
    if (!list.length) {
      return emptyCard('当前范围没有达到复核线的条目', '高经济低输出与发育路死亡都未触发复核线；不硬凑清单。');
    }
    const rows = list.slice(0, ANOMALY_LIMIT).map((anomaly) => `<div class="dx-anom">
      <div class="dx-anom-head"><b>${esc(anomaly.name || anomaly.playerId || '选手')}</b><span>${esc(anomaly.lane || '分路未标注')} · ${esc(anomaly.hero || '英雄未标注')}</span>${badge(anomalyKind(anomaly))}</div>
      <p>${esc(anomaly.text || '—')}</p>
      <div class="dx-anom-foot"><span>${esc(anomaly.date || '日期未知')} · ${esc(anomaly.opponentName || '对手待命名')} · ${esc(resultText(anomaly.result))}</span>${anomaly.seq ? `<a href="${esc(route('match', anomaly.seq))}">回到对局 ${icon('arrow')}</a>` : ''}</div>
    </div>`).join('');
    const more = list.length > ANOMALY_LIMIT ? `<p class="dx-note">共 ${fmt(list.length)} 条，列表中显示前 ${ANOMALY_LIMIT} 条。</p>` : '';
    return `<div class="dx-anom-list">${rows}</div>${more}`;
  }
  function byLaneBlock(resource) {
    const rows = listOf(resource && resource.byLane);
    if (!rows.length) return emptyCard('当前筛选没有分路均值', '终局面板缺金币或伤害字段。');
    const efficiency = listOf(resource && resource.efficiency);
    const effOf = (lane) => {
      const hit = efficiency.find((item) => item && item.lane === lane);
      return hit ? num(hit.ratio) : null;
    };
    const compact = rows.map((row) => [
      esc(row.lane || '分路未标注'),
      fmt(row.n),
      pctCell(row.goldShare),
      pctCell(row.heroDamageShare),
      pctCell(row.towerShare),
      fmt(effOf(row.lane), 2),
    ]);
    const full = rows.map((row) => [
      esc(row.lane || '分路未标注'),
      fmt(row.n),
      pctCell(row.goldShare),
      pctCell(row.heroDamageShare),
      pctCell(row.towerShare),
      pctCell(row.controlShare),
      pctCell(row.healShare),
      fmt(row.deaths, 1),
      fmt(row.gpm, 1),
    ]);
    const metricsNote = (resource && resource.metrics && resource.metrics.note)
      || '经济=营地 battleStats.money；英雄伤害=totalHeroHurtCnt；推塔=buildingDamage；damage 与 totalHeroHurtCnt 不混用。占比按同局同阵营五人合计，分路筛选不改变占比分母。';
    return `${table(['分路', 'n', '经济占比', '伤害占比', '推塔占比', '输出 / 经济'], compact)}
      ${note('占比按「同局同阵营五人合计」计算；分路筛选不改变占比分母。游走 / 辅助请改看控制与治疗，不按输出评价。')}
      <details class="dx-details"><summary>其余指标（控制 / 治疗 / 死亡 / GPM）</summary>${table(['分路', 'n', '经济占比', '伤害占比', '推塔占比', '控制占比', '治疗占比', '死亡', 'GPM'], full)}</details>
      ${note(esc(metricsNote))}`;
  }

  /* 散点交互：点选一个人次，下方给出这一局的完整证据；差距排行给出可行动排序。 */
  function playerPointDetail(player) {
    if (!player) {
      return `<div class="dx-point-card is-empty"><b>点一个点，看这一局的证据</b><span>散点用于发现异常人次；点选后会在这里给出对局、英雄、经济/输出/推塔/控制与来源。</span></div>`;
    }
    const gap = (num(player.goldShare) ?? 0) - (num(player.heroDamageShare) ?? 0);
    const meta = [player.date, player.opponentName ? '对阵 ' + player.opponentName : '', resultText(player.result)].filter(Boolean).join(' · ');
    const link = player.seq ? `<a class="control" href="${esc(route('match', player.seq))}">回到这一局 ${icon('arrow')}</a>` : '';
    return `<div class="dx-point-card">
      <div class="dx-point-head"><b>${esc(player.name || player.playerId || '选手')}</b><span>${esc(player.hero || '英雄未知')} · ${esc(player.lane || '分路未标注')}</span></div>
      <div class="dx-point-metrics">
        <div><span>经济占比</span><strong>${pct(player.goldShare)}</strong></div>
        <div><span>英雄伤害占比</span><strong>${pct(player.heroDamageShare)}</strong></div>
        <div><span>经济−输出差</span><strong class="${gap >= 5 ? 'is-warn' : ''}">${gap > 0 ? '+' : ''}${fmt(gap, 1)}pp</strong></div>
        <div><span>推塔占比</span><strong>${pct(player.towerShare)}</strong></div>
        <div><span>GPM</span><strong>${fmt(player.gpm, 1)}</strong></div>
        <div><span>死亡</span><strong>${fmt(player.deaths)}</strong></div>
        <div><span>控制</span><strong>${fmt(player.control)}s</strong></div>
        <div><span>治疗</span><strong>${fmt(player.heal)}</strong></div>
      </div>
      <div class="dx-point-foot"><span>${esc(meta || '来源待确认')}</span>${link}</div>
    </div>`;
  }

  function playerGapRanking(players) {
    const rows = listOf(players).map((player, index) => ({
      player,
      index,
      gap: (num(player.goldShare) ?? 0) - (num(player.heroDamageShare) ?? 0),
    })).filter((row) => row.player && num(row.player.goldShare) !== null && num(row.player.heroDamageShare) !== null)
      .sort((a, b) => b.gap - a.gap).slice(0, 6);
    if (!rows.length) return '';
    const max = Math.max(1, ...rows.map((row) => Math.abs(row.gap)));
    return `<div class="dx-gap-list"><div class="dx-gap-head"><b>经济 → 输出差距排行</b><span>只列差距最大的 6 人次；点击看证据</span></div>
      ${rows.map((row) => {
        const player = row.player;
        const active = state.selectedPlayerPoint === row.index ? ' is-active' : '';
        return `<button type="button" class="dx-gap-row${active}" data-dx-point="${row.index}">
          <span class="dx-gap-name">${esc(player.name || player.playerId || '选手')}<small>${esc(player.hero || '')} · ${esc(player.lane || '')}</small></span>
          <i><em style="width:${Math.round(Math.abs(row.gap) / max * 100)}%"></em></i>
          <b class="${row.gap >= 5 ? 'is-warn' : ''}">${row.gap > 0 ? '+' : ''}${fmt(row.gap, 1)}pp</b>
        </button>`;
      }).join('')}</div>`;
  }

  async function playerHtml(signal) {
    const resource = await requestJson('/api/decision/resource', scopeQuery({ side: 'own', lane: state.playerLane }), signal);
    if (!resource || resource.available === false) {
      return block('选手研究 · 资源分配', `<div class="dx-toolbar"><label class="dx-field"><span>分路</span><select data-dx-player-lane aria-label="选择分路"><option value="">全部分路</option>${LANES.map((lane) => `<option value="${esc(lane)}"${lane === state.playerLane ? ' selected' : ''}>${esc(lane)}</option>`).join('')}</select></label></div>${emptyCard('当前范围没有可用的资源分配样本', esc((resource && resource.reason) || '终局面板缺金币字段。'))}`, { noteText: '终局面板口径；只用于发现值得复核的资源配置，不评价选手。', slot: 'player' });
    }
    const players = listOf(resource.players);
    state.lastPlayers = players;
    const anomalies = listOf(resource.anomalies);
    const summary = resource.summary || {};
    const quadrant = resource.quadrant || {};
    const basis = resource.quadrantBasis === 'fixed' ? '20/20 固定分界' : `中位线 ${pct(quadrant.xSplit)} / ${pct(quadrant.ySplit)}`;
    const laneSelect = `<label class="dx-field"><span>分路</span><select data-dx-player-lane aria-label="选择分路"><option value="">全部分路</option>${LANES.map((lane) => `<option value="${esc(lane)}"${lane === state.playerLane ? ' selected' : ''}>${esc(lane)}</option>`).join('')}</select></label>`;
    const chips = metrics([
      { label: '选手行', value: `${fmt(players.length)} 条`, noteText: `涉及对局 ${fmt(summary.games)} 局 · ${fmt(summary.rows)} 行中筛出` },
      { label: '复核条目', value: `${fmt(anomalies.length)} 条`, noteText: `高经济低输出 ${fmt(summary.quadrantFlagCount)} · 发育路死亡 ${fmt(summary.deathAnomalyCount)}` },
      { label: '象限分界', value: esc(basis), noteText: '样本 <10 时用 20/20 固定分界' },
      { label: '样本', value: summary.smallSample ? '不足' : '可用', noteText: summary.smallSample ? '样本不足，仅供观察' : `n=${fmt(players.length)} 人次` },
    ]);
    const body = `<div class="dx-player-grid">
      <div class="dx-player-chart"><h3 class="dx-subhead">经济占比 × 英雄伤害占比</h3>${quadrantChart(players, quadrant, state.selectedPlayerPoint)}<div data-dx-point-detail>${playerPointDetail(state.selectedPlayerPoint === null ? null : players[state.selectedPlayerPoint])}</div>${playerGapRanking(players)}${note('中位线按当前样本计算；点大小＝推塔占比；点/差距行可点选，只用于发现待复核的资源分配，不评价选手。')}</div>
      <div class="dx-player-anoms"><h3 class="dx-subhead">复核清单 · 共 ${fmt(anomalies.length)} 条</h3>${anomalyList(anomalies)}</div>
    </div>`;
    return `${block('选手研究 · 资源分配与发育效率', `<div class="dx-toolbar">${laneSelect}<span class="dx-toolbar-meta">经济占比 / 伤害占比均按「同局同阵营五人合计」计算</span></div>${chips}${body}`, {
      noteText: '终局面板（逐人终局）口径；只发现值得复核的资源配置，不评价选手、不排名。',
      slot: 'player',
    })}
    ${block('分路均值与效率', byLaneBlock(resource), { noteText: '同分路内看「输出占比 / 经济占比」，不跨分路排名：各分路职责不同。', slot: 'lanes' })}`;
  }

  /* ── 训练验证 ─────────────────────────────────────────────────── */
  function trainingTable(effectData) {
    const results = listOf(effectData && effectData.results);
    if (!results.length) {
      return emptyCard('还没有训练干预记录', '工作台登记训练目标后，系统会把干预前后各至少 5 条本队营地记录放在一起比较。', `<a class="control" href="#effect">去训练效果页 ${icon('arrow')}</a>`);
    }
    const rows = results.map((result) => {
      const effect = (result && result.effect) || {};
      const goal = esc((result && result.goal) || '训练目标');
      const label = esc(effect.label || (result && result.metric) || '观察指标');
      if (!effect.available) {
        return `<tr><td>${goal}</td><td>${label}</td><td colspan="6" class="dx-muted">${esc(effect.reason || '样本不足，暂不计算。')}</td></tr>`;
      }
      const preMean = num(effect.preMean);
      const postMean = num(effect.postMean);
      const delta = preMean !== null && postMean !== null ? postMean - preMean : null;
      const target = num(result && result.target);
      const achieve = target !== null && target !== 0 && postMean !== null ? (postMean / target) * 100 : null;
      return `<tr>
        <td>${goal}</td>
        <td>${label}</td>
        <td>${fmt(preMean, 2)}</td>
        <td>${fmt(postMean, 2)}</td>
        <td>${has(delta) ? signed(delta, 2) : '—'}</td>
        <td>${fmt(num(effect.effectSize), 2)}</td>
        <td>${fmt(effect.nPre)} → ${fmt(effect.nPost)} 人次</td>
        <td>${has(achieve) ? pct(achieve) : '—'}</td>
      </tr>`;
    }).join('');
    return `${table(['目标', '指标', '干预前', '干预后', '差值', '效应量 d', '样本', '达成率'], rows)}
      ${note('达成率＝干预后均值 / 目标值（仅目标为数值时显示）；目标方向未登记，不做达标判断。效应量为描述性对比，不是因果结论。')}`;
  }
  async function trainingHtml(signal) {
    const effectData = await requestJson('/api/v3/effect', '', signal);
    const results = listOf(effectData && effectData.results);
    const usable = results.filter((result) => result && result.effect && result.effect.available);
    const meanEffect = usable.length
      ? usable.reduce((sum, result) => sum + (num(result.effect.effectSize) || 0), 0) / usable.length
      : null;
    const banner = `<div class="dx-banner is-info"><b>C 级</b> 训练目标与复盘问题的联动尚未打通；这里只做干预前后的描述对比，不宣称因果。</div>`;
    const chips = metrics([
      { label: '干预记录', value: `${fmt(results.length)} 条`, noteText: '训练目标' },
      { label: '可对比', value: `${fmt(usable.length)} 条`, noteText: '两侧样本 ≥ 5 人次' },
      { label: '平均效应量', value: meanEffect === null ? '—' : fmt(meanEffect, 2), noteText: 'Cohen’s d · 描述性对比' },
      { label: '最近一条', value: esc((results[0] && results[0].start_date) || '—'), noteText: esc((results[0] && results[0].goal) || '') },
    ]);
    return `${banner}${block('训练验证 · 干预前后对照', chips + trainingTable(effectData) + (effectData && effectData.dateNote ? note(esc(effectData.dateNote)) : '') + note('训练验证来自训练登记与本队营地记录，不受上方日期 / 对手 / 结果筛选影响。'), {
      noteText: '每侧至少 5 条有效人次才计算效应量；样本不足会写明原因。',
      action: `<a class="card-link" href="#effect">训练效果页 ${icon('arrow')}</a>`,
      slot: 'training',
    })}`;
  }

  /* ── 交互 ─────────────────────────────────────────────────────── */
  function updateHash({ replace = false } = {}) {
    const params = new URLSearchParams();
    if (state.tab === 'review' && state.game) params.set('game', state.game);
    /* 只有显式指定过对手才把 opponent 写进 URL；切 tab 时保持 #decision/prep 干净。 */
    if (state.tab === 'prep' && state.prepOpponent && state.prepOpponentInUrl) params.set('opponent', state.prepOpponent);
    const search = params.toString();
    const hash = '#decision/' + state.tab + (search ? '?' + search : '');
    if (location.hash === hash) return;
    try {
      if (replace) history.replaceState(null, '', hash);
      else history.pushState(null, '', hash);
    } catch {
      /* 嵌入式浏览器禁用 pushState 时退回 hash 赋值（会触发整页重挂载，仍能到正确 tab） */
      try { location.hash = hash; } catch { /* 忽略 */ }
    }
  }
  function selectTab(next) {
    if (!TAB_IDS.includes(next) || next === state.tab) return;
    state.tab = next;
    syncControls();
    updateHash();
    const tabs = state.container && state.container.querySelector('.dx-tabs');
    if (tabs) {
      const top = tabs.getBoundingClientRect().top + window.scrollY - 14;
      if (top > 0) window.scrollTo({ top, behavior: 'smooth' });
    }
    loadTab();
  }
  function focusChain(index) {
    const container = state.container;
    if (!container) return;
    const card = container.querySelector('[data-dx-chain-card="' + index + '"]');
    if (!card) return;
    container.querySelectorAll('[data-dx-chain-card].is-active').forEach((node) => node.classList.remove('is-active'));
    card.classList.add('is-active');
    if (card.tagName === 'DETAILS') card.open = true;
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  function toggleRoute(routeId) {
    const container = state.container;
    if (!container) return;
    const cards = container.querySelectorAll('[data-dx-route-card]');
    const paths = container.querySelectorAll('[data-dx-route]');
    const card = container.querySelector('[data-dx-route-card="' + routeId + '"]');
    const wasActive = Boolean(card && card.classList.contains('is-active'));
    cards.forEach((node) => {
      const active = !wasActive && node.dataset.dxRouteCard === routeId;
      node.classList.toggle('is-active', active);
      node.setAttribute('aria-pressed', String(active));
    });
    paths.forEach((node) => {
      const match = node.dataset.dxRoute === routeId;
      node.classList.toggle('is-active', !wasActive && match);
      node.classList.toggle('is-dim', !wasActive && !match);
    });
  }
  function resetScope() {
    state.scope = { from: '', to: '', opponent: '', result: '' };
    showScopeError('');
    syncControls();
    updateHash({ replace: true });
    loadTab();
  }
  function onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const tabHit = target.closest('[data-dx-tab]');
    if (tabHit) { selectTab(tabHit.dataset.dxTab); return; }
    if (target.closest('[data-dx-action="refresh"]')) { refreshAll(); return; }
    if (target.closest('[data-dx-refresh]')) { refreshAll(); return; }
    if (target.closest('[data-dx-action="reset-scope"]')) { resetScope(); return; }
    if (target.closest('[data-dx-retry]')) { loadTab(); return; }
    const chainHit = target.closest('[data-dx-chain]');
    if (chainHit) { focusChain(chainHit.dataset.dxChain); return; }
    const routeHit = target.closest('[data-dx-route-card]');
    if (routeHit) { toggleRoute(routeHit.dataset.dxRouteCard); return; }
    const pointHit = target.closest('[data-dx-point]');
    if (pointHit) {
      selectPlayerPoint(Number(pointHit.dataset.dxPoint));
    }
  }
  function selectPlayerPoint(index) {
    state.selectedPlayerPoint = Number.isFinite(index) ? index : null;
    const container = state.container;
    if (!container) return;
    container.querySelectorAll('[data-dx-point]').forEach((node) => {
      const hit = Number(node.dataset.dxPoint) === state.selectedPlayerPoint;
      node.classList.toggle('is-selected', hit);
      if (node.classList.contains('dx-gap-row')) node.classList.toggle('is-active', hit);
    });
    const host = container.querySelector('[data-dx-point-detail]');
    if (host) {
      const players = listOf(state.lastPlayers);
      host.innerHTML = playerPointDetail(state.selectedPlayerPoint === null ? null : players[state.selectedPlayerPoint]);
    }
  }
  function onKeyDown(event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const chainHit = target.closest('[data-dx-chain]');
    if (chainHit) {
      event.preventDefault();
      focusChain(chainHit.dataset.dxChain);
      return;
    }
    const pointHit = target.closest('[data-dx-point]');
    if (pointHit) {
      event.preventDefault();
      selectPlayerPoint(Number(pointHit.dataset.dxPoint));
    }
  }
  function onChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const scopeKey = target.dataset.dxScope;
    if (scopeKey === 'from' || scopeKey === 'to') {
      const value = String(target.value || '').trim();
      state.scope[scopeKey] = value;
      if (state.scope.from && state.scope.to && state.scope.from > state.scope.to) {
        showScopeError('开始日期不能晚于结束日期。');
        return;
      }
      showScopeError('');
      syncControls();
      loadTab();
      return;
    }
    if (scopeKey === 'opponent') {
      state.scope.opponent = String(target.value || '');
      syncControls();
      updateHash({ replace: true });
      loadTab();
      return;
    }
    if (scopeKey === 'result') {
      state.scope.result = String(target.value || '');
      syncControls();
      loadTab();
      return;
    }
    if (target.dataset.dxGame !== undefined) {
      state.game = String(target.value || '');
      updateHash({ replace: true });
      loadTab();
      return;
    }
    if (target.dataset.dxPlayerLane !== undefined) {
      state.playerLane = String(target.value || '');
      state.selectedPlayerPoint = null;
      loadTab();
      return;
    }
    if (target.dataset.dxPrepLane !== undefined) {
      state.prepLane = String(target.value || '');
      loadTab();
      return;
    }
    if (target.dataset.dxPrepOpponent !== undefined) {
      state.prepOpponent = String(target.value || '');
      state.prepOpponentInUrl = true;
      syncControls();
      updateHash({ replace: true });
      loadTab();
    }
  }
  function bind(container) {
    if (container.dataset.dxBound === '1') return;
    container.dataset.dxBound = '1';
    container.addEventListener('click', onClick);
    container.addEventListener('change', onChange);
    container.addEventListener('keydown', onKeyDown);
  }

  /* ── 入口 ─────────────────────────────────────────────────────── */
  function normalizeTab(value) {
    return TAB_IDS.includes(value) ? value : 'review';
  }
  function seedScope() {
    const scope = { from: '', to: '', opponent: '', result: '' };
    try {
      const params = new URLSearchParams(currentQuery() || '');
      scope.from = params.get('from') || '';
      scope.to = params.get('to') || '';
    } catch { /* 取不到全局筛选时就用空范围 */ }
    return scope;
  }
  function mount(container, nextRoute) {
    if (!container) return;
    state.gen += 1;
    const gen = state.gen;
    state.container = container;
    state.tab = normalizeTab(nextRoute && nextRoute.key);
    state.catalog = null;
    state.cache = new Map();
    state.catalogAbort?.abort();
    state.tabAbort?.abort();
    state.scope = seedScope();
    state.game = '';
    state.prepOpponent = '';
    state.prepOpponentInUrl = false;
    state.prepLane = '';
    state.playerLane = '';
    state.urlGame = '';
    try { state.urlGame = new URLSearchParams(location.hash.split('?')[1] || '').get('game') || ''; } catch { state.urlGame = ''; }
    state.catalogAbort = new AbortController();
    container.innerHTML = '<div class="page dx-page"><div class="dx-loading">正在读取赛训决策数据…</div></div>';
    bind(container);
    loadCatalog(gen);
  }

  return { mount };
}
