/* 「数据源展示」页：赛事 → 战队池/选手池/对局池 的后端数据图谱与 ID 关联体检。
 *
 * 自取数模块，外壳接线（app.js）：
 *   OWN_MODULE_ROUTES 加 'sources'；ensureModules 里 importOnce('./datasource-page.js?v=...')；
 *   load() 早退；renderers.sources = () => '<div data-ds-root></div>'；
 *   render() 里 mount/dispose(document.querySelector('[data-ds-root]'))。
 * CSS 由 index.html 的 datasource.css?v=... 引入。
 *
 * 数据来自 GET /api/studio/workspace/data-map?competition=<id>，只读。
 */
import { glyph } from './ui-icons.js';

const DEFAULT_API_BASE = (() => {
  try { return new URL('..', import.meta.url).pathname.replace(/\/$/, ''); } catch { return ''; }
})();
const _pair = (v) => String(v ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const fmt = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('zh-CN') : '—';
const LEVEL = {
  error: { label: '断链', cls: 'is-error' },
  warn: { label: '提醒', cls: 'is-warn' },
  info: { label: '说明', cls: 'is-info' },
};
const POOL_ICON = {
  teams: 'teams', players: 'players', matches: 'matches', series: 'seriesbuilder',
  clusters: 'opponents',
};
const POOL_HINT = {
  teams: '战队主数据 · teams',
  players: '选手主数据 · players',
  matches: '对局记录 · match_records',
  series: '系列赛 · training_series',
  clusters: '营地聚类 · team_clusters',
};

export function createDataSourcePage(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc : _pair;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;

  let root = null;
  let controller = null;
  let generation = 0;
  let bound = false;
  let payload = null;
  let selected = '';
  let loading = false;
  let failed = '';
  let relPool = '';
  let relEntity = '';
  let relKind = '';
  let relState = '';
  let nodeDrag = null;
  /* 池子轮播的状态：索引只跟随用户切换 / 滚动，不作为独立数据源。 */
  let poolIndex = 0;
  let carouselRaf = 0;
  let carouselSettle = 0;
  let carouselPending = -1;
  let carouselSettled = -1;

  /* 训练课池对读图没有帮助，还会把视图越拉越长，从数据图里拿掉。 */
  const HIDDEN_POOLS = new Set(['sessions']);
  function activePools() {
    return (payload?.pools || []).filter((p) => !HIDDEN_POOLS.has(p.key));
  }

  function competitionKey() {
    try { return localStorage.getItem('training-current-competition') || ''; } catch { return ''; }
  }

  async function api(path) {
    const response = await fetch(API_BASE + '/api/' + path, {
      cache: 'no-store', signal: controller?.signal, headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `读取失败（${response.status}）`);
    }
    return response.json();
  }

  function setNotice(text, error = false) {
    const node = root?.querySelector('[data-ds-notice]');
    if (!node) return;
    node.hidden = !text;
    node.className = 'ds-notice' + (error ? ' is-error' : '');
    node.textContent = text || '';
  }

  function announce(text) {
    const status = root?.querySelector('[data-ds-status]');
    if (status) status.textContent = text;
    if (text && notify) notify(text);
  }

  async function load() {
    if (!root) return;
    const token = ++generation;
    controller?.abort();
    controller = new AbortController();
    loading = true;
    failed = '';
    paintBusy();
    setNotice('');
    try {
      const query = selected ? `?competition=${encodeURIComponent(selected)}` : '';
      const value = await api('studio/workspace/data-map' + query);
      if (token !== generation || !root?.isConnected) return;
      if (!value.ok) throw new Error('接口返回异常');
      payload = value;
      selected = value.competitionId || selected;
      loading = false;
      paint();
      announce(`已读取 ${fmt(value.summary?.scopedRows || 0)} 条范围内记录，${value.summary?.errors || 0} 处断链、${value.summary?.warnings || 0} 处提醒`);
    } catch (error) {
      if (error?.name === 'AbortError' || token !== generation) return;
      loading = false;
      failed = error?.message || '读取失败';
      paintBusy();
      setNotice(failed + '。请确认工作台服务正在运行，然后点「重新读取」。', true);
      announce('数据源展示读取失败');
    }
  }

  function html() {
    return `<div class="ds-page">
      <header class="page-intro ds-page-intro"><div><h1>数据源展示</h1><p>按赛事查看数据表、关联线路和 ID 断链；空池与断链分开显示。</p></div><div class="intro-actions"><button type="button" class="control" data-ds-refresh>${glyph('refresh', { size: 18 })}重新读取</button></div></header>
      <section class="section ds-head" aria-label="数据源概况">
        <div class="ds-controls">
          <label class="ds-pick"><span>当前赛事</span>
            <select data-ds-comp aria-label="选择赛事"><option value="">读取中…</option></select></label>
          <span class="ds-updated" data-ds-updated></span>
        </div>
        <p class="ds-notice" data-ds-notice role="alert" hidden></p>
        <p class="visually-hidden" role="status" data-ds-status></p>
        <div class="ds-summary" data-ds-summary></div>
      </section>
      <div data-ds-body></div>
    </div>`;
  }

  function paintBusy() {
    const body = root?.querySelector('[data-ds-body]');
    if (!body) return;
    body.innerHTML = loading
      ? '<div class="ds-loading"><span class="ds-spin"></span>正在读取赛事数据图谱…</div>'
      : failed ? `<div class="ds-loading is-failed">读取失败：${esc(failed)}</div>` : '';
  }

  function summaryHtml(s = {}) {
    const cells = [
      ['数据表', fmt(s.tableCount), '张表已登记', 'neutral'],
      ['范围内记录', fmt(s.scopedRows), `全库 ${fmt(s.rowTotal)} 条`, 'neutral'],
      ['断链', fmt(s.errors), s.errors ? '有 ID 对不上' : '未发现', s.errors ? 'bad' : 'good'],
      ['提醒', fmt(s.warnings), s.warnings ? '需要确认' : '一切正常', s.warnings ? 'warn' : 'good'],
    ];
    return cells.map(([label, value, note, tone]) => `<div class="ds-stat is-${tone}">
      <span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('');
  }

  /* 池子里的每一行都是可折叠的原生 details：默认收起，几千条也只是几千行摘要。
     同一个池子共用一个 name，一次只展开一行，视图始终紧凑。 */
  function itemRows(pool) {
    const items = pool.items || [];
    if (!items.length) return '<div class="ds-item-empty">这个池子还是空的</div>';
    const group = `ds-items-${esc(pool.key)}`;
    return items.map((item) => `<details class="ds-item" name="${group}">
      <summary>
        <span class="ds-item-name" title="${esc(item.id)}">${esc(item.label)}</span>
        <code title="${esc(item.id)}">${esc(String(item.id).slice(0, 14))}</code>
        ${(item.badges || []).map((b) => `<em class="ds-badge">${esc(b)}</em>`).join('')}
        <i class="ds-item-caret" aria-hidden="true"></i>
      </summary>
      <div class="ds-item-body">
        ${item.detail ? `<p>${esc(item.detail)}</p>` : ''}
        <span>完整 ID</span><code class="ds-item-id">${esc(item.id)}</code>
      </div>
    </details>`).join('');
  }

  function poolSlide(pool, index, total) {
    const broken = pool.key === 'teams'
      ? payload?.issues?.some((x) => x.level === 'error' && /战队/.test(x.title))
      : pool.key === 'players'
        ? payload?.issues?.some((x) => x.level === 'error' && /选手/.test(x.title))
        : false;
    const state = broken ? 'is-broken' : (pool.scoped ? 'is-live' : 'is-idle');
    const label = broken ? '有断链' : (pool.scoped ? '线路正常' : '赛事未声明');
    return `<article class="ds-pool ${state}" role="group" aria-roledescription="slide"
        aria-label="第 ${index + 1} 张，共 ${total} 张：${esc(pool.label)}" data-ds-pool="${esc(pool.key)}" data-ds-slide="${index}">
      <div class="ds-pool-head">
        <span class="ds-pool-icon">${icon(POOL_ICON[pool.key] || 'sources') || '◈'}</span>
        <div><b>${esc(pool.label)}</b><small>${esc(POOL_HINT[pool.key] || pool.table || '')}</small></div>
        <em class="ds-pool-state">${esc(label)}</em>
      </div>
      <div class="ds-pool-count"><strong>${fmt(pool.scoped)}</strong><span>范围内 / 全库 ${fmt(pool.total)}</span></div>
      <p class="ds-pool-note">${esc(pool.note || '')}</p>
      <div class="ds-item-list">${itemRows(pool)}</div>
    </article>`;
  }

  function graphHtml() {
    const comp = payload.competition || { name: '未选择赛事', status: '', date: '' };
    const pools = activePools();
    const total = pools.length;
    const markers = pools.map((p, i) => `<button type="button" data-ds-marker="${i}"
      aria-label="查看${esc(p.label)}"${i === poolIndex ? ' aria-current="true"' : ''}>${esc(p.label)}</button>`).join('');
    return `<section class="section ds-graph-section">
      <div class="section-heading"><div><h2>赛事数据图</h2>
        </div></div>
      <div class="ds-graph">
        <div class="ds-root-row">
          <article class="ds-event-card ${comp.status === 'planned' ? 'is-planned' : ''}">
            <span class="ds-event-kicker">赛事 · COMPETITION</span>
            <h3>${esc(comp.name)}</h3>
            <div class="ds-event-meta"><span class="ds-event-id" title="${esc(comp.id)}">赛事 ID · ${esc(String(comp.id || '').slice(0, 12))}${String(comp.id || '').length > 12 ? '…' : ''}</span>
              ${comp.status ? `<em>${esc({ planned: '计划中', active: '进行中', finished: '已结束', archived: '已归档' }[comp.status] || comp.status)}</em>` : ''}${comp.date ? `<span>${esc(comp.date)}</span>` : ''}</div>
            <div class="ds-event-numbers">
              <span><b>${fmt(comp.declaredTeams)}</b>声明战队</span>
              <span><b>${fmt(comp.declaredPlayers)}</b>声明选手</span>
              <span><b>${fmt(comp.declaredMatches)}</b>关键局</span>
              <span><b>${fmt(comp.scopedMatches)}</b>范围内局</span>
            </div>
          </article>
        </div>
        <div class="ds-split" aria-hidden="true"></div>
        <section class="ds-carousel" aria-roledescription="carousel" aria-label="数据池">
          <div class="ds-carousel-bar">
            <button type="button" class="ds-carousel-arrow" data-ds-prev aria-label="上一个数据池">‹</button>
            <div class="ds-carousel-markers" role="group" aria-label="选择数据池">${markers}</div>
            <button type="button" class="ds-carousel-arrow" data-ds-next aria-label="下一个数据池">›</button>
          </div>
          <div class="ds-carousel-track" tabindex="0" role="group" aria-label="数据池卡片">
            ${pools.map((p, i) => poolSlide(p, i, total)).join('') || '<div class="ds-carousel-empty">没有可展示的数据池</div>'}
          </div>
          <p class="ds-visually-hidden" role="status" aria-live="polite" data-ds-carousel-status></p>
        </section>
      </div>
      <div class="ds-legend">
        <span><i class="is-live"></i>线路正常</span>
        <span><i class="is-idle"></i>赛事没声明 / 暂无数据</span>
        <span><i class="is-broken"></i>ID 对不上</span>
        <span class="ds-legend-note">聚类与战队是两套 ID，靠合并链和别名对接</span>
      </div>
    </section>`;
  }

  function edgesHtml() {
    const rows = payload.edges || [];
    return `<section class="section ds-section">
      <div class="section-heading"><div><h2>关联线路</h2>
        <p>${glyph('warning', { size: 18 })}空池子标「空」不算断链。</p></div></div>
      <div class="ds-edge-list">${rows.map((e) => {
        const state = e.empty ? 'empty' : (e.weak && !e.ok ? 'weak' : (e.ok ? 'ok' : 'broken'));
        const text = { ok: '通', empty: '空', weak: '文本', broken: '断' }[state];
        return `<div class="ds-edge is-${state}">
        <span class="ds-edge-kind">${esc(e.kind === 'reverse' ? '反向归属' : e.kind === 'declared' ? '赛事声明' : e.kind === 'relation' ? '关系表' : e.kind === 'text' ? '文本解析' : 'ID 引用')}</span>
        <b>${esc(e.source)}</b><span class="ds-edge-arrow">→</span><b>${esc(e.target)}</b>
        <span class="ds-edge-label">${esc(e.label)}</span>
        ${e.field ? `<code>${esc(e.field)}</code>` : ''}
        <em>${esc(e.detail || '')}</em>
        <span class="ds-edge-state">${text}</span>
      </div>`; }).join('') || '<div class="ds-empty">没有可展示的关联。</div>'}</div>
    </section>`;
  }

  function relEntities() {
    const all = payload?.entityLinks || [];
    return all.filter((item) => !relPool || item.pool === relPool);
  }

  function relOptions(list, value, label) {
    return `<option value="">${esc(label)}</option>` + list.map((item) =>
      `<option value="${esc(item.value)}"${item.value === value ? ' selected' : ''}>${esc(item.label)}</option>`).join('');
  }

  function relayTableHtml() {
    const pool = (payload?.pools || []).find((p) => p.key === relPool);
    const rows = (payload?.relationships || []).filter((r) => {
      if (relKind && r.kind !== relKind) return false;
      if (relState && r.state !== relState) return false;
      if (pool && r.from.table !== pool.table && r.to.table !== pool.table) return false;
      return true;
    });
    const stateText = { linked: '已连上', broken: '对不上', empty: '暂无数据' };
    return `<div class="ds-table-wrap" data-ds-rel-table-wrap tabindex="0" role="region" aria-label="字段关系连线表">
      <table class="ds-table ds-rel-table">
        <caption class="ds-visually-hidden">字段之间的关系连线</caption>
        <thead><tr>
          <th scope="col">关系</th><th scope="col">起点字段</th><th scope="col">基数</th>
          <th scope="col">终点字段</th><th scope="col">匹配值</th><th scope="col">状态</th>
        </tr></thead>
        <tbody>${rows.map((r) => `<tr class="is-${esc(r.state)}">
          <td>${esc(r.label)}</td>
          <td><code>${esc(r.from.label)}.${esc(r.from.column)}</code></td>
          <td><b class="ds-card-arrow">${esc(r.cardinality)} →</b></td>
          <td><code>${esc(r.to.label)}.${esc(r.to.column)}</code></td>
          <td>${fmt(r.count)} <small>／ ${fmt(r.fromRows)} → ${fmt(r.toRows)}</small></td>
          <td><em class="ds-rel-state is-${esc(r.state)}">${esc(stateText[r.state] || r.state)}</em></td>
        </tr>`).join('') || '<tr><td colspan="6" class="ds-empty">没有符合条件的关系。</td></tr>'}</tbody>
      </table>
    </div>`;
  }

  const PLAIN_OUT = {
    '战队 → 队下选手': '它带了这些选手',
    '战队名 → 系列赛文本对手': '系列赛里用名字记着它',
    '战队简称 → 系列赛对手': '系列赛里用简称记着它',
    '旧名别名 → 系列赛对手': '系列赛里还留着它的旧名字',
    '战队 → 系列赛指定对手': '这些系列赛把它设成了对手',
    '战队 → 对局对手': '这些对局里它是对手',
    '战队 → 对局本队': '这些对局里它是本队',
    '战队 → 旧 ID 映射': '系统里它还有这些旧编号',
    '聚类合并目标 → 战队': '这些营地聚类并到了它',
    '选手 → 10 人阵容里的位置': '它出现在这些对局的十人名单里',
    '选手 → 游戏账号': '它对应这些游戏账号',
    '选手 → 营地昵称映射': '它对应这些营地昵称',
    '营地昵称 → 选手主数据': '这些营地昵称认出了它',
    '阵容里的选手 ID → 选手池': '十人名单里的编号认出了它',
    '阵容里的战队 ID → 战队池': '阵容里的战队编号认出了它',
    '选手 → 所属战队': '它属于这些战队',
    '对局 → 阵容里的 10 个名字': '这局的十人名单来自',
    '对局 → 系列赛关系': '这局归到这些系列赛',
    '对局 → 系列赛': '这局属于这些系列赛',
    '对局 → 赛事': '这局属于这些赛事',
    '系列赛 → 包含的对局': '这个系列赛包含这些对局',
    '系列赛 → 赛事': '这个系列赛属于这些赛事',
    '系列赛 → 战队': '这个系列赛的对手是这些战队',
    '系列赛 → 训练课': '这个系列赛排在这些训练课里',
    '训练课 → 赛事': '这节训练课属于这些赛事',
    '本队资料 → 战队池': '本队资料对应的战队是',
    '本队选手档案 → 选手池': '本队档案对应的选手是',
    '档案游戏 ID → 选手账号': '档案里的游戏编号对应的选手是',
  };
  const PLAIN_IN = {
    '战队 → 队下选手': '这些选手归它管',
    '选手 → 所属战队': '这些战队下面有它',
    '战队名 → 系列赛文本对手': '这些系列赛记着它',
    '战队 → 对局对手': '这些对局把它当对手',
    '战队 → 对局本队': '这些对局把它当本队',
    '选手 → 10 人阵容里的位置': '这些对局的十人名单里有它',
    '对局 → 系列赛': '这些系列赛包含它',
    '系列赛 → 赛事': '这些赛事包含它',
    '本队选手档案 → 选手池': '档案里记着这些人',
  };

  const FRIENDLY_TABLE = {
    '对局记录': '场对局', '比赛阵容': '条十人名单', '对局十人阵容': '条十人名单', '系列赛': '个系列赛',
    '选手主数据': '名选手', '战队主数据': '支战队', '营地昵称': '个昵称', '赛事': '个赛事',
  };
  const looksLikeId = (v) => /^[a-z][a-z0-9]*-[\w-]{6,}$/i.test(String(v || ''));

  function plainPhrase(entity, link) {
    const out = link.direction === 'out';
    const label = link.label;
    const pool = entity.pool;
    if (pool === 'teams') {
      if (!out && label === '选手 → 所属战队') return '这些选手属于它';
      if (!out && label === '阵容里的战队 ID → 战队池') return '这些对局的十人名单里有它';
      if (!out && label === '战队名 → 系列赛文本对手') return '这些系列赛用名字记着它';
      if (!out && label === '战队 → 对局对手') return '这些对局把它当对手';
      if (!out && label === '战队 → 对局本队') return '这些对局把它当本队';
      if (!out && label === '本队资料 → 战队池') return '本队资料指的就是它';
    }
    if (pool === 'players') {
      if (!out && label === '战队 → 队下选手') return '这些战队带了它';
      if (!out && label === '选手 → 10 人阵容里的位置') return '这些对局的十人名单里有它';
      if (!out && label === '本队选手档案 → 选手池') return '本队档案里记着它';
    }
    if (pool === 'matches') {
      if (out && label === '对局 → 阵容里的 10 个名字') return '这局的十人名单里是';
      if (out && label === '对局 → 系列赛') return '这局属于';
    }
    if (pool === 'series') {
      if (out && label === '系列赛 → 包含的对局') return '这个系列赛包含';
    }
    return out
      ? (PLAIN_OUT[label] || '它关联到')
      : (PLAIN_IN[label] || '这些数据也指向它');
  }

  function relayDetailHtml(entity) {
    if (!entity) return '<div class="ds-empty">选一个实体，看它具体连到了谁。</div>';
    const links = entity.links || [];
    const subject = entity.label;
    if (!links.length) return `<div class="ds-empty">「${esc(subject)}」暂时没有连到其他数据。</div>`;
    return `<div class="ds-rel-entity-head"><b>${esc(subject)}</b><span>共 ${fmt(links.length)} 种联系</span></div>
      <ul class="ds-rel-links ds-rel-links-plain">${links.map((link) => {
        const peers = (link.peers || []).map((p) => p.label);
        const parts = String(link.via || '').split('→');
        const sourceTable = parts[0]?.trim().split('.')[0] || '';
        const targetTable = parts[1]?.trim().split('.')[0] || '';
        const unit = FRIENDLY_TABLE[link.direction === 'out' ? targetTable : sourceTable] || '条记录';
        const names = peers.length && peers.every(looksLikeId)
          ? `${fmt(peers.length)} ${unit}`
          : (peers.slice(0, 6).join('、') || '暂时没有具体记录');
        const extra = peers.length > 6 && !peers.every(looksLikeId) ? ` 等 ${fmt(peers.length)} 个` : '';
        return `<li><p>${esc(subject)} ${esc(plainPhrase(entity, link))}：<b>${esc(names)}</b>${esc(extra)}。</p></li>`;
      }).join('')}</ul>`;
  }

  function relationshipHtml() {
    const pools = payload?.pools || [];
    const entities = relEntities();
    if (relEntity && !entities.some((item) => item.id === relEntity)) relEntity = '';
    const entity = entities.find((item) => item.id === relEntity) || null;
    return `<section class="section ds-section ds-rel-section">
      <div class="section-heading"><div><h2>关系模型视图</h2></div></div>
      <div class="ds-rel-filters">
        <label><span>实体类型</span>
          <select data-ds-rel-pool aria-label="按实体类型筛选">${relOptions(pools.map((p) => ({ value: p.key, label: p.label })), relPool, '全部池子')}</select></label>
        <label><span>具体实体</span>
          <select data-ds-rel-entity aria-label="按具体实体筛选">${relOptions(entities.map((e) => ({ value: e.id, label: `${e.poolLabel} · ${e.label}` })), relEntity, '全部实体')}</select></label>
        <label><span>连线类型</span>
          <select data-ds-rel-kind aria-label="按连线类型筛选">${relOptions([{ value: 'ID', label: 'ID 引用' }, { value: '文本', label: '文本匹配' }], relKind, '全部类型')}</select></label>
        <label><span>状态</span>
          <select data-ds-rel-state aria-label="按状态筛选">${relOptions([{ value: 'linked', label: '已连上' }, { value: 'broken', label: '对不上' }, { value: 'empty', label: '暂无数据' }], relState, '全部状态')}</select></label>
        <button type="button" class="control" data-ds-rel-reset>${glyph('refresh', { size: 18 })}重新整理</button>
      </div>
      <p class="visually-hidden" role="status" data-ds-canvas-status></p>
      <div data-ds-rel-body>${relayBodyHtml(entity)}</div>
    </section>`;
  }

  function focusLinks(entity) {
    return (entity?.links || []).filter((link) => {
      if (relKind && link.kind !== relKind) return false;
      if (relState && relState !== 'linked' && link.peers?.length) return false;
      return true;
    });
  }

  function pickPanelHtml() {
    const entities = relEntities();
    const groups = new Map();
    entities.forEach((item) => {
      if (!groups.has(item.poolLabel)) groups.set(item.poolLabel, []);
      groups.get(item.poolLabel).push(item);
    });
    if (!groups.size) return '<div class="ds-empty">当前筛选下没有可选择的实体。</div>';
    return `<div class="ds-pick-panel"><h3>${glyph('compare', { size: 18 })}选一个实体，画布自动整理</h3>
      ${[...groups].map(([label, list]) => `<section class="ds-pick-group">
        <h4>${esc(label)} <small>${fmt(list.length)}</small></h4>
        <div class="ds-pick-chips">${list.slice(0, 14).map((item) =>
          `<button type="button" data-ds-pick-entity="${esc(item.id)}" data-ds-pick-pool="${esc(item.pool)}">${esc(item.label)}</button>`).join('')}
          ${list.length > 14 ? `<small>还有 ${fmt(list.length - 14)} 个，用上方「具体实体」下拉选</small>` : ''}</div>
      </section>`).join('')}
    </div>`;
  }

  function focusCanvasHtml(entity) {
    const links = focusLinks(entity);
    const step = 150;
    const height = Math.max(280, links.length * step + 40);
    const anchorTop = Math.max(24, Math.round((height - 118) / 2));
    const nodes = links.map((link, i) => `<article class="ds-focus-node" data-node="${i}" style="left:430px;top:${24 + i * step}px">
      <div class="ds-focus-node-top">
        <button type="button" class="ds-node-handle" data-ds-node-handle aria-label="拖动这张关系卡片，聚焦后可用方向键移动">⠿</button>
        <span class="ds-rel-dir">${link.direction === 'out' ? '出线' : '入线'}</span>
        <b>${esc(link.label)}</b><em>${esc(link.cardinality)}</em>
      </div>
      <p class="ds-focus-via">${esc(link.via)}</p>
      <p class="ds-focus-value">连接值 <code>${esc(link.value)}</code></p>
      <div class="ds-rel-peers">${(link.peers || []).map((p) =>
        `<span title="${esc(p.id)}">${esc(p.label)}</span>`).join('') || '<small>没有连到的记录</small>'}
        ${link.total > (link.peers || []).length ? `<small>还有 ${fmt(link.total - link.peers.length)} 条</small>` : ''}</div>
    </article>`).join('');
    return `<div class="ds-canvas-wrap" data-ds-canvas-wrap tabindex="0" role="region" aria-label="单个实体的关系画布，可滚动查看">
      <div class="ds-canvas ds-canvas-focus" data-ds-canvas data-focus-root style="width:900px;height:${height}px">
        <svg class="ds-lines" data-ds-lines aria-hidden="true">
          <defs><marker id="ds-arrow-ok" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1a7359"/></marker></defs>
          <g data-ds-line-group></g>
        </svg>
        <article class="ds-focus-anchor" data-anchor style="left:40px;top:${anchorTop}px">
          <span>当前实体</span><b>${esc(entity.label)}</b>
          <code>${esc(entity.id)}</code><small>${esc(entity.poolLabel)} · ${fmt(links.length)} 条关系</small>
        </article>
        ${nodes}
      </div>
    </div>`;
  }

  function relayBodyHtml(entity) {
    return `<div class="ds-rel-layout">
      <div class="ds-rel-map">
        ${entity ? focusCanvasHtml(entity) : pickPanelHtml()}
        <details class="ds-rel-list"><summary>展开字段连线清单</summary>${relayTableHtml()}</details>
      </div>
      <aside class="ds-rel-detail"><h3>实体下钻</h3>${relayDetailHtml(entity)}</aside>
    </div>`;
  }

  function nodePoint(node, side) {
    const canvas = root?.querySelector('[data-ds-canvas]');
    if (!canvas || !node) return null;
    const base = canvas.getBoundingClientRect();
    const rect = node.getBoundingClientRect();
    return {
      x: (side === 'right' ? rect.right : rect.left) - base.left,
      y: rect.top + rect.height / 2 - base.top,
    };
  }

  function drawLines() {
    const canvas = root?.querySelector('[data-ds-canvas]');
    const group = root?.querySelector('[data-ds-line-group]');
    if (!canvas || !group) return;
    const anchor = canvas.querySelector('[data-anchor]');
    const nodes = canvas.querySelectorAll('[data-node]');
    if (!anchor) return;
    const a = nodePoint(anchor, 'right');
    const anchorRect = anchor.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    const anchorTop = anchorRect.top - canvasRect.top;
    group.innerHTML = [...nodes].map((node, i) => {
      const b = nodePoint(node, 'left');
      if (!a || !b) return '';
      const from = {
        x: a.x,
        y: anchorTop + anchorRect.height * ((i + 0.5) / nodes.length),
      };
      const path = `M ${from.x} ${from.y} C ${from.x + 70} ${from.y}, ${b.x - 70} ${b.y}, ${b.x} ${b.y}`;
      const mx = (from.x + b.x) / 2;
      const my = (from.y + b.y) / 2 - 6;
      const label = node.querySelector('em')?.textContent || '';
      return `<g class="ds-line is-linked is-focus" data-line="${i}">
        <path d="${path}" marker-end="url(#ds-arrow-ok)"/>
        <text x="${mx}" y="${my}" text-anchor="middle">${esc(label)}</text>
      </g>`;
    }).join('');
  }

  function paintRelationships() {
    if (!root || !payload) return;
    const host = root.querySelector('[data-ds-rel-body]');
    if (!host) return;
    const entities = relEntities();
    if (relEntity && !entities.some((item) => item.id === relEntity)) relEntity = '';
    host.innerHTML = relayBodyHtml(entities.find((item) => item.id === relEntity) || null);
    const entitySelect = root.querySelector('[data-ds-rel-entity]');
    if (entitySelect) {
      entitySelect.innerHTML = relOptions(entities.map((e) => ({ value: e.id, label: `${e.poolLabel} · ${e.label}` })), relEntity, '全部实体');
    }
    requestAnimationFrame(drawLines);
  }

  function resetCanvas() {
    paintRelationships();
    const wrap = root?.querySelector('[data-ds-canvas-wrap]');
    if (wrap) wrap.scrollTop = 0;
    const status = root?.querySelector('[data-ds-canvas-status]');
    if (status) status.textContent = '已按当前实体重新整理关系图';
  }

  function commitNodeMove(card, dx, dy) {
    const canvas = root?.querySelector('[data-ds-canvas]');
    if (!canvas || !card) return;
    const left = Math.max(0, Math.min((parseFloat(card.style.left) || 0) + dx, canvas.offsetWidth - card.offsetWidth));
    const top = Math.max(0, Math.min((parseFloat(card.style.top) || 0) + dy, canvas.offsetHeight - card.offsetHeight));
    card.style.left = left + 'px';
    card.style.top = top + 'px';
    card.style.transform = '';
    drawLines();
  }

  function issuesHtml() {
    const items = payload.issues || [];
    const blocks = ['error', 'warn', 'info'].map((level) => {
      const list = items.filter((x) => x.level === level);
      if (!list.length) return '';
      const meta = LEVEL[level];
      return `<div class="ds-issue-group ${meta.cls}">
        <h3><span>${meta.label}</span><b>${fmt(list.length)}</b></h3>
        ${list.map((item) => `<article class="ds-issue">
          <div class="ds-issue-head"><b>${esc(item.title)}</b><em>${esc(item.code)}</em><span>×${fmt(item.count)}</span></div>
          <p>${esc(item.detail)}</p>
          ${item.field ? `<code class="ds-issue-field">${esc(item.field)}</code>` : ''}
          ${(item.samples || []).length ? `<div class="ds-samples">${item.samples.map((s) => `<code>${esc(s)}</code>`).join('')}</div>` : ''}
        </article>`).join('')}
      </div>`;
    }).join('');
    return `<section class="section ds-section">
      <div class="section-heading"><div><h2>问题清单</h2>
        </div></div>
      ${blocks || '<div class="ds-empty">没有发现问题，后端关联是干净的。</div>'}
    </section>`;
  }

  function tablesHtml() {
    const rows = payload.tables || [];
    return `<section class="section ds-section">
      <div class="section-heading"><div><h2>数据库表清单</h2>
        <p>全库 ${fmt(rows.length)} 张表；「范围内」一列只算当前赛事相关的数据。</p></div></div>
      <details class="ds-table-details">
        <summary>展开全部 ${fmt(rows.length)} 张表（含字段与行数）</summary>
        <div class="ds-table-wrap"><table class="ds-table">
          <thead><tr><th>表</th><th>说明</th><th>主键</th><th>全库行数</th><th>范围内</th><th>字段</th></tr></thead>
          <tbody>${rows.map((t) => `<tr class="${t.scopedRows ? 'is-scoped' : ''}">
            <td><code>${esc(t.name)}</code></td><td>${esc(t.label)}</td>
            <td><code>${esc(t.key || '—')}</code></td>
            <td>${fmt(t.rows)}</td><td><b>${fmt(t.scopedRows)}</b></td>
            <td><span class="ds-cols" title="${esc((t.cols || []).join(', '))}">${esc((t.cols || []).slice(0, 5).join(' · '))}${(t.cols || []).length > 5 ? ' …' : ''}</span></td>
          </tr>`).join('')}</tbody>
        </table></div>
      </details>
    </section>`;
  }

  /* ── 池子轮播：原生横向滚动 + scroll-snap，按钮 / 标记只是辅助 ── */
  function carouselTrack() {
    return root?.querySelector('.ds-carousel-track') || null;
  }
  function slideSteps() {
    const track = carouselTrack();
    if (!track) return [];
    const slides = [...track.querySelectorAll('.ds-pool')];
    const base = slides[0]?.offsetLeft || 0;
    return slides.map((slide) => slide.offsetLeft - base);
  }
  function nearestSlide() {
    const track = carouselTrack(), steps = slideSteps();
    if (!track || !steps.length) return 0;
    const x = track.scrollLeft;
    let best = 0, bestDistance = Infinity;
    steps.forEach((step, i) => {
      const distance = Math.abs(step - x);
      if (distance < bestDistance) { bestDistance = distance; best = i; }
    });
    return best;
  }
  function setMarker(index) {
    if (!root) return;
    const markers = [...root.querySelectorAll('[data-ds-marker]')];
    markers.forEach((marker, i) => {
      if (i === index) marker.setAttribute('aria-current', 'true');
      else marker.removeAttribute('aria-current');
    });
    const prev = root.querySelector('[data-ds-prev]');
    const next = root.querySelector('[data-ds-next]');
    if (prev) prev.disabled = index <= 0;
    if (next) next.disabled = index >= markers.length - 1;
    /* 按钮变禁用后焦点不能丢，转给另一个按钮。 */
    if (prev?.disabled && document.activeElement === prev) next?.focus();
    if (next?.disabled && document.activeElement === next) prev?.focus();
  }
  function onCarouselSettled() {
    const index = nearestSlide();
    carouselPending = -1;
    if (index === carouselSettled) return;
    carouselSettled = index;
    setMarker(index);
    const status = root?.querySelector('[data-ds-carousel-status]');
    const total = root?.querySelectorAll('[data-ds-marker]').length || 0;
    if (status) status.textContent = total ? `第 ${index + 1} 张，共 ${total} 张` : '';
  }
  function goToSlide(index, smooth = true) {
    const track = carouselTrack(), steps = slideSteps();
    if (!track || !steps.length) return;
    const next = Math.max(0, Math.min(steps.length - 1, index));
    carouselPending = next;
    setMarker(next); // 用户一决定就更新标记，不等滚动动画结束
    if (Math.abs(track.scrollLeft - steps[next]) < 1) {
      carouselPending = -1;
      onCarouselSettled();
      return;
    }
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    track.scrollTo({ left: steps[next], behavior: smooth && !reduce ? 'smooth' : 'auto' });
  }

  function paint() {
    if (!root || !payload) return;
    const select = root.querySelector('[data-ds-comp]');
    if (select) {
      const options = (payload.competitions || []).map((c) =>
        `<option value="${esc(c.id)}"${c.id === payload.competitionId ? ' selected' : ''}>${esc(c.name)}${c.status ? ` · ${esc(c.status)}` : ''}</option>`);
      select.innerHTML = options.length ? options.join('') : '<option value="">还没有赛事</option>';
    }
    const updated = root.querySelector('[data-ds-updated]');
    if (updated) updated.textContent = payload.generatedAt ? `快照 ${payload.generatedAt}` : '';
    const summary = root.querySelector('[data-ds-summary]');
    if (summary) summary.innerHTML = summaryHtml(payload.summary);
    const body = root.querySelector('[data-ds-body]');
    if (body) {
      body.innerHTML = graphHtml() + edgesHtml() + relationshipHtml() + issuesHtml() + tablesHtml();
      /* 重画后把滚动位置恢复到当前池子，标记 / 按钮状态跟真实位置对齐。 */
      poolIndex = Math.max(0, Math.min(poolIndex, Math.max(0, activePools().length - 1)));
      const track = carouselTrack();
      if (track && poolIndex > 0) {
        const steps = slideSteps();
        if (steps[poolIndex] != null) track.scrollTo({ left: steps[poolIndex], behavior: 'instant' });
      }
      carouselPending = -1;
      carouselSettled = nearestSlide();
      setMarker(carouselSettled);
      requestAnimationFrame(drawLines);
    }
  }

  function bind(node) {
    if (!node || bound) return;
    bound = true;
    node.addEventListener('change', (event) => {
      const select = event.target.closest('[data-ds-comp]');
      if (select) {
        selected = select.value;
        try {
          if (selected) localStorage.setItem('training-current-competition', selected);
        } catch { /* 隐私模式下不写也可以看图 */ }
        load();
        return;
      }
      const rel = event.target.closest('[data-ds-rel-pool],[data-ds-rel-entity],[data-ds-rel-kind],[data-ds-rel-state]');
      if (rel) {
        if (rel.matches('[data-ds-rel-pool]')) { relPool = rel.value; relEntity = ''; }
        if (rel.matches('[data-ds-rel-entity]')) relEntity = rel.value;
        if (rel.matches('[data-ds-rel-kind]')) relKind = rel.value;
        if (rel.matches('[data-ds-rel-state]')) relState = rel.value;
        paintRelationships();
        return;
      }
    });
    /* scroll 不冒泡，用捕获阶段监听轨道；脚本驱动的滚动期间不回写标记。 */
    node.addEventListener('scroll', (event) => {
      const track = event.target;
      if (!track?.matches?.('.ds-carousel-track')) return;
      /* scrollend 尚未普及：没有时用防抖的 scroll 兜底，每次滚动都顺延。 */
      if (!('onscrollend' in window)) {
        clearTimeout(carouselSettle);
        carouselSettle = setTimeout(onCarouselSettled, 160);
      }
      if (carouselPending >= 0 || carouselRaf) return;
      carouselRaf = requestAnimationFrame(() => {
        carouselRaf = 0;
        setMarker(nearestSlide());
      });
    }, true);
    node.addEventListener('scrollend', (event) => {
      if (event.target?.matches?.('.ds-carousel-track')) onCarouselSettled();
    }, true);

    node.addEventListener('click', (event) => {
      if (event.target.closest('[data-ds-refresh]')) {
        event.preventDefault();
        load();
      }
      const prev = event.target.closest('[data-ds-prev]');
      if (prev) {
        event.preventDefault();
        const at = nearestSlide();
        if (at > 0) { poolIndex = at - 1; goToSlide(poolIndex); }
        return;
      }
      const next = event.target.closest('[data-ds-next]');
      if (next) {
        event.preventDefault();
        const at = nearestSlide();
        const total = root.querySelectorAll('[data-ds-marker]').length;
        if (at < total - 1) { poolIndex = at + 1; goToSlide(poolIndex); }
        return;
      }
      const marker = event.target.closest('[data-ds-marker]');
      if (marker) {
        event.preventDefault();
        poolIndex = Number(marker.dataset.dsMarker) || 0;
        goToSlide(poolIndex);
        return;
      }
      if (event.target.closest('[data-ds-rel-reset]')) {
        event.preventDefault();
        resetCanvas();
      }
      const pick = event.target.closest('[data-ds-pick-entity]');
      if (pick) {
        event.preventDefault();
        relEntity = pick.dataset.dsPickEntity || '';
        const select = root.querySelector('[data-ds-rel-entity]');
        if (select) select.value = relEntity;
        paintRelationships();
        const wrap = root.querySelector('[data-ds-canvas-wrap]');
        if (wrap) wrap.scrollTop = 0;
      }
    });
    node.addEventListener('pointerdown', (event) => {
      const handle = event.target.closest('[data-ds-node-handle]');
      if (!handle || event.button !== 0) return;
      const card = handle.closest('.ds-focus-node');
      if (!card) return;
      nodeDrag = {
        handle, card, pointerId: event.pointerId,
        startX: event.clientX, startY: event.clientY,
        left: parseFloat(card.style.left) || 0, top: parseFloat(card.style.top) || 0,
        dx: 0, dy: 0, moved: false,
      };
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    node.addEventListener('pointermove', (event) => {
      if (!nodeDrag || event.pointerId !== nodeDrag.pointerId) return;
      nodeDrag.dx = event.clientX - nodeDrag.startX;
      nodeDrag.dy = event.clientY - nodeDrag.startY;
      if (Math.abs(nodeDrag.dx) + Math.abs(nodeDrag.dy) < 4 && !nodeDrag.moved) return;
      nodeDrag.moved = true;
      nodeDrag.handle.classList.add('is-dragging');
      nodeDrag.card.style.transform = `translate(${nodeDrag.dx}px, ${nodeDrag.dy}px)`;
      drawLines();
    });
    function endNodeDrag(event) {
      if (!nodeDrag || (event && event.pointerId !== nodeDrag.pointerId)) return;
      const { card, handle, dx, dy, moved } = nodeDrag;
      handle.classList.remove('is-dragging');
      if (handle.hasPointerCapture?.(nodeDrag.pointerId)) handle.releasePointerCapture(nodeDrag.pointerId);
      nodeDrag = null;
      if (moved) commitNodeMove(card, dx, dy);
    }
    node.addEventListener('pointerup', endNodeDrag);
    node.addEventListener('pointercancel', endNodeDrag);
    node.addEventListener('lostpointercapture', endNodeDrag);
    node.addEventListener('keydown', (event) => {
      const handle = event.target.closest('[data-ds-node-handle]');
      if (!handle) return;
      const step = event.shiftKey ? 40 : 15;
      const offsets = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      const delta = offsets[event.key];
      if (!delta) return;
      event.preventDefault();
      commitNodeMove(handle.closest('.ds-focus-node'), delta[0], delta[1]);
    });
    node.addEventListener('route:repainted', paint);
  }

  function mount(node) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    if (!root.innerHTML.trim()) root.innerHTML = html();
    if (!selected) selected = competitionKey();
    bound = false;
    bind(root);
    load();
  }

  function dispose() {
    controller?.abort();
    controller = null;
    generation += 1;
    nodeDrag = null;
    clearTimeout(carouselSettle);
    if (carouselRaf) cancelAnimationFrame(carouselRaf);
    carouselRaf = 0;
    carouselPending = -1;
    carouselSettled = -1;
    root = null;
    bound = false;
  }

  return {
    html, render: html, mount, bind, dispose, rerender: paint, load,
    state: {
      get payload() { return payload; },
      get competitionId() { return payload?.competitionId || selected; },
    },
  };
}
