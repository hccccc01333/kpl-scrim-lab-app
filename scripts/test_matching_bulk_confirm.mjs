/** 匹配页侧栏「一键确认」回归：node scripts/test_matching_bulk_confirm.mjs */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const js = readFileSync(new URL('../v3/public/matching-page.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../v3/public/matching.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');

assert.match(js, /function reviewPendingSide\(game, camp\)/, '必须按阵营限制批量复核范围');
assert.match(js, /data-mb-confirm-all=/, '侧栏必须渲染一键确认按钮');
assert.match(js, /rows\.forEach\(\(row\) => \{ row\.confidence = 'manual'; \}\)/, '批量确认必须写 manual 置信度');
assert.match(js, /game\.dirty = true/, '批量确认后必须标记 dirty 等待保存');
assert.match(js, /select\.dataset\.mbCamp !== camp/, '只更新当前阵营的行，不能跨阵营误改');
assert.match(js, /可点侧栏「一键确认」批量复核/, '复核提示必须告诉教练有批量入口');
assert.match(css, /\.mb-confirm-all:disabled/, '禁用态要有可辨识样式');
assert.match(css, /\.mb-side > header \{[^}]*flex-wrap: wrap/, '窄屏侧栏标题与按钮要能换行');
assert.match(app, /matching-page\.js\?v=20261128ui5/, '模块版本戳必须更新，避免旧缓存');

console.log('matching bulk confirm: all assertions passed');
