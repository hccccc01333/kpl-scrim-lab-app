/* 首页「今天先看这几件事」：工作台首页的决策入口（紧凑版）。
   设计目标：
   - 只占 3 行：每条 1 行标题 + 元信息，证据按需展开；首页不再堆 5 张大卡。
   - 真的会变：按当前工作台筛选（日期）请求 /api/decision/briefing，展示
     scope/fingerprint/评估数；换数据范围或补对局后重算，不是固定清单。
   - 行主入口走工作台网页端决策台（#decision/<tab>?game=...），完整四工作区在网页里直接看；
     保留一个「在赛训台看」小链接跳到桌面客户端的同一分析。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const BRIEFING_URL = API_BASE + '/api/decision/briefing';
const FETCH_TIMEOUT = 8000;
const ROW_LIMIT = 3;
const EVIDENCE_LIMIT = 6;

const SEVERITY = { high: ['高', '高优先级'], medium: ['中', '中优先级'], low: ['低', '低优先级'] };
const CONFIDENCE = { high: '高可信', medium: '中可信', low: '低可信' };
const KIND_LABEL = {
  fight_arrival: '团战执行', late_join: '团战执行', loss_pattern: '失利窗口',
  resource_mismatch: '资源分配', comeback_leak: '优势保持', slow_conversion: '优势保持',
  opening_habit: '开局习惯', coverage_gap: '采集覆盖',
};
const KIND_TAB = {
  comeback_leak: 'review', slow_conversion: 'review', loss_pattern: 'review',
  fight_arrival: 'review', late_join: 'review', resource_mismatch: 'player',
  opening_habit: 'prep',
};

export function createHomeDecision({ esc, fmt, time, icon, route }) {
  const state = { box: null, controller: null, expanded: false, scope: {} };

  const listOf = (value) => (Array.isArray(value) ? value : []);
  const number = (value) => typeof value === 'number' && Number.isFinite(value);
  const safeId = (value) => String(value ?? '').replace(/[^A-Za-z0-9_-]/g, '') || 'item';
  const tabFor = (kind) => (kind === 'coverage_gap' ? '' : KIND_TAB[kind] || 'review');
  const kindName = (item) => KIND_LABEL[item.kind] || item.analysis || '分析';
  const gameOf = (item) => listOf(item.evidence).find((entry) => entry && entry.game)?.game || '';
  const clientLink = (item) => {
    const tab = tabFor(item.kind);
    if (!tab) return '';
    const params = new URLSearchParams({ tab });
    const game = gameOf(item);
    if (game) params.set('game', String(game));
    return 'kpl-client://open?' + params.toString();
  };
  /* 工作台网页端决策台：主入口。带上 tab 页签 + 具体对局（有证据时）一起过去。 */
  const workbenchLink = (item) => {
    const tab = tabFor(item.kind) || 'review';
    const game = gameOf(item);
    return '#decision/' + tab + (game ? '?' + new URLSearchParams({ game: String(game) }).toString() : '');
  };

  function scopeText(briefing) {
    const scope = briefing?.scope || {};
    const parts = [];
    if (number(scope.games)) parts.push(`${fmt(scope.games)} 局有回放`);
    if (scope.dateFrom || scope.dateTo) {
      parts.push(`${scope.dateFrom || '起'} → ${scope.dateTo || '今'}`);
    }
    if (scope.result === 'loss') parts.push('只看失利');
    if (scope.opponent) parts.push(esc(scope.opponent));
    const evaluated = number(briefing?.evaluated) ? briefing.evaluated : null;
    const triggered = number(briefing?.triggered) ? briefing.triggered : null;
    const selected = number(briefing?.items?.length) ? briefing.items.length : 0;
    const selection = evaluated && triggered
      ? `共评估 ${evaluated} 类信号，命中 ${triggered} 条，按严重度显示前 ${selected} 条`
      : `按严重度显示前 ${selected} 条`;
    return (parts.length ? `当前范围：${parts.join(' · ')}。` : '当前范围：全部已关联回放。') + selection;
  }

  function evidenceList(item) {
    const evidence = listOf(item.evidence).filter((entry) => entry && typeof entry === 'object').slice(0, EVIDENCE_LIMIT);
    if (!evidence.length) return '<p class="hd-ev-empty">这一条没有可展开的对局证据，去看分析页的聚合依据。</p>';
    return `<ol class="hd-ev-list">${evidence.map((entry) => {
      const label = entry.label || entry.game || '对局';
      const game = entry.game
        ? `<a href="${esc(route('match', entry.game))}">${esc(label)}</a>`
        : `<span>${esc(label)}</span>`;
      const at = number(entry.t) && entry.t >= 0 ? `<small>${esc(time(entry.t))}</small>` : '';
      return `<li>${game}${at}<span>${esc(entry.text || '')}</span></li>`;
    }).join('')}</ol>`;
  }

  function row(item, index) {
    const sev = Object.hasOwn(SEVERITY, item.severity) ? item.severity : 'low';
    const confidence = Object.hasOwn(CONFIDENCE, item.confidence) ? item.confidence : 'medium';
    const samples = number(item.n) ? item.n : null;
    const lowSample = confidence === 'low' || !(samples >= 10);
    const client = clientLink(item);
    const workbench = workbenchLink(item);
    const anchor = 'hd-ev-' + safeId(item.id);
    const evidenceCount = listOf(item.evidence).length;
    return `<li class="hd-row" data-sev="${esc(sev)}" data-id="${esc(item.id || '')}">
      <span class="hd-no">${String(index + 1).padStart(2, '0')}</span>
      <div class="hd-row-main">
        <a class="hd-row-title" href="${esc(workbench)}" title="在工作台决策台打开这条分析">${esc(item.title || '未命名问题')}</a>
        <span class="hd-row-meta">
          <span class="hd-sev">${esc(SEVERITY[sev][0])}优先级</span>
          <span>${esc(kindName(item))}</span>
          <span>n=${samples === null ? '—' : fmt(samples)}</span>
          <span>${esc(CONFIDENCE[confidence])}</span>
          ${lowSample ? '<span class="hd-warn">样本不足</span>' : ''}
        </span>
      </div>
      <div class="hd-row-actions">
        ${evidenceCount ? `<button type="button" class="hd-btn" data-hd-evidence aria-expanded="false" aria-controls="${anchor}">证据 ×${evidenceCount}${icon('chevron')}</button>` : ''}
        <a class="hd-btn is-primary" href="${esc(workbench)}">查看分析${icon('arrow')}</a>
        ${client ? `<a class="hd-btn is-client" href="${esc(client)}" title="在桌面客户端看完整分析">在赛训台看${icon('arrow')}</a>` : ''}
      </div>
      <div class="hd-ev" id="${anchor}" hidden>
        ${item.detail ? `<p class="hd-ev-detail">${esc(item.detail)}</p>` : ''}
        ${evidenceList(item)}
        ${item.caveat ? `<p class="hd-ev-caveat">口径：${esc(item.caveat)}</p>` : ''}
      </div>
    </li>`;
  }

  function skippedBlock(briefing) {
    const skipped = listOf(briefing?.skipped).filter((entry) => entry && (entry.analysis || entry.reason));
    if (!skipped.length) return '';
    return `<details class="hd-skipped"><summary>还有 ${skipped.length} 项暂不出结论</summary>
      <ul>${skipped.map((entry) => `<li><b>${esc(entry.analysis || '分析')}</b>${esc(entry.reason || '数据不足')}</li>`).join('')}</ul>
    </details>`;
  }

  function section(briefing, body) {
    const fingerprint = briefing?.fingerprint ? `<span class="hd-fp" title="数据范围与入选条目生成的版本号">数据版本 ${esc(briefing.fingerprint)}</span>` : '';
    return `<section class="section hd-section" aria-labelledby="hd-title">
      <div class="hd-head">
        <div class="hd-head-copy">
          <span class="hd-kicker">TODAY · 自动生成</span>
          <h2 id="hd-title">今天先看这几件事</h2>
          <p class="hd-scope">${esc(scopeText(briefing))} ${fingerprint}</p>
        </div>
        <div class="hd-head-actions">
          <a class="hd-link" href="#decision">打开决策台${icon('arrow')}</a>
        </div>
      </div>
      ${body}
      <p class="hd-foot">问题由当前对局自动计算，换数据范围或补充回放后会重算；证据只陈述观察，不证明因果。</p>
    </section>`;
  }

  function emptyBody(kind) {
    return `<div class="hd-empty" role="status">
      <b>当前范围没有足够证据的问题</b>
      <span>${kind === 'error' ? '决策数据暂时读不到，稍后重试；首页其它内容不受影响。' : '放宽日期筛选、补关联回放，或多打几局后再看。'}</span>
      <button type="button" class="control" data-hd-retry>${icon('refresh')}重新读取</button>
    </div>`;
  }

  function render(briefing) {
    const items = listOf(briefing?.items).slice(0, ROW_LIMIT);
    if (!items.length) return section(briefing, emptyBody('empty'));
    return section(briefing, `<ol class="hd-list">${items.map(row).join('')}</ol>${skippedBlock(briefing)}`);
  }

  function alive(box, controller) {
    return state.box === box && box.isConnected && state.controller === controller;
  }

  function query(scope) {
    const params = new URLSearchParams({ limit: String(ROW_LIMIT) });
    if (scope?.from) params.set('from', scope.from);
    if (scope?.to) params.set('to', scope.to);
    return params.toString();
  }

  async function load(box, controller, scope) {
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
    let briefing = null;
    try {
      const response = await fetch(`${BRIEFING_URL}?${query(scope)}`, {
        signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`briefing ${response.status}`);
      briefing = await response.json();
    } catch (error) {
      clearTimeout(timer);
      if (!alive(box, controller)) return false;
      box.innerHTML = section(null, emptyBody('error'));
      box.setAttribute('aria-busy', 'false');
      return false;
    }
    clearTimeout(timer);
    if (!alive(box, controller)) return false;
    try {
      box.innerHTML = briefing?.available === false
        ? section(briefing, emptyBody('empty'))
        : render(briefing);
    } catch {
      box.innerHTML = section(null, emptyBody('error'));
    }
    box.setAttribute('aria-busy', 'false');
    return true;
  }

  function hydrate(box, scope = {}) {
    if (!box) return Promise.resolve(false);
    state.box = box;
    state.scope = scope;
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    box.classList.add('home-decision');
    box.setAttribute('aria-busy', 'true');
    box.innerHTML = section(null, '<div class="hd-loading">正在按当前数据范围筛选今天该看的问题…</div>');
    return load(box, controller, scope);
  }

  function setRowOpen(row, open) {
    const panel = row.querySelector('.hd-ev');
    const button = row.querySelector('[data-hd-evidence]');
    if (!panel) return;
    panel.hidden = !open;
    row.classList.toggle('is-open', open);
    if (button) {
      button.setAttribute('aria-expanded', String(open));
      const count = panel.querySelectorAll('.hd-ev-list li').length;
      button.innerHTML = (open ? '收起' : `证据 ×${count}`) + icon('chevron');
    }
  }

  function onClick(event) {
    const box = event.currentTarget;
    if (event.target.closest('[data-hd-retry]')) {
      event.preventDefault();
      hydrate(box, state.scope);
      return;
    }
    const toggle = event.target.closest('[data-hd-evidence]');
    if (toggle) {
      event.preventDefault();
      const row = toggle.closest('.hd-row');
      const willOpen = row?.querySelector('.hd-ev')?.hidden;
      box.querySelectorAll('.hd-row.is-open').forEach((other) => {
        if (other !== row) setRowOpen(other, false);
      });
      if (row) setRowOpen(row, Boolean(willOpen));
    }
  }

  function bind(box) {
    if (!box || box.dataset.hdBound === '1') return;
    box.dataset.hdBound = '1';
    box.addEventListener('click', onClick);
  }

  return { render, hydrate, bind };
}
