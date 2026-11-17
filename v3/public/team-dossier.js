/* 战队详情 · team dossier v9（2026-11-17 教练反馈修订）
   ============================================================
   v9 只改「看得懂、点得动」的地方：
   1) 01–05 真分节：点哪个只看哪个，时间 / 赛制常驻在分节条上；
   2) 筛选收进一个下拉；英雄列表默认只摊一条路，头像改成大圆卡，
      「全部 110」是清除英雄筛选，不再是一排小胶囊；
   3) 分路 × 类型、边野搭配、位置组合、五路类型全部换成带文字的表，
      小分路（游走）的三类辅助也能逐个对上；
   4) 名次折线可点线聚焦，前段 / 近段与 BO 切片写清口径；
   5) 英雄池的大卡与「具体拿了谁」放大，ban 后替补按次数加权。
   历史图表函数保留在下方，当前页面只调用 v9 的新图元。
   ============================================================ */
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const LANE_SHORT = {'对抗路': '对抗', '打野': '打野', '中路': '中路', '发育路': '发育', '游走': '游走'};
const ARCH = {
  '对抗路': ['战边', '坦边'],
  '打野': ['刺野', '战野', '坦野'],
  '中路': ['工具人', '法核'],
  '发育路': ['游射', '呆射'],
  '游走': ['开团辅', '保护辅', '功能辅'],
};
/* 类型在全页统一排序：先按分路，再按路内顺序。 */
const TYPE_ORDER = LANES.flatMap((lane) => ARCH[lane]);
const TYPE_LANE = Object.fromEntries(LANES.flatMap((lane) => ARCH[lane].map((type) => [type, lane])));
const TYPE_DESC = {
  '战边': '战士边路，带线切后', '坦边': '坦克边路，抗伤开团',
  '刺野': '刺客打野，切后排', '战野': '战士打野，半前排', '坦野': '坦克打野，开团抗伤',
  '工具人': '功能中单，先手控制', '法核': '法师核心，主要输出',
  '游射': '位移射手，自保输出', '呆射': '站桩射手，持续输出',
  '开团辅': '先手开团', '保护辅': '保排反手', '功能辅': '功能增益',
};
const EDGE_COMBO = {
  '战刺': ['战边', '刺野'], '战战': ['战边', '战野'], '战坦': ['战边', '坦野'],
  '坦刺': ['坦边', '刺野'], '坦战': ['坦边', '战野'], '坦坦': ['坦边', '坦野'],
};
const UNLABELED = ['待分类', '未标注', '未知', ''];
const PAIRS = [
  ['边野', '对抗路', '打野'], ['中野', '中路', '打野'], ['射辅', '发育路', '游走'],
  ['中辅', '中路', '游走'], ['野辅', '打野', '游走'], ['边中', '对抗路', '中路'],
  ['边射', '对抗路', '发育路'], ['边辅', '对抗路', '游走'], ['野射', '打野', '发育路'],
  ['中射', '中路', '发育路'],
];
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
  '工具人': 'var(--c-type-工具人)', '法核': 'var(--c-type-法核)',
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

  const card = (title, meta, body, cls = '') => `<article class="tp-card${cls ? ' ' + cls : ''}"><header class="tp-card-head"><h3>${title}</h3>${meta ? `<span>${meta}</span>` : ''}</header>${body}</article>`;
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

  /* 3c. 分路 × 类型矩阵：每一格都写人次和本路占比，小分路也不会丢标签。 */
  function typeMatrix(rows, opts = {}) {
    const typedRows = rows.filter((row) => isKnownType(row.archetype));
    const lanes = LANES.filter((lane) => typedRows.some((row) => row.lane === lane));
    if (!lanes.length) return '';
    const types = TYPE_ORDER.filter((type) => typedRows.some((row) => row.archetype === type));
    if (!types.length) return '';
    const countOf = (lane, type) => typedRows.filter((row) => row.lane === lane && row.archetype === type).length;
    const laneTotal = (lane) => typedRows.filter((row) => row.lane === lane).length;
    const typeTotal = (type) => typedRows.filter((row) => row.archetype === type).length;
    let max = 1;
    for (const lane of lanes) for (const type of types) max = Math.max(max, countOf(lane, type));
    const head = `<thead><tr><th class="tp-mx-corner"><span>分路</span><small>人次</small></th>${types.map((type, ti) => `<th data-col="${ti}"><i style="background:${colorOfKey(type)}"></i>${esc(type)}</th>`).join('')}<th class="tp-mx-sum">合计</th></tr></thead>`;
    const body = lanes.map((lane) => {
      const total = laneTotal(lane);
      const cells = types.map((type, ti) => {
        const cellRows = typedRows.filter((row) => row.lane === lane && row.archetype === type);
        const count = cellRows.length;
        if (!count) return `<td class="tp-mx-cell is-zero" data-col="${ti}">·</td>`;
        const alpha = 12 + Math.round((count / max) * 30);
        const games = cellRows.map((row) => row.game);
        const gid = gamesAttr(games, `${lane} · ${type}`, [lane]);
        return `<td class="tp-mx-cell is-drill" data-col="${ti}" style="background:color-mix(in srgb, ${colorOfKey(lane)} ${alpha}%, var(--paper))"${gid} title="${esc(`${lane} · ${type} · ${fmt(count)} 人次（${pct((count / total) * 100)}）；点开看这 ${fmt(games.length)} 局`)}"><b>${fmt(count)}</b><small>${pct((count / total) * 100)}</small></td>`;
      }).join('');
      return `<tr><th class="tp-mx-lane"><i style="background:${colorOfKey(lane)}"></i><span>${esc(lane)}</span><b>${fmt(total)}</b></th>${cells}<td class="tp-mx-sum">${fmt(total)}</td></tr>`;
    }).join('');
    const foot = `<tfoot><tr><th class="tp-mx-lane">合计</th>${types.map((type) => `<td class="tp-mx-sum">${fmt(typeTotal(type))}</td>`).join('')}<td class="tp-mx-sum is-strong">${fmt(typedRows.length)}</td></tr></tfoot>`;
    return `<p class="tp-scrollhint">← 左右滑动看全部类型 →</p><div class="tp-mx-wrap"><table class="tp-mx" aria-label="${esc(opts.aria || '分路与类型矩阵')}">${head}<tbody>${body}</tbody>${foot}</table></div>`;
  }

  /* 3d. 选人顺位矩阵：行是分路，列是第几手，把「选人」写进表头。 */
  function priorityTable(rows, mode) {
    const lanes = LANES.filter((lane) => rows.some((row) => row.lane === lane));
    const countOf = (lane, slot) => rows.filter((row) => row.lane === lane && row.slot === slot).length;
    const laneSlots = (lane) => rows.filter((row) => row.lane === lane).map((row) => row.slot);
    let max = 1;
    for (const lane of lanes) for (const slot of [1, 2, 3, 4, 5]) max = Math.max(max, countOf(lane, slot));
    const head = `<thead><tr><th class="tp-pr-corner" rowspan="2">分路</th><th class="tp-pr-group" colspan="5">${mode === 'ban' ? 'Ban' : '选人'} · 第几手</th><th class="tp-pr-side" rowspan="2">中位</th><th class="tp-pr-side" rowspan="2">众数</th><th class="tp-pr-side" rowspan="2">合计</th></tr><tr>${[1, 2, 3, 4, 5].map((slot) => `<th class="tp-pr-slot" data-col="${slot}">第${slot}手</th>`).join('')}</tr></thead>`;
    const body = lanes.map((lane) => {
      const slots = laneSlots(lane);
      const band = medianBand(slots);
      const mode2 = modeOf(slots);
      const cells = [1, 2, 3, 4, 5].map((slot) => {
        const cellRows = rows.filter((row) => row.lane === lane && row.slot === slot);
        const count = cellRows.length;
        if (!count) return `<td class="tp-pr-cell is-zero" data-col="${slot}">·</td>`;
        const alpha = 8 + Math.round((count / max) * 34);
        const gid = gamesAttr(cellRows.map((row) => row.game), `${lane} · 第${slot}手`, [lane]);
        return `<td class="tp-pr-cell is-drill" data-col="${slot}" style="background:color-mix(in srgb, ${colorOfKey(lane)} ${alpha}%, var(--paper))"${gid} title="${esc(`${lane} · 第${slot}手 · ${fmt(count)} 人次；点开看这 ${fmt(count)} 局`)}"><b>${fmt(count)}</b></td>`;
      }).join('');
      return `<tr><th class="tp-pr-lane"><i style="background:${colorOfKey(lane)}"></i>${esc(lane)}</th>${cells}<td class="tp-pr-side">${band ? (band[0] === band[1] ? band[0] : `${band[0]}–${band[1]}`) : '—'}</td><td class="tp-pr-side">${mode2 ? mode2.values.join('/') : '—'}</td><td class="tp-pr-side is-strong">${fmt(slots.length)}</td></tr>`;
    }).join('');
    return `<p class="tp-scrollhint">← 左右滑动看第 4、5 手 →</p><div class="tp-pr-wrap"><table class="tp-pr" aria-label="选人顺位矩阵">${head}<tbody>${body}</tbody></table></div>`;
  }

  /* 3e. 英雄池大卡：头像 56px，名字和次数在下面，不再挤成一条胶囊。 */
  function poolHeroCard(hero, count, type) {
    return `<a class="tp-poolhero" href="${route('hero', hero)}" title="${esc(`${hero}${type ? ` · ${type}` : ''} · ${fmt(count)} 次`)}">
      <span class="tp-poolhero-face">${String(portrait(hero, 'is-face')).replace(' loading="lazy"', '')}<em>${fmt(count)}</em></span>
      <b>${esc(hero)}</b>${type ? `<small>${esc(type)}</small>` : ''}
    </a>`;
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
      const roseGames = opts.gamesOf ? opts.gamesOf(item) : [];
      const gid = roseGames.length ? gamesAttr(roseGames, `${opts.caption || '分布'} · ${item.key}`, opts.lanesOf ? opts.lanesOf(item) : []) : '';
      return `<path d="M${x0.toFixed(1)} ${y0.toFixed(1)} L${x3.toFixed(1)} ${y3.toFixed(1)} A${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L${x1.toFixed(1)} ${y1.toFixed(1)} A${inner} ${inner} 0 ${large} 0 ${x0.toFixed(1)} ${y0.toFixed(1)} Z" fill="${opts.colorOf ? opts.colorOf(item) : 'var(--accent)'}" class="tp-rose-bar${gid ? ' is-drill' : ''}"${gid}><title>${esc(`${item.key} · ${fmt(item.count)} 局${gid ? '；点开看这 ' + roseGames.length + ' 局' : ''}`)}</title></path>
        <text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="tp-rose-label">${esc(item.key)}</text>
        <text x="${lx.toFixed(1)}" y="${(ly + 11).toFixed(1)}" text-anchor="middle" class="tp-rose-count">${fmt(item.count)}</text>`;
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
      const status = note.closest('.tp-card')?.querySelector('[data-tp-note-status]');
      clearTimeout(note.__tpNoteTimer);
      note.__tpNoteTimer = setTimeout(() => {
        try {
          localStorage.setItem(note.dataset.tpNote, note.value);
          if (status) {
            const stamp = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
            status.textContent = `已保存 ${stamp}`;
          }
        } catch {
          if (status) status.textContent = '本机无法保存';
        }
      }, 250);
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

  function filterChips() {
    const view = model;
    const total = view ? view.deepGames.length : 0;
    const liveGames = activeGames(view);
    const live = liveGames.length;
    const scope = state.days === 'all' ? '全部时间' : state.days === 'custom' ? `${state.from || '起'}~${state.to || '止'}` : `近 ${state.days} 天`;
    const bo = state.bo === 'all' ? '全部赛制' : state.bo === 'none' ? '未登记赛制' : `BO${state.bo}`;
    return `<div class="tp-filter tp-filter-compact" role="group" aria-label="样本范围">
      <div class="tp-filter-head">
        <span class="tp-filter-title">样本范围</span>
        <b>${esc(scope)}</b><i>·</i><b>${esc(bo)}</b>
        <span class="tp-filter-note">改时间 / 赛制用下方分节条；这里只显示当前口径</span>
      </div>
      <div class="tp-filter-stat" data-tp-mount="filterstat">${filterStat(live, total)}</div>
    </div>`;
  }

  function scopeStrip(games) {
    if (!games.length) return '';
    const days = [...new Set(games.map((game) => game.day).filter(Boolean))].sort();
    const range = days.length ? `${days[0]}~${days[days.length - 1]}` : '—';
    const draft = draftGames(games).length;
    const boKnown = games.filter((game) => game.bo).length;
    const unregistered = games.length - boKnown;
    return `<div class="tp-scope-strip" aria-label="样本口径">
      <span class="tp-scope-strong">${fmt(games.length)} 局</span>
      <span>${esc(range)}</span>
      <span>手序 ${fmt(draft)}</span>
      <span>BO 登记 ${fmt(boKnown)}</span>
      ${unregistered ? `<span class="is-warn">未登记 ${fmt(unregistered)}</span>` : ''}
      <span class="tp-scope-note">BP 手序只统计有手序的局；类型 / 英雄池按全部对局，边野只算双方都有类型的局</span>
    </div>`;
  }

  function noteCard() {
    const storageKey = `kpl-team-note:${model?.key || 'team'}`;
    let note = '';
    try { note = localStorage.getItem(storageKey) || ''; } catch { note = ''; }
    return card('教练笔记', '本机保存 · 只在这台电脑可见', `<textarea class="tp-note" data-tp-note="${esc(storageKey)}" maxlength="2000" placeholder="这队喜欢什么、怕什么、上次交手怎么输的……">${esc(note)}</textarea><p class="tp-note-foot" data-tp-note-status>${note ? '已保存' : '输入后自动保存'}</p>`, 'is-wide');
  }

  function filterStat(live, total) {
    if (!model) return '';
    const boCounts = (model.coverage && model.coverage.boCounts) || {};
    const boOf = (bo) => Number(boCounts[bo] ?? boCounts[String(bo)] ?? 0);
    const boText = [3, 5, 7].filter((bo) => boOf(bo)).map((bo) => `BO${bo} ${fmt(boOf(bo))}`).join(' · ');
    const decided = activeGames(model).filter((game) => game.opponentWin === true || game.opponentWin === false);
    const wins = decided.filter((game) => game.opponentWin === true).length;
    const pctLive = total ? Math.round((live / total) * 100) : 0;
    return `<div class="tp-filter-copy"><b>当前 ${fmt(live)} / ${fmt(total)} 局</b><span>对手 ${fmt(wins)} 胜 ${fmt(decided.length - wins)} 负${decided.length ? ` · ${pct(wins / decided.length * 100)}` : ''}${boText ? ` · ${boText}` : ''}</span></div>
      <div class="tp-filter-cover"><span class="tp-filter-ring">${ringArc(pctLive, 40, 4)}<b>${pctLive}%</b></span><small>样本覆盖</small></div>`;
  }

  function ringArc(rate, size = 58, stroke = 5) {
    const r = (size - stroke) / 2;
    const c = 2 * Math.PI * r;
    const value = (Math.max(0, Math.min(100, rate)) / 100) * c;
    return `<svg class="tp-ringarc" viewBox="0 0 ${size} ${size}" role="img" aria-label="${fmt(rate, 0)}%">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--tp-hair)" stroke-width="${stroke}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${value.toFixed(1)} ${(c - value).toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    </svg>`;
  }

  /* ── 01 整体对照：数字 + 环比 ─────────────────────────────────── */
  const BASE_METRICS = [
    ['场均控龙', 'dragons', 1, 0.05, '中立资源'],
    ['场均推塔', 'towers', 1, 0.05, '推进兑现'],
    ['场均经济', 'gold', 0, 500, '资源总量'],
  ];

  function metricValue(games, side, field) {
    const values = games.map((game) => game.sides?.[side]?.stats?.[field]).filter(has);
    return values.length ? mean(values) : null;
  }

  function baseBoard(games) {
    const prev = previousGames(model);
    const blocks = BASE_METRICS.map(([label, field, digits, threshold, note]) => {
      const opp = metricValue(games, 'enemy', field);
      const own = metricValue(games, 'own', field);
      const oppDelta = has(opp) && has(metricValue(prev, 'enemy', field)) ? opp - metricValue(prev, 'enemy', field) : null;
      const ownDelta = has(own) && has(metricValue(prev, 'own', field)) ? own - metricValue(prev, 'own', field) : null;
      const show = (value) => (field === 'gold' ? `${fmt(value / 1000, 1)}k` : fmt(value, digits));
      const deltaText = (value) => {
        if (!has(value)) return '无环比';
        if (Math.abs(value) < threshold) return '持平';
        const body = field === 'gold' ? `${fmt(Math.abs(value) / 1000, 1)}k` : fmt(Math.abs(value), digits);
        return `${value > 0 ? '↑' : '↓'} ${body}`;
      };
      const deltaTone = (value) => (!has(value) || Math.abs(value) < threshold ? 'is-even' : value > 0 ? 'is-up' : 'is-down');
      const gap = has(opp) && has(own) ? opp - own : null;
      return `<div class="tp-metric">
        <div class="tp-metric-head"><b>${esc(label)}</b><small>${esc(note)}</small></div>
        <div class="tp-metric-body">
          <span class="is-opp"><small>对手</small><b>${show(opp)}</b><em class="${deltaTone(oppDelta)}">${deltaText(oppDelta)}</em></span>
          <span class="is-own"><small>本队</small><b>${show(own)}</b><em class="${deltaTone(ownDelta)}">${deltaText(ownDelta)}</em></span>
        </div>
        <div class="tp-metric-foot"><em>${!has(gap) ? '—' : Math.abs(gap) < threshold ? '两队持平' : `${gap > 0 ? '对手高' : '本队高'} ${field === 'gold' ? `${fmt(Math.abs(gap) / 1000, 1)}k` : fmt(Math.abs(gap), digits)}`}</em></div>
      </div>`;
    }).join('');
    const compareNote = prev.length ? `环比＝上一个同长度窗口（${fmt(prev.length)} 局）` : '选全部 / 自定义时没有环比窗口';
    return card('整体对照', `${fmt(games.length)} 局 · ${compareNote}`, `<div class="tp-metrics">${blocks}</div>
      <p class="tp-read">只摆这三项：控龙是队伍级资源决策、推塔是推进兑现、经济是资源总量，跨队能比。↑↓ 是和上一个同长度窗口比的环比。</p>`, 'is-wide');
  }

  function formCard(games) {
    const form = games.slice(0, 14).reverse();
    const squares = form.map((game) => `<i class="tp-sq ${game.opponentWin === true ? 'is-loss' : game.opponentWin === false ? 'is-win' : 'is-unknown'}" title="${esc(`${game.start || ''} · ${game.opponentWin === true ? '对手胜' : game.opponentWin === false ? '本队胜' : '结果未知'}${game.bo ? ` · BO${game.bo}` : ''}`)}"></i>`).join('');
    const decided = games.filter((game) => game.opponentWin === true || game.opponentWin === false);
    const losses = decided.filter((game) => game.opponentWin === true).length;
    const durations = games.map((game) => game.duration).filter((v) => has(v) && v > 0);
    return card('近期交手', `${fmt(games.length)} 局`, `<div class="tp-form-strip">${squares || '<span class="tp-quiet">还没有对局记录</span>'}</div>
      <div class="tp-form-legend"><span><i class="is-win"></i>本队胜</span><span><i class="is-loss"></i>对手胜</span><small>左旧 → 右新</small></div>
      <div class="tp-form-stats">
        <div><small>对手战绩</small><b>${fmt(losses)} 胜 ${fmt(decided.length - losses)} 负</b></div>
        <div><small>对手胜率</small><b>${decided.length ? pct((losses / decided.length) * 100) : '—'}</b></div>
        <div><small>场均时长</small><b>${time(mean(durations))}</b></div>
      </div>`);
  }

  /* ── 02 BP 手序 ───────────────────────────────────────────────── */
  const draftGames = (games) => games.filter((game) => game.draft?.known && game.draft.ordered);

  function handRows(games, mode) {
    const rows = [];
    for (const game of draftGames(games)) {
      const list = game.draft.ordered?.enemy?.[mode] || [];
      list.forEach((entry, index) => rows.push({slot: index + 1, ...entry, game}));
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
      <span class="tp-bpbar-note">英雄列表默认只摊一条路；头像角标是人次，同一英雄只出现一张卡</span>
    </div>`;
  }

  function bpDistribution(games) {
    const mode = state.mode;
    let rows = handRows(games, mode);
    if (!rows.length) return card(mode === 'ban' ? 'Ban 分布' : '选人分布', '没有可用手序', `${bpControls()}${lack('这批筛选条件里没有带手序的 BP。')}`);
    if (state.hand !== 'all') rows = rows.filter((row) => row.slot === Number(state.hand));
    const heroBar = heroPicker(rows, {key: 'bpHero', laneKey: 'bpHeroLane', lane: state.bpHeroLane, label: '英雄'});
    const laneRows = state.lane === 'all' ? rows : rows.filter((row) => row.lane === state.lane);
    const focusRows = state.bpHero === 'all' ? laneRows : rows.filter((row) => row.hero === state.bpHero);
    const scope = `${state.hand === 'all' ? '全部手序' : `第 ${state.hand} 手`}${state.lane === 'all' ? '' : ` · ${state.lane}`}`;
    if (!focusRows.length) return card(mode === 'ban' ? 'Ban 分布' : '选人分布', `${scope} · 0 人次`, `${bpControls()}${heroBar}${lack('当前手序、分路或英雄没有记录，换一个条件再看看。')}`);
    /* 选到单个英雄：看它落在第几手，而不是一张只有一个扇区的图。 */
    if (state.bpHero !== 'all') {
      const slots = focusRows.map((row) => row.slot);
      const items = [1, 2, 3, 4, 5].map((slot) => ({key: `第 ${slot} 手`, slot, count: slots.filter((value) => value === slot).length, games: focusRows.filter((row) => row.slot === slot).map((row) => row.game)})).filter((item) => item.count);
      const lane = LANES.map((name) => ({name, count: focusRows.filter((row) => row.lane === name).length})).sort((a, b) => b.count - a.count)[0];
      const type = distOf(focusRows.filter((row) => isKnownType(row.archetype)).map((row) => row.archetype)).sort((a, b) => b[1] - a[1])[0];
      const heroTable = items.map((item) => [item.key, `${fmt(item.count)} 人次`, pct((item.count / focusRows.length) * 100)]);
      return card(`${mode === 'ban' ? 'Ban' : '选人'}分布 · ${state.bpHero}`, `${fmt(focusRows.length)} 人次 · 落在第几手`, `${bpControls()}${heroBar}
        <div class="tp-focusbar">
          <span class="tp-focusbar-face">${String(portrait(state.bpHero, 'is-face')).replace(' loading="lazy"', '')}</span>
          <span class="tp-focusbar-copy"><small>正在单看</small><b>${esc(state.bpHero)}</b></span>
          <button type="button" class="tp-focusbar-exit" data-tp-filter="bpHero" data-tp-value="all">退出单看 · 回到全部</button>
        </div>
        <div class="tp-sun-wrap">
          <div class="tp-sun-figure">${rose(items, {size: 260, caption: '人次', colorOf: (item) => HAND_COLOR[Math.max(0, [1, 2, 3, 4, 5].indexOf(Number(String(item.key).replace(/[^0-9]/g, '')))) % 5], gamesOf: (item) => item.games})}${dataTable(['手序', '人次', '占比'], heroTable, '点扇区可以看这只英雄在那几手对应的局。')}</div>
          <div class="tp-sun-side">
            <div class="tp-sun-block"><small>这几次的落点</small>
              <div class="tp-typelist">
                <span><i style="background:${lane ? colorOfKey(lane.name) : 'var(--c-muted)'}"></i><b>${lane ? esc(lane.name) : '—'}</b><em>${lane ? fmt(lane.count) : '0'}</em><small>人次</small></span>
                <span><i style="background:${type ? colorOfKey(type[0]) : 'var(--c-muted)'}"></i><b>${type ? esc(type[0]) : '未标注'}</b><em>${type ? fmt(type[1]) : '0'}</em><small>人次</small></span>
                <span><i style="background:var(--c-hand-3)"></i><b>中位手序</b><em>${medianBand(slots) ? (medianBand(slots)[0] === medianBand(slots)[1] ? medianBand(slots)[0] : `${medianBand(slots)[0]}–${medianBand(slots)[1]}`) : '—'}</em><small>手</small></span>
                <span><i style="background:var(--c-hand-1)"></i><b>众数手序</b><em>${modeOf(slots) ? modeOf(slots).values.join('/') : '—'}</em><small>手</small></span>
              </div>
            </div>
          </div>
        </div><p class="tp-read">这里的「第几手」是这套阵容里第几个选人：第 1 手＝最先亮出来的那一手。</p>`);
    }
    const total = focusRows.length;
    const types = distOf(focusRows.filter((row) => isKnownType(row.archetype)).map((row) => row.archetype)).sort((a, b) => b[1] - a[1]);
    const untyped = focusRows.filter((row) => !isKnownType(row.archetype)).length;
    const top = types.slice(0, 3).map(([type, count]) => `<span><i style="background:${colorOfKey(type)}"></i>${esc(type)}<b>${fmt(count)}</b><small>人次</small></span>`).join('');
    return card(`${mode === 'ban' ? 'Ban' : '选人'}分布 · 分路 × 类型`, `${scope} · ${fmt(total)} 人次`, `${bpControls()}${heroBar}
      <div class="tp-mx-head">
        <div class="tp-mx-top"><small>出现最多</small>${top || '<span class="tp-quiet">未标注</span>'}</div>
      </div>
      ${typeMatrix(focusRows, {aria: `${mode === 'ban' ? 'Ban' : '选人'}分路与类型矩阵`})}
      <p class="tp-read">行是分路，列是英雄类型；格子里是人次，浅色小字是这一路里的占比。点任意一格可以看对应的局。${untyped ? `还有 ${fmt(untyped)} 人次类型未标注，不进表。` : ''}</p>`);
  }

  function handStream(games) {
    const mode = state.mode;
    const rows = handRows(games, mode);
    if (!rows.length) return '';
    const slots = [...new Set(rows.map((row) => row.slot))].sort((a, b) => a - b).slice(0, 5);
    if (slots.length < 2) return '';
    const series = slots.map((slot) => {
      const group = rows.filter((row) => row.slot === slot);
      return {label: `第${slot}${mode === 'ban' ? ' ban' : '选'}`, slot, rows: group, total: group.length, segments: LANES.map((lane) => ({key: lane, count: group.filter((row) => row.lane === lane).length})).filter((seg) => seg.count)};
    });
    const keys = LANES.filter((lane) => series.some((item) => item.segments.some((seg) => seg.key === lane)));
    const per = new Set(series.map((item) => item.total));
    const tableRows = series.map((item) => [`${item.label}`, ...keys.map((key) => `${fmt(item.segments.find((seg) => seg.key === key)?.count || 0)}（${pct((item.segments.find((seg) => seg.key === key)?.count || 0) / item.total * 100)}）`), fmt(item.total)]);
    return card(`${mode === 'ban' ? 'Ban' : '选人'}手序 · 分路构成`, `${fmt(rows.length)} 人次 · ${per.size === 1 ? `每手 ${fmt(series[0].total)} 人次` : '按手序拆开'}`, `${shareColumns(series, keys, {width: 600, height: 250, barW: 70, shortOf: (key) => LANE_SHORT[key] || key, aria: `${mode === 'ban' ? 'Ban' : '选人'}手序分路构成`, gamesOf: (item, key) => item.rows.filter((row) => row.lane === key).map((row) => row.game), lanesOf: (key) => [key]})}
      <div class="tp-legend">${keys.map((key) => `<span><i style="background:${colorOfKey(key)}"></i>${esc(key)}</span>`).join('')}</div>
      ${dataTable(['手序', ...keys, '合计'], tableRows, '点色块可以看对应对局；这里的百分比是同一手内的分路占比。')}
      <p class="tp-read">每一手总人次相同，所以柱高固定为 100%，只看分路占比：哪一路的色块在第几手最厚，就是他们最优先处理的位置。点色块可以看对应的局。</p>`);
  }

  function priorityCard(games) {
    const mode = state.mode;
    const rows = handRows(games, mode);
    if (!rows.length) return '';
    return card(`${mode === 'ban' ? 'Ban' : '选人'}顺位`, `${fmt(rows.length)} 人次 · 行＝分路，列＝第几手`, `${priorityTable(rows, mode)}
      <p class="tp-read">先横着看表头：列是「第几手」，第 1 手就是这套阵容里第一个${mode === 'ban' ? ' ban' : '选人'}。格子里的数字是该分路在第几手出现了多少次；右侧中位／众数是这一路的整体顺位。点格子可以看对应的局。</p>`);
  }

  function sliceGroups(games) {
    const chrono = [...games].filter((game) => game.day).sort((a, b) => String(a.start || '').localeCompare(String(b.start || '')));
    const cut = Math.ceil(chrono.length / 2);
    const withRange = (group) => {
      const days = group.games.map((game) => game.day).filter(Boolean).sort();
      return {...group, range: days.length ? `${days[0]}~${days[days.length - 1]}` : ''};
    };
    return [
      {key: 'early', label: '前段', note: `${fmt(chrono.slice(0, cut).length)} 局`, games: chrono.slice(0, cut)},
      {key: 'late', label: '近段', note: `${fmt(chrono.slice(cut).length)} 局`, games: chrono.slice(cut)},
      ...[3, 5, 7].map((bo) => {
        const list = games.filter((game) => Number(game.bo) === bo);
        return {key: `bo${bo}`, label: `BO${bo}`, note: `${fmt(list.length)} 局`, games: list};
      }),
    ].map(withRange).filter((group) => group.games.length >= 1);
  }

  function driftCard(games) {
    const groups = sliceGroups(games);
    if (groups.length < 2) return card('变化 · 时间与赛制', '切片不足', lack('切片后样本不足两组。'));
    const laneSeries = groups.map((group) => {
      const rows = handRows(group.games, 'pick').filter((row) => row.slot <= 2);
      return {label: group.label, note: group.note, range: group.range, games: group.games, segments: LANES.map((lane) => ({key: lane, count: rows.filter((row) => row.lane === lane).length})).filter((seg) => seg.count)};
    });
    const coreSeries = groups.map((group) => {
      const lineups = group.games.map((game) => game.sides?.enemy?.lineup).filter((lineup) => lineup && lineup.total);
      return {label: group.label, note: `${fmt(lineups.length)} 局`, range: group.range, games: group.games, total: lineups.length, segments: [1, 2, 3, 4].map((core) => ({key: `${core} 核`, count: lineups.filter((lineup) => lineup.cores === core).length})).filter((seg) => seg.count)};
    });
    const laneKeys = LANES.filter((lane) => laneSeries.some((item) => item.segments.some((seg) => seg.key === lane)));
    const coreKeys = ['1 核', '2 核', '3 核', '4 核'];
    const laneTable = groups.map((group, index) => {
      const item = laneSeries[index];
      const totals = new Map(laneKeys.map((key) => [key, item.segments.find((seg) => seg.key === key)?.count || 0]));
      const sorted = [...totals.entries()].sort((a, b) => b[1] - a[1]);
      const rankOf = new Map(sorted.map(([key], rank) => [key, rank + 1]));
      return [`${group.label}<small>${group.range || ''}</small>`, ...laneKeys.map((key) => `${fmt(totals.get(key) || 0)} 人次<small>第${rankOf.get(key) || '—'}名</small>`)];
    });
    const coreTable = coreSeries.map((item) => [`${item.label}<small>${item.range || ''} · ${fmt(item.total)} 局</small>`, ...coreKeys.map((key) => {
      const count = item.segments.find((seg) => seg.key === key)?.count || 0;
      return `${fmt(count)}<small>${item.total ? pct((count / item.total) * 100) : '—'}</small>`;
    })]);
    return card('变化 · 时间与赛制', `${fmt(groups.length)} 个切片 · 名次与构成`, `<div class="tp-driftgrid">
      <div class="tp-driftcell"><header><b>前两手选人 · 分路名次</b><small>第 1 名＝这个切片里被选得最多；点线上的点看对局，点线只看这一路</small></header>${bumpChart(laneSeries, laneKeys, {height: 230, aria: '分路名次变化', gamesOf: (item, key) => item.games.filter((game) => handRows([game], 'pick').some((row) => row.slot <= 2 && row.lane === key))})}${dataTable(['切片', ...laneKeys], laneTable, '表里是每个切片的选人次和名次；点图上的点可以看对应局。')}</div>
      <div class="tp-driftcell"><header><b>核数构成</b><small>柱高固定 100%，只看体系变胖还是变瘦</small></header>${shareColumns(coreSeries, coreKeys, {width: 520, height: 230, barW: 54, shortOf: (key) => key.replace(' ', ''), colorOf: (key) => CORE_COLOR[coreKeys.indexOf(key) % 4], aria: '核数构成', gamesOf: (item, key) => item.games.filter((game) => (game.sides?.enemy?.lineup?.cores || 0) === Number(key.replace(/\D/g, '')) && game.sides?.enemy?.lineup?.total)})}<div class="tp-legend">${coreKeys.map((key, index) => `<span><i style="background:${CORE_COLOR[index]}"></i>${esc(key)}</span>`).join('')}</div>${dataTable(['切片', ...coreKeys], coreTable, '每个切片下方标了日期范围和局数；点柱子可以看对应局。')}</div>
    </div><p class="tp-read"><b>前段 / 近段</b>：把这批局按开始时间排序后对半切，前一半叫前段，后一半叫近段。<b>BO3 / BO5 / BO7</b> 是按赛制另切的一刀，会和前后段重叠，不是互斥分组。左图名次 1＝该切片里这条分路被选得最多；右图每根柱子的总高都是 100%，柱下标的是该切片的局数。</p>`);
  }

  /* ── 03 阵容与风格 ────────────────────────────────────────────── */
  const enemyPicks = (game) => game.sides?.enemy?.picks || [];
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
    const allEdges = ['战边', '坦边'], allJungles = ['刺野', '战野', '坦野'];
    const cellOf = (edge, jungle) => cells.get(`${edge}|${jungle}`) || {games: 0, wins: 0};
    const edgeTypes = allEdges.filter((edge) => allJungles.some((jungle) => cellOf(edge, jungle).games));
    const jungleTypes = allJungles.filter((jungle) => allEdges.some((edge) => cellOf(edge, jungle).games));
    const hiddenTypes = [...allEdges, ...allJungles].filter((type) => !edgeTypes.includes(type) && !jungleTypes.includes(type));
    let max = 1;
    for (const edge of edgeTypes) for (const jungle of jungleTypes) max = Math.max(max, cellOf(edge, jungle).games);
    const colTotal = (jungle) => edgeTypes.reduce((sum, edge) => sum + cellOf(edge, jungle).games, 0);
    const rowTotal = (edge) => jungleTypes.reduce((sum, jungle) => sum + cellOf(edge, jungle).games, 0);
    const head = `<thead><tr><th class="tp-evm-corner"><span>对抗路</span><small>打野</small></th>${jungleTypes.map((jungle, ji) => `<th data-col="${ji}"><i style="background:${colorOfKey(jungle)}"></i>${esc(jungle)}</th>`).join('')}<th class="tp-evm-sum">合计</th></tr></thead>`;
    const body = edgeTypes.map((edge) => `<tr><th class="tp-evm-row"><i style="background:${colorOfKey(edge)}"></i><span>${esc(edge)}</span><small>${fmt(rowTotal(edge))} 局</small></th>${jungleTypes.map((jungle, ji) => {
      const cell = cellOf(edge, jungle);
      if (!cell.games) return `<td class="tp-evm-cell is-zero" data-col="${ji}">—</td>`;
      const alpha = 10 + Math.round((cell.games / max) * 30);
      const cellGames = rows.filter((game) => {
        const e = pickOfLane(game, '对抗路'), j = pickOfLane(game, '打野');
        return e?.archetype === edge && j?.archetype === jungle;
      });
      const gid = gamesAttr(cellGames, `${edge} + ${jungle}`, ['对抗路', '打野']);
      return `<td class="tp-evm-cell is-drill${cell.games === max ? ' is-top' : ''}" data-col="${ji}" style="background:color-mix(in srgb, ${colorOfKey(edge)} ${alpha}%, var(--paper))"${gid} title="${esc(`${edge} + ${jungle} · ${fmt(cell.games)} 局 · ${pct((cell.games / total) * 100)}；点开看这 ${fmt(cellGames.length)} 局`)}"><b>${fmt(cell.games)} 局</b><small>${pct((cell.games / total) * 100)}</small><em>${cell.games >= 3 ? `对手胜 ${pct((cell.wins / cell.games) * 100)}` : '样本不足'}</em></td>`;
    }).join('')}<td class="tp-evm-sum">${fmt(rowTotal(edge))}</td></tr>`).join('');
    const foot = `<tfoot><tr><th class="tp-evm-row">合计</th>${jungleTypes.map((jungle) => `<td class="tp-evm-sum">${fmt(colTotal(jungle))}</td>`).join('')}<td class="tp-evm-sum is-strong">${fmt(total)}</td></tr></tfoot>`;
    const top = [...cells.entries()].sort((a, b) => b[1].games - a[1].games)[0];
    const guide = `<div class="tp-evm-guide">
      <div class="tp-evm-top"><small>最常见</small><b>${esc(top[0].replace('|', ' + '))}</b><span>${fmt(top[1].games)} 局 · ${pct((top[1].games / total) * 100)}</span></div>
      <div class="tp-evm-types">${[...edgeTypes, ...jungleTypes].map((type) => `<span><i style="background:${colorOfKey(type)}"></i><b>${esc(type)}</b><small>${esc(TYPE_DESC[type] || '')}</small></span>`).join('')}</div>
      ${hiddenTypes.length ? `<p class="tp-evm-hidden">本样本没有出现：${hiddenTypes.map((type) => esc(type)).join('、')}，已收起。</p>` : ''}
      <p class="tp-read">横着读一行：以「战边」为例，配刺野几局、配战野几局、配坦野几局，一眼能看出这套阵容让谁顶前排、谁负责切后。格子里第一行是局数，第二行是占比，第三行是这种搭配下对手的胜率（少于 3 局写样本不足）。只统计对抗路和打野都有类型标注的局。点格子可以看对应的局。</p>
    </div>`;
    return card('边野搭配 · 前排与切入', `${fmt(total)} 局 · 边路 × 打野`, `<p class="tp-scrollhint">← 左右滑动看全部打野类型 →</p><div class="tp-evm"><div class="tp-evm-wrap"><table class="tp-evm-table" aria-label="边野搭配矩阵">${head}<tbody>${body}</tbody>${foot}</table></div>${guide}</div>`, 'is-wide');
  }

  function coreCard(games) {
    const rows = games.map((game) => game.sides?.enemy?.lineup).filter((lineup) => lineup && lineup.total);
    if (!rows.length) return card('核数', '没有阵容标签', lack('这批局没有可用的类型标注。'));
    const cores = rows.map((lineup) => lineup.cores);
    const items = [1, 2, 3, 4, 5].map((core) => ({key: `${core} 核`, core, count: cores.filter((value) => value === core).length, games: games.filter((game) => game.sides?.enemy?.lineup?.cores === core)})).filter((item) => item.count);
    const four = cores.filter((value) => value >= 4).length;
    const tableRows = items.map((item) => [item.key, `${fmt(item.count)} 局`, pct((item.count / rows.length) * 100)]);
    return card('核数', `${fmt(rows.length)} 局 · 一局一个核数`, `<div class="tp-rose-wrap">${rose(items, {size: 240, caption: '局', colorOf: (item) => CORE_COLOR[items.indexOf(item) % 4], gamesOf: (item) => item.games})}${dataTable(['核数', '局数', '占比'], tableRows, '点扇区可以看对应局。')}</div>
      <p class="tp-read">${fmt(four)} 局是四核（${pct((four / rows.length) * 100)}）。核＝战边 / 刺野 / 战野 / 法核 / 游射 / 呆射；坦边、坦野、工具人、辅助不分核。点扇区可以看对应的局。</p>`);
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
      if (!item.total) return `<div class="tp-lanerow is-empty"><div class="tp-lanerow-head"><i style="background:${colorOfKey(item.lane)}"></i><b>${esc(item.lane)}</b><small>类型未标注</small></div><p class="tp-lack">这一路还没有类型标注。</p></div>`;
      const segments = item.segments.map((seg) => {
        const share = (seg.count / item.total) * 100;
        const segGames = rows.filter((game) => pickOfLane(game, item.lane)?.archetype === seg.key);
        const gid = gamesAttr(segGames, `${item.lane} · ${seg.key}`, [item.lane]);
        return `<span class="tp-lanerow-seg${gid ? ' is-drill' : ''}" data-col="${TYPE_ORDER.indexOf(seg.key)}" style="width:${share.toFixed(2)}%;background:${colorOfKey(seg.key)}"${gid} title="${esc(`${item.lane} · ${seg.key} · ${fmt(seg.count)} 局（${pct(share)}）；点开看这 ${fmt(segGames.length)} 局`)}">${share >= 11 ? `<b>${esc(seg.key)}</b>` : ''}</span>`;
      }).join('');
      const list = item.segments.map((seg) => `<span><i style="background:${colorOfKey(seg.key)}"></i><b>${esc(seg.key)}</b><em>${fmt(seg.count)} 局</em><small>${pct((seg.count / item.total) * 100)}</small></span>`).join('');
      return `<div class="tp-lanerow"><div class="tp-lanerow-head"><i style="background:${colorOfKey(item.lane)}"></i><b>${esc(item.lane)}</b><small>${fmt(item.total)} 局有类型标注</small></div><div class="tp-lanerow-bar">${segments}</div><div class="tp-lanerow-list">${list}</div></div>`;
    }).join('');
    return card('五路类型', `${fmt(rows.length)} 局 · 每路一条构成`, `<div class="tp-lanetypes">${body}</div>
      <p class="tp-read">每一行是一路；横条按类型切分，条上写得下就写类型名，写不下的在下面清单里全部列出局数和占比。这样游走的三类辅助也能逐个对上。点色块可以看对应的局。本卡统计全部对局；BP 的分路 × 类型只统计有手序的局，所以同一路的人次可能略少。</p>`);
  }

  function pairCard(games) {
    const rows = games.filter((game) => enemyPicks(game).length);
    if (!rows.length) return card('位置组合', '没有选人明细', lack('这批局没有可用的选人明细。'));
    const pairKeys = PAIRS.map(([label, laneA, laneB]) => {
      const counter = new Map();
      for (const game of rows) {
        const a = pickOfLane(game, laneA), b = pickOfLane(game, laneB);
        if (!a || !b || !isKnownType(a.archetype) || !isKnownType(b.archetype)) continue;
        const key = `${a.archetype} × ${b.archetype}`;
        counter.set(key, (counter.get(key) || 0) + 1);
      }
      const ranked = [...counter.entries()].sort((x, y) => y[1] - x[1]);
      const total = ranked.reduce((sum, [, value]) => sum + value, 0);
      const top = ranked[0];
      return {label, laneA, laneB, top, ranked, total, stable: total ? top[1] / total : 0, kinds: ranked.length};
    }).sort((a, b) => (b.top?.[1] || 0) - (a.top?.[1] || 0) || b.total - a.total);
    const maxTop = Math.max(1, ...pairKeys.map((item) => item.top?.[1] || 0));
    const body = pairKeys.map((item) => {
      const combos = item.ranked.slice(0, 3).map(([key, count]) => `${key} ${count}局`).join('；');
      const comboParts = item.top ? item.top[0].split(' × ') : [];
      const comboGames = item.top ? rows.filter((game) => {
        const a = pickOfLane(game, item.laneA), b = pickOfLane(game, item.laneB);
        return a?.archetype === comboParts[0] && b?.archetype === comboParts[1];
      }) : [];
      const gid = comboGames.length ? gamesAttr(comboGames, `${item.label} · ${item.top ? item.top[0] : ''}`, [item.laneA, item.laneB]) : '';
      return `<div class="tp-pairrow${gid ? ' is-drill' : ''}"${gid} title="${esc(`${item.laneA} × ${item.laneB}：${combos || '没有记录'}${gid ? '；点开看这 ' + comboGames.length + ' 局' : ''}`)}">
        <span class="tp-pairlabel"><i style="background:${colorOfKey(item.laneA)}"></i><b>${esc(item.label)}</b><small>${esc(item.laneA)} × ${esc(item.laneB)}</small></span>
        <span class="tp-paircombo">${item.top ? `${esc(item.top[0])}<em>${fmt(item.top[1])} 局</em>` : '—'}</span>
        <span class="tp-pairmeter"><i style="width:${(((item.top?.[1] || 0) / maxTop) * 100).toFixed(1)}%;background:${colorOfKey(item.laneA)}"></i></span>
        <b class="tp-pairnum">${fmt(item.top?.[1] || 0)} / ${fmt(item.total)}</b>
        <small class="tp-pairshare">${item.total ? `${pct(item.stable * 100)} 稳定` : '—'}</small>
      </div>`;
    }).join('');
    return card('位置组合 · 五个位置两两', `${fmt(rows.length)} 局 · ${fmt(pairKeys.length)} 对位置`, `<div class="tp-pairlist">
      <div class="tp-pairrow is-head"><span>位置组合</span><span>最常见的类型搭配</span><span></span><span>出现 / 该对</span><span>稳定度</span></div>
      ${body}
    </div><p class="tp-read">因为每局五个位置都有人，单看「这一对出现了几局」永远等于样本局数；所以这里按「最常见的类型搭配出现了几局」排序。<b>稳定度</b>＝最常见搭配占这一对全部组合的比例，越高说明他们越固定用同一套类型组合，越低说明搭配越分散。点一行可以看这一对最常见搭配对应的局。之前打野 × 中路这一格漏了，这次十对都在。</p>`, 'is-wide');
  }

  /* ── 04 英雄池与替代 ──────────────────────────────────────────── */
  function poolCard(games) {
    const rows = games.filter((game) => enemyPicks(game).length);
    if (!rows.length) return card('英雄池与替代', '没有选人明细', lack('这批局没有可用的选人明细。'));
    const known = draftGames(games);
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
    const lanes = LANES.map((lane) => {
      const picks = new Map();
      for (const game of rows) {
        const pick = pickOfLane(game, lane);
        if (!pick) continue;
        picks.set(pick.name, (picks.get(pick.name) || 0) + 1);
      }
      const bans = new Map();
      for (const game of known) for (const ban of (game.draft.ordered.own.ban || [])) if (ban?.hero && ban.lane === lane) bans.set(ban.hero, (bans.get(ban.hero) || 0) + 1);
      return {lane, list: [...picks.entries()].sort((a, b) => b[1] - a[1]), bans: [...bans.entries()].sort((a, b) => b[1] - a[1])};
    });
    const laneCards = lanes.map((row) => `<div class="tp-poollane"><header><i style="background:${colorOfKey(row.lane)}"></i><b>${esc(row.lane)}</b><small>${fmt(rows.length)} 局</small></header>
      <div class="tp-poollane-col"><small>最常选 · 前 4</small><div class="tp-poolgrid">${row.list.slice(0, 4).map(([hero, games]) => poolHeroCard(hero, games)).join('') || '<span class="tp-quiet">—</span>'}</div></div>
      <div class="tp-poollane-col"><small>被我们 ban</small><div class="tp-poolgrid">${row.bans.slice(0, 3).map(([hero, games]) => poolHeroCard(hero, games)).join('') || '<span class="tp-quiet">—</span>'}</div></div>
    </div>`).join('');

    const heroBar = heroPicker(raw.map((link) => ({hero: link.from, lane: link.lane, archetype: link.fromType})), {key: 'poolHero', laneKey: 'poolHeroLane', lane: state.poolHeroLane, label: '被我们 ban 的英雄'});

    if (!links.length) {
      return card('英雄池 · 选与 ban', `${fmt(rows.length)} 局 · 五个位置`, `<div class="tp-poollanes">${laneCards}</div>
        <div class="tp-flowsection"><header><b>被 ban 之后拿谁</b></header>${lack('这批筛选里没有「我们 ban 了、他们同路改拿」的记录。')}</div>`);
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
      return card(`英雄池 · ${selected} 被 ban 之后`, `${fmt(total)} 次 · ${esc(lane || '同路')}`, `${heroBar}
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
        </div><p class="tp-read">左是我们 ban 的 ${esc(selected)}，右是他们同一路改拿的英雄；右侧给出替补的类型分布和具体英雄卡，直接能看出「ban 掉之后他们换的是同一类还是换了思路」。被 ban 之后拿谁只统计有手序的局；上面的选人与被 ban 覆盖全部对局。</p>`);
    }

    return card('英雄池 · 选与 ban', `${fmt(rows.length)} 局 · 五个位置`, `<div class="tp-poollanes">${laneCards}</div>
      <div class="tp-flowsection"><header><b>被 ban 之后拿谁</b><small>先选一条路，再点英雄头像只看那一只被 ban 之后的替补；角标是人次</small></header>${heroBar}${flowChart(links, {leftLimit: 6, rightLimit: 8})}</div>
      <p class="tp-read">选人与被我们 ban 覆盖全部对局；被 ban 之后拿谁只统计有手序的局，所以两张卡的样本会差几局。</p>`);
  }

  /* ── 05 结果 ──────────────────────────────────────────────────── */
  function resultCard(games) {
    const rows = games.filter((game) => game.opponentWin === true || game.opponentWin === false);
    if (rows.length < 4) return card('赢与输的结构差别', '样本不足', lack('可判定胜负的局少于 4 局。'));
    const win = rows.filter((game) => game.opponentWin === false);
    const loss = rows.filter((game) => game.opponentWin === true);
    const coreUp = new Map(), coreDown = new Map();
    for (const game of win) { const c = game.sides?.enemy?.lineup?.cores; if (has(c)) coreUp.set(c, (coreUp.get(c) || 0) + 1); }
    for (const game of loss) { const c = game.sides?.enemy?.lineup?.cores; if (has(c)) coreDown.set(c, (coreDown.get(c) || 0) + 1); }
    const styleUp = new Map(), styleDown = new Map();
    for (const [list, bucket] of [[win, styleUp], [loss, styleDown]]) {
      for (const game of list) {
        const edge = pickOfLane(game, '对抗路'), jungle = pickOfLane(game, '打野');
        if (!edge || !jungle || !isKnownType(edge.archetype) || !isKnownType(jungle.archetype)) continue;
        const key = `${edge.archetype}+${jungle.archetype}`;
        bucket.set(key, (bucket.get(key) || 0) + 1);
      }
    }
    const durations = (list) => mean(list.map((game) => game.duration).filter((value) => has(value) && value > 0));
    const rate = (list, pred) => (list.length ? pct((list.filter(pred).length / list.length) * 100) : '—');
    const hiddenLabels = [];
    for (const [label, core] of [['1 核', 1], ['2 核', 2], ['3 核', 3], ['4 核', 4]]) {
      if (!(coreUp.get(core) || coreDown.get(core))) hiddenLabels.push(label);
    }
    for (const [label, combo] of Object.entries(EDGE_COMBO)) {
      if (!(styleUp.get(combo.join('+')) || styleDown.get(combo.join('+')))) hiddenLabels.push(label);
    }
    const hiddenNote = hiddenLabels.length ? ` <b>本样本没有：${esc(hiddenLabels.join('、'))}</b>，已收起。` : '';
    return card('赢与输的结构差别', `${fmt(rows.length)} 局 · 对手胜 ${fmt(loss.length)} / 本队胜 ${fmt(win.length)}`, `<div class="tp-result">
      <div class="tp-result-col"><header><b>核数 · 上下对冲</b><small>上＝本队胜，下＝对手胜</small></header>${mirrorColumns(['1 核', '2 核', '3 核', '4 核'], new Map([['1 核', coreUp.get(1) || 0], ['2 核', coreUp.get(2) || 0], ['3 核', coreUp.get(3) || 0], ['4 核', coreUp.get(4) || 0]]), new Map([['1 核', coreDown.get(1) || 0], ['2 核', coreDown.get(2) || 0], ['3 核', coreDown.get(3) || 0], ['4 核', coreDown.get(4) || 0]]), {width: 460, height: 210, hideEmpty: true, gamesOf: (key, side) => {
        const core = Number(key.replace(/\D/g, ''));
        return (side === 'up' ? win : loss).filter((game) => (game.sides?.enemy?.lineup?.cores || 0) === core);
      }})}</div>
      <div class="tp-result-col"><header><b>边野搭配 · 上下对冲</b><small>同一套搭配在两种结果里的局数</small></header>${mirrorColumns(['战刺', '战战', '战坦', '坦刺', '坦战', '坦坦'], new Map([['战刺', styleUp.get('战边+刺野') || 0], ['战战', styleUp.get('战边+战野') || 0], ['战坦', styleUp.get('战边+坦野') || 0], ['坦刺', styleUp.get('坦边+刺野') || 0], ['坦战', styleUp.get('坦边+战野') || 0], ['坦坦', styleUp.get('坦边+坦野') || 0]]), new Map([['战刺', styleDown.get('战边+刺野') || 0], ['战战', styleDown.get('战边+战野') || 0], ['战坦', styleDown.get('战边+坦野') || 0], ['坦刺', styleDown.get('坦边+刺野') || 0], ['坦战', styleDown.get('坦边+战野') || 0], ['坦坦', styleDown.get('坦边+坦野') || 0]]), {width: 460, height: 210, hideEmpty: true, gamesOf: (key, side) => {
        const [edgeType, jungleType] = EDGE_COMBO[key] || [];
        return (side === 'up' ? win : loss).filter((game) => {
          const edge = pickOfLane(game, '对抗路'), jungle = pickOfLane(game, '打野');
          return edge?.archetype === edgeType && jungle?.archetype === jungleType;
        });
      }, lanesOf: () => ['对抗路', '打野']})}</div>
    </div>
    <div class="tp-result-stats">
      <div><small>场均时长</small><b class="is-win">${time(durations(win))}</b><b class="is-loss">${time(durations(loss))}</b></div>
      <div><small>四核占比</small><b class="is-win">${rate(win, (game) => (game.sides?.enemy?.lineup?.cores || 0) >= 4)}</b><b class="is-loss">${rate(loss, (game) => (game.sides?.enemy?.lineup?.cores || 0) >= 4)}</b></div>
      <div><small>双坦前排占比</small><b class="is-win">${rate(win, (game) => { const edge = pickOfLane(game, '对抗路'), jungle = pickOfLane(game, '打野'); return edge?.archetype === '坦边' && jungle?.archetype === '坦野'; })}</b><b class="is-loss">${rate(loss, (game) => { const edge = pickOfLane(game, '对抗路'), jungle = pickOfLane(game, '打野'); return edge?.archetype === '坦边' && jungle?.archetype === '坦野'; })}</b></div>
    </div>
    <p class="tp-read">绿＝本队赢下的局，赭＝对手赢下的局；同一分类上下对冲，谁的柱子在下面更粗，就是谁在这种结构里赢得多。只画本样本出现过的分类。${hiddenNote}点柱子可以看对应的局。</p>`, 'is-wide');
  }

  /* ── 头部 ─────────────────────────────────────────────────────── */
  function headBlock(view) {
    const { meta, oppName, matches, avgDuration, oppRate, coverage } = view;
    const thin = matches < 3;
    const tags = [];
    if (thin) tags.push(['样本不足', 'sample']);
    if (matches >= 3 && (oppRate ?? -1) >= 60) tags.push(['交手下风', 'weak']);
    if (matches >= 3 && (oppRate ?? 101) <= 40) tags.push(['交手占优', 'strong']);
    if (meta.named) tags.push(['已命名', 'neutral']);
    if (meta.coach) tags.push([`教练 ${meta.coach}`, 'neutral']);
    if (!tags.length) tags.push(['待观察', 'neutral']);
    const current = meta.currentPlayers || meta.players || [];
    const lanePlayers = [...current].sort((a, b) => {
      const ia = LANES.indexOf(a.lane), ib = LANES.indexOf(b.lane);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    }).slice(0, 5);
    const roster = `<div class="tp-roster" aria-label="当前五人">${LANES.map((lane) => {
      const player = lanePlayers.find((item) => item.lane === lane) || current.find((item) => item.lane === lane);
      return `<span class="tp-player${player ? '' : ' is-empty'}"><i>${esc((player?.name || '?').slice(0, 1))}</i><span><small>${esc(lane)}</small><b>${esc(player?.name || '待补')}</b></span><em>${player ? `${fmt(player.games || 0)} 局` : '—'}</em></span>`;
    }).join('')}</div>`;
    const facts = [
      ['交手', `${fmt(matches)} 局`],
      ['本队战绩', `${fmt(meta.wins)} 胜 ${fmt(meta.losses)} 负`],
      ['对手胜率', pct(oppRate)],
      ['场均时长', time(avgDuration)],
      ['最近交手', text(meta.lastSeen)],
    ];
    if (thin) facts[2][0] = '对手胜率（单局）';
    const boText = coverage && coverage.boKnown
      ? [3, 5, 7].filter((bo) => coverage.boCounts[bo] || coverage.boCounts[String(bo)]).map((bo) => `BO${bo} ${fmt(coverage.boCounts[bo] ?? coverage.boCounts[String(bo)])}`).join(' · ')
      : '';
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
          <p>营地阵容聚类 · 首次 ${text(meta.firstSeen)} · 最近 ${text(meta.lastSeen)}${boText ? ` · ${boText}` : ''}</p>
        </div>
        <div class="tp-tags">${tags.slice(0, 5).map(([label, cls]) => `<span class="tp-tag is-${cls}">${esc(label)}</span>`).join('')}</div>
      </div>
      <dl class="tp-facts">${facts.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`).join('')}</dl>
      ${roster}
      <p class="tp-scope">本页口径：全部营地面板 · 时间窗与赛制筛选只影响下方的分析段，头部数字始终是全样本</p>
    </header>`;
  }

  function briefBlock(view, games) {
    const decided = games.filter((game) => game.opponentWin === true || game.opponentWin === false);
    const losses = decided.filter((game) => game.opponentWin === true).length;
    const lineups = games.map((game) => game.sides?.enemy?.lineup).filter((lineup) => lineup && lineup.total);
    const cores = lineups.map((lineup) => lineup.cores);
    const rows = handRows(games, 'pick');
    const firstLane = modeOf(rows.filter((row) => row.slot === 1 && isKnownLane(row.lane)).map((row) => row.lane));
    const boText = [3, 5, 7].map((bo) => ({bo, games: games.filter((game) => Number(game.bo) === bo)})).filter((row) => row.games.length).map((row) => `BO${row.bo} ${fmt(row.games.length)} 局`).join(' / ');
    const parts = [
      `${fmt(games.length)} 局样本${boText ? `（${boText}）` : ''}`,
      cores.length ? `最常见 ${modeOf(cores).values.join('/')} 核` : '',
      firstLane ? `第一手最常落在${esc(firstLane.values.join('/'))}` : '',
      `对手 ${fmt(losses)} 胜 ${fmt(decided.length - losses)} 负`,
    ].filter(Boolean);
    return `<div data-tp-mount="brief"><section class="tp-brief" aria-label="阶段性观察">
      <span class="tp-brief-label">阶段性观察</span>
      <div class="tp-brief-body"><p class="tp-brief-line">${parts.join('，')}。</p><p class="tp-brief-note">只描述当前筛选内的分布，不构成强弱结论。</p></div>
    </section></div>`;
  }

  const section = (id, no, title, sub, chip, body) => `<section class="tp-sec${state.section === id ? ' is-active' : ''}" id="${id}" data-no="${no}" role="tabpanel" aria-labelledby="tp-tab-${id}"${state.section === id ? '' : ' hidden'}>
    <header class="tp-sec-head"><div class="tp-sec-title"><h2>${title}</h2>${chip ? `<span class="tp-sec-chip">${esc(chip)}</span>` : ''}<button type="button" class="tp-sec-copy" data-tp-section-copy="${id}" title="复制本节的文字与表格">复制本节</button></div><p class="tp-sec-sub">${sub}</p></header>
    <div class="tp-sec-body" id="${id}-body">${body}</div>
  </section>`;

  const NAV = [['tp-overview', '01 样本'], ['tp-bp', '02 BP 手序'], ['tp-comp', '03 阵容与风格'], ['tp-pool', '04 英雄池'], ['tp-result', '05 结果']];

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
    const section01 = section('tp-overview', '01', '样本与整体', '三个能跨队比的数，带环比与交手时间线。', `${fmt(games.length)} 局`, `<div class="tp-grid is-2-1">${baseBoard(games)}${formCard(games)}</div>${noteCard()}`);
    const section02 = section('tp-bp', '02', 'BP 手序', '分路与类型的协作分布，按手序、分路、时间窗拆开看。', `${fmt(known.length)} 局有手序`, bpDistribution(games) + `<div class="tp-grid is-2">${handStream(games)}${priorityCard(games)}</div>` + driftCard(games));
    const section03 = section('tp-comp', '03', '阵容与风格', '边野怎么搭、几核、五路类型与位置组合。', `${fmt(games.length)} 局`, styleCard(games) + `<div class="tp-grid is-2">${coreCard(games)}${laneTypeCard(games)}</div>` + pairCard(games));
    const section04 = section('tp-pool', '04', '英雄池', '每个位置他们选什么、被 ban 什么、被 ban 之后拿谁。', `${fmt(games.length)} 局`, poolCard(games));
    const section05 = section('tp-result', '05', '结果', '赢下的局和对手赢下的局，结构差在哪。', `${fmt(games.length)} 局`, resultCard(games));
    return scopeStrip(games) + section01 + section02 + section03 + section04 + section05 + tabFoot();
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
      ${briefBlock(view, games)}
      ${filterChips()}
      ${tabsBar()}
      <div data-tp-analysis>${bodyHtml(view, games)}</div>
      ${drawerShell()}
    </div>`;
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
    const brief = root.querySelector('[data-tp-mount="brief"]');
    if (brief) brief.innerHTML = briefBlock(model, games);
    const nav = root.querySelector('.tp-tabs');
    if (nav) nav.outerHTML = tabsBar();
    const stat = root.querySelector('[data-tp-mount="filterstat"]');
    if (stat) stat.innerHTML = filterStat(games.length, model.deepGames.length);
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
    } else if (name === 'days') {
      state.days = value;
      if (value === 'custom' && !state.from) {
        const days = model?.days || [];
        if (days.length) { state.from = days[0]; state.to = days[days.length - 1]; }
      }
    } else if (name === 'bo') {
      state.bo = value;
    } else if (['hand', 'lane', 'mode', 'bpHero', 'poolHero', 'bpHeroLane', 'poolHeroLane'].includes(name)) {
      state[name] = value;
      if (name === 'mode') state.bpHero = 'all';
      if (name === 'lane' && value !== 'all') state.bpHeroLane = value;
    } else if (name === 'from' || name === 'to') {
      state[name] = value;
    }
    if (name === 'days' || name === 'bo') {
      const host = root?.querySelector('.tp-filter');
      if (host) host.outerHTML = filterChips();
    }
    repaint(root);
  }

  return {render, setFilter, setSection, repaint, openGames, closeGames, state, get model() { return model; }};
}
