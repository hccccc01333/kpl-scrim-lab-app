/* 阵容标签：卡片墙 + 分路筛选 + 头像挑选（模块八，2026-11-22 二次改版）
 *
 * 自取数独立模块，外壳（app.js）只给一个挂载点：
 *     <div data-lt-root></div>       —— 设置页「阵容标签」tab
 * 模块自己读 /api/v3/lineup-tags（GET/POST）、/api/v3/lineup-tags/meta
 * （英雄名录 + 分路兜底）、/api/studio/workspace/competitions（赛事下拉）。
 * 英雄资料优先用外壳 metadata（icons / heroTypes=英雄×分路），后到或缺失时
 * 回退 meta 接口；头像统一走 h.portrait（真实游戏头像，拿不到时退占位字）。
 * 不改 app.js 的路由与挂载逻辑；切走页面时 dispose() 撤销在途请求与监听。
 *
 * 2026-11-22 按赛训组反馈改版：
 *   - 撤掉「口述文稿批量导入」与页面上的长说明文案，只留标签本身；
 *   - 已保存标签为卡片墙（标签名 + 5 个游戏头像 + 赛事记录）；
 *   - 新建 / 编辑为头像网格手动挑选：分路筛选（KPL 分路图标）→ 搜索 → 点 5 个；
 *   - 后端 load() 没保存过时给内置标签（DEFAULT_TAGS），教练改完保存即生效。
 */
const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const MAX_HEROES = 5;

/* 分路顺序与图标：图标来自 kpl-svg/modules/role-icon-*.svg（与十人面板同源）。 */
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const LANE_SLUG = { '对抗路': 'clash', '打野': 'jungle', '中路': 'mid', '发育路': 'farm', '游走': 'roam' };
const KPL_SVG = new URL('./kpl-svg/', import.meta.url).href;

const text = (value) => String(value ?? '').trim();
const defaultEsc = (value) => text(value).replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));
/* 比较用去括号：元流之子(坦克) 与 元流之子坦克 视作同一个名字。 */
const bare = (value) => text(value).replace(/[()（）]/g, '');

export function createLineupTagsPage(h = {}) {
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

  const LIST_URL = `${API_BASE}/api/v3/lineup-tags`;
  const META_URL = `${API_BASE}/api/v3/lineup-tags/meta`;
  const COMP_URL = `${API_BASE}/api/studio/workspace/competitions`;
  const ids = {
    search: `lt-${Math.random().toString(36).slice(2, 8)}-search`,
    name: `lt-${Math.random().toString(36).slice(2, 8)}-name`,
    competition: `lt-${Math.random().toString(36).slice(2, 8)}-comp`,
    note: `lt-${Math.random().toString(36).slice(2, 8)}-note`,
    dialog: `lt-${Math.random().toString(36).slice(2, 8)}-dialog`,
  };

  let root = null;
  let controller = null;
  let bound = null;
  let generation = 0;
  let liveNode = null;
  let localMeta = null;          // {heroes, lanes} —— meta 接口的兜底名录
  let localDefaults = [];        // 内置标签种子（meta 接口），「恢复内置标签」用
  let competitions = [];         // 赛事下拉的数据（[{id, name, date}]）

  const state = { ready: false, loading: false, revision: 0, updatedAt: '', tags: [], savedTags: [] };
  const ui = { notice: '', error: false, saving: false, editingId: null,
    pendingDelete: null, picked: [], query: '', lane: '' };

  /* ── 播报：优先外壳 notify，否则自建单一 polite live region ─────────── */
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

  /* ── 英雄名录与分路：外壳 metadata 优先，meta 接口兜底 ─────────────── */
  function heroNames() {
    const outer = getMetadata() || {};
    const names = new Set();
    for (const name of Object.keys(outer.heroTypes || {})) if (name) names.add(text(name));
    for (const name of Object.keys(outer.icons || {})) if (name) names.add(text(name));
    for (const name of localMeta?.heroes || []) if (name) names.add(text(name));
    return [...names].filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }
  /* 英雄的分路列表：metadata.heroTypes 是 英雄→{分路: 定位}，取键即为分路。 */
  function lanesOf(name) {
    const outer = getMetadata() || {};
    const fromOuter = outer.heroTypes?.[name];
    if (Array.isArray(fromOuter)) return fromOuter.map(text).filter(Boolean);
    if (fromOuter && typeof fromOuter === 'object') return Object.keys(fromOuter);
    return (localMeta?.lanes?.[name]) || [];
  }
  async function ensureMeta() {
    if (!root) return;
    try {
      const response = await fetch(META_URL, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal,
      });
      if (!response.ok) return;
      const doc = await response.json();
      localMeta = {
        heroes: Array.isArray(doc.heroes) ? doc.heroes.map(text).filter(Boolean) : [],
        lanes: doc.lanes && typeof doc.lanes === 'object' ? doc.lanes : {},
      };
      localDefaults = Array.isArray(doc.defaults) ? doc.defaults : [];
    } catch { /* 名录暂时拿不到时仍可用外壳 metadata 渲染 */ }
    if (!root) return;
    paintLanes();
    paintPicker();
    paintGallery();
  }
  /* 赛事下拉：失败不打扰（保留「不关联赛事」）。 */
  async function ensureCompetitions() {
    if (!root) return;
    try {
      const response = await fetch(COMP_URL, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal,
      });
      if (!response.ok) return;
      const doc = await response.json();
      competitions = (Array.isArray(doc.competitions) ? doc.competitions : [])
        .filter((row) => row && text(row.id))
        .map((row) => ({ id: text(row.id), name: text(row.name), date: text(row.date) }));
      paintCompetitionOptions();
    } catch { /* 赛事暂时拿不到时仍可保存不带赛事的标签 */ }
  }

  /* ── 数据 ───────────────────────────────────────────────────────────── */
  function applyPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    state.revision = Number(payload.revision) || 0;
    state.updatedAt = text(payload.updatedAt);
    state.tags = Array.isArray(payload.tags) ? payload.tags : [];
    state.savedTags = JSON.parse(JSON.stringify(state.tags));
  }
  async function load({ quiet = false, keepNotice = false } = {}) {
    if (!root) return;
    const gen = ++generation;
    state.loading = true;
    if (!keepNotice) setNotice('正在读取阵容标签…', { quiet: true });
    try {
      const response = await fetch(LIST_URL, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal,
      });
      if (!response.ok) throw new Error(`读取阵容标签失败（${response.status}）`);
      const payload = await response.json();
      if (gen !== generation || !root) return;
      applyPayload(payload);
      state.ready = true;
      paintGallery();
      if (!quiet) setNotice('');
      else if (!keepNotice) setNotice('', { quiet: true });
    } catch (error) {
      if (gen !== generation || !root || keepNotice || error.name === 'AbortError') return;
      setNotice(error.message || '阵容标签读取失败，请点「重新读取」重试。', { error: true });
    } finally {
      if (gen === generation) state.loading = false;
    }
  }
  async function save(next, successText) {
    if (ui.saving) return false;
    ui.saving = true;
    paintFormState();
    try {
      const response = await fetch(LIST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ revision: state.revision, tags: next }),
      });
      if (response.status === 409) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || '保存冲突：阵容标签已被别人修改，请点「重新读取」后再试。');
      }
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || `保存失败（${response.status}）`);
      }
      const payload = await response.json().catch(() => ({}));
      state.revision = Number(payload.revision) || state.revision + 1;
      state.updatedAt = text(payload.updatedAt) || new Date().toISOString();
      state.tags = next;
      state.savedTags = JSON.parse(JSON.stringify(next));
      paintGallery();
      await load({ quiet: true, keepNotice: true });
      setNotice(successText);
      document.dispatchEvent(new CustomEvent('lineup-tags:saved'));
      return true;
    } catch (error) {
      setNotice(error.message || '保存失败，请稍后重试。', { error: true });
      return false;
    } finally {
      ui.saving = false;
      paintFormState();
    }
  }
  const entryOf = (id) => state.tags.find((row) => String(row?.id) === String(id)) || null;
  const newId = () => `lt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  /* ── 交互动作 ───────────────────────────────────────────────────────── */
  function togglePick(name) {
    if (ui.picked.includes(name)) {
      ui.picked = ui.picked.filter((row) => row !== name);
      announce(`已移除 ${name}（${ui.picked.length}/${MAX_HEROES}）`);
    } else if (ui.picked.length >= MAX_HEROES) {
      setNotice(`已经有 ${MAX_HEROES} 个英雄，先移除一个再补入。`, { error: true });
      return;
    } else {
      ui.picked.push(name);
      announce(`已选 ${name}（${ui.picked.length}/${MAX_HEROES}）`);
    }
    paintSlots();
    paintPicker();
    paintFormState();
    if (ui.error) setNotice('', { quiet: true });
  }
  function setLane(lane) {
    ui.lane = LANES.includes(lane) ? lane : '';
    paintLanes();
    paintPicker();
  }
  function resetForm({ keepNotice = false } = {}) {
    ui.picked = []; ui.editingId = null;
    const name = root?.querySelector('[data-lt-name]');
    if (name) name.value = '';
    const note = root?.querySelector('[data-lt-note]');
    if (note) note.value = '';
    const comp = root?.querySelector('[data-lt-competition]');
    if (comp) comp.value = '';
    /* 搜索词一并清掉：否则保存/取消后网格还停在过滤态，教练容易愣一下。 */
    ui.query = '';
    const search = root?.querySelector('[data-lt-search]');
    if (search) search.value = '';
    paintSlots(); paintPicker(); paintFormState();
    if (!keepNotice) setNotice('已清空选择。');
  }
  /* 恢复内置标签：把当前缺的内置套数补回来（id 或名称已存在的跳过，不覆盖教练改过的）。 */
  function restoreDefaults() {
    const ids = new Set(state.tags.map((row) => String(row?.id ?? '')));
    const names = new Set(state.tags.map((row) => text(row?.name)));
    const missing = localDefaults.filter((row) => !ids.has(text(row?.id)) && !names.has(text(row?.name)));
    if (!missing.length) { setNotice('内置标签都在，不用恢复。'); return; }
    const next = state.tags.map((row) => ({ ...row })).concat(missing.map((row) => ({
      id: text(row.id) || newId(),
      name: text(row.name),
      heroes: (Array.isArray(row.heroes) ? row.heroes : []).slice(0, MAX_HEROES),
      note: text(row.note),
      competition: null,
      source: 'builtin',
      createdAt: new Date().toISOString(),
    })));
    save(next, `已恢复 ${missing.length} 套内置标签。`);
  }
  function startEdit(id) {
    const entry = entryOf(id);
    if (!entry) return;
    ui.editingId = String(entry.id);
    ui.picked = (Array.isArray(entry.heroes) ? entry.heroes : []).slice(0, MAX_HEROES);
    const name = root?.querySelector('[data-lt-name]');
    const note = root?.querySelector('[data-lt-note]');
    const comp = root?.querySelector('[data-lt-competition]');
    if (name) name.value = text(entry.name);
    if (note) note.value = text(entry.note);
    if (comp) comp.value = text(entry.competition?.id);
    paintSlots(); paintPicker(); paintFormState();
    setNotice(`已把「${text(entry.name)}」回填到下方，改完点保存。`);
    name?.focus();
    root?.querySelector('.lt-save')?.scrollIntoView?.({ block: 'start' });
  }
  function requestDelete(id) {
    const entry = entryOf(id);
    const dialog = root?.querySelector('[data-lt-dialog]');
    if (!entry || !dialog) return;
    ui.pendingDelete = String(entry.id);
    const target = root.querySelector('[data-lt-dialog-text]');
    if (target) target.textContent = `确定删除阵容标签「${text(entry.name)}」吗？删除会立即保存。`;
    dialog.showModal();
  }

  /* ── 渲染 ───────────────────────────────────────────────────────────── */
  function paintStatus() {
    const node = root?.querySelector('[data-lt-status]');
    if (!node) return;
    node.textContent = ui.notice;
    node.classList.toggle('is-error', ui.error);
    node.hidden = !ui.notice;
  }
  /* 卡片墙：标签名 + 5 个游戏头像 + 赛事记录。 */
  function paintGallery() {
    const holder = root?.querySelector('[data-lt-list]');
    if (!holder) return;
    holder.innerHTML = state.tags.length ? state.tags.map((row) => {
      const heroes = Array.isArray(row.heroes) ? row.heroes : [];
      const faces = heroes.map((name) => `<span class="lt-card-face">${portrait(name, 'lt-face')}</span>`).join('');
      const source = text(row.source) === 'builtin' ? '内置预置'
        : text(row.source) === 'speech' ? '口述导入' : '手动创建';
      const when = text(row.createdAt).slice(0, 10);
      const comp = row.competition && text(row.competition.id)
        ? `<span class="lt-comp-chip" title="赛事记录">${esc(text(row.competition.name) || '已关联赛事')}${text(row.competition.date) ? `<i>${esc(text(row.competition.date))}</i>` : ''}</span>`
        : '';
      return `<li class="lt-card">
          <div class="lt-card-top"><b class="lt-card-name">${esc(row.name)}</b>
            <span class="lt-row-actions">
              <button type="button" class="control lt-icon-btn" data-lt-edit="${esc(row.id)}"
                aria-label="编辑标签 ${esc(row.name)}" title="编辑">${icon('edit') || '编辑'}</button>
              <button type="button" class="control lt-icon-btn lt-danger" data-lt-delete="${esc(row.id)}"
                aria-label="删除标签 ${esc(row.name)}" title="删除">${icon('close') || '删除'}</button>
            </span></div>
          <div class="lt-card-faces" aria-hidden="true">${faces}</div>
          <small class="lt-card-heroes">${esc(heroes.join(' · '))}</small>
          ${row.note ? `<small class="lt-card-note">${esc(row.note)}</small>` : ''}
          <div class="lt-card-meta">${comp}<span class="lt-card-source">${esc(source)}</span>${when ? `<span class="lt-card-when">${esc(when)}</span>` : ''}</div>
        </li>`;
    }).join('') : '<li class="lt-empty">还没有阵容标签。在下方挑 5 个英雄，起个名字保存。</li>';
    const total = root.querySelector('[data-lt-total]');
    if (total) total.textContent = `（共 ${state.tags.length} 条）`;
    /* 恢复按钮：只在真的缺了内置套数时出现，按钮上带缺几套。 */
    const restore = root.querySelector('[data-lt-restore]');
    if (restore) {
      const ids = new Set(state.tags.map((row) => String(row?.id ?? '')));
      const names = new Set(state.tags.map((row) => text(row?.name)));
      const missing = localDefaults.filter((row) => !ids.has(text(row?.id)) && !names.has(text(row?.name))).length;
      restore.hidden = !missing;
      restore.textContent = missing ? `恢复内置标签（缺 ${missing} 套）` : '恢复内置标签';
    }
  }
  /* 已选槽位：5 个固定格子，选中的亮头像，空格虚线占位。 */
  function paintSlots() {
    const holder = root?.querySelector('[data-lt-slots]');
    if (!holder) return;
    const slots = [];
    for (let at = 0; at < MAX_HEROES; at += 1) {
      const name = ui.picked[at];
      if (name) {
        slots.push(`<span class="lt-slot is-filled">
            <span class="lt-slot-order" aria-hidden="true">${at + 1}</span>
            ${portrait(name, 'lt-slot-face')}
            <span class="lt-slot-name">${esc(name)}</span>
            <button type="button" class="lt-slot-x" data-lt-remove="${esc(name)}"
              aria-label="移除 ${esc(name)}">×</button>
          </span>`);
      } else {
        slots.push(`<span class="lt-slot is-empty" aria-hidden="true"><i>${at + 1}</i></span>`);
      }
    }
    holder.innerHTML = slots.join('');
    const count = root.querySelector('[data-lt-count]');
    if (count) count.textContent = `${ui.picked.length}/${MAX_HEROES}`;
    const hint = root.querySelector('[data-lt-slot-hint]');
    if (hint) hint.textContent = ui.picked.length === MAX_HEROES
      ? '已选满，填名称即可保存。'
      : `还差 ${MAX_HEROES - ui.picked.length} 个`;
  }
  /* 分路筛选条：全部 + 五条分路（KPL 分路图标）。 */
  function paintLanes() {
    const holder = root?.querySelector('[data-lt-lanes]');
    if (!holder) return;
    const chip = (lane) => {
      const active = ui.lane === lane;
      const slug = LANE_SLUG[lane];
      const label = lane ? `<img src="${KPL_SVG}modules/role-icon-${slug}.svg" alt="" aria-hidden="true" loading="lazy">${esc(lane)}` : '全部';
      return `<button type="button" class="lt-lane-chip${active ? ' is-active' : ''}"
          data-lt-lane="${esc(lane)}" aria-pressed="${active}">${label}</button>`;
    };
    holder.innerHTML = chip('') + LANES.map(chip).join('');
  }
  /* 头像网格：分路 + 关键词过滤，点选加入，选中带顺序角标。 */
  function paintPicker() {
    const holder = root?.querySelector('[data-lt-picker]');
    if (!holder) return;
    const query = bare(ui.query).toLowerCase();
    const full = ui.picked.length >= MAX_HEROES;
    const tiles = heroNames().filter((name) => {
      if (ui.lane && !lanesOf(name).includes(ui.lane)) return false;
      return !query || name.toLowerCase().includes(query) || bare(name).toLowerCase().includes(query);
    });
    holder.innerHTML = tiles.length ? tiles.map((name) => {
      const order = ui.picked.indexOf(name);
      const picked = order >= 0;
      return `<button type="button" class="lt-tile${picked ? ' is-picked' : ''}${full && !picked ? ' is-dim' : ''}"
          data-lt-hero="${esc(name)}" aria-pressed="${picked}" title="${esc(name)}">
          ${portrait(name, 'lt-tile-face')}
          <span class="lt-tile-name" title="${esc(name)}">${esc(name)}</span>
          ${picked ? `<i class="lt-tile-badge" aria-hidden="true">${order + 1}</i>` : ''}
        </button>`;
    }).join('') : '<p class="lt-picker-empty">没有匹配的英雄，换个分路或关键词试试。</p>';
  }
  function paintCompetitionOptions() {
    const select = root?.querySelector('[data-lt-competition]');
    if (!select) return;
    const current = select.value;
    const sorted = [...competitions].sort((a, b) => (b.date || '').localeCompare(a.date || '')
      || (a.name || '').localeCompare(b.name || '', 'zh-Hans-CN'));
    select.innerHTML = ['<option value="">不关联赛事</option>']
      .concat(sorted.map((row) => `<option value="${esc(row.id)}">${esc(row.name || '未命名赛事')}${row.date ? ` · ${esc(row.date)}` : ''}</option>`))
      .join('');
    if (current) select.value = current;
  }
  function paintFormState() {
    const title = root?.querySelector('[data-lt-form-title]');
    if (title) title.textContent = ui.editingId ? '编辑阵容标签' : '新建阵容标签';
    const submit = root?.querySelector('[data-lt-save]');
    if (submit) {
      /* 选择数量属于校验：按钮始终可点，点后由 submit 给出明确错误，
         不让键盘用户面对一个无法触发、也不知道原因的禁用按钮。 */
      submit.disabled = ui.saving;
      submit.textContent = ui.saving ? '保存中…' : ui.editingId ? '保存修改' : '保存为阵容标签';
    }
    const cancel = root?.querySelector('[data-lt-cancel-edit]');
    if (cancel) cancel.hidden = !ui.editingId;
  }
  function paintAll() {
    paintStatus(); paintGallery(); paintSlots(); paintLanes(); paintPicker(); paintFormState();
  }

  /* 骨架全静态；事件委托挂在 root，不用内联 onclick。所有控件都有可见 label。 */
  function html(data) {
    if (data) applyPayload(data);
    return `<div class="lt-page">
      <section class="section lt-lead">
        <div class="lt-lead-row">
          <h1>阵容标签</h1>
          <button type="button" class="control" data-lt-reload>${icon('refresh')} 重新读取</button>
        </div>
        <p class="lt-status" data-lt-status hidden></p>
      </section>

      <section class="section lt-existing">
        <div class="section-heading"><div><h2>我们的阵容标签 <span class="lt-count" data-lt-total></span></h2></div>
          <button type="button" class="control" data-lt-restore hidden>恢复内置标签</button></div>
        <ul class="lt-gallery" data-lt-list role="list"></ul>
      </section>

      <section class="section lt-save">
        <div class="section-heading"><div><h2 data-lt-form-title>新建阵容标签</h2></div></div>
        <form class="lt-editor" data-lt-save-form aria-label="新建或编辑阵容标签">
          <div class="lt-editor-side">
            <div class="lt-field">
              <span class="lt-field-label">已选英雄 <span class="lt-count" data-lt-count>0/${MAX_HEROES}</span></span>
              <div class="lt-slots" data-lt-slots></div>
              <p class="lt-form-hint" data-lt-slot-hint></p>
            </div>
            <div class="lt-field">
              <label for="${ids.name}">标签名称 <span aria-hidden="true">*</span></label>
              <input id="${ids.name}" data-lt-name type="text" maxlength="24" required autocomplete="off"
                placeholder="如：无前排">
            </div>
            <div class="lt-field">
              <label for="${ids.competition}">赛事记录（可选）</label>
              <select id="${ids.competition}" data-lt-competition>
                <option value="">不关联赛事</option>
              </select>
            </div>
            <div class="lt-field">
              <label for="${ids.note}">备注（可选）</label>
              <input id="${ids.note}" data-lt-note type="text" maxlength="80" autocomplete="off"
                placeholder="记录赛训口径 / 使用场景">
            </div>
            <p class="lt-save-actions">
              <button type="button" class="control" data-lt-cancel-edit hidden>取消编辑</button>
              <button type="submit" class="primary" data-lt-save>保存为阵容标签</button>
            </p>
          </div>
          <div class="lt-picker-side">
            <div class="lt-picker-bar">
              <div class="lt-lane-row" data-lt-lanes role="group" aria-label="按分路筛选"></div>
              <div class="lt-search-row">
                <label class="visually-hidden" for="${ids.search}">搜索英雄</label>
                <input id="${ids.search}" data-lt-search type="text" autocomplete="off" spellcheck="false"
                  placeholder="搜索英雄名，如：盾山">
              </div>
            </div>
            <div class="lt-picker" data-lt-picker role="group" aria-label="英雄头像，点选加入阵容"></div>
          </div>
        </form>
      </section>

      <dialog class="lt-dialog" data-lt-dialog aria-labelledby="${ids.dialog}-title">
        <h2 id="${ids.dialog}-title">确认删除</h2>
        <p data-lt-dialog-text></p>
        <form method="dialog" class="lt-dialog-actions" data-lt-dialog-form aria-label="确认删除阵容标签">
          <button type="submit" value="cancel" class="control" autofocus>取消</button>
          <button type="submit" value="delete" class="lt-delete-btn">删除</button>
        </form>
      </dialog>
    </div>`;
  }

  /* ── 事件 ───────────────────────────────────────────────────────────── */
  function onClick(event) {
    if (event.target.closest('[data-lt-reload]')) { load(); return; }
    if (event.target.closest('[data-lt-restore]')) { restoreDefaults(); return; }
    const laneChip = event.target.closest('[data-lt-lane]');
    if (laneChip) { setLane(text(laneChip.dataset.ltLane)); return; }
    const tile = event.target.closest('[data-lt-hero]');
    if (tile) { togglePick(text(tile.dataset.ltHero)); return; }
    const remove = event.target.closest('[data-lt-remove]');
    if (remove) { togglePick(text(remove.dataset.ltRemove)); return; }
    if (event.target.closest('[data-lt-cancel-edit]')) { resetForm(); return; }
    const edit = event.target.closest('[data-lt-edit]');
    if (edit) { startEdit(text(edit.dataset.ltEdit)); return; }
    const del = event.target.closest('[data-lt-delete]');
    if (del) requestDelete(text(del.dataset.ltDelete));
  }
  function onInput(event) {
    if (!event.target.matches?.('[data-lt-search]')) return;
    ui.query = event.target.value;
    paintPicker();
  }
  function onSubmit(event) {
    const form = event.target;
    /* 删除确认：用弹窗表单的 submit（submitter 区分取消/删除）做决策。
       实测部分环境下 <dialog> 关闭后的 close 事件会丢（ returnValue 已置、
       close 监听不触发），挂在 close 上删除会静默丢失，所以不依赖它；
       不 preventDefault，让弹窗照常关闭。 */
    if (form.matches?.('[data-lt-dialog-form]')) {
      if (event.submitter?.value !== 'delete') { ui.pendingDelete = null; return; }
      const pending = ui.pendingDelete;
      ui.pendingDelete = null;
      if (!pending) return;
      const next = state.tags.filter((row) => String(row.id) !== String(pending));
      save(next, '已删除，阵容标签已更新。');
      return;
    }
    if (!form.matches?.('[data-lt-save-form]')) return;
    event.preventDefault();
    if (ui.picked.length !== MAX_HEROES) {
      setNotice(`需要恰好 ${MAX_HEROES} 个英雄才能保存，当前 ${ui.picked.length} 个。`, { error: true });
      return;
    }
    const nameField = form.querySelector('[data-lt-name]');
    const name = text(nameField?.value);
    if (!name) {
      setNotice('请填写标签名称。', { error: true });
      nameField?.focus();
      return;
    }
    /* 同名检查：编辑时放过自己；撞名不覆盖，让教练改个名或直接编辑原卡。 */
    const editingId = ui.editingId;
    const dupe = state.tags.find((row) => String(row.id) !== String(editingId) && text(row.name) === name);
    if (dupe) {
      setNotice(`已有同名标签「${name}」，换个名字，或直接编辑那张卡。`, { error: true });
      nameField?.focus();
      return;
    }
    const compId = text(form.querySelector('[data-lt-competition]')?.value);
    const comp = competitions.find((row) => row.id === compId) || null;
    const entry = {
      id: ui.editingId || newId(),
      name,
      heroes: ui.picked.slice(),
      note: text(form.querySelector('[data-lt-note]')?.value),
      competition: comp ? { id: comp.id, name: comp.name, date: comp.date } : null,
      source: 'manual',
      createdAt: new Date().toISOString(),
    };
    const next = state.tags.map((row) => ({ ...row }));
    const at = next.findIndex((row) => String(row.id) === String(entry.id));
    if (at >= 0) next[at] = entry; else next.push(entry);
    const editing = Boolean(ui.editingId);
    save(next, editing ? `已保存标签「${name}」的修改。` : `已保存阵容标签「${name}」。`)
      .then((ok) => { if (ok) resetForm({ keepNotice: true }); });
  }
  /* close 只做清理（Esc / 取消路径），删除决策在 submit，避免重复保存。 */
  function onDialogClose(event) {
    event.target.returnValue = '';
    ui.pendingDelete = null;
  }

  function ensureCss() {
    if (document.querySelector('link[data-lt-css]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = new URL('./lineup-tags.css?v=20261122c', import.meta.url).href;
    link.dataset.ltCss = '1';
    document.head.append(link);
  }
  function bind(node) {
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('input', onInput);
    node.addEventListener('submit', onSubmit);
    node.querySelector('[data-lt-dialog]')?.addEventListener('close', onDialogClose);
  }
  function dispose() {
    generation += 1;
    controller?.abort();
    controller = null;
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('input', onInput);
      bound.removeEventListener('submit', onSubmit);
      bound.querySelector('[data-lt-dialog]')?.removeEventListener('close', onDialogClose);
      bound = null;
    }
    root = null;
    ui.pendingDelete = null;
  }
  function mount(node, data) {
    if (!node) return;
    if (root && root !== node) dispose();
    ensureCss();
    root = node;
    if (data) applyPayload(data);
    root.innerHTML = html();
    bind(root);
    controller = new AbortController();
    paintAll();
    ensureMeta();
    ensureCompetitions();
    load();
  }
  /* 外壳 metadata 后到时调用：只补名录/分路/头像，不动用户已经选中的英雄。 */
  function rerender() {
    if (!root) return;
    paintPicker(); paintGallery(); paintSlots();
  }

  return { html, render: html, mount, bind, dispose, rerender, state, announce };
}

export default createLineupTagsPage;
