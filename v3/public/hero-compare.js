/* 英雄对比 · 可视化重构
   与「通用跨局分析」同一套设计语言：白底、大读数、一分析一形态、
   每卡两个可切换视图、图形可悬停读数 / 点选换人、教练语言、无解释小字。
   顶部沿用「对位深区」深墨蓝结论卡：结论式 H1 + 双人左右对位。
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

const VIEWS = {
  '01': ['六项对位', '差值排序'],
  '02': ['胜率对照', '全英雄位置'],
  '03': ['三项产出', '谁在扛伤害'],
  '04': ['全英雄坐标', '输出分布带'],
  '05': ['出场与胜率', '出场排行'],
};

export function createHeroCompare({ esc = es, portrait = () => '' } = {}) {
  const state = { data: null, scope: 'own', keyA: '', keyB: '', views: {} };
  const pool = () => (state.data && state.data.heroes && state.data.heroes[state.scope]) || [];
  const find = (k) => pool().find((x) => keyOf(x) === k);
  const viewOf = (id) => state.views[id] || 'a';

  function initKeys() {
    const list = pool().slice().sort((a, b) => (b.games || 0) - (a.games || 0));
    if (!list.length) { state.keyA = ''; state.keyB = ''; return; }
    if (!find(state.keyA)) state.keyA = keyOf(list[0]);
    if (!find(state.keyB)) state.keyB = keyOf(list[1] || list[0]);
    if (state.keyA === state.keyB && list[1]) state.keyB = keyOf(list[1]);
  }

  const sorted = (key) => pool().filter((x) => isNum(x[key])).slice().sort((a, b) => b[key] - a[key]);
  const rank = (key, v) => isNum(v) ? 1 + pool().filter((x) => isNum(x[key]) && x[key] > v).length : null;
  const quantile = (arr, p) => {
    const s = arr.filter(isNum).slice().sort((a, b) => a - b);
    if (!s.length) return 0;
    const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return s[lo] + (s[hi] - s[lo]) * (i - lo);
  };

  /* ── 通用零件 ─────────────────────────────────────────────── */
  function shell(id, a, b) {
    const meta = VIEWS[id] || ['看图', '换个角度'];
    const cur = viewOf(id);
    const one = (k, html) => `<div class="hc-view${cur === k ? ' is-enter' : ''}" data-hc-view="${k}"${cur === k ? '' : ' hidden'}>${html}</div>`;
    return `<div class="hcv" data-hc-viz="${id}">
      <div class="hcv-bar"><div class="hcv-switch" role="group" aria-label="切换视图">
        <button type="button" data-hc-view-btn="a" data-hc-viz="${id}" class="${cur === 'a' ? 'is-on' : ''}">${es(meta[0])}</button>
        <button type="button" data-hc-view-btn="b" data-hc-viz="${id}" class="${cur === 'b' ? 'is-on' : ''}">${es(meta[1])}</button>
      </div></div>
      <div class="hcv-stage">${one('a', a)}${one('b', b)}<div class="hcv-tip" hidden></div></div>
    </div>`;
  }
  const view = (hero, body) => `<div class="hcv-view"><div class="hcv-hero">${hero}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${es(v)}</b><span>${es(label)}</span></div>`;
  const barRow = (label, value, width, cls, tipText, sub = '') => `<div class="hcv-row" ${tip(tipText)}>
    <span class="hcv-row-label">${es(label)}${sub ? `<small>${es(sub)}</small>` : ''}</span>
    <i class="hcv-track"><b class="${cls}" style="width:${width}"></b></i>
    <em class="hcv-row-val">${es(value)}</em></div>`;
  const scaleTicks = (a, b, c) => `<div class="hcv-ticks"><span>${es(a)}</span><span>${es(b)}</span><span>${es(c)}</span></div>`;

  function card(id, name, title, chart, action, method) {
    return `<article class="hc-card" id="hc-analysis-${id}">
      <div class="hc-card-top"><span class="hc-kicker">${id} / 英雄对比</span></div>
      <div class="hc-card-name">${es(name)}</div>
      <h3 class="hc-card-title">${title}</h3>
      <div class="hc-card-canvas">${chart}</div>
      <div class="hc-card-foot"><div class="hc-train"><span>怎么用</span><p>${es(action)}</p></div>
        <a class="hc-open" href="#hero/${encodeURIComponent((find(state.keyA) || {}).hero || '')}">打开 ${es((find(state.keyA) || {}).hero || '英雄')} 档案 →</a></div>
      <p class="hc-method"><b>怎么算的</b> ${es(method)}</p>
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
      return `<div class="hc-cell" ${tip(`${label} · ${es(a.hero)} ${show(va)} / ${es(b.hero)} ${show(vb)}`)}>
        <span class="hc-cell-label">${es(label)}</span>
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
    const diffs = METRICS.map(([label, key, show, unit]) => ({ label, key, show, unit, d: (isNum(a[key]) ? a[key] : 0) - (isNum(b[key]) ? b[key] : 0) }))
      .sort((x, y) => Math.abs(y.d) - Math.abs(x.d));
    const mx = Math.max(1, ...diffs.map((x) => Math.abs(x.d)));
    const B = view(big(`${diffs.filter((x) => x.d > 0).length} 项`, `${a.hero} 高于 ${b.hero}`, 'teal'),
      `<div class="hcv-rows">${diffs.map((x) => barRow(x.label, `${x.d >= 0 ? '+' : '−'}${x.show(Math.abs(x.d))}${x.unit}`,
        `${(Math.abs(x.d) / mx * 100).toFixed(1)}%`, x.d >= 0 ? 'a' : 'b', `${x.label} · ${es(a.hero)} ${x.show(a[x.key])} / ${es(b.hero)} ${x.show(b[x.key])}`)).join('')}</div>`);
    return shell('01', A, B);
  }

  /* ── 02 胜率可信度分析 ────────────────────────────────────── */
  function analysis02(a, b) {
    const gap = (isNum(a.winRate) ? a.winRate : 0) - (isNum(b.winRate) ? b.winRate : 0);
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
    const A = view(big(`${signed1(gap)} 个百分点`, `${gap >= 0 ? a.hero : b.hero} 的胜率更高`, gap >= 0 ? 'gold' : 'teal'),
      `<div class="hc-rings">${side(a, 'a')}
        <div class="hc-rings-mid"><i></i><b>${pc(Math.abs(gap))}</b><span>胜率差</span></div>
        ${side(b, 'b')}</div>`);
    const vals = pool().map((x) => x.winRate).filter(isNum).sort((x, y) => x - y);
    const q = (p) => quantile(vals, p);
    const lo = q(.1), hi = q(.9), span = Math.max(1, hi - lo);
    const at = (v) => clamp(((isNum(v) ? v : 0) - lo) / span * 100, 1, 99);
    const ra = rank('winRate', a.winRate), rb = rank('winRate', b.winRate);
    const B = view(big(ra ? `第 ${ra} / ${pool().length}` : '—', `${a.hero} 在全英雄的胜率位次`, 'gold'),
      `<div class="hc-band-label"><span>最差的10%对局 ${pc(lo)}</span><b>全英雄 ${pool().length} 个</b><span>最好的10%对局 ${pc(hi)}</span></div>
      <div class="hc-band"><i class="hc-band-fill" style="left:${at(q(.25)).toFixed(1)}%;width:${(at(q(.75)) - at(q(.25))).toFixed(1)}%"></i>
        <i class="hc-band-dot a" style="left:${at(a.winRate).toFixed(1)}%" ${tip(`${a.hero} ${pc(a.winRate)} · 第 ${ra} 名`)}></i>
        <i class="hc-band-dot b" style="left:${at(b.winRate).toFixed(1)}%" ${tip(`${b.hero} ${pc(b.winRate)} · 第 ${rb} 名`)}></i></div>
      <div class="hc-band-foot"><span>${es(a.hero)} 第 ${ra || '—'} 名</span><span>${es(b.hero)} 第 ${rb || '—'} 名</span></div>`);
    return shell('02', A, B);
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
      <div class="hc-b2b-foot"><span>金 ${es(a.hero)} · ${es(b.hero)} 青</span><span>每行按该项较高者对齐</span></div>`);
    const ra = isNum(a.dpm) && isNum(a.dtpm) && a.dtpm ? a.dpm / a.dtpm : 0;
    const rb = isNum(b.dpm) && isNum(b.dtpm) && b.dtpm ? b.dpm / b.dtpm : 0;
    const B = view(big(n1(Math.max(ra, rb)), '每承 1 点伤害换出的输出', 'teal'),
      `<div class="hc-duo">
        <div class="hc-duo-side"><span>${es(a.hero)} · 输出 / 承伤</span><b>${n1(ra)}</b><small>分均输出 ${n0(a.dpm)} · 承伤 ${n0(a.dtpm)}</small></div>
        <i>→</i>
        <div class="hc-duo-side"><span>${es(b.hero)} · 输出 / 承伤</span><b>${n1(rb)}</b><small>分均输出 ${n0(b.dpm)} · 承伤 ${n0(b.dtpm)}</small></div>
        <em>${signed(ra - rb)}</em></div>`);
    return shell('03', A, B);
  }

  /* ── 04 全英雄坐标分析 ────────────────────────────────────── */
  function analysis04(a, b) {
    const list = pool().filter((x) => isNum(x.gpm) && isNum(x.dpm));
    const xs = list.map((x) => x.gpm), ys = list.map((x) => x.dpm);
    const x0 = quantile(xs, .02) * .98, x1 = quantile(xs, .98) * 1.02;
    const y0 = quantile(ys, .02) * .9, y1 = quantile(ys, .98) * 1.05;
    const X = (v) => clamp((v - x0) / Math.max(1, x1 - x0) * 100, 1, 99);
    const Y = (v) => clamp(100 - (v - y0) / Math.max(1, y1 - y0) * 100, 2, 98);
    const pts = list.map((x) => {
      const me = keyOf(x) === state.keyA || keyOf(x) === state.keyB;
      const cls = keyOf(x) === state.keyA ? 'a' : keyOf(x) === state.keyB ? 'b' : '';
      return `<i class="hc-pt ${cls}" style="left:${X(x.gpm).toFixed(2)}%;top:${Y(x.dpm).toFixed(2)}%"
        ${tip(`${x.hero} · ${x.lane || ''} · 分均经济 ${n0(x.gpm)} · 分均输出 ${n0(x.dpm)} · 点一下换到右侧对比`)}
        data-hc-pick="${es(keyOf(x))}"></i>`;
    }).join('');
    const label = (x, cls) => `<span class="hc-pt-label ${cls}" style="left:${X(x.gpm).toFixed(2)}%;top:${Y(x.dpm).toFixed(2)}%">${es(x.hero)}</span>`;
    const ra = rank('dpm', a.dpm);
    const A = view(big(ra ? `第 ${ra} / ${pool().length}` : '—', `${a.hero} 的分均输出位次`, 'gold'),
      `<div class="hc-scatter-wrap"><div class="hc-grid-lines"><i></i><i></i><i></i><i></i></div>
        ${pts}${label(a, 'a')}${label(b, 'b')}
        <span class="hc-axis-x">分均经济 ${n0(x0)} → ${n0(x1)}</span>
        <span class="hc-axis-y">分均输出 ${n0(y0)} → ${n0(y1)}</span></div>`);
    const vals = pool().map((x) => x.dpm).filter(isNum);
    const lo = quantile(vals, .1), hi = quantile(vals, .9), span = Math.max(1, hi - lo);
    const at = (v) => clamp(((isNum(v) ? v : 0) - lo) / span * 100, 1, 99);
    const B = view(big(n0(a.dpm), `${a.hero} 的分均输出`, 'teal'),
      `<div class="hc-band-label"><span>最差的10%对局 ${n0(lo)}</span><b>全英雄分均输出</b><span>最好的10%对局 ${n0(hi)}</span></div>
      <div class="hc-band"><i class="hc-band-fill" style="left:${at(quantile(vals, .25)).toFixed(1)}%;width:${(at(quantile(vals, .75)) - at(quantile(vals, .25))).toFixed(1)}%"></i>
        <i class="hc-band-dot a" style="left:${at(a.dpm).toFixed(1)}%" ${tip(`${a.hero} ${n0(a.dpm)}`)}></i>
        <i class="hc-band-dot b" style="left:${at(b.dpm).toFixed(1)}%" ${tip(`${b.hero} ${n0(b.dpm)}`)}></i></div>
      <div class="hc-band-foot"><span>${es(a.hero)} ${n0(a.dpm)}</span><span>${es(b.hero)} ${n0(b.dpm)}</span></div>`);
    return shell('04', A, B);
  }

  /* ── 05 使用与轮换分析 ────────────────────────────────────── */
  function analysis05(a, b) {
    const list = pool().filter((x) => isNum(x.games) && isNum(x.winRate));
    const bins = [
      { label: '1 局', hit: (g) => g <= 1 },
      { label: '2–3 局', hit: (g) => g >= 2 && g <= 3 },
      { label: '4–6 局', hit: (g) => g >= 4 && g <= 6 },
      { label: '7–10 局', hit: (g) => g >= 7 && g <= 10 },
      { label: '11 局以上', hit: (g) => g >= 11 },
    ].map((x) => {
      const group = list.filter((y) => x.hit(y.games));
      return { ...x, n: group.length, win: group.length ? group.reduce((t, y) => t + y.winRate, 0) / group.length : 0, group };
    });
    const maxN = Math.max(1, ...bins.map((x) => x.n));
    const A = view(big(`${n0(a.games)} 局`, `${a.hero} 的出场，是 ${b.hero} 的 ${(isNum(b.games) && b.games ? a.games / b.games : 0).toFixed(1)} 倍`, 'gold'),
      `<div class="hc-bins">${bins.map((x) => {
        const hasA = x.group.some((y) => keyOf(y) === state.keyA);
        const hasB = x.group.some((y) => keyOf(y) === state.keyB);
        const marks = `${hasA ? `<em class="a" ${tip(`${a.hero} 在「${x.label}」这一档`)}>${es(a.hero)}</em>` : ''}${hasB ? `<em class="b" ${tip(`${b.hero} 在「${x.label}」这一档`)}>${es(b.hero)}</em>` : ''}`;
        return `<div class="hc-bin" ${tip(`${x.label} · ${x.n} 个英雄 · 平均胜率 ${pc(x.win)}`)}>
          <div class="hc-bin-top"><b>${n0(x.win)}%</b><small>平均胜率</small>${marks}</div>
          <i class="hc-bin-bar" style="height:${(x.n / maxN * 100).toFixed(1)}%"><b>${n0(x.n)}</b></i>
          <span>${es(x.label)}</span></div>`;
      }).join('')}</div>`);
    const top = sorted('games').slice(0, 8);
    const mx = Math.max(1, ...top.map((x) => x.games));
    const B = view(big(`${top.length} 个`, '出场最多的英雄', 'teal'),
      `<div class="hcv-rows">${top.map((x) => {
        const me = keyOf(x) === state.keyA || keyOf(x) === state.keyB;
        return barRow(`${x.hero} · ${x.lane || ''}`, `${n0(x.games)} 局`, `${(x.games / mx * 100).toFixed(1)}%`, me ? 'a' : '',
          `${x.hero} · ${x.games} 局 · 胜率 ${pc(x.winRate)}`, me ? '当前对比' : '');
      }).join('')}</div>`);
    return shell('05', A, B);
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
    const names = ['六项对位分析', '胜率可信度分析', '分均产出分析', '全英雄坐标分析', '使用与轮换分析'];
    const ra = rank('dpm', a.dpm);
    const sum = summary(a, b);
    const head01 = sum.aWins === sum.bWins
      ? `六项各领先 <em>${sum.aWins}</em> 项，差距最大的是${es(sum.best ? sum.best.label : '—')}`
      : `${es(a.hero)} 六项里领先 <em>${sum.aWins}</em> 项`;
    const cards = [
      card('01', names[0], head01,
        analysis01(a, b), `把领先项固定成 ${a.hero} 的选用理由，落后项列进 ${b.hero} 的专项训练。`,
        '本队营地结算汇总；六项均为该英雄全部出场局的均值或比率，不同英雄的出场局数不同。'),
      card('02', names[1], `胜率差 <em>${signed1((a.winRate || 0) - (b.winRate || 0))}</em> 个百分点，${es((a.winRate || 0) >= (b.winRate || 0) ? a.hero : b.hero)} 更稳`,
        analysis02(a, b), `胜率高但出场少的一边先补齐场次，再决定比赛日首选。`,
        '胜率＝胜场 / 有胜负的局；全英雄位次按同一范围全部英雄排序，出场局数一并给出。'),
      card('03', names[2], `分均输出 <em>${n0(a.dpm)}</em> 对 <em>${n0(b.dpm)}</em>，承伤 ${n0(a.dtpm)} 对 ${n0(b.dtpm)}`,
        analysis03(a, b), `输出高但承伤也高的一边，训练里补一轮站位与进场时机。`,
        '分均值＝总量 ÷ 出场总时长（分钟）；输出 / 承伤比用同一局集合的分均值相除。'),
      card('04', names[3], `${es(a.hero)} 的分均输出排全英雄 <em>${ra ? `第 ${ra}` : '—'}</em> / ${pool().length}`,
        analysis04(a, b), `在坐标图里点任意英雄换到右侧，快速筛出同档可替代人选。`,
        '横轴分均经济、纵轴分均输出，点为同范围全部英雄；分布带用全英雄第 10 / 25 / 50 / 75 / 90 档。'),
      card('05', names[4], `${es(a.hero)} 用了 <em>${n0(a.games)}</em> 局，${es(b.hero)} 用了 ${n0(b.games)} 局`,
        analysis05(a, b), `出场多且胜率稳的作主选，出场少的排进下一轮轮换验证。`,
        '横轴出场局数、纵轴胜率、点大小按分均输出；竖线为全英雄出场典型水平，横线为 50% 胜率。'),
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
  function switchView(id, key) {
    state.views[id] = key;
    const wrap = [...document.querySelectorAll('[data-hc-viz]')].find((el) => el.dataset.hcViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-hc-view-btn]').forEach((x) => x.classList.toggle('is-on', x.dataset.hcViewBtn === key));
    wrap.querySelectorAll('.hc-view').forEach((x) => {
      const on = x.dataset.hcView === key;
      x.hidden = !on;
      x.classList.remove('is-enter');
      if (on) { void x.offsetWidth; x.classList.add('is-enter'); }
    });
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
    const vb = t.closest('[data-hc-view-btn]');
    if (vb) { switchView(vb.dataset.hcViz, vb.dataset.hcViewBtn); return; }
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
