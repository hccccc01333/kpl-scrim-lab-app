/** Pure contract tests: no service, private data, browser, or package dependency. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../v3/public/gallery-view.js', import.meta.url), 'utf8');
const { averageEconomy, renderGallery } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

// A densely sampled game must have the same weight as a sparse game in the same time bucket.
const curve = averageEconomy({ matches: [
  { points: [[30, 100], [31, 100], [32, 100], [60, 200]] },
  { points: [[30, 300], [60, 400]] },
] });
assert.deepEqual(curve, { points: [[30, 200], [60, 300]], games: 2 });
assert.deepEqual(averageEconomy({ matches: [{ points: [[-30, 1], [0, null], [60, NaN]] }] }), { points: [], games: 0 });
assert.deepEqual(averageEconomy(undefined), { points: [], games: 0 });

// A tail seen in one of four games cannot be presented as their average trend.
const tail = averageEconomy({ matches: [
  { points: [[0, 0], [30, 100], [600, 9000]] },
  { points: [[0, 0], [30, 200]] },
  { points: [[0, 0], [30, 300]] },
  { points: [[0, 0], [30, 400]] },
] });
assert.deepEqual(tail.points, [[0, 0], [30, 250]]);

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const ctx = { esc, fmt: String, icon: () => '', chart: () => '<svg></svg>' };
const data = {
  period: { from: '2026-11-02', to: '2026-11-08' },
  coverage: { games: 0 }, // Replays can be absent while final-panel matches are present.
  record: { wins: 15, losses: 16, decided: 31, unknown: 0, form: [{ date: '2026-11-05', result: 'win', opponent: '<img src=x onerror=alert(1)>' }] },
};
const rendered = renderGallery({ data }, ctx);
assert.match(rendered.cover, /<b>31<\/b><small>局/);
assert.match(rendered.cover, /近 1 局/);
assert.doesNotMatch(rendered.cover, /<img src=x/);
assert.match(rendered.cover, /&lt;img src=x/);
assert.match(renderGallery({ data: {} }, ctx).cover, /<b>—<\/b>/);
assert.match(renderGallery({ data, galleryError: true }, ctx).evidence, /data-pbr-retry/);
console.log('gallery view: sampling weight, partial tails, missing data, panel counts, escaping, and recovery passed');
