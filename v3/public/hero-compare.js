/* 英雄对比 · 可视化重构
   与「通用跨局分析」同一套设计语言：白底、大读数、一分析一形态、
   每卡一张图、可悬停读数 / 点选换人、教练语言、无解释小字。
   顶头条为浅白对位结论卡：结论式 H1 + 双人左右对位。
   数据：/api/studio/camp-compare 的 heroes.own / heroes.enemy 聚合样本。 */

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const es = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n0 = (v) => isNum(v) ? Math.round(v).toLocaleString('zh-CN') : '—';
const n1 = (v) => isNum(v) ? v.toFixed(1) : '—';
const pc = (v) => isNum(v) ? `${v.toFixed(1)}%` : '—';
const signed = (v) => (v < 0 ? '−' : '+') + Math.round(Math.abs(isNum(v) ? v : 0)).toLocaleString('zh-CN');
const signed1 = (v) => (v < 0 ? '−' : '+') + Math.abs(isNum(v) ? v : 0).toFixed(1);
const tip = (t) => `data-hc-tip="${es(t)}"`;
const keyOf = (x) => `${x.hero}|${x.lane || ''}`;

/* 英雄不能只用「输出」一把尺子量：输出位看经济/输出，游走位看参团/承伤/控制/治疗。
   分路取当前对象 A 的实际位置，A 是输出位就只出输出位对比，是游走位就只出游走位对比。 */
const ROLE_GROUPS = {
  damage: {
    label: '输出 · 资源位', sub: '对抗路 / 打野 / 中路 / 发育路',
    lanes: ['对抗路', '打野', '中路', '发育路'],
    x: { key: 'gpm', label: '分均经济', fmt: n0 },
    y: { key: 'dpm', label: '分均输出', fmt: n0 },
    head: { key: 'dpm', label: '分均输出' },
    strip: [['分均经济', 'gpm', n0], ['分均输出', 'dpm', n0], ['参团率', 'participation', pc], ['KDA', 'kda', n1]],
  },
  support: {
    label: '游走 · 保护位', sub: '游走（辅助）',
    lanes: ['游走'],
    x: { key: 'participation', label: '参团率', fmt: pc },
    y: { key: 'dtpm', label: '分均承伤', fmt: n0 },
    head: { key: 'participation', label: '参团率' },
    strip: [['参团率', 'participation', pc], ['分均承伤', 'dtpm', n0], ['分均控制', 'controlPerMin', n1], ['分均治疗', 'healPerMin', n0]],
  },
};
const roleOf = (x) => (ROLE_GROUPS.support.lanes.indexOf(x.lane) >= 0 ? 'support' : 'damage');

export function createHeroCompare({ esc = es, portrait = () => '' } = {}) {
  const state = { data: null, scope: 'own', keyA: '', keyB: '' };
  const pool = () => (state.data && state.data.heroes && state.data.heroes[state.scope]) || [];
  const find = (k) => pool().find((x) => keyOf(x) === k);

  function initKeys() {
    const list = pool().slice().sort((a, b) => (b.games || 0) - (a.games || 0));
    if (!list.length) { state.keyA = ''; state.keyB = ''; return; }
    if (!find(state.keyA)) state.keyA = keyOf(list[0]);
    if (!find(state.keyB)) state.keyB = keyOf(list[1] || list[0]);
    if (state.keyA === state.keyB && list[1]) state.keyB = keyOf(list[1]);
  }

  const rank = (key, v, list = pool()) => isNum(v) ? 1 + list.filter((x) => isNum(x[key]) && x[key] > v).length : null;
  const quantile = (arr, p) => {
    const s = arr.filter(isNum).slice().sort((a, b) => a - b);
    if (!s.length) return 0;
    const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return s[lo] + (s[hi] - s[lo]) * (i - lo);
  };

  /* ── 通用零件 ─────────────────────────────────────────────── */
  function shell(id, a) {
    return `<div class="hcv" data-hc-viz="${id}">
      <div class="hcv-stage"><div class="hc-view is-enter" data-hc-view="a">${a}</div><div class="hcv-tip" hidden></div></div>
    </div>`;
  }
  const view = (hero, body) => `<div class="hcv-view"><div class="hcv-hero">${hero}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${es(v)}</b><span>${es(label)}</span></div>`;

  function card(id, name, title, chart, titleAttrs = '') {
    return `<article class="hc-card" id="hc-analysis-${id}">
      <div class="hc-card-top"><span class="hc-kicker">${id} / 英雄对比</span></div>
      <div class="hc-card-name">${es(name)}</div>
      <h3 class="hc-card-title"${titleAttrs}>${title}</h3>
      <div class="hc-card-canvas">${chart}</div>
    </article>`;
  }

  function summary(a, b) {
    const marks = METRICS.map(([label, key, show]) => ({
      label, key, show,
      d: (isNum(a[key]) ? a[key] : 0) - (isNum(b[key]) ? b[key] : 0),
      has: isNum(a[key]) && isNum(b[key]),
    }));
    return {
      aWins: marks.filter((x) => x.has && x.d > 0).length,
      bWins: marks.filter((x) => x.has && x.d < 0).length,
      best: marks.filter((x) => x.has).slice().sort((x, y) => Math.abs(y.d) - Math.abs(x.d))[0] || null,
    };
  }

  /* ── 01 六项对位分析 ──────────────────────────────────────── */
  const METRICS = [
    ['场次', 'games', (v) => n0(v), '局'],
    ['胜率', 'winRate', (v) => pc(v), '个百分点'],
    ['KDA', 'kda', (v) => n1(v), ''],
    ['分均经济', 'gpm', (v) => n0(v), '金'],
    ['分均输出', 'dpm', (v) => n0(v), '点'],
    ['参团率', 'participation', (v) => pc(v), '个百分点'],
  ];

  function analysis01(a, b) {
    const cells = METRICS.map(([label, key, show, unit]) => {
      const va = a[key], vb = b[key];
      const total = Math.max(1, Math.abs(isNum(va) ? va : 0) + Math.abs(isNum(vb) ? vb : 0));
      const wa = clamp(Math.abs(isNum(va) ? va : 0) / total * 100, 4, 96);
      const wb = 100 - wa;
      const win = isNum(va) && isNum(vb) ? (va > vb ? 'a' : vb > va ? 'b' : '') : '';
      const gap = isNum(va) && isNum(vb) ? va - vb : null;
      const badge = win
        ? `<b class="hc-cell-badge ${win}">${win === 'a' ? '▲' : '▼'} ${es(win === 'a' ? a.hero : b.hero)} 领先</b>`
        : '<b class="hc-cell-badge tie">持平</b>';
      return `<div class="hc-cell" data-win="${win || 'tie'}" ${tip(`${label} · ${es(a.hero)} ${show(va)} / ${es(b.hero)} ${show(vb)}`)}>
        <div class="hc-cell-head"><span class="hc-cell-label">${es(label)}</span>${badge}</div>
        <div class="hc-cell-duel">
          <b class="a ${win === 'a' ? 'win' : ''}">${show(va)}</b>
          <i class="hc-duel-bar"><em class="a" style="width:${wa.toFixed(1)}%"></em><em class="b" style="width:${wb.toFixed(1)}%"></em></i>
          <b class="b ${win === 'b' ? 'win' : ''}">${show(vb)}</b>
        </div>
        <small>${gap === null ? '—' : `${gap >= 0 ? es(a.hero) : es(b.hero)} 多 ${show(Math.abs(gap))}${unit}`}</small>
      </div>`;
    }).join('');
    const sum = summary(a, b);
    const A = view(big(`${sum.aWins} / 6`, `${a.hero} 领先的指标项数`, 'gold'), `<div class="hc-mtx">${cells}</div>`);
    return shell('01', A);
  }

  /* ── 02 胜率与样本量（Wilson 区间） ──────────────────────────── */
  function wilsonCI(wins, games, z = 1.96) {
    if (!games || games <= 0) return null;
    const p = (wins || 0) / games;
    const z2 = z * z;
    const denom = 1 + z2 / games;
    const center = (p + z2 / (2 * games)) / denom;
    const half = z * Math.sqrt(p * (1 - p) / games + z2 / (4 * games * games)) / denom;
    return { low: Math.max(0, center - half) * 100, high: Math.min(1, center + half) * 100, p: p * 100 };
  }
  function analysis02(a, b) {
    const gap = (isNum(a.winRate) ? a.winRate : 0) - (isNum(b.winRate) ? b.winRate : 0);
    const ciA = wilsonCI(a.wins, a.games), ciB = wilsonCI(b.wins, b.games);
    const R = 62, C = 2 * Math.PI * R;
    const side = (x, cls) => {
      const v = clamp((isNum(x.winRate) ? x.winRate : 0) / 100, 0, 1);
      return `<div class="hc-ring" ${tip(`${x.hero} · ${x.games || 0} 局 · ${x.wins || 0} 胜`)}>
        <svg viewBox="0 0 160 160" role="img" aria-label="${es(x.hero)}胜率">
          <circle class="hc-ring-bg" cx="80" cy="80" r="${R}" fill="none" stroke-width="19"/>
          <circle class="hc-ring-fg ${cls}" cx="80" cy="80" r="${R}" fill="none" stroke-width="19"
            stroke-dasharray="${(v * C).toFixed(2)} ${(C - v * C).toFixed(2)}" stroke-linecap="round" transform="rotate(-90 80 80)"/>
          <text class="hc-ring-num" x="80" y="82" text-anchor="middle">${pc(x.winRate)}</text>
        </svg>
        <b>${es(x.hero)}</b><small>${n0(x.games)} 局 · ${n0(x.wins)} 胜</small></div>`;
    };
    const ciLine = (x, ci) => `${es(x.hero)} ${n0(x.games)} 局${ci ? `（95% CI ${pc(ci.low)}–${pc(ci.high)}）` : ''}`;
    const A = view(big(`${signed1(gap)} 个百分点`, `${gap >= 0 ? a.hero : b.hero} 的胜率更高`, gap >= 0 ? 'gold' : 'teal'),
      `<div class="hc-rings">${side(a, 'a')}
        <div class="hc-rings-mid"><i></i><b>${pc(Math.abs(gap))}</b><span>胜率差</span></div>
        ${side(b, 'b')}</div>
      <p class="hc-ci-line"><b>样本可信度</b><span>${ciLine(a, ciA)}</span><i></i><span>${ciLine(b, ciB)}</span></p>`);
    return shell('02', A);
  }

  /* ── 03 分均产出分析 ──────────────────────────────────────── */
  function analysis03(a, b) {
    const rows = [['分均经济', 'gpm', (v) => n0(v)], ['分均输出', 'dpm', (v) => n0(v)], ['分均承伤', 'dtpm', (v) => n0(v)]];
    const dpmGap = isNum(a.dpm) && isNum(b.dpm) && b.dpm ? (a.dpm - b.dpm) / b.dpm * 100 : 0;
    const A = view(big(`${signed(dpmGap)}%`, `${a.hero} 的分均输出相对 ${b.hero}`, dpmGap >= 0 ? 'gold' : 'teal'),
      `<div class="hc-b2b">${rows.map(([label, key, show]) => {
        const va = isNum(a[key]) ? a[key] : 0, vb = isNum(b[key]) ? b[key] : 0;
        const mx = Math.max(1, Math.abs(va), Math.abs(vb));
        return `<div class="hc-b2b-row" ${tip(`${label} · ${es(a.hero)} ${show(va)} / ${es(b.hero)} ${show(vb)}`)}>
          <b class="a">${show(va)}</b>
          <i class="hc-b2b-track"><em class="a" style="width:${(Math.abs(va) / mx * 50).toFixed(1)}%"></em><em class="b" style="width:${(Math.abs(vb) / mx * 50).toFixed(1)}%"></em></i>
          <b class="b">${show(vb)}</b><span>${es(label)}</span></div>`;
      }).join('')}</div>
      <div class="hc-b2b-foot"><span>蓝 ${es(a.hero)} · ${es(b.hero)} 红</span><span>每行按该项较高者对齐</span></div>`);
    return shell('03', A);
  }

  /* ── 04 分路坐标：尺子跟着对象 A 的实际位置走 ───────────────── */
  const groupOf = (roleId) => pool().filter((x) => roleOf(x) === roleId);

  function roleTitle(a, roleId, list) {
    const g = ROLE_GROUPS[roleId];
    const r = rank(g.head.key, a[g.head.key], list);
    return `${es(a.hero)} · ${g.label}：${g.head.label}排 <em>${r ? `第 ${r}` : '—'}</em> / ${list.length}`;
  }

  function analysis04(a, b) {
    const roleId = roleOf(a);
    const g = ROLE_GROUPS[roleId];
    const list = groupOf(roleId).filter((x) => isNum(x[g.x.key]) && isNum(x[g.y.key]));
    const xs = list.map((x) => x[g.x.key]), ys = list.map((x) => x[g.y.key]);
    const x0 = quantile(xs, .02) * .98, x1 = quantile(xs, .98) * 1.02;
    const y0 = quantile(ys, .02) * .9, y1 = quantile(ys, .98) * 1.05;
    const X = (v) => clamp((v - x0) / Math.max(1, x1 - x0) * 100, 1, 99);
    const Y = (v) => clamp(100 - (v - y0) / Math.max(1, y1 - y0) * 100, 2, 98);
    const inGroup = (x) => roleOf(x) === roleId;
    const pts = list.map((x) => {
      const cls = keyOf(x) === state.keyA ? 'a' : keyOf(x) === state.keyB ? 'b' : '';
      return `<i class="hc-pt ${cls}" style="left:${X(x[g.x.key]).toFixed(2)}%;top:${Y(x[g.y.key]).toFixed(2)}%"
        ${tip(`${x.hero} · ${x.lane} · ${g.x.label} ${g.x.fmt(x[g.x.key])} · ${g.y.label} ${g.y.fmt(x[g.y.key])} · 点一下换到右侧对比`)}
        data-hc-pick="${es(keyOf(x))}"></i>`;
    }).join('');
    const label = (x, cls) => `<span class="hc-pt-label ${cls}" style="left:${X(x[g.x.key]).toFixed(2)}%;top:${Y(x[g.y.key]).toFixed(2)}%">${es(x.hero)}</span>`;
    const rankA = rank(g.head.key, a[g.head.key], list);
    const bigVal = rankA ? `第 ${rankA} / ${list.length}` : (isNum(a[g.head.key]) ? g.head.key === 'participation' ? pc(a[g.head.key]) : n0(a[g.head.key]) : '—');
    const note = `<p class="hc-role-note"><b>${g.label}</b> · ${g.sub} · ${list.length} 个英雄。<span>${roleId === 'support'
      ? '按游走位口径：看参团、承伤、控制与治疗。'
      : '按输出位口径：看经济与输出，看谁把资源转成伤害。'}</span></p>`;
    const scatter = `<div class="hc-scatter-wrap"><div class="hc-grid-lines"><i></i><i></i><i></i><i></i></div>
        ${pts}${inGroup(a) ? label(a, 'a') : ''}${inGroup(b) ? label(b, 'b') : ''}
        <span class="hc-axis-x">${g.x.label} ${g.x.fmt(x0)} → ${g.x.fmt(x1)}</span>
        <span class="hc-axis-y">${g.y.label} ${g.y.fmt(y0)} → ${g.y.fmt(y1)}</span></div>`;
    const strip = `<div class="hc-mtx hc-mtx-role">${g.strip.map(([lbl, key, fmt]) => {
      const va = a[key], vb = b[key];
      const total = Math.max(1, Math.abs(isNum(va) ? va : 0) + Math.abs(isNum(vb) ? vb : 0));
      const wa = clamp(Math.abs(isNum(va) ? va : 0) / total * 100, 4, 96);
      const win = isNum(va) && isNum(vb) ? (va > vb ? 'a' : vb > va ? 'b' : '') : '';
      return `<div class="hc-cell" data-win="${win || 'tie'}" ${tip(`${lbl} · ${es(a.hero)} ${fmt(va)} / ${es(b.hero)} ${fmt(vb)}`)}>
        <span class="hc-cell-label">${lbl}</span>
        <div class="hc-cell-duel"><b class="a ${win === 'a' ? 'win' : ''}">${fmt(va)}</b>
          <i class="hc-duel-bar"><em class="a" style="width:${wa.toFixed(1)}%"></em><em class="b" style="width:${(100 - wa).toFixed(1)}%"></em></i>
          <b class="b ${win === 'b' ? 'win' : ''}">${fmt(vb)}</b></div></div>`;
    }).join('')}</div>`;
    return shell('04', view(big(bigVal, `${a.hero} · ${g.label}的${g.head.label}位次`, roleId === 'support' ? 'teal' : 'gold'), note + scatter + strip));
  }

  /* ── 页面 ─────────────────────────────────────────────────── */
  function heroHead(a, b) {
    const { aWins, bWins, best } = summary(a, b);
    const tie = aWins === bWins;
    const opts = (value) => pool().slice().sort((x, y) => (y.games || 0) - (x.games || 0))
      .map((x) => `<option value="${es(keyOf(x))}"${keyOf(x) === value ? ' selected' : ''}>${es(x.hero)} · ${es(x.lane || '位置未知')}（${n0(x.games)} 局）</option>`).join('');
    const totalGames = pool().reduce((s, x) => s + (isNum(x.games) ? x.games : 0), 0);
    const sel = (side, value) => `<select data-hc-select="${side}">${opts(value)}</select>`;
    return `<section class="hc-hero">
      <div class="hc-hero-top"><span class="hc-hero-kicker">英雄对比 / ${state.scope === 'own' ? '本队' : '对手'}营地样本</span>
        <span class="hc-hero-scope">${n0(pool().length)} 个英雄 · ${n0(totalGames)} 人次出场</span></div>
      <div class="hc-duel">
        <div class="hc-duel-side a">
          <div class="hc-duel-id">${portrait(a.hero, 'hc-avatar')}<div><span>对象 A</span><b>${es(a.hero)}</b><small>${es(a.lane || '位置未知')} · ${n0(a.games)} 局</small></div></div>
          <div class="hc-duel-num"><b>${pc(a.winRate)}</b><span>胜率</span></div>
          ${sel('a', state.keyA)}
        </div>
        <div class="hc-vs"><span>VS</span><i></i><b>${aWins} : ${bWins}</b><small>六项领先</small></div>
        <div class="hc-duel-side b">
          <div class="hc-duel-id">${portrait(b.hero, 'hc-avatar')}<div><span>对象 B</span><b>${es(b.hero)}</b><small>${es(b.lane || '位置未知')} · ${n0(b.games)} 局</small></div></div>
          <div class="hc-duel-num"><b>${pc(b.winRate)}</b><span>胜率</span></div>
          ${sel('b', state.keyB)}
        </div>
      </div>
      <h2 class="hc-claim">${tie
        ? `${es(a.hero)} 与 ${es(b.hero)} 六项各领先 ${aWins} 项，侧重不同`
        : `${es(aWins > bWins ? a.hero : b.hero)} 六项里领先 ${Math.max(aWins, bWins)} 项`}</h2>
      <p class="hc-fact">差距最大的是${es(best ? best.label : '—')}：${es(a.hero)} ${best ? best.show(a[best.key]) : '—'}，${es(b.hero)} ${best ? best.show(b[best.key]) : '—'}</p>
    </section>`;
  }

  function render(value) {
    if (value) state.data = value;
    if (!state.data) return '<div class="page"><div class="loading">正在汇总英雄样本…</div></div>';
    initKeys();
    const a = find(state.keyA), b = find(state.keyB);
    if (!a || !b) return '<div class="page"><div class="empty">当前范围没有可对比的英雄样本。</div></div>';
    const names = ['六项对位分析', '胜率与样本可信度', '分均产出分析', '分路坐标分析'];
    const roleId = roleOf(a);
    const sum = summary(a, b);
    const head01 = sum.aWins === sum.bWins
      ? `六项各领先 <em>${sum.aWins}</em> 项，差距最大的是${es(sum.best ? sum.best.label : '—')}`
      : `${es(a.hero)} 六项里领先 <em>${sum.aWins}</em> 项`;
    const cards = [
      card('01', names[0], head01, analysis01(a, b)),
      card('02', names[1], `胜率差 <em>${signed1((a.winRate || 0) - (b.winRate || 0))}</em> 个百分点，${es((a.winRate || 0) >= (b.winRate || 0) ? a.hero : b.hero)} 更稳`,
        analysis02(a, b)),
      card('03', names[2], `分均输出 <em>${n0(a.dpm)}</em> 对 <em>${n0(b.dpm)}</em>，承伤 ${n0(a.dtpm)} 对 ${n0(b.dtpm)}`,
        analysis03(a, b)),
      card('04', names[3], roleTitle(a, roleId, groupOf(roleId)), analysis04(a, b)),
    ].join('');
    return `<div class="page hc-page">
      <div class="page-intro hc-intro"><div><h1>英雄对比</h1><p>两个英雄摆在一起，看谁更稳、强在哪、下一阶段练谁。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>
      ${heroHead(a, b)}
      <div class="hc-toolbar">
        <label class="hc-filter"><span>样本范围</span><select data-hc-scope>
          <option value="own"${state.scope === 'own' ? ' selected' : ''}>本队英雄</option>
          <option value="enemy"${state.scope === 'enemy' ? ' selected' : ''}>对手英雄</option>
        </select></label>
        <span class="hc-toolbar-count">当前 ${n0(pool().length)} 个英雄 · 点图里的任意英雄可换到右侧对比</span>
      </div>
      <div class="hc-index" role="group" aria-label="分析直达">${names.map((x, i) => `<button type="button" data-hc-jump="0${i + 1}">${es(x)}</button>`).join('')}</div>
      <section class="hc-cards">${cards}</section>
      <p class="hc-source">数据来源：王者营地面板十人结算汇总；英雄身份按英雄名与分路区分，同一英雄不同分路单列。</p>
    </div>`;
  }

  /* ── 交互：一次注册，事件委托，重渲染不重复绑定 ───────────── */
  function rerender() {
    const page = document.querySelector('.hc-page');
    if (page) page.outerHTML = render(null);
  }
  function showTip(target, event) {
    const wrap = target.closest('[data-hc-viz]');
    if (!wrap) return;
    const box = wrap.querySelector('.hcv-tip'), stage = wrap.querySelector('.hcv-stage');
    if (!box || !stage) return;
    box.textContent = target.dataset.hcTip || '';
    box.hidden = false;
    const r = stage.getBoundingClientRect();
    box.style.left = `${clamp(event.clientX - r.left + 12, 8, Math.max(8, r.width - 250))}px`;
    box.style.top = `${clamp(event.clientY - r.top - 38, 6, Math.max(6, r.height - 40))}px`;
  }
  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.hc-page')) return;
    if (t.closest('a')) return;
    const jump = t.closest('[data-hc-jump]');
    if (jump) { const el = document.getElementById(`hc-analysis-${jump.dataset.hcJump}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const pick = t.closest('[data-hc-pick]');
    if (pick && pick.dataset.hcPick) {
      if (pick.dataset.hcPick === state.keyA) state.keyB = state.keyA;
      else state.keyB = pick.dataset.hcPick;
      if (state.keyA === state.keyB) {
        const alt = pool().find((x) => keyOf(x) !== state.keyA);
        if (alt) state.keyB = keyOf(alt);
      }
      rerender();
    }
  });
  document.addEventListener('change', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.hc-page')) return;
    if (t.dataset.hcSelect) {
      const k = t.value;
      if (t.dataset.hcSelect === 'a') {
        state.keyA = k;
        if (state.keyA === state.keyB) { const alt = pool().find((x) => keyOf(x) !== k); if (alt) state.keyB = keyOf(alt); }
      } else state.keyB = k;
      rerender();
      return;
    }
    if (t.hasAttribute('data-hc-scope')) { state.scope = t.value; initKeys(); rerender(); }
  });
  document.addEventListener('mousemove', (event) => {
    const t = event.target.closest ? event.target.closest('[data-hc-tip]') : null;
    if (t && t.closest('.hc-page')) showTip(t, event);
    else document.querySelectorAll('.hcv-tip').forEach((x) => { x.hidden = true; });
  });

  return { render };
}
