/* 本地诊断信息：错误码 + 脱敏上下文，供教练粘贴到反馈群。
   约束力：不采集身份、战队、对局内容；不联网；不把原始堆栈摆到界面上。 */
import { helpContent } from './help-content.js';

let blockSeq = 0;
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[c]);

function sanitize(value, limit = 240) {
  let text = String(value ?? '').replace(/\s+/g, ' ').trim();
  text = text.replace(/[A-Za-z]:\\[^\s"']+/g, '<本机路径>')
    .replace(/\/(?:home|Users)\/[^\s"']+/g, '<本机路径>')
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<邮箱>')
    .replace(/\b(?:token|password|secret)=[^\s]+/gi, '<凭据>');
  return text.length > limit ? text.slice(0, limit) + '…' : text;
}

function shortAgent() {
  const ua = navigator.userAgent || '';
  const browser = /(Edg|Chrome|Firefox|Safari)\/([\d.]+)/.exec(ua);
  const os = /Windows NT ([\d.]+)/.exec(ua);
  return [os ? 'Windows ' + os[1] : '未知系统', browser ? browser[1] + ' ' + browser[2] : '未知浏览器'].join(' / ');
}

export function errorEntry(code) {
  return helpContent.errors?.[code] || null;
}

export function diagnosticText({ code = '', error = null, route = '', requestPath = '' } = {}) {
  const entry = errorEntry(code);
  const message = sanitize(error && (error.message || error.name) ? (error.message || error.name) : '未提供异常信息');
  return [
    '[KPL 训练赛工作台 · 诊断信息]',
    `错误码：${code || '未归类'}（${entry ? entry.title : '未注册错误码'}）`,
    `时间：${new Date().toLocaleString('zh-CN', { hour12: false })}`,
    `版本：v${helpContent.version || '未知'}`,
    `页面：${sanitize(route || location.hash || '(无)', 120)}`,
    `请求：${sanitize(requestPath || '—', 120)}`,
    `异常：${message}`,
    `环境：${shortAgent()}`,
    '说明：已脱敏，不包含对局数据、选手姓名、账号、凭据或本机路径。',
    `反馈渠道：${helpContent.feedback?.channel || '项目反馈群'}（${helpContent.feedback?.channelValue || '待公布'}）`
  ].join('\n');
}

export function diagnosticBlock({ code = '', error = null, route = '', requestPath = '' } = {}) {
  const id = `dx-${++blockSeq}`;
  const text = diagnosticText({ code, error, route, requestPath });
  const entry = errorEntry(code);
  return `<div class="dx-block">
    <div class="dx-head"><b>${escapeHtml(code || '未归类')} · ${escapeHtml(entry ? entry.title : '未注册错误码')}</b><span>已脱敏 · 可粘贴到反馈群</span></div>
    <pre class="dx-text" id="${id}" tabindex="0"><code>${escapeHtml(text)}</code></pre>
    <div class="dx-copy">
      <button type="button" class="control" data-diagnostic-copy aria-controls="${id}">复制诊断信息</button>
      <span class="dx-copy-tip" role="status" aria-live="polite"></span>
    </div>
  </div>`;
}

async function copyText(text) {
  if (!text) throw new Error('empty');
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;top:-1000px;left:-1000px;opacity:0';
  document.body.append(area);
  area.select();
  try {
    if (!document.execCommand('copy')) throw new Error('copy failed');
  } finally {
    area.remove();
  }
}

export function bindDiagnosticCopy(root, { getText } = {}) {
  if (!root) return () => {};
  const buttons = [...root.querySelectorAll('[data-diagnostic-copy]')];
  const timers = new Map();
  const cleanups = buttons.map((button) => {
    const wrap = button.closest('.dx-copy') || button.parentElement;
    const tip = wrap?.querySelector('.dx-copy-tip');
    const target = document.getElementById(button.getAttribute('aria-controls') || '');
    const report = (ok) => {
      clearTimeout(timers.get(button));
      wrap?.setAttribute('data-state', ok ? 'ok' : 'failed');
      if (tip) tip.textContent = ok ? '已复制' : '复制失败，请手动选择文本';
      timers.set(button, setTimeout(() => {
        wrap?.removeAttribute('data-state');
        if (tip) tip.textContent = '';
      }, 2600));
    };
    const onClick = async () => {
      const text = getText ? getText(button) : (target?.innerText || '');
      try {
        await copyText(text);
        report(true);
      } catch {
        report(false);
      }
    };
    button.addEventListener('click', onClick);
    return () => {
      button.removeEventListener('click', onClick);
      clearTimeout(timers.get(button));
    };
  });
  return () => cleanups.forEach((fn) => fn());
}
