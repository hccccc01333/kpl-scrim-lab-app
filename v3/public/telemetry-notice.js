/* 匿名使用统计的告知与开关。
 *
 * 首次打开工作台时弹一次说明：采集什么、不采集什么、本机匿名 ID、如何关闭；
 * 之后页脚「匿名统计」可以随时再打开，查看状态或重新开启。
 * 只做 UI，真正的上报在 telemetry.py（服务端启动时延迟发心跳）。
 */

const NOTICE_KEY = 'kpl-telemetry-notice-v1';
const AUTO_OPEN_DELAY = 2200;

export function initTelemetryNotice({ API_BASE }) {
  const dialog = document.createElement('dialog');
  dialog.className = 'usage-dialog';
  dialog.setAttribute('aria-labelledby', 'usage-title');
  dialog.innerHTML = `<div class="usage-card">
    <div class="usage-top">
      <span class="usage-kicker">隐私说明</span>
      <button type="button" class="usage-close" data-usage="keep" aria-label="关闭">×</button>
    </div>
    <h2 class="usage-title" id="usage-title">匿名使用统计</h2>
    <p class="usage-lead">为了知道有多少台电脑在用、哪个版本最常用，工作台会向作者发送一条<strong>匿名心跳</strong>。它不包含你的账号、战队、选手或对局内容，也不会影响工作台的任何功能。</p>
    <div class="usage-cols">
      <div>
        <h3>会上报</h3>
        <ul>
          <li>本机随机生成的安装 ID（首次启动生成，不是账号）</li>
          <li>工作台版本号</li>
          <li>Windows 版本与 CPU 架构</li>
          <li>首次使用时间、本次启动时间</li>
        </ul>
      </div>
      <div>
        <h3>不会上报</h3>
        <ul>
          <li>对局、阵容、BP、战绩</li>
          <li>战队、教练、选手、营地账号</li>
          <li>文件名、目录、截图或录屏内容</li>
          <li>主机名、用户名、邮箱、手机号</li>
        </ul>
      </div>
    </div>
    <p class="usage-note">频率：每次启动最多 1 条，20 小时内不重复；离线就不发。匿名 ID 只用于区分不同电脑，统计服务只保存上面列出的字段。</p>
    <dl class="usage-state">
      <div><dt>当前状态</dt><dd data-usage-state>读取中…</dd></div>
      <div><dt>本机匿名 ID</dt><dd><code data-usage-id>—</code><button type="button" class="usage-copy" data-usage="copy">复制</button></dd></div>
    </dl>
    <p class="usage-env" data-usage-env hidden></p>
    <p class="usage-message" data-usage-message role="status" hidden></p>
    <div class="usage-actions">
      <button type="button" class="primary" data-usage="keep">继续使用（保持开启）</button>
      <button type="button" class="control" data-usage="toggle">关闭匿名统计</button>
      <button type="button" class="usage-link" data-usage="close">先关掉</button>
    </div>
    <p class="usage-foot">关闭后立即停止上报；之后可以在页脚「匿名统计」里重新开启。安装 ID 保存在 data/usage/install_id.txt，删除该文件等同换一个新 ID。</p>
  </div>`;
  document.body.appendChild(dialog);

  const refs = {
    state: dialog.querySelector('[data-usage-state]'),
    id: dialog.querySelector('[data-usage-id]'),
    env: dialog.querySelector('[data-usage-env]'),
    message: dialog.querySelector('[data-usage-message]'),
    keep: dialog.querySelector('[data-usage="keep"]'),
    toggle: dialog.querySelector('[data-usage="toggle"]'),
    close: dialog.querySelector('[data-usage="close"]'),
    copy: dialog.querySelector('[data-usage="copy"]'),
  };
  let status = null;
  let messageTimer = 0;

  function markSeen() {
    try { localStorage.setItem(NOTICE_KEY, '1'); } catch (error) { /* 隐私模式 */ }
  }

  function flash(text) {
    refs.message.textContent = text;
    refs.message.hidden = false;
    clearTimeout(messageTimer);
    messageTimer = setTimeout(() => { refs.message.hidden = true; }, 4200);
  }

  function render() {
    if (!status) return;
    const enabled = Boolean(status.enabled);
    refs.state.textContent = enabled
      ? `已开启（每 ${status.periodHours || 20} 小时最多一条${status.lastPingAt ? `，最近一次 ${status.lastPingAt.replace('T', ' ').replace('Z', '')}` : ''}）`
      : (status.envDisabled ? '已关闭（环境变量 KPL_TELEMETRY）' : '已关闭');
    refs.id.textContent = status.installId || '—';
    refs.keep.hidden = !enabled;
    refs.keep.style.display = enabled ? '' : 'none';
    refs.toggle.textContent = enabled ? '关闭匿名统计' : '重新开启匿名统计';
    refs.toggle.hidden = Boolean(status.envDisabled);
    refs.toggle.style.display = status.envDisabled ? 'none' : '';
    refs.env.hidden = !status.envDisabled;
    refs.env.textContent = status.envDisabled
      ? '当前被环境变量 KPL_TELEMETRY 关闭，工作台里改不了；去掉这个环境变量后重启才会恢复上报。'
      : '';
  }

  async function loadStatus() {
    const response = await fetch(`${API_BASE}/api/usage/status`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    status = await response.json();
    render();
    return status;
  }

  async function toggle() {
    if (!status || status.envDisabled) return;
    const path = status.enabled ? 'optout' : 'optin';
    refs.toggle.disabled = true;
    try {
      const response = await fetch(`${API_BASE}/api/usage/${path}`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      status = await response.json();
      render();
      flash(status.enabled ? '已重新开启匿名统计。' : '已关闭，本机不再上报匿名统计。');
    } catch (error) {
      flash('操作失败，请稍后再试。');
    } finally {
      refs.toggle.disabled = false;
    }
  }

  function open() {
    markSeen();
    loadStatus()
      .then(() => { if (!dialog.open) dialog.showModal(); })
      .catch(() => { /* 后端不可用时静默：不挡工作台 */ });
  }

  function close() {
    markSeen();
    if (dialog.open) dialog.close();
  }

  dialog.addEventListener('click', (event) => {
    const action = event.target.closest('[data-usage]');
    if (!action) return;
    const kind = action.dataset.usage;
    if (kind === 'keep' || kind === 'close') close();
    else if (kind === 'toggle') toggle();
    else if (kind === 'copy') {
      const text = String(refs.id.textContent || '');
      if (navigator.clipboard && text && text !== '—') {
        navigator.clipboard.writeText(text).then(() => flash('安装 ID 已复制。')).catch(() => flash('复制失败，可以手动选中。'));
      }
    }
  });

  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close();
  });

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-action="usage-info"]');
    if (!trigger) return;
    event.preventDefault();
    open();
  });

  setTimeout(() => {
    let seen = '';
    try { seen = localStorage.getItem(NOTICE_KEY) || ''; } catch (error) { /* 隐私模式 */ }
    if (seen) return;
    // Playwright 等自动化巡检浏览器不主动弹首次说明，避免遮挡页面截图与交互；
    // 真人浏览器（navigator.webdriver 为 false）照常只弹一次。
    if (navigator.webdriver) return;
    loadStatus()
      .then(() => {
        if (!status || !status.enabled) { markSeen(); return; }
        if (!dialog.open) {
          markSeen();
          dialog.showModal();
        }
      })
      .catch(() => { /* 静默 */ });
  }, AUTO_OPEN_DELAY);
}
