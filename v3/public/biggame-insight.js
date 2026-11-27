/* 大场分析 · 单场页的可见层（2026-11 重做 v2）
 *
 * 只做「数据 → 版面」；口径、分母、模型质量都在 series_insight / series_engine，
 * 前端不重算结论。
 *
 * 设计约束（赛训组反馈）：
 * - 每个模块开头一句人话标题，标题里带关键数字；
 * - 一屏只回答一个问题，先结论后证据；
 * - 局次一律「第一把…第七把」；
 * - 缺失显示「—」并注明覆盖局数，不补 0、不画空图；
 * - 不再出现选手状态；不再用三个小圆环叠在一起表达 BP。
 */

import { glyph } from './ui-icons.js';

const LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
const LANE_SHORT = { 对抗路: '对抗', 打野: '打野', 中路: '中路', 发育路: '发育', 游走: '游走' };
const PHASE_KEYS = ['early', 'mid', 'late'];
const PHASE_TABS = [
  ['early', '0–4 分', '对线'],
  ['mid', '4–10 分', '发育'],
  ['late', '10 分后', '决胜'],
  ['all', '全场', '汇总'],
];
const GAME_WORDS = ['第一把', '第二把', '第三把', '第四把', '第五把', '第六把', '第七把'];
const DRAGON_ORDER = ['暴君', '主宰', '暗影暴君', '暗影主宰', '风暴龙王'];
const BASE_MODES = [['prev', '上一场同赛制'], ['d3', '近 3 天'], ['d7', '近 7 天'],
  ['d30', '近 30 天'], ['format', '同赛制历史']];
const DRAFT_SCHEDULE = (() => {
  const slots = [];
  for (let i = 0; i < 5; i += 1) slots.push(['ban', 'own'], ['ban', 'foe']);
  const picks = [['own'], ['foe'], ['foe'], ['own'], ['own'], ['foe'], ['foe'], ['own'], ['own'], ['foe']];
  return slots.concat(picks.map(([side]) => ['pick', side]));
})();
export const gameWord = (index) => GAME_WORDS[(Number(index) || 1) - 1] || `第${Number(index) || 1}把`;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

function num(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function fmtSigned(value, digits = 0) {
  if (!num(value)) return '—';
  const abs = digits ? Math.abs(value).toFixed(digits) : Math.round(Math.abs(value)).toLocaleString('zh-CN');
  return `${value < 0 ? '−' : '+'}${abs}`;
}

function fmtNumber(value) {
  if (!num(value)) return '—';
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded)
    ? rounded.toLocaleString('zh-CN')
    : rounded.toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function localHelpers(h) {
  const { esc, fmt } = h;
  const gold = (v, digits = 0) => (num(v) ? fmt.signed(v, digits) : '—');
  const pct1 = (v, digits = 1) => (num(v) ? `${Number(v).toFixed(digits)}%` : '—');
  const count = (v) => (num(v) ? fmt.count(v) : '—');
  const fixed = (v, digits = 1) => (num(v) ? fmt.fixed(v, digits) : '—');
  const duration = (v) => (num(v) && v > 0 ? fmt.duration(v) : '—');
  const resultWord = (result) => (result === 'win' ? '胜' : result === 'loss' ? '负' : '—');
  const resultCls = (result) => (result === 'win' ? 'is-win' : result === 'loss' ? 'is-loss' : '');
  return { esc, gold, pct1, count, fixed, duration, resultWord, resultCls };
}

function emptyState(text) {
  return `<div class="bgx-empty-inline">${text}</div>`;
}

function cardHead(esc, kicker, title, lede, meta = '') {
  /* 标题下不再摆说明小字：口径限制收成带图标的角标，操作靠控件本身自解释。 */
  const scope = lede
    ? `<span class="bgx-card-scope" title="${esc(lede)}">${glyph('warning', { label: '数据口径', size: 16 })} 口径</span>`
    : '';
  return `<div class="bgx-card-head">
    <div class="bgx-card-head-copy">
      <span class="bgx-kicker">${esc(kicker)}</span>
      <h2 class="bgx-card-title">${title}</h2>
    </div>
    ${meta || scope ? `<div class="bgx-card-meta">${scope}${meta}</div>` : ''}
  </div>`;
}

function avatar(h, name, cls = '') {
  if (typeof h.portrait === 'function') return h.portrait(name || '', cls);
  return `<span class="portrait portrait-placeholder ${cls}">${(name || '?')[0]}</span>`;
}

function heroChip(h, hero, sub = '', tone = '') {
  const { esc } = h;
  if (!hero) return '';
  return `<span class="bgv-hero ${tone}">${avatar(h, hero, 'bgv-hero-img')}
    <b>${esc(hero)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</span>`;
}

function selectBase(ui, attr = 'data-bgv-base') {
  const current = BASE_MODES.some(([key]) => key === ui.baseMode) ? ui.baseMode : 'format';
  return `<label class="bgx-field bgv-select"><span>时间窗</span>
    <select class="bgx-select" ${attr}>${BASE_MODES.map(([key, label]) =>
      `<option value="${key}"${key === current ? ' selected' : ''}>${label}</option>`).join('')}</select>
  </label>`;
}

/* ── 01 总览：指标板 ───────────────────────────────────────── */
const VIEW_MODES = [['games', '逐局'], ['win', '赢局平均'], ['loss', '输局平均']];
const VIEW_WORD = { games: '整场', win: '赢局', loss: '输局' };
const NA_TEXT = { 'no-replay': '缺回放', 'not-triggered': '本局未触发', 'no-base': '无历史基准' };
/* 单元格里只放得下短标签；完整解释留在 title 和表下图例。 */
const NA_SHORT = { 'no-replay': '缺回放', 'not-triggered': '未触发', 'no-base': '无基准' };
const VERDICT_LABEL = {
  firstBlood: '一血', firstTower: '首塔', at10: '10 分钟经济', towers: '推塔',
  fightRate: '团战胜率', cut: '切 C', cutJungle: '打野切 C', cutSuffered: '被切 C',
};

/* 画图只消费后端已经算好的逐局值，不在这里重新算指标口径。 */
function plotValue(metric, cell) {
  if (cell === null || cell === undefined) return null;
  if (metric.kind === 'flag') return num(cell) ? 1 : 0;
  if (metric.kind === 'pair') {
    if (!num(cell.own) || !num(cell.foe)) return null;
    const total = cell.own + cell.foe;
    return total > 0 ? cell.own / total * 100 : 50;
  }
  return num(cell) ? cell : null;
}

function wholeFor(metric, view) {
  return view !== 'games' && metric.byResult?.[view] ? metric.byResult[view] : (metric.series || {});
}

function wholeNumber(metric, view) {
  const whole = wholeFor(metric, view);
  return metric.kind === 'num' ? whole.value : (num(whole.rate) ? whole.rate : whole.value);
}

function deltaFor(metric, mode, view) {
  const base = (metric.base || {})[mode];
  const current = wholeNumber(metric, view);
  return num(base) && num(current) ? current - base : null;
}

function deltaText(metric, delta) {
  const digits = metric.kind === 'num' && metric.unit === 'gold' ? 0 : 1;
  /* 赛训组口径：对比列写百分号，数值不变（19.4pp → 19.4%）。
     底层仍是「当前值 − 基准值」的百分点差，只把展示单位改成 %。 */
  const unit = metric.kind === 'num' ? (metric.unit === 'gold' ? '' : ' 次') : '%';
  const abs = digits ? Math.abs(delta).toFixed(digits) : Math.round(Math.abs(delta)).toLocaleString('zh-CN');
  return `${delta > 0 ? '↑' : '↓'} ${abs}${unit}`;
}

/* 对比列收敛成一枚胶囊：只看方向和幅度，基准值放进表头标签里。 */
function deltaPill(metric, delta, title = '') {
  if (!num(delta)) return `<span class="bgv-delta is-na" title="没有可用的历史基准">— 无基准</span>`;
  const digits = metric.kind === 'num' && metric.unit === 'gold' ? 0 : 1;
  const rounded = digits ? Number(Math.abs(delta).toFixed(digits)) : Math.round(Math.abs(delta));
  if (!rounded) return `<span class="bgv-delta is-flat">持平</span>`;
  const good = (delta > 0) !== !!metric.reverse;
  return `<span class="bgv-delta ${good ? 'is-good' : 'is-bad'}" title="${title}">${deltaText(metric, delta)}</span>`;
}

function naCell(reason) {
  const key = reason || 'not-triggered';
  const short = NA_SHORT[key] || '无数据';
  const full = NA_TEXT[key] || NA_TEXT['not-triggered'];
  return `<span class="bgv-cell is-na" data-na="${key}" title="${full}">—<small>${short}</small></span>`;
}

function flagCell(value, reason) {
  if (!num(value)) return naCell(reason);
  const got = !!value;
  const word = got ? '拿到' : '未拿到';
  return `<span class="bgv-cell ${got ? 'is-good' : 'is-bad'}" title="${word}">${got ? '✓' : '✗'}<small>${word}</small></span>`;
}

function pairCell(value, reason) {
  if (!value || !num(value.own) || !num(value.foe)) return naCell(reason);
  const tone = value.own > value.foe ? 'is-good' : value.own < value.foe ? 'is-bad' : '';
  return `<span class="bgv-cell ${tone}"><b>${fmtNumber(value.own)}</b><i>:</i><b>${fmtNumber(value.foe)}</b></span>`;
}

function numberCell(value, reverse, reason) {
  if (!num(value)) return naCell(reason);
  const tone = value === 0 ? '' : (value > 0) !== reverse ? 'is-good' : 'is-bad';
  return `<span class="bgv-cell ${tone}"><b>${fmtSigned(value)}</b></span>`;
}

function pctCell(value, reason) {
  if (!num(value)) return naCell(reason);
  const tone = value >= 55 ? 'is-good' : value <= 45 ? 'is-bad' : '';
  return `<span class="bgv-cell ${tone}"><b>${Math.round(value)}%</b></span>`;
}

function cellFor(metric, value, reason) {
  if (metric.kind === 'flag') return flagCell(value, reason);
  if (metric.kind === 'pair') return pairCell(value, reason);
  if (metric.kind === 'pct') return pctCell(value, reason);
  return numberCell(value, metric.reverse, reason);
}

/* 赢局 / 输局视角只画一列聚合值，不把赢下的那几局又铺开一遍。 */
function aggregateCell(metric, view) {
  const w = wholeFor(metric, view);
  if (metric.kind === 'flag') {
    return num(w.rate) ? `<span class="bgv-cell ${w.rate >= 55 ? 'is-good' : w.rate <= 45 ? 'is-bad' : ''}">
      <b>${Math.round(w.rate)}%</b><small>${w.own || 0}/${w.n || 0}</small></span>` : naCell('not-triggered');
  }
  if (metric.kind === 'pair') {
    return num(w.own) && num(w.foe)
      ? `<span class="bgv-cell ${w.own > w.foe ? 'is-good' : w.own < w.foe ? 'is-bad' : ''}">
        <b>${fmtNumber(w.own)} : ${fmtNumber(w.foe)}</b><small>控制 ${num(w.rate) ? `${Math.round(w.rate)}%` : '—'}</small></span>`
      : naCell('not-triggered');
  }
  if (metric.kind === 'pct') {
    return num(w.value) ? `<span class="bgv-cell ${w.value >= 55 ? 'is-good' : w.value <= 45 ? 'is-bad' : ''}">
      <b>${Math.round(w.value)}%</b><small>${w.n || 0} 局</small></span>` : naCell('not-triggered');
  }
  return num(w.value) ? `<span class="bgv-cell ${(w.value > 0) !== !!metric.reverse ? 'is-good' : 'is-bad'}">
    <b>${metric.unit === 'gold' ? fmtSigned(w.value) : fmtNumber(w.value)}</b><small>${w.n || 0} 局</small></span>`
    : naCell('not-triggered');
}

function seriesFor(metric, view) {
  const s = wholeFor(metric, view);
  if (metric.kind === 'flag') {
    if (!num(s.n) || !s.n) return '—';
    return `<b>${s.own}/${s.n}</b><small>${num(s.rate) ? `${Math.round(s.rate)}%` : '—'} · ${VIEW_WORD[view]}值</small>`;
  }
  if (metric.kind === 'pair') {
    if (!num(s.own) || !num(s.foe)) return '—';
    return `<b>${fmtNumber(s.own)} : ${fmtNumber(s.foe)}</b><small>控制 ${num(s.rate) ? `${Math.round(s.rate)}%` : '—'}</small>`;
  }
  if (metric.kind === 'pct') {
    return num(s.value) ? `<b>${Math.round(s.value)}%</b><small>${s.n || 0} 局</small>` : '—';
  }
  if (!num(s.value)) return '—';
  return `<b>${metric.unit === 'gold' ? fmtSigned(s.value) : fmtNumber(s.value)}</b>
    <small>${num(s.total) ? `共 ${s.total} 次` : `${s.n || 0} 局`}</small>`;
}

/* 五张读数卡底部的迷你走势：0 为中心的方向色，缺失留空不画 0。 */
function miniSpark(values, { zero = false, pips = false } = {}) {
  if (!values.length) return '<span class="bgv-spark is-empty">—</span>';
  if (pips) {
    return `<span class="bgv-spark is-pips" aria-hidden="true">${values.map((value) =>
      `<i class="${!num(value) ? 'is-na' : value ? 'is-win' : 'is-loss'}"></i>`).join('')}</span>`;
  }
  const valid = values.filter(num);
  if (!valid.length) return '<span class="bgv-spark is-empty">—</span>';
  const width = 96;
  const height = 24;
  const mid = height / 2;
  const max = Math.max(1, ...valid.map((value) => Math.abs(value)));
  const step = width / values.length;
  const bars = values.map((value, index) => {
    if (!num(value)) return '';
    const barHeight = Math.max(1, Math.abs(value) / max * (mid - 2));
    const y = zero ? (value >= 0 ? mid - barHeight : mid) : height - barHeight;
    const cls = zero && value < 0 ? 'is-down' : 'is-up';
    return `<rect x="${(index * step + 2).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(2, step - 4).toFixed(1)}" height="${barHeight.toFixed(1)}" rx="1" class="${cls}"></rect>`;
  }).join('');
  return `<svg class="bgv-spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
    ${zero ? `<line x1="0" y1="${mid}" x2="${width}" y2="${mid}" class="bgv-spark-zero"/>` : ''}${bars}</svg>`;
}

function readoutTile(label, value, sub, tone = '', spark = '') {
  return `<div class="bgv-tile ${tone}"><span>${label}</span><b>${value}</b><small>${sub || ''}</small>${spark}</div>`;
}

function viewIndexes(games, view) {
  return games.map((_, index) => index).filter((index) => view === 'games' || games[index].result === view);
}

function overviewReadout(insight, metrics, games, view) {
  const score = (insight.summary || {}).score || {};
  const byKey = new Map(metrics.map((metric) => [metric.key, metric]));
  const indexes = viewIndexes(games, view);
  const blood = byKey.get('firstBlood');
  const at10 = byKey.get('at10');
  const towers = byKey.get('towers');
  const dragonRows = metrics.filter((metric) => metric.key.startsWith('dragon:'));
  let dragonOwn = 0;
  let dragonFoe = 0;
  const dragonSpread = indexes.map((index) => {
    let own = 0;
    let foe = 0;
    for (const metric of dragonRows) {
      const cell = metric.perGame?.[index];
      if (!cell || !num(cell.own) || !num(cell.foe)) continue;
      own += cell.own;
      foe += cell.foe;
    }
    dragonOwn += own;
    dragonFoe += foe;
    return own + foe ? own / (own + foe) * 100 - 50 : null;
  });
  const bloodWhole = blood ? wholeFor(blood, view) : {};
  const at10Whole = at10 ? wholeFor(at10, view) : {};
  const towerWhole = towers ? wholeFor(towers, view) : {};
  const resultPips = miniSpark(indexes.map((index) =>
    games[index].result === 'win' ? 1 : games[index].result === 'loss' ? 0 : null), { pips: true });
  const bloodTone = num(bloodWhole.rate) ? (bloodWhole.rate >= 55 ? 'is-good' : bloodWhole.rate <= 45 ? 'is-bad' : '') : '';
  const goldTone = num(at10Whole.value) ? (at10Whole.value > 0 ? 'is-good' : 'is-bad') : '';
  const towerTone = num(towerWhole.rate) ? (towerWhole.rate >= 55 ? 'is-good' : towerWhole.rate <= 45 ? 'is-bad' : '') : '';
  return `<div class="bgv-readout">
    ${readoutTile('大场', `${score.us ?? 0}<i>:</i>${score.them ?? 0}`, `${VIEW_WORD[view]} · ${indexes.length} 局`, '', resultPips)}
    ${readoutTile('一血', num(bloodWhole.rate) ? `${bloodWhole.own || 0}/${bloodWhole.n || 0}` : '—',
      num(bloodWhole.rate) ? `${Math.round(bloodWhole.rate)}% · ${bloodWhole.n} 局` : '无回放', bloodTone,
      blood ? miniSpark(indexes.map((index) => plotValue(blood, blood.perGame?.[index])), { pips: true }) : '')}
    ${readoutTile('中立资源', dragonOwn + dragonFoe ? `${fmtNumber(dragonOwn)} : ${fmtNumber(dragonFoe)}` : '—',
      dragonOwn + dragonFoe ? `我方占比 ${Math.round(dragonOwn / (dragonOwn + dragonFoe) * 100)}%` : '无回放', '',
      miniSpark(dragonSpread, { zero: true }))}
    ${readoutTile('10′ 经济差', num(at10Whole.value) ? fmtSigned(at10Whole.value) : '—',
      num(at10Whole.n) ? `${at10Whole.n} 局有过程` : '缺过程', goldTone,
      at10 ? miniSpark(indexes.map((index) => plotValue(at10, at10.perGame?.[index])), { zero: true }) : '')}
    ${readoutTile('推塔', num(towerWhole.own) && num(towerWhole.foe) ? `${fmtNumber(towerWhole.own)} : ${fmtNumber(towerWhole.foe)}` : '—',
      num(towerWhole.rate) ? `占 ${Math.round(towerWhole.rate)}%` : '无回放', towerTone,
      towers ? miniSpark(indexes.map((index) => {
        const cell = towers.perGame?.[index];
        return cell && num(cell.own) && num(cell.foe) ? cell.own - cell.foe : null;
      }), { zero: true }) : '')}
  </div>`;
}

/* 结论层：只拼装后端已经算好的数值，覆盖不足 3 局的差异降权，不占头条。 */
function conclusionBlock(insight, metrics, games, mode, modeLabel, esc) {
  const total = games.length;
  if (!total) return '';
  const ranked = metrics.map((metric) => {
    const delta = deltaFor(metric, mode, 'games');
    const coverage = num(metric.coverage) ? metric.coverage
      : (metric.perGame || []).filter((value) => value !== null && value !== undefined).length;
    return { metric, delta, coverage, score: num(delta) ? Math.abs(delta) * Math.min(coverage, 3) / 3 : 0 };
  }).filter((row) => num(row.delta) && row.coverage > 0)
    .map((row) => ({ ...row, good: (row.delta > 0) !== !!row.metric.reverse }))
    .sort((a, b) => b.score - a.score);
  if (!ranked.length) {
    return `<div class="bgv-conclusion is-muted"><p class="bgv-conclusion-line">本场没有${esc(modeLabel)}基准，先看下面的逐局证据。</p></div>`;
  }
  const labelOf = (row) => VERDICT_LABEL[row.metric.key] || row.metric.label;
  const notable = (row) => Math.abs(row.delta) >= (row.metric.kind === 'num' && row.metric.unit === 'gold' ? 1500 : 10);
  const phrase = (list) => `${list.map(labelOf).join('、')}${list.some(notable) ? '明显' : ''}`;
  const good = ranked.filter((row) => row.good).slice(0, 2);
  const bad = ranked.filter((row) => !row.good).slice(0, 2);
  let text;
  if (good.length && bad.length) text = `本场${phrase(good)}占优，但 ${phrase(bad)}落后。`;
  else if (good.length) text = `本场${phrase(good)}占优，其余指标与${modeLabel}接近。`;
  else text = `本场${phrase(bad)}落后，其余指标与${modeLabel}接近。`;
  text += `覆盖 ${total} 局，逐局证据见下表。`;
  const tags = ranked.slice(0, 3).map((row) =>
    `<span class="bgv-diff ${row.good ? 'is-good' : 'is-bad'}">${esc(labelOf(row))}
      <b>${deltaText(row.metric, row.delta)}</b><small>${row.coverage}/${total} 局</small></span>`).join('');
  return `<div class="bgv-conclusion" aria-label="本场结论">
    <p class="bgv-conclusion-line">${esc(text)}</p>
    <div class="bgv-diff-tags">${tags}</div>
    <p class="bgv-conclusion-note">差异标签按「偏离基准 × 覆盖局数」排序；不足 3 局的指标降权。</p>
  </div>`;
}

/* 展开层讲人话：每局一张小卡，写清第几把、胜负、数值和一条方向条，
   不再放没有坐标和单位的抽象走势图。 */
function plotText(metric, raw) {
  if (metric.kind === 'flag') return raw ? '✓ 拿到' : '✗ 未拿到';
  if (metric.kind === 'pair') return num(raw?.own) && num(raw?.foe) ? `${fmtNumber(raw.own)} : ${fmtNumber(raw.foe)}` : '—';
  if (metric.kind === 'pct') return num(raw) ? `${Math.round(raw)}%` : '—';
  return num(raw) ? (metric.unit === 'gold' ? fmtSigned(raw) : fmtNumber(raw)) : '—';
}

function detailBody(metric, games, view, esc) {
  const indexes = viewIndexes(games, view);
  const raws = indexes.map((index) => metric.perGame?.[index]);
  const values = raws.map((raw) => plotValue(metric, raw));
  const max = Math.max(1, ...values.filter(num).map((value) => Math.abs(value)));
  const cards = indexes.map((index, position) => {
    const game = games[index];
    const raw = raws[position];
    const value = values[position];
    const reason = metric.missing?.[index] || (raw === null || raw === undefined ? 'not-triggered' : null);
    const positive = metric.kind === 'flag' ? value === 1
      : metric.kind === 'num' ? value > 0 : value >= 50;
    const tone = !num(value) ? 'is-na' : (positive !== !!metric.reverse ? 'is-up' : 'is-down');
    const width = num(value) ? Math.max(6, Math.min(100, Math.abs(value) / max * 100)) : 0;
    return `<div class="bgv-evidence ${tone === 'is-na' ? 'is-na' : ''}">
      <b>${esc(gameWord(game.gameIndex))}</b>
      <span>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : ''}</span>
      <em>${num(value) ? esc(plotText(metric, raw)) : esc(NA_SHORT[reason] || '无数据')}</em>
      <i class="bgv-evidence-bar ${tone}" style="--w:${width.toFixed(0)}%"></i>
    </div>`;
  }).join('');
  return `<div class="bgv-evidence-wrap">
    <p class="bgv-evidence-head">${esc(metric.label)} · 逐局证据（${values.filter(num).length}/${games.length} 局有值）</p>
    <div class="bgv-evidence-list">${cards || '<span class="bgx-quiet">这个视角没有可展示的局</span>'}</div>
  </div>`;
}

export function renderOverview(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const block = insight.overview;
  if (!block || !(block.metrics || []).length) {
    return `${cardHead(esc, '01 总览与对比', '这场没有可用的过程指标', '')}${emptyState('没有过程指标，先补齐回放或 BP 名单。')}`;
  }
  const mode = BASE_MODES.some(([key]) => key === ui.baseMode) ? ui.baseMode : 'format';
  const modeLabel = (BASE_MODES.find(([key]) => key === mode) || [])[1];
  const games = block.games || [];
  const view = VIEW_MODES.some(([key]) => key === ui.overviewView) ? ui.overviewView : 'games';
  const shownGames = view === 'games' ? games : games.filter((game) => game.result === view);
  const aggregate = view !== 'games';
  const indexes = viewIndexes(games, view);
  const columns = aggregate ? 1 : (shownGames.length || 1);
  const metricsAll = block.metrics || [];
  const groups = [];
  for (const metric of metricsAll) if (!groups.includes(metric.group)) groups.push(metric.group);
  const metricGroup = ui.metricGroup === 'key' || groups.includes(ui.metricGroup) ? ui.metricGroup : 'all';
  let metrics = metricGroup === 'all' ? metricsAll
    : metricGroup === 'key' ? metricsAll.slice()
      : metricsAll.filter((metric) => metric.group === metricGroup);
  if (metricGroup === 'key') {
    /* 关键项不再固定名单：偏离基准越大、覆盖越足越靠前；不足 3 局降权。 */
    const scored = (metric) => {
      const delta = deltaFor(metric, mode, view);
      const coverage = num(metric.coverage) ? metric.coverage : (metric.perGame || []).length;
      return num(delta) ? Math.abs(delta) * Math.min(coverage, 3) / 3 : 0;
    };
    metrics.sort((a, b) => scored(b) - scored(a) || metricsAll.indexOf(a) - metricsAll.indexOf(b));
    metrics = metrics.slice(0, 8);
  }

  /* 关键项按偏离排序后分组会交错，重复组名反而更乱：只在固定分组视角显示组带。 */
  const showGroupHeads = metricGroup !== 'key' && new Set(metrics.map((metric) => metric.group)).size > 1;
  const bodyRows = [];
  let lastGroup = '';
  for (const metric of metrics) {
    if (showGroupHeads && metric.group !== lastGroup) {
      bodyRows.push(`<tr class="bgv-group-row"><th scope="colgroup" colspan="${columns + 3}">${esc(metric.group)}</th></tr>`);
      lastGroup = metric.group;
    }
    const cells = aggregate
      ? `<td class="bgv-col-game is-aggregate">${aggregateCell(metric, view)}</td>`
      : shownGames.map((game) => {
        const index = games.indexOf(game);
        const value = metric.perGame?.[index];
        const reason = metric.missing?.[index] || (value === null || value === undefined ? 'not-triggered' : null);
        return `<td class="bgv-col-game" data-bgv-game="${esc(String(game.gameIndex))}">
          <button type="button" class="bgv-cell-btn" data-bgv-game="${esc(String(game.gameIndex))}" aria-label="${esc(metric.label)} ${esc(gameWord(game.gameIndex))}：点按高亮这一局">${cellFor(metric, value, reason)}</button></td>`;
      }).join('');
    const detailId = `bgv-detail-${metrics.indexOf(metric)}`;
    const strip = miniSpark(indexes.map((index) => plotValue(metric, metric.perGame?.[index])),
      { zero: metric.kind === 'num' });
    bodyRows.push(`<tr class="bgv-metric-row">
      <th scope="row" class="bgv-col-metric">
        <button type="button" class="bgv-row-toggle" data-bgv-expand="${detailId}" aria-expanded="false" aria-controls="${detailId}">
          <span class="bgv-row-caret" aria-hidden="true"></span>
          <span class="bgv-metric-copy"><b title="${esc(metric.label)}">${esc(metric.label)}</b><small title="${esc(metric.hint || '')}">${esc(metric.hint || '')}</small></span>
          <span class="bgv-mini-strip" aria-hidden="true">${strip}</span>
        </button>
      </th>
      ${cells}
      <td class="bgv-col-series">${seriesFor(metric, view)}</td>
      <td class="bgv-col-compare">${deltaPill(metric, deltaFor(metric, mode, view), `${esc(metric.label)} · ${esc(modeLabel)}`)}</td>
    </tr>
    <tr class="bgv-detail-row" id="${detailId}" hidden><td colspan="${columns + 3}">${detailBody(metric, games, view, esc)}</td></tr>`);
  }

  const head = `<thead><tr>
    <th scope="col" class="bgv-col-metric">指标</th>
    ${aggregate
      ? `<th scope="col" class="bgv-col-head">${VIEW_WORD[view]}平均<small>${shownGames.length} 局</small></th>`
      : shownGames.map((game) => `<th scope="col" class="bgv-col-head" data-bgv-game="${esc(String(game.gameIndex))}">${esc(gameWord(game.gameIndex))}
        <i class="${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</i></th>`).join('')}
    <th scope="col" class="bgv-col-series">整场</th>
    <th scope="col" class="bgv-col-compare">对比<small>${esc(modeLabel)}</small></th>
  </tr></thead>`;

  const filterToggle = `<div class="bgx-seg bgv-filter" role="group" aria-label="指标分组">
    ${[['all', '全部'], ['key', '关键 8 项'], ...groups.map((name) => [name, name])].map(([value, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgv-group="${esc(value)}" aria-pressed="${metricGroup === value}">${esc(label)}</button>`).join('')}
  </div>`;
  const viewToggle = `<div class="bgx-seg bgv-view" role="group" aria-label="指标视角">
    ${VIEW_MODES.map(([value, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgv-view="${value}" aria-pressed="${view === value}">${label}</button>`).join('')}
  </div>`;
  const baseN = insight.baseline?.modes?.[mode]?.metrics?.n;
  const baseTag = `<span class="bgv-base-tag" title="对比基准来自${esc(modeLabel)}，不是本场数据">基准 ${esc(modeLabel)}${num(baseN) ? ` · ${count(baseN)} 局` : ''}</span>`;
  const filterBar = `<div class="bgv-toolbar">
    <div class="bgv-toolbar-left">${filterToggle}${viewToggle}</div>
    <span class="bgv-toolbar-count">显示 ${count(metrics.length)} / ${count(metricsAll.length)} 项</span>
  </div>`;
  const legend = `<div class="bgv-na-legend">
    <span><i class="is-good">✓ 拿到</i><i class="is-bad">✗ 未拿到</i></span>
    <span><i class="is-na">—</i> 缺回放 / 本局未触发 / 无历史基准：每格写明原因，不再把「—」当 0</span>
  </div>`;
  return `${cardHead(esc, '01 总览与对比', `这一场 BO${esc(String(insight.baseline?.bestOf || games.length))}，每一局的关键指标`, '',
    `${selectBase(ui)}${baseTag}<span class="bgx-chip">${count(games.length)} 局</span>`)}
    ${conclusionBlock(insight, metricsAll, games, mode, modeLabel, esc)}
    ${overviewReadout(insight, metricsAll, games, view)}
    ${filterBar}
    <div class="bgv-board-scroll${aggregate ? ' is-aggregate' : ''}" tabindex="0" role="region" aria-label="逐局指标表，可横向滚动" style="--bgv-cols:${columns}">
      <table class="bgv-board">
        <caption class="visually-hidden">本场逐局指标、整场值与${esc(modeLabel)}基准对比</caption>
        ${head}<tbody>${bodyRows.join('')}</tbody>
      </table>
    </div>
    ${legend}`;
}

/* ── 01 系列赛走势 ─────────────────────────────────────────── */
/* ── 02 每局 BP 读法 ───────────────────────────────────────── */
function qty(value, total) {
  return `${num(value) ? value : 0}<i>/${num(total) ? total : '—'}</i>`;
}

function readCell(value, total, label, tone = '', note = '') {
  return `<div class="bgv-read ${tone}"><b>${qty(value, total)}</b><span>${label}</span>${note ? `<small>${note}</small>` : ''}</div>`;
}

const bpSideClass = (side) => side === 'blue' || side === 'red' ? `is-${side}` : 'is-unknown';
const bpSideName = (side) => side === 'blue' ? '蓝方' : side === 'red' ? '红方' : '阵营未记录';
const bpSideBadge = (team, side) => `<span class="bgv-bp-side-badge ${bpSideClass(side)}"><i></i>${team} · ${bpSideName(side)}</span>`;

function lineupRow(h, side, cells, actualSide) {
  const { esc } = h;
  return `<div class="bgv-lineup-side ${bpSideClass(actualSide)}">
    <span class="bgv-side-label">${side === 'foe' ? '对方' : '我方'}<small>${bpSideName(actualSide)}</small></span>
    <div class="bgv-lineup-heroes">${(cells || []).map((cell) =>
      heroChip(h, cell.hero, [cell.position, cell.archetype].filter(Boolean).join(' · '))).join('') || '<span class="bgx-quiet">没有名单</span>'}</div>
  </div>`;
}

function capsPips(side, caps, core, actualSide) {
  const items = ['前排', '开团', '控制'].map((key) => ({ label: key, value: num(caps[key]) ? caps[key] : 0 }));
  if (num(core)) items.push({ label: '核心', value: core });
  const dots = (value) => {
    const count = clamp(Math.round(value), 0, 5);
    return `<span class="bgv-cap-dots">${Array.from({ length: 5 },
      (_, index) => `<i class="${index < count ? 'is-on' : ''}"></i>`).join('')}</span>`;
  };
  return `<div class="bgv-caps-side ${bpSideClass(actualSide)}">
    <span class="bgv-caps-side-label">${side === 'foe' ? '对方' : '我方'}<small>${bpSideName(actualSide)}</small></span>
    <div class="bgv-caps-tiles">${items.map((item) => `<div class="bgv-cap">
      <b>${item.value}</b><span>${item.label}</span>${dots(item.value)}
    </div>`).join('')}</div>
  </div>`;
}

function comboBlock(game, h, ownSide) {
  const { esc } = h;
  const foeSide = ownSide === 'blue' ? 'red' : ownSide === 'red' ? 'blue' : null;
  /* 只认赛训组组合池里的双人组合：本局两边都拿到才算「命中」；
     池子为空时不再退回 KPL / 历史常用组合，避免拿任意双人组当组合池。 */
  const poolDoc = h.comboPool && !h.comboPool.builtin ? h.comboPool : null;
  const pool = (poolDoc?.pairs || []).filter((row) => Array.isArray(row.heroes) && row.heroes.length === 2);
  const strengthWord = (value) => value === 'strong' ? '强联动' : value === 'weak' ? '弱联动' : '组合池';
  const sideBlock = (side) => {
    const title = side === 'foe' ? '对方双人组合' : '我方双人组合';
    const actualSide = side === 'foe' ? foeSide : ownSide;
    const empty = (text) => `<div class="bgv-combo-side ${bpSideClass(actualSide)}">
      <span class="bgv-combo-title">${title}</span><p class="bgv-combo-empty">${text}</p></div>`;
    if (h.comboPool === undefined) return empty('组合池读取中…');
    if (!h.comboPool) return empty('组合池暂不可读');
    if (!pool.length) return empty('组合池还没有保存双人组合');
    const picked = new Set((side === 'foe' ? game.heroesFoe : game.heroesOwn) || []);
    const hits = pool.filter((row) => row.heroes.every((hero) => picked.has(hero)));
    if (!hits.length) return empty('这局没有命中组合池');
    return `<div class="bgv-combo-side ${bpSideClass(actualSide)}">
      <span class="bgv-combo-title">${title}</span>
      ${hits.slice(0, 2).map((row) => {
        const pair = row.heroes || [];
        return `<div class="bgv-combo-row is-got">
          <div class="bgv-combo-faces">${pair.map((hero, index) => `<span class="bgv-combo-face is-kept">
            ${h.portrait(hero, 'bgv-combo-img')}<b>${esc(hero)}</b>
          </span>${index === 0 ? '<em class="bgv-combo-plus">+</em>' : ''}`).join('')}</div>
          <div class="bgv-combo-copy"><b>命中<em class="bgv-kpl-tag">组合池</em></b><small>${esc(strengthWord(row.strength))}</small></div>
        </div>`;
      }).join('')}
    </div>`;
  };
  return `<div class="bgv-combos-deny">${sideBlock('foe')}${sideBlock('own')}</div>`;
}

function bpDraftFlow(game, boGame, h) {
  const ownSide = boGame?.foeSide === 'blue' ? 'red' : boGame?.foeSide === 'red' ? 'blue' : null;
  const foeSide = ownSide === 'blue' ? 'red' : ownSide === 'red' ? 'blue' : null;
  const picks = {
    own: boGame?.ownPicks?.length ? boGame.ownPicks : (game.heroesOwn || []),
    foe: boGame?.foePicks?.length ? boGame.foePicks : (game.heroesFoe || []),
  };
  const bans = {
    own: boGame?.ownBans?.length ? boGame.ownBans : (game.bansOwn || []),
    foe: boGame?.foeBans?.length ? boGame.foeBans : (game.bansFoe || []),
  };
  if (!ownSide) {
    const team = (key, label) => {
      const events = [
        ...(bans[key] || []).map((hero) => ({ hero, action: 'ban' })),
        ...(picks[key] || []).map((hero) => ({ hero, action: 'pick' })),
      ];
      return `<section class="bgv-bp-fallback-team"><h4>${label}</h4><div>${events.map((event) => `
        <span class="bgv-bp-event is-unknown is-${event.action}">${h.portrait(event.hero, 'bgv-bp-event-face')}<b>${h.esc(event.hero)}</b><small>${event.action === 'ban' ? 'Ban' : 'Pick'}</small></span>`).join('')}</div></section>`;
    };
    return `<section class="bgv-bp-draft is-unknown"><header><b>Ban / Pick 流程</b><span>阵营未记录，按队伍汇总</span></header><div class="bgv-bp-fallback">${team('own', '我方')}${team('foe', '对方')}</div></section>`;
  }
  const banCount = Math.max(4, Math.min(5, Math.max((bans.own || []).length, (bans.foe || []).length)));
  const schedule = BP_SCHEDULE[banCount] || BP_SCHEDULE[4];
  const phases = [
    { key: 'ban1', title: 'R1 Ban', note: '第一轮禁用', events: [] },
    { key: 'pick1', title: 'P1', note: '第一轮选择', events: [] },
    { key: 'ban2', title: 'R2 Ban', note: '第二轮禁用', events: [] },
    { key: 'pick2', title: 'P2', note: '第二轮选择', events: [] },
  ];
  const counters = { own: { ban: 0, pick: 0 }, foe: { ban: 0, pick: 0 } };
  let phaseIndex = -1;
  let lastAction = '';
  schedule.forEach(([action, camp], order) => {
    if (action !== lastAction) { phaseIndex++; lastAction = action; }
    const side = camp === 'B' ? 'blue' : 'red';
    const team = side === ownSide ? 'own' : 'foe';
    const list = action === 'ban' ? bans[team] : picks[team];
    const slot = counters[team][action]++;
    phases[phaseIndex].events.push({
      action, side, team, hero: list[slot] || '', order: order + 1, slot: slot + 1,
    });
  });
  return `<section class="bgv-bp-draft" aria-label="两轮 Ban 与 Pick 流程">
    <header><b>两轮 BP 流程</b><div class="bgv-bp-draft-legend"><span class="is-blue"><i></i>蓝方</span><span class="is-red"><i></i>红方</span><span><em>Ban</em>禁用</span><span><em>Pick</em>选择</span></div></header>
    <div class="bgv-bp-phases">${phases.map((phase) => `<section class="bgv-bp-phase">
      <header><b>${phase.title}</b><span>${phase.note}</span></header>
      <div class="bgv-bp-phase-events">${phase.events.map((event) => `<div class="bgv-bp-event ${bpSideClass(event.side)} is-${event.action}" title="${h.esc(`第 ${event.order} 手 · ${event.team === 'own' ? '我方' : '对方'} · ${event.action === 'ban' ? 'Ban' : 'Pick'} ${event.hero || '未记录'}`)}">
        <span class="bgv-bp-event-side">${event.team === 'own' ? '我' : '敌'} · ${bpSideName(event.side)}</span>
        ${event.hero ? h.portrait(event.hero, 'bgv-bp-event-face') : '<span class="bgv-bp-event-empty">—</span>'}
        <b>${h.esc(event.hero || '未记录')}</b>
        <small>${event.action === 'ban' ? 'Ban' : 'Pick'} ${event.slot}</small>
        ${event.action === 'ban' ? '<i class="bgv-bp-event-slash"></i>' : ''}
      </div>`).join('')}</div>
    </section>`).join('')}</div>
  </section>`;
}


export function renderBp(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const plan = insight.bpPlan;
  if (!plan || !(plan.games || []).length) {
    return `${cardHead(esc, '02 BP 博弈', '这场没有可核对的 BP 记录', '')}${emptyState('没有 BP 名单，先到对局详情补齐 BP。')}`;
  }
  const allGames = plan.games;
  const playable = allGames.filter((game) => (game.heroesOwn || []).length && (game.heroesFoe || []).length);
  const filtered = ui.bpGame ? playable.filter((game) => String(game.gameIndex) === String(ui.bpGame)) : playable;
  const games = filtered.length ? filtered : playable;
  if (!playable.length) {
    return `${cardHead(esc, '02 BP 博弈', '这场没有可读的 BP 名单', '')}${emptyState('没有 BP 名单，先到对局详情补齐 BP。')}`;
  }
  const series = plan.series || {};
  const boGames = insight.boBp?.current?.games || [];
  const ownHits = games.reduce((sum, game) => sum + (game.plan?.ownHits || 0), 0);
  const foeHits = games.reduce((sum, game) => sum + (game.plan?.foeHits || 0), 0);
  const brokenFoe = games.reduce((sum, game) => sum + ((game.combos?.foe || [])
    .filter((row) => row.status === 'broken' || row.status === 'stolen' || row.status === 'denied').length), 0);
  const brokenOwn = games.reduce((sum, game) => sum + ((game.combos?.own || [])
    .filter((row) => row.status === 'broken' || row.status === 'stolen' || row.status === 'denied').length), 0);
  const pairHits = games.reduce((sum, game) => sum + (game.kpl?.own?.pairHits || 0), 0);
  const pairN = games.filter((game) => num(game.kpl?.own?.pairN)).length;
  const banTotal = games.reduce((sum, game) => sum
    + (game.ban?.denyItems || []).filter((item) => item.foePicks > 0).length, 0);
  const banPossible = games.reduce((sum, game) => sum + (game.bansOwn || []).length, 0);
  const edgeMean = num(series.edgeMean) ? series.edgeMean : null;
  const edgeWord = edgeMean === null ? '数据不足' : edgeMean >= 0.03 ? '整体占优'
    : edgeMean <= -0.03 ? '整体下风' : '整体接近';
  const cards = games.map((game, index) => {
    const comp = (insight.comp?.games || []).find((item) => String(item.gameIndex) === String(game.gameIndex)) || {};
    const system = (insight.compSystem?.games || []).find((item) => String(item.gameIndex) === String(game.gameIndex)) || {};
    const boGame = boGames.find((item) => String(item.index) === String(game.gameIndex)) || null;
    const ownSide = boGame?.foeSide === 'blue' ? 'red' : boGame?.foeSide === 'red' ? 'blue' : null;
    const foeSide = ownSide === 'blue' ? 'red' : ownSide === 'red' ? 'blue' : null;
    const planTotal = (game.plan?.foeWanted || []).length || 3;
    const planHit = game.plan?.foeHits || 0;
    const banHit = (game.ban?.denyItems || []).filter((item) => item.foePicks > 0).length;
    const banCount = (game.bansOwn || []).length || 5;
    const pairHit = game.kpl?.own?.pairHits || 0;
    const ownCaps = comp.ownCaps || {};
    const foeCaps = comp.foeCaps || {};
    const core = num((system.own || {}).cores) ? system.own.cores : null;
    const foeCore = num((system.foe || {}).cores) ? system.foe.cores : null;
    /* 名单展示必须以完整的 heroes*（5 人）为准，签名只用来加分路/打法角标。
       backend 的 _signature() 会丢掉「分路未登记 / 打法待分类」的选手，
       旧逻辑只要签名非空就整份替掉名单，那位选手就从界面上凭空消失。
       老数据只有签名没有 heroes* 时，仍退回签名，保证不倒退。 */
    const lineupCells = (heroes, signature) => {
      const sig = signature || [];
      const byHero = new Map(sig.map((cell) => [cell.hero, cell]));
      const names = heroes && heroes.length ? heroes : sig.map((cell) => cell.hero);
      return names.map((hero) => byHero.get(hero) || { hero, position: '', archetype: '' });
    };
    const ownCells = lineupCells(game.heroesOwn, game.signature?.own);
    const foeCells = lineupCells(game.heroesFoe, game.signature?.foe);
    const open = ui.bpOpen?.[String(game.gameIndex)] ?? (!!ui.bpGame || index === 0);
    return `<details class="bgv-bp-card ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}"
      data-bp-card="${esc(String(game.gameIndex))}" ${open ? 'open' : ''}>
      <summary class="bgv-bp-sum">
        <b>${esc(gameWord(game.gameIndex))}</b>
        <em>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em>
      </summary>
      <div class="bgv-bp-body">
        <div class="bgv-bp-game-head">${bpSideBadge('我方', ownSide)}<span class="bgv-bp-vs">VS</span>${bpSideBadge('对方', foeSide)}</div>
        <div class="bgv-bp-lineups">${lineupRow(h, 'own', ownCells, ownSide)}${lineupRow(h, 'foe', foeCells, foeSide)}</div>
        ${bpDraftFlow(game, boGame, h)}
        <div class="bgv-bp-lower">
          <section class="bgv-bp-combo-panel" aria-label="双方双人组合">${comboBlock(game, h, ownSide)}</section>
          <section class="bgv-bp-read-panel" aria-label="本局教练指标">
            <div class="bgv-bp-reads">
              ${readCell(planHit, planTotal, '对方首选被处理', planHit >= Math.ceil(planTotal / 2) ? 'is-good' : '', '禁用或抢走对方想用的英雄')}
              ${readCell(banHit, banCount, '禁用命中', banHit >= Math.ceil(banCount / 2) ? 'is-good' : '', '禁到对方常用英雄')}
              ${readCell(pairHit, 10, '双人组合命中', pairHit >= 3 ? 'is-good' : '', '五人阵容共 10 种双人搭配')}
            </div>
            <div class="bgv-caps-board">${capsPips('own', ownCaps, core, ownSide)}${capsPips('foe', foeCaps, foeCore, foeSide)}</div>
          </section>
        </div>
      </div>
    </details>`;
  }).join('');

  const filterChip = ui.bpGame
    ? `<button type="button" class="bgx-btn control" data-bp-game="">${glyph('matches', { label: '看全部局', size: 18 })} 看全部 ${count(playable.length)} 局</button>`
    : '';
  return `${cardHead(esc, '02 BP 博弈', `${ui.bpGame ? `第 ${esc(String(ui.bpGame))} 把` : `这 ${count(playable.length)} 局`} BP，${esc(edgeWord)}`,
    '',
    `${filterChip}${ui.bpGame ? `<span class="bgx-chip">第 ${esc(String(ui.bpGame))} 把</span>` : ''}`)}
    <div class="bgv-bp-summary">
      ${readoutTile('拆掉对方想组的组合', `${brokenFoe} 组`, '禁用或抢走其中一张', brokenFoe > 0 ? 'is-good' : '')}
      ${readoutTile('对方拆掉我方组合', `${brokenOwn} 组`, '对方禁用或抢走其中一张', brokenOwn > brokenFoe ? 'is-bad' : '')}
      ${readoutTile('拿到对方想用的英雄', `${ownHits} 次`, '对手核心被我们抢 / ban 的次数另计', ownHits >= foeHits ? 'is-good' : '')}
      ${readoutTile('双人组合命中', pairN ? `${pairHits} 对` : '—', `${pairN} 局有组合样本`)}
      ${readoutTile('禁用命中', banPossible ? `${banTotal} / ${banPossible}` : '—', '禁到对方常用英雄的 Ban 数')}
    </div>
    <div class="bgv-bp-grid">${cards}</div>`;
}

/* ── 02 BP 意图：可点的局次轨道 ──────────────────────────── */
function topEntries(games, getter, limit = 2) {
  const counts = new Map();
  for (const game of games) {
    const value = getter(game);
    const key = Array.isArray(value) ? value.filter(Boolean).join('|') : value;
    if (!key) continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit)
    .map(([key, count]) => ({ key, count, heroes: key.split('|') }));
}

function boHero(h, hero, tone = 'is-pick') {
  if (!hero) return '<span class="bgv-boh-none">—</span>';
  return `<span class="bgv-boh-hero ${tone}" title="${h.esc(hero)}">${h.portrait(hero, 'bgv-boh-face')}<b>${h.esc(hero)}</b></span>`;
}

/* 规则中心里的 KPL 初稿证据串（n / 胜率 / 超额 / Wilson 下界）是生成器的中间量，
   不是教练写得出的结论，不占复盘卡片的版面；赛训组手写的备注照常保留。 */
function coachNote(note) {
  const text = String(note || '');
  return /KPL|Wilson|下界|超额|衰减|pp\b|n=\d/.test(text) ? '' : text;
}

function boRow(label, tiles, meta, cls = '') {
  return `<div class="bgv-boh-row ${cls}"><span>${label}</span><div class="bgv-boh-tiles">${tiles}</div><em>${meta || ''}</em></div>`;
}

/* KPL 征召的逐手顺序：4 Ban / 5 Ban 两套。
   B = 蓝方，R = 红方；数字顺序就是全局 BP 手序。 */
const BP_SCHEDULE = {
  4: [
    ['ban', 'B'], ['ban', 'R'], ['ban', 'B'], ['ban', 'R'],
    ['pick', 'B'], ['pick', 'R'], ['pick', 'R'], ['pick', 'B'], ['pick', 'B'], ['pick', 'R'],
    ['ban', 'R'], ['ban', 'B'], ['ban', 'R'], ['ban', 'B'],
    ['pick', 'R'], ['pick', 'B'], ['pick', 'B'], ['pick', 'R'],
  ],
  5: [
    ['ban', 'B'], ['ban', 'R'], ['ban', 'B'], ['ban', 'R'],
    ['pick', 'B'], ['pick', 'R'], ['pick', 'R'], ['pick', 'B'], ['pick', 'B'], ['pick', 'R'],
    ['ban', 'R'], ['ban', 'B'], ['ban', 'R'], ['ban', 'B'], ['ban', 'R'], ['ban', 'B'],
    ['pick', 'R'], ['pick', 'B'], ['pick', 'B'], ['pick', 'R'],
  ],
};

function boSideLabel(side) {
  return side === 'red' ? '红方' : side === 'blue' ? '蓝方' : '红蓝未知';
}

function boSideOrders(side, banCount) {
  if (side !== 'blue' && side !== 'red') return { bans: [], picks: [] };
  const code = side === 'blue' ? 'B' : 'R';
  const schedule = BP_SCHEDULE[banCount] || BP_SCHEDULE[4];
  const bans = [];
  const picks = [];
  schedule.forEach(([action, camp], index) => {
    if (camp !== code) return;
    if (action === 'ban') bans.push(index + 1);
    else picks.push(index + 1);
  });
  return { bans, picks };
}

/* 对面自己的 pick 楼层：按 BP 手序成对。
   蓝方：1L / 2L+3L / 4L+5L；红方：1L+2L / 3L / 4L / 5L（counter）。 */
function boPickGroups(side, orders) {
  const pick = orders.picks || [];
  if (side === 'red') {
    return [
      { label: '1L + 2L', slots: [0, 1], orders: pick.slice(0, 2), phase: '一阶段' },
      { label: '3L', slots: [2], orders: pick.slice(2, 3), phase: '一阶段' },
      { label: '4L', slots: [3], orders: pick.slice(3, 4), phase: '二阶段' },
      { label: '5L · counter', slots: [4], orders: pick.slice(4, 5), phase: '二阶段', counter: true },
    ];
  }
  return [
    { label: '1L', slots: [0], orders: pick.slice(0, 1), phase: '一阶段' },
    { label: '2L + 3L', slots: [1, 2], orders: pick.slice(1, 3), phase: '一阶段' },
    { label: '4L + 5L', slots: [3, 4], orders: pick.slice(3, 5), phase: '二阶段' },
  ];
}

export function renderBoHabit(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const block = insight.boBp;
  if (!block || !block.available) {
    return `<section class="bgx-card bgv-boh">
      ${cardHead(esc, '02 BP 意图', '这一把的 BP 还没数据', '')}
      ${emptyState('本场 BP 还没到齐，暂无同赛制历史。')}
    </section>`;
  }
  const bestOf = Number(block.bestOf) || 7;
  const current = block.current || {};
  const anchorDate = current.date || '';
  const windowKey = ['30', '90', 'all'].includes(ui.boWindow) ? ui.boWindow : '90';
  const scope = ui.boScope === 'all' ? 'all' : 'opp';
  const days = windowKey === 'all' ? null : Number(windowKey);
  const cutoff = (() => {
    if (!days || !anchorDate) return '';
    const date = new Date(`${anchorDate}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - days);
    return date.toISOString().slice(0, 10);
  })();
  const history = (block.history || []).filter((item) =>
    (scope === 'all' || item.sameOpponent)
    && (!anchorDate || (item.date || '') <= anchorDate)
    && (!cutoff || (item.date || '') >= cutoff));
  const slots = Array.from({ length: bestOf }, (_, index) => index + 1);
  const selected = Math.min(bestOf, Math.max(1, Number(ui.boSlot) || 1));
  const cur = (current.games || []).find((game) => Number(game.index) === selected) || null;
  const selectedSide = cur?.foeSide || 'blue';

  /* 组合意图：组合只认赛训组保存的组合池；克制方向只认赛训规则中心的
     克制关系（英雄→英雄、组合→组合），不再拿营地/KPL 对位临时兜底。 */
  const poolDoc = h.comboPool && !h.comboPool.builtin ? h.comboPool : null;
  const poolCombos = poolDoc ? [
    ...(poolDoc.pairs || []).map((row) => ({ ...row, size: 2 })),
    ...(poolDoc.trios || []).map((row) => ({ ...row, size: 3 })),
  ].map((row) => {
    const heroes = [...new Set((row.heroes || [])
      .map((hero) => String(hero || '').trim()).filter(Boolean))];
    return { ...row, heroes, key: heroes.slice().sort().join('|') };
  }).filter((row) => row.heroes.length === row.size) : [];
  const comboHeroes = new Set(poolCombos.flatMap((combo) => combo.heroes));

  const splitNames = (value) => String(value || '')
    .split(/[+＋，,、;；/|]+/).map((part) => part.trim()).filter(Boolean);
  const counterHeroes = (row, side) => {
    const list = row?.[side === 'a' ? 'aHeroes' : 'bHeroes'];
    if (Array.isArray(list)) return [...new Set(list.map((hero) => String(hero || '').trim()).filter(Boolean))];
    return [...new Set(splitNames(row?.[side === 'a' ? 'a' : 'b']))];
  };
  const comboByKey = new Map(poolCombos.map((combo) => [combo.key, combo]));
  const comboByName = new Map(poolCombos
    .map((combo) => [String(combo.name || '').trim(), combo])
    .filter(([name]) => name));
  const ruleComboByName = new Map(((h.rulesCombos && h.rulesCombos.combos) || [])
    .map((combo) => [String(combo.name || '').trim(), combo])
    .filter(([name]) => name));
  /* 规则里的组合可能是「英雄+英雄」文本，也可能是规则中心的组合名；
     两种都先解析成英雄集合，再回到组合池里找同一组。 */
  const resolveCombo = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return null;
    if (comboByName.has(raw)) return comboByName.get(raw);
    const direct = comboByKey.get([...new Set(splitNames(raw))].sort().join('|'));
    if (direct) return direct;
    const ruleCombo = ruleComboByName.get(raw);
    if (!ruleCombo) return null;
    const key = [...new Set((ruleCombo.heroes || [])
      .map((hero) => String(hero || '').trim()).filter(Boolean))].sort().join('|');
    return comboByKey.get(key) || null;
  };
  const rawHeroRules = (h.rulesCounters && h.rulesCounters.heroPairs) || [];
  const rawComboRules = (h.rulesCounters && h.rulesCounters.comboPairs) || [];
  const heroRules = rawHeroRules
    .flatMap((row) => counterHeroes(row, 'a').flatMap((attacker) =>
      counterHeroes(row, 'b').map((defender) => ({
        attacker, defender,
        strength: row.strength, note: row.note,
      }))))
    .filter((row) => row.attacker && row.defender);
  const comboRules = rawComboRules
    .map((row) => ({
      attacker: resolveCombo(row.aHeroes ?? row.a), defender: resolveCombo(row.bHeroes ?? row.b),
      strength: row.strength, note: row.note,
    }))
    .filter((row) => row.attacker && row.defender);
  const heroRulesByDefender = new Map();
  for (const rule of heroRules) {
    if (!heroRulesByDefender.has(rule.defender)) heroRulesByDefender.set(rule.defender, []);
    heroRulesByDefender.get(rule.defender).push(rule);
  }
  const comboRulesByDefender = new Map();
  for (const rule of comboRules) {
    if (!comboRulesByDefender.has(rule.defender.key)) comboRulesByDefender.set(rule.defender.key, []);
    comboRulesByDefender.get(rule.defender.key).push(rule);
  }
  const rulesHint = h.rulesCounters === undefined ? '克制规则读取中…'
    : !h.rulesCounters ? '克制规则暂不可读'
      : (!heroRules.length && !comboRules.length)
        ? (rawHeroRules.length || rawComboRules.length ? '克制规则未匹配组合池' : '克制规则未配置')
        : '';

  const foePickSet = (game) => new Set((game?.foePicks || []).filter(Boolean));
  const ownPickSet = (game) => new Set((game?.ownPicks || []).filter(Boolean));
  const combosStolen = (game) => {
    const picked = foePickSet(game);
    return poolCombos.filter((combo) => combo.heroes.every((hero) => picked.has(hero)));
  };
  const comboForHero = (hero) => poolCombos.find((combo) =>
    combo.heroes.includes(hero) && combo.strength === 'strong')
    || poolCombos.find((combo) => combo.heroes.includes(hero)) || null;
  const combosBroken = (game) => {
    const banned = new Set((game?.foeBans || []).filter(Boolean));
    const picked = foePickSet(game);
    /* 已经被对面整组抢走的英雄不再重复算「拆」；只算单抢一张。 */
    const stolen = new Set(combosStolen(game).flatMap((combo) => combo.heroes));
    const rows = [];
    for (const hero of banned) {
      if (!comboHeroes.has(hero)) continue;
      const combo = comboForHero(hero);
      if (combo) rows.push({ hero, via: 'ban', combo });
    }
    for (const hero of picked) {
      if (!comboHeroes.has(hero) || stolen.has(hero)) continue;
      const combo = comboForHero(hero);
      if (combo) rows.push({ hero, via: 'pick', combo });
    }
    return rows;
  };
  const combosOwned = (game) => {
    const own = ownPickSet(game);
    return poolCombos.filter((combo) => combo.heroes.every((hero) => own.has(hero)));
  };
  const ruleCovers = (combo) => (comboRulesByDefender.get(combo.key) || []).length
    || combo.heroes.some((hero) => (heroRulesByDefender.get(hero) || []).length);
  const combosCountered = (game) => {
    if (!heroRules.length && !comboRules.length) return [];
    const foe = foePickSet(game);
    const hits = new Map();
    for (const combo of combosOwned(game)) {
      for (const rule of comboRulesByDefender.get(combo.key) || []) {
        if (!rule.attacker.heroes.every((hero) => foe.has(hero))) continue;
        const key = `combo|${rule.attacker.key}|${combo.key}`;
        if (!hits.has(key)) hits.set(key, { type: 'combo', attacker: rule.attacker, defender: combo, rule });
      }
      for (const hero of combo.heroes) {
        for (const rule of heroRulesByDefender.get(hero) || []) {
          if (!foe.has(rule.attacker)) continue;
          const key = `hero|${rule.attacker}|${combo.key}|${hero}`;
          if (!hits.has(key)) hits.set(key, { type: 'hero', attacker: rule.attacker, defender: hero, combo, rule });
        }
      }
    }
    /* 同一受方组合已有组合→组合规则命中时，不再叠英雄→英雄的同一件事。 */
    const comboDefenders = new Set([...hits.values()]
      .filter((hit) => hit.type === 'combo').map((hit) => hit.defender.key));
    return [...hits.values()].filter((hit) => hit.type === 'combo' || !comboDefenders.has(hit.combo.key));
  };
  const counterable = (game) => combosOwned(game).some((combo) => ruleCovers(combo));

  const poolHint = h.comboPool === undefined ? '组合池读取中…'
    : !h.comboPool ? '组合池暂不可读'
      : !poolCombos.length ? '组合池还没有保存组合'
        : '';
  const comboFaces = (combo, opts = {}) => {
    const { slashed = '', marked = '' } = opts;
    return combo.heroes.map((hero) => {
      let tile = boHero(h, hero);
      if (slashed === hero || marked === hero) {
        tile = `<span class="bgv-boh-faceunit ${slashed === hero ? 'is-slash' : ''}">
          ${tile}${marked === hero ? '<i class="bgv-boh-facemark">抢</i>' : ''}
        </span>`;
      }
      return tile;
    }).join('<i class="bgv-boh-plus">+</i>');
  };
  const stealFlow = (combo) => `<span class="bgv-boh-breakflow">
    ${comboFaces(combo)}
    <span class="bgv-boh-stealnote"><b>抢</b><small>整组拿齐</small></span>
  </span>`;
  const breakFlow = (item) => `<span class="bgv-boh-breakflow">
    ${comboFaces(item.combo, {
      slashed: item.via === 'ban' ? item.hero : '',
      marked: item.via === 'pick' ? item.hero : '',
    })}
    <span class="bgv-boh-breaknote">
      <b class="${item.via === 'pick' ? 'is-pick' : ''}">${item.via === 'ban' ? 'ban' : '单抢'}</b>
      <small>一张 · 组合被拆</small>
    </span>
  </span>`;
  const counterFlow = (hit) => {
    const arrow = '<span class="bgv-boh-flow-arrow"><i>克制</i><b>→</b></span>';
    if (hit.type === 'combo') {
      return `<span class="bgv-boh-flow">
        <span class="bgv-boh-flow-side">${comboFaces(hit.attacker)}</span>
        ${arrow}
        <span class="bgv-boh-flow-side is-def">${comboFaces(hit.defender)}</span>
      </span>`;
    }
    return `<span class="bgv-boh-flow is-hero">
      <span class="bgv-boh-flow-side">${boHero(h, hit.attacker)}</span>
      ${arrow}
      <span class="bgv-boh-flow-side is-def">${boHero(h, hit.defender)}</span>
      ${hit.combo ? `<em class="bgv-boh-flow-note">在 ${esc(hit.combo.heroes.join(' + '))}</em>` : ''}
    </span>`;
  };
  const intentLabel = {
    steal: '<span title="对面直接拿齐我方组合池里的两张（或三张）">抢我方组合</span>',
    break: '<span title="对面 ban 掉或单抢我方组合池里的一张">拆我方组合</span>',
    counter: '<span title="按赛训规则中心的克制方向：攻方 → 受方；只在本局我们拿到组合池组合时判">克我方组合</span>',
  };

  /* 18 手 = 4 Ban，20 手 = 5 Ban。历史只取和当前赛制同 Ban 数的局，
     不把 KPL 20 手和训练赛 18 手混在一张表里。 */
  const gameBans = (game) => Math.max(4, Math.min(5, Math.max(
    (game.foeBans || []).length, (game.ownBans || []).length)));
  const modeBans = (games) => {
    const counts = new Map();
    for (const game of games) {
      const n = gameBans(game);
      counts.set(n, (counts.get(n) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0]?.[0] || 0;
  };
  const formatBans = modeBans(current.games || [])
    || modeBans(history.flatMap((item) => item.games || []))
    || 4;
  const historyForFormat = history.filter((item) =>
    (item.games || []).some((game) => gameBans(game) === formatBans));
  /* 真正的「习惯」要把同侧同赛制的所有局合在一起看，而不是每个局次只取一条。 */
  const pooledBySide = (side) => historyForFormat.flatMap((item) => item.games || [])
    .filter((game) => gameBans(game) === formatBans
      && (!game.foeSide || game.foeSide === side));
  const pooledGames = pooledBySide(selectedSide);
  const pooledStat = {
    games: pooledGames,
    winCount: pooledGames.filter((game) => game.result === 'win').length,
    decided: pooledGames.filter((game) => game.result === 'win' || game.result === 'loss').length,
    tags: topEntries(pooledGames, (game) => game.foeTags?.[0], 2),
  };

  const stats = new Map(slots.map((slot) => {
    const all = historyForFormat.flatMap((item) => (item.games || [])
      .filter((game) => Number(game.index) === slot && gameBans(game) === formatBans));
    /* 旧数据可能没有 foeSide：未知侧也保留，不让整块突然空掉。 */
    const games = all.filter((game) => !game.foeSide || game.foeSide === selectedSide);
    const winCount = games.filter((game) => game.result === 'win').length;
    const decided = games.filter((game) => game.result === 'win' || game.result === 'loss').length;
    const tags = topEntries(games, (game) => game.foeTags?.[0], 2);
    return [slot, {
      slot, games, allGames: all, winCount, decided, tags,
      sides: {
        blue: all.filter((game) => game.foeSide === 'blue').length,
        red: all.filter((game) => game.foeSide === 'red').length,
        unknown: all.filter((game) => !game.foeSide).length,
      },
    }];
  }));

  /* ── BO 习惯 · 楼层板 ─────────────────────────────────────────
     左边蓝方、右边红方：各 4/5 个 Ban 位 + 1~5 楼；中间是选中那一手的意图。
     场次/胜率只来自同赛制历史局，按该局实际红蓝方取数，不把两边混算。 */
  const board = (h.boBoard && h.boBoard.game === selected) ? h.boBoard
    : { game: selected, bans: { blue: [], red: [] }, pick: null, open: {} };
  const otherSide = (side) => (side === 'blue' ? 'red' : 'blue');
  const sideView = (game, side) => {
    const foeSide = game?.foeSide || selectedSide;
    const foeIsSide = foeSide === side;
    const ownSide = foeIsSide ? otherSide(side) : side;
    return {
      picks: (foeIsSide ? game?.foePicks : game?.ownPicks) || [],
      bans: (foeIsSide ? game?.foeBans : game?.ownBans) || [],
      win: game?.result === 'win' ? ownSide === side
        : game?.result === 'loss' ? ownSide !== side : null,
    };
  };
  const historyBoardGames = historyForFormat.flatMap((item) => item.games || [])
    .filter((game) => gameBans(game) === formatBans);
  /* 没有同赛制历史时，用本场已打的局给出场次/胜率，并在面板上明确标出口径。 */
  const boardGames = historyBoardGames.length ? historyBoardGames
    : (current.games || []).filter((game) => gameBans(game) === formatBans);
  const boardStatScope = historyBoardGames.length
    ? `${historyBoardGames.length} 局同赛制历史` : `本场 ${boardGames.length} 局（无同赛制历史）`;
  const statOf = (list) => {
    const decided = list.filter((game) => game.win !== null);
    const wins = decided.filter((game) => game.win).length;
    return {
      n: list.length, w: wins, decided: decided.length,
      pct: decided.length ? Math.round(wins / decided.length * 100) : null,
    };
  };
  const statHtml = (stat) => `<span class="boh-an-stat" title="${stat.decided} 局有胜负结果">
    <b class="boh-an-num">${stat.n || '—'}</b><small>场</small>
    <b class="boh-an-num ${stat.pct !== null && stat.pct >= 70 ? 'is-good' : ''}">${stat.pct === null ? '—' : `${stat.pct}%`}</b><small>胜率</small>
  </span>`;
  /* 攻方组合/英雄由本方拿齐，受方由对面拿齐；两端都按楼层板上的颜色取数。 */
  const relationStat = (side, attackers, defenders) => {
    const matched = boardGames.filter((game) => {
      const mine = sideView(game, side).picks;
      const theirs = sideView(game, otherSide(side)).picks;
      return attackers.every((hero) => mine.includes(hero))
        && defenders.every((hero) => theirs.includes(hero));
    });
    return statOf(matched.map((game) => ({ ...game, win: sideView(game, side).win })));
  };
  const comboStat = (side, combo) => relationStat(side, combo.heroes, []);
  const heroStat = (side, hero) => relationStat(side, [hero], []);
  const focusFaces = (combo, focus) => combo.heroes.map((hero) => {
    const tile = boHero(h, hero);
    return hero === focus ? `<span class="boh-an-focus">${tile}</span>` : tile;
  }).join('<i class="bgv-boh-plus">+</i>');
  const faceList = (heroes) => heroes.map((hero) => boHero(h, hero)).join('<i class="bgv-boh-plus">+</i>');
  const heroStrip = (heroes) => heroes.map((hero) => boHero(h, hero)).join('');
  /* 可折叠的一层；prefix 让 Ban 与楼层的展开状态各自独立记忆。 */
  const fold = (prefix, key, label, meta, body, cls = '') => `<details class="boh-fold ${cls}" data-boh-fold="${prefix}-${key}" ${board.open && board.open[`${prefix}-${key}`] ? 'open' : ''}>
    <summary><b>${label}</b><span>${meta}</span></summary>
    <div class="boh-fold-body">${body}</div>
  </details>`;

  /* Ban 的三层判断：视角翻到「被 ban 的英雄若给对手用」。
     - 胜率/场次看对手方拿这个英雄的表现；
     - 想拿组合看对手方想拿的组合；
     - 命中克制看这个英雄克不克 ban 方自己这局的英雄/组合。 */
  const banIntentFolds = (side, index, hero) => {
    const denied = otherSide(side);
    const prefix = `ban-${side}-${index}`;
    const folds = [];
    const wants = poolCombos.filter((combo) => combo.heroes.includes(hero))
      .sort((a, b) => comboStat(denied, b).n - comboStat(denied, a).n);
    if (wants.length) {
      folds.push(fold(prefix, 'want', `${boSideLabel(denied)}想拿组合`, `${wants.length} 组`, `<div class="boh-an-list">${wants.slice(0, 4).map((combo) => `<div class="boh-an-row is-combo">
        ${focusFaces(combo, hero)}
        <div class="boh-an-row-meta">${statHtml(comboStat(denied, combo))}<small>${boSideLabel(denied)}想拿 · 被 ban 掉</small></div>
      </div>`).join('')}</div>`, 'is-combo'));
    }
    const hs = heroStat(denied, hero);
    if (hs.n) {
      const hot = hs.decided >= 2 && hs.pct !== null && hs.w / hs.decided >= 0.7;
      folds.push(fold(prefix, 'hero', hot ? `${boSideLabel(denied)}高胜率英雄` : `${boSideLabel(denied)}英雄数据`, hs.pct === null ? '—' : `${hs.pct}%`, `<div class="boh-an-row is-hero">
        ${boHero(h, hero)}
        <div class="boh-an-row-meta">${statHtml(hs)}<small>${boSideLabel(denied)}拿到这个英雄时的表现</small></div>
      </div>`, hot ? 'is-hot' : ''));
    }
    const myPicks = cur ? sideView(cur, side).picks : [];
    const deniedPicks = cur ? sideView(cur, denied).picks : [];
    const hits = [];
    const addHit = (attackers, defenders, note) => {
      const key = `${attackers.join('+')}|${defenders.join('+')}`;
      if (hits.some((hit) => hit.key === key)) return;
      hits.push({ key, attackers, defenders, note, stat: relationStat(denied, attackers, defenders) });
    };
    for (const rule of heroRules) {
      if (rule.attacker !== hero) continue;
      if (myPicks.includes(rule.defender)) addHit([hero], [rule.defender], rule.note);
      const defCombo = resolveCombo(rule.defender);
      if (defCombo && defCombo.heroes.every((item) => myPicks.includes(item))) {
        addHit([hero], defCombo.heroes, defCombo.name || rule.defender);
      }
    }
    for (const rule of comboRules) {
      if (!rule.attacker.heroes.includes(hero)) continue;
      if (!rule.attacker.heroes.every((item) => item === hero || deniedPicks.includes(item))) continue;
      if (!rule.defender.heroes.every((item) => myPicks.includes(item))) continue;
      addHit(rule.attacker.heroes, rule.defender.heroes, rule.defender.name || '');
    }
    if (hits.length) {
      folds.push(fold(prefix, 'counter', `命中克制 · 克${boSideLabel(side)}`, `${hits.length} 条`, `<div class="boh-an-list">${hits.map((hit) => `<div class="boh-an-row is-counter">
        <span class="boh-an-side">${faceList(hit.attackers)}</span>
        <span class="boh-an-arrow"><i>克制</i><b>→</b></span>
        <span class="boh-an-side is-def">${faceList(hit.defenders)}</span>
        <div class="boh-an-row-meta">${statHtml(hit.stat)}${coachNote(hit.note) ? `<small>${esc(coachNote(hit.note))}</small>` : ''}</div>
      </div>`).join('')}</div>`, 'is-counter'));
    }
    return `<div class="boh-ban-intent">
      <div class="boh-ban-intent-head"><span class="boh-an-kicker is-${denied}">${boSideLabel(denied)}视角</span>${glyph('ban', { label: '被禁英雄', size: 18 })}<b>${esc(hero)}</b></div>
      ${folds.length ? folds.join('') : '<p class="boh-an-none">这个英雄没有命中组合 / 高胜率样本 / 克制关系。</p>'}
    </div>`;
  };

  const banAnalysis = (side, slots) => {
    const bans = cur ? sideView(cur, side).bans : [];
    const pickedPairs = slots.map((index) => ({ index, hero: bans[index] })).filter((item) => item.hero);
    const picked = pickedPairs.map((item) => item.hero);
    if (!picked.length) return `<div class="boh-an-empty">${glyph('ban', { label: '未选 Ban 位', size: 22 })}<b>未选 Ban 位</b></div>`;
    const broken = poolCombos.filter((combo) => combo.heroes.some((hero) => picked.includes(hero)));
    const remaining = [...new Set(broken.flatMap((combo) => combo.heroes))]
      .filter((hero) => !picked.includes(hero));
    const candidates = poolCombos
      .filter((combo) => !combo.heroes.some((hero) => picked.includes(hero))
        && combo.heroes.some((hero) => remaining.includes(hero)))
      .sort((a, b) => comboStat(side, b).n - comboStat(side, a).n);
    return `<div class="boh-an-head"><span class="boh-an-kicker is-${side}">${boSideLabel(side)} · Ban</span><b>${picked.map((hero) => esc(hero)).join(' + ')}</b><small class="boh-an-scope">${boardStatScope}</small></div>
      ${broken.length ? `<div class="boh-an-title">${picked.length > 1 ? `这 ${picked.length} 个 Ban 拆了 ${broken.length} 组：` : '这个 Ban 拆掉的组合：'}</div>
        <div class="boh-an-broken">${broken.slice(0, 6).map((combo) => `<div class="boh-an-combo">
          ${comboFaces(combo, { slashed: combo.heroes.find((hero) => picked.includes(hero)) || '' })}
          <b>${esc(combo.name || combo.heroes.join(' + '))} 被拆</b>
        </div>`).join('')}</div>`
        : '<p class="boh-an-none">这个 Ban 没有命中组合池里的组合。</p>'}
      ${remaining.length ? `<div class="boh-an-title">被拆之后剩下的英雄：</div>
        <div class="boh-an-remain">${heroStrip(remaining)}</div>
        <div class="boh-an-title">这些英雄可以搭的组合：</div>
        <div class="boh-an-list">${candidates.length ? candidates.slice(0, 4).map((combo) => `<div class="boh-an-row is-combo">
          ${focusFaces(combo, '')}
          <div class="boh-an-row-meta">${statHtml(comboStat(side, combo))}</div>
        </div>`).join('') : '<p class="boh-an-none">暂时没有可搭的组合。</p>'}</div>` : ''}
      ${pickedPairs.map((item) => banIntentFolds(side, item.index, item.hero)).join('')}`;
  };

  const pickAnalysis = (side, index, hero) => {
    const foe = otherSide(side);
    const oppPicks = cur ? sideView(cur, foe).picks : [];
    const myPicks = cur ? sideView(cur, side).picks : [];
    const prefix = `${side}-${index}`;
    const folds = [];
    const combos = poolCombos.filter((combo) => combo.heroes.includes(hero))
      .sort((a, b) => comboStat(side, b).n - comboStat(side, a).n);
    if (combos.length) {
      folds.push(fold(prefix, 'combo', '想选组合', `${combos.length} 组`, `<div class="boh-an-list">${combos.slice(0, 4).map((combo) => `<div class="boh-an-row is-combo">
        ${focusFaces(combo, hero)}
        <div class="boh-an-row-meta">${statHtml(comboStat(side, combo))}<small>含 ${esc(hero)} 的组合</small></div>
      </div>`).join('')}</div>`, 'is-combo'));
    }
    const hs = heroStat(side, hero);
    if (hs.n) {
      const hot = hs.decided >= 2 && hs.pct !== null && hs.w / hs.decided >= 0.7;
      folds.push(fold(prefix, 'hero', hot ? '高胜率英雄' : '英雄数据', hs.pct === null ? '—' : `${hs.pct}%`, `<div class="boh-an-row is-hero">
        ${boHero(h, hero)}
        <div class="boh-an-row-meta">${statHtml(hs)}<small>${hot ? '这个英雄在这边的强势选择' : '这个英雄在这边的历史表现'}</small></div>
      </div>`, hot ? 'is-hot' : ''));
    }
    const hits = [];
    const addHit = (attackers, defenders, note) => {
      const key = `${attackers.join('+')}|${defenders.join('+')}`;
      if (hits.some((hit) => hit.key === key)) return;
      hits.push({ key, attackers, defenders, note, stat: relationStat(side, attackers, defenders) });
    };
    for (const rule of heroRules) {
      if (rule.attacker !== hero) continue;
      if (oppPicks.includes(rule.defender)) addHit([hero], [rule.defender], rule.note);
      const defCombo = resolveCombo(rule.defender);
      if (defCombo && defCombo.heroes.every((item) => oppPicks.includes(item))) {
        addHit([hero], defCombo.heroes, defCombo.name || rule.defender);
      }
    }
    for (const rule of comboRules) {
      if (!rule.attacker.heroes.includes(hero)) continue;
      if (!rule.attacker.heroes.every((item) => myPicks.includes(item))) continue;
      if (!rule.defender.heroes.every((item) => oppPicks.includes(item))) continue;
      addHit(rule.attacker.heroes, rule.defender.heroes, rule.defender.name || '');
    }
    if (hits.length) {
      folds.push(fold(prefix, 'counter', '命中克制', `${hits.length} 条`, `<div class="boh-an-list">${hits.map((hit) => `<div class="boh-an-row is-counter">
        <span class="boh-an-side">${faceList(hit.attackers)}</span>
        <span class="boh-an-arrow"><i>克制</i><b>→</b></span>
        <span class="boh-an-side is-def">${faceList(hit.defenders)}</span>
        <div class="boh-an-row-meta">${statHtml(hit.stat)}${coachNote(hit.note) ? `<small>${esc(coachNote(hit.note))}</small>` : ''}</div>
      </div>`).join('')}</div>`, 'is-counter'));
    }
    return `<div class="boh-an-head"><span class="boh-an-kicker is-${side}">${boSideLabel(side)} · ${index + 1} 楼</span><b>${esc(hero)}</b><small class="boh-an-scope">${boardStatScope}</small></div>
      ${folds.length ? folds.join('') : '<p class="boh-an-none">这个英雄没有命中组合、高胜率样本或克制规则。</p>'}`;
  };

  const banCell = (side, index) => {
    const bans = cur ? sideView(cur, side).bans : [];
    const hero = bans[index] || '';
    const on = (board.bans?.[side] || []).includes(index);
    return `<button type="button" class="boh-cell is-ban ${hero ? 'has-hero' : ''} ${on ? 'is-on' : ''}" data-boh-cell data-side="${side}" data-kind="ban" data-index="${index}" aria-pressed="${on}"
      title="${esc(boSideLabel(side))} Ban ${index + 1}${hero ? ` · ${esc(hero)}（已 ban）` : ''}">
      <span class="boh-ban-tag">Ban ${index + 1}</span>
      ${hero ? `<span class="boh-ban-face">${h.portrait(hero, 'boh-cell-face')}</span>` : '<span class="boh-cell-empty">—</span>'}
      <b>${esc(hero || '未记录')}</b>
    </button>`;
  };
  const pickCell = (side, index) => {
    const picks = cur ? sideView(cur, side).picks : [];
    const hero = picks[index] || '';
    const on = !!(board.pick && board.pick.side === side && board.pick.index === index);
    const stat = hero ? heroStat(side, hero) : null;
    const highWin = !!(stat?.decided && stat.w / stat.decided >= 0.7);
    return `<button type="button" class="boh-cell is-pick ${on ? 'is-on' : ''} ${highWin ? 'is-high-win' : ''}" data-boh-cell data-side="${side}" data-kind="pick" data-index="${index}" aria-pressed="${on}"
      title="${esc(boSideLabel(side))} ${index + 1} 楼${hero ? ` · ${esc(hero)}${highWin ? ' · 高胜率' : ''}` : ''}">
      <span class="boh-floor">${index + 1} 楼</span>
      ${hero ? h.portrait(hero, 'boh-cell-face') : '<span class="boh-cell-empty">—</span>'}
      <span class="boh-pick-copy"><b>${esc(hero || '未记录')}</b><small>${stat && stat.n ? `${stat.n} 场 · ${stat.pct === null ? '—' : `${stat.pct}%`}` : '—'}</small></span>
      ${highWin ? '<span class="boh-high-win-tag" aria-hidden="true">高胜</span>' : ''}
    </button>`;
  };
  const sideBoard = (side) => `<section class="boh-side is-${side}" aria-label="${boSideLabel(side)}">
    <header class="boh-side-head"><b>${boSideLabel(side)}</b><span>${side === 'blue' ? 'BLUE' : 'RED'} SIDE</span></header>
    <div class="boh-bans">${Array.from({ length: formatBans }, (_, index) => banCell(side, index)).join('')}</div>
    <div class="boh-frame"><span class="boh-frame-label">${boSideLabel(side)} 1–5 楼</span>
      ${Array.from({ length: 5 }, (_, index) => pickCell(side, index)).join('')}
    </div>
  </section>`;
  const overviewSide = (side) => {
    const picks = cur ? sideView(cur, side).picks : [];
    const oppPicks = cur ? sideView(cur, otherSide(side)).picks : [];
    const combos = poolCombos.filter((combo) => combo.heroes.every((hero) => picks.includes(hero)))
      .sort((a, b) => comboStat(side, b).n - comboStat(side, a).n);
    const hits = [];
    const addHit = (hit) => {
      const key = hit.type === 'combo'
        ? `combo|${hit.attacker.key}|${hit.defender.key}`
        : `hero|${hit.attacker}|${hit.defender}`;
      if (hits.some((item) => item.key === key)) return;
      hits.push({
        ...hit, key,
        stat: relationStat(side,
          hit.type === 'combo' ? hit.attacker.heroes : [hit.attacker],
          hit.type === 'combo' ? hit.defender.heroes : [hit.defender]),
      });
    };
    for (const rule of heroRules) {
      if (!picks.includes(rule.attacker)) continue;
      if (oppPicks.includes(rule.defender)) addHit({ type: 'hero', attacker: rule.attacker, defender: rule.defender, note: rule.note });
      const defCombo = resolveCombo(rule.defender);
      if (defCombo && defCombo.heroes.every((hero) => oppPicks.includes(hero))) {
        addHit({ type: 'combo', attacker: { heroes: [rule.attacker], key: rule.attacker }, defender: defCombo, note: rule.note });
      }
    }
    for (const rule of comboRules) {
      if (!rule.attacker.heroes.every((hero) => picks.includes(hero))) continue;
      if (!rule.defender.heroes.every((hero) => oppPicks.includes(hero))) continue;
      addHit({ type: 'combo', attacker: rule.attacker, defender: rule.defender, note: rule.note });
    }
    const highWins = picks.map((hero) => ({ hero, stat: heroStat(side, hero) }))
      .filter((item) => item.stat.decided && item.stat.w / item.stat.decided >= 0.7)
      .sort((a, b) => b.stat.w / b.stat.decided - a.stat.w / a.stat.decided || b.stat.n - a.stat.n);
    const block = (key, title, body) => `<section class="boh-overview-block">
      <h4>${title}</h4>${body}
    </section>`;
    return `<section class="boh-overview-side is-${side}" aria-label="${boSideLabel(side)}总览">
      <header class="boh-overview-head"><h3>${boSideLabel(side)}</h3><span>${side === 'blue' ? 'BLUE' : 'RED'} SIDE</span></header>
      ${block('combo', '组合', combos.length ? `<div class="boh-overview-list">${combos.slice(0, 4).map((combo) => `<div class="boh-overview-row is-combo">
        ${comboFaces(combo)}<div class="boh-overview-meta">${statHtml(comboStat(side, combo))}</div>
      </div>`).join('')}</div>` : '<p class="boh-an-none">这局没有命中已保存的组合。</p>')}
      ${block('counter', '克制关系', hits.length ? `<div class="boh-overview-list">${hits.slice(0, 4).map((hit) => `<div class="boh-overview-row is-counter">
        ${counterFlow(hit)}<div class="boh-overview-meta">${statHtml(hit.stat)}${coachNote(hit.note) ? `<small>${esc(coachNote(hit.note))}</small>` : ''}</div>
      </div>`).join('')}</div>` : '<p class="boh-an-none">这局没有命中克制规则。</p>')}
      ${block('win', '高胜率英雄', highWins.length ? `<div class="boh-overview-wins">${highWins.map((item) => `<div class="boh-overview-win">
        ${boHero(h, item.hero)}<span><b>${item.stat.pct}%</b><small>${item.stat.n} 场</small></span>
      </div>`).join('')}</div>` : '<p class="boh-an-none">没有达到 70% 胜率的英雄。</p>')}
    </section>`;
  };
  const overviewHtml = `<div class="boh-overview" aria-label="蓝红双方 BP 总览">
    ${overviewSide('blue')}${overviewSide('red')}
    <p class="boh-overview-scope">胜率口径：${esc(boardStatScope)}；70% 及以上标为高胜率。</p>
  </div>`;
  const boardBans = [...(board.bans?.blue || []), ...(board.bans?.red || [])];
  const analysisHtml = board.pick && (sideView(cur, board.pick.side).picks[board.pick.index] || cur)
    ? pickAnalysis(board.pick.side, board.pick.index, sideView(cur, board.pick.side).picks[board.pick.index] || '未记录')
    : boardBans.length
      ? banAnalysis(board.bans.blue.length ? 'blue' : 'red', board.bans.blue.length ? board.bans.blue : board.bans.red)
      : overviewHtml;

  /* 这一块现在是「这一把的 BP 意图」，不是历史习惯统计：
     筛选只保留本场视角和切局，历史样本范围 / 时间窗那些入口拿掉了。 */
  const stepButtons = `<div class="bgv-boh-step" role="group" aria-label="切换局次">
    <button type="button" class="bgx-btn control" data-boh-step="-1" ${selected <= 1 ? 'disabled' : ''}>${glyph('clock', { label: '上一把', size: 18 })} 上一把</button>
    <button type="button" class="bgx-btn control" data-boh-step="1" ${selected >= bestOf ? 'disabled' : ''}>${glyph('clock', { label: '下一把', size: 18 })} 下一把</button>
  </div>`;

  const rail = slots.map((slot) => {
    const cell = stats.get(slot);
    const game = (current.games || []).find((item) => Number(item.index) === slot);
    /* 每一把按它自己的红蓝方预览，不跟当前筛选串味。 */
    const slotSide = game?.foeSide || selectedSide;
    const slotGames = (cell.allGames || cell.games).filter((item) => !item.foeSide || item.foeSide === slotSide);
    const floor = boPickGroups(slotSide, boSideOrders(slotSide, formatBans))[0];
    const first = topEntries(pooledBySide(slotSide), (item) => floor.slots.map((i) => item.foePicks?.[i]), 1)[0];
    const firstKey = game && (!game.foeSide || game.foeSide === slotSide)
      ? floor.slots.map((i) => game.foePicks?.[i]).join('|') : '';
    const same = !!(game && first && firstKey === first.key);
    const flag = game ? (!first ? '新' : same ? '照做' : '变招') : '';
    return `<button type="button" class="bgv-boh-slot ${slot === selected ? 'is-on' : ''} ${game ? (first ? (same ? 'is-same' : 'is-diff') : 'is-new') : ''}"
      data-bgx-boslot="${slot}" aria-pressed="${slot === selected}"
      title="${esc(gameWord(slot))} · ${boSideLabel(slotSide)} · ${slotGames.length || 0} 个样本${first ? ` · ${first.heroes.map((hero) => hero).join(' + ')}` : ''}${flag ? ` · ${flag}` : ''}">
      <b>${esc(gameWord(slot))}</b>
    </button>`;
  }).join('');

  const winRate = (value) => (value.decided ? `${value.winCount}/${value.decided} · ${Math.round(value.winCount / value.decided * 100)}%` : '—');
  const subRate = (list) => {
    const decided = list.filter((game) => game.result === 'win' || game.result === 'loss').length;
    const wins = list.filter((game) => game.result === 'win').length;
    return decided ? `${wins}/${decided} · ${Math.round(wins / decided * 100)}%` : '—';
  };
  const metaFor = (countValue, list, total) => {
    if (total <= 1) {
      const result = list[0]?.result;
      return `唯一 1 场${result === 'win' ? ' · 胜' : result === 'loss' ? ' · 负' : ''}`;
    }
    return `${countValue}/${total} 次 · ${subRate(list)}`;
  };

  const banCount = formatBans;
  const formatLabel = `${banCount === 5 ? 20 : 18} 手 · ${banCount} Ban`;
  const orders = boSideOrders(selectedSide, banCount);
  const floorGroups = boPickGroups(selectedSide, orders);
  const banRows = Array.from({ length: banCount }, (_, index) => {
    const top = topEntries(pooledGames, (game) => game.foeBans?.[index], 1)[0] || null;
    const subset = top ? pooledGames.filter((game) => game.foeBans?.[index] === top.key) : [];
    const phase = index < 2 ? '一阶段' : '二阶段';
    return {
      order: orders.bans[index] || 0, kind: 'ban', slot: index,
      label: `ban${index + 1}`, phase, top,
      tiles: top ? boHero(h, top.key, 'is-ban') : '<span class="bgv-boh-none">—</span>',
      meta: top ? `${phase} · ${metaFor(top.count, subset, pooledGames.length)}` : '没有记录',
    };
  });
  const pickRows = floorGroups.map((floor) => {
    const pool = pooledGames.filter((game) => floor.slots.every((i) => game.foePicks?.[i]));
    const top = topEntries(pool, (game) => floor.slots.map((i) => game.foePicks[i]), 1)[0] || null;
    const subset = top ? pool.filter((game) => floor.slots.map((i) => game.foePicks[i]).join('|') === top.key) : [];
    return {
      order: floor.orders[0] || 0, kind: 'pick', slots: floor.slots,
      label: floor.label, phase: floor.phase, counter: floor.counter, top,
      tiles: top ? top.heroes.map((hero) => boHero(h, hero)).join('') : '<span class="bgv-boh-none">—</span>',
      meta: top ? `${floor.phase} · ${metaFor(top.count, subset, pooledGames.length)}` : '没有记录',
    };
  });
  const bpRows = [...banRows, ...pickRows].sort((a, b) => a.order - b.order);

  /* 把「抢 / 拆 / 克」按局汇总：一局里抢到两组也只算一局，但组合明细各自计数。 */
  const emptyIntents = () => ({ steals: [], breaks: [], counters: [] });
  /* 每个楼层自己算「这一手发生了什么」：抢整组 / 拆一张 / 被规则克制。 */
  const rowIntents = (row, games) => {
    const steals = new Map();
    const breaks = new Map();
    const counters = new Map();
    const add = (bucket, key, item) => {
      const hit = bucket.get(key) || { ...item, count: 0 };
      hit.count += 1;
      bucket.set(key, hit);
    };
    for (const game of games) {
      if (row.kind === 'ban') {
        const hero = game.foeBans?.[row.slot];
        if (!hero || !comboHeroes.has(hero)) continue;
        const combo = comboForHero(hero);
        if (combo) add(breaks, `${combo.key}|${hero}|ban`, { hero, via: 'ban', combo });
        continue;
      }
      const picked = (row.slots || []).map((index) => game.foePicks?.[index]).filter(Boolean);
      if (!row.slots || picked.length !== row.slots.length) continue;
      const foePicks = game.foePicks || [];
      const lastPick = (hero) => foePicks.lastIndexOf(hero);
      /* 组合可能跨楼层拿齐：算在「最后一块」所在的那一行，不要求同一层凑齐。 */
      for (const combo of combosStolen(game)) {
        const last = Math.max(...combo.heroes.map(lastPick));
        if (last >= 0 && row.slots.includes(last)) add(steals, combo.key, { combo });
      }
      /* 单抢一张 → 拆；已经被整组抢走的英雄不重复算。 */
      const stolenHeroes = new Set(combosStolen(game).flatMap((combo) => combo.heroes));
      for (const hero of picked) {
        if (!comboHeroes.has(hero) || stolenHeroes.has(hero)) continue;
        const combo = comboForHero(hero);
        if (combo) add(breaks, `${combo.key}|${hero}|pick`, { hero, via: 'pick', combo });
      }
      /* 克制规则里的攻方也可能跨楼层；算在攻方最后一块所在行。 */
      for (const hit of combosCountered(game)) {
        const last = hit.type === 'hero'
          ? lastPick(hit.attacker)
          : Math.max(...hit.attacker.heroes.map(lastPick));
        if (last < 0 || !row.slots.includes(last)) continue;
        const key = hit.type === 'combo'
          ? `combo|${hit.attacker.key}|${hit.defender.key}`
          : `hero|${hit.attacker}|${hit.combo.key}|${hit.defender}`;
        add(counters, key, hit);
      }
    }
    return {
      steals: [...steals.values()].sort((a, b) => b.count - a.count),
      breaks: [...breaks.values()].sort((a, b) => b.count - a.count),
      counters: [...counters.values()].sort((a, b) => b.count - a.count),
    };
  };
  const historyIntents = new Map(bpRows.map((row) => [row, rowIntents(row, pooledGames)]));
  const currentIntents = new Map(bpRows.map((row) => [row, cur ? rowIntents(row, [cur]) : emptyIntents()]));
  /* 折叠态只给「ban 拆 / 整组抢 / 被克」；单抢一张不单独刷一行角标，
     避免每层 pick 都挂一个「拆」，需要时在已有角标的展开面板里看。 */
  const hasIntents = (intents) => !!(intents && (
    intents.steals.length
    || intents.counters.length
    || intents.breaks.some((item) => item.via === 'ban')
  ));
  const intentTotal = (list) => list.reduce((sum, item) => sum + (item.count || 1), 0);
  const intentBadges = (intents) => {
    if (!hasIntents(intents)) return '';
    const badges = [];
    if (intents.steals.length) badges.push(`<span class="bgv-boh-intent-badge is-steal" title="点开看整组被抢的组合">抢 ${intentTotal(intents.steals)}</span>`);
    if (intents.breaks.length) badges.push(`<span class="bgv-boh-intent-badge is-break" title="点开看哪张被 ban / 哪组被拆">拆 ${intentTotal(intents.breaks)}</span>`);
    if (intents.counters.length) badges.push(`<span class="bgv-boh-intent-badge is-counter" title="点开看攻方 → 受方">克 ${intentTotal(intents.counters)}</span>`);
    return `${badges.join('')}<i class="bgv-boh-intent-caret" aria-hidden="true">▾</i>`;
  };
  const intentPanel = (intents) => {
    if (!hasIntents(intents)) return '';
    const section = (label, cls, list, render) => list.length ? `<div class="bgv-boh-intent-sec">
      <b class="${cls}">${label}</b>
      ${list.slice(0, 3).map((item) => `<span class="bgv-boh-intent-item">${render(item)}${(item.count || 1) > 1 ? `<small>×${item.count}</small>` : ''}</span>`).join('')}
      ${list.length > 3 ? `<small class="bgv-boh-intent-more">+${list.length - 3}</small>` : ''}
    </div>` : '';
    return `<div class="bgv-boh-intent-panel" hidden>
      ${section('抢', 'is-steal', intents.steals, (item) => stealFlow(item.combo))}
      ${section('拆', 'is-break', intents.breaks, breakFlow)}
      ${section('克', 'is-counter', intents.counters, counterFlow)}
    </div>`;
  };
  const boDetailRow = (label, tiles, meta, cls, intents) => {
    if (!hasIntents(intents)) return boRow(label, tiles, meta, cls);
    return `<div class="bgv-boh-details">
      <div class="bgv-boh-row ${cls}" role="button" tabindex="0" aria-expanded="false" data-boh-intent-toggle>
        <span>${label}</span>
        <div class="bgv-boh-tiles">${tiles}${intentBadges(intents)}</div>
        <em>${meta}</em>
      </div>
      ${intentPanel(intents)}
    </div>`;
  };
  const rulesHintHtml = rulesHint
    ? `${esc(rulesHint)}${rulesHint === '克制规则未配置' || rulesHint === '克制规则未匹配组合池'
      ? ' <a class="bgv-boh-rulelink" href="#rules">去检查 →</a>' : ''}`
    : '';
  const intent = (() => {
    if (poolHint) return { note: `<p class="bgv-boh-intent-note">${esc(poolHint)}${poolHint === '组合池还没有保存组合'
      ? ' <a class="bgv-boh-rulelink" href="#combo-pool">去保存组合 →</a>' : ''}</p>` };
    let stealGames = 0;
    let breakGames = 0;
    let counterGames = 0;
    for (const game of pooledGames) {
      if (combosStolen(game).length) stealGames += 1;
      if (combosBroken(game).length) breakGames += 1;
      if (combosCountered(game).length) counterGames += 1;
    }
    const bits = [
      stealGames ? `抢 ${stealGames} 场` : '',
      breakGames ? `拆 ${breakGames} 场` : '',
      counterGames ? `被克 ${counterGames} 场` : '',
    ].filter(Boolean);
    const note = bits.length || rulesHintHtml
      ? `<p class="bgv-boh-intent-note">对面组合意图：${bits.join(' · ')}${bits.length && rulesHintHtml ? ' · ' : ''}${rulesHintHtml}</p>`
      : '';
    return { note };
  })();

  const historyBlock = pooledGames.length ? `
    ${intent.note}
    ${bpRows.map((row) => boDetailRow(`#${row.order} ${row.label}`, row.tiles, row.meta, row.counter ? 'is-counter' : '', historyIntents.get(row))).join('')}
    ${boRow('常用体系', pooledStat.tags.length ? pooledStat.tags.map((tag) => `<span class="bgv-boh-tag">${esc(tag.key)}<b>${tag.count}</b></span>`).join('') : '<span class="bgv-boh-none">—</span>', '')}
  ` : `<div class="bgv-boh-empty">这个红蓝方、这个赛制还没有历史样本。</div>`;

  const currentKeyFor = (row) => {
    if (!cur) return '';
    if (row.kind === 'ban') return cur.foeBans?.[row.slot] || '';
    const values = row.slots.map((i) => cur.foePicks?.[i]).filter(Boolean);
    return values.length === row.slots.length ? values.join('|') : '';
  };
  const currentTilesFor = (row) => {
    if (!cur) return '<span class="bgv-boh-none">—</span>';
    if (row.kind === 'ban') return cur.foeBans?.[row.slot] ? boHero(h, cur.foeBans[row.slot], 'is-ban') : '<span class="bgv-boh-none">—</span>';
    return row.slots.map((i) => cur.foePicks?.[i]).filter(Boolean).map((hero) => boHero(h, hero)).join('') || '<span class="bgv-boh-none">—</span>';
  };
  let compared = 0;
  let matches = 0;
  const currentRows = bpRows.map((row) => {
    const key = currentKeyFor(row);
    const same = !!(key && row.top && row.top.key === key);
    if (key && row.top) {
      compared += 1;
      if (same) matches += 1;
    }
    return boDetailRow(`#${row.order} ${row.label}`, currentTilesFor(row), key ? (same ? '照做' : '变招') : '未记录', row.counter ? 'is-counter' : '', currentIntents.get(row));
  }).join('');
  const currentTags = cur ? topEntries([cur], (game) => game.foeTags?.[0], 2) : [];
  const currentBlock = !cur
    ? `<div class="bgv-boh-empty">本场没打到这一把${bestOf > (current.games || []).length ? '（大场已结束）' : ''}。</div>`
    : `
      ${currentRows}
      ${boRow('常用体系', currentTags.length ? currentTags.map((tag) => `<span class="bgv-boh-tag">${esc(tag.key)}</span>`).join('') : '<span class="bgv-boh-none">—</span>', '')}
      ${boRow('这一把', `<b class="bgv-boh-rate ${cur.result === 'win' ? 'is-win' : cur.result === 'loss' ? 'is-loss' : ''}">${cur.result === 'win' ? '胜' : cur.result === 'loss' ? '负' : '—'}</b>`, '')}
      ${compared ? `<p class="bgv-boh-verdict ${matches === compared ? 'is-same' : 'is-diff'}">
        ${pooledGames.length < 2 ? '对照样本少（1 局），只作方向参考；' : ''}BP 顺序：${matches}/${compared} 个节点与历史一致${matches === compared ? '，这一把延续了同样的意图。' : '，变化的节点就是这把要看的重点。'}
      </p>` : ''}
    `;

  const sampleMap = new Map();
  for (const item of historyForFormat) {
    if (!(item.games || []).some((game) => gameBans(game) === formatBans
      && (!game.foeSide || game.foeSide === selectedSide))) continue;
    const label = `${item.date ? item.date.slice(5) : '—'} ${item.opponent || ''}`.trim();
    sampleMap.set(label, (sampleMap.get(label) || 0) + 1);
  }
  const sampleDates = [...sampleMap].map(([label, n]) => (n > 1 ? `${label} ×${n}` : label));

  return `<section class="bgx-card bgv-boh">
    ${cardHead(esc, '02 BP 意图', '对手这一把，BP 想干什么', '',
      `<span class="bgx-chip">${esc(formatLabel)}</span>`)}
    <div class="bgv-boh-toolbar">${stepButtons}<span class="bgx-spacer"></span><button type="button" class="bgx-btn control" data-bgx-boreset>${glyph('refresh', { label: '重置', size: 18 })} 重置</button></div>
    <div class="bgv-boh-rail">${rail}</div>
    <div class="boh-board-wrap">
      ${sideBoard('blue')}
      <section class="boh-analyze" aria-label="蓝红双方 BP 总览或所选英雄意图">${analysisHtml}</section>
      ${sideBoard('red')}
    </div>
    <div class="boh-board-foot">
      ${intent.note || ''}
      ${compared ? `<p class="bgv-boh-verdict ${matches === compared ? 'is-same' : 'is-diff'}">
        ${pooledGames.length < 2 ? '对照样本少（1 局），只作方向参考；' : ''}BP 顺序：${matches}/${compared} 个节点与历史一致${matches === compared ? '，这一把延续了同样的意图。' : '，变化的节点可按楼层点开看。'}
      </p>` : ''}
      ${sampleDates.length ? `<div class="bgv-boh-samples">样本：${sampleDates.map((item) => `<span>${esc(item)}</span>`).join('')}</div>` : ''}
    </div>
  </section>`;
}



/* ── 03 阵容体系 ───────────────────────────────────────────── */

function distributionPanel(block, side, esc, title, games, h) {
  const rows = (block.distribution || {})[side] || {};
  const known = games.filter((game) => (game[side] || {}).types && Object.keys(game[side].types).length).length;
  const lanePanel = (lane) => {
    const list = rows[lane] || [];
    const total = list.reduce((sum, row) => sum + (row.n || 0), 0);
    if (!total) return '<div class="bgv-type-empty">没有名单</div>';
    const cards = list.map((row) => {
      const heroes = new Map();
      for (const game of games) {
        for (const item of ((game[side] || {}).heroes || [])) {
          if (item.lane !== lane || item.type !== row.type || !item.hero) continue;
          heroes.set(item.hero, (heroes.get(item.hero) || 0) + 1);
        }
      }
      const faces = [...heroes.entries()].map(([hero, n]) => `<span class="bgv-type-hero" title="${esc(`${hero} · ${n} 局`)}">
        ${h.portrait(hero, 'bgv-type-face')}${n > 1 ? `<em>×${n}</em>` : ''}
      </span>`).join('');
      return `<article class="bgv-type-card">
        <header><h5>${esc(row.type)}</h5><span>${row.n} 局 · ${row.pct == null ? '—' : `${Math.round(row.pct)}%`}</span></header>
        <div class="bgv-type-heroes">${faces || '<span class="bgv-type-empty">头像缺失</span>'}</div>
      </article>`;
    }).join('');
    return `<section class="bgv-type-lane">
      <h4>${esc(LANE_SHORT[lane] || lane)}<small>${total} 局</small></h4>
      <div class="bgv-type-grid">${cards}</div>
    </section>`;
  };
  return `<section class="xw-mod bgv-mod">
    <div class="xw-mod-head">
      <div class="xw-mod-copy"><span class="xw-mod-kicker">${side === 'own' ? '我方' : '对方'}</span>
        <h3>${esc(title)}</h3></div>
      <span class="xw-mod-meta">${known} 局有名单</span>
    </div>
    <div class="bgv-type-lanes">${LANE_ORDER.map(lanePanel).join('')}</div>
  </section>`;
}

function corePanel(block, side, games, esc) {
  const entries = games.map((game) => ({ game, value: game[side]?.cores }))
    .filter((entry) => typeof entry.value === 'number' && Number.isFinite(entry.value));
  if (!entries.length) return '<div class="bgv-empty">没有核心数数据</div>';
  const values = entries.map((entry) => entry.value);
  const counts = new Map();
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  const dots = entries.map((entry, index) => `<span class="bgv-core-dot is-tone-${entry.value % 3}" style="--core-order:${index}" title="${esc(`第 ${entry.game?.gameIndex || index + 1} 局 · ${entry.value} 核`)}">${entry.value}</span>`).join('');
  const legend = [...counts.entries()].sort((a, b) => a[0] - b[0]).map(([value, n]) =>
    `<span class="bgv-core-key is-tone-${value % 3}"><i></i>${value} 核<b>${n} 局</b><em>${Math.round(n / values.length * 100)}%</em></span>`).join('');
  return `<div class="bgv-core-panel">
    <div class="bgv-core-dots" aria-label="每局核心数">${dots}</div>
    <div class="bgv-core-legend">${legend}</div>
    <p class="bgv-core-note">${values.length} 局 · 平均 ${average.toFixed(1)} 核；一格代表一局。</p>
  </div>`;
}

/* 英雄池交叉：三个方框——我方队名 / 敌方队名 / 公共英雄。
   * 我方框只放我方用过的，敌方框只放对方用过的，两队都用的单独进公共英雄框；
   * 每个头像上的身份标签常驻，不靠 hover、也不在窄屏隐藏。
   * 只有这三种归属标签，不再有「新东西」第四类；上游给 none 时按这批局里
   * 实际谁选出过归侧。大场页与战队详情共用这份版面。 */
export function renderHeroPoolCross(rows, h, names = {}, outcomeScope = 'all') {
  const { esc } = h;
  const ownName = names.ownName || '本队';
  const foeName = names.foeName || '对手';
  const tag = { own: '我方熟', foe: '对方熟', both: '公共英雄' };
  const order = { both: 0, own: 1, foe: 2 };
  const statusOf = (row) => {
    if (row.ownApps && row.foeApps) return 'both';
    if (row.ownApps) return 'own';
    if (row.foeApps) return 'foe';
    if (row.ownPick && row.foePick) return 'both';
    if (row.ownPick) return 'own';
    if (row.foePick) return 'foe';
    return row.status === 'foe' ? 'foe' : row.status === 'both' ? 'both' : 'own';
  };
  const sorted = (rows || []).map((row) => ({...row, status: statusOf(row)}))
    .sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9)
      || (b.ownApps + b.foeApps) - (a.ownApps + a.foeApps)
      || String(a.hero).localeCompare(String(b.hero), 'zh-CN'));
  const outcome = (row) => {
    const wins = Number(outcomeScope === 'own' ? row.ownWins : outcomeScope === 'foe' ? row.foeWins : row.wins) || 0;
    const losses = Number(outcomeScope === 'own' ? row.ownLosses : outcomeScope === 'foe' ? row.foeLosses : row.losses) || 0;
    if (!wins && !losses) return '';
    const mixed = wins > 0 && losses > 0;
    const label = mixed ? `${wins}胜${losses}负` : wins ? '胜' : '负';
    const tone = mixed ? 'mixed' : wins ? 'win' : 'loss';
    const scopeName = outcomeScope === 'own' ? '我方' : outcomeScope === 'foe' ? '对方' : '总';
    return `<span class="bgv-pool-outcome is-${tone}" aria-label="${esc(`${scopeName}视角 · ${label}`)}">${label}</span>`;
  };
  const zone = (list) => list.map((row) => `<div class="xw-hero is-${esc(row.status)}">
      ${h.portrait(row.hero, 'xw-face-img')}
      ${outcome(row)}
      <b>${esc(row.hero)}</b>
      <small>${esc([row.lane, row.type].filter(Boolean).join(' · '))}</small>
      <small class="bgv-pool-count">我 <em>${fmtCount(row.ownApps)}</em> · 敌 <em>${fmtCount(row.foeApps)}</em></small>
      <span class="bgv-pool-tag is-${esc(row.status)}">${tag[row.status]}</span>
    </div>`).join('');
  const ownRows = sorted.filter((r) => r.status === 'own');
  const foeRows = sorted.filter((r) => r.status === 'foe');
  const bothRows = sorted.filter((r) => r.status === 'both');
  const panel = (side, name, sub, list) => `<section class="bgv-poolteam is-${side}">
      <header><b>${esc(name)}</b><span>${list.length} 个</span></header>
      <p>${esc(sub)}</p>
      <div class="xw-pool bgv-pool-team">${zone(list)}${list.length ? '' : '<span class="bgv-poolteam-empty">没有可用记录。</span>'}</div>
    </section>`;
  return `<div class="bgv-poolteam-grid">
      ${panel('own', ownName, '只有这支战队用过的英雄', ownRows)}
      ${panel('foe', foeName, '只有这支战队用过的英雄', foeRows)}
      ${panel('both', '公共英雄', '两队都用过的英雄，单独成框', bothRows)}
    </div>`;
}

function fmtCount(v) {
  return Number.isFinite(v) ? v : 0;
}

function poolGroups(games, h, names, outcomeScope = 'all') {
  /* 只统计本场这几局的十人名单：次数与三种归属标签都用同一份口径，
     不混进 series_insight 提供的「历史语料次数」，否则会出现 0/0 却标我方熟。 */
  const rows = new Map();
  for (const game of games) {
    for (const side of ['own', 'foe']) {
      for (const item of ((game[side] || {}).heroes || [])) {
        const key = item.hero;
        if (!key) continue;
        const row = rows.get(key) || {
          hero: key, lane: item.lane || '', type: item.type || '',
          ownApps: 0, foeApps: 0, ownPick: false, foePick: false,
          wins: 0, losses: 0, ownWins: 0, ownLosses: 0, foeWins: 0, foeLosses: 0,
        };
        if (side === 'own') { row.ownApps++; row.ownPick = true; }
        else { row.foeApps++; row.foePick = true; }
        if (game.result === 'win' || game.result === 'loss') {
          const heroWon = side === 'own' ? game.result === 'win' : game.result === 'loss';
          if (heroWon) {
            row.wins++;
            if (side === 'own') row.ownWins++; else row.foeWins++;
          } else {
            row.losses++;
            if (side === 'own') row.ownLosses++; else row.foeLosses++;
          }
        }
        rows.set(key, row);
      }
    }
  }
  return renderHeroPoolCross([...rows.values()], h, names, outcomeScope);
}

export function renderCompSystem(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const block = insight.compSystem;
  if (!block || !(block.games || []).length) {
    return `${cardHead(esc, '03 阵容体系', '这场读不到阵容结构', '')}${emptyState('没有阵容数据，缺十人名单时不给体系结论。')}`;
  }
  const games = block.games.slice().sort((a, b) => (a.gameIndex || 0) - (b.gameIndex || 0));
  const known = games.filter((game) => (game.own || {}).combo || (game.foe || {}).combo).length;

  const anomalies = (block.anomalies || []).map((item) => `<div class="bgv-anom is-${esc(item.level || 'low')}">
    <b>${esc(item.title)}</b><p>${esc(item.detail)}</p>
  </div>`).join('');
  const outcomeScope = ['all', 'own', 'foe'].includes(ui.poolOutcomeScope) ? ui.poolOutcomeScope : 'all';
  /* 赛训组口径：窄屏只放得下「总共 / 我方 / 敌方」，完整语义放到 title / aria-label，
     data-bgx-pool-outcome 的取值不变（all/own/foe），功能语义不跟着改。 */
  const outcomeTabs = `<div class="bgx-seg bgv-pool-scope" role="group" aria-label="英雄池胜负统计视角">${[
    ['all', '总共', '总胜负：双方使用这个英雄时所在队伍的胜负'],
    ['own', '我方', '只看我方：只统计我方使用这个英雄时的胜负'],
    ['foe', '敌方', '只看对方：只统计对方使用这个英雄时的胜负'],
  ].map(([key, label, title]) => `<button type="button" data-bgx-pool-outcome="${key}" aria-pressed="${outcomeScope === key}" title="${esc(title)}" aria-label="${esc(title)}">${label}</button>`).join('')}</div>`;
  const outcomeNote = outcomeScope === 'own' ? '角标只统计我方使用这个英雄时的胜负。'
    : outcomeScope === 'foe' ? '角标只统计对方使用这个英雄时的胜负。'
      : '角标统计双方使用这个英雄时，所在队伍的胜负。';

  return `<section class="bgv-sec">
    <header class="xw-sec-head">
      <div class="xw-sec-title"><span class="xw-sec-num">03</span><h2>阵容体系：双方各自在打什么</h2></div>
      <span class="xw-sec-meta">${count(games.length)} 局 · ${known} 局有名单</span>
    </header>
    <div class="bgv-arch-grid">
      ${distributionPanel(block, 'own', esc, '五路类型', games, h)}
      ${distributionPanel(block, 'foe', esc, '五路类型', games, h)}
    </div>

    <section class="xw-mod bgv-mod bgv-core-mod">
      <div class="xw-mod-head"><div class="xw-mod-copy"><span class="xw-mod-kicker">核心数</span>
        <h3>每局几个核心</h3></div><span class="xw-mod-meta">分均经济 ≥18% 计核心</span></div>
      <div class="bgv-core-pair">
        <div><span class="bgv-chart-label">我方</span>${corePanel(block, 'own', games, esc)}</div>
        <div><span class="bgv-chart-label is-foe">对方</span>${corePanel(block, 'foe', games, esc)}</div>
      </div>
    </section>

    ${anomalies ? `<div class="bgv-anoms">${anomalies}</div>` : ''}

    <section class="bgv-pool-block">
      <header class="xw-sec-head"><div class="xw-sec-title"><h2>英雄池交叉：这场选出来的英雄，谁用过</h2></div>
        <div class="bgv-pool-head-tools">${outcomeTabs}<span class="xw-sec-meta">${count(games.length)} 局 · 只统计这场十人名单</span></div></header>
      <p class="bgv-pool-scope-note">${outcomeNote}</p>
      ${poolGroups(games, h, { ownName: h.ownName, foeName: h.foeName }, outcomeScope)}
    </section>
  </section>`;
}


/* ── 04 阶段与资源 ─────────────────────────────────────────── */
function phaseCell(game, key) {
  const resource = ((game.resources || {})[key]) || {};
  return {
    dragonOwn: resource.dragonOwn, dragonFoe: resource.dragonFoe,
    towerOwn: resource.towerOwn, towerFoe: resource.towerFoe,
    fightN: resource.fightN, fightWon: resource.fightWon,
    fightDecided: resource.fightDecided, fightDecidedWin: resource.fightDecidedWin,
    antiRed: resource.antiRed, antiBlue: resource.antiBlue,
    stolenRed: resource.stolenRed, stolenBlue: resource.stolenBlue,
  };
}

function sumPhase(cells) {
  const out = { dragonOwn: null, dragonFoe: null, towerOwn: null, towerFoe: null,
    fightN: 0, fightWon: 0, fightDecided: 0, fightDecidedWin: 0,
    antiRed: 0, antiBlue: 0, stolenRed: 0, stolenBlue: 0 };
  let dragonKnown = false; let towerKnown = false; let fightKnown = false;
  for (const cell of cells) {
    if (!cell) continue;
    for (const key of ['dragonOwn', 'dragonFoe', 'towerOwn', 'towerFoe']) {
      if (typeof cell[key] === 'number') {
        out[key] = (out[key] || 0) + cell[key];
        if (key.startsWith('dragon')) dragonKnown = true; else towerKnown = true;
      }
    }
    if (typeof cell.fightN === 'number') { fightKnown = true; out.fightN += cell.fightN; }
    if (typeof cell.fightWon === 'number') out.fightWon += cell.fightWon;
    if (typeof cell.fightDecided === 'number') out.fightDecided += cell.fightDecided;
    if (typeof cell.fightDecidedWin === 'number') out.fightDecidedWin += cell.fightDecidedWin;
    for (const key of ['antiRed', 'antiBlue', 'stolenRed', 'stolenBlue']) {
      if (typeof cell[key] === 'number') out[key] += cell[key];
    }
  }
  if (!dragonKnown) { out.dragonOwn = null; out.dragonFoe = null; }
  if (!towerKnown) { out.towerOwn = null; out.towerFoe = null; }
  if (!fightKnown) { out.fightN = null; out.fightWon = null; }
  return out;
}

function vcol(value, max, cls, label) {
  const px = num(value) && max > 0 ? Math.max(5, Math.round(value / max * 92)) : 0;
  const text = num(value) ? String(Math.round(value * 100) / 100) : '—';
  return `<div class="bgx-vcol ${cls}"><b>${text}</b><i style="height:${px}px"></i><span>${label}</span></div>`;
}

function ringSvg(percent, tone = '') {
  const p = num(percent) ? clamp(percent, 0, 100) : 0;
  return `<div class="bgx-ring">
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <circle class="track" cx="50" cy="50" r="42"></circle>
      <circle class="fill ${tone}" cx="50" cy="50" r="42" style="stroke-dasharray:${(p * 2.639).toFixed(1)} 263.9"></circle>
    </svg>
    <span class="bgx-ring-center"><b>${num(percent) ? `${Math.round(percent)}%` : '—'}</b><small>团战胜率</small></span>
  </div>`;
}


export function renderPhase(insight, ui, h) {
  const { esc, fixed, count } = localHelpers(h);
  const games = (insight.phase && insight.phase.perGame) || [];
  if (!games.length) {
    return `${cardHead(esc, '04 执行与资源', '每一段拿了什么，打了几波团', '')}${emptyState('没有阶段数据。')}`;
  }
  const active = PHASE_TABS.some(([key]) => key === ui.phase) ? ui.phase : 'mid';
  const cellsFor = (game) => (active === 'all'
    ? sumPhase(PHASE_KEYS.map((key) => phaseCell(game, key)))
    : phaseCell(game, active));
  const cellList = games.map(cellsFor);
  const withReplay = cellList.filter((cell) => cell
    && (num(cell.dragonOwn) || num(cell.towerOwn) || num(cell.fightN)));
  const sum = (list, key) => {
    const values = list.map((cell) => cell && cell[key]).filter(num);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  };
  const ownDragon = sum(withReplay, 'dragonOwn');
  const foeDragon = sum(withReplay, 'dragonFoe');
  const ownTower = sum(withReplay, 'towerOwn');
  const foeTower = sum(withReplay, 'towerFoe');
  const fightN = sum(withReplay, 'fightN');
  const fightWon = sum(withReplay, 'fightWon');
  const fightDecided = sum(withReplay, 'fightDecided');
  const fightDecidedWin = sum(withReplay, 'fightDecidedWin');
  const fightRate = num(fightDecidedWin) && num(fightDecided) && fightDecided > 0
    ? fightDecidedWin / fightDecided * 100 : null;
  const antiRed = sum(withReplay, 'antiRed');
  const antiBlue = sum(withReplay, 'antiBlue');
  const stolenRed = sum(withReplay, 'stolenRed');
  const stolenBlue = sum(withReplay, 'stolenBlue');
  const dragonMax = Math.max(0.6, ownDragon || 0, foeDragon || 0);
  const towerMax = Math.max(0.6, ownTower || 0, foeTower || 0);
  const buffMax = Math.max(0.4, antiRed || 0, antiBlue || 0);

  const segButton = (key, label, sub) => `<button type="button" class="bgx-seg-btn" data-bgx-phase="${key}" aria-pressed="${key === active}">${label}<span class="bgx-quiet" style="font-weight:500"> · ${sub}</span></button>`;
  const tabs = `<div class="bgx-seg bgx-phase-tabs" role="group" aria-label="阶段">${PHASE_TABS.map(([key, label, sub]) => segButton(key, label, sub)).join('')}</div>`;

  const phaseName = (PHASE_TABS.find(([key]) => key === active) || [])[2] || '全场';
  return `${cardHead(esc, '04 执行与资源', `${esc(phaseName)}这一段：龙、塔、团战、反野`,
    '没有回放事件的项显示「—」，不补 0。', tabs)}
    <div class="bgx-phase-readout">
      <div class="bgx-phase-stat">
        <header><b><i>龙</i>拿了几条龙</b><em>${num(ownDragon) || num(foeDragon) ? `场均 · ${count(withReplay.length)} 局` : '无回放'}</em></header>
        <div class="bgx-vcols">${vcol(ownDragon, dragonMax, '', '我方')}${vcol(foeDragon, dragonMax, 'is-foe', '对方')}</div>
      </div>
      <div class="bgx-phase-stat">
        <header><b><i>塔</i>推了几座塔</b><em>${num(ownTower) || num(foeTower) ? '按建筑去重' : '回放异常'}</em></header>
        <div class="bgx-vcols">${vcol(ownTower, towerMax, '', '我方')}${vcol(foeTower, towerMax, 'is-foe', '对方')}</div>
      </div>
      <div class="bgx-phase-stat">
        <header><b><i>团</i>打了几波团</b><em>${num(fightN) ? `${fixed(fightN, 1)} 波/场` : '无回放'}</em></header>
        <div class="bgx-phase-fight">
          ${ringSvg(fightRate)}
          <div class="bgx-phase-fight-copy">
            <span>场均 <b>${num(fightN) ? fixed(fightN, 1) : '—'}</b> 波</span>
            <span>赢下 <b>${num(fightWon) ? fixed(fightWon, 1) : '—'}</b> 波</span>
            <span>有击杀的团才进分母</span>
          </div>
        </div>
      </div>
      <div class="bgx-phase-stat">
        <header><b><i>野</i>反了几次野</b><em>${num(antiRed) || num(antiBlue) ? '反红 / 反蓝' : '无回放'}</em></header>
        <div class="bgx-vcols">${vcol(antiRed, buffMax, '', '反红')}${vcol(antiBlue, buffMax, 'is-foe', '反蓝')}</div>
        <p class="bgx-phase-buff-note">被反：红 <b>${num(stolenRed) ? fixed(stolenRed, 1) : '—'}</b> · 蓝 <b>${num(stolenBlue) ? fixed(stolenBlue, 1) : '—'}</b></p>
      </div>
    </div>`;
}
