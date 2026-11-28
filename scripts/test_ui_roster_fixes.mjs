import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createPlayers } from '../v3/public/players-page.js';
import { createPlayerCompare } from '../v3/public/player-compare.js';
import { render as renderMetrics } from '../v3/public/metrics-observe.js';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const esc = (value) => String(value ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const fmt = (value, digits = 0) => Number.isFinite(Number(value))
  ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
  : '—';
const pct = (value) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : '—';

globalThis.location = { hash: '' };
globalThis.document = {
  addEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

/* 选手档案：高危动作默认收起，头像/数据态/表头单位使用稳定结构。 */
const players = createPlayers({
  esc, fmt, pct, diff: fmt, portrait: () => '',
  block: () => '', empty: (message) => `<div class="empty">${esc(message)}</div>`, reload() {},
});
const archiveBoard = {
  summary: { teamName: 'KK' },
  players: [{
    name: '花沋', memberId: 'player-b', side: 'own', lane: '发育路', games: 10,
    wins: 6, decided: 10, mvp: 1, kda: 3.25, score: 61.5, winRate: 60,
    participation: 22, damageShare: 31,
  }],
  games: [],
};
const archive = players.archivePage(archiveBoard, {
  teams: [{ id: 'team-kk', name: 'KK' }],
  players: [
    { id: 'player-a', name: 'KK', teamId: 'team-kk', teamName: 'KK', position: '打野' },
    { id: 'player-b', name: '花沋', teamId: 'team-kk', teamName: 'KK', position: '发育路' },
  ],
});
assert.match(archive, /<details class="arch-id-more">/, '选手次要操作必须使用可展开菜单');
assert.match(archive, /<summary class="arch-id-more-trigger" aria-label="更多选手操作">/, '次级菜单需要可访问名称');
assert.equal((archive.match(/data-pa-id-delete=/g) || []).length, 2, '每名选手保留一个删除入口');
const detailsAt = archive.indexOf('<details class="arch-id-more">');
const deleteAt = archive.indexOf('data-pa-id-delete=');
assert.ok(detailsAt >= 0 && deleteAt > detailsAt, '删除按钮必须位于次级菜单内，不能红色常显');
assert.match(archive, /pl-ava player-avatar arch-id-mark/, '档案头像必须走统一头像规则');
assert.match(archive, /data-pa-data-state="ready"/, '有关联数据的选手要有 ready 圆点状态');
assert.match(archive, /data-pa-data-state="empty"/, '未关联数据的选手要有 empty 圆点状态');
assert.match(archive, /class="arch-id-state-dot"/, '数据状态必须使用圆点类');
const playersSource = read('v3/public/players-page.js');
assert.match(playersSource, /window\.confirm\(`删除选手ID/, '删除必须保留二次确认');
assert.match(playersSource, /\/api\/v3\/identity\/players\/delete/, '删除 API 口径不能改变');
assert.match(playersSource, /局数（局）/, '表格局数要带单位');
assert.match(playersSource, /胜率（%）/, '表格胜率要带单位');
assert.match(playersSource, /参团率（%）/, '表格参团率要带单位');
assert.match(playersSource, /role="table" aria-label="选手数据列表"/, '列表视图要有表头语义');
globalThis.location.hash = 'before-summary-click';
const summaryTarget = {
  closest(selector) {
    if (selector === '[data-pl-goto]') return { dataset: { plGoto: 'player-b' } };
    if (selector === 'button, a, summary') return {};
    return null;
  },
};
assert.equal(players.click({ target: summaryTarget }), false, '更多操作 summary 不应被整卡跳转拦截');
assert.equal(globalThis.location.hash, 'before-summary-click', '展开更多操作时不得跳转选手详情');

/* 选手对比：结论只出现一次，格式为「名称 实际指标比分 名称」。 */
const compare = createPlayerCompare({ esc });
const compareBoard = {
  identity: { members: [
    { id: 'player-a', name: 'KK', label: 'KK' },
    { id: 'player-b', name: '花沋', label: '花沋' },
  ] },
  players: [
    { name: 'KK', memberId: 'player-a', side: 'own', lane: '', games: 10, wins: 6, decided: 10,
      winRate: 60, kda: 5, gpm: 600, dpm: 500, participation: 20, damageShare: 30,
      goldShare: 25, takenShare: 20, dtpm: 1000, score: 70, heroes: [], recent: [] },
    { name: '花沋', memberId: 'player-b', side: 'own', lane: '', games: 10, wins: 5, decided: 10,
      winRate: 50, kda: 4, gpm: 500, dpm: 600, participation: 25, damageShare: 25,
      goldShare: 25, takenShare: 20, dtpm: 900, score: 65, heroes: [], recent: [] },
  ],
  games: [],
  opponents: [],
};
const compareHtml = compare.render(compareBoard);
assert.match(compareHtml, /class="pc-score-name a">KK<\/span><b class="pc-score" data-pc-score-a="4" data-pc-score-b="2">4:2<\/b><span class="pc-score-name b">花沋<\/span>/,
  '结论必须使用 KK 4:2 花沋 的实际指标比分');
assert.equal((compareHtml.match(/4:2/g) || []).length, 1, '同一比分不能在页头重复三次');
assert.doesNotMatch(compareHtml, /位置指标领先项/, '旧的重复结论文案必须移除');
assert.match(compareHtml, /<nav class="hc-index pc-steps" aria-label="分析步骤">/, '步骤导航要使用紧凑结构');
assert.equal((compareHtml.match(/data-pc-jump=/g) || []).length, 4, '四个分析步骤要保留');
assert.match(compareHtml, /pc-mono player-avatar/, '对比头像必须走统一头像规则');
assert.match(compareHtml, /蓝方 · 选手 A/, '对比左侧必须明确为蓝方');
assert.match(compareHtml, /红方 · 选手 B/, '对比右侧必须明确为红方');

/* 战队/交手记录：长列表有滚动结构与可见提示，右栏按日分组并有搜索空态。 */
const featuresSource = read('v3/public/features.js');
assert.match(featuresSource, /tb-list tb-list-scroll[^>]*tabindex="0"[^>]*role="region"/, '战队索引要有可聚焦滚动区');
assert.match(featuresSource, /class="tb-scroll-note">列表可滚动/, '战队长列表不能无声裁切');
assert.match(featuresSource, /ttn-list ttn-list-scroll[^>]*tabindex="0"/, '交手记录索引要有可聚焦滚动区');
assert.match(featuresSource, /ttn-timeline ttn-timeline-scroll[^>]*tabindex="0"/, '交手记录时间线要有可聚焦滚动区');
assert.match(featuresSource, /ttn-day-group/, '交手记录要按日分组');
assert.match(featuresSource, /data-ttn-empty hidden[\s\S]*没有匹配的对手/, '搜索无结果要有明确空态');
assert.match(featuresSource, /emptyState\.hidden = items\.length === 0 \|\| shown > 0/,
  '空库不显示搜索空态，有库无匹配时才显示');
assert.match(featuresSource, /class="ttn-description"/, '说明文字要有局部可读样式类');

/* 指标观察：分路有明确默认项，已选对象有头像，警示贴近数据源。 */
const metricsHtml = renderMetrics();
assert.match(metricsHtml, /<option value="" selected>全部分路<\/option>/, '分路下拉必须有默认/占位项');
assert.doesNotMatch(metricsHtml, /mo-warn-note/, '警示条不能继续漂浮在对比对象面板头部');
const metricsSource = read('v3/public/metrics-observe.js');
assert.match(metricsSource, /mo-source-control[\s\S]*data-mo-source aria-describedby="\$\{uid\}-source-note-0"[\s\S]*mo-source-note/, '警示条要紧邻数据源控件并被其描述');
assert.match(metricsSource, /\$\{mono\(p\.name\)\}<span>\$\{esc\(p\.name\)\}<\/span>/, '已选对比对象必须显示头像而不是灰占位');
assert.match(metricsSource, /mo-ava player-avatar/, '指标观察头像必须走统一头像规则');

console.log('UI roster fixes: all assertions passed');
