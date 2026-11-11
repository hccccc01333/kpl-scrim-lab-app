/* 选手对比 · 可视化重构
   与「通用跨局分析」「英雄对比」「选手与位置」「教练档案」同一套语言：
   白底、大读数、一分析一形态、每卡两个可切换视图、悬停读数、点选换人。
   顶部沿用「对位深区」深墨蓝结论卡：结论式 H1 + 双人左右对位。
   数据：/api/v3/players-board 的 players（营地聚合与分位）+ games（逐局十人面板）。 */

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const es = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n0 = (v) => isNum(v) ? Math.round(v).toLocaleString('zh-CN') : '—';
const n1 = (v) => isNum(v) ? v.toFixed(1) : '—';
const pc = (v) => isNum(v) ? `${v.toFixed(1)}%` : '—';
const sg = (v) => { const r = Math.round(isNum(v) ? v : 0) || 0; return (r < 0 ? '−' : '+') + Math.abs(r).toLocaleString('zh-CN'); };
const sg1 = (v) => { const r = Math.round((isNum(v) ? v : 0) * 10) / 10 || 0; return (r < 0 ? '−' : '+') + Math.abs(r).toFixed(1); };
const tip = (t) => `data-pc-tip="${es(t)}"`;
const resWord = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '—';
const resCls = (r) => r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : 'is-none';

const VIEWS = {
  '01': ['八项对位', '谁赢哪项'],
  '02': ['分位雷达', '分位刻度'],
  '03': ['分位差排序', '各自强项'],
  '04': ['英雄重合', '英雄集中度'],
  '05': ['同场逐局', '同队与对位'],
  '06': ['逐局评分', '按天走势'],
  '07': ['评分分布', '最好与最差'],
};

const METRICS = [
  ['kda', 'KDA', (v) => n1(v), ''],
  ['gpm', '分均经济', (v) => n0(v), ' 金'],
  ['dpm', '分均输出', (v) => n0(v), ' 点'],
  ['participation', '参团率', (v) => pc(v), ' 个点'],
  ['damageShare', '输出占比', (v) => pc(v), ' 个点'],
  ['goldShare', '经济占比', (v) => pc(v), ' 个点'],
  ['takenShare', '承伤占比', (v) => pc(v), ' 个点'],
  ['dtpm', '分均承伤', (v) => n0(v), ' 点'],
];
const DIMS = [
  ['kda', 'KDA'], ['gpm', '分均经济'], ['dpm', '分均输出'],
  ['participation', '参团率'], ['damageShare', '输出占比'], ['takenShare', '承伤占比'],
];
const PCT_DIMS = [
  ['kda', 'KDA'], ['gpm', '分均经济'], ['dpm', '分均输出'],
  ['participation', '参团率'], ['damageShare', '输出占比'],
  ['goldShare', '经济占比'], ['takenShare', '承伤占比'],
];

export function createPlayerCompare({ esc = es, portrait = () => '' } = {}) {
  const state = { board: null, scope: 'all', lane: '', nameA: '', nameB: '', views: {} };

  const all = () => ((state.board && state.board.players) || []).filter((p) => (p.games || 0) >= 1);
  const pool = () => {
    const base = all();
    const narrow = base.filter((p) => (state.scope === 'all' || p.side === state.scope) && (!state.lane || p.lane === state.lane));
    return narrow.length >= 2 ? narrow : base;
  };
  const find = (n) => pool().find((p) => p.name === n);
  const viewOf = (id) => state.views[id] || 'a';
  const pctOf = (p, key) => (p && p.percent && isNum(p.percent[key]) ? p.percent[key] : null);
  const hrefOf = (name) => `#playerdetail/${encodeURIComponent(String(name == null ? '' : name))}`;

  /* ── 选手级派生量 ─────────────────────────────────────────── */
  function statOf(p) {
    const recent = (p.recent || []).slice();
    const chrono = recent.slice().reverse();
    const ratings = chrono.map((r) => r.rating).filter(isNum);
    const sorted = ratings.slice().sort((x, y) => x - y);
    const med = sorted.length
      ? (sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2)
      : null;
    const mean = ratings.length ? ratings.reduce((a, b) => a + b, 0) / ratings.length : null;
    const sd = ratings.length > 1 ? Math.sqrt(ratings.reduce((a, b) => a + (b - mean) ** 2, 0) / ratings.length) : null;
    const days = Object.keys((p.splits && p.splits.day) || {}).sort();
    return { recent, chrono, ratings, min: sorted.length ? sorted[0] : null, max: sorted.length ? sorted[sorted.length - 1] : null, med, mean, sd, days };
  }

  function sharedGames(a, b) {
    const out = [];
    for (const g of state.board.games || []) {
      const own = g.own || [], enemy = g.enemy || [];
      const ea = own.find((x) => x.name === a) || enemy.find((x) => x.name === a);
      const eb = own.find((x) => x.name === b) || enemy.find((x) => x.name === b);
      if (!ea || !eb) continue;
      const sameSide = (own.some((x) => x.name === a) && own.some((x) => x.name === b))
        || (enemy.some((x) => x.name === a) && enemy.some((x) => x.name === b));
      out.push({ game: g, ea, eb, sameSide });
    }
    return out.sort((x, y) => String(y.game.sort || '').localeCompare(String(x.game.sort || '')));
  }

  /* ── 通用零件 ─────────────────────────────────────────────── */
  function shell(id, va, vb) {
    const meta = VIEWS[id] || ['看图', '换个角度'];
    const cur = viewOf(id);
    const one = (k, html) => `<div class="hc-view${cur === k ? ' is-enter' : ''}" data-pc-view="${k}"${cur === k ? '' : ' hidden'}>${html}</div>`;
    return `<div class="hcv" data-pc-viz="${id}">
      <div class="hcv-bar"><div class="hcv-switch" role="group" aria-label="切换视图">
        <button type="button" data-pc-view-btn="a" data-pc-viz="${id}" class="${cur === 'a' ? 'is-on' : ''}">${es(meta[0])}</button>
        <button type="button" data-pc-view-btn="b" data-pc-viz="${id}" class="${cur === 'b' ? 'is-on' : ''}">${es(meta[1])}</button>
      </div></div>
      <div class="hcv-stage">${one('a', va)}${one('b', vb)}<div class="pcv-tip" hidden></div></div>
    </div>`;
  }
  const view = (big, body) => `<div class="hcv-view"><div class="hcv-hero">${big}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${es(v)}</b><span>${es(label)}</span></div>`;

  function card(id, name, title, chart, action, method, linkName) {
    return `<article class="hc-card" id="pc-analysis-${id}">
      <div class="hc-card-top"><span class="hc-kicker">${id} / 选手对比</span></div>
      <div class="hc-card-name">${es(name)}</div>
      <h3 class="hc-card-title">${title}</h3>
      <div class="hc-card-canvas">${chart}</div>
      <div class="hc-card-foot"><div class="hc-train"><span>怎么用</span><p>${es(action)}</p></div>
        <a class="hc-open" href="${esc(hrefOf(linkName))}">打开 ${es(linkName)} 档案 →</a></div>
      <p class="hc-method"><b>怎么算的</b> ${es(method)}</p>
    </article>`;
  }

  /* ── 01 指标对位分析 ──────────────────────────────────────── */
  function analysis01(a, b) {
    const rows = METRICS.map(([key, label, show]) => {
      const va = a[key], vb = b[key];
      const av = Math.abs(isNum(va) ? va : 0), bv = Math.abs(isNum(vb) ? vb : 0);
      const total = Math.max(1, av + bv);
      const wa = clamp(av / total * 100, 5, 95);
      const win = isNum(va) && isNum(vb) ? (va > vb ? 'a' : vb > va ? 'b' : '') : '';
      return `<div class="pc-tug-row" ${tip(`${label} · ${a.name} ${show(va)} 对 ${b.name} ${show(vb)}`)}>
        <span class="pc-tug-label">${esc(label)}</span>
        <b class="pc-tug-val a${win === 'a' ? ' is-win' : ''}">${show(va)}</b>
        <i class="pc-tug"><em class="a" style="width:${wa.toFixed(1)}%"></em><em class="b" style="width:${(100 - wa).toFixed(1)}%"></em></i>
        <b class="pc-tug-val b${win === 'b' ? ' is-win' : ''}">${show(vb)}</b>
      </div>`;
    }).join('');
    const A = view(big(`${METRICS.filter(([k]) => isNum(a[k]) && isNum(b[k]) && a[k] > b[k]).length} : ${METRICS.filter(([k]) => isNum(a[k]) && isNum(b[k]) && b[k] > a[k]).length}`,
      `${a.name} 与 ${b.name} 的八项领先比`, 'gold'),
      `<div class="pc-legend"><span><i class="a"></i>${esc(a.name)}</span><span><i class="b"></i>${esc(b.name)}</span></div><div class="pc-tugs">${rows}</div>`);
    const tiles = METRICS.map(([key, label, show, unit]) => {
      const va = a[key], vb = b[key];
      const d = isNum(va) && isNum(vb) ? va - vb : null;
      const who = d === null ? '' : d > 0 ? 'a' : d < 0 ? 'b' : '';
      const win = who === 'a' ? a.name : who === 'b' ? b.name : '持平';
      return `<div class="pc-tile ${who}" ${tip(`${label} · ${a.name} ${show(va)} / ${b.name} ${show(vb)}`)}>
        <span class="pc-tile-label">${esc(label)}</span>
        <b class="pc-tile-win">${esc(win)}</b>
        <em class="pc-tile-gap">${d === null ? '—' : `${d > 0 ? '多' : d < 0 ? '少' : '平'} ${d === 0 ? '' : show(Math.abs(d))}${d === 0 ? '' : unit}`}</em>
      </div>`;
    }).join('');
    const B = view(big(`${METRICS.filter(([k]) => isNum(a[k]) && isNum(b[k]) && a[k] !== b[k]).length} 项`, '八项里分出胜负的项数', 'teal'),
      `<div class="pc-tiles">${tiles}</div>`);
    return shell('01', A, B);
  }

  /* ── 02 位置分位分析 ──────────────────────────────────────── */
  function radar(a, b) {
    const size = 320, cx = size / 2, cy = size / 2 + 4, R = size / 2 - 54;
    const n = DIMS.length;
    const pt = (i, r) => {
      const ang = -Math.PI / 2 + i * 2 * Math.PI / n;
      return [cx + Math.cos(ang) * r, cy + Math.sin(ang) * r];
    };
    const ring = (k) => `<polygon class="pc-rad-ring${Math.abs(k - 0.5) < 1e-6 ? ' is-mid' : ''}" points="${DIMS.map((_, i) => pt(i, R * k).map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = DIMS.map((_, i) => { const [x, y] = pt(i, R); return `<line class="pc-rad-spoke" x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join('');
    const labels = DIMS.map(([key, label], i) => {
      const [x, y] = pt(i, R + 26);
      return `<text class="pc-rad-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${esc(label)}</text>`;
    }).join('');
    const series = [
      { p: a, cls: 'a' },
      { p: b, cls: 'b' },
    ];
    const poly = series.map((s) => {
      const vals = DIMS.map(([key]) => clamp(pctOf(s.p, key) ?? 0, 0, 100));
      return `<polygon class="pc-rad-area ${s.cls}" points="${vals.map((v, i) => pt(i, R * v / 100).map((x) => x.toFixed(1)).join(',')).join(' ')}"/>`;
    }).join('');
    const dots = series.map((s) => DIMS.map(([key, label], i) => {
      const v = pctOf(s.p, key);
      if (!isNum(v)) return '';
      const [x, y] = pt(i, R * clamp(v, 0, 100) / 100);
      return `<circle class="pc-rad-dot ${s.cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.8" ${tip(`${s.p.name} · ${label} 分位 ${n0(v)}`)}></circle>`;
    }).join('')).join('');
    return `<svg class="pc-rad-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="同位置分位雷达">
      ${[0.25, 0.5, 0.75, 1].map(ring).join('')}${spokes}${poly}${dots}
      <text class="pc-rad-tick" x="${cx + 8}" y="${(cy - R * 0.5 + 4).toFixed(1)}">50</text>${labels}
    </svg>`;
  }

  function analysis02(a, b) {
    const vals = DIMS.map(([key]) => [pctOf(a, key), pctOf(b, key)]).filter(([x, y]) => isNum(x) && isNum(y));
    const meanA = vals.length ? vals.reduce((s, [x]) => s + x, 0) / vals.length : null;
    const meanB = vals.length ? vals.reduce((s, [, y]) => s + y, 0) / vals.length : null;
    const A = view(big(n0(meanA), `平均分位 · ${b.name} 为 ${n0(meanB)}`, 'gold'),
      `<div class="pc-rad-wrap">${radar(a, b)}
        <div class="pc-legend"><span><i class="a"></i>${esc(a.name)}</span><span><i class="b"></i>${esc(b.name)}</span><em>外圈 = 同位置更靠前</em></div></div>`);
    const rows = DIMS.map(([key, label]) => {
      const pa = pctOf(a, key), pb = pctOf(b, key);
      if (!isNum(pa) && !isNum(pb)) return '';
      return `<div class="pc-ladder-row" ${tip(`${label} · ${a.name} 分位 ${n0(pa)} · ${b.name} 分位 ${n0(pb)}`)}>
        <span class="pc-ladder-label">${esc(label)}</span>
        <i class="pc-ladder"><em></em>
          ${isNum(pa) ? `<b class="a" style="left:${clamp(pa, 0, 100)}%"></b>` : ''}
          ${isNum(pb) ? `<b class="b" style="left:${clamp(pb, 0, 100)}%"></b>` : ''}
        </i>
        <b class="pc-ladder-val a">${isNum(pa) ? n0(pa) : '—'}</b>
        <b class="pc-ladder-val b">${isNum(pb) ? n0(pb) : '—'}</b>
      </div>`;
    }).join('');
    const B = view(big(`${vals.filter(([x, y]) => x > y).length} 项`, `${a.name} 分位高于 ${b.name} 的维度数`, 'teal'),
      `<div class="pc-ladders"><div class="pc-ladder-head"><span></span><span>0</span><span>50</span><span>100</span></div>${rows}</div>
       <div class="pc-legend"><span><i class="a"></i>${esc(a.name)}</span><span><i class="b"></i>${esc(b.name)}</span></div>`);
    return shell('02', A, B);
  }

  /* ── 03 强弱项分析 ────────────────────────────────────────── */
  function analysis03(a, b) {
    const diffs = PCT_DIMS.map(([key, label]) => ({
      key, label, pa: pctOf(a, key), pb: pctOf(b, key),
      d: (pctOf(a, key) ?? 0) - (pctOf(b, key) ?? 0),
    })).filter((x) => isNum(x.pa) && isNum(x.pb)).sort((x, y) => y.d - x.d);
    const maxAbs = Math.max(1, ...diffs.map((x) => Math.abs(x.d)));
    const rows = diffs.map((x) => {
      const w = Math.abs(x.d) / maxAbs * 50;
      const pos = x.d >= 0;
      return `<div class="pc-bip-row" ${tip(`${x.label} · ${a.name} 分位 ${n0(x.pa)} · ${b.name} 分位 ${n0(x.pb)}`)}>
        <span class="pc-bip-label">${esc(x.label)}</span>
        <i class="pc-bip"><em></em><b class="${pos ? 'a' : 'b'}" style="${pos ? 'left:50%' : 'right:50%'};width:${w.toFixed(1)}%"></b></i>
        <b class="pc-bip-val ${pos ? 'pos' : 'neg'}">${sg1(x.d)}</b>
        <small class="pc-bip-who">${esc(pos ? a.name : b.name)} 高</small>
      </div>`;
    }).join('');
    const top = diffs[0] || null;
    const A = view(big(top ? sg1(top.d) : '—', top ? `最大分位差 · ${top.label}（${a.name} − ${b.name}）` : '还没有分位样本', top && top.d < 0 ? 'teal' : 'gold'),
      `<div class="pc-bips">${rows}</div>
       <div class="pc-legend"><span><i class="a"></i>${esc(a.name)} 更强</span><span><i class="b"></i>${esc(b.name)} 更强</span></div>`);

    const best = (p) => PCT_DIMS.map(([key, label]) => ({ key, label, v: pctOf(p, key) })).filter((x) => isNum(x.v)).sort((x, y) => y.v - x.v);
    const la = best(a), lb = best(b);
    const quote = (p, item, weak, cls) => `<div class="pc-quote ${cls}${weak ? ' is-weak' : ''}">
      <span>${esc(p.name)} · ${weak ? '最弱一项' : '最强一项'}</span>
      <b>${esc(item ? item.label : '—')}</b>
      <em>分位 ${item ? n0(item.v) : '—'}</em></div>`;
    const B = view(big(`${la.length ? n0(la[0].v) : '—'} / ${lb.length ? n0(lb[0].v) : '—'}`, `两人的最强项分位（${a.name} / ${b.name}）`, 'teal'),
      `<div class="pc-quotes">
        ${quote(a, la[0], false, 'a')}${quote(a, la[la.length - 1], true, 'a')}
        ${quote(b, lb[0], false, 'b')}${quote(b, lb[lb.length - 1], true, 'b')}
      </div>`);
    return shell('03', A, B);
  }

  /* ── 04 英雄池分析 ────────────────────────────────────────── */
  function analysis04(a, b) {
    const listOf = (p) => (p.heroes || []).filter((x) => (x.games || 0) > 0).slice().sort((x, y) => (y.games || 0) - (x.games || 0));
    const la = listOf(a), lb = listOf(b);
    const mapA = new Map(la.map((x) => [x.hero, x]));
    const mapB = new Map(lb.map((x) => [x.hero, x]));
    const both = [...mapA.keys()].filter((h) => mapB.has(h));
    const onlyA = [...mapA.keys()].filter((h) => !mapB.has(h));
    const onlyB = [...mapB.keys()].filter((h) => !mapA.has(h));
    const chip = (h, games) => `<span class="pc-chip">${portrait(h)}<b>${esc(h)}</b><em>${n0(games)} 局</em></span>`;
    const A = view(big(`${both.length}`, `个英雄两人都用（${a.name} ${la.length} 个 / ${b.name} ${lb.length} 个）`, 'gold'),
      `<div class="pc-pool${both.length ? '' : ' is-lone'}">
        <div class="pc-pool-col"><b>仅 ${esc(a.name)}</b>${onlyA.slice(0, 8).map((h) => chip(h, mapA.get(h).games)).join('') || '<em class="pc-pool-empty">没有独用英雄</em>'}</div>
        <div class="pc-pool-col is-both"><b>两人都用</b>${both.map((h) => chip(h, Math.max(mapA.get(h).games, mapB.get(h).games))).join('') || '<div class="pc-pool-zero"><b>0</b><span>个重合英雄</span></div>'}</div>
        <div class="pc-pool-col"><b>仅 ${esc(b.name)}</b>${onlyB.slice(0, 8).map((h) => chip(h, mapB.get(h).games)).join('') || '<em class="pc-pool-empty">没有独用英雄</em>'}</div>
      </div>`);

    const conc = (list, p, cls) => {
      const total = Math.max(1, list.reduce((s, x) => s + (x.games || 0), 0));
      return `<div class="pc-conc-col ${cls}"><b>${esc(p.name)}<small>${n0(total)} 人次</small></b>
        ${list.slice(0, 6).map((x) => `<div class="pc-conc-row" ${tip(`${p.name} · ${x.hero} ${n0(x.games)} 局 · 占 ${pc(x.games / total * 100)}`)}>
          ${portrait(x.hero)}<span>${esc(x.hero)}</span>
          <i class="pc-conc"><em class="${cls}" style="width:${(x.games / total * 100).toFixed(1)}%"></em></i>
          <b>${pc(x.games / total * 100)}</b></div>`).join('')}
      </div>`;
    };
    const topShare = (list) => {
      const total = Math.max(1, list.reduce((s, x) => s + (x.games || 0), 0));
      return list.length ? list[0].games / total * 100 : null;
    };
    const B = view(big(pc(topShare(la)), `${a.name} 第一英雄占自己出场；${b.name} 为 ${pc(topShare(lb))}`, 'teal'),
      `<div class="pc-conc-grid">${conc(la, a, 'a')}${conc(lb, b, 'b')}</div>`);
    return shell('04', A, B);
  }

  /* ── 05 同场记录分析 ──────────────────────────────────────── */
  function analysis05(a, b) {
    const list = sharedGames(a.name, b.name);
    const same = list.filter((x) => x.sameSide);
    const vs = list.filter((x) => !x.sameSide);
    if (!list.length) {
      const empty = `<div class="pc-empty">两人还没有同场记录 —— 换一个对位，或先在采集里补齐同场对局。</div>`;
      return shell('05', view(big('0', '局同场', 'teal'), empty), view(big('—', '同队与对位', 'teal'), empty));
    }
    const rows = list.slice(0, 8).map((x) => {
      const g = x.game;
      const gap = (isNum(x.ea.gold) ? x.ea.gold : 0) - (isNum(x.eb.gold) ? x.eb.gold : 0);
      const line = (item, cls) => `<span class="pc-shared-line ${cls}"><span class="pc-shared-id">${portrait(item.hero)}<b>${esc(item.hero || '未知')}</b></span><em>KDA ${n1(item.kda)} · ${n0(item.gold)} 金</em></span>`;
      return `<div class="pc-shared-row" ${tip(`${g.day || ''} ${g.opponent || ''} · ${a.name} ${n0(x.ea.gold)} 金 / ${b.name} ${n0(x.eb.gold)} 金`)}>
        <span class="pc-shared-meta"><b>${esc((g.day || '').slice(5) || '—')}</b><em>${esc(g.opponent || '对手未标注')}</em><i class="${resCls(g.result)}">${resWord(g.result)}</i></span>
        ${line(x.ea, 'a')}
        <span class="pc-shared-gap ${gap >= 0 ? 'pos' : 'neg'}">${sg(gap)}</span>
        ${line(x.eb, 'b')}
      </div>`;
    }).join('');
    const A = view(big(`${list.length}`, `局同场 · 同队 ${same.length} 局 / 对位 ${vs.length} 局`, 'gold'),
      `<div class="pc-shared"><div class="pc-shared-head"><span></span><span>${esc(a.name)}</span><span>经济差</span><span>${esc(b.name)}</span></div>${rows}</div>`);

    const winRate = (arr, sideAName) => {
      let w = 0, n = 0;
      for (const x of arr) {
        const g = x.game;
        if (g.result !== 'win' && g.result !== 'loss') continue;
        const aInOwn = (g.own || []).some((p) => p.name === sideAName);
        const aWon = (g.result === 'win') === aInOwn;
        w += aWon ? 1 : 0; n += 1;
      }
      return n ? { w, n, rate: w / n * 100 } : { w: 0, n: 0, rate: null };
    };
    const st = winRate(same, a.name);
    const vh = vs.map((x) => {
      const g = x.game;
      const aInOwn = (g.own || []).some((p) => p.name === a.name);
      const aWon = (g.result === 'win') === aInOwn;
      const goldA = isNum(x.ea.gold) ? x.ea.gold : 0;
      const goldB = isNum(x.eb.gold) ? x.eb.gold : 0;
      return { aWon, goldA, goldB, lane: x.ea.lane || x.eb.lane || '' };
    });
    const vsA = vh.filter((x) => x.aWon).length;
    const vsGold = vh.length ? vh.reduce((s, x) => s + (x.goldA - x.goldB), 0) / vh.length : null;
    const pane = (title, count, html) => `<div class="pc-rel"><span>${esc(title)}</span><b>${count}</b>${html}</div>`;
    const B = view(big(`${same.length}`, `局同队，${vs.length} 局对位`, 'teal'),
      `<div class="pc-rels">
        ${pane(`${a.name} 与 ${b.name} 同队`, `${st.n} 局`, st.n
          ? `<em>同队胜率 ${pc(st.rate)}</em><i class="pc-rel-bar"><b class="a" style="width:${st.rate.toFixed(1)}%"></b></i>`
          : '<em>没有同队样本</em>')}
        ${pane('两人分在对立面', `${vs.length} 局`, vs.length
          ? `<em>${a.name} 赢 ${vsA} 局 / ${b.name} 赢 ${vs.length - vsA} 局</em><i class="pc-rel-bar is-vs"><b class="a" style="width:${(vsA / vs.length * 100).toFixed(1)}%"></b><b class="b" style="width:${((vs.length - vsA) / vs.length * 100).toFixed(1)}%"></b></i><em>对位经济差 ${sg(Math.round(vsGold))} 金</em>`
          : '<em>没有对位样本</em>')}
      </div>`);
    return shell('05', A, B);
  }

  /* ── 06 状态走势分析 ──────────────────────────────────────── */
  function lineSvg(series, opts) {
    const W = 720, H = 216, padL = 38, padR = 16, padT = 14, padB = 26;
    const values = series.flatMap((s) => s.pts.map((p) => p.y)).filter(isNum);
    if (!values.length) return '<div class="pc-empty">还没有逐局评分。</div>';
    const lo = Math.floor(Math.min(...values) - 1);
    const hi = Math.ceil(Math.max(...values) + 1);
    const maxLen = Math.max(1, ...series.map((s) => s.pts.length));
    const X = (i) => padL + (maxLen === 1 ? (W - padL - padR) / 2 : i / (maxLen - 1) * (W - padL - padR));
    const Y = (v) => padT + (1 - (v - lo) / Math.max(0.001, hi - lo)) * (H - padT - padB);
    const grid = [0, 0.25, 0.5, 0.75, 1].map((k) => {
      const y = padT + k * (H - padT - padB);
      const v = hi - k * (hi - lo);
      return `<line class="pc-line-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>
        <text class="pc-line-tick" x="${padL - 8}" y="${(y + 3.4).toFixed(1)}" text-anchor="end">${v.toFixed(1)}</text>`;
    }).join('');
    const paths = series.map((s) => {
      const pts = s.pts.filter((p) => isNum(p.y));
      if (!pts.length) return '';
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(s.pts.indexOf(p)).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(' ');
      const dots = pts.map((p) => `<circle class="pc-line-dot ${s.cls}" cx="${X(s.pts.indexOf(p)).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.4" ${tip(p.tip)}></circle>`).join('');
      return `<path class="pc-line-path ${s.cls}" d="${d}" fill="none"/>${dots}`;
    }).join('');
    const xLabels = (opts && opts.xLabels) || [];
    const labels = xLabels.slice(0, maxLen).map((t, i) =>
      `<text class="pc-line-tick" x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(t)}</text>`).join('');
    return `<svg class="pc-line-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="逐局评分走势">${grid}${paths}${labels}</svg>`;
  }

  function analysis06(a, b) {
    const sa = statOf(a), sb = statOf(b);
    const len = Math.max(sa.chrono.length, sb.chrono.length);
    const serA = { cls: 'a', pts: sa.chrono.slice(-12).map((r, i) => ({ y: r.rating, tip: `${a.name} · ${r.day || ''} ${r.hero || ''} · 评分 ${n1(r.rating)} · ${resWord(r.result)}` })) };
    const serB = { cls: 'b', pts: sb.chrono.slice(-12).map((r) => ({ y: r.rating, tip: `${b.name} · ${r.day || ''} ${r.hero || ''} · 评分 ${n1(r.rating)} · ${resWord(r.result)}` })) };
    const lastA = sa.chrono.length ? sa.chrono[sa.chrono.length - 1].rating : null;
    const lastB = sb.chrono.length ? sb.chrono[sb.chrono.length - 1].rating : null;
    const formWord = (p) => {
      const f = p.form || {};
      if (!f.available) return '样本不足';
      return f.tone === 'up' ? '在上升' : f.tone === 'down' ? '在下滑' : '基本持平';
    };
    const A = view(big(`${n1(lastA)} / ${n1(lastB)}`, `最近一局评分 · ${a.name} / ${b.name}`, (lastA || 0) >= (lastB || 0) ? 'gold' : 'teal'),
      `${lineSvg([serA, serB], {})}
       <div class="pc-legend"><span><i class="a"></i>${esc(a.name)} ${esc(formWord(a))}</span><span><i class="b"></i>${esc(b.name)} ${esc(formWord(b))}</span></div>`);

    const days = [...new Set([...sa.days, ...sb.days])].sort();
    const dayPts = (p) => days.map((d) => {
      const row = (p.splits && p.splits.day && p.splits.day[d]) || null;
      return row && isNum(row.games) ? { y: row.rating, tip: `${p.name} · ${d} · ${n0(row.games)} 局 · 评分 ${n1(row.rating)} · 胜率 ${pc(row.winRate)}` } : null;
    }).filter(Boolean);
    const dsA = { cls: 'a', pts: dayPts(a) };
    const dsB = { cls: 'b', pts: dayPts(b) };
    const B = view(big(`${days.length}`, `天有记录 · ${days[0] || '—'} 起`, 'teal'),
      days.length >= 2
        ? `${lineSvg([dsA, dsB], { xLabels: days.map((d) => String(d).slice(5)) })}
           <div class="pc-legend"><span><i class="a"></i>${esc(a.name)} 按天评分</span><span><i class="b"></i>${esc(b.name)} 按天评分</span></div>`
        : `<div class="pc-empty">只有 ${days.length} 天记录，按天走势还看不出来。</div>`);
    return shell('06', A, B);
  }

  /* ── 07 稳定性分析 ────────────────────────────────────────── */
  function analysis07(a, b) {
    const sa = statOf(a), sb = statOf(b);
    const vals = [...sa.ratings, ...sb.ratings];
    const lo = vals.length ? Math.floor(Math.min(...vals)) : 0;
    const hi = vals.length ? Math.ceil(Math.max(...vals)) : 12;
    const span = Math.max(1, hi - lo);
    const step = span <= 10 ? 1 : 2;
    const bins = Math.max(1, Math.ceil(span / step));
    const bucket = (arr) => {
      const out = new Array(bins).fill(0);
      for (const v of arr) out[clamp(Math.floor((v - lo) / step), 0, bins - 1)] += 1;
      return out;
    };
    const ha = bucket(sa.ratings), hb = bucket(sb.ratings);
    const peak = Math.max(1, ...ha, ...hb);
    const hist = `<div class="pc-hist" style="grid-template-columns:repeat(${bins},minmax(0,1fr))">${Array.from({ length: bins }, (_, i) => {
      const from = lo + i * step, to = from + step;
      return `<div class="pc-hist-col" ${tip(`${from.toFixed(1)}–${to.toFixed(1)} 分 · ${a.name} ${ha[i]} 局 / ${b.name} ${hb[i]} 局`)}>
        <span class="pc-hist-bars">
          <i class="a" style="height:${Math.max(2, ha[i] / peak * 100)}%"></i>
          <i class="b" style="height:${Math.max(2, hb[i] / peak * 100)}%"></i>
        </span>
        <em>${from.toFixed(0)}</em>
      </div>`;
    }).join('')}</div>`;
    const A = view(big(`${n1(sa.sd)} / ${n1(sb.sd)}`, `评分波动（标准差）· ${a.name} / ${b.name}`, (sa.sd || 0) <= (sb.sd || 0) ? 'gold' : 'teal'),
      `${hist}<div class="pc-legend"><span><i class="a"></i>${esc(a.name)} ${sa.ratings.length} 局</span><span><i class="b"></i>${esc(b.name)} ${sb.ratings.length} 局</span><span>横轴为每局评分</span></div>`);

    const axisLo = vals.length ? Math.min(lo, 0) : 0;
    const axisHi = hi || 12;
    const pos = (v) => clamp((v - axisLo) / Math.max(0.001, axisHi - axisLo) * 100, 0, 100);
    const rangeRow = (p, st, cls) => {
      if (!isNum(st.min)) return `<div class="pc-range-row"><span>${esc(p.name)}</span><i class="pc-range"></i><b>—</b></div>`;
      const l = pos(st.min), r = pos(st.max);
      return `<div class="pc-range-row">
        <span>${esc(p.name)}</span>
        <i class="pc-range"><em class="${cls}" style="left:${l.toFixed(1)}%;width:${Math.max(1.5, r - l).toFixed(1)}%"></em>
          ${isNum(st.med) ? `<b class="${cls}" style="left:${pos(st.med).toFixed(1)}%"></b>` : ''}</i>
        <b>${n1(st.min)} – ${n1(st.max)}</b>
      </div>`;
    };
    const B = view(big(`${n1(sa.min)}–${n1(sa.max)}`, `${a.name} 的评分区间；中位 ${n1(sa.med)}`, 'teal'),
      `<div class="pc-ranges">${rangeRow(a, sa, 'a')}${rangeRow(b, sb, 'b')}</div>
       <div class="pc-range-axis"><span>${axisLo.toFixed(0)}</span><span>中位竖线</span><span>${axisHi.toFixed(0)}</span></div>`);
    return shell('07', A, B);
  }

  /* ── 深墨蓝结论卡 ─────────────────────────────────────────── */
  function head(a, b) {
    const opts = (value) => {
      const group = (list, label) => {
        const rows = list.slice().sort((x, y) => (y.games || 0) - (x.games || 0) || (y.score || 0) - (x.score || 0))
          .map((x) => `<option value="${esc(x.name)}"${x.name === value ? ' selected' : ''}>${esc(x.name)} · ${esc(x.lane || '位置未知')} · ${n0(x.games)} 局</option>`).join('');
        return rows ? `<optgroup label="${label}">${rows}</optgroup>` : '';
      };
      return `${group(pool().filter((p) => p.side === 'own'), '本队侧')}${group(pool().filter((p) => p.side === 'enemy'), '对手侧')}`;
    };
    const marks = METRICS.map(([key]) => ({ key, has: isNum(a[key]) && isNum(b[key]), d: (isNum(a[key]) ? a[key] : 0) - (isNum(b[key]) ? b[key] : 0) }));
    const aWins = marks.filter((x) => x.has && x.d > 0).length;
    const bWins = marks.filter((x) => x.has && x.d < 0).length;
    const best = METRICS.map(([key, label, show]) => ({ key, label, show, d: (isNum(a[key]) ? a[key] : 0) - (isNum(b[key]) ? b[key] : 0) }))
      .filter((x) => isNum(a[x.key]) && isNum(b[x.key]))
      .sort((x, y) => Math.abs(y.d) - Math.abs(x.d))[0] || null;
    const totalGames = all().reduce((s, p) => s + (p.games || 0), 0);
    const mono = (name, cls) => `<span class="pc-mono ${cls}">${esc(String(name || '?').trim().slice(0, 1) || '?')}</span>`;
    const side = (p, cls, which) => `<div class="hc-duel-side ${cls}">
      <div class="hc-duel-id">${mono(p.name, cls)}<div><span>选手 ${which}</span><b>${esc(p.name)}</b><small>${esc(p.lane || '位置未知')} · ${n0(p.games)} 局 · 胜率 ${pc(p.winRate)}</small></div></div>
      <div class="hc-duel-num"><b>${n1(p.score)}</b><span>表现分</span></div>
      <select data-pc-select="${which === 'A' ? 'a' : 'b'}" aria-label="选手 ${which}">${opts(which === 'A' ? a.name : b.name)}</select>
    </div>`;
    const claim = aWins === bWins
      ? `两人八项各领先 <em>${aWins}</em> 项，差距最大的是${esc(best ? best.label : '—')}`
      : `${esc(aWins > bWins ? a.name : b.name)} 八项里领先 <em>${Math.max(aWins, bWins)}</em> 项`;
    const fact = best
      ? `差距最大的是${esc(best.label)}：${esc(a.name)} <em>${best.show(a[best.key])}</em> 对 ${esc(b.name)} ${best.show(b[best.key])}；${a.lane === b.lane ? '同位置对比，分位可直接横着读' : '两人不在同一位置，分位以各自位置为基准'}`
      : '';
    return `<section class="hc-hero pc-hero">
      <div class="hc-hero-top"><span class="hc-hero-kicker">选手对比 / 营地十人面板</span>
        <span class="hc-hero-scope">${n0(all().length)} 名选手 · ${n0((state.board.games || []).length)} 局 · ${n0(totalGames)} 人次</span></div>
      <div class="hc-duel">${side(a, 'a', 'A')}
        <div class="hc-vs"><span>VS</span><i></i><b>${aWins} : ${bWins}</b><small>八项领先</small></div>
        ${side(b, 'b', 'B')}</div>
      <h2 class="hc-claim">${claim}</h2>
      <p class="hc-fact">${fact}</p>
    </section>`;
  }

  /* ── 页面 ─────────────────────────────────────────────────── */
  const NAMES = ['指标对位分析', '位置分位分析', '强弱项分析', '英雄池分析', '同场记录分析', '状态走势分析', '稳定性分析'];

  function initKeys() {
    const list = pool().slice().sort((x, y) => (y.games || 0) - (x.games || 0) || (y.score || 0) - (x.score || 0));
    const solid = list.filter((p) => (p.games || 0) >= 2);
    const pick = solid.length >= 2 ? solid : list;
    if (!find(state.nameA)) state.nameA = (pick[0] || {}).name || '';
    if (!find(state.nameB) || state.nameB === state.nameA) {
      const alt = pick.find((p) => p.name !== state.nameA) || list.find((p) => p.name !== state.nameA);
      state.nameB = (alt || {}).name || state.nameA;
    }
  }

  function render(value) {
    if (value) state.board = value;
    if (!state.board) return '<div class="page"><div class="loading">正在汇总选手面板…</div></div>';
    initKeys();
    const a = find(state.nameA), b = find(state.nameB);
    if (!a || !b || a === b) {
      return `<div class="page hc-page pc-page"><div class="page-intro hc-intro"><div><h1>选手对比</h1><p>两个人摆在一起，看谁更强、强在哪、能不能互换。</p></div></div>
        <div class="empty">当前筛选下不足两名选手，放宽对路或阵营再看。</div></div>`;
    }
    const sa = statOf(a), sb = statOf(b);
    const best = METRICS.map(([key, label, show]) => ({ key, label, show, d: (isNum(a[key]) ? a[key] : 0) - (isNum(b[key]) ? b[key] : 0) }))
      .filter((x) => isNum(a[x.key]) && isNum(b[x.key])).sort((x, y) => Math.abs(y.d) - Math.abs(x.d))[0] || null;
    const pcDiffs = PCT_DIMS.map(([key, label]) => ({ key, label, d: (pctOf(a, key) ?? 0) - (pctOf(b, key) ?? 0) }))
      .filter((x) => isNum(pctOf(a, x.key)) && isNum(pctOf(b, x.key)))
      .sort((x, y) => Math.abs(y.d) - Math.abs(x.d));
    const pcTop = pcDiffs[0] || null;
    const meanPct = (p) => {
      const vals = DIMS.map(([k]) => pctOf(p, k)).filter(isNum);
      return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
    };
    const poolNames = pool().map((p) => p.name).filter((x) => x !== a.name && x !== b.name);
    const reach = poolNames.length ? poolNames.slice(0, 3) : [];
    const cards = [
      card('01', NAMES[0],
        best ? `八项里 <em>${esc((isNum(a[best.key]) && a[best.key] >= b[best.key]) ? a.name : b.name)}</em> 领先，${esc(best.label)}差得最多` : '八项对位',
        analysis01(a, b),
        `把领先项固化成主选理由，落后项直接排进下一轮专项。`,
        '八项均为该选手全部出场局的均值或比率；两个名字并排，行内按两者最大值分色。', a.name),
      card('02', NAMES[1],
        `平均分位 <em>${n0(meanPct(a))}</em> 对 <em>${n0(meanPct(b))}</em>，${esc((meanPct(a) || 0) >= (meanPct(b) || 0) ? a.name : b.name)} 更靠前`,
        analysis02(a, b),
        `分位低的维度就是这名选手的训练缺口，按维度排周计划。`,
        '分位为该选手在同位置全部选手中的百分位（0–100），跨位置不比较。', a.name),
      card('03', NAMES[2],
        pcTop ? `最大差距在${esc(pcTop.label)}：<em>${sg1(pcTop.d)}</em> 个分位，${esc(pcTop.d >= 0 ? a.name : b.name)} 更强` : '强弱项',
        analysis03(a, b),
        `一人补最弱项，另一人把最强项做成战术发起点。`,
        '分位差 = A 的分位 − B 的分位，正数表示 A 更强；只比两人都有样本的维度。', a.name),
      card('04', NAMES[3],
        `两人共用 <em>${(a.heroes || []).filter((x) => (b.heroes || []).some((y) => y.hero === x.hero)).length}</em> 个英雄，${esc(a.name)} 用 <em>${n0((a.heroes || []).length)}</em> 个 / ${esc(b.name)} <em>${n0((b.heroes || []).length)}</em> 个`,
        analysis04(a, b),
        `重合多说明可直接互换，重合少说明轮换要提前排英雄池。`,
        '英雄池取营地面板里出现过出场局的英雄；集中度 = 该英雄出场 ÷ 本人全部出场。', a.name),
      card('05', NAMES[4],
        `同场 <em>${sharedGames(a.name, b.name).length}</em> 局，其中同队 <em>${sharedGames(a.name, b.name).filter((x) => x.sameSide).length}</em> 局`,
        analysis05(a, b),
        `同队局看配合，对位局看谁在直接交手里占上风。`,
        '同场 = 同一局十人面板里两人都出现；经济差 = A 终局经济 − B 终局经济。', a.name),
      card('06', NAMES[5],
        `最近一局 <em>${n1(sa.chrono.length ? sa.chrono[sa.chrono.length - 1].rating : null)}</em> 对 <em>${n1(sb.chrono.length ? sb.chrono[sb.chrono.length - 1].rating : null)}</em>`,
        analysis06(a, b),
        `两人都在上升就一起加练，一升一降先把下滑那位排进复盘。`,
        '评分取营地每局结算评分；走势按时间从左到右，两轴同尺度。', a.name),
      card('07', NAMES[6],
        `评分区间 <em>${n1(sa.min)}–${n1(sa.max)}</em> 对 <em>${n1(sb.min)}–${n1(sb.max)}</em>，波动 <em>${n1(sa.sd)}</em> / ${n1(sb.sd)}`,
        analysis07(a, b),
        `波动大的一位先求稳：把最容易崩的那类局挑出来单练。`,
        '取最近至多 12 局的营地评分，标准差衡量波动；区间条两端为最低与最高。', a.name),
    ].join('');
    const count = pool().length;
    return `<div class="page hc-page pc-page">
      <div class="page-intro hc-intro"><div><h1>选手对比</h1><p>两个人摆在一起：谁更强、强在哪、能不能互换。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>
      ${head(a, b)}
      <div class="hc-toolbar">
        <label class="hc-filter"><span>对路</span><select data-pc-lane aria-label="对路">
          <option value="">全部位置</option>${['对抗路', '打野', '中路', '发育路', '游走'].map((l) => `<option value="${esc(l)}"${state.lane === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
        <label class="hc-filter"><span>阵营</span><select data-pc-scope aria-label="阵营">
          <option value="all"${state.scope === 'all' ? ' selected' : ''}>全部</option>
          <option value="own"${state.scope === 'own' ? ' selected' : ''}>本队侧</option>
          <option value="enemy"${state.scope === 'enemy' ? ' selected' : ''}>对手侧</option></select></label>
        <span class="hc-toolbar-count">当前 ${n0(count)} 名选手 · 点任意条形或方块可换到右侧${reach.length ? ` · 试试 ${reach.map((x) => `<button type="button" class="pc-reach" data-pc-pick="${esc(x)}">${esc(x)}</button>`).join('')}` : ''}</span>
      </div>
      <div class="hc-index" role="group" aria-label="分析直达">${NAMES.map((x, i) => `<button type="button" data-pc-jump="0${i + 1}">${esc(x)}</button>`).join('')}</div>
      <section class="hc-cards">${cards}</section>
      <p class="hc-source">数据来源：王者营地十人面板与逐局结算；分位只在同位置内计算，跨位置只比原始值。</p>
    </div>`;
  }

  /* ── 交互 ─────────────────────────────────────────────────── */
  function rerender() {
    const page = document.querySelector('.pc-page');
    if (page) page.outerHTML = render(null);
  }
  function switchView(id, key) {
    state.views[id] = key;
    const wrap = [...document.querySelectorAll('[data-pc-viz]')].find((el) => el.dataset.pcViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-pc-view-btn]').forEach((x) => x.classList.toggle('is-on', x.dataset.pcViewBtn === key));
    wrap.querySelectorAll('.hc-view').forEach((x) => {
      const on = x.dataset.pcView === key;
      x.hidden = !on;
      x.classList.remove('is-enter');
      if (on) { void x.offsetWidth; x.classList.add('is-enter'); }
    });
  }
  function showTip(target, event) {
    const wrap = target.closest('[data-pc-viz]');
    if (!wrap) return;
    const box = wrap.querySelector('.pcv-tip'), stage = wrap.querySelector('.hcv-stage');
    if (!box || !stage) return;
    box.textContent = target.dataset.pcTip || '';
    box.hidden = false;
    const r = stage.getBoundingClientRect();
    box.style.left = `${clamp(event.clientX - r.left + 12, 8, Math.max(8, r.width - 250))}px`;
    box.style.top = `${clamp(event.clientY - r.top - 38, 6, Math.max(6, r.height - 40))}px`;
  }

  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.pc-page')) return;
    const jump = t.closest('[data-pc-jump]');
    if (jump) { const el = document.getElementById(`pc-analysis-${jump.dataset.pcJump}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const vb = t.closest('[data-pc-view-btn]');
    if (vb) { switchView(vb.dataset.pcViz, vb.dataset.pcViewBtn); return; }
    const pick = t.closest('[data-pc-pick]');
    if (pick && pick.dataset.pcPick) {
      state.nameB = pick.dataset.pcPick;
      if (state.nameB === state.nameA) {
        const alt = pool().find((x) => x.name !== state.nameA);
        if (alt) state.nameB = alt.name;
      }
      rerender();
    }
  });
  document.addEventListener('change', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.pc-page')) return;
    if (t.dataset.pcSelect) {
      if (t.dataset.pcSelect === 'a') {
        state.nameA = t.value;
        if (state.nameA === state.nameB) { const alt = pool().find((x) => x.name !== t.value); if (alt) state.nameB = alt.name; }
      } else {
        state.nameB = t.value;
        if (state.nameB === state.nameA) { const alt = pool().find((x) => x.name !== t.value); if (alt) state.nameA = alt.name; }
      }
      rerender();
      return;
    }
    if (t.hasAttribute('data-pc-lane')) { state.lane = t.value; rerender(); return; }
    if (t.hasAttribute('data-pc-scope')) { state.scope = t.value; rerender(); }
  });
  document.addEventListener('mousemove', (event) => {
    const t = event.target.closest ? event.target.closest('[data-pc-tip]') : null;
    if (t && t.closest('.pc-page')) showTip(t, event);
    else document.querySelectorAll('.pcv-tip').forEach((x) => { x.hidden = true; });
  });

  return { render };
}
