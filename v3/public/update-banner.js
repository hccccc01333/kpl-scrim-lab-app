/* 工作台自动更新提示。
 *
 * 页面打开后静默请求 /api/update/check：有新版就在右下角弹卡片，支持
 * 「立即更新」（服务端下载增量包 → 校验 → 替换 → 自动重启）、「选择本地更新包」
 * （离线时把 patch-*.zip 交给教练）和「稍后」。更新过程中轮询 /api/health，
 * 服务以新版本回来后自动刷新页面；失败或回滚时给出可操作提示。
 *
 * 页脚的「检查更新」随时可以手动检查；源码模式（目录里有 .git）不弹自动提示，
 * 由后端 sourceMode 标记，避免把开发者的仓库当成免安装包去覆盖。
 */

const RELEASE_PAGE = 'https://gitee.com/Rainfun42/kpl-scrim-lab-app/releases/latest';
const DISMISS_KEY = 'kpl-update-dismissed';
const LAST_CHECK_KEY = 'kpl-update-last-check';
const AUTO_CHECK_DELAY = 1500;
const CHECK_THROTTLE = 30 * 60 * 1000;
const HEALTH_TIMEOUT = 150 * 1000;
const HEALTH_INTERVAL = 1600;
const NOTE_LIMIT = 6;

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/* 只比较数字段，预发布后缀按 0 处理：足够判断“服务是否已重启到新版本”。 */
function compareVersion(a, b) {
  const parse = (value) => String(value || '')
    .replace(/^v/i, '')
    .split(/[.+-]/)
    .map((part) => {
      const number = Number.parseInt(part, 10);
      return Number.isFinite(number) ? number : 0;
    });
  const left = parse(a);
  const right = parse(b);
  for (let index = 0; index < Math.max(left.length, right.length, 1); index += 1) {
    const l = left[index] || 0;
    const r = right[index] || 0;
    if (l !== r) return l > r ? 1 : -1;
  }
  return 0;
}

function formatSize(bytes) {
  const value = Number(bytes) || 0;
  if (!value) return '';
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function initUpdateBanner({ API_BASE }) {
  const dock = document.createElement('div');
  dock.className = 'update-dock';
  dock.hidden = true;
  dock.innerHTML = `<section class="update-card" role="dialog" aria-label="工作台更新">
    <div class="update-top">
      <span class="update-kicker" data-update-kicker>发现新版本</span>
      <button type="button" class="update-close" data-update="later" aria-label="稍后再说">×</button>
    </div>
    <h2 class="update-title"><span data-update-version>新版本</span><small data-update-date></small></h2>
    <p class="update-meta" data-update-meta></p>
    <ul class="update-notes" data-update-notes hidden></ul>
    <p class="update-hint" data-update-hint hidden></p>
    <div class="update-progress" data-update-progress hidden>
      <span class="update-spinner" aria-hidden="true"></span><span data-update-progress-text></span>
    </div>
    <p class="update-error" data-update-error role="alert" hidden></p>
    <div class="update-actions" data-update-actions>
      <button type="button" class="primary" data-update="now">立即更新</button>
      <button type="button" class="control" data-update="local">选择本地更新包</button>
      <button type="button" class="update-later" data-update="later">稍后</button>
    </div>
    <p class="update-foot" data-update-foot>更新只替换程序文件，data/ 与 .env 不会被修改。</p>
    <input type="file" accept=".zip,application/zip" data-update-file hidden>
  </section>`;
  document.body.appendChild(dock);

  const toast = document.createElement('div');
  toast.className = 'update-toast';
  toast.setAttribute('role', 'status');
  toast.hidden = true;
  document.body.appendChild(toast);

  const refs = {
    kicker: dock.querySelector('[data-update-kicker]'),
    version: dock.querySelector('[data-update-version]'),
    date: dock.querySelector('[data-update-date]'),
    meta: dock.querySelector('[data-update-meta]'),
    notes: dock.querySelector('[data-update-notes]'),
    hint: dock.querySelector('[data-update-hint]'),
    progress: dock.querySelector('[data-update-progress]'),
    progressText: dock.querySelector('[data-update-progress-text]'),
    error: dock.querySelector('[data-update-error]'),
    actions: dock.querySelector('[data-update-actions]'),
    now: dock.querySelector('[data-update="now"]'),
    local: dock.querySelector('[data-update="local"]'),
    foot: dock.querySelector('[data-update-foot]'),
    file: dock.querySelector('[data-update-file]'),
  };
  const state = { data: null, working: false, timer: 0 };

  /* 页面自己加载时的版本（服务端注入的 meta）。服务端已经换成新版本、页面
   * 还是旧的时候要明确说出来：覆盖安装/手动替换程序文件后，旧标签页不会
   * 自动变新，教练会以为「某些页面还是旧页面」。 */
  const loadedVersion = (() => {
    const meta = document.querySelector('meta[name="app-version"]');
    return meta && meta.content ? String(meta.content).trim() : '';
  })();
  let driftNotified = false;

  function noticeVersionDrift(serverVersion) {
    const running = String(serverVersion || '').trim();
    if (driftNotified || !loadedVersion || !running) return;
    if (compareVersion(running, loadedVersion) === 0) return;
    driftNotified = true;
    showToast(`工作台已升级到 v${running}，当前页面还是 v${loadedVersion} 的旧页面；`
      + '按 Ctrl+F5（或重新打开工作台）刷新后即可看到新界面。', 15000);
  }

  let toastTimer = 0;
  function showToast(message, duration = 4500) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, duration);
  }

  function setFooterVersion(version) {
    const trigger = document.querySelector('[data-action="check-update"]');
    if (!trigger || !version) return;
    trigger.dataset.label = `检查更新 · v${version}`;
    trigger.textContent = trigger.dataset.label;
  }

  function clearExtras() {
    refs.actions.querySelectorAll('.update-extra').forEach((node) => node.remove());
  }

  function hideCard() {
    dock.hidden = true;
    clearInterval(state.timer);
    state.data = null;
    state.working = false;
  }

  function dismiss() {
    if (state.data && state.data.latestVersion) {
      try { sessionStorage.setItem(DISMISS_KEY, state.data.latestVersion); } catch (error) { /* 隐私模式 */ }
    }
    hideCard();
  }

  function renderNotes(notes) {
    const lines = (Array.isArray(notes) ? notes : [])
      .map((note) => String(note == null ? '' : note).replace(/^[-*]\s*/, '').trim())
      .filter(Boolean)
      .slice(0, NOTE_LIMIT);
    refs.notes.textContent = '';
    refs.notes.hidden = lines.length === 0;
    lines.forEach((line) => {
      const item = document.createElement('li');
      item.textContent = line;
      refs.notes.appendChild(item);
    });
    if (lines.length) {
      const more = document.createElement('li');
      more.className = 'update-more';
      const link = document.createElement('a');
      link.href = RELEASE_PAGE;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = '查看完整更新说明';
      more.appendChild(link);
      refs.notes.appendChild(more);
    }
  }

  function baseRender(data) {
    state.data = data;
    clearInterval(state.timer);
    clearExtras();
    refs.error.hidden = true;
    refs.progress.hidden = true;
    refs.actions.hidden = false;
    refs.now.hidden = false;
    refs.local.hidden = false;
    refs.now.disabled = false;
    refs.local.disabled = false;
    refs.date.textContent = data.releaseDate ? `${data.releaseDate}` : '';
    refs.version.textContent = `v${data.latestVersion}`;
    renderNotes(data.notes);
    dock.hidden = false;
  }

  function renderAvailable(data) {
    baseRender(data);
    refs.kicker.textContent = '发现新版本';
    const bits = [`当前 v${data.currentVersion || '旧版本'}`];
    const size = formatSize(data.patch && data.patch.size);
    if (size) bits.push(`增量包 ${size}`);
    refs.meta.textContent = bits.join(' · ');
    refs.hint.hidden = true;
    refs.foot.textContent = '更新只替换程序文件，data/ 与 .env 不会被修改；完成后服务会自动重启。';
    refs.foot.hidden = false;
  }

  function renderBlocked(data) {
    baseRender(data);
    refs.kicker.textContent = '需要先换完整包';
    refs.meta.textContent = `当前 v${data.currentVersion || '旧版本'} 低于最低支持版本 v${data.minVersion || '新版本'}`;
    refs.hint.hidden = false;
    refs.hint.textContent = '这个跨度不能只换程序文件：请下载完整包解压覆盖程序目录，或安装新版安装包；data/ 会保留。';
    refs.actions.hidden = false;
    refs.now.hidden = true;
    refs.local.hidden = true;
    const download = document.createElement('a');
    download.className = 'primary update-extra';
    download.href = (data.full && data.full.url) || RELEASE_PAGE;
    download.target = '_blank';
    download.rel = 'noreferrer';
    download.textContent = '下载完整包';
    refs.actions.insertBefore(download, refs.actions.firstChild);
    const page = document.createElement('a');
    page.className = 'update-later update-extra';
    page.href = RELEASE_PAGE;
    page.target = '_blank';
    page.rel = 'noreferrer';
    page.textContent = '打开下载页';
    refs.actions.insertBefore(page, refs.actions.lastChild);
    refs.foot.textContent = '不放心手动替换时，也可以把这一页发作者，让作者帮你确认。';
    refs.foot.hidden = false;
  }

  function setWorking(message) {
    state.working = true;
    refs.error.hidden = true;
    refs.actions.hidden = true;
    refs.progress.hidden = false;
    refs.progressText.textContent = message;
    dock.hidden = false;
  }

  function showError(message) {
    state.working = false;
    clearInterval(state.timer);
    refs.progress.hidden = true;
    refs.actions.hidden = false;
    refs.now.hidden = false;
    refs.local.hidden = false;
    refs.now.disabled = false;
    refs.local.disabled = false;
    refs.error.hidden = false;
    refs.error.textContent = message;
    dock.hidden = false;
  }

  async function pollHealth(expected, previous) {
    const started = Date.now();
    while (Date.now() - started < HEALTH_TIMEOUT) {
      await sleep(HEALTH_INTERVAL);
      const elapsed = Math.round((Date.now() - started) / 1000);
      refs.progressText.textContent = `服务正在重启为 v${expected}…（已等待 ${elapsed} 秒）`;
      try {
        const response = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
        if (!response.ok) continue;
        const health = await response.json();
        const version = String(health && health.version || '');
        const reached = expected
          ? compareVersion(version, expected) >= 0
          : compareVersion(version, previous) > 0;
        if (reached) {
          refs.progressText.textContent = `已更新到 v${version}，正在刷新页面…`;
          setTimeout(() => { window.location.reload(); }, 1000);
          return true;
        }
      } catch (error) { /* 重启窗口内连接被拒绝是正常现象 */ }
    }
    let detail = '';
    try {
      const response = await fetch(`${API_BASE}/api/update/status`, { cache: 'no-store' });
      const status = await response.json();
      detail = status && status.lastResult && status.lastResult.message || '';
    } catch (error) { /* 服务仍未恢复 */ }
    showError(detail
      ? `更新未完成：${detail}`
      : '更新未完成：服务没有在 2 分钟内恢复。请重新打开工作台，或把 logs/update.log 发给作者。');
    return false;
  }

  async function applyOnline(data) {
    if (state.working) return;
    state.working = true;
    setWorking('正在下载并校验增量包…');
    let expected = data.latestVersion;
    try {
      const response = await fetch(`${API_BASE}/api/update/apply`, { method: 'POST' });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `更新失败（HTTP ${response.status}）`);
      }
      const body = await response.json().catch(() => ({}));
      expected = (body.pending && body.pending.version) || expected;
    } catch (error) {
      if (!(error instanceof TypeError)) {
        showError(error.message || '更新失败');
        return;
      }
      /* fetch 连接中断通常意味着服务已经在退出：继续等健康检查。 */
    }
    setWorking(`服务正在重启为 v${expected}…`);
    await pollHealth(expected, data.currentVersion);
  }

  async function applyLocal(file) {
    if (state.working) return;
    if (!/\.zip$/i.test(file.name)) {
      showError('请选择 patch-*.zip 更新包。');
      return;
    }
    state.working = true;
    setWorking(`正在校验 ${file.name}…`);
    try {
      const safeName = file.name.replace(/[^\x20-\x7e]/g, '_');
      const response = await fetch(`${API_BASE}/api/update/stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/zip', 'X-Filename': safeName },
        body: file,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `更新包校验失败（HTTP ${response.status}）`);
      }
      const body = await response.json().catch(() => ({}));
      const expected = (body.pending && body.pending.version) || '';
      setWorking('更新包已校验，正在应用并重启服务…');
      const restart = await fetch(`${API_BASE}/api/update/restart`, { method: 'POST' });
      if (!restart.ok) {
        const detail = await restart.json().catch(() => ({}));
        throw new Error(detail.detail || '应用更新失败');
      }
      setWorking(`服务正在重启为 ${expected ? 'v' + expected : '新版本'}…`);
      await pollHealth(expected, state.data && state.data.currentVersion);
    } catch (error) {
      showError(error.message || '本地更新失败');
    }
  }

  async function checkNow({ force = null } = {}) {
    const last = Number(localStorage.getItem(LAST_CHECK_KEY) || 0);
    const needForce = force == null ? (!last || Date.now() - last > CHECK_THROTTLE) : force;
    const response = await fetch(`${API_BASE}/api/update/check${needForce ? '?force=1' : ''}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`检查更新失败（HTTP ${response.status}）`);
    const data = await response.json();
    if (needForce) {
      try { localStorage.setItem(LAST_CHECK_KEY, String(Date.now())); } catch (error) { /* 隐私模式 */ }
    }
    if (data && data.currentVersion) setFooterVersion(data.currentVersion);
    return data;
  }

  function handleCheck(data, { auto = false, forceShow = false } = {}) {
    if (!data || data.ok === false) return;
    if (data.sourceMode) {
      if (!auto) showToast('源码模式：请运行「更新代码.bat」（等价 git pull）更新。');
      return;
    }
    if (data.updateAvailable) {
      let dismissed = '';
      try { dismissed = sessionStorage.getItem(DISMISS_KEY) || ''; } catch (error) { /* 隐私模式 */ }
      if (!forceShow && auto && dismissed === data.latestVersion) return;
      if (data.blocked) renderBlocked(data);
      else renderAvailable(data);
      return;
    }
    if (!auto) showToast(`已是最新版本${data.currentVersion ? ' v' + data.currentVersion : ''}`);
  }

  async function autoCheck() {
    try {
      const data = await checkNow();
      noticeVersionDrift(data && data.currentVersion);
      handleCheck(data, { auto: true });
    } catch (error) { /* 没网就静默，不打扰工作台 */ }
  }

  dock.addEventListener('click', (event) => {
    const action = event.target.closest('[data-update]');
    if (!action || state.working) return;
    const kind = action.dataset.update;
    if (kind === 'later') dismiss();
    else if (kind === 'now' && state.data) applyOnline(state.data);
    else if (kind === 'local') refs.file.click();
  });

  refs.file.addEventListener('change', () => {
    const file = refs.file.files && refs.file.files[0];
    refs.file.value = '';
    if (file) applyLocal(file);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !dock.hidden && !state.working) dismiss();
  });

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-action="check-update"]');
    if (!trigger || trigger.disabled) return;
    event.preventDefault();
    trigger.disabled = true;
    trigger.textContent = '正在检查…';
    checkNow({ force: true })
      .then((data) => {
        setFooterVersion(data && data.currentVersion);
        noticeVersionDrift(data && data.currentVersion);
        handleCheck(data, { auto: false, forceShow: true });
      })
      .catch(() => showToast('检查更新失败：请确认这台电脑能联网后再试。'))
      .finally(() => {
        trigger.disabled = false;
        trigger.textContent = trigger.dataset.label || '检查更新';
      });
  });

  setTimeout(autoCheck, AUTO_CHECK_DELAY);
}
