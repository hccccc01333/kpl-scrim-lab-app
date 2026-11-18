import { normalizedCamp, sampleNear, teamTotal, economyDirection, eventSide, laneRealisation } from './match-recap-metrics.js';
import { featureSections } from './feature-sections.js';
import { createWorkbenchUI, loadingSkeleton } from './workbench-ui.js';
import { createTour } from './tour.js';
import { initUpdateBanner } from './update-banner.js';
/* 页面模块不再静态 import（见 ensureModules）：过去一进工作台就要把所有页面模块
   解析一遍——31 个文件 / 1.9 MB，光解析就占掉首屏 300 毫秒左右，而其中绝大多数
   属于用户还没打开过的页面。 */

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const CLIENT_DOWNLOAD_URL = 'https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest';
const app = document.querySelector('#app');
const nav = [
  ['overview', '首页'], ['ingest', '采集'], ['matches', '对局'], ['teams', '战队'], ['players', '选手'],
  ['heroes', '英雄'], ['bp', 'BP'], ['setup', '赛训'], ['sources', '数据来源'],
];
const labels = Object.fromEntries(nav);
for (const pages of Object.values(featureSections)) for (const [key, label] of pages) labels[key] = label;
Object.assign(labels, { match: '对局复盘', player: '选手详情', playerdetail: '选手个人页', team: '战队详情', hero: '英雄详情', report: '分析报告', review: '缺失值审查', shots: '截图 OCR', videos: '录屏', replays: '回放', capture: '导入表格', economy: '经济转折', tempo: '节奏分析', opponents: '对手侦察', teamtraining: '战队训练', ownership: '对手归属', pending: '待确认', effect: '训练效果', session: '训练课', competition: '比赛详情', weekly: '训练周报' });
function sectionFor(name) {
  const detail = { match: 'matches', player: 'players', playerdetail: 'players', team: 'teams', hero: 'heroes', report: 'reports', review: 'ingest', shots: 'ingest', videos: 'ingest', replays: 'ingest', capture: 'ingest', economy: 'matches', tempo: 'matches', opponents: 'teams', ownership: 'setup', pending: 'setup', effect: 'setup', session: 'setup', competition: 'setup', weekly: 'setup' }[name] || name;
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
  edit: '<path d="M4.5 19.5h3.6L18.6 9a2.55 2.55 0 1 0-3.6-3.6L4.5 15.9z"/><path d="m14.2 6.2 3.6 3.6"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 4 4"/>',
  overview: '<path d="M3.5 10.5 12 3l8.5 7.5V20H14v-6h-4v6H3.5z"/>',
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
  camera: '<path d="M4 8h3l1.7-2.2h6.6L17 8h3v11H4z"/><circle cx="12" cy="13.2" r="3.4"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4m10 0h4M3 15h4m10 0h4"/>',
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
/* 分均经济评级（赛训组 2026-11-14 口径，单位金/分钟）：
   对抗路/发育路 = 10 分钟基准 ÷10：6800 及格 / 7000 良好 / 7400 优秀；
   中路 550/分钟 达标即可（5500/10 分钟）；
   打野按赛训组英雄标签分两类：坦野 6800 总量（=680/分钟）、其余（刺野/战野/
   待分类）按野核 800/分钟；游走不记录。
   英雄×分路类型来自 /api/metadata 的 heroTypes（resources/hero_tags.json）。 */
const GOLD_GRADES = {
  '对抗路': [[740, '优秀', 'good'], [700, '良好', 'ok'], [680, '及格', 'pass'], [0, '待提升', 'low']],
  '发育路': [[740, '优秀', 'good'], [700, '良好', 'ok'], [680, '及格', 'pass'], [0, '待提升', 'low']],
  '中路': [[550, '达标', 'pass'], [0, '待提升', 'low']],
};
const JUNGLE_TYPES = { tank: { key: '坦野', grades: [[680, '及格', 'pass'], [0, '待提升', 'low']] },
  core: { key: '野核', grades: [[800, '达标', 'pass'], [0, '待提升', 'low']] } };
/* 打野位的英雄类型：坦野 → 坦野口径；其余（含标签待确认）默认野核口径。
   本局实际职责不同（如蓝领让资源）时教练按实际判读，这里只给默认口径。 */
function jungleKindOf(hero) {
  const type = String((metadata.heroTypes || {})[hero || '']?.['打野'] || '');
  return JUNGLE_TYPES.tank.key === type ? 'tank' : 'core';
}
function jungleTypeLabel(hero) {
  return JUNGLE_TYPES[jungleKindOf(hero)].key;
}
function goldGrade(lane, gpm, hero) {
  const defs = lane === '打野'
    ? JUNGLE_TYPES[jungleKindOf(hero)].grades
    : GOLD_GRADES[lane];
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
let theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
let mdAnchorObserver = null;   // 复盘大屏区块条的滚动高亮（每次重渲染重建）
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
  /* 已下线的子页：旧链接回所在模块的主页，不落到首页。
     名单与状态、选手认领已并入选手档案（认领就在档案卡名字旁）；
     选手与位置已下线，独有信息由跨局分析、战队页与选手档案覆盖。 */
  const retired = { teamcompare: 'teams', h2h: 'teams', profiles: 'teams', records: 'featured', query: 'matches', teamstyle: 'teams', teamroster: 'teams',
    teambp: 'bp', bpcounter: 'bp',
    players: 'playerarchive', identity: 'playerarchive', compare: 'playerarchive',
    /* 2026-11-16：截图 / 录屏 / 回放 / 审查已并进采集页，旧链接仍落在采集页的对应页签
       （采集页自己按 hash 决定显示哪一块，#review/<id> 也照常打开那条审查明细）。 */
    shots: 'ingest', videos: 'ingest', replays: 'ingest', review: 'ingest' };
  /* BP 内容已整体重建为单页：#bp/team、#bp/counter 与旧 #teambp、#bpcounter
     一律回到 #bp，不再保留子页。 */
  const bpKey = name === 'bp' && ['team', 'counter'].includes(decoded) ? '' : decoded;
  return { name: retired[name] || (Object.hasOwn(labels, name) ? name : 'overview'), key: bpKey, anchor, tab };
}

function score(match) {
  const own = match.ownCamp || 'blue';
  const value = (camp) => match.scores?.[camp] ?? match.scores?.[mirror[camp]];
  const a = value(own);
  const b = value(opposite[own]);
  return has(a) && has(b) ? `${fmt(a)} <span>:</span> ${fmt(b)}` : '—';
}

/** 本队击杀占双方总击杀的比例；没有比分时返回 null。用于对局卡片的占比条。 */
function killShare(match) {
  const own = match.ownCamp || 'blue';
  const value = (camp) => match.scores?.[camp] ?? match.scores?.[mirror[camp]];
  const a = value(own);
  const b = value(opposite[own]);
  if (!has(a) || !has(b) || a + b <= 0) return null;
  return { own: a, enemy: b, pct: (a / (a + b)) * 100 };
}

function portrait(name, cls = '') {
  const url = metadata.icons?.[name];
  if (/^\/catalog\/icons\/hero-\d+\.png$/.test(url || '')) {
    return `<img class="portrait ${cls}" src="${esc(url)}" alt="${esc(name)}" loading="lazy">`;
  }
  return `<span class="portrait portrait-placeholder ${cls}" aria-label="${esc(name || '未知英雄')}">${esc((name || '?')[0])}</span>`;
}

const navHref = (key) => key === 'setup' ? '#plan' : key === 'players' ? '#playerarchive' : '#' + key;
let workbenchUI;
function shell() {
  const brand = `<a class="wordmark" href="#overview" aria-label="赛训数据首页"><span class="brand-symbol" aria-hidden="true"><i></i><i></i><i></i></span><span>赛训数据<small>TRAINING DATA</small></span></a>`;
  const navLink = ([key, label]) => `<a href="${navHref(key)}" data-nav="${key}"><span class="nav-icon">${icon(key)}</span><span>${label}</span></a>`;
  app.innerHTML = `<header class="masthead"><div class="masthead-inner">${brand}
    <nav class="main-nav" aria-label="主导航">${nav.map(navLink).join('')}</nav>
    <button type="button" class="head-button menu-button" data-action="menu" aria-label="打开导航" aria-expanded="false" aria-controls="ui-navigation">${icon('menu')}</button>
    <nav class="ui-breadcrumb" aria-label="当前位置"><a href="#overview" data-ui-section>工作台</a>${icon('chevron')}<span data-ui-page>赛训总览</span></nav>
    <button type="button" class="ui-search-trigger" data-ui-search aria-label="搜索页面与功能" aria-haspopup="dialog" aria-controls="ui-command">${icon('search')}<span>搜索页面与功能</span><kbd>Ctrl K</kbd></button>
    <div class="head-actions"><button type="button" class="head-button inbox-button" data-sx-inbox aria-label="待处理" title="待处理">${icon('inbox')}<span class="inbox-badge" data-inbox-badge hidden></span></button><a class="mode-button client-button" href="kpl-client://open" data-action="open-client" title="打开桌面客户端（需安装）" aria-label="打开桌面客户端">${icon('client')}<span>打开客户端</span></a><button class="head-button tour-button" data-action="tour" aria-label="使用教程" title="使用教程">${icon('help')}</button><button class="head-button theme-button" data-action="theme" aria-label="切换主题"></button>
      </div>
  </div></header>
  <dialog id="ui-navigation" class="mobile-menu" aria-label="页面导航" closedby="any"><div class="ui-drawer-head">${brand}<button type="button" class="head-button" data-ui-close aria-label="关闭导航" autofocus>${icon('close')}</button></div><nav aria-label="移动导航">${nav.map(navLink).join('')}</nav><div class="ui-drawer-tools" aria-label="常用操作"><button type="button" class="control" data-sx-inbox>${icon('inbox')}待处理</button><button type="button" class="control" data-action="tour">${icon('help')}使用教程</button><a class="control" href="kpl-client://open" data-action="open-client">${icon('client')}打开客户端</a></div></dialog>
  <dialog id="ui-command" class="ui-command" aria-label="搜索页面与功能" closedby="any"><div class="ui-command-head">${icon('search')}<input type="search" class="ui-command-input" role="combobox" aria-autocomplete="list" aria-controls="ui-command-results" aria-expanded="true" aria-label="搜索页面与功能" placeholder="搜索页面与功能…" autocomplete="off" autofocus><button type="button" class="head-button" data-ui-close aria-label="关闭搜索">${icon('close')}</button></div><div id="ui-command-results" class="ui-command-results" role="listbox" aria-label="搜索结果" data-command-results></div><div class="ui-command-foot"><span>↑ ↓ 选择 · Enter 打开 · Esc 关闭</span><span data-command-count></span></div></dialog>
  <div class="demo-banner" hidden><strong>演示模式</strong> 所有比赛、选手与分析均为虚构数据，仅供体验。<button data-action="demo">返回真实数据 →</button></div>
  <div class="secondary-wrap"><nav class="secondary-nav" aria-label="分类导航"></nav></div>
  <main id="content" tabindex="-1"></main>
  <footer class="footer"><span>赛训数据</span><span class="footer-actions"><button type="button" class="footer-update" data-action="check-update">检查更新</button></span><span>英雄资料来自王者荣耀官方，相关权利归原权利人。</span></footer>
  <dialog id="filters"></dialog>`;
  applyTheme();
  workbenchUI = createWorkbenchUI({ app, nav, labels, icon, esc, navHref, sectionFor, featureSections });
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

function openInbox() {  const data = inboxState;
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

function openBpOrderDialog() {
  const draft = data?.draft;
  if (!draft || !draft.picks) return;
  const seq = draft.gameSeq;
  if (!seq) { window.alert('这局没有营地编号，无法录入顺序。'); return; }
  let dialog = document.querySelector('#bp-order-dialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'bp-order-dialog';
    dialog.className = 'sx-dialog bp-order-dialog';
    document.body.append(dialog);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  }
  const sideLabel = { left: '本队 · 蓝方', right: '对手 · 红方' };
  /* 回填已保存的模式与一手方：否则第二次打开会永远显示「训练赛」，
     用户会以为切换模式没有覆盖。 */
  const savedMode = draft.bpOrderMode === 'kpl' ? 'kpl' : 'scrim';
  const savedFirst = draft.firstPick === 'right' ? 'right' : 'left';
  const sideBlock = (side) => {
    const picks = (draft.picks?.[side] || []).map((row) => row?.name).filter(Boolean);
    const bans = (draft.bans?.[side] || []).map((row) => row?.name).filter(Boolean);
    const opts = (names) => names.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
    const pickRows = Array.from({ length: 5 }, (_, i) => `<label>P${i + 1}<select data-order-side="${side}" data-order-kind="picks" data-order-index="${i}">${opts(picks)}</select></label>`).join('');
    const banRows = Array.from({ length: bans.length }, (_, i) => `<label>B${i + 1}<select data-order-side="${side}" data-order-kind="bans" data-order-index="${i}">${opts(bans)}</select></label>`).join('');
    return `<section class="bp-order-side"><h3>${sideLabel[side]}</h3>
      <div class="bp-order-group"><b>选用 P1–P5</b>${pickRows}</div>
      <div class="bp-order-group"><b>禁用 B1–B${bans.length}</b>${banRows}</div></section>`;
  };
  dialog.innerHTML = `<div class="sx-dialog-head"><div><span class="sx-eyebrow">BP ORDER</span><h2>手工录入 BP 顺序</h2></div><button type="button" class="sx-dialog-x" data-bp-order-close aria-label="关闭">×</button></div>
    <p class="sx-dialog-note">训练赛 / KPL 都是 20 手（每侧 5 Ban + 5 Pick）；按真实顺序排，禁用允许跨侧重复（排位同时禁用）。选用必须与营地终局名单一致。保存后本页显示 P/B 楼层。</p>
    <div class="bp-order-mode"><span>模式</span><label><input type="radio" name="bp-order-mode" value="scrim" ${savedMode === 'scrim' ? 'checked' : ''}> 训练赛</label><label><input type="radio" name="bp-order-mode" value="kpl" ${savedMode === 'kpl' ? 'checked' : ''}> KPL</label><label>一手方<select data-order-first><option value="left" ${savedFirst === 'left' ? 'selected' : ''}>蓝方</option><option value="right" ${savedFirst === 'right' ? 'selected' : ''}>红方</option></select></label></div>
    <div class="bp-order-grid">${sideBlock('left')}${sideBlock('right')}</div>
    <div class="bp-order-foot"><p class="form-status" data-order-status></p><button type="button" class="control" data-bp-order-cancel>取消</button><button type="button" class="primary" data-bp-order-save>保存顺序</button></div>`;
  dialog.querySelectorAll('select[data-order-side]').forEach((select) => {
    const side = select.dataset.orderSide, kind = select.dataset.orderKind;
    const index = Number(select.dataset.orderIndex);
    const list = kind === 'picks' ? (draft.picks?.[side] || []) : (draft.bans?.[side] || []);
    const name = list[index]?.name;
    if (name) select.value = name;
  });
  dialog.onclick = (event) => {
    if (event.target === dialog) { dialog.close(); return; }
    if (event.target.closest('[data-bp-order-close]') || event.target.closest('[data-bp-order-cancel]')) {
      dialog.close();
      return;
    }
    const save = event.target.closest('[data-bp-order-save]');
    if (save) saveBpOrder(dialog, save);
  };
  if (!dialog.open) dialog.showModal();
}

function collectBpOrder(dialog) {
  const payload = {
    mode: dialog.querySelector('input[name="bp-order-mode"]:checked')?.value || 'scrim',
    bans: { left: [], right: [] }, picks: { left: [], right: [] },
    firstPick: dialog.querySelector('[data-order-first]')?.value || 'left',
  };
  dialog.querySelectorAll('select[data-order-side]').forEach((select) => {
    payload[select.dataset.orderKind][select.dataset.orderSide][Number(select.dataset.orderIndex)] = select.value;
  });
  return payload;
}

function saveBpOrder(dialog, button) {
  const status = dialog.querySelector('[data-order-status]');
  const seq = data?.draft?.gameSeq;
  if (!seq) {
    if (status) status.textContent = '这局没有营地编号，无法保存。';
    return;
  }
  const payload = collectBpOrder(dialog);
  const allPicks = payload.picks.left.concat(payload.picks.right);
  if (new Set(allPicks).size !== allPicks.length) {
    if (status) status.textContent = '双方选用不能重复。';
    return;
  }
  button.disabled = true;
  if (status) status.textContent = '正在保存…';
  fetch(`${API_BASE}/api/v3/camp-bp-order/${encodeURIComponent(seq)}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  }).then(async (response) => {
    if (!response.ok) {
      let detail = '保存失败';
      try { detail = (await response.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    dialog.close();
    await load(true);
  }).catch((error) => {
    if (status) status.textContent = error.message || '保存失败';
    button.disabled = false;
  });
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

function teamSkeleton() {
  const lines = (n, cls = '') => Array.from({length: n}, (_, i) => `<div class="tp-skel-line${i === 0 && cls ? ' ' + cls : ''}"></div>`).join('');
  return `<div class="page feature-page tp-page tp-skeleton" aria-busy="true" aria-label="正在读取战队数据">
    <div class="tp-skel-card"><div class="tp-skel-head"><span class="tp-skel-crest"></span><div class="tp-skel-lines"><div class="tp-skel-line is-title"></div><div class="tp-skel-line is-mid"></div><div class="tp-skel-line is-short"></div></div></div></div>
    <div class="tp-skel-card">${lines(3, 'is-mid')}</div>
    <div class="tp-skel-grid"><div class="tp-skel-card">${lines(5)}</div><div class="tp-skel-card">${lines(5)}</div></div>
  </div>`;
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
/* 同一天的局号：只给「有日期、且当天不止一局」的对局编号，按时间正序数。
   采集包常常没有日期，缺日期的局不编号，免得后面全变成「第 208 局」。 */
function dayNumbers(matches) {
  const groups = new Map();
  for (const match of matches || []) {
    const day = String(match.date || '');
    if (!day) continue;
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(match);
  }
  const numbers = new Map();
  for (const list of groups.values()) {
    if (list.length < 2) continue;
    [...list].reverse().forEach((match, index) => numbers.set(match.key, index + 1));
  }
  return numbers;
}
function matchRows(rows, dayNo = new Map(), grouped = false) {
  if (!rows.length) return `<div class="empty">当前范围暂无对局。</div>`;
  /* 一行摆双方十人：左组本队、右组对面，按分路同序排列，中间 VS 分开两组。 */
  const lineup = (m) => {
    const pairs = (m.lineup || []).filter((p) => p.own || p.enemy).slice(0, 5);
    if (!pairs.length) return `<div class="small-lineup">${(m.heroes || []).slice(0, 5).map((hero) => portrait(hero)).join('')}</div>`;
    const cell = (hero, foe, lane) => hero
      ? `<span class="ml-cell${foe ? ' is-foe' : ''}" title="${esc([lane, (foe ? '对面 ' : '本队 ') + hero].filter(Boolean).join(' · '))}">${portrait(hero)}</span>`
      : '<span class="ml-cell is-empty"></span>';
    const faces = (list, foe) => `<span class="ml-faces">${list.map((p) => cell(foe ? p.enemy : p.own, foe, p.lane)).join('')}</span>`;
    const hasFoe = pairs.some((p) => p.enemy);
    return `<div class="match-lineup" title="左组本队 · 右组对面，同一顺序即同分路对位">
      <span class="ml-side is-own"><small>本队</small>${faces(pairs, false)}</span>
      ${hasFoe ? `<span class="ml-vs">VS</span><span class="ml-side is-foe"><small>对面</small>${faces(pairs, true)}</span>` : ''}
    </div>`;
  };
  /* 第二行小字：模式 + 这一把的开局时间（营地 startTime），没有时间的旧局退回当天第几局。 */
  const when = (m) => {
    const start = String(m.startTime || '').trim();
    if (start) return start.slice(-5);
    const no = dayNo.get(m.key);
    return no ? `第 ${no} 局` : '';
  };
  const item = (m) => {
    const label = when(m);
    const share = killShare(m);
    const margin = share
      ? `<span class="match-margin ${m.result === 'win' ? 'is-win' : m.result === 'loss' ? 'is-loss' : ''}" title="击杀占比 ${Math.round(share.pct)}% · ${fmt(share.own)} : ${fmt(share.enemy)}"><i style="width:${share.pct.toFixed(1)}%"></i><b aria-hidden="true"></b></span>`
      : '<span class="match-margin is-empty" aria-hidden="true"></span>';
    return `<div class="match-row-wrap">
    <a class="match-row" href="${esc(route('match', m.key))}">
    <div class="match-date"><b>${esc((m.date || '日期未知').slice(5))}</b><small>${esc((m.date || '').slice(0,4))}</small></div>
    <div class="match-opponent"><small>${m.isSeed ? '验证对局' : esc(m.mode || '对局记录')}${label ? ` · ${esc(label)}` : ''}</small><span class="match-opponent-line"><b${m.opponent ? '' : ' title="还没填对手队名，点右侧铅笔补上"'}>${esc(m.opponent ? '对阵 ' + m.opponent : '对手未标注')}</b></span></div>
    <span class="result ${esc(m.result)}">${esc(resultName[m.result] || '未知')}</span>
    <strong class="row-score" title="本队 : 对面">${score(m)}</strong><span class="match-duration" title="本局时长">${time(m.duration)}</span>
    ${margin}
    ${lineup(m)}
    <span class="row-arrow">${icon('arrow')}</span></a>
    <button type="button" class="match-edit match-rename-control" data-match-edit="${esc(m.key)}" data-opponent="${esc(m.opponent || '')}" data-team-id="${esc(m.opponentTeamId || '')}" title="${m.opponentTeamId ? '给这支对手战队改名（全站同步）' : '修改对手队名'}" aria-label="修改${esc(m.opponent || '未标注对手')}的队名">${icon('edit')}</button>
  </div>`;
  };
  /* 一屏只铺 24 行：54 场的档案页会拉到 4000px 高，而教练真正要找的
     往往是最近几局。其余收进折叠区，搜索仍走同一套渲染。 */
  const head = rows.slice(0, MATCH_ROWS_OPEN), rest = rows.slice(MATCH_ROWS_OPEN);
  const renderRows = (list) => {
    if (!grouped) return `<div class="match-list">${list.map(item).join('')}</div>`;
    const groups = new Map();
    for (const match of list) {
      const day = match.date || '日期未标注';
      if (!groups.has(day)) groups.set(day, []);
      groups.get(day).push(match);
    }
    return [...groups].map(([day, games]) => {
      const wins = games.filter((match) => match.result === 'win').length;
      const losses = games.filter((match) => match.result === 'loss').length;
      const total = Math.max(1, games.length);
      return `<section class="fixture-day" aria-label="${esc(day)}的对局">
      <div class="fixture-day-head"><h3><time${/^\d{4}-\d{2}-\d{2}$/.test(day) ? ` datetime="${esc(day)}"` : ''}>${esc(day)}</time></h3><span>${games.length} 局</span><span class="fixture-day-record">${wins} 胜 · ${losses} 负</span>
        <span class="day-split" aria-hidden="true"><i class="is-win" style="width:${wins / total * 100}%"></i><i class="is-loss" style="width:${losses / total * 100}%"></i></span></div>
      <div class="match-list">${games.map(item).join('')}</div></section>`;
    }).join('');
  };
  return `${renderRows(head)}
    ${rest.length ? `<details class="match-more"><summary>还有 ${rest.length} 场，展开</summary>
      ${renderRows(rest)}</details>` : ''}`;
}

/** 编辑对手队名：归到战队的局走战队分析统一改名，其余写 match_meta 覆盖层。 */
function opponentDialog(key, current, teamId) {
  const dialog = dialogFor();
  const linked = Boolean(teamId);
  dialog.innerHTML = `<form id="opponent-form" data-key="${esc(key)}" data-team-id="${esc(teamId || '')}"><div class="dialog-head"><div><h2>${linked ? '给对手战队改名' : '编辑对手队名'}</h2><p>${linked ? '队名由「战队分析」统一管理：改名后这支对手的全部对局同步更新（对局档案、系列赛编组、跨局分析都跟着变）。' : '只影响本机显示与统计，不改原始数据包；留空表示「对手未标注」。'}</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><label>对手战队/队名<input name="opponent" maxlength="50" value="${esc(current)}" placeholder="例如：漂流网咖"${linked ? ' required' : ''}></label>
    <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">保存</button></div></form>`;
  dialog.showModal();
  dialog.querySelector('input[name="opponent"]')?.focus();
}

/* 当前筛选 + 搜索范围内、对手未标注的局：批量赋名只动这一批。 */
function unlabelledTargets() {
  const mf = matchFilters();
  const keyword = String(view.search || '').toLowerCase();
  return (data.matches || [])
    .filter((m) => matchPasses(m, mf))
    .filter((m) => !keyword || [m.opponent, m.title, m.date, ...(m.heroes || [])].some((x) => String(x || '').toLowerCase().includes(keyword)))
    .filter((m) => !String(m.opponent || '').trim());
}

/* 批量补对手队名：训练赛通常一天一个对手，先按日期筛好，再一口气赋名。 */
function bulkOpponentDialog() {
  const targets = unlabelledTargets();
  const dialog = dialogFor();
  if (!targets.length) {
    dialog.innerHTML = `<form id="bulk-opponent-form"><div class="dialog-head"><div><h2>批量补对手队名</h2><p>当前范围里没有「对手未标注」的对局。</p></div>
      <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
      <div class="dialog-actions"><button type="button" class="control" data-action="close">好</button></div></form>`;
    dialog.showModal();
    return;
  }
  const days = new Map();
  for (const match of targets) {
    const day = String(match.date || '无日期');
    days.set(day, (days.get(day) || 0) + 1);
  }
  const dayList = [...days].sort((a, b) => String(b[0]).localeCompare(String(a[0])))
    .map(([day, count]) => `<li><span>${esc(day)}</span><em>${fmt(count)} 场</em></li>`).join('');
  dialog.innerHTML = `<form id="bulk-opponent-form"><div class="dialog-head"><div><h2>批量补对手队名</h2><p>把当前范围里 ${fmt(targets.length)} 场未标注的局一次设为同一个队名；只写本机覆盖层，原始数据不动。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><label>对手战队/队名<input name="opponent" maxlength="50" placeholder="例如：漂流网咖" required></label>
    <div class="bulk-days"><span>将修改这些对局</span><ul>${dayList}</ul></div>
    <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">保存到 ${fmt(targets.length)} 场</button></div></form>`;
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

/* 首页（#overview）由 period-brief.js 自取数渲染：周期切换、一句战况、动态指标、
   变化卡、下一场约训与数据覆盖都在模块里。这里只保留两条外壳能力：路由挂载点，
   以及「空库」时的入库弹窗（首页不整页换向导）。
   2026-11-13 反馈：日期范围一窄，首页整页变成「先把第一局拿进来」，又没有任何出口，
   点「首页」因为 hash 没变也不会重渲染 —— 看起来就像进了死胡同。
   现在首页永远渲染简报，空库只用弹窗说明；弹窗可关闭，关掉后仍是首页。 */
function scopeKey() {
  return [filters.from, filters.to, filters.validation ? 1 : 0, filters.source.join(',')].join('|');
}
let emptyDialogDismissed = '';

function showNoDataDialog() {
  const dialog = dialogFor();
  if (!dialog || dialog.open || emptyDialogDismissed === scopeKey()) return;
  dialog.classList.add('is-wide');
  dialog.innerHTML = `<div class="dialog-head"><div><h2>还没有对局数据</h2>
    <p>这个工作台不自带比赛数据，先拿一局进来；弹窗关掉后仍是首页，随时可以再打开。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body welcome-in-dialog">${welcomePage()}</div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">稍后</button></div>`;
  dialog.showModal();
  hydrateWelcome();
}

/* 专业研究明细表：恢复真实渲染，供 tempo/sources/research/depth/features 等模块展示明细。
   默认折叠由调用方用 <details> 控制；本函数只负责产出表格，不返回空串。 */
function table(head, rows, cls = '') {
  const h = Array.isArray(head) ? head : [head];
  const r = Array.isArray(rows) ? rows : [];
  return `<div class="dx-table-wrap"><table class="dx-table${cls ? ' ' + cls : ''}"><thead><tr>${h.map((cell) => `<th>${esc(cell)}</th>`).join('')}</tr></thead><tbody>${r.map((cells) => {
    const arr = Array.isArray(cells) ? cells : [cells];
    return `<tr>${arr.map((cell) => `<td>${cell}</td>`).join('')}</tr>`;
  }).join('')}</tbody></table></div>`;
}

/* ---------- 对局档案筛选：对手 / 英雄组合 / 日期 ----------
   选 2 个以上英雄就是「这几位同时出场」，对应教练看阵容组合的习惯；
   筛选只在前端已有数据上做，不重新请求。 */
const MF_NONE = '__none__';
/* 筛选条件的记忆层级：URL hash（分享/后退/刷新直达）> localStorage（切页回来还在）。
   「清除筛选」两层一起清，避免下次进来又冒出旧条件。 */
const MF_STORAGE = 'training-matches-filters';

function matchFilters() {
  if (!view.matchFilters) view.matchFilters = { opponents: [], heroes: [], days: [], from: '', to: '' };
  return view.matchFilters;
}

function matchFiltersQuery(mf, search) {
  const params = new URLSearchParams();
  if (search) params.set('q', search);
  if (mf.opponents.length) params.set('opp', mf.opponents.join(','));
  if (mf.heroes.length) params.set('hero', mf.heroes.join(','));
  if (mf.days.length) params.set('day', mf.days.join(','));
  if (mf.from) params.set('from', mf.from);
  if (mf.to) params.set('to', mf.to);
  return params.toString();
}

function readMatchFiltersQuery() {
  const query = location.hash.split('?')[1] || '';
  if (!query) return null;
  const params = new URLSearchParams(query);
  const list = (name) => String(params.get(name) || '').split(',').map((x) => x.trim()).filter(Boolean);
  const mf = { opponents: list('opp'), heroes: list('hero'), days: list('day'), from: String(params.get('from') || ''), to: String(params.get('to') || '') };
  const search = String(params.get('q') || '');
  if (!matchFiltersActive(mf) && !search) return null;
  return { mf, search };
}

/* 筛选变化后把条件写回 URL（不触发 hashchange、不重载页面），并存一份本机记忆。 */
function syncMatchHash() {
  const mf = matchFilters();
  const query = matchFiltersQuery(mf, view.search || '');
  try {
    if (matchFiltersActive(mf)) localStorage.setItem(MF_STORAGE, JSON.stringify(mf));
    else localStorage.removeItem(MF_STORAGE);
  } catch {}
  try {
    const path = location.hash.slice(1).split('?')[0];
    const next = `#${path}${query ? `?${query}` : ''}`;
    if (location.hash !== next) history.replaceState(null, '', next);
  } catch {}
}

/* 进对局档案页时恢复条件：URL 里有就用 URL（分享链接），否则用上次本机的筛选。 */
function restoreMatchFilters() {
  if (view.mfRestored) return;
  view.mfRestored = true;
  const fromUrl = readMatchFiltersQuery();
  if (fromUrl) {
    view.matchFilters = fromUrl.mf;
    view.search = fromUrl.search;
    return;
  }
  try {
    const saved = JSON.parse(localStorage.getItem(MF_STORAGE) || 'null');
    if (saved && matchFiltersActive(saved)) {
      view.matchFilters = { opponents: [], heroes: [], days: [], from: '', to: '', ...saved };
      syncMatchHash();
    }
  } catch {}
}

function matchFiltersActive(mf) {
  return Boolean(mf.opponents.length || mf.heroes.length || mf.days.length || mf.from || mf.to);
}

function matchPasses(match, mf) {
  const heroes = match.heroes || [];
  if (mf.opponents.length) {
    const name = String(match.opponent || '').trim() || MF_NONE;
    if (!mf.opponents.includes(name)) return false;
  }
  if (mf.heroes.length && !mf.heroes.every((hero) => heroes.includes(hero))) return false;
  if (mf.days.length) {
    if (!mf.days.includes(String(match.date || ''))) return false;
  } else if (mf.from || mf.to) {
    const day = String(match.date || '');
    if (!day) return false;
    if (mf.from && day < mf.from) return false;
    if (mf.to && day > mf.to) return false;
  }
  return true;
}

function matchFacets(matches) {
  const opponents = new Map(), heroes = new Map(), days = new Map();
  for (const match of matches || []) {
    const name = String(match.opponent || '').trim() || MF_NONE;
    opponents.set(name, (opponents.get(name) || 0) + 1);
    for (const hero of match.heroes || []) heroes.set(hero, (heroes.get(hero) || 0) + 1);
    const day = String(match.date || '');
    if (day) days.set(day, (days.get(day) || 0) + 1);
  }
  return {
    opponents: [...opponents].sort((a, b) => b[1] - a[1]),
    heroes: [...heroes].sort((a, b) => b[1] - a[1]),
    days: [...days].sort((a, b) => b[0].localeCompare(a[0])),
  };
}

function matchFilterBar(total, shown) {
  const mf = matchFilters();
  const active = matchFiltersActive(mf) || Boolean(view.search);
  const pill = (kind, label, count) => `<button type="button" class="mf-pill${count ? ' is-on' : ''}" data-mf-open="${kind}" aria-haspopup="dialog" aria-expanded="false">${label}${count ? `<b>${count}</b>` : ''}${icon('chevron')}</button>`;
  const chip = (kind, value, label, title) => `<span class="mf-chip" title="${esc(title || label)}"><span>${esc(label)}</span><button type="button" data-mf-remove="${kind}" data-mf-value="${esc(value)}" aria-label="移除 ${esc(label)}">×</button></span>`;
  const chips = [
    ...mf.opponents.map((name) => (name === MF_NONE
      ? chip('opponents', name, '对手未标注')
      : chip('opponents', name, name))),
    ...(mf.heroes.length ? [chip('heroes', '*', `${mf.heroes.length} 人组合 · ${mf.heroes.join(' + ')}`)] : []),
    ...mf.days.map((day) => chip('days', day, String(day).slice(5))),
    ...(mf.from || mf.to ? [chip('range', '*', [mf.from, mf.to].filter(Boolean).join(' ~ '))] : []),
  ].join('');
  return `<div class="mfilter" data-filter-bar>
    <div class="mf-pills">${pill('opponent', '对手', mf.opponents.length)}${pill('hero', '英雄', mf.heroes.length)}${pill('day', '日期', mf.days.length)}</div>
    ${chips ? `<div class="mf-chips" data-mf-chips>${chips}</div>` : '<div class="mf-chips" data-mf-chips></div>'}
    <span class="mf-spacer"></span>
    <span class="mf-total">${active ? `${fmt(shown)} / 共 ${fmt(total)} 场` : `共 ${fmt(total)} 场`}</span>
    ${active ? '<button type="button" class="mf-clear" data-mf-clear>清除筛选</button>' : ''}
  </div>`;
}

function matchFilterPanel(kind) {
  const mf = matchFilters();
  const facets = matchFacets(data.matches || []);
  if (kind === 'opponent') {
    const rows = facets.opponents.map(([name, count]) => `<label class="mf-opt">
      <input type="checkbox" data-mf-opt="opponents" data-mf-value="${esc(name)}" ${mf.opponents.includes(name) ? 'checked' : ''}>
      <span class="mf-opt-main">${name === MF_NONE ? '对手未标注' : esc(name)}</span>
      <em>${fmt(count)} 局</em></label>`).join('');
    const noneCount = facets.opponents.find(([name]) => name === MF_NONE)?.[1] || 0;
    return `<div class="mf-pop-head"><input class="mf-q" data-mf-q="opponent" placeholder="搜索对手" aria-label="搜索对手"></div>
      <div class="mf-pop-list" data-mf-list><div class="mf-opt-empty">还没有填过对手队名，先在行尾铅笔里补。</div>${rows}</div>
      <div class="mf-pop-foot"><span>可多选，命中任一对手</span><span class="mf-foot-btns">${noneCount ? `<button type="button" class="mf-bulk" data-mf-bulk>批量补队名 (${fmt(noneCount)})</button>` : ''}<button type="button" data-mf-reset="opponents">清空</button></span></div>`;
  }
  if (kind === 'hero') {
    const rows = facets.heroes.map(([hero, count]) => {
      const order = mf.heroes.indexOf(hero);
      return `<label class="mf-hero${order >= 0 ? ' is-on' : ''}">
        <input type="checkbox" data-mf-opt="heroes" data-mf-value="${esc(hero)}" ${order >= 0 ? 'checked' : ''}>
        ${portrait(hero)}
        <span>${esc(hero)}</span>
        <em>${fmt(count)}</em>
        ${order >= 0 ? `<i class="mf-order">${order + 1}</i>` : ''}
      </label>`;
    }).join('');
    return `<div class="mf-pop-head"><input class="mf-q" data-mf-q="hero" placeholder="搜索英雄" aria-label="搜索英雄"></div>
      <div class="mf-pop-tip">选 2 个以上，只看这些英雄<span>同时出场</span>的局（2 人组合 / 3 人组合…）</div>
      <div class="mf-pop-grid" data-mf-list>${rows}</div>
      <div class="mf-pop-foot"><span>${mf.heroes.length ? `已选 ${mf.heroes.length} 个 · 同一局同时出场` : '按出场次数排序'}</span><button type="button" data-mf-reset="heroes">清空</button></div>`;
  }
  const dayRows = facets.days.map(([day, count]) => `<label class="mf-opt">
    <input type="checkbox" data-mf-opt="days" data-mf-value="${esc(day)}" ${mf.days.includes(day) ? 'checked' : ''}>
    <span class="mf-opt-main">${esc(day)}</span><em>${fmt(count)} 局</em></label>`).join('');
  return `<div class="mf-pop-head"><input class="mf-q" data-mf-q="day" placeholder="搜索日期，如 11-02" aria-label="搜索日期"></div>
    <div class="mf-pop-list" data-mf-list>${dayRows || '<div class="mf-opt-empty">这些对局还没有日期。</div>'}</div>
    <div class="mf-pop-range">
      <span>自定义</span>
      <input type="date" data-mf-cal="from" value="${esc(mf.from || '')}" aria-label="开始日期">
      <i>—</i>
      <input type="date" data-mf-cal="to" value="${esc(mf.to || '')}" aria-label="结束日期">
    </div>
    <div class="mf-pop-foot"><span>勾选整天，或填起止日期</span><button type="button" data-mf-reset="days">清空</button></div>`;
}

/* 筛选变化后原地刷新结果、计数与徽标，不动搜索框焦点。 */
function refreshMatchResults() {
  const route = current();
  if (route.name !== 'matches') return;
  const temp = document.createElement('div');
  temp.innerHTML = renderers.matches(data, route.key);
  const results = document.querySelector('[data-results]');
  if (results) results.innerHTML = temp.querySelector('[data-results]')?.innerHTML || '';
  const count = document.querySelector('[data-result-count]');
  if (count) count.innerHTML = temp.querySelector('[data-result-count]')?.innerHTML || '';
  const summary = document.querySelector('.match-overview');
  if (summary) summary.innerHTML = temp.querySelector('.match-overview')?.innerHTML || '';
  const bar = document.querySelector('[data-filter-bar]');
  if (bar) bar.outerHTML = temp.querySelector('[data-filter-bar]')?.outerHTML || '';
  syncMatchHash();
  syncMatchFilterPills();
  if (matchKbIndex >= 0) paintMatchKb(matchKbRows());
}

function syncMatchFilterPills() {
  document.querySelectorAll('[data-mf-open]').forEach((pill) => {
    const open = Boolean(document.querySelector(`.mf-pop[data-mf-pop="${pill.dataset.mfOpen}"]`));
    pill.setAttribute('aria-expanded', open ? 'true' : 'false');
    pill.classList.toggle('is-open', open);
  });
}

function closeMatchFilter() {
  document.querySelectorAll('.mf-pop').forEach((pop) => pop.remove());
  document.querySelectorAll('[data-mf-open].is-open').forEach((pill) => pill.classList.remove('is-open'));
  syncMatchFilterPills();
}

function openMatchFilter(kind) {
  const existing = document.querySelector(`.mf-pop[data-mf-pop="${kind}"]`);
  closeMatchFilter();
  if (existing) return;
  const pill = document.querySelector(`[data-mf-open="${kind}"]`);
  if (!pill) return;
  const pop = document.createElement('div');
  pop.className = 'mf-pop';
  pop.dataset.mfPop = kind;
  pop.setAttribute('role', 'dialog');
  pop.innerHTML = matchFilterPanel(kind);
  document.body.appendChild(pop);
  const width = kind === 'hero' ? 384 : 320;
  const rect = pill.getBoundingClientRect();
  pop.style.width = `${width}px`;
  pop.style.left = `${Math.max(16, Math.min(window.innerWidth - width - 16, rect.left))}px`;
  /* 优先在按钮下方展开，按剩余高度收面板；下方实在放不下才翻到上方。 */
  const spaceBelow = window.innerHeight - rect.bottom - 24;
  const spaceAbove = rect.top - 16;
  let top = rect.bottom + 8;
  if (spaceBelow < 300 && spaceAbove > spaceBelow) {
    pop.style.maxHeight = `${Math.min(440, Math.max(240, spaceAbove - 8))}px`;
    top = Math.max(12, rect.top - pop.offsetHeight - 8);
  } else {
    pop.style.maxHeight = `${Math.min(440, Math.max(240, spaceBelow))}px`;
  }
  pop.style.top = `${Math.round(top)}px`;
  pill.classList.add('is-open');
  syncMatchFilterPills();
  if (kind !== 'day') pop.querySelector('.mf-q')?.focus();
}

function toggleMatchFilter(kind) {
  openMatchFilter(kind);
}

function updateMatchFilter(kind, value, checked) {
  const mf = matchFilters();
  if (kind === 'days') {
    /* 选了整天就清掉自定义区间，两个入口不能互相打架。 */
    mf.days = checked ? [...new Set([...mf.days, value])] : mf.days.filter((x) => x !== value);
    if (checked) { mf.from = ''; mf.to = ''; }
  } else {
    const list = mf[kind];
    mf[kind] = checked ? [...new Set([...list, value])] : list.filter((x) => x !== value);
  }
  refreshMatchResults();
  const pop = document.querySelector(`.mf-pop[data-mf-pop="${kind === 'days' ? 'day' : kind === 'heroes' ? 'hero' : 'opponent'}"]`);
  if (pop) {
    if (kind === 'opponents') {
      pop.querySelectorAll('[data-mf-opt]').forEach((input) => { input.checked = mf.opponents.includes(input.dataset.mfValue); });
    } else if (kind === 'days') {
      pop.querySelectorAll('[data-mf-opt]').forEach((input) => { input.checked = mf.days.includes(input.dataset.mfValue); });
    } else {
      /* 英雄项要重画序号，整块换掉最省事。 */
      const list = pop.querySelector('[data-mf-list]');
      if (list) {
        const temp = document.createElement('div');
        temp.innerHTML = matchFilterPanel('hero');
        list.innerHTML = temp.querySelector('[data-mf-list]')?.innerHTML || '';
        pop.querySelector('.mf-pop-foot span').textContent = mf.heroes.length ? `已选 ${mf.heroes.length} 个 · 同一局同时出场` : '按出场次数排序';
      }
    }
  }
}

function clearMatchFilter(kind) {
  const mf = matchFilters();
  if (kind === 'range') { mf.from = ''; mf.to = ''; }
  else if (kind) mf[kind] = [];
  else view.matchFilters = { opponents: [], heroes: [], days: [], from: '', to: '' };
  closeMatchFilter();
  refreshMatchResults();
}


function matchesPage(value, key) {
  restoreMatchFilters();
  const hero = key.startsWith('hero=') ? key.slice(5) : '';
  const mf = matchFilters();
  const rows = value.matches
    .filter((m) => !hero || (m.heroes || []).includes(hero))
    .filter((m) => matchPasses(m, mf))
    .filter((m) => !view.search || [m.opponent, m.title, m.date, ...(m.heroes || [])].some((x) => String(x || '').toLowerCase().includes(view.search.toLowerCase())));
  const won=rows.filter(m=>m.result==='win').length,lost=rows.filter(m=>m.result==='loss').length,decided=won+lost;
  const rate = decided ? (won / decided) * 100 : 0;
  const dayCount = new Set(rows.map((m) => m.date).filter(Boolean)).size;
  const perDay = new Map();
  for (const m of rows) if (m.date) perDay.set(m.date, (perDay.get(m.date) || 0) + 1);
  const dayBars = [...perDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-8);
  const maxDay = Math.max(1, ...dayBars.map(([, count]) => count));
  const barsHtml = dayBars.map(([day, count]) => `<i style="height:${Math.max(10, count / maxDay * 100).toFixed(0)}%" title="${esc(day)} · ${fmt(count)} 局"></i>`).join('');
  const recent = rows.slice(0, 10);
  const recentHtml = recent.map((m) => {
    const label = m.result === 'win' ? '胜' : m.result === 'loss' ? '负' : '—';
    const tip = [m.date, m.opponent ? `对阵 ${m.opponent}` : '对手未标注',
      score(m).replace(/<[^>]+>/g, ' '), m.mode].filter(Boolean).join(' · ');
    return `<i class="is-${esc(m.result || 'unknown')}" title="${esc(tip)}">${label}</i>`;
  }).join('');
  const summary=`<div class="match-overview">
    <div class="mo-cell mo-games">
      <span class="mo-label">当前对局</span>
      <strong class="mo-value">${fmt(rows.length)} <small>场</small></strong>
      <p>${fmt(dayCount)} 个训练日 · 当前筛选</p>
      ${barsHtml ? `<span class="mo-bars" aria-hidden="true">${barsHtml}</span>` : ''}
    </div>
    <div class="mo-cell mo-record">
      <span class="mo-label">本队战绩</span>
      <strong class="mo-value"><b class="is-win">${fmt(won)}</b> 胜 <b class="is-loss">${fmt(lost)}</b> 负</strong>
      <div class="mo-split" aria-hidden="true"><i class="is-win" style="width:${decided ? won / decided * 100 : 0}%"></i><i class="is-loss" style="width:${decided ? lost / decided * 100 : 0}%"></i></div>
      <p>${fmt(decided)} 场有胜负${rows.length - decided ? ` · ${fmt(rows.length - decided)} 场未计入` : ''}</p>
    </div>
    <div class="mo-cell mo-rate">
      <div class="mo-donut" style="--rate:${rate.toFixed(1)}"><span><b>${decided ? pct(rate) : '—'}</b><small>胜率</small></span></div>
      <p>${fmt(decided)} 场有胜负</p>
    </div>
    <div class="mo-cell mo-form">
      <span class="mo-label">近 ${recent.length || 0} 场</span>
      <div class="mo-form-row">${recentHtml || '<em>暂无对局</em>'}</div>
      <p>${recent[0] ? `最近 ${esc(recent[0].date || '')}${recent[0].opponent ? ` · 对阵 ${esc(recent[0].opponent)}` : ''}` : '当前范围暂无对局'}</p>
    </div>
  </div>`;
  return `<div class="page fixture-page">${pageIntro('对局档案', '按训练日归档。查看阵容与战绩，从任意一局进入复盘。')}
    ${summary}<section class="section fixture-ledger" aria-label="${hero ? esc(hero) + '的对局' : '对局记录'}">
    <div class="mf-toolbar">
      <label class="search mf-search">${icon('search')}<input type="search" name="search" value="${esc(view.search || '')}" placeholder="搜索对手、英雄或日期" aria-label="搜索对局"></label>
      ${matchFilterBar(value.matches.length, rows.length)}
    </div>
    <div class="fixture-column-head" aria-hidden="true"><span>对手 / 场次</span><span>胜负</span><span>击杀比分</span><span>时长</span><span>双方阵容 · 按分路排列</span><span></span></div>
    <div data-results>${matchRows(rows, dayNumbers(value.matches), true)}</div></section></div>`;
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
    <section class="section"><div class="section-heading"><div><h2>状态</h2><p>同一名选手近 3 场与此前 3 场的营地评分</p></div></div>${formHtml}</section>
    ${heroes.length ? `<section class="section"><div class="section-heading"><div><h2>常用英雄</h2><p>按出场次数</p></div></div><div class="hero-chips player-heroes">${heroes.map((h) => `<span>${portrait(h.hero)}${esc(h.hero)} <small>${fmt(h.matches)} 局</small></span>`).join('')}</div></section>` : ''}
    <section class="section"><div class="section-heading"><div><h2>近期对局</h2><p>点击比赛可回看完整记录</p></div><a href="#players">返回选手</a></div>
    <div class="player-history">${[...value.points].reverse().slice(0,8).map(m=>`<a href="${esc(route('match',m.matchKey))}"><span>${esc(m.date||'日期未知')}</span>${portrait(m.hero)}<b>${esc(m.hero||'未知英雄')}</b><small>${esc(m.opponent||'对手未标注')}</small><strong>${fmt(m.kda,1)} <i>KDA</i></strong></a>`).join('')||'<div class="empty">暂无逐局记录。</div>'}</div><details class="table-disclosure"><summary>查看全部逐局 <span>${rows.length} 条</span></summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>日期</th><th>对手</th><th>英雄</th><th>赛果</th><th>KDA</th><th>分均经济</th><th>分均输出</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details></section></div>`;
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

/* 10 分钟经济的分路阈值（赛训组 2026-11-14 口径）：
   对抗路 / 发育路 6800 及格、7000 良好、7400 优秀（10 分钟总量）；
   中路 550/分钟 达标即可 → 5500；打野分野核（800/分钟 → 8000）与坦野（6800 总量），
   英雄×分路类型看 /api/metadata 的 heroTypes；游走不记录。
   放在模块级，是因为保存后要就地重画评级，不想整页刷新。 */
const GOLD10_GRADES = {
  '对抗路': [[7400, '优秀', 'good'], [7000, '良好', 'ok'], [6800, '及格', 'pass'], [0, '待提升', 'low']],
  '发育路': [[7400, '优秀', 'good'], [7000, '良好', 'ok'], [6800, '及格', 'pass'], [0, '待提升', 'low']],
  '中路': [[5500, '达标', 'pass'], [0, '待提升', 'low']],
};
const GOLD10_JUNGLE = {
  tank: [[6800, '及格', 'pass'], [0, '待提升', 'low']],     // 坦野：6800 总量
  core: [[8000, '达标', 'pass'], [0, '待提升', 'low']],     // 野核：800/分钟
};
function gold10Grade(lane, value, hero) {
  const defs = lane === '打野'
    ? GOLD10_JUNGLE[jungleKindOf(hero)]
    : GOLD10_GRADES[lane];
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
    .map((x) => [x.gameTime, (x.blueGold - x.redGold) * (blue === 'red' ? -1 : 1)])
    .sort((a, b) => a[0] - b[0]);
  const draft = m.draft;
  const eventNames = { resource: '资源', structure: '建筑', kill: '击杀', heroKill: '击杀' };
  const events = m.replay?.events || [];
  const swings = [];
  for (let i = 1; i < points.length; i++) {
    const delta = points[i][1] - points[i - 1][1];
    if (Math.abs(delta) >= 200) swings.push({ t: points[i][0], delta, value: points[i][1] });
  }
  const finalDiff = points.length ? points.at(-1)[1] : null;
  const plainScore = score(m).replace(/<[^>]+>/g, '');
  const goldAt = (t) => sampleNear(points, t, (p) => p[0])?.[1] ?? null;
  const phaseRows = phaseWindows(m.duration).map((w, i) => {
    const a = goldAt(w.start), b = goldAt(w.end);
    return [w.label, time(w.start) + '–' + time(w.end), has(a) && has(b) ? diff(b - a) : '—', has(b) ? diff(b) : '—'];
  });
  const resultText = resultName[m.result] || '未知';
  /* ── 证据类型：每个区块先说清楚这是什么分析，避免把描述当结论 ─────────
     本局描述＝只陈述这一局；历史参照＝历史同口径频数；样本估计＝带样本量的
     胜率，样本少时只作观察；样本不足＝只报计数、不给比率。资源事件 <5 不报控制率。
     RATE_MIN_N 自 2026-11-17 起只用于「能不能下结论」（整局徽章是否敢写优势/
     劣势），**不再用来藏数字**：组合胜率从 1 场起就照给，读多重由 sampleTag 标。
     置信区间（95% CI）2026-11-17 起全站不显示（教练 2026-11-17：看不懂，不要）。 */
  const RATE_MIN_N = 10;
  const RES_RATE_MIN_N = 5;
  /* 样本分级（教练 2026-11-17）：不再用一刀切「n<10」把胜率藏起来——藏掉等于
     什么都不给，教练只看到一排「样本不足」。数字照给，标签说明能读多重：
     ≥30 可用 / 10–29 参考 / 3–9 观察 / <3 个例。 */
  const sampleTier = (n) => (n >= 30 ? ['is-solid', '可用']
    : n >= 10 ? ['is-ref', '参考']
      : n >= 3 ? ['is-watch', '观察'] : ['is-tiny', '个例']);
  const sampleTag = (n, title) => {
    if (!Number.isFinite(n)) return '';
    const [cls, label] = sampleTier(n);
    return `<em class="md-samp ${cls}" title="${esc(title || `${fmt(n)} 场：${label}`)}">${label}</em>`;
  };
  /* 13 场的胜率不是「结论」，但也不是「没有」——数字照给，不配区间（教练不要 CI）。 */
  const rateText = (wr) => (has(wr) ? `<span>胜率 <b>${fmt(wr, 1)}%</b></span>` : '');
  const EVIDENCE = {
    desc: ['本局描述', '只陈述这一局发生了什么，不做推断'],
    hist: ['历史参照', '历史同口径样本的场次与胜率，不是本局因果'],
    interval: ['样本估计', '给出样本量与胜率；样本少时只作观察，不下结论'],
    thin: ['样本不足', '样本量不足，只报计数，不给比率'],
  };
  const evTag = (kind) => {
    const [label, note] = EVIDENCE[kind] || EVIDENCE.desc;
    return `<span class="md-ev is-${kind}" title="${esc(note)}">${esc(label)}</span>`;
  };
  const absPoints = (m.process?.timeline || []).filter((x) => has(x.gameTime) && has(x.blueGold) && has(x.redGold) && (!has(m.duration) || x.gameTime <= m.duration))
    .map((x) => ({ t: x.gameTime, b: x.blueGold, r: x.redGold }))
    .sort((a, b) => a.t - b.t);
  const absAt = (t, key) => sampleNear(absPoints, t)?.[key] ?? null;
  const ownKey = (own === 'red' || own === 'right') ? 'r' : 'b';
  const enemyKey = ownKey === 'b' ? 'r' : 'b';
  const phaseWins = phaseWindows(m.duration);
  const phaseGain = (i, key) => {
    const w = phaseWins[i];
    if (!w || !has(m.duration) || !m.duration) return null;
    const seconds = w.end - w.start;
    if (!has(seconds) || seconds <= 0) return null;
    const a = absAt(w.start, key), b = absAt(w.end, key);
    /* 三段长度不同：绝对值不可横向比较，统一换成每分钟增长。 */
    return has(a) && has(b) ? (b - a) / seconds * 60 : null;
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
      const side = eventSide(e.killerCamp, own);
      if (!side) continue; // Unknown owner is not the opponent.
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
  /* 时长缺失时 time() 会返回「—」，不能当成一项元信息排进去（会多出一个孤零零的破折号）。 */
  const hasDuration = Number.isFinite(m.duration) && m.duration > 0;
  const mdCrumb = `<div class="md-crumb">
    <a class="md-back" href="#matches"><span aria-hidden="true">←</span> 对局档案</a>
    <span class="md-crumb-meta">${[m.date || '日期未知', m.mode, hasDuration ? time(m.duration) : ''].filter(Boolean).map((x) => `<i>${esc(x)}</i>`).join('')}</span>
    <span class="md-crumb-actions"><button class="control" data-action="filter">${icon('filter')} 数据范围</button><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></span>
  </div>`;
  const outcome = m.result === 'win' ? '收下这一局' : m.result === 'loss' ? '交出这一局' : '结束这一局';
  const heroWhen = hasDuration ? ` ${time(m.duration)} ` : '';
  /* 结论句不用「最大相邻波动」：那是 30 个噪声差分里的极值，天然会大。
     改成 10 分钟与终局的两次快照，回答「这局怎么走到终局」。 */
  const gapAt10 = goldAt(600);
  const hasGap = Number.isFinite(gapAt10) && Number.isFinite(finalDiff);
  const gapText = (value) => value === 0 ? '持平' : `${value > 0 ? '领先' : '落后'} ${fmt(Math.abs(value))}`;
  const heroClaim = hasGap
    ? `10 分钟${gapText(gapAt10)}，终局${gapText(finalDiff)}`
    : `本队${heroWhen}以 ${plainScore} ${outcome}`;
  const heroFact = hasGap
    ? `本队${heroWhen}以 ${plainScore} ${outcome} · 10 分钟差取 600 秒最近采样，终局差取末次采样；均非因果`
    : `回放记录 ${events.length} 条事件`;
  const winSide = m.result === 'win' ? 'own' : m.result === 'loss' ? 'rival' : '';
  /* 比赛脉搏放进本局结论（2026-11-14）：结论卡内直接给整局经济差曲线与资源事件标记，
     总量条紧随其后。回放事件是异步到达的，#match-verdict 会被整块替换（见 load()）。 */
  const pulseBlock = `<div class="md-hero-pulse" id="match-pulse">
      <div class="md-hero-pulse-head"><span>比赛脉搏</span><small>经济差与本队视角一致 · ${series.length} 个采样点 · 菱形＝龙、圆点＝BUFF、方块＝防御塔、大方块＝水晶，点标记看具体是什么</small></div>
      ${series.length ? mods.deep.pulse(series, events.map((e) => ({ ...e, label: eventLabel(e) })), m.duration, { own, ownName: metadata.teamName || '本队', foeName: m.opponent || '对手' }) : '<div class="md-ov-empty">阵营未知，无法展示本队视角的经济差。</div>'}
      <div class="mp-legend mp-legend-foot"><span class="own">本队</span><span class="foe">对手</span><span class="shape dia">龙</span><span class="shape cir">BUFF</span><span class="shape sq">防御塔</span><span class="shape sq big">水晶</span></div>
    </div>`;
  const mdHero = `<section class="md-hero" id="match-verdict">
    <div class="md-hero-head">
      <span class="md-hero-kicker">本局结论 ${evTag('desc')}</span>
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
        <div class="md-line-note"><em class="${m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : ''}">${esc(resultText)}</em>${hasDuration ? `<span>${time(m.duration)}</span>` : ''}</div>
        <p class="md-line-diff"><b>${diff(finalDiff)}</b> 末次采样经济差 · 本队视角</p>
      </div>
      <div class="md-line-side rival">
        <span>对手 · ${esc(sides[opposite[own]] || '阵营未知')}</span>
        <b>${esc(m.opponent || '未标注')}</b>
      </div>
    </div>
    <p>口径：营地面板经济采样（约 30 秒一点）与回放事件；经济差为本队减对手，不做跨局推断。</p>
    ${pulseBlock}
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
    const dragonTotal = ownDragons + foeDragons;
    /* 单局资源是计数：少于 5 条龙/主宰时不给控制率，1:0 写成 100% 会误导。 */
    const rate = dragonTotal >= RES_RATE_MIN_N
      ? Math.round(ownDragons / dragonTotal * 100) : null;
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
        <span class="md-res-caption">${rate === null
          ? (dragonTotal ? `龙 / 主宰 ${ownDragons} : ${foeDragons} · 样本不足（共 ${dragonTotal} 条，n<${RES_RATE_MIN_N} 不给控制率）` : '本局没有龙 / 主宰事件')
          : `龙 / 主宰控制率（我方 ${ownDragons} : ${foeDragons} 对方）`}</span>
        <span class="md-res-gauge${rate === null ? ' is-thin' : ''}"><i style="width:${rate === null ? 100 : rate}%"></i></span>
      </div>
      <div class="md-res-items">${rows.map(item).join('')}${towerItem}</div>
      ${buffLine}
    </div>`;
  })();
  const mdPhases = `<section class="section" id="match-phases"><div class="section-heading"><div><h2>阶段对比${evTag('desc')}</h2><p>经济差与阶段增长按营地采样，已按每分钟归一（三段长度不同，看 /分 可直接横向比较）；资源 / 建筑是回放事件计数；入侵是本队五人合计进入对侧半区的时间占比</p></div></div>
    ${mods.deep.phaseTable(phaseTableRows)}${resourceBand}
  </section>`;
  const nodeRows = [
    ...[...swings].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 4).map((s) => ({ t: s.t, event: '经济差波动', delta: s.delta, value: diff(s.value), dir: economyDirection(s.delta) })),
    ...events.filter((e) => /kill|death|resource|structure/i.test(e.kind || '')).slice(0, 4).map((e) => ({ t: e.t, event: `${eventLabel(e)} · ${e.killerHero || e.killer || '—'}`, delta: null, value: has(goldAt(e.t)) ? diff(goldAt(e.t)) : '—', dir: '回放事件' })),
  ].sort((a, b) => (a.t || 0) - (b.t || 0)).slice(0, 8);
  const dirClass = (d) => d === '利于本队' ? 'own' : d === '利于对手' ? 'enemy' : 'event';
  const mdTimeline = nodeRows.length ? `<section class="section" id="match-timeline"><div class="section-heading"><div><h2>关键节点${evTag('desc')}</h2><p>按时间排列，每个数字都能回到具体分钟；波动取绝对值最大的几次，是最大波动，不是因果转折</p></div></div>
    <div class="md-node-head"><span>时间</span><span>关键节点</span><span>经济差变化</span><span>当时经济差</span><span>方向 / 来源</span></div>
    <div class="md-node-list">${nodeRows.map((n) => `<div class="md-node-row"><span class="md-node-time">${time(n.t)}</span><b>${esc(n.event)}</b><span class="md-node-num" data-label="变化">${n.delta === null ? '—' : diff(n.delta)}</span><span class="md-node-num" data-label="当时经济差">${esc(n.value)}</span><span class="md-node-dir ${dirClass(n.dir)}">${esc(n.dir)}</span></div>`).join('')}</div>
  </section>` : '';
  /* 10 分钟经济：营地接口只有团队金币（30 秒一个点），没有逐人；回放的金币流水
     对不上账（残差 17.5%，个别 43%）。所以这一格只能由教练手填，填在覆盖层里，
     不动原始数据包；不填就留空，不估。
     赛训组 2026-11-14 口径：游走不记录；打野按英雄标签分野核（8000＝800/分钟）
     与坦野（6800 总量）；中路 5500 达标。 */
  const mdGold10 = (() => {
    const saved = m.gold10 || {};
    const byPos = { 对抗路: 0, 打野: 1, 中路: 2, 发育路: 3 };
    const people = (m.players || []).filter((p) => (p.camp === own || p.camp === opposite[own])
      && p.position !== '游走');                       // 游走不记录
    if (people.length < 2) return '';
    const side = (camp) => people.filter((p) => p.camp === camp)
      .sort((a, b) => (byPos[a.position] ?? 9) - (byPos[b.position] ?? 9))
      .map((p) => {
        const key = `${p.camp}-${p.slot}`;
        const value = has(saved[key]) ? saved[key] : null;
        const grade = value === null ? null : gold10Grade(p.position, value, p.hero);
        const jungleTag = p.position === '打野' && p.hero
          ? `<em class="md-g10-jtype ${jungleKindOf(p.hero)}">${jungleTypeLabel(p.hero)}</em>` : '';
        return `<label class="md-g10-row">
          <span class="md-g10-lane">${esc(p.position || '未标注')}</span>
          <span class="md-g10-hero">${esc(p.hero || '—')}${jungleTag}</span>
          <input type="number" inputmode="numeric" min="0" max="100000" step="1"
                 data-gold10="${esc(key)}" data-gold10-lane="${esc(p.position || '')}"
                 data-gold10-hero="${esc(p.hero || '')}"
                 value="${value === null ? '' : value}" placeholder="填 10 分钟金币">
          ${grade ? `<em class="md-grade ${grade.level}">${grade.label}</em>` : '<em class="md-grade is-blank"></em>'}
        </label>`;
      }).join('');
    const filled = people.filter((p) => has(saved[`${p.camp}-${p.slot}`])).length;
    return `<section class="section" id="match-gold10"><div class="section-heading"><div><h2>10 分钟经济${evTag('desc')}</h2><p>营地与回放都没有逐人金币时间轴（回放只有团队经济，逐人流水对不上账），所以这格只能手填。赛训组口径：对抗路 / 发育路 6800 及格、7000 良好、7400 优秀；中路 5500 达标（550/分钟）；打野按英雄标签分野核 8000（800/分钟）与坦野 6800；游走不记录</p></div>
      <span class="md-g10-count">已填 <b>${filled}</b> / ${people.length}</span></div>
      <div class="md-g10-grid">
        <div class="md-g10-side"><span class="md-g10-side-label own">本队</span>${side(own)}</div>
        <div class="md-g10-side"><span class="md-g10-side-label foe">对手</span>${side(opposite[own])}</div>
      </div>
      <p class="md-g10-note">填在覆盖层里，不改原始数据包；不填就留空，不估算、不补齐。打野的类型章按赛训组英雄标签给出，本局实际职责不同（如蓝领让资源）按实际判读。</p>
    </section>`;
  })();
  const mdProfiles = `<section class="section" id="match-profiles"><div class="section-heading"><div><h2>十人面板${evTag('desc')}</h2><p>对位比较按同分路两人归一，条形为本队占两人的比重；同队比较看队内份额。有位置数据时多一列「入侵」＝在对方半区的停留占比</p></div></div>
    ${mods.deep.panel(m.players || [], own, m.positions, m.duration, m.replay?.kills, m.replay?.fights, m.replay?.deaths)}
  </section>`;
  /* 位置数据请求过但没有：说明该局缺逐秒位置（未关联官方回放），不再无限转圈。 */
  const positionsEmpty = m.positionsRequested
    ? '<div class="empty">该局没有逐秒位置数据（需要在采集页的通道校对里关联本局官方回放）</div>'
    : '<div class="empty">正在读取营地的逐秒位置…</div>';
  const mdHeat = `<section class="section" id="match-heat"><div class="section-heading"><div><h2>对位热区${evTag('desc')}</h2><p>选一路，看这一路两个人在 90 秒窗口里怎么移动；可拖动时间轴或点播放。金为本队、青为对手</p></div></div>
    ${m.positions ? mods.deep.heat(m.positions, m.players, own, m.duration, m.replay) : positionsEmpty}
  </section>`;
  const mdDuel = `<section class="section" id="match-duel"><div class="section-heading"><div><h2>对位纵深${evTag('desc')}</h2><p>同一张表两种口径：深区＝推进进度 &gt; 66%，半区＝&gt; 50%（即入侵）；方块数表示停留时长，每格约 10 秒，最多 10 格</p></div></div>
    ${m.positions ? mods.deep.duel(m.positions, m.players, own, m.duration) : positionsEmpty}
  </section>`;
  const mdJungle = `<section class="section" id="match-jungle"><div class="section-heading"><div><h2>疑似打野并线${evTag('desc')}</h2><p>按出兵时间窗口、分路走廊与打野/队友聚集近似识别；不代表实际补刀或吃到兵线经济。三段按 KPL 口径切：0–4 对线 / 4–10 发育 / 10 分钟后；时间轴上线是本队打野、下线是对手，大点＝三人并线，悬停看时刻</p></div></div>
    ${m.positions ? (mods.deep.jungleJoin(m.positions, m.players, own, m.duration) || '<div class="empty">这局的位置名单里没有打野，并线统计不成立</div>') : positionsEmpty}
  </section>`;
  /* 地图页签（2026-11-14 撤掉阵线后只剩对位热区 / 对位纵深）都靠逐秒位置：
     没位置时并成一张空态卡，不再上下重复两遍同一句话。 */
  const mdMap = m.positions ? `${mdHeat}${mdDuel}` : `<section class="section" id="match-map-empty">
    <div class="section-heading"><div><h2>地图${evTag('desc')}</h2><p>对位热区与对位纵深都要逐秒位置数据</p></div></div>
    ${m.positionsRequested
      ? '<div class="empty">这一局没有逐秒位置数据：在采集页的「通道校对」里关联本局官方回放后，这里会自动出热区与纵深。</div>'
      : '<div class="empty">正在读取营地的逐秒位置…</div>'}
  </section>`;
  const ownSideKey = (own === 'red' || own === 'right') ? 'right' : 'left';
  const enemySideKey = ownSideKey === 'left' ? 'right' : 'left';
  const banSlotCount = Math.max((draft?.bans?.left || []).length, (draft?.bans?.right || []).length);
  /* 阵容槽位：固定列网格（见 CSS），头像+名字整卡可点跳英雄详情页。
     BP 顺序只有人工录入过才显示（P=选用楼层 / B=禁用楼层）；营地名单没有顺序，
     不猜——行头标「顺序未知」。 */
  const slots = (list, kind) => Array.from({ length: kind === 'bans' ? Math.max(1, banSlotCount) : 5 }, (_, i) => {
    const h = list[i];
    /* 选用与禁用的顺序可信度分开：手工录入的是每侧顺序；Ban 允许重复。 */
    const showOrder = kind === 'bans' ? draft?.banOrderKnown : draft?.pickOrderKnown;
    const orderBadge = showOrder ? `<i class="md-slot-order">${kind === 'bans' ? 'B' : 'P'}${i + 1}</i>` : '';
    const iconUrl = h?.icon || metadata.icons?.[h?.name];
    const portraitHtml = iconUrl && /^\/catalog\/icons\/hero-\d+\.png$/.test(iconUrl)
      ? `<img class="portrait" src="${esc(iconUrl)}" alt="${esc(h?.name)}" loading="lazy">`
      : portrait(h?.name);
    return h ? `<span class="md-slot">${orderBadge}<a class="bp-hero-link" href="${esc(route('hero', h.name))}" title="查看 ${esc(h.name)} 详情">${portraitHtml}<b>${esc(h.name)}</b></a></span>`
             : `<span class="md-slot md-slot-empty">${orderBadge}<em>${kind === 'bans' ? (banSlotCount ? '空 BAN' : '禁用未录入') : (draft?.pickOrderKnown ? '空位' : '顺序未知')}</em></span>`;
  }).join('');
  const bpRow = (key, title, side) => `<div class="md-bp-row ${side}">
    <b>${esc(title)}${draft && !draft.pickOrderKnown ? '<em class="md-bp-noorder">顺序未知</em>' : (draft?.orderAssumed ? '<em class="md-bp-assumed">推定</em>' : '')}</b>
    <div class="md-bp-seg"><span class="md-bp-seg-label">选用</span>
      <span class="md-bp-picks">${slots(draft?.picks?.[key] || [], 'picks')}</span></div>
    <div class="md-bp-seg"><span class="md-bp-seg-label">禁用</span>
      <span class="md-bp-bans" style="--bp-slots:${Math.max(1, banSlotCount)}">${slots(draft?.bans?.[key] || [], 'bans')}</span></div>
  </div>`;
  /* 头像 + 名字一起跳英雄详情页；大屏各区块（对位 / 克制 / 组合）共用。 */
  const heroFace = (hero, cls) => hero
    ? `<a class="bp-hero-link md-mu-face ${cls}" href="${esc(route('hero', hero))}" title="查看 ${esc(hero)} 详情">${portrait(hero)}<b>${esc(hero)}</b></a>`
    : '<span class="md-mu-face is-none">—</span>';
  /* ── BP 复盘：把「历史对位」「历史联动」两个库对到本局，回答「这把 BP 打得怎么样」──
     只报算得出来的：算不了的写「待积累」，不给总分，也不拿胜负倒推 BP 好坏。 */
  const bpAnalysis = (() => {
    const empty = { review: '', combos: '', kpl: '', matchup: '', ownCombos: [], foeCombos: [], comboCard: () => '' };
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
    /* 大盘数据的窗口日：91m 的日线隔天发布，今天刷新过就取到源站最新一行。
       「今日巅峰对位胜率」指今天刷新、拿到的最新窗口，页面上把日期写明。 */
    const ladderDay = String(m.bpFacts?.ladder?.windowEnd || '').slice(0, 10);
    const lanes = ORDER.map((lane) => {
      const a = mine.get(lane), b = theirs.get(lane);
      if (!a || !b) return null;
      const facts = ladderLanes.get(lane) || null;
      const scrim = byPair.get(`${a.hero}|${b.hero}`) || null;
      const nowDiff = has(a.gold) && has(b.gold) ? a.gold - b.gold : null;
      /* 标签口径（教练 2026-11-13）：优势 / 劣势 / 打平 / 初步；
         50–199 局只作初步观察，n≥200 且 CI 不跨 0 才判优势/劣势。 */
      const states = { ahead: '优势', behind: '劣势', even: '打平', preliminary: '初步' };
      const verdict = facts && facts.n ? (states[facts.state] || '样本不足') : '样本不足';
      const judgeable = verdict === '优势' || verdict === '劣势';
      /* 终局经济与历史对位方向一致不等于前期对线兑现；4'/10' 团队经济也建立不了单路对线兑现。 */
      const realised = judgeable ? laneRealisation(verdict, nowDiff) : null;
      return { lane, a, b, facts, scrim, verdict, nowDiff, judgeable, realised };
    }).filter(Boolean);

    /* 头像 + 名字一起跳英雄详情页（heroFace 定义在 bpRow 一层，大屏各区块共用）。 */
    const verdictText = (lane) => lane.verdict === '优势' ? '优势'
      : lane.verdict === '劣势' ? '劣势' : lane.verdict === '打平' ? '打平'
      : lane.verdict === '初步' ? '初步' : '样本不足';
    const verdictCls = (lane) => lane.verdict === '优势' ? 'is-ahead'
      : lane.verdict === '劣势' ? 'is-behind' : lane.verdict === '打平' ? 'is-even' : 'is-thin';
    /* 没有对位样本时把原因写清楚：现在只剩「未收录 / <50 局」，
       使用率只作背景，不再当门槛。 */
    const laneMissNote = (lane) => {
      const a = lane.facts?.minePick, b = lane.facts?.foePick;
      if (a === null || a === undefined || b === null || b === undefined) return '未收录或不足 50 局';
      return `未收录或不足 50 局，双方使用率 ${fmt(a, 2)}% / ${fmt(b, 2)}%`;
    };
    /* 英雄强度：对位样本对冷门英雄永远凑不够，教练要的「这个英雄在巅峰千强本身
       是什么强度」只能从英雄维度给。档位按**本局这条路**的英雄池排（不是源站主分路：
       源站把李信也放进发育路榜，按主分路排会拿他比射手）。近 7 天看当下。 */
    const strengthBit = (hero, s, kind) => {
      if (!s) return '';
      const wr = has(s.wr7d) ? s.wr7d : s.wr;
      const pick = has(s.pick7d) ? s.pick7d : s.pick;
      if (!has(wr)) return '';
      const tier = s.tier
        ? `<em class="md-mu-tier ${String(s.tier).toLowerCase()}" title="同路档位：${esc(s.role || '')} 第 ${fmt(s.rank)} / ${fmt(s.size)}">${s.tier}</em>`
        : '';
      return `<span class="md-mu-str ${kind}"><b>${esc(hero)}</b><i>${fmt(wr, 1)}%</i><small>登场 ${fmt(pick, 2)}%</small>${tier}</span>`;
    };
    const strengthLine = (lane) => {
      const s = lane.facts?.strength;
      if (!s) return '';
      const mine = strengthBit(lane.a.hero, s.mine, 'own');
      const foe = strengthBit(lane.b.hero, s.foe, 'foe');
      if (!mine && !foe) return '';
      const size = s.mine?.size || s.foe?.size;
      return `<p class="md-mu-strength">强度 <small>近 7 天 · 本路${size ? ` ${fmt(size)} 人` : ''}</small>${mine}${foe || '<span class="md-mu-str is-none">对方未收录</span>'}</p>`;
    };
    const laneCard = (lane) => `<article class="md-mu-card ${verdictCls(lane)}">
      <header><span class="md-mu-lane">${lane.lane}</span><em class="${verdictCls(lane)}">${verdictText(lane)}</em></header>
      <div class="md-mu-who">${heroFace(lane.a.hero, 'own')}<i>vs</i>${heroFace(lane.b.hero, 'foe')}</div>
      ${lane.facts && lane.facts.n ? `<p class="md-mu-hist">巅峰千强对位 · ${fmt(lane.facts.n)} 局${lane.facts.n < 200 ? ' <small>（初步观察，n<200 不判优势/劣势）</small>' : lane.facts.n < 3000 ? ' <small>（最好 3000+）</small>' : ''}${lane.facts.lowPick ? ` <small>（低登场率 ${fmt(lane.facts.aPick, 2)}% / ${fmt(lane.facts.bPick, 2)}%，胜率可能虚高；只作初步观察）</small>` : ''} · 对位胜率 <b>${fmt(lane.facts.wr, 1)}%</b><span>（预期 ${fmt(lane.facts.expected, 1)}% · 超额 <b>${lane.facts.excess > 0 ? '+' : ''}${fmt(lane.facts.excess, 1)}</b>）</span></p>`
        : `<p class="md-mu-hist">没有可判的对位样本（${laneMissNote(lane)}）</p>`}
      ${strengthLine(lane)}
      ${lane.scrim && lane.scrim.n ? `<p class="md-mu-hist">自家 ${fmt(lane.scrim.n)} 局 · 对线领先 ${fmt(lane.scrim.aheadRate, 0)}%</p>` : ''}
      ${lane.nowDiff === null ? '<p class="md-mu-now">本局经济差 —</p>'
        : `<p class="md-mu-now">本局对位经济差 <b>${diff(lane.nowDiff)}</b>${lane.realised === null ? ''
          : lane.realised ? ' · <i class="is-hit">终局同向</i>' : ' · <i class="is-miss">终局反向</i>'}</p>`}
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
         两种口径分开写，不合成一个结论。
         教练 2026-11-17：2 局 100% 不能当结论，但把胜率整行藏掉更糟——一排「样本不足」
         等于什么都没给。所以胜率 / 搭档加成一律给，用「可用 / 参考 / 观察 / 个例」标出
         能读多重。 */
      const kplRow = (m.bpFacts?.kpl?.comboIndex || {})[combo.heroes.join('+')];
      const decided = Number(combo.decided ?? combo.games) || 0;
      const kplWins = kplRow && has(kplRow.wins) ? kplRow.wins
        : kplRow && has(kplRow.wr) ? Math.round((kplRow.n || 0) * kplRow.wr / 100) : null;
      /* 头像和名字都跳英雄详情页。 */
      const faceLink = (hero) => `<a class="bp-hero-link" href="${esc(route('hero', hero))}" title="查看 ${esc(hero)} 详情">${portrait(hero)}<b>${esc(hero)}</b></a>`;
      /* 搭档加成＝相对两人各自基准的差，1–2 局算出来是噪声（+55 点那种），
         所以只在 3 局起才给；胜率本身照给，用样本标签说明能读多重。 */
      const synText = has(combo.synergy) && decided >= 3
        ? `<span class="${combo.synergy >= 0 ? 'is-good' : 'is-bad'}" title="搭档加成 = 两人同场时的胜率 − 两名英雄各自平时胜率算出的预期值（${pct(combo.winRate)} − ${pct(combo.expected)}）">搭档加成 ${Math.abs(combo.synergy) < 0.05 ? '0' : diff(combo.synergy)} 点</span>`
        : '';
      return `<article class="md-combo-card">
      <div class="md-combo-heroes">${combo.heroes.map(faceLink).join('<i>+</i>')}</div>
      <p>${fmt(combo.games)} 局 ${fmt(combo.wins)} 胜
        ${has(combo.winRate) ? `<span class="md-combo-rate">胜率 ${fmt(combo.winRate, 1)}%</span>` : ''}
        ${sampleTag(decided, `自家 ${fmt(decided)} 局：${sampleTier(decided)[1]}`)}
        ${synText}</p>
      ${kplRow ? `<p class="md-combo-kpl">KPL ${fmt(kplRow.n)} 场${has(kplRow.wr)
          ? ` · 胜率 ${fmt(kplRow.wr, 1)}%`
          : ''}${sampleTag(Number(kplRow.n) || 0, `KPL ${fmt(kplRow.n)} 场：${sampleTier(Number(kplRow.n) || 0)[1]}`)}${kplRow.lastDate ? `（最近 ${esc(String(kplRow.lastDate).slice(0, 10))}）` : kplRow.year ? `（${kplRow.year} 年）` : ''}</p>`
        : '<p class="md-combo-kpl is-quiet">KPL 没出现过</p>'}
    </article>`;
    };
    const combos = (ownCombos.length || foeCombos.length) ? `<div class="md-bp-combos">
      <div class="md-bp-combo-side"><span>我方组合</span><div class="md-combo-grid">${ownCombos.map(comboCard).join('') || '<small>当前阵容没有历史组合样本</small>'}</div></div>
      <div class="md-bp-combo-side foe"><span>对手组合</span><div class="md-combo-grid">${foeCombos.map(comboCard).join('') || '<small>对手阵容没有历史组合样本</small>'}</div></div>
    </div>` : '';

    /* 赛事命中：先回答「我们这套 5 人整阵容，KPL 那边见过没有」，再拆到双人 / 三人
       组合。所以只报命中、场次、胜率和用过这套的队，不报是哪一场。
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

      /* 第三层：命中组合逐条（沿用 3 双人 + 2 三人的截断）。
         头像跳英雄详情页；teams 已按最近使用日期倒序（后端 kpl_bp 排好），
         「最近谁用」= 第一个 chip；使用时间显示组合最近一次同场的比赛日期。
         胜率一律给（教练 2026-11-17）：11 场 45.5% 是有信息量的，9 场 / 3 场也一样，
         只用「可用 / 参考 / 观察 / 个例」标出能读多重，不再整行写「样本不足」。 */
      const comboRow = (row, size) => {
        const heroes = Array.isArray(row?.heroes) ? row.heroes.filter(Boolean) : [];
        if (!heroes.length) return '';
        const n = Number(row.n) || 0;
        const faceLink = (hero) => `<a class="bp-hero-link" href="${esc(route('hero', hero))}" title="查看 ${esc(hero)} 详情">${portrait(hero)}<b>${esc(hero)}</b></a>`;
        const usedWhen = dateOnly(row.lastDate)
          ? `<span class="md-kplhit-when">最近 <b>${dateOnly(row.lastDate)}</b></span>`
          : has(row.year) ? `<span class="md-kplhit-when"><b>${row.year}</b> 年</span>` : '';
        return `<div class="md-kplhit-row">
          <span class="md-kplhit-tag">${size === 3 ? '三人' : '双人'}</span>
          <div class="md-kplhit-body">
            <div class="md-kplhit-heroes"><span class="md-kplhit-faces">${heroes.map(faceLink).join('<i>+</i>')}</span></div>
            ${teamChips(row.teams)}
          </div>
          <div class="md-kplhit-stat">${has(row.n) ? `<span><b>${fmt(row.n)}</b> 场</span>` : ''}${rateText(row.wr)}${sampleTag(n, `KPL 同队同场 ${fmt(n)} 场：${sampleTier(n)[1]}`)}${usedWhen}</div>
        </div>`;
      };
      /* 命中组合逐条：前 5 条直接列（3 双人 + 2 三人），其余收进「展开全部」。
         教练要的是先看最常出现的几组，想看全再展开——不默认把 10 条全铺开。 */
      const allItems = [
        ...(Array.isArray(facts.pairs) ? facts.pairs : []).map((row) => ({ row, size: 2 })),
        ...(Array.isArray(facts.trios) ? facts.trios : []).map((row) => ({ row, size: 3 })),
      ];
      const headItems = allItems.slice(0, 5);
      const restItems = allItems.slice(5);
      const rows = headItems.map((item) => comboRow(item.row, item.size)).filter(Boolean);
      const restRows = restItems.map((item) => comboRow(item.row, item.size)).filter(Boolean);
      const list = rows.length ? `<div class="md-kplhit-list">
        <div class="md-kplhit-list-head"><span>命中组合</span><span>同队同场同时选用过，≥1 场即算命中 · 胜率按场次分级：≥30 可用 / 10–29 参考 / 3–9 观察 / &lt;3 个例</span></div>
        ${rows.join('')}
        ${restRows.length ? `<details class="md-kplhit-more"><summary>展开其余 ${restRows.length} 组（本队 ${has(totalPairs) ? fmt(totalPairs) : '—'} 组双人里命中 ${fmt(hitPairs)} 组）</summary>${restRows.join('')}</details>` : ''}
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

    /* 概览只留一句判定：对位 / 赛事 / 组合的明细分别在下方区块，不重复列数字。
       可判对位不足 3 路时不给「优势 / 劣势」的总体结论；50–199 的初步观察不计入。 */
    const judged = lanes.filter((lane) => lane.judgeable);
    const prelim = lanes.filter((lane) => lane.verdict === '初步');
    const ahead = judged.filter((lane) => lane.verdict === '优势').length;
    const behind = judged.filter((lane) => lane.verdict === '劣势').length;
    const judgeableCombos = ownCombos.filter((combo) => (Number(combo.decided ?? combo.games) || 0) >= RATE_MIN_N);
    const thin = judged.length < 3;
    const tone = (!judged.length && !judgeableCombos.length) || thin ? 'is-thin'
      : ahead > behind ? 'is-good' : behind > ahead ? 'is-bad' : 'is-even';
    const badge = !judged.length && !judgeableCombos.length
      ? (prelim.length ? '初步观察' : '证据不足')
      : thin ? '样本偏薄'
       : ahead > behind ? '优势' : behind > ahead ? '劣势' : '打平';
    const review = `<span class="md-bprev-badge ${tone}" title="样本不足时只作参考；对位 / 组合明细见下方区块">${badge}</span>`;
    /* 「预期 vs 执行」整块撤掉（教练 2026-11-17：教练看不懂，一张卡片就够）。
       对位卡片里保留一句终局同向/反向作为注脚，不再单独排一张对照表。 */
    const matchup = lanes.length ? `<div class="md-matchup">
      <div class="md-matchup-head"><b>对位压制</b><small>巅峰千强同分路对位${ladderDay ? `（源站累积样本，截至 ${ladderDay}）` : ''}：基准取最近 8 周周中位数，低登场率英雄按 pick/(pick+2%) 向 50% 收缩；n≥50 收录，50–199 或低登场率只作初步观察，n≥200 且方向稳定才判优势/劣势</small></div>
      <div class="md-mu-grid">${lanes.map(laneCard).join('')}</div></div>` : '';
    /* 复制成一段话：教练复盘完要发群 / 写进日报，不想再手抄。
       只取已经判定过的结论（对位 / 克制 / 命中组合），不另外算口径。 */
    const copyText = (() => {
      const lines = [];
      const date = String(m.dateText || m.date || '').slice(0, 10);
      lines.push(`${date} vs ${m.opponent || '对手'}｜本局 BP 复盘：${badge}`);
      for (const lane of lanes) {
        const sample = lane.facts?.n ? `${fmt(lane.facts.n)} 局` : '无对位样本';
        const gold = lane.nowDiff === null ? '' : `，本局 ${diff(lane.nowDiff)}`;
        lines.push(`· ${lane.lane} ${lane.a.hero} vs ${lane.b.hero}：${lane.verdict}（${sample}${gold}）`);
      }
      const counterRows = (m.bpFacts?.counters?.lanes || [])
        .filter((row) => has(row.campCounter) || has(row.campCountered) || row.kpl)
        .map((row) => {
          if (row.kpl) return `${row.lane} ${row.mine} vs ${row.foe} KPL ${row.kpl.n} 场我方 ${fmt(row.kpl.wr, 1)}%`;
          if (has(row.campCountered)) return `${row.lane} ${row.mine} 被 ${row.foe} 克 ${fmt(row.campCountered, 1)}`;
          return `${row.lane} ${row.mine} 克 ${row.foe} ${fmt(row.campCounter, 1)}`;
        });
      if (counterRows.length) lines.push(`· 克制：${counterRows.join('；')}`);
      const hitFacts = m.bpFacts?.kpl;
      const hitRows = [...(hitFacts?.pairs || []).slice(0, 3), ...(hitFacts?.trios || []).slice(0, 2)]
        .map((row) => `${row.heroes.join('+')} ${row.n} 场${has(row.wr) ? ` ${fmt(row.wr, 1)}%` : ''}`);
      if (hitRows.length) lines.push(`· KPL 命中组合：${hitRows.join('；')}`);
      return lines.join('\n');
    })();
    /* 拆开返回：复盘大屏各区块共用同一批判定结果，不另算口径。 */
    return { review, combos, kpl: kplBlock, matchup, ownCombos, foeCombos, comboCard, copyText };
  })();
  /* 总量按十人面板逐人求和（详情接口不带 own/enemy 汇总）。 */
  const teamAgg = (camp) => ({
    gold: teamTotal(m.players, camp, 'gold'), kills: teamTotal(m.players, camp, 'kills'),
    damage: teamTotal(m.players, camp, 'damage'), taken: teamTotal(m.players, camp, 'taken'),
  });
  const totalsBand = (id) => `<div class="md-totals-band" id="${id}">
    <div class="md-totals-head"><span>总量 · ${esc(metadata.teamName || '本队')} vs ${esc(m.opponent || '对手')} ${evTag('desc')}</span><small>五人对应字段完整才合计（缺失显示—）；金色为本队，青色为对手；/分 按本局时长归一</small></div>
    ${mods.deep.totals({ own: teamAgg(own), enemy: teamAgg(opposite[own]), duration: m.duration })}
  </div>`;
  const mdTotals = totalsBand('match-totals');

  /* ── 复盘大屏（2026-11-14 改版）─────────────────────────────────────
     结论（内含比赛脉搏）→ 总量 → 双方阵容 → 本局 BP 复盘（并入赛事命中）→
     对位压制 → 联动组合 → 阶段对比 + 关键节点。团战与资源 / 经济走势两张卡按教练
     要求撤掉（团战细节在「事件」页签，经济曲线在结论卡的脉搏里）；赛事命中不再是
     独立卡片，命中组合（头像 / 胜率 / 最近谁用 / 使用时间）直接长在 BP 复盘里。
     回放是异步到达的，结论与各区块按 id 整块替换。 */
  const ovCombos = (() => {
    const ownList = bpAnalysis.ownCombos || [], foeList = bpAnalysis.foeCombos || [];
    if (!ownList.length && !foeList.length) return '<div class="md-ov-empty">双方阵容都没有历史组合样本（联动组合需要营地 / 回放数据）。</div>';
    const side = (label, list, cls) => `<div class="md-bp-combo-side${cls ? ' ' + cls : ''}"><span>${label}</span><div class="md-combo-grid">${list.length ? list.slice(0, 3).map(bpAnalysis.comboCard).join('') : '<small>当前阵容没有历史组合样本</small>'}</div></div>`;
    return `<div class="md-bp-combos md-ov-combos">${side('我方组合', ownList)}${side('对手组合', foeList, 'foe')}</div>`;
  })();

  /* ── 组合得失（2026-11-17）──────────────────────────────────────────
     把「双方想凑的组合」拆成四种结局，左右两栏各一种阵营：
       我方想拿 → 拿到了 / 被对面拆了；  对面想拿 → 他们拿到了 / 被我们拆了。
     「想凑」的候选池两个来源：
       ① 这一方自己打过的双人 / 三人（营地组合，≥2 局）——他们真会用的；
       ② KPL 上本局出现过的英雄之间的组合（≥5 场）——职业赛场验证过的。
     判定全在选人上：阵容里能凑齐＝拿到；只差一格、且那格被对面 ban 走或抢走
     （对面先拿）＝拆掉；一格都没拿到的谈不上「想凑」，不列。
     拆掉的那一格画成灰色 + 斜杠，拿到的是亮的——一眼看出缺哪块。 */
  /* 组合得失的摘要行，供「复制结论」拼在最后（mdBroken 里赋值）。 */
  let ledgerLine = '';
  const mdBroken = (() => {
    if (!draft) return '';
    const names = (rows) => (rows || []).map((row) => (row && row.name) || '').filter(Boolean);
    const picks = { own: names(draft?.picks?.[ownSideKey]), foe: names(draft?.picks?.[enemySideKey]) };
    const bans = { own: names(draft?.bans?.[ownSideKey]), foe: names(draft?.bans?.[enemySideKey]) };
    if (!picks.own.length && !picks.foe.length) return '';
    const kplDraft = m.bpFacts?.kpl?.draftCombos || { pairs: {}, trios: {} };
    const combosData = m.combosData;
    const kplOf = (heroes) => kplDraft[heroes.length === 3 ? 'trios' : 'pairs'][[...heroes].sort().join('+')] || null;
    const keyOf = (heroes) => [...heroes].sort().join('+');

    const collect = (side, oppSide) => {
      const mine = picks[side], opp = picks[oppSide], oppBans = bans[oppSide];
      if (!mine.length) return { got: [], broken: [] };
      const got = [], broken = [];
      const consider = (heroes, extra) => {
        const inside = heroes.filter((hero) => mine.includes(hero));
        const missing = heroes.filter((hero) => !mine.includes(hero));
        // 一格都没凑到 → 不是「想凑」，不列
        if (!inside.length) return;
        if (!missing.length) {
          got.push({ heroes, inside, kpl: kplOf(heroes), ...extra });
          return;
        }
        if (missing.length !== 1) return;
        const gone = missing[0];
        const reason = oppBans.includes(gone) ? 'ban' : opp.includes(gone) ? 'steal' : '';
        if (!reason) return;
        broken.push({ heroes, inside, gone, reason, kpl: kplOf(heroes), ...extra });
      };
      for (const kind of ['pairs', 'trios']) {
        for (const combo of (combosData?.[kind]?.[side]?.combos || [])) {
          const games = Number(combo.decided ?? combo.games) || 0;
          if (games < 2) continue;                 // 1 局不成「组合」，只是凑巧
          consider(combo.heroes || [], { source: 'camp', games,
            wins: combo.wins, winRate: combo.winRate });
        }
      }
      for (const kind of ['pairs', 'trios']) {
        for (const row of Object.values(kplDraft[kind] || {})) {
          if ((row.n || 0) < 5) continue;          // KPL 旁证要够样本
          consider(row.heroes || [], { source: 'kpl', games: 0, wins: null, winRate: null });
        }
      }
      /* 同一批英雄只留最「完整」的那条：三人组合在，就不重复列它包含的双人。
         拿到与拆掉分开去重——「拿到两人套、三人套被拆」是两件事，都值得留。 */
      const prune = (list) => {
        const kept = list.filter((item) => !list.some((other) => other !== item
          && other.heroes.length > item.heroes.length
          && item.heroes.every((hero) => other.heroes.includes(hero))));
        const seen = new Set();
        return kept.sort((a, b) => (b.games - a.games)
          || ((b.winRate || 0) - (a.winRate || 0))
          || ((b.kpl?.n || 0) - (a.kpl?.n || 0)))
          .filter((item) => {
            const key = keyOf(item.heroes);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          })
          .slice(0, 3);
      };
      return { got: prune(got), broken: prune(broken) };
    };

    const row = (item, side, status) => {
      const opp = side === 'own' ? '对面' : '我们';
      const facts = [];
      if (item.source === 'camp') {
        facts.push(`${side === 'own' ? '我方' : '对方'} ${fmt(item.games)} 局${has(item.winRate) ? ` · ${fmt(item.winRate, 1)}%` : ''}`);
      }
      if (item.kpl) facts.push(`KPL ${fmt(item.kpl.n)} 场${has(item.kpl.wr) ? ` · ${fmt(item.kpl.wr, 1)}%` : ''}`);
      const faces = item.heroes.map((hero) => heroFace(hero, item.gone === hero ? 'is-gone' : '')).join('<i>+</i>');
      const note = status === 'got'
        ? `<span class="md-bk-why is-got">${side === 'own' ? '我们拿到' : '他们拿到'}</span>`
        : `<span class="md-bk-why">${opp} ${item.reason === 'ban' ? 'ban' : '抢'} 了 <b>${esc(item.gone)}</b><em class="md-bk-tag ${item.reason}">${item.reason === 'ban' ? 'ban' : '抢'}</em></span>`;
      return `<div class="md-bk-row ${status === 'got' ? 'is-got' : 'is-broken'}">
        <span class="md-bk-faces">${faces}</span>
        ${note}
        <span class="md-bk-ev">${facts.join(' · ')}</span>
      </div>`;
    };

    const own = collect('own', 'foe');
    const foe = collect('foe', 'own');
    if (!own.got.length && !own.broken.length && !foe.got.length && !foe.broken.length) return '';
    ledgerLine = `· 组合得失：我方拿到 ${own.got.length} 套、被拆 ${own.broken.length} 套；`
      + `对面拿到 ${foe.got.length} 套、被拆 ${foe.broken.length} 套`;
    const column = (side, title, data) => {
      const label = side === 'own' ? '我方' : '对方';
      const counter = (n) => `<em>拿到 ${fmt(n)} 套 · 被拆 ${fmt(data.broken.length)} 套</em>`;
      return `<div class="md-bk-col ${side}">
        <div class="md-bk-head"><b>${title}</b>${counter(data.got.length)}</div>
        <div class="md-bk-list">
          ${data.got.map((item) => row(item, side, 'got')).join('')}
          ${data.broken.map((item) => row(item, side, 'broken')).join('')}
        </div>
        ${(!data.got.length && !data.broken.length) ? `<p class="md-bk-empty">${label}这局没有能凑的历史组合</p>` : ''}
      </div>`;
    };
    return `<div class="md-broken">
      ${column('own', '我方想拿的组合', own)}
      ${column('foe', '对面想拿的组合', foe)}
    </div>`;
  })();

  /* 复盘大屏的区块：每个区块仍是 section.section（后到的回放数据按 id 替换），
     但由下面的一组整行容器拼成宽屏版式，不再一列堆到底。 */
  const mdOvLineup = `<section class="section md-ov" id="match-ov-lineup">
      <div class="section-heading"><div><h2>双方阵容${evTag('desc')}</h2><p>营地终局名单 · 选用 / 禁用各自按槽位对齐${draft?.pickOrderKnown
        ? (draft?.orderAssumed
            ? '，默认按训练赛顺序推定（营地名单排列，未人工核验）；可手工修改'
            : draft?.banOrderKnown ? `，BP 顺序按手工录入显示（${draft?.bpOrderMode === 'kpl' ? 'KPL' : '训练赛'}模式；P＝选用楼层，B＝禁用楼层）` : '，选用顺序已录入（P＝楼层）；禁用只有名单、无先后')
        : '；营地名单不记 BP 顺序，标「顺序未知」，手工录入后显示楼层'}${draft ? ` · 本局录入 ${banSlotCount} 个禁用槽` : ''}</p></div>${draft && draft.gameSeq ? `<button type="button" class="control" data-bp-order>${draft.pickOrderKnown ? '修改 BP 顺序' : '手工录入 BP 顺序'}</button>` : ''}</div>
      <div class="md-ov-lineup">${draft ? `${bpRow(ownSideKey, '本队 · ' + (sides[own] || ''), 'own')}${bpRow(enemySideKey, '对手 · ' + (sides[opposite[own]] || ''), 'enemy')}` : '<div class="md-ov-empty">暂无禁选记录。</div>'}</div>
    </section>`;
  const mdOvBp = `<section class="section md-ov" id="match-ov-bp">
      <div class="section-heading"><div><h2>本局 BP 复盘${evTag('hist')} ${bpAnalysis.review || ''}</h2><p>赛事命中看 KPL——命中组合带头像、胜率、最近谁用、使用时间，直接长在下面；对位与组合分别在下方区块</p></div>${(bpAnalysis.copyText || ledgerLine) ? `<button type="button" class="control md-copy" data-md-copy="${esc([bpAnalysis.copyText, ledgerLine].filter(Boolean).join('\n'))}" title="把这一局的 BP 结论复制成一段话，直接发群或贴进日报">复制结论</button>` : ''}</div>
      <div class="md-ov-pad">${bpAnalysis.kpl || '<div class="md-ov-empty">这局没有 KPL 赛事数据，赛事命中先留空。</div>'}</div>
    </section>`;
  const mdOvMatchup = `<section class="section md-ov" id="match-ov-matchup">
      <div class="section-heading"><div><h2>对位压制${evTag('interval')}</h2><p>巅峰千强同分路对位（源站累积样本）：基准取最近 8 周周中位数，低登场率英雄向 50% 收缩；n≥50 收录，50–199 或低登场率只作初步观察，n≥200 且方向稳定才判优势/劣势；牌面下方补「英雄强度」——近 7 天胜率、登场率与同路 T1–T4 档位，对位样本凑不够时看这一行</p></div></div>
      <div class="md-ov-pad">${bpAnalysis.matchup || '<div class="md-ov-empty">五路对位在巅峰千强都没有可判样本。</div>'}</div>
    </section>`;
  /* 克制命中：两个证据源分开列、不合成一个分（与对位压制同一口径纪律）。
     KPL＝自抓赛事的跨阵营有向对位（n≥10 且胜率≥55% 记命中，3–9 局记观察值）；
     营地＝营地 App 英雄关系指数（≥2.5 记命中，1.5–2.5 记倾向）。
     2026-11-17 改：① 营地按**两侧各查两向**（a克b 可能只记在 b 的被克里）；
     ② 有记录就显示数值，不再只输出「命中 / 无记录」；③ 五路里查不到的那几路
     合并成一句说明，不占五行空白。 */
  const ovCounters = (() => {
    const facts = m.bpFacts?.counters;
    if (!facts) return '<div class="md-ov-empty">这局没有克制事实数据（KPL / 营地两源都没加载）。</div>';
    const wrText = (value) => has(value) ? `${Number(value).toFixed(1)}%` : '—';
    const chip = (kind, text, title) => text
      ? `<span class="md-ct-chip ${kind}" title="${esc(title || text)}">${esc(text)}</span>` : '';
    /* KPL 证据 chip：后端已统一成**我方视角**（有 a→b 用 a→b，否则用 b→a 的补数），
       所以永远只有一条「N 场 · 我方 X%」，不再同时列「我方 40 / 对方 60」两遍。 */
    const kplChip = (row) => {
      if (!row || !has(row.n) || !has(row.wr)) return '';
      const lead = Number(row.lead) || 0;
      const kind = row.hit ? (lead > 0 ? 'is-hit' : 'is-miss') : row.watch ? 'is-watch' : 'is-quiet';
      const tag = row.hit ? '命中' : row.watch ? '观察' : '参考';
      const when = row.lastDate ? `，最近 ${row.lastDate}` : '';
      const arrow = lead >= 2 ? ' ↑' : lead <= -2 ? ' ↓' : '';
      return chip(kind, `KPL ${fmt(row.n)} 场 · 我方 ${wrText(row.wr)}${arrow}`,
        `我方英雄对位胜率 ${wrText(row.wr)}（${fmt(row.n)} 场，对方 ${wrText(100 - row.wr)}${when}）· ${tag}`);
    };
    const campChip = (index, hit, lean, countered, via) => {
      if (index === null || index === undefined) return '';
      const text = countered ? `被克制 ${fmt(Number(index), 1)}` : `营地克制 ${fmt(Number(index), 1)}`;
      const kind = hit ? (countered ? 'is-miss' : 'is-hit') : lean ? 'is-watch' : 'is-quiet';
      const side = via === 'foe' ? '（从对方英雄的关系表查到）' : '';
      return chip(kind, text,
        `营地 App 英雄关系指数 ${fmt(Number(index), 1)}${countered ? '（对方克我方）' : '（我方克对方）'}${side}`);
    };
    const laneRow = (entry) => {
      const chips = [
        kplChip(entry.kpl),
        campChip(entry.campCounter, entry.campHit, entry.campLean, false, entry.campCounterVia),
        campChip(entry.campCountered, entry.campCounteredHit, entry.campCounteredLean, true, entry.campCounteredVia),
      ].filter(Boolean).join('');
      return `<div class="md-ct-row">
        <span class="md-ct-lane">${esc(entry.lane)}</span>
        <span class="md-ct-who">${heroFace(entry.mine, 'own')}<i>vs</i>${heroFace(entry.foe, 'foe')}</span>
        <span class="md-ct-chips">${chips || '<em class="md-ct-none">未查到这对的记录</em>'}</span>
      </div>`;
    };
    const notableRow = (entry) => {
      const good = entry.verdict === '我方克制';
      const chips = [
        chip(good ? 'is-hit' : 'is-miss', entry.verdict),
        kplChip(entry.kpl),
        campChip(entry.camp, entry.campHit, entry.campLean, !good, entry.campVia),
        entry.conflict ? chip('is-quiet', '两源方向不一致', 'KPL 与营地对这对组合的方向判断不同，各看各的，不下单方结论') : '',
      ].filter(Boolean).join('');
      return `<div class="md-ct-row is-notable">
        <span class="md-ct-lane">交叉</span>
        <span class="md-ct-who">${heroFace(entry.mine, 'own')}<i>vs</i>${heroFace(entry.foe, 'foe')}</span>
        <span class="md-ct-chips">${chips}</span>
      </div>`;
    };
    const rows = (facts.lanes || []).map((entry) => ({ entry, html: laneRow(entry) }))
      .map((item) => ({ ...item, empty: /md-ct-none/.test(item.html) }));
    const hitRows = rows.filter((item) => !item.empty).map((item) => item.html).join('');
    const blank = rows.filter((item) => item.empty);
    /* 五路全空时不再排五行「两源均无克制记录」——合成一句，把为什么没有说清楚。 */
    const blankNote = blank.length ? `<div class="md-ct-blank">
        <b>${blank.length === rows.length ? '五路' : `另有 ${blank.length} 路`}没有可查的克制记录</b>
        <span>${blank.map((item) => `${item.entry.lane} ${item.entry.mine}↔${item.entry.foe}`).join(' · ')}——
          营地表每个英雄只收录前 3 组关系，KPL 只统计真实交手过的对位；查不到＝库里没有这对，不是「不克制」。
          这一路看上方「对位压制」的巅峰千强对位样本。</span>
      </div>` : '';
    const laneList = `${hitRows}${blankNote}`;
    const notableList = (facts.notable || []).map(notableRow).join('');
    const foot = `<p class="md-ct-foot">口径：KPL＝本项目自抓赛事的跨阵营有向对位（样本 ≥10 局且胜率 ≥55% 记命中，3–9 局按观察值列出，库里 ${fmt(facts.kpl?.pairs)} 条）；营地＝营地 App 英雄关系指数（≥ 2.5 记命中，1.5–2.5 记倾向；每个英雄只收录前 3 组，一对英雄两侧各查两向${facts.camp?.capturedAt ? `，抓取于 ${esc(facts.camp.capturedAt)}` : ''}）。两源分开列，不合成一个分。</p>`;
    return `<div class="md-counters">
      <div class="md-ct-head"><b>五路对位</b><span>我方克对方 / 我方被克，证据分别来自 KPL 与营地；有记录就给数值</span></div>
      <div class="md-ct-list">${laneList || '<div class="md-ov-empty">五路对位没有配齐，克制不成立。</div>'}</div>
      ${notableList ? `<div class="md-ct-head"><b>重点交叉提示</b><span>非同路对位里有克制记录的组合，按营地指数与 KPL 场次排</span></div>
      <div class="md-ct-list">${notableList}</div>` : ''}
      ${foot}
    </div>`;
  })();
  const mdOvCounters = `<section class="section md-ov" id="match-ov-counters">
      <div class="section-heading"><div><h2>克制命中${evTag('hist')}</h2><p>KPL 自抓赛事的跨阵营对位与营地 App 英雄关系，两源分开列、不合成一个分；五路对位里查得到的逐条列，查不到的那几路合并成一句说明（营地表每个英雄只收录前 3 组关系，所以查不到≠不克制）</p></div></div>
      <div class="md-ov-pad">${ovCounters}</div>
    </section>`;
  const mdOvCombos = `<section class="section md-ov" id="match-ov-combos">
      <div class="section-heading"><div><h2>联动组合${evTag('hist')}</h2><p>双方阵容对到历史组合样本：几局、几胜、胜率、搭档加成，以及这套组合 KPL 见没见过；胜率不再因为场次少就不给，只用「可用 / 参考 / 观察 / 个例」标出能读多重</p></div></div>
      <div class="md-ov-pad">${ovCombos}</div>
    </section>`;
  const mdOvBroken = mdBroken ? `<section class="section md-ov" id="match-ov-broken">
      <div class="section-heading"><div><h2>组合得失${evTag('hist')}</h2><p>双方各有一批「想凑」的组合：阵容里凑齐了就是拿到（亮色），只差一格、那格被对面 ban 走或抢走就是被拆（那格灰掉并划斜杠）。候选＝他们自己打过的双人 / 三人（≥2 局）与 KPL 上本局英雄之间打过 ≥5 场的组合</p></div></div>
      <div class="md-ov-pad">${mdBroken}</div>
    </section>` : '';
  const mdCohesion = `<section class="section" id="match-cohesion"><div class="section-heading"><div><h2>中野辅与入侵${evTag('desc')}</h2><p>集结＝中/野/辅三人两两距离 ≤ 22.5（对角线 15%）且持续 ≥ 5 秒；入侵结果按团战账本的击杀与官方事件里的资源/建筑归因，不插值经济</p></div></div>
    ${m.positions ? mods.deep.cohesion(m.positions, m.players, own, m.duration, events, m.replay?.kills) : positionsEmpty}
  </section>`;
  /* 战斗拆成两块：团战（点地图看本波）与掉点（筛选/点选看单次），各自带分析。 */
  const battle = mods.deep.battle(m.positions, m.players, own, m.duration, points, m.replay?.deaths, m.replay?.fights);
  const mdFights = battle && battle.fights
    ? `<section class="section" id="match-battle"><div class="section-heading"><div><h2>团战${evTag('desc')}</h2><p>团战点大小＝参战人数，颜色＝该波击杀差（本队金 / 对手青）；点地图上的点看这一波的伤害、承伤与控制，下方为团战分析</p></div></div>${battle.fights}</section>`
    : battle ? ''
      : '<section class="section" id="match-battle"><div class="empty">这局没有团战或掉点数据（需要营地回放的 battles 段）</div></section>';
  const mdDeaths = battle && battle.deaths
    ? `<section class="section" id="match-deaths"><div class="section-heading"><div><h2>掉点${evTag('desc')}</h2><p>掉点＝一次阵亡；损失＝死前 120 秒经济差走势外推到复活时刻的差额（本队视角，负＝我方亏、正＝我方赚）。点圆点或列表固定选中，切换选手看他这局全部掉点</p></div></div>${battle.deaths}</section>`
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
    /* 每场团战的首杀击杀 = 该团战最早的一次击杀（与 firstKillerCamp 同源）。 */
    const firstOfFight = new Map();
    for (const k of rows) {
      if (!k.fight) continue;
      const cur = firstOfFight.get(k.fight);
      if (!cur || k.t < cur.t) firstOfFight.set(k.fight, k);
    }
    const firstKeys = new Set([...firstOfFight.values()].map(keyOf));
    /* 教练要的不是账本，是统计：每人切了几次 C、开了几次首杀。 */
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
       谁切了 C、谁首杀多由卡片高亮和数字表达。未知分路排最后。 */
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
    /* 团战结果：首杀方 + 该波击杀差。fights 缺失时只讲击杀账本，不编团战结果。 */
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
    const foeFightLosses = foeFights.filter((f) => fightKills(f, ownSide) < fightKills(f, foeSide)).length;
    const foeFirstDraws = foeFights.filter((f) => fightKills(f, ownSide) === fightKills(f, foeSide)).length;
    /* 团战节奏条：一个小方块＝一波团战；金/青 = 谁首杀，实心/空心 = 赢/输。 */
    const fightStrip = fights.length ? `<div class="md-fight-strip">
      <div class="md-fight-dots" role="img" aria-label="团战首杀与结果时间轴">${fights.map((f) => {
        const side = fightFirst(f);
        const ownTag = side === ownSide;
        const won = ownWonFight(f);
        const score = `${fightKills(f, ownSide)}:${fightKills(f, foeSide)}`;
        return `<i class="md-fight-dot ${ownTag ? 'is-own' : side ? 'is-foe' : 'is-unknown'}${won ? ' is-win' : ' is-loss'}" title="${esc(time(f.t))} · ${ownTag ? '我方' : side ? '对方' : '未记录'}首杀 · 击杀 ${score}"></i>`;
      }).join('')}</div>
      <div class="md-fight-legend"><span class="own">我方首杀</span><span class="foe">对方首杀</span><em>实心＝赢下，空心＝未赢（含平局）</em></div>
    </div>` : '';
    /* 首杀分析：首杀方和团战结果放在一句话里，后面才是五路分布。 */
    const topFirst = stats.slice().sort((a, b) => b.first - a.first)[0];
    const cutTargetCounts = new Map();
    for (const s of stats) for (const target of s.cutTargets) cutTargetCounts.set(target, (cutTargetCounts.get(target) || 0) + 1);
    const cutTargetText = [...cutTargetCounts.entries()].map(([target, n]) => `${target}${n > 1 ? ` ×${n}` : ''}`).join('、');
    const cutAllFirst = cutTotal > 0 && stats.every((s) => s.cutFirsts === s.cut);
    const parts = [];
    if (ownFights.length) {
      parts.push(`本局 ${fights.length} 波团战里我方首杀 ${ownFights.length} 波、赢下 ${ownFightWins} 波`);
      if (foeFights.length) parts.push(`对方首杀 ${foeFights.length} 波，我方 ${foeFights.length - foeFightLosses - foeFirstDraws} 胜 ${foeFightLosses} 负${foeFirstDraws ? ` ${foeFirstDraws} 平` : ''}`);
    } else if (firstTotal) {
      parts.push(`本局我方首杀 ${firstTotal} 次${firstRate !== null ? `，占我方击杀 ${pct(firstRate)}` : ''}`);
    }
    if (topFirst && topFirst.first) {
      parts.push(`${topFirst.p.position || '未知分路'}·${topFirst.p.label || topFirst.p.hero} 首杀 ${topFirst.first} 次最多`);
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
      : ownFightWins === ownFights.length && ownFights.length >= 2 ? '首杀全胜'
        : ownFirstRate >= 0.7 ? '首杀占优' : ownFirstRate >= 0.5 ? '首杀一般' : '首杀吃亏';
    const tiles = [
      ['首杀', `${firstTotal}<small>次</small>`, '',
        firstRate !== null ? `占我方击杀 ${pct(firstRate)}` : '按击杀账本统计'],
      ['首杀团战', ownFights.length ? `${ownFightWins}<i>/</i>${ownFights.length}` : '—', '赢下',
        ownFights.length ? `对方首杀 ${foeFights.length} 波` : '回放没有团战段'],
      ['被首杀', `${foeFights.length}`, '波',
        foeFights.length ? `我方 ${foeFights.length - foeFightLosses - foeFirstDraws} 胜 ${foeFightLosses} 负${foeFirstDraws ? ` ${foeFirstDraws} 平` : ''}` : '没有被对方首杀'],
      ['切C', `${cutTotal}`, '次',
        cutTotal ? (cutTargetText || '已形成切C') : '未形成切C'],
    ];
    const statCards = stats.map((s) => `<article class="md-cut-card${s.cut ? ' is-hot' : ''}">
      <header><span class="md-cut-lane">${esc(s.p.position || '未标注')}</span><b>${esc(s.p.label || s.p.hero)}</b>${portrait(s.p.hero || '', 'md-cut-face')}</header>
      <div class="md-cut-rows">
        <div class="md-cut-row is-first"><span class="md-cut-row-label">首杀</span><span class="md-cut-track"><i style="width:${Math.round(s.first / maxFirst * 100)}%"></i></span><b>${s.first}</b><small>${firstTotal ? Math.round(s.first / firstTotal * 100) + '%' : '—'}</small></div>
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
        <span class="md-kill-side"><em>${esc(k.killer)}</em>${first ? '<i class="md-kill-first">首杀</i>' : ''}<small>${esc(kl || '—')}</small></span>
        <span class="md-kill-arrow">→</span>
        <span class="md-kill-side"><em>${esc(k.victim)}</em><small>${esc(vl || '—')}</small></span>
        <em class="md-kill-cut">${cut ? '切C' : ''}</em>
      </div>`;
    };
    return `<section class="section" id="match-kills"><div class="section-heading"><div><h2>切C 与首杀${evTag('desc')}</h2><p>只算我方：切C＝我方对抗路 / 打野击杀对方中路或发育路；首杀＝该波团战里的第一次击杀。五路统计在上，首杀分析居中，逐条账本收在折叠区</p></div></div>
      <div class="md-cut-grid">${statCards}</div>
      <div class="md-viz-analysis md-bprev ${tone}">
        <div class="md-bprev-head"><b>首杀分析</b><span class="md-bprev-badge ${tone}">${badge}</span></div>
        <p class="md-bprev-lede">${parts.join('；')}。</p>
        <div class="md-bprev-stats">${tiles.map(([label, value, unit, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}<small>${unit}</small></span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
        ${fightStrip}
        <p class="md-bprev-thin">口径：首杀＝该波团战第一次击杀；切C＝对抗路 / 打野击杀对方中路、发育路；团战结果取官方回放 fights 的双方击杀数。</p>
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
    return `<section class="section" id="match-events"><div class="section-heading"><div><h2>事件详情${evTag('desc')}</h2><p>官方回放 keyEventArr：资源 / 推塔事件按时间排成卡片，参战者用分段占比；单位不可信时只列参战。下方附事件分析与营地复盘叙述</p></div></div>
      ${eventHtml}
      ${narrations.length ? `<details class="md-ev-narr"><summary>营地复盘叙述 <b>${narrations.length}</b> 条 <small>官方回放 adviceList</small></summary>${narrations.slice(0, 20).map((n) => `<p><span>${time(n.t)}</span>${esc(plainNarration(n.text))}</p>`).join('')}</details>` : ''}
      ${notes.length ? `<p class="md-ev-note">${notes.join('；')}。</p>` : ''}
    </section>`;
  })();
  /* 「阵线」（五人平均推进进度）2026-11-14 按赛训组反馈撤掉：
     把五个人压成一个百分比，教练看不出该点谁、该改哪一路；同页的
     「对位热区」「对位纵深」已经能逐路、逐人回答「压没压过去」。 */
  const mdSource = `<p class="md-source">数据来源：王者营地面板（十人结算 / 经济采样 / 分路派生卡片）、官方回放事件与营地逐秒位置 · ${esc(m.date || '')} ${esc(m.opponent ? '对阵 ' + m.opponent : '')}</p>`;
  /* 单局页原来一屏 8000px。2026-11-14：复盘大屏收敛成
     结论（脉搏在内）/ 总量 / 阵容 / BP 复盘（含赛事命中）/ 对位 / 组合 / 阶段 / 节点，
     用宽屏分栏排；十人 / 事件 / 地图 仍作为下钻页签。地址带页签，刷新后停在原处。 */
  const mdTab = ['review', 'data', 'events', 'map'].includes(current().tab) ? current().tab : 'review';
  const tabButton = (key, label, note) => `<button type="button" class="md-tab" data-md-tab="${key}"
    role="tab" aria-selected="${key === mdTab}"><b>${label}</b><small>${note}</small></button>`;
  const mdTabs = `<div class="md-tabs" role="tablist" aria-label="单局页签">
    ${tabButton('review', '复盘大屏', '结论 · BP · 对位')}
    ${tabButton('data', '十人数据', '对位 · 同队 · 营地卡片')}
    ${tabButton('events', '事件', '击杀 · 资源 · 团战')}
    ${tabButton('map', '地图', '热区 · 纵深')}
  </div>`;
  /* 图例放在页签下面：先告诉读者每个标签是什么，再进入数字。
     这是页面级的证据声明，不随筛选/回放到达而变化。 */
  const mdEvidenceLegend = `<div class="md-ev-legend" aria-label="证据类型说明">
    <span>证据类型</span>
    ${evTag('desc')}<small>只看这一局</small>
    ${evTag('hist')}<small>历史同口径频数</small>
    ${evTag('interval')}<small>带样本量的胜率</small>
    ${evTag('thin')}<small>只报计数</small>
  </div>`;
  /* 复盘大屏有 8 个区块，一屏放不下：给一条**吸顶的区块条**，点一下滚到那一块，
     滚动时自动高亮。教练复盘时的动作是「先看结论、再去对位、最后看组合」，
     没有这条只能一路滚，还容易滚过头。 */
  const anchorButton = (id, label) => `<button type="button" class="md-anchor" data-md-anchor="${id}">${label}</button>`;
  const mdAnchors = `<nav class="md-anchorbar" data-md-anchorbar aria-label="复盘大屏区块">
    ${anchorButton('match-verdict', '结论')}
    ${anchorButton('match-ov-lineup', '阵容')}
    ${anchorButton('match-ov-bp', 'BP')}
    ${anchorButton('match-ov-matchup', '对位')}
    ${anchorButton('match-ov-counters', '克制')}
    ${anchorButton('match-ov-combos', '组合')}
    ${anchorButton('match-ov-broken', '得失')}
    ${anchorButton('match-phases', '阶段')}
    ${anchorButton('match-timeline', '节点')}
  </nav>`;
  return `<div class="page md-page" data-md-tab-active="${mdTab}">${mdCrumb}${mdTabs}${mdEvidenceLegend}
    <div class="md-pane" data-md-pane="review">
      ${mdAnchors}
      ${mdHero}
      ${mdTotals}
      ${mdOvLineup}
      ${mdOvBp}
      ${mdOvMatchup}
      ${mdOvCounters}
      ${mdOvCombos}
      ${mdOvBroken}
      <div class="md-pane-row">${mdPhases}${mdTimeline}</div>
    </div>
    <div class="md-pane" data-md-pane="data">${mdGold10}${mdProfiles}${mdJungle}${mdCohesion}</div>
    <div class="md-pane" data-md-pane="events">${mdFights}${mdDeaths}${mdKills}${mdEventDetail}</div>
    <div class="md-pane" data-md-pane="map">${mdMap}</div>
    ${mdSource}
    </div>`;
}

const tour = createTour();

/* ── 按页加载的页面模块 ────────────────────────────────────────────────
   mods 里放的是构造好的模块对象，第一次进入对应路由时才 import + 构造。
   render() 保持同步：load() 会先 await ensureModules(路由) 再渲染，
   所以模板与事件处理里可以直接读 mods.xxx（未加载时用 ?. 兜底）。
   每个 import() 只发一次请求，失败会清掉缓存以便下次重试。 */
const mods = {};
const importJobs = new Map();

function importOnce(path) {
  let job = importJobs.get(path);
  if (!job) {
    job = import(path).catch((error) => { importJobs.delete(path); throw error; });
    importJobs.set(path, job);
  }
  return job;
}

/* 这些路由有自己的页面模块，其余（含详情页、采集页签）都走 features.js。 */
const OWN_MODULE_ROUTES = new Set(['overview', 'bp', 'match', 'cross', 'biggame', 'series-builder']);

async function ensureModules(name) {
  const jobs = [];
  if (!OWN_MODULE_ROUTES.has(name) && !mods.features) {
    jobs.push(importOnce('./features.js?v=20261117k').then(({ createFeatures }) => {
      mods.features = createFeatures({ esc, fmt, pct, diff, time, portrait, route, table,
        pageIntro, icon, microChart, gameAnchorBar, reload: () => load(true),
        currentQuery: () => query() });
    }));
  }
  if (name === 'overview' && !mods.brief) {
    /* 首页简报：模块自己请求 /api/briefing，外壳只给挂载点、筛选与跳转动作。 */
    jobs.push(importOnce('./period-brief.js').then(({ createPeriodBrief }) => {
      mods.brief = createPeriodBrief({
        esc, fmt, icon, API_BASE,
        getFilters: () => filters,
        openRange: () => filterDialog(),
        onEmptyLibrary: () => showNoDataDialog(),
        applyScope: ({ from, to }) => {
          filters = { ...filters, from, to };
          try { localStorage.setItem('training-rebuild-filters', JSON.stringify(filters)); } catch {}
        },
      });
    }));
  }
  if (name === 'bp' && !mods.bpLab) {
    jobs.push(importOnce('./bp-studio.js?v=20261118d4').then(({ createBpStudio }) => {
      mods.bpLab = createBpStudio({ esc, fmt, pct, icon, portrait, API_BASE });
    }));
  }
  if (name === 'match' && !mods.deep) {
    jobs.push(importOnce('./match-deep.js').then(({ createMatchDeep }) => {
      mods.deep = createMatchDeep({ esc, fmt, pct, diff, time, portrait,
        phases: phaseWindows, gpmOf, goldGrade });
      mods.deep.bindPanel(document);
    }));
  }
  if (name === 'cross' && !mods.crossPage) {
    jobs.push(importOnce('./cross-page.js').then(({ createCrossPage }) => {
      mods.crossPage = createCrossPage({ esc, fmt, pct, diff, time, portrait });
    }));
  }
  if (name === 'biggame' && !mods.bigGamePage) {
    jobs.push(importOnce('./biggame-page.js').then(({ createBigGamePage }) => {
      mods.bigGamePage = createBigGamePage({ esc, fmt, pct, diff, time, portrait });
    }));
  }
  if (name === 'series-builder' && !mods.seriesBuilder) {
    jobs.push(importOnce('./series-builder.js').then(({ createSeriesBuilder }) => {
      mods.seriesBuilder = createSeriesBuilder({ esc, fmt, diff, pct, time, portrait, route, icon });
    }));
  }
  if (name === 'combos' && !mods.comboQuery) {
    jobs.push(importOnce('./combo-query.js').then(({ createComboQuery }) => {
      mods.comboQuery = createComboQuery({
        esc, fmt, portrait, route, icon,
        getHeroes: () => Object.keys(metadata.icons || {}),
      });
      mods.comboQuery.bind();
    }));
  }
  await Promise.all(jobs);
}

/* KPL 组合全库（备赛工具）：数据拉一次缓存在模块级，英雄组合页渲染后挂进
   [data-kq-mount]。它是全库查询、与单局无关，所以不放复盘大屏。 */
let kplComboLibrary = null;
async function loadKplComboLibrary() {
  if (kplComboLibrary) return kplComboLibrary;
  const response = await fetch(API_BASE + '/api/v3/kpl/combos');
  if (!response.ok) throw new Error(`KPL 组合库读取失败：${response.status}`);
  kplComboLibrary = await response.json();
  return kplComboLibrary;
}
function mountComboQuery() {
  const mount = document.querySelector('[data-kq-mount]');
  if (!mount) return;
  mount.innerHTML = `<section class="section kq-section" id="kpl-combo-query">
      <div class="section-heading"><div><h2>KPL 组合查询</h2><p>全库组合（双人 / 三人 / 四人）按 1–4 个英雄筛选：几局几胜、最近谁用、使用时间；不限本局阵容，备赛查套路用</p></div></div>
      <div class="kq-pad">${mods.comboQuery.render(kplComboLibrary)}</div>
    </section>`;
  if (kplComboLibrary) return;
  loadKplComboLibrary().then(() => {
    if (!document.body.contains(mount)) return;
    mount.querySelector('.kq-pad').innerHTML = mods.comboQuery.render(kplComboLibrary);
  }).catch(() => {
    const pad = mount.querySelector('.kq-pad');
    if (pad) pad.innerHTML = '<div class="md-ov-empty">KPL 组合库读取失败，稍后刷新重试。</div>';
  });
}
/* 比赛脉搏交互需要原始序列，渲染时记下来，注入 DOM 后再绑定。 */
let pulseState = null;
const renderers = { overview: () => '<div class="page home pbr-home" data-pbr-root></div>',
  bp: () => '<div data-bp-lab-root></div>',
  matches: matchesPage, opponents: opponentsPage, players: playersPage,
  player: playerPage, tempo: tempoPage, sources: sourcesPage, match: matchPage,
  cross: () => mods.crossPage.render(),
  biggame: () => mods.bigGamePage.render(),
  'series-builder': () => '<div data-sb-root></div>' };
let lastRenderedRoute = '';
function render(r = current()) {
  workbenchUI?.updateRoute(r);
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
  secondary.querySelector('.secondary-nav').innerHTML = tabs.map(([key, label]) => `<a href="#${key}" ${key === activeTab || ({match:'matches',player:'players',playerdetail:'players',team:'teams',hero:'heroes',report:'reports'}[r.name] === key) ? 'aria-current="page"' : ''}>${label}</a>`).join('');
  document.querySelector('#content').innerHTML = mods.features?.has(r.name)
    ? mods.features.render(r.name, data, r.key) : renderers[r.name](data, r.key);
  mods.features?.afterRender();
  if (r.name === 'combos') {
    /* 英雄组合页尾的 KPL 组合查询（备赛工具，与单局无关）由这里挂载取数。 */
    mountComboQuery();
  }
  if (r.name === 'bp') {
    /* BP 概览自取数：单页十个内容区，外壳只给挂载点。 */
    mods.bpLab.mount(document.querySelector('[data-bp-lab-root]'));
  } else {
    mods.bpLab?.dispose();
  }
  if (r.name === 'overview') {
    /* 首页简报自取数：每次进入/重渲都由模块按当前周期与全局筛选重新请求，
       空库的首次使用引导在弹窗里（见 showNoDataDialog），首页不换向导。 */
    mods.brief.mount(document.querySelector('[data-pbr-root]'));
  } else {
    /* 切走时撤销简报请求，慢响应不再写回已经离开的页面。 */
    mods.brief?.dispose();
  }
  if (r.name === 'series-builder') {
    /* 系列赛编组中心自取数（同首页简报模式）。 */
    mods.seriesBuilder.mount(document.querySelector('[data-sb-root]'));
  } else {
    /* 切走时撤销请求并解除 document 级监听。 */
    mods.seriesBuilder?.dispose();
  }
  if (r.name === 'match' && pulseState) mods.deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
  if (r.name === 'match') mods.deep.bindHeat(document);
  if (r.name === 'match') mods.deep.bindBattle(document);
  bindAnchors();
  if (r.name === 'cross') mods.crossPage.bind(document);
  if (r.name === 'biggame') mods.bigGamePage.bind(document);
  updateMode();
  if (isNewRoute) window.scrollTo(0, 0);
  refreshInbox();
  tour.afterRender();
}

/* 复盘大屏区块条：隐藏没有对应区块的按钮（克制/组合在无数据时不渲染），
   再用 IntersectionObserver 跟着滚动高亮当前区块。每次重渲染重建，旧的先断开。 */
function bindAnchors() {
  mdAnchorObserver?.disconnect();
  mdAnchorObserver = null;
  const bar = document.querySelector('[data-md-anchorbar]');
  if (!bar) return;
  /* 顶栏（masthead）+ 二级导航的高度：联动的两段都是 sticky，区块条要贴在他们下面，
     否则会钻到顶栏底下看不见。量出来写进 CSS 变量，窄屏/字号变化自动跟着变。 */
  const headerHeight = ['header.masthead', '.secondary-wrap']
    .map((selector) => document.querySelector(selector)?.getBoundingClientRect().height || 0)
    .reduce((sum, value) => sum + value, 0);
  document.documentElement.style.setProperty('--md-anchor-top', `${Math.round(headerHeight)}px`);
  const buttons = [...bar.querySelectorAll('[data-md-anchor]')].filter((node) => {
    const target = document.getElementById(node.dataset.mdAnchor);
    node.hidden = !target;
    return Boolean(target);
  });
  if (!buttons.length || typeof IntersectionObserver !== 'function') return;
  const byId = new Map(buttons.map((node) => [node.dataset.mdAnchor, node]));
  mdAnchorObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!visible) return;
    const node = byId.get(visible.target.id);
    if (!node) return;
    buttons.forEach((item) => item.classList.toggle('is-on', item === node));
  }, { rootMargin: '-96px 0px -55% 0px', threshold: 0 });
  [...byId.keys()].forEach((id) => {
    const target = document.getElementById(id);
    if (target) mdAnchorObserver.observe(target);
  });
}

/* 跨局分析以「大场」为单位，由 crossPage 自己取 /api/cross/series-summary；
   不再在进入页面时拉全量对局向量。 */

async function load(fresh = false) {
  const generation = ++loadGeneration;
  request?.abort();
  request = new AbortController();
  const currentRequest = request;
  const r = current();
  workbenchUI?.updateRoute(r);
  const routeKey = routeKeyOf(r);
  /* 换页归零重试计数；手动刷新也给一次全新的重试机会。 */
  if (routeKey !== loadRoute) { loadRoute = routeKey; retryByRoute.clear(); }
  if (fresh) retryByRoute.delete(routeKey);
  const stale = () => isStale(generation, routeKey);
  /* 离线期间：不逐页发请求，直接渲染占位；探活成功后会自动 load() 当前页。 */
  if (offlineSince) { renderOffline(r); return; }
  /* 先把这一页需要的页面模块按需取回来（首次访问该页会有一个 import 请求，
     之后都走缓存）。取不到时继续渲染骨架，不把整页拖死。 */
  try {
    await ensureModules(r.name);
  } catch { /* 模块加载失败按无数据处理，下面的渲染走空态 */ }
  if (stale()) return;
  if (r.name === 'bp') {
    data = null;
    /* BP 页自取数；头像目录单独补一次，到了就重绘，不让 BP 页等完整 metadata。 */
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        mods.bpLab?.rerender();
      }).catch(() => { /* 图标缺失时保留文字占位 */ });
    }
    render(r);
    return;
  }
  /* 系列赛编组中心自取数（series-builder.js）：不走通用取数管道，
     接口失败也不会被这里的静默重试/整页报错吃掉。 */
  if (r.name === 'series-builder') {
    data = null;
    /* 图标目录与编组数据并行取：编组页只需要头像，走 /api/metadata/icons
       轻量接口，不再为一份图标目录等仓库快照重建（冷启动约 3 秒）。
       图标到了补一次头像；其它页需要完整 metadata 时会重新取。 */
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        if (current().name === 'series-builder') mods.seriesBuilder?.rerender();
      }).catch(() => { /* 图标目录缺失时保留文字占位 */ });
    }
    render(r);
    return;
  }
  /* 首页简报自取数（period-brief.js）：不走 /api/overview，
     这样切周期只重取简报，接口失败也不会被这里的静默重试/整页报错吃掉。 */
  if (r.name === 'overview') {
    data = null;
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata').then((meta) => {
        if (stale()) return;
        metadata = meta;
        updateMode();
      }).catch(() => {});
    }
    render(r);
    return;
  }
  const endpoint = r.name === 'players' ? 'v3/players/board'
    : ({ match: 'matches/', player: 'players/', opponents: 'studio/teams', cross: 'matches' }[r.name] || r.name) + (['match','player'].includes(r.name) ? encodeURIComponent(r.key) : '');
  document.querySelector('#content').innerHTML = r.name === 'team'
    ? teamSkeleton()
    : loadingSkeleton();
  /* 详情路由缺 ID（直接输入 #session / #match 等）：别去请求一个空 key，
     那会 404 后落到"暂时读不到数据"的死循环。给出明确的返回入口。 */
  /* 「选手认领」是整页不是详情页：它没有单条 ID，缺 key 也应该正常渲染。 */
  const DETAIL_ROUTES = ['match', 'player', 'playerdetail', 'hero', 'team', 'session', 'competition', 'report'];
  if (DETAIL_ROUTES.includes(r.name) && !r.key) {
    const section = sectionFor(r.name);
    const label = labels[r.name] || '条目';
    document.querySelector('#content').innerHTML = `<div class="page"><section class="section"><div class="offline-card">
      <b>还没有选定${esc(label)}</b>
      <p>这个页面需要一个具体的${esc(label)} ID。请从列表页打开，或先返回上一级。</p>
      <div class="offline-actions"><a class="control" href="#${esc(section)}">返回${esc(labels[section] || '列表')}</a></div>
    </div></section></div>`;
    return;
  }
  try {
    /* 跨局分析由页面自己取 series-summary；不必先拉对局列表。 */
    const pageData = (r.name === 'cross' || r.name === 'biggame') ? Promise.resolve({}) : (mods.features?.has(r.name) ? mods.features.load(r.name, r.key, currentRequest.signal, fresh) : get(endpoint, fresh));
    const [result, meta] = await Promise.all([pageData, (metadata.icons && !metadata.iconsOnly) ? Promise.resolve(metadata) : get('metadata')]);
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
          const matchupResponse = await fetch(API_BASE + '/api/v3/facts/lane_matchup', { signal: currentRequest.signal });
          if (matchupResponse.ok) data.laneMatchup = await matchupResponse.json();
        } catch { /* 对位压制历史失败不影响主页面 */ }
      } catch {
        if (stale()) return;
        data.replayStatus = 'error';
      }
      if (!stale()) {
        const temp=document.createElement('div');temp.innerHTML=matchPage(data);
        /* 单局页拆成页签后，后到的区块必须插回它自己的页签，
           否则「事件」页里的击杀账本会被塞进隐藏的「地图」页。
           这里不再写死 id 清单：按 temp 里实际的 `[data-md-pane] section[id]` 遍历，
           新加的区块（如「打野并线」）自动跟着走；结论卡 #match-verdict 不是
           section.section，但脉搏的事件标记要等回放，所以选择器放宽到所有带 id 的
           section，整卡替换。 */
        const paneSections = '.md-pane section[id]';
        const incoming = [...temp.querySelectorAll(paneSections)];
        /* 手填的「10 分钟经济」靠输入框活着，不参与异步替换，免得冲掉正在输入的数值。 */
        const keepInPlace = new Set(['match-gold10']);
        const keep = new Set(incoming.map((node) => node.id));
        for (const updated of incoming) {
          const existing = document.getElementById(updated.id);
          if (existing && keepInPlace.has(updated.id)) continue;
          if (existing) { existing.replaceWith(updated); continue; }
          const paneKey = updated.closest('[data-md-pane]')?.dataset.mdPane || 'review';
          const pane = document.querySelector(`[data-md-pane="${paneKey}"]`);
          if (pane) pane.append(updated);
        }
        /* 新版不再渲染的区块（首屏的「没有团战数据」占位等）直接撤掉 */
        for (const old of document.querySelectorAll(paneSections)) {
          if (!keep.has(old.id)) old.remove();
        }
        if (pulseState) mods.deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
        mods.deep.bindHeat(document);
        mods.deep.bindBattle(document);
      }
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
  const dialog = dialogFor();
  const team = (metadata && metadata.teamName) || '';
  dialog.innerHTML = `<form id="name-form"><div class="dialog-head"><div><h2>命名并归队</h2><p>把「${esc(label)}」归到一名选手和一支战队；保存后这些记录并入该选手。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <div class="date-fields"><label>对局昵称<input value="${esc(label)}" readonly></label><label>选手名称<input name="name" required maxlength="40" value="${esc(label)}"></label></div>
      <div class="date-fields"><label>所属战队<input name="team" maxlength="40" value="${esc(team)}" placeholder="默认本队"></label></div>
      <fieldset class="sx-pos-field"><legend>位置（可多选，第一个勾的是主位置）</legend><div class="sx-pos-chips">${['对抗路', '打野', '中路', '发育路', '游走'].map((x) => `<label class="sx-pos-chip"><input type="checkbox" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">保存并归队</button></div></form>`;
  dialog.showModal();
}

/* 取共享弹窗容器：切回普通弹窗时去掉「首次使用引导」用的加宽样式。 */
function dialogFor() {
  const element = document.querySelector('#filters');
  element?.classList.remove('is-wide');
  return element;
}

function filterDialog() {
  const dialog = dialogFor();
  dialog.innerHTML = `<form id="filter-form"><div class="dialog-head"><div><h2>数据范围</h2><p>选择日期、来源与样本。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><div class="date-fields"><label>开始日期<input type="date" name="from" value="${esc(filters.from)}"></label>
    <label>结束日期<input type="date" name="to" value="${esc(filters.to)}"></label></div><fieldset><legend>数据来源</legend>
    ${Object.entries(sourceName).map(([key, text]) => `<label class="check"><input type="checkbox" name="source" value="${key}" ${filters.source.includes(key) ? 'checked' : ''}>${text}</label>`).join('')}</fieldset>
    <label class="check"><input type="checkbox" name="validation" ${filters.validation ? 'checked' : ''}>包含验证数据</label><p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="reset">恢复默认</button><button class="primary" type="submit">应用范围</button></div></form>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
}

function clientMissingDialog() {
  const dialog = dialogFor();
  dialog.innerHTML = `<div class="dialog-head"><div><h2>没有检测到客户端</h2>
    <p>可能还没有安装，或系统没有注册 kpl-client://open 协议。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><p>下载安装后，再点「打开客户端」即可从这里直接进入客户端；当前页面会自动带过去。</p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">稍后</button>
      <a class="primary" href="${CLIENT_DOWNLOAD_URL}" target="_blank" rel="noopener">去下载客户端</a></div>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
}

/* 对局筛选浮层挂在 body 上：列表重绘不会把它一起换掉，连勾几项也不会关。
   用 document 级委托处理打开、移除、清空与点外关闭。 */
document.addEventListener('click', (event) => {
  /* 「复制结论」：把 data-md-copy 里的纯文本写进剪贴板，按钮临时变「已复制」。
     clipboard API 在 http://127.0.0.1 可用；万一被浏览器拒绝，退回 textarea + execCommand。 */
  const copyBtn = event.target.closest('[data-md-copy]');
  if (copyBtn) {
    event.preventDefault();
    const text = copyBtn.dataset.mdCopy || '';
    const label = copyBtn.textContent;
    const done = () => {
      copyBtn.textContent = '已复制';
      copyBtn.classList.add('is-done');
      setTimeout(() => { copyBtn.textContent = label; copyBtn.classList.remove('is-done'); }, 1600);
    };
    const fallback = () => {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try { document.execCommand('copy'); done(); } catch { /* 复制失败就保持原样 */ }
      area.remove();
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fallback);
    } else {
      fallback();
    }
    return;
  }
  const trigger = event.target.closest('[data-mf-open]');
  if (trigger) {
    event.preventDefault();
    openMatchFilter(trigger.dataset.mfOpen);
    return;
  }
  const clear = event.target.closest('[data-mf-clear]');
  if (clear) {
    event.preventDefault();
    /* 搜索词不在 matchFilters 里，清除筛选时要一起清掉，否则计数和列表会打架。 */
    view.search = '';
    const search = document.querySelector('.mf-search input');
    if (search) search.value = '';
    clearMatchFilter(null);
    return;
  }
  const reset = event.target.closest('[data-mf-reset]');
  if (reset) {
    event.preventDefault();
    clearMatchFilter(reset.dataset.mfReset);
    return;
  }
  const remove = event.target.closest('[data-mf-remove]');
  if (remove) {
    event.preventDefault();
    const kind = remove.dataset.mfRemove;
    const value = remove.dataset.mfValue || '';
    if (kind === 'range' || value === '*') clearMatchFilter(kind);
    else updateMatchFilter(kind, value, false);
    return;
  }
  const bulk = event.target.closest('[data-mf-bulk]');
  if (bulk) {
    event.preventDefault();
    closeMatchFilter();
    bulkOpponentDialog();
    return;
  }
  if (!event.target.closest('.mf-pop') && document.querySelector('.mf-pop')) closeMatchFilter();
});

document.addEventListener('input', (event) => {
  const box = event.target.closest('[data-mf-q]');
  if (!box) return;
  const pop = box.closest('.mf-pop');
  const keyword = box.value.trim().toLowerCase();
  pop?.querySelectorAll('[data-mf-list] .mf-opt, [data-mf-list] .mf-hero').forEach((row) => {
    row.hidden = Boolean(keyword) && !row.textContent.toLowerCase().includes(keyword);
  });
});

document.addEventListener('change', (event) => {
  const opt = event.target.closest('[data-mf-opt]');
  if (opt) {
    updateMatchFilter(opt.dataset.mfOpt, opt.dataset.mfValue, opt.checked);
    return;
  }
  const cal = event.target.closest('[data-mf-cal]');
  if (!cal) return;
  const mf = matchFilters();
  mf[cal.dataset.mfCal] = cal.value || '';
  if (cal.value) mf.days = [];
  refreshMatchResults();
  const pop = cal.closest('.mf-pop');
  if (pop) {
    const temp = document.createElement('div');
    temp.innerHTML = matchFilterPanel('day');
    pop.innerHTML = temp.innerHTML;
  }
});

/* 键盘导航：浮层打开时 ↑↓ 在选项间移动、空格勾选、Enter 收起；
   浮层关闭时（对局档案页）↑↓/J/K 选局、Enter 进复盘。全程不碰鼠标。 */
let mfKbIndex = -1;
let matchKbIndex = -1;

function mfKbItems(pop) {
  return [...pop.querySelectorAll('[data-mf-list] .mf-opt, [data-mf-list] .mf-hero')].filter((el) => !el.hidden);
}

function paintMfKb(pop) {
  pop.querySelectorAll('.mf-kb').forEach((el) => el.classList.remove('mf-kb'));
  const item = mfKbItems(pop)[mfKbIndex];
  if (item) {
    item.classList.add('mf-kb');
    item.scrollIntoView({ block: 'nearest' });
  }
}

function matchKbRows() {
  return [...document.querySelectorAll('.match-list .match-row')];
}

function paintMatchKb(rows) {
  document.querySelectorAll('.match-row.kb-active').forEach((el) => el.classList.remove('kb-active'));
  const row = rows[matchKbIndex];
  if (row) {
    const folded = row.closest('details');
    if (folded && !folded.open) folded.open = true;
    row.classList.add('kb-active');
    row.scrollIntoView({ block: 'nearest' });
  }
}

document.addEventListener('keydown', (event) => {
  const pop = document.querySelector('.mf-pop');
  if (pop) {
    if (event.key === 'Escape' || event.key === 'Enter') {
      event.preventDefault();
      mfKbIndex = -1;
      closeMatchFilter();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const count = mfKbItems(pop).length;
      if (!count) return;
      mfKbIndex = event.key === 'ArrowDown' ? (mfKbIndex + 1) % count : (mfKbIndex <= 0 ? count - 1 : mfKbIndex - 1);
      paintMfKb(pop);
      return;
    }
    /* 空格勾选活动项——↑↓ 移过之后教练按空格就是要勾选；
       还没动过方向键时（无活动项）空格照常打字，不拦。 */
    if (event.key === ' ') {
      const item = mfKbItems(pop)[mfKbIndex];
      if (item) {
        event.preventDefault();
        item.querySelector('input')?.click();
      }
    }
    return;
  }
  mfKbIndex = -1;
  if (current().name !== 'matches') { matchKbIndex = -1; return; }
  if (event.target.closest('input, textarea, select')) return;
  const down = event.key === 'ArrowDown' || event.key === 'j';
  const up = event.key === 'ArrowUp' || event.key === 'k';
  if (!down && !up && event.key !== 'Enter') return;
  const rows = matchKbRows();
  if (!rows.length) return;
  if (event.key === 'Enter') {
    const row = rows[matchKbIndex];
    if (row) {
      event.preventDefault();
      location.hash = row.getAttribute('href').slice(1);
    }
    return;
  }
  event.preventDefault();
  matchKbIndex = down ? Math.min(rows.length - 1, matchKbIndex + 1) : Math.max(0, matchKbIndex - 1);
  paintMatchKb(rows);
});

app.addEventListener('click', (event) => {
  /* 点「当前就在这一页」的导航（例如已经在首页再点「首页」）时 hash 不变、不会触发
     hashchange：这里手动重载当前页，避免看起来点了没反应、回不到首页。 */
  const selfLink = event.target.closest('a[href^="#"]');
  if (selfLink && location.hash && selfLink.getAttribute('href') === location.hash) {
    event.preventDefault();
    emptyDialogDismissed = '';
    load(true);
    return;
  }
  const editOpponent = event.target.closest('[data-match-edit]');
  if (editOpponent) {
    event.preventDefault();
    event.stopPropagation();
    opponentDialog(editOpponent.dataset.matchEdit, editOpponent.dataset.opponent || '', editOpponent.dataset.teamId || '');
    return;
  }
  if (event.target.closest('[data-bp-order]')) {
    event.preventDefault();
    openBpOrderDialog();
    return;
  }
  if (mods.features?.click(event)) return;
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
  /* 复盘大屏区块条：点一下滚到那一块（吸顶条会把标题挡住，靠 CSS 的
     scroll-margin-top 让位）。高亮由 bindAnchors 的 IntersectionObserver 管。 */
  const mdAnchorHit = event.target.closest('[data-md-anchor]');
  if (mdAnchorHit) {
    const target = document.getElementById(mdAnchorHit.dataset.mdAnchor);
    if (target) {
      event.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      mdAnchorHit.closest('[data-md-anchorbar]')?.querySelectorAll('[data-md-anchor]')
        .forEach((node) => node.classList.toggle('is-on', node === mdAnchorHit));
    }
    return;
  }
  /* 页签按钮与复盘大屏里的跳转按钮（data-md-jump）共用一套切换逻辑：
     只切显示，不重新取数；地址用 replaceState 同步，刷新后停在原页签。 */
  const mdTabHit = event.target.closest('[data-md-tab]') || event.target.closest('[data-md-jump]');
  if (mdTabHit) {
    const page = mdTabHit.closest('.md-page');
    const key = mdTabHit.dataset.mdTab || mdTabHit.dataset.mdJump;
    if (!page || !key) return;
    page.dataset.mdTabActive = key;
    page.querySelectorAll('[data-md-tab]').forEach((node) => {
      node.setAttribute('aria-selected', String(node.dataset.mdTab === key));
    });
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
      /* 离开演示就把演示实例关掉：它是隔离的第二个进程（端口 = 主端口 +7），
         留着会一直占着端口、让任务管理器里多一个 python。演示数据可丢，直接关。
         keepalive 让请求在跳转后仍能送达，不等它回包。 */
      try { fetch('/api/shutdown', {method:'POST', cache:'no-store', keepalive:true}); } catch {}
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
  if (action === 'theme') { theme = theme === 'light' ? 'dark' : 'light'; try { localStorage.setItem('training-rebuild-theme', theme); } catch {} applyTheme(); }
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
  if (action === 'clear-scope') {
    filters = { ...filters, from: '', to: '' };
    try { localStorage.setItem('training-rebuild-filters', JSON.stringify(filters)); } catch {}
    emptyDialogDismissed = '';
    const dlg = document.querySelector('#filters');
    if (dlg && dlg.open) dlg.close();
    load(true);
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
    workbenchUI.toggleMenu();
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
  if (mods.features?.submit(event)) return;
  if (event.target.id === 'bulk-opponent-form') {
    event.preventDefault();
    const name = String(new FormData(event.target).get('opponent') || '').trim();
    const error = !name ? '请填写对手队名。' : '';
    event.target.querySelector('.filter-error').textContent = error;
    if (error) return;
    const keys = unlabelledTargets().map((m) => m.key);
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '保存中…';
    fetch(API_BASE + '/api/v3/match-meta-bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keys, opponent: name }),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      document.querySelector('#filters').close();
      /* 赋完名「对手未标注」这一组已经空了，自动摘掉，免得列表突然变 0 场。 */
      const mf = matchFilters();
      if (mf.opponents.includes(MF_NONE)) mf.opponents = mf.opponents.filter((x) => x !== MF_NONE);
      await load(true);
    }).catch((err) => {
      button.disabled = false;
      button.textContent = '保存';
      event.target.querySelector('.filter-error').textContent = err.message;
    });
    return;
  }
  if (event.target.id === 'opponent-form') {
    event.preventDefault();
    const form = new FormData(event.target);
    const name = String(form.get('opponent') || '').trim();
    const teamId = event.target.dataset.teamId || '';
    const button = event.target.querySelector('button[type=submit]');
    if (teamId && !name) {
      event.target.querySelector('.filter-error').textContent = '请填写战队名称。';
      return;
    }
    button.disabled = true;
    /* 归到战队的局：改的是战队分析里的队名，一次改动全站同步。
       没有营地面板的局仍是逐局补录，保持原行为。 */
    const url = teamId ? API_BASE + '/api/studio/teams/rename'
      : API_BASE + '/api/v3/match-meta/' + encodeURIComponent(event.target.dataset.key);
    const payload = teamId ? { id: teamId, name } : { opponent: name };
    fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      document.querySelector('#filters')?.close();
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
    const positions = form.getAll('position').map((value) => String(value || '')).filter(Boolean);
    const payload = { label: event.target.querySelector('input[readonly]').value, name: form.get('name'), positions, position: positions[0] || '', team: form.get('team') };
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
  mods.features?.change(event);
  if (event.target.name !== 'search' || !renderers[current().name]) return;
  view.search = event.target.value;
  syncMatchHash();
  const results = document.querySelector('[data-results]');
  const temp = document.createElement('div');
  const r = current();
  temp.innerHTML = renderers[r.name](data, r.key);
  results.innerHTML = temp.querySelector('[data-results]').innerHTML;
  const count=document.querySelector('[data-result-count]');if(count)count.innerHTML=temp.querySelector('[data-result-count]')?.innerHTML||'';
  const summary=document.querySelector('.match-overview');if(summary)summary.innerHTML=temp.querySelector('.match-overview')?.innerHTML||'';
  const bar=document.querySelector('[data-filter-bar]');if(bar)bar.outerHTML=temp.querySelector('[data-filter-bar]')?.outerHTML||'';
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
      const lane = el.dataset.gold10Lane
        || el.closest('.md-g10-row')?.querySelector('.md-g10-lane')?.textContent || '';
      const grade = el.value === '' ? null : gold10Grade(lane, Number(el.value), el.dataset.gold10Hero);
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
app.addEventListener('change', (event) => mods.features?.change(event));

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
  workbenchUI.closeMenu();
  window.scrollTo(0,0);
  load();
});
document.querySelector('.skip').addEventListener('click', (event) => { event.preventDefault(); document.querySelector('#content').focus(); });
shell();
/* 关掉空数据弹窗后不要立刻再弹：记住当前筛选范围，等范围变化再提示。 */
document.querySelector('#filters')?.addEventListener('close', () => { emptyDialogDismissed = scopeKey(); });
initUpdateBanner({ API_BASE });
load();
