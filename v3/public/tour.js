/** 初始化清单：从右上角入口打开，六步完成判定由后端数据给出，每完成一步弹一次提示。 */

const CHECKLIST_API = '/api/studio/workspace/onboarding';
const COMPETITION_KEY = 'training-current-competition';
const CHECKLIST_STEPS = [
  { key: 'profile', title: '战队与选手档案', desc: '队名、联赛与首发选手（含营地 ID 绑定）', link: '#playerarchive', cta: '去建档' },
  { key: 'rules', title: '规则配置', desc: '组合池、克制关系、字段判定——决定分析的口径', link: '#rules', cta: '去配置', optional: true },
  { key: 'opponents', title: '对手库', desc: '常打对手先建档，分析才能「只看本对手」', link: '#teams', cta: '去录入' },
  { key: 'capture', title: '采集第一局', desc: '营地同步或截图录屏，识别结果检查通过', link: '#capture', cta: '去采集' },
  { key: 'series', title: '编第一个系列赛', desc: '把对局编成 BO3/5/7 并确认，解锁大场分析', link: '#series-builder', cta: '去编组' },
  { key: 'corpus', title: '语料积累解锁分析', desc: '跨局 / 体系等按语料阈值逐步亮起', link: '#cross', cta: '看进度' },
];
const checklistDone = (data) => ({
  profile: !!data.ownPlayersBound,
  rules: !!(data.rules && (data.rules.comboPoolSaved || data.rules.counterRules)),
  opponents: (data.opponentCount || 0) >= 1,
  capture: (data.matchCount || 0) >= 1,
  series: (data.confirmedSeries || 0) >= 1,
  corpus: (data.confirmedGames || 0) >= (data.corpusThreshold || 20),
});
function checklistMeta(step, data) {
  if (step.key === 'series') return `${data.confirmedSeries || 0} 个已确认`;
  if (step.key === 'capture') return `已采 ${data.matchCount || 0} 局`;
  if (step.key === 'corpus') return `语料 ${data.confirmedGames || 0}/${data.corpusThreshold || 20} 局`;
  if (step.key === 'opponents') return `${data.opponentCount || 0} 个对手`;
  if (step.key === 'rules') {
    if (data.rules && data.rules.counterRules) return `克制规则 ${data.rules.counterRules} 条`;
    if (data.rules && data.rules.comboPoolSaved) return '组合池已保存';
    return '未配置';
  }
  return '';
}

/* ── 完成提示（toast） ────────────────────────────────────────────────────
   popover="manual" 让提示留在顶层、不被页面 z-index 压住，也不会被点别处关掉；
   不支持 popover 的浏览器退回普通固定定位节点。 */
let toastSeq = 0;
function toastRegion() {
  let region = document.getElementById('cl-toast-region');
  if (!region) {
    region = document.createElement('div');
    region.id = 'cl-toast-region';
    region.className = 'cl-toast-region';
    region.setAttribute('role', 'region');
    region.setAttribute('aria-label', '完成提示');
    document.body.append(region);
  }
  return region;
}
function announce(text) {
  if (typeof window.ariaNotify === 'function') {
    try { window.ariaNotify(text); return; } catch { /* 退回 live region */ }
  }
  let live = document.getElementById('cl-toast-live');
  if (!live) {
    live = document.createElement('div');
    live.id = 'cl-toast-live';
    live.className = 'cl-sr-only';
    live.setAttribute('aria-live', 'polite');
    live.setAttribute('aria-atomic', 'true');
    document.body.append(live);
  }
  live.textContent = '';
  setTimeout(() => { live.textContent = text; }, 30);
}
function restackToasts() {
  toastRegion().querySelectorAll('.cl-toast').forEach((node, index) => {
    node.style.bottom = `${24 + index * 70}px`;
  });
}
function showCompleteToast(title) {
  const text = `你已完成「${title}」`;
  const region = toastRegion();
  const node = document.createElement('div');
  node.id = `cl-toast-${++toastSeq}`;
  node.className = 'cl-toast';
  const native = Object.hasOwn(HTMLElement.prototype, 'popover');
  if (native) node.setAttribute('popover', 'manual');

  const mark = document.createElement('span');
  mark.className = 'cl-toast-mark';
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = '✓';
  const copy = document.createElement('span');
  copy.textContent = text;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'cl-toast-x';
  close.setAttribute('aria-label', '关闭提示');
  close.textContent = '×';
  if (native) {
    close.setAttribute('popovertarget', node.id);
    close.setAttribute('popovertargetaction', 'hide');
  }
  node.append(mark, copy, close);
  region.append(node);
  if (native) node.showPopover?.();
  restackToasts();

  /* 入场动画：下一帧再加 is-in，起始样式交给 @starting-style。 */
  requestAnimationFrame(() => node.classList.add('is-in'));
  announce(text);

  let timer = null;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(dismiss, 4200);
  };
  function dismiss() {
    if (!node.isConnected) return;
    clearTimeout(timer);
    node.classList.remove('is-in');
    const finish = () => {
      if (native && node.matches(':popover-open')) node.hidePopover?.();
      node.remove();
      restackToasts();
    };
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) finish();
    else setTimeout(finish, 220);
  }
  /* 用户正在读/操作这条提示时不要自动收走。 */
  node.addEventListener('mouseenter', () => clearTimeout(timer));
  node.addEventListener('mouseleave', schedule);
  node.addEventListener('focusin', () => clearTimeout(timer));
  node.addEventListener('focusout', schedule);
  close.addEventListener('click', dismiss);
  schedule();
}

export function createChecklist() {
  let mode = 'idle';          // idle | checklist
  let checklistData = null;
  let competition = '';
  let lastDone = null;
  let fetchSeq = 0;
  const layer = document.createElement('div');
  layer.className = 'tour-layer';
  layer.hidden = true;
  document.body.append(layer);

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  function close() {
    mode = 'idle';
    layer.hidden = true;
    layer.innerHTML = '';
  }

  function paintChecklist() {
    if (mode !== 'checklist') return;
    const data = checklistData;
    const done = data ? checklistDone(data) : {};
    const current = data ? (data.competitions || []).find((item) => String(item.id) === String(competition)) : null;
    const statusWord = { ongoing: '进行中', planned: '筹备中', archived: '已归档' }[current?.status] || '';
    const header = competition
      ? `把「${esc(current ? current.name : '当前赛事')}」的数据跑通`
      : '先选一个赛事，再开始归集数据';
    const subline = competition
      ? (statusWord ? `当前赛事 · ${statusWord}` : '当前赛事')
      : '赛事是备战周期：训练赛与正赛都归到它名下';
    const doneCount = CHECKLIST_STEPS.filter((step) => done[step.key]).length;
    const pct = Math.round(doneCount / CHECKLIST_STEPS.length * 100);
    layer.innerHTML = `<div class="tour-full"></div><div class="tour-hub cl-hub" role="dialog" aria-modal="true" aria-labelledby="cl-title">
      <div class="tour-hub-head">
        <span class="tour-eyebrow">初始化清单</span>
        <button class="tour-x" data-cl-close aria-label="关闭清单">×</button>
        <h2 id="cl-title">${header}</h2>
        <p>${esc(subline)} · 六步做完，数据就跑通了。每完成一步会自动提示你。</p>
        <div class="tour-progress"><i style="width:${pct}%"></i><span>已完成 ${doneCount} / ${CHECKLIST_STEPS.length}</span></div>
      </div>
      <ol class="tour-lessons cl-steps">${CHECKLIST_STEPS.map((step, index) => {
        const ok = !!done[step.key];
        return `<li><a class="tour-lesson cl-step ${ok ? 'is-done' : ''}" href="${step.link}" data-cl-goto>
          <span class="tour-lesson-no cl-no" aria-hidden="true">${ok ? '✓' : index + 1}</span>
          <span class="tour-lesson-copy"><b>${esc(step.title)}${step.optional ? '<i class="cl-opt">推荐</i>' : ''}</b><small>${esc(step.desc)}</small></span>
          <span class="tour-lesson-meta"><b>${esc(data ? checklistMeta(step, data) : '')}</b><span class="tour-tags"><i class="tour-state ${ok ? 'is-done' : ''}">${ok ? '已完成' : '待完成'}</i><i class="cl-cta">${ok ? '查看' : esc(step.cta)} →</i></span></span>
        </a></li>`;
      }).join('')}</ol>
      <div class="tour-hub-foot">
        <p>完成状态由数据自动判定，不用手动打勾。</p>
        <div class="tour-hub-actions"><button class="primary" data-cl-close>知道了</button></div>
      </div>
    </div>`;
  }

  async function refreshData() {
    const seq = ++fetchSeq;
    let id = '';
    try { id = localStorage.getItem(COMPETITION_KEY) || ''; } catch { /* 无痕模式 */ }
    try {
      const url = new URL(CHECKLIST_API, location.origin);
      if (id) url.searchParams.set('competition', id);
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) throw new Error('checklist ' + response.status);
      const data = await response.json();
      if (seq !== fetchSeq) return;
      competition = id;
      checklistData = data;
      const done = checklistDone(data);
      if (lastDone) {
        CHECKLIST_STEPS.forEach((step) => {
          if (done[step.key] && !lastDone[step.key]) showCompleteToast(step.title);
        });
      }
      lastDone = done;
      paintChecklist();
    } catch { /* 取数失败时保留上次状态，不打断使用 */ }
  }

  function checklist() {
    mode = 'checklist';
    layer.hidden = false;
    paintChecklist();
    refreshData();
  }

  layer.addEventListener('click', (event) => {
    if (event.target.closest('[data-cl-close]')) { close(); return; }
    /* 清单里的深链：关掉遮罩，让 href 正常把页面带到对应模块。 */
    if (event.target.closest('[data-cl-goto]')) close();
  });

  /* 清单开着时锁住背景滚动；清单内部的步骤列表仍可滚。 */
  const locked = () => mode === 'checklist';
  function scrollableIn(node, boundary) {
    let el = node instanceof Element ? node : null;
    while (el && el !== boundary) {
      const style = getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight - el.clientHeight > 2) return true;
      el = el.parentElement;
    }
    return false;
  }
  function guardScroll(event) {
    if (!locked()) return;
    const hub = layer.querySelector('.tour-hub');
    if (hub && hub.contains(event.target) && scrollableIn(event.target, hub)) return;
    if (event.cancelable) event.preventDefault();
  }
  window.addEventListener('wheel', guardScroll, { passive: false, capture: true });
  window.addEventListener('touchmove', guardScroll, { passive: false, capture: true });
  document.addEventListener('keydown', (event) => {
    if (!locked() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) return;
    if (event.key === ' ' && layer.contains(event.target)) return;
    event.preventDefault();
  }, true);
  document.addEventListener('keydown', (event) => { if (locked() && event.key === 'Escape') close(); });

  /* 完成状态可能被就地保存（不复渲染路由），定时补一次，保证提示不会漏。 */
  setInterval(() => { if (!document.hidden) refreshData(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshData(); });

  return {
    start() { checklist(); },
    open() { checklist(); },
    afterRender() { refreshData(); },
  };
}
