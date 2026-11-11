import { groupFor } from './navigation.js';
import { createFeatures, featureSections } from './features.js';
import { createMatchDeep } from './match-deep.js';
import { createCrossPage } from './cross-page.js';
import { createTour } from './tour.js';
import { createHomeDecision } from './home-decision.js';
import { createDecisionPage } from './decision-page.js';
import { createBpCounter } from './bp-counter.js';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const CLIENT_DOWNLOAD_URL = 'https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest';
const app = document.querySelector('#app');
const nav = [
  ['overview', '首页'], ['decision', '决策'], ['ingest', '采集'], ['matches', '对局'], ['teams', '战队'], ['players', '选手'],
  ['heroes', '英雄'], ['bp', 'BP'], ['setup', '赛训'], ['sources', '数据来源'],
];
const labels = Object.fromEntries(nav);
for (const pages of Object.values(featureSections)) for (const [key, label] of pages) labels[key] = label;
Object.assign(labels, { decision: '决策台', match: '对局复盘', player: '选手详情', playerdetail: '选手个人页', identity: '选手认领', team: '战队详情', hero: '英雄详情', topic: '分析详情', study: '分析详情', report: '分析报告', review: '缺失值审查', shots: '截图 OCR', videos: '录屏', replays: '回放', capture: '导入表格', economy: '经济转折', tempo: '节奏分析', opponents: '对手侦察', teamstyle: '战队风格', teamroster: '战队阵容', teamtraining: '战队训练', ownership: '对手归属', pending: '待确认', effect: '训练效果', session: '训练课', competition: '比赛详情', weekly: '训练周报' });
function sectionFor(name) {
  if (name === 'topic' || name === 'study') return groupFor(name, current().key);
  const detail = { match: 'matches', player: 'players', playerdetail: 'players', identity: 'players', team: 'teams', hero: 'heroes', report: 'reports', review: 'ingest', shots: 'ingest', videos: 'ingest', replays: 'ingest', capture: 'ingest', economy: 'matches', tempo: 'matches', opponents: 'teams', ownership: 'setup', pending: 'setup', effect: 'setup', session: 'setup', competition: 'setup', weekly: 'setup' }[name] || name;
  return Object.keys(featureSections).find((section) => featureSections[section].some(([key]) => key === detail)) || detail;
}
const icons = {
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/>',
  moon: '<path d="M20.9 13.3A8.9 8.9 0 0 1 10.7 3.1 9 9 0 1 0 20.9 13.3Z"/>',
  filter: '<path d="M4 7h16M7 12h10m-7 5h4"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 4 4"/>',
  overview: '<path d="M3.5 10.5 12 3l8.5 7.5V20H14v-6h-4v6H3.5z"/>',
  decision: '<path d="M12 3v18M12 6h7l2.4 3L19 12h-7M12 12H5L2.6 15 5 18h7"/>',
  matches: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  teams: '<path d="M12 3 4 6.5v5.8c0 4.3 3.1 7.1 8 8.7 4.9-1.6 8-4.4 8-8.7V6.5z"/><path d="m8.8 12 2 2 4.4-4.4"/>',
  players: '<circle cx="9" cy="8" r="3"/><path d="M3.5 20v-1.5a5.5 5.5 0 0 1 11 0V20M16 5a3 3 0 0 1 0 6m1 4a4.5 4.5 0 0 1 3.5 4.4V20"/>',
  heroes: '<path d="m12 3 2.4 5.2 5.6.7-4.1 3.9 1 5.6-4.9-2.7-4.9 2.7 1-5.6L4 8.9l5.6-.7z"/>',
  bp: '<path d="m12 3.5 7.5 4.4-2.8 12.3H7.3L4.5 7.9zM4.5 7.9 12 13l7.5-5.1M12 13v7.2"/>',
  space: '<path d="M4 4v16h16M7 16l4-5 3.5 2.5L20 6"/><circle cx="20" cy="6" r="1"/>',
  setup: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h3m-3 3h7"/>',
  sources: '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.7 2.7 0 0 1 5.2 1c0 1.8-2.7 2.2-2.7 4M12 17.4h.01"/>',
  inbox: '<path d="M4 5h16v14H4z"/><path d="M4 13h4l2 3h4l2-3h4"/>',
  demo: '<path d="m8 5 11 7-11 7z"/>',
  client: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  ingest: '<path d="M12 3v11m-4-4 4 4 4-4"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
};
const icon = (name) => `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[name]}</svg>`;
const esc = (x) => String(x ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const has = (n) => typeof n === 'number' && Number.isFinite(n);
const fmt = (n, digits = 0) => has(n) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(n) : '—';
const pct = (n) => has(n) ? fmt(n, 1) + '%' : '—';
const diff = (n) => has(n) ? (n > 0 ? '+' : '') + fmt(n === 0 ? 0 : n) : '—';
const time = (n) => has(n) && n >= 0 ? `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, '0')}` : '—';
/* 阶段口径（教练 2026-11-10 确认）：对线期 0–4 分钟，发育期 4–10 分钟，其后为后期。
   所有阶段相关面板统一走这两个函数，避免各算各的三等分。始终返回 3 段
   （短局的后段长度为 0，图表天然不绘制）。 */
const PHASE_DEFS = [['对线期', 0, 240], ['发育期', 240, 600], ['后期', 600, Infinity]];
function phaseWindows(duration) {
  const total = has(duration) && duration > 0 ? duration : 0;
  return PHASE_DEFS.map(([label, start, end]) => {
    const a = Math.min(start, total);
    const b = Math.min(end === Infinity ? total : end, total);
    return { label, start: a, end: Math.max(a, b) };
  });
}
/* 分均经济评级（教练 2026-11-10 口径，单位金/分钟）：
   对抗路/发育路 = 10 分钟基准 ÷10：6800 及格 / 7000 良好 / 7400 优秀；
   打野（野核）：700 及格 / 750 良好 / 800 优秀；
   中单/游走暂无阈值，只显示数值。 */
const GOLD_GRADES = {
  '对抗路': [[740, '优秀', 'good'], [700, '良好', 'ok'], [680, '及格', 'pass'], [0, '待提升', 'low']],
  '发育路': [[740, '优秀', 'good'], [700, '良好', 'ok'], [680, '及格', 'pass'], [0, '待提升', 'low']],
  '打野': [[800, '优秀', 'good'], [750, '良好', 'ok'], [700, '及格', 'pass'], [0, '待提升', 'low']],
};
function goldGrade(lane, gpm) {
  const defs = GOLD_GRADES[lane];
  if (!defs || !has(gpm)) return null;
  for (const [need, label, level] of defs) if (gpm >= need) return { label, level };
  return null;
}
function gpmOf(player, duration) {
  if (!player || !has(player.gold)) return null;
  const minutes = has(duration) && duration > 0 ? duration / 60 : null;
  return minutes ? player.gold / minutes : null;
}
function phaseIndexAt(t, duration) {
  if (!has(duration) || duration <= 0) return 0;
  if (t < 240) return 0;
  if (t < 600) return 1;
  return 2;
}
const route = (page, value = '') => '#' + page + (value ? '/' + encodeURIComponent(value) : '');
const resultName = { win: '胜利', loss: '失利', draw: '平局', unknown: '未知' };
const sides = { blue: '蓝方', red: '红方', left: '左侧', right: '右侧' };
const opposite = { blue: 'red', red: 'blue', left: 'right', right: 'left' };
const mirror = { blue: 'left', red: 'right', left: 'blue', right: 'red' };
const sourceName = { db: '本机记录', bundle: '对局数据包', sheet: '表格导入' };
let request;
/* 当前路由（用于判断是否换了页；连接恢复后据此加载当前页）。 */
let loadRoute = '';
/* 一次页面读取的世代编号：换页即作废，旧请求的结果与错误都不能写进新页面。
   静态资源每次刷新都读磁盘，路由表只在进程启动时加载，两者可能短暂错配；
   这里保证错配时只表现为「这一页在读」，不会出现上一页的错误框。 */
let loadGeneration = 0;
const routeKeyOf = (r) => `${r.name}/${r.key || ''}`;
const isStale = (generation, routeKey) =>
  generation !== loadGeneration || routeKeyOf(current()) !== routeKey;
const isCancelled = (error, signal) =>
  Boolean(signal?.aborted) || error?.name === 'AbortError';
/* 同一路由短时失败先自动重试，别把一次 404 直接整页报错。 */
const retryByRoute = new Map();
/* 连接状态：网络层失败后进入自动重连，恢复后自动加载当前页。 */
let offlineSince = 0;
let reconnectTimer = null;
let reconnectDelay = 1000;

function ensureOfflineBanner() {
  let node = document.querySelector('#offline-banner');
  if (!node) {
    node = document.createElement('div');
    node.id = 'offline-banner';
    node.className = 'offline-banner';
    node.hidden = true;
    node.innerHTML = '<span>连接中断</span><b>正在自动重连…</b>';
    document.body.append(node);
  }
  return node;
}
function scheduleReconnect(delay) {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(probeServer, delay);
}
function setOffline(active) {
  const banner = ensureOfflineBanner();
  if (active) {
    if (!offlineSince) { offlineSince = Date.now(); reconnectDelay = 1000; }
    banner.hidden = false;
    scheduleReconnect(reconnectDelay);
    return;
  }
  offlineSince = 0;
  banner.hidden = true;
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  reconnectDelay = 1000;
}
async function probeServer() {
  reconnectTimer = null;
  if (!offlineSince) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3000);
  let reachable = false;
  try {
    /* 任何响应都算“服务在”，不要求 2xx：这一步只判断端口有没有起来。 */
    await fetch(API_BASE + '/api/metadata?source=db', {cache: 'no-store', signal: controller.signal});
    reachable = true;
  } catch {
    reachable = false;
  } finally {
    clearTimeout(timer);
  }
  if (!offlineSince) return;
  if (reachable) { setOffline(false); load(); return; }
  reconnectDelay = Math.min(Math.round(reconnectDelay * 1.6), 8000);
  scheduleReconnect(reconnectDelay);
}
function renderOffline(r = current()) {
  const box = document.querySelector('#content');
  if (!box) return;
  box.innerHTML = `<div class="page"><section class="section"><div class="offline-card">
    <b>${esc(labels[r.name] || '当前页面')}暂时读不到数据</b>
    <p>与工作台的连接中断了，恢复后会<strong>自动加载这一页</strong>，也可以点下面的按钮立即重试。</p>
    <div class="offline-actions"><button class="control" data-action="refresh">立即重试</button></div>
  </div></section></div>`;
}
function renderDataNotice(r) {
  const box = document.querySelector('#content');
  if (!box) return;
  box.innerHTML = `<div class="page"><section class="section"><div class="offline-card">
    <b>${esc(labels[r.name] || '当前页面')}暂时读不到数据</b>
    <p>这一页的数据还没返回，已经自动重试过；稍后再点一次读取即可。</p>
    <div class="offline-actions"><button class="control" data-action="refresh">重新读取</button></div>
  </div></section></div>`;
}
let metadata = {};
let data;
let view = {};
let theme = localStorage.getItem('training-rebuild-theme') || 'light';
let filters = { source: ['db', 'bundle'], from: '', to: '', validation: false };
try {
  const saved = JSON.parse(localStorage.getItem('training-rebuild-filters'));
  if (saved && Array.isArray(saved.source) && saved.source.some((x) => ['db', 'bundle', 'sheet'].includes(x))) {
    filters = { ...filters, ...saved, source: saved.source.filter((x) => ['db', 'bundle', 'sheet'].includes(x)) };
  }
} catch {}

function current() {
  const [path, search = ''] = location.hash.slice(1).split('?');
  const [name, key, tab = ''] = path.split('/');
  let decoded = '';
  try { decoded = decodeURIComponent(key || ''); } catch {}
  let anchor = '';
  try { anchor = new URLSearchParams(search).get('match') || ''; } catch {}
  /* 已下线的战队子页：旧链接回战队档案，不落到首页。 */
  const retired = { teamcompare: 'teams', h2h: 'teams', profiles: 'teams' };
  return { name: retired[name] || (Object.hasOwn(labels, name) ? name : 'overview'), key: decoded, anchor, tab };
}

function score(match) {
  const own = match.ownCamp || 'blue';
  const value = (camp) => match.scores?.[camp] ?? match.scores?.[mirror[camp]];
  const a = value(own);
  const b = value(opposite[own]);
  return has(a) && has(b) ? `${fmt(a)} <span>:</span> ${fmt(b)}` : '—';
}

function portrait(name, cls = '') {
  const url = metadata.icons?.[name];
  if (/^\/catalog\/icons\/hero-\d+\.png$/.test(url || '')) {
    return `<img class="portrait ${cls}" src="${esc(url)}" alt="${esc(name)}" loading="lazy">`;
  }
  return `<span class="portrait portrait-placeholder ${cls}" aria-label="${esc(name || '未知英雄')}">${esc((name || '?')[0])}</span>`;
}

const navHref = (key) => key === 'setup' ? '#plan' : key === 'players' ? '#playerarchive' : '#' + key;
function shell() {
  app.innerHTML = `<header class="masthead"><div class="masthead-inner">
    <a class="wordmark" href="#overview" aria-label="赛训数据首页"><span class="brand-symbol"><i></i><i></i><i></i></span>
      <span>赛训数据<small>TRAINING DATA</small></span></a>
    <nav class="main-nav" aria-label="主导航">${nav.map(([key, label]) => `<a href="${navHref(key)}" data-nav="${key}"><span class="nav-icon">${icon(key)}</span>${label}</a>`).join('')}</nav>
    <div class="head-actions"><button type="button" class="head-button inbox-button" data-sx-inbox aria-label="待处理" title="待处理">${icon('inbox')}<span class="inbox-badge" data-inbox-badge hidden></span></button><a class="mode-button client-button" href="kpl-client://open" data-action="open-client" title="打开桌面客户端（需安装）" aria-label="打开桌面客户端">${icon('client')}<span>打开客户端</span></a><button class="head-button tour-button" data-action="tour" aria-label="使用教程" title="使用教程">${icon('help')}</button><button class="head-button theme-button" data-action="theme" aria-label="切换主题"></button>
      <button class="head-button menu-button" data-action="menu" aria-label="打开导航" aria-expanded="false">${icon('menu')}</button></div>
  </div></header>
  <div class="mobile-menu" hidden><nav aria-label="移动导航">${nav.map(([key, label]) => `<a href="${navHref(key)}">${icon(key)}${label}</a>`).join('')}</nav></div>
  <div class="demo-banner" hidden><strong>演示模式</strong> 所有比赛、选手与分析均为虚构数据，仅供体验。<button data-action="demo">返回真实数据 →</button></div>
  <div class="secondary-wrap"><nav class="secondary-nav" aria-label="分类导航"></nav><nav class="analysis-rail" aria-label="板块分析"></nav></div>
  <main id="content" tabindex="-1"></main>
  <footer class="footer"><span>赛训数据</span><span>英雄资料来自王者荣耀官方，相关权利归原权利人。</span></footer>
  <dialog id="filters"></dialog>`;
  applyTheme();
}

let inboxState = null;
async function refreshInbox() {
  const badge = document.querySelector('[data-inbox-badge]');
  const link = document.querySelector('.inbox-button');
  if (!badge || !link) return;
  try {
    const response = await fetch(API_BASE + '/api/studio/workspace/inbox', {cache:'no-store'});
    if (!response.ok) throw new Error('inbox');
    inboxState = await response.json();
    const count = Number(inboxState.total || 0);
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = !count;
    link.setAttribute('aria-label', count ? `待处理 ${count} 项` : '待处理');
    link.title = count ? `待处理 ${count} 项` : '待处理';
  } catch {
    badge.hidden = true;
  }
}

function openInbox() {
  const data = inboxState;
  if (!data) return;
  let dialog = document.querySelector('#sx-inbox-dialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'sx-inbox-dialog';
    dialog.className = 'sx-dialog sx-inbox-dialog';
    document.body.append(dialog);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  }
  const groups = (data.groups || []).map((group) => {
    const items = group.items || [];
    let body = '';
    if (group.key === 'unmapped') {
      body = items.map((item) => `<div class="sx-inbox-map" data-old-id="${esc(item.oldId)}">
        <span><b>${esc(item.oldId)}</b><small>${fmt(item.matches)} 局</small></span>
        <select aria-label="映射到战队">${(data.teams || []).map((team) => `<option value="${esc(team.id)}">${esc(team.name)}</option>`).join('')}</select>
        <button type="button" class="control" data-sx-map-opponent>映射</button>
      </div>`).join('');
    } else if (items.length) {
      body = `<div class="sx-inbox-items">${items.map((item) => `<a href="${esc(item.href)}" data-sx-inbox-link>${esc(item.label)}</a>`).join('')}</div>`;
    }
    return `<section class="sx-inbox-group">
      <header><b>${esc(group.label)}</b><strong>${fmt(group.count)}</strong></header>
      <p>${esc(group.note || '')}</p>${body}
      ${group.key !== 'unmapped' ? `<a class="sx-inbox-go" href="${esc(group.href)}" data-sx-inbox-link>去处理 →</a>` : ''}
    </section>`;
  }).join('');
  dialog.innerHTML = `<div class="sx-dialog-head"><div><span class="sx-eyebrow">INBOX</span><h2>待处理 ${fmt(data.total || 0)} 项</h2></div><button type="button" class="sx-dialog-x" data-sx-inbox-close aria-label="关闭">×</button></div><p class="sx-dialog-note">先清数据，再看报告；这里只列需要人工判断的事项。</p><div class="sx-inbox-groups">${groups || '<p class="sx-empty">当前没有待处理项。</p>'}</div>`;
  if (!dialog.open) dialog.showModal();
}

function updateMode() {
  const demo=!!metadata.demo;
  const banner=document.querySelector('.demo-banner');
  if (banner) banner.hidden=!demo;
}

function applyTheme() {
  document.documentElement.dataset.theme = theme;
  const button = document.querySelector('.theme-button');
  button.innerHTML = icon(theme === 'light' ? 'moon' : 'sun');
  button.setAttribute('aria-label', theme === 'light' ? '切换深色主题' : '切换浅色主题');
}

function query(fresh = false) {
  const q = new URLSearchParams({ source: filters.source.join(',') });
  if (filters.from) q.set('from', filters.from);
  if (filters.to) q.set('to', filters.to);
  /* 跨局分析的主体是「一批对局」：默认纳入全部已确认对局，
     否则默认排除验证数据后只剩 1 局，整页对照会失去意义。 */
  if (filters.validation || current().name === 'cross') q.set('validation', '1');
  if (fresh) q.set('fresh', '1');
  return '?' + q.toString();
}

async function get(path, fresh = false) {
  const response = await fetch(API_BASE + '/api/' + path + query(fresh), { signal: request.signal, cache: 'no-store' });
  if (!response.ok) {
    /* 后端可能返回英文 detail（如 "Not Found"），不把它原样摆到教练面前。 */
    const error = new Error(response.status === 404 ? '这一页的数据暂时读不到。' : '数据读取失败，稍后会自动重试。');
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function pageIntro(title, subtitle, right = '') {
  return `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>
    <div class="intro-actions">${right}<button class="control" data-action="filter">${icon('filter')} 数据范围</button>
    <button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></div></div>`;
}

function gameAnchorBar() {
  let key = '';
  try { key = new URLSearchParams(location.hash.split('?')[1] || '').get('match') || ''; } catch {}
  if (!key) return '';
  const hit = (data?.matches || []).find((x) => x.key === key);
  const label = hit ? [hit.date, hit.opponent ? '对阵 ' + hit.opponent : ''].filter(Boolean).join(' · ') : key;
  return `<div class="depth-anchor"><span>当前对局 <b>${esc(label)}</b> · 下方是跨局参照，逐局明细可回到这一局</span><a href="${route('match', key)}">回到这一局复盘 ↗</a></div>`;
}

let chartSeq = 0;
function chart(points, label, opts = {}) {
  const values = (points || []).filter((p) => has(p[0]) && has(p[1])).sort((a, b) => a[0] - b[0]);
  if (!values.length) return `<div class="chart-empty">暂无可用的经济时间轴 · 经济采样来自「官方回放」，需要在采集页的通道校对里关联本局官方回放链接（录屏时间轴亦可代替）</div>`;
  const max = Math.max(1, ...values.map((p) => Math.abs(p[1])));
  /* 平均曲线要说明是几局折出来的，别让「25 个采样点」被读成 25 个点。 */
  const limit = Math.ceil(max / 5000) * 5000;
  const low = Math.min(0, ...values.map((p) => p[1])) < 0 ? -limit : 0;
  const high = limit;
  const x0 = values[0][0], x1 = values.at(-1)[0];
  const x = (n) => 55 + (x1 === x0 ? .5 : (n - x0) / (x1 - x0)) * 620;
  const y = (n) => 20 + (high - n) / (high - low) * 185;
  const path = values.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
  const duration = opts.duration || 0;
  const rich = !!opts.rich;
  const step = limit >= 20000 ? 10000 : 5000;
  const ticks = (() => {
    if (!rich) return [...new Set([low, 0, high])];
    const out = [];
    for (let v = low; v <= high; v += step) out.push(v);
    if (!out.includes(0)) out.push(0);
    return [...new Set(out)].sort((a, b) => a - b);
  })();
  const tip = values.at(-1);
  /* 时间轴刻度：每 5 分钟一个（长局 5 分钟、20 分钟以上仍按 5 分），首尾标签另画。 */
  const xTicks = (() => {
    const span = x1 - x0;
    if (span < 120) return [];
    const step = 300;
    const out = [];
    for (let tick = Math.ceil(x0 / step) * step; tick < x1; tick += step) {
      if (tick - x0 < 40 || x1 - tick < 40) continue;
      if (time(tick) === time(x0) || time(tick) === time(x1)) continue;
      out.push(tick);
      if (out.length >= 10) break;
    }
    return out;
  })();
  const gid = 'chart-grad-' + (++chartSeq);
  const bands = rich && duration > 0 ? ['前期', '中期', '后期'].map((name, i) => {
    const xa = x(Math.max(duration * i / 3, x0)), xb = x(Math.min(duration * (i + 1) / 3, x1));
    return xb - xa > 1 ? `<rect x="${xa.toFixed(1)}" y="20" width="${(xb - xa).toFixed(1)}" height="185" class="chart-band${i % 2 ? ' alt' : ''}"/>` : '';
  }).join('') : '';
  const phaseLines = duration > 0 ? [1, 2].map((i) => {
    const t = duration * i / 3;
    return t > x0 && t < x1 ? `<line x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="20" y2="205" class="chart-phase-line"/>` : '';
  }).join('') : '';
  const phaseLabels = duration > 0 ? ['前期', '中期', '后期'].map((name, i) => {
    const mid = duration * (i + .5) / 3;
    return mid >= x0 && mid <= x1 ? `<text x="${x(mid).toFixed(1)}" y="13" text-anchor="middle" class="chart-phase-label">${name}</text>` : '';
  }).join('') : '';
  const zeroLine = rich && low < 0 ? `<line x1="55" x2="675" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="chart-zero"/>` : '';
  const eventLines = (opts.nodes || []).filter((n) => has(n.t) && n.t >= x0 && n.t <= x1).slice(0, 8).map((n) =>
    `<line x1="${x(n.t).toFixed(1)}" x2="${x(n.t).toFixed(1)}" y1="20" y2="205" class="chart-event-line"><title>${esc(time(n.t) + ' · ' + n.event)}</title></line>`
  ).join('');
  const badge = rich ? (() => {
    const txt = diff(tip[1]);
    const w = txt.length * 7.2 + 18;
    const px = x(tip[0]), py = y(tip[1]);
    const bx = Math.max(55, Math.min(675 - w, px - w - 12));
    const by = tip[1] >= 0 ? py - 32 : py + 12;
    return `<g class="chart-badge"><rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${w.toFixed(1)}" height="23" rx="11.5"/><text x="${(bx + 9).toFixed(1)}" y="${(by + 15.5).toFixed(1)}">${esc(txt)}</text></g>`;
  })() : '';
  return `<div class="chart-wrap${rich ? ' chart-rich' : ''}"><svg viewBox="0 0 700 245" role="img" aria-label="${esc(label)}，${values.length} 个采样点，最后 ${time(tip[0])} 时经济差 ${diff(tip[1])} 金">
    ${rich ? `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--accent);stop-opacity:.26"/><stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/></linearGradient></defs>` : ''}
    ${bands}
    ${ticks.map((tick) => `<line x1="55" x2="675" y1="${y(tick)}" y2="${y(tick)}" class="grid-line"/>
      <text x="45" y="${y(tick)+4}" text-anchor="end" class="axis-text">${tick ? esc(`${fmt(tick / 1000, 1)}k`) : '0'}</text>`).join('')}
    ${phaseLines}${zeroLine}${eventLines}
    <path d="${path} L${x(tip[0])},${y(0)} L${x(values[0][0])},${y(0)} Z" class="${rich ? 'area-rich' : 'area'}"${rich ? ` fill="url(#${gid})"` : ''}/>
    <path d="${path}" class="curve"/>
    ${values.map((point) => `<circle tabindex="0" cx="${x(point[0])}" cy="${y(point[1])}" r="5" class="point"
      data-point="${esc(time(point[0]) + '　' + diff(point[1]) + ' 金')}" aria-label="${esc(time(point[0]) + '，经济差 ' + diff(point[1]) + ' 金')}"><title>${time(point[0])}　${diff(point[1])} 金</title></circle>`).join('')}
    ${badge}
    ${phaseLabels}
    ${xTicks.map((tick) => `<line x1="${x(tick).toFixed(1)}" x2="${x(tick).toFixed(1)}" y1="205" y2="209" class="grid-line"/><text x="${x(tick).toFixed(1)}" y="233" text-anchor="middle" class="axis-text">${time(tick)}</text>`).join('')}
    <text x="55" y="233" class="axis-text">${time(x0)}</text><text x="675" y="233" text-anchor="end" class="axis-text">${time(x1)}</text>
    </svg><div class="chart-tooltip" role="status" hidden></div><div class="chart-foot"><span><i></i> 本队经济差</span><span>${opts.note || `${values.length} 个采样点`}${eventLines ? ' · 金色虚线为关键节点' : ''}${rich && duration > 0 ? ' · 底色为前 / 中 / 后期' : ''}</span></div></div>`;
}

function microChart(points, label) {
  const data=(points||[]).filter(p=>has(p[0])&&has(p[1])).sort((a,b)=>a[0]-b[0]);
  if(data.length<2)return '<div class="micro-empty">暂无完整时间轴</div>';
  const max=Math.max(1,...data.map(p=>Math.abs(p[1]))), x0=data[0][0], x1=data.at(-1)[0];
  const x=v=>4+(v-x0)/(x1-x0||1)*292, y=v=>40-v/max*32;
  const d=data.map((p,i)=>`${i?'L':'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
  return `<svg class="micro-chart" viewBox="0 0 300 80" role="img" aria-label="${esc(label)}，${data.length} 个采样点，最后经济差 ${diff(data.at(-1)[1])}"><line x1="4" y1="40" x2="296" y2="40" class="grid-line"/><path d="${d}" class="curve"/><circle cx="${x(data.at(-1)[0])}" cy="${y(data.at(-1)[1])}" r="3" class="depth-dot"/></svg>`;
}

const MATCH_ROWS_OPEN = 24;
function matchRows(rows) {
  if (!rows.length) return `<div class="empty">当前范围暂无对局。</div>`;
  const item = (m) => `<div class="match-row-wrap">
    <a class="match-row" href="${esc(route('match', m.key))}">
    <div class="match-date"><b>${esc((m.date || '日期未知').slice(5))}</b><small>${esc((m.date || '').slice(0,4))}</small></div>
    <div class="match-opponent"><small>${m.isSeed ? '验证对局' : esc(m.mode || '对局记录')}</small><b>${esc(m.opponent ? '对阵 ' + m.opponent : '对手未标注')}</b></div>
    <span class="result ${esc(m.result)}">${esc(resultName[m.result] || '未知')}</span>
    <strong class="row-score">${score(m)}</strong><span class="match-duration">${time(m.duration)}</span>
    <div class="small-lineup">${(m.heroes || []).slice(0, 5).map((hero) => portrait(hero)).join('')}</div>
    <span class="row-arrow">${icon('arrow')}</span></a>
    <button type="button" class="match-edit" data-match-edit="${esc(m.key)}" data-opponent="${esc(m.opponent || '')}" title="编辑对手队名" aria-label="编辑对手队名">✎</button>
  </div>`;
  /* 一屏只铺 24 行：54 场的档案页会拉到 4000px 高，而教练真正要找的
     往往是最近几局。其余收进折叠区，搜索仍走同一套渲染。 */
  const head = rows.slice(0, MATCH_ROWS_OPEN), rest = rows.slice(MATCH_ROWS_OPEN);
  return `<div class="match-list">${head.map(item).join('')}</div>
    ${rest.length ? `<details class="match-more"><summary>还有 ${rest.length} 场，展开</summary>
      <div class="match-list">${rest.map(item).join('')}</div></details>` : ''}`;
}

/** 编辑对手队名：写 match_meta 覆盖层（不改原始数据包）。 */
function opponentDialog(key, current) {
  const dialog = document.querySelector('#filters');
  dialog.innerHTML = `<form id="opponent-form" data-key="${esc(key)}"><div class="dialog-head"><div><h2>编辑对手队名</h2><p>只影响本机显示与统计，不改原始数据包；留空表示「对手未标注」。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><label>对手战队/队名<input name="opponent" maxlength="50" value="${esc(current)}" placeholder="例如：漂流网咖"></label>
    <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">保存</button></div></form>`;
  dialog.showModal();
  dialog.querySelector('input[name="opponent"]')?.focus();
}

/* 第一次打开、库里还没有对局时，先给三条把数据拿进来的路。
   这里不做「空状态」解释，教练此刻需要的是下一步动作。 */
function welcomePage() {
  return `<div class="page welcome-page">
    <section class="welcome-hero">
      <span class="welcome-eyebrow">第一次使用</span>
      <h1>先把第一局拿进来</h1>
      <p>这个工作台不自带比赛数据。三种方式任选一种，三分钟就能看到一场完整复盘；之后每天打开它，新对局会排到待处理。</p>
    </section>
    <div class="welcome-paths">
      <a class="welcome-path is-primary" href="#ingest">
        <span class="welcome-no">01 · 推荐</span>
        <b>扫码采集</b>
        <p>教练号扫码授权一次，之后每天拉取最近的训练赛。BP 与十人面板最完整。</p>
        <em>适合已经在打训练赛</em>
      </a>
      <button class="welcome-path" data-action="open-client">
        <span class="welcome-no">02 · 复盘</span>
        <b>打开桌面客户端</b>
        <p>工作台负责采集与缺失值审查，客户端负责逐分钟复盘；两边读同一套本机数据。</p>
        <em>需要先安装客户端</em>
      </button>
      <a class="welcome-path" href="#capture">
        <span class="welcome-no">03 · 兜底</span>
        <b>导入表格 / 截图</b>
        <p>已经有赛后表格、七张截图或录屏，直接从文件开始；没有营地授权也能用。</p>
        <em>适合先补一局</em>
      </a>
    </div>
    <section class="welcome-foot">
      <div><span>数据目录</span><code data-welcome-dir>正在读取…</code></div>
      <div class="welcome-actions">
        <button class="control" data-action="open-data">打开数据目录</button>
        <button class="control" data-action="refresh">我已经有数据</button>
      </div>
    </section>
    <div class="welcome-legacy" data-welcome-legacy hidden></div>
    <div class="welcome-migrate" data-migrate-progress hidden></div>
    <details class="welcome-other">
      <summary>旧数据在别的位置</summary>
      <div class="welcome-other-row">
        <input class="control" type="text" data-welcome-path spellcheck="false"
          placeholder="粘贴旧数据目录，例如 D:\\KPL训练赛项目\\data">
        <button class="control" data-action="migrate-path">搬到这台电脑</button>
      </div>
      <label class="welcome-check"><input type="checkbox" data-migrate-heavy checked> 连同回放与录屏一起搬（热区、深度分析要用）</label>
      <p>只读取旧目录，不改动它；这台电脑的库里已经有对局时不会执行。</p>
    </details>
  </div>`;
}

/* 搬迁进度：字节 / 文件数都来自后端任务状态，页面只负责显示。 */
let migrateTimer = null;

function sizeText(bytes) {
  if (!has(bytes) || bytes <= 0) return '';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const MIGRATE_LABELS = {
  scanning: '正在清点旧文件…',
  copying: '正在搬文件',
  database: '正在合并比赛数据…',
  upgrading: '正在升级数据结构…',
  merging: '正在放进数据目录…',
  done: '搬完了，正在重新读取…',
  error: '没有搬完',
};

function paintMigration(job) {
  const panel = document.querySelector('[data-migrate-progress]');
  if (!panel) return;
  panel.hidden = false;
  panel.classList.toggle('is-error', job.state === 'error');
  const total = Math.max(1, job.totalBytes || 0);
  const ratio = (job.bytes || 0) / total;
  const percent = job.state === 'done' ? 100 : Math.min(97, Math.round(ratio * 100));
  const shown = percent === 0 && job.bytes ? '<1' : String(percent);
  const label = job.state === 'copying'
    ? `正在搬文件 ${fmt(job.copied || 0)} / ${fmt(job.totalFiles || 0)}`
    : (MIGRATE_LABELS[job.state] || '正在搬…');
  const amount = sizeText(job.bytes) && job.totalBytes ? ` · ${sizeText(job.bytes)} / ${sizeText(job.totalBytes)}` : '';
  panel.innerHTML = `<div class="welcome-bar"><i style="width:${percent || (job.bytes ? 2 : 0)}%"></i></div>
    <div class="welcome-migrate-line"><span>${esc(label + amount)}</span><em>${shown}%</em></div>
    ${job.state === 'copying' && job.current ? `<code>${esc(job.current)}</code>` : ''}
    ${job.state === 'error' ? `<p>${esc(job.error || '请再试一次；原来的数据没有被改动。')}</p>` : ''}`;
}

async function startMigration(path, includeReplays) {
  if (migrateTimer) { clearTimeout(migrateTimer); migrateTimer = null; }
  paintMigration({ state: 'scanning', bytes: 0, totalBytes: 0 });
  try {
    const response = await fetch(API_BASE + '/api/data/migrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, includeReplays: !!includeReplays }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '搬迁没有开始，请重试。');
  } catch (error) {
    paintMigration({ state: 'error', error: error.message });
    return;
  }
  const poll = async () => {
    let job;
    try {
      job = await get('data/migrate');
    } catch {
      migrateTimer = setTimeout(poll, 1500);
      return;
    }
    paintMigration(job);
    if (job.state === 'done') { migrateTimer = null; await load(true); return; }
    if (job.state === 'error') { migrateTimer = null; return; }
    migrateTimer = setTimeout(poll, 600);
  };
  migrateTimer = setTimeout(poll, 400);
}

async function hydrateWelcome() {
  const label = document.querySelector('[data-welcome-dir]');
  if (!label) return;
  try {
    const info = await get('welcome');
    if (!label.isConnected) return;
    label.textContent = info.dataDir || 'data';
    const box = document.querySelector('[data-welcome-legacy]');
    if (box && Array.isArray(info.legacy) && info.legacy.length) {
      box.hidden = false;
      const old = info.legacy[0];
      const when = old.modified ? new Date(old.modified * 1000).toLocaleDateString('zh-CN') : '';
      box.innerHTML = `<div class="welcome-legacy-head"><b>发现旧数据</b>
          <span>${fmt(old.matches || 0)} 局${when ? ` · 最后更新 ${esc(when)}` : ''}</span></div>
        <p><code>${esc(old.path)}</code> 是之前那份训练数据，可以整库搬过来，不用自己复制文件夹。</p>
        <div class="welcome-legacy-actions">
          <button class="control is-primary" data-action="migrate-legacy" data-path="${esc(old.path)}">搬到这台电脑</button>
          <label class="welcome-check"><input type="checkbox" data-migrate-heavy checked> 连同回放与录屏（热区、深度分析要用，体积大）</label>
        </div>`;
    }
  } catch {
    if (label.isConnected) label.textContent = 'data';
  }
}

function overview(value) {
  const { summary, matches, team, process } = value;
  /* 空库：首屏直接给三条路，不留一页「0 局」。 */
  if (!summary.matches) return welcomePage();
  const latest = matches[0];
  const duration = matches.map((m) => m.duration).filter((value) => has(value) && value > 0);
  const avgDuration = duration.length ? duration.reduce((a, b) => a + b, 0) / duration.length : null;
  /* 第一句就是结论：这批局打成什么样，数字直接进标题。 */
  const decided = summary.decided || 0;
  const wins = summary.wins || 0;
  const losses = Math.max(0, decided - wins);
  const goldDiff = team.avgGoldDiff;
  /* 样本太少就别下「全胜」的结论，先如实报几胜几负。 */
  const record = decided >= 3
    ? (losses === 0 ? `${fmt(decided)} 局全胜` : `${fmt(decided)} 局 ${fmt(wins)} 胜 ${fmt(losses)} 负`)
    : decided
      ? `${fmt(summary.matches)} 局 ${fmt(wins)} 胜${losses ? ` ${fmt(losses)} 负` : ''}`
      : `${fmt(summary.matches)} 局训练赛`;
  const margin = has(goldDiff)
    ? `，${decided > 1 ? '场均' : ''}${goldDiff >= 0 ? '领先' : '落后'} ${fmt(Math.abs(goldDiff))} 金`
    : '';
  const dates = [...new Set(matches.map((m) => m.date).filter(Boolean))].sort();
  const range = dates.length > 1 ? `${dates[0]} → ${dates.at(-1)}` : `截至 ${dates[0] || '日期未知'}`;
  const meta = `${range} · ${fmt(summary.matches)} 局 · 营地终局面板 + 回放时间轴`;
  const featured = latest ? `<article class="featured"><div class="featured-top"><span class="live-mark">最近对局</span>
    <span>${esc(latest.date || '日期未知')} &nbsp; / &nbsp; ${time(latest.duration)}</span></div>
    <div class="versus"><div class="versus-team"><small>${esc(sides[latest.ownCamp] || '本队')}</small><strong>${esc(summary.teamName || '本队')}</strong><span>本队</span></div>
    <div class="versus-score"><small class="${esc(latest.result)}">${esc(resultName[latest.result] || '未知')}</small><b>${score(latest)}</b></div>
    <div class="versus-team rival"><small>对手</small><strong>${esc(latest.opponent || '未标注')}</strong><span>对方战队</span></div></div>
    <div class="featured-bottom"><div class="lineup"><span class="lineup-label">本队阵容</span>${(latest.heroes || []).slice(0,5).map((hero) => `<div class="lineup-person">${portrait(hero)}<small>${esc(hero)}</small></div>`).join('') || '—'}</div>
      <a class="featured-link" href="${esc(route('match', latest.key))}">查看对局 ${icon('arrow')}</a></div></article>`
    : `<article class="featured featured-empty"><h2>暂无对局记录</h2><p>导入训练赛后，这里会显示最近一场对局。</p></article>`;
  const hero = summary.topHeroes?.[0];
  const heroId = hero && /^\/catalog\/icons\/hero-(\d+)\.png$/.exec(metadata.icons?.[hero.hero] || '')?.[1];
  const art = heroId === '140' ? API_BASE + '/static/media/hero-140.jpg'
    : heroId ? `https://game.gtimg.cn/images/yxzj/img201606/skin/hero-info/${heroId}/${heroId}-bigskin-1.jpg` : '';
  const spotlight = hero ? `<a class="spotlight" href="${esc(route('matches', 'hero=' + hero.hero))}"${art ? ` style="background-image:linear-gradient(180deg,rgba(10,18,28,.03) 5%,rgba(10,18,28,.22) 45%,rgba(10,18,28,.95) 100%),url('${art}')"` : ''}>
    <div class="spotlight-head"><span>英雄观察</span><span>${icon('arrow')}</span></div>
    <div class="spotlight-copy"><span>本队出场最多</span><h2>${esc(hero.hero)}</h2>
      <div class="spotlight-details"><span><b>${fmt(hero.picks)}</b> 次出场</span><span><b>${pct(hero.winRate)}</b> 胜率 / ${hero.decided} 局</span></div></div></a>`
    : `<div class="spotlight no-hero"><div class="spotlight-copy"><span>英雄观察</span><h2>暂无出场数据</h2></div></div>`;
  const p = process.matches[0];
  /* 首页看的是这一批，不是最后一局：按 30 秒对齐求平均。
     后段只剩一两局在撑，样本不足就截断，免得尾巴把结论带偏。 */
  const games = (process.matches || []).filter((game) => (game.points || []).length);
  const buckets = new Map();
  games.forEach((game) => (game.points || []).forEach(([t, v]) => {
    if (!has(t) || !has(v)) return;
    const key = Math.round(t / 30) * 30;
    const cell = buckets.get(key) || { sum: 0, n: 0 };
    cell.sum += v;
    cell.n += 1;
    buckets.set(key, cell);
  }));
  const grid = [...buckets.entries()].sort((a, b) => a[0] - b[0]);
  const enough = Math.max(3, Math.round(games.length * 0.45));
  let last = grid.length - 1;
  while (last >= 0 && grid[last][1].n < enough) last -= 1;
  const avgCurve = last >= 1 ? grid.slice(0, last + 1).map(([t, cell]) => [t, Math.round(cell.sum / cell.n)]) : [];
  const useAvg = games.length >= 3 && avgCurve.length >= 2;
  const curve = useAvg ? avgCurve : (p?.points || []);
  const curveNote = useAvg
    ? `近 ${games.length} 局平均 · 每 30 秒一个点 · 截到 ${time(avgCurve.at(-1)[0])}（更长的局样本不足）`
    : (p ? `${p.date || '日期未知'} · 对阵 ${p.opponent || '对手未标注'} · 最近一局` : '最近可用对局');
  return `<div class="page home">
    ${pageIntro(`${record}${margin}`, meta, filters.validation ? '<span class="scope-chip">含验证数据</span>' : '')}
    <div class="home-decision" id="home-decision" data-home-decision></div>
    <div class="feature-grid">${featured}${spotlight}</div>
    <div class="stats-band"><div><span>对局总数</span><strong>${fmt(summary.matches)}<small>局</small></strong><p>${fmt(summary.coverage.timelineMatches)} 局时间轴完整</p></div>
      <div><span>平均对局时长</span><strong>${time(avgDuration)}</strong><p>${duration.length} 局有时长</p></div>
      <div><span>场均击杀</span><strong>${fmt(team.avgKills, 1)}</strong><p>本队五人合计</p></div>
      <div><span>场均经济</span><strong>${fmt(team.avgGold)}</strong><p>本队五人终局合计</p></div></div>
    <div class="insight-grid"><section class="section curve-section"><div class="section-heading"><div><h2>经济走势</h2>
      <p>${esc(curveNote)}</p></div>
      <a href="#tempo">查看节奏分析 ${icon('arrow')}</a></div>${chart(curve, useAvg ? '这批局的平均经济差' : '本队经济差', useAvg ? { note: `${games.length} 局平均 · ${curve.length} 个时间点` } : {})}</section>
      <section class="section heroes-section"><div class="section-heading"><div><h2>英雄出场</h2><p>本队当前样本</p></div>
        <a href="#bp">查看全部 ${icon('arrow')}</a></div>
        <div class="hero-rows">${(summary.topHeroes || []).slice(0,5).map((h) => `<a href="${esc(route('matches', 'hero=' + h.hero))}" class="hero-row">
          ${portrait(h.hero)}<div><b>${esc(h.hero)}</b><small>${esc((h.positions || []).join(' / ') || '分路未知')}</small></div>
          <span>${fmt(h.picks)}<small>次出场</small></span><span>${pct(h.winRate)}<small>${h.wins} / ${h.decided} 局</small></span></a>`).join('') || '<div class="empty">暂无英雄数据。</div>'}</div></section></div>
    <section class="section matches-section"><div class="section-heading"><div><h2>对局记录</h2><p>查看比分、阵容与复盘详情</p></div>
      <a href="#matches">全部对局 ${icon('arrow')}</a></div>${matchRows(matches.slice(0,5))}</section>
  </div>`;
}

/* 数据明细折叠已按产品要求全站下线；保留函数签名以兼容既有调用点。 */
function table() { return ''; }

function matchesPage(value, key) {
  const hero = key.startsWith('hero=') ? key.slice(5) : '';
  const rows = value.matches.filter((m) => !hero || (m.heroes || []).includes(hero))
    .filter((m) => !view.search || [m.opponent, m.title, m.date, ...(m.heroes || [])].some((x) => String(x || '').toLowerCase().includes(view.search.toLowerCase())));
  const won=rows.filter(m=>m.result==='win').length,lost=rows.filter(m=>m.result==='loss').length,decided=won+lost;
  const summary=`<div class="match-overview"><div><span>当前对局</span><strong>${fmt(rows.length)} <small>场</small></strong><p>当前筛选与搜索范围</p></div><div><span>本队战绩</span><strong>${fmt(won)} <i>胜</i> ${fmt(lost)} <i>负</i></strong><p>${fmt(rows.length-decided)} 场结果未计入胜负</p></div><div class="match-overview-bar"><span>有胜负对局的胜率</span><strong>${pct(decided?won/decided*100:null)}</strong><div><i style="width:${decided?won/decided*100:0}%"></i></div><p>按 ${fmt(decided)} 场有胜负的对局计算</p></div></div>`;
  return `<div class="page">${pageIntro('对局档案', '查找对局并查看比赛详情。')}
    ${summary}<section class="section"><div class="section-heading"><div><h2>${hero ? esc(hero) + '的对局' : '对局记录'}</h2><p data-result-count>${rows.length} 场记录</p></div>
    <label class="search">${icon('search')}<input type="search" name="search" value="${esc(view.search || '')}" placeholder="搜索对手、英雄或日期" aria-label="搜索对局"></label></div>
    <div data-results>${matchRows(rows)}</div></section></div>`;
}

function playersPage(value) {
  const roster = value.roster || [];
  const formById = new Map((value.form || []).map((item) => [item.id, item]));
  const summary = value.summary || {};
  const unbound = value.unbound || [];
  const pairs = value.pairs || [];
  const toneName = { up: '上升', down: '下滑', flat: '持平' };
  const shortDate = (x) => (x ? String(x).slice(5) : '');
  const chip = (item, games) => !games || !item || !item.samples ? '' : item.available
    ? `<em class="form-chip ${esc(item.tone)}">${item.tone === 'up' ? '↑' : item.tone === 'down' ? '↓' : '→'} ${esc(toneName[item.tone])}</em>`
    : '<em class="form-chip muted">样本不足</em>';
  const formLine = summary.formReady
    ? `状态可判断 ${summary.formReady} 人${summary.rising || summary.falling ? `（上升 ${summary.rising}、下滑 ${summary.falling}）` : ''}`
    : '状态样本还不够 6 场';
  const brief = [`当前范围 ${fmt(summary.matches)} 局`,
    roster.length ? `名单 ${roster.length} 人、${fmt(summary.played)} 人出场${summary.bench ? `、${fmt(summary.bench)} 人未出场` : ''}` : '名单还没建立',
    formLine,
    unbound.length ? `未认领昵称 ${unbound.length} 个、${fmt(summary.unboundGames)} 局` : ''].filter(Boolean).join('，') + '。';
  const card = (p) => {
    const item = formById.get(p.id);
    return `<a class="player-profile" href="${esc(route('player', p.id))}"><div class="player-profile-top"><span class="player-monogram">${esc((p.label || '?').slice(0, 2))}</span><div><h3>${esc(p.label)}</h3><p>${esc(p.position || '位置待填写')} ${chip(item, p.games)}</p></div><span class="player-arrow">↗</span></div><div class="player-metrics"><div><small>出场</small><strong>${fmt(p.games)}</strong></div><div><small>胜率</small><strong>${pct(p.winRate)}</strong></div><div><small>KDA</small><strong>${fmt(p.kda, 2)}</strong></div></div><div class="player-hero-strip">${(p.heroes || []).map((h) => portrait(h.hero)).join('')}<small>${p.lastDate ? '最近 ' + esc(shortDate(p.lastDate)) : '暂无记录'}</small></div></a>`;
  };
  const bench = roster.filter((p) => !p.played);
  const formRows = roster.map((p) => {
    const item = formById.get(p.id);
    if (!item || !item.samples) return '';
    const shown = item.available;
    return `<div class="form-row"><span class="nm">${esc(p.label)}</span><span class="lane">${esc(p.position || '—')}</span><span class="val">${shown ? fmt(item.prior, 1) : '—'}</span><i>→</i><span class="val now">${shown ? fmt(item.recent, 1) : '—'}</span><span class="delta ${shown ? esc(item.tone) : ''}">${shown ? diff(item.delta) : ''}</span><span class="tone ${shown ? esc(item.tone) : 'muted'}">${shown ? esc(toneName[item.tone]) : '样本不足'}</span></div>`;
  }).join('');
  const pairsShown = pairs.slice(0, 4);
  const pairRows = pairsShown.map((pair) => `<div class="pair-row"><span class="names">${esc(pair.a.label)} <i>+</i> ${esc(pair.b.label)}</span><span class="meta">同场 ${fmt(pair.games)} 场 · ${fmt(pair.wins)} 胜</span><strong>${pct(pair.winRate)}</strong></div>`).join('');
  const rosterById = new Map(roster.map((p) => [p.id, p]));
  const bound = (value.players || []).filter((p) => p.bound);
  const rows = bound.map((p) => {
    const member = rosterById.get(p.playerId);
    const lane = member ? member.position : (p.positions || []).join(' / ');
    return [`<a class="text-link" href="${esc(route('player', p.playerKey))}">${esc(p.label)}</a>`, esc(lane || '—'), fmt(p.matches), pct(p.winRate), fmt(p.kda, 2), fmt(p.gpm, 1), fmt(p.dpm, 1), pct(p.participation)];
  });
  const emptyRoster = '<div class="empty">本队名单还没建立。先在「赛训 → 数据准备 → 建档」登记选手，或在「选手认领」把对局昵称并入名单。</div>';
  return `<div class="page">${pageIntro('名单与状态', '谁在打、谁状态在变、谁和谁能搭。名单取自建档，表现只统计已认领身份。')}
    <div class="analysis-observation"><span>结论</span><p>${esc(brief)}</p></div>
    ${unbound.length ? `<div class="scope-note"><span>身份待认领</span>还有 ${fmt(unbound.length)} 个昵称没有并入名单（${fmt(summary.unboundGames)} 局），不计入名单、状态与排名。命名入口在下方「待命名」。</div>` : ''}
    <section class="section"><div class="section-heading"><div><h2>名单与轮换</h2><p>位置取自名单；出场为当前范围内的已认领记录</p></div><a href="#identity">管理名单 ${icon('arrow')}</a></div>
      <div class="player-card-grid">${roster.map(card).join('') || emptyRoster}</div>
      ${bench.length ? `<p class="roster-bench"><span>本期未出场</span>${bench.map((p) => esc(p.label) + (p.position ? '（' + esc(p.position) + '）' : '')).join('、')}</p>` : ''}</section>
    ${unbound.length ? `<section class="section"><div class="section-heading"><div><h2>待命名</h2><p>给昵称起名并归队后，这些局会并入该选手的长期档案</p></div></div>
      <div class="name-queue">${unbound.map((item) => `<div class="name-row"><span class="nm">${esc(item.label)}</span><span class="meta">${fmt(item.games)} 局${item.lastDate ? ' · 最近 ' + esc(shortDate(item.lastDate)) : ''}</span><button class="primary" data-action="name-player" data-label="${esc(item.label)}">命名并归队</button></div>`).join('')}</div></section>` : ''}
    <div class="split-panels">
      <section class="section"><div class="section-heading"><div><h2>状态变化</h2><p>同一名选手近 3 场与此前 3 场的营地评分，不跨选手排名</p></div></div>
        ${formRows ? `<div class="form-rows"><div class="form-row head"><span>选手</span><span>位置</span><span>此前</span><i></i><span>近 3 场</span><span>变化</span><span>判断</span></div>${formRows}</div>` : `<div class="empty">${(value.form || []).some((item) => item.samples) ? '还没有已认领选手的评分记录。' : '当前范围的记录还没有营地评分，状态要等评分数据补齐。'}</div>`}
        <p class="section-note">少于 6 场不给趋势结论；评分来自营地结算。</p></section>
      <section class="section"><div class="section-heading"><div><h2>搭档</h2><p>同场 3 场以上的双人组合，只用已认领身份</p></div></div>
        ${pairRows ? `<div class="pair-rows">${pairRows}</div>` : '<div class="empty">同场 3 场以上的固定组合还不够。</div>'}
        <p class="section-note">同场指同一局同时出场，未要求完整五人阵容。${pairs.length > 1 && pairs.every((pair) => pair.games === pairs[0].games) ? ' 当前这套阵容基本固定，组合之间没有差别。' : ''}</p></section>
    </div>
    <section class="section"><div class="section-heading"><div><h2>已认领选手数据</h2><p>${bound.length} 名已认领选手；未认领昵称不计入</p></div></div>
      ${bound.length ? `<details class="table-disclosure"><summary>查看数据明细 <span>${bound.length} 名</span></summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>选手</th><th>位置</th><th>出场</th><th>胜率</th><th>KDA</th><th>分均经济</th><th>分均输出</th><th>参团率</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>` : '<div class="empty">还没有已认领选手。先在「选手认领」把对局昵称并入名单。</div>'}
      </section>
  </div>`;
}

function playerPage(value) {
  const p = value.stats;
  const label = (p && p.label) || value.label || '';
  const games = (p && p.matches) || 0;
  const lane = p && (p.positions || []).length ? p.positions.join(' / ') : '位置待填写';
  const rows = [...value.points].reverse().map((m) => [`<a class="text-link" href="${esc(route('match', m.matchKey))}">${esc(m.date || '日期未知')}</a>`,
    esc(m.opponent || '未标注'), `<span class="table-hero">${portrait(m.hero)}${esc(m.hero || '未知')}</span>`,
    esc(resultName[m.result] || '未知'), fmt(m.kda,1), fmt(m.gpm,1), fmt(m.dpm,1)]);
  const heroes = p ? (p.heroes || []).slice(0, 6) : [];
  const rated = (value.points || []).map((m) => m.rating).filter((v) => has(v));
  const formHtml = rated.length < 6
    ? `<p class="section-note">评分 ${rated.length} 场，少于 6 场，不判断趋势。</p>`
    : (() => {
        const prior = rated.slice(-6, -3), recent = rated.slice(-3);
        const priorMean = prior.reduce((a, b) => a + b, 0) / prior.length;
        const recentMean = recent.reduce((a, b) => a + b, 0) / recent.length;
        const delta = recentMean - priorMean;
        const tone = delta >= 0.5 ? 'up' : delta <= -0.5 ? 'down' : 'flat';
        const word = { up: '上升', down: '下滑', flat: '持平' }[tone];
        return `<div class="pl-form"><span><small>此前 3 场</small><b>${fmt(priorMean, 1)}</b></span><i>→</i><span><small>近 3 场</small><b>${fmt(recentMean, 1)}</b></span><span class="pl-form-tag ${tone}">${delta >= 0 ? '+' : ''}${fmt(delta, 1)} · ${word}</span></div><p class="section-note">评分来自营地结算；比的是同一名选手自己，不跨选手排名。</p>`;
      })();
  const crumb = `<div class="md-crumb">
    <a class="md-back" href="#players"><span aria-hidden="true">←</span> 名单与状态</a>
    <span class="md-crumb-meta">${[lane, games ? `${fmt(games)} 局` : '', p && p.bound ? '已归队' : '待命名'].filter(Boolean).map((x) => `<i>${esc(x)}</i>`).join('')}</span>
    <span class="md-crumb-actions">${p && !p.bound ? `<button class="primary" data-action="name-player" data-label="${esc(label)}">命名并归队</button>` : ''}<button class="control" data-action="filter">${icon('filter')} 数据范围</button><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></span>
  </div>`;
  const claim = !p ? '当前范围没有该选手的数据'
    : p.bound ? `${p.label} 在 ${lane} 出场 ${fmt(games)} 局，胜率 ${pct(p.winRate)}`
    : `「${p.label}」还没命名，${fmt(games)} 局的记录暂时挂在这个昵称下`;
  const fact = !p ? '换一个数据范围试试'
    : p.bound ? `KDA ${fmt(p.kda, 1)} · 分均经济 ${fmt(p.gpm, 1)} · 参团率 ${pct(p.participation)}`
    : '命名并归队后，这些记录会并入该选手的长期档案';
  const hero = `<section class="md-hero">
    <div class="md-hero-head"><span class="md-hero-kicker">${p && p.bound ? '选手结论' : '身份待定'}</span><span class="md-hero-meta">${[lane, p && p.bound ? '已归队' : '待命名'].filter(Boolean).map(esc).join(' · ')}</span></div>
    <h1><b>${esc(claim)}</b><span>${esc(fact)}</span></h1>
    <div class="md-line">
      <div class="md-line-side"><span>出场</span><b>${fmt(games)} 局</b></div>
      <div class="md-line-mid"><strong>${fmt(p && p.kda, 1)}<i>KDA</i></strong><div class="md-line-note"><em class="${p && p.winRate >= 50 ? 'win' : 'loss'}">${pct(p && p.winRate)}</em><span>胜率</span></div></div>
      <div class="md-line-side rival"><span>分均经济</span><b>${fmt(p && p.gpm, 1)}</b></div>
    </div>
    <p>口径：当前数据范围内的本队记录；营地面板与回放来源分开统计，未归队时只按这个昵称算。</p>
  </section>`;
  return `<div class="page md-page">${crumb}${hero}
    <div data-player-analyses data-player-label="${esc(label)}">
      <section class="section"><div class="section-heading"><div><h2>同位置参照</h2><p>与同分路的已记录样本比较，条形共用一条标尺</p></div><a href="#topic/compare_baseline">全部选手 ${icon('arrow')}</a></div>
        <div data-analysis="baseline"><div class="empty">正在读取同位置样本…</div></div></section>
      <section class="section"><div class="section-heading"><div><h2>分路对位</h2><p>同分路对手的终局经济与 KDA 差，按时间倒序</p></div><a href="#topic/lane_matchup">全部选手 ${icon('arrow')}</a></div>
        <div data-analysis="lane"><div class="empty">正在读取对位记录…</div></div></section>
      <section class="section"><div class="section-heading"><div><h2>补刀与产出</h2><p>补刀 → 经济 → 输出，看链条断在哪一段</p></div><a href="#topic/cs_conversion">全部选手 ${icon('arrow')}</a></div>
        <div data-analysis="cs"><div class="empty">正在读取补刀记录…</div></div></section>
    </div>
    <section class="section"><div class="section-heading"><div><h2>状态</h2><p>同一名选手近 3 场与此前 3 场的营地评分</p></div></div>${formHtml}</section>
    <div data-player-analyses data-player-label="${esc(label)}">
      <section class="section"><div class="section-heading"><div><h2>搭档</h2><p>同场 3 场以上、身份已认领的双人组合</p></div><a href="#study/player_pairs">全部选手 ${icon('arrow')}</a></div>
        <div data-analysis="pairs"><div class="empty">正在读取搭档记录…</div></div></section>
    </div>
    ${heroes.length ? `<section class="section"><div class="section-heading"><div><h2>常用英雄</h2><p>按出场次数</p></div></div><div class="hero-chips player-heroes">${heroes.map((h) => `<span>${portrait(h.hero)}${esc(h.hero)} <small>${fmt(h.matches)} 局</small></span>`).join('')}</div></section>` : ''}
    <section class="section"><div class="section-heading"><div><h2>近期对局</h2><p>点击比赛可回看完整记录</p></div><a href="#players">返回选手</a></div>
    <div class="player-history">${[...value.points].reverse().slice(0,8).map(m=>`<a href="${esc(route('match',m.matchKey))}"><span>${esc(m.date||'日期未知')}</span>${portrait(m.hero)}<b>${esc(m.hero||'未知英雄')}</b><small>${esc(m.opponent||'对手未标注')}</small><strong>${fmt(m.kda,1)} <i>KDA</i></strong></a>`).join('')||'<div class="empty">暂无逐局记录。</div>'}</div><details class="table-disclosure"><summary>查看全部逐局 <span>${rows.length} 条</span></summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>日期</th><th>对手</th><th>英雄</th><th>赛果</th><th>KDA</th><th>分均经济</th><th>分均输出</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details></section></div>`;
}

function playerBaseline(payload) {
  const row = (payload.rows || [])[0];
  if (!row || !row.metrics) return '<div class="empty">这名选手还没有可用于同位置比较的记录。</div>';
  const metrics = [['gpm', '分均经济'], ['dpm', '分均输出'], ['participation', '参团率'], ['goldShare', '经济占比'], ['damageShare', '输出占比']];
  const shares = new Set(['participation', 'goldShare', 'damageShare']);
  const show = (key, n) => shares.has(key) ? pct(n) : fmt(n, 0);
  const rows = metrics.map(([key, name]) => {
    const m = row.metrics[key];
    if (!m || !has(m.value)) return `<div class="pl-cmp-row"><span class="k">${name}</span><span class="md-phase-cell own"><b>—</b></span><span class="md-phase-cell enemy"><b>—</b></span><span class="num">无样本</span></div>`;
    const scale = Math.max(Math.abs(m.value), Math.abs(m.baseline || 0), Math.abs(m.p90 || 0)) || 1;
    const own = Math.max(0, Math.min(1, Math.abs(m.value) / scale));
    const base = Math.max(0, Math.min(1, Math.abs(m.baseline || 0) / scale));
    const percentile = has(m.percentile) ? Math.round(m.percentile) : null;
    return `<div class="pl-cmp-row"><span class="k">${name}</span><span class="md-phase-cell own" style="--v:${own.toFixed(3)}"><b>${show(key, m.value)}</b></span><span class="md-phase-cell enemy" style="--v:${base.toFixed(3)}"><b>${show(key, m.baseline)}</b></span><span class="num">${percentile == null ? '样本不足' : `超过 ${percentile}%`}</span></div>`;
  }).join('');
  return `<div class="pl-cmp"><div class="pl-cmp-head"><span>指标</span><span>本人</span><span>同位置基准</span><span class="num">分位</span></div>${rows}</div>
    <div class="md-phase-legend"><span class="own">本人</span><span class="enemy">同位置基准</span><span class="md-phase-legend-note">同位置 ${esc(row.lane || '未记录')} · 参照池 ${fmt((row.metrics.gpm || {}).n)} 行；分位只描述这批样本内的相对位置</span></div>`;
}

function playerLanes(payload) {
  const roads = (payload.roads || []).slice().reverse();
  if (!roads.length) return '<div class="empty">没有可判定的同分路对位记录。</div>';
  const shown = roads.slice(0, 8);
  const rows = shown.map((road) => {
    const when = String(road.label || '').replace(' · 训练赛', '');
    const lead = has(road.goldDiff) ? road.goldDiff : null;
    const kda = !has(road.kdaDiff) ? '—' : Math.abs(road.kdaDiff) < 0.05 ? '0.0' : (road.kdaDiff > 0 ? '+' : '') + fmt(road.kdaDiff, 1);
    return `<div class="md-node-row pl-node"><span class="md-node-time">${esc(when)}</span><b>${esc(road.ownHero || '—')} <em>vs</em> ${esc(road.enemyHero || '—')}<small>${esc(road.enemyPlayer || '')}</small></b><span class="md-node-num ${lead == null ? '' : lead >= 0 ? 'up' : 'down'}">${lead == null ? '—' : diff(lead)}</span><span class="md-node-num">${kda}</span><span class="md-node-dir ${road.win ? 'own' : 'enemy'}">${road.win ? '胜' : '负'}</span></div>`;
  }).join('');
  return `<div class="md-node-head pl-node"><span>时间</span><span>对位</span><span>经济差</span><span>KDA 差</span><span>结果</span></div><div class="md-node-list">${rows}</div>
    <p class="section-note">经济差 = 我方 − 对方终局金币；对线结果不是个人能力评价。${roads.length > shown.length ? ` 共 ${roads.length} 场，展示最近 ${shown.length} 场。` : ''}</p>`;
}

function playerCs(payload) {
  const row = (payload.byPlayer || [])[0];
  if (!row) return '<div class="empty">这名选手没有补刀记录。</div>';
  const items = [['补刀', row.cs], ['总经济', row.gold], ['对英雄输出', row.heroDamage], ['转化比', row.conversion]].filter(([, v]) => has(v));
  if (!items.length) return '<div class="empty">这批记录没有补刀字段。</div>';
  const missing = has(row.cs) ? '' : ' 这批记录没有补刀字段，只看到经济与输出。';
  return `<div class="pl-form">${items.map(([name, value]) => `<span><small>${name}</small><b>${fmt(value, name === '转化比' ? 2 : 0)}</b></span>`).join('')}</div><p class="section-note">场均（${fmt(row.n)} 场）；补刀、经济与输出只有终局值，看相关不看作因果。${missing}</p>`;
}

function playerPairs(payload, label) {
  const rows = (payload.rows || []).filter((row) => row.a === label || row.b === label);
  if (!rows.length) return '<div class="empty">没有 3 场以上、且身份已认领的双人组合。</div>';
  return `<div class="md-node-head pl-pair"><span>搭档</span><span>同场</span><span>胜率</span></div><div class="md-node-list">${rows.slice(0, 6).map((row) => {
    const other = row.a === label ? row.b : row.a;
    return `<div class="md-node-row pl-pair"><b>${esc(other)}</b><span class="md-node-num">${fmt(row.n)} 场</span><span class="md-node-num">${pct(row.winRate)}</span></div>`;
  }).join('')}</div><p class="section-note">只统计本队完整五人阵容且身份已认领的对局；Lift 描述共现，不代表协同因果。</p>`;
}

async function hydratePlayer(label) {
  const roots = [...document.querySelectorAll('[data-player-analyses]')];
  if (!roots.length || !label) return;
  const candidates = [...new Set([label, label.split('.').pop()].filter(Boolean))];
  const depthPayload = async (id, ready) => {
    for (const name of candidates) {
      try {
        const response = await fetch(`${API_BASE}/api/depth/analysis/${id}?player=${encodeURIComponent(name)}`, { cache: 'no-store' });
        if (!response.ok) continue;
        const value = await response.json();
        if (ready(value.payload || {})) return value.payload || {};
      } catch {}
    }
    return null;
  };
  const fill = (selector, payload, render) => {
    roots.forEach((root) => {
      const box = root.querySelector(selector);
      if (box && box.isConnected) box.innerHTML = payload ? render(payload) : '<div class="empty">营地面板里还没有这名选手的记录。</div>';
    });
  };
  const [baseline, lane, cs, pairs] = await Promise.all([
    depthPayload('compare_baseline', (payload) => (payload.rows || []).length > 0),
    depthPayload('lane_matchup', (payload) => (payload.roads || []).length > 0),
    depthPayload('cs_conversion', (payload) => (payload.byPlayer || []).length > 0),
    fetch(`${API_BASE}/api/v3/research/player_pairs${query()}`, { cache: 'no-store' }).then((response) => response.ok ? response.json() : null).catch(() => null),
  ]);
  fill('[data-analysis="baseline"]', baseline, playerBaseline);
  fill('[data-analysis="lane"]', lane, playerLanes);
  fill('[data-analysis="cs"]', cs, playerCs);
  fill('[data-analysis="pairs"]', pairs, (payload) => playerPairs(payload, label));
}

function opponentsPage(value) {
  /* 阵容侦察：一行一支对手，看他们五个位置是谁、常打什么英雄。 */
  const lanes = ['对抗路', '打野', '中路', '发育路', '游走'];
  const teams = [...(value.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0) || String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')));
  const named = teams.filter((t) => t.named).length;
  const players = teams.reduce((n, t) => n + (t.players || []).length, 0);
  const laneOf = (p) => lanes.indexOf(p.lane) < 0 ? 99 : lanes.indexOf(p.lane);
  const rows = teams.map((t) => {
    const roster = [...(t.players || [])].sort((a, b) => laneOf(a) - laneOf(b));
    return `<a class="fj-row tm-scout" href="${route('team', t.id)}">
      <span class="tm-crest">${esc((t.displayName || '?').slice(0, 1))}</span>
      <span class="fj-main"><b>${esc(t.displayName)}</b><small>${esc(t.coach ? '教练 ' + t.coach : t.named ? '已建档' : '阵容聚类 · 待命名')}</small></span>
      <span class="tm-scout-roster">${roster.map((p) => `<span><i>${esc(p.lane || '位置未知')}</i><b>${esc(p.name)}</b></span>`).join('') || '<span><i>阵容</i><b>未记录</b></span>'}</span>
      <span class="fj-heroes">${(t.heroes || []).slice(0, 5).map((h) => portrait(h.hero)).join('')}</span>
      <span class="fj-go">→</span></a>`;
  }).join('');
  return `<div class="page feature-page">${pageIntro('对手侦察', `${fmt(teams.length)} 支对手 · ${fmt(players)} 名选手 · ${fmt(named)} 支已命名 · 一行一支，看阵容与常用英雄。`)}
    <div class="fj-lede">
      <span><small>对手战队</small><b>${fmt(teams.length)} 支</b><i>营地阵容聚类</i></span>
      <span><small>对手选手</small><b>${fmt(players)} 人</b><i>五人阵容合计</i></span>
      <span><small>已命名</small><b>${fmt(named)} 支</b><i>${named ? '教练已确认' : '全部待命名'}</i></span>
      <span><small>完整五人</small><b>${fmt(teams.filter((t) => (t.players || []).length >= 5).length)} 支</b><i>可做阵容对位</i></span>
      <span><small>最近交手</small><b>${esc(teams[0]?.lastSeen || '—')}</b><i>${esc(teams[0]?.displayName || '')}</i></span>
    </div>
    <section class="section"><div class="section-heading"><div><h2>阵容侦察</h2><p>位置按营地分路字段排序；右侧是该队这批对局里的常用英雄</p></div></div>
      <div class="fj-list">${rows || '<div class="empty">暂无已识别对手。</div>'}</div></section></div>`;
}

function tempoPage(value) {
  const a = value.process.aggregate;
  const p = value.process.matches[0];
  const anchor = current().anchor;
  const rows = value.process.matches.map((m) => [`<a class="text-link" href="${esc(route('match', m.key))}">${esc(m.date || '日期未知')}　${esc(m.opponent || '未标注')}</a>`,
    pct(m.coverage), diff(m.diffAt['600']), diff(m.finalDiff), fmt(m.killsPerMinute,1)]);
  return `<div class="page">${pageIntro('节奏分析', '查看赛内经济变化与关键时点。')}
    ${gameAnchorBar()}
    <div class="stats-band"><div><span>可分析对局</span><strong>${fmt(a.games)}</strong><p>时间轴覆盖 ≥ 60%</p></div>
    <div><span>10 分钟经济差</span><strong>${diff(a.avgDiffAt['600'])}</strong><p>${a.landmarkSamples['600']} 局可用</p></div>
    <div><span>领先转胜率</span><strong>${pct(a.leadAt10Conversion)}</strong><p>${a.leadAt10Games} 局领先且有胜负</p></div>
    <div><span>落后后获胜</span><strong>${a.landmarkSamples['600'] ? fmt(a.comebacks) : '—'}</strong><p>10 分钟时点</p></div></div>
    <section class="section"><div class="section-heading"><div><h2>最近可用经济曲线</h2><p>${p ? esc(p.date || '') : '暂无样本'}</p></div></div>
    ${chart(p?.points, '本队经济差')}</section>
    <section class="section"><div class="section-heading"><div><h2>逐局经济走势</h2><p>本队减去对手 · 展示最近 9 场有时间轴的对局</p></div></div>
    <div class="tempo-card-grid">${value.process.matches.slice(0,9).map(m=>`<a class="tempo-card${anchor===m.key?' is-anchor':''}" href="${esc(route('match',m.key))}"><div><span>${esc(m.date||'日期未知')}</span><small>${esc(m.opponent||'对手未标注')}</small></div><h3>末次经济差 <strong>${diff(m.finalDiff)}</strong></h3>${microChart(m.points,'本队经济差')}<p><span>${time(m.observedStart)} — ${time(m.observedEnd)}</span><span>覆盖 ${pct(m.coverage)}</span></p></a>`).join('')||'<div class="empty">当前范围暂无可用时间轴。</div>'}</div>
    ${table(['对局', '时间轴覆盖', '10 分钟经济差', '最后采样经济差', '分均击杀'], rows)}</section></div>`;
}

function sourcesPage(value) {
  const checks = value.quality.checks.map((c) => [esc(c.label), `${c.ok} / ${c.total} 局`,
    c.missing ? `缺 ${c.missing} 局` : c.total ? '已覆盖' : '暂无样本', esc(c.hint)]);
  const inventory = value.inventory;
  const rows = [['本机记录', inventory.dbMatches], ['对局数据包', inventory.bundleMatches], ['导入表格对局', inventory.sheetMatches], ['未确认草稿', inventory.drafts]]
    .map(([name, count]) => [esc(name), fmt(count)]);
  return `<div class="page">${pageIntro('数据来源与覆盖', '检查当前样本的字段覆盖情况。')}
    <section class="section"><div class="section-heading"><div><h2>字段覆盖</h2><p>当前筛选范围共 ${value.quality.total} 局</p></div></div>
    <div class="coverage-grid">${value.quality.checks.map(c=>`<article><div><b>${esc(c.label)}</b><span>${fmt(c.ok)} / ${fmt(c.total)} 局</span></div><div class="coverage-track"><i style="width:${c.total?Math.max(0,Math.min(100,c.ok/c.total*100)):0}%"></i></div><p>${esc(c.hint||'')}</p></article>`).join('')}</div>${table(['检查项', '覆盖 / 总数', '状态', '说明'], checks)}</section>
    <section class="section"><div class="section-heading"><div><h2>数据来源</h2><p>已合并的对局可能出现在多个来源中。</p></div></div>
    <div class="source-grid">${[['本机记录', inventory.dbMatches], ['对局数据包', inventory.bundleMatches], ['导入表格对局', inventory.sheetMatches], ['未确认草稿', inventory.drafts]].map(([name,count])=>`<div><span>${esc(name)}</span><strong>${fmt(count)}</strong><small>条记录</small></div>`).join('')}</div>${table(['来源', '局数'], rows)}</section></div>`;
}

/* 10 分钟经济的分路阈值（教练给的：对抗路 / 发育路 6800 及格、7000 良好、7400 优秀）。
   放在模块级，是因为保存后要就地重画评级，不想整页刷新。 */
const GOLD10_GRADES = {
  '对抗路': [[7400, '优秀', 'good'], [7000, '良好', 'ok'], [6800, '及格', 'pass'], [0, '待提升', 'low']],
  '发育路': [[7400, '优秀', 'good'], [7000, '良好', 'ok'], [6800, '及格', 'pass'], [0, '待提升', 'low']],
};
function gold10Grade(lane, value) {
  const defs = GOLD10_GRADES[lane];
  if (!defs || !has(value)) return null;
  for (const [need, label, level] of defs) if (value >= need) return { label, level };
  return null;
}

function matchPage(m) {
  const own = m.ownCamp;
  /* 资源 / 建筑的具体名字。营地 H5 前端把 dtID 编成了「阵营 + 路 + 塔序」：
     getTowerRoad(dtID) / getTowerIndex(dtID) 两个函数是它的原文（已存进
     docs/camp_frontend_labels.json 的同一份前端包里）。路名按各自半区镜像：
     蓝方的「一路」是上路，红方的「一路」是下路。 */
  const TOWER_LANES = { blue: ['上路', '中路', '下路'], red: ['下路', '中路', '上路'] };
  const RESOURCE_NAMES = { 8: '暗影主宰', 9: '暴君', 17: '暗影暴君', 10: '蓝 BUFF', 11: '红 BUFF' };
  const towerName = (id, owner) => {
    const n = Number(id);
    if (n === 10 || n === 20) return '水晶';
    if (!Number.isFinite(n) || n < 1) return '';
    const road = Math.floor((n % 10 - 1) / 3);
    const index = 3 - ((n % 10 - 1) % 3);      /* 1=高地 2=二塔 3=一塔 */
    const lane = (TOWER_LANES[owner] || TOWER_LANES.blue)[road] || '';
    return `${lane}${index === 1 ? '高地塔' : index === 2 ? '二塔' : '一塔'}`;
  };
  /* 事件的显示名：资源看 dtID，建筑看到底是哪一路哪一座。 */
  const eventLabel = (e) => {
    if (!e) return '';
    if (e.kind === 'structure') {
      const named = towerName(e.id, e.ownerCamp || e.killerCamp);
      return named ? `${e.ownerCamp === own ? '我方' : '对方'}${named}` : (e.name || '建筑');
    }
    if (e.kind === 'resource') {
      const named = RESOURCE_NAMES[Number(e.id)];
      if (named) return named;
    }
    return e.name || (e.kind === 'resource' ? '资源' : '事件');
  };
  const blue = { left: 'blue', right: 'red' }[own] || own;
  const points = (m.process?.timeline || []).filter((x) => has(x.gameTime) && has(x.blueGold) && has(x.redGold) && (!has(m.duration) || x.gameTime <= m.duration))
    .map((x) => [x.gameTime, (x.blueGold - x.redGold) * (blue === 'red' ? -1 : 1)]);
  const draft = m.draft;
  const eventNames = { resource: '资源', structure: '建筑', kill: '击杀', heroKill: '击杀' };
  const events = m.replay?.events || [];
  const swings = [];
  for (let i = 1; i < points.length; i++) {
    const delta = points[i][1] - points[i - 1][1];
    if (Math.abs(delta) >= 200) swings.push({ t: points[i][0], delta, value: points[i][1] });
  }
  const turn = swings.length ? swings.reduce((a, b) => Math.abs(b.delta) > Math.abs(a.delta) ? b : a) : null;
  const finalDiff = points.length ? points.at(-1)[1] : null;
  const plainScore = score(m).replace(/<[^>]+>/g, '');
  const goldAt = (t) => {
    if (!has(t)) return null;
    let best = null;
    for (const p of points) if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
    return best ? best[1] : null;
  };
  const phaseRows = phaseWindows(m.duration).map((w, i) => {
    const a = goldAt(w.start), b = goldAt(w.end);
    return [w.label, time(w.start) + '–' + time(w.end), has(a) && has(b) ? diff(b - a) : '—', has(b) ? diff(b) : '—'];
  });
  const resultText = resultName[m.result] || '未知';
  const absPoints = (m.process?.timeline || []).filter((x) => has(x.gameTime) && has(x.blueGold) && has(x.redGold) && (!has(m.duration) || x.gameTime <= m.duration))
    .map((x) => ({ t: x.gameTime, b: x.blueGold, r: x.redGold }));
  const absAt = (t, key) => {
    let best = null;
    for (const p of absPoints) if (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    return best ? best[key] : null;
  };
  const ownKey = (own === 'red' || own === 'right') ? 'r' : 'b';
  const enemyKey = ownKey === 'b' ? 'r' : 'b';
  const phaseWins = phaseWindows(m.duration);
  const phaseGain = (i, key) => {
    const w = phaseWins[i];
    if (!w || !has(m.duration) || !m.duration) return null;
    const a = absAt(w.start, key), b = absAt(w.end, key);
    return has(a) && has(b) ? b - a : null;
  };
  const gains = [0, 1, 2].map((i) => ({ own: phaseGain(i, ownKey), enemy: phaseGain(i, enemyKey) }));
  const gainMax = Math.max(1, ...gains.flatMap((g) => [Math.abs(g.own || 0), Math.abs(g.enemy || 0)]));
  const phaseLabels = phaseWins.map((w) => w.label);
  const phaseOf = (t) => phaseIndexAt(t, m.duration);
  /* 比赛脉搏的序列：本队 / 对手经济绝对值 + 本队视角经济差 */
  const series = absPoints.filter((p) => !has(m.duration) || p.t <= m.duration)
    .map((p) => ({ t: p.t, own: ownKey === 'b' ? p.b : p.r, foe: ownKey === 'b' ? p.r : p.b, diff: ownKey === 'b' ? p.b - p.r : p.r - p.b }));
  /* 阶段内资源 / 建筑事件计数（按击杀方阵营归属） */
  const phaseEvents = [0, 1, 2].map((i) => {
    const res = { own: 0, foe: 0 }, struct = { own: 0, foe: 0 };
    for (const e of events) {
      if (!has(e.t) || phaseOf(e.t) !== i) continue;
      const side = e.killerCamp === own ? 'own' : 'foe';
      if (e.kind === 'resource') res[side] += 1;
      else if (e.kind === 'structure') struct[side] += 1;
    }
    return { res, struct };
  });
  /* 入侵率：本队五人在对侧半区的采样占比（需要逐秒位置） */
  const invadeRates = [0, 1, 2].map((i) => {
    if (!m.positions) return null;
    let inside = 0, total = 0;
    for (const p of m.positions.players) {
      if (p.camp !== own) continue;
      for (let k = 0; k < p.points.length; k++) {
        const t = k * m.positions.step;
        if (has(m.duration) && m.duration > 0 && t > m.duration) break;
        if (phaseOf(t) !== i) continue;
        const [x, y] = p.points[k];
        const prog = Math.min(1, Math.max(0, (x + y + 112) / 224));
        total += 1;
        if (own === 'blue' ? prog > 0.5 : prog < 0.5) inside += 1;
      }
    }
    return total ? inside / total * 100 : null;
  });
  const phaseTableRows = [0, 1, 2].map((i) => {
    const g = gains[i];
    const net = has(g.own) && has(g.enemy) ? g.own - g.enemy : null;
    return {
      label: phaseLabels[i], range: phaseRows[i][1],
      ownGain: g.own, foeGain: g.enemy, net,
      ownPct: Math.max(0, Math.min(1, Math.abs(g.own || 0) / gainMax)).toFixed(3),
      foePct: Math.max(0, Math.min(1, Math.abs(g.enemy || 0) / gainMax)).toFixed(3),
      res: phaseEvents[i].res, struct: phaseEvents[i].struct, invade: invadeRates[i],
    };
  });
  pulseState = { series, events: events.map((e) => ({ ...e, label: eventLabel(e) })), own };
  const scoreParts = plainScore.split(' : ');
  const mdCrumb = `<div class="md-crumb">
    <a class="md-back" href="#matches"><span aria-hidden="true">←</span> 对局档案</a>
    <span class="md-crumb-meta">${[m.date || '日期未知', m.mode, time(m.duration)].filter(Boolean).map((x) => `<i>${esc(x)}</i>`).join('')}</span>
    <span class="md-crumb-actions"><button class="control" data-action="filter">${icon('filter')} 数据范围</button><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></span>
  </div>`;
  const outcome = m.result === 'win' ? '收下这一局' : m.result === 'loss' ? '交出这一局' : '结束这一局';
  const heroClaim = points.length >= 2 && turn
    ? `${time(turn.t)} 一波 ${diff(turn.delta)} 后经济差${finalDiff >= 0 ? '再没回落' : '始终没能翻正'}`
    : `本队 ${time(m.duration)} 以 ${plainScore} ${outcome}`;
  const heroFact = points.length >= 2 && turn
    ? `本队 ${time(m.duration)} 以 ${plainScore} ${outcome}`
    : `回放记录 ${events.length} 条事件`;
  const winSide = m.result === 'win' ? 'own' : m.result === 'loss' ? 'rival' : '';
  const mdHero = `<section class="md-hero" id="match-verdict">
    <div class="md-hero-head">
      <span class="md-hero-kicker">本局结论</span>
      <span class="md-hero-meta">${[m.mode || '训练赛', m.session].filter(Boolean).map(esc).join(' · ')}</span>
    </div>
    <h1><b>${esc(heroClaim)}</b><span>${esc(heroFact)}</span></h1>
    <div class="md-line">
      <div class="md-line-side own">
        <span>本队 · ${esc(sides[own] || '阵营未知')}</span>
        <b>${esc(metadata.teamName || '本队')}</b>
      </div>
      <div class="md-line-mid">
        <strong><i class="${winSide === 'own' ? 'win' : ''}">${esc(scoreParts[0] || '—')}</i><span>:</span><i class="${winSide === 'rival' ? 'win' : ''}">${esc(scoreParts[1] || '—')}</i></strong>
        <div class="md-line-note"><em class="${m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : ''}">${esc(resultText)}</em><span>${time(m.duration)}</span></div>
        <p class="md-line-diff"><b>${diff(finalDiff)}</b> 终局经济差 · 本队视角</p>
      </div>
      <div class="md-line-side rival">
        <span>对手 · ${esc(sides[opposite[own]] || '阵营未知')}</span>
        <b>${esc(m.opponent || '未标注')}</b>
      </div>
    </div>
    <p>口径：营地面板经济采样（约 30 秒一点）与回放事件；经济差为本队减对手，不做跨局推断。</p>
  </section>`;
  const resourceBand = (() => {
    if (!events.length) return '';
    /* 龙/主宰按具体名字数（暗影主宰、暴君、暗影暴君），防御塔拆到「哪一路哪一座」，
       并把双方占比画成对向条——只写 1:0 看不出这一局资源是被谁控住的。 */
    const names = ['暴君', '暗影暴君', '暗影主宰'];
    const count = (name, camp) => events.filter((e) => eventLabel(e) === name && e.killerCamp === camp).length;
    const rows = names.map((name) => ({ name, own: count(name, own), foe: count(name, opposite[own]) }));
    const ownDragons = rows.reduce((sum, row) => sum + row.own, 0);
    const foeDragons = rows.reduce((sum, row) => sum + row.foe, 0);
    const rate = ownDragons + foeDragons ? Math.round(ownDragons / (ownDragons + foeDragons) * 100) : null;
    const towers = events.filter((e) => e.kind === 'structure');
    const towerOf = (camp) => towers.filter((e) => e.killerCamp === camp);
    const tierCount = (camp, tier) => towerOf(camp).filter((e) => (towerName(e.id, e.ownerCamp) || '').includes(tier)).length;
    const coreOf = (camp) => towerOf(camp).filter((e) => towerName(e.id, e.ownerCamp) === '水晶').length;
    const ownTowers = towerOf(own).filter((e) => towerName(e.id, e.ownerCamp) !== '水晶').length;
    const foeTowers = towerOf(opposite[own]).filter((e) => towerName(e.id, e.ownerCamp) !== '水晶').length;
    const tierLine = (camp) => {
      const parts = ['一塔', '二塔', '高地塔'].map((tier) => `${tier} ${tierCount(camp, tier)}`);
      const core = coreOf(camp);
      if (core) parts.push(`水晶 ${core}`);
      return parts.join(' · ');
    };
    const buffs = m.replay?.buffEvents || [];
    const anti = buffs.filter((b) => b.owner && b.killer && b.owner !== own && b.killer === own).length;
    const stolen = buffs.filter((b) => b.owner === own && b.killer && b.killer !== own).length;
    const farmed = buffs.filter((b) => b.owner === own && b.killer === own).length;
    const buffLine = buffs.length
      ? `<p class="md-res-buff">BUFF 收己方野 <b>${farmed}</b> · 反野 <b>${anti}</b> 次 · 被反 <b>${stolen}</b> 次<small>回放 killbuff 事件</small></p>`
      : '';
    const item = (row) => {
      const total = row.own + row.foe;
      const pctOwn = total ? row.own / total * 100 : 50;
      return `<div class="md-res-item">
        <span class="md-res-item-top"><i>${esc(row.name)}</i><b>${row.own}</b><em>:</em><b class="foe">${row.foe}</b></span>
        <span class="md-res-bar" title="${esc(row.name)} 我方 ${row.own} / 对方 ${row.foe}"><i style="width:${pctOwn.toFixed(1)}%"></i></span>
      </div>`;
    };
    const towerTotal = ownTowers + foeTowers;
    const towerItem = `<div class="md-res-item md-res-item-wide">
      <span class="md-res-item-top"><i>防御塔</i><b>${ownTowers}</b><em>:</em><b class="foe">${foeTowers}</b></span>
      <span class="md-res-bar" title="我方推掉 ${ownTowers} 座 / 对方推掉 ${foeTowers} 座"><i style="width:${(towerTotal ? ownTowers / towerTotal * 100 : 50).toFixed(1)}%"></i></span>
      <small>我方推：${esc(tierLine(own))}<br>对方推：${esc(tierLine(opposite[own]))}</small>
    </div>`;
    return `<div class="md-res">
      <div class="md-res-main">
        <span class="md-res-kicker">资源控制</span>
        <strong class="md-res-rate">${rate === null ? '—' : rate}<small>${rate === null ? '' : '%'}</small></strong>
        <span class="md-res-caption">龙 / 主宰控制率（我方 ${ownDragons} : ${foeDragons} 对方）</span>
        <span class="md-res-gauge"><i style="width:${rate === null ? 50 : rate}%"></i></span>
      </div>
      <div class="md-res-items">${rows.map(item).join('')}${towerItem}</div>
      ${buffLine}
    </div>`;
  })();
  const mdPhases = `<section class="section" id="match-phases"><div class="section-heading"><div><h2>阶段对比</h2><p>经济差与阶段变化按营地采样；资源 / 建筑是回放事件计数；入侵是本队五人合计进入对侧半区的时间占比</p></div></div>
    ${deep.phaseTable(phaseTableRows)}${resourceBand}
  </section>`;
  const nodeRows = [
    ...[...swings].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 4).map((s) => ({ t: s.t, event: '经济差波动', delta: s.delta, value: diff(s.value), dir: (m.result === 'win' ? s.delta > 0 : s.delta < 0) ? '利于本队' : '利于对手' })),
    ...events.filter((e) => /kill|death|resource|structure/i.test(e.kind || '')).slice(0, 4).map((e) => ({ t: e.t, event: `${eventLabel(e)} · ${e.killerHero || e.killer || '—'}`, delta: null, value: has(goldAt(e.t)) ? diff(goldAt(e.t)) : '—', dir: '回放事件' })),
  ].sort((a, b) => (a.t || 0) - (b.t || 0)).slice(0, 8);
  const dirClass = (d) => d === '利于本队' ? 'own' : d === '利于对手' ? 'enemy' : 'event';
  const mdTimeline = nodeRows.length ? `<section class="section" id="match-timeline"><div class="section-heading"><div><h2>关键节点</h2><p>按时间排列，每个数字都能回到具体分钟；波动取绝对值最大的几次</p></div></div>
    <div class="md-node-head"><span>时间</span><span>关键节点</span><span>经济差变化</span><span>当时经济差</span><span>方向 / 来源</span></div>
    <div class="md-node-list">${nodeRows.map((n) => `<div class="md-node-row"><span class="md-node-time">${time(n.t)}</span><b>${esc(n.event)}</b><span class="md-node-num">${n.delta === null ? '—' : diff(n.delta)}</span><span class="md-node-num">${esc(n.value)}</span><span class="md-node-dir ${dirClass(n.dir)}">${esc(n.dir)}</span></div>`).join('')}</div>
  </section>` : '';
  /* 10 分钟经济：营地接口只有团队金币（30 秒一个点），没有逐人；回放的金币流水
     对不上账（残差 17.5%，个别 43%）。所以这一格只能由教练手填，填在覆盖层里，
     不动原始数据包；不填就留空，不估。 */
  const mdGold10 = (() => {
    const saved = m.gold10 || {};
    const byPos = { 对抗路: 0, 打野: 1, 中路: 2, 发育路: 3, 游走: 4 };
    const people = (m.players || []).filter((p) => p.camp === own || p.camp === opposite[own]);
    if (people.length < 2) return '';
    const side = (camp) => people.filter((p) => p.camp === camp)
      .sort((a, b) => (byPos[a.position] ?? 9) - (byPos[b.position] ?? 9))
      .map((p) => {
        const key = `${p.camp}-${p.slot}`;
        const value = has(saved[key]) ? saved[key] : null;
        const grade = value === null ? null : gold10Grade(p.position, value);
        return `<label class="md-g10-row">
          <span class="md-g10-lane">${esc(p.position || '未标注')}</span>
          <span class="md-g10-hero">${esc(p.hero || '—')}</span>
          <input type="number" inputmode="numeric" min="0" max="100000" step="1"
                 data-gold10="${esc(key)}" value="${value === null ? '' : value}" placeholder="填 10 分钟金币">
          ${grade ? `<em class="md-grade ${grade.level}">${grade.label}</em>` : '<em class="md-grade is-blank"></em>'}
        </label>`;
      }).join('');
    const filled = people.filter((p) => has(saved[`${p.camp}-${p.slot}`])).length;
    return `<section class="section" id="match-gold10"><div class="section-heading"><div><h2>10 分钟经济</h2><p>营地与回放都没有逐人金币时间轴（回放只有团队经济，逐人流水对不上账），所以这格只能手填。填完立刻按分路出评级：对抗路 / 发育路 6800 及格、7000 良好、7400 优秀</p></div>
      <span class="md-g10-count">已填 <b>${filled}</b> / ${people.length}</span></div>
      <div class="md-g10-grid">
        <div class="md-g10-side"><span class="md-g10-side-label own">本队</span>${side(own)}</div>
        <div class="md-g10-side"><span class="md-g10-side-label foe">对手</span>${side(opposite[own])}</div>
      </div>
      <p class="md-g10-note">填在覆盖层里，不改原始数据包；不填就留空，不估算、不补齐。</p>
    </section>`;
  })();
  const mdProfiles = `<section class="section" id="match-profiles"><div class="section-heading"><div><h2>十人面板</h2><p>对位比较按同分路两人归一，条形为本队占两人的比重；同队比较看队内份额。有位置数据时多一列「入侵」＝在对方半区的停留占比</p></div></div>
    ${deep.panel(m.players || [], own, m.positions, m.duration, m.replay?.kills, m.replay?.fights, m.replay?.deaths)}
  </section>`;
  /* 位置数据请求过但没有：说明该局缺逐秒位置（未关联官方回放），不再无限转圈。 */
  const positionsEmpty = m.positionsRequested
    ? '<div class="empty">该局没有逐秒位置数据（需要在采集页的通道校对里关联本局官方回放）</div>'
    : '<div class="empty">正在读取营地的逐秒位置…</div>';
  const mdHeat = `<section class="section" id="match-heat"><div class="section-heading"><div><h2>对位热区</h2><p>选一路，看这一路两个人在 90 秒窗口里怎么移动；可拖动时间轴或点播放。金为本队、青为对手</p></div></div>
    ${m.positions ? deep.heat(m.positions, m.players, own, m.duration) : positionsEmpty}
  </section>`;
  const mdDuel = `<section class="section" id="match-duel"><div class="section-heading"><div><h2>对位纵深</h2><p>同一张表两种口径：深区＝推进进度 &gt; 66%，半区＝&gt; 50%（即入侵）；方块数表示停留时长，每格约 10 秒，最多 10 格</p></div></div>
    ${m.positions ? deep.duel(m.positions, m.players, own, m.duration) : positionsEmpty}
  </section>`;
  const mdJungle = `<section class="section" id="match-jungle"><div class="section-heading"><div><h2>打野并线</h2><p>兵线到了，打野和这条路的队友一起吃这波线，算一次并线。三段按 KPL 口径切：0–4 对线 / 4–10 发育 / 10 分钟后；时间轴上线是本队打野、下线是对手，大点＝三人并线，悬停看时刻</p></div></div>
    ${m.positions ? deep.jungleJoin(m.positions, m.players, own, m.duration) : positionsEmpty}
  </section>`;
  const ownSideKey = (own === 'red' || own === 'right') ? 'right' : 'left';
  const enemySideKey = ownSideKey === 'left' ? 'right' : 'left';
  const slots = (list, kind) => Array.from({ length: 5 }, (_, i) => {
    const h = list[i];
    return h ? `<span>${kind === 'picks' ? `<em>${i + 1}</em>` : ''}${portrait(h.name)}${esc(h.name)}</span>`
             : `<span class="md-bp-empty"><em>${kind === 'bans' ? '空 BAN' : '空位'}</em></span>`;
  }).join('');
  const bpRow = (key, title, side) => `<div class="md-bp-row ${side}"><b>${esc(title)}</b>
    <span class="md-bp-picks">${slots(draft?.picks?.[key] || [], 'picks')}</span>
    <span class="md-bp-bans">${slots(draft?.bans?.[key] || [], 'bans')}</span></div>`;
  /* ── BP 复盘：把「历史对位」「历史联动」两个库对到本局，回答「这把 BP 打得怎么样」──
     只报算得出来的：算不了的写「待积累」，不给总分，也不拿胜负倒推 BP 好坏。 */
  const bpAnalysis = (() => {
    const empty = { review: '', combos: '', matchup: '' };
    if (!draft) return empty;
    const lmRows = m.laneMatchup?.payload?.heroes || [];
    const byPair = new Map(lmRows.map((row) => [`${row.ownHero}|${row.enemyHero}`, row]));
    const mine = new Map(), theirs = new Map();
    for (const p of m.players || []) {
      if (!p.position) continue;
      (p.camp === own ? mine : theirs).set(p.position, p);
    }
    const ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
    /* 对位压制的主口径是**巅峰千强大盘**（带超额胜率），不是自家训练赛、更不是 KPL：
       自家样本太薄；KPL 的英雄对位被「强队选强英雄」污染，冷门英雄几乎没有样本，
       拿它判克制会把「英雄本来就弱」说成「被克制」。自家历史只作一行补充。 */
    const ladderLanes = new Map((m.bpFacts?.ladder?.lanes || []).map((row) => [row.lane, row]));
    const lanes = ORDER.map((lane) => {
      const a = mine.get(lane), b = theirs.get(lane);
      if (!a || !b) return null;
      const facts = ladderLanes.get(lane) || null;
      const scrim = byPair.get(`${a.hero}|${b.hero}`) || null;
      const nowDiff = has(a.gold) && has(b.gold) ? a.gold - b.gold : null;
      const states = { ahead: '压制', behind: '劣势', even: '均势' };
      const verdict = facts ? (states[facts.state] || '样本不足') : '样本不足';
      const judgeable = verdict !== '样本不足';
      /* 兑现：大盘说这对组合占优、本局经济也领先（反之亦然） */
      const realised = judgeable && has(nowDiff)
        ? (verdict === '压制' ? nowDiff > 0 : verdict === '劣势' ? nowDiff < 0 : null)
        : null;
      return { lane, a, b, facts, scrim, verdict, nowDiff, judgeable, realised };
    }).filter(Boolean);

    const verdictText = (lane) => lane.verdict === '压制' ? '我方占优'
      : lane.verdict === '劣势' ? '我方吃亏' : lane.verdict === '均势' ? '打平' : '无大盘样本';
    const verdictCls = (lane) => lane.verdict === '压制' ? 'is-ahead'
      : lane.verdict === '劣势' ? 'is-behind' : lane.verdict === '均势' ? 'is-even' : 'is-thin';
    const laneCard = (lane) => `<article class="md-mu-card ${verdictCls(lane)}">
      <header><span class="md-mu-lane">${lane.lane}</span><em class="${verdictCls(lane)}">${verdictText(lane)}</em></header>
      <div class="md-mu-who"><b class="own">${esc(lane.a.hero || '—')}</b><i>vs</i><b class="foe">${esc(lane.b.hero || '—')}</b></div>
      ${lane.facts && lane.facts.n ? `<p class="md-mu-hist">巅峰千强 ${fmt(lane.facts.n)} 局 · 实际 ${fmt(lane.facts.wr, 1)}% vs 预期 ${fmt(lane.facts.expected, 1)}% · 超额 <b>${diff(lane.facts.excess)}</b></p>`
        : `<p class="md-mu-hist">巅峰千强没有这个对位样本${lane.facts && (lane.facts.minePick || lane.facts.foePick)
          ? `（使用率 ${lane.facts.minePick === null || lane.facts.minePick === undefined ? '—' : fmt(lane.facts.minePick, 2) + '%'}
             / ${lane.facts.foePick === null || lane.facts.foePick === undefined ? '—' : fmt(lane.facts.foePick, 2) + '%'}，门槛 3%）` : ''}</p>`}
      ${lane.scrim && lane.scrim.n ? `<p class="md-mu-hist">自家 ${fmt(lane.scrim.n)} 局 · 对线领先 ${fmt(lane.scrim.aheadRate, 0)}%</p>` : ''}
      ${lane.nowDiff === null ? '<p class="md-mu-now">本局经济差 —</p>'
        : `<p class="md-mu-now">本局对位经济差 <b>${diff(lane.nowDiff)}</b>${lane.realised === null ? ''
          : lane.realised ? ' · <i class="is-hit">与大盘同向</i>' : ' · <i class="is-miss">与大盘相反</i>'}</p>`}
    </article>`;

    /* 联动：把双方阵容对到历史组合样本 */
    const heroesOf = (key) => (draft?.picks?.[key] || []).map((row) => row && row.name).filter(Boolean);
    const collect = (side, heroes) => {
      const combosData = m.combosData;
      if (!combosData || !heroes.length) return [];
      const out = [];
      for (const list of [combosData.pairs, combosData.trios]) {
        for (const combo of (list?.[side]?.combos || [])) {
          if (combo.heroes.length >= 2 && combo.heroes.every((hero) => heroes.includes(hero))) {
            out.push({ ...combo, size: combo.heroes.length });
          }
        }
      }
      return out.sort((x, y) => (y.games - x.games) || (y.synergy - x.synergy)).slice(0, 3);
    };
    const ownCombos = collect('own', heroesOf(ownSideKey));
    const foeCombos = collect('enemy', heroesOf(enemySideKey));
    const comboCard = (combo) => {
      /* KPL 那一行是「这套组合职业赛场见得到吗」，自家那两行是「你们自己打得怎么样」——
         两种口径分开写，不合成一个结论。 */
      const kplRow = (m.bpFacts?.kpl?.comboIndex || {})[combo.heroes.join('+')];
      return `<article class="md-combo-card">
      <div class="md-combo-heroes">${combo.heroes.map((hero) => portrait(hero)).join('<i>+</i>')}</div>
      <b>${esc(combo.heroes.join(' + '))}</b>
      <p>${fmt(combo.games)} 局 ${fmt(combo.wins)} 胜
        <span class="${combo.synergy >= 0 ? 'is-good' : 'is-bad'}" title="搭档加成 = 两人同场时的胜率 − 两名英雄各自平时胜率算出的预期值（${pct(combo.winRate)} − ${pct(combo.expected)}）">搭档加成 ${Math.abs(combo.synergy) < 0.05 ? '0' : diff(combo.synergy)} 点</span></p>
      ${kplRow ? `<p class="md-combo-kpl">KPL ${fmt(kplRow.n)} 场 · 胜率 ${fmt(kplRow.wr, 1)}%${kplRow.year ? `（${kplRow.year}）` : ''}</p>`
        : '<p class="md-combo-kpl is-quiet">KPL 没出现过</p>'}
    </article>`;
    };
    const combos = (ownCombos.length || foeCombos.length) ? `<div class="md-bp-combos">
      <div class="md-bp-combo-side"><span>我方组合</span><div class="md-combo-grid">${ownCombos.map(comboCard).join('') || '<small>当前阵容没有历史组合样本</small>'}</div></div>
      <div class="md-bp-combo-side foe"><span>对手组合</span><div class="md-combo-grid">${foeCombos.map(comboCard).join('') || '<small>对手阵容没有历史组合样本</small>'}</div></div>
    </div>` : '';

    /* 赛事命中：先回答教练真正问的「我们这套 5 人整阵容，KPL 那边见过没有」，再拆到
       双人 / 三人组合。教练原话：「不需要具体说明是哪一局，有就行」——所以只报命中、
       场次、胜率和用过这套的队，不报是哪一场。
       整阵容（lineup / lineupSeen）是新增字段：老数据没有时退化成只看组合层，
       不硬编「没见过」，也不显示空字段。 */
    const kplBlock = (() => {
      const facts = m.bpFacts?.kpl;
      if (!facts) return '';
      const ownHeroes = heroesOf(ownSideKey);
      const hitPairs = has(facts.hitPairs) ? facts.hitPairs : 0;
      const hitTrios = has(facts.hitTrios) ? facts.hitTrios : 0;
      const totalPairs = has(facts.totalPairs) ? facts.totalPairs
        : ownHeroes.length >= 2 ? ownHeroes.length * (ownHeroes.length - 1) / 2 : null;
      const totalTrios = has(facts.totalTrios) ? facts.totalTrios
        : ownHeroes.length >= 3 ? ownHeroes.length * (ownHeroes.length - 1) * (ownHeroes.length - 2) / 6 : null;
      const dateOnly = (value) => {
        const date = String(value ?? '').trim().slice(0, 10);
        return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : '';
      };
      /* 胜率统一保留 1 位小数：同一块里不出现 70% / 44.4% 混排。 */
      const wrText = (value) => has(value) ? `${value.toFixed(1)}%` : '—';
      /* 「哪些队用过」：最多 3 支，多出的写 +N；没有 teams 就整行不出。 */
      const teamChips = (teams) => {
        const list = (Array.isArray(teams) ? teams : []).filter((row) => row && row.team);
        if (!list.length) return '';
        const shown = list.slice(0, 3);
        const rest = list.length - shown.length;
        const detail = list.map((row) => `${row.team} ${fmt(row.n)} 场 ${fmt(row.wins)} 胜`).join(' · ');
        return `<span class="md-kplhit-teams" title="${esc(detail)}"><em>用过</em>${shown.map((row) => `<span class="md-kplhit-team">${esc(row.team)}</span>`).join('')}${rest > 0 ? `<span class="md-kplhit-team is-more">+${rest}</span>` : ''}</span>`;
      };

      /* 第一层：整阵容结论，字号最大，是这块的主结论。 */
      const lineup = facts.lineup && typeof facts.lineup === 'object' ? facts.lineup : null;
      const lineupKnown = typeof facts.lineupSeen === 'boolean' || Object.prototype.hasOwnProperty.call(facts, 'lineup');
      const lineupSeen = lineupKnown
        ? (typeof facts.lineupSeen === 'boolean' ? facts.lineupSeen : Boolean(lineup)) : false;
      const isEmpty = !hitPairs && !hitTrios && !(lineupKnown && lineupSeen);
      const lineupMeta = lineup
        ? `${teamChips(lineup.teams)}
          ${has(lineup.wr) ? `<span>胜率 <b>${wrText(lineup.wr)}</b></span>` : ''}
          ${has(lineup.year) ? `<span>最近出现 ${lineup.year} 年</span>` : ''}`
        : '';
      const missScope = [has(facts.leagueCount) ? `${fmt(facts.leagueCount)} 个赛季` : '',
        has(facts.games) ? `${fmt(facts.games)} 局` : ''].filter(Boolean).join('、');
      const missNote = missScope
        ? `完整的 5 人阵容在 KPL 已收录的 ${missScope}里没有同队同场记录，这是正常结论。`
        : '完整的 5 人阵容在 KPL 统计窗口内还没有同队同场记录，这是正常结论。';
      const lineupHtml = !lineupKnown ? '' : lineupSeen
        ? `<div class="md-kplhit-lineup is-seen">
            <p class="md-kplhit-verdict">本队 5 人整阵容 KPL ${has(lineup?.n) ? `见过 <b>${fmt(lineup.n)}</b> 次` : '出现过'}${has(lineup?.wins) ? `（<b>${fmt(lineup.wins)}</b> 胜）` : ''}</p>
            ${lineupMeta.trim() ? `<div class="md-kplhit-lineup-meta">${lineupMeta}</div>` : ''}
          </div>`
        : `<div class="md-kplhit-lineup is-miss">
            <p class="md-kplhit-verdict">本队 5 人整阵容 KPL 没出现过</p>
            <p class="md-kplhit-lineup-note">${missNote}</p>
          </div>`;
      /* 整阵容字段还没落地时，用组合层结论补一句，别让这块只剩两个进度条。 */
      const comboSummary = !lineupKnown && !isEmpty
        ? `<p class="md-kplhit-summary">本队 ${has(totalPairs) ? fmt(totalPairs) : '—'} 组双人里 <b>${fmt(hitPairs)}</b> 组见过${has(totalTrios) ? `，${fmt(totalTrios)} 组三人里 <b>${fmt(hitTrios)}</b> 组见过` : ''}</p>`
        : '';

      /* 第二层：组合命中率，数字块 + 进度条。 */
      const rateBar = (label, hit, total) => {
        const ratio = has(total) && total > 0 ? Math.min(100, hit / total * 100) : null;
        return `<div class="md-kplhit-rate">
          <span class="md-kplhit-rate-label">${label}</span>
          <span class="md-kplhit-rate-num"><b>${fmt(hit)}</b><i>/</i>${has(total) ? fmt(total) : '—'}</span>
          ${ratio === null ? '' : `<span class="md-kplhit-bar${hit ? '' : ' is-zero'}" title="${label}命中 ${fmt(hit)} / ${fmt(total)}"><i style="width:${ratio.toFixed(1)}%"></i></span>`}
        </div>`;
      };
      const rates = `<div class="md-kplhit-rates">
        ${rateBar('双人组合', hitPairs, totalPairs)}${rateBar('三人组合', hitTrios, totalTrios)}
      </div>`;

      /* 第三层：命中组合逐条（沿用 3 双人 + 2 三人的截断）。 */
      const comboRow = (row, size) => {
        const heroes = Array.isArray(row?.heroes) ? row.heroes.filter(Boolean) : [];
        if (!heroes.length) return '';
        return `<div class="md-kplhit-row">
          <span class="md-kplhit-tag">${size === 3 ? '三人' : '双人'}</span>
          <div class="md-kplhit-body">
            <div class="md-kplhit-heroes"><span class="md-kplhit-faces">${heroes.map((hero) => portrait(hero)).join('<i>+</i>')}</span><b>${esc(heroes.join(' + '))}</b></div>
            ${teamChips(row.teams)}
          </div>
          <div class="md-kplhit-stat">${has(row.n) ? `<span><b>${fmt(row.n)}</b> 场</span>` : ''}${has(row.wr) ? `<span>胜率 <b>${wrText(row.wr)}</b></span>` : ''}</div>
        </div>`;
      };
      const rows = [
        ...(Array.isArray(facts.pairs) ? facts.pairs.slice(0, 3) : []).map((row) => ({ row, size: 2 })),
        ...(Array.isArray(facts.trios) ? facts.trios.slice(0, 2) : []).map((row) => ({ row, size: 3 })),
      ].map((item) => comboRow(item.row, item.size)).filter(Boolean);
      const list = rows.length ? `<div class="md-kplhit-list">
        <div class="md-kplhit-list-head"><span>命中组合</span><span>同队同场同时选用过，≥1 场即算命中</span></div>
        ${rows.join('')}
      </div>` : '';
      const isEmptyNote = isEmpty ? `<div class="md-kplhit-empty">
        ${lineupKnown ? '' : '<p class="md-kplhit-empty-line">本队双人 / 三人组合在 KPL 统计窗口内都没有命中</p>'}
        <small>这不是坏消息：KPL 统计的是同队同场同时选用过的组合，新阵容或冷门搭配本来就不容易命中。</small>
      </div>` : '';

      /* 第四层：口径脚注，缺字段就不显示对应片段。 */
      const footBits = [];
      if (facts.sourceLabel) footBits.push(esc(String(facts.sourceLabel)));
      const start = dateOnly(facts.windowStart), end = dateOnly(facts.windowEnd);
      if (start && end) footBits.push(`${start} – ${end}`);
      else if (start) footBits.push(`${start} 起`);
      else if (end) footBits.push(`截至 ${end}`);
      const updated = dateOnly(facts.updatedAt);
      if (updated) footBits.push(`更新于 ${updated}`);
      const foot = footBits.length ? `<p class="md-kplhit-foot">${footBits.join('<i>·</i>')}</p>` : '';

      const cls = `md-kplhit${isEmpty ? ' is-empty' : ''}${lineupKnown && lineupSeen ? ' is-seen' : ''}`;
      return `<div class="${cls}">
        <div class="md-kplhit-head"><b>赛事命中</b>${facts.sourceLabel ? `<span class="md-kplhit-src">${esc(String(facts.sourceLabel))}</span>` : ''}</div>
        ${comboSummary}${lineupHtml}${rates}${list}${isEmptyNote}${foot}
      </div>`;
    })();

    /* 结论句：只陈述能算的，样本薄就自己说薄。 */
    const judged = lanes.filter((lane) => lane.judgeable);
    const ahead = judged.filter((lane) => lane.verdict === '压制').length;
    const behind = judged.filter((lane) => lane.verdict === '劣势').length;
    const realised = judged.filter((lane) => lane.realised === true).length;
    const positiveCombos = ownCombos.filter((combo) => combo.synergy > 0).length;
    const parts = [];
    if (judged.length) {
      const bits = [];
      if (ahead) bits.push(`占优 ${ahead}`);
      if (behind) bits.push(`吃亏 ${behind}`);
      parts.push(bits.length ? `巅峰千强五路可判 ${judged.length} 路：${bits.join('、')}`
        : `巅峰千强五路可判 ${judged.length} 路，都是打平`);
      if (judged.some((lane) => lane.realised !== null)) parts.push(`本局兑现 ${realised} 路`);
    } else {
      parts.push('五路对位在巅峰千强都没有样本');
    }
    if (m.bpFacts?.kpl) {
      const hit = (m.bpFacts.kpl.hitPairs || 0) + (m.bpFacts.kpl.hitTrios || 0);
      parts.push(hit ? `赛事命中 ${hit} 组（KPL 出现过）` : '赛事无命中');
    }
    if (ownCombos.length) parts.push(`我方 ${ownCombos.length} 组搭档里 ${positiveCombos} 组为正加成`);
    else parts.push('我方阵容没有历史组合样本');
    const thin = judged.length < 3;
    /* 可判不足 3 路时不给「占优 / 吃亏」的结论，只写「样本偏薄」——
       1 路对位就下总体判断，等于替教练过度解读。 */
    const tone = (!judged.length && !ownCombos.length) || thin ? 'is-thin'
      : ahead > behind ? 'is-good' : behind > ahead ? 'is-bad' : 'is-thin';
    const badge = !judged.length && !ownCombos.length ? '证据不足'
      : thin ? '样本偏薄'
      : ahead > behind ? 'BP 端占优' : behind > ahead ? 'BP 端吃亏' : '五五开';
    const review = `<div class="md-bprev ${tone}">
      <div class="md-bprev-head"><b>本局 BP 复盘</b><span class="md-bprev-badge ${tone}">${badge}</span></div>
      <p class="md-bprev-lede">${parts.join('；')}。</p>
      <div class="md-bprev-stats">
        <div class="md-bprev-stat"><span class="md-bprev-stat-label">对位</span>
          <span class="md-bprev-stat-value">${judged.length}<i>/</i>${lanes.length}<small>路可判</small></span>
          <span class="md-bprev-stat-note">${judged.length
            ? `占优 ${ahead} · 吃亏 ${behind}${judged.some((lane) => lane.realised !== null) ? ` · 兑现 ${realised}` : ''}`
            : '巅峰千强没有可判对位'}</span></div>
        <div class="md-bprev-stat"><span class="md-bprev-stat-label">赛事</span>
          <span class="md-bprev-stat-value">${m.bpFacts?.kpl ? `${(m.bpFacts.kpl.hitPairs || 0) + (m.bpFacts.kpl.hitTrios || 0)}<small>组命中</small>` : '—'}</span>
          <span class="md-bprev-stat-note">${m.bpFacts?.kpl
            ? `双人 ${fmt(m.bpFacts.kpl.hitPairs)} · 三人 ${fmt(m.bpFacts.kpl.hitTrios)}`
            : '暂无 KPL 数据'}</span></div>
        <div class="md-bprev-stat"><span class="md-bprev-stat-label">组合</span>
          <span class="md-bprev-stat-value">${ownCombos.length ? `${positiveCombos}<i>/</i>${ownCombos.length}<small>组</small>` : '—'}</span>
          <span class="md-bprev-stat-note">${ownCombos.length ? '搭档加成为正' : '阵容没有历史组合样本'}</span></div>
      </div>
      ${thin ? '<p class="md-bprev-thin">对位样本还薄，这条结论只作参考；同一个英雄对位再打几局就会自动变成可判。</p>' : ''}
    </div>`;
    const matchup = lanes.length ? `<div class="md-matchup">
      <div class="md-matchup-head"><b>对位压制</b><small>巅峰千强同分路对位：超额胜率（实际 − 两英雄基准期望）≥ +2 判我方占优、≤ −2 判吃亏；样本 ≥200 局且双方使用率 ≥3%</small></div>
      <div class="md-mu-grid">${lanes.map(laneCard).join('')}</div></div>` : '';
    return { review, combos: `${kplBlock}${combos}`, matchup };
  })();
  const mdBp = `<section class="section" id="match-bp"><div class="section-heading"><div><h2>本局 BP</h2><p>营地终局名单 · 禁用固定 5 位，空位标为空 BAN；选用按 pickHeros 原样展示${draft?.pickOrderKnown ? '（已人工校对选用顺序）' : ''}</p></div></div>
    ${draft ? `<div class="md-bp-head"><span>阵容</span><span>选用 · 按序号</span><span>禁用 · 固定 5 位</span></div><div class="md-bp-list">${bpRow(ownSideKey, '本队 · ' + (sides[own] || ''), 'own')}${bpRow(enemySideKey, '对手 · ' + (sides[opposite[own]] || ''), 'enemy')}</div>${bpAnalysis.review}${bpAnalysis.combos}${bpAnalysis.matchup}` : '<div class="empty">暂无禁选记录。</div>'}
  </section>`;
  /* 总量按十人面板逐人求和（详情接口不带 own/enemy 汇总）。 */
  const teamAgg = (camp) => {
    const list = (m.players || []).filter((p) => p.camp === camp);
    const sum = (key) => list.reduce((a, p) => a + (has(p[key]) ? p[key] : 0), 0);
    return { gold: sum('gold'), kills: sum('kills'), damage: sum('damage'), taken: sum('taken') };
  };
  const mdTotals = `<div class="md-totals-band" id="match-totals">
    <div class="md-totals-head"><span>总量 · ${esc(metadata.teamName || '本队')} vs ${esc(m.opponent || '对手')}</span><small>营地十人面板五人合计；金色为本队，青色为对手</small></div>
    ${deep.totals({ own: teamAgg(own), enemy: teamAgg(opposite[own]) })}
  </div>`;
  const mdPulse = `<section class="section md-pulse" id="match-pulse"><div class="section-heading"><div><h2>比赛脉搏</h2><p>经济差与本队视角一致 · ${series.length} 个采样点；菱形＝龙、圆点＝BUFF、方块＝防御塔、大方块＝水晶，点标记看具体是什么</p></div></div>
    ${series.length ? deep.pulse(series, events.map((e) => ({ ...e, label: eventLabel(e) })), m.duration, { own, ownName: metadata.teamName || '本队', foeName: m.opponent || '对手' }) : '<div class="empty">阵营未知，无法展示本队视角的经济差。</div>'}
    <div class="mp-legend mp-legend-foot"><span class="own">本队</span><span class="foe">对手</span><span class="shape dia">龙</span><span class="shape cir">BUFF</span><span class="shape sq">防御塔</span><span class="shape sq big">水晶</span></div>
  </section>`;
  const mdCohesion = `<section class="section" id="match-cohesion"><div class="section-heading"><div><h2>中野辅与入侵</h2><p>集结＝中/野/辅三人两两距离 ≤ 22.5（对角线 15%）且持续 ≥ 5 秒；入侵结果按团战账本的击杀与官方事件里的资源/建筑归因，不插值经济</p></div></div>
    ${m.positions ? deep.cohesion(m.positions, m.players, own, m.duration, events, m.replay?.kills) : positionsEmpty}
  </section>`;
  /* 战斗拆成两块：团战（点地图看本波）与掉点（筛选/点选看单次），各自带分析。 */
  const battle = deep.battle(m.positions, m.players, own, m.duration, points, m.replay?.deaths, m.replay?.fights);
  const mdFights = battle && battle.fights
    ? `<section class="section" id="match-battle"><div class="section-heading"><div><h2>团战</h2><p>团战点大小＝参战人数，颜色＝该波击杀差（本队金 / 对手青）；点地图上的点看这一波的伤害、承伤与控制，下方为团战分析</p></div></div>${battle.fights}</section>`
    : battle ? ''
      : '<section class="section" id="match-battle"><div class="empty">这局没有团战或掉点数据（需要营地回放的 battles 段）</div></section>';
  const mdDeaths = battle && battle.deaths
    ? `<section class="section" id="match-deaths"><div class="section-heading"><div><h2>掉点</h2><p>掉点＝一次阵亡；损失＝死前 120 秒经济差走势外推到复活时刻的差额（本队视角，负＝我方亏、正＝我方赚）。点圆点或列表固定选中，切换选手看他这局全部掉点</p></div></div>${battle.deaths}</section>`
    : '';
  /* 击杀账本：官方回放 battle.killInfo 逐次记录 killerObjID → objID。
     切C = 我方对抗路/打野击杀对方中路/发育路（教练第三波明确要的指标）。
     页面分三层：五路统计卡（先手/击杀用条、切C 用目标 chips）→ 开团分析
     （先手与团战结果、团战节奏条）→ 逐条账本（折叠）。三块同源，口径不另算。 */
  const mdKills = (() => {
    const kills = m.replay?.kills || [];
    if (!kills.length) return '';
    const byHero = new Map((m.players || []).map((p) => [`${p.camp}-${p.hero}`, p]));
    const laneOfKill = (camp, hero) => (byHero.get(`${camp}-${hero}`) || {}).position || '';
    const isCut = (k) => ['对抗路', '打野'].includes(laneOfKill(k.killerCamp, k.killer))
      && ['中路', '发育路'].includes(laneOfKill(k.victimCamp, k.victim));
    const keyOf = (k) => `${k.t}-${k.killer}-${k.victim}`;
    const rows = kills.slice().sort((a, b) => a.t - b.t);
    /* 每场团战的先手击杀 = 该团战最早的一次击杀（与 firstKillerCamp 同源）。 */
    const firstOfFight = new Map();
    for (const k of rows) {
      if (!k.fight) continue;
      const cur = firstOfFight.get(k.fight);
      if (!cur || k.t < cur.t) firstOfFight.set(k.fight, k);
    }
    const firstKeys = new Set([...firstOfFight.values()].map(keyOf));
    /* 教练要的不是账本，是统计：每人切了几次 C、开了几次先手。 */
    const statOf = (p) => {
      const mine = rows.filter((k) => k.killerCamp === p.camp && k.killer === p.hero);
      const cuts = mine.filter(isCut);
      return {
        p, kills: mine.length,
        cut: cuts.length,
        cutTargets: [...new Set(cuts.map((k) => k.victim))],
        cutFirsts: cuts.filter((k) => firstKeys.has(keyOf(k))).length,
        first: mine.filter((k) => firstKeys.has(keyOf(k))).length,
      };
    };
    /* 五路按固定顺序排（对抗路 / 打野 / 中路 / 发育路 / 游走），跨局对比时位置不跳动；
       谁切了 C、谁先手多由卡片高亮和数字表达。未知分路排最后。 */
    const LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
    const stats = (m.players || []).filter((p) => p.camp === own).map(statOf)
      .sort((a, b) => {
        const ai = LANE_ORDER.indexOf(a.p.position), bi = LANE_ORDER.indexOf(b.p.position);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
      });
    const cutTotal = stats.reduce((sum, s) => sum + s.cut, 0);
    const firstTotal = stats.reduce((sum, s) => sum + s.first, 0);
    const ownKills = rows.filter((k) => k.killerCamp === own).length;
    const firstRate = ownKills ? Math.round(firstTotal / ownKills * 100) : null;
    const maxFirst = Math.max(1, ...stats.map((s) => s.first));
    const maxKills = Math.max(1, ...stats.map((s) => s.kills));
    /* 团战结果：先手方 + 该波击杀差。fights 缺失时只讲击杀账本，不编团战结果。 */
    const ownSide = own === 'red' ? 'red' : 'blue';
    const foeSide = ownSide === 'blue' ? 'red' : 'blue';
    const fights = (m.replay?.fights || [])
      .filter((f) => has(f.t) && has(f.blue) && has(f.red))
      .sort((a, b) => a.t - b.t);
    const fightFirst = (f) => {
      if (f.first) return f.first;
      const k = firstOfFight.get(String(f.id));
      return k ? k.killerCamp : '';
    };
    const fightKills = (f, side) => (side === 'red' ? f.red : f.blue);
    const ownWonFight = (f) => fightKills(f, ownSide) > fightKills(f, foeSide);
    const ownFights = fights.filter((f) => fightFirst(f) === ownSide);
    const foeFights = fights.filter((f) => fightFirst(f) && fightFirst(f) !== ownSide);
    const ownFightWins = ownFights.filter(ownWonFight).length;
    const foeFightLosses = foeFights.filter((f) => !ownWonFight(f)).length;
    /* 团战节奏条：一个小方块＝一波团战；金/青 = 谁先手，实心/空心 = 赢/输。 */
    const fightStrip = fights.length ? `<div class="md-fight-strip">
      <div class="md-fight-dots" role="img" aria-label="团战先手与结果时间轴">${fights.map((f) => {
        const side = fightFirst(f);
        const ownTag = side === ownSide;
        const won = ownWonFight(f);
        const score = `${fightKills(f, ownSide)}:${fightKills(f, foeSide)}`;
        return `<i class="md-fight-dot ${ownTag ? 'is-own' : side ? 'is-foe' : 'is-unknown'}${won ? ' is-win' : ' is-loss'}" title="${esc(time(f.t))} · ${ownTag ? '我方' : side ? '对方' : '未记录'}先手 · 击杀 ${score}"></i>`;
      }).join('')}</div>
      <div class="md-fight-legend"><span class="own">我方先手</span><span class="foe">对方先手</span><em>实心＝赢下，空心＝失利</em></div>
    </div>` : '';
    /* 开团分析：先手方和团战结果放在一句话里，后面才是五路分布。 */
    const topFirst = stats.slice().sort((a, b) => b.first - a.first)[0];
    const cutTargetCounts = new Map();
    for (const s of stats) for (const target of s.cutTargets) cutTargetCounts.set(target, (cutTargetCounts.get(target) || 0) + 1);
    const cutTargetText = [...cutTargetCounts.entries()].map(([target, n]) => `${target}${n > 1 ? ` ×${n}` : ''}`).join('、');
    const cutAllFirst = cutTotal > 0 && stats.every((s) => s.cutFirsts === s.cut);
    const parts = [];
    if (ownFights.length) {
      parts.push(`本局 ${fights.length} 波团战里我方先手 ${ownFights.length} 波、赢下 ${ownFightWins} 波`);
      if (foeFights.length) parts.push(`对方先手 ${foeFights.length} 波，我方 ${foeFights.length - foeFightLosses} 胜 ${foeFightLosses} 负`);
    } else if (firstTotal) {
      parts.push(`本局我方先手 ${firstTotal} 次${firstRate !== null ? `，占我方击杀 ${pct(firstRate)}` : ''}`);
    }
    if (topFirst && topFirst.first) {
      parts.push(`${topFirst.p.position || '未知分路'}·${topFirst.p.label || topFirst.p.hero} 先手 ${topFirst.first} 次最多`);
    }
    if (cutTotal) {
      parts.push(`切 C ${cutTotal} 次${cutTargetText ? `，目标 ${cutTargetText}` : ''}${cutAllFirst ? '，且都是该波团战的第一击' : ''}`);
    } else {
      parts.push('本局没有形成对对方中路 / 发育路的切 C');
    }
    const ownFirstRate = ownFights.length ? ownFightWins / ownFights.length : null;
    const tone = ownFirstRate === null ? 'is-thin'
      : (ownFightWins === ownFights.length && ownFights.length >= 2) || ownFirstRate >= 0.7 ? 'is-good'
        : ownFirstRate >= 0.5 ? 'is-thin' : 'is-bad';
    const badge = ownFirstRate === null ? '样本不足'
      : ownFightWins === ownFights.length && ownFights.length >= 2 ? '先手全胜'
        : ownFirstRate >= 0.7 ? '先手占优' : ownFirstRate >= 0.5 ? '先手一般' : '先手吃亏';
    const tiles = [
      ['先手', `${firstTotal}<small>次</small>`, '',
        firstRate !== null ? `占我方击杀 ${pct(firstRate)}` : '按击杀账本统计'],
      ['先手团战', ownFights.length ? `${ownFightWins}<i>/</i>${ownFights.length}` : '—', '赢下',
        ownFights.length ? `对方先手 ${foeFights.length} 波` : '回放没有团战段'],
      ['被先手', `${foeFights.length}`, '波',
        foeFights.length ? `我方 ${foeFights.length - foeFightLosses} 胜 ${foeFightLosses} 负` : '没有被对方先手'],
      ['切C', `${cutTotal}`, '次',
        cutTotal ? (cutTargetText || '已形成切C') : '未形成切C'],
    ];
    const statCards = stats.map((s) => `<article class="md-cut-card${s.cut ? ' is-hot' : ''}">
      <header><span class="md-cut-lane">${esc(s.p.position || '未标注')}</span><b>${esc(s.p.label || s.p.hero)}</b>${portrait(s.p.hero || '', 'md-cut-face')}</header>
      <div class="md-cut-rows">
        <div class="md-cut-row is-first"><span class="md-cut-row-label">先手</span><span class="md-cut-track"><i style="width:${Math.round(s.first / maxFirst * 100)}%"></i></span><b>${s.first}</b><small>${firstTotal ? Math.round(s.first / firstTotal * 100) + '%' : '—'}</small></div>
        <div class="md-cut-row"><span class="md-cut-row-label">击杀</span><span class="md-cut-track"><i style="width:${Math.round(s.kills / maxKills * 100)}%"></i></span><b>${s.kills}</b><small>${ownKills ? Math.round(s.kills / ownKills * 100) + '%' : '—'}</small></div>
      </div>
      <div class="md-cut-foot">
        <span class="md-cut-badge${s.cut ? ' is-live' : ''}">切C <b>${s.cut}</b></span>
        ${s.cutTargets.length ? `<span class="md-cut-targets">切了 ${s.cutTargets.map((target) => `<i>${esc(target)}</i>`).join('、')}</span>` : '<span class="md-cut-targets is-quiet">未形成切C</span>'}
      </div>
    </article>`).join('');
    const row = (k) => {
      const cut = isCut(k);
      const first = firstKeys.has(keyOf(k));
      const kl = laneOfKill(k.killerCamp, k.killer);
      const vl = laneOfKill(k.victimCamp, k.victim);
      const ownKill = k.killerCamp === own;
      return `<div class="md-kill ${ownKill ? 'own' : 'foe'}${cut ? ' is-cut' : ''}">
        <span class="md-kill-t">${time(k.t)}</span>
        <span class="md-kill-camp ${ownKill ? 'own' : 'foe'}">${ownKill ? '我方' : '对方'}</span>
        <span class="md-kill-side"><em>${esc(k.killer)}</em>${first ? '<i class="md-kill-first">先手</i>' : ''}<small>${esc(kl || '—')}</small></span>
        <span class="md-kill-arrow">→</span>
        <span class="md-kill-side"><em>${esc(k.victim)}</em><small>${esc(vl || '—')}</small></span>
        <em class="md-kill-cut">${cut ? '切C' : ''}</em>
      </div>`;
    };
    return `<section class="section" id="match-kills"><div class="section-heading"><div><h2>切C 与先手</h2><p>只算我方：切C＝我方对抗路 / 打野击杀对方中路或发育路；先手＝该波团战里的第一次击杀。五路统计在上，开团分析居中，逐条账本收在折叠区</p></div></div>
      <div class="md-cut-grid">${statCards}</div>
      <div class="md-viz-analysis md-bprev ${tone}">
        <div class="md-bprev-head"><b>开团分析</b><span class="md-bprev-badge ${tone}">${badge}</span></div>
        <p class="md-bprev-lede">${parts.join('；')}。</p>
        <div class="md-bprev-stats">${tiles.map(([label, value, unit, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}<small>${unit}</small></span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
        ${fightStrip}
        <p class="md-bprev-thin">口径：先手＝该波团战第一次击杀；切C＝对抗路 / 打野击杀对方中路、发育路；团战结果取官方回放 fights 的双方击杀数。</p>
      </div>
      <details class="md-camp md-kill-fold"><summary>逐条击杀账本 <b>${rows.length}</b> 条 <small>时间 · 阵营 · 击杀方 → 被击杀方</small></summary>
        <div class="md-kill-list">${rows.map(row).join('')}</div>
      </details>
    </section>`;
  })();
  /* 事件详情：资源/推塔事件的参战者与伤害占比（keyEventArr.hurtTotal），
     以及营地复盘的中文叙述（adviceList）。仅官方回放存在时显示。
     重排：资源与推塔分两组卡片，多参战者用分段占比条，单参战者不画 100% 长条；
     下方给一条事件分析（控图、推塔节奏、参战与伤害集中度）。 */
  const mdEventDetail = (() => {
    const replay = m.replay || {};
    const all = (replay.events || []).filter((e) => e.kind === 'resource' || e.kind === 'structure');
    const narrations = replay.narrations || [];
    /* keyEventArr 的 hurtTotal 只在推塔类事件里和「伤害」一个量级；
       野怪/暴君事件的取值会到千万级（同一份数据里 800 与 21005396 并存），
       单位没有被证实。所以超过 10 万的绝对值不显示，也不参与占比计算。 */
    const TRUST_HURT = 100000;
    const trustedValue = (v) => has(v) && v < TRUST_HURT;
    const reliable = (e) => (e.participants || []).every((p) => !has(p.hurtTotal) || p.hurtTotal < TRUST_HURT);
    const keyEvents = all.filter((e) => e.name && e.name !== '野怪')
      .slice().sort((a, b) => a.t - b.t);
    if (!keyEvents.length && !narrations.length) return '';
    const resources = keyEvents.filter((e) => e.kind === 'resource');
    const structures = keyEvents.filter((e) => e.kind === 'structure');
    const sideOf = (e) => (e.killerCamp === own ? 'own' : e.killerCamp ? 'foe' : '');
    const tierOf = (label) => /水晶/.test(label) ? '水晶'
      : /高地塔/.test(label) ? '高地塔' : /二塔/.test(label) ? '二塔' : /一塔/.test(label) ? '一塔' : '建筑';
    /* 参战与「可核单位」伤害的集中度：单位不可信的事件不参与伤害汇总。 */
    const participated = keyEvents.filter((e) => (e.participants || []).length);
    const heroTally = new Map();
    const damageTally = new Map();
    for (const e of participated) {
      for (const p of e.participants || []) {
        const hero = p.hero || p.name;
        if (!hero) continue;
        const row = heroTally.get(hero) || { hero, events: 0, structures: 0, resources: 0 };
        row.events += 1;
        if (e.kind === 'structure') row.structures += 1; else row.resources += 1;
        heroTally.set(hero, row);
      }
      if (!reliable(e)) continue;
      const total = (e.participants || []).reduce((sum, p) => sum + (has(p.hurtTotal) ? p.hurtTotal : 0), 0);
      if (!total) continue;
      for (const p of e.participants || []) {
        const hero = p.hero || p.name;
        if (!hero || !has(p.hurtTotal) || !p.hurtTotal) continue;
        const row = damageTally.get(hero) || { hero, damage: 0 };
        row.damage += p.hurtTotal;
        damageTally.set(hero, row);
      }
    }
    const trustTotal = [...damageTally.values()].reduce((sum, row) => sum + row.damage, 0);
    const damageRank = [...damageTally.values()].sort((a, b) => b.damage - a.damage);
    const participateRank = [...heroTally.values()].sort((a, b) => b.events - a.events);
    const topParticipant = participateRank[0] || null;
    const topDamage = trustTotal ? { ...damageRank[0], share: Math.round(damageRank[0].damage / trustTotal * 100) } : null;
    const ownEvents = keyEvents.filter((e) => sideOf(e) === 'own');
    const foeEvents = keyEvents.filter((e) => sideOf(e) === 'foe');
    const ownResources = resources.filter((e) => sideOf(e) === 'own');
    const ownStructures = structures.filter((e) => sideOf(e) === 'own');
    const foeStructures = structures.filter((e) => sideOf(e) === 'foe');
    const foeTowers = foeStructures.filter((e) => tierOf(eventLabel(e)) !== '水晶').length;
    const foeCrystal = foeStructures.find((e) => tierOf(eventLabel(e)) === '水晶');
    const crystal = ownStructures.find((e) => tierOf(eventLabel(e)) === '水晶');
    const towerCount = ownStructures.filter((e) => tierOf(eventLabel(e)) !== '水晶').length;
    const firstStructure = structures[0] || null;
    const resourceNames = [...new Set(resources.map((e) => eventLabel(e)))];
    const ownResourceNames = [...new Set(ownResources.map((e) => eventLabel(e)))];
    /* 事件分析一句话：先讲结果，再讲推塔节奏与参战集中度。 */
    const parts = [];
    parts.push(`本局 ${keyEvents.length} 个关键事件，我方拿下 ${ownEvents.length} 个${foeEvents.length ? `、对手 ${foeEvents.length} 个` : ''}`);
    if (resources.length) {
      parts.push(ownResources.length
        ? `我方拿下 ${ownResourceNames.join('、')} ${ownResources.length} 条`
        : `${resourceNames.join('、')} 全被对手拿走`);
    }
    if (structures.length) {
      parts.push(`我方推塔 ${towerCount} 座${crystal ? ` + 水晶（${time(crystal.t)}）` : ''}${firstStructure ? `，首推 ${time(firstStructure.t)}` : ''}`);
      if (foeTowers || foeCrystal) parts.push(`对手推掉我方 ${foeTowers} 座${foeCrystal ? ' + 水晶' : ''}`);
    }
    if (topParticipant) parts.push(`${topParticipant.hero} 参战 ${topParticipant.events} 次最多`);
    if (topDamage && topDamage.damage) parts.push(`可核建筑伤害里 ${topDamage.hero} 占 ${pct(topDamage.share)}`);
    const tone = ownEvents.length > foeEvents.length ? 'is-good' : ownEvents.length < foeEvents.length ? 'is-bad' : 'is-thin';
    const badge = ownEvents.length > foeEvents.length ? '我方控图'
      : ownEvents.length < foeEvents.length ? '对手控图' : '势均力敌';
    const eventCard = (e) => {
      const side = sideOf(e);
      const label = eventLabel(e);
      const participants = (e.participants || []).slice()
        .sort((a, b) => (b.hurtTotal || 0) - (a.hurtTotal || 0));
      const ok = reliable(e);
      const total = participants.reduce((sum, p) => sum + (has(p.hurtTotal) ? p.hurtTotal : 0), 0);
      const shareOf = (p) => (ok && total && has(p.hurtTotal) ? Math.round(p.hurtTotal / total * 100) : null);
      const segments = ok && total && participants.length > 1
        ? `<div class="md-ev-seg">${participants.map((p) => {
            const share = shareOf(p);
            return `<i class="is-${p.camp === own ? 'own' : 'foe'}" style="width:${share}%" title="${esc((p.hero || p.name || '') + ' ' + share + '%')}"></i>`;
          }).join('')}</div>`
        : '';
      const chips = participants.length
        ? `<div class="md-ev-parts">${participants.map((p) => {
            const name = p.hero || p.name || '—';
            /* 单参战者不显示 100%；单位不可信的事件只列参战者，不显示占比和数值。 */
            const share = participants.length > 1 && ok ? shareOf(p) : null;
            const showValue = trustedValue(p.hurtTotal) && (participants.length === 1 || ok);
            return `<span class="md-ev-part is-${p.camp === own ? 'own' : 'foe'}">${portrait(name, 'md-ev-face')}<em>${esc(name)}</em>${share !== null ? `<b>${share}%</b>` : ''}${showValue ? `<small>${fmt(p.hurtTotal)}</small>` : ''}</span>`;
          }).join('')}</div>`
        : '<p class="md-ev-empty">回放未记录参战者，只按结果计入</p>';
      const tag = side ? (e.kind === 'structure'
        ? (side === 'own' ? '我方推掉' : '对手推掉')
        : (side === 'own' ? '我方拿下' : '对手拿下')) : '归属未记录';
      /* 卡片名本身已带「对方 / 我方 + 路 + 塔序」，这里只标事件类别。 */
      const kind = e.kind === 'resource' ? '资源' : '推塔';
      return `<article class="md-ev-card${side ? ' is-' + side : ''}">
        <header class="md-ev-head">
          <span class="md-ev-t">${time(e.t)}</span>
          <span class="md-ev-kind">${kind}</span>
          <b class="md-ev-name">${esc(label)}</b>
          <span class="md-ev-tag ${side || 'is-unknown'}">${tag}</span>
          <small class="md-ev-meta">${participants.length ? `${participants.length} 人参与` : '仅记结果'}</small>
        </header>
        ${segments}${chips}
      </article>`;
    };
    const eventGroup = (title, list, towerMode) => {
      if (!list.length) return '';
      const ownCount = list.filter((e) => sideOf(e) === 'own').length;
      const foeCount = list.filter((e) => sideOf(e) === 'foe').length;
      return `<div class="md-ev-group">
        <div class="md-ev-group-head"><b>${title}</b><span>${list.length} 个 · 我方 ${ownCount}${foeCount ? ` / 对手 ${foeCount}` : ''}</span></div>
        <div class="md-ev-cards${towerMode ? ' is-towers' : ''}">${list.map(eventCard).join('')}</div>
      </div>`;
    };
    const notes = [];
    if (participated.length < keyEvents.length) {
      notes.push(`${keyEvents.length - participated.length} 个事件回放未记录参战者，只按结果计入`);
    }
    if (participated.some((e) => !reliable(e))) {
      notes.push('资源类事件的伤害单位营地未证实（同一份回放里 800 与 2100 万并存），这类事件只列参战者、不显示数值');
    }
    /* 营地叙述里带的 <c="#颜色">…</c> 富文本标记转成纯文本。 */
    const plainNarration = (text) => String(text || '').replace(/<c="[^"]*">/g, '').replace(/<\/c>/g, '');
    const resTiles = [
      ['关键事件', `${keyEvents.length}<small>个</small>`, `资源 ${resources.length} · 建筑 ${structures.length}`],
      ['资源控制', `${ownResources.length}<i>/</i>${resources.length}`,
        ownResourceNames.length ? `${ownResourceNames.join('、')} · 我方拿下`
          : resources.length ? '资源全被对手拿走' : '本局没有资源事件'],
      ['推塔', `${towerCount}<small>座</small>${crystal ? '<i>+</i><small>水晶</small>' : ''}`, firstStructure ? `首推 ${time(firstStructure.t)}` : '回放没有建筑事件'],
      ['参战最多', `${topParticipant ? topParticipant.events : 0}<small>次</small>`, topParticipant ? topParticipant.hero : '回放没有参战记录'],
    ];
    /* 只有叙述、没有关键事件的对局：不渲染空分组和空分析，只留叙述。 */
    const eventHtml = keyEvents.length ? `<div class="md-ev-groups">
        ${eventGroup('关键资源', resources, false)}
        ${eventGroup('推塔与水晶', structures, true)}
      </div>
      <div class="md-viz-analysis md-bprev ${tone}">
        <div class="md-bprev-head"><b>事件分析</b><span class="md-bprev-badge ${tone}">${badge}</span></div>
        <p class="md-bprev-lede">${parts.join('；')}。</p>
        <div class="md-bprev-stats">${resTiles.map(([label, value, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}</span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
        <p class="md-bprev-thin">口径：只统计官方回放 keyEventArr 的资源与建筑事件，归属按 killerCamp；伤害占比只在单位可信的事件内计算。</p>
      </div>` : '';
    return `<section class="section" id="match-events"><div class="section-heading"><div><h2>事件详情</h2><p>官方回放 keyEventArr：资源 / 推塔事件按时间排成卡片，参战者用分段占比；单位不可信时只列参战。下方附事件分析与营地复盘叙述</p></div></div>
      ${eventHtml}
      ${narrations.length ? `<details class="md-ev-narr"><summary>营地复盘叙述 <b>${narrations.length}</b> 条 <small>官方回放 adviceList</small></summary>${narrations.slice(0, 20).map((n) => `<p><span>${time(n.t)}</span>${esc(plainNarration(n.text))}</p>`).join('')}</details>` : ''}
      ${notes.length ? `<p class="md-ev-note">${notes.join('；')}。</p>` : ''}
    </section>`;
  })();
  const mdFront = `<section class="section" id="match-front"><div class="section-heading"><div><h2>阵线</h2><p>五人平均推进进度：0 是己方基地、100% 是对方基地；线越过中线说明压过去了。分段线是对线/发育/后期的分界</p></div></div>
    ${deep.frontline(m.positions, m.players, own, m.duration) || '<div class="empty">这局没有位置数据</div>'}
  </section>`;
  const mdSource = `<p class="md-source">数据来源：王者营地面板（十人结算 / 经济采样 / 分路派生卡片）、官方回放事件与营地逐秒位置 · ${esc(m.date || '')} ${esc(m.opponent ? '对阵 ' + m.opponent : '')}</p>`;
  /* 单局页原来一屏 8000px：复盘要往上翻很久才看得到十人面板。
     按「看结论 / 看十人 / 看事件 / 看地图」拆成四个页签，
     每页只保留自己那段，地址仍带页签，刷新后停在原处。 */
  const mdTab = ['review', 'data', 'events', 'map'].includes(current().tab) ? current().tab : 'review';
  const tabButton = (key, label, note) => `<button type="button" class="md-tab" data-md-tab="${key}"
    role="tab" aria-selected="${key === mdTab}"><b>${label}</b><small>${note}</small></button>`;
  const mdTabs = `<div class="md-tabs" role="tablist" aria-label="单局页签">
    ${tabButton('review', '复盘', '结论 · BP · 阶段')}
    ${tabButton('data', '十人数据', '对位 · 同队 · 营地卡片')}
    ${tabButton('events', '事件', '击杀 · 资源 · 叙述')}
    ${tabButton('map', '地图', '阵线 · 热区 · 纵深')}
  </div>`;
  return `<div class="page md-page" data-md-tab-active="${mdTab}">${mdCrumb}${mdTabs}
    <div class="md-pane" data-md-pane="review">${mdHero}${mdBp}${mdTotals}${mdPhases}${mdPulse}${mdTimeline}</div>
    <div class="md-pane" data-md-pane="data">${mdGold10}${mdProfiles}${mdJungle}${mdCohesion}</div>
    <div class="md-pane" data-md-pane="events">${mdFights}${mdDeaths}${mdKills}${mdEventDetail}</div>
    <div class="md-pane" data-md-pane="map">${mdFront}${mdHeat}${mdDuel}</div>
    ${mdSource}
    </div>`;
}

const tour = createTour();
/* 首页决策入口：只接管 #home-decision 容器，数据单独异步取，失败不阻塞首页。 */
const homeDecision = createHomeDecision({ esc, fmt, time, icon, route });
/* 决策台：四个工作区在网页端直接可看。数据域独立（/api/decision/*），
   自带取数、abort 与重试，因此 load() 对它跳过常规 endpoint。 */
const decisionPage = createDecisionPage({ esc, fmt, pct, diff, time, table, icon, route, API_BASE, currentQuery: () => query() });
/* BP 抗针对放在 BP 模块自己的子页（#bpcounter），决策台赛前备战只放摘要入口。 */
const bpCounter = createBpCounter({ esc, fmt, pct, icon });
const features = createFeatures({ esc, fmt, pct, diff, time, portrait, route, table, pageIntro, icon, microChart, gameAnchorBar, reload: () => load(true), currentQuery: () => query() });
const deep = createMatchDeep({ esc, fmt, pct, diff, time, portrait, phases: phaseWindows,
  gpmOf, goldGrade });
const crossPage = createCrossPage({ esc, fmt, pct, diff, time, portrait });
deep.bindPanel(document);
/* 比赛脉搏交互需要原始序列，渲染时记下来，注入 DOM 后再绑定。 */
let pulseState = null;
const renderers = { overview, decision: () => '<div id="decision-root" class="decision-root"></div>', bpcounter: () => '<div id="bpcounter-root"></div>',
  matches: matchesPage, opponents: opponentsPage, players: playersPage,
  player: playerPage, tempo: tempoPage, sources: sourcesPage, match: matchPage,
  cross: (d) => (d && d.cross ? crossPage.render(d.cross, { total: d.crossTotal || d.cross.length, limit: d.crossLimit || CROSS_LIMIT, cohort: d.cohort }) : '<div class="page"><div class="loading">正在汇总各局数据…</div></div>') };
let lastRenderedRoute = '';
function render(r = current()) {
  /* 换路由时回到顶部：从很长的单局页切到跨局分析，不重置会停在中段 */
  const routeKey = `${r.name}/${r.key || ''}`;
  const isNewRoute = routeKey !== lastRenderedRoute;
  lastRenderedRoute = routeKey;
  document.querySelectorAll('[data-nav]').forEach((a) => {
    if (a.dataset.nav === sectionFor(r.name)) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  document.title = labels[r.name] + ' | 赛训数据';
  const tabs = featureSections[sectionFor(r.name)] || [];
  const secondary = document.querySelector('.secondary-wrap');
  secondary.hidden = tabs.length < 2;
  const activeTab = {ownership:'setup', pending:'setup', effect:'reports', session:'plan', weekly:'reports', identity:'players'}[r.name] || r.name;
  secondary.querySelector('nav').innerHTML = tabs.map(([key, label]) => `<a href="#${key}" ${key === activeTab || ({match:'matches',player:'players',playerdetail:'players',team:'teams',hero:'heroes',report:'reports'}[r.name] === key) ? 'aria-current="page"' : ''}>${label}</a>`).join('');
  document.querySelector('#content').innerHTML = features.has(r.name) ? features.render(r.name, data, r.key) : renderers[r.name](data, r.key);
  /* 分析专题不设平铺导航入口：跨局分析从页面内按需进入。
     #topic/* 与 #study/* 路由仍保留可达（labels / sectionFor 兜底），只是不再出现在导航条。 */
  const analysisRail=secondary.querySelector('.analysis-rail');
  analysisRail.innerHTML='';
  analysisRail.hidden=true;
  features.afterRender();
  /* 决策台自己挂载：#decision-root 里再拉 /api/decision/*，失败只影响本页，不触发全站重试。 */
  if (r.name === 'decision') {
    const root = document.querySelector('#decision-root');
    if (root) decisionPage.mount(root, r);
  }
  if (r.name === 'bpcounter') {
    const root = document.querySelector('#bpcounter-root');
    if (root) bpCounter.mount(root);
  }
  /* 决策卡在 overview 渲染成功后才挂载：welcomePage（空库）没有这个容器，自动跳过；
     接口慢或失败只影响这一块，首页其余区块照常显示。 */
  if (r.name === 'overview') {
    const box = document.querySelector('#home-decision');
    if (box) {
      homeDecision.hydrate(box, { from: filters.from || '', to: filters.to || '' });
      homeDecision.bind(box);
    }
  }
  if (r.name === 'overview' && data && data.summary && !data.summary.matches) hydrateWelcome();
  if (r.name === 'player') {
    /* 选手不在当前数据范围时 stats 为 null，也要把四个子面板收尾，
       否则「正在读取…」会永久停留（2026-11-07 上线测评发现）。 */
    const playerLabel = (data && ((data.stats && data.stats.label) || data.label)) || r.key || '';
    hydratePlayer(playerLabel);
  }
  if (r.name === 'match' && pulseState) deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
  if (r.name === 'match') deep.bindHeat(document);
  if (r.name === 'match') deep.bindBattle(document);
  if (r.name === 'cross') crossPage.bind(document);
  updateMode();
  if (isNewRoute) window.scrollTo(0, 0);
  refreshInbox();
  tour.afterRender();
}

/* 跨局分析：按当前筛选范围，把每局的详情 / 位置 / 回放各取一次。
   局数会持续增长，这里分批并发取回一个分析窗口（默认最近 200 局），
   页面结论基于窗口内全量，渲染按页分批；总数单独带回用于写明口径。 */
const CROSS_LIMIT = 200;
async function hydrateCross(detail, signal) {
  const all = detail.matches || [];
  const list = all.slice(0, CROSS_LIMIT);
  detail.crossTotal = all.length;
  detail.crossLimit = CROSS_LIMIT;
  /* 通用跨局分析的总体：一次请求拿到全量局的轻量向量，不随局数放大请求数。
     逐局对照台仍取最近一个明细窗口，两者互不干扰。 */
  try {
    const response = await fetch(API_BASE + '/api/cross/vectors' + query(), { signal, cache: 'no-store' });
    if (response.ok) detail.cohort = await response.json();
  } catch {
    detail.cohort = null;
  }
  const rows = new Array(list.length).fill(null);
  let next = 0;
  const take = async () => {
    while (next < list.length && !signal.aborted) {
      const index = next++;
      const m = list[index];
      const url = (path) => API_BASE + '/api/' + path + encodeURIComponent(m.key);
      try {
        const [d, pos, rep] = await Promise.all([
          fetch(url('matches/'), { signal, cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)),
          fetch(url('positions/'), { signal, cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
          fetch(url('replay/'), { signal, cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
        ]);
        if (!d) continue;
        rows[index] = {
          key: m.key,
          date: d.date || m.date || '',
          opponent: d.opponent || m.opponent || '',
          result: d.result || m.result || '',
          duration: d.duration || m.duration || 0,
          version: d.version || m.version || '',
          session: d.session || m.session || '',
          ownCamp: d.ownCamp,
          players: d.players || [],
          detail: d,
          positions: pos,
          replay: rep,
        };
      } catch {
        /* 单局取数失败就跳过，不让一局拖垮整页 */
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(6, list.length) }, take));
  detail.cross = rows.filter(Boolean);
}

async function load(fresh = false) {
  const generation = ++loadGeneration;
  request?.abort();
  request = new AbortController();
  const currentRequest = request;
  const r = current();
  const routeKey = routeKeyOf(r);
  /* 换页归零重试计数；手动刷新也给一次全新的重试机会。 */
  if (routeKey !== loadRoute) { loadRoute = routeKey; retryByRoute.clear(); }
  if (fresh) retryByRoute.delete(routeKey);
  const stale = () => isStale(generation, routeKey);
  /* 离线期间：不逐页发请求，直接渲染占位；探活成功后会自动 load() 当前页。 */
  if (offlineSince) { renderOffline(r); return; }
  /* 决策台自带取数 / abort / 页面内重试：这里不请求页面 endpoint，直接渲染并挂载。
     这样即便 /api/decision 暂时失败，也不会被 load() 的静默重试和整页报错逻辑吃掉。 */
  if (r.name === 'decision' || r.name === 'bpcounter') {
    data = null;
    render(r);
    return;
  }
  const endpoint = r.name === 'players' ? 'v3/players/board'
    : ({ match: 'matches/', player: 'players/', opponents: 'studio/teams', cross: 'matches' }[r.name] || r.name) + (['match','player'].includes(r.name) ? encodeURIComponent(r.key) : '');
  document.querySelector('#content').innerHTML = '<div class="page"><div class="loading">正在读取赛训数据…</div></div>';
  /* 详情路由缺 ID（直接输入 #session / #match 等）：别去请求一个空 key，
     那会 404 后落到"暂时读不到数据"的死循环。给出明确的返回入口。 */
  /* 「选手认领」是整页不是详情页：它没有单条 ID，缺 key 也应该正常渲染。 */
  const DETAIL_ROUTES = ['match', 'player', 'playerdetail', 'hero', 'team', 'session', 'competition', 'report', 'topic', 'study'];
  if (DETAIL_ROUTES.includes(r.name) && !r.key) {
    const section = sectionFor(r.name).name;
    const label = labels[r.name] || '条目';
    document.querySelector('#content').innerHTML = `<div class="page"><section class="section"><div class="offline-card">
      <b>还没有选定${esc(label)}</b>
      <p>这个页面需要一个具体的${esc(label)} ID。请从列表页打开，或先返回上一级。</p>
      <div class="offline-actions"><a class="control" href="#${esc(section)}">返回${esc(labels[section] || '列表')}</a></div>
    </div></section></div>`;
    return;
  }
  try {
    const [result, meta] = await Promise.all([features.has(r.name) ? features.load(r.name, r.key, currentRequest.signal) : get(endpoint, fresh), metadata.icons ? Promise.resolve(metadata) : get('metadata')]);
    if (stale()) return;
    metadata = meta;
    data = result;
    retryByRoute.delete(routeKey);
    if (r.name === 'match') data.replayStatus = 'loading';
    render(r);
    if (r.name === 'match') {
      try {
        const [response, posResponse] = await Promise.all([
          fetch(API_BASE + '/api/replay/' + encodeURIComponent(r.key), { signal: currentRequest.signal, cache: 'no-store' }),
          fetch(API_BASE + '/api/positions/' + encodeURIComponent(r.key), { signal: currentRequest.signal, cache: 'no-store' }).catch(() => null),
        ]);
        data.positionsRequested = true;
        if (stale()) return;
        data.replayStatus = response.status === 404 ? 'unavailable' : response.ok ? 'ready' : 'error';
        if (response.ok) data.replay = await response.json();
        if (posResponse && posResponse.ok) data.positions = await posResponse.json();
        try {
          const combosResponse = await fetch(API_BASE + '/api/studio/camp-combos?min=2', { signal: currentRequest.signal });
          if (combosResponse.ok) data.combosData = await combosResponse.json();
        } catch { /* 组合数据失败不影响主页面 */ }
        try {
          const matchupResponse = await fetch(API_BASE + '/api/depth/analysis/lane_matchup', { signal: currentRequest.signal });
          if (matchupResponse.ok) data.laneMatchup = await matchupResponse.json();
        } catch { /* 对位压制历史失败不影响主页面 */ }
      } catch {
        if (stale()) return;
        data.replayStatus = 'error';
      }
      if (!stale()) {
        const temp=document.createElement('div');temp.innerHTML=matchPage(data);
        /* 单局页拆成四个页签后，后到的区块必须插回它自己的页签，
           否则「事件」页里的击杀账本会被塞进隐藏的「地图」页。 */
        const PANE_OF = {
          'match-verdict': 'review', 'match-bp': 'review', 'match-phases': 'review',
          'match-pulse': 'review', 'match-timeline': 'review',
          'match-profiles': 'data', 'match-cohesion': 'data',
          'match-battle': 'events', 'match-deaths': 'events', 'match-kills': 'events', 'match-events': 'events',
          'match-front': 'map', 'match-heat': 'map', 'match-duel': 'map',
        };
        ['match-verdict','match-bp','match-phases','match-pulse','match-timeline','match-profiles','match-cohesion','match-battle','match-deaths','match-kills','match-events','match-front','match-heat','match-duel'].forEach((id)=>{
          const existing=document.getElementById(id),updated=temp.querySelector('#'+id);
          if(existing&&updated)existing.replaceWith(updated);
          else if(updated){ /* 首次渲染没有该区块（如依赖回放的事件详情）：插到对应页签末尾 */
            const pane=document.querySelector(`[data-md-pane="${PANE_OF[id] || 'review'}"]`);
            if(pane) pane.append(updated);
          }
          /* 回放后到、后来渲染出正式区块时，把首屏的「没有团战数据」占位删掉 */
          else if(existing && (id === 'match-battle' || id === 'match-deaths')) existing.remove();
        });
        if (pulseState) deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
        deep.bindHeat(document);
        deep.bindBattle(document);
      }
    }
    if (r.name === 'cross') {
      await hydrateCross(data, currentRequest.signal);
      if (!stale()) render(r);
    }
  } catch (error) {
    /* 主动取消的请求、已经切走的页面：既不重试，也不把错误写进新页面。 */
    if (stale() || isCancelled(error, currentRequest.signal)) return;
    /* 网络层断开：进入自动重连，恢复后自动加载当前页。 */
    const offline = error instanceof TypeError
      || /Failed to fetch|NetworkError|Load failed|Network request failed/i.test(String(error?.message || ''));
    if (offline) {
      setOffline(true);
      renderOffline(r);
      return;
    }
    /* 单次接口失败（含静态资源与路由表短暂错配）先静默重试，页面保持「正在读取」；
       连续失败才给一页可读提示，绝不把英文 detail 或本地运维话术摆给教练。 */
    const attempts = retryByRoute.get(routeKey) || 0;
    if (attempts < 2) {
      retryByRoute.set(routeKey, attempts + 1);
      setTimeout(() => { if (!isStale(generation, routeKey)) load(fresh); }, 350 * (attempts + 1));
      return;
    }
    retryByRoute.delete(routeKey);
    renderDataNotice(r);
  }
}

function namePlayerDialog(label) {
  const dialog = document.querySelector('#filters');
  const team = (metadata && metadata.teamName) || '';
  dialog.innerHTML = `<form id="name-form"><div class="dialog-head"><div><h2>命名并归队</h2><p>把「${esc(label)}」归到一名选手和一支战队；保存后这些记录并入该选手。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <div class="date-fields"><label>对局昵称<input value="${esc(label)}" readonly></label><label>选手名称<input name="name" required maxlength="40" value="${esc(label)}"></label></div>
      <div class="date-fields"><label>位置<select name="position"><option value="">待确认</option>${['对抗路', '打野', '中路', '发育路', '游走'].map((x) => `<option>${x}</option>`).join('')}</select></label><label>所属战队<input name="team" maxlength="40" value="${esc(team)}" placeholder="默认本队"></label></div>
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">保存并归队</button></div></form>`;
  dialog.showModal();
}

function filterDialog() {
  const dialog = document.querySelector('#filters');
  dialog.innerHTML = `<form id="filter-form"><div class="dialog-head"><div><h2>数据范围</h2><p>选择日期、来源与样本。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><div class="date-fields"><label>开始日期<input type="date" name="from" value="${esc(filters.from)}"></label>
    <label>结束日期<input type="date" name="to" value="${esc(filters.to)}"></label></div><fieldset><legend>数据来源</legend>
    ${Object.entries(sourceName).map(([key, text]) => `<label class="check"><input type="checkbox" name="source" value="${key}" ${filters.source.includes(key) ? 'checked' : ''}>${text}</label>`).join('')}</fieldset>
    <label class="check"><input type="checkbox" name="validation" ${filters.validation ? 'checked' : ''}>包含验证数据</label><p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="reset">恢复默认</button><button class="primary" type="submit">应用范围</button></div></form>`;
  dialog.showModal();
}

function clientMissingDialog() {
  const dialog = document.querySelector('#filters');
  dialog.innerHTML = `<div class="dialog-head"><div><h2>没有检测到客户端</h2>
    <p>可能还没有安装，或系统没有注册 kpl-client://open 协议。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><p>下载安装后，再点「打开客户端」即可从这里直接进入客户端；当前页面会自动带过去。</p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">稍后</button>
      <a class="primary" href="${CLIENT_DOWNLOAD_URL}" target="_blank" rel="noopener">去下载客户端</a></div>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
}

app.addEventListener('click', (event) => {
  const editOpponent = event.target.closest('[data-match-edit]');
  if (editOpponent) {
    event.preventDefault();
    event.stopPropagation();
    opponentDialog(editOpponent.dataset.matchEdit, editOpponent.dataset.opponent || '');
    return;
  }
  if (features.click(event)) return;
  if (event.target.closest('[data-sx-inbox]')) { openInbox(); return; }
  if (event.target.closest('[data-sx-inbox-close]')) { document.querySelector('#sx-inbox-dialog')?.close(); return; }
  if (event.target.closest('[data-sx-inbox-link]')) { document.querySelector('#sx-inbox-dialog')?.close(); return; }
  if (event.target.closest('[data-sx-map-opponent]')) {
    const row = event.target.closest('.sx-inbox-map');
    const button = event.target.closest('button');
    const teamId = row?.querySelector('select')?.value;
    if (!row || !teamId) return;
    button.disabled = true;
    button.textContent = '映射中…';
    fetch(API_BASE + '/api/studio/workspace/opponents/map', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({oldId:row.dataset.oldId, teamId}),
    }).then(async (response) => {
      if (!response.ok) {
        let detail = '映射失败';
        try { detail = (await response.json()).detail || detail; } catch {}
        throw new Error(detail);
      }
      document.querySelector('#sx-inbox-dialog')?.close();
      await load(true);
    }).catch((error) => {
      button.disabled = false;
      button.textContent = '映射';
      window.alert(error.message);
    });
    return;
  }
  const mdTabHit = event.target.closest('[data-md-tab]');
  if (mdTabHit) {
    const page = mdTabHit.closest('.md-page');
    const key = mdTabHit.dataset.mdTab;
    if (!page || !key) return;
    page.dataset.mdTabActive = key;
    page.querySelectorAll('[data-md-tab]').forEach((node) => {
      node.setAttribute('aria-selected', String(node.dataset.mdTab === key));
    });
    /* 换页签不重新取数：只切显示，地址用 replaceState 同步，刷新后停在原页签。 */
    try {
      const route = current();
      history.replaceState(null, '', `#match/${encodeURIComponent(route.key)}/${key}`);
    } catch { /* 某些嵌入式浏览器禁 replaceState，忽略 */ }
    document.querySelector('#content')?.scrollIntoView({ block: 'start' });
    return;
  }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action) return;
  if (action === 'tour') { tour.start(); return; }
  if (action === 'open-client') {
    event.preventDefault();
    const started = Date.now();
    try { window.location.href = 'kpl-client://open'; } catch { /* 交给下面的兜底提示 */ }
    // 协议已注册时客户端会抢走焦点；页面仍有焦点说明多半没装。
    setTimeout(() => {
      if (document.hasFocus() && Date.now() - started < 6000) clientMissingDialog();
    }, 1800);
    return;
  }
  if (action === 'demo') {
    if (metadata.demo) {
      let origin='http://127.0.0.1:8766';
      try { const candidate=new URL(new URLSearchParams(location.search).get('return')); if (['127.0.0.1','localhost'].includes(candidate.hostname) && candidate.protocol==='http:') origin=candidate.origin; } catch {}
      location.assign(origin+'/#overview');
    } else {
      const button=event.target.closest('button'); button.disabled=true; const label=button.querySelector('span'); if(label)label.textContent='正在准备…';
      const start = async () => {
        const response = await fetch(API_BASE + '/api/demo/start',{method:'POST'});
        const body = await response.json();
        if (!response.ok) throw Error(body.detail||'演示环境启动失败');
        return body;
      };
      start().then(body=>{const url=new URL(body.url);url.searchParams.set('return',location.origin);location.assign(url.href+'#overview')}).catch(error=>{button.disabled=false;if(label)label.textContent='演示数据';window.alert(error.message)});
    }
    return;
  }
  if (action === 'theme') { theme = theme === 'light' ? 'dark' : 'light'; localStorage.setItem('training-rebuild-theme', theme); applyTheme(); }
  if (action === 'open-data') {
    fetch(API_BASE + '/api/data/open', { method: 'POST' })
      .then((response) => { if (!response.ok) throw new Error(); })
      .catch(() => window.alert('没能打开数据目录，请手动打开安装目录下的 data 文件夹。'));
    return;
  }
  if (action === 'migrate-legacy') {
    const button = event.target.closest('[data-action]');
    const heavy = document.querySelector('[data-welcome-legacy] [data-migrate-heavy]');
    button.disabled = true;
    startMigration(button.dataset.path, heavy ? heavy.checked : true);
    return;
  }
  if (action === 'migrate-path') {
    const input = document.querySelector('[data-welcome-path]');
    const value = (input?.value || '').trim().replace(/^"|"$/g, '');
    if (!value) { input?.focus(); return; }
    const heavy = input.closest('details')?.querySelector('[data-migrate-heavy]');
    event.target.closest('button').disabled = true;
    startMigration(value, heavy ? heavy.checked : true);
    return;
  }
  if (action === 'refresh') {
    metadata = {};
    /* 离线时点重试：立刻探活一次，服务回来了就自动加载当前页。 */
    if (offlineSince) { reconnectDelay = 600; scheduleReconnect(0); }
    load(true);
  }
  if (action === 'filter') filterDialog();
  if (action === 'name-player') { namePlayerDialog(event.target.closest('[data-action]').dataset.label); return; }
  if (action === 'close') document.querySelector('#filters').close();
  if (action === 'menu') {
    const menu = document.querySelector('.mobile-menu');
    menu.hidden = !menu.hidden;
    event.target.closest('button').setAttribute('aria-expanded', String(!menu.hidden));
  }
  if (action === 'reset') {
    const form = document.querySelector('#filter-form');
    form.elements.from.value = '';
    form.elements.to.value = '';
    form.elements.validation.checked = false;
    form.querySelectorAll('[name="source"]').forEach((x) => { x.checked = ['db','bundle'].includes(x.value); });
    form.querySelector('.filter-error').textContent = '';
  }
});

app.addEventListener('submit', (event) => {
  if (features.submit(event)) return;
  if (event.target.id === 'opponent-form') {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = { opponent: String(form.get('opponent') || '').trim() };
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    fetch(API_BASE + '/api/v3/match-meta/' + encodeURIComponent(event.target.dataset.key), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      document.querySelector('#filters').close();
      load(true);
    }).catch((err) => {
      button.disabled = false;
      event.target.querySelector('.filter-error').textContent = err.message;
    });
    return;
  }
  if (event.target.name === 'opponent' && event.target.closest('#opponent-form')) return;
  if (event.target.id === 'name-form') {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = { label: event.target.querySelector('input[readonly]').value, name: form.get('name'), position: form.get('position'), team: form.get('team') };
    const error = !String(payload.name || '').trim() ? '请填写选手名称。' : '';
    event.target.querySelector('.filter-error').textContent = error;
    if (error) return;
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    fetch(API_BASE + '/api/v3/identity/name', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(async (response) => { const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.detail || '保存失败'); document.querySelector('#filters').close(); load(true); })
      .catch((err) => { button.disabled = false; event.target.querySelector('.filter-error').textContent = err.message; });
    return;
  }
  if (event.target.id !== 'filter-form') return;
  event.preventDefault();
  const form = new FormData(event.target);
  const source = form.getAll('source');
  const from = form.get('from') || '', to = form.get('to') || '';
  const error = !source.length ? '请至少选择一个数据来源。' : from && to && from > to ? '开始日期不能晚于结束日期。' : '';
  event.target.querySelector('.filter-error').textContent = error;
  if (error) return;
  filters = { source, from, to, validation: form.has('validation') };
  localStorage.setItem('training-rebuild-filters', JSON.stringify(filters));
  document.querySelector('#filters').close();
  load();
});

app.addEventListener('input', (event) => {
  features.change(event);
  if (event.target.name !== 'search' || !renderers[current().name]) return;
  view.search = event.target.value;
  const results = document.querySelector('[data-results]');
  const temp = document.createElement('div');
  const r = current();
  temp.innerHTML = renderers[r.name](data, r.key);
  results.innerHTML = temp.querySelector('[data-results]').innerHTML;
  const count=document.querySelector('[data-result-count]');if(count)count.innerHTML=temp.querySelector('[data-result-count]')?.innerHTML||'';
  const summary=document.querySelector('.match-overview');if(summary)summary.innerHTML=temp.querySelector('.match-overview')?.innerHTML||'';
});

app.addEventListener('change', async (event) => {
  const input = event.target.closest('[data-gold10]');
  if (!input) return;
  const card = document.querySelector('#match-gold10');
  if (!card) return;
  const gold10 = {};
  card.querySelectorAll('[data-gold10]').forEach((el) => {
    const raw = String(el.value || '').trim();
    if (raw !== '' && Number.isFinite(Number(raw))) gold10[el.dataset.gold10] = Number(raw);
  });
  const key = current().key;
  input.classList.remove('is-bad');
  try {
    const response = await fetch(API_BASE + '/api/v3/match-meta/' + encodeURIComponent(key), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gold10 }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || '保存失败');
    }
    /* 就地重画这一格的评级和计数，不整页刷新：教练通常要连着填五个人。 */
    card.querySelectorAll('[data-gold10]').forEach((el) => {
      const lane = el.closest('.md-g10-row')?.querySelector('.md-g10-lane')?.textContent || '';
      const grade = el.value === '' ? null : gold10Grade(lane, Number(el.value));
      const chip = el.parentElement.querySelector('.md-grade');
      if (!chip) return;
      chip.className = `md-grade ${grade ? grade.level : 'is-blank'}`;
      chip.textContent = grade ? grade.label : '';
    });
    const count = card.querySelector('.md-g10-count b');
    if (count) count.textContent = String(Object.keys(gold10).length);
  } catch (error) {
    input.classList.add('is-bad');
    window.alert(error.message || '保存失败');
  }
});
app.addEventListener('change', (event) => features.change(event));

function showChartPoint(event) {
  const point = event.target.closest('[data-point]');
  if (!point) return;
  const wrap = point.closest('.chart-wrap');
  const tip = wrap.querySelector('.chart-tooltip');
  const box = wrap.getBoundingClientRect();
  const mark = point.getBoundingClientRect();
  tip.textContent = point.dataset.point;
  tip.hidden = false;
  tip.style.left = Math.max(4, Math.min(mark.left - box.left + 8, box.width - tip.offsetWidth - 4)) + 'px';
  tip.style.top = Math.max(0, mark.top - box.top - tip.offsetHeight - 8) + 'px';
}
function hideChartPoint(event) {
  const point = event.target.closest('[data-point]');
  if (point) point.closest('.chart-wrap').querySelector('.chart-tooltip').hidden = true;
}
app.addEventListener('mouseover', showChartPoint);
app.addEventListener('focusin', showChartPoint);
app.addEventListener('mouseout', hideChartPoint);
app.addEventListener('focusout', hideChartPoint);

window.addEventListener('hashchange', () => {
  view = {};
  document.querySelector('.mobile-menu').hidden = true;
  document.querySelector('.menu-button').setAttribute('aria-expanded', 'false');
  window.scrollTo(0,0);
  load();
});
document.querySelector('.skip').addEventListener('click', (event) => { event.preventDefault(); document.querySelector('#content').focus(); });
shell();
load();
