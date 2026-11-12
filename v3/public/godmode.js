/* 工作台 · 上帝模式 v8 · 流式网格版
 *
 * 回到「整洁优先」：页面保持原来的网格流式排版，不做绝对定位画布。
 * 自定义只做四件事，且默认不改变原布局：
 *   1. ⠿ 拖动排序（在流里换位置）
 *   2. ◧ 调整块宽度（全宽 / 2/3 / 1/2 / 1/3，仍然按流排列）
 *   3. 👁 隐藏/显示块
 *   4. 点块内任意元素：隐藏 / 改文字 / 调字号 / 上下移 / 恢复
 * 所有改动按页保存在 localStorage（kpl:v3-godmode:v5）。
 */
(() => {
  const KEY = 'kpl:v3-godmode:v5';
  const BAR_ID = 'gm-editbar';
  const TOOL_ID = 'gm-el-toolbar';
  const STYLE_ID = 'gm-style-v8';

  let state = load();
  let pageKey = routeKey();
  let editing = false;
  let selected = null;
  let observer = null;
  let timer = 0;

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
      return raw && typeof raw === 'object' ? raw : {};
    } catch { return {}; }
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {}
  }
  function routeKey() {
    const raw = (location.hash || '').replace(/^#\/?/, '');
    return raw.split('/')[0].split('?')[0] || 'home';
  }
  function pageEl() {
    return document.querySelector('#content .page') || document.querySelector('#content');
  }
  function pageState() {
    if (!state[pageKey] || typeof state[pageKey] !== 'object') state[pageKey] = {};
    const ps = state[pageKey];
    if (!ps.blocks || typeof ps.blocks !== 'object') ps.blocks = {};
    if (!ps.elements || typeof ps.elements !== 'object') ps.elements = {};
    if (!Array.isArray(ps.order)) ps.order = [];
    return ps;
  }
  function items() {
    const page = pageEl();
    if (!page) return [];
    return [...page.children].filter((el) =>
      el.tagName !== 'SCRIPT' && el.tagName !== 'STYLE'
      && !el.classList.contains('gm-block-controls')
      && !el.classList.contains('gm-resize'));
  }
  function itemId(el) {
    let id = el.getAttribute('data-gm-id');
    if (!id) {
      const heading = el.querySelector('.section-heading h2') || el.querySelector('h2');
      const text = heading ? heading.textContent.trim() : '';
      if (text) {
        id = 'gm-' + text.replace(/[^a-z0-9\u4e00-\u9fa5]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 40);
      } else {
        const parts = [];
        let node = el;
        const page = pageEl();
        while (node && node !== page) {
          const parent = node.parentElement;
          if (!parent) break;
          parts.unshift(node.tagName.toLowerCase() + [...parent.children].indexOf(node));
          node = parent;
        }
        id = 'gm-' + parts.join('-');
      }
      el.setAttribute('data-gm-id', id);
    }
    return id;
  }
  function pathOf(el, root) {
    const chain = [];
    let node = el;
    while (node && node !== root) {
      const parent = node.parentElement;
      if (!parent) return '';
      chain.unshift([...parent.children].indexOf(node));
      node = parent;
    }
    return chain.join('/');
  }
  function elByPath(root, path) {
    if (!path) return null;
    let node = root;
    for (const part of String(path).split('/')) {
      const index = Number(part);
      if (!Number.isInteger(index) || !node || !node.children[index]) return null;
      node = node.children[index];
    }
    return node;
  }

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .gm-editbar{position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:95;display:flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid var(--line,#ddd);border-radius:99px;background:var(--paper,#fff);box-shadow:0 10px 30px rgba(16,28,26,.18);font:700 12px/1 system-ui;pointer-events:none}
      .gm-editbar button{pointer-events:auto;height:28px;padding:0 10px;border:1px solid var(--line,#ddd);border-radius:7px;background:transparent;color:inherit;font:inherit;cursor:pointer}
      .gm-editbar button:hover{border-color:var(--accent,#0e655b);color:var(--accent,#0e655b)}
      .gm-editbar button.primary{background:var(--accent,#0e655b);color:#fff;border-color:var(--accent,#0e655b)}
      .gm-editbar .gm-hint{color:var(--muted,#5e6d69);font-weight:400;font-size:11px;max-width:52ch}
      body.gm-editing [data-gm-item]{outline:1px dashed rgba(14,101,91,.35);outline-offset:-1px}
      .gm-block-controls{position:absolute;top:6px;right:6px;z-index:20;display:none;align-items:center;gap:4px}
      body.gm-editing [data-gm-item]{position:relative}
      body.gm-editing .gm-block-controls{display:flex}
      .gm-ctl{height:26px;min-width:26px;padding:0 7px;border:1px solid var(--accent,#0e655b);border-radius:6px;background:var(--paper,#fff);color:var(--accent,#0e655b);font:700 12px/1 system-ui;cursor:grab}
      .gm-ctl:hover{background:var(--accent,#0e655b);color:#fff}
      .gm-ctl.is-off{background:var(--accent,#0e655b);color:#fff}
      .gm-el-toolbar{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:96;display:flex;align-items:center;gap:5px;padding:7px 9px;border:1px solid var(--line,#ddd);border-radius:99px;background:var(--paper,#fff);box-shadow:0 12px 34px rgba(16,28,26,.22);font:700 12px/1 system-ui;max-width:calc(100vw - 32px);flex-wrap:wrap;justify-content:center}
      .gm-el-toolbar button{height:27px;padding:0 9px;border:1px solid var(--line,#ddd);border-radius:6px;background:transparent;color:inherit;font:inherit;cursor:pointer}
      .gm-el-toolbar button:hover{border-color:var(--accent,#0e655b);color:var(--accent,#0e655b)}
      .gm-el-toolbar .gm-el-name{max-width:22ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted,#5e6d69);font-weight:400}
      .gm-selected{outline:2px solid #c65a3d !important;outline-offset:1px}
      .gm-el-hidden{display:none !important}
      .gm-dragging{opacity:.6}
    `;
    document.head.appendChild(style);
  }

  function button(label, title, onClick, className) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    if (title) b.title = title;
    if (className) b.className = className;
    b.addEventListener('click', (event) => { event.stopPropagation(); onClick(); });
    return b;
  }

  const WIDTHS = ['', '66%', '50%', '33%'];
  function widthLabel(width) {
    if (width === '66%') return '2/3';
    if (width === '50%') return '1/2';
    if (width === '33%') return '1/3';
    return '全宽';
  }

  function ensureControls(item) {
    const id = itemId(item);
    item.setAttribute('data-gm-item', '1');
    let controls = item.querySelector(':scope > .gm-block-controls');
    if (!controls) {
      controls = document.createElement('div');
      controls.className = 'gm-block-controls';
      const drag = button('⠿', '拖动排序', () => {}, 'gm-ctl gm-drag');
      const beginDrag = (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        if (item.dataset.gmDown === '1') return;
        item.dataset.gmDown = '1';
        startDrag(event, item);
      };
      drag.addEventListener('pointerdown', beginDrag);
      drag.addEventListener('mousedown', beginDrag);
      controls.appendChild(drag);
      const widthBtn = button('◧', '切换宽度：全宽 → 2/3 → 1/2 → 1/3', () => {
        const ps = pageState();
        const conf = ps.blocks[id] || {};
        const next = WIDTHS[(WIDTHS.indexOf(conf.width || '') + 1) % WIDTHS.length];
        ps.blocks[id] = { ...conf, width: next };
        save();
        apply();
      }, 'gm-ctl gm-width');
      controls.appendChild(widthBtn);
      controls.appendChild(button('👁', '隐藏/显示这个块', () => {
        const ps = pageState();
        const conf = ps.blocks[id] || {};
        ps.blocks[id] = { ...conf, hidden: !conf.hidden };
        save();
        apply();
      }, 'gm-ctl gm-hide'));
      item.appendChild(controls);
    }
    const ps = pageState();
    const conf = ps.blocks[id] || {};
    const hideBtn = controls.querySelector('.gm-hide');
    if (hideBtn) hideBtn.classList.toggle('is-off', !!conf.hidden);
    const widthBtn = controls.querySelector('.gm-width');
    if (widthBtn) widthBtn.textContent = widthLabel(conf.width || '');
  }

  function startDrag(event, item) {
    event.preventDefault();
    event.stopPropagation();
    item.classList.add('gm-dragging');
    const move = (e) => {
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const target = under && under.closest ? under.closest('[data-gm-item]') : null;
      if (!target || target === item) return;
      const rect = target.getBoundingClientRect();
      const before = e.clientY < rect.top + rect.height / 2;
      target.parentElement.insertBefore(item, before ? target : target.nextSibling);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      item.classList.remove('gm-dragging');
      delete item.dataset.gmDown;
      const ps = pageState();
      ps.order = items().map((el) => itemId(el));
      save();
      apply();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up, { once: true });
  }

  function applyElementOps(item) {
    const id = itemId(item);
    item.querySelectorAll('.gm-el-hidden').forEach((el) => el.classList.remove('gm-el-hidden'));
    const ops = pageState().elements[id] || {};
    for (const [path, op] of Object.entries(ops)) {
      const el = elByPath(item, path);
      if (!el) continue;
      if (op.hidden) el.classList.add('gm-el-hidden');
      if (op.fontSize) el.style.fontSize = op.fontSize + 'px';
      if (typeof op.text === 'string' && !el.children.length) el.textContent = op.text;
    }
  }

  function applyOrder(list) {
    const ps = pageState();
    if (!ps.order.length) return;
    const byId = new Map(list.map((el) => [itemId(el), el]));
    let anchor = null;
    for (const id of ps.order) {
      const el = byId.get(id);
      if (!el) continue;
      if (anchor) anchor.parentElement.insertBefore(el, anchor.nextSibling);
      anchor = el;
    }
  }

  function apply() {
    injectStyle();
    document.body.classList.toggle('gm-editing', editing);
    const page = pageEl();
    if (!page) return;
    const list = items();
    if (!list.length) return;
    const ps = pageState();
    applyOrder(list);
    for (const item of items()) {
      ensureControls(item);
      const id = itemId(item);
      const conf = ps.blocks[id] || {};
      item.style.display = conf.hidden ? 'none' : '';
      item.style.maxWidth = conf.width || '';
      item.style.justifySelf = conf.width ? 'start' : '';
      applyElementOps(item);
    }
    renderEditBar();
    if (!editing) clearSelection();
  }

  function renderEditBar() {
    let bar = document.getElementById(BAR_ID);
    if (!editing) {
      if (bar) bar.remove();
      return;
    }
    if (bar) {
      const count = pageState().order.length ? pageState().order.length : items().length;
      const countEl = bar.querySelector('.gm-count');
      if (countEl) countEl.textContent = `${count} 个块`;
      return;
    }
    bar = document.createElement('div');
    bar.id = BAR_ID;
    bar.className = 'gm-editbar';
    const hint = document.createElement('span');
    hint.className = 'gm-hint';
    hint.textContent = '拖 ⠿ 排序 · ◧ 调宽度 · 👁 显隐 · 点块内元素可改内容';
    bar.appendChild(hint);
    const count = document.createElement('span');
    count.className = 'gm-hint gm-count';
    count.textContent = `${items().length} 个块`;
    bar.appendChild(count);
    bar.appendChild(button('完成', '退出自定义', () => { editing = false; apply(); }));
    bar.appendChild(button('全部显示', '恢复所有隐藏块与元素', () => {
      const ps = pageState();
      ps.blocks = {};
      ps.elements = {};
      save();
      apply();
    }, 'primary'));
    bar.appendChild(button('重置本页', '清掉本页自定义，恢复原始排版', () => {
      delete state[pageKey];
      save();
      apply();
    }));
    document.body.appendChild(bar);
  }

  function clearSelection() {
    if (selected && selected.el) selected.el.classList.remove('gm-selected');
    selected = null;
    const tool = document.getElementById(TOOL_ID);
    if (tool) tool.remove();
  }

  function selectElement(el, item) {
    clearSelection();
    selected = { el, itemId: itemId(item), path: pathOf(el, item) };
    el.classList.add('gm-selected');
    showElementToolbar();
  }

  function showElementToolbar() {
    const existing = document.getElementById(TOOL_ID);
    if (existing) existing.remove();
    if (!selected) return;
    const tool = document.createElement('div');
    tool.id = TOOL_ID;
    tool.className = 'gm-el-toolbar';
    const name = document.createElement('span');
    name.className = 'gm-el-name';
    name.textContent = selected.el.tagName.toLowerCase() + (selected.el.className ? '.' + String(selected.el.className).split(' ')[0] : '');
    tool.appendChild(name);
    const saveOp = (patch) => {
      const ps = pageState();
      ps.elements[selected.itemId] = ps.elements[selected.itemId] || {};
      const conf = ps.elements[selected.itemId][selected.path] || {};
      Object.assign(conf, patch);
      ps.elements[selected.itemId][selected.path] = conf;
      save();
    };
    tool.appendChild(button('隐藏', '隐藏这个元素', () => {
      saveOp({ hidden: true });
      const item = selected.el.closest('[data-gm-item]');
      clearSelection();
      if (item) applyElementOps(item);
    }));
    tool.appendChild(button('改文字', '点一下进入文字编辑，回车保存', () => {
      const el = selected.el;
      el.setAttribute('contenteditable', 'true');
      el.focus();
      const done = () => {
        el.removeAttribute('contenteditable');
        saveOp({ text: el.textContent });
      };
      el.addEventListener('blur', done, { once: true });
      el.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); el.blur(); }
      });
    }));
    tool.appendChild(button('A+', '字号变大', () => {
      const el = selected.el;
      const size = parseFloat(getComputedStyle(el).fontSize) || 14;
      el.style.fontSize = Math.min(60, size + 2) + 'px';
      saveOp({ fontSize: Math.round(parseFloat(el.style.fontSize)) });
    }));
    tool.appendChild(button('A-', '字号变小', () => {
      const el = selected.el;
      const size = parseFloat(getComputedStyle(el).fontSize) || 14;
      el.style.fontSize = Math.max(10, size - 2) + 'px';
      saveOp({ fontSize: Math.round(parseFloat(el.style.fontSize)) });
    }));
    tool.appendChild(button('↑', '上移', () => moveElement(-1)));
    tool.appendChild(button('↓', '下移', () => moveElement(1)));
    tool.appendChild(button('恢复', '恢复这个元素', () => {
      const ps = pageState();
      if (ps.elements[selected.itemId]) {
        delete ps.elements[selected.itemId][selected.path];
        save();
      }
      const item = selected.el.closest('[data-gm-item]');
      clearSelection();
      if (item) applyElementOps(item);
    }));
    tool.appendChild(button('×', '取消选择', clearSelection));
    document.body.appendChild(tool);
  }

  function moveElement(delta) {
    if (!selected) return;
    const el = selected.el;
    const parent = el.parentElement;
    if (!parent) return;
    const siblings = [...parent.children];
    const index = siblings.indexOf(el);
    const target = index + delta;
    if (target < 0 || target >= siblings.length) return;
    if (delta < 0) parent.insertBefore(el, siblings[target]);
    else parent.insertBefore(el, siblings[target].nextSibling);
    selected.path = pathOf(el, el.closest('[data-gm-item]'));
    showElementToolbar();
  }

  function onPageClick(event) {
    if (!editing) return;
    if (event.target.closest('.gm-block-controls,#gm-editbar,#gm-el-toolbar,#gm-launcher')) return;
    const item = event.target.closest('[data-gm-item]');
    if (!item) return;
    if (selected && selected.el === event.target) return;
    event.preventDefault();
    event.stopPropagation();
    selectElement(event.target, item);
  }

  function ensureLauncher() {
    if (document.getElementById('gm-launcher')) return;
    injectStyle();
    const launcher = document.createElement('button');
    launcher.id = 'gm-launcher';
    launcher.type = 'button';
    launcher.textContent = '自定义';
    launcher.title = '自定义这一页：排序 / 宽度 / 显隐 / 块内元素';
    Object.assign(launcher.style, {
      position: 'fixed', right: '18px', bottom: '18px', zIndex: 94,
      height: '36px', padding: '0 15px', border: '1px solid #0e655b', borderRadius: '99px',
      background: '#0e655b', color: '#fff', font: '700 13px/1 system-ui', cursor: 'pointer',
      boxShadow: '0 10px 26px rgba(16,28,26,.22)'
    });
    launcher.addEventListener('click', () => {
      editing = !editing;
      apply();
    });
    document.body.appendChild(launcher);
  }

  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { ensureLauncher(); apply(); }, 120);
  }

  function start() {
    injectStyle();
    ensureLauncher();
    apply();
    if (observer) observer.disconnect();
    observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type !== 'childList') continue;
        const target = mutation.target && mutation.target.nodeType === 1
          ? mutation.target : mutation.target && mutation.target.parentElement;
        if (!target) continue;
        if (target.closest && target.closest(`#${BAR_ID},#${TOOL_ID},#gm-launcher`)) continue;
        schedule();
        return;
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener('click', onPageClick, true);
    window.addEventListener('hashchange', () => {
      pageKey = routeKey();
      editing = false;
      clearSelection();
      schedule();
    });
    window.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') clearSelection();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
