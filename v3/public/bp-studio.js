/* BP 工作台（2026-11 重做 · 图表版）
 *
 * 一条页面回答四个问题：
 *   01 版本里谁值得先拿 → 02 自选组合有多强 → 03 目标被拿走时 KPL / 我们各怎么应对
 *   → 04 对手的 Ban 在想什么 → 05 体系与异动 → 06 赛前方案。
 *
 * 数据全部来自 `/api/v3/bp-studio`（页面模型 + 目录 + 对手情报）和
 * `/api/v3/bp-studio/target`、`/combo`（目标下钻）。前端只做排版与交互，
 * 不重算胜率、不推断缺失手序；每条结论都带样本与口径。
 *
 * 可视化原则（教练 2026-11-16 明确要求）：不用细长横条。所有占比用气泡
 * 散点、区间点图、哑铃对比、Ban 位热力图/同心环、体系雷达、窗口斜率图。
 *
 * 筛选状态存 localStorage：刷新页面回来还是同一边、同一窗口。
 */

import {createBpViz} from './bps-viz.js?v=20261118a8';

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const SECTION_LIST = [
  ['heroes', '01', '英雄优先级', '版本里哪些英雄值得先拿？', '气泡 = Pick 次数 · 颜色 = 分路'],
  ['combos', '02', '组合强度', '自选组合到底多强，联盟哪些组合在赢？', '同队同局，不是因果协同'],
  ['break', '03', '战队如何破解', '目标被对面拿走，KPL 怎么应对，我们怎么应对？', 'KPL 先验 × 本队训练赛'],
  ['opponent', '04', '对手 BP 情报', '他的 Ban 在想什么，第一手之后他会怎么走？', 'Ban 意图 / 手序 / 条件回应'],
  ['types', '05', '类型与手序', '他第一手 Ban / 选的是什么类型？放到 BO 和时间里还成立吗？', '类型 × 手序 × 赛制 × 核数'],
  ['systems', '06', '体系与异动', '双方爱打什么体系，最近谁在变？', '体系雷达 + 窗口斜率'],
  ['plan', '07', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？', '历史证据，不是最优解'],
];
const STORE_KEY = 'bp-studio.v3';

export function createBpStudio({esc, fmt, pct, icon, portrait, API_BASE}) {
  /* 元流之子实际只有这五个形态：坦克 / 辅助 / 射手 / 法师 / 刺客。 */
  const FORM_ABBR = {坦克: '坦', 辅助: '辅', 射手: '射', 法师: '法', 刺客: '刺'};

  /* 英雄简称：元流之子（坦克）→ 元坦、元流之子（法师）→ 元法；组合串按 + 拆开分别简称。 */
  function heroShort(name) {
    const text = String(name ?? '');
    if (text.includes(' + ')) return text.split(' + ').map(heroShort).join(' + ');
    const match = text.match(/^(.+?)[(（]([^)）]+)[)）]$/);
    if (!match) return text;
    const base = match[1].trim();
    const form = FORM_ABBR[match[2].trim()] || match[2].trim().slice(0, 1);
    if (base === '元流之子') return `元${form}`;
    return `${base}·${form}`;
  }

  const viz = createBpViz({esc, portrait, short: heroShort});
  const state = {
    root: null, controller: null, disposed: false,
    data: null, loading: false, error: '',
    source: 'kpl', leagues: [], team: '', opponent: '',
    recentDays: 30, from: '', to: '', compare: 'prev',
    lane: '', chartAll: false, chartView: 'bubble', comboOpen: false, comboSize: 2, comboSort: 'usage', oppComboSize: '2',
    comboPick: [], comboDetail: null, comboLoading: false, comboError: '',
    target: [], targetData: null, targetLoading: false, targetError: '', targetOpen: false,
    heroSearch: '', comboSearch: '', targetSearch: '',
    types: null, typesLoading: false, typesError: '', typeBo: 0, typeSide: 'opponent', kplTypes: null, prior: 60, typeHand: 0, typeCore: 0, typeFocus: '', counterRowLane: '', counterColLane: '', counterSel: null, counterMode: 'pick',
    tree: null, treeLoading: false, treeError: '', treeDepth: 6, treeBranch: 3, treeSide: '', treeStale: true,
    treeMode: 'flow', decisionPath: [], decisionPins: [],
    seqTeam: 'opponent', seqAction: 'pick', seqHand: 1, seqHero: '', seqLane: '', seqOpen: false,
    seqData: null, seqLoading: false, seqError: '', lastLoadedAt: 0, teamQuery: '', collapsed: {},
    typesStale: true, seqStale: true, heroQuery: '', viewNote: '', compact: false,
    solo: true, active: 'heroes',
    pins: {heroes: [], combos: []}, heroSort: {key: 'priority', dir: -1}, views: [], viewName: '',
    shareTip: '', compareOpponent: '', compareBlock: null, compareLoading: false,
    pop: '',
  };

  const has = (n) => typeof n === 'number' && Number.isFinite(n);
  const num = (n) => has(n) ? fmt(n) : '—';
  const rate = (n) => has(n) ? pct(n) : '—';
  const signed = (n, d = 1) => has(n) ? `${n > 0 ? '+' : ''}${fmt(n, d)}` : '—';
  const interval = (arr) => Array.isArray(arr) && has(arr[0]) && has(arr[1])
    ? `${pct(arr[0])}–${pct(arr[1])}` : '—';

  // ── 视觉基元 ────────────────────────────────────────────────────────
  const deltaChip = (value, {tone = 'good', suffix = ' pp'} = {}) => {
    if (!has(value)) return '<span class="bps-delta is-fall">—</span>';
    if (Math.abs(value) < 0.05) return '<span class="bps-delta is-fall">持平</span>';
    const up = value > 0;
    let cls;
    if (tone === 'good') cls = up ? 'is-good' : 'is-bad';
    else if (tone === 'bad') cls = up ? 'is-bad' : 'is-good';
    else cls = up ? 'is-rise' : 'is-fall';
    return `<span class="bps-delta ${cls}"><i>${up ? '▲' : '▼'}</i>${fmt(Math.abs(value), 1)}${suffix}</span>`;
  };

  const sampleBadge = (sample) => {
    const cls = sample === '样本充足' ? 'is-good' : sample === '小样本' ? 'is-mid' : 'is-low';
    return `<span class="bps-badge ${cls}">${esc(sample || '样本不足')}</span>`;
  };

  const heroImg = (hero, cls = '') => {
    const html = portrait(hero, `bps-p ${cls}`.trim());
    const attr = `data-hover-hero="${esc(hero)}"`;
    return html.includes('<img ') ? html.replace('<img ', `<img ${attr} `)
      : `<span ${attr}>${html}</span>`;
  };

  function qualityChip() {
    const quality = state.data?.quality;
    if (!quality?.games) return '';
    const pctValue = Math.round((quality.ordered / quality.games) * 100);
    const title = `数据截至 ${state.data?.scope?.to || '—'}；盲选 ${quality.blind} 局 · BP 不完整 ${quality.partial} 局，已从“第 N 手”统计剔除`;
    return `<span class="bps-quality" title="${esc(title)}">手序 ${num(quality.ordered)}/${num(quality.games)} · ${pctValue}%</span>`;
  }

  const teamMark = (name, cls = '') => {
    if (name === '__all__') {
      return `<span class="bps-team-mark ${cls}" title="全部对手"><b>Σ</b></span>`;
    }
    const icons = state.data?.options?.teamIcons || {};
    const team = (state.data?.options?.teams || []).find((item) => item.name === name);
    const src = icons[name];
    const abbr = (team?.abbr || name || '?').slice(0, 3);
    const safe = typeof src === 'string' && /^\/catalog\/icons\/teams\/[A-Za-z0-9_.-]+$/.test(src);
    return `<span class="bps-team-mark ${cls}" title="${esc(name || '')}">${safe
      ? `<img src="${esc(src)}" alt="${esc(name || '')}">` : esc(abbr)}</span>`;
  };

  const heroFace = (hero, {count = null, share = null, wr = null} = {}) => `
    <span class="bps-face">${heroImg(hero)}<span>${esc(heroShort(hero))}</span>${count == null
      ? '' : `<em>${num(count)} 局</em>`}${share == null ? '' : `<em>${rate(share)}</em>`}${wr == null
      ? '' : `<em class="is-wr">胜率 ${rate(wr)}</em>`}</span>`;

  const seg = (items, active, attr, {small = false} = {}) => `
    <div class="bps-seg ${small ? 'is-small' : ''}" role="group">
      ${items.map(([value, label]) => `<button type="button" ${attr}="${esc(value)}"
        aria-pressed="${String(active) === String(value)}">${esc(label)}</button>`).join('')}
    </div>`;

  const section = (id, no, title, question, metaText = '') => {
    const meta = SECTION_LIST.find(([key]) => key === id) || [];
    return `<section class="bps-section" id="bps-${id}" data-bps-section="${id}">
      <header class="bps-section-head">
        <span class="bps-section-no">${no}</span>
        <h2>${esc(title)}</h2>
        <span class="bps-section-meta">${esc(metaText || meta[4] || '')}</span>
        <p>${esc(question)}</p>
      </header>`;
  };

  // ── 数据 ────────────────────────────────────────────────────────────
  function queryParams(extra = {}) {
    const values = {source: state.source, recentDays: state.recentDays,
      compare: state.compare, ...extra};
    if (state.leagues.length) values.leagues = state.leagues.join(',');
    if (state.team) values.team = state.team;
    else if (!state.data) values.team = '__auto__';
    if (state.opponent) values.opponent = state.opponent;
    else if (!state.data) values.opponent = '__auto__';
    if (state.from && state.to) { values.from = state.from; values.to = state.to; }
    return new URLSearchParams(values).toString();
  }

  async function api(path, signal) {
    const response = await fetch(`${API_BASE}/api/v3/bp-studio${path}`, {
      cache: 'no-store', signal, headers: {Accept: 'application/json'},
    });
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail || ''; } catch {}
      throw new Error(detail || `请求失败（HTTP ${response.status}）`);
    }
    return response.json();
  }

  function persist() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        source: state.source, leagues: state.leagues, team: state.team,
        opponent: state.opponent, recentDays: state.recentDays,
        from: state.from, to: state.to, compare: state.compare,
        lane: state.lane, chartAll: state.chartAll, chartView: state.chartView,
        comboSize: state.comboSize, comboSort: state.comboSort, prior: state.prior,
        collapsed: state.collapsed, pins: state.pins, views: state.views, compact: state.compact,
        solo: state.solo, active: state.active,
        treeDepth: state.treeDepth, treeBranch: state.treeBranch, treeSide: state.treeSide,
        comboPick: state.comboPick, target: state.target,
      }));
    } catch {}
    syncUrl();
  }

  function syncUrl() {
    if (!state.root || !state.data) return;
    try {
      history.replaceState(null, '', `${location.pathname}?${shareParams().toString()}${location.hash || '#bp'}`);
    } catch {}
  }

  function restore() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (!raw || typeof raw !== 'object') return;
      for (const key of ['source', 'team', 'opponent', 'recentDays', 'from', 'to',
        'compare', 'lane', 'chartAll', 'chartView', 'comboSize', 'comboSort', 'prior',
        'treeDepth', 'treeBranch', 'treeSide']) {
        if (raw[key] !== undefined && raw[key] !== null) state[key] = raw[key];
      }
      if (Array.isArray(raw.leagues)) state.leagues = raw.leagues.slice(0, 40);
      if (Array.isArray(raw.comboPick)) state.comboPick = raw.comboPick.slice(0, 3);
      if (Array.isArray(raw.target)) state.target = raw.target.slice(0, 3);
      if (raw.collapsed && typeof raw.collapsed === 'object') state.collapsed = raw.collapsed;
      if (typeof raw.compact === 'boolean') state.compact = raw.compact;
      if (typeof raw.solo === 'boolean') state.solo = raw.solo;
      if (SECTION_LIST.some(([key]) => key === raw.active)) state.active = raw.active;
      if (raw.pins && typeof raw.pins === 'object') {
        state.pins = {heroes: Array.isArray(raw.pins.heroes) ? raw.pins.heroes.slice(0, 20) : [],
          combos: Array.isArray(raw.pins.combos) ? raw.pins.combos.slice(0, 20) : []};
      }
      if (Array.isArray(raw.views)) state.views = raw.views.slice(0, 20);
    } catch {}
  }

  async function load() {
    if (!state.root || state.disposed) return;
    state.controller?.abort();
    state.controller = new AbortController();
    const controller = state.controller;
    state.loading = true;
    state.error = '';
    paint();
    try {
      const data = await api(`?${queryParams()}`, controller.signal);
      if (controller.signal.aborted) return;
      state.data = data;
      state.loading = false;
      state.lastLoadedAt = Date.now();
      if (!state.team) state.team = data.scope?.team || data.options.defaultTeam || '';
      if (!state.opponent) state.opponent = data.scope?.opponent || data.options.defaultOpponent || '';
      paint();
      if (state.target.length) loadTarget();
      if (state.comboPick.length >= 2) loadCombo();
      state.typesStale = true;
      state.treeStale = true;
      state.seqStale = true;
      observeLazy();
      if (state.compareOpponent) loadCompareOpponent();
    } catch (error) {
      if (controller.signal.aborted) return;
      state.loading = false;
      state.error = error.message || '读取失败';
      paint();
    }
  }

  let targetTimer = 0;
  function queueTarget() {
    clearTimeout(targetTimer);
    targetTimer = setTimeout(loadTarget, 220);
  }

  async function loadTarget() {
    if (!state.root || !state.target.length) return;
    state.targetLoading = true;
    state.targetError = '';
    paint();
    try {
      const search = new URLSearchParams({target: state.target.join(','),
        recentDays: state.recentDays, source: state.source});
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.team) search.set('team', state.team);
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      const data = await api(`/target?${search.toString()}`);
      state.targetData = data;
    } catch (error) {
      state.targetError = error.message || '目标读取失败';
    } finally {
      state.targetLoading = false;
      paint();
    }
  }

  let comboTimer = 0;
  function queueCombo() {
    clearTimeout(comboTimer);
    comboTimer = setTimeout(loadCombo, 180);
  }

  async function loadCombo() {
    if (!state.root || state.comboPick.length < 2) {
      state.comboDetail = null;
      return;
    }
    state.comboLoading = true;
    state.comboError = '';
    paint();
    try {
      const search = new URLSearchParams({target: state.comboPick.join(','),
        source: state.source, recentDays: state.recentDays});
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.source === 'scrim' && state.team) search.set('team', state.team);
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      const data = await api(`/combo?${search.toString()}`);
      state.comboDetail = data;
    } catch (error) {
      state.comboError = error.message || '组合读取失败';
    } finally {
      state.comboLoading = false;
      paint();
    }
  }

  async function loadTypes() {
    if (!state.root || !state.data) return;
    state.typesLoading = true;
    state.typesError = '';
    paint();
    try {
      const search = new URLSearchParams({source: state.source,
        recentDays: state.recentDays, bo: String(state.typeBo),
        hand: String(state.typeHand), core: String(state.typeCore)});
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.team) search.set('team', state.team);
      if (state.opponent) search.set('opponent', state.opponent);
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      if (state.target.length) search.set('targets', state.target.join(','));
      state.types = await api(`/types?${search.toString()}`);
      state.typesStale = false;
      if (state.source === 'scrim') {
        const base = new URLSearchParams({source: 'kpl', recentDays: state.recentDays,
          bo: String(state.typeBo), hand: String(state.typeHand), core: String(state.typeCore)});
        if (state.leagues.length) base.set('leagues', state.leagues.join(','));
        if (state.from && state.to) { base.set('from', state.from); base.set('to', state.to); }
        state.kplTypes = await api(`/types?${base.toString()}`);
      } else {
        state.kplTypes = null;
      }
    } catch (error) {
      state.typesError = error.message || '类型数据读取失败';
    } finally {
      state.typesLoading = false;
      paint();
    }
  }

  async function loadTree() {
    if (!state.root || !state.data) return;
    state.treeLoading = true;
    state.treeError = '';
    state.decisionPath = [];
    state.decisionPins = [];
    paint();
    try {
      const search = new URLSearchParams({
        source: state.source, recentDays: state.recentDays,
        depth: String(state.treeDepth), branch: String(state.treeBranch),
      });
      let team;
      if (state.typeSide === 'opponent' && state.opponent && state.opponent !== '__all__') {
        team = state.opponent;
      } else {
        team = state.source === 'scrim' ? '本队' : state.team;
        if (state.opponent && state.opponent !== '__all__') search.set('opponent', state.opponent);
      }
      if (team) search.set('team', team);
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      if (state.treeSide) search.set('side', state.treeSide);
      state.tree = await api(`/tree?${search.toString()}`);
      state.treeStale = false;
    } catch (error) {
      state.treeError = error.message || '时序分支读取失败';
      state.treeStale = false;
    } finally {
      state.treeLoading = false;
      paint();
    }
  }

  async function loadSequence() {
    if (!state.root || !state.data) return;
    state.seqLoading = true;
    state.seqError = '';
    paint();
    try {
      const search = new URLSearchParams({
        source: state.source, action: state.seqAction,
        hand: String(state.seqHand), recentDays: state.recentDays,
      });
      const team = state.seqTeam === 'own'
        ? (state.source === 'scrim' ? '本队' : state.team)
        : (state.opponent === '__all__' ? '' : state.opponent);
      if (team) search.set('team', team);
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.seqHero) search.set('hero', state.seqHero);
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      state.seqData = await api(`/sequence?${search.toString()}`);
      state.seqStale = false;
    } catch (error) {
      state.seqError = error.message || '手序数据读取失败';
    } finally {
      state.seqLoading = false;
      paint();
    }
  }

  /* 我的关注 + 样本不足提示 */
  function pinsBar() {
    const heroes = state.pins.heroes || [];
    const combos = state.pins.combos || [];
    if (!heroes.length && !combos.length) return '';
    return `<div class="bps-pins">
      <span class="bps-pins-label">我的关注</span>
      ${heroes.map((hero) => `<button type="button" class="bps-pin-chip" data-bps-pin-hero="${esc(hero)}">
        ${heroImg(hero)}<span>${esc(heroShort(hero))}</span><i data-bps-unpin="hero:${esc(hero)}" aria-label="取消关注">×</i></button>`).join('')}
      ${combos.map((combo) => `<button type="button" class="bps-pin-chip" data-bps-pin-combo="${esc(combo)}">
        ${combo.split(',').map((hero) => heroImg(hero)).join('')}<span>${esc(combo.replace(/,/g, ' + '))}</span>
        <i data-bps-unpin="combo:${esc(combo)}" aria-label="取消关注">×</i></button>`).join('')}
    </div>`;
  }

  function sampleBanner() {
    const games = state.data?.scope?.games || 0;
    if (games >= 20) return '';
    const next = state.recentDays < 90 ? 90 : 365;
    return `<div class="bps-sample-warn">
      <b>当前窗口只有 ${num(games)} 个队-局</b>
      <span>胜率、克制这类结论很容易被 1–2 局带偏。</span>
      <button type="button" class="bps-softbtn" data-bps-widen="${next}">放到近 ${next} 天</button>
    </div>`;
  }

  function applyShareLink() {
    try {
      const params = new URLSearchParams(location.search);
      if (params.get('bps') !== '1') return;
      const read = (key) => params.get(key);
      if (read('source') === 'scrim' || read('source') === 'kpl') state.source = read('source');
      if (read('leagues')) state.leagues = read('leagues').split(',').filter(Boolean).slice(0, 40);
      if (read('team') !== null) state.team = read('team');
      if (read('opponent') !== null) state.opponent = read('opponent');
      if (read('days')) state.recentDays = Number(read('days')) || 30;
      if (read('from')) state.from = read('from');
      if (read('to')) state.to = read('to');
      if (read('compare')) state.compare = read('compare');
      if (read('target')) state.target = read('target').split(',').filter(Boolean).slice(0, 3);
      if (read('combo')) state.comboPick = read('combo').split(',').filter(Boolean).slice(0, 3);
      if (read('bo')) state.typeBo = Number(read('bo')) || 0;
      if (read('hand')) state.typeHand = Number(read('hand')) || 0;
      if (read('core')) state.typeCore = Number(read('core')) || 0;
    } catch {}
  }

  function shareParams() {
    const params = new URLSearchParams({bps: '1', source: state.source});
    if (state.leagues.length) params.set('leagues', state.leagues.join(','));
    if (state.team) params.set('team', state.team);
    if (state.opponent) params.set('opponent', state.opponent);
    if (state.from && state.to) { params.set('from', state.from); params.set('to', state.to); }
    params.set('days', String(state.recentDays));
    params.set('compare', state.compare);
    if (state.target.length) params.set('target', state.target.join(','));
    if (state.comboPick.length) params.set('combo', state.comboPick.join(','));
    if (state.typeBo) params.set('bo', String(state.typeBo));
    if (state.typeHand) params.set('hand', String(state.typeHand));
    if (state.typeCore) params.set('core', String(state.typeCore));
    return params;
  }


  /* 综合推荐 = KPL 份额 × 先验权重 + 本队份额 × (1-权重) */
  function blendRows(rows) {
    const weight = (state.prior ?? 60) / 100;
    return (rows || []).map((row) => ({
      ...row,
      blend: Math.round(((row.kplShare || 0) * weight + (row.ownShare || 0) * (1 - weight)) * 10) / 10,
    })).sort((a, b) => b.blend - a.blend).slice(0, 5);
  }

  function blendPanel() {
    const compare = state.targetData?.compare;
    if (!compare?.available) return '';
    const rows = blendRows(compare.rows);
    if (!rows.length) return '';
    return `<div class="bps-blend-rows">${rows.map((row) => `
      <span class="bps-face">${heroImg(row.hero)}<span>${esc(row.hero)}</span>
        <em>${num(row.blend)}%</em><em class="bps-sub">K ${num(row.kplShare)}% · 我 ${num(row.ownShare)}%</em></span>`).join('')}
    </div>`;
  }

  function filterSnapshot() {
    return {
      source: state.source, leagues: [...state.leagues], team: state.team,
      opponent: state.opponent, from: state.from, to: state.to,
      recentDays: state.recentDays, compare: state.compare,
      target: [...state.target], comboPick: [...state.comboPick],
      typeBo: state.typeBo, typeHand: state.typeHand, typeCore: state.typeCore,
      seqTeam: state.seqTeam, seqAction: state.seqAction, seqHand: state.seqHand,
      seqHero: state.seqHero, typeFocus: state.typeFocus,
    };
  }

  // ── 标题带 ──────────────────────────────────────────────────────────
  function heroBand() {
    const data = state.data;
    const scope = data.scope;
    const heroes = data.primary.heroes;
    const top = heroes.top?.[0];
    const topBan = [...(heroes.rows || [])].sort((a, b) => (b.banRate || 0) - (a.banRate || 0))[0];
    const isKpl = state.source === 'kpl';
    const topHero = top?.hero || '';
    const banHero = topBan?.hero || '';
    const title = !isKpl
      ? `本队 ${data.primary.games ? num(data.primary.games) : 0} 个队-局，<em>对照</em> KPL 校准`
      : (topHero && banHero && topHero !== banHero
        ? `<em>${esc(topHero)}</em> 优先级最高，${esc(banHero)} 最吃 Ban`
        : topHero
          ? `<em>${esc(topHero)}</em> 一个人占了两头：优先级最高，也最吃 Ban`
          : 'BP 工作台');
    const years = (data.options.years || []).filter((row) => row.year);
    const span = years.length ? `${years[0].year}–${years[years.length - 1].year}` : '—';
    const seasonText = state.leagues.length ? `${state.leagues.length} 个赛季` : span;
    const games = data.primary.games;
    const teamGames = data.primary.boardGames;
    return `<header class="bps-hero">
      <div class="bps-hero-copy">
        <span class="bps-eyebrow"><i></i>BP STUDIO · ${isKpl ? 'KPL 赛事' : '训练赛'}</span>
        <h1>${title}</h1>
        <p>${isKpl
          ? `按每方 Ban/Pick 数组统计第 N 手；<b>${num(games)}</b> 个队-局里看版本、组合、拆解与对手习惯。`
          : `只统计本队训练赛 <b>${num(teamGames)}</b> 个队-局；KPL 同窗口作为先验对照，两边不混算。`}
          ${state.from && state.to ? `当前自定义窗口 <b>${esc(state.from)} → ${esc(state.to)}</b>。` : ''}</p>
      </div>
      <div class="bps-hero-facts">
        <div><span>覆盖队-局</span><b>${num(games)}</b><small>${isKpl ? 'KPL 双方视角' : '本队视角'}</small></div>
        <div><span>赛季范围</span><b>${esc(seasonText)}</b><small>${esc(String(scope.from || '').slice(5))} → ${esc(String(scope.to || '').slice(5))}</small></div>
        <div><span>对比窗口</span><b>${state.compare === 'prev' ? '环比' : state.compare === 'yoy' ? '同比' : '关闭'}</b><small>${scope.prev ? `${esc(String(scope.prev.from).slice(5))} → ${esc(String(scope.prev.to).slice(5))}` : '无上一窗口'}</small></div>
        <div><span>对手样本</span><b>${state.opponent ? num(data.opponentBlock?.games || 0) : '—'}</b><small>${state.opponent ? esc(state.opponent === '__all__' ? '全部对手' : state.opponent) : '未选择对手'}</small></div>
      </div>
    </header>`;
  }

  // ── 筛选台 ──────────────────────────────────────────────────────────
  function seasonPanel() {
    const years = state.data?.options?.years || [];
    const selected = new Set(state.leagues);
    return `<div class="bps-pop" data-bps-pop-panel="season" ${state.pop === 'season' ? '' : 'hidden'}>
      <div class="bps-pop-head"><b>选择赛季</b>
        <span class="bps-sub">${selected.size ? `已选 ${selected.size} 个` : '未选 = 全库'}</span>
      </div>
      ${years.map((year) => {
        const ids = year.leagues.map((row) => row.id);
        const allOn = ids.every((id) => selected.has(id));
        return `<div class="bps-season-year">
          <b>${year.year}<small>${num(year.games)} 局</small></b>
          <div class="bps-chips">
            <button type="button" class="bps-chip" data-bps-year="${year.year}"
              aria-pressed="${allOn}">全年</button>
            ${year.leagues.map((row) => `<button type="button" class="bps-chip"
              data-bps-league="${esc(row.id)}" aria-pressed="${selected.has(row.id)}"
              title="${esc(row.name)} · ${num(row.games)} 局">${esc(row.short || row.kind)}
              <em>${num(row.games)}</em></button>`).join('')}
          </div>
        </div>`;
      }).join('')}
      <div class="bps-pop-foot">
        <button type="button" class="bps-link" data-bps-leagues-clear>清空（全库）</button>
        <button type="button" class="bps-softbtn" data-bps-pop-close>收起</button>
      </div>
    </div>`;
  }

  function teamPanel(kind) {
    const dataSource = state.data?.source || state.source;
    const scrim = dataSource === 'scrim';
    const options = kind === 'team'
      ? (scrim
        ? [{name: '本队', abbr: ''}]
        : (state.data?.options?.teams || []))
      : (scrim
        ? (state.data?.options?.scrimOpponents || []).map((name) => ({name, abbr: ''}))
        : (state.data?.options?.teams || []));
    const current = kind === 'team' ? state.team : state.opponent;
    return `<div class="bps-pop is-right" data-bps-pop-panel="${kind}" ${state.pop === kind ? '' : 'hidden'}>
      <div class="bps-pop-head"><b>${kind === 'team' ? '选择本队' : '选择对手'}</b>
        <span class="bps-sub">${scrim ? '训练赛只统计本队，对手来自营地记录' : '队标来自 KPL 官方赛程'}</span></div>
      ${scrim ? '' : `<label class="bps-search" style="margin-bottom:8px">${icon('search')}
        <input type="search" data-bps-team-search="${kind}" placeholder="搜战队" autocomplete="off" value="${esc(state.teamQuery || '')}">
      </label>`}
      <div class="bps-team-grid ${scrim ? 'is-scrim' : ''}">
        ${kind === 'opponent' ? `<button type="button" class="bps-team-option"
          data-bps-select-opponent="__all__" aria-pressed="${current === '__all__'}">
          <span class="bps-team-mark"><b>Σ</b></span>
          <span><b>全部对手（合并）</b><small>把所有对手的 BP 合在一起看</small></span>
        </button>` : ''}
        ${options.map((item) => `<button type="button" class="bps-team-option ${scrim ? 'is-plain' : ''}"
          data-bps-select-${kind}="${esc(item.name)}"
          aria-pressed="${item.name === current}">
          ${scrim ? '' : teamMark(item.name)}
          <span><b>${esc(item.name)}</b><small>${esc(item.abbr || '')}${item.games ? ` · ${num(item.games)} 场` : ''}</small></span>
        </button>`).join('') || `<p class="bps-note">${scrim ? '训练赛还没有对手记录。' : '这个数据源里还没有战队记录。'}</p>`}
      </div>
      <div class="bps-pop-foot">
        ${scrim ? '' : `<button type="button" class="bps-link" data-bps-select-${kind}="">不限定</button>`}
        <button type="button" class="bps-softbtn" data-bps-pop-close>收起</button>
      </div>
    </div>`;
  }

  function rangePanel() {
    const days = state.data?.options?.recentOptions || [7, 15, 30, 90, 180, 365];
    return `<div class="bps-pop is-right" data-bps-pop-panel="range" ${state.pop === 'range' ? '' : 'hidden'}>
      <div class="bps-pop-head"><b>时间窗口</b><span class="bps-sub">默认以数据最后一天为锚点</span></div>
      <div class="bps-chips">
        ${days.map((value) => `<button type="button" class="bps-chip" data-bps-days="${value}"
          aria-pressed="${!state.from && Number(state.recentDays) === value}">近 ${value} 天</button>`).join('')}
      </div>
      <div class="bps-range-custom" style="margin-top:14px">
        <label>起<input type="date" data-bps-from value="${esc(state.from)}"></label>
        <label>止<input type="date" data-bps-to value="${esc(state.to)}"></label>
      </div>
      <div class="bps-compare">
        <span class="bps-console-label">对比</span>
        ${seg([['prev', '环比'], ['yoy', '同比'], ['none', '关闭']], state.compare, 'data-bps-compare')}
      </div>
      <div class="bps-prior">
        <div><span class="bps-console-label">KPL 先验权重</span><b data-bps-prior-value>${num(state.prior)}%</b></div>
        <input type="range" min="0" max="100" step="5" value="${num(state.prior)}" data-bps-prior>
        <p class="bps-note">KPL ${num(state.prior)}% / 训练赛 ${num(100 - state.prior)}%。用于 03 的“综合推荐”和类型对照；强队可调低，次级队可调高。</p>
      </div>
      <div class="bps-pop-foot">
        <button type="button" class="bps-link" data-bps-range-reset>回到近 ${state.recentDays} 天</button>
        <button type="button" class="bps-primary" data-bps-range-apply>应用</button>
      </div>
    </div>`;
  }

  function viewsPanel() {
    return `<div class="bps-pop is-right" data-bps-pop-panel="views" ${state.pop === 'views' ? '' : 'hidden'}>
      <div class="bps-pop-head"><b>保存的视图</b><span class="bps-sub">把这一套筛选记下来，下次一键回来</span></div>
      <div class="bps-view-save">
        <input data-bps-view-name placeholder="例如：北京WB · BO5 · 第1手" value="${esc(state.viewName || '')}" autocomplete="off">
        <button type="button" class="bps-primary" data-bps-view-save>保存当前</button>
      </div>
      <div class="bps-view-save" style="margin-top:-4px">
        <input data-bps-view-note placeholder="备注（可选）：针对 WB 第一手盾山" value="${esc(state.viewNote || '')}" autocomplete="off">
      </div>
      <div class="bps-view-list">
        ${(state.views || []).map((view) => `<div class="bps-view-row">
          <button type="button" class="bps-view-name" data-bps-view-apply="${esc(view.name)}">${esc(view.name)}</button>
          <small>${esc(view.note || view.summary || '')}</small>
          <button type="button" class="bps-link" data-bps-view-del="${esc(view.name)}" aria-label="删除">×</button>
        </div>`).join('') || '<p class="bps-note">还没有保存的视图。</p>'}
      </div>
      <div class="bps-pop-foot">
        <button type="button" class="bps-softbtn" data-bps-share>复制分享链接</button>
        <button type="button" class="bps-softbtn" data-bps-export-all>导出长图（01–07）</button>
        <span class="bps-sub">${esc(state.shareTip || '链接会带上当前赛季、战队、窗口和目标')}</span>
      </div>
    </div>`;
  }

  function consoleBar() {
    const isKpl = state.source === 'kpl';
    const leagues = state.leagues.length;
    return `<div class="bps-console">
      <div class="bps-console-group">
        <span class="bps-console-label">数据源</span>
        ${seg([['kpl', 'KPL 赛事'], ['scrim', '训练赛']], state.source, 'data-bps-source')}
      </div>
      ${isKpl ? `<span class="bps-console-sep"></span>
      <div class="bps-console-group">
        <span class="bps-console-label">赛季</span>
        <button type="button" class="bps-trigger" data-bps-pop="season"
          aria-expanded="${state.pop === 'season'}">
          ${leagues ? `已选 ${leagues} 个赛季` : '全部赛季'}
          <span class="bps-trigger-sub">${leagues ? '' : (state.data?.options?.years?.length || 0) + ' 年'}</span>
          ${icon('chevron')}
        </button>
        ${seasonPanel()}
      </div>` : ''}
      <span class="bps-console-sep"></span>
      <div class="bps-console-group">
        <span class="bps-console-label">本队</span>
        <button type="button" class="bps-trigger" data-bps-pop="team"
          aria-expanded="${state.pop === 'team'}">
          ${state.team ? `${isKpl ? teamMark(state.team) : ''}<span>${esc(state.team)}</span>` : '不限定'}
          ${icon('chevron')}
        </button>
        ${teamPanel('team')}
      </div>
      <div class="bps-console-group">
        <span class="bps-console-label">对手</span>
        <button type="button" class="bps-trigger ${state.opponent ? '' : 'is-empty'}"
          data-bps-pop="opponent" aria-expanded="${state.pop === 'opponent'}">
          ${state.opponent ? `${isKpl ? teamMark(state.opponent) : ''}<span>${state.opponent === '__all__' ? '全部对手' : esc(state.opponent)}</span>` : '选择对手'}
          ${icon('chevron')}
        </button>
        ${teamPanel('opponent')}
      </div>
      <span class="bps-console-sep"></span>
      <div class="bps-console-group">
        <span class="bps-console-label">窗口</span>
        <button type="button" class="bps-trigger" data-bps-pop="range"
          aria-expanded="${state.pop === 'range'}">
          ${state.from && state.to ? `${esc(state.from)} → ${esc(state.to)}` : `近 ${state.recentDays} 天`}
          <span class="bps-trigger-sub">${state.compare === 'prev' ? '环比' : state.compare === 'yoy' ? '同比' : '不对比'}</span>
          ${icon('chevron')}
        </button>
        ${rangePanel()}
      </div>
      <span class="bps-console-sep"></span>
      <div class="bps-console-group">
        <span class="bps-console-label">视图</span>
        <button type="button" class="bps-trigger" data-bps-pop="views" aria-expanded="${state.pop === 'views'}">
          ${(state.views || []).length ? `${state.views.length} 个视图` : '保存视图'}
          ${icon('chevron')}
        </button>
        ${viewsPanel()}
      </div>
      <span class="bps-console-spacer"></span>
      ${state.loading
        ? '<span class="bps-updating"><i></i>更新中</span>'
        : qualityChip()}
      <button type="button" class="bps-softbtn is-icon" data-bps-compact aria-pressed="${state.compact}"
        title="${state.compact ? '切回标准视图' : '切换简洁视图（隐藏图表）'}">${state.compact ? '标准' : '简洁'}</button>
      <button type="button" class="bps-softbtn is-icon" data-bps-reset aria-label="重置筛选" title="清空赛季、战队、时间、目标等全部筛选">${icon('close')}</button>
      <button type="button" class="bps-softbtn is-icon" data-bps-refresh aria-label="重新读取" title="重新读取">${icon('refresh')}</button>
    </div>
    ${state.loading ? '<span class="bps-progress" aria-hidden="true"></span>' : ''}`;
  }

  function jumpBar() {
    return `<nav class="bps-jump" aria-label="BP 分区">
      ${SECTION_LIST.map(([key, no, title]) => `<button type="button" data-bps-jump="${key}"
        aria-pressed="${state.solo && state.active === key}"
        class="${state.solo && state.active === key ? 'is-active' : ''}">
        <i>${no}</i>${esc(title)}</button>`).join('')}
      <button type="button" class="bps-jump-mode" data-bps-solo aria-pressed="${state.solo}"
        title="${state.solo ? '当前：单节阅读，点击切回连续滚动' : '当前：连续滚动，点击切到单节阅读'}">
        ${state.solo ? '单节阅读' : '连续滚动'}
      </button>
    </nav>`;
  }

  function syncSticky() {
    const sticky = state.root?.querySelector('.bps-sticky');
    if (!sticky) return;
    const height = Math.round(sticky.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--bps-sticky-h', `${height}px`);
  }

  // ── 01 英雄优先级 ───────────────────────────────────────────────────
  function focusCard(row) {
    return `<button type="button" class="bps-focus" data-bps-hero-card="${esc(row.hero)}"
      title="把 ${esc(row.hero)} 送到 03 破解区">
      ${pinStar(`hero:${row.hero}`)}
      <span class="bps-focus-top">
        ${heroImg(row.hero)}
        <span class="bps-focus-id"><b>${esc(heroShort(row.hero))}</b>
          <small>${esc(row.lane || '分路未记录')} · ${esc(row.signal || '常规')}</small></span>
      </span>
      <span class="bps-focus-nums">
        <span>Pick<b>${rate(row.pickRate)}</b></span>
        <span>Ban<b>${rate(row.banRate)}</b></span>
        <span>胜率<b>${rate(row.winRate)}</b></span>
      </span>
      <span class="bps-focus-meta">
        <span>区间 ${interval(row.interval)}</span>
        <span>Ban ${deltaChip(row.delta?.ban, {tone: 'neutral'})}</span>
        <span>胜率 ${deltaChip(row.delta?.win)}</span>
      </span>
      <span class="bps-focus-spark">${viz.spark(row.spark, {key: 'pickRate', w: 220, h: 26})}</span>
    </button>`;
  }

  function heroSection() {
    const data = state.data;
    const block = data.primary.heroes;
    const rows = (block.rows || []).filter((row) => !state.lane || row.lane === state.lane);
    const laneCounts = {};
    for (const row of block.rows || []) laneCounts[row.lane || '未记录'] = (laneCounts[row.lane || '未记录'] || 0) + 1;
    const lanes = [['', '全部', block.rows?.length || 0],
      ...LANES.filter((lane) => laneCounts[lane]).map((lane) => [lane, lane, laneCounts[lane]])];
    const movers = block.movers || {up: [], down: []};
    const ranked = [...rows].sort((a, b) => (b.priority || 0) - (a.priority || 0));
    const chartRows = state.chartAll ? ranked : ranked.slice(0, 24);
    const matrixRows = state.chartAll ? ranked : (() => {
      const buckets = {};
      for (const row of ranked) (buckets[row.lane || '未记录'] = buckets[row.lane || '未记录'] || []).push(row);
      return Object.values(buckets).flatMap((list) => list.slice(0, 10));
    })();
    const moverRow = (row) => `<div class="bps-mover-row">${heroImg(row.hero)}
      <span>${esc(heroShort(row.hero))}</span>${deltaChip(row.delta?.ban, {tone: 'neutral'})}</div>`;
    const sortKey = state.heroSort?.key || 'priority';
    const sortDir = state.heroSort?.dir || -1;
    const filteredRows = rows.filter((row) => !state.heroQuery
      || row.hero.includes(String(state.heroQuery).trim()));
    const sortedRows = [...filteredRows].sort((a, b) => {
      const value = (row) => (sortKey === 'deltaBan' ? (row.delta?.ban ?? -999)
        : sortKey === 'deltaWin' ? (row.delta?.win ?? -999) : (row[sortKey] ?? -999));
      return (value(a) - value(b)) * sortDir;
    });
    const sortHead = (key, label) => `<th class="is-num" data-bps-hero-sort="${key}"
      aria-sort="${sortKey === key ? (sortDir > 0 ? 'ascending' : 'descending') : 'none'}">${label}${sortKey === key ? (sortDir > 0 ? ' ↑' : ' ↓') : ''}</th>`;
    const fullTable = `<details class="bps-details">
      <summary>逐英雄明细 <small>全部 ${num(block.rows?.length || 0)} 个英雄 · 当前筛选 ${num(rows.length)} 个 · 点表头排序</small></summary>
      <div class="bps-details-body">
        <label class="bps-search" style="margin:8px 4px 6px">${icon('search')}
          <input type="search" data-bps-hero-filter placeholder="搜英雄" value="${esc(state.heroQuery || '')}" autocomplete="off"></label>
        <table class="bps-table">
          <thead><tr><th data-bps-hero-sort="hero">英雄</th><th data-bps-hero-sort="lane">分路</th>${sortHead('pickRate', 'Pick')}${sortHead('banRate', 'Ban')}
            ${sortHead('winRate', '胜率')}<th>区间</th>${sortHead('deltaBan', 'Ban 环比')}${sortHead('deltaWin', '胜率环比')}</tr></thead>
          <tbody>${sortedRows.map((row) => `<tr>
            <td><span class="bps-face">${heroImg(row.hero)}<span>${esc(heroShort(row.hero))}</span></span></td>
            <td>${esc(row.lane || '—')}</td>
            <td class="is-num">${rate(row.pickRate)}</td>
            <td class="is-num">${rate(row.banRate)}</td>
            <td class="is-num is-strong">${rate(row.winRate)}</td>
            <td class="is-num">${interval(row.interval)}</td>
            <td class="is-num">${deltaChip(row.delta?.ban, {tone: 'neutral'})}</td>
            <td class="is-num">${deltaChip(row.delta?.win)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </details>`;
    return `${section('heroes', '01', '英雄优先级', '当前版本哪些英雄值得优先考虑？',
      state.chartView === 'bubble' ? '气泡 = Pick 次数 · 颜色 = 分路' : '色块 = Ban 率 · 按分路排优先级')}
      <div class="bps-hero-layout">
        <aside class="bps-lane-rail">
          ${lanes.map(([value, label, count]) => `<button type="button" data-bps-lane="${esc(value)}"
            aria-pressed="${state.lane === value}">${esc(label)}<em>${num(count)}</em></button>`).join('')}
        </aside>
        <div>
          <div class="bps-panel">
            <div class="bps-chart-head"><b>${state.chartView === 'bubble' ? 'Ban × 胜率 气泡图' : '分路优先级矩阵'}</b>
              <span>${state.chartView === 'bubble' ? '滚轮缩放 / 拖拽移动 · 气泡 = Pick 次数 · 虚线 = 中位 Ban 与 50% 胜率' : '色块越深 Ban 率越高 · 每个分路按优先级取前 10'}</span></div>
            <div class="bps-chart-tools">
              ${seg([['top', '前 24 高优先'], ['all', '全部 ' + num(rows.length)]], state.chartAll ? 'all' : 'top', 'data-bps-chart-limit', {small: true})}
              ${seg([['bubble', '气泡图'], ['matrix', '分路矩阵']], state.chartView, 'data-bps-chart-view', {small: true})}
              ${state.chartView === 'bubble' ? '<button type="button" class="bps-link" data-bps-chart-reset>重置视图</button>' : ''}
            </div>
            <div class="bps-chart">${state.chartView === 'bubble'
              ? viz.heroScatter(chartRows, {onlyLane: state.lane, width: 1080, height: 430, minDecided: 8})
              : heroMatrix(matrixRows)}</div>
            ${state.chartView === 'bubble' ? `<div class="bps-chart-legend">
              ${['对抗路', '打野', '中路', '发育路', '游走'].map((lane) => `<i><span style="display:inline-block;width:8px;height:8px;border-radius:3px;background:${viz.LANE_COLOR[lane]}"></span>${lane}</i>`).join('')}
              <i><span style="display:inline-block;width:8px;height:8px;border-radius:50%;border:2px solid var(--bps-quiet)"></span>气泡大小 = Pick 次数</i>
              <i>只标注优先级最高的 12 个</i>
            </div>` : ''}
          </div>
          <div class="bps-focus-grid">${rows.slice(0, 4).map(focusCard).join('')}</div>
          ${fullTable}
        </div>
        <aside class="bps-movers">
          <div class="bps-movers-block">
            <b>升温 · Ban 率上升</b>
            ${(movers.up || []).slice(0, 5).map(moverRow).join('') || '<p class="bps-note">样本不足</p>'}
          </div>
          <div class="bps-movers-block">
            <b>降温 · Ban 率下降</b>
            ${(movers.down || []).slice(0, 5).map(moverRow).join('') || '<p class="bps-note">样本不足</p>'}
          </div>
          <div class="bps-movers-block">
            <b>怎么读</b>
            <p class="bps-note">Ban 率 = 被 Ban 的队-局 ÷ 全部队-局；环比对照上一段同样长度的窗口。点击上方焦点卡或气泡里的英雄，会把目标送到 03 破解区。</p>
          </div>
        </aside>
      </div></section>`;
  }

  function heroMatrix(rows) {
    const byLane = {};
    for (const row of rows) {
      const lane = row.lane || '未记录';
      (byLane[lane] = byLane[lane] || []).push(row);
    }
    const lanes = [...LANES.filter((lane) => byLane[lane]), ...(byLane['未记录'] ? ['未记录'] : [])];
    if (!lanes.length) return '<div class="bv-empty">当前筛选没有英雄。</div>';
    return `<div class="bps-matrix">${lanes.map((lane) => {
      const list = [...byLane[lane]].sort((a, b) => (b.priority || 0) - (a.priority || 0));
      const maxBan = Math.max(1, ...list.map((row) => row.banRate || 0));
      return `<div class="bps-matrix-col">
        <header><b>${esc(lane)}</b><span>${num(list.length)} 个英雄</span></header>
        <div class="bps-matrix-grid">
          ${list.slice(0, 12).map((row, index) => {
            const heat = Math.min(1, (row.banRate || 0) / maxBan);
            return `<button type="button" class="bps-tile" data-bps-hero-card="${esc(row.hero)}"
              style="--heat:${heat.toFixed(2)}" title="Pick ${rate(row.pickRate)} · Ban ${rate(row.banRate)} · 胜率 ${rate(row.winRate)}">
              <i class="bps-tile-bg"></i>
              <span class="bps-tile-rank">${index + 1}</span>
              ${heroImg(row.hero)}
              <span class="bps-tile-id"><b>${esc(heroShort(row.hero))}</b><small>${rate(row.winRate)} 胜率</small></span>
              <span class="bps-tile-nums"><em>P ${rate(row.pickRate)}</em><em>B ${rate(row.banRate)}</em></span>
            </button>`;
          }).join('')}
        </div>
      </div>`;
    }).join('')}</div>`;
  }

  function heroPicker(picked, {action = 'combo', max = 3, placeholder = ''} = {}) {
    const heroes = state.data?.options?.heroes || [];
    const priority = new Map((state.data?.primary?.heroes?.rows || [])
      .map((row) => [row.hero, row.priority || 0]));
    const ranked = [...heroes].sort((a, b) => {
      if (a.lane !== b.lane) return 0;
      return (priority.get(b.name) || 0) - (priority.get(a.name) || 0);
    });
    const laneOrder = LANES.filter((lane) => heroes.some((row) => row.lane === lane));
    const groups = [...laneOrder, '其他'];
    const selected = new Set(picked);
    return `<div class="bps-picker" data-bps-picker="${action}">
      <div class="bps-picker-head">
        <div class="bps-picker-selected">
          ${picked.map((hero) => `<span class="bps-picker-chip">${heroImg(hero)}<span>${esc(heroShort(hero))}</span>
            <button type="button" data-bps-remove="${esc(hero)}" data-bps-remove-action="${action}"
              aria-label="移除 ${esc(hero)}">×</button></span>`).join('')
            || `<span class="bps-sub">${esc(placeholder || '点头像选英雄，最多 3 个')}</span>`}
        </div>
        <div class="bps-picker-tools">
          <label class="bps-search">${icon('search')}
            <input type="search" data-bps-search="${action}" value="${esc(state[`${action}Search`] || '')}"
              placeholder="搜英雄" autocomplete="off"></label>
          <span class="bps-sub">${picked.length}/${max}</span>
          <button type="button" class="bps-link" data-bps-clear="${action}">清空</button>
        </div>
      </div>
      <div class="bps-picker-grid">
        ${groups.map((lane) => {
          const list = ranked.filter((row) => (lane === '其他' ? !laneOrder.includes(row.lane) : row.lane === lane));
          if (!list.length) return '';
          return `<div class="bps-picker-lane" data-lane-group="${esc(lane)}">
            <span>${esc(lane)}</span><i></i></div>${list.map((row) => `<button type="button"
            class="bps-hero-btn ${selected.has(row.name) ? 'is-on' : ''}"
            data-bps-pick="${esc(row.name)}" data-bps-pick-action="${action}"
            data-bps-hero-name="${esc(row.name)}" aria-pressed="${selected.has(row.name)}">
            ${heroImg(row.name)}<span>${esc(heroShort(row.name))}</span></button>`).join('')}`;
        }).join('')}
      </div>
    </div>`;
  }

  // ── 02 组合强度 ─────────────────────────────────────────────────────
  function comboCard() {
    if (state.comboPick.length < 2) {
      return `<div class="bps-empty" style="margin-top:14px"><b>先选两个英雄</b>
        <p>组合按“同队同局”统计：两个英雄在同一支队、同一局里一起出场才算命中。</p></div>`;
    }
    if (state.comboLoading && !state.comboDetail) {
      return '<div class="bps-loading"><span class="bps-spinner"></span>正在查这组英雄的同队同局记录…</div>';
    }
    if (state.comboError) {
      return `<div class="bps-inline-error">${esc(state.comboError)}
        <button type="button" class="bps-softbtn" data-bps-combo-retry>重试</button></div>`;
    }
    const detail = state.comboDetail;
    if (!detail) return '<div class="bps-loading">准备组合数据…</div>';
    if (!detail.available) {
      return `<div class="bps-empty" style="margin-top:14px"><b>这组英雄没有同队同局记录</b>
        <p>${esc(detail.reason || '换一个组合或放宽时间窗。')}</p></div>`;
    }
    const recent = (detail.recent || []).map((row) => `<div class="bps-window-cell">
      <span>近 ${num(row.days)} 天</span><b>${rate(row.winRate)}</b>
      <small>${num(row.games)} 局 · 前窗 ${rate(row.previousWinRate)}</small></div>`).join('');
    return `<article class="bps-combo-card">
      <div class="bps-combo-hero">
        <div class="bps-combo-faces">${detail.heroes.map((hero) => heroImg(hero)).join('<i class="is-plus">+</i>')}</div>
        <div class="bps-combo-title">
          <h3>${esc(heroShort(detail.label))}</h3>
          <p>${esc(detail.team || (state.source === 'kpl' ? 'KPL 联盟' : '本队'))} · 同队同局 ${num(detail.games)} 局 · 占所选范围 ${rate(detail.share)}</p>
        </div>
        <span style="margin-left:auto">${sampleBadge(detail.sample)}</span>
      </div>
      <div class="bps-combo-metrics">
        <div><span>命中局数</span><b>${num(detail.games)}</b><small>${num(detail.wins)} 胜 / ${num(detail.decided)} 局有胜负</small></div>
        <div><span>组合胜率</span><b>${rate(detail.winRate)}</b><small>${interval(detail.interval)} · Wilson 95%</small></div>
        <div><span>相对基准</span><b class="${has(detail.relative) ? (detail.relative >= 0 ? 'is-good' : 'is-bad') : ''}">${has(detail.relative) ? `${signed(detail.relative)} pp` : '—'}</b><small>单英雄基准 ${rate(detail.reference)}</small></div>
        <div><span>覆盖战队</span><b>${num(detail.teams)}</b><small>${state.source === 'kpl' ? 'KPL / 挑战者杯' : '训练赛'}</small></div>
      </div>
      <div class="bps-combo-body">
        <div class="bps-combo-section"><b>近 7 / 15 / 30 天</b><div class="bps-window-row">${recent}</div></div>
        <div class="bps-combo-section"><b>常见搭档</b>
          <div class="bps-faces-row">${(detail.teammates || []).slice(0, 6).map((row) => heroFace(row.hero, {count: row.games, wr: row.winRate})).join('') || '<span class="bps-sub">没有重复搭档</span>'}</div>
        </div>
        <div class="bps-combo-section"><b>主要对手</b>
          <div class="bps-faces-row">${(detail.opponents || []).slice(0, 5).map((row) => heroFace(row.opponent, {count: row.games, wr: row.winRate})).join('') || '<span class="bps-sub">没有对手记录</span>'}</div>
        </div>
        <p class="bps-note">相对基准 = 组合胜率 − 所选英雄各自收缩胜率的均值；不是因果协同。</p>
      </div>
    </article>`;
  }

  function trioCards(rows) {
    const list = (rows || []).slice(0, 9);
    if (!list.length) return '<div class="bv-empty">当前范围没有三人组合。</div>';
    return `<div class="bps-trio-grid">${list.map((row) => {
      const rel = row.relative;
      return `<button type="button" class="bps-trio" data-bps-combo-row="${esc(row.heroes.join(','))}">
        <span class="bps-trio-faces">${row.heroes.map((hero) => heroImg(hero)).join('<i>+</i>')}</span>
        <span class="bps-trio-meta"><b>${num(row.games)} 局</b><em>${rate(row.winRate)}</em></span>
        <span class="bps-trio-rel ${has(rel) ? (rel >= 0 ? 'is-good' : 'is-bad') : ''}">${has(rel) ? `${signed(rel)} pp` : '基准 —'}</span>
      </button>`;
    }).join('')}</div>`;
  }

  function comboSection() {
    const combos = state.data.primary.combos;
    const rows = (state.comboSize === 2 ? combos.pairs : combos.size3) || [];
    const sorted = state.comboSort === 'signal'
      ? [...rows].sort((a, b) => (b.relative ?? -999) - (a.relative ?? -999))
      : [...rows].sort((a, b) => (b.games || 0) - (a.games || 0));
    const list = state.comboOpen ? sorted.slice(0, 45) : sorted.slice(0, 12);
    const row = (item) => `<button type="button" class="bps-combo-row" data-bps-combo-row="${esc(item.heroes.join(','))}">
      ${pinStar(`combo:${item.heroes.join(',')}`)}
      <span class="bps-cr-faces">${item.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(heroShort(item.label))}</b></span>
      <span class="bps-cr-num">${num(item.games)} 局<small>${rate(item.share)} 使用率</small></span>
      <span class="bps-cr-ci">${viz.intervalDot(item.winRate, item.interval)}
        <small>${rate(item.winRate)} · ${interval(item.interval)}</small></span>
      <span class="bps-cr-num is-hide-sm">${deltaChip(item.deltaWin)}<small>环比</small></span>
      <span class="bps-cr-meta is-hide-sm">
        <span class="bps-badge ${item.relative == null ? 'is-low' : item.relative >= 0 ? 'is-good' : 'is-bad'}">${has(item.relative) ? `基准 ${signed(item.relative)}` : '基准 —'}</span>
      </span>
    </button>`;
    return `${section('combos', '02', '组合强度', '自选组合到底多强，联盟哪些组合在赢？')}
      <div class="bps-combo-layout">
        <div>
          ${heroPicker(state.comboPick, {action: 'combo', max: 3, placeholder: '选 2–3 个英雄查组合'})}
          <p class="bps-note" style="margin:8px 2px 0">选 2–3 个英雄，查同队同局战绩；再点一次取消。</p>
          ${comboCard()}
        </div>
        <div>
          ${state.comboSize === 2 ? `<div class="bps-panel">
            <div class="bps-chart-head"><b>组合矩阵 · 英雄 × 英雄</b>
              <span>颜色 = 相对基准（绿高红低）· 深浅 = 命中局数 · 数字 = 同队同局</span></div>
            <div class="bps-chart">${viz.comboMatrix(sorted, {width: 780, cell: 40})}</div>
          </div>` : `<div class="bps-panel">
            <div class="bps-chart-head"><b>三人组合 · 信号卡</b>
              <span>三张头像 = 同队同局三人 · 底色 = 相对基准</span></div>
            <div class="bps-chart" style="padding:6px 14px 14px">${trioCards(sorted)}</div>
          </div>`}
          <div class="bps-board" style="margin-top:14px">
            <div class="bps-board-head">
              ${seg([['2', '双人组合'], ['3', '三人组合']], state.comboSize, 'data-bps-combo-size', {small: true})}
              ${seg([['usage', '按使用'], ['signal', '按信号']], state.comboSort, 'data-bps-combo-sort', {small: true})}
            </div>
            <div class="bps-board-head" style="border-top:0;padding-top:0">
              <span class="bps-sub">${num(sorted.length)} 组 · 同队同局 ≥2 局才进榜</span>
              <span class="bps-sub">点一行带回左侧</span>
            </div>
            <div class="bps-board-list">${list.map(row).join('') || '<div class="bps-empty"><b>当前范围没有组合记录</b></div>'}</div>
            ${sorted.length > 12 ? `<div class="bps-board-foot">
              <button type="button" class="bps-link" data-bps-combo-more>${state.comboOpen ? '收起' : `展开全部 ${num(sorted.length)} 组`}</button>
            </div>` : ''}
          </div>
        </div>
      </div></section>`;
  }

  // ── 03 战队如何破解 ─────────────────────────────────────────────────
  function breakPrompt() {
    const pairs = (state.data.primary.combos.pairs || []).slice(0, 6);
    return `<div class="bps-empty"><b>先选一个目标</b>
      <p>目标可以是一个英雄，也可以是 2–3 个英雄的组合。选完会同时给出：KPL 历史上怎么应对、本队训练赛怎么应对、差在哪。</p>
      <div class="bps-faces-row" style="justify-content:center;margin-top:6px">
        ${pairs.map((row) => `<button type="button" class="bps-face" data-bps-quick-target="${esc(row.heroes.join(','))}">
          ${row.heroes.map((hero) => heroImg(hero)).join('')}<em>${num(row.games)} 局</em></button>`).join('')}
      </div></div>`;
  }

  function answerPanel(block, label, tone) {
    if (!block || !block.available) {
      return `<div class="bps-panel"><div class="bps-panel-head"><h3>${esc(label)}</h3></div>
        <div class="bps-panel-body"><div class="bps-empty"><b>没有可比较的样本</b>
          <p>${esc(block?.reason || '当前窗口里没有目标被拿到的记录。')}</p></div></div></div>`;
    }
    const answers = block.answers || [];
    const gap = !answers.length
      ? `<div class="bps-empty" style="margin:8px 0"><b>当前窗口没有被完整放出的局</b>
          <p>Ban 数据仍然有效：${num(block.banned?.games)} 次被 Ban（${rate(block.banned?.share)}）。换更长的窗口能看到历史应对。</p>
          <button type="button" class="bps-softbtn" data-bps-widen="365">放到近 365 天</button></div>`
      : '';
    return `<div class="bps-panel">
      <div class="bps-panel-head">
        <h3>${esc(label)} <small>${num(block.answerGames)} 局面对目标</small></h3>
        ${sampleBadge(block.sample)}
      </div>
      <div class="bps-panel-body" style="padding-top:4px">
        ${gap}
        ${answers.slice(0, 6).map((row) => `<div class="bps-answer-row">
          ${heroImg(row.hero)}
          <div class="bps-answer-main"><b>${esc(heroShort(row.hero))}</b>
            <small>${num(row.count)} 次 · 占 ${rate(row.share)}</small></div>
          ${viz.intervalDot(row.winRate, row.interval, {width: 118, height: 20})}
          <span class="bps-ar-wr">${rate(row.winRate)}</span>
        </div>`).join('') || '<p class="bps-note">没有可用的应对记录。</p>'}
      </div>
      <div class="bps-panel-body" style="border-top:1px solid var(--bps-line-soft);display:flex;gap:14px;align-items:center;flex-wrap:wrap">
        ${viz.handRing((block.banned?.hands || []).map((row) => ({...row, share: row.share})), {size: 150})}
        <div style="flex:1 1 180px;display:grid;gap:6px">
          <p class="bps-note">Ban 率 ${rate(block.banned?.share)} · 首轮 ${num(block.banned?.firstRound)} 次 / 次轮 ${num(block.banned?.secondRound)} 次</p>
          <p class="bps-note">被完整放出的 ${num(block.completed?.games)} 局，胜率 ${rate(block.completed?.winRate)}；被拆 ${num(block.broken?.games)} 局。</p>
        </div>
      </div>
    </div>`;
  }

  function targetPicker() {
    const open = state.targetOpen;
    const picked = state.target;
    if (open) {
      return `<div class="bps-target-open">${heroPicker(picked,
        {action: 'target', max: 3, placeholder: '选 1–3 个英雄作为目标'})}
        <div style="display:flex;justify-content:flex-end;margin-top:6px">
          <button type="button" class="bps-link" data-bps-target-toggle>收起英雄面板</button></div></div>`;
    }
    return `<div class="bps-target-collapsed">
      <span class="bps-console-label">研究对象</span>
      ${picked.length
        ? picked.map((hero) => `<span class="bps-picker-chip">${heroImg(hero)}<span>${esc(hero)}</span></span>`).join('')
        : '<span class="bps-sub">还没有目标：选 1–3 个英雄，看 KPL 与本队各自怎么应对</span>'}
      <button type="button" class="bps-softbtn" data-bps-target-toggle>${picked.length ? '改目标' : '选目标英雄'}</button>
    </div>`;
  }

  function breakSection() {
    const target = state.target;
    let body = '';
    if (!target.length) {
      body = breakPrompt();
    } else if (state.targetLoading && !state.targetData) {
      body = '<div class="bps-loading"><span class="bps-spinner"></span>正在比较 KPL 与本队的应对…</div>';
    } else if (state.targetError) {
      body = `<div class="bps-inline-error">${esc(state.targetError)}
        <button type="button" class="bps-softbtn" data-bps-target-retry>重试</button></div>`;
    } else if (state.targetData) {
      const block = state.targetData;
      const kpl = block.kpl;
      const own = block.own;
      const compare = block.compare || {};
      const hit = compare.hit || {};
      body = `<div class="bps-break-target">
        <div class="bps-break-strip">
          <div class="bps-break-stat"><span>被完整放出的局</span><b>${num(kpl.completed?.games)}</b>
            <small>胜率 ${rate(kpl.completed?.winRate)} · ${interval(kpl.completed?.interval)}</small></div>
          <div class="bps-break-stat"><span>被拆掉的局</span><b>${num(kpl.broken?.games)}</b>
            <small>占 ${rate(kpl.broken?.share)} · 对手 Ban 掉其中一半</small></div>
          <div class="bps-break-stat"><span>两边各拿一个</span><b>${num(kpl.split?.games)}</b>
            <small>全部被 Ban ${num(kpl.blocked?.games)} 局 · ${rate(kpl.blocked?.share)}</small></div>
        </div>
        <div class="bps-break-grid">
          ${answerPanel(kpl, `KPL 应对 · ${block.label}`, 'kpl')}
          ${answerPanel(own, `本队应对 · ${block.label}`, 'own')}
        </div>
        <div class="bps-hit" style="grid-template-columns:96px minmax(0,1fr)">
          ${viz.donut(hit.value, {label: '命中率', size: 96, stroke: 10})}
          <div class="bps-hit-copy">
            <b>本队应对里，${has(hit.value) ? rate(hit.value) : '—'} 落在 KPL 最常用的 8 个应对里</b>
            <p>${has(hit.value) ? `本队 ${num(hit.ownPicks)} 次应对；KPL 常用：${(hit.kplTop || []).map(esc).join('、') || '—'}。` : '本队还没有面对这个目标的训练赛样本，先积累再比较。'}
              Ban 率对比：KPL ${rate(compare.ban?.kplRate)} / 本队 ${rate(compare.ban?.ownRate)}
              （${has(compare.ban?.delta) ? `${signed(compare.ban.delta)} pp` : '—'}）。
              先验权重 KPL ${num(state.prior)}% / 训练赛 ${num(100 - state.prior)}%。</p>
            <div class="bps-blend" data-bps-blend>${blendPanel()}</div>
          </div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>同一目标，两边怎么选</h3>
            <span class="bps-sub">哑铃两端 = KPL 份额 / 本队份额</span></div>
          <div class="bps-panel-body">
            ${viz.dumbbell(compare.rows || [], {aKey: 'kplShare', bKey: 'ownShare', labelKey: 'hero', width: 760})}
          </div>
          <div class="bps-panel-body is-flush" style="border-top:1px solid var(--bps-line-soft)">
            <table class="bps-table">
              <thead><tr><th>应对英雄</th><th class="is-num">KPL 次数</th><th class="is-num">KPL 胜率</th>
                <th class="is-num">本队次数</th><th class="is-num">本队胜率</th><th class="is-num">份额差</th></tr></thead>
              <tbody>${(compare.rows || []).map((row) => `<tr class="${row.ownCount ? '' : 'is-miss'}">
                <td><span class="bps-face">${heroImg(row.hero)}<span>${esc(heroShort(row.hero))}</span>${row.inKplTop ? '<span class="bps-tag">KPL 前八</span>' : ''}</span></td>
                <td class="is-num">${num(row.kplCount)}</td>
                <td class="is-num">${rate(row.kplWinRate)}</td>
                <td class="is-num is-strong">${num(row.ownCount)}</td>
                <td class="is-num">${rate(row.ownWinRate)}</td>
                <td class="is-num">${deltaChip(row.deltaShare, {tone: 'neutral'})}</td>
              </tr>`).join('') || '<tr><td colspan="6" class="bps-note">还没有可比较的应对。</td></tr>'}</tbody>
            </table>
          </div>
        </div>
        ${(compare.missed || []).length ? `<div class="bps-panel"><div class="bps-panel-head"><h3>KPL 常用、本队还没用过</h3></div>
          <div class="bps-panel-body"><div class="bps-faces-row">${compare.missed.map((row) => heroFace(row.hero, {count: row.kplCount})).join('')}</div></div></div>` : ''}
      </div>`;
    }
    return `${section('break', '03', '战队如何破解', '目标被对面拿走，KPL 怎么应对，我们怎么应对？')}
      ${targetPicker()}
      <div style="margin-top:14px">${body}</div></section>`;
  }


  async function loadCompareOpponent() {
    if (!state.compareOpponent) { state.compareBlock = null; paint(); return; }
    state.compareLoading = true;
    paint();
    try {
      const search = new URLSearchParams({source: state.source,
        opponent: state.compareOpponent, recentDays: state.recentDays});
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      state.compareBlock = await api(`/opponent?${search.toString()}`);
    } catch (error) {
      state.compareBlock = {available: false, reason: error.message};
    } finally {
      state.compareLoading = false;
      paint();
    }
  }

  function comparePanel() {
    if (!state.compareOpponent || !state.compareBlock?.available) return '';
    const a = state.data?.opponentBlock;
    const b = state.compareBlock;
    if (!a?.available) return '';
    const metric = (key, label, value) => `<span class="bps-compare-metric" data-cmp-key="metric:${key}">
      <i>${label}</i><b>${value}</b></span>`;
    const column = (block, name, primary) => `<div class="bps-compare-col ${primary ? 'is-primary' : ''}">
      <div class="bps-compare-head">
        ${teamMark(name, 'is-lg')}
        <div><h4>${esc(name)}</h4>
          <p>${num(block.games)} 队-局</p></div>
      </div>
      <div class="bps-compare-metrics">
        ${metric('winRate', '胜率', rate(block.winRate))}
        ${metric('interval', '区间', interval(block.interval))}
        ${metric('games', '局数', num(block.games))}
      </div>
      <div class="bps-compare-scroll" data-cmp-scroll="${primary ? 'a' : 'b'}">
        <div class="bps-compare-chart" data-cmp-key="metric:ban">${viz.handHeatmap(block.banHands || [],
          {width: 430, leftWidth: 62, colWidth: 92, rowHeight: 30})}</div>
        <div class="bps-compare-lists">
          <div><h5>英雄池</h5>${(block.heroes || []).slice(0, 6).map((row) =>
            `<div class="bps-compare-row" data-cmp-key="hero:${esc(row.hero)}">${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b><em>${rate(row.winRate)}</em></div>`).join('')}</div>
          <div><h5>常用组合</h5>${(block.combos?.['2'] || []).slice(0, 5).map((row) =>
            `<div class="bps-compare-row" data-cmp-key="combo:${esc(row.heroes.join(','))}">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(heroShort(row.label))}</b><em>${rate(row.winRate)}</em></div>`).join('')}</div>
        </div>
      </div>
    </div>`;
    return `<div class="bps-panel bps-cmp" style="margin-bottom:16px">
      <div class="bps-panel-head"><h3>对手对比</h3>
        <span class="bps-sub">同一窗口 · 左右两列滚动联动，悬停同一指标会同时高亮</span>
        <button type="button" class="bps-link" data-bps-compare-clear>取消对比</button></div>
      <div class="bps-panel-body">
        <div class="bps-compare-grid">
          ${column(a, state.opponent === '__all__' ? '全部对手' : state.opponent, true)}
          ${column(b, state.compareOpponent, false)}
        </div>
      </div>
    </div>`;
  }

  function comparePanelPick() {
    const options = (state.data?.options?.teams || [])
      .filter((item) => item.name !== state.opponent && item.name !== state.team);
    return `<div class="bps-pop is-right" data-bps-pop-panel="compare" ${state.pop === 'compare' ? '' : 'hidden'}>
      <div class="bps-pop-head"><b>选择对比对手</b><span class="bps-sub">同一窗口下并排看</span></div>
      <div class="bps-team-grid">
        ${options.map((item) => `<button type="button" class="bps-team-option"
          data-bps-compare-opponent="${esc(item.name)}" aria-pressed="${state.compareOpponent === item.name}">
          ${teamMark(item.name)}<span><b>${esc(item.name)}</b><small>${esc(item.abbr || '')}</small></span>
        </button>`).join('')}
      </div>
      <div class="bps-pop-foot"><button type="button" class="bps-softbtn" data-bps-pop-close>收起</button></div>
    </div>`;
  }

  function sequencePanel() {
    const lanes = ['', ...LANES];
    const heroes = state.data?.options?.heroes || [];
    const laneHeroes = heroes.filter((row) => !state.seqLane || row.lane === state.seqLane);
    const maxHand = state.seqAction === 'pick' ? 5 : 4;
    const hand = Math.min(state.seqHand, maxHand);
    const data = state.seqData;
    return `<div class="bps-panel bps-seq">
      <div class="bps-panel-head"><h3>手序查询 · 第 N 手他在做什么</h3>
        <span class="bps-sub">先选队伍、动作、第几手；再加英雄就只看这一手</span>
        ${state.target.length === 1 && state.seqHero !== state.target[0]
          ? `<button type="button" class="bps-link" data-bps-seq-from-target>用 03 目标：${esc(state.target[0])}</button>` : ''}</div>
      <div class="bps-seq-controls">
        <span class="bps-console-label">队伍</span>${seg([['opponent', '对手'], ['own', '我们']], state.seqTeam, 'data-bps-seq-team', {small: true})}
        <span class="bps-console-label">动作</span>${seg([['pick', 'Pick'], ['ban', 'Ban']], state.seqAction, 'data-bps-seq-action', {small: true})}
        <span class="bps-console-label">第几手</span>${seg(Array.from({length: maxHand}, (_, index) => [String(index + 1), `${index + 1}`]), String(hand), 'data-bps-seq-hand', {small: true})}
        <span class="bps-console-label">英雄</span>
        <button type="button" class="bps-trigger is-small" data-bps-seq-toggle aria-expanded="${state.seqOpen}">
          ${state.seqHero ? `${heroImg(state.seqHero)}<span>${esc(state.seqHero)}</span>` : '全部英雄'}
          ${icon('chevron')}
        </button>
        ${state.seqHero ? '<button type="button" class="bps-link" data-bps-seq-clear>清空</button>' : ''}
      </div>
      ${state.seqOpen ? `<div class="bps-seq-picker">
        <div class="bps-chips">${lanes.map((lane) => `<button type="button" class="bps-chip"
          data-bps-seq-lane="${esc(lane)}" aria-pressed="${state.seqLane === lane}">${lane || '全部'}</button>`).join('')}</div>
        <div class="bps-seq-grid">${laneHeroes.map((row) => `<button type="button"
          class="bps-hero-btn ${state.seqHero === row.name ? 'is-on' : ''}"
          data-bps-seq-hero="${esc(row.name)}">${heroImg(row.name)}<span>${esc(heroShort(row.name))}</span></button>`).join('')}</div>
      </div>` : ''}
      ${state.seqLoading && !data ? '<div class="bps-loading">正在按手序取数…</div>' : ''}
      ${state.seqError ? `<div class="bps-inline-error">${esc(state.seqError)}</div>` : ''}
      ${data?.available ? `<div class="bps-seq-result">
        <div class="bps-seq-stats">
          <span><b>${num(data.games)}</b> 局</span>
          <span><b>${rate(data.winRate)}</b> 胜率</span>
          <span><b>${interval(data.interval)}</b> 区间</span>
          ${sampleBadge(data.sample)}
        </div>
        <div class="bps-seq-cols">
          <div><h4>这一手（${state.seqAction === 'pick' ? 'Pick' : 'Ban'}）${state.seqHero ? esc(state.seqHero) : '最常出现'}</h4>
            ${(data.ownAtHand || []).slice(0, 6).map((row) => `<div class="bps-seq-row">${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b><em>${num(row.count)}</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
          <div><h4>对面同一手</h4>
            ${(data.enemyAtHand || []).slice(0, 6).map((row) => `<div class="bps-seq-row">${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b><em>${num(row.count)}</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
          <div><h4>对面下一手</h4>
            ${(data.enemyNext || []).slice(0, 6).map((row) => `<div class="bps-seq-row">${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b><em>${num(row.count)}</em></div>`).join('') || '<p class="bps-note">—</p>'}
            <p class="bps-note" style="margin-top:6px">类型：${(data.enemyNextTypes || []).slice(0, 4).map((row) => `${esc(row.type)} ${num(row.count)}`).join(' · ') || '—'}</p>
          </div>
        </div>
      </div>` : (data && !data.available ? `<div class="bps-empty"><b>没有符合的对局</b><p>${esc(data.reason || '')}</p></div>` : '')}
    </div>`;
  }

  function opponentSection() {
    const block = state.data.opponentBlock;
    if (!state.opponent) {
      return `${section('opponent', '04', '对手 BP 情报', '他的 Ban 在想什么，第一手之后他会怎么走？')}
        <div class="bps-empty"><b>先选一个对手</b><p>在顶部“对手”里选；KPL 用联盟赛季数据，训练赛用营地对手名。</p></div></section>`;
    }
    if (!block || !block.available) {
      return `${section('opponent', '04', '对手 BP 情报', '他的 Ban 在想什么，第一手之后他会怎么走？')}
        <div class="bps-empty"><b>没有这个对手的记录</b><p>${esc(block?.reason || '')}</p></div></section>`;
    }
    const combos = block.combos?.[state.oppComboSize] || [];
    const intentRow = (row) => `<div class="bps-intent-row">
      ${heroImg(row.hero)}
      <div class="bps-intent-main"><b>${esc(heroShort(row.hero))}</b>
        <span class="bps-intent-tags">${(row.intents || []).map((tag) => `<span class="bps-tag ${tag.kind === '拆组合' ? '' : tag.kind === '版本热门' ? 'is-warm' : 'is-quiet'}" title="${esc(tag.detail || '')}">${esc(tag.kind)}</span>`).join('')}</span>
      </div>
      <span class="bps-ar-count"><b>${num(row.count)}</b><small>${rate(row.share)}</small></span>
    </div>`;
    return `${section('opponent', '04', '对手 BP 情报', '他的 Ban 在想什么，第一手之后他会怎么走？')}
      <div class="bps-opp-head">
        ${teamMark(state.opponent, 'is-lg')}
        <div class="bps-opp-id"><h3>${state.opponent === '__all__' ? '全部对手' : esc(state.opponent)}</h3>
          <p>${num(block.games)} 个队-局 · 可算手序 ${num(block.orderGames)} 局 · ${esc(block.sample || '')}</p></div>
        <span class="bps-compare-wrap" style="margin-left:auto">
          <button type="button" class="bps-softbtn" data-bps-pop="compare">
            ${state.compareOpponent ? `对比：${esc(state.compareOpponent)}` : '对比对手'} ${icon('chevron')}
          </button>
          ${comparePanelPick()}
        </span>
        <div class="bps-opp-facts">
          <div><span>胜率</span><b>${rate(block.winRate)}</b></div>
          <div><span>区间</span><b style="font-size:15px">${interval(block.interval)}</b></div>
          <div><span>首 Ban 种类</span><b>${num((block.firstBans || []).length)}</b></div>
        </div>
      </div>
      ${comparePanel()}
      ${sequencePanel()}
      <div class="bps-opp-grid">
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>第一手 Ban 与意图</h3><span class="bps-sub">一局可多标签</span></div>
          <div class="bps-panel-body" style="padding:6px 8px">${(block.firstBans || []).map(intentRow).join('') || '<p class="bps-note">没有逐手记录。</p>'}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>第 N 手 Ban 热力</h3><span class="bps-sub">颜色越深 = 越常在这个 Ban 位</span></div>
          <div class="bps-panel-body">${viz.handHeatmap(block.banHands || [])}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>我们第一手之后，他先拿什么</h3><span class="bps-sub">同局共现</span></div>
          <div class="bps-panel-body" style="padding:4px 10px">
            ${(block.responses || []).slice(0, 6).map((row) => `<div class="bps-response-row">
              <div class="bps-response-our">${heroImg(row.ourFirst)}<div><b>${esc(row.ourFirst)}</b><small>${num(row.games)} 局</small></div></div>
              <div class="bps-response-next">
                <div class="bps-response-line"><span>选</span>${(row.nextPicks || []).map((pick) => `<span class="bps-mini-face">${heroImg(pick.hero)}${esc(pick.hero)} · ${num(pick.count)}</span>`).join('') || '<span class="bps-sub">—</span>'}</div>
                <div class="bps-response-line"><span>Ban</span>${(row.nextBans || []).map((pick) => `<span class="bps-mini-face">${heroImg(pick.hero)}${esc(pick.hero)} · ${num(pick.count)}</span>`).join('') || '<span class="bps-sub">—</span>'}</div>
              </div>
            </div>`).join('') || '<p class="bps-note">样本不足 3 局。</p>'}
          </div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>他爱用的组合</h3>
            ${seg([['2', '双人'], ['3', '三人'], ['4', '四人']], state.oppComboSize, 'data-bps-opp-combo', {small: true})}</div>
          <div class="bps-panel-body" style="padding:4px 10px">
            ${combos.length ? combos.slice(0, 8).map((row) => `<div class="bps-opp-combo-row">
              <span class="bps-opp-combo-faces">${row.heroes.map((hero) => heroImg(hero)).join('')}</span>
              <span class="bps-opp-combo-name">${esc(heroShort(row.label))}</span>
              <span class="bps-opp-combo-num">${num(row.games)} 局</span>
              <span class="bps-opp-combo-wr">${rate(row.winRate)}</span>
              <span class="bps-badge ${row.relative == null ? 'is-low' : row.relative >= 0 ? 'is-good' : 'is-bad'}">${has(row.relative) ? `${signed(row.relative)} pp` : '—'}</span>
            </div>`).join('') : '<p class="bps-note">当前窗口没有组合记录。</p>'}
          </div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>他的英雄池 · Pick × 胜率</h3><span class="bps-sub">气泡 = Pick 次数</span></div>
          <div class="bps-panel-body">${viz.poolScatter(block.heroes, {width: 760, height: 360})}
            ${(() => {
              const pool = (block.heroes || []).filter((row) => (row.picks || 0) >= 2 && has(row.winRate));
              const strong = [...pool].filter((row) => row.winRate >= 55).sort((a, b) => b.picks - a.picks).slice(0, 3);
              const volume = [...pool].sort((a, b) => b.picks - a.picks).slice(0, 3);
              const weak = [...pool].filter((row) => row.winRate < 45).sort((a, b) => b.picks - a.picks).slice(0, 2);
              const line = (label, list) => list.length
                ? `<span><b>${label}</b>${list.map((row) => `${esc(heroShort(row.hero))} ${rate(row.winRate)}`).join('、')}</span>` : '';
              return `<div class="bps-pool-takeaway">${line('高胜率', strong)}${line('高出场', volume)}${line('低效', weak)}</div>`;
            })()}
          </div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>打他，什么有效</h3><span class="bps-sub">点 = 对手拿到该英雄时的胜率</span></div>
          <div class="bps-panel-body">
            ${viz.portraitQuadrant(block.counters || [], {width: 700, height: 320})}
          </div>
        </div>
      </div>
      <div class="bps-panel" style="margin-top:16px">
        <div class="bps-panel-head"><h3>输一局之后怎么调</h3><span class="bps-sub">同一系列赛的下一局</span></div>
        <div class="bps-panel-body"><div class="bps-serie">
          <div><span>输后下一局胜率</span><b>${rate(block.series?.afterLoss?.winRate)}</b><small>${num(block.series?.afterLoss?.games)} 个样本 · Ban 变化 ${rate(block.series?.afterLoss?.changeRate)}</small></div>
          <div><span>赢后下一局胜率</span><b>${rate(block.series?.afterWin?.winRate)}</b><small>${num(block.series?.afterWin?.games)} 个样本 · Ban 变化 ${rate(block.series?.afterWin?.changeRate)}</small></div>
        </div></div>
      </div>
      ${(block.caveats || []).length ? `<p class="bps-note" style="margin-top:10px">${block.caveats.map(esc).join(' ')}</p>` : ''}</section>`;
  }

  // ── 05 类型与手序 ───────────────────────────────────────────────────
  /* 克制冷热按“对面分路 / 我们分路”筛，矩阵会缩到 2–3 行 × 2–3 列。 */
  function counterMatrixHtml(t, laneOf) {
    const banMode = state.counterMode === 'ban';
    const counters = banMode ? t.banCounters : t.counters;
    if (!counters?.available) {
      return `<div class="bv-empty">${banMode
        ? '当前 Ban 手 / 窗口下没有足够样本，换个 Ban 手或放宽窗口。'
        : '当前窗口没有可比较的类型克制样本。'}</div>`;
    }
    const rowLane = state.counterRowLane;
    const colLane = state.counterColLane;
    let rowIdx = counters.rows.map((_, index) => index)
      .filter((index) => !rowLane || laneOf(counters.rows[index]) === rowLane);
    let colIdx = counters.cols.map((_, index) => index)
      .filter((index) => !colLane || laneOf(counters.cols[index]) === colLane);
    if (!rowIdx.length || !colIdx.length) {
      return '<div class="bv-empty">这个分路组合没有足够样本，换一边试试。</div>';
    }
    const sel = state.counterSel;
    if (sel) {
      rowIdx = rowIdx.slice(Math.max(0, sel.r0), Math.min(rowIdx.length - 1, sel.r1) + 1);
      colIdx = colIdx.slice(Math.max(0, sel.c0), Math.min(colIdx.length - 1, sel.c1) + 1);
    }
    const rows = rowIdx.map((index) => counters.rows[index]);
    const cols = colIdx.map((index) => counters.cols[index]);
    const matrix = rowIdx.map((ri) => colIdx.map((ci) => counters.matrix[ri][ci]));
    const best = (counters.best || []).filter((row) => rows.includes(row.enemy)
      && cols.includes(row.response));
    const cell = rows.length <= 2 && cols.length <= 3 ? 82 : rows.length <= 4 ? 66 : 54;
    return `${sel ? `<div class="bps-counter-sel">
        <span>已框选 ${rows.length} × ${cols.length}</span>
        <button type="button" class="bps-link" data-bps-counter-reset>重置矩阵</button>
      </div>` : '<div class="bps-counter-hint">在矩阵上拖一个方块，只看这几类对比（例如 3×2）</div>'}
      ${viz.typeCounterMatrix({rows, cols, matrix}, laneOf, {width: Math.max(520, 96 + cols.length * cell), cell})}
      ${best.length ? `<div class="bps-best-counters">${best.slice(0, 4).map((row) =>
        `<span class="bps-best-chip"><b>${esc(row.enemy)}</b> → ${esc(row.response)}
          <em>${rate(row.winRate)}</em><i class="${row.delta >= 0 ? 'is-good' : 'is-bad'}">${signed(row.delta)} pp</i></span>`).join('')}</div>` : ''}`;
  }

  function decisionTreeHtml() {
    const tree = state.tree;
    if (!tree?.available) {
      return `<div class="bps-empty"><b>还没有可展开的手序</b>
        <p>${esc(tree?.reason || '先选一个有已核验逐手记录的对手和窗口。')}</p></div>`;
    }
    const nodes = tree.nodes || [];
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const children = new Map();
    for (const node of nodes) {
      if (!children.has(node.parent)) children.set(node.parent, []);
      children.get(node.parent).push(node);
    }
    const path = state.decisionPath.map((id) => byId.get(id)).filter(Boolean);
    const parentKey = path.length ? path[path.length - 1].id : '0';
    const siblings = [...(children.get(parentKey) || [])]
      .sort((a, b) => (b.count - a.count) || String(a.hero).localeCompare(String(b.hero)));
    const next = siblings.slice(0, 3);
    const total = siblings.reduce((sum, node) => sum + node.count, 0) || 1;
    const last = path[path.length - 1];
    const crumb = [`<button type="button" class="bps-crumb ${path.length ? '' : 'is-on'}"
        data-bps-decision-back="0">BP 开始</button>`]
      .concat(path.map((node, index) => `<button type="button" class="bps-crumb ${index === path.length - 1 ? 'is-on' : ''}"
        data-bps-decision-back="${index + 1}">${esc(heroShort(node.hero))}<em>${node.count}</em></button>`))
      .join('<i>›</i>');
    if (!next.length) {
      return `<div class="bps-decision">
        <div class="bps-decision-path">${crumb}</div>
        <div class="bps-empty is-soft"><b>这条路径到头了</b>
          <p>当前选择之后没有更长的已核验样本；换一个分支或换窗口。</p>
          <button type="button" class="bps-softbtn" data-bps-decision-reset>回到起点</button></div>
      </div>`;
    }
    const cards = next.map((node) => {
      const share = node.count / total;
      const grand = [...(children.get(node.id) || [])]
        .sort((a, b) => b.count - a.count).slice(0, 3);
      const grandTotal = grand.reduce((sum, item) => sum + item.count, 0) || 1;
      return `<div class="bps-decision-card">
        <button type="button" class="bps-decision-main" data-bps-decision-pick="${esc(node.id)}">
          <span class="bps-decision-head">${heroImg(node.hero)}
            <span><b>${esc(heroShort(node.hero))}</b><small>${node.action === 'ban' ? 'BAN' : 'PICK'} · ${node.actor === 'team' ? '我方' : '对方'}</small></span>
            <em>${node.count} 局</em></span>
          <span class="bps-decision-label"><span>分支概率</span><b>${Math.round(share * 100)}%</b></span>
          <span class="bps-prob"><i style="width:${Math.round(share * 100)}%"></i></span>
          <span class="bps-decision-label"><span>这条路径胜率</span><b>${node.winRate == null ? '—' : `${fmt(node.winRate, 1)}%`}</b></span>
          <span class="bps-score"><i style="width:${node.winRate == null ? 0 : Math.round(node.winRate)}%"></i></span>
          <span class="bps-decision-next">${grand.length
            ? `预测下一手：${grand.map((item) => `${esc(heroShort(item.hero))} ${Math.round(item.count / grandTotal * 100)}%`).join(' · ')}`
            : '没有更长的样本'}</span>
        </button>
        <button type="button" class="bps-decision-pin" data-bps-decision-pin="${esc(node.id)}">固定这条对比</button>
      </div>`;
    }).join('');
    const pins = (state.decisionPins || []).map((ids, index) => {
      const route = ids.map((id) => byId.get(id)).filter(Boolean);
      if (!route.length) return '';
      const tail = route[route.length - 1];
      return `<span class="bps-decision-pinrow">
        <b>${route.map((node) => esc(heroShort(node.hero))).join(' → ')}</b>
        <em>${tail.count} 局 · 胜率 ${tail.winRate == null ? '—' : `${fmt(tail.winRate, 1)}%`}</em>
        <button type="button" data-bps-decision-unpin="${index}" aria-label="移除">×</button>
      </span>`;
    }).join('');
    return `<div class="bps-decision">
      <div class="bps-decision-path">${crumb}</div>
      <div class="bps-decision-caption">当前${last ? `在「${esc(heroShort(last.hero))}」之后` : '从第一手开始'}，
        按历史条件频率展开前 ${next.length} 个分支；条宽 = 分支概率，第二条 = 该路径胜率。</div>
      <div class="bps-decision-cands">${cards}</div>
      ${pins ? `<div class="bps-decision-pins"><span class="bps-console-label">固定对比</span>${pins}</div>` : ''}
    </div>`;
  }

  function draftTreePanel() {
    return `<div class="bps-panel is-wide bps-tree-panel" data-bps-tree>
      <div class="bps-panel-head"><h3>BP 时序分支</h3>
        <span class="bps-sub">同一手同一英雄合并；线宽 = 局数；只认已核验手序</span></div>
      <div class="bps-panel-body">
        <div class="bps-tree-tools">
          <span class="bps-console-label">视图</span>${seg([['flow', '历史路径'], ['decision', '决策树']],
            state.treeMode, 'data-bps-tree-mode', {small: true})}
          ${state.treeMode === 'flow' ? `<span class="bps-console-label">深度</span>${seg([[6, '前 6 手'], [10, '前 10 手'], [20, '全 20 手']],
            String(state.treeDepth), 'data-bps-tree-depth', {small: true})}
          <span class="bps-console-label">分叉</span>${seg([[2, '2 支'], [3, '3 支']],
            String(state.treeBranch), 'data-bps-tree-branch', {small: true})}` : ''}
          <span class="bps-console-label">看</span>${seg([['opponent', '对手'], ['own', '我们']],
            state.typeSide, 'data-bps-tree-side', {small: true})}
          <span class="bps-console-label">阵营</span>${seg([['', '自动'], ['1', '蓝方'], ['2', '红方']],
            state.treeSide, 'data-bps-tree-camp', {small: true})}
          ${state.tree?.available
            ? `<span class="bps-sub">已核验 ${num(state.tree.games)} / ${num(state.tree.total)} 局
              ${state.tree.sideCounts ? `· 蓝 ${num(state.tree.sideCounts['1'] || 0)} / 红 ${num(state.tree.sideCounts['2'] || 0)}` : ''}</span>` : ''}
        </div>
        ${state.treeMode === 'decision' ? decisionTreeHtml() : `
        ${state.treeLoading && !state.tree ? '<div class="bps-loading">正在按逐手事件建树…</div>' : ''}
        ${state.treeError ? `<div class="bps-inline-error">${esc(state.treeError)}</div>` : ''}
        ${state.tree?.available && state.tree.games < 8
          ? '<p class="bps-note">已核验手序不到 8 局，整张图只作方向参考，不当作稳定习惯。</p>' : ''}
        ${state.tree?.available && state.treeDepth >= 20
          ? '<p class="bps-note">20 手较宽，图内可左右滚动看完整路径。</p>' : ''}
        ${state.tree?.available ? `<div class="bps-tree-scroll">${viz.draftFlowMap(state.tree, {width: 1080, height: 480})}</div>
          <div class="bps-tree-key">
            <span><i class="is-own-pick"></i>我方 Pick</span>
            <span><i class="is-own-ban"></i>我方 Ban</span>
            <span><i class="is-foe-pick"></i>对方 Pick</span>
            <span><i class="is-foe-ban"></i>对方 Ban</span>
            <span class="is-note">线宽 = 局数；同一手同一英雄合并成一个节点</span>
          </div>`
          : (state.tree ? `<div class="bps-empty"><b>还没有可画的手序</b>
              <p>${esc(state.tree.reason || '')}</p></div>` : '')}`}
      </div>
    </div>`;
  }

  function typesSection() {
    const head = section('types', '05', '类型与手序',
      '他第一手 Ban / 选的是什么类型？放到 BO 和时间里还成立吗？',
      '类型 × 手序 × 赛制 × 核数');
    if (state.typesLoading && !state.types) {
      return `${head}<div class="bps-loading"><span class="bps-spinner"></span>正在按类型拆 Ban / Pick…</div></section>`;
    }
    if (state.typesError && !state.types) {
      return `${head}<div class="bps-inline-error">${esc(state.typesError)}
        <button type="button" class="bps-softbtn" data-bps-types-retry>重试</button></div></section>`;
    }
    const t = state.types;
    if (!t) return `${head}</section>`;
    const sides = state.source === 'scrim'
      ? [['own', '我们'], ['opponent', '对手'], ['kpl', 'KPL']]
      : [['opponent', '对手'], ['league', '联盟']];
    const side = sides.some(([value]) => value === state.typeSide) ? state.typeSide : sides[0][0];
    const profile = side === 'kpl' ? state.kplTypes?.leagueProfile
      : side === 'league' ? t.leagueProfile
        : side === 'own' ? t.ownProfile : t.opponentProfile;
    const groups = t.taxonomy?.groups || {};
    const typeRows = Object.values(groups).flat();
    const laneOf = (type) => Object.keys(groups).find((lane) => groups[lane].includes(type)) || '';
    const boOptions = [['0', '全部'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']]
      .filter(([value]) => value === '0' || (t.bo?.available || []).includes(Number(value)));
    const handOptions = [['0', '全部'], ['1', '第1手'], ['2', '第2手'], ['3', '第3手'], ['4', '第4手']];
    const coreOptions = [['0', '全部'], ['2', '2核'], ['3', '3核'], ['4', '4核']];
    const focus = state.typeFocus;
    const tools = `<div class="bps-types-tools">
      <span class="bps-console-label">对象</span>${seg(sides, side, 'data-bps-type-side', {small: true})}
      <span class="bps-console-label">赛制</span>${seg(boOptions, String(state.typeBo), 'data-bps-type-bo', {small: true})}
      <span class="bps-console-label">Ban 手</span>${seg(handOptions, String(state.typeHand), 'data-bps-type-hand', {small: true})}
      <span class="bps-console-label">核数</span>${seg(coreOptions, String(state.typeCore), 'data-bps-type-core', {small: true})}
      ${focus ? `<button type="button" class="bps-chip is-focus" data-bps-type-focus="">
        已聚焦 ${esc(focus)} <em>×</em></button>` : '<span class="bps-sub">点图里的类型可以跨图聚焦</span>'}
    </div>`;
    if (!profile) {
      return `${head}${tools}<div class="bps-empty"><b>当前窗口没有可拆的 BP 记录</b>
        <p>换窗口、换对象，或先积累样本。</p></div></section>`;
    }
    const laneOptions = [['', '全部'], ...Object.keys(groups).map((lane) => [lane, lane])
      .map(([value, label]) => [value, label.slice(0, 2) === '对抗' ? '对抗' : label.replace('路', '')])];
    /* Ban 手筛选只作用于克制矩阵（对面 Ban 模式）；上面两张 Ban 图始终看全量手序。 */
    const banFull = profile.banFull || profile.ban || {};
    const hands = banFull.handRows || [];
    const slots = profile.pick?.slotRows || [];
    const cores = profile.cores?.rows || [];
    const handCols = hands.map((hand) => ({label: `第${hand.hand}手`, sub: `${hand.games} 局`}));
    const handCells = typeRows.map((type) => hands.map((hand) =>
      (hand.types.find((row) => row.type === type) || {}).share || 0));
    const banTypes = typeRows.map((type) => ({
      type,
      total: hands.reduce((sum, hand) => sum + ((hand.types.find((row) => row.type === type) || {}).share || 0), 0),
    })).sort((a, b) => b.total - a.total).slice(0, 6);
    const banSeries = banTypes.map(({type}) => ({
      label: type,
      color: viz.LANE_COLOR[laneOf(type)] || '#246b63',
      values: hands.map((hand) => (hand.types.find((row) => row.type === type) || {}).share || 0),
    }));
    const pickTypes = typeRows.map((type) => ({
      type,
      total: slots.reduce((sum, slot) => sum + ((slot.types.find((row) => row.type === type) || {}).share || 0), 0),
    })).sort((a, b) => b.total - a.total).slice(0, 6);
    const pickSeries = pickTypes.map(({type}) => ({
      label: type,
      color: viz.LANE_COLOR[laneOf(type)] || '#246b63',
      values: slots.map((slot) => (slot.types.find((row) => row.type === type) || {}).share || 0),
    }));
    const compactText = state.compact ? `<div class="bps-compact-summary">
      <span><b>第一手 Ban</b>：${(banFull.firstTypes || []).slice(0, 4).map((row) => `${row.type} ${rate(row.share)}`).join('、') || '—'}</span>
      <span><b>核数</b>：${(cores || []).map((row) => `${row.cores}核 ${rate(row.share)} / 胜率 ${rate(row.winRate)}`).join(' · ') || '—'}</span>
      <span><b>克制</b>：${(t.counters?.best || []).slice(0, 3).map((row) => `${row.enemy}→${row.response} ${rate(row.winRate)}`).join('；') || '—'}</span>
    </div>` : '';
    return `${head}${tools}${compactText}
      ${draftTreePanel()}
      <div class="bps-type-grid">
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>第一手 Ban 的类型</h3><span class="bps-sub">${num(banFull.games || 0)} 局</span></div>
          <div class="bps-panel-body">${viz.typeRank(banFull.firstTypes || [], laneOf, {width: 460, focus})}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>Ban 手序 × 类型</h3><span class="bps-sub">同一类型在第 1–4 手 Ban 的份额</span></div>
          <div class="bps-panel-body">${viz.typeLines(banSeries,
            {width: 520, height: 280, xLabels: hands.map((hand) => `第${hand.hand}手`), focus})}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>Pick 位次 × 类型</h3><span class="bps-sub">同一类型在第 1–5 手的份额</span></div>
          <div class="bps-panel-body">${viz.typeLines(pickSeries,
            {width: 520, height: 280, xLabels: slots.map((slot) => `${slot.slot} 手`), focus})}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>阵容核数</h3><span class="bps-sub">横轴核数 · 纵轴胜率 · 点大小 = 局数</span></div>
          <div class="bps-panel-body">${viz.coreDots(cores, {width: 460, height: 260})}</div>
        </div>
        <div class="bps-panel is-wide">
          <div class="bps-panel-head"><h3>类型克制矩阵</h3><span class="bps-sub">${state.counterMode === 'ban'
            ? `对面 Ban 手${state.typeHand ? `（第 ${state.typeHand} 手）` : '（全部）'} 的类型 × 我们出的类型`
            : '对面拿到的类型 × 我们出的类型'} · 拖方块只看选中范围</span></div>
          <div class="bps-counter-tools">
            ${seg([['pick', '对面 Pick'], ['ban', '对面 Ban']], state.counterMode, 'data-bps-counter-mode', {small: true})}
            <span class="bps-console-label">对面</span>${seg(laneOptions, state.counterRowLane, 'data-bps-counter-row', {small: true})}
            <span class="bps-console-label">我们</span>${seg(laneOptions, state.counterColLane, 'data-bps-counter-col', {small: true})}
          </div>
          <div class="bps-panel-body">${counterMatrixHtml(t, laneOf)}</div>
        </div>
      </div>
      ${t.conditional?.available ? `<div class="bps-panel" style="margin-top:14px">
        <div class="bps-panel-head"><h3>对面拿到 ${esc((t.conditional.targets || []).join(' + '))} 时</h3>
          <span class="bps-sub">${num(t.conditional.games)} 局 · 两边第一手出什么类型</span></div>
        <div class="bps-panel-body bps-type-cond">
          <div><h4>我们第一手</h4>${viz.typeRank(t.conditional.ownFirstTypes || [], laneOf, {width: 420})}</div>
          <div><h4>对手第一手</h4>${viz.typeRank(t.conditional.enemyFirstTypes || [], laneOf, {width: 420})}</div>
        </div>
      </div>` : ''}
      <p class="bps-note" style="margin-top:10px">类型 = 五路 12 类；核数口径：战边/刺野/战野/法核/射手算核，坦边/坦野/工具人/辅助不算，战野按“可转肉”先计一核。Ban 手只影响 Ban 侧统计，Pick 位次图始终看 1–5 手。</p></section>`;
  }

  // ── 05 体系与异动 ───────────────────────────────────────────────────
  function systemsSection() {
    const data = state.data;
    const systems = data.primary.systems;
    const rows = systems.rows || [];
    const diff = systems.diff || [];
    const anomalies = data.primary.anomalies;
    return `${section('systems', '06', '体系与异动', '双方爱打什么体系，最近谁在变？')}
      <div class="bps-opp-grid">
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>体系雷达</h3><span class="bps-sub">实线 = 本队，虚线 = 对手</span></div>
          <div class="bps-panel-body">${viz.radar(diff, {aKey: 'ownPickRate', bKey: 'enemyPickRate', labelKey: 'system', width: 470, height: 420, aLabel: '本队', bLabel: state.opponent || '对手'})}</div>
        </div>
        <div class="bps-panel">
          <div class="bps-panel-head"><h3>${state.source === 'scrim' ? '本队英雄异动' : '联盟英雄异动'}</h3>
            <span class="bps-sub">斜率 = 当前窗口 → 上一窗口</span></div>
          <div class="bps-panel-body">
            ${anomalies?.available ? `<div class="bps-anomaly-grid">${anomalies.rows.map((row) => {
              const key = row.kind === '胜率' ? 'winRate' : row.kind === 'Ban 率' ? 'banRate' : 'pickRate';
              return `<div class="bps-anomaly">
                <div class="bps-anomaly-top">${heroImg(row.hero)}<div><b>${esc(heroShort(row.hero))}</b><small>${esc(row.lane || '')} · ${esc(row.kind)}变化</small></div></div>
                <div class="bps-anomaly-body">
                  <div class="bps-num">${rate(row.current[key])}<small>上一窗口 ${rate(row.previous[key])}</small></div>
                  ${deltaChip(row.kind === '胜率' ? row.delta.win : row.kind === 'Ban 率' ? row.delta.ban : row.delta.pick, {tone: row.kind === '胜率' ? 'good' : 'neutral'})}
                </div>
                ${viz.miniDelta(row.previous[key], row.current[key], {width: 240, height: 30})}
              </div>`;
            }).join('')}</div>` : `<div class="bps-empty"><b>没有明显的窗口异动</b><p>${esc(anomalies?.reason || '变化幅度都在 5 个百分点以内。')}</p></div>`}
          </div>
        </div>
      </div>
      <div class="bps-panel" style="margin-top:16px">
        <div class="bps-panel-head"><h3>阵容差异</h3><span class="bps-sub">本队 vs ${esc(state.opponent || '对手')} 的双人组合</span></div>
        <div class="bps-panel-body">
          ${data.lineupDiff?.available ? `<div class="bps-diff-grid">
            <div class="bps-diff-col"><h4>两边都在用</h4>${(data.lineupDiff.shared || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>${num(row.ownGames)} / ${num(row.enemyGames)}</em></div>`).join('') || '<p class="bps-note">没有交集。</p>'}</div>
            <div class="bps-diff-col"><h4>只有本队在用</h4>${(data.lineupDiff.onlyUs || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>${num(row.games)} 局</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
            <div class="bps-diff-col"><h4>只有对手在用</h4>${(data.lineupDiff.onlyThem || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>${num(row.games)} 局</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
          </div>` : '<div class="bps-empty"><b>还没有可对比的阵容</b><p>需要本队训练赛与对手同窗口的记录。</p></div>'}
        </div>
      </div></section>`;
  }

  // ── 06 赛前方案 ─────────────────────────────────────────────────────
  function planSection() {
    const plan = state.data.plan;
    if (!plan?.available) {
      return `${section('plan', '07', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？')}
        <div class="bps-empty"><b>${esc(plan?.reason || '先选一个对手')}</b>
          <p>方案只按历史证据准备：对手常拿什么、我们 Ban 谁、被 Ban 之后本队第一手怎么接。</p></div></section>`;
    }
    const banItem = (row) => `<div class="bps-plan-item">${heroImg(row.hero)}
      <div><b>${esc(heroShort(row.hero))}</b><small>${esc(row.reason || '')}</small></div>
      <em>${rate(row.ourWinRate)}</em></div>`;
    const branch = (row) => `<div class="bps-plan-item">
      <div><b>对手 Ban ${esc(row.ban)}</b><small>${num(row.games)} 局</small></div>
      <em>${esc((row.options || []).map((option) => `${option.hero} ${num(option.count)}`).join(' / '))}</em></div>`;
    const system = (row) => `<div class="bps-plan-item">
      <div><b>${esc(heroShort(row.label))}</b><small>${num(row.games)} 局 · 基准 ${has(row.relative) ? `${signed(row.relative)} pp` : '—'}</small></div>
      <em>${rate(row.winRate)}</em></div>`;
    return `${section('plan', '07', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？')}
      <div class="bps-plan-grid">
        <div class="bps-plan-col"><h4>优先 Ban</h4>
          ${(plan.banPriority || []).map(banItem).join('') || '<p class="bps-note">对手样本不足。</p>'}</div>
        <div class="bps-plan-col"><h4>对手 Ban 之后我们接什么</h4>
          ${(plan.branches || []).map(branch).join('') || '<p class="bps-note">还没有足够的 Ban 后样本。</p>'}</div>
        <div class="bps-plan-col"><h4>本队体系与威胁</h4>
          ${(plan.ourSystems || []).map(system).join('') || '<p class="bps-note">本队体系样本不足。</p>'}
          ${(plan.threats || []).length ? `<p class="bps-note" style="margin-top:10px">对手常用：${plan.threats.map((row) => esc(heroShort(row.label))).join('、')}</p>` : ''}</div>
      </div>
      <p class="bps-note" style="margin-top:10px">${(plan.caveats || []).map(esc).join(' ')}</p></section>`;
  }

  // ── 组装 ────────────────────────────────────────────────────────────
  function skeleton() {
    return `<div class="bps">
      <header class="bps-hero" style="display:block;min-height:150px"></header>
      <div class="bps-skeleton">
        <div class="bps-sk" style="height:64px"></div>
        <div class="bps-sk" style="height:220px"></div>
        <div class="bps-sk" style="height:160px"></div>
      </div>
    </div>`;
  }

  function errorState() {
    return `<div class="bps"><div class="bps-empty" style="margin-top:40px">
      <b>BP 数据暂时读不到</b><p>${esc(state.error)}</p>
      <button type="button" class="bps-primary" data-bps-refresh>重新读取</button></div></div>`;
  }

  function paint() {
    if (!state.root || state.disposed) return;
    const y = window.scrollY;
    if (state.loading && !state.data) state.root.innerHTML = skeleton();
    else if (state.error && !state.data) state.root.innerHTML = errorState();
    else if (!state.data) state.root.innerHTML = skeleton();
    else {
      const visible = state.solo ? [state.active] : SECTION_LIST.map(([key]) => key);
      state.root.innerHTML = `<div class="bps ${state.compact ? 'is-compact' : ''}">
        ${heroBand()}
        <div class="bps-sticky">
          ${consoleBar()}
          ${jumpBar()}
        </div>
        ${pinsBar()}
        ${sampleBanner()}
        <div class="bps-sections">
          ${visible.map((key) => SECTION_RENDER[key]()).join('')}
        </div>
        <div class="bps-caveats">${(state.data.caveats || []).map((text) => `<p class="bps-note">· ${esc(text)}</p>`).join('')}</div>
        <button type="button" class="bps-top" data-bps-top hidden aria-label="回到顶部">${icon('arrow')}</button>
      </div>`;
    }
    if (y > 0) window.scrollTo(0, y);
    applyZoom();
    decorateSections();
    observeLazy();
    updateActiveJump();
    requestAnimationFrame(syncSticky);
    // 单节模式直接进入 05 时，主图在首屏下方，不能等滚动才请求。
    if (state.solo && state.active === 'types' && state.data
      && state.treeStale && !state.treeLoading) {
      setTimeout(() => {
        if (state.treeStale && !state.treeLoading) loadTree();
      }, 60);
    }
  }

  let lazyObserver = null;
  function observeLazy() {
    if (!state.root) return;
    if (!lazyObserver) {
      lazyObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const key = entry.target.dataset.bpsLazy;
          if (key === 'types' && state.typesStale && !state.typesLoading) loadTypes();
          else if (key === 'tree' && state.treeStale && !state.treeLoading) loadTree();
          else if (key === 'sequence' && state.seqStale && !state.seqLoading) loadSequence();
        }
      }, {rootMargin: '600px 0px'});
    }
    lazyObserver.disconnect();
    const types = state.root.querySelector('[data-bps-section="types"]');
    if (types && state.typesStale && !state.collapsed.types) {
      types.dataset.bpsLazy = 'types';
      lazyObserver.observe(types);
    }
    const tree = state.root.querySelector('[data-bps-tree]');
    if (tree && state.treeStale && !state.treeLoading) {
      tree.dataset.bpsLazy = 'tree';
      lazyObserver.observe(tree);
    }
    const seq = state.root.querySelector('.bps-seq');
    if (seq && state.seqStale) {
      seq.dataset.bpsLazy = 'sequence';
      lazyObserver.observe(seq);
    }
  }

  const SECTION_RENDER = {
    heroes: () => heroSection(), combos: () => comboSection(), break: () => breakSection(),
    opponent: () => opponentSection(), types: () => typesSection(),
    systems: () => systemsSection(), plan: () => planSection(),
  };
  let sectionFrame = 0;

  function refreshSection(key) {
    const render = SECTION_RENDER[key];
    const current = state.root?.querySelector(`[data-bps-section="${key}"]`);
    if (!render || !current) { paint(); return; }
    cancelAnimationFrame(sectionFrame);
    sectionFrame = requestAnimationFrame(() => {
      const holder = document.createElement('div');
      holder.innerHTML = render();
      const next = holder.firstElementChild;
      if (!next) return;
      current.replaceWith(next);
      decorateSections();
      applyZoom();
      observeLazy();
      updateActiveJump();
    });
  }

  /* ── 悬浮卡 ───────────────────────────────────────────────────────── */
  let hoverNode = null;
  function ensureHoverCard() {
    if (hoverNode) return hoverNode;
    hoverNode = document.createElement('div');
    hoverNode.className = 'bps-hover-card';
    hoverNode.hidden = true;
    document.body.appendChild(hoverNode);
    return hoverNode;
  }

  function heroRow(hero) {
    return (state.data?.primary?.heroes?.rows || []).find((row) => row.hero === hero) || null;
  }

  function showHover(hero, anchor) {
    const row = heroRow(hero);
    const card = ensureHoverCard();
    if (!row) { card.hidden = true; return; }
    card.innerHTML = `<div class="bps-hover-head">${portrait(hero, 'bps-hover-img')}
        <div><b>${esc(heroShort(hero))}</b><small>${esc(row.lane || '')} · ${esc(row.signal || '')}</small></div></div>
      <div class="bps-hover-metrics">
        <span><i>Pick</i><b>${rate(row.pickRate)}</b></span>
        <span><i>Ban</i><b>${rate(row.banRate)}</b></span>
        <span><i>胜率</i><b>${rate(row.winRate)}</b></span>
      </div>
      <div class="bps-hover-deltas">Ban ${deltaChip(row.delta?.ban, {tone: 'neutral'})} · 胜率 ${deltaChip(row.delta?.win)}</div>
      <div class="bps-hover-spark">${viz.spark(row.spark, {key: 'pickRate', w: 200, h: 30})}</div>
      <div class="bps-hover-foot">区间 ${interval(row.interval)} · 点击可送到 03 破解</div>`;
    card.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const width = 228;
    let left = rect.right + 12;
    if (left + width > window.innerWidth - 12) left = rect.left - width - 12;
    left = Math.max(12, left);
    let top = rect.top - 6;
    const height = card.offsetHeight || 190;
    if (top + height > window.innerHeight - 12) top = window.innerHeight - height - 12;
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(Math.max(12, top))}px`;
  }

  /* 每个分区右上角加“收起”，长页面可以只留要看的几节。 */
  function decorateSections() {
    state.root.querySelectorAll('[data-bps-section]').forEach((sec) => {
      const key = sec.dataset.bpsSection;
      const head = sec.querySelector('.bps-section-head');
      if (head && !head.querySelector('.bps-export')) {
        const group = document.createElement('span');
        group.className = 'bps-export';
        group.innerHTML = `<button type="button" data-bps-export-png="${key}" title="导出本节 PNG">PNG</button>
          <button type="button" data-bps-export-csv="${key}" title="导出本节 CSV">CSV</button>`;
        head.appendChild(group);
      }
      if (head && !head.querySelector('.bps-collapse')) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'bps-collapse';
        button.dataset.bpsCollapse = key;
        button.setAttribute('aria-label', '收起或展开这一节');
        button.innerHTML = icon('chevron');
        head.appendChild(button);
      }
      sec.classList.toggle('is-collapsed', Boolean(state.collapsed[key]));
    });
  }

  function closePops(except = '') {
    state.pop = except;
    if (!state.root) return;
    state.root.querySelectorAll('[data-bps-pop-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.bpsPopPanel !== except;
    });
    state.root.querySelectorAll('[data-bps-pop]').forEach((button) => {
      button.setAttribute('aria-expanded', String(button.dataset.bpsPop === except));
    });
  }

  function updateActiveJump() {
    if (!state.root) return;
    const sections = [...state.root.querySelectorAll('[data-bps-section]')];
    if (!sections.length) return;
    const stickyH = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--bps-sticky-h')) || 120;
    const mark = window.scrollY + stickyH + 20;
    let active = sections[0].dataset.bpsSection;
    if (!state.solo) {
      for (const item of sections) {
        if (item.offsetTop <= mark) active = item.dataset.bpsSection;
      }
      state.active = active;
    } else {
      active = state.active;
    }
    state.root.querySelectorAll('[data-bps-jump]').forEach((link) => {
      link.classList.toggle('is-active', link.dataset.bpsJump === active);
      link.setAttribute('aria-pressed', String(link.dataset.bpsJump === active));
    });
    const topButton = state.root.querySelector('[data-bps-top]');
    if (topButton) topButton.hidden = window.scrollY < 600;
  }

  function filterPicker(action, text) {
    const picker = state.root?.querySelector(`[data-bps-picker="${action}"]`);
    if (!picker) return;
    const query = String(text || '').trim();
    picker.querySelectorAll('[data-bps-hero-name]').forEach((button) => {
      button.hidden = Boolean(query) && !button.dataset.bpsHeroName.includes(query);
    });
    picker.querySelectorAll('[data-lane-group]').forEach((group) => {
      let next = group.nextElementSibling;
      let any = false;
      while (next && !next.dataset.laneGroup) {
        if (!next.hidden) any = true;
        next = next.nextElementSibling;
      }
      group.style.display = any ? 'flex' : 'none';
    });
  }

  // ── 事件 ────────────────────────────────────────────────────────────
  function scrollToSection(id) {
    if (state.solo) {
      state.active = id;
      state.collapsed[id] = false;
      persist();
      paint();
      window.scrollTo({top: 0, behavior: 'smooth'});
      return;
    }
    const target = state.root?.querySelector(`#bps-${id}`);
    if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function onPick(action, hero) {
    const list = action === 'combo' ? state.comboPick : state.target;
    const index = list.indexOf(hero);
    if (index >= 0) list.splice(index, 1);
    else if (list.length < 3) list.push(hero);
    else { list.shift(); list.push(hero); }
    persist();
    paint();
    if (action === 'target') { queueTarget(); loadTypes(); }
    else if (state.comboPick.length >= 2) queueCombo();
    else state.comboDetail = null;
  }

  /* 矩阵拖选：在 12×12 上拖一个方块，直接缩成 3×2 / 5×5 这种对比。 */
  let matrixDrag = null;

  function matrixCellAt(svg, clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const left = Number(svg.dataset.left);
    const top = Number(svg.dataset.top);
    const cell = Number(svg.dataset.cell);
    const rows = Number(svg.dataset.rows);
    const cols = Number(svg.dataset.cols);
    if (!rect.width || !cell) return null;
    const x = (clientX - rect.left) / rect.width * vb.width;
    const y = (clientY - rect.top) / rect.height * vb.height;
    const c = Math.floor((x - left) / cell);
    const r = Math.floor((y - top) / cell);
    if (c < 0 || r < 0 || c >= cols || r >= rows) return null;
    return {r, c};
  }

  function drawMatrixBrush() {
    if (!matrixDrag) return;
    const {svg, r0, c0, r1, c1} = matrixDrag;
    const left = Number(svg.dataset.left);
    const top = Number(svg.dataset.top);
    const cell = Number(svg.dataset.cell);
    let brush = svg.querySelector('.bv-brush');
    if (!brush) {
      brush = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      brush.setAttribute('class', 'bv-brush');
      svg.appendChild(brush);
    }
    const x = left + Math.min(c0, c1) * cell;
    const y = top + Math.min(r0, r1) * cell;
    brush.setAttribute('x', x + 1);
    brush.setAttribute('y', y + 1);
    brush.setAttribute('width', (Math.abs(c1 - c0) + 1) * cell - 4);
    brush.setAttribute('height', (Math.abs(r1 - r0) + 1) * cell - 4);
    brush.setAttribute('rx', 8);
  }

  function matrixPointerDown(event) {
    const svg = event.target.closest('.bv-matrix');
    if (!svg || event.button !== 0) return;
    const pos = matrixCellAt(svg, event.clientX, event.clientY);
    if (!pos) return;
    matrixDrag = {svg, r0: pos.r, c0: pos.c, r1: pos.r, c1: pos.c};
    drawMatrixBrush();
    svg.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function matrixPointerMove(event) {
    if (!matrixDrag) return;
    const pos = matrixCellAt(matrixDrag.svg, event.clientX, event.clientY);
    if (!pos) return;
    matrixDrag.r1 = pos.r;
    matrixDrag.c1 = pos.c;
    drawMatrixBrush();
  }

  function matrixPointerUp() {
    if (!matrixDrag) return;
    const {r0, c0, r1, c1} = matrixDrag;
    state.counterSel = {
      r0: Math.min(r0, r1), r1: Math.max(r0, r1),
      c0: Math.min(c0, c1), c1: Math.max(c0, c1),
    };
    matrixDrag = null;
    paint();
  }

  function togglePin(spec) {
    const [kind, value] = String(spec).split(':');
    if (!value) return;
    const list = kind === 'combo' ? state.pins.combos : state.pins.heroes;
    const index = list.indexOf(value);
    if (index >= 0) list.splice(index, 1);
    else list.unshift(value);
    persist();
    paint();
  }

  const pinStar = (spec) => {
    const [kind, value] = String(spec).split(':');
    const list = kind === 'combo' ? state.pins.combos : state.pins.heroes;
    const on = list.includes(value);
    return `<span class="bps-pin ${on ? 'is-on' : ''}" data-bps-pin="${esc(spec)}"
      role="button" title="${on ? '取消关注' : '加入我的关注'}">${on ? '★' : '☆'}</span>`;
  };

  /* ── 导出 ─────────────────────────────────────────────────────────── */
  function csvRows(key) {
    const data = state.data;
    if (!data) return null;
    const rows = [];
    if (key === 'heroes') {
      rows.push(['英雄', '分路', 'Pick率', 'Ban率', '胜率', '区间', 'Ban环比', '胜率环比']);
      for (const row of data.primary.heroes.rows) {
        rows.push([row.hero, row.lane, row.pickRate, row.banRate, row.winRate,
          interval(row.interval), row.delta?.ban, row.delta?.win]);
      }
    } else if (key === 'combos') {
      rows.push(['组合', '局数', '使用率', '胜率', '区间', '基准', '环比']);
      for (const row of [...(data.primary.combos.pairs || []), ...(data.primary.combos.size3 || [])]) {
        rows.push([row.label, row.games, row.share, row.winRate, interval(row.interval), row.relative, row.deltaWin]);
      }
    } else if (key === 'break') {
      rows.push(['应对英雄', 'KPL次数', 'KPL胜率', '本队次数', '本队胜率', '份额差']);
      for (const row of state.targetData?.compare?.rows || []) {
        rows.push([row.hero, row.kplCount, row.kplWinRate, row.ownCount, row.ownWinRate, row.deltaShare]);
      }
    } else if (key === 'opponent') {
      rows.push(['第一手Ban', '次数', '占比', '意图']);
      for (const row of data.opponentBlock?.firstBans || []) {
        rows.push([row.hero, row.count, row.share, (row.intents || []).map((tag) => tag.kind).join('/')]);
      }
    } else if (key === 'types') {
      const c = data.typesCounters || state.types?.counters;
      if (!c?.available) return null;
      rows.push(['对面类型', ...c.cols]);
      c.rows.forEach((enemy, ri) => rows.push([enemy, ...c.cols.map((_, ci) => c.matrix[ri][ci]?.winRate ?? '')]));
    } else if (key === 'systems') {
      rows.push(['体系', 'Pick率', 'Ban率', '环比Pick', '环比Ban']);
      for (const row of data.primary.systems.rows) {
        rows.push([row.system, row.pickRate, row.banRate, row.deltaPick, row.deltaBan]);
      }
    } else if (key === 'plan') {
      rows.push(['优先Ban', '原因', '我们对位胜率']);
      for (const row of data.plan?.banPriority || []) rows.push([row.hero, row.reason, row.ourWinRate]);
    }
    return rows.length > 1 ? rows : null;
  }

  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = name;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function exportCsv(key) {
    const rows = csvRows(key);
    if (!rows) { toast('这一节没有可导出的表'); return; }
    const text = '\ufeff' + rows.map((row) => row.map((cell) => {
      const value = cell == null ? '' : String(cell);
      return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
    }).join(',')).join('\n');
    download(new Blob([text], {type: 'text/csv;charset=utf-8'}), `bp-${key}-${new Date().toISOString().slice(0, 10)}.csv`);
    toast('CSV 已导出');
  }

  async function sectionCanvas(key, scale = 2) {
    const section = state.root?.querySelector(`[data-bps-section="${key}"]`);
    if (!section) throw new Error('section missing');
    const rect = section.getBoundingClientRect();
    if (rect.height < 40) return null;
    const clone = section.cloneNode(true);
    clone.style.width = `${Math.round(rect.width)}px`;
    clone.style.background = '#fff';
    clone.querySelectorAll('.bps-collapse, .bps-export').forEach((node) => node.remove());
    const toDataUrl = async (url) => {
      try {
        const response = await fetch(url);
        const blob = await response.blob();
        return await new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => resolve(url);
          reader.readAsDataURL(blob);
        });
      } catch { return url; }
    };
    const imageNodes = [...clone.querySelectorAll('img')];
    await Promise.all(imageNodes.map(async (img) => { img.src = await toDataUrl(img.src); }));
    const svgImages = [...clone.querySelectorAll('image')];
    await Promise.all(svgImages.map(async (node) => {
      const href = node.getAttribute('href') || node.getAttribute('xlink:href');
      if (!href || href.startsWith('data:')) return;
      const data = await toDataUrl(href);
      node.setAttribute('href', data);
      node.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', data);
    }));
    let css = exportCssCache;
    if (!css) {
      const urls = ['/static/ui-tokens.css', '/static/ui-primitives.css', '/static/style.css',
        '/static/celadon.css', '/static/design-consistency.css', '/static/bp-studio.css'];
      const texts = await Promise.all(urls.map(async (url) => {
        try { return await (await fetch(url)).text(); } catch { return ''; }
      }));
      css = texts.join('\n')
        .replace(/@font-face\s*\{[^}]*\}/g, '')
        .replace(/@import[^;]+;/g, '')
        .replace(/url\((?!['"]?data:)[^)]*\)/g, 'none');
      exportCssCache = css;
    }
    const markup = new XMLSerializer().serializeToString(clone);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${rect.width}" height="${rect.height}">
      <foreignObject width="100%" height="100%">
        <div xmlns="http://www.w3.org/1999/xhtml"><style><![CDATA[${css}]]></style>
          <div class="bps" style="padding:0;max-width:none;margin:0">${markup}</div></div>
      </foreignObject></svg>`;
    const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    const image = new Image();
    image.crossOrigin = 'anonymous';
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(rect.width * scale);
    canvas.height = Math.round(rect.height * scale);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(image, 0, 0);
    return canvas;
  }

  async function sectionToPng(key) {
    toast('正在生成图片…', 4000);
    try {
      const canvas = await sectionCanvas(key, 2);
      if (!canvas) { toast('这一节是收起的，先展开再导出'); return; }
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('empty');
      download(blob, `bp-${key}-${new Date().toISOString().slice(0, 10)}.png`);
      toast('PNG 已导出');
    } catch (error) {
      console.warn('[bp-export]', error);
      toast('导出失败，先用系统截图');
    }
  }

  /* 全部拼成一张长图：按 01–07 的顺序纵向拼接，超过 16000px 自动等比缩小。 */
  async function exportAllPng() {
    const keys = SECTION_LIST.map(([key]) => key);
    const canvases = [];
    try {
      /* 懒加载的分区如果还没取过数，先补齐再截图，避免长图里 04/05 是空壳。 */
      if (state.typesStale || state.seqStale) {
        toast('先补齐类型与手序数据…', 120000);
        await Promise.all([
          state.typesStale ? loadTypes() : Promise.resolve(),
          state.seqStale ? loadSequence() : Promise.resolve(),
        ]);
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      for (let index = 0; index < keys.length; index += 1) {
        toast(`正在拼接 ${index + 1}/${keys.length}…`, 120000);
        const canvas = await sectionCanvas(keys[index], 1);
        if (canvas) canvases.push(canvas);
      }
      if (!canvases.length) { toast('没有可导出的分区'); return; }
      const gap = 28;
      const width = Math.max(...canvases.map((canvas) => canvas.width));
      let height = canvases.reduce((sum, canvas) => sum + canvas.height, 0) + gap * (canvases.length - 1);
      let ratio = 1;
      if (height > 16000) { ratio = 16000 / height; height = 16000; }
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height);
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      let y = 0;
      for (const item of canvases) {
        ctx.drawImage(item, 0, Math.round(y), Math.round(item.width * ratio), Math.round(item.height * ratio));
        y += item.height * ratio + gap * ratio;
      }
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('empty');
      download(blob, `bp-all-${new Date().toISOString().slice(0, 10)}.png`);
      toast('长图已导出');
    } catch (error) {
      console.warn('[bp-export-all]', error);
      toast('长图导出失败，可以逐节导出');
    }
  }

  let toastTimer = 0;
  let exportCssCache = '';
  function toast(text, ms = 1800) {
    let node = state.root?.querySelector('.bps-toast');
    if (!node && state.root) {
      node = document.createElement('div');
      node.className = 'bps-toast';
      state.root.appendChild(node);
    }
    if (!node) return;
    node.textContent = text;
    node.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('is-on'), ms);
  }

  function onClick(event) {
    if (suppressClick) { suppressClick = false; return; }
    const unpin = event.target.closest('[data-bps-unpin]');
    if (unpin) { togglePin(unpin.dataset.bpsUnpin); return; }
    const pin = event.target.closest('[data-bps-pin]');
    if (pin) { togglePin(pin.dataset.bpsPin); return; }
    const pinHero = event.target.closest('[data-bps-pin-hero]');
    if (pinHero) {
      state.target = [pinHero.dataset.bpsPinHero];
      persist(); paint(); loadTarget(); scrollToSection('break'); return;
    }
    const pinCombo = event.target.closest('[data-bps-pin-combo]');
    if (pinCombo) {
      state.comboPick = pinCombo.dataset.bpsPinCombo.split(',').slice(0, 3);
      persist(); paint(); loadCombo(); scrollToSection('combos'); return;
    }
    const heroSort = event.target.closest('[data-bps-hero-sort]');
    if (heroSort) {
      const key = heroSort.dataset.bpsHeroSort;
      state.heroSort = {key, dir: state.heroSort?.key === key ? (state.heroSort.dir > 0 ? -1 : 1) : -1};
      paint(); return;
    }
    const pickRemove = event.target.closest('[data-bps-remove]');
    if (pickRemove) {
      const action = pickRemove.dataset.bpsRemoveAction;
      const list = action === 'combo' ? state.comboPick : state.target;
      const index = list.indexOf(pickRemove.dataset.bpsRemove);
      if (index >= 0) list.splice(index, 1);
      persist();
      paint();
      if (action === 'target') queueTarget();
      return;
    }
    const popButton = event.target.closest('[data-bps-pop]');
    if (popButton) {
      closePops(state.pop === popButton.dataset.bpsPop ? '' : popButton.dataset.bpsPop);
      return;
    }
    if (event.target.closest('[data-bps-pop-close]')) { closePops(''); return; }
    if (!event.target.closest('.bps-pop')) closePops('');

    const source = event.target.closest('[data-bps-source]');
    if (source) {
      state.source = source.dataset.bpsSource;
      state.leagues = [];
      state.team = state.source === 'scrim' ? '本队' : '';
      state.opponent = '';
      state.from = ''; state.to = '';
      state.target = []; state.targetData = null;
      state.comboPick = []; state.comboDetail = null;
      persist(); load(); return;
    }
    const league = event.target.closest('[data-bps-league]');
    if (league) {
      const id = league.dataset.bpsLeague;
      const set = new Set(state.leagues);
      if (set.has(id)) set.delete(id); else set.add(id);
      state.leagues = [...set];
      persist(); load(); return;
    }
    const year = event.target.closest('[data-bps-year]');
    if (year) {
      const value = Number(year.dataset.bpsYear);
      const info = (state.data.options.years || []).find((row) => row.year === value);
      const ids = (info?.leagues || []).map((row) => row.id);
      const set = new Set(state.leagues);
      const allOn = ids.every((id) => set.has(id));
      ids.forEach((id) => (allOn ? set.delete(id) : set.add(id)));
      state.leagues = [...set];
      persist(); load(); return;
    }
    if (event.target.closest('[data-bps-leagues-clear]')) {
      state.leagues = []; persist(); load(); return;
    }
    const team = event.target.closest('[data-bps-select-team]');
    if (team) { state.team = team.dataset.bpsSelectTeam; closePops(''); persist(); load(); return; }
    const opponent = event.target.closest('[data-bps-select-opponent]');
    if (opponent) {
      state.opponent = opponent.dataset.bpsSelectOpponent;
      closePops(''); persist(); load(); return;
    }
    const days = event.target.closest('[data-bps-days]');
    if (days) {
      state.recentDays = Number(days.dataset.bpsDays);
      state.from = ''; state.to = '';
      persist(); load(); return;
    }
    const compare = event.target.closest('[data-bps-compare]');
    if (compare) { state.compare = compare.dataset.bpsCompare; persist(); load(); return; }
    if (event.target.closest('[data-bps-range-apply]')) {
      const from = state.root.querySelector('[data-bps-from]')?.value || '';
      const to = state.root.querySelector('[data-bps-to]')?.value || '';
      if (from && to && from > to) { state.error = '开始日期晚于结束日期'; paint(); return; }
      state.from = from; state.to = to;
      closePops(''); persist(); load(); return;
    }
    if (event.target.closest('[data-bps-range-reset]')) {
      state.from = ''; state.to = '';
      closePops(''); persist(); load(); return;
    }
    if (event.target.closest('[data-bps-view-save]')) {
      const name = (state.viewName || '').trim() || `视图 ${(state.views || []).length + 1}`;
      const snapshot = filterSnapshot();
      const summary = [
        snapshot.source === 'kpl' ? 'KPL' : '训练赛',
        snapshot.leagues.length ? `${snapshot.leagues.length} 赛季` : '全赛季',
        snapshot.opponent ? `对手 ${snapshot.opponent}` : '',
        `近 ${snapshot.recentDays} 天`,
        snapshot.typeBo ? `BO${snapshot.typeBo}` : '',
        snapshot.typeHand ? `第 ${snapshot.typeHand} 手` : '',
      ].filter(Boolean).join(' · ');
      state.views = [{name, summary, note: state.viewNote || '', snapshot}, ...(state.views || []).filter((view) => view.name !== name)].slice(0, 20);
      state.viewName = ''; state.viewNote = '';
      persist();
      paint();
      toast('视图已保存');
      return;
    }
    const viewApply = event.target.closest('[data-bps-view-apply]');
    if (viewApply) {
      const view = (state.views || []).find((item) => item.name === viewApply.dataset.bpsViewApply);
      if (view?.snapshot) {
        Object.assign(state, JSON.parse(JSON.stringify(view.snapshot)));
        closePops('');
        persist();
        load();
      }
      return;
    }
    const viewDel = event.target.closest('[data-bps-view-del]');
    if (viewDel) {
      state.views = (state.views || []).filter((item) => item.name !== viewDel.dataset.bpsViewDel);
      persist(); paint(); return;
    }
    if (event.target.closest('[data-bps-export-all]')) { exportAllPng(); return; }
    if (event.target.closest('[data-bps-share]')) {
      const url = `${location.origin}${location.pathname}?${shareParams().toString()}#bp`;
      const done = () => { state.shareTip = '已复制到剪贴板'; paint(); };
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done).catch(() => {
        state.shareTip = url; paint();
      });
      else { state.shareTip = url; paint(); }
      return;
    }
    if (event.target.closest('[data-bps-compact]')) {
      state.compact = !state.compact; persist(); paint(); return;
    }
    if (event.target.closest('[data-bps-reset]')) {
      state.leagues = [];
      state.team = state.source === 'scrim' ? '本队' : '';
      state.opponent = '';
      state.from = ''; state.to = '';
      state.compare = 'prev'; state.recentDays = 30;
      state.target = []; state.targetData = null;
      state.comboPick = []; state.comboDetail = null;
      state.seqHero = ''; state.typeFocus = ''; state.counterSel = null;
      state.lane = '';
      persist(); load(); return;
    }
    if (event.target.closest('[data-bps-top]')) {
      window.scrollTo({top: 0, behavior: 'smooth'}); return;
    }
    if (event.target.closest('[data-bps-refresh]')) { load(); return; }
    const lane = event.target.closest('[data-bps-lane]');
    if (lane) { state.lane = lane.dataset.bpsLane; resetZoom(); refreshSection('heroes'); return; }
    const chartLimit = event.target.closest('[data-bps-chart-limit]');
    if (chartLimit) { state.chartAll = chartLimit.dataset.bpsChartLimit === 'all'; resetZoom(); refreshSection('heroes'); return; }
    const chartView = event.target.closest('[data-bps-chart-view]');
    if (chartView) { state.chartView = chartView.dataset.bpsChartView; resetZoom(); refreshSection('heroes'); return; }
    if (event.target.closest('[data-bps-chart-reset]')) { resetZoom(); return; }
    if (event.target.closest('[data-bps-seq-toggle]')) {
      state.seqOpen = !state.seqOpen; paint(); return;
    }
    const seqLane = event.target.closest('[data-bps-seq-lane]');
    if (seqLane) { state.seqLane = seqLane.dataset.bpsSeqLane; paint(); return; }
    const seqHero = event.target.closest('[data-bps-seq-hero]');
    if (seqHero) {
      const value = seqHero.dataset.bpsSeqHero;
      state.seqHero = state.seqHero === value ? '' : value;
      state.seqOpen = false; loadSequence(); return;
    }
    if (event.target.closest('[data-bps-seq-from-target]')) {
      state.seqHero = state.target[0]; state.seqOpen = false; loadSequence(); return;
    }
    if (event.target.closest('[data-bps-seq-clear]')) {
      state.seqHero = ''; loadSequence(); return;
    }
    const seqTeam = event.target.closest('[data-bps-seq-team]');
    if (seqTeam) { state.seqTeam = seqTeam.dataset.bpsSeqTeam; loadSequence(); return; }
    const seqAction = event.target.closest('[data-bps-seq-action]');
    if (seqAction) {
      state.seqAction = seqAction.dataset.bpsSeqAction;
      state.seqHand = Math.min(state.seqHand, state.seqAction === 'pick' ? 5 : 4);
      loadSequence(); return;
    }
    const seqHand = event.target.closest('[data-bps-seq-hand]');
    if (seqHand) { state.seqHand = Number(seqHand.dataset.bpsSeqHand); loadSequence(); return; }
    const typeBo = event.target.closest('[data-bps-type-bo]');
    if (typeBo) { state.typeBo = Number(typeBo.dataset.bpsTypeBo); loadTypes(); return; }
    const typeHand = event.target.closest('[data-bps-type-hand]');
    if (typeHand) { state.typeHand = Number(typeHand.dataset.bpsTypeHand); loadTypes(); return; }
    const typeCore = event.target.closest('[data-bps-type-core]');
    if (typeCore) { state.typeCore = Number(typeCore.dataset.bpsTypeCore); loadTypes(); return; }
    const treeDepth = event.target.closest('[data-bps-tree-depth]');
    if (treeDepth) { state.treeDepth = Number(treeDepth.dataset.bpsTreeDepth); loadTree(); return; }
    const treeBranch = event.target.closest('[data-bps-tree-branch]');
    if (treeBranch) { state.treeBranch = Number(treeBranch.dataset.bpsTreeBranch); loadTree(); return; }
    const treeSide = event.target.closest('[data-bps-tree-side]');
    if (treeSide) {
      state.typeSide = treeSide.dataset.bpsTreeSide;
      state.treeStale = true;
      loadTree();
      return;
    }
    const treeCamp = event.target.closest('[data-bps-tree-camp]');
    if (treeCamp) {
      state.treeSide = treeCamp.dataset.bpsTreeCamp;
      loadTree();
      return;
    }
    const treeMode = event.target.closest('[data-bps-tree-mode]');
    if (treeMode) {
      state.treeMode = treeMode.dataset.bpsTreeMode === 'decision' ? 'decision' : 'flow';
      state.decisionPath = [];
      paint();
      return;
    }
    const decisionPick = event.target.closest('[data-bps-decision-pick]');
    if (decisionPick) {
      state.decisionPath.push(decisionPick.dataset.bpsDecisionPick);
      paint();
      return;
    }
    const decisionPin = event.target.closest('[data-bps-decision-pin]');
    if (decisionPin) {
      const route = [...state.decisionPath, decisionPin.dataset.bpsDecisionPin];
      state.decisionPins = [...(state.decisionPins || []), route].slice(-3);
      paint();
      return;
    }
    const decisionUnpin = event.target.closest('[data-bps-decision-unpin]');
    if (decisionUnpin) {
      state.decisionPins.splice(Number(decisionUnpin.dataset.bpsDecisionUnpin) || 0, 1);
      paint();
      return;
    }
    const decisionBack = event.target.closest('[data-bps-decision-back]');
    if (decisionBack) {
      state.decisionPath = state.decisionPath.slice(0, Number(decisionBack.dataset.bpsDecisionBack) || 0);
      paint();
      return;
    }
    if (event.target.closest('[data-bps-decision-reset]')) {
      state.decisionPath = [];
      paint();
      return;
    }
    const compareOpponent = event.target.closest('[data-bps-compare-opponent]');
    if (compareOpponent) {
      state.compareOpponent = compareOpponent.dataset.bpsCompareOpponent;
      closePops(''); loadCompareOpponent(); return;
    }
    if (event.target.closest('[data-bps-compare-clear]')) {
      state.compareOpponent = ''; state.compareBlock = null; paint(); return;
    }
    const counterMode = event.target.closest('[data-bps-counter-mode]');
    if (counterMode) { state.counterMode = counterMode.dataset.bpsCounterMode; state.counterSel = null; refreshSection('types'); return; }
    const counterRow = event.target.closest('[data-bps-counter-row]');
    if (counterRow) { state.counterRowLane = counterRow.dataset.bpsCounterRow; state.counterSel = null; paint(); return; }
    const counterCol = event.target.closest('[data-bps-counter-col]');
    if (counterCol) { state.counterColLane = counterCol.dataset.bpsCounterCol; state.counterSel = null; paint(); return; }
    if (event.target.closest('[data-bps-counter-reset]')) { state.counterSel = null; paint(); return; }
    const typeFocus = event.target.closest('[data-bps-type-focus]');
    if (typeFocus) {
      const value = typeFocus.dataset.bpsTypeFocus;
      state.typeFocus = state.typeFocus === value ? '' : value;
      refreshSection('types'); return;
    }
    const typeSide = event.target.closest('[data-bps-type-side]');
    if (typeSide) {
      state.typeSide = typeSide.dataset.bpsTypeSide;
      state.treeStale = true;
      refreshSection('types');
      if (state.tree) loadTree();
      return;
    }
    if (event.target.closest('[data-bps-widen]')) {
      state.recentDays = Number(event.target.closest('[data-bps-widen]').dataset.bpsWiden) || 90;
      state.from = ''; state.to = '';
      persist(); load(); return;
    }
    const heroCard = event.target.closest('[data-bps-hero-card]');
    if (heroCard) {
      state.target = [heroCard.dataset.bpsHeroCard];
      state.targetOpen = false;
      persist(); paint(); loadTarget(); scrollToSection('break'); return;
    }
    const pick = event.target.closest('[data-bps-pick]');
    if (pick) { onPick(pick.dataset.bpsPickAction, pick.dataset.bpsPick); return; }
    if (event.target.closest('[data-bps-target-toggle]')) {
      state.targetOpen = !state.targetOpen; paint(); return;
    }
    if (event.target.closest('[data-bps-clear]')) {
      const action = event.target.closest('[data-bps-clear]').dataset.bpsClear;
      if (action === 'combo') { state.comboPick = []; state.comboDetail = null; }
      else { state.target = []; state.targetData = null; }
      persist(); paint(); return;
    }
    if (event.target.closest('[data-bps-combo-more]')) {
      state.comboOpen = !state.comboOpen; paint(); return;
    }
    const comboSize = event.target.closest('[data-bps-combo-size]');
    if (comboSize) { state.comboSize = Number(comboSize.dataset.bpsComboSize); refreshSection('combos'); return; }
    const comboSort = event.target.closest('[data-bps-combo-sort]');
    if (comboSort) { state.comboSort = comboSort.dataset.bpsComboSort; refreshSection('combos'); return; }
    const comboRow = event.target.closest('[data-bps-combo-row]');
    if (comboRow) {
      state.comboPick = comboRow.dataset.bpsComboRow.split(',').slice(0, 3);
      persist(); paint(); loadCombo();
      scrollToSection('combos'); return;
    }
    const quick = event.target.closest('[data-bps-quick-target]');
    if (quick) {
      state.target = quick.dataset.bpsQuickTarget.split(',').slice(0, 3);
      persist(); paint(); loadTarget(); return;
    }
    if (event.target.closest('[data-bps-combo-retry]')) { loadCombo(); return; }
    if (event.target.closest('[data-bps-target-retry]')) { loadTarget(); return; }
    if (event.target.closest('[data-bps-types-retry]')) { loadTypes(); return; }
    const oppCombo = event.target.closest('[data-bps-opp-combo]');
    if (oppCombo) { state.oppComboSize = oppCombo.dataset.bpsOppCombo; paint(); return; }
    const exportPng = event.target.closest('[data-bps-export-png]');
    if (exportPng) { sectionToPng(exportPng.dataset.bpsExportPng); return; }
    const exportCsvButton = event.target.closest('[data-bps-export-csv]');
    if (exportCsvButton) { exportCsv(exportCsvButton.dataset.bpsExportCsv); return; }
    const collapse = event.target.closest('[data-bps-collapse]');
    if (collapse) {
      const key = collapse.dataset.bpsCollapse;
      state.collapsed[key] = !state.collapsed[key];
      persist();
      const section = state.root.querySelector(`[data-bps-section="${key}"]`);
      section?.classList.toggle('is-collapsed', Boolean(state.collapsed[key]));
      return;
    }
    const jump = event.target.closest('[data-bps-jump]');
    if (jump) { scrollToSection(jump.dataset.bpsJump); return; }
    const solo = event.target.closest('[data-bps-solo]');
    if (solo) {
      state.solo = !state.solo;
      state.collapsed[state.active] = false;
      persist();
      paint();
      window.scrollTo({top: 0, behavior: 'smooth'});
      return;
    }
  }

  function onInput(event) {
    const viewNote = event.target.closest('[data-bps-view-note]');
    if (viewNote) { state.viewNote = viewNote.value; return; }
    const heroFilter = event.target.closest('[data-bps-hero-filter]');
    if (heroFilter) {
      state.heroQuery = heroFilter.value;
      refreshSection('heroes');
      return;
    }
    const viewName = event.target.closest('[data-bps-view-name]');
    if (viewName) { state.viewName = viewName.value; return; }
    const teamSearch = event.target.closest('[data-bps-team-search]');
    if (teamSearch) {
      state.teamQuery = teamSearch.value;
      const panel = teamSearch.closest('.bps-pop');
      const query = teamSearch.value.trim();
      panel?.querySelectorAll('.bps-team-option').forEach((option) => {
        option.hidden = Boolean(query) && !option.textContent.includes(query);
      });
      return;
    }
    const prior = event.target.closest('[data-bps-prior]');
    if (prior) {
      state.prior = Number(prior.value);
      const label = state.root?.querySelector('[data-bps-prior-value]');
      if (label) label.textContent = `${state.prior}%`;
      persist();
      const panel = state.root?.querySelector('[data-bps-blend]');
      if (panel) panel.innerHTML = blendPanel();
      return;
    }
    const input = event.target.closest('[data-bps-search]');
    if (!input) return;
    const action = input.dataset.bpsSearch;
    state[`${action}Search`] = input.value;
    filterPicker(action, input.value);
  }

  /* 气泡图缩放 / 拖拽：直接改 <g> 的 transform，不重排页面。 */
  let zoom = {k: 1, x: 0, y: 0};
  let drag = null;
  let suppressClick = false;

  function applyZoom() {
    const group = state.root?.querySelector('.bv-scatter .bv-zoom-inner');
    if (group) {
      group.setAttribute('transform',
        `translate(${zoom.x.toFixed(2)} ${zoom.y.toFixed(2)}) scale(${zoom.k.toFixed(3)})`);
    }
  }

  function resetZoom() {
    zoom = {k: 1, x: 0, y: 0};
    applyZoom();
  }

  function chartSvg(node) {
    const svg = node?.closest?.('.bv-scatter');
    return svg || null;
  }

  function onWheel(event) {
    const svg = chartSvg(event.target);
    if (!svg) return;
    event.preventDefault();
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    if (!rect.width) return;
    const mx = (event.clientX - rect.left) / rect.width * viewBox.width;
    const my = (event.clientY - rect.top) / rect.height * viewBox.height;
    const factor = Math.exp(-event.deltaY * 0.0012);
    const next = Math.min(8, Math.max(1, zoom.k * factor));
    const ratio = next / zoom.k;
    zoom.x = mx - (mx - zoom.x) * ratio;
    zoom.y = my - (my - zoom.y) * ratio;
    zoom.k = next;
    if (next === 1) { zoom.x = 0; zoom.y = 0; }
    applyZoom();
  }

  function onPointerDown(event) {
    const svg = chartSvg(event.target);
    if (!svg || event.button !== 0) return;
    drag = {svg, sx: event.clientX, sy: event.clientY, ox: zoom.x, oy: zoom.y, moved: false};
    svg.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event) {
    if (!drag) return;
    const rect = drag.svg.getBoundingClientRect();
    const viewBox = drag.svg.viewBox.baseVal;
    if (!rect.width) return;
    const dx = (event.clientX - drag.sx) / rect.width * viewBox.width;
    const dy = (event.clientY - drag.sy) / rect.height * viewBox.height;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    zoom.x = drag.ox + dx;
    zoom.y = drag.oy + dy;
    applyZoom();
  }

  function onPointerUp() {
    if (!drag) return;
    if (drag.moved) suppressClick = true;
    drag = null;
  }

  let compareScrollLock = false;
  function onCompareScroll(event) {
    const el = event.target;
    if (!el?.classList?.contains('bps-compare-scroll')) return;
    if (compareScrollLock) return;
    const panels = [...state.root.querySelectorAll('.bps-compare-scroll')];
    const other = panels.find((node) => node !== el);
    if (!other) return;
    compareScrollLock = true;
    const max = el.scrollHeight - el.clientHeight;
    const ratio = max > 0 ? el.scrollTop / max : 0;
    other.scrollTop = ratio * Math.max(0, other.scrollHeight - other.clientHeight);
    requestAnimationFrame(() => { compareScrollLock = false; });
  }

  function onCompareHover(event) {
    const node = event.target.closest?.('[data-cmp-key]');
    if (!node || !state.root?.contains(node)) return;
    const key = node.dataset.cmpKey;
    state.root.querySelectorAll('[data-cmp-key]').forEach((item) => {
      item.classList.toggle('is-linked', item.dataset.cmpKey === key);
    });
  }

  function onCompareOut(event) {
    const node = event.target.closest?.('[data-cmp-key]');
    if (!node) return;
    const next = event.relatedTarget?.closest?.('[data-cmp-key]');
    if (next?.dataset.cmpKey === node.dataset.cmpKey) return;
    state.root.querySelectorAll('[data-cmp-key].is-linked').forEach((item) => item.classList.remove('is-linked'));
  }

  function onHoverIn(event) {
    const node = event.target.closest?.('[data-hover-hero]');
    if (!node || !state.root?.contains(node)) return;
    showHover(node.dataset.hoverHero, node);
  }

  function onHoverOut(event) {
    const node = event.target.closest?.('[data-hover-hero]');
    if (!node) return;
    const next = event.relatedTarget?.closest?.('[data-hover-hero]');
    if (!next) { if (hoverNode) hoverNode.hidden = true; }
  }

  let scrollBound = null;
  let clickBound = null;
  let inputBound = null;
  let keyBound = null;
  let resizeBound = null;

  function bind() {
    clickBound = (event) => {
      if (!state.root?.contains(event.target)) return;
      onClick(event);
    };
    inputBound = (event) => {
      if (!state.root?.contains(event.target)) return;
      onInput(event);
    };
    scrollBound = () => updateActiveJump();
    resizeBound = () => { syncSticky(); updateActiveJump(); };
    keyBound = (event) => {
      if (event.key === 'Escape') {
        if (state.pop) closePops('');
        if (state.seqOpen) { state.seqOpen = false; paint(); }
        return;
      }
      /* 1–7 跳分区；输入框里不抢键。 */
      if (/^[1-7]$/.test(event.key)
        && !event.target.closest('input, textarea, select, [contenteditable]')) {
        const key = SECTION_LIST[Number(event.key) - 1]?.[0];
        if (key) scrollToSection(key);
      }
    };
    document.addEventListener('click', clickBound);
    document.addEventListener('input', inputBound);
    document.addEventListener('keydown', keyBound);
    document.addEventListener('mouseover', onHoverIn);
    document.addEventListener('mouseout', onHoverOut);
    document.addEventListener('mouseover', onCompareHover);
    document.addEventListener('mouseout', onCompareOut);
    document.addEventListener('scroll', onCompareScroll, true);
    window.addEventListener('scroll', scrollBound, {passive: true});
    window.addEventListener('resize', resizeBound, {passive: true});
    state.root?.addEventListener('wheel', onWheel, {passive: false});
    state.root?.addEventListener('pointerdown', onPointerDown);
    state.root?.addEventListener('pointerdown', matrixPointerDown);
    state.root?.addEventListener('pointermove', onPointerMove);
    state.root?.addEventListener('pointermove', matrixPointerMove);
    state.root?.addEventListener('pointerup', onPointerUp);
    state.root?.addEventListener('pointerup', matrixPointerUp);
  }

  function unbind() {
    if (clickBound) document.removeEventListener('click', clickBound);
    if (inputBound) document.removeEventListener('input', inputBound);
    if (scrollBound) window.removeEventListener('scroll', scrollBound);
    if (resizeBound) window.removeEventListener('resize', resizeBound);
    if (keyBound) document.removeEventListener('keydown', keyBound);
    document.removeEventListener('mouseover', onHoverIn);
    document.removeEventListener('mouseout', onHoverOut);
    document.removeEventListener('mouseover', onCompareHover);
    document.removeEventListener('mouseout', onCompareOut);
    document.removeEventListener('scroll', onCompareScroll, true);
    if (hoverNode) { hoverNode.remove(); hoverNode = null; }
    state.root?.removeEventListener('wheel', onWheel);
    state.root?.removeEventListener('pointerdown', onPointerDown);
    state.root?.removeEventListener('pointerdown', matrixPointerDown);
    state.root?.removeEventListener('pointermove', onPointerMove);
    state.root?.removeEventListener('pointermove', matrixPointerMove);
    state.root?.removeEventListener('pointerup', onPointerUp);
    state.root?.removeEventListener('pointerup', matrixPointerUp);
    clickBound = inputBound = scrollBound = keyBound = null;
  }

  function mount(root) {
    if (!root) return;
    state.root = root;
    state.disposed = false;
    restore();
    if (window.innerWidth < 900) state.compact = true;
    if (window.innerWidth < 760 && !Object.keys(state.collapsed || {}).length) {
      state.collapsed = {combos: true, types: true, systems: true, plan: true};
    }
    applyShareLink();
    bind();
    if (!state.data) paint();
    load();
  }

  function dispose() {
    state.disposed = true;
    state.controller?.abort();
    clearTimeout(targetTimer);
    clearTimeout(comboTimer);
    unbind();
    state.root = null;
  }

  return {mount, dispose};
}
