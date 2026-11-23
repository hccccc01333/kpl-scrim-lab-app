/* 三套档案模块：本队 / 对手 / 试训（2026-11，对应 docs/重构蓝图_白金画廊交互.md 3.5.1）
 *
 * 调用方式（lead 接入路由时用，本文件不碰 app.js / index.html）：
 *   import { render, createProfilesPage } from './profiles.js';
 *   const page = render(container, { esc, icon, notify, API_BASE });
 *   // 离开路由时： page.dispose();
 *   或手动持有实例： const page = createProfilesPage(ctx); page.mount(container, ctx);
 *   render(container, ctx) 对同一 container 幂等，重复调用只刷新内容、不重复绑事件。
 *
 * hash 路由名：#profiles
 * 样式：本文件自动注入 ./profiles.css（无需改 index.html）。
 * 数据：GET /api/v3/profiles、PUT /api/v3/profiles（落盘 data/profiles.json，
 *       revision 乐观锁；服务端端点见 v3/serve.py 末尾 # === profiles module ===）。
 * 英雄名录：GET /api/catalog（resources/catalog.json），头像 /catalog/icons/hero-*.png。
 *
 * 约束：原生 ES 模块 + fetch + 模板字符串；委托 addEventListener；
 *       增删改用原生 <dialog> + showModal()（不写 role=dialog / aria-modal / Esc 处理）；
 *       所有用户输入先 esc；颜色只用现有 CSS 变量。
 */
import { glyph, deco, plus } from './ui-icons.js';

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const CSS_HREF = new URL('./profiles.css', import.meta.url).href;
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const TABS = [
  { key: 'own', label: '本队' },
  { key: 'opponents', label: '对手' },
  { key: 'trials', label: '试训' },
];
/* 页签前置图标：仅映射白名单里的语义图标，不参与任何数据逻辑。 */
const TAB_GLYPH = { own: 'players', opponents: 'opponent', trials: 'clock' };
const METRICS = [
  { key: 'kda', label: 'KDA' },
  { key: 'winRate', label: '胜率' },
  { key: 'mvp', label: 'MVP' },
  { key: 'joinRate', label: '参团率' },
  { key: 'damageShare', label: '输出占比' },
];

/* 与 grade-rules.js 一致的字符级转义：模板字符串里所有用户数据都过这里。 */
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));
const text = (value) => String(value ?? '').trim();
const uid = (prefix) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
const clone = (value) => JSON.parse(JSON.stringify(value ?? null));
/** 资料记录时间：datetime-local 的挂钟时间，不带时区；只表示「这条资料是哪天记的」。 */
const nowLocal = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const dash = (value) => (text(value) === '' ? '<span class="pf-dim">—</span>' : escapeHtml(value));
const safeIcon = (url) => (/^\/catalog\/icons\/[A-Za-z0-9._/-]+$/.test(String(url || '')) ? String(url) : '');
/** 空态的淡金人物大图标（glyph 默认 aria-hidden，文字仍由调用方保留）。 */
const emptyIcon = (size = 26) => glyph('players', { size, cls: 'pf-empty-icon' });

function ensureStyles() {
  if (typeof document === 'undefined' || document.querySelector('link[data-pf-css]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS_HREF;
  link.dataset.pfCss = '1';
  document.head.appendChild(link);
}

function emptyDoc() {
  return { schema: 'profiles-v1', revision: 1, updatedAt: '', own: [], opponents: [], trials: [] };
}

function normalizeDoc(raw) {
  const out = emptyDoc();
  if (!raw || typeof raw !== 'object') return out;
  for (const key of ['own', 'opponents', 'trials']) {
    out[key] = Array.isArray(raw[key]) ? raw[key].filter((item) => item && typeof item === 'object') : [];
  }
  const revision = Number(raw.revision);
  out.revision = Number.isFinite(revision) && revision > 0 ? Math.floor(revision) : 1;
  out.updatedAt = text(raw.updatedAt);
  for (const list of [out.own, out.opponents, out.trials]) {
    for (const item of list) {
      if (!item.id) item.id = uid('import');
      if (!item.heroPowers || typeof item.heroPowers !== 'object') item.heroPowers = {};
    }
  }
  for (const trial of out.trials) {
    trial.windows = Array.isArray(trial.windows) ? trial.windows.filter((w) => w && typeof w === 'object') : [];
    for (const win of trial.windows) {
      if (!win.id) win.id = uid('win');
      if (!win.heroPowers || typeof win.heroPowers !== 'object') win.heroPowers = {};
      if (!win.metrics || typeof win.metrics !== 'object') win.metrics = {};
    }
  }
  return out;
}

function normalizeHeroes(payload) {
  const out = [];
  const seen = new Set();
  const push = (id, name, icon) => {
    const key = text(name);
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({ id: text(id) || key, name: key, icon: safeIcon(icon) });
  };
  if (payload && Array.isArray(payload.entries)) {
    for (const entry of payload.entries) {
      if (entry && entry.kind === 'hero') push(entry.id, entry.name, entry.icon);
    }
  }
  if (!out.length && payload && Array.isArray(payload.heroes)) {
    for (const name of payload.heroes) push(name, name, payload.icons?.[name]);
  }
  return out;
}

/* ── 表单控件小工具（属性值一律 esc） ─────────────────────────────── */
function textInput(id, name, value, opts = {}) {
  const attrs = [
    `id="${escapeHtml(id)}"`, `name="${escapeHtml(name)}"`,
    `value="${escapeHtml(value ?? '')}"`,
    `type="${escapeHtml(opts.type || 'text')}"`,
    opts.required ? 'required' : '',
    opts.autofocus ? 'autofocus' : '',
    opts.placeholder ? `placeholder="${escapeHtml(opts.placeholder)}"` : '',
    opts.min != null ? `min="${escapeHtml(opts.min)}"` : '',
    opts.step != null ? `step="${escapeHtml(opts.step)}"` : '',
    opts.describedBy ? `aria-describedby="${escapeHtml(opts.describedBy)}"` : '',
    `autocomplete="${escapeHtml(opts.autocomplete || 'off')}"`,
  ].filter(Boolean).join(' ');
  return `<input ${attrs}>`;
}

function selectInput(id, name, value, options, opts = {}) {
  const body = options.map((item) => {
    const val = String(item.value ?? item);
    const label = String(item.label ?? item);
    return `<option value="${escapeHtml(val)}"${val === String(value ?? '') ? ' selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
  return `<select id="${escapeHtml(id)}" name="${escapeHtml(name)}"${opts.required ? ' required' : ''}${opts.autofocus ? ' autofocus' : ''}>${body}</select>`;
}

function textareaInput(id, name, value, opts = {}) {
  return `<textarea id="${escapeHtml(id)}" name="${escapeHtml(name)}" rows="${opts.rows || 2}"${opts.placeholder ? ` placeholder="${escapeHtml(opts.placeholder)}"` : ''}>${escapeHtml(value ?? '')}</textarea>`;
}

function field(label, id, control, hintId = '') {
  // 必填星号由控件上的 required 属性统一推导，避免说明写「带 * 必填」而个别表单漏标。
  const required = /\srequired(?=[\s>])/.test(control);
  const mark = required ? ' <span class="pf-required" aria-hidden="true">*</span>' : '';
  const cleanLabel = label.replace(/\s*\*\s*$/, '');
  return `<div class="pf-field">
    <label for="${escapeHtml(id)}">${escapeHtml(cleanLabel)}${mark}</label>
    ${control}
    ${hintId ? `<p class="pf-hint" id="${escapeHtml(hintId)}">按需要填写，留空不参与对比。</p>` : ''}
  </div>`;
}

/* ── 页面实例 ─────────────────────────────────────────────────────── */
export function createProfilesPage(h = {}) {
  ensureStyles();
  // 不信任外部传入的 esc 实现：模板里的每个用户字段都过本文件的字符级转义。
  const esc = escapeHtml;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const icon = typeof h.icon === 'function' ? h.icon : (() => '');

  let root = null;
  let bound = null;
  let controller = null;
  let generation = 0;
  let disposed = false;

  const state = {
    doc: emptyDoc(),
    heroes: [],
    heroIndex: new Map(),
    heroLanes: {},
    heroLaneFilter: '',
    importQuery: '',
    tab: 'own',
    loading: true,
    saving: false,
    notice: '',
    noticeError: false,
    heroQuery: '',
    editor: null,          // { kind, id, draft, transferFromId, trialId }
    pendingConfirm: null,  // () => void
    compare: { windowKey: '', ids: [] },
  };

  /* ── 数据 ──────────────────────────────────────────────────────── */
  async function api(path, options = {}) {
    const response = await fetch(API_BASE + '/api/' + path, {
      cache: 'no-store', ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
      signal: options.signal || controller?.signal,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `请求失败（${response.status}）`);
    }
    return response.json();
  }

  function setNotice(message, isError = false) {
    state.notice = text(message);
    state.noticeError = Boolean(isError);
    paintNotice();
    if (state.notice && notify) notify(state.notice);
  }

  /** 弹窗内的校验 / 保存失败提示：写在 dialog 内部，避免被 ::backdrop 遮住。 */
  function setDialogError(message) {
    const node = root?.querySelector('[data-pf-dialog-err]');
    if (!node) { setNotice(message, true); return; }
    const msg = text(message);
    node.innerHTML = msg ? `${glyph('warning', { size: 14 })}<span>${esc(msg)}</span>` : '';
    node.hidden = !msg;
  }

  /** 刷新按钮的加载态：同步 disabled / aria-busy / 文案。 */
  function setReloadBusy(busy) {
    const btn = root?.querySelector('[data-pf-reload]');
    if (!btn) return;
    btn.disabled = busy;
    btn.setAttribute('aria-busy', String(busy));
    const label = btn.querySelector('[data-pf-reload-label]');
    if (label) label.textContent = busy ? '刷新中…' : '刷新';
  }

  async function load() {
    if (!root) return;
    const gen = ++generation;
    state.loading = true;
    paint();
    setReloadBusy(true);
    controller?.abort();
    controller = new AbortController();
    try {
      const [docPayload, catalogPayload, lanePayload] = await Promise.all([
        api('v3/profiles', { signal: controller.signal }),
        api('catalog', { signal: controller.signal }).catch(() => ({ entries: [] })),
        api('v3/lineup-tags/meta', { signal: controller.signal }).catch(() => ({ lanes: {} })),
      ]);
      if (gen !== generation || !root) return;
      state.doc = normalizeDoc(docPayload);
      state.heroes = normalizeHeroes(catalogPayload);
      state.heroIndex = new Map(state.heroes.map((hero) => [hero.id, hero]));
      state.heroLanes = lanePayload?.lanes && typeof lanePayload.lanes === 'object' ? lanePayload.lanes : {};
      setNotice('');
    } catch (error) {
      if (error.name !== 'AbortError' && gen === generation) {
        setNotice(error.message || '档案读取失败，请点「刷新」重试。', true);
      }
    } finally {
      if (gen === generation) {
        state.loading = false;
        paint();
        setReloadBusy(false);
      }
    }
  }

  async function persist(nextDoc) {
    state.saving = true;
    paint();
    try {
      const saved = await api('v3/profiles', {
        method: 'PUT',
        body: JSON.stringify({ revision: state.doc.revision, ...nextDoc }),
      });
      state.doc = normalizeDoc(saved);
      setNotice('已保存。');
      return true;
    } catch (error) {
      const message = text(error.message);
      const detail = (message.includes('409') || message.includes('已被其他人更新'))
        ? '档案已被其他人更新，请点「刷新」后再改。'
        : (message || '保存失败，请重试。');
      // 编辑器仍打开时提示必须落在 dialog 内，否则被遮罩挡住；关闭后的状态才走页头 notice。
      if (state.editor) setDialogError(detail);
      else setNotice(detail, true);
      return false;
    } finally {
      state.saving = false;
      paint();
    }
  }

  /* ── 展示用小工具 ──────────────────────────────────────────────── */
  function heroById(id) { return state.heroIndex.get(String(id)) || null; }

  function heroChip(id, power, index) {
    const hero = heroById(id);
    const src = hero ? safeIcon(hero.icon) : '';
    return `<span class="pf-hero-chip">
      ${src ? `<img src="${esc(src)}" alt="" width="26" height="26" loading="lazy">` : `<span class="pf-hero-initial">${esc((hero?.name || String(id)).slice(0, 1))}</span>`}
      <span class="pf-hero-chip-name">${esc(hero?.name || id)}</span>
      <label class="pf-visually-hidden" for="pf-power-${index}">战力</label>
      <input id="pf-power-${index}" type="number" min="0" step="1" inputmode="numeric"
             data-pf-hero-power="${esc(id)}" value="${esc(power ?? '')}" aria-label="${esc(hero?.name || id)} 战力">
      <button type="button" class="pf-icon-btn" data-pf-hero-remove="${esc(id)}" aria-label="移除 ${esc(hero?.name || id)}">${glyph('ban', { size: 14 })}</button>
    </span>`;
  }

  function heroOption(hero, selected) {
    return `<button type="button" class="pf-hero-option${selected ? ' is-selected' : ''}"
        data-pf-hero-toggle="${esc(hero.id)}" aria-pressed="${selected}">
      ${hero.icon ? `<img src="${esc(hero.icon)}" alt="" width="34" height="34" loading="lazy">` : `<span class="pf-hero-initial">${esc(hero.name.slice(0, 1))}</span>`}
      <span>${esc(hero.name)}</span>
    </button>`;
  }

  function heroPowersCell(powers) {
    const entries = Object.entries(powers || {}).filter(([, value]) => text(value) !== '');
    if (!entries.length) return '<span class="pf-dim">未录入</span>';
    const parts = entries.slice(0, 4).map(([id, value]) => {
      const hero = heroById(id);
      const src = hero ? safeIcon(hero.icon) : '';
      return `<span class="pf-mini-hero" title="${esc(hero?.name || id)} 战力 ${esc(value)}">${src ? `<img src="${esc(src)}" alt="" width="18" height="18" loading="lazy">` : ''}<b>${esc(hero?.name || id)}</b> ${esc(value)}</span>`;
    });
    if (entries.length > 4) parts.push(`<span class="pf-dim">+${entries.length - 4}</span>`);
    return parts.join('');
  }

  function laneScoresCell(scores) {
    return LANES.map((lane) => `<span class="pf-lane"><i>${esc(lane)}</i> ${dash(scores?.[lane])}</span>`).join('');
  }

  function tagsCell(tags) {
    const list = Array.isArray(tags) ? tags.filter((item) => text(item)) : [];
    return list.length ? list.map((tag) => `<span class="pf-tag">${esc(tag)}</span>`).join('') : '<span class="pf-dim">—</span>';
  }

  function metricsCell(metrics) {
    const list = METRICS.filter((m) => text(metrics?.[m.key]) !== '');
    return list.length ? list.map((m) => `<span class="pf-metric"><i>${esc(m.label)}</i> ${esc(metrics[m.key])}</span>`).join('') : '<span class="pf-dim">未录入</span>';
  }

  const windowKeyOf = (win) => `${text(win?.start)}~${text(win?.end)}`;
  const windowLabel = (win) => `${text(win?.start) || '起止待定'} → ${text(win?.end) || '起止待定'}`;

  function allWindowKeys() {
    const map = new Map();
    for (const trial of state.doc.trials) {
      for (const win of trial.windows || []) {
        const key = windowKeyOf(win);
        if (!map.has(key)) map.set(key, { key, label: windowLabel(win) });
      }
    }
    return [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
  }

  /* ── 骨架与局部刷新 ────────────────────────────────────────────── */
  function html() {
    return `<div class="pf-page">
      <header class="pf-head">
        <div class="pf-head-top">
          <div>
            ${deco('divider-title')}
            <h1>档案管理</h1>
            <p>本队 / 对手 / 试训三条线各自独立。档案只记身份与属性，赛后指标率请到观察视图看。</p>
          </div>
          <button type="button" class="control" data-pf-reload>${icon('refresh') || glyph('refresh', { size: 14 })}<span data-pf-reload-label>刷新</span></button>
        </div>
        <nav class="pf-tabs" aria-label="档案类别">
          ${TABS.map((tab) => `<button type="button" class="pf-tab" data-pf-tab="${esc(tab.key)}" aria-pressed="${state.tab === tab.key}">
            ${glyph(TAB_GLYPH[tab.key], { size: 15 })}${esc(tab.label)} <span class="pf-tab-count" data-pf-count="${esc(tab.key)}">0</span>
          </button>`).join('')}
        </nav>
      </header>
      <p class="pf-notice" data-pf-notice role="status" aria-live="polite" hidden></p>
      <div data-pf-body></div>
    </div>
    <dialog class="pf-dialog" data-pf-editor aria-labelledby="pf-editor-title" aria-describedby="pf-editor-desc">
      <div data-pf-editor-body></div>
    </dialog>
    <dialog class="pf-dialog pf-dialog-sm" data-pf-confirm aria-labelledby="pf-confirm-title" aria-describedby="pf-confirm-text">
      <h2 id="pf-confirm-title">请确认</h2>
      <p id="pf-confirm-text" data-pf-confirm-text></p>
      <div class="pf-dialog-actions">
        <button type="button" class="control" data-pf-confirm-cancel autofocus>取消</button>
        <button type="button" class="pf-danger" data-pf-confirm-ok>确认</button>
      </div>
    </dialog>`;
  }

  function paintNotice() {
    const node = root?.querySelector('[data-pf-notice]');
    if (!node) return;
    node.innerHTML = state.noticeError && state.notice
      ? `${glyph('warning', { size: 14 })}<span>${esc(state.notice)}</span>`
      : esc(state.notice);
    node.classList.toggle('is-error', state.noticeError);
    node.hidden = !state.notice;
  }

  function paintTabs() {
    if (!root) return;
    root.querySelectorAll('[data-pf-tab]').forEach((button) => {
      const active = button.dataset.pfTab === state.tab;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const counts = { own: state.doc.own.length, opponents: state.doc.opponents.length, trials: state.doc.trials.length };
    root.querySelectorAll('[data-pf-count]').forEach((node) => {
      node.textContent = String(counts[node.dataset.pfCount] ?? 0);
    });
  }

  function paint() {
    if (!root) return;
    const body = root.querySelector('[data-pf-body]');
    if (body) {
      if (state.loading) {
        body.innerHTML = `<div class="pf-loading">${glyph('refresh', { size: 20, cls: 'pf-spin' })}正在读取档案…</div>`;
      } else if (state.tab === 'own') {
        body.innerHTML = ownHtml();
      } else if (state.tab === 'opponents') {
        body.innerHTML = opponentsHtml();
      } else {
        body.innerHTML = trialsHtml();
      }
    }
    paintTabs();
    paintNotice();
  }

  /* ── 本队 ──────────────────────────────────────────────────────── */
  function ownHtml() {
    const rows = state.doc.own.map((item) => `<tr>
      <th scope="row">${dash(item.realName)}</th>
      <td>${dash(item.matchId)}</td>
      <td>${dash(item.mainLane)}</td>
      <td>${dash(item.peakScore)}</td>
      <td class="pf-lanes">${laneScoresCell(item.laneScores)}</td>
      <td class="pf-heroes">${heroPowersCell(item.heroPowers)}</td>
      <td><span class="pf-badge ${item.starter === 'sub' ? 'is-sub' : 'is-starter'}">${item.starter === 'sub' ? '替补' : '首发'}</span></td>
      <td>${dash(item.personality)}</td>
      <td>${tagsCell(item.tags)}</td>
      <td>${dash(item.recordedAt)}</td>
      <td class="pf-actions">
        <button type="button" class="control" data-pf-edit data-pf-kind="own" data-pf-id="${esc(item.id)}">${glyph('edit', { size: 14 })}编辑</button>
        <button type="button" class="control" data-pf-transfer-out data-pf-id="${esc(item.id)}">${glyph('export', { size: 14 })}转出</button>
        <button type="button" class="control is-danger" data-pf-delete data-pf-kind="own" data-pf-id="${esc(item.id)}">${glyph('trash', { size: 14 })}删除</button>
      </td>
    </tr>`).join('');
    return `<section class="pf-section">
      <div class="pf-section-head"><div><h2>本队选手档案</h2>
        <p>真实姓名 / 比赛 ID 必填；五路段数、英雄战力与风格标签都是纯事实字段，可在卡片里点头像补录。</p></div>
        <div class="pf-head-actions">
          <button type="button" class="control" data-pf-import-own>${glyph('players', { size: 14 })}从选手分析导入</button>
          <button type="button" class="primary" data-pf-add-own>${plus({ size: 14 })}新增本队选手</button>
        </div></div>
      <div class="pf-table-wrap" tabindex="0" role="region" aria-label="本队选手档案表">
        <table class="pf-table">
          <caption class="pf-visually-hidden">本队选手档案</caption>
          <thead><tr>
            <th scope="col">真实姓名</th><th scope="col">比赛 ID</th><th scope="col">主位置</th>
            <th scope="col">巅峰分</th><th scope="col">五路分路段数</th><th scope="col">英雄战力</th>
            <th scope="col">身份</th><th scope="col">性格</th><th scope="col">风格标签</th>
            <th scope="col">记录时间</th><th scope="col">操作</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="11" class="pf-empty"><div class="pf-empty-guide">
            ${emptyIcon()}<b>还没有本队选手</b>
            <span>先建档案，再补事实字段，赛后指标才有归属。</span>
            <span class="pf-empty-steps">1 新增选手 · 2 点头像补五路段数与英雄战力 · 3 从选手分析导入已有数据</span>
          </div></td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }

  /* ── 对手 ──────────────────────────────────────────────────────── */
  function opponentsHtml() {
    const rows = state.doc.opponents.map((item) => `<tr>
      <th scope="row">${dash(item.matchId)}</th>
      <td>${dash(item.name)}</td>
      <td>${dash(item.team)}</td>
      <td>${dash(item.lane)}</td>
      <td>${dash(item.peakScore)}</td>
      <td>${dash(item.note)}</td>
      <td class="pf-actions">
        <button type="button" class="primary" data-pf-transfer-in data-pf-id="${esc(item.id)}">${glyph('home', { size: 14 })}转会转入</button>
        <button type="button" class="control" data-pf-edit data-pf-kind="opponents" data-pf-id="${esc(item.id)}">${glyph('edit', { size: 14 })}编辑</button>
        <button type="button" class="control is-danger" data-pf-delete data-pf-kind="opponents" data-pf-id="${esc(item.id)}">${glyph('trash', { size: 14 })}删除</button>
      </td>
    </tr>`).join('');
    return `<section class="pf-section">
      <div class="pf-section-head"><div><h2>对手选手档案</h2>
        <p>只需比赛正式 ID；其他信息先空着也能存。「转会转入」会把这条升格为本队档案（必填项需补齐）。</p></div>
        <button type="button" class="primary" data-pf-add-opp>${plus({ size: 14 })}新增对手选手</button></div>
      <div class="pf-table-wrap" tabindex="0" role="region" aria-label="对手选手档案表">
        <table class="pf-table">
          <caption class="pf-visually-hidden">对手选手档案</caption>
          <thead><tr>
            <th scope="col">比赛正式 ID</th><th scope="col">姓名 / 比赛名</th><th scope="col">所属战队</th>
            <th scope="col">位置</th><th scope="col">巅峰分</th><th scope="col">备注</th><th scope="col">操作</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="7" class="pf-empty">${emptyIcon()}还没有对手选手。忘了 ID 可以先留占位，之后补。</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }

  /* ── 试训 ──────────────────────────────────────────────────────── */
  function trialWindowsHtml() {
    const rows = [];
    for (const trial of state.doc.trials) {
      for (const win of trial.windows || []) {
        rows.push(`<tr>
          <th scope="row">${dash(trial.name)}</th>
          <td>${esc(windowLabel(win))}</td>
          <td>${dash(win.peakScore)}</td>
          <td>${dash(win.rank)}</td>
          <td class="pf-lanes">${laneScoresCell(win.laneScores)}</td>
          <td class="pf-heroes">${heroPowersCell(win.heroPowers)}</td>
          <td>${dash(win.heroesUsed)}</td>
          <td>${metricsCell(win.metrics)}</td>
          <td>${dash(win.recordedAt)}</td>
          <td class="pf-actions">
            <button type="button" class="control" data-pf-window-edit data-pf-trial="${esc(trial.id)}" data-pf-id="${esc(win.id)}">${glyph('edit', { size: 14 })}编辑</button>
            <button type="button" class="control is-danger" data-pf-window-delete data-pf-trial="${esc(trial.id)}" data-pf-id="${esc(win.id)}">${glyph('trash', { size: 14 })}删除</button>
          </td>
        </tr>`);
      }
    }
    return `<section class="pf-section">
      <div class="pf-section-head"><div><h3>时间窗明细</h3>
        <p>一个试训者可以挂多个时间窗；转正只打标记，记录原样留在这里，不迁出、不并入正式档案。</p></div></div>
      <div class="pf-table-wrap" tabindex="0" role="region" aria-label="试训时间窗明细表">
        <table class="pf-table">
          <caption class="pf-visually-hidden">试训时间窗明细</caption>
          <thead><tr>
            <th scope="col">试训者</th><th scope="col">时间窗</th><th scope="col">巅峰分</th><th scope="col">段位</th>
            <th scope="col">五路段数</th><th scope="col">英雄战力</th><th scope="col">该段用英雄</th>
            <th scope="col">比赛指标</th><th scope="col">记录时间</th><th scope="col">操作</th>
          </tr></thead>
          <tbody>${rows.join('') || `<tr><td colspan="10" class="pf-empty">${emptyIcon()}还没有时间窗，先在上方试训者行点「加时间窗」。</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }

  function comparisonHtml() {
    const windows = allWindowKeys();
    if (!windows.length) {
      return `<section class="pf-section"><h3>横向对比</h3>
        <p class="pf-empty">${emptyIcon()}还没有时间窗。添加后可在这里按同一时间窗把多名试训者摆在一起看。</p></section>`;
    }
    const chosen = windows.some((w) => w.key === state.compare.windowKey) ? state.compare.windowKey : windows[0].key;
    state.compare.windowKey = chosen;
    const candidates = state.doc.trials.filter((trial) => (trial.windows || []).some((win) => windowKeyOf(win) === chosen));
    const ids = state.compare.ids.filter((id) => candidates.some((trial) => trial.id === id));
    const selected = ids.length ? ids : candidates.map((trial) => trial.id);
    state.compare.ids = selected;

    const rows = selected.map((id) => {
      const trial = candidates.find((item) => item.id === id);
      const win = (trial.windows || []).find((item) => windowKeyOf(item) === chosen);
      return `<tr>
        <th scope="row">${dash(trial.name)}</th>
        <td>${dash(win.peakScore)}</td>
        <td>${dash(win.rank)}</td>
        <td class="pf-heroes">${heroPowersCell(win.heroPowers)}</td>
        <td>${dash(win.heroesUsed)}</td>
        <td>${metricsCell(win.metrics)}</td>
      </tr>`;
    }).join('');

    return `<section class="pf-section pf-compare">
      <h3>横向对比 <small>同一时间窗</small></h3>
      <div class="pf-compare-controls">
        <label for="pf-window-select">时间窗
          <select id="pf-window-select" data-pf-window-select>
            ${windows.map((w) => `<option value="${esc(w.key)}"${w.key === chosen ? ' selected' : ''}>${esc(w.label)}</option>`).join('')}
          </select>
        </label>
        <fieldset class="pf-compare-people">
          <legend>参与对比的试训者</legend>
          ${candidates.map((trial) => `<label class="pf-check">
            <input type="checkbox" data-pf-compare-toggle value="${esc(trial.id)}"${selected.includes(trial.id) ? ' checked' : ''}>
            <span>${esc(trial.name)}</span></label>`).join('')}
        </fieldset>
      </div>
      <div class="pf-table-wrap" tabindex="0" role="region" aria-label="试训者横向对比表">
        <table class="pf-table">
          <caption class="pf-visually-hidden">试训者在所选时间窗的横向对比</caption>
          <thead><tr>
            <th scope="col">试训者</th><th scope="col">巅峰分</th><th scope="col">段位</th>
            <th scope="col">英雄战力</th><th scope="col">该段用英雄</th><th scope="col">比赛指标</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="6" class="pf-empty">${emptyIcon()}至少勾选一名试训者。</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }

  function trialsHtml() {
    const rows = state.doc.trials.map((trial) => {
      const count = (trial.windows || []).length;
      return `<tr>
        <th scope="row">${dash(trial.name)}${trial.promoted ? ' <span class="pf-badge is-promoted">已转正</span>' : ''}</th>
        <td>${dash(trial.mainLane)}</td>
        <td>${dash(trial.style)}</td>
        <td>${dash(trial.peakScore)}</td>
        <td class="pf-lanes">${laneScoresCell(trial.laneScores)}</td>
        <td class="pf-heroes">${heroPowersCell(trial.heroPowers)}</td>
        <td>${dash(trial.recordedAt)}</td>
        <td>${trial.promoted ? '已转正（留在本系统）' : '试训中'}</td>
        <td>${count} 个</td>
        <td class="pf-actions">
          <button type="button" class="control" data-pf-window-add data-pf-trial="${esc(trial.id)}">${glyph('calendar', { size: 14 })}加时间窗</button>
          <button type="button" class="control" data-pf-promote data-pf-id="${esc(trial.id)}">${glyph('shield', { size: 14 })}${trial.promoted ? '取消转正' : '标记转正'}</button>
          <button type="button" class="control" data-pf-edit data-pf-kind="trials" data-pf-id="${esc(trial.id)}">${glyph('edit', { size: 14 })}编辑</button>
          <button type="button" class="control is-danger" data-pf-delete data-pf-kind="trials" data-pf-id="${esc(trial.id)}">${glyph('trash', { size: 14 })}删除</button>
        </td>
      </tr>`;
    }).join('');
    return `<section class="pf-section">
      <div class="pf-section-head"><div><h2>试训档案</h2>
        <p>独立时间窗系统：按姓名 / 主打分路 / 风格建档，再往下挂 10/27–10/30 这样的时间块。</p></div>
        <button type="button" class="primary" data-pf-add-trial>${plus({ size: 14 })}新增试训者</button></div>
      <div class="pf-table-wrap" tabindex="0" role="region" aria-label="试训者档案表">
        <table class="pf-table">
          <caption class="pf-visually-hidden">试训者档案</caption>
          <thead><tr>
            <th scope="col">姓名</th><th scope="col">主打分路</th><th scope="col">风格</th>
            <th scope="col">巅峰分</th><th scope="col">五路段数</th><th scope="col">英雄战力</th>
            <th scope="col">记录时间</th><th scope="col">状态</th><th scope="col">时间窗</th><th scope="col">操作</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="10" class="pf-empty">${emptyIcon()}还没有试训者。</td></tr>`}</tbody>
        </table>
      </div>
    </section>
    ${trialWindowsHtml()}
    ${comparisonHtml()}`;
  }

  /* ── 对话框 ────────────────────────────────────────────────────── */
  function draftFor(kind, id, prefill = {}) {
    if (kind === 'own') {
      const item = id ? state.doc.own.find((x) => x.id === id) : null;
      const base = item ? clone(item) : {};
      return {
        realName: prefill.realName ?? base.realName ?? '',
        matchId: prefill.matchId ?? base.matchId ?? '',
        mainLane: prefill.mainLane ?? base.mainLane ?? LANES[0],
        peakScore: base.peakScore ?? '',
        laneScores: { ...(base.laneScores || {}) },
        heroPowers: { ...(base.heroPowers || {}) },
        starter: base.starter === 'sub' ? 'sub' : 'starter',
        personality: base.personality ?? '',
        tags: Array.isArray(base.tags) ? base.tags.slice() : [],
        recordedAt: base.recordedAt ?? nowLocal(),
      };
    }
    if (kind === 'opponents') {
      const item = id ? state.doc.opponents.find((x) => x.id === id) : null;
      return { matchId: item?.matchId ?? '', name: item?.name ?? '', team: item?.team ?? '',
        lane: item?.lane ?? '', peakScore: item?.peakScore ?? '', note: item?.note ?? '' };
    }
    if (kind === 'trials') {
      const item = id ? state.doc.trials.find((x) => x.id === id) : null;
      return { name: item?.name ?? '', mainLane: item?.mainLane ?? LANES[0],
        style: item?.style ?? '', note: item?.note ?? '', promoted: Boolean(item?.promoted),
        peakScore: item?.peakScore ?? '',
        laneScores: { ...(item?.laneScores || {}) },
        heroPowers: { ...(item?.heroPowers || {}) },
        recordedAt: item?.recordedAt ?? nowLocal() };
    }
    const trial = state.doc.trials.find((x) => x.id === (prefill.trialId || ''));
    const win = id ? (trial?.windows || []).find((x) => x.id === id) : null;
    return {
      start: win?.start ?? '', end: win?.end ?? '', peakScore: win?.peakScore ?? '',
      rank: win?.rank ?? '', heroPowers: { ...(win?.heroPowers || {}) },
      laneScores: { ...(win?.laneScores || {}) },
      heroesUsed: win?.heroesUsed ?? '', metrics: { ...(win?.metrics || {}) },
      recordedAt: win?.recordedAt ?? nowLocal(),
    };
  }

  function editorTitle(kind, editing) {
    const map = {
      own: ['新增本队选手', '编辑本队选手'],
      opponents: ['新增对手选手', '编辑对手选手'],
      trials: ['新增试训者', '编辑试训者'],
      window: ['新增时间窗', '编辑时间窗'],
    };
    const pair = map[kind] || map.own;
    return pair[editing ? 1 : 0];
  }

  function heroPickerHtml() {
    return `<div class="pf-field pf-hero-picker">
      <label for="pf-hero-search">英雄战力 · 点头像选英雄</label>
      <p class="pf-hint" id="pf-hero-hint">先点头像选中，再在右侧填战力；不选英雄也能保存。</p>
      <div class="pf-hero-filters">
        <label for="pf-hero-lane">分路筛选</label>
        <select id="pf-hero-lane" data-pf-hero-lane>
          <option value="">全部分路</option>
          ${LANES.map((lane) => `<option value="${escapeHtml(lane)}"${state.heroLaneFilter === lane ? ' selected' : ''}>${escapeHtml(lane)}</option>`).join('')}
        </select>
        <input type="search" id="pf-hero-search" data-pf-hero-search placeholder="搜索英雄名"
               autocomplete="off" aria-describedby="pf-hero-hint">
      </div>
      <div class="pf-hero-selected" data-pf-hero-selected></div>
      <div class="pf-hero-grid" data-pf-hero-grid></div>
    </div>`;
  }

  function editorFormHtml() {
    const ed = state.editor;
    const draft = ed.draft;
    let inner = '';
    if (ed.kind === 'own') {
      inner = `
        <div class="pf-form-grid">
          ${field('真实姓名', 'pf-realName', textInput('pf-realName', 'realName', draft.realName, { required: true, autofocus: true, placeholder: '如：张三' }))}
          ${field('比赛 ID', 'pf-matchId', textInput('pf-matchId', 'matchId', draft.matchId, { required: true, placeholder: '比赛正式使用的 ID' }))}
          ${field('主位置', 'pf-mainLane', selectInput('pf-mainLane', 'mainLane', draft.mainLane, LANES, { required: true }))}
          ${field('巅峰赛分数', 'pf-peakScore', textInput('pf-peakScore', 'peakScore', draft.peakScore, { type: 'number', min: 0, inputmode: 'numeric' }))}
          ${field('资料记录时间', 'pf-recordedAt', textInput('pf-recordedAt', 'recordedAt', draft.recordedAt, { type: 'datetime-local', step: 60 }))}
          ${field('身份', 'pf-starter', selectInput('pf-starter', 'starter', draft.starter, [
            { value: 'starter', label: '首发' }, { value: 'sub', label: '替补' },
          ]))}
          ${field('性格', 'pf-personality', textInput('pf-personality', 'personality', draft.personality, { placeholder: '如：沉稳、敢开团' }))}
        </div>
        <fieldset class="pf-fieldset"><legend>五路分路段数</legend>
          <div class="pf-lane-grid">${LANES.map((lane, i) => field(lane, `pf-lane-${i}`,
            textInput(`pf-lane-${i}`, `lane-${i}`, draft.laneScores[lane] ?? '', { type: 'number', min: 0, inputmode: 'numeric' }))).join('')}</div>
        </fieldset>
        ${heroPickerHtml()}
        <fieldset class="pf-fieldset"><legend>教练自定义风格标签</legend>
          <div class="pf-tag-list" data-pf-tag-list></div>
          <div class="pf-tag-add">
            <label class="pf-visually-hidden" for="pf-tag-input">新风格标签</label>
            <input id="pf-tag-input" data-pf-tag-input type="text" placeholder="如：指挥 / 激进 / 稳塔" autocomplete="off">
            <button type="button" class="control" data-pf-tag-add>添加标签</button>
          </div>
        </fieldset>`;
    } else if (ed.kind === 'opponents') {
      inner = `<div class="pf-form-grid">
        ${field('比赛正式 ID *', 'pf-matchId', textInput('pf-matchId', 'matchId', draft.matchId, { required: true, autofocus: true, placeholder: '必填，其他都可后补' }))}
        ${field('姓名 / 比赛名', 'pf-name', textInput('pf-name', 'name', draft.name, { placeholder: '可先留空' }))}
        ${field('所属战队', 'pf-team', textInput('pf-team', 'team', draft.team))}
        ${field('位置', 'pf-lane', selectInput('pf-lane', 'lane', draft.lane || '', [{ value: '', label: '未填' }, ...LANES]))}
        ${field('巅峰分', 'pf-peakScore', textInput('pf-peakScore', 'peakScore', draft.peakScore, { type: 'number', min: 0, inputmode: 'numeric' }))}
      </div>
      ${field('备注', 'pf-note', textareaInput('pf-note', 'note', draft.note, { placeholder: '交手印象、来源等' }))}`;
    } else if (ed.kind === 'trials') {
      inner = `<div class="pf-form-grid">
        ${field('姓名 *', 'pf-name', textInput('pf-name', 'name', draft.name, { required: true, autofocus: true }))}
        ${field('主打分路 *', 'pf-mainLane', selectInput('pf-mainLane', 'mainLane', draft.mainLane, LANES, { required: true }))}
        ${field('风格 *', 'pf-style', textInput('pf-style', 'style', draft.style, { required: true, placeholder: '如：进攻型中单' }))}
        ${field('巅峰赛分数', 'pf-peakScore', textInput('pf-peakScore', 'peakScore', draft.peakScore, { type: 'number', min: 0, inputmode: 'numeric' }))}
        ${field('资料记录时间', 'pf-recordedAt', textInput('pf-recordedAt', 'recordedAt', draft.recordedAt, { type: 'datetime-local', step: 60 }))}
      </div>
      <fieldset class="pf-fieldset"><legend>五路分路段数</legend>
        <div class="pf-lane-grid">${LANES.map((lane, i) => field(lane, `pf-lane-${i}`,
          textInput(`pf-lane-${i}`, `lane-${i}`, draft.laneScores[lane] ?? '', { type: 'number', min: 0, inputmode: 'numeric' }))).join('')}</div>
      </fieldset>
      ${heroPickerHtml()}
      ${field('备注', 'pf-note', textareaInput('pf-note', 'note', draft.note))}
      <label class="pf-check pf-check-block"><input type="checkbox" name="promoted"${draft.promoted ? ' checked' : ''}><span>已转正（记录仍留在试训系统）</span></label>`;
    } else {
      inner = `<div class="pf-form-grid">
        ${field('开始日期 *', 'pf-start', textInput('pf-start', 'start', draft.start, { type: 'date', required: true, autofocus: true }))}
        ${field('结束日期 *', 'pf-end', textInput('pf-end', 'end', draft.end, { type: 'date', required: true }))}
        ${field('巅峰分', 'pf-peakScore', textInput('pf-peakScore', 'peakScore', draft.peakScore, { type: 'number', min: 0, inputmode: 'numeric' }))}
        ${field('段位', 'pf-rank', textInput('pf-rank', 'rank', draft.rank, { placeholder: '如：荣耀王者 50 星' }))}
        ${field('资料记录时间', 'pf-recordedAt', textInput('pf-recordedAt', 'recordedAt', draft.recordedAt, { type: 'datetime-local', step: 60 }))}
      </div>
      <fieldset class="pf-fieldset"><legend>本时间窗五路段数</legend>
        <div class="pf-lane-grid">${LANES.map((lane, i) => field(lane, `pf-lane-${i}`,
          textInput(`pf-lane-${i}`, `lane-${i}`, draft.laneScores[lane] ?? '', { type: 'number', min: 0, inputmode: 'numeric' }))).join('')}</div>
      </fieldset>
      ${heroPickerHtml()}
      ${field('该段用英雄', 'pf-heroesUsed', textInput('pf-heroesUsed', 'heroesUsed', draft.heroesUsed, { placeholder: '多个用逗号分隔', describedBy: 'pf-heroes-hint' }))}
      <p class="pf-hint" id="pf-heroes-hint">和上面选的英雄可以不一致：这里记实际常用的。</p>
      <fieldset class="pf-fieldset"><legend>比赛指标（选填）</legend>
        <div class="pf-metric-grid">${METRICS.map((m) => field(m.label, `pf-metric-${m.key}`,
          textInput(`pf-metric-${m.key}`, `metric-${m.key}`, draft.metrics[m.key] ?? '', { placeholder: '选填' }))).join('')}</div>
      </fieldset>`;
    }
    const transferNote = ed.transferFromId
      ? '<p class="pf-transfer-note">转会转入：保存后会补齐必填项，并从对手档案移除这条记录。</p>'
      : '';
    return `<h2 id="pf-editor-title">${esc(editorTitle(ed.kind, Boolean(ed.id)))}</h2>
      <p id="pf-editor-desc" class="pf-dialog-desc">带 * 的为必填项；其余留空不参与对比。</p>
      ${transferNote}
      <p class="pf-dialog-err" role="alert" data-pf-dialog-err hidden></p>
      <form data-pf-form>
        ${inner}
        <div class="pf-dialog-actions">
          <button type="button" class="control" data-pf-dialog-cancel>取消</button>
          <button type="submit" class="primary">保存</button>
        </div>
      </form>`;
  }

  function paintHeroSelected() {
    const holder = root?.querySelector('[data-pf-hero-selected]');
    if (!holder || !state.editor) return;
    const powers = state.editor.draft.heroPowers || {};
    const entries = Object.entries(powers);
    holder.innerHTML = entries.length
      ? entries.map(([id, value], index) => heroChip(id, value, index)).join('')
      : '<span class="pf-dim">还没有选英雄，点下面的头像添加。</span>';
  }

  function paintHeroGrid() {
    const grid = root?.querySelector('[data-pf-hero-grid]');
    if (!grid) return;
    const query = state.heroQuery.trim().toLowerCase();
    const lane = state.heroLaneFilter;
    const list = state.heroes.filter((hero) => {
      if (query && !hero.name.toLowerCase().includes(query)) return false;
      if (!lane) return true;
      const lanes = state.heroLanes[hero.name] || [];
      return lanes.includes(lane);
    }).slice(0, 120);
    const selected = state.editor?.draft.heroPowers || {};
    grid.innerHTML = list.length
      ? list.map((hero) => heroOption(hero, Object.prototype.hasOwnProperty.call(selected, hero.id))).join('')
      : `<p class="pf-empty-small">${glyph('heroes', { size: 16 })}没有匹配的英雄。</p>`;
  }

  function paintTags() {
    const holder = root?.querySelector('[data-pf-tag-list]');
    if (!holder || !state.editor) return;
    const tags = state.editor.draft.tags || [];
    holder.innerHTML = tags.length
      ? tags.map((tag, index) => `<span class="pf-tag is-editable">${esc(tag)}
          <button type="button" class="pf-icon-btn" data-pf-tag-remove="${index}" aria-label="删除标签 ${esc(tag)}">${glyph('ban', { size: 14 })}</button>
        </span>`).join('')
      : '<span class="pf-dim">还没有风格标签。</span>';
  }

  /** 从选手分析页拉取本队名单，按比赛 ID 去重后让人勾选导入；导入后仍可在表格里补录。 */
  async function openImport() {
    try {
      const board = await api('v3/players-board', { signal: controller?.signal });
      const known = new Set();
      for (const item of state.doc.own) {
        if (text(item.matchId)) known.add(text(item.matchId));
        if (text(item.realName)) known.add(text(item.realName));
      }
      const seen = new Set();
      const candidates = ((board && board.players) || [])
        .filter((player) => player && player.side === 'own' && text(player.name))
        .map((player) => ({ matchId: text(player.name), lane: text(player.lane),
          games: Number(player.games) || 0, accounts: (player.accountIds || []).length }))
        .filter((item) => {
          if (known.has(item.matchId) || seen.has(item.matchId)) return false;
          seen.add(item.matchId);
          return true;
        })
        .sort((a, b) => b.games - a.games || a.matchId.localeCompare(b.matchId, 'zh-CN'));
      state.importQuery = '';
      state.editor = { kind: 'import', draft: {}, candidates, selected: new Set(candidates.map((c) => c.matchId)) };
      state.heroQuery = '';
      state.heroLaneFilter = '';
      const body = root?.querySelector('[data-pf-editor-body]');
      const dialog = root?.querySelector('[data-pf-editor]');
      if (!body || !dialog) return;
      body.innerHTML = importFormHtml();
      if (!dialog.open) dialog.showModal();
      paintImportList();
    } catch (error) {
      setNotice(error.message || '读取选手分析数据失败，请重试。', true);
    }
  }

  function importFormHtml() {
    return `<h2 id="pf-editor-title">从选手分析导入本队</h2>
      <p id="pf-editor-desc" class="pf-dialog-desc">按比赛 ID 去重，只导入还没建档的人；真实姓名等字段留空，导入后在表格里补录。</p>
      <p class="pf-dialog-err" role="alert" data-pf-dialog-err hidden></p>
      <form data-pf-form>
        <div class="pf-import-bar">
          <label class="pf-visually-hidden" for="pf-import-search">搜索本队选手</label>
          <input type="search" id="pf-import-search" data-pf-import-search placeholder="搜索比赛 ID / 分路" autocomplete="off" autofocus>
          <button type="button" class="control" data-pf-import-all>全选</button>
          <button type="button" class="control" data-pf-import-none>清空</button>
        </div>
        <p class="pf-hint" data-pf-import-count></p>
        <div class="pf-import-list" data-pf-import-list tabindex="0" role="group" aria-label="可导入的本队选手"></div>
        <div class="pf-dialog-actions">
          <button type="button" class="control" data-pf-dialog-cancel>取消</button>
          <button type="submit" class="primary">导入所选</button>
        </div>
      </form>`;
  }

  function paintImportList() {
    const holder = root?.querySelector('[data-pf-import-list]');
    const count = root?.querySelector('[data-pf-import-count]');
    const ed = state.editor;
    if (!holder || !ed || ed.kind !== 'import') return;
    const query = state.importQuery.trim().toLowerCase();
    const list = ed.candidates.filter((item) => !query
      || item.matchId.toLowerCase().includes(query) || item.lane.toLowerCase().includes(query));
    if (count) count.textContent = `候选 ${ed.candidates.length} 人，已选 ${ed.selected.size} 人。`;
    const focused = root?.querySelector(':focus')?.dataset?.pfImportId;
    holder.innerHTML = list.length ? list.map((item) => `<label class="pf-import-row">
      <input type="checkbox" data-pf-import-id value="${escapeHtml(item.matchId)}"${ed.selected.has(item.matchId) ? ' checked' : ''}>
      <span class="pf-import-name">${escapeHtml(item.matchId)}</span>
      <span class="pf-import-meta">${escapeHtml(item.lane || '位置未记')} · ${escapeHtml(item.games)} 局${item.accounts ? ` · ${item.accounts} 个账号` : ''}</span>
    </label>`).join('') : `<p class="pf-empty-small">${glyph('players', { size: 16 })}没有匹配的选手。</p>`;
    if (focused) {
      const node = [...holder.querySelectorAll('[data-pf-import-id]')].find((el) => el.value === focused);
      node?.focus();
    }
  }

  function openEditor(kind, id, prefill = {}, transferFromId = '', trialId = '') {
    state.editor = { kind, id: id || '', draft: draftFor(kind, id, { ...prefill, trialId }), transferFromId, trialId };
    state.heroQuery = '';
    state.heroLaneFilter = '';
    const body = root?.querySelector('[data-pf-editor-body]');
    const dialog = root?.querySelector('[data-pf-editor]');
    if (!body || !dialog) return;
    body.innerHTML = editorFormHtml();
    paintHeroSelected();
    paintHeroGrid();
    paintTags();
    if (!dialog.open) dialog.showModal();
  }

  function closeEditor() {
    const dialog = root?.querySelector('[data-pf-editor]');
    if (dialog?.open) dialog.close();
    state.editor = null;
  }

  function askConfirm(message, action) {
    state.pendingConfirm = action;
    const dialog = root?.querySelector('[data-pf-confirm]');
    const label = dialog?.querySelector('[data-pf-confirm-text]');
    if (label) label.textContent = message;
    if (dialog && !dialog.open) dialog.showModal();
  }

  function closeConfirm() {
    const dialog = root?.querySelector('[data-pf-confirm]');
    if (dialog?.open) dialog.close();
    state.pendingConfirm = null;
  }

  /* ── 保存 ──────────────────────────────────────────────────────── */
  function collectHeroPowers(form, draft) {
    form.querySelectorAll('[data-pf-hero-power]').forEach((input) => {
      draft.heroPowers[input.dataset.pfHeroPower] = String(input.value ?? '').trim();
    });
    return { ...draft.heroPowers };
  }

  function onSubmit(event) {
    const form = event.target.closest('[data-pf-form]');
    if (!form || !state.editor) return;
    event.preventDefault();
    const ed = state.editor;
    const data = new FormData(form);
    const heroPowers = collectHeroPowers(form, ed.draft);
    const next = clone(state.doc);
    const recordId = ed.id || uid(ed.kind === 'window' ? 'win' : ed.kind.slice(0, 3));

    if (ed.kind === 'import') {
      const checked = new Set([...form.querySelectorAll('[data-pf-import-id]:checked')].map((node) => node.value));
      const chosen = ed.candidates.filter((item) => checked.has(item.matchId));
      if (!chosen.length) {
        setDialogError('请先勾选要导入的选手。');
        return;
      }
      const at = nowLocal();
      for (const item of chosen) {
        next.own.push({ id: uid('own'), realName: '', matchId: item.matchId, mainLane: item.lane || LANES[0],
          peakScore: '', laneScores: {}, heroPowers: {}, starter: 'starter', personality: '', tags: [],
          recordedAt: at, source: 'players-board', games: item.games });
      }
      persist(next).then((ok) => {
        if (ok) {
          setNotice(`已导入 ${chosen.length} 名选手，真实姓名等字段可在表格里补录。`);
          closeEditor();
        }
      });
      return;
    }

    if (ed.kind === 'own') {
      const laneScores = {};
      LANES.forEach((lane, i) => { laneScores[lane] = String(data.get(`lane-${i}`) ?? '').trim(); });
      const record = {
        id: recordId,
        realName: text(data.get('realName')),
        matchId: text(data.get('matchId')),
        mainLane: text(data.get('mainLane')) || LANES[0],
        peakScore: text(data.get('peakScore')),
        laneScores,
        heroPowers,
        starter: text(data.get('starter')) === 'sub' ? 'sub' : 'starter',
        personality: text(data.get('personality')),
        tags: (ed.draft.tags || []).filter((tag) => text(tag)),
        recordedAt: text(data.get('recordedAt')) || nowLocal(),
      };
      const at = next.own.findIndex((item) => item.id === ed.id);
      if (at >= 0) next.own[at] = record; else next.own.push(record);
      if (ed.transferFromId) next.opponents = next.opponents.filter((item) => item.id !== ed.transferFromId);
    } else if (ed.kind === 'opponents') {
      const record = {
        id: recordId, matchId: text(data.get('matchId')), name: text(data.get('name')),
        team: text(data.get('team')), lane: text(data.get('lane')),
        peakScore: text(data.get('peakScore')), note: text(data.get('note')),
      };
      const at = next.opponents.findIndex((item) => item.id === ed.id);
      if (at >= 0) next.opponents[at] = record; else next.opponents.push(record);
    } else if (ed.kind === 'trials') {
      const trialLaneScores = {};
      LANES.forEach((lane, i) => { trialLaneScores[lane] = String(data.get(`lane-${i}`) ?? '').trim(); });
      const record = {
        id: recordId, name: text(data.get('name')), mainLane: text(data.get('mainLane')),
        style: text(data.get('style')), note: text(data.get('note')),
        promoted: Boolean(data.get('promoted')),
        peakScore: text(data.get('peakScore')), laneScores: trialLaneScores, heroPowers,
        recordedAt: text(data.get('recordedAt')) || nowLocal(),
        windows: ed.id ? (next.trials.find((item) => item.id === ed.id)?.windows || []) : [],
      };
      const at = next.trials.findIndex((item) => item.id === ed.id);
      if (at >= 0) next.trials[at] = record; else next.trials.push(record);
    } else {
      const start = text(data.get('start'));
      const end = text(data.get('end'));
      if (start && end && end < start) {
        setDialogError('结束日期不能早于开始日期。');
        const endField = form.querySelector('[name="end"]');
        endField?.setAttribute('aria-invalid', 'true');
        endField?.focus();
        return;
      }
      const metrics = {};
      METRICS.forEach((m) => { metrics[m.key] = text(data.get(`metric-${m.key}`)); });
      const laneScores = {};
      LANES.forEach((lane, i) => { laneScores[lane] = String(data.get(`lane-${i}`) ?? '').trim(); });
      const record = {
        id: recordId, start, end, peakScore: text(data.get('peakScore')),
        rank: text(data.get('rank')), heroPowers, laneScores,
        heroesUsed: text(data.get('heroesUsed')), metrics,
        recordedAt: text(data.get('recordedAt')) || nowLocal(),
      };
      const trial = next.trials.find((item) => item.id === ed.trialId);
      if (!trial) { setDialogError('找不到对应的试训者，请刷新后重试。'); return; }
      trial.windows = trial.windows || [];
      const at = trial.windows.findIndex((item) => item.id === ed.id);
      if (at >= 0) trial.windows[at] = record; else trial.windows.push(record);
    }

    persist(next).then((ok) => {
      if (ok) closeEditor();
    });
  }

  /* ── 事件委托 ──────────────────────────────────────────────────── */
  function onClick(event) {
    const target = event.target;
    if (target.closest('[data-pf-reload]')) { load(); return; }

    const tab = target.closest('[data-pf-tab]');
    if (tab) { state.tab = tab.dataset.pfTab; paint(); return; }

    if (target.closest('[data-pf-add-own]')) { openEditor('own', ''); return; }
    if (target.closest('[data-pf-import-own]')) { openImport(); return; }
    if (target.closest('[data-pf-import-all]') && state.editor?.kind === 'import') {
      state.editor.selected = new Set(state.editor.candidates.map((item) => item.matchId));
      paintImportList();
      return;
    }
    if (target.closest('[data-pf-import-none]') && state.editor?.kind === 'import') {
      state.editor.selected = new Set();
      paintImportList();
      return;
    }
    if (target.closest('[data-pf-add-opp]')) { openEditor('opponents', ''); return; }
    if (target.closest('[data-pf-add-trial]')) { openEditor('trials', ''); return; }

    const edit = target.closest('[data-pf-edit]');
    if (edit) { openEditor(edit.dataset.pfKind, edit.dataset.pfId); return; }

    const del = target.closest('[data-pf-delete]');
    if (del) {
      const kind = del.dataset.pfKind;
      const id = del.dataset.pfId;
      const item = (state.doc[kind] || []).find((x) => x.id === id);
      if (!item) return;
      const label = item.realName || item.name || item.matchId || '这条记录';
      askConfirm(`确定删除「${label}」？此操作不可撤销。`, () => {
        const next = clone(state.doc);
        next[kind] = next[kind].filter((x) => x.id !== id);
        persist(next);
      });
      return;
    }

    const transferIn = target.closest('[data-pf-transfer-in]');
    if (transferIn) {
      const opp = state.doc.opponents.find((x) => x.id === transferIn.dataset.pfId);
      if (!opp) return;
      openEditor('own', '', {
        realName: opp.name || '', matchId: opp.matchId || '',
        mainLane: opp.lane || LANES[0], peakScore: opp.peakScore || '',
      }, opp.id);
      return;
    }

    const transferOut = target.closest('[data-pf-transfer-out]');
    if (transferOut) {
      const own = state.doc.own.find((x) => x.id === transferOut.dataset.pfId);
      if (!own) return;
      askConfirm(`把「${own.realName || '这名选手'}」转出到对手档案？本队记录会移除。`, () => {
        const next = clone(state.doc);
        next.own = next.own.filter((x) => x.id !== own.id);
        if (!next.opponents.some((o) => o.matchId && o.matchId === own.matchId)) {
          next.opponents.push({
            id: uid('opp'), matchId: own.matchId || '', name: own.realName || '',
            team: '', lane: own.mainLane || '', peakScore: own.peakScore || '',
            note: '由本队档案转会转入',
          });
        }
        persist(next);
      });
      return;
    }

    const promote = target.closest('[data-pf-promote]');
    if (promote) {
      const next = clone(state.doc);
      const trial = next.trials.find((x) => x.id === promote.dataset.pfId);
      if (!trial) return;
      trial.promoted = !trial.promoted;
      persist(next);
      return;
    }

    const addWindow = target.closest('[data-pf-window-add]');
    if (addWindow) { openEditor('window', '', {}, '', addWindow.dataset.pfTrial); return; }

    const editWindow = target.closest('[data-pf-window-edit]');
    if (editWindow) { openEditor('window', editWindow.dataset.pfId, {}, '', editWindow.dataset.pfTrial); return; }

    const deleteWindow = target.closest('[data-pf-window-delete]');
    if (deleteWindow) {
      const trialId = deleteWindow.dataset.pfTrial;
      const winId = deleteWindow.dataset.pfId;
      const trial = state.doc.trials.find((x) => x.id === trialId);
      const win = trial?.windows?.find((x) => x.id === winId);
      if (!trial || !win) return;
      askConfirm(`删除「${trial.name}」的 ${windowLabel(win)} 时间窗？`, () => {
        const next = clone(state.doc);
        const t = next.trials.find((x) => x.id === trialId);
        if (t) t.windows = (t.windows || []).filter((x) => x.id !== winId);
        persist(next);
      });
      return;
    }

    const heroToggle = target.closest('[data-pf-hero-toggle]');
    if (heroToggle && state.editor) {
      const id = heroToggle.dataset.pfHeroToggle;
      const powers = state.editor.draft.heroPowers;
      if (Object.prototype.hasOwnProperty.call(powers, id)) delete powers[id];
      else powers[id] = '';
      paintHeroSelected();
      paintHeroGrid();
      return;
    }

    const heroRemove = target.closest('[data-pf-hero-remove]');
    if (heroRemove && state.editor) {
      delete state.editor.draft.heroPowers[heroRemove.dataset.pfHeroRemove];
      paintHeroSelected();
      paintHeroGrid();
      return;
    }

    const tagAdd = target.closest('[data-pf-tag-add]');
    if (tagAdd && state.editor) {
      const input = root.querySelector('[data-pf-tag-input]');
      const value = text(input?.value);
      if (!value) { input?.focus(); return; }
      state.editor.draft.tags = state.editor.draft.tags || [];
      if (!state.editor.draft.tags.includes(value)) state.editor.draft.tags.push(value);
      if (input) input.value = '';
      paintTags();
      input?.focus();
      return;
    }

    const tagRemove = target.closest('[data-pf-tag-remove]');
    if (tagRemove && state.editor) {
      state.editor.draft.tags.splice(Number(tagRemove.dataset.pfTagRemove), 1);
      paintTags();
      return;
    }

    if (target.closest('[data-pf-dialog-cancel]')) { closeEditor(); return; }
    if (target.closest('[data-pf-confirm-cancel]')) { closeConfirm(); return; }
    if (target.closest('[data-pf-confirm-ok]')) {
      const action = state.pendingConfirm;
      const dialog = root.querySelector('[data-pf-confirm]');
      if (dialog?.open) dialog.close();
      state.pendingConfirm = null;
      action?.();
    }
  }

  function refocusCompare(id) {
    const nodes = root?.querySelectorAll('[data-pf-compare-toggle]') || [];
    for (const node of nodes) {
      if (node.value === id) { node.focus(); return; }
    }
  }

  function onInput(event) {
    const target = event.target;
    if (!target?.matches) return;
    if (event.type === 'input' && target.matches('[data-pf-hero-search]')) {
      state.heroQuery = String(target.value || '');
      paintHeroGrid();
      return;
    }
    if (event.type === 'change' && target.matches('[data-pf-hero-lane]')) {
      state.heroLaneFilter = String(target.value || '');
      paintHeroGrid();
      return;
    }
    if (event.type === 'input' && target.matches('[data-pf-import-search]')) {
      state.importQuery = String(target.value || '');
      paintImportList();
      return;
    }
    if (event.type === 'change' && target.matches('[data-pf-import-id]') && state.editor?.kind === 'import') {
      const id = target.value;
      if (target.checked) state.editor.selected.add(id); else state.editor.selected.delete(id);
      paintImportList();
      return;
    }
    if (event.type === 'input' && target.matches('[data-pf-hero-power]') && state.editor) {
      state.editor.draft.heroPowers[target.dataset.pfHeroPower] = String(target.value ?? '').trim();
      return;
    }
    if (event.type === 'change' && target.matches('[data-pf-window-select]')) {
      state.compare.windowKey = String(target.value || '');
      state.compare.ids = [];
      paint();
      root?.querySelector('[data-pf-window-select]')?.focus();
      return;
    }
    if (event.type === 'change' && target.matches('[data-pf-compare-toggle]')) {
      const id = target.value;
      const set = new Set(state.compare.ids);
      if (target.checked) set.add(id); else set.delete(id);
      state.compare.ids = [...set];
      paint();
      refocusCompare(id);
      return;
    }
    // 用户开始修正时清掉上一条弹窗错误与 aria-invalid，避免提示残留
    if (event.type === 'input' && target.matches('[data-pf-form] input, [data-pf-form] select, [data-pf-form] textarea')) {
      if (target.hasAttribute('aria-invalid')) target.removeAttribute('aria-invalid');
      const err = root?.querySelector('[data-pf-dialog-err]');
      if (err && !err.hidden) { err.hidden = true; err.innerHTML = ''; }
    }
  }

  /** 原生 required 校验不触发 submit，这里把首个无效字段的原因同步到弹窗错误区。 */
  function onInvalid(event) {
    if (!state.editor) return;
    const fieldNode = event.target;
    if (!fieldNode?.matches?.('input, select, textarea')) return;
    fieldNode.setAttribute('aria-invalid', 'true');
    setDialogError(fieldNode.validationMessage || '此项为必填项。');
  }

  function onEditorClose() {
    state.editor = null;
  }

  function onConfirmClose() {
    const dialog = root?.querySelector('[data-pf-confirm]');
    if (!dialog) return;
    dialog.returnValue = '';
    state.pendingConfirm = null;
  }

  function bind(node) {
    if (bound === node) return;
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('submit', onSubmit);
    node.addEventListener('input', onInput);
    node.addEventListener('change', onInput);
    // invalid 不冒泡，必须用捕获阶段才能在委托节点上收到
    node.addEventListener('invalid', onInvalid, true);
    node.querySelector('[data-pf-editor]')?.addEventListener('close', onEditorClose);
    node.querySelector('[data-pf-confirm]')?.addEventListener('close', onConfirmClose);
  }

  function unbind(node) {
    if (!node) return;
    node.removeEventListener('click', onClick);
    node.removeEventListener('submit', onSubmit);
    node.removeEventListener('input', onInput);
    node.removeEventListener('change', onInput);
    node.removeEventListener('invalid', onInvalid, true);
    node.querySelector('[data-pf-editor]')?.removeEventListener('close', onEditorClose);
    node.querySelector('[data-pf-confirm]')?.removeEventListener('close', onConfirmClose);
    if (bound === node) bound = null;
  }

  function mount(node) {
    if (!node) return;
    if (root && root !== node) {
      unbind(root);
      controller?.abort();
    }
    root = node;
    root.innerHTML = html();
    bind(root);
    load();
  }

  function dispose() {
    disposed = true;
    generation += 1;
    controller?.abort();
    controller = null;
    unbind(root);
    root = null;
  }

  return {
    html,
    render: html,
    mount,
    bind,
    dispose,
    rerender: paint,
    load,
    get root() { return root; },
    get disposed() { return disposed; },
    state,
  };
}

/* 稳定入口：lead 直接 import { render } from './profiles.js' 后 render(container, ctx)。 */
let singleton = null;
export function render(container, ctx = {}) {
  if (!container) return null;
  if (singleton && singleton.root !== container) singleton.dispose();
  if (!singleton || singleton.disposed) singleton = createProfilesPage(ctx);
  singleton.mount(container, ctx);
  return singleton;
}

export default createProfilesPage;
