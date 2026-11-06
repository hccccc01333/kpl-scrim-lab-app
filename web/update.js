const CHECK_DELAY = 1800;
const DISMISS_KEY = 'kpl-update-dismissed';
const state = {version: '', card: null, busy: false};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function action(label, className, onClick) {
  const node = el('button', `kpl-update-btn ${className}`, label);
  node.type = 'button';
  node.addEventListener('click', onClick);
  return node;
}

function closeCard() {
  if (state.card) {
    state.card.remove();
    state.card = null;
  }
}

function setStatus(node, message, isError = false) {
  node.textContent = message || '';
  node.classList.toggle('is-error', Boolean(isError));
}

function makeCard(title) {
  closeCard();
  const card = el('section', 'kpl-update-card');
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', title);

  const head = el('div', 'kpl-update-head');
  head.append(el('h2', '', title));
  const close = el('button', 'kpl-update-close', '×');
  close.type = 'button';
  close.setAttribute('aria-label', '关闭更新提示');
  close.addEventListener('click', () => {
    const version = card.dataset.version;
    if (version) sessionStorage.setItem(DISMISS_KEY, version);
    closeCard();
  });
  head.append(close);

  const body = el('div', 'kpl-update-body');
  const status = el('p', 'kpl-update-status');
  body.append(status);
  const actions = el('div', 'kpl-update-actions');
  card.append(head, body, actions);
  document.body.append(card);
  state.card = card;
  return {card, body, status, actions};
}

function notesList(notes) {
  const list = el('ul', 'kpl-update-notes');
  const items = Array.isArray(notes) ? notes : [];
  if (!items.length) items.push('本次更新包含若干修复与优化。');
  for (const note of items) list.append(el('li', '', String(note)));
  return list;
}

function renderVersion(version) {
  if (!version) return;
  let node = document.querySelector('.kpl-version');
  if (!node) {
    node = el('span', 'kpl-version');
    document.body.append(node);
  }
  node.textContent = `v${version}`;
  node.title = `当前版本 v${version}，点击检查更新`;
  node.setAttribute('role', 'button');
  node.tabIndex = 0;
  if (!node.dataset.bound) {
    node.dataset.bound = '1';
    const trigger = () => check(true);
    node.addEventListener('click', trigger);
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        trigger();
      }
    });
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const detail = data && (typeof data.detail === 'string' ? data.detail : data.reason);
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return data;
}

function showFailure(result) {
  const {body, actions} = makeCard('上次更新未完成');
  body.append(el('p', 'kpl-update-meta', result?.message || '更新失败，当前仍在运行旧版本。'));
  actions.append(action('知道了', 'primary', closeCard));
}

function showPending(pending) {
  const {card, body, status, actions} = makeCard('更新已准备');
  card.dataset.version = pending.version || '';
  body.append(el('p', 'kpl-update-meta',
    `v${pending.version} 已下载并通过校验。重启工作台后生效，data 目录不会被修改。`));
  if (pending.notes?.length) body.append(notesList(pending.notes));

  const restart = action('立即重启', 'primary', restartNow);
  const later = action('稍后', 'ghost', closeCard);
  actions.append(restart, later);
  setStatus(status, `共 ${pending.fileCount || 0} 个文件待应用。`);
}

function showUpdate(data) {
  const {card, body, status, actions} = makeCard(`发现新版本 v${data.latestVersion}`);
  card.dataset.version = data.latestVersion;

  const meta = [`当前 v${data.currentVersion}`];
  if (data.publishedAt) meta.push(`发布于 ${String(data.publishedAt).slice(0, 10)}`);
  body.append(el('p', 'kpl-update-meta', meta.join(' · ')));
  body.append(notesList(data.notes));

  if (data.blocked) {
    body.append(el('p', 'kpl-update-warning',
      `当前版本过旧，需要先升级到 v${data.minVersion}。请下载完整包。`));
    if (data.full?.url) {
      const link = el('a', 'kpl-update-btn primary', '下载完整包');
      link.href = data.full.url;
      link.target = '_blank';
      link.rel = 'noopener';
      actions.append(link);
    }
    actions.append(action('稍后', 'ghost', closeCard));
    setStatus(status, '增量更新不可用。');
    return;
  }

  if (!data.patch && data.full?.url) {
    body.append(el('p', 'kpl-update-warning',
      '该版本只提供完整包，下载后解压覆盖程序文件即可，data 目录请保留。'));
    const link = el('a', 'kpl-update-btn primary', '下载完整包');
    link.href = data.full.url;
    link.target = '_blank';
    link.rel = 'noopener';
    actions.append(link, action('稍后', 'ghost', closeCard));
    setStatus(status, '没有可用的增量包。');
    return;
  }

  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.zip,application/zip';
  fileInput.className = 'kpl-update-file';
  fileInput.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    fileInput.value = '';
    if (file) stageLocal(file, status, data.currentVersion);
  });

  const apply = action('立即更新', 'primary', () => applyOnline(status));
  const local = action('选择本地更新包', 'secondary', () => fileInput.click());
  const later = action('稍后', 'ghost', () => {
    sessionStorage.setItem(DISMISS_KEY, data.latestVersion);
    closeCard();
  });
  actions.append(apply, local, later, fileInput);
  setStatus(status, data.stale ? '更新检查使用了本地缓存。' : '');
}

async function applyOnline(status) {
  if (state.busy) return;
  state.busy = true;
  setStatus(status, '正在下载增量包…');
  let response;
  try {
    response = await fetch('/api/update/apply', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}',
    });
  } catch (error) {
    setStatus(status, '服务正在重启，页面会自动刷新…');
    await waitForRestart(state.version);
    state.busy = false;
    return;
  }
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = typeof payload.detail === 'string' ? payload.detail : '';
    } catch (error) {
      detail = '';
    }
    setStatus(status, detail || `更新请求失败（${response.status}）`, true);
    state.busy = false;
    return;
  }
  setStatus(status, '正在重启，页面会自动刷新…');
  await waitForRestart(state.version);
  state.busy = false;
}

async function stageLocal(file, status, currentVersion) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    setStatus(status, '请选择 .zip 格式的更新包。', true);
    return;
  }
  if (file.size > 120 * 1024 * 1024) {
    setStatus(status, '更新包超过 120 MB。', true);
    return;
  }
  setStatus(status, '正在校验更新包…');
  try {
    const data = await api('/api/update/stage', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/zip',
        'X-Filename': encodeURIComponent(file.name),
      },
      body: file,
    });
    if (data?.pending) {
      showPending(data.pending);
    } else {
      setStatus(status, '更新包已通过校验，但未生成待应用记录。', true);
    }
  } catch (error) {
    setStatus(status, error.message || '更新包校验失败。', true);
  }
}

async function restartNow() {
  if (state.busy) return;
  state.busy = true;
  const card = state.card;
  const status = card?.querySelector('.kpl-update-status');
  try {
    const response = await fetch('/api/update/restart', {method: 'POST'});
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = typeof payload.detail === 'string' ? payload.detail : '';
      } catch (error) {
        detail = '';
      }
      if (status) setStatus(status, detail || '没有待应用的更新。', true);
      state.busy = false;
      return;
    }
  } catch (error) {
    // The server normally exits before the response is read.
  }
  if (status) setStatus(status, '正在重启，页面会自动刷新…');
  await waitForRestart(state.version);
  state.busy = false;
}

async function waitForRestart(oldVersion) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    await sleep(1500);
    try {
      const health = await api('/api/health');
      if (health?.version && health.version !== oldVersion) {
        window.location.reload();
        return;
      }
    } catch (error) {
      // Still restarting; keep polling.
    }
  }
  const card = state.card;
  const status = card?.querySelector('.kpl-update-status');
  if (status) setStatus(status, '更新可能需要更长时间，请手动刷新页面。', true);
}

async function check(force = false) {
  if (!navigator.onLine) return;
  let data;
  try {
    data = await api(`/api/update/check${force ? '?force=1' : ''}`);
  } catch (error) {
    return;
  }
  if (!data?.ok) return;
  state.version = data.currentVersion || state.version;
  renderVersion(state.version);
  if (data.pending) {
    showPending(data.pending);
    return;
  }
  if (!data.updateAvailable && !data.blocked) return;
  if (!force && sessionStorage.getItem(DISMISS_KEY) === data.latestVersion) return;
  showUpdate(data);
}

async function init() {
  let health = null;
  try {
    health = await api('/api/health');
  } catch (error) {
    health = null;
  }
  if (health?.version) {
    state.version = health.version;
    renderVersion(health.version);
  }

  let status = null;
  try {
    status = await api('/api/update/status');
  } catch (error) {
    status = null;
  }
  if (status?.pending) {
    showPending(status.pending);
    return;
  }
  if (status?.lastResult && status.lastResult.ok === false) {
    showFailure(status.lastResult);
  }
  setTimeout(() => check(), CHECK_DELAY);
  window.addEventListener('online', () => check(true));
}

window.KPLUpdate = {check};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init, {once: true});
} else {
  init();
}
