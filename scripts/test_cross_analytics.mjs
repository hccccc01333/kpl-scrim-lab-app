/**
 * 跨局分析内核口径回归（无服务、无浏览器、无依赖）。
 * 运行：node scripts/test_cross_analytics.mjs
 *
 * 这些断言只锁「游戏分析口径」的关键边界：
 * - 缺失不补 0；空样本不造结论；
 * - 比率区间在 0–1，组间秩差方向正确；
 * - 推塔差按同一局配对，不能把两条过滤后的数组按下标硬减；
 * - 英雄收缩胜率在原始胜率与整体基线之间；
 * - 缺 comp/first 字段时分析不抛错。
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../v3/public/cross-analytics.js', import.meta.url), 'utf8');
const mod = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const { analyzeCohort, internals } = mod;

const make = (i, over = {}) => {
  const win = i % 2 === 0;
  const at10 = win ? 3000 + i * 100 : -3000 - i * 100;
  return {
    key: `m${i}`,
    date: `2026-01-0${i + 1}`,
    clock: '20:00',
    order: `2026-01-0${i + 1} 20:00`,
    result: win ? 'win' : 'loss',
    opponent: i < 4 ? 'A' : 'B',
    duration: 900 + i * 30,
    at10,
    finalDiff: win ? 8000 : -8000,
    killsOwn: win ? 15 : 8,
    killsFoe: win ? 8 : 15,
    lanes: {
      对抗路: { gold: win ? 100 : -100, damage: 500, taken: -200 },
      打野: { gold: win ? 150 : -150, damage: 800, taken: 300 },
      中路: { gold: win ? 120 : -120, damage: 600, taken: 100 },
      发育路: { gold: win ? 180 : -180, damage: 1200, taken: -300 },
      游走: { gold: win ? 80 : -80, damage: 300, taken: 900 },
    },
    heroes: ['项羽', '赵云', '小乔', '百里守约', '钟馗'],
    heroesFoe: ['吕布', '孙悟空', '貂蝉', '马可波罗', '瑶'],
    bans: ['大乔'],
    bansOwn: ['大乔'],
    bansFoe: ['项羽'],
    compOwn: ['保护链', '强开团'],
    compFoe: ['双前排'],
    obj: { dragonOwn: win ? 3 : 1, dragonFoe: win ? 1 : 3, towerOwn: win ? 8 : 4, towerFoe: win ? 4 : 8 },
    objAt10: { dragonOwn: 1, dragonFoe: 0, towerOwn: 2, towerFoe: 1 },
    death: { own: win ? 8 : 14, foe: win ? 14 : 8 },
    fight: { n: 20, win: win ? 13 : 7, decidedN: 16, decidedWin: win ? 11 : 5 },
    first: {
      bloodT: 70, bloodSide: win ? 'own' : 'foe',
      dragonT: 120, dragonSide: win ? 'own' : 'foe', dragonName: '暴君',
      towerT: 300, towerSide: win ? 'own' : 'foe',
    },
    cut: { n: win ? 3 : 1, first: win ? 1 : 0 },
    fk: {
      adv: { n: 10, win: win ? 8 : 4 }, even: { n: 5, win: win ? 3 : 2 },
      dis: { n: 5, win: win ? 2 : 1 }, first: { n: 8, win: win ? 7 : 3 },
      firstAgainst: { n: 8, win: win ? 6 : 2 },
    },
    jungle: { crossShare: win ? 0.2 : 0.1, deepShare: 0.05, firstCross: 100, crossSec: 120 },
    buff: { anti: 2, stolen: 1 },
    fs: { 对抗路: { hurtShare: 0.2, takenShare: 0.3, n: 16 } },
    pl: [
      { name: '上单', camp: 'blue', pos: '对抗路', hero: '项羽', arch: '坦边', gpm: 600, dpm: 1500, part: 0.6, d: 2 },
      { name: '打野', camp: 'blue', pos: '打野', hero: '赵云', arch: '战士野', gpm: 650, dpm: 1800, part: 0.7, d: 3 },
      { name: '中单', camp: 'blue', pos: '中路', hero: '小乔', arch: '法刺', gpm: 620, dpm: 2200, part: 0.65, d: 2 },
      { name: '射手', camp: 'blue', pos: '发育路', hero: '百里守约', arch: '游射', gpm: 700, dpm: 2500, part: 0.62, d: 2 },
      { name: '辅助', camp: 'blue', pos: '游走', hero: '钟馗', arch: '开团辅', gpm: 400, dpm: 900, part: 0.7, d: 4 },
    ],
    camp: 'blue',
    version: 'v1', session: 's1',
    hasReplay: true, ecoPoints: 30,
    ...over,
  };
};

/* 1. 空样本不造结论 */
const empty = analyzeCohort([]);
assert.equal(empty.total, 0);
assert.equal(empty.coverage.n, 0);
assert.equal(empty.record.decided, 0);
assert.equal(empty.drivers.length, 0);

/* 2. 缺失不补 0 */
const prepared = internals.prepare([{ key: 'x', at10: null, finalDiff: null, duration: 0 }]);
assert.equal(prepared[0].at10, null);
assert.equal(prepared[0].final, null);

/* 3. 比率区间与方向 */
assert.equal(internals.wilson(0, 0), null);
const ci = internals.wilson(5, 10);
assert.ok(ci[0] >= 0 && ci[1] <= 1 && ci[0] <= 0.5 && ci[1] >= 0.5);
assert.ok(internals.cliffs([3, 4, 5], [0, 1, 2]) > 0);
assert.ok(internals.cliffs([0, 1, 2], [3, 4, 5]) < 0);

/* 4. 赢输驱动方向：终局经济差赢的局更高 */
const rows = Array.from({ length: 8 }, (_, i) => make(i));
const a = analyzeCohort(rows);
const final = a.drivers.find((d) => d.key === 'final');
assert.ok(final && final.effect > 0, '终局经济差在赢局应更高');
assert.ok(a.winCondition && /赢的局更高/.test(a.winCondition.text));

/* 5. 推塔差按同一局配对；空塔的局不参与，不能下标错位 */
const obj = internals.objectiveOf(internals.prepare([
  make(0, { obj: { dragonOwn: 2, dragonFoe: 1, towerOwn: 8, towerFoe: 4 } }),
  make(1, { obj: { dragonOwn: 1, dragonFoe: 2, towerOwn: null, towerFoe: null } }),
]));
assert.equal(obj.tower.diff, 4);
assert.equal(obj.tower.own, 8);

/* 6. 英雄收缩胜率落在原始胜率与整体基线之间 */
const d = internals.draftOf(internals.prepare(rows));
const hero = d.heroes.find((h) => h.hero === '项羽');
assert.ok(hero);
assert.ok(hero.shrunk <= Math.max(hero.rate.value, d.baseline) + 1e-9);
assert.ok(hero.shrunk >= Math.min(hero.rate.value, d.baseline) - 1e-9);

/* 7. 缺 comp/first 不抛错，且不把缺失当 0 */
const sparse = internals.prepare(rows.map((r) => ({ ...r, compOwn: null, compFoe: null, first: null, objAt10: null })));
const sparseResult = internals.draftOf(sparse);
assert.equal(sparseResult.comps.length, 0);
const sparseEarly = internals.earlyOf(sparse);
assert.equal(sparseEarly.firstN, 0);
assert.equal(sparseEarly.blood.rate, null);
assert.ok(Array.isArray(sparseEarly.jungle.cross) === false);

/* 8. 对手分组与样本标记 */
const opponents = internals.opponentOf(internals.prepare(rows));
assert.equal(opponents.items.length, 2);
assert.ok(opponents.items.every((x) => x.n === 4));

/* 9. 覆盖警示：版本只有 1 个、系列赛 0 局，应给出边界说明 */
const coverage = internals.coverageOf(internals.prepare(rows));
assert.ok(coverage.caveats.some((c) => c.includes('版本')));
assert.ok(coverage.caveats.some((c) => c.includes('系列赛')));

/* 10. 营地参团率 0–100 折成 0–1，页面不会再出现 6190% */
const withPart = internals.prepare(rows.map((r) => ({
  ...r,
  pl: r.pl.map((p) => ({ ...p, part: p.part * 100 })),
})));
const exec = internals.playerExecutionOf(withPart);
assert.ok(exec.length > 0);
assert.ok(exec.every((p) => p.part == null || (p.part >= 0 && p.part <= 1)));

console.log('cross-analytics: all assertions passed');
