/**
 * Static / synthetic regression checks for the analyst homepage (赛训周期简报).
 * Run: node scripts/test_workspace_home.mjs
 * No live service, local training files or external packages required.
 *
 * 契约：docs/period_brief.md §2（/api/briefing 字段）与 §3（布局）。
 * 这里只验前端：给定契约形状的 payload，渲染出该有的结构、该少的统计词，
 * 以及空态 / 空库 / 失败 / 截断（最多 4 指标、3 条变化、2 条证据）等边界。
 */
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const briefUrl = new URL('../v3/public/period-brief.js', import.meta.url);
const briefSource = readFileSync(briefUrl, 'utf8');
const style = readFileSync(new URL('../v3/public/style.css', import.meta.url), 'utf8');
const uiStyle = readFileSync(new URL('../v3/public/ui-system.css', import.meta.url), 'utf8');
const platinumStyle = readFileSync(new URL('../v3/public/platinum-ds.css', import.meta.url), 'utf8');
const findingStyle = style + uiStyle + platinumStyle;
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');
const { renderBrief } = await import('data:text/javascript;base64,' + Buffer.from(briefSource).toString('base64'));

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[c]);
const ctx = {
  esc,
  fmt: (value) => (Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—'),
  icon: (name) => `<svg data-icon="${name}"></svg>`,
};
const render = (view) => renderBrief(view, ctx);

/* ── 复盘区 10 个字段目录 + 4 局合成对局（部分卡缺字段，用来验「—」） ── */
const WATCH_META = [
  { id: 'deficit', label: '最多落后', note: '全场最多落后多少金币' },
  { id: 'deaths', label: '我方掉点', note: '我方掉点次数' },
  { id: 'giveback', label: '领先被反超', note: '领先 1000 金币以上、后来被反超' },
  { id: 'fight', label: '团战打输', note: '打输的团战波数' },
  { id: 'at10', label: '10 分钟经济差', note: '10 分钟时我方领先 / 落后的金币' },
  { id: 'duration', label: '时长', note: '这局打了多久' },
  { id: 'dragon', label: '关键龙丢失', note: '关键龙丢了几条' },
  { id: 'tower', label: '被推塔', note: '被对手推掉的塔数' },
  { id: 'gold', label: '终局经济差', note: '终局时的经济差' },
  { id: 'damage', label: '团队输出占比', note: '我方团队输出占全场的比例' },
];
const WATCH_DISPLAY_DEFAULT = ['deficit', 'at10', 'deaths', 'duration'];
const WATCH_LABEL = Object.fromEntries(WATCH_META.map((field) => [field.id, field.label]));
const WATCH_COUNTS = { deficit: 17, deaths: 23, giveback: 9, fight: 15,
  at10: 21, duration: 23, dragon: 18, tower: 20, gold: 23, damage: 16 };
const WATCH_ROSTER = [
  { name: '项羽', lane: '对抗路', icon: '/catalog/icons/hero-1.png' },
  { name: '姜子牙', lane: '中路', icon: '/catalog/icons/hero-2.png' },
  { name: '黄忠', lane: '发育路', icon: '/catalog/icons/hero-3.png' },
  { name: '李白', lane: '打野', icon: '/catalog/icons/hero-4.png' },
  { name: '朵莉亚', lane: '游走', icon: '/catalog/icons/hero-5.png' },
];
const WATCH_MOMENTS = {
  a: [{ t: 600, clock: '10:00', label: '10 分钟 -2,500' },
    { t: 1200, clock: '20:00', label: '领先被反超' },
    { t: 1691, clock: '28:11', label: '最多落后 4,500' }],
  b: [{ t: 780, clock: '13:00', label: '丢暴君' }],
  c: [],
  d: [{ t: 480, clock: '08:00', label: '打输团战' },
    { t: 1100, clock: '18:20', label: '被推塔' }],
  e: [],
};

const WATCH_GAMES = {
  a: { date: '11-04', label: '11-04 · 对阵 #29', result: 'loss',
    conclusion: '本期最长的一局，打了 27 分钟，10 分钟落后 2,500 金币，先看开局。',
    values: { deficit: '-4,500 金币', deaths: '32 次', giveback: '-3,100 金币',
      fight: '4 波', at10: '-2,500 金币', duration: '27:08',
      dragon: '3 条', tower: '6 座', gold: '-12,400 金币', damage: '38.2%' } },
  b: { date: '11-03', label: '11-03 · 对阵 #20', result: 'loss',
    conclusion: '中期一波龙团被打出 0 换 4，经济差一路被拉开。',
    values: { deficit: '-3,900 金币', deaths: '28 次', giveback: '-2,600 金币',
      fight: '3 波', duration: '22:41', dragon: '2 条', tower: '5 座',
      gold: '-8,700 金币', damage: '41.5%' } },
  c: { date: '11-02', label: '11-02 · 对阵 #18', result: 'win',
    conclusion: '开局领先一路兑现，19 分钟推平，可当作优势局的参照。',
    values: { deaths: '18 次', at10: '+1,600 金币', duration: '19:02',
      dragon: '4 条', gold: '+6,200 金币', damage: '52.0%' } },
  d: { date: '11-02', label: '11-02 · 对阵 #17', result: 'loss',
    conclusion: '10 分钟还咬着，最后 18 分钟被推掉两座高地。',
    values: { deficit: '-2,100 金币', deaths: '22 次', giveback: '-1,200 金币',
      fight: '2 波', at10: '-800 金币', duration: '18:30',
      tower: '3 座', gold: '-5,300 金币', damage: '44.1%' } },
  e: { date: '11-03', label: '11-03 · 对阵 #22', result: 'loss',
    conclusion: '前中期两波团战打输，经济差被滚到 9,000 金币。',
    values: { deficit: '-1,800 金币', deaths: '35 次', giveback: '-2,400 金币',
      fight: '5 波', at10: '-1,100 金币', duration: '24:12',
      dragon: '5 条', tower: '7 座', gold: '-9,200 金币', damage: '36.0%' } },
};
/* 每个字段 5 张卡（后端最多 30）；game 'a' 出现在所有分组，用来验同 key 跨组共享关注。 */
const WATCH_GROUP_IDS = Object.fromEntries(
  WATCH_META.map((meta) => [meta.id, ['a', 'b', 'c', 'd', 'e']]));
const WATCH_SHARED_KEY = 'channel-a';

const watchCard = (gameId, field) => {
  const game = WATCH_GAMES[gameId];
  const values = WATCH_META
    .filter((meta) => game.values[meta.id] !== undefined)
    .map((meta) => ({ id: meta.id, label: meta.label, value: game.values[meta.id] }));
  const numbers = [];
  if (game.values[field]) numbers.push({ label: WATCH_LABEL[field], value: game.values[field], focus: true });
  for (const item of values) {
    if (item.id === field || numbers.length >= 4) continue;
    numbers.push({ label: item.label, value: item.value });
  }
  const gameKey = `channel-${gameId}`;
  return {
    id: `watch_${gameId}_${field}`, kind: game.result, field, title: game.label,
    conclusion: game.conclusion, values, numbers: numbers.slice(0, 4),
    rosterText: WATCH_ROSTER.map((player) => player.name).join(' · '),
    rosterPlayers: WATCH_ROSTER,
    moments: WATCH_MOMENTS[gameId] || [],
    evidence: [{ game: gameKey, label: '这局过程', note: '' }],
    primary_destination: `#match/${gameKey}`,
  };
};
const WATCH_FIELDS = WATCH_META.map((meta) => ({
  id: meta.id, label: meta.label, note: meta.note, unit: '',
  count: WATCH_COUNTS[meta.id], empty: `本期没有${meta.label}的局。`,
  items: WATCH_GROUP_IDS[meta.id].map((gameId) => watchCard(gameId, meta.id)),
}));

/* 契约 §2 的示例 payload，按周期给不同数字，用来验「切周期数字会变」。 */
const weekPayload = {
  available: true,
  reason: null,
  generatedAt: '2026-11-13T18:30:00',
  period: {
    kind: 'week', label: '本周', from: '2026-11-09', to: '2026-11-15', rangeLabel: '11-09 ~ 11-15',
    prev: { label: '上周同期', from: '2026-11-02', to: '2026-11-08', rangeLabel: '11-02 ~ 11-08' },
  },
  fallback_hint: null,
  coverage: {
    games: 6, decided: 6, withReplay: 6, withTimeline: 6, panelGames: 6,
    versions: ['1.0'], opponents: 4, dateLabel: '11-09 ~ 11-15',
    note: '本期收录 6 局，其中 6 局可看比赛过程',
  },
  record: { wins: 4, losses: 2, decided: 6, winRate: 66.7,
    prev: { wins: 5, losses: 1, decided: 6, winRate: 83.3 },
    form: [
      { result: 'win', date: '2026-11-02', opponent: '#a' },
      { result: 'loss', date: '2026-11-03', opponent: '#b' },
      { result: 'win', date: '2026-11-03', opponent: '#c' },
      { result: 'win', date: '2026-11-04', opponent: '#d' },
      { result: 'loss', date: '2026-11-04', opponent: '#e' },
      { result: 'win', date: '2026-11-04', opponent: '#f' },
    ] },
  summary: {
    sentence: '本周 6 局 4 胜 2 负，胜率 66.7%，比上周同期少赢 1 局。',
    tone: 'down',
    note: '训练赛战绩来自营地终局面板，比赛过程以官方回放为准。',
  },
  metrics: [
    { id: 'record', label: '本期战绩', valueText: '4 胜 2 负', valueSub: null,
      prevValueText: '5 胜 1 负', deltaText: '-1 场', tone: 'down',
      sample: 6, prevSample: 6, total: 6, coverage: '6/6 局', enough: true,
      note: '含仅有终局面板的局', rank: null },
    { id: 'win_rate', label: '本期胜率', valueText: '4/6', valueSub: '66.7%',
      prevValueText: '5/6（83.3%）', deltaText: '-16.6 个百分点', tone: 'down',
      sample: 6, prevSample: 6, total: 6, coverage: '6/6 局', enough: true,
      note: '已判定胜负的局里赢下的比例',
      rank: { pos: 4, total: 7, percentile: 50, tier: 'mid', tierText: '中等', text: '中等 4/7' } },
    { id: 'lead_rate', label: '十分钟领先率', valueText: '5/6', valueSub: '83.3%',
      prevValueText: null, deltaText: '上期暂无可比数据', tone: 'none',
      sample: 6, prevSample: 0, total: 6, coverage: '6/6 局', enough: true,
      note: '10 分钟时经济领先的局占比',
      rank: { pos: 1, total: 7, percentile: 100, tier: 'lead', tierText: '领先', text: '领先 1/7' } },
    { id: 'lead_hold_rate', label: '十分钟领先兑现率', valueText: '4/5', valueSub: '80.0%',
      prevValueText: null, deltaText: '上期暂无可比数据', tone: 'none',
      sample: 5, prevSample: 0, total: 5, coverage: '5/5 局', enough: true,
      note: '10 分钟领先的局最终赢下几局', rank: null },
    { id: 'lead_econ', label: '十分钟经济差', valueText: '+2,480 金币', valueSub: null,
      prevValueText: null, deltaText: '上期暂无可比数据', tone: 'none',
      sample: 6, prevSample: 0, total: 6, coverage: '6/6 局', enough: true,
      note: '10 分钟时我方领先 / 落后的金币',
      rank: { pos: 7, total: 7, percentile: 0, tier: 'behind', tierText: '落后', text: '落后 7/7' } },
    { id: 'fight_rate', label: '团战胜率', valueText: '62/90', valueSub: '68.9%',
      prevValueText: '50/80（62.5%）', deltaText: '+6.4 个百分点', tone: 'up',
      sample: 90, prevSample: 80, total: 90, coverage: '90/90 波', enough: true,
      note: '按每波团战的击杀结果统计',
      rank: { pos: 2, total: 7, percentile: 83.3, tier: 'lead', tierText: '领先', text: '领先 2/7' } },
    { id: 'dragon_rate', label: '关键龙控制率', valueText: '12/20', valueSub: '60.0%',
      prevValueText: null, deltaText: '上期暂无可比数据', tone: 'none',
      sample: 20, prevSample: 0, total: 20, coverage: '20/20 个', enough: true,
      note: '暗影主宰 / 暴君 / 暗影暴君里我方拿到的比例',
      rank: { pos: 5, total: 7, percentile: 33.3, tier: 'mid', tierText: '中等', text: '中等 5/7' } },
    { id: 'first_tower_rate', label: '一塔率', valueText: '5/6', valueSub: '83.3%',
      prevValueText: null, deltaText: '上期暂无可比数据', tone: 'none',
      sample: 6, prevSample: 0, total: 6, coverage: '6/6 局', enough: true,
      note: '每局第一座防御塔由我方拿到的比例',
      rank: { pos: 3, total: 7, percentile: 66.7, tier: 'mid', tierText: '中等', text: '中等 3/7' } },
  ],
  findings: [
    {
      id: 'lead_hold_down', kind: 'advantage', title: '十分钟领先后，丢掉优势的局变多了',
      conclusion: '本周 6 局十分钟领先，赢下 4 局；上周同期 5 局全胜。',
      numbers: [{ label: '本期', value: '4/6' }, { label: '上期', value: '5/5' }, { label: '多余', value: '忽略' }],
      n: 6, enough: false,
      evidence: [
        { game: 'channel-aaa', label: '11-04 · 对阵 #29', note: '10 分钟领先 1.2k，后期被翻', t: 1691, approx: true },
        { game: 'channel-bbb', label: '11-05 · 对阵 #31', note: '领先 2k 后被追平', t: 1500, approx: false },
        { game: 'channel-ccc', label: '11-06 · 对阵 #33', note: '第三条证据要被截断', t: 1300, approx: false },
      ],
      counterexamples: [],
      primary_destination: '#match/channel-aaa',
      deep_destination: '#players?from=2026-11-09&to=2026-11-15&source=db,bundle',
      limitation: '样本 6 局，只作本批观察；对照局不足时不能当稳定规律。',
    },
    {
      id: 'fight_arrival_up', kind: 'fight', title: '开局人少还硬接团的情况变多了',
      conclusion: '本周 9 场人数落后团战只赢 2 场，上周 7 场赢 4 场。',
      numbers: [{ label: '本期', value: '2/9' }, { label: '上期', value: '4/7' }],
      n: 9, enough: true,
      evidence: [{ game: 'channel-ddd', label: '11-05 · 对阵 #30', note: '人数落后仍接团，被打出 0 换 4' }],
      primary_destination: '#match/channel-ddd',
      deep_destination: '#matches?from=2026-11-09&to=2026-11-15',
      limitation: '只统计有回放的团战。',
    },
    {
      id: 'objective_down', kind: 'objective', title: '龙塔争夺的收益变差了',
      conclusion: '本周每局拿到 2.1 个资源/塔，上周 2.8 个。',
      numbers: [{ label: '本期', value: '2.1' }, { label: '上期', value: '2.8' }],
      n: 6, enough: true, evidence: [], limitation: '按终局面板统计。',
    },
    {
      id: 'comp_concentrated', kind: 'comp', title: '阵容更集中在中野',
      conclusion: '本周 5 局用同一套中野双人组，上周用了 8 套不同组合。',
      numbers: [{ label: '本期', value: '5 套' }, { label: '上期', value: '8 套' }],
      n: 6, enough: true, evidence: [], limitation: '',
    },
    {
      id: 'roster_death_up', kind: 'roster', title: '发育路一局死 3 次以上的情况变多了',
      conclusion: '本周 23 局里有 7 局发育路一局死 3 次以上，上周 21 局里 4 局。',
      numbers: [{ label: '本期', value: '7/23 局' }, { label: '上期', value: '4/21 局' }],
      n: 23, enough: true, evidence: [], limitation: '',
    },
    {
      id: 'opening_death', kind: 'training', title: '开局 5 分钟内掉点的情况变多了',
      conclusion: '本周 6 局里有 4 局开局 5 分钟就掉点，上周 2 局。',
      numbers: [{ label: '本期', value: '4/6' }, { label: '上期', value: '2/6' }],
      n: 6, enough: true, evidence: [], limitation: '',
    },
  ],
  findingsTitle: '本期重点发现',
  findingsCountText: '6 条',
  watchTitle: '本期最值得复盘的比赛',
  watchCountText: '5 局',
  watchField: 'deficit',
  watch: WATCH_FIELDS.find((field) => field.id === 'deficit').items,
  watchFields: WATCH_FIELDS,
  watchDisplayFields: WATCH_DISPLAY_DEFAULT,
  next: {
    available: true,
    note: '',
    items: [{ date: '2026-11-14', time: '19:30', opponent: '待命名战队 #29', note: '训练赛' }],
  },
  sources: { replay: 23, panel: 32, schedule: 1, note: '来源：官方回放 + 营地终局面板' },
  notes: ['训练赛与正式比赛未区分，按来源筛选查看'],
};

const recentPayload = JSON.parse(JSON.stringify(weekPayload));
recentPayload.period = {
  kind: 'recent', label: '最近 5 场', from: '2026-11-02', to: '2026-11-04',
  rangeLabel: '11-02 ~ 11-04', n: 5,
  prev: { label: '前 5 场', shortLabel: '前 5 场', from: '2026-10-28', to: '2026-10-30', rangeLabel: '10-28 ~ 10-30' },
};
recentPayload.summary = { sentence: '最近 5 场 4 胜 1 负，胜率 80.0%。', tone: 'up', note: '' };
recentPayload.watchTitle = '最近 5 场最值得复盘的比赛';

const monthPayload = JSON.parse(JSON.stringify(weekPayload));
monthPayload.period = {
  kind: 'month', label: '本月', from: '2026-11-01', to: '2026-11-30', rangeLabel: '11-01 ~ 11-30',
  prev: { label: '上月同期', from: '2026-10-01', to: '2026-10-30', rangeLabel: '10-01 ~ 10-30' },
};
monthPayload.summary = { sentence: '本月 21 局 12 胜 9 负，胜率 57.1%，比上月同期少赢 3 局。', tone: 'down', note: '训练赛战绩来自营地终局面板，比赛过程以官方回放为准。' };
monthPayload.coverage = { ...weekPayload.coverage, games: 21, withReplay: 12, note: '本期收录 21 局，其中 12 局可看比赛过程' };

const emptyPeriod = {
  available: false,
  reason: '本周还没有登记对局。',
  period: weekPayload.period,
  fallback_hint: { from: '2026-11-02', to: '2026-11-02', label: '11-02 ~ 11-02', games: 7 },
  coverage: { games: 0, decided: 0, withReplay: 0, withTimeline: 0, panelGames: 0, versions: [], opponents: 0, dateLabel: '11-09 ~ 11-15', note: '' },
  summary: null,
  metrics: [],
  findings: [],
  next: { available: true, note: '', items: [{ date: '2026-11-14', time: '19:30', opponent: '待命名战队 #29', note: '训练赛' }] },
  sources: { replay: 0, panel: 0, schedule: 1, note: '' },
  notes: [],
};

const emptyLibrary = {
  ...emptyPeriod,
  available: false,
  reason: '这个工作台还没有任何对局数据。',
  fallback_hint: null,
  period: { ...weekPayload.period, rangeLabel: '' },
  next: { available: false, note: '还没有登记下一场约训', items: [] },
};

/* 1) 本周正常渲染：结构、顺序、下钻链接与截断 */
const week = render({ kind: 'week', data: weekPayload });
// Decorative artwork must not replace or alter any original homepage content.
for (const view of [
  { kind: 'week', data: weekPayload }, { kind: 'month', data: monthPayload },
  { kind: 'week', data: emptyPeriod }, { kind: 'week', data: emptyLibrary },
  { kind: 'week', loading: true }, { kind: 'week', error: new Error('unavailable') },
]) {
  const withArtwork = renderBrief(view, { ...ctx, art: true });
  assert.equal(withArtwork.replace(/<img class="pbr-celadon-art"[^>]*>/, '').replace(/>\s+</g, '><'), render(view).replace(/>\s+</g, '><'),
    '青瓷装饰不能删减原首页的内容或操作');
  assert(!withArtwork.includes('data-gallery-evidence'), '不能插入额外经济/最近对局模块');
}
for (const text of ['赛训周期简报', '赛训总览', '本周 · 11-09 ~ 11-15', '对比上周同期 11-02 ~ 11-08']) {
  assert(week.includes(text), '简报缺少契约要求的文案：' + text);
}
for (const key of ['today', 'week', 'month', 'all', 'days', 'custom']) {
  assert(week.includes(`data-pbr-period="${key}"`), '缺少周期按钮：' + key);
}
assert(week.includes('data-pbr-period="week" aria-pressed="true"'), '默认周期应为本周期高亮');
assert(week.includes('data-action="filter"'), '顶部必须有「数据范围」入口');
assert(week.includes('本期战况'), '缺少本期战况板块');
assert(week.includes('4胜2负'), '战绩 KPI 应压缩胜负数之间的空格');
assert(week.includes('胜率 66.7%'), '战绩 KPI 应显示胜率');
assert(week.includes('本期重点发现'), '缺少发现板块标题');
assert(week.includes('本期最值得复盘的比赛'), '复盘板块标题要带周期');
assert(!week.includes('下一场约训') && !week.includes('数据覆盖'), '首页不再重复侧栏与数据源页入口');
assert(week.includes('全部对局'), '缺少全部对局入口');
assert(week.includes('href="#matches" data-pbr-all-games'), '全部对局应对齐对局档案路由');

/* 指标区使用语义表格：比例只显示百分率，分子分母与口径留在 title。 */
const metricCount = (week.match(/<tr data-metric-id="/g) || []).length;
assert.equal(metricCount, 6, '过滤重复胜率/兑现率后应保留 6 行指标，实际 ' + metricCount);
assert(week.includes('data-metric-id="record"'), '指标表需要 data-metric-id 作为稳定钩子');
assert(week.includes('<caption class="pbr-sr-only">本期与上期指标对比</caption>'), '指标表需要屏幕阅读器标题');
assert(week.includes('<th scope="col">指标</th><th scope="col">本期</th><th scope="col">上期</th><th scope="col">变化</th>'), '指标表需要完整列头');
assert(week.includes('62/90 · 按每波团战的击杀结果统计'), '比例指标的分子分母与口径应保留在 title');
assert(week.includes('class="pbr-t-current" title="62/90 · 按每波团战的击杀结果统计">68.9%'), '比例指标主值只显示百分率');
assert(week.includes('+6.4pp'), '百分点变化应压缩为 pp');
assert(week.includes('+2,480 金币'), '经济差保留金币单位');
assert(!week.includes('暂不可比'), '指标表不应出现「暂不可比」');
assert(!week.includes('href="#matches?from=2026-11-09'), '指标表不挂下钻链接');


const totalCards = WATCH_META.reduce((sum, meta) => sum + WATCH_GROUP_IDS[meta.id].length, 0);
/* 发现区（第 3 轮）：不限条数（6 条全渲染）+ 区块内滚动 + 关注按钮/置顶/时间 */
/* 信息不删：所有卡都渲染时间点与紧凑阵容，首卡只是更宽。 */
const totalMoments = WATCH_META.reduce((sum, meta) => sum + WATCH_GROUP_IDS[meta.id]
  .reduce((acc, gameId) => acc + (WATCH_MOMENTS[gameId] || []).length, 0), 0);
const findingCount = (week.match(/class="pbr-finding"/g) || []).length;
assert.equal(findingCount, 6, '发现区应渲染全部 6 条（不再截 3 条），实际 ' + findingCount);
for (const no of ['01', '02', '03', '04', '05', '06']) {
  assert(week.includes(`class="pbr-finding-no">${no}`), '发现行缺少序号 ' + no);
}
assert.equal((week.match(/class="pbr-finding-main"/g) || []).length, 6, '发现行要有左侧文字栏');
assert.equal((week.match(/class="pbr-finding-stats"/g) || []).length, 6, '发现行要有右侧数字栏');
assert.equal((week.match(/class="pbr-finding-stat"/g) || []).length, 12, '每条发现显示本期/上期两个数字');
assert(week.includes('<strong>4/6</strong><span>本期</span>'), '发现行应保留本期数字');
assert(week.includes('<strong>5/5</strong><span>上期</span>'), '发现行应保留上期数字');
assert(week.includes('十分钟领先后，丢掉优势的局变多了'), '缺少发现标题');
assert(week.includes('本周 6 局十分钟领先，赢下 4 局；上周同期 5 局全胜。'), '缺少结论句');
assert(!week.includes('多余'), '发现行只用本期与上期，多余数字不再显示');
assert(!week.includes('本批观察'), '首页不再出现「本批观察」');
assert(!week.includes('更多分析'), '首页不再显示「更多分析」');
assert(!week.includes('href="#players?from=2026-11-09'), '发现卡不再带更多分析下钻');
assert.equal((week.match(/data-pbr-fav-finding="/g) || []).length, 6,
  '每条发现都应有 [data-pbr-fav-finding] 关注按钮');
assert.equal((week.match(/data-pbr-ignore-finding="/g) || []).length, 6,
  '每条发现都应有忽略按钮');
assert(week.includes('关注'), '发现行缺少「关注」文案');
assert(week.includes('<details class="pbr-finding"'), '发现行应使用原生 details 渐进展开');
assert(week.includes('<summary class="pbr-finding-trigger">'), '发现行需要键盘可操作的 summary');
assert(!week.includes('channel-ccc'), '每条变化最多 2 条证据，第 3 条应被截断');

/* 关注注入（纯渲染）：findingFavs → 该条置顶 + is-fav + 已关注 · MM-DD HH:mm */
const favFinding = render({ kind: 'week', data: weekPayload,
  findingFavs: { opening_death: '2026-11-13T18:30:00' } });
const favFindingOrder = [...favFinding.matchAll(/data-pbr-fav-finding="([^"]+)"/g)].map((match) => match[1]);
assert.equal(favFindingOrder[0], 'opening_death', '关注的发现应渲染在最前：' + favFindingOrder.join(','));
assert(/class="pbr-finding[^"]*is-fav/.test(favFinding), '关注的发现行应加 is-fav');
assert(favFinding.includes('已关注 · 11-13 18:30'), '关注的发现应显示「已关注 · MM-DD HH:mm」');
const favFindingCrossYear = render({ kind: 'week', data: weekPayload,
  findingFavs: { opening_death: '2025-12-31T18:30:00' } });
assert(favFindingCrossYear.includes('已关注 · 2025-12-31 18:30'), '跨年关注时间要带年份');

/* 复盘区：当前字段的 5 张名片 + 10 个排序选项；不再渲染旧分组轨道。 */
const activeCards = WATCH_GROUP_IDS.deficit.length;
assert.equal((week.match(/class="pbr-review-card"/g) || []).length, activeCards,
  '默认复盘区只渲染当前字段的名片');
assert.equal((week.match(/data-review-id="/g) || []).length, activeCards,
  '每张复盘名片都有稳定 id');
assert.equal((week.match(/class="pbr-roster-hero"/g) || []).length, activeCards * 5,
  '每张名片保留我方五人阵容');
assert.equal((week.match(/href="#match\/channel-/g) || []).length, 3 + activeCards * 2,
  '证据对局链接：发现区 3 + 复盘名片每条 2 个动作');
assert(!week.includes('channel-ccc'), '每条变化最多 2 条证据，第 3 条应被截断');
assert(!week.includes('data-pbr-moment'), '名片版不再堆时间点 chip');
assert(!week.includes('data-pbr-watch-group'), '旧复盘分组轨道应删除');
assert(!week.includes('data-pbr-fav-watch'), '名片版不再显示重复关注按钮');
assert(!week.includes('data-pbr-value='), '名片版不再堆四组指标');

const sortOptions = [...week.matchAll(/data-pbr-sort-option="([^"]+)"[^>]*aria-selected="(true|false)"/g)];
assert.equal(sortOptions.length, 10, '排序菜单应有 10 个字段选项，实际 ' + sortOptions.length);
assert.deepEqual(sortOptions.map((match) => match[1]), WATCH_META.map((field) => field.id),
  '排序选项顺序应与 watchFields 目录一致');
assert.equal(sortOptions.filter((match) => match[2] === 'true').length, 1, '排序菜单选中项应严格唯一');
assert(/data-pbr-sort-option="deficit"[^>]*aria-selected="true"/.test(week), '默认排序字段 deficit 要高亮');
const deathsOption = (week.match(/data-pbr-sort-option="deaths"[\s\S]*?<\/button>/) || [''])[0];
assert(deathsOption.includes('我方掉点'), '排序选项要带字段名');

/* 排序切换：只换当前字段的名片，菜单选中项跟着切。 */
const filtered = render({ kind: 'week', data: { ...weekPayload, watchField: 'deaths' } });
assert(/data-pbr-sort-option="deaths"[^>]*aria-selected="true"/.test(filtered), '排序菜单选中项要跟着切换');
assert(/data-pbr-sort-option="deficit"[^>]*aria-selected="false"/.test(filtered), '旧字段不得残留高亮');
assert(filtered.includes('data-review-id="watch_a_deaths"'), '切换后应渲染新字段的名片');
assert.equal((filtered.match(/class="pbr-review-card"/g) || []).length, activeCards,
  '切换字段后名片数量保持稳定');
const emptyGroup = render({ kind: 'week', data: { ...weekPayload, watchField: 'giveback',
  watchFields: WATCH_FIELDS.map((field) => field.id === 'giveback' ? { ...field, items: [] } : field) } });
assert(emptyGroup.includes('本期没有领先被反超的局。'), '该字段没数据时给一句明确空态，不留白卡');

/* 老报文（无 watchFields）：仍渲染复盘名片，不造排序菜单。 */
const legacy = render({ kind: 'week', data: {
  ...weekPayload, watchFields: undefined, watchDisplayFields: undefined, watchField: undefined,
  watch: [{ id: 'watch_legacy', kind: 'loss', field: 'deficit', title: '11-04 · 对阵 #29',
    conclusion: '老报文的一句话结论。',
    numbers: [{ label: '时长', value: '27:08' }, { label: '10 分钟经济差', value: '-2,500 金币' }],
    rosterText: '项羽 · 姜子牙',
    rosterPlayers: [{ name: '项羽', lane: '对抗路', icon: '/catalog/icons/hero-1.png' }],
    evidence: [{ game: 'channel-watch', label: '这局过程', note: '' }] }],
} });
assert(legacy.includes('class="pbr-review-card"'), '老报文复盘名片仍要渲染');
assert(!legacy.includes('data-pbr-sort-option'), '老报文不应出现排序菜单');
assert(!legacy.includes('data-pbr-watch-group'), '老报文不应出现筛选分组');
assert.equal((legacy.match(/data-pbr-fav-watch="/g) || []).length, 0,
  '老报文不应出现复盘卡关注按钮');
assert.equal((legacy.match(/data-pbr-fav-finding="/g) || []).length, 6,
  '老报文的发现区仍应有关注按钮（findings 独立区块）');
assert(!legacy.includes('data-pbr-moment'), '老报文不应渲染时间点');
assert(legacy.includes('data-pbr-ignore-finding'), '老报文发现区仍应有忽略按钮');

/* 关注工作流：已复盘 + 我的结论；无结论时出现 ＋结论。 */
const findingFavs = { opening_death: { at: '2026-11-13T18:30:00',
  reviewedAt: '2026-11-14T09:00:00', note: '重点练开局' } };
const favRender = render({ kind: 'week', data: weekPayload, findingFavs, viewMode: 'all' });
assert(favRender.includes('data-pbr-fav-review'), '关注后应出现「已复盘」按钮');
assert(/data-pbr-fav-review[^>]*aria-pressed="true"/.test(favRender), '已复盘按钮应选中');
assert(favRender.includes('重点练开局'), '已保存的结论应渲染出来');
assert.equal((favRender.match(/data-pbr-fav-review/g) || []).length, 1,
  '只有一条关注发现，已复盘按钮应唯一');
const findingFavsNoNote = { opening_death: { at: '2026-11-13T18:30:00', reviewedAt: '', note: '' } };
assert(render({ kind: 'week', data: weekPayload, findingFavs: findingFavsNoNote }).includes('data-pbr-fav-note'),
  '关注但无结论时应出现 ＋结论');

/* 三态视图过滤：关注 = 有收藏；待复盘 = 收藏且 reviewedAt 空。 */
const favView = render({ kind: 'week', data: weekPayload, findingFavs, viewMode: 'fav' });
assert.equal((favView.match(/class="pbr-finding(?=[ "])(?![^"]*is-watch)[^"]*"/g) || []).length, 1,
  '关注视图发现区应只剩 1 条');
assert(favView.includes('已复盘') && favView.includes('重点练开局'), '关注视图应显示已复盘/我的结论');
const todoView = render({ kind: 'week', data: weekPayload, findingFavs, viewMode: 'todo' });
assert.equal((todoView.match(/class="pbr-finding(?=[ "])(?![^"]*is-watch)[^"]*"/g) || []).length, 0,
  '待复盘视图应排除已复盘发现');
assert(todoView.includes('没有待复盘的发现。'), '待复盘视图应给出明确空态');

/* 忽略：隐藏 + 区头「已忽略 N 条」。 */
const ignoredView = render({ kind: 'week', data: weekPayload,
  findingIgnored: { lead_hold_down: '2026-11-13T18:30:00' } });
assert(!ignoredView.includes('data-pbr-fav-finding="lead_hold_down"'),
  '被忽略的发现不应渲染');
assert(ignoredView.includes('已忽略 1 条'), '区头应显示「已忽略 N 条」');
assert(ignoredView.includes('data-pbr-restore-ignored'), '区头应提供恢复入口');
assert.equal((ignoredView.match(/data-pbr-ignore-finding="/g) || []).length, 5,
  '忽略 1 条后剩余 5 条发现的忽略按钮');

/* 下钻链接都必须是站内 hash 路由（分析专题正被并行任务增删，这里只验路由形状，
   不锁死具体页面；证据对局与「全部对局」的目标在上面单独断言）。 */
const targets = [...week.matchAll(/href="([^"]+)"/g)].map((match) => match[1]);
assert(targets.length >= 4, '首页可点目标过少');
for (const href of targets) {
  assert(href.startsWith('#'), '简报导链必须是站内 hash 路由：' + href);
  assert(!href.startsWith('#decision'), '不应再出现决策台路由：' + href);
  assert(/^#[a-z][a-z0-9_-]*(\/|\?|$)/.test(href), '目标不是「#路由」形状：' + href);
}

/* 文案纪律：默认简报不出现统计术语，也不出现占位脏值 */
for (const banned of ['Wilson', '分位', '聚类', '效应量', '模型', 'NaN', 'undefined', '>null<']) {
  assert(!week.includes(banned), '首页不应出现：' + banned);
}

/* 2) 切周期：标题范围跟着变（前端不排序、不改写后端文案） */
const month = render({ kind: 'month', data: monthPayload });
assert(month.includes('本月 · 11-01 ~ 11-30'), '月份周期标题范围不对');
assert(month.includes('对比上月同期 10-01 ~ 10-30'), '月份对比范围没跟着变');
assert(!month.includes('本周 · 11-09 ~ 11-15'), '切周期后不得残留上一周期范围');
assert(month.includes('data-pbr-period="month" aria-pressed="true"'), '月份按钮应为高亮态');

/* 3) 本期 0 局：紧凑空态 + 三个后续入口，且不出现旧结论 */
const empty = render({ kind: 'week', data: emptyPeriod });
assert(empty.includes('本周没有对局'), '空态标题不对');
assert(empty.includes('pbr-empty pbr-empty--compact'), '空态应使用紧凑结构');
assert(empty.includes('接下来可以做什么'), '空态要说明后续操作');
assert(empty.includes('查看全部对局') && empty.includes('核对选手匹配') && empty.includes('整理系列赛'), '空态要给出三个后续入口');
assert(empty.includes('href="#ingest"'), '空态要给去采集入口');
assert(!empty.includes('本周还没有登记对局。'), '空态不重复后端原始错误文案');
assert(!empty.includes('训练安排') && !empty.includes('data-pbr-fallback'), '空态不再堆叠训练安排与最近批次入口');
assert(!empty.includes(weekPayload.summary.sentence), '空态不得残留旧结论');
assert(!empty.includes('class="pbr-finding"'), '空态不应渲染变化卡');

/* 4) 空库：同样保留可读空态与入库入口 */
const library = render({ kind: 'week', data: emptyLibrary });
assert(library.includes('本周没有对局'), '空库也要渲染可读空态');
assert(library.includes('href="#ingest"'), '空库要能去采集');
assert(library.includes('整理系列赛'), '空库仍保留后续工作入口');

/* 5) 读取中 / 失败：不残留旧结论，失败可重试 */
const loading = render({ kind: 'week', data: null, loading: true });
assert(loading.includes('正在读取本期简报'), '缺少读取中状态');
assert(!loading.includes('本周期最值得关注的变化'), '读取中不应保留旧变化');
const failed = render({ kind: 'week', data: null, error: Object.assign(new Error('boom'), { status: 500 }) });
assert(failed.includes('data-pbr-retry'), '失败要给重试按钮');
assert(failed.includes('本期简报没读出来'), '失败要给模块内错误标题');
assert(!failed.includes(weekPayload.summary.sentence), '失败不得残留旧结论');
const missing = render({ kind: 'week', data: null, error: Object.assign(new Error('全站 404'), { status: 404 }) });
assert(!missing.includes('全站 404'), '不应把英文/内部错误原样摆出来');

/* 6) 静态检查：入口改造完成，旧首页代码不再残留。
   首页模块已改成按路由懒加载（importOnce），这里只要求入口仍指向 period-brief.js。 */
assert(app.includes('./period-brief.js'), 'app.js 必须接新首页模块');
assert(/createPeriodBrief/.test(app), 'app.js 必须用 createPeriodBrief 建简报');
assert(app.includes('brief.mount(document.querySelector(\'[data-pbr-root]\'))'), 'app.js 必须在 #overview 挂载简报');
assert(app.includes('r.name === \'overview\''), 'app.js 必须把 #overview 交给自取数分支');
assert(!app.includes('renderWorkspaceHome'), '旧首页渲染函数应从 app.js 移除');
assert(!app.includes('data-wh-range'), '旧周期按钮处理器应从 app.js 移除');
assert(!app.includes('data-wh-inbox-count'), '旧首页待办挂点应从 app.js 移除');
assert(!existsSync(new URL('../v3/public/workspace-home.js', import.meta.url)), '旧首页模块应已删除');
assert(!briefSource.includes('renderWorkspaceHome'), '新模块不应引用旧首页');
assert(briefSource.includes('export function renderBrief'), '简报模块要导出纯渲染供回归');
assert(briefSource.includes('/api/briefing'), '简报必须自取 /api/briefing');
assert(!briefSource.includes('localStorage.setItem'), '简报模块不写筛选，周期只影响自身请求');
/* 当前名片版只需要排序菜单；旧字段弹层与轨道控件不应重新出现。 */
assert(briefSource.includes('data-pbr-sort-option'), '排序选项钩子缺失');
assert(!week.includes('data-pbr-sort-toggle') && !week.includes('data-pbr-fields-toggle'),
  '旧工具栏按钮不应出现在名片版');
assert(!week.includes('data-pbr-watch-prev') && !week.includes('data-pbr-watch-next'),
  '旧横向轨道箭头不应出现');
assert(style.includes('.pbr-home'), '简报样式必须落进 style.css');
assert(style.includes('.pbr-period[aria-pressed="true"]'), '周期按钮需要选中态样式');
assert(findingStyle.includes('.pbr-finding-main') && findingStyle.includes('.pbr-finding-stats'), '发现行要有文字与数字两栏样式');
assert(findingStyle.includes('.pbr-watch-menu') && findingStyle.includes('.pbr-review-card'), '复盘名片与排序菜单需要样式');
assert(findingStyle.includes('.pbr-metrics-table'), '指标表需要样式');
assert(/\.pbr-home \{[^}]*font-family: var\(--font\)/.test(style),
  '首页应使用全站字体栈（Manrope + Noto Sans SC），不要单独锁死雅黑');
assert(findingStyle.includes('.pbr-finding-accordion'), '发现区需要渐进展开容器样式');
assert(style.includes('overflow-y: auto') || style.includes('overflow-y:auto'), '页面长列表要能内部上下滚动');
assert(style.includes('.pbr-fav'), '关注按钮需要样式');
assert(briefSource.includes('recent') && briefSource.includes('days'), '简报模块应支持 recent/days 周期');
assert(briefSource.includes('pbr-view-mode'), '视图模式持久化钩子缺失');
assert(briefSource.includes('pbr-finding-ignored'), '忽略持久化键缺失');
assert(briefSource.includes('reviewedAt'), '收藏结构应含 reviewedAt');
assert(briefSource.includes("node.closest('details:not([open])')"), '重画后焦点目标应自动展开所属 details');
assert(briefSource.includes('openIds.has(node.dataset.findingId)'), '发现区重画应恢复原展开项');
assert(platinumStyle.includes('@media (max-width: 900px)'), '复盘名片与发现行需要窄屏断点');
assert(style.includes('overflow-wrap: anywhere'), '长文案要能换行，避免横向滚动');

/* 7) 首页改造不牵动模块分析页：分析专题由并行任务增删，
   首页回归不再读取/断言 analysis-pages.js（该文件可能被别的任务移除/恢复）。 */

console.log('period brief checks passed');
console.log('  · 指标表', metricCount, '行，发现行', findingCount, '条，复盘名片', activeCards, '张');
console.log('  · 排序菜单 + 关注工作流 + 新周期/视图/忽略/老报文 均通过');
console.log('  · 空态 / 空库 / 读取中 / 失败 四种边界均通过');
