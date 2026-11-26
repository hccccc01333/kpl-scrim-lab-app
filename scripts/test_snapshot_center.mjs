import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createSnapshotCenter } from '../v3/public/snapshot-center.js';

const html = createSnapshotCenter({ API_BASE: '' }).html();

assert.match(html, /规则是全局共享的/);
assert.match(html, /给每场赛事留一份/);
assert.match(html, /怎么用/);
assert.match(html, /打包[\s\S]*取回[\s\S]*留痕/);
assert.match(html, /已结束赛事只允许按当下打包覆盖/);
assert.match(html, /data-sc-grid/);
assert.match(html, /data-sc-packall/);
assert.match(html, /class="sc-dialog"/);

/* 样式必须在 uplift 之后加载，且用局部 !important 锁回按钮尺寸。 */
const indexHtml = readFileSync(new URL('../v3/public/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../v3/public/snapshot-center.css', import.meta.url), 'utf8');
assert.ok(indexHtml.indexOf('snapshot-center.css') > indexHtml.indexOf('uplift.css'));
assert.match(css, /#app \.sc-module-head \{[\s\S]*min-block-size: 0 !important/);
assert.match(css, /@media \(max-width: 760px\)[\s\S]*grid-row: 3/);

console.log('snapshot center layout: all assertions passed');
