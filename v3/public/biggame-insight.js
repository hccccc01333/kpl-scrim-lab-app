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
const POOL_COLORS = ['#1c6a5c', '#3f8b76', '#6aa894', '#96c3b2', '#c4ddd2'];
const FOE_COLORS = ['#a9553f', '#bd765c', '#cf9a83', '#dfbcaa', '#f0ddd4'];

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

function baseFor(metric, mode, esc) {
  const base = (metric.base || {})[mode];
  if (!num(base)) return '<span class="bgv-base is-na">基准 —</span>';
  let delta = null;
  let unit = '';
  if (metric.kind === 'flag') {
    const rate = metric.series?.rate;
    if (num(rate)) delta = rate - base;
    unit = 'pp';
  } else if (metric.kind === 'pair') {
    const rate = metric.series?.rate;
    if (num(rate)) delta = rate - base;
    unit = 'pp';
  } else if (metric.kind === 'pct') {
    if (num(metric.series?.value)) delta = metric.series.value - base;
    unit = 'pp';
  } else {
    if (num(metric.series?.value)) delta = metric.series.value - base;
    unit = metric.unit === 'gold' ? '' : ' 次';
  }
  const baseText = metric.kind === 'flag' || metric.kind === 'pair' || metric.kind === 'pct'
    ? `${Math.round(base)}%` : (metric.unit === 'gold' ? fmtSigned(base) : fmtNumber(base));
  const deltaText = num(delta)
    ? `<em class="${delta === 0 ? '' : (delta > 0) !== !!metric.reverse ? 'is-up' : 'is-down'}">${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(metric.kind === 'num' && metric.unit === 'gold' ? 0 : 1)}${unit}</em>`
    : '';
  return `<span class="bgv-base">基准 <b>${baseText}</b>${deltaText}</span>`;
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
  const metricMode = ui.metricMode === 'key' ? 'key' : 'all';
  const metrics = metricMode === 'key' ? metricsAll.filter((metric) => KEY_METRICS.has(metric.key)) : metricsAll;

  const groupRows = [];
  let lastGroup = '';
  for (const metric of metrics) {
    if (metric.group !== lastGroup) {
      groupRows.push(`<div class="bgv-row is-group"><span>${esc(metric.group)}</span></div>`);
      lastGroup = metric.group;
    }
    const cells = (metric.perGame || []).map((value) => cellFor(metric, value)).join('');
    groupRows.push(`<div class="bgv-row">
      <div class="bgv-metric"><b>${esc(metric.label)}</b><small>${esc(metric.hint || '')}</small></div>
      ${cells}
      <div class="bgv-series">${seriesFor(metric)}</div>
      <div class="bgv-compare">${baseFor(metric, mode, esc)}</div>
    </div>`);
  }

  const head = `<div class="bgv-row is-head">
    <span class="bgv-metric">指标</span>
    ${games.map((game) => `<span class="bgv-col-head">${esc(gameWord(game.gameIndex))}
      <i class="${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</i></span>`).join('')}
    <span class="bgv-series">整场</span>
    <span class="bgv-compare">对比</span>
  </div>`;

  const cov = block.coverage || {};
  const coverageNote = [
    `一血 ${cov.firstBlood || 0}/${cov.games || games.length} 局`,
    `中立资源 ${cov.objective || 0}/${cov.games || games.length} 局`,
    `推塔 ${cov.towers || 0}/${cov.games || games.length} 局`,
  ].join(' · ');

  const modeToggle = `<div class="bgx-seg bgv-mode" role="group" aria-label="指标范围">
    <button type="button" class="bgx-seg-btn" data-bgv-metricmode="key" aria-pressed="${metricMode === 'key'}">关键 8 项</button>
    <button type="button" class="bgx-seg-btn" data-bgv-metricmode="all" aria-pressed="${metricMode === 'all'}">全部</button>
  </div>`;
  return `${cardHead(esc, '01 总览与对比', `这一场 BO${esc(String(insight.baseline?.bestOf || games.length))}，每一局的关键指标`,
    `一行一个指标、一列一局；右侧是整场与「${esc(modeLabel)}」的差值。只列赛训会看的几项，不铺全部报表。`,
    `${selectBase(ui)}${modeToggle}<span class="bgx-chip">${count(games.length)} 局</span>`)}
    ${overviewReadout(insight, metrics)}
    <div class="bgv-board" style="--bgv-cols:${columns}">
      ${head}${groupRows.join('')}
    </div>
    <p class="bgv-note"><b>覆盖</b>${esc(coverageNote)}有回放/有名单；没有的格显示「—」，不补 0。对比列＝本场与「${esc(modeLabel)}」的差，绿色是更好、红色是更差（被切 C 反向）。</p>`;
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
  const sideBlock = (side) => {
    const rows = (game.combos || {})[side] || [];
    const title = side === 'foe' ? '对方想要的组合' : '我方想要的组合';
    if (!rows.length) return `<div class="bgv-combo-side ${side === 'foe' ? 'is-foe' : ''}">
      <span class="bgv-combo-title">${title}</span><p class="bgv-combo-empty">这局没有可读的常用组合</p></div>`;
    return `<div class="bgv-combo-side ${side === 'foe' ? 'is-foe' : ''}">
      <span class="bgv-combo-title">${title}</span>
      ${rows.map((row) => {
        const lost = row.lost;
        const pair = row.heroes || [];
        const word = side === 'foe'
          ? (row.status === 'broken' ? `我们 ban ${lost}，拆掉`
            : row.status === 'stolen' ? `我们抢 ${lost}，拆掉`
              : row.status === 'denied' ? `两边都没拿到`
                : '对方拿到')
          : (row.status === 'broken' ? `对面 ban ${lost}，拆掉`
            : row.status === 'stolen' ? `对面抢 ${lost}，拆掉`
              : row.status === 'denied' ? '两边都没拿到'
                : '我们拿到');
        const tone = row.status === 'got' ? 'is-got' : row.status === 'broken' || row.status === 'stolen' ? 'is-broken' : 'is-denied';
        return `<div class="bgv-combo-row ${tone}">
          <div class="bgv-combo-faces">${pair.map((hero, index) => `<span class="bgv-combo-face ${hero === lost ? 'is-lost' : 'is-kept'}">
            ${h.portrait(hero, 'bgv-combo-img')}<b>${esc(hero)}</b>
          </span>${index === 0 ? '<em class="bgv-combo-plus">+</em>' : ''}`).join('')}</div>
          <div class="bgv-combo-copy"><b>${word}${row.source === 'KPL' ? '<em class="bgv-kpl-tag">KPL</em>' : ''}</b><small>${row.source === 'KPL' ? 'KPL' : (side === 'foe' ? '对手' : '我方')} ${row.n || 0} 场 · ${num(row.wr) ? `${row.wr}%` : '—'}</small></div>
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

function kplPairsBlock(game, h) {
  const { esc } = h;
  const side = (key, label) => {
    const block = (game.kpl || {})[key] || {};
    const pairs = (block.pairs || []).slice(0, 2);
    if (!block.available || !pairs.length) return `<div class="bgv-kpl-side ${key === 'foe' ? 'is-foe' : ''}">
      <span class="bgv-kpl-title">${label} KPL 双人组</span><p class="bgv-kpl-empty">这套五人没有 KPL 双人样本</p></div>`;
    return `<div class="bgv-kpl-side ${key === 'foe' ? 'is-foe' : ''}">
      <span class="bgv-kpl-title">${label} KPL 双人组 <b>${block.pairHits || 0} 对</b></span>
      <div class="bgv-kpl-pairs">${pairs.map((pair) => `<span class="bgv-kpl-pair">
        <span class="bgv-kpl-faces">${pair.heroes.map((hero) => h.portrait(hero, 'bgv-kpl-face')).join('')}</span>
        <span class="bgv-kpl-copy"><b>${pair.heroes.map((hero) => esc(hero)).join(' + ')}</b><small>KPL ${pair.n} 场 · ${num(pair.wr) ? `${pair.wr}%` : '—'}</small></span>
      </span>`).join('')}</div>
    </div>`;
  };
  return `<div class="bgv-kpl">${side('own', '我方')}${side('foe', '对方')}</div>`;
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
  const missing = allGames.length - playable.length;
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
    const firstFoe = (game.heroesFoe || [])[0];
    return `<details class="bgv-bp-card ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}"
      data-bp-card="${esc(String(game.gameIndex))}" ${open ? 'open' : ''}>
      <summary class="bgv-bp-sum">
        <b>${esc(gameWord(game.gameIndex))}</b>
        <em>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em>
        <span class="bgv-verdict">${esc(game.label || '—')}</span>
        ${firstFoe ? `<span class="bgv-bp-sum-first"><i>对方一抢</i>${h.portrait(firstFoe, 'bgv-bp-sum-face')}<b>${esc(firstFoe)}</b></span>` : ''}
        <span class="bgv-bp-sum-kpl">KPL <b>${pairHit}</b> 对</span>
        <button type="button" class="bgv-bp-jump" data-bp-jump-order="${esc(String(game.gameIndex))}">看这把 20 手 →</button>
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
        ${kplPairsBlock(game, h)}
        <div class="bgv-bans-visual">${banTiles(game.bansOwn, h, 'own')}${banTiles(game.bansFoe, h, 'foe')}</div>
      </div>
    </details>`;
  }).join('');

  const filterChip = ui.bpGame
    ? `<button type="button" class="bgx-btn" data-bp-game="">看全部 ${count(playable.length)} 局</button>`
    : '';
  return `${cardHead(esc, '02 BP 博弈', `${ui.bpGame ? `第 ${esc(String(ui.bpGame))} 把` : `这 ${count(playable.length)} 局`} BP，${esc(edgeWord)}`,
    '每一局先看双方五人分工，再看组合有没有被拆：亮着的头像是拿到了，灰掉打叉的是被 ban / 被抢的。最后才是三个读数。',
    `${filterChip}${ui.bpGame ? `<span class="bgx-chip">第 ${esc(String(ui.bpGame))} 把</span>`
      : `<span class="bgx-chip is-accent">${count(series.advantageGames)}/${count(series.count)} 局占优</span>`}`)}
    <div class="bgv-bp-summary">
      ${readoutTile('拆掉对方组合', `${brokenFoe} 组`, 'ban 或抢掉其中一张', brokenFoe > 0 ? 'is-good' : '')}
      ${readoutTile('我方组合被拆', `${brokenOwn} 组`, '对面 ban 或抢掉', brokenOwn > brokenFoe ? 'is-bad' : '')}
      ${readoutTile('我方拿到首选', `${ownHits} 次`, '对手核心被我们抢/ban 的次数另计', ownHits >= foeHits ? 'is-good' : '')}
      ${readoutTile('KPL 双人命中', pairN ? `${pairHits} 对` : '—', `${pairN} 局有组合样本`)}
      ${readoutTile('ban 命中', `${banTotal} / ${games.length * 5}`, '打到对手常用英雄的 ban')}
    </div>
    <div class="bgv-bp-grid">${cards}</div>
    ${missing ? `<p class="bgv-note"><b>名单缺失</b>另外 ${missing} 局没有双方完整名单，未进入这张卡；不拿空数据凑结论。</p>` : ''}
    <p class="bgv-note"><b>怎么读</b>组合来自双方在这份历史语料里的常用双人组（≥2 场）＋ KPL 常用双人组。绿色＝拿到了；红色＝被拆掉（ban 或抢走其中一张）；灰色＝两边都没拿到。不是胜负预测。</p>`;
}

/* ── 02 BP 顺序：征召模式固定 20 手，按名单入位就是真实手序 ── */
const SCRIM_20 = (() => {
  const slots = [];
  for (let i = 0; i < 5; i += 1) slots.push(['ban', '1'], ['ban', '2']);
  const picks = ['1', '2', '2', '1', '1', '2', '2', '1', '1', '2'];
  return slots.concat(picks.map((code) => ['pick', code]));
})();

function draftTile(h, hero, step, action, side, role) {
  const { esc } = h;
  return `<span class="bgv-draft-tile ${action} ${side === 'foe' ? 'is-foe' : ''}">
    <em>${String(step).padStart(2, '0')}</em>
    <span class="bgv-draft-action">${action === 'ban' ? 'BAN' : 'PICK'} · ${side === 'foe' ? '敌' : '我'}</span>
    ${hero ? h.portrait(hero, 'bgv-draft-face') : '<span class="bgv-draft-empty">—</span>'}
    ${action === 'ban' && hero ? '<i class="bgv-draft-slash"></i>' : ''}
    <b>${hero ? esc(hero) : '未记录'}</b>
    ${role ? `<small>${esc(role)}</small>` : ''}
  </span>`;
}

export function renderDraft(insight, ui, h) {
  const { esc } = localHelpers(h);
  const games = (insight.draft && insight.draft.games) || [];
  if (!games.length) {
    return `${cardHead(esc, '02 BP 顺序', '这场没有 BP 名单', '没有名单就不猜手序。')}${emptyState('没有 BP 名单。')}`;
  }
  const picked = games.find((game) => String(game.gameIndex) === String(ui.draftGame)) || games[0];
  const ownCode = picked.camp === 'red' ? '2' : '1';
  const sideOf = (code) => (code === ownCode ? 'own' : 'foe');
  const ownBans = picked.bansOwn || [];
  const foeBans = picked.bansFoe || [];
  const ownPicks = picked.heroesOwn || [];
  const foePicks = picked.heroesFoe || [];
  let oi = 0; let fi = 0; let op = 0; let fp = 0;
  const steps = SCRIM_20.map(([action, code], index) => {
    const side = sideOf(code);
    let hero = '';
    if (action === 'ban') hero = side === 'own' ? (ownBans[oi++] || '') : (foeBans[fi++] || '');
    else hero = side === 'own' ? (ownPicks[op++] || '') : (foePicks[fp++] || '');
    return { action, side, hero, step: index + 1 };
  });
  const roleOf = (hero) => {
    const cells = [...(picked.signature?.own || []), ...(picked.signature?.foe || [])];
    const cell = cells.find((item) => item.hero === hero);
    return cell ? [cell.position, cell.archetype].filter(Boolean).join(' · ') : '';
  };
  const firstPick = steps[10] || {};
  const lastPick = steps[19] || {};
  const complete = steps.every((step) => step.hero);
  const sourceWord = picked.orderSource === 'explicit' ? '逐手记录'
    : picked.orderSource === 'scrim-20' ? '征召 20 手还原' : '名单不完整';
  const row = (from, to, label) => `<div class="bgv-draft-20-row">
    <span class="bgv-draft-20-label">${label}</span>
    ${steps.slice(from, to).map((step) => draftTile(h, step.hero, step.step, step.action, step.side,
      step.action === 'pick' ? roleOf(step.hero) : '')).join('')}
  </div>`;
  const switchStrip = `<div class="bgv-game-switch" role="group" aria-label="局次">
    <button type="button" class="bgv-game-switch-all" data-bp-game="" aria-pressed="${!ui.bpGame}">全部局</button>
    ${games.map((game) => {
      const ownCode = game.camp === 'red' ? '2' : '1';
      const pickOnOwn = ownCode === '1';
      const firstPick = (pickOnOwn ? game.heroesOwn : game.heroesFoe)?.[0];
      const firstBan = (pickOnOwn ? game.bansOwn : game.bansFoe)?.[0];
      const on = String(ui.bpGame || ui.draftGame) === String(game.gameIndex);
      return `<button type="button" class="bgv-game-switch-slot ${on ? 'is-on' : ''} ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}"
        data-bp-game="${esc(String(game.gameIndex))}" aria-pressed="${on}">
        <span>${esc(gameWord(game.gameIndex))}<em>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em></span>
        <i class="bgv-game-switch-face">${firstPick ? h.portrait(firstPick, 'bgv-game-switch-img') : '—'}</i>
        <small>一抢 ${firstPick ? esc(firstPick) : '—'}</small>
        <small class="is-ban">首 ban ${firstBan ? esc(firstBan) : '—'}</small>
      </button>`;
    }).join('')}
  </div>`;
  return `<section class="bgx-card bgv-draft">
    ${cardHead(esc, '02 BP 顺序', `${esc(gameWord(picked.gameIndex))}：20 手，谁先拿、谁 counter`,
      '训练赛征召模式固定 20 手：10 ban 蓝红交替，随后蓝1、红2、蓝2、红2、蓝2、红1。每方名单按手序入位，得到的就是真实 BP 顺序。',
      `<span class="bgx-chip">${picked.camp === 'red' ? '我方红方' : '我方蓝方'}</span><span class="bgx-chip ${complete ? 'is-accent' : ''}">${sourceWord}</span>`)}
    ${switchStrip}
    <div class="bgv-draft-20">
      ${row(0, 10, 'BAN 01–10')}
      ${row(10, 20, 'PICK 11–20')}
    </div>
    <div class="bgv-draft-keys">
      <span><b>一抢</b>${firstPick.hero ? esc(firstPick.hero) : '—'}<em>${firstPick.side === 'foe' ? '对方' : '我方'}</em></span>
      <span><b>末位</b>${lastPick.hero ? esc(lastPick.hero) : '—'}<em>${lastPick.side === 'foe' ? '对方' : '我方'}</em></span>
      <span><b>我方一抢</b>${ownPicks[0] ? esc(ownPicks[0]) : '—'}</span>
      <span><b>对方一抢</b>${foePicks[0] ? esc(foePicks[0]) : '—'}</span>
    </div>
    <div class="bgv-draft-legend"><span><i class="is-ban"></i>BAN：灰头像 + 斜杠</span><span><i class="is-pick"></i>PICK：亮头像 + 分路/类型</span><span>01–20 是全局手序，不是我/敌各自的手序</span></div>
  </section>`;
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
  return `<span class="bgv-boh-hero ${tone}">${h.portrait(hero, 'bgv-boh-face')}<b>${h.esc(hero)}</b></span>`;
}

function boRow(label, tiles, meta) {
  return `<div class="bgv-boh-row"><span>${label}</span><div class="bgv-boh-tiles">${tiles}</div><em>${meta || ''}</em></div>`;
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
  const stats = new Map(slots.map((slot) => {
    const games = history.flatMap((item) => (item.games || []).filter((game) => Number(game.index) === slot));
    const winCount = games.filter((game) => game.result === 'win').length;
    const decided = games.filter((game) => game.result === 'win' || game.result === 'loss').length;
    const ban = topEntries(games, (game) => game.foeBans?.[0], 1)[0] || null;
    const pick = topEntries(games, (game) => game.foePicks?.[0], 1)[0] || null;
    const two = topEntries(games, (game) => game.foePicks?.slice(0, 2), 1)[0] || null;
    const tags = topEntries(games, (game) => game.foeTags?.[0], 2);
    return [slot, { slot, games, winCount, decided, ban, pick, two, tags }];
  }));
  const selected = Math.min(bestOf, Math.max(1, Number(ui.boSlot) || 1));
  const stat = stats.get(selected) || { games: [], winCount: 0, decided: 0, tags: [] };
  const cur = (current.games || []).find((game) => Number(game.index) === selected) || null;
  const samePick = !!(cur && stat.pick && cur.foePicks?.[0] === stat.pick.key);
  const sameBan = !!(cur && stat.ban && cur.foeBans?.[0] === stat.ban.key);

  const scopeTabs = `<div class="bgx-seg" role="group" aria-label="历史范围">
    <button type="button" class="bgx-seg-btn" data-bgx-boscope="opp" aria-pressed="${scope === 'opp'}">只看本对手</button>
    <button type="button" class="bgx-seg-btn" data-bgx-boscope="all" aria-pressed="${scope === 'all'}">全部 BO${esc(String(bestOf))}</button>
  </div>`;
  const windowTabs = `<div class="bgx-seg" role="group" aria-label="时间">
    ${[['30', '近 30 天'], ['90', '近 90 天'], ['all', '全部']].map(([key, label]) =>
      `<button type="button" class="bgx-seg-btn" data-bgx-bowindow="${key}" aria-pressed="${key === windowKey}">${label}</button>`).join('')}
  </div>`;
  const sampleDates = history
    .filter((item) => (item.games || []).some((game) => Number(game.index) === selected))
    .map((item) => `${item.date ? item.date.slice(5) : '—'} ${item.opponent || ''}`.trim());
  const stepButtons = `<div class="bgv-boh-step" role="group" aria-label="切换局次">
    <button type="button" class="bgx-btn" data-boh-step="-1" ${selected <= 1 ? 'disabled' : ''}>← 上一把</button>
    <button type="button" class="bgx-btn" data-boh-step="1" ${selected >= bestOf ? 'disabled' : ''}>下一把 →</button>
  </div>`;

  const rail = slots.map((slot) => {
    const cell = stats.get(slot);
    const game = (current.games || []).find((item) => Number(item.index) === slot);
    const same = !!(game && cell.pick && cell.ban
      && game.foePicks?.[0] === cell.pick.key && game.foeBans?.[0] === cell.ban.key);
    const flag = game ? (!cell.pick ? '新' : same ? '照做' : '变招') : '';
    return `<button type="button" class="bgv-boh-slot ${slot === selected ? 'is-on' : ''} ${game ? (cell.pick ? (same ? 'is-same' : 'is-diff') : 'is-new') : ''}"
      data-bgx-boslot="${slot}" aria-pressed="${slot === selected}"
      title="${esc(gameWord(slot))} · ${cell.games.length || 0} 个样本${cell.pick ? ` · 一抢 ${cell.pick.key}` : ''}">
      <span class="bgv-boh-no">${String(slot).padStart(2, '0')}</span>
      <b>${esc(gameWord(slot))}</b>
      <span class="bgv-boh-slot-face">${cell.pick ? h.portrait(cell.pick.key, 'bgv-boh-slot-img') : '—'}</span>
      <small>${cell.games.length ? `${cell.games.length} 场` : '无样本'}</small>
      ${flag ? `<i class="bgv-boh-flag ${cell.pick ? (same ? 'is-same' : 'is-diff') : 'is-new'}">${flag}</i>` : ''}
    </button>`;
  }).join('');

  const winRate = (value) => (value.decided ? `${value.winCount}/${value.decided} · ${Math.round(value.winCount / value.decided * 100)}%` : '—');
  const subset = (predicate) => stat.games.filter(predicate);
  const banSubset = stat.ban ? subset((game) => game.foeBans?.[0] === stat.ban.key) : [];
  const pickSubset = stat.pick ? subset((game) => game.foePicks?.[0] === stat.pick.key) : [];
  const twoSubset = stat.two ? subset((game) => game.foePicks?.slice(0, 2).join('|') === stat.two.key) : [];
  const subRate = (list) => {
    const decided = list.filter((game) => game.result === 'win' || game.result === 'loss').length;
    const wins = list.filter((game) => game.result === 'win').length;
    return decided ? `${wins}/${decided} · ${Math.round(wins / decided * 100)}%` : '—';
  };
  const metaFor = (count, list, total) => {
    if (total <= 1) {
      const result = list[0]?.result;
      return `唯一 1 场${result === 'win' ? ' · 胜' : result === 'loss' ? ' · 负' : ''}`;
    }
    return `${count}/${total} 次 · ${subRate(list)}`;
  };

  const historyBlock = stat.games.length ? `
    ${boRow('首 ban', stat.ban ? boHero(h, stat.ban.key, 'is-ban') : '<span class="bgv-boh-none">—</span>',
      stat.ban ? metaFor(stat.ban.count, banSubset, stat.games.length) : '没有记录')}
    ${boRow('一抢', stat.pick ? boHero(h, stat.pick.key) : '<span class="bgv-boh-none">—</span>',
      stat.pick ? metaFor(stat.pick.count, pickSubset, stat.games.length) : '没有记录')}
    ${boRow('前两手', stat.two ? stat.two.heroes.map((hero) => boHero(h, hero)).join('') : '<span class="bgv-boh-none">—</span>',
      stat.two ? metaFor(stat.two.count, twoSubset, stat.games.length) : '没有记录')}
    ${boRow('常用体系', stat.tags.length ? stat.tags.map((tag) => `<span class="bgv-boh-tag">${esc(tag.key)}<b>${tag.count}</b></span>`).join('') : '<span class="bgv-boh-none">—</span>', '')}
    ${boRow('这一把胜率', `<b class="bgv-boh-rate">${winRate(stat)}</b>`, `${stat.games.length} 场样本`)}
  ` : `<div class="bgv-boh-empty">这个局次还没有历史样本。</div>`;

  const currentBlock = cur ? `
    ${boRow('首 ban', boHero(h, cur.foeBans?.[0], 'is-ban'), sameBan ? '和平时一样' : '变了')}
    ${boRow('一抢', boHero(h, cur.foePicks?.[0]), samePick ? '和平时一样' : '变了')}
    ${boRow('前两手', (cur.foePicks || []).slice(0, 2).map((hero) => boHero(h, hero)).join(''), '')}
    ${boRow('这一把', `<b class="bgv-boh-rate ${cur.result === 'win' ? 'is-win' : cur.result === 'loss' ? 'is-loss' : ''}">${cur.result === 'win' ? '胜' : cur.result === 'loss' ? '负' : '—'}</b>`, '')}
    <p class="bgv-boh-verdict ${samePick && sameBan ? 'is-same' : 'is-diff'}">
      ${stat.games.length < 2 && stat.pick ? '样本少（1 场），只作方向参考；' : ''}${samePick && sameBan ? '照做：首 ban 与一抢都和平时一样。'
        : !stat.pick ? '没有历史样本，先记录这一把。'
          : `变招：${sameBan ? '首 ban 照做' : `首 ban 从 ${stat.ban?.key || '—'} 换成 ${cur.foeBans?.[0] || '—'}`}；${samePick ? '一抢照做' : `一抢从 ${stat.pick.key} 换成 ${cur.foePicks?.[0] || '—'}`}。`}
    </p>
  ` : `<div class="bgv-boh-empty">本场没打到这一把${bestOf > (current.games || []).length ? '（大场已结束）' : ''}。</div>`;

  return `<section class="bgx-card bgv-boh">
    ${cardHead(esc, '02 BO 赛制 BP 习惯', `对手在 BO${esc(String(bestOf))} 的每一把，习惯怎么开`,
      '点局次看细节：他们第 N 把常 ban 谁、一抢谁、前两手什么组合；再对照本场同局次是不是照做。',
      `<span class="bgx-chip">${count(history.length)} 场 BO${esc(String(bestOf))}</span>`)}
    <div class="bgv-boh-toolbar">${scopeTabs}<span class="bgx-spacer"></span>${windowTabs}<button type="button" class="bgx-btn" data-bgx-boreset>重置</button></div>
    <div class="bgv-boh-rail">${rail}</div>
    <div class="bgv-boh-detail">
      <section class="bgv-boh-col">
        <header><span>历史 · ${esc(gameWord(selected))}</span>${stepButtons}</header>
        ${historyBlock}
        ${sampleDates.length ? `<div class="bgv-boh-samples">样本：${sampleDates.map((item) => `<span>${esc(item)}</span>`).join('')}</div>` : ''}
      </section>
      <section class="bgv-boh-col is-current">
        <header><span>本场 · ${esc(gameWord(selected))}</span><b>${cur ? (cur.result === 'win' ? '胜' : cur.result === 'loss' ? '负' : '—') : '未打到'}</b></header>
        ${currentBlock}
      </section>
    </div>
    <p class="bgv-note"><b>口径</b>局次按双方真正打过的顺序连续编号；首 ban / 一抢取该方名单第 1 个，前两手取第 1–2 个。样本 <2 场只作方向参考。</p>
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

function poolGroups(games, h) {
  const { esc } = h;
  const rows = new Map();
  for (const game of games) {
    for (const side of ['own', 'foe']) {
      for (const item of ((game[side] || {}).heroes || [])) {
        const key = item.hero;
        const row = rows.get(key) || { hero: key, lane: item.lane, type: item.type, ownApps: 0, foeApps: 0, status: item.status };
        row.ownApps = Math.max(row.ownApps, item.ownApps || 0);
        row.foeApps = Math.max(row.foeApps, item.foeApps || 0);
        row.status = item.status;
        rows.set(key, row);
      }
    }
  }
  const meta = {
    none: ['双方都没用过', '新东西'],
    own: ['只有我方用过', '我方熟'],
    foe: ['只有对方用过', '对方熟'],
    both: ['双方都用过', '舒适区'],
  };
  const order = { none: 0, own: 1, foe: 2, both: 3 };
  const list = [...rows.values()].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || a.hero.localeCompare(b.hero, 'zh-CN'));
  const counts = { none: 0, own: 0, foe: 0, both: 0 };
  for (const row of list) counts[row.status] = (counts[row.status] || 0) + 1;
  return `<div class="bgv-pool-legend">${Object.entries(meta).map(([key, [title, sub]]) => `<span class="bgv-pool-key is-${key}"><i></i>${title}<b>${counts[key] || 0}</b><em>${sub}</em></span>`).join('')}
    <span class="bgv-pool-note">我 / 敌 后面的数字是历史出场局数</span></div>
    <div class="xw-pool bgv-pool-all">${list.map((row) => `<div class="xw-hero is-${row.status}">
      ${h.portrait(row.hero, 'xw-face-img')}
      <b>${esc(row.hero)}</b>
      <small>${esc([row.lane, row.type].filter(Boolean).join(' · '))}</small>
      <small class="bgv-pool-count">我 <em>${row.ownApps}</em> · 敌 <em>${row.foeApps}</em></small>
      <span class="bgv-pool-tag is-${row.status}">${meta[row.status] ? meta[row.status][1] : '新东西'}</span>
    </div>`).join('')}</div>`;
}

export function renderCompSystem(insight, ui, h) {
  const { esc, count } = localHelpers(h);
  const block = insight.compSystem;
  if (!block || !(block.games || []).length) {
    return `${cardHead(esc, '03 阵容体系', '这场读不到阵容结构', '缺十人名单时不给体系结论。')}${emptyState('没有阵容数据。')}`;
  }
  const games = block.games.slice().sort((a, b) => (a.gameIndex || 0) - (b.gameIndex || 0));
  const known = games.filter((game) => (game.own || {}).combo || (game.foe || {}).combo).length;
  const gameRows = games.map((game) => {
    const sideLine = (side) => {
      const cell = game[side] || {};
      const bits = [cell.combo, cell.adc, cell.support, num(cell.cores) ? `${cell.cores} 核` : ''].filter(Boolean);
      return bits.length ? bits.join(' · ') : '名单缺失';
    };
    const heroes = (side) => ((game[side] || {}).heroes || []).slice(0, 5).map((item) =>
      `<span class="bgv-mini-hero" title="${esc(item.hero)}">${h.portrait(item.hero, 'bgv-mini-face')}<small>${esc(item.hero)}</small></span>`).join('');
    return `<div class="bgv-comp-game ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">
      <b>${esc(gameWord(game.gameIndex))}</b><span>${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span>
      <div class="bgv-comp-side"><small>我</small><p>${esc(sideLine('own'))}</p><div>${heroes('own')}</div></div>
      <div class="bgv-comp-side"><small>敌</small><p>${esc(sideLine('foe'))}</p><div>${heroes('foe')}</div></div>
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
        <h3>每一把的搭法：打野+边路 / 射手 / 辅助 / 核心</h3></div>
        <span class="xw-mod-meta">${games.length} 局</span></div>
      <div class="bgv-comp-games">${gameRows}</div>
    </section>

    ${anomalies ? `<div class="bgv-anoms">${anomalies}</div>` : ''}

    <section class="bgv-pool-block">
      <header class="xw-sec-head"><div class="xw-sec-title"><span class="xw-sec-num">池</span><h2>英雄池交叉：这场选出来的英雄，双方以前用没用过</h2></div>
        <span class="xw-sec-meta">我方 ${block.ownHistoryGames || 0} 局 · 对方 ${block.foeHistoryGames || 0} 局</span></header>
      ${poolGroups(games, h)}
    </section>

    <details class="bgv-details"><summary>同类型分工的面板差异（分均经济 / 输出 / 参团）</summary>
      <div class="bgv-stat-table">
        <div class="bgv-stat-row is-head"><span>分路</span><span>我方</span><span>对方</span></div>
        ${LANE_ORDER.map((lane) => {
          const own = (block.stats?.own || {})[lane] || {};
          const foe = (block.stats?.foe || {})[lane] || {};
          return `<div class="bgv-stat-row"><b>${esc(lane)}</b>
            <span>${num(own.gpm) ? `经济 ${Math.round(own.gpm)} · 输出 ${Math.round(own.dpm || 0)} · 参团 ${own.part || '—'}%` : '—'}</span>
            <span>${num(foe.gpm) ? `经济 ${Math.round(foe.gpm)} · 输出 ${Math.round(foe.dpm || 0)} · 参团 ${foe.part || '—'}%` : '—'}</span></div>`;
        }).join('')}
      </div>
      <p class="bgv-note">只做描述性对照：同样分路/类型，双方的面板产出差；不控制对手强弱与局内时长，不能当因果。</p>
    </details>
    <p class="bgv-note"><b>口径</b>类型来自赛训标签（五路 12 类）；核心数按分均经济份额 ≥18% 的分路数；英雄池「我方/对方用过」来自历史语料（对方只按同名精确匹配）。</p>
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
    <p class="bgx-bp-note">龙＝暴君/主宰/龙王；塔＝摧毁的防御塔（按建筑去重）；团＝有击杀的团战；反野＝在对方野区击杀红/蓝 buff，被反＝对方在我们野区拿到。只统计有回放事件流的局。</p>`;
}
