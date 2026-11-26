/* 单局标签（教练自己写，存后端覆盖层 match_meta.tags）
 *
 * 三个入口共用这一个模块：首页「最值得复盘的比赛」卡片、对局档案的每一局、
 * 单局复盘页顶部的标题区。数据只有一份，任何一处改完其余两处刷新即同步。
 *
 * 用法（渲染侧）：在任意位置放一个空容器
 *     <div class="tagrow" data-tag-key="channel-xxxx"></div>
 * 模块用 MutationObserver 盯着 #content，出现就填上；不需要改各页面的渲染流程。
 *
 * 推荐规则：按「用过的次数」从多到少，输入时按包含匹配过滤；
 * 一次最多露 6 个，再多折成「更多 N 个」。
 */

import { glyph } from './ui-icons.js';

const BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const LIST_URL = `${BASE}/api/v3/match-tags`;
const SAVE_URL = (key) => `${BASE}/api/v3/match-meta/${encodeURIComponent(key)}`;
const SHOW_LIMIT = 6;

const state = {
  ready: false,
  loading: null,
  byMatch: {},
  notes: {},
  searchFields: {},
  vocabulary: [],
  labels: {},
  noteEditor: null,
  /* 查询字段的候选顺序：最新加过的标签排前面，配合 vocabulary 一起在输入时实时更新。 */
  recentTags: [],
  limit: 12,
  maxLength: 16,
  openKey: null,
  draft: '',
};

/* 每个查询框各自记住当前输入的标签（首页 / 对局档案互不影响）。 */
const queryState = {};

const text = (value) => String(value ?? '').trim();
const esc = (value) => text(value).replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

/* 中文等 IME 下，确认候选词的回车也会发 keydown：此时 isComposing 为 true，
   Safari 因事件顺序bug还会把 keyCode 报成 229。此时输入框里还是没上屏的拼音，
   直接 addTag 会存空/存错——表现就是「回车保存失效」。两个回车入口都要挡一下。 */
const imeConfirming = (event) => event.isComposing === true || event.keyCode === 229;

export function tagsOf(key) {
  const list = state.byMatch[text(key)];
  return Array.isArray(list) ? list.slice() : [];
}

/** 标签上的关联备注（与「赛后笔记」分开存，属于 match_meta.tagNotes）。 */
export function tagNotesOf(key) {
  const notes = state.notes[text(key)];
  return notes && typeof notes === 'object' ? { ...notes } : {};
}

export function vocabulary() {
  return state.vocabulary.slice();
}

/** 档案页等调用方等标签数据到位后再渲染；重复调用安全。 */
export function tagsReady() {
  return ensureLoaded();
}

/** 批量打标签后强制重读后端覆盖层，保持各入口的标签视图一致。 */
export function reloadTags() {
  state.ready = false;
  state.loading = null;
  return ensureLoaded();
}

/** 一次写入整局的标签与关联备注；重点关注页用它原子地保存「关注 + 原因 + 说明」。 */
export function setMatchTags(key, tags, notes) {
  return apply(text(key), Array.isArray(tags) ? tags.map(text).filter(Boolean) : [], notes);
}

function ensureLoaded() {
  if (state.ready) return Promise.resolve(state);
  if (state.loading) return state.loading;
  state.loading = fetch(LIST_URL, { headers: { Accept: 'application/json' } })
    .then((response) => (response.ok ? response.json() : null))
    .then((payload) => {
      if (payload && payload.ok) {
        state.byMatch = payload.byMatch || {};
        state.notes = payload.notes || {};
        state.searchFields = payload.search || {};
        state.vocabulary = Array.isArray(payload.tags) ? payload.tags : [];
        state.labels = payload.labels && typeof payload.labels === 'object' ? payload.labels : {};
        state.recentTags = state.vocabulary.map((item) => text(item.name)).filter(Boolean);
        state.limit = Number(payload.limit) || state.limit;
        state.maxLength = Number(payload.maxLength) || state.maxLength;
      }
      state.ready = true;
      return state;
    })
    .catch(() => {
      state.ready = true;
      return state;
    })
    .finally(() => { state.loading = null; });
  return state.loading;
}

/* ── 渲染 ─────────────────────────────────────────────────────── */

function suggestions(keyword) {
  const word = text(keyword).toLowerCase();
  return state.vocabulary
    .filter((item) => !word || text(item.name).toLowerCase().includes(word))
    .map((item) => text(item.name))
    .filter(Boolean);
}

function notesOf(key) {
  const notes = state.notes[key];
  return notes && typeof notes === 'object' ? notes : {};
}

function chipsHtml(key) {
  const tags = tagsOf(key);
  const notes = notesOf(key);
  return tags.map((tag) => {
    const note = text(notes[tag]);
    const editing = state.noteEditor && state.noteEditor.key === key && state.noteEditor.tag === tag;
    return `<span class="tagchip" data-tag-own="${esc(key)}">
      <span class="tagchip-text"${note ? ` title="${esc(note)}"` : ''}>${esc(tag)}${note ? '<i class="tagchip-dot" aria-hidden="true"></i>' : ''}</span>
      <button type="button" class="tagchip-note" data-tag-note="${esc(key)}"
        data-tag-name="${esc(tag)}" title="给「${esc(tag)}」写备注" aria-label="给标签 ${esc(tag)} 写备注">${glyph('edit', { size: 16 })}</button>
      <button type="button" class="tagchip-x" data-tag-remove="${esc(key)}"
        data-tag-name="${esc(tag)}" title="去掉「${esc(tag)}」" aria-label="去掉标签 ${esc(tag)}">${glyph('trash', { size: 16 })}</button>
      ${editing ? `<span class="tagnote-editor"><input class="tagnote-input" data-tagnote-input="${esc(key)}"
        data-tag-name="${esc(tag)}" value="${esc(note)}" maxlength="200" placeholder="为什么标记这一局（可不填）"
        aria-label="标签 ${esc(tag)} 在本局的备注"><button type="button" data-tagnote-save="${esc(key)}"
        data-tag-name="${esc(tag)}">${glyph('pick', { size: 16 })} 保存</button></span>` : ''}
    </span>`;
  }).join('');
}

function pickerHtml(key) {
  if (state.openKey !== key) return '';
  const pool = suggestions(state.draft);
  const shown = pool.slice(0, SHOW_LIMIT);
  const rest = pool.length - shown.length;
  const options = shown.map((name) => `<button type="button" class="tagpick" data-tag-pick="${esc(key)}"
      data-tag-name="${esc(name)}">${esc(name)}</button>`).join('');
  return `<span class="tagpick-wrap">
      <input class="taginput" data-tag-input="${esc(key)}" value="${esc(state.draft)}"
        maxlength="${state.maxLength}" placeholder="输入标签，回车保存" autocomplete="off"
        aria-label="给这一局加标签" list="none">
      ${shown.length ? `<span class="tagpick-list">${options}${rest > 0
        ? `<button type="button" class="tagpick tagpick-more" data-tag-more="${esc(key)}">更多 ${rest} 个</button>`
        : ''}</span>` : ''}
    </span>`;
}

function rowHtml(key) {
  const tags = tagsOf(key);
  const full = tags.length >= state.limit;
  return `${chipsHtml(key)}
    ${full ? '' : `<button type="button" class="tagadd" data-tag-add="${esc(key)}"
      title="给这一局加标签">${glyph('edit', { size: 18 })} 加标签</button>`}
    ${pickerHtml(key)}`;
}

function paint(node) {
  const key = text(node.dataset.tagKey);
  if (!key) return;
  node.innerHTML = rowHtml(key);
  node.dataset.tagReady = '1';
  if (state.openKey === key) {
    const input = node.querySelector('.taginput');
    if (input) input.focus();
  }
  if (state.noteEditor && state.noteEditor.key === key) {
    const input = node.querySelector('.tagnote-input');
    if (input) input.focus();
  }
}

function repaint(key) {
  document.querySelectorAll('.tagrow').forEach((node) => {
    if (text(node.dataset.tagKey) === text(key)) paint(node);
  });
  document.querySelectorAll('[data-tag-strip]').forEach((node) => {
    if (text(node.dataset.tagStrip) === text(key)) paintStrip(node);
  });
}

function paintStrip(node) {
  const key = text(node.dataset.tagStrip);
  const tags = tagsOf(key);
  node.innerHTML = tags.map((tag) => `<span class="tagchip tagchip-ro">${esc(tag)}</span>`).join('');
  node.hidden = !tags.length;
  node.dataset.tagStripReady = '1';
}

/* 把 #content 里所有还没有内容的标签容器填上；重复调用安全。
   .tagrow 是可编辑的（chips + ＋标签）；.tagstrip 是只读的（档案列表卡片里
   已经在 <a> 里，不能再塞按钮，只显示标签本身）。 */
export function mount(root) {
  const host = root || document;
  host.querySelectorAll('.tagrow').forEach((node) => {
    if (!node.dataset.tagReady || !node.childElementCount) paint(node);
  });
  host.querySelectorAll('[data-tag-strip]:not([data-tag-strip-ready])').forEach(paintStrip);
  host.querySelectorAll('[data-tagquery]:not([data-tagquery-ready])').forEach(paintQuery);
  host.querySelectorAll('[data-tagbar]:not([data-tagbar-ready])').forEach(paintBar);
}

/* ── 标签查询：首页复盘区下方 / 对局档案工具栏 ───────────────────────
 * 教练输入或点选一个标签，列出挂过这个标签的对局，点进去就是单局复盘。
 * 候选来自 recentTags（新加的标签排最前），任何一处加完标签这里立刻能查。
 *
 * 页面只放一个空容器：
 *     <div class="tagquery" data-tagquery="home" data-tq-label="标签查询"></div>
 * 本模块用 MutationObserver 盯着 #content，出现就填上，不改各页渲染流程。
 */

const QUERY_CHIP_LIMIT = 14;
const QUERY_DEFAULT_LABEL = { home: '标签查询', matches: '查标签' };

function queryOf(scope) {
  if (!queryState[scope]) queryState[scope] = { value: '', expanded: false };
  return queryState[scope];
}

function queryCandidates(word) {
  const keyword = text(word).toLowerCase();
  const alive = new Set(state.vocabulary.map((item) => text(item.name)));
  const names = state.recentTags.filter((name) => alive.has(name));
  return keyword ? names.filter((name) => name.toLowerCase().includes(keyword)) : names;
}

function matchLabel(key) {
  return text(state.labels[key]) || text(key);
}

function queryMatches(word) {
  const tag = text(word);
  if (!tag) return [];
  return Object.keys(state.byMatch)
    .filter((key) => (state.byMatch[key] || []).includes(tag))
    .sort((a, b) => matchLabel(a).localeCompare(matchLabel(b), 'zh-Hans-CN'));
}

function queryResultsHtml(word) {
  const tag = text(word);
  if (!tag) return '';
  const keys = queryMatches(tag);
  if (!keys.length) {
    return `<p class="tq-empty">还没有对局挂过「${esc(tag)}」这个标签。</p>`;
  }
  const hits = keys.map((key) => `<a class="tq-hit" href="#match/${encodeURIComponent(key)}" title="${esc(key)}">
      <span class="tq-hit-name">${esc(matchLabel(key))}</span>
      <span class="tq-hit-tags">${(state.byMatch[key] || []).map((tagName) => `<i>${esc(tagName)}</i>`).join('')}</span>
      <span class="tq-hit-go" aria-hidden="true">→</span>
    </a>`).join('');
  return `<p class="tq-count">标签「<b>${esc(tag)}</b>」· 找到 ${keys.length} 局</p>
    <div class="tq-hits">${hits}</div>`;
}

function queryChipsHtml(scope, word) {
  const pool = queryCandidates(word);
  if (!pool.length) {
    return state.vocabulary.length
      ? '<span class="tq-chip-empty">没有匹配的标签</span>'
      : '<span class="tq-chip-empty">还没有标签：先在复盘卡或档案里点「加标签」创建一个</span>';
  }
  const shown = queryOf(scope).expanded ? pool : pool.slice(0, QUERY_CHIP_LIMIT);
  const rest = pool.length - shown.length;
  return shown.map((name) => `<button type="button" class="tq-chip${name === text(word) ? ' is-on' : ''}"
      data-tq-pick="${esc(scope)}" data-tq-name="${esc(name)}">${esc(name)}</button>`).join('')
    + (rest > 0 ? `<button type="button" class="tq-chip tq-chip-more" data-tq-more="${esc(scope)}">更多 ${rest} 个</button>` : '');
}

/* 只重画候选与结果，不碰输入框：输入过程中光标不会丢。 */
function paintQueryParts(node, scope) {
  const word = queryOf(scope).value;
  const chips = node.querySelector('.tq-chips');
  const out = node.querySelector('.tq-out');
  const clear = node.querySelector('[data-tq-clear]');
  if (chips) chips.innerHTML = queryChipsHtml(scope, word);
  if (out) out.innerHTML = queryResultsHtml(word);
  if (clear) clear.hidden = !text(word);
}

function paintQuery(node) {
  /* 注意：data-tagquery 没有内部连字符，dataset 里是小写 tagquery，不是 tagQuery。 */
  const scope = text(node.dataset.tagquery);
  if (!scope) return;
  const label = text(node.dataset.tqLabel) || QUERY_DEFAULT_LABEL[scope] || '标签查询';
  const word = queryOf(scope).value;
  node.innerHTML = `<div class="tq-body">
      <div class="tq-head">${glyph('matches', { label: '标签查询', size: 18 })}<b>${esc(label)}</b></div>
      <div class="tq-bar">
        <input class="tq-input" data-tq-input="${esc(scope)}" value="${esc(word)}"
          maxlength="${state.maxLength}" placeholder="输入标签，如：团战" autocomplete="off"
          list="none" aria-label="按标签查询对局">
        <button type="button" class="tq-go" data-tq-go="${esc(scope)}">${glyph('matches', { size: 18 })} 查询</button>
        <button type="button" class="tq-clear" data-tq-clear="${esc(scope)}"${text(word) ? '' : ' hidden'}>${glyph('refresh', { size: 18 })} 清除</button>
      </div>
      <div class="tq-chips" data-tq-chips="${esc(scope)}"></div>
      <div class="tq-out" data-tq-out="${esc(scope)}"></div>
    </div>`;
  node.dataset.tagqueryReady = '1';
  paintQueryParts(node, scope);
}

function repaintQueries() {
  document.querySelectorAll('[data-tagquery]').forEach((node) => {
    if (node.dataset.tagqueryReady) paintQueryParts(node, text(node.dataset.tagquery));
  });
}

/* ── 首页标签检索栏：组合检索 + 跨周期找回 ───────────────────────
 * 标签是赛训组找回历史比赛的入口，不是卡片的附属品。选中多个标签是「且」，
 * 关键词同时匹配标签名、英雄、对手和日期；命中范围是所有打过标签的对局，
 * 不受首页「最近 5 场」周期影响。系统特征（复盘类型）不进自定义标签词表。
 */
const barState = {};

function barOf(scope) {
  if (!barState[scope]) barState[scope] = { keyword: '', tags: [], expanded: false, manage: false };
  return barState[scope];
}

function barCandidates(word) {
  const keyword = text(word).toLowerCase();
  const names = state.vocabulary.map((item) => text(item.name)).filter(Boolean);
  return keyword ? names.filter((name) => name.toLowerCase().includes(keyword)) : names;
}

function barHitKeys(scope) {
  const bar = barOf(scope);
  const keyword = text(bar.keyword).toLowerCase();
  return Object.keys(state.byMatch).filter((key) => {
    const tags = state.byMatch[key] || [];
    if (!bar.tags.every((tag) => tags.includes(tag))) return false;
    if (!keyword) return true;
    const field = state.searchFields[key] || {};
    const haystack = [...tags, ...(field.heroes || []), field.opponent, field.date]
      .filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(keyword);
  }).sort((a, b) => text((state.searchFields[b] || {}).date)
    .localeCompare(text((state.searchFields[a] || {}).date)));
}

function barChipsHtml(scope, word) {
  const pool = barCandidates(word);
  if (!pool.length) {
    return `<span class="tagbar-empty">${state.vocabulary.length ? '没有匹配的标签' : '还没有标签：在下方卡片点「加标签」创建'}</span>`;
  }
  const bar = barOf(scope);
  const shown = bar.expanded ? pool : pool.slice(0, 10);
  const rest = pool.length - shown.length;
  return shown.map((name) => `<button type="button" class="tagbar-chip${bar.tags.includes(name) ? ' is-on' : ''}"
      data-tb-tag="${esc(scope)}" data-tb-name="${esc(name)}" aria-pressed="${String(bar.tags.includes(name))}">
      <span>${esc(name)}</span><i aria-hidden="true">${state.vocabulary.find((v) => text(v.name) === name)?.count || ''}</i>
    </button>`).join('')
    + (rest > 0 ? `<button type="button" class="tagbar-chip is-more" data-tb-more="${esc(scope)}">更多 ${rest} 个</button>` : '');
}

function barResultsHtml(scope) {
  const bar = barOf(scope);
  if (!bar.tags.length && !text(bar.keyword)) return '';
  const keys = barHitKeys(scope);
  if (!keys.length) return '<p class="tagbar-empty">没有同时满足这些条件的对局。</p>';
  const rows = keys.map((key) => {
    const notes = notesOf(key);
    const note = bar.tags.map((tag) => notes[tag] ? `<small>${esc(text(notes[tag]))}</small>` : '').join('');
    return `<a class="tagbar-hit" href="#match/${encodeURIComponent(key)}">
      <span class="tagbar-hit-name">${esc(matchLabel(key))}</span>
      <span class="tagbar-hit-tags">${(state.byMatch[key] || []).map((tag) => `<i${bar.tags.includes(tag) ? ' class="is-on"' : ''}>${esc(tag)}</i>`).join('')}</span>
      ${note}
      <span aria-hidden="true">→</span>
    </a>`;
  }).join('');
  return `<p class="tagbar-count">找到 ${keys.length} 场对局</p><div class="tagbar-hits">${rows}</div>`;
}

function barManageHtml(scope) {
  const bar = barOf(scope);
  if (!bar.manage) return '';
  const rows = state.vocabulary.map((item) => {
    const name = text(item.name);
    if (!name) return '';
    return `<span class="tagbar-manage-row"><span>${esc(name)} · ${item.count} 场</span>
      <button type="button" data-tb-rename="${esc(scope)}" data-tb-name="${esc(name)}">${glyph('edit', { size: 16 })} 重命名</button>
      <button type="button" data-tb-delete="${esc(scope)}" data-tb-name="${esc(name)}">${glyph('trash', { size: 16 })} 删除</button></span>`;
  }).join('');
  return `<div class="tagbar-manage">${rows || '<span class="tagbar-empty">还没有标签可管理</span>'}</div>`;
}

function paintBarParts(node, scope) {
  const bar = barOf(scope);
  const chips = node.querySelector('[data-tb-chips]');
  const out = node.querySelector('[data-tb-out]');
  const manage = node.querySelector('[data-tb-manage]');
  const status = node.querySelector('[data-tb-status]');
  if (chips) chips.innerHTML = barChipsHtml(scope, bar.keyword);
  if (out) out.innerHTML = barResultsHtml(scope);
  if (manage) manage.innerHTML = barManageHtml(scope);
  if (status) {
    const active = bar.tags.length || text(bar.keyword);
    status.textContent = active ? `已选 ${bar.tags.length} 个标签${text(bar.keyword) ? ` · 关键词「${text(bar.keyword)}」` : ''}` : '';
  }
  document.dispatchEvent(new CustomEvent('match-tags:filter', {
    detail: { scope, tags: bar.tags.slice(), keyword: text(bar.keyword), keys: barHitKeys(scope) },
  }));
}

function paintBar(node) {
  const scope = text(node.dataset.tagbar);
  if (!scope) return;
  const bar = barOf(scope);
  node.innerHTML = `<search class="tagbar-body" aria-label="按标签检索对局">
    <form class="tagbar-form" data-tb-form="${esc(scope)}" method="GET" action="#">
      <label for="tb-input-${esc(scope)}">标签检索</label>
      <input type="search" id="tb-input-${esc(scope)}" data-tb-input="${esc(scope)}" value="${esc(bar.keyword)}"
        placeholder="标签名 / 英雄 / 对手 / 日期" maxlength="40" autocomplete="off" autocorrect="off" spellcheck="false" list="none">
      <button type="submit">${glyph('matches', { size: 18 })} 检索</button>
      <button type="button" data-tb-reset="${esc(scope)}">${glyph('refresh', { size: 18 })} 重置</button>
      <button type="button" data-tb-manage-toggle="${esc(scope)}">${glyph('edit', { size: 18 })} 管理标签</button>
    </form>
    <fieldset class="tagbar-fieldset"><legend>常用标签</legend>
      <div class="tagbar-chips" data-tb-chips="${esc(scope)}"></div>
    </fieldset>
    <div class="tagbar-foot"><span data-tb-status="${esc(scope)}"></span></div>
    <div class="tagbar-out" data-tb-out="${esc(scope)}"></div>
    <div data-tb-manage="${esc(scope)}"></div>
  </search>`;
  node.dataset.tagbarReady = '1';
  paintBarParts(node, scope);
}

function repaintBars() {
  document.querySelectorAll('[data-tagbar]').forEach((node) => {
    if (node.dataset.tagbarReady) paintBarParts(node, text(node.dataset.tagbar));
  });
}

/* ── 查询事件（与加标签的 data-tag-* 完全分开，互不干扰） ────────── */

document.addEventListener('click', (event) => {
  const pick = event.target.closest('[data-tq-pick]');
  if (pick) {
    event.preventDefault();
    const scope = text(pick.dataset.tqPick);
    const query = queryOf(scope);
    query.value = text(pick.dataset.tqName);
    query.expanded = false;
    const node = pick.closest('[data-tagquery]');
    const input = node && node.querySelector('[data-tq-input]');
    if (input) input.value = query.value;
    if (node) paintQueryParts(node, scope);
    return;
  }
  const more = event.target.closest('[data-tq-more]');
  if (more) {
    event.preventDefault();
    const scope = text(more.dataset.tqMore);
    queryOf(scope).expanded = true;
    const node = more.closest('[data-tagquery]');
    if (node) paintQueryParts(node, scope);
    return;
  }
  const go = event.target.closest('[data-tq-go]');
  if (go) {
    event.preventDefault();
    const scope = text(go.dataset.tqGo);
    const node = go.closest('[data-tagquery]');
    const input = node && node.querySelector('[data-tq-input]');
    const query = queryOf(scope);
    query.value = text(input && input.value);
    query.expanded = false;
    if (node) paintQueryParts(node, scope);
    return;
  }
  const clear = event.target.closest('[data-tq-clear]');
  if (clear) {
    event.preventDefault();
    const scope = text(clear.dataset.tqClear);
    const query = queryOf(scope);
    query.value = '';
    query.expanded = false;
    const node = clear.closest('[data-tagquery]');
    const input = node && node.querySelector('[data-tq-input]');
    if (input) input.value = '';
    if (node) paintQueryParts(node, scope);
  }
});

document.addEventListener('input', (event) => {
  const input = event.target.closest('[data-tq-input]');
  if (!input) return;
  const scope = text(input.dataset.tqInput);
  const query = queryOf(scope);
  query.value = input.value;
  query.expanded = false;
  const node = input.closest('[data-tagquery]');
  if (node) paintQueryParts(node, scope);
});

document.addEventListener('keydown', (event) => {
  const input = event.target.closest('[data-tq-input]');
  if (!input || event.key !== 'Enter') return;
  event.preventDefault();
  /* IME 正在选字：这次回车只是让候选词上屏，不当成「查询」。 */
  if (imeConfirming(event)) return;
  const scope = text(input.dataset.tqInput);
  const query = queryOf(scope);
  query.value = input.value;
  query.expanded = false;
  const node = input.closest('[data-tagquery]');
  if (node) paintQueryParts(node, scope);
});

/* 任何一处加/删标签都会走 apply() → 这里跟着刷新候选与结果，做到实时更新。 */
document.addEventListener('match-tags:change', () => { repaintQueries(); repaintBars(); });

/* ── 检索栏事件 ─────────────────────────────────────────────── */

function barNode(target) {
  return target.closest('[data-tagbar]');
}

document.addEventListener('click', (event) => {
  const chip = event.target.closest('[data-tb-tag]');
  if (chip) {
    event.preventDefault();
    const scope = text(chip.dataset.tbTag);
    const name = text(chip.dataset.tbName);
    const bar = barOf(scope);
    bar.tags = bar.tags.includes(name) ? bar.tags.filter((item) => item !== name) : bar.tags.concat(name);
    const node = barNode(chip);
    if (node) paintBarParts(node, scope);
    return;
  }
  const more = event.target.closest('[data-tb-more]');
  if (more) {
    event.preventDefault();
    const scope = text(more.dataset.tbMore);
    barOf(scope).expanded = true;
    const node = barNode(more);
    if (node) paintBarParts(node, scope);
    return;
  }
  const reset = event.target.closest('[data-tb-reset]');
  if (reset) {
    event.preventDefault();
    const scope = text(reset.dataset.tbReset);
    barState[scope] = { keyword: '', tags: [], expanded: false, manage: barOf(scope).manage };
    const node = barNode(reset);
    const input = node && node.querySelector('[data-tb-input]');
    if (input) input.value = '';
    if (node) paintBarParts(node, scope);
    return;
  }
  const manageToggle = event.target.closest('[data-tb-manage-toggle]');
  if (manageToggle) {
    event.preventDefault();
    const scope = text(manageToggle.dataset.tbManageToggle);
    barOf(scope).manage = !barOf(scope).manage;
    const node = barNode(manageToggle);
    if (node) paintBarParts(node, scope);
    return;
  }
  const rename = event.target.closest('[data-tb-rename]');
  if (rename) {
    event.preventDefault();
    renameTag(text(rename.dataset.tbName));
    return;
  }
  const del = event.target.closest('[data-tb-delete]');
  if (del) {
    event.preventDefault();
    deleteTag(text(del.dataset.tbName));
  }
});

document.addEventListener('input', (event) => {
  const input = event.target.closest('[data-tb-input]');
  if (!input) return;
  const scope = text(input.dataset.tbInput);
  const bar = barOf(scope);
  bar.keyword = input.value;
  bar.expanded = false;
  const node = barNode(input);
  if (node) paintBarParts(node, scope);
});

document.addEventListener('submit', (event) => {
  const form = event.target.closest('[data-tb-form]');
  if (!form) return;
  event.preventDefault();
  const scope = text(form.dataset.tbForm);
  const input = form.querySelector('[data-tb-input]');
  barOf(scope).keyword = text(input && input.value);
  const node = barNode(form);
  if (node) paintBarParts(node, scope);
});

document.addEventListener('keydown', (event) => {
  const input = event.target.closest('[data-tb-input]');
  if (!input || event.key !== 'Enter' || imeConfirming(event)) return;
  event.preventDefault();
  const scope = text(input.dataset.tbInput);
  barOf(scope).keyword = input.value;
  const node = barNode(input);
  if (node) paintBarParts(node, scope);
});

/* ── 写入 ─────────────────────────────────────────────────────── */

async function save(key, tags, notes) {
  const body = { tags };
  if (notes) body.tagNotes = notes;
  const response = await fetch(SAVE_URL(key), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || '标签保存失败');
  }
  return response.json().catch(() => ({}));
}

function touchVocabulary(tag, delta) {
  const name = text(tag);
  if (!name) return;
  const index = state.vocabulary.findIndex((item) => text(item.name) === name);
  if (index < 0) {
    if (delta > 0) {
      state.vocabulary.push({ name, count: 1 });
      /* 新标签排查询候选最前：教练刚给某局加完 a，马上就能用 a 查到。 */
      state.recentTags = [name, ...state.recentTags.filter((item) => item !== name)];
    }
  } else {
    state.vocabulary[index].count += delta;
    if (state.vocabulary[index].count <= 0) {
      state.vocabulary.splice(index, 1);
      state.recentTags = state.recentTags.filter((item) => item !== name);
    }
  }
  state.vocabulary.sort((a, b) => (b.count - a.count) || text(a.name).localeCompare(text(b.name)));
}

async function apply(key, next, nextNotes) {
  const before = tagsOf(key);
  try {
    await save(key, next, nextNotes);
    state.byMatch[key] = next;
    if (nextNotes) state.notes[key] = nextNotes;
    before.filter((tag) => !next.includes(tag)).forEach((tag) => touchVocabulary(tag, -1));
    next.filter((tag) => !before.includes(tag)).forEach((tag) => touchVocabulary(tag, 1));
    repaint(key);
    document.dispatchEvent(new CustomEvent('match-tags:change', { detail: { key, tags: next } }));
  } catch (error) {
    window.alert(error.message || '标签保存失败');
  }
}

function addTag(key, raw) {
  const name = text(raw).slice(0, state.maxLength);
  if (!name) return;
  const current = tagsOf(key);
  if (current.includes(name)) {
    state.openKey = null;
    state.draft = '';
    repaint(key);
    return;
  }
  if (current.length >= state.limit) {
    window.alert(`一局最多 ${state.limit} 个标签`);
    return;
  }
  state.openKey = null;
  state.draft = '';
  apply(key, current.concat(name));
}

function removeTag(key, name) {
  const next = tagsOf(key).filter((tag) => tag !== name);
  const notes = { ...notesOf(key) };
  delete notes[name];
  apply(key, next, notes);
}

/* 备注只改关联记录，不新增/删除标签。 */
async function saveNote(key, name, note) {
  const notes = { ...notesOf(key) };
  if (note) notes[name] = note;
  else delete notes[name];
  state.noteEditor = null;
  try {
    await save(key, tagsOf(key), notes);
    state.notes[key] = notes;
    repaint(key);
    repaintBars();
    document.dispatchEvent(new CustomEvent('match-tags:change', { detail: { key, tags: tagsOf(key) } }));
  } catch (error) {
    window.alert(error.message || '备注保存失败');
  }
}

async function postTagAction(path, body) {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || '标签操作失败');
  }
  return response.json().catch(() => ({}));
}

async function renameTag(oldName) {
  const newName = text(window.prompt(`把标签「${oldName}」改成：`, oldName)).slice(0, state.maxLength);
  if (!newName || newName === oldName) return;
  try {
    await postTagAction('/api/v3/tags/rename', { from: oldName, to: newName });
    const index = state.vocabulary.findIndex((item) => text(item.name) === oldName);
    if (index >= 0) state.vocabulary[index].name = newName;
    state.recentTags = state.recentTags.map((item) => item === oldName ? newName : item);
    Object.keys(state.byMatch).forEach((key) => {
      state.byMatch[key] = state.byMatch[key].map((tag) => tag === oldName ? newName : tag);
      if (state.notes[key] && state.notes[key][oldName]) {
        state.notes[key][newName] = state.notes[key][oldName];
        delete state.notes[key][oldName];
      }
    });
    Object.keys(barState).forEach((scope) => {
      barState[scope].tags = barState[scope].tags.map((tag) => tag === oldName ? newName : tag);
    });
    repaintBars();
    document.dispatchEvent(new CustomEvent('match-tags:change', { detail: {} }));
  } catch (error) {
    window.alert(error.message || '重命名失败');
  }
}

async function deleteTag(name) {
  if (!window.confirm(`删除标签「${name}」？所有对局上的这个标签和备注都会被移除。`)) return;
  try {
    await postTagAction('/api/v3/tags/delete', { name });
    state.vocabulary = state.vocabulary.filter((item) => text(item.name) !== name);
    state.recentTags = state.recentTags.filter((item) => item !== name);
    Object.keys(state.byMatch).forEach((key) => {
      state.byMatch[key] = state.byMatch[key].filter((tag) => tag !== name);
      if (state.notes[key]) delete state.notes[key][name];
    });
    Object.keys(barState).forEach((scope) => {
      barState[scope].tags = barState[scope].tags.filter((tag) => tag !== name);
    });
    repaintBars();
    document.dispatchEvent(new CustomEvent('match-tags:change', { detail: {} }));
  } catch (error) {
    window.alert(error.message || '删除失败');
  }
}

/* ── 事件 ─────────────────────────────────────────────────────── */

document.addEventListener('click', (event) => {
  const noteBtn = event.target.closest('[data-tag-note]');
  if (noteBtn) {
    event.preventDefault();
    const key = text(noteBtn.dataset.tagNote);
    const name = text(noteBtn.dataset.tagName);
    const editing = state.noteEditor && state.noteEditor.key === key && state.noteEditor.tag === name;
    state.noteEditor = editing ? null : { key, tag: name };
    repaint(key);
    return;
  }
  const noteSave = event.target.closest('[data-tagnote-save]');
  if (noteSave) {
    event.preventDefault();
    const key = text(noteSave.dataset.tagnoteSave);
    const name = text(noteSave.dataset.tagName);
    const node = noteSave.closest('.tagchip');
    const input = node && node.querySelector('[data-tagnote-input]');
    saveNote(key, name, text(input && input.value));
    return;
  }
  const add = event.target.closest('[data-tag-add]');
  if (add) {
    event.preventDefault();
    const key = text(add.dataset.tagAdd);
    state.openKey = state.openKey === key ? null : key;
    state.draft = '';
    repaint(key);
    return;
  }
  const pick = event.target.closest('[data-tag-pick]');
  if (pick) {
    event.preventDefault();
    addTag(text(pick.dataset.tagPick), pick.dataset.tagName);
    return;
  }
  const remove = event.target.closest('[data-tag-remove]');
  if (remove) {
    event.preventDefault();
    removeTag(text(remove.dataset.tagRemove), text(remove.dataset.tagName));
    return;
  }
  /* 点到别处：收起还没提交的输入框。 */
  if (state.openKey && !event.target.closest('.tagpick-wrap')) {
    const key = state.openKey;
    state.openKey = null;
    state.draft = '';
    repaint(key);
  }
});

document.addEventListener('input', (event) => {
  const input = event.target.closest('[data-tag-input]');
  if (!input) return;
  state.draft = input.value;
  const key = text(input.dataset.tagInput);
  const node = document.querySelector(`.tagrow[data-tag-key="${CSS.escape(key)}"]`);
  if (!node) return;
  /* 只重画推荐列表，别把正在输入的 input 换掉，否则光标会丢。 */
  const wrap = node.querySelector('.tagpick-wrap');
  if (!wrap) return;
  const holder = node.querySelector('.tagpick-list');
  const pool = suggestions(state.draft);
  const shown = pool.slice(0, SHOW_LIMIT);
  const rest = pool.length - shown.length;
  const html = shown.map((name) => `<button type="button" class="tagpick" data-tag-pick="${esc(key)}"
      data-tag-name="${esc(name)}">${esc(name)}</button>`).join('')
    + (rest > 0 ? `<button type="button" class="tagpick tagpick-more" data-tag-more="${esc(key)}">更多 ${rest} 个</button>` : '');
  if (holder) {
    holder.innerHTML = html;
  } else if (html) {
    wrap.insertAdjacentHTML('beforeend', `<span class="tagpick-list">${html}</span>`);
  }
});

document.addEventListener('keydown', (event) => {
  const input = event.target.closest('[data-tag-input]');
  if (!input) return;
  const key = text(input.dataset.tagInput);
  if (event.key === 'Enter') {
    event.preventDefault();
    /* 等中文候选词上屏再保存：否则 addTag 读到的是拼音，甚至空串直接 return。 */
    if (imeConfirming(event)) return;
    addTag(key, input.value);
  } else if (event.key === 'Escape') {
    /* 选字中途按 Esc 是取消候选，不是收起整个输入框。 */
    if (imeConfirming(event)) return;
    event.preventDefault();
    state.openKey = null;
    state.draft = '';
    repaint(key);
  }
});

document.addEventListener('keydown', (event) => {
  const input = event.target.closest('[data-tagnote-input]');
  if (!input) return;
  if (event.key === 'Enter' && !imeConfirming(event)) {
    event.preventDefault();
    saveNote(text(input.dataset.tagnoteInput), text(input.dataset.tagName), text(input.value));
  } else if (event.key === 'Escape' && !imeConfirming(event)) {
    event.preventDefault();
    const key = text(input.dataset.tagnoteInput);
    state.noteEditor = null;
    repaint(key);
  }
});

/* 展开「更多」：把全部候选一次性铺出来（不再折叠）。 */
document.addEventListener('click', (event) => {
  const more = event.target.closest('[data-tag-more]');
  if (!more) return;
  event.preventDefault();
  const key = text(more.dataset.tagMore);
  const node = document.querySelector(`.tagrow[data-tag-key="${CSS.escape(key)}"]`);
  const holder = node && node.querySelector('.tagpick-list');
  if (!holder) return;
  const pool = suggestions(state.draft);
  holder.innerHTML = pool.map((name) => `<button type="button" class="tagpick" data-tag-pick="${esc(key)}"
      data-tag-name="${esc(name)}">${esc(name)}</button>`).join('');
});

/* ── 自动挂载 ─────────────────────────────────────────────────── */

function watch(root) {
  if (!root || typeof MutationObserver === 'undefined') return;
  const run = () => {
    ensureLoaded().then(() => mount(root));
  };
  const observer = new MutationObserver(() => {
    if (root.querySelector('.tagrow:not([data-tag-ready]), [data-tag-strip]:not([data-tag-strip-ready]), [data-tagquery]:not([data-tagquery-ready]), [data-tagbar]:not([data-tagbar-ready])')) run();
  });
  observer.observe(root, { childList: true, subtree: true });
  run();
}

if (typeof document !== 'undefined') {
  const start = () => {
    const content = document.querySelector('#content');
    if (content) watch(content);
    else window.requestAnimationFrame(start);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}

export { ensureLoaded };
