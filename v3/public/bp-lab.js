/* BP 概览 · 九个内容区驱动的研究页。
   数据源：/api/v3/bp-lab（KPL 含挑战者杯 / 训练赛分源）
   口径：KPL 只按每方 Pick/Ban 数组顺序统计“第 N 手”，不还原全局交错手序；
   版本为空时不按日期推断；训练赛默认 20 手（营地默认顺序），Ban 不足处只显示名单。 */
const FETCH_TIMEOUT = 30000;

export function createBpLab({esc, fmt, pct, icon, portrait, API_BASE}) {
  const state = {
    root: null, controller: null, partController: null, observer: null,
    source: 'kpl', league: 'all', team: '', opponent: '', from: '', to: '',
    view: 'database',
    unit: 'month', recentDays: 30, target: [], combo: [], rule: 'scrim-global-20', bo: 'BO5',
    lane: '', comboSort: 'usage', lookupText: '', lookup: null, lookupBusy: false,
    lookupOpen: false,
    counters: null, stability: null, data: null, loading: false, error: '',
    opponentResearch: null, opponentSide: '', opponentFirstPick: '',
    opponentCombo: [], opponentHero: '',
    sim: {rule: 'scrim-global-20', bo: 'BO5', gameNumber: 1, side: '1',
          events: [], evidenceSource: 'kpl', result: null, loading: false, error: ''},
    compare: null, compareLoading: false, compareError: '',
    opponentCompare: null, opponentCompareLoading: false, opponentCompareError: '',
    compareSeq: {focus: 0, opponent: 0},
    diagnose: null, diagnoseLoading: false, diagnoseError: '', diagnoseSeq: 0,
    diagnoseController: null, diagnoseHero: '', diagnoseEnemy: '',
    comboPick: [], comboDetail: null, comboDetailLoading: false,
    comboDetailError: '', comboDetailSeq: 0, comboDetailController: null,
    pendingAnchor: '',
    counterPickerOpen: false, stabilityPickerOpen: false,
  };

  const has = (n) => typeof n === 'number' && Number.isFinite(n);
  const num = (n) => has(n) ? fmt(n) : '—';
  const rate = (n) => has(n) ? pct(n) : '—';
  const interval = (arr) => Array.isArray(arr) && has(arr[0]) && has(arr[1])
    ? `${pct(arr[0])}–${pct(arr[1])}` : '—';
  const bar = (value, max = 100, cls = '') => {
    const width = has(value) && has(max) && max > 0
      ? Math.max(0, Math.min(100, value / max * 100)) : 0;
    return `<span class="bpl-bar ${cls}"><i style="width:${width}%"></i></span>`;
  };
  const heroChip = (hero, {small = false, count = null} = {}) =>
    `<span class="bpl-hero-chip${small ? ' is-small' : ''}">${portrait(hero, 'bpl-hero-img')}<span>${esc(hero)}</span>${count == null ? '' : `<em>${num(count)}</em>`}</span>`;
  const sampleBadge = (sample) => {
    const cls = sample === '样本充足' ? 'is-good' : sample === '小样本' ? 'is-mid' : 'is-low';
    return `<span class="bpl-badge ${cls}">${esc(sample || '样本不足')}</span>`;
  };
  const verdictBadge = (verdict) => {
    const cls = verdict === '有效（观察）' || verdict === '稳定' ? 'is-good'
      : verdict === '未达预期' || verdict === '波动大' ? 'is-bad'
      : verdict === '持平 / 待验证' || verdict === '有波动' ? 'is-mid' : 'is-low';
    return `<span class="bpl-badge ${cls}">${esc(verdict || '样本不足')}</span>`;
  };
  const metric = (label, value, note = '') =>
    `<div class="bpl-metric"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`;
  const empty = (title, note = '') =>
    `<div class="bpl-empty"><b>${esc(title)}</b>${note ? `<p>${esc(note)}</p>` : ''}</div>`;
  const note = (text) => text ? `<p class="bpl-note">${esc(text)}</p>` : '';
  const dataTable = (head, rows, {emptyText = '暂无记录', className = ''} = {}) =>
    `<div class="bpl-table-wrap"><table class="bpl-table ${className}"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('') : `<tr><td class="bpl-table-empty" colspan="${head.length}">${esc(emptyText)}</td></tr>`}</tbody></table></div>`;

  function parseHeroes(text) {
    return [...new Set(String(text || '').split(/[,，、+\s/]+/).map((s) => s.trim()).filter(Boolean))];
  }

  function baseParams(extra = {}) {
    const values = {source: state.source, ...extra};
    if (state.source === 'kpl') values.league = state.league;
    if (state.from) values.from = state.from;
    if (state.to) values.to = state.to;
    if (state.team) values.team = state.team;
    if (state.opponent) values.opponent = state.opponent;
    values.unit = state.unit;
    values.recentDays = state.recentDays;
    if (state.source === 'scrim') { values.rule = state.rule; values.bo = state.bo; }
    if (state.target.length) values.target = state.target.join(',');
    if (state.combo.length) values.combo = state.combo.join(',');
    return new URLSearchParams(values).toString();
  }

  async function api(path, signal) {
    const response = await fetch(`${API_BASE}/api/${path}`, {
      cache: 'no-store', signal, headers: {Accept: 'application/json'},
    });
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail || ''; } catch {}
      throw new Error(detail || `请求失败（HTTP ${response.status}）`);
    }
    return response.json();
  }

  function syncDefaults(data) {
    const units = data.options?.units || [state.unit];
    if (!state.target?.length) state.target = data.options?.target || [];
    if (!state.combo?.length) state.combo = data.options?.combo || [];
    if (!units.includes(state.unit)) state.unit = data.options?.unit || units[0] || 'month';
    if (state.source === 'scrim' && !['day', 'month'].includes(state.unit)) state.unit = 'day';
  }

  async function load() {
    if (!state.root) return;
    state.controller?.abort();
    state.controller = new AbortController();
    const controller = state.controller;
    state.loading = true;
    state.error = '';
    state.comboDetail = null;
    state.comboDetailLoading = false;
    state.comboDetailError = '';
    state.comboDetailSeq += 1;
    state.comboDetailController?.abort();
    paint();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
    try {
      const data = await api(`v3/bp-lab?${baseParams()}`, controller.signal);
      if (controller.signal.aborted) return;
      state.data = data;
      syncDefaults(data);
      state.opponentResearch = null;
      if (!state.opponentCombo?.length) {
        state.opponentCombo = data.opponentResearch?.situation?.combo || [];
      }
      if (!state.opponentHero) {
        state.opponentHero = data.opponentResearch?.situation?.hero || '';
      }
      state.loading = false;
      paint();
    } catch (error) {
      if (controller.signal.aborted) return;
      state.loading = false;
      state.error = error.message || '读取失败';
      paint();
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadCounters(target) {
    state.partController?.abort();
    state.partController = new AbortController();
    try {
      const values = {source: state.source, target: target.join(',')};
      if (state.source === 'kpl') values.league = state.league;
      if (state.from) values.from = state.from;
      if (state.to) values.to = state.to;
      const data = await api(`v3/bp-lab/counters?${new URLSearchParams(values)}`, state.partController.signal);
      if (state.partController.signal.aborted) return;
      state.counters = data;
      paint();
    } catch (error) {
      if (!state.partController.signal.aborted) {
        state.counters = {available: false, reason: error.message, rows: []};
        paint();
      }
    }
  }

  async function loadStability(combo) {
    state.partController?.abort();
    state.partController = new AbortController();
    try {
      const values = {source: state.source, combo: combo.join(','), unit: state.unit};
      if (state.source === 'kpl') values.league = state.league;
      if (state.team) values.team = state.team;
      if (state.from) values.from = state.from;
      if (state.to) values.to = state.to;
      const data = await api(`v3/bp-lab/stability?${new URLSearchParams(values)}`, state.partController.signal);
      if (state.partController.signal.aborted) return;
      state.stability = data;
      paint();
    } catch (error) {
      if (!state.partController.signal.aborted) {
        state.stability = {available: false, reason: error.message, windows: []};
        paint();
      }
    }
  }

  async function loadCompare(kind = 'focus') {
    if (!state.data) return;
    const opponentMode = kind === 'opponent';
    const valueKey = opponentMode ? 'opponentCompare' : 'compare';
    const loadingKey = opponentMode ? 'opponentCompareLoading' : 'compareLoading';
    const errorKey = opponentMode ? 'opponentCompareError' : 'compareError';
    const token = (state.compareSeq[kind] || 0) + 1;
    state.compareSeq[kind] = token;
    state[loadingKey] = true;
    state[errorKey] = '';
    paint();
    try {
      const team = opponentMode
        ? (state.opponent || state.data.options?.defaultOpponent || '')
        : (state.team || (state.source === 'scrim' ? '本队' : ''));
      const values = {source: state.source, recentDays: state.recentDays};
      if (state.source === 'kpl') values.league = state.league;
      if (team) values.team = team;
      if (!opponentMode && state.target?.length) values.target = state.target.join(',');
      if (state.from) values.from = state.from;
      if (state.to) values.to = state.to;
      const response = await fetch(`${API_BASE}/api/v3/bp-lab/compare?${new URLSearchParams(values)}`,
                                   {cache: 'no-store', headers: {Accept: 'application/json'}});
      if (!response.ok) {
        let detail = '';
        try { detail = (await response.json()).detail || ''; } catch {}
        throw new Error(detail || `时间对比失败（HTTP ${response.status}）`);
      }
      const payload = await response.json();
      if (state.compareSeq[kind] !== token) return;
      state[valueKey] = payload;
      state[loadingKey] = false;
      paint();
    } catch (error) {
      if (state.compareSeq[kind] !== token) return;
      state[loadingKey] = false;
      state[errorKey] = error.message || '时间对比失败';
      paint();
    }
  }

  function ensureCompare() {
    if (!state.data) return;
    if (!state.compare && !state.compareLoading && !state.compareError) {
      void loadCompare('focus');
    }
  }

  function ensureOpponentCompare() {
    if (state.view !== 'opponent' || !state.data) return;
    if (!state.opponentCompare && !state.opponentCompareLoading
        && !state.opponentCompareError) {
      void loadCompare('opponent');
    }
  }

  function diagnoseKey() {
    return JSON.stringify({
      source: state.source, league: state.source === 'kpl' ? state.league : '',
      team: state.team, hero: state.diagnoseHero, from: state.from, to: state.to,
      enemy: parseHeroes(state.diagnoseEnemy), recentDays: state.recentDays,
    });
  }

  async function loadDiagnose() {
    if (!state.data) return;
    const token = state.diagnoseSeq + 1;
    state.diagnoseSeq = token;
    state.diagnoseController?.abort();
    state.diagnoseController = new AbortController();
    state.diagnoseLoading = true;
    state.diagnoseError = '';
    paint();
    const values = {source: state.source, hero: state.diagnoseHero,
                    recentDays: state.recentDays};
    if (state.source === 'kpl') values.league = state.league;
    if (state.team) values.team = state.team;
    if (state.from) values.from = state.from;
    if (state.to) values.to = state.to;
    const enemy = parseHeroes(state.diagnoseEnemy);
    if (enemy.length) values.enemyLineup = enemy.join(',');
    try {
      const payload = await api(`v3/bp-lab/diagnose?${new URLSearchParams(values)}`,
                                state.diagnoseController.signal);
      if (state.diagnoseSeq !== token) return;
      if (payload.hero) state.diagnoseHero = payload.hero;
      state.diagnose = {...payload, _key: diagnoseKey()};
      state.diagnoseLoading = false;
      paint();
    } catch (error) {
      if (state.diagnoseSeq !== token || state.diagnoseController.signal.aborted) return;
      state.diagnoseLoading = false;
      state.diagnoseError = error.message || '诊断数据读取失败';
      paint();
    }
  }

  function ensureDiagnose(force = false) {
    if (state.view !== 'diagnose' || !state.data) return;
    const key = diagnoseKey();
    if (!force && state.diagnose?._key === key) return;
    if (!force && state.diagnoseLoading) return;
    void loadDiagnose();
  }

  function comboDetailKey() {
    return JSON.stringify({
      source: state.source, league: state.source === 'kpl' ? state.league : '',
      team: state.team, heroes: state.comboPick || [],
      recentDays: state.recentDays, from: state.from, to: state.to,
    });
  }

  async function loadComboDetail(force = false) {
    if (!state.data) return;
    const heroes = [...(state.comboPick || [])];
    if (heroes.length < 2) return;
    const key = comboDetailKey();
    if (!force && state.comboDetail?._key === key) return;
    const token = state.comboDetailSeq + 1;
    state.comboDetailSeq = token;
    state.comboDetailController?.abort();
    state.comboDetailController = new AbortController();
    state.comboDetailLoading = true;
    state.comboDetailError = '';
    paint();
    const values = {source: state.source, heroes: heroes.join(','),
                    recentDays: state.recentDays};
    if (state.source === 'kpl') values.league = state.league;
    if (state.team) values.team = state.team;
    if (state.from) values.from = state.from;
    if (state.to) values.to = state.to;
    try {
      const payload = await api(`v3/bp-lab/combo?${new URLSearchParams(values)}`,
                                state.comboDetailController.signal);
      if (state.comboDetailSeq !== token) return;
      state.comboDetail = {...payload, _key: comboDetailKey()};
      state.comboDetailLoading = false;
      paint();
    } catch (error) {
      if (state.comboDetailSeq !== token
          || state.comboDetailController.signal.aborted) return;
      state.comboDetailLoading = false;
      state.comboDetailError = error.message || '组合数据读取失败';
      paint();
    }
  }

  function ensureComboDetail() {
    if (state.view !== 'database' || !state.data || state.loading) return;
    if ((state.comboPick || []).length < 2) return;
    if (state.comboDetailLoading) return;
    if (state.comboDetail?._key === comboDetailKey()) return;
    void loadComboDetail();
  }

  function heroCompareMap(compare) {
    return new Map(((compare && compare.heroes) || []).map((row) => [row.hero, row]));
  }

  function comboCompareMap(compare) {
    return new Map(((compare && compare.combos) || []).map((row) => [row.label, row]));
  }

  async function loadOpponentResearch() {
    state.partController?.abort();
    state.partController = new AbortController();
    try {
      const opponent = state.opponent || state.data?.options?.defaultOpponent || '';
      const values = {source: state.source, opponent};
      if (state.source === 'kpl') values.league = state.league;
      if (state.from) values.from = state.from;
      if (state.to) values.to = state.to;
      if (state.opponentSide) values.side = state.opponentSide;
      if (state.opponentFirstPick) values.firstPick = state.opponentFirstPick;
      if (state.opponentCombo?.length) values.combo = state.opponentCombo.join(',');
      if (state.opponentHero) values.hero = state.opponentHero;
      const data = await api(`v3/bp-lab/opponent?${new URLSearchParams(values)}`,
                             state.partController.signal);
      if (state.partController.signal.aborted) return;
      state.opponentResearch = data;
      if (data.situation) {
        state.opponentSide = data.situation.side || '';
        state.opponentFirstPick = data.situation.firstPick || '';
        state.opponentCombo = data.situation.combo || [];
        state.opponentHero = data.situation.hero || '';
      }
      paint();
    } catch (error) {
      if (!state.partController.signal.aborted) {
        state.opponentResearch = {available: false, reason: error.message};
        paint();
      }
    }
  }

  async function loadLookup(heroes) {
    if (!heroes.length) return;
    state.partController?.abort();
    state.partController = new AbortController();
    state.lookupBusy = true;
    state.lookup = null;
    paint();
    try {
      const values = {source: state.source, heroes: heroes.join(',')};
      if (state.source === 'kpl') values.league = state.league;
      if (state.from) values.from = state.from;
      if (state.to) values.to = state.to;
      const data = await api(`v3/bp-lab/lookup?${new URLSearchParams(values)}`, state.partController.signal);
      if (state.partController.signal.aborted) return;
      state.lookup = data;
      state.lookupBusy = false;
      paint();
    } catch (error) {
      if (state.partController.signal.aborted) return;
      state.lookup = {available: false, reason: error.message};
      state.lookupBusy = false;
      paint();
    }
  }

  // -------------------------------------------------------------------------
  // 页面骨架
  // -------------------------------------------------------------------------
  function hero() {
    const scope = state.data?.scope || {};
    const sourceLabel = state.source === 'kpl'
      ? (state.league === 'challenger' ? 'KPL · 挑战者杯' : state.league === 'kpl' ? 'KPL · 联赛' : 'KPL · 含挑战者杯')
      : '训练赛 · 营地面板';
    const rows = state.data?.heroes?.rows || [];
    const topPick = [...rows].sort((a, b) => (b.pickRate || 0) - (a.pickRate || 0))[0];
    const topBan = [...rows].sort((a, b) => (b.banRate || 0) - (a.banRate || 0))[0];
    const headline = topPick && topBan ? `${topPick.hero} Pick 最高，${topBan.hero} Ban 最高` : 'BP 概览';
    const lede = topPick && topBan
      ? `${scope.matches ? `${num(scope.matches)} 局里，` : ''}${topPick.hero} Pick 率 ${rate(topPick.pickRate)}，${topBan.hero} Ban 率 ${rate(topBan.banRate)}。先看优先级，再看组合、对手和训练赛。`
      : '从英雄池与组合强度，到指定对手研究、选禁习惯和明天的准备方案。';
    return `<header class="bpl-hero">
      <div class="bpl-hero-copy">
        <span class="bpl-eyebrow">BP LAB <i></i> 赛前研究</span>
        <h1>${esc(headline)}</h1>
        <p>${esc(lede)}</p>
      </div>
      <div class="bpl-hero-facts">
        <div><span>数据源</span><b>${esc(sourceLabel)}</b></div>
        <div><span>覆盖</span><b>${scope.matches ? `${num(scope.matches)} 局` : (state.loading ? '读取中' : '—')}</b></div>
        <div><span>时间</span><b>${scope.from ? `${esc(String(scope.from).slice(0, 7))} → ${esc(String(scope.to).slice(0, 7))}` : '—'}</b></div>
        <div><span>版本</span><b>${scope.versionAvailable ? `${scope.versions.length} 个已记录` : '未记录'}</b></div>
      </div>
    </header>`;
  }

  function toolbar() {
    const data = state.data || {};
    const options = data.options || {};
    const teams = options.teams || [];
    const units = options.units || (state.source === 'scrim' ? ['day'] : ['month', 'season', 'stage']);
    const teamOptions = `<option value="" ${state.team ? '' : 'selected'}>自动 · ${esc(options.defaultTeam || '按数据')}</option>${teams.map((name) => `<option value="${esc(name)}" ${name === state.team ? 'selected' : ''}>${esc(name)}</option>`).join('')}`;
    const opponentOptions = `<option value="" ${state.opponent ? '' : 'selected'}>自动 · ${esc(options.defaultOpponent || '按数据')}</option>${teams.map((name) => `<option value="${esc(name)}" ${name === state.opponent ? 'selected' : ''}>${esc(name)}</option>`).join('')}`;
    const unitLabels = {day: '按日', month: '按月', season: '按赛季', stage: '按阶段'};
    return `<div class="bpl-toolbar">
      <div class="bpl-segment" role="group" aria-label="数据源">
        <button type="button" data-bpl-source="kpl" aria-pressed="${state.source === 'kpl'}">KPL 赛事</button>
        <button type="button" data-bpl-source="scrim" aria-pressed="${state.source === 'scrim'}">训练赛</button>
      </div>
      ${state.source === 'kpl' ? `<label class="bpl-field">赛事
        <select data-bpl-field="league">
          <option value="all" ${state.league === 'all' ? 'selected' : ''}>全部（含挑战者杯）</option>
          <option value="kpl" ${state.league === 'kpl' ? 'selected' : ''}>KPL 联赛</option>
          <option value="challenger" ${state.league === 'challenger' ? 'selected' : ''}>挑战者杯</option>
        </select></label>` : ''}
      <label class="bpl-field">本队
        <select data-bpl-field="team">${teamOptions || '<option value="">自动</option>'}</select></label>
      <label class="bpl-field">对手
        <select data-bpl-field="opponent">${opponentOptions || '<option value="">自动</option>'}</select></label>
      <label class="bpl-field bpl-date">起
        <input type="date" data-bpl-field="from" value="${esc(state.from)}"></label>
      <label class="bpl-field bpl-date">止
        <input type="date" data-bpl-field="to" value="${esc(state.to)}"></label>
      <label class="bpl-field">近期
        <select data-bpl-field="recentDays">${(options.recentOptions || [7, 15, 30]).map((days) => `<option value="${days}" ${days === state.recentDays ? 'selected' : ''}>近 ${days} 天</option>`).join('')}</select></label>
      <label class="bpl-field">窗口
        <select data-bpl-field="unit">${units.map((unit) => `<option value="${unit}" ${unit === state.unit ? 'selected' : ''}>${esc(unitLabels[unit] || unit)}</option>`).join('')}</select></label>
      <button type="button" class="bpl-refresh" data-bpl-refresh aria-label="刷新数据">${icon('refresh')}</button>
    </div>
    <div class="bpl-scope">
      <span class="bpl-scope-chip">${state.source === 'kpl' ? 'KPL 与训练赛不混算' : '训练赛只作本批观察'}</span>
      <span class="bpl-scope-chip">${state.source === 'kpl' ? '每方手序（非全局交错）' : '营地默认 20 手'}</span>
      <span class="bpl-scope-chip">${data.scope?.versionAvailable ? '版本已记录' : '版本未记录'}</span>
      <p>${state.source === 'kpl' ? 'KPL 含挑战者杯；第一手 / Ban 后选择按该队数组顺序统计。' : '训练赛来自本机营地面板；对手多为占位名，组合样本少时只作单场观察。'}</p>
    </div>`;
  }

  const JUMPS = [
    ['heroes', '英雄'], ['combos', '组合'], ['opponent', '对手'], ['counters', '破解'],
    ['habits', '习惯'], ['evolution', '演变'],
    ['scrim', '训练赛'], ['stability', '稳定'], ['plan', '方案'], ['simulate', '沙盘'],
  ];
  const VIEWS = [
    {id: 'database', label: '英雄与组合数据库', hint: '英雄 / 组合 / 反制', sections: ['heroes', 'combos', 'counters']},
    {id: 'opponent', label: '对手 BP 情报', hint: '行为 / 习惯 / 演变', sections: ['opponent', 'habits', 'evolution']},
    {id: 'scrim', label: '己方训练赛评估', hint: '体系 / 稳定', sections: ['scrim', 'stability']},
    {id: 'diagnose', label: '己方英雄诊断', hint: '表现 / 异常 / 归因', sections: ['diagnosePerf', 'diagnoseTrend', 'diagnoseAnomaly', 'diagnoseLocate', 'diagnoseAttribution', 'diagnoseLineup'],
     jumps: [['diagnosePerf', '表现', '01'], ['diagnoseTrend', '趋势', '02'], ['diagnoseAnomaly', '异常', '03'],
             ['diagnoseLocate', '定位', '04'], ['diagnoseAttribution', '归因', '05'], ['diagnoseLineup', '阵容', '06']]},
    {id: 'simulate', label: 'BP 策略模拟', hint: '候选 / 回应', sections: ['plan', 'simulate']},
  ];
  const activeView = () => VIEWS.find((view) => view.id === state.view) || VIEWS[0];
  function viewTabs() {
    return `<nav class="bpl-views" aria-label="BP 分析视图">${VIEWS.map((view) =>
      `<button type="button" data-bpl-view="${view.id}" aria-pressed="${state.view === view.id}"><b>${esc(view.label)}</b><span>${esc(view.hint)}</span></button>`).join('')}</nav>`;
  }
  function jumpNav() {
    const view = activeView();
    const entries = view.jumps || view.sections.map((key) => {
      const index = JUMPS.findIndex(([id]) => id === key);
      return [key, JUMPS[index]?.[1] || key, index + 1];
    });
    return `<nav class="bpl-jump" aria-label="BP 内容导航">${entries.map(([key, label, number]) =>
      `<button type="button" data-bpl-jump="${key}"><i>${esc(String(number).padStart(2, '0'))}</i>${esc(label)}</button>`).join('')}</nav>`;
  }

  const TIME_SECTIONS = new Set(['heroes', 'combos', 'opponent', 'counters', 'habits',
    'evolution', 'scrim', 'stability', 'plan', 'diagnosePerf']);

  function sectionTimeBar(id) {
    if (!TIME_SECTIONS.has(id)) return '';
    const custom = Boolean(state.from || state.to);
    const range = custom
      ? `${state.from || '…'} → ${state.to || '…'}`
      : `近 ${state.recentDays} 天`;
    return `<div class="bpl-section-timebar" data-bpl-timebar="${id}">
      <span class="bpl-timebar-label">时间窗</span>
      <div class="bpl-segment bpl-segment-small" role="group" aria-label="本区时间窗（全页同步）">
        ${[7, 15, 30].map((days) => `<button type="button" data-bpl-section-days="${days}" data-bpl-section-anchor="${id}" aria-pressed="${!custom && state.recentDays === days}">近 ${days} 天</button>`).join('')}
      </div>
      ${custom ? `<span class="bpl-muted">${esc(range)}</span><button type="button" class="bpl-link" data-bpl-section-clear="${id}">改回近 ${state.recentDays} 天</button>` : '<span class="bpl-muted">全页同步</span>'}
    </div>`;
  }

  function section(id, number, title, question, meta, body) {
    return `<section class="bpl-section" id="bpl-${id}" data-bpl-section="${id}">
      <header class="bpl-section-head">
        <span class="bpl-number">${number}</span>
        <div><h2>${esc(title)}</h2><p>${esc(question)}</p></div>
        ${meta || ''}
      </header>
      ${sectionTimeBar(id)}
      ${body}
    </section>`;
  }

  // -------------------------------------------------------------------------
  // 01 英雄优先级
  // -------------------------------------------------------------------------
  function heroesSection(data) {
    const board = data.heroes || {};
    const rows = board.rows || [];
    const lanes = board.lanes || [];
    if (!rows.length) return section('heroes', '01', '英雄优先级', '当前版本哪些英雄值得优先考虑？', '', empty('当前范围没有英雄记录', '换数据源或放宽时间范围。'));
    if (state.lane && !lanes.includes(state.lane)) state.lane = '';
    const laneRows = state.lane ? (board.byLane?.[state.lane] || []) : rows;
    const topRows = laneRows.slice(0, 12);
    const topPick = [...rows].sort((a, b) => (b.pickRate || 0) - (a.pickRate || 0))[0];
    const topBan = [...rows].sort((a, b) => (b.banRate || 0) - (a.banRate || 0))[0];
    const laneTabs = `<div class="bpl-tabs" role="group" aria-label="分路筛选">
      <button type="button" data-bpl-lane="" class="${state.lane ? '' : 'is-active'}">全部</button>
      ${lanes.map((lane) => `<button type="button" data-bpl-lane="${esc(lane)}" class="${state.lane === lane ? 'is-active' : ''}">${esc(lane)}</button>`).join('')}
    </div>`;
    const scopeLabel = state.team ? `本队 · ${state.team}` : '联盟大盘';
    const kpiGames = state.team ? board.total : data.scope?.matches;
    const kpiNote = state.team ? `${num(board.total)} 队-局` : `队-局 ${num(board.total)}`;
    const focusHeroes = heroCompareMap(state.compare);
    const table = dataTable(['英雄', '分路', 'Pick', 'Pick 率', 'Ban 率', '胜率', '样本', '判断'], laneRows.map((row) => {
      const cmp = focusHeroes.get(row.hero);
      return [
        `<div class="bpl-hero-cell">${heroChip(row.hero)}</div>`,
        `<span class="bpl-muted">${esc(row.lane || '—')}</span>`,
        `<b>${num(row.picks)}</b>`,
        `<div class="bpl-num-bar"><span>${rate(row.pickRate)}</span>${bar(row.pickRate, 100)}${cmp ? deltaLine(cmp.pickDelta, cmp.pickDeltaYoy) : ''}</div>`,
        `<div class="bpl-num-bar is-ban"><span>${rate(row.banRate)}</span>${bar(row.banRate, 100, 'is-ban')}${cmp ? deltaLine(cmp.banDelta, cmp.banDeltaYoy) : ''}</div>`,
        `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</div>`,
        sampleBadge(row.sample),
        `<span class="bpl-signal">${esc(row.signal || '常规')}</span>`,
      ];
    }), {emptyText: '当前分路没有英雄记录'});
    const laneBoard = lanes.map((lane) => {
      const laneRows = (board.byLane?.[lane] || []).slice(0, 3);
      return `<div class="bpl-lane-card"><div class="bpl-lane-head"><b>${esc(lane)}</b><span>${num(laneRows[0]?.picks || 0)} 次最高</span></div>
        ${laneRows.map((row) => `<div class="bpl-lane-row">${heroChip(row.hero, {small: true})}<span>${rate(row.pickRate)}</span></div>`).join('') || '<span class="bpl-muted">暂无</span>'}</div>`;
    }).join('');
    const stat = (label, value, count, ratio, tone) => `<div class="bpl-tile-stat ${tone}">
      <span>${label}</span><b>${value}</b>
      <small>${num(count)} 次</small>
      <i class="bpl-tile-bar"><b style="width:${Math.max(1, Math.min(100, ratio || 0)).toFixed(1)}%"></b></i>
    </div>`;
    const tiles = topRows.map((row) => `<article class="bpl-hero-tile">
      <header>
        <span class="bpl-tile-ava">${portrait(row.hero, 'bpl-tile-img')}</span>
        <span class="bpl-tile-id"><b>${esc(row.hero)}</b><small>${esc(row.lane || '—')}</small></span>
      </header>
      <div class="bpl-tile-stats">
        ${stat('Pick', rate(row.pickRate), row.picks, row.pickRate, 'is-pick')}
        ${stat('Ban', rate(row.banRate), row.bans, row.banRate, 'is-ban')}
      </div>
      <div class="bpl-tile-win"><span>胜率</span><b class="${row.winRate >= 55 ? 'is-up' : row.winRate <= 45 ? 'is-down' : ''}">${rate(row.winRate)}</b><small>${interval(row.interval)}</small></div>
      <footer>${sampleBadge(row.sample)}</footer>
    </article>`).join('');
    const body = `<div class="bpl-factline">
      <span>覆盖 <b>${num(kpiGames)}</b> 局</span>
      <span>最高 Pick <b>${topPick ? esc(topPick.hero) : '—'}</b>${topPick ? ` ${rate(topPick.pickRate)}` : ''}</span>
      <span>最高 Ban <b>${topBan ? esc(topBan.hero) : '—'}</b>${topBan ? ` ${rate(topBan.banRate)}` : ''}</span>
      <span>版本 <b>${data.scope?.versionAvailable ? '已记录' : '未记录'}</b></span>
    </div>
    <div class="bpl-card bpl-hero-board">
      <div class="bpl-card-head">${laneTabs}<span class="bpl-muted">按 Pick + Ban 热度排序</span></div>
      <div class="bpl-hero-grid">${tiles}</div>
      <details class="bpl-details"><summary>逐英雄明细（全部 ${laneRows.length} 个）</summary>${table}</details>
    </div>
    <div class="bpl-card bpl-lane-panel"><div class="bpl-card-head"><h3>分路优先级</h3><span class="bpl-muted">每路前 3 · 当前分路筛选</span></div><div class="bpl-lane-grid">${laneBoard}</div></div>
    ${note('Pick 率 / Ban 率的分母是队-局；KPL 一局有两个队-局。样本不足时只作观察，不下结论。')}`;
    return section('heroes', '01', '英雄优先级', '当前版本哪些英雄值得优先考虑？',
      `<span class="bpl-section-meta">${esc(scopeLabel)} · ${num(board.total)} 队-局</span>`, body);
  }

  function heroPicker(action, selected, max = 3, hint = '') {
    const all = state.data?.options?.heroes || [];
    const selectedSet = new Set(selected || []);
    const ordered = [...new Set([...(selected || []), ...all])];
    return `<div class="bpl-picker" data-bpl-picker="${action}">
      <div class="bpl-picker-head">
        <div class="bpl-picker-selected">${(selected || []).map((hero) => `<span class="bpl-picker-chip">${portrait(hero, 'bpl-picker-chip-img')}<b>${esc(hero)}</b><button type="button" data-bpl-pick-remove="${esc(hero)}" data-bpl-picker-action="${action}" aria-label="移除 ${esc(hero)}">×</button></span>`).join('') || `<span class="bpl-muted">还没选英雄</span>`}</div>
        <label class="bpl-picker-search">${icon('search')}<input data-bpl-picker-search placeholder="搜英雄" autocomplete="off"></label>
        <span class="bpl-muted">${selected.length}/${max}</span>
        <button type="button" class="bpl-link" data-bpl-picker-clear="${action}">清空</button>
      </div>
      <div class="bpl-picker-grid" data-bpl-picker-grid="${action}">
        ${ordered.map((hero) => `<button type="button" class="bpl-picker-hero ${selectedSet.has(hero) ? 'is-on' : ''}" data-bpl-pick="${action}" data-bpl-pick-hero="${esc(hero)}" data-picker-name="${esc(hero)}" aria-pressed="${selectedSet.has(hero)}">${portrait(hero, 'bpl-picker-img')}<span>${esc(hero)}</span></button>`).join('')}
      </div>
      ${hint ? `<p class="bpl-note">${esc(hint)}</p>` : ''}
    </div>`;
  }

  function comboDetailBlock() {
    const picked = state.comboPick || [];
    const detail = state.comboDetail;
    if (picked.length < 2) {
      return `<div class="bpl-empty bpl-picker-prompt"><b>点两个英雄头像，组成你想查的组合</b><p>再点一次移除；最多 3 个。选满 2 个后自动查同队同局战绩。</p></div>`;
    }
    if (state.comboDetailLoading && !detail) return '<div class="bpl-loading">正在查这组英雄的同队同局记录…</div>';
    if (state.comboDetailError) {
      return `<div class="bpl-error-inline"><b>组合数据暂时读不到</b><p>${esc(state.comboDetailError)}</p><button type="button" class="bpl-primary" data-bpl-combo-retry>重试</button></div>`;
    }
    if (!detail) return '<div class="bpl-loading">正在准备组合数据…</div>';
    if (!detail.available) {
      return empty('这组英雄没有同队同局记录', detail.reason || '换一个组合或放宽时间窗。');
    }
    const recentRows = detail.recent || [];
    const recent = recentRows.map((row) => `<div class="bpl-diag-period">
      <span>近 ${num(row.days)} 天</span><b>${rate(row.winRate)}</b>
      <small>${num(row.games)} 局 · 前窗 ${rate(row.previousWinRate)}</small>
      ${diagDelta(row.delta)}
    </div>`).join('');
    const recentHtml = recentRows.some((row) => row.games)
      ? `<div class="bpl-diag-periods">${recent}</div>`
      : `<p class="bpl-note">近 7 / 15 / 30 天没有这组英雄的同队同局记录；上面的总样本来自更早的历史。</p>`;
    const sideRows = (detail.sides || []).map((row) => [
      `<b>阵营 ${esc(row.side)}</b>`, `${num(row.games)} 局`, diagWin(row),
    ]);
    const mateRows = (detail.teammates || []).map((row) => [
      heroChip(row.hero, {small: true}), `${num(row.games)} 局`, rate(row.share), diagWin(row),
    ]);
    const oppRows = (detail.opponents || []).map((row) => [
      `<b>${esc(row.opponent)}</b>`, `${num(row.games)} 局`, diagWin(row),
    ]);
    const evidence = (detail.evidence || []).map((row) => `<div class="bpl-evidence-row">
      <span>${esc(row.date || '日期未记录')}</span><b>${esc(row.team || '')} vs ${esc(row.enemy || '')}</b>
      <em class="${row.result === true ? 'is-win' : row.result === false ? 'is-loss' : ''}">${row.result === true ? '胜' : row.result === false ? '负' : '—'}</em>
      <small>${(row.ownPicks || []).map((hero) => esc(hero)).join(' / ')}</small>
    </div>`).join('');
    return `<div class="bpl-card bpl-custom-combo">
      <div class="bpl-card-head"><div class="bpl-combo-cell">${detail.heroes.map((hero) => heroChip(hero)).join('<i class="bpl-plus">+</i>')}</div>${sampleBadge(detail.sample)}</div>
      <div class="bpl-kpis">
        ${metric('命中局数', `${num(detail.games)} 局`, `占所选范围 ${rate(detail.share)}`)}
        ${metric('组合胜率', rate(detail.winRate), `${num(detail.wins)} 胜 · ${interval(detail.interval)}`)}
        ${metric('相对基准', detail.relative == null ? '—' : `${detail.relative >= 0 ? '+' : ''}${fmt(detail.relative, 1)} pp`, detail.reference == null ? '样本不足' : `单英雄基准 ${rate(detail.reference)}`)}
        ${metric('覆盖战队', `${num(detail.teams)} 支`, `${esc(state.source === 'kpl' ? 'KPL / 挑战者杯' : '训练赛')}`)}
      </div>
      ${recentHtml}
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>阵营分布</h3><span class="bpl-muted">同队同局</span></div>${dataTable(['阵营', '局数', '胜率'], sideRows, {emptyText: '没有阵营记录'})}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>常见搭档</h3><span class="bpl-muted">剩余位置</span></div>${dataTable(['英雄', '局数', '出现率', '胜率'], mateRows, {emptyText: '没有重复搭档'})}</div>
      </div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>对手分布</h3><span class="bpl-muted">这组英雄遇到谁</span></div>${dataTable(['对手', '局数', '组合胜率'], oppRows, {emptyText: '没有对手记录'})}</div>
      <details class="bpl-details"><summary>展开证据局（${(detail.evidence || []).length} 条）</summary><div class="bpl-evidence">${evidence || '<span class="bpl-muted">没有证据局</span>'}</div></details>
      ${(detail.caveats || []).map((text) => note(text)).join('')}
    </div>`;
  }

  // -------------------------------------------------------------------------
  // 02 组合强度
  // -------------------------------------------------------------------------
  function combosSection(data) {
    const combos = data.combos || {};
    const pairs = state.comboSort === 'signal' ? (combos.pairsBySignal || []) : (combos.pairs || []);
    const trios = state.comboSort === 'signal' ? (combos.triosBySignal || []) : (combos.trios || []);
    const spotlight = combos.spotlight || null;
    const focusCombos = comboCompareMap(state.compare);
    const comboRows = (rows, size) => dataTable(['组合', '局数', '使用率', '胜率', '近' + state.recentDays + '天', '变化', '相对基准', '样本'], rows.slice(0, size).map((row) => {
      const cmp = focusCombos.get(row.label);
      return [
        `<button type="button" class="bpl-combo-pick" data-bpl-combo-pick="${esc(row.heroes.join(','))}">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</button>`,
        `<b>${num(row.games)}</b>`,
        `<div class="bpl-num-bar"><span>${rate(row.share)}</span>${bar(row.share, 100)}</div>`,
        `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</div>`,
        `<div class="bpl-win"><b>${rate(row.recentWinRate)}</b><small>${num(row.recentGames)} 局</small></div>`,
        row.recentChange == null ? '<span class="bpl-muted">—</span>' : `<b class="${row.recentChange >= 0 ? 'is-up' : 'is-down'}">${row.recentChange >= 0 ? '+' : ''}${fmt(row.recentChange, 1)} pp</b>`,
        row.relative == null ? '<span class="bpl-muted">—</span>' : `<b class="${row.relative >= 0 ? 'is-up' : 'is-down'}">${row.relative >= 0 ? '+' : ''}${fmt(row.relative, 1)} pp</b>`,
        sampleBadge(row.sample),
      ];
    }), {emptyText: '当前范围没有组合记录'});
    const spotlightHtml = spotlight ? `<div class="bpl-spotlight">
      <div class="bpl-spotlight-heroes">${spotlight.heroes.map((hero) => `<div>${portrait(hero, 'bpl-spotlight-img')}<b>${esc(hero)}</b></div>`).join('<i>+</i>')}</div>
      <div><span class="bpl-eyebrow">SPOTLIGHT · 组合样本</span>
        <h3>${esc(spotlight.label)}</h3>
        <p>KPL 历史上同队同局出现 <b>${num(spotlight.games)}</b> 局，胜率 <b>${rate(spotlight.winRate)}</b>${spotlight.relative == null ? '' : `，相对单英雄基准 <b class="${spotlight.relative >= 0 ? 'is-up' : 'is-down'}">${spotlight.relative >= 0 ? '+' : ''}${fmt(spotlight.relative, 1)} pp</b>`}；近 ${state.recentDays} 天 <b>${rate(spotlight.recentWinRate)}</b>（${num(spotlight.recentGames)} 局，变化 ${spotlight.recentChange == null ? '—' : `${spotlight.recentChange >= 0 ? '+' : ''}${fmt(spotlight.recentChange, 1)} pp`}）。</p>
        <div class="bpl-spotlight-facts">${metric('样本', num(spotlight.decided), '局有胜负')}${metric('覆盖战队', num(spotlight.teams), '支')}</div>
        <button type="button" class="bpl-ghost" data-bpl-combo-pick="${esc(spotlight.heroes.join(','))}">用这个组合</button>
      </div>
    </div>` : empty('当前范围没有可用组合 spotlight', '组合至少 2 局才进入统计。');
    const body = `<div class="bpl-card bpl-picker-card">
      <div class="bpl-card-head"><h3>自选组合</h3><span class="bpl-muted">头像相加 = 同队同局；点已有组合可直接带入</span></div>
      ${heroPicker('combo', state.comboPick, 3, '点头像加入组合；再点一次移除。2 个或 3 个英雄都可以，选满 2 个自动查历史战绩。')}
    </div>
    ${comboDetailBlock()}
    <div class="bpl-card-head bpl-toolbar-line">
      <span class="bpl-muted">相对基准 = 组合胜率 − 单英雄收缩基准；不是因果协同。</span>
      <div class="bpl-segment bpl-segment-small" role="group" aria-label="组合排序">
        <button type="button" data-bpl-combo-sort="usage" aria-pressed="${state.comboSort === 'usage'}">按使用</button>
        <button type="button" data-bpl-combo-sort="signal" aria-pressed="${state.comboSort === 'signal'}">按信号</button>
      </div>
    </div>
    ${spotlightHtml}
    <div class="bpl-grid bpl-grid-even">
      <div class="bpl-card"><div class="bpl-card-head"><h3>双人组合</h3><span class="bpl-muted">同队同局</span></div>${comboRows(pairs, 10)}</div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>三人组合</h3><span class="bpl-muted">同队同局</span></div>${comboRows(trios, 10)}</div>
    </div>
    ${note('使用率分母为队-局；组合样本少时，胜率与相对基准只作观察。')}`;
    return section('combos', '02', '组合强度', '鲁班大师＋鲁班七号的组合有多强？',
      `<span class="bpl-section-meta">${state.team ? `本队 · ${esc(state.team)}` : '联盟大盘'} · ${num((combos.pairs || []).length + (combos.trios || []).length)} 组</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 03 的高级查询工具：任意英雄 / 组合 / 完整阵容
  // -------------------------------------------------------------------------
  function lookupTool(data) {
    const heroes = data.options?.heroes || [];
    const datalist = `<datalist id="bpl-hero-options">${heroes.map((hero) => `<option value="${esc(hero)}"></option>`).join('')}</datalist>`;
    const result = state.lookup;
    let resultHtml = `<div class="bpl-lookup-prompt">
      <b>查一个英雄、一组双/三英雄，或一套完整五人阵容。</b>
      <p>例：小乔适合应对哪些阵容？鲁班父子在 KPL 见过多少局？</p>
      <div class="bpl-example-row">
        ${['小乔', '鲁班大师,鲁班七号', '大乔,公孙离', '张良,王昭君'].map((text) => `<button type="button" data-bpl-example="${esc(text)}">${esc(text.replace(',', ' + '))}</button>`).join('')}
      </div>
    </div>`;
    if (state.lookupBusy) resultHtml = '<div class="bpl-loading">正在查历史对抗…</div>';
    else if (result) {
      if (!result.available) {
        resultHtml = empty('没有命中', result.reason || '换一个英雄或放宽时间范围。');
      } else {
        const summary = result.summary || {};
        const lineups = (result.opponentLineups || []).slice(0, 8);
        const signatures = (result.signatures || []).slice(0, 6);
        resultHtml = `<div class="bpl-kpis">
          ${metric('命中局数', num(summary.games), result.mode === 'lineup' ? '完整阵容' : result.mode === 'hero' ? '单英雄' : '组合')}
          ${metric('胜率', rate(summary.winRate), `${num(summary.wins)} 胜 / ${num(summary.decided)} 局`)}
          ${metric('覆盖战队', num(summary.teams), `${summary.from || '—'} → ${summary.to || '—'}`)}
        </div>
        <div class="bpl-grid bpl-grid-even">
          <div class="bpl-card"><div class="bpl-card-head"><h3>对手常用阵容</h3><span class="bpl-muted">目标英雄所在队的对手</span></div>
            ${dataTable(['对手阵容', '局数', '目标胜率'], lineups.map((row) => [
              `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
              num(row.games), rate(row.winRate),
            ]), {emptyText: '没有完整五人阵容记录'})}
          </div>
          <div class="bpl-card"><div class="bpl-card-head"><h3>对手分路类型</h3><span class="bpl-muted">五路类型签名</span></div>
            ${dataTable(['类型', '局数', '目标胜率'], signatures.map((row) => [
              `<span class="bpl-signature">${esc(row.label)}</span>`, num(row.games), rate(row.winRate),
            ]), {emptyText: '分路信息不足，无法生成类型'})}
          </div>
        </div>
        <details class="bpl-details"><summary>展开证据局（${(result.evidence || []).length} 条）</summary>
          <div class="bpl-evidence">${(result.evidence || []).map((row) => `<div class="bpl-evidence-row">
            <span>${esc(row.date || '日期未记录')}</span><b>${esc(row.team || '')} vs ${esc(row.enemy || '')}</b>
            <em class="${row.result === true ? 'is-win' : row.result === false ? 'is-loss' : ''}">${row.result === true ? '胜' : row.result === false ? '负' : '—'}</em>
            <small>${row.ownPicks.map((hero) => esc(hero)).join(' / ')}</small>
          </div>`).join('') || '<span class="bpl-muted">没有证据局</span>'}
          </div></details>
        ${(result.caveats || []).map((text) => note(text)).join('')}`;
      }
    }
    const body = `<form class="bpl-lookup-form" data-bpl-lookup-form>
      <div class="bpl-lookup-input">${icon('search')}<input name="heroes" data-bpl-lookup-input list="bpl-hero-options" value="${esc(state.lookupText)}" placeholder="输入英雄，逗号分隔；5 个英雄按完整阵容查" autocomplete="off"></div>
      <button class="bpl-primary" type="submit">查历史对抗</button>
    </form>${datalist}
    <div class="bpl-lookup-actions"><span class="bpl-muted">${state.source === 'kpl' ? 'KPL（含挑战者杯）' : '训练赛'} · 与当前时间范围一致</span></div>
    ${resultHtml}`;
    return body;
  }

  // -------------------------------------------------------------------------
  // 03 针对指定对手的历史阵容研究
  // -------------------------------------------------------------------------
  function behaviorBlocks(behavior) {
    if (!behavior || !behavior.available) {
      return `<div class="bpl-empty bpl-behavior-empty"><b>行为画像暂不可用</b><p>${esc(behavior?.reason || '当前对手没有逐手顺序，无法做第一手/败后调整。')}</p></div>`;
    }
    const sideCard = (key) => {
      const rows = behavior.firstPicksBySide?.[key] || [];
      return `<div class="bpl-behavior-side"><div class="bpl-card-head"><h3>阵营 ${esc(key)} · 第一手</h3><span class="bpl-muted">该方第 1 手</span></div>
        ${rows.slice(0, 5).map((row) => `<div class="bpl-behavior-row">${heroChip(row.hero, {small: true})}<span>${num(row.count)} 次</span><b>${rate(row.winRate)}</b></div>`).join('') || '<span class="bpl-muted">暂无</span>'}</div>`;
    };
    const seriesCard = (key, label) => {
      const row = behavior.series?.[key] || {};
      return `<div class="bpl-behavior-side"><div class="bpl-card-head"><h3>${label}</h3><span class="bpl-muted">${num(row.games)} 局</span></div>
        <div class="bpl-behavior-kpis">${metric('下一局胜率', rate(row.nextWinRate), `${num(row.wins)} 胜 / ${num(row.decided)} 局`)}${metric('第一手变化', rate(row.firstPickChangeRate), '相较上一局')}${metric('Ban 变化', rate(row.banChangeRate), '集合有变化')}</div></div>`;
    };
    const conditionalRows = (behavior.conditionalFirstPicks || []).slice(0, 5);
    const players = (behavior.players || []).slice(0, 5);
    return `<div class="bpl-behavior-head"><h3>对手 BP 行为画像</h3><span class="bpl-muted">第一手 / 回应 / 败后调整 / 选手池</span></div>
      <div class="bpl-grid bpl-behavior-grid">
        ${sideCard('1')}${sideCard('2')}
        <div class="bpl-card"><div class="bpl-card-head"><h3>看到我方第一手后</h3><span class="bpl-muted">同局第一手共现</span></div>
          ${dataTable(['我方第一手', '样本', '对手更常第一手'], conditionalRows.map((row) => [
            heroChip(row.ourFirst, {small: true}), `${num(row.games)} 局`,
            `<div class="bpl-chip-row">${(row.responses || []).slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('')}</div>`,
          ]), {emptyText: '样本不足 3 局'})}
        </div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>系列赛调整</h3><span class="bpl-muted">按败后 / 胜后</span></div>
          <div class="bpl-behavior-series">${seriesCard('afterLoss', '上一局失利后')}${seriesCard('afterWin', '上一局取胜后')}</div>
        </div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>选手英雄池</h3><span class="bpl-muted">KPL 十人面板</span></div>
          ${dataTable(['选手', '局数', '常选英雄', '第一手'], players.map((row) => [
            `<b>${esc(row.player)}</b>`, num(row.games),
            `<div class="bpl-chip-row">${(row.heroes || []).slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.games})).join('')}</div>`,
            `${num(row.firstPickCount)} 次`,
          ]), {emptyText: '没有选手-英雄映射'})}
        </div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>行为口径</h3><span class="bpl-muted">不是因果</span></div>
          <ul class="bpl-list">${(behavior.notes || []).map((text) => `<li>${esc(text)}</li>`).join('')}</ul>
        </div>
      </div>`;
  }

  function opponentResearchSection(data) {
    const research = state.opponentResearch || data.opponentResearch || {};
    if (!research.available) {
      return section('opponent', '03', '针对指定对手的历史阵容研究', '研究特定对手、特定阵容、特定 BP 局面下的历史表现。', '',
        empty('先选一支有记录的对手', research.reason || '当前范围没有对手记录。'));
    }
    const options = research.options || {};
    const situation = research.situation || {};
    const oppHeroCmp = heroCompareMap(state.opponentCompare);
    const oppComboCmp = comboCompareMap(state.opponentCompare);
    const selectedCombo = (situation.combo || []).join(',');
    const selectedHero = situation.hero || '';
    const side = situation.side || '';
    const firstPick = situation.firstPick || '';
    const opponentOptions = (data.options?.teams || []).map((name) =>
      `<option value="${esc(name)}" ${name === research.team ? 'selected' : ''}>${esc(name)}</option>`).join('');
    const sideOptions = (options.sides || []).map((value) =>
      `<option value="${esc(value)}" ${value === side ? 'selected' : ''}>阵营 ${esc(value)}</option>`).join('');
    const firstPickOptions = (options.firstPicks || []).map((row) =>
      `<option value="${esc(row.hero)}" ${row.hero === firstPick ? 'selected' : ''}>${esc(row.hero)} · ${num(row.count)} 次</option>`).join('');
    const comboOptions = (options.combos || []).map((row) =>
      `<option value="${esc(row.heroes.join(','))}" ${row.heroes.join(',') === selectedCombo ? 'selected' : ''}>${esc(row.label)} · ${num(row.games)} 局</option>`).join('');
    const heroOptions = (options.heroes || []).map((row) =>
      `<option value="${esc(row.hero)}" ${row.hero === selectedHero ? 'selected' : ''}>${esc(row.hero)} · ${num(row.picks)} 次</option>`).join('');
    const controls = `<div class="bpl-research-controls">
      <label class="bpl-field">研究对手<select data-bpl-research-opponent>${opponentOptions || '<option value="">暂无对手</option>'}</select></label>
      <label class="bpl-field">阵营<select data-bpl-research-side><option value="">全部阵营</option>${sideOptions}</select></label>
      <label class="bpl-field">对手第一手<select data-bpl-research-first-pick><option value="">全部第一手</option>${firstPickOptions}</select></label>
      <label class="bpl-field">对手组合<select data-bpl-research-combo>${comboOptions || '<option value="">暂无组合</option>'}</select></label>
      <label class="bpl-field">对手英雄<select data-bpl-research-hero>${heroOptions || '<option value="">暂无英雄</option>'}</select></label>
    </div>`;
    const comboRows = [
      ...(research.comboUsage?.pairs || []).map((row) => ({...row, size: '双人'})),
      ...(research.comboUsage?.trios || []).map((row) => ({...row, size: '三人'})),
    ].slice(0, 10);
    const comboUsageTable = dataTable(['组合', '类型', '局数', '使用率', '胜率', '样本'], comboRows.map((row) => {
      const cmp = oppComboCmp.get(row.label);
      return [
        `<button type="button" class="bpl-link" data-bpl-research-combo="${esc(row.heroes.join(','))}">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</button>`,
        `<span class="bpl-muted">${row.size}</span>`,
        `<b>${num(row.games)}</b>`,
        `<div class="bpl-num-bar"><span>${rate(row.share)}</span>${bar(row.share, 100)}</div>`,
        `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</div>`,
        sampleBadge(row.sample),
      ];
    }), {emptyText: '当前局面没有组合样本'});
    const comboCounterRows = (research.comboCounters?.rows || []).map((row) => [
      `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
      `${num(row.games)} 局`,
      `<div class="bpl-win"><b>${rate(row.opponentWinRate)}</b><small>对手胜率</small></div>`,
      `<div class="bpl-win"><b class="${row.counterWinRate != null && row.counterWinRate >= 55 ? 'is-up' : ''}">${rate(row.counterWinRate)}</b><small>反制胜率</small></div>`,
      sampleBadge(row.decided >= 10 ? '样本充足' : row.decided >= 3 ? '小样本' : '样本不足'),
    ]);
    const heroUsageTable = dataTable(['英雄', 'Pick', 'Pick 率', '胜率', '样本'], (research.heroUsage || []).map((row) => {
      const cmp = oppHeroCmp.get(row.hero);
      return [
        `<button type="button" class="bpl-link" data-bpl-research-hero="${esc(row.hero)}">${heroChip(row.hero)}</button>`,
        `<b>${num(row.picks)}</b>`,
        `<div class="bpl-num-bar"><span>${rate(row.pickRate)}</span>${bar(row.pickRate, 100)}${cmp ? deltaLine(cmp.pickDelta, cmp.pickDeltaYoy) : ''}</div>`,
        `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</div>`,
        sampleBadge(row.sample),
      ];
    }), {emptyText: '当前局面没有英雄样本'});
    const heroCounterRows = (research.heroCounters?.rows || []).map((row) => [
      heroChip(row.hero, {small: true}),
      `${num(row.games)} 局`,
      `<div class="bpl-win"><b>${rate(row.opponentWinRate)}</b><small>对手胜率</small></div>`,
      `<div class="bpl-win"><b class="${row.counterWinRate != null && row.counterWinRate >= 55 ? 'is-up' : ''}">${rate(row.counterWinRate)}</b><small>反制胜率</small></div>`,
      sampleBadge(row.decided >= 10 ? '样本充足' : row.decided >= 3 ? '小样本' : '样本不足'),
    ]);
    const summary = `<div class="bpl-research-summary">
      <span class="bpl-section-meta">${esc(research.team)} · ${num(research.situationGames)} 局局面样本</span>
      ${(research.summary?.topThreats || []).map((text) => `<span class="bpl-pill">重点防：${esc(text)}</span>`).join('')}
      ${(research.summary?.watch || []).map((text) => `<span class="bpl-pill is-warm">不要放：${esc(text)}</span>`).join('')}
    </div>`;
    const body = `${controls}${summary}
      <div class="bpl-grid bpl-research-grid">
        <div class="bpl-card"><div class="bpl-card-head"><h3>对手组合使用</h3><span class="bpl-muted">对手同队同局 · 胜率</span></div>${comboUsageTable}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>对手组合的反制</h3><span class="bpl-muted">${esc(research.comboCounters?.label || '未选组合')}</span></div>${dataTable(['敌方组合', '交手', '对手胜率', '反制胜率', '样本'], comboCounterRows, {emptyText: '该组合当前局面下没有 ≥3 局的反制记录'})}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>对手英雄使用</h3><span class="bpl-muted">对手 Pick · 胜率</span></div>${heroUsageTable}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>英雄反制</h3><span class="bpl-muted">${esc(research.heroCounters?.hero || '未选英雄')}</span></div>${dataTable(['敌方英雄', '交手', '对手胜率', '反制胜率', '样本'], heroCounterRows, {emptyText: '该英雄当前局面下没有 ≥3 局的反制记录'})}</div>
      </div>
      ${(research.caveats || []).map((text) => note(text)).join('')}
      ${behaviorBlocks(research.behavior)}
      <details class="bpl-details bpl-advanced"${state.lookup || state.lookupBusy || state.lookupOpen ? ' open' : ''}><summary>高级查询：任意英雄 / 组合 / 完整阵容</summary>${lookupTool(data)}</details>`;
    return section('opponent', '03', '针对指定对手的历史阵容研究',
      '研究特定对手、特定阵容、特定 BP 局面下的历史表现。',
      `<span class="bpl-section-meta">${esc(research.team)} · ${num(research.games)} 局</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 04 战队如何破解
  // -------------------------------------------------------------------------
  function countersSection(data) {
    const current = state.counters || data.teamCounters || {};
    const pairs = (data.combos?.pairs || []).slice(0, 10);
    const trios = (data.combos?.trios || []).slice(0, 8);
    const heroTargets = (data.heroes?.top || []).slice(0, 8);
    const targetValue = (target) => target.length === 1 ? `hero:${target[0]}` : `combo:${target.join(',')}`;
    const options = [
      ...pairs.map((row) => [`combo:${row.heroes.join(',')}`, `组合 · ${row.label}`]),
      ...trios.map((row) => [`combo:${row.heroes.join(',')}`, `三人 · ${row.label}`]),
      ...heroTargets.map((row) => [`hero:${row.hero}`, `英雄 · ${row.hero}`]),
    ];
    const selected = targetValue(state.target?.length ? state.target : (current.target || []));
    if (selected && !options.some(([value]) => value === selected)) {
      const fallbackLabel = state.target?.length === 1 ? `英雄 · ${state.target[0]}` : `研究对象 · ${(state.target || []).join(' + ')}`;
      options.unshift([selected, fallbackLabel]);
    }
    const select = `<label class="bpl-field bpl-target-select">研究对象
      <select data-bpl-target>${options.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></label>`;
    const targetList = state.target?.length ? state.target : (current.target || []);
    const focusHeroes = heroCompareMap(state.compare);
    const focusCombos = comboCompareMap(state.compare);
    const targetCmp = state.compare?.target;
    const targetDelta = targetCmp
      ? `${deltaLine(targetCmp.shareDelta, targetCmp.shareDeltaYoy)}${deltaLine(targetCmp.winDelta, targetCmp.winDeltaYoy)}`
      : '';
    if (!current.available) {
      return section('counters', '04', '战队如何破解', '职业队一般怎么破解某个体系？', '', empty('没有可比较的战队记录', current.reason || '换一个目标或数据源。'));
    }
    const rows = (current.rows || []).slice(0, 12);
    const table = dataTable(['战队', '面对目标', '对目标胜率', '拆组合 Ban 率', '常用应对', '样本'], rows.map((row) => [
      `<b>${esc(row.team)}</b>`,
      `${num(row.games)} 局`,
      `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small></div>`,
      `<div class="bpl-num-bar is-ban"><span>${rate(row.banRate)}</span>${bar(row.banRate, 100, 'is-ban')}</div>`,
      `<div class="bpl-chip-row">${(row.responseHeroes || []).slice(0, 4).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('')}</div>`,
      sampleBadge(row.sample),
    ]), {emptyText: '没有战队面对过该目标'});
    const topResponses = (current.summary?.topResponses || []).slice(0, 6);
    const body = `<div class="bpl-toolbar-line">${select}<span class="bpl-muted">目标在对手阵容、本队与之交手的局；Ban 率按拆组合（禁任一）计算。</span>${targetDelta ? `<span class="bpl-target-compare">目标时间变化${targetDelta}</span>` : ''}</div>
      <details class="bpl-picker-details" data-bpl-picker-details="counter" ${state.counterPickerOpen ? 'open' : ''}><summary>用头像自选目标（1–3 个英雄）</summary>${heroPicker('counter', targetList, 3, '点英雄头像组成目标；单英雄、双人组合或三人组合都可以。')}</details>
      <div class="bpl-kpis">
        ${metric('面对目标', `${num(current.summary?.games)} 局`, `${num(current.summary?.teams)} 支战队`)}
        ${metric('目标', esc(current.label || '—'), '英雄 / 组合')}
        ${metric('最常见应对', esc(topResponses[0]?.hero || '—'), topResponses[0] ? `${num(topResponses[0].count)} 次` : '')}
        ${metric('统计口径', '拆组合', '禁任一英雄算 Ban')}
      </div>
      <div class="bpl-card">${table}</div>
      <div class="bpl-chip-strip"><span class="bpl-muted">全体应对英雄</span>${topResponses.map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>
      ${(current.caveats || []).map((text) => note(text)).join('')}`;
    return section('counters', '04', '战队如何破解', '职业队一般怎么破解某个体系？',
      `<span class="bpl-section-meta">${num(current.summary?.teams || 0)} 支队</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 05 选禁习惯
  // -------------------------------------------------------------------------
  function habitsSection(data) {
    const habits = data.draftHabits || {};
    if (!habits.available) {
      return section('habits', '05', '选禁习惯', '对手 Ban A 后更可能选 B 还是 C？', '', empty('没有该战队的 BP 记录', habits.reason || '换个本队或数据源。'));
    }
    const topBans = habits.topBans || [];
    const topPicks = habits.topPicks || [];
    const firstPicks = habits.firstPicks || [];
    const banResponses = habits.banResponses || [];
    const sides = habits.sides || {};
    const oppHeroCmp = heroCompareMap(state.opponentCompare);
    const list = (rows, cls = '', deltaKey = '') => `<div class="bpl-rank-list">${rows.slice(0, 8).map((row, index) => {
      const cmp = oppHeroCmp.get(row.hero);
      return `<div class="bpl-rank-row">
        <i>${index + 1}</i><div class="bpl-rank-hero">${heroChip(row.hero, {small: true})}${cmp && deltaKey ? deltaLine(cmp[deltaKey], cmp[`${deltaKey}Yoy`]) : ''}</div>
        <div class="bpl-num-bar ${cls}"><span>${rate(row.share)}</span>${bar(row.share, 100, cls)}</div>
        <b>${num(row.count)}</b></div>`;
    }).join('') || '<span class="bpl-muted">暂无</span>'}</div>`;
    const firstPickRows = dataTable(['第一手', '次数', '占比', '胜率'], firstPicks.slice(0, 6).map((row) => [
      heroChip(row.hero, {small: true}), num(row.count), rate(row.share), rate(row.winRate),
    ]), {emptyText: habits.orderKnown ? '暂无' : '没有逐手顺序'});
    const responseRows = dataTable(['对手 Ban', '样本', '本队第一手更常选', '胜率'], banResponses.slice(0, 6).map((row) => [
      heroChip(row.ban, {small: true}),
      `${num(row.games)} 局`,
      `<div class="bpl-chip-row">${(row.options || []).slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('')}</div>`,
      (row.options || []).slice(0, 3).map((item) => `<span class="bpl-inline-rate">${rate(item.winRate)}</span>`).join(' / '),
    ]), {emptyText: habits.orderKnown ? '样本不足 3 局，暂不展示' : '训练赛没有逐手顺序'});
    const sideCard = (key, label) => {
      const row = sides[key] || {};
      return `<div class="bpl-side-card"><div><span>${label}</span><b>${num(row.decided)} 局有胜负</b></div>
        <strong>${rate(row.winRate)}</strong><small>${interval(row.interval)}</small>
        <p>${(row.firstPicks || []).slice(0, 3).map((item) => esc(item.hero)).join(' / ') || '—'}</p></div>`;
    };
    const slots = `<details class="bpl-details"><summary>展开 Pick / Ban 槽位分布</summary>
      <div class="bpl-slot-grid">
        ${(habits.pickSlots || []).map((slot) => `<div class="bpl-slot"><b>第 ${slot.slot} Pick</b>${slot.heroes.slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>`).join('')}
      </div>
      <div class="bpl-slot-grid">
        ${(habits.banSlots || []).map((slot) => `<div class="bpl-slot"><b>第 ${slot.slot} Ban</b>${slot.heroes.slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>`).join('')}
      </div>
    </details>`;
    const body = `<div class="bpl-kpis">
      ${metric('战队', esc(habits.team || '—'), `${num(habits.games)} 局记录`)}
      ${metric('可算手序', `${num(habits.orderGames)} 局`, habits.orderKnown ? (state.source === 'scrim' ? '营地默认 20 手' : 'KPL 每方数组顺序') : '无逐手顺序')}
      ${metric('最常 Ban', esc(topBans[0]?.hero || '—'), topBans[0] ? `${num(topBans[0].count)} 次` : '')}
      ${metric('最常 Pick', esc(topPicks[0]?.hero || '—'), topPicks[0] ? `${num(topPicks[0].count)} 次` : '')}
    </div>
    <div class="bpl-grid bpl-grid-habits">
      <div class="bpl-card"><div class="bpl-card-head"><h3>常 Ban</h3><span class="bpl-muted">按次数</span></div>${list(topBans, '', 'banDelta')}</div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>常 Pick</h3><span class="bpl-muted">按次数</span></div>${list(topPicks, 'is-pick', 'pickDelta')}</div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>第一手</h3><span class="bpl-muted">该队第 1 手 Pick</span></div>${firstPickRows}</div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>阵营差异</h3><span class="bpl-muted">阵营 1 / 2</span></div><div class="bpl-side-grid">${sideCard('1', '阵营 1')}${sideCard('2', '阵营 2')}</div></div>
    </div>
    <div class="bpl-card"><div class="bpl-card-head"><h3>对手 Ban A 后，本队第一手更常选谁</h3><span class="bpl-muted">按对手 Ban 集合条件</span></div>${responseRows}</div>
    ${slots}
    ${note(habits.note || '')}
    ${(habits.caveats || []).map((text) => note(text)).join('')}`;
    return section('habits', '05', '选禁习惯', '对手 Ban A 后更可能选 B 还是 C？',
      `<span class="bpl-section-meta">${num(habits.orderGames)} 局可算手序</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 06 策略演变
  // -------------------------------------------------------------------------
  const deltaCell = (value) => value == null
    ? '<span class="bpl-muted">—</span>'
    : `<b class="${value >= 0 ? 'is-up' : 'is-down'}">${value >= 0 ? '+' : ''}${fmt(value, 1)} pp</b>`;
  const deltaLine = (prev, yoy) => {
    const parts = [];
    if (prev != null) parts.push(`环比 ${prev >= 0 ? '+' : ''}${fmt(prev, 1)}`);
    if (yoy != null) parts.push(`同比 ${yoy >= 0 ? '+' : ''}${fmt(yoy, 1)}`);
    return parts.length ? `<small class="bpl-delta">${parts.join(' · ')}</small>` : '';
  };

  function compareBlock(kind = 'focus') {
    const opponentMode = kind === 'opponent';
    const loading = opponentMode ? state.opponentCompareLoading : state.compareLoading;
    const error = opponentMode ? state.opponentCompareError : state.compareError;
    const compare = opponentMode ? state.opponentCompare : state.compare;
    if (loading && !compare) {
      return '<div class="bpl-card bpl-compare"><div class="bpl-loading">正在计算环比 / 同比…</div></div>';
    }
    if (error) {
      return `<div class="bpl-card bpl-compare"><div class="bpl-error-inline"><b>时间对比暂时读不到</b><p>${esc(error)}</p><button type="button" class="bpl-primary" data-bpl-compare-run="${opponentMode ? 'opponent' : 'focus'}">重试</button></div></div>`;
    }
    if (!compare || !compare.available) return '';
    const periods = [
      ['current', '当前窗口', true],
      ['previous', '环比 · 上一个等长窗口', compare.previousAvailable],
      ['yoy', '同比 · 去年同日期', compare.yoyAvailable],
    ];
    const cards = periods.map(([key, label, available]) => {
      const row = compare[key] || {};
      if (!available) {
        return `<article class="bpl-period is-empty"><span>${esc(label)}</span><b>无对局</b><small>样本不足，不做硬对比</small></article>`;
      }
      return `<article class="bpl-period">
        <span>${esc(label)}</span>
        <b>${num(row.matches)} 局</b>
        <small>${esc(row.start || '')} → ${esc(row.end || '')}</small>
        <div class="bpl-period-metrics"><em>${rate(row.winRate)} 胜率</em><em>${esc(row.topPick || '—')} 最高 Pick</em><em>${esc(row.topBan || '—')} 最高 Ban</em></div>
        ${(row.firstPicks || []).length ? `<p>第一手：${row.firstPicks.slice(0, 3).map((item) => esc(item.hero)).join(' / ')}</p>` : ''}
      </article>`;
    }).join('');
    const heroRows = (compare.heroes || []).slice(0, 12).map((row) => [
      heroChip(row.hero, {small: true}),
      `<div class="bpl-win"><b>${rate(row.pickRate)}</b><small>${num(row.picks)} 次</small></div>`,
      deltaCell(row.pickDelta), deltaCell(row.pickDeltaYoy),
      `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${num(row.decided)} 局</small></div>`,
      deltaCell(row.winDelta), deltaCell(row.winDeltaYoy),
      sampleBadge(row.sample),
    ]);
    const comboRows = (compare.combos || []).slice(0, 12).map((row) => [
      `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
      `${num(row.games)} 局`,
      `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${num(row.prevGames)} / ${num(row.yoyGames)} 局</small></div>`,
      deltaCell(row.winDelta), deltaCell(row.winDeltaYoy), sampleBadge(row.sample),
    ]);
    const sideRows = ['1', '2'].map((side) => {
      const cur = compare.current?.sides?.[side] || {};
      const prev = compare.previous?.sides?.[side] || {};
      const last = compare.yoy?.sides?.[side] || {};
      return [`阵营 ${side}`, rate(cur.winRate), deltaCell(_compareDelta(cur.winRate, prev.winRate)),
              deltaCell(_compareDelta(cur.winRate, last.winRate)), `${num(cur.games)} 队-局`];
    });
    return `<div class="bpl-compare">
      <div class="bpl-compare-head"><h3>时间对比 · 环比 / 同比</h3><span class="bpl-muted">当前 vs 上一等长窗口 vs 去年同日期</span></div>
      <div class="bpl-period-grid">${cards}</div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>英雄变化</h3><span class="bpl-muted">按当前 Pick 率排序</span></div>
        ${dataTable(['英雄', '当前 Pick', 'Pick 环比', 'Pick 同比', '当前胜率', '胜率环比', '胜率同比', '样本'], heroRows, {emptyText: '当前窗口没有英雄样本'})}
      </div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>组合变化</h3><span class="bpl-muted">按当前场次排序</span></div>
          ${dataTable(['组合', '局数', '当前胜率', '胜率环比', '胜率同比', '样本'], comboRows, {emptyText: '当前窗口没有组合样本'})}
        </div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>阵营对比</h3><span class="bpl-muted">胜率变化</span></div>
          ${dataTable(['阵营', '当前胜率', '胜率环比', '胜率同比', '样本'], sideRows, {emptyText: '没有阵营记录'})}
        </div>
      </div>
      ${(compare.caveats || []).map((text) => note(text)).join('')}
    </div>`;
  }

  function _compareDelta(current, previous) {
    return (typeof current === 'number' && typeof previous === 'number')
      ? Math.round((current - previous) * 10) / 10 : null;
  }

  function evolutionSection(data) {
    const evolution = data.evolution || {};
    const windows = evolution.windows || [];
    const compareHtml = compareBlock('opponent');
    if (!windows.length) return section('evolution', '06', '策略演变', '对手最近是不是改变了惯用战术？', '', compareHtml || empty('当前范围没有时间窗口记录', '放宽时间范围或换数据源。'));
    const rows = windows.slice(-12).reverse();
    const body = `${compareHtml}<div class="bpl-timeline">${rows.map((window) => {
      const picks = (window.topPicks || []).slice(0, 4);
      const bans = (window.topBans || []).slice(0, 3);
      return `<article class="bpl-window">
        <div class="bpl-window-date"><b>${esc(window.key)}</b><span>${esc(window.start || '')}${window.end && window.end !== window.start ? ` → ${esc(window.end)}` : ''}</span></div>
        <div class="bpl-window-main">
          <div class="bpl-window-metrics"><span>${num(window.games)} 局</span><span>${rate(window.winRate)} 胜率</span><span>${interval(window.interval)}</span></div>
          <div class="bpl-window-picks"><span class="bpl-muted">Pick</span>${picks.map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>
          <div class="bpl-window-picks"><span class="bpl-muted">Ban</span>${bans.map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>
          <div class="bpl-window-picks"><span class="bpl-muted">组合</span>${(window.topPairs || []).slice(0, 2).map((pair) => `<span class="bpl-mini-combo">${esc(pair.label)} · ${rate(pair.winRate)}</span>`).join('') || '<span class="bpl-muted">—</span>'}</div>
          <div class="bpl-window-picks"><span class="bpl-muted">阵营</span><span class="bpl-mini-combo">1：${rate(window.sides?.['1']?.winRate)}</span><span class="bpl-mini-combo">2：${rate(window.sides?.['2']?.winRate)}</span></div>
          <div class="bpl-window-picks"><span class="bpl-muted">第一手</span>${(window.firstPicks || []).slice(0, 3).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('') || '<span class="bpl-muted">—</span>'}</div>
        </div>
        <div class="bpl-window-bar">${bar(window.winRate, 100)}</div>
      </article>`;
    }).join('')}</div>
    ${note(evolution.note || '')}
    ${note('窗口按当前选择的时间粒度聚合；KPL 版本字段为空，不把时间变化解释成版本变化。')}`;
    return section('evolution', '06', '策略演变', '对手最近是不是改变了惯用战术？',
      `<span class="bpl-section-meta">${state.team ? `本队 · ${esc(state.team)}` : '联盟大盘'} · ${num(windows.length)} 个窗口</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 07 训练赛体系
  // -------------------------------------------------------------------------
  function scrimSection(data) {
    const scrim = data.scrim || {};
    if (!scrim.available) {
      return section('scrim', '07', '训练赛体系', '我们训练过的体系究竟是否有效？', '',
        `<div class="bpl-empty bpl-empty-cta"><b>看训练赛体系，需要把数据源切到训练赛</b><p>${esc(scrim.reason || 'KPL 是职业赛事证据，训练赛看本队体系。')}</p><button type="button" class="bpl-primary" data-bpl-cta-source="scrim">切到训练赛</button></div>`);
    }
    const validity = (scrim.validity || []).slice(0, 12);
    const focusCombos = comboCompareMap(state.compare);
    const body = `<div class="bpl-kpis">
      ${metric('本队训练局', num(scrim.games), `${num(scrim.decided)} 局有胜负`)}
      ${metric('有效体系', num(scrim.summary?.effective), '相对基准 +5pp 以上')}
      ${metric('待验证', num(scrim.summary?.watch), '持平 / 样本不足')}
      ${metric('未达预期', num(scrim.summary?.weak), '相对基准 -5pp 以下')}
    </div>
    <div class="bpl-card"><div class="bpl-card-head"><h3>体系有效性</h3><span class="bpl-muted">组合胜率 vs 单英雄基准</span></div>
      ${dataTable(['组合', '局数', '胜率', '相对基准', '分路适配', '判定'], validity.map((row) => {
        const cmp = focusCombos.get(row.label);
        return [
          `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
          `<b>${num(row.games)}</b>`,
          `<div class="bpl-win"><b>${rate(row.winRate)}</b><small>${interval(row.interval)}</small>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</div>`,
          row.relative == null ? '—' : `<b class="${row.relative >= 0 ? 'is-up' : 'is-down'}">${row.relative >= 0 ? '+' : ''}${fmt(row.relative, 1)} pp</b>`,
          row.laneFit ? '<span class="bpl-badge is-good">分路齐全</span>' : '<span class="bpl-badge is-low">分路待确认</span>',
          verdictBadge(row.verdict),
        ];
      }), {emptyText: '组合样本不足 3 局'})}
    </div>
    <div class="bpl-grid bpl-grid-even">
      <div class="bpl-card"><div class="bpl-card-head"><h3>有效体系的分路与选手</h3><span class="bpl-muted">前 6</span></div>
        <div class="bpl-fit-list">${validity.slice(0, 6).map((row) => `<div class="bpl-fit-row">
          <div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>
          <span>${(row.lanes || []).map((lane) => esc(lane.lane)).join(' / ') || '分路未记录'}</span>
          <small>${(row.players || []).map((player) => esc(player.player)).join(' / ') || '选手未记录'}</small>
        </div>`).join('') || '<span class="bpl-muted">暂无</span>'}</div>
      </div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>训练赛常 Pick</h3><span class="bpl-muted">本队</span></div>
        <div class="bpl-chip-strip">${(data.heroes?.top || []).slice(0, 10).map((row) => heroChip(row.hero, {small: true, count: row.picks})).join('')}</div>
        ${(scrim.caveats || []).map((text) => note(text)).join('')}
      </div>
    </div>
    <div class="bpl-card"><div class="bpl-card-head"><h3>面对对手组合</h3><span class="bpl-muted">本队胜率 · 反制表现</span></div>
      ${dataTable(['对手组合', '交手', '本队胜率', '区间'], (scrim.counterRows || []).map((row) => [
        `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
        num(row.games), rate(row.ourWinRate), interval(row.interval),
      ]), {emptyText: '对手组合样本不足 3 局'})}
    </div>`;
    return section('scrim', '07', '训练赛体系', '我们训练过的体系究竟是否有效？',
      `<span class="bpl-section-meta">${num(scrim.games)} 局</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 08 组合稳定性
  // -------------------------------------------------------------------------
  function stabilitySection(data) {
    const stability = state.stability || data.stability || {};
    const options = stability.availableCombos?.length
      ? stability.availableCombos
      : (data.stability?.availableCombos || []);
    const selectedList = state.combo || stability.combo || [];
    const selected = selectedList.join(',');
    const hasOption = options.some((row) => row.heroes.join(',') === selected);
    const customOption = selected && !hasOption
      ? `<option value="${esc(selected)}" selected>${esc(selectedList.join(' + '))} · 自选</option>` : '';
    const select = `<label class="bpl-field bpl-target-select">组合
      <select data-bpl-stability-combo>
        ${customOption}${options.map((row) => `<option value="${esc(row.heroes.join(','))}" ${row.heroes.join(',') === selected ? 'selected' : ''}>${esc(row.label)} · ${num(row.games)} 局</option>`).join('') || '<option value="">暂无可评估组合</option>'}
      </select></label>`;
    if (!stability.available) {
      return section('stability', '08', '组合稳定性', '这个体系是真的稳定，还是偶尔赢了几局？', '',
        `<div class="bpl-toolbar-line">${select}<span class="bpl-muted">至少 3 个有效窗口才判断</span></div>${empty('该组合在当前范围没有命中局', stability.reason || '换一个组合或数据源。')}`);
    }
    const windows = stability.windows || [];
    const maxGames = Math.max(1, ...windows.map((row) => row.decided || 0));
    const stabLabel = (state.combo || stability.combo || []).join(' + ');
    const stabCmp = comboCompareMap(state.compare).get(stabLabel);
    const body = `<div class="bpl-toolbar-line">${select}${verdictBadge(stability.verdict)}<span class="bpl-muted">${num(stability.validWindows)} 个有效窗口</span>${stabCmp ? deltaLine(stabCmp.winDelta, stabCmp.winDeltaYoy) : ''}</div>
      <details class="bpl-picker-details" data-bpl-picker-details="stability" ${state.stabilityPickerOpen ? 'open' : ''}><summary>用头像自选组合（2–3 个英雄）</summary>${heroPicker('stability', state.combo || stability.combo || [], 3, '点头像组成要评估稳定性的组合；至少 2 个。')}</details>
      <div class="bpl-kpis">
        ${metric('总样本', `${num(stability.total)} 局`, `${num(stability.decided)} 局有胜负`)}
        ${metric('总胜率', rate(stability.winRate), interval(stability.interval))}
        ${metric('窗口波动', stability.rangePP == null ? '—' : `${fmt(stability.rangePP, 1)} pp`, '最高 − 最低')}
        ${metric('最大回撤', stability.maxDrawdown == null ? '—' : `${fmt(stability.maxDrawdown, 1)} pp`, '峰到之后低谷')}
      </div>
      <div class="bpl-stability-chart">${windows.map((row) => `<div class="bpl-stability-window">
        <div class="bpl-stability-bar" title="${esc(row.key)} · ${num(row.games)} 局">
          <i style="height:${Math.max(2, (row.decided || 0) / maxGames * 100)}%"></i>
          <b style="height:${row.winRate == null ? 2 : Math.max(2, row.winRate)}%"></b>
        </div>
        <span>${esc(row.key)}</span><small>${row.winRate == null ? '—' : rate(row.winRate)}</small>
      </div>`).join('')}</div>
      <div class="bpl-stability-legend"><span><i></i>胜率</span><span>柱高 = 有胜负局数</span></div>
      ${note('窗口样本少的点只作观察；稳定判定需要至少 3 个每窗 ≥3 局有胜负的窗口。')}
      ${(stability.caveats || []).map((text) => note(text)).join('')}`;
    return section('stability', '08', '组合稳定性', '这个体系是真的稳定，还是偶尔赢了几局？',
      `<span class="bpl-section-meta">${state.team ? `本队 · ${esc(state.team)}` : '联盟大盘'} · ${num(windows.length)} 个窗口</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 09 赛前方案
  // -------------------------------------------------------------------------
  function planSection(data) {
    const plan = data.plan || {};
    if (!plan.available) {
      return section('plan', '09', '赛前方案', '针对明天的对手，准备哪些阵容与应对分支？', '',
        empty('先选一支对手', plan.reason || '当前范围没有对手记录。'));
    }
    const ruleOptions = [['scrim-global-20', '20 手 · 每方 5 Ban + 10 Pick']];
    const boOptions = ['BO3', 'BO5', 'BO7'];
    const ruleControls = state.source === 'scrim'
      ? `<label class="bpl-field">BP 规则<select data-bpl-field="rule">${ruleOptions.map(([value, label]) => `<option value="${value}" ${value === state.rule ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
         <label class="bpl-field">赛制<select data-bpl-field="bo">${boOptions.map((value) => `<option value="${value}" ${value === state.bo ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>`
      : '<span class="bpl-badge is-low">KPL · 无规则模拟</span>';
    const oppCombos = comboCompareMap(state.opponentCompare);
    const threatRows = (plan.threats || []).map((row) => {
      const cmp = oppCombos.get(row.label);
      return `<li><b>${esc(row.label)}</b><span>${num(row.games)} 局 · ${rate(row.winRate)}</span>${cmp ? deltaLine(cmp.winDelta, cmp.winDeltaYoy) : ''}</li>`;
    }).join('');
    const banRows = dataTable(['优先限制', '对手 Pick', '本队对位胜率', '理由'], (plan.banPriority || []).map((row) => [
      heroChip(row.hero, {small: true}), `${num(row.oppPicks)} 次 · ${rate(row.oppShare)}`,
      `<div class="bpl-win"><b>${rate(row.ourWinRate)}</b><small>${num(row.ourGames)} 局</small></div>`,
      `<span class="bpl-muted">${esc(row.reason || '')}</span>`,
    ]), {emptyText: '样本不足，暂不排 Ban 优先级'});
    const branchRows = (plan.branches || []).map((row) => `<div class="bpl-branch">
      <div class="bpl-branch-trigger">对手 Ban <b>${esc(row.ban)}</b><span>${num(row.games)} 局</span></div>
      <div class="bpl-branch-options">${(row.options || []).map((item) => `<div>${heroChip(item.hero, {small: true})}<b>${rate(item.winRate)}</b><small>${num(item.count)} 次</small></div>`).join('') || '<span class="bpl-muted">样本不足</span>'}</div>
    </div>`).join('');
    const responseRows = (plan.responses || []).map((row) => `<div class="bpl-response-row">
      <b>${esc(row.opponentCombo)}</b><span>${num(row.games)} 局 · 本队胜率 ${rate(row.ourWinRate)}</span>
      <div class="bpl-chip-row">${(row.responseHeroes || []).slice(0, 5).map((item) => heroChip(item.hero, {small: true, count: item.count})).join('')}</div>
    </div>`).join('');
    const systemRows = (plan.ourSystems || []).slice(0, 6).map((row) => `<div class="bpl-system-row">
      <div class="bpl-combo-cell">${(row.heroes || []).map((hero) => heroChip(hero, {small: true})).join('') || esc(row.label || '')}</div>
      <b>${rate(row.winRate)}</b><small>${num(row.games)} 局</small>${verdictBadge(row.verdict)}
    </div>`).join('');
    const body = `<div class="bpl-toolbar-line">${ruleControls}<span class="bpl-muted">${esc(plan.rule?.note || '')}</span><button type="button" class="bpl-ghost" data-bpl-copy>复制方案</button></div>
      <div class="bpl-plan-summary">${(plan.summary || []).map((text) => `<span>${esc(text)}</span>`).join('') || '<span>当前样本不足以生成总结。</span>'}</div>
      <div class="bpl-grid bpl-grid-plan">
        <div class="bpl-card"><div class="bpl-card-head"><h3>对手最常用</h3><span class="bpl-muted">优先准备</span></div><ul class="bpl-list">${threatRows || '<li>暂无稳定组合</li>'}</ul></div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>Ban 优先级</h3><span class="bpl-muted">对手常 Pick × 本队对位</span></div>${banRows}</div>
      </div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>对手 Ban 后的第一手分支</h3><span class="bpl-muted">按对手 Ban 集合条件</span></div>
        <div class="bpl-branch-list">${branchRows || '<span class="bpl-muted">没有可算的条件分支（当前局面样本不足）</span>'}</div>
      </div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>本队可用体系</h3><span class="bpl-muted">训练赛 / KPL 本队</span></div><div class="bpl-system-list">${systemRows || '<span class="bpl-muted">暂无</span>'}</div></div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>对手组合的应对</h3><span class="bpl-muted">本队历史</span></div><div class="bpl-response-list">${responseRows || '<span class="bpl-muted">样本不足</span>'}</div></div>
      </div>
      <div class="bpl-plan-foot">${(plan.caveats || []).map((text) => note(text)).join('')}</div>`;
    return section('plan', '09', '赛前方案', '针对明天的对手，准备哪些阵容与应对分支？',
      `<span class="bpl-section-meta">${esc(plan.team || '本队')} vs ${esc(plan.opponent || '对手')}</span>`, body);
  }

  // -------------------------------------------------------------------------
  // 10 BP 策略沙盘
  // -------------------------------------------------------------------------
  async function runSim() {
    const data = state.data;
    if (!data) return;
    const team = state.team || data.options?.defaultTeam || '';
    const opponent = state.opponent || data.options?.defaultOpponent || '';
    const sim = state.sim;
    if (!team || !opponent) {
      sim.error = '先选本队与对手。';
      paint();
      return;
    }
    sim.loading = true;
    sim.error = '';
    paint();
    const payload = {
      rule: sim.rule, bo: sim.bo, gameNumber: 1, side: sim.side,
      team, opponent, events: sim.events,
      evidenceSource: sim.evidenceSource,
      league: state.league, from: state.from, to: state.to,
    };
    try {
      const response = await fetch(`${API_BASE}/api/v3/bp-lab/simulate`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload), cache: 'no-store',
      });
      if (!response.ok) {
        let detail = '';
        try { detail = (await response.json()).detail || ''; } catch {}
        throw new Error(detail || `模拟失败（HTTP ${response.status}）`);
      }
      sim.result = await response.json();
      sim.loading = false;
      paint();
    } catch (error) {
      sim.loading = false;
      sim.error = error.message || '模拟失败';
      paint();
    }
  }

  function ensureSim() {
    if (state.view !== 'simulate' || !state.data) return;
    if (state.sim.loading || state.sim.result || state.sim.error) return;
    void runSim();
  }

  function appendSimEvent(action, camp, hero) {
    if (!action || !camp || !hero) return;
    state.sim.events = [...state.sim.events, {
      order: state.sim.events.length + 1, action, camp, hero,
    }];
    state.sim.result = null;
    void runSim();
  }

  // -------------------------------------------------------------------------
  // 05 己方英雄诊断 N01–N16
  // -------------------------------------------------------------------------
  const diagDelta = (value, suffix = ' pp') => value == null
    ? '<span class="bpl-muted">—</span>'
    : `<b class="bpl-diag-delta ${value >= 0 ? 'is-up' : 'is-down'}">${value >= 0 ? '+' : ''}${fmt(value, 1)}${suffix}</b>`;
  const diagWin = (row) => `<div class="bpl-win"><b>${rate(row?.winRate)}</b><small>${interval(row?.interval)}</small></div>`;
  const resultMark = (result) => result === true
    ? '<span class="bpl-diag-result is-win">胜</span>'
    : result === false ? '<span class="bpl-diag-result is-loss">负</span>'
      : '<span class="bpl-diag-result">—</span>';

  function diagnosisUnavailable(number, title, question) {
    let body;
    if (state.diagnoseError) {
      body = `<div class="bpl-error-inline"><b>诊断数据暂时读不到</b><p>${esc(state.diagnoseError)}</p><button type="button" class="bpl-primary" data-bpl-diagnose-retry>重试</button></div>`;
    } else if (state.diagnoseLoading) {
      body = '<div class="bpl-loading">正在对齐英雄、阵容与时间窗口…</div>';
    } else {
      body = empty('先选一个英雄', '在上方选择本队与英雄，诊断会按当前时间窗口展开。');
    }
    return section('diagnosePerf', number, title, question, '', body);
  }

  function diagnosisControls(data) {
    const heroes = [...new Set([state.diagnoseHero,
      ...(data.options?.heroes || []), ...((data.heroes?.rows || []).map((row) => row.hero))
    ].filter(Boolean))];
    return `<div class="bpl-diag-controls">
      <label class="bpl-field">诊断英雄
        <select data-bpl-diagnose-hero>${state.diagnoseHero ? '' : '<option value="">自动 · 当前窗口常用英雄</option>'}${heroes.map((hero) =>
          `<option value="${esc(hero)}" ${hero === state.diagnoseHero ? 'selected' : ''}>${esc(hero)}</option>`).join('')}</select></label>
      <label class="bpl-field bpl-diag-enemy">敌方阵容（可选）
        <input data-bpl-diagnose-enemy list="bpl-diag-hero-options" value="${esc(state.diagnoseEnemy)}" placeholder="最多 5 个，逗号分隔" autocomplete="off"></label>
      <button type="button" class="bpl-primary" data-bpl-diagnose-run>重新诊断</button>
      <span class="bpl-muted">当前窗口 vs 前一个等长窗口；敌方阵容用于“特定阵容”反制胜率。</span>
      <datalist id="bpl-diag-hero-options">${(data.options?.heroes || []).map((hero) => `<option value="${esc(hero)}"></option>`).join('')}</datalist>
    </div>`;
  }

  function diagnosePerfSection(data) {
    const d = state.diagnose;
    if (!d?.available) return diagnosisUnavailable('N01–N02', '己方英雄表现', '英雄使用胜率与反制胜率。');
    const current = d.performance.current || {};
    const previous = d.performance.previous || {};
    const delta = current.winRate != null && previous.winRate != null
      ? Math.round((current.winRate - previous.winRate) * 10) / 10 : null;
    const enemyLineup = d.counters.enemyLineup || {};
    const lineupCurrent = enemyLineup.current || {};
    const lineupPrevious = enemyLineup.previous || {};
    const lineupDelta = lineupCurrent.winRate != null && lineupPrevious.winRate != null
      ? Math.round((lineupCurrent.winRate - lineupPrevious.winRate) * 10) / 10 : null;
    const recent = (d.lineups.current || []).slice(0, 6).map((row) =>
      `<div class="bpl-diag-match">${resultMark(row.result)}
        <span>${esc(String(row.date || '').slice(5))}</span>
        <b>${esc(row.opponent || '对手未记录')}</b>
        <small>${esc(row.side === '1' ? '阵营 1' : row.side === '2' ? '阵营 2' : '阵营未知')}</small></div>`).join('');
    const counterRows = (d.locate.enemyHeroes || []).map((row) => [
      heroChip(row.hero, {small: true}),
      `${num(row.games)} 局`,
      diagWin(row),
      row.previousWinRate == null ? '<span class="bpl-muted">—</span>' : rate(row.previousWinRate),
      diagDelta(row.winDelta),
      sampleBadge(row.sample),
    ]);
    const enemyCombos = (d.counters.enemyCombos || []).slice(0, 6).map((row) => [
      `<div class="bpl-combo-cell">${row.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>`,
      `${num(row.games)} 局`, diagWin(row), sampleBadge(row.sample),
    ]);
    const body = `${diagnosisControls(data)}
      <div class="bpl-kpis">
        ${metric('当前窗口', `${num(current.games)} 局`, `${esc(d.period.start)} → ${esc(d.period.end)}`)}
        ${metric('英雄胜率', rate(current.winRate), `${num(current.wins)} 胜 · ${interval(current.interval)}`)}
        ${metric('前窗胜率', rate(previous.winRate), `${num(previous.games)} 局 · ${previous.sample || ''} · 变化 ${delta == null ? '—' : `${delta >= 0 ? '+' : ''}${fmt(delta, 1)} pp`}`)}
        ${metric('全期使用', `${num(d.heroGames.total)} 局`, d.performance.total?.sample || '')}
      </div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>N01 · 英雄使用胜率</h3>${sampleBadge(current.sample)}</div>
          <div class="bpl-diag-form">${recent || '<span class="bpl-muted">当前窗口没有使用记录</span>'}</div>
          ${enemyLineup.heroes?.length ? `<div class="bpl-diag-lineup-stat"><span>指定敌方阵容</span><div class="bpl-chip-row">${enemyLineup.heroes.map((hero) => heroChip(hero, {small: true})).join('')}</div>
            <b>${rate(lineupCurrent.winRate)}</b><small>${num(lineupCurrent.games)} 局 · 前窗 ${rate(lineupPrevious.winRate)} · ${lineupDelta == null ? '—' : `${lineupDelta >= 0 ? '+' : ''}${fmt(lineupDelta, 1)} pp`}</small></div>` : ''}
        </div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N02 · 英雄反制胜率</h3><span class="bpl-muted">敌方英雄出现时，我方所选英雄的胜率</span></div>
          ${dataTable(['敌方英雄', '同场', '我方胜率', '前窗', '变化', '样本'], counterRows, {emptyText: '当前窗口没有可比较的敌方英雄'})}
        </div>
      </div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>N02 补充 · 敌方双人组合</h3><span class="bpl-muted">同场出现过的敌方组合</span></div>
        ${dataTable(['敌方组合', '同场', '我方胜率', '样本'], enemyCombos, {emptyText: '没有重复出现的敌方组合'})}
      </div>`;
    return section('diagnosePerf', 'N01–N02', '己方英雄表现', '英雄使用胜率与反制胜率。',
      `<span class="bpl-section-meta">${esc(d.team)} · ${esc(d.hero)}</span>`, body);
  }

  function diagnoseTrendSection(data) {
    const d = state.diagnose;
    if (!d?.available) return '';
    const trendCards = (d.performance.trend || []).map((row) => `<div class="bpl-diag-period">
      <span>近 ${num(row.days)} 天</span><b>${rate(row.winRate)}</b>
      <small>${num(row.games)} 局 · ${esc(row.sample || '')} · 前窗 ${rate(row.previousWinRate)}</small>
      ${diagDelta(row.delta)}
    </div>`).join('');
    const weekly = (d.performance.weekly || []).map((row) => [
      `<b>${esc(row.key)}</b>`, `${num(row.games)} 局`, diagWin(row), diagDelta(row.delta),
    ]);
    const volatility = (d.counters.volatility || []).map((row) => {
      const series = (row.series || []).map((item) =>
        `<span class="bpl-diag-week"><i>${esc(String(item.weekStart).slice(5))}</i>${rate(item.winRate)}<small>${num(item.games)} 局</small></span>`).join('');
      return `<div class="bpl-diag-vol-row">${heroChip(row.hero, {small: true})}
        <span class="bpl-muted">${num(row.weeks)} 周 · 极差 ${row.range == null ? '—' : `${fmt(row.range, 1)} pp`}</span>
        <div class="bpl-diag-vol-series">${series || '<span class="bpl-muted">周样本不足</span>'}</div></div>`;
    }).join('');
    const body = `<div class="bpl-diag-periods">${trendCards}</div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>N03 · 自然周胜率</h3><span class="bpl-muted">每周至少 1 局</span></div>
          ${dataTable(['周', '局数', '胜率', '较前周'], weekly, {emptyText: '没有周记录'})}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N04 · 反制效果波动</h3><span class="bpl-muted">敌方英雄按周的我方胜率</span></div>
          ${volatility || empty('没有可计算的反制波动', '需要至少两周、且敌方英雄有同场记录。')}</div>
      </div>`;
    return section('diagnoseTrend', 'N03–N04', '周期趋势分析', '周、近 7/15/30 天胜率与反制效果波动。',
      `<span class="bpl-section-meta">${esc(d.period.start)} → ${esc(d.period.end)}</span>`, body);
  }

  function diagnoseAnomalySection(data) {
    const d = state.diagnose;
    if (!d?.available) return '';
    const a = d.anomaly || {};
    const cur = a.current || {};
    const base = a.baseline || {};
    const severity = a.severity === '高' ? 'is-bad' : a.severity === '中' ? 'is-mid'
      : a.severity === '低' ? 'is-low' : 'is-good';
    const body = `<div class="bpl-diag-anomaly ${a.significant ? 'is-significant' : ''}">
      <div class="bpl-diag-anomaly-main">
        <span class="bpl-badge ${severity}">${esc(a.verdict || '未触发')}</span>
        <b>${a.drop == null ? '—' : `${a.drop >= 0 ? '+' : ''}${fmt(a.drop, 1)} pp`}</b>
        <small>当前 ${rate(cur.winRate)}（${num(cur.games)} 局） vs 基准 ${rate(base.winRate)}（${num(base.games)} 局）</small>
      </div>
      <div class="bpl-diag-anomaly-grid">
        ${metric('N05 · 异常下降', a.drop == null ? '—' : `${a.drop >= 0 ? '+' : ''}${fmt(a.drop, 1)} pp`, `严重度 ${a.severity || '—'}`)}
        ${metric('N06 · 显著性', a.significant ? '显著' : '未显著', `p = ${a.pValue == null ? '—' : fmt(a.pValue, 4)} · z = ${a.z == null ? '—' : fmt(a.z, 2)}`)}
        ${metric('基准口径', base.scope === 'history' ? '历史全部' : '前一个等长窗口', `${esc(base.start || '')} → ${esc(base.end || '')}`)}
        ${metric('历史波动', a.volatility == null ? '—' : `${fmt(a.volatility, 1)} pp`, '周胜率极差')}
      </div>
    </div>
    <div class="bpl-card"><div class="bpl-card-head"><h3>判定规则</h3><span class="bpl-muted">不把噪声写成结论</span></div>
      <ul class="bpl-list">${(a.caveats || []).map((text) => `<li><span>${esc(text)}</span></li>`).join('')}</ul>
      <p class="bpl-note">显著性只看“当前窗口相对基准是否可能只是波动”；它不解释原因，原因在 N07–N14 继续定位。</p>
    </div>`;
    return section('diagnoseAnomaly', 'N05–N06', '异常检测与显著性', '胜率是否真的异常下降，幅度是否超出样本噪声？',
      `<span class="bpl-section-meta">${a.significant ? '触发' : '未触发'} · ${esc(d.hero)}</span>`, body);
  }

  function diagnoseLocateSection(data) {
    const d = state.diagnose;
    if (!d?.available) return '';
    const locate = d.locate || {};
    const partnerRows = (locate.partners || []).map((row) => [
      heroChip(row.hero, {small: true}), `${num(row.games)} 局`, rate(row.share),
      row.previousShare == null ? '—' : rate(row.previousShare), diagDelta(row.shareDelta),
      diagWin(row), sampleBadge(row.sample),
    ]);
    const enemyRows = (locate.enemyHeroes || []).map((row) => [
      heroChip(row.hero, {small: true}), rate(row.share),
      row.previousShare == null ? '—' : rate(row.previousShare), diagDelta(row.shareDelta),
      diagWin(row), sampleBadge(row.sample),
    ]);
    const lane = locate.laneOpponents || {};
    const laneRows = (lane.heroes || []).map((row) => [
      heroChip(row.hero, {small: true}), `${num(row.games)} 局`, diagWin(row),
      row.previousWinRate == null ? '—' : rate(row.previousWinRate), diagDelta(row.winDelta),
      sampleBadge(row.sample),
    ]);
    const playerRows = (locate.players || []).map((row) => [
      `<b>${esc(row.player)}</b>`, esc(row.lane || '—'), `${num(row.games)} 局`,
      rate(row.share), row.previousShare == null ? '—' : rate(row.previousShare),
      diagDelta(row.shareDelta), diagWin(row),
    ]);
    const ctx = locate.context?.current || {};
    const ctxRows = (ctx.opponents || []).map((row) => [
      `<b>${esc(row.key)}</b>`, `${num(row.games)} 局`, diagWin(row),
      row.opponentWinRate == null ? '<span class="bpl-muted">—</span>'
        : `<div class="bpl-win"><b>${rate(row.opponentWinRate)}</b><small>${num(row.opponentGames)} 局</small></div>`,
    ]);
    const sideRows = (ctx.sides || []).map((row) => [
      `<b>阵营 ${esc(row.key)}</b>`, `${num(row.games)} 局`, diagWin(row),
    ]);
    const body = `<div class="bpl-diag-note-row">${d.compareAvailable
      ? `当前窗口 vs 前一个等长窗口（前窗 ${num(d.heroGames.previous)} 局）；变化是记录差异，不代表因果。`
      : '前一个等长窗口没有同英雄记录；下表只列当前窗口，N12 / N16 不做前后差异。'}</div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>N07 · 英雄阵容搭配变化</h3><span class="bpl-muted">同队同局搭档</span></div>
          ${dataTable(['搭档', '当前局', '占比', '前窗占比', '占比变化', '胜率', '样本'], partnerRows, {emptyText: '没有搭档记录'})}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N08 · 敌方阵容变化</h3><span class="bpl-muted">敌方英雄出现率</span></div>
          ${dataTable(['敌方英雄', '当前占比', '前窗占比', '占比变化', '当前胜率', '样本'], enemyRows, {emptyText: '没有敌方英雄记录'})}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N09 · 对位英雄变化</h3><span class="bpl-muted">${lane.available ? `同分路 · ${esc(lane.lane)}` : '分路缺失'}</span></div>
          ${lane.available ? dataTable(['对位英雄', '同场', '我方胜率', '前窗', '变化', '样本'], laneRows, {emptyText: '当前窗口没有对位记录'}) : empty('无法定位对位英雄', lane.reason || '缺少分路映射。')}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N10 · 选手变化</h3><span class="bpl-muted">使用该英雄的选手</span></div>
          ${dataTable(['选手', '分路', '当前局', '占比', '前窗占比', '占比变化', '胜率'], playerRows, {emptyText: '没有选手-英雄映射'})}</div>
      </div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>N11 · 对手强度与阵营</h3><span class="bpl-muted">对手、阵营、赛事分布</span></div>
        <div class="bpl-grid bpl-grid-even">
          <div>${dataTable(['对手', '同场', '我方胜率', '对手整体胜率'], ctxRows, {emptyText: '没有对手记录'})}</div>
          <div>${dataTable(['阵营', '同场', '我方胜率'], sideRows, {emptyText: '没有阵营记录'})}</div>
        </div>
      </div>`;
    return section('diagnoseLocate', 'N07–N11', '异常定位', '搭档、敌方阵容、对位、选手、对手与阵营，哪一块变了？',
      `<span class="bpl-section-meta">当前 ${num(d.heroGames.current)} 局 · 前窗 ${num(d.heroGames.previous)} 局</span>`, body);
  }

  function diagnoseAttributionSection(data) {
    const d = state.diagnose;
    if (!d?.available) return '';
    const assocRows = (d.associations || []).map((row) => [
      `<span class="bpl-badge ${row.kind === '搭档' ? 'is-good' : 'is-mid'}">${esc(row.kind)}</span>`,
      row.kind === '搭档' ? heroChip(row.object, {small: true}) : esc(row.object),
      `${num(row.currentGames)} / ${num(row.previousGames)}`,
      diagDelta(row.shareDelta), rate(row.currentWinRate), rate(row.previousWinRate),
      diagDelta(row.winDelta),
    ]);
    const labels = {kda: 'KDA', kills: '击杀', assists: '助攻', deaths: '死亡',
      gold: '经济（金币）', heroDamage: '对英雄伤害', taken: '承伤',
      participation: '参团率', towers: '推塔'};
    const units = {participation: '%', towers: ' 座'};
    const perf = d.performanceStats || {};
    const perfRows = perf.current?.available ? Object.entries(labels).map(([key, label]) => {
      const cur = perf.current.metrics?.[key];
      const prev = perf.previous?.metrics?.[key];
      const delta = perf.delta?.[key];
      return [`<b>${esc(label)}</b>`,
        cur == null ? '—' : `${fmt(cur, 1)}${units[key] || ''}`,
        prev == null ? '—' : `${fmt(prev, 1)}${units[key] || ''}`,
        diagDelta(delta, units[key] === '%' ? ' pp' : '')];
    }) : [];
    const tempo = d.tempo?.current || {};
    const tempoPrevious = d.tempo?.previous || {};
    const tempoRows = Object.entries(tempo.checkpoints || {}).map(([stamp, row]) => {
      const prev = tempoPrevious.checkpoints?.[stamp];
      const delta = row.avgGoldDiff != null && prev?.avgGoldDiff != null
        ? Math.round((row.avgGoldDiff - prev.avgGoldDiff) * 10) / 10 : null;
      const minutes = {120: '2 分钟', 240: '4 分钟', 600: '10 分钟'}[stamp] || `${stamp}s`;
      return [`<b>${minutes}</b>`, `${num(row.games)} 局`,
        row.avgGoldDiff == null ? '—' : `${row.avgGoldDiff >= 0 ? '+' : ''}${fmt(row.avgGoldDiff, 1)}`,
        prev?.avgGoldDiff == null ? '—' : `${prev.avgGoldDiff >= 0 ? '+' : ''}${fmt(prev.avgGoldDiff, 1)}`,
        diagDelta(delta, '')];
    });
    const body = `<div class="bpl-card"><div class="bpl-card-head"><h3>N12 · 阵容关联因素分析</h3><span class="bpl-muted">变化并列，不写因果</span></div>
      ${d.associationAvailable ? dataTable(['类型', '对象', '当前/前窗局数', '占比变化', '当前胜率', '前窗胜率', '胜率变化'], assocRows, {emptyText: '没有可比较的阵容因素'}) : empty('前窗样本不足，暂不做阵容关联', d.associationReason || '前一个等长窗口没有足够的同英雄记录。')}
      <p class="bpl-note">这些因素只是和胜率变化同时出现；样本不足时不下“导致”结论。</p></div>
      <div class="bpl-grid bpl-grid-even">
        <div class="bpl-card"><div class="bpl-card-head"><h3>N13 · 比赛表现变化</h3><span class="bpl-muted">${perf.current?.available ? `当前 ${num(perf.current.games)} 局 / 前窗 ${num(perf.previous?.games)} 局` : '逐人统计'}</span></div>
          ${perf.current?.available ? dataTable(['指标', '当前', '前窗', '变化'], perfRows) : empty('当前来源没有逐人表现', perf.current?.reason || 'KPL 只有名单与分路，没有逐人经济/KDA/输出。')}</div>
        <div class="bpl-card"><div class="bpl-card-head"><h3>N14 · 团战与节奏变化</h3><span class="bpl-muted">有回放匹配时</span></div>
          ${tempo.available ? `${dataTable(['经济检查点', '样本', '当前队级经济差', '前窗', '变化'], tempoRows)}<p class="bpl-note">${esc(tempo.note || '')}</p>` : empty('没有回放经济曲线', tempo.reason || '团战与资源控制需要事件数据。')}</div>
      </div>`;
    return section('diagnoseAttribution', 'N12–N14', '异常归因', '阵容、比赛表现与节奏，哪些变化与胜率同向？',
      `<span class="bpl-section-meta">${d.associationAvailable ? `${(d.associations || []).length} 个关联因素` : '前窗样本不足'}</span>`, body);
  }

  function lineupLine(row) {
    return `<div class="bpl-diag-lineup">
      <div class="bpl-diag-lineup-head">${resultMark(row.result)}<b>${esc(String(row.date || '').slice(5))}</b><span>${esc(row.opponent || '对手未记录')}</span><small>${esc(row.side === '1' ? '阵营 1' : row.side === '2' ? '阵营 2' : '阵营未知')}</small></div>
      <div class="bpl-diag-lineup-picks"><span>我方</span><div class="bpl-chip-row">${(row.own || []).map((hero) => heroChip(hero, {small: true})).join('') || '<span class="bpl-muted">—</span>'}</div></div>
      <div class="bpl-diag-lineup-picks"><span>敌方</span><div class="bpl-chip-row">${(row.enemy || []).map((hero) => heroChip(hero, {small: true})).join('') || '<span class="bpl-muted">—</span>'}</div></div>
    </div>`;
  }

  function diagnoseLineupSection(data) {
    const d = state.diagnose;
    if (!d?.available) return '';
    const diff = d.diff || {};
    const diffBlock = (title, row) => `<div class="bpl-diag-diff">
      <b>${esc(title)}</b>
      <div><span class="bpl-muted">新增</span><div class="bpl-chip-row">${(row.added || []).map((hero) => heroChip(hero, {small: true})).join('') || '<span class="bpl-muted">—</span>'}</div></div>
      <div><span class="bpl-muted">消失</span><div class="bpl-chip-row">${(row.removed || []).map((hero) => heroChip(hero, {small: true})).join('') || '<span class="bpl-muted">—</span>'}</div></div>
      <div><span class="bpl-muted">共有</span><div class="bpl-chip-row">${(row.common || []).slice(0, 8).map((hero) => heroChip(hero, {small: true})).join('') || '<span class="bpl-muted">—</span>'}</div></div>
    </div>`;
    const periods = (d.lineupPeriods || []).map((period) =>
      `<details class="bpl-details"><summary>${esc(period.period)} · ${num(period.games)} 局</summary>
        <div class="bpl-diag-lineup-list">${(period.lineups || []).map(lineupLine).join('')}</div></details>`).join('');
    const currentList = (d.lineups.current || []).slice(0, 6).map(lineupLine).join('');
    const previousList = (d.lineups.previous || []).slice(0, 6).map(lineupLine).join('');
    const body = `<div class="bpl-grid bpl-grid-even">
      <div class="bpl-card"><div class="bpl-card-head"><h3>N15 · 当前窗口阵容明细</h3><span class="bpl-muted">最近 ${num(Math.min(6, (d.lineups.current || []).length))} · 共 ${num(d.heroGames.current)} 局</span></div>
        <div class="bpl-diag-lineup-list">${currentList || empty('当前窗口没有阵容记录')}</div></div>
      <div class="bpl-card"><div class="bpl-card-head"><h3>N15 · 前窗阵容明细</h3><span class="bpl-muted">最近 ${num(Math.min(6, (d.lineups.previous || []).length))} · 共 ${num(d.heroGames.previous)} 局</span></div>
        <div class="bpl-diag-lineup-list">${previousList || empty('前窗没有阵容记录')}</div></div>
    </div>
    <div class="bpl-card"><div class="bpl-card-head"><h3>N16 · 阵容差异识别</h3><span class="bpl-muted">当前 vs 前窗</span></div>
      ${d.diff?.available ? `<div class="bpl-diag-diff-grid">
        ${diffBlock('搭档', diff.partner || {})}
        ${diffBlock('敌方英雄', diff.enemy || {})}
        ${diffBlock('对位英雄', diff.lane || {})}
      </div>
      <p class="bpl-note">差异是集合差异，表示“这批阵容里出现了/消失了谁”，不直接代表战术优劣。</p>` : empty('前窗样本不足，暂不识别差异', d.diff?.reason || '前一个等长窗口没有足够的同英雄记录。')}
    </div>
    <details class="bpl-details"><summary>按月展开多周期阵容</summary>
      <div class="bpl-diag-periods-list">${periods || '<span class="bpl-muted">没有更多周期</span>'}</div>
    </details>`;
    return section('diagnoseLineup', 'N15–N16', '阵容对比', '多周期阵容明细与差异识别。',
      `<span class="bpl-section-meta">${num(d.heroGames.total)} 局全期</span>`, body);
  }


  function simulateSection(data) {
    const sim = state.sim;
    const result = sim.result;
    const team = state.team || data.options?.defaultTeam || '本队';
    const opponent = state.opponent || data.options?.defaultOpponent || '对手';
    const controls = `<div class="bpl-research-controls bpl-sim-controls">
      <label class="bpl-field">证据来源<select data-bpl-sim-field="evidenceSource">
        <option value="kpl" ${sim.evidenceSource === 'kpl' ? 'selected' : ''}>KPL（含挑战者杯）</option>
        <option value="scrim" ${sim.evidenceSource === 'scrim' ? 'selected' : ''}>训练赛</option>
      </select></label>
      <label class="bpl-field">规则<select data-bpl-sim-field="rule">
        <option value="scrim-global-20" ${sim.rule === 'scrim-global-20' ? 'selected' : ''}>20 手 · 每方 5 Ban + 10 Pick</option>
      </select></label>
      <label class="bpl-field">赛制<select data-bpl-sim-field="bo">
        ${['BO3', 'BO5', 'BO7'].map((value) => `<option value="${value}" ${value === sim.bo ? 'selected' : ''}>${value}</option>`).join('')}
      </select></label>
      <label class="bpl-field">我方阵营<select data-bpl-sim-field="side">
        <option value="1" ${sim.side === '1' ? 'selected' : ''}>阵营 1 · 蓝</option>
        <option value="2" ${sim.side === '2' ? 'selected' : ''}>阵营 2 · 红</option>
      </select></label>
      <button type="button" class="bpl-ghost" data-bpl-sim-reset>重开本局</button>
    </div>`;
    const events = result?.events || sim.events || [];
    const eventHtml = events.length ? `<div class="bpl-sim-events">${events.map((event) => `<span class="bpl-sim-event ${event.action === 'ban' ? 'is-ban' : 'is-pick'}">
      <i>${event.order}</i>${event.action === 'ban' ? 'Ban' : 'Pick'} · ${event.camp === sim.side ? '我方' : '对手'} · ${esc(event.hero)}
    </span>`).join('')}</div>` : '<p class="bpl-muted">还没有动作。第一手从当前规则的第一个 Ban 开始。</p>';
    let body = '';
    if (sim.loading) {
      body = '<div class="bpl-loading">正在按训练赛规则生成候选…</div>';
    } else if (sim.error) {
      body = `<div class="bpl-error-inline"><b>沙盘暂时读不到</b><p>${esc(sim.error)}</p><button type="button" class="bpl-primary" data-bpl-sim-run>重试</button></div>`;
    } else if (!result) {
      body = `<div class="bpl-lookup-prompt"><b>从空局开始，或重开本局。</b><p>规则只走训练赛 15/20 手；证据来源可切 KPL 或训练赛。</p><button type="button" class="bpl-primary" data-bpl-sim-run>开始沙盘</button></div>`;
    } else if (result.complete) {
      body = `<div class="bpl-empty"><b>本局 BP 已完成</b><p>${esc(result.note || '')}</p><button type="button" class="bpl-primary" data-bpl-sim-reset>重开本局</button></div>`;
    } else {
      const actor = result.actor === 'opponent' ? '对手回合' : '我方回合';
      const next = result.nextAction || {};
      const candidates = result.candidates || [];
      const candidateRows = candidates.map((row) => `<div class="bpl-sim-candidate">
        <div class="bpl-sim-candidate-top">${heroChip(row.hero)}<b>${fmt(row.score, 1)}</b>
          <span class="bpl-badge ${row.confidence === 'high' ? 'is-good' : row.confidence === 'medium' ? 'is-mid' : 'is-low'}">${row.confidence === 'high' ? '证据较足' : row.confidence === 'medium' ? '中等证据' : '低样本'}</span>
          <button type="button" class="bpl-primary bpl-sim-choose" data-bpl-sim-candidate="${esc(row.hero)}">选这个</button>
        </div>
        <p>${(row.reasons || []).map((text) => esc(text)).join(' · ')}</p>
      </div>`).join('');
      const branches = (result.branches || []).map((branch) => {
        const nextInfo = branch.opponentNext;
        if (!nextInfo) return `<div class="bpl-sim-branch"><b>选 ${esc(branch.candidate.hero)}</b><span>${esc(branch.note || '本局结束')}</span></div>`;
        const options = (nextInfo.options || []).map((option) => `<button type="button" class="bpl-sim-response" data-bpl-sim-response="${esc(option.hero)}" data-bpl-sim-action="${esc(nextInfo.action)}" data-bpl-sim-camp="${sim.side === '1' ? '2' : '1'}" title="假设对手选这个">
          ${esc(option.hero)}<small>${num(option.opponentPicks)} 次</small></button>`).join('');
        return `<div class="bpl-sim-branch"><b>选 ${esc(branch.candidate.hero)} 后</b><span>对手 ${nextInfo.action === 'ban' ? 'Ban' : 'Pick'} 可能：</span><div class="bpl-chip-row">${options || `<span class="bpl-muted">${esc(nextInfo.note || '样本不足')}</span>`}</div></div>`;
      }).join('');
      body = `<div class="bpl-sim-status"><span class="bpl-eyebrow">BP SANDBOX</span><b>${actor}</b><span>下一步：${next.action === 'ban' ? 'Ban' : 'Pick'} · ${next.camp == null ? '' : (String(next.camp) === sim.side ? '我方' : '对手')} · 第 ${next.order || events.length + 1} 手</span></div>
        <div class="bpl-sim-candidates">${candidateRows || '<span class="bpl-muted">没有合法候选。</span>'}</div>
        ${branches ? `<div class="bpl-sim-branches"><h3>选后对手一步回应</h3>${branches}</div>` : ''}
        <p class="bpl-note">${esc(result.note || '')}</p>
        ${(result.caveats || []).map((text) => note(text)).join('')}`;
    }
    const bodyHtml = `<div class="bpl-card bpl-sim-card"><div class="bpl-card-head"><h3>当前 BP 局面</h3><span class="bpl-muted">${esc(team)} vs ${esc(opponent)} · 训练赛规则</span></div>
      ${controls}${eventHtml}${body}</div>`;
    return section('simulate', '10', 'BP 策略沙盘', '面对当前 BP 局面，下一手有哪些有证据的候选？',
      `<span class="bpl-section-meta">${esc(team)} vs ${esc(opponent)}</span>`, bodyHtml);
  }

  // -------------------------------------------------------------------------
  // 渲染
  // -------------------------------------------------------------------------
  function skeleton() {
    return `<div class="page bpl-page">${hero()}${toolbar()}${viewTabs()}<div class="bpl-loading">正在汇总 ${state.source === 'kpl' ? 'KPL' : '训练赛'} BP 数据…</div></div>`;
  }

  function errorPage() {
    return `<div class="page bpl-page">${hero()}${toolbar()}${viewTabs()}
      <div class="bpl-error"><b>BP 数据暂时读不到</b><p>${esc(state.error)}</p><button type="button" class="bpl-primary" data-bpl-refresh>重试</button></div></div>`;
  }

  const SECTION_RENDERERS = {
    heroes: heroesSection, combos: combosSection, opponent: opponentResearchSection,
    counters: countersSection, habits: habitsSection, evolution: evolutionSection,
    scrim: scrimSection, stability: stabilitySection, plan: planSection,
    simulate: simulateSection,
    diagnosePerf: diagnosePerfSection, diagnoseTrend: diagnoseTrendSection,
    diagnoseAnomaly: diagnoseAnomalySection, diagnoseLocate: diagnoseLocateSection,
    diagnoseAttribution: diagnoseAttributionSection, diagnoseLineup: diagnoseLineupSection,
  };
  function render(data) {
    const view = activeView();
    const sections = view.sections.map((key) => SECTION_RENDERERS[key](data)).join('');
    return `<div class="page bpl-page">
      ${hero()}${toolbar()}${viewTabs()}${jumpNav()}
      <div class="bpl-sections">${sections}</div>
      <div class="bpl-caveats">${(data.caveats || []).map((text) => note(text)).join('')}</div>
    </div>`;
  }

  function restoreAnchor() {
    if (!state.pendingAnchor || state.loading || !state.data) return;
    const target = document.getElementById(`bpl-${state.pendingAnchor}`);
    if (!target) return;
    const anchor = state.pendingAnchor;
    state.pendingAnchor = '';
    requestAnimationFrame(() => target.scrollIntoView({block: 'start'}));
  }

  function paint() {
    if (!state.root) return;
    if (state.loading && !state.data) {
      state.root.innerHTML = skeleton();
    } else if (state.error) {
      state.root.innerHTML = errorPage();
    } else if (!state.data) {
      state.root.innerHTML = skeleton();
    } else {
      state.root.innerHTML = render(state.data);
      bindJump();
      if (state.view === 'simulate') ensureSim();
      if (state.view === 'diagnose') ensureDiagnose();
      if (state.view === 'database') ensureComboDetail();
      ensureCompare();
      if (state.view === 'opponent') ensureOpponentCompare();
      restoreAnchor();
    }
  }

  function bindJump() {
    state.observer?.disconnect();
    const root = state.root;
    if (!root || typeof IntersectionObserver === 'undefined') return;
    const buttons = [...root.querySelectorAll('[data-bpl-jump]')];
    const sections = [...root.querySelectorAll('[data-bpl-section]')];
    if (!buttons.length || !sections.length) return;
    state.observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const active = entry.target.dataset.bplSection;
        buttons.forEach((button) => button.classList.toggle('is-active', button.dataset.bplJump === active));
      }
    }, {rootMargin: '-18% 0px -72% 0px'});
    sections.forEach((section) => state.observer.observe(section));
  }

  // -------------------------------------------------------------------------
  // 交互
  // -------------------------------------------------------------------------
  function resetForSource(source) {
    state.source = source;
    state.league = 'all';
    state.team = '';
    state.opponent = '';
    state.from = '';
    state.to = '';
    state.unit = source === 'scrim' ? 'day' : 'month';
    state.recentDays = source === 'scrim' ? 7 : 30;
    state.target = [];
    state.combo = [];
    state.lane = '';
    state.lookup = null;
    state.lookupOpen = false;
    state.lookupText = '';
    state.counters = null;
    state.stability = null;
    state.opponentResearch = null;
    state.opponentSide = '';
    state.opponentFirstPick = '';
    state.opponentCombo = [];
    state.opponentHero = '';
    state.sim.evidenceSource = source;
    state.compare = null;
    state.compareLoading = false;
    state.compareError = '';
    state.opponentCompare = null;
    state.opponentCompareLoading = false;
    state.opponentCompareError = '';
    state.sim.events = [];
    state.sim.result = null;
    state.sim.error = '';
    state.diagnose = null;
    state.diagnoseLoading = false;
    state.diagnoseError = '';
    state.diagnoseHero = '';
    state.diagnoseEnemy = '';
    state.diagnoseSeq += 1;
    state.comboPick = [];
    state.comboDetail = null;
    state.comboDetailError = '';
    state.comboDetailSeq += 1;
    state.comboDetailController?.abort();
    state.diagnoseController?.abort();
    state.data = null;
    state.error = '';
  }

  function onSource(source) {
    if (source === state.source) return;
    resetForSource(source);
    void load();
  }

  function setPick(action, heroes) {
    if (action === 'combo') {
      state.comboPick = heroes;
      state.comboDetail = null;
      state.comboDetailError = '';
      state.comboDetailSeq += 1;
      state.comboDetailController?.abort();
      if (heroes.length >= 2) void loadComboDetail();
      else paint();
      return;
    }
    if (action === 'counter') {
      state.target = heroes;
      state.counters = null;
      state.compare = null;
      state.compareLoading = false;
      state.compareError = '';
      state.compareSeq.focus += 1;
      if (heroes.length) {
        void loadCounters(heroes);
        void loadCompare('focus');
      }
      paint();
      return;
    }
    if (action === 'stability') {
      state.combo = heroes;
      state.stability = null;
      if (heroes.length >= 2) void loadStability(heroes);
      else paint();
    }
  }

  function togglePick(action, hero) {
    const current = action === 'combo' ? [...(state.comboPick || [])]
      : action === 'counter' ? [...(state.target || [])]
        : [...(state.combo || [])];
    const limit = 3;
    const exists = current.includes(hero);
    const next = exists ? current.filter((item) => item !== hero)
      : current.length >= limit ? current : [...current, hero];
    if (!exists && current.length >= limit) return;
    setPick(action, next);
  }

  function onChange(event) {
    const target = event.target;
    const field = target.closest('[data-bpl-field]')?.dataset.bplField;
    if (field) {
      const value = target.value;
      if (field === 'from' || field === 'to') state[field] = value;
      else if (field === 'unit') state.unit = value;
      else if (field === 'recentDays') state.recentDays = Number(value) || 30;
      else if (field === 'rule') state.rule = value;
      else if (field === 'bo') state.bo = value;
      else state[field] = value;
      if (field === 'rule' || field === 'bo') { void load(); return; }
      state.counters = null;
      state.stability = null;
      state.lookup = null;
      state.lookupOpen = false;
      state.opponentResearch = null;
      if (['league', 'from', 'to', 'team', 'opponent', 'recentDays'].includes(field)) {
        state.opponentSide = '';
        state.opponentFirstPick = '';
        state.opponentCombo = [];
        state.opponentHero = '';
        state.sim.events = [];
        state.sim.result = null;
        state.sim.error = '';
        state.compare = null;
        state.compareLoading = false;
        state.compareError = '';
        state.opponentCompare = null;
        state.opponentCompareLoading = false;
        state.opponentCompareError = '';
        state.compareSeq.focus += 1;
        state.compareSeq.opponent += 1;
        state.diagnose = null;
        state.diagnoseLoading = false;
        state.diagnoseError = '';
        state.diagnoseSeq += 1;
        state.diagnoseController?.abort();
        if (field === 'team' || field === 'league') {
          state.diagnoseHero = '';
          state.comboPick = [];
          state.comboDetail = null;
          state.comboDetailError = '';
          state.comboDetailSeq += 1;
          state.comboDetailController?.abort();
        }
      }
      void load();
      return;
    }
    if (target.matches('[data-bpl-diagnose-hero]')) {
      state.diagnoseHero = target.value || '';
      state.diagnose = null;
      state.diagnoseError = '';
      state.diagnoseSeq += 1;
      state.diagnoseController?.abort();
      void loadDiagnose();
      return;
    }
    if (target.matches('[data-bpl-diagnose-enemy]')) {
      state.diagnoseEnemy = target.value || '';
      return;
    }
    if (target.matches('[data-bpl-research-opponent]')) {
      state.opponent = target.value || '';
      state.opponentResearch = null;
      state.opponentSide = '';
      state.opponentFirstPick = '';
      state.opponentCombo = [];
      state.opponentHero = '';
      void load();
      return;
    }
    if (target.matches('[data-bpl-sim-field]')) {
      const field = target.dataset.bplSimField;
      state.sim[field] = target.value;
      state.sim.events = [];
      state.sim.result = null;
      state.sim.error = '';
      if (state.view === 'simulate') void runSim();
      return;
    }
    if (target.matches('[data-bpl-research-side]')) {
      state.opponentSide = target.value || '';
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    if (target.matches('[data-bpl-research-first-pick]')) {
      state.opponentFirstPick = target.value || '';
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    if (target.matches('[data-bpl-research-combo]')) {
      state.opponentCombo = (target.value || '').split(',').filter(Boolean);
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    if (target.matches('[data-bpl-research-hero]')) {
      state.opponentHero = target.value || '';
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    if (target.matches('[data-bpl-target]')) {
      const value = target.value || '';
      state.target = value.startsWith('hero:')
        ? [value.slice(5)] : value.startsWith('combo:') ? value.slice(6).split(',') : [];
      state.counters = null;
      state.compare = null;
      state.compareLoading = false;
      state.compareError = '';
      state.compareSeq.focus += 1;
      void loadCounters(state.target);
      void loadCompare('focus');
      return;
    }
    if (target.matches('[data-bpl-stability-combo]')) {
      state.combo = (target.value || '').split(',').filter(Boolean);
      state.stability = null;
      void loadStability(state.combo);
    }
  }

  function onClick(event) {
    const view = event.target.closest('[data-bpl-view]');
    if (view) {
      state.view = view.dataset.bplView || 'database';
      paint();
      if (state.view === 'simulate') ensureSim();
      ensureCompare();
      if (state.view === 'opponent') ensureOpponentCompare();
      return;
    }
    const source = event.target.closest('[data-bpl-source]');
    if (source) { onSource(source.dataset.bplSource); return; }
    const pickerSummary = event.target.closest('[data-bpl-picker-details] > summary');
    if (pickerSummary) {
      const key = pickerSummary.parentElement.dataset.bplPickerDetails;
      state[`${key}PickerOpen`] = true;
    }
    const sectionDays = event.target.closest('[data-bpl-section-days]');
    if (sectionDays) {
      state.recentDays = Number(sectionDays.dataset.bplSectionDays) || 30;
      state.from = '';
      state.to = '';
      state.pendingAnchor = sectionDays.dataset.bplSectionAnchor || '';
      void load();
      return;
    }
    const sectionClear = event.target.closest('[data-bpl-section-clear]');
    if (sectionClear) {
      state.from = '';
      state.to = '';
      state.pendingAnchor = sectionClear.dataset.bplSectionClear || '';
      void load();
      return;
    }
    const pickClear = event.target.closest('[data-bpl-picker-clear]');
    if (pickClear) { setPick(pickClear.dataset.bplPickerClear, []); return; }
    const pickRemove = event.target.closest('[data-bpl-pick-remove]');
    if (pickRemove) {
      const action = pickRemove.dataset.bplPickerAction;
      const hero = pickRemove.dataset.bplPickRemove;
      const current = action === 'combo' ? state.comboPick
        : action === 'counter' ? state.target : state.combo;
      setPick(action, (current || []).filter((item) => item !== hero));
      return;
    }
    const pickHero = event.target.closest('[data-bpl-pick]');
    if (pickHero) {
      togglePick(pickHero.dataset.bplPick, pickHero.dataset.bplPickHero);
      return;
    }
    const comboPick = event.target.closest('[data-bpl-combo-pick]');
    if (comboPick) {
      const heroes = (comboPick.dataset.bplComboPick || '').split(',').filter(Boolean);
      if (heroes.length) setPick('combo', heroes);
      return;
    }
    const comboRetry = event.target.closest('[data-bpl-combo-retry]');
    if (comboRetry) { void loadComboDetail(true); return; }
    const compareRun = event.target.closest('[data-bpl-compare-run]');
    if (compareRun) {
      const kind = compareRun.dataset.bplCompareRun === 'opponent' ? 'opponent' : 'focus';
      if (kind === 'opponent') {
        state.opponentCompare = null; state.opponentCompareError = ''; void loadCompare('opponent');
      } else {
        state.compare = null; state.compareError = ''; void loadCompare('focus');
      }
      return;
    }
    const simRun = event.target.closest('[data-bpl-sim-run]');
    if (simRun) { state.sim.result = null; void runSim(); return; }
    const diagnoseRun = event.target.closest('[data-bpl-diagnose-run]');
    if (diagnoseRun) {
      state.diagnose = null;
      state.diagnoseError = '';
      void loadDiagnose();
      return;
    }
    const diagnoseRetry = event.target.closest('[data-bpl-diagnose-retry]');
    if (diagnoseRetry) {
      state.diagnose = null;
      state.diagnoseError = '';
      void loadDiagnose();
      return;
    }
    const simReset = event.target.closest('[data-bpl-sim-reset]');
    if (simReset) {
      state.sim.events = [];
      state.sim.result = null;
      state.sim.error = '';
      void runSim();
      return;
    }
    const simCandidate = event.target.closest('[data-bpl-sim-candidate]');
    if (simCandidate && state.sim.result?.nextAction) {
      const next = state.sim.result.nextAction;
      appendSimEvent(next.action, next.camp, simCandidate.dataset.bplSimCandidate);
      return;
    }
    const simResponse = event.target.closest('[data-bpl-sim-response]');
    if (simResponse) {
      appendSimEvent(simResponse.dataset.bplSimAction,
                     simResponse.dataset.bplSimCamp,
                     simResponse.dataset.bplSimResponse);
      return;
    }
    const cta = event.target.closest('[data-bpl-cta-source]');
    if (cta) { onSource(cta.dataset.bplCtaSource); return; }
    const refresh = event.target.closest('[data-bpl-refresh]');
    if (refresh) { void load(); return; }
    const jump = event.target.closest('[data-bpl-jump]');
    if (jump) {
      event.preventDefault();
      const target = document.querySelector(`#bpl-${jump.dataset.bplJump}`);
      target?.scrollIntoView({behavior: 'smooth', block: 'start'});
      return;
    }
    const lane = event.target.closest('[data-bpl-lane]');
    if (lane) { state.lane = lane.dataset.bplLane || ''; paint(); return; }
    const sort = event.target.closest('[data-bpl-combo-sort]');
    if (sort) { state.comboSort = sort.dataset.bplComboSort || 'usage'; paint(); return; }
    const advanced = event.target.closest('.bpl-advanced > summary');
    if (advanced) { state.lookupOpen = true; return; }
    const researchCombo = event.target.closest('button[data-bpl-research-combo]');
    if (researchCombo) {
      state.opponentCombo = (researchCombo.dataset.bplResearchCombo || '').split(',').filter(Boolean);
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    const researchHero = event.target.closest('button[data-bpl-research-hero]');
    if (researchHero) {
      state.opponentHero = researchHero.dataset.bplResearchHero || '';
      state.opponentResearch = null;
      void loadOpponentResearch();
      return;
    }
    const example = event.target.closest('[data-bpl-example]');
    if (example) {
      state.lookupText = example.dataset.bplExample || '';
      const heroes = parseHeroes(state.lookupText);
      if (heroes.length) void loadLookup(heroes);
      return;
    }
    const copy = event.target.closest('[data-bpl-copy]');
    if (copy) {
      const text = planText(state.data?.plan || {});
      if (!navigator.clipboard?.writeText) {
        copy.textContent = '复制失败';
        setTimeout(() => { copy.textContent = '复制方案'; }, 2000);
        return;
      }
      navigator.clipboard.writeText(text).then(() => {
        copy.textContent = '已复制';
        setTimeout(() => { copy.textContent = '复制方案'; }, 2000);
      }).catch(() => { copy.textContent = '复制失败'; });
    }
  }

  function onInput(event) {
    const input = event.target.closest('[data-bpl-picker-search]');
    if (!input) return;
    const picker = input.closest('.bpl-picker');
    const query = input.value.trim();
    picker?.querySelectorAll('[data-picker-name]').forEach((button) => {
      button.hidden = Boolean(query) && !button.dataset.pickerName.includes(query);
    });
  }

  function onSubmit(event) {
    const form = event.target.closest('[data-bpl-lookup-form]');
    if (!form) return;
    event.preventDefault();
    const input = form.querySelector('[data-bpl-lookup-input]');
    state.lookupText = input?.value || '';
    const heroes = parseHeroes(state.lookupText);
    if (heroes.length) void loadLookup(heroes);
  }

  function bind(root) {
    root.addEventListener('change', onChange);
    root.addEventListener('click', onClick);
    root.addEventListener('input', onInput);
    root.addEventListener('submit', onSubmit);
    /* toggle 不冒泡；捕获阶段记下高级查询的展开状态，重绘后保持。 */
    root.addEventListener('toggle', (event) => {
      if (event.target.matches?.('.bpl-advanced')) state.lookupOpen = event.target.open;
      const picker = event.target.closest?.('[data-bpl-picker-details]');
      if (picker && event.target.open) {
        const key = picker.dataset.bplPickerDetails;
        state[`${key}PickerOpen`] = true;
      }
    }, true);
  }

  function planText(plan) {
    if (!plan?.available) return '当前没有可用的赛前方案。';
    const lines = [`BP 赛前方案：${plan.team || '本队'} vs ${plan.opponent || '对手'}`];
    if (plan.rule?.title) lines.push(`规则：${plan.rule.title}`);
    for (const text of plan.summary || []) lines.push(`- ${text}`);
    if (plan.threats?.length) {
      lines.push('', '对手最常用：');
      for (const row of plan.threats) lines.push(`- ${row.label}：${num(row.games)} 局，胜率 ${rate(row.winRate)}`);
    }
    if (plan.banPriority?.length) {
      lines.push('', 'Ban 优先级：');
      for (const row of plan.banPriority) lines.push(`- ${row.hero}：对手 ${num(row.oppPicks)} 次，本队对位胜率 ${rate(row.ourWinRate)}`);
    }
    if (plan.branches?.length) {
      lines.push('', '对手 Ban 后第一手：');
      for (const row of plan.branches) {
        const options = (row.options || []).map((item) => `${item.hero}（${num(item.count)} 次 / ${rate(item.winRate)}）`).join('、');
        lines.push(`- Ban ${row.ban}：${options || '样本不足'}`);
      }
    }
    if (plan.responses?.length) {
      lines.push('', '对手组合的应对：');
      for (const row of plan.responses) lines.push(`- ${row.opponentCombo}：本队 ${num(row.games)} 局，胜率 ${rate(row.ourWinRate)}`);
    }
    lines.push('', '口径：历史证据 + 规则提示，不是最优解；样本不足的分支必须待验证。');
    return lines.join('\n');
  }

  function mount(root) {
    if (!root) return;
    if (state.root === root) return;
    state.root = root;
    bind(root);
    void load();
  }

  function dispose() {
    state.controller?.abort();
    state.partController?.abort();
    state.diagnoseController?.abort();
    state.comboDetailController?.abort();
    state.observer?.disconnect();
    state.observer = null;
    state.root = null;
  }

  return {mount, dispose, rerender: paint};
}
