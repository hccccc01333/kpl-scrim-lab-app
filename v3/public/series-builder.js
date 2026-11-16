/* 系列赛编组中心（V2.1，route #series-builder）。

   2026-11 重构：一次 bootstrap 取数、按天折叠、搜索/对手筛选、行内选择、
   底部操作条、系列赛卡收纳式菜单。交互契约（docs/series_builder.md §交互）：
   - 未编组对局按日分组、一行一局，整行是选择单元；字段与「对局档案」同一套读法。
   - 点行选中、Shift 点首尾连选；Esc 取消；Ctrl+Z 撤销；每天可「全选本日」。
   - 自动建议只做候选（服务端不落库），确认后才建系列赛。
   - 所有操作只改系列赛关系，原始对局数据不动；撤销通过逆向 API 完成。
   - 一局已属其他系列赛时标红阻止，需先移出再编组（409 带占用方）。

   性能约定：
   - 首屏只请求 /api/series/bootstrap（轻量向量 + 系列赛 + 候选），与
     /api/metadata 并行；不再并发打两个全量向量接口。
   - 日期默认折叠，只渲染展开的一天；每天默认 24 行，按需加载更多。
   - 写操作直接用返回的 series 更新本地状态，不再全量重取。 */

const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

const BO_LIST = [3, 5, 7];
const DAY_PAGE = 24;
const PAGE_CACHE_TTL = 60000;
const WRITE_BUTTONS = '[data-sb-confirm],[data-sb-append-confirm],[data-sb-confirm-suggest],'
  + '[data-sb-set-bo],[data-sb-mark],[data-sb-delete-confirm],[data-sb-delete],[data-sb-move],'
  + '[data-sb-remove],[data-sb-set-bo-series],[data-sb-append],[data-sb-edit],[data-sb-bulk-suggest]';

/* 模块级缓存：路由切走再回来先出内容，再静默校正。 */
let cachedPayload = null;
let cachedAt = 0;
let toastSeq = 0;

const UI_KEY = 'training-series-builder-ui-v1';
function readUIState() {
  try {
    const value = JSON.parse(localStorage.getItem(UI_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}
function writeUIState(value) {
  try { localStorage.setItem(UI_KEY, JSON.stringify(value)); } catch { /* 隐私模式忽略 */ }
}

const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
const keyOf = (v) => String(v && v.key != null ? v.key : '');
const dateOf = (v) => String((v && v.date) || '').slice(0, 10) || '未知日期';
const sortKeyOf = (v) => `${dateOf(v)}T${String(v && v.clock || '99:99').padStart(5, '0')}|${keyOf(v)}`;
const ascTime = (a, b) => sortKeyOf(a).localeCompare(sortKeyOf(b));
const descTime = (a, b) => sortKeyOf(b).localeCompare(sortKeyOf(a));
const WEEKDAYS = '日一二三四五六';

function weekdayOf(dateText) {
  const d = new Date(dateText + 'T12:00:00');
  return Number.isNaN(d.getTime()) ? '' : `周${WEEKDAYS[d.getDay()]}`;
}

function clockText(clock) { return clock || '--:--'; }

function sparkIcon() {
  return '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M12 3.2l1.7 5.1 5.1 1.7-5.1 1.7L12 16.8l-1.7-5.1L5.2 10l5.1-1.7z"/>'
    + '<path d="M18.2 15.4l.8 2.3 2.3.8-2.3.8-.8 2.3-.8-2.3-2.3-.8 2.3-.8z"/></svg>';
}

export function createSeriesBuilder({ esc, fmt, diff, time, portrait, route, icon }) {
  let root = null;
  let generation = 0;
  let controller = null;
  let searchTimer = null;
  let loadToken = 0;
  let busyButtons = [];
  const restored = readUIState();
  const restoredFilter = restored.filter && typeof restored.filter === 'object' ? restored.filter : {};

  const state = {
    loaded: false, loading: false, error: '',
    vectors: [], byKey: new Map(),
    series: [], memberOf: new Map(),
    suggestions: [], blocked: [],
    selection: new Set(), anchor: null,
    bestOf: 0, fixedMode: false,
    appendTo: null, editId: null, menuId: null, dangerId: null, dragGame: null,
    busy: false, undoStack: [],
    openDays: new Set(Array.isArray(restored.openDays) ? restored.openDays : []),
    manualOpen: new Set(Array.isArray(restored.manualOpen) ? restored.manualOpen : []),
    openReady: Boolean(restored.openReady),
    seriesOpen: new Set(Array.isArray(restored.seriesOpen) ? restored.seriesOpen : []),
    dayLimit: new Map((Array.isArray(restored.dayLimit) ? restored.dayLimit : [])
      .filter((pair) => Array.isArray(pair) && typeof pair[0] === 'string' && Number.isFinite(Number(pair[1])))
      .map(([date, count]) => [date, Math.max(DAY_PAGE, Number(count))])),
    filter: {
      q: typeof restoredFilter.q === 'string' ? restoredFilter.q : '',
      opponent: typeof restoredFilter.opponent === 'string' ? restoredFilter.opponent : '',
      reviewOnly: Boolean(restoredFilter.reviewOnly),
      qualityOnly: Boolean(restoredFilter.qualityOnly),
    },
    showSuggest: typeof restored.showSuggest === 'boolean' ? restored.showSuggest : false,
    bulkConfirm: false,
    counts: { ungrouped: 0, groupedGames: 0 },
  };
  if (state.filter.reviewOnly) state.filter.qualityOnly = false;

  /* ───────────────────────── 数据 ───────────────────────── */
  function applySeries(series) {
    state.series = series.slice().sort((a, b) => String(a.startAt || '').localeCompare(String(b.startAt || '')));
    state.memberOf = new Map();
    for (const s of state.series) {
      for (const g of s.games || []) {
        state.memberOf.set(String(g.matchKey), { seriesId: s.id, gameIndex: g.gameIndex, series: s });
      }
    }
    state.counts.groupedGames = state.memberOf.size;
  }

  function applyPayload(payload) {
    state.bulkConfirm = false;
    const vectors = (payload && payload.vectors) || [];
    state.vectors = vectors.slice().sort(descTime);
    state.byKey = new Map(vectors.map((v) => [keyOf(v), v]));
    applySeries((payload && payload.series) || []);
    state.suggestions = (payload && payload.suggestions) || [];
    state.blocked = (payload && payload.blocked) || [];
    syncReviewFilter();
    syncQualityFilter();
    state.counts.ungrouped = state.vectors.filter((v) => !state.memberOf.has(keyOf(v))).length;
    /* 数据刷新后把已失效的选区 / 已入组局清掉，避免确认时撞 409。 */
    state.selection = new Set([...state.selection].filter((k) => state.byKey.has(k) && !state.memberOf.has(k)));
    if (state.selection.size) state.selection = new Set(orderKeys([...state.selection]));
    else state.anchor = null;
  }

  function cachePayload() {
    cachedPayload = {
      vectors: state.vectors, series: state.series,
      suggestions: state.suggestions, blocked: state.blocked,
    };
    cachedAt = Date.now();
  }

  function saveUIState() {
    if (!state.loaded) return;
    writeUIState({
      filter: state.filter,
      openDays: [...state.openDays],
      manualOpen: [...state.manualOpen],
      seriesOpen: [...state.seriesOpen],
      dayLimit: [...state.dayLimit.entries()],
      openReady: state.openReady,
      showSuggest: state.showSuggest,
    });
  }

  async function load({ silent = false } = {}) {
    if (!root) return;
    const gen = ++generation;
    const token = ++loadToken;
    controller?.abort();
    controller = new AbortController();
    state.loading = true;
    state.error = '';
    if (!silent) render();
    try {
      const response = await fetch(`${API_BASE}/api/series/bootstrap`, {
        signal: controller.signal, cache: 'no-store',
      });
      if (gen !== generation) return;
      if (!response.ok) throw new Error(`加载失败（${response.status}）`);
      const payload = await response.json();
      if (gen !== generation) return;
      applyPayload(payload);
      cachePayload();
      state.loaded = true;
      state.loading = false;
      render();
    } catch (error) {
      if (gen !== generation || (error && error.name === 'AbortError')) return;
      state.loading = false;
      if (!state.loaded) state.error = String((error && error.message) || error);
      else toast(`刷新失败：${(error && error.message) || error}`, 'error');
      render();
    } finally {
      if (token === loadToken) state.loading = false;
    }
  }

  async function api(path, options = {}) {
    const write = String(options.method || 'GET').toUpperCase() !== 'GET';
    if (write && state.busy) throw new Error('上一次操作还在处理，请稍候再试');
    if (write) setBusy(true);
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        cache: 'no-store', ...options,
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload && payload.detail;
        const message = typeof detail === 'object' && detail
          ? detail.message : (detail || payload.message || `请求失败（${response.status}）`);
        const error = new Error(message);
        error.occupied = typeof detail === 'object' && detail ? detail.occupied : null;
        error.status = response.status;
        throw error;
      }
      return payload;
    } finally {
      if (write) setBusy(false);
    }
  }

  /* ───────────────────────── 选区 ───────────────────────── */
  function orderKeys(keys) {
    return keys.slice().sort((a, b) => {
      const va = state.byKey.get(a) || { key: a }, vb = state.byKey.get(b) || { key: b };
      return sortKeyOf(va).localeCompare(sortKeyOf(vb));
    });
  }

  function selectionCapacity() {
    const target = state.series.find((s) => s.id === state.appendTo);
    return target ? Math.max(0, Number(target.bestOf) - (target.games || []).length) : 0;
  }

  function setSelection(keys) {
    let valid = keys.filter((k) => state.byKey.has(k));
    if (state.appendTo) {
      const capacity = selectionCapacity();
      if (valid.length > capacity) {
        valid = valid.slice(0, capacity);
        const target = state.series.find((s) => s.id === state.appendTo);
        toast(`BO${target ? target.bestOf : '?'} 还能加 ${capacity} 局，先改赛制或移出一局`, 'error');
      }
    }
    state.selection = new Set(orderKeys(valid));
    syncSelection();
    renderActionBar();
  }

  function toggleRow(key, event) {
    if (state.busy) return;
    const all = displayKeys();
    if (event && event.shiftKey && state.anchor && all.includes(state.anchor)) {
      const ia = all.indexOf(state.anchor), ib = all.indexOf(key);
      setSelection(all.slice(Math.min(ia, ib), Math.max(ia, ib) + 1));
      return;
    }
    const next = new Set(state.selection);
    if (next.has(key)) next.delete(key); else next.add(key);
    if (state.appendTo && next.size > state.selection.size && next.size > selectionCapacity()) {
      const target = state.series.find((s) => s.id === state.appendTo);
      toast(`BO${target ? target.bestOf : '?'} 还能加 ${selectionCapacity()} 局，先改赛制或移出一局`, 'error');
      return;
    }
    state.anchor = key;
    setSelection([...next]);
  }

  function clearSelection() {
    state.selection = new Set();
    state.anchor = null;
    state.bestOf = 0;
    state.fixedMode = false;
    syncSelection();
    renderActionBar();
  }

  function selectDay(date, rows) {
    const keys = rows.map(keyOf);
    const allSelected = keys.length > 0 && keys.every((k) => state.selection.has(k));
    const next = new Set(state.selection);
    for (const k of keys) { if (allSelected) next.delete(k); else next.add(k); }
    state.anchor = keys[0] || state.anchor;
    setSelection([...next]);
    render();
  }

  function recommendedBestOf(count) {
    if (count >= 6) return 7;
    if (count >= 4) return 5;
    return 3;
  }

  /* 选中的局数如果超过当前赛制，自动升到能装下的最小 BO；
     用户主动选过更大 BO（例如 3 局按 BO5 未完赛）则保持。 */
  function effectiveBestOf(count) {
    if (!state.bestOf) return recommendedBestOf(count);
    return count > state.bestOf ? recommendedBestOf(count) : state.bestOf;
  }

  function selectionWarnings(keys) {
    const warns = [];
    const items = keys.map((k) => state.byKey.get(k)).filter(Boolean);
    if (items.some((v) => !v.clock)) warns.push('部分对局缺少开赛时间，请确认局序');
    const opps = [...new Set(items.map((v) => v.opponent || ''))];
    if (opps.length > 1) warns.push('选中了不同对手：' + opps.filter(Boolean).join(' / '));
    if (opps.length === 1 && !opps[0]) warns.push('对手未标注，建议先在对局档案补齐');
    const versions = [...new Set(items.map((v) => v.version || ''))].filter(Boolean);
    if (versions.length > 1) warns.push('选中了不同版本：' + versions.join(' / '));
    if (keys.length > 7) warns.push('超过 7 局，无法确认为单个 BO');
    return warns;
  }

  /* 一行一局的“能不能直接编”的最低字段；缺哪项在行内用 ⚠ 提示。 */
  function rowIssues(v) {
    const issues = [];
    if (!v.opponent) issues.push('缺对手');
    if (!v.clock) issues.push('缺开赛时间');
    if (!(v.heroes || []).length && !(v.heroesFoe || []).length) issues.push('缺阵容');
    if (v.result !== 'win' && v.result !== 'loss') issues.push('缺结果');
    if (!v.duration) issues.push('缺时长');
    if (!Number.isFinite(v.killsOwn) || !Number.isFinite(v.killsFoe)) issues.push('缺比分');
    return issues;
  }

  function qualityCount() {
    return state.vectors.filter((v) => !state.memberOf.has(keyOf(v)) && rowIssues(v).length).length;
  }

  function syncQualityFilter() {
    if (state.filter.qualityOnly && !qualityCount()) state.filter.qualityOnly = false;
  }

  /* ───────────────────────── 筛选 / 分组 ───────────────────────── */
  function hasFilter() {
    return Boolean(state.filter.q || state.filter.opponent
      || state.filter.reviewOnly || state.filter.qualityOnly);
  }

  /* 日期允许 2026-11-08 / 11-08 / 11.08 / 11/08 几种写法。 */
  function dateTokens(date) {
    const text = String(date || '');
    const short = text.slice(5);
    return [text, text.replace(/-/g, '.'), text.replace(/-/g, '/'),
      short, short.replace(/-/g, '.'), short.replace(/-/g, '/')].filter(Boolean);
  }

  function rowMatches(v) {
    if (state.filter.reviewOnly) return false;
    if (state.filter.qualityOnly && !rowIssues(v).length) return false;
    const opp = state.filter.opponent;
    if (opp && (v.opponent || '') !== opp) return false;
    const q = state.filter.q.trim().toLowerCase();
    if (!q) return true;
    return [...dateTokens(v.date), v.clock, v.opponent, v.session, v.version,
      v.result === 'win' ? '胜' : v.result === 'loss' ? '负' : '']
      .filter(Boolean).join(' ').toLowerCase().includes(q);
  }

  function seriesMatches(s) {
    if (state.filter.reviewOnly && s.status !== 'needs_review') return false;
    if (state.filter.qualityOnly) return false;
    const opp = state.filter.opponent;
    if (opp && (s.opponent || '') !== opp) return false;
    const q = state.filter.q.trim().toLowerCase();
    if (!q) return true;
    return [...dateTokens(String(s.startAt || '').slice(0, 10)), s.opponent, s.completion,
      (s.ruleset && s.ruleset.name) || ''].filter(Boolean).join(' ').toLowerCase().includes(q);
  }

  function dateOfSeries(s) {
    const text = String(s.startAt || '').slice(0, 10);
    if (text) return text;
    const first = (s.games || [])[0];
    return first ? dateOf(state.byKey.get(String(first.matchKey)) || {}) : '未知日期';
  }

  function displayDays() {
    const buckets = new Map();
    const bucket = (date) => {
      if (!buckets.has(date)) buckets.set(date, { date, all: [], rows: [], series: [] });
      return buckets.get(date);
    };
    for (const v of state.vectors) bucket(dateOf(v)).all.push(v);
    for (const s of state.series) bucket(dateOfSeries(s)).series.push(s);
    const out = [];
    for (const item of buckets.values()) {
      item.all.sort(ascTime);
      item.rows = item.all.filter((v) => !state.memberOf.has(keyOf(v)) && rowMatches(v));
      item.series = item.series.filter(seriesMatches)
        .sort((a, b) => String(a.startAt || '').localeCompare(String(b.startAt || '')));
      if (!item.rows.length && !item.series.length) continue;
      out.push(item);
    }
    out.sort((a, b) => b.date.localeCompare(a.date));
    return out;
  }

  function displayKeys() {
    return displayDays().flatMap((d) => d.rows.map(keyOf));
  }

  function isOpen(date) { return state.openDays.has(date); }

  function syncOpenDays(days) {
    if (!days.length) { state.openDays = new Set(); return; }
    const valid = new Set(days.map((d) => d.date));
    state.openDays = new Set([...state.openDays].filter((d) => valid.has(d)));
    if (!state.openReady) {
      state.openDays = new Set([days[0].date]);
      state.manualOpen = new Set(state.openDays);
      state.openReady = true;
      return;
    }
    if (!state.openDays.size && !hasFilter()) {
      state.openDays = new Set([days[0].date]);
      state.manualOpen = new Set(state.openDays);
    }
  }

  function applyFilter(patch, { rebuild = false } = {}) {
    const before = hasFilter();
    state.filter = { ...state.filter, ...patch };
    const after = hasFilter();
    if (!before && after) state.manualOpen = new Set(state.openDays);
    if (before && !after) state.openDays = new Set(state.manualOpen);
    const days = displayDays();
    if (after) state.openDays = new Set(days.map((d) => d.date));
    if (rebuild) render();
    else { updateScope(days); renderWorkspace(days); }
  }

  /* ───────────────────────── 状态反馈 ───────────────────────── */
  function toast(text, kind = '', options = {}) {
    if (!root) return;
    let host = document.querySelector('[data-sb-toasts]');
    if (!host) {
      host = document.createElement('div');
      host.className = 'sb-toasts';
      host.dataset.sbToasts = '1';
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    const id = ++toastSeq;
    const node = document.createElement('div');
    node.className = `sb-toast${kind ? ' is-' + kind : ''}`;
    node.dataset.toast = String(id);
    node.innerHTML = `<span class="sb-toast-dot" aria-hidden="true"></span>
      <span class="sb-toast-text">${esc(text)}</span>
      ${options.undo ? '<button type="button" class="sb-toast-action" data-sb-toast-undo>撤销</button>' : ''}
      <button type="button" class="sb-toast-close" data-sb-toast-close aria-label="关闭提示">${icon('close')}</button>`;
    host.appendChild(node);
    const remove = () => {
      node.remove();
    };
    node.querySelector('[data-sb-toast-close]')?.addEventListener('click', remove);
    node.querySelector('[data-sb-toast-undo]')?.addEventListener('click', () => {
      remove();
      if (typeof options.undo === 'function') options.undo();
    });
    setTimeout(remove, options.timeout || (options.undo ? 10000 : 6000));
  }

  function pushUndo(op) {
    state.undoStack.push(op);
    if (state.undoStack.length > 20) state.undoStack.shift();
  }

  async function undo() {
    const op = state.undoStack.pop();
    if (!op) { toast('没有可撤销的操作'); return; }
    await undoOp(op);
  }

  function setBusy(flag) {
    state.busy = flag;
    if (!root) return;
    root.setAttribute('aria-busy', flag ? 'true' : 'false');
    for (const btn of busyButtons) {
      if (btn.isConnected) btn.disabled = btn.dataset.wasDisabled === '1';
    }
    busyButtons = [];
    if (flag) {
      root.querySelectorAll(WRITE_BUTTONS).forEach((btn) => {
        btn.dataset.wasDisabled = btn.disabled ? '1' : '0';
        btn.disabled = true;
        busyButtons.push(btn);
      });
    }
    const confirm = root.querySelector('[data-sb-confirm],[data-sb-append-confirm]');
    if (confirm) confirm.textContent = flag ? '处理中…' : (state.appendTo ? '加入系列赛' : '确认编组');
  }

  /* ───────────────────────── 渲染 ───────────────────────── */
  function latestDate() {
    return state.vectors.length ? dateOf(state.vectors[0]) : '—';
  }

  function opponentOptions() {
    const counts = new Map();
    for (const v of state.vectors) {
      if (state.memberOf.has(keyOf(v))) continue;
      const name = v.opponent || '';
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    const rows = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    if (state.filter.opponent && !counts.has(state.filter.opponent)) {
      rows.unshift([state.filter.opponent, 0]);
    }
    return rows;
  }

  function heroFaces(heroes, foe, eager = false) {
    const list = (heroes || []).slice(0, 5).filter(Boolean);
    if (!list.length) return '<span class="sb-faces is-empty">阵容待补</span>';
    const face = (name) => {
      const html = portrait(name);
      return eager ? html.replace('loading="lazy"', 'loading="eager"') : html;
    };
    return `<span class="sb-faces${foe ? ' is-foe' : ''}" title="${foe ? '对面' : '本队'}阵容">`
      + list.map(face).join('') + '</span>';
  }

  function completionLabel(s) {
    const map = { completed: '已完赛', open: '未完赛', interrupted: '中断', incomplete: '采集不完整' };
    /* “打满”按实际局数显示，而不是建组时选的 completionMode：
       BO3 打了 3 局就是打满，不管当时选的是标准还是固定；
       固定打满但只打了 3/5 局的系列赛不冒充“打满”。存储的 mode 不改。 */
    const fullLength = Number(s.bestOf) > 0 && (s.games || []).length >= Number(s.bestOf);
    return `${map[s.completion] || s.completion || '—'}${fullLength ? ' · 打满' : ''}`;
  }

  function seriesLabel(s) {
    return `BO${(s && s.bestOf) || '?'} · ${(s && s.opponent) || '对手待补'}`;
  }

  function menuHtml(s, editing, danger) {
    return `<div class="sb-menu" role="menu" data-sb-menu-panel="${esc(s.id)}">
      <span class="sb-menu-label">赛制</span>
      <div class="sb-menu-seg">${BO_LIST.map((bo) => `<button type="button" data-sb-set-bo-series="${esc(s.id)}" data-bo="${bo}"
        class="${Number(s.bestOf) === bo ? 'is-active' : ''}" role="menuitemradio" aria-checked="${Number(s.bestOf) === bo}">BO${bo}</button>`).join('')}</div>
      <div class="sb-menu-sep"></div>
      <button type="button" role="menuitem" data-sb-append="${esc(s.id)}">添加对局</button>
      <button type="button" role="menuitem" data-sb-edit="${esc(s.id)}">${editing ? '退出调整' : '调整局序 / 移出'}</button>
      ${s.status === 'needs_review' ? `<button type="button" role="menuitem" data-sb-mark-reviewed="${esc(s.id)}">标记已核实</button>` : ''}
      <button type="button" role="menuitem" data-sb-mark="${esc(s.id)}" data-mark="interrupted">标记中断</button>
      <button type="button" role="menuitem" data-sb-mark="${esc(s.id)}" data-mark="incomplete">标记采集不完整</button>
      <div class="sb-menu-sep"></div>
      <button type="button" role="menuitem" class="is-danger" data-sb-delete="${esc(s.id)}">${danger ? '确认删除编组？' : '删除编组'}</button>
    </div>`;
  }

  function seriesCard(s) {
    const games = (s.games || []).slice().sort((a, b) => a.gameIndex - b.gameIndex);
    const editing = state.editId === s.id;
    const menu = state.menuId === s.id;
    const danger = state.dangerId === s.id;
    const date = dateOfSeries(s);
    const rules = (s.ruleset && s.ruleset.name) || '';
    const score = s.score || { us: 0, them: 0 };
    const stateClass = ['interrupted', 'incomplete'].includes(s.completion) ? 'is-bad'
      : s.completion === 'completed' ? 'is-done' : 'is-open';
    return `<article class="sb-series${editing ? ' is-editing' : ''}" data-sb-series="${esc(s.id)}">
      <div class="sb-series-head">
        <span class="sb-bo">BO${esc(s.bestOf)}</span>
        <div class="sb-series-title">
          <b>${esc(s.opponent || '对手待补')}</b>
          <small>${esc(date)}${rules ? ' · ' + esc(rules) : ''}</small>
        </div>
        <span class="sb-series-score" aria-label="小局比分"><b>${fmt(score.us)}</b><i>:</i><b>${fmt(score.them)}</b></span>
        <span class="sb-state ${stateClass}">${esc(completionLabel(s))}</span>
        ${s.status === 'needs_review' ? '<span class="sb-review-badge">待核实</span>' : ''}
        <a class="sb-series-open" href="${esc(route('cross', 'series/' + s.id))}">分析 ${icon('arrow')}</a>
        <button type="button" class="sb-iconbtn" data-sb-menu="${esc(s.id)}"
          aria-label="更多系列赛操作" aria-expanded="${menu}">${icon('menu')}</button>
      </div>
      <div class="sb-series-games" role="list">
        ${games.map((g) => {
          const v = state.byKey.get(String(g.matchKey)) || {};
          const res = v.result === 'win' ? 'win' : v.result === 'loss' ? 'loss' : '';
          if (editing) {
            return `<span class="sb-game ${res}" role="listitem" draggable="true" data-sb-game="${esc(String(g.matchKey))}"
              title="拖动调整局序；也可用箭头">
              <b>G${g.gameIndex}</b><span>${esc(clockText(v.clock))}</span>
              <span class="sb-game-tools">
                <button type="button" data-sb-move="${esc(s.id)}" data-key="${esc(String(g.matchKey))}" data-dir="-1" aria-label="前移">←</button>
                <button type="button" data-sb-move="${esc(s.id)}" data-key="${esc(String(g.matchKey))}" data-dir="1" aria-label="后移">→</button>
                <button type="button" class="is-danger" data-sb-remove="${esc(s.id)}" data-key="${esc(String(g.matchKey))}" aria-label="移出这一局">${icon('close')}</button>
              </span>
            </span>`;
          }
          return `<a class="sb-game ${res}" role="listitem" href="${esc('#match/' + encodeURIComponent(String(g.matchKey)))}"
            title="打开这一局复盘"><b>G${g.gameIndex}</b><span>${esc(clockText(v.clock))}</span></a>`;
        }).join('')}
        ${editing ? `<button type="button" class="sb-game-done" data-sb-finish-edit="${esc(s.id)}">完成调整</button>` : ''}
      </div>
      ${s.notes ? `<p class="sb-series-note">${esc(s.notes)}</p>` : ''}
      ${menu ? menuHtml(s, editing, danger) : ''}
    </article>`;
  }

  function actionableSuggestions() {
    return state.suggestions
      .map((s, index) => ({ s, index }))
      .filter(({ s }) => Number(s.count) <= 7);
  }

  /* 批量只碰“高置信”：无警告、无需人工核实、装得下 BO。 */
  function bulkCandidates() {
    return actionableSuggestions().filter(({ s }) => !(s.warnings || []).length && !s.needsReview);
  }

  function suggestPanel() {
    if (!state.showSuggest || !state.suggestions.length) return '';
    const list = actionableSuggestions();
    const hidden = state.suggestions.length - list.length;
    const bulk = bulkCandidates();
    const cards = list.map(({ s, index }) => {
      const warnings = s.warnings || [];
      return `<article class="sb-cand" data-sb-cand="${index}">
        <div class="sb-cand-top">
          <span class="sb-bo">BO${esc(s.bestOf)}</span>
          <b>${esc(s.opponent || '对手待确认')}</b>
          <span class="sb-cand-count">${s.count} 局</span>
        </div>
        <div class="sb-cand-meta">${esc(s.date || '')}<i>·</i>${s.completion === 'completed' ? '已完赛' : '未完赛'}</div>
        <div class="sb-cand-games">${(s.matchKeys || []).slice(0, 7).map((k, i) => {
          const v = state.byKey.get(String(k)) || {};
          const res = v.result === 'win' ? 'win' : v.result === 'loss' ? 'loss' : '';
          return `<span class="sb-cand-game ${res}" title="${esc(clockText(v.clock))}">G${i + 1}</span>`;
        }).join('')}</div>
        ${warnings.length ? `<p class="sb-cand-warn" title="${esc(warnings.join('；'))}">⚠ ${esc(warnings[0])}${warnings.length > 1 ? ` +${warnings.length - 1}` : ''}</p>` : ''}
        <button type="button" class="sb-cand-apply" data-sb-confirm-suggest="${index}"
          title="按这个候选创建系列赛">一键编组</button>
      </article>`;
    }).join('');
    return `<section class="sb-cands" data-sb-suggest-panel aria-label="自动识别候选">
      <header class="sb-cands-head">
        <span class="sb-cands-icon">${sparkIcon()}</span>
        <div class="sb-cands-copy"><b>自动识别候选</b><small>按日期 + 对手 + 时间连续性分组，只生成候选，确认后才落库</small></div>
        <span class="sb-cands-count">${list.length} 组可一键${hidden ? ` · 另 ${hidden} 组需手动拆分` : ''}</span>
        ${bulk.length ? `<button type="button" class="sb-bulk-btn${state.bulkConfirm ? ' is-confirm' : ''}" data-sb-bulk-suggest
          title="只处理无警告、无需人工核实、≤7 局的候选">${state.bulkConfirm ? `确认编组 ${bulk.length} 组？` : `全部编组 ${bulk.length} 组`}</button>` : ''}
        <button type="button" class="sb-linkbtn" data-sb-suggest-close>收起</button>
      </header>
      ${state.bulkConfirm && bulk.length ? `<p class="sb-bulk-note">只处理无警告、无需核实的 ${bulk.length} 组；确认后仍可撤销。
        <button type="button" class="sb-linkbtn" data-sb-bulk-cancel>取消</button></p>` : ''}
      ${list.length ? `<div class="sb-cands-rail">${cards}</div>`
        : `<p class="sb-cands-none">这 ${hidden} 组候选都超过 7 局，无法一次确认为单个 BO；请在下方按时间连续段手动选取。</p>`}
    </section>`;
  }

  function rowHtml(v, no, date, eager = false) {
    const key = keyOf(v);
    const selected = state.selection.has(key);
    const own = Number.isFinite(v.killsOwn) ? v.killsOwn : null;
    const foe = Number.isFinite(v.killsFoe) ? v.killsFoe : null;
    const meta = [v.session || '训练赛', v.version].filter(Boolean).join(' · ');
    const issues = rowIssues(v);
    const gold = Number.isFinite(v.finalDiff) ? v.finalDiff : null;
    const cls = [
      'sb-row',
      selected ? 'is-selected' : '',
      v.result === 'win' ? 'is-win' : v.result === 'loss' ? 'is-loss' : '',
      !v.clock ? 'is-missing-clock' : '',
    ].filter(Boolean).join(' ');
    return `<div class="${cls}" data-sb-key="${esc(key)}" data-date="${esc(date)}" role="option"
      tabindex="0" aria-selected="${selected}" title="点这一行选中；Shift 点首尾可连选">
      <span class="sb-check" aria-hidden="true"></span>
      <span class="sb-row-when"><b>第 ${no} 局</b><small>${esc(clockText(v.clock))}</small></span>
      <span class="sb-row-opp"><b>${esc(v.opponent ? '对阵 ' + v.opponent : '对手待补')}</b><small>${esc(meta)}${issues.length ? `<i class="sb-row-flag" title="${esc(issues.join(' / '))}">⚠ ${issues.length}</i>` : ''}</small></span>
      <span class="sb-row-result">${v.result === 'win' ? '胜' : v.result === 'loss' ? '负' : '—'}</span>
      <span class="sb-row-score">${own === null || foe === null ? '—' : `${fmt(own)} : ${fmt(foe)}`}</span>
      <span class="sb-row-dur">${time(v.duration)}</span>
      <span class="sb-row-gold ${gold > 0 ? 'is-up' : gold < 0 ? 'is-down' : ''}">${diff(v.finalDiff)}</span>
      <span class="sb-row-lineup">${heroFaces(v.heroes, false, eager)}<em>VS</em>${heroFaces(v.heroesFoe, true, eager)}</span>
      <a class="sb-row-open" href="${esc('#match/' + encodeURIComponent(key))}" aria-label="打开这一局复盘" title="打开复盘">${icon('arrow')}</a>
    </div>`;
  }

  function groupedChip(s, date) {
    const score = s.score || { us: 0, them: 0 };
    const stateClass = ['interrupted', 'incomplete'].includes(s.completion) ? 'is-bad'
      : s.completion === 'completed' ? 'is-done' : 'is-open';
    const review = s.status === 'needs_review' ? ' needs-review' : '';
    return `<button type="button" class="sb-grouped-chip${review}" data-sb-series-toggle="${esc(date)}"
      title="${esc(completionLabel(s))}${s.status === 'needs_review' ? ' · 待核实' : ''}；点开管理这一组">
      <span class="sb-bo">BO${esc(s.bestOf)}</span>
      <b>${esc(s.opponent || '对手待补')}</b>
      <span class="sb-gchip-score">${fmt(score.us)} : ${fmt(score.them)}</span>
      <i class="sb-gchip-dot ${stateClass}" aria-hidden="true"></i>
    </button>`;
  }

  function dayBody(item) {
    const { date, rows, series, all } = item;
    const noOf = new Map(all.map((v, i) => [keyOf(v), i + 1]));
    const limit = state.dayLimit.get(date) || DAY_PAGE;
    const shown = rows.slice(0, limit);
    const allShownSelected = shown.length > 0 && shown.every((v) => state.selection.has(keyOf(v)));
    const selectLabel = allShownSelected ? '取消本页'
      : rows.length > limit ? `全选当前 ${shown.length} 局` : '全选本日';
    const forceSeries = state.filter.reviewOnly;
    const seriesOpen = forceSeries || state.seriesOpen.has(date)
      || series.some((s) => s.id === state.menuId || s.id === state.editId
        || s.id === state.dangerId || s.id === state.appendTo);
    return `<div class="sb-day-body">
      ${series.length ? `<div class="sb-day-block">
        <div class="sb-day-label"><span>${forceSeries ? '待核实' : '已编组'} <b>${series.length}</b> 组</span>
          ${forceSeries ? '' : `<button type="button" class="sb-linkbtn" data-sb-series-toggle="${esc(date)}">${seriesOpen ? '收起' : '管理'}</button>`}
        </div>
        ${seriesOpen ? `<div class="sb-series-grid">${series.map(seriesCard).join('')}</div>`
          : `<div class="sb-grouped-row">${series.map((s) => groupedChip(s, date)).join('')}</div>`}
      </div>` : ''}
      ${rows.length ? `<div class="sb-day-block">
        <div class="sb-day-label"><span>待编组 <b>${rows.length}</b> 局</span>
          <button type="button" class="sb-linkbtn" data-sb-select-day="${esc(date)}">${selectLabel}</button>
        </div>
        <div class="sb-rows" role="listbox" aria-multiselectable="true" aria-label="${esc(date)} 待编组对局">
          ${shown.map((v, idx) => rowHtml(v, noOf.get(keyOf(v)) || '?', date, idx < 6)).join('')}
        </div>
        ${rows.length > shown.length ? `<button type="button" class="sb-loadmore" data-sb-load-more="${esc(date)}">
          继续显示后 ${Math.min(DAY_PAGE, rows.length - shown.length)} 局 <span>还有 ${rows.length - shown.length} 局</span>
        </button>` : ''}
      </div>` : ''}
    </div>`;
  }

  function dayHtml(item) {
    const open = isOpen(item.date);
    const total = item.all.length;
    const grouped = item.all.filter((v) => state.memberOf.has(keyOf(v))).length;
    const ratio = total ? Math.round((grouped / total) * 100) : 100;
    return `<section class="sb-day${open ? ' is-open' : ''}" data-sb-day="${esc(item.date)}">
      <header class="sb-day-head" data-sb-day-toggle="${esc(item.date)}" role="button" tabindex="0"
        aria-expanded="${open}" aria-controls="sb-day-${esc(item.date)}">
        <span class="sb-day-date"><b>${esc(item.date)}</b><small>${esc(weekdayOf(item.date))}</small></span>
        <span class="sb-day-stats">${state.filter.reviewOnly
          ? `<b>${item.series.length}</b> 组待核实`
          : state.filter.qualityOnly
            ? `<b>${item.rows.length}</b> 局需补数据`
            : `${item.rows.length ? `<b>${item.rows.length}</b> 局待编` : '已编组'}${item.series.length ? `<i>·</i>${item.series.length} 组` : ''}`}</span>
        <span class="sb-day-meter" title="当天已编组占比 ${ratio}%"><i style="width:${ratio}%"></i></span>
        <span class="sb-day-chev">${icon('chevron')}</span>
      </header>
      <div class="sb-day-wrap" id="sb-day-${esc(item.date)}" ${open ? '' : 'hidden'}>${open ? dayBody(item) : ''}</div>
    </section>`;
  }

  function railHtml(days) {
    return `<div class="sb-rail-head"><span>日期</span><small>${days.length} 天</small></div>
      <div class="sb-rail-list">${days.map((item) => {
        const total = item.all.length;
        const grouped = item.all.filter((v) => state.memberOf.has(keyOf(v))).length;
        const ratio = total ? Math.round((grouped / total) * 100) : 100;
        const active = isOpen(item.date);
        return `<button type="button" class="sb-rail-item${active ? ' is-active' : ''}" data-sb-jump="${esc(item.date)}"
          aria-pressed="${active}" title="${esc(item.date)} · ${grouped}/${total} 局已编组">
          <span class="sb-rail-date"><b>${esc(item.date.slice(5).replace('-', '.'))}</b><small>${esc(weekdayOf(item.date))}</small></span>
          <span class="sb-rail-meter"><i style="width:${ratio}%"></i></span>
          <span class="sb-rail-count">${item.rows.length ? `${item.rows.length} 局` : '已编组'}</span>
        </button>`;
      }).join('')}</div>`;
  }

  function workspaceHtml(days = displayDays()) {
    if (!days.length) {
      return `<div class="sb-workspace is-empty"><div class="sb-empty">
        <b>${hasFilter() ? '没有匹配的对局' : '还没有待编组对局'}</b>
        <p>${hasFilter() ? '换个对手或关键词试试。' : '先到「对局档案」完成归档，再回来编组。'}</p>
        ${hasFilter() ? '<button type="button" class="sb-ghost" data-sb-reset-filter>清除筛选</button>'
          : `<a class="sb-ghost" href="#matches">去对局档案</a>`}
      </div></div>`;
    }
    return `<div class="sb-workspace">
      <aside class="sb-rail" aria-label="按日期定位">${railHtml(days)}</aside>
      <div class="sb-days-strip" aria-label="按日期定位">${days.map((d) => `<button type="button"
        class="sb-day-chip${isOpen(d.date) ? ' is-active' : ''}" data-sb-jump="${esc(d.date)}">
        ${esc(d.date.slice(5).replace('-', '.'))}<b>${d.rows.length}</b></button>`).join('')}</div>
      <section class="sb-days" data-sb-days>${days.map(dayHtml).join('')}</section>
    </div>`;
  }

  function skeletonHtml() {
    return `<div class="sb-workspace is-loading" aria-hidden="true">
      <aside class="sb-rail sb-skeleton-rail"></aside>
      <section class="sb-days">
        ${[0, 1, 2].map(() => `<div class="sb-skel-day"><div class="sb-skel-line w40"></div>
          <div class="sb-skel-row"></div><div class="sb-skel-row"></div><div class="sb-skel-row"></div></div>`).join('')}
      </section>
    </div>`;
  }

  function heroHtml() {
    const ungrouped = state.counts.ungrouped;
    const groups = state.series.length;
    const candidates = actionableSuggestions().length;
    return `<header class="sb-hero">
      <div class="sb-hero-copy">
        <span class="sb-eyebrow">SERIES BUILDER</span>
        <h1>系列赛编组</h1>
        <p class="sb-lede">一行一局：点行选中、Shift 连选，底部确认赛制生成系列赛。编组只改关系，不动原始对局。</p>
      </div>
      <div class="sb-hero-meta" aria-label="编组概览">
        <span class="sb-hero-stat"><b>${fmt(ungrouped)}</b><small>局待编组</small></span>
        <span class="sb-hero-stat"><b>${fmt(groups)}</b><small>组已确认</small></span>
        <span class="sb-hero-stat" title="另有 ${Math.max(0, state.suggestions.length - candidates)} 组超过 7 局，需手动拆分"><b>${fmt(candidates)}</b><small>组可一键</small></span>
        <span class="sb-hero-stat is-quiet"><b>${esc(latestDate())}</b><small>最近对局</small></span>
      </div>
    </header>`;
  }

  function scopeText(days) {
    if (!state.loaded) return '';
    if (state.filter.reviewOnly) {
      return `待核实 ${days.reduce((n, d) => n + d.series.length, 0)} 组 · ${days.length} 天`;
    }
    if (state.filter.qualityOnly) {
      return `需补数据 ${days.reduce((n, d) => n + d.rows.length, 0)} 局 · ${days.length} 天`;
    }
    if (hasFilter()) {
      return `筛选后 ${days.length} 天 · ${fmt(days.reduce((n, d) => n + d.rows.length, 0))} 局`;
    }
    return `${days.length} 天 · ${fmt(state.counts.ungrouped)} 局待编组`;
  }

  function updateScope(days) {
    const node = root?.querySelector('.sb-toolbar-scope');
    if (node) node.textContent = scopeText(days);
  }

  function toolbarHtml(days = []) {
    const options = opponentOptions();
    const current = state.filter.opponent;
    const scope = scopeText(days);
    const reviewCount = state.series.filter((s) => s.status === 'needs_review').length;
    const quality = qualityCount();
    return `<div class="sb-toolbar" data-sb-toolbar>
      <div class="sb-toolbar-main">
        <label class="sb-search">
          <span class="sb-search-icon">${icon('search')}</span>
          <input type="search" data-sb-search value="${esc(state.filter.q)}" placeholder="搜索对手、训练组、版本" autocomplete="off" aria-label="搜索对局">
          <button type="button" class="sb-search-clear${state.filter.q ? ' is-on' : ''}" data-sb-clear-search aria-label="清空搜索">${icon('close')}</button>
        </label>
        <label class="sb-select">
          <span class="sb-select-label">对手</span>
          <select data-sb-opponent aria-label="按对手筛选">
            <option value="">全部对手</option>
            ${options.map(([name, count]) => `<option value="${esc(name)}"${name === current ? ' selected' : ''}>${esc(name)}（${count}）</option>`).join('')}
          </select>
        </label>
        ${reviewCount ? `<button type="button" class="sb-filter-chip${state.filter.reviewOnly ? ' is-on' : ''}"
          data-sb-review-filter aria-pressed="${state.filter.reviewOnly}" title="只看需要人工确认的编组">
          <span class="sb-chip-dot" aria-hidden="true"></span>待核实 <b>${reviewCount}</b></button>` : ''}
        ${quality ? `<button type="button" class="sb-filter-chip is-quality${state.filter.qualityOnly ? ' is-on' : ''}"
          data-sb-quality-filter aria-pressed="${state.filter.qualityOnly}" title="只看缺对手 / 开赛时间 / 阵容等字段的待编组局">
          <span class="sb-chip-dot" aria-hidden="true"></span>需补数据 <b>${quality}</b></button>` : ''}
        <button type="button" class="sb-iconbtn sb-refresh" data-sb-refresh aria-label="刷新数据" title="刷新数据">${icon('refresh')}</button>
      </div>
      <div class="sb-toolbar-side">
        ${scope ? `<span class="sb-toolbar-scope">${esc(scope)}</span>` : ''}
        ${actionableSuggestions().length ? `<button type="button" class="sb-suggest-toggle${state.showSuggest ? ' is-on' : ''}"
          data-sb-suggest-toggle aria-pressed="${state.showSuggest}" title="智能候选（只生成建议，不自动落库）">${sparkIcon()}<span>智能候选</span><b>${actionableSuggestions().length}</b></button>` : ''}
        <span class="sb-toolbar-hint">⌘/Ctrl+Z 撤销 · / 搜索</span>
      </div>
    </div>`;
  }

  function bannerHtml() {
    if (!state.appendTo) return '';
    const target = state.series.find((s) => s.id === state.appendTo);
    if (!target) return '';
    const count = (target.games || []).length;
    const capacity = Math.max(0, Number(target.bestOf) - count);
    return `<div class="sb-banner" role="status">
      <span class="sb-banner-dot"></span>
      <span>正在向 <b>BO${esc(target.bestOf)} · ${esc(target.opponent || '对手待补')}</b> 添加对局
        （当前 ${count}/${esc(target.bestOf)} 局，${capacity ? `还能加 ${capacity} 局` : '已满，先改赛制或移出一局'}）：
        勾选下方待编组对局，再点底部「加入系列赛」。</span>
      <button type="button" class="sb-linkbtn" data-sb-cancel-append>取消</button>
    </div>`;
  }

  function html() {
    if (state.error && !state.loaded) {
      return `<div class="page sb-page"><section class="sb-empty is-error">
        <b>读不到编组数据</b><p>${esc(state.error)}</p>
        <button type="button" class="sb-ghost" data-sb-retry>重试</button>
      </section></div>`;
    }
    const days = state.loaded ? displayDays() : [];
    if (state.loaded) syncOpenDays(days);
    return `<div class="page sb-page${state.selection.size ? ' has-selection' : ''}">
      ${heroHtml()}
      ${toolbarHtml(state.loaded ? days : [])}
      ${bannerHtml()}
      ${suggestPanel()}
      ${state.loaded ? workspaceHtml(days) : skeletonHtml()}
    </div>`;
  }

  function render() {
    if (!root) return;
    const y = window.scrollY;
    root.innerHTML = html();
    syncSelection();
    renderActionBar();
    setBusy(state.busy);
    if (state.loaded) cachePayload();
    saveUIState();
    window.scrollTo(0, y);
  }

  function renderWorkspace(days = displayDays()) {
    if (!root) return;
    syncOpenDays(days);
    const current = root.querySelector('.sb-workspace');
    if (!current) { render(); return; }
    const y = window.scrollY;
    current.outerHTML = workspaceHtml(days);
    syncSelection();
    renderActionBar();
    saveUIState();
    window.scrollTo(0, y);
  }

  function syncSelection() {
    if (!root) return;
    root.querySelectorAll('[data-sb-key]').forEach((node) => {
      const on = state.selection.has(node.dataset.sbKey);
      node.classList.toggle('is-selected', on);
      node.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    root.querySelector('.sb-page')?.classList.toggle('has-selection', state.selection.size > 0);
  }

  function renderActionBar() {
    root?.querySelectorAll('[data-sb-selectbar]').forEach((n) => n.remove());
    if (!root || !state.selection.size) return;
    const keys = orderKeys([...state.selection]);
    const recommend = recommendedBestOf(keys.length);
    const bestOf = effectiveBestOf(keys.length);
    const full = keys.length === bestOf;
    const fixed = full || state.fixedMode;
    const appending = Boolean(state.appendTo);
    const target = appending ? state.series.find((s) => s.id === state.appendTo) : null;
    const existing = target ? (target.games || []).length : 0;
    const capacity = target ? Math.max(0, Number(target.bestOf) - existing) : 0;
    const overflow = appending && keys.length > capacity;
    const warns = selectionWarnings(keys);
    if (appending && overflow) {
      warns.unshift(capacity
        ? `BO${target.bestOf} 还能加 ${capacity} 局，当前选了 ${keys.length} 局`
        : `BO${target.bestOf} 已满 ${existing} 局，先改赛制或移出一局`);
    }
    const bar = document.createElement('div');
    bar.className = 'sb-selectbar';
    bar.dataset.sbSelectbar = '1';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', '编组操作');
    bar.innerHTML = `
      <div class="sb-selectbar-main">
        <span class="sb-selectbar-count"><b>${keys.length}</b> 局</span>
        <span class="sb-selectbar-sort">按开赛时间排序</span>
        ${warns.length ? `<span class="sb-selectbar-warn" title="${esc(warns.join('；'))}">⚠ ${esc(warns[0])}${warns.length > 1 ? ` +${warns.length - 1}` : ''}</span>` : ''}
      </div>
      ${appending ? '' : `<div class="sb-seg" role="group" aria-label="赛制">
        ${BO_LIST.map((bo) => {
          const invalid = keys.length > bo;
          return `<button type="button" data-sb-set-bo="${bo}" ${invalid ? 'disabled' : ''}
            class="${bo === bestOf ? 'is-active' : ''}${bo === recommend ? ' is-rec' : ''}"
            aria-pressed="${bo === bestOf}" title="${invalid ? `已选 ${keys.length} 局，超过 BO${bo}` : bo === recommend ? '按局数推荐' : `改为 BO${bo}`}">BO${bo}${bo === recommend ? '<i>推荐</i>' : ''}</button>`;
        }).join('')}
      </div>
      <label class="sb-switch${full ? ' is-auto' : ''}" title="${full ? '选满 BO 局数，自动按打满记录' : '固定打满：打满 BO 局数才算完赛'}">
        <input type="checkbox" data-sb-fixed ${fixed ? 'checked' : ''} ${full ? 'disabled' : ''}>
        <span class="sb-switch-track" aria-hidden="true"></span><span>打满</span>
        ${full ? '<em class="sb-switch-auto">自动</em>' : ''}
      </label>`}
      <div class="sb-selectbar-actions">
        <button type="button" class="sb-ab-cancel" data-sb-clear aria-label="取消选择">${icon('close')}</button>
        ${appending
          ? `<button type="button" class="sb-ab-confirm" data-sb-append-confirm ${(overflow || !keys.length) ? 'disabled' : ''}>加入系列赛</button>`
          : `<button type="button" class="sb-ab-confirm" data-sb-confirm ${keys.length > 7 ? 'disabled' : ''}>确认编组</button>`}
      </div>`;
    root.appendChild(bar);
  }

  /* ───────────────────────── 写操作 ───────────────────────── */
  function syncReviewFilter() {
    if (state.filter.reviewOnly && !state.series.some((s) => s.status === 'needs_review')) {
      state.filter.reviewOnly = false;
    }
  }

  function upsertSeries(series) {
    const index = state.series.findIndex((s) => s.id === series.id);
    if (index >= 0) state.series[index] = series;
    else state.series.push(series);
    applySeries(state.series);
    const keys = new Set((series.games || []).map((g) => String(g.matchKey)));
    state.suggestions = state.suggestions.filter((s) => !(s.matchKeys || []).some((k) => keys.has(String(k))));
    state.counts.ungrouped = state.vectors.filter((v) => !state.memberOf.has(keyOf(v))).length;
    syncReviewFilter();
    syncQualityFilter();
  }

  function removeSeries(id) {
    state.series = state.series.filter((s) => s.id !== id);
    applySeries(state.series);
    state.counts.ungrouped = state.vectors.filter((v) => !state.memberOf.has(keyOf(v))).length;
    syncReviewFilter();
    syncQualityFilter();
  }

  function describeKey(key) {
    const v = state.byKey.get(String(key));
    if (!v) return String(key);
    const sameDay = state.vectors.filter((x) => dateOf(x) === dateOf(v)).sort(ascTime);
    const no = sameDay.findIndex((x) => keyOf(x) === String(key)) + 1;
    return `第 ${no || '?'} 局 ${clockText(v.clock)}`;
  }

  async function confirmSelection() {
    const keys = orderKeys([...state.selection]);
    if (!keys.length) return;
    const bestOf = effectiveBestOf(keys.length);
    const full = keys.length === bestOf;
    if (keys.length > bestOf) {
      toast(`已选 ${keys.length} 局超过 BO${bestOf}，请改大赛制或取消多余对局`, 'error');
      return;
    }
    const completionMode = (full || state.fixedMode) ? 'fixed' : 'standard';
    const items = keys.map((k) => state.byKey.get(k)).filter(Boolean);
    const opps = [...new Set(items.map((v) => v.opponent || ''))].filter(Boolean);
    const sessions = [...new Set(items.map((v) => v.session || ''))].filter(Boolean);
    const versions = [...new Set(items.map((v) => v.version || ''))].filter(Boolean);
    try {
      const payload = await api('/api/series', {
        method: 'POST',
        body: {
          bestOf, completionMode,
          games: keys,
          opponent: opps.length === 1 ? opps[0] : null,
          session: sessions.length === 1 ? sessions[0] : null,
          version: versions.length === 1 ? versions[0] : null,
          status: selectionWarnings(keys).length ? 'needs_review' : 'confirmed',
        },
      });
      const created = payload.series;
      const op = { label: `创建 ${seriesLabel(created)}`,
        run: () => api(`/api/series/${created.id}`, { method: 'DELETE' }) };
      pushUndo(op);
      upsertSeries(created);
      state.seriesOpen.add(dateOfSeries(created));
      clearSelection();
      render();
      toast(`已编组 BO${bestOf} · ${keys.length} 局${full ? ' · 打满' : ''}`, 'ok', { undo: () => undoOp(op) });
    } catch (error) {
      const occupied = Array.isArray(error.occupied) ? error.occupied : [];
      if (occupied.length) {
        const taken = new Set(occupied.map(([k]) => String(k)));
        state.selection = new Set([...state.selection].filter((k) => !taken.has(k)));
        const detail = occupied.slice(0, 3).map(([k, s]) => `${describeKey(k)} 已属 ${s}`).join('，');
        toast(`编组失败：${detail}${occupied.length > 3 ? ' 等' : ''}；已移出选区`, 'error', { timeout: 9000 });
        renderActionBar();
        syncSelection();
        await load({ silent: true });
      } else {
        toast(`编组失败：${error.message}`, 'error');
      }
    }
  }

  function suggestionBody(s) {
    return {
      bestOf: s.bestOf, completionMode: s.completionMode, games: s.matchKeys,
      opponent: s.opponent, session: s.session, version: s.version,
      status: s.needsReview ? 'needs_review' : 'confirmed',
    };
  }

  async function confirmSuggest(index) {
    const s = state.suggestions[index];
    if (!s) return;
    try {
      const payload = await api('/api/series', { method: 'POST', body: suggestionBody(s) });
      const created = payload.series;
      const op = { label: `创建 ${seriesLabel(created)}`,
        run: () => api(`/api/series/${created.id}`, { method: 'DELETE' }) };
      pushUndo(op);
      upsertSeries(created);
      state.seriesOpen.add(dateOfSeries(created));
      render();
      toast(`已按候选编组 ${seriesLabel(created)}`, 'ok', { undo: () => undoOp(op) });
    } catch (error) {
      toast(`编组失败：${error.message}`, 'error');
      if (Array.isArray(error.occupied) && error.occupied.length) await load({ silent: true });
    }
  }

  async function bulkCreateSuggestions() {
    const list = bulkCandidates();
    if (!list.length) return;
    state.bulkConfirm = false;
    const created = [];
    const failed = [];
    for (const { s } of list) {
      try {
        const payload = await api('/api/series', { method: 'POST', body: suggestionBody(s) });
        created.push(payload.series);
        upsertSeries(payload.series);
      } catch (error) {
        failed.push(error);
      }
    }
    const ids = created.map((s) => s.id);
    const op = ids.length ? {
      label: `批量编组 ${ids.length} 组`,
      run: async () => { for (const id of ids) await api(`/api/series/${id}`, { method: 'DELETE' }); },
    } : null;
    if (op) pushUndo(op);
    render();
    if (created.length) {
      toast(`已编组 ${created.length} 组${failed.length ? `，${failed.length} 组失败` : ''}`,
        failed.length ? 'error' : 'ok', op ? { undo: () => undoOp(op) } : {});
    } else {
      toast(`批量编组失败：${failed[0]?.message || '未知错误'}`, 'error');
    }
  }

  async function undoOp(op) {
    if (op.done) return;
    op.done = true;
    state.undoStack = state.undoStack.filter((item) => item !== op);
    try {
      await op.run();
      toast(`已撤销：${op.label}`, 'ok');
      await load({ silent: true });
    } catch (error) {
      toast(`撤销失败：${error.message}`, 'error');
    }
  }

  async function patchSeries(seriesId, body, label) {
    const before = state.series.find((s) => s.id === seriesId);
    const snapshot = before ? {
      bestOf: before.bestOf, completionMode: before.completionMode,
      games: (before.games || []).map((g) => ({ matchKey: g.matchKey, gameIndex: g.gameIndex })),
      completion: before.completion, notes: before.notes, status: before.status,
    } : null;
    try {
      const payload = await api(`/api/series/${seriesId}`, { method: 'PATCH', body });
      const op = snapshot ? { label, run: () => api(`/api/series/${seriesId}`, { method: 'PATCH', body: snapshot }) } : null;
      if (op) pushUndo(op);
      if (payload.series) upsertSeries(payload.series);
      render();
      toast('已更新：' + label, 'ok', op ? { undo: () => undoOp(op) } : {});
      /* 局次变了，候选与未编组行都要跟着变；bootstrap 命中缓存，补一次很便宜。 */
      if (body && body.games) load({ silent: true });
      return true;
    } catch (error) {
      toast(`更新失败：${error.message}`, 'error');
      return false;
    }
  }

  async function deleteSeries(seriesId) {
    const before = state.series.find((s) => s.id === seriesId);
    try {
      await api(`/api/series/${seriesId}`, { method: 'DELETE' });
      const op = before ? {
        label: `删除 ${seriesLabel(before)}`,
        run: () => api('/api/series', {
          method: 'POST',
          body: {
            id: before.id, bestOf: before.bestOf, completionMode: before.completionMode,
            games: (before.games || []).map((g) => ({ matchKey: g.matchKey, gameIndex: g.gameIndex })),
            opponent: before.opponent, session: before.session, version: before.version,
            status: before.status, completion: before.completion, notes: before.notes,
          },
        }),
      } : null;
      if (op) pushUndo(op);
      removeSeries(seriesId);
      state.dangerId = null;
      state.menuId = null;
      render();
      toast(`已删除 ${before ? seriesLabel(before) : '编组'}，对局保留`, 'ok', op ? { undo: () => undoOp(op) } : {});
      load({ silent: true });
    } catch (error) {
      toast(`删除失败：${error.message}`, 'error');
    }
  }

  async function appendSelected(seriesId) {
    const target = state.series.find((s) => s.id === seriesId);
    if (!target) return;
    const games = (target.games || []).map((g) => ({ matchKey: g.matchKey, gameIndex: g.gameIndex }));
    for (const key of orderKeys([...state.selection])) games.push({ matchKey: key, gameIndex: games.length + 1 });
    const ok = await patchSeries(seriesId, { games }, `向 ${seriesLabel(target)} 添加 ${state.selection.size} 局`);
    if (ok) { state.appendTo = null; clearSelection(); render(); }
  }

  async function moveGame(seriesId, key, dir) {
    const target = state.series.find((s) => s.id === seriesId);
    if (!target) return;
    const games = (target.games || []).slice().sort((a, b) => a.gameIndex - b.gameIndex);
    const index = games.findIndex((g) => g.matchKey === key);
    const swap = index + dir;
    if (index < 0 || swap < 0 || swap >= games.length) return;
    [games[index], games[swap]] = [games[swap], games[index]];
    await patchSeries(seriesId, { games: games.map((g) => ({ matchKey: g.matchKey, gameIndex: g.gameIndex })) },
      `调整 ${seriesLabel(target)} 局序`);
  }

  async function reorderGame(seriesId, fromKey, toKey) {
    const target = state.series.find((s) => s.id === seriesId);
    if (!target) return;
    const games = (target.games || []).slice().sort((a, b) => a.gameIndex - b.gameIndex);
    const from = games.findIndex((g) => g.matchKey === fromKey);
    const to = games.findIndex((g) => g.matchKey === toKey);
    if (from < 0 || to < 0 || from === to) return;
    const [item] = games.splice(from, 1);
    games.splice(to, 0, item);
    await patchSeries(seriesId, { games: games.map((g, i) => ({ matchKey: g.matchKey, gameIndex: i + 1 })) },
      `调整 ${seriesLabel(target)} 局序`);
  }

  async function removeGame(seriesId, key) {
    const target = state.series.find((s) => s.id === seriesId);
    if (!target) return;
    const games = (target.games || []).filter((g) => g.matchKey !== key)
      .sort((a, b) => a.gameIndex - b.gameIndex)
      .map((g, index) => ({ matchKey: g.matchKey, gameIndex: index + 1 }));
    if (!games.length) { toast('至少保留一局；要整组删除请用「删除编组」', 'error'); return; }
    await patchSeries(seriesId, { games }, `从 ${seriesLabel(target)} 移出一局`);
  }

  async function cycleBestOf(seriesId, bestOf) {
    const target = state.series.find((s) => s.id === seriesId);
    if (!target || Number(target.bestOf) === Number(bestOf)) return;
    await patchSeries(seriesId, { bestOf: Number(bestOf) }, `${seriesLabel(target)} 改为 BO${bestOf}`);
  }

  /* ───────────────────────── 事件 ───────────────────────── */
  function closeMenu() {
    if (!state.menuId) return;
    state.menuId = null;
    state.dangerId = null;
    root?.querySelectorAll('[data-sb-menu-panel]').forEach((n) => n.remove());
    root?.querySelectorAll('[data-sb-menu][aria-expanded="true"]').forEach((n) => n.setAttribute('aria-expanded', 'false'));
  }

  function jumpToDay(date) {
    state.openDays = new Set([date]);
    if (!hasFilter()) state.manualOpen = new Set(state.openDays);
    render();
    root?.querySelector(`[data-sb-day="${CSS.escape(date)}"]`)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function onClick(event) {
    const target = event.target;
    if (!root) return;
    if (target.closest('a')) return; // 链接照常跳转

    /* 菜单点外部先收起；只摘菜单节点，不整页重绘，避免这次点击丢掉。 */
    if (state.menuId && !target.closest('[data-sb-menu-panel],[data-sb-menu]')) closeMenu();

    const row = target.closest('[data-sb-key]');
    if (row) { toggleRow(row.dataset.sbKey, event); return; }

    const dayToggle = target.closest('[data-sb-day-toggle]');
    if (dayToggle) {
      const date = dayToggle.dataset.sbDayToggle;
      if (state.openDays.has(date)) state.openDays.delete(date); else state.openDays.add(date);
      if (!hasFilter()) state.manualOpen = new Set(state.openDays);
      render();
      return;
    }

    const jump = target.closest('[data-sb-jump]');
    if (jump) { jumpToDay(jump.dataset.sbJump); return; }

    const action = target.closest('[data-sb-select-day],[data-sb-load-more],[data-sb-reset-filter],'
      + '[data-sb-series-toggle],[data-sb-review-filter],[data-sb-quality-filter],[data-sb-refresh],[data-sb-clear-search],'
      + '[data-sb-suggest-toggle],[data-sb-suggest-close],[data-sb-confirm],[data-sb-append-confirm],'
      + '[data-sb-clear],[data-sb-set-bo],[data-sb-fixed],[data-sb-confirm-suggest],[data-sb-menu],'
      + '[data-sb-edit],[data-sb-finish-edit],[data-sb-append],[data-sb-set-bo-series],[data-sb-mark],'
      + '[data-sb-bulk-suggest],[data-sb-bulk-cancel],'
      + '[data-sb-mark-reviewed],[data-sb-delete],[data-sb-move],[data-sb-remove],'
      + '[data-sb-cancel-append],[data-sb-retry]');
    if (!action) {
      if (state.menuId && !target.closest('[data-sb-series]')) closeMenu();
      return;
    }
    if (state.busy && target.closest(WRITE_BUTTONS)) return;

    if (action.dataset.sbSeriesToggle) {
      const date = action.dataset.sbSeriesToggle;
      if (state.seriesOpen.has(date)) state.seriesOpen.delete(date); else state.seriesOpen.add(date);
      render();
      return;
    }
    if (action.dataset.sbReviewFilter !== undefined) {
      applyFilter({ reviewOnly: !state.filter.reviewOnly, qualityOnly: false }, { rebuild: true });
      return;
    }
    if (action.dataset.sbQualityFilter !== undefined) {
      applyFilter({ qualityOnly: !state.filter.qualityOnly, reviewOnly: false }, { rebuild: true });
      return;
    }
    if (action.dataset.sbSelectDay) {
      const date = action.dataset.sbSelectDay;
      const item = displayDays().find((d) => d.date === date);
      const limit = state.dayLimit.get(date) || DAY_PAGE;
      if (item) selectDay(item.date, item.rows.slice(0, limit));
      return;
    }
    if (action.dataset.sbLoadMore) {
      const date = action.dataset.sbLoadMore;
      state.dayLimit.set(date, (state.dayLimit.get(date) || DAY_PAGE) + DAY_PAGE);
      render();
      return;
    }
    if (action.dataset.sbResetFilter !== undefined) {
      state.filter = { q: '', opponent: '', reviewOnly: false, qualityOnly: false };
      state.openDays = new Set(state.manualOpen);
      render();
      return;
    }
    if (action.dataset.sbRefresh !== undefined) {
      action.classList.add('is-spinning');
      load({ silent: state.loaded }).finally(() => action.classList.remove('is-spinning'));
      return;
    }
    if (action.dataset.sbClearSearch !== undefined) {
      applyFilter({ q: '' }, { rebuild: true });
      root.querySelector('[data-sb-search]')?.focus();
      return;
    }
    if (action.dataset.sbSuggestToggle !== undefined) {
      state.showSuggest = !state.showSuggest;
      state.bulkConfirm = false;
      render();
      return;
    }
    if (action.dataset.sbSuggestClose !== undefined) {
      state.showSuggest = false;
      state.bulkConfirm = false;
      render();
      return;
    }
    if (action.dataset.sbBulkSuggest !== undefined) {
      if (!state.bulkConfirm) {
        state.bulkConfirm = true;
        render();
        return;
      }
      bulkCreateSuggestions();
      return;
    }
    if (action.dataset.sbBulkCancel !== undefined) {
      state.bulkConfirm = false;
      render();
      return;
    }
    if (action.dataset.sbSetBo !== undefined) {
      state.bestOf = Number(action.dataset.sbSetBo);
      renderActionBar();
      return;
    }
    if (action.dataset.sbConfirm !== undefined) { confirmSelection(); return; }
    if (action.dataset.sbAppendConfirm !== undefined) { appendSelected(state.appendTo); return; }
    if (action.dataset.sbClear !== undefined) { state.appendTo = null; clearSelection(); render(); return; }
    if (action.dataset.sbConfirmSuggest !== undefined) { confirmSuggest(Number(action.dataset.sbConfirmSuggest)); return; }
    if (action.dataset.sbMenu) {
      const id = action.dataset.sbMenu;
      const again = state.menuId === id;
      closeMenu();
      if (again) return;
      const series = state.series.find((s) => s.id === id);
      const card = root.querySelector(`[data-sb-series="${CSS.escape(id)}"]`);
      if (!series || !card) return;
      state.menuId = id;
      state.dangerId = null;
      action.setAttribute('aria-expanded', 'true');
      card.insertAdjacentHTML('beforeend', menuHtml(series, state.editId === id, false));
      return;
    }
    if (action.dataset.sbEdit) {
      state.editId = state.editId === action.dataset.sbEdit ? null : action.dataset.sbEdit;
      state.menuId = null;
      render();
      return;
    }
    if (action.dataset.sbFinishEdit) { state.editId = null; render(); return; }
    if (action.dataset.sbAppend) {
      state.appendTo = action.dataset.sbAppend;
      state.menuId = null;
      clearSelection();
      render();
      return;
    }
    if (action.dataset.sbSetBoSeries) { cycleBestOf(action.dataset.sbSetBoSeries, action.dataset.bo); return; }
    if (action.dataset.sbMarkReviewed) {
      patchSeries(action.dataset.sbMarkReviewed, { status: 'confirmed' }, '标记已核实');
      state.menuId = null;
      return;
    }
    if (action.dataset.sbMark) {
      patchSeries(action.dataset.sbMark, { completion: action.dataset.mark },
        `标注 ${action.dataset.mark === 'interrupted' ? '中断' : '采集不完整'}`);
      state.menuId = null;
      return;
    }
    if (action.dataset.sbDelete) {
      if (state.dangerId === action.dataset.sbDelete) { deleteSeries(action.dataset.sbDelete); return; }
      state.dangerId = action.dataset.sbDelete;
      const panel = root.querySelector(`[data-sb-menu-panel="${CSS.escape(action.dataset.sbDelete)}"]`);
      const button = panel?.querySelector('[data-sb-delete]');
      if (button) button.textContent = '确认删除编组？';
      return;
    }
    if (action.dataset.sbMove) { moveGame(action.dataset.sbMove, action.dataset.key, Number(action.dataset.dir)); return; }
    if (action.dataset.sbRemove) { removeGame(action.dataset.sbRemove, action.dataset.key); return; }
    if (action.dataset.sbCancelAppend !== undefined) { state.appendTo = null; clearSelection(); render(); return; }
    if (action.dataset.sbRetry !== undefined) { load(); return; }
  }

  function onInput(event) {
    if (!event.target.matches('[data-sb-search]')) return;
    const value = event.target.value;
    const clear = root.querySelector('[data-sb-clear-search]');
    if (clear) clear.classList.toggle('is-on', Boolean(value));
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => applyFilter({ q: value }), 140);
  }

  function onChange(event) {
    const target = event.target;
    if (target.matches('[data-sb-opponent]')) {
      applyFilter({ opponent: target.value }, { rebuild: true });
      return;
    }
    if (target.matches('[data-sb-fixed]')) state.fixedMode = target.checked;
  }

  function visibleRowNodes() {
    return root ? [...root.querySelectorAll('[data-sb-key]')] : [];
  }

  function moveRowFocus(node, dir, event) {
    const rows = visibleRowNodes();
    const index = rows.indexOf(node);
    if (index < 0) return;
    const next = rows[Math.min(rows.length - 1, Math.max(0, index + dir))];
    if (!next || next === node) return;
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: 'nearest' });
    if (event.shiftKey) {
      const keys = rows.map((row) => row.dataset.sbKey);
      const anchor = keys.includes(state.anchor) ? state.anchor : node.dataset.sbKey;
      const ia = keys.indexOf(anchor), ib = keys.indexOf(next.dataset.sbKey);
      if (ia >= 0 && ib >= 0) setSelection(keys.slice(Math.min(ia, ib), Math.max(ia, ib) + 1));
    } else {
      state.anchor = next.dataset.sbKey;
    }
  }

  function onKeyDown(event) {
    if (!root) return;
    const typing = /^(input|textarea|select)$/i.test((event.target.tagName || ''));
    if (event.key === 'Escape') {
      if (state.menuId || state.editId || state.appendTo || state.dangerId || state.bulkConfirm) {
        state.menuId = null; state.editId = null; state.appendTo = null; state.dangerId = null;
        state.bulkConfirm = false;
        render();
      } else if (state.selection.size) {
        clearSelection();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !typing) {
      event.preventDefault();
      undo();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && !typing) {
      const rows = visibleRowNodes();
      if (!rows.length) return;
      event.preventDefault();
      setSelection(rows.map((row) => row.dataset.sbKey));
      return;
    }
    if (event.key === '/' && !typing) {
      event.preventDefault();
      root.querySelector('[data-sb-search]')?.focus();
      return;
    }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !typing) {
      const row = event.target.closest?.('[data-sb-key]');
      if (!row || event.target.closest?.('a')) return;
      event.preventDefault();
      moveRowFocus(row, event.key === 'ArrowDown' ? 1 : -1, event);
      return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && !typing) {
      if (event.target.closest?.('a')) return;
      const row = event.target.closest?.('[data-sb-key]');
      if (row) {
        event.preventDefault();
        toggleRow(row.dataset.sbKey, event);
        return;
      }
      const day = event.target.closest?.('[data-sb-day-toggle]');
      if (day) { event.preventDefault(); day.click(); }
    }
  }

  function onDocClick(event) {
    if (!state.menuId) return;
    if (event.target.closest?.('[data-sb-menu-panel],[data-sb-menu]')) return;
    if (event.target.closest?.('[data-sb-root]')) return; // 页内由根节点处理，避免重复
    closeMenu();
  }

  function dragCleanup() {
    state.dragGame = null;
    root?.querySelectorAll('.sb-game.is-dragging,.sb-game.is-drop-target')
      .forEach((n) => n.classList.remove('is-dragging', 'is-drop-target'));
  }

  function onDragStart(event) {
    const chip = event.target.closest?.('[data-sb-game]');
    const card = chip?.closest?.('[data-sb-series]');
    if (!chip || !card || state.editId !== card.dataset.sbSeries) return;
    state.dragGame = { seriesId: card.dataset.sbSeries, key: chip.dataset.sbGame };
    chip.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      try { event.dataTransfer.setData('text/plain', state.dragGame.key); } catch { /* 忽略 */ }
    }
  }

  function onDragOver(event) {
    if (!state.dragGame) return;
    const chip = event.target.closest?.('[data-sb-game]');
    const card = chip?.closest?.('[data-sb-series]');
    if (!chip || !card || card.dataset.sbSeries !== state.dragGame.seriesId) return;
    if (chip.dataset.sbGame === state.dragGame.key) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    root?.querySelectorAll('.sb-game.is-drop-target').forEach((n) => n.classList.remove('is-drop-target'));
    chip.classList.add('is-drop-target');
  }

  function onDragLeave(event) {
    event.target.closest?.('[data-sb-game]')?.classList.remove('is-drop-target');
  }

  function onDrop(event) {
    const drag = state.dragGame;
    if (!drag) return;
    const chip = event.target.closest?.('[data-sb-game]');
    const card = chip?.closest?.('[data-sb-series]');
    if (!chip || !card || card.dataset.sbSeries !== drag.seriesId) return;
    event.preventDefault();
    const targetKey = chip.dataset.sbGame;
    dragCleanup();
    if (targetKey && targetKey !== drag.key) reorderGame(drag.seriesId, drag.key, targetKey);
  }

  function bind(node) {
    node.addEventListener('click', onClick);
    node.addEventListener('input', onInput);
    node.addEventListener('change', onChange);
    node.addEventListener('dragstart', onDragStart);
    node.addEventListener('dragover', onDragOver);
    node.addEventListener('dragleave', onDragLeave);
    node.addEventListener('drop', onDrop);
    node.addEventListener('dragend', dragCleanup);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('click', onDocClick);
  }

  function mount(node) {
    if (!node || node.dataset.sbBound) return;
    /* 外壳重新渲染出新的挂载点时，先把上一份文档级监听解掉，避免重复响应。 */
    if (root && root !== node) dispose();
    node.dataset.sbBound = '1';
    root = node;
    bind(node);
    if (cachedPayload && Date.now() - cachedAt < PAGE_CACHE_TTL) {
      applyPayload(cachedPayload);
      state.loaded = true;
      render();
      load({ silent: true });
    } else {
      load();
    }
  }

  /* metadata 后到：只补头像，不动选区 / 折叠状态。 */
  function rerender() {
    if (root && state.loaded) render();
  }

  function dispose() {
    saveUIState();
    generation += 1;
    controller?.abort();
    controller = null;
    clearTimeout(searchTimer);
    document.removeEventListener('keydown', onKeyDown);
    document.removeEventListener('click', onDocClick);
    document.querySelectorAll('[data-sb-toasts]').forEach((n) => n.remove());
    root = null;
    busyButtons = [];
  }

  return { mount, dispose, rerender, state };
}
