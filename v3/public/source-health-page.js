/* 管理 → 外部数据源爬取情况：自取数模块（app.js 接线见 OWN_MODULE_ROUTES）。
 *
 * 只读 GET /api/v3/data-source-health；卡片上的「重新爬取」POST
 * /api/v3/data-source-health/refresh，后台任务执行，本页轮询直到结束。
 * 卡片语义：article + 标题 + 独立 button（不用整卡链接，卡片本身不是导航）。
 */
import { glyph } from './ui-icons.js';

const DEFAULT_API_BASE = (() => {
  try { return new URL('..', import.meta.url).pathname.replace(/\/$/, ''); } catch { return ''; }
})();
const STATUS = {
  ok: { cls: 'is-ok' }, stale: { cls: 'is-stale' }, warn: { cls: 'is-warn' },
  error: { cls: 'is-error' }, running: { cls: 'is-running' },
};
const fmt = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('zh-CN') : '—';
const when = (v) => {
  const s = String(v || '');
  return s ? s.replace('T', ' ').slice(0, 16) : '—';
};

export function createSourceHealthPage(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc : (v) => String(v ?? '');
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const notify = typeof h.notify === 'function' ? h.notify : null;

  let root = null;
  let controller = null;
  let timer = 0;
  let generation = 0;
  let loading = false;
  let failed = '';
  let payload = null;

  function liveNode() { return root?.querySelector('[data-sh-live]') || null; }
  function say(message) { const node = liveNode(); if (node) node.textContent = message || ''; }

  async function load(quiet = false) {
    if (!root || loading) return;
    const ticket = ++generation;
    controller?.abort();
    controller = new AbortController();
    loading = true;
    if (!quiet) say('正在读取数据源状态…');
    try {
      const response = await fetch(API_BASE + '/api/v3/data-source-health', {
        cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`接口返回 ${response.status}`);
      const doc = await response.json();
      if (ticket !== generation) return;
      payload = doc;
      failed = '';
      paint();
      const pending = (doc.sources || []).some((card) => card.running);
      if (pending) {
        clearTimeout(timer);
        timer = window.setTimeout(() => load(true), 3000);
      }
    } catch (error) {
      if (error.name === 'AbortError' || ticket !== generation) return;
      failed = `读不到数据源状态：${error.message}`;
      if (ticket === generation) paint();
    } finally {
      loading = false;
    }
  }

  function cardHtml(card) {
    const state = STATUS[card.status] || STATUS.warn;
    const key = esc(card.key);
    const retry = card.canRetry
      ? `<button type="button" class="control sh-retry" data-sh-retry="${key}"${card.running ? ' disabled' : ''}>${glyph('refresh', { size: 18 })}<span>${card.running ? '正在爬取…' : '重新爬取'}</span></button>`
      : '<span class="sh-noaction">随巅峰千强一起刷新</span>';
    const last = card.lastResult?.message
      ? `<p class="sh-last ${card.lastResult.ok ? '' : 'is-bad'}">${esc(card.lastResult.message)}</p>` : '';
    return `<article class="sh-card ${state.cls}" data-source="${key}">
      <header class="sh-head">
        <span class="sh-icon" aria-hidden="true">${icon(card.icon || 'sources')}</span>
        <h3>${esc(card.name)}</h3>
        <span class="sh-badge">${esc(card.label || state.cls)}</span>
      </header>
      <p class="sh-desc">${esc(card.description || '')}</p>
      <dl class="sh-meta">
        <div><dt>已收录</dt><dd>${fmt(card.count)}</dd></div>
        <div><dt>最近更新</dt><dd>${when(card.updatedAt)}</dd></div>
      </dl>
      <p class="sh-detail">${esc(card.detail || '')}</p>
      ${last}
      <footer class="sh-foot">${retry}</footer>
    </article>`;
  }

  function paint() {
    if (!root) return;
    const sources = payload?.sources || [];
    const counts = payload?.counts || {};
    const summary = failed
      ? `<div class="sh-summary is-error" role="status">${glyph('warning', { size: 18 })}<span>${esc(failed)}</span><button type="button" class="control" data-sh-reload>${glyph('refresh', { size: 18 })}重试读取</button></div>`
      : `<div class="sh-summary">
          <span class="sh-summary-title">自动刷新状态</span>
          <span class="sh-pill is-ok">正常 <b>${Number(counts.ok) || 0}</b></span>
          <span class="sh-pill is-stale">待处理 <b>${Number(counts.stale) || 0}</b></span>
          <span class="sh-pill is-error">失败 <b>${Number(counts.error) || 0}</b></span>
          <span class="sh-summary-note">${esc(payload?.offlineHint || '')}</span>
        </div>`;
    root.innerHTML = `<section class="page sh-page">
      <div class="sh-intro">
        <div><p class="sh-eyebrow">管理 / 外部数据源</p><h1>外部数据源爬取情况</h1></div>
      </div>
      ${summary}
      <p class="sh-live" data-sh-live role="status" aria-live="polite"></p>
      <div class="sh-grid">${sources.map(cardHtml).join('')}</div>
    </section>`;
  }

  async function retry(key, button) {
    if (button?.disabled) return;
    button.disabled = true;
    say(`正在启动 ${key} 的爬取任务…`);
    try {
      const response = await fetch(API_BASE + '/api/v3/data-source-health/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ source: key }),
      });
      const doc = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(doc.detail || `接口返回 ${response.status}`);
      say(doc.message || '爬取任务已启动，卡片会显示进度。');
      notify?.(doc.message || '爬取任务已启动');
      clearTimeout(timer);
      timer = window.setTimeout(() => load(true), 1200);
    } catch (error) {
      say(`启动失败：${error.message}`);
      notify?.(`启动失败：${error.message}`);
      button.disabled = false;
    }
  }

  function onClick(event) {
    const retryButton = event.target.closest('[data-sh-retry]');
    if (retryButton && root.contains(retryButton)) {
      retry(retryButton.dataset.shRetry, retryButton);
      return;
    }
    if (event.target.closest('[data-sh-reload]')) load();
  }

  function mount(node) {
    if (!node || root === node) return;
    dispose();
    root = node;
    root.addEventListener('click', onClick);
    paint();
    load();
    timer = window.setInterval(() => load(true), 30000);
  }

  function dispose() {
    clearTimeout(timer);
    clearInterval(timer);
    timer = 0;
    controller?.abort();
    controller = null;
    generation++;
    root?.removeEventListener('click', onClick);
    root = null;
    payload = null;
  }

  return { mount, dispose, reload: () => load() };
}
