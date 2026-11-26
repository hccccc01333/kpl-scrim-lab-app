/** 两轮 BP 指纹内核回归：node scripts/test_team_bp_fingerprint.mjs */
import assert from 'node:assert/strict';
import {
  buildFingerprint, buildConditional, filterByCondition, roundsOf, targetKind, trajectoryOf,
} from '../v3/public/team-bp-fingerprint.js';

const ev = (order, phase, action, side, hero, lane, archetype, extra = {}) => ({
  order, phase, action, side, hero, lane, archetype, parallel: false, blind: false, ...extra,
});

const makeGame = ({ result = true, first = [], second = [], ban2 = [], cores = 3, front = 1 } = {}) => {
  const events = [
    ev(1, 'ban1', 'ban', 'own', '盾山', '游走', '保护辅'),
    ev(2, 'ban1', 'ban', 'enemy', '张良', '中路', '工具人'),
    ev(3, 'ban1', 'ban', 'own', '庄周', '游走', '功能辅'),
    ev(4, 'ban1', 'ban', 'enemy', '海月', '中路', '法刺'),
    ...first.map((pick, index) => ev(5 + index, 'pick1', 'pick', 'enemy', pick.hero, pick.lane, pick.archetype)),
    ...ban2.map((ban, index) => ev(11 + index, 'ban2', 'ban', 'own', ban.hero, ban.lane, ban.archetype)),
    ...second.map((pick, index) => ev(17 + index, 'pick2', 'pick', 'enemy', pick.hero, pick.lane, pick.archetype)),
  ];
  return {
    opponentWin: result,
    draft: { known: true, events, orderAssumed: false, ruleProfile: 'draft-20' },
    sides: { enemy: { lineup: { cores, front, controls: 4, engage: 2, peel: 1, damage: 5, known: 5, total: 5 } } },
  };
};

const firstA = [
  { hero: '赵云', lane: '打野', archetype: '战野' },
  { hero: '吕布', lane: '对抗路', archetype: '战边' },
  { hero: '张飞', lane: '游走', archetype: '保护辅' },
];
const games = [
  makeGame({
    result: true, first: firstA,
    ban2: [{ hero: '澜', lane: '打野', archetype: '战野' }],
    second: [{ hero: '貂蝉', lane: '中路', archetype: '法刺' }],
    cores: 3, front: 1,
  }),
  makeGame({
    result: false, first: firstA,
    ban2: [{ hero: '不知火舞', lane: '中路', archetype: '法刺' }],
    second: [{ hero: '马可波罗', lane: '发育路', archetype: '游射' }],
    cores: 2, front: 0,
  }),
  makeGame({
    result: null, first: firstA,
    ban2: [{ hero: '瑶', lane: '游走', archetype: '保护辅' }],
    second: [{ hero: '小乔', lane: '中路', archetype: '法刺' }],
    cores: 3, front: 1,
  }),
];

/* 1. 未知结果不落入输局，赢输分组保持三态。 */
const fingerprint = buildFingerprint(games);
assert.equal(fingerprint.known.length, 3);
assert.equal(fingerprint.win.length, 1);
assert.equal(fingerprint.loss.length, 1);
assert.equal(fingerprint.unknown.length, 1);
assert.equal(fingerprint.winData.firstPickHeroes[0].key, '赵云');
assert.equal(fingerprint.lossData.structure.avgCores, 2);

/* 2. 两轮事件按 phase 分开，第二 Pick 不会被混进首抢。 */
const rounds = roundsOf(games[0]);
assert.deepEqual(rounds.pick1.enemy.map((event) => event.hero), ['赵云', '吕布', '张飞']);
assert.deepEqual(rounds.ban2.own.map((event) => event.hero), ['澜']);
assert.deepEqual(rounds.pick2.enemy.map((event) => event.hero), ['貂蝉']);

/* 3. 针对识别：同路同型、同路、核心、前排和其他。 */
assert.equal(targetKind({ hero: '关羽', lane: '对抗路', archetype: '战边' }, [firstA[1]]), 'laneType');
assert.equal(targetKind({ hero: '廉颇', lane: '对抗路', archetype: '坦边' }, [firstA[1]]), 'lane');
assert.equal(targetKind({ hero: '不知火舞', lane: '中路', archetype: '法刺' }, [firstA[0]]), 'core');
assert.equal(targetKind({ hero: '瑶', lane: '游走', archetype: '保护辅' }, [firstA[2]]), 'laneType');
assert.equal(targetKind({ hero: '张良', lane: '中路', archetype: '工具人' }, [firstA[0]]), 'other');
assert.equal(targetKind({ hero: '海月', lane: '中路', archetype: '法刺' }, []), 'unknown');

/* 4. P1 → R2 Ban → P2 条件路径按来源英雄累计，不覆盖前一条样本。 */
const conditional = buildConditional(games, 'p1-r2');
const zhao = conditional.rows.find((row) => row.key === '赵云');
assert.ok(zhao);
assert.equal(zhao.games, 3);
assert.deepEqual(zhao.responses.map((row) => row.key).sort(), ['core', 'laneType', 'other'].sort());
assert.equal(zhao.next.find((row) => row.key === '貂蝉').count, 1);

/* 5. 条件筛选同时约束赢局与输局，核心数筛选不会把未知结果补成输。 */
const coreTwo = filterByCondition(games, { type: 'core', value: 2 });
assert.equal(coreTwo.length, 1);
assert.equal(buildFingerprint(coreTwo).loss.length, 1);
const firstZhao = filterByCondition(games, { type: 'firstPickHero', value: '赵云' });
assert.equal(firstZhao.length, 3);

/* 6. 第一轮与第二轮末段响应使用各自阶段，不拿所有 Ban 去配首抢。 */
const r1 = buildConditional(games, 'r1-p1');
const r2 = buildConditional(games, 'r2-p2');
assert.ok(r1.rows.length >= 2);
assert.equal(r1.rows.find((row) => row.key === '盾山').responses[0].key, '赵云');
assert.equal(r2.rows.find((row) => row.key === '澜').responses[0].key, '貂蝉');

/* 7. 缺 phase 时按赛制手序兜底；同时 Ban 保留 parallel，不伪造逐手结论。 */
const fallback = makeGame({ result: true, first: firstA.slice(0, 1) });
fallback.draft.events = fallback.draft.events.map((event) => ({ ...event, phase: '' }));
fallback.draft.ruleProfile = 'draft-18';
assert.equal(roundsOf(fallback).pick1.enemy[0].hero, '赵云');
const parallel = makeGame({ result: true, first: firstA.slice(0, 1) });
parallel.draft.ruleProfile = 'rank-20';
parallel.draft.events = [ev(1, 'ban', 'ban', 'own', '盾山', '游走', '保护辅', { parallel: true })];
assert.equal(trajectoryOf(parallel)[0].events[0].parallel, true);
assert.equal(buildConditional([parallel], 'p1-r2').rows.length, 0);

/* 8. 空样本不造结论。 */
assert.equal(buildFingerprint([]).known.length, 0);
assert.equal(buildConditional([], 'p1-r2').rows.length, 0);

console.log('team BP fingerprint: all assertions passed');
