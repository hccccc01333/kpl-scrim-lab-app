/** 上手引导：右上角入口打开的阶段式清单。
 *  设计口径：只把「关键步骤」计入进度；可选规则与语料积累单独呈现，不说谎。
 *  解锁状态直接取 /api/v3/unlocks，避免清单和分析页给出两套答案。
 */

const CHECKLIST_API = '/api/studio/workspace/onboarding';
const UNLOCKS_API = '/api/v3/unlocks';
const COMPETITION_KEY = 'training-current-competition';

/* 只有这 5 步是「跑通数据」的必经步骤。规则是可选项，语料是持续积累，均不计入进度。 */
const KEY_STEPS = ['competition', 'profile', 'opponents', 'capture', 'series'];

const PHASES = [
  {
    no: '01', title: '定赛事', hint: '数据按赛事隔离，先定范围',
    items: [
      { key: 'competition', title: '当前赛事', desc: '训练赛与正赛都归到它名下，分析只看这里的对局', link: '#competitions', cta: '去选赛事' },
    ],
  },
  {
    no: '02', title: '建底稿', hint: '身份信息一次建好，长期复用',
    items: [
      { key: 'profile', title: '战队与选手档案', desc: '队名、联赛、首发选手；绑定营地 ID 后才能看个人表现', link: '#playerarchive', cta: '去建档' },
      { key: 'opponents', title: '对手库', desc: '常打对手先建档，分析才能「只看本对手」', link: '#teams', cta: '去录入' },
      { key: 'rules', title: '规则配置', desc: '组合池与克制关系决定分析口径，内置规则已可直接使用', link: '#rules', cta: '去配置', optional: true },
    ],
  },
  {
    no: '03', title: '出结论', hint: '对局 → 编组 → 分析，解锁以实际数据为准',
    items: [
      { key: 'capture', title: '采集对局', desc: '营地同步 / 截图 / 录屏，识别结果检查通过后入库', link: '#capture', cta: '去采集' },
      { key: 'series', title: '编组并确认系列赛', desc: '把对局编成 BO3/5/7 并确认，大场与跨场分析随之解锁', link: '#series-builder', cta: '去编组' },
      { key: 'corpus', title: '语料深度', desc: '本赛事已确认的对局越多，跨场趋势越稳；这不是一道门槛', link: '#cross', cta: '看进度', continuous: true },
    ],
  },
];

const STATUS_WORD = { ongoing: '进行中', planned: '筹备中', archived: '已归档' };
const ANALYSES = [['biggame', '大场分析', '#biggame'], ['cross', '跨场分析', '#cross']];

function checklistDone(data, competition) {
  const scoped = competition ? (data.scopedMatchCount ?? data.matchCount ?? 0) : (data.matchCount || 0);
  return {
    competition: !!competition,
    profile: !!data.ownPlayersBound,
    opponents: (data.opponentCount || 0) >= 1,
    rules: !!(data.rules && (data.rules.comboPoolSaved || data.rules.counterRules)),
    capture: scoped >= 1,
    series: (data.confirmedSeries || 0) >= 1,
    corpus: (data.confirmedGames || 0) >= (data.corpusThreshold || 20),
  };
}

function itemMeta(key, data, competition, state) {
  switch (key) {
    case 'competition': {
      const cur = (data.competitions || []).find((item) => String(item.id) === String(competition));
      return cur ? `${STATUS_WORD[cur.status] || ''} · 已选` : '未选择';
    }
    case 'profile': return state.profile ? '选手已绑定' : '未绑定';
    case 'opponents': return `${data.opponentCount || 0} 个对手`;
    case 'rules': {
      const rules = data.rules || {};
      if (rules.comboPoolSaved && rules.counterRules) return `组合池 + 内置 ${rules.counterRules} 条`;
      if (rules.comboPoolSaved) return '组合池已保存';
      if (rules.counterRules) return `内置 ${rules.counterRules} 条`;
      return '未配置';
    }
    case 'capture': return competition ? `本赛事 ${data.scopedMatchCount || 0} 局` : `全部 ${data.matchCount || 0} 局`;
    case 'series': return `${data.confirmedSeries || 0} 个已确认`;
    case 'corpus': return `已确认 ${data.confirmedGames || 0}/${data.corpusThreshold || 20} 局`;
    default: return '';
  }
}

function nextStep(data, competition, state) {
  if (!competition) {
    return { title: '先选择或新建一个赛事', body: '赛事是备战周期：训练赛与正赛都归到它名下，之后所有分析只看当前赛事。', href: '#competitions', cta: '去选赛事' };
  }
  if (!state.profile) {
    return { title: '绑定本队选手与营地 ID', body: '没有本队选手档案，个人表现与选人提醒只能用对手数据凑合。', href: '#playerarchive', cta: '去建档' };
  }
  if (!state.opponents) {
    return { title: '录入第一个常打对手', body: '对手库建好后，分析才能按「只看本对手」收窄。', href: '#teams', cta: '去录入' };
  }
  if (!state.capture) {
    return { title: '采集本赛事第一局', body: '营地同步 / 截图 / 录屏都可以，识别结果检查通过才算入库。', href: '#capture', cta: '去采集' };
  }
  if (!state.series) {
    return { title: '把对局编成系列赛并确认', body: '确认 1 个 BO3/5/7 就会解锁大场与跨场分析。', href: '#series-builder', cta: '去编组' };
  }
  return {
    title: '关键步骤已完成，可以开始分析了',
    body: `本赛事已确认 ${data.confirmedGames || 0}/${data.corpusThreshold || 20} 局，语料越足跨场趋势越稳。`,
    href: '#cross', cta: '看分析',
  };
}

/* ── 完成提示（toast）：popover="manual" 让提示留在顶层；不支持时退回固定定位节点。 */
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
  node.addEventListener('mouseenter', () => clearTimeout(timer));
  node.addEventListener('mouseleave', schedule);
  node.addEventListener('focusin', () => clearTimeout(timer));
  node.addEventListener('focusout', schedule);
  close.addEventListener('click', dismiss);
  schedule();
}

export function createChecklist() {
  let mode = 'idle';              // idle | checklist
  let checklistData = null;
  let unlockData = null;
  let competition = '';
  let lastDone = null;
  let lastSignature = '';
  let firstPaint = true;
  let fetchSeq = 0;

  /* 原生 dialog：浏览器负责顶层、焦点圈定、Esc、背景 inert，不再手写滚动锁。 */
  const hub = document.createElement('dialog');
  hub.className = 'tour-hub cl-hub';
  hub.id = 'cl-hub';
  hub.setAttribute('aria-labelledby', 'cl-title');
  document.body.append(hub);

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  hub.addEventListener('close', () => { mode = 'idle'; hub.innerHTML = ''; });

  function close() {
    mode = 'idle';
    if (hub.open) {
      if (typeof hub.close === 'function') hub.close();
      else hub.removeAttribute('open');
    } else {
      hub.innerHTML = '';
    }
  }

  function paintChecklist() {
    if (mode !== 'checklist' || !hub.open) return;
    /* 数据刷新会重建 DOM；记住焦点落点并放回原控件，别让键盘用户丢位置。 */
    const active = document.activeElement;
    const focusKey = active && active !== hub && hub.contains(active) ? (active.dataset.clFocus || '')
      : (active === hub ? 'next' : '');
    const data = checklistData;
    const state = data ? checklistDone(data, competition) : {};
    const doneCount = data ? KEY_STEPS.filter((key) => state[key]).length : 0;
    const total = KEY_STEPS.length;
    const next = data ? nextStep(data, competition, state) : null;
    const current = data ? (data.competitions || []).find((item) => String(item.id) === String(competition)) : null;
    const header = competition
      ? `把「${esc(current ? current.name : '当前赛事')}」的数据用起来`
      : '先选一个赛事，再开始归集数据';
    const subline = competition
      ? `当前赛事 · ${STATUS_WORD[current?.status] || '已选'} · 5 个关键步骤可任意顺序完成`
      : '赛事是备战周期：训练赛与正赛都归到它名下';

    const phases = PHASES.map((phase) => {
      const keyItems = phase.items.filter((item) => KEY_STEPS.includes(item.key));
      const phaseDone = data ? keyItems.filter((item) => state[item.key]).length : 0;
      const rows = phase.items.map((item) => {
        const ok = Boolean(state[item.key]);
        const locked = !competition && item.key !== 'competition' && item.key !== 'rules';
        const stateText = item.continuous ? (ok ? '已达标' : '持续积累')
          : item.optional ? (ok ? '已就绪' : '可选')
            : (ok ? '已完成' : '待完成');
        const href = locked ? '#competitions' : item.link;
        const cta = locked ? '先选赛事' : (ok ? '查看' : item.cta);
        return `<li class="cl-item ${ok ? 'is-done' : ''} ${locked ? 'is-locked' : ''} ${item.continuous ? 'is-continuous' : ''} ${item.optional ? 'is-optional' : ''}">
          <a href="${href}" data-cl-goto data-cl-focus="item-${item.key}">
            <span class="cl-mark" aria-hidden="true">${ok ? '✓' : (item.continuous ? '~' : '·')}</span>
            <span class="cl-item-copy"><b>${esc(item.title)}${item.optional ? '<i class="cl-optional">可选</i>' : ''}</b><small>${esc(item.desc)}</small></span>
            <span class="cl-item-side"><em>${esc(data ? itemMeta(item.key, data, competition, state) : '')}</em><i class="cl-state ${ok ? 'is-done' : ''}">${stateText}</i><i class="cl-cta">${esc(cta)} →</i></span>
          </a>
        </li>`;
      }).join('');
      return `<li class="cl-phase ${data && phaseDone === keyItems.length ? 'is-done' : ''}">
        <header><span class="cl-phase-no">${phase.no}</span><h3>${phase.title}</h3><p>${phase.hint}</p><span class="cl-phase-count">${data ? phaseDone : 0}/${keyItems.length}</span></header>
        <ol class="cl-items">${rows}</ol>
      </li>`;
    }).join('');

    const available = ANALYSES.map(([key, label, href]) => {
      const route = unlockData?.routes?.[key];
      const on = Boolean(competition && route?.unlocked);
      const hint = !competition ? '选赛事后可用' : (on ? '已解锁' : (route?.hint || '确认系列赛后可用'));
      return on
        ? `<a class="cl-available-item is-on" href="${href}" data-cl-goto data-cl-focus="avail-${key}">${label}<i>${esc(hint)}</i></a>`
        : `<span class="cl-available-item">${label}<i>${esc(hint)}</i></span>`;
    }).join('');

    hub.innerHTML = `<div class="tour-hub-head">
        <span class="cl-eyebrow">上手引导 · 3 个阶段</span>
        <button class="tour-x" data-cl-close data-cl-focus="close" aria-label="关闭引导">×</button>
        <h2 id="cl-title">${header}</h2>
        <p class="cl-subline">${esc(subline)}。完成状态由数据自动判定，不用手动打勾。</p>
        <div class="cl-progress-row">
          <label for="cl-progress">关键步骤</label>
          <progress class="cl-progress" id="cl-progress" max="${total}" value="${doneCount}"></progress>
          <b>${doneCount} / ${total}</b>
        </div>
      </div>
      <div class="cl-body">
        ${next ? `<section class="cl-next" aria-labelledby="cl-next-title">
          <span class="cl-next-kicker">下一步</span>
          <span><h3 id="cl-next-title">${esc(next.title)}</h3><p>${esc(next.body)}</p></span>
          <a class="cl-next-cta" href="${next.href}" data-cl-goto data-cl-focus="next"${firstPaint ? ' autofocus' : ''}>${esc(next.cta)} →</a>
        </section>` : '<p class="cl-loading">正在读取当前进度…</p>'}
        <section class="cl-available" aria-label="分析可用性"><span class="cl-available-kicker">现在可用</span>${available}</section>
        <ol class="cl-phases">${phases}</ol>
      </div>
      <div class="tour-hub-foot">
        <p>规则为可选增强；语料随对局持续积累，不作为解锁门槛。</p>
        <button class="primary" data-cl-close data-cl-focus="dismiss">知道了</button>
      </div>`;
    if (focusKey) {
      const target = hub.querySelector(`[data-cl-focus="${focusKey.replace(/"/g, '')}"]`)
        || hub.querySelector('[data-cl-focus="next"]');
      target?.focus?.({ preventScroll: true });
    }
    firstPaint = false;
  }

  async function refreshData() {
    const seq = ++fetchSeq;
    let id = '';
    try { id = localStorage.getItem(COMPETITION_KEY) || ''; } catch { /* 无痕模式 */ }
    try {
      const url = new URL(CHECKLIST_API, location.origin);
      const unlockUrl = new URL(UNLOCKS_API, location.origin);
      if (id) {
        url.searchParams.set('competition', id);
        unlockUrl.searchParams.set('competition', id);
      }
      const [response, unlockResponse] = await Promise.all([
        fetch(url, { cache: 'no-store' }),
        fetch(unlockUrl, { cache: 'no-store' }).catch(() => null),
      ]);
      if (!response.ok) throw new Error('checklist ' + response.status);
      const data = await response.json();
      const unlocks = unlockResponse?.ok ? await unlockResponse.json() : null;
      if (seq !== fetchSeq) return;
      competition = id;
      checklistData = data;
      unlockData = unlocks;
      const done = checklistDone(data, competition);
      if (lastDone) {
        KEY_STEPS.forEach((key) => {
          const title = PHASES.flatMap((phase) => phase.items).find((item) => item.key === key)?.title;
          if (title && done[key] && !lastDone[key]) showCompleteToast(title);
        });
      }
      lastDone = done;
      const signature = JSON.stringify([competition, data, unlocks?.routes || null]);
      /* 内容没变就不重绘，避免每 15 秒把用户正在点的控件换掉。 */
      if (signature !== lastSignature) {
        lastSignature = signature;
        paintChecklist();
      }
    } catch { /* 取数失败时保留上次状态，不打断使用 */ }
  }

  function checklist() {
    mode = 'checklist';
    firstPaint = true;
    lastSignature = '';
    paintChecklist();
    if (!hub.open) {
      if (typeof hub.showModal === 'function') hub.showModal();
      else hub.setAttribute('open', '');
    }
    refreshData();
  }

  hub.addEventListener('click', (event) => {
    if (event.target.closest('[data-cl-close]')) { close(); return; }
    /* 清单里的深链：关掉弹层，让 href 正常把页面带到对应模块。 */
    if (event.target.closest('[data-cl-goto]')) close();
  });

  /* 完成状态可能被就地保存（不复渲染路由），定时补一次，保证提示不会漏。 */
  setInterval(() => { if (!document.hidden) refreshData(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshData(); });

  return {
    start() { checklist(); },
    open() { checklist(); },
    afterRender() { refreshData(); },
  };
}
