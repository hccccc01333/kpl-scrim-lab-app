import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

const app = read('v3/public/app.js');
const css = read('v3/public/page-header.css');
const html = read('v3/public/index.html');

assert.match(app, /page-header-unified/, 'JS 必须给常规页头加统一容器类');
assert.match(app, /page-h1-host/, 'JS 必须给标题父级加宿主类');
assert.match(app, /page-h1-kicker/, 'JS 必须插入统一眉题');
assert.match(app, /routeName !== 'weekly'/, '周报页头必须排除');
assert.match(app, /closest\('\.report-sheet--weekly, dialog'\)/, '报告与对话框必须排除');

assert.match(css, /--ui-page-title-font: "Songti SC"/, '标题必须使用统一宋体字栈');
assert.match(css, /--ui-page-title-size: clamp\(/, '标题字号必须用 rem 型 clamp');
assert.match(css, /border-block-end: 1px solid var\(--ui-page-rule\)/, '页头必须有统一分隔线');
assert.match(css, /text-wrap: balance/, '标题必须均衡换行');
assert.match(css, /forced-colors: active/, '页头必须有强制颜色回退');
assert.match(css, /\.desk-h1-tri/, '旧装饰三角必须隐藏');
assert.match(css, /\.comp-kicker/, '赛事页旧英文眉题必须隐藏');

assert.match(html, /page-header\.css\?v=20261128hdr1/, 'index.html 必须加载统一页头样式');
assert.match(html, /app\.js\?v=20261128hdr1/, 'index.html 必须更新 app.js 版本戳');

console.log('page header unification: all assertions passed');
