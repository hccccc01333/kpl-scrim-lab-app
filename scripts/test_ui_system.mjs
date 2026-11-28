import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const css = read('v3/public/ui-system.css');
const html = read('v3/public/index.html');
const docs = read('v3/public/docs-page.js');
const sources = read('v3/public/datasource-page.js');
const health = read('v3/public/source-health-page.js');
const rhythm = read('v3/public/line-rhythm.css');
const desk = read('v3/public/training-desk.css');

assert.match(html, /ui-system\.css\?v=20261128ui5/, '全站样式必须最后加载并带版本戳');
assert.match(css, /--ui-control-height: 38px/, '控件高度必须统一');
assert.match(css, /font-variant-numeric: tabular-nums/, '表格数字必须等宽');
assert.match(css, /position: sticky[\s\S]*?inset-block-start: 0/, '表头必须吸顶');
assert.match(css, /max-block-size: min\(68vh, 760px\)/, '长表必须可滚动而不是无声裁切');
assert.match(css, /scrollbar-gutter: stable/, '滚动区必须保留稳定滚动条');
assert.match(css, /\.pbr-empty-icon \{ inline-size: 44px; block-size: 44px/, '首页空态图标必须缩小');
assert.match(css, /\.ds-split::after, #content \.ds-pool::before, #content \.ds-pool::after \{ display: none; \}/, '数据源图必须去掉 T 形分叉与箭头');
assert.match(css, /\.pb-coach-hero-light[\s\S]*?background: var\(--ui-surface\) !important/, '教练页必须使用浅色表面');
assert.match(css, /\.pc-page \{[^}]*--pca: #2166c7[^}]*--pcb: #c0392b/, '选手对比必须左蓝右红');
assert.match(css, /\.sh-status-details[\s\S]*?\.sh-auto/, '数据源状态说明必须折叠且保留自动刷新说明');
assert.match(css, /\.hc-color-legend[\s\S]*?\.hc-cell-lead/, '英雄对比必须有文字图例与非颜色领先标识');
assert.match(css, /\.thd-no-change :is\(\.thd-table-head, \.thd-row\)/, '本队英雄无环比时必须移除空列');
assert.match(css, /\.bps-debug > summary/, 'BP 演示入口必须使用可键盘操作的折叠说明');
assert.match(css, /\.arch-id-more-menu[\s\S]*?position: absolute/, '选手危险操作必须收进弹出菜单');
assert.match(css, /\.ttn-timeline-scroll[\s\S]*?overflow: auto/, '交手记录必须可滚动');
assert.match(css, /forced-colors: active/, '强制颜色模式必须可读');
assert.match(css, /prefers-reduced-motion: reduce/, '减少动态效果偏好必须生效');
assert.match(css, /--ui-info: #2166c7[\s\S]*?--ui-info-soft: #e8f0fb/, '同步中 pill 必须定义信息色令牌');
assert.match(css, /:root\[data-theme="dark"\][\s\S]*?--ui-info: #8db9f2[\s\S]*?--ui-info-soft: #24344f/, '深色主题必须有信息色令牌');
assert.match(css, /@media \(max-width: 620px\)[\s\S]*?#app #content :is\(\.control, button\.primary, \.primary\):not\(\.report-page \*, dialog \*\) \{ padding-inline: 11px !important; \}/,
  '窄屏控件 padding 必须覆盖历史 important 规则');
assert.match(css, /\.cp-page \.cp-strength\[hidden\]/, '组合池隐藏字段集不得被 display 规则重新显示');
assert.match(health, /openSources\.has\(node\.closest\('\[data-source\]'\)\?\.dataset\.source\)/,
  '数据源轮询重绘必须恢复用户展开的状态说明');
assert.doesNotMatch(health, /setInterval\(/, '数据源轮询不能混用 timeout 与 interval');
assert.match(health, /pending \? 3000 : 30000/, '同步结束后必须恢复 30 秒空闲轮询');
assert.doesNotMatch(rhythm, /\.pf-lane-filter, \.tb-seg, \.sh-summary/, '状态摘要不能跟页签一起被等分成窄列');
assert.match(rhythm, /#app #content \.sh-summary > \* \{[\s\S]*?flex: 0 1 auto !important/, '状态计数必须按文字宽度排布并换行');
assert.match(desk, /@media \(max-width: 620px\)[\s\S]*?\.desk-crumb \{ display: none; \}/,
  '窄屏顶栏面包屑必须隐藏，避免竖排文字压住搜索框和板块切换');
assert.match(html, /line-rhythm\.css\?v=20261128ui6/, '线条感样式必须带新版本戳');
assert.match(html, /training-desk\.css\?v=20261128ui6/, '顶栏样式必须带新版本戳');

assert.equal((docs.match(/<h1>/g) || []).length, 1, '文档页只能有一个 h1');
assert.match(docs, /<h2>\$\{esc\(chapter\.title\)\}<\/h2>/, '章节标题必须降为 h2');
assert.match(docs, /role="region" aria-label="错误码索引"/, '错误码表必须提供可滚动命名区域');
assert.match(docs, /<caption class="visually-hidden">/, '错误码表必须有语义标题');
assert.match(sources, /<h1>数据源展示<\/h1>/, '数据源页必须有统一 h1');
assert.match(sources, /空池与断链分开显示/, '数据源页必须解释空池与断链');

console.log('ui system: all assertions passed');
