/**
 * Static/synthetic regression checks for analyst homepage routes.
 * Run: node scripts/test_workspace_home.mjs
 * No live service, local training files or external packages required.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../v3/public/workspace-home.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../v3/public/workspace-home.css', import.meta.url), 'utf8');
const index = readFileSync(new URL('../v3/public/index.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');
const { renderWorkspaceHome } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[c]);
const helpers = {
  esc: escape,
  fmt: (value) => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—',
  pct: (value) => Number.isFinite(value) ? value.toFixed(1) + '%' : '—',
  time: (value) => Number.isFinite(value) ? Math.floor(value / 60) + ':' + String(Math.floor(value % 60)).padStart(2, '0') : '—',
  portrait: (name) => '<span class="portrait">' + escape(name) + '</span>',
  route: (key, value = '') => '#' + key + (value ? '/' + encodeURIComponent(value) : ''),
  icon: (name) => '<svg data-icon="' + name + '"></svg>',
  chart: () => '<div class="chart-wrap">chart</div>',
  score: () => '3 <span>:</span> 2',
  resultName: { win: '胜利', loss: '失利' },
  sides: { blue: '蓝方', red: '红方' },
  filters: { from: '', to: '', validation: false },
};

const sample = {
  summary: {
    matches: 2, decided: 2, wins: 1, teamName: '测试战队',
    coverage: { timelineMatches: 1 },
    topHeroes: [{ hero: '鲁班七号', picks: 2, positions: ['发育路'] }],
  },
  matches: [
    { key: 'test-1', date: '2026-11-12', duration: 750, opponent: '对手队伍',
      result: 'win', ownCamp: 'blue', heroes: ['鲁班七号'] },
  ],
  team: {},
  process: { matches: [] },
};

for (const data of [sample, {
  summary: { matches: 0, coverage: {} }, matches: [], team: {}, process: { matches: [] },
}]) {
  const html = renderWorkspaceHome(data, helpers);
  const targets = [...html.matchAll(/href="([^"]+)"/g)].map(match => match[1]);
  const allowed = new Set([
    'ingest','match','matches','tempo','heroes','decision','pending','plan',
    'sources','cross','bpcounter','opponents','playerarchive','reports',
  ]);
  assert(targets.length >= 20, 'Homepage should have real routes on all major cards');
  for (const href of targets) {
    assert(href.startsWith('#'), 'Internal homepage target must use SPA hash routing: ' + href);
    assert(allowed.has(href.slice(1).split('/')[0]), 'Target does not match a registered route: ' + href);
  }
  for (const key of ['ingest','decision','cross','bpcounter','opponents','playerarchive','plan','reports']) {
    assert(html.includes('data-wh-target="' + key + '"'), 'Work entry missing: ' + key);
  }
  assert(html.includes('id="home-decision"'), 'Async decision briefing mount point must survive');
  assert(html.includes('data-wh-inbox-count'), 'Live pending work must have a mount point');
  assert(html.includes('class="wh-spotlight wh-link"'), 'Latest match card must be entirely clickable');
  assert(!html.includes('href=""'), 'No empty navigation targets');
}
assert(index.includes('static/workspace-home.css'), 'Homepage stylesheet must load');
assert(app.includes("import { renderWorkspaceHome }"), 'App must import the homepage module');
assert(css.includes('text-decoration: none !important'), 'Homepage must suppress text underlines');
assert(css.includes('focus-visible'), 'Keyboard focus must remain visible despite hidden underlines');
console.log('workspace homepage checks passed');
