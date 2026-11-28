/* Focused regressions for the audited workbench UI fixes (task-8).
 * Run: node scripts/test_overview_ui_workbench_fixes.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const source = (name) => readFileSync(new URL(`v3/public/${name}`, root), 'utf8');
const periodSource = source('period-brief.js');
const { renderBrief } = await import('data:text/javascript;base64,' + Buffer.from(periodSource).toString('base64'));
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const ctx = { esc, icon: () => '', fmt: (value) => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—' };
const emptyData = { available: false, period: { kind: 'week', label: '本周', rangeLabel: '11-09 ~ 11-15', prev: { label: '上周同期', rangeLabel: '11-02 ~ 11-08' } } };
const empty = renderBrief({ kind: 'week', data: emptyData }, ctx);
assert(empty.includes('pbr-empty--compact'), 'overview empty state must be compact');
assert(empty.includes('pbr-empty-support') && empty.includes('pbr-shortcut-grid'), 'overview empty state must offer explicit next steps');
for (const route of ['#matches', '#matching', '#series-builder', '#ingest']) assert(empty.includes(`href="${route}"`), `empty state missing shortcut ${route}`);
assert(empty.includes('pbr-filter-label">周期') && empty.includes('pbr-filter-label">视角'), 'period and view filters must be visibly grouped');
assert(empty.includes('11-09 ~ 11-15') && empty.includes('对比上周同期 11-02 ~ 11-08'), 'period range and comparison must remain explicit');

const competitions = source('competitions.js');
assert((competitions.match(/class="comp-stat-card"/g) || []).length === 3, 'competition summary must render three stat cards');
assert(competitions.includes('comp-card--fill'), 'competition cards must be able to fill the viewport');
assert(!competitions.includes('class="comp-carousel-markers"'), 'competition carousel must keep only one pagination scheme');
assert(competitions.includes('comp-table-wrap--archive') && competitions.includes('comp-table-actions'), 'archive table and actions need alignment hooks');

const team = source('team-profile.js');
assert(team.includes('tp-head--clean'), 'team profile must not repeat its own kicker/title');
assert(team.includes('<button type="button" class="tp-person is-empty" data-tp-edit'), 'pending staff must be an actionable add button');
assert(team.includes('添加姓名') && team.includes('tp-person is-filled'), 'staff card states need distinct copy and hierarchy');

const matching = source('matching-page.js');
assert(matching.includes('mb-head--icon-safe') && matching.includes('mb-title-icon'), 'matching title icon needs a local safe box');
assert(matching.includes('待复核账号') && matching.includes('账号 ${esc(rule.playerId)}'), 'matching UI must not mix unexplained ID labels');
assert(matching.includes('mb-status--text'), 'matching state needs a textual status hook');

const series = source('series-builder.js');
assert(series.includes('<details class="sb-help">'), 'series instructions must collapse into help');
assert(series.includes('sb-faces--large') && series.includes('sb-row-lineup--wrap'), 'series hero faces need larger wrapping layout');
assert(series.includes('sb-day-progress') && series.includes('role="progressbar"'), 'series progress must sit with counts and expose text semantics');

const notes = source('match-notes.js');
assert(notes.includes('mn-empty--clear') && notes.includes('从页面上方的新增入口'), 'note empty state must be explicit without a duplicate add button');
assert(notes.includes('mn-note-action') && notes.includes('mn-add--large'), 'note icon actions need larger hit areas');
assert.equal((notes.match(/<button[^>]*data-mn-page-add/g) || []).length, 1, 'standalone notes page must keep exactly one add entry');
const groupHeadBlock = notes.slice(notes.indexOf('const groupHead'), notes.indexOf('list.innerHTML = keys.length'));
assert(!groupHeadBlock.includes('data-mn-add'), 'standalone note groups must not repeat the add entry');

const { createResearch } = await import(new URL('v3/public/research.js', root));
const research = createResearch({
  esc, fmt: (value) => String(value ?? '—'), icon: () => '',
  table: () => '<table></table>', pageIntro: (title) => `<h1>${esc(title)}</h1>`,
});
const reports = research.reports({ reports: [] });
assert(reports.includes('sx-report-stat'), 'report hero must render stat cards');
assert(reports.includes('还没有保存的报告') && reports.includes('第一份报告生成后会自动保存到这里'), 'empty report library needs a first-report guide');
assert(reports.includes('sx-week-focus-icon--large'), 'report configuration icons need larger hit areas');

const biggame = source('biggame-page.js');
assert(biggame.includes('function scoreHtml('), 'big game list/detail must share one score template');
assert(biggame.includes('bgx-team-foot--primary') && biggame.includes('已完赛 ${us}:${them} · 查看复盘'), 'big game needs a solid entry action and completed state');

const cross = source('cross-page.js');
assert(cross.includes('xw-trend-value') && cross.includes('xw-trend-date') && cross.includes('xw-trend-baseline'), 'cross trend bars need dates, net values and zero baseline');
assert(cross.includes('xw-tabs--compact') && cross.includes('xw-sec-head--grouped'), 'cross tabs and module sections need compact hierarchy');
assert(cross.includes('xw-mod-note--contained'), 'cross metric notes must stay attached to their module');

const capture = source('capture-page.js');
assert(!capture.includes('capv-next-num'), 'ingest hero must not show a giant step watermark');
assert(capture.includes('capv-next-side--compact') && !capture.includes('capv-connection-status'), 'ingest authorization issue/CTA must be consolidated in the hero');
assert(capture.includes('capv-page--aligned') && capture.includes('capv-context'), 'ingest breadcrumb/title context must be explicit');
assert(capture.includes('${fmt(autoPassed)} <em>局</em>') && capture.includes('${fmt(needReview)} <em>条</em>'), 'ingest count units must be consistently spaced');

const app = source('app.js');
assert(app.includes('archive-columns') && app.includes('archive-list-head--scroll'), 'archive list needs headers and non-truncated sort controls');
assert(app.includes('archive-side--reveal') && app.includes('archive-result--quiet'), 'archive inline tools/badges must be de-emphasized');
assert(app.includes('opp-page--centered') && app.includes('opp-team-grid--balanced'), 'opponent layout needs centered balanced columns');
assert(app.includes('opp-player-role') && app.includes('opp-lane-add'), 'opponent role/add controls need clear placement');

const features = source('features.js');
assert(features.includes('REASONS.filter((name) => stats.counts[name] > 0)'), 'zero-count focus filters must be hidden');
assert(features.includes('fmx-row--card') && features.includes('fmx-evidence primary'), 'featured result rows need card layout and solid primary action');
assert(features.includes('fmx-search'), 'featured search needs a narrow width hook');

console.log('ui workbench fixes: all assertions passed');
