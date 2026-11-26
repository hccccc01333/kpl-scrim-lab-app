/** 总览三层改版回归：node scripts/test_biggame_overview.mjs */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderOverview } from '../v3/public/biggame-insight.js';

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
export const h = {
  esc,
  fmt: {
    signed: (value, digits = 0) => `${Number(value) < 0 ? '−' : '+'}${Math.abs(Number(value)).toFixed(digits)}`,
    count: (value) => String(value),
    fixed: (value, digits = 1) => Number(value).toFixed(digits),
    duration: (value) => `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`,
  },
  portrait: () => '',
};

const results = ['win', 'win', 'loss', 'win', 'loss', 'win', 'loss'];
const games = results.map((result, index) => ({
  gameIndex: index + 1, result, hasReplay: true,
  at10: [-1200, 2400, -3100, 800, -5400, 1600, -900][index],
  dragonTypes: { 暴君: { own: 2, foe: 1 } },
}));

const metric = (key, extra) => ({
  key, group: '开局', label: key, hint: '测试指标', kind: 'num', unit: 'count',
  perGame: games.map((_, index) => index), series: { value: 1, n: 7 }, base: {},
  coverage: 7, missing: games.map(() => null),
  byResult: {
    win: { value: 2, total: 8, n: 4 },
    loss: { value: -1, total: -3, n: 3 },
  },
  ...extra,
});

export const insight = {
  summary: { score: { us: 4, them: 3 } },
  baseline: {
    bestOf: 7,
    modes: { format: { metrics: { n: 128, series: 12 } } },
  },
  overview: {
    games,
    coverage: { games: 7 },
    metrics: [
      metric('firstBlood', {
        kind: 'flag', label: '一血', group: '开局',
        perGame: [1, 0, 1, 1, 0, 1, 0], series: { own: 4, n: 7, rate: 57.1 },
        base: { format: 15 }, coverage: 7,
        byResult: {
          win: { own: 4, n: 4, rate: 100 },
          loss: { own: 0, n: 3, rate: 0 },
        },
      }),
      metric('at10', {
        label: '10′ 经济差', kind: 'num', unit: 'gold',
        perGame: games.map((game, index) => index === 6 ? null : game.at10), series: { value: -3763, n: 6 },
        base: { format: 1600 }, coverage: 6,
        missing: [null, null, null, null, null, null, 'no-replay'],
      }),
      metric('towers', {
        label: '推塔', kind: 'pair',
        perGame: games.map(() => ({ own: 6, foe: 9 })),
        series: { own: 6, foe: 9, rate: 40, n: 7 },
        base: { format: 55 }, coverage: 7,
      }),
      metric('fightRate', {
        label: '团战胜率', kind: 'pct', unit: '%',
        perGame: [60, 70, 40, 80, 30, 55, 45], series: { value: 54, n: 7 },
        base: {}, coverage: 7,
      }),
    ],
  },
};

const html = renderOverview(insight, { baseMode: 'format', metricGroup: 'all', overviewView: 'games' }, h);

/* 1. 结论 → 差异 → 证据：一句话结论带覆盖局数，差异标签也带分母。 */
assert.match(html, /bgv-conclusion-line/);
assert.match(html, /覆盖 7 局/);
assert.match(html, /bgv-diff-tags/);
assert.match(html, /\d+\/7 局/);

/* 2. 基准只写一次，带历史样本量；对比列是 delta 胶囊。 */
assert.match(html, /基准 同赛制历史 · 128 局/);
assert.equal((html.match(/比同赛制历史/g) || []).length, 0);
assert.match(html, /bgv-delta is-good"[^>]*>↑ 42\.1pp/);
assert.match(html, /bgv-delta is-bad"[^>]*>↓ 5,363/);
assert.match(html, /bgv-delta is-na"[^>]*>— 无基准/);

/* 3. 五个读数卡都有迷你走势，经济差以 0 为中心。 */
assert.equal((html.match(/class="bgv-spark/g) || []).length >= 5, true);
assert.equal((html.match(/bgv-spark-zero/g) || []).length >= 3, true);

/* 4. ✓/✗ 带文字，三种缺失状态不再共用一个无解释的「—」。 */
assert.match(html, /✓<small>拿到<\/small>/);
assert.match(html, /✗<small>未拿到<\/small>/);
assert.match(html, /data-na="no-replay"/);
assert.match(html, /缺回放/);
assert.match(html, /本局未触发/);
assert.match(html, /无历史基准/);

/* 5. 语义表格 + 三列吸边 + 行展开 + 列高亮。 */
assert.match(html, /<table class="bgv-board">/);
assert.match(html, /class="bgv-col-series">整场/);
assert.match(html, /data-bgv-expand="bgv-detail-0" aria-expanded="false"/);
assert.match(html, /<tr class="bgv-detail-row" id="bgv-detail-0" hidden>/);
assert.match(html, /data-bgv-game="1"/);
assert.match(html, /role="region" aria-label="逐局指标表，可横向滚动"/);

/* 6. 视角切换：赢局平均只取赢局，整场值来自 byResult。 */
const winHtml = renderOverview(insight, { baseMode: 'format', metricGroup: 'all', overviewView: 'win' }, h);
assert.match(winHtml, /data-bgv-view="win" aria-pressed="true"/);
assert.equal((winHtml.match(/data-bgv-game=/g) || []).length, 0);
assert.match(winHtml, /4\/4/);

/* 7. 关键 8 项按偏离 × 覆盖排序，一血（42.1pp）排在推塔（15pp）前。 */
const keyHtml = renderOverview(insight, { baseMode: 'format', metricGroup: 'key', overviewView: 'games' }, h);
const order = ['一血', '推塔'].map((label) => keyHtml.indexOf(`>${label}</b>`));
assert.ok(order[0] >= 0 && order[1] >= 0 && order[0] < order[1], '关键项按差异绝对值排序');

/* 8. 样式必须未分层且最后加载，否则 uplift.css 的 !important 会把格子撑成药丸。 */
const indexHtml = readFileSync(new URL('../v3/public/index.html', import.meta.url), 'utf8');
const overviewCss = readFileSync(new URL('../v3/public/biggame-overview.css', import.meta.url), 'utf8');
assert.ok(indexHtml.indexOf('biggame-overview.css') > indexHtml.indexOf('player-detail-refined.css'));
assert.match(overviewCss, /#app \.bgv-board \.bgv-cell-btn[\s\S]*min-block-size: 0 !important/);
assert.doesNotMatch(overviewCss, /@container/);

console.log('big game overview render: all assertions passed');
