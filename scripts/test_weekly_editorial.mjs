/** 周报横向精致版回归：node scripts/test_weekly_editorial.mjs */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const js = readFileSync(new URL('../v3/public/features.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../v3/public/weekly-refined.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../v3/public/index.html', import.meta.url), 'utf8');

assert.match(js, /\['matches', '本周对局概览'\]/, '周报对局模块标题必须改成概览');
assert.match(js, /本周表现优异/, '领导摘要必须写「本周表现优异」');
assert.match(js, /本周重点改善/, '领导摘要必须写「本周重点改善」');
assert.match(js, /class="rl-mosaic"/, '领导摘要必须走横向拼版');
assert.match(js, /const matchOverviewHtml =/, '对局模块必须改成聚合概览');
assert.match(js, /按日聚合，只保留节奏与结论/, '必须写清逐局明细不在周报展开');
assert.doesNotMatch(js, /if \(mod\.id === 'matches'\)[^\n]*<table class="report-table"/, 'matches 模块不得再直接铺明细表');
assert.match(js, /class="report-lede"/, '必须有本周结论导语');
assert.match(js, /<footer class="report-footer">/, '周报必须有页脚版本信息');
assert.match(css, /@page weekly-report \{ size: A4 landscape; margin: 10mm; \}/, '打印必须走 A4 横向命名页');
assert.match(css, /\.rl-mosaic \{ display: grid; grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/, '领导摘要必须是 12 栏编辑式拼版');
assert.match(css, /\.report-sheet--weekly \{ page: weekly-report;/, '周报必须绑定横向命名页');
assert.match(css, /--rl-gradient-space: in oklab/, '渐变必须显式指定 in oklab 并有回退');
assert.match(css, /text-wrap: pretty/, '导语正文必须用 pretty 换行');
assert.match(css, /@media \(forced-colors: active\) \{\s*\.report-lede/, '导语必须有强制颜色回退');
assert.match(css, /counter-reset: weekly-section/, '章节必须有编辑式编号');
assert.match(css, /"Songti SC"/, '标题必须有衬线字体栈');
assert.match(css, /\.rl-table-wrap \.report-table \{ table-layout: fixed; width: 100%/, '组合表必须固定三列');
assert.match(css, /text-box: trim-both cap alphabetic/, '头像与文字必须按可见字形对齐');
assert.match(css, /font-variant-numeric: tabular-nums/, '局数必须等宽对齐');
assert.match(css, /\.rl-table-wrap tr \{ display: table-row/, '组合表不能被容器查询拆成块');
assert.match(css, /\.rl-mosaic > \.rl-card--table \{ grid-column: span 6; \}/, '组合卡必须给足宽度');
assert.match(js, /<progress max="100" value=/, '胜率必须用原生 progress 承载语义');
assert.match(js, /class="rl-rank"/, '组合必须有排名');
assert.match(css, /appearance: none; border: 0 solid;/, 'progress 必须显式重置默认样式');
assert.match(html, /weekly-refined\.css\?v=20261127weeklyart6/, 'index.html 必须最后加载周报视觉层');
assert.match(app, /features\.js\?v=20261127weeklyart6/, 'app.js 模块版本戳必须更新');
assert.match(html, /features\.js\?v=20261127weeklyart6/, 'index.html 预取版本戳必须更新');

console.log('weekly editorial layout: all assertions passed');
