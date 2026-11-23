/* 赛训规则中心（2026-11-22，蓝图 3.5.6；2026-11-23 去重瘦身）
 *
 * 三个 tab：英雄标签 / 克制关系 / 其他规则。共用一套「导入 JSON / 导出 JSON /
 * 变更历史 / 回滚」组件（config-tools.js），共用一套后端持久化骨架
 * （/api/v3/rules-center/{kind}，revision 乐观锁 + config_history 保存前快照）。
 * 原「英雄组合体系 / 阵容标签 / 字段好坏判定」三个 tab 与 组合池设置 / 阵容标签 /
 * 规则设置 页签重复（rules_* 副本也没有分析消费方），整块下线；组合克制
 * 子表的组合候选改读组合池设置的同一份数据（/api/v3/custom-combos）。
 *
 * 统一条目契约：
 *   - effective: {eventId, eventName, from, to} —— 按赛事「正式比赛时间」取规则版本；
 *     四项全留空 = 始终生效。赛事用 ID 或名称关联（两者都可填）。
 *   - revision / history —— 条目级修订与旧快照；文档级 revision 由后端乐观锁维护，
 *     文档级变更历史由 config-tools 的历史面板展示、可回滚。
 *
 * 与既有模块的关系（核心逻辑一律不碰）：
 *   - combo-pool.js（2/3 人池）是组合的唯一编辑入口，本页只读它的数据做克制候选。
 *   - grade-rules.js（分路×字段四档阈值）与 lineup-tags.js 各自独立维护。
 *   - counter_library.py / data/facts/counter_library.json 的算法与数据不动；
 *     本页克制表是独立规则表（按赛事维度、英雄↔英雄与组合↔组合分表），
 *     不参与现有命中判定；接入需另写适配（见文末 TODO）。
 *
 * 外壳（app.js）只给挂载点 <div data-rc-root></div>：
 *     const { createRulesCenter } = await import('./rules-center.js?v=20261122a');
 *     mods.rulesCenter = createRulesCenter({ esc, API_BASE, icon, notify, portrait, getMetadata });
 *     mods.rulesCenter.mount(document.querySelector('[data-rc-root]'));  // 离开路由时 dispose()
 */
import { createConfigTools } from './config-tools.js?v=20261122b';
import { glyph, deco, plus } from './ui-icons.js';

export const RULES_CENTER_ROUTE = 'rules';   // hash 路由：#rules

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const CENTER_LABEL = '赛训规则中心';
const MISC_GROUPS = ['异常判定规则', '指标口径', '风格标签体系', '自定义'];
const STRENGTHS = ['强', '中', '弱'];
const COUNTER_SUBS = [
  { key: 'hero', label: '英雄克制英雄', list: 'heroPairs' },
  { key: 'combo', label: '组合克制组合', list: 'comboPairs' },
];

const TABS = [
  { key: 'hero-tags', label: '英雄标签', kind: 'hero_tags' },
  { key: 'counters', label: '克制关系', kind: 'counters' },
  { key: 'misc', label: '其他规则', kind: 'misc' },
];
/** tab 语义图标（白名单内的 glyph 名），仅用于渲染，不参与 tab 逻辑。 */
const TAB_ICON = {
  'hero-tags': 'heroes', counters: 'compare', misc: 'sources',
};
const KIND_META = {
  hero_tags: { label: '英雄标签', list: 'heroes', expect: 'heroes' },
  counters: { label: '克制关系', list: null, expect: ['heroPairs', 'comboPairs'] },
  misc: { label: '其他规则', list: 'entries', expect: 'entries' },
};

const text = (v) => String(v ?? '').trim();
const splitNames = (raw) => String(raw || '').split(/[\s,，、;；/|]+/).map(text).filter(Boolean);
const defaultEsc = (v) => text(v).replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));
const blankEffective = () => ({ eventId: '', eventName: '', from: '', to: '' });
const newId = (kind) => `rc-${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

/** 条目级修订 + 旧快照：内容变化才 +revision 并压入一条 history（上限 20）。 */
function stampEntries(next, prev, keyOf) {
  const before = new Map((prev || []).map((row) => [keyOf(row), row]));
  const at = new Date().toISOString();
  const content = (row) => {
    if (!row) return '';
    const { revision, history, ...rest } = row;   // eslint-disable-line no-unused-vars
    return JSON.stringify(rest);
  };
  return next.map((row) => {
    const old = before.get(keyOf(row));
    if (!old) return { ...row, revision: 1, history: [] };
    const rev = Number(old.revision) || 0;
    if (content(old) === content(row)) {
      return { ...row, revision: rev, history: Array.isArray(row.history) ? row.history : [] };
    }
    const snapshot = { ...old };
    delete snapshot.history;
    const history = [...(Array.isArray(row.history) ? row.history : []).slice(-19),
      { at, revision: rev, snapshot }];
    return { ...row, revision: rev + 1, history };
  });
}

export function createRulesCenter(h = {}) {
  const esc = h.esc || defaultEsc;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const getMetadata = typeof h.getMetadata === 'function' ? h.getMetadata : () => ({});
  const portrait = typeof h.portrait === 'function' ? h.portrait : (name, cls = '') => {
    const url = getMetadata().icons?.[name];
    if (/^\/catalog\/icons\/hero-\d+\.png$/.test(url || '')) {
      return `<img class="portrait ${cls}" src="${esc(url)}" alt="${esc(name)}" loading="lazy">`;
    }
    return `<span class="portrait portrait-placeholder ${cls}" aria-label="${esc(name || '未知英雄')}">${esc((name || '?')[0])}</span>`;
  };
  const uid = 'rc-' + Math.random().toString(36).slice(2, 9);

  let root = null;
  let bound = null;
  let controller = null;
  let tools = null;             // 当前 tab 的 config-tools 实例（同一时刻只挂一个）
  let liveNode = null;
  let picker = null;            // 克制弹窗的头像选择状态 {a:[], b:[], q:{a:'',b:''}}
  const generation = {};

  const state = {
    active: 'hero-tags',
    docs: {}, baseline: {}, saving: false,
    query: { 'hero-tags': '', misc: '' },
    comboPool: null,               // 组合池设置页的同一份数据（/api/v3/custom-combos）
    heroLane: '全部', counterSub: 'hero',
    counterFilter: { hero: [], combo: [] },      // 克制表英雄头像筛选（各子表独立）
    counterFilterQ: { hero: '', combo: '' },     // 头像筛选器内的搜索词
    counterFilterLane: { hero: '全部', combo: '全部' },   // 头像筛选器先选分路再选英雄
    notice: '', error: false,
    editing: null,
  };
  const activeKind = () => TABS.find((tab) => tab.key === state.active)?.kind || null;
  const docOf = (kind) => state.docs[kind] || {};
  const dirty = (kind) => Boolean(state.docs[kind])
    && JSON.stringify(state.docs[kind]) !== state.baseline[kind];

  /* ── 播报 ─────────────────────────────────────────────────────────── */
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
    state.notice = text(message);
    state.error = Boolean(error);
    paintStatus();
    if (!quiet && state.notice) announce(state.notice);
  }

  /* ── 即时反馈：弹窗内字段错误 / 成功 toast / 新行高亮 ─────────────── */
  let fieldSeq = 0;
  let toastTimer = 0;
  function clearFieldError(form) {
    if (!form) return;
    const box = form.querySelector('[data-rc-field-error]');
    if (box) { box.hidden = true; box.textContent = ''; }
    form.querySelectorAll('[data-rc-invalid]').forEach((field) => {
      field.removeAttribute('aria-invalid');
      field.removeAttribute('data-rc-invalid');
      const ids = (field.getAttribute('aria-describedby') || '').split(/\s+/)
        .filter((id) => id && id !== `${uid}-field-error`);
      if (ids.length) field.setAttribute('aria-describedby', ids.join(' '));
      else field.removeAttribute('aria-describedby');
    });
  }
  /** 校验错误写进 dialog 内的 role=alert（页头 notice 会被 dialog 遮住）。 */
  function fieldError(form, message, selector) {
    clearFieldError(form);
    const box = form?.querySelector('[data-rc-field-error]');
    if (!box) { setNotice(message, { error: true, quiet: true }); return; }
    box.innerHTML = `${glyph('warning', { size: 14 })} <span>${esc(message)}</span>`;
    box.hidden = false;
    const field = selector ? form.querySelector(selector) : null;
    if (field) {
      if (!field.id) field.id = `${uid}-field-${++fieldSeq}`;
      field.setAttribute('aria-invalid', 'true');
      field.setAttribute('data-rc-invalid', '');
      const ids = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      if (!ids.includes(box.id)) ids.push(box.id);
      field.setAttribute('aria-describedby', ids.join(' '));
      field.focus();
    }
    // 弹窗内容可滚动 + foot 吸底：用 center 才能把错误条滚到可见区，不被吸底按钮盖住。
    box.scrollIntoView?.({ block: 'center' });
  }
  function toast(message) {
    if (!notify) return;   // 外壳没注入 notify 时静默跳过
    try { notify(`✓ ${message}`); } catch { /* 外部播报异常不影响主流程 */ }
    const host = root?.querySelector('.rc-page') || root;
    if (!host) return;
    let el = host.querySelector('[data-rc-toast]');
    if (!el) {
      el = document.createElement('div');
      el.className = 'rc-toast';
      el.dataset.rcToast = '';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      host.append(el);
    }
    el.innerHTML = `<span aria-hidden="true">✓</span> <span>${esc(message)}</span>`;
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => el.remove(), 2400);
  }
  function markFresh(entries) {
    const ids = new Set((entries || []).map((row) => String(row.key ?? row.id ?? '')));
    if (!ids.size) return;
    window.setTimeout(() => {
      root?.querySelectorAll('[data-rc-row-id]').forEach((row) => {
        if (!ids.has(row.dataset.rcRowId)) return;
        row.classList.add('is-fresh');
        window.setTimeout(() => row.classList.remove('is-fresh'), 1900);
      });
    }, 0);
  }
  function reportSuccess(message, entries) {
    setNotice(message, { quiet: Boolean(notify) });   // notify 已承担播报，避免重复
    toast(message);
    markFresh(entries);
  }

  /* ── 数据 ─────────────────────────────────────────────────────────── */
  function applyDoc(kind, payload) {
    const { saved, historyName, ...doc } = payload || {};   // eslint-disable-line no-unused-vars
    if (!doc || typeof doc !== 'object') return;
    state.docs[kind] = doc;
    state.baseline[kind] = JSON.stringify(doc);
  }
  async function load(kind, { quiet = false } = {}) {
    if (!root) return;
    const gen = (generation[kind] = (generation[kind] || 0) + 1);
    try {
      const response = await fetch(`${API_BASE}/api/v3/rules-center/${encodeURIComponent(kind)}`, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal,
      });
      if (!response.ok) throw new Error(`读取${KIND_META[kind].label}失败（${response.status}）`);
      applyDoc(kind, await response.json());
      if (gen !== generation[kind] || !root) return;
      if (activeKind() === kind) paint();
      if (!quiet) setNotice(`${KIND_META[kind].label}已读取。`);
    } catch (error) {
      if (gen !== generation[kind] || !root || error.name === 'AbortError') return;
      setNotice(error.message || '规则读取失败，请点「重新读取」重试。', { error: true });
    }
  }
  async function save(kind, summary = '') {
    if (state.saving || !state.docs[kind]) return false;
    state.saving = true;
    paintSaveState();
    try {
      const doc = state.docs[kind];
      const response = await fetch(`${API_BASE}/api/v3/rules-center/${encodeURIComponent(kind)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ revision: Number(doc.revision) || 0, doc, summary: summary || `${KIND_META[kind].label}已更新` }),
      });
      if (response.status === 409) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || '规则已被其他人更新，请点「重新读取」后再保存。');
      }
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `保存失败（${response.status}）`);
      }
      const payload = await response.json();
      doc.revision = Number(payload.revision) || (Number(doc.revision) || 0) + 1;
      doc.updatedAt = payload.updatedAt || new Date().toISOString();
      state.baseline[kind] = JSON.stringify(doc);
      paint();
      tools?.refresh();
      setNotice(`${KIND_META[kind].label}已保存：修订 ${doc.revision}。`);
      document.dispatchEvent(new CustomEvent('rules-center:saved', { detail: { kind } }));
      return true;
    } catch (error) {
      setNotice(error.message || '保存失败，请稍后重试。', { error: true });
      return false;
    } finally {
      state.saving = false;
      paintSaveState();
    }
  }

  /* ── 英雄资料 / 标签候选 ─────────────────────────────────────────── */
  function heroNames() {
    const outer = getMetadata() || {};
    const names = Object.keys(outer.heroTypes || {}).length
      ? Object.keys(outer.heroTypes) : Object.keys(outer.icons || {});
    const tagged = Object.keys(docOf('hero_tags').heroes || {});
    return [...new Set([...names, ...tagged])].filter(Boolean)
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }
  function heroTypes() {
    const fromDoc = docOf('hero_tags').heroes || {};
    const values = new Set();
    for (const hero of Object.values(fromDoc)) {
      if (text(hero.defaultType)) values.add(text(hero.defaultType));
      for (const value of Object.values(hero.lanes || {})) if (text(value)) values.add(text(value));
    }
    return [...values].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }
  function poolRows() { return [...(state.comboPool?.pairs || []), ...(state.comboPool?.trios || [])]; }
  function comboNames() {
    return poolRows().map((row) => text(row.name) || (row.heroes || []).join('+')).filter(Boolean);
  }
  /** 拉组合池设置的同一份数据（克制表组合候选 / 成员映射用），失败给空池不阻塞。 */
  async function loadComboPool() {
    try {
      const response = await fetch(`${API_BASE}/api/v3/custom-combos`,
        { headers: { Accept: 'application/json' }, signal: controller?.signal, cache: 'no-store' });
      if (!response.ok) throw new Error(String(response.status));
      state.comboPool = await response.json();
    } catch { state.comboPool = state.comboPool || { pairs: [], trios: [] }; }
    paintCounters();
  }
  /** 英雄 → 可打分路（metadata.heroTypes，键缺失视为未标注）。 */
  function lanesOf(name) {
    const row = (getMetadata() || {}).heroTypes?.[name] || {};
    return LANES.filter((lane) => row[lane] !== undefined && row[lane] !== null && row[lane] !== '');
  }
  /** 分路筛选按钮行：全部 + 五路。group 用于事件分发（弹窗两侧 / 列表两张子表）。 */
  const laneBtns = (group, current) => `<div class="rc-lane-row" role="group" aria-label="按分路筛选英雄">
      ${['全部', ...LANES].map((lane) => `<button type="button" class="rc-lane${current === lane ? ' is-on' : ''}"
          data-rc-lane="${group}" data-rc-lane-name="${esc(lane)}" aria-pressed="${current === lane}">${esc(lane)}</button>`).join('')}
    </div>`;
  /** 组合名 → 成员英雄列表（克制表按英雄头像筛组合时用）。 */
  function comboHeroesMap() {
    const map = new Map();
    for (const row of poolRows()) {
      const name = text(row.name) || (row.heroes || []).join('+');
      if (name) map.set(name, (row.heroes || []).map(text).filter(Boolean));
    }
    return map;
  }
  /** 头像按钮（弹窗选择器与列表筛选共用）：点一下切换选中。 */
  const heroPickBtn = (name, on, attrs) => `<button type="button" class="rc-pick-hero${on ? ' is-on' : ''}"
      aria-pressed="${on}" ${attrs}><span class="rc-pick-face" aria-hidden="true">${portrait(name)}</span>
      <span class="rc-pick-name">${esc(name)}</span></button>`;
  /** 弹窗内一侧（攻方 / 受方）的头像网格：先分路、再搜索词，双条件过滤。 */
  function pickGridHtml(side) {
    const q = text(picker?.q?.[side]).toLowerCase();
    const lane = picker?.lane?.[side] || '全部';
    const sel = picker?.[side] || [];
    const list = heroNames().filter((name) =>
      (lane === '全部' || lanesOf(name).includes(lane))
      && (!q || name.toLowerCase().includes(q)));
    return list.length ? list.map((name) => heroPickBtn(name, sel.includes(name),
      `data-rc-pick="${side}" data-rc-pick-name="${esc(name)}"`)).join('')
      : '<p class="rc-muted">这个分路没有匹配的英雄。</p>';
  }
  /** 已选 chips（含 × 移除），初次打开弹窗也要渲染，编辑回填才看得见。 */
  function pickChipsHtml(side) {
    const sel = picker?.[side] || [];
    return sel.map((name) => `<span class="rc-chip">
        <span class="rc-chip-face" aria-hidden="true">${portrait(name)}</span><span>${esc(name)}</span>
        <button type="button" class="rc-chip-x" data-rc-pick-remove="${side}" data-rc-pick-remove-name="${esc(name)}"
          aria-label="移除 ${esc(name)}">×</button></span>`).join('');
  }
  function paintPickChips(side) {
    const holder = root?.querySelector(`[data-rc-pick-chips="${side}"]`);
    if (holder) holder.innerHTML = pickChipsHtml(side);
  }
  function paintPickGrid(side) {
    const grid = root?.querySelector(`[data-rc-pick-grid="${side}"]`);
    if (grid) grid.innerHTML = pickGridHtml(side);
  }
  /** 点头像切换选择：编辑=单选替换，新增=多选（1 对多 / 多对多）。 */
  function togglePick(side, name) {
    if (!picker) return;
    const list = picker[side];
    const at = list.indexOf(name);
    if (at >= 0) list.splice(at, 1);
    else if (state.editing?.mode === 'edit') list.splice(0, list.length, name);
    else list.push(name);
    paintPickChips(side);
    paintPickGrid(side);
  }
  const datalistHtml = (id, values) => `<datalist id="${esc(id)}">${values
    .map((v) => `<option value="${esc(v)}"></option>`).join('')}</datalist>`;

  /* ── 生效时间字段 ─────────────────────────────────────────────────── */
  function effectiveFields(eff = {}) {
    return `<fieldset class="rc-eff">
      <legend>生效时间（按赛事正式比赛时间）</legend>
      <div class="rc-grid2">
        <label>赛事 ID <input type="text" data-f-eff="eventId" value="${esc(eff.eventId)}" placeholder="如 2026QS"></label>
        <label>赛事名 <input type="text" data-f-eff="eventName" value="${esc(eff.eventName)}" placeholder="如 2026 秋季赛"></label>
        <label>起（正式比赛日） <input type="date" data-f-eff="from" value="${esc(eff.from)}" placeholder="留空 = 始终生效"></label>
        <label>止（正式比赛日） <input type="date" data-f-eff="to" value="${esc(eff.to)}" placeholder="留空 = 始终生效"></label>
      </div>
    </fieldset>`;
  }
  function readEffective(form) {
    const out = blankEffective();
    form.querySelectorAll('[data-f-eff]').forEach((input) => {
      out[input.dataset.fEff] = text(input.value);
    });
    return out;
  }
  function effectiveText(eff = {}) {
    const event = [eff.eventId, eff.eventName].filter(Boolean).join(' · ');
    const win = [eff.from, eff.to].filter(Boolean).join(' ~ ');
    if (!event && !win) return '<span class="rc-always">始终生效</span>';
    return `<span class="rc-effective">${esc(event || '不限赛事')}<br><small>${esc(win || '不限正式比赛日')}</small></span>`;
  }

  /* ── config-tools 复用 ────────────────────────────────────────────── */
  function mountTools(kind) {
    const slot = root?.querySelector('[data-rc-tools-slot]');
    if (!slot) return;
    tools?.dispose();
    tools = null;
    slot.innerHTML = '';
    if (!kind) {
      slot.innerHTML = '';
      return;
    }
    const meta = KIND_META[kind];
    tools = createConfigTools({
      configName: `rules_${kind}`, API_BASE, esc, icon, notify,
      exportName: `rules_${kind}`, label: meta.label,
      expect: meta.expect,
      historyUrl: `${API_BASE}/api/v3/rules-center/${kind}/history`,
      rollbackUrl: `${API_BASE}/api/v3/rules-center/${kind}/rollback`,
      getDoc: () => docOf(kind),
      onImport: (doc) => {
        state.docs[kind] = doc;
        paint();
        setNotice(`已读取导入文件，${meta.label}的改动尚未保存，请检查后点「保存更改」。`);
      },
      onRollback: () => load(kind, { quiet: true }),
      isDirty: () => dirty(kind),
    });
    slot.innerHTML = tools.html();
    tools.mount(slot);
  }

  /* ── 表格渲染 ─────────────────────────────────────────────────────── */
  const td = (label, content, cls = '') => `<td data-label="${esc(label)}"${cls ? ` class="${cls}"` : ''}>${content}</td>`;
  const actionBtns = (kind, entry, sub) => `<span class="rc-actions">
      <button type="button" class="control rc-icon" data-rc-edit="${esc(entry.id)}" data-rc-kind="${kind}" data-rc-sub="${esc(sub || '')}"
        aria-label="编辑 ${esc(entry.name || entry.key || entry.id || '条目')}" title="编辑">${glyph('edit', { size: 14 })}</button>
      <button type="button" class="control rc-icon is-danger" data-rc-del="${esc(entry.id)}" data-rc-kind="${kind}" data-rc-sub="${esc(sub || '')}"
        aria-label="删除 ${esc(entry.name || entry.key || entry.id || '条目')}" title="删除">${glyph('trash', { size: 14 })}</button>
    </span>`;
  const historyBtn = (kind, entry, sub, name = '') => `<button type="button" class="control rc-history-btn"
      data-rc-history="${esc(entry.id)}" data-rc-kind="${kind}" data-rc-sub="${esc(sub || '')}" data-rc-name="${esc(name)}"
      aria-label="查看 ${esc(name || entry.id || '条目')} 的条目级历史">历史 <span class="rc-rev">r${esc(Number(entry.revision) || 0)}</span></button>`;
  const tokens = (list) => (list || []).map((v) => `<span class="rc-token">${esc(v)}</span>`).join('') || '<span class="rc-muted">—</span>';
  /** 空状态：对应 tab 的语义图标 + 内联「＋新增」，点一下直接开表单。 */
  const emptyWithAdd = (cols, message, iconName, kind, sub = '') => `<tr><td class="rc-empty" colspan="${cols}">
      <span class="rc-empty-inner">${glyph(iconName, { size: 18 })}<span>${esc(message)}</span>
        <button type="button" class="control rc-empty-add" data-rc-add="${esc(kind)}" data-rc-sub="${esc(sub)}"
          aria-label="新增${esc(KIND_META[kind]?.label || '条目')}">${plus({ size: 14 })} 新增</button>
      </span></td></tr>`;

  function paintHeroTags() {
    const body = root?.querySelector('[data-rc-body="hero-tags"]');
    if (!body) return;
    const heroes = docOf('hero_tags').heroes || {};
    const meta = docOf('hero_tags')._rulesMeta || {};
    const q = state.query['hero-tags'].toLowerCase();
    const rows = Object.entries(heroes).filter(([name, hero]) => {
      const laneOk = state.heroLane === '全部' || text(hero.defaultLane) === state.heroLane
        || Object.keys(hero.lanes || {}).includes(state.heroLane);
      return laneOk && (!q || name.toLowerCase().includes(q) || text(hero.defaultType).toLowerCase().includes(q));
    });
    body.innerHTML = rows.length ? rows.map(([name, hero]) => {
      const dims = Object.values(hero.matrix || {}).filter((v) => Number(v) === 1).length;
      const view = { id: name, name, revision: meta[name]?.revision || 0 };
      return `<tr data-rc-row-id="${esc(name)}">
        ${td('英雄', `<span class="rc-hero-cell">${portrait(name, 'portrait-sm')}<b>${esc(name)}</b><small>#${esc(hero.id)}</small></span>`)}
        ${td('默认分路', esc(hero.defaultLane) || '<span class="rc-muted">—</span>')}
        ${td('默认类型', `<span class="rc-token">${esc(hero.defaultType) || '—'}</span>`)}
        ${td('兼容定位', esc(hero.compat) || '<span class="rc-muted">—</span>')}
        ${td('分路 → 类型', tokens(Object.entries(hero.lanes || {}).map(([lane, type]) => `${lane}:${type}`)))}
        ${td('能力矩阵', `${dims} 项启用`)}
        ${td('修订 / 历史', historyBtn('hero_tags', view, '', name))}
        ${td('操作', `<span class="rc-actions">
          <button type="button" class="control rc-icon" data-rc-edit-hero="${esc(name)}" aria-label="编辑 ${esc(name)} 标签" title="编辑 ${esc(name)} 标签">${glyph('edit', { size: 14 })}</button>
          <button type="button" class="control rc-icon is-danger" data-rc-del-hero="${esc(name)}" aria-label="删除 ${esc(name)} 标签" title="删除 ${esc(name)} 标签">${glyph('trash', { size: 14 })}</button>
        </span>`)}
      </tr>`;
    }).join('') : emptyWithAdd(8, '没有匹配的英雄标签，可搜索 / 切分路后再试。', 'heroes', 'hero_tags');
    const count = root.querySelector('[data-rc-hero-count]');
    if (count) count.textContent = `共 ${Object.keys(heroes).length} 个英雄`;
  }

  function paintCounters() {
    const sub = COUNTER_SUBS.find((s) => s.key === state.counterSub) || COUNTER_SUBS[0];
    root?.querySelectorAll('[data-rc-counter-sub]').forEach((btn) => {
      const on = btn.dataset.rcCounterSub === sub.key;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', String(on));
    });
    root?.querySelectorAll('[data-rc-counter-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.rcCounterPanel !== sub.key;
    });
    const body = root?.querySelector(`[data-rc-body="counters-${sub.key}"]`);
    if (!body) return;
    // 英雄头像筛选：英雄表看攻方 / 受方是否命中；组合表看两张子表的组合成员是否覆盖所选英雄。
    const sel = state.counterFilter[sub.key] || [];
    const comboHeroes = sub.key === 'combo' ? comboHeroesMap() : null;
    const hitCombo = (name) => {
      const heroes = comboHeroes?.get(text(name)) || [];
      return heroes.length > 0 && sel.every((hero) => heroes.includes(hero));
    };
    const rows = (docOf('counters')[sub.list] || []).filter((row) => {
      if (!sel.length) return true;
      return sub.key === 'hero' ? (sel.includes(row.a) || sel.includes(row.b))
        : (hitCombo(row.a) || hitCombo(row.b));
    });
    const heroCell = (name) => `<span class="rc-hero-cell">${portrait(name)}<b>${esc(name)}</b></span>`;
    body.innerHTML = rows.length ? rows.map((row) => `<tr data-rc-row-id="${esc(row.id)}">
        ${td('攻方', sub.key === 'hero' ? heroCell(row.a) : `<b>${esc(row.a)}</b>`)}
        ${td('受方', sub.key === 'hero' ? heroCell(row.b) : `<b>${esc(row.b)}</b>`)}
        ${td('方向', '<span class="rc-arrow">→</span>')}
        ${td('强度', `<span class="rc-strength s-${esc(row.strength)}">${esc(row.strength || '中')}</span>`)}
        ${td('分路', esc(row.lane) || '<span class="rc-muted">不限</span>')}
        ${td('生效赛事 / 时间', effectiveText(row.effective))}
        ${td('备注', esc(row.note) || '<span class="rc-muted">—</span>')}
        ${td('修订 / 历史', historyBtn('counters', row, sub.key))}
        ${td('操作', actionBtns('counters', row, sub.key))}
      </tr>`).join('')
      : sel.length
        ? `<tr><td class="rc-empty" colspan="9">没有符合「英雄筛选」的${esc(sub.label)}记录，可在上方清空筛选。</td></tr>`
        : emptyWithAdd(9, `还没有${sub.label}记录，可一次填多个攻方 / 受方。`, 'compare', 'counters', sub.key);
    paintCounterFilter(sub.key);
  }

  /** 克制表筛选器：已选头像 chips（吸在 summary 上，收起也能看到）+ 搜索 + 头像网格。 */
  function paintCounterFilter(sub) {
    const wrap = root?.querySelector(`[data-rc-cfilter-wrap="${sub}"]`);
    if (!wrap) return;
    const sel = state.counterFilter[sub] || [];
    const chips = wrap.querySelector(`[data-rc-cfilter-chips="${sub}"]`);
    if (chips) {
      chips.innerHTML = sel.map((name) => `<span class="rc-chip">
          <span class="rc-chip-face" aria-hidden="true">${portrait(name)}</span><span>${esc(name)}</span>
          <button type="button" class="rc-chip-x" data-rc-cfilter-remove="${sub}" data-rc-cfilter-remove-name="${esc(name)}"
            aria-label="取消筛选 ${esc(name)}">×</button></span>`).join('');
    }
    const count = wrap.querySelector(`[data-rc-cfilter-count="${sub}"]`);
    if (count) count.textContent = sel.length ? `已选 ${sel.length}/4` : '';
    const grid = wrap.querySelector(`[data-rc-cfilter-grid="${sub}"]`);
    if (grid) {
      const q = state.counterFilterQ[sub].toLowerCase();
      const lane = state.counterFilterLane[sub] || '全部';
      const list = heroNames().filter((name) =>
        (lane === '全部' || lanesOf(name).includes(lane))
        && (!q || name.toLowerCase().includes(q)));
      grid.innerHTML = list.length ? list.map((name) => heroPickBtn(name, sel.includes(name),
        `data-rc-cfilter-hero="${sub}" data-rc-cfilter-name="${esc(name)}"`)).join('')
        : '<p class="rc-muted">这个分路没有匹配的英雄，换个分路或关键词试试。</p>';
    }
    const clear = wrap.querySelector(`[data-rc-cfilter-clear="${sub}"]`);
    if (clear) clear.disabled = !sel.length;
  }
  function toggleCounterFilter(sub, name) {
    const list = state.counterFilter[sub] || (state.counterFilter[sub] = []);
    const at = list.indexOf(name);
    if (at >= 0) {
      list.splice(at, 1);
      announce(`已取消筛选 ${name}`);
    } else {
      if (list.length >= 4) { announce('英雄筛选最多选 4 个。'); return; }
      list.push(name);
      announce(`筛选条件：${list.join('、')}（已选 ${list.length}/4）`);
    }
    paintCounters();
  }

  function paintMisc() {
    const body = root?.querySelector('[data-rc-body="misc"]');
    if (!body) return;
    const q = state.query.misc.toLowerCase();
    const rows = (docOf('misc').entries || []).filter((row) => !q
      || [row.group, row.key, row.value, row.note].some((v) => String(v || '').toLowerCase().includes(q)));
    body.innerHTML = rows.length ? rows.map((row) => `<tr data-rc-row-id="${esc(row.id)}">
        ${td('分类', `<span class="rc-token">${esc(row.group || '自定义')}</span>`)}
        ${td('规则键', `<b>${esc(row.key)}</b>`)}
        ${td('规则值 / 口径', `<span class="rc-value">${esc(row.value)}</span>`)}
        ${td('备注', esc(row.note) || '<span class="rc-muted">—</span>')}
        ${td('生效赛事 / 时间', effectiveText(row.effective))}
        ${td('修订 / 历史', historyBtn('misc', row, '', row.key))}
        ${td('操作', actionBtns('misc', row))}
      </tr>`).join('') : emptyWithAdd(7, '还没有其他规则（异常判定 / 指标口径 / 风格标签等）。', 'sources', 'misc');
  }

  function paintStatus() {
    const node = root?.querySelector('[data-rc-notice]');
    if (!node) return;
    node.textContent = state.notice;
    node.classList.toggle('is-error', state.error);
    node.hidden = !state.notice;
  }
  function paintRev() {
    const node = root?.querySelector('[data-rc-doc-rev]');
    if (!node) return;
    const kind = activeKind();
    if (!kind) { node.textContent = '独立页维护'; return; }
    const doc = docOf(kind);
    node.textContent = `修订 ${Number(doc.revision) || 0}${doc.updatedAt ? ` · ${esc(String(doc.updatedAt).slice(0, 19).replace('T', ' '))}` : ''}`;
  }
  function paintSaveState() {
    root?.querySelectorAll('[data-rc-save]').forEach((btn) => {
      const kind = btn.dataset.rcSave;
      btn.disabled = !dirty(kind) || state.saving;
      btn.textContent = state.saving ? '保存中…' : (dirty(kind) ? '保存更改 ●' : '保存更改');
    });
  }
  function paintTabs() {
    root?.querySelectorAll('[data-rc-tab]').forEach((btn) => {
      const on = btn.dataset.rcTab === state.active;
      btn.setAttribute('aria-selected', String(on));
      btn.tabIndex = on ? 0 : -1;
      btn.classList.toggle('is-on', on);
    });
    root?.querySelectorAll('[data-rc-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.rcPanel !== state.active;
    });
  }
  function paint() {
    if (!root) return;
    paintTabs();
    paintHeroTags(); paintCounters(); paintMisc();
    paintStatus(); paintRev(); paintSaveState();
  }

  /* ── 对话框：新增 / 编辑 / 删除 / 条目历史 ─────────────────────────── */
  function openDialog({ title, body, mode = 'edit', kind = '', entry = null, key = '', sub = '', submitText = '保存', warn = false }) {
    if (!root) return;
    state.editing = { mode, kind, entry, key, sub };
    const dialog = root.querySelector('[data-rc-dialog]');
    if (!dialog) return;
    const titleNode = root.querySelector('[data-rc-dialog-title]');
    if (warn) titleNode.innerHTML = `${glyph('warning', { size: 16 })} <span>${esc(title)}</span>`;
    else titleNode.textContent = title;
    const bodyNode = root.querySelector('[data-rc-dialog-body]');
    bodyNode.innerHTML = `${body}<p class="rc-field-error" id="${uid}-field-error" role="alert" data-rc-field-error hidden></p>`;
    const submit = root.querySelector('[data-rc-dialog-submit]');
    submit.textContent = submitText;
    submit.hidden = mode === 'history';
    submit.classList.toggle('is-danger', mode === 'delete');
    const cancel = root.querySelector('[data-rc-dialog-cancel]');
    const first = root.querySelector('[data-rc-dialog-body] input, [data-rc-dialog-body] select, [data-rc-dialog-body] textarea');
    cancel.autofocus = mode === 'delete' || mode === 'history';
    if (first) first.autofocus = cancel.autofocus ? false : true;
    dialog.showModal();
  }
  function newEntry(kind, sub = '') {
    const base = { id: newId(kind), effective: blankEffective(), revision: 0, history: [] };
    if (kind === 'counters') return { ...base, a: '', b: '', strength: '强', lane: '全部', note: '', ...(sub === 'combo' ? { sub } : {}) };
    if (kind === 'misc') return { ...base, group: MISC_GROUPS[0], key: '', value: '', note: '' };
    return base;
  }

  function entryBody(kind, entry, isEdit = false) {
    const eff = effectiveFields(entry.effective);
    if (kind === 'counters') {
      const multi = !isEdit;
      if (state.counterSub === 'combo') {
        // 组合克制组合：组合名可能含分隔符，不适合按名字回传，保留文字输入 + 候选。
        const names = comboNames();
        const comboDatalist = datalistHtml(`${uid}-combo-names`, names);
        return `<div class="rc-grid2">
          <label>攻方组合（谁克制）${multi ? '，多个用逗号分隔 → 1对多 / 多对多' : ''}
            <input type="text" data-f="a" value="${esc(entry.a)}" placeholder="如 张良+虞姬" list="${uid}-combo-names" required></label>
          <label>受方组合（被谁克制）${multi ? '，多个用逗号分隔' : ''}
            <input type="text" data-f="b" value="${esc(entry.b)}" placeholder="如 太乙+鲁班" list="${uid}-combo-names" required></label>
          <label>强度 <select data-f="strength">${STRENGTHS.map((s) => `<option value="${esc(s)}"${entry.strength === s ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select></label>
          <label>分路 <select data-f="lane">
            ${['全部', ...LANES].map((l) => `<option value="${esc(l)}"${(entry.lane || '全部') === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}
          </select></label>
        </div>
        ${comboDatalist}
        <label>备注 <textarea data-f="note" rows="2">${esc(entry.note)}</textarea></label>
        ${eff}`;
      }
      // 英雄克制英雄：先选分路，再点头像选攻方 / 受方，不再手打名字。
      picker = {
        a: isEdit ? [text(entry.a)].filter(Boolean) : [],
        b: isEdit ? [text(entry.b)].filter(Boolean) : [],
        q: { a: '', b: '' },
        lane: { a: '全部', b: '全部' },
      };
      const pickField = (side, label) => `<div class="rc-picker" data-rc-picker="${side}" tabindex="-1">
          <div class="rc-picker-head"><span class="rc-picker-label">${label}</span>
            <input type="search" data-rc-pick-search="${side}" placeholder="搜英雄名" autocomplete="off"></div>
          ${laneBtns(`pick-${side}`, '全部')}
          <div class="rc-picker-chips" data-rc-pick-chips="${side}">${pickChipsHtml(side)}</div>
          <div class="rc-picker-grid" data-rc-pick-grid="${side}">${pickGridHtml(side)}</div>
        </div>`;
      return `<div class="rc-grid2">
          ${pickField('a', '攻方（谁克制）')}
          ${pickField('b', '受方（被谁克制）')}
        </div>
        <div class="rc-grid2">
          <label>强度 <select data-f="strength">${STRENGTHS.map((s) => `<option value="${esc(s)}"${entry.strength === s ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select></label>
          <label>分路 <select data-f="lane">
            ${['全部', ...LANES].map((l) => `<option value="${esc(l)}"${(entry.lane || '全部') === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}
          </select></label>
        </div>
        <label>备注 <textarea data-f="note" rows="2">${esc(entry.note)}</textarea></label>
        ${eff}`;
    }
    if (kind === 'misc') {
      return `<div class="rc-grid2">
        <label>分类 <select data-f="group">${MISC_GROUPS.map((g) => `<option value="${esc(g)}"${entry.group === g ? ' selected' : ''}>${esc(g)}</option>`).join('')}</select></label>
        <label>规则键 <input type="text" data-f="key" value="${esc(entry.key)}" placeholder="如 一血经济阈值" required></label>
      </div>
      <label>规则值 / 口径 / 公式（列表可用换行） <textarea data-f="value" rows="4">${esc(entry.value)}</textarea></label>
      <label>备注 <textarea data-f="note" rows="2">${esc(entry.note)}</textarea></label>${eff}`;
    }
    return eff;
  }

  function heroTagBody(name, hero = {}) {
    const dims = docOf('hero_tags').capabilityDims || [];
    const meta = docOf('hero_tags')._rulesMeta || {};
    const types = heroTypes();
    const eff = hero.effective || {};
    return `<div class="rc-grid2">
        <label>英雄名 <input type="text" data-f="name" value="${esc(name)}" required></label>
        <label>英雄 ID <input type="number" data-f="id" value="${esc(hero.id || '')}"></label>
        <label>默认分路 <select data-f="defaultLane">${['', ...LANES].map((l) => `<option value="${esc(l)}"${(hero.defaultLane || '') === l ? ' selected' : ''}>${esc(l || '未标注')}</option>`).join('')}</select></label>
        <label>默认类型（五路 12 类） <input type="text" data-f="defaultType" list="${uid}-types" value="${esc(hero.defaultType)}" placeholder="如 野核 / 工具人法师"></label>
        <label>兼容定位 / 通俗叫法 <input type="text" data-f="compat" value="${esc(hero.compat)}"></label>
      </div>
      <fieldset><legend>分路 → 类型（该英雄可打的分路）</legend><div class="rc-grid2">
        ${LANES.map((lane) => `<label>${esc(lane)} <input type="text" data-f-lane="${esc(lane)}" list="${uid}-types" value="${esc(hero.lanes?.[lane] || '')}" placeholder="留空=不可打"></label>`).join('')}
      </div></fieldset>
      <fieldset><legend>能力矩阵（勾选 = 1，原 schema 19 维）</legend><div class="rc-check-grid">
        ${dims.map((dim) => `<label class="rc-check"><input type="checkbox" data-f-dim="${esc(dim)}"${hero.matrix?.[dim] ? ' checked' : ''}> ${esc(dim)}</label>`).join('') || '<span class="rc-muted">该文档没有 capabilityDims</span>'}
      </div></fieldset>
      ${datalistHtml(`${uid}-types`, types)}
      ${effectiveFields(eff)}`;
  }

  function historyBody(title, entries) {
    if (!entries?.length) return `<p class="rc-muted">${esc(title)}还没有条目级历史。修改内容并保存后，旧版本会留在这里。</p>`;
    return `${entries.map((item, i) => `<details class="rc-hist-item"${i === 0 ? ' open' : ''}>
        <summary>修订 ${esc(item.revision || 0)} · ${esc(String(item.at || '').slice(0, 19).replace('T', ' '))}</summary>
        <pre>${esc(JSON.stringify(item.snapshot || {}, null, 2))}</pre>
      </details>`).join('')}`;
  }

  function addEntry(kind, sub = '') {
    if (kind === 'hero_tags') {
      openDialog({ title: '新增英雄标签', mode: 'create', kind,
        body: heroTagBody('', { id: '', lanes: {}, matrix: {} }), submitText: '新增英雄' });
      return;
    }
    openDialog({ title: `新增 · ${KIND_META[kind].label}`, mode: 'create', kind, sub,
      body: entryBody(kind, newEntry(kind, sub), false) });
  }
  function editEntry(kind, id, sub = '') {
    if (kind === 'hero_tags') {
      const hero = docOf('hero_tags').heroes?.[id];
      if (!hero) return;
      openDialog({ title: `编辑英雄标签 · ${id}`, mode: 'edit', kind, key: id,
        body: heroTagBody(id, hero) });
      return;
    }
    const listKey = kind === 'counters' ? COUNTER_SUBS.find((s) => s.key === sub)?.list : KIND_META[kind].list;
    const entry = (docOf(kind)[listKey] || []).find((row) => String(row.id) === String(id));
    if (!entry) return;
    openDialog({ title: `编辑 · ${KIND_META[kind].label}`, mode: 'edit', kind, sub, entry,
      body: entryBody(kind, entry, true) });
  }
  function deleteEntry(kind, id, sub = '') {
    if (kind === 'hero_tags') {
      if (!docOf('hero_tags').heroes?.[id]) return;
      openDialog({ title: '删除英雄标签', mode: 'delete', kind, key: id, warn: true,
        body: `<p>确定删除「${esc(id)}」的英雄标签吗？保存后生效，文档历史可回滚。</p>`,
        submitText: '确认删除' });
      return;
    }
    const listKey = kind === 'counters' ? COUNTER_SUBS.find((s) => s.key === sub)?.list : KIND_META[kind].list;
    const entry = (docOf(kind)[listKey] || []).find((row) => String(row.id) === String(id));
    if (!entry) return;
    const name = entry.name || entry.key || `${entry.a || ''} → ${entry.b || ''}` || id;
    openDialog({ title: '删除规则条目', mode: 'delete', kind, sub, entry, warn: true,
      body: `<p>确定删除「${esc(name)}」吗？保存后生效，文档历史可回滚。</p>`, submitText: '确认删除' });
  }
  function showHistory(kind, id, sub = '', name = '') {
    if (kind === 'hero_tags') {
      openDialog({ title: `条目历史 · ${name || id}`, mode: 'history',
        body: historyBody(name || id, docOf('hero_tags')._rulesMeta?.[id]?.history || []) });
      return;
    }
    const listKey = kind === 'counters' ? COUNTER_SUBS.find((s) => s.key === sub)?.list : KIND_META[kind].list;
    const entry = (docOf(kind)[listKey] || []).find((row) => String(row.id) === String(id));
    if (!entry) return;
    openDialog({ title: `条目历史 · ${name || id}`, mode: 'history',
      body: historyBody(name || id, entry.history) });
  }

  function collectEntries(ed, form) {
    const get = (sel) => text(form.querySelector(sel)?.value);
    const eff = readEffective(form);
    if (ed.kind === 'hero_tags') {
      const old = docOf('hero_tags').heroes?.[ed.key] || {};
      const name = get('[data-f="name"]').slice(0, 40);
      if (!name) { fieldError(form, '请填写英雄名。', '[data-f="name"]'); return null; }
      const lanes = {};
      form.querySelectorAll('[data-f-lane]').forEach((input) => {
        const value = text(input.value);
        if (value) lanes[input.dataset.fLane] = value;
      });
      const matrix = {};
      form.querySelectorAll('[data-f-dim]').forEach((input) => { matrix[input.dataset.fDim] = input.checked ? 1 : 0; });
      const idValue = get('[data-f="id"]');
      const hero = {
        ...old,
        id: idValue === '' ? old.id : Number(idValue),
        defaultLane: get('[data-f="defaultLane"]'),
        defaultType: get('[data-f="defaultType"]'),
        compat: get('[data-f="compat"]'),
        lanes, matrix,
      };
      if (eff.eventId || eff.eventName || eff.from || eff.to) hero.effective = eff;
      else delete hero.effective;
      return [{ key: name, hero }];
    }
    const source = ed.entry || newEntry(ed.kind, ed.sub);
    if (ed.kind === 'counters') {
      const comboMode = state.counterSub === 'combo';
      const as = comboMode ? [get('[data-f="a"]')] : (picker?.a || []).map(text).filter(Boolean);
      const bs = comboMode ? [get('[data-f="b"]')] : (picker?.b || []).map(text).filter(Boolean);
      if (!as.length || !bs.length || as.some((v) => !v) || bs.some((v) => !v)) {
        const target = !as.length || as.some((v) => !v)
          ? (comboMode ? '[data-f="a"]' : '[data-rc-picker="a"]')
          : (comboMode ? '[data-f="b"]' : '[data-rc-picker="b"]');
        fieldError(form, comboMode ? '攻方与受方都要填写。' : '攻方与受方都要选择英雄。', target);
        return null;
      }
      const out = [];
      for (const a of as) for (const b of bs) {
        if (a === b) continue;
        // 1对1 / 1对多 / 多对多：笛卡尔展开为多条有向关系（每条都带自己的修订与历史）。
        const base = ed.mode === 'edit' ? source : { ...source, id: newId('counters') };
        out.push({ ...base, a, b, strength: get('[data-f="strength"]') || '中',
          lane: get('[data-f="lane"]') || '全部', note: get('[data-f="note"]'), effective: eff });
      }
      if (!out.length) {
        fieldError(form, comboMode ? '攻方与受方不能是同一个对象。' : '攻方与受方不能是同一个英雄。',
          comboMode ? '[data-f="b"]' : '[data-rc-picker="b"]');
        return null;
      }
      return out;
    }
    if (ed.kind === 'misc') {
      const key = get('[data-f="key"]').slice(0, 80);
      if (!key) { fieldError(form, '请填写规则键。', '[data-f="key"]'); return null; }
      return [{ ...source, group: get('[data-f="group"]') || '自定义', key,
        value: get('[data-f="value"]'), note: get('[data-f="note"]'), effective: eff }];
    }
    return null;
  }

  function applyEntries(ed, entries) {
    if (!entries?.length) return 0;
    const kind = ed.kind;
    const doc = state.docs[kind];
    if (!doc) return 0;
    if (kind === 'hero_tags') {
      const heroes = { ...(doc.heroes || {}) };
      const meta = { ...(doc._rulesMeta || {}) };
      const at = new Date().toISOString();
      for (const { key, hero } of entries) {
        const old = heroes[ed.key];
        const m = meta[ed.key] || { revision: 0, history: [] };
        if (!old || JSON.stringify(old) !== JSON.stringify(hero)) {
          meta[key] = {
            revision: (Number(m.revision) || 0) + 1,
            history: [...(m.history || []).slice(-19), { at, revision: Number(m.revision) || 0, snapshot: old || null }],
          };
        } else {
          meta[key] = m;
        }
        if (ed.key && ed.key !== key) { delete heroes[ed.key]; delete meta[ed.key]; }
        heroes[key] = hero;
      }
      doc.heroes = heroes;
      doc._rulesMeta = meta;
      return entries.length;
    }
    const listKey = kind === 'counters'
      ? (COUNTER_SUBS.find((s) => s.key === ed.sub) || COUNTER_SUBS[0]).list
      : KIND_META[kind].list;
    const prev = doc[listKey] || [];
    const next = prev.slice();
    if (ed.mode === 'edit') {
      const at = next.findIndex((row) => String(row.id) === String(ed.entry.id));
      if (at >= 0) next.splice(at, 1, ...entries);
      else next.push(...entries);
    } else {
      next.push(...entries);
    }
    doc[listKey] = stampEntries(next, prev, (row) => String(row.id));
    return entries.length;
  }
  function applyDelete(ed) {
    const doc = state.docs[ed.kind];
    if (!doc) return;
    if (ed.kind === 'hero_tags') {
      const heroes = { ...(doc.heroes || {}) };
      delete heroes[ed.key];
      doc.heroes = heroes;
      if (doc._rulesMeta) {
        const meta = { ...doc._rulesMeta }; delete meta[ed.key]; doc._rulesMeta = meta;
      }
      return;
    }
    const listKey = ed.kind === 'counters'
      ? (COUNTER_SUBS.find((s) => s.key === ed.sub) || COUNTER_SUBS[0]).list
      : KIND_META[ed.kind].list;
    doc[listKey] = (doc[listKey] || []).filter((row) => String(row.id) !== String(ed.entry.id));
  }

  function switchTab(key) {
    if (!TABS.some((tab) => tab.key === key) || key === state.active) return;
    const dirtyKinds = Object.keys(KIND_META).filter((k) => k !== activeKind() && dirty(k));
    if (dirtyKinds.length && !window.confirm(`还有未保存的修改（${dirtyKinds.map((k) => KIND_META[k].label).join('、')}），确定切换吗？`)) return;
    state.active = key;
    setNotice('', { quiet: true });
    paint();
    mountTools(activeKind());
  }

  /* ── 事件 ─────────────────────────────────────────────────────────── */
  function onClick(event) {
    const tab = event.target.closest('[data-rc-tab]');
    if (tab) { switchTab(tab.dataset.rcTab); return; }
    const jump = event.target.closest('[data-rc-jump]');
    if (jump) { location.hash = jump.dataset.rcJump; return; }
    const reload = event.target.closest('[data-rc-reload]');
    if (reload) { load(reload.dataset.rcReload); return; }
    const saveBtn = event.target.closest('[data-rc-save]');
    if (saveBtn) { save(saveBtn.dataset.rcSave, `${KIND_META[saveBtn.dataset.rcSave].label}：手动保存`); return; }
    const add = event.target.closest('[data-rc-add]');
    if (add) { addEntry(add.dataset.rcAdd, add.dataset.rcSub || state.counterSub); return; }
    const edit = event.target.closest('[data-rc-edit]');
    if (edit) { editEntry(edit.dataset.rcKind, edit.dataset.rcEdit, edit.dataset.rcSub); return; }
    const del = event.target.closest('[data-rc-del]');
    if (del) { deleteEntry(del.dataset.rcKind, del.dataset.rcDel, del.dataset.rcSub); return; }
    const heroEdit = event.target.closest('[data-rc-edit-hero]');
    if (heroEdit) { editEntry('hero_tags', heroEdit.dataset.rcEditHero); return; }
    const heroDel = event.target.closest('[data-rc-del-hero]');
    if (heroDel) { deleteEntry('hero_tags', heroDel.dataset.rcDelHero); return; }
    const hist = event.target.closest('[data-rc-history]');
    if (hist) { showHistory(hist.dataset.rcKind, hist.dataset.rcHistory, hist.dataset.rcSub, hist.dataset.rcName); return; }
    const sub = event.target.closest('[data-rc-counter-sub]');
    if (sub) { state.counterSub = sub.dataset.rcCounterSub; paintCounters(); return; }
    /* 先选分路，再点英雄：group 区分弹窗两侧与列表两张子表。 */
    const laneBtn = event.target.closest('[data-rc-lane]');
    if (laneBtn) {
      const group = laneBtn.dataset.rcLane;
      const lane = laneBtn.dataset.rcLaneName;
      // 按钮高亮就地更新（行内的按钮不参与网格重画）。
      laneBtn.closest('.rc-lane-row')?.querySelectorAll('.rc-lane').forEach((btn) => {
        const on = btn.dataset.rcLaneName === lane;
        btn.classList.toggle('is-on', on);
        btn.setAttribute('aria-pressed', String(on));
      });
      if (group === 'pick-a' || group === 'pick-b') {
        if (picker) {
          picker.lane[group.slice(-1)] = lane;
          paintPickGrid(group.slice(-1));
        }
      } else if (group === 'filter-hero' || group === 'filter-combo') {
        const sub = group.slice('filter-'.length);
        state.counterFilterLane[sub] = lane;
        paintCounterFilter(sub);
      }
      return;
    }
    /* 克制表英雄头像筛选：chips 的 × 在 summary 里，preventDefault 防止顺手把面板收起。 */
    const cfHero = event.target.closest('[data-rc-cfilter-hero]');
    if (cfHero) { toggleCounterFilter(cfHero.dataset.rcCfilterHero, text(cfHero.dataset.rcCfilterName)); return; }
    const cfRemove = event.target.closest('[data-rc-cfilter-remove]');
    if (cfRemove) {
      event.preventDefault();
      toggleCounterFilter(cfRemove.dataset.rcCfilterRemove, text(cfRemove.dataset.rcCfilterRemoveName));
      return;
    }
    const cfClear = event.target.closest('[data-rc-cfilter-clear]');
    if (cfClear) {
      state.counterFilter[cfClear.dataset.rcCfilterClear] = [];
      paintCounters();
      announce('已清空英雄筛选');
      return;
    }
    /* 弹窗内头像选择：点头像切换，chips × 移除。 */
    const pick = event.target.closest('[data-rc-pick]');
    if (pick) { togglePick(pick.dataset.rcPick, text(pick.dataset.rcPickName)); return; }
    const pickRemove = event.target.closest('[data-rc-pick-remove]');
    if (pickRemove) { togglePick(pickRemove.dataset.rcPickRemove, text(pickRemove.dataset.rcPickRemoveName)); return; }
    if (event.target.closest('[data-rc-dialog-cancel]')) {
      root.querySelector('[data-rc-dialog]')?.close(); state.editing = null; return;
    }
  }
  function onInput(event) {
    // 弹窗内的头像选择器搜索：先过滤网格，再照常清掉上一条字段错误。
    const pickSearch = event.target.closest('[data-rc-pick-search]');
    if (pickSearch && picker) {
      const side = pickSearch.dataset.rcPickSearch;
      picker.q[side] = pickSearch.value;
      paintPickGrid(side);
    }
    if (event.target.closest?.('[data-rc-dialog-form]')) {
      clearFieldError(event.target.closest('form'));   // 改动字段即清掉上一条弹窗内错误
      return;
    }
    const filterSearch = event.target.closest('[data-rc-cfilter-search]');
    if (filterSearch) {
      const sub = filterSearch.dataset.rcCfilterSearch;
      state.counterFilterQ[sub] = filterSearch.value;
      paintCounterFilter(sub);
      return;
    }
    const search = event.target.closest('[data-rc-search]');
    if (!search) return;
    state.query[search.dataset.rcSearch] = search.value;
    const key = search.dataset.rcSearch;
    if (key === 'hero-tags') paintHeroTags();
    else if (key === 'misc') paintMisc();
  }
  function onChange(event) {
    const size = event.target.closest('[data-rc-size-filter]');
    const lane = event.target.closest('[data-rc-hero-lane]');
    if (lane) { state.heroLane = lane.value; paintHeroTags(); }
  }
  function onKeydown(event) {
    if (!event.target.closest('[data-rc-tab]')) return;
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const index = TABS.findIndex((t) => t.key === state.active);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
    switchTab(TABS[next].key);
    root?.querySelector(`[data-rc-tab="${TABS[next].key}"]`)?.focus();
  }
  function onSubmit(event) {
    const form = event.target;
    if (!form.matches?.('[data-rc-dialog-form]')) return;
    event.preventDefault();
    const ed = state.editing;
    if (!ed) return;
    const dialog = root.querySelector('[data-rc-dialog]');
    clearFieldError(form);
    if (ed.mode === 'delete') {
      applyDelete(ed);
      reportSuccess('已标记删除，点「保存更改」后生效。');
    } else {
      const entries = collectEntries(ed, form);
      if (!entries) return;   // 校验没过：保持对话框打开，错误在弹窗内显示
      const n = applyEntries(ed, entries);
      reportSuccess(`已${ed.mode === 'edit' ? '更新' : '新增'} ${n} 条，点「保存更改」后生效。`, entries);
    }
    state.editing = null;
    dialog.close();
    paint();
  }

  /* ── 页面骨架 ─────────────────────────────────────────────────────── */
  function panelInner(tab) {
    const kind = tab.kind;
    const meta = KIND_META[kind];
    const saveBtn = `<button type="button" class="primary" data-rc-save="${kind}" disabled>保存更改</button>`;
    const reloadBtn = `<button type="button" class="control" data-rc-reload="${kind}">${glyph('arrow-up', { size: 14 })} 重新读取</button>`;
    // search 不在 glyph 白名单：沿用外壳注入的 icon('search')，外壳未提供时退化为纯文字输入框。
    const search = (placeholder) => `<search class="rc-search"><label class="visually-hidden" for="${uid}-search-${tab.key}">搜索${esc(meta.label)}</label>
      ${icon('search')}
      <input id="${uid}-search-${tab.key}" type="search" data-rc-search="${tab.key}" placeholder="${esc(placeholder)}" autocomplete="off"></search>`;
    if (kind === 'hero_tags') {
      return `<section class="section">
        <div class="section-heading"><div><h2>英雄标签（五路 12 类，可直接编辑）</h2></div>
          <div class="rc-panel-actions">${reloadBtn}<span class="rc-count" data-rc-hero-count></span>${saveBtn}</div></div>
        <div class="rc-filter">${search('按英雄名 / 类型搜索')}
          <label>分路 <select data-rc-hero-lane>${['全部', ...LANES].map((l) => `<option${state.heroLane === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
          <button type="button" class="primary" data-rc-add="hero_tags">${plus({ size: 14 })} 新增英雄</button></div>
        <div class="rc-table-wrap" tabindex="0" role="region" aria-labelledby="${uid}-cap-hero">
          <table class="rc-table"><caption id="${uid}-cap-hero" class="visually-hidden">英雄标签表</caption>
            <thead><tr><th scope="col">英雄</th><th scope="col">默认分路</th><th scope="col">默认类型</th><th scope="col">兼容定位</th><th scope="col">分路 → 类型</th><th scope="col">能力矩阵</th><th scope="col">修订 / 历史</th><th scope="col">操作</th></tr></thead>
            <tbody data-rc-body="hero-tags"></tbody></table></div>
      </section>`;
    }
    if (kind === 'counters') {
      const heroFilter = (subKey) => `<details class="rc-hero-filter" data-rc-cfilter-wrap="${subKey}">
          <summary><span class="rc-hero-filter-label">英雄筛选</span>
            <span class="rc-hero-filter-chips" data-rc-cfilter-chips="${subKey}"></span>
            <span class="rc-hero-filter-count" data-rc-cfilter-count="${subKey}"></span></summary>
          <div class="rc-hero-filter-body">
            ${laneBtns(`filter-${subKey}`, state.counterFilterLane[subKey] || '全部')}
            <input type="search" data-rc-cfilter-search="${subKey}" placeholder="搜英雄名" autocomplete="off">
            <div class="rc-hero-filter-grid" data-rc-cfilter-grid="${subKey}"></div>
            <div class="rc-hero-filter-foot"><button type="button" class="control" data-rc-cfilter-clear="${subKey}" disabled>清空筛选</button></div>
          </div>
        </details>`;
      return `<section class="section">
        <div class="section-heading"><div><h2>克制关系</h2></div>
          <div class="rc-panel-actions">${reloadBtn}${saveBtn}</div></div>
        <p class="rc-effective-hint">克制规则支持「按赛事生效」：条目里填赛事 ID / 名称或时间窗，未填＝常年生效；BP 习惯的克制命中会按当前赛事自动取用。</p>
        <div class="rc-subtabs" role="group" aria-label="克制关系子表">
          ${COUNTER_SUBS.map((s) => `<button type="button" class="rc-subtab" data-rc-counter-sub="${s.key}" aria-pressed="${state.counterSub === s.key}">${esc(s.label)}</button>`).join('')}
        </div>
        <div class="rc-filter" data-rc-counter-panel="hero"${state.counterSub !== 'hero' ? ' hidden' : ''}>
          ${heroFilter('hero')}<button type="button" class="primary" data-rc-add="counters" data-rc-sub="hero">${plus({ size: 14 })} 新增英雄克制</button></div>
        <div class="rc-table-wrap" tabindex="0" role="region" aria-labelledby="${uid}-cap-ch" data-rc-counter-panel="hero"${state.counterSub !== 'hero' ? ' hidden' : ''}>
          <table class="rc-table"><caption id="${uid}-cap-ch" class="visually-hidden">英雄克制英雄</caption>
            <thead><tr><th scope="col">攻方</th><th scope="col">受方</th><th scope="col">方向</th><th scope="col">强度</th><th scope="col">分路</th><th scope="col">生效赛事 / 时间</th><th scope="col">备注</th><th scope="col">修订 / 历史</th><th scope="col">操作</th></tr></thead>
            <tbody data-rc-body="counters-hero"></tbody></table></div>
        <div class="rc-filter" data-rc-counter-panel="combo"${state.counterSub !== 'combo' ? ' hidden' : ''}>
          ${heroFilter('combo')}<button type="button" class="primary" data-rc-add="counters" data-rc-sub="combo">${plus({ size: 14 })} 新增组合克制</button></div>
        <div class="rc-table-wrap" tabindex="0" role="region" aria-labelledby="${uid}-cap-cc" data-rc-counter-panel="combo"${state.counterSub !== 'combo' ? ' hidden' : ''}>
          <table class="rc-table"><caption id="${uid}-cap-cc" class="visually-hidden">组合克制组合</caption>
            <thead><tr><th scope="col">攻方组合</th><th scope="col">受方组合</th><th scope="col">方向</th><th scope="col">强度</th><th scope="col">分路</th><th scope="col">生效赛事 / 时间</th><th scope="col">备注</th><th scope="col">修订 / 历史</th><th scope="col">操作</th></tr></thead>
            <tbody data-rc-body="counters-combo"></tbody></table></div>
      </section>`;
    }
    return `<section class="section">
      <div class="section-heading"><div><h2>其他规则（异常判定 / 指标口径 / 风格标签）</h2></div>
        <div class="rc-panel-actions">${reloadBtn}${saveBtn}</div></div>
      <div class="rc-filter">${search('按分类 / 键 / 值搜索')}<button type="button" class="primary" data-rc-add="misc">${plus({ size: 14 })} 新增条目</button></div>
      <div class="rc-table-wrap" tabindex="0" role="region" aria-labelledby="${uid}-cap-misc">
        <table class="rc-table"><caption id="${uid}-cap-misc" class="visually-hidden">其他规则表</caption>
          <thead><tr><th scope="col">分类</th><th scope="col">规则键</th><th scope="col">规则值 / 口径</th><th scope="col">备注</th><th scope="col">生效赛事 / 时间</th><th scope="col">修订 / 历史</th><th scope="col">操作</th></tr></thead>
          <tbody data-rc-body="misc"></tbody></table></div>
    </section>`;
  }
  function html() {
    return `<div class="rc-page ${CENTER_LABEL ? 'rc-platinum' : ''}">
      <header class="section rc-head">
        ${deco('divider-title', { cls: 'rc-head-deco' })}
        <div class="section-heading"><div><h1>赛训规则中心</h1></div>
          <span class="rc-doc-rev" data-rc-doc-rev></span></div>
        <p class="rc-notice" data-rc-notice hidden></p>
      </header>
      <nav class="rc-tabs" role="tablist" aria-label="赛训规则分类">
        ${TABS.map((tab) => `<button type="button" role="tab" id="${uid}-tab-${tab.key}"
          aria-controls="${uid}-panel-${tab.key}" aria-selected="${state.active === tab.key}"
          tabindex="${state.active === tab.key ? 0 : -1}" class="rc-tab${state.active === tab.key ? ' is-on' : ''}"
          data-rc-tab="${tab.key}">${glyph(TAB_ICON[tab.key] || 'book', { size: 15 })}<span>${esc(tab.label)}</span></button>`).join('')}
      </nav>
      ${TABS.map((tab) => `<section class="rc-panel" role="tabpanel" id="${uid}-panel-${tab.key}"
        aria-labelledby="${uid}-tab-${tab.key}" data-rc-panel="${tab.key}"${state.active === tab.key ? '' : ' hidden'}>
        ${panelInner(tab)}</section>`).join('')}
      <div class="rc-tools-slot" data-rc-tools-slot></div>
      <dialog class="rc-dialog" data-rc-dialog aria-labelledby="${uid}-dialog-title">
        <div class="rc-dialog-head"><h2 id="${uid}-dialog-title" data-rc-dialog-title></h2></div>
        <form class="rc-dialog-form" data-rc-dialog-form novalidate>
          <div class="rc-dialog-body" data-rc-dialog-body></div>
          <div class="rc-dialog-foot">
            <button type="button" class="control" data-rc-dialog-cancel>取消</button>
            <button type="submit" class="primary" data-rc-dialog-submit>保存</button>
          </div>
        </form>
      </dialog>
    </div>`;
  }

  function bind(node) {
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('input', onInput);
    node.addEventListener('change', onChange);
    node.addEventListener('keydown', onKeydown);
    node.addEventListener('submit', onSubmit);
  }
  function dispose() {
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('input', onInput);
      bound.removeEventListener('change', onChange);
      bound.removeEventListener('keydown', onKeydown);
      bound.removeEventListener('submit', onSubmit);
      bound = null;
    }
    tools?.dispose();
    tools = null;
    clearTimeout(toastTimer);
    controller?.abort();
    controller = null;
    root = null;
    picker = null;
    state.editing = null;
  }
  function mount(node) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    root.innerHTML = html();
    bind(root);
    mountTools(activeKind());
    controller = new AbortController();
    Object.keys(KIND_META).forEach((kind) => load(kind, { quiet: true }));
    loadComboPool();
    paint();
  }

  return { html, render: html, mount, bind, dispose, rerender: paint, state, announce };
}

export default createRulesCenter;

/* ── TODO（明确遗留，不影响当前读 / 展示 / 手改 / 持久化）─────────────────
 * 1. 生效时间目前只存字段 + 展示；对局按赛事正式比赛时间「自动选取当时版本」需
 *    分析链路接入（读取 rules-* 并按 effective 过滤），本页只提供数据契约。
 * 2. 克制表与 counter_library.py / bp_facts 的命中算法未打通：当前是独立规则表，
 *    若要进入命中判定，需要后端新增按赛事版本取表的适配层（不修改原算法文件）。
 * 3. 组合体系表与原 combo-pool.js 的 2/3 人池、阵容标签与原 lineup-tags.js 的标签表
 *    是独立数据；页面提供跳转对照，自动同步 / 合并留待口径统一后处理。
 * 4. 更严格的表单校验（人数与英雄数一致、赛事日期先后、英雄名必须在名录内）。
 * 5. 英雄标签被 scripts/import_hero_tags.py 重新导入会覆盖手工修改，需导入脚本
 *    合并 _rulesMeta 或先导出备份；本页已有提示。
 */
