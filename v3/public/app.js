import { normalizedCamp, sampleNear, teamTotal, economyDirection, eventSide, laneRealisation } from './match-recap-metrics.js';
import { equipIcons } from './equipment-icons.js';
import { glyph, deco } from './ui-icons.js';
import { featureSections } from './feature-sections.js?v=20261123nav';
import { createWorkbenchUI, loadingSkeleton } from './workbench-ui.js';
import { createChecklist } from './tour.js?v=20261126tour3';
import { initUpdateBanner } from './update-banner.js';
import { diagnosticBlock, bindDiagnosticCopy, errorEntry } from './diagnostics.js';
/* 单局标签：自挂载（盯着 #content 里的 .tagrow 占位），首页 / 档案 / 单局页共用。
   档案库还要读同一份标签数据做组合筛选、搜索与批量管理，不能再自己拉一套接口。 */
import { tagsOf, tagNotesOf, vocabulary, tagsReady, reloadTags } from './match-tags.js';
/* 重点关注：给每局挂「关注 + 原因 + 说明」的统一入口，档案行里也能直接标。 */
import './focus-matches.js';
/* 分路图标来自 KPL 总决赛 SVG 包；用目录 URL 拼路径，文档根下的相对路径在本站会 404。 */
const KPL_SVG = new URL('./kpl-svg/', import.meta.url).href;
const LANE_SVG = { '对抗路': 'clash', '打野': 'jungle', '中路': 'mid', '发育路': 'farm', '游走': 'roam' };
const ARCHIVE_SORTS = [
  { key: 'time', label: '时间', hint: '按日期与开始时间倒序' },
  { key: 'duration', label: '时长', hint: '每个日期内，打得久的排前面' },
  { key: 'winrate', label: '对手胜率', hint: '每个日期内，按当前结果里该对手的胜率排序' },
  { key: 'opponent', label: '对手', hint: '每个日期内，按对手队名排序' },
];
const ARCHIVE_SORT_KEY = 'training-archive-sort';
const ARCHIVE_SCROLL_KEY = 'training-archive-scroll';
const ARCHIVE_COLLAPSED_KEY = 'training-archive-collapsed';
const zhCollator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });
/* 页面模块不再静态 import（见 ensureModules）：过去一进工作台就要把所有页面模块
   解析一遍——31 个文件 / 1.9 MB，光解析就占掉首屏 300 毫秒左右，而其中绝大多数
   属于用户还没打开过的页面。 */

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const CLIENT_DOWNLOAD_URL = 'https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest';
const app = document.querySelector('#app');
/* 侧边栏按 4.0 赛事驱动流程排（2026-11-24 定稿）：
   工作台：首页 → 赛事（周期先行）→ 本队（身份预建）→ 对方战队 → 采集（自动分队/人工匹配）→ 系列赛编组（最后编组）；
   选手档案并入「本队」页的二级页签；其余是赛训复盘与情报分析。 */
const nav = [
  ['overview', '首页'], ['competitions', '赛事'], ['team-profile', '本队'],
  ['opponents', '对方战队'], ['ingest', '采集'], ['matching', '匹配与编组'],
  ['match-notes', '赛训'], ['matches', '单局分析'], ['biggame', '大场分析'], ['cross', '跨场分析'],
  ['teams', '战队分析'], ['players', '选手分析'], ['heroes', '英雄分析'], ['bp', 'BP 工作台'],
  ['rules', '规则中心'], ['snapshot-center', '快照中心'],
  ['sources', '数据源展示'], ['docs', '文档'], ['source-health', '外部数据源'],
  ['ingest', '采集'], ['competitions', '赛事'], ['series-builder', '系列赛编组'],
  ['matches', '单局分析'], ['biggame', '大场分析'], ['cross', '跨场分析'],
  ['teams', '战队'], ['players', '选手'], ['heroes', '英雄'], ['bp', 'BP 工作台'],
  ['rules', '规则中心'], ['snapshot-center', '快照中心'],
  ['sources', '数据源展示'], ['docs', '文档'], ['source-health', '外部数据源'],
];
const labels = Object.fromEntries(nav);
for (const pages of Object.values(featureSections)) for (const [key, label] of pages) labels[key] = label;
Object.assign(labels, { biggame: '大场分析', cross: '跨场分析', matching: '匹配与编组', 'series-builder': '系列赛编组', rules: '规则中心', 'match-notes': '赛训', 'team-profile': '本队', profiles: '本队选手档案', match: '对局复盘', player: '选手详情', playerdetail: '选手个人页', team: '战队详情', hero: '英雄详情', report: '分析报告', review: '缺失值审查', shots: '截图 OCR', videos: '录屏', replays: '回放', imported: '已采集对局', capture: '导入表格', economy: '经济转折', tempo: '节奏分析', opponents: '对方战队', teams: '战队分析', players: '选手分析', heroes: '英雄分析', teamtraining: '交手记录', ownership: '对手归属', pending: '待确认', session: '训练课', competitions: '赛事', competition: '赛事详情', weekly: '训练周报', 'snapshot-center': '快照中心' });
function sectionFor(name) {
  const detail = { match: 'matches', player: 'players', playerdetail: 'players', team: 'teams', hero: 'heroes', report: 'reports', review: 'ingest', shots: 'ingest', videos: 'ingest', replays: 'ingest', imported: 'ingest', capture: 'ingest', economy: 'matches', tempo: 'matches', opponents: 'opponents', ownership: 'setup', pending: 'setup', effect: 'setup', session: 'setup', competition: 'competitions', weekly: 'setup' }[name] || name;
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
  trash: '<path d="M4 7h16M9 7V4.5h6V7m3 0-.8 12.5a1.5 1.5 0 0 1-1.5 1.4H7.3a1.5 1.5 0 0 1-1.5-1.4L5 7m5 4v6m4-6v6"/>',
  edit: '<path d="M4.5 19.5h3.6L18.6 9a2.55 2.55 0 1 0-3.6-3.6L4.5 15.9z"/><path d="m14.2 6.2 3.6 3.6"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 4 4"/>',
  overview: '<path d="M3.5 10.5 12 3l8.5 7.5V20H14v-6h-4v6H3.5z"/>',
  matches: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  /* 赛训：哨子（训练课），与「单局分析」的文档图标区分开。 */
  'match-notes': '<circle cx="10" cy="14" r="5.5"/><path d="M15.3 11.3 20 9v6l-4.7-2.3"/><path d="M8.5 9 8 4.5h4l-.5 4.5"/>',
  teams: '<path d="M12 3 4 6.5v5.8c0 4.3 3.1 7.1 8 8.7 4.9-1.6 8-4.4 8-8.7V6.5z"/><path d="m8.8 12 2 2 4.4-4.4"/>',
  players: '<circle cx="9" cy="8" r="3"/><path d="M3.5 20v-1.5a5.5 5.5 0 0 1 11 0V20M16 5a3 3 0 0 1 0 6m1 4a4.5 4.5 0 0 1 3.5 4.4V20"/>',
  'team-profile': '<path d="M12 3 4.5 6v5.6c0 4.2 3 7.1 7.5 8.4 4.5-1.3 7.5-4.2 7.5-8.4V6z"/><path d="m12 7.6 1.35 2.75 3.03.44-2.19 2.14.52 3.02L12 14.62l-2.71 1.43.52-3.02-2.19-2.14 3.03-.44z"/>',
  profiles: '<rect x="3.5" y="5" width="13" height="11" rx="2"/><circle cx="8.5" cy="9" r="1.7"/><path d="M5.6 14c.4-1.9 1.6-2.8 2.9-2.8s2.5.9 2.9 2.8"/><path d="M8 20h9a2 2 0 0 0 2-2V8.5a2 2 0 0 0-2-2h-1.2"/>',
  heroes: '<path d="m12 3 2.4 5.2 5.6.7-4.1 3.9 1 5.6-4.9-2.7-4.9 2.7 1-5.6L4 8.9l5.6-.7z"/>',
  bp: '<path d="m12 3.5 7.5 4.4-2.8 12.3H7.3L4.5 7.9zM4.5 7.9 12 13l7.5-5.1M12 13v7.2"/>',
  space: '<path d="M4 4v16h16M7 16l4-5 3.5 2.5L20 6"/><circle cx="20" cy="6" r="1"/>',
  setup: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h3m-3 3h7"/>',
  seriesbuilder: '<rect x="3.5" y="4.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="4.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  biggame: '<path d="M8 4h8v4a4 4 0 0 1-8 0z"/><path d="M8 5H5a3 3 0 0 0 3 4M16 5h3a3 3 0 0 1-3 4M12 12v4m-3 4h6"/>',
  cross: '<path d="M4 17l4-6 4 3 5-7"/><path d="M13.5 7H17v3.5"/>',
  opponents: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  rules: '<path d="M5 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H5z"/><path d="M19 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
  'snapshot-center': '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9h17M7.5 4v5m9-5v5M8 13h8M8 16.5h5"/>',
  competitions: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h3m-3 3h7"/>',
  sources: '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  'source-health': '<path d="M6.5 17.5a4.5 4.5 0 0 1-.6-8.96 6 6 0 0 1 11.6 1.2 3.8 3.8 0 0 1-.5 7.76"/><path d="M12 10.5v7m-2.5-2.5L12 17.5l2.5-2.5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.7 2.7 0 0 1 5.2 1c0 1.8-2.7 2.2-2.7 4M12 17.4h.01"/>',
  docs: '<path d="M5 4.5h9.5L19 9v10.5H5z"/><path d="M14 4.5V9h5M8 12h8M8 15.5h8"/>',
  inbox: '<path d="M4 5h16v14H4z"/><path d="M4 13h4l2 3h4l2-3h4"/>',
  demo: '<path d="m8 5 11 7-11 7z"/>',
  camera: '<path d="M4 8h3l1.7-2.2h6.6L17 8h3v11H4z"/><circle cx="12" cy="13.2" r="3.4"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4m10 0h4M3 15h4m10 0h4"/>',
  client: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  ingest: '<path d="M12 3v11m-4-4 4 4 4-4"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  download: '<path d="M12 3v11m-4-4 4 4 4-4"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  upload: '<path d="M12 16V5m-4 4 4-4 4 4"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
};
const icon = (name) => `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[name] || ''}</svg>`;
/* 页内标题用的语义图标：与侧栏共用一套内联 SVG，currentColor 自动跟随青绿主题，
   不套用会被主题隐藏的金色装饰件。 */
const HEADING_ICONS = {
  overview: 'chart', competitions: 'calendar', 'team-profile': 'team-profile',
  opponents: 'opponents', ingest: 'ingest', matching: 'seriesbuilder',
  'match-notes': 'match-notes', matches: 'matches', biggame: 'biggame',
  cross: 'cross', teams: 'teams', players: 'players', heroes: 'heroes',
  bp: 'bp', rules: 'rules', 'snapshot-center': 'snapshot-center',
  sources: 'sources', 'source-health': 'source-health', docs: 'docs',
};
/* 给页面 H1 与侧栏分组加统一的图标锚点；纯装饰，不改盒模型与文字内容。
   带 data-deco 的节点直接跳过，重绘后不会叠图标。 */
function decorateHeadings(routeName) {
  const h1 = document.querySelector('#content h1:not([data-deco])');
  /* 有的页面走模块路由（如 #players -> playerarchive），按标题文字兜底选图标。 */
  let name = HEADING_ICONS[routeName];
  if (h1 && !name) {
    const text = h1.textContent || '';
    if (/选手/.test(text)) name = 'players';
    else if (/本队|战队/.test(text)) name = 'teams';
    else if (/英雄/.test(text)) name = 'heroes';
    else if (/BP|禁选/.test(text)) name = 'bp';
    else if (/跨局|跨场|大场/.test(text)) name = 'cross';
    else if (/单局|对局/.test(text)) name = 'matches';
    else if (/赛事|比赛/.test(text)) name = 'calendar';
    else if (/采集|导入/.test(text)) name = 'capture';
    else if (/规则|配置/.test(text)) name = 'rules';
    else if (/数据源|快照/.test(text)) name = 'sources';
  }
  if (h1 && name) {
    h1.dataset.deco = '1';
    h1.insertAdjacentHTML('afterbegin',
      `<span class="desk-h1-glyph" aria-hidden="true">${icon(name)}</span>` +
      deco('section-triangle', { cls: 'desk-h1-tri' }));
  }
  document.querySelectorAll('.desk-group > span:not([data-deco])').forEach((span) => {
    span.dataset.deco = '1';
    span.insertAdjacentHTML('afterbegin', '<span class="desk-group-glyph" aria-hidden="true"></span>');
  });
}
/* 首页简报、选手池等模块的 H1 在 render() 之后异步挂载；监听 #content，
   标题一出现就补图标。切页先断开旧观察器，避免累积监听。 */
let headingObserver;
function watchHeadings(routeName) {
  headingObserver?.disconnect();
  const root = document.querySelector('#content');
  if (!root) return;
  headingObserver = new MutationObserver(() => decorateHeadings(routeName));
  headingObserver.observe(root, { childList: true, subtree: true });
  decorateHeadings(routeName);
  /* 有的页面走独立渲染分支，不在 render() 末尾汇合；定时补一次兜底（幂等）。 */
  setTimeout(() => decorateHeadings(routeName), 400);
  setTimeout(() => decorateHeadings(routeName), 1600);
}
const esc = (x) => String(x ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const has = (n) => typeof n === 'number' && Number.isFinite(n);
const fmt = (n, digits = 0) => has(n) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(n) : '—';
const pct = (n) => has(n) ? fmt(n, 1) + '%' : '—';
const diff = (n) => has(n) ? (n > 0 ? '+' : '') + fmt(n === 0 ? 0 : n) : '—';
const time = (n) => has(n) && n >= 0 ? `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, '0')}` : '—';
/* 阶段口径（教练 2026-11-10 确认、2026-11-19 改标签）：0–4 / 4–10 / 10–结束。
   所有阶段相关面板统一走这两个函数，避免各算各的三等分。始终返回 3 段
   （短局的后段长度为 0，图表天然不绘制）。
   标签直接用时间段：教练原话「前期中期后期改成具体时间分段」，写时间比
   写「发育期」更没有歧义，几处图表/表格也就不用各解释一遍。 */
const PHASE_DEFS = [['0–4', 0, 240], ['4–10', 240, 600], ['10–结束', 600, Infinity]];
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
/* 打野位的英雄类型：优先看**本局实际出的打野刀**（player.blade，后端从营地
   finalEquips 判定：肉刀→坦野 tank、红/法刀→野核 core），拿不到才退回英雄静态
   标签（heroTypes['打野']）。同一英雄不同出装会切口径——大司命肉刀坦野/红刀野核。 */
function jungleKindOf(hero, player) {
  const blade = player && typeof player === 'object' ? player.blade : null;
  if (blade && JUNGLE_TYPES[blade.kind]) return blade.kind;
  const type = String((metadata.heroTypes || {})[hero || '']?.['打野'] || '');
  return type.includes('坦野') ? 'tank' : 'core';
}
function jungleTypeLabel(hero, player) {
  return JUNGLE_TYPES[jungleKindOf(hero, player)].key;
}
function goldGrade(lane, gpm, hero, player) {
  const defs = lane === '打野'
    ? JUNGLE_TYPES[jungleKindOf(hero, player)].grades
    : GOLD_GRADES[lane];
  if (!defs || !has(gpm)) return null;
  for (const [need, label, level] of defs) if (gpm >= need) return { label, level };
  return null;
}

/* ── 赛训组自定义评级规则（grade-rules.js 设置页维护，最高优先级）─────────
   gradeRulesDoc 在 load() 里对 match 路由取一次；没保存过规则时为 null，
   所有 fieldGrade 调用退回上面的硬编码口径，保证旧实例照常工作。 */
const LEVEL_LABEL = { elite: '卓越', good: '优秀', pass: '达标', ok: '达标', low: '待提升' };
let gradeRulesPromise = null;
function ensureGradeRules() {
  if (gradeRulesDoc !== null && gradeRulesDoc !== undefined) return Promise.resolve(gradeRulesDoc);
  if (gradeRulesPromise) return gradeRulesPromise;
  gradeRulesPromise = fetch(API_BASE + '/api/v3/grade-rules', { cache: 'no-store' })
    .then((r) => r.ok ? r.json() : null)
    .then((doc) => { gradeRulesDoc = doc?.saved ? doc : null; gradeRulesPromise = null; return gradeRulesDoc; })
    .catch(() => { gradeRulesPromise = null; return null; });
  return gradeRulesPromise;
}
/* 把选手的分路（+打野刀类型）映射到规则主体 key，与后端 grade_rules.subject_for 一致。 */
function subjectOf(player) {
  const pos = String(player?.position || '').trim();
  if (pos === '打野·坦野' || pos === '打野·野核') return pos;
  if (pos === '打野') {
    // 与 grade_rules.subject_for / jungleKindOf 同一口径：本局打野刀优先，
    // 拿不到再退回英雄静态标签。以前这里只看 blade，缺刀时会和 goldGrade 分叉。
    return jungleKindOf(player?.hero, player) === 'tank' ? '打野·坦野' : '打野·野核';
  }
  return pos;
}
/* 按已保存规则给一个数值定档；无规则/无值返回 null。direction=down 时数值越低越好。
   `minutes` 只供按局时长匹配的字段（补刀）使用，口径与后端 grade_rules.grade 一致。 */
function fieldGrade(subject, field, value, minutes) {
  if (value === null || value === undefined || value === '' || !gradeRulesDoc) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const rule = gradeRulesDoc.subjects?.[subject]?.[field];
  // 设置页没勾选生效的字段不进入任何评级口径，与后端 grade_rules.grade 一致。
  if (!rule || rule.active === false || !Array.isArray(rule.thresholds)) return null;
  const table = field === 'cs' && rule.minuteStandard && typeof rule.minuteStandard === 'object'
    ? rule.minuteStandard : null;
  if (table) {
    const keys = Object.keys(table).map(Number).filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
    if (!keys.length) return null;
    let minute = Number(minutes);
    if (!Number.isFinite(minute)) return null;
    minute = Math.round(minute);
    if (minute < 18) minute = 18;
    const lower = keys.filter((x) => x <= minute);
    const standard = Number(table[String(lower.length ? lower[lower.length - 1] : keys[0])]);
    if (!Number.isFinite(standard)) return null;
    if (subject === '中路') return { level: 'ok', label: '达标' };
    if (n > standard) return { level: 'elite', label: '高于标准' };
    if (n < standard) return { level: 'low', label: '低于标准' };
    return { level: 'ok', label: '达标' };
  }
  const [e, g, p] = rule.thresholds;
  const down = rule.direction === 'down';
  let level = 'low';
  if (down ? n <= e : n >= e) level = 'elite';
  else if (down ? n <= g : n >= g) level = 'good';
  else if (down ? n <= p : n >= p) level = 'pass';
  return { level, label: LEVEL_LABEL[level] };
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
function renderOffline(r = current(), error = null) {
  const box = document.querySelector('#content');
  if (!box) return;
  const code = 'E-SYS-001';
  const title = errorEntry(code)?.title || '工作台连接中断';
  box.innerHTML = `<div class="page"><section class="section"><div class="offline-card dx-error">
    <div class="dx-error-head"><span class="dx-error-code">${esc(code)}</span><b>${esc(labels[r.name] || '当前页面')} · ${esc(title)}</b></div>
    <p>与工作台的连接中断了，恢复后会<strong>自动加载这一页</strong>，也可以点下面的按钮立即重试。</p>
    <div class="offline-actions"><button class="control" data-action="refresh">${glyph('refresh', { size: 18 })} 立即重试</button></div>
    ${diagnosticBlock({ code, error, route: r, requestPath: error?.path })}
    <p class="dx-error-foot">反馈时把错误码和诊断信息一起贴到群里，不用重复描述页面。</p>
  </div></section></div>`;
  bindDiagnosticCopy(box);
}
function renderDataNotice(r, error = null) {
  const box = document.querySelector('#content');
  if (!box) return;
  const code = 'E-SYS-002';
  const title = errorEntry(code)?.title || '这一页的数据还没返回';
  box.innerHTML = `<div class="page"><section class="section"><div class="offline-card dx-error">
    <div class="dx-error-head"><span class="dx-error-code">${esc(code)}</span><b>${esc(labels[r.name] || '当前页面')} · ${esc(title)}</b></div>
    <p>这一页的数据还没返回，已经自动重试过；稍后再点一次读取即可。</p>
    <div class="offline-actions"><button class="control" data-action="refresh">${glyph('refresh', { size: 18 })} 重新读取</button></div>
    ${diagnosticBlock({ code, error, route: r, requestPath: error?.path })}
    <p class="dx-error-foot">反馈时把错误码和诊断信息一起贴到群里，不用重复描述页面。</p>
  </div></section></div>`;
  bindDiagnosticCopy(box);
}
let metadata = {};
let data;
let view = {};
let archiveScrollRemember = 0;   // 从复盘返回档案时恢复的滚动位置
let lastRouteName = '';          // hashchange 里要知道刚才在哪一页
let theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
let stickyTabsObserver = null;   // 单局四段页签的吸顶偏移（跟随顶栏高度）
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
  /* profiles 原本是已下线的「名单与状态」子页；2026-11-22 起 #profiles 由新档案管理模块接管，故不再重定向。 */
  const retired = { teamcompare: 'teams', h2h: 'teams', records: 'featured', query: 'matches', teamstyle: 'teams', teamroster: 'teams',
    teambp: 'bp', bpcounter: 'bp',
    players: 'playerarchive', identity: 'playerarchive', compare: 'playerarchive',
    /* 2026-11-16：截图 / 录屏 / 回放 / 审查已并进采集页，旧链接仍落在采集页的对应页签
       （采集页自己按 hash 决定显示哪一块，#review/<id> 也照常打开那条审查明细）。 */
    shots: 'ingest', videos: 'ingest', replays: 'ingest', review: 'ingest', imported: 'ingest',
    /* 2026-11-22：英雄组合页已下线，旧链接回到英雄榜。 */
    /* 2026-11-22：比赛与训练计划已并入赛事页（比赛=赛事同一份数据，排期/看板改为赛事页区块）。 */
    plan: 'competitions', combos: 'heroes' };
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

function openDeciderDialog() {
  let dialog = document.querySelector('#decider-dialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'decider-dialog';
    dialog.className = 'sx-dialog bp-order-dialog decider-dialog';
    document.body.append(dialog);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  }
  const heroes = Object.keys(metadata.heroTypes || {}).sort((a, b) => a.localeCompare(b, 'zh'));
  const options = (selected = '') => ['<option value="">— 未选 —</option>']
    .concat(heroes.map((name) => `<option value="${esc(name)}"${name === selected ? ' selected' : ''}>${esc(name)}</option>`))
    .join('');
  const side = (key, label) => `<section class="bp-order-side"><h3>${label}</h3>
    <div class="bp-order-group"><b>盲选 5 个</b>
      ${Array.from({ length: 5 }, (_, index) => `<label>P${index + 1}<select data-decider-side="${key}" data-decider-index="${index}">${options()}</select></label>`).join('')}
    </div></section>`;
  dialog.innerHTML = `<div class="sx-dialog-head"><div><span class="sx-eyebrow">PEAK DUEL</span><h2>${glyph('bp', { size: 20 })} 巅峰对决 · 双方盲选</h2></div><button type="button" class="sx-dialog-x" data-decider-close aria-label="关闭">×</button></div>
    <p class="sx-dialog-note">BO7 第 7 局（大比分 3:3）：取消 Ban；双方各盲选 5 个；解除此前全局 BP 限制。允许双方选到同一个英雄；同一方 5 个不能重复。</p>
    <div class="bp-order-grid">${side('own', '我方')}${side('foe', '对方')}</div>
    <div class="bp-order-foot"><p class="form-status" data-decider-status></p>
      <button type="button" class="control" data-decider-clear>${glyph('trash', { size: 18 })} 清空</button>
      <button type="button" class="control" data-decider-close>关闭</button>
      <button type="button" class="primary" data-decider-summary>${glyph('export', { size: 18 })} 生成摘要</button></div>
    <div class="decider-summary" data-decider-summary-box hidden></div>`;
  const values = (key) => [...dialog.querySelectorAll(`[data-decider-side="${key}"]`)].map((select) => select.value);
  const status = dialog.querySelector('[data-decider-status]');
  const summaryBox = dialog.querySelector('[data-decider-summary-box]');
  const renderSummary = () => {
    const own = values('own');
    const foe = values('foe');
    const duplicates = (list) => list.filter((name, index) => name && list.indexOf(name) !== index);
    if (duplicates(own).length || duplicates(foe).length) {
      status.textContent = '同一方不能重复选同一个英雄；双方之间可以重复。';
      summaryBox.hidden = true;
      return;
    }
    if (own.filter(Boolean).length < 5 || foe.filter(Boolean).length < 5) {
      status.textContent = '双方各选满 5 个再生成摘要。';
      summaryBox.hidden = true;
      return;
    }
    status.textContent = '';
    const lineup = (list, tone) => `<div class="decider-lineup ${tone}"><b>${tone === 'own' ? '我方' : '对方'}</b>${list.map((name) => `<span class="decider-hero">${portrait(name, 'decider-portrait')}<em>${esc(name)}</em></span>`).join('')}</div>`;
    summaryBox.innerHTML = `${lineup(own, 'own')}${lineup(foe, 'foe')}<p class="decider-note">无 Ban、解除全局 BP；双方可重复选同一英雄；这是赛前推演，不改动任何对局记录。</p>`;
    summaryBox.hidden = false;
  };
  dialog.onclick = (event) => {
    if (event.target === dialog || event.target.closest('[data-decider-close]')) { dialog.close(); return; }
    if (event.target.closest('[data-decider-clear]')) {
      dialog.querySelectorAll('select[data-decider-side]').forEach((select) => { select.value = ''; });
      status.textContent = '';
      summaryBox.hidden = true;
      return;
    }
    if (event.target.closest('[data-decider-summary]')) renderSummary();
  };
  dialog.onchange = () => { summaryBox.hidden = true; status.textContent = ''; };
  if (!dialog.open) dialog.showModal();
}

const navHref = (key) => key === 'setup' ? '#competitions' : key === 'players' ? '#playerarchive' : '#' + key;

/* ── 赛事门控（2026-11）：未选赛事时锁住对局/战队/选手/英雄/BP 入口 ────────
   赛训以赛事为中心，所有数据都要归档到一场赛事下。没选赛事就点这些入口会
   不知道是哪场比赛的数据，所以默认灰掉并阻止激活（aria-disabled 保留可聚焦，
   见 accessibility 指南：disabled 链接用 aria-disabled 而非 pointer-events）。 */
const GATED_NAV = new Set(['matches', 'teams', 'players', 'heroes', 'bp',
  'biggame', 'cross', 'matching', 'series-builder', 'opponents']);
const COMPETITION_KEY = 'training-current-competition';
let competitionNameCache = '';
let competitionContextToken = 0;
try { competitionNameCache = localStorage.getItem(COMPETITION_KEY + '-name') || ''; } catch {}
function hasCurrentCompetition() {
  try { return Boolean(localStorage.getItem(COMPETITION_KEY)); } catch { return false; }
}
let requestedPage = '';
async function refreshCompetitionContext(force = false) {
  /* 赛事域（M1）：顶栏把「切换赛事」升级成常显当前赛事名。
     渲染极频繁（分析页会多次重绘），这里用缓存 + 请求令牌防止「切换赛事」/
     赛事名来回闪烁；同一赛事只解析一次，切赛事时 force 重新解析。 */
  const context = app.querySelector('[data-competition-context]');
  if (!context) return;
  let id = '';
  try { id = localStorage.getItem(COMPETITION_KEY) || ''; } catch {}
  if (!id) {
    competitionNameCache = '';
    if (context.textContent !== '选择赛事') context.textContent = '选择赛事';
    return;
  }
  if (!force && competitionNameCache) {
    if (context.textContent !== competitionNameCache) context.textContent = competitionNameCache;
    return;
  }
  /* 只有真的没有缓存（首次进入）才显示占位文字，避免已显示赛事名时又退化。 */
  if (!competitionNameCache && context.textContent !== '切换赛事') context.textContent = '切换赛事';
  const token = ++competitionContextToken;
  try {
    const response = await fetch(API_BASE + '/api/studio/workspace/competitions', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    if (token !== competitionContextToken) return;
    const found = (data.competitions || []).find((item) => String(item.id) === String(id));
    if (found && found.name) {
      competitionNameCache = String(found.name);
      try { localStorage.setItem(COMPETITION_KEY + '-name', competitionNameCache); } catch {}
      if (context.isConnected && context.textContent !== competitionNameCache) {
        context.textContent = competitionNameCache;
      }
    }
  } catch { /* 名称解析失败不影响门控 */ }
}

function applyGate() {
  const locked = !hasCurrentCompetition();
  app.querySelectorAll('[data-nav]').forEach((link) => {
    const needsCompetition = locked && GATED_NAV.has(link.dataset.nav);
    link.toggleAttribute('data-needs-competition', needsCompetition);
    link.title = needsCompetition ? '先选择赛事，再进入' + link.textContent.trim() : '';
  });
  const activeNav = current().name;
  app.querySelectorAll('[data-nav]').forEach((link) => {
    const state = unlockState.loaded ? unlockState.routes[link.dataset.nav] : null;
    link.toggleAttribute('data-data-locked', Boolean(state && state.unlocked === false));
    if (link.dataset.nav === activeNav) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const context = app.querySelector('[data-competition-context]');
  /* 别在每次 applyGate 都把已解析的赛事名打回「切换赛事」。 */
  if (context && (locked || !competitionNameCache)) {
    const placeholder = locked ? '选择赛事' : '切换赛事';
    if (context.textContent !== placeholder) context.textContent = placeholder;
  }
  refreshCompetitionContext();
}
document.addEventListener('route:repainted', () => injectEventChip(current()));
document.addEventListener('competition:selected', () => {
  competitionNameCache = '';
  applyGate();
  refreshCompetitionContext(true);
  if (hasCurrentCompetition() && requestedPage && current().name === 'competitions') {
    location.hash = requestedPage;
    requestedPage = '';
  } else if (GATED_NAV.has(sectionFor(current().name)) && !hasCurrentCompetition()) {
    location.hash = '#competitions';
  } else load(true);
});
let workbenchUI;
function shell() {
  const brand = `<a class="desk-brand" href="#overview" aria-label="赛训数据首页"><img src="static/media/mark.svg" alt="" width="32" height="32">赛训数据</a>`;
  const navLink = ([key, label]) => `<a href="${navHref(key)}" data-nav="${key}">${icon(key === 'series-builder' || key === 'matching' ? 'seriesbuilder' : key) || ''}<span>${label}</span></a>`;
  /* 按 key 取导航项，不用 slice 下标：nav 是「主导航 + 各板块页签」的合集，
     之前插入「快照中心」就把管理组的下标挤掉了，新增的「外部数据源」不显示。 */
  const navByKey = new Map(nav);
  const groups = [
    ['工作台', ['overview', 'competitions', 'team-profile', 'opponents', 'ingest', 'matching']],
    ['赛训与复盘', ['match-notes', 'matches', 'biggame', 'cross']],
    ['情报（赛前准备）', ['teams', 'players', 'heroes', 'bp']],
    ['配置（规则库）', ['rules']],
    ['管理', ['snapshot-center', 'sources', 'docs', 'source-health']],
  ].map(([title, keys]) => [title,
    keys.map((key) => [key, navByKey.get(key) || key]).filter(([, label]) => Boolean(label))]);
  const navigation = groups.map(([title, entries]) => `<div class="desk-group"><span>${title}</span>${entries.map(navLink).join('')}</div>`).join('');
  const tools = `<button type="button" data-action="checklist">${icon('help')}上手引导</button><a href="kpl-client://open" data-action="open-client">${icon('client')}打开客户端</a>`;
  app.innerHTML = `<aside class="desk-rail">${brand}<nav class="desk-links main-nav" aria-label="主导航">${navigation}</nav><div class="desk-tools">${tools}</div></aside>
  <header class="desk-bar">
    <button type="button" class="desk-icon menu-button" data-action="menu" aria-label="打开导航" aria-expanded="false" aria-controls="ui-navigation">${icon('menu')}</button>
    <nav class="desk-crumb" aria-label="当前位置"><a href="#overview" data-ui-section>工作台</a>${icon('chevron')}<span data-ui-page>首页</span></nav>
    <button type="button" class="desk-search" data-ui-search aria-label="搜索页面与功能" aria-haspopup="dialog" aria-controls="ui-command">${icon('search')}<span>找页面或功能</span><kbd>Ctrl K</kbd></button>
    <a class="desk-context" href="#competitions">${icon('setup')}<span data-competition-context>选择赛事</span></a>
    <button type="button" class="desk-icon inbox-button" data-sx-inbox aria-label="待处理" title="待处理">${icon('inbox')}<span class="inbox-badge" data-inbox-badge hidden></span></button>
  </header>
  <dialog id="ui-navigation" class="desk-drawer" aria-label="页面导航" closedby="any"><div class="desk-drawer-head">${brand}<button type="button" class="desk-icon" data-ui-close aria-label="关闭导航" autofocus>${icon('close')}</button></div><nav class="desk-links" aria-label="移动导航">${navigation}</nav><div class="desk-tools ui-drawer-tools">${tools}</div></dialog>
  <dialog id="ui-command" class="ui-command" aria-label="搜索页面与功能" closedby="any"><div class="ui-command-head">${icon('search')}<input type="search" class="ui-command-input" role="combobox" aria-autocomplete="list" aria-controls="ui-command-results" aria-expanded="true" aria-label="搜索页面与功能" placeholder="搜索页面与功能…" autocomplete="off" autofocus><button type="button" class="head-button" data-ui-close aria-label="关闭搜索">${icon('close')}</button></div><div id="ui-command-results" class="ui-command-results" role="listbox" aria-label="搜索结果" data-command-results></div><div class="ui-command-foot"><span>↑ ↓ 选择 · Enter 打开 · Esc 关闭</span><span data-command-count></span></div></dialog>
  <div class="demo-banner" hidden><strong>演示模式</strong> 所有比赛、选手与分析均为虚构数据，仅供体验。<button data-action="demo">${glyph('arrow-up', { size: 18 })} 返回真实数据</button></div>
  <div class="secondary-wrap"><nav class="secondary-nav" aria-label="分类导航"></nav><label class="desk-page-select"><span>板块页面</span><select aria-label="切换板块页面"></select></label></div>
  <div class="desk-event-chip" id="desk-event-chip" hidden></div>
  <p class="desk-handoff" role="status" hidden></p>
  <main id="content" tabindex="-1"></main>
  <footer class="footer"><span>赛训数据</span><span class="footer-actions"><a href="#docs?chapter=about" class="footer-about">关于作者与项目来源</a><button type="button" class="footer-update" data-action="check-update">${glyph('refresh', { size: 18 })} 检查更新</button></span><span>英雄资料来自王者荣耀官方，相关权利归原权利人。</span></footer>
  <dialog id="filters"></dialog>`;
  applyTheme();
  workbenchUI = createWorkbenchUI({ app, nav, labels, icon, esc, navHref, sectionFor, featureSections });
  applyGate();
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
    /* 挂到 #app 里：关闭 / 深链 / 对手映射的点击代理都在 #app 上，
       放 body 会让弹窗里的按钮收不到这些事件（× 关不掉）。 */
    app.append(dialog);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  }
  const groups = (data.groups || []).map((group) => {
    const items = group.items || [];
    let body = '';
    if (group.key === 'unmapped') {
      body = items.map((item) => `<div class="sx-inbox-map" data-old-id="${esc(item.oldId)}">
        <span><b>${esc(item.oldId)}</b><small>${fmt(item.matches)} 局</small></span>
        <select aria-label="映射到战队">${(data.teams || []).map((team) => `<option value="${esc(team.id)}">${esc(team.name)}</option>`).join('')}</select>
        <button type="button" class="control" data-sx-map-opponent>${glyph('compare', { size: 18 })} 应用映射</button>
      </div>`).join('');
    } else if (items.length) {
      body = `<div class="sx-inbox-items">${items.map((item) => `<a href="${esc(item.href)}" data-sx-inbox-link>${esc(item.label)}</a>`).join('')}</div>`;
    }
    return `<section class="sx-inbox-group">
      <header><b>${esc(group.label)}</b><strong>${fmt(group.count)}</strong></header>
      <p>${esc(group.note || '')}</p>${body}
      ${group.key !== 'unmapped' ? `<a class="sx-inbox-go" href="${esc(group.href)}" data-sx-inbox-link>${glyph('arrow-up', { size: 18 })} 去处理</a>` : ''}
    </section>`;
  }).join('');
  dialog.innerHTML = `<div class="sx-dialog-head"><div><span class="sx-eyebrow">INBOX</span><h2>${glyph('warning', { size: 20 })} 待处理 ${fmt(data.total || 0)} 项</h2></div><button type="button" class="sx-dialog-x" data-sx-inbox-close aria-label="关闭">×</button></div><div class="sx-inbox-groups">${groups || `<div class="sx-empty">${glyph('victory', { size: 32 })}<strong>没有待处理项</strong></div>`}</div>`;
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
  if (!button) return;
  button.innerHTML = icon(theme === 'light' ? 'moon' : 'sun');
  button.setAttribute('aria-label', theme === 'light' ? '切换深色主题' : '切换浅色主题');
}

function query(fresh = false) {
  const q = new URLSearchParams({ source: filters.source.join(',') });
  /* 赛事域（M1）：所有走统一取数层的分析请求自动带上当前赛事，
     服务端据此收窄仓库；未选赛事时不带参数，行为与旧口径一致。 */
  let competitionId = '';
  try { competitionId = localStorage.getItem(COMPETITION_KEY) || ''; } catch {}
  if (competitionId) q.set('competition', competitionId);
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
    error.path = path;
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
  /* 标题下不再摆说明小字；口径与限制放在各区块正文里，按钮自己要一眼看懂。 */
  return `<div class="page-intro"><div><h1>${esc(title)}</h1></div>
    <div class="intro-actions">${right}<button class="control" data-action="filter">${glyph('calendar', { size: 18 })} 筛选范围</button>
    <button class="control icon-control" data-action="refresh" aria-label="刷新数据">${glyph('refresh', { size: 18 })}</button></div></div>`;
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
  /* 阶段底色与分界线按固定口径切（0–4 / 4–10 / 10–结束），不再按总时长三等分：
     一局 15 分钟三等分是 5/5/5，和教练认的 4/6/5 对不上。 */
  const windows = duration > 0 ? phaseWindows(duration) : [];
  const bands = rich && windows.length ? windows.map((win, i) => {
    const xa = x(Math.max(win.start, x0)), xb = x(Math.min(win.end, x1));
    return xb - xa > 1 ? `<rect x="${xa.toFixed(1)}" y="20" width="${(xb - xa).toFixed(1)}" height="185" class="chart-band${i % 2 ? ' alt' : ''}"/>` : '';
  }).join('') : '';
  const phaseLines = windows.slice(1).map((win) => {
    const t = win.start;
    return t > x0 && t < x1 ? `<line x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="20" y2="205" class="chart-phase-line"/>` : '';
  }).join('');
  const phaseLabels = windows.map((win) => {
    const mid = (win.start + win.end) / 2;
    return mid >= x0 && mid <= x1 ? `<text x="${x(mid).toFixed(1)}" y="13" text-anchor="middle" class="chart-phase-label">${esc(win.label)}</text>` : '';
  }).join('');
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
/* 分路图标：只给真实存在的 lane 加角标；原始数据没标分路就不画，不假装排过序。 */
function laneBadge(lane) {
  const slug = LANE_SVG[lane];
  return slug ? `<img class="lane-badge" src="${KPL_SVG}modules/role-icon-${slug}.svg" alt="" aria-hidden="true" loading="lazy">` : '';
}

/** 双方十人按真实分路顺序排列；只有一方数据时按实际数据降级显示。 */
function archiveLineup(match) {
  const pairs = (match.lineup || []).filter((pair) => pair.own || pair.enemy).slice(0, 5);
  const cell = (hero, lane, foe) => hero
    ? `<span class="ml-cell${foe ? ' is-foe' : ''}${lane ? '' : ' is-unknown'}" title="${esc([lane || '分路未标注', (foe ? '对方 ' : '我方 ') + hero].join(' · '))}">${portrait(hero)}${laneBadge(lane)}</span>`
    : '<span class="ml-cell is-empty" title="这一路没有阵容记录"></span>';
  /* 外层只占一个网格单元：否则「我方 / VS / 对方」会被浏览器当成三列，
     把对方阵容挤到下一行，行高翻倍。 */
  if (!pairs.length) {
    const heroes = (match.heroes || []).slice(0, 5);
    if (!heroes.length) return '<span class="match-lineup archive-lineup"><span class="ml-empty">双方阵容未记录</span></span>';
    return `<span class="match-lineup archive-lineup">
      <span class="ml-side is-own"><small>我方</small><span class="ml-faces">${heroes.map((hero) => cell(hero, '', false)).join('')}</span></span>
      <span class="ml-note">仅我方阵容</span></span>`;
  }
  const foePairs = pairs.filter((pair) => pair.enemy);
  return `<span class="match-lineup archive-lineup" title="左组本队 · 右组对面，同一顺序即同分路对位">
    <span class="ml-side is-own"><small>我方</small><span class="ml-faces">${pairs.map((pair) => cell(pair.own, pair.lane, false)).join('')}</span></span>
    ${foePairs.length
      ? `<span class="ml-vs" aria-hidden="true">VS</span><span class="ml-side is-foe"><small>对方</small><span class="ml-faces">${foePairs.map((pair) => cell(pair.enemy, pair.lane, true)).join('')}</span></span>`
      : '<span class="ml-note">仅我方阵容</span>'}</span>`;
}

function archiveSortKey() {
  const saved = view.archiveSort || (() => { try { return localStorage.getItem(ARCHIVE_SORT_KEY) || 'time'; } catch { return 'time'; } })();
  return ARCHIVE_SORTS.some((item) => item.key === saved) ? saved : 'time';
}

function archiveOpponentRates(rows) {
  const stats = new Map();
  for (const match of rows) {
    const name = match.opponent || '';
    if (!name) continue;
    const entry = stats.get(name) || { win: 0, decided: 0 };
    if (match.result === 'win' || match.result === 'loss') entry.decided += 1;
    if (match.result === 'win') entry.win += 1;
    stats.set(name, entry);
  }
  const rates = new Map();
  for (const [name, entry] of stats) rates.set(name, entry.decided ? entry.win / entry.decided : -1);
  return rates;
}

function archiveCompare(sort, byKey, rates) {
  const time = (a, b) => String(b?.date || '').localeCompare(String(a?.date || ''))
    || String(b?.startTime || '').localeCompare(String(a?.startTime || ''));
  return (a, b) => {
    if (sort === 'duration') {
      const d = Number(b?.duration || 0) - Number(a?.duration || 0);
      if (d) return d;
    } else if (sort === 'opponent') {
      const d = zhCollator.compare(a?.opponent || '', b?.opponent || '');
      if (d) return d;
    } else if (sort === 'winrate') {
      const d = (rates.get(b?.opponent || '') ?? -1) - (rates.get(a?.opponent || '') ?? -1);
      if (d) return d;
    }
    return time(a, b);
  };
}

/* 排序只搬已有节点，不重建结果区：焦点、标签输入与图片状态都不丢。 */
function applyArchiveSort(sort) {
  const byKey = new Map((data?.matches || []).map((match) => [match.key, match]));
  const compare = archiveCompare(sort, byKey, archiveOpponentRates(data?.matches || []));
  const move = Object.hasOwn(Element.prototype, 'moveBefore')
    ? (list, row) => list.moveBefore(row, null)
    : (list, row) => list.append(row);
  let total = 0;
  document.querySelectorAll('.archive-ledger .match-list').forEach((list) => {
    const rows = [...list.querySelectorAll(':scope > .archive-row-wrap')];
    total += rows.length;
    rows.sort((a, b) => compare(byKey.get(a.dataset.matchKey), byKey.get(b.dataset.matchKey)));
    rows.forEach((row) => move(list, row));
  });
  const meta = ARCHIVE_SORTS.find((item) => item.key === sort) || ARCHIVE_SORTS[0];
  const status = document.querySelector('[data-archive-sort-status]');
  if (status) status.textContent = `已按${meta.label}排序，共 ${total} 场`;
  document.querySelectorAll('[data-archive-sort]').forEach((button) => {
    const active = button.dataset.archiveSort === sort;
    button.classList.toggle('is-on', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

/* 档案库列表：一行一场，所有条件都作用于全库结果（不再只铺前 24 行）。
   保留 .match-row / .match-list / .fixture-day 这几个类名，键盘导航与既有
   事件委托照常工作；标签与备注按钮放在 <a> 外侧，避免交互元素嵌套。 */
function matchRows(rows, dayNo = new Map()) {
  if (!rows.length) {
    const clear = `<button type="button" class="control" data-mf-clear>${glyph('refresh', { size: 18 })} 清除筛选</button>`;
    const ingest = `<a class="primary" href="#ingest">${glyph('capture', { size: 18 })} 采集对局</a>`;
    const formal = `<a class="control" href="#official-entry">${glyph('edit', { size: 18 })} 录正式比赛</a>`;
    if (view.archiveTagKeys?.size) return `<div class="empty">${glyph('matches', { size: 52 })}<strong>标签命中不在当前范围</strong><p>这些标签在全库有命中，但都不在当前数据范围。</p><p>${clear}</p></div>`;
    /* 空态按类型给去处：正式比赛是空多半是还没录，训练赛是空多半是还没采集。 */
    const type = matchFilters().type || 'training';
    if (type === 'formal') return `<div class="empty">${glyph('matches', { size: 52 })}<strong>还没有正式比赛</strong><p>${clear}${formal}</p></div>`;
    if (type === 'all') return `<div class="empty">${glyph('matches', { size: 52 })}<strong>当前范围暂无对局</strong><p>${clear}${ingest}${formal}</p></div>`;
    return `<div class="empty">${glyph('matches', { size: 52 })}<strong>当前范围暂无训练赛</strong><p>${clear}${ingest}</p></div>`;
  }
  const item = (match) => {
    const no = dayNo.get(match.key);
    const start = String(match.startTime || '').trim();
    const clock = start ? start.slice(-5) : '';
    const noteCount = (archiveNotesMap[match.key] || []).length;
    const matchTags = tagsOf(match.key) || [];
    const hiddenTags = matchTags.slice(3);
    const opponentTitle = match.opponent ? `对手：${match.opponent}` : '对手未标注';
    const shortResult = { win: '胜', loss: '负', draw: '平' }[match.result] || '—';
    return `<div class="match-row-wrap archive-row-wrap" data-match-key="${esc(match.key)}">
      <label class="archive-pick"><input type="checkbox" data-archive-check="${esc(match.key)}"
        ${view.archiveSelected?.has(match.key) ? 'checked' : ''} aria-label="选择这一局：${esc(match.opponent || match.date || match.key)}"></label>
      <a class="match-row archive-row" href="${esc(route('match', match.key))}">
        <span class="archive-when"><b>${esc((match.date || '日期未知').slice(5))}</b><small>${esc(clock || (no ? `第 ${no} 局` : (match.date || '').slice(0, 4)))}</small></span>
        <span class="archive-opponent"><small>${match.isSeed ? '验证对局' : esc(match.mode || match.session || '训练赛')}${match.gameNo ? ` · 第 ${fmt(match.gameNo)} 局` : (no ? ` · 第 ${no} 局` : '')}</small>
          <span class="archive-opponent-line"><b title="${esc(opponentTitle)}">${esc(match.opponent ? '对阵 ' + match.opponent : '对手未标注')}</b></span></span>
        <span class="result ${esc(match.result)}"><i aria-hidden="true"></i>${shortResult}</span>
        <strong class="row-score" title="击杀数 · 本队 : 对面">${score(match)}</strong>
        <span class="match-duration" title="本局时长">${time(match.duration)}</span>
        ${archiveLineup(match)}
        <span class="row-arrow" title="查看复盘">查看复盘 ${icon('arrow')}</span>
      </a>
      <div class="archive-side">
        <div class="tagrow" data-tag-key="${esc(match.key)}" aria-label="这一局的自定义标签"${hiddenTags.length ? ` data-tag-more="+${hiddenTags.length}" title="还有：${esc(hiddenTags.join('、'))}"` : ''}></div>
        <div class="archive-tools">
          <button type="button" class="archive-focus" data-focus-match="${esc(match.key)}"
            data-focus-opponent="${esc(match.opponent || '')}" data-focus-date="${esc(match.date || '')}"
            data-focus-result="${esc(match.result || '')}" data-focus-score="${esc(score(match))}"
            data-focus-duration="${esc(time(match.duration))}" data-focus-diff="${esc(Number.isFinite(match.goldDiff) ? fmt(match.goldDiff) : '')}"
            aria-label="${matchTags.includes('重点') ? '编辑这一局的重点关注' : '把这一局加入重点关注'}" title="重点关注">${matchTags.includes('重点') ? '★' : '☆'}</button>
          <button type="button" class="archive-note" data-archive-note="${esc(match.key)}" aria-label="编辑这一局的教练备注">备注${noteCount ? `<b>${noteCount}</b>` : ''}</button>
        </div>
      </div>
    </div>`;
  };
  const sort = archiveSortKey();
  const byKey = new Map((data?.matches || []).map((match) => [match.key, match]));
  const compare = archiveCompare(sort, byKey, archiveOpponentRates(rows));
  if (!view.archiveCollapsed) {
    view.archiveCollapsed = new Set();
    try { for (const day of JSON.parse(sessionStorage.getItem(ARCHIVE_COLLAPSED_KEY) || '[]')) view.archiveCollapsed.add(day); } catch {}
  }
  const collapsed = view.archiveCollapsed;
  const groups = new Map();
  for (const match of rows) {
    const day = match.date || '日期未标注';
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(match);
  }
  return [...groups].sort(([a], [b]) => b.localeCompare(a)).map(([day, games]) => {
    games.sort(compare);
    const wins = games.filter((match) => match.result === 'win').length;
    const losses = games.filter((match) => match.result === 'loss').length;
    const total = Math.max(1, games.length);
    return `<details class="fixture-day" data-archive-day="${esc(day)}"${collapsed.has(day) ? '' : ' open'}>
      <summary class="fixture-day-head"><div class="archive-day-head-inner">
        <span class="archive-day-caret" aria-hidden="true">${icon('chevron')}</span>
        <span class="archive-day-date"><time${/^\d{4}-\d{2}-\d{2}$/.test(day) ? ` datetime="${esc(day)}"` : ''}>${esc(day)}</time></span>
        <span>${games.length} 场</span><span class="fixture-day-record">${wins} 胜 · ${losses} 负</span>
        <span class="day-split" aria-hidden="true"><i class="is-win" style="width:${wins / total * 100}%"></i><i class="is-loss" style="width:${losses / total * 100}%"></i></span></div></summary>
      <div class="match-list">${games.map(item).join('')}</div></details>`;
  }).join('');
}

/** 编辑对手队名：归到战队的局走战队分析统一改名，其余写 match_meta 覆盖层。 */
function opponentDialog(key, current, teamId) {
  const dialog = dialogFor();
  dialog.setAttribute('aria-labelledby', 'opponent-dialog-title');
  const linked = Boolean(teamId);
  dialog.innerHTML = `<form id="opponent-form" data-key="${esc(key)}" data-team-id="${esc(teamId || '')}"><div class="dialog-head"><div><h2 id="opponent-dialog-title">${linked ? '给对手战队改名' : '编辑对手队名'}</h2><p>${linked ? '队名由「战队分析」统一管理：改名后这支对手的全部对局同步更新（对局档案、系列赛编组、跨场分析都跟着变）。' : '只影响本机显示与统计，不改原始数据包；留空表示「对手未标注」。'}</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><label>对手战队/队名<input name="opponent" maxlength="50" value="${esc(current)}" placeholder="例如：漂流网咖" autofocus${linked ? ' required' : ''}></label>
    <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">${glyph('shield', { size: 18 })} 保存</button></div></form>`;
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
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">${glyph('shield', { size: 18 })} 保存到 ${fmt(targets.length)} 场</button></div></form>`;
  dialog.showModal();
  dialog.querySelector('input[name="opponent"]')?.focus();
}

/* 第一次打开、库里还没有对局时，先给三条把数据拿进来的路。
   这里不做「空状态」解释，教练此刻需要的是下一步动作。 */
function welcomePage() {
  return `<div class="page welcome-page">
    <section class="welcome-hero">
      ${glyph('capture', { size: 52 })}
      <span class="welcome-eyebrow">第一次使用</span>
      <h1>先把第一局拿进来</h1>
    </section>
    <div class="welcome-paths">
      <a class="welcome-path is-primary" href="#ingest">
        <span class="welcome-no">01 · 推荐</span>
        <b>${glyph('capture', { size: 20 })} 扫码采集</b>
        <em>适合已经在打训练赛</em>
      </a>
      <button class="welcome-path" data-action="open-client">
        <span class="welcome-no">02 · 复盘</span>
        <b>${glyph('arrow-up', { size: 20 })} 打开桌面客户端</b>
        <em>需要先安装客户端</em>
      </button>
      <a class="welcome-path" href="#capture">
        <span class="welcome-no">03 · 兜底</span>
        <b>${glyph('export', { size: 20 })} 导入表格 / 截图</b>
        <em>适合先补一局</em>
      </a>
    </div>
    <section class="welcome-foot">
      <div><span>数据目录</span><code data-welcome-dir>正在读取…</code></div>
      <div class="welcome-actions">
        <button class="control" data-action="open-data">${glyph('sources', { size: 18 })} 打开数据目录</button>
        <button class="control" data-action="refresh">${glyph('refresh', { size: 18 })} 重新检查数据</button>
      </div>
    </section>
    <div class="welcome-legacy" data-welcome-legacy hidden></div>
    <div class="welcome-migrate" data-migrate-progress hidden></div>
    <details class="welcome-other">
      <summary>旧数据在别的位置</summary>
      <div class="welcome-other-row">
        <input class="control" type="text" data-welcome-path spellcheck="false"
          placeholder="粘贴旧数据目录，例如 D:\\KPL训练赛项目\\data">
        <button class="control" data-action="migrate-path">${glyph('arrow-up', { size: 18 })} 搬到这台电脑</button>
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
          <button class="control is-primary" data-action="migrate-legacy" data-path="${esc(old.path)}">${glyph('arrow-up', { size: 18 })} 搬到这台电脑</button>
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
function showNoDataDialog() {
  const dialog = dialogFor();
  if (!dialog || dialog.open) return;
  dialog.classList.add('is-wide');
  dialog.innerHTML = `<div class="dialog-head"><div><h2>${glyph('warning', { size: 20 })} 还没有对局数据</h2>
    <p>这个工作台不自带比赛数据，先拿一局进来。</p></div>
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
  if (!view.matchFilters) view.matchFilters = { type: 'training', opponents: [], heroes: [], days: [], results: [], from: '', to: '' };
  /* 旧链接 / 旧本机记忆里没有胜负字段，补默认值，避免 undefined.length。 */
  if (!Array.isArray(view.matchFilters.results)) view.matchFilters.results = [];
  if (!view.matchFilters.type) view.matchFilters.type = 'training';
  return view.matchFilters;
}

function matchFiltersQuery(mf, search) {
  const params = new URLSearchParams();
  if (search) params.set('q', search);
  if (mf.type && mf.type !== 'training') params.set('type', mf.type);
  if (mf.opponents.length) params.set('opp', mf.opponents.join(','));
  if (mf.heroes.length) params.set('hero', mf.heroes.join(','));
  if (mf.days.length) params.set('day', mf.days.join(','));
  if (mf.results.length) params.set('res', mf.results.join(','));
  if (mf.from) params.set('from', mf.from);
  if (mf.to) params.set('to', mf.to);
  return params.toString();
}

function readMatchFiltersQuery() {
  const query = location.hash.split('?')[1] || '';
  if (!query) return null;
  const params = new URLSearchParams(query);
  const list = (name) => String(params.get(name) || '').split(',').map((x) => x.trim()).filter(Boolean);
  const type = String(params.get('type') || 'training');
  const mf = { type: ['training', 'all'].includes(type) ? type : 'training', opponents: list('opp'), heroes: list('hero'), days: list('day'), results: list('res'), from: String(params.get('from') || ''), to: String(params.get('to') || '') };
  const search = String(params.get('q') || '');
  if (!matchFiltersActive(mf) && !search && mf.type === 'training') return null;
  return { mf, search };
}

/* 筛选变化后把条件写回 URL（不触发 hashchange、不重载页面），并存一份本机记忆。 */
function syncMatchHash() {
  const mf = matchFilters();
  const query = matchFiltersQuery(mf, view.search || '');
  try {
    /* 类型切换（训练赛/正式比赛）不算「筛选条件」，但也要记住；其余条件只有
       真的选了才存，避免旧条件悄悄跟回来。 */
    if (matchFiltersActive(mf) || (mf.type && mf.type !== 'training')) localStorage.setItem(MF_STORAGE, JSON.stringify(mf));
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
      view.matchFilters = { type: 'training', opponents: [], heroes: [], days: [], results: [], from: '', to: '', ...saved };
      if (!['training', 'all'].includes(view.matchFilters.type)) view.matchFilters.type = 'training';
      syncMatchHash();
    }
  } catch {}
}

function matchFiltersActive(mf) {
  return Boolean(mf.opponents.length || mf.heroes.length || mf.days.length || mf.results.length || mf.from || mf.to);
}

/* 赛后笔记索引与标签数据都在档案页初始化时拉一次，统一搜索同时覆盖两者；
   取数失败就降级为空，不影响列表本身。 */
let archiveNotesPromise = null;
let archiveNotesMap = {};
function archiveNotes() {
  if (!archiveNotesPromise) {
    archiveNotesPromise = fetch(API_BASE + '/api/studio/notes', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => { archiveNotesMap = payload && payload.ok && payload.byMatch ? payload.byMatch : {}; return archiveNotesMap; })
      .catch(() => { archiveNotesMap = {}; return archiveNotesMap; });
  }
  return archiveNotesPromise;
}
function reloadArchiveNotes() { archiveNotesPromise = null; return archiveNotes(); }

/** 一处搜索覆盖对手、英雄、日期、标签、标签备注与教练笔记。 */
function matchSearchText(match) {
  const tags = tagsOf(match.key);
  const tagNotes = tagNotesOf(match.key);
  const notes = archiveNotesMap[match.key] || [];
  return [match.opponent, match.title, match.mode, match.date, match.startTime,
    ...(match.heroes || []), ...tags, ...tags.map((tag) => tagNotes[tag]),
    ...notes.map((note) => note && note.body)]
    .filter(Boolean).join(' ').toLowerCase();
}

function matchPasses(match, mf) {
  const heroes = match.heroes || [];
  /* 类型切换（2026-11-22 反馈）：训练赛与正式比赛分流存放，默认只看训练赛，
     切到「正式比赛」看线上表格录入的正式对局，「全部」合并两口径。 */
  const type = mf.type || 'training';
  if (type !== 'all') {
    const formal = (match.matchType || 'training') === 'formal';
    if (formal !== (type === 'formal')) return false;
  }
  if (mf.opponents.length) {
    const name = String(match.opponent || '').trim() || MF_NONE;
    if (!mf.opponents.includes(name)) return false;
  }
  if (mf.heroes.length && !mf.heroes.every((hero) => heroes.includes(hero))) return false;
  if (mf.results.length && !mf.results.includes(match.result || 'unknown')) return false;
  if (mf.days.length) {
    if (!mf.days.includes(String(match.date || ''))) return false;
  } else if (mf.from || mf.to) {
    const day = String(match.date || '');
    if (!day) return false;
    if (mf.from && day < mf.from) return false;
    if (mf.to && day > mf.to) return false;
  }
  /* 标签检索栏命中全库 key；只有真正选了标签或关键词时才收窄主列表。 */
  if (view.archiveTagKeys && !view.archiveTagKeys.has(match.key)) return false;
  return true;
}

/* 占位队名（待命名战队 #N）是签名聚类的显示兜底，不是对手：
   老数据升级后仍在，筛选项里出现它就会诱导教练按假队名筛。 */
const isPlaceholderOpponent = (name) => {
  const text = String(name || '').trim();
  return !text || /^待命名/.test(text);
};

function matchFacets(matches) {
  const opponents = new Map(), heroes = new Map(), days = new Map();
  for (const match of matches || []) {
    const name = isPlaceholderOpponent(match.opponent) ? MF_NONE
      : String(match.opponent).trim();
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
    ...mf.results.map((value) => chip('results', value, { win: '胜利', loss: '失利', draw: '平局', unknown: '结果未知' }[value] || value)),
    ...(mf.from || mf.to ? [chip('range', '*', [mf.from, mf.to].filter(Boolean).join(' ~ '))] : []),
  ].join('');
  /* 类型切换：正式比赛在线上表格录入后落到同一份档案库，这里按口径分流，
     训练赛和正式比赛互不混排；数字给到「正式比赛里有货」的提示。 */
  const typeCounts = { training: 0, formal: 0 };
  for (const match of data.matches || []) {
    const formal = (match.matchType || 'training') === 'formal';
    typeCounts[formal ? 'formal' : 'training'] += 1;
  }
  const seg = (value, label, count) => `<button type="button" class="mf-seg${(mf.type || 'training') === value ? ' is-on' : ''}" data-mf-type="${value}" aria-pressed="${(mf.type || 'training') === value}">${label}<b>${fmt(count)}</b></button>`;
  return `<div class="mfilter" data-filter-bar>
    <div class="mf-seg-group" role="group" aria-label="比赛类型">${seg('training', '训练赛', typeCounts.training)}${seg('all', '全部', typeCounts.training + typeCounts.formal)}</div>
    <div class="mf-pills">${pill('opponent', '对手', mf.opponents.length)}${pill('result', '胜负', mf.results.length)}${pill('hero', '英雄', mf.heroes.length)}${pill('day', '日期', mf.days.length)}${pill('tag', '标签', view.archiveTagKeys?.size || 0)}</div>
    ${chips ? `<div class="mf-chips" data-mf-chips>${chips}</div>` : '<div class="mf-chips" data-mf-chips></div>'}
    <span class="archive-tag-hint" data-archive-tag-count></span>
    <span class="mf-spacer"></span>
    <span class="mf-total">${active ? `${fmt(shown)} / 共 ${fmt(total)} 场` : `共 ${fmt(total)} 场`}</span>
    ${active ? '<button type="button" class="mf-clear" data-mf-clear>清除筛选</button>' : ''}
  </div>`;
}

function matchFilterPanel(kind) {
  const mf = matchFilters();
  /* 候选清单跟着当前类型走：训练赛视图里不把正式比赛的对手/日期混进来。 */
  const facets = matchFacets((data.matches || []).filter((m) => matchPasses(m, { ...mf, opponents: [], heroes: [], days: [], results: [] })));
  /* 标签检索与其他筛选同在主筛选栏里展开，不再单独占一整行。
     面板必须挂进 #content：match-tags.js 的自动挂载只观察这个容器。 */
  if (kind === 'tag') {
    return `<div class="mf-pop-head"><b class="mf-pop-title">标签检索 · 全库组合查找</b></div>
      <div class="pbr-tagbar mf-pop-tagbar" data-tagbar="archive"></div>`;
  }
  if (kind === 'opponent') {
    const rows = facets.opponents.map(([name, count]) => `<label class="mf-opt">
      <input type="checkbox" data-mf-opt="opponents" data-mf-value="${esc(name)}" ${mf.opponents.includes(name) ? 'checked' : ''}>
      <span class="mf-opt-main">${name === MF_NONE ? '对手未标注' : esc(name)}</span>
      <em>${fmt(count)} 局</em></label>`).join('');
    const noneCount = facets.opponents.find(([name]) => name === MF_NONE)?.[1] || 0;
    return `<div class="mf-pop-head"><input class="mf-q" data-mf-q="opponent" placeholder="搜索对手" aria-label="搜索对手"></div>
      <div class="mf-pop-list" data-mf-list><div class="mf-opt-empty">还没有填过对手队名</div>${rows}</div>
      <div class="mf-pop-foot"><span>可多选，命中任一对手</span><span class="mf-foot-btns">${noneCount ? `<button type="button" class="mf-bulk" data-mf-bulk>${glyph('edit', { size: 18 })} 批量补队名 (${fmt(noneCount)})</button>` : ''}<button type="button" data-mf-reset="opponents">清空</button></span></div>`;
  }
  if (kind === 'result') {
    const counts = { win: 0, loss: 0, unknown: 0 };
    for (const match of data.matches || []) {
      const key = ['win', 'loss'].includes(match.result) ? match.result : 'unknown';
      counts[key] += 1;
    }
    const labels = { win: '胜利', loss: '失利', unknown: '未记录胜负' };
    const rows = Object.entries(counts).map(([value, count]) => `<label class="mf-opt">
      <input type="checkbox" data-mf-opt="results" data-mf-value="${value}" ${mf.results.includes(value) ? 'checked' : ''}>
      <span class="mf-opt-main">${labels[value]}</span><em>${fmt(count)} 局</em></label>`).join('');
    return `<div class="mf-pop-head"><b class="mf-pop-title">胜负</b></div>
      <div class="mf-pop-list" data-mf-list>${rows}</div>
      <div class="mf-pop-foot"><span>可多选；统计随筛选重算</span><button type="button" data-mf-reset="results">清空</button></div>`;
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
      <div class="mf-pop-grid" data-mf-list>${rows}</div>
      <div class="mf-pop-foot"><span>${mf.heroes.length ? `已选 ${mf.heroes.length} 个 · 同一局同时出场` : ''}</span><button type="button" data-mf-reset="heroes">清空</button></div>`;
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
    <div class="mf-pop-foot"><span>按日期筛选</span><button type="button" data-mf-reset="days">清空</button></div>`;
}

/* 搜索命中用 CSS Custom Highlight 标出来，不改 DOM 结构、不碰事件委托。
   浏览器不支持时列表照常可用，只是没有黄色底纹。 */
function paintArchiveHighlights(routeName = current().name) {
  if (!('CSS' in window) || !CSS.highlights) return;
  CSS.highlights.delete('archive-search');
  const term = String(view.search || '').trim().toLowerCase();
  if (routeName !== 'matches' || !term) return;
  const ranges = [];
  document.querySelectorAll('[data-results] .archive-opponent b, [data-results] .tagchip, [data-results] .archive-when').forEach((host) => {
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const text = node.textContent.toLowerCase();
      let at = text.indexOf(term);
      while (at !== -1) {
        try {
          const range = new Range();
          range.setStart(node, at);
          range.setEnd(node, at + term.length);
          ranges.push(range);
        } catch { /* 节点在重绘中失效就跳过，不影响列表 */ }
        at = text.indexOf(term, at + term.length);
      }
      node = walker.nextNode();
    }
  });
  if (ranges.length) CSS.highlights.set('archive-search', new Highlight(...ranges));
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
  const bulkTags = document.querySelector('[data-archive-bulk-tags]');
  if (bulkTags) bulkTags.innerHTML = temp.querySelector('[data-archive-bulk-tags]')?.innerHTML || '';
  const tagOptions = document.querySelector('#archive-bulk-tag-options');
  if (tagOptions) tagOptions.innerHTML = temp.querySelector('#archive-bulk-tag-options')?.innerHTML || '';
  syncMatchHash();
  syncMatchFilterPills();
  paintArchiveHighlights();
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

/* ── 档案库：标签检索栏 / 标签变更 / 选局 ───────────────────────── */
document.addEventListener('match-tags:filter', (event) => {
  if (current().name !== 'matches') return;
  const { tags = [], keyword = '', keys = [] } = event.detail || {};
  const active = Boolean(tags.length || String(keyword).trim());
  view.archiveTagKeys = active ? new Set(keys) : null;
  /* refreshMatchResults 会重绘整个筛选栏，提示要放在重绘之后再写。 */
  refreshMatchResults();
  const label = document.querySelector('[data-archive-tag-count]');
  if (label) label.textContent = active ? `${tags.length} 个标签 · 命中 ${keys.length} 场` : '';
});

/* 折叠状态跟着筛选重绘走：原生 details 的 toggle 不冒泡，用捕获记下来。 */
document.addEventListener('toggle', (event) => {
  const day = event.target;
  if (!(day instanceof HTMLDetailsElement) || !day.matches('.archive-ledger details.fixture-day')) return;
  if (!view.archiveCollapsed) view.archiveCollapsed = new Set();
  if (day.open) view.archiveCollapsed.delete(day.dataset.archiveDay);
  else view.archiveCollapsed.add(day.dataset.archiveDay);
  try { sessionStorage.setItem(ARCHIVE_COLLAPSED_KEY, JSON.stringify([...view.archiveCollapsed])); } catch {}
}, true);

document.addEventListener('match-tags:change', (event) => {
  /* 只更新这一行的溢出计数，不整页重绘——否则刚点开的标签输入框会失焦。 */
  const key = event.detail?.key;
  if (key) {
    const row = document.querySelector(`.archive-row-wrap[data-match-key="${CSS.escape(key)}"] .tagrow`);
    if (row) {
      const hidden = (tagsOf(key) || []).slice(3);
      if (hidden.length) {
        row.dataset.tagMore = `+${hidden.length}`;
        row.title = `还有：${hidden.join('、')}`;
      } else {
        delete row.dataset.tagMore;
        row.removeAttribute('title');
      }
    }
    const star = document.querySelector(`.archive-row-wrap[data-match-key="${CSS.escape(key)}"] .archive-focus`);
    if (star) {
      const on = (tagsOf(key) || []).includes('重点');
      star.textContent = on ? '★' : '☆';
      star.setAttribute('aria-label', on ? '编辑这一局的重点关注' : '把这一局加入重点关注');
    }
  }
  if (current().name === 'matches' && view.archiveTagKeys) refreshMatchResults();
});

document.addEventListener('change', (event) => {
  const box = event.target.closest('[data-archive-check]');
  if (!box) return;
  if (!view.archiveSelected) view.archiveSelected = new Set();
  if (box.checked) view.archiveSelected.add(box.dataset.archiveCheck);
  else view.archiveSelected.delete(box.dataset.archiveCheck);
  const count = document.querySelector('[data-archive-selected]');
  if (count) count.textContent = `已选 ${fmt(view.archiveSelected.size)} 场`;
});

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
  const host = kind === 'tag' ? (document.querySelector('#content') || document.body) : document.body;
  host.appendChild(pop);
  const width = kind === 'tag' ? 460 : kind === 'hero' ? 384 : 320;
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
        pop.querySelector('.mf-pop-foot span').textContent = mf.heroes.length ? `已选 ${mf.heroes.length} 个 · 同一局同时出场` : '';
      }
    }
  }
}

function clearMatchFilter(kind) {
  const mf = matchFilters();
  if (kind === 'range') { mf.from = ''; mf.to = ''; }
  else if (kind) mf[kind] = [];
  else view.matchFilters = { opponents: [], heroes: [], days: [], results: [], from: '', to: '' };
  closeMatchFilter();
  refreshMatchResults();
}


/* 标签与笔记属于档案页的检索维度，但都是各自模块自取数。这里首次进入时等它们一次，
   到位后原地刷新结果区；后续增改标签/笔记由 match-tags:change 事件驱动。 */
let archiveDataPromise = null;
function ensureArchiveData() {
  if (archiveDataPromise) return archiveDataPromise;
  archiveDataPromise = Promise.all([tagsReady(), archiveNotes()]).then(() => {
    if (current().name === 'matches') refreshMatchResults();
  });
  return archiveDataPromise;
}

async function handleArchiveBulk(action) {
  const status = document.querySelector('[data-archive-bulk-status]');
  const say = (message) => { if (status) status.textContent = message; };
  if (action === 'exit') { view.archiveBatch = false; render(); return; }
  if (action === 'clear') {
    view.archiveSelected = new Set();
    document.querySelectorAll('[data-archive-check]').forEach((box) => { box.checked = false; });
    say('已清空选择');
    render();
    return;
  }
  if (action === 'select-all' || action === 'invert') {
    if (!view.archiveSelected) view.archiveSelected = new Set();
    document.querySelectorAll('[data-results] [data-archive-check]').forEach((box) => {
      const checked = action === 'select-all' ? true : !box.checked;
      box.checked = checked;
      if (checked) view.archiveSelected.add(box.dataset.archiveCheck);
      else view.archiveSelected.delete(box.dataset.archiveCheck);
    });
    say(`已选 ${fmt(view.archiveSelected.size)} 场`);
    const count = document.querySelector('[data-archive-selected]');
    if (count) count.textContent = `已选 ${fmt(view.archiveSelected.size)} 场`;
    return;
  }
  const input = document.querySelector('[data-archive-bulk-tag]');
  const tag = String(input?.value || '').trim().slice(0, 16);
  const keys = [...(view.archiveSelected || [])];
  if (!tag) { say('先填标签名'); input?.focus(); return; }
  if (!keys.length) { say('先勾选要处理的对局'); return; }
  const verb = action === 'remove' ? '移除' : '添加';
  say(`正在${verb}…`);
  try {
    const response = await fetch(API_BASE + '/api/v3/tags/bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(action === 'remove' ? { keys, remove: tag } : { keys, add: tag }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || '批量操作失败');
    }
    const result = await response.json().catch(() => ({}));
    await reloadTags();
    document.dispatchEvent(new CustomEvent('match-tags:change', { detail: {} }));
    if (input) input.value = '';
    say(`已${verb} ${fmt(result.changed ?? keys.length)} 场`);
    refreshMatchResults();
  } catch (error) {
    say(error.message || '批量操作失败');
  }
}

/** 行尾「备注」：沿用赛后笔记接口，不把 104 个笔记组件一次挂进列表。 */
async function openArchiveNote(key) {
  const dialog = dialogFor();
  if (dialog.open) dialog.close();
  dialog.classList.add('archive-note-dialog');
  dialog.setAttribute('aria-labelledby', 'archive-note-title');
  let draft = {};
  try { draft = JSON.parse(localStorage.getItem('training-note-draft:' + key) || '{}') || {}; } catch { draft = {}; }
  let lastAuthor = '';
  try { lastAuthor = localStorage.getItem('training-note-author') || ''; } catch { lastAuthor = ''; }
  dialog.innerHTML = `<form id="archive-note-form" data-key="${esc(key)}"><div class="dialog-head"><div>
    <h2 id="archive-note-title">${glyph('book', { size: 20 })} 教练备注</h2></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <section class="archive-note-history"><h3>已有备注</h3><p class="archive-note-loading">读取备注…</p></section>
      <section class="archive-note-compose"><h3>新增备注</h3>
        <label class="archive-note-field"><span>备注内容</span>
          <textarea name="body" rows="4" maxlength="4000" autofocus placeholder="例如：前期入侵失败，龙团沟通断点">${esc(draft.body || '')}</textarea></label>
        <small class="archive-note-draft-status" data-note-draft-status>${draft.body ? '草稿已自动保存在本机' : ''}</small>
        <label class="archive-note-field"><span>记录人（可留空）</span>
          <input name="author" maxlength="40" placeholder="本机操作者" value="${esc(draft.author || lastAuthor)}"></label>
      </section>
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">关闭</button>
      <button class="primary" type="submit">${glyph('book', { size: 18 })} 保存备注</button></div></form>`;
  dialog.showModal();
  try {
    const response = await fetch(API_BASE + '/api/studio/notes?match_key=' + encodeURIComponent(key));
    const payload = response.ok ? await response.json() : null;
    const notes = payload && payload.ok && Array.isArray(payload.notes) ? payload.notes : [];
    const host = dialog.querySelector('.archive-note-loading');
    if (!host.isConnected) return;
    host.className = 'archive-note-list';
    if (!notes.length) { host.textContent = '这场还没有备注。'; return; }
    host.innerHTML = notes.map((note) => `<article class="archive-note-item"><p>${esc(note.body)}</p>
      <footer><small>${esc(note.author || '未署名')}${note.updatedAt ? ` · ${esc(new Date(note.updatedAt * 1000).toLocaleString('zh-CN'))}` : ''}</small>
      <button type="button" data-archive-note-del="${esc(note.id)}" aria-label="删除这条备注">${glyph('trash', { size: 18 })} 删除</button></footer></article>`).join('');
  } catch {
    const host = dialog.querySelector('.archive-note-loading');
    if (host) host.textContent = '备注读取失败，可以直接在下方新增。';
  }
}

function matchesPage(value, key) {
  restoreMatchFilters();
  ensureArchiveData();
  const hero = key.startsWith('hero=') ? key.slice(5) : '';
  const mf = matchFilters();
  const keyword = String(view.search || '').trim().toLowerCase();
  const rows = value.matches
    .filter((m) => !hero || (m.heroes || []).includes(hero))
    .filter((m) => matchPasses(m, mf))
    .filter((m) => !keyword || matchSearchText(m).includes(keyword));
  const won = rows.filter((m) => m.result === 'win').length;
  const lost = rows.filter((m) => m.result === 'loss').length;
  const decided = won + lost;
  const rate = decided ? (won / decided) * 100 : 0;
  const dayCount = new Set(rows.map((m) => m.date).filter(Boolean)).size;
  /* 统计摘要压成一行：档案页的首屏属于比赛记录，不属于仪表盘。 */
  const summary = `<div class="match-overview archive-summary" aria-label="当前筛选结果统计">
    <span class="mo-cell"><small>对局</small><b>${fmt(rows.length)}</b><em>场</em></span>
    <span class="mo-cell"><small>战绩</small><b class="is-win">${fmt(won)}</b> 胜 <b class="is-loss">${fmt(lost)}</b> 负</span>
    <span class="mo-cell" title="胜率 = 胜场 ÷（胜场 + 负场），平局与未记录胜负不计入分母"><small>胜率</small><b>${decided ? pct(rate) : '—'}</b></span>
    <span class="mo-cell"><small>训练日</small><b>${fmt(dayCount)}</b><em>天</em></span>
    <span class="archive-summary-note">按当前筛选实时计算 · 全库 ${fmt(value.matches.length)} 场</span>
  </div>`;
  const selected = view.archiveSelected?.size || 0;
  return `<div class="page fixture-page archive-page">${pageIntro('单局分析')}
    ${summary}
    <section class="section fixture-ledger archive-ledger${view.archiveBatch ? ' is-batch' : ''}" aria-label="${hero ? esc(hero) + '的对局' : { training: '训练赛档案', formal: '正式比赛档案', all: '全部对局档案' }[mf.type || 'training']}">
      <div class="mf-toolbar archive-toolbar">
        <label class="search mf-search">${icon('search')}<input type="search" name="search" value="${esc(view.search || '')}" placeholder="搜对手 / 英雄 / 标签 / 备注" aria-label="搜索对局"></label>
        ${matchFilterBar(value.matches.length, rows.length)}
        <button type="button" class="archive-batch-toggle${view.archiveBatch ? ' is-on' : ''}" data-archive-batch aria-pressed="${Boolean(view.archiveBatch)}">${glyph('book', { size: 18 })} 批量打标签</button>
      </div>
      <div class="archive-list-head">
        <div class="archive-sort" role="group" aria-label="对局排序">
          <span class="archive-sort-label">排序</span>
          ${ARCHIVE_SORTS.map((item) => `<button type="button" class="archive-sort-btn${archiveSortKey() === item.key ? ' is-on' : ''}" data-archive-sort="${item.key}" aria-pressed="${archiveSortKey() === item.key}" title="${item.hint}">${item.label}</button>`).join('')}
        </div>
      </div>
      <p class="visually-hidden" role="status" data-archive-sort-status></p>
      <div class="archive-bulkbar" data-archive-bulkbar${view.archiveBatch ? '' : ' hidden'}>
        <div class="archive-bulk-library"><span>标签库</span>
          <div class="archive-bulk-tags" data-archive-bulk-tags>${vocabulary().length
            ? vocabulary().slice(0, 12).map((item) => `<button type="button" data-archive-bulk-tag-name="${esc(item.name)}" title="${fmt(item.count)} 场">${esc(item.name)}</button>`).join('')
            : `<span class="archive-bulk-empty">${glyph('book', { size: 18 })} 还没有标签</span>`}</div>
        </div>
        <datalist id="archive-bulk-tag-options">${vocabulary().map((item) => `<option value="${esc(item.name)}"></option>`).join('')}</datalist>
        <b data-archive-selected>已选 ${fmt(selected)} 场</b>
        <button type="button" data-archive-select-all data-archive-bulk="select-all">${glyph('pick', { size: 18 })} 全选当前结果</button>
        <button type="button" data-archive-bulk="invert">反选</button>
        <label><span>标签名</span><input type="text" data-archive-bulk-tag maxlength="16" placeholder="点上面的标签或输入新标签" aria-label="批量操作的标签名" list="archive-bulk-tag-options" autocomplete="off"></label>
        <button type="button" class="primary" data-archive-bulk="add">${glyph('book', { size: 18 })} 添加到所选</button>
        <button type="button" data-archive-bulk="remove">${glyph('trash', { size: 18 })} 从所选移除</button>
        <button type="button" data-archive-bulk="clear">${glyph('ban', { size: 18 })} 清空选择</button>
        <button type="button" data-archive-bulk="exit">${glyph('arrow-up', { size: 18 })} 退出批量</button>
        <span class="archive-bulk-status" data-archive-bulk-status role="status"></span>
      </div>
      <div data-results>${matchRows(rows, dayNumbers(value.matches))}</div></section></div>`;
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
  const emptyRoster = `<div class="empty">${glyph('players', { size: 52 })}<strong>本队名单还没建立</strong><p>名单取自建档，表现只统计已认领身份。</p><p><a class="primary" href="#profiles">${glyph('players', { size: 18 })} 去建档</a></p></div>`;
  return `<div class="page">${pageIntro('名单与状态')}
    <div class="analysis-observation"><span>结论</span><p>${esc(brief)}</p></div>
    ${unbound.length ? `<div class="scope-note"><span>身份待认领</span>还有 ${fmt(unbound.length)} 个昵称没有并入名单（${fmt(summary.unboundGames)} 局），不计入名单、状态与排名。命名入口在下方「待命名」。</div>` : ''}
    <section class="section"><div class="section-heading"><div><h2>名单与轮换</h2><p>位置取自名单；出场为当前范围内的已认领记录</p></div><a href="#identity">管理名单 ${icon('arrow')}</a></div>
      <div class="player-card-grid">${roster.map(card).join('') || emptyRoster}</div>
      ${bench.length ? `<p class="roster-bench"><span>本期未出场</span>${bench.map((p) => esc(p.label) + (p.position ? '（' + esc(p.position) + '）' : '')).join('、')}</p>` : ''}</section>
    ${unbound.length ? `<section class="section"><div class="section-heading"><div><h2>待命名</h2></div></div>
      <div class="name-queue">${unbound.map((item) => `<div class="name-row"><span class="nm">${esc(item.label)}</span><span class="meta">${fmt(item.games)} 局${item.lastDate ? ' · 最近 ' + esc(shortDate(item.lastDate)) : ''}</span><button class="primary" data-action="name-player" data-label="${esc(item.label)}">${glyph('players', { size: 18 })} 命名并归队</button></div>`).join('')}</div></section>` : ''}
    <div class="split-panels">
      <section class="section"><div class="section-heading"><div><h2>状态变化</h2><p>同一名选手近 3 场与此前 3 场的营地评分，不跨选手排名</p></div></div>
        ${formRows ? `<div class="form-rows"><div class="form-row head"><span>选手</span><span>位置</span><span>此前</span><i></i><span>近 3 场</span><span>变化</span><span>判断</span></div>${formRows}</div>` : `<div class="empty">${glyph('chart', { size: 52 })}<strong>状态样本不足</strong><p>${(value.form || []).some((item) => item.samples) ? '还没有已认领选手的评分记录。' : '当前范围的记录还没有营地评分，状态要等评分数据补齐。'}</p></div>`}
        <p class="section-note">少于 6 场不给趋势结论；评分来自营地结算。</p></section>
      <section class="section"><div class="section-heading"><div><h2>搭档</h2><p>同场 3 场以上的双人组合，只用已认领身份</p></div></div>
        ${pairRows ? `<div class="pair-rows">${pairRows}</div>` : '<div class="empty">同场 3 场以上的固定组合还不够。</div>'}
        <p class="section-note">同场指同一局同时出场，未要求完整五人阵容。${pairs.length > 1 && pairs.every((pair) => pair.games === pairs[0].games) ? ' 当前这套阵容基本固定，组合之间没有差别。' : ''}</p></section>
    </div>
    <section class="section"><div class="section-heading"><div><h2>已认领选手数据</h2><p>${bound.length} 名已认领选手；未认领昵称不计入</p></div></div>
      ${bound.length ? `<details class="table-disclosure"><summary>查看数据明细 <span>${bound.length} 名</span></summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>选手</th><th>位置</th><th>出场</th><th>胜率</th><th>KDA</th><th>分均经济</th><th>分均输出</th><th>参团率</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>` : `<div class="empty">${glyph('players', { size: 52 })}<strong>还没有已认领选手</strong><p><a class="control" href="#profiles">${glyph('players', { size: 18 })} 去认领昵称</a></p></div>`}
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
    <span class="md-crumb-actions">${p && !p.bound ? `<button class="primary" data-action="name-player" data-label="${esc(label)}">${glyph('players', { size: 18 })} 命名并归队</button>` : ''}<button class="control" data-action="filter">${glyph('calendar', { size: 18 })} 筛选范围</button><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${glyph('refresh', { size: 18 })}</button></span>
  </div>`;
  const claim = !p ? '当前范围没有该选手的数据'
    : p.bound ? `${p.label} 在 ${lane} 出场 ${fmt(games)} 局，胜率 ${pct(p.winRate)}`
    : `「${p.label}」还没命名，${fmt(games)} 局的记录暂时挂在这个昵称下`;
  const fact = !p ? ''
    : p.bound ? `KDA ${fmt(p.kda, 1)} · 分均经济 ${fmt(p.gpm, 1)} · 参团率 ${pct(p.participation)}`
    : '记录暂按昵称统计，归队后并入选手档案';
  const hero = `<section class="md-hero">
    <div class="md-hero-head"><span class="md-hero-kicker">${p && p.bound ? '选手结论' : '身份待定'}</span><span class="md-hero-meta">${[lane, p && p.bound ? '已归队' : '待命名'].filter(Boolean).map(esc).join(' · ')}</span></div>
    <h1><b>${esc(claim)}</b>${fact ? `<span>${esc(fact)}</span>` : ''}</h1>
    <div class="md-line">
      <div class="md-line-side"><span>出场</span><b>${fmt(games)} 局</b></div>
      <div class="md-line-mid"><strong>${fmt(p && p.kda, 1)}<i>KDA</i></strong><div class="md-line-note"><em class="${p && p.winRate >= 50 ? 'win' : 'loss'}">${pct(p && p.winRate)}</em><span>胜率</span></div></div>
      <div class="md-line-side rival"><span>分均经济</span><b>${fmt(p && p.gpm, 1)}</b></div>
    </div>
    <p>口径：当前数据范围内的本队记录；营地面板与回放来源分开统计，未归队时只按这个昵称算。</p>
  </section>`;
  return `<div class="page md-page">${crumb}${hero}
    <section class="section"><div class="section-heading"><div><h2>状态</h2><p>同一名选手近 3 场与此前 3 场的营地评分</p></div></div>${formHtml}</section>
    ${heroes.length ? `<section class="section"><div class="section-heading"><div><h2>常用英雄</h2></div></div><div class="hero-chips player-heroes">${heroes.map((h) => `<span>${portrait(h.hero)}${esc(h.hero)} <small>${fmt(h.matches)} 局</small></span>`).join('')}</div></section>` : ''}
    <section class="section"><div class="section-heading"><div><h2>近期对局</h2></div><a href="#players">返回选手</a></div>
    <div class="player-history">${[...value.points].reverse().slice(0,8).map(m=>`<a href="${esc(route('match',m.matchKey))}"><span>${esc(m.date||'日期未知')}</span>${portrait(m.hero)}<b>${esc(m.hero||'未知英雄')}</b><small>${esc(m.opponent||'对手未标注')}</small><strong>${fmt(m.kda,1)} <i>KDA</i></strong></a>`).join('')||'<div class="empty">暂无逐局记录。</div>'}</div><details class="table-disclosure"><summary>查看全部逐局 <span>${rows.length} 条</span></summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>日期</th><th>对手</th><th>英雄</th><th>赛果</th><th>KDA</th><th>分均经济</th><th>分均输出</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details></section></div>`;
}

const OPP_LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

function opponentsPage(value) {
  /* 本队战队也在 teams 主数据里（对局要引用它），但不能出现在「对方战队」
     列表里：那张卡带删除按钮，而删除会连本队选手 ID 和账号映射一起清掉。 */
  const ownId = String(value.ownTeamId || '');
  const teams = [...(value.teams || [])]
    .filter((t) => String(t.id || '') !== ownId)
    .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh'));
  const players = (value.players || []).filter((p) => p.status !== 'archived');
  const playerCard = (p) => {
    const key = (p.name && p.name !== p.camp_user_id ? p.name : p.camp_user_id) || '';
    return `<article class="opp-player">
      <span class="opp-player-avatar" aria-hidden="true">${esc(String(p.camp_user_id || '?').slice(0, 1))}</span>
      <a class="opp-player-main" href="#playerdetail/${encodeURIComponent(key)}" title="打开选手分析">
        <b>ID ${esc(p.camp_user_id || '—')}</b>
        <small>${esc(p.name && p.name !== p.camp_user_id ? p.name : '姓名未填')}</small></a>
      <div class="opp-player-ops">
        <button type="button" class="control" data-opp-player-edit="${esc(p.id || '')}" aria-label="编辑选手 ${esc(p.camp_user_id || p.name || '')}">${glyph('edit', { size: 13 })}</button>
        <button type="button" class="control is-danger" data-opp-player-del="${esc(p.id || '')}" aria-label="删除选手 ${esc(p.camp_user_id || p.name || '')}">${glyph('trash', { size: 13 })}</button>
      </div></article>`;
  };
  const teamCard = (t) => {
    const roster = players.filter((p) => p.team_id === t.id);
    const lanes = OPP_LANES.map((lane) => {
      const list = roster.filter((p) => (p.position || '') === lane);
      return `<div class="opp-lane"><div class="opp-lane-head">
        <b><img class="opp-lane-icon" src="${KPL_SVG}modules/role-icon-${LANE_SVG[lane] || 'holder-blank'}.svg" alt="" aria-hidden="true">${esc(lane)} <span class="opp-lane-count">${list.length}</span></b>
        <button type="button" class="control" data-opp-player-add="${esc(t.id || '')}" data-opp-lane="${esc(lane)}">${glyph('players', { size: 13 })} 添加选手</button>
      </div><div class="opp-player-list">${list.map(playerCard).join('') || '<p class="opp-empty">还没有选手</p>'}</div></div>`;
    }).join('');
    return `<section class="opp-team-card" aria-labelledby="opp-team-${esc(t.id || '')}">
      <header class="opp-team-head"><div>
        <span class="opp-eyebrow">${glyph('opponent', { size: 14 })} 对方战队</span>
        <h2 id="opp-team-${esc(t.id || '')}">${esc(t.name || '未命名战队')}</h2>
        <p class="opp-team-meta">${esc(t.league || '层级未填')} · 主教练 ${esc(t.coach || '未填')}${t.aliases && t.aliases.length ? ` · 别名 ${esc(t.aliases.join(' / '))}` : ''}</p>
      </div><div class="opp-team-ops">
        <button type="button" class="control" data-opp-team-edit="${esc(t.id || '')}" aria-label="编辑战队 ${esc(t.name || '')}">${glyph('edit', { size: 14 })} 编辑</button>
        <button type="button" class="control is-danger" data-opp-team-del="${esc(t.id || '')}" aria-label="删除战队 ${esc(t.name || '')}">${glyph('trash', { size: 14 })} 删除</button>
      </div></header>
      <div class="opp-lanes">${lanes}</div></section>`;
  };
  return `<div class="page feature-page opp-page">
    <div class="opp-page-head"><h1>对方战队</h1>
      <button type="button" class="primary" data-opp-team-add>${glyph('opponent', { size: 16 })} 创建对手战队</button></div>
    ${teams.length ? `<div class="opp-team-grid">${teams.map(teamCard).join('')}</div>`
      : `<div class="empty opp-page-empty">${glyph('opponent', { size: 52 })}<strong>还没有对手战队</strong><p><button type="button" class="primary" data-opp-team-add>${glyph('opponent', { size: 18 })} 创建对手战队</button></p></div>`}
  </div>`;
}

function oppTeamDialog(team) {
  const dialog = dialogFor();
  dialog.setAttribute('aria-labelledby', 'opp-team-dialog-title');
  const edit = Boolean(team);
  dialog.innerHTML = `<form id="opp-team-form" data-team-id="${esc(team?.id || '')}"><div class="dialog-head"><div>
    <h2 id="opp-team-dialog-title">${glyph('opponent', { size: 20 })} ${edit ? '编辑对手战队' : '创建对手战队'}</h2></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <label for="opp-team-name">战队名称 <em>必填</em></label>
      <input id="opp-team-name" name="name" required maxlength="50" value="${esc(team?.name || '')}" autofocus>
      <label for="opp-team-short">简称</label><input id="opp-team-short" name="shortName" maxlength="20" value="${esc(team?.short_name || '')}">
      <label for="opp-team-league">层级 / 联赛</label><input id="opp-team-league" name="league" maxlength="50" value="${esc(team?.league || '')}" placeholder="例如：KPL / 次级联赛">
      <label for="opp-team-coach">主教练</label><input id="opp-team-coach" name="coach" maxlength="50" value="${esc(team?.coach || '')}">
      <label for="opp-team-alias">别名（逗号分隔）</label><input id="opp-team-alias" name="aliases" maxlength="200" value="${esc((team?.aliases || []).join(', '))}">
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button>
      <button class="primary" type="submit">${glyph('shield', { size: 18 })} ${edit ? '保存修改' : '创建战队'}</button></div></form>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
  dialog.querySelector('#opp-team-name')?.focus();
}

function oppPlayerDialog(player, teamId, lane) {
  const dialog = dialogFor();
  dialog.setAttribute('aria-labelledby', 'opp-player-dialog-title');
  const edit = Boolean(player);
  dialog.innerHTML = `<form id="opp-player-form" data-player-id="${esc(player?.id || '')}" data-team-id="${esc(player?.team_id || teamId || '')}"><div class="dialog-head"><div>
    <h2 id="opp-player-dialog-title">${glyph('players', { size: 20 })} ${edit ? '编辑对方选手' : '添加对方选手'}</h2></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <label for="opp-player-id">选手 ID <em>必填 · 不可重复</em></label>
      <input id="opp-player-id" name="campUserId" required maxlength="80" value="${esc(player?.camp_user_id || '')}" placeholder="他在这个战队里用的 ID" autofocus>
      <label for="opp-player-name">真实姓名（可选）</label>
      <input id="opp-player-name" name="name" maxlength="50" value="${esc(player?.name && player.name !== player.camp_user_id ? player.name : '')}" placeholder="不知道可以留空">
      <label for="opp-player-lane">分路</label>
      <select id="opp-player-lane" name="position"><option value="">未指定</option>${OPP_LANES.map((x) => `<option value="${esc(x)}"${(player?.position || lane) === x ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select>
      <label for="opp-player-role">身份</label>
      <select id="opp-player-role" name="role"><option value="main"${(player?.role || 'main') === 'main' ? ' selected' : ''}>首发</option><option value="sub"${player?.role === 'sub' ? ' selected' : ''}>替补</option></select>
      <label for="opp-player-alias">别名（逗号分隔）</label><input id="opp-player-alias" name="aliases" maxlength="200" value="${esc((player?.aliases || []).join(', '))}">
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button>
      <button class="primary" type="submit">${glyph('shield', { size: 18 })} ${edit ? '保存修改' : '添加选手'}</button></div></form>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
  dialog.querySelector('#opp-player-id')?.focus();
}

function oppConfirm(message, onConfirm) {
  const dialog = dialogFor();
  dialog.setAttribute('aria-labelledby', 'opp-confirm-title');
  dialog.innerHTML = `<div class="dialog-head"><div><h2 id="opp-confirm-title">${glyph('warning', { size: 20 })} 确认删除</h2>
    <p>${esc(message)}</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close" autofocus>取消</button>
      <button type="button" class="primary is-danger" data-opp-confirm-ok>${glyph('trash', { size: 18 })} 确认删除</button></div>`;
  dialog.querySelector('[data-opp-confirm-ok]')?.addEventListener('click', () => {
    dialog.close();
    onConfirm();
  }, { once: true });
  if (dialog.open) dialog.close();
  dialog.showModal();
  dialog.querySelector('[data-action="close"]')?.focus();
}

function tempoPage(value) {
  const a = value.process.aggregate;
  const p = value.process.matches[0];
  const anchor = current().anchor;
  const rows = value.process.matches.map((m) => [`<a class="text-link" href="${esc(route('match', m.key))}">${esc(m.date || '日期未知')}　${esc(m.opponent || '未标注')}</a>`,
    pct(m.coverage), diff(m.diffAt['600']), diff(m.finalDiff), fmt(m.killsPerMinute,1)]);
  return `<div class="page">${pageIntro('节奏分析')}
    ${gameAnchorBar()}
    <div class="stats-band"><div><span>可分析对局</span><strong>${fmt(a.games)}</strong><p>时间轴覆盖 ≥ 60%</p></div>
    <div><span>10 分钟经济差</span><strong>${diff(a.avgDiffAt['600'])}</strong><p>${a.landmarkSamples['600']} 局可用</p></div>
    <div><span>领先转胜率</span><strong>${pct(a.leadAt10Conversion)}</strong><p>${a.leadAt10Games} 局领先且有胜负</p></div>
    <div><span>落后后获胜</span><strong>${a.landmarkSamples['600'] ? fmt(a.comebacks) : '—'}</strong><p>10 分钟时点</p></div></div>
    <section class="section"><div class="section-heading"><div><h2>最近可用经济曲线</h2><p>${p ? esc(p.date || '') : '暂无样本'}</p></div></div>
    ${chart(p?.points, '本队经济差')}</section>
    <section class="section"><div class="section-heading"><div><h2>逐局经济走势</h2><p>本队减去对手 · 展示最近 9 场有时间轴的对局</p></div></div>
    <div class="tempo-card-grid">${value.process.matches.slice(0,9).map(m=>`<a class="tempo-card${anchor===m.key?' is-anchor':''}" href="${esc(route('match',m.key))}"><div><span>${esc(m.date||'日期未知')}</span><small>${esc(m.opponent||'对手未标注')}</small></div><h3>末次经济差 <strong>${diff(m.finalDiff)}</strong></h3>${microChart(m.points,'本队经济差')}<p><span>${time(m.observedStart)} — ${time(m.observedEnd)}</span><span>覆盖 ${pct(m.coverage)}</span></p></a>`).join('')||`<div class="empty">${glyph('chart', { size: 52 })}<strong>当前范围暂无可用时间轴</strong><p>这批对局还没有可用的逐分钟经济采样。</p></div>`}</div>
    ${table(['对局', '时间轴覆盖', '10 分钟经济差', '最后采样经济差', '分均击杀'], rows)}</section></div>`;
}

/* 旧的 sourcesPage（字段覆盖率 / 来源计数）已由自取数的「数据源展示」模块替代，
   页面逻辑见 datasource-page.js，接口见 /api/studio/workspace/data-map。 */

/* 10 分钟经济的分路阈值（赛训组 2026-11-14 口径）：
   对抗路 / 发育路 6800 及格、7000 良好、7400 优秀（10 分钟总量）；
   中路 550/分钟 达标即可 → 5500；打野分野核（800/分钟 → 8000）与坦野（6800 总量），
   打野类型优先看本局出的打野刀（肉刀=坦野/红刀法刀=野核），拿不到才退回 heroTypes；游走不记录。
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
function gold10Grade(lane, value, hero, player) {
  /* 10 分钟经济来自教练手填的 coach detail，不是规则中心的字段白名单成员；
     这里保持独立硬编码口径，不走 fieldGrade（以前那次调用永远拿不到规则）。 */
  const defs = lane === '打野'
    ? GOLD10_JUNGLE[jungleKindOf(hero, player)]
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
    <a class="md-back" href="#matches"><span aria-hidden="true">←</span> 单局分析</a>
    <span class="md-crumb-meta">${[m.date || '日期未知', m.mode, hasDuration ? time(m.duration) : ''].filter(Boolean).map((x) => `<i>${esc(x)}</i>`).join('')}</span>
    <div class="tagrow" data-tag-key="${esc(m.key || current().key || '')}"></div>
    <span class="md-crumb-actions"><button class="control" data-action="filter">${glyph('calendar', { size: 18 })} 筛选范围</button><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${glyph('refresh', { size: 18 })}</button></span>
  </div>`;
  const outcome = m.result === 'win' ? '收下这一局' : m.result === 'loss' ? '交出这一局' : '结束这一局';
  const heroWhen = hasDuration ? ` ${time(m.duration)} ` : '';
  /* 结论句不用「最大相邻波动」：那是 30 个噪声差分里的极值，天然会大。
     改成 10 分钟与终局的两次快照，回答「这局怎么走到终局」。 */
  const gapAt10 = goldAt(600);
  const hasGap = Number.isFinite(gapAt10) && Number.isFinite(finalDiff);
  const gapText = (value) => value === 0 ? '持平' : `${value > 0 ? '领先' : '落后'} ${fmt(Math.abs(value))}`;
  /* 结论句里的数字单独加粗（设计稿：10 分钟落后 <b>3,604</b>，终局领先 <b>3,382</b>） */
  const claimHtml = hasGap
    ? `10 分钟${gapText(gapAt10).replace(/(\d[\d,]*)/, '<b>$1</b>')}，终局${gapText(finalDiff).replace(/(\d[\d,]*)/, '<b>$1</b>')}`
    : esc(`本队${heroWhen}以 ${plainScore} ${outcome}`);
  const heroFact = hasGap
    ? `本队${heroWhen}以 ${plainScore} ${outcome} · 10 分钟差取 600 秒最近采样，终局差取末次采样；均非因果`
    : `回放记录 ${events.length} 条事件`;
  const winSide = m.result === 'win' ? 'own' : m.result === 'loss' ? 'rival' : '';
  /* 比赛脉搏放进本局结论（2026-11-14）：结论卡内直接给整局经济差曲线与资源事件标记，
     总量条紧随其后。回放事件是异步到达的，#match-verdict 会被整块替换（见 load()）。 */
  /* 脉搏：保留前端真实数据 SVG + 悬停交互，套设计稿 readout / legend 骨架 */
  const pulseBlock = `<div class="dv-pulse" id="match-pulse">
      <span class="dv-kicker">比赛脉搏</span>
      ${series.length ? mods.deep.pulse(series, events.map((e) => ({ ...e, label: eventLabel(e) })), m.duration, { own, ownName: metadata.teamName || '本队', foeName: m.opponent || '对手' }) : '<div class="md-ov-empty">阵营未知，无法展示本队视角的经济差。</div>'}
      <div class="dv-legend"><span><i class="own"></i>本队</span><span><i class="foe"></i>对手</span><span><i class="dia"></i>龙</span><span><i class="buff"></i>BUFF</span><span><i class="sq"></i>防御塔</span><span><i class="sq"></i>水晶</span></div>
    </div>`;
  /* ── 新首屏（2026-11-22 图三版式）────────────────────────────────────
     比分头 → 镜像 Pick/Ban → 经济/资源 → 五路对位表 → 比赛脉搏。
     原「结论卡 / 总量 / 双方阵容 / 对位压制」四块合并成这一张卡；
     五路表的「详细数据」就地展开该路对位卡片，十人面板仍留在「十人数据」页签。 */
  const ownCamp = ({ left: 'blue', right: 'red' })[own] || own;
  const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';
  const ownSideKey = (own === 'red' || own === 'right') ? 'right' : 'left';
  const enemySideKey = ownSideKey === 'left' ? 'right' : 'left';
  const banSlotCount = Math.max((draft?.bans?.left || []).length, (draft?.bans?.right || []).length);
  /* 总量按十人面板逐人求和（详情接口不带 own/enemy 汇总）。 */
  const teamAgg = (camp) => ({
    gold: teamTotal(m.players, camp, 'gold'), kills: teamTotal(m.players, camp, 'kills'),
    damage: teamTotal(m.players, camp, 'damage'), taken: teamTotal(m.players, camp, 'taken'),
  });
  const ownAgg = teamAgg(ownCamp), foeAgg = teamAgg(foeCamp);
  const msName = metadata.teamName || '本队';
  const msFoe = m.opponent || '对手';
  const msCrest = (name) => esc((String(name || '?').trim()[0] || '?'));
  const msCross = `<svg class="ms-cross" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3.5 8.6 5l9.9 9.9L20 20l-1.2-5.6L8.9 4.5 4 3.5Z"/><path d="M20 3.5 15.4 5l-9.9 9.9L4 20l1.2-5.6 9.9-9.9L20 3.5Z"/></svg>`;
  const msNum = (value) => {
    const raw = String(value ?? '').replace(/,/g, '').trim();
    return raw ? Number(raw) : NaN;
  };
  const msOwnScore = msNum(scoreParts[0]), msFoeScore = msNum(scoreParts[1]);
  const msScoreKnown = Number.isFinite(msOwnScore) && Number.isFinite(msFoeScore);
  const msResultKnown = msScoreKnown || ['win', 'loss', 'draw'].includes(m.result);
  const msDraw = msScoreKnown ? msOwnScore === msFoeScore : m.result === 'draw';
  const msOwnWon = msScoreKnown ? msOwnScore > msFoeScore : m.result === 'win';
  const msBadge = (won) => !msResultKnown ? ['is-draw', '—'] : msDraw ? ['is-draw', '平局'] : won ? ['is-win', '胜利'] : ['is-loss', '失败'];
  const [msOwnBadgeCls, msOwnBadgeText] = msBadge(msOwnWon);
  const [msFoeBadgeCls, msFoeBadgeText] = msBadge(msScoreKnown ? msFoeScore > msOwnScore : m.result === 'loss');
  const msGold = (value) => has(value) ? (value >= 1000 ? `${(value / 1000).toFixed(1)}k` : fmt(value)) : '—';
  const msHeroArt = (h) => {
    const icon = h?.icon || metadata.icons?.[h?.name];
    return icon && /^\/catalog\/icons\/hero-\d+\.png$/.test(icon)
      ? `<img class="portrait" src="${esc(icon)}" alt="${esc(h?.name || '')}" loading="lazy">`
      : portrait(h?.name);
  };
  const msHero = (h, kind, index) => {
    if (!h) return '<span class="ms-hero is-empty" aria-hidden="true"></span>';
    const known = kind === 'ban' ? draft?.banOrderKnown : draft?.pickOrderKnown;
    const order = known ? `${kind === 'ban' ? 'B' : 'P'}${index + 1} · ` : '';
    return `<a class="ms-hero ${kind === 'ban' ? 'is-ban' : 'is-pick'}" href="${esc(route('hero', h.name))}" title="${esc(order + h.name)}" aria-label="${esc(order + h.name)}">${msHeroArt(h)}</a>`;
  };
  const msStrip = (list, kind) => Array.from({ length: 5 }, (_, i) => msHero(list[i], kind, i)).join('');
  /* 资源行只统计回放里真有的事件；没有回放时留空，不拿 0 冒充「没拿龙」。
     killerCamp 历史上有 blue/red 与 left/right 两套写法，统一归一后再比。 */
  const msCamp = (value) => normalizedCamp(value);
  const msRes = (camp) => (events.length ? {
    tyrant: events.filter((e) => e.kind === 'resource' && msCamp(e.killerCamp) === msCamp(camp) && /暴君/.test(eventLabel(e))).length,
    lord: events.filter((e) => e.kind === 'resource' && msCamp(e.killerCamp) === msCamp(camp) && /主宰/.test(eventLabel(e))).length,
    towers: events.filter((e) => e.kind === 'structure' && msCamp(e.killerCamp) === msCamp(camp) && !/水晶/.test(eventLabel(e))).length,
  } : null);
  const msOwnRes = msRes(ownCamp), msFoeRes = msRes(foeCamp);
  const msResItem = (icon, label, count) => `<span class="ms-res-item" title="${esc(label)}"><img src="static/resicon/${icon}" alt=""><b>${has(count) ? fmt(count) : '—'}</b><small>${esc(label)}</small></span>`;
  const msResGroup = (res, side) => {
    const items = side === 'own'
      ? [['resicon_tyrant_v4.png', '暴君', res?.tyrant], ['resicon_lord_v4.png', '主宰', res?.lord], ['resicon_tower_v4.png', '防御塔', res?.towers]]
      : [['resicon_tower_v4.png', '防御塔', res?.towers], ['resicon_lord_v4.png', '主宰', res?.lord], ['resicon_tyrant_v4.png', '暴君', res?.tyrant]];
    return items.map(([icon, label, count]) => msResItem(icon, label, count)).join('');
  };
  const msLanes = ['对抗路', '打野', '中路', '发育路', '游走'];
  const msLaneOf = (p) => msLanes.includes(p.position) ? p.position : '游走';
  const msByLane = (camp) => {
    const map = new Map();
    const target = msCamp(camp);
    for (const p of (m.players || [])) {
      if (msCamp(p.camp) !== target) continue;
      const lane = msLaneOf(p);
      if (!map.has(lane)) map.set(lane, p);
    }
    return map;
  };
  const msOwnLanes = msByLane(ownCamp), msFoeLanes = msByLane(foeCamp);
  const msMaxDamage = Math.max(1, ...(m.players || []).map((p) => Number(p.damage) || 0));
  const msMaxGold = Math.max(1, ...(m.players || []).map((p) => Number(p.gold) || 0));
  const msBar = (value, max) => {
    const n = Number(value) || 0;
    return n > 0 ? `${Math.max(4, Math.round(n / max * 100))}%` : '0%';
  };
  const msKda = (p) => `${fmt(p.kills)}/${fmt(p.deaths)}/${fmt(p.assists)}`;
  /* 出装：优先回放 builds，其次营地面板 equipment / 截图 OCR 候选；最多 6 件。 */
  const msEquipNames = (p) => {
    const names = [];
    const push = (raw) => {
      const name = String(raw || '').trim();
      if (name && !names.includes(name)) names.push(name);
    };
    const fromItem = (item) => push(typeof item === 'string' ? item
      : (item?.name || item?.itemName || item?.equipName
         || (Array.isArray(item?.candidates) ? item.candidates[0]?.name : '')));
    if (Array.isArray(p?.builds)) p.builds.forEach(fromItem);
    const equip = p?.equipment;
    if (Array.isArray(equip)) equip.forEach(fromItem);
    else if (equip && typeof equip === 'object' && Array.isArray(equip.slots)) equip.slots.forEach(fromItem);
    else if (typeof equip === 'string') equip.split(/[,，\s]+/).forEach(push);
    return names.slice(0, 6);
  };
  const msLaneItems = (p) => {
    const items = msEquipNames(p).map((name) => {
      const icon = equipIcons[name];
      return icon
        ? `<img src="${esc(icon)}" alt="${esc(name)}" title="${esc(name)}" loading="lazy">`
        : `<i title="${esc(name)}">${esc(name.slice(0, 2))}</i>`;
    }).join('');
    return items
      ? `<span class="ms-lane-items" aria-label="${esc((p?.hero || p?.label || '') + ' 的出装')}">${items}</span>`
      : '<span class="ms-lane-items is-empty" title="本局没有出装记录">装备未采集</span>';
  };
  /* 双方英雄下方统一放金币，装备贴着中线留白摆放。 */
  const msLaneSide = (p, side, value, max) => p
    ? `<div class="ms-lane-side ${side}">
        <div class="ms-lane-core">
          <div class="ms-lane-who">${portrait(p.hero, 'ms-lane-face')}<span><b>${esc(p.hero || '—')}</b><small>${esc(p.label || p.nickname || '—')}</small><em>${msKda(p)}</em></span></div>
          <div class="ms-lane-stat"><b>${fmt(value)}</b><i style="--w:${msBar(value, max)}"></i></div>
        </div>
        ${msLaneItems(p)}
      </div>`
    : `<div class="ms-lane-side ${side} is-empty"><div class="ms-lane-core"><div class="ms-lane-who"><span><b>未匹配</b><small>—</small></span></div><div class="ms-lane-stat"><b>—</b></div></div></div>`;
  /* 详细数据不跳页签：五条对位卡片预先渲染在各自行下方，点按钮只展开这一路。 */
  const msLaneViews = (m.players || []).length && typeof mods.deep.laneViews === 'function'
    ? mods.deep.laneViews(m.players, own, m.duration, m.replay?.kills) : {};
  const msLaneRows = (m.players || []).length ? msLanes.map((lane) => {
    const a = msOwnLanes.get(lane), b = msFoeLanes.get(lane);
    if (!a && !b) return '';
    return `<div class="ms-lane-row">
      ${msLaneSide(a, 'own', a?.gold, msMaxGold)}
      <div class="ms-lane-mid"><b>${lane}</b><button type="button" class="ms-lane-more" data-ms-lane="${esc(lane)}" aria-expanded="false">详细数据 <span aria-hidden="true">›</span></button></div>
      ${msLaneSide(b, 'foe', b?.gold, msMaxGold)}
    </div>
    <div class="ms-lane-detail" data-ms-lane-detail="${esc(lane)}" hidden>${msLaneViews[lane] || '<p class="ms-lane-detail-empty">这路没有对位数据。</p>'}</div>`;
  }).join('') : '';
  const msDraft = draft ? `
    <div class="ms-draft">
      <div class="ms-draft-row is-pick"><div class="ms-heroes own">${msStrip(draft?.picks?.[ownSideKey] || [], 'pick')}</div><span class="ms-draft-label">Pick</span><div class="ms-heroes foe">${msStrip(draft?.picks?.[enemySideKey] || [], 'pick')}</div></div>
      <div class="ms-draft-row is-ban"><div class="ms-heroes own">${msStrip(draft?.bans?.[ownSideKey] || [], 'ban')}</div><span class="ms-draft-label">Ban</span><div class="ms-heroes foe">${msStrip(draft?.bans?.[enemySideKey] || [], 'ban')}</div></div>
      <div class="ms-draft-row is-econ"><b class="own">${msGold(ownAgg.gold)}</b><span class="ms-draft-label">经济</span><b class="foe">${msGold(foeAgg.gold)}</b></div>
      ${msOwnRes ? `<div class="ms-draft-row is-res"><div class="ms-res own">${msResGroup(msOwnRes, 'own')}</div><span class="ms-draft-label">资源</span><div class="ms-res foe">${msResGroup(msFoeRes, 'foe')}</div></div>` : ''}
    </div>` : '<div class="ms-draft-empty">暂无禁选记录。</div>';
  const mdTotalMetric = (label, ownValue, foeValue) => {
    const max = Math.max(1, Number(ownValue) || 0, Number(foeValue) || 0);
    return `<div class="md-total-metric">
      <div class="md-total-label">${esc(label)}</div>
      <div class="md-total-vals"><b class="own">${fmt(ownValue)}</b><span>vs</span><b class="foe">${fmt(foeValue)}</b></div>
      <div class="md-total-bars"><i class="own" style="--w:${msBar(ownValue, max)}"></i><i class="foe" style="--w:${msBar(foeValue, max)}"></i></div>
    </div>`;
  };
  const mdTotals = (m.players || []).length ? `<section class="section md-totals-card" id="match-totals">
    <div class="md-totals-head"><b>总量</b><span>双方十人合计</span></div>
    <div class="md-totals-grid">
      ${mdTotalMetric('金币', ownAgg.gold, foeAgg.gold)}
      ${mdTotalMetric('击杀', ownAgg.kills, foeAgg.kills)}
      ${mdTotalMetric('输出', ownAgg.damage, foeAgg.damage)}
      ${mdTotalMetric('承伤', ownAgg.taken, foeAgg.taken)}
    </div>
  </section>` : '';
  const mdHero = `<section class="md-hero ms-summary" id="match-verdict">
    <div class="ms-top"><div class="ms-top-left"><span class="dv-kicker">本局结论</span><span class="dv-tag">${evTag('desc') ? '本局描述' : '单局复盘'}</span></div><span class="ms-mode">${esc([m.mode || '训练赛', m.session].filter(Boolean).join(' · ') || '排位赛双排')}</span></div>
    <div class="dv-claim ms-claim"><h1>${claimHtml}</h1><p>${esc(heroFact)}</p></div>
    <div class="ms-board">
      <div class="ms-team own"><span class="ms-crest">${msCrest(msName)}</span><div class="ms-team-text"><b>${esc(msName)}</b><em class="ms-badge ${msOwnBadgeCls}">${msOwnBadgeText}</em></div></div>
      <div class="ms-board-mid"><div class="ms-score"><i class="own">${esc(scoreParts[0] || '—')}</i>${msCross}<i class="foe">${esc(scoreParts[1] || '—')}</i></div><small>比赛时长 ${hasDuration ? time(m.duration) : '—'}</small></div>
      <div class="ms-team foe"><div class="ms-team-text"><b>${esc(msFoe)}</b><em class="ms-badge ${msFoeBadgeCls}">${msFoeBadgeText}</em></div><span class="ms-crest">${msCrest(msFoe)}</span></div>
    </div>
    ${msDraft}
    ${msLaneRows ? `<div class="ms-lanes"><div class="ms-lanes-head"><span>金币</span><span>对位</span><span>金币</span></div>${msLaneRows}</div>` : '<div class="ms-lanes-empty">暂无十人面板数据。</div>'}
  </section>`;
  /* 脉搏单独成卡：十人面板紧跟在首屏下面，脉搏再跟在面板后面，不再把结论卡撑到 1400px。 */
  const mdPulse = `<section class="section ms-pulse-card" id="match-pulse-card">${pulseBlock}</section>`;
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
    /* 1:1 设计稿：4 个资源小格 + 3 张资源卡 */
    const buffTotal = buffs.length;
    const buffRate = buffTotal ? Math.round((farmed + anti) / buffTotal * 100) : null;
    const resTiles = [
      ['资源控制', rate === null ? '—' : `${rate}%`, rate !== null ? 'blue' : ''],
      ['BUFF 控制', buffRate === null ? '—' : `${buffRate}%`, buffRate !== null ? 'blue' : ''],
      ['推塔数', `${ownTowers} : ${foeTowers}`, ''],
      ['龙 / 主宰', `${ownDragons} : ${foeDragons}`, ''],
    ].map(([label, value, cls]) => `<div class="res-item"><small>${label}</small><b class="${cls}">${value}</b></div>`).join('');

    const resCard = `<div class="rCard"><div class="rHead">资源明细</div>
      ${rows.map((row) => `<div class="rLine"><span>${esc(row.name)}</span><b class="own">${row.own}</b><i>:</i><b class="foe">${row.foe}</b></div>`).join('')}
    </div>`;
    const tierRows = ['一塔', '二塔', '高地塔'].map((tier) => `<div class="tLine"><span>${tier}</span><b>${tierCount(own, tier)}</b><b class="foe">${tierCount(opposite[own], tier)}</b></div>`).join('');
    const towerCard = `<div class="rCard"><div class="rHead">推塔明细</div>
      <div class="tHead"><span></span><b>我方</b><b>对方</b></div>${tierRows}</div>`;
    const buffCard = `<div class="rCard"><div class="rHead">BUFF</div>
      <div class="bLine">
        <div><b>${farmed}</b><small>收己方野</small></div>
        <div><b>${anti}</b><small>反野</small></div>
        <div><b>${stolen}</b><small>被反</small></div>
      </div></div>`;
    return `<div class="res">${resTiles}</div>
      <div class="res-cards">${resCard}${towerCard}${buffCard}</div>`;
  })();
  const mdPhases = `<section class="section" id="match-phases">
    ${mods.deep.phaseTable(phaseTableRows)}
  </section>`;
  /* 「关键节点」整块按设计稿删除：标题、说明、节点行都不再渲染，锚点条也去掉。 */
  /* 10 分钟经济：营地接口只有团队金币（30 秒一个点），没有逐人；回放的金币流水
     对不上账（残差 17.5%，个别 43%）。所以这一格只能由教练手填，填在覆盖层里，
     不动原始数据包；不填就留空，不估。
     赛训组 2026-11-14 口径：打野按英雄标签分野核（8000＝800/分钟）与坦野（6800 总量）；
     中路 5500 达标。2026-11-22 教练要求补上辅助（游走）第 5 人，也走手填；
     游走没有硬编码评级，填了只显示数值。 */
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
        const grade = value === null ? null : gold10Grade(p.position, value, p.hero, p);
        const jungleTag = p.position === '打野' && p.hero
          ? `<em class="md-g10-jtype ${jungleKindOf(p.hero, p)}" title="${p.blade ? `本局打野刀：${esc(p.blade.blade)}` : '按英雄默认标签'}">${jungleTypeLabel(p.hero, p)}</em>` : '';
        return `<label class="md-g10-row ${p.camp === own ? 'own' : 'foe'}">
          <span class="ec-top"><span class="md-g10-lane">${esc(p.position || '未标注')}</span>
            <span class="ec-side">${p.camp === own ? '本队' : '对手'}</span></span>
          <span class="md-g10-hero">${portrait(p.hero, 'g10-avatar')}<b>${esc(p.hero || '—')}</b>${jungleTag}</span>
          <input type="number" inputmode="numeric" min="0" max="100000" step="1"
                 data-gold10="${esc(key)}" data-gold10-lane="${esc(p.position || '')}"
                 data-gold10-hero="${esc(p.hero || '')}"
                 data-gold10-blade="${esc(p.blade?.blade || '')}" data-gold10-kind="${esc(p.blade?.kind || '')}"
                 value="${value === null ? '' : value}" placeholder="填 10 分钟金币">
          ${grade ? `<em class="md-grade ${grade.level}">${grade.label}</em>` : '<em class="md-grade is-blank"></em>'}
        </label>`;
      }).join('');
    const filled = people.filter((p) => has(saved[`${p.camp}-${p.slot}`])).length;
    return `<section class="section" id="match-gold10"><div class="section-heading"><div><h2>10 分钟经济${evTag('desc')}</h2><p>营地与回放都没有逐人金币时间轴（回放只有团队经济，逐人流水对不上账），所以这格只能手填。赛训组口径：对抗路 / 发育路 6800 及格、7000 良好、7400 优秀；中路 5500 达标（550/分钟）；打野按英雄标签分野核 8000（800/分钟）与坦野 6800；辅助（游走）同样手填，只记录数值</p></div>
      <span class="md-g10-count">已填 <b>${filled}</b> / ${people.length}</span></div>
      <div class="md-g10-grid">
        <div class="md-g10-side"><span class="md-g10-side-label own">本队</span>${side(own)}</div>
        <div class="md-g10-side"><span class="md-g10-side-label foe">对手</span>${side(opposite[own])}</div>
      </div>
      <p class="md-g10-note">填在覆盖层里，不改原始数据包；不填就留空，不估算、不补齐。打野的类型章按赛训组英雄标签给出，本局实际职责不同（如蓝领让资源）按实际判读；辅助（游走）也手填。</p>
    </section>`;
  })();
  const mdProfiles = `<section class="section" id="match-profiles"><div class="section-heading"><div><h2>十人面板${evTag('desc')}</h2></div></div>
    ${mods.deep.panel(m.players || [], own, m.positions, m.duration, m.replay?.kills, m.replay?.fights, m.replay?.deaths)}
  </section>`;
  /* 位置数据请求过但没有：说明该局缺逐秒位置（未关联官方回放），不再无限转圈。 */
  const positionsEmpty = m.positionsRequested
    ? '<div class="empty">该局没有逐秒位置数据（需要在采集页的通道校对里关联本局官方回放）</div>'
    : '<div class="empty">正在读取营地的逐秒位置…</div>';
  const mdHeat = `<section class="section" id="match-heat"><div class="section-heading"><div><h2>对位热区${evTag('desc')}</h2><p>蓝为本队、红为对手</p></div></div>
    ${m.positions ? mods.deep.heat(m.positions, m.players, own, m.duration, m.replay) : positionsEmpty}
  </section>`;
  const mdDuel = `<section class="section" id="match-duel"><div class="section-heading"><div><h2>入侵时长${evTag('desc')}</h2></div></div>
    ${m.positions ? mods.deep.duel(m.positions, m.players, own, m.duration) : positionsEmpty}
  </section>`;
  const mdJungle = `<section class="section" id="match-jungle"><div class="section-heading"><div><h2>疑似打野并线${evTag('desc')}</h2></div></div>
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

    /* 头像 + 名字一起跳英雄详情页（heroFace 定义在首屏一层，大屏各区块共用）。 */
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
        ? `<span class="tier ${String(s.tier).toLowerCase()}" title="同路档位：${esc(s.role || '')} 第 ${fmt(s.rank)} / ${fmt(s.size)}">${s.tier}</span>`
        : '<span class="tier"></span>';
      return `<div class="st-row"><span class="st-name">${esc(hero)}</span>${tier}<b>${fmt(wr, 1)}%</b><small>登场 ${fmt(pick, 2)}%</small></div>`;
    };
    const strengthLine = (lane) => {
      const s = lane.facts?.strength;
      if (!s) return '';
      const mine = strengthBit(lane.a.hero, s.mine, 'own');
      const foe = strengthBit(lane.b.hero, s.foe, 'foe');
      if (!mine && !foe) return '';
      const size = s.mine?.size || s.foe?.size;
      return `<div class="strength"><div class="st-head">强度 <small>近 7 天 · 本路${size ? ` ${fmt(size)} 人` : ''}</small></div>${mine}${foe || '<div class="st-row"><span class="st-name">对方未收录</span></div>'}</div>`;
    };
    /* 对位胜率块（设计稿 .rate）：有样本给双向条，没样本给「无对位样本」 */
    const rateLine = (lane) => {
      const f = lane.facts;
      if (!f || !f.n) {
        return `<div class="rate"><div class="rate-label">对位胜率</div>
          <div class="rate-none">无对位样本</div>
          <div class="rate-sub">${esc(laneMissNote(lane))}</div></div>`;
      }
      const own = Math.max(0, Math.min(100, Number(f.wr) || 0));
      const excess = Number(f.excess);
      return `<div class="rate"><div class="rate-label">对位胜率</div>
        <div class="rate-nums"><b class="own">${fmt(own, 1)}%</b><span>vs</span><b class="foe">${fmt(100 - own, 1)}%</b></div>
        <div class="rate-bar"><i class="own" style="width:${own.toFixed(1)}%"></i><i class="foe"></i></div>
        <div class="rate-sub">${fmt(f.n)} 局 · 预期 ${fmt(f.expected, 1)}% · 超额 ${Number.isFinite(excess) && excess > 0 ? '+' : ''}${fmt(excess, 1)}${f.lowPick ? ` · 低登场 ${fmt(f.aPick, 2)}%/${fmt(f.bPick, 2)}%` : ''}</div></div>`;
    };
    const laneCard = (lane) => {
      return `<article class="md-mu-card ${verdictCls(lane)}">
      <div class="dc-top"><span class="dc-lane">${esc(lane.lane)}</span><span class="verdict ${verdictCls(lane)}">${esc(verdictText(lane))}</span></div>
      <div class="dc-heroes">${heroFace(lane.a.hero, 'own')}<span class="vs">vs</span>${heroFace(lane.b.hero, 'foe')}</div>
      ${rateLine(lane)}
      ${strengthLine(lane)}
    </article>`;
    };

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

      /* 第二层：组合命中率（设计稿：左标签 + 右侧进度条） */
      const rateBar = (label, hit, total) => {
        const ratio = has(total) && total > 0 ? Math.min(100, hit / total * 100) : null;
        return `<div class="count">
          <span class="count-label">${label}<b>${fmt(hit)}/${has(total) ? fmt(total) : '—'}</b></span>
          <span class="count-track"><i class="${hit ? '' : 'zero'}" style="width:${ratio === null ? 0 : ratio.toFixed(1)}%"></i></span>
        </div>`;
      };
      const rates = `<div class="counts">
        ${rateBar('双人组合', hitPairs, totalPairs)}${rateBar('体系', hitTrios, totalTrios)}
      </div>`;

      /* 第三层：命中组合横向卡片（1:1 设计稿：圆头像 + 队名 chip + 三项统计） */
      const comboCard = (row, size) => {
        const heroes = Array.isArray(row?.heroes) ? row.heroes.filter(Boolean) : [];
        if (!heroes.length) return '';
        const n = Number(row.n) || 0;
        const grade = n >= 30 ? ['ref', '可用'] : n >= 10 ? ['ref', '参考'] : n >= 3 ? ['watch', '观察'] : ['ref', '个例'];
        const wr = has(row.wr) ? row.wr : null;
        const wrCls = wr === null ? '' : wr >= 55 ? 'good' : wr < 45 ? 'bad' : 'ref';
        const teams = Array.isArray(row.teams) ? row.teams.filter((t) => t && (t.team || typeof t === 'string')) : [];
        const shown = teams.slice(0, 3);
        const more = teams.length - shown.length;
        const teamName = (t) => (typeof t === 'string' ? t : t.team);
        /* 池子命中行：沿用 combo-query 的小标签（赛训 / 体系名 / 强·弱联动），口径一眼可见。 */
        const flagTags = [
          row.source === 'custom' ? '<span class="kq-src">赛训</span>' : '',
          row.name ? `<span class="kq-sysname">${esc(row.name)}</span>` : '',
          row.strength === 'strong' ? '<span class="kq-strength is-strong">强联动</span>' : '',
          row.strength === 'weak' ? '<span class="kq-strength is-weak">弱联动</span>' : '',
        ].filter(Boolean).join('');
        return `<article class="combo-card">
          <div class="cc-top"><span class="cc-kinds"><span class="cc-kind">${size === 3 ? '体系' : '双人'}</span>${flagTags}</span><span class="cc-grade ${grade[0]}">${grade[1]}</span></div>
          <div class="cc-heroes">${heroes.slice(0, 3).map((hero) => `<div class="cc-hero">
            <a class="bp-hero-link" href="${esc(route('hero', hero))}" title="查看 ${esc(hero)} 详情">${portrait(hero, 'avatar')}<b>${esc(hero)}</b></a>
          </div>`).join('<span class="cc-plus">+</span>')}</div>
          <div class="cc-used">用过</div>
          <div class="cc-teams">${shown.map((t) => `<span>${esc(teamName(t))}</span>`).join('')}${more > 0 ? `<span>+${more}</span>` : ''}</div>
          <div class="cc-stats">
            <div><small>场次</small><b>${fmt(n)}</b></div>
            <div><small>胜率</small><b class="${wrCls}">${wr === null ? '—' : pct(wr)}</b></div>
            <div><small>最近</small><b class="recent">${dateOnly(row.lastDate) || (has(row.year) ? row.year : '—')}</b></div>
          </div>
        </article>`;
      };
      const allItems = [
        ...(Array.isArray(facts.pairs) ? facts.pairs : []).map((row) => ({ row, size: 2 })),
        ...(Array.isArray(facts.trios) ? facts.trios : []).map((row) => ({ row, size: 3 })),
      ];
      const cards = allItems.map((item) => comboCard(item.row, item.size)).filter(Boolean);
      /* 2026-11-19 教练：这些「命中组合」卡与上面「我方组合 / 对手组合」是同一批组合的两种画法，
         上下重复，整块删掉，只留整阵容结论 + 命中率进度条 + 口径脚注。 */
      const list = '';
      const isEmptyNote = isEmpty ? `<div class="md-kplhit-empty">
        ${lineupKnown ? '' : '<p class="md-kplhit-empty-line">本队双人 / 三人体系在 KPL 统计窗口内都没有命中</p>'}
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

      /* 赛训池口径：.hidden 的 .md-kplhit-foot 之外，再给一个始终可见的口径标记；
         三人体系命中横幅放联动组合区顶部，头像 + 文字让教练一眼看到。 */
      const scopeMark = facts.poolActive === true
        ? '<p class="md-kplhit-scope">口径：赛训组组合池（最高优先级）· 双人/三人以池子名单为准；四人组合仍看 KPL 全库</p>'
        : '';
      const trioBanner = (Array.isArray(facts.trios) ? facts.trios : [])
        .filter((row) => row && row.source === 'custom' && row.name)
        .map((row) => {
          const faces = (Array.isArray(row.heroes) ? row.heroes : []).filter(Boolean)
            .map((hero) => `<span class="cp-trio-face">${portrait(hero, 'avatar')}</span>`).join('');
          const strength = row.strength === 'strong' ? '<span class="kq-strength is-strong">强联动</span>'
            : row.strength === 'weak' ? '<span class="kq-strength is-weak">弱联动</span>' : '';
          return `<div class="cp-trio-hit">
            ${faces ? `<span class="cp-trio-faces">${faces}</span>` : ''}
            <span class="cp-trio-copy"><b>三人体系命中：${esc(row.name)}</b>${strength}${row.note ? `<small>${esc(row.note)}</small>` : ''}</span>
          </div>`;
        }).join('');
      const cls = `md-kplhit${isEmpty ? ' is-empty' : ''}${lineupKnown && lineupSeen ? ' is-seen' : ''}`;
      return `<div class="${cls}">
        ${scopeMark}${trioBanner}${rates}${list}${isEmptyNote}${foot}
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
      <div class="md-hscroll"><div class="md-mu-grid">${lanes.map(laneCard).join('')}</div></div></div>` : '';
    /* 复制成一段话：教练复盘完要发群 / 写进日报，不想再手抄。
       只取已经判定过的结论（对位 / 克制 / 命中组合），不另外算口径。 */
    const copyText = (() => {
      const lines = [];
      const date = String(m.dateText || m.date || '').slice(0, 10);
      /* 发群时对方只看到这一段话：带上本队名，别让人猜是哪支队在复盘。 */
      lines.push(`${date} ${metadata.teamName || '本队'} vs ${m.opponent || '对手'}｜本局 BP 复盘：${badge}`);
      for (const lane of lanes) {
        const sample = lane.facts?.n ? `${fmt(lane.facts.n)} 局` : '无对位样本';
        const gold = lane.nowDiff === null ? '' : `，本局 ${diff(lane.nowDiff)}`;
        lines.push(`· ${lane.lane} ${lane.a.hero} vs ${lane.b.hero}：${lane.verdict}（${sample}${gold}）`);
      }
      const counterPairs = (m.rulesCounters?.heroPairs || []);
      const counterRows = (m.bpFacts?.counters?.lanes || []).map((row) => {
        const forward = counterPairs.find((pair) => pair.a === row.mine && pair.b === row.foe);
        const reverse = counterPairs.find((pair) => pair.a === row.foe && pair.b === row.mine);
        if (forward) return `${row.lane} ${row.mine} 克 ${row.foe}（规则中心 ${forward.strength || '中'}）`;
        if (reverse) return `${row.lane} ${row.mine} 被 ${row.foe} 克（规则中心 ${reverse.strength || '中'}）`;
        return '';
      }).filter(Boolean);
      if (counterRows.length) lines.push(`· 克制：${counterRows.join('；')}`);
      return lines.join('\n');
    })();
    /* 拆开返回：复盘大屏各区块共用同一批判定结果，不另算口径。 */
    return { review, badge, combos, kpl: kplBlock, matchup, ownCombos, foeCombos, comboCard, copyText };
  })();
  /* 用 section：回放事件异步到达后，资源明细要跟着整块刷新。
     资源/推塔/BUFF 明细紧跟「总量」卡放在复盘大屏，不再塞进「十人数据」页签。 */
  const mdResourceDetail = events.length ? `<section class="section" id="match-resource-detail">
    <div class="section-heading"><div><h2>资源与推塔</h2><p>龙 / 主宰、防御塔与 BUFF 的逐项明细；总量卡只给双方合计</p></div></div>
    ${resourceBand}
  </section>` : '';

  /* ── 复盘大屏（2026-11-14 改版）─────────────────────────────────────
     结论（内含比赛脉搏）→ 总量 → 双方阵容 → 本局 BP 复盘（并入赛事命中）→
     对位压制 → 克制命中 → 组合得失 → 阶段对比 + 关键节点。团战与资源 / 经济走势两张卡按教练
     要求撤掉（团战细节在「事件」页签，经济曲线在结论卡的脉搏里）；赛事命中不再是
     独立卡片。
     2026-11-19 教练：原「我方组合 / 对手组合」（联动组合）与下面的「组合得失（拿到 / 被拆）」
     讲的是同一批组合，上下重复，整块撤掉，只留设计稿那一版。 */

  const mdOvMatchup = bpAnalysis.matchup ? `<section class="section md-ov" id="match-ov-matchup">
      <div class="section-heading"><div><h2>对位压制${evTag('interval')}</h2><p>巅峰千强同分路对位（源站累积样本）：基准取最近 8 周周中位数，低登场率英雄向 50% 收缩；n≥50 收录，50–199 或低登场率只作初步观察，n≥200 且方向稳定才判优势/劣势</p></div></div>
      <div class="md-ov-pad">${bpAnalysis.matchup}</div>
    </section>` : '';
  /* 克制关系：只认赛训规则中心「克制关系 → 英雄克制英雄」里维护过的有向关系。
     规则中心没维护的对位不猜，也不拿 KPL / 营地数据兜底。 */
  const ovCounters = (() => {
    const lanes = (m.bpFacts?.counters?.lanes || []).filter((row) => row?.mine && row?.foe);
    const pairs = (m.rulesCounters?.heroPairs || []).filter((row) => row?.a && row?.b);
    if (!lanes.length) return '<div class="md-ov-empty">这局五路对位没有配齐，克制关系不成立。</div>';
    if (!m.rulesCounters) return '<div class="md-ov-empty">规则中心克制关系暂不可读。</div>';
    if (!pairs.length) return '<div class="md-ov-empty">规则中心还没有维护克制关系（规则中心 → 克制关系 → 英雄克制英雄）。</div>';
    const find = (a, b) => pairs.find((row) => row.a === a && row.b === b) || null;
    const strength = (row) => row?.strength || '中';
    const chip = (row, mineLabel) => row
      ? `<span class="md-ct-chip ${mineLabel ? 'is-hit' : 'is-miss'}" title="${esc(`${row.a} → ${row.b} · 强度 ${strength(row)}${row.note ? ` · ${row.note}` : ''}`)}">规则 · ${mineLabel ? `我方${esc(strength(row))}克` : `被${esc(strength(row))}克`}</span>`
      : '';
    const lanePairs = new Set();
    const laneRows = lanes.map((entry) => {
      const forward = find(entry.mine, entry.foe);
      const reverse = find(entry.foe, entry.mine);
      lanePairs.add(`${entry.mine}|${entry.foe}`);
      const chips = [chip(forward, true), chip(reverse, false)].filter(Boolean).join('');
      if (!chips) return '';
      return `<div class="md-ct-row">
        <span class="md-ct-lane" aria-hidden="true"></span>
        <span class="md-ct-who">${heroFace(entry.mine, 'own')}<i>vs</i>${heroFace(entry.foe, 'foe')}</span>
        <span class="md-ct-chips">${chips}</span>
      </div>`;
    }).filter(Boolean).join('');
    const sideOf = new Map();
    for (const entry of lanes) { sideOf.set(entry.mine, 'own'); sideOf.set(entry.foe, 'foe'); }
    const notable = pairs.filter((row) => sideOf.has(row.a) && sideOf.has(row.b)
      && sideOf.get(row.a) !== sideOf.get(row.b)
      && !lanePairs.has(`${row.a}|${row.b}`) && !lanePairs.has(`${row.b}|${row.a}`)).slice(0, 8);
    const notableRows = notable.map((row) => {
      const aOwn = sideOf.get(row.a) === 'own';
      return `<div class="md-ct-row is-notable">
        <span class="md-ct-lane">交叉</span>
        <span class="md-ct-who">${heroFace(row.a, aOwn ? 'own' : 'foe')}<i>→</i>${heroFace(row.b, aOwn ? 'foe' : 'own')}</span>
        <span class="md-ct-chips"><span class="md-ct-chip ${aOwn ? 'is-hit' : 'is-miss'}">${aOwn ? '我方克制' : '对方克制'} · ${esc(strength(row))}</span></span>
      </div>`;
    }).join('');
    // 规则中心 counters 接口不返回 sourceVersion；用当前 revision/updatedAt
    // 让用户至少能看到本局按哪一版规则渲染。
    const counters = m.rulesCounters;
    const version = counters && {
      competitionName: `规则中心 Rev ${counters.revision ?? 0}`,
      finalizedAt: counters.updatedAt || '',
    };
    const foot = `<p class="md-ct-foot">口径：赛训规则中心「克制关系 → 英雄克制英雄」里维护的攻方 → 受方有向关系；强度取维护值（强/中/弱）。规则中心没维护的对位不显示，不拿 KPL / 营地数据兜底。${version ? ` 本局使用「${esc(version.competitionName || version.competitionId || '')}」定稿于 ${esc(String(version.finalizedAt || '').slice(0, 10))} 的版本。` : ''}</p>`;
    return `<div class="md-counters">
      <div class="md-ct-head"><b>五路对位</b><span>只看规则中心维护过的英雄克制关系</span></div>
      <div class="md-hscroll"><div class="md-ct-list">${laneRows || '<div class="md-ov-empty">五路对位在规则中心都没有维护克制关系。</div>'}</div></div>
      ${notableRows ? `<div class="md-ct-head"><b>重点交叉提示</b><span>这局十人里跨分路、且规则中心有记录的克制关系</span></div>
      <div class="md-hscroll"><div class="md-ct-list">${notableRows}</div></div>` : ''}
      ${foot}
    </div>`;
  })();
  const mdOvCounters = `<section class="section md-ov" id="match-ov-counters">
      <div class="section-heading"><div><h2>克制关系${evTag('desc')}</h2><p>只列赛训规则中心「克制关系」里维护过的英雄对位；规则中心没维护就不显示，不拿 KPL / 营地数据兜底</p></div></div>
      <div class="md-ov-pad">${ovCounters}</div>
    </section>`;

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
    const empty = (text) => `<div class="md-ov-empty">${text}</div>`;
    if (!draft) return empty('这局没有 BP 记录，组合得失不成立。');
    const names = (rows) => (rows || []).map((row) => (row && row.name) || '').filter(Boolean);
    const picks = { own: names(draft?.picks?.[ownSideKey]), foe: names(draft?.picks?.[enemySideKey]) };
    const bans = { own: names(draft?.bans?.[ownSideKey]), foe: names(draft?.bans?.[enemySideKey]) };
    if (!picks.own.length && !picks.foe.length) return empty('这局没有可读的选人记录，组合得失不成立。');
    /* 只认赛训组组合池：池子里的双人 / 三人组合才有资格算「想拿的组合」；
       营地历史双人组、KPL 组合都不再作为候选。 */
    const pool = m.comboPool && !m.comboPool.builtin ? m.comboPool : null;
    const poolRows = [
      ...(pool?.pairs || []).map((row) => ({ ...row, size: 2 })),
      ...(pool?.trios || []).map((row) => ({ ...row, size: 3 })),
    ].filter((row) => Array.isArray(row.heroes) && row.heroes.length === row.size);
    if (!poolRows.length) return empty('赛训组组合池还没有保存双人 / 三人组合，组合得失不成立。');
    const keyOf = (heroes) => [...heroes].sort().join('+');
    const strengthRank = (value) => (value === 'strong' ? 0 : value === 'weak' ? 1 : 2);

    const collect = (side, oppSide) => {
      const mine = picks[side], opp = picks[oppSide], oppBans = bans[oppSide];
      if (!mine.length) return { got: [], broken: [] };
      const got = [], broken = [];
      const consider = (heroes, extra) => {
        const inside = heroes.filter((hero) => mine.includes(hero));
        const missing = heroes.filter((hero) => !mine.includes(hero));
        if (!inside.length) return;
        if (!missing.length) {
          got.push({ heroes, inside, ...extra });
          return;
        }
        if (missing.length !== 1) return;
        const gone = missing[0];
        const reason = oppBans.includes(gone) ? 'ban' : opp.includes(gone) ? 'steal' : '';
        if (!reason) return;
        broken.push({ heroes, inside, gone, reason, ...extra });
      };
      for (const combo of poolRows) {
        consider(combo.heroes || [], { source: 'pool', strength: combo.strength, name: combo.name });
      }
      const prune = (list) => {
        const kept = list.filter((item) => !list.some((other) => other !== item
          && other.heroes.length > item.heroes.length
          && item.heroes.every((hero) => other.heroes.includes(hero))));
        const seen = new Set();
        return kept.sort((a, b) => strengthRank(a.strength) - strengthRank(b.strength)
          || String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
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
      const facts = [`组合池${item.strength === 'strong' ? ' · 强联动' : item.strength === 'weak' ? ' · 弱联动' : ''}`];
      const name = String(item.name || '').trim();
      if (name && !/^\d+$/.test(name)) facts.push(name);
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
    if (!own.got.length && !own.broken.length && !foe.got.length && !foe.broken.length) return empty('组合池里没有本局能凑的组合。');
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
        ${(!data.got.length && !data.broken.length) ? `<p class="md-bk-empty">${label}这局没有命中组合池的组合</p>` : ''}
      </div>`;
    };
    return `<div class="md-broken">
      ${column('own', '我方想拿的组合', own)}
      ${column('foe', '对面想拿的组合', foe)}
    </div>`;
  })();
  const mdOvBroken = `<section class="section md-ov" id="match-ov-broken">
      <div class="section-heading"><div><h2>组合得失${evTag('desc')}</h2><p>候选只认赛训组组合池（双人 / 三人）里保存过的组合；池子外的历史双人组、KPL 组合都不算。阵容里凑齐就是拿到（亮色），只差一格且那格被对面 ban 走或抢走就是被拆（那格灰掉并划斜杠）</p></div></div>
      <div class="md-ov-pad">${mdBroken}</div>
    </section>`;
  const mdCohesion = (() => {
    const head = `<div class="section-heading"><div><h2>中野辅集结与 BUFF${evTag('desc')}</h2></div></div>`;
    if (!m.positions) return `<section class="section" id="match-cohesion">${head}${positionsEmpty}</section>`;
    /* 推塔矩阵：按推塔方（killerCamp）拆到「上路/中路/下路 × 一塔/二塔/高地塔」。 */
    const towers = {};
    for (const camp of ['blue', 'red']) {
      towers[camp] = {
        一塔: { 上路: 0, 中路: 0, 下路: 0 },
        二塔: { 上路: 0, 中路: 0, 下路: 0 },
        高地塔: { 上路: 0, 中路: 0, 下路: 0 },
      };
    }
    for (const e of events) {
      if (e.kind !== 'structure' || !e.killerCamp || !towers[e.killerCamp]) continue;
      const hit = eventLabel(e).match(/(上路|中路|下路)(一塔|二塔|高地塔)/);
      if (hit) towers[e.killerCamp][hit[2]][hit[1]] += 1;
    }
    const extras = { buffs: m.replay?.buffEvents || [], towers };
    return `<section class="section" id="match-cohesion">${head}
      ${mods.deep.cohesion(m.positions, m.players, own, m.duration, events, m.replay?.kills, extras)}
    </section>`;
  })();
  /* 战斗拆成两块：团战（点地图看本波）与掉点（筛选/点选看单次），各自带分析。 */
  const battle = mods.deep.battle(m.positions, m.players, own, m.duration, points, m.replay?.deaths, m.replay?.fights);
  const mdFights = battle && battle.fights
    ? `<section class="section" id="match-battle"><div class="section-heading"><div><h2>团战${evTag('desc')}</h2><p>点大小＝参战人数，颜色＝该波击杀差（本队金 / 对手青）</p></div></div>${battle.fights}</section>`
    : battle ? ''
      : '<section class="section" id="match-battle"><div class="empty">这局没有团战或掉点数据（需要营地回放的 battles 段）</div></section>';
  const mdDeaths = battle && battle.deaths
    ? `<section class="section" id="match-deaths"><div class="section-heading"><div><h2>掉点${evTag('desc')}</h2><p>掉点＝一次阵亡；损失＝死前 120 秒经济差走势外推到复活时刻的差额（本队视角，负＝我方亏、正＝我方赚）</p></div></div>${battle.deaths}</section>`
    : '';
  /* 切C 与首杀（设计稿 design-redblue/切C与首杀_优化版.html）：
     切 C 五张卡 → 敌方切 C 五张卡 → 团战首杀 / 团战击杀四个数字卡。
     口径：切C＝对抗路/打野击杀对方中路或发育路；首杀＝该波团战第一次击杀。
     设计稿里的首杀分析、团战节奏小方块、逐条账本都不再渲染。 */
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
    const statOf = (p) => {
      const mine = rows.filter((k) => k.killerCamp === p.camp && k.killer === p.hero);
      const cuts = mine.filter(isCut);
      const targetCounts = new Map();
      for (const k of cuts) targetCounts.set(k.victim, (targetCounts.get(k.victim) || 0) + 1);
      return {
        p, kills: mine.length, cut: cuts.length,
        targets: [...targetCounts.keys()], targetCounts,
        first: mine.filter((k) => firstKeys.has(keyOf(k))).length,
      };
    };
    const LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
    const byLane = (camp) => (m.players || []).filter((p) => p.camp === camp).map(statOf)
      .sort((a, b) => {
        const ai = LANE_ORDER.indexOf(a.p.position), bi = LANE_ORDER.indexOf(b.p.position);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
      });
    const ownStats = byLane(own);
    const foeCamp = opposite[own] || (own === 'blue' ? 'red' : 'blue');
    const foeStats = byLane(foeCamp);
    const cutTotal = ownStats.reduce((sum, s) => sum + s.cut, 0);
    const foeCutTotal = foeStats.reduce((sum, s) => sum + s.cut, 0);
    const firstTotal = ownStats.reduce((sum, s) => sum + s.first, 0);
    const ownKills = rows.filter((k) => k.killerCamp === own).length;
    const firstRate = ownKills ? Math.round(firstTotal / ownKills * 100) : null;
    const targetText = (stats) => {
      const map = new Map();
      for (const s of stats) for (const [target, n] of s.targetCounts) map.set(target, (map.get(target) || 0) + n);
      return [...map.entries()].map(([target, n]) => `${target}${n > 1 ? ` ×${n}` : ''}`).join('、');
    };
    const ownTargetText = targetText(ownStats);
    const foeTargetText = targetText(foeStats);

    /* 团战首杀 / 击杀账：fights 缺失时只报靠击杀能算的部分，不编团战结果。 */
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
    const foeFirstOwnWins = foeFights.filter(ownWonFight).length;
    const foeFirstLosses = foeFights.filter((f) => fightKills(f, ownSide) < fightKills(f, foeSide)).length;
    const foeFirstDraws = foeFights.length - foeFirstOwnWins - foeFirstLosses;
    const fightKillRows = rows.filter((k) => k.killerCamp === own && k.fight);
    const fightKillTotal = fightKillRows.length || ownKills;
    const fightKillLanes = (() => {
      const counter = new Map();
      for (const k of fightKillRows) {
        const lane = laneOfKill(own, k.killer);
        if (lane) counter.set(lane, (counter.get(lane) || 0) + 1);
      }
      const sorted = [...counter.entries()].sort((a, b) => b[1] - a[1]);
      if (!sorted.length) return '';
      if (sorted.length >= 2 && sorted[0][1] === sorted[1][1]) {
        const rest = sorted.slice(2, 3).map(([lane, n]) => `${lane} ${n} 次`).join('，');
        return `${sorted[0][0]} / ${sorted[1][0]} 各 ${sorted[0][1]} 次${rest ? `，${rest}` : ''}`;
      }
      return sorted.slice(0, 3).map(([lane, n]) => `${lane} ${n} 次`).join('，');
    })();

    const card = (s, side) => {
      const hit = s.cut > 0;
      const isBy = side === 'by';
      const chips = s.targets.map((target) => `<span class="md-cut-target">${portrait(target, 'md-cut-target-face')}<em>${esc(target)}</em></span>`).join('');
      const shareFirst = firstTotal ? Math.round(s.first / firstTotal * 100) : null;
      const shareKills = ownKills ? Math.round(s.kills / ownKills * 100) : null;
      return `<article class="md-cut-card ${side}${hit ? ' is-hit' : ' is-none'}">
        <div class="md-cut-top"><span class="md-cut-lane">${esc(s.p.position || '未标注')}</span><b>${esc(s.p.hero || s.p.label || '—')}</b></div>
        <div class="md-cut-nick">${esc(s.p.label || '—')}</div>
        <div class="md-cut-main">${portrait(s.p.hero || '', 'md-cut-face')}
          <span class="md-cut-num">${s.cut}<small>次切 C</small></span></div>
        ${hit ? `<div class="md-cut-targets">${chips}</div>` : '<div class="md-cut-none">未形成切 C</div>'}
        <div class="md-cut-sub">${isBy
          ? (hit ? '<span>我方 C 位被针对</span>' : '')
          : `<span>首杀 <b>${s.first}</b></span><span>击杀 <b>${s.kills}</b></span><span class="md-cut-pct">${shareFirst === null ? '—' : `${shareFirst}%`} / ${shareKills === null ? '—' : `${shareKills}%`}</span>`}
        </div>
      </article>`;
    };
    const statCard = (label, value, sub) => `<div class="md-cut-stat">
      <div class="md-cut-stat-label">${label}</div>
      <div class="md-cut-stat-big">${value}</div>
      <div class="md-cut-stat-sub">${sub}</div>
    </div>`;
    return `<section class="section" id="match-kills"><div class="section-heading"><div><h2>切C与首杀${evTag('desc')}</h2></div></div>
      <div class="md-cut-block">
        <div class="md-cut-sec-head"><h2>切 C</h2>
          <span class="md-cut-total">本队共 <b>${cutTotal}</b> 次${ownTargetText ? ` · 目标 ${ownTargetText}` : ''}</span></div>
        <div class="md-cut-cards">${ownStats.map((s) => card(s, 'own')).join('')}</div>
      </div>
      <div class="md-cut-block">
        <div class="md-cut-sec-head"><h2>敌方切 C</h2>
          <span class="md-cut-total">敌方共 <b class="is-foe">${foeCutTotal}</b> 次${foeTargetText ? ` · 目标 ${foeTargetText}` : ''}</span></div>
        <div class="md-cut-cards">${foeStats.map((s) => card(s, 'by')).join('')}</div>
      </div>
      <div class="md-cut-block">
        <div class="md-cut-sec-head"><h2>团战首杀 / 团战击杀</h2></div>
        <div class="md-cut-stats">
          ${statCard('我方首杀', `${firstTotal} <em>次</em>`,
            firstRate === null ? '按击杀账本统计' : `占我方击杀 <b>${firstRate}%</b>`)}
          ${statCard('首杀团战', ownFights.length ? `${ownFightWins}<em>/${ownFights.length}</em>` : '— <em>波</em>',
            ownFights.length ? `我方首杀的团战赢下 ${ownFightWins} 波` : '回放没有团战段')}
          ${statCard('被首杀', `${foeFights.length} <em>波</em>`,
            foeFights.length ? `对方首杀，我方 <b>${foeFirstOwnWins} 胜 ${foeFirstLosses} 负${foeFirstDraws ? ` ${foeFirstDraws} 平` : ''}</b>` : '没有被对方首杀')}
          ${statCard('团战击杀', `${fightKillTotal} <em>次</em>`,
            fightKillLanes || '按击杀账本统计')}
        </div>
      </div>
    </section>`;
  })();
  /* 事件时间轴（2026-11-19）：资源与推塔水晶两条横向时间轴，悬停看参与者 */
  const mdEventTimeline = `<section class="section" id="match-event-timeline"><div class="section-heading"><div><h2>事件时间轴${evTag('desc')}</h2></div></div>
    ${m.replay?.events?.length ? mods.deep.timeline(m.replay.events.map((e) => ({ ...e, label: eventLabel(e) })), own, m.duration, m.players) : '<div class="empty">这一局没有回放事件。</div>'}
  </section>`;
  /* 「阵线」（五人平均推进进度）2026-11-14 按赛训组反馈撤掉：
     把五个人压成一个百分比，教练看不出该点谁、该改哪一路；同页的
     「对位热区」「对位纵深」已经能逐路、逐人回答「压没压过去」。 */
  const mdSource = `<p class="md-source">数据来源：王者营地面板（十人结算 / 经济采样 / 分路派生卡片）、官方回放事件与营地逐秒位置 · ${esc(m.date || '')} ${esc(m.opponent ? '对阵 ' + m.opponent : '')}</p>`;
  /* 单局页原来一屏 8000px。2026-11-14：复盘大屏收敛成
     结论（脉搏在内）/ 总量 / 阵容 / BP 复盘（含赛事命中）/ 对位 / 组合 / 阶段 / 节点，
     用宽屏分栏排；十人 / 事件 / 地图 仍作为下钻页签。地址带页签，刷新后停在原处。 */
  const mdTab = ['review', 'data', 'events', 'map'].includes(current().tab) ? current().tab : 'review';
  const tabButton = (key, label) => `<button type="button" class="md-tab" data-md-tab="${key}"
    id="md-tab-${key}" role="tab" aria-selected="${key === mdTab}"
    aria-controls="md-pane-${key}" tabindex="${key === mdTab ? '0' : '-1'}"><b>${label}</b></button>`;
  const mdTabs = `<div class="md-tabs" role="tablist" aria-label="单局页签">
    ${tabButton('review', '复盘大屏')}
    ${tabButton('data', '十人数据')}
    ${tabButton('events', '事件')}
    ${tabButton('map', '地图')}
  </div>`;
  /* 复盘大屏的区块导航条已撤掉（2026-11-22）：顶部四个页签已经承担导航，
     再压一条吸顶条只会把结论卡继续往下推。证据类型图例也一并撤掉：
     教练反馈「看数据不需要先读一遍图例」，各区块仍保留自己的证据徽标。 */
  return `<div class="page md-page" data-md-tab-active="${mdTab}">${mdCrumb}${mdTabs}
    <div class="md-pane" id="md-pane-review" data-md-pane="review" role="tabpanel" aria-labelledby="md-tab-review">
      ${mdHero}
      ${mdTotals}
      ${mdResourceDetail}
      ${mdPulse}
      ${mdOvCounters}
      ${mdOvBroken}
      <div class="md-pane-row">${mdPhases}</div>
    </div>
    <div class="md-pane" id="md-pane-data" data-md-pane="data" role="tabpanel" aria-labelledby="md-tab-data">${mdGold10}${mdProfiles}${mdOvMatchup}${mdJungle}${mdCohesion}</div>
    <div class="md-pane" id="md-pane-events" data-md-pane="events" role="tabpanel" aria-labelledby="md-tab-events">${mdEventTimeline}${mdFights}${mdDeaths}${mdKills}</div>
    <div class="md-pane" id="md-pane-map" data-md-pane="map" role="tabpanel" aria-labelledby="md-tab-map">${mdMap}</div>
    ${mdSource}
    </div>`;
}

const checklist = createChecklist();

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

/* 组合池设置的屏幕阅读器播报：页面自己有可见状态条，这里只把结果读给辅助技术。
   与 biggame-page 的 announce 同一口径，不额外弹窗打断操作。 */
let comboLiveNode = null;
function comboNotify(message) {
  if (!comboLiveNode || !comboLiveNode.isConnected) {
    comboLiveNode = document.createElement('div');
    comboLiveNode.setAttribute('role', 'status');
    comboLiveNode.setAttribute('aria-live', 'polite');
    comboLiveNode.style.cssText = 'position:fixed;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap';
    document.body.append(comboLiveNode);
  }
  comboLiveNode.textContent = message;
}

/* 这些路由有自己的页面模块，其余（含详情页、采集页签）都走 features.js。 */
const OWN_MODULE_ROUTES = new Set(['overview', 'team-profile', 'bp', 'match', 'cross', 'biggame', 'matching', 'series-builder', 'combo-pool', 'grade-rules', 'competitions', 'lineup-tags', 'profiles', 'metrics-observe', 'rules', 'snapshot-center', 'official-entry', 'match-notes', 'docs', 'sources', 'source-health']);

async function ensureModules(name) {
  const jobs = [];
  if (!OWN_MODULE_ROUTES.has(name) && !mods.features) {
    jobs.push(importOnce('./features.js?v=20261127csmin1').then(({ createFeatures }) => {
      mods.features = createFeatures({ esc, fmt, pct, diff, time, portrait, route, table,
        pageIntro, icon, microChart, gameAnchorBar, reload: () => load(true),
        currentQuery: () => query(), teamName: () => metadata.teamName || '' });
    }));
  }
  if (name === 'docs' && !mods.docsPage) {
    jobs.push(importOnce('./docs-page.js?v=20261126about2').then(({ createDocsPage }) => {
      mods.docsPage = createDocsPage({ esc, icon });
    }));
  }
  if (name === 'overview' && !mods.brief) {
    /* 首页简报：模块自己请求 /api/briefing，外壳只给挂载点、筛选与跳转动作。 */
    jobs.push(importOnce('./period-brief.js').then(({ createPeriodBrief }) => {
      mods.brief = createPeriodBrief({
        esc, fmt, icon, API_BASE, portrait,
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
  if (name === 'team-profile' && !mods.teamProfile) {
    jobs.push(importOnce('./team-profile.js?v=20261123staff4').then(({ createTeamProfilePage }) => {
      mods.teamProfile = createTeamProfilePage({ esc, API_BASE, notify: comboNotify });
    }));
  }
  if (name === 'bp' && !mods.bpLab) {
    jobs.push(importOnce('./bp-studio.js?v=20261126bpclear1').then(({ createBpStudio }) => {
      mods.bpLab = createBpStudio({ esc, fmt, pct, icon, portrait, API_BASE });
    }));
  }
  if (name === 'match' && !mods.deep) {
    jobs.push(importOnce('./match-deep.js?v=20261127csmin1').then(({ createMatchDeep }) => {
      mods.deep = createMatchDeep({ esc, fmt, pct, diff, time, portrait,
        phases: phaseWindows, gpmOf, goldGrade, fieldGrade, subjectOf });
      mods.deep.bindPanel(document);
    }));
  }
  if (name === 'cross' && !mods.crossPage) {
    jobs.push(importOnce('./cross-page.js?v=20261126zero').then(({ createCrossPage }) => {
      mods.crossPage = createCrossPage({ esc, fmt, pct, diff, time, portrait });
    }));
  }
  if (name === 'biggame' && !mods.bigGamePage) {
    jobs.push(importOnce('./biggame-page.js?v=20261126coach2').then(({ createBigGamePage }) => {
      /* 大场页的英雄池交叉要按双方战队分区：本队名从这里取，对手名在详情数据里。 */
      mods.bigGamePage = createBigGamePage({ esc, fmt, pct, diff, time, portrait, teamName: () => metadata.teamName || '' });
    }));
  }
  if (name === 'matching' && !mods.matching) {
    jobs.push(importOnce('./matching-page.js').then(({ createMatchingPage }) => {
      mods.matching = createMatchingPage({ esc, API_BASE, icon,
        refresh: () => load(true) });
    }));
  }
  if (name === 'series-builder' && !mods.seriesBuilder) {
    jobs.push(importOnce('./series-builder.js?v=20261126noanalysis').then(({ createSeriesBuilder }) => {
      mods.seriesBuilder = createSeriesBuilder({ esc, fmt, diff, pct, time, portrait, route, icon });
    }));
  }
  if (name === 'combo-pool' && !mods.comboPool) {
    jobs.push(importOnce('./combo-pool.js?v=20261127csmin1').then(({ createComboPoolPage }) => {
      /* 组合池自取数：英雄资料通过 getter 读外壳的 metadata，不碰 combo-query
         的既有组合分析逻辑；头像目录后到时由 load() 调 rerender() 补画。 */
      mods.comboPool = createComboPoolPage({
        esc, portrait, API_BASE, icon, notify: comboNotify,
        getMetadata: () => metadata,
      });
    }));
  }
  if (name === 'grade-rules' && !mods.gradeRules) {
    jobs.push(importOnce('./grade-rules.js?v=20261127csmin1').then(({ createGradeRulesPage }) => {
      mods.gradeRules = createGradeRulesPage({ esc, API_BASE, icon, notify: comboNotify });
    }));
  }
  if (name === 'competitions' && !mods.competitions) {
    jobs.push(importOnce('./competitions.js?v=20261126mono2').then(({ createCompetitionsPage }) => {
      mods.competitions = createCompetitionsPage({ esc, API_BASE, icon, notify: comboNotify });
    }));
  }
  if (name === 'lineup-tags' && !mods.lineupTags) {
    jobs.push(importOnce('./lineup-tags.js?v=20261124snap').then(({ createLineupTagsPage }) => {
      mods.lineupTags = createLineupTagsPage({ esc, portrait, API_BASE, icon, notify: comboNotify,
        getMetadata: () => metadata });
    }));
  }
  /* === 数据管理层新模块（2026-11-22）===
     三套档案 / 指标观察 / 规则中心 / 正式录入 / 赛后笔记；全部自取数，
     外壳只给挂载点。CSS 统一在 index.html 内 kpl-gold.css 之后加载。 */
  if ((name === 'profiles' || name === 'team-profile') && (!mods.profiles || !mods.teamProfiles)) {
    jobs.push(importOnce('./profiles.js').then(({ createProfilesPage }) => {
      const ctx = { esc, icon, notify: comboNotify, API_BASE };
      if (!mods.profiles) mods.profiles = createProfilesPage(ctx);
      /* 本队页里的档案用嵌入骨架：不再重复整页标题与返回链接。 */
      if (!mods.teamProfiles) mods.teamProfiles = createProfilesPage({ ...ctx, embedded: true });
    }));
  }
  if (name === 'metrics-observe' && !mods.metricsObserve) {
    jobs.push(importOnce('./metrics-observe.js?v=20261124mo5').then(({ createMetricsObservePage }) => {
      mods.metricsObserve = createMetricsObservePage({ esc, API_BASE, notify: comboNotify });
    }));
  }
  if (name === 'rules' && !mods.rulesCenter) {
    jobs.push(importOnce('./rules-center.js?v=20261127csmin1').then(({ createRulesCenter }) => {
      mods.rulesCenter = createRulesCenter({ esc, API_BASE, icon, notify: comboNotify,
        portrait, getMetadata: () => metadata });
      // 规则中心保存英雄标签后，同一次 SPA 会话也刷新 metadata（combo / 分路筛选 / 评级兜底）。
      document.addEventListener('rules-center:saved', (event) => {
        if (event.detail?.kind !== 'hero_tags') return;
        fetch(API_BASE + '/api/metadata', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null))
          .then((meta) => { if (meta) metadata = meta; })
          .catch(() => {});
      });
    }));
  }
  if (name === 'snapshot-center' && !mods.snapshotCenter) {
    jobs.push(importOnce('./snapshot-center.js?v=20261126sc1').then(({ createSnapshotCenter }) => {
      mods.snapshotCenter = createSnapshotCenter({ esc, API_BASE, icon, notify: comboNotify, portrait });
    }));
  }
  if (name === 'official-entry' && !mods.officialEntry) {
    jobs.push(importOnce('./official-entry.js?v=20261122optional').then(({ initOfficialEntry }) => {
      mods.officialEntry = initOfficialEntry;
    }));
  }
  if (name === 'match-notes' && !mods.matchNotesPage) {
    jobs.push(importOnce('./match-notes.js?v=20261123a').then(({ initMatchNotesPage }) => {
      mods.matchNotesPage = initMatchNotesPage;
    }));
  }
  /* 数据源展示：赛事范围内的后端数据图谱（只读），自取数。 */
  if (name === 'sources' && !mods.dataSource) {
    jobs.push(importOnce('./datasource-page.js?v=20261124ds10').then(({ createDataSourcePage }) => {
      mods.dataSource = createDataSourcePage({ esc, API_BASE, icon, notify: comboNotify });
    }));
  }
  /* 管理 → 外部数据源爬取情况：四张状态卡 + 手动重试。 */
  if (name === 'source-health' && !mods.sourceHealth) {
    jobs.push(importOnce('./source-health-page.js?v=20261124sh1').then(({ createSourceHealthPage }) => {
      mods.sourceHealth = createSourceHealthPage({ esc, API_BASE, icon, notify: comboNotify });
    }));
  }
  await Promise.all(jobs);
}

/* 赛训组保存评级规则后，让下次打开的对局页重新取规则（评级按钮就地重画）。 */
let gradeRulesDoc = null;
document.addEventListener('grade-rules:saved', () => { gradeRulesDoc = null; });
/* 比赛脉搏交互需要原始序列，渲染时记下来，注入 DOM 后再绑定。 */
let pulseState = null;
const renderers = { overview: () => '<div class="page home pbr-home" data-pbr-root></div>',
  'team-profile': () => '<div data-tp-root></div><div data-pf-root></div>',
  bp: () => '<div data-bp-lab-root></div>',
  matches: matchesPage, opponents: opponentsPage, players: playersPage,
  player: playerPage, tempo: tempoPage,
  /* 数据源展示改成自取数模块；旧的 sourcesPage（字段覆盖率）已下线。 */
  sources: () => '<div data-ds-root></div>', match: matchPage,
  'source-health': () => '<div data-sh-root></div>',
  cross: () => (mods.crossPage ? mods.crossPage.render() : emptyPage()),
  biggame: () => (mods.bigGamePage ? mods.bigGamePage.render() : emptyPage()),
  'series-builder': () => '<div data-sb-root></div>',
  matching: () => '<div data-matching-root></div>',
  'combo-pool': () => '<div data-cp-root></div>',
  'grade-rules': () => '<div data-gr-root></div>',
  'competitions': () => '<div data-comp-root></div>',
  'lineup-tags': () => '<div data-lt-root></div>',
  'profiles': () => '<div data-pf-root></div>',
  'metrics-observe': () => '<div data-mo-root></div>',
  'rules': () => '<div data-rc-root></div>',
  'snapshot-center': () => '<div data-sc-root></div>',
  'official-entry': () => '<div data-oe-root></div>',
  'match-notes': () => '<div data-mn-root></div>',
  docs: () => (mods.docsPage ? mods.docsPage.render() : emptyPage()) };
const emptyPage = () => '<div class="page"><p class="md-empty">这一页暂时没有可显示的内容。</p></div>';
let routeFocusPending = false;
let docsDispose = null;
let lastRenderedRoute = '';
/* 单局四段页签吸顶：顶栏本身是 sticky，页签要贴在它下面。
   高度量出来写进 CSS 变量，字号 / 窄屏 / 更新横幅都不会把页签盖住。 */
function bindStickyTabs() {
  const bar = document.querySelector('.desk-bar');
  if (!bar) return;
  const sync = () => document.documentElement.style.setProperty(
    '--md-tabs-top', `${Math.round(bar.getBoundingClientRect().height)}px`);
  sync();
  stickyTabsObserver?.disconnect();
  if (typeof ResizeObserver === 'function') {
    stickyTabsObserver = new ResizeObserver(sync);
    stickyTabsObserver.observe(bar);
  }
}
/* 状态条 / 锁卡共用的转义小件。初始化清单已移到右上角入口（见 tour.js）。 */
const onbEsc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

/* ── 数据解锁 v2：分析页按赛事语料阈值渲染锁卡（不隐藏菜单） ────────── */
const UNLOCK_GATED = new Set(['biggame', 'cross']);
let unlockToken = 0;
let unlockState = { loaded: false, competition: '', routes: {} };

async function refreshUnlocks(r = current()) {
  const token = ++unlockToken;
  let competition = '';
  try { competition = localStorage.getItem(COMPETITION_KEY) || ''; } catch {}
  try {
    const url = API_BASE + '/api/v3/unlocks'
      + (competition ? `?competition=${encodeURIComponent(competition)}` : '');
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error('unlocks ' + response.status);
    const data = await response.json();
    if (token !== unlockToken) return;
    /* 以前这里误写成 unlockCache（未定义），严格模式下抛 ReferenceError 被下面
       空 catch 吞掉，unlockState 永不刷新——赛训组把 BO3 改成 BO5 又改回、
       点「已核实」后，大场/跨局解锁进度卡在旧状态，看着像没被收录。 */
    const changed = JSON.stringify(unlockState.routes) !== JSON.stringify(data.routes || {});
    unlockState = { loaded: true, competition, routes: data.routes || {} };
    applyGate();
    /* 旧条件 !document.querySelector('.lock-card') 在「已解锁」页恒真：
       render → refreshUnlocks → render → … 无限重绘，顶栏赛事 chip 因此疯闪。 */
    const gated = UNLOCK_GATED.has(r.name);
    const lockedNow = Boolean(unlockState.routes[r.name] && unlockState.routes[r.name].unlocked === false);
    const hasLockCard = Boolean(document.querySelector('.lock-card'));
    if (gated && (changed || (lockedNow && !hasLockCard) || (!lockedNow && hasLockCard))) render(r);
  } catch (err) { /* 解析失败保持当前页面；别再静默吞掉同类笔误 */
    console.warn('refreshUnlocks failed:', err);
  }
}

function renderUnlockCard(state) {
  const pct = state.need ? Math.min(100, Math.round(state.n / state.need * 100)) : 0;
  const cta = (state.cta || []).map(([href, label]) =>
    `<a class="lock-cta" href="${href}">${glyph('arrow-up', { size: 18 })} ${onbEsc(label)}</a>`).join('');
  return `<section class="lock-card">
    ${glyph('shield', { size: 40 })}
    <span class="lock-kicker">未解锁</span>
    <h2>${onbEsc(state.label)}</h2>
    <p class="lock-hint">${onbEsc(state.hint)}</p>
    <div class="lock-progress"><b>${onbEsc(String(state.n))}<i>/${onbEsc(String(state.need))} ${onbEsc(state.unit)}</i></b>
      <span class="onb-bar"><i style="inline-size:${pct}%"></i></span></div>
    <div class="lock-ctas">${cta}</div>
  </section>`;
}

/* 赛事域：跨局 / BP 工作台等分析页头部统一注入当前赛事 chip。 */
const CHIP_ROUTES = new Set(['cross', 'bp', 'biggame', 'matches', 'teams', 'players', 'heroes']);
function injectEventChip(r) {
  const strip = document.getElementById('desk-event-chip');
  if (!strip) return;
  if (!CHIP_ROUTES.has(r.name)) { strip.hidden = true; return; }
  let id = '', name = '';
  try {
    id = localStorage.getItem(COMPETITION_KEY) || '';
    name = localStorage.getItem(COMPETITION_KEY + '-name') || '';
  } catch {}
  if (!id) {
    if (!strip.hidden) strip.hidden = true;
    return;
  }
  const text = `当前赛事 · ${name || id}`;
  /* route:repainted 在详情页很频繁；内容没变就别整块重建节点，避免闪烁。 */
  if (!strip.hidden && strip.textContent === text) return;
  strip.hidden = false;
  strip.textContent = '';
  const dot = document.createElement('span');
  dot.className = 'desk-event-chip-dot';
  const label = document.createElement('span');
  label.textContent = text;
  strip.append(dot, label);
}

function render(r = current()) {
  lastRouteName = r.name;
  workbenchUI?.updateRoute(r);
  /* 换路由时回到顶部：从很长的单局页切到跨局分析，不重置会停在中段 */
  const routeKey = `${r.name}/${r.key || ''}`;
  const isNewRoute = routeKey !== lastRenderedRoute;
  lastRenderedRoute = routeKey;
  document.title = labels[r.name] + ' | 赛训数据';
  if (UNLOCK_GATED.has(r.name) && unlockState.loaded
      && unlockState.routes[r.name] && unlockState.routes[r.name].unlocked === false) {
    // 门控页也要释放上一个页面的模块，否则监听/轮询会挂在已卸载 DOM 上继续跑。
    docsDispose?.(); docsDispose = null;
    for (const key of ['bpLab', 'brief', 'teamProfile', 'teamProfiles', 'matching',
      'seriesBuilder', 'comboPool', 'gradeRules', 'competitions', 'lineupTags',
      'profiles', 'metricsObserve', 'rulesCenter', 'snapshotCenter', 'dataSource',
      'sourceHealth']) mods[key]?.dispose?.();
    document.querySelector('#content').innerHTML = renderUnlockCard(unlockState.routes[r.name]);
    injectEventChip(r);
    decorateHeadings(r.name);
    return;
  }
  document.querySelector('#content').innerHTML = mods.features?.has(r.name)
    ? mods.features.render(r.name, data, r.key) : renderers[r.name](data, r.key);
  injectEventChip(r);
  decorateHeadings(r.name);
  refreshUnlocks(r);
  mods.features?.afterRender();
  docsDispose?.();
  docsDispose = r.name === 'docs' ? mods.docsPage?.bind(document.querySelector('.help-page')) : null;
  if (r.name === 'match') bindStickyTabs();
  if (r.name === 'bp') {
    /* BP 概览自取数：单页十个内容区，外壳只给挂载点。 */
    mods.bpLab.mount(document.querySelector('[data-bp-lab-root]'));
  } else {
    mods.bpLab?.dispose();
  }
  if (r.name === 'overview') {
    /* 首页简报自取数：每次进入/重渲都由模块按当前周期与全局筛选重新请求，
       空库的首次使用引导在弹窗里（见 showNoDataDialog），首页不摆清单卡。 */
    mods.brief.mount(document.querySelector('[data-pbr-root]'));
  } else {
    /* 切走时撤销简报请求，慢响应不再写回已经离开的页面。 */
    mods.brief?.dispose();
  }
  if (r.name === 'team-profile') {
    mods.teamProfile?.mount(document.querySelector('[data-tp-root]'));
    mods.teamProfiles?.mount(document.querySelector('[data-pf-root]'));
  } else {
    mods.teamProfile?.dispose();
    mods.teamProfiles?.dispose();
  }
  if (r.name === 'matching') {
    /* 匹配页自取数；离开时撤销在途请求与监听。 */
    mods.matching.mount(document.querySelector('[data-matching-root]'));
  } else {
    mods.matching?.dispose();
  }
  if (r.name === 'series-builder') {
    /* 系列赛编组中心自取数（同首页简报模式）。 */
    mods.seriesBuilder.mount(document.querySelector('[data-sb-root]'));
  } else {
    /* 切走时撤销请求并解除 document 级监听。 */
    mods.seriesBuilder?.dispose();
  }
  if (r.name === 'combo-pool') {
    /* 组合池设置页自取数：外壳只给挂载点，切换时撤销在途请求与监听。 */
    mods.comboPool?.mount(document.querySelector('[data-cp-root]'));
  } else {
    mods.comboPool?.dispose();
  }
  if (r.name === 'grade-rules') {
    mods.gradeRules?.mount(document.querySelector('[data-gr-root]'));
  } else {
    mods.gradeRules?.dispose();
  }
  if (r.name === 'competitions') {
    mods.competitions?.mount(document.querySelector('[data-comp-root]'));
  } else {
    mods.competitions?.dispose();
  }
  if (r.name === 'lineup-tags') {
    mods.lineupTags?.mount(document.querySelector('[data-lt-root]'));
  } else {
    mods.lineupTags?.dispose();
  }
  /* 数据管理层新模块：进入挂载、离开释放（init 型模块自填容器、无需 dispose）。 */
  if (r.name === 'profiles') {
    mods.profiles?.mount(document.querySelector('[data-pf-root]'));
  } else {
    mods.profiles?.dispose();
  }
  if (r.name === 'metrics-observe') {
    mods.metricsObserve?.mount(document.querySelector('[data-mo-root]'));
  } else {
    mods.metricsObserve?.dispose();
  }
  if (r.name === 'rules') {
    mods.rulesCenter?.mount(document.querySelector('[data-rc-root]'));
  } else {
    mods.rulesCenter?.dispose();
  }
  if (r.name === 'snapshot-center') {
    mods.snapshotCenter?.mount(document.querySelector('[data-sc-root]'));
  } else {
    mods.snapshotCenter?.dispose();
  }
  if (r.name === 'official-entry') {
    mods.officialEntry?.(document.querySelector('[data-oe-root]'));
  }
  if (r.name === 'match-notes') {
    mods.matchNotesPage?.(document.querySelector('[data-mn-root]'));
  }
  if (r.name === 'sources') {
    mods.dataSource?.mount(document.querySelector('[data-ds-root]'));
  } else {
    mods.dataSource?.dispose();
  }
  if (r.name === 'source-health') {
    mods.sourceHealth?.mount(document.querySelector('[data-sh-root]'));
  } else {
    mods.sourceHealth?.dispose();
  }
  /* 赛事门控：未选赛事时灰掉对局/战队/选手/英雄/BP 等功能入口。 */
  applyGate();
  if (r.name === 'match' && pulseState) mods.deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
  if (r.name === 'match') mods.deep.bindHeat(document);
  if (r.name === 'match') mods.deep.bindBattle(document);
  if (r.name === 'match') mods.deep.bindDuel?.(document);
  if (r.name === 'match') mods.deep.bindTimeline?.(document);
  if (r.name === 'match') mods.deep.bindHScrollHints?.(document);
  if (r.name === 'cross') mods.crossPage.bind(document);
  if (r.name === 'biggame') mods.bigGamePage.bind(document);
  updateMode();
  paintArchiveHighlights(r.name);
  if (isNewRoute) {
    window.scrollTo(0, 0);
    if (routeFocusPending && !document.querySelector('dialog[open]')) app.querySelector('#content').focus({preventScroll:true});
    routeFocusPending = false;
  }
  refreshInbox();
  /* 初始化清单只在右上角入口里呈现；每次换页顺手对一次完成状态，
     这样在任何页面做完动作都能即时弹出「你已完成 …」。 */
  checklist.afterRender();
  /* 部分页面由模块异步挂载标题：标题一出现就补图标。 */
  watchHeadings(r.name);
  if (r.name === 'matches' && archiveScrollRemember > 0) {
    const y = archiveScrollRemember;
    archiveScrollRemember = 0;
    requestAnimationFrame(() => window.scrollTo(0, y));
  }
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
  /* 文档页是静态内容：不拉业务数据，断网也能看说明和错误码。 */
  if (r.name === 'docs') {
    data = null;
    render(r);
    return;
  }
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
  /* 匹配页自取数：一次拿轻量对局 + 选手池 + 战队池，写操作也由模块自己发。 */
  if (r.name === 'matching') {
    data = null;
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
  /* 组合池设置页自取数（combo-pool.js）：与系列赛编组同模式，不走通用
     /api/<route> 管道；英雄头像目录按需补一次，到了只补画头像不动表单。 */
  if (r.name === 'combo-pool') {
    data = null;
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        if (current().name === 'combo-pool') mods.comboPool?.rerender();
      }).catch(() => { /* 头像缺失时保留文字占位 */ });
    }
    render(r);
    return;
  }
  /* 评级规则设置页自取数（grade-rules.js），与组合池同模式。 */
  if (r.name === 'grade-rules') {
    data = null;
    render(r);
    return;
  }
  /* 外部数据源爬取状态自取数（source-health-page.js），不走通用 /api/sources。 */
  if (r.name === 'source-health') {
    data = null;
    render(r);
    return;
  }
  /* 赛事列表页自取数（competitions.js），与组合池同模式。 */
  if (r.name === 'competitions') {
    data = null;
    render(r);
    return;
  }
  /* 数据源展示自取数（datasource-page.js）：整页只读 /api/studio/workspace/data-map。
     不能走通用 /api/sources，否则旧字段覆盖率的错误态会盖掉图谱。 */
  if (r.name === 'sources') {
    data = null;
    render(r);
    return;
  }
  /* 阵容标签页自取数（lineup-tags.js），与组合池同模式；英雄头像目录按需
     补一次，到了补画头像网格与标签卡，不让整页等完整 metadata（冷启动约 3 秒）。 */
  if (r.name === 'lineup-tags') {
    data = null;
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        if (current().name === 'lineup-tags') mods.lineupTags?.rerender();
      }).catch(() => { /* 头像缺失时保留文字占位 */ });
    }
    render(r);
    return;
  }
  /* 数据管理层新模块（2026-11-22）全部自取数：
     档案管理 / 指标观察 / 规则中心 / 正式录入 / 赛后笔记均自己 fetch，
     不走通用 /api/<route> 管道，否则会落到"暂时读不到数据"。 */
  if (r.name === 'rules') {
    data = null;
    /* 规则中心同样按需补一次头像目录：克制弹窗的头像选择 / 筛选、英雄标签表都用它。 */
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        if (current().name === 'rules') mods.rulesCenter?.rerender();
      }).catch(() => { /* 头像缺失时保留文字占位 */ });
    }
    render(r);
    return;
  }
  /* 快照中心的英雄头像需要头像目录；和规则中心同模式按需补一次。 */
  if (r.name === 'snapshot-center') {
    data = null;
    if (!metadata.icons || metadata.iconsOnly) {
      get('metadata/icons').then((meta) => {
        metadata = { ...metadata, icons: meta.icons, heroTypes: meta.heroTypes || metadata.heroTypes, iconsOnly: true };
        if (current().name === 'snapshot-center') mods.snapshotCenter?.rerender();
      }).catch(() => { /* 头像缺失时保留占位字 */ });
    }
    render(r);
    return;
  }
  if (['team-profile', 'profiles', 'metrics-observe', 'rules', 'official-entry', 'match-notes'].includes(r.name)) {
    data = null;
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
    /* 对方战队是纯主数据页：战队与选手两张表一起读，渲染时按战队分组。 */
    const pageData = r.name === 'opponents'
      ? Promise.all([get('studio/workspace/teams', fresh), get('studio/workspace/players', fresh)])
          .then(([teamData, playerData]) => ({ teams: teamData.teams || [], ownTeamId: teamData.ownTeamId || '', players: playerData.players || [] }))
      : (r.name === 'cross' || r.name === 'biggame') ? Promise.resolve({})
      : (mods.features?.has(r.name) ? mods.features.load(r.name, r.key, currentRequest.signal, fresh) : get(endpoint, fresh));
    const [result, meta] = await Promise.all([pageData, (metadata.icons && !metadata.iconsOnly) ? Promise.resolve(metadata) : get('metadata')]);
    if (stale()) return;
    metadata = meta;
    data = result || {};
    retryByRoute.delete(routeKey);
    if (r.name === 'match') data.replayStatus = 'loading';
    /* 评级规则先取到再渲染：这样 10 分钟经济档位与选手字段徽标首屏就按赛训口径。 */
    if (r.name === 'match') await ensureGradeRules();
    if (stale()) return;
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
        try {
          // 带当前赛事读取：后端优先返回该赛事的定稿快照，复盘旧赛事不会被后来的改动串味。
          let counterComp = '';
          try { counterComp = localStorage.getItem(COMPETITION_KEY) || ''; } catch {}
          const countersUrl = API_BASE + '/api/v3/rules-center/counters'
            + (counterComp ? `?competition=${encodeURIComponent(counterComp)}` : '');
          const countersResponse = await fetch(countersUrl, { signal: currentRequest.signal, cache: 'no-store' });
          if (countersResponse.ok) data.rulesCounters = await countersResponse.json();
        } catch { /* 规则中心克制关系失败不影响主页面 */ }
        try {
          const poolResponse = await fetch(API_BASE + '/api/v3/custom-combos', { signal: currentRequest.signal, cache: 'no-store' });
          if (poolResponse.ok) data.comboPool = await poolResponse.json();
        } catch { /* 组合池失败不影响主页面 */ }
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
          if (pane) {
            /* 回放事件异步到达：#match-resource-detail 首屏还不存在，不能 append 到页签末尾
               （那样会掉到阶段对比下面）。找它在 temp 里的下一个已有区块当锚点，插回原位。 */
            let anchor = null;
            let sibling = updated.nextElementSibling;
            while (sibling && !anchor) {
              if (sibling.id) anchor = document.getElementById(sibling.id);
              sibling = sibling.nextElementSibling;
            }
            if (anchor?.parentElement) anchor.parentElement.insertBefore(updated, anchor);
            else pane.append(updated);
          }
        }
        /* 新版不再渲染的区块（首屏的「没有团战数据」占位等）直接撤掉 */
        for (const old of document.querySelectorAll(paneSections)) {
          if (!keep.has(old.id)) old.remove();
        }
        if (pulseState) mods.deep.bindPulse(document, pulseState.series, pulseState.events, pulseState.own);
        mods.deep.bindHeat(document);
        mods.deep.bindBattle(document);
        mods.deep.bindDuel?.(document);
        mods.deep.bindTimeline?.(document);
        mods.deep.bindHScrollHints?.(document);
      }
    }
  } catch (error) {
    /* 渲染异常以前被静默吞掉，页面只剩骨架屏、无从定位；留一行日志便于排查。 */
    console.error('[md-render]', error && (error.stack || error.message || error));
    /* 主动取消的请求、已经切走的页面：既不重试，也不把错误写进新页面。 */
    if (stale() || isCancelled(error, currentRequest.signal)) return;
    /* 网络层断开：进入自动重连，恢复后自动加载当前页。 */
    // TypeError 也可能是渲染器内部空引用；只有「fetch 形状」的 TypeError 才算断网。
    const offline = error instanceof TypeError
      && /Failed to fetch|NetworkError|Load failed|Network request failed/i.test(
        String(error && error.message || ''));
    if (offline) {
      setOffline(true);
      renderOffline(r, error);
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
    renderDataNotice(r, error);
  }
}

function namePlayerDialog(label) {
  const dialog = dialogFor();
  const team = (metadata && metadata.teamName) || '';
  dialog.innerHTML = `<form id="name-form"><div class="dialog-head"><div><h2>${glyph('players', { size: 20 })} 命名并归队</h2><p>保存后这些记录并入该选手。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">
      <div class="date-fields"><label>对局昵称<input value="${esc(label)}" readonly></label><label>选手名称<input name="name" required maxlength="40" value="${esc(label)}"></label></div>
      <div class="date-fields"><label>所属战队<input name="team" maxlength="40" value="${esc(team)}" placeholder="默认本队"></label></div>
      <fieldset class="sx-pos-field"><legend>位置（可多选，第一个勾的是主位置）</legend><div class="sx-pos-chips">${['对抗路', '打野', '中路', '发育路', '游走'].map((x) => `<label class="sx-pos-chip"><input type="checkbox" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
      <p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">取消</button><button class="primary" type="submit">${glyph('players', { size: 18 })} 保存并归队</button></div></form>`;
  dialog.showModal();
}

/* 取共享弹窗容器：切回普通弹窗时去掉「首次使用引导」用的加宽样式。 */
function dialogFor() {
  const element = document.querySelector('#filters');
  element?.classList.remove('is-wide', 'archive-note-dialog');
  element?.removeAttribute('aria-labelledby');
  return element;
}

function filterDialog() {
  const dialog = dialogFor();
  dialog.innerHTML = `<form id="filter-form"><div class="dialog-head"><div><h2>${glyph('calendar', { size: 20 })} 筛选范围</h2></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><div class="date-fields"><label>开始日期<input type="date" name="from" value="${esc(filters.from)}"></label>
    <label>结束日期<input type="date" name="to" value="${esc(filters.to)}"></label></div><fieldset><legend>数据来源</legend>
    ${Object.entries(sourceName).map(([key, text]) => `<label class="check"><input type="checkbox" name="source" value="${key}" ${filters.source.includes(key) ? 'checked' : ''}>${text}</label>`).join('')}</fieldset>
    <label class="check"><input type="checkbox" name="validation" ${filters.validation ? 'checked' : ''}>包含验证数据</label><p class="filter-error" role="alert"></p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="reset">${glyph('refresh', { size: 18 })} 恢复默认</button><button class="primary" type="submit">${glyph('calendar', { size: 18 })} 应用范围</button></div></form>`;
  if (dialog.open) dialog.close();
  dialog.showModal();
}

function clientMissingDialog() {
  const dialog = dialogFor();
  dialog.innerHTML = `<div class="dialog-head"><div><h2>${glyph('warning', { size: 20 })} 没有检测到客户端</h2>
    <p>可能还没有安装，或系统没有注册 kpl-client://open 协议。</p></div>
    <button type="button" class="head-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body"><p>下载安装后，再点「打开客户端」即可从这里直接进入客户端；当前页面会自动带过去。</p></div>
    <div class="dialog-actions"><button type="button" class="control" data-action="close">稍后</button>
      <a class="primary" href="${CLIENT_DOWNLOAD_URL}" target="_blank" rel="noopener">${glyph('export', { size: 18 })} 下载客户端</a></div>`;
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
  /* 类型切换（训练赛 / 正式比赛 / 全部）：原地重刷列表与计数，开着的候选弹层
     里的口径变了，一并关掉；列表区的无障碍名跟着口径走。 */
  const segButton = event.target.closest('[data-mf-type]');
  if (segButton) {
    event.preventDefault();
    const mf = matchFilters();
    if (mf.type === segButton.dataset.mfType) return;
    mf.type = segButton.dataset.mfType;
    closeMatchFilter();
    refreshMatchResults();
    const ledger = document.querySelector('.archive-ledger');
    if (ledger) ledger.setAttribute('aria-label', { training: '训练赛档案', formal: '正式比赛档案', all: '全部对局档案' }[mf.type] || '训练赛档案');
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
  /* 单局页签：方向键按 tabs 模式移焦并激活（点击逻辑统一走已有的 click 委托）。 */
  const tabKey = event.target.closest?.('[data-md-tab]');
  if (tabKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
    const tabs = [...(tabKey.closest('.md-tabs')?.querySelectorAll('[data-md-tab]') || [])];
    if (tabs.length > 1) {
      const at = tabs.indexOf(tabKey);
      const step = event.key === 'ArrowRight' ? 1 : tabs.length - 1;
      const next = tabs[(at + step) % tabs.length];
      event.preventDefault();
      next.focus();
      next.click();
      return;
    }
  }
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
  /* 赛事门控：被锁的功能入口即使带 href 也不许激活，给出明确引导。 */
  const gatedLink = event.target.closest('a[data-needs-competition]');
  /* 当前页的自链接不该被门控踢走；交给下面的自链接分支原地重载。 */
  if (gatedLink && gatedLink.getAttribute('href') !== location.hash) {
    event.preventDefault();
    event.stopPropagation();
    requestedPage = gatedLink.getAttribute('href');
    const handoff = app.querySelector('.desk-handoff');
    handoff.textContent = '选择赛事后，将自动进入' + gatedLink.textContent.trim() + '。';
    handoff.hidden = false;
    workbenchUI.closeMenu();
    location.hash = '#competitions';
    return;
  }
  /* 点「当前就在这一页」的导航（例如已经在首页再点「首页」）时 hash 不变、不会触发
     hashchange：这里手动重载当前页，避免看起来点了没反应、回不到首页。 */
  const selfLink = event.target.closest('a[href^="#"]');
  if (selfLink && !selfLink.hasAttribute('data-sx-jump') && location.hash && selfLink.getAttribute('href') === location.hash) {
    event.preventDefault();
    load(true);
    return;
  }
  const batchToggle = event.target.closest('[data-archive-batch]');
  const sortButton = event.target.closest('[data-archive-sort]');
  if (sortButton) {
    event.preventDefault();
    const key = sortButton.dataset.archiveSort;
    if (!ARCHIVE_SORTS.some((item) => item.key === key)) return;
    view.archiveSort = key;
    try { localStorage.setItem(ARCHIVE_SORT_KEY, key); } catch {}
    applyArchiveSort(key);
    return;
  }
  if (batchToggle) {
    event.preventDefault();
    view.archiveBatch = !view.archiveBatch;
    if (!view.archiveBatch) view.archiveSelected = new Set();
    render();
    return;
  }
  const libraryTag = event.target.closest('[data-archive-bulk-tag-name]');
  if (libraryTag) {
    event.preventDefault();
    const input = document.querySelector('[data-archive-bulk-tag]');
    if (input) { input.value = libraryTag.dataset.archiveBulkTagName; input.focus(); }
    return;
  }
  const bulkAction = event.target.closest('[data-archive-bulk]');
  if (bulkAction) {
    event.preventDefault();
    handleArchiveBulk(bulkAction.dataset.archiveBulk);
    return;
  }
  const noteButton = event.target.closest('[data-archive-note]');
  if (noteButton) {
    event.preventDefault();
    openArchiveNote(noteButton.dataset.archiveNote);
    return;
  }
  const noteDelete = event.target.closest('[data-archive-note-del]');
  if (noteDelete) {
    event.preventDefault();
    const form = noteDelete.closest('form');
    fetch(API_BASE + '/api/studio/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ matchKey: form?.dataset.key, id: noteDelete.dataset.archiveNoteDel, delete: true }),
    }).then((response) => {
      if (!response.ok) return;
      openArchiveNote(form?.dataset.key);
      reloadArchiveNotes().then(() => { if (current().name === 'matches') refreshMatchResults(); });
    });
    return;
  }
  /* 对方战队：战队与选手建档入口。 */
  if (event.target.closest('[data-opp-team-add]')) { oppTeamDialog(null); return; }
  const teamEdit = event.target.closest('[data-opp-team-edit]');
  if (teamEdit) { oppTeamDialog((data.teams || []).find((t) => t.id === teamEdit.dataset.oppTeamEdit)); return; }
  const teamDel = event.target.closest('[data-opp-team-del]');
  if (teamDel) {
    const t = (data.teams || []).find((x) => x.id === teamDel.dataset.oppTeamDel);
    if (!t) return;
    oppConfirm(`确定删除战队「${t.name || t.id}」？该战队下的选手和账号映射会一并删除，不会留在选手池。`, () => {
      fetch(API_BASE + '/api/studio/workspace/teams/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: t.id }),
      }).then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || '删除失败');
        load(true);
      }).catch((err) => window.alert(err.message || '删除失败'));
    });
    return;
  }
  const playerAdd = event.target.closest('[data-opp-player-add]');
  if (playerAdd) { oppPlayerDialog(null, playerAdd.dataset.oppPlayerAdd, playerAdd.dataset.oppLane); return; }
  const playerEdit = event.target.closest('[data-opp-player-edit]');
  if (playerEdit) { oppPlayerDialog((data?.players || []).find((p) => p.id === playerEdit.dataset.oppPlayerEdit)); return; }
  const playerDel = event.target.closest('[data-opp-player-del]');
  if (playerDel) {
    const p = (data?.players || []).find((x) => x.id === playerDel.dataset.oppPlayerDel);
    if (!p) return;
    oppConfirm(`确定删除选手「${p.camp_user_id || p.name || p.id}」？该选手 ID 和挂着的账号映射会一并删除。`, () => {
      fetch(API_BASE + '/api/studio/workspace/players/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: p.id }),
      }).then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || '删除失败');
        document.querySelector('#filters')?.close();
        load(true);
      }).catch((err) => window.alert(err.message || '删除失败'));
    });
    return;
  }
  if (event.target.closest('[data-decider-open]')) {
    event.preventDefault();
    openDeciderDialog();
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
    button.innerHTML = `${glyph('refresh', { size: 18 })} 应用中…`;
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
      button.innerHTML = `${glyph('compare', { size: 18 })} 应用映射`;
      window.alert(error.message);
    });
    return;
  }
  /* 五路对位表的「详细数据」：就地展开这一路的对位卡片，不再切页签。 */
  const msLaneHit = event.target.closest('[data-ms-lane]');
  if (msLaneHit) {
    const lane = msLaneHit.dataset.msLane;
    const row = msLaneHit.closest('.ms-lane-row');
    const detail = row?.nextElementSibling;
    if (!lane || !detail || !detail.matches('[data-ms-lane-detail]')) return;
    const open = detail.hidden;
    const box = msLaneHit.closest('.ms-lanes');
    box?.querySelectorAll('[data-ms-lane-detail]').forEach((node) => {
      if (node === detail) return;
      node.hidden = true;
      const btn = node.previousElementSibling?.querySelector('[data-ms-lane]');
      if (btn) {
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '详细数据 <span aria-hidden="true">›</span>';
      }
    });
    detail.hidden = !open;
    msLaneHit.setAttribute('aria-expanded', String(open));
    msLaneHit.innerHTML = open
      ? '收起 <span aria-hidden="true">⌃</span>'
      : '详细数据 <span aria-hidden="true">›</span>';
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
      const on = node.dataset.mdTab === key;
      node.setAttribute('aria-selected', String(on));
      node.tabIndex = on ? 0 : -1;
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
  if (action === 'checklist') { checklist.start(); return; }
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
  if (event.target.id === 'opp-team-form') {
    event.preventDefault();
    const form = event.target;
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.aliases = String(payload.aliases || '').split(/[,，]/).map((x) => x.trim()).filter(Boolean);
    if (form.dataset.teamId) payload.id = form.dataset.teamId;
    const error = !String(payload.name || '').trim() ? '请填写战队名称。' : '';
    form.querySelector('.filter-error').textContent = error;
    if (error) return;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    fetch(API_BASE + '/api/studio/workspace/teams', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      document.querySelector('#filters')?.close(); load(true);
    }).catch((err) => { button.disabled = false; form.querySelector('.filter-error').textContent = err.message || '保存失败'; });
    return;
  }
  if (event.target.id === 'opp-player-form') {
    event.preventDefault();
    const form = event.target;
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.aliases = String(payload.aliases || '').split(/[,，]/).map((x) => x.trim()).filter(Boolean);
    payload.teamId = form.dataset.teamId || '';
    const playerId = form.dataset.playerId || '';
    if (playerId) payload.id = playerId;
    const gameId = String(payload.campUserId || '').trim();
    const duplicate = (data?.players || []).some((p) => p.camp_user_id === gameId && p.id !== playerId);
    const error = !gameId ? '请填写选手 ID。' : duplicate ? `选手 ID「${gameId}」已存在，不能重复。` : '';
    form.querySelector('.filter-error').textContent = error;
    if (error) return;
    payload.campUserId = gameId;
    if (!String(payload.name || '').trim()) payload.name = gameId;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    fetch(API_BASE + '/api/studio/workspace/players', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      document.querySelector('#filters')?.close(); load(true);
    }).catch((err) => { button.disabled = false; form.querySelector('.filter-error').textContent = err.message || '保存失败'; });
    return;
  }
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
  if (event.target.id === 'archive-note-form') {
    event.preventDefault();
    const textarea = event.target.querySelector('[name="body"]');
    const body = String(textarea?.value || '').trim();
    if (!body) { event.target.querySelector('.filter-error').textContent = '写点内容再保存。'; textarea?.focus(); return; }
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    fetch(API_BASE + '/api/studio/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ matchKey: event.target.dataset.key, body,
        author: String(event.target.querySelector('[name="author"]')?.value || '').trim() }),
    }).then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || '保存失败');
      const savedKey = event.target.dataset.key;
      try { localStorage.removeItem('training-note-draft:' + savedKey); } catch {}
      openArchiveNote(savedKey);
      reloadArchiveNotes().then(() => { if (current().name === 'matches') refreshMatchResults(); });
    }).catch((error) => {
      button.disabled = false;
      event.target.querySelector('.filter-error').textContent = error.message || '保存失败';
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
  try { localStorage.setItem('training-rebuild-filters', JSON.stringify(filters)); } catch { /* 隐私模式/配额满不能挡住筛选提交 */ }
  document.querySelector('#filters').close();
  load();
});

app.addEventListener('input', (event) => {
  mods.features?.change(event);
  const noteForm = event.target.closest('#archive-note-form');
  if (noteForm) {
    const body = noteForm.querySelector('[name="body"]')?.value || '';
    const author = noteForm.querySelector('[name="author"]')?.value || '';
    try {
      localStorage.setItem('training-note-draft:' + noteForm.dataset.key, JSON.stringify({ body, author }));
      if (author.trim()) localStorage.setItem('training-note-author', author.trim());
    } catch { /* 隐私模式下写不进去也不影响当前编辑 */ }
    const status = noteForm.querySelector('[data-note-draft-status]');
    if (status) status.textContent = body ? '草稿已自动保存在本机' : '';
    return;
  }
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
  paintArchiveHighlights();
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
      const bladeKind = el.dataset.gold10Kind || '';
      const bladePlayer = bladeKind ? { blade: { kind: bladeKind, blade: el.dataset.gold10Blade || '' } } : null;
      const grade = el.value === '' ? null : gold10Grade(lane, Number(el.value), el.dataset.gold10Hero, bladePlayer);
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
  // 弹窗跨页存活会让提交回调在新页 data=null 上取 players，误报成断网。
  document.querySelector('#filters')?.close();
  routeFocusPending = true;
  const nextRoute = current().name;
  if (lastRouteName === 'matches') {
    try { sessionStorage.setItem(ARCHIVE_SCROLL_KEY, String(window.scrollY)); } catch {}
  }
  if (nextRoute === 'matches') {
    try { archiveScrollRemember = Number(sessionStorage.getItem(ARCHIVE_SCROLL_KEY)) || 0; } catch {}
    try { sessionStorage.removeItem(ARCHIVE_SCROLL_KEY); } catch {}
  }
  if (nextRoute !== 'competitions') {
    requestedPage = '';
    app.querySelector('.desk-handoff').hidden = true;
  }
  view = {};
  workbenchUI.closeMenu();
  window.scrollTo(0,0);
  load();
});
document.querySelector('.skip').addEventListener('click', (event) => { event.preventDefault(); document.querySelector('#content').focus(); });
shell();
initUpdateBanner({ API_BASE });
load();
/* 首屏空闲时预取 features.js：采集/对局等页签首次进入不必等 2–8s 骨架。
   importOnce 会复用同一个 promise，真正进入时不会重复下载或实例化。 */
const prefetchFeatures = () => { if (!mods.features) importOnce('./features.js?v=20261127csmin1'); };
if ('requestIdleCallback' in window) requestIdleCallback(prefetchFeatures, { timeout: 2500 });
else setTimeout(prefetchFeatures, 1200);
