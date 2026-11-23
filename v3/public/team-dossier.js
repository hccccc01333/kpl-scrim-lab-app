/* 战队详情 · team dossier v9（2026-11-17 教练反馈修订）
   ============================================================
   v9 只改「看得懂、点得动」的地方：
   1) 01–05 真分节：点哪个只看哪个，时间 / 赛制常驻在分节条上；
   2) 筛选收进一个下拉；英雄列表默认只摊一条路，头像改成大圆卡，
      「全部 110」是清除英雄筛选，不再是一排小胶囊；
   3) 分路 × 类型、边野搭配、位置组合、五路类型全部换成带文字的表，
      小分路（游走）的三类辅助也能逐个对上；
   4) 名次折线可点线聚焦，本窗口 / 上窗口与 BO 切片写清口径；
   5) 英雄池的大卡与「具体拿了谁」放大，ban 后替补按次数加权。
   历史图表函数保留在下方，当前页面只调用 v9 的新图元。
   ============================================================ */
import { renderHeroPoolCross } from './biggame-insight.js';

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
/* 赛训组 2026-11-19：中路只有「法刺」，旧接口缓存里的「法核」在展示层归一。 */
const normArch = (value) => (value === '法核' ? '法刺' : value);
const LANE_SHORT = {'对抗路': '对抗', '打野': '打野', '中路': '中路', '发育路': '发育', '游走': '游走'};
const ARCH = {
  '对抗路': ['战边', '坦边'],
  '打野': ['刺野', '战野', '坦野'],
  '中路': ['工具人', '法刺'],
  '发育路': ['游射', '呆射'],
  '游走': ['开团辅', '保护辅', '功能辅'],
};
/* 类型在全页统一排序：先按分路，再按路内顺序。 */
const TYPE_ORDER = LANES.flatMap((lane) => ARCH[lane]);
const TYPE_LANE = Object.fromEntries(LANES.flatMap((lane) => ARCH[lane].map((type) => [type, lane])));
const TYPE_DESC = {
  '战边': '战士边路，带线切后', '坦边': '坦克边路，抗伤开团',
  '刺野': '刺客打野，切后排', '战野': '战士打野，半前排', '坦野': '坦克打野，开团抗伤',
  '工具人': '功能中单，先手控制', '法刺': '法师核心，主要输出',
  '游射': '位移射手，自保输出', '呆射': '站桩射手，持续输出',
  '开团辅': '先手开团', '保护辅': '保排反手', '功能辅': '功能增益',
};
const EDGE_COMBO = {
  '战刺': ['战边', '刺野'], '战战': ['战边', '战野'], '战坦': ['战边', '坦野'],
  '坦刺': ['坦边', '刺野'], '坦战': ['坦边', '战野'], '坦坦': ['坦边', '坦野'],
};
const UNLABELED = ['待分类', '未标注', '未知', ''];
const WINDOWS = [['3', '近 3 天'], ['7', '近 7 天'], ['30', '近 30 天'], ['all', '全部'], ['custom', '自定义']];
const BO_OPTIONS = [['all', '全部赛制'], ['3', 'BO3'], ['5', 'BO5'], ['7', 'BO7'], ['none', '未登记']];
/* 分路五色相：同一路在图里永远是同一个颜色。 */
const LANE_COLOR = ['var(--c-lane-0)', 'var(--c-lane-1)', 'var(--c-lane-2)', 'var(--c-lane-3)', 'var(--c-lane-4)', 'var(--c-muted)'];
const HAND_COLOR = ['var(--c-hand-1)', 'var(--c-hand-2)', 'var(--c-hand-3)', 'var(--c-hand-4)', 'var(--c-hand-5)'];
const CORE_COLOR = ['var(--c-core-1)', 'var(--c-core-2)', 'var(--c-core-3)', 'var(--c-core-4)'];
/* 类型：在分路色系里再分深浅，跨图一致。 */
const TYPE_COLOR = {
  '战边': 'var(--c-type-战边)', '坦边': 'var(--c-type-坦边)',
  '刺野': 'var(--c-type-刺野)', '战野': 'var(--c-type-战野)', '坦野': 'var(--c-type-坦野)',
  '工具人': 'var(--c-type-工具人)', '法刺': 'var(--c-type-法刺)',
  '游射': 'var(--c-type-游射)', '呆射': 'var(--c-type-呆射)',
  '开团辅': 'var(--c-type-开团辅)', '保护辅': 'var(--c-type-保护辅)', '功能辅': 'var(--c-type-功能辅)',
};

const num = (v) => typeof v === 'number' && Number.isFinite(v);
const mean = (list) => (list.length ? list.reduce((a, b) => a + b, 0) / list.length : null);
const dayNum = (day) => {
  const hit = /^(\d{1,2})-(\d{1,2})/.exec(String(day || ''));
  return hit ? Number(hit[1]) * 100 + Number(hit[2]) : null;
};
const medianBand = (list) => {
  if (!list.length) return null;
  const sorted = [...list].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? [sorted[mid], sorted[mid]] : [sorted[mid - 1], sorted[mid]];
};
const modeOf = (list) => {
  if (!list.length) return null;
  const counter = new Map();
  for (const value of list) counter.set(value, (counter.get(value) || 0) + 1);
  const top = Math.max(...counter.values());
  return {values: [...counter.entries()].filter(([, count]) => count === top).map(([value]) => value).sort((a, b) => a - b), count: top};
};
const distOf = (list) => {
  const counter = new Map();
  for (const value of list) counter.set(value, (counter.get(value) || 0) + 1);
  return [...counter.entries()].sort((a, b) => a[0] - b[0]);
};

export function createTeamDossier(h) {
  const { esc, fmt, pct, time, portrait, route } = h;
  const text = (v) => (v == null || v === '' ? '—' : esc(v));
  const has = num;
  const state = {
    days: '30', bo: 'all', from: '', to: '', hand: 'all', lane: 'all', mode: 'pick',
    bpHero: 'all', poolHero: 'all', bpHeroLane: '对抗路', poolHeroLane: '对抗路',
    responseBan: '', responsePick: '',
    section: 'tp-overview',
  };
  let model = null;
  /* 点数字下钻：渲染时把「这一格/这一行对应的局」登记成 id，点击时按 id 取回。 */
  let gameRegistry = new Map();
  let gameSeq = 0;
  let drawerTrigger = null;
  const resetGameRegistry = () => { gameRegistry = new Map(); gameSeq = 0; };
  const registerGames = (games, title, lanes = []) => {
    const unique = [...new Set((games || []).filter(Boolean))];
    if (!unique.length) return '';
    const id = `g${++gameSeq}`;
    gameRegistry.set(id, {games: unique, title, lanes});
    return id;
  };
  const gamesAttr = (games, title, lanes = []) => {
    const id = registerGames(games, title, lanes);
    return id ? ` data-tp-games="${id}"` : '';
  };
  const isDrill = (games) => (games && games.length ? ' is-drill' : '');

  const card = (title, meta, body, cls = '') => `<article class="tp-card${cls ? ' ' + cls : ''}">${title || meta ? `<header class="tp-card-head"><h3>${title}</h3>${meta ? `<span>${meta}</span>` : ''}</header>` : ''}${body}</article>`;
  const lack = (note) => `<p class="tp-lack">证据不足 · ${esc(note)}</p>`;
  const heroChip = (hero, count, title) => `<a class="tp-hchip" href="${route('hero', hero)}" title="${esc(title || `${hero}${has(count) ? ` · ${fmt(count)} 次` : ''}`)}">${String(portrait(hero, 'is-chip')).replace(' loading="lazy"', '')}<b>${esc(hero)}</b>${has(count) ? `<small>${fmt(count)}</small>` : ''}</a>`;
  const heroChips = (rows, limit = 5) => `<div class="tp-hchips">${(rows || []).slice(0, limit).map((row) => heroChip(row.hero, row.games, row.title)).join('') || '<span class="tp-quiet">—</span>'}</div>`;
  /* 图下数值表：图看形状，表看精确数；移动端也能直接读。 */
  const dataTable = (headers, rows, note = '') => `<details class="tp-data"><summary>看数值</summary><div class="tp-data-wrap"><table class="tp-data-table"><thead><tr>${headers.map((head) => `<th>${esc(head)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="tp-data-hint">左右滑动看全表</p>${note ? `<p class="tp-data-note">${note}</p>` : ''}</details>`;
  const laneCls = (lane) => (LANES.includes(lane) ? `tp-lane-${LANES.indexOf(lane)}` : 'tp-lane-unlabeled');
  const isKnownType = (type) => Boolean(type) && !UNLABELED.includes(type);
  const isKnownLane = (lane) => LANES.includes(lane);
  const iconOf = (hero) => {
    const hit = /src="([^"]+)"/.exec(String(portrait(hero, 'is-face')));
    return hit ? hit[1] : '';
  };
  const svg = (w, h, inner, aria) => `<svg class="tp-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(aria)}">${inner}</svg>`;
  const colorOfKey = (key) => TYPE_COLOR[key] || (LANES.includes(key) ? LANE_COLOR[LANES.indexOf(key)] : 'var(--c-muted)');

  /* ══ 图元 ══════════════════════════════════════════════════════ */

  /* 1. 旭日：分路（内环）→ 类型（外环）。 */
  function sunburst(nodes, opts = {}) {
    const {size = 280} = opts;
    const c = size / 2;
    const r0 = size * 0.13, r1 = size * 0.25, r2 = size * 0.38, r3 = size * 0.45;
    const total = nodes.reduce((sum, node) => sum + node.count, 0);
    if (!total) return '';
    const arc = (a, b, angle0, angle1) => {
      const large = angle1 - angle0 > Math.PI ? 1 : 0;
      const p = (r, ang) => [c + r * Math.cos(ang), c + r * Math.sin(ang)];
      const [x0, y0] = p(b, angle0), [x1, y1] = p(b, angle1), [x2, y2] = p(a, angle1), [x3, y3] = p(a, angle0);
      return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${b} ${b} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} L${x2.toFixed(2)} ${y2.toFixed(2)} A${a} ${a} 0 ${large} 0 ${x3.toFixed(2)} ${y3.toFixed(2)} Z`;
    };
    let angle = -Math.PI / 2;
    const parts = [];
    nodes.forEach((node) => {
      if (!node.count) return;
      const span = (node.count / total) * Math.PI * 2;
      const a0 = angle, a1 = angle + span;
      parts.push(`<path d="${arc(r0, r1, a0, a1)}" fill="${node.color || colorOfKey(node.key)}" class="tp-sun-seg"><title>${esc(`${node.key} · ${fmt(node.count)}`)}</title></path>`);
      if (span > 0.3) {
        const mid = (a0 + a1) / 2;
        const [lx, ly] = [c + ((r0 + r1) / 2) * Math.cos(mid), c + ((r0 + r1) / 2) * Math.sin(mid) + 3.2];
        parts.push(`<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="tp-sun-label">${esc(node.key)}</text>`);
      }
      let inner = a0;
      const kids = (node.children || []).filter((child) => child.count);
      kids.forEach((child, index) => {
        const cSpan = (child.count / total) * Math.PI * 2;
        parts.push(`<path d="${arc(r1 + 3, r2, inner, inner + cSpan)}" fill="${colorOfKey(child.key)}" fill-opacity="${(1 - index * 0.18).toFixed(2)}" class="tp-sun-seg"><title>${esc(`${node.key} → ${child.key} · ${fmt(child.count)}`)}</title></path>`);
        if (cSpan > 0.36) {
          const mid = inner + cSpan / 2;
          const [lx, ly] = [c + ((r1 + r2) / 2) * Math.cos(mid), c + ((r1 + r2) / 2) * Math.sin(mid) + 3];
          parts.push(`<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="tp-sun-label is-child">${esc(child.key)}</text>`);
        }
        inner += cSpan;
      });
      angle = a1;
    });
    return svg(size, size, `<circle cx="${c}" cy="${c}" r="${r3}" class="tp-sun-ring"/>${parts.join('')}
      <circle cx="${c}" cy="${c}" r="${r0 - 3}" class="tp-sun-hole"/>
      <text x="${c}" y="${c - 1}" text-anchor="middle" class="tp-sun-total">${fmt(total)}</text>
      <text x="${c}" y="${c + 14}" text-anchor="middle" class="tp-sun-caption">${esc(opts.caption || '人次')}</text>`, opts.aria || '分布旭日图');
  }

  /* 2. 流带（stream）：横向按手序铺开，纵向按分路分层，面积＝人次。 */
  function streamChart(series, opts = {}) {
    const W = opts.width || 560, H = opts.height || 190;
    const keys = opts.keys || [];
    const n = series.length;
    if (n < 2 || !keys.length) return '';
    const padT = 10, padB = 26;
    const plotH = H - padT - padB;
    const xs = series.map((_, index) => 46 + (index / (n - 1)) * (W - 76));
    const totals = series.map((item) => item.segments.reduce((sum, seg) => sum + seg.count, 0));
    const maxTotal = Math.max(1, ...totals);
    /* 每一层在每个 x 上的上下边界 */
    const stack = series.map((item, index) => {
      let acc = 0;
      const col = new Map();
      for (const key of keys) {
        const seg = item.segments.find((s) => s.key === key);
        const value = seg ? seg.count : 0;
        const h = (value / maxTotal) * plotH;
        col.set(key, {y0: acc, y1: acc + h, value});
        acc += h;
      }
      return {x: xs[index], col};
    });
    /* 用二次曲线连接中点，得到平滑的带子 */
    const band = (key) => {
      const top = stack.map((col) => [col.x, padT + plotH - col.col.get(key).y0]);
      const bottom = stack.map((col) => [col.x, padT + plotH - col.col.get(key).y1]);
      const path = (points) => {
        let d = `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
        for (let i = 1; i < points.length; i++) {
          const [px, py] = points[i - 1];
          const [cx, cy] = points[i];
          const mx = (px + cx) / 2;
          d += ` C${mx.toFixed(1)} ${py.toFixed(1)}, ${mx.toFixed(1)} ${cy.toFixed(1)}, ${cx.toFixed(1)} ${cy.toFixed(1)}`;
        }
        return d;
      };
      return `<path d="${path(top)} ${path([...bottom].reverse()).replace(/^M/, 'L')} Z" fill="${(opts.colorOf ? opts.colorOf(key) : colorOfKey(key))}" class="tp-stream-band"><title>${esc(key)}</title></path>`;
    };
    const grid = series.map((item, index) => `<text x="${xs[index].toFixed(1)}" y="${H - 8}" text-anchor="middle" class="tp-stream-x">${esc(item.label)}</text><text x="${xs[index].toFixed(1)}" y="${padT - 0}" text-anchor="middle" class="tp-stream-total">${fmt(totals[index])}</text>`).join('');
    return svg(W, H, `${keys.map(band).join('')}${grid}`, opts.aria || '手序流带');
  }

  /* 3. 气泡矩阵：行 × 列，面积与透明度同时编码次数。 */
  function bubbleMatrix(rows, cols, get, opts = {}) {
    const cell = opts.cell || 36;
    const padL = opts.padL || 64, padT = 24;
    const W = padL + cols.length * cell + 16;
    const H = padT + rows.length * cell + 8;
    let max = 1;
    for (const row of rows) for (const col of cols) max = Math.max(max, get(row, col) || 0);
    const cells = [];
    rows.forEach((row, ri) => {
      cols.forEach((col, ci) => {
        const value = get(row, col) || 0;
        const cx = padL + ci * cell + cell / 2;
        const cy = padT + ri * cell + cell / 2;
        if (!value) { cells.push(`<circle cx="${cx}" cy="${cy}" r="2" class="tp-bub-empty"/>`); return; }
        const r = 4 + Math.sqrt(value / max) * (cell / 2 - 4);
        cells.push(`<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="${LANE_COLOR[ri % 5]}" fill-opacity="${(0.42 + 0.58 * (value / max)).toFixed(2)}" class="tp-bub"><title>${esc(`${row.label} · ${col} · ${fmt(value)} 次`)}</title></circle><text x="${cx}" y="${cy + 3.4}" class="tp-bub-text">${fmt(value)}</text>`);
      });
    });
    const head = cols.map((col, ci) => `<text x="${padL + ci * cell + cell / 2}" y="${padT - 9}" text-anchor="middle" class="tp-bub-axis">${esc(col)}</text>`).join('');
    const labels = rows.map((row, ri) => `<text x="${padL - 12}" y="${padT + ri * cell + cell / 2 + 3.5}" text-anchor="end" class="tp-bub-row">${esc(row.label)}</text>`).join('');
    return svg(W, H, `${head}${labels}${cells.join('')}`, opts.aria || '气泡矩阵');
  }

  /* 3b. 100% 占比柱：每一列总高固定，段内写字，解决小切片没有标签的问题。 */
  function shareColumns(series, keys, opts = {}) {
    const W = opts.width || 560, H = opts.height || 250;
    const padL = 40, padR = 14, padT = 18, padB = opts.padB || 46;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const slot = plotW / Math.max(1, series.length);
    const barW = Math.min(opts.barW || 62, slot * 0.62);
    const short = opts.shortOf || ((key) => key);
    const totals = series.map((item) => item.total ?? item.segments.reduce((sum, seg) => sum + seg.count, 0));
    const grid = [0, 0.5, 1].map((tick) => {
      const y = padT + plotH * (1 - tick);
      return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" class="tp-share-grid"/><text x="${padL - 8}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" class="tp-share-tick">${Math.round(tick * 100)}%</text>`;
    }).join('');
    const bars = series.map((item, index) => {
      const total = totals[index];
      const x = padL + index * slot + (slot - barW) / 2;
      let y = padT + plotH;
      const segments = keys.map((key) => {
        const seg = item.segments.find((s) => s.key === key);
        const count = seg?.count || 0;
        const h = total ? (count / total) * plotH : 0;
        if (!h) return '';
        y -= h;
        const label = h >= 17 ? `<text x="${(x + barW / 2).toFixed(1)}" y="${(y + h / 2 + 3.6).toFixed(1)}" text-anchor="middle" class="tp-share-label">${esc(short(key))}</text>` : '';
        const segGames = opts.gamesOf ? opts.gamesOf(item, key) : [];
        const gid = segGames.length ? gamesAttr(segGames, `${item.label} · ${key}`, opts.lanesOf ? opts.lanesOf(key) : []) : '';
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${opts.colorOf ? opts.colorOf(key) : colorOfKey(key)}" class="tp-share-seg${gid ? ' is-drill' : ''}"${gid}><title>${esc(`${item.label} · ${key} · ${fmt(count)}（${pct((count / total) * 100)}）`)}</title></rect>${label}`;
      }).join('');
      const note = opts.noteOf ? opts.noteOf(item, total) : (item.note || '');
      return `<g class="tp-share-col">${segments}
        <text x="${(x + barW / 2).toFixed(1)}" y="${H - 24}" text-anchor="middle" class="tp-share-x">${esc(item.label)}</text>
        ${note ? `<text x="${(x + barW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="tp-share-note">${esc(note)}</text>` : ''}
      </g>`;
    }).join('');
    return svg(W, H, `${grid}${bars}`, opts.aria || '占比柱');
  }

  /* 3c. 分路类型构成：每条分路一条分段条 + 清晰清单。
       要看的就是「对抗路选了多少战边、多少坦边」，稀疏矩阵的大量空格与合计行没有信息量。 */
  function typeMatrix(rows, opts = {}) {
    const typedRows = rows.filter((row) => isKnownType(row.archetype));
    const lanes = LANES.filter((lane) => typedRows.some((row) => row.lane === lane));
    if (!lanes.length) return '';
    const body = lanes.map((lane) => {
      const laneRows = typedRows.filter((row) => row.lane === lane);
      const total = laneRows.length;
      const parts = TYPE_ORDER
        .map((type) => ({type, partRows: laneRows.filter((row) => row.archetype === type)}))
        .filter((part) => part.partRows.length)
        .sort((a, b) => b.partRows.length - a.partRows.length);
      const bar = parts.map((part) => {
        const share = (part.partRows.length / total) * 100;
        const games = part.partRows.map((row) => row.game);
        const gid = gamesAttr(games, `${lane} · ${part.type}`, [lane]);
        return `<span class="tp-tm-seg${gid ? ' is-drill' : ''}"${gid} data-col="${TYPE_ORDER.indexOf(part.type)}" style="width:${share.toFixed(2)}%;background:${colorOfKey(part.type)}" title="${esc(`${lane} · ${part.type} · ${fmt(part.partRows.length)} 人次（${pct(share)}）；点开看这 ${fmt(games.length)} 局`)}">${share >= 12 ? `<i>${pct(share)}</i>` : ''}</span>`;
      }).join('');
      const list = parts.map((part) => `<span><i style="background:${colorOfKey(part.type)}"></i><b>${esc(part.type)}</b><em>${fmt(part.partRows.length)} 人次</em><small>${pct((part.partRows.length / total) * 100)}</small></span>`).join('');
      return `<div class="tp-tm-row">
        <div class="tp-tm-head"><b>${esc(lane)}</b><small>${fmt(total)} 人次</small></div>
        <div class="tp-tm-bar" role="img" aria-label="${esc(`${lane}各类型构成`)}">${bar}</div>
        <div class="tp-tm-list">${list}</div>
      </div>`;
    }).join('');
    return `<div class="tp-tm" aria-label="${esc(opts.aria || '分路类型构成')}">${body}</div>`;
  }

  /* 3e. 英雄池大卡：头像 56px，名字和次数在下面，不再挤成一条胶囊。 */
  function poolHeroCard(hero, count, type) {
    return `<a class="tp-poolhero" href="${route('hero', hero)}" title="${esc(`${hero}${type ? ` · ${type}` : ''} · ${fmt(count)} 次`)}">
      <span class="tp-poolhero-face">${String(portrait(hero, 'is-face')).replace(' loading="lazy"', '')}<em>${fmt(count)}</em></span>
      <b>${esc(hero)}</b>${type ? `<small>${esc(type)}</small>` : ''}
    </a>`;
  }
  /* BP 顶部速览的紧凑英雄格：头像 32px，比英雄池的大圆卡小一圈。 */
  function topHeroTile(hero, count, winRate = null) {
    return `<a class="tp-tophero" href="${route('hero', hero)}" title="${esc(`${hero} · ${fmt(count)} 次${winRate == null ? '' : ` · 本队胜率 ${winRate}%`}`)}">
      <span class="tp-tophero-face">${String(portrait(hero, 'is-face')).replace(' loading="lazy"', '')}<em>${fmt(count)}</em></span>
      <b>${esc(hero)}</b>${winRate == null ? '' : `<i class="tp-tophero-rate${winRate >= 50 ? ' is-win' : ' is-loss'}">本队 ${winRate}%</i>`}</a>`;
  }
  /* 4. 排名折线（bump）：切片之间名次怎么换；右侧直接写线名，点线只看一路。 */
  function bumpChart(series, keys, opts = {}) {
    const W = opts.width || 460, H = opts.height || 230;
    const padL = 54, padR = 92, padT = 18, padB = 38;
    const n = series.length;
    if (!n) return '';
    const ranks = series.map((item) => {
      const totals = keys.map((key) => ({key, count: item.segments.find((seg) => seg.key === key)?.count || 0}));
      const sorted = [...totals].sort((a, b) => b.count - a.count);
      return new Map(sorted.map((row, index) => [row.key, {rank: index + 1, count: row.count}]));
    });
    const xs = series.map((_, index) => padL + (index / Math.max(1, n - 1)) * (W - padL - padR));
    const ys = (rank) => padT + ((rank - 1) / Math.max(1, keys.length - 1)) * (H - padT - padB);
    const lines = keys.map((key) => {
      const points = series.map((_, index) => [xs[index], ys(ranks[index].get(key).rank)]);
      const path = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
      return `<g class="tp-bump-series" data-tp-bump="${esc(key)}"><path d="${path}" fill="none" stroke="transparent" stroke-width="12" pointer-events="stroke" class="tp-bump-hit"/><path d="${path}" fill="none" stroke="${colorOfKey(key)}" stroke-width="2" stroke-linecap="round" class="tp-bump-line"/>
        ${points.map(([x, y], index) => {
          const dotGames = opts.gamesOf ? opts.gamesOf(series[index], key) : [];
          const gid = dotGames.length ? gamesAttr(dotGames, `${key} · ${series[index].label}`, [key]) : '';
          return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${colorOfKey(key)}" class="tp-bump-dot"><title>${esc(`${key} · ${series[index].label} · 第 ${ranks[index].get(key).rank} 名 · ${fmt(ranks[index].get(key).count)} 人次${gid ? '；点开看这 ' + dotGames.length + ' 局' : ''}`)}</title></circle>${gid ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="10" fill="transparent" pointer-events="all" class="tp-bump-hitdot is-drill"${gid}><title>${esc(`${key} · ${series[index].label} · 点开看这 ${dotGames.length} 局`)}</title></circle>` : ''}`;
        }).join('')}</g>`;
    }).join('');
    const rankTicks = keys.map((_, index) => `<text x="${padL - 12}" y="${(ys(index + 1) + 3.5).toFixed(1)}" text-anchor="end" class="tp-bump-rank">第 ${index + 1}</text>`).join('');
    const final = keys.map((key) => ({key, rank: ranks[n - 1].get(key).rank, y: ys(ranks[n - 1].get(key).rank)})).sort((a, b) => a.y - b.y);
    let lastY = -99;
    for (const item of final) { item.y = Math.max(item.y, lastY + 14); lastY = item.y; }
    const endLabels = final.map((item) => {
      const ly = Math.min(item.y + 3.5, H - padB - 4);
      return `<text x="${(W - padR + 20).toFixed(1)}" y="${ly.toFixed(1)}" class="tp-bump-end" fill="${colorOfKey(item.key)}">${esc(item.key)}</text>`;
    }).join('');
    const cols = rankTicks + series.map((item, index) => `<text x="${xs[index].toFixed(1)}" y="${H - 24}" text-anchor="middle" class="tp-bump-x">${esc(item.label)}</text>${item.note ? `<text x="${xs[index].toFixed(1)}" y="${H - 8}" text-anchor="middle" class="tp-bump-note">${esc(item.note)}</text>` : ''}`).join('');
    const legend = keys.map((key) => `<button type="button" class="tp-bump-key" data-tp-bump="${esc(key)}" aria-pressed="false"><i style="background:${colorOfKey(key)}"></i>${esc(key)}</button>`).join('');
    return `<div class="tp-bump">${svg(W, H, `${lines}${cols}${endLabels}`, opts.aria || '名次变化')}<div class="tp-legend tp-bump-keys">${legend}</div></div>`;
  }

  /* 5. 和弦：边路类型与打野类型之间的搭配流量。 */
  function chord(links, opts = {}) {
    const size = opts.size || 260;
    const c = size / 2;
    const rOut = size * 0.45, rIn = size * 0.36;
    const groups = opts.groups || [];
    const keys = groups.flatMap((group) => group.nodes);
    const totals = new Map(keys.map((key) => [key, 0]));
    for (const link of links) {
      totals.set(link.from, (totals.get(link.from) || 0) + link.count);
      totals.set(link.to, (totals.get(link.to) || 0) + link.count);
    }
    const total = [...totals.values()].reduce((sum, value) => sum + value, 0);
    if (!total) return '';
    const spans = new Map();
    let angle = -Math.PI / 2;
    const groupGap = 0.06;
    groups.forEach((group) => {
      group.nodes.forEach((key) => {
        const span = ((totals.get(key) || 0) / total) * (Math.PI * 2 - groupGap * groups.length);
        spans.set(key, {start: angle, end: angle + span});
        angle += span;
      });
      angle += groupGap;
    });
    const point = (r, ang) => [c + r * Math.cos(ang), c + r * Math.sin(ang)];
    const arcs = groups.map((group) => group.nodes.map((key) => {
      const span = spans.get(key);
      if (!span || span.end - span.start < 0.0001) return '';
      const large = span.end - span.start > Math.PI ? 1 : 0;
      const [x0, y0] = point(rOut, span.start), [x1, y1] = point(rOut, span.end);
      const [x2, y2] = point(rIn, span.end), [x3, y3] = point(rIn, span.start);
      const mid = (span.start + span.end) / 2;
      const [lx, ly] = point(rOut + 12, mid);
      return `<path d="M${x0.toFixed(1)} ${y0.toFixed(1)} A${rOut} ${rOut} 0 ${large} 1 ${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)} A${rIn} ${rIn} 0 ${large} 0 ${x3.toFixed(1)} ${y3.toFixed(1)} Z" fill="${colorOfKey(key)}" class="tp-chord-arc"><title>${esc(`${key} · ${fmt(totals.get(key))} 局`)}</title></path>
        <text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="tp-chord-label">${esc(key)}</text>`;
    }).join('')).join('');
    const cursors = new Map(keys.map((key) => [key, spans.get(key)?.start || 0]));
    const ribbons = links.slice().sort((a, b) => b.count - a.count).map((link) => {
      const fromSpan = spans.get(link.from), toSpan = spans.get(link.to);
      if (!fromSpan || !toSpan) return '';
      const fromWidth = (link.count / total) * (Math.PI * 2 - 0.18);
      const toWidth = fromWidth;
      const a0 = cursors.get(link.from), a1 = a0 + fromWidth;
      cursors.set(link.from, a1);
      const b0 = cursors.get(link.to), b1 = b0 + toWidth;
      cursors.set(link.to, b1);
      const [x0, y0] = point(rIn - 4, a0), [x1, y1] = point(rIn - 4, a1);
      const [x2, y2] = point(rIn - 4, b1), [x3, y3] = point(rIn - 4, b0);
      const path = `M${x0.toFixed(1)} ${y0.toFixed(1)} Q${c} ${c} ${x1.toFixed(1)} ${y1.toFixed(1)} A${rIn - 4} ${rIn - 4} 0 0 0 ${x3.toFixed(1)} ${y3.toFixed(1)} Q${c} ${c} ${x2.toFixed(1)} ${y2.toFixed(1)} A${rIn - 4} ${rIn - 4} 0 0 0 ${x0.toFixed(1)} ${y0.toFixed(1)} Z`;
      return `<path d="${path}" fill="${colorOfKey(link.from)}" fill-opacity=".22" class="tp-chord-ribbon"><title>${esc(`${link.from} + ${link.to} · ${fmt(link.count)} 局`)}</title></path>`;
    }).join('');
    return svg(size, size, `${ribbons}${arcs}`, opts.aria || '边野和弦图');
  }

  /* 6. 玫瑰图：极坐标上的柱子，半径表示局数。 */
  function rose(items, opts = {}) {
    const size = opts.size || 220;
    const c = size / 2;
    const inner = size * 0.13, outer = size * 0.40;
    const total = items.reduce((sum, item) => sum + item.count, 0);
    if (!total) return '';
    const max = Math.max(...items.map((item) => item.count));
    const step = (Math.PI * 2) / items.length;
    const bars = items.map((item, index) => {
      const a0 = -Math.PI / 2 + index * step + step * 0.06;
      const a1 = a0 + step * 0.88;
      const r = inner + (item.count / max) * (outer - inner);
      const p = (radius, ang) => [c + radius * Math.cos(ang), c + radius * Math.sin(ang)];
      const [x0, y0] = p(inner, a0), [x1, y1] = p(inner, a1);
      const [x2, y2] = p(r, a1), [x3, y3] = p(r, a0);
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const mid = (a0 + a1) / 2;
      const [lx, ly] = p(r + 10, mid);
      /* 局数放进扇区里：沿中线取内外半径的中点，白色粗体压在色块上，
         不再和外侧的「N 核」标签挤成一行。 */
      const [ix, iy] = p((inner + r) / 2, mid);
      const roseGames = opts.gamesOf ? opts.gamesOf(item) : [];
      const gid = roseGames.length ? gamesAttr(roseGames, `${opts.caption || '分布'} · ${item.key}`, opts.lanesOf ? opts.lanesOf(item) : []) : '';
      return `<path d="M${x0.toFixed(1)} ${y0.toFixed(1)} L${x3.toFixed(1)} ${y3.toFixed(1)} A${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L${x1.toFixed(1)} ${y1.toFixed(1)} A${inner} ${inner} 0 ${large} 0 ${x0.toFixed(1)} ${y0.toFixed(1)} Z" fill="${opts.colorOf ? opts.colorOf(item) : 'var(--accent)'}" class="tp-rose-bar${gid ? ' is-drill' : ''}"${gid}><title>${esc(`${item.key} · ${fmt(item.count)} 局${gid ? '；点开看这 ' + roseGames.length + ' 局' : ''}`)}</title></path>
        <text x="${ix.toFixed(1)}" y="${iy.toFixed(1)}" text-anchor="middle" dominant-baseline="central" class="tp-rose-value">${fmt(item.count)}</text>
        <text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="tp-rose-label">${esc(item.key)}</text>`;
    }).join('');
    return svg(size, size, `${bars}<circle cx="${c}" cy="${c}" r="${inner - 2}" class="tp-sun-hole"/>
      <text x="${c}" y="${c + 1}" text-anchor="middle" class="tp-sun-total">${fmt(total)}</text>
      <text x="${c}" y="${c + 15}" text-anchor="middle" class="tp-sun-caption">${esc(opts.caption || '局')}</text>`, opts.aria || '玫瑰图');
  }

  /* 7. 小环组：每个分路一个环，环内按类型切。 */
  function miniRings(items, opts = {}) {
    const size = opts.size || 92;
    const r = size * 0.34;
    const circumference = 2 * Math.PI * r;
    return `<div class="tp-minirings">${items.map((item) => {
      const total = item.segments.reduce((sum, seg) => sum + seg.count, 0) || 1;
      let offset = 0;
      const arcs = item.segments.map((seg) => {
        const len = (seg.count / total) * circumference;
        const d = `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${colorOfKey(seg.key)}" stroke-width="${size * 0.16}" stroke-dasharray="${len.toFixed(1)} ${(circumference - len).toFixed(1)}" stroke-dashoffset="${(-offset).toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})" class="tp-miniring-seg"><title>${esc(`${item.label} · ${seg.key} · ${fmt(seg.count)} 局`)}</title></circle>`;
        offset += len;
        return d;
      }).join('');
      const top = item.segments.slice().sort((a, b) => b.count - a.count)[0];
      return `<div class="tp-miniring"><div class="tp-miniring-figure"><svg viewBox="0 0 ${size} ${size}" class="tp-miniring-svg">${arcs}</svg>
        <span class="tp-miniring-center"><b>${fmt(total)}</b><small>局</small></span></div>
        <span class="tp-miniring-lane"><i class="${laneCls(item.label)}"></i>${esc(item.label)}</span>
        <span class="tp-miniring-top">${top ? `${esc(top.key)} ${pct((top.count / total) * 100)}` : '—'}</span></div>`;
    }).join('')}</div>`;
  }

  /* 8. 桑基：我们 ban 的英雄 → 他们同路改拿的英雄。 */
  function flowChart(links, opts = {}) {
    if (!links.length) return '';
    const leftTotals = new Map(), rightTotals = new Map();
    for (const link of links) {
      leftTotals.set(link.from, (leftTotals.get(link.from) || 0) + link.count);
      rightTotals.set(link.to, (rightTotals.get(link.to) || 0) + link.count);
    }
    const left = [...leftTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, opts.leftLimit || 5);
    const leftSet = new Set(left.map(([hero]) => hero));
    const right = [...rightTotals.entries()].filter(([hero]) => !leftSet.has(hero)).sort((a, b) => b[1] - a[1]).slice(0, opts.rightLimit || 6);
    const total = left.reduce((sum, [, count]) => sum + count, 0) || 1;
    const W = 720, H = Math.max(180, Math.max(left.length, right.length) * 40 + 24);
    const x0 = 190, x1 = W - 190;
    const place = (nodes, gap) => {
      const sum = nodes.reduce((acc, [, count]) => acc + count, 0) || 1;
      const usable = H - 24 - gap * Math.max(0, nodes.length - 1);
      const map = new Map();
      let y = 12;
      for (const [hero, count] of nodes) {
        const h = Math.max(16, (count / sum) * usable);
        map.set(hero, {y, h, count});
        y += h + gap;
      }
      return map;
    };
    const leftNodes = place(left, 10);
    const rightNodes = place(right, 8);
    const cursorLeft = new Map([...leftNodes].map(([hero, node]) => [hero, node.y]));
    const cursorRight = new Map([...rightNodes].map(([hero, node]) => [hero, node.y]));
    const ribbons = [...links]
      .filter((link) => leftNodes.has(link.from) && rightNodes.has(link.to))
      .sort((a, b) => b.count - a.count)
      .map((link) => {
        const lh = (link.count / total) * (H - 24);
        const rh = lh;
        const y0 = cursorLeft.get(link.from);
        const y1 = cursorRight.get(link.to);
        cursorLeft.set(link.from, y0 + lh + 1.5);
        cursorRight.set(link.to, y1 + rh + 1.5);
        const path = `M${x0} ${y0.toFixed(1)} C${x0 + 90} ${y0.toFixed(1)}, ${x1 - 90} ${y1.toFixed(1)}, ${x1} ${y1.toFixed(1)} L${x1} ${(y1 + rh).toFixed(1)} C${x1 - 90} ${(y1 + rh).toFixed(1)}, ${x0 + 90} ${(y0 + lh).toFixed(1)}, ${x0} ${(y0 + lh).toFixed(1)} Z`;
        return `<path d="${path}" fill="${colorOfKey('战边')}" fill-opacity=".2" class="tp-flow-link"><title>${esc(`${link.from} → ${link.to} · ${fmt(link.count)} 次`)}</title></path>`;
      }).join('');
    const drawNode = (hero, x, data, side) => {
      const icon = iconOf(hero);
      const size = Math.min(24, Math.max(14, data.h));
      const ix = side === 'left' ? x - size - 8 : x + 8;
      return `<rect x="${x - 3}" y="${data.y.toFixed(1)}" width="6" height="${data.h.toFixed(1)}" rx="3" fill="${side === 'left' ? 'var(--c-loss)' : 'var(--c-win)'}"/>
        ${icon ? `<image href="${icon}" x="${ix}" y="${(data.y + (data.h - size) / 2).toFixed(1)}" width="${size}" height="${size}" class="tp-flow-icon" preserveAspectRatio="xMidYMid slice"/>` : ''}
        <text x="${side === 'left' ? x - size - 14 : x + size + 14}" y="${(data.y + data.h / 2 + 3.5).toFixed(1)}" text-anchor="${side === 'left' ? 'end' : 'start'}" class="tp-flow-label">${esc(hero)}<tspan class="tp-flow-count"> ${fmt(data.count)}</tspan></text>`;
    };
    return `<div class="tp-flow">${svg(W, H, `${ribbons}${[...leftNodes].map(([hero, data]) => drawNode(hero, x0, data, 'left')).join('')}${[...rightNodes].map(([hero, data]) => drawNode(hero, x1, data, 'right')).join('')}`, opts.aria || '替补流向')}
      <div class="tp-flow-legend"><span><i class="is-loss"></i>我们 ban 掉</span><span><i class="is-win"></i>他们同路改拿</span><span>线宽＝次数</span></div></div>`;
  }

  /* 9. 镜像柱：上半是赢的局、下半是输的局，同一分类上下对冲。 */
  function mirrorColumns(categories, up, down, opts = {}) {
    const W = opts.width || 520, H = opts.height || 200;
    const padT = 16, padB = 30, mid = H / 2;
    const shown = opts.hideEmpty ? categories.filter((key) => (up.get(key) || 0) + (down.get(key) || 0) > 0) : categories;
    if (!shown.length) return '';
    const max = Math.max(1, ...shown.flatMap((key) => [up.get(key) || 0, down.get(key) || 0]));
    const slot = (W - 40) / shown.length;
    const barW = Math.min(46, slot * 0.52);
    const bars = shown.map((key, index) => {
      const x = 30 + index * slot + slot / 2 - barW / 2;
      const upH = ((up.get(key) || 0) / max) * (mid - padT - 6);
      const downH = ((down.get(key) || 0) / max) * (mid - padB - 6);
      const upGames = opts.gamesOf ? opts.gamesOf(key, 'up') : [];
      const downGames = opts.gamesOf ? opts.gamesOf(key, 'down') : [];
      const upGid = upGames.length ? gamesAttr(upGames, `${key} · 本队胜`, opts.lanesOf ? opts.lanesOf(key, 'up') : []) : '';
      const downGid = downGames.length ? gamesAttr(downGames, `${key} · 对手胜`, opts.lanesOf ? opts.lanesOf(key, 'down') : []) : '';
      return `<rect x="${x.toFixed(1)}" y="${(mid - upH - 4).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0, upH).toFixed(1)}" rx="4" fill="var(--c-win)" class="tp-mirror-bar${upGid ? ' is-drill' : ''}"${upGid}><title>${esc(`${key} · 本队胜 ${fmt(up.get(key) || 0)} 局${upGid ? '；点开看这 ' + upGames.length + ' 局' : ''}`)}</title></rect>
        ${(up.get(key) || 0) ? `<text x="${(x + barW / 2).toFixed(1)}" y="${(mid - upH - 9).toFixed(1)}" text-anchor="middle" class="tp-mirror-count">${fmt(up.get(key) || 0)}</text>` : ''}
        <rect x="${x.toFixed(1)}" y="${(mid + 4).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0, downH).toFixed(1)}" rx="4" fill="var(--c-loss)" class="tp-mirror-bar${downGid ? ' is-drill' : ''}"${downGid}><title>${esc(`${key} · 对手胜 ${fmt(down.get(key) || 0)} 局${downGid ? '；点开看这 ' + downGames.length + ' 局' : ''}`)}</title></rect>
        ${(down.get(key) || 0) ? `<text x="${(x + barW / 2).toFixed(1)}" y="${(mid + downH + 16).toFixed(1)}" text-anchor="middle" class="tp-mirror-count">${fmt(down.get(key) || 0)}</text>` : ''}
        <text x="${(x + barW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="tp-mirror-x">${esc(key)}</text>`;
    }).join('');
    return `${svg(W, H, `<line x1="20" y1="${mid}" x2="${W - 20}" y2="${mid}" class="tp-mirror-axis"/>${bars}`, opts.aria || '输赢结构对比')}<div class="tp-legend"><span><i style="background:var(--c-win)"></i>上：本队胜</span><span><i style="background:var(--c-loss)"></i>下：对手胜</span></div>`;
  }

  /* 英雄选择器：一次只摊开一条路，头像用大圆卡；「全部」是清除筛选，不是全选。 */
  function heroPicker(rows, opts) {
    const key = opts.key;
    const laneKey = opts.laneKey;
    const current = state[key] || 'all';
    const lane = opts.lane || 'all';
    const total = rows.length;
    const unique = new Set(rows.map((row) => row.hero)).size;
    const lanes = LANES.filter((name) => rows.some((row) => row.lane === name));
    if (rows.some((row) => !isKnownLane(row.lane))) lanes.push('未标注');
    const laneTotal = (name) => rows.filter((row) => (isKnownLane(row.lane) ? row.lane : '未标注') === name).length;
    const groups = new Map();
    const all = new Map();
    for (const row of rows) {
      const name = isKnownLane(row.lane) ? row.lane : '未标注';
      if (!groups.has(name)) groups.set(name, new Map());
      const bucket = groups.get(name);
      const item = bucket.get(row.hero) || {hero: row.hero, count: 0, lane: name, type: ''};
      item.count++;
      if (!item.type && row.archetype) item.type = row.archetype;
      bucket.set(row.hero, item);
      const flat = all.get(row.hero) || {hero: row.hero, count: 0, lane: name, type: ''};
      flat.count++;
      if (!flat.type && row.archetype) flat.type = row.archetype;
      all.set(row.hero, flat);
    }
    const types = TYPE_ORDER.filter((type) => rows.some((row) => row.archetype === type && (lane === 'all' || row.lane === lane)));
    const cards = (list) => [...list].sort((a, b) => b.count - a.count || String(a.hero).localeCompare(String(b.hero), 'zh')).map((item) => `<button type="button" class="tp-herocard${current === item.hero ? ' is-on' : ''}" data-tp-filter="${key}" data-tp-value="${esc(item.hero)}" data-hero-name="${esc(item.hero)}" data-hero-type="${esc(item.type || '')}" aria-pressed="${current === item.hero}" title="${esc(`${item.hero} · ${fmt(item.count)} 人次${item.type ? ` · ${item.type}` : ''}`)}">
      <span class="tp-herocard-face">${String(portrait(item.hero, 'is-face')).replace(' loading="lazy"', '')}<em>${fmt(item.count)}</em></span>
      <b>${esc(item.hero)}</b>${item.type ? `<small class="tp-herocard-type"><i style="background:${colorOfKey(item.type)}"></i>${esc(item.type)}</small>` : ''}
    </button>`).join('');
    const laneButtons = `<button type="button" class="tp-heropick-lane${lane === 'all' ? ' is-on' : ''}" data-tp-filter="${laneKey}" data-tp-value="all" aria-pressed="${lane === 'all'}">五路<small>${fmt(total)}</small></button>${lanes.map((name) => `<button type="button" class="tp-heropick-lane${lane === name ? ' is-on' : ''}" data-tp-filter="${laneKey}" data-tp-value="${esc(name)}" aria-pressed="${lane === name}"><i style="background:${colorOfKey(name)}"></i>${esc(name)}<small>${fmt(laneTotal(name))}</small></button>`).join('')}`;
    const visibleUnique = lane === 'all' ? unique : new Set(rows.filter((row) => row.lane === lane).map((row) => row.hero)).size;
    const body = lane === 'all'
      ? `<div class="tp-heropick-grid" data-tp-hero-grid>${cards([...all.values()])}</div>`
      : groups.has(lane)
        ? `<div class="tp-heropick-grid" data-tp-hero-grid>${cards([...groups.get(lane).values()])}</div>`
        : '<p class="tp-lack">这条路没有可用英雄。</p>';
    const toolbar = `<div class="tp-heropick-tools">
      <label class="tp-herosearch"><span aria-hidden="true">⌕</span><input type="search" data-tp-hero-search="${key}" placeholder="搜英雄" autocomplete="off" aria-label="搜索英雄"></label>
      <div class="tp-herotypes" role="group" aria-label="按类型筛选英雄">
        <button type="button" class="tp-herotype is-on" data-tp-hero-type="all" aria-pressed="true">全部类型</button>
        ${types.map((type) => `<button type="button" class="tp-herotype" data-tp-hero-type="${esc(type)}" aria-pressed="false"><i style="background:${colorOfKey(type)}"></i>${esc(type)}</button>`).join('')}
      </div>
      <span class="tp-herocount" data-tp-hero-count>${fmt(visibleUnique)} 个英雄</span>
    </div>
    <p class="tp-hero-empty" data-tp-hero-empty hidden>没有匹配的英雄，清空搜索或换一个类型。</p>`;
    return `<div class="tp-heropick">
      <div class="tp-heropick-bar">
        <span class="tp-heropick-label">${esc(opts.label || '英雄')}</span>
        <div class="tp-heropick-lanes" role="group" aria-label="按分路查看英雄">${laneButtons}</div>
        <button type="button" class="tp-heroall${current === 'all' ? ' is-on' : ''}" data-tp-filter="${key}" data-tp-value="all" aria-pressed="${current === 'all'}" title="清除英雄筛选，回到 ${fmt(total)} 人次">
          <span class="tp-heroall-mark">Σ</span>
          <span class="tp-heroall-copy"><b>全部 ${fmt(total)}</b><small>人次 · ${fmt(unique)} 个英雄</small></span>
        </button>
      </div>
      ${toolbar}
      ${body}
    </div>`;
  }

  /* 英雄选择器的就地筛选：搜索 + 类型，不重绘、不丢焦点。 */
  function filterHeroPicker(picker) {
    if (!picker) return;
    const query = String(picker.querySelector('[data-tp-hero-search]')?.value || '').trim().toLowerCase();
    const active = picker.querySelector('.tp-herotype.is-on')?.dataset.tpHeroType || 'all';
    let count = 0;
    picker.querySelectorAll('[data-tp-hero-grid] .tp-herocard').forEach((card) => {
      const name = String(card.dataset.heroName || '').toLowerCase();
      const type = card.dataset.heroType || '';
      const show = (!query || name.includes(query)) && (active === 'all' || type === active);
      card.hidden = !show;
      if (show) count++;
    });
    const counter = picker.querySelector('[data-tp-hero-count]');
    if (counter) counter.textContent = `${fmt(count)} 个英雄`;
    const empty = picker.querySelector('[data-tp-hero-empty]');
    if (empty) empty.hidden = count > 0;
  }

  if (typeof document !== 'undefined' && !window.__tpHeroFilterBound) {
    window.__tpHeroFilterBound = true;
    document.addEventListener('input', (event) => {
      const input = event.target.closest?.('[data-tp-hero-search]');
      if (input) filterHeroPicker(input.closest('.tp-heropick'));
    });
    document.addEventListener('toggle', (event) => {
      if (event.target.matches?.('[data-tp-pickfold]')) bpHeroFoldOpen = event.target.open;
    }, true);
    document.addEventListener('click', (event) => {
      const button = event.target.closest?.('[data-tp-hero-type]');
      if (!button) return;
      const picker = button.closest('.tp-heropick');
      if (!picker) return;
      picker.querySelectorAll('.tp-herotype').forEach((item) => {
        const on = item === button;
        item.classList.toggle('is-on', on);
        item.setAttribute('aria-pressed', String(on));
      });
      filterHeroPicker(picker);
    });
  }

  if (typeof document !== 'undefined' && !window.__tpGridHoverBound) {
    window.__tpGridHoverBound = true;
    document.addEventListener('pointerover', (event) => {
      const cell = event.target.closest?.('[data-col]');
      const table = cell?.closest('table');
      document.querySelectorAll('table .is-col-hl').forEach((el) => { if (el.closest('table') !== table) el.classList.remove('is-col-hl'); });
      if (!table) return;
      table.querySelectorAll('.is-col-hl').forEach((el) => el.classList.remove('is-col-hl'));
      const col = cell.dataset.col;
      if (col == null) return;
      table.querySelectorAll(`[data-col="${col}"]`).forEach((el) => el.classList.add('is-col-hl'));
    });
  }

  if (typeof document !== 'undefined' && !window.__tpNoteBound) {
    window.__tpNoteBound = true;
    document.addEventListener('input', (event) => {
      const note = event.target.closest?.('[data-tp-note]');
      if (!note) return;
      const card = note.closest('.tp-card');
      const status = card?.querySelector('[data-tp-note-status]');
      const count = card?.querySelector('[data-tp-note-count]');
      if (count) count.textContent = `${note.value.length} / 2000`;
      clearTimeout(note.__tpNoteTimer);
      note.__tpNoteTimer = setTimeout(() => {
        try {
          const days = loadNoteDays(note.dataset.tpNote);
          days[note.dataset.noteDate] = note.value;
          saveNoteDays(note.dataset.tpNote, days);
          /* 同步日历上的绿点：写了就有，清空就去掉。 */
          const cell = document.querySelector(`[data-note-cal-day="${note.dataset.noteDate}"]`);
          if (cell) {
            const dot = cell.querySelector('.tp-note-dot');
            if (note.value.trim() && !dot) cell.insertAdjacentHTML('beforeend', '<i class="tp-note-dot"></i>');
            if (!note.value.trim() && dot) dot.remove();
          }
          if (status) {
            const stamp = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
            status.textContent = `已保存 ${stamp}`;
          }
        } catch {
          if (status) status.textContent = '本机无法保存';
        }
      }, 250);
    });
    /* 常用标注一键插入笔记；复制按钮把整段笔记带走。都复用 input 事件以触发自动保存。 */
    document.addEventListener('click', (event) => {
      /* 切换记录日期：直接换 textarea 内容，不重绘整页。 */
      /* 日历选日期 / 翻月 / 回到今天：直接换 textarea 与网格，不重绘整页。 */
      const calDay = event.target.closest?.('[data-note-cal-day]');
      if (calDay) {
        const c = calDay.closest('.tp-card');
        const note = c?.querySelector('[data-tp-note]');
        if (!note) return;
        const key = calDay.dataset.noteCalDay;
        noteSelectedDate = key;
        const days = loadNoteDays(note.dataset.tpNote);
        note.value = String(days[key] || '');
        note.dataset.noteDate = key;
        c.querySelector('[data-note-sel-label]').textContent = `${noteSelText(key)}`;
        c.querySelectorAll('[data-note-cal-day]').forEach((b) => {
          const on = b.dataset.noteCalDay === key;
          b.classList.toggle('is-sel', on);
          b.setAttribute('aria-pressed', String(on));
        });
        const status = c.querySelector('[data-tp-note-status]');
        const count = c.querySelector('[data-tp-note-count]');
        if (count) count.textContent = `${note.value.length} / 2000`;
        if (status) status.textContent = note.value ? '已保存' : '输入后自动保存';
        document.getElementById('tp-note-cal')?.hidePopover?.();
        c.querySelector('.tp-note-datebtn')?.focus();
        return;
      }
      const calStep = event.target.closest?.('[data-note-cal-step]');
      if (calStep) {
        const c = calStep.closest('.tp-card');
        const note = c?.querySelector('[data-tp-note]');
        if (!note) return;
        const base = noteCalMonth || noteTodayKey().slice(0, 7);
        const [y, m] = base.split('-').map(Number);
        const d = new Date(y, m - 1 + Number(calStep.dataset.noteCalStep), 1);
        noteCalMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        const days = loadNoteDays(note.dataset.tpNote);
        c.querySelector('[data-note-cal-title]').textContent = noteCalTitle();
        c.querySelector('.tp-note-cal-grid').innerHTML = noteCalGridHtml(days);
        return;
      }
      const calToday = event.target.closest?.('[data-note-cal-today]');
      if (calToday) {
        const c = calToday.closest('.tp-card');
        const note = c?.querySelector('[data-tp-note]');
        if (!note) return;
        noteSelectedDate = null;
        noteCalMonth = null;
        const key = noteTodayKey();
        const days = loadNoteDays(note.dataset.tpNote);
        note.value = String(days[key] || '');
        note.dataset.noteDate = key;
        c.querySelector('[data-note-sel-label]').textContent = `${noteSelText(key)}`;
        c.querySelector('[data-note-cal-title]').textContent = noteCalTitle();
        c.querySelector('.tp-note-cal-grid').innerHTML = noteCalGridHtml(days);
        const status = c.querySelector('[data-tp-note-status]');
        const count = c.querySelector('[data-tp-note-count]');
        if (count) count.textContent = `${note.value.length} / 2000`;
        if (status) status.textContent = note.value ? '已保存' : '输入后自动保存';
        document.getElementById('tp-note-cal')?.hidePopover?.();
        c.querySelector('.tp-note-datebtn')?.focus();
        return;
      }
      const tag = event.target.closest?.('[data-note-tag]');
      if (tag) {
        const note = tag.closest('.tp-card')?.querySelector('[data-tp-note]');
        if (!note) return;
        const text = tag.dataset.noteTag || '';
        const start = note.selectionStart ?? note.value.length;
        const end = note.selectionEnd ?? note.value.length;
        const before = note.value.slice(0, start);
        const after = note.value.slice(end);
        const joiner = before && !/[\s，。、；：]$/.test(before) ? '，' : '';
        const insert = joiner + text;
        note.value = before + insert + after;
        const caret = (before + insert).length;
        note.focus();
        note.setSelectionRange(caret, caret);
        note.dispatchEvent(new Event('input', {bubbles: true}));
        return;
      }
      const copy = event.target.closest?.('[data-note-copy]');
      if (copy) {
        const note = copy.closest('.tp-card')?.querySelector('[data-tp-note]');
        if (!note) return;
        const done = () => { const old = copy.dataset.label || copy.textContent; copy.dataset.label = old; copy.textContent = '已复制'; setTimeout(() => { copy.textContent = old; }, 1400); };
        if (navigator.clipboard?.writeText) navigator.clipboard.writeText(note.value).then(done).catch(() => {});
      }
    });
  }

  /* 就地更新标签卡与头部标签，不整页重绘，焦点留在原处。 */
  const paintTags = (root) => {
    if (!root || !model) return;
    const tags = loadTeamTags(model.t.id);
    root.querySelectorAll('[data-tp-tag-preset]').forEach((button) => {
      const on = tags.includes(button.dataset.tpTagPreset);
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', String(on));
      const mark = button.querySelector('i');
      if (mark) mark.textContent = on ? '✓' : '+';
    });
    const current = root.querySelector('[data-tp-tag-current]');
    if (current) current.innerHTML = tags.length
      ? tags.map((label) => `<span class="tp-utag-chip is-${tagKind(label)}">${esc(label)}<button type="button" class="tp-utag-remove" data-tp-tag-remove="${esc(label)}" aria-label="移除标签 ${esc(label)}" title="移除 ${esc(label)}">×</button></span>`).join('')
      : '<span class="tp-quiet">还没打标签</span>';
    const status = root.querySelector('[data-tp-tag-status]');
    if (status) status.textContent = tags.length ? `已打 ${fmt(tags.length)} 个标签 · 赛训组共享` : '';
    const head = root.querySelector('[data-tp-head-tags]');
    if (head) head.innerHTML = headTagChips(model);
  };
  if (typeof document !== 'undefined' && !window.__tpTagBound) {
    window.__tpTagBound = true;
    const writeTags = (root, tags) => { saveTeamTags(model?.t?.id, tags); paintTags(root); };
    document.addEventListener('click', (event) => {
      const preset = event.target.closest?.('[data-tp-tag-preset]');
      if (preset) {
        const label = preset.dataset.tpTagPreset;
        const tags = loadTeamTags(model?.t?.id);
        writeTags(preset.closest('.tp-page'), tags.includes(label) ? tags.filter((item) => item !== label) : [...tags, label]);
        return;
      }
      const remove = event.target.closest?.('[data-tp-tag-remove]');
      if (!remove) return;
      const root = remove.closest('.tp-page');
      const tags = loadTeamTags(model?.t?.id).filter((item) => item !== remove.dataset.tpTagRemove);
      writeTags(root, tags);
      /* 焦点落到下一枚删除按钮；没有就回输入框，不把用户丢回页首。 */
      const next = root?.querySelector('[data-tp-tag-remove]') || root?.querySelector('[data-tp-tag-input]');
      next?.focus();
    });
    document.addEventListener('submit', (event) => {
      const form = event.target.closest?.('[data-tp-tag-form]');
      if (!form) return;
      event.preventDefault();
      const input = form.querySelector('[data-tp-tag-input]');
      const label = String(input?.value || '').trim().slice(0, 20);
      if (label) {
        const tags = loadTeamTags(model?.t?.id);
        if (!tags.includes(label)) writeTags(form.closest('.tp-page'), [...tags, label]);
      }
      if (input) { input.value = ''; input.focus(); }
    });
  }

  /* ══ 数据 ══════════════════════════════════════════════════════ */
  function buildView(value, key, compareData, bpData, deepData, behaviorData) {
    const teams = value.teams || [];
    const t = teams.find((x) => x.id === key);
    if (!t) return null;
    const deep = deepData && (deepData.team || deepData.games) ? deepData : null;
    const meta = {...t, ...(deep?.team || {})};
    const own = {...(value.own || {}), ...(deep?.own || {})};
    const games = [...(meta.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const deepGames = [...(deep?.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const durations = games.map((g) => g.duration).filter((v) => has(v) && v > 0);
    const days = deepGames.map((g) => String(g.day || '')).filter(Boolean).sort();
    return {
      key, t, meta, own, cmp: compareData || {}, deep, bpData: bpData || {}, behaviorData: behaviorData || {},
      games, deepGames,
      oppName: meta.displayName || '对手',
      ownName: own.name || '本队',
      matches: meta.matches || games.length || 0,
      avgDuration: durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
      oppRate: (() => { const decided = (meta.wins || 0) + (meta.losses || 0); return decided ? (meta.losses || 0) / decided * 100 : null; })(),
      coverage: deep?.coverage || null,
      anchor: days.length ? days[days.length - 1] : '',
      days,
    };
  }

  function boMatch(game) {
    if (state.bo === 'all') return true;
    if (state.bo === 'none') return !game.bo;
    return Number(game.bo) === Number(state.bo);
  }

  function inRange(game, span) {
    const stamp = dayNum(game.day);
    const anchorNum = dayNum(model?.anchor);
    if (stamp == null || anchorNum == null) return false;
    if (!boMatch(game)) return false;
    if (span === 'all') return true;
    if (span === 'custom') {
      const from = dayNum(state.from), to = dayNum(state.to);
      if (from != null && stamp < from) return false;
      if (to != null && stamp > to) return false;
      return true;
    }
    const days = Number(span);
    return stamp <= anchorNum && anchorNum - stamp <= days;
  }

  const activeGames = (view) => (view ? view.deepGames.filter((game) => inRange(game, state.days)) : []);

  function previousGames(view) {
    if (!view || state.days === 'all' || state.days === 'custom') return [];
    const span = Number(state.days);
    const anchorNum = dayNum(view.anchor);
    if (anchorNum == null) return [];
    return view.deepGames.filter((game) => {
      const stamp = dayNum(game.day);
      if (stamp == null || !boMatch(game)) return false;
      const delta = anchorNum - stamp;
      return delta > span && delta <= span * 2;
    });
  }

  const NOTE_TAGS = ['前期入侵', '后期团战强', '怕强开', '运营稳', '节奏偏慢', '野辅联动好', '阵容吃配合', '翻盘能力强'];

  /* ── 战队标签（模块三）───────────────────────────────────────────
     教练按巅峰分 / 俱乐部给对手打标签：常用标签点一下打上、再点取消，
     俱乐部等自定义标签手填。按战队 id 存本机，和教练笔记同一口径，
     不改主数据、不动历史对局。 */
  const TAG_PRESETS = [
    {label: '巅峰2100', kind: 'peak', title: '对手里有巅峰分 2100+ 的选手'},
    {label: '百强', kind: 'peak', title: '对手里有巅峰百强选手'},
    {label: '国赛队', kind: 'elite', title: '打过全国大赛的队伍'},
  ];
  const TAG_LIMIT = 12;
  /* 标签 / 笔记都存赛训数据库（全组共享），localStorage 只作离线过渡缓存。 */
  const tagCache = new Map();
  const noteCache = new Map();
  let tagPresets = null;
  let sharedLoadedFor = null;
  const sharedPresets = () => (tagPresets && tagPresets.length ? tagPresets : TAG_PRESETS);
  const tagKind = (label) => sharedPresets().find((preset) => preset.label === label)?.kind || 'club';
  const tagStorageKey = (id) => `kpl-team-tags:${id || 'team'}`;
  function loadTeamTags(id) {
    if (tagCache.has(id)) return tagCache.get(id) || [];
    try {
      const parsed = JSON.parse(localStorage.getItem(tagStorageKey(id)) || '[]');
      if (!Array.isArray(parsed)) return [];
      return [...new Set(parsed.filter((value) => typeof value === 'string')
        .map((value) => value.trim()).filter(Boolean))].slice(0, TAG_LIMIT);
    } catch { return []; }
  }
  function saveTeamTags(id, tags) {
    const list = tags.slice(0, TAG_LIMIT);
    tagCache.set(id, list);
    window.__teamTagsDirty = true;
    try { localStorage.setItem(tagStorageKey(id), JSON.stringify(list)); } catch {}
    fetch('/api/studio/team-tags', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team: id, tags: list}),
    }).catch(() => {});
  }
  /* 渲染后把库里的标签 / 笔记取回来，覆盖本机缓存并重画这两个卡片。 */
  function loadSharedAsync(root) {
    const id = model?.t?.id;
    if (!id || sharedLoadedFor === id || typeof fetch === 'undefined') return;
    sharedLoadedFor = id;
    Promise.all([
      fetch('/api/studio/team-tags?team=' + encodeURIComponent(id)).then((r) => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/studio/team-notes?team=' + encodeURIComponent(id)).then((r) => r.ok ? r.json() : null).catch(() => null),
    ]).then(([tagData, noteData]) => {
      if (model?.t?.id !== id) return;
      if (tagData) {
        if (Array.isArray(tagData.presets) && tagData.presets.length) tagPresets = tagData.presets;
        tagCache.set(id, Array.isArray(tagData.tags) ? tagData.tags : []);
      }
      if (noteData && noteData.days && typeof noteData.days === 'object') noteCache.set(id, noteData.days);
      if (!root || !document.body.contains(root)) return;
      const area = root.querySelector('[data-tp-analysis]');
      if (area && typeof repaint === 'function') repaint(root);
      paintTags(root);
      /* repaint 重建了节头，新鲜度提示要补回去。 */
      window.__loadFreshness?.();
    });
  }

  let noteSelectedDate = null; /* null = 今天；否则 'YYYY-MM-DD' */
  let noteCalMonth = null;     /* 日历显示月 'YYYY-MM'；null = 今天所在月 */
  const noteDateKey = (offset) => {
    const d = new Date();
    d.setDate(d.getDate() - offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const noteTodayKey = () => noteDateKey(0);
  const noteSelectedKey = () => noteSelectedDate || noteTodayKey();
  /* 只用字符串 key 比较，不解析 ISO 字符串为 Date，避免时区漂移。 */
  const noteDayLabel = (key) => key === noteTodayKey() ? '今天' : key === noteDateKey(1) ? '昨天' : key === noteDateKey(2) ? '前天' : key.slice(5);
  /* 触发按钮上的完整文案：相对日期拼具体日期，更早的日期本身就是日期，不重复。 */
  const noteSelText = (key) => {
    const label = noteDayLabel(key);
    return label.includes('-') ? label : `${label} · ${key.slice(5)}`;
  };
  /* 按天存储：{ 'YYYY-MM-DD': 文本 }。兼容并迁移旧的单条笔记。 */
  function loadNoteDays(storageKey) {
    const teamKey = storageKey.replace('kpl-team-note-days:', '');
    if (noteCache.has(teamKey)) return noteCache.get(teamKey) || {};
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
      }
    } catch {}
    try {
      const old = localStorage.getItem(storageKey.replace('-days:', ':'));
      if (old) {
        const map = {[noteDateKey(0)]: old};
        try { localStorage.setItem(storageKey, JSON.stringify(map)); } catch {}
        return map;
      }
    } catch {}
    return {};
  }
  /* 日历网格：周一开头；有笔记的日子带绿点，选中日高亮，今天描边。 */
  function saveNoteDays(storageKey, days) {
    const teamKey = storageKey.replace('kpl-team-note-days:', '');
    noteCache.set(teamKey, days);
    try { localStorage.setItem(storageKey, JSON.stringify(days)); } catch {}
    fetch('/api/studio/team-notes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team: teamKey, days}),
    }).catch(() => {});
  }
  function noteCalGridHtml(days) {
    const month = noteCalMonth || noteTodayKey().slice(0, 7);
    const [y, m] = month.split('-').map(Number);
    const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;
    const total = new Date(y, m, 0).getDate();
    const todayKey = noteTodayKey(), selKey = noteSelectedKey();
    let cells = '';
    for (let i = 0; i < lead; i++) cells += '<span class="tp-note-cal-cell is-blank" aria-hidden="true"></span>';
    for (let day = 1; day <= total; day++) {
      const key = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const filled = !!String(days[key] || '').trim();
      const cls = ['tp-note-cal-cell'];
      if (key === selKey) cls.push('is-sel');
      if (key === todayKey) cls.push('is-today');
      cells += `<button type="button" class="${cls.join(' ')}" data-note-cal-day="${key}" aria-label="${key}${filled ? '，有笔记' : ''}" aria-pressed="${key === selKey}"><span>${day}</span>${filled ? '<i class="tp-note-dot"></i>' : ''}</button>`;
    }
    return cells;
  }
  function noteCalTitle() {
    const month = noteCalMonth || noteTodayKey().slice(0, 7);
    const [y, m] = month.split('-').map(Number);
    return `${y} 年 ${m} 月`;
  }
  function noteCard() {
    const storageKey = `kpl-team-note-days:${model?.key || 'team'}`;
    const days = loadNoteDays(storageKey);
    const selKey = noteSelectedKey();
    const note = String(days[selKey] || '');
    const tags = NOTE_TAGS.map((t) => `<button type="button" class="tp-note-tag" data-note-tag="${esc(t)}" title="插入「${esc(t)}」">+ ${esc(t)}</button>`).join('');
    const dows = ['一', '二', '三', '四', '五', '六', '日'].map((d) => `<span>${d}</span>`).join('');
    const history = Object.entries(days).filter(([, value]) => String(value || '').trim()).sort((a, b) => b[0].localeCompare(a[0]));
    const historyHtml = `<details class="tp-note-history">
      <summary>历史笔记 · ${fmt(history.length)} 天</summary>
      ${history.length
        ? `<div class="tp-note-history-list">${history.map(([key, text]) => `<button type="button" class="tp-note-history-item${key === selKey ? ' is-sel' : ''}" data-note-cal-day="${esc(key)}"><b>${esc(noteSelText(key))}</b><span>${esc(String(text).slice(0, 48))}</span></button>`).join('')}</div>`
        : '<p class="tp-note-history-empty"><i class="empty-dot"></i>还没有历史笔记，写下第一条吧。</p>'}
    </details>`;
    return card('教练笔记', '赛训组共享 · 按天记录', `<div class="tp-note-datesel">
      <button type="button" class="tp-note-datebtn" commandfor="tp-note-cal" command="toggle-popover" aria-label="选择笔记日期">
        <span class="tp-note-dateico" aria-hidden="true">▦</span>
        <span class="tp-note-datetext"><b data-note-sel-label>${esc(noteSelText(selKey))}</b><small>点开选日期 · 绿点＝已写</small></span>
        <span class="tp-note-caret" aria-hidden="true">▾</span>
      </button>
      <div id="tp-note-cal" popover class="tp-note-cal">
        <div class="tp-note-cal-head">
          <button type="button" class="tp-note-cal-nav" data-note-cal-step="-1" aria-label="上个月">‹</button>
          <b data-note-cal-title>${noteCalTitle()}</b>
          <button type="button" class="tp-note-cal-nav" data-note-cal-step="1" aria-label="下个月">›</button>
        </div>
        <div class="tp-note-cal-dow" aria-hidden="true">${dows}</div>
        <div class="tp-note-cal-grid" role="group" aria-label="选择日期">${noteCalGridHtml(days)}</div>
        <div class="tp-note-cal-foot"><span><i class="tp-note-dot"></i>有笔记</span><button type="button" class="tp-note-cal-today" data-note-cal-today>回到今天</button></div>
      </div>
    </div>
      <div class="tp-note-tags" role="group" aria-label="常用标注，点击插入笔记">${tags}</div>
      <textarea class="tp-note" data-tp-note="${esc(storageKey)}" data-note-date="${selKey}" maxlength="2000" placeholder="这队喜欢什么、怕什么、上次交手怎么输的…… 点上方标签可快速插入">${esc(note)}</textarea>
      <div class="tp-note-foot"><span data-tp-note-status>${note ? '已保存' : '输入后自动保存'}</span><span class="tp-note-count" data-tp-note-count>${note.length} / 2000</span><button type="button" class="tp-note-copy" data-note-copy>复制</button></div>
      ${historyHtml}`, 'is-wide');
  }

  /* ── 01 整体对照：一针见血的对比表 ──────────────────────────────
     每行一个有效指标，直接给「本队领先/落后多少」和「环比是改善还是下滑」。
     good 指明这个指标高好还是低好（死亡越低越好），据此判断占优方向与环比好坏。 */
  const CMP_METRICS = [
    {key: 'kills', label: '场均击杀', good: 'high', digits: 1},
    {key: 'deaths', label: '场均死亡', good: 'low', digits: 1},
    {key: 'assists', label: '场均助攻', good: 'high', digits: 1},
    {key: 'gold', label: '场均经济', good: 'high', digits: 1, scale: 1000, suffix: 'k'},
    {key: 'towers', label: '场均推塔', good: 'high', digits: 1},
    {key: 'dragons', label: '场均控龙', good: 'high', digits: 1},
  ];

  /* 取某队在某指标上的值：均取 sides[side].stats 该字段的场均。 */
  function metricOf(games, side, key) {
    if (!games.length) return null;
    const values = games.map((g) => g.sides?.[side]?.stats?.[key]).filter(has);
    return values.length ? mean(values) : null;
  }

  function baseBoard(games) {
    const prev = previousGames(model);
    const rows = [];
    let lead = 0, behind = 0, better = 0, worse = 0;
    let topEdge = null, topGap = null;
    for (const m of CMP_METRICS) {
      const opp = metricOf(games, 'enemy', m.key);
      const own = metricOf(games, 'own', m.key);
      if (!has(opp) && !has(own)) continue; // 这一指标双方都没数据（如控龙常缺），不占行
      /* eps 用指标原始单位：经济是原始金（500 金≈0.5k），否则 0.05k 内的差会被误报成"落后 0k"。 */
      const eps = m.key === 'gold' ? 500 : 0.05;
      const show = (v) => !has(v) ? '—' : `${fmt(m.scale ? v / m.scale : v, m.digits)}${m.unit || m.suffix || ''}`;
      /* 优势 = 本队优势幅度：高好指标取 own-opp，低好指标取 opp-own。正=本队占优。 */
      const edge = has(opp) && has(own) ? (m.good === 'high' ? own - opp : opp - own) : null;
      let gapText = '—', gapTone = 'is-even';
      if (has(edge)) {
        if (Math.abs(edge) < eps) gapText = '两队持平';
        else {
          gapText = `${edge > 0 ? '本队领先' : '本队落后'} ${show(Math.abs(edge))}`;
          gapTone = edge > 0 ? 'is-good' : 'is-bad';
          if (edge > 0) lead++; else behind++;
          const rec = {label: m.label, size: Math.abs(edge)};
          if (edge > 0 && (!topEdge || rec.size > topEdge.size)) topEdge = rec;
          if (edge < 0 && (!topGap || rec.size > topGap.size)) topGap = rec;
        }
      }
      /* 环比看本队：delta = 本队当前 - 上窗口，按 good 方向判好坏。 */
      const ownPrev = metricOf(prev, 'own', m.key);
      const delta = has(own) && has(ownPrev) ? own - ownPrev : null;
      let trendText = '—', trendTone = 'is-even';
      if (has(delta)) {
        if (Math.abs(delta) < eps) trendText = '持平';
        else {
          const good = m.good === 'high' ? delta > 0 : delta < 0;
          trendText = `${delta > 0 ? '↑' : '↓'} ${show(Math.abs(delta))}`;
          trendTone = good ? 'is-good' : 'is-bad';
          if (good) better++; else worse++;
        }
      }
      const trendBadge = trendText !== '—' ? `<small class="tp-duel-trend ${trendTone}">环比 ${trendText}</small>` : '';
      /* 固定四列：指标 / 对手 / 本队 / 差距。数字右对齐，位置在每行严格对齐。 */
      rows.push(`<div class="tp-duel ${gapTone}" role="listitem">
        <div class="tp-duel-name"><b>${esc(m.label)}</b>${trendBadge}</div>
        <span class="tp-duel-opp">${show(opp)}</span>
        <span class="tp-duel-own">${show(own)}</span>
        <div class="tp-duel-gap"><b>${gapText}</b></div>
      </div>`);
    }
    /* 顶部战绩牌：大比分一眼定调，下面一行点出最大强弱项。 */
    const tally = lead + behind;
    const headline = tally
      ? (behind === 0 ? '本队全面占优' : lead > behind ? '本队总体占优' : lead === behind ? '两队各有胜负' : '本队总体落后')
      : '暂无可比指标';
    const hero = `<div class="tp-cmp-hero">
      <div class="tp-cmp-score"><b>${lead}</b><i>:</i><b>${behind}</b><span>本队占优 · 对手占优</span></div>
      <div class="tp-cmp-headline"><b>${headline}</b>
        <div class="tp-cmp-highlights">
          ${topEdge ? `<span class="is-good">最强 <b>${esc(topEdge.label)}</b></span>` : ''}
          ${topGap ? `<span class="is-bad">最弱 <b>${esc(topGap.label)}</b></span>` : ''}
          ${better || worse ? `<span class="is-even">环比 <b>${better}↑ / ${worse}↓</b></span>` : ''}
        </div>
      </div>
    </div>`;
    const note = prev.length ? `环比＝上一个同长度窗口（${fmt(prev.length)} 局）` : '当前口径没有环比窗口';
    const head = `<div class="tp-duel tp-duel-head" aria-hidden="true"><span></span><span>对手</span><span>本队</span><span></span></div>`;
    return card('整体对照', `${fmt(games.length)} 局 · ${note}`, `${hero}
      <div class="tp-duels" role="list" aria-label="本队与对手的关键指标对决">${head}${rows.join('')}</div>`, 'is-wide');
  }

  /* ── 02 BP ───────────────────────────────────────────────────── */
  const draftGames = (games) => games.filter((game) => game.draft?.known && game.draft.ordered);

  function handRows(games, mode) {
    const rows = [];
    for (const game of draftGames(games)) {
      const list = game.draft.ordered?.enemy?.[mode] || [];
      list.forEach((entry, index) => rows.push({slot: index + 1, ...entry, archetype: normArch(entry.archetype), game}));
    }
    return rows;
  }

  /* 筛选收进一个下拉：看 / 手序 / 图表分路，不再铺三行胶囊。 */
  function bpControls() {
    const hands = [['all', '全部'], ['1', '第 1'], ['2', '第 2'], ['3', '第 3'], ['4', '第 4'], ['5', '第 5']];
    const modeLabel = state.mode === 'ban' ? 'Ban' : '选人';
    const handLabel = state.hand === 'all' ? '全部手序' : `第 ${state.hand} 手`;
    const laneLabel = state.lane === 'all' ? '五路' : state.lane;
    const chips = [];
    if (state.mode === 'ban') chips.push(['mode', 'pick', 'Ban 分布', '切回选人']);
    if (state.hand !== 'all') chips.push(['hand', 'all', `第 ${state.hand} 手`, '取消手序']);
    if (state.lane !== 'all') chips.push(['lane', 'all', `只看 ${state.lane}`, '回到五路']);
    if (state.bpHero !== 'all') chips.push(['bpHero', 'all', `英雄 ${state.bpHero}`, '取消单英雄']);
    const chipBar = chips.length ? `<div class="tp-activechips"><span>生效</span>${chips.map(([name, value, label, title]) => `<button type="button" class="tp-activechip" data-tp-filter="${name}" data-tp-value="${value}" title="${esc(title)}">${esc(label)}<i aria-hidden="true">×</i></button>`).join('')}<button type="button" class="tp-activechip is-clear" data-tp-filter="reset" data-tp-value="all">全部清除</button></div>` : '';
    return `<div class="tp-bpbar">
      <details class="tp-more">
        <summary class="tp-more-summary"><span class="tp-more-ico" aria-hidden="true">≡</span><b>筛选</b><small>${modeLabel} · ${handLabel} · ${laneLabel}</small><span class="tp-more-caret" aria-hidden="true">▾</span></summary>
        <div class="tp-more-panel">
          <div class="tp-more-group"><span>看</span><div class="tp-seg"><button type="button" class="tp-seg-btn" data-tp-filter="mode" data-tp-value="pick" aria-pressed="${state.mode === 'pick'}">选人</button><button type="button" class="tp-seg-btn" data-tp-filter="mode" data-tp-value="ban" aria-pressed="${state.mode === 'ban'}">Ban</button></div></div>
          <div class="tp-more-group"><span>手序</span><div class="tp-seg">${hands.map(([value, label]) => `<button type="button" class="tp-seg-btn" data-tp-filter="hand" data-tp-value="${value}" aria-pressed="${state.hand === value}">${esc(label)}</button>`).join('')}</div></div>
          <div class="tp-more-group"><span>图表分路</span><div class="tp-seg"><button type="button" class="tp-seg-btn" data-tp-filter="lane" data-tp-value="all" aria-pressed="${state.lane === 'all'}">五路</button>${LANES.map((lane) => `<button type="button" class="tp-seg-btn" data-tp-filter="lane" data-tp-value="${esc(lane)}" aria-pressed="${state.lane === lane}">${esc(lane.slice(0, 2))}</button>`).join('')}</div></div>
          <button type="button" class="tp-more-reset" data-tp-filter="reset" data-tp-value="all">恢复默认</button>
        </div>
      </details>
      ${chipBar}
    </div>`;
  }

  /* 英雄选择器收进 details，默认收起，避免一进分节就摊一整排头像。
     repaint 会重建 DOM，用模块变量记住展开状态，筛选/选英雄后不会意外合上。 */
  let bpHeroFoldOpen = false;
  function heroPickerFold(rows) {
    const inner = heroPicker(rows, {key: 'bpHero', laneKey: 'bpHeroLane', lane: state.bpHeroLane, label: '英雄'});
    const open = bpHeroFoldOpen ? ' open' : '';
    return `<details class="tp-pickfold"${open} data-tp-pickfold>
      <summary><span class="tp-pickfold-ico" aria-hidden="true">♟</span><span>选英雄看落点</span><small>${state.bpHero === 'all' ? '看他在第几手拿 / Ban' : `当前 ${esc(state.bpHero)}`}</small><span class="tp-pickfold-caret" aria-hidden="true">▾</span></summary>
      ${inner}
    </details>`;
  }

  /* 单个英雄的画像：拿与 Ban 各一条同款手序刻度条，一眼看出「常在第几手拿 / Ban」。 */
  function heroFocusCard(mode, state_bpHero, focusRows, controls, pickRows, banRows) {
    const slots = focusRows.map((row) => row.slot);
    const lane = LANES.map((name) => ({name, count: focusRows.filter((row) => row.lane === name).length})).sort((a, b) => b.count - a.count)[0];
    const type = distOf(focusRows.filter((row) => isKnownType(row.archetype)).map((row) => row.archetype)).sort((a, b) => b[1] - a[1])[0];
    const band = medianBand(slots);
    const bandText = band ? (band[0] === band[1] ? String(band[0]) : `${band[0]}–${band[1]}`) : '—';
    const modeText = modeOf(slots) ? modeOf(slots).values.join('/') : '—';
    /* 一条手序刻度条：每一手一段，段高按人次，峰值手高亮；下 marking 对齐手序号。 */
    const handTicks = (rows) => {
      const src = rows || [];
      const counts = [1, 2, 3, 4, 5].map((slot) => ({slot, count: src.filter((row) => row.slot === slot).length}));
      const peak = Math.max(...counts.map((c) => c.count), 1);
      const ticks = counts.map((c) => {
        const h = c.count ? Math.max(14, Math.round(c.count / peak * 100)) : 0;
        const isPeak = c.count === peak;
        return `<div class="tp-handtick${isPeak ? ' is-peak' : ''}${c.count ? '' : ' is-zero'}" title="第 ${c.slot} 手 · ${fmt(c.count)} 人次">
          <span class="tp-handtick-bar"><i style="height:${h}%"></i></span>
          <b>${c.count || ''}</b>
          <small>${c.slot} 手</small>
        </div>`;
      }).join('');
      return `<div class="tp-handchart-plot" role="img" aria-label="手序分布：${counts.map((c) => `第${c.slot}手${c.count}人次`).join('，')}">${ticks}</div>`;
    };
    const facts = [
      ['主要分路', lane ? esc(lane.name) : '—', lane ? `${fmt(lane.count)} 人次` : ''],
      ['主要类型', type ? esc(type[0]) : '—', type ? `${fmt(type[1])} 人次` : ''],
      ['中位手序', bandText, '手'],
      ['最常落在', modeText, '手'],
    ].map(([label, value, sub]) => `<div class="tp-focusfact"><small>${label}</small><b>${value}</b><em>${sub}</em></div>`).join('');
    return card(`${mode === 'ban' ? 'Ban' : '选人'} · ${esc(state_bpHero)}`, `${fmt(focusRows.length)} 人次 · 出手画像`, `${controls}
      <div class="tp-herofocus-head">
        <span class="tp-herofocus-face">${String(portrait(state_bpHero, 'is-face')).replace(' loading="lazy"', '')}</span>
        <div class="tp-herofocus-title"><small>正在单看</small><b>${esc(state_bpHero)}</b></div>
        <button type="button" class="tp-herofocus-exit" data-tp-filter="bpHero" data-tp-value="all">退出单看</button>
      </div>
      <div class="tp-handchart">
        <div class="tp-handchart-head"><b>常在第几手拿</b><small>从左到右＝第 1 手到第 5 手，柱子越高用得越多</small></div>
        ${handTicks(pickRows)}
      </div>
      <div class="tp-handchart">
        <div class="tp-handchart-head"><b>常在第几手 Ban</b><small>从左到右＝第 1 手到第 5 手，柱子越高用得越多</small></div>
        ${handTicks(banRows)}
      </div>
      <div class="tp-focusfacts">${facts}</div>`);
  }

  /* 对面常选 / 常 ban 前五：BP 页顶部的速览，按当前时间窗与赛制筛选，只算有手序的局。 */
  /* 各分路自己的常选 / 常 ban 前五，和总榜同一批有手序的局。 */
  function laneTopList(games, lane, mode = 'pick', limit = 5) {
    const counts = new Map();
    for (const row of handRows(games, mode)) {
      if (row.lane !== lane || !row.hero) continue;
      const entry = counts.get(row.hero) || {n: 0, own: 0, decided: 0};
      entry.n++;
      if (row.game.opponentWin === true || row.game.opponentWin === false) {
        entry.decided++;
        if (!row.game.opponentWin) entry.own++;
      }
      counts.set(row.hero, entry);
    }
    return [...counts.entries()]
      .map(([hero, entry]) => [hero, entry.n, entry.decided ? Math.round(entry.own / entry.decided * 100) : null])
      .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), 'zh-CN'))
      .slice(0, limit);
  }

  function enemyTopCard(games) {
    const known = draftGames(games);
    if (!known.length) return card('', '', lack('这批筛选里没有带手序的 BP。'));
    /* 常选 / 常 ban 都按五路各一张卡，同一批有手序的局。 */
    const laneCardsFor = (mode) => LANES.map((lane) => {
      const list = laneTopList(games, lane, mode);
      const total = list.reduce((sum, [, count]) => sum + count, 0);
      return card(lane, list.length ? `${fmt(total)} 人次` : '暂无数据',
        `<div class="tp-toprow">${list.map(([hero, count, rate]) => topHeroTile(hero, count, rate)).join('') || '<span class="tp-quiet">—</span>'}</div>`);
    }).join('');
    return `<div class="tp-lanecards-head">常选 · 各分路前五</div><div class="tp-lanecards">${laneCardsFor('pick')}</div>`
      + `<div class="tp-lanecards-head">常 ban · 各分路前五</div><div class="tp-lanecards">${laneCardsFor('ban')}</div>`;
  }

  function bpDistribution(games) {
    const mode = state.mode;
    let rows = handRows(games, mode);
    if (!rows.length) return card(mode === 'ban' ? 'Ban 分布' : '选人分布', '没有可用手序', `${bpControls()}${lack('这批筛选条件里没有带手序的 BP。')}`);
    if (state.hand !== 'all') rows = rows.filter((row) => row.slot === Number(state.hand));
    const laneRows = state.lane === 'all' ? rows : rows.filter((row) => row.lane === state.lane);
    const focusRows = state.bpHero === 'all' ? laneRows : rows.filter((row) => row.hero === state.bpHero);
    const scope = `${state.hand === 'all' ? '全部手序' : `第 ${state.hand} 手`}${state.lane === 'all' ? '' : ` · ${state.lane}`}`;
    if (!focusRows.length) return card(mode === 'ban' ? 'Ban 分布' : '选人分布', `${scope} · 0 人次`, `${bpControls()}${heroPickerFold(rows)}${lack('当前手序、分路或英雄没有记录，换一个条件再看看。')}`);
    /* 选到单个英雄：单独一张画像卡，不摊头像列表、不摆饼图。 */
    if (state.bpHero !== 'all') {
      const both = (m) => handRows(games, m).filter((row) => row.hero === state.bpHero
        && (state.hand === 'all' || row.slot === Number(state.hand))
        && (state.lane === 'all' || row.lane === state.lane));
      return heroFocusCard(mode, state.bpHero, focusRows, bpControls(), both('pick'), both('ban'));
    }

    /* 默认态只留英雄选择入口；分路类型构成已统一到 03「五路类型」，这里不再重复。 */
    return card(`${mode === 'ban' ? 'Ban' : '选人'} · 选英雄看落点`, `${scope} · ${fmt(focusRows.length)} 人次`, `${bpControls()}${heroPickerFold(rows)}`);
  }

  /* ── 03 阵容与风格 ────────────────────────────────────────────── */
  const enemyPicks = (game) => (game.sides?.enemy?.picks || []).map((pick) => (
    pick.archetype === '法核' ? { ...pick, archetype: '法刺' } : pick));
  const pickOfLane = (game, lane) => enemyPicks(game).find((pick) => pick.lane === lane) || null;

  function styleCard(games) {
    const rows = games.filter((game) => enemyPicks(game).length);
    if (!rows.length) return card('边野搭配', '没有选人明细', lack('这批局没有可用的选人明细。'));
    const cells = new Map();
    let total = 0;
    for (const game of rows) {
      const edge = pickOfLane(game, '对抗路');
      const jungle = pickOfLane(game, '打野');
      if (!edge || !jungle || !isKnownType(edge.archetype) || !isKnownType(jungle.archetype)) continue;
      total++;
      const key = `${edge.archetype}|${jungle.archetype}`;
      const cell = cells.get(key) || {games: 0, wins: 0};
      cell.games++;
      if (game.opponentWin === true) cell.wins++;
      cells.set(key, cell);
    }
    if (!total) return card('边野搭配', '类型未标注', lack('对抗路与打野的类型都还没标注。'));
    /* 每种实际出现的搭配一行：横条看占比，大字看局数与对手胜率。
       比 2×3 矩阵更搭这组数据——矩阵里的空格子和合计行在这里没有信息量。 */
    const combos = [...cells.entries()]
      .filter(([, cell]) => cell.games > 0)
      .map(([key, cell]) => {
        const [edge, jungle] = key.split('|');
        return {edge, jungle, games: cell.games, wins: cell.wins};
      })
      .sort((a, b) => b.games - a.games || a.edge.localeCompare(b.edge, 'zh'));
    const max = combos[0]?.games || 1;
    const body = combos.map((combo) => {
      const share = (combo.games / total) * 100;
      const cellGames = rows.filter((game) => {
        const e = pickOfLane(game, '对抗路'), j = pickOfLane(game, '打野');
        return e?.archetype === combo.edge && j?.archetype === combo.jungle;
      });
      const gid = gamesAttr(cellGames, `${combo.edge} + ${combo.jungle}`, ['对抗路', '打野']);
      const winRate = pct((combo.wins / combo.games) * 100);
      return `<div class="tp-edgecombo${gid ? ' is-drill' : ''}"${gid} title="${esc(`${combo.edge} + ${combo.jungle} · ${fmt(combo.games)} 局 · 占比 ${pct(share)} · 对手胜率 ${winRate}${gid ? '；点开看这 ' + cellGames.length + ' 局' : ''}`)}">
        <span class="tp-ec-name"><b>${esc(combo.edge)} + ${esc(combo.jungle)}</b></span>
        <span class="tp-ec-bar" aria-hidden="true"><i style="width:${((combo.games / max) * 100).toFixed(1)}%"></i></span>
        <span class="tp-ec-games"><b>${fmt(combo.games)}</b><small>局 · ${pct(share)}</small></span>
        <span class="tp-ec-win"><b>${winRate}</b><small>对手胜率</small></span>
      </div>`;
    }).join('');
    return card('边野搭配 · 前排与切入', `${fmt(total)} 局`, `<div class="tp-edgecombos">
      <div class="tp-edgecombo is-head"><span>搭配</span><span></span><span>出现</span><span>对手胜率</span></div>
      ${body}
    </div>`, 'is-wide');
  }

  function coreCard(games) {
    const rows = games.map((game) => game.sides?.enemy?.lineup).filter((lineup) => lineup && lineup.total);
    if (!rows.length) return card('核数', '没有阵容标签', lack('这批局没有可用的类型标注。'));
    const cores = rows.map((lineup) => lineup.cores);
    const items = [1, 2, 3, 4, 5].map((core) => ({key: `${core} 核`, core, count: cores.filter((value) => value === core).length, games: games.filter((game) => game.sides?.enemy?.lineup?.cores === core)})).filter((item) => item.count);
    return card('核数', '', `<div class="tp-rose-wrap">${rose(items, {size: 240, caption: '局', colorOf: (item) => CORE_COLOR[items.indexOf(item) % 4], gamesOf: (item) => item.games})}</div>`);
  }

  function laneTypeCard(games) {
    const rows = games.filter((game) => enemyPicks(game).length);
    if (!rows.length) return card('五路类型', '没有选人明细', lack('这批局没有可用的选人明细。'));
    const items = LANES.map((lane) => {
      const typed = rows.filter((game) => isKnownType(pickOfLane(game, lane)?.archetype));
      return {
        lane,
        total: typed.length,
        segments: ARCH[lane].map((type) => ({key: type, count: typed.filter((game) => pickOfLane(game, lane)?.archetype === type).length})).filter((seg) => seg.count),
      };
    });
    const body = items.map((item) => {
      if (!item.total) return `<div class="tp-lanerow is-empty"><div class="tp-lanerow-head"><b>${esc(item.lane)}</b></div><p class="tp-lack">这一路还没有类型标注。</p></div>`;
      const segments = item.segments.map((seg) => {
        const share = (seg.count / item.total) * 100;
        const segGames = rows.filter((game) => pickOfLane(game, item.lane)?.archetype === seg.key);
        const gid = gamesAttr(segGames, `${item.lane} · ${seg.key}`, [item.lane]);
        return `<span class="tp-lanerow-seg${gid ? ' is-drill' : ''}" data-col="${TYPE_ORDER.indexOf(seg.key)}" style="width:${share.toFixed(2)}%;background:${colorOfKey(seg.key)}"${gid} title="${esc(`${item.lane} · ${seg.key} · ${fmt(seg.count)} 局（${pct(share)}）；点开看这 ${fmt(segGames.length)} 局`)}"></span>`;
      }).join('');
      const list = item.segments.map((seg) => `<span><i style="background:${colorOfKey(seg.key)}"></i><b>${esc(seg.key)}</b><em>${fmt(seg.count)} 局</em><small>${pct((seg.count / item.total) * 100)}</small></span>`).join('');
      return `<div class="tp-lanerow"><div class="tp-lanerow-head"><b>${esc(item.lane)}</b></div><div class="tp-lanerow-bar">${segments}</div><div class="tp-lanerow-list">${list}</div></div>`;
    }).join('');
    return card('五路类型', '', `<div class="tp-lanetypes">${body}</div>`);
  }

  /* 战队层面的英雄池交叉：和大场页共用同一份版面，只是范围换成
     「当前筛选内、这支对手与我方的交手局」。公共英雄＝两队都选出过。 */
  function poolCrossCard(games) {
    const rows = new Map();
    for (const game of games) {
      for (const [side, picks] of [['own', game.sides?.own?.picks], ['foe', enemyPicks(game)]]) {
        for (const pick of picks || []) {
          const hero = pick.name;
          if (!hero) continue;
          const row = rows.get(hero) || { hero, lane: pick.lane || '', type: normArch(pick.archetype) || '', ownApps: 0, foeApps: 0, ownPick: false, foePick: false };
          if (side === 'own') { row.ownApps++; row.ownPick = true; } else { row.foeApps++; row.foePick = true; }
          if (!row.lane && pick.lane) row.lane = pick.lane;
          if (!row.type && pick.archetype) row.type = normArch(pick.archetype);
          rows.set(hero, row);
        }
      }
    }
    const list = [...rows.values()];
    if (!list.length) return card('', '', lack('这批局没有可用的选人明细。'), 'is-wide');
    for (const row of list) row.status = row.ownApps && row.foeApps ? 'both' : row.ownApps ? 'own' : 'foe';
    /* 分区面板本身已经写明队名与「只有这支战队用过」，不再重复卡头计数与口径说明。 */
    return card('', '', renderHeroPoolCross(list, { esc, portrait }, {
        ownName: (typeof h.teamName === 'function' ? h.teamName() : '') || model?.ownName || '本队',
        foeName: model?.oppName || '对手',
      }), 'is-wide');
  }

  /* ── Ban 后替补（BP 页末尾） ──────────────────────────────────── */
  function poolCard(games) {
    const known = draftGames(games);
    if (!known.length) return card('被 ban 之后拿谁', '没有手序', lack('这批局没有可用的 BP 手序。'));
    /* 我们 ban 掉某只英雄之后，他们在同一条路实际拿了谁；带上替补的类型。 */
    const raw = [];
    for (const game of known) {
      const byLane = new Map(enemyPicks(game).map((pick) => [pick.lane, pick]));
      for (const ban of (game.draft.ordered.own.ban || [])) {
        if (!ban?.hero || !isKnownLane(ban.lane)) continue;
        const pick = byLane.get(ban.lane);
        if (!pick) continue;
        raw.push({from: ban.hero, fromType: isKnownType(ban.archetype) ? ban.archetype : '', lane: ban.lane, to: pick.name, toType: isKnownType(pick.archetype) ? pick.archetype : '', count: 1});
      }
    }
    const merged = new Map();
    for (const link of raw) {
      const key = `${link.from}|${link.to}`;
      const item = merged.get(key) || {from: link.from, lane: link.lane, to: link.to, toType: link.toType, count: 0};
      item.count++;
      merged.set(key, item);
    }
    const links = [...merged.values()].sort((a, b) => b.count - a.count);
    const selected = state.poolHero;
    const heroBar = heroPicker(raw.map((link) => ({hero: link.from, lane: link.lane, archetype: link.fromType})), {key: 'poolHero', laneKey: 'poolHeroLane', lane: state.poolHeroLane, label: '被我们 ban 的英雄'});

    if (!links.length) {
      return card('被 ban 之后拿谁', `${fmt(known.length)} 局有手序`, lack('这批筛选里没有「我们 ban 了、他们同路改拿」的记录。'));
    }

    if (selected !== 'all' && links.some((link) => link.from === selected)) {
      const selLinks = links.filter((link) => link.from === selected);
      const lane = selLinks[0]?.lane || '';
      const picked = new Map();
      for (const link of selLinks) picked.set(link.to, {hero: link.to, games: link.count, type: link.toType});
      const list = [...picked.values()].sort((a, b) => b.games - a.games);
      const typeCounts = new Map();
      for (const link of selLinks) if (link.toType) typeCounts.set(link.toType, (typeCounts.get(link.toType) || 0) + link.count);
      const types = [...typeCounts.entries()].sort((a, b) => b[1] - a[1]);
      const untyped = selLinks.filter((link) => !link.toType).reduce((sum, link) => sum + link.count, 0);
      const total = selLinks.reduce((sum, link) => sum + link.count, 0) || 1;
      return card(`${selected} 被 ban 之后`, `${fmt(total)} 次 · ${esc(lane || '同路')}`, `${heroBar}
        <div class="tp-focusbar">
          <span class="tp-focusbar-face">${String(portrait(selected, 'is-face')).replace(' loading="lazy"', '')}</span>
          <span class="tp-focusbar-copy"><small>正在单看</small><b>${esc(selected)}</b></span>
          <button type="button" class="tp-focusbar-exit" data-tp-filter="poolHero" data-tp-value="all">退出单看 · 回到整池</button>
        </div>
        <div class="tp-replace-view">
          <div class="tp-replace-flow">${flowChart(selLinks, {leftLimit: 1, rightLimit: 8})}</div>
          <div class="tp-replace-side">
            <div class="tp-sun-block"><small>替补的类型分布</small>
              <div class="tp-typelist">${types.map(([type, count]) => `<span><i style="background:${colorOfKey(type)}"></i><b>${esc(type)}</b><em>${pct((count / total) * 100)}</em><small>${fmt(count)} 次</small></span>`).join('')}${untyped ? `<span><i style="background:var(--c-muted)"></i><b>未标注</b><em>${pct((untyped / total) * 100)}</em><small>${fmt(untyped)} 次</small></span>` : ''}</div>
            </div>
            <div class="tp-sun-block"><small>具体拿了谁 · 点英雄看详情</small><div class="tp-replace-grid">${list.slice(0, 8).map((item) => poolHeroCard(item.hero, item.games, item.type)).join('') || '<span class="tp-quiet">—</span>'}</div></div>
          </div>
        </div><p class="tp-read">左是我们 ban 的 ${esc(selected)}，右是他们同一路改拿的英雄；右侧给出替补的类型分布和具体英雄卡，直接能看出「ban 掉之后他们换的是同一类还是换了思路」。只统计有手序、且对手同路有选人的局。</p>`);
    }

    return card('被 ban 之后拿谁', `${fmt(links.length)} 组改拿 · ${fmt(known.length)} 局有手序`, `<div class="tp-flowsection is-lead"><header><b>点英雄头像，只看那一只被 ban 之后的同路替补</b><small>角标是人次</small></header>${heroBar}${flowChart(links, {leftLimit: 6, rightLimit: 8})}</div>
      <p class="tp-read">只统计有手序、且我们 ban 掉后对手同路有选人的局。</p>`);
  }

  /* ── BP 2.0（2026-11-22）：四个直接改变 ban / pick 的分析 ─────────
     1) 英雄优先级象限：他们愿不愿意选 × 拿到后赢不赢；
     2) 赢/输局 BP 指纹：赢的局和输的局，首抢 / 一 ban / 阵容结构差在哪；
     3) 条件响应：我们 ban X 后，他们一抢什么、二抢什么；
     4) 招牌 ban 后改拿：按选手看招牌被 ban 后的同路替补。
     四块都只消费当前筛选后的局，样本量写在卡头。 */
  const bpOrdered = (game) => game?.draft?.ordered?.enemy || {pick: [], ban: []};
  const bpDraft = (games) => games.filter((game) => game.draft?.known
    && ((bpOrdered(game).pick || []).length || (bpOrdered(game).ban || []).length));
  const bpWin = (game) => Boolean(game.opponentWin);
  const bpRate = (wins, games) => (games ? wins / games * 100 : null);
  const bpPct = (value) => (has(value) ? pct(value) : '—');
  const bpBans = (game) => (game.draft?.ordered?.own?.ban || []).map((row) => row.hero).filter(Boolean);
  const bpUnique = (list) => [...new Set((list || []).filter(Boolean))];

  /* ── 1. 英雄优先级象限 ─────────────────────────────────────────── */
  function bpPriorityData(games) {
    const picks = new Map(), bans = new Map();
    for (const game of games) {
      for (const pick of (game.sides?.enemy?.picks || [])) {
        if (!pick?.name) continue;
        const row = picks.get(pick.name) || {hero: pick.name, lane: pick.lane || '', games: 0, wins: 0, list: []};
        row.games++; row.wins += bpWin(game) ? 1 : 0; row.list.push(game);
        row.lane ||= pick.lane || '';
        picks.set(pick.name, row);
      }
      for (const hero of bpBans(game)) {
        const row = bans.get(hero) || {hero, lane: '', games: 0, list: []};
        row.games++; row.list.push(game);
        bans.set(hero, row);
      }
    }
    const all = bpUnique([...picks.keys(), ...bans.keys()]).map((hero) => {
      const p = picks.get(hero), b = bans.get(hero);
      return {
        hero,
        lane: p?.lane || b?.lane || '',
        pickGames: p?.games || 0,
        pickWins: p?.wins || 0,
        winRate: p ? bpRate(p.wins, p.games) : null,
        pickRate: games.length ? (p?.games || 0) / games.length * 100 : 0,
        banGames: b?.games || 0,
        banRate: games.length ? (b?.games || 0) / games.length * 100 : 0,
        presence: games.length ? ((p?.games || 0) + (b?.games || 0)) / games.length * 100 : 0,
        games: bpUnique([...(p?.list || []), ...(b?.list || [])]),
      };
    }).sort((a, b) => b.presence - a.presence);
    const picked = all.filter((row) => row.pickGames > 0);
    /* 竖线用「至少 3 局」做决策阈值，比中位数更稳定：1 局英雄太多会把线压到 4%。 */
    const xLine = Math.max(8, Math.min(20, 3 / Math.max(1, games.length) * 100));
    const xMax = Math.max(20, Math.ceil((Math.max(0, ...picked.map((row) => row.pickRate)) + 1) / 10) * 10);
    const base = bpRate(games.filter(bpWin).length, games.length) ?? 50;
    return {all, picked, bannedOnly: all.filter((row) => !row.pickGames && row.banGames), base, xLine, xMax};
  }

  function bpPriorityCard(games) {
    const data = bpPriorityData(games);
    if (!data.picked.length && !data.bannedOnly.length) {
      return card('英雄优先级', '', lack('这批局没有可用的选人 / Ban 记录。'), 'is-bp-card');
    }
    const plotted = data.picked.slice(0, 20);
    const dots = plotted.map((row, index) => {
      const x = 4 + (row.pickRate / data.xMax) * 92;
      const y = 6 + ((row.winRate ?? data.base) / 100) * 88;
      const size = row.pickGames >= 4 ? 'is-big' : row.pickGames >= 2 ? 'is-mid' : 'is-small';
      const labeled = index < 6;
      const title = `${row.hero} · 选用 ${row.pickGames} 局（${bpPct(row.winRate)} 胜率）· 被我们 ban ${row.banGames} 局`;
      return `<button type="button" class="tp-qdot ${size}${labeled ? ' is-labeled' : ''}" style="left:${x.toFixed(2)}%;bottom:${y.toFixed(2)}%"${gamesAttr(row.games, title)} title="${esc(title)}" aria-label="${esc(title)}">
        <span class="tp-qdot-face" style="border-color:${colorOfKey(row.lane)}">${portrait(row.hero, 'is-qface')}</span>
        ${labeled ? `<b>${esc(row.hero)}</b>` : ''}
        ${labeled && row.banGames ? `<em>ban ${Math.round(row.banRate)}%</em>` : ''}
      </button>`;
    }).join('');
    const bannedOnly = data.bannedOnly.length ? `<div class="tp-qonly"><span>只被 ban / 未选用</span>${data.bannedOnly.slice(0, 8).map((row) => heroChip(row.hero, row.banGames, `${row.hero} · 被我们 ban ${row.banGames} 局`)).join('')}</div>` : '';
    const table = dataTable(
      ['英雄', '分路', '选用', '胜率', '被我们 ban'],
      data.all.slice(0, 20).map((row) => [esc(row.hero), esc(row.lane || '—'), `${fmt(row.pickGames)} 局`, bpPct(row.winRate), `${fmt(row.banGames)} 局`]),
      '图上取 presence 前 20 只，完整前 20 见本表；悬停 / 点开头像看对应对局。'
    );
    return card('英雄优先级', `${fmt(games.length)} 局 · 基准 ${bpPct(data.base)} · 图取前 20`, `
      <div class="tp-quad" role="img" aria-label="英雄优先级四象限：横轴选用率，纵轴拿到后胜率">
        <span class="tp-quad-ylabel">拿到后胜率</span>
        <div class="tp-quad-plot">
          <i class="tp-quad-tint is-steal" style="left:0;width:${(data.xLine / data.xMax) * 100}%;top:0;bottom:${data.base}%"></i>
          <i class="tp-quad-tint is-must" style="left:${(data.xLine / data.xMax) * 100}%;right:0;top:0;bottom:${data.base}%"></i>
          <i class="tp-quad-tint is-low" style="left:0;width:${(data.xLine / data.xMax) * 100}%;top:${100 - data.base}%;bottom:0"></i>
          <i class="tp-quad-tint is-bait" style="left:${(data.xLine / data.xMax) * 100}%;right:0;top:${100 - data.base}%;bottom:0"></i>
          <span class="tp-quad-area is-steal">可抢 / 尊重</span>
          <span class="tp-quad-area is-must">必 ban</span>
          <span class="tp-quad-area is-low">低优先</span>
          <span class="tp-quad-area is-bait">可放</span>
          <span class="tp-quad-ytick" style="bottom:0%">0%</span>
          <span class="tp-quad-ytick" style="bottom:50%">50%</span>
          <span class="tp-quad-ytick" style="bottom:100%">100%</span>
          <i class="tp-quad-line is-h" style="bottom:${data.base}%"></i>
          <i class="tp-quad-line is-v" style="left:${(data.xLine / data.xMax) * 100}%"></i>
          ${dots}
        </div>
        <div class="tp-quad-xticks">${[0, 1 / 3, 2 / 3, 1].map((part) => `<span style="left:${(part * 100).toFixed(1)}%">${Math.round(data.xMax * part)}%</span>`).join('')}</div>
        <div class="tp-quad-x"><span>选用率 →</span><span>虚线：3 局阈值 ${bpPct(data.xLine)} · 基准 ${bpPct(data.base)}</span><span>点大小＝选用局数</span></div>
      </div>
      ${bannedOnly}
      <p class="tp-read">右上＝他们常选且拿到后赢得多，优先 ban；右下＝常选但赢不多，可以放；左上＝不常选、拿到却赢，别轻易放；左下＝低优先。ban% 是我们目前 ban 掉它的比例。</p>
      ${table}`, 'is-bp-card');
  }

  /* ── 2. 赢 / 输局 BP 指纹 ─────────────────────────────────────── */
  function bpFingerprintData(games) {
    const known = bpDraft(games);
    const win = known.filter(bpWin), loss = known.filter((game) => !bpWin(game));
    const firstPick = (game) => (bpOrdered(game).pick || [])[0] || null;
    const firstBan = (game) => (bpOrdered(game).ban || [])[0] || null;
    const laneRows = (list, picker) => {
      const total = list.length || 1;
      return LANES.map((lane) => ({lane, games: list.filter((game) => picker(game)?.lane === lane).length}))
        .filter((row) => row.games)
        .map((row) => ({...row, share: row.games / total * 100}))
        .sort((a, b) => b.games - a.games);
    };
    const heroRows = (list) => {
      const map = new Map();
      for (const game of list) {
        const first = firstPick(game);
        const hero = first?.hero;
        if (!hero) continue;
        const row = map.get(hero) || {hero, lane: first?.lane || '', games: 0, list: []};
        row.games++; row.list.push(game); row.lane ||= first?.lane || ''; map.set(hero, row);
      }
      return [...map.values()].sort((a, b) => b.games - a.games);
    };
    const lineupOf = (game) => game.sides?.enemy?.lineup;
    const coreRate = (list) => {
      const usable = list.filter((game) => has(lineupOf(game)?.cores));
      return usable.length ? usable.filter((game) => Number(lineupOf(game).cores) >= 4).length / usable.length * 100 : null;
    };
    const avgCores = (list) => {
      const values = list.map((game) => lineupOf(game)?.cores).filter(has);
      return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    };
    const noFrontRate = (list) => {
      const usable = list.filter((game) => has(lineupOf(game)?.front));
      return usable.length ? usable.filter((game) => Number(lineupOf(game).front) === 0).length / usable.length * 100 : null;
    };
    return {
      known, win, loss,
      firstPickWin: laneRows(win, firstPick), firstPickLoss: laneRows(loss, firstPick),
      firstBanWin: laneRows(win, firstBan), firstBanLoss: laneRows(loss, firstBan),
      heroWin: heroRows(win), heroLoss: heroRows(loss),
      coreWin: coreRate(win), coreLoss: coreRate(loss),
      avgCoreWin: avgCores(win), avgCoreLoss: avgCores(loss),
      noFrontWin: noFrontRate(win), noFrontLoss: noFrontRate(loss),
    };
  }

  function bpFingerprintCard(games) {
    const data = bpFingerprintData(games);
    if (!data.known.length) return card('赢 / 输局 BP 指纹', '', lack('这批局没有可用的 BP 手序。'));
    const bar = (rows) => `<span class="tp-fp-bar">${rows.map((row) => `<i style="width:${row.share.toFixed(1)}%;background:${colorOfKey(row.lane)}" title="${esc(`${row.lane} · ${row.games} 局`)}"></i>`).join('')}</span>`;
    const top = (rows) => (rows[0] ? `${esc(rows[0].lane)} ${Math.round(rows[0].share)}%` : '—');
    const cell = (list, rows, label) => (list.length
      ? `<button type="button" class="tp-fp-cell"${gamesAttr(list, label)}>${bar(rows)}<span>${top(rows)}</span></button>`
      : '<span class="tp-fp-cell is-empty">没有记录</span>');
    const fillCell = (list, value, text, label) => (list.length
      ? `<button type="button" class="tp-fp-cell"${gamesAttr(list, label)}><span class="tp-fp-fill"><i style="width:${has(value) ? Math.max(0, Math.min(100, value)) : 0}%"></i></span><span>${text}</span></button>`
      : '<span class="tp-fp-cell is-empty">没有记录</span>');
    const heroCell = (list, rows, label) => (list.length
      ? `<div class="tp-fp-heroes">${rows.slice(0, 3).map((row) => `<button type="button" class="tp-fp-hero"${gamesAttr(row.list, `${label} · 首抢 ${row.hero}`)}><i class="tp-fp-hero-lane" style="background:${colorOfKey(row.lane)}" aria-hidden="true"></i>${portrait(row.hero, 'is-face')}<b>${esc(row.hero)}</b><small>${fmt(row.games)}</small></button>`).join('') || '<span class="tp-quiet">—</span>'}</div>`
      : '<span class="tp-fp-cell is-empty">没有记录</span>');
    const row = (label, winCell, lossCell) => `<div class="tp-fp-row"><div class="tp-fp-label">${label}</div>${winCell}${lossCell}</div>`;
    const gaps = [
      {key: '无前排率', win: data.noFrontWin, loss: data.noFrontLoss},
      {key: '4 核率', win: data.coreWin, loss: data.coreLoss},
    ].filter((item) => has(item.win) && has(item.loss))
      .sort((a, b) => Math.abs(b.loss - b.win) - Math.abs(a.loss - a.win));
    const gap = gaps[0];
    return card('赢 / 输局 BP 指纹', `${fmt(data.known.length)} 局有手序 · 赢 ${fmt(data.win.length)} / 输 ${fmt(data.loss.length)}`, `
      <div class="tp-fp-head"><span></span><b>赢局 ${fmt(data.win.length)}</b><b>输局 ${fmt(data.loss.length)}</b></div>
      ${gap ? `<div class="tp-fp-insight"><b>最大差异 · ${gap.key}</b><span>赢局 ${bpPct(gap.win)} · 输局 ${bpPct(gap.loss)}</span></div>` : ''}
      ${row('首抢分路', cell(data.win, data.firstPickWin, '赢局 · 首抢分路'), cell(data.loss, data.firstPickLoss, '输局 · 首抢分路'))}
      ${row('一 ban 分路', cell(data.win, data.firstBanWin, '赢局 · 一 ban 分路'), cell(data.loss, data.firstBanLoss, '输局 · 一 ban 分路'))}
      ${row('4 核率', fillCell(data.win, data.coreWin, `4 核 ${bpPct(data.coreWin)} · 平均 ${has(data.avgCoreWin) ? data.avgCoreWin.toFixed(1) : '—'} 核`, '赢局 · 4 核阵容'), fillCell(data.loss, data.coreLoss, `4 核 ${bpPct(data.coreLoss)} · 平均 ${has(data.avgCoreLoss) ? data.avgCoreLoss.toFixed(1) : '—'} 核`, '输局 · 4 核阵容'))}
      ${row('无前排率', fillCell(data.win, data.noFrontWin, `无前排 ${bpPct(data.noFrontWin)}`, '赢局 · 无前排'), fillCell(data.loss, data.noFrontLoss, `无前排 ${bpPct(data.noFrontLoss)}`, '输局 · 无前排'))}
      ${row('首抢英雄', heroCell(data.win, data.heroWin, '赢局'), heroCell(data.loss, data.heroLoss, '输局'))}
      <p class="tp-read">只统计有手序的局；百分比以该侧局数为分母。点任一行看对应对局，点首抢英雄只看那只英雄的局。赢局和输局的差别是观察，不是因果。</p>`, 'is-fingerprint is-bp-card');
  }

  /* ── 3. 条件响应：我们 ban → 他们一抢 → 他们二抢 ─────────────── */
  function bpResponseData(games) {
    const known = bpDraft(games);
    const byBan = new Map();
    for (const game of known) {
      const picks = bpOrdered(game).pick || [];
      const first = picks[0];
      if (!first?.hero) continue;
      for (const ban of (game.draft?.ordered?.own?.ban || [])) {
        const banHero = ban.hero;
        if (!banHero) continue;
        const row = byBan.get(banHero) || {hero: banHero, lane: ban.lane || '', games: 0, wins: 0, list: [], first: new Map()};
        row.games++; row.wins += bpWin(game) ? 1 : 0; row.list.push(game);
        row.lane ||= ban.lane || '';
        const f = row.first.get(first.hero) || {hero: first.hero, lane: first.lane || '', games: 0, wins: 0, list: [], second: new Map()};
        f.games++; f.wins += bpWin(game) ? 1 : 0; f.list.push(game);
        const second = picks[1];
        if (second?.hero) {
          const s = f.second.get(second.hero) || {hero: second.hero, lane: second.lane || '', games: 0, wins: 0, list: []};
          s.games++; s.wins += bpWin(game) ? 1 : 0; s.list.push(game);
          f.second.set(second.hero, s);
        }
        row.first.set(first.hero, f);
        byBan.set(banHero, row);
      }
    }
    return [...byBan.values()]
      .map((row) => ({...row, list: bpUnique(row.list), first: [...row.first.values()].sort((a, b) => b.games - a.games)}))
      .sort((a, b) => b.games - a.games);
  }

  function bpResponseCard(games) {
    const rows = bpResponseData(games);
    if (!rows.length) return card('条件响应 · ban 之后他们怎么拿', '', lack('这批局没有「我们 ban → 他们一抢」的完整手序。'), 'is-bp-card');
    if (!rows.some((row) => row.hero === state.responseBan)) state.responseBan = rows[0].hero;
    const row = rows.find((item) => item.hero === state.responseBan) || rows[0];
    const firsts = row.first;
    if (!firsts.some((item) => item.hero === state.responsePick)) state.responsePick = firsts[0]?.hero || '';
    const pick = firsts.find((item) => item.hero === state.responsePick) || firsts[0] || null;
    const seconds = pick ? [...pick.second.values()].sort((a, b) => b.games - a.games) : [];
    const pathGames = pick ? pick.list : row.list;
    const node = (item, kind, on, attrs, note) => {
      const share = kind === 'ban' ? null : (item.games / (kind === 'pick' ? row.games : pick.games) * 100);
      const title = `${item.hero} · ${fmt(item.games)} 局${has(item.wins) ? ` · 他们胜率 ${bpPct(bpRate(item.wins, item.games))}` : ''}`;
      const filterAttrs = kind === 'ban'
        ? ` data-tp-filter="responseBan" data-tp-value="${esc(item.hero)}"`
        : kind === 'pick' ? ` data-tp-filter="responsePick" data-tp-value="${esc(item.hero)}"` : '';
      return `<button type="button" class="tp-rsp-node is-${kind}${on ? ' is-on' : ''}" style="--rsp:${colorOfKey(item.lane)}" ${attrs}${filterAttrs} title="${esc(title)}" aria-label="${esc(title)}">
        <span class="tp-rsp-face">${portrait(item.hero, 'is-face')}</span>
        <span class="tp-rsp-copy"><b>${esc(item.hero)}</b><small>${note}</small>${share === null ? '' : `<span class="tp-rsp-share"><i style="width:${Math.max(3, share).toFixed(1)}%"></i></span>`}</span>
        ${has(item.wins) ? `<em>${bpPct(bpRate(item.wins, item.games))}</em>` : ''}
      </button>`;
    };
    const banNodes = rows.map((item) => node(
      item, 'ban', item.hero === row.hero, '',
      `${fmt(item.games)} 局 · ban 后胜 ${bpPct(bpRate(item.wins, item.games))}`
    )).join('');
    const firstNodes = firsts.slice(0, 8).map((item) => node(
      item, 'pick', item.hero === pick?.hero, '',
      `${fmt(item.games)} 局 · 占 ${Math.round(item.games / row.games * 100)}%`
    )).join('') || '<p class="tp-lack">没有一抢记录。</p>';
    const secondNodes = seconds.slice(0, 8).map((item) => node(
      item, 'second', false, gamesAttr(item.list, `我们 ban ${row.hero} · 一抢 ${pick?.hero} · 二抢 ${item.hero}`),
      `${fmt(item.games)} 局 · 占 ${Math.round(item.games / (pick?.games || 1) * 100)}%`
    )).join('') || '<p class="tp-lack">这一组一抢后面没有二抢记录。</p>';
    return card('条件响应 · ban 之后他们怎么拿', `${fmt(games.length)} 局 · ${fmt(row.games)} 局 ban 过 ${row.hero}`, `
      <div class="tp-rsp-path">
        <span class="tp-rsp-path-item">${portrait(row.hero, 'is-path-face')}<small>ban</small><b>${esc(row.hero)}</b></span><i aria-hidden="true">→</i>
        <span class="tp-rsp-path-item">${pick ? portrait(pick.hero, 'is-path-face') : ''}<small>一抢</small><b>${pick ? esc(pick.hero) : '—'}</b></span><i aria-hidden="true">→</i>
        <span class="tp-rsp-path-item">${seconds[0] ? portrait(seconds[0].hero, 'is-path-face') : ''}<small>二抢</small><b>${seconds[0] ? esc(seconds[0].hero) : '—'}</b></span>
      </div>
      <div class="tp-rsp">
        <div class="tp-rsp-col is-ban"><div class="tp-rsp-head"><span>我们 ban</span><small>候选 ${fmt(rows.length)} 个</small></div><div class="tp-rsp-list is-ban">${banNodes}</div></div>
        <span class="tp-rsp-arrow" aria-hidden="true">→</span>
        <div class="tp-rsp-col"><div class="tp-rsp-head"><span>他们一抢</span><small>${fmt(row.games)} 局</small></div><div class="tp-rsp-list">${firstNodes}</div></div>
        <span class="tp-rsp-arrow" aria-hidden="true">→</span>
        <div class="tp-rsp-col"><div class="tp-rsp-head"><span>他们二抢</span><small>${pick ? `一抢 ${esc(pick.hero)}` : '先选一抢'}</small></div><div class="tp-rsp-list">${secondNodes}</div></div>
      </div>
      <div class="tp-rsp-foot">
        <span>我们 ban <b>${esc(row.hero)}</b> 的 ${fmt(row.games)} 局里，他们胜率 <b>${bpPct(bpRate(row.wins, row.games))}</b>；一抢 <b>${pick ? esc(pick.hero) : '—'}</b> 后二抢最常拿 <b>${seconds[0] ? esc(seconds[0].hero) : '—'}</b>。${row.games < 3 ? '样本少，只作观察。' : ''}</span>
        ${pathGames.length ? `<button type="button" class="tp-rsp-games"${gamesAttr(pathGames, `我们 ban ${row.hero}${pick ? ` · 一抢 ${pick.hero}` : ''}`)}>看这 ${fmt(pathGames.length)} 局 →</button>` : ''}
      </div>
      <p class="tp-read">点左边换一个 ban 候选，点中间换一个一抢英雄；每层都是这批筛选局里的历史频率，不是预测。样本少的节点只作观察。</p>`, 'is-bp-card');
  }

  /* ── 4. 招牌 ban 后改拿（按选手） ─────────────────────────────── */
  function bpSignatureData(games) {
    const byPlayer = new Map();
    for (const game of games) {
      const players = game.sides?.enemy?.players || [];
      if (!players.length) continue;
      const bans = new Set(bpBans(game));
      for (const player of players) {
        if (!player?.name || !player?.hero) continue;
        const key = player.id || player.name;
        const row = byPlayer.get(key) || {id: key, name: player.name, lane: player.lane || '', picks: new Map(), records: []};
        row.lane ||= player.lane || '';
        row.picks.set(player.hero, (row.picks.get(player.hero) || 0) + 1);
        row.records.push({game, hero: player.hero, lane: player.lane || '', bans});
        byPlayer.set(key, row);
      }
    }
    const laneOrder = (lane) => {
      const index = LANES.indexOf(lane);
      return index < 0 ? 99 : index;
    };
    return [...byPlayer.values()].map((row) => {
      const signatures = [...row.picks.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 2)
        .filter(([, count]) => count >= 2)
        .map(([hero]) => {
          const played = row.records.filter((record) => record.hero === hero);
          const banned = row.records.filter((record) => record.bans.has(hero));
          const replacements = new Map();
          for (const record of banned) {
            if (record.hero === hero) continue;
            const item = replacements.get(record.hero) || {hero: record.hero, lane: record.lane, games: 0, wins: 0, list: []};
            item.games++; item.wins += bpWin(record.game) ? 1 : 0; item.list.push(record.game);
            replacements.set(record.hero, item);
          }
          return {
            hero,
            lane: row.lane,
            games: played.length,
            winRate: bpRate(played.filter((record) => bpWin(record.game)).length, played.length),
            banGames: banned.length,
            bannedWinRate: bpRate(banned.filter((record) => bpWin(record.game)).length, banned.length),
            replacements: [...replacements.values()].sort((a, b) => b.games - a.games),
            gamesList: bpUnique([...played.map((record) => record.game), ...banned.map((record) => record.game)]),
          };
        });
      return {...row, signatures, laneOrder: laneOrder(row.lane)};
    }).filter((row) => row.signatures.length)
      .sort((a, b) => a.laneOrder - b.laneOrder || a.name.localeCompare(b.name));
  }

  function bpSignatureCard(games) {
    const rows = bpSignatureData(games);
    if (!rows.length) return card('招牌 ban 后改拿', '选手名单不稳定', lack('这批局没有同一位选手 2 局同英雄的记录；等有固定首发后再看招牌与替补。'), 'is-bp-card');
    const totalBans = rows.reduce((sum, row) => sum + row.signatures.reduce((n, sig) => n + sig.banGames, 0), 0);
    const heroButton = (item, meta, label) => `<button type="button" class="tp-sig-hero"${gamesAttr(item.list || item.gamesList, label)}>
      ${portrait(item.hero, 'is-face')}<span><b>${esc(item.hero)}</b><small>${meta}</small></span>
    </button>`;
    const body = rows.map((row) => row.signatures.map((sig, index) => {
      const playerCell = index === 0 ? `<th scope="rowgroup" rowspan="${row.signatures.length}"><b>${esc(row.name)}</b><small>${esc(row.lane || '—')}</small></th>` : '';
      const repl = sig.banGames
        ? (sig.replacements.length
          ? `<div class="tp-sig-repl">${sig.replacements.slice(0, 3).map((item) => heroButton(item, `${fmt(item.games)} 局 · ${bpPct(bpRate(item.wins, item.games))}`, `${row.name} · ${sig.hero} 被 ban 后改拿 ${item.hero}`)).join('')}</div>`
          : '<span class="tp-quiet">没改拿记录</span>')
        : '<span class="tp-quiet">没被我们 ban 过</span>';
      return `<tr style="--sig-lane:${colorOfKey(row.lane)}">
        ${playerCell}
        <td>${heroButton({hero: sig.hero, list: sig.gamesList}, `${fmt(sig.games)} 局 · ${bpPct(sig.winRate)}`, `${row.name} 的招牌 ${sig.hero}`)}</td>
        <td><b>${sig.banGames ? fmt(sig.banGames) : '—'}</b>${sig.banGames ? `<small class="tp-sig-rate">改拿后 ${bpPct(sig.bannedWinRate)}</small>` : ''}</td>
        <td>${repl}</td>
      </tr>`;
    }).join('')).join('');
    return card('招牌 ban 后改拿', `${fmt(rows.length)} 人 · 招牌被 ban ${fmt(totalBans)} 局`, `
      <div class="tp-sig-wrap"><table class="tp-sig-table">
        <thead><tr><th scope="col">选手</th><th scope="col">招牌</th><th scope="col">被我们 ban</th><th scope="col">改拿</th></tr></thead>
        <tbody>${body}</tbody>
      </table></div>
      <p class="tp-read">招牌＝同一选手在这批局里拿得最多的 1–2 个英雄（至少 2 局）。只统计有出场、且招牌被我们 ban 的局；改拿后的胜率以被 ban 的局为分母。点英雄看具体对局，样本少时只作观察。</p>`, 'is-bp-card');
  }

  /* ── 战队标签 ─────────────────────────────────────────────────── */
  /* 自动状态标签保持原样；教练标签排在最前，一眼能看到「巅峰 / 俱乐部」。 */
  function computedTags(view) {
    const { meta, matches, oppRate } = view;
    const thin = matches < 3;
    const tags = [];
    if (thin) tags.push(['样本不足', 'sample']);
    if (matches >= 3 && (oppRate ?? -1) >= 60) tags.push(['交手下风', 'weak']);
    if (matches >= 3 && (oppRate ?? 101) <= 40) tags.push(['交手占优', 'strong']);
    if (meta.named) tags.push(['已命名', 'neutral']);
    if (meta.coach) tags.push([`教练 ${meta.coach}`, 'neutral']);
    if (!tags.length) tags.push(['待观察', 'neutral']);
    return tags;
  }
  function headTagChips(view) {
    const user = loadTeamTags(view.t.id).map((label) =>
      `<span class="tp-tag is-usertag is-${tagKind(label)}" title="教练按巅峰分/俱乐部标注">${esc(label)}</span>`);
    const auto = computedTags(view).map(([label, cls]) => `<span class="tp-tag is-${cls}">${esc(label)}</span>`);
    return [...user, ...auto].slice(0, 6).join('');
  }
  function tagChipsHtml(tags) {
    if (!tags.length) return '<span class="tp-quiet">还没打标签</span>';
    return tags.map((label) => `<span class="tp-utag-chip is-${tagKind(label)}">${esc(label)}<button type="button" class="tp-utag-remove" data-tp-tag-remove="${esc(label)}" aria-label="移除标签 ${esc(label)}" title="移除 ${esc(label)}">×</button></span>`).join('');
  }
  function tagsCard(view) {
    const tags = loadTeamTags(view.t.id);
    const inputId = `tp-utag-input-${esc(view.t.id)}`;
    const helpId = `tp-utag-help-${esc(view.t.id)}`;
    const presets = sharedPresets().map((preset) => {
      const on = tags.includes(preset.label);
      return `<button type="button" class="tp-utag-preset${on ? ' is-on' : ''}" data-tp-tag-preset="${esc(preset.label)}" aria-pressed="${on}" title="${esc(preset.title)}"><i aria-hidden="true">${on ? '✓' : '+'}</i>${esc(preset.label)}</button>`;
    }).join('');
    return card('战队标签', '赛训组共享 · 按巅峰分 / 俱乐部 / 赛事级别', `<div class="tp-utag" data-tp-tags-card>
      <div class="tp-utag-main">
        <fieldset class="tp-utag-set">
          <legend>常用标签 · 点一下打上，再点一下取消</legend>
          <div class="tp-utag-presets" role="group" aria-label="按巅峰分选常用标签">${presets}</div>
        </fieldset>
        <form class="tp-utag-form" data-tp-tag-form>
          <label for="${inputId}">自定义标签 · 填俱乐部名等</label>
          <div class="tp-utag-field">
            <input id="${inputId}" type="text" data-tp-tag-input maxlength="20" placeholder="例如：AG 俱乐部" autocomplete="off" autocorrect="off" autocapitalize="none" spellcheck="false" enterkeyhint="done" aria-describedby="${helpId}">
            <button type="submit">添加标签</button>
          </div>
          <p id="${helpId}" class="tp-utag-help">预置标签点选即可，也可填俱乐部等自定义标签；保存在赛训数据库，全组共享。</p>
        </form>
      </div>
      <div class="tp-utag-current" role="group" aria-label="已打标签" data-tp-tag-current>${tagChipsHtml(tags)}</div>
      <p class="tp-utag-status" role="status" aria-live="polite" data-tp-tag-status>${tags.length ? `已打 ${fmt(tags.length)} 个标签 · 赛训组共享` : ''}</p>
    </div>`);
  }

  /* ── 头部 ─────────────────────────────────────────────────────── */
  function headBlock(view) {
    const { meta, oppName, matches, avgDuration, oppRate } = view;
    const thin = matches < 3;
    const facts = [
      ['交手', `${fmt(matches)} 局`],
      ['本队战绩', `${fmt(meta.wins)} 胜 ${fmt(meta.losses)} 负`],
      ['对手胜率', pct(oppRate)],
      ['场均时长', time(avgDuration)],
      ['最近交手', text(meta.lastSeen)],
    ];
    if (thin) facts[2][0] = '对手胜率（单局）';
    const stamp = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
    return `<header class="tp-head">
      <div class="tp-head-bar">
        <a class="tp-back" href="#teams">← 战队分析</a>
        <div class="tp-head-actions">
          <span class="tp-updated">本页读取 ${esc(stamp)}</span>
          <button type="button" class="tp-btn" data-team-rename="${esc(view.t.id)}" data-team-label="${esc(view.t.displayName)}">${meta.named ? '改名' : '命名'}</button>
          <button type="button" class="tp-btn" data-tp-copy data-tp-summary="__TP_SUMMARY__">复制摘要</button>
          <button type="button" class="tp-btn tp-refresh" data-tp-refresh><span class="tp-refresh-ico" aria-hidden="true">↻</span>刷新</button>
        </div>
      </div>
      <div class="tp-id">
        <span class="tp-crest" aria-hidden="true">${esc((oppName || '?').slice(0, 1))}</span>
        <div class="tp-id-copy">
          <span class="tp-eyebrow">对手档案 / TEAM DOSSIER</span>
          <h1>${text(oppName)}</h1>
        </div>
        <div class="tp-tags" data-tp-head-tags>${headTagChips(view)}</div>
      </div>
      <dl class="tp-facts">${facts.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`).join('')}</dl>
    </header>`;
  }

  const section = (id, no, title, sub, chip, body) => `<section class="tp-sec${state.section === id ? ' is-active' : ''}" id="${id}" data-no="${no}" role="tabpanel" aria-labelledby="tp-tab-${id}"${state.section === id ? '' : ' hidden'}>
    ${title ? `<header class="tp-sec-head"><div class="tp-sec-title"><h2>${title}</h2>${chip ? `<span class="tp-sec-chip">${esc(chip)}</span>` : ''}<button type="button" class="tp-sec-copy" data-tp-section-copy="${id}" title="复制本节的文字与表格">复制本节</button></div><p class="tp-sec-sub">${sub}</p></header>` : ''}
    <div class="tp-sec-body" id="${id}-body">${body}</div>
  </section>`;

  const NAV = [['tp-overview', '01 样本'], ['tp-bp', '02 BP'], ['tp-comp', '03 阵容与风格'], ['tp-pool', '04 英雄池']];

  function tabsBar() {
    const live = model ? activeGames(model).length : 0;
    const total = model ? model.deepGames.length : 0;
    return `<nav class="tp-tabs" aria-label="页面分节">
      <div class="tp-tablist" role="tablist" aria-label="五段分析">${NAV.map(([id, label]) => `<button type="button" class="tp-tab${id === state.section ? ' is-active' : ''}" id="tp-tab-${id}" role="tab" data-tp-tab="${id}" aria-selected="${id === state.section}" aria-controls="${id}">${esc(label)}</button>`).join('')}</div>
      <div class="tp-tabtools">
        <label class="tp-miniselect"><span>时间</span><select data-tp-select="days">${WINDOWS.map(([value, label]) => `<option value="${value}"${state.days === value ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
        ${state.days === 'custom' ? `<span class="tp-customdates"><input type="date" data-tp-date="from" value="${esc(state.from ? `2026-${state.from}` : '')}" aria-label="起始日期"><em>→</em><input type="date" data-tp-date="to" value="${esc(state.to ? `2026-${state.to}` : '')}" aria-label="结束日期"></span>` : ''}
        <label class="tp-miniselect"><span>赛制</span><select data-tp-select="bo">${BO_OPTIONS.map(([value]) => `<option value="${value}"${state.bo === value ? ' selected' : ''}>${esc(value === 'all' ? '全部赛制' : value === 'none' ? '未登记' : `BO${value}`)}</option>`).join('')}</select></label>
        <span class="tp-tabscope">${fmt(live)} / ${fmt(total)} 局</span>
      </div>
    </nav>`;
  }

  function tabFoot() {
    const index = Math.max(0, NAV.findIndex(([id]) => id === state.section));
    const prev = NAV[index - 1], next = NAV[index + 1];
    return `<div class="tp-tabfoot">${prev ? `<button type="button" data-tp-tab="${prev[0]}">← ${esc(prev[1])}</button>` : '<span></span>'}<span class="tp-tabfoot-pos">${index + 1} / ${NAV.length}</span>${next ? `<button type="button" data-tp-tab="${next[0]}">${esc(next[1])} →</button>` : '<span></span>'}</div>`;
  }

  function bodyHtml(view, games) {
    resetGameRegistry();
    const known = draftGames(games);
    const section01 = section('tp-overview', '01', '样本与整体', '三个能跨队比的数，带环比；口径取当前筛选内的对局。', `${fmt(games.length)} 局`, `${tagsCard(view)}${noteCard()}${baseBoard(games)}`);
    const section02 = section('tp-bp', '02', 'BP', '先看英雄优先级、输赢指纹、ban 后响应与选手招牌；下面是分路常选 / 常 ban 明细。<span class="hb-fresh" data-freshness></span>', `${fmt(known.length)} 局有手序`, `<div class="tp-grid is-2 tp-bp-pair">${bpPriorityCard(games)}${bpFingerprintCard(games)}</div>` + bpResponseCard(games) + bpSignatureCard(games) + `<details class="tp-bp-details"><summary>分路常选 / 常 ban 明细 · 5 路 × 2</summary>${enemyTopCard(games)}</details>` + bpDistribution(games) + poolCard(games));
    const section03 = section('tp-comp', '03', '阵容与风格', '边野怎么搭、几核、五路类型。', `${fmt(games.length)} 局`, styleCard(games) + `<div class="tp-grid is-2">${coreCard(games)}${laneTypeCard(games)}</div>`);
    /* 04 英雄池：只留双方英雄池交叉；常选 / 常 ban 与 ban 后替补移到 BP。
       顶部筛条与标签页已经写明节名和局数，本节不再重复标题、副标题与复制按钮。 */
    const section04 = section('tp-pool', '04', '', '', '', poolCrossCard(games));
    return section01 + section02 + section03 + section04 + tabFoot();
  }

  function drawerShell() {
    return `<div class="tp-drawer" data-tp-drawer hidden>
      <div class="tp-drawer-backdrop" data-tp-drawer-close></div>
      <aside class="tp-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="tp-drawer-title">
        <header class="tp-drawer-head">
          <div><small>对局明细</small><h3 id="tp-drawer-title" data-tp-drawer-title>对局</h3><p data-tp-drawer-meta></p></div>
          <button type="button" class="tp-drawer-close" data-tp-drawer-close aria-label="关闭对局明细">×</button>
        </header>
        <div class="tp-drawer-body" data-tp-drawer-body></div>
      </aside>
    </div>`;
  }

  function drawerGameRow(game, lanes) {
    const picks = lanes.length ? lanes.map((lane) => pickOfLane(game, lane)).filter(Boolean) : enemyPicks(game);
    const decided = game.opponentWin === true || game.opponentWin === false;
    const result = !decided ? '结果未知' : game.opponentWin ? '对手胜' : '本队胜';
    const resultCls = !decided ? 'is-unknown' : game.opponentWin ? 'is-loss' : 'is-win';
    const heroes = picks.slice(0, 5).map((pick) => `<span><i class="${laneCls(pick.lane)}"></i><small>${esc(LANE_SHORT[pick.lane] || pick.lane)}</small>${esc(pick.name)}</span>`).join('');
    const inner = `<span class="tp-drawer-date">${esc(game.start || game.day || '—')}</span>
      <span class="tp-drawer-res ${resultCls}">${result}</span>
      <span class="tp-drawer-meta">${time(game.duration)} · ${game.bo ? `BO${game.bo}` : 'BO 未登记'}</span>
      <span class="tp-drawer-picks">${heroes || '<span class="tp-quiet">阵容未知</span>'}</span>
      <span class="tp-drawer-go">${game.matchKey ? '复盘 →' : ''}</span>`;
    return game.matchKey
      ? `<a class="tp-drawer-game" href="${esc(route('match', game.matchKey))}">${inner}</a>`
      : `<div class="tp-drawer-game">${inner}</div>`;
  }

  function openGames(id, root) {
    const entry = gameRegistry.get(id);
    const page = root?.closest('.tp-page') || root;
    const drawer = page?.querySelector('[data-tp-drawer]');
    if (!entry || !drawer) return;
    const games = [...entry.games].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    drawer.querySelector('[data-tp-drawer-title]').textContent = entry.title;
    drawer.querySelector('[data-tp-drawer-meta]').textContent = `${fmt(games.length)} 局 · 点任意一局进入复盘`;
    drawer.querySelector('[data-tp-drawer-body]').innerHTML = games.map((game) => drawerGameRow(game, entry.lanes || [])).join('');
    drawerTrigger = document.activeElement;
    drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add('is-open'));
    document.body.classList.add('tp-drawer-open');
    drawer.querySelector('[data-tp-drawer-close]')?.focus();
  }

  function closeGames(root) {
    const page = root?.closest('.tp-page') || root;
    const drawer = page?.querySelector('[data-tp-drawer]');
    if (!drawer || drawer.hidden) return;
    drawer.classList.remove('is-open');
    drawer.hidden = true;
    document.body.classList.remove('tp-drawer-open');
    if (drawerTrigger && typeof drawerTrigger.focus === 'function' && document.contains(drawerTrigger)) drawerTrigger.focus();
    drawerTrigger = null;
  }

  if (typeof document !== 'undefined' && !window.__tpDrawerWatch) {
    window.__tpDrawerWatch = true;
    window.addEventListener('hashchange', () => {
      document.body.classList.remove('tp-drawer-open');
      const page = document.querySelector('.tp-page');
      if (page) closeGames(page);
    });
  }

  function render(value, key, compareData, bpData, deepData, behaviorData) {
    document.body.classList.remove('tp-drawer-open');
    const view = buildView(value, key, compareData, bpData, deepData, behaviorData);
    if (!view) {
      return `<div class="page feature-page tp-page"><header class="tp-head"><div class="tp-head-bar"><a class="tp-back" href="#teams">← 战队分析</a></div><div class="tp-id"><div class="tp-id-copy"><span class="tp-eyebrow">对手档案</span><h1>未找到这支战队</h1><p>这支战队可能已被合并。</p></div></div></header><div class="empty">这支战队可能已被合并。</div></div>`;
    }
    model = view;
    const games = activeGames(view);
    const html = `<div class="page feature-page tp-page td-page">
      ${headBlock(view)}
      ${tabsBar()}
      <div data-tp-analysis>${bodyHtml(view, games)}</div>
      ${drawerShell()}
    </div>`;
    /* 标签 / 笔记在库里共享：DOM 落地后再异步取回，避免首屏阻塞。 */
    setTimeout(() => {
      const root = document.querySelector('.tp-page');
      if (root) loadSharedAsync(root);
      window.__loadFreshness?.();
    }, 0);
    return html.replace('__TP_SUMMARY__', esc(summary(view, games)));
  }

  function summary(view, games) {
    const decided = games.filter((game) => game.opponentWin === true || game.opponentWin === false);
    const losses = decided.filter((game) => game.opponentWin === true).length;
    const rows = handRows(games, 'pick');
    const firstLane = modeOf(rows.filter((row) => row.slot === 1 && isKnownLane(row.lane)).map((row) => row.lane));
    const lineups = games.map((game) => game.sides?.enemy?.lineup).filter((lineup) => lineup && lineup.total);
    return [
      `对手：${view.oppName}`,
      `样本：${fmt(games.length)} 局（对手 ${fmt(losses)} 胜 ${fmt(decided.length - losses)} 负，场均 ${time(mean(games.map((game) => game.duration).filter((v) => has(v) && v > 0)))}）`,
      `切片：${state.days === 'all' ? '全部时间' : state.days === 'custom' ? `${state.from || '起'}~${state.to || '止'}` : `近 ${state.days} 天`} · ${state.bo === 'all' ? '全部赛制' : state.bo === 'none' ? '未登记赛制' : `BO${state.bo}`}`,
      `结构：${lineups.length ? `最常见 ${modeOf(lineups.map((lineup) => lineup.cores)).values.join('/')} 核` : '类型标注不足'}`,
      `第一手：${firstLane ? `${firstLane.values.join('/')}（${fmt(firstLane.count)} 局）` : '手序不足'}`,
      '口径：营地终局面板；定序数据只给中位 / 众数',
    ].join('\n');
  }

  function repaint(root) {
    if (!root || !model) return;
    const games = activeGames(model);
    const holder = root.querySelector('[data-tp-analysis]');
    if (holder) holder.innerHTML = bodyHtml(model, games);
    const nav = root.querySelector('.tp-tabs');
    if (nav) nav.outerHTML = tabsBar();
    const copy = root.querySelector('[data-tp-copy]');
    if (copy) copy.dataset.tpSummary = summary(model, games);
    const sync = (selector, active) => root.querySelectorAll(selector).forEach((el) => el.setAttribute('aria-pressed', String(el.dataset.tpValue === active)));
    sync('[data-tp-filter="days"]', state.days);
    sync('[data-tp-filter="bo"]', state.bo);
    sync('[data-tp-filter="mode"]', state.mode);
    sync('[data-tp-filter="hand"]', state.hand);
    sync('[data-tp-filter="lane"]', state.lane);
    root.querySelectorAll('[data-tp-filter="bpHero"], [data-tp-filter="poolHero"]').forEach((el) => el.classList.toggle('is-on', el.dataset.tpValue === (el.dataset.tpFilter === 'bpHero' ? state.bpHero : state.poolHero)));
  }

  function setSection(id, root) {
    if (!NAV.some(([sid]) => sid === id)) return;
    state.section = id;
    const page = root?.closest('.tp-page') || root;
    if (!page) return;
    closeGames(page);
    page.querySelectorAll('.tp-sec').forEach((sec) => {
      const on = sec.id === id;
      sec.hidden = !on;
      sec.classList.toggle('is-active', on);
    });
    page.querySelectorAll('.tp-tablist [data-tp-tab]').forEach((button) => {
      const on = button.dataset.tpTab === id;
      button.classList.toggle('is-active', on);
      button.setAttribute('aria-selected', String(on));
    });
    const foot = page.querySelector('.tp-tabfoot');
    if (foot) foot.outerHTML = tabFoot();
    const nav = page.querySelector('.tp-tabs');
    const anchor = page.querySelector('[data-tp-analysis]');
    if (nav && anchor) {
      const stickyTop = parseFloat(getComputedStyle(nav).top) || 0;
      const top = anchor.getBoundingClientRect().top + window.scrollY - stickyTop - nav.getBoundingClientRect().height - 10;
      window.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
    }
  }

  function setFilter(name, value, root) {
    closeGames(root);
    if (name === 'reset') {
      state.mode = 'pick';
      state.hand = 'all';
      state.lane = 'all';
      state.bpHero = 'all';
      state.responseBan = '';
      state.responsePick = '';
    } else if (name === 'days') {
      state.days = value;
      if (value === 'custom' && !state.from) {
        const days = model?.days || [];
        if (days.length) { state.from = days[0]; state.to = days[days.length - 1]; }
      }
    } else if (name === 'bo') {
      state.bo = value;
    } else if (['hand', 'lane', 'mode', 'bpHero', 'poolHero', 'bpHeroLane', 'poolHeroLane', 'responseBan', 'responsePick'].includes(name)) {
      state[name] = value;
      if (name === 'mode') state.bpHero = 'all';
      if (name === 'lane' && value !== 'all') state.bpHeroLane = value;
      if (name === 'responseBan') state.responsePick = '';
    } else if (name === 'from' || name === 'to') {
      state[name] = value;
    }
    repaint(root);
  }

  return {render, setFilter, setSection, repaint, openGames, closeGames, state, get model() { return model; }};
}
