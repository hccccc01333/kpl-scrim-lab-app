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

import {createBpViz} from './bps-viz.js?v=20261124link2';

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const SECTION_LIST = [
  ['heroes', '01', '英雄优先级', '版本里哪些英雄值得先拿？', '气泡 = Pick 次数 · 颜色 = 分路'],
  ['combos', '02', '组合', '自选组合到底多强，联盟哪些组合在赢？', '同队同局，不是因果协同 · 阵容差异'],
  ['break', '03', '战队如何破解', '目标被对面拿走，KPL 怎么应对，我们怎么应对？', 'KPL 先验 × 本队训练赛'],
  ['opponent', '04', '对手 BP 情报', '他的 Ban 在想什么，第一手之后他会怎么走？', 'Ban 意图 / 手序 / 条件回应'],
  ['types', '05', '手序', '他第一手 Ban / 选的是什么类型？放到 BO 和时间里还成立吗？', '手序 × 赛制'],
  ['plan', '06', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？', '历史证据，不是最优解'],
  ['counter', '07', '应对分析', '对方第一手之后，双方逐层怎么接？', '楼层 × 战队 × 先后手 × BO'],
];
/* 应对分析前置条件：逐手一张卡，Ban 与 Pick 混排，手号连续不跳号。
   hand = 全局第几手；key 同时用作 state.counterPrefix 的键和后端 prefix_* 参数名。
   排程以 bp_formats 为准：draft-20 = KPL 5 Ban/方共 20 手；draft-18 = 训练赛 4 Ban/方共 18 手。
   旧版把 6/7、8/9、18/19 手合并成一张卡，导致第 19 手看不见，这里全部拆开。 */
const prefixBan = (key, camp, n, hand) => ({key, camp, suffix: `Ban ${n}`, group: 'ban', hand, slots: 1});
const prefixPick = (key, camp, n, hand) => ({key, camp, suffix: `${n}L`, group: 'pick', hand, slots: 1});
const COUNTER_STAGES_20 = [
  prefixBan('blueBan1', '1', 1, 1), prefixBan('redBan1', '2', 1, 2),
  prefixBan('blueBan2', '1', 2, 3), prefixBan('redBan2', '2', 2, 4),
  prefixPick('blue1', '1', 1, 5), prefixPick('red1', '2', 1, 6),
  prefixPick('red2', '2', 2, 7), prefixPick('blue2', '1', 2, 8),
  prefixPick('blue3', '1', 3, 9), prefixPick('red3', '2', 3, 10),
  prefixBan('redBan3', '2', 3, 11), prefixBan('blueBan3', '1', 3, 12),
  prefixBan('redBan4', '2', 4, 13), prefixBan('blueBan4', '1', 4, 14),
  prefixBan('redBan5', '2', 5, 15), prefixBan('blueBan5', '1', 5, 16),
  prefixPick('red4', '2', 4, 17), prefixPick('blue4', '1', 4, 18),
  prefixPick('blue5', '1', 5, 19), prefixPick('red5', '2', 5, 20),
];
const COUNTER_STAGES_18 = [
  prefixBan('blueBan1', '1', 1, 1), prefixBan('redBan1', '2', 1, 2),
  prefixBan('blueBan2', '1', 2, 3), prefixBan('redBan2', '2', 2, 4),
  prefixPick('blue1', '1', 1, 5), prefixPick('red1', '2', 1, 6),
  prefixPick('red2', '2', 2, 7), prefixPick('blue2', '1', 2, 8),
  prefixPick('blue3', '1', 3, 9), prefixPick('red3', '2', 3, 10),
  prefixBan('redBan3', '2', 3, 11), prefixBan('blueBan3', '1', 3, 12),
  prefixBan('redBan4', '2', 4, 13), prefixBan('blueBan4', '1', 4, 14),
  prefixPick('red4', '2', 4, 15), prefixPick('blue4', '1', 4, 16),
  prefixPick('blue5', '1', 5, 17), prefixPick('red5', '2', 5, 18),
];
const ALL_PREFIX_STAGES = [...COUNTER_STAGES_20, ...COUNTER_STAGES_18];
const prefixStages = (rule) => rule === 'draft-18' ? COUNTER_STAGES_18 : COUNTER_STAGES_20;
const STORE_KEY = 'bp-studio.v3';
const MODES = [['scrim', '训练赛'], ['kpl', 'KPL'], ['rank', '排位与巅峰']];
const MODE_CONF = {
  scrim: {source: 'scrim', rule: 'draft-18'},
  kpl: {source: 'kpl', rule: ''},
  rank: {source: 'scrim', rule: 'rank-20'},
};

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
    mode: 'kpl', source: 'kpl', rule: 'draft-20', leagues: [], team: '', opponent: '',
    recentDays: 30, from: '', to: '', compare: 'prev',
    lane: '', chartAll: false, chartView: 'bubble', comboOpen: false, comboSize: 2, comboSort: 'usage', oppComboSize: '2',
    comboPick: [], comboDetail: null, comboLoading: false, comboError: '',
    target: [], targetData: null, targetLoading: false, targetError: '', targetOpen: false, breakView: 'ours',
    heroSearch: '', comboSearch: '', targetSearch: '',
    types: null, typesLoading: false, typesError: '', typeBo: 0, typeSide: 'opponent', kplTypes: null, prior: 60, typeHand: 0, typeCore: 0, typeFocus: '', counterRowLane: '', counterColLane: '', counterSel: null, counterMode: 'pick',
    tree: null, treeLoading: false, treeError: '', treeDepth: 6, treeBranch: 3, treeSide: '', treeStale: true,
    treeMode: 'flow', decisionPath: [], decisionPins: [], decisionNote: '', flowHero: '',
    typeTreeMode: 'flow', typeHandFocus: 0, flowSimple: true,
    ringHero: '', ringLane: '', ring: null, ringLoading: false, ringError: '', ringStale: true,
    seqTeam: 'opponent', seqAction: 'pick', seqHand: 1, seqHero: '', seqLane: '', seqOpen: false,
    seqData: null, seqLoading: false, seqError: '', lastLoadedAt: 0, teamQuery: '', collapsed: {},
    counterData: null, counterLoading: false, counterError: '', counterStale: true,
    counterSide: '', counterBo: 0, counterOpen: '', counterSearch: '', counterTeamScope: 'all',
    counterPrefix: Object.fromEntries([...new Set(ALL_PREFIX_STAGES.map((stage) => stage.key))].map((key) => [key, []])),
    counterPrefixStage: 'blueBan1', counterPrefixSearch: '',
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
  // 窗口跨年时只留月日会出现「11-15 → 11-14」这种看着像倒挂的区间，
  // 当前窗和环比窗还可能显示成同一串；跨年就补全年，同年内才省略年份。
  const windowRange = (from, to) => {
    const a = String(from || ''), b = String(to || '');
    if (!a || !b) return '—';
    return a.slice(0, 4) === b.slice(0, 4)
      ? `${a.slice(5)} → ${b.slice(5)}`
      : `${a} → ${b}`;
  };

  // ── 视觉基元 ────────────────────────────────────────────────────────
  const deltaChip = (value, {tone = 'good', suffix = ' pp'} = {}) => {
    if (!has(value)) return '<span class="bps-delta is-flat">—</span>';
    if (Math.abs(value) < 0.05) return '<span class="bps-delta is-flat">持平</span>';
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
        <span class="bps-section-no">${meta[1] || no}</span>
        <h2>${esc(title)}</h2>
        <span class="bps-section-meta">${esc(metaText || meta[4] || '')}</span>
        <p>${esc(question)}</p>
      </header>`;
  };

  // ── 数据 ────────────────────────────────────────────────────────────
  function queryParams(extra = {}) {
    const values = {source: state.source, rule: state.rule, demo: state.demo ? 1 : '', recentDays: state.recentDays,
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
    /* 赛事域 P1-4：BP 工作台全部请求自动带上当前赛事，scrim 语料按其归集窗口收滤。 */
    let competition = '';
    try { competition = localStorage.getItem('training-current-competition') || ''; } catch {}
    const competitionSuffix = competition
      ? `${path.includes('?') ? '&' : '?'}competition=${encodeURIComponent(competition)}` : '';
    const response = await fetch(`${API_BASE}/api/v3/bp-studio${path}${competitionSuffix}`, {
      cache: 'no-store', signal, headers: {Accept: 'application/json'},
    });
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('接口不存在：当前工作台可能还是旧进程，请重启工作台后再试。');
      }
      let detail = '';
      try { detail = (await response.json()).detail || ''; } catch {}
      throw new Error(detail || `请求失败（HTTP ${response.status}）`);
    }
    return response.json();
  }

  function persist() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        mode: state.mode, rule: state.rule, source: state.source, leagues: state.leagues, team: state.team,
        opponent: state.opponent, recentDays: state.recentDays,
        from: state.from, to: state.to, compare: state.compare,
        lane: state.lane, chartAll: state.chartAll, chartView: state.chartView,
        comboSize: state.comboSize, comboSort: state.comboSort, prior: state.prior,
        collapsed: state.collapsed, pins: state.pins, views: state.views, compact: state.compact,
        solo: state.solo, active: state.active,
        treeDepth: state.treeDepth, treeBranch: state.treeBranch, treeSide: state.treeSide,
        treeMode: state.treeMode, flowHero: state.flowHero, flowSimple: state.flowSimple,
        typeTreeMode: state.typeTreeMode,
        comboPick: state.comboPick, target: state.target,
        counterPrefix: state.counterPrefix, counterPrefixStage: state.counterPrefixStage,
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

  function applyMode(mode) {
    const conf = MODE_CONF[mode] || MODE_CONF.kpl;
    state.mode = MODE_CONF[mode] ? mode : 'kpl';
    state.source = conf.source;
    state.rule = conf.rule;
    state.demo = false;
    normalizePrefixStage();
  }

  /* 18 手没有第 5 轮 Ban；切模式后当前选中的手号必须落在新排程里。 */
  function normalizePrefixStage() {
    const stages = prefixStages(state.rule);
    if (!stages.some((stage) => stage.key === state.counterPrefixStage)) {
      state.counterPrefixStage = stages[0].key;
    }
  }

  function restore() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (!raw || typeof raw !== 'object') return;
      if (raw.mode && MODE_CONF[raw.mode]) applyMode(raw.mode);
      else if (raw.source === 'scrim' || raw.source === 'kpl') applyMode(raw.source);
      for (const key of ['source', 'team', 'opponent', 'recentDays', 'from', 'to',
        'compare', 'lane', 'chartAll', 'chartView', 'comboSize', 'comboSort', 'prior',
        'treeDepth', 'treeBranch', 'treeSide', 'flowHero', 'treeMode', 'flowSimple', 'typeTreeMode']) {
        if (raw[key] !== undefined && raw[key] !== null) state[key] = raw[key];
      }
      if (Array.isArray(raw.leagues)) state.leagues = raw.leagues.slice(0, 40);
      if (Array.isArray(raw.comboPick)) state.comboPick = raw.comboPick.slice(0, 3);
      if (Array.isArray(raw.target)) state.target = raw.target.slice(0, 3);
      if (raw.counterPrefix && typeof raw.counterPrefix === 'object') {
        for (const key of Object.keys(state.counterPrefix)) {
          if (Array.isArray(raw.counterPrefix[key])) {
            state.counterPrefix[key] = raw.counterPrefix[key].slice(0, 2);
          }
        }
      }
      if (raw.counterPrefixStage && state.counterPrefix[raw.counterPrefixStage]) {
        state.counterPrefixStage = raw.counterPrefixStage;
      }
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
      // 没有任何 BP 记录：只画空态，下面这些默认值都没有可选项可填。
      if (data && data.available === false) {
        paint();
        return;
      }
      if (!state.team) state.team = data.scope?.team || data.options.defaultTeam || '';
      if (!state.opponent) state.opponent = data.scope?.opponent || data.options.defaultOpponent || '';
      if (!state.ringHero) {
        state.ringHero = data.primary?.heroes?.top?.[0]?.hero
          || data.primary?.heroes?.rows?.[0]?.hero || '';
      }
      if (!state.ringLane && state.ringHero) {
        const row = (data.primary?.heroes?.rows || []).find((item) => item.hero === state.ringHero);
        state.ringLane = row?.lane || '';
      }
      paint();
      if (state.target.length) loadTarget();
      if (state.comboPick.length >= 2) loadCombo();
      state.typesStale = true;
      state.treeStale = true;
      state.ringStale = true;
      state.seqStale = true;
      state.counterStale = true;
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

  async function loadRing() {
    if (!state.root || !state.ringHero) return;
    state.ringLoading = true;
    state.ringError = '';
    paint();
    try {
      const search = new URLSearchParams({
        hero: state.ringHero, source: state.source, recentDays: state.recentDays,
      });
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      state.ring = await api(`/hero-ring?${search.toString()}`);
      state.ringStale = false;
    } catch (error) {
      state.ringError = error.message || '英雄关系读取失败';
      state.ringStale = false;
    } finally {
      state.ringLoading = false;
      paint();
    }
  }

  /* 应对分析：楼层 × 战队 × 先后手 × BO 全部交给后端算，前端只排版。 */
  async function loadCounterChain() {
    if (!state.root) return;
    state.counterLoading = true;
    state.counterError = '';
    paint();
    try {
      const search = new URLSearchParams({
        source: state.source, recentDays: state.recentDays,
        side: state.counterSide, bo: String(state.counterBo),
      });
      if (state.leagues.length) search.set('leagues', state.leagues.join(','));
      /* 选了「我方蓝/红方」就必须锁定我方 + 指定对手，否则 side 只是在筛记录方。 */
      if (state.counterTeamScope === 'matchup' || state.counterSide) {
        if (state.source === 'scrim') search.set('team', '本队');
        else if (state.team) search.set('team', state.team);
        if (state.opponent && state.opponent !== '__all__') search.set('opponent', state.opponent);
      }
      /* 只提交当前模式排程里的手：训练赛 18 手不会把 KPL 第 5 轮 Ban 带进筛选。 */
      for (const stage of prefixStages(state.rule)) {
        const heroes = state.counterPrefix[stage.key] || [];
        if (heroes.length) search.set(`prefix_${stage.key}`, heroes.join(','));
      }
      if (state.from && state.to) { search.set('from', state.from); search.set('to', state.to); }
      state.counterData = await api(`/counter-chain?${search.toString()}`);
      state.counterStale = false;
    } catch (error) {
      state.counterError = error.message || '应对分析读取失败';
      state.counterStale = false;
    } finally {
      state.counterLoading = false;
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
      if (state.flowHero) search.set('hero', state.flowHero);
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
    // 已经在最长窗口（或自定义窗口）时再给「放到近 365 天」就是死按钮：
    // 近 365 天被数据源本身截断，点下去窗口和样本都不会变。
    const canWiden = !state.from && !state.to && state.recentDays < next;
    return `<div class="bps-sample-warn">
      <b>当前窗口只有 ${num(games)} 个队-局</b>
      <span>胜率、克制这类结论很容易被 1–2 局带偏。${canWiden ? '' : '当前数据源本身样本有限，换数据源或补采更多对局后再看。'}</span>
      ${canWiden ? `<button type="button" class="bps-softbtn" data-bps-widen="${next}">放到近 ${next} 天</button>` : ''}
    </div>`;
  }

  function applyShareLink() {
    try {
      const params = new URLSearchParams(location.search);
      if (params.get('bps') !== '1') return;
      const read = (key) => params.get(key);
      const mode = read('mode');
      if (mode && MODE_CONF[mode]) applyMode(mode);
      else if (read('source') === 'scrim' || read('source') === 'kpl') applyMode(read('source'));
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
    const params = new URLSearchParams({bps: '1', mode: state.mode, rule: state.rule, source: state.source});
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
      mode: state.mode, rule: state.rule, source: state.source, leagues: [...state.leagues], team: state.team,
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
    const isKpl = state.source === 'kpl';
    const games = data.primary.games;
    const teamGames = data.primary.boardGames;
    const years = (data.options.years || []).filter((row) => row.year);
    const span = years.length ? `${years[0].year}–${years[years.length - 1].year}` : '—';
    // 训练赛页没有赛季概念：options.years 是 KPL 目录的全库年份，
    // 拿它当「赛季范围」会显示 2019–2026，和 11-02→11-10 的数据窗口对不上。
    const fromYear = String(scope.from || '').slice(0, 4);
    const toYear = String(scope.to || '').slice(0, 4);
    const dataSpan = fromYear && toYear
      ? (fromYear === toYear ? fromYear : `${fromYear}–${toYear}`) : '—';
    const seasonText = isKpl
      ? (state.leagues.length ? `${state.leagues.length} 个赛季` : span)
      : dataSpan;
    return `<header class="bps-hero">
      <div class="bps-hero-copy">
        <h1>BP 工作台</h1>
        ${state.mode === 'scrim' && !(data.quality?.ordered)
          ? `<p class="bps-note">当前营地数据是排位/巅峰（rank-20）；征召 18 手还没有完整对局。
              <button type="button" class="bps-softbtn" data-bps-demo>载入模拟数据</button></p>` : ''}
        ${state.demo
          ? '<p class="bps-note">模拟数据 · 8 局征召 18 手，仅用于界面验证，不计入真实统计。</p>' : ''}
      </div>
      <div class="bps-hero-facts">
        <div><span>覆盖队-局</span><b>${num(games)}</b><small>${isKpl ? 'KPL 双方视角' : `双方合计 · 本队 ${num(teamGames)}`}</small></div>
        <div><span>${isKpl ? '赛季范围' : '数据范围'}</span><b>${esc(seasonText)}</b><small class="bps-range">${esc(windowRange(scope.from, scope.to))}</small></div>
        <div><span>对比窗口</span><b>${state.compare === 'prev' ? '环比' : state.compare === 'yoy' ? '同比' : '关闭'}</b><small class="bps-range">${scope.prev ? esc(windowRange(scope.prev.from, scope.prev.to)) : '无上一窗口'}</small></div>
        <div><span>对手样本</span><b>${state.opponent ? num(data.opponentBlock?.games || 0) : '—'}</b><small>${state.opponent ? esc(state.opponent === '__all__' ? '全部对手' : state.opponent) : '未选择对手'}</small></div>
      </div>
    </header>`;
  }

  // ── 筛选台 ──────────────────────────────────────────────────────────
  function seasonPanel() {
    const years = state.data?.options?.years || [];
    const selected = new Set(state.leagues);
    return `<div class="bps-pop is-right" data-bps-pop-panel="season" ${state.pop === 'season' ? '' : 'hidden'}>
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
      ${state.loading ? '<span class="bps-progress" aria-hidden="true"></span>' : ''}
      <div class="bps-console-group">
        <span class="bps-console-label">模式</span>
        ${seg(MODES, state.mode, 'data-bps-mode')}
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
      <div class="bps-console-tools">
        ${state.loading
          ? '<span class="bps-updating"><i></i>更新中</span>'
          : qualityChip()}
        <button type="button" class="bps-softbtn is-icon" data-bps-compact aria-pressed="${state.compact}"
          title="${state.compact ? '切回标准视图' : '切换简洁视图（隐藏图表）'}">${state.compact ? '标准' : '简洁'}</button>
        <button type="button" class="bps-softbtn is-icon" data-bps-reset aria-label="重置筛选" title="清空赛季、战队、时间、目标等全部筛选">${icon('close')}</button>
        <button type="button" class="bps-softbtn is-icon" data-bps-refresh aria-label="重新读取" title="重新读取">${icon('refresh')}</button>
      </div>
    </div>`;
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

  function bindFlowDrag() {
    if (!state.root) return;
    state.root.querySelectorAll('.bps-tree-scroll').forEach((scroller) => {
      if (scroller.dataset.dragBound) return;
      scroller.dataset.dragBound = '1';
      let active = false;
      let startX = 0;
      let startY = 0;
      let startLeft = 0;
      let startTop = 0;
      scroller.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return;
        // 点节点要触发 click（占比 / 决策分支），不能被画布拖拽拦下。
        if (event.target.closest?.('[data-bps-type-level], [data-bps-decision-pick], [data-bps-flow-hero]')) return;
        active = true;
        startX = event.clientX;
        startY = event.clientY;
        startLeft = scroller.scrollLeft;
        startTop = scroller.scrollTop;
        scroller.classList.add('is-dragging');
        scroller.setPointerCapture?.(event.pointerId);
        event.preventDefault();
      });
      scroller.addEventListener('pointermove', (event) => {
        if (!active) return;
        scroller.scrollLeft = startLeft - (event.clientX - startX);
        scroller.scrollTop = startTop - (event.clientY - startY);
      });
      const end = () => {
        active = false;
        scroller.classList.remove('is-dragging');
      };
      scroller.addEventListener('pointerup', end);
      scroller.addEventListener('pointercancel', end);
      scroller.addEventListener('lostpointercapture', end);
    });
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
      <span class="bps-focus-spark">${viz.spark(row.spark, {key: 'pickRate', w: 260, h: 26})}</span>
    </button>`;
  }

  /* 搭配从关系环里单独拎出一行：双人组合卡片按胜率排，样本量随卡标注。 */
  function ringPartnersHtml() {
    const partners = [...(state.ring?.partners || [])]
      .sort((a, b) => (b.winRate ?? -1) - (a.winRate ?? -1));
    if (!partners.length) return '';
    return `<div class="bps-ring-partners">
      <div class="bps-subblock-head"><b>最佳搭档 · 双人组合</b></div>
      <div class="bps-partner-cards">${partners.map((row) => `<div class="bps-partner-card">
        ${heroImg(row.hero)}
        <b>${esc(heroShort(row.hero))}</b>
        <span>胜率 ${rate(row.winRate)}</span>
        <small>${num(row.n)} 局</small>
      </div>`).join('')}</div>
    </div>`;
  }

  /* 克制链按英雄/全局口径展示：关系环本身就来自 KPL 全局对位，不绑定某支战队。
     对位英雄用头像而不是名字，和下方最佳搭档卡、关系环中心的呈现保持一致。 */
  function ringChainHtml() {
    const ring = state.ring;
    if (!ring?.available) return '';
    const faces = (list) => (list || []).slice(0, 3)
      .map((row) => `<span class="bps-chain-face" title="${esc(row.hero)}">${heroImg(row.hero)}</span>`).join('') || '—';
    return `<div class="bps-ring-chain">
      <div class="bps-subblock-head"><b>克制链 · 全局英雄对位</b></div>
      <div class="bps-chain-row">
        <span class="is-against"><em>被克制</em>${faces(ring.counteredBy)}</span>
        <b>${esc(heroShort(ring.hero))}</b>
        <span class="is-for"><em>克制</em>${faces(ring.counters)}</span>
      </div>
    </div>`;
  }

  function ringPanel() {
    const heroes = state.data?.options?.heroes || [];
    const laneHeroes = heroes.filter((row) => !state.ringLane || row.lane === state.ringLane);
    if (laneHeroes.length && !laneHeroes.some((row) => row.name === state.ringHero)) {
      state.ringHero = laneHeroes[0].name;
    }
    const laneOptions = [['', '全部分路'], ...LANES.map((lane) => [lane, lane])]
      .map(([value, label]) => `<option value="${esc(value)}" ${state.ringLane === value ? 'selected' : ''}>${esc(label)}</option>`).join('');
    const heroOptions = laneHeroes.map((row) => `<option value="${esc(row.name)}"
      ${row.name === state.ringHero ? 'selected' : ''}>${esc(row.name)}</option>`).join('');
    return `<div class="bps-panel bps-ring-panel" data-bps-ring>
      <div class="bps-panel-head"><h3>英雄关系环</h3>
        <span class="bps-sub">克制 / 被克制 / 最佳搭档 · KPL 历史对位与同队同局</span></div>
      <div class="bps-panel-body">
        <div class="bps-ring-tools">
          <span class="bps-console-label">分路</span>
          <select data-bps-ring-lane>${laneOptions}</select>
          <span class="bps-console-label">英雄</span>
          <select data-bps-ring-hero>${heroOptions}</select>
          ${state.ring?.stats ? `<span class="bps-sub">${num(state.ring.stats.games)} 队-局 · Pick ${rate(state.ring.stats.pickRate)} · Ban ${rate(state.ring.stats.banRate)} · 胜率 ${rate(state.ring.stats.winRate)}</span>` : ''}
        </div>
        ${state.ringLoading && !state.ring ? '<div class="bps-loading">正在读取英雄关系…</div>' : ''}
        ${state.ringError ? `<div class="bps-inline-error">${esc(state.ringError)}</div>` : ''}
        ${state.ring?.available ? viz.heroRing(state.ring, {width: 760, height: 380})
          : (state.ring ? `<div class="bps-empty"><b>没有这个英雄的关系数据</b><p>${esc(state.ring.reason || '')}</p></div>` : '')}
        ${ringChainHtml()}
        ${ringPartnersHtml()}
      </div>
    </div>`;
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
              <span class="bps-tool-divider" aria-hidden="true"></span>
              ${seg([['bubble', '气泡图'], ['matrix', '分路矩阵']], state.chartView, 'data-bps-chart-view', {small: true})}
              ${state.chartView === 'bubble' ? '<button type="button" class="bps-link" data-bps-chart-reset>重置视图</button>' : ''}
            </div>
            <div class="bps-chart">${state.chartView === 'bubble'
              ? viz.heroScatter(chartRows, {onlyLane: state.lane, width: 860, height: 350, minDecided: 8})
              : heroMatrix(matrixRows)}</div>
            ${state.chartView === 'bubble' ? `<div class="bps-chart-legend">
              ${['对抗路', '打野', '中路', '发育路', '游走'].map((lane) => `<i><span style="display:inline-block;width:8px;height:8px;border-radius:3px;background:${viz.LANE_COLOR[lane]}"></span>${lane}</i>`).join('')}
              <i><span style="display:inline-block;width:8px;height:8px;border-radius:50%;border:2px solid var(--bps-quiet)"></span>气泡大小 = Pick 次数</i>
              <i>只标注优先级最高的 12 个</i>
            </div>` : ''}
          </div>
          <div class="bps-focus-grid">${rows.slice(0, 4).map(focusCard).join('')}</div>
          ${ringPanel()}
          ${fullTable}
        </div>
        <aside class="bps-movers">
          <div class="bps-movers-block">
            <b>${movers.opponent ? `${esc(movers.opponent)} Ban 率上升` : '对方 Ban 率上升'}</b>
            ${(movers.up || []).slice(0, 5).map(moverRow).join('') || '<p class="bps-note">样本不足</p>'}
          </div>
          <div class="bps-movers-block">
            <b>${movers.opponent ? `${esc(movers.opponent)} Ban 率下降` : '对方 Ban 率下降'}</b>
            ${(movers.down || []).slice(0, 5).map(moverRow).join('') || '<p class="bps-note">样本不足</p>'}
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
        <p class="bps-note bps-picker-empty" hidden>没有匹配的英雄。换个关键词，或清空搜索框看全部。</p>
      </div>
    </div>`;
  }

  // ── 02 组合（组合强度 + 阵容差异）────────────────────────────────────
  function comboCard() {
    if (state.comboPick.length < 2) {
      return `<div class="bps-empty bps-combo-empty"><b>先选两个英雄</b>
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
      return `<div class="bps-empty bps-combo-empty"><b>这组英雄没有同队同局记录</b>
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

  function comboCards(rows) {
    const list = (rows || []).slice(0, 9);
    if (!list.length) return '<div class="bv-empty">当前范围没有组合卡片。</div>';
    return `<div class="bps-trio-grid">${list.map((row) => {
      const rel = row.relative;
      return `<button type="button" class="bps-trio" data-bps-combo-row="${esc(row.heroes.join(','))}">
        <span class="bps-trio-faces">${row.heroes.map((hero) => heroImg(hero)).join('<i>+</i>')}</span>
        <span class="bps-trio-meta"><b>${num(row.games)} 局</b><em>${rate(row.winRate)} 胜率</em></span>
        <span class="bps-trio-rel ${has(rel) ? (rel >= 0 ? 'is-good' : 'is-bad') : ''}">${has(rel) ? `${signed(rel)} pp` : '—'}</span>
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
      <span class="bps-cr-ci"><b class="bps-cr-wr">${rate(item.winRate)}</b>
        <small>胜率</small></span>
      <span class="bps-cr-num is-hide-sm">${deltaChip(item.deltaWin)}<small>环比</small></span>
      <span class="bps-cr-meta is-hide-sm">
        <span class="bps-badge ${item.relative == null ? 'is-low' : item.relative >= 0 ? 'is-good' : 'is-bad'}">${has(item.relative) ? `基准 ${signed(item.relative)}` : '基准 —'}</span>
      </span>
    </button>`;
    return `${section('combos', '02', '组合', '自选组合到底多强，联盟哪些组合在赢？')}
      <div class="bps-combo-layout">
        <div>
          ${heroPicker(state.comboPick, {action: 'combo', max: 3, placeholder: '选 2–3 个英雄查组合'})}
          <p class="bps-note" style="margin:8px 2px 0">选 2–3 个英雄，查同队同局战绩；再点一次取消。</p>
          ${comboCard()}
        </div>
        <div>
          <div class="bps-panel">
            <div class="bps-chart-head"><b>${state.comboSize === 2 ? '双人组合 · 组合卡' : '三人体系 · 组合卡'}</b>
              <span>头像 = 同队同局 · 数字 = 场次与胜率 · 绿/红 = 比基准高/低</span></div>
            <div class="bps-chart" style="padding:6px 14px 14px">${comboCards(sorted)}</div>
          </div>
          <div class="bps-board" style="margin-top:14px">
            <div class="bps-board-head">
              ${seg([['2', '双人组合'], ['3', '三人体系']], state.comboSize, 'data-bps-combo-size', {small: true})}
              ${seg([['usage', '按使用'], ['signal', '按胜率']], state.comboSort, 'data-bps-combo-sort', {small: true})}
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
      </div>
      ${lineupDiffPanel()}</section>`;
  }

  // ── 03 战队如何破解 ─────────────────────────────────────────────────
  function breakPrompt() {
    const pairs = (state.data.primary.combos.pairs || []).slice(0, 6);
    return `<div class="bps-empty"><b>先选一个目标</b>
      <p>目标可以是一个英雄，也可以是 2–3 个英雄的组合。选完会同时给出：KPL 历史上怎么应对、本队训练赛怎么应对、差在哪。</p>
      <div class="bps-faces-row" style="justify-content:center;margin-top:6px">
        ${pairs.map((row) => `<button type="button" class="bps-face" title="${esc(row.heroes.join('、'))}"
          data-bps-quick-target="${esc(row.heroes.join(','))}">
          ${row.heroes.map((hero) => heroImg(hero)).join('')}
          <small>${esc(row.heroes.map(heroShort).join(' + '))}</small><em>${num(row.games)} 局</em></button>`).join('')}
      </div></div>`;
  }

  /* 单英雄 Ban 手序：每个目标单独一行，第几手被 Ban 一眼看清，不用会和文字重叠的圆环。 */
  function banHandRowsHtml(block) {
    const byHero = block.banned?.byHero || [];
    if (!byHero.length) return '<p class="bps-note">没有可拆的 Ban 手序。试试扩大时间窗，或先切到「对手 / 我们」其中一方。</p>';
    return byHero.map((h) => {
      const max = Math.max(...h.hands.map((x) => x.count), 0);
      const peakIdx = max > 0 ? h.hands.findIndex((x) => x.count === max) : -1;
      const cells = h.hands.map((x, i) => `<span class="bps-bhcell ${max > 0 && x.count === max ? 'is-peak' : ''}" title="第${i + 1}手 ${num(x.count)} 次">${num(x.count)}</span>`).join('');
      return `<div class="bps-banhero">
        ${heroImg(h.hero)}
        <div class="bps-banhero-main"><b>${esc(heroShort(h.hero))}</b>
          <small>${num(h.total)} 次被 Ban${peakIdx >= 0 ? ` · 常在第 <b>${peakIdx + 1}</b> 手` : ''}</small></div>
        <div class="bps-banhands">${cells}</div>
      </div>`;
    }).join('');
  }
  /* 双人组合应对：对面拿到目标时，我们常一起拿的两个人 + 次数 + 胜率。 */
  function comboAnswersHtml(block) {
    const combos = block.answerCombos || [];
    if (!combos.length) return '<p class="bps-note">还没有稳定的双人组合应对（同框至少 3 次）。</p>';
    return combos.slice(0, 4).map((row) => `<div class="bps-comboans">
      <span class="bps-ca-faces">${(row.heroes || []).map((hero) => heroImg(hero)).join('')}</span>
      <span class="bps-ca-name">${esc(row.label)}</span>
      <span class="bps-ca-n">${num(row.count)} 次</span>
      <span class="bps-ca-wr">${rate(row.winRate)}</span>
    </div>`).join('');
  }

  function answerPanel(block, label, tone) {
    if (!block || !block.available) {
      return `<div class="bps-panel"><div class="bps-panel-head"><h3>${esc(label)}</h3></div>
        <div class="bps-panel-body"><div class="bps-empty"><b>没有可比较的样本</b>
          <p>${esc(block?.reason || '当前窗口里没有目标被拿到的记录。')}</p></div></div></div>`;
    }
    const answers = block.answers || [];
    const gap = !answers.length
      ? `<div class="bps-empty-compact"><b>当前窗口没有被完整放出的局</b>
          <span>Ban 数据仍然有效：${num(block.banned?.games)} 次被 Ban（${rate(block.banned?.share)}）。</span>
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
        </div>`).join('') || ''}
      </div>
      <div class="bps-panel-body" style="border-top:1px solid var(--bps-line-soft)">
        <div class="bps-subblock-head"><b>双人组合应对</b><span class="bps-sub">对面拿到目标时，我们一起拿的组合 · 胜率</span></div>
        ${comboAnswersHtml(block)}
      </div>
      <div class="bps-panel-body" style="border-top:1px solid var(--bps-line-soft)">
        <div class="bps-subblock-head"><b>目标各在第几手被 Ban</b><span class="bps-sub">每局各自的手序 · 格子＝第1–5手次数</span></div>
        ${banHandRowsHtml(block)}
        <p class="bps-note" style="margin-top:6px">Ban 率 ${rate(block.banned?.share)} · 首轮 ${num(block.banned?.firstRound)} 次 / 次轮 ${num(block.banned?.secondRound)} 次；被完整放出 ${num(block.completed?.games)} 局（胜率 ${rate(block.completed?.winRate)}）。</p>
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
        : '<span class="bps-sub">研究对象 · 待选（1–3 个英雄）</span>'}
      <button type="button" class="${picked.length ? 'bps-softbtn' : 'bps-link'}" data-bps-target-toggle>${picked.length ? '改目标' : '展开全部英雄'}</button>
    </div>`;
  }

  /* 按 BP 顺序把每一手（楼层）与其下一手应对并排，右侧可切视角。数据取已核验手序主线。 */
  function bpLadderHtml() {
    const view = state.breakView || 'ours';
    const tree = state.tree;
    const viewBox = `<label class="bps-ladder-view"><span>视角</span>
      <select data-bps-break-view aria-label="切换逐层推演视角">
        ${[['ours', '我方视角'], ['theirs', '对方视角'], ['target', '对手战队针对性']]
          .map(([value, label]) => `<option value="${value}" ${view === value ? 'selected' : ''}>${label}</option>`).join('')}
      </select></label>`;
    let body;
    if (!tree) {
      body = '<div class="bps-loading"><span class="bps-spinner"></span>正在读取已核验的 BP 手序…</div>';
    } else if (!tree.available || !(tree.main || []).length) {
      body = `<div class="bps-empty"><b>没有可推演的 BP 手序</b><p>${esc(tree.reason || '换个窗口或对手再试。')}</p></div>`;
    } else {
      const byId = new Map((tree.nodes || []).map((node) => [node.id, node]));
      const main = tree.main.map((id) => byId.get(id)).filter(Boolean);
      const ourSide = view === 'theirs' ? (tree.side === '1' ? '2' : '1') : (tree.side || '1');
      const who = (side) => view === 'target'
        ? esc(tree.opponent || state.opponent || '对手')
        : (String(side) === String(ourSide) ? '我方' : '对方');
      body = main.map((node, index) => {
        const next = main[index + 1];
        const camp = String(node.side) === '1' ? '蓝方' : String(node.side) === '2' ? '红方' : '手序';
        return `<div class="bps-ladder-row">
          <div class="bps-ladder-floor"><b>第 ${node.level} 手</b><span>${camp} · ${node.action === 'ban' ? 'Ban' : 'Pick'} · ${who(node.side)}</span></div>
          <div class="bps-ladder-hero">${heroImg(node.hero)}<b>${esc(heroShort(node.hero))}</b>
            <small>${num(node.count)} 局 · 胜率 ${rate(node.winRate)}</small></div>
          <div class="bps-ladder-arrow" aria-hidden="true">→</div>
          <div class="bps-ladder-answer">${next
            ? `${heroImg(next.hero)}<b>${esc(heroShort(next.hero))}</b><small>第 ${next.level} 手 · ${who(next.side)}回应 · ${num(next.count)} 局</small>`
            : '<span class="bps-sub">主线最后一手（Counter 位）</span>'}</div>
        </div>`;
      }).join('');
    }
    return `<div class="bps-panel bps-ladder-panel" data-bps-lazy="tree">
      <div class="bps-panel-head"><h3>应对分析 · 按 BP 顺序逐层推演</h3>
        <span class="bps-sub">楼层与应对并排 · 主线 = 样本最多的一条已核验路径</span>${viewBox}</div>
      <div class="bps-panel-body">${body}</div>
    </div>`;
  }

  /* 应对分析：和「逐层推演」互补——这里按楼层给出每种触发的回应分布，可下钻。 */
  function counterSection() {
    const sideItems = [['', '不限'], ['1', '我方蓝方'], ['2', '我方红方']];
    const boItems = [['0', '全部 BO'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7']];
    const sideName = (camp) => state.counterSide === '1'
      ? (camp === '1' ? '我方蓝方' : '敌方红方')
      : state.counterSide === '2'
        ? (camp === '1' ? '敌方蓝方' : '我方红方')
        : (camp === '1' ? '蓝方' : '红方');
    const stageLabel = (stage) => `${sideName(stage.camp)} ${stage.suffix}`;
    const stages = prefixStages(state.rule);
    const activeStage = stages.find((stage) => stage.key === state.counterPrefixStage)
      || stages[0];
    const stageButton = (stage) => {
      const picked = state.counterPrefix[stage.key] || [];
      const faces = picked.length
        ? `${picked.slice(0, 3).map((hero) => heroImg(hero)).join('')}${picked.length > 3 ? `<i>+${picked.length - 3}</i>` : ''}`
        : '<span class="bps-slot-empty" aria-hidden="true"></span>';
      return `<button type="button" class="bps-prefix-stage is-${stage.group} ${picked.length ? 'is-filled' : ''} ${stage.key === activeStage.key ? 'is-on' : ''}"
        data-bps-prefix-stage="${stage.key}" aria-pressed="${stage.key === activeStage.key}"
        aria-label="第 ${stage.hand} 手 · ${esc(stageLabel(stage))}${picked.length ? '：' + esc(picked.join('、')) : '，未指定'}"
        title="第 ${stage.hand} 手 · ${esc(stageLabel(stage))}${picked.length ? '：' + esc(picked.join('、')) : ''}">
        <span class="bps-slot-index">${String(stage.hand).padStart(2, '0')}</span>
        <span class="bps-slot-faces">${faces}</span>
        <span class="bps-slot-text"><b>${esc(stageLabel(stage))}</b>
          <small>${picked.length ? esc(picked.map((hero) => heroShort(hero)).join(' · ')) : '未指定'}</small></span>
      </button>`;
    };
    const prefixBox = `<fieldset class="bps-prefix-card">
      <legend class="bps-sr-only">前置条件</legend>
      <div class="bps-prefix-head">
        <div><h4>前置条件</h4><p>按真实 BP 手序填已确定的英雄，Ban 与 Pick 混在一起</p></div>
        <button type="button" class="bps-link" data-bps-prefix-clear>清空全部</button>
      </div>
      <div class="bps-prefix-body">
        <div class="bps-prefix-slots">
          <div class="bps-prefix-group">
            <span class="bps-prefix-group-label">BP 顺序 · 第几手（${state.rule === 'draft-18' ? '训练赛 18 手' : 'KPL 20 手'}）</span>
            <div class="bps-prefix-slot-grid">${stages.map(stageButton).join('')}</div>
          </div>
        </div>
        <div class="bps-prefix-picker">${heroPicker(state.counterPrefix[activeStage.key], {action: 'counterPrefix',
          max: activeStage.slots, placeholder: `点英雄设定「${stageLabel(activeStage)}」`})}</div>
      </div>
    </fieldset>`;
    const controls = `<div class="bps-counter-tools">
      <span class="bps-tool-group"><span class="bps-console-label">战队</span>
        ${seg([['all', '全部战队'], ['matchup', '本队 vs 对手']], state.counterTeamScope,
          'data-bps-counter-team', {small: true})}</span>
      <span class="bps-tool-group"><span class="bps-console-label">我方位置</span>
        ${seg(sideItems, state.counterSide, 'data-bps-counter-side', {small: true})}</span>
      <span class="bps-tool-group"><span class="bps-console-label">赛制</span>
        ${seg(boItems, String(state.counterBo), 'data-bps-counter-bo', {small: true})}</span>
      <span class="bps-tool-group">
        <input type="search" class="bps-counter-search" data-bps-counter-search
          value="${esc(state.counterSearch)}" placeholder="搜索英雄" aria-label="搜索英雄">
        <button type="button" class="bps-softbtn" data-bps-counter-retry>刷新</button>
      </span>
    </div>${prefixBox}`;
    let body;
    if (state.counterLoading && !state.counterData) {
      body = '<div class="bps-loading"><span class="bps-spinner"></span>正在按楼层统计应对…</div>';
    } else if (state.counterError) {
      body = `<div class="bps-inline-error">${esc(state.counterError)}
        <button type="button" class="bps-softbtn" data-bps-counter-retry>重试</button></div>`;
    } else if (!state.counterData) {
      body = '<div class="bps-loading"><span class="bps-spinner"></span>正在按楼层统计应对…</div>';
    } else if (state.counterData.available === false) {
      body = `<div class="bps-empty"><b>没有可分析的应对样本</b><p>${esc(state.counterData.reason || '换个筛选条件再试。')}</p></div>`;
    } else {
      const data = state.counterData;
      const scope = data.scope || {};
      const faces = (heroes) => (heroes || []).map((hero) => heroImg(hero)).join('');
      const card = (chain) => {
        const rows = chain.rows.filter((row) => !state.counterSearch
          || row.label.includes(state.counterSearch));
        return `<div class="bps-counter-card" data-bps-counter-chain="${esc(chain.key)}">
          <div class="bps-counter-head"><b>${esc(chain.title)}</b>
            <span class="bps-sub">${num(chain.rows.length)} 组触发 · ${state.counterOpen.startsWith(chain.key + '|') ? '点击收起回应' : '点击展开回应'}</span></div>
          <table class="bps-counter-table">
            <colgroup><col><col class="is-num"><col class="is-num"><col class="is-num"></colgroup>
            <thead><tr><th>英雄 / 组合</th><th class="is-num">场次</th>
              <th class="is-num">出场率</th><th class="is-num">胜率</th></tr></thead>
            <tbody>${rows.map((row) => {
              const key = `${chain.key}|${row.label}`;
              const open = state.counterOpen === key;
              return `<tr class="bps-counter-tr" data-bps-cd-row="${esc(key)}"
                tabindex="0" role="button" aria-expanded="${open}">
                <td><span class="bps-counter-face">${faces(row.heroes)}${esc(heroShort(row.label))}${row.games < 3 ? '<em class="bps-resp-tiny">小样本</em>' : ''}</span></td>
                <td class="is-num">${num(row.games)}</td>
                <td class="is-num">${rate(row.share)}</td>
                <td class="is-num">${rate(row.winRate)}</td>
              </tr>${open ? `<tr class="bps-counter-resp-row"><td colspan="4">
                <div class="bps-counter-resp-head">对手回应 · ${num(row.responseTotal)} 种 · 含 1 场小样本，全部列出</div>
                ${(row.responses || []).map((resp) => `<div class="bps-counter-resp${resp.games < 3 ? ' is-tiny' : ''}">
                  <span class="bps-counter-face">${faces(resp.heroes)}${esc(heroShort(resp.label))}${resp.games < 3 ? '<em class="bps-resp-tiny">小样本</em>' : ''}</span>
                  <span class="is-num">${num(resp.games)} 场</span>
                  <span class="is-num">${rate(resp.share)}</span>
                  <span class="is-num">${rate(resp.winRate)}</span>
                </div>`).join('') || '<p class="bps-note">这一层还没有回应记录。</p>'}
              </td></tr>` : ''}`;
            }).join('') || '<tr><td colspan="4" class="bps-note">没有匹配的英雄。换个关键词，或清空搜索框看全部。</td></tr>'}</tbody>
          </table>
        </div>`;
      };
      body = `<div class="bps-counter-scope">
        <span>已核验 <b>${num(scope.games)}</b> 局 · 逐层 <b>${num(scope.chains)}</b> 局${scope.prefixGames != null ? ` · 符合前置 <b>${num(scope.prefixGames)}</b> 局` : ''}</span>
        <span>${(state.counterTeamScope === 'matchup' || state.counterSide)
          ? `${esc(scope.team || state.team || '本队')} vs ${esc(scope.opponent || state.opponent || '对手')}`
          : '全部战队'}</span>
        <span>${scope.side === '1' ? '我方蓝方' : scope.side === '2' ? '我方红方' : '不限位置'} · ${scope.bo ? `BO${scope.bo}` : '全部 BO'}</span>
      </div>
      <div class="bps-counter-grid">${(data.chains || []).map(card).join('')}</div>`;
    }
    return `${section('counter', '07', '应对分析', '先定已选英雄，再看双方逐层怎么接？',
      '已选英雄 × 楼层 × 战队 × 先后手 × BO')}
      <div class="bps-panel-body" data-bps-counter>${controls}${body}</div>
    </section>`;
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
          <div class="bps-break-stat ${(kpl.split?.games || 0) === 0 ? 'is-zero' : ''}"><span>两边各拿一个</span><b>${num(kpl.split?.games)}</b>
            <small>全部被 Ban ${num(kpl.blocked?.games)} 局 · ${rate(kpl.blocked?.share)}</small></div>
        </div>
        <div class="bps-break-grid">
          ${answerPanel(kpl, `KPL 应对 · ${block.label}`, 'kpl')}
          ${answerPanel(own, `本队应对 · ${block.label}`, 'own')}
        </div>
        <div class="bps-hit is-plain" style="grid-template-columns:minmax(0,1fr)">
          <div class="bps-hit-figure"><b>${has(hit.value) ? rate(hit.value) : '—'}</b><span>命中率</span></div>
          <div class="bps-hit-copy">
            <b>本队应对里，${has(hit.value) ? rate(hit.value) : '—'} 落在 KPL 最常用的 8 个应对里</b>
            <p>${has(hit.value) ? `本队 ${num(hit.ownPicks)} 次应对；KPL 常用：${(hit.kplTop || []).map(esc).join('、') || '—'}。` : '本队还没有面对这个目标的训练赛样本，先积累再比较。'}
              Ban 率对比：KPL ${rate(compare.ban?.kplRate)} / 本队 ${rate(compare.ban?.ownRate)}
              （${has(compare.ban?.delta) ? `${signed(compare.ban.delta)} pp` : '—'}）。
              先验权重 KPL ${num(state.prior)}% / 训练赛 ${num(100 - state.prior)}%。</p>
            <div class="bps-blend" data-bps-blend>${blendPanel()}</div>
            ${(() => {
              const ch = compare.comboHit || {};
              if (!has(ch.value) && !ch.ownCombos) return '';
              return `<p class="bps-note" style="margin-top:6px"><b>组合命中率 ${has(ch.value) ? rate(ch.value) : '—'}</b>：本队 ${num(ch.ownCombos)} 次双人组合应对里，落在 KPL 常用组合的比例。</p>`;
            })()}
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
            ${(data.enemyNextTypes || []).length ? `<div class="bps-seq-types">${(data.enemyNextTypes || []).slice(0, 4).map((row) => {
              const groups = state.data?.types?.taxonomy?.groups || {};
              const lane = Object.keys(groups).find((key) => groups[key].includes(row.type)) || '';
              return `<span class="bps-seq-type" style="--type-color:${viz.LANE_COLOR[lane] || '#1f6fcf'}">${esc(row.type)} <b>${num(row.count)}</b></span>`;
            }).join('')}<small>共 ${num(data.enemyNextTypes.reduce((sum, row) => sum + (row.count || 0), 0))} 局</small></div>` : ''}
          </div>
        </div>
      </div>` : (data && !data.available ? `<div class="bps-empty"><b>没有符合的对局</b><p>${esc(data.reason || '')}</p></div>` : '')}
    </div>`;
  }

  /* 对手情报的三块卡片化替换：不用热力图/散点，直接给头像 + 数字。 */
  function banHandCards(hands) {
    const list = (hands || []).filter((hand) => (hand.heroes || []).length);
    if (!list.length) return '<div class="bps-empty">没有逐手 Ban 记录。</div>';
    return `<div class="bps-banhand-list">${list.map((hand) => `<div class="bps-banhand">
      <div class="bps-banhand-head"><b>第 ${num(hand.hand)} 手</b><span>${num(hand.games)} 局</span></div>
      <div class="bps-banhand-chips">${(hand.heroes || []).slice(0, 5).map((row) => `<span class="bps-banhand-chip">
        ${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b><em>${num(row.count)} 次</em></span>`).join('')}</div>
    </div>`).join('')}</div>`;
  }

  function statCards(rows, {countKey, countLabel, rateKey, empty, lowerIsBetter = false, rateLabel = '胜率'}) {
    const list = (rows || []).filter((row) => row.hero && has(row[rateKey]))
      .sort((a, b) => (b[countKey] || 0) - (a[countKey] || 0)).slice(0, 9);
    if (!list.length) return `<div class="bps-empty">${esc(empty)}</div>`;
    return `<div class="bps-stat-grid">${list.map((row) => `<div class="bps-stat-card">
      <span class="bps-stat-face">${heroImg(row.hero)}<b>${esc(heroShort(row.hero))}</b></span>
      <span class="bps-stat-num"><b>${num(row[countKey])}</b><small>${countLabel}</small></span>
      <span class="bps-stat-num ${lowerIsBetter
        ? ((row[rateKey] || 0) <= 45 ? 'is-good' : (row[rateKey] || 0) >= 55 ? 'is-bad' : '')
        : ((row[rateKey] || 0) >= 55 ? 'is-good' : (row[rateKey] || 0) <= 45 ? 'is-bad' : '')}"><b>${rate(row[rateKey])}</b><small>${rateLabel}</small></span>
    </div>`).join('')}</div>`;
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
          <div class="bps-panel-head"><h3>第 N 手 Ban 统计</h3><span class="bps-sub">每一手最常禁的英雄与次数</span></div>
          <div class="bps-panel-body">${banHandCards(block.banHands || [])}</div>
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
          <div class="bps-panel-head"><h3>他的英雄池 · Pick 与胜率</h3><span class="bps-sub">按 Pick 次数排序</span></div>
          <div class="bps-panel-body">${statCards(block.heroes, {countKey: 'picks', countLabel: '次 Pick', rateKey: 'winRate', empty: '当前窗口没有英雄池样本。'})}
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
          <div class="bps-panel-head"><h3>打他，什么有效</h3><span class="bps-sub">他拿到该英雄时的胜率 · 越低越好</span></div>
          <div class="bps-panel-body">
            ${statCards(block.counters, {countKey: 'games', countLabel: '局', rateKey: 'opponentWinRate', empty: '当前窗口没有对位样本。', lowerIsBetter: true, rateLabel: '他胜率'})}
          </div>
        </div>
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
        data-bps-decision-back="${index + 1}">${esc(heroShort(node.hero))}<em>${node.level}手 ${node.action === 'ban' ? 'BAN' : 'PICK'}</em></button>`))
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
      return `<option value="${esc(node.hero)}">${esc(node.hero)} · ${node.count} 局 · ${Math.round(share * 100)}%</option>`;
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
        水平展开前 ${next.length} 个分支；线宽 = 分支概率，节点条 = 该路径胜率。</div>
      <div class="bps-decision-tree">${viz.decisionTreeMap(state.tree, state.decisionPath,
        {width: 780, height: 420, branch: 3})}</div>
      <div class="bps-decision-manual">
        <span class="bps-console-label">手动指定下一手</span>
        <select data-bps-decision-hero>
          <option value="">选一个英雄…</option>${cards}
        </select>
        <button type="button" class="bps-softbtn" data-bps-decision-apply>走这手</button>
        <button type="button" class="bps-softbtn" data-bps-decision-pin-current>固定当前路径</button>
        <span class="bps-note">${esc(state.decisionNote || '')}</span>
      </div>
      ${pins ? `<div class="bps-decision-pins"><span class="bps-console-label">固定对比</span>${pins}</div>` : ''}
    </div>`;
  }

  function treeTakeaway(byType) {
    const nodes = state.tree?.nodes || [];
    const first = nodes.filter((node) => node.level === 1 && node.action === 'ban');
    if (!first.length) return '';
    const total = first.reduce((sum, node) => sum + (node.count || 0), 0);
    const top = [...first].sort((a, b) => (b.count || 0) - (a.count || 0))[0];
    const label = byType ? (top.type || '待分类') : heroShort(top.hero);
    const share = total ? Math.round((top.count || 0) / total * 100) : 0;
    return `当前 ${num(state.tree.games || 0)} 局样本里，第一手 Ban 集中在${label}（${num(top.count || 0)} 局，占首 Ban ${share}%）。悬停节点看它接下来最常见的走向。`;
  }

  function draftTreePanel() {
    return `<div class="bps-panel is-wide bps-tree-panel" data-bps-tree>
      <div class="bps-panel-head"><h3>BP 时序分支</h3>
        <span class="bps-sub">同一手同一英雄合并；线宽 = 局数；训练赛按征召规则展开手序</span></div>
      <div class="bps-panel-body">
        <p class="bps-tree-takeaway">${treeTakeaway(false)}</p>
        <div class="bps-tree-tools">
          <span class="bps-console-label">视图</span>${seg([['flow', '历史路径'], ['decision', '决策树']],
            state.treeMode, 'data-bps-tree-mode', {small: true})}
          ${state.treeMode === 'flow' ? `<span class="bps-console-label">深度</span>${seg([[6, '前六手'], [10, '前10手'], [18, '全18手'], [20, '全20手']],
            String(state.treeDepth), 'data-bps-tree-depth', {small: true})}
          <span class="bps-console-label">分叉</span>${seg([[2, '2 支'], [3, '3 支']],
            String(state.treeBranch), 'data-bps-tree-branch', {small: true})}
          <span class="bps-console-label">连线</span>${seg([['1', '精简'], ['0', '完整']],
            state.flowSimple ? '1' : '0', 'data-bps-flow-simple', {small: true})}` : ''}
          <span class="bps-console-label">看</span>${seg([['opponent', '对手'], ['own', '我们']],
            state.typeSide, 'data-bps-tree-side', {small: true})}
          <span class="bps-console-label">阵营</span>${seg([['', '自动'], ['1', '蓝方'], ['2', '红方']],
            state.treeSide, 'data-bps-tree-camp', {small: true})}
          ${state.treeMode === 'decision' ? `<span class="bps-console-label">阶段</span>
            <button type="button" class="bps-softbtn" data-bps-decision-phase="ban">从 Ban 开始</button>
            <button type="button" class="bps-softbtn" data-bps-decision-phase="pick">从第一个 Pick 开始</button>` : ''}
          ${state.tree?.available
            ? `<span class="bps-sub">已核验 ${num(state.tree.games)} / ${num(state.tree.total)} 局
              ${state.tree.sideCounts ? `· 蓝 ${num(state.tree.sideCounts['1'] || 0)} / 红 ${num(state.tree.sideCounts['2'] || 0)}` : ''}</span>` : ''}
          ${state.flowHero ? `<span class="bps-flow-start">起点：${esc(heroShort(state.flowHero))}
            <button type="button" data-bps-flow-start-clear aria-label="清除起点">×</button></span>` : ''}
        </div>
        ${state.treeMode === 'flow' && state.tree?.available ? `<div class="bps-flow-nav">
          <button type="button" class="bps-softbtn" data-bps-flow-left>← 向左</button>
          <button type="button" class="bps-softbtn" data-bps-flow-right>向右 →</button>
          <button type="button" class="bps-softbtn" data-bps-flow-up>↑ 向上</button>
          <button type="button" class="bps-softbtn" data-bps-flow-down>↓ 向下</button>
          <span>按住图面可上下左右自由拖动，点头像可设为起点</span>
          <button type="button" class="bps-softbtn" data-bps-flow-pick>跳到 Pick 阶段</button>
        </div>` : ''}
        ${state.treeMode === 'decision' ? decisionTreeHtml() : `
        ${state.treeLoading && !state.tree ? '<div class="bps-loading">正在按逐手事件建树…</div>' : ''}
        ${state.treeError ? `<div class="bps-inline-error">${esc(state.treeError)}</div>` : ''}
        ${state.tree?.available && state.tree.games < 8
          ? '<p class="bps-note">已核验手序不到 8 局，整张图只作方向参考，不当作稳定习惯。</p>' : ''}
        ${state.tree?.available && state.treeDepth >= 18
          ? '<p class="bps-note">手数较多，按住图面拖动或点方向键看完整路径。</p>' : ''}
        ${state.tree?.available ? `<div class="bps-tree-scroll">${viz.draftFlowMap(state.tree, {width: 1560, height: 680, maxEdges: state.flowSimple ? 36 : 0})}</div>
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

  /* 类型版 BP 时序：和英雄版同款分析，只是把节点换成英雄类型标签（五路 12 类）。 */
  function typeHandBreakdown(level) {
    const nodes = (state.tree?.nodes || []).filter((n) => n.level === level && n.type && n.count);
    if (!nodes.length) return '<p class="bps-note">这一手没有可统计的类型。</p>';
    const merged = new Map();
    for (const n of nodes) merged.set(n.type, (merged.get(n.type) || 0) + n.count);
    const total = [...merged.values()].reduce((a, b) => a + b, 0) || 1;
    const laneOf = (t) => {
      const groups = state.types?.taxonomy?.groups || {};
      return Object.keys(groups).find((lane) => groups[lane].includes(t)) || '';
    };
    return [...merged.entries()].sort((a, b) => b[1] - a[1]).map(([type, count]) => {
      const share = (count / total) * 100;
      const color = viz.LANE_COLOR[laneOf(type)] || '#246b63';
      return `<div class="bps-typebreak-row">
        <span class="bps-typebreak-name">${esc(type)}</span>
        <span class="bps-typebreak-track"><i style="width:${share.toFixed(1)}%;background:${color}"></i></span>
        <b>${share.toFixed(1)}%</b><small>${num(count)} 局</small>
      </div>`;
    }).join('');
  }

  function typeTreePanel() {
    const available = state.tree?.available;
    const focus = state.typeHandFocus;
    return `<div class="bps-panel is-wide bps-tree-panel bps-typetree" data-bps-typetree>
      <div class="bps-panel-head"><h3>BP 时序 · 类型</h3>
        <span class="bps-sub">和上面的时序同款分析，节点换成英雄类型（五路 12 类）；点一手看该手各类型占比</span></div>
      <div class="bps-panel-body">
        <p class="bps-tree-takeaway">${treeTakeaway(true)}</p>
        <div class="bps-tree-tools">
          <span class="bps-console-label">视图</span>${seg([['flow', '历史路径'], ['decision', '决策树']],
            state.typeTreeMode, 'data-bps-type-tree-mode', {small: true})}
          ${available ? `<span class="bps-console-label">连线</span>${seg([['1', '精简'], ['0', '完整']],
            state.flowSimple ? '1' : '0', 'data-bps-flow-simple', {small: true})}` : ''}
          ${available ? `<span class="bps-sub">类型来自英雄标签；线宽 = 局数</span>` : ''}
        </div>
        ${state.treeLoading && !state.tree ? '<div class="bps-loading">正在按逐手事件建树…</div>' : ''}
        ${available ? `<div class="bps-tree-scroll">${
          state.typeTreeMode === 'decision'
            ? viz.decisionTreeMap(state.tree, state.decisionPath, {width: 780, height: 480, branch: 3, byType: true})
            : viz.draftFlowMap(state.tree, {width: 1560, height: 680, byType: true, maxEdges: state.flowSimple ? 36 : 0})
        }</div>
          <div class="bps-tree-key bps-typetree-key">
            ${['对抗路', '打野', '中路', '发育路', '游走'].map((lane) => `<span><i class="is-lane" style="background:${viz.LANE_COLOR[lane]}"></i>${lane}</span>`).join('')}
            <span><i class="is-own-pick"></i>我方 Pick</span>
            <span><i class="is-own-ban"></i>我方 Ban</span>
            <span><i class="is-foe-pick"></i>对方 Pick</span>
            <span><i class="is-foe-ban"></i>对方 Ban</span>
            <span class="is-note">胶囊色 = 分路 · 线宽 = 局数</span>
          </div>
          ${focus ? `<div class="bps-typebreak">
            <div class="bps-typebreak-head"><b>第 ${focus} 手 · 各类型占比</b>
              <button type="button" class="bps-link" data-bps-type-break-close>收起 ×</button></div>
            ${typeHandBreakdown(focus)}
          </div>` : '<p class="bps-note">点上面任意一个类型节点，展开这一手的类型占比。</p>'}`
          : (state.tree ? `<div class="bps-empty"><b>还没有可画的类型时序</b><p>${esc(state.tree.reason || '')}</p></div>` : '')}
      </div>
    </div>`;
  }

  function typesSection() {
    const head = section('types', '05', '手序',
      '他第一手 Ban / 选的是什么类型？放到 BO 和时间里还成立吗？',
      '手序 × 赛制');
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
    const banMax = state.mode === 'scrim' ? 4 : 5;
    const handOptions = [['0', '全部']].concat(
      Array.from({ length: banMax }, (_, index) => [String(index + 1), `第${index + 1}手`]));
    const coreOptions = [['0', '全部'], ['2', '2核'], ['3', '3核'], ['4', '4核']];
    const focus = state.typeFocus;
    const tools = `<div class="bps-types-tools">
      <span class="bps-console-label">对象</span>${seg(sides, side, 'data-bps-type-side', {small: true})}
      <span class="bps-console-label">赛制</span>${seg(boOptions, String(state.typeBo), 'data-bps-type-bo', {small: true})}
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
    return `${head}${tools}
      ${draftTreePanel()}
      ${typeTreePanel()}
      <p class="bps-note" style="margin-top:10px">类型 = 五路 12 类；英雄类型来自赛训组标签。类型时序与英雄时序共用同一批已核验手序。</p></section>`;
  }

  /* 阵容差异：本队 vs 对手的双人组合三栏对照。
     2026-11-22 从「英雄异动」迁到 02 组合；英雄异动整节按赛训组反馈删除。 */
  function lineupDiffPanel() {
    const data = state.data;
    return `<div class="bps-panel" style="margin-top:16px">
      <div class="bps-panel-head"><h3>阵容差异</h3><span class="bps-sub">本队 vs ${esc(state.opponent || '对手')} 的双人组合</span></div>
      <div class="bps-panel-body">
        ${data.lineupDiff?.available ? `<div class="bps-diff-grid">
          <div class="bps-diff-col ${(data.lineupDiff.shared || []).length ? '' : 'is-empty'}"><h4>两边都在用</h4>${(data.lineupDiff.shared || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>本队 ${num(row.ownGames)} 局 ${rate(row.ownWinRate)} · 对手 ${num(row.enemyGames)} 局 ${rate(row.enemyWinRate)}</em></div>`).join('') || '<p class="bps-note">没有交集。</p>'}</div>
          <div class="bps-diff-col"><h4>只有本队在用</h4>${(data.lineupDiff.onlyUs || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>${num(row.games)} 局 · ${rate(row.winRate)} 胜率</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
          <div class="bps-diff-col"><h4>只有对手在用</h4>${(data.lineupDiff.onlyThem || []).map((row) => `<div class="bps-diff-item">${row.heroes.map((hero) => heroImg(hero)).join('')}<b>${esc(row.label)}</b><em>${num(row.games)} 局 · ${rate(row.winRate)} 胜率</em></div>`).join('') || '<p class="bps-note">—</p>'}</div>
        </div>` : '<div class="bps-empty"><b>还没有可对比的阵容</b><p>需要本队训练赛与对手同窗口的记录。</p></div>'}
      </div>
    </div>`;
  }

  /* 赛前方案直接引用 03 的应对结论：目标一换，这里跟着换，不再各写一套。 */
  function planResponseBlock() {
    const block = state.targetData;
    if (!block?.available) return '';
    const col = (data, label) => `<div class="bps-plan-res-col">
      <b>${esc(label)}</b>
      ${(data?.answers || []).slice(0, 4).map((row) => `<div class="bps-plan-res-row">
        ${heroImg(row.hero)}<span>${esc(heroShort(row.hero))}</span>
        <em>${num(row.count)} 次 · ${rate(row.winRate)}</em></div>`).join('') || '<p class="bps-note">样本不足。</p>'}
    </div>`;
    return `<div class="bps-panel bps-plan-response">
      <div class="bps-panel-head"><h3>针对「${esc(block.label)}」的应对 · 引用 03</h3>
        <span class="bps-sub">与破解页同一份目标数据；选目标后自动同步</span></div>
      <div class="bps-plan-response-grid">${col(block.kpl, 'KPL 应对')}${col(block.own, '本队应对')}</div>
    </div>`;
  }

  // ── 06 赛前方案 ─────────────────────────────────────────────────────
  function planSection() {
    const plan = state.data.plan;
    if (!plan?.available) {
      return `${section('plan', '06', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？')}
        <div class="bps-empty"><b>${esc(plan?.reason || '先选一个对手')}</b>
          <p>方案只按历史证据准备：对手常拿什么、我们 Ban 谁、被 Ban 之后本队第一手怎么接。</p></div></section>`;
    }
    const heroesOf = (label) => String(label || '').split('+').map((hero) => hero.trim()).filter(Boolean);
    const planRate = (n) => {
      if (!has(n)) return '—';
      const text = fmt(n, 1);
      return `${text.includes('.') ? text : `${text}.0`}%`;
    };
    const banItem = (row) => `<div class="bps-plan-item has-portrait" data-bps-plan-col="0">${heroImg(row.hero)}
      <div class="bps-plan-text"><b>${esc(heroShort(row.hero))}</b><small>${esc(row.reason || '')}</small></div>
      <em>${planRate(row.ourWinRate)}</em></div>`;
    const branch = (row) => `<div class="bps-plan-item bps-plan-branch has-portrait" data-bps-plan-col="1">
      ${heroImg(row.ban)}
      <div class="bps-plan-text"><b>对手 Ban ${esc(row.ban)}</b><small>${num(row.games)} 局</small></div>
      <div class="bps-plan-options">${(row.options || []).slice(0, 4).map((option) => `<span class="bps-plan-option">
        ${heroImg(option.hero)}<b>${esc(heroShort(option.hero))}</b><em>${num(option.count)}</em></span>`).join('') || '<span class="bps-sub">样本不足</span>'}</div>
    </div>`;
    const system = (row) => `<div class="bps-plan-item has-portrait" data-bps-plan-col="2">
      <span class="bps-plan-faces">${heroesOf(row.label).map((hero) => heroImg(hero)).join('')}</span>
      <div class="bps-plan-text"><b>${esc(row.label)}</b><small>${num(row.games)} 局 · 基准 ${has(row.relative) ? `${signed(row.relative)} pp` : '—'}</small></div>
      <em>${planRate(row.winRate)}</em></div>`;
    const firstBan = (plan.banPriority || [])[0];
    const firstBranch = (plan.branches || [])[0];
    const firstOption = (firstBranch?.options || [])[0];
    const firstSystem = (plan.ourSystems || [])[0];
    const step = (index, label, hero, text) => `<button type="button" class="bps-plan-step" data-bps-plan-step="${index}">
      <i>${index + 1}</i><span class="bps-plan-step-label">${esc(label)}</span>
      ${hero ? heroImg(hero) : ''}<b>${esc(text || (hero ? heroShort(hero) : '样本不足'))}</b></button>`;
    const flowStrip = firstBan ? `<div class="bps-plan-flow" aria-label="赛前推演">
      ${step(0, '先 Ban', firstBan.hero)}
      <span class="bps-plan-arrow" aria-hidden="true">→</span>
      ${step(1, '对手转 Ban', firstBranch?.ban, firstBranch ? heroShort(firstBranch.ban) : '')}
      <span class="bps-plan-arrow" aria-hidden="true">→</span>
      ${step(2, '我们接', firstOption?.hero || '', firstOption ? heroShort(firstOption.hero) : (firstSystem?.label || ''))}
    </div>` : '';
    const takeaway = firstBan
      ? `建议首 Ban ${heroShort(firstBan.hero)}：${firstBan.reason || `对手拿到后我方胜率 ${planRate(firstBan.ourWinRate)}`}。对方若转 Ban，按右侧两列接。`
      : '当前样本不足，先扩大时间窗或切换对手后再看结论。';
    return `${section('plan', '06', '赛前方案', '这场先 Ban 谁、被 Ban 之后怎么接？')}
      <p class="bps-plan-takeaway">${esc(takeaway)}</p>
      ${flowStrip}
      <div class="bps-plan-grid">
        <div class="bps-plan-col"><h4>优先 Ban</h4>
          ${(plan.banPriority || []).map(banItem).join('') || '<p class="bps-note">对手样本不足。试试扩大时间窗，或在筛选台切到具体对手。</p>'}</div>
        <div class="bps-plan-col"><h4>对手 Ban 之后我们接什么</h4>
          ${(plan.branches || []).map(branch).join('') || '<p class="bps-note">还没有足够的 Ban 后样本。可先在 02 组合里确认对手常 Ban 英雄。</p>'}</div>
        <div class="bps-plan-col"><h4>本队体系与威胁</h4>
          ${(plan.ourSystems || []).map(system).join('') || '<p class="bps-note">本队体系样本不足。切到「只看我们」并扩大时间窗后再看。</p>'}
          ${(plan.threats || []).length ? `<div class="bps-plan-threats"><b>对手常用</b>
            ${plan.threats.map((row) => `<span class="bps-plan-threat">${heroesOf(row.label).map((hero) => heroImg(hero)).join('')}
              <span>${esc(row.label)}</span><b>${planRate(row.winRate)}</b></span>`).join('')}</div>` : ''}</div>
      </div>
      ${planResponseBlock()}
      <p class="bps-note" style="margin-top:10px">${(plan.caveats || []).map(esc).join(' ')}</p></section>`;
  }

  // ── 组装 ────────────────────────────────────────────────────────────
  function skeleton() {
    return `<div class="bps">
      <header class="bps-hero" style="display:block;min-height:150px"></header>
      <p class="bps-loading" data-bps-loading>正在读取 BP 数据…</p>
      <div class="bps-skeleton">
        <div class="bps-sk" style="height:64px"></div>
        <div class="bps-sk" style="height:220px"></div>
        <div class="bps-sk" style="height:160px"></div>
      </div>
    </div>`;
  }

  /* 库里一条 BP 记录都没有：说清缺什么、下一步做什么，别摆一句「读不到」。 */
  function unavailableState(reason) {
    return `<div class="bps">
      <div class="bps-empty bps-unavailable">
        <b>还没有可分析的 BP 记录</b>
        <p>${esc(reason || '当前数据源还没有可用的 BP 记录。')}</p>
        <p class="bps-note">先把训练赛对局拿进来（营地同步，或截图 / 录屏），BP 页会按每方 Ban / Pick 顺序自动整理；想先看版式，也可以载入一份模拟数据。</p>
        <div class="bps-unavailable-actions">
          <a class="bps-primary" href="#ingest">去采集</a>
          <button type="button" class="bps-softbtn" data-bps-demo>载入模拟数据</button>
          <button type="button" class="bps-softbtn" data-bps-refresh>重新读取</button>
        </div>
      </div>
    </div>`;
  }

  function errorState() {
    return `<div class="bps"><div class="bps-empty" style="margin-top:40px">
      <b>BP 数据暂时读不到</b><p>${esc(state.error)}</p>
      <button type="button" class="bps-primary" data-bps-refresh>重新读取</button></div></div>`;
  }

  /* 重绘会替换整棵 DOM；记录当前控件的稳定标识，渲染后回焦，避免 Tab 顺序从头开始。 */
  function focusToken() {
    const el = document.activeElement;
    if (!el || !state.root?.contains(el)) return '';
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-bps-') && attr.name !== 'data-bps-section') {
        return `[${attr.name}="${String(attr.value).replace(/"/g, '\\"')}"]`;
      }
    }
    return '';
  }
  function restoreFocus(token) {
    if (!token) return;
    requestAnimationFrame(() => {
      try { state.root?.querySelector(token)?.focus({preventScroll: true}); } catch (_) { /* 忽略过时标识 */ }
    });
  }

  function paint() {
    if (!state.root || state.disposed) return;
    if (hoverNode) hoverNode.hidden = true;
    /* 解读浮层不随重绘强制关闭：其他分区异步加载完成时不应打断正在看的节点。 */
    const focus = focusToken();
    const y = window.scrollY;
    const treeScrolls = [...state.root.querySelectorAll('.bps-tree-scroll')]
      .map((el) => [el.scrollLeft, el.scrollTop]);
    if (state.loading && !state.data) state.root.innerHTML = skeleton();
    else if (state.error && !state.data) state.root.innerHTML = errorState();
    else if (!state.data) state.root.innerHTML = skeleton();
    else if (state.data.available === false) {
      state.root.innerHTML = unavailableState(state.data.reason);
    } else {
      const visible = state.solo ? [state.active] : SECTION_LIST.map(([key]) => key);
      state.root.innerHTML = `<div class="bps ${state.compact ? 'is-compact' : ''}">
        ${heroBand()}
        <div class="bps-sticky">
          ${jumpBar()}
          <div class="bps-filters">${consoleBar()}</div>
        </div>
        ${pinsBar()}
        ${sampleBanner()}
        <div class="bps-sections">
          ${visible.map((key) => SECTION_RENDER[key]()).join('')}
        </div>
        <button type="button" class="bps-top" data-bps-top hidden aria-label="回到顶部">${icon('arrow')}</button>
      </div>`;
    }
    if (y > 0) window.scrollTo(0, y);
    const treeAfter = state.root.querySelectorAll('.bps-tree-scroll');
    treeScrolls.forEach(([left, top], index) => {
      const el = treeAfter[index];
      if (!el) return;
      el.scrollLeft = left;
      el.scrollTop = top;
    });
    /* 重绘后把已保存的搜索词重新作用到英雄选择器，避免筛选态丢失。 */
    state.root?.querySelectorAll('input[data-bps-search]').forEach((input) => {
      filterPicker(input.dataset.bpsSearch, input.value);
    });
    restoreFocus(focus);
    applyZoom();
    decorateSections();
    observeLazy();
    bindFlowDrag();
    bindActiveObserver();
    updateActiveJump();
    if (state.typeHandFocus) {
      requestAnimationFrame(() => {
        state.root?.querySelector('.bps-typebreak')?.scrollIntoView({block: 'nearest'});
      });
    }
    requestAnimationFrame(syncSticky);
    // 单节模式直接进入 01 时，关系环在首屏下方，不能等滚动才请求。
    if (state.solo && state.active === 'heroes' && state.data
      && state.ringStale && !state.ringLoading) {
      setTimeout(() => {
        if (state.ringStale && !state.ringLoading) loadRing();
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
          else if (key === 'ring' && state.ringStale && !state.ringLoading) loadRing();
          else if (key === 'sequence' && state.seqStale && !state.seqLoading) loadSequence();
          else if (key === 'counter' && state.counterStale && !state.counterLoading) loadCounterChain();
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
    const ring = state.root.querySelector('[data-bps-ring]');
    if (ring && state.ringStale && !state.ringLoading) {
      ring.dataset.bpsLazy = 'ring';
      lazyObserver.observe(ring);
    }
    const breakTree = state.root.querySelector('[data-bps-lazy="tree"]');
    if (breakTree && state.treeStale && !state.treeLoading) {
      lazyObserver.observe(breakTree);
    }
    const seq = state.root.querySelector('.bps-seq');
    if (seq && state.seqStale) {
      seq.dataset.bpsLazy = 'sequence';
      lazyObserver.observe(seq);
    }
    const counter = state.root.querySelector('[data-bps-counter]');
    if (counter && state.counterStale && !state.counterLoading) {
      counter.dataset.bpsLazy = 'counter';
      lazyObserver.observe(counter);
    }
  }

  const SECTION_RENDER = {
    heroes: () => heroSection(), combos: () => comboSection(), break: () => breakSection(),
    opponent: () => opponentSection(), types: () => typesSection(),
    plan: () => planSection(), counter: () => counterSection(),
  };
  let sectionFrame = 0;

  function refreshSection(key) {
    const render = SECTION_RENDER[key];
    const current = state.root?.querySelector(`[data-bps-section="${key}"]`);
    if (!render || !current) { paint(); return; }
    const focus = focusToken();
    cancelAnimationFrame(sectionFrame);
    sectionFrame = requestAnimationFrame(() => {
      const holder = document.createElement('div');
      holder.innerHTML = render();
      const next = holder.firstElementChild;
      if (!next) return;
      current.replaceWith(next);
      restoreFocus(focus);
      decorateSections();
      applyZoom();
      observeLazy();
      bindFlowDrag();
      bindActiveObserver();
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

  /* 时序图节点解读：文字锚定在节点旁，和连线高亮指向同一处证据。 */
  let flowCallout = null;
  function ensureFlowCallout() {
    if (flowCallout) return flowCallout;
    flowCallout = document.createElement('div');
    flowCallout.className = 'bps-flow-callout';
    flowCallout.hidden = true;
    flowCallout.setAttribute('role', 'tooltip');
    document.body.appendChild(flowCallout);
    return flowCallout;
  }

  function showFlowCallout(node) {
    const callout = ensureFlowCallout();
    const svg = node.closest('svg');
    if (!svg) return;
    const key = node.dataset.flowNode;
    const title = node.querySelector('title')?.textContent || '';
    const count = (title.match(/(\d+)\s*局/) || [])[1] || '';
    const win = (title.match(/胜率\s*([\d.]+)%/) || [])[1] || '';
    const label = node.dataset.bpsTypeLevel
      ? `第 ${node.dataset.bpsTypeLevel} 手 · ${node.dataset.bpsTypeName || '待分类'}`
      : (node.dataset.bpsFlowHero || '该节点');
    const outgoing = [...svg.querySelectorAll('[data-flow-edge]')]
      .filter((path) => path.dataset.flowEdge.startsWith(`${key}>`))
      .sort((a, b) => Number(b.dataset.edgeCount || 0) - Number(a.dataset.edgeCount || 0))[0];
    let nextText = '这是当前样本里的末手。';
    if (outgoing) {
      const childKey = outgoing.dataset.flowEdge.slice(key.length + 1);
      const child = [...svg.querySelectorAll('[data-flow-node]')]
        .find((item) => item.dataset.flowNode === childKey);
      const nextLabel = child?.dataset.bpsTypeName || child?.dataset.bpsFlowHero || '下一手';
      nextText = `接下来最常走向${nextLabel}（${outgoing.dataset.edgeCount || 0} 局）。`;
    }
    callout.textContent = `${label}：${count ? `${count} 局` : '有样本'}${win ? `，胜率 ${win}%` : ''}。${nextText}`;
    callout.hidden = false;
    const rect = node.getBoundingClientRect();
    const size = callout.getBoundingClientRect();
    let left = rect.right + 14;
    if (left + size.width > window.innerWidth - 12) left = Math.max(12, rect.left - size.width - 14);
    let top = rect.top - 10;
    if (top + size.height > window.innerHeight - 12) top = Math.max(12, window.innerHeight - size.height - 12);
    callout.style.left = `${Math.round(left)}px`;
    callout.style.top = `${Math.round(top)}px`;
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
      <div class="bps-hover-foot">区间 ${interval(row.interval)} · ${(() => {
        const owner = anchor.closest?.('[data-hover-hint], [data-bps-hero-card]');
        if (owner?.dataset.hoverHint) return owner.dataset.hoverHint;
        if (owner?.hasAttribute('data-bps-hero-card') && /送到/.test(owner.getAttribute('title') || '')) {
          return '点击可送到 03 破解';
        }
        return '悬停查看样本区间';
      })()}</div>`;
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
    const trigger = except ? state.root.querySelector(`[data-bps-pop="${except}"]`) : null;
    state.root.querySelectorAll('[data-bps-pop-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.bpsPopPanel !== except;
      panel.classList.remove('is-up');
      if (panel.hidden) return;
      /* 浮层宽度大，贴触发器右缘后可能越过视口；按触发器位置钳制到可视区域。 */
      const groupRect = (panel.offsetParent || trigger || panel).getBoundingClientRect();
      const triggerRect = trigger ? trigger.getBoundingClientRect() : groupRect;
      const width = panel.offsetWidth;
      const desired = Math.max(12, Math.min(triggerRect.right - width, window.innerWidth - width - 12));
      panel.style.left = `${desired - groupRect.left}px`;
      panel.style.right = 'auto';
      const rect = panel.getBoundingClientRect();
      if (rect.bottom > window.innerHeight - 12 && rect.top > window.innerHeight * 0.4) {
        panel.classList.add('is-up');
      }
      panel.style.maxHeight = `${Math.max(220, Math.min(620, window.innerHeight - 40))}px`;
    });
    state.root.querySelectorAll('[data-bps-pop]').forEach((button) => {
      button.setAttribute('aria-expanded', String(button.dataset.bpsPop === except));
    });
  }

  /* 分区高亮改由 IntersectionObserver 负责：只在「视口中间带」被跨过时切换一次，
     不再每个 scroll 事件按 offsetTop 重算。原来筛选台收起会改变 sticky 高度，
     mark 跟着抖，两个分区在边界处来回抢高亮，看起来就是导航条闪烁。 */
  let activeObserver = null;
  function paintActiveJump() {
    if (!state.root) return;
    state.root.querySelectorAll('[data-bps-jump]').forEach((link) => {
      const active = link.dataset.bpsJump === state.active;
      if ((link.getAttribute('aria-pressed') === 'true') === active) return;
      link.classList.toggle('is-active', active);
      link.setAttribute('aria-pressed', String(active));
    });
  }
  function setActiveJump(key) {
    if (!key || key === state.active) return;
    state.active = key;
    paintActiveJump();
  }
  function computeActiveFromScroll() {
    if (!state.root || state.solo) return;
    const sections = [...state.root.querySelectorAll('[data-bps-section]')];
    if (!sections.length) return;
    const stickyH = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--bps-sticky-h')) || 120;
    const mark = window.scrollY + stickyH + 20;
    let active = sections[0].dataset.bpsSection;
    for (const item of sections) {
      if (item.offsetTop <= mark) active = item.dataset.bpsSection;
    }
    setActiveJump(active);
  }
  function bindActiveObserver() {
    activeObserver?.disconnect();
    activeObserver = null;
    if (!state.root || !('IntersectionObserver' in window)) return;
    const sections = [...state.root.querySelectorAll('[data-bps-section]')];
    if (!sections.length) return;
    activeObserver = new IntersectionObserver((entries) => {
      const hit = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (hit) setActiveJump(hit.target.dataset.bpsSection);
    }, { rootMargin: '-40% 0px -40% 0px', threshold: 0 });
    sections.forEach((section) => activeObserver.observe(section));
  }
  function updateActiveJump() {
    if (!state.root) return;
    if (!activeObserver) computeActiveFromScroll();
    paintActiveJump();
    const topButton = state.root.querySelector('[data-bps-top]');
    if (topButton) {
      const hide = window.scrollY < 600;
      if (topButton.hidden !== hide) topButton.hidden = hide;
    }
  }

  function filterPicker(action, text) {
    const picker = state.root?.querySelector(`[data-bps-picker="${action}"]`);
    if (!picker) return;
    const query = String(text || '').trim().toLowerCase();
    let visible = 0;
    picker.querySelectorAll('[data-bps-hero-name]').forEach((button) => {
      button.hidden = Boolean(query) && !button.dataset.bpsHeroName.toLowerCase().includes(query);
      if (!button.hidden) visible += 1;
    });
    const empty = picker.querySelector('.bps-picker-empty');
    if (empty) empty.hidden = visible > 0;
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
    if (!target) return;
    const sticky = state.root.querySelector('.bps-sticky');
    const bottom = sticky ? sticky.getBoundingClientRect().bottom : 0;
    const top = target.getBoundingClientRect().top + window.scrollY - bottom - 16;
    window.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
  }

  function onPick(action, hero) {
    if (action === 'counterPrefix') {
      const stages = prefixStages(state.rule);
      const stage = stages.find((item) => item.key === state.counterPrefixStage)
        || stages[0];
      const list = state.counterPrefix[stage.key];
      const index = list.indexOf(hero);
      if (index >= 0) list.splice(index, 1);
      else if (list.length < stage.slots) list.push(hero);
      else { list.shift(); list.push(hero); }
      persist(); refreshSection('counter'); loadCounterChain(); return;
    }
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
    /* 外层 .bps-focus 已是 button，这里不能再嵌 button。 */
    return `<span class="bps-pin ${on ? 'is-on' : ''}" data-bps-pin="${esc(spec)}"
      role="button" tabindex="0" aria-pressed="${on}"
      aria-label="${on ? '取消关注' : '加入我的关注'}"
      title="${on ? '取消关注' : '加入我的关注'}">${on ? '★' : '☆'}</span>`;
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
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
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
      if (action === 'counterPrefix') { onPick(action, pickRemove.dataset.bpsRemove); return; }
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

    if (event.target.closest('[data-bps-demo]')) {
      state.mode = 'scrim';
      state.source = 'scrim';
      state.rule = 'draft-18';
      normalizePrefixStage();
      state.demo = true;
      state.leagues = [];
      state.team = '本队';
      state.opponent = '';
      persist();
      load();
      return;
    }
    const modeButton = event.target.closest('[data-bps-mode]');
    if (modeButton) {
      applyMode(modeButton.dataset.bpsMode);
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
    const flowStartClear = event.target.closest('[data-bps-flow-start-clear]');
    if (flowStartClear) { state.flowHero = ''; state.treeStale = true; loadTree(); return; }
    const flowHero = event.target.closest('[data-bps-flow-hero]');
    if (flowHero && state.treeMode === 'flow' && !flowHero.hasAttribute('data-bps-type-level')) {
      const hero = flowHero.dataset.bpsFlowHero;
      if (hero && hero !== state.flowHero) {
        state.flowHero = hero;
        state.treeStale = true;
        persist();
        loadTree();
      }
      return;
    }
    const treeDepth = event.target.closest('[data-bps-tree-depth]');
    if (treeDepth) { state.treeDepth = Number(treeDepth.dataset.bpsTreeDepth); loadTree(); return; }
    const treeBranch = event.target.closest('[data-bps-tree-branch]');
    if (treeBranch) { state.treeBranch = Number(treeBranch.dataset.bpsTreeBranch); loadTree(); return; }
    const flowSimple = event.target.closest('[data-bps-flow-simple]');
    if (flowSimple) {
      state.flowSimple = flowSimple.dataset.bpsFlowSimple === '1';
      persist(); paint(); return;
    }
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
    const typeTreeMode = event.target.closest('[data-bps-type-tree-mode]');
    if (typeTreeMode) {
      state.typeTreeMode = typeTreeMode.dataset.bpsTypeTreeMode === 'decision' ? 'decision' : 'flow';
      paint();
      return;
    }
    const typeNode = event.target.closest('[data-bps-type-level]');
    if (typeNode) {
      state.typeHandFocus = Number(typeNode.dataset.bpsTypeLevel) || 0;
      paint();
      return;
    }
    const typeBreakClose = event.target.closest('[data-bps-type-break-close]');
    if (typeBreakClose) {
      state.typeHandFocus = 0;
      paint();
      return;
    }
    const flowLeft = event.target.closest('[data-bps-flow-left]');
    if (flowLeft) {
      state.root.querySelector('.bps-tree-scroll')?.scrollBy({left: -620, behavior: 'smooth'});
      return;
    }
    const flowRight = event.target.closest('[data-bps-flow-right]');
    if (flowRight) {
      state.root.querySelector('.bps-tree-scroll')?.scrollBy({left: 620, behavior: 'smooth'});
      return;
    }
    const flowUp = event.target.closest('[data-bps-flow-up]');
    if (flowUp) {
      state.root.querySelector('.bps-tree-scroll')?.scrollBy({top: -360, behavior: 'smooth'});
      return;
    }
    const flowDown = event.target.closest('[data-bps-flow-down]');
    if (flowDown) {
      state.root.querySelector('.bps-tree-scroll')?.scrollBy({top: 360, behavior: 'smooth'});
      return;
    }
    const flowPick = event.target.closest('[data-bps-flow-pick]');
    if (flowPick) {
      const scroller = state.root.querySelector('.bps-tree-scroll');
      if (scroller) scroller.scrollTo({left: scroller.scrollWidth * 0.48, behavior: 'smooth'});
      return;
    }
    const decisionPhase = event.target.closest('[data-bps-decision-phase]');
    if (decisionPhase) {
      const phase = decisionPhase.dataset.bpsDecisionPhase;
      const byId = new Map((state.tree?.nodes || []).map((node) => [node.id, node]));
      const main = (state.tree?.main || []).map((id) => byId.get(id)).filter(Boolean);
      if (phase === 'pick') {
        const index = main.findIndex((node) => node.action === 'pick');
        if (index > 0) {
          state.decisionPath = main.slice(0, index).map((node) => node.id);
          state.decisionNote = '';
        } else if (index === 0) {
          state.decisionPath = [];
          state.decisionNote = '';
        } else {
          state.decisionNote = '这段样本里没有 Pick 手序。';
        }
      } else {
        state.decisionPath = [];
        state.decisionNote = '';
      }
      paint();
      return;
    }
    const decisionPick = event.target.closest('[data-bps-decision-pick]');
    if (decisionPick) {
      state.decisionPath.push(...String(decisionPick.dataset.bpsDecisionPick).split(',').filter(Boolean));
      state.decisionNote = '';
      paint();
      return;
    }
    const decisionPin = event.target.closest('[data-bps-decision-pin]');
    if (decisionPin) {
      const route = [...state.decisionPath, ...String(decisionPin.dataset.bpsDecisionPin).split(',').filter(Boolean)];
      state.decisionPins = [...(state.decisionPins || []), route].slice(-3);
      paint();
      return;
    }
    if (event.target.closest('[data-bps-decision-pin-current]')) {
      if (state.decisionPath.length) {
        state.decisionPins = [...(state.decisionPins || []), [...state.decisionPath]].slice(-3);
        paint();
      }
      return;
    }
    if (event.target.closest('[data-bps-decision-apply]')) {
      const hero = state.root?.querySelector('[data-bps-decision-hero]')?.value || '';
      const nodes = state.tree?.nodes || [];
      const children = new Map();
      for (const node of nodes) {
        if (!children.has(node.parent)) children.set(node.parent, []);
        children.get(node.parent).push(node);
      }
      const parentKey = state.decisionPath.length ? state.decisionPath[state.decisionPath.length - 1] : '0';
      const hit = (children.get(parentKey) || []).find((node) => node.hero === hero);
      if (!hit) {
        state.decisionNote = hero ? `「${hero}」在已核验样本里没有出现，不能凭空展开。` : '先选一个英雄。';
        paint();
        return;
      }
      state.decisionPath.push(hit.id);
      state.decisionNote = '';
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
      if (action === 'counterPrefix') {
        state.counterPrefix[state.counterPrefixStage] = [];
        state.counterPrefixSearch = '';
        persist(); refreshSection('counter'); loadCounterChain(); return;
      }
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
    if (event.target.closest('[data-bps-counter-retry]')) { loadCounterChain(); return; }
    const counterTeam = event.target.closest('[data-bps-counter-team]');
    if (counterTeam) {
      state.counterTeamScope = counterTeam.dataset.bpsCounterTeam;
      if (state.counterTeamScope === 'all') state.counterSide = '';
      state.counterStale = true;
      state.counterOpen = '';
      loadCounterChain();
      return;
    }
    const counterSide = event.target.closest('[data-bps-counter-side]');
    if (counterSide) {
      state.counterSide = counterSide.dataset.bpsCounterSide;
      if (state.counterSide) state.counterTeamScope = 'matchup';
      state.counterStale = true;
      state.counterOpen = '';
      loadCounterChain();
      return;
    }
    const counterBo = event.target.closest('[data-bps-counter-bo]');
    if (counterBo) {
      state.counterBo = Number(counterBo.dataset.bpsCounterBo) || 0;
      state.counterStale = true;
      state.counterOpen = '';
      loadCounterChain();
      return;
    }
    const prefixStage = event.target.closest('[data-bps-prefix-stage]');
    if (prefixStage) {
      state.counterPrefixStage = prefixStage.dataset.bpsPrefixStage;
      persist(); refreshSection('counter'); return;
    }
    if (event.target.closest('[data-bps-prefix-clear]')) {
      for (const key of Object.keys(state.counterPrefix)) state.counterPrefix[key] = [];
      state.counterPrefixSearch = '';
      persist(); refreshSection('counter'); loadCounterChain(); return;
    }
    const counterDrill = event.target.closest('[data-bps-cd-row]');
    if (counterDrill) {
      const key = counterDrill.dataset.bpsCdRow;
      state.counterOpen = state.counterOpen === key ? '' : key;
      refreshSection('counter');
      return;
    }
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
    const breakView = event.target.closest('[data-bps-break-view]');
    if (breakView) {
      state.breakView = breakView.value;
      paint();
      return;
    }
    const counterSearch = event.target.closest('[data-bps-counter-search]');
    if (counterSearch) {
      state.counterSearch = counterSearch.value.trim();
      refreshSection('counter');
      return;
    }
    const ringLane = event.target.closest('[data-bps-ring-lane]');
    if (ringLane) {
      state.ringLane = ringLane.value;
      const heroes = state.data?.options?.heroes || [];
      const laneHeroes = heroes.filter((row) => !state.ringLane || row.lane === state.ringLane);
      if (laneHeroes.length && !laneHeroes.some((row) => row.name === state.ringHero)) {
        state.ringHero = laneHeroes[0].name;
      }
      loadRing();
      return;
    }
    const ringHero = event.target.closest('[data-bps-ring-hero]');
    if (ringHero) {
      state.ringHero = ringHero.value;
      loadRing();
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

  /* 时序图：悬停节点时高亮它的进出边，其余连线淡出，解开“毛球”。 */
  function highlightFlow(node, on) {
    const svg = node.closest('svg');
    if (!svg) return;
    const key = node.dataset.flowNode;
    svg.querySelectorAll('[data-flow-edge]').forEach((path) => {
      const edge = path.dataset.flowEdge;
      const linked = edge.startsWith(`${key}>`) || edge.endsWith(`>${key}`);
      path.classList.toggle('is-hot', on && linked);
      path.classList.toggle('is-dim', on && !linked);
    });
  }

  /* 推演条与下方三列双向联动：文字定位到证据，证据反指回文字。 */
  function linkPlan(index) {
    if (!state.root) return;
    state.root.querySelectorAll('[data-bps-plan-step]').forEach((node) => {
      node.classList.toggle('is-linked', Number(node.dataset.bpsPlanStep) === index);
    });
    state.root.querySelectorAll('[data-bps-plan-col]').forEach((node) => {
      const col = Number(node.dataset.bpsPlanCol);
      node.classList.toggle('is-linked', col === index);
      node.classList.toggle('is-dimmed', index >= 0 && col !== index);
    });
  }

  function onHoverIn(event) {
    const flow = event.target.closest?.('[data-flow-node]');
    if (flow && state.root?.contains(flow)) {
      highlightFlow(flow, true);
      showFlowCallout(flow);
    }
    const step = event.target.closest?.('[data-bps-plan-step]');
    const col = event.target.closest?.('[data-bps-plan-col]');
    if (step && state.root?.contains(step)) linkPlan(Number(step.dataset.bpsPlanStep));
    else if (col && state.root?.contains(col)) linkPlan(Number(col.dataset.bpsPlanCol));
    const node = event.target.closest?.('[data-hover-hero]');
    if (!node || !state.root?.contains(node)) return;
    showHover(node.dataset.hoverHero, node);
  }

  function onHoverOut(event) {
    if (event.target.closest?.('.bps-flow-callout')) {
      const next = event.relatedTarget?.closest?.('[data-flow-node], .bps-flow-callout');
      if (!next && flowCallout) flowCallout.hidden = true;
    }
    const flow = event.target.closest?.('[data-flow-node]');
    if (flow) {
      const next = event.relatedTarget?.closest?.('[data-flow-node], .bps-flow-callout');
      if (!next || next.closest('svg') !== flow.closest('svg')) {
        highlightFlow(flow, false);
        if (flowCallout && !flowCallout.contains(event.relatedTarget)) flowCallout.hidden = true;
      }
    }
    const step = event.target.closest?.('[data-bps-plan-step], [data-bps-plan-col]');
    if (step) {
      const next = event.relatedTarget?.closest?.('[data-bps-plan-step], [data-bps-plan-col]');
      if (!next || next.dataset.bpsPlanStep !== step.dataset.bpsPlanStep && next.dataset.bpsPlanCol !== step.dataset.bpsPlanCol) linkPlan(-1);
    }
    const node = event.target.closest?.('[data-hover-hero]');
    if (!node) return;
    const nextHero = event.relatedTarget?.closest?.('[data-hover-hero]');
    if (!nextHero) { if (hoverNode) hoverNode.hidden = true; }
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
    scrollBound = () => {
      if (hoverNode) hoverNode.hidden = true;
      if (flowCallout) flowCallout.hidden = true;
      /* 不再在滚动里改吸顶层的 padding / display：那会在 sticky 临界点触发
         scroll anchoring 补偿，把元素推离吸附位，来回 oscillation 就是闪烁。 */
      updateActiveJump();
    };
    resizeBound = () => { syncSticky(); updateActiveJump(); };
    keyBound = (event) => {
      if (event.key === 'Escape' && flowCallout) flowCallout.hidden = true;
      if (event.key === 'Enter' || event.key === ' ') {
        const drill = event.target?.closest?.('[data-bps-cd-row]');
        if (drill && state.root?.contains(drill)) {
          event.preventDefault();
          const key = drill.dataset.bpsCdRow;
          state.counterOpen = state.counterOpen === key ? '' : key;
          refreshSection('counter');
          return;
        }
        const pin = event.target?.closest?.('[data-bps-pin]');
        if (pin && state.root?.contains(pin)) {
          event.preventDefault();
          togglePin(pin.dataset.bpsPin);
          return;
        }
      }
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
    if (flowCallout) { flowCallout.remove(); flowCallout = null; }
    state.root?.removeEventListener('wheel', onWheel);
    state.root?.removeEventListener('pointerdown', onPointerDown);
    state.root?.removeEventListener('pointerdown', matrixPointerDown);
    state.root?.removeEventListener('pointermove', onPointerMove);
    state.root?.removeEventListener('pointermove', matrixPointerMove);
    state.root?.removeEventListener('pointerup', onPointerUp);
    state.root?.removeEventListener('pointerup', matrixPointerUp);
    clickBound = inputBound = scrollBound = resizeBound = keyBound = null;
  }

  function mount(root) {
    if (!root) return;
    /* 点当前导航会 load(true) 重渲同页：innerHTML 换掉了 root，但 document/window
       上的监听不会跟着消失。先解绑上一组再挂新的，避免每次重渲累积一套 handler。 */
    if (clickBound) unbind();
    state.root = root;
    state.disposed = false;
    restore();
    if (window.innerWidth < 900) state.compact = true;
    if (window.innerWidth < 760 && !Object.keys(state.collapsed || {}).length) {
      state.collapsed = {combos: true, types: true, plan: true};
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
