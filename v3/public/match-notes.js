/* 赛后笔记组件（挂在单局上，也可独立成 #match-notes 页）
 *
 * 导出：
 *   matchNotesHtml(matchKey, notes)  —— 渲染用的 HTML 片段（ lead 在单局页innerHTML 里插入）
 *   init(container, matchKey)        —— 给已插入的容器绑事件并拉取该局笔记
 *   matchNotesPageHtml()             —— 独立页骨架（列出所有局的笔记，给笔记日历留扩展位）
 *   initMatchNotesPage(container)    —— 绑定独立页
 *   autoMountMatchNotes(root)        —— 可选自动挂载（带 data-match-notes / data-match-notes-page 的容器）
 *
 * 后端：GET/POST /api/studio/notes（data/match_notes.json）。
 * 所有用户文本一律 esc() 后再进模板；笔记正文带 < > & 也不会变成标签。
 */
import { glyph } from './ui-icons.js';

const NOTES_API = '/api/studio/notes';
const DEFAULT_TAGS = ['BP失误', '状态差', '配合问题', '节奏断点', '沟通不足'];
const MAX_BODY = 4000;
const MAX_TAGS = 8;
const MAX_TAG_LEN = 16;

export function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}
const text = (value) => String(value == null ? '' : value).trim();
const imeConfirming = (event) => event.isComposing === true || event.keyCode === 229;

const state = {
  byMatch: new Map(),   // matchKey -> notes[]
  bound: new WeakMap(), // container -> handle
  pageReady: new WeakSet(),
  editor: null,
  statusTimer: 0,
  lastAction: '',   // 最近一次成功动作，给独立页状态条加"笔记已保存 · "前缀
};

async function api(path, { method = 'GET', body } = {}) {
  const init = { method, cache: 'no-store' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch { /* 非 JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : '笔记接口暂时读不到，请稍后重试。');
  }
  try { return await response.json(); }
  catch { throw new Error('笔记接口返回的不是 JSON，请确认打开的是赛训工作台。'); }
}

function normalize(raw) {
  const item = raw && typeof raw === 'object' ? raw : {};
  return {
    id: text(item.id),
    matchKey: text(item.matchKey),
    body: String(item.body ?? ''),
    tags: Array.isArray(item.tags) ? item.tags.map((tag) => text(tag)).filter(Boolean).slice(0, MAX_TAGS) : [],
    author: text(item.author),
    createdAt: item.createdAt || '',
    updatedAt: item.updatedAt || '',
  };
}

function when(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    // 后端 time.time() 是秒；new Date 需要毫秒，这里补一次单位换算。
    const date = new Date(value < 1e12 ? value * 1000 : value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  const stamp = text(value);
  if (!stamp) return '';
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return stamp.slice(0, 16);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/* ── 渲染 ─────────────────────────────────────────────────────── */

function notesInnerHtml(key, notes) {
  if (!notes.length) return `<div class="mn-empty mn-empty--clear" aria-label="这一局还没有笔记">
      <span class="mn-empty-icon" aria-hidden="true">${glyph('book', { size: 24 })}</span>
      <span><b>这一局还没有笔记</b><small>从页面上方的新增入口选择这一局，补上第一条赛后观察。</small></span>
    </div>`;
  return notes.map((note) => `<article class="mn-note" data-mn-note-id="${esc(note.id)}">
      <p class="mn-body">${esc(note.body).replace(/\n/g, '<br>')}</p>
      ${note.tags.length ? `<div class="mn-tags">${note.tags.map((tag) => `<span class="mn-tag">${esc(tag)}</span>`).join('')}</div>` : ''}
      <div class="mn-note-actions">
        <button type="button" class="mn-edit mn-note-action" data-mn-edit="${esc(key)}" data-mn-id="${esc(note.id)}"
          aria-label="编辑笔记" title="编辑笔记">${glyph('edit', { size: 18 })} 编辑</button>
        <button type="button" class="mn-del mn-note-action" data-mn-del="${esc(key)}" data-mn-id="${esc(note.id)}"
          aria-label="删除笔记" title="删除笔记">${glyph('trash', { size: 18 })} 删除</button>
        <span class="mn-meta">${esc(when(note.updatedAt || note.createdAt))}${note.author ? ` · ${esc(note.author)}` : ''}</span>
      </div>
    </article>`).join('');
}

/** 嵌入单局复盘页：lead 把返回值插进容器，再对本容器调用 init(container, matchKey)。 */
export function matchNotesHtml(matchKey, notes = []) {
  const key = text(matchKey);
  const list = (Array.isArray(notes) ? notes : []).map(normalize);
  return `<section class="mn-embed" data-match-notes data-match-key="${esc(key)}">
    <div class="mn-head">
      <span><span class="mn-kicker">赛后笔记</span><span class="mn-count">${list.length} 条</span></span>
      <button type="button" class="mn-add mn-add--large" data-mn-add="${esc(key)}">${glyph('edit', { size: 18 })} 写笔记</button>
    </div>
    <div class="mn-list" data-mn-list>${notesInnerHtml(key, list)}</div>
    <p class="mn-status" role="status" aria-live="polite" data-mn-status></p>
  </section>`;
}

/** 独立页：应用标准页壳 + 按对局分组的笔记列表。分组头显示 日期 · 对阵（可点进复盘）。 */
export function matchNotesPageHtml() {
  return `<div class="page feature-page mn-pagev2">
    <header class="page-intro mn-page-intro"><div><h1>${glyph('book', { label: '赛后笔记', size: 20 })} 赛后笔记</h1></div>
      <div class="intro-actions"><button type="button" class="primary" data-mn-page-add>${glyph('edit', { size: 18 })} 新增笔记</button></div></header>
    <div class="mn-page-list" data-mn-page-list></div>
    <p class="mn-status" role="status" aria-live="polite" data-mn-page-status></p>
  </div>`;
}

function say(node, message, kind = '') {
  if (!node) return;
  const iconName = kind === 'ok' ? 'pick' : kind === 'error' ? 'warning' : '';
  // role=status 留在节点上；只替换内容，保留无障碍语义。
  node.innerHTML = iconName
    ? `${glyph(iconName, { size: 14 })} <span>${esc(message)}</span>`
    : esc(message);
  node.className = `mn-status${kind ? ` is-${kind}` : ''}`;
  // 关键：不要重建节点，role=status 的节点保持同一个才能被读屏稳定播报。
}
function sayEmbeds(key, message, kind = 'ok') {
  document.querySelectorAll(`[data-match-notes][data-match-key="${CSS.escape(key)}"]`).forEach((embed) => {
    say(embed.querySelector('[data-mn-status]'), message, kind);
  });
}
/** 删除确认：复用白金 dialog，取代 window.confirm；Esc / 焦点归还交给原生 dialog。 */
function confirmDelete(note) {
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'mn-dialog mn-confirm';
    dialog.setAttribute('aria-labelledby', 'mn-confirm-title');
    const full = text(note.body);
    const digest = full.replace(/\s+/g, ' ').slice(0, 60);
    dialog.innerHTML = `<div class="mn-head"><h2 id="mn-confirm-title">${glyph('warning', { size: 16 })} 删除这条笔记？</h2></div>
      <p class="mn-confirm-summary">${esc(digest)}${full.length > 60 ? '…' : ''}</p>
      <form method="dialog" class="mn-dialog-actions">
        <button value="cancel" class="oe-btn" autofocus>取消</button>
        <button value="delete" class="oe-btn oe-btn-danger" data-mn-confirm-del>${glyph('trash', { size: 18 })} 删除笔记</button>
      </form>`;
    document.body.append(dialog);
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      resolve(ok);
      if (dialog.isConnected) dialog.close();
      dialog.remove();
    };
    dialog.addEventListener('close', () => finish(false));   // Esc / 取消视为不删除
    dialog.addEventListener('click', (event) => {
      if (event.target.closest('[data-mn-confirm-del]')) finish(true);
    });
    dialog.showModal();
  });
}

function repaint(key) {
  const notes = state.byMatch.get(key) || [];
  document.querySelectorAll(`[data-match-notes][data-match-key="${CSS.escape(key)}"]`).forEach((embed) => {
    const list = embed.querySelector('[data-mn-list]');
    if (list) list.innerHTML = notesInnerHtml(key, notes);
    const count = embed.querySelector('.mn-count');
    if (count) count.textContent = `${notes.length} 条`;
    embed.dataset.mnReady = '1';
    if (!state.bound.has(embed)) bindEmbed(embed, key);
  });
}

/* ── 编辑弹窗（原生 dialog） ─────────────────────────────────── */

function dateOptionsHtml(index) {
  const counts = new Map();
  index.forEach((match) => {
    const date = String(match?.date || '').slice(0, 10);
    if (date) counts.set(date, (counts.get(date) || 0) + 1);
  });
  const dates = [...counts.keys()].sort((a, b) => b.localeCompare(a));
  return `<option value="">选择日期</option>${dates.map((date) =>
    `<option value="${esc(date)}">${esc(date)}（${counts.get(date)} 局）</option>`).join('')}`;
}

function gameOptionsHtml(index, date) {
  const games = [...index.values()]
    .filter((match) => match && String(match.date || '').slice(0, 10) === date)
    .sort((a, b) => String(b.startTime || '').localeCompare(String(a.startTime || '')));
  if (!games.length) return '<option value="">这一天暂无对局</option>';
  return `<option value="">选择这一天的对局</option>` + games.map((match, index) => {
    const clock = String(match.startTime || '').slice(11, 16) || '时间未标注';
    const rival = match.opponent ? `对阵 ${match.opponent}` : '对手未标注';
    const result = match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '';
    /* 选项里不暴露 channel-xxx：同一天同对手用序号区分，教练能认出来。 */
    return `<option value="${esc(match.key)}">第 ${index + 1} 局 · ${esc(clock)} · ${esc(rival)}${result ? ` · ${result}` : ''}</option>`;
  }).join('');
}

function chipsHtml(tags, askKey, index, body, editing) {
  const pick = askKey ? `<div class="mn-pick">
      <div class="mn-step"><span class="mn-step-no" aria-hidden="true">1</span><div class="oe-field"><label for="mn-date">先选日期</label>
        <select id="mn-date" data-mn-date required aria-invalid="false">${dateOptionsHtml(index)}</select></div></div>
      <div class="mn-step"><span class="mn-step-no" aria-hidden="true">2</span><div class="oe-field"><label for="mn-game">再选这一天的对局</label>
        <select id="mn-game" data-mn-game required aria-invalid="false"><option value="">先选日期</option></select></div></div>
    </div>
    ${index.size ? '' : '<p class="mn-hint">对局列表暂时读不到，请刷新后重试。</p>'}
    ${index.size ? '' : `<div class="oe-field"><label for="mn-key">对局编号（列表读取失败时可手动填写）</label>
      <input type="text" id="mn-key" data-mn-key-input maxlength="160" placeholder="channel-xxxxxxxx"></div>`}` : '';
  return `<div class="mn-head"><div class="mn-head-title"><h2 id="mn-editor-title">${glyph('book', { size: 18 })} ${editing ? '编辑赛后笔记' : '写赛后笔记'}</h2>
      <p class="mn-sub">${askKey ? '先选日期和对局，再写正文、加标签。' : '把问题和下一次的调整写清楚。'}</p></div></div>
    ${pick}
    <div class="mn-step"><span class="mn-step-no" aria-hidden="true">${askKey ? '3' : '1'}</span><div class="oe-field"><label for="mn-body">笔记正文</label>
      <textarea id="mn-body" data-mn-body maxlength="${MAX_BODY}" required aria-invalid="false"
        placeholder="这局哪里出了问题，下一场怎么调…">${esc(body)}</textarea></div></div>
    <div class="mn-step"><span class="mn-step-no" aria-hidden="true">${askKey ? '4' : '2'}</span><div class="oe-field"><label for="mn-tag-input">标签（回车添加，可自由增删）</label>
      <div class="mn-tags" data-mn-chips>${tags.map((tag) => `<span class="mn-tag">${esc(tag)}
        <button type="button" class="mn-tag-x" data-mn-tag-remove="${esc(tag)}" aria-label="移除标签 ${esc(tag)}">×</button></span>`).join('')}</div>
      <div class="oe-pair"><input type="text" id="mn-tag-input" class="mn-tag-input" data-mn-tag-input
        maxlength="${MAX_TAG_LEN}" list="mn-tag-options" autocomplete="off" spellcheck="false"
        placeholder="${DEFAULT_TAGS.slice(0, 3).map(esc).join(' / ')}">
        <datalist id="mn-tag-options">${DEFAULT_TAGS.map((tag) => `<option value="${esc(tag)}"></option>`).join('')}</datalist>
        <button type="button" class="mn-tagadd" data-mn-tag-add>${glyph('edit', { size: 18 })} 添加标签</button></div></div></div>
    <p class="oe-err" id="mn-editor-error" role="alert" data-mn-editor-error></p>`;
}

function closeEditor() {
  if (!state.editor) return;
  const { dialog, onClose } = state.editor;
  state.editor = null;
  if (onClose) onClose();
  if (dialog.isConnected) dialog.close();
  dialog.remove();
}

/** 打开（或重建）笔记表单；askKey 用于独立页新增，先选日期再选对局。 */
let editorToken = 0;
async function openEditor({ key = '', note = null, askKey = false, onSaved } = {}) {
  closeEditor();
  const token = ++editorToken;
  /* 独立页新增要先拿到对局目录，才能按日期列对局；目录只拉一次并缓存。 */
  const index = askKey ? await matchIndex() : new Map();
  if (token !== editorToken) return;
  const current = note ? normalize(note) : null;
  const editorState = { key, body: current?.body || '', tags: current ? current.tags.slice() : [] };
  const dialog = document.createElement('dialog');
  dialog.className = 'mn-dialog';
  dialog.setAttribute('aria-labelledby', 'mn-editor-title');
  dialog.innerHTML = `${chipsHtml(editorState.tags, askKey, index, editorState.body, Boolean(current))}
    <form method="dialog" class="mn-dialog-actions">
      <button value="cancel" class="oe-btn" formnovalidate>取消</button>
      <button type="button" class="oe-btn oe-btn-primary" data-mn-save>保存笔记</button>
    </form>`;
  document.body.append(dialog);

  const errorNode = dialog.querySelector('[data-mn-editor-error]');
  const bodyInput = dialog.querySelector('[data-mn-body]');
  const tagInput = dialog.querySelector('[data-mn-tag-input]');
  const chips = dialog.querySelector('[data-mn-chips]');
  const dateSelect = dialog.querySelector('[data-mn-date]');
  const gameSelect = dialog.querySelector('[data-mn-game]');
  /** 错误行：warning 图标 + "错误："文字前缀（不只靠红色）；保存中走 spinner + 文字双通道。 */
  /* :user-invalid 只是视觉状态，aria-invalid 由脚本同步给读屏；清空错误时一并复位。 */
  const markInvalid = (node, invalid) => node?.setAttribute('aria-invalid', invalid ? 'true' : 'false');
  const clearErrors = () => {
    setError('');
    [dateSelect, gameSelect, bodyInput].forEach((node) => markInvalid(node, false));
  };
  const fail = (message, node) => {
    setError(message);
    markInvalid(node, true);
    node?.focus();
  };
  const setError = (message, { busy = false } = {}) => {
    if (!message) { errorNode.textContent = ''; return; }
    errorNode.innerHTML = busy
      ? `<span class="mn-spin" aria-hidden="true"></span><span>${esc(message)}</span>`
      : `${glyph('warning', { size: 14 })} <span>错误：${esc(message)}</span>`;
  };

  const drawChips = () => {
    chips.innerHTML = editorState.tags.map((tag) => `<span class="mn-tag">${esc(tag)}
      <button type="button" class="mn-tag-x" data-mn-tag-remove="${esc(tag)}" aria-label="移除标签 ${esc(tag)}">×</button></span>`).join('');
  };
  const addTag = () => {
    const tag = text(tagInput.value).slice(0, MAX_TAG_LEN);
    if (!tag) return;
    if (editorState.tags.includes(tag)) { tagInput.value = ''; return; }
    if (editorState.tags.length >= MAX_TAGS) {
      setError(`最多 ${MAX_TAGS} 个标签，请先移除一个。`);
      return;
    }
    setError('');
    editorState.tags.push(tag);
    tagInput.value = '';
    drawChips();
    tagInput.focus();
  };

  dialog.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-mn-tag-remove]');
    if (remove) {
      event.preventDefault();
      editorState.tags = editorState.tags.filter((tag) => tag !== remove.dataset.mnTagRemove);
      setError('');
      drawChips();
      return;
    }
    if (event.target.closest('[data-mn-tag-add]')) { addTag(); return; }
    if (event.target.closest('[data-mn-save]')) {
      const finalKey = text(gameSelect?.value || dialog.querySelector('[data-mn-key-input]')?.value || key);
      const body = String(bodyInput.value || '').trim();
      clearErrors();
      if (askKey && dateSelect && !dateSelect.value) { fail('请先选择日期。', dateSelect); return; }
      if (askKey && gameSelect && !gameSelect.value) { fail('请选择这一天的对局。', gameSelect); return; }
      if (!finalKey) { setError('请选择要写笔记的对局。'); return; }
      if (!body) { fail('笔记正文不能为空。', bodyInput); return; }
      const button = dialog.querySelector('[data-mn-save]');
      const saveLabel = button.textContent;
      button.disabled = true;
      button.textContent = '保存中…';
      setError('正在保存…', { busy: true });
      const payload = { matchKey: finalKey, body, tags: editorState.tags, author: '' };
      if (current?.id) payload.id = current.id;
      api(NOTES_API, { method: 'POST', body: payload }).then((data) => {
        const notes = (data?.notes || []).map(normalize);
        state.byMatch.set(finalKey, notes);
        state.lastAction = '笔记已保存';
        repaint(finalKey);
        sayEmbeds(finalKey, '笔记已保存。');
        refreshPage();
        closeEditor();
        if (onSaved) onSaved(finalKey);
      }).catch((error) => {
        setError(error?.message || '保存失败，请稍后重试。');
        button.textContent = saveLabel;
        button.disabled = false;
      });
    }
  });
  dialog.addEventListener('change', (event) => {
    if (event.target !== dateSelect || !gameSelect) return;
    gameSelect.innerHTML = dateSelect.value ? gameOptionsHtml(index, dateSelect.value) : '<option value="">先选日期</option>';
    markInvalid(gameSelect, false);
    clearErrors();
  });
  dialog.addEventListener('input', (event) => {
    if (event.target === dateSelect || event.target === gameSelect || event.target === bodyInput) clearErrors();
  });
  dialog.addEventListener('keydown', (event) => {
    if (event.target !== tagInput || event.key !== 'Enter') return;
    event.preventDefault();
    if (imeConfirming(event)) return; // 中文输入法选词时不要误加标签
    addTag();
  });
  dialog.addEventListener('close', () => {
    if (state.editor?.dialog === dialog) state.editor = null;
    dialog.remove();
  });

  state.editor = { dialog, onClose: null };
  dialog.showModal();
  (askKey ? (dateSelect && !index.size ? dialog.querySelector('[data-mn-key-input]') : dateSelect) : bodyInput)?.focus();
}

/* ── 嵌入组件 ─────────────────────────────────────────────────── */

function bindEmbed(container, key, force = false) {
  if (!force && state.bound.has(container)) return state.bound.get(container);
  const handle = {
    key,
    container,
    reload: () => loadMatch(key),
    openEditor: () => openEditor({ key, onSaved: () => sayEmbeds(key, '笔记已保存。') }),
  };
  state.bound.set(container, handle);
  container.addEventListener('click', (event) => {
    const add = event.target.closest('[data-mn-add]');
    if (add) { openEditor({ key: add.dataset.mnAdd }); return; }
    const edit = event.target.closest('[data-mn-edit]');
    if (edit) {
      const matchKey = edit.dataset.mnEdit;
      const note = (state.byMatch.get(matchKey) || []).find((item) => item.id === edit.dataset.mnId);
      if (note) openEditor({ key: matchKey, note });
      return;
    }
    const del = event.target.closest('[data-mn-del]');
    if (del) {
      const matchKey = del.dataset.mnDel;
      const note = (state.byMatch.get(matchKey) || []).find((item) => item.id === del.dataset.mnId);
      if (!note) return;
      confirmDelete(note).then((ok) => {
        if (!ok) return;
        api(NOTES_API, { method: 'POST', body: { matchKey, id: note.id, delete: true } })
          .then((data) => {
            state.byMatch.set(matchKey, (data?.notes || []).map(normalize));
            state.lastAction = '笔记已删除';
            repaint(matchKey);
            sayEmbeds(matchKey, '笔记已删除。');
            refreshPage();
          })
          .catch((error) => say(container.querySelector('[data-mn-status]'), error?.message, 'error'));
      });
    }
  });
  return handle;
}

async function loadMatch(key) {
  try {
    const data = await api(`${NOTES_API}?match_key=${encodeURIComponent(key)}`);
    state.byMatch.set(key, (data?.notes || []).map(normalize));
    repaint(key);
  } catch (error) {
    document.querySelectorAll(`[data-match-notes][data-match-key="${CSS.escape(key)}"]`).forEach((node) => {
      say(node.querySelector('[data-mn-status]'), error?.message, 'error');
    });
  }
}

/** lead 的接线示例：
 *    import { matchNotesHtml, init } from './match-notes.js';
 *    html += matchNotesHtml(m.matchKey, []);
 *    // 渲染后：init(content.querySelector('.mn-embed'), m.matchKey);
 */
export function init(container, matchKey) {
  if (!container) return null;
  const key = text(matchKey || container.dataset?.matchKey || '');
  if (!key) return null;
  const existing = state.bound.get(container);
  // 同一个容器可能被路由复用后换了 matchKey 或重建了内部 DOM，此时要重新绑定。
  if (existing && existing.key === key && container.querySelector('[data-mn-list]')) return existing;
  if (!container.querySelector('[data-mn-list]')) container.innerHTML = matchNotesHtml(key, state.byMatch.get(key) || []);
  container.classList.add('mn-embed');
  container.dataset.matchNotes = '';
  container.dataset.matchKey = key;
  bindEmbed(container, key, true);
  loadMatch(key);
  return state.bound.get(container);
}

/* ── 独立页 ───────────────────────────────────────────────────── */

function refreshPage() {
  document.querySelectorAll('[data-match-notes-page]').forEach((page) => {
    if (state.pageReady.has(page)) loadPage(page);
  });
}

/* 对局索引：matchKey → 日期 / 对手 / 赛制。一次拉全量列表，分组头据此显示
   「11-02 · 对阵 星轨战队」而不是裸 channel-xxx；拉不到就退回 key 兜底。 */
let matchIndexPromise = null;
function matchIndex() {
  if (!matchIndexPromise) {
    matchIndexPromise = api('/api/matches')
      .then((data) => new Map((data?.matches || []).map((m) => [m.key, m])))
      .catch(() => new Map());
  }
  return matchIndexPromise;
}

async function loadPage(page) {
  const list = page.querySelector('[data-mn-page-list]');
  const status = page.querySelector('[data-mn-page-status]');
  try {
    const [data, index] = await Promise.all([api(NOTES_API), matchIndex()]);
    const byMatch = data?.byMatch || {};
    Object.entries(byMatch).forEach(([key, notes]) => state.byMatch.set(key, notes.map(normalize)));
    const keys = Object.keys(byMatch).sort((a, b) => {
      const da = String(index.get(a)?.date || ''), db = String(index.get(b)?.date || '');
      return db.localeCompare(da) || a.localeCompare(b);
    });
    const groupHead = (key, notes) => {
      const m = index.get(key);
      const day = String(m?.date || '');
      const label = [day.slice(5), m?.opponent ? `对阵 ${m.opponent}` : '对手未标注'].filter(Boolean).join(' · ') || '未标注对局';
      /* 分组头只放教练看得懂的日期/对手/赛制，不再把 channel-xxx 当副标题。 */
      const detail = [m?.matchType === 'formal' ? '正式赛' : '训练赛',
        String(m?.startTime || '').slice(11, 16) || '',
        m?.session ? `训练组 ${m.session}` : ''].filter(Boolean).join(' · ');
      return `<a class="mn-group-main" href="#match/${encodeURIComponent(key)}" title="打开这一局的复盘：${esc(label)}">
          <b>${esc(label)}</b><small>${esc(detail)}</small></a>
        <span class="mn-count">${notes.length} 条</span>`;
    };
    list.innerHTML = keys.length
      ? keys.map((key) => `<article class="mn-group" data-match-notes data-match-key="${esc(key)}">
          <div class="mn-group-head">${groupHead(key, byMatch[key])}</div>
          <div class="mn-list" data-mn-list>${notesInnerHtml(key, byMatch[key])}</div>
        </article>`).join('')
      : `<div class="mn-empty mn-empty-cta">${glyph('book', { label: '赛后笔记', size: 20 })}
          <span>还没有赛后笔记</span><small>点击右上角「新增笔记」选择对局，写下第一条观察。</small>
        </div>`;
    // 分组容器就是 embed：绑一次事件，后续增删改由 repaint / loadPage 原地刷新。
    list.querySelectorAll('.mn-group').forEach((group) => {
      group.dataset.mnReady = '1';
      bindEmbed(group, group.dataset.matchKey);
    });
    const prefix = state.lastAction ? `${state.lastAction} · ` : '';
    state.lastAction = '';
    say(status, `${prefix}共 ${keys.length} 局有笔记。`, 'ok');
    // 从正式比赛录入页过来时带 ?match_key=...，滚动到对应组。
    const hashQuery = String(location.hash || '').split('?')[1] || '';
    const wanted = new URLSearchParams(hashQuery).get('match_key');
    if (wanted) {
      const target = [...list.querySelectorAll('.mn-group')].find((node) => node.dataset.matchKey === wanted);
      if (target) target.scrollIntoView({ block: 'center' });
    }
  } catch (error) {
    say(status, error?.message, 'error');
  }
}

export function initMatchNotesPage(container) {
  if (!container) return null;
  if (state.pageReady.has(container)) return container;
  if (!container.querySelector('[data-mn-page-list]')) container.innerHTML = matchNotesPageHtml();
  container.classList.add('mn-page');
  container.dataset.matchNotesPage = '';
  state.pageReady.add(container);
  container.addEventListener('click', (event) => {
    if (event.target.closest('[data-mn-page-add]')) openEditor({ askKey: true });
  });
  loadPage(container);
  return container;
}

/* ── 自动挂载（可选） ─────────────────────────────────────────── */

export function autoMountMatchNotes(root = document) {
  root.querySelectorAll('[data-match-notes]:not([data-mn-ready])').forEach((node) => {
    node.dataset.mnReady = '1';
    init(node, node.dataset.matchKey);
  });
  root.querySelectorAll('[data-match-notes-page]:not([data-mn-page-ready])').forEach((node) => {
    node.dataset.mnPageReady = '1';
    initMatchNotesPage(node);
  });
}

function ensureFallbackStyles() {
  if (typeof document === 'undefined') return;
  // 图标对齐规则独立于 fallback：主页面已链接 official-entry.css 时会跳过下面的兜底样式，
  // 但金色 SVG 仍需 inline-flex 对齐，所以这段始终注入（official-entry.css 不在本模块写作用域）。
  if (!document.getElementById('mn-icon-style')) {
    const iconStyle = document.createElement('style');
    iconStyle.id = 'mn-icon-style';
    iconStyle.textContent = `
      .mn-add{display:inline-flex;align-items:center;justify-content:center;gap:6px}
      .mn-head-title{min-inline-size:0}
      .mn-add .ui-glyph{flex:0 0 auto}
      /* official-entry.css 的 .oe-pair input{inline-size:62px} 会压扁标签框，这里用更高特异性覆盖。 */
      .mn-dialog .oe-pair input.mn-tag-input{inline-size:min(240px,100%);flex:1 1 160px;min-inline-size:0}
      .mn-edit,.mn-del,.mn-tagadd{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-inline-size:24px;min-block-size:24px}
      .mn-status{display:inline-flex;align-items:center;gap:6px}
      .mn-status .ui-glyph,.mn-edit .ui-glyph,.mn-del .ui-glyph{flex:0 0 auto}
      .mn-empty-cta{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
      .mn-empty-cta::before{content:none}
      .mn-dialog h2{display:inline-flex;align-items:center;gap:8px}
      .mn-dialog .oe-err{display:flex;align-items:center;gap:6px}
      .mn-confirm-summary{margin:8px 0;padding:8px 10px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:8px;background:var(--soft,#F5EBD3);font-size:13px;line-height:1.6;overflow-wrap:anywhere}
      .oe-btn-danger{border-color:var(--danger,#B5564A);background:var(--danger,#B5564A);color:#fff;font-weight:600}
      .mn-spin{display:inline-block;inline-size:13px;block-size:13px;flex:0 0 auto;border:2px solid rgba(215,176,113,.35);border:2px solid color-mix(in srgb,var(--accent,#D7B071) 35%,transparent);border-top-color:var(--accent-ink,#8A6530);border-radius:50%;animation:mn-spin .7s linear infinite}
      @keyframes mn-spin{to{rotate:360deg}}
      @media (prefers-reduced-motion: reduce){.mn-spin{animation:none}}
      .mn-empty::before{content:'';display:inline-block;inline-size:6px;block-size:6px;margin-inline-end:8px;border-radius:50%;background:var(--accent,#D7B071);vertical-align:.12em;opacity:.8}
    `;
    document.head.append(iconStyle);
  }
  if (document.getElementById('mn-fallback-style')) return;
  let loaded = '';
  try { loaded = getComputedStyle(document.documentElement).getPropertyValue('--oe-styles-loaded').trim(); }
  catch { /* 老浏览器忽略 */ }
  if (loaded === '1') return; // official-entry.css 已链接
  const style = document.createElement('style');
  style.id = 'mn-fallback-style';
  style.textContent = `
    dialog:modal{overscroll-behavior:contain}
    dialog::backdrop{overflow:hidden;overscroll-behavior:contain;background:rgba(47,43,30,.34)}
    .mn-embed,.mn-page{display:grid;gap:10px;padding:14px 16px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:12px;background:var(--paper,#FFFEFC);color:var(--text,#2F281E)}
    .mn-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .mn-kicker{color:var(--accent-ink,#8A6530);font-weight:600;font-size:13px}
    .mn-count,.mn-meta,.mn-empty{color:var(--muted,#6E6658);font-size:12px}
    .mn-list{display:grid;gap:8px}
    .mn-note{padding:10px 12px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:8px;background:var(--paper-2,var(--surface,#F3F0E9))}
    .mn-body{font-size:13px;line-height:1.7;overflow-wrap:anywhere}
    .mn-tags{display:flex;flex-wrap:wrap;gap:5px;margin-block-start:8px}
    .mn-tag{padding:2px 8px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:999px;background:var(--soft,#F5EBD3);color:var(--accent-ink,#8A6530);font-size:12px}
    .mn-note-actions{display:flex;align-items:center;gap:6px;margin-block-start:6px}
    .mn-dialog{inline-size:min(520px,calc(100vw - 32px));max-block-size:86vh;overflow:auto;padding:18px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:18px;background:var(--paper,#FFFEFC);color:var(--text,#2F281E)}
    .mn-dialog[open]{display:block}
    .mn-dialog textarea{min-block-size:150px;resize:vertical;line-height:1.6}
    .mn-dialog input{min-block-size:40px}
    .mn-dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-block-start:14px}
    .oe-btn{min-block-size:42px;padding:8px 16px;border:1px solid var(--line,rgba(150,116,49,.28));border-radius:8px;background:var(--paper,#FFFEFC);color:var(--text,#2F281E);font:inherit;cursor:pointer}
    .oe-btn-primary{border-color:var(--accent-ink,#8A6530);background:var(--accent-ink,#8A6530);color:#fff;font-weight:600}
    .oe-field{display:grid;gap:4px;margin-block-end:12px}
    .oe-err{min-block-size:18px;color:var(--danger,#B5564A);font-size:12px}
  `;
  document.head.append(style);
}

if (typeof document !== 'undefined') {
  ensureFallbackStyles();
  const start = () => {
    const content = document.querySelector('#content');
    if (!content) return;
    autoMountMatchNotes(content);
    if (typeof MutationObserver === 'undefined') return;
    const observer = new MutationObserver(() => autoMountMatchNotes(content));
    observer.observe(content, { childList: true, subtree: true });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}
