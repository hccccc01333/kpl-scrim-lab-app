/** 赛后笔记不暴露裸对局号回归：node scripts/test_match_notes_no_raw_id.mjs */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const js = readFileSync(new URL('../v3/public/match-notes.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../v3/public/app.js', import.meta.url), 'utf8');

assert.doesNotMatch(js, /<small>\$\{esc\(key\)\}<\/small>/, '分组头不得把 channel key 当副标题');
assert.doesNotMatch(js, /title="打开这一局的复盘（\$\{esc\(key\)\}）"/, '链接 title 也不得暴露 key');
assert.match(js, /const detail = \[m\?\.matchType/, '副标题要做成赛制/时间/训练组');
assert.match(js, /第 \$\{index \+ 1\} 局/, '同日多局用序号而不是 ID 尾号区分');
assert.doesNotMatch(js, /const tail = String\(match\.key/, '对局选择项不得再截 key 尾号');
assert.match(app, /match-notes\.js\?v=20261127noid1/, '模块版本戳必须更新');

console.log('match notes no raw id: all assertions passed');
