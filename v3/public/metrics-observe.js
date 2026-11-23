/* 本队选手指标观察 · 视图层（hash: #metrics-observe）
 *
 * 组件层第一个实例：默认单栏，可切两栏/三栏做对位排版；每栏对象可选
 * 本队 / 对手 / KPL 分路平均；指标与四档阈值取赛训组 grade-rules；
 * 筛选 BO × 赛事 × 类型 × 时间窗；趋势含巅峰分 / 段位 / 英雄战力（占位）。
 * 数据逻辑在 modules/metrics-engine.js，本文件只负责控件、渲染与事件。
 *
 * 外壳接线（由 app.js 负责）：
 *   import { createMetricsObservePage } from './metrics-observe.js';
 *   mods.metricsObserve = createMetricsObservePage({ esc, API_BASE, notify });
 *   // sections['metrics-observe'] = () => '<div data-mo-root></div>'
 *   // 切换路由时 mods.metricsObserve?.mount(document.querySelector('[data-mo-root]'))
 *   // 离开路由时 mods.metricsObserve?.dispose()
 *
 * 本文件同时导出顶层 render()，返回整页外壳 HTML，便于外壳直接插入后再 mount。
 */
import {
  createMetricsEngine, lineChartSvg,
  MAX_POINTS, BO_OPTIONS, TYPE_OPTIONS, WINDOW_OPTIONS, DEFAULT_FILTERS,
} from './modules/metrics-engine.js';
import { glyph, deco } from './ui-icons.js';

export const HASH = 'metrics-observe';

const defaultEsc = (v) => String(v ?? '').trim().replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const SOURCES = [['own', '本队选手'], ['opponent', '对手选手'], ['kpl', 'KPL 分路平均']];
const LANES = ['', '对抗路', '发育路', '中路', '打野·野核', '打野·坦野', '游走'];
const laneLabel = (lane) => (lane ? ({ '打野·野核': '打野 · 野核', '打野·坦野': '打野 · 坦野' }[lane] || lane) : '全部分路');
const sourceLabel = (source) => (SOURCES.find((s) => s[0] === source) || ['', '未知'])[1];
const MAX_SUBJECTS_PER_COL = 5;

/** 刷新图标：外层若提供 icon('refresh') 优先沿用；否则用套件的循环箭头（arrow-up 是趋势箭头，不用）。 */
function refreshGlyph(h = {}) {
  return (typeof h?.icon === 'function' && h.icon('refresh')) || glyph('refresh', { size: 14 });
}

/** 整页外壳；mount 会把它写进挂载点。 */
export function render(h = {}) {
  const uid = 'mo-' + Math.random().toString(36).slice(2, 9);
  const refreshIcon = refreshGlyph(h);
  return `<div class="mo-page" data-mo-page data-mo-uid="${uid}">
    <a class="visually-hidden mo-skip" href="#${uid}-results">跳到对比结果</a>
    <header class="mo-head">
      <div class="mo-head-top"><span class="mo-kicker">TRAINING · METRICS OBSERVE</span>
        <span class="mo-scope" data-mo-scope>赛训组指标口径</span></div>
      ${deco('divider-title')}
      <h1>本队选手指标观察</h1>
    </header>

    <section class="mo-panel mo-setup" aria-labelledby="${uid}-setup-title">
      <div class="mo-panel-head"><h2 id="${uid}-setup-title">${glyph('chart', { size: 16 })}观察设置</h2>
        <button type="button" class="control mo-refresh" data-mo-refresh>${refreshIcon}<span data-mo-refresh-label>刷新数据</span></button></div>
      <div class="mo-setup-grid">
        <fieldset class="mo-fs"><legend>排版</legend>
          <div class="mo-radios">
            <label><input type="radio" name="${uid}-cols" value="1" checked> 单栏</label>
            <label><input type="radio" name="${uid}-cols" value="2"> 两栏对位</label>
            <label><input type="radio" name="${uid}-cols" value="3"> 三栏对位</label>
          </div>
        </fieldset>
        <fieldset class="mo-fs"><legend>${glyph('compare', { size: 16 })} 对比方式</legend>
          <div class="mo-radios">
            <label><input type="radio" name="${uid}-mode" value="overlay" checked> 叠加曲线</label>
            <label><input type="radio" name="${uid}-mode" value="split"> 分栏对比</label>
          </div>
        </fieldset>
        <fieldset class="mo-fs mo-fs-filters"><legend>筛选与指标</legend>
          <div class="mo-fields">
            <div class="mo-field"><label for="${uid}-lane">分路</label>
              <select id="${uid}-lane" data-mo-lane>${LANES.map((l) => `<option value="${defaultEsc(l)}">${defaultEsc(laneLabel(l))}</option>`).join('')}</select></div>
            <div class="mo-field"><label for="${uid}-metric">趋势指标</label>
              <select id="${uid}-metric" data-mo-metric><option value="gpm">分均经济</option></select></div>
            <div class="mo-field"><label for="${uid}-bo">BO 赛制</label>
              <select id="${uid}-bo" data-mo-bo>${BO_OPTIONS.map(([v, l]) => `<option value="${defaultEsc(v)}">${defaultEsc(l)}</option>`).join('')}</select></div>
            <div class="mo-field"><label for="${uid}-comp">赛事</label>
              <select id="${uid}-comp" data-mo-comp><option value="">全部赛事</option></select></div>
            <div class="mo-field"><label for="${uid}-type">比赛类型</label>
              <select id="${uid}-type" data-mo-type>${TYPE_OPTIONS.map(([v, l]) => `<option value="${defaultEsc(v)}">${defaultEsc(l)}</option>`).join('')}</select></div>
            <div class="mo-field"><label for="${uid}-win">${glyph('calendar', { size: 13 })}时间窗</label>
              <select id="${uid}-win" data-mo-window>${WINDOW_OPTIONS.map(([v, l]) => `<option value="${defaultEsc(v)}">${defaultEsc(l)}</option>`).join('')}</select></div>
            <div class="mo-field" data-mo-custom hidden><label for="${uid}-from">${glyph('calendar', { size: 13 })}起始日期</label>
              <input id="${uid}-from" type="date" data-mo-from></div>
            <div class="mo-field" data-mo-custom hidden><label for="${uid}-to">${glyph('calendar', { size: 13 })}结束日期</label>
              <input id="${uid}-to" type="date" data-mo-to></div>
          </div>
        </fieldset>
      </div>
      <p class="mo-status" data-mo-status role="status" aria-live="polite">正在读取规则与选手名单…</p>
    </section>

    <section class="mo-panel" aria-labelledby="${uid}-slots-title">
      <div class="mo-panel-head"><h2 id="${uid}-slots-title">${glyph('compare', { size: 16 })}对比对象</h2>
        <p class="mo-hint">每栏可叠加多名选手（最多 ${MAX_SUBJECTS_PER_COL} 名）；换数据源会重置该栏。</p></div>
      <div class="mo-columns" data-mo-slots></div>
    </section>

    <div id="${uid}-results" tabindex="-1">
      <section class="mo-results" data-mo-results aria-busy="true">
        <div class="mo-empty">${glyph('refresh', { size: 20, cls: 'mo-spin' })}正在汇总指标…</div>
      </section>
    </div>
  </div>`;
}

/**
 * 创建页面控制器。h: { esc, API_BASE, notify }
 * 返回 { html, render, mount, dispose, rerender, state }
 */
export function createMetricsObservePage(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc : defaultEsc;
  const API_BASE = h.API_BASE || (() => {
    try { return new URL('..', import.meta.url).pathname.replace(/\/$/, ''); } catch { return '/v3'; }
  })();
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const engine = createMetricsEngine({ apiBase: API_BASE, esc });
  const uid = 'mo-' + Math.random().toString(36).slice(2, 9);

  const state = {
    cols: 1, mode: 'overlay', lane: '', metric: 'gpm',
    filters: { ...DEFAULT_FILTERS },
    slots: [{ source: 'own', picks: [] }, { source: 'kpl', picks: [] }, { source: 'opponent', picks: [] }],
    result: null, loading: false, error: '',
  };
  let root = null, bound = null, generation = 0, statusNode = null;

  /* ── 工具 ─────────────────────────────────────────────────────────── */
  const $ = (sel) => (root ? root.querySelector(sel) : null);
  const $$ = (sel) => (root ? [...root.querySelectorAll(sel)] : []);
  function announce(message, isError = false) {
    if (!statusNode || !statusNode.isConnected) return;
    statusNode.textContent = message;
    statusNode.classList.toggle('is-error', isError);
    if (notify) notify(message);
  }
  /** 刷新按钮的加载态：同步 disabled / aria-busy / 文案，避免重复点击。 */
  function setRefreshBusy(busy) {
    const btn = $('[data-mo-refresh]');
    if (!btn) return;
    btn.disabled = busy;
    btn.setAttribute('aria-busy', String(busy));
    const label = btn.querySelector('[data-mo-refresh-label]');
    if (label) label.textContent = busy ? '刷新中…' : '刷新数据';
  }
  function fmtVal(metric, value) {
    if (!isNum(value)) return '—';
    const unit = metric && metric.unit;
    let out;
    if (unit === '%') out = value.toFixed(1) + '%';
    else if ((metric && metric.key) === 'kda') out = value.toFixed(2);
    else if ((metric && metric.key) === 'rating') out = value.toFixed(1);
    else if (Math.abs(value) >= 100) out = Math.round(value).toLocaleString('zh-CN');
    else out = (Math.round(value * 10) / 10).toString();
    return out + (unit && unit !== '%' ? ` <small>${esc(unit)}</small>` : '');
  }
  function firstOf(source) {
    const list = engine.listSubjects({ source, lane: state.lane });
    return list[0] || null;
  }
  function subjects() {
    return state.slots.slice(0, state.cols).flatMap((slot) => slot.picks.map((p) => ({ ...p, __slot: state.slots.indexOf(slot) })));
  }
  function scopeText(includeLane = true) {
    const f = state.filters;
    const bits = includeLane ? [laneLabel(state.lane)] : [];
    if (f.bo) bits.push(f.bo);
    if (f.comp) {
      const comp = ((engine.sources && engine.sources.competitions) || []).find((c) => String(c.id) === String(f.comp));
      bits.push(comp ? comp.name : '指定赛事');
    }
    bits.push(f.type === 'training' ? '训练赛' : f.type === 'formal' ? '正式赛' : '全部类型');
    if (f.window === 'custom') bits.push(`${f.from || '—'} ~ ${f.to || '—'}`);
    else if (f.window !== 'all') bits.push((WINDOW_OPTIONS.find((o) => o[0] === f.window) || [])[1] || f.window);
    return bits.filter(Boolean).join(' · ');
  }

  /* ── 渲染：控件 ───────────────────────────────────────────────────── */
  function paintMetricOptions() {
    const sel = $('[data-mo-metric]');
    if (!sel) return;
    const all = engine.listMetrics(state.lane);
    const groups = [
      ['分路核心指标（赛训组规则）', all.core.filter((m) => m.fromRule)],
      ['逐局事实补充（未设阈值）', all.core.filter((m) => !m.fromRule)],
    ];
    const options = groups.filter(([, list]) => list.length).map(([label, list]) => `<optgroup label="${esc(label)}">${list.map((m) =>
      `<option value="${esc(m.key)}"${m.key === state.metric ? ' selected' : ''}>${esc(m.label)}${m.placeholder ? '（占位）' : ''}</option>`).join('')}</optgroup>`).join('');
    sel.innerHTML = options;
    if (!all.core.concat(all.attrs).some((m) => m.key === state.metric)) state.metric = all.core[0] ? all.core[0].key : 'gpm';
    sel.value = state.metric;
  }
  function paintCompetitions() {
    const sel = $('[data-mo-comp]');
    if (!sel) return;
    const comps = (engine.sources && engine.sources.competitions) || [];
    sel.innerHTML = `<option value="">全部赛事</option>` + comps.map((c) =>
      `<option value="${esc(c.id)}"${String(c.id) === String(state.filters.comp) ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  }
  function slotOptions(slot) {
    const list = engine.listSubjects({ source: slot.source, lane: state.lane });
    return list.slice(0, 60).map((p) => `<option value="${esc(p.name)}">${esc(p.name)} · ${esc(p.lane || '位置未知')} · ${Number(p.games) || 0} 局</option>`).join('');
  }
  function chipsHtml(slot, index) {
    if (!slot.picks.length) return '<li class="mo-chip is-empty">尚未选择对象，用上方下拉追加。</li>';
    return slot.picks.map((p) => `<li class="mo-chip is-${esc(p.source)}">
      <span>${esc(p.name)}</span><small>${esc(sourceLabel(p.source))}</small>
      <button type="button" data-mo-remove="${index}" data-mo-name="${esc(p.name)}" aria-label="从第 ${index + 1} 栏移除 ${esc(p.name)}">×</button>
    </li>`).join('');
  }
  function paintSlots() {
    const box = $('[data-mo-slots]');
    if (!box) return;
    box.dataset.cols = String(state.cols);
    box.innerHTML = state.slots.slice(0, state.cols).map((slot, i) => `<fieldset class="mo-slot" data-mo-slot="${i}">
      <legend>第 ${i + 1} 栏 · 对比对象 <span class="mo-slot-count">${slot.picks.length} 名</span></legend>
      <div class="mo-slot-controls">
        <div class="mo-field"><label for="${uid}-source-${i}">数据源</label>
          <select id="${uid}-source-${i}" data-mo-source="${i}">${SOURCES.map(([v, l]) =>
            `<option value="${v}"${slot.source === v ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
        <div class="mo-field"><label for="${uid}-pick-${i}">追加选手</label>
          <select id="${uid}-pick-${i}" data-mo-pick="${i}" aria-describedby="${uid}-pick-hint-${i}">
            <option value="">选择后加入本栏…</option>${slotOptions(slot)}</select>
          <span id="${uid}-pick-hint-${i}" class="visually-hidden">选中后加入本栏，可重复添加多名对象</span></div>
      </div>
      <ul class="mo-chips" data-mo-chips="${i}">${chipsHtml(slot, i)}</ul>
    </fieldset>`).join('');
  }
  function resetPicksForLane() {
    state.slots.slice(0, state.cols).forEach((slot) => {
      slot.picks = slot.picks.filter((p) => {
        const list = engine.listSubjects({ source: p.source, lane: state.lane });
        return list.some((x) => x.name === p.name);
      });
      if (!slot.picks.length) {
        const first = firstOf(slot.source);
        if (first) slot.picks = [first];
      }
    });
  }

  /* ── 渲染：结果 ───────────────────────────────────────────────────── */
  function tableHtml(table, capId) {
    // 属性字段还没有真实逐局样本，整张占位表不展示。
    if (table.placeholder) return '';
    // 没有任何可用样本的指标整行不显示；KPL 只输出能算的字段，其余字段不会出现在这张表里。
    const rows = (table.rows || []).filter((row) =>
      (row.cells || []).some((c) => (c.samples || 0) > 0 || isNum(c.value)));
    if (!rows.length) return '';
    const names = ((rows[0] && rows[0].cells) || []).map((c) => c.subject);
    return `<div class="mo-table-wrap" tabindex="0" role="region" aria-labelledby="${capId}">
      <table class="mo-table" style="--mo-c0:&quot;指标&quot;;${names.map((n, i) => `--mo-c${i + 1}:&quot;${esc(n)}&quot;`).join(';')}">
        <caption id="${capId}">${table.placeholder ? '属性趋势' : '分路核心指标 · 赛训组规则'}</caption>
        <thead><tr><th scope="col">指标</th>${names.map((n, i) => `<th scope="col"><span class="mo-swatch s${i % 6}" aria-hidden="true"></span>${esc(n)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map((row) => `<tr><th scope="row">${esc(row.label)}${row.unit ? ` <small>${esc(row.unit)}</small>` : ''}</th>
          ${row.cells.map((c, i) => `<td><b class="mo-val ${i ? `s${i % 6}` : ''}">${c.display ? esc(c.display) : fmtVal(row, c.value)}</b>
            <span class="mo-grade is-${esc(c.grade.level)}">${esc(c.grade.label)}</span>
            <small class="mo-samples">${c.samples ? `${c.samples} 局` : ''}</small></td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>`;
  }
  function chartHtml(list, metric, index) {
    const series = list.map((s, i) => ({ name: s.subject.name, cls: `s${(index + i) % 6}`, pts: s.points }));
    // 无数据点时只输出空态，不再渲染图注 / 图例（否则会出现「没有数据」却仍讲达标线的矛盾）
    if (!series.some((s) => (s.pts || []).length)) {
      const msg = list.every((s) => s.baseline) ? 'KPL 分路平均没有逐局趋势，指标见下方表格。' : '当前筛选没有可画的数据点。';
      return `<div class="mo-empty">${glyph('chart', { size: 20 })}${esc(msg)}</div>`;
    }
    const rule = metric && metric.fromRule && metric.thresholds.length >= 3 ? { v: Number(metric.thresholds[2]), label: '达标线' } : null;
    const svg = lineChartSvg(series, {
      esc, ref: rule,
      title: `${metric ? metric.label : '指标'}趋势 · ${scopeText()}${list.some((s) => s.placeholder) ? '（含占位属性）' : ''}`,
      desc: series.map((s) => {
        const pts = s.pts || []; const last = pts[pts.length - 1];
        const note = list.find((x) => x.subject.name === s.name);
        return `${s.name}：${pts.length} 点${note && note.placeholder ? '（占位数据）' : ''}，末值 ${last ? last.y : '无'}`;
      }).join('；'),
    });
    return `<figure class="mo-figure">
      ${svg}
      <figcaption>${esc(metric ? metric.label : '指标')}随时间变化 · ${esc(scopeText())}
        ${rule ? ' · 金色虚线为赛训组达标线' : ''}${list.some((s) => s.placeholder) ? ' · 含属性占位数据' : ''}
        · 每条曲线最多 ${MAX_POINTS} 点（等距抽样）</figcaption>
      <ul class="mo-legend">${series.map((s, i) => `<li><span class="mo-swatch ${s.cls}" aria-hidden="true"></span>${esc(s.name)}</li>`).join('')}</ul>
    </figure>`;
  }
  function paintResults() {
    const box = $('[data-mo-results]');
    if (!box || !state.result) return;
    const r = state.result;
    const metric = r.metric || engine.findMetric(r.effectiveLane, state.metric) || { key: state.metric, label: state.metric };
    const figs = [];
    const hasPoints = (r.series || []).some((s) => (s.points || []).length);
    if (hasPoints) {
      if (state.mode === 'split') {
        for (let i = 0; i < state.cols; i++) {
          const list = r.series.filter((s) => s.subject.__slot === i);
          if (list.length) figs.push(`<div class="mo-fig-head"><h3>第 ${i + 1} 栏 · ${esc(list.map((s) => s.subject.name).join(' / '))}</h3></div>${chartHtml(list, metric, i * 2)}`);
        }
      } else {
        figs.push(chartHtml(r.series, metric, 0));
      }
    }
    const capBase = `${uid}-core-cap`;
    box.innerHTML = `<div class="mo-result-head"><h2>${deco('section-triangle')}指标对比结果</h2>
        <p>规则主体：${esc(r.ruleSubject || '未取到赛训组规则')} · 生效分路：${esc(laneLabel(r.effectiveLane))} · ${esc(scopeText(false))}</p></div>
      <div class="mo-figures">${figs.length ? figs.join('') : `<div class="mo-empty">${glyph('chart', { size: 20 })}${r.series.every((s) => s.baseline) ? 'KPL 分路平均没有逐局趋势，指标见下方表格。' : '当前筛选没有可画的数据点。'}</div>`}</div>
      <div class="mo-tables">
        ${tableHtml({ rows: r.coreTable }, capBase)}
        ${tableHtml({ rows: r.attrTable, placeholder: true }, `${uid}-attr-cap`)}
      </div>`;
    box.setAttribute('aria-busy', 'false');
  }

  /* ── 取数 ─────────────────────────────────────────────────────────── */
  async function refresh({ silent = false } = {}) {
    const gen = ++generation;
    state.loading = true;
    const box = $('[data-mo-results]');
    if (box) box.setAttribute('aria-busy', 'true');
    if (!silent) announce('正在重算指标与曲线…');
    try {
      const list = subjects();
      if (!list.length) throw new Error('还没有选择对比对象。');
      const result = await engine.buildComparison({ subjects: list, metricKey: state.metric, filters: state.filters,
        lane: state.lane, mode: state.mode });
      if (gen !== generation || !root) return;
      result.metric = engine.findMetric(result.effectiveLane, state.metric) || { key: state.metric, label: state.metric, unit: '' };
      result.series.forEach((s) => { s.subject.__slot = s.subject.__slot ?? list.find((x) => x.name === s.subject.name)?.__slot ?? 0; });
      state.result = result;
      state.error = '';
      paintResults();
      const n = Object.values(result.samples).reduce((a, b) => a + b, 0);
      announce(`已更新：${list.length} 名对象 · ${n} 局样本 · 指标「${result.metric.label}」`);
    } catch (error) {
      if (gen !== generation || !root) return;
      state.error = error.message || '数据读取失败';
      announce(`读取失败：${state.error}`, true);
      if (box) { box.setAttribute('aria-busy', 'false'); box.innerHTML = `<div class="mo-empty is-error">${glyph('warning', { size: 20 })}${esc(state.error)}。请检查服务后点「刷新数据」。</div>`; }
    } finally {
      if (gen === generation) state.loading = false;
    }
  }
  async function load() {
    announce('正在读取规则与选手名单…');
    try {
      await engine.loadSources();
      if (!root) return;
      paintCompetitions();
      if (!state.lane) {
        const own = engine.listSubjects({ source: 'own' })[0];
        state.lane = own && own.lane ? own.lane : '中路';
        const sel = $('[data-mo-lane]'); if (sel) sel.value = state.lane;
      }
      paintMetricOptions();
      resetPicksForLane();
      paintSlots();
      await refresh({ silent: true });
    } catch (error) {
      announce(`初始化失败：${error.message || '未知错误'}`, true);
      const box = $('[data-mo-results]');
      if (box) box.innerHTML = `<div class="mo-empty is-error">${glyph('warning', { size: 20 })}${esc(error.message || '数据读取失败')}</div>`;
    }
  }

  /* ── 事件 ─────────────────────────────────────────────────────────── */
  function onClick(event) {
    const t = event.target;
    if (t.closest('[data-mo-refresh]')) {
      setRefreshBusy(true);
      engine.invalidate();
      load().finally(() => setRefreshBusy(false));
      return;
    }
    const rm = t.closest('[data-mo-remove]');
    if (rm) {
      const i = Number(rm.dataset.moRemove);
      const name = rm.dataset.moName;
      state.slots[i].picks = state.slots[i].picks.filter((p) => p.name !== name);
      const box = $(`[data-mo-chips="${i}"]`);
      if (box) box.innerHTML = chipsHtml(state.slots[i], i);
      announce(`已从本栏移除 ${name}`);
      refresh({ silent: true });
    }
  }
  function onChange(event) {
    const t = event.target;
    if (!root || !t.dataset) return;
    if (t.name === `${uid}-cols`) {
      state.cols = Number(t.value) || 1;
      resetPicksForLane(); paintSlots(); paintResults();
      announce(`已切换为${state.cols}栏对位排版`);
      return;
    }
    if (t.name === `${uid}-mode`) {
      state.mode = t.value === 'split' ? 'split' : 'overlay';
      paintResults();
      announce(state.mode === 'split' ? '已切换为分栏对比' : '已切换为叠加曲线');
      return;
    }
    if (t.hasAttribute('data-mo-lane')) {
      state.lane = t.value;
      paintMetricOptions(); resetPicksForLane(); paintSlots(); refresh();
      return;
    }
    if (t.hasAttribute('data-mo-metric')) { state.metric = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-bo')) { state.filters.bo = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-comp')) { state.filters.comp = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-type')) { state.filters.type = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-window')) {
      state.filters.window = t.value;
      $$('[data-mo-custom]').forEach((el) => { el.hidden = t.value !== 'custom'; });
      refresh(); return;
    }
    if (t.hasAttribute('data-mo-from')) { state.filters.from = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-to')) { state.filters.to = t.value; refresh(); return; }
    if (t.hasAttribute('data-mo-source')) {
      const i = Number(t.dataset.moSource);
      state.slots[i].source = t.value;
      const first = firstOf(t.value);
      state.slots[i].picks = first ? [first] : [];
      paintSlots(); refresh();
      return;
    }
    if (t.hasAttribute('data-mo-pick')) {
      const i = Number(t.dataset.moPick);
      const name = t.value;
      if (!name) return;
      const picked = engine.listSubjects({ source: state.slots[i].source, lane: state.lane }).find((p) => p.name === name);
      if (picked && !state.slots[i].picks.some((p) => p.name === picked.name)) {
        if (state.slots[i].picks.length >= MAX_SUBJECTS_PER_COL) { announce(`本栏最多 ${MAX_SUBJECTS_PER_COL} 名对象。`, true); t.value = ''; return; }
        state.slots[i].picks.push(picked);
        const box = $(`[data-mo-chips="${i}"]`);
        if (box) box.innerHTML = chipsHtml(state.slots[i], i);
        announce(`已将 ${picked.name} 加入第 ${i + 1} 栏`);
        refresh({ silent: true });
      }
      t.value = '';
    }
  }
  function bind(node) {
    if (bound === node) return;
    if (bound) dispose();
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('change', onChange);
  }
  function dispose() {
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('change', onChange);
      bound = null;
    }
    generation++;
    root = null; statusNode = null;
  }
  function mount(node) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    root.innerHTML = render(h);
    statusNode = $('[data-mo-status]');
    bind(root);
    load();
  }
  function rerender() { if (state.result) paintResults(); }

  return { html: render, render, mount, bind, dispose, rerender, state, engine };
}

export default createMetricsObservePage;
