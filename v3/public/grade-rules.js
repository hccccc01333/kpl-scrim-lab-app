/* 评级规则设置页（2026-11）
 *
 * 赛训组自己维护「分路 × 字段」的 4 档评级阈值：卓越 / 优秀 / 达标 / 待提升。
 * 规则优先级最高——保存后，对局复盘的选手字段评级与经济档位都按这里取数。
 * 数据来自 GET/POST /api/v3/grade-rules，沿用 combo-pool 的 revision 乐观锁。
 *
 * 外壳（app.js）只给挂载点：<div data-gr-root></div>
 */
import { glyph } from './ui-icons.js';
import { currentCompetitionId, currentCompetitionName, saveSnapshot } from './rule-snapshots.js?v=20261124snap';

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

const text = (value) => String(value ?? '').trim();
const defaultEsc = (value) => text(value).replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

const LEVELS = [
  { level: 'elite', label: '卓越' },
  { level: 'good', label: '优秀' },
  { level: 'pass', label: '达标' },
  { level: 'low', label: '待提升' },
];
const SUBJECTS = [
  { key: '对抗路', label: '对抗路' },
  { key: '发育路', label: '发育路' },
  { key: '中路', label: '中路' },
  { key: '打野·坦野', label: '打野 · 坦野' },
  { key: '打野·野核', label: '打野 · 野核' },
  { key: '游走', label: '游走（辅助）' },
];
export function createGradeRulesPage(h = {}) {
  const esc = h.esc || defaultEsc;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const LIST_URL = `${API_BASE}/api/v3/grade-rules`;
  const uid = 'gr-' + Math.random().toString(36).slice(2, 9);

  let root = null;
  let controller = null;
  let generation = 0;
  let liveNode = null;
  let bound = null;
  let defaults = null;             // 服务端返回的默认文档快照，供「恢复默认」用

  const state = { ready: false, loading: false, revision: 0, updatedAt: '', subjects: {}, saved: false };
  const ui = { subject: '游走', saving: false, notice: '', error: false, draft: null, onlyActive: false };

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
    ui.notice = text(message);
    ui.error = Boolean(error);
    paintStatus();
    if (!quiet && ui.notice) announce(ui.notice);
  }

  /* ── 数据 ─────────────────────────────────────────────────────────── */
  function applyPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    state.revision = Number(payload.revision) || 0;
    state.updatedAt = text(payload.updatedAt);
    state.subjects = payload.subjects && typeof payload.subjects === 'object' ? payload.subjects : {};
    state.saved = Boolean(payload.saved);
    // 服务端显式下发内置默认档位；保存过后 state.subjects 是上次保存值，不能当默认。
    if (!defaults) defaults = JSON.parse(JSON.stringify(payload.defaults || state.subjects));
    ui.draft = JSON.parse(JSON.stringify(state.subjects));
  }
  async function load({ quiet = false, keepNotice = false } = {}) {
    if (!root) return;
    const gen = ++generation;
    state.loading = true;
    if (!keepNotice) setNotice('正在读取评级规则…', { quiet: true });
    try {
      const response = await fetch(LIST_URL, { headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller?.signal });
      if (!response.ok) throw new Error(`读取评级规则失败（${response.status}）`);
      const payload = await response.json();
      if (gen !== generation || !root) return;
      applyPayload(payload);
      state.ready = true;
      paintAll();
      if (!quiet) {
        const total = Object.values(state.subjects).reduce((n, fields) => n + Object.keys(fields || {}).length, 0);
        const active = Object.values(state.subjects).reduce(
          (n, fields) => n + Object.values(fields || {}).filter((r) => r.active !== false).length, 0);
        setNotice(state.saved ? `规则已读取：修订 ${state.revision}，${total} 个字段（${active} 个生效）。`
          : `已载入内置默认规则：${total} 个字段（${active} 个生效，其余列出但默认不生效）。改完点保存才会生效。`);
      }
      else if (!keepNotice) setNotice('', { quiet: true });
    } catch (error) {
      if (gen !== generation || !root || keepNotice) return;
      setNotice(error.message || '评级规则读取失败，请点「重新读取」重试。', { error: true });
    } finally {
      if (gen === generation) state.loading = false;
    }
  }
  async function save() {
    if (ui.saving || !ui.draft) return false;
    /* 保存前校验全部阈值：非数字 / 档位顺序错误都阻止提交，聚焦首个错误。 */
    if (!validateAll()) {
      setNotice('有阈值填写不正确或档位顺序颠倒，请检查标红的输入后再保存。', { error: true });
      return false;
    }
    ui.saving = true;
    paintFoot();
    try {
      const response = await fetch(LIST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ revision: state.revision, subjects: ui.draft }),
      });
      if (response.status === 409) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || '保存冲突：规则已被其他人修改，请点「重新读取」后再试。');
      }
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(text(detail.detail) || `保存失败（${response.status}）`);
      }
      const payload = await response.json().catch(() => ({}));
      state.revision = Number(payload.revision) || state.revision + 1;
      state.updatedAt = text(payload.updatedAt) || new Date().toISOString();
      state.subjects = JSON.parse(JSON.stringify(ui.draft));
      state.saved = true;
      setNotice(`规则已保存并生效（修订 ${state.revision}）。`);
      document.dispatchEvent(new CustomEvent('grade-rules:saved'));
      return true;
    } catch (error) {
      setNotice(error.message || '保存失败，请稍后重试。', { error: true });
      return false;
    } finally {
      ui.saving = false;
      paintFoot();
    }
  }

  /** 先把草稿保存并生效，再把整份评级规则打包到当前赛事快照。 */
  async function snapshotCurrent() {
    const compId = currentCompetitionId();
    if (!compId) { setNotice('请先在顶栏选择赛事，再保存快照。', { error: true }); return; }
    if (!(await save())) return;
    try {
      const result = await saveSnapshot('grade_rules', compId, '规则设置 · 赛事快照', API_BASE);
      setNotice(`已把评级规则存到「${currentCompetitionName() || compId}」快照（第 ${result.revision} 版）。`);
    } catch (error) {
      setNotice(error.message || '赛事快照保存失败。', { error: true });
    }
  }

  /* ── 草稿编辑 ─────────────────────────────────────────────────────── */
  function fieldsOf(subject) {
    // 字段顺序完全由后端规则文档决定（已列全 FIELDS），前端不再硬编码清单。
    return Object.keys(ui.draft?.[subject] || {});
  }
  function activeCount(subject) {
    return Object.values(ui.draft?.[subject] || {}).filter((r) => r?.active !== false).length;
  }
  function setActive(subject, field, checked) {
    const rule = ui.draft?.[subject]?.[field];
    if (!rule) return;
    rule.active = Boolean(checked);
    const row = root?.querySelector(`[data-gr-active="${field}"]`)?.closest('tr');
    row?.classList.toggle('is-off', !rule.active);
    paintTabs(); paintFoot();
  }
  function setAllActive(checked) {
    const fields = ui.draft?.[ui.subject] || {};
    Object.values(fields).forEach((rule) => { rule.active = Boolean(checked); });
    paintTable(); paintTabs(); paintFoot();
    announce(`「${SUBJECTS.find((s) => s.key === ui.subject)?.label || ui.subject}」已${checked ? '全部勾选生效' : '全部取消生效'}（还没保存）`);
  }
  function setThreshold(subject, field, index, value) {
    const rule = ui.draft?.[subject]?.[field];
    if (!rule || !Array.isArray(rule.thresholds)) return;
    const number = Number(value);
    if (!Number.isFinite(number)) return;
    rule.thresholds[index] = number;
  }
  function resetSubject() {
    if (!defaults?.[ui.subject]) return;
    ui.draft[ui.subject] = JSON.parse(JSON.stringify(defaults[ui.subject]));
    paintTable();
    setNotice(`「${SUBJECTS.find((s) => s.key === ui.subject)?.label || ui.subject}」已恢复默认阈值（还没保存）。`);
  }
  function dirty() {
    return JSON.stringify(ui.draft) !== JSON.stringify(state.subjects);
  }

  /* ── 渲染 ─────────────────────────────────────────────────────────── */
  const SUBJECT_ICON = ['shield', 'pick', 'heroes', 'bp', 'compare', 'coach'];
  function subjectTabs() {
    return SUBJECTS.map((s, i) => {
      const count = Object.keys(ui.draft?.[s.key] || {}).length;
      const on = activeCount(s.key);
      return `<button type="button" class="gr-subject${s.key === ui.subject ? ' is-on' : ''}"
        data-gr-subject="${esc(s.key)}" aria-pressed="${s.key === ui.subject}">${glyph(SUBJECT_ICON[i] || 'heroes', { size: 16 })}${esc(s.label)}<span class="gr-tab-count" title="${on} 个生效 / 共 ${count} 个字段">${on}/${count}</span></button>`;
    }).join('');
  }
  function paintTabs() {
    root?.querySelectorAll('[data-gr-subject]').forEach((node) => {
      const key = node.dataset.grSubject;
      const on = key === ui.subject;
      node.setAttribute('aria-pressed', String(on));
      node.classList.toggle('is-on', on);
      // 字段数由后端数据决定，load 完成后补画（首屏 html() 时 draft 还没到）。
      const count = Object.keys(ui.draft?.[key] || {}).length;
      const active = activeCount(key);
      const badge = node.querySelector('.gr-tab-count');
      if (badge) {
        badge.textContent = `${active}/${count}`;
        badge.title = `${active} 个生效 / 共 ${count} 个字段`;
      }
    });
  }
  function paintTable() {
    const body = root?.querySelector('[data-gr-tbody]');
    if (!body || !ui.draft) return;
    const subject = ui.subject;
    const allFields = fieldsOf(subject);
    if (!allFields.length) {
      body.innerHTML = '<tr><td colspan="7" class="gr-empty">这个评分主体还没有字段。请点「恢复本分路默认」。</td></tr>';
      return;
    }
    const fields = ui.onlyActive
      ? allFields.filter((field) => ui.draft[subject][field]?.active !== false)
      : allFields;
    body.innerHTML = fields.map((field) => {
      const rule = ui.draft[subject][field];
      const down = rule.direction === 'down';
      const label = rule.label || field;
      const unit = rule.unit || '';
      const t = rule.thresholds || [0, 0, 0];
      const cells = levelInputs(subject, field, t);
      // 营地卡片字段没有公开基准，阈值是占位参考值，明确标注需赛训组按实战校准。
      const estimate = rule.estimate
        ? '<span class="gr-estimate" title="营地卡片无公开基准，默认阈值仅供参考，请按实战数据校准">待校准</span>' : '';
      // 英文 key 对赛训组是噪音，改显示数据来源（营地卡片 / 基础字段）。
      const source = rule.source === 'tile'
        ? '<small class="gr-src gr-src-tile">营地卡片</small>'
        : '<small class="gr-src">基础字段</small>';
      const on = rule.active !== false;
      return `<tr class="${on ? '' : 'is-off'}">
        <th scope="row">${esc(label)}${estimate}${source}</th>
        <td class="gr-active-cell"><input type="checkbox" class="gr-active" data-gr-active="${esc(field)}"
          ${on ? 'checked' : ''} aria-label="启用字段「${esc(label)}」"><span class="visually-hidden">${on ? '已生效' : '未生效'}</span></td>
        <td><span class="gr-dir ${down ? 'is-down' : 'is-up'}" title="${down ? '数值越低越好' : '数值越高越好'}">${down ? '↓ 越低越好' : '↑ 越高越好'}</span></td>
        ${cells}
        <td><span class="gr-unit">${esc(unit)}</span></td>
      </tr>`;
    }).join('');
    const title = root.querySelector('[data-gr-subject-title]');
    if (title) title.textContent = SUBJECTS.find((s) => s.key === ui.subject)?.label || ui.subject;
    const toggle = root.querySelector('[data-gr-only-active]');
    if (toggle) toggle.checked = ui.onlyActive;
    const toggleLabel = root.querySelector('[data-gr-only-active-label]');
    if (toggleLabel) toggleLabel.textContent = `只看生效 (${activeCount(subject)}/${allFields.length})`;
  }
  function levelInputs(subject, field, thresholds) {
    return LEVELS.slice(0, 3).map((lv, i) => {
      const id = `${uid}-${subject}-${field}-${lv.level}`.replace(/[^\w-]/g, '-');
      return `<td><label class="visually-hidden" for="${id}">${esc(lv.label)}阈值</label>
        <input id="${id}" type="text" inputmode="decimal" data-gr-th="${esc(field)}" data-gr-index="${i}"
          value="${esc(thresholds[i])}" aria-invalid="false"></td>`;
    }).join('');
  }
  function paintStatus() {
    const node = root?.querySelector('[data-gr-status]');
    if (!node) return;
    node.textContent = ui.notice;
    node.classList.toggle('is-error', ui.error);
    node.hidden = !ui.notice;
  }
  function paintFoot() {
    const save = root?.querySelector('[data-gr-save]');
    if (save) {
      save.disabled = ui.saving || !dirty();
      save.innerHTML = `${glyph('pick', { size: 18 })}<span>${ui.saving ? '保存中…' : '保存并生效'}</span>`;
    }
    const reset = root?.querySelector('[data-gr-reset]');
    if (reset) reset.disabled = ui.saving;
    const rev = root?.querySelector('[data-gr-rev]');
    if (rev) {
      rev.textContent = state.saved ? '已保存' : '内置默认 · 尚未保存';
      rev.classList.toggle('is-saved', state.saved);
    }
  }
  function paintAll() {
    paintTabs(); paintTable(); paintStatus(); paintFoot();
  }

  /* ── 页面骨架：静态标记 + 事件委托，无内联脚本 ───────────────────── */
  function html() {
    return `<div class="gr-page">
      <section class="section gr-lead">
        <div class="section-heading"><div><h1>规则设置</h1></div>
          <div class="gr-lead-actions">
            <button type="button" class="control" data-gr-snapshot>${glyph('export', { size: 18 })}存为当前赛事快照</button>
            <button type="button" class="control" data-gr-reload>${glyph('refresh', { size: 18 })}重新读取</button>
          </div></div>
        <span class="gr-rev" data-gr-rev></span>
        <p class="gr-status" data-gr-status hidden></p>
      </section>

      <section class="section gr-editor">
        <div class="gr-toolbar">
          <div class="gr-subjects" role="group" aria-label="选择评分主体">${subjectTabs()}</div>
          <div class="gr-toolbar-actions">
            <label class="gr-only-active"><input type="checkbox" data-gr-only-active><span data-gr-only-active-label>只看生效</span></label>
            <button type="button" class="control" data-gr-all-on>${glyph('pick', { size: 18 })}本分路全选</button>
            <button type="button" class="control" data-gr-all-off>${glyph('ban', { size: 18 })}全部取消</button>
          </div>
        </div>
        <div class="gr-table-wrap" tabindex="0" role="region" aria-labelledby="${uid}-table-cap">
          <table class="gr-table">
            <caption id="${uid}-table-cap" class="visually-hidden"><span data-gr-subject-title>游走</span> 的评级阈值</caption>
            <thead><tr>
              <th scope="col">字段</th><th scope="col" title="勾上才生效">生效</th><th scope="col">方向</th>
              <th scope="col"><span class="gr-lv gr-lv-elite">卓越</span></th>
              <th scope="col"><span class="gr-lv gr-lv-good">优秀</span></th>
              <th scope="col"><span class="gr-lv gr-lv-pass">达标</span></th>
              <th scope="col">单位</th>
            </tr></thead>
            <tbody data-gr-tbody></tbody>
          </table>
        </div>
        <div class="gr-foot">
          <button type="button" class="control" data-gr-reset>${glyph('refresh', { size: 18 })}恢复本分路默认</button>
          <button type="button" class="primary" data-gr-save disabled>${glyph('pick', { size: 18 })}<span>保存并生效</span></button>
        </div>
      </section>
    </div>`;
  }

  /* ── 事件 ─────────────────────────────────────────────────────────── */
  function onClick(event) {
    const tab = event.target.closest('[data-gr-subject]');
    if (tab) {
      ui.subject = text(tab.dataset.grSubject);
      paintTabs(); paintTable();
      announce(`已切换到${SUBJECTS.find((s) => s.key === ui.subject)?.label || ui.subject}`);
      return;
    }
    if (event.target.closest('[data-gr-reload]')) { load(); return; }
    if (event.target.closest('[data-gr-snapshot]')) { snapshotCurrent(); return; }
    if (event.target.closest('[data-gr-all-on]')) { setAllActive(true); return; }
    if (event.target.closest('[data-gr-all-off]')) { setAllActive(false); return; }
    if (event.target.closest('[data-gr-reset]')) { resetSubject(); paintFoot(); return; }
    if (event.target.closest('[data-gr-save]')) { save(); return; }
  }
  function onInput(event) {
    const input = event.target.closest('[data-gr-th]');
    if (!input) return;
    // 输入时只更新草稿、清错误，不重画表格（避免丢焦点/光标）；保存时才校验数值。
    setThreshold(ui.subject, text(input.dataset.grTh), Number(input.dataset.grIndex), input.value);
    if (ui.error) setNotice('', { quiet: true });
    paintFoot();
  }
  /* 单个阈值输入的校验：非空数字 + 档位顺序（up 递减 / down 递增由方向决定）。
     视觉用 .is-invalid，程序态用 aria-invalid，二者同步（见 accessible-error-announcement）。 */
  function validateInput(input) {
    const field = text(input.dataset.grTh);
    const index = Number(input.dataset.grIndex);
    const rule = ui.draft?.[ui.subject]?.[field];
    const number = Number(input.value);
    let bad = text(input.value) === '' || !Number.isFinite(number);
    if (!bad && rule) {
      // 同一行的三档按 index 相邻比较：up 要求 t0≥t1≥t2；down 要求 t0≤t1≤t2。
      const row = input.closest('tr');
      const siblings = row ? [...row.querySelectorAll('[data-gr-th]')] : [];
      const values = siblings.map((n) => text(n.value) === '' ? NaN : Number(n.value));
      const down = rule.direction === 'down';
      if (index > 0 && Number.isFinite(values[index - 1])) {
        bad = down ? values[index - 1] > number : values[index - 1] < number;
      }
      if (index < 2 && Number.isFinite(values[index + 1])) {
        bad = bad || (down ? number > values[index + 1] : number < values[index + 1]);
      }
    }
    input.classList.toggle('is-invalid', Boolean(bad));
    input.setAttribute('aria-invalid', bad ? 'true' : 'false');
    return !bad;
  }
  function validateAll() {
    if (!root) return true;
    // 未勾选生效的字段不参与评级口径，阈值留空也不拦保存。
    const inputs = [...root.querySelectorAll('[data-gr-th]')].filter((input) => {
      const field = text(input.dataset.grTh);
      return ui.draft?.[ui.subject]?.[field]?.active !== false;
    });
    const bad = inputs.filter((input) => !validateInput(input));
    if (bad.length) {
      bad[0].focus();
      return false;
    }
    // 阈值顺序要对整个草稿负责：当前只渲染一个主体，但保存会一次写入所有主体。
    // up 档位必须 elite≥good≥pass，down 必须 elite≤good≤pass，和后端 _valid 一致。
    for (const [subject, fields] of Object.entries(ui.draft || {})) {
      for (const [field, rule] of Object.entries(fields || {})) {
        if (!rule || rule.active === false) continue;
        const ts = rule.thresholds;
        if (!Array.isArray(ts) || ts.length !== 3
            || !ts.every((v) => Number.isFinite(Number(v)))) continue; // 格式问题由上面的输入校验管
        const [a, b, c] = ts.map(Number);
        const ok = rule.direction === 'down' ? (a <= b && b <= c) : (a >= b && b >= c);
        if (ok) continue;
        if (subject === ui.subject) {
          root.querySelector(`[data-gr-th="${field}"]`)?.focus();
        }
        setNotice(`${subject} · ${field} 的阈值顺序与档位方向不符（${rule.direction === 'down' ? '卓越应≤达标' : '卓越应≥达标'}）`, { error: true });
        return false;
      }
    }
    return true;
  }
  function onChange(event) {
    const active = event.target.closest('[data-gr-active]');
    if (active) {
      setActive(ui.subject, text(active.dataset.grActive), active.checked);
      return;
    }
    const only = event.target.closest('[data-gr-only-active]');
    if (only) {
      ui.onlyActive = Boolean(only.checked);
      paintTable();
      return;
    }
    const input = event.target.closest('[data-gr-th]');
    if (!input) return;
    validateInput(input);
    if (!input.classList.contains('is-invalid') && ui.error) setNotice('', { quiet: true });
  }
  function onBlur(event) {
    const input = event.target.closest('[data-gr-th]');
    if (input) validateInput(input);
  }
  const onSnapshotRestored = (event) => {
    if (event.detail?.module === 'grade_rules') load({ quiet: true });
  };
  function bind(node) {
    if (bound === node) return;
    document.addEventListener('rule-snapshots:restored', onSnapshotRestored);
    if (bound) dispose();
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('input', onInput);
    node.addEventListener('change', onChange);
    node.addEventListener('focusout', onBlur);
  }
  function dispose() {
    document.removeEventListener('rule-snapshots:restored', onSnapshotRestored);
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('input', onInput);
      bound.removeEventListener('change', onChange);
      bound.removeEventListener('focusout', onBlur);
      bound = null;
    }
    controller?.abort();
    controller = null;
    root = null;
    defaults = null;
    ui.draft = null;
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
    load();
  }
  function rerender() { paintAll(); }

  return { html, render: html, mount, bind, dispose, rerender, state, announce };
}

export default createGradeRulesPage;
