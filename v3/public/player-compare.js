/* 选手对比 · v4
   KPL 红蓝对决语言：红方 A / 蓝方 B，浅白底，结论先行。
   五张分析卡：位置指标 / 位置排名 / 英雄池 / 状态走势 / 最好与最差。
   同位置优先配对（仍可手动跨位置对比）；筛选与目录合并为一条吸顶工具条。
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

const METRICS = [
  ['kda', 'KDA', (v) => n1(v)],
  ['gpm', '分均经济', (v) => n0(v)],
  ['dpm', '分均输出', (v) => n0(v)],
  ['participation', '参团率', (v) => pc(v)],
  ['damageShare', '输出占比', (v) => pc(v)],
  ['goldShare', '经济占比', (v) => pc(v)],
  ['takenShare', '承伤占比', (v) => pc(v)],
  ['dtpm', '分均承伤', (v) => n0(v)],
];
const METRIC = Object.fromEntries(METRICS.map((m) => [m[0], m]));
/* 不同位置看的指标不一样：游走看参团与承伤，输出位看输出与经济。 */
const ROLE_METRICS = {
  '游走': ['participation', 'takenShare', 'dtpm', 'kda'],
  '辅助': ['participation', 'takenShare', 'dtpm', 'kda'],
  '中路': ['dpm', 'damageShare', 'kda', 'participation', 'gpm'],
  '打野': ['gpm', 'participation', 'kda', 'dpm'],
  '发育路': ['dpm', 'damageShare', 'gpm', 'kda', 'participation'],
  '对抗路': ['takenShare', 'dtpm', 'dpm', 'kda', 'participation'],
};
const DIMS = [
  ['kda', 'KDA'], ['gpm', '分均经济'], ['dpm', '分均输出'],
  ['participation', '参团率'], ['damageShare', '输出占比'], ['takenShare', '承伤占比'],
];

export function createPlayerCompare({ esc = es, portrait = () => '' } = {}) {
  const state = { board: null, scope: 'all', lane: '', nameA: '', nameB: '', source: 'own', team: '' };

  const rawAll = () => ((state.board && state.board.players) || []).filter((p) => (p.games || 0) >= 1);
  /* 对比数据源：本队 / KPL / 指定战队。
     - 本队：board 里 side=own 的选手；
     - 指定战队：取每名本队选手对该队的逐场切片（board.players[].splits.opponent）；
     - KPL：当前 players-board 不含 KPL 选手逐局样本，按 0 显示，不拿别的数据冒充。
     没有样本的指标一律显示 0，不显示「—」。 */
  const all = () => {
    const base = rawAll();
    if (state.source === 'team') {
      return base.map((p) => {
        const split = (p.splits && p.splits.opponent && p.splits.opponent[state.team]) || null;
        if (!split || !(split.games || 0)) return null;
        return {...p, games: split.games || 0, wins: split.wins || 0, decided: split.decided || 0,
          winRate: split.winRate, kda: split.kda, gpm: split.gpm, dpm: split.dpm,
          participation: split.participation, damageShare: split.damageShare, rating: split.rating,
          recent: [], form: null, percent: p.percent, score: p.score};
      }).filter(Boolean);
    }
    if (state.source === 'kpl') return [];
    return base.filter((p) => p.side === 'own');
  };
  const sourceBar = () => `<label class="hc-filter"><span>数据源</span><select data-pc-source aria-label="对比数据源">
      <option value="own"${state.source === 'own' ? ' selected' : ''}>自家</option>
      <option value="kpl"${state.source === 'kpl' ? ' selected' : ''}>KPL</option>
      <option value="team"${state.source === 'team' ? ' selected' : ''}>指定战队</option></select></label>
    ${state.source === 'team' ? `<label class="hc-filter"><span>战队</span><select data-pc-team aria-label="指定战队">
      ${((state.board && state.board.opponents) || []).map((o) => `<option value="${esc(o.name)}"${state.team === o.name ? ' selected' : ''}>${esc(o.name)}</option>`).join('')}</select></label>` : ''}`;
  const pool = () => {
    const base = all();
    const narrow = base.filter((p) => (state.scope === 'all' || p.side === state.scope) && (!state.lane || p.lane === state.lane));
    return narrow.length >= 2 ? narrow : base;
  };
  const find = (n) => pool().find((p) => p.name === n);
  const pctOf = (p, key) => (p && p.percent && isNum(p.percent[key]) ? p.percent[key] : null);

  /* ── 派生量 ─────────────────────────────────────────────────── */
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
    return { recent, chrono, ratings, min: sorted.length ? sorted[0] : null, max: sorted.length ? sorted[sorted.length - 1] : null, med, mean, sd };
  }

  /* 把「分位」翻成教练组看得懂的「同位置第几 / 共几人」。 */
  function rankOf(p, key) {
    if (!isNum(p && p[key])) return null;
    const peers = all().filter((x) => x.lane === p.lane && isNum(x[key]));
    if (peers.length < 2) return null;
    const ahead = peers.filter((x) => x[key] > p[key]).length;
    return { rank: ahead + 1, total: peers.length };
  }
  function rankSummary(p) {
    const rs = DIMS.map(([k]) => rankOf(p, k)).filter(Boolean);
    if (!rs.length) return null;
    return {
      rank: rs.reduce((s, x) => s + x.rank, 0) / rs.length,
      total: rs.reduce((s, x) => s + x.total, 0) / rs.length,
    };
  }

  function metricsFor(a, b) {
    const sa = ROLE_METRICS[a.lane], sb = ROLE_METRICS[b.lane];
    let keys;
    if (a.lane && a.lane === b.lane && sa) keys = sa.slice();
    else if (sa && sb) keys = [...new Set([...sa, ...sb])];
    else keys = METRICS.map(([k]) => k);
    return keys.filter((k) => METRIC[k]).map((k) => METRIC[k]);
  }

  /* ── 通用零件 ───────────────────────────────────────────────── */
  function shell(id, panes) {
    const body = panes.map(([label, html], i) => `<section class="hcv-pane${i ? ' is-b' : ''}"><div class="hcv-pane-cap"><span class="hcv-pane-no">${es(id)}</span>${es(label)}</div>${html}</section>`).join('');
    return `<div class="hcv" data-pc-viz="${id}"><div class="hcv-stage">${body}<div class="pcv-tip" hidden></div></div></div>`;
  }
  const view = (big, body) => `<div class="hcv-view"><div class="hcv-hero">${big}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${es(v)}</b><span>${es(label)}</span></div>`;

  function card(id, name, title, chart) {
    return `<article class="hc-card" id="pc-analysis-${id}">
      <div class="hc-card-head">
        <div class="hc-card-heading"><span class="hc-card-no">${id}</span><div>
          <span class="hc-card-name">${es(name)}</span>
          <h3 class="hc-card-title">${title}</h3>
        </div></div>
      </div>
      <div class="hc-card-canvas">${chart}</div>
    </article>`;
  }

  /* ── 01 位置指标对位：去掉细横条，数字放大、赢家就地高亮 ───────── */
  function analysis01(a, b) {
    const mets = metricsFor(a, b);
    let leadA = 0, leadB = 0;
    const rows = mets.map(([key, label, show]) => {
      const va = a[key], vb = b[key];
      const ok = isNum(va) && isNum(vb);
      const win = ok ? (va > vb ? 'a' : vb > va ? 'b' : '') : '';
      if (win === 'a') leadA++; else if (win === 'b') leadB++;
      return `<div class="pc-vs-row ${win}" ${tip(`${label} · ${a.name} ${show(va)} / ${b.name} ${show(vb)}`)}>
        <span class="pc-vs-key">${esc(label)}</span>
        <b class="pc-vs-val a${win === 'a' ? ' is-win' : ''}">${show(va)}${win === 'a' ? '<i>领先</i>' : ''}</b>
        <b class="pc-vs-val b${win === 'b' ? ' is-win' : ''}">${show(vb)}${win === 'b' ? '<i>领先</i>' : ''}</b>
      </div>`;
    }).join('');
    const head = `<div class="pc-vs-head"><span>本位置指标</span><b class="a">${esc(a.name)}</b><b class="b">${esc(b.name)}</b></div>`;
    const label = mets.length > 4 ? `${esc(a.lane || '位置')}看这些指标` : '按位置挑的指标';
    return shell('01', [[label, view(
      big(`${leadA} : ${leadB}`, `本位置指标领先项 · ${a.name} / ${b.name}`, leadA === leadB ? '' : leadA > leadB ? 'red' : 'blue'),
      `<div class="pc-vs-table">${head}${rows}</div>`
    )]]);
  }

  /* ── 02 位置排名：雷达保留，分位全部翻成「第几 / 共几人」 ─────── */
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
    const series = [{ p: a, cls: 'a' }, { p: b, cls: 'b' }];
    const poly = series.map((s) => {
      const vals = DIMS.map(([key]) => clamp(pctOf(s.p, key) ?? 0, 0, 100));
      return `<polygon class="pc-rad-area ${s.cls}" points="${vals.map((v, i) => pt(i, R * v / 100).map((x) => x.toFixed(1)).join(',')).join(' ')}"/>`;
    }).join('');
    const dots = series.map((s) => DIMS.map(([key, label], i) => {
      const v = pctOf(s.p, key);
      if (!isNum(v)) return '';
      const [x, y] = pt(i, R * clamp(v, 0, 100) / 100);
      const rk = rankOf(s.p, key);
      const rankText = rk ? `同位置第 ${rk.rank} / ${rk.total}` : '排名样本不足';
      return `<circle class="pc-rad-dot ${s.cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.8" ${tip(`${s.p.name} · ${label} · ${rankText}`)}></circle>`;
    }).join('')).join('');
    return `<svg class="pc-rad-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="同位置排名雷达">
      ${[0.25, 0.5, 0.75, 1].map(ring).join('')}${spokes}${poly}${dots}${labels}
    </svg>`;
  }

  function analysis02(a, b) {
    const ra = rankSummary(a), rb = rankSummary(b);
    const avg = ra && rb ? `第 ${n0(ra.rank)} / 第 ${n0(rb.rank)}` : '—';
    const A = view(big(avg, `同位置平均排名 · ${a.name} / ${b.name}`, ra && rb && ra.rank < rb.rank ? 'red' : 'blue'),
      `<div class="pc-rad-wrap">${radar(a, b)}<div class="pc-legend"><span><i class="a"></i>${esc(a.name)}</span><span><i class="b"></i>${esc(b.name)}</span></div></div>`);

    const rows = DIMS.map(([key, label]) => {
      const rka = rankOf(a, key), rkb = rankOf(b, key);
      const pos = (r) => r && r.total > 1 ? clamp((r.rank - 1) / (r.total - 1) * 100, 0, 100) : 50;
      const win = rka && rkb ? (rka.rank < rkb.rank ? 'a' : rkb.rank < rka.rank ? 'b' : '') : '';
      return `<div class="pc-ladder-row ${win}" ${tip(`${label} · ${a.name} 同位置第 ${rka ? rka.rank : '—'} / ${rka ? rka.total : '—'} 人 · ${b.name} 第 ${rkb ? rkb.rank : '—'} / ${rkb ? rkb.total : '—'} 人`)}>
        <span class="pc-ladder-label">${esc(label)}</span>
        <i class="pc-ladder"><em></em>
          ${rka ? `<b class="a" style="left:${pos(rka).toFixed(1)}%"></b>` : ''}
          ${rkb ? `<b class="b" style="left:${pos(rkb).toFixed(1)}%"></b>` : ''}
        </i>
        <b class="pc-ladder-val a">${rka ? `第${n0(rka.rank)}` : '—'}</b>
        <b class="pc-ladder-val b">${rkb ? `第${n0(rkb.rank)}` : '—'}</b>
      </div>`;
    }).join('');
    const better = ra && rb ? (ra.rank < rb.rank ? a.name : rb.rank < ra.rank ? b.name : '两人持平') : '样本不足';
    const B = view(big(esc(better), '同位置平均排名更靠前的一方', 'blue'),
      `<div class="pc-ladders"><div class="pc-ladder-head"><span></span><span>同位置排名：越靠左越强</span><span>${esc(a.name)}</span><span>${esc(b.name)}</span></div>${rows}</div>`);
    return shell('02', [['位置排名雷达', A], ['位置排名刻度', B]]);
  }

  /* ── 03 英雄池：重合 + 集中度 ───────────────────────────────── */
  function analysis03(a, b) {
    const listOf = (p) => (p.heroes || []).filter((x) => (x.games || 0) > 0).slice().sort((x, y) => (y.games || 0) - (x.games || 0));
    const la = listOf(a), lb = listOf(b);
    const mapA = new Map(la.map((x) => [x.hero, x]));
    const mapB = new Map(lb.map((x) => [x.hero, x]));
    const both = [...mapA.keys()].filter((h) => mapB.has(h));
    const onlyA = [...mapA.keys()].filter((h) => !mapB.has(h));
    const onlyB = [...mapB.keys()].filter((h) => !mapA.has(h));
    const chip = (h, games) => `<span class="pc-chip">${portrait(h)}<b>${esc(h)}</b><em>${n0(games)} 局</em></span>`;
    const gamesOf = (h, source) => (source.get(h) || {}).games || 0;
    const col = (title, heroes, cls, source) => `<div class="pc-pool-col ${cls}"><b>${esc(title)}</b>
      ${heroes.length ? heroes.slice(0, 6).map((h) => chip(h, gamesOf(h, source))).join('') : `<div class="pc-pool-zero"><b>0</b><span>个英雄</span></div>`}
    </div>`;
    const A = view(big(`${both.length}`, `两人都用过的英雄（${a.name} ${la.length} 个 / ${b.name} ${lb.length} 个）`, 'red'),
      `<div class="pc-pool">${col('仅 ' + a.name, onlyA, 'only-a', mapA)}${col('两人都用', both, 'is-both', mapA)}${col('仅 ' + b.name, onlyB, 'only-b', mapB)}</div>`);

    const topShare = (p, list) => list.length ? (list[0].games || 0) / list.reduce((s, x) => s + (x.games || 0), 0) * 100 : null;
    const sa = topShare(a, la), sb = topShare(b, lb);
    const concCol = (p, list, cls) => `<div class="pc-conc-col ${cls}"><b>${esc(p.name)}<small>${n0(list.reduce((s, x) => s + (x.games || 0), 0))} 人次</small></b>
      ${list.length ? list.slice(0, 6).map((x) => {
        const share = (x.games || 0) / list.reduce((s, y) => s + (y.games || 0), 0) * 100;
        return `<div class="pc-conc-row">${portrait(x.hero)}<span>${esc(x.hero)}</span><i class="pc-conc"><em class="${cls === 'a' ? 'a' : 'b'}" style="width:${share.toFixed(1)}%"></em></i><b>${share.toFixed(1)}%</b></div>`;
      }).join('') : '<div class="pc-pool-empty">没有出场英雄</div>'}</div>`;
    const B = view(big(`${sa !== null ? sa.toFixed(1) : '—'}% / ${sb !== null ? sb.toFixed(1) : '—'}%`, `第一英雄占自己出场比重 · ${a.name} / ${b.name}`, 'blue'),
      `<div class="pc-conc-grid">${concCol(a, la, 'a')}${concCol(b, lb, 'b')}</div>`);
    return shell('03', [['英雄重合', A], ['英雄集中度', B]]);
  }

  /* ── 04 状态走势：按局，不再按天 ─────────────────────────────── */
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
    return `<svg class="pc-line-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="按局评分走势">${grid}${paths}${labels}</svg>`;
  }

  function analysis04(a, b) {
    const sa = statOf(a), sb = statOf(b);
    const serA = { cls: 'a', pts: sa.chrono.slice(-12).map((r) => ({ y: r.rating, tip: `${a.name} · 第${sa.chrono.indexOf(r) + 1}局 · ${r.hero || ''} · 评分 ${n1(r.rating)} · ${resWord(r.result)}` })) };
    const serB = { cls: 'b', pts: sb.chrono.slice(-12).map((r) => ({ y: r.rating, tip: `${b.name} · 第${sb.chrono.indexOf(r) + 1}局 · ${r.hero || ''} · 评分 ${n1(r.rating)} · ${resWord(r.result)}` })) };
    const lastA = sa.chrono.length ? sa.chrono[sa.chrono.length - 1].rating : null;
    const lastB = sb.chrono.length ? sb.chrono[sb.chrono.length - 1].rating : null;
    const A = view(big(`${n1(lastA)} / ${n1(lastB)}`, `最近一局评分 · ${a.name} / ${b.name}`, (lastA || 0) >= (lastB || 0) ? 'red' : 'blue'),
      `${lineSvg([serA, serB], {})}<div class="pc-legend"><span><i class="a"></i>${esc(a.name)} 最近 12 局</span><span><i class="b"></i>${esc(b.name)} 最近 12 局</span></div>`);

    const roll = (vals, w) => vals.map((_, i) => {
      const s = vals.slice(Math.max(0, i - w + 1), i + 1);
      return s.reduce((x, y) => x + y, 0) / s.length;
    });
    const rA = roll(sa.ratings, 3), rB = roll(sb.ratings, 3);
    const trend = (p, st, series, cls) => ({
      cls,
      pts: series.map((y, i) => ({ y, tip: `${p.name} · 第${i + 1}局 · 3 局滚动评分 ${n1(y)}` })),
    });
    const B = view(big(`${sa.ratings.length} / ${sb.ratings.length}`, `有效评分局数 · ${a.name} / ${b.name}`, 'blue'),
      rA.length || rB.length
        ? `${lineSvg([trend(a, sa, rA, 'a'), trend(b, sb, rB, 'b')], {})}<div class="pc-legend"><span><i class="a"></i>${esc(a.name)} 按局走势</span><span><i class="b"></i>${esc(b.name)} 按局走势</span><span>3 局滚动，抹掉单局偶然</span></div>`
        : '<div class="pc-empty">还没有足够的逐局评分。</div>');
    return shell('04', [['逐局评分', A], ['按局走势', B]]);
  }

  /* ── 页面 ───────────────────────────────────────────────────── */
  const NAMES = [
    ['01', '位置指标'], ['02', '位置排名'], ['03', '英雄池'],
    ['04', '状态走势'],
  ];

  function initKeys() {
    const list = pool().slice().sort((x, y) => (y.games || 0) - (x.games || 0) || (y.score || 0) - (x.score || 0));
    const solid = list.filter((p) => (p.games || 0) >= 2);
    const pick = solid.length >= 2 ? solid : list;
    if (!find(state.nameA)) state.nameA = (pick[0] || {}).name || '';
    const a = find(state.nameA);
    const sameLane = a ? pick.filter((p) => p.name !== a.name && p.lane === a.lane) : [];
    if (!find(state.nameB) || state.nameB === state.nameA) {
      state.nameB = (sameLane[0] || pick.find((p) => p.name !== state.nameA) || list.find((p) => p.name !== state.nameA) || {}).name || state.nameA;
    }
  }

  function render(value) {
    if (value) state.board = value;
    if (!state.board) return '<div class="page"><div class="loading">正在汇总选手面板…</div></div>';
    initKeys();
    const a = find(state.nameA), b = find(state.nameB);
    if (!a || !b || a === b) {
      const why = state.source === 'kpl' ? '当前数据源（KPL）没有选手逐局样本，人数与场次按 0 显示。'
        : state.source === 'team' ? `本队对「${esc(state.team || '指定战队')}」还没有足够的出场样本，人数与场次按 0 显示。`
          : '当前筛选下不足两名选手，放宽对路或阵营再看。';
      return `<div class="page hc-page pc-page"><h1 class="pc-empty-title">选手对比</h1>
        <div class="hc-controlbar"><div class="hc-controlbar-filters">${sourceBar()}</div></div>
        <div class="empty">${why}</div>
        <p class="hc-source">样本计数：${n0(all().length)} 名选手 · 0 局。无样本一律显示 0。</p></div>`;
    }
    const sa = statOf(a), sb = statOf(b);
    const mets = metricsFor(a, b);
    const leadA = mets.filter(([k]) => isNum(a[k]) && isNum(b[k]) && a[k] > b[k]).length;
    const leadB = mets.filter(([k]) => isNum(a[k]) && isNum(b[k]) && b[k] > a[k]).length;
    const ra = rankSummary(a), rb = rankSummary(b);
    const overlap = (() => {
      const ma = new Set((a.heroes || []).filter((x) => (x.games || 0) > 0).map((x) => x.hero));
      return (b.heroes || []).filter((x) => (x.games || 0) > 0 && ma.has(x.hero)).length;
    })();
    const reach = pool().map((p) => p.name).filter((x) => x !== a.name && x !== b.name).slice(0, 3);

    const cards = [
      card('01', '位置指标', `${esc(a.lane || '本位置')}看：${esc(leadA > leadB ? a.name : leadB > leadA ? b.name : '两人')}领先 <em>${Math.max(leadA, leadB)}</em> 项`, analysis01(a, b)),
      card('02', '位置排名', ra && rb ? `同位置平均排名 <em>第 ${n0(ra.rank)}</em> 对 <em>第 ${n0(rb.rank)}</em>` : '同位置排名样本不足', analysis02(a, b)),
      card('03', '英雄池', `两人重合 <em>${overlap}</em> 个英雄；集中度见右栏`, analysis03(a, b)),
      card('04', '状态走势', `最近一局 <em>${n1(sa.chrono.length ? sa.chrono[sa.chrono.length - 1].rating : null)}</em> 对 <em>${n1(sb.chrono.length ? sb.chrono[sb.chrono.length - 1].rating : null)}</em>`, analysis04(a, b)),
    ].join('');

    return `<div class="page hc-page pc-page">
      ${head(a, b, leadA, leadB)}
      <div class="hc-controlbar">
        <div class="hc-controlbar-filters">
          ${sourceBar()}
          <label class="hc-filter"><span>对路</span><select data-pc-lane aria-label="对路">
            <option value="">全部位置</option>${['对抗路', '打野', '中路', '发育路', '游走'].map((l) => `<option value="${esc(l)}"${state.lane === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
          <label class="hc-filter"><span>阵营</span><select data-pc-scope aria-label="阵营">
            <option value="all"${state.scope === 'all' ? ' selected' : ''}>本队</option></select></label>
          <button class="control pc-refresh" data-action="refresh">刷新数据</button>
          <span class="hc-toolbar-count">${n0(pool().length)} 人 · 点条形可换人${reach.length ? ` · ${reach.map((x) => `<button type="button" class="pc-reach" data-pc-pick="${esc(x)}">${esc(x)}</button>`).join('')}` : ''}</span>
        </div>
        <div class="hc-index" role="group" aria-label="分析直达">${NAMES.map(([id, name]) => `<button type="button" data-pc-jump="${id}"><i>${id}</i>${esc(name)}</button>`).join('')}</div>
      </div>
      <section class="hc-cards">${cards}</section>
      <p class="hc-source">数据来源：王者营地十人面板与逐局结算；数据源＝${{own: '自家', kpl: 'KPL', team: `指定战队 ${state.team || ''}`}[state.source] || '自家'}，无样本按 0 显示；同位置排名只在本位置内比较，跨位置对比请看原始值。</p>
    </div>`;
  }

  /* ── 浅白红蓝对决头 ─────────────────────────────────────────── */
  function head(a, b, leadA, leadB) {
    const opts = (value) => {
      const groups = (list, label) => {
        const rows = list.slice().sort((x, y) => (y.games || 0) - (x.games || 0) || (y.score || 0) - (x.score || 0))
          .map((x) => `<option value="${esc(x.name)}"${x.name === value ? ' selected' : ''}>${esc(x.name)} · ${esc(x.lane || '位置未知')} · ${n0(x.games)} 局</option>`).join('');
        return rows ? `<optgroup label="${label}">${rows}</optgroup>` : '';
      };
      const cur = pool().find((p) => p.name === value);
      const list = pool().slice();
      if (cur) list.sort((x, y) => (x.lane === cur.lane ? -1 : 0) - (y.lane === cur.lane ? -1 : 0) || (y.games || 0) - (x.games || 0));
      const rows = list.map((x) => `<option value="${esc(x.name)}"${x.name === value ? ' selected' : ''}>${esc(x.name)} · ${esc(x.lane || '位置未知')} · ${n0(x.games)} 局</option>`).join('');
      return rows;
    };
    const sameLane = a.lane && a.lane === b.lane;
    const mono = (name, cls) => `<span class="pc-mono ${cls}">${esc(String(name || '?').trim().slice(0, 1) || '?')}</span>`;
    const side = (p, cls, which) => `<div class="hc-duel-side ${cls}">
      <div class="hc-duel-id">${mono(p.name, cls)}<div><span>${cls === 'a' ? '红方' : '蓝方'} · 选手 ${which}</span><b>${esc(p.name)}</b><small>${esc(p.lane || '位置未知')} · ${n0(p.games)} 局 · 胜率 ${pc(p.winRate)}</small></div></div>
      <div class="hc-duel-num"><b>${n1(p.score)}</b><span>表现分</span></div>
      <select data-pc-select="${which === 'A' ? 'a' : 'b'}" aria-label="选手 ${which}">${opts(p.name)}</select>
    </div>`;
    const claim = leadA === leadB
      ? `两人位置指标各领先 <em>${leadA}</em> 项，势均力敌`
      : `${esc(leadA > leadB ? a.name : b.name)} 在本位置指标里领先 <em>${Math.max(leadA, leadB)}</em> 项`;
    const fact = sameLane
      ? `同为${esc(a.lane)}，第 2 张卡的名次可直接横着读；换人时同位置选手排在前面。`
      : `${esc(a.name)} 是${esc(a.lane || '未知位置')}，${esc(b.name)} 是${esc(b.lane || '未知位置')}；不同位置只比原始值，名次各按各的位置算。`;
    const winner = leadA === leadB ? '' : leadA > leadB ? 'a' : 'b';
    return `<section class="hc-hero pc-hero">
      <div class="hc-hero-top"><span class="hc-hero-kicker">KPL · 选手对决</span>
        <span class="hc-hero-scope">${n0(all().length)} 名选手 · ${n0((state.board.games || []).length)} 局</span></div>
      <div class="hc-duel">
        ${side(a, 'a', 'A')}
        <div class="hc-vs ${winner}"><span class="hc-vs-tag">VS</span>
          <b><span class="hc-vs-n a">${leadA}</span><i></i><span class="hc-vs-n b">${leadB}</span></b><small>位置指标领先</small></div>
        ${side(b, 'b', 'B')}
      </div>
      <div class="hc-verdict"><span class="hc-verdict-tag">结论</span>
        <h2 class="hc-claim">${claim}</h2><p class="hc-fact">${fact}</p></div>
    </section>`;
  }

  /* ── 交互 ───────────────────────────────────────────────────── */
  function rerender() {
    const page = document.querySelector('.pc-page');
    if (page) page.outerHTML = render(null);
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
    const pick = t.closest('[data-pc-pick]');
    if (pick && pick.dataset.pcPick) {
      state.nameB = pick.dataset.pcPick;
      if (state.nameB === state.nameA) {
        const alt = pool().find((x) => x.name !== state.nameA);
        if (alt) state.nameB = alt.name;
      }
      rerender();
      return;
    }
  });
  document.addEventListener('change', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.pc-page')) return;
    if (t.hasAttribute('data-pc-select')) {
      const isA = t.dataset.pcSelect === 'a';
      if (isA) {
        state.nameA = t.value;
        const cur = find(state.nameA);
        const alt = cur ? pool().filter((x) => x.name !== state.nameA).sort((x, y) => (x.lane === cur.lane ? -1 : 0) - (y.lane === cur.lane ? -1 : 0) || (y.games || 0) - (x.games || 0))[0] : null;
        if (alt) state.nameB = alt.name;
      } else {
        state.nameB = t.value;
      }
      if (state.nameB === state.nameA) { const alt = pool().find((x) => x.name !== t.value); if (alt) state.nameB = alt.name; }
      rerender();
      return;
    }
    if (t.hasAttribute('data-pc-source')) {
      state.source = t.value;
      if (state.source === 'team' && !state.team) {
        state.team = (((state.board && state.board.opponents) || [])[0] || {}).name || '';
      }
      state.nameA = ''; state.nameB = '';
      rerender();
      return;
    }
    if (t.hasAttribute('data-pc-team')) {
      state.team = t.value;
      state.nameA = ''; state.nameB = '';
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
