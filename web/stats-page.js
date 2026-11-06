/* 数据看板 —— 工作台内模块页：总览 / 队员 / 英雄 / 对手 / 阵容 / 比赛 / 采集候选 / 数据源 */

const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits = 0) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
};
const percent = (value) => value === null || value === undefined ? '—' : `${Number(value).toFixed(1)}%`;
const clock = (seconds) => {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(Number(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};

const TABS = [
  ['overview', '总览'], ['players', '队员'], ['heroes', '英雄'], ['matchups', '对位'],
  ['bp', 'BP'], ['objectives', '资源'], ['rivals', '对手'], ['lineups', '阵容'],
  ['matches', '比赛'], ['process', '过程'], ['focus', '训练闭环'], ['capture', '采集候选'], ['sources', '数据源'],
];

const state = {
  tab: 'overview',
  options: null, overview: null, players: [], heroes: [], team: null, matches: [],
  sources: null, imports: null, lineups: null, rosterMatches: null, capture: null,
  profiles: null, matchups: null, pairs: null, process: null,
  bp: null, objectives: null, scouting: null, focus: null,
  selectedPlayer: null, selectedMatch: null,
  filters: { sources: ['db', 'bundle'], from: '', to: '', player: '', hero: '', session: '', version: '', opponent: '', result: '', includePartial: false },
};

let ctx = null;
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];

function resultPill(value) {
  const label = { win: '胜', loss: '负', draw: '平', unknown: '未知' }[value] || '未知';
  return `<span class="pill ${esc(value || 'unknown')}">${label}</span>`;
}
function sourceBadges(sources) {
  const names = { db: '本机', bundle: '录像', sheet: '表格' };
  return (sources || []).map(source => `<span class="badge">${names[source] || source}</span>`).join(' ');
}
function emptyBox(text) { return `<div class="empty">${esc(text)}</div>`; }
function warningsBox(warnings) {
  if (!warnings || !warnings.length) return '<div class="warn info">没有额外提示。</div>';
  return warnings.map(w => `<div class="warn">${esc(w)}</div>`).join('');
}
function winRateBar(rate) {
  return `<div class="bar"><i style="width:${Math.max(0, Math.min(100, rate || 0))}%"></i></div>`;
}

/* ---------- 页面骨架 ---------- */

function shell() {
  return `
  <div class="page-heading"><div><h1>数据看板</h1>
    <p class="subtitle">汇总已确认比赛、录像数据包与表格导入；过程与候选数据单独标注，不与正式统计混算。</p></div>
    <div class="band-stats" id="stats-band"></div>
    <div class="band-action"><button class="button secondary" id="stats-reload">刷新数据</button></div></div>
  <section class="panel"><div class="form-section stats-filters">
    <div class="stats-filter-row">
      <div class="source-group" id="source-group"></div>
      <label class="field-inline">开始 <input id="f-from" type="date"></label>
      <label class="field-inline">结束 <input id="f-to" type="date"></label>
      <label class="field-inline">队员 <select id="f-player"><option value="">全部</option></select></label>
      <label class="field-inline">英雄 <select id="f-hero"><option value="">全部</option></select></label>
      <label class="field-inline">赛段 <select id="f-session"><option value="">全部</option></select></label>
      <label class="field-inline">版本 <select id="f-version"><option value="">全部</option></select></label>
      <label class="field-inline">结果 <select id="f-result"><option value="">全部</option></select></label>
    </div>
    <div class="stats-filter-row">
      <label class="field-inline">对手 <input id="f-opponent" list="stats-opponents" placeholder="对手"></label>
      <datalist id="stats-opponents"></datalist>
      <label class="check-inline"><input id="f-partial" type="checkbox"> 包含部分数据</label>
      <span class="flex-gap"></span>
      <button class="button" id="apply">应用</button>
      <button class="button secondary" id="reset">重置</button>
    </div>
  </div></section>
  <div class="tabs" id="stats-tabs">${TABS.map(([key, label]) => `<button class="tab${key === state.tab ? ' active' : ''}" data-tab="${key}">${label}</button>`).join('')}</div>
  <div id="stats-body"><div class="loading">正在汇总本机数据…</div></div>`;
}

function currentParams() {
  const p = new URLSearchParams();
  const f = state.filters;
  if (f.from) p.set('from', f.from);
  if (f.to) p.set('to', f.to);
  if (f.sources.length) p.set('source', f.sources.join(','));
  if (f.player) p.set('player', f.player);
  if (f.hero) p.set('hero', f.hero);
  if (f.session) p.set('session', f.session);
  if (f.version) p.set('version', f.version);
  if (f.opponent) p.set('opponent', f.opponent);
  if (f.result) p.set('result', f.result);
  if (f.includePartial) p.set('includePartial', '1');
  return p;
}
const qs = (params) => { const s = params.toString(); return s ? '?' + s : ''; };

/* ---------- 数据读取 ---------- */

async function refresh() {
  const params = qs(currentParams());
  const [overview, players, heroes, team, matches] = await Promise.all([
    ctx.api('/api/analysis/overview' + params),
    ctx.api('/api/analysis/players' + params),
    ctx.api('/api/analysis/heroes' + params),
    ctx.api('/api/analysis/teams' + params),
    ctx.api('/api/analysis/matches' + params),
  ]);
  state.overview = overview;
  state.players = players.players || [];
  state.heroes = heroes.heroes || [];
  state.team = team.team || null;
  state.matches = matches.matches || [];
  state.lineups = null;
  state.profiles = null;
  state.matchups = null;
  state.pairs = null;
  state.process = null;
  state.bp = null;
  state.objectives = null;
  state.scouting = null;
  state.focus = null;
  renderBand();
  renderTab();
}

function renderBand() {
  const d = state.overview;
  if (!d) return;
  const stat = (label, value, note = '', hot = false) =>
    `<div class="band-stat${hot ? ' hot' : ''}"><span>${label}</span><b>${esc(value)}</b>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
  $('#stats-band').innerHTML =
    stat('比赛', num(d.matches), `${num(d.decided)} 场有胜负`) +
    stat('胜率', d.winRate === null ? '—' : percent(d.winRate), `${d.wins} 胜 / ${Math.max(0, d.decided - d.wins)} 负`, true) +
    stat('队员', num(d.players), '按数据源去重') +
    stat('英雄', num(d.heroes), '出场英雄数');
}

/* ---------- 筛选区 ---------- */

function setSelect(selector, items, current, label) {
  const select = $(selector);
  const keep = current || '';
  select.innerHTML = `<option value="">全部</option>` + items.map(item => {
    const value = typeof item === 'string' ? item : item.key;
    const text = typeof item === 'string' ? item : label(item);
    return `<option value="${esc(value)}">${esc(text)}</option>`;
  }).join('');
  select.value = items.some(item => (typeof item === 'string' ? item : item.key) === keep) ? keep : '';
}

function renderFilterOptions() {
  const options = state.options;
  const box = $('#source-group');
  const choices = options?.sources || [
    { key: 'db', label: '本机记录' }, { key: 'bundle', label: '录像数据包' }, { key: 'sheet', label: '表格导入' },
  ];
  box.innerHTML = choices.map(choice => `
    <label class="source-chip${state.filters.sources.includes(choice.key) ? ' on' : ''}">
      <input type="checkbox" value="${esc(choice.key)}"${state.filters.sources.includes(choice.key) ? ' checked' : ''}>
      ${esc(choice.label)}
    </label>`).join('');
  $$('input', box).forEach(input => input.addEventListener('change', () => {
    state.filters.sources = $$('input:checked', box).map(item => item.value);
    $$('.source-chip', box).forEach(chip => chip.classList.toggle('on', $('input', chip).checked));
  }));
  setSelect('#f-player', options?.players || [], state.filters.player,
    item => `${item.label}${item.bound ? '' : ' · 未绑定'}`);
  setSelect('#f-hero', options?.heroes || [], state.filters.hero, item => item);
  setSelect('#f-session', options?.sessions || [], state.filters.session, item => item);
  setSelect('#f-version', options?.versions || [], state.filters.version, item => item);
  setSelect('#f-result', options?.results || [], state.filters.result, item => item.label);
  $('#stats-opponents').innerHTML = (options?.opponents || []).map(item => `<option value="${esc(item)}"></option>`).join('');
  $('#f-from').value = state.filters.from;
  $('#f-to').value = state.filters.to;
  $('#f-partial').checked = state.filters.includePartial;
  $('#f-opponent').value = state.filters.opponent;
}

function readFilters() {
  state.filters.from = $('#f-from').value;
  state.filters.to = $('#f-to').value;
  state.filters.player = $('#f-player').value;
  state.filters.hero = $('#f-hero').value;
  state.filters.session = $('#f-session').value;
  state.filters.version = $('#f-version').value;
  state.filters.opponent = $('#f-opponent').value.trim();
  state.filters.result = $('#f-result').value;
  state.filters.includePartial = $('#f-partial').checked;
}

function bindShell() {
  $('#stats-tabs').addEventListener('click', event => {
    const button = event.target.closest('button[data-tab]');
    if (!button) return;
    state.tab = button.dataset.tab;
    $$('#stats-tabs .tab').forEach(t => t.classList.toggle('active', t === button));
    state.selectedPlayer = null;
    state.selectedMatch = null;
    renderTab();
  });
  $('#apply').addEventListener('click', async () => {
    readFilters();
    state.selectedPlayer = null;
    state.selectedMatch = null;
    try { await refresh(); } catch (error) { ctx.toast(error.message, true); }
  });
  $('#reset').addEventListener('click', async () => {
    state.filters = { sources: ['db', 'bundle'], from: '', to: '', player: '', hero: '', session: '', version: '', opponent: '', result: '', includePartial: false };
    renderFilterOptions();
    try { await refresh(); } catch (error) { ctx.toast(error.message, true); }
  });
  $('#stats-reload').addEventListener('click', async () => {
    try {
      await ctx.api('/api/analysis/reload' + qs(currentParams()), 'POST');
      state.options = await ctx.api('/api/analysis/filters');
      state.sources = null;
      renderFilterOptions();
      await refresh();
      ctx.toast('已重新读取数据');
    } catch (error) { ctx.toast(error.message, true); }
  });
}

function renderTab() {
  const body = $('#stats-body');
  if (!body) return;
  const views = {
    overview: renderOverview, players: renderPlayers, heroes: renderHeroes, matchups: renderMatchups,
    bp: renderBp, objectives: renderObjectives, rivals: renderRivals, lineups: renderLineups,
    matches: renderMatches, process: renderProcess, focus: renderFocus,
    capture: renderCapture, sources: renderSources,
  };
  (views[state.tab] || renderOverview)();
}

/* ---------- 模块：总览 ---------- */

function formStrip() {
  const decided = state.matches
    .filter(m => m.result === 'win' || m.result === 'loss')
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  const recent = decided.slice(0, 10).reverse();
  let streak = 0;
  if (decided.length) {
    const latest = decided[0].result;
    for (const m of decided) { if (m.result === latest) streak += 1; else break; }
    const streakText = `${streak} 连${latest === 'win' ? '胜' : '败'}`;
    const dots = recent.map(m => `<span class="form-dot ${m.result}" title="${esc(m.dateText || m.date || '')} ${m.result === 'win' ? '胜' : '负'}"></span>`).join('');
    return `<div class="form-strip"><div><span class="helper">近 ${recent.length} 场</span><div class="form-dots">${dots}</div></div><div class="form-streak">${streakText}</div></div>`;
  }
  return '<div class="empty">还没有可判定胜负的比赛。</div>';
}

function monthlyTrend() {
  const byMonth = new Map();
  for (const m of state.matches) {
    if ((m.result !== 'win' && m.result !== 'loss') || !m.date) continue;
    const month = String(m.date).slice(0, 7);
    const entry = byMonth.get(month) || { played: 0, wins: 0 };
    entry.played += 1;
    if (m.result === 'win') entry.wins += 1;
    byMonth.set(month, entry);
  }
  const months = [...byMonth.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-6);
  if (!months.length) return '<div class="empty">暂无按月统计；确认比赛后展示月度胜负走势。</div>';
  return months.map(([month, entry]) => `
    <div class="month-row"><span class="month-label">${esc(month)}</span>
      <div class="bar month-bar"><i style="width:${entry.wins / entry.played * 100}%"></i></div>
      <b>${entry.wins} 胜 ${entry.played - entry.wins} 负</b></div>`).join('');
}

function table(headers, rows, emptyText = '暂无数据', numHeads = ['场次', '胜率', 'KDA', 'GPM', 'DPM', '参团']) {
  if (rows !== null && !rows.length) return emptyBox(emptyText);
  return `<div class="table-wrap"><table><thead><tr>${headers.map(h =>
    `<th class="${numHeads.includes(h) ? 'num' : ''}">${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows === null ? '' : rows.map(cells => `<tr>${cells.map((cell, i) =>
      `<td class="${numHeads.includes(headers[i]) ? 'num' : ''}">${cell ?? '—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function renderOverview() {
  const d = state.overview;
  const body = $('#stats-body');
  if (!d) { body.innerHTML = emptyBox('暂无数据。'); return; }
  const coverage = d.coverage;
  body.innerHTML = `
  <div class="cards" id="overview-cards">${[
    ['比赛', d.matches, `${d.decided} 场有胜负`],
    ['胜率', d.winRate === null ? '—' : percent(d.winRate), `${d.wins} 胜 / ${d.decided} 场`],
    ['队员', d.players, '按数据源去重'],
    ['英雄', d.heroes, '出场英雄数'],
    ['完整终局', coverage.completeMatches, '十人终局字段齐全'],
    ['部分数据', coverage.partialRows, '快照 / 缺字段'],
  ].map(([k, v, s]) => `<div class="card"><div class="k">${k}</div><div class="v${typeof v === 'string' && v.length > 5 ? ' small' : ''}">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('')}</div>
  <div class="stats-grid2">
    <section class="panel"><div class="panel-header"><div><h2>近期状态</h2><div class="panel-subtitle">按时间倒序的胜负与连胜连败</div></div></div>${formStrip()}</section>
    <section class="panel"><div class="panel-header"><div><h2>月度战绩</h2><div class="panel-subtitle">最近 6 个月</div></div></div><div class="form-section month-list">${monthlyTrend()}</div></section>
  </div>
  <div class="stats-grid2">
    <section class="panel"><div class="panel-header"><div><h2>队员概览</h2><div class="panel-subtitle">按出场场次</div></div><button class="button ghost" data-goto-tab="players">查看全部 →</button></div>
      ${table(['队员', '场次', '胜率', 'KDA', 'GPM', 'DPM', '参团'],
        d.topPlayers.map(row => [esc(row.label), num(row.matches), percent(row.winRate), num(row.kda, 2), num(row.gpm, 1), num(row.dpm, 1), percent(row.participation)]),
        '还没有计入统计的完整终局数据；可勾选“包含部分数据”查看过程快照。')}</section>
    <section class="panel"><div class="panel-header"><div><h2>英雄概览</h2><div class="panel-subtitle">按出场次数</div></div><button class="button ghost" data-goto-tab="heroes">查看全部 →</button></div>
      ${table(['英雄', '出场', '胜率', 'KDA', 'GPM'],
        d.topHeroes.map(row => [esc(row.hero), num(row.picks), percent(row.winRate), num(row.kda, 2), num(row.gpm, 1)]),
        '暂无英雄统计。')}</section>
  </div>
  <div class="stats-grid2">
    <section class="panel"><div class="panel-header"><h2>数据覆盖</h2></div><div class="coverage">${[
      ['时间轴', coverage.timelineMatches], ['记分板', coverage.scoreboardMatches],
      ['POV', coverage.povMatches], ['完整终局', coverage.completeMatches],
      ['部分行', coverage.partialRows], ['对手未知', coverage.unknownOpponentMatches],
    ].map(([label, value]) => `<div class="item"><b>${num(value)}</b><span>${label}</span></div>`).join('')}</div></section>
    <section class="panel"><div class="panel-header"><h2>提示</h2></div><div class="warnings">${warningsBox(d.warnings)}</div></section>
  </div>`;
  $$('[data-goto-tab]', body).forEach(button => button.addEventListener('click', () => {
    $(`#stats-tabs button[data-tab="${button.dataset.gotoTab}"]`).click();
  }));
}

/* ---------- 模块：队员 ---------- */

function renderPlayers() {
  const body = $('#stats-body');
  const hint = `${state.players.length} 人 · ${state.filters.includePartial ? '含部分数据' : '仅完整终局'}`;
  body.innerHTML = `
  <section class="panel"><div class="panel-header"><div><h2>资源分配档案</h2>
    <div class="panel-subtitle">占比相对本队同位置基线；基线由本队全部已确认比赛按位置平均得出</div></div></div>
    <div id="profiles-table"><div class="loading">正在计算画像…</div></div></section>
  <section class="panel section-gap"><div class="panel-header"><div><h2>队员统计</h2><div class="panel-subtitle">${hint} · 点击行查看趋势与逐场</div></div>
    <button class="button secondary" id="export-players">导出 CSV</button></div><div id="players-table"></div></section>
  <section class="panel detail hidden" id="player-detail"></section>`;
  const rows = state.players.map(player => `
    <tr data-player="${esc(player.playerKey)}">
      <td>${esc(player.label)}${player.bound ? '' : ' <span class="badge">未绑定</span>'}</td>
      <td class="num">${num(player.matches)}</td>
      <td class="num">${player.wins}/${player.decided}</td>
      <td class="num">${percent(player.winRate)}</td>
      <td class="num">${num(player.kda, 2)}</td>
      <td class="num">${num(player.gpm, 1)}</td>
      <td class="num">${num(player.dpm, 1)}</td>
      <td class="num">${percent(player.participation)}</td>
      <td>${player.heroes.slice(0, 3).map(item => `${esc(item.hero)}×${item.matches}`).join('、') || '—'}</td>
      <td><span class="pill ${player.partialRows ? 'partial' : 'full'}">${player.partialRows ? '部分' : '完整'}</span></td>
    </tr>`).join('');
  $('#players-table').innerHTML = table(
    ['队员', '场次', '胜/负', '胜率', 'KDA', 'GPM', 'DPM', '参团', '英雄池', '数据'],
    state.players.length ? null : [], '没有符合筛选的完整终局数据。若只有过程快照，请勾选“包含部分数据”再应用。')
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`);
  $$('#players-table tr[data-player]').forEach(row => row.addEventListener('click', () => {
    $$('#players-table tr').forEach(item => item.classList.remove('selected'));
    row.classList.add('selected');
    loadPlayer(row.dataset.player);
  }));
  $('#export-players').addEventListener('click', () => exportCsv('队员', ['队员', '场次', '胜', '负', '胜率%', 'KDA', 'GPM', 'DPM', '参团%', '英雄池'],
    state.players.map(p => [p.label, p.matches, p.wins, p.decided - p.wins, p.winRate, p.kda, p.gpm, p.dpm, p.participation,
      p.heroes.map(h => `${h.hero}x${h.matches}`).join(' /')])));
  ensureProfiles().then(renderProfilesTable).catch(error => {
    const box = $('#profiles-table');
    if (box) box.innerHTML = emptyBox(error.message);
  });
}

async function ensureProfiles() {
  if (state.profiles) return;
  state.profiles = await ctx.api('/api/analysis/profiles' + qs(currentParams()));
}

function renderProfilesTable() {
  const box = $('#profiles-table');
  if (!box) return;
  const data = state.profiles;
  if (!data || !data.players.length) { box.innerHTML = emptyBox('还没有绑定的本队队员数据。'); return; }
  const baselineMap = Object.fromEntries((data.baselines || []).map(item => [item.position, item]));
  const rows = data.players.map(player => {
    const base = baselineMap[player.mainPosition] || {};
    const m = player.metrics;
    const cell = (stat, unit = '') => stat ? `${num(stat.mean, 1)}${unit}` : '—';
    const withBase = (stat, baseValue, unit = '%') => {
      if (!stat) return '—';
      const delta = baseValue === undefined || baseValue === null ? '' :
        ` <span class="helper">基线 ${num(baseValue, 1)}${unit}</span>`;
      return `${num(stat.mean, 1)}${unit}${delta}<div class="helper">样本 ${stat.n}</div>`;
    };
    return `<tr data-profile="${esc(player.key)}">
      <td><strong>${esc(player.label)}</strong><div class="helper">${esc(player.mainPosition || '分路未确认')}</div></td>
      <td class="num">${num(player.games)}</td>
      <td>${withBase(m.goldShare, base.goldShare)}</td>
      <td>${withBase(m.damageShare, base.damageShare)}</td>
      <td>${withBase(m.takenShare, base.takenShare)}</td>
      <td>${cell(m.kda, '')}<div class="helper">样本 ${m.kda ? m.kda.n : 0}</div></td>
      <td>${m.kda ? num(m.kda.recent, 2) : '—'}</td>
      <td>${m.dpm ? num(m.dpm.mean, 0) : '—'}</td>
    </tr>`;
  }).join('');
  box.innerHTML = table(['队员', '场次', '经济占比', '输出占比', '承伤占比', 'KDA', '近 5 场 KDA', '分均输出'],
    data.players.length ? null : [], '', [])
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`)
    + (data.baselines?.length ? `<div class="summary-footnote">位置基线：${data.baselines.map(item =>
      `${esc(item.position)} 经济 ${num(item.goldShare, 1)}% / 输出 ${num(item.damageShare, 1)}% / 承伤 ${num(item.takenShare, 1)}%（${item.n} 局）`).join(' · ')}</div>` : '');
  $$('#profiles-table tr[data-profile]').forEach(row => row.addEventListener('click', () => {
    const target = document.querySelector(`#players-table tr[data-player="${CSS.escape(row.dataset.profile)}"]`);
    if (target) target.click();
  }));
}

function drawRadar(container, dims) {
  if (!container || !dims.length) return;
  const size = 240, cx = size / 2, cy = size / 2, radius = 92;
  const angle = index => -Math.PI / 2 + index * 2 * Math.PI / dims.length;
  const point = (index, ratio) => {
    const r = Math.min(ratio, 2) / 2 * radius;
    return `${(cx + Math.cos(angle(index)) * r).toFixed(1)},${(cy + Math.sin(angle(index)) * r).toFixed(1)}`;
  };
  const rings = [0.5, 1, 1.5].map(ratio =>
    `<polygon points="${dims.map((_, index) => point(index, ratio)).join(' ')}" fill="none" stroke="#e5e9f0" stroke-width="1"/>`).join('');
  const axes = dims.map((_, index) =>
    `<line x1="${cx}" y1="${cy}" x2="${(cx + Math.cos(angle(index)) * radius).toFixed(1)}" y2="${(cy + Math.sin(angle(index)) * radius).toFixed(1)}" stroke="#e5e9f0" stroke-width="1"/>`).join('');
  const labels = dims.map((dim, index) => {
    const lx = cx + Math.cos(angle(index)) * (radius + 16), ly = cy + Math.sin(angle(index)) * (radius + 14);
    return `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" font-size="10" fill="#76818f">${esc(dim.label)} ${dim.ratio === null ? '—' : `${dim.ratio.toFixed(2)}×`}</text>`;
  }).join('');
  const polygon = `<polygon points="${dims.map((dim, index) => point(index, dim.ratio ?? 0)).join(' ')}" fill="rgba(43,109,232,.18)" stroke="#2b6de8" stroke-width="1.6"/>`;
  container.innerHTML = `<svg viewBox="0 0 ${size} ${size}" role="img">${rings}${axes}${polygon}${labels}
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="9" fill="#9aa4b1">1.0 = 位置基线</text></svg>`;
}

async function loadPlayer(key) {
  state.selectedPlayer = key;
  const detail = $('#player-detail');
  detail.classList.remove('hidden');
  detail.innerHTML = '<div class="empty">加载队员趋势…</div>';
  try {
    const data = await ctx.api(`/api/analysis/players/${encodeURIComponent(key)}/trend` + qs(currentParams()));
    const points = data.points || [];
    const profile = state.profiles?.players?.find(item => item.key === key);
    const baseline = profile ? (state.profiles.baselines || []).find(item => item.position === profile.mainPosition) : null;
    const radarDims = profile && baseline ? [
      { label: '输出占比', ratio: profile.metrics.damageShare && baseline.damageShare ? profile.metrics.damageShare.mean / baseline.damageShare : null },
      { label: '经济占比', ratio: profile.metrics.goldShare && baseline.goldShare ? profile.metrics.goldShare.mean / baseline.goldShare : null },
      { label: '承伤占比', ratio: profile.metrics.takenShare && baseline.takenShare ? profile.metrics.takenShare.mean / baseline.takenShare : null },
      { label: '分均输出', ratio: profile.metrics.dpm && baseline.dpm ? profile.metrics.dpm.mean / baseline.dpm : null },
      { label: '参团率', ratio: profile.metrics.participation && baseline.participation ? profile.metrics.participation.mean / baseline.participation : null },
      { label: 'KDA', ratio: profile.metrics.kda && baseline.kda ? profile.metrics.kda.mean / baseline.kda : null },
    ].filter(dim => dim.ratio !== null) : [];
    const stability = profile ? [
      ['KDA', profile.metrics.kda ? `${num(profile.metrics.kda.mean, 2)} ±${num(profile.metrics.kda.std, 2)}` : '—',
        `地板 ${profile.metrics.kda ? num(profile.metrics.kda.floor, 2) : '—'} / 天花板 ${profile.metrics.kda ? num(profile.metrics.kda.ceil, 2) : '—'}`],
      ['场均死亡', profile.metrics.deaths ? num(profile.metrics.deaths.mean, 1) : '—',
        profile.metrics.deaths ? `最差 ${num(profile.metrics.deaths.ceil, 0)}` : ''],
      ['近 5 场 KDA', profile.metrics.kda ? num(profile.metrics.kda.recent, 2) : '—',
        profile.metrics.kda ? `赛季 ${num(profile.metrics.kda.mean, 2)}` : ''],
      ['分均输出', profile.metrics.dpm ? num(profile.metrics.dpm.mean, 0) : '—',
        profile.metrics.dpm ? `地板 ${num(profile.metrics.dpm.floor, 0)}` : ''],
    ] : null;
    detail.innerHTML = `
      <div class="panel-header"><div><h2>${esc(data.label)} · 逐场趋势</h2><div class="panel-subtitle">${points.length} 场 · ${state.filters.includePartial ? '含部分数据' : '仅完整终局'}</div></div></div>
      <div class="form-section">
        ${stability ? `<div class="cards stat-cards">${stability.map(([k, v, s]) =>
          `<div class="card"><div class="k">${k}</div><div class="v small">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('')}</div>` : ''}
        <div class="stats-grid2">
          ${radarDims.length ? `<div class="panel"><div class="panel-header"><div><h2>六维画像</h2><div class="panel-subtitle">相对${esc(profile.mainPosition)}位置基线；1.0 = 全队同位置平均</div></div></div><div class="form-section"><div id="player-radar"></div><div class="legend"><span><i style="background:#2b6de8"></i>该队员</span></div></div></div>` : ''}
          <div class="panel"><div class="panel-header"><div><h2>逐场趋势</h2><div class="panel-subtitle">${points.length} 场 · ${state.filters.includePartial ? '含部分数据' : '仅完整终局'}</div></div></div>
          <div class="form-section"><div class="chart" id="player-chart"></div><div class="legend"><span><i style="background:#2b6de8"></i>KDA</span></div></div></div>
        </div>
        ${table(['日期', '对手', '结果', '英雄', 'K/D/A', 'KDA', 'GPM', 'DPM', '参团', '来源'],
          points.map(point => [
            esc(point.date || '—'), esc(point.opponent || '—'), resultPill(point.result), esc(point.hero || '—'),
            `${num(point.kills)}/${num(point.deaths)}/${num(point.assists)}`,
            num(point.kda, 2), num(point.gpm, 1), num(point.dpm, 1), percent(point.participation), sourceBadges([point.source]),
          ]), '没有逐场数据。')}
        <div class="warnings">${warningsBox(data.warnings)}</div>
      </div>`;
    drawLine($('#player-chart'), [{
      name: 'KDA', color: '#2b6de8',
      points: points.map((point, index) => ({ x: index, y: point.kda, label: `${point.date || ''} ${point.hero || ''}`.trim() })),
    }], { xLabels: points.map(point => point.date || ''), yFormat: value => num(value, 2) });
    drawRadar($('#player-radar'), radarDims);
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) { detail.innerHTML = emptyBox(error.message); }
}

/* ---------- 模块：英雄 ---------- */

function renderHeroes() {
  const body = $('#stats-body');
  body.innerHTML = `
  <section class="panel"><div class="panel-header"><div><h2>英雄统计</h2>
    <div class="panel-subtitle">${state.heroes.length} 个英雄 · ${state.filters.includePartial ? '含部分数据' : '仅完整终局'} · 点击行查看该英雄的全部比赛</div></div>
    <button class="button secondary" id="export-heroes">导出 CSV</button></div><div id="heroes-table"></div></section>
  <section class="panel section-gap"><div class="panel-header"><div><h2>队员 × 英雄舒适度</h2>
    <div class="panel-subtitle">该队员使用此英雄的 KDA 相对全队使用此英雄基线的偏离；双方 ≥2 场才显示</div></div></div>
    <div id="comfort-table"><div class="loading">正在计算舒适度…</div></div></section>`;
  const rows = state.heroes.map(hero => `
    <tr data-hero="${esc(hero.hero)}">
      <td><strong>${esc(hero.hero)}</strong></td><td class="num">${num(hero.picks)}</td>
      <td class="num">${hero.wins}/${hero.decided}</td><td class="num">${percent(hero.winRate)}</td>
      <td class="num">${num(hero.kda, 2)}</td><td class="num">${num(hero.gpm, 1)}</td>
      <td class="num">${num(hero.dpm, 1)}</td>
      <td>${hero.players.slice(0, 4).map(esc).join('、') || '—'}</td>
      <td><span class="pill ${hero.partialPicks ? 'partial' : 'full'}">${hero.fullPicks}/${hero.picks}</span></td>
    </tr>`).join('');
  $('#heroes-table').innerHTML = table(
    ['英雄', '出场', '胜/负', '胜率', 'KDA', 'GPM', 'DPM', '常用队员', '完整'],
    state.heroes.length ? null : [], '没有符合筛选的英雄数据。')
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`);
  $$('#heroes-table tr[data-hero]').forEach(row => row.addEventListener('click', () => {
    state.filters.hero = row.dataset.hero;
    state.tab = 'matches';
    $$('#stats-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'matches'));
    refresh().catch(error => ctx.toast(error.message, true));
  }));
  $('#export-heroes').addEventListener('click', () => exportCsv('英雄', ['英雄', '出场', '胜', '负', '胜率%', 'KDA', 'GPM', 'DPM', '常用队员'],
    state.heroes.map(h => [h.hero, h.picks, h.wins, h.decided - h.wins, h.winRate, h.kda, h.gpm, h.dpm, h.players.join(' /')])));
  ensureProfiles().then(() => {
    const box = $('#comfort-table');
    if (!box) return;
    const comfort = state.profiles?.comfort || [];
    if (!comfort.length) { box.innerHTML = emptyBox('还没有足够样本的英雄×队员组合（各 ≥2 场）。'); return; }
    box.innerHTML = table(['队员', '英雄', '场次', '组合 KDA', '英雄基线 KDA', '偏离'],
      comfort.map(item => [esc(item.player), esc(item.hero), num(item.n), num(item.kda, 2), num(item.baseline, 2),
        `<span class="${item.delta >= 0 ? 'win' : 'loss'}">${item.delta >= 0 ? '+' : ''}${num(item.delta, 2)}</span>`]),
      '', ['场次', '组合 KDA', '英雄基线 KDA', '偏离'])
      + '<div class="summary-footnote">偏离为描述性统计，样本量小，不构成实力评价；正负只代表相对本队该英雄的平均水平。</div>';
  }).catch(error => {
    const box = $('#comfort-table');
    if (box) box.innerHTML = emptyBox(error.message);
  });
}

/* ---------- 模块：对手 ---------- */

function renderRivals() {
  const team = state.team;
  const body = $('#stats-body');
  const cards = team ? [
    ['比赛', num(team.matches), `完整队局 ${num(team.fullMatches)}`],
    ['胜率', team.winRate === null ? '—' : percent(team.winRate), `${team.wins} 胜 / ${team.decided} 场`],
    ['场均经济', num(team.avgGold), `样本 ${num(team.samples?.gold)}`],
    ['场均经济差', num(team.avgGoldDiff), `样本 ${num(team.samples?.goldDiff)}`],
    ['场均击杀', num(team.avgKills, 1), '队伍合计'],
  ] : [];
  body.innerHTML = `
  <div class="cards">${cards.map(([k, v, s]) => `<div class="card"><div class="k">${k}</div><div class="v${String(v).length > 5 ? ' small' : ''}">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('')}</div>
  <div class="stats-grid2">
    <section class="panel"><div class="panel-header"><div><h2>对手对阵</h2><div class="panel-subtitle">按对手汇总胜负与经济差</div></div></div><div id="rivals-table"></div></section>
    <section class="panel"><div class="panel-header"><div><h2>阵营与样本</h2><div class="panel-subtitle">本队被记录在截图左 / 右侧的分布</div></div></div><div class="coverage" id="rivals-side"></div></section>
  </div>
  <section class="panel section-gap"><div class="panel-header"><div><h2>对手侦察档案</h2>
    <div class="panel-subtitle">历史交锋、对手英雄池与 BP 习惯；再约同一对手前先看这一页</div></div></div>
    <div id="scouting-body"><div class="loading">正在整理侦察档案…</div></div></section>`;
  const opponents = team?.opponents || [];
  $('#rivals-table').innerHTML = (team && !team.available)
    ? emptyBox('没有识别本队阵营的比赛。')
    : (opponents.length
      ? table(['对手', '比赛', '胜/负', '胜率', '胜率条'],
        opponents.map(row => [esc(row.name), num(row.matches), `${row.wins}/${row.decided}`, percent(row.winRate), winRateBar(row.winRate)]),
        '暂无对手信息。', ['比赛', '胜/负', '胜率'])
      : emptyBox('暂无对手信息。'))
    + (team && team.fullMatches === 0 ? '<div class="warn info">当前没有完整终局数据，队伍场均值为空；勾选“包含部分数据”可查看过程快照。</div>' : '');
  const sides = Object.entries(team?.side || {});
  $('#rivals-side').innerHTML = sides.length
    ? sides.map(([side, count]) => `<div class="item"><b>${num(count)}</b><span>${esc({ blue: '蓝方', red: '红方', left: '截图左侧', right: '截图右侧' }[side] || side)}</span></div>`).join('')
    : emptyBox('阵营未知。');
  Promise.all([ctx.api('/api/analysis/scouting' + qs(currentParams())), ensureBp()]).then(([scouting]) => {
    const box = $('#scouting-body');
    if (!box) return;
    const opponents = (scouting.opponents || []).filter(item => item.opponent !== '对手未知' || (scouting.opponents || []).length === 1);
    if (!opponents.length) { box.innerHTML = emptyBox('还没有已确认比赛的对手记录。'); return; }
    const habits = Object.fromEntries((state.bp?.opponents || []).map(item => [item.opponent, item]));
    box.innerHTML = opponents.map(item => {
      const habit = habits[item.opponent];
      return `<details class="fold-fold"><summary><strong>${esc(item.opponent)}</strong>
        <span class="helper">${item.matches} 局 · ${item.decided ? `胜率 ${percent(item.winRate)}` : '胜负未判定'}</span></summary>
      <div class="form-section scouting-grid">
        <div><strong>交锋与阵营</strong><div class="helper">我方在截图左 ${item.sides.left} 次 / 右 ${item.sides.right} 次；判定胜负 ${item.decided} 局</div></div>
        <div><strong>对手常用英雄</strong><div class="bp-habit-list">${item.enemyHeroes.length ? item.enemyHeroes.map(([hero, count]) => `<span class="tag red">${esc(hero)} ×${count}</span>`).join('') : '<span class="helper">无记录</span>'}</div></div>
        <div><strong>我方应对英雄</strong><div class="bp-habit-list">${item.ownHeroes.length ? item.ownHeroes.map(([hero, count]) => `<span class="tag blue">${esc(hero)} ×${count}</span>`).join('') : '<span class="helper">无记录</span>'}</div></div>
        <div><strong>他们的 BP 习惯</strong><div class="bp-habit-list">${habit && (habit.bans.length || habit.picks.length)
          ? `${habit.bans.map(([hero, count]) => `<span class="tag gray">禁 ${esc(hero)} ×${count}</span>`).join('')}${habit.picks.map(([hero, count]) => `<span class="tag blue">选 ${esc(hero)} ×${count}</span>`).join('')}`
          : '<span class="helper">等结构化 BP 数据（比赛校对页填写后自动出现）</span>'}</div></div>
      </div></details>`;
    }).join('');
  }).catch(error => { $('#scouting-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：阵容 ---------- */

async function ensureLineups() {
  if (state.lineups) return;
  const params = currentParams();
  for (const key of ['player', 'hero', 'result']) params.delete(key);
  const summary = await ctx.api('/api/summary' + qs(params));
  const roster = await ctx.api('/api/state');
  state.lineups = summary.lineups || [];
  state.rosterMatches = roster.matches || [];
}

function renderLineups() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>本队五人组合</h2>
    <div class="panel-subtitle">来自已确认比赛；组合按本队五名英雄去重统计</div></div></div><div id="lineups-table"></div>
    <div id="lineups-detail"></div></section>
    <section class="panel section-gap"><div class="panel-header"><div><h2>双人协同</h2>
    <div class="panel-subtitle">两名绑定队员同场时的胜负；先看同场次数，再看胜率</div></div></div>
    <div id="pairs-table"><div class="loading">正在计算协同矩阵…</div></div></section>`;
  renderLineupsTable();
  ensureLineups().then(() => renderLineupsTable()).catch(error => {
    $('#lineups-table').innerHTML = emptyBox(error.message);
  });
  ensurePairs().then(() => renderPairsTable()).catch(error => {
    const box = $('#pairs-table');
    if (box) box.innerHTML = emptyBox(error.message);
  });
}

async function ensurePairs() {
  if (state.pairs) return;
  state.pairs = await ctx.api('/api/analysis/pairs' + qs(currentParams()));
}

function renderPairsTable() {
  const box = $('#pairs-table');
  if (!box) return;
  const pairs = (state.pairs?.pairs || []).filter(item => item.games >= 2);
  if (!pairs.length) { box.innerHTML = emptyBox('还没有同场 ≥2 次的队员组合；比赛积累后自动出现。'); return; }
  box.innerHTML = table(['队员组合', '同场', '胜', '胜率', '胜率条'],
    pairs.slice(0, 20).map(item => [
      `${esc(item.a.label)}${item.a.position ? `（${esc(item.a.position)}）` : ''} + ${esc(item.b.label)}${item.b.position ? `（${esc(item.b.position)}）` : ''}`,
      num(item.games), num(item.wins), percent(item.winRate), winRateBar(item.winRate),
    ]), '', ['同场', '胜', '胜率'])
    + `<div class="summary-footnote">只统计双方都已绑定队员身份的场次；同场次数少时胜率只是描述，不代表组合强度。</div>`;
}

function renderLineupsTable() {
  const box = $('#lineups-table');
  if (!box) return;
  if (!state.lineups) { box.innerHTML = '<div class="loading">正在读取已确认比赛…</div>'; return; }
  const rows = state.lineups.map(l => `
    <tr data-lineup="${esc(l.name)}">
      <td><strong>${esc(l.name)}</strong></td>
      <td class="num">${num(l.games)}</td>
      <td class="num">${num(l.wins)}</td>
      <td class="num">${percent(l.games ? l.wins / l.games * 100 : null)}</td>
      <td>${winRateBar(l.games ? l.wins / l.games * 100 : 0)}</td>
      <td><button class="button ghost" data-lineup-detail="${esc(l.name)}">逐局证据 →</button></td>
    </tr>`).join('');
  box.innerHTML = table(['五人组合', '出场', '胜', '胜率', '胜率条', '证据'],
    state.lineups.length ? null : [], '还没有已确认的比赛；先在比赛档案完成校对入库。', ['出场', '胜', '胜率'])
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`);
  $$('[data-lineup-detail]', box).forEach(button => button.addEventListener('click', () => {
    const lineup = state.lineups.find(l => l.name === button.dataset.lineupDetail);
    if (!lineup) return;
    const detail = $('#lineups-detail');
    const matches = (lineup.matchIds || []).map(id => state.rosterMatches?.find(m => m.id === id)).filter(Boolean);
    detail.innerHTML = `<div class="panel-header"><h2>${esc(lineup.name)}</h2><span class="tag gray">${matches.length} 局</span></div>` +
      (matches.length ? matches.map(m => `
        <a class="recent-row" href="#edit/${esc(m.id)}"><div><strong>vs ${esc(m.opponent || '对手待填写')}</strong>
        <small>${esc(m.date || '日期待补充')} · ${esc(m.session || '日常训练')}</small></div>
        ${m.side === m.winner ? '<span class="tag">胜利</span>' : m.status === 'draft' ? '<span class="tag amber">待校对</span>' : '<span class="tag red">失利</span>'}</a>`).join('')
      : emptyBox('没有找到对应的比赛记录。'));
  }));
}

/* ---------- 模块：比赛 ---------- */

function renderMatches() {
  const body = $('#stats-body');
  body.innerHTML = `
  <section class="panel"><div class="panel-header"><div><h2>比赛列表</h2>
    <div class="panel-subtitle">${state.matches.length} 场 · 点击行查看十人终局与过程数据</div></div></div><div id="matches-table"></div></section>
  <section class="panel detail hidden" id="match-detail"></section>`;
  const rows = state.matches.map(match => `
    <tr data-match="${esc(match.key)}">
      <td>${esc(match.dateText || match.date || '—')}</td>
      <td>${esc(match.opponent || '未知对手')}</td>
      <td>${resultPill(match.result)}</td>
      <td class="num">${clock(match.duration)}</td>
      <td class="num">${num(match.players)}</td>
      <td><span class="pill ${match.complete ? 'full' : 'partial'}">${match.complete ? '完整' : '部分'}</span></td>
      <td>${[match.hasTimeline ? '时间轴' : '', match.hasScoreboard ? '记分板' : '', match.hasPov ? 'POV' : ''].filter(Boolean).join(' / ') || '—'}</td>
      <td>${sourceBadges(match.sources)}</td>
    </tr>`).join('');
  $('#matches-table').innerHTML = table(['日期', '对手', '结果', '时长', '队员', '终局', '过程', '来源'],
    state.matches.length ? null : [], '没有符合筛选的比赛。', ['时长', '队员'])
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`);
  $$('#matches-table tr[data-match]').forEach(row => row.addEventListener('click', () => loadMatch(row.dataset.match)));
}

async function loadMatch(key) {
  state.selectedMatch = key;
  const detail = $('#match-detail');
  detail.classList.remove('hidden');
  detail.innerHTML = '<div class="empty">加载比赛…</div>';
  try {
    const match = await ctx.api(`/api/analysis/matches/${encodeURIComponent(key)}`);
    const process = match.process || {};
    const players = match.players || [];
    const rows = players.map(player => `
      <tr><td>${esc(player.camp || '—')}</td><td>${esc(player.hero || '—')}</td>
        <td>${esc(player.label || '—')}${player.playerId ? '' : ' <span class="badge">未绑定</span>'}</td>
        <td class="num">${num(player.kills)}/${num(player.deaths)}/${num(player.assists)}</td>
        <td class="num">${num(player.kda, 2)}</td><td class="num">${num(player.gold)}</td>
        <td class="num">${num(player.damage)}</td><td class="num">${num(player.taken)}</td>
        <td class="num">${percent(player.participation)}</td><td class="num">${num(player.rating, 2)}</td>
        <td><span class="pill ${player.partial ? 'partial' : 'full'}">${player.partial ? '部分' : '完整'}</span></td></tr>`).join('');
    const timeline = process.timeline || [];
    const snapshots = process.scoreboardSnapshots || [];
    const povs = players.flatMap(player => (player.process?.pov || []).map(segment => ({ player, segment })));
    const last = timeline[timeline.length - 1];
    const scoreText = match.scores && Object.keys(match.scores).length
      ? Object.entries(match.scores).map(([k, v]) => `${k} ${v}`).join(' / ') : '—';
    detail.innerHTML = `
      <div class="panel-header"><div><h2>${esc(match.dateText || match.date || '比赛')} · ${esc(match.opponent || '未知对手')}</h2>
        <div class="panel-subtitle">时长 ${clock(match.duration)} · 模式 ${esc(match.mode || '—')} · 本队阵营 ${esc({blue:'蓝方',left:'蓝方',red:'红方',right:'红方'}[match.ownCamp] || '—')} · 比分 ${esc(scoreText)}${last ? ` · 终局经济 蓝 ${num(last.blueGold)} / 红 ${num(last.redGold)}` : ''}</div></div>
        <div class="review-actions">${resultPill(match.result)}${sourceBadges(match.sources)}</div></div>
      <div class="form-section">
        <h3 class="detail-title">十人终局</h3>
        ${table(['阵营', '英雄', '队员', 'K/D/A', 'KDA', '经济', '输出', '承伤', '参团', '评分', '状态'],
          players.length ? null : [], '没有队员数据', ['KDA', '经济', '输出', '承伤', '参团', '评分'])
          .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`)}
        <h3 class="detail-title">团队经济</h3>
        <div class="chart" id="match-chart"></div>
        <div class="legend"><span><i style="background:#2f6fe4"></i>蓝方经济</span><span><i style="background:#e5483d"></i>红方经济</span></div>
        ${timeline.length ? '' : '<div class="sub">这场没有录像时间轴，只有终局数据。</div>'}
        ${snapshots.length ? `<details class="fold"><summary>记分板快照 · ${snapshots.length} 个时间点</summary>${snapshotTable(snapshots)}</details>` : ''}
        ${povs.length ? `<details class="fold"><summary>POV 面板段 · ${povs.length} 段</summary>${povTable(povs)}</details>` : ''}
        <h3 class="detail-title">提示</h3><div class="warnings">${warningsBox(match.warnings || [])}</div>
      </div>`;
    if (timeline.length) {
      drawLine($('#match-chart'), [
        { name: '蓝方', color: '#2f6fe4', points: timeline.map(point => ({ x: point.gameTime, y: point.blueGold, label: `${clock(point.gameTime)} 蓝 ${num(point.blueGold)}` })) },
        { name: '红方', color: '#e5483d', points: timeline.map(point => ({ x: point.gameTime, y: point.redGold, label: `${clock(point.gameTime)} 红 ${num(point.redGold)}` })) },
      ], { xLabels: timeline.map(point => clock(point.gameTime)), yFormat: value => num(value) });
    }
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) { detail.innerHTML = emptyBox(error.message); }
}

function snapshotTable(snapshots) {
  const rows = [];
  for (const snapshot of snapshots) {
    for (const player of snapshot.players || []) {
      rows.push(`<tr><td>${clock(snapshot.gameTime)}</td><td>${esc(player.camp || '')}</td>
        <td>${esc(player.hero || '')}</td><td>${esc(player.nickname || '')}</td>
        <td class="num">${(player.kda || []).map(v => v === null ? '—' : v).join('/')}</td>
        <td class="num">${num(player.totalGold)}</td></tr>`);
    }
  }
  return table(['时间', '阵营', '英雄', '队员', 'K/D/A', '累计经济'], rows.length ? null : [], '', ['累计经济'])
    .replace('<tbody></tbody>', `<tbody>${rows.join('')}</tbody>`);
}

function povTable(povs) {
  const rows = povs.map(({ player, segment }) => `
    <tr><td>${esc(player.hero || '')}</td><td>${esc(player.label || '')}</td>
      <td>${clock(segment.gameStart)}–${clock(segment.gameEnd)}</td>
      <td class="num">${num(segment.levelFirst)}→${num(segment.levelLast)}</td>
      <td class="num">${(segment.kdaFirst || []).join('/')} → ${(segment.kdaLast || []).join('/')}</td>
      <td class="num">${num(segment.availableGoldFirst)}→${num(segment.availableGoldLast)}</td>
      <td>${esc(segment.runes?.raw || '—')}</td>
      <td class="num">${segment.equipment?.filled ?? '—'}/6</td></tr>`).join('');
  return table(['英雄', '队员', '局内段', '等级', 'KDA', '可用金币', '铭文', '装备槽'],
    rows.length ? null : [], '', ['等级', 'KDA', '可用金币', '装备槽'])
    .replace('<tbody></tbody>', `<tbody>${rows}</tbody>`);
}

/* ---------- 模块：对位 ---------- */

function diffText(value) {
  if (value === null || value === undefined) return '—';
  return `${value > 0 ? '+' : ''}${num(value)}`;
}

function dotStrip(rows) {
  if (!rows.length) return '';
  const diffs = rows.map(row => row.diff);
  const min = Math.min(...diffs, 0), max = Math.max(...diffs, 0);
  const span = max - min || 1;
  const pos = diff => ((diff - min) / span * 100).toFixed(1);
  const zero = ((0 - min) / span * 100).toFixed(1);
  const dots = rows.map(row => {
    const color = row.win === true ? 'win' : row.win === false ? 'loss' : 'neutral';
    return `<span class="strip-dot ${color}" style="left:${pos(row.diff)}%" title="${esc(row.date || '')} ${esc(row.opponent)} ${diffText(row.diff)}"></span>`;
  }).join('');
  return `<div class="dot-strip"><span class="zero-line" style="left:${zero}%"></span>${dots}</div>`;
}

async function ensureMatchups() {
  if (state.matchups) return;
  state.matchups = await ctx.api('/api/analysis/lane-matchups' + qs(currentParams()));
}

function renderMatchups() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>对线质量</h2>
    <div class="panel-subtitle">同分路双方都确认身份时，才生成终局经济差对照；正 = 我方压钱</div></div></div>
    <div id="matchups-body"><div class="loading">正在聚合对线数据…</div></div></section>`;
  ensureMatchups().then(() => {
    const box = $('#matchups-body');
    if (!box) return;
    const data = state.matchups;
    const positions = data.positions || [];
    const byLane = {};
    for (const row of data.rows || []) (byLane[row.position] = byLane[row.position] || []).push(row);
    if (!positions.length) {
      box.innerHTML = emptyBox('还没有可统计的对线对照。需要比赛中双方十人的实际分路都已确认；可在比赛校对页补齐后回来看。');
      return;
    }
    box.innerHTML = `
    <div class="cards">${positions.map(item => `<div class="card">
      <div class="k">${esc(item.position)} · ${item.n} 局</div>
      <div class="v ${item.avgDiff >= 0 ? '' : 'small'}">${diffText(item.avgDiff)}</div>
      <div class="s">平均终局经济差 · 占优率 ${percent(item.aheadRate)}${item.winWhenAhead !== null ? ` · 占优时胜率 ${percent(item.winWhenAhead)}` : ''}</div>
    </div>`).join('')}</div>
    <div class="form-section">${positions.map(item => `
      <div class="lane-block"><div class="lane-head"><strong>${esc(item.position)}</strong>
        <span class="helper">${item.n} 局 · 平均 ${diffText(item.avgDiff)}${item.avgKdaDiff !== null && item.avgKdaDiff !== undefined ? ` · KDA 差 ${diffText(item.avgKdaDiff)}` : ''}</span></div>
      ${dotStrip(byLane[item.position] || [])}</div>`).join('')}
    <div class="legend"><span><i style="background:var(--ok)"></i>对线占优且赢下</span><span><i style="background:var(--team-red)"></i>对线落后且输掉</span><span><i style="background:#c3ccd8"></i>其他</span></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th>对手</th><th>分路</th><th>我方</th><th>对方</th><th class="num">经济差</th><th>结果</th></tr></thead>
    <tbody>${(data.rows || []).slice(0, 60).map(row => `<tr>
      <td>${esc(row.date || '—')}</td><td>${esc(row.opponent || '—')}</td><td>${esc(row.position)}</td>
      <td>${esc(row.ownLabel || '')} ${esc(row.ownHero)}</td><td>${esc(row.enemyHero)}</td>
      <td class="num"><strong class="${row.diff > 0 ? 'win' : row.diff < 0 ? 'loss' : ''}">${diffText(row.diff)}</strong></td>
      <td>${row.win === null ? '—' : row.win ? '胜' : '负'}</td></tr>`).join('')}</tbody></table></div>`;
  }).catch(error => { $('#matchups-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：过程 ---------- */

function resampleCurve(points, steps = 30) {
  if (points.length < 2) return points;
  const out = [];
  const first = points[0][0], last = points[points.length - 1][0];
  let cursor = 0;
  for (let i = 0; i <= steps; i += 1) {
    const t = first + (last - first) * i / steps;
    while (cursor < points.length - 2 && points[cursor + 1][0] < t) cursor += 1;
    const [t0, d0] = points[cursor];
    const [t1, d1] = points[cursor + 1] || [t0 + 1, d0];
    const ratio = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
    out.push([t, d0 + (d1 - d0) * ratio]);
  }
  return out;
}

async function ensureProcess() {
  if (state.process) return;
  state.process = await ctx.api('/api/analysis/process' + qs(currentParams()));
}

function renderProcess() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>时段画像</h2>
    <div class="panel-subtitle">只统计时间轴覆盖 ≥60% 且本队阵营已知的比赛；曲线按各局自身时长归一化</div></div>
    <span class="tag gray" id="process-count">…</span></div>
    <div id="process-body"><div class="loading">正在聚合过程数据…</div></div></section>`;
  ensureProcess().then(() => {
    const box = $('#process-body');
    if (!box) return;
    const data = state.process;
    const agg = data.aggregate || {};
    const matches = data.matches || [];
    $('#process-count').textContent = `${agg.games ?? 0} 局达标`;
    if (!matches.length) {
      box.innerHTML = emptyBox('还没有覆盖 ≥60% 的录像时间轴。把回放录屏交给「回放文件 → OCR」，再在「采集通道」关联到比赛后，这里会自动出现时段分析。');
      return;
    }
    const cards = [
      ['前期优势转化率', agg.leadAt10Conversion === null ? '—' : percent(agg.leadAt10Conversion),
        `10 分钟领先的 ${agg.leadAt10Games} 局最终胜率`],
      ['翻盘 / 被翻盘', `${agg.comebacks ?? 0} / ${agg.blownLeads ?? 0}`, '按 10 分钟落后/领先到终局反转'],
      ['分均击杀', agg.avgKillsPerMinute === null ? '—' : num(agg.avgKillsPerMinute, 2), `${agg.games} 局平均`],
      ['15 分钟经济差', agg.avgDiffAt?.['900'] === null || agg.avgDiffAt?.['900'] === undefined ? '—' : diffText(agg.avgDiffAt['900']),
        `样本 ${matches.length} 局`],
    ];
    const series = matches.map(entry => ({
      name: `${entry.date || ''} ${entry.opponent || ''}`.trim(),
      color: entry.win === true ? 'rgba(43,109,232,.55)' : entry.win === false ? 'rgba(229,72,61,.5)' : 'rgba(120,130,143,.45)',
      dots: false,
      points: resampleCurve(entry.points).map(point => ({ x: point[0], y: point[1], label: `${entry.date || ''} ${entry.opponent || ''} ${Math.round(point[0] / 60)}分 ${diffText(Math.round(point[1]))}` })),
    }));
    const xLabels = Array.from({ length: 31 }, (_, i) => i % 15 === 0 ? `${Math.round(i / 30 * 100)}%` : '');
    box.innerHTML = `
    <div class="cards">${cards.map(([k, v, s]) => `<div class="card"><div class="k">${k}</div><div class="v small">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('')}</div>
    <div class="form-section"><h3 class="detail-title">经济差曲线叠加（正 = 我方领先）</h3>
      <div class="chart" id="process-chart"></div>
      <div class="legend"><span><i style="background:#2b6de8"></i>最终获胜</span><span><i style="background:#e5483d"></i>最终落败</span><span><i style="background:#78828f"></i>胜负未知</span></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th>对手</th><th class="num">@2分</th><th class="num">@5分</th><th class="num">@10分</th><th class="num">@15分</th>
      <th class="num">前 5 分钟</th><th class="num">5–15 分</th><th class="num">15 分后</th><th class="num">终局</th><th>结果</th><th class="num">覆盖</th></tr></thead>
    <tbody>${matches.map(entry => `<tr>
      <td>${esc(entry.date || '—')}</td><td>${esc(entry.opponent || '—')}</td>
      <td class="num">${diffText(entry.diffAt?.['120'])}</td><td class="num">${diffText(entry.diffAt?.['300'])}</td>
      <td class="num">${diffText(entry.diffAt?.['600'])}</td><td class="num">${diffText(entry.diffAt?.['900'])}</td>
      <td class="num">${diffText(entry.phases?.early)}</td><td class="num">${diffText(entry.phases?.mid)}</td>
      <td class="num">${diffText(entry.phases?.late)}</td><td class="num"><strong class="${entry.finalDiff > 0 ? 'win' : entry.finalDiff < 0 ? 'loss' : ''}">${diffText(entry.finalDiff)}</strong></td>
      <td>${entry.win === null ? '—' : entry.win ? '胜' : '负'}</td><td class="num">${entry.coverage === null ? '—' : `${num(entry.coverage, 0)}%`}</td></tr>`).join('')}</tbody></table></div>`;
    drawLine($('#process-chart'), series, { xLabels, yFormat: value => diffText(Math.round(value)) });
  }).catch(error => { $('#process-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：BP ---------- */

async function ensureBp() {
  if (state.bp) return;
  const [bp, catalog] = await Promise.all([
    ctx.api('/api/analysis/bp' + qs(currentParams())),
    ctx.api('/api/catalog').catch(() => ({entries: []})),
  ]);
  state.bp = bp;
  state.bpIcons = {};
  ((catalog && catalog.entries) || []).forEach(entry => {
    if (entry.kind === 'hero' && entry.icon) state.bpIcons[entry.name] = entry.icon;
  });
}

function bpFace(name, meta, icons) {
  const info = (meta && meta[name]) || {};
  const src = info.icon || (icons && icons[name]) || (info.id ? `/catalog/icons/hero-${info.id}.png` : '');
  return src ? `<img src="${esc(src)}" alt="" style="width:20px;height:20px;border-radius:5px;vertical-align:middle;margin-right:5px;object-fit:cover">` : '';
}

function renderBp() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>BP 分析</h2>
    <div class="panel-subtitle">营地 battledetail 名单自动同步 + 比赛校对人工手序；旧文本 BP 不参与统计</div></div>
    <span class="tag gray" id="bp-count">…</span></div><div id="bp-body"><div class="loading">正在汇总 BP 数据…</div></div></section>`;
  ensureBp().then(() => {
    const box = $('#bp-body');
    if (!box) return;
    const data = state.bp;
    $('#bp-count').textContent = `${data.matchesWithBp || 0} 局有 BP`;
    if (!data.matchesWithBp) {
      box.innerHTML = emptyBox('还没有 BP 记录。在采集页同步营地战绩并核对入库，或在比赛校对页按手序填写双方 ban/pick。');
      return;
    }
    const win = value => value === null || value === undefined ? '—' : percent(value);
    const face = name => bpFace(name, data.heroMeta, state.bpIcons);
    const source = `<div class="helper" style="margin-bottom:10px">数据来源：营地自动 ${num(data.campBpMatches || 0)} 场 · 人工录入 ${num(data.manualBpMatches || 0)} 场；营地名单不含 pick 手序与一手方，手序统计只来自人工录入。</div>`;
    const warning = data.sampleWarning ? `<div class="helper" style="margin-bottom:10px;padding:8px;border-radius:6px;background:#fff2f0;color:#a32d2d">注意：${esc(data.sampleWarning)}</div>` : '';
    box.innerHTML = `${source}${warning}
    <div class="stats-grid2">
      <section class="panel"><div class="panel-header"><div><h2>禁用频率榜</h2><div class="panel-subtitle">括号内为实施禁用一方在该局的胜率</div></div></div>
        ${data.bans.length ? table(['英雄', '总次数', '左方禁', '右方禁', '左方胜率', '右方胜率'],
          data.bans.map(item => [`${face(item.hero)}${esc(item.hero)}`, num(item.total), num(item.byLeft), num(item.byRight), win(item.leftWinRate), win(item.rightWinRate)]),
          '', ['总次数', '左方禁', '右方禁', '左方胜率', '右方胜率']) : emptyBox('还没有禁用记录。')}</section>
      <section class="panel"><div class="panel-header"><div><h2>我方选用与手序</h2><div class="panel-subtitle">按手序分桶的胜率是描述性统计</div></div></div>
        ${data.ownPicks.length ? table(['英雄', '选用', '胜场'],
          data.ownPicks.map(item => [`${face(item.hero)}${esc(item.hero)}`, num(item.count), num(item.wins)]), '', ['选用', '胜场']) : emptyBox('还没有选用记录。')}
        <div class="form-section"><h3 class="detail-title">手序效果</h3>
        <div class="cards">${data.orderEffect.map(item => `<div class="card"><div class="k">第 ${item.order} 手</div>
          <div class="v small">${item.n ? percent(item.wins / item.n * 100) : '—'}</div><div class="s">${item.n} 局</div></div>`).join('')}</div></div></section>
    </div>
    <section class="panel section-gap"><div class="panel-header"><div><h2>对手 BP 习惯</h2><div class="panel-subtitle">按对手汇总的禁用与选用频率</div></div></div>
      ${data.opponents.filter(item => item.bans.length || item.picks.length).length ? data.opponents.map(item => `
        <details class="fold-fold"><summary>${esc(item.opponent)} · ${item.matches} 局</summary>
        <div class="form-section bp-habits"><div><strong>他们常禁</strong><div class="bp-habit-list">${item.bans.length ? item.bans.map(([hero, count]) => `<span class="tag gray">${face(hero)}${esc(hero)} ×${count}</span>`).join('') : '<span class="helper">无记录</span>'}</div></div>
        <div><strong>他们常用</strong><div class="bp-habit-list">${item.picks.length ? item.picks.map(([hero, count]) => `<span class="tag blue">${face(hero)}${esc(hero)} ×${count}</span>`).join('') : '<span class="helper">无记录</span>'}</div></div></div></details>`).join('')
      : emptyBox('还没有对手的 BP 记录。')}</section>`;
  }).catch(error => { $('#bp-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：资源 ---------- */

async function ensureObjectives() {
  if (state.objectives) return;
  state.objectives = await ctx.api('/api/analysis/objectives' + qs(currentParams()));
}

function renderObjectives() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>资源控制</h2>
    <div class="panel-subtitle">来自比赛校对页的资源速记；计数必填、时间可选；描述性统计，不构成因果</div></div></div>
    <div id="objectives-body"><div class="loading">正在汇总资源事件…</div></div></section>`;
  ensureObjectives().then(() => {
    const box = $('#objectives-body');
    if (!box) return;
    const data = state.objectives;
    const agg = data.aggregate || {};
    const labels = { tyrant: '暴君', dominator: '主宰', storm: '风暴龙王' };
    const hasData = data.rows?.length;
    if (!hasData) {
      box.innerHTML = emptyBox('还没有资源事件。在「比赛校对」页的资源速记条记下暴君/主宰/推塔，保存后这里自动出现控制率与塔数差。');
      return;
    }
    box.innerHTML = `
    <div class="cards">${Object.entries(labels).map(([key, label]) => {
      const item = agg[key] || {};
      return `<div class="card"><div class="k">${label}控制率</div>
        <div class="v small">${item.ownRate === null || item.ownRate === undefined ? '—' : percent(item.ownRate)}</div>
        <div class="s">我方 ${num(item.own)} / 对方 ${num(item.enemy)} · 胜局 ${percent(item.rateWhenWin)} / 负局 ${percent(item.rateWhenLoss)}</div></div>`;
    }).join('')}
      <div class="card"><div class="k">场均塔数差</div>
        <div class="v small">${agg.towers?.avgDiff === null || agg.towers?.avgDiff === undefined ? '—' : diffText(agg.towers.avgDiff)}</div>
        <div class="s">胜局 ${diffText(agg.towers?.diffWhenWin)} / 负局 ${diffText(agg.towers?.diffWhenLoss)}</div></div>
      <div class="card"><div class="k">一塔归属</div>
        <div class="v small">${agg.firstTower?.own || 0} : ${agg.firstTower?.enemy || 0}</div>
        <div class="s">${agg.firstTower?.winRateWhenOwnFirst ? `我方拿一塔时胜率 ${percent(agg.firstTower.winRateWhenOwnFirst)}` : '样本不足'}</div></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th>对手</th>
      <th>暴君（我:对）</th><th>主宰（我:对）</th><th>风暴（我:对）</th><th class="num">塔数差</th><th>一塔</th><th>结果</th></tr></thead>
    <tbody>${data.rows.map(row => `<tr>
      <td>${esc(row.date || '—')}</td><td>${esc(row.opponent || '—')}</td>
      <td>${num(row.counts?.tyrant?.[0])} : ${num(row.counts?.tyrant?.[1])}</td>
      <td>${num(row.counts?.dominator?.[0])} : ${num(row.counts?.dominator?.[1])}</td>
      <td>${num(row.counts?.storm?.[0])} : ${num(row.counts?.storm?.[1])}</td>
      <td class="num">${row.towerDiff === null ? '—' : diffText(row.towerDiff)}</td>
      <td>${row.firstTower === 'own' ? '我方' : row.firstTower === 'enemy' ? '对方' : '—'}</td>
      <td>${row.win === null ? '—' : row.win ? '胜' : '负'}</td></tr>`).join('')}</tbody></table></div>`;
  }).catch(error => { $('#objectives-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：训练闭环 ---------- */

const FOCUS_METRICS = {
  kda: { label: 'KDA', scope: 'player' }, deaths: { label: '场均死亡', scope: 'player' },
  dpm: { label: '分均输出', scope: 'player' }, tpm: { label: '分均承伤', scope: 'player' },
  participation: { label: '参团率', scope: 'player' }, laneDiff: { label: '对线经济差', scope: 'position' },
  win: { label: '胜负', scope: 'team' }, teamGoldDiff: { label: '终局经济差', scope: 'team' },
};
const SCOPE_LABELS = { player: '队员', position: '分路', team: '全队' };
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const FOCUS_STATUS = { active: '进行中', watching: '继续盯', improved: '已改善', archived: '已归档' };

async function ensureFocus() {
  if (state.focus) return;
  const [evaluation, roster] = await Promise.all([
    ctx.api('/api/focus/evaluate'), ctx.api('/api/state'),
  ]);
  state.focus = evaluation;
  state.roster = roster.settings?.roster || [];
}

function renderFocus() {
  const body = $('#stats-body');
  body.innerHTML = `
  <section class="panel"><div class="panel-header"><div><h2>训练重点</h2>
    <div class="panel-subtitle">每个重点绑定一个可计算指标；指标无数据时如实显示，不做估算</div></div>
    <button class="button" id="focus-toggle-create">＋ 新建重点</button></div>
    <div class="form-section hidden" id="focus-create-form">
      <div class="stats-filter-row">
        <label class="field-inline">标题 <input id="focus-title" maxlength="80" style="width:240px" placeholder="例如：中路支援偏慢"></label>
        <label class="field-inline">指标 <select id="focus-metric">${Object.entries(FOCUS_METRICS).map(([key, item]) =>
          `<option value="${key}">${item.label}（${SCOPE_LABELS[item.scope]}）</option>`).join('')}</select></label>
        <label class="field-inline">对象 <select id="focus-scope"></select></label>
        <label class="field-inline">方向 <select id="focus-direction"><option value="up">越高越好</option><option value="down">越低越好</option></select></label>
        <label class="field-inline">目标值 <input id="focus-target" inputmode="decimal" style="width:90px" placeholder="可选"></label>
        <button class="button" id="focus-create">创建</button>
      </div>
      <p class="helper">首批指标与口径见 docs/metric_registry.md；评估只用已确认比赛，按日期升序逐场取值。</p>
    </div>
    <div id="focus-list"><div class="loading">正在评估训练重点…</div></div></section>`;
  $('#focus-toggle-create').addEventListener('click', () => {
    const form = $('#focus-create-form');
    form.classList.toggle('hidden');
    if (!form.classList.contains('hidden')) renderFocusScopeSelect();
  });
  $('#focus-metric').addEventListener('change', renderFocusScopeSelect);
  $('#focus-create').addEventListener('click', async () => {
    try {
      const metric = $('#focus-metric').value;
      await ctx.api('/api/focus', 'POST', {
        title: $('#focus-title').value, metric,
        scopeType: FOCUS_METRICS[metric].scope, scopeId: $('#focus-scope').value,
        direction: $('#focus-direction').value,
        target: $('#focus-target').value === '' ? null : Number($('#focus-target').value),
      });
      state.focus = null;
      ctx.toast('训练重点已创建');
      renderFocus();
    } catch (error) { ctx.toast(error.message, true); }
  });
  ensureFocus().then(renderFocusList).catch(error => { $('#focus-list').innerHTML = emptyBox(error.message); });
}

function renderFocusScopeSelect() {
  const metric = $('#focus-metric').value;
  const spec = FOCUS_METRICS[metric];
  const select = $('#focus-scope');
  if (spec.scope === 'player') {
    select.innerHTML = (state.roster?.length ? state.roster : (state.profiles?.players || []).map(item => ({ id: item.key, name: item.label })))
      .map(player => `<option value="${esc(player.id || player.key)}">${esc(player.name || player.label)}</option>`).join('')
      || '<option value="">先在战队名单添加队员</option>';
    select.disabled = !select.options.length;
  } else if (spec.scope === 'position') {
    select.innerHTML = LANES.map(lane => `<option>${lane}</option>`).join('');
    select.disabled = false;
  } else {
    select.innerHTML = '<option value="">全队</option>';
    select.disabled = true;
  }
}

function focusSparkline(points, direction, target) {
  if (!points.length) return '';
  const width = 220, height = 46;
  const values = points.map(point => point.value);
  let min = Math.min(...values, target ?? Infinity), max = Math.max(...values, target ?? -Infinity);
  if (min === max) { max += 1; min -= 1; }
  const x = index => points.length === 1 ? width / 2 : index / (points.length - 1) * (width - 8) + 4;
  const y = value => 4 + (1 - (value - min) / (max - min)) * (height - 10);
  const path = points.map((point, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');
  const targetLine = target === null || target === undefined ? '' :
    `<line x1="4" y1="${y(target).toFixed(1)}" x2="${width - 4}" y2="${y(target).toFixed(1)}" stroke="#e0a818" stroke-dasharray="3 3" stroke-width="1"/>`;
  const dots = points.map((point, index) =>
    `<circle cx="${x(index).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="2.4" fill="${point.value === points[points.length - 1].value ? '#2b6de8' : '#93a3b8'}"><title>${esc(point.date)} ${esc(point.opportunity || point.opponent || '')} ${point.value}</title></circle>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img" class="focus-spark">${path ? `<path d="${path}" fill="none" stroke="#2b6de8" stroke-width="1.6"/>` : ''}${targetLine}${dots}</svg>`;
}

function renderFocusList() {
  const box = $('#focus-list');
  if (!box) return;
  const items = state.focus?.items || [];
  if (!items.length) {
    box.innerHTML = emptyBox('还没有训练重点。复盘一局时在编辑页关联，或在这里新建；创建后每确认一局，指标自动追加一个数据点。');
    return;
  }
  const groups = [
    ['active', '进行中'], ['watching', '继续盯'], ['improved', '已改善'], ['archived', '已归档'],
  ];
  box.innerHTML = groups.map(([status, label]) => {
    const group = items.filter(item => (item.status || 'active') === status);
    if (!group.length) return '';
    return `<div class="focus-group"><div class="focus-group-head">${label} · ${group.length}</div>
    <div class="stats-grid2">${group.map(item => {
      const spec = FOCUS_METRICS[item.metric] || { label: item.metric, scope: item.scopeType };
      const scopeLabel = item.scopeType === 'player'
        ? (state.roster?.find(player => player.id === item.scopeId)?.name || item.scopeId)
        : item.scopeType === 'position' ? item.scopeId : '全队';
      const recent = item.points.slice(-5);
      const last = item.points[item.points.length - 1];
      return `<section class="panel focus-card" data-focus="${esc(item.id)}"><div class="panel-header">
        <div><h2>${esc(item.title)}</h2><div class="panel-subtitle">${spec.label} · ${esc(scopeLabel)} · ${item.direction === 'down' ? '越低越好' : '越高越好'}${item.target !== null && item.target !== undefined ? ` · 目标 ${item.target}` : ''}</div></div>
        <span class="tag ${status === 'improved' ? '' : status === 'active' ? 'blue' : 'gray'}">${FOCUS_STATUS[status]}</span></div>
      <div class="form-section focus-card-body">
        ${item.points.length ? `${focusSparkline(recent, item.direction, item.target)}
          <div class="focus-stats"><span>基线 <b>${num(item.baseline, 2)}</b></span><span>近 ${recent.length} 场 <b>${num(item.recent, 2)}</b></span><span>最近 <b>${num(last?.value)}</b></span>${item.targetRate !== null && item.targetRate !== undefined ? `<span>近 5 场达标 <b>${percent(item.targetRate)}</b></span>` : ''}</div>
          <div class="helper">样本 ${item.points.length} 局 · ${last ? `最近一局 ${esc(last.date || '')} ${esc(last.opponent || '')}` : ''}</div>`
        : '<div class="empty">等待数据源：还没有可计算该指标的已确认比赛。</div>'}
        <div class="focus-actions">
          ${status !== 'improved' ? `<button class="button ghost" data-focus-status="${esc(item.id)}:improved">标为已改善</button>` : ''}
          ${status === 'active' ? `<button class="button ghost" data-focus-status="${esc(item.id)}:watching">继续盯</button>` : ''}
          ${status === 'watching' ? `<button class="button ghost" data-focus-status="${esc(item.id)}:active">回到进行中</button>` : ''}
          ${status !== 'archived' ? `<button class="button ghost" data-focus-status="${esc(item.id)}:archived">归档</button>` : `<button class="button ghost" data-focus-status="${esc(item.id)}:active">恢复</button>`}
        </div>
      </div></section>`;
    }).join('')}</div></div>`;
  }).join('') || emptyBox('没有该状态的训练重点。');
  box.querySelectorAll('[data-focus-status]').forEach(button => button.addEventListener('click', async () => {
    const [id, status] = button.dataset.focusStatus.split(':');
    try {
      await ctx.api(`/api/focus/${encodeURIComponent(id)}`, 'PATCH', { status });
      state.focus = null;
      renderFocusList();
    } catch (error) { ctx.toast(error.message, true); }
  }));
}

/* ---------- 模块：采集候选 ---------- */

const CAPTURE_RANKINGS = [
  { key: 'csPerMin', field: 'cs', label: '分均补刀', note: '补刀数 / 本组时长', unit: '' },
  { key: 'damageConversion', field: 'damageConversion', label: '伤害转化比', note: '输出伤害 / 总经济', unit: '' },
  { key: 'towerDamage', field: 'towerDamage', label: '对塔伤害', note: '对塔输出合计', unit: '' },
  { key: 'control', field: 'control', label: '控制效果', note: '控制时长 / 次数，按画面数值', unit: '' },
  { key: 'healing', field: 'healing', label: '治疗量', note: '治疗合计', unit: '' },
  { key: 'takenPerDeath', field: 'takenPerDeath', label: '每死承伤', note: '承伤 / 死亡', unit: '' },
];

async function ensureCapture() {
  if (state.capture) return;
  const data = await ctx.api('/api/postgame/images');
  state.capture = data;
}

function captureRows(ranking, compute) {
  const groups = state.capture?.groups || [];
  const rows = [];
  for (const group of groups) {
    const minutes = group.match?.durationSec ? group.match.durationSec / 60 : null;
    for (const player of group.players || []) {
      const value = compute(player, minutes);
      if (value === null || !Number.isFinite(value)) continue;
      rows.push({
        value, side: player.side, slot: player.slot ?? 0,
        nickname: player.nickname?.value || '未识别昵称',
        hero: player.hero?.value || '—',
        group: group.match?.date || '日期未识别',
        demo: Boolean(group.demo),
      });
    }
  }
  return rows.sort((a, b) => b.value - a.value).slice(0, 8);
}

function renderCapture() {
  const body = $('#stats-body');
  body.innerHTML = `<section class="panel"><div class="panel-header"><div><h2>采集候选 · 扩展字段</h2>
    <div class="panel-subtitle">来自「截图采集」的分页截图候选（含示例数据）；只读展示，不进入正式统计</div></div>
    <span class="tag amber">候选数据</span></div><div id="capture-body"><div class="loading">正在读取采集候选…</div></div></section>`;
  ensureCapture().then(() => {
    const box = $('#capture-body');
    if (!box) return;
    const groups = state.capture?.groups || [];
    if (!groups.length) { box.innerHTML = emptyBox('还没有采集数据。先在「截图采集」上传分页截图，或载入示例分析。'); return; }
    const covers = CAPTURE_RANKINGS.map(ranking => {
      const rows = captureRows(ranking, (player, minutes) => {
        const field = player.fields?.[ranking.field];
        if (!field || field.value === null) return null;
        if (ranking.key === 'csPerMin') return minutes ? field.value / minutes : null;
        return Number(field.value);
      });
      return `<section class="panel"><div class="panel-header"><div><h2>${ranking.label}</h2><div class="panel-subtitle">${ranking.note} · 前 8 名</div></div></div>
        ${rows.length ? `<div class="capture-rank-list">${rows.map(row => `
          <div class="capture-rank-item"><span class="capture-slot ${row.side === 'right' ? 'right' : ''}">${row.side === 'right' ? '右' : '左'}${row.slot + 1}</span>
          <strong>${esc(row.nickname)}</strong><small>${esc(row.hero)}</small>
          <em>${num(row.value, ranking.key === 'csPerMin' ? 2 : 1)}</em>
          <span class="badge">${esc(row.group)}${row.demo ? ' · 示例' : ''}</span></div>`).join('')}</div>`
        : emptyBox('这一字段还没有可读数值。')}</section>`;
    }).join('');
    const imageCount = state.capture?.images?.length || 0;
    box.innerHTML = `<div class="stats-grid2 stats-grid-wide">${covers}</div>
      <div class="summary-footnote">共 ${groups.length} 组候选 · ${imageCount} 张截图。分均补刀按组内时长折算；其余为画面原值。字段读不到时留空，不做估算。</div>`;
  }).catch(error => { $('#capture-body').innerHTML = emptyBox(error.message); });
}

/* ---------- 模块：数据源 ---------- */

async function ensureSources() {
  if (state.sources) return;
  const [sources, imports] = await Promise.all([ctx.api('/api/analysis/sources'), ctx.api('/api/analysis/imports')]);
  state.sources = sources;
  state.imports = imports;
}

function renderSources() {
  const body = $('#stats-body');
  body.innerHTML = `<div id="source-cards" class="cards"></div>
    <section class="panel"><div class="panel-header"><div><h2>表格导入</h2><div class="panel-subtitle">默认不计入单局统计；聚合表不可与单局混算</div></div></div><div id="imports-table"></div></section>
    <section class="panel"><div class="panel-header"><div><h2>聚合表</h2><div class="panel-subtitle">跨局统计，禁止再按单局求和</div></div></div><div id="aggregates-table"></div></section>
    <section class="panel"><div class="panel-header"><h2>提示</h2></div><div class="warnings" id="sources-warnings"></div></section>`;
  ensureSources().then(() => {
    const data = state.sources;
    $('#source-cards').innerHTML = [
      ['本机记录', data.db.confirmed, `草稿 ${data.db.drafts}`],
      ['录像数据包', data.bundles.count, `已关联 ${data.bundles.linked}`],
      ['表格导入', (data.imports || []).length, '默认不计入单局'],
      ['聚合表', (data.aggregates || []).length, '禁止再聚合'],
    ].map(([k, v, s]) => `<div class="card"><div class="k">${k}</div><div class="v">${num(v)}</div><div class="s">${esc(s)}</div></div>`).join('');
    const imports = state.imports?.imports || [];
    $('#imports-table').innerHTML = imports.length ? table(['文件', 'profile', '工作表', '行数', '质量'],
      imports.map(item => [esc(item.source?.name || item.id), esc(item.profileSource || '—'),
        (item.sheets || []).map(sheet => `${esc(sheet.name)}<span class="badge">${esc(sheet.grain)}</span>`).join(' '),
        num(item.quality?.rows ?? 0), item.quality?.duplicates ? `重复键 ${item.quality.duplicates}` : '—']),
      '', ['行数']) : emptyBox('还没有表格导入。先用 scripts/import_sheet.py 导入。');
    const aggregates = state.imports?.aggregates || [];
    $('#aggregates-table').innerHTML = aggregates.length ? table(['来源', '表', '粒度', '行数'],
      aggregates.map(item => [esc(item.source?.name || item.importId), esc(item.name), esc(item.grain), num(item.rowCount ?? '—')]),
      '', ['行数']) : emptyBox('没有聚合表。');
    $('#sources-warnings').innerHTML = warningsBox(data.warnings || []);
  }).catch(error => { $('#source-cards').innerHTML = emptyBox(error.message); });
}

/* ---------- 图表与导出 ---------- */

function drawLine(container, series, options = {}) {
  if (!container) return;
  const width = 760, height = options.height || 250;
  const pad = { left: 54, right: 18, top: 18, bottom: 34 };
  const points = series.flatMap(item => item.points).filter(point => Number.isFinite(Number(point.y)));
  if (!points.length) { container.innerHTML = emptyBox('暂无可绘制的数据'); return; }
  const n = Math.max(...series.map(item => item.points.length), 1);
  const values = points.map(point => Number(point.y));
  let minY = options.minY ?? Math.min(...values, 0);
  let maxY = options.maxY ?? Math.max(...values, 1);
  if (minY === maxY) { maxY += 1; minY -= 1; }
  const x = index => pad.left + (n <= 1 ? 0 : index / (n - 1)) * (width - pad.left - pad.right);
  const y = value => pad.top + (1 - (Number(value) - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const grid = [];
  for (let i = 0; i <= 4; i += 1) {
    const value = minY + (maxY - minY) * i / 4;
    grid.push(`<line x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}" stroke="#e5e9f0" stroke-width="1"/>`);
    grid.push(`<text x="${pad.left - 8}" y="${y(value) + 4}" fill="#76818f" font-size="10" text-anchor="end">${esc((options.yFormat || num)(value))}</text>`);
  }
  const lines = series.map(seriesItem => {
    const valid = seriesItem.points.map((point, index) => ({ point, index }))
      .filter(entry => Number.isFinite(Number(entry.point.y)));
    if (!valid.length) return '';
    const path = valid.map((entry, position) =>
      `${position ? 'L' : 'M'}${x(entry.index).toFixed(1)},${y(entry.point.y).toFixed(1)}`).join(' ');
    const dots = seriesItem.dots === false ? '' : valid.map(entry =>
      `<circle cx="${x(entry.index)}" cy="${y(entry.point.y)}" r="2.6" fill="${seriesItem.color}"><title>${esc(entry.point.label || '')}</title></circle>`).join('');
    return `<path d="${path}" fill="none" stroke="${seriesItem.color}" stroke-width="2"/>${dots}`;
  }).join('');
  const labels = options.xLabels || [];
  const step = Math.max(1, Math.ceil(labels.length / 7));
  const xLabels = labels.map((label, index) => index % step === 0
    ? `<text x="${x(index)}" y="${height - 10}" fill="#76818f" font-size="10" text-anchor="middle">${esc(label)}</text>` : '').join('');
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img"><g>${grid.join('')}</g>${lines}${xLabels}</svg>`;
}

function exportCsv(label, headers, rows) {
  if (!rows.length) { ctx.toast('当前筛选没有可导出的记录'); return; }
  const cell = value => {
    let text = value === null || value === undefined ? '' : String(value);
    if (/^[\s\u0000-\u001f]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const content = [headers.map(cell).join(','), ...rows.map(row => row.map(cell).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `数据看板-${label}-${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  ctx.toast(`已导出 ${rows.length} 行${label}数据，包含当前筛选口径`);
}

/* ---------- 入口 ---------- */

export async function renderStats(container, { api, toast, isCurrent, initialTab }) {
  if (initialTab) state.tab = initialTab;
  ctx = { api, toast, isCurrent };
  container.innerHTML = shell();
  bindShell();
  try {
    state.options = await api('/api/analysis/filters');
    renderFilterOptions();
    await refresh();
  } catch (error) {
    if (isCurrent()) $('#stats-body').innerHTML = `<div class="notice red">数据看板读取失败：${esc(error.message)}。请确认本地服务仍在运行。</div>`;
    toast(error.message, true);
  }
}
