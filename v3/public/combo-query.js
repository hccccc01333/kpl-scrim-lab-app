/* KPL 组合查询：全库（双人 / 三人 / 四人）按 1–4 个英雄筛选。
   组件状态在模块内（单局页只有一个实例），浮层挂 body——页面重渲染不丢状态。
   交互模式对齐对局档案的英雄多选浮层（搜索 + 头像网格 + 键盘导航 + 点外收起），
   视觉按 2025 常见 combobox 写法重做：胶囊触发器 + chips + 尺寸 tabs。 */

import { glyph } from './ui-icons.js';

const MAX_SELECT = 4;
const MAX_ROWS = 40;
const SIZE_LABEL = { 2: '双人', 3: '三人', 4: '四人' };

export function createComboQuery({ esc, fmt, portrait, route, icon, getHeroes }) {
  const state = { data: null, selected: [], size: 'all', heroes: [] };

  /* ── 数据 ─────────────────────────────────────────────────────── */
  const listsOf = (data) => ({ 2: data?.pairs || [], 3: data?.trios || [], 4: data?.quads || [] });

  function matches(row) {
    return state.selected.every((hero) => row.heroes.includes(hero));
  }

  function collect() {
    if (!state.data) return [];
    const sizes = state.size === 'all' ? [2, 3, 4] : [Number(state.size)];
    const lists = listsOf(state.data);
    const out = [];
    for (const size of sizes) {
      for (const row of lists[size] || []) {
        if (matches(row)) out.push({ ...row, size });
      }
    }
    out.sort((a, b) => (b.n - a.n) || (a.heroes.join() < b.heroes.join() ? -1 : 1));
    return out;
  }

  function counts() {
    if (!state.data) return {};
    const lists = listsOf(state.data);
    return { 2: (lists[2] || []).filter(matches).length,
             3: (lists[3] || []).filter(matches).length,
             4: (lists[4] || []).filter(matches).length };
  }

  /* ── 片段 ─────────────────────────────────────────────────────── */
  const faceLink = (hero) => `<a class="bp-hero-link kq-face" href="${esc(route('hero', hero))}"
    title="查看 ${esc(hero)} 详情">${portrait(hero)}<b>${esc(hero)}</b></a>`;

  const teamChips = (teams) => {
    const list = (Array.isArray(teams) ? teams : []).filter((row) => row && row.team);
    if (!list.length) return '';
    const shown = list.slice(0, 3);
    const rest = list.length - shown.length;
    const detail = list.map((row) => `${row.team} ${fmt(row.n)} 场 ${fmt(row.wins)} 胜`).join(' · ');
    return `<span class="kq-teams" title="${esc(detail)}">${shown.map((row) =>
      `<span class="kq-team">${esc(row.team)}</span>`).join('')}${rest > 0 ? `<span class="kq-team is-more">+${rest}</span>` : ''}</span>`;
  };

  function rowHtml(row) {
    const when = row.lastDate
      ? `<span class="kq-when">最近 <b>${esc(row.lastDate)}</b></span>`
      : row.year ? `<span class="kq-when"><b>${row.year}</b> 年</span>` : '';
    /* 赛训池行：文字标签（赛训 / 体系名 / 强弱联动）不只靠颜色区分口径。 */
    const flags = [
      row.source === 'custom' ? '<span class="kq-src">赛训</span>' : '',
      row.name ? `<span class="kq-sysname">${esc(row.name)}</span>` : '',
      row.strength === 'strong' ? '<span class="kq-strength is-strong">强联动</span>' : '',
      row.strength === 'weak' ? '<span class="kq-strength is-weak">弱联动</span>' : '',
    ].filter(Boolean).join('');
    return `<div class="kq-row">
      <span class="kq-tag">${SIZE_LABEL[row.size] || ''}</span>
      ${flags}
      <span class="kq-heroes">${row.heroes.map(faceLink).join('<i>+</i>')}</span>
      ${teamChips(row.teams)}
      <span class="kq-stat"><b>${fmt(row.n)}</b> 场<i>·</i>胜率 <b>${has_(row.wr) ? `${Number(row.wr).toFixed(1)}%` : '—'}</b></span>
      ${when}
    </div>`;
  }

  const has_ = (value) => typeof value === 'number' && Number.isFinite(value);

  function resultsHtml() {
    const rows = collect();
    if (!state.selected.length) {
      const total = Object.entries(counts()).map(([size, count]) =>
        `${SIZE_LABEL[size]} ${fmt(count)}`).join(' · ');
      const basis = state.data?.poolActive ? '赛训组组合池' : '样本 ≥3 场';
      return `<div class="kq-hint kq-hint-empty">${glyph('heroes', { size: 28 })}<b>选择英雄开始查询</b><span>最多 4 个，多选只返回包含全部的组合 · 库里共 ${esc(total)} 组（${basis}）</span></div>`;
    }
    if (!rows.length) {
      return `<div class="kq-hint kq-hint-empty">${glyph('warning', { size: 28 })}<b>没有匹配的组合</b><span>KPL 统计窗口内暂无这组${state.size === 'all' ? '' : SIZE_LABEL[state.size]}记录</span></div>`;
    }
    const more = rows.length > MAX_ROWS ? `<p class="kq-more">只展示场次最多的前 ${MAX_ROWS} 行（共 ${fmt(rows.length)} 行命中）</p>` : '';
    return `<div class="kq-list">${rows.slice(0, MAX_ROWS).map(rowHtml).join('')}</div>${more}`;
  }

  function barHtml() {
    const chips = state.selected.map((hero) => `<span class="kq-chip" data-kq-remove="${esc(hero)}"
      title="移除 ${esc(hero)}">${portrait(hero)}<b>${esc(hero)}</b><i aria-hidden="true">×</i></span>`).join('');
    const countsNow = counts();
    const tab = (key, label) => `<button type="button" class="kq-tab${state.size === key ? ' is-on' : ''}"
      data-kq-size="${key}">${glyph(key === 'all' ? 'hero-pool' : 'heroes', { size: 16 })}${label}${key !== 'all' ? `<small>${fmt(countsNow[key])}</small>` : ''}</button>`;
    return `<div class="kq-bar">
      <button type="button" class="kq-open" data-kq-open aria-haspopup="dialog" aria-expanded="false">
        ${glyph('heroes', { size: 18 })}<span>${state.selected.length ? '已选' : '选择英雄'}</span>${chips}
      </button>
      <div class="kq-tabs" role="tablist" aria-label="组合人数">
        ${tab('all', '全部')}${tab(2, '双人')}${tab(3, '三人')}${tab(4, '四人')}
      </div>
    </div>`;
  }

  function footHtml() {
    const data = state.data;
    if (!data) return '';
    const scope = [data.windowStart, data.windowEnd].filter(Boolean).join(' – ');
    /* 池子已保存时双人/三人以名单为准，只在脚注补充背景口径；四人仍走 KPL 全库。 */
    const basis = data.poolActive
      ? '口径：赛训组组合池（最高优先级），双人/三人以池子名单为准；KPL 只补背景场次/胜率。四人组合仍看 KPL 全库。'
      : '口径：同队同场同时选用过的组合，≥1 场即收录，样本 ≥3 场进库';
    return `<p class="kq-foot">${esc(basis)}${scope ? ` · 统计窗口 ${esc(scope)}` : ''}${data.games ? ` · ${fmt(data.games)} 局` : ''}${data.updatedAt ? ` · 更新于 ${esc(String(data.updatedAt).slice(0, 10))}` : ''}。点击英雄名跳英雄详情页。</p>`;
  }

  /* ── 对外：区块内容（app.js 拼进 #match-ov-kq）────────────────── */
  function render(data) {
    state.data = data || null;
    if (!data) {
      return '<div class="md-ov-empty kq-loading">正在读取 KPL 组合库……首次进入单局页会随组合事实表一起到，稍等或刷新。</div>';
    }
    state.heroes = getHeroes().filter(Boolean);
    return `<div class="kq" data-kq-root>${barHtml()}<div data-kq-results>${resultsHtml()}</div>${footHtml()}</div>`;
  }

  /* ── 浮层（英雄选择器）────────────────────────────────────────── */
  function closePop() {
    document.querySelectorAll('.kq-pop').forEach((node) => node.remove());
    document.querySelectorAll('[data-kq-open]').forEach((btn) => btn.setAttribute('aria-expanded', 'false'));
  }

  function openPop(anchor) {
    closePop();
    const pop = document.createElement('div');
    pop.className = 'kq-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', '选择英雄');
    const pool = state.heroes.length ? state.heroes : Object.keys(state.data?.pairs?.[0] ? {} : {}) || [];
    pop.innerHTML = `
      <div class="kq-pop-head"><input class="kq-q" data-kq-q type="text" placeholder="搜索英雄"
        autocomplete="off" spellcheck="false"></div>
      <div class="kq-pop-grid" data-kq-list>${pool.map((hero) => {
        const order = state.selected.indexOf(hero);
        return `<button type="button" class="kq-hero${order >= 0 ? ' is-on' : ''}" data-kq-hero="${esc(hero)}">
          ${portrait(hero)}<span>${esc(hero)}</span>${order >= 0 ? `<i class="kq-order">${order + 1}</i>` : ''}</button>`;
      }).join('')}</div>
      <div class="kq-pop-foot"><span>${state.selected.length ? `已选 ${state.selected.length} / ${MAX_SELECT}` : '按目录顺序排列'}</span>
        <button type="button" class="kq-reset" data-kq-clear>${glyph('trash', { size: 18 })}清空</button></div>`;
    document.body.appendChild(pop);
    const rect = anchor.getBoundingClientRect();
    const width = 392;
    pop.style.width = `${width}px`;
    pop.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 320 && rect.top > spaceBelow) {
      pop.style.bottom = `${window.innerHeight - rect.top + 8}px`;
      pop.style.top = 'auto';
    } else {
      pop.style.top = `${rect.bottom + 8}px`;
      pop.style.bottom = 'auto';
    }
    const maxH = Math.min(468, Math.max(240, Math.min(spaceBelow, rect.top) - 16));
    pop.style.maxHeight = `${maxH}px`;
    anchor.setAttribute('aria-expanded', 'true');
    pop.querySelector('[data-kq-q]').focus();
  }

  function refresh(inPlace) {
    /* 状态变化后只重画块内两处：工具条（chips + tabs 计数）与结果区；浮层选择标另刷。 */
    const root = document.querySelector('[data-kq-root]');
    if (!root) return;
    const bar = root.querySelector('.kq-bar');
    if (bar) {
      const temp = document.createElement('div');
      temp.innerHTML = barHtml();
      bar.replaceWith(temp.firstElementChild);
    }
    const results = root.querySelector('[data-kq-results]');
    if (results) results.innerHTML = resultsHtml();
    if (!inPlace) closePop();
    // 浮层还开着（inPlace）时刷新选择标记
    const pop = document.querySelector('.kq-pop');
    if (pop && inPlace) {
      pop.querySelectorAll('[data-kq-hero]').forEach((btn) => {
        const order = state.selected.indexOf(btn.dataset.kqHero);
        btn.classList.toggle('is-on', order >= 0);
        const badge = btn.querySelector('.kq-order');
        if (order >= 0) {
          if (badge) badge.textContent = String(order + 1);
          else btn.insertAdjacentHTML('beforeend', `<i class="kq-order">${order + 1}</i>`);
        } else if (badge) badge.remove();
      });
      const foot = pop.querySelector('.kq-pop-foot span');
      if (foot) foot.textContent = state.selected.length ? `已选 ${state.selected.length} / ${MAX_SELECT}` : '按目录顺序排列';
    }
  }

  function toggleHero(hero) {
    const at = state.selected.indexOf(hero);
    if (at >= 0) state.selected.splice(at, 1);
    else if (state.selected.length < MAX_SELECT) state.selected.push(hero);
    refresh(true);
  }

  /* ── 一次性事件绑定（app.js 初始化时调用）────────────────────── */
  function bind() {
    document.addEventListener('click', (event) => {
      const open = event.target.closest('[data-kq-open]');
      if (open) {
        if (open.getAttribute('aria-expanded') === 'true') closePop();
        else openPop(open);
        return;
      }
      /* 浮层内部的具体动作先处理；剩下的（点在浮层空白处）不关闭浮层。 */
      const heroBtn = event.target.closest('[data-kq-hero]');
      if (heroBtn) { toggleHero(heroBtn.dataset.kqHero); return; }
      if (event.target.closest('[data-kq-clear]')) {
        state.selected = [];
        refresh(false);
        return;
      }
      if (event.target.closest('.kq-pop')) return;
      if (!event.target.closest('[data-kq-root]')) closePop();
      const remove = event.target.closest('[data-kq-remove]');
      if (remove) { toggleHero(remove.dataset.kqRemove); return; }
      const size = event.target.closest('[data-kq-size]');
      if (size) {
        state.size = size.dataset.kqSize;
        refresh(true);
      }
    });
    document.addEventListener('input', (event) => {
      const input = event.target.closest('[data-kq-q]');
      if (!input) return;
      const text = input.value.trim().toLowerCase();
      const pop = input.closest('.kq-pop');
      if (!pop) return;
      pop.querySelectorAll('[data-kq-hero]').forEach((btn) => {
        btn.hidden = Boolean(text) && !btn.dataset.kqHero.toLowerCase().includes(text);
      });
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && document.querySelector('.kq-pop')) {
        closePop();
        return;
      }
      if (!event.target.closest('.kq-pop') && !event.target.closest('[data-kq-open]')) return;
      const pop = document.querySelector('.kq-pop');
      if (!pop) return;
      const items = [...pop.querySelectorAll('[data-kq-hero]')].filter((btn) => !btn.hidden);
      const current = items.indexOf(pop.querySelector('.kq-kb'));
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const next = current < 0 ? 0 : (current + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
        items.forEach((btn) => btn.classList.remove('kq-kb'));
        items[next]?.classList.add('kq-kb');
        items[next]?.scrollIntoView({ block: 'nearest' });
      } else if (event.key === 'Enter' && current >= 0) {
        event.preventDefault();
        toggleHero(items[current].dataset.kqHero);
      }
    });
  }

  return { render, bind, closePop, state };
}
