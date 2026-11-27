/**
 * 赛训组反馈回归：跨场金币两档门槛 / 领先落后分色 / 对比列百分号 / 图 6 筛选短标签。
 * 运行：node scripts/test_cross_gold_thresholds.mjs
 * 纯静态断言 + 内核常量断言，不启服务、不开浏览器。
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { LEAD_TIERS, BIG_LEAD_AT10, HUGE_LEAD_AT10 } from '../v3/public/cross-analytics.js';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const page = read('v3/public/cross-page.js');
const viz = read('v3/public/cross-viz.js');
const kernel = read('v3/public/cross-analytics.js');
const insight = read('v3/public/biggame-insight.js');
const crossCss = read('v3/public/cross.css');
const overviewCss = read('v3/public/biggame-overview.css');
const period = read('analysis_period.py');

/* 1. 内核就是两档门槛的来源，不是只改了页面文案。 */
assert.deepEqual(LEAD_TIERS.map((row) => row.threshold), [3000, 5000]);
assert.equal(BIG_LEAD_AT10, 3000);
assert.equal(HUGE_LEAD_AT10, 5000);
assert.ok(kernel.includes('export const LEAD_TIERS'), '门槛常量必须导出给页面复用');
assert.ok(kernel.includes('riskTierOf(rows, threshold)'), '风险计数按档位计算，不能只换文案');
assert.doesNotMatch(kernel, /at10\s*>=\s*1000|at10\s*<=\s*-1000/, '内核不应残留 1,000 金币阈值');

/* 2. 跨场页：两档并列、领先/落后分色且文案写明，不再出现旧的 1,000 门槛。 */
assert.ok(page.includes('LEAD_TIERS, BIG_LEAD_AT10'), '页面从内核拿门槛，不自己写死');
assert.ok(page.includes('xw-lead-word') && page.includes('xw-behind-word'), '领先/落后文案带颜色 class');
assert.ok(page.includes('xw-tier-line') && page.includes('is-${x.side}'), '两档并排且按条件着色');
assert.ok(page.includes('<em class="xw-behind-word">落后</em>就算，没有金币门槛'));
assert.doesNotMatch(page, /1,000 金币|1,000<\/b>|at10 >= 1000/, '跨场页不应残留 1,000 金币门槛');

/* 3. 图 6（翻盘局分布）：两档各一栏，按领先/落后而非胜负分色。 */
assert.ok(viz.includes("import { BIG_LEAD_AT10 } from './cross-analytics.js'"));
assert.ok(viz.includes('xv-tier-grid') && viz.includes('tierList'), '两档逐局名单同时展示');
assert.ok(viz.includes("side: 'lead'") && viz.includes("side: 'behind'"));
assert.ok(viz.includes('xv-lead-word') && viz.includes('xv-behind-word'));
assert.doesNotMatch(viz, /1,000 金币|cls: 'is-loss'|cls: 'is-win'/, '翻盘卡不再写 1,000 或按胜负着色');

/* 4. 总览与对比：单位改成 %，数值口径不动；图 6 筛选只留短标签。 */
assert.ok(/:\s*'%';/.test(insight), 'deltaText 的展示单位应是 %');
assert.doesNotMatch(insight, /: 'pp';/, '不应残留 pp 单位常量');
assert.ok(insight.includes("['all', '总共'") && insight.includes("['own', '我方'"));
assert.ok(insight.includes("['foe', '敌方'"));
assert.doesNotMatch(insight, /'总胜负'|'只看我方'|'只看对方'/, '按钮只显示总共/我方/敌方');
assert.ok(insight.includes('data-bgx-pool-outcome="${key}"'), 'data 值仍是 all/own/foe，功能语义不变');

/* 5. CSS：窄屏不溢出；颜色不止靠色相（文案已写明），并给出新特性 fallback。 */
assert.ok(crossCss.includes('.xw-count-row.is-lead > b { color: var(--ds-pos); }'));
assert.ok(crossCss.includes('.xw-count-row.is-behind > b { color: var(--ds-neg); }'));
assert.ok(crossCss.includes('.xw-tier-line { display: flex; flex-wrap: wrap;'));
assert.ok(crossCss.includes('.xv-tier-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));'));
assert.ok(/@media \(max-width: 640px\)[\s\S]*\.xv-tier-grid \{ grid-template-columns: minmax\(0, 1fr\);/.test(crossCss));
assert.ok(crossCss.includes('color: contrast-color(var(--tier-bg));'));
assert.ok(crossCss.includes('color: var(--tier-fg);'), 'contrast-color() 必须有 fallback');
assert.ok(crossCss.includes('text-box: trim-both cap alphabetic;'));
assert.ok(overviewCss.includes('.bgv-pool-scope { flex-wrap: wrap; min-inline-size: 0; }'));
assert.ok(overviewCss.includes('text-box: trim-both cap alphabetic;'));

/* 6. 周期简报的 1,000 是另一套口径，注释要说清楚，别被误当成跨场来源改掉。 */
assert.ok(period.includes('LEAD_AT10 = 1000'));
assert.ok(period.includes('不是跨场分析卡片的后端来源'));

console.log('cross gold thresholds + labels: all assertions passed');
