/* 赛训组配置工具（2026-11）：导出 JSON / 导入 JSON / 变更历史 / 未保存提醒。
 * 组合池设置页与规则设置页共用；外壳只给一个挂载点与当前状态快照的 getter。
 *
 * 用法：
 *   const tools = createConfigTools({
 *     configName: 'combo_pool' | 'grade_rules',
 *     API_BASE, esc, icon, notify,
 *     getDoc: () => ({...当前草稿}),   // 导出用
 *     onImport: (doc) => {...},        // 导入成功后把数据灌进页面草稿
 *     onRollback: (doc) => {...},      // 回滚成功后把数据灌进页面草稿
 *     isDirty: () => bool,             // 未保存提醒用
 *   });
 *   root.innerHTML = tools.html(); tools.mount(root);
  *   // 可选（赛训规则中心复用）：historyUrl / rollbackUrl / exportName / title / label / expect
 */
const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const defaultEsc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

export function createConfigTools(h = {}) {
  const esc = h.esc || defaultEsc;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const configName = h.configName;
  // 赛训规则中心复用：可覆盖历史/回滚地址、导出文件名、展示名与导入校验字段。
  // 不传时行为与组合池/评级规则完全一致。
  const historyUrl = h.historyUrl ?? `${API_BASE}/api/v3/config-history/${encodeURIComponent(configName)}`;
  const rollbackUrl = h.rollbackUrl ?? `${historyUrl}/rollback`;
  const exportName = h.exportName ?? configName ?? 'config';
  const sectionTitle = h.title ?? '配置管理';
  const sectionLabel = h.label ?? (configName === 'combo_pool' ? '组合池'
    : configName === 'grade_rules' ? '评级规则' : String(exportName));
  const getDoc = typeof h.getDoc === 'function' ? h.getDoc : () => ({});
  const onImport = typeof h.onImport === 'function' ? h.onImport : () => {};
  const onRollback = typeof h.onRollback === 'function' ? h.onRollback : () => {};
  const isDirty = typeof h.isDirty === 'function' ? h.isDirty : () => false;
  const uid = 'cfg-' + Math.random().toString(36).slice(2, 9);

  const HISTORY_URL = historyUrl;
  const ROLLBACK_URL = rollbackUrl;
  let root = null;
  let controller = null;
  let entries = [];
  let pendingRollback = null;   // {id, revision} 二次确认

  function announce(msg) { if (notify) notify(msg); }
  function setNotice(msg, error = false) {
    if (!root) return;
    const node = root.querySelector('[data-cfg-status]');
    if (!node) return;
    node.textContent = msg || '';
    node.classList.toggle('is-error', error);
    node.hidden = !msg;
    if (msg) announce(msg);
  }

  async function loadHistory() {
    if (!root) return;
    try {
      const response = await fetch(HISTORY_URL, { headers: { Accept: 'application/json' },
        cache: 'no-store', signal: controller?.signal });
      if (!response.ok) throw new Error(`读取变更历史失败（${response.status}）`);
      const payload = await response.json();
      entries = Array.isArray(payload.entries) ? payload.entries : [];
      paintHistory();
      if (typeof h.onHistoryLoaded === 'function') h.onHistoryLoaded(entries);
    } catch (error) {
      if (error.name !== 'AbortError') setNotice(error.message || '变更历史读取失败。', true);
    }
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    // 本地时间，秒级
    return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function paintHistory() {
    const list = root?.querySelector('[data-cfg-history]');
    if (!list) return;
    if (!entries.length) {
      list.innerHTML = '<li class="cfg-empty">还没有变更记录。保存一次配置后这里会显示历史。</li>';
      return;
    }
    list.innerHTML = entries.map((e) => `<li class="cfg-entry">
      <span class="cfg-entry-meta"><time datetime="${esc(e.at)}">${esc(fmtTime(e.at))}</time><span class="cfg-entry-rev">修订 ${esc(e.revision)}</span></span>
      <span class="cfg-entry-summary">${esc(e.summary)}</span>
      <button type="button" class="control cfg-rollback" data-cfg-rollback="${esc(e.id)}"
        aria-label="回滚到 ${esc(fmtTime(e.at))} 的版本">回滚</button>
    </li>`).join('');
    const confirm = root.querySelector('[data-cfg-rollback-confirm]');
    if (confirm) confirm.hidden = !pendingRollback;
    const label = root.querySelector('[data-cfg-rollback-label]');
    if (label && pendingRollback) label.textContent = `确认回滚到「${pendingRollback.summary}」？当前未保存的修改会丢失。`;
  }

  function exportJson() {
    const doc = getDoc();
    if (!doc || !Object.keys(doc).length) { setNotice('当前没有可导出的配置。', true); return; }
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${exportName}-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(`已导出 ${a.download}。`);
  }

  async function onFileChosen(event) {
    const input = event.target.closest('[data-cfg-import]');
    if (!input) return;
    const file = input.files?.[0];
    input.value = '';   // 允许重复导入同一文件
    if (!file) return;
    try {
      const text = await file.text();
      const doc = JSON.parse(text);
      if (!doc || typeof doc !== 'object') throw new Error('文件内容不是有效的 JSON 对象');
      // 默认字段与旧行为一致；规则中心通过 expect 指定自己的数据字段（数组或对象均可）。
      const expected = Object.hasOwn(h, 'expect') ? h.expect
        : (configName === 'combo_pool' ? 'pairs' : 'subjects');
      const fields = Array.isArray(expected) ? expected : [expected];
      if (fields.length && !fields.some((field) => Array.isArray(doc[field])
          || (doc[field] && typeof doc[field] === 'object'))) {
        throw new Error(`文件缺少 ${fields.join(' / ')} 字段，可能不是${sectionLabel}配置`);
      }
      onImport(doc);
      setNotice(`已读取 ${file.name}，内容已填入编辑区，请检查后点保存。`);
    } catch (error) {
      setNotice(`导入失败：${error.message || '文件格式不正确'}`, true);
    }
  }

  async function confirmRollback() {
    if (!pendingRollback) return;
    setNotice('正在回滚…');
    try {
      const response = await fetch(ROLLBACK_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ revision: pendingRollback.revision, entryId: pendingRollback.id }),
      });
      if (response.status === 409) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || '配置已被其他人更新，请刷新后再试。');
      }
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `回滚失败（${response.status}）`);
      }
      pendingRollback = null;
      paintHistory();
      // 回滚成功后让页面重新取最新配置（由调用方回调决定怎么填草稿）
      await loadHistory();
      onRollback();
      setNotice('已回滚，请检查编辑区并保存以生效。');
    } catch (error) {
      setNotice(error.message || '回滚失败，请稍后重试。', true);
    }
  }

  function onClick(event) {
    if (event.target.closest('[data-cfg-export]')) { exportJson(); return; }
    const btn = event.target.closest('[data-cfg-rollback]');
    if (btn) {
      const entry = entries.find((e) => e.id === btn.dataset.cfgRollback);
      if (!entry) return;
      pendingRollback = { id: entry.id, summary: entry.summary, revision: Number(entry.revision) || 0 };
      paintHistory();
      return;
    }
    if (event.target.closest('[data-cfg-rollback-cancel]')) {
      pendingRollback = null; paintHistory(); return;
    }
    if (event.target.closest('[data-cfg-rollback-yes]')) { confirmRollback(); return; }
    if (event.target.closest('[data-cfg-refresh-history]')) { loadHistory(); }
  }

  function onChange(event) {
    if (event.target.closest('[data-cfg-import]')) onFileChosen(event);
  }

  /* 未保存提醒：刷新/关标签走 beforeunload；hash 路由切换走 hashchange 二次确认。 */
  function beforeUnload(event) {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = '';   // 兼容旧浏览器的标准写法
  }
  let hashAtMount = null;
  let ignoreHash = false;
  function onHashChange(event) {
    if (ignoreHash) { ignoreHash = false; hashAtMount = location.hash; return; }
    if (!isDirty()) { hashAtMount = location.hash; return; }
    const target = location.hash;
    if (window.confirm('当前有未保存的修改，确定离开吗？')) {
      hashAtMount = target;   // 确认离开，放行
    } else {
      // 取消：阻止 app.js 的冒泡监听继续 load()，并回到进入本页时的路由。
      event?.stopImmediatePropagation?.();
      ignoreHash = true;
      location.hash = hashAtMount || '';
    }
  }

  function mount(node) {
    if (!node) return;
    root = node;
    hashAtMount = location.hash;
    root.addEventListener('click', onClick);
    root.addEventListener('change', onChange);
    window.addEventListener('beforeunload', beforeUnload);
    // 捕获阶段：必须在 app.js 的冒泡 hashchange（会触发 render/dispose）之前执行。
    window.addEventListener('hashchange', onHashChange, true);
    controller = new AbortController();
    loadHistory();
  }
  function dispose() {
    if (root) {
      root.removeEventListener('click', onClick);
      root.removeEventListener('change', onChange);
      root = null;
    }
    window.removeEventListener('beforeunload', beforeUnload);
    window.removeEventListener('hashchange', onHashChange, true);
    controller?.abort();
    controller = null;
  }
  function refresh() { loadHistory(); }

  function html() {
    return `<section class="section cfg-section">
      <div class="section-heading"><div><h2>${esc(sectionTitle)}</h2></div></div>
      <div class="cfg-tools">
        <button type="button" class="control" data-cfg-export>${icon('download') || '↓'} 导出 JSON</button>
        <label class="cfg-import-label control">
          ${icon('upload') || '↑'} 导入 JSON
          <input type="file" accept=".json,application/json" data-cfg-import class="visually-hidden">
        </label>
        <button type="button" class="control" data-cfg-refresh-history>刷新历史</button>
      </div>
      <p class="cfg-status" data-cfg-status hidden></p>
      <details class="cfg-history" data-cfg-history-panel>
        <summary>变更历史 <span class="cfg-history-count" data-cfg-history-count></span></summary>
        <ul class="cfg-history-list" data-cfg-history></ul>
        <div class="cfg-rollback-confirm" data-cfg-rollback-confirm hidden>
          <p data-cfg-rollback-label></p>
          <button type="button" class="control" data-cfg-rollback-cancel>取消</button>
          <button type="button" class="primary" data-cfg-rollback-yes>确认回滚</button>
        </div>
      </details>
    </section>`;
  }

  /* 供宿主页的「撤销上次修改」按钮调用：回滚到指定历史条目。 */
  async function rollbackTo(id, revision) {
    pendingRollback = { id, summary: '上一次修改', revision: Number(revision) || 0 };
    await confirmRollback();
  }

  return { html, mount, dispose, refresh, setNotice, announce, rollbackTo,
    state: { get entries() { return entries; } } };
}

export default createConfigTools;
