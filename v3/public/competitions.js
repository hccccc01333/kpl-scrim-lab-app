/* 赛事（比赛）列表 · 编辑 · 归档与双时间口径（2026-11）
 *
 * 赛训以赛事为中心：先在这里选择一场赛事，之后对局/战队/选手/英雄/BP 才可用。
 * 当前赛事存 localStorage['training-current-competition']，外壳据此做导航门控。
 *
 * 2026-11-22 合并：原「比赛与训练计划」页（#plan）并入本页 —— 比赛与本页赛事本就是
 * 同一份 studio/workspace/competitions 数据；训练赛排期（schedules）改为本页区块，
 * #plan 旧链接由外壳重定向到 #competitions。原训练负荷/目标达成看板随 2026-11-22
 * 反馈下线（连同 dashboard 请求一起移除）。
 *
 * 双时间口径（docs/重构蓝图_白金画廊交互.md §3.5.3）：
 * - 训练赛训练时间窗 date~end_date，按【训练日期 date】落入训练起始~结束（不是 recorded_date）；
 * - 正式比赛范围 formal_from~formal_to，与训练时间独立；
 * - 归属在查询时计算，改赛事时间后自动重算，不写死在对局上；
 * - 试训对局 in_trial 由后端排除；key_match_keys 手动挂载作为补充。
 * - 赛事与「训练赛/正式赛」是独立维度，分别展示、互不合并。
 *
 * 数据来自 /api/studio/workspace/competitions*（GET/POST/DELETE）与
 * /api/studio/workspace/schedules（GET/POST）、/api/v3/vocab。
 * 外壳给挂载点：<div data-comp-root></div>
 */

import { glyph, plus } from './ui-icons.js';

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const STORAGE_KEY = 'training-current-competition';

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const defaultEsc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
const fmt = (value, digits = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
};
const pct = (value, digits = 0) => (Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}%` : '—');
const localDate = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const weekdayOf = (date) => {
  if (!date) return '';
  const d = new Date(`${date}T00:00:00`);
  return Number.isNaN(d.getTime()) ? '' : ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
};

export function createCompetitionsPage(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc : defaultEsc;
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;
  let root = null;
  let bound = null;
  let controller = null;
  let archiveController = null;
  let generation = 0;
  let competitions = [];
  let teams = [];
  let schedules = [];      // 训练赛排期（原 #plan 页数据，2026-11-22 并入本页）
  let vocab = null;        // 赛训词表（训练组 / 赛制 / 规则 / 版本候选）
  let schedLoadFailed = false;
  let schedLoaded = false;
  let loading = false;
  let notice = '';
  let error = false;
  // 归档面板：训练赛 / 正式赛按赛事查；未归档区始终展示。
  let archive = { id: '', training: [], formal: [], unfiled: [], loading: false };
  let excluded = [];  // 拉错被排除的对局，保留记录以便撤销
  let dialog = null;
  let editingId = '';
  let editingScheduleId = '';
  let pendingDeleteId = '';
  let assignNotice = { msg: '', error: false };
  let carouselRaf = 0;

  const STATUS = { planned: '备赛中', training: '训练中', ongoing: '比赛中', completed: '已结束', cancelled: '已取消' };
  const SCHED_STATUS = { planned: '计划中', confirmed: '已确认', completed: '已完成', cancelled: '已取消' };
  const VOCAB_KINDS = { session: 'sessions', format: 'formats', rules: 'rules', version: 'versions' };
  const CURRENT_KEY = STORAGE_KEY;

  function currentId() {
    try { return localStorage.getItem(CURRENT_KEY) || ''; } catch { return ''; }
  }
  function setCurrentId(id) {
    try { id ? localStorage.setItem(CURRENT_KEY, id) : localStorage.removeItem(CURRENT_KEY); } catch {}
    document.dispatchEvent(new CustomEvent('competition:selected', { detail: { id, competitions } }));
  }
  function announce(msg) { if (notify) notify(msg); }
  function setNotice(msg, isError = false) {
    notice = String(msg || ''); error = Boolean(isError); paintNotice();
    if (notice) announce(notice);
  }
  function paintNotice() {
    const node = root?.querySelector('[data-comp-notice]');
    if (!node) return;
    // 图标 + 文案双通道：错误态不只靠红色传达；文案先转义，避免注入。
    node.innerHTML = `${error ? glyph('warning', { size: 14, cls: 'comp-notice-icon' }) : ''}${esc(notice)}`;
    node.classList.toggle('is-error', error);
    node.setAttribute('role', error ? 'alert' : 'status');
    node.setAttribute('aria-live', error ? 'assertive' : 'polite');
    node.hidden = !notice;
  }
  function setWarning(msg) {
    const node = dialog?.querySelector('[data-comp-warning]');
    if (!node) return;
    // 图标 + 文案双通道，不只靠颜色；图标 aria-hidden，可访问名仍由文字承担。
    node.innerHTML = msg ? `${glyph('warning', { size: 14 })}${esc(msg)}` : '';
    node.hidden = !msg;
  }
  /* 补挂结果贴在表格旁而非页顶：表格在页面底部，页顶提示用户根本看不到。 */
  function setAssignNotice(msg, isError = false) {
    assignNotice = { msg: String(msg || ''), error: Boolean(isError) };
    paintArchive();
    if (assignNotice.msg) {
      root?.querySelector('[data-comp-assign-notice]')?.scrollIntoView({ block: 'nearest' });
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(API_BASE + '/api/' + path, {
      cache: 'no-store', ...options,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
      signal: options.signal || controller?.signal,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `请求失败（${response.status}）`);
    }
    return response.json();
  }

  async function load(fresh = false) {
    if (!root) return;
    const myGen = ++generation;
    loading = true; paint();
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    try {
      const [comp, team] = await Promise.all([
        api('studio/workspace/competitions', { signal }),
        api('studio/workspace/teams', { signal }),
      ]);
      if (myGen !== generation || !root) return;
      competitions = Array.isArray(comp.competitions) ? comp.competitions : [];
      teams = Array.isArray(team.teams) ? team.teams : [];
      // 当前赛事 / 归档赛事若已被删除，清掉选中态
      const cur = currentId();
      if (cur && !competitions.some((c) => c.id === cur)) setCurrentId('');
      if (archive.id && !competitions.some((c) => c.id === archive.id)) archive.id = '';
      paint();
      refreshArchive();
    } catch (e) {
      if (e.name !== 'AbortError') setNotice(e.message || '赛事读取失败。', true);
    } finally {
      loading = false;
      if (myGen === generation) paint();
    }
    /* 软依赖：排期 / 词表任一失败不拖垮赛事主体，各自降级为空态。
       （训练负荷/目标达成看板已按反馈整块下线，不再请求 dashboard。） */
    try {
      const [sched, vb] = await Promise.all([
        api('studio/workspace/schedules', { signal }).catch(() => null),
        api('v3/vocab', { signal }).catch(() => null),
      ]);
      if (myGen !== generation || !root) return;
      schedLoadFailed = !sched;
      schedules = Array.isArray(sched?.schedules) ? sched.schedules : [];
      vocab = vb && typeof vb === 'object' ? vb : null;
      schedLoaded = true;
      paintVocab();
    } catch {
      if (myGen !== generation || !root) return;
      schedLoadFailed = true;
      schedules = [];
      schedLoaded = true;
    }
    paintSchedules();
  }

  async function refreshArchive() {
    if (!root) return;
    const myGen = generation;
    archive.loading = true; paintArchive();
    archiveController?.abort();
    archiveController = new AbortController();
    const signal = archiveController.signal;
    const paths = ['studio/workspace/competitions/unfiled-matches', 'studio/workspace/matches/excluded'];
    for (const comp of competitions) {
      const id = encodeURIComponent(comp.id);
      paths.push(`studio/workspace/competitions/${id}/training-matches`,
                 `studio/workspace/competitions/${id}/formal-matches`);
    }
    try {
      const results = await Promise.all(paths.map((path) => api(path, { signal })));
      if (myGen !== generation || !root) return;
      archive.unfiled = Array.isArray(results[0]?.matches) ? results[0].matches : [];
      excluded = Array.isArray(results[1]?.matches) ? results[1].matches : [];
      archive.training = [];
      archive.formal = [];
      const seen = new Set();
      competitions.forEach((comp, i) => {
        const training = Array.isArray(results[2 + i * 2]?.matches) ? results[2 + i * 2].matches : [];
        const formal = Array.isArray(results[3 + i * 2]?.matches) ? results[3 + i * 2].matches : [];
        training.forEach((row) => {
          const key = String(row.match_key ?? '');
          if (seen.has(key)) return;
          seen.add(key);
          archive.training.push({ ...row, competitionId: comp.id, competitionName: comp.name });
        });
        formal.forEach((row) => archive.formal.push({ ...row, competitionId: comp.id, competitionName: comp.name }));
      });
    } catch (e) {
      if (e.name !== 'AbortError') setNotice(e.message || '归档读取失败。', true);
    } finally {
      archive.loading = false;
      if (myGen === generation) paintArchive();
    }
  }

  function teamName(id) {
    return teams.find((t) => t.id === id)?.name || id || '—';
  }
  function rangeText(from, to) {
    if (!from) return '日期待定';
    return to && to !== from ? `${from} → ${to}` : from;
  }
  function collectRange(c) {
    return rangeText(c.date, c.end_date || c.date);
  }
  function formalRange(c) {
    return c.formal_from ? rangeText(c.formal_from, c.formal_to || c.formal_from) : '未设置';
  }
  function fmtRange(c) {
    return `训练 ${collectRange(c)} · 正式 ${formalRange(c)}`;
  }

  function card(c, index, total) {
    const cur = currentId() === c.id;
    const status = STATUS[c.status] || c.status || '备赛中';
    const indexLabel = String(index + 1).padStart(2, '0');
    return `<article class="comp-card${cur ? ' is-current' : ''}" data-comp-card="${esc(c.id)}"
      role="group" aria-roledescription="slide" aria-label="${index + 1} / ${total} · ${esc(c.name)}"
      data-marker-name="${esc(c.name)}">
      <span class="comp-card-index" aria-hidden="true">${indexLabel}</span>
      <header class="comp-card-head">
        <h3>${esc(c.name)}</h3>
        <span class="comp-status is-${esc(c.status || 'planned')}"><i class="comp-status-dot" aria-hidden="true"></i>${esc(status)}</span>
        ${cur ? '<span class="comp-current-badge">当前赛事</span>' : ''}
      </header>
      <div class="comp-card-when">
        <span class="comp-card-when-label">训练时间</span>
        <b>${esc(collectRange(c))}</b>
        <small>此区间内的训练赛会自动归档到本赛事</small>
      </div>
      <footer class="comp-card-actions">
        <button type="button" class="${cur ? 'control comp-selected' : 'primary comp-gold'}" data-comp-select="${esc(c.id)}" ${cur ? 'disabled' : ''}>
          ${cur ? glyph('shield', { size: 13 }) : ''}${cur ? '已选中' : '设为当前'}
        </button>
        <span class="comp-card-tools">
          <button type="button" class="control" data-comp-edit="${esc(c.id)}" aria-label="编辑赛事 ${esc(c.name)}">${glyph('edit', { size: 13 })}编辑</button>
          <button type="button" class="control comp-del" data-comp-delete="${esc(c.id)}" aria-label="删除赛事 ${esc(c.name)}">${glyph('trash', { size: 13 })}删除</button>
        </span>
      </footer>
    </article>`;
  }

  /* 赛事卡片横向轮播：原生滚动 + snap，控件只负责发起滚动与状态播报。 */
  function trackCards() {
    return [...(root?.querySelectorAll('[data-comp-track] [data-comp-card]') || [])];
  }
  function nearestCardIndex() {
    const track = root?.querySelector('[data-comp-track]');
    if (!track) return 0;
    const center = track.scrollLeft + track.clientWidth / 2;
    let best = 0, distance = Infinity;
    trackCards().forEach((card, index) => {
      const gap = Math.abs(card.offsetLeft + card.offsetWidth / 2 - center);
      if (gap < distance) { distance = gap; best = index; }
    });
    return best;
  }
  function setCarouselStatus(index) {
    const cards = trackCards();
    if (!cards.length) return;
    const status = root?.querySelector('[data-comp-carousel-status]');
    if (status) {
      status.textContent = `第 ${index + 1} / ${cards.length} 个赛事 · ${cards[index].dataset.markerName || ''}`;
      status.hidden = false;
    }
    root?.querySelectorAll('[data-comp-marker]').forEach((button, i) => {
      if (i === index) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    });
  }
  function scrollToCard(index) {
    const track = root?.querySelector('[data-comp-track]');
    const card = trackCards()[index];
    if (!track || !card) return;
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    track.scrollTo({ left: card.offsetLeft - (track.clientWidth - card.offsetWidth) / 2, behavior: smooth ? 'smooth' : 'auto' });
    setCarouselStatus(index);
  }
  function paintMarkers() {
    const node = root?.querySelector('[data-comp-markers]');
    if (!node) return;
    node.innerHTML = trackCards().map((card, i) =>
      `<button type="button" data-comp-marker="${i}" aria-label="切换到 ${esc(card.dataset.markerName || `赛事 ${i + 1}`)}"${i === 0 ? ' aria-current="true"' : ''}></button>`).join('');
    if (trackCards().length) setCarouselStatus(0);
  }
  function onCarouselScroll(event) {
    if (!event.target?.closest?.('[data-comp-track]') || carouselRaf) return;
    carouselRaf = requestAnimationFrame(() => { carouselRaf = 0; setCarouselStatus(nearestCardIndex()); });
  }

  function paintSummary() {
    const node = root?.querySelector('[data-comp-summary]');
    if (!node) return;
    const values = [competitions.length, archive.training.length, archive.unfiled.length];
    node.querySelectorAll('b').forEach((item, index) => { item.textContent = fmt(values[index]); });
  }

  function paint() {
    if (!root) return;
    const cur = currentId();
    const curComp = competitions.find((c) => c.id === cur);
    const banner = curComp
      ? `<div class="comp-current">
           <i class="comp-current-dot" aria-hidden="true"></i><span>当前赛事</span>
           <b>${esc(curComp.name)}</b>
           <small>${esc(fmtRange(curComp))}</small>
           <button type="button" class="control" data-comp-clear>${glyph('ban', { size: 18 })}取消选择</button></div>`
      : '';
    const ordered = [...competitions].sort((a, b) =>
      String(b.date || b.createdAt || '').localeCompare(String(a.date || a.createdAt || '')));
    const list = ordered.length
      ? `<div class="comp-carousel">
           <div class="comp-carousel-track" data-comp-track tabindex="0" role="group" aria-label="赛事列表">
             ${ordered.map((c, i) => card(c, i, ordered.length)).join('')}
           </div>
           <div class="comp-carousel-markers" data-comp-markers aria-label="选择赛事"></div>
         </div>`
      : `<div class="comp-empty">
           <div class="comp-empty-mark">${glyph('calendar', { size: 30 })}</div>
           <b>还没有赛事</b>
           <p>先新建赛事并设定训练时间，训练赛会按日期自动归档。</p>
           </div>`;
    const block = `<section class="comp-block comp-events-block">
      <div class="comp-block-head">
        <h2 class="comp-section-title"><span class="comp-section-index">01</span>赛事
          ${ordered.length ? `<span class="comp-count">${ordered.length}</span>` : ''}</h2>
        ${ordered.length > 1 ? `<span class="comp-carousel-actions">
          <button type="button" class="control" data-comp-prev aria-label="上一个赛事">‹</button>
          <span class="comp-carousel-status" data-comp-carousel-status role="status" aria-live="polite" hidden></span>
          <button type="button" class="control" data-comp-next aria-label="下一个赛事">›</button>
        </span>` : ''}
      </div>
      ${list}</section>`;
    const body = root.querySelector('[data-comp-body]');
    if (body) body.innerHTML = loading ? '<div class="comp-loading">正在读取赛事…</div>'
      : banner + block;
    paintMarkers();
    paintNotice();
    paintSummary();
    paintArchive();
    paintSchedules();
  }

  /* ── 赛事域 M2：存量系列批量归属 + 正赛数据录入 ─────────────────── */
  async function paintOps() {
    const body = root.querySelector('[data-comp-ops-body]');
    if (!body) return;
    try {
      const data = await api('studio/workspace/unfiled-series');
      const series = data.series || [];
      const options = competitions.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
      body.innerHTML = series.length
        ? `<ul class="comp-ops-list">${series.map((item) => `
            <li class="comp-ops-row" data-comp-series="${esc(item.id)}">
              <b>${esc(item.opponent || '未命名系列')}</b>
              <small>${esc(item.startAt || '—')} · BO${esc(String(item.bestOf || ''))} · ${(item.games || []).length} 局</small>
              <select aria-label="归属到赛事">${options}</select>
              <button type="button" class="control" data-comp-assign-series>${glyph('sources', { size: 18 })}归属</button>
            </li>`).join('')}</ul>
           <p class="comp-ops-hint">${glyph('warning', { size: 18 })}混编会被拒绝：对局须先挂到同一赛事。</p>`
        : '<p class="comp-ops-empty">没有待归属的系列赛——都已经在赛事名下了。</p>';
    } catch {
      body.innerHTML = '<p class="comp-ops-empty">存量系列读取失败，稍后刷新重试。</p>';
    }
  }

  async function openKplDialog() {
    const dialog = root.querySelector('[data-comp-kpl-dialog]');
    if (!dialog) return;
    const form = dialog.querySelector('[data-comp-kpl-form]');
    const statusBox = dialog.querySelector('[data-comp-kpl-status]');
    const list = dialog.querySelector('[data-comp-kpl-list]');
    const select = form.elements['competitionId'];
    select.innerHTML = competitions.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    const cur = currentId();
    if (cur && competitions.some((c) => c.id === cur)) select.value = cur;
    statusBox.hidden = false;
    statusBox.textContent = '正在拉取本队 KPL 比赛…';
    list.innerHTML = '';
    dialog.showModal();
    try {
      const data = await api('studio/workspace/formal-sync/pull');
      const games = data.games || [];
      statusBox.textContent = games.length
        ? `拉到 ${games.length} 场本队比赛（已自动去重），勾选后落库。`
        : '没有拉到新的本队比赛（或都已在库中）。';
      list.innerHTML = games.map((g, index) => `
        <label class="comp-ops-row"><input type="checkbox" name="battleId" value="${esc(g.battleId)}">
          <b>${esc(g.date || '')} ${esc(g.result === 'win' ? '胜' : g.result === 'loss' ? '负' : '—')}</b>
          <small>vs ${esc(g.opponent)} · ${esc(g.league || '')} ${esc(g.stage || '')} · ${esc(g.bpMode || '')}</small>
        </label>`).join('');
    } catch (error) {
      statusBox.textContent = error.message || '拉取失败';
    }
  }

  async function commitKpl(form) {
    const dialog = root.querySelector('[data-comp-kpl-dialog]');
    const saveBtn = dialog.querySelector('[data-comp-kpl-save]');
    const checked = [...form.querySelectorAll('input[name="battleId"]:checked')]
      .map((input) => input.value);
    if (!checked.length) { setNotice('请先勾选要落库的比赛', { error: true }); return; }
    saveBtn.disabled = true;
    try {
      const data = await api('studio/workspace/formal-sync/commit', {
        method: 'POST', body: JSON.stringify({
          competitionId: form.elements['competitionId'].value,
          battleIds: checked, own: '',
        }),
      });
      const failCount = (data.failed || []).length;
      setNotice(failCount ? `落库 ${data.saved.length} 场，${failCount} 场失败` : `已落库 ${data.saved.length} 场正赛`,
        { error: failCount > 0 });
      dialog.close();
      paintOps();
      load();
    } catch (error) {
      setNotice(error.message || '落库失败', { error: true });
    } finally {
      saveBtn.disabled = false;
    }
  }

  async function archiveWizard(compId) {
    const dialog = root.querySelector('[data-comp-archive-dialog]');
    if (!dialog) return;
    const form = dialog.querySelector('[data-comp-archive-form]');
    form.reset();
    const preview = dialog.querySelector('[data-comp-archive-preview]');
    const cancel = dialog.querySelector('[data-comp-archive-cancel]');
    if (cancel) cancel.onclick = () => dialog.close();
    dialog.showModal();
    preview.textContent = '正在读取收尾检查…';
    try {
      const data = await api(`studio/workspace/competitions/${encodeURIComponent(compId)}/archive-preview`);
      const bits = [];
      if ((data.unconfirmedSeries || []).length) bits.push(`${data.unconfirmedSeries.length} 个未确认系列`);
      if (data.unfiledMatches) bits.push(`${data.unfiledMatches} 局未归属`);
      preview.textContent = bits.length
        ? `归档前请先处理：${bits.join('、')}。确认无误后填新赛事信息继续。`
        : '收尾检查通过，可直接归档并开启新赛季。';
    } catch (error) {
      preview.textContent = error.message || '收尾检查失败';
    }
    form.onsubmit = (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const v = (key) => String(data.get(key) ?? '').trim();
      if (!v('nextName') || !v('nextDate')) { setNotice('新赛事名称与日期必填', { error: true }); return; }
      api(`studio/workspace/competitions/${encodeURIComponent(compId)}/archive`, {
        method: 'POST', body: JSON.stringify({
          nextName: v('nextName'), nextDate: v('nextDate'), nextEndDate: v('nextEndDate'),
          formalFrom: v('formalFrom'), formalTo: v('formalTo'),
        }),
      }).then(() => { setNotice('已归档并开启新赛季'); load(); })
        .catch((error) => setNotice(error.message || '归档失败', { error: true }));
      dialog.close();
    };
  }

  function openFormalDialog() {
    const dialog = root.querySelector('[data-comp-formal-dialog]');
    if (!dialog) return;
    const form = dialog.querySelector('[data-comp-formal-form]');
    form.reset();
    const select = form.elements['competitionId'];
    select.innerHTML = competitions.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    const cur = currentId();
    if (cur && competitions.some((c) => c.id === cur)) select.value = cur;
    dialog.showModal();
    form.elements['date']?.focus();
  }

  async function saveFormal() {
    const dialog = root.querySelector('[data-comp-formal-dialog]');
    if (!dialog) return;
    const form = dialog.querySelector('[data-comp-formal-form]');
    const saveBtn = dialog.querySelector('[data-comp-formal-save]');
    const value = (fieldName) => String(form.elements[fieldName]?.value ?? '').trim();
    const lineup = value('lineup').split('\n').map((line) => line.trim()).filter(Boolean);
    // 赛果选择是「我方胜/负」语义，而库里 winner 存的是绝对阵营；
    // 必须按我方阵营换算，红方我方胜不能再被显示成失利。
    const ownSide = value('ownSide') || 'blue';
    const result = value('winner');
    const winner = result === 'win' ? ownSide
      : result === 'loss' ? (ownSide === 'blue' ? 'red' : 'blue') : null;
    const payload = {
      date: value('date'), opponent: value('opponent'), score: value('score'),
      ownSide, winner, competitionId: value('competitionId') || null,
      lineup: lineup.length ? lineup : null,
    };
    const splitList = (name) => value(name)
      ? value(name).split(/[，,、]/).map((item) => item.trim()).filter(Boolean) : [];
    const picksOwn = splitList('picksOwn');
    const picksFoe = splitList('picksFoe');
    const bansOwn = splitList('bansOwn');
    const bansFoe = splitList('bansFoe');
    if (picksOwn.length || picksFoe.length || bansOwn.length || bansFoe.length) {
      payload.ownSide = value('ownSide') || 'blue';
      payload.bp = {
        bans: { left: bansOwn, right: bansFoe },
        picks: { left: picksOwn, right: picksFoe },
      };
    }
    if (!payload.date || !payload.opponent) { setNotice('日期与对手必填', { error: true }); return; }
    saveBtn.disabled = true;
    try {
      const data = await api('studio/workspace/formal-matches', {
        method: 'POST', body: JSON.stringify(payload),
      });
      setNotice(data.dedup ? '已存在同对手同日期同比分的正赛，未重复录入' : '正赛已录入并归属赛事');
      dialog.close();
      paintOps();
      load();
    } catch (error) {
      setNotice(error.message || '录入失败，稍后再试', { error: true });
    } finally {
      saveBtn.disabled = false;
    }
  }

  const AGG_LABEL = { window: '按训练时间', manual: '手动挂载', direct: '直连', unfiled: '未归档' };
  function aggLabel(value) { return AGG_LABEL[value] || value || '—'; }

  /* 第一列：头像 vs 头像（2026-11-22 反馈）。channel-xxx 这种裸 ID 教练认不出来，
     换成 本队 / 对手 两枚队徽 + 对手名；队徽取队名首字，悬停可见完整对局 ID，
     点整格进对局复盘。对手没标注时给「未」占位徽，不挤表。 */
  function teamOf(id) { return teams.find((t) => t.id === id) || null; }
  function crestOf(team, fallback) {
    const name = String(team?.name || '').trim();
    return esc((name || fallback || '未').trim()[0] || '未');
  }
  function versusCell(row) {
    const key = String(row.match_key ?? '');
    const own = teamOf(row.own_team_id || 'team-own');
    const foe = teamOf(row.enemy_team_id);
    const foeName = String(foe?.name || '').trim() || '对手未标注';
    return `<th scope="row" class="comp-versus-cell">
      <a class="comp-versus" href="#match/${encodeURIComponent(key)}" title="对局 ${esc(key)} · 打开复盘">
        <span class="comp-crest is-own" aria-hidden="true">${crestOf(own, '本')}</span>
        <i class="comp-versus-x" aria-hidden="true">vs</i>
        <span class="comp-crest is-foe" aria-hidden="true">${crestOf(foe, '未')}</span>
        <b class="comp-versus-name">${esc(foeName)}</b>
        <span class="visually-hidden">对阵 ${esc(String(own?.name || '本队'))} vs ${esc(foeName)}，打开复盘</span>
      </a>
    </th>`;
  }
  function normalRow(row) {
    return `<tr>
      ${versusCell(row)}
      <td>${esc(row.trainingDate || row.date || '—')}</td>
      <td>${esc(row.date || '—')}</td>
      <td>${esc(row.matchType === 'formal' ? '正式赛' : '训练赛')}</td>
      <td>${esc(row.session || row.source || '—')}</td>
      <td>${esc(aggLabel(row.aggregation))}</td>
    </tr>`;
  }
  function dateOf(row) { return String(row.trainingDate || row.date || ''); }
  function sortedByDate(rows) { return [...rows].sort((a, b) => dateOf(b).localeCompare(dateOf(a))); }
  function archivedRow(row) {
    const name = row.competitionName || competitions.find((c) => c.id === row.competitionId)?.name || '—';
    return `<tr>
      <td>${esc(dateOf(row) || '—')}</td>
      ${versusCell(row)}
      <td>${esc(row.session || row.source || '—')}</td>
      <td><span class="comp-event-tag" title="${esc(name)}">${esc(name)}</span></td>
      <td><span class="comp-agg is-${esc(row.aggregation || '')}">${esc(aggLabel(row.aggregation))}</span></td>
      <td><button type="button" class="control is-danger" data-comp-exclude="${esc(String(row.match_key || ''))}" aria-label="从归档中移除对局 ${esc(String(row.match_key || ''))}">${glyph('trash', { size: 13 })}移除</button></td>
    </tr>`;
  }
  function unfiledRow(row) {
    const key = String(row.match_key ?? '');
    return `<tr>
      <td>${esc(dateOf(row) || '—')}</td>
      ${versusCell(row)}
      <td>${esc(row.session || row.source || '—')}</td>
      <td><div class="comp-assign">
        <select data-unfiled-target="${esc(key)}" aria-label="把对局 ${esc(key)} 补挂到赛事">
          <option value="">选择赛事…</option>
          ${competitions.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}
        </select>
        <button type="button" class="control" data-unfiled-assign="${esc(key)}">${glyph('sources', { size: 13 })}补挂</button>
      </div></td>
    </tr>`;
  }
  function matchTable(rows, kind) {
    if (!rows.length) return `<p class="comp-sub-empty">暂无对局。</p>`;
    const unfiled = kind === 'unfiled';
    const caption = unfiled ? '未归档训练赛' : kind === 'formal' ? '已归档正式比赛' : '已归档训练赛';
    const headers = unfiled
      ? ['训练日期', '对阵', '来源', '补挂到赛事']
      : ['训练日期', '对阵', '来源', '所属赛事', '归档方式', '纠错'];
    return `<div class="comp-table-wrap" role="region" aria-label="${esc(caption)}" tabindex="0">
      <table class="comp-table">
        <caption class="visually-hidden">${esc(caption)}</caption>
        <thead><tr>${headers.map((label) => `<th scope="col">${esc(label)}</th>`).join('')}</tr></thead>
        <tbody>${sortedByDate(rows).map((row) => (unfiled ? unfiledRow(row) : archivedRow(row))).join('')}</tbody>
      </table>
    </div>`;
  }

  function paintArchive() {
    const node = root?.querySelector('[data-comp-archive]');
    if (!node) return;
    if (archive.loading) { node.innerHTML = '<div class="comp-loading">正在读取归档…</div>'; return; }
    node.innerHTML = `
      <div class="comp-archive-group">
        <div class="comp-archive-head"><div>
          <b>训练赛归档 <span class="comp-count">${archive.training.length}</span></b>
          <small>按训练日期落入赛事的「训练起始 / 训练结束」，也可在赛事卡片设定时间范围。</small>
        </div></div>
        ${matchTable(archive.training, 'training')}
      </div>
      <div class="comp-archive-group comp-archive-group--unfiled">
        <div class="comp-archive-head"><div>
          <b>未归档区 <span class="comp-count">${archive.unfiled.length}</span></b>
          <small>没有落入任何赛事窗口的训练赛，选赛事后点「补挂」即可归属。</small>
        </div></div>
        <p class="comp-assign-notice${assignNotice.error ? ' is-error' : ''}" data-comp-assign-notice role="status" aria-live="polite"${assignNotice.msg ? '' : ' hidden'}>${esc(assignNotice.msg)}</p>
        ${matchTable(archive.unfiled, 'unfiled')}
      </div>
      <div class="comp-archive-group">
        <div class="comp-archive-head"><div>
          <b>正式比赛 <span class="comp-count">${archive.formal.length}</span></b>
          <small>按正式比赛范围独立归档。</small>
        </div></div>
        ${matchTable(archive.formal, 'formal')}
      </div>
      ${excluded.length ? `<div class="comp-archive-group comp-archive-group--excluded">
        <div class="comp-archive-head"><div>
          <b>已移除 <span class="comp-count">${excluded.length}</span></b>
          <small>拉错的局（如排位 / 巅峰赛）已从归档中排除；撤销后按原日期与赛事窗口重新归集。</small>
        </div></div>
        <div class="comp-table-wrap" role="region" aria-label="已移除的对局" tabindex="0">
          <table class="comp-table"><thead><tr>
            <th scope="col">对局</th><th scope="col">日期</th><th scope="col">来源</th><th scope="col">移除原因</th><th scope="col">操作</th>
          </tr></thead><tbody>${excluded.map((row) => `<tr>
            <td>${esc(String(row.match_key || '—'))}</td>
            <td>${esc(String(row.date || '—'))}</td>
            <td>${esc(String(row.session || '—'))}</td>
            <td>${esc(String(row.excluded_reason || '未填写'))}</td>
            <td><button type="button" class="control" data-comp-restore="${esc(String(row.match_key || ''))}">${glyph('refresh', { size: 13 })}撤销移除</button></td>
          </tr>`).join('')}</tbody></table>
        </div>
      </div>` : ''}`;
    paintSummary();
  }

  /* ── 训练赛排期（原 #plan 页，2026-11-22 并入）：登记训练课、关联赛事 ── */
  const vocabList = (field) => ((vocab && vocab[VOCAB_KINDS[field]]) || []);
  const vocabDatalists = () => ['sessions', 'formats', 'rules', 'versions'].map((key) =>
    `<datalist id="comp-vocab-${key}">${(vocab?.[key] || [])
      .map((value) => `<option value="${esc(value)}"></option>`).join('')}</datalist>`).join('');
  const foeTeamOptions = (current) => teams
    .filter((t) => t.id !== 'team-own')
    .map((t) => `<option value="${esc(t.id)}"${t.id === current ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
  const schedCompOptions = (current) => competitions
    .map((c) => `<option value="${esc(c.id)}"${c.id === current ? ' selected' : ''}>${esc(c.name)} · ${esc(c.date || '')}</option>`).join('');

  function schedRows() {
    const today = localDate();
    const ordered = [...schedules].sort((a, b) => String(a.date || '').localeCompare(String(b.date || ''))
      || String(a.start_time || '').localeCompare(String(b.start_time || '')));
    const upcoming = ordered.filter((x) => String(x.date || '') >= today);
    const past = ordered.filter((x) => String(x.date || '') < today).reverse();
    const next = upcoming.find((x) => x.status !== 'cancelled' && x.status !== 'completed');
    const compNameOf = (x) => competitions.find((c) => c.id === x.competition_id)?.name || '';
    const foeOf = (x) => teams.find((t) => t.id === x.opponent_team_id)?.name || '未指定对手';
    const rowOf = (x) => `<tr>
      <th scope="row"><span class="comp-sched-when"><b>${esc(x.date || '—')}${weekdayOf(x.date) ? ` <small>${esc(weekdayOf(x.date))}</small>` : ''}</b><small>${esc(x.start_time || '时间未定')}</small></span></th>
      <td>${esc(foeOf(x))}</td>
      <td>${esc(x.session || '—')}</td>
      <td>${x.competition_id ? esc(compNameOf(x)) : '<span class="comp-muted-cell">不关联</span>'}</td>
      <td>${esc(x.format || '—')}</td>
      <td><span class="comp-status is-${esc(x.status || 'planned')}">${esc(SCHED_STATUS[x.status] || x.status || '计划中')}</span></td>
      <td><span class="comp-sched-ops">
        <a class="control" href="#session/${encodeURIComponent(x.id)}">${glyph('calendar', { size: 18 })}训练课</a>
        <button type="button" class="control" data-comp-sched-edit="${esc(x.id)}" aria-label="编辑训练课 ${esc(x.date)}">${glyph('edit', { size: 12 })}编辑</button>
      </span></td>
    </tr>`;
    const group = (label, rows, emptyText) => `<h4 class="comp-sched-group">${esc(label)} <span class="comp-count">${rows.length}</span></h4>
      ${rows.length ? `<div class="comp-table-wrap" role="region" aria-label="${esc(label)}训练课" tabindex="0">
        <table class="comp-table comp-sched-table">
          <thead><tr><th scope="col">日期 / 时间</th><th scope="col">约战对手</th><th scope="col">训练组</th><th scope="col">关联赛事</th><th scope="col">赛制</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
          <tbody>${rows.map(rowOf).join('')}</tbody>
        </table>
      </div>` : `<p class="comp-sub-empty">${esc(emptyText)}</p>`}`;
    const nextStrip = next
      ? (() => {
          const parts = [`对阵 ${foeOf(next)}`];
          if (next.session) parts.push(next.session);
          if (next.format) parts.push(next.format);
          return `<div class="comp-current comp-next-strip">
           <i class="comp-current-dot" aria-hidden="true"></i><span>下一场</span>
           <b>${esc(next.date)} ${esc(next.start_time || '')}</b>
           <small>${esc(parts.join(' · '))}</small>
           <a class="control" href="#session/${encodeURIComponent(next.id)}">${glyph('calendar', { size: 18 })}打开训练课</a>
         </div>`;
        })()
      : '';
    const head = `<div class="comp-sched-head">
        ${nextStrip}
        ${schedLoadFailed ? '<p class="comp-sub-empty">训练课排期读取失败，点右上「刷新」重试。</p>' : ''}
      </div>
      ${group('即将到来', upcoming, '没有即将到来的训练课；点上方「排训练课」登记。')}
      ${group('已结束 / 已过期', past, '还没有历史训练课。')}`;
    return { head, next, total: schedules.length };
  }

  function paintSchedules() {
    const node = root?.querySelector('[data-comp-sched]');
    if (!node) return;
    if (!schedLoaded) { node.innerHTML = '<div class="comp-loading">正在读取排期…</div>'; return; }
    const { head, next, total } = schedRows();
    node.innerHTML = head;
    const chip = root?.querySelector('[data-comp-sched-next]');
    if (chip) chip.innerHTML = next ? `下一场 <b>${esc(next.date)}</b>` : '';
    const count = root?.querySelector('[data-comp-sched-count]');
    if (count) count.textContent = `${total}`;
  }

  /** 词表候选拉到后回填 datalist（弹窗打开时即可联想）。 */
  function paintVocab() {
    if (!root) return;
    ['sessions', 'formats', 'rules', 'versions'].forEach((key) => {
      const list = root.querySelector(`#comp-vocab-${key}`);
      if (list) list.innerHTML = (vocab?.[key] || []).map((value) => `<option value="${esc(value)}"></option>`).join('');
    });
  }

  function openScheduleDialog(x = null) {
    const schedDialog = root?.querySelector('[data-comp-sched-dialog]');
    const form = schedDialog?.querySelector('[data-comp-sched-form]');
    if (!form) return;
    form.reset();
    form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
    editingScheduleId = x?.id || '';
    schedDialog.querySelector('[data-comp-sched-title]').textContent = x ? '编辑训练课' : '添加训练课';
    const warn = schedDialog.querySelector('[data-comp-sched-warn]');
    if (warn) { warn.hidden = true; warn.textContent = ''; }
    const set = (name, value) => { const el = form.elements[name]; if (el) el.value = value ?? ''; };
    set('id', x?.id || '');
    set('date', x?.date || localDate());
    set('startTime', x?.start_time || '');
    // 对手 / 关联赛事的候选取当前数据重建（赛事、战队可能刚变过）
    form.elements['opponentTeamId'].innerHTML = `<option value="">未指定对手</option>${foeTeamOptions(x?.opponent_team_id)}`;
    form.elements['competitionId'].innerHTML = `<option value="">不关联比赛</option>${schedCompOptions(x?.competition_id ?? (x ? '' : currentId()))}`;
    set('session', x?.session || '');
    set('format', x?.format || '');
    set('rules', x?.rules || '');
    set('version', x?.version || '');
    set('notes', x?.notes || '');
    set('status', x?.status || 'planned');
    schedDialog.showModal();
    form.elements['date']?.focus();
  }

  function submitSchedule(form) {
    const data = new FormData(form);
    const v = (key) => String(data.get(key) ?? '').trim();
    if (!v('date')) {
      const warn = root.querySelector('[data-comp-sched-warn]');
      if (warn) { warn.textContent = '请填写训练课日期。'; warn.hidden = false; }
      form.elements['date']?.focus();
      return;
    }
    const button = form.querySelector('[type="submit"]');
    if (button) button.disabled = true;
    api('studio/workspace/schedules', {
      method: 'POST',
      body: JSON.stringify({
        id: editingScheduleId || undefined,
        date: v('date'),
        startTime: v('startTime'),
        opponentTeamId: v('opponentTeamId') || null,
        competitionId: v('competitionId') || null,
        session: v('session'),
        format: v('format'),
        rules: v('rules'),
        version: v('version'),
        notes: v('notes'),
        status: v('status') || 'planned',
      }),
    }).then(() => {
      const wasEdit = Boolean(editingScheduleId);
      root.querySelector('[data-comp-sched-dialog]')?.close();
      editingScheduleId = '';
      setNotice(`已${wasEdit ? '保存' : '登记'}训练课（${v('date')}）。`);
      load();
    }).catch((e) => {
      const warn = root.querySelector('[data-comp-sched-warn]');
      if (warn) { warn.textContent = e.message || '保存失败。'; warn.hidden = false; }
      if (button) button.disabled = false;
    });
  }

  /* 训练负荷与目标达成看板已按 2026-11 反馈下线（原 #plan 移植段整段删除）。 */

  function openDialog(comp) {
    if (!dialog) return;
    const form = dialog.querySelector('[data-comp-form]');
    if (!form) return;
    form.reset();
    form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
    editingId = comp ? comp.id : '';
    dialog.querySelector('[data-comp-dialog-title]').textContent = comp ? `编辑赛事 · ${comp.name}` : '新建赛事';
    setWarning('');
    const set = (name, value) => { const el = form.elements[name]; if (el) el.value = value ?? ''; };
    set('id', comp?.id);
    set('name', comp?.name);
    set('date', comp?.date);
    set('endDate', comp?.end_date);
    set('formalFrom', comp?.formal_from);
    set('formalTo', comp?.formal_to);
    set('stage', comp?.stage);
    set('format', comp?.format);
    set('status', comp?.status || 'planned');
    dialog.showModal();
    form.elements['name']?.focus();
  }

  function overlaps(aStart, aEnd, bStart, bEnd) {
    if (!aStart && !aEnd) return false;
    if (!bStart && !bEnd) return false;
    const lowA = aStart || '', highA = aEnd || aStart || '9999-12-31';
    const lowB = bStart || '', highB = bEnd || bStart || '9999-12-31';
    return lowA <= highB && lowB <= highA;
  }
  function findOverlaps(values, excludeId) {
    const hits = [];
    const targetCollect = [values.date, values.endDate || values.date];
    const targetFormal = values.formalFrom ? [values.formalFrom, values.formalTo || values.formalFrom] : null;
    for (const c of competitions) {
      if (excludeId && c.id === excludeId) continue;
      const pairs = [['训练时间窗', targetCollect, [c.date, c.end_date || c.date]]];
      if (targetFormal && c.formal_from) {
        pairs.push(['正式范围', targetFormal, [c.formal_from, c.formal_to || c.formal_from]]);
      }
      for (const [label, a, b] of pairs) {
        if (overlaps(a[0], a[1], b[0], b[1])) {
          hits.push(`「${c.name}」${label} ${rangeText(b[0], b[1])}`);
          break;
        }
      }
    }
    return hits;
  }
  function dialogValues(form) {
    const data = new FormData(form);
    const v = (key) => String(data.get(key) ?? '').trim();
    return { date: v('date'), endDate: v('endDate'), formalFrom: v('formalFrom'), formalTo: v('formalTo') };
  }

  function buildBody(form, id) {
    const data = new FormData(form);
    const v = (key) => String(data.get(key) ?? '').trim();
    const base = id ? (competitions.find((c) => c.id === id) || {}) : {};
    const body = {
      name: v('name'), date: v('date'), endDate: v('endDate'),
      formalFrom: v('formalFrom'), formalTo: v('formalTo'),
      status: v('status') || null,
      stage: v('stage'), format: v('format'),
    };
    if (id) {
      // 编辑：补齐后端非 COALESCE 字段，避免顺手清空既有归属/人员信息。
      Object.assign(body, {
        id,
        opponentTeamId: base.opponent_team_id ?? null,
        teamIds: base.team_ids,
        headCoach: base.head_coach,
        assistantCoach: base.assistant_coach,
        dataAnalyst: base.data_analyst,
        staff: base.staff,
        ownPlayerIds: base.own_player_ids,
        keyMatchKeys: base.key_match_keys,
        owner: base.owner,
        notes: base.notes,
      });
    } else {
      body.status = 'planned';
    }
    return body;
  }

  function onClick(event) {
    const assignBtn = event.target.closest('[data-comp-assign-series]');
    if (assignBtn) {
      const row = assignBtn.closest('[data-comp-series]');
      const select = row && row.querySelector('select');
      const seriesId = row && row.dataset.compSeries;
      if (seriesId && select && select.value) {
        assignBtn.disabled = true;
        api(`studio/workspace/competitions/${encodeURIComponent(select.value)}/assign-series`, {
          method: 'POST', body: JSON.stringify({ seriesIds: [seriesId] }),
        }).then((data) => {
          const failed = (data && data.failed) || [];
          setNotice(failed.length ? failed[0].error : '已归属到所选赛事', { error: failed.length > 0 });
          load();
        }).catch((error) => setNotice(error.message || '归属失败', { error: true }));
      }
      return;
    }
    const statusBtn = event.target.closest('[data-comp-status]');
    if (statusBtn) {
      const target = statusBtn.dataset.compStatus;
      const compId = statusBtn.dataset.compStatusId;
      if (statusBtn.dataset.compArchive) { archiveWizard(compId); return; }
      const comp = competitions.find((c) => c.id === compId);
      api('studio/workspace/competitions', {
        method: 'POST',
        body: JSON.stringify({ id: compId, name: comp?.name || '', date: comp?.date || '',
          endDate: comp?.end_date || '', status: target }),
      }).then(() => { setNotice(target === 'archived' ? '赛事已归档（只读）' : '状态已更新'); load(); })
        .catch((error) => setNotice(error.message || '状态更新失败', { error: true }));
      return;
    }
    if (event.target.closest('[data-comp-kpl-pull]')) { openKplDialog(); return; }
    if (event.target.closest('[data-comp-kpl-cancel]')) {
      const dialog = root.querySelector('[data-comp-kpl-dialog]');
      if (dialog) dialog.close();
      return;
    }
    if (event.target.closest('[data-comp-kpl-save]')) { commitKpl(event.target.closest('[data-comp-kpl-form]')); return; }
    if (event.target.closest('[data-comp-formal-add]')) { openFormalDialog(); return; }
    if (event.target.closest('[data-comp-formal-cancel]')) {
      const dialog = root.querySelector('[data-comp-formal-dialog]');
      if (dialog) dialog.close();
      return;
    }
    if (event.target.closest('[data-comp-formal-save]')) { saveFormal(); return; }
    const select = event.target.closest('[data-comp-select]');
    if (select) {
      const id = select.dataset.compSelect;
      setCurrentId(id);
      paint();
      notify?.(`已设为当前赛事：${competitions.find((c) => c.id === id)?.name || ''}`);
      return;
    }
    if (event.target.closest('[data-comp-clear]')) {
      setCurrentId(''); paint(); notify?.('已取消当前赛事，功能入口已锁定。'); return;
    }
    if (event.target.closest('[data-comp-new]')) { openDialog(null); return; }
    if (event.target.closest('[data-comp-sched-add]')) { openScheduleDialog(null); return; }
    if (event.target.closest('[data-comp-cancel]')) { dialog?.close(); return; }
    if (event.target.closest('[data-comp-sched-cancel]')) {
      root.querySelector('[data-comp-sched-dialog]')?.close();
      editingScheduleId = '';
      return;
    }
    const schedEdit = event.target.closest('[data-comp-sched-edit]');
    if (schedEdit) {
      const row = schedules.find((x) => x.id === schedEdit.dataset.compSchedEdit);
      if (row) openScheduleDialog(row);
      return;
    }
    const edit = event.target.closest('[data-comp-edit]');
    if (edit) {
      const comp = competitions.find((c) => c.id === edit.dataset.compEdit);
      if (comp) openDialog(comp);
      return;
    }
    if (event.target.closest('[data-comp-prev]')) {
      scrollToCard(Math.max(0, nearestCardIndex() - 1)); return;
    }
    if (event.target.closest('[data-comp-next]')) {
      scrollToCard(Math.min(trackCards().length - 1, nearestCardIndex() + 1)); return;
    }
    const marker = event.target.closest('[data-comp-marker]');
    if (marker) { scrollToCard(Number(marker.dataset.compMarker)); return; }
    const assign = event.target.closest('[data-unfiled-assign]');
    if (assign) { assignUnfiled(assign.dataset.unfiledAssign); return; }
    const exclude = event.target.closest('[data-comp-exclude]');
    if (exclude) { excludeMatch(exclude.dataset.compExclude); return; }
    const restore = event.target.closest('[data-comp-restore]');
    if (restore) { restoreMatch(restore.dataset.compRestore); return; }
    const del = event.target.closest('[data-comp-delete]');
    if (del) {
      const comp = competitions.find((c) => c.id === del.dataset.compDelete);
      if (!comp) return;
      pendingDeleteId = comp.id;
      const confirmDialog = root.querySelector('[data-comp-confirm]');
      confirmDialog.querySelector('[data-comp-confirm-msg]').textContent =
        `确定删除赛事「${comp.name}」？训练课与对局不会被删除，只会解除归属。`;
      confirmDialog.showModal(); // 原生焦点收敛/Esc/焦点归还，不自建陷阱
      return;
    }
    if (event.target.closest('[data-comp-confirm-cancel]')) {
      root.querySelector('[data-comp-confirm]')?.close();
      return;
    }
    if (event.target.closest('[data-comp-confirm-ok]')) {
      const id = pendingDeleteId;
      const comp = competitions.find((c) => c.id === id);
      root.querySelector('[data-comp-confirm]')?.close();
      pendingDeleteId = '';
      if (!comp) return;
      api(`studio/workspace/competitions/${encodeURIComponent(id)}`, { method: 'DELETE' })
        .then(() => { if (currentId() === id) setCurrentId(''); if (archive.id === id) archive.id = ''; setNotice(`已删除赛事「${comp.name}」。`); load(true); })
        .catch((e) => setNotice(e.message || '删除失败。', true));
      return;
    }
    if (event.target.closest('[data-comp-reload]')) { load(true); }
  }

  function excludeMatch(key) {
    if (!key) { setNotice('该对局没有可识别的键，无法移除。', true); return; }
    const reason = window.prompt('为什么移除这场对局？（例如：排位赛 / 巅峰赛误拉入）', '比赛类型不对');
    if (reason === null) return;
    api(`studio/workspace/matches/${encodeURIComponent(key)}/exclude`, {
      method: 'POST', body: JSON.stringify({ reason }) })
      .then(() => { setNotice(`已移除对局「${key}」，可在「已移除」区撤销。`); refreshArchive(); })
      .catch((e) => setNotice(e.message || '移除失败。', true));
  }

  function restoreMatch(key) {
    if (!key) return;
    api(`studio/workspace/matches/${encodeURIComponent(key)}/restore`, { method: 'POST', body: '{}' })
      .then(() => { setNotice(`已撤销移除，对局「${key}」重新归集。`); refreshArchive(); })
      .catch((e) => setNotice(e.message || '撤销失败。', true));
  }

  function assignUnfiled(key) {
    const button = Array.from(root?.querySelectorAll('[data-unfiled-assign]') || [])
      .find((el) => el.dataset.unfiledAssign === key);
    const select = button?.closest('tr')?.querySelector('[data-unfiled-target]');
    const compId = select?.value || '';
    if (!compId) { setAssignNotice('请先选择要补挂到的赛事。', true); select?.focus(); return; }
    const comp = competitions.find((c) => c.id === compId);
    if (!comp) return;
    let keys = [];
    try { keys = JSON.parse(comp.key_match_keys || '[]'); } catch { keys = []; }
    if (!Array.isArray(keys)) keys = [];
    if (!keys.includes(key)) keys.push(key);
    api('studio/workspace/competitions', {
      method: 'POST',
      body: JSON.stringify({
        id: comp.id, name: comp.name, date: comp.date, endDate: comp.end_date || '',
        formalFrom: comp.formal_from || '', formalTo: comp.formal_to || '',
        stage: comp.stage || '', format: comp.format || '',
        opponentTeamId: comp.opponent_team_id ?? null,
        teamIds: comp.team_ids, headCoach: comp.head_coach, assistantCoach: comp.assistant_coach,
        dataAnalyst: comp.data_analyst, staff: comp.staff, ownPlayerIds: comp.own_player_ids,
        keyMatchKeys: keys, owner: comp.owner, notes: comp.notes,
      }),
    }).then(() => {
      setAssignNotice(`已把对局「${key}」补挂到赛事「${comp.name}」。`);
      load(true);
    }).catch((e) => setAssignNotice(e.message || '补挂失败。', true));
  }

  function onSubmit(event) {
    const form = event.target.closest('[data-comp-form]');
    if (form) {
      competitionFormSubmit(form, event);
      return;
    }
    const schedForm = event.target.closest('[data-comp-sched-form]');
    if (schedForm) {
      event.preventDefault();
      submitSchedule(schedForm);
    }
  }

  function competitionFormSubmit(form, event) {
    event.preventDefault();
    const data = new FormData(form);
    const name = String(data.get('name') || '').trim();
    const date = String(data.get('date') || '').trim();
    if (!name || !date) {
      // 表单已 novalidate：统一走中文提示，不再弹英文原生气泡。
      setWarning('请填写赛事名称与训练起始日期。');
      form.elements['name']?.setAttribute('aria-invalid', name ? 'false' : 'true');
      form.elements['date']?.setAttribute('aria-invalid', date ? 'false' : 'true');
      (name ? form.elements['date'] : form.elements['name'])?.focus();
      return;
    }
    form.elements['name']?.setAttribute('aria-invalid', 'false');
    form.elements['date']?.setAttribute('aria-invalid', 'false');
    const values = dialogValues(form);
    const hits = findOverlaps(values, editingId);
    // 重叠只警告、不阻止保存（教练自行负责）。
    setWarning(hits.length
      ? `时间窗口与 ${hits.length} 场赛事重叠：${hits.slice(0, 3).join('、')}${hits.length > 3 ? '…' : ''}。仍会保存，请自行确认。`
      : '');
    const body = buildBody(form, editingId);
    api('studio/workspace/competitions', { method: 'POST', body: JSON.stringify(body) })
      .then(() => {
        dialog?.close();
        setNotice(`已${editingId ? '保存' : '新建'}赛事「${name}」。`);
        load(true);
      })
      .catch((e) => setWarning(e.message || '保存失败。'));
  }

  function onDialogChange(event) {
    if (!dialog?.open) return;
    const form = event.target.closest('[data-comp-form]');
    if (!form || !/^(date|endDate|formalFrom|formalTo)$/.test(event.target.name || '')) return;
    const hits = findOverlaps(dialogValues(form), editingId);
    setWarning(hits.length
      ? `窗口重叠提示：${hits.join('、')}（仍可保存，请自行确认）`
      : '');
  }

  function html() {
    return `<div class="comp-page">
      <header class="comp-lead">
        <div class="comp-lead-row">
          <div class="comp-lead-copy">
            <p class="comp-kicker">COMPETITION &amp; TRAINING</p>
            <h1>赛事与训练</h1>
            <p class="comp-lead-sub">管理赛事窗口、训练归档与正式比赛记录。</p>
          </div>
          <div class="comp-lead-actions">
            <button type="button" class="primary comp-gold" data-comp-new>${plus({ size: 18 })}新建赛事</button>
            <button type="button" class="control" data-comp-reload>${glyph('refresh', { size: 18 })}刷新</button>
          </div>
        </div>
        <div class="comp-summary" data-comp-summary aria-label="赛事与训练概览">
          <div><b>0</b><span>赛事</span></div>
          <div><b>0</b><span>训练归档</span></div>
          <div><b>0</b><span>未归档</span></div>
        </div>
        <p class="comp-notice" data-comp-notice role="status" aria-live="polite" hidden></p>
      </header>
      <div data-comp-body></div>
      <section class="comp-block comp-archive-block">
        <div class="comp-block-head">
          <h2 class="comp-section-title"><span class="comp-section-index">02</span>归档区</h2>
        </div>
        <div class="comp-archive-panel" data-comp-archive></div>
      </section>
      <dialog class="comp-dialog" data-comp-archive-dialog aria-labelledby="comp-archive-title">
        <form class="comp-form" data-comp-archive-form novalidate aria-label="归档对局">
          <h3 id="comp-archive-title">归档赛事 · 开启新赛季</h3>
          <p class="comp-dialog-sub" data-comp-archive-preview>正在读取收尾检查…</p>
          <div class="comp-form-grid">
            <label>新赛事名称 <input name="nextName" required placeholder="如：春季赛备战" autocomplete="off"></label>
            <label>新赛事训练起始 <input name="nextDate" type="date" required></label>
            <label>新赛事训练结束 <input name="nextEndDate" type="date"></label>
            <label>正式比赛起 <input name="formalFrom" type="date"></label>
            <label>正式比赛止 <input name="formalTo" type="date"></label>
          </div>
          <div class="comp-dialog-actions">
            <button type="button" class="control" data-comp-archive-cancel>${glyph('ban', { size: 18 })}取消</button>
            <button type="submit" class="primary comp-gold">${glyph('export', { size: 18 })}归档并开启新赛季</button>
          </div>
        </form>
      </dialog>
      <dialog class="comp-dialog" data-comp-kpl-dialog aria-labelledby="comp-kpl-title">
        <form class="comp-form" data-comp-kpl-form novalidate aria-label="录入 KPL 对局">
          <h3 id="comp-kpl-title">拉取 KPL 正赛</h3>
          <p class="comp-warn" data-comp-kpl-status role="status" hidden></p>
          <label>归属赛事 <select name="competitionId"></select></label>
          <div class="comp-archive-panel" data-comp-kpl-list></div>
          <div class="comp-dialog-actions">
            <button type="button" class="control" data-comp-kpl-cancel>${glyph('ban', { size: 18 })}取消</button>
            <button type="button" class="primary comp-gold" data-comp-kpl-save>${glyph('pick', { size: 18 })}落库所选</button>
          </div>
        </form>
      </dialog>
      <dialog class="comp-dialog" data-comp-formal-dialog aria-labelledby="comp-formal-title">
        <form class="comp-form" data-comp-formal-form novalidate aria-label="录入正式比赛">
          <h3 id="comp-formal-title">录入正式比赛</h3>
          <p class="comp-dialog-sub">${glyph('warning', { size: 16 })}同对手 / 日期 / 比分不会重复录入。</p>
          <div class="comp-form-grid">
            <label>比赛日期 <input name="date" type="date" required></label>
            <label>对手 <input name="opponent" required placeholder="对手队名" autocomplete="off"></label>
            <label>比分 <input name="score" placeholder="如 3:1"></label>
            <label>归属赛事 <select name="competitionId"></select></label>
            <label>赛果 <select name="winner"><option value="">未记录</option><option value="win">我方胜</option><option value="loss">我方负</option></select></label>
          </div>
          <label>阵容（可选，每行「阵营,位置,英雄」；留空 = 仅结果级）
            <textarea name="lineup" rows="4" placeholder="我方,对抗路,英雄名&#10;对方,中路,英雄名"></textarea></label>
          <details class="comp-formal-bp">
            <summary>BP 顺序（可选，第三档：逐手名单）</summary>
            <div class="comp-form-grid">
              <label>我方阵营 <select name="ownSide"><option value="blue">蓝方</option><option value="red">红方</option></select></label>
              <label>我方五人（按选人顺序，逗号分隔） <input name="picksOwn" placeholder="英雄1,英雄2,…"></label>
              <label>对方五人（按选人顺序） <input name="picksFoe" placeholder="英雄1,英雄2,…"></label>
              <label>我方 Ban（逗号分隔） <input name="bansOwn" placeholder="英雄,…"></label>
              <label>对方 Ban（逗号分隔） <input name="bansFoe" placeholder="英雄,…"></label>
            </div>
            <small class="comp-ops-hint">${glyph('warning', { size: 16 })}缺人标「顺序待核对」，不伪造顺序。</small>
          </details>
          <div class="comp-dialog-actions">
            <button type="button" class="control" data-comp-formal-cancel>${glyph('ban', { size: 18 })}取消</button>
            <button type="button" class="primary comp-gold" data-comp-formal-save>${glyph('pick', { size: 18 })}保存正赛</button>
          </div>
        </form>
      </dialog>
      <dialog class="comp-dialog" data-comp-dialog aria-labelledby="comp-dialog-title">
        <form class="comp-form" data-comp-form novalidate aria-labelledby="comp-dialog-title">
          <input type="hidden" name="id">
          <h3 id="comp-dialog-title" data-comp-dialog-title>新建赛事</h3>
          <p class="comp-warn" data-comp-warning role="status" hidden></p>
          <div class="comp-form-grid">
            <label>赛事名称 <input name="name" required placeholder="如：王者荣耀全国大赛" autocomplete="off" autofocus></label>
            <label>训练起始 <input name="date" type="date" required></label>
            <label>训练结束 <input name="endDate" type="date"></label>
            <label>正式比赛起 <input name="formalFrom" type="date"></label>
            <label>正式比赛止 <input name="formalTo" type="date"></label>
            <label>赛段 <input name="stage" placeholder="如：11 月线上赛" autocomplete="off"></label>
            <label>赛制 <input name="format" placeholder="如：BO5 / 单循环" autocomplete="off"></label>
            <label>状态 <select name="status"><option value="planned">筹备中</option><option value="ongoing">进行中</option><option value="archived">已归档</option></select></label>
          </div>
          <div class="comp-dialog-actions">
            <button type="button" class="control" data-comp-cancel>${glyph('ban', { size: 18 })}取消</button>
            <button type="submit" class="primary comp-gold">${glyph('pick', { size: 18 })}保存赛事</button>
          </div>
        </form>
      </dialog>
      ${vocabDatalists()}
      <dialog class="comp-dialog comp-confirm" data-comp-confirm aria-labelledby="comp-confirm-title">
        <h3 id="comp-confirm-title">${glyph('warning', { size: 18 })}删除赛事</h3>
        <p class="comp-confirm-msg" data-comp-confirm-msg role="alert"></p>
        <div class="comp-dialog-actions">
          <button type="button" class="control" data-comp-confirm-cancel autofocus>${glyph('ban', { size: 18 })}取消</button>
          <button type="button" class="control comp-del" data-comp-confirm-ok>${glyph('trash', { size: 18 })}确认删除</button>
        </div>
      </dialog>
    </div>`;
  }

  function mount(node, data) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    if (data?.competitionId) archive.id = String(data.competitionId);
    root.innerHTML = html();
    dialog = root.querySelector('[data-comp-dialog]');
    bind(root);
    paint();
    load();
  }
  function bind(node) {
    if (bound === node) return;
    bound = node;
    node.addEventListener('click', onClick);
    node.addEventListener('submit', onSubmit);
    node.addEventListener('change', onDialogChange);
    node.addEventListener('scroll', onCarouselScroll, true);
  }
  function dispose() {
    generation += 1;
    controller?.abort(); controller = null;
    archiveController?.abort(); archiveController = null;
    if (bound) {
      bound.removeEventListener('click', onClick);
      bound.removeEventListener('submit', onSubmit);
      bound.removeEventListener('change', onDialogChange);
      bound.removeEventListener('scroll', onCarouselScroll, true);
      if (carouselRaf) { cancelAnimationFrame(carouselRaf); carouselRaf = 0; }
      bound = null;
    }
    dialog = null;
    root = null;
    editingScheduleId = '';
    pendingDeleteId = '';
    assignNotice = { msg: '', error: false };
  }
  function rerender() { paint(); }

  return { html, render: html, mount, bind, dispose, rerender, load,
    state: {
      get currentId() { return currentId(); },
      get competitions() { return competitions; },
      get archive() { return archive; },
    } };
}

export default createCompetitionsPage;
