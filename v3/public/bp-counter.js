/* BP 抗针对（P1-6）：先看对手常禁什么，再看我方被禁后还剩什么。
   数据：/api/decision/bp（营地终局面板禁选 + 我方分路/选手英雄池）；
   本页只做赛前补练与阵容准备建议，不推断英雄强度、不把少量胜率当结论。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const BP_URL = API_BASE + '/api/decision/bp';
const CATALOG_URL = API_BASE + '/api/decision/catalog';
const FETCH_TIMEOUT = 8000;

export function createBpCounter({ esc, fmt, pct, icon }) {
  const state = { box: null, controller: null, opponent: '', data: null, catalog: null, error: '' };

  const listOf = (value) => (Array.isArray(value) ? value : []);
  const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
  /* 工作台全站的数据明细表已被产品下线；这里用决策页自己的轻量表格，不复用全局 table()。 */
  const tableHtml = (head, rows) => `<div class="bpc-table-wrap"><table class="bpc-table">
    <thead><tr>${head.map((cell) => `<th>${esc(cell)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
  const query = () => (state.opponent ? `?opponent=${encodeURIComponent(state.opponent)}` : '');

  function metrics(items) {
    return `<div class="bpc-metrics">${items.map((item) => `<div class="bpc-metric">
      <span>${esc(item.label)}</span><b>${item.value}</b><small>${esc(item.note || '')}</small></div>`).join('')}</div>`;
  }

  function opponentSelect() {
    const opponents = listOf(state.catalog && state.catalog.opponents);
    const options = opponents.map((item) => `<option value="${esc(item.id)}"${item.id === state.opponent ? ' selected' : ''}>${esc(item.name || item.id)}（回放 ${fmt(item.replayGames)} 局）</option>`).join('');
    return `<label class="bpc-field"><span>研究对手</span>
      <select data-bpc-opponent aria-label="选择对手">
        <option value="">全部对手（本批汇总）</option>${options}
      </select></label>
      <span class="bpc-hint">每名对手目前多为 1 局回放，对手禁选只做单场观察，不当稳定套路。</span>`;
  }

  function banList(bans) {
    const rows = listOf(bans).slice(0, 8);
    if (!rows.length) return '<p class="bpc-empty-line">当前范围没有可用的禁选记录。</p>';
    const max = Math.max(1, ...rows.map((row) => num(row.games) || 0));
    return `<div class="bpc-ban-list">${rows.map((row, index) => `<div class="bpc-ban-row">
      <span class="bpc-rank">${index + 1}</span>
      <b>${esc(row.hero)}</b>
      <i><em style="width:${Math.round((num(row.games) || 0) / max * 100)}%"></em></i>
      <span>${fmt(row.games)} 局 · ${pct(row.share)}</span>
      <small>${esc(listOf(row.opponents).join(' / ') || '对手待命名')}</small>
    </div>`).join('')}</div>`;
  }

  function laneCards(lanes) {
    const rows = listOf(lanes);
    if (!rows.length) return '<p class="bpc-empty-line">当前范围没有分路英雄池。</p>';
    return `<div class="bpc-lane-grid">${rows.map((lane) => {
      const heroes = listOf(lane.heroes).slice(0, 4).map((item) => `<span class="bpc-hero" title="出场 ${fmt(item.games)} 局 · 胜率 ${pct(item.winRate)}">${esc(item.hero)}<small>${fmt(item.games)}</small></span>`).join('');
      const banned = listOf(lane.bannedHits).length ? `被常禁：${listOf(lane.bannedHits).map((hero) => esc(hero)).join(' / ')}` : '常用英雄暂未被对手重点禁';
      return `<article class="bpc-lane${lane.thin ? ' is-thin' : ''}">
        <div class="bpc-lane-head"><b>${esc(lane.lane)}</b><span>${fmt(lane.games)} 局 · ${fmt(lane.players)} 人</span>
          ${lane.thin ? '<em class="bpc-badge">可用池偏薄</em>' : ''}</div>
        <div class="bpc-heroes">${heroes || '<span class="bpc-empty-line">无英雄样本</span>'}</div>
        <p>${banned}</p>
        <div class="bpc-lane-foot"><span>被禁后剩余 ${fmt(lane.poolDepth)} 个</span><span>建议：${esc(listOf(lane.recommendations).join(' / ') || '—')}</span></div>
      </article>`;
    }).join('')}</div>`;
  }

  function playerTable(players) {
    const rows = listOf(players);
    if (!rows.length) return '<p class="bpc-empty-line">本批没有 ≥3 局的稳定选手样本；按分路上面的英雄池看。</p>';
    return tableHtml(['选手', '分路', '场次', '常用英雄', '被常禁命中', '被禁后剩余', '补练建议'], rows.map((item) => [
      esc(item.name), esc(item.lane), fmt(item.games),
      esc(listOf(item.heroes).slice(0, 3).map((hero) => hero.hero).join(' · ')),
      esc(listOf(item.bannedHits).join(' · ') || '—'),
      `${fmt(item.poolDepth)} 个${item.thin ? '（偏薄）' : ''}`,
      esc(listOf(item.recommendations).join(' · ') || '—'),
    ]));
  }

  function weakTable(weak) {
    const rows = listOf(weak);
    if (!rows.length) return '';
    return `<h3 class="bpc-subtitle">我方与对手 ban 位重合的英雄</h3>` +
      tableHtml(['英雄', '我方出场', '被禁局数', '被禁占比', '常禁对手'], rows.map((item) => [
        esc(item.hero), fmt(item.ownGames), fmt(item.bannedGames), pct(item.share),
        esc(listOf(item.opponents).join(' / ') || '—'),
      ]));
  }

  function renderBody(data) {
    const coverage = data.coverage || {};
    const suggestions = listOf(data.team && data.team.suggestions);
    const chips = metrics([
      { label: '终局面板', value: `${fmt(coverage.panelGames)} 局`, note: '含 BP 禁选' },
      { label: '可分析禁选', value: `${fmt(coverage.gamesWithBans)} 局`, note: '双方 ban 记录' },
      { label: '稳定选手样本', value: `${fmt(coverage.players)} 人`, note: `另有 ${fmt(coverage.rotatedPlayers)} 个轮换昵称未单列` },
      { label: '对手', value: `${fmt(coverage.opponents)} 个`, note: '按对面五人签名' },
    ]);
    const suggestionList = suggestions.length
      ? `<div class="bpc-suggestions"><b>本周补练建议</b><ul>${suggestions.map((text) => `<li>${esc(text)}</li>`).join('')}</ul></div>`
      : '<div class="bpc-suggestions"><b>本周补练建议</b><p>当前没有触发补练条件；去 BP 页看完整英雄池与对位。</p></div>';
    return `${chips}${suggestionList}
      <div class="bpc-grid">
        <section class="bpc-panel"><div class="bpc-panel-head"><h3>对手常禁</h3><span>按被禁局数排序</span></div>${banList(data.bans && data.bans.overall)}</section>
        <section class="bpc-panel"><div class="bpc-panel-head"><h3>我方分路可用池</h3><span>被对手常禁命中后</span></div>${laneCards(data.lanes)}</section>
      </div>
      <section class="bpc-panel"><div class="bpc-panel-head"><h3>稳定选手样本</h3><span>≥3 局；营地昵称，未绑定名单时会提示</span></div>${playerTable(data.players)}</section>
      ${weakTable(data.team && data.team.weakHeroes)}
      <ul class="bpc-caveats">${listOf(data.caveats).map((text) => `<li>${esc(text)}</li>`).join('')}</ul>`;
  }

  function shell(content) {
    return `<div class="page bpc-page">
      <div class="page-intro bpc-intro">
        <div class="bpc-hero-copy">
          <span class="bpc-kicker">BP LAB <i></i> 抗针对</span>
          <h1>BP 抗针对</h1>
          <p>先看对手常禁什么，再看我方被禁后还剩什么；只基于本批终局面板，不推断英雄强度。</p>
        </div>
        <div class="intro-actions"><button class="control" type="button" data-bpc-refresh>${icon('refresh')} 刷新数据</button></div>
      </div>
      <div class="bpc-toolbar">${state.catalog ? opponentSelect() : ''}</div>
      <div data-bpc-body>${content}</div>
    </div>`;
  }

  async function request(url, signal) {
    const response = await fetch(url, { cache: 'no-store', signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function load(controller) {
    const box = state.box;
    if (!box) return;
    box.setAttribute('aria-busy', 'true');
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
    try {
      const [data, catalog] = await Promise.all([
        request(BP_URL + query(), controller.signal),
        request(CATALOG_URL, controller.signal).catch(() => null),
      ]);
      if (!state.box || controller.signal.aborted) return;
      state.data = data;
      state.catalog = catalog;
      state.error = '';
      box.innerHTML = shell(data && data.available === false
        ? `<div class="empty">${esc(data.reason || '当前范围没有可分析的 BP 数据。')}</div>`
        : renderBody(data));
    } catch (error) {
      if (controller.signal.aborted) return;
      state.error = error.message || '读取失败';
      box.innerHTML = shell(`<div class="empty">BP 抗针对暂时读不到（${esc(state.error)}）。<button class="control" type="button" data-bpc-refresh>重试</button></div>`);
    } finally {
      clearTimeout(timer);
      box.setAttribute('aria-busy', 'false');
    }
  }

  function bind(box) {
    if (!box || box.dataset.bpcBound === '1') return;
    box.dataset.bpcBound = '1';
    box.addEventListener('change', (event) => {
      const select = event.target.closest('[data-bpc-opponent]');
      if (!select) return;
      state.opponent = select.value;
      state.controller?.abort();
      state.controller = new AbortController();
      void load(state.controller);
    });
    box.addEventListener('click', (event) => {
      if (!event.target.closest('[data-bpc-refresh]')) return;
      event.preventDefault();
      state.controller?.abort();
      state.controller = new AbortController();
      void load(state.controller);
    });
  }

  function mount(box) {
    if (!box) return;
    state.box = box;
    state.controller?.abort();
    state.controller = new AbortController();
    box.innerHTML = shell('<div class="loading">正在汇总 BP 禁选与英雄池…</div>');
    bind(box);
    void load(state.controller);
  }

  return { mount, render: (data) => renderBody(data) };
}
