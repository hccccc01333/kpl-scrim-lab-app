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
  return `<div class="bgx-card-head">
    <div class="bgx-card-head-copy">
      <span class="bgx-kicker">${esc(kicker)}</span>
      <h2 class="bgx-card-title">${title}</h2>
      ${lede ? `<p class="bgx-card-lede">${lede}</p>` : ''}
    </div>
    ${meta ? `<div class="bgx-card-meta">${meta}</div>` : ''}
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
function flagCell(value, esc) {
  if (!num(value)) return '<span class="bgv-cell is-na">—</span>';
  return `<span class="bgv-cell ${value ? 'is-good' : 'is-bad'}">${value ? '✓' : '✗'}</span>`;
}

function pairCell(value) {
  if (!value || !num(value.own) || !num(value.foe)) return '<span class="bgv-cell is-na">—</span>';
  const tone = value.own > value.foe ? 'is-good' : value.own < value.foe ? 'is-bad' : '';
  return `<span class="bgv-cell ${tone}"><b>${fmtNumber(value.own)}</b><i>:</i><b>${fmtNumber(value.foe)}</b></span>`;
}

function numberCell(value, reverse = false) {
  if (!num(value)) return '<span class="bgv-cell is-na">—</span>';
  const tone = value === 0 ? '' : (value > 0) !== reverse ? 'is-good' : 'is-bad';
  return `<span class="bgv-cell ${tone}"><b>${fmtSigned(value)}</b></span>`;
}

function pctCell(value) {
  if (!num(value)) return '<span class="bgv-cell is-na">—</span>';
  const tone = value >= 55 ? 'is-good' : value <= 45 ? 'is-bad' : '';
  return `<span class="bgv-cell ${tone}"><b>${Math.round(value)}%</b></span>`;
}

function cellFor(metric, value) {
  if (metric.kind === 'flag') return flagCell(value);
  if (metric.kind === 'pair') return pairCell(value);
  if (metric.kind === 'pct') return pctCell(value);
  return numberCell(value, metric.reverse);
}

function seriesFor(metric) {
  const s = metric.series || {};
  if (metric.kind === 'flag') {
    if (!num(s.n) || !s.n) return '—';
    return `<b>${s.own}/${s.n}</b><small>${num(s.rate) ? `${Math.round(s.rate)}%` : '—'}</small>`;
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

/* 对比列只说「比选中的时间窗增加/下降多少」，不再展示基准值。 */
function baseFor(metric, mode, modeLabel, esc) {
  const ref = `<span class="bgv-base-ref">比${esc(modeLabel)}</span>`;
  const base = (metric.base || {})[mode];
  if (!num(base)) return `<span class="bgv-base is-na">${ref}<em>—</em></span>`;
  let delta = null;
  let unit = '';
  if (metric.kind === 'flag' || metric.kind === 'pair') {
    if (num(metric.series?.rate)) delta = metric.series.rate - base;
    unit = 'pp';
  } else if (metric.kind === 'pct') {
    if (num(metric.series?.value)) delta = metric.series.value - base;
    unit = 'pp';
  } else if (num(metric.series?.value)) {
    delta = metric.series.value - base;
    unit = metric.unit === 'gold' ? '' : ' 次';
  }
  if (!num(delta)) return `<span class="bgv-base is-na">${ref}<em>—</em></span>`;
  const digits = metric.kind === 'num' && metric.unit === 'gold' ? 0 : 1;
  const rounded = digits ? Number(Math.abs(delta).toFixed(digits)) : Math.round(Math.abs(delta));
  if (!rounded) return `<span class="bgv-base">${ref}<em>持平</em></span>`;
  const valueText = digits ? rounded.toFixed(digits) : rounded.toLocaleString('zh-CN');
  const cls = (delta > 0) !== !!metric.reverse ? 'is-up' : 'is-down';
  return `<span class="bgv-base">${ref}<em class="${cls}">${delta > 0 ? '增加' : '下降'} ${valueText}${unit}</em></span>`;
}

function readoutTile(label, value, sub, tone = '') {
  return `<div class="bgv-tile ${tone}"><span>${label}</span><b>${value}</b><small>${sub || ''}</small></div>`;
}

function overviewReadout(insight, metrics) {
  const score = (insight.summary || {}).score || {};
  const byKey = new Map(metrics.map((metric) => [metric.key, metric]));
  const blood = byKey.get('firstBlood')?.series || {};
  const dragonRows = metrics.filter((metric) => metric.key.startsWith('dragon:'));
  const dragonOwn = dragonRows.reduce((sum, metric) => sum + (metric.series?.own || 0), 0);
  const dragonFoe = dragonRows.reduce((sum, metric) => sum + (metric.series?.foe || 0), 0);
  const at10 = byKey.get('at10')?.series || {};
  const towers = byKey.get('towers')?.series || {};
  return `<div class="bgv-readout">
    ${readoutTile('大场', `${score.us ?? 0}<i>:</i>${score.them ?? 0}`, '本场 BO', '')}
    ${readoutTile('一血', num(blood.rate) ? `${blood.own}/${blood.n}` : '—', num(blood.rate) ? `${Math.round(blood.rate)}%` : '无回放')}
    ${readoutTile('中立资源', dragonOwn + dragonFoe ? `${fmtNumber(dragonOwn)} : ${fmtNumber(dragonFoe)}` : '—',
      dragonOwn + dragonFoe ? `我方占比 ${Math.round(dragonOwn / (dragonOwn + dragonFoe) * 100)}%` : '无回放')}
    ${readoutTile('10′ 经济差', num(at10.value) ? fmtSigned(at10.value) : '—', num(at10.n) ? `${at10.n} 局有过程` : '缺过程')}
    ${readoutTile('推塔', num(towers.own) ? `${fmtNumber(towers.own)} : ${fmtNumber(towers.foe)}` : '—',
      num(towers.rate) ? `占 ${Math.round(towers.rate)}%` : '无回放')}
  </div>`;
}

export function renderOverview(insight, ui, h) {
  const { esc, count, pct1 } = localHelpers(h);
  const block = insight.overview;
  if (!block || !(block.metrics || []).length) {
    return `${cardHead(esc, '01 总览与对比', '这场没有可用的过程指标', '先补齐回放或 BP 名单，指标板才有数据。')}${emptyState('没有过程指标。')}`;
  }
  const mode = BASE_MODES.some(([key]) => key === ui.baseMode) ? ui.baseMode : 'format';
  const modeLabel = (BASE_MODES.find(([key]) => key === mode) || [])[1];
  const games = block.games || [];
  const columns = games.length || 1;
  const metricsAll = block.metrics || [];
  const KEY_METRICS = new Set(['firstBlood', 'firstTower', 'at10', 'dragon:暴君', 'dragon:主宰',
    'towers', 'fightRate', 'cut']);
  const groups = [];
  for (const metric of metricsAll) if (!groups.includes(metric.group)) groups.push(metric.group);
  const metricGroup = ui.metricGroup === 'key' || groups.includes(ui.metricGroup) ? ui.metricGroup : 'all';
  const metrics = metricGroup === 'all' ? metricsAll
    : metricGroup === 'key' ? metricsAll.filter((metric) => KEY_METRICS.has(metric.key))
      : metricsAll.filter((metric) => metric.group === metricGroup);

  // 只筛出一个分组时不再重复画分组标题行。
  const showGroupHeads = new Set(metrics.map((metric) => metric.group)).size > 1;
  const groupRows = [];
  let lastGroup = '';
  for (const metric of metrics) {
    if (showGroupHeads && metric.group !== lastGroup) {
      groupRows.push(`<div class="bgv-row is-group"><span>${esc(metric.group)}</span></div>`);
      lastGroup = metric.group;
    }
    const cells = (metric.perGame || []).map((value) => cellFor(metric, value)).join('');
    groupRows.push(`<div class="bgv-row">
      <div class="bgv-metric"><b>${esc(metric.label)}</b><small>${esc(metric.hint || '')}</small></div>
      ${cells}
      <div class="bgv-series">${seriesFor(metric)}</div>
      <div class="bgv-compare">${baseFor(metric, mode, modeLabel, esc)}</div>
    </div>`);
  }

  const head = `<div class="bgv-row is-head">
    <span class="bgv-metric">指标</span>
    ${games.map((game) => `<span class="bgv-col-head">${esc(gameWord(game.gameIndex))}
      <i class="${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</i></span>`).join('')}
    <span class="bgv-series">整场</span>
    <span class="bgv-compare">对比</span>
  </div>`;

  const filterToggle = `<div class="bgx-seg bgv-filter" role="group" aria-label="指标分组">
    ${[['all', '全部'], ['key', '关键 8 项'], ...groups.map((name) => [name, name])].map(([value, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgv-group="${esc(value)}" aria-pressed="${metricGroup === value}">${esc(label)}</button>`).join('')}
  </div>`;
  const filterBar = `<div class="bgv-toolbar">
    ${filterToggle}
    <span class="bgv-toolbar-count">显示 ${count(metrics.length)} / ${count(metricsAll.length)} 项</span>
  </div>`;
  return `${cardHead(esc, '01 总览与对比', `这一场 BO${esc(String(insight.baseline?.bestOf || games.length))}，每一局的关键指标`,
    `一行一个指标、一列一局；对比列写本场比「${esc(modeLabel)}」增加或下降多少。按上面的分组可以只看一段。`,
    `${selectBase(ui)}<span class="bgx-chip">${count(games.length)} 局</span>`)}
    ${overviewReadout(insight, metricsAll)}
    ${filterBar}
    <div class="bgv-board" style="--bgv-cols:${columns}">
      ${head}${groupRows.join('')}
    </div>`;
}

/* ── 01 系列赛走势 ─────────────────────────────────────────── */
/* ── 02 每局 BP 读法 ───────────────────────────────────────── */
function qty(value, total) {
  return `${num(value) ? value : 0}<i>/${num(total) ? total : '—'}</i>`;
}

function readCell(value, total, label, tone = '') {
  return `<div class="bgv-read ${tone}"><b>${qty(value, total)}</b><span>${label}</span></div>`;
}

function lineupRow(h, side, cells, result) {
  const { esc } = h;
  return `<div class="bgv-lineup-side ${side === 'foe' ? 'is-foe' : ''}">
    <span class="bgv-side-label">${side === 'foe' ? '对方' : '我方'}</span>
    <div class="bgv-lineup-heroes">${(cells || []).map((cell) =>
      heroChip(h, cell.hero, [cell.position, cell.archetype].filter(Boolean).join(' · '))).join('') || '<span class="bgx-quiet">没有名单</span>'}</div>
  </div>`;
}

function capsPips(side, caps, core) {
  const items = ['前排', '开团', '控制'].map((key) => ({ label: key, value: num(caps[key]) ? caps[key] : 0 }));
  if (num(core)) items.push({ label: '核心', value: core });
  const dots = (value) => {
    const count = clamp(Math.round(value), 0, 5);
    return `<span class="bgv-cap-dots">${Array.from({ length: 5 },
      (_, index) => `<i class="${index < count ? 'is-on' : ''}"></i>`).join('')}</span>`;
  };
  return `<div class="bgv-caps-side ${side === 'foe' ? 'is-foe' : ''}">
    <span class="bgv-caps-side-label">${side === 'foe' ? '对方' : '我方'}</span>
    <div class="bgv-caps-tiles">${items.map((item) => `<div class="bgv-cap">
      <b>${item.value}</b><span>${item.label}</span>${dots(item.value)}
    </div>`).join('')}</div>
  </div>`;
}

function comboBlock(game, h) {
  const { esc } = h;
  /* 只认赛训组组合池里的双人组合：本局两边都拿到才算「命中」；
     池子为空时不再退回 KPL / 历史常用组合，避免拿任意双人组当组合池。 */
  const poolDoc = h.comboPool && !h.comboPool.builtin ? h.comboPool : null;
  const pool = (poolDoc?.pairs || []).filter((row) => Array.isArray(row.heroes) && row.heroes.length === 2);
  const strengthWord = (value) => value === 'strong' ? '强联动' : value === 'weak' ? '弱联动' : '组合池';
  const sideBlock = (side) => {
    const title = side === 'foe' ? '对方命中组合' : '我方命中组合';
    const empty = (text) => `<div class="bgv-combo-side ${side === 'foe' ? 'is-foe' : ''}">
      <span class="bgv-combo-title">${title}</span><p class="bgv-combo-empty">${text}</p></div>`;
    if (h.comboPool === undefined) return empty('组合池读取中…');
    if (!h.comboPool) return empty('组合池暂不可读');
    if (!pool.length) return empty('组合池还没有保存双人组合');
    const picked = new Set((side === 'foe' ? game.heroesFoe : game.heroesOwn) || []);
    const hits = pool.filter((row) => row.heroes.every((hero) => picked.has(hero)));
    if (!hits.length) return empty('这局没有命中组合池');
    return `<div class="bgv-combo-side ${side === 'foe' ? 'is-foe' : ''}">
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

function banTiles(list, h, side) {
  const { esc } = h;
  const heroes = list || [];
  if (!heroes.length) return '';
  return `<div class="bgv-ban-row ${side === 'foe' ? 'is-foe' : ''}"><span>${side === 'foe' ? '敌 ban' : '我 ban'}</span>
    <div>${heroes.map((hero) => `<span class="bgv-ban-tile">${h.portrait(hero, 'bgv-ban-img')}<b>${esc(hero)}</b></span>`).join('')}</div>
  </div>`;
}

export function renderBp(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const plan = insight.bpPlan;
  if (!plan || !(plan.games || []).length) {
    return `${cardHead(esc, '02 BP 博弈', '这场没有可核对的 BP 记录', '名单缺失时不给结论；先到对局详情补齐 BP。')}${emptyState('没有 BP 名单。')}`;
  }
  const allGames = plan.games;
  const playable = allGames.filter((game) => (game.heroesOwn || []).length && (game.heroesFoe || []).length);
  const filtered = ui.bpGame ? playable.filter((game) => String(game.gameIndex) === String(ui.bpGame)) : playable;
  const games = filtered.length ? filtered : playable;
  if (!playable.length) {
    return `${cardHead(esc, '02 BP 博弈', '这场没有可读的 BP 名单', '名单缺失时不给结论；先到对局详情补齐 BP。')}${emptyState('没有 BP 名单。')}`;
  }
  const series = plan.series || {};
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
  const edgeMean = num(series.edgeMean) ? series.edgeMean : null;
  const edgeWord = edgeMean === null ? '数据不足' : edgeMean >= 0.03 ? '整体占优'
    : edgeMean <= -0.03 ? '整体下风' : '整体接近';
  const cards = games.map((game, index) => {
    const comp = (insight.comp?.games || []).find((item) => String(item.gameIndex) === String(game.gameIndex)) || {};
    const system = (insight.compSystem?.games || []).find((item) => String(item.gameIndex) === String(game.gameIndex)) || {};
    const planTotal = (game.plan?.foeWanted || []).length || 3;
    const planHit = game.plan?.foeHits || 0;
    const banHit = (game.ban?.denyItems || []).filter((item) => item.foePicks > 0).length;
    const pairHit = game.kpl?.own?.pairHits || 0;
    const ownCaps = comp.ownCaps || {};
    const foeCaps = comp.foeCaps || {};
    const core = num((system.own || {}).cores) ? system.own.cores : null;
    const foeCore = num((system.foe || {}).cores) ? system.foe.cores : null;
    const ownCells = (game.signature?.own || []).length
      ? game.signature.own
      : (game.heroesOwn || []).map((hero) => ({ hero, position: '', archetype: '' }));
    const foeCells = (game.signature?.foe || []).length
      ? game.signature.foe
      : (game.heroesFoe || []).map((hero) => ({ hero, position: '', archetype: '' }));
    const open = ui.bpOpen?.[String(game.gameIndex)] ?? (!!ui.bpGame || index === 0);
    return `<details class="bgv-bp-card ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}"
      data-bp-card="${esc(String(game.gameIndex))}" ${open ? 'open' : ''}>
      <summary class="bgv-bp-sum">
        <b>${esc(gameWord(game.gameIndex))}</b>
        <em>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em>
      </summary>
      <div class="bgv-bp-body">
        ${lineupRow(h, 'own', ownCells, game.result)}
        ${lineupRow(h, 'foe', foeCells, game.result)}
        ${comboBlock(game, h)}
        <div class="bgv-bp-reads">
          ${readCell(planHit, planTotal, '对方计划命中', planHit >= Math.ceil(planTotal / 2) ? 'is-good' : '')}
          ${readCell(banHit, 5, 'ban 命中', banHit >= 3 ? 'is-good' : '')}
          ${readCell(pairHit, 10, 'KPL 双人命中', pairHit >= 3 ? 'is-good' : '')}
        </div>
        <div class="bgv-caps-board">${capsPips('own', ownCaps, core)}${capsPips('foe', foeCaps, foeCore)}</div>
        <div class="bgv-bans-visual">${banTiles(game.bansOwn, h, 'own')}${banTiles(game.bansFoe, h, 'foe')}</div>
      </div>
    </details>`;
  }).join('');

  const filterChip = ui.bpGame
    ? `<button type="button" class="bgx-btn" data-bp-game="">看全部 ${count(playable.length)} 局</button>`
    : '';
  return `${cardHead(esc, '02 BP 博弈', `${ui.bpGame ? `第 ${esc(String(ui.bpGame))} 把` : `这 ${count(playable.length)} 局`} BP，${esc(edgeWord)}`,
    '',
    `${filterChip}${ui.bpGame ? `<span class="bgx-chip">第 ${esc(String(ui.bpGame))} 把</span>` : ''}`)}
    <div class="bgv-bp-summary">
      ${readoutTile('拆掉对方组合', `${brokenFoe} 组`, 'ban 或抢掉其中一张', brokenFoe > 0 ? 'is-good' : '')}
      ${readoutTile('我方组合被拆', `${brokenOwn} 组`, '对面 ban 或抢掉', brokenOwn > brokenFoe ? 'is-bad' : '')}
      ${readoutTile('我方拿到首选', `${ownHits} 次`, '对手核心被我们抢/ban 的次数另计', ownHits >= foeHits ? 'is-good' : '')}
      ${readoutTile('KPL 双人命中', pairN ? `${pairHits} 对` : '—', `${pairN} 局有组合样本`)}
      ${readoutTile('ban 命中', `${banTotal} / ${games.length * 5}`, '打到对手常用英雄的 ban')}
    </div>
    <div class="bgv-bp-grid">${cards}</div>`;
}

/* ── 02 BO 赛制 BP 习惯：可点的局次轨道 ───────────────────── */
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
      ${cardHead(esc, '02 BO 赛制 BP 习惯', '同赛制的历史 BO 还不够', '等对手在同一赛制下有更多大场，再看每一把的开场习惯。')}
      ${emptyState('暂无同赛制历史。')}
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
  const sideKey = ['auto', 'blue', 'red'].includes(ui.boSide) ? ui.boSide : 'auto';
  const selectedSide = sideKey === 'auto' ? (cur?.foeSide || 'blue') : sideKey;

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
    .map((row) => ({
      attacker: String(row.a || '').trim(),
      defender: String(row.b || '').trim(),
      strength: row.strength, note: row.note,
    }))
    .filter((row) => row.attacker && row.defender);
  const comboRules = rawComboRules
    .map((row) => ({
      attacker: resolveCombo(row.a), defender: resolveCombo(row.b),
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
      <em class="bgv-boh-flow-note">在 ${esc(hit.combo.heroes.join(' + '))}</em>
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
  const sideMatched = !cur || !cur.foeSide || cur.foeSide === selectedSide;

  const scopeTabs = `<div class="bgx-seg" role="group" aria-label="历史范围">
    <button type="button" class="bgx-seg-btn" data-bgx-boscope="opp" aria-pressed="${scope === 'opp'}">只看本对手</button>
    <button type="button" class="bgx-seg-btn" data-bgx-boscope="all" aria-pressed="${scope === 'all'}">全部 BO${esc(String(bestOf))}</button>
  </div>`;
  const sideTabs = `<div class="bgx-seg" role="group" aria-label="红蓝方">
    ${[['auto', '本场同侧'], ['blue', '蓝方'], ['red', '红方']].map(([key, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgx-boside="${key}" aria-pressed="${sideKey === key}">${label}</button>`).join('')}
  </div>`;
  const windowTabs = `<div class="bgx-seg" role="group" aria-label="时间">
    ${[['30', '近 30 天'], ['90', '近 90 天'], ['all', '全部']].map(([key, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgx-bowindow="${key}" aria-pressed="${key === windowKey}">${label}</button>`).join('')}
  </div>`;
  const stepButtons = `<div class="bgv-boh-step" role="group" aria-label="切换局次">
    <button type="button" class="bgx-btn" data-boh-step="-1" ${selected <= 1 ? 'disabled' : ''}>← 上一把</button>
    <button type="button" class="bgx-btn" data-boh-step="1" ${selected >= bestOf ? 'disabled' : ''}>下一把 →</button>
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
      title="${esc(gameWord(slot))} · ${boSideLabel(slotSide)} · ${slotGames.length || 0} 个样本${first ? ` · ${first.heroes.map((hero) => hero).join(' + ')}` : ''}">
      <span class="bgv-boh-no">${String(slot).padStart(2, '0')}</span>
      <b>${esc(gameWord(slot))}</b>
      <span class="bgv-boh-slot-face">${first ? first.heroes.map((hero) => h.portrait(hero, 'bgv-boh-slot-img')).join('') : '—'}</span>
      <small>${boSideLabel(slotSide)} ${slotGames.length} 场</small>
      ${flag ? `<i class="bgv-boh-flag ${first ? (same ? 'is-same' : 'is-diff') : 'is-new'}">${flag}</i>` : ''}
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
    if (poolHint) return { note: `<p class="bgv-boh-intent-note">${esc(poolHint)}</p>` };
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
  const mismatch = cur && !sideMatched
    ? `<div class="bgv-boh-empty">本场是${boSideLabel(cur.foeSide)}，当前筛选的是${boSideLabel(selectedSide)}；切回「本场同侧」再看逐手对照。</div>`
    : '';
  const currentBlock = !cur
    ? `<div class="bgv-boh-empty">本场没打到这一把${bestOf > (current.games || []).length ? '（大场已结束）' : ''}。</div>`
    : mismatch || `
      ${currentRows}
      ${boRow('常用体系', currentTags.length ? currentTags.map((tag) => `<span class="bgv-boh-tag">${esc(tag.key)}</span>`).join('') : '<span class="bgv-boh-none">—</span>', '')}
      ${boRow('这一把', `<b class="bgv-boh-rate ${cur.result === 'win' ? 'is-win' : cur.result === 'loss' ? 'is-loss' : ''}">${cur.result === 'win' ? '胜' : cur.result === 'loss' ? '负' : '—'}</b>`, '')}
      ${compared ? `<p class="bgv-boh-verdict ${matches === compared ? 'is-same' : 'is-diff'}">
        ${pooledGames.length < 2 ? '样本少（1 局），只作方向参考；' : ''}BP 顺序：${matches}/${compared} 个节点照做${matches === compared ? '，这一把基本沿用平时习惯。' : '，有变化的地方已在上面逐项标出。'}
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
    ${cardHead(esc, '02 BO 赛制 BP 习惯', `对手在 BO${esc(String(bestOf))} 的每一把，习惯怎么开`,
      '先看同侧同赛制的历史习惯，再对照本场第 N 把是不是照做；组合按组合池，克制箭头按赛训规则中心。',
      `<span class="bgx-chip">${count(historyForFormat.length)} 场 BO${esc(String(bestOf))} · ${esc(formatLabel)}</span>`)}
    <div class="bgv-boh-toolbar">${scopeTabs}${sideTabs}<span class="bgx-spacer"></span>${windowTabs}<button type="button" class="bgx-btn ${ui.boIncludeOtherEvents ? 'is-on' : ''}" data-bgx-boother aria-pressed="${ui.boIncludeOtherEvents}" title="对手 BP 习惯允许跨赛事积累；默认只看当前赛事">${ui.boIncludeOtherEvents ? '✓ ' : ''}含其他赛事历史</button><button type="button" class="bgx-btn" data-bgx-boreset>重置</button></div>
    <div class="bgv-boh-rail">${rail}</div>
    <div class="bgv-boh-detail">
      <section class="bgv-boh-col">
        <header><span>历史习惯 · ${boSideLabel(selectedSide)} · ${pooledGames.length} 局</span><b title="${pooledGames.length} 局样本">${winRate(pooledStat)}</b></header>
        ${historyBlock}
        ${sampleDates.length ? `<div class="bgv-boh-samples">样本：${sampleDates.map((item) => `<span>${esc(item)}</span>`).join('')}</div>` : ''}
      </section>
      <section class="bgv-boh-col is-current">
        <header><span>本场 · ${esc(gameWord(selected))} · ${boSideLabel(cur?.foeSide || selectedSide)}</span>${stepButtons}<b>${cur ? (cur.result === 'win' ? '胜' : cur.result === 'loss' ? '负' : '—') : '未打到'}</b></header>
        ${currentBlock}
      </section>
    </div>
  </section>`;
}



/* ── 03 阵容体系 ───────────────────────────────────────────── */
const ARCH_TONE = ['is-0', 'is-1', 'is-2', 'is-3'];

function archBand(rows, esc) {
  const list = rows || [];
  const total = list.reduce((sum, row) => sum + (row.n || 0), 0);
  if (!total) return '<div class="xw-arch-miss">没有名单</div>';
  const segs = list.map((row, index) =>
    `<span class="xw-arch-seg ${ARCH_TONE[index % 4]}" style="flex:${Math.max(1, row.n || 0)}" title="${esc(row.type)} ${row.n} 局"></span>`).join('');
  const legend = list.map((row, index) =>
    `<span class="xw-arch-key ${ARCH_TONE[index % 4]}"><i></i>${esc(row.type)}<b>${row.n}</b><em>${Math.round((row.n || 0) / total * 100)}%</em></span>`).join('');
  return `<div class="bgv-arch-band"><div class="xw-arch-band">${segs}</div><div class="xw-arch-legend">${legend}</div></div>`;
}

function distributionPanel(block, side, esc, title, games) {
  const rows = (block.distribution || {})[side] || {};
  const known = games.filter((game) => (game[side] || {}).types && Object.keys(game[side].types).length).length;
  return `<section class="xw-mod bgv-mod">
    <div class="xw-mod-head">
      <div class="xw-mod-copy"><span class="xw-mod-kicker">${side === 'own' ? '我方' : '对方'}</span>
        <h3>${esc(title)}</h3></div>
      <span class="xw-mod-meta">${known} 局有名单</span>
    </div>
    <div class="xw-mod-body"><div class="xw-arch">${LANE_ORDER.map((lane) => `<div class="xw-arch-row">
      <span class="xw-arch-lane">${esc(LANE_SHORT[lane] || lane)}<small>${(rows[lane] || []).reduce((sum, row) => sum + row.n, 0)} 局</small></span>
      <div class="xw-arch-main">${archBand(rows[lane] || [], esc)}</div>
    </div>`).join('')}</div></div>
  </section>`;
}

function bandChart(rows, esc, tone = '') {
  const list = rows || [];
  const total = list.reduce((sum, row) => sum + (row.value || 0), 0);
  if (!total) return '<div class="bgv-empty">没有数据</div>';
  return `<div class="bgv-band-chart ${tone}">
    <div class="xw-arch-band">${list.map((row, index) => (row.value > 0
      ? `<span class="xw-arch-seg is-${index}" style="flex:${row.value}" title="${esc(row.label)} ${row.value} 局"></span>` : '')).join('')}</div>
    <div class="xw-arch-legend">${list.map((row, index) =>
      `<span class="xw-arch-key is-${index}"><i></i>${esc(row.label)}<b>${row.value}</b><em>${num(row.pct) ? `${Math.round(row.pct)}%` : '—'}</em></span>`).join('')}</div>
  </div>`;
}

function comboRows(rows) {
  return (rows || []).slice(0, 4).map((row) => ({ label: row.label, value: row.n || 0, pct: row.pct }));
}

function coreRows(rows) {
  const map = new Map((rows || []).map((row) => [Number(row.n), row.games || 0]));
  const total = [...map.values()].reduce((sum, value) => sum + value, 0);
  return [1, 2, 3, 4, 5].map((n) => ({
    label: `${n} 核`, value: map.get(n) || 0,
    pct: total ? (map.get(n) || 0) / total * 100 : null,
  }));
}

/* 英雄池交叉：三个方框——我方队名 / 敌方队名 / 公共英雄。
   * 我方框只放我方用过的，敌方框只放对方用过的，两队都用的单独进公共英雄框；
   * 每个头像上的身份标签常驻，不靠 hover、也不在窄屏隐藏。
   * 大场页与战队详情共用这一份版面，各自喂 rows 与真实队名。 */
export function renderHeroPoolCross(rows, h, names = {}) {
  const { esc } = h;
  const ownName = names.ownName || '本队';
  const foeName = names.foeName || '对手';
  const tag = { none: '新东西', own: '我方熟', foe: '对方熟', both: '公共英雄' };
  const order = { both: 0, own: 1, foe: 2, none: 3 };
  const sorted = [...rows].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9)
    || (b.ownApps + b.foeApps) - (a.ownApps + a.foeApps)
    || String(a.hero).localeCompare(String(b.hero), 'zh-CN'));
  const zone = (list) => list.map((row) => `<div class="xw-hero is-${esc(row.status || 'none')}">
      ${h.portrait(row.hero, 'xw-face-img')}
      <b>${esc(row.hero)}</b>
      <small>${esc([row.lane, row.type].filter(Boolean).join(' · '))}</small>
      <small class="bgv-pool-count">我 <em>${fmtCount(row.ownApps)}</em> · 敌 <em>${fmtCount(row.foeApps)}</em></small>
      <span class="bgv-pool-tag is-${esc(row.status || 'none')}">${tag[row.status] || '新东西'}</span>
    </div>`).join('');
  /* 新东西（双方以前都没用过）按这批局里谁实际拿出来过归侧，不混进公共英雄。 */
  const ownRows = sorted.filter((r) => r.status === 'own' || (r.status === 'none' && r.ownPick));
  const foeRows = sorted.filter((r) => r.status === 'foe' || (r.status === 'none' && r.foePick));
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

function poolGroups(games, h, names) {
  const rows = new Map();
  for (const game of games) {
    for (const side of ['own', 'foe']) {
      for (const item of ((game[side] || {}).heroes || [])) {
        const key = item.hero;
        const row = rows.get(key) || { hero: key, lane: item.lane, type: item.type, ownApps: 0, foeApps: 0, status: item.status, ownPick: false, foePick: false };
        row.ownApps = Math.max(row.ownApps, item.ownApps || 0);
        row.foeApps = Math.max(row.foeApps, item.foeApps || 0);
        row.status = item.status;
        row[side === 'own' ? 'ownPick' : 'foePick'] = true;
        rows.set(key, row);
      }
    }
  }
  return renderHeroPoolCross([...rows.values()], h, names);
}

export function renderCompSystem(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const block = insight.compSystem;
  if (!block || !(block.games || []).length) {
    return `${cardHead(esc, '03 阵容体系', '这场读不到阵容结构', '缺十人名单时不给体系结论。')}${emptyState('没有阵容数据。')}`;
  }
  const games = block.games.slice().sort((a, b) => (a.gameIndex || 0) - (b.gameIndex || 0));
  const known = games.filter((game) => (game.own || {}).combo || (game.foe || {}).combo).length;
  /* 教练反馈：这一块列得太细。每局只留五人头像 + 核数，
     Combo/射手/辅助的长串改名放在头像 title 里，想看再悬停，不再占一整行。 */
  const gameRows = games.map((game) => {
    const side = (key, label) => {
      const cell = game[key] || {};
      const picks = (cell.heroes || []).slice(0, 5);
      const tip = [cell.combo, cell.adc, cell.support].filter(Boolean).join(' · ');
      const faces = picks.length
        ? picks.map((item) => `<span class="bgv-mini-hero" title="${esc([item.hero, item.lane, item.type].filter(Boolean).join(' · '))}">${h.portrait(item.hero, 'bgv-mini-face')}</span>`).join('')
        : '<span class="bgv-comp-none">名单缺失</span>';
      return `<div class="bgv-comp-side"><small>${label}</small><div${tip ? ` title="${esc(tip)}"` : ''}>${faces}</div>${num(cell.cores) ? `<em class="bgv-comp-core">${cell.cores} 核</em>` : ''}</div>`;
    };
    return `<div class="bgv-comp-game ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">
      <b>${esc(gameWord(game.gameIndex))}</b><span>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span>
      ${side('own', '我')}${side('foe', '敌')}
    </div>`;
  }).join('');

  const anomalies = (block.anomalies || []).map((item) => `<div class="bgv-anom is-${esc(item.level || 'low')}">
    <b>${esc(item.title)}</b><p>${esc(item.detail)}</p>
  </div>`).join('');

  const comboMax = Math.max(1,
    ...(block.combos?.own || []).map((row) => row.n || 0),
    ...(block.combos?.foe || []).map((row) => row.n || 0));

  return `<section class="bgv-sec">
    <header class="xw-sec-head">
      <div class="xw-sec-title"><span class="xw-sec-num">03</span><h2>阵容体系：双方各自在打什么</h2></div>
      <span class="xw-sec-meta">${count(games.length)} 局 · ${known} 局有名单</span>
    </header>
    <p class="xw-statement">不看「能力雷达」，只看教练会说的词：坦野还是刺野、战边还是坦边、呆射还是游射、几核。再看英雄池我们/对方熟不熟。每条色带就是一局，厚色带里每一段是一个类型。</p>

    <div class="bgv-arch-grid">
      ${distributionPanel(block, 'own', esc, '五路类型', games)}
      ${distributionPanel(block, 'foe', esc, '五路类型', games)}
    </div>

    <div class="bgv-chart-grid">
      <section class="xw-mod bgv-mod">
        <div class="xw-mod-head"><div class="xw-mod-copy"><span class="xw-mod-kicker">打野 + 对抗路</span>
          <h3>我们和对面，各自怎么搭前两手</h3></div><span class="xw-mod-meta">${comboMax} 局封顶</span></div>
        <div class="bgv-chart-pair">
          <div><span class="bgv-chart-label">我方</span>${bandChart(comboRows(block.combos?.own), esc)}</div>
          <div><span class="bgv-chart-label is-foe">对方</span>${bandChart(comboRows(block.combos?.foe), esc, 'is-foe')}</div>
        </div>
      </section>
      <section class="xw-mod bgv-mod">
        <div class="xw-mod-head"><div class="xw-mod-copy"><span class="xw-mod-kicker">核心数</span>
          <h3>一核到五核，各占多少</h3></div><span class="xw-mod-meta">分均经济 ≥18% 计核心</span></div>
        <div class="bgv-chart-pair">
          <div><span class="bgv-chart-label">我方</span>${bandChart(coreRows(block.cores?.own), esc)}</div>
          <div><span class="bgv-chart-label is-foe">对方</span>${bandChart(coreRows(block.cores?.foe), esc, 'is-foe')}</div>
        </div>
      </section>
    </div>

    <section class="xw-mod bgv-mod">
      <div class="xw-mod-head"><div class="xw-mod-copy"><span class="xw-mod-kicker">逐局</span>
        <h3>每一把的五人：阵容有没有换</h3></div>
        <span class="xw-mod-meta">${games.length} 局</span></div>
      <div class="bgv-comp-games">${gameRows}</div>
    </section>

    ${anomalies ? `<div class="bgv-anoms">${anomalies}</div>` : ''}

    <section class="bgv-pool-block">
      <header class="xw-sec-head"><div class="xw-sec-title"><span class="xw-sec-num">池</span><h2>英雄池交叉：这场选出来的英雄，双方以前用没用过</h2></div>
        <span class="xw-sec-meta">我方 ${block.ownHistoryGames || 0} 局 · 对方 ${block.foeHistoryGames || 0} 局</span></header>
      ${poolGroups(games, h, { ownName: h.ownName, foeName: h.foeName })}
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

/* 全场走势：龙 / 塔 / 团战 / 反野按 0–4、4–10、10 分后三个阶段画折线，只在场次汇总时出现。 */
function phaseTrendSvg(resources, esc) {
  const rows = PHASE_KEYS.map((key) => (resources || []).find((row) => row.key === key)).filter(Boolean);
  if (rows.length < 2) return '';
  const valueOf = (row, key) => {
    if (key === 'invade') return (num(row.antiRed) ? row.antiRed : 0) + (num(row.antiBlue) ? row.antiBlue : 0);
    return num(row[key]) ? row[key] : 0;
  };
  const series = [
    { label: '龙', color: 'var(--bgx-accent)', key: 'dragonOwn' },
    { label: '塔', color: '#b08a3e', key: 'towerOwn' },
    { label: '团', color: 'var(--bgx-loss)', key: 'fightN' },
    { label: '反野', color: '#3a6ea5', key: 'invade' },
  ].map((item) => ({ ...item, values: rows.map((row) => valueOf(row, item.key)) }));
  const max = Math.max(1, ...series.flatMap((item) => item.values));
  const top = Math.max(1, Math.ceil(Math.ceil(max * 1.1) / 4) * 4);
  const W = 960; const H = 220; const padL = 46; const padR = 24; const padT = 18; const padB = 34;
  const x = (index) => padL + (index / Math.max(1, rows.length - 1)) * (W - padL - padR);
  const y = (value) => padT + (1 - value / top) * (H - padT - padB);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const gy = padT + ratio * (H - padT - padB);
    return `<line class="bgx-trend-grid" x1="${padL}" y1="${gy.toFixed(1)}" x2="${W - padR}" y2="${gy.toFixed(1)}"></line>
      <text class="bgx-trend-axis" x="${padL - 10}" y="${(gy + 4).toFixed(1)}" text-anchor="end">${Math.round(top * (1 - ratio))}</text>`;
  }).join('');
  const xLabels = rows.map((row, index) => `<text class="bgx-trend-axis" x="${x(index).toFixed(1)}" y="${H - 10}" text-anchor="middle">${esc(row.label || '')}</text>`).join('');
  const lines = series.map((item) => {
    const points = item.values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
    const dots = item.values.map((value, index) => `<circle cx="${x(index).toFixed(1)}" cy="${y(value).toFixed(1)}" r="4" fill="${item.color}"><title>${esc(`${item.label} · ${rows[index].label || ''} · ${Math.round(value * 100) / 100}`)}</title></circle>`).join('');
    return `<polyline points="${points}" fill="none" stroke="${item.color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></polyline>${dots}`;
  }).join('');
  const legend = series.map((item) => `<span><i style="background:${item.color}"></i>${esc(item.label)}</span>`).join('');
  return `<div class="bgx-phase-trend">
    <div class="bgx-phase-trend-head"><b>全场走势 · 场均</b><span class="bgx-phase-trend-legend">${legend}</span></div>
    <div class="bgx-phase-trend-scroll"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="龙、塔、团战、反野按阶段的全场走势">${grid}${xLabels}${lines}</svg></div>
  </div>`;
}

export function renderPhase(insight, ui, h) {
  const { esc, fixed, count } = localHelpers(h);
  const games = (insight.phase && insight.phase.perGame) || [];
  if (!games.length) {
    return `${cardHead(esc, '04 执行与资源', '每一段拿了什么，打了几波团', '这几局没有阶段数据。')}${emptyState('没有阶段数据。')}`;
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
    '先选阶段，再看这一段的资源与团战；没有回放事件的项显示「—」，不补 0。选手状态已下线，不再用不可靠的状态分。', tabs)}
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
    </div>
    ${active === 'all' ? phaseTrendSvg(insight.phase?.resources, esc) : ''}`;
}
