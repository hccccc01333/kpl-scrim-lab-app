/* 跨局分析（2026-11-16 · 系列赛级 · 赛中 / 赛后 / 英雄和 BP）
 *
 * 这一页的单位是「大场」：把多场已确认的 BO3/5/7 放在一起看。
 * 三区：赛中（过程归因）/ 赛后（选手执行）/ 英雄和 BP（对位情报）。
 * 单场 BO 是独立模块 #biggame（大场分析），不嵌在本页。
 *
 * 数据：系列赛汇总 + 各局向量；范围/赛制/对手在前端过滤，
 * 选中大场的 seriesId 圈定小局，再交给 cross-analytics 做统计。
 * 「环比」= 同一筛选条件下、紧邻的等长上一段时间；全部时间没有上一段，就不给环比。
 */

import { analyzeCohort, fmt, LANES, internals, LEAD_TIERS, BIG_LEAD_AT10 } from './cross-analytics.js';
import { renderViz } from './cross-viz.js';
import { glyph } from './ui-icons.js';

const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

/* 赛事域（M1）：跨局页自带取数，统一在这里补当前赛事参数。 */
const currentCompetitionId = () => {
  try { return localStorage.getItem('training-current-competition') || ''; } catch { return ''; }
};
const scopedSeriesUrl = (path) => {
  const competition = currentCompetitionId();
  if (!competition) return path;
  return `${path}${path.includes('?') ? '&' : '?'}competition=${encodeURIComponent(competition)}`;
};

const RANGE_OPTIONS = [['all', '全部'], ['3', '近 3 天'], ['7', '近 7 天'], ['30', '近 30 天'], ['custom', '自定义']];
const BO_OPTIONS = [['', '全部'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']];
const SIDE_OPTIONS = [['own', '本队'], ['foe', '敌方']];
const SECTIONS = [
  { key: 'ingame', num: '01', label: '赛中', note: '过程归因：经济路径、前期节奏、领先守成、资源兑现、团战' },
  { key: 'postgame', num: '02', label: '赛后', note: '选手执行：五路每人做了什么，跟对手同位置差在哪' },
  { key: 'draft', num: '03', label: '英雄和 BP', note: '英雄类型、体系、英雄池、组合、红蓝方、楼层分析、对位台' },
];
/* 每个分区右上角的模块索引：长页面里不用滚回顶部找。 */
const SECTION_INDEX = {
  ingame: [['ingame-economy', '经济路径'], ['ingame-tempo', '前期节奏'], ['ingame-lead', '领先守成'], ['ingame-obj', '资源兑现'], ['ingame-fight', '团战']],
  postgame: [['post-exec', '选手执行']],
  draft: [['draft-arch', '打法类型'], ['draft-comp', '体系'], ['draft-pool', '英雄池'], ['draft-pair', '双人组合'], ['draft-sides', '红蓝方'], ['draft-floor', '楼层分析'], ['draft-bp', '对位台']],
};

/* 对面楼层：按 BP 的 pick 顺序。
   蓝方：1L 单 → 2L+3L 成对 → 4L+5L 成对；
   红方：1L+2L 成对 → 3L 单 → 4L 单 → 5L 单（counter）。
   只用于「只看对面」楼层分析的英雄视图；slot 是 heroesFoe 里的下标。
   组合视图与这些楼层按钮解耦：只按红蓝方取数，在对面 5 手里找组合池命中。 */
const FLOOR_SETS = {
  blue: [
    { key: '1', label: '1L', slots: [0] },
    { key: '2-3', label: '2L + 3L', slots: [1, 2] },
    { key: '4-5', label: '4L + 5L', slots: [3, 4] },
    { key: 'first4', label: '前 4 手', slots: [0, 1, 2, 3] },
  ],
  red: [
    { key: '1-2', label: '1L + 2L', slots: [0, 1] },
    { key: '3', label: '3L', slots: [2] },
    { key: '4', label: '4L', slots: [3] },
    { key: '5', label: '5L · counter', slots: [4], counter: true },
    { key: 'first4', label: '前 4 手', slots: [0, 1, 2, 3] },
  ],
};
const COMP_GLOSS = {
  无前排: '五个英雄里没有前排，正面顶不住，靠边路与拉扯',
  单前排: '只有一名前排，正面能顶一阵，第二个身板要靠边路或辅助补',
  多前排: '两名以上前排，正面能顶住，开团与反打更稳',
};
/* 类型颜色按类型名固定，不随某条路的排序变化；同一类型在不同分路表里保持一致。 */
const ARCH_COLORS = {
  战边: '#2f6f5b', 坦边: '#4f7fa3', 刺野: '#a05f77', 战野: '#c18a4f', 坦野: '#7b8a68',
  工具人: '#6a6a8a', 法刺: '#3f7f78', 游射: '#4f7fa3', 呆射: '#c18a4f',
  开团辅: '#a05f77', 保护辅: '#2f6f5b', 功能辅: '#6a6a8a',
};
const DEFAULT_RANGE = 'all';
const COMPLETION_LABEL = { completed: '已完赛', open: '未完赛', interrupted: '中断', incomplete: '采集不完整' };
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const pct100 = (v) => (num(v) ? `${Math.round(v)}%` : '—');
const rateText = (k, n) => (n ? `${k}/${n}（${Math.round(k / n * 100)}%）` : '样本不足');
const rateOf = (r) => (r && num(r.value) ? Math.round(r.value * 100) : null);
const isDate = (text) => /^\d{4}-\d{2}-\d{2}$/.test(String(text || ''));
const isoAddDays = (iso, days) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
const dayDiff = (from, to) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000);
const seriesDate = (s) => String(s.startAt || s.endAt || (s.games || [])[0]?.date || '').slice(0, 10);
const gameResults = (s) => (s.games || []).filter((g) => g.result === 'win' || g.result === 'loss')
  .slice().sort((a, b) => (Number(a.gameIndex) || 0) - (Number(b.gameIndex) || 0));
const scoreValid = (s) => {
  const bestOf = Number(s.bestOf) || 3;
  const max = s.completionMode === 'fixed' ? bestOf : Math.ceil(bestOf / 2);
  return (Number(s.score?.us) || 0) <= max && (Number(s.score?.them) || 0) <= max;
};

/* 「金」是错的：全站写「金币」。这里统一一个格式化。 */
const gold = (v, digits = 0) => {
  if (!num(v)) return '—';
  const abs = digits ? Math.abs(v).toFixed(digits) : Math.round(Math.abs(v)).toLocaleString('zh-CN');
  return `${v < 0 ? '−' : v > 0 ? '+' : ''}${abs}`;
};
const plain = (v, digits = 0) => (num(v) ? (digits ? v.toFixed(digits) : Math.round(v).toLocaleString('zh-CN')) : '—');
const secText = (v) => (num(v) ? `${Math.round(v)} 秒` : '—');
const clock = (v) => (num(v) && v > 0 ? `${Math.floor(Math.round(v) / 60)}:${String(Math.round(v) % 60).padStart(2, '0')}` : '—');


export function createCrossPage(h) {
  const { esc, portrait = () => '' } = h;
  let root = null;
  let generation = 0;
  let controller = null;
  const state = {
    allSeries: [], rulesets: [], latestDate: '', vectors: [], vectorsError: false,
    /* 赛训组组合池：双人组合模块只认这里的名单。 */
    comboPool: null,
    /* 规则中心「克制关系」：对位台给应对英雄标「克制夏侯惇」用，随赛事定稿版本走。 */
    counterRules: null,
    section: SECTIONS[0].key,
    loaded: false, loading: false, error: '',
    detailId: '', detail: null, detailLoading: false, detailError: '',
    /* 页面内交互：BP 分区口径（本队或敌方）/ BP 只看哪个对手 / 对位台选中的英雄 */
    side: 'own', bpOpp: '', bpMode: 'against', bpHeroes: [], bpInit: false,
    /* 楼层分析：只看对面，默认对面蓝方 1L；组合视图是独立开关，只看红蓝方。 */
    floorSide: 'blue', floorSlot: '1', floorMode: 'hero',
    /* 展开中的「看这 N 局」、英雄选择器弹层、选择器搜索词 */
    games: '', picker: '', heroQuery: '',
  };
  const scope = { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '' };
  const vizViews = {};

  /* 「我们 / 对面」跟着视角走：翻到敌方看的时候，句子里的人称也要跟着翻。 */
  let meWord = '我们';
  let themWord = '对手';
  let otherWord = '对手';
  function syncWords() {
    const foe = state.side === 'foe';
    meWord = foe ? '对面' : '我们';
    themWord = foe ? '我们' : '对手';
    otherWord = foe ? '我方' : '对方';
  }
  const sideLabel = () => (state.side === 'foe' ? '敌方' : '本队');

  /* ── 地址与范围 ───────────────────────────────────────────── */
  function readScope() {
    const query = String(location.hash || '').split('?')[1] || '';
    const params = new URLSearchParams(query);
    const pick = (key, allowed, fallback) => (allowed.includes(params.get(key) || '') ? (params.get(key) || '') : fallback);
    scope.range = pick('range', RANGE_OPTIONS.map(([k]) => k), DEFAULT_RANGE);
    scope.bo = pick('bo', ['3', '5', '7'], '');
    state.section = pick('view', SECTIONS.map((x) => x.key), SECTIONS[0].key);
    scope.opponent = String(params.get('opp') || '');
    scope.from = isDate(params.get('from')) ? params.get('from') : '';
    scope.to = isDate(params.get('to')) ? params.get('to') : '';
    if (scope.range !== 'custom' && scope.from && scope.to) scope.range = 'custom';
    if (scope.range !== 'custom') { scope.from = ''; scope.to = ''; }
    state.bpOpp = String(params.get('bpopp') || '');
    state.side = params.get('side') === 'foe' ? 'foe' : 'own';
    state.floorSide = params.get('bside') === 'red' ? 'red' : 'blue';
    const floorKeys = FLOOR_SETS[state.floorSide].map((x) => x.key);
    state.floorSlot = floorKeys.includes(params.get('bfloor') || '') ? params.get('bfloor') : floorKeys[0];
    state.floorMode = params.get('bmode') === 'combo' ? 'combo' : 'hero';
  }

  function scopeQuery() {
    const params = new URLSearchParams();
    if (scope.range !== DEFAULT_RANGE) params.set('range', scope.range);
    if (scope.range === 'custom') {
      if (scope.from) params.set('from', scope.from);
      if (scope.to) params.set('to', scope.to);
    }
    if (scope.bo) params.set('bo', scope.bo);
    if (scope.opponent) params.set('opp', scope.opponent);
    if (state.side === 'foe') params.set('side', 'foe');
    if (state.bpOpp) params.set('bpopp', state.bpOpp);
    if (state.floorSide !== 'blue') params.set('bside', state.floorSide);
    if (state.floorSlot !== FLOOR_SETS[state.floorSide][0].key) params.set('bfloor', state.floorSlot);
    if (state.floorMode === 'combo') params.set('bmode', 'combo');
    if (state.section && state.section !== SECTIONS[0].key) params.set('view', state.section);
    const query = params.toString();
    return query ? `?${query}` : '';
  }

  function routeParts() {
    return String(location.hash || '').replace(/^#/, '').split('?')[0].split('/');
  }

  function detailIdOf() {
    const parts = routeParts();
    return parts[0] === 'cross' && parts[1] === 'series' && parts[2] ? decodeURIComponent(parts[2]) : '';
  }

  function isCrossRoute() {
    return routeParts()[0] === 'cross';
  }

  function syncScopeUrl() {
    const detailId = detailIdOf();
    const path = detailId ? `#cross/series/${encodeURIComponent(detailId)}` : '#cross';
    try { history.replaceState(null, '', `${path}${scopeQuery()}`); } catch { /* 嵌入式浏览器禁 replaceState */ }
  }

  const RANGE_DAYS = { 3: 3, 7: 7, 30: 30 };

  function scopeBounds() {
    if (scope.range === 'custom') return [scope.from, scope.to];
    if (scope.range === 'all' || !state.latestDate) return ['', ''];
    const days = RANGE_DAYS[scope.range] || 7;
    return [isoAddDays(state.latestDate, -(days - 1)), state.latestDate];
  }

  /* 环比窗口：紧邻当前窗口的等长上一段。全部时间没有上一段，返回 null。 */
  function prevBounds() {
    const [from, to] = scopeBounds();
    if (!from || !to) return null;
    const days = dayDiff(from, to) + 1;
    return [isoAddDays(from, -days), isoAddDays(from, -1)];
  }

  function scopeActive() {
    return !!(scope.range !== DEFAULT_RANGE || scope.bo || scope.opponent);
  }

  function scopeLabel() {
    const range = (RANGE_OPTIONS.find(([key]) => key === scope.range) || ['', '全部'])[1];
    const bits = [scope.range === 'custom' && (scope.from || scope.to)
      ? `${scope.from || '最早'} → ${scope.to || '最新'}` : range];
    if (scope.bo) bits.push(`BO${scope.bo}`);
    if (scope.opponent) bits.push(scope.opponent);
    return bits.join(' · ');
  }

  function filteredSeries(bounds) {
    const [from, to] = bounds || scopeBounds();
    return (state.allSeries || []).filter((s) => {
      const day = seriesDate(s);
      if ((from || to) && !day) return false;
      if (from && day < from) return false;
      if (to && day > to) return false;
      if (scope.bo && Number(s.bestOf) !== Number(scope.bo)) return false;
      if (scope.opponent && String(s.opponent || '').trim() !== scope.opponent) return false;
      return true;
    }).sort((a, b) => String(seriesDate(b)).localeCompare(String(seriesDate(a))));
  }

  function selectedVectors(series) {
    const ids = new Set((series || []).map((s) => s.id));
    return (state.vectors || []).filter((v) => ids.has(v.seriesId));
  }

  function uniq(key) {
    return [...new Set((state.allSeries || []).map((s) => String(s[key] || '').trim()).filter(Boolean))].sort();
  }

  /* ── 视角镜像：把每一局翻到对面看 ──────────────────────────────
   * 页面上的「本队 / 敌方」不是一个筛选器，是换一边算：
   * 胜负取反、经济差取反、龙/塔/人头/BUFF 两侧对调、阵容与 ban 两侧对调、
   * 十人面板换成对面那五个人。野区逐秒坐标只有我方打野，翻过去就留空，
   * 不补 0；页面在野区事件不足时显示通用空态「这批局没有可读的野区 BUFF 事件…」，
   * 并不写死「敌方没有逐秒坐标」这类原因文案。 */
  const negate = (v) => (num(v) ? -v : v);
  const flipSide = (side) => (side === 'own' ? 'foe' : side === 'foe' ? 'own' : side);
  function flipVector(v) {
    if (!v || !v.key) return v;
    const camp = v.camp === 'red' ? 'red' : 'blue';
    const other = camp === 'blue' ? 'red' : 'blue';
    const pl = Array.isArray(v.pl) ? v.pl : [];
    const swap = (o, a, b) => (o && typeof o === 'object' ? { ...o, [a]: o[b], [b]: o[a] } : o);
    const fk = v.fk && typeof v.fk === 'object'
      ? {
        ...v.fk,
        adv: v.fk.dis, dis: v.fk.adv, even: v.fk.even,
        first: v.fk.firstAgainst, firstAgainst: v.fk.first,
      }
      : v.fk;
    const fight = v.fight && typeof v.fight === 'object'
      ? {
        ...v.fight,
        win: num(v.fight.win) && num(v.fight.n) ? v.fight.n - v.fight.win : v.fight.win,
        decidedWin: num(v.fight.decidedWin) && num(v.fight.decidedN) ? v.fight.decidedN - v.fight.decidedWin : v.fight.decidedWin,
      }
      : v.fight;
    const first = v.first && typeof v.first === 'object'
      ? {
        ...v.first,
        bloodSide: flipSide(v.first.bloodSide),
        dragonSide: flipSide(v.first.dragonSide),
        towerSide: flipSide(v.first.towerSide),
      }
      : v.first;
    const lanes = v.lanes && typeof v.lanes === 'object'
      ? Object.fromEntries(Object.entries(v.lanes).map(([lane, cell]) => [lane, {
        ...cell, gold: negate(cell.gold), damage: negate(cell.damage), taken: negate(cell.taken),
      }]))
      : v.lanes;
    return {
      ...v,
      camp: other,
      result: v.result === 'win' ? 'loss' : v.result === 'loss' ? 'win' : v.result,
      at10: negate(v.at10), finalDiff: negate(v.finalDiff), at4: negate(v.at4),
      g: Array.isArray(v.g) ? v.g.map(negate) : v.g,
      w: Array.isArray(v.w) ? v.w.map(negate) : v.w,
      s: Array.isArray(v.s) ? v.s.map(negate) : v.s,
      seg: v.seg && typeof v.seg === 'object'
        ? { early: negate(v.seg.early), mid: negate(v.seg.mid), late: negate(v.seg.late) } : v.seg,
      obj: swap(swap(v.obj, 'dragonOwn', 'dragonFoe'), 'towerOwn', 'towerFoe'),
      objAt10: swap(swap(v.objAt10, 'dragonOwn', 'dragonFoe'), 'towerOwn', 'towerFoe'),
      death: swap(v.death, 'own', 'foe'),
      buff: {
        anti: v.buff?.stolen ?? null, stolen: v.buff?.anti ?? null,
        antiRed: v.buff?.stolenRed ?? null, antiBlue: v.buff?.stolenBlue ?? null,
        stolenRed: v.buff?.antiRed ?? null, stolenBlue: v.buff?.antiBlue ?? null,
      },
      fight, fk, first,
      cut: v.cut && typeof v.cut === 'object' ? { ...v.cut, first: null } : v.cut,
      // 对面打野的过河/深入坐标：后端逐局算好放在 jungleFoe，翻过来直接顶上。
      jungle: v.jungleFoe || { crossSec: null, crossShare: null, firstCross: null, deepSec: null, deepShare: null },
      fs: null,
      lanes,
      killsOwn: v.killsFoe, killsFoe: v.killsOwn,
      heroes: Array.isArray(v.heroesFoe) ? v.heroesFoe : [],
      heroesFoe: Array.isArray(v.heroes) ? v.heroes : [],
      bansOwn: Array.isArray(v.bansFoe) ? v.bansFoe : null,
      bansFoe: Array.isArray(v.bansOwn) ? v.bansOwn : null,
      compOwn: Array.isArray(v.compFoe) ? v.compFoe : null,
      compFoe: Array.isArray(v.compOwn) ? v.compOwn : null,
      // prepare() 会按 camp 把 10 人拆成「这边 5 人 / 对面 5 人」，所以这里交回完整十人。
      pl,
      mirrored: true,
    };
  }
  function vectorSide(vectors) {
    return state.side === 'foe' ? (vectors || []).map(flipVector) : (vectors || []);
  }

  /* 环比：上一段时间用同一套筛选重跑一遍，只取要对比的那几个读数。 */
  function prevCohort() {
    const bounds = prevBounds();
    if (!bounds || !state.loaded) return null;
    const series = filteredSeries(bounds);
    if (!series.length) return null;
    return { bounds, cohort: analyzeCohort(vectorSide(selectedVectors(series))) };
  }

  /* 环比读数：cur/prev 都是原始数；没有上一段就写一个横杠，表示「无」。
     cfg.kind 决定单位与是否「越低越好」。 */
  function deltaChip(cur, prev, cfg = {}) {
    if (!num(cur) || !num(prev)) return '<span class="xw-delta is-na">环比 —</span>';
    const diff = cur - prev;
    const kind = cfg.kind || 'num';
    const eps = kind === 'rate' ? 0.004 : Math.max(0.5, Math.abs(prev) * 0.01);
    if (Math.abs(diff) < eps) return `<span class="xw-delta is-flat">持平</span>`;
    const up = diff > 0;
    const text = kind === 'rate' ? `${Math.abs(Math.round(diff * 100))}` : plain(Math.abs(diff), cfg.digits || 0);
    const unit = kind === 'rate' ? '%' : '';
    return `<span class="xw-delta ${up ? 'is-up' : 'is-down'}" title="环比上一段：${plain(prev, cfg.digits || 0)} → ${plain(cur, cfg.digits || 0)}">${up ? '↑' : '↓'}${text}${unit}</span>`;
  }

  /* ── 多场汇总：所有口径都从过滤后的系列赛重算 ───────────────── */
  function deriveSummary(series) {
    const totals = { series: series.length, completed: 0, seriesWins: 0, seriesLosses: 0, games: 0, gameWins: 0 };
    const seq = new Map();
    const cons = new Map();
    const after = [];
    const dist = new Map();
    const boMix = new Map();
    let close = 0, sweep = 0, missing = 0, fixed = 0, invalid = 0, needsReview = 0;
    for (const s of series) {
      if (s.completion === 'completed') totals.completed += 1;
      if (s.completionMode === 'fixed') fixed += 1;
      if (!scoreValid(s)) invalid += 1;
      if (s.status === 'needs_review') needsReview += 1;
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      if (us > them) totals.seriesWins += 1;
      else if (them > us) totals.seriesLosses += 1;
      if (us || them) {
        const key = `${us}:${them}`;
        dist.set(key, (dist.get(key) || 0) + 1);
        if (Math.abs(us - them) === 1) close += 1;
        if (us === 0 || them === 0) sweep += 1;
      }
      boMix.set(Number(s.bestOf) || 3, (boMix.get(Number(s.bestOf) || 3) || 0) + 1);
      missing += (s.coverage?.missingGames || []).length;
      const games = gameResults(s);
      totals.games += games.length;
      totals.gameWins += games.filter((g) => g.result === 'win').length;
      games.forEach((g, i) => {
        const index = Number(g.gameIndex) || i + 1;
        const bucket = seq.get(index) || { gameIndex: index, results: [], at10: [] };
        bucket.results.push(g.result);
        if (num(g.at10)) bucket.at10.push(g.at10);
        seq.set(index, bucket);
        const c = cons.get(index) || { gameIndex: index, us: [], foe: [] };
        if (num(g.usedUsCount)) c.us.push(g.usedUsCount);
        if (num(g.usedFoeCount)) c.foe.push(g.usedFoeCount);
        cons.set(index, c);
        if (i > 0 && games[i - 1].result === 'loss') {
          after.push({
            nextResult: g.result,
            at10Delta: num(games[i - 1].at10) && num(g.at10) ? g.at10 - games[i - 1].at10 : null,
          });
        }
      });
    }
    const decided = totals.seriesWins + totals.seriesLosses;
    const gameSequence = [...seq.values()].sort((a, b) => a.gameIndex - b.gameIndex).map((b) => {
      const wins = b.results.filter((r) => r === 'win').length;
      return {
        gameIndex: b.gameIndex, n: b.results.length, wins,
        winRate: b.results.length ? wins / b.results.length * 100 : null,
        medianAt10: b.at10.length ? fmt.median(b.at10) : null,
        at10Samples: b.at10.length,
      };
    });
    const consumption = [...cons.values()].sort((a, b) => a.gameIndex - b.gameIndex).map((c) => ({
      gameIndex: c.gameIndex,
      avgUsedUs: c.us.length ? c.us.reduce((a, b) => a + b, 0) / c.us.length : null,
      avgUsedFoe: c.foe.length ? c.foe.reduce((a, b) => a + b, 0) / c.foe.length : null,
      n: c.us.length,
    }));
    const nextWins = after.filter((p) => p.nextResult === 'win').length;
    const deltas = after.map((p) => p.at10Delta).filter(num);
    return {
      totals: {
        ...totals,
        seriesWinRate: decided ? totals.seriesWins / decided * 100 : null,
        gameWinRate: totals.games ? totals.gameWins / totals.games * 100 : null,
        ci: decided ? fmt.wilson(totals.seriesWins, decided) : null,
        avgGames: series.length ? totals.games / series.length : null,
      },
      gameSequence, consumption,
      afterLoss: {
        n: after.length, nextWins,
        nextWinRate: after.length ? nextWins / after.length * 100 : null,
        medianAt10Delta: deltas.length ? fmt.median(deltas) : null,
        deltaSamples: deltas.length,
      },
      scoreDist: [...dist.entries()].map(([label, n]) => ({ label, n })).sort((a, b) => b.n - a.n),
      boMix: [...boMix.entries()].sort((a, b) => a[0] - b[0]),
      close, sweep, missing, fixed, invalid, needsReview,
    };
  }

  /* ── 取数 ─────────────────────────────────────────────────── */
  async function loadAll() {
    const gen = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.loading = true;
    state.error = '';
    paintLoading('第 1 步 / 2 · 正在读系列赛与大场…');
    try {
      const [summaryResponse, combosResponse, countersResponse] = await Promise.all([
        fetch(scopedSeriesUrl(`${API_BASE}/api/cross/series-summary`), { signal: controller.signal, cache: 'no-store' }),
        fetch(`${API_BASE}/api/v3/custom-combos`, { signal: controller.signal, cache: 'no-store' }).catch(() => null),
        fetch(scopedSeriesUrl(`${API_BASE}/api/v3/rules-center/counters`), { signal: controller.signal, cache: 'no-store' }).catch(() => null),
      ]);
      if (gen !== generation) return;
      if (!summaryResponse.ok) throw new Error(`系列赛汇总 ${summaryResponse.status}`);
      const payload = await summaryResponse.json();
      state.comboPool = combosResponse?.ok ? await combosResponse.json().catch(() => null) : null;
      /* 克制关系读不到就当没有，不阻塞对位台其它内容。 */
      state.counterRules = countersResponse?.ok ? await countersResponse.json().catch(() => null) : null;
      state.allSeries = payload.series || [];
      state.rulesets = payload.rulesets || [];
      state.latestDate = state.allSeries.map(seriesDate).filter(Boolean).sort().pop() || '';
      paintLoading('第 2 步 / 2 · 正在算各局向量（首次约半分钟，之后走缓存）…');
      const vectorResponse = await fetch(scopedSeriesUrl(`${API_BASE}/api/cross/vectors?source=db%2Cbundle&validation=1`), { signal: controller.signal, cache: 'no-store' });
      if (gen !== generation) return;
      state.vectorsError = !vectorResponse.ok;
      state.vectors = vectorResponse.ok ? ((await vectorResponse.json()).vectors || []) : [];
      state.loaded = true;
    } catch (error) {
      if (gen !== generation) return;
      state.error = String(error && error.message || error);
    }
    state.loading = false;
    if (isCrossRoute() && !detailIdOf()) paint(listHtml());
  }

  async function loadDetail(id) {
    const gen = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.detailId = id;
    state.detailLoading = true;
    state.detailError = '';
    state.detail = null;
    paintLoading('正在读取大场明细…');
    try {
      const response = await fetch(scopedSeriesUrl(`${API_BASE}/api/series/${encodeURIComponent(id)}/analysis`), {
        signal: controller.signal, cache: 'no-store',
      });
      if (gen !== generation) return;
      if (!response.ok) throw new Error(`大场明细 ${response.status}`);
      state.detail = await response.json();
    } catch (error) {
      if (gen !== generation) return;
      state.detailError = String(error && error.message || error);
    }
    state.detailLoading = false;
    if (isCrossRoute() && detailIdOf() === id) paint(detailHtml());
  }

  /* ── 页头：战报台 ──────────────────────────────────────────── */
  function winRateText(value) {
    return num(value) ? `${Math.round(value)}%` : '—';
  }

  /* 大场净胜走势：一场一根柱，赢在上、输在下，柱上写比分。 */
  function trendBlock(series) {
    const list = series.slice(0, 15).reverse();
    if (list.length < 2) return '';
    const diffs = list.map((s) => (Number(s.score?.us) || 0) - (Number(s.score?.them) || 0));
    const max = Math.max(1, ...diffs.map((v) => Math.abs(v)));
    const cols = list.map((s, i) => {
      const diff = diffs[i];
      const us = Number(s.score?.us) || 0;
      const them = Number(s.score?.them) || 0;
      const tone = diff > 0 ? 'is-win' : diff < 0 ? 'is-loss' : 'is-draw';
      const h = (10 + Math.abs(diff) / max * 46).toFixed(1);
      const title = `${seriesDate(s)} ${s.opponent || '对手待补'} ${us}:${them} · 点开看这场大场`;
      /* 平局也要留一根零线，否则整列空白看起来像数据缺失。 */
      const up = diff > 0 ? `<i style="height:${h}px"></i>`
        : diff === 0 ? '<i class="xw-trend-zero" aria-hidden="true"></i>' : '';
      return `<a class="xw-trend-col ${tone}" href="#biggame/${encodeURIComponent(s.id)}" title="${esc(title)}">
        <span class="xw-trend-up">${up}</span>
        <span class="xw-trend-score">${us}:${them}</span>
        <span class="xw-trend-down">${diff < 0 ? `<i style="height:${h}px"></i>` : ''}</span>
      </a>`;
    }).join('');
    return `<div class="xw-trend">
      <div class="xw-trend-head"><b>大场净胜走势</b><span>最近 ${list.length} 场 · 点柱看这场</span></div>
      <div class="xw-trend-rail">${cols}</div>
      <div class="xw-trend-axis"><span>${esc((seriesDate(list[0]) || '—').slice(5))}</span><span>${esc((seriesDate(list[list.length - 1]) || '—').slice(5))}</span></div>
    </div>`;
  }

  function recentBlock(series) {
    const list = series.slice(0, 5);
    if (!list.length) return '';
    return `<div class="xw-recent">
      <div class="xw-block-head"><b>最近大场</b><span>${list.length} 场</span></div>
      ${list.map((s) => {
        const us = Number(s.score?.us) || 0;
        const them = Number(s.score?.them) || 0;
        const tone = us > them ? 'is-win' : them > us ? 'is-loss' : 'is-draw';
        const day = seriesDate(s);
        return `<a class="xw-recent-row ${tone}" href="#biggame/${encodeURIComponent(s.id)}">
          <b>${us}:${them}</b>
          <span>${esc(s.opponent || '对手待补')}</span>
          ${day ? `<small>${esc(day.slice(5))}</small>` : ''}
        </a>`;
      }).join('')}
    </div>`;
  }

  /* 比分带：一个比分一个格子，大字为主，不再画横条。 */
  function scoreDistBlock(sum) {
    if (!sum.scoreDist.length) return '';
    const shown = sum.scoreDist.slice(0, 6);
    const rest = sum.scoreDist.slice(6);
    const restGames = rest.reduce((s, x) => s + x.n, 0);
    return `<div class="xw-scores">
      <div class="xw-block-head"><b>比分分布</b><span>${sum.scoreDist.length} 种</span></div>
      <div class="xw-score-grid">
        ${shown.map((x) => {
          const [us, them] = x.label.split(':').map(Number);
          const tone = us > them ? 'is-win' : them > us ? 'is-loss' : 'is-draw';
          return `<div class="xw-score ${tone}"><b>${esc(x.label)}</b><span>${x.n} 场</span></div>`;
        }).join('')}
      </div>
      ${rest.length ? `<p class="xw-dist-rest">另有 ${rest.length} 种比分合计 ${restGames} 场</p>` : ''}
    </div>`;
  }

  /* 当前口径：把「敌方 / 近 7 天 / BO5 / 对手 D」摊在页头上，点一下就地取消。
     筛选控件还在下面，但教练一眼能确认自己在看哪一档。 */
  function scopeChips() {
    const chips = [];
    if (state.side === 'foe') chips.push(['side', '敌方视角']);
    if (scope.range !== DEFAULT_RANGE) {
      const label = scope.range === 'custom'
        ? `${scope.from || '最早'} → ${scope.to || '最新'}`
        : (RANGE_OPTIONS.find(([key]) => key === scope.range) || ['', ''])[1];
      chips.push(['range', label]);
    }
    if (scope.bo) chips.push(['bo', `BO${scope.bo}`]);
    if (scope.opponent) chips.push(['opp', `对手 ${scope.opponent}`]);
    if (state.bpOpp) chips.push(['bp', `BP 只看 ${state.bpOpp}`]);
    if (!chips.length) return `<div class="xw-scope-row is-empty"><span>全部已确认对局</span></div>`;
    return `<div class="xw-scope-row">
      <span class="xw-scope-label">当前口径</span>
      ${chips.map(([key, label]) => `<button type="button" class="xw-chip is-scope" data-xw-scope="${key}" title="点一下取消这个条件">${esc(label)}<i>×</i></button>`).join('')}
    </div>`;
  }

  function headHtml(sum, series) {
    const t = sum.totals;
    /* 赛训组 2026-11-19：大场就是「大场」，不再写 BO；场均局数删除。
       18–14 是小局总比分（胜–负），标签必须写清楚，不能只写「小局」。 */
    const title = t.series ? `${t.series} 场大场，<em>${t.seriesWins}</em> 胜 <em>${t.seriesLosses}</em> 负` : '当前范围没有系列赛';
    const rate = num(t.seriesWinRate) ? Math.round(t.seriesWinRate) : null;
    const undecided = Math.max(0, t.series - t.seriesWins - t.seriesLosses);
    const kpis = [];
    if (t.games) kpis.push({ n: `${t.gameWins}–${t.games - t.gameWins}`, label: '小局胜–负' });
    if (t.series) kpis.push({ n: String(sum.close), label: '打满' });
    return `<header class="xw-mast">
      <div class="xw-mast-top">
        <p class="xw-eyebrow">跨场分析<i>/</i>多场大场<i>/</i>${esc(scopeLabel())}</p>
        <nav class="xw-mast-links">
          <a href="#biggame">大场分析 <span>↗</span></a>
          <a href="#series-builder">系列赛编组 <span>↗</span></a>
        </nav>
      </div>
      ${scopeChips()}
      <div class="xw-mast-main">
        <div class="xw-mast-copy">
          <h1>${title}</h1>
          <ul class="xw-kpis">${kpis.map((k) => `<li><b>${esc(k.n)}</b><span>${esc(k.label)}</span></li>`).join('')}</ul>
        </div>
        <div class="xw-rate">
          <span class="xw-rate-label">大场胜率</span>
          <div class="xw-rate-num"><b>${rate === null ? '—' : rate}</b>${rate === null ? '' : '<em>%</em>'}</div>
          <p class="xw-rate-foot">${t.seriesWins} 胜 ${t.seriesLosses} 负${undecided ? ` · ${undecided} 场未决` : ''} · 共 ${t.series} 场</p>
        </div>
      </div>
      <div class="xw-mast-foot">
        <div class="xw-mast-trend">${trendBlock(series)}</div>
        <div class="xw-mast-side">${scoreDistBlock(sum)}</div>
        <div class="xw-mast-side">${recentBlock(series)}</div>
      </div>
    </header>`;
  }

  function scopeBarHtml(sum) {
    const seg = (list, current, attr) => `<div class="xw-seg">${list.map(([key, label]) =>
      `<button type="button" class="xw-segbtn" ${attr}="${key}" aria-pressed="${String(current) === key}">${esc(label)}</button>`).join('')}</div>`;
    const select = (key, label, list, value, emptyLabel, attr = 'data-cx') => `<label class="xw-sel"><span>${label}</span><select ${attr}="${key}"${list.length ? '' : ' disabled'}>
      <option value="">${esc(emptyLabel)}</option>${list.map((item) => `<option value="${esc(item)}"${item === value ? ' selected' : ''}>${esc(item)}</option>`).join('')}</select></label>`;
    /* 常打对手：按场次取前 3，点一下就切，不用每次翻下拉。 */
    const rank = new Map();
    for (const s of state.allSeries || []) {
      const name = String(s.opponent || '').trim();
      if (name) rank.set(name, (rank.get(name) || 0) + 1);
    }
    const quick = [...rank.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 3);
    return `<div class="xw-pin">
      <div class="xw-bar">
      <div class="xw-bar-row">
        <div class="xw-filter"><span>视角</span><div class="xw-seg">${SIDE_OPTIONS.map(([key, label]) =>
          `<button type="button" class="xw-segbtn${state.side === key ? ' is-on' : ''}" data-xw-side="${key}" aria-pressed="${state.side === key}">${esc(label)}</button>`).join('')}</div></div>
        <div class="xw-filter"><span>时间</span>${seg(RANGE_OPTIONS, scope.range, 'data-cx-range')}</div>
        ${scope.range === 'custom' ? `<div class="xw-dates"><input type="date" data-cx-date="from" value="${esc(scope.from)}" aria-label="开始日期"><i>→</i><input type="date" data-cx-date="to" value="${esc(scope.to)}" aria-label="结束日期"></div>` : ''}
        <div class="xw-filter"><span>赛制</span>${seg(BO_OPTIONS, scope.bo, 'data-cx-bo')}</div>
        ${select('opponent', '对手', uniq('opponent'), scope.opponent, '全部对手')}
        ${quick.length > 1 ? `<div class="xw-quick"><span>常打</span>${quick.map(([name, n]) =>
          `<button type="button" class="xw-chip${scope.opponent === name ? ' is-on' : ''}" data-cx-opp="${esc(name)}" title="${esc(`${name}：${n} 场`)}">${esc(name)} <b>${n}</b></button>`).join('')}</div>` : ''}
        ${scopeActive() ? `<button type="button" class="xw-clear control" data-cx-clear>${glyph('refresh', { label: '清除筛选', size: 18 })} 清除筛选</button>` : ''}
      </div>
    </div>
      <nav class="xw-tabs" aria-label="跨场分析分区">
        ${SECTIONS.map((section) => `<button type="button" class="xw-tab${section.key === state.section ? ' is-active' : ''}" data-cx-section-link="${section.key}" title="${esc(section.note)}"><b>${section.num}</b>${glyph(section.key === 'ingame' ? 'chart' : section.key === 'postgame' ? 'players' : 'bp', { label: section.label, size: 18 })}<span>${esc(section.label)}</span></button>`).join('')}
      </nav>
    </div>`;
  }

  /* ── 通用块 ─────────────────────────────────────────────────── */
  function module({ id, span = 12, kicker = '', title = '', meta = '', body = '', note = '', extra = '' }) {
    const icon = String(kicker).includes('赛后') ? 'players' : String(kicker).includes('英雄') || String(kicker).includes('BP') ? 'bp' : 'chart';
    return `<article class="xw-mod is-${span}" id="xw-${esc(id)}">
      <div class="xw-mod-head">
        <div class="xw-mod-copy">
          ${kicker ? `<span class="xw-mod-kicker">${glyph(icon, { size: 18 })}${esc(kicker)}</span>` : ''}
          ${title ? `<h3>${title}</h3>` : ''}
        </div>
        ${meta ? `<span class="xw-mod-meta">${meta}</span>` : ''}
      </div>
      ${extra}
      ${body ? `<div class="xw-mod-body">${body}</div>` : ''}
      ${note ? `<p class="xw-mod-note">${note}</p>` : ''}
    </article>`;
  }

  function sectionHead(key, meta, extra = '') {
    const section = SECTIONS.find((x) => x.key === key);
    const index = (SECTION_INDEX[key] || []).map(([id, label]) =>
      `<button type="button" class="xw-index-link" data-xw-jump="${esc(id)}">${esc(label)}</button>`).join('');
    return `<header class="xw-sec-head">
      <div class="xw-sec-title">
        <span class="xw-sec-num">${section.num}</span>
        <h2>${esc(section.label)}</h2>
        <span class="xw-sec-meta">${meta || ''}</span>
      </div>
      ${extra ? `<div class="xw-sec-tools">${extra}</div>` : ''}
      ${index ? `<nav class="xw-index" aria-label="本区模块">${index}</nav>` : ''}
    </header>`;
  }

  function emptyVector(text) {
    return `<div class="xw-empty">${glyph('warning', { label: '暂无数据', size: 22 })}<p class="xw-muted">${esc(text)}</p></div>`;
  }

  /* ── 「看这 N 局」：把结论落回具体对局 ──────────────────────────
     教练看到「大优被翻 11 局」第一反应是哪 11 局，所以每个计数都挂一个
     展开按钮，按 key 反查逐局，点局进单局复盘。 */
  const gamesBtn = (key, n, active) =>
    `<button type="button" class="xw-more${active ? ' is-on' : ''}" data-xw-games="${esc(key)}">${glyph('matches', { label: '看这局', size: 18 })} 看这 ${n} 局</button>`;

  function gamesPanel(a, keys, title, hint = '') {
    const map = new Map((a.rows || []).map((r) => [r.key, r]));
    const list = (keys || []).map((k) => map.get(k)).filter(Boolean)
      .sort((x, y) => String(y.order || '').localeCompare(String(x.order || '')));
    if (!list.length) return '<div class="xw-games-panel"><p class="xw-muted">这批局没有可展开的明细。</p></div>';
    return `<div class="xw-games-panel" id="xw-games-panel">
      <div class="xw-games-head">
        ${glyph('matches', { label: '对局明细', size: 18 })}<b>${esc(title)}</b>
        <span>${list.length} 局 · 按时间倒序</span>
        <button type="button" class="xw-clear control" data-xw-games="${esc(state.games)}">${glyph('arrow-up', { label: '收起', size: 18 })} 收起明细</button>
      </div>
      <div class="xw-gcard-grid">
        ${list.map((r) => `<a class="xw-gcard is-${r.result === 'win' ? 'win' : r.result === 'loss' ? 'loss' : 'na'}" href="#match/${encodeURIComponent(r.key)}">
          <b>${r.result === 'win' ? '胜' : r.result === 'loss' ? '负' : '—'}</b>
          <span>${esc(r.opponent || '对手待补')}</span>
          <small>${esc((r.date || '').slice(5))}${r.clock ? ` · ${esc(String(r.clock))}` : ''}</small>
          <em>10′ ${fmt.signed(r.at10)}</em>
          <em>终 ${fmt.signed(r.final)}</em>
        </a>`).join('')}
      </div>
    </div>`;
  }

  /* 单场大场分析仍复用这个卡片壳；列表页不再使用。 */
  function card({ id, span = 6, kicker, sample, title, lede = '', chart = null, body = '', note = '', method = '' }) {
    /* 口径说明不再挂在标题下面；真正需要保留的限制放到卡片末尾。 */
    const scope = lede
      ? `<p class="xc-card-note">${glyph('warning', { label: '数据口径', size: 16 })} ${esc(lede)}</p>`
      : '';
    return `<article class="xc-card xc-span-${span}" id="xc-${esc(id)}">
      <div class="xc-card-head"><span class="xc-kicker">${glyph('chart', { size: 18 })}${esc(kicker)}</span>${sample ? `<span class="xc-badge">${esc(sample)}</span>` : ''}</div>
      <h3 class="xc-card-title">${title}</h3>
      ${chart ? `<div class="xc-card-chart">${renderViz({ ...chart, id: chart.id || id }, { view: (key) => vizViews[key] || 'a' })}</div>` : ''}
      ${body}
      ${scope}
    </article>`;
  }
  /* 页面内用到的两个小格式化：比例数与正负色（只用文字，不靠红绿）。 */
  const rateNum = (v) => (num(v) ? Math.round(v * 100) : null);

  /* ── 赛中 ───────────────────────────────────────────────────── */
  function ingameStatement(a) {
    if (!a || !a.total) return `<div class="xw-verdict"><p class="xw-verdict-main">这批大场没有可读的赛中过程，先确认对局是否挂上回放。</p></div>`;
    const lead = a.path.lead;
    const risk = a.risk;
    /* 描述、结论、明细三段本质是同一句话：合成一句大结论顶在最前面，
       下面只留一行把结论说清楚，字号压下去，不再三段各占一行抢注意力。 */
    const losses = Math.max(0, lead.n - lead.wins);
    const thrown = Math.min(losses, (risk.throw && risk.throw.k) || 0);
    const games = lead.games || [];
    const detail = games.length
      ? `<em class="xw-lead-word">领先</em>明细：${games.slice(0, 6).map((g) => `${esc(g.label)} <b>${gold(g.at10)}</b>`).join('、')}${games.length > 6 ? ` 等 ${games.length} 局` : ''}。`
      : '';
    /* 两档门槛都写在结论里：≥3,000（默认档）与 ≥5,000（更严档）样本量并列。 */
    const tierLine = LEAD_TIERS.map(({ threshold, word }) =>
      `≥${threshold.toLocaleString('zh-CN')}（${word}领先）${(lead.tiers?.[threshold] || {}).n || 0} 局`).join(' · ');
    let main = '', note = '';
    if (lead.n) {
      const adv = gold(lead.avgAt10);
      const head = `<b>${lead.n}</b> 局 10 分钟平均<em class="xw-lead-word">领先</em> <b>${adv}</b> 金币，`;
      if (!lead.wins && thrown === losses) {
        main = `${head}结果 <b>0 胜 ${losses} 负</b>，全被翻盘。`;
        note = `10 分钟的经济优势一分都没兑现，先复盘 10 分钟后的资源兑现和团战决策。${detail}`;
      } else if (lead.wins > losses) {
        main = `${head}赢下 <b>${lead.wins}</b> 局，前中期优势兑现了。`;
        note = `保持这套前中期节奏。${detail}`;
      } else {
        main = `${head}但只赢下 <b>${lead.wins}</b> 局，兑现不稳定。`;
        note = `重点看丢掉的 ${losses} 局是怎么被追回来的。${detail}`;
      }
    } else {
      main = `这批局没有 10 分钟<em class="xw-lead-word">领先</em> ≥${BIG_LEAD_AT10.toLocaleString('zh-CN')} 金币的样本。`;
      note = '';
    }
    const take = [note, tierLine].filter(Boolean).join(' ');
    return `<div class="xw-verdict"><p class="xw-verdict-main">${main}</p>${take ? `<p class="xw-verdict-take">${take}</p>` : ''}</div>`;
  }

  const tile = ({ label, value, unit = '', sub = '', delta = '' }) =>
    `<div class="xw-tile"><span class="xw-tile-label">${esc(label)}</span><b class="xw-tile-value">${value}${unit ? `<em>${unit}</em>` : ''}</b><span class="xw-tile-sub">${sub}</span>${delta}</div>`;

  function economyModule(a) {
    const risk = a.risk;
    const path = a.path;
    /* 翻盘 / 被翻盘的逐局分布：把 key 反查成逐局卡，带 10 分钟与终局经济。 */
    const byKey = new Map((a.rows || []).map((r) => [r.key, r]));
    const flipOf = (keys) => (keys || []).map((key) => byKey.get(key)).filter(Boolean).map((r) => ({
      key: r.key, label: internals.gameLabelOf(r), at10: r.at10, final: r.final, result: r.result,
    }));
    const flips = {
      throw: flipOf(risk.keys && risk.keys.throw),
      comeback: flipOf(risk.keys && risk.keys.comeback),
      /* 图 6 同时给 3,000 / 5,000 两档逐局名单，按同一套 key 反查，口径与计数一致。 */
      tiers: LEAD_TIERS.map(({ threshold }) => ({
        threshold,
        throw: flipOf(risk.tiers?.[threshold]?.keys?.throw),
        comeback: flipOf(risk.tiers?.[threshold]?.keys?.comeback),
      })),
    };
    return module({
      id: 'ingame-economy', span: 12, kicker: '赛中 · 经济路径', meta: `${path.curve.length ? '4 个阶段锚点' : '过程样本不足'}`,
      title: `赢的局 <em>${gold(path.curve.find((p) => p.key === 'at10')?.win.med)}</em>，输的局 <em>${gold(path.curve.find((p) => p.key === 'at10')?.loss.med)}</em>（10 分钟）`,
      body: renderViz({ type: 'economy', id: 'ingame-economy-viz', curve: path.curve, phase: path.phase, flips }, { view: (key) => vizViews[key] || 'a' }),
    });
  }

  function pitLedger(early) {
    const j = early.jungle;
    if (!num(j.anti)) return '';
    const row = (label, red, blue, hint) => `<div class="xw-ledger-row">
      <span class="xw-ledger-label">${esc(label)}<small>${esc(hint)}</small></span>
      <div><b>${plain(red)}</b><small>红 BUFF</small></div>
      <div><b>${plain(blue)}</b><small>蓝 BUFF</small></div>
    </div>`;
    const n = j.n || 1;
    return `<div class="xw-ledger">
      <div class="xw-block-head"><b>野区帐本</b><span>${j.n} 局有回放 BUFF 事件</span></div>
      ${row('我们反野', Math.round((j.antiRed || 0) * n), Math.round((j.antiBlue || 0) * n), '抢走对方的 BUFF')}
      ${row('被反野', Math.round((j.stolenRed || 0) * n), Math.round((j.stolenBlue || 0) * n), '被对方抢走的 BUFF')}
    </div>`;
  }

  function tempoModule(a, prev) {
    const early = a.early;
    const pe = prev?.cohort?.early;
    const ev = (key) => {
      const e = early[key];
      const sub = `${e.own}/${e.n} 局 · 拿到时平均 ${clock(fmt.median(e.ownT))}`;
      return tile({ label: `${key === 'blood' ? '一血' : key === 'dragon' ? '一龙' : '一塔'}率`, value: rateNum(e.rate) === null ? '—' : String(rateNum(e.rate)), unit: '%', sub, delta: deltaChip(e.rate, pe?.[key]?.rate, { kind: 'rate' }) });
    };
    const j = early.jungle;
    const pj = pe?.jungle;
    /* 野区要么两边都有坐标，要么两边都没有；后端没算出坐标时（没有 positions.json）
       不摆空砖，直接写清楚为什么。 */
    /* 赛训组 2026-11-19：删掉「打野过河」「深入野区」两张卡，只留反野 / 被反野。 */
    const hasJungle = num(j.anti) || num(j.stolen);
    const jungleTiles = [
      tile({ label: '反野 / 场', value: num(j.anti) ? fmt.fixed(j.anti, 1) : '—', unit: ' 次', sub: '红蓝合计', delta: deltaChip(j.anti, pj?.anti, { digits: 1 }) }),
      tile({ label: '被反野 / 场', value: num(j.stolen) ? fmt.fixed(j.stolen, 1) : '—', unit: ' 次', sub: '红蓝合计', delta: deltaChip(j.stolen, pj?.stolen, { digits: 1 }) }),
    ].join('');
    const fourMin = tile({
      label: '4 分钟领先率', value: rateNum(early.at4.leadRate) === null ? '—' : String(rateNum(early.at4.leadRate)), unit: '%',
      sub: `${early.at4.n} 局有一定经济差`, delta: deltaChip(early.at4.leadRate, pe?.at4?.leadRate, { kind: 'rate' }),
    });
    return module({
      id: 'ingame-tempo', span: 12, kicker: '赛中 · 前期节奏', meta: `${early.firstN} 局有一血/一龙/一塔`,
      title: '开局拿到什么，野区压了多少',
      body: `<div class="xw-stack">
        <div>
          <div class="xw-block-head"><b>开局 4 分钟</b><span>分母是该事件可读的局，拿到用时按这边拿到的局算</span></div>
          <div class="xw-tiles">${ev('blood')}${ev('dragon')}${ev('tower')}${fourMin}</div>
        </div>
        ${hasJungle
          ? `<div class="xw-split">
          <div class="xw-split-main">
            <div class="xw-block-head"><b>野区</b><span>0–10 分钟回放 BUFF 事件</span></div>
            <div class="xw-tiles is-two">${jungleTiles}</div>
          </div>
          <div class="xw-split-side">${pitLedger(early)}</div>
        </div>`
          : '<div class="xw-empty-note">这批局没有可读的野区 BUFF 事件，反野 / 被反野算不出来；换成 0 会看错，所以这里留空。</div>'}
      </div>`,
      note: '反野按回放的 BUFF 事件拆分红蓝，不是估计值。',
    });
  }

  function leadModule(a) {
    const risk = a.risk;
    /* 同一指标在两档门槛下各算一份；3,000 档是默认档，5,000 档只在下面并列展示。 */
    const tierRisk = (threshold, field) => risk.tiers?.[threshold]?.[field] || risk[field] || { k: 0, n: 0 };
    const rows = [
      {
        key: 'throw', label: '大优被翻', side: 'lead', field: 'throw',
        hint: (t) => `10 分钟<em class="xw-lead-word">领先</em> ≥${t.toLocaleString('zh-CN')} 金币，最后输掉`,
      },
      {
        key: 'comeback', label: '大劣翻盘', side: 'behind', field: 'comeback',
        hint: (t) => `10 分钟<em class="xw-behind-word">落后</em> ≥${t.toLocaleString('zh-CN')} 金币，最后赢下`,
      },
      {
        key: 'behind', label: '10 分钟落后', side: 'behind', k: risk.behind.k, n: risk.behind.n,
        hint: '<em class="xw-behind-word">落后</em>就算，没有金币门槛',
      },
      {
        key: 'blowLoss', label: '终局被打穿', side: 'behind', k: risk.blowLoss.k, n: risk.blowLoss.n,
        hint: '终局<em class="xw-behind-word">落后</em> 10,000 金币以上',
      },
    ].map((x) => ({
      ...x,
      main: x.field ? tierRisk(BIG_LEAD_AT10, x.field) : { k: x.k, n: x.n },
      keys: (risk.keys && risk.keys[x.key]) || [],
    })).filter((x) => num(x.main.k));
    const openKey = state.games.startsWith('risk:') ? state.games.slice(5) : '';
    const openRow = rows.find((x) => x.key === openKey);
    const tierChips = (x) => LEAD_TIERS.map(({ threshold, word }) => {
      const r = tierRisk(threshold, x.field);
      const sideWord = x.side === 'lead' ? '领先' : '落后';
      return `<span class="xw-tier is-${x.side}"><b>≥${threshold.toLocaleString('zh-CN')}</b><em>${word}${sideWord}</em> ${r.k}/${r.n} 局</span>`;
    }).join('');
    return module({
      id: 'ingame-lead', span: 5, kicker: '赛中 · 领先守成', meta: `${risk.at10.n} 局有 10 分钟经济差`,
      title: rows.length
        ? `大优被翻 <em>${tierRisk(BIG_LEAD_AT10, 'throw').k}</em> 局，大劣翻盘 <em>${tierRisk(BIG_LEAD_AT10, 'comeback').k}</em> 局`
        : '领先守成',
      body: `<div class="xw-counts">${rows.map((x) => `<div class="xw-count-row is-${x.side}${openKey === x.key ? ' is-open' : ''}">
        <b>${x.main.k}</b><span class="xw-count-label">
          <span class="xw-count-name">${esc(x.label)}</span>
          <small><strong>符合条件 ${x.main.n} 局</strong> · ${x.field ? x.hint(BIG_LEAD_AT10) : x.hint}</small>
          ${x.field ? `<span class="xw-tier-line">${tierChips(x)}</span>` : ''}
        </span>
        ${x.keys.length ? gamesBtn(`risk:${x.key}`, x.keys.length, openKey === x.key) : ''}
      </div>`).join('')}</div>
      ${openRow ? gamesPanel(a, risk.keys[openRow.key], `${openRow.label}：${risk.keys[openRow.key].length} 局`) : ''}`,
      note: '左侧大数字与「符合条件」按 ≥3,000 档统计；≥5,000 是更严档位的同一指标，两档不能相加。四类样本也可能重叠，不能相加。',
    });
  }

  function objectiveModule(a) {
    const obj = a.objective;
    if (!obj || !obj.steps.length) return module({ id: 'ingame-obj', span: 7, kicker: '赛中 · 资源兑现', title: '没有可读的资源样本', body: emptyVector('需要回放里的龙/塔事件。') });
    const openIdx = state.games.startsWith('step:') ? Number(state.games.slice(5)) : -1;
    const steps = obj.steps.map((s, i) => `<div class="xw-step">
      <span class="xw-step-no">${i + 1}</span>
      <span class="xw-step-label">${esc(s.label)}</span>
      <b>${s.n}<em>局</em></b>
      <strong>${s.wins} 胜 · ${num(s.rate.value) ? `${Math.round(s.rate.value * 100)}%` : '—'}</strong>
      ${s.keys && s.keys.length ? `<button type="button" class="xw-more${openIdx === i ? ' is-on' : ''}" data-xw-games="step:${i}">看这 ${s.keys.length} 局</button>` : ''}
    </div>`).join('');
    return module({
      id: 'ingame-obj', span: 7, kicker: '赛中 · 资源兑现', meta: `${obj.n} 局有龙塔事件`,
      title: `控龙 ${plain(obj.dragon.own)} : ${plain(obj.dragon.foe)}，推塔 ${fmt.fixed(obj.tower.own, 1)} : ${fmt.fixed(obj.tower.foe, 1)} 座`,
      body: `<div class="xw-steps">${steps}</div>
        ${openIdx >= 0 && obj.steps[openIdx] ? gamesPanel(a, obj.steps[openIdx].keys, `${obj.steps[openIdx].label}：${obj.steps[openIdx].n} 局`) : ''}
        <div class="xw-facts">
          <span>控龙率 <b>${rateNum(obj.dragon.rate) === null ? '—' : `${rateNum(obj.dragon.rate)}%`}</b></span>
          <span>落后翻盘 <b>${obj.comeback.n} 局里 ${obj.comeback.wins} 局</b></span>
          <span>推塔净差 <b>${fmt.signed(obj.tower.diff)} 座 / 场</b></span>
        </div>`,
      note: '每一步都是「10 分钟领先的局里再满足这个条件」的子集，不是因果链；越往后子集越小，只作趋势。',
    });
  }

  function fightModule(a) {
    const fight = a.fight;
    if (!fight || !fight.n) return module({ id: 'ingame-fight', span: 12, kicker: '赛中 · 团战', title: '没有可读的团战样本', body: emptyVector('需要回放里的击杀团事件。') });
    const buckets = [
      ['多打少', fight.adv], ['人数相同', fight.even], ['少打多', fight.dis],
      ['我们先拿首杀', fight.first], ['对方先拿首杀', fight.firstAgainst],
    ].filter(([, x]) => x && x.n > 0);
    const bucketCards = buckets.map(([label, x]) => `<div class="xw-bucket">
      <span>${esc(label)}</span>
      <b>${Math.round((x.rate.value || 0) * 100)}<em>%</em></b>
      <small>${x.n} 波 · 赢 ${x.wins}</small>
    </div>`).join('');
    const dmg = (fight.damage || []).filter((x) => x && num(x.hurt));
    const damage = dmg.length ? `<div class="xw-dmg">
      <div class="xw-dmg-head"><span>团战输出 / 承伤占比</span><span>每条路独立算，加起来不等于 100%</span></div>
      <div class="xw-dmg-cols">${dmg.map((x) => `<div class="xw-dmg-col">
        <div class="xw-dmg-plot">
          <i class="is-out" style="height:${Math.max(3, (x.hurt || 0) * 100).toFixed(1)}%"><b>${Math.round((x.hurt || 0) * 100)}</b></i>
          <i class="is-in" style="height:${Math.max(3, (x.taken || 0) * 100).toFixed(1)}%"><b>${Math.round((x.taken || 0) * 100)}</b></i>
        </div>
        <span class="xw-dmg-lane">${esc(x.lane)}</span>
      </div>`).join('')}</div>
      <div class="xw-dmg-legend"><span><i class="is-out"></i>团战输出</span><span><i class="is-in"></i>团战承伤</span></div>
    </div>` : '';
    return module({
      id: 'ingame-fight', span: 12, kicker: '赛中 · 团战', meta: `${fight.decided.n} 波有击杀`,
      title: `团战 ${plain(fight.totalN)} 波，场均 ${fmt.fixed(fight.perGame.avg, 1)} 波，胜率 <em>${rateNum(fight.decided.value)}%</em>`,
      body: `<div class="xw-buckets">${bucketCards}</div>${damage}`,
      note: '零击杀的拉扯团不进胜率分母；伤害占比是同一条路在每波团里占我方总伤害的平均值，五条路不能相加。',
    });
  }

  function ingameCards(a, prev) {
    if (!a || !a.total) return module({ id: 'ingame-empty', span: 12, kicker: '赛中', title: '没有可用的赛中数据', body: emptyVector('先确认对局是否已关联回放与过程数据。') });
    return `${economyModule(a)}${tempoModule(a, prev)}${leadModule(a)}${objectiveModule(a)}${fightModule(a)}`;
  }

  /* ── 赛后：选手执行 ─────────────────────────────────────────── */
  const EXEC_METRICS = [
    { key: 'gpm', label: '分均经济', digits: 0, noSupport: true },
    { key: 'dmgShare', label: '输出占比', rate: true, noSupport: true },
    { key: 'tpm', label: '分均承伤', digits: 0 },
    { key: 'part', label: '参团率', rate: true },
    { key: 'd', label: '死亡', digits: 1 },
  ];

  /* 名单只列真正在轮换里的人：同一路取「局数 ≥ 该路最高局数的 20% 且 ≥ 3 局」的前两人。
   * 陪练/改名的一次性昵称不铺进表里，只记一句「另有 N 人」。
   * 同名但分路不同（同昵称被不同人用过）只保留局数最多的那一路，避免一个人占三行。 */
  function rosterOf(own) {
    const byLane = new Map();
    for (const p of own) {
      if (!byLane.has(p.pos)) byLane.set(p.pos, []);
      byLane.get(p.pos).push(p);
    }
    /* 一行一个位置：每个位置取局数最多的那个人。
       同一个昵称在不同位置各有一行是数据事实（同一昵称被不同人用过），
       位置列已经把它们分开，不做跨位置去重。 */
    const rows = [];
    const hidden = [];
    for (const lane of LANES) {
      const list = (byLane.get(lane) || []).slice().sort((a, b) => b.games - a.games);
      if (!list.length) continue;
      rows.push(list[0]);
      hidden.push(...list.slice(1));
    }
    return {
      rows,
      hiddenPlayers: hidden.length,
      hiddenGames: hidden.reduce((s, p) => s + p.games, 0),
    };
  }

  function postgameStatement(a) {
    if (!a || !a.total) return `<p class="xw-statement">这批大场没有可读的赛后面板，先补齐十人结算。</p>`;
    const roster = rosterOf(a.execution.own);
    const top = roster.rows.slice().sort((x, y) => (y.dmgShare || 0) - (x.dmgShare || 0))[0];
    const parts = [`${roster.rows.length} 名轮换选手有结算面板`];
    if (top && num(top.dmgShare)) parts.push(`输出占比最高是 <em>${esc(top.name)}</em>（<em>${Math.round(top.dmgShare * 100)}%</em>，${top.games} 局）`);
    const lowDeath = roster.rows.filter((x) => num(x.d)).sort((x, y) => x.d - y.d)[0];
    if (lowDeath) parts.push(`场均死亡最低是 <em>${esc(lowDeath.name)}</em>（<em>${fmt.fixed(lowDeath.d, 1)}</em>）`);
    return `<p class="xw-statement">${parts.join('；')}。</p>`;
  }

  function execModule(a, prev) {
    const ex = a.execution;
    if (!ex.own.length) return module({ id: 'post-exec', span: 12, kicker: '赛后 · 选手执行', title: '没有可读的选手面板', body: emptyVector('先补齐十人结算。') });
    const pe = prev?.cohort?.execution;
    const roster = rosterOf(ex.own);
    const head = `<div class="xw-exec-head"><span>位置</span><span>选手</span>${EXEC_METRICS.map((m) => `<span>${m.label}</span>`).join('')}</div>`;
    const rows = roster.rows.map((p) => {
      const before = pe?.own.find((x) => x.pos === p.pos && x.name === p.name);
      const foe = ex.foe[p.pos] || {};
      const cells = [];
      let supportPair = false;
      for (const m of EXEC_METRICS) {
        if (m.noSupport && p.pos === '游走') {
          /* 游走不看经济与输出：两列合成一格，别把同一句「不看这项」重复两遍。 */
          if (!supportPair) {
            cells.push('<span class="xw-exec-cell is-na is-span-2"><b>—</b></span>');
            supportPair = true;
          }
          continue;
        }
        const value = p[m.key];
        const text = m.rate ? (num(value) ? `${Math.round(value * 100)}%` : '—') : m.digits ? fmt.fixed(value, m.digits) : plain(value);
        const foeValue = foe[m.key];
        const foeText = m.rate ? (num(foeValue) ? `${Math.round(foeValue * 100)}%` : '') : num(foeValue) ? (m.digits ? fmt.fixed(foeValue, m.digits) : plain(foeValue)) : '';
        const delta = num(value) && before && num(before[m.key]) ? deltaChip(value, before[m.key], m.rate ? { kind: 'rate' } : { digits: m.digits || 0 }) : '';
        /* 赛训组 2026-11-19：不能只摆两个数，要直接说谁好谁坏。
           死亡越少越好，其余指标越高越好；赢的一侧给「本队优 / 对手优 + 差值」。 */
        /* 展示精度相同就视为持平，避免「3.3 vs 3.3 → 对手优 少 0.0」这种噪声。 */
        const comparable = num(value) && num(foeValue) && text !== foeText;
        const ownBetter = comparable && (m.key === 'd' ? value < foeValue : value > foeValue);
        const gapValue = comparable ? Math.abs(value - foeValue) : null;
        const gapText = gapValue === null ? ''
          : m.rate ? `${Math.max(1, Math.round(gapValue * 100))}%`
            : m.digits ? fmt.fixed(gapValue, m.digits) : plain(gapValue);
        const verdict = !comparable ? ''
          : `<em class="xw-exec-verdict is-${ownBetter ? 'own' : 'foe'}">${ownBetter ? '本队优' : '对手优'} ${m.key === 'd' ? `少 ${gapText}` : `+${gapText}`}</em>`;
        cells.push(`<span class="xw-exec-cell${comparable ? (ownBetter ? ' is-own-better' : ' is-foe-better') : ''}"><b>${text}</b>${foeText ? `<i>${otherWord} ${foeText}${verdict}</i>` : '<i class="is-empty">—</i>'}${delta}</span>`);
      }
      return `<div class="xw-exec-row">
        <span class="xw-exec-lane">${esc(p.pos)}</span>
        <span class="xw-exec-who"><b>${esc(p.name)}</b><small>${p.games} 局</small></span>
        ${cells.join('')}
      </div>`;
    }).join('');
    return module({
      id: 'post-exec', span: 12, kicker: '赛后 · 选手执行',
      title: '每个位置做了什么，跟对手同位置差在哪',
      body: `<div class="xw-exec">${head}${rows}</div>`,
    });
  }

  function postgameCards(a, prev) {
    return execModule(a, prev);
  }

  /* 体系只按前排数量分三档：0 = 无前排，1 = 单前排，2+ = 多前排。
     旧的功能标签（保护链/强开团等）不再进入这个模块。 */
  function frontCompStats(rows) {
    const order = ['无前排', '单前排', '多前排'];
    const map = new Map(order.map((tag) => [tag, { tag, games: 0, wins: 0, decided: 0 }]));
    for (const r of rows || []) {
      const tags = Array.isArray(r.compOwn) ? r.compOwn : [];
      if (!tags.length) continue;
      const tag = tags.includes('无前排') ? '无前排' : tags.includes('双前排') ? '多前排' : '单前排';
      const e = map.get(tag);
      e.games += 1;
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
    }
    return order.map((tag) => {
      const e = map.get(tag);
      return {
        ...e,
        rate: e.decided ? { value: e.wins / e.decided } : null,
        share: (rows || []).length ? e.games / rows.length : null,
      };
    }).filter((x) => x.games);
  }

  /* ── 英雄和 BP ──────────────────────────────────────────────── */
  function draftTools(opponents) {
    return `<div class="xw-tools">
      <label class="xw-sel"><span>只看对手</span><select data-xw="bp-opp">
        <option value="">全部对手</option>
        ${opponents.map((name) => `<option value="${esc(name)}"${state.bpOpp === name ? ' selected' : ''}>${esc(name)}</option>`).join('')}
      </select></label>
    </div>`;
  }

  function archetypeModule(dp) {
    const data = dp.archetypes.own;
    if (!data.length) return module({ id: 'draft-arch', span: 12, kicker: '英雄和 BP · 打法类型', title: '没有可读的分路类型', body: emptyVector('十人面板缺少英雄或分路。') });
    const body = data.map((lane) => {
      const total = Math.max(1, lane.n);
      const ranked = lane.items.slice().sort((a, b) => b.games - a.games || lane.items.indexOf(a) - lane.items.indexOf(b));
      const primary = ranked[0];
      const primaryShare = Math.round(primary.games / total * 100);
      const mix = primaryShare >= 75 ? `主玩${primary.arch}` : ranked.length > 1 ? `${ranked.length} 类轮换` : `只拿${primary.arch}`;
      const colorOf = (arch) => ARCH_COLORS[arch] || '#7b8a68';
      const bandLabel = ranked.map((x) => `${x.arch} ${x.games} 局（${Math.round(x.games / total * 100)}%）`).join('；');
      const band = ranked.map((x) => `<span class="xw-arch-fill" style="flex:${x.games};--arch-color:${colorOf(x.arch)}" aria-hidden="true"></span>`).join('');
      const types = ranked.map((x, i) => `<li${i === 0 ? ' class="is-primary"' : ''}>
        <i style="--arch-color:${colorOf(x.arch)}" aria-hidden="true"></i><b>${esc(x.arch)}</b><span>${x.games} 局</span><em>${Math.round(x.games / total * 100)}%</em>
      </li>`).join('');
      const miss = lane.unknown && lane.unknown.games
        ? `<p class="xw-arch-miss">另有 ${lane.unknown.games} 局未识别类型（${esc(lane.unknown.heroes.slice(0, 3).join('、'))}），不计入占比。</p>`
        : '';
      return `<article class="xw-arch-card" role="listitem">
        <header class="xw-arch-card-head"><h4>${esc(lane.lane)}</h4><span>${lane.n} 局有类型</span></header>
        <div class="xw-arch-primary"><span>${esc(mix)}</span><div><b>${esc(primary.arch)}</b><strong>${primaryShare}%</strong></div><small>${primary.games} / ${lane.n} 局</small></div>
        <div class="xw-arch-bar" role="img" aria-label="${esc(`${lane.lane}：${bandLabel}`)}">${band}</div>
        <ul class="xw-arch-types" aria-label="${esc(`${lane.lane}类型清单`)}">${types}</ul>
        ${miss}
      </article>`;
    }).join('');
    const total = data.reduce((s, x) => s + x.n, 0);
    return module({
      id: 'draft-arch', span: 12, kicker: `英雄和 BP · 打法类型 · ${sideLabel()}`, meta: `${total} 个分路类型样本`,
      title: '五路各拿什么类型，哪里在轮换',
      body: `<div class="xw-arch"><div class="xw-arch-grid" role="list" aria-label="五路英雄类型分布">${body}</div></div>`,
      note: '每路先看主玩类型和占比，下面保留完整类型清单；占比只按已识别类型的出场计算。',
    });
  }

  function compModule(dp) {
    const list = frontCompStats(dp.rows);
    if (!list.length) return module({ id: 'draft-comp', span: 5, kicker: '英雄和 BP · 体系', title: '没有可读的体系', body: emptyVector('阵容里缺少可识别的英雄。') });
    const covered = list.reduce((sum, x) => sum + x.games, 0);
    return module({
      id: 'draft-comp', span: 5, kicker: `英雄和 BP · 体系 · ${sideLabel()}`, meta: `${list.length} 档 · ${covered} 局`,
      body: `<div class="xw-comps">${list.map((x) => `<div class="xw-comp" tabindex="0">
        <div class="xw-comp-top"><b>${esc(x.tag)}</b><span class="xw-comp-num">${x.games}<em>局</em></span><span class="xw-comp-rate">${rateOf(x.rate) === null ? '—' : `${rateOf(x.rate)}%`}</span></div>
        <p class="xw-comp-gloss">${esc(COMP_GLOSS[x.tag] || '按阵容前排数量判定')}</p>
      </div>`).join('')}</div>`,
    });
  }

  function heroPoolModule(dp) {
    const list = dp.draft.heroes;
    if (!list.length) return module({ id: 'draft-pool', span: 7, kicker: '英雄和 BP · 英雄池', title: '没有可读的英雄池', body: emptyVector('十人面板缺少英雄。') });
    const total = dp.total;
    const tiles = list.slice(0, 18).map((x) => `<button type="button" class="xw-hero" data-xw-pick="${esc(x.hero)}" title="${esc(`${x.hero}：${x.games} 局，胜率 ${rateOf(x.rate) === null ? '—' : `${rateOf(x.rate)}%`}`)}">
      <span class="xw-face">${portrait(x.hero, 'xw-face-img')}</span>
      <b>${esc(x.hero)}</b>
      <small>${x.games} 局 · <em>${rateOf(x.rate) === null ? '—' : `${rateOf(x.rate)}%`}</em></small>
    </button>`).join('');
    return module({
      id: 'draft-pool', span: 7, kicker: `英雄和 BP · 英雄池 · ${sideLabel()}`, meta: `${list.length} 个英雄 · ${total} 局`,
      title: `${meWord}拿得最多的是谁`,
      body: `<div class="xw-pool">${tiles}</div>`,
    });
  }

  /* 组合池命中：直接从逐局英雄里找池子里的双人组合，不再受自动组合
     3 局门槛限制；样本少也列出来，但打「样本少」标签，不硬下结论。 */
  function poolPairStats(rows, poolKeys) {
    const map = new Map();
    for (const r of rows || []) {
      const hs = [...new Set(r.heroes || [])].filter(Boolean).slice(0, 5);
      if (hs.length < 2) continue;
      const seen = new Set();
      for (let i = 0; i < hs.length; i += 1) {
        for (let j = i + 1; j < hs.length; j += 1) {
          const key = [hs[i], hs[j]].sort().join('|');
          if (!poolKeys.has(key) || seen.has(key)) continue;
          seen.add(key);
          const e = map.get(key) || { heroes: [hs[i], hs[j]], games: 0, wins: 0, decided: 0, keys: [] };
          e.games += 1;
          e.keys.push(r.key);
          if (r.result === 'win') e.wins += 1;
          if (r.decided) e.decided += 1;
          map.set(key, e);
        }
      }
    }
    const decided = (rows || []).filter((r) => r.decided);
    return [...map.values()].map((e) => {
      const keys = new Set(e.keys);
      const rest = decided.filter((r) => !keys.has(r.key));
      const restRate = rest.length ? rest.filter((r) => r.result === 'win').length / rest.length : null;
      const rate = e.decided ? e.wins / e.decided : null;
      return {
        heroes: e.heroes, label: e.heroes.join(' + '), n: e.decided, games: e.games,
        wins: e.wins, rate: rate === null ? null : { value: rate },
        lift: rate !== null && restRate !== null ? rate - restRate : null,
      };
    }).sort((a, b) => b.n - a.n || (b.rate?.value || 0) - (a.rate?.value || 0));
  }

  function pairModule(dp) {
    /* 双人组合只认赛训组组合池：命中池子里的组合才列出；
       池子为空或这批局一个都没命中，直接写「无命中组合池」。 */
    const poolDoc = state.comboPool && !state.comboPool.builtin ? state.comboPool : null;
    const poolPairs = (poolDoc?.pairs || []).filter((row) => Array.isArray(row.heroes) && row.heroes.length === 2);
    const poolCount = poolPairs.length;
    const poolKeys = new Set(poolPairs.map((row) => [...new Set(row.heroes)].sort().join('|')));
    const hits = poolPairStats(dp.rows, poolKeys);
    const row = (x) => {
      const thin = x.n < 3;
      const tone = thin ? 'thin' : (num(x.lift) && x.lift < 0 ? 'bad' : 'good');
      return `<div class="xw-pair is-${tone}">
        <span class="xw-pair-faces">${x.heroes.map((h) => portrait(h, 'xw-face-img')).join('<i>+</i>')}</span>
        <span class="xw-pair-copy"><b title="${esc(x.label)}">${esc(x.label)}</b><small>${x.wins} 胜 ${x.n - x.wins} 负 · ${x.n} 局 · 胜率 ${rateNum(x.rate?.value)}%${!thin && num(x.lift) ? ` · ${x.lift >= 0 ? '+' : '−'}${Math.abs(Math.round(x.lift * 100))}%` : ''}</small></span>
        <em class="xw-pair-tag">${thin ? '样本少' : tone === 'good' ? '更好打' : '更吃力'}</em>
      </div>`;
    };
    if (!hits.length) {
      return module({
        id: 'draft-pair', span: 5, kicker: `英雄和 BP · 双人组合 · ${sideLabel()}`, meta: `组合池 ${poolCount} 组`,
        title: '无命中组合池',
        body: emptyVector(poolCount
          ? `这批 ${dp.total} 局里没有出现组合池中的双人组合。`
          : '组合池还没有保存双人组合。'),
      });
    }
    return module({
      id: 'draft-pair', span: 5, kicker: `英雄和 BP · 双人组合 · ${sideLabel()}`, meta: `组合池 ${poolCount} 组`,
      title: `组合池命中 ${hits.length} 组`,
      body: `<div class="xw-pairs">${hits.slice(0, 10).map(row).join('')}</div>`,
    });
  }

  /* 对面视角：我们打红，对面就是蓝；对面赢 = 我们输。
     红蓝方卡只回答两件事：对面站蓝/红的胜率，以及站这一边后输了几次。 */
  const opponentSideOf = (row) => (row.camp === 'blue' ? 'red' : 'blue');
  const pctOf = (wins, n) => (n ? Math.round((wins / n) * 100) : null);

  function opponentSideStats(rows) {
    return ['blue', 'red'].map((side) => {
      const list = (rows || []).filter((r) => r.decided && opponentSideOf(r) === side);
      const wins = list.filter((r) => r.result === 'loss').length;
      return { side, n: list.length, wins, losses: list.length - wins, rate: pctOf(wins, list.length) };
    });
  }

  function sidesModule(dp) {
    const stats = opponentSideStats(dp.rows);
    const total = stats.reduce((n, s) => n + s.n, 0);
    const sideRows = stats.map((s) => `<div class="xw-side is-${s.side}">
      <span>${s.side === 'blue' ? '对面蓝方' : '对面红方'}</span>
      <em>${s.rate === null ? '—' : `${s.rate}%`}</em>
      <small>${s.n} 场 · 输 ${s.losses} 次</small>
    </div>`).join('');
    return module({
      id: 'draft-sides', span: 12, kicker: '英雄和 BP · 红蓝方', meta: `${total} 局 · 对面视角`,
      title: state.bpOpp ? `对 ${esc(state.bpOpp)}：对面站红蓝方的胜率` : '对面站红蓝方的胜率',
      body: `<div class="xw-sides is-opponent">${sideRows}</div>`,
      note: '胜率按对面视角统计；失败次数是对方选到该阵营后输掉的局数。',
    });
  }

  /* 楼层分析：只看对面。
     英雄视图按对方 pick 顺序拆楼层；组合视图与楼层按钮解耦，只按红蓝方取数，
     在对面 5 个 pick 位里找组合池命中（可跨楼层、可同楼层），并标注每一手的位置。 */
  function floorRows(rows, side, floor) {
    return (rows || []).filter((r) => {
      if (!r.decided || opponentSideOf(r) !== side) return false;
      const hs = r.heroesFoe || [];
      return floor.slots.every((i) => hs[i]);
    });
  }

  function floorHeroes(rows, side, floor) {
    const map = new Map();
    for (const r of floorRows(rows, side, floor)) {
      const heroes = [...new Set(floor.slots.map((i) => r.heroesFoe[i]).filter(Boolean))];
      for (const hero of heroes) {
        const e = map.get(hero) || { hero, games: 0, wins: 0 };
        e.games += 1;
        if (r.result === 'loss') e.wins += 1;
        map.set(hero, e);
      }
    }
    return [...map.values()]
      .map((e) => ({ ...e, rate: pctOf(e.wins, e.games) }))
      .sort((a, b) => b.games - a.games || String(a.hero).localeCompare(String(b.hero), 'zh-CN'));
  }

  /* 组合池名单：内置名单来自赛训组提供的「全英雄组合.xlsx」，
     自定义名单会整体覆盖它；两种都按名单判定命中。 */
  function floorPoolKeys() {
    const poolDoc = state.comboPool || null;
    const pairs = (poolDoc?.pairs || []).filter((row) => Array.isArray(row.heroes) && row.heroes.length === 2);
    const keys = new Map();
    for (const row of pairs) {
      const heroes = [...new Set(row.heroes)];
      if (heroes.length !== 2) continue;
      /* 名单顺序固定展示顺序，楼层按这个顺序标注，不随局内 pick 先后颠倒。 */
      keys.set(heroes.slice().sort().join('|'), heroes);
    }
    return { pairs, keys };
  }

  /* 组合视图：从对面 5 手里找池子里的双人组合，记录每个组合落在哪两手。
     fi/fj 是名单里第 1 / 第 2 个英雄在 heroesFoe 里的下标。 */
  function floorPoolCombos(rows, side, pool) {
    const games = (rows || []).filter((r) => r.decided && opponentSideOf(r) === side);
    const map = new Map();
    for (const r of games) {
      const hs = r.heroesFoe || [];
      const seen = new Set();
      for (let i = 0; i < hs.length; i += 1) {
        for (let j = i + 1; j < hs.length; j += 1) {
          if (!hs[i] || !hs[j]) continue;
          const key = [hs[i], hs[j]].sort().join('|');
          const heroes = pool.keys.get(key);
          if (!heroes || seen.has(key)) continue;
          seen.add(key);
          const e = map.get(key) || { heroes, games: 0, wins: 0, patterns: new Map() };
          e.games += 1;
          if (r.result === 'loss') e.wins += 1;
          const fi = heroes[0] === hs[i] ? i : j;
          const fj = heroes[1] === hs[j] ? j : i;
          const pk = `${fi}-${fj}`;
          const p = e.patterns.get(pk) || { fi, fj, n: 0 };
          p.n += 1;
          e.patterns.set(pk, p);
          map.set(key, e);
        }
      }
    }
    return [...map.values()]
      .map((e) => ({
        ...e, label: e.heroes.join(' + '), rate: pctOf(e.wins, e.games),
        floors: [...e.patterns.values()].sort((a, b) => b.n - a.n || a.fi - b.fi),
      }))
      .sort((a, b) => b.games - a.games || a.label.localeCompare(b.label, 'zh-CN'));
  }

  function floorModule(dp) {
    const side = state.floorSide === 'red' ? 'red' : 'blue';
    const floors = FLOOR_SETS[side];
    const floor = floors.find((x) => x.key === state.floorSlot) || floors[0];
    const mode = state.floorMode === 'combo' ? 'combo' : 'hero';
    const rows = dp.rows || [];
    const pool = floorPoolKeys();
    /* 组合视图不跟楼层联动：只按红蓝方取数，在对面 5 手里找组合池命中。 */
    const games = mode === 'combo'
      ? rows.filter((r) => r.decided && opponentSideOf(r) === side)
      : floorRows(rows, side, floor);
    const wins = games.filter((r) => r.result === 'loss').length;
    const rate = pctOf(wins, games.length);
    const items = mode === 'combo' ? floorPoolCombos(rows, side, pool) : floorHeroes(rows, side, floor);
    const bans = (dp.draft.bansFoe || []).slice(0, 8);
    const banList = bans.length
      ? `<div class="xw-ban-chips">${bans.map((b) => `<span class="xw-ban-chip" title="${esc(`对面 ban ${b.hero} ${b.games} 次`)}">
          <span class="xw-face">${portrait(b.hero, 'xw-face-img')}</span><b>${esc(b.hero)}</b><em>${b.games}</em></span>`).join('')}</div>`
      : '<p class="xw-muted">没有可拆分的对面 ban。</p>';
    const sideBtns = ['blue', 'red'].map((key) => `<button type="button" class="xw-segbtn${side === key ? ' is-on' : ''}" data-xw-floor-side="${key}">${key === 'blue' ? '蓝方' : '红方'}</button>`).join('');
    /* 组合视图里楼层按钮不参与，直接不渲染，避免看起来像还能联动。 */
    const floorBtns = mode === 'hero'
      ? `<div class="xw-seg">${floors.map((x) => `<button type="button" class="xw-segbtn${floor.key === x.key ? ' is-on' : ''}" data-xw-floor="${esc(x.key)}">${esc(x.label)}</button>`).join('')}</div>`
      : '';
    const comboBtn = `<div class="xw-floor-mode"><div class="xw-seg"><button type="button" class="xw-segbtn${mode === 'combo' ? ' is-on' : ''}" data-xw-floor-combo aria-pressed="${mode === 'combo'}">组合显示</button></div></div>`;
    const resultText = (x) => `${x.games} 次 · 胜率 ${x.rate === null || x.rate === undefined ? '—' : `${x.rate}%`}`;
    const comboCard = (x) => `<div class="xw-floor-combo-card">
      <div class="xw-floor-combo-head">
        <span class="xw-face-pair">${x.heroes.map((hero) => `<span class="xw-face">${portrait(hero, 'xw-face-img')}</span>`).join('<i>+</i>')}</span>
        <span class="xw-floor-copy"><b title="${esc(x.label)}">${esc(x.label)}</b><small>${resultText(x)}</small></span>
      </div>
      <div class="xw-floor-combo-slots">${x.floors.map((p) => `<span><em>${p.fi + 1}L</em> ${esc(x.heroes[0])} · <em>${p.fj + 1}L</em> ${esc(x.heroes[1])}<i>×${p.n}</i></span>`).join('')}</div>
    </div>`;
    const list = items.length
      ? `<div class="xw-floor-list${mode === 'combo' ? ' is-combo' : ''}">${items.slice(0, 12).map((x) => mode === 'combo'
        ? comboCard(x)
        : `<div class="xw-floor-item"><span class="xw-face">${portrait(x.hero, 'xw-face-img')}</span>
            <span class="xw-floor-copy"><b>${esc(x.hero)}</b><small>${resultText(x)}</small></span></div>`).join('')}</div>`
      : `<p class="xw-muted">${mode === 'combo'
        ? (pool.keys.size ? '这批局对面 5 手里没有出现组合池中的双人组合。' : '组合池还没有保存双人组合。')
        : '这个楼层还没有可统计的对面选人。'}</p>`;
    return module({
      id: 'draft-floor', span: 12, kicker: '英雄和 BP · 楼层分析', meta: `${rows.filter((r) => r.decided).length} 局 · 只看对面`,
      title: mode === 'combo'
        ? `${side === 'blue' ? '对面蓝方' : '对面红方'} 5 手里拿了什么组合`
        : `${side === 'blue' ? '对面蓝方' : '对面红方'}每一楼拿什么`,
      body: `<div class="xw-floor-bans"><div class="xw-block-head"><b>对面常搬</b><span>次数</span></div>${banList}</div>
        <div class="xw-floor-controls">
          <div class="xw-seg">${sideBtns}</div>
          ${floorBtns}
          ${comboBtn}
        </div>
        <div class="xw-floor-summary"><b>${side === 'blue' ? '对面蓝方' : '对面红方'}</b><span>${mode === 'combo' ? '5 手' : esc(floor.label)}</span><span>${games.length} 局</span><span>对面胜率 ${rate === null ? '—' : `${rate}%`}</span><span>${items.length} ${mode === 'combo' ? '种组合' : '个英雄'}</span></div>
        ${list}`,
    });
  }

  function bpTargetModule(dp, opponents) {
    const d = dp.draft;
    const mode = state.bpMode === 'pair' ? 'pair' : 'against';
    const pool = mode === 'pair' ? d.heroesFoe : d.heroes;
    /* 赛训组 2026-11-19：去掉「组合英雄（可选）」第二个下拉；
       直接把主英雄选择器改成 1–4 个多选，选 2 个以上就是组合。 */
    /* 首次进入对位台时默认选第一个英雄；用户点「清空」后保持空，
       这样多选组合不会又偷偷把默认英雄加回来。 */
    if (!state.bpInit && pool.length) {
      state.bpInit = true;
      if (!state.bpHeroes.length) state.bpHeroes = [pool[0].hero];
    }
    const pickedHeroes = (state.bpHeroes || []).filter((h) => pool.some((x) => x.hero === h)).slice(0, 4);
    /* 2026-11-20：对位台两个方向都支持 1–4 个多选；选 2 个以上按组合看。 */
    const heroes = pickedHeroes;
    const hero = heroes[0] || '';
    const isCombo = heroes.length > 1;
    /* 标题按实际选中的英雄显示：单选一个就写那一个，多选组合要把全部列出来。
       以前固定只写 heroes[0]，选了「夏侯惇 + 安琪拉」仍写成「打夏侯惇」，
       教练会以为下面只统计了夏侯惇一个。 */
    const heroLabel = heroes.length > 1 ? heroes.join(' + ') : hero;
    /* 应对英雄若克制我们选中的某个英雄（规则中心「英雄克制英雄」a→b），
       在行尾标「克制X」。方向：a=攻方(应对英雄)，b=受方(我们选的英雄)。 */
    const counterTag = (foeHero) => {
      const pairs = state.counterRules?.heroPairs || [];
      const beaten = [...new Set(pairs
        .filter((row) => row?.a === foeHero && heroes.includes(row.b))
        .map((row) => row.b))];
      /* 始终占住这一格，没有克制关系就留空，让各行的局数/胜率对齐。 */
      if (!beaten.length) return '<span class="xw-ct-cell" aria-hidden="true"></span>';
      return `<span class="xw-ct-cell"><span class="xw-ct-tag" title="规则中心克制关系：${esc(foeHero)} 克制 ${esc(beaten.join('、'))}">克制${beaten.map((h) => esc(h)).join('、')}</span></span>`;
    };
    const modes = [['against', '我们拿英雄 / 组合'], ['pair', '对手拿英雄 / 组合']].map(([key, label]) =>
      `<button type="button" class="xw-segbtn${mode === key ? ' is-on' : ''}" data-xw-mode="${key}">${esc(label)}</button>`).join('');
    const chips = pool.slice(0, 10).map((x) => `<button type="button" class="xw-chip${heroes.includes(x.hero) ? ' is-on' : ''}" data-xw-pick="${esc(x.hero)}">${esc(x.hero)} <b>${x.games}</b></button>`).join('');
    /* 英雄选择器：133 个英雄塞进原生 select 根本没法用，改成可搜索的弹层。
       对位台支持 1–4 个英雄，选满 4 个后其余选项禁用。 */
    const pickerOpen = state.picker === 'hero';
    const btnFaces = heroes.map((h) => `<span class="xw-face is-sm">${portrait(h, 'xw-face-img')}</span>`).join('');
    const btnNames = heroes.map((h) => `<b>${esc(h)}</b>`).join('<i class="xw-picker-plus">+</i>');
    const pickerHtml = `<div class="xw-picker${pickerOpen ? ' is-open' : ''}">
      <span class="xw-picker-label">英雄 / 组合</span>
      <button type="button" class="xw-picker-btn" data-xw-picker="hero" aria-expanded="${pickerOpen ? 'true' : 'false'}">
        ${glyph('heroes', { label: '选英雄', size: 18 })}${heroes.length ? `${btnFaces}<span class="xw-picker-names">${btnNames}</span>` : '<b>选英雄</b>'}
        <i aria-hidden="true">▾</i>
      </button>
      ${pickerOpen ? `<div class="xw-picker-pop">
        <input type="search" class="xw-picker-search" data-xw-search="hero" placeholder="搜英雄名（可多选 2–4 个）" value="${esc(state.heroQuery)}" aria-label="搜索英雄">
        <div class="xw-picker-grid">
          ${pool.map((x) => {
            const on = heroes.includes(x.hero);
            const full = !on && heroes.length >= 4;
            return `<button type="button" class="xw-picker-opt${on ? ' is-on' : ''}" data-xw-combo="${esc(x.hero)}"${full ? ' disabled' : ''}>
              <span class="xw-face is-sm">${portrait(x.hero, 'xw-face-img')}</span><b>${esc(x.hero)}</b><em>${x.games}</em>
              ${on ? '<i class="xw-pick-check" aria-hidden="true">✓</i>' : ''}
            </button>`;
          }).join('')}
        </div>
        <div class="xw-picker-foot">
          <button type="button" class="xw-clear control" data-xw-combo-clear>${glyph('trash', { label: '清空', size: 18 })} 清空</button>
          <button type="button" class="xw-clear control" data-xw-picker="">${glyph('ban', { label: '关闭', size: 18 })} 关闭</button>
        </div>
      </div>` : ''}
    </div>`;
    const controls = `<div class="xw-bp-controls">
      <div class="xw-seg">${modes}</div>
      ${pickerHtml}
    </div>
    <div class="xw-chips">${chips}</div>`;
    let body = emptyVector(hero ? '当前范围里没有这组英雄的记录。' : '还没有选择英雄。');
    if (mode === 'against' && hero) {
      const t = dp.bp.target(heroes);
      if (t && (t.games || t.ban.games)) {
        const maxBan = Math.max(1, ...t.ban.byTurn);
        const turns = t.ban.byTurn.map((n, i) => `<div class="xw-turn${n === maxBan && n ? ' is-top' : ''}">
          <span>第 ${i + 1} 手</span><b>${n}</b><i style="height:${(n / maxBan * 64).toFixed(1)}px"></i>
        </div>`).join('');
        /* 赛训组反馈：应对清单不显示英雄名，直接用放大的头像；头像后面
           挂「克制X」标。名字保留在 title / alt 里，读屏和悬停仍能读到。 */
        const responses = t.responses.length ? `<div class="xw-bp-list">${t.responses.map((x) => `<div class="xw-bp-row is-portrait">
          <span class="xw-face is-hero" title="${esc(x.hero)}">${portrait(x.hero, 'xw-face-img')}</span>
          ${counterTag(x.hero)}
          <span>${x.games} 局</span>
          <em>${themWord}赢 ${x.foeWins}${x.games ? `（${Math.round(x.foeWins / x.games * 100)}%）` : ''}</em>
        </div>`).join('')}</div>` : `<p class="xw-muted">没有可对照的同位置对手。</p>`;
        const combos = t.combos.length ? `<div class="xw-bp-list">${t.combos.map((x) => `<div class="xw-bp-row is-portrait">
          <span class="xw-face-pair is-hero" title="${esc(x.heroes.join(' + '))}">${x.heroes.map((h) => portrait(h, 'xw-face-img')).join('')}</span>
          <span class="xw-ct-cell" aria-hidden="true"></span>
          <span>${x.games} 局</span>
          <em>${themWord}赢 ${x.foeWins}${x.games ? `（${Math.round(x.foeWins / x.games * 100)}%）` : ''}</em>
        </div>`).join('')}</div>` : '';
        const byOpp = t.byOpponent.length ? `<div class="xw-bp-list">${t.byOpponent.map((x) => `<div class="xw-bp-row is-opp">
          <b>${esc(x.name)}</b>
          <span>${x.games} 局 · ${x.wins} 胜</span>
          <div class="xw-bp-mini-list">${x.responses.length
            ? x.responses.map((r) => `<span class="xw-bp-mini"><span class="xw-face is-xs">${portrait(r.hero, 'xw-face-img')}</span>${esc(r.hero)}×${r.games}</span>`).join('')
            : '<span class="xw-bp-mini is-empty">无对照</span>'}</div>
        </div>`).join('')}</div>` : '';
        body = `<div class="xw-bp-hero">
            <div class="xw-bp-hero-id">
              <span class="xw-face is-lg">${t.want.map((h) => portrait(h, 'xw-face-img')).join('')}</span>
              <div><h4>${esc(t.want.join(' + '))}</h4><p>${meWord}拿了 <b>${t.games}</b> 局，<b>${t.wins}</b> 胜${num(t.rate.value) ? `（${Math.round(t.rate.value * 100)}%）` : ''}</p></div>
            </div>
            <div class="xw-bp-banline">
              <span>${themWord} ban 它 <b>${t.ban.games}</b> 次</span>
              <span>${meWord} ban 它 <b>${t.banOwn.games}</b> 次</span>
            </div>
          </div>
          <div class="xw-subblock"><div class="xw-block-head"><b>对手第几手 ban 它</b><span>按对方自己的 ban 顺序</span></div>${
            t.ban.games
              ? `<div class="xw-turns">${turns}</div>`
              : `<p class="xw-muted">${themWord}一次都没 ban 过${esc(heroLabel)}，不用看顺序。</p>`}</div>
          <div class="xw-two-col is-bp">
            <div class="xw-subblock"><div class="xw-block-head"><b>没 ban 时，${themWord}拿什么打${esc(heroLabel)}</b><span>同位置</span></div>${responses}</div>
            <div class="xw-subblock"><div class="xw-block-head"><b>各队怎么应对</b><span>${opponents.length} 个对手</span></div>${byOpp || emptyVector('没有分队伍样本。')}</div>
          </div>
          ${combos ? `<div class="xw-subblock is-bp-combos"><div class="xw-block-head"><b>${meWord}拿它时，${themWord}整条阵容的常见组合</b><span>对方英雄</span></div>${combos}</div>` : ''}`;
      }
    } else if (mode === 'pair' && hero) {
      const p = dp.bp.pairing(heroes);
      if (p && p.games) {
        const pickWord = p.isCombo ? '这套组合' : '这个英雄';
        const parts = p.partners.length ? `<div class="xw-bp-list">${p.partners.map((x) => `<div class="xw-bp-row">
          <span class="xw-face is-sm">${portrait(x.hero, 'xw-face-img')}</span>
          <b>${esc(x.hero)}</b>
          <span>${x.games} 局</span>
          <em>${themWord}赢 ${x.foeWins}${x.games ? `（${Math.round(x.foeWins / x.games * 100)}%）` : ''}</em>
        </div>`).join('')}</div>` : `<p class="xw-muted">没有搭档样本。</p>`;
        /* 这组行只有 3 个孩子，套 4 栏的 .xw-bp-row 会把搭档名挤进 62px 列，
           折成「宫本武 / 藏×1」那种竖排。复用已有的 is-opp 两栏 + mini-list：
           队名与局数一行，搭档名横向换行，内容不变、只是不再被挤窄。 */
        const byOpp = p.byOpponent.map((x) => `<div class="xw-bp-row is-opp">
          <b>${esc(x.name)}</b>
          <span>${x.games} 局 · 对方赢 ${Math.round((x.rate.value || 0) * x.games)}</span>
          <div class="xw-bp-mini-list">${x.partners.length
            ? x.partners.map((r) => `<span class="xw-bp-mini"><span class="xw-face is-xs">${portrait(r.hero, 'xw-face-img')}</span>${esc(r.hero)}×${r.games}</span>`).join('')
            : '<span class="xw-bp-mini is-empty">无搭档</span>'}</div>
        </div>`).join('');
        body = `<div class="xw-bp-hero">
            <div class="xw-bp-hero-id">
              <span class="xw-face is-lg">${p.heroes.map((h) => portrait(h, 'xw-face-img')).join('')}</span>
              <div><h4>${themWord}拿 ${p.heroes.map((h) => esc(h)).join(' + ')}</h4><p>出现 <b>${p.games}</b> 局，${themWord}赢 <b>${p.foeWins}</b></p></div>
            </div>
            <div class="xw-bp-banline"><span>${meWord} ban ${p.isCombo ? '掉其中英雄' : '它'} <b>${p.ban.games}</b> ${p.isCombo ? '局' : '次'}</span></div>
          </div>
          <div class="xw-two-col is-bp">
            <div class="xw-subblock"><div class="xw-block-head"><b>${pickWord}还常跟谁一起出</b><span>${p.isCombo ? '对方的第 3/4 个英雄' : '对方的搭档'}</span></div>${parts}</div>
            <div class="xw-subblock"><div class="xw-block-head"><b>各队怎么配${pickWord}</b><span>按对手分</span></div><div class="xw-bp-list">${byOpp}</div></div>
          </div>`;
      }
    }
    return module({
      id: 'draft-bp', span: 12, kicker: '英雄和 BP · 对位台', meta: `${dp.total} 局`,
      title: mode === 'pair'
        ? (isCombo ? `${themWord}拿出 ${heroes.map((h) => esc(h)).join(' + ')} 时，谁跟它搭` : `${themWord}拿这个英雄时，谁跟它搭`)
        : (!hero ? '先选 1–4 个英雄，看对手怎么应对'
          : (isCombo ? `${meWord}拿 ${heroes.map((h) => esc(h)).join(' + ')} 这几个时，${themWord}怎么应对` : `${meWord}拿这个英雄时，${themWord}怎么应对`)),
      body: `${controls}${body}`,
      note: mode === 'pair' ? '所选英雄同时在对方阵容出现时，同一方还常拿谁；选 2–4 个即按组合看。' : 'ban 顺序按对方自己那一侧的 ban 列表；「没 ban 时拿什么打」取这套组合里第一个英雄所在分路的对手；「克制X」标只取规则中心维护过的英雄克制关系。',
    });
  }

  function draftCards(dp, opponents) {
    if (!dp || !dp.total) return module({ id: 'draft-empty', span: 12, kicker: '英雄和 BP', title: '没有可用的英雄 / BP 数据', body: emptyVector('先补齐十人面板或 BP 名单。') });
    return `${archetypeModule(dp)}${compModule(dp)}${heroPoolModule(dp)}${pairModule(dp)}${sidesModule(dp)}${floorModule(dp)}${bpTargetModule(dp, opponents)}`;
  }

  /* ── 页面 ───────────────────────────────────────────────────── */
  function listHtml() {
    syncWords();
    if (state.error) return `<div class="page xw-page"><section class="xw-blank">${glyph('warning', { label: '读取失败', size: 28 })}<h1>读不到跨局数据</h1><p>${esc(state.error)}</p><button type="button" class="xw-btn primary control" data-cx-retry>${glyph('refresh', { label: '重试', size: 18 })} 重试</button></section></div>`;
    if (!state.allSeries.length) {
      return `<div class="page xw-page"><section class="xw-blank">${glyph('bp', { label: '系列赛编组', size: 28 })}<h1>还没有已确认的系列赛</h1><p>先到系列赛编组确认 BO3/5/7。</p><a class="xw-btn primary control" href="#series-builder">${glyph('bp', { label: '去编组', size: 18 })} 去系列赛编组</a></section></div>`;
    }
    const series = filteredSeries();
    if (!series.length) {
      return `<div class="page xw-page">${scopeBarHtml(null)}<section class="xw-blank">${glyph('refresh', { label: '清除筛选', size: 28 })}<h1>当前范围没有系列赛</h1><button type="button" class="xw-btn primary control" data-cx-clear>${glyph('refresh', { label: '清除筛选', size: 18 })} 清除筛选</button></section></div>`;
    }
    const sum = deriveSummary(series);
    const vectors = vectorSide(selectedVectors(series));
    const a = analyzeCohort(vectors);
    const prev = prevCohort();
    /* BP 分区自带对手选择：选了对手就只在这一批局里算 BP，不影响赛中/赛后。 */
    const opponents = uniq('opponent');
    const bpVectors = state.bpOpp ? vectors.filter((v) => String(v.opponent || '').trim() === state.bpOpp) : vectors;
    const dp = state.bpOpp ? analyzeCohort(bpVectors) : a;
    const sideWord = state.side === 'foe' ? '敌方' : '我方';
    const meta = {
      ingame: `${sideWord} · ${a.total} 局有过程`,
      postgame: `${sideWord} · ${a.total} 局有面板`,
      draft: `${state.bpOpp || '全部对手'} · ${dp.total} 局`,
    };
    return `<div class="page xw-page">
      ${headHtml(sum, series)}
      ${scopeBarHtml(sum)}
      <section class="xw-section" id="xw-sec-ingame" data-cx-section="ingame"${state.section === 'ingame' ? '' : ' hidden'}>
        ${sectionHead('ingame', meta.ingame)}
        ${state.vectorsError ? '<div class="xw-section-note">各局向量没取到，赛中分析暂不可用。</div>' : ''}
        ${ingameStatement(a)}
        <div class="xw-grid">${ingameCards(a, prev)}</div>
      </section>
      <section class="xw-section" id="xw-sec-postgame" data-cx-section="postgame"${state.section === 'postgame' ? '' : ' hidden'}>
        ${sectionHead('postgame', meta.postgame)}
        ${state.vectorsError ? '<div class="xw-section-note">各局向量没取到，赛后分析暂不可用。</div>' : ''}
        ${postgameStatement(a)}
        <div class="xw-grid">${postgameCards(a, prev)}</div>
      </section>
      <section class="xw-section" id="xw-sec-draft" data-cx-section="draft"${state.section === 'draft' ? '' : ' hidden'}>
        ${sectionHead('draft', '', draftTools(opponents))}
        ${state.vectorsError ? '<div class="xw-section-note">各局向量没取到，英雄和 BP 暂不可用。</div>' : ''}
        <div class="xw-grid">${draftCards(dp, opponents)}</div>
      </section>
    </div>`;
  }
  /* ── 单场大场分析 ─────────────────────────────────────────── */
  function detailChart(games) {
    const rows = games.filter((g) => num(g.at10) || num(g.finalDiff));
    if (rows.length < 2) return '<p class="xc-muted">过程数据不足，画不出逐局走势。</p>';
    const H = 190, W = 1000;
    const vals = rows.flatMap((g) => [g.at10, g.finalDiff]).filter(num);
    const max = Math.max(1000, ...vals.map((v) => Math.abs(v)));
    const xOf = (i) => 30 + (i / Math.max(1, rows.length - 1)) * 940;
    const yOf = (v) => H / 2 - (v / max) * (H / 2 - 24);
    const line = (key, cls) => {
      const d = rows.map((g, i) => (num(g[key]) ? `${i ? 'L' : 'M'}${xOf(i).toFixed(1)},${yOf(g[key]).toFixed(1)}` : '')).filter(Boolean).join(' ');
      return d ? `<path class="line ${cls}" d="${d}" stroke-width="2.2" fill="none" vector-effect="non-scaling-stroke"/>` : '';
    };
    const dots = rows.map((g, i) => {
      if (!num(g.at10)) return '';
      return `<a class="xv-dot ${g.result === 'win' ? 'win' : g.result === 'loss' ? 'loss' : 'na'}" style="left:${(xOf(i) / W * 100).toFixed(2)}%;top:${(yOf(g.at10) / H * 100).toFixed(2)}%" href="#match/${encodeURIComponent(g.matchKey)}" title="G${g.gameIndex} · 10′ ${fmt.signed(g.at10)}"></a>`;
    }).join('');
    return `<div class="xv-chartwrap">
      <div class="xv-chartbox" style="height:${H}px"><svg class="xv-shape" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        ${Array.from({ length: 5 }, (_, i) => `<line class="grid" x1="0" x2="${W}" y1="${H * i / 4}" y2="${H * i / 4}" vector-effect="non-scaling-stroke"/>`).join('')}
        <line class="zero" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>
        ${line('at10', 'winline')}${line('finalDiff', 'roll')}
      </svg><span class="xv-y-lab top">${fmt.signed(max)}</span><span class="xv-y-lab mid">0</span><span class="xv-y-lab bottom">${fmt.signed(-max)}</span>${dots}</div>
      <div class="xv-axis">${rows.map((g) => `<span>G${g.gameIndex}</span>`).join('')}</div>
      <div class="xv-legend"><span><i class="win"></i>10 分钟</span><span><i class="roll"></i>终局</span></div>
    </div>`;
  }

  function miniGames(games) {
    return `<div class="xc-games">${games.map((g) => {
      const res = g.result === 'win' ? 'win' : g.result === 'loss' ? 'loss' : 'na';
      return `<a class="xc-gcard ${res}" href="#match/${encodeURIComponent(g.matchKey)}">
        <b>G${g.gameIndex}</b><span>${res === 'win' ? '胜' : res === 'loss' ? '负' : '—'}</span>
        <small>${num(g.at10) ? `10′ ${fmt.signed(g.at10)}` : '无过程'}</small>
        <small>${fmt.duration(g.duration)}</small>
      </a>`;
    }).join('')}</div>`;
  }

  function verdictText(series, games, score) {
    const us = Number(score?.us) || 0, them = Number(score?.them) || 0;
    const bestOf = Number(series.bestOf) || games.length;
    const results = games.map((g) => g.result).filter((r) => r === 'win' || r === 'loss');
    const full = games.length >= bestOf;
    if (!scoreValid(series)) return `比分 ${us}:${them} 与 BO${bestOf} 赛制不一致，先核实编组/规则集，再谈逆转或零封。`;
    if (series.completionMode === 'fixed') {
      return `固定打满 ${games.length} 局，${us} 胜 ${them} 负。`;
    }
    if (us > them) {
      if (them === 0) return `直落 ${us} 局拿下；没有给对手任何一局。`;
      if (results[0] === 'loss') return `先丢一局，随后连扳 ${us} 局完成逆转。`;
      return `以大场 ${us}:${them} 拿下${full ? '，打满全局数' : ''}。`;
    }
    if (them > us) {
      if (us === 0) return `被直落 ${them} 局；没有拿到一局。`;
      if (results[0] === 'win') return `先赢一局，随后被连扳 ${them} 局。`;
      return `以大场 ${us}:${them} 落败${full ? '，打满全局数' : ''}。`;
    }
    return '系列赛未分胜负，先确认比分或采集完整性。';
  }

  function detailHtml() {
    if (state.detailError) return `<div class="page xc-page"><a class="xc-back" href="#cross${scopeQuery()}">${glyph('home', { label: '返回跨场分析', size: 18 })} 返回跨场分析</a><section class="xc-blank">${glyph('warning', { label: '读取失败', size: 28 })}<h1>读不到这场大场</h1><p>${esc(state.detailError)}</p></section></div>`;
    const data = state.detail;
    if (!data) return `<div class="page xc-page"><div class="loading">正在读取大场明细…</div></div>`;
    const series = data.series || {};
    const games = (data.games || []).slice().sort((a, b) => (Number(a.gameIndex) || 0) - (Number(b.gameIndex) || 0));
    const score = data.score || series.score || { us: 0, them: 0 };
    const us = Number(score.us) || 0, them = Number(score.them) || 0;
    const resultWord = us > them ? '战胜' : us < them ? '不敌' : '对阵';
    const durations = games.map((g) => g.duration).filter(num);
    const at10s = games.map((g) => g.at10).filter(num);
    const verdict = verdictText(series, games, score);
    const rule = series.ruleset?.name || series.rulesetId || '规则集未设置';
    const back = `#cross${scopeQuery()}`;
    const transitions = games.filter((g) => g.gameIndex > 1);
    const adjustments = transitions.map((g) => {
      const adj = g.adjustment || {};
      const resp = (data.opponentResponse || []).find((r) => Number(r.gameIndex) === Number(g.gameIndex)) || {};
      const chips = (arr, cls = '') => (arr || []).map((x) => `<span class="xc-hero-pill ${cls}">${esc(x)}</span>`).join('') || '<span class="xc-muted">无</span>';
      return `<div class="xc-transition">
        <div class="xc-transition-head"><b>G${g.gameIndex - 1} → G${g.gameIndex}</b><span>${esc(adj.changeLabel || '对照缺失')}</span></div>
        <div class="xc-transition-grid">
          <div><small>我方新增</small><div class="xc-hero-chips">${chips(adj.newOwn, 'new')}</div></div>
          <div><small>我方移出</small><div class="xc-hero-chips">${chips(adj.droppedOwn, 'out')}</div></div>
          <div><small>对方新增</small><div class="xc-hero-chips">${chips(resp.newFoe, 'new')}</div></div>
          <div><small>对方移出</small><div class="xc-hero-chips">${chips(resp.droppedFoe, 'out')}</div></div>
        </div>
        <p class="xc-muted">${adj.compChanged ? '我方体系标签变化；' : ''}${resp.compChanged ? '对方体系标签变化；' : ''}${(resp.banRepeat || []).length ? `对方重复 ban：${esc(resp.banRepeat.join('、'))}` : ''}${!adj.compChanged && !resp.compChanged && !(resp.banRepeat || []).length ? '没有观察到明显的体系/ban 调整。' : ''}</p>
      </div>`;
    }).join('');
    const ledgerRows = games.map((g) => {
      const bp = (data.bpLedger?.perGame || []).find((x) => Number(x.gameIndex) === Number(g.gameIndex)) || {};
      const newOwn = (g.adjustment || {}).newOwn || [];
      return `<tr><td class="num">G${g.gameIndex}</td><td class="num">${fmt.count(bp.usedUsCount)}</td><td class="num">${fmt.count(bp.usedFoeCount)}</td><td>${esc(newOwn.join('、') || '—')}</td><td class="num">${fmt.count((bp.blockUs || []).length)}</td></tr>`;
    }).join('');
    const afterPairs = (data.afterLoss?.pairs || []).map((p) => `<div class="xc-pair-card">
      <b>G${p.fromGame} → G${p.toGame}</b><span class="${p.nextResult === 'win' ? 'win' : 'loss'}">${p.nextResult === 'win' ? '下一局胜' : '下一局负'}</span>
      <small>${num(p.at10Delta) ? `10′ 变化 ${fmt.signed(p.at10Delta)}` : '缺过程数据，不比较经济差'}</small>
    </div>`).join('');
    const responseRows = (data.opponentResponse || []).map((r) => `<tr><td class="num">G${r.gameIndex}</td><td>${esc((r.newFoe || []).join('、') || '—')}</td><td>${esc((r.droppedFoe || []).join('、') || '—')}</td><td>${r.compChanged ? '是' : '否'}</td><td>${esc((r.banRepeat || []).join('、') || '—')}</td></tr>`).join('');
    const caveats = (data.caveats || []).map((c) => `<li>${esc(c)}</li>`).join('');
    const coverage = data.coverage || {};
    return `<div class="page xc-page xc-series-detail">
      <a class="xc-back" href="${back}">${glyph('home', { label: '返回跨场分析', size: 18 })} 返回跨场分析</a>
      <header class="xc-head xc-detail-head">
        <div class="xc-head-main">
          <p class="xc-eyebrow">大场分析 <i>/</i> BO${esc(String(series.bestOf || '—'))} <i>/</i> ${esc(String(series.startAt || games[0]?.date || '—'))} <i>/</i> ${esc(COMPLETION_LABEL[series.completion] || series.completion || '—')}</p>
          <h1 class="xc-title">${scoreValid(series) ? `${us}:${them} ${resultWord}` : `比分 ${us}:${them} 待核实`} ${esc(series.opponent || '对手待补')} <span class="xc-title-ci">${esc(rule)}</span></h1>
          <p class="xc-sub">${games.length} 局 · ${durations.length ? `平均 ${fmt.duration(fmt.mean(durations))}` : '缺时长'} · ${at10s.length ? `10 分钟差 ${fmt.signed(fmt.median(at10s))}` : '缺 10 分钟过程'} · ${series.completionMode === 'fixed' ? '固定打满' : '标准决胜'} · ${scoreValid(series) ? '' : '比分与赛制不一致 · '}${series.status === 'needs_review' ? '编组待核实' : '编组已确认'}</p>
          <div class="xc-coverage"><span class="xc-cov"><b>${fmt.count(games.length)}</b> 小局</span><span class="xc-cov"><b>${fmt.count(coverage.withVector || 0)}</b> 有向量</span><span class="xc-cov"><b>${fmt.count(coverage.orderKnownGames || 0)}</b> 有手序</span><span class="xc-cov"><b>${fmt.count(coverage.at10Games || 0)}</b> 有 10 分钟</span></div>
        </div>
        <div class="xc-head-actions"><a class="xc-btn control" href="#series-builder">${glyph('bp', { label: '去编组中心', size: 18 })} 去编组中心</a></div>
      </header>
      <div class="xc-cards">
        <article class="xc-card xc-span-12">
          <div class="xc-card-head"><span class="xc-kicker">${glyph('chart', { size: 18 })}系列赛结论</span><span class="xc-badge">${games.length} 局</span></div>
          <h3 class="xc-card-title">${esc(verdict)}</h3>
          ${miniGames(games)}
          ${detailChart(games)}
          <p class="xc-card-note">${glyph('warning', { label: '数据口径', size: 16 })} 线是 10 分钟经济差与终局经济差（本队减对手）。</p>
        </article>
        ${card({ id: 'detail-games', span: 12, kicker: '逐局对比', sample: `${games.length} 局`, title: '每一局的结果、经济差与阵容', lede: '调整按终局阵容口径；没有 BP 手序时，不推断先后手针对。', body: `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th>结果</th><th class="num">时长</th><th class="num">10′差</th><th class="num">终局差</th><th>我方体系</th><th>对方体系</th><th>调整</th><th>复盘</th></tr></thead><tbody>${games.map((g) => `<tr><td class="num">G${g.gameIndex}</td><td><b class="${g.result === 'win' ? 'win' : 'loss'}">${g.result === 'win' ? '胜' : g.result === 'loss' ? '负' : '—'}</b></td><td class="num">${fmt.duration(g.duration)}</td><td class="num">${fmt.signed(g.at10)}</td><td class="num">${fmt.signed(g.finalDiff)}</td><td>${esc(g.compOwn || '—')}</td><td>${esc(g.compFoe || '—')}</td><td>${esc(g.adjustment?.changeLabel || '—')}</td><td><a href="#match/${encodeURIComponent(g.matchKey)}">打开 →</a></td></tr>`).join('')}</tbody></table></div>` })}
        ${card({ id: 'detail-adjust', span: 7, kicker: '调整与对手回应', sample: `${transitions.length} 次过渡`, title: transitions.length ? '每一局之间改了什么' : '没有可对照的连续局', lede: '', body: adjustments || '<p class="xc-muted">只有一局，或缺少阵容。</p>', method: '相邻两局对比终局阵容；有手序才谈「针对顺序」，这里不做先后手推断。' })}
        ${card({ id: 'detail-ledger', span: 5, kicker: '全局 BP 消耗', sample: `${ledgerRows ? games.length : 0} 局`, title: esc(rule), lede: '每局累计曾选与我方不可再选；跨局复用按规则集检查。', body: ledgerRows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th class="num">我</th><th class="num">敌</th><th>本局新增</th><th class="num">我方已锁</th></tr></thead><tbody>${ledgerRows}</tbody></table></div><p class="xc-card-note">${esc(series.ruleset?.note || '')}</p>` : '<p class="xc-muted">没有阵容账本。</p>', method: '累计曾选按系列赛推进；规则集以本场设置为准；检测到复用会写在覆盖说明里。' })}
        ${card({ id: 'detail-afterloss', span: 6, kicker: '败局恢复', sample: `${(data.afterLoss?.pairs || []).length} 对`, title: data.afterLoss?.n ? `下一局赢 ${data.afterLoss.nextWins}/${data.afterLoss.n}（${pct100(data.afterLoss.nextWinRate)}）` : '没有输局后的下一局', lede: data.afterLoss?.deltaSamples ? `下一局 10 分钟差常见变化 ${fmt.signed(data.afterLoss.medianAt10Delta)}（${data.afterLoss.deltaSamples} 对）` : '缺过程数据，不比较经济差。', body: `${afterPairs || '<p class="xc-muted">没有可对照的连败过渡。</p>'}${data.compSwitch?.pairs ? `<div class="xc-risk-grid"><div class="xc-risk"><span>体系延续后</span><b>${pct100(data.compSwitch.continued?.winRate)}</b><small>${data.compSwitch.continued?.nextWins || 0}/${data.compSwitch.continued?.n || 0} 次</small></div><div class="xc-risk"><span>体系切换后</span><b>${pct100(data.compSwitch.switched?.winRate)}</b><small>${data.compSwitch.switched?.nextWins || 0}/${data.compSwitch.switched?.n || 0} 次</small></div></div>` : ''}`, note: '调整与下一局胜负是关联，不是因果。' })}
        ${card({ id: 'detail-response', span: 6, kicker: '对手回应', sample: `${(data.opponentResponse || []).length} 次`, title: responseRows ? '对手逐局的新增/移出与禁用' : '没有可读的对手调整', lede: '只有终局名单时，这里显示的是「换人」，不是「第几手针对」。', body: responseRows ? `<div class="xc-table-wrap"><table class="xc-table"><thead><tr><th class="num">局</th><th>新增</th><th>移出</th><th>换体系</th><th>重复 ban</th></tr></thead><tbody>${responseRows}</tbody></table></div>` : '<p class="xc-muted">阵容缺失，无法对照。</p>' })}
        ${card({ id: 'detail-coverage', span: 12, kicker: '覆盖与口径', sample: `${coverage.games || games.length} 局`, title: '这场大场能回答什么、不能回答什么', lede: `向量 ${coverage.withVector || 0} 局 · 明细 ${coverage.withDetail || 0} 局 · 手序 ${coverage.orderKnownGames || 0} 局 · 过程 ${coverage.processKnownGames || 0} 局 · 10 分钟 ${coverage.at10Games || 0} 局`, body: (caveats || !scoreValid(series)) ? `<ul class="xc-caveats-list">${scoreValid(series) ? '' : `<li>比分 ${us}:${them} 与 BO${series.bestOf || '—'} 赛制不一致：先核实编组、赛制或规则集，本页不据此下大场结论。</li>`}${caveats}</ul>` : '<p class="xc-muted">没有额外口径警示。</p>' })}
      </div>
      <p class="xc-source"><b>数据</b> 系列赛编组 + 各局向量/明细；大场结论只在这组 BO 内成立，不跨系列赛外推。</p>
    </div>`;
  }

  function updateSectionNav() {
    if (!isCrossRoute()) return;
    const sections = [...document.querySelectorAll('[data-cx-section]')];
    if (!sections.length) return;
    const marker = window.scrollY + 150;
    let active = sections[0];
    for (const section of sections) {
      if (section.offsetTop <= marker) active = section;
    }
    document.querySelectorAll('[data-cx-section-link]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.cxSectionLink === active.dataset.cxSection);
    });
  }

  function switchViz(id, key) {
    vizViews[id] = key;
    const wrap = [...document.querySelectorAll('[data-xc-viz]')].find((el) => el.dataset.xcViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-xc-view-btn]').forEach((b) => b.classList.toggle('is-on', b.dataset.xcViewBtn === key));
    wrap.querySelectorAll('.xv-view').forEach((v) => {
      const on = v.dataset.xcView === key;
      v.hidden = !on;
    });
  }

  function showVizTip(target, event) {
    const wrap = target.closest('[data-xc-viz]');
    if (!wrap) return;
    const tip = wrap.querySelector('.xv-tip');
    if (!tip) return;
    tip.textContent = target.dataset.xcTip || '';
    tip.hidden = false;
    const box = wrap.querySelector('.xv-stage')?.getBoundingClientRect();
    if (!box) return;
    tip.style.left = `${Math.max(8, Math.min(event.clientX - box.left + 12, Math.max(8, box.width - 260)))}px`;
    tip.style.top = `${Math.max(6, Math.min(event.clientY - box.top - 36, Math.max(6, box.height - 48)))}px`;
  }

  function hideVizTips() {
    document.querySelectorAll('.xv-tip').forEach((t) => { t.hidden = true; });
  }

  /* ── 渲染与事件 ───────────────────────────────────────────── */
  function paint(html) {
    document.dispatchEvent(new CustomEvent('route:repainted'));
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (host) host.innerHTML = html;
    syncStickyTop();
    requestAnimationFrame(() => {
      document.querySelectorAll('[data-cx-section]').forEach((s) => { s.hidden = s.dataset.cxSection !== state.section; });
    });
  }

  /* 吸顶页签要让开顶部导航：量一下固定头部的高度写进 CSS 变量。 */
  function syncStickyTop() {
    const heads = ['.masthead', '.secondary-nav', '.ui-subnav']
      .map((sel) => document.querySelector(sel))
      .filter(Boolean);
    const top = heads.reduce((sum, el) => sum + (el.getBoundingClientRect().height || 0), 0);
    const page = document.querySelector('.xw-page');
    if (page) page.style.setProperty('--xw-sticky-top', `${Math.round(top)}px`);
  }

  /* 加载态：给骨架 + 第几步，别让教练以为卡死了（首次要算向量缓存）。 */
  function paintLoading(text) {
    if (!isCrossRoute()) return;
    const host = document.querySelector('#content');
    if (!host) return;
    host.innerHTML = `<div class="page xw-page xw-loading">
      <div class="xw-skel-head">
        <span class="xw-skel-line is-xs"></span>
        <span class="xw-skel-line is-xl"></span>
        <span class="xw-skel-line is-md"></span>
      </div>
      <div class="xw-skel-grid">
        <i class="xw-skel-card is-wide"></i>
        <i class="xw-skel-card"></i>
        <i class="xw-skel-card"></i>
      </div>
      <p class="xw-loading-text"><span class="xw-spin" aria-hidden="true"></span>${esc(text)}</p>
    </div>`;
  }

  function ensure(force = false) {
    if (!isCrossRoute()) return;
    readScope();
    const legacy = routeParts();
    if (legacy[0] === 'cross' && legacy[1] === 'series' && legacy[2]) {
      location.replace(`#biggame/${encodeURIComponent(decodeURIComponent(legacy[2]))}${scopeQuery()}`);
      return;
    }
    const detailId = detailIdOf();
    if (detailId) {
      // 不因 detailLoading 卡住：过期请求可能不会再回来清理标志。
      if (force || state.detailId !== detailId || !state.detail) loadDetail(detailId);
      else if (state.detail) paint(detailHtml());
      return;
    }
    if (force || !state.loaded) loadAll();
    else paint(listHtml());
  }

  function render() {
    return '<div class="page xw-page" data-cx-root><div class="loading">正在汇总系列赛…</div></div>';
  }

  function bind(node) {
    root = node;
    if (!bind.done) {
      bind.done = true;
      document.addEventListener('click', onClick);
      document.addEventListener('change', onChange);
      document.addEventListener('competition:selected', () => {
        // 赛事域（M1）：切赛事即切分析域——清空语料/明细与页内筛选后重载。
        Object.assign(state, {
          allSeries: [], rulesets: [], latestDate: '', vectors: [], vectorsError: false,
          detailId: '', detail: null, detailError: '',
          side: 'own', bpOpp: '', bpMode: 'against', bpHeroes: [], bpInit: false,
        });
        state.loaded = false;
        loadAll();
      });
      document.addEventListener('input', onInput);
      document.addEventListener('mousemove', (event) => {
        if (!isCrossRoute()) return;
        const tip = event.target.closest ? event.target.closest('[data-xc-tip]') : null;
        if (tip) showVizTip(tip, event); else hideVizTips();
      });
      document.addEventListener('mouseleave', hideVizTips);
      document.addEventListener('keydown', (event) => {
        if (!isCrossRoute() || event.key !== 'Escape') return;
        if (!state.picker) return;
        state.picker = '';
        repaint();
      });
    }
    ensure(true);
  }

  /* 英雄选择器搜索：就地过滤，不重绘（重绘会丢焦点）。 */
  function onInput(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const input = event.target.closest('[data-xw-search]');
    if (!input) return;
    const q = String(input.value || '').trim();
    state.heroQuery = q;
    const pop = input.closest('.xw-picker-pop');
    if (!pop) return;
    pop.querySelectorAll('.xw-picker-opt').forEach((btn) => {
      btn.hidden = !!q && !(btn.textContent || '').includes(q);
    });
  }

  /* 重新画一次当前分区；保留滚动位置，不让点一下跳回顶部。 */
  function repaint() {
    const y = window.scrollY;
    paint(listHtml());
    window.scrollTo(0, y);
  }

  function onClick(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const rangeBtn = event.target.closest('[data-cx-range]');
    if (rangeBtn) {
      scope.range = rangeBtn.dataset.cxRange;
      if (scope.range !== 'custom') { scope.from = ''; scope.to = ''; }
      syncScopeUrl(); repaint(); return;
    }
    const boBtn = event.target.closest('[data-cx-bo]');
    if (boBtn) { scope.bo = boBtn.dataset.cxBo; syncScopeUrl(); repaint(); return; }
    if (event.target.closest('[data-cx-clear]')) {
      Object.assign(scope, { range: DEFAULT_RANGE, from: '', to: '', bo: '', opponent: '' });
      state.bpOpp = ''; state.bpHeroes = []; state.bpInit = false;
      state.floorSide = 'blue'; state.floorSlot = '1'; state.floorMode = 'hero';
      syncScopeUrl(); repaint(); return;
    }
    if (event.target.closest('[data-cx-retry]')) { state.loaded = false; loadAll(); return; }
    const sectionBtn = event.target.closest('[data-cx-section-link]');
    if (sectionBtn) {
      state.section = sectionBtn.dataset.cxSectionLink;
      document.querySelectorAll('[data-cx-section]').forEach((s) => { s.hidden = s.dataset.cxSection !== state.section; });
      document.querySelectorAll('[data-cx-section-link]').forEach((b) => b.classList.toggle('is-active', b === sectionBtn));
      syncScopeUrl();
      const bar = document.querySelector('.xw-bar');
      if (bar) bar.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    /* 口径 chip：点一下取消这一条 */
    const scopeBtn = event.target.closest('[data-xw-scope]');
    if (scopeBtn) {
      const key = scopeBtn.dataset.xwScope;
      if (key === 'side') state.side = 'own';
      else if (key === 'range') { scope.range = DEFAULT_RANGE; scope.from = ''; scope.to = ''; }
      else if (key === 'bo') scope.bo = '';
      else if (key === 'opp') { scope.opponent = ''; state.bpOpp = ''; }
      else if (key === 'bp') state.bpOpp = '';
      syncScopeUrl(); repaint(); return;
    }
    /* 常打对手快捷 */
    const oppBtn = event.target.closest('[data-cx-opp]');
    if (oppBtn) {
      const name = oppBtn.dataset.cxOpp || '';
      scope.opponent = scope.opponent === name ? '' : name;
      state.bpOpp = '';
      syncScopeUrl(); repaint(); return;
    }
    /* 本区模块索引 */
    const jumpBtn = event.target.closest('[data-xw-jump]');
    if (jumpBtn) {
      const target = document.getElementById(`xw-${jumpBtn.dataset.xwJump}`);
      if (target) {
        /* 自己算落点：吸顶页签 + 顶部导航的高度都要让开，别指望 scroll-padding。 */
        const page = document.querySelector('.xw-page');
        const stickyTop = parseFloat(getComputedStyle(page || document.body).getPropertyValue('--xw-sticky-top')) || 0;
        const pinH = document.querySelector('.xw-pin')?.getBoundingClientRect().height
          || document.querySelector('.xw-tabs')?.getBoundingClientRect().height || 84;
        const y = target.getBoundingClientRect().top + window.scrollY - stickyTop - pinH - 16;
        window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
      }
      return;
    }
    /* 「看这 N 局」展开/收起 */
    const gamesBtnEl = event.target.closest('[data-xw-games]');
    if (gamesBtnEl) {
      const key = gamesBtnEl.dataset.xwGames || '';
      state.games = state.games === key ? '' : key;
      repaint();
      const panel = document.getElementById('xw-games-panel');
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    /* BP 分区：本队 / 敌方 */
    const sideBtn = event.target.closest('[data-xw-side]');
    if (sideBtn) { state.side = sideBtn.dataset.xwSide === 'foe' ? 'foe' : 'own'; state.bpHeroes = []; state.bpInit = false; syncScopeUrl(); repaint(); return; }
    /* 楼层分析：对面蓝/红、楼层、组合显示（组合视图只跟红蓝方联动） */
    const floorSideBtn = event.target.closest('[data-xw-floor-side]');
    if (floorSideBtn) {
      state.floorSide = floorSideBtn.dataset.xwFloorSide === 'red' ? 'red' : 'blue';
      const floors = FLOOR_SETS[state.floorSide];
      if (!floors.some((x) => x.key === state.floorSlot)) state.floorSlot = floors[0].key;
      syncScopeUrl(); repaint(); return;
    }
    const floorBtn = event.target.closest('[data-xw-floor]');
    if (floorBtn) {
      state.floorSlot = floorBtn.dataset.xwFloor || '1';
      syncScopeUrl(); repaint(); return;
    }
    const floorComboBtn = event.target.closest('[data-xw-floor-combo]');
    if (floorComboBtn) {
      state.floorMode = state.floorMode === 'combo' ? 'hero' : 'combo';
      syncScopeUrl(); repaint(); return;
    }
    /* 对位台：模式与英雄 */
    const modeBtn = event.target.closest('[data-xw-mode]');
    if (modeBtn) {
      state.bpMode = modeBtn.dataset.xwMode === 'pair' ? 'pair' : 'against';
      state.bpHeroes = []; state.bpInit = false; state.picker = '';
      repaint(); return;
    }
    /* 英雄选择器开合 */
    const pickerBtn = event.target.closest('[data-xw-picker]');
    if (pickerBtn) {
      const kind = pickerBtn.dataset.xwPicker || '';
      state.picker = state.picker === kind ? '' : kind;
      state.heroQuery = '';
      repaint();
      const input = document.querySelector('.xw-picker-search');
      if (input) input.focus();
      return;
    }
    /* 选择器里多选：两个方向都支持 1–4 个英雄，选 2 个以上即组合，再点一次取消。 */
    const comboBtn = event.target.closest('[data-xw-combo]');
    if (comboBtn) {
      const hero = comboBtn.dataset.xwCombo || '';
      if (!hero) return;
      let arr = (state.bpHeroes || []).filter(Boolean).slice(0, 4);
      const i = arr.indexOf(hero);
      if (i >= 0) arr.splice(i, 1);
      else if (arr.length < 4) arr.push(hero);
      state.bpHeroes = arr;
      repaint();
      const input = document.querySelector('.xw-picker-search');
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      return;
    }
    if (event.target.closest('[data-xw-combo-clear]')) {
      state.bpHeroes = [];
      repaint();
      const input = document.querySelector('.xw-picker-search');
      if (input) input.focus();
      return;
    }
    const pickBtn = event.target.closest('[data-xw-pick]');
    if (pickBtn) {
      const hero = pickBtn.dataset.xwPick || '';
      state.bpHeroes = hero ? [hero] : [];
      state.picker = '';
      repaint();
      /* 从英雄池点过来时滚到对位台；在弹层里选就不用跳 */
      if (pickBtn.classList.contains('xw-hero')) {
        const card = document.getElementById('xw-draft-bp');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      return;
    }
    const viewBtn = event.target.closest('[data-xc-view-btn]');
    if (viewBtn) { switchViz(viewBtn.dataset.xcVizId, viewBtn.dataset.xcViewBtn); return; }
  }

  function onChange(event) {
    if (!isCrossRoute() || !event.target.closest) return;
    const dateNode = event.target.closest('[data-cx-date]');
    if (dateNode) {
      if (dateNode.dataset.cxDate === 'from') scope.from = dateNode.value;
      if (dateNode.dataset.cxDate === 'to') scope.to = dateNode.value;
      if (scope.from || scope.to) scope.range = 'custom';
      syncScopeUrl(); repaint(); return;
    }
    const xw = event.target.closest('[data-xw]');
    if (xw) {
      const key = xw.dataset.xw;
      if (key === 'bp-opp') state.bpOpp = xw.value;
      else if (key === 'bp-hero') state.bpHeroes = xw.value ? [xw.value] : [];
      syncScopeUrl(); repaint(); return;
    }
    const node = event.target.closest('[data-cx]');
    if (!node) return;
    if (node.dataset.cx === 'opponent') scope.opponent = node.value;
    syncScopeUrl(); repaint();
  }

  return { render, bind };
}
