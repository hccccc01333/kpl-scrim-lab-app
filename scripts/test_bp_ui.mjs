/** BP 工作台 UI 回归：node scripts/test_bp_ui.mjs */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { bpRuleLabel } from '../v3/public/bp-studio.js';

assert.equal(bpRuleLabel('draft-20'), 'KPL 20 手（每方 5 Ban）');
assert.equal(bpRuleLabel('draft-18'), '训练赛 18 手（每方 4 Ban）');
assert.equal(bpRuleLabel('rank-20'), '排位 / 巅峰 20 手');

const source = await readFile(new URL('../v3/public/bp-studio.js', import.meta.url), 'utf8');
assert.match(source, /<h1>BP 工作台<\/h1>/);
assert.match(source, /bps-hero-desc/);
assert.match(source, /从英雄优先级到赛前方案/);
assert.match(source, /bps-prefix-group-label">BP 顺序 · \$\{esc\(bpRuleLabel\(state\.rule\)\)\}/);
assert.doesNotMatch(source, /当前营地数据是排位\/巅峰（rank-20）/);
assert.doesNotMatch(source, />\s*载入模拟数据</);

const demoLabels = source.match(/data-bps-demo[\s\S]{0,180}?查看模拟数据（仅演示）/g) || [];
assert.equal(demoLabels.length, 2);
assert.match(source, /<details class="bps-debug">/);
assert.match(source, /模拟数据只用于验证界面，不计入真实统计/);
assert.match(source, /bps-empty bps-empty-compact bps-unavailable/);
assert.match(source, /<div class="bps-empty bps-empty-compact">/);
assert.match(source, /function unavailableState[\s\S]*?\$\{heroBandShell\(\)\}[\s\S]*?bps-unavailable/,
  '无数据空态也必须保留统一页头');
assert.match(source, /function errorState[\s\S]*?\$\{heroBandShell\(\)\}[\s\S]*?bps-empty/,
  '读取失败空态也必须保留统一页头');
assert.doesNotMatch(source, /style="margin-top:40px"/);

console.log('BP UI: all assertions passed');
