/** 逐局 BP 可视化回归：node scripts/test_biggame_bp_render.mjs */
import assert from 'node:assert/strict';
import { renderBp, renderHeroPoolCross } from '../v3/public/biggame-insight.js';

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const h = {
  esc,
  fmt: {
    signed: (value, digits = 0) => Number(value).toFixed(digits),
    count: (value) => String(value),
    fixed: (value, digits = 1) => Number(value).toFixed(digits),
    duration: (value) => `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`,
  },
  portrait: (name, cls = '') => `<img class="${cls}" alt="${esc(name)}" src="/icons/${encodeURIComponent(name)}.png">`,
  comboPool: { pairs: [] },
};

const ownPicks = ['海月', '张飞', '百里守约', '铠', '芈月'];
const foePicks = ['哪吒', '女娲', '赵云', '赵怀真', '敖隐'];
const ownBans = ['盾山', '鲁班大师', '苏烈', '空空儿'];
const foeBans = ['关羽', '元流之子(辅助)', '镜', '阿古朵'];

const game = (index, result = 'win') => ({
  gameIndex: index,
  matchKey: `match-${index}`,
  result,
  heroesOwn: ownPicks,
  heroesFoe: foePicks,
  bansOwn: ownBans,
  bansFoe: foeBans,
  signature: { own: [], foe: [] },
  plan: { foeWanted: [{}, {}, {}], ownWanted: [{}, {}], foeHits: index === 1 ? 2 : 1, ownHits: 1 },
  ban: { denyItems: index === 1 ? [{ foePicks: 2 }, { foePicks: 1 }] : [{ foePicks: 1 }] },
  kpl: { own: { pairHits: 2, pairN: 1 } },
  combos: { own: [{ status: 'got' }], foe: [{ status: 'broken' }] },
});

const insight = {
  bpPlan: {
    series: { edgeMean: 0.01 },
    games: [game(1), game(2, 'loss'), game(3)],
  },
  boBp: {
    current: {
      games: [
        { index: 1, foeSide: 'red', ownPicks, foePicks, ownBans, foeBans },
        { index: 2, foeSide: 'blue', ownPicks, foePicks, ownBans, foeBans },
        { index: 3, foeSide: null, ownPicks, foePicks, ownBans, foeBans },
      ],
    },
  },
  comp: {
    games: [1, 2, 3].map((gameIndex) => ({
      gameIndex,
      ownCaps: { 前排: 1, 开团: 1, 控制: 2 },
      foeCaps: { 前排: 2, 开团: 2, 控制: 3 },
    })),
  },
  compSystem: {
    games: [1, 2, 3].map((gameIndex) => ({ gameIndex, own: { cores: 3 }, foe: { cores: 2 } })),
  },
};

const html = renderBp(insight, { bpGame: '', bpOpen: { 1: true, 2: true, 3: true } }, h);

/* 1. 每局按真实阵营换色，未知阵营保持中性。 */
assert.match(html, /我方 · 蓝方/);
assert.match(html, /对方 · 红方/);
assert.match(html, /我方 · 红方/);
assert.match(html, /对方 · 蓝方/);
assert.match(html, /阵营未记录/);
const unknownCard = html.split('data-bp-card="3"')[1]?.split('</details>')[0] || '';
assert.match(unknownCard, /bgv-bp-side-badge is-unknown/);
assert.doesNotMatch(unknownCard, /bgv-bp-side-badge is-(blue|red)/);

/* 2. Ban 与 Pick 在同一四阶段流程中，且 18 手顺序保留。 */
assert.equal((html.match(/class="bgv-bp-draft"/g) || []).length, 2);
for (const label of ['R1 Ban', 'P1', 'R2 Ban', 'P2']) assert.match(html, new RegExp(label));
assert.match(html, /bgv-bp-event is-blue is-ban/);
assert.match(html, /bgv-bp-event is-red is-pick/);
assert.match(html, /第 1 手/);
assert.match(html, /第 18 手/);

/* 3. 教练可读名称替换旧技术标签。 */
for (const label of ['双人组合命中', '拆掉对方想组的组合', '对方拆掉我方组合', '拿到对方想用的英雄', '禁用命中', '对方首选被处理']) {
  assert.match(html, new RegExp(label));
}
for (const label of ['KPL 双人命中', '对方计划命中', 'ban 命中', '我方拿到首选', '我方组合被拆']) {
  assert.doesNotMatch(html, new RegExp(label));
}

/* 4. 4 Ban 局使用实际分母，不再写死 5。 */
assert.match(html, /<b>4 \/ 12<\/b>/);
assert.match(html, /2<i>\/4<\/i>/);
assert.match(html, /五人阵容共 10 种双人搭配/);

/* 5. 英雄池胜负角标支持总 / 我方 / 对方三种视角。 */
const poolRows = [{
  hero: '测试英雄', lane: '对抗路', type: '战边', ownApps: 1, foeApps: 1,
  wins: 1, losses: 1, ownWins: 1, ownLosses: 0, foeWins: 0, foeLosses: 1,
}];
const poolAll = renderHeroPoolCross(poolRows, h, {}, 'all');
const poolOwn = renderHeroPoolCross(poolRows, h, {}, 'own');
const poolFoe = renderHeroPoolCross(poolRows, h, {}, 'foe');
assert.match(poolAll, />1胜1负<\/span>/);
assert.match(poolOwn, />胜<\/span>/);
assert.match(poolFoe, />负<\/span>/);
assert.match(poolOwn, /我方视角 · 胜/);
assert.match(poolFoe, /对方视角 · 负/);
const ownOnly = renderHeroPoolCross([{ ...poolRows[0], foeApps: 0, foeWins: 0, foeLosses: 0 }], h, {}, 'foe');
assert.doesNotMatch(ownOnly, /bgv-pool-outcome/);

console.log('big game BP render: all assertions passed');
