/** 周报横向精致版回归：node scripts/test_weekly_editorial.mjs */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const js = readFileSync(new URL('../v3/public/features.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../v3/public/style.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../v3/public/index.html', import.meta.url), 'utf8');

assert.match(js, /\['matches', '本周对局概览'\]/, '周报对局模块标题必须改成概览');
assert.match(js, /本周表现优异/, '领导摘要必须写「本周表现优异」');
assert.match(js, /本周重点改善/, '领导摘要必须写「本周重点改善」');
assert.match(js, /class="rl-mosaic"/, '领导摘要必须走横向拼版');
assert.match(js, /const matchOverviewHtml =/, '对局模块必须改成聚合概览');
assert.match(js, /按日聚合，只保留节奏与结论/, '必须写清逐局明细不在周报展开');
assert.doesNotMatch(js, /if \(mod\.id === 'matches'\)[^\n]*<table class="report-table"/, 'matches 模块不得再直接铺明细表');
assert.match(css, /@page weekly-report \{ size: A4 landscape; margin: 10mm; \}/, '打印必须走 A4 横向命名页');
assert.match(css, /\.rl-mosaic \{ display: grid; grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/, '领导摘要必须是 12 栏编辑式拼版');
assert.match(css, /\.report-sheet--weekly \{ page: weekly-report;/, '周报必须绑定横向命名页');
assert.match(app, /features\.js\?v=20261127weeklyart1/, 'app.js 模块版本戳必须更新');
assert.match(html, /features\.js\?v=20261127weeklyart1/, 'index.html 预取版本戳必须更新');

console.log('weekly editorial layout: all assertions passed');
