/** 英雄板块 UI 回归：node scripts/test_hero_ui.mjs */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

/* 这些模块只在事件回调里访问 DOM；渲染测试用最小 stub 即可。 */
globalThis.document = {
  addEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

const [
  { createHeroCompare },
  { createHeroUsagePage, createLaneMetricsPage, createComboCardsPage },
] = await Promise.all([
  import('../v3/public/hero-compare.js'),
  import('../v3/public/team-hero-insight.js'),
]);

const portrait = () => '<img class="portrait" alt="">';

/* 1. 英雄对比固定左蓝右红，结论只保留一句，领先不只靠颜色。 */
const compareData = {
  heroes: {
    own: [
      { hero: '测试甲', lane: '对抗路', games: 8, winRate: 60, kda: 4.2, gpm: 720, dpm: 21000, participation: 55 },
      { hero: '测试乙', lane: '对抗路', games: 6, winRate: 50, kda: 3.1, gpm: 620, dpm: 18000, participation: 60 },
    ],
    enemy: [],
  },
};
const compareHtml = createHeroCompare({ portrait }).render(compareData);
assert.match(compareHtml, /hc-duel-side a is-blue/);
assert.match(compareHtml, /hc-duel-side b is-red/);
assert.match(compareHtml, /hc-color-legend/);
assert.match(compareHtml, /对象 A（左 · 蓝）/);
assert.match(compareHtml, /对象 B（右 · 红）/);
assert.match(compareHtml, /不只看颜色/);
assert.match(compareHtml, /测试甲 领先/);
const claim = compareHtml.match(/<h2 class="hc-claim">([\s\S]*?)<\/h2>/)?.[1] || '';
assert.ok(claim);
assert.doesNotMatch(claim, /<\/p>|<p/);
assert.doesNotMatch(compareHtml, /<p class="hc-fact">/);

/* 2. 本队英雄表：全空环比列隐藏，单位进表头；有环比时恢复。 */
const baseRow = (hero, games = 2, change) => ({
  hero,
  lane: '对抗路',
  kplWinRate: null,
  byPeriod: { 7: { games, winRate: 50, current: { games, winRate: 50 }, change } },
  trend7: [],
});
const usageNoChange = createHeroUsagePage({ portrait }).render({ heroRows: [baseRow('测试甲'), baseRow('测试乙')] });
assert.match(usageNoChange, /thd-no-change/);
assert.match(usageNoChange, /使用次数（次）/);
assert.match(usageNoChange, /训练赛胜率（%）/);
assert.match(usageNoChange, /KPL 胜率（%）/);
assert.doesNotMatch(usageNoChange, /<span>环比（%）<\/span>/);
assert.doesNotMatch(usageNoChange, /<small>次<\/small>|<small>训练赛<\/small>|<small>KPL<\/small>/);
assert.match(usageNoChange, /thd-seg-quiet thd-period-switch/);

const usageWithChange = createHeroUsagePage({ portrait }).render({ heroRows: [baseRow('测试甲', 3, 2.5)] });
assert.doesNotMatch(usageWithChange, /thd-no-change/);
assert.match(usageWithChange, /<span>环比（%）<\/span>/);

/* 3. 分路指标：首屏选有数据且达标最多的英雄，页签数字与达标徽章带明确单位。 */
const metric = (label, level = 'pass') => ({ label, value: 1, previous: 1, change: 0, level, grade: '达标' });
const laneData = {
  anchor: '2026-11-28',
  laneHeroes: {
    对抗路: [
      { hero: '空数据英雄', byPeriod: { 7: { games: 9, metrics: [] } } },
      { hero: '少达标英雄', byPeriod: { 7: { games: 8, metrics: [metric('指标一'), metric('指标二', 'low'), metric('指标三', 'low')] } } },
      { hero: '多达标英雄', byPeriod: { 7: { games: 6, metrics: [metric('指标一'), metric('指标二'), metric('指标三')] } } },
    ],
  },
};
const laneHtml = createLaneMetricsPage({ portrait }).render(laneData);
assert.match(laneHtml, /使用英雄 多达标英雄/);
assert.match(laneHtml, /3 个英雄/);
assert.match(laneHtml, /<span class="thd-pass-badge">3 项达标<\/span>/);
assert.match(laneHtml, /指标一/);

/* 4. 组合卡：有数据优先、空卡折叠、空环比隐藏、强弱联动规则可见。 */
const combo = (heroes, games = 0, change) => ({
  heroes,
  kind: 'pairs',
  strength: heroes[0] === '有数据' ? 'strong' : 'weak',
  byPeriod: { 7: { games, winRate: games ? 60 : null, current: { games, winRate: games ? 60 : null }, change } },
});
const comboData = {
  anchor: '2026-11-28',
  combos: [combo(['空卡甲']), combo(['有数据'], 5), combo(['空卡乙'])],
};
const comboHtml = createComboCardsPage({ portrait }).render(comboData);
assert.ok(comboHtml.indexOf('有数据') < comboHtml.indexOf('空卡甲'));
assert.match(comboHtml, /当前窗口暂无对局/);
assert.match(comboHtml, /thd-combo-nums is-no-change/);
assert.match(comboHtml, /强联动/);
assert.match(comboHtml, /弱联动/);
assert.match(comboHtml, /标签不代表当前胜率更高/);
assert.match(comboHtml, /3 组 · 1 组有数据/);

/* 5. 英雄榜只在授权函数内做展示修正：两个筛选口径、清晰表头、重复文案上移、去无信息条。 */
const features = await readFile(new URL('../v3/public/features.js', import.meta.url), 'utf8');
const heroBoard = features.slice(features.indexOf('  function heroes(value) {'), features.indexOf('  function heroDetail('));
assert.equal((heroBoard.match(/全部档位/g) || []).length, 1);
assert.match(heroBoard, /全部巅峰档位/);
assert.match(heroBoard, /训练赛胜率 \/ KPL 胜率/);
assert.match(heroBoard, /hb-th-sub/);
assert.doesNotMatch(heroBoard, /hb-gradient-track/);
assert.doesNotMatch(heroBoard, /巅峰千强 · 每日更新|国服第 10 · 每日/);

console.log('hero UI: all assertions passed');
