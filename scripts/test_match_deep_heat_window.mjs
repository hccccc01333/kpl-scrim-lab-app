import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../v3/public/match-deep.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');

assert.match(src, /const HEAT_WINDOWS = \[15, 20, 30, 60\]/);
assert.match(src, /let heatWindow = 20;/);
assert.match(src, /data-heat-window/);
assert.match(src, /const from = Math\.max\(0, at - heatWindow\);/);
assert.match(src, /当前窗口 \$\{heatWindow\} 秒/);
assert.doesNotMatch(src, /HEAT_WINDOW = 90/);
assert.ok(app.indexOf('match-deep.js?v=20261127csmin1') > -1);

console.log('match heat window: all assertions passed');
