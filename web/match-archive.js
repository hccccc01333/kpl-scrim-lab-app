/* 比赛档案 / 精选对局 / 训练纪录 —— 以「教练能不能一眼看懂」为准重写。
   规范：
   1. 任何数字都带单位与口径；没有数据就写「未记录」，不显示 0。
   2. 每个页面先说清楚「这一页在回答什么问题」。
   3. 缺口必须可见、可补：卡片直接给出还缺哪几项。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
const signed = (value, digits = 0) => {
  if (!Number.isFinite(Number(value)) || value === null) return '—';
  const v = Number(value);
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}`;
};
const RESULT = {win: '胜', loss: '负', draw: '平', unknown: '待确认'};
const SOURCE = {db: '本机记录', bundle: '录像数据包', sheet: '表格导入', capture: '截图候选'};

function clock(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return null;
  const s = Math.round(Number(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function parseClock(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  if (/^\d+:\d{1,2}$/.test(raw)) {
    const [m, s] = raw.split(':').map(Number);
    return m + s / 60;
  }
  if (/^\d+(\.\d+)?$/.test(raw)) return Number(raw);
  return NaN;
}

function weekday(date) {
  const d = new Date(`${date}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  return '周' + '日一二三四五六'[d.getDay()];
}

function resultTone(result) {
  return result === 'win' ? 'win' : result === 'loss' ? 'loss' : result === 'draw' ? 'draw' : 'unknown';
}

function scoreLine(match, teamName) {
  const s = match.scores || {};
  const own = match.ownCamp === 'blue' ? s.blue ?? s.left : match.ownCamp === 'red' ? s.red ?? s.right : s.left;
  const enemy = match.ownCamp === 'blue' ? s.red ?? s.right : match.ownCamp === 'red' ? s.blue ?? s.left : s.right;
  if (own == null || enemy == null) return null;
  return {own, enemy, teamName};
}

/* ---------------- 筛选条 ---------------- */

function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function buildQuery(state) {
  const p = new URLSearchParams();
  if (state.from) p.set('from', state.from);
  if (state.to) p.set('to', state.to);
  if (state.player) p.set('player', state.player);
  if (state.hero) p.set('hero', state.hero);
  if (state.opponent) p.set('opponent', state.opponent);
  if (state.result) p.set('result', state.result);
  p.set('source', state.sources.join(','));
  if (state.includePartial) p.set('includePartial', '1');
  if (localStorage.getItem('excludeSeeds') === '1') p.set('excludeSeeds', '1');
  return '?' + p.toString();
}

function activeChips(state, workspace) {
  const chips = [];
  if (state.range !== 'all' && state.range !== 'custom') {
    chips.push({key: 'range', label: {d7: '近 7 天', d30: '近 30 天', month: '本月'}[state.range]});
  }
  if (state.range === 'custom') {
    chips.push({key: 'range', label: `${state.from || '不限'} → ${state.to || '不限'}`});
  }
  if (state.opponent) chips.push({key: 'opponent', label: `对手：${state.opponent}`});
  if (state.result) chips.push({key: 'result', label: `赛果：${RESULT[state.result] || state.result}`});
  if (state.player) {
    const found = (workspace?.filters?.players || []).find(p => p.key === state.player);
    chips.push({key: 'player', label: `选手：${found?.label || state.player}`});
  }
  if (state.hero) chips.push({key: 'hero', label: `英雄：${state.hero}`});
  if (state.sources.includes('sheet')) chips.push({key: 'sources', label: '含表格导入'});
  if (!state.includePartial) chips.push({key: 'includePartial', label: '不含部分记录'});
  return chips;
}

function filterBar(state, workspace) {
  const opps = workspace?.filters?.opponents || [];
  const players = (workspace?.filters?.players || []).filter(p => p.bound).slice(0, 30);
  const heroes = workspace?.filters?.heroes || [];
  return `<section class="ar-filter">
    <div class="ar-filter-main">
      <div class="ar-search">
        <span aria-hidden="true">⌕</span>
        <input id="ar-q" type="search" placeholder="搜索对手、标题、日期（如 11-02 或 vs 狼队）" value="${esc(state.q)}" autocomplete="off">
      </div>
      <div class="ar-ranges" role="group" aria-label="时间范围">
        ${[['all', '全部'], ['d7', '近 7 天'], ['d30', '近 30 天'], ['month', '本月']].map(([key, label]) =>
          `<button class="ar-range${state.range === key ? ' active' : ''}" data-range="${key}">${label}</button>`).join('')}
      </div>
      <button class="ar-more${state.open ? ' active' : ''}" id="ar-toggle" aria-expanded="${state.open}">
        更多筛选${state.open ? ' ▴' : ' ▾'}
      </button>
    </div>
    <div class="ar-filter-more" ${state.open ? '' : 'hidden'}>
      <label class="ar-field"><span>开始日期</span><input id="ar-from" type="date" value="${esc(state.from)}"></label>
      <label class="ar-field"><span>结束日期</span><input id="ar-to" type="date" value="${esc(state.to)}"></label>
      <label class="ar-field"><span>对手</span>
        <select id="ar-opponent"><option value="">全部对手</option>${opps.map(o => `<option value="${esc(o)}"${o === state.opponent ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>
      </label>
      <label class="ar-field"><span>选手</span>
        <select id="ar-player"><option value="">全部选手</option>${players.map(p => `<option value="${esc(p.key)}"${p.key === state.player ? ' selected' : ''}>${esc(p.label)}</option>`).join('')}</select>
      </label>
      <label class="ar-field"><span>英雄</span>
        <select id="ar-hero"><option value="">全部英雄</option>${heroes.map(h => `<option value="${esc(h)}"${h === state.hero ? ' selected' : ''}>${esc(h)}</option>`).join('')}</select>
      </label>
      <label class="ar-field"><span>赛果</span>
        <select id="ar-result"><option value="">全部</option>${['win', 'loss', 'draw', 'unknown'].map(r => `<option value="${r}"${r === state.result ? ' selected' : ''}>${RESULT[r]}</option>`).join('')}</select>
      </label>
      <label class="ar-check"><input id="ar-sheet" type="checkbox"${state.sources.includes('sheet') ? ' checked' : ''}>含表格导入</label>
      <label class="ar-check"><input id="ar-partial" type="checkbox"${state.includePartial ? ' checked' : ''}>含部分记录</label>
    </div>
    <div class="ar-chips" id="ar-chips"></div>
  </section>`;
}

/* ---------------- 比赛卡片 ---------------- */

/* 未认领对手的托底显示名：对手字段为空、或对手名没有认领到战队档案时，
   标题显示「未认领N」。编号取自全量对手清单（与当前筛选无关，顺序稳定）；
   真实对手名不写回数据——筛选、补全档案、撤销都仍按原名工作，
   悬停「对手未认领」徽章可见原名。 */
function unclaimedCtx(workspace, teamName) {
  const registered = new Set([teamName, ...(workspace?.profile?.teams || []).map(team => team.name)]
    .filter(Boolean).map(name => String(name).trim().toLowerCase()));
  const named = (workspace?.filters?.opponents || [])
    .filter(name => !registered.has(String(name).trim().toLowerCase()));
  const labels = new Map(named.map((name, index) => [String(name).trim().toLowerCase(), `未认领${index + 1}`]));
  return {registered, labels, emptyLabel: `未认领${named.length + 1}`};
}

function opponentView(match, ctx) {
  const raw = String(match?.opponent || '').trim();
  if (!raw) return {text: ctx.emptyLabel, orphan: false, raw: ''};
  const key = raw.toLowerCase();
  if (ctx.registered.has(key)) return {text: raw, orphan: false, raw};
  return {text: ctx.labels.get(key) || raw, orphan: true, raw};
}

function metricCell(label, value, note, tone = '') {
  return `<div class="ar-metric ${tone}"><span>${esc(label)}</span><b>${value}</b><small>${esc(note)}</small></div>`;
}

function matchCard(match, teamName, options = {}) {
  const score = scoreLine(match, teamName);
  const tone = resultTone(match.result);
  const duration = clock(match.duration);
  const own = match.own || null;
  const enemy = match.enemy || null;
  const view = options.ctx ? opponentView(match, options.ctx) : null;
  const shown = view ? view.text : String(match.opponent || '').trim();
  const title = shown ? `${teamName} vs ${shown}` : (match.title || '未命名对局');
  const sub = [match.date ? `${match.date} ${weekday(match.date)}` : '日期未记录', match.session, match.mode]
    .filter(Boolean).join(' · ');
  const heroes = (match.heroes || []).slice(0, 5);
  const gaps = match.missing || [];
  const sources = (match.sources || []).map(s => SOURCE[s] || s).join(' + ');
  const reason = options.reasonFor ? options.reasonFor(match) : '';
  // 对手没有认领到战队档案（空名或旧名）时给出入口，避免删除战队后看不出比赛丢了对手。
  const orphan = view
    ? view.orphan
    : !!(match.opponent && options.registered
      && !options.registered.has(String(match.opponent).trim().toLowerCase()));
  const orphanTip = view && view.raw
    ? `原名「${view.raw}」没有认领到战队档案；去战队档案认领、统一名称或清空`
    : '这个对手名没有建档，去战队档案统一口径';
  return `<article class="ar-card ${tone}" data-key="${esc(match.key)}">
    <header class="ar-card-head">
      <div class="ar-card-title">
        <div class="ar-card-sub">
          <span>${esc(sub)}</span>
          ${match.isSeed ? '<span class="ar-flag">测试数据</span>' : ''}
          <span class="ar-src">${esc(sources)}</span>
          ${orphan ? `<a class="ar-flag ar-flag-team" href="#teams" title="${esc(orphanTip)}">对手未认领</a>` : ''}
        </div>
        <h3>${esc(title)}</h3>
      </div>
      <div class="ar-card-result">
        ${score ? `<b>${num(score.own)}<em>:</em>${num(score.enemy)}</b>` : '<b class="muted">比分未记录</b>'}
        <span class="ar-pill ${tone}">${RESULT[match.result] || '待确认'}</span>
      </div>
    </header>
    <div class="ar-metrics">
      ${metricCell('终局经济差', match.goldDiff == null ? '—' : signed(match.goldDiff),
        match.goldDiff == null ? '缺时间轴' : '本队 − 对手',
        match.goldDiff == null ? 'dim' : match.goldDiff >= 0 ? 'up' : 'down')}
      ${metricCell('时长', duration || '—', duration ? '回放可定位' : '影响分均换算', duration ? '' : 'dim')}
      ${metricCell('击杀', own ? `${num(own.kills)} : ${num(enemy?.kills)}` : '—',
        own ? `击杀差 ${signed(own.kills - enemy.kills)}` : '无十人数据', own ? '' : 'dim')}
      ${metricCell('团队 KDA', own ? num(own.kda, 2) : '—',
        own ? `${num(own.kills)}/${num(own.deaths)}/${num(own.assists)}` : '缺数据', own ? '' : 'dim')}
    </div>
    ${heroes.length ? `<div class="ar-lineup">${heroes.map(h => `<span>${esc(h)}</span>`).join('')}</div>` : ''}
    ${reason ? `<div class="ar-reason">${reason}</div>` : ''}
    <footer class="ar-card-foot">
      <div class="ar-gaps">${gaps.length
        ? `<span class="ar-gap-label">待补</span>${gaps.map(g => `<span class="ar-gap">${esc(g)}</span>`).join('')}`
        : '<span class="ar-complete">档案完整</span>'}</div>
      <div class="ar-card-actions">
        ${gaps.length ? `<button class="ar-btn ghost" data-fix="${esc(match.key)}">补全档案</button>` : ''}
        <a class="ar-btn" href="#match/${encodeURIComponent(match.key)}">查看对局</a>
      </div>
    </footer>
  </article>`;
}

/* ---------------- 档案体检 ---------------- */

function qualityBar(quality) {
  if (!quality) return '';
  const score = quality.score ?? 0;
  const tone = score >= 85 ? 'good' : score >= 60 ? 'mid' : 'bad';
  const pending = (quality.checks || []).filter(c => c.missing > 0)
    .sort((a, b) => b.missing - a.missing);
  return `<section class="ar-quality ${tone}">
    <div class="ar-quality-head">
      <div class="ar-quality-score"><b>${num(score)}<small>%</small></b><span>档案完整度</span></div>
      <div class="ar-quality-tags">
        ${pending.length
          ? pending.map(c => `<span class="ar-quality-tag">缺 ${esc(c.label)} <b>${c.missing}/${c.total}</b></span>`).join('')
          : '<span class="ar-quality-tag ok">基础档案齐全，可以直接进入复盘</span>'}
      </div>
      ${quality.seedMatches ? `<span class="ar-quality-seed">${num(quality.seedMatches)} 场为验证数据</span>` : ''}
    </div>
    <div class="ar-quality-track"><i style="width:${Math.max(2, Math.min(100, score))}%"></i></div>
    ${pending.length ? `<p class="ar-quality-hint">${esc(pending[0].hint)}</p>` : ''}
  </section>`;
}

/* ---------------- 主页面：比赛档案 ---------------- */

import {appendDepthSections} from '/assets/depth-section.js';

export async function renderMatches(container, {api, workspace, isCurrent, toast}) {
  const teamName = workspace?.overview?.teamName || '本队';
  const knownTeams = [...new Set([
    ...(workspace?.profile?.teams || []).map(team => team.name).filter(Boolean),
    ...(workspace?.filters?.opponents || []),
  ])].slice(0, 60);
  // 只有教练手动录入的战队算「已认领」；filters.opponents 包含所有出现过的对手名，不能当档案用。
  const ctx = unclaimedCtx(workspace, teamName);
  const state = {
    q: '', from: '', to: '', range: 'all', opponent: '', player: '', hero: '',
    result: '', sources: ['db', 'bundle'], includePartial: true, open: false,
  };
  let items = [];
  let total = 0;
  let summary = {};
  // 数据页面默认密排表格；卡片视图保留给需要看缺口的场景，选择记在本地
  let layout = localStorage.getItem('ar-layout') === 'cards' ? 'cards' : 'table';
  let serial = 0;
  let quality = workspace?.overview?.dataQuality || null;

  const load = async () => {
    const mine = ++serial;
    const data = await api('/api/studio/view/matches' + buildQuery(state) +
      '&limit=200&offset=0&q=' + encodeURIComponent(state.q));
    if (isCurrent && !isCurrent()) return null;
    if (mine !== serial) return null;
    items = data.matches || [];
    total = Number(data.total) || items.length;
    summary = data.summary || {};
    return data;
  };

  const first = await load();
  if (first === null) return;

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">MATCHES · 比赛档案</span>
        <h1>比赛档案</h1>
        <p>一局一条记录。先看赢在哪、缺什么，再点进去看十人明细。</p>
        <div class="page-facts">
          <span>${num(total)} 场记录</span>
          <span>${num(summary.wins)} 胜 ${num(summary.losses)} 负${summary.unknown ? ` ${num(summary.unknown)} 待确认` : ''}</span>
          <span>${num(summary.complete)} 场十人齐全</span>
          ${quality?.seedMatches ? `<span class="fact-warn">含 ${quality.seedMatches} 场验证数据</span>` : ''}
        </div>
      </div>
      <div class="heading-actions">
        ${quality && (quality.checks || []).some(c => c.missing > 0) ? '<button class="button" id="ar-next-gap">补下一场待补</button>' : ''}
        <button class="button" data-print>打印 / PDF</button>
        <a class="button" href="#teams">战队档案</a>
        <a class="button primary" href="#capture">导入比赛 →</a>
      </div>
    </div>
    <div id="ar-quality">${qualityBar(quality)}</div>
    <div id="ar-filter">${filterBar(state, workspace)}</div>
    <div class="ar-toolbar">
      <span id="ar-count">${num(total)} 场 · 显示 ${num(items.length)}</span>
      <div class="ar-layout" role="group" aria-label="视图切换">
        <button data-layout="cards" class="${layout === 'cards' ? 'active' : ''}">卡片</button>
        <button data-layout="table" class="${layout === 'table' ? 'active' : ''}">表格</button>
      </div>
    </div>
    <div id="ar-body"></div>
  `;

  const paint = () => {
    const chips = activeChips(state, workspace);
    const chipBox = container.querySelector('#ar-chips');
    if (chipBox) {
      chipBox.innerHTML = chips.length
        ? chips.map(c => `<button class="ar-chip" data-drop="${c.key}">${esc(c.label)}<i aria-hidden="true">×</i></button>`).join('')
          + `<button class="ar-chip clear" data-drop="all">清空条件</button>`
        : '';
    }
    const body = container.querySelector('#ar-body');
    if (!body) return;
    if (!items.length) {
      body.innerHTML = `<div class="ar-empty">
        <strong>没有符合条件的对局</strong>
        <p>放宽时间范围或清空筛选条件；如果确实还没导入，先完成一次采集。</p>
        <a class="button" href="#matches">清空筛选</a>
        <a class="button primary" href="#capture">导入比赛</a>
      </div>`;
      return;
    }
    if (layout === 'table') {
      body.innerHTML = matchesTable(items, teamName, ctx);
      return;
    }
    body.innerHTML = `<div class="ar-grid">${items.map(m => matchCard(m, teamName, {ctx})).join('')}</div>`;
  };

  const refresh = async () => {
    const data = await load();
    if (data === null) return;
    container.querySelector('#ar-count').textContent = `${num(total)} 场 · 显示 ${num(items.length)}`;
    const facts = container.querySelector('.page-facts');
    if (facts) facts.innerHTML = `<span>${num(total)} 场记录</span><span>${num(summary.wins)} 胜 ${num(summary.losses)} 负${summary.unknown ? ` ${num(summary.unknown)} 待确认` : ''}</span><span>${num(summary.complete)} 场十人齐全</span>${quality?.seedMatches ? `<span class="fact-warn">含 ${quality.seedMatches} 场验证数据</span>` : ''}`;
    paint();
  };

  const setRange = (key) => {
    state.range = key;
    if (key === 'all') { state.from = ''; state.to = ''; }
    if (key === 'd7') { state.from = daysAgo(7); state.to = today(); }
    if (key === 'd30') { state.from = daysAgo(30); state.to = today(); }
    if (key === 'month') { state.from = today().slice(0, 8) + '01'; state.to = today(); }
    container.querySelectorAll('.ar-range').forEach(btn => btn.classList.toggle('active', btn.dataset.range === key));
    refresh();
  };

  container.addEventListener('input', (event) => {
    if (event.target.id === 'ar-q') {
      state.q = event.target.value;
      clearTimeout(container._arTimer);
      container._arTimer = setTimeout(refresh, 260);
    }
  });

  container.addEventListener('change', (event) => {
    const id = event.target.id;
    if (id === 'ar-from') { state.from = event.target.value; state.range = 'custom'; refresh(); }
    if (id === 'ar-to') { state.to = event.target.value; state.range = 'custom'; refresh(); }
    if (id === 'ar-opponent') { state.opponent = event.target.value; refresh(); }
    if (id === 'ar-player') { state.player = event.target.value; refresh(); }
    if (id === 'ar-hero') { state.hero = event.target.value; refresh(); }
    if (id === 'ar-result') { state.result = event.target.value; refresh(); }
    if (id === 'ar-sheet') {
      state.sources = event.target.checked ? ['db', 'bundle', 'sheet'] : ['db', 'bundle'];
      refresh();
    }
    if (id === 'ar-partial') { state.includePartial = event.target.checked; refresh(); }
  });

  container.addEventListener('click', async (event) => {
    const range = event.target.closest('[data-range]');
    if (range) return setRange(range.dataset.range);

    if (event.target.closest('#ar-toggle')) {
      state.open = !state.open;
      const more = container.querySelector('.ar-filter-more');
      const btn = container.querySelector('#ar-toggle');
      if (more) more.hidden = !state.open;
      if (btn) { btn.classList.toggle('active', state.open); btn.textContent = state.open ? '更多筛选 ▴' : '更多筛选 ▾'; }
      return;
    }

    const layoutBtn = event.target.closest('[data-layout]');
    if (layoutBtn) {
      layout = layoutBtn.dataset.layout;
      localStorage.setItem('ar-layout', layout);
      container.querySelectorAll('[data-layout]').forEach(b => b.classList.toggle('active', b.dataset.layout === layout));
      paint();
      return;
    }

    const drop = event.target.closest('[data-drop]');
    if (drop) {
      const key = drop.dataset.drop;
      if (key === 'all' || key === 'range') { state.range = 'all'; state.from = ''; state.to = ''; }
      if (key === 'opponent') state.opponent = '';
      if (key === 'result') state.result = '';
      if (key === 'player') state.player = '';
      if (key === 'hero') state.hero = '';
      if (key === 'sources') state.sources = ['db', 'bundle'];
      if (key === 'includePartial') state.includePartial = true;
      container.querySelector('#ar-filter').innerHTML = filterBar(state, workspace);
      await refresh();
      return;
    }

    if (event.target.closest('#ar-next-gap')) {
      const next = items.find(m => (m.missing || []).length);
      if (!next) return toast?.('所有对局的档案都补齐了');
      openFixDialog(next, teamName, async () => {
        const data = await api('/api/studio/workspace');
        if (isCurrent && !isCurrent()) return;
        quality = data?.overview?.dataQuality || quality;
        const box = container.querySelector('#ar-quality');
        if (box) box.innerHTML = qualityBar(quality);
        await refresh();
        toast?.('档案已补全');
      }, knownTeams);
      return;
    }

    const fix = event.target.closest('[data-fix]');
    if (fix) {
      const match = items.find(m => m.key === fix.dataset.fix);
      if (match) openFixDialog(match, teamName, async (savedKey) => {
        const data = await api('/api/studio/workspace');
        if (isCurrent && !isCurrent()) return;
        quality = data?.overview?.dataQuality || quality;
        const box = container.querySelector('#ar-quality');
        if (box) box.innerHTML = qualityBar(quality);
        await refresh();
        toast?.('档案已补全');
        const next = items.find(m => (m.missing || []).length && m.key !== savedKey);
        if (next) setTimeout(() => {
          const el = container.querySelector(`[data-key="${CSS.escape(next.key)}"]`);
          if (el) { el.scrollIntoView({block: 'center', behavior: 'smooth'}); el.classList.add('flash'); }
        }, 120);
      }, knownTeams);
    }
  });

  paint();
  appendDepthSections(container, [
    {id: 'time_economy', note: '逐局经济差过程（含掉点窗口）'},
    {id: 'time_events', note: '逐局事件密度'},
    {id: 'time_kill_rhythm', note: '逐局击杀节奏'},
  ], {api, isCurrent});
}

function matchesTable(items, teamName, ctx = null) {
  const rows = items.map(m => {
    const score = scoreLine(m, teamName);
    const view = ctx ? opponentView(m, ctx) : null;
    const shown = view ? view.text : String(m.opponent || '').trim();
    return `<tr class="clickable" data-open="${esc(m.key)}">
      <td>${esc(m.date || '—')}</td>
      <td class="main-cell">${esc(shown || m.title || '未命名')}</td>
      <td>${score ? `${num(score.own)}:${num(score.enemy)}` : '—'}</td>
      <td>${esc(RESULT[m.result] || '待确认')}</td>
      <td class="num">${clock(m.duration) || '—'}</td>
      <td class="num">${m.goldDiff == null ? '—' : signed(m.goldDiff)}</td>
      <td>${(m.missing || []).length ? esc(m.missing.join('、')) : '<span class="muted">完整</span>'}</td>
    </tr>`;
  }).join('');
  return `<div class="table-scroll"><table class="data-table ar-table">
    <thead><tr><th>日期</th><th>对手 / 标题</th><th>比分</th><th>赛果</th><th>时长</th><th>终局经济差</th><th>缺失项</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

/* ---------------- 补全档案 ---------------- */

function openFixDialog(match, teamName, onSaved, teamNames = []) {
  const dialog = document.querySelector('#detail-dialog');
  const title = document.querySelector('#detail-title');
  const body = document.querySelector('#detail-body');
  if (!dialog || !body) return;
  title.textContent = '补全档案';
  const duration = match.duration ? clock(match.duration) : '';
  body.innerHTML = `<div class="ar-fix">
    <p class="ar-fix-lead">这一局还缺：<b>${(match.missing || []).join(' · ') || '无'}</b>。补录只写在本机，不改原始数据包。</p>
    <label class="ar-fix-field"><span>对手战队</span>
      <input id="fix-opponent" maxlength="50" list="fix-team-options" placeholder="如：成都AG超玩会" value="${esc(match.opponent || '')}">
      <datalist id="fix-team-options">${teamNames.map(name => `<option value="${esc(name)}"></option>`).join('')}</datalist>
      ${teamNames.length ? '<small class="ar-fix-hint">从已建档的战队里选，或直接输入新队名；孤立队名可在「战队档案」里统一</small>' : ''}
    </label>
    <div class="ar-fix-row">
      <label class="ar-fix-field"><span>比赛时长（分:秒）</span>
        <input id="fix-duration" placeholder="11:33" value="${esc(duration)}"></label>
      <label class="ar-fix-field"><span>训练组 / 阶段</span>
        <input id="fix-session" maxlength="40" placeholder="如：11月集训 Day1" value="${esc(match.session || '')}"></label>
    </div>
    <label class="ar-fix-field"><span>赛果</span>
      <select id="fix-result">
        <option value="">保持原判（${RESULT[match.result] || '待确认'}）</option>
        ${['win', 'loss', 'draw'].map(r => `<option value="${r}">${RESULT[r]}</option>`).join('')}
      </select></label>
    <label class="ar-fix-field"><span>备注</span>
      <textarea id="fix-note" rows="2" maxlength="500" placeholder="选填：BP 失误、阵容实验等">${esc(match.note || '')}</textarea></label>
    <div class="ar-fix-actions">
      <button class="button" id="fix-cancel">取消</button>
      <button class="button primary" id="fix-save">保存</button>
    </div>
  </div>`;
  dialog.showModal();
  const close = () => dialog.close();
  body.querySelector('#fix-cancel').onclick = close;
  body.querySelector('#fix-save').onclick = async () => {
    const btn = body.querySelector('#fix-save');
    btn.disabled = true;
    const payload = {};
    const opponent = body.querySelector('#fix-opponent').value.trim();
    const session = body.querySelector('#fix-session').value.trim();
    const note = body.querySelector('#fix-note').value.trim();
    const result = body.querySelector('#fix-result').value;
    const minutes = parseClock(body.querySelector('#fix-duration').value);
    if (Number.isNaN(minutes)) {
      btn.disabled = false;
      return alert('时长请填 11:33 这样的格式，或直接填分钟数');
    }
    payload.opponent = opponent;
    payload.session = session;
    payload.note = note;
    if (minutes != null) payload.duration = minutes;
    if (result) payload.result = result;
    try {
      await fetch(`/api/studio/match-meta/${encodeURIComponent(match.key)}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
      }).then(async r => { if (!r.ok) throw Error((await r.json()).detail || '保存失败'); });
      close();
      onSaved?.(match.key);
    } catch (error) {
      console.error(error);
      alert(error.message);
    } finally {
      btn.disabled = false;
    }
  };
}

/* ---------------- 精选对局 ---------------- */

const RULES = [
  {key: 'comeback', label: '落后翻盘', detail: '10 分钟经济落后 ≥ 2,000，最终获胜'},
  {key: 'blown', label: '领先被翻', detail: '10 分钟经济领先 ≥ 2,000，最终落败'},
  {key: 'close', label: '经济接近', detail: '终局经济差绝对值 < 3,000'},
  {key: 'swing', label: '经济反复', detail: '经济差正负翻转 ≥ 2 次'},
  {key: 'bloody', label: '高击杀', detail: '双方总击杀 / 分钟 ≥ 本组 P75'},
];

function evaluateFeatured(match, killThreshold) {
  const reasons = [];
  const lead = match.leadAt10;
  if (lead === false && match.win === true && Number(match.diffAt?.['600']) <= -2000) reasons.push('comeback');
  if (lead === true && match.win === false) reasons.push('blown');
  if (match.finalDiff != null && Math.abs(match.finalDiff) < 3000) reasons.push('close');
  if (Number(match.signFlips) >= 2) reasons.push('swing');
  const rate = match.killsPerMinute;
  if (killThreshold != null && rate !== null && rate !== undefined && rate !== ''
      && Number.isFinite(Number(rate)) && Number(rate) >= killThreshold) reasons.push('bloody');
  return reasons;
}

export async function renderFeatured(container, {api, workspace, isCurrent, query}) {
  const [data, matchesView, catalog] = await Promise.all([
    api('/api/studio/view/process' + query()),
    api('/api/studio/view/matches' + query()),
    api('/api/catalog').catch(() => ({entries: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const all = data.matches || [];
  // process 视图只有过程指标（finalDiff / signFlips / points…），
  // 卡片要的比分、十人 KDA、经济差、阵容在 matches 视图里，按 key 关联。
  const archive = new Map((matchesView.matches || []).map(match => [match.key, match]));
  const teamName = workspace?.overview?.teamName || '本队';
  const killRates = all.map(match => match.killsPerMinute)
    // Number(null) === 0，必须显式排除，否则「没采集」会被当成有效 0
    .filter(value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)))
    .map(Number).sort((a, b) => a - b);
  // 固定 1.2 会让本样本 11/11 全命中，规则失去区分度；改用本组 P75 自适应阈值。
  const killRateAvailable = killRates.length >= 4;
  const killThreshold = killRateAvailable
    ? killRates[Math.min(killRates.length - 1, Math.ceil(killRates.length * 0.75) - 1)]
    : null;
  const fallbackCount = all.filter(match => match.killsPerMinuteSource === 'final-score').length;
  const scored = all.map(match => ({match, reasons: evaluateFeatured(match, killThreshold)}))
    .sort((a, b) => b.reasons.length - a.reasons.length);
  const featured = scored.filter(item => item.reasons.length);
  const undecidable = Math.max(0, (workspace?.overview?.matches || 0) - all.length);
  const ruleDetail = rule => rule.key === 'bloody' && killThreshold != null
    ? `双方总击杀 / 分钟 ≥ 本组 P75（${killThreshold.toFixed(2)}）`
    : rule.detail;
  const ruleCount = RULES.map(rule => ({
    rule, hits: scored.filter(item => item.reasons.includes(rule.key)).length,
    unavailable: rule.key === 'bloody' && !killRateAvailable,
  }));

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">FEATURED · 精选对局</span>
        <h1>值得回看的局</h1>
        <p>不是「打得好的局」，是「有信息量的局」：翻盘、被翻、胶着、经济反复、高击杀。</p>
        <div class="page-facts">
          <span>${num(all.length)} 场可判</span>
          <span>${num(featured.length)} 场入选</span>
          <span>判定门槛见下方规则表</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#matches">比赛档案</a>
        <button class="button" data-print>打印 / PDF</button>
      </div>
    </div>
    <section class="ar-rules">
      <div class="ar-rules-head">
        <div><h2>判定规则</h2><p>五条独立规则，命中任意一条即入选；命中越多排越前。</p></div>
      </div>
      <div class="ar-rule-grid">
        ${ruleCount.map(({rule, hits, unavailable}) => `<div class="ar-rule${hits ? ' hit' : ''}${unavailable ? ' unavailable' : ''}">
          <div class="ar-rule-top"><strong>${esc(rule.label)}</strong><b>${unavailable ? '—' : num(hits)}${unavailable ? '' : '<small>场</small>'}</b></div>
          <p>${esc(ruleDetail(rule))}${unavailable ? '<em> · 击杀率样本不足，本规则暂不可判定</em>' : ''}</p>
          <span class="ar-rule-bar"><i style="width:${all.length && !unavailable ? Math.round(hits / all.length * 100) : 0}%"></i></span>
        </div>`).join('')}
      </div>
      <p class="ar-rules-note">${all.length
        ? (undecidable
            ? `当前只有 ${num(all.length)} 场具备「时间轴 + 时长」，其余 ${num(undecidable)} 场因缺时长或时间轴无法判定——这是数据缺口，不是没亮点。`
            : `当前 ${num(all.length)} 场全部具备「时间轴 + 时长」，规则判定覆盖完整。`)
          + (killRateAvailable
              ? `「高击杀」按终局双方总击杀 ÷ 结算时长计算（${num(fallbackCount)} 场为终局比分口径，逐局核对与官方 killInfo 逐次英雄击杀总数一致），阈值取本组 P75 ${killThreshold.toFixed(2)}，固定 1.2 会让全部对局命中；带毫秒时间戳的「谁在几秒击杀谁」见深度分析 → 击杀。`
              : '「高击杀」需要至少 4 场有击杀率的样本，本规则暂不参与判定。')
        : '还没有可判定的对局：需要「经济时间轴 + 时长」同时具备。'}</p>
    </section>
    ${featured.length
      ? `<div class="ar-grid">${featured.map(({match, reasons}) => {
          const full = archive.get(match.key) || {};
          return matchCard({
            ...match, ...full,
            goldDiff: full.goldDiff ?? match.finalDiff ?? null,
            missing: full.missing || [],
            heroes: full.heroes || [],
          }, teamName,
          {ctx: unclaimedCtx(workspace, teamName), reasonFor: () => `<span class="ar-reason-label">入选理由</span>${reasons.map(k => `<b>${esc(RULES.find(r => r.key === k)?.label || k)}</b>`).join('')}`});
        }).join('')}</div>`
      : `<div class="ar-empty"><strong>当前没有触发任何规则的对局</strong>
          <p>${all.length ? '这几场都是「领先并且赢下、经济差明显」的常规局，回看优先级不高。' : '先补齐时长与时间轴，再回来看。'}</p>
          <a class="button" href="#matches">去补全档案</a></div>`}
  `;
}

/* ---------------- 训练纪录 ---------------- */

export async function renderRecords(container, {api, workspace, isCurrent, query}) {
  const data = await api('/api/studio/view/process' + query());
  if (isCurrent && !isCurrent()) return;
  const all = data.matches || [];
  const recordCtx = unclaimedCtx(workspace, workspace?.overview?.teamName || '本队');

  const byDuration = all.filter(m => m.duration || m.observedEnd)
    .sort((a, b) => (b.duration || b.observedEnd * 60) - (a.duration || a.observedEnd * 60));
  const byDiff = all.filter(m => m.finalDiff != null).sort((a, b) => b.finalDiff - a.finalDiff);
  const closest = all.filter(m => m.finalDiff != null).sort((a, b) => Math.abs(a.finalDiff) - Math.abs(b.finalDiff));
  const swings = all.filter(m => m.signFlips != null).sort((a, b) => b.signFlips - a.signFlips);
  const avgDiff = byDiff.length ? byDiff.reduce((s, m) => s + m.finalDiff, 0) / byDiff.length : null;

  const card = (label, value, unit, match, note, compare) => `<article class="ar-record">
      <span class="ar-record-label">${esc(label)}</span>
      <b class="ar-record-value">${value}<small>${esc(unit)}</small></b>
      <span class="ar-record-note">${note}</span>
      ${compare ? `<span class="ar-record-compare">${compare}</span>` : ''}
      ${match ? `<a class="ar-record-link" href="#match/${encodeURIComponent(match.key)}">${esc('vs ' + opponentView(match, recordCtx).text)} →</a>` : ''}
    </article>`;

  const longest = byDuration[0], shortest = byDuration[byDuration.length - 1];
  const best = byDiff[0], worst = byDiff[byDiff.length - 1];
  const tight = closest[0], wild = swings[0];
  const seconds = m => (m?.duration ? Number(m.duration) : m?.observedEnd ? Math.round(m.observedEnd) : null);
  const sameExtreme = best && tight && best.key === tight.key;

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">RECORDS · 训练纪录</span>
        <h1>训练纪录</h1>
        <p>队史极值 + 参照值。每项都标注是哪一场、比队均高多少，避免「最长等于最短」这种空纪录。</p>
        <div class="page-facts">
          <span>${num(all.length)} 场可计算</span>
          <span>队均经济差 ${avgDiff == null ? '—' : signed(avgDiff)}</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#matches">比赛档案</a>
        <button class="button" data-print>打印 / PDF</button>
      </div>
    </div>
    ${!all.length
      ? `<div class="ar-empty"><strong>还没有可计算的纪录</strong><p>纪录需要「时长 + 经济时间轴」，先去补全档案。</p><a class="button" href="#matches">去补全</a></div>`
      : `<div class="ar-record-grid">
        ${longest && shortest && longest.key !== shortest.key
          ? card('最长对局', clock(seconds(longest)) || '—', '', longest, '按比赛时长',
              `最短 ${clock(seconds(shortest))} · 相差 ${Math.round((seconds(longest) - seconds(shortest)) / 60)} 分`)
          : longest ? card('对局时长', clock(seconds(longest)) || '—', '', longest, '只有 1 场可计算，暂不设长短纪录', '') : ''}
        ${best ? card('最大终局经济差', signed(best.finalDiff), '', best, '本队 − 对手', avgDiff != null ? `队均 ${signed(avgDiff)} · 高出 ${signed(best.finalDiff - avgDiff)}` : '') : ''}
        ${worst && worst.key !== best?.key ? card('最小终局经济差', signed(worst.finalDiff), '', worst, '本队 − 对手', avgDiff != null ? `队均 ${signed(avgDiff)} · 低于 ${signed(worst.finalDiff - avgDiff)}` : '') : ''}
        ${tight && !sameExtreme ? card('最胶着', signed(tight.finalDiff), '', tight, '终局经济差绝对值最小', byDiff.length > 1 ? `与最悬殊相差 ${num(Math.abs((best?.finalDiff ?? 0) - tight.finalDiff))}` : '') : ''}
        ${wild && wild.signFlips ? card('最反复', num(wild.signFlips), '次', wild, '经济差正负翻转次数', '翻转越多，越值得看节奏控制') : ''}
      </div>
      <p class="ar-rules-note">没有参与的纪录（例如「总击杀最高」）已移除：它与胜负、经济差的解释力重复，且容易被单局爆发误导。</p>`}
  `;
  appendDepthSections(container, [
    {id: 'time_cross_match', note: '跨局训练节奏'},
  ], {api, isCurrent});
}
