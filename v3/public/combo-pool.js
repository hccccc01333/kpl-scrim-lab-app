/* 组合池设置页（2026-11）
 *
 * 赛训组自己维护「双人组合池」和「三人体系池」，优先级最高：组合命中 / 拆组合 /
 * 双人组合 / 三人体系分析都以这里的口径为准。本文件只做前端交互，数据来自
 * GET/POST /api/v3/custom-combos，英雄资料通过 getMetadata() getter 读 app.js
 * 的 metadata.icons / metadata.heroTypes（window.metadata 不可靠，不直接读全局）。
 *
 * 外壳（app.js）只给一个挂载点：
 *     <div data-cp-root></div>
 * 模块自己取数、渲染、绑定；切路由时 dispose() 断请求与监听。
 */
import { glyph } from './ui-icons.js';
import { currentCompetitionId, currentCompetitionName, saveSnapshot } from './rule-snapshots.js?v=20261124snap';

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

const text = (value) => String(value ?? '').trim();
const defaultEsc = (value) => text(value).replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

export function createComboPoolPage(h = {}) {
  const esc = h.esc || defaultEsc;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const getMetadata = typeof h.getMetadata === 'function' ? h.getMetadata : () => ({});
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const portrait = typeof h.portrait === 'function' ? h.portrait : (name, cls = '') => {
    const url = getMetadata().icons?.[name];
    if (/^\/catalog\/icons\/hero-\d+\.png$/.test(url || '')) {
      return `<img class="portrait ${cls}" src="${esc(url)}" alt="${esc(name)}" loading="lazy">`;
    }
    return `<span class="portrait portrait-placeholder ${cls}" aria-label="${esc(name || '未知英雄')}">${esc((name || '?')[0])}</span>`;
  };

  const LIST_URL = `${API_BASE}/api/v3/custom-combos`;
  const META_URL = `${API_BASE}/api/metadata/icons`;
  const uid = 'cp-' + Math.random().toString(36).slice(2, 9);

  let root = null;
  let controller = null;
  let generation = 0;
  let localMeta = null;          // getter 还没数据时的一轮回退缓存
  let liveNode = null;
  let bound = null;

  const state = { ready: false, loading: false, revision: 0, updatedAt: '', pairs: [], trios: [],
    savedPairs: [], savedTrios: [] };
  const ui = {
    lane: '全部', query: '', listQuery: '', selected: [], editing: null,
    saving: false, pendingDelete: null, notice: '', error: false,
    // 「已有组合」的头像筛选器（与上方"已选英雄"完全独立）。
    filterHeroes: [], filterLane: '全部', filterQuery: '', filterMode: 'exact',
  };
  const MAX_SELECT = 3;

  /* ── 播报：优先用外壳传进来的 notify，否则自己维护一个 polite live region ── */
  function announce(message) {
    if (notify) { notify(message); return; }
    if (!liveNode || !liveNode.isConnected) {
      liveNode = document.createElement('div');
      liveNode.setAttribute('role', 'status');
      liveNode.setAttribute('aria-live', 'polite');
      liveNode.style.cssText = 'position:fixed;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap';
      document.body.append(liveNode);
    }
    liveNode.textContent = message;
  }
  function setNotice(message, { error = false, quiet = false } = {}) {
    ui.notice = text(message);
    ui.error = Boolean(error);
    paintStatus();
    if (!quiet && ui.notice) announce(ui.notice);
  }

  /* ── 英雄资料 ─────────────────────────────────────────────────────── */
  function meta() {
    const outer = getMetadata() || {};
    return {
      icons: outer.icons || localMeta?.icons || {},
      heroTypes: outer.heroTypes || localMeta?.heroTypes || {},
    };
  }
  function heroNames() {
    const { icons, heroTypes } = meta();
    const names = Object.keys(heroTypes).length ? Object.keys(heroTypes) : Object.keys(icons);
    return names.filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }
  function lanesOf(name) {
    const row = meta().heroTypes[name] || {};
    return LANES.filter((lane) => row[lane] !== undefined && row[lane] !== null && row[lane] !== '');
  }
  function filteredHeroes() {
    const q = ui.query.toLowerCase();
    return heroNames().filter((name) =>
      (ui.lane === '全部' || lanesOf(name).includes(ui.lane)) && (!q || name.toLowerCase().includes(q)));
  }
  /* 已有组合筛选：文本查询 + 头像多选叠加。
     头像筛选按「组合英雄集合包含全部所选英雄」判定；选 2 个只筛双人池、选 3 个只筛三人池
     （另一池显示空），与「选 2 进组合池、选 3 进体系池」的口径一致。 */
  function matchesText(entry, q) {
    if (!q) return true;
    return entryName(entry).toLowerCase().includes(q)
      || (entry.heroes || []).some((hero) => String(hero).toLowerCase().includes(q))
      || String(entry.note || '').toLowerCase().includes(q);
  }
  function filteredEntries(kind) {
    const list = kind === 'pairs' ? state.pairs : state.trios;
    const q = ui.listQuery.toLowerCase();
    const picks = ui.filterHeroes;
    // 精确模式：选 2 个只查双人池、选 3 个只查三人池；包含模式：任何池只要包含所选英雄即可。
    if (picks.length && ui.filterMode === 'exact' && picks.length !== (kind === 'pairs' ? 2 : 3)) return [];
    return list.filter((entry) => {
      if (!matchesText(entry, q)) return false;
      if (!picks.length) return true;
      const heroes = new Set(entry.heroes || []);
      return picks.every((name) => heroes.has(name));
    });
  }
  /* 头像筛选器的英雄列表（独立分路/名字筛选，不动英雄池的 ui.lane/ui.query）。 */
  function filteredFilterHeroes() {
    const q = ui.filterQuery.toLowerCase();
    return heroNames().filter((name) =>
      (ui.filterLane === '全部' || lanesOf(name).includes(ui.filterLane))
      && (!q || name.toLowerCase().includes(q)));
  }
  function toggleFilterHero(name) {
    const at = ui.filterHeroes.indexOf(name);
    if (at >= 0) ui.filterHeroes.splice(at, 1);
    else {
      if (ui.filterHeroes.length >= MAX_SELECT) ui.filterHeroes.shift(); // 满 3 个时顶掉最早的，保持"选 2/3 个"
      ui.filterHeroes.push(name);
    }
    paintFilterGrid(); paintFilterChips(); paintLists();
    announce(at >= 0 ? `已取消筛选 ${name}` : `筛选条件：${ui.filterHeroes.join('、')}（已选 ${ui.filterHeroes.length} 个）`);
  }
  function clearFilter() {
    if (!ui.filterHeroes.length) return;
    ui.filterHeroes = [];
    paintFilterGrid(); paintFilterChips(); paintLists();
    announce('已清空头像筛选');
  }
  /* 批量导入：按分隔符拆成英雄名，用别名容错，去重后最多选 MAX_SELECT 个。
     返回 {added, skipped, unknown, overflow}，调用方据此播报。 */
  function addHeroNames(raw) {
    const known = heroNames();
    const byName = new Map(known.map((name) => [name.toLowerCase(), name]));
    const parts = String(raw || '').split(/[\s,，、;；/|]+/).map(text).filter(Boolean);
    const result = { added: [], skipped: [], unknown: [], overflow: false };
    for (const part of parts) {
      const hit = byName.get(part.toLowerCase());
      if (!hit) { result.unknown.push(part); continue; }
      if (ui.selected.includes(hit)) { result.skipped.push(hit); continue; }
      if (ui.selected.length >= MAX_SELECT) { result.overflow = true; break; }
      ui.selected.push(hit);
      result.added.push(hit);
    }
    paintGrid();
    paintSelected();
    return result;
  }
  /* 按当前分路批量选：把该分路英雄依次加入，直到选满 MAX_SELECT。 */
  function addLaneHeroes() {
    if (ui.lane === '全部') {
      setNotice('请先选一个具体分路，再点「选本分路」。', { error: true });
      return;
    }
    let added = 0;
    for (const name of filteredHeroes()) {
      if (ui.selected.length >= MAX_SELECT) break;
      if (ui.selected.includes(name)) continue;
      ui.selected.push(name);
      added += 1;
    }
    paintGrid();
    paintSelected();
    setNotice(added ? `已加入 ${added} 个「${ui.lane}」英雄${ui.selected.length >= MAX_SELECT ? '（已达 3 个上限）' : ''}。`
      : '当前分路没有更多可加入的英雄。');
  }
  /* 空状态一键补充：把内置默认的该池条目加进来（跳过已存在的英雄组合）。 */
  async function addBuiltin(kind) {
    try {
      const response = await fetch(`${API_BASE}/api/v3/custom-combos/builtin`, {
        headers: { Accept: 'application/json' }, signal: controller?.signal,
      });
      if (!response.ok) throw new Error(`读取内置默认失败（${response.status}）`);
      const doc = await response.json();
      const incoming = (kind === 'pairs' ? doc.pairs : doc.trios) || [];
      const key = (row) => JSON.stringify([...row.heroes].sort());
      const existing = new Set((kind === 'pairs' ? state.pairs : state.trios).map(key));
      const additions = incoming.filter((row) => !existing.has(key(row))).map((row) => ({ ...row, id: newId() }));
      if (!additions.length) { setNotice('内置默认里没有可补充的新组合。'); return; }
      const nextPairs = kind === 'pairs' ? state.pairs.concat(additions) : state.pairs.slice();
      const nextTrios = kind === 'trios' ? state.trios.concat(additions) : state.trios.slice();
      await save(nextPairs, nextTrios, `已从内置默认补充 ${additions.length} 条${kind === 'pairs' ? '双人组合' : '三人体系'}。`);
    } catch (error) {
      if (error.name !== 'AbortError') setNotice(error.message || '补充失败，请稍后重试。', true);
    }
  }
  async function ensureHeroes() {
    const outer = getMetadata() || {};
    if (Object.keys(outer.icons || {}).length || Object.keys(outer.heroTypes || {}).length || localMeta) return;
    try {
      const response = await fetch(META_URL, { headers: { Accept: 'application/json' } });
      if (response.ok) localMeta = await response.json();
    } catch { /* 头像暂时缺失时仍可用文字选择 */ }
  }

  /* ── 数据 ─────────────────────────────────────────────────────────── */
  function applyPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    state.revision = Number(payload.revision) || 0;
    state.updatedAt = text(payload.updatedAt);
    state.pairs = Array.isArray(payload.pairs) ? payload.pairs : [];
    state.trios = Array.isArray(payload.trios) ? payload.trios : [];
    state.savedPairs = JSON.parse(JSON.stringify(state.pairs));
    state.savedTrios = JSON.parse(JSON.stringify(state.trios));
  }
  function dirty() {
    return JSON.stringify(state.pairs) !== JSON.stringify(state.savedPairs)
      || JSON.stringify(state.trios) !== JSON.stringify(state.savedTrios);
  }

  function entryOf(kind, id) {
    const list = kind === 'pairs' ? state.pairs : state.trios;
    return list.find((item) => String(item?.id) === String(id)) || null;
  }
  const entryName = (entry) => text(entry?.name) || (entry?.heroes || []).join(' + ') || '未命名';

  async function load({ quiet = false, keepNotice = false } = {}) {
    if (!root) return;
    const gen = ++generation;
    state.loading = true;
    if (!keepNotice) setNotice('正在读取组合池…', { quiet: true });
    try {
      const response = await fetch(LIST_URL, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal,
      });
      if (!response.ok) throw new Error(`读取组合池失败（${response.status}）`);
      const payload = await response.json();
      if (gen !== generation || !root) return;
      applyPayload(payload);
      state.ready = true;
      paintLists();
      paintSelected();
      if (!quiet) setNotice(`组合池已读取：双人 ${state.pairs.length} 条，三人 ${state.trios.length} 条。`);
      else if (!keepNotice) setNotice('', { quiet: true });
    } catch (error) {
      if (gen !== generation || !root || keepNotice) return;
      setNotice(error.message || '组合池读取失败，请点「重新读取」重试。', { error: true });
    } finally {
      if (gen === generation) state.loading = false;
    }
  }

  async function save(nextPairs, nextTrios, successText) {
    if (ui.saving) return false;
    ui.saving = true;
    paintSelected();
    try {
      const response = await fetch(LIST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ revision: state.revision, pairs: nextPairs, trios: nextTrios }),
      });
      if (response.status === 409) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || '保存冲突：组合池已被其他人修改，请点「重新读取」后再试。');
      }
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || `保存失败（${response.status}）`);
      }
      const payload = await response.json().catch(() => ({}));
      state.revision = Number(payload.revision) || state.revision + 1;
      state.updatedAt = text(payload.updatedAt) || new Date().toISOString();
      state.pairs = nextPairs;
      state.trios = nextTrios;
      paintLists();
      /* 保存成功后以服务端为准刷新列表；这次后台读取不覆盖刚成功的提示。 */
      await load({ quiet: true, keepNotice: true });
      setNotice(successText);
      /* 通知外壳失效 KPL 组合全库缓存：保存后同一会话再开英雄组合页要看到新名单。 */
      document.dispatchEvent(new CustomEvent('combo-pool:saved'));
      return true;
    } catch (error) {
      setNotice(error.message || '保存失败，请稍后重试。', { error: true });
      return false;
    } finally {
      ui.saving = false;
      paintSelected();
    }
  }

  /** 组合池的增删改即时落盘，因此这里直接把当下整份池打包到当前赛事。 */
  async function snapshotCurrent() {
    const compId = currentCompetitionId();
    if (!compId) { setNotice('请先在顶栏选择赛事，再保存快照。', { error: true }); return; }
    try {
      const result = await saveSnapshot('combos', compId, '组合池设置 · 赛事快照', API_BASE);
      setNotice(`已把组合池存到「${currentCompetitionName() || compId}」快照（第 ${result.revision} 版）。`);
    } catch (error) {
      setNotice(error.message || '赛事快照保存失败。', { error: true });
    }
  }

  /* ── 选择区状态 ───────────────────────────────────────────────────── */
  const countOf = (kind) => (kind === 'pairs' ? 2 : 3);
  function expectedKind() {
    if (ui.editing) {
      return ui.selected.length === countOf(ui.editing.kind) ? ui.editing.kind : null;
    }
    if (ui.selected.length === 2) return 'pairs';
    if (ui.selected.length === 3) return 'trios';
    return null;
  }
  const newId = () => `cp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  function toggleHero(name, restoreFocus = true) {
    const at = ui.selected.indexOf(name);
    if (at >= 0) ui.selected.splice(at, 1);
    else ui.selected.push(name);
    paintGrid();
    paintSelected();
    if (restoreFocus) {
      const again = [...(root?.querySelectorAll('[data-cp-hero]') || [])]
        .find((node) => node.dataset.cpHero === name);
      again?.focus();
    }
  }
  function resetSelection() {
    ui.selected = [];
    ui.editing = null;
    const name = root?.querySelector('[data-cp-name]');
    if (name) name.value = '';
    const strong = root?.querySelector('[data-cp-strength="strong"]');
    const weak = root?.querySelector('[data-cp-strength="weak"]');
    if (strong) strong.checked = true;
    if (weak) weak.checked = false;
    paintGrid();
    paintSelected();
  }
  function startEdit(kind, id) {
    const entry = entryOf(kind, id);
    if (!entry) return;
    ui.editing = { kind, id: entry.id };
    ui.selected = (entry.heroes || []).slice(0, countOf(kind));
    paintGrid();
    paintSelected();
    const name = root?.querySelector('[data-cp-name]');
    if (name) name.value = entryName(entry);
    const strong = root?.querySelector('[data-cp-strength="strong"]');
    const weak = root?.querySelector('[data-cp-strength="weak"]');
    if (strong) strong.checked = entry.strength !== 'weak';
    if (weak) weak.checked = entry.strength === 'weak';
    setNotice(`已把「${entryName(entry)}」回填到选择区，修改后点保存。`);
    name?.focus();
    root?.querySelector('.cp-selected')?.scrollIntoView?.({ block: 'nearest' });
  }
  function requestDelete(kind, id) {
    const entry = entryOf(kind, id);
    const dialog = root?.querySelector('[data-cp-dialog]');
    if (!entry || !dialog) return;
    ui.pendingDelete = { kind, id: entry.id };
    const label = kind === 'pairs' ? '双人组合' : '三人体系';
    const target = root.querySelector('[data-cp-dialog-text]');
    if (target) target.textContent = `确定删除${label}「${entryName(entry)}」吗？删除会立即保存到组合池。`;
    dialog.showModal();
  }

  /* ── 渲染 ─────────────────────────────────────────────────────────── */
  function laneButtons() {
    return ['全部', ...LANES].map((lane) => `<button type="button" class="cp-lane${lane === ui.lane ? ' is-on' : ''}"
        data-cp-lane="${esc(lane)}" aria-pressed="${lane === ui.lane}">${esc(lane)}</button>`).join('');
  }
  function filterLaneButtons() {
    return ['全部', ...LANES].map((lane) => `<button type="button" class="cp-lane${lane === ui.filterLane ? ' is-on' : ''}"
        data-cp-filter-lane="${esc(lane)}" aria-pressed="${lane === ui.filterLane}">${esc(lane)}</button>`).join('');
  }
  function paintLanes() {
    root?.querySelectorAll('[data-cp-lane]').forEach((node) => {
      const on = node.dataset.cpLane === ui.lane;
      node.setAttribute('aria-pressed', String(on));
      node.classList.toggle('is-on', on);
    });
    const pick = root?.querySelector('[data-cp-lane-pick]');
    if (pick) pick.disabled = ui.lane === '全部';
  }
  function paintGrid() {
    const grid = root?.querySelector('[data-cp-grid]');
    if (!grid) return;
    const list = filteredHeroes();
    if (!list.length) {
      grid.innerHTML = `<p class="cp-empty">${heroNames().length
        ? '没有匹配的英雄，换个关键词或分路试试。' : '英雄资料还没到位，稍后会自动刷新。'}</p>`;
      return;
    }
    grid.innerHTML = list.map((name) => {
      const on = ui.selected.includes(name);
      const lanes = lanesOf(name).join(' / ');
      return `<button type="button" class="cp-hero${on ? ' is-on' : ''}" data-cp-hero="${esc(name)}"
          aria-pressed="${on}"${lanes ? ` title="${esc(name)} · ${esc(lanes)}"` : ''}>
          <span class="cp-hero-face" aria-hidden="true">${portrait(name)}</span>
          <span class="cp-hero-name" title="${esc(name)}">${esc(name)}</span>
        </button>`;
    }).join('');
  }
  /* ── 已有组合的头像筛选器（独立状态，复用头像/分路渲染）──────────── */
  function paintFilterLanes() {
    root?.querySelectorAll('[data-cp-filter-lane]').forEach((node) => {
      const on = node.dataset.cpFilterLane === ui.filterLane;
      node.setAttribute('aria-pressed', String(on));
      node.classList.toggle('is-on', on);
    });
  }
  function paintFilterGrid() {
    const grid = root?.querySelector('[data-cp-filter-grid]');
    if (!grid) return;
    const list = filteredFilterHeroes();
    if (!list.length) {
      grid.innerHTML = '<p class="cp-empty">没有匹配的英雄，换个关键词或分路试试。</p>';
      return;
    }
    grid.innerHTML = list.map((name) => {
      const on = ui.filterHeroes.includes(name);
      const lanes = lanesOf(name).join(' / ');
      return `<button type="button" class="cp-hero${on ? ' is-on' : ''}" data-cp-filter-hero="${esc(name)}"
          aria-pressed="${on}"${lanes ? ` title="${esc(name)} · ${esc(lanes)}"` : ''}>
          <span class="cp-hero-face" aria-hidden="true">${portrait(name, 'portrait-sm')}</span>
          <span class="cp-hero-name" title="${esc(name)}">${esc(name)}</span>
        </button>`;
    }).join('');
  }
  function paintFilterChips() {
    const holder = root?.querySelector('[data-cp-filter-chips]');
    if (!holder) return;
    const n = ui.filterHeroes.length;
    holder.innerHTML = ui.filterHeroes.length ? ui.filterHeroes.map((name) => `<span class="cp-chip">
        <span class="cp-chip-face" aria-hidden="true">${portrait(name, 'portrait-sm')}</span>
        <span>${esc(name)}</span>
        <button type="button" class="cp-chip-x" data-cp-filter-remove="${esc(name)}"
          aria-label="取消筛选 ${esc(name)}">×</button>
      </span>`).join('') : '';
    const clear = root.querySelector('[data-cp-filter-clear]');
    if (clear) clear.disabled = !n;
    const summaryCount = root.querySelector('[data-cp-filter-summary-count]');
    if (summaryCount) summaryCount.textContent = n ? `（已选 ${n} 个）` : '';
    const hint = root.querySelector('[data-cp-filter-hint]');
    if (hint) {
      if (!n) hint.textContent = '';
      else if (ui.filterMode === 'include') hint.textContent = `包含匹配：正在查找包含这 ${n} 个英雄的所有组合（双人 / 三人均可）。`;
      else hint.textContent = n === 2 ? '精确匹配：正在筛选包含这两人的双人组合。'
        : '精确匹配：正在筛选包含这三人的三人体系。';
    }
    root?.querySelectorAll('[data-cp-filter-mode]').forEach((node) => {
      const on = node.dataset.cpFilterMode === ui.filterMode;
      node.setAttribute('aria-pressed', String(on));
      node.classList.toggle('is-on', on);
    });
  }
  function paintSelected() {
    const holder = root?.querySelector('[data-cp-selected]');
    if (!holder) return;
    holder.innerHTML = ui.selected.length ? ui.selected.map((name) => `<span class="cp-chip">
        <span class="cp-chip-face" aria-hidden="true">${portrait(name, 'portrait-sm')}</span>
        <span>${esc(name)}</span>
        <button type="button" class="cp-chip-x" data-cp-chip-remove="${esc(name)}"
          aria-label="从已选中移除 ${esc(name)}">×</button>
      </span>`).join('') : `<div class="cp-selected-empty">
        <p><b>还没有选英雄。</b>从上方英雄池开始：选 2 个加入双人组合池，选 3 个加入三人体系池。</p>
        <button type="button" class="control cp-empty-action" data-cp-start-pick>${glyph('heroes', { size: 18 })}去选择英雄</button>
      </div>`;

    const clear = root.querySelector('[data-cp-clear]');
    if (clear) clear.disabled = !ui.selected.length;
    const kind = expectedKind();
    const submit = root.querySelector('[data-cp-submit]');
    const hint = root.querySelector('[data-cp-form-hint]');
    const strength = root.querySelector('[data-cp-strength-wrap]');
    const cancel = root.querySelector('[data-cp-cancel-edit]');
    if (submit) {
      /* 数量无效时不让提交进入保存链路；原因始终显示在旁边，禁用态也有明确文案。 */
      submit.disabled = ui.saving || !kind;
      submit.title = !kind ? '请先选择 2 个或 3 个英雄' : '';
      submit.setAttribute('aria-describedby', `${uid}-form-hint`);
      submit.innerHTML = `${glyph('hero-pool', { size: 18 })}<span>${ui.editing ? '保存修改'
        : kind === 'pairs' ? '加入双人组合池'
          : kind === 'trios' ? '加入三人体系池' : '加入组合池'}</span>`;
    }
    if (hint) {
      hint.textContent = ui.selected.length > MAX_SELECT
        ? `已选 ${ui.selected.length} 个，超过上限：最多 3 个。请移除多余的。`
        : ui.editing && !kind
          ? `编辑${ui.editing.kind === 'pairs' ? '双人组合' : '三人体系'}需要保持 ${countOf(ui.editing.kind)} 个英雄，当前 ${ui.selected.length} 个。`
          : !kind ? `当前已选 ${ui.selected.length} 个：选 2 个加入组合池，选 3 个加入体系池。`
            : ui.editing ? '保存后会覆盖原来的条目。' : '可以填名字；双人组合还要选联动强弱。';
    }
    if (strength) strength.hidden = !kind;   // 双人和三人都要选强弱
    if (cancel) {
      cancel.hidden = !ui.editing;
      cancel.disabled = ui.saving;
    }
  }

  function rowHtml(kind, entry) {
    const heroes = Array.isArray(entry.heroes) ? entry.heroes : [];
    const name = entryName(entry);
    const label = kind === 'pairs' ? '双人组合' : '三人体系';
    // 老数据（内置默认之前的 trio）可能没有 strength，默认按强联动显示。
    const tag = `<span class="cp-tag ${entry.strength === 'weak' ? 'is-weak' : 'is-strong'}">${entry.strength === 'weak' ? '弱联动' : '强联动'}</span>`;
    const faces = heroes.map((hero) => `<span class="cp-row-face" aria-hidden="true">${portrait(hero, 'portrait-sm')}</span>`).join('');
    return `<li class="cp-entry" data-cp-entry="${esc(entry.id)}">
        <span class="cp-row-faces">${faces}</span>
        <span class="cp-row-body"><b>${esc(name)}</b><small>${esc(heroes.join(' + '))}${entry.note ? ` · ${esc(entry.note)}` : ''}</small></span>
        ${tag}
        <span class="cp-row-actions">
          <button type="button" class="control cp-icon-btn" data-cp-edit="${esc(entry.id)}" data-cp-kind="${kind}"
            aria-label="编辑${label} ${esc(name)}" title="编辑">${glyph('edit', { size: 18 })}</button>
          <button type="button" class="control cp-icon-btn cp-danger" data-cp-delete="${esc(entry.id)}" data-cp-kind="${kind}"
            aria-label="删除${label} ${esc(name)}" title="删除">${glyph('trash', { size: 18 })}</button>
        </span>
      </li>`;
  }
  function listMarkup(kind, list, emptyText) {
    if (list.length) return list.map((entry) => rowHtml(kind, entry)).join('');
    const label = kind === 'pairs' ? '双人组合' : '三人体系';
    if (ui.filterHeroes.length) {
      const need = kind === 'pairs' ? 2 : 3;
      if (ui.filterMode === 'exact' && ui.filterHeroes.length !== need) {
        return `<li class="cp-empty">精确模式下选 ${need} 个英雄才查${label}；或切换到「包含匹配」跨池查找。</li>`;
      }
      return `<li class="cp-empty">没有${ui.filterMode === 'include' ? '包含' : '同时包含'}「${esc(ui.filterHeroes.join('、'))}」的${label}。</li>`;
    }
    const builtinBtn = (!ui.listQuery && !ui.filterHeroes.length)
      ? ` <button type="button" class="control cp-add-builtin" data-cp-add-builtin="${kind}" aria-label="从内置默认补充${label}">${glyph('refresh', { size: 18 })}从内置默认补充</button>` : '';
    return `<li class="cp-empty">${ui.listQuery
      ? `没有匹配「${esc(ui.listQuery)}」的${label}。` : emptyText}${builtinBtn}</li>`;
  }
  function paintLists() {
    const pairs = root?.querySelector('[data-cp-pairs]');
    const trios = root?.querySelector('[data-cp-trios]');
    if (!pairs || !trios) return;
    const shownPairs = filteredEntries('pairs');
    const shownTrios = filteredEntries('trios');
    pairs.innerHTML = listMarkup('pairs', shownPairs, '还没有双人组合。上方选 2 个英雄即可加入。');
    trios.innerHTML = listMarkup('trios', shownTrios, '还没有三人体系。上方选 3 个英雄即可加入。');
    const pairCount = root.querySelector('[data-cp-pair-count]');
    const trioCount = root.querySelector('[data-cp-trio-count]');
    const stats = root.querySelector('[data-cp-strength-stats]');
    const filtering = Boolean(ui.listQuery) || ui.filterHeroes.length > 0;
    const countText = (shown, all) => filtering ? `匹配 ${shown} / ${all} 条` : `共 ${all} 条`;
    if (pairCount) pairCount.textContent = countText(shownPairs.length, state.pairs.length);
    if (trioCount) trioCount.textContent = countText(shownTrios.length, state.trios.length);
    /* 两个池数量悬殊时别各占一半：长列表给宽列，短列表收成侧栏并顶部对齐。 */
    const grid = root.querySelector('.cp-existing-grid');
    if (grid) {
      const long = Math.max(shownPairs.length, shownTrios.length);
      const short = Math.min(shownPairs.length, shownTrios.length);
      const skewed = long >= 6 && short * 4 <= long;
      grid.classList.toggle('is-pair-heavy', skewed && shownPairs.length >= shownTrios.length);
      grid.classList.toggle('is-trio-heavy', skewed && shownTrios.length > shownPairs.length);
    }
    if (stats) {
      const strong = state.pairs.filter((entry) => entry.strength !== 'weak').length;
      const weak = state.pairs.length - strong;
      stats.innerHTML = `<span class="cp-stat cp-stat-strong">强 ${strong}</span><span class="cp-stat cp-stat-weak">弱 ${weak}</span>`;
    }
  }
  function paintStatus() {
    const node = root?.querySelector('[data-cp-status]');
    if (!node) return;
    node.textContent = ui.notice;
    node.classList.toggle('is-error', ui.error);
    node.hidden = !ui.notice;
  }
  function paintAll() {
    paintLanes(); paintGrid(); paintSelected();
    paintFilterLanes(); paintFilterGrid(); paintFilterChips();
    paintLists(); paintStatus();
  }

  /* 页面骨架：除动态面板外全部静态，事件用委托挂在 root 上，不使用内联 onclick。 */
  function html(data) {
    if (data) applyPayload(data);
    return `<div class="cp-page">
      <section class="section cp-lead">
        <div class="section-heading"><div>
          <h1>组合池设置</h1>
        </div>
          <div class="cp-head-actions">
            <button type="button" class="control" data-cp-snapshot>${glyph('export', { size: 18 })}存为当前赛事快照</button>
            <button type="button" class="control" data-cp-reload>${glyph('refresh', { size: 18 })}重新读取</button></div></div>
        <!-- 可见状态条只给人看；播报统一走 notify 的单一 polite live region，避免读两遍。 -->
        <p class="cp-status" data-cp-status hidden></p>
      </section>

      <section class="section cp-pool">
        <div class="section-heading"><div><h2>英雄池</h2></div></div>
        <search class="cp-search">
          <label class="visually-hidden" for="${uid}-search">按英雄名搜索</label>
          <input id="${uid}-search" type="search" data-cp-search placeholder="搜索英雄名" autocomplete="off" spellcheck="false">
        </search>
        <div class="cp-lanes" role="group" aria-label="按分路筛选英雄">${laneButtons()}</div>
        <div class="cp-lane-actions" role="group" aria-label="按当前分路批量选择">
          <button type="button" class="control cp-lane-pick" data-cp-lane-pick disabled>${glyph('pick', { size: 18 })}选本分路</button>
        </div>
        <div class="cp-grid-scroller" data-cp-grid-scroller>
          <div class="cp-grid cp-grid--bounded" data-cp-grid></div>
        </div>
      </section>

      <section class="section cp-selected">
       <div class="cp-selected-inner">
        <div class="section-heading"><div><h2>已选英雄</h2></div>
          <button type="button" class="control" data-cp-clear disabled>${glyph('trash', { size: 18 })}清空</button></div>
        <div class="cp-chips" data-cp-selected></div>
       </div>
      </section>

      <!-- 批量导入与命名表单不跟随滚动：sticky 区只保留已选头像和操作入口。 -->
      <section class="section cp-compose">
        <details class="cp-batch">
          <summary>${glyph('export', { size: 18 })}批量导入 / 按分路选</summary>
          <form class="cp-batch-form" data-cp-batch-form aria-label="批量加入英雄">
            <label class="visually-hidden" for="${uid}-batch">批量粘贴英雄名</label>
            <input id="${uid}-batch" type="text" data-cp-batch placeholder="粘贴英雄名，空格 / 逗号 / 顿号分隔"
              autocomplete="off" spellcheck="false">
            <button type="submit" class="control" data-cp-batch-add>${glyph('pick', { size: 18 })}加入已选</button>
          </form>
        </details>
        <form class="cp-form" data-cp-form aria-labelledby="${uid}-form-title">
          <p class="visually-hidden" id="${uid}-form-title">加入组合池</p>
          <div class="cp-form-row">
            <label for="${uid}-name">名称 <span aria-hidden="true">*</span></label>
            <input id="${uid}-name" data-cp-name type="text" maxlength="40" required autocomplete="off"
              placeholder="给这组联动起个名字">
          </div>
          <fieldset class="cp-strength" data-cp-strength-wrap>
            <legend>联动强弱</legend>
            <label><input type="radio" data-cp-strength="strong" name="${uid}-strength" value="strong" checked> 强联动</label>
            <label><input type="radio" data-cp-strength="weak" name="${uid}-strength" value="weak"> 弱联动</label>
          </fieldset>
          <p class="cp-form-hint" id="${uid}-form-hint" data-cp-form-hint></p>
          <div class="cp-form-foot">
            <button type="button" class="control cp-cancel-edit" data-cp-cancel-edit hidden>${glyph('ban', { size: 18 })}取消编辑</button>
            <button type="submit" class="primary" data-cp-submit disabled>${glyph('hero-pool', { size: 18 })}加入组合池</button>
          </div>
        </form>
      </section>

      <section class="section cp-existing">
        <div class="section-heading"><div><h2>已有组合</h2></div></div>
        <details class="cp-filter" data-cp-filter>
          <summary>${glyph('heroes', { size: 18 })}用英雄头像筛选组合 <span class="cp-filter-summary-count" data-cp-filter-summary-count></span></summary>
          <div class="cp-filter-body">
            <div class="cp-filter-tools">
              <label class="visually-hidden" for="${uid}-filter-search">在筛选器内搜索英雄</label>
              <input id="${uid}-filter-search" type="search" data-cp-filter-search placeholder="搜索英雄名" autocomplete="off" spellcheck="false">
              <div class="cp-filter-lanes" role="group" aria-label="筛选器按分路筛选英雄">${filterLaneButtons()}</div>
            </div>
            <p class="cp-filter-hint" data-cp-filter-hint></p>
            <div class="cp-filter-mode" role="group" aria-label="筛选匹配方式">
              <button type="button" class="cp-lane${ui.filterMode === 'exact' ? ' is-on' : ''}" data-cp-filter-mode="exact" aria-pressed="${ui.filterMode === 'exact'}">${glyph('shield', { size: 18 })}精确匹配（按人数分池）</button>
              <button type="button" class="cp-lane${ui.filterMode === 'include' ? ' is-on' : ''}" data-cp-filter-mode="include" aria-pressed="${ui.filterMode === 'include'}">${glyph('heroes', { size: 18 })}包含匹配（跨池查找）</button>
            </div>
            <div class="cp-filter-chips" data-cp-filter-chips></div>
            <div class="cp-filter-grid cp-grid-scroller" data-cp-grid-scroller>
              <div class="cp-grid cp-grid--bounded" data-cp-filter-grid></div>
            </div>
            <button type="button" class="control cp-filter-clear" data-cp-filter-clear disabled>${glyph('trash', { size: 18 })}清空筛选</button>
          </div>
        </details>
        <search class="cp-list-search">
          <label class="visually-hidden" for="${uid}-list-search">搜索已有组合</label>
          <input id="${uid}-list-search" type="search" data-cp-list-search
            placeholder="按英雄名 / 组合名 / 备注筛选已有组合" autocomplete="off" spellcheck="false">
        </search>
        <div class="cp-existing-grid">
          <div class="cp-list-wrap"><h3>双人组合池 <span class="cp-count" data-cp-pair-count></span></h3>
            <div class="cp-strength-stats" data-cp-strength-stats></div>
            <ul class="cp-list" data-cp-pairs role="list"></ul></div>
          <div class="cp-list-wrap"><h3>三人体系池 <span class="cp-count" data-cp-trio-count></span></h3>
            <ul class="cp-list" data-cp-trios role="list"></ul></div>
        </div>
      </section>

      <dialog class="cp-dialog" data-cp-dialog aria-labelledby="${uid}-dialog-title" closedby="closerequest">
        <h2 id="${uid}-dialog-title">确认删除</h2>
        <p data-cp-dialog-text></p>
        <form method="dialog" class="cp-dialog-actions" aria-label="确认删除组合">
          <button type="submit" value="cancel" class="control" autofocus>${glyph('ban', { size: 18 })}取消</button>
          <button type="submit" value="delete" class="cp-delete-btn">${glyph('trash', { size: 18 })}删除</button>
        </form>
      </dialog>
    </div>`;
  }

  /* ── 事件 ─────────────────────────────────────────────────────────── */
  function onClick(event) {
    /* 头像筛选器（已有组合查看区）——与上方"已选英雄"状态完全独立。 */
    const filterLane = event.target.closest('[data-cp-filter-lane]');
    if (filterLane) {
      ui.filterLane = text(filterLane.dataset.cpFilterLane);
      paintFilterLanes(); paintFilterGrid();
      return;
    }
    const filterHero = event.target.closest('[data-cp-filter-hero]');
    if (filterHero) { toggleFilterHero(text(filterHero.dataset.cpFilterHero)); return; }
    const filterRemove = event.target.closest('[data-cp-filter-remove]');
    if (filterRemove) { toggleFilterHero(text(filterRemove.dataset.cpFilterRemove)); return; }
    if (event.target.closest('[data-cp-filter-clear]')) { clearFilter(); return; }
    const addBuiltinBtn = event.target.closest('[data-cp-add-builtin]');
    if (addBuiltinBtn) { addBuiltin(text(addBuiltinBtn.dataset.cpAddBuiltin)); return; }
    const filterMode = event.target.closest('[data-cp-filter-mode]');
    if (filterMode) {
      ui.filterMode = filterMode.dataset.cpFilterMode === 'include' ? 'include' : 'exact';
      paintFilterChips(); paintLists();
      announce(ui.filterMode === 'include' ? '已切换到包含匹配：跨池查找包含所选英雄的组合' : '已切换到精确匹配');
      return;
    }

    const lane = event.target.closest('[data-cp-lane]');
    if (lane) {
      ui.lane = text(lane.dataset.cpLane);
      paintLanes(); paintGrid();
      announce(`已按${ui.lane}筛选英雄`);
      return;
    }
    const hero = event.target.closest('[data-cp-hero]');
    if (hero) { toggleHero(text(hero.dataset.cpHero)); return; }
    if (event.target.closest('[data-cp-lane-pick]')) { addLaneHeroes(); return; }
    if (event.target.closest('[data-cp-start-pick]')) {
      root?.querySelector('.cp-pool')?.scrollIntoView?.({ block: 'start' });
      root?.querySelector('[data-cp-search]')?.focus({ preventScroll: true });
      announce('请在英雄池中选择 2 个或 3 个英雄。');
      return;
    }
    const remove = event.target.closest('[data-cp-chip-remove]');
    if (remove) { toggleHero(text(remove.dataset.cpChipRemove), false); return; }
    if (event.target.closest('[data-cp-clear]')) {
      if (!ui.selected.length) return;
      resetSelection();
      setNotice('已清空选择。');
      return;
    }
    if (event.target.closest('[data-cp-reload]')) { load(); return; }
    if (event.target.closest('[data-cp-snapshot]')) { snapshotCurrent(); return; }
    if (event.target.closest('[data-cp-cancel-edit]')) {
      resetSelection();
      setNotice('已取消编辑。');
      return;
    }
    const edit = event.target.closest('[data-cp-edit]');
    if (edit) { startEdit(text(edit.dataset.cpKind), text(edit.dataset.cpEdit)); return; }
    const del = event.target.closest('[data-cp-delete]');
    if (del) { requestDelete(text(del.dataset.cpKind), text(del.dataset.cpDelete)); }
  }
  function onInput(event) {
    const input = event.target.closest('[data-cp-search]');
    if (input) {
      ui.query = input.value;    // 不重画 input 本身，保留焦点与光标
      paintGrid();
      return;
    }
    const listInput = event.target.closest('[data-cp-list-search]');
    if (listInput) {
      ui.listQuery = listInput.value;
      paintLists();              // 已有组合过滤，不重画搜索框
      return;
    }
    const filterInput = event.target.closest('[data-cp-filter-search]');
    if (filterInput) {
      ui.filterQuery = filterInput.value;
      paintFilterGrid();         // 只重画筛选器头像网格，保留焦点
    }
  }
  function onSubmit(event) {
    const form = event.target;
    if (form.matches?.('[data-cp-batch-form]')) {
      event.preventDefault();
      const field = form.querySelector('[data-cp-batch]');
      const result = addHeroNames(field?.value);
      if (field) field.value = '';
      const bits = [];
      if (result.added.length) bits.push(`已加入 ${result.added.length} 个`);
      if (result.skipped.length) bits.push(`重复 ${result.skipped.length} 个`);
      if (result.unknown.length) bits.push(`未识别「${result.unknown.join('、')}」`);
      if (result.overflow) bits.push('已达 3 个上限');
      setNotice(bits.length ? `${bits.join('，')}。` : '没有可加入的英雄名。', { error: !result.added.length });
      return;
    }
    if (!form.matches?.('[data-cp-form]')) return;
    event.preventDefault();
    const kind = expectedKind();
    if (!kind) {
      setNotice('请选择 2 个或 3 个英雄再保存。', { error: true });
      return;
    }
    const name = text(form.querySelector('[data-cp-name]')?.value).slice(0, 40);
    if (!name) {
      setNotice('请填写名称。', { error: true });
      form.querySelector('[data-cp-name]')?.focus();
      return;
    }
    const heroes = ui.selected.slice();
    const entry = { id: ui.editing ? ui.editing.id : newId(), heroes, name };
    // 双人与三人均记录联动强弱。
    entry.strength = form.querySelector('[data-cp-strength]:checked')?.value === 'weak' ? 'weak' : 'strong';
    const nextPairs = state.pairs.map((item) => ({ ...item }));
    const nextTrios = state.trios.map((item) => ({ ...item }));
    if (ui.editing) {
      const list = ui.editing.kind === 'pairs' ? nextPairs : nextTrios;
      const at = list.findIndex((item) => String(item.id) === String(ui.editing.id));
      if (at >= 0) list[at] = entry; else list.push(entry);
    } else {
      (kind === 'pairs' ? nextPairs : nextTrios).push(entry);
    }
    const editing = Boolean(ui.editing);
    const label = kind === 'pairs' ? '双人组合' : '三人体系';
    save(nextPairs, nextTrios, editing ? `已保存${label}修改。` : `已加入${label}池。`)
      .then((ok) => { if (ok) resetSelection(); });
  }
  function onDialogClose(event) {
    const dialog = event.target;
    const value = dialog.returnValue;
    dialog.returnValue = '';   // Esc 与各浏览器的残留值都可能干扰下一次判断
    const pending = ui.pendingDelete;
    ui.pendingDelete = null;
    if (value !== 'delete' || !pending) return;
    const nextPairs = state.pairs.filter((item) => String(item.id) !== String(pending.id));
    const nextTrios = state.trios.filter((item) => String(item.id) !== String(pending.id));
    save(nextPairs, nextTrios, '已删除，组合池已更新。');
  }

  const onSnapshotRestored = (event) => {
    if (event.detail?.module === 'combos') load({ quiet: true });
  };
  function bind(node) {
    bound = node;
    document.addEventListener('rule-snapshots:restored', onSnapshotRestored);
    node.addEventListener('click', onClick);
    node.addEventListener('input', onInput);
    node.addEventListener('submit', onSubmit);
    const dialog = node.querySelector('[data-cp-dialog]');
    dialog?.addEventListener('close', onDialogClose);
  }
  function dispose() {
    generation += 1;
    document.removeEventListener('rule-snapshots:restored', onSnapshotRestored);
    controller?.abort();
    controller = null;
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('input', onInput);
      bound.removeEventListener('submit', onSubmit);
      bound.querySelector('[data-cp-dialog]')?.removeEventListener('close', onDialogClose);
      bound = null;
    }
    root = null;
    ui.pendingDelete = null;
  }

  function mount(node, data) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    if (data) applyPayload(data);
    root.innerHTML = html();
    bind(root);
    controller = new AbortController();
    paintAll();
    ensureHeroes().then(() => { if (root === node) { paintGrid(); paintFilterGrid(); paintFilterChips(); } });
    load();
  }
  /* metadata 的头像目录后到时只重画头像，不动选区与表单输入。 */
  function rerender() {
    if (!root) return;
    paintGrid(); paintSelected(); paintLists();
    paintFilterGrid(); paintFilterChips();
  }

  return { html, render: html, mount, bind, dispose, rerender, state, announce };
}

export default createComboPoolPage;
