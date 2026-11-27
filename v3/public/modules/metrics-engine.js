/* 指标观察引擎（metrics-engine）· 可复用
 * ─────────────────────────────────────────────────────────────────────────────
 * 用途：把「选对象 → 选指标 → 选筛选 → 出对比」抽成无 DOM 依赖的数据引擎，
 *      供「本队选手指标观察」与后续「多场对局分析」共用。图表是纯 SVG 字符串，
 *      沿用项目现有画法（player-compare.js / player-viz.js），不引第三方库。
 *
 * import {
 *   createMetricsEngine, lineChartSvg, downsample,
 *   ATTR_FIELDS, BO_OPTIONS, TYPE_OPTIONS, WINDOW_OPTIONS, DEFAULT_FILTERS,
 * } from './modules/metrics-engine.js';
 *
 * const engine = createMetricsEngine({ apiBase, fetchImpl, esc });
 *
 * API（全部异步方法返回 Promise）：
 *   engine.loadSources()                       -> { rules, board, competitions }
 *       // 并行 GET /api/v3/grade-rules（字段清单与四档阈值）
 *       //     + /api/v3/players-board（本队/对手名单）
 *       //     + /api/studio/workspace/competitions（赛事，失败降级为 []）
 *   engine.listSubjects({ source, lane })      -> [{ id, name, source, lane, games, sample? }]
 *       // source: 'own' | 'opponent' | 'kpl'；kpl 为真实 KPL 分路平均（只有能算的指标）
 *   engine.listMetrics(lane)                   -> { ruleSubject, core: [metric], attrs: [metric] }
 *       // core 来自 grade-rules 的分路字段 + 逐局事实补充字段；attrs 为属性占位字段
 *       // metric: { key, label, unit, direction, thresholds, fromRule, gradeKey, source, placeholder }
 *   engine.filterRows(rows, filters, comps)    -> rows   // BO × 赛事 × 类型 × 时间窗
 *   engine.seriesFor({ subject, metricKey, rows?, filters, lane })
 *                                              -> { subject, metric, points, placeholder, samples }
 *   engine.buildComparison({ subjects, metricKey, filters, lane, mode })
 *                                              -> { series, coreTable, attrTable, notes,
 *                                                   samples, ruleSubject, effectiveLane }
 *       // coreTable/attrTable: [{ key, label, unit, placeholder, cells:[{subject,value,grade}] }]
 *   engine.grade(value, metric)                -> { level:'elite|good|pass|low|na', label:'卓越|…' }
 *   engine.invalidate()                         // 清空详情缓存，下次重新取数
 *
 *   lineChartSvg(series, opts) -> '<svg role="img" …>…</svg>'  // 多序列折线 + 达标参考线
 *       series: [{ name, cls:'s0', pts:[{x,y,label,tip}] }]；opts: { ref, title, desc, W, H, xLabels }
 *
 * 数据口径说明 / TODO：
 *   - 赛事/BO/训练赛类型在现有逐局事实里是弱字段：BO 取 series.bestOf，类型取 series 是否存在，
 *     赛事按 title 或日期窗回溯；这些是「尽力而为」匹配，接入 workspace_store 的正式归档字段后应替换。
 *   - 巅峰分 / 段位 / 英雄战力在选手档案里尚未建字段：ATTR_FIELDS 用确定性占位序列，
 *     placeholder=true，界面必须显示「属性占位数据，待接入档案字段」。
 *   - KPL 分路平均来自 /api/v3/kpl/lane-baseline（KPL BP 逐局事实 + 英雄外部胜率）；
 *     逐局选手面板没有的指标不输出、不对比，曲线也不为 KPL 画假趋势。
 */
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const text = (v) => String(v ?? '').trim();
const defaultEsc = (v) => text(v).replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

export const DEFAULT_API_BASE = (() => {
  // 本文件在 v3/public/modules/ 下，两级向上才是 API 根（v3/）。
  try { return new URL('../..', import.meta.url).pathname.replace(/\/$/, ''); }
  catch { return '/v3'; }
})();

export const BO_OPTIONS = [['', '全部 BO'], ['1', 'BO1'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']];
export const TYPE_OPTIONS = [['', '全部类型'], ['training', '训练赛'], ['formal', '正式赛']];
export const WINDOW_OPTIONS = [['all', '全部时间'], ['7', '近 7 个有数据日'], ['30', '近 30 个有数据日'], ['custom', '自定义区间']];
export const DEFAULT_FILTERS = { bo: '', comp: '', type: '', window: 'all', from: '', to: '' };

/* 逐局事实里有、但 grade-rules 未设阈值的补充核心指标；保持「规则优先」，只补不盖。 */
export const CORE_EXTRAS = [
  { key: 'winRate', label: '分路胜率', unit: '%', direction: 'up' },
  { key: 'heroWinRate', label: '英雄 KPL 胜率', unit: '%', direction: 'up' },
  { key: 'kda', label: 'KDA', unit: '', direction: 'up' },
  { key: 'damageShare', label: '输出占比', unit: '%', direction: 'up' },
  { key: 'goldShare', label: '经济占比', unit: '%', direction: 'up' },
  { key: 'takenShare', label: '承伤占比', unit: '%', direction: 'down' },
];

/* 属性趋势字段：档案字段尚未建立，全部是占位数据（界面必须标注）。 */
export const ATTR_FIELDS = [
  { key: 'peak', label: '巅峰分', unit: '分', direction: 'up', placeholder: true, base: 2560 },
  { key: 'rank', label: '段位', unit: '档', direction: 'up', placeholder: true, base: 7,
    names: ['青铜', '白银', '黄金', '铂金', '钻石', '星耀', '最强王者', '荣耀王者', '传奇王者'] },
  { key: 'power', label: '英雄战力', unit: '战力', direction: 'up', placeholder: true, base: 88 },
];
const ATTR_KEYS = new Set(ATTR_FIELDS.map((f) => f.key));
export const ATTR_RANK_NAMES = ATTR_FIELDS.find((f) => f.key === 'rank').names;

export const MAX_POINTS = 40;    // 单条曲线最多 40 点，防止长赛季画爆
const DAY = 86400000;
const laneFamily = (lane) => (text(lane).startsWith('打野') ? '打野' : text(lane));
const familyMatch = (a, b) => !a || !b || laneFamily(a) === laneFamily(b);
/* 逐局行的 lane 只有「打野」；选中具体子主体时按英雄打野标签分流，
   与 grade_rules.subject_for 同口径（战野/刺野/法核 → 野核，坦野 → 坦野）。 */
function rowLaneSubject(row, lane, heroTypes) {
  const rowLane = text(row && row.lane);
  if (!lane || !rowLane.startsWith('打野') || !String(lane).startsWith('打野')) {
    return familyMatch(rowLane, lane);
  }
  if (lane === '打野') return true;
  const hero = text(row && row.hero);
  const jungle = String(((heroTypes && heroTypes[hero]) || {})['打野'] || '');
  return (jungle.includes('坦野') ? '打野·坦野' : '打野·野核') === lane;
}
const hash = (s) => { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; }

/** 等距抽样，保留首末点；多条曲线叠加时控制 SVG 节点数。 */
export function downsample(points, max = MAX_POINTS) {
  const list = Array.isArray(points) ? points : [];
  if (list.length <= max) return list.slice();
  const stride = Math.ceil(list.length / max);
  const out = [];
  for (let i = 0; i < list.length; i += stride) out.push(list[i]);
  if (out[out.length - 1] !== list[list.length - 1]) out.push(list[list.length - 1]);
  return out;
}

/** 规则四档评级：up 越高越好，down 越低越好；阈值取规则文档的前三档。 */
export function gradeValue(value, metric) {
  if (!isNum(value) || !metric || !Array.isArray(metric.thresholds) || metric.thresholds.length < 3) {
    return { level: 'na', label: metric && metric.fromRule ? '样本不足' : '规则未设阈值' };
  }
  const t = metric.thresholds.map(Number);
  const down = metric.direction === 'down';
  if (down ? value <= t[0] : value >= t[0]) return { level: 'elite', label: '卓越' };
  if (down ? value <= t[1] : value >= t[1]) return { level: 'good', label: '优秀' };
  if (down ? value <= t[2] : value >= t[2]) return { level: 'pass', label: '达标' };
  return { level: 'low', label: '待提升' };
}

function pickRuleSubject(subjects, lane) {
  if (!subjects || typeof subjects !== 'object') return '';
  if (subjects[lane]) return lane;
  if (laneFamily(lane) === '打野') {
    for (const key of ['打野·野核', '打野·坦野', '打野']) if (subjects[key]) return key;
  }
  return '';
}

function attrValue(metric, base, seed, index, count) {
  // 确定性占位序列：轻微波动 + 缓慢上行，绝不伪装成真实档案数据。
  const r = rng(seed + index * 7919);
  const drift = (index / Math.max(1, count - 1) - 0.5) * (metric.key === 'peak' ? 70 : metric.key === 'power' ? 5 : 1);
  const noise = (r() - 0.5) * (metric.key === 'peak' ? 46 : metric.key === 'power' ? 4 : 0.9);
  let v = base + drift + noise;
  if (metric.key === 'rank') v = Math.min(8, Math.max(3, Math.round(v)));
  return Math.round(v * 10) / 10;
}

function attrSeries(subject, metric, count = 14) {
  const seed = hash(`${subject.name}|${metric.key}`);
  const base = subject.sample && subject.sample.attrs && isNum(subject.sample.attrs[metric.key])
    ? subject.sample.attrs[metric.key] : metric.base;
  const today = new Date();
  return Array.from({ length: count }, (_, i) => {
    const day = new Date(today.getTime() - (count - 1 - i) * 7 * DAY).toISOString().slice(0, 10);
    const y = attrValue(metric, base, seed, i, count);
    const shown = metric.key === 'rank' ? (ATTR_RANK_NAMES[Math.round(y)] || `${y} 档`) : `${y} ${metric.unit}`;
    return { x: i, y, label: day, tip: `${subject.name} · ${metric.label}（占位）· ${shown} · 第 ${i + 1} 期` };
  });
}

function dayOf(row) {
  return text(row.day || row.series?.date || row.at || row.date).slice(0, 10);
}
function boOf(row) {
  const v = row.series?.bestOf ?? row.bestOf ?? row.bo;
  return isNum(v) ? String(v) : text(v);
}
function typeOf(row) {
  const raw = text(row.sourceType || row.type || row.source);
  if (/正式|formal|match|official/i.test(raw)) return 'formal';
  if (/训练|training|scrim/i.test(raw)) return 'training';
  // TODO: 现有逐局事实没有明确的赛制来源字段，暂以 series（训练赛系列赛）是否存在推断。
  return row.series ? 'training' : 'formal';
}
function competitionOf(row, comps) {
  const title = `${text(row.title)} ${text(row.match)}`;
  const hit = comps.find((c) => c.name && title.includes(String(c.name)));
  if (hit) return String(hit.id);
  const day = dayOf(row);
  if (!day) return '';
  const inside = comps.filter((c) => c.date && day >= String(c.date) && (!c.end_date || day <= String(c.end_date)));
  // 日期重叠时取起点最近的一场；TODO: 真正口径应由 workspace_store 的归档关系给出。
  inside.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return inside.length ? String(inside[0].id) : '';
}

/** 按 BO × 赛事 × 类型 × 时间窗过滤逐局事实；不改变原数组。 */
export function filterRows(rows, filters = {}, comps = []) {
  const f = { ...DEFAULT_FILTERS, ...filters };
  const list = Array.isArray(rows) ? rows.slice() : [];
  const days = [...new Set(list.map(dayOf).filter(Boolean))].sort();
  let from = '', to = '';
  if (f.window === 'custom') { from = text(f.from); to = text(f.to); if (from && to && from > to) [from, to] = [to, from]; }
  else if (f.window !== 'all') {
    const n = Number(f.window) || 7;
    from = days.slice(-n)[0] || '';
    to = days[days.length - 1] || '';
  }
  return list.filter((row) => {
    if (f.bo && boOf(row) !== String(f.bo)) return false;
    if (f.comp && competitionOf(row, comps) !== String(f.comp)) return false;
    if (f.type && typeOf(row) !== f.type) return false;
    if (f.window !== 'all' && f.window !== 'custom') {
      const d = dayOf(row);
      if (!d || (from && d < from) || (to && d > to)) return false;
    }
    if (f.window === 'custom') {
      const d = dayOf(row);
      if (!d || (from && d < from) || (to && d > to)) return false;
    }
    return true;
  });
}

function metricValue(row, metric) {
  if (!row || !metric) return null;
  // 规则文档的字段名（metric.key）才是逐局事实的取值键；gradeKey 仅作兜底，
  // 防止某条规则的 key 被填成中文标签时整列取不到数。
  const key = metric.key || metric.gradeKey;
  const alt = metric.gradeKey && metric.gradeKey !== key ? metric.gradeKey : null;
  const pick = (name) => (isNum(row[name]) ? row[name] : (alt && isNum(row[alt]) ? row[alt] : null));
  let v;
  if (metric.source === 'tile') {
    const tiles = row.campTiles || row.tiles || [];
    const tile = Array.isArray(tiles) ? tiles.find((t) => t.key === key || t.name === key || t.key === alt) : null;
    v = tile ? tile.value : pick(key);
  } else {
    // 规则里的 tpm 对应逐局事实的 dtpm（分均承伤）。
    v = key === 'tpm' && isNum(row.dtpm) ? row.dtpm : pick(key);
  }
  return isNum(v) ? v : null;
}

function mean(values) {
  const v = values.filter(isNum);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

/**
 * 无 DOM 依赖的可复用引擎。options: { apiBase, fetchImpl, esc }
 */
export function createMetricsEngine(options = {}) {
  const apiBase = text(options.apiBase || DEFAULT_API_BASE).replace(/\/$/, '');
  const doFetch = options.fetchImpl || ((url, init) => fetch(url, init));
  const esc = options.esc || defaultEsc;
  let sources = null;
  let sourcesPending = null;
  const details = new Map();
  const detailPending = new Map();

  async function getJSON(url) {
    const response = await doFetch(url, { cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`${text(url)} 读取失败（${response.status}）`);
    return response.json();
  }

  /* 营地游戏名 → 选手ID：优先 memberId，其次匹配与编组登记的 camp_user_id / 别名。
     没建ID的账号返回 null，不进分析页（游戏名只留在 lookupName 供取数）。 */
  function boundName(p) {
    const members = (sources && sources.board && sources.board.identity && sources.board.identity.members) || [];
    if (p && p.memberId) {
      const owner = members.find((m) => m.id === p.memberId);
      if (owner) return owner.label || owner.name || p.name;
    }
    const raw = text(p && p.name);
    const owner = members.find((m) => m.camp_user_id === raw
      || (Array.isArray(m.aliases) && m.aliases.includes(raw))
      || m.name === raw || m.label === raw);
    return owner ? (owner.label || owner.name || raw) : null;
  }

  async function loadSources() {
    if (sources) return sources;
    if (sourcesPending) return sourcesPending;
    sourcesPending = Promise.all([
      getJSON(`${apiBase}/api/v3/grade-rules`),
      getJSON(`${apiBase}/api/v3/players-board`),
      getJSON(`${apiBase}/api/studio/workspace/competitions`).catch(() => ({ competitions: [] })),
      getJSON(`${apiBase}/api/v3/kpl/lane-baseline`).catch(() => ({ lanes: {} })),
      // 英雄 × 分路标签：逐局行的 lane 只有「打野」，要靠英雄判定坦野/野核。
      getJSON(`${apiBase}/api/metadata/icons`).catch(() => ({})),
    ]).then(([rules, board, competitions, kpl, icons]) => {
      sources = {
        // 未保存过规则时不要拿内置默认档位给指标评级，跟对局/选手页一致。
        rules: rules && rules.saved && rules.subjects ? rules : { subjects: {} },
        board: board && Array.isArray(board.players) ? board : { players: [], games: [] },
        competitions: Array.isArray(competitions?.competitions) ? competitions.competitions : [],
        kpl: kpl && kpl.lanes ? kpl : { lanes: {} },
        heroTypes: icons && icons.heroTypes ? icons.heroTypes : {},
      };
      sourcesPending = null;
      return sources;
    }).catch((error) => { sourcesPending = null; throw error; });
    return sourcesPending;
  }

  function invalidate() {
    sources = null; sourcesPending = null; details.clear(); detailPending.clear();
  }

  async function detail(name) {
    if (details.has(name)) return details.get(name);
    if (detailPending.has(name)) return detailPending.get(name);
    const url = `${apiBase}/api/v3/player-detail?player=${encodeURIComponent(name)}`;
    const job = getJSON(url).then((doc) => { details.set(name, doc); detailPending.delete(name); return doc; })
      .catch((error) => { detailPending.delete(name); throw error; });
    detailPending.set(name, job);
    return job;
  }

  function listSubjects({ source = 'own', lane = '', team = '' } = {}) {
    const src = sources || { board: { players: [] } };
    if (source === 'kpl') {
      const lanes = (src.kpl && src.kpl.lanes) || {};
      return Object.entries(lanes)
        .filter(([name, cell]) => (!lane || familyMatch(name, lane)) && cell && (cell.games || 0) > 0)
        .sort(([a], [b]) => a.localeCompare(b, 'zh-CN'))
        .map(([name, cell]) => ({
          id: `kpl:${name}`, name: `KPL平均 · ${name}`, source: 'kpl', lane: name, games: cell.games,
          baseline: true, metrics: { winRate: cell.winRate, heroWinRate: cell.heroWinRate },
          samples: { winRate: cell.games, heroWinRate: cell.heroWinSamples || 0 },
        }));
    }
    const side = source === 'opponent' ? 'enemy' : 'own';
    const byId = new Map();
    for (const p of (src.board.players || [])) {
      if ((p.side || 'own') !== side || (p.games || 0) <= 0) continue;
      if (lane && !familyMatch(p.lane, lane)) continue;
      const split = source === 'team' && team ? ((p.splits && p.splits.opponent && p.splits.opponent[team]) || null) : null;
      if (source === 'team' && (!split || (split.games || 0) <= 0)) continue;
      const label = boundName(p);
      if (!label) continue; /* 未建ID的营地号不进分析页 */
      const subject = { id: `${source}:${label}`, name: label, lookupName: p.name, bound: true,
        source, lane: p.lane || '', games: split ? split.games : (p.games || 0),
        opponentTeam: source === 'team' ? team : '' };
      const previous = byId.get(label);
      if (!previous || subject.games > previous.games) byId.set(label, subject);
    }
    return [...byId.values()].sort((a, b) => b.games - a.games);
  }

  /** 可选战队：从 players-board 的对手列表里取，带场次供下拉显示。 */
  function listTeams() {
    const src = sources || { board: {} };
    const seen = new Set();
    return ((src.board.opponents || []).map((o) => ({ name: text(o.name), games: o.games || 0 }))
      .filter((o) => o.name && !seen.has(o.name) && seen.add(o.name)))
      .sort((a, b) => b.games - a.games || a.name.localeCompare(b.name, 'zh-CN'));
  }

  function listMetrics(lane = '') {
    const subjects = (sources && sources.rules && sources.rules.subjects) || {};
    const ruleSubject = pickRuleSubject(subjects, lane);
    // 未勾选生效的字段不进入指标表，跟后端 team-hero-insight 的口径一致。
    const fromRules = ruleSubject ? Object.entries(subjects[ruleSubject] || {})
      .filter(([, rule]) => rule && rule.active !== false).map(([key, rule]) => ({
      key, label: text(rule.label || key), unit: text(rule.unit || ''), direction: rule.direction === 'down' ? 'down' : 'up',
      thresholds: Array.isArray(rule.thresholds) ? rule.thresholds : [], fromRule: true,
      gradeKey: text(rule.key || key), source: rule.source === 'tile' ? 'tile' : 'player', placeholder: false,
    })) : [];
    const extras = CORE_EXTRAS.map((m) => ({ ...m, thresholds: [], fromRule: false, gradeKey: m.key,
      source: 'player', placeholder: false }));
    const core = fromRules.concat(extras);
    return { ruleSubject, core, attrs: ATTR_FIELDS.map((m) => ({ ...m, fromRule: false, gradeKey: m.key, source: 'attr' })) };
  }

  function findMetric(lane, key) {
    const all = listMetrics(lane);
    return all.core.concat(all.attrs).find((m) => m.key === key) || null;
  }

  async function rowsFor(subject) {
    // KPL 平均只有聚合值，没有逐局面板；不伪造逐局数据，也不画趋势。
    if (subject.baseline) return [];
    const doc = await detail(subject.lookupName || subject.name);
    const kplHeroes = (doc && doc.kplHeroStats) || {};
    let rows = doc && Array.isArray(doc.rows) ? doc.rows : [];
    /* 战队口径：只保留对该队的逐局样本，不把跨队场次混进来冒充。 */
    if (subject.opponentTeam) rows = rows.filter((r) => (text(r.opponent) || text(r.opponentTeam)) === subject.opponentTeam);
    return rows.slice().map((row) => ({
      ...row,
      winRate: row.result === 'win' ? 100 : (row.result === 'loss' ? 0 : null),
      heroWinRate: isNum(kplHeroes[row.hero]?.winRate) ? kplHeroes[row.hero].winRate : null,
    }));
  }

  async function seriesFor({ subject, metricKey, rows = null, filters = {}, lane = '' }) {
    const metric = findMetric(lane, metricKey);
    const safeMetric = metric || { key: metricKey, label: metricKey, unit: '', direction: 'up', thresholds: [], fromRule: false };
    if (subject.baseline) {
      return { subject, metric: safeMetric, points: [], placeholder: false,
        samples: subject.games || 0, baseline: true };
    }
    const sourceRows = rows || await rowsFor(subject);
    const matching = sourceRows.filter((r) => rowLaneSubject(r, lane, sources && sources.heroTypes));
    if (ATTR_KEYS.has(metricKey)) {
      return { subject, metric: safeMetric, points: attrSeries(subject, safeMetric), placeholder: true, samples: matching.length };
    }
    const points = matching.map((row, i) => {
      const y = metricValue(row, safeMetric);
      if (!isNum(y)) return null;
      const d = dayOf(row) || `第 ${i + 1} 局`;
      const g = gradeValue(y, safeMetric);
      return { x: i, y, label: d, tip: `${subject.name} · ${safeMetric.label} ${y.toFixed(safeMetric.direction === 'down' || y > 50 ? 0 : 2)}${safeMetric.unit ? ' ' + safeMetric.unit : ''} · ${g.label} · ${d} · ${text(row.hero) || '未知英雄'}` };
    }).filter(Boolean).sort((a, b) => String(a.label).localeCompare(String(b.label))
      || a.x - b.x).map((p, i) => ({ ...p, x: i }));
    return { subject, metric: safeMetric, points: downsample(points), placeholder: false, samples: matching.length };
  }

  function tableRow(lane, metric, subject, rows) {
    if (subject.baseline) {
      const value = subject.metrics && isNum(subject.metrics[metric.key]) ? subject.metrics[metric.key] : null;
      return { subject: subject.name, source: 'kpl', value,
        grade: { level: 'na', label: value == null ? '不对比' : 'KPL 平均' },
        samples: (subject.samples && subject.samples[metric.key]) || 0 };
    }
    const matching = rows.filter((r) => rowLaneSubject(r, lane, sources && sources.heroTypes));
    const values = matching.map((r) => metricValue(r, metric));
    const value = mean(values);
    return { subject: subject.name, source: subject.source, value, grade: gradeValue(value, metric), samples: values.filter(isNum).length };
  }

  /**
   * 主入口：选对象 → 选指标 → 选筛选 → 出对比数据。
   * subjects: [{ id, name, source, lane, sample? }]；mode 仅用于界面提示，数据层两种模式都返回全量。
   */
  async function buildComparison({ subjects = [], metricKey = 'gpm', filters = {}, lane = '', mode = 'overlay' } = {}) {
    const src = await loadSources();
    const list = subjects.filter((s) => s && s.name);
    const metrics = listMetrics(lane);
    /* 分路筛选为空时不替用户挑第一对象的分路：多对象跨位置对比会因此丢样本。
       规则主体由 listMetrics 按空分路兜底，每个对象仍用自己的逐局数据。 */
    const effectiveLane = lane || '';
    const rowsBy = new Map();
    const keyOf = (s) => `${s.id || s.name}|${s.opponentTeam || ''}`;
    await Promise.all(list.map(async (s) => { rowsBy.set(keyOf(s), filterRows(await rowsFor(s), filters, src.competitions)); }));

    const series = await Promise.all(list.map((s) => seriesFor({
      subject: s, metricKey, rows: rowsBy.get(keyOf(s)), filters, lane: effectiveLane,
    })));
    const coreTable = metrics.core.map((metric) => ({
      key: metric.key, label: metric.label, unit: metric.unit, placeholder: false, fromRule: metric.fromRule,
      cells: list.map((s) => tableRow(effectiveLane, metric, s, rowsBy.get(keyOf(s)) || [])),
    }));
    const attrTable = metrics.attrs.map((metric) => ({
      key: metric.key, label: metric.label, unit: metric.unit, placeholder: true, fromRule: false,
      cells: list.filter((s) => !s.baseline).map((s) => {
        const s0 = attrSeries(s, metric, 1)[0];
        return { subject: s.name, source: s.source, value: s0.y, grade: { level: 'na', label: '占位' }, samples: 0,
          display: metric.key === 'rank' ? (ATTR_RANK_NAMES[Math.round(s0.y)] || `${s0.y} 档`) : null };
      }),
    }));

    const notes = [];
    if (list.some((s) => s.baseline)) notes.push('KPL 平均只对比能从 KPL 逐局事实算出的指标（胜率类）；其他字段不对比。');
    if (metrics.attrs.length) notes.push('巅峰分 / 段位 / 英雄战力是属性占位数据，待接入选手档案字段。');
    if (!metrics.ruleSubject) notes.push('当前分路没有取到赛训组评级规则，指标按逐局事实字段显示（无四档评级）。');
    if (filters.comp && !src.competitions.length) notes.push('赛事列表未取到，赛事筛选按逐局事实的标题/日期尽力匹配。');
    if (series.some((s) => !s.points.length)) notes.push('有对象在当前筛选下没有可用逐局样本，曲线与表格按「样本不足」显示。');
    if (mode === 'split') notes.push('分栏对比：每栏独立成图，Y 轴按本栏数据自适应；叠加模式使用统一 Y 轴。');

    return { series, coreTable, attrTable, notes, samples: Object.fromEntries([...rowsBy].map(([k, v]) => [k, v.length])),
      ruleSubject: metrics.ruleSubject, effectiveLane, competitions: src.competitions };
  }

  return { loadSources, invalidate, listSubjects, listTeams, listMetrics, filterRows, seriesFor, buildComparison,
    grade: gradeValue, findMetric, get sources() { return sources; } };
}

/**
 * 手绘 SVG 折线（项目现有画法，无第三方依赖）。返回可直接 innerHTML 的字符串。
 * series: [{ name, cls:'s0'…, pts:[{x,y,label,tip}] }]
 * opts.ref: { v, label } 达标参考线；opts.title/desc 提供无障碍文本。
 */
export function lineChartSvg(series = [], opts = {}) {
  const esc = opts.esc || defaultEsc;
  const W = opts.W || 760, H = opts.H || 264;
  const padL = 48, padR = 16, padT = 16, padB = 30;
  const all = series.flatMap((s) => (s.pts || []).map((p) => p.y)).filter(isNum);
  if (!all.length) {
    return `<div class="mo-empty">当前筛选下没有可画的数据点。放宽筛选或换一个指标试试。</div>`;
  }
  const ref = opts.ref && isNum(opts.ref.v) ? opts.ref : null;
  let lo = Math.min(...all, ref ? ref.v : Infinity), hi = Math.max(...all, ref ? ref.v : -Infinity);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const maxLen = Math.max(1, ...series.map((s) => (s.pts || []).length));
  const X = (i) => padL + (maxLen === 1 ? (W - padL - padR) / 2 : i / (maxLen - 1) * (W - padL - padR));
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
  const fmtTick = (v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('zh-CN') : Math.round(v * 10) / 10);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((k) => {
    const y = padT + k * (H - padT - padB);
    return `<line class="mo-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>`
      + `<text class="mo-tick" x="${padL - 8}" y="${(y + 3.5).toFixed(1)}" text-anchor="end">${fmtTick(hi - k * (hi - lo))}</text>`;
  }).join('');
  const labelAt = (s) => (s.pts || []).length ? s.pts[s.pts.length - 1].label : '';
  const labels = (opts.xLabels && opts.xLabels.length ? opts.xLabels
    : (series.find((s) => (s.pts || []).length) || {}).pts || []).map((p) => (typeof p === 'string' ? p : p.label)).filter(Boolean);
  const step = Math.max(1, Math.ceil(labels.length / 5));
  const xText = labels.filter((_, i) => i % step === 0 || i === labels.length - 1).slice(0, 8)
    .map((t, i, arr) => `<text class="mo-tick" x="${X(Math.min(maxLen - 1, i * step)).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(String(t).slice(5) || t)}</text>`).join('');
  const refLine = ref ? `<line class="mo-ref" x1="${padL}" y1="${Y(ref.v).toFixed(1)}" x2="${W - padR}" y2="${Y(ref.v).toFixed(1)}"/>`
    + `<text class="mo-ref-label" x="${W - padR - 4}" y="${(Y(ref.v) - 5).toFixed(1)}" text-anchor="end">${esc(ref.label || '达标线')}</text>` : '';
  const paths = series.map((s, si) => {
    const pts = (s.pts || []).filter((p) => isNum(p.y));
    if (!pts.length) return '';
    const cls = s.cls || `s${si % 6}`;
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x ?? i).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(' ');
    const dots = pts.map((p) => `<circle class="mo-dot ${cls}" cx="${X(p.x ?? 0).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.4"><title>${esc(p.tip || `${s.name}: ${p.y}`)}</title></circle>`).join('');
    /* 单序列且点数不多时直接把数值写在点旁，避免「一条线看不出是多少」。 */
    const labels = series.length === 1 && pts.length <= 8 ? pts.map((p) => {
      const cx = X(p.x ?? 0), cy = Y(p.y);
      const ty = cy - 9 < padT + 2 ? cy + 15 : cy - 9;
      return `<text class="mo-point-label" x="${cx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="middle">${fmtTick(p.y)}</text>`;
    }).join('') : '';
    return `<path class="mo-line ${cls}" d="${d}" fill="none"/>${dots}${labels}`;
  }).join('');
  const title = opts.title || '指标趋势';
  const desc = opts.desc || series.map((s) => {
    const pts = s.pts || []; const last = pts[pts.length - 1];
    return `${s.name}：${pts.length} 个点，末值 ${last ? fmtTick(last.y) : '无'}`;
  }).join('；');
  return `<svg class="mo-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">
    <title>${esc(title)}</title><desc>${esc(desc)}</desc>
    ${grid}${refLine}${paths}${xText}
  </svg>`;
}

export default createMetricsEngine;
