/** 教练档案 UI 回归：node scripts/test_coach_ui.mjs */
import assert from 'node:assert/strict';

globalThis.document = { addEventListener() {} };
const { createCoachBoard } = await import('../v3/public/coach-viz.js');

const hero = (name, lane) => ({ name, lane, icon: '' });
const board = {
  teams: [{ id: 'team-a', name: '测试战队', coach: '测试教练' }],
  games: [{
    key: 'game-1', start: '2026-11-28T10:00:00+08:00', day: '2026-11-28',
    teamId: 'team-a', coach: '测试教练', side: 'blue', result: 'loss',
    picks: {
      enemy: ['对抗路', '打野', '中路', '发育路', '游走'].map((lane, i) => hero(`教练英雄${i}`, lane)),
      own: [hero('本队英雄', '对抗路')],
    },
    bans: {
      enemy: [hero('禁用英雄一', '打野'), hero('禁用英雄二', '中路'), hero('禁用英雄三', '发育路'), hero('禁用英雄四', '游走')],
      own: [hero('本队常用英雄', '对抗路')],
    },
  }],
};

const html = createCoachBoard().render(board, { teams: [{ id: 'team-a', coach: '测试教练' }] });
assert.match(html, /pb-coach-hero-light/);
assert.match(html, /pb-color-legend/);
assert.match(html, /蓝方/);
assert.match(html, /红方/);
assert.match(html, /当前教练/);
assert.match(html, /低于参照/);
assert.match(html, /说明/);
assert.match(html, /英雄热门度/);
for (const legacy of ['同侪站位', '条件频率', '英雄偏冷', '英雄偏热', '禁得偏热', '禁得偏冷']) {
  assert.doesNotMatch(html, new RegExp(legacy));
}
assert.match(html, /最近一局/);
assert.match(html, /禁用命中本队常用英雄/);

console.log('coach UI: all assertions passed');
