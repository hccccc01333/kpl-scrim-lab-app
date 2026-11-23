/* 选手详情页可视图元 v2（2026-11-16 第二版：面板化 / 去横向细长条）

   这一版只做「密度高、对齐齐、信息多」的图：
   - 纵向柱（分组 / 双向 / 带误差须 / 直方分布）—— 取代原来一行一条的横条；
   - 矩形树图、热力矩阵、箱线图、雷达、环形、气泡四象限、折线带；
   - 一切图都放进 12 栏网格的面板里，一行铺满，不留大片空白；
   - 每张图都能塞进多层信息：颜色 + 尺寸 + 参考线 + 数值 + 悬浮说明。

   约定：
   1. 纯字符串模板 + 内联 SVG，不引图表库；
   2. 颜色走 ui-tokens 变量与 --pv-c1..6 分类色，深色主题自动跟随；
   3. 悬浮说明用原生 <title>，没有 JS 提示层；
   4. 图一律 role="img" + aria-label。 */
export function createPlayerViz({esc, fmt}) {
  const S = (v) => esc(String(v ?? ''));
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const N = (v, d = 0) => (isNum(v) ? fmt(v, d) : '—');
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const signed = (v, d = 0) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmt(v, d)}` : '—');
  const FULL = 1400;
  const empty = (text) => `<p class="pv-empty">${S(text)}</p>`;

  /* 分路固定配色：同一路在整页所有图里颜色一致，读图不用反复找 legend。 */
  const LANE_CLS = {'对抗路': 'is-c1', '打野': 'is-c2', '中路': 'is-c3', '发育路': 'is-c4', '游走': 'is-c5'};
  const laneCls = (lane) => LANE_CLS[lane] || 'is-c6';
  const CAT = ['is-c1', 'is-c2', 'is-c3', 'is-c4', 'is-c5', 'is-c6'];
  const catCls = (i) => CAT[i % CAT.length];

  /* ── 图宽：按「这张图占 12 栏里的几栏」来算 ─────────────────────────
     以前每张图都写死 W=1200，塞进 5/7 栏的面板右边就被切掉一大截
     （替代候选那张图在 1440 宽屏上溢出 470px）。现在由面板宽度反推：
     内容宽 → 12 栏网格 → 面板内宽，图按这个像素画，正好 1:1；
     估计偏大时再由 CSS 的 max-width:100% 等比收一点，绝不横向溢出。 */
  function gridWidth() {
    const hasWin = typeof window !== 'undefined' && Number(window.innerWidth) > 0;
    const vw = hasWin ? Number(window.innerWidth) : 1440;
    /* .page-wide 两侧各 48px；1100px 以下面板一律铺满 12 栏（见 CSS）。 */
    return {grid: Math.min(Math.max(vw, 960), 1800) - 32 - 64, wide: !hasWin || vw > 1100};
  }
  /* span = 面板占的栏数（4/5/6/7/8/12），返回这张图能用的像素宽。 */
  const w = (span = 12) => {
    const {grid, wide} = gridWidth();
    const eff = wide ? Math.min(12, Math.max(4, span)) : 12;
    const GAP = 12, PAD = 30;
    const panel = (grid - 11 * GAP) * eff / 12 + (eff - 1) * GAP;
    return Math.max(300, Math.round(panel - PAD));
  };

  /* 关键的渲染约定：SVG 用 viewBox 的原始像素当上限（max-width），
     面板比它宽时按 1:1 显示，不再被放大。之前图表被拉伸到 2 倍，
     字形落在分数像素上，看起来就是「发虚」。
     宽度不写死在 inline style 上：让 CSS 的 max-width:100% 兜底，
     这样即使估宽有偏差也只是略微等比缩小，不会切掉右边的柱子。 */
  const svg = (w, h, inner, aria) => `<svg class="pv-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"
    role="img" aria-label="${S(aria)}" preserveAspectRatio="xMidYMid meet">${inner}</svg>`;

  /* ── 面板网格：一行 12 栏，图按 4 / 5 / 6 / 7 / 8 / 12 栏铺满 ──────── */
  const panel = (title, body, opt = {}) => `<section class="pv-panel${opt.span ? ` is-${opt.span}` : ''}">
    ${title || opt.right ? `<header class="pv-panel-head"><h4>${title || ''}</h4>${opt.right ? `<span class="pv-panel-right">${opt.right}</span>` : ''}</header>` : ''}
    <div class="pv-panel-body">${body}</div>
  </section>`;
  const grid = (list) => `<div class="pv-grid">${list.filter(Boolean).join('')}</div>`;

  /* ── 轴刻度 ──────────────────────────────────────────────────────── */
  function niceTicks(lo, hi, count = 4) {
    if (!isNum(lo) || !isNum(hi)) return {lo: 0, hi: 1, ticks: [0, 1]};
    if (hi === lo) { const pad = Math.abs(hi) * 0.1 || 1; lo -= pad; hi += pad; }
    const span = hi - lo;
    const step = Math.pow(10, Math.floor(Math.log10(span / count)));
    const err = span / count / step;
    const mult = err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    const unit = step * mult;
    const start = Math.floor(lo / unit) * unit;
    const end = Math.ceil(hi / unit) * unit;
    const ticks = [];
    for (let v = start; v <= end + unit * 0.5; v += unit) ticks.push(Math.round(v / unit) * unit);
    return {lo: start, hi: end, ticks};
  }

  /* ── 纵向柱：分组 / 双向 / 带误差须，一个函数覆盖全页的柱状图 ────────
     - 有负值时基线自动落在 0，柱子上下长（环比、经济差都用它）；
     - series 可以给多条，同一类目并排分组（本人 vs 同英雄基准）；
     - series.lo / series.hi 给误差须（置信区间、标准差）；
     - labelsHtml 给了就用 HTML 画 x 轴标签，能塞英雄头像并与柱子严格对齐。 */
  function columns(opt) {
    const {
      labels = [], labelsHtml = null, series = [], W = FULL, H = 260,
      padL = 46, padR = 16, padT = 22, padB = 30, fmtV = (v) => N(v, 0),
      refs = [], yTicks = 4, maxBarW = 34, aria = '柱状图', showValues = true,
      minText = null, forceZero = false, valueInside = false,
    } = opt;
    const n = Math.max(labels.length, ...series.map((s) => s.values.length), 0);
    const all = series.flatMap((s) => [...(s.values || []), ...(s.lo || []), ...(s.hi || [])]).filter(isNum);
    if (!n || !all.length) return empty('这一组没有可画的数值。');
    /* 用 HTML 画 x 轴标签时，SVG 底部不需要再留文字空间。 */
    const axisPad = labelsHtml ? 12 : padB;
    let lo = Math.min(...all), hi = Math.max(...all);
    const hasNeg = lo < 0;
    if (hasNeg || forceZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (isNum(opt.yMin)) lo = Math.min(lo, opt.yMin);
    if (isNum(opt.yMax)) hi = Math.max(hi, opt.yMax);
    const pad = (hi - lo) * 0.14 || 1;
    /* baseline：
       zero —— 轴从 0 起，柱长直接就是量值（场次、百分比、经济差都用这个）；
       auto —— 轴从数据下端起，只用来排序，柱长不读绝对值（评分、KDA 这类窄区间指标）。 */
    const lower = hasNeg || forceZero ? lo : opt.baseline === 'auto' ? lo - pad * 0.7 : 0;
    const upper = isNum(opt.yMax) ? Math.max(opt.yMax, hi) : hi + pad;
    const tick = niceTicks(lower, upper, yTicks);
    const base = hasNeg || forceZero ? 0 : tick.lo;
    const plotW = W - padL - padR, plotH = H - padT - (labelsHtml ? 14 : padB);
    const slot = plotW / n;
    const y = (v) => padT + plotH - (v - tick.lo) / Math.max(1e-9, tick.hi - tick.lo) * plotH;
    const zeroY = y(base);
    const groups = Math.max(1, series.length);
    const barW = Math.min(maxBarW, slot * 0.74 / groups);
    const offset = (gi) => slot * gi / groups + (slot / groups - barW) / 2;
    /* 槽位窄到放不下数字时就不标了：46 个英雄挤一张图时，
       标了也是糊成一片，不如让 bar 自己说话（悬浮仍有 <title>）。 */
    const showVals = showValues && slot >= 26;

    const tickList = tick.ticks.filter((v) => v >= tick.lo - 1e-9 && v <= tick.hi + 1e-9);
    const gridHtml = tickList.map((v) => `<line class="pv-grid" x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}"/>
      <text class="pv-axis" x="${padL - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${S(fmtV(v))}</text>`).join('');
    const refsHtml = refs.filter((r) => isNum(r.v)).map((r) => `<line class="pv-ref ${r.cls || ''}" x1="${padL}" y1="${y(r.v).toFixed(1)}" x2="${W - padR}" y2="${y(r.v).toFixed(1)}"/>
      ${r.label ? `<text class="pv-ref-label" x="${W - padR - 4}" y="${(y(r.v) - 6).toFixed(1)}" text-anchor="end">${S(r.label)}</text>` : ''}`).join('');

    const bars = series.map((s, gi) => (s.values || []).map((v, i) => {
      if (!isNum(v)) return '';
      const x0 = padL + slot * i + offset(gi);
      const top = Math.min(y(v), zeroY), h = Math.max(1.5, Math.abs(y(v) - zeroY));
      const cls = (s.clsAt && s.clsAt[i]) || s.cls || '';
      const text = s.texts && s.texts[i];
      /* 文字贴着柱端放，但不能越过绘图区：
         碰到顶部（柱顶到 100% 这种）就翻到柱子里面，用白字，
         否则深色数字压在深色柱子上等于没画。 */
      const plotBottom = H - (labelsHtml ? 14 : padB);
      let anchorY = 0, inside = false;
      if (v >= base) {
        anchorY = Math.max(padT + 9, top - 6);
        if (anchorY > top - 2) { inside = true; anchorY = Math.min(top + 17, plotBottom - 4); }
      } else {
        anchorY = Math.min(plotBottom - 3, top + h + 13);
        if (anchorY < top + h + 2) { inside = true; anchorY = Math.max(top + h - 6, padT + 8); }
      }
      const label = showVals && text != null
        ? `<text class="pv-col-val ${cls}${inside ? ' is-inside' : ''}" x="${(x0 + barW / 2).toFixed(1)}" y="${anchorY.toFixed(1)}" text-anchor="middle">${S(text)}</text>` : '';
      const whisk = isNum((s.lo || [])[i]) && isNum((s.hi || [])[i])
        ? `<line class="pv-whisk" x1="${(x0 + barW / 2).toFixed(1)}" y1="${y(s.lo[i]).toFixed(1)}" x2="${(x0 + barW / 2).toFixed(1)}" y2="${y(s.hi[i]).toFixed(1)}"/>
           <line class="pv-whisk-cap" x1="${(x0 + barW / 2 - 5).toFixed(1)}" y1="${y(s.lo[i]).toFixed(1)}" x2="${(x0 + barW / 2 + 5).toFixed(1)}" y2="${y(s.lo[i]).toFixed(1)}"/>
           <line class="pv-whisk-cap" x1="${(x0 + barW / 2 - 5).toFixed(1)}" y1="${y(s.hi[i]).toFixed(1)}" x2="${(x0 + barW / 2 + 5).toFixed(1)}" y2="${y(s.hi[i]).toFixed(1)}"/>` : '';
      return `<rect class="pv-col ${cls}" x="${x0.toFixed(1)}" y="${top.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3"><title>${S(`${labels[i] || `第 ${i + 1} 列`}${series.length > 1 ? ` · ${s.name || ''}` : ''} ${fmtV(v)}`)}</title></rect>${whisk}${label}`;
    }).join('')).join('');

    const axis = `<line class="pv-axis-line" x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${W - padR}" y2="${zeroY.toFixed(1)}"/>`;
    /* 类目多、槽位窄时按间隔抽稀，避免 x 轴文字叠在一起。 */
    const every = Math.max(1, Math.ceil(labels.length / Math.max(1, Math.floor(plotW / 46))));
    const svgLabels = labelsHtml ? '' : labels.map((text, i) => {
      if (labels.length > 2 && i % every !== 0 && i !== labels.length - 1) return '';
      const x = padL + slot * i + slot / 2;
      const short = String(text).length > 9 ? `${String(text).slice(0, 8)}…` : String(text);
      return `<text class="pv-axis" x="${x.toFixed(1)}" y="${H - padB + 18}" text-anchor="middle">${S(short)}</text>`;
    }).join('');
    const core = svg(W, H, `${gridHtml}${refsHtml}${axis}${bars}${svgLabels}`, aria);
    if (!labelsHtml) return core;
    const nG = Math.max(1, labelsHtml.length);
    return `<div class="pv-colwrap">${core}<div class="pv-collabels" style="padding-left:${(padL / W * 100).toFixed(2)}%;padding-right:${(padR / W * 100).toFixed(2)}%;grid-template-columns:repeat(${nG},minmax(0,1fr))">${
      labelsHtml.map((x) => `<span>${x}</span>`).join('')}</div></div>`;
  }

  /* ── 矩形树图：英雄使用面积图（面积 = 场次，颜色 = 分路）────────────
     用 HTML 绝对定位而不是 SVG：格子要放英雄头像（<img>），SVG 里塞不进 HTML 图；
     顺带用 CSS 的 ellipsis 解决长名字溢出，不用手算截断。

     一个赛季下来英雄会到 40+ 个，全铺进 620×330 会碎成一堆看不清的细条，
     所以默认只画前 top 个，剩下的并成一块「其他 N 个英雄」：
     面积仍然如实加总，但小块不再抢视觉。listDetail 里给完整清单。 */
  function treemap(opt) {
    const {items = [], W = 620, H = 320, aria = '矩形树图', top = 13, pickName = '', showSub = true} = opt;
    let list = items.filter((x) => isNum(x.value) && x.value > 0).sort((a, b) => b.value - a.value);
    if (!list.length) return empty('这一组没有可铺的面积。');
    let restCount = 0, restValue = 0;
    if (list.length > top) {
      const rest = list.slice(top - 1);
      restCount = rest.length;
      restValue = rest.reduce((a, b) => a + b.value, 0);
      list = list.slice(0, top - 1).concat([{
        label: `其他 ${restCount} 个英雄`, value: restValue, cls: 'is-other',
        sub: `${fmtVDefault(restValue)} · 各 ${Math.max(1, Math.round(restValue / restCount))} 局左右`,
        title: `还有 ${restCount} 个英雄合计 ${fmtVDefault(restValue)}：${rest.map((x) => `${x.label} ${x.value}`).slice(0, 14).join('、')}${restCount > 14 ? ' …' : ''}`,
      }]);
    }
    const total = list.reduce((a, b) => a + b.value, 0);
    const rows = [];
    let rest = list.slice(), scale = (W * H) / total;
    const worst = (row, w) => {
      const s = row.reduce((a, b) => a + b.value * scale, 0);
      const mx = Math.max(...row.map((b) => b.value * scale));
      const mn = Math.min(...row.map((b) => b.value * scale));
      return Math.max((w * w * mx) / (s * s), (s * s) / (w * w * mn));
    };
    let box = {x: 0, y: 0, w: W, h: H};
    while (rest.length) {
      const vertical = box.w >= box.h;
      const side = vertical ? box.h : box.w;
      let row = [rest[0]], i = 1;
      while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) { row.push(rest[i]); i += 1; }
      const sum = row.reduce((a, b) => a + b.value * scale, 0);
      const thick = sum / side;
      let acc = vertical ? box.y : box.x;
      for (const item of row) {
        const len = (item.value * scale) / thick;
        rows.push(vertical
          ? {item, x: box.x, y: acc, w: thick, h: len}
          : {item, x: acc, y: box.y, w: len, h: thick});
        acc += len;
      }
      rest = rest.slice(row.length);
      box = vertical ? {x: box.x + thick, y: box.y, w: box.w - thick, h: box.h} : {x: box.x, y: box.y + thick, w: box.w, h: box.h - thick};
    }
    return `<div class="pv-tm" role="img" aria-label="${S(aria)}" style="--pv-tm-ratio:${W} / ${H}">
      ${rows.map(({item, x, y, w, h}) => {
        const mid = w > 52 && h > 30;
        /* 小方块只留头像和名字；够大才写「局数 · 胜率」，免得小字挤成一团。 */
        const roomy = w > 120 && h > 90 && w * h > 15000;
        const attrs = `left:${(x / W * 100).toFixed(2)}%;top:${(y / H * 100).toFixed(2)}%;width:${(w / W * 100).toFixed(2)}%;height:${(h / H * 100).toFixed(2)}%`;
        const inner = `<span class="pv-tm-face">${item.icon || ''}</span>
          <b>${S(item.label)}</b>${showSub && roomy && item.sub ? `<small>${S(item.sub)}</small>` : ''}`;
        const cls = `pv-tm-tile ${item.cls || ''}${mid ? ' is-mid' : ''}`;
        const tip = S(item.title || `${item.label} · ${fmtVDefault(item.value)}`);
        /* 点方块 = 把这个英雄设成当前切片（不再跳英雄页：跳走就看不到切片效果了）；
           英雄页入口留在卡片标题与「英雄」下拉里。 */
        if (pickName && item.pick) {
          return `<button type="button" class="${cls}" style="${attrs}" data-pdx-set="${S(pickName)}:${S(item.pick)}"
            title="${tip}｜点击只看这位英雄，再点一次回到全部">${inner}</button>`;
        }
        if (item.href) return `<a class="${cls}" href="${item.href}" style="${attrs}" title="${tip}">${inner}</a>`;
        return `<span class="${cls}" style="${attrs}" title="${tip}">${inner}</span>`;
      }).join('')}
    </div>`;
  }
  const fmtVDefault = (v) => `${N(v, 0)} 局`;

  /* ── 热力矩阵：分路 × 指标 / 英雄 × 训练日 / 英雄 × 英雄 ───────────
     颜色是唯一量纲，格子里放数值；行头列头固定，整块对齐。

     列一多（一个赛季能攒 40 个训练日）就不再压缩格子宽度，改成横向滚动：
     格子保持 44px 宽、行头吸在左边，信息一条不丢，也不会缩成看不懂的细线。 */
  function heat(opt) {
    const {rows = [], cols = [], aria = '热力矩阵', fmtV = (v) => N(v, 0), max = null, min = 0,
      diverging = false, legend = '', empty: emptyText = '', cellH = 0,
      scrollAt = 9, headW = 150, colW = 52, fit = 0} = opt;
    if (!rows.length || !cols.length) return empty('这一格还没有可对位的组合。');
    const flat = rows.flatMap((r) => r.cells.map((c) => (c && isNum(c.v) ? c.v : null))).filter(isNum);
    const top = max ?? Math.max(1e-9, ...flat), bot = diverging ? 0 : min;
    const cells = rows.map((row) => `<div class="pv-heat-row${row.cls ? ' ' + row.cls : ''}">
      <div class="pv-heat-head">${row.labelHtml || S(row.label)}</div>
      ${cols.map((col, ci) => {
        const cell = row.cells[ci];
        if (!cell || !isNum(cell.v)) return `<div class="pv-heat-cell is-empty" title="${S(`${row.label || ''} × ${col.label || ''} · 无记录`)}"><span>${S(emptyText)}</span></div>`;
        const t = diverging
          ? clamp((cell.v - 50) / 50, -1, 1)
          : clamp((cell.v - bot) / Math.max(1e-9, top - bot), 0, 1);
        const level = Math.round(Math.abs(t) * 10) / 10;
        /* 分位型热力用方向色（偏高走 accent、偏低走 warning），普通热力只用一个色阶。 */
        const sign = diverging ? (t > 0.12 ? 'up' : t < -0.12 ? 'down' : 'mid') : '';
        return `<div class="pv-heat-cell ${cell.cls || ''}"${sign ? ` data-sign="${sign}"` : ''} style="--pv-heat:${level}" title="${S(cell.title || `${row.label} × ${col.label} · ${fmtV(cell.v)}`)}"><b>${S(cell.text ?? fmtV(cell.v))}</b>${cell.sub ? `<small>${S(cell.sub)}</small>` : ''}</div>`;
      }).join('')}
    </div>`).join('');
    const head = `<div class="pv-heat-row is-head"><div class="pv-heat-head"></div>${cols.map((col) => `<div class="pv-heat-col">${col.iconHtml || S(col.label)}</div>`).join('')}</div>`;
    /* 列宽按「表头放得下」来定：指标名 5 个字要 78px，日期 5 个字 52px 够。
       放不下就横向滚动，而不是把格子压到 46px 让表头互相压字。 */
    const gap = 4;
    const need = headW + cols.length * colW + cols.length * gap;
    const scroll = fit ? need > fit - 6 : cols.length > scrollAt;
    return `<div class="pv-heat${cellH ? ' is-tall' : ''}${scroll ? ' is-scroll' : ''}" role="img" aria-label="${S(aria)}"
      style="--pv-heat-cols:${cols.length};--pv-heat-headw:${headW}px;--pv-heat-colw:${colW}px">
      ${head}${cells}${legend ? `<div class="pv-heat-legend">${legend}</div>` : ''}</div>`;
  }

  /* ── 箱线图（纵向）：稳定性分层用，一眼看出中位、四分位和离散范围 ──── */
  function boxplot(opt) {
    const {groups = [], W = FULL, H = 280, padL = 46, padR = 16, padT = 20, padB = 34,
      fmtV = (v) => N(v, 0), aria = '箱线图', labelsHtml = null, refs = []} = opt;
    const list = groups.filter((g) => isNum(g.med));
    if (!list.length) return empty('没有足够的分组建箱。');
    const all = list.flatMap((g) => [g.lo, g.hi, g.med]).filter(isNum);
    const tick = niceTicks(Math.min(...all), Math.max(...all), 4);
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const slot = plotW / list.length;
    const y = (v) => padT + plotH - (v - tick.lo) / Math.max(1e-9, tick.hi - tick.lo) * plotH;
    const gridHtml = tick.ticks.map((v) => `<line class="pv-grid" x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}"/>
      <text class="pv-axis" x="${padL - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${S(fmtV(v))}</text>`).join('');
    const refsHtml = refs.filter((r) => isNum(r.v)).map((r) => `<line class="pv-ref" x1="${padL}" y1="${y(r.v).toFixed(1)}" x2="${W - padR}" y2="${y(r.v).toFixed(1)}"/>
      ${r.label ? `<text class="pv-ref-label" x="${padL + 4}" y="${(y(r.v) - 5).toFixed(1)}">${S(r.label)}</text>` : ''}`).join('');
    const bw = Math.min(44, slot * 0.5);
    const body = list.map((g, i) => {
      const cx = padL + slot * i + slot / 2;
      const cls = g.cls || 'is-a';
      return `<line class="pv-box-whisk" x1="${cx}" y1="${y(g.lo).toFixed(1)}" x2="${cx}" y2="${y(g.hi).toFixed(1)}"/>
        <line class="pv-box-cap" x1="${(cx - bw / 3).toFixed(1)}" y1="${y(g.lo).toFixed(1)}" x2="${(cx + bw / 3).toFixed(1)}" y2="${y(g.lo).toFixed(1)}"/>
        <line class="pv-box-cap" x1="${(cx - bw / 3).toFixed(1)}" y1="${y(g.hi).toFixed(1)}" x2="${(cx + bw / 3).toFixed(1)}" y2="${y(g.hi).toFixed(1)}"/>
        <rect class="pv-box ${cls}" x="${(cx - bw / 2).toFixed(1)}" y="${y(g.q3).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(2, y(g.q1) - y(g.q3)).toFixed(1)}" rx="3"><title>${S(`${g.label} · 中位 ${fmtV(g.med)} · 四分位 ${fmtV(g.q1)} ~ ${fmtV(g.q3)} · 全距 ${fmtV(g.lo)} ~ ${fmtV(g.hi)} · ${fmt(g.n || 0)} 局`)}</title></rect>
        <line class="pv-box-med ${cls}" x1="${(cx - bw / 2).toFixed(1)}" y1="${y(g.med).toFixed(1)}" x2="${(cx + bw / 2).toFixed(1)}" y2="${y(g.med).toFixed(1)}"/>
        ${g.games ? `<text class="pv-axis" x="${cx}" y="${(padT + plotH + 14).toFixed(1)}" text-anchor="middle">${S(g.label)}</text>
        <text class="pv-axis is-dim" x="${cx}" y="${(padT + plotH + 27).toFixed(1)}" text-anchor="middle">${fmt(g.games)} 局</text>` : ''}`;
    }).join('');
    const core = svg(W, H, `${gridHtml}${refsHtml}${body}`, aria);
    if (!labelsHtml) return core;
    return `<div class="pv-colwrap">${core}<div class="pv-collabels" style="padding-left:${(padL / W * 100).toFixed(2)}%;padding-right:${(padR / W * 100).toFixed(2)}%;grid-template-columns:repeat(${labelsHtml.length},minmax(0,1fr))">${labelsHtml.map((x) => `<span>${x}</span>`).join('')}</div></div>`;
  }

  /* ── 折线（可带面积、置信带、逐点配色、事件标记）──────────────────── */
  function line(opt) {
    const {labels = [], series = [], W = FULL, H = 240, padL = 52, padR = 22, padT = 18, padB = 34,
      fmtY = (v) => N(v, 0), yTicks = 4, dots = true, area = false, refs = [], bands = [],
      zero = false, aria = '走势折线', muted = false} = opt;
    const n = Math.max(labels.length, ...series.map((s) => s.values.length), 0);
    if (!n) return empty('这一组没有可画的时间点。');
    const all = series.flatMap((s) => s.values).filter(isNum);
    if (!all.length) return empty('这一组没有可用数值。');
    let lo = Math.min(...all), hi = Math.max(...all);
    if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    const pad = (hi - lo) * 0.12 || Math.max(1, Math.abs(hi) * 0.1);
    const tick = niceTicks(zero ? lo : lo - pad, hi + pad, yTicks);
    const x = (i) => padL + (n === 1 ? (W - padL - padR) / 2 : i * (W - padL - padR) / (n - 1));
    const y = (v) => padT + (H - padT - padB) - (v - tick.lo) / Math.max(1e-9, tick.hi - tick.lo) * (H - padT - padB);
    const grid = tick.ticks.map((v) => `<line class="pv-grid" x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}"/>
      <text class="pv-axis" x="${padL - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${S(fmtY(v))}</text>`).join('');
    const bandsHtml = bands.map((b) => {
      const a = x(clamp(b.from, 0, n - 1)), z = x(clamp(b.to, 0, n - 1));
      return `<rect class="pv-band ${b.cls || ''}" x="${Math.min(a, z).toFixed(1)}" y="${padT}" width="${Math.max(2, Math.abs(z - a)).toFixed(1)}" height="${(H - padT - padB).toFixed(1)}"/>`;
    }).join('');
    const refsHtml = refs.filter((r) => isNum(r.v)).map((r) => `<line class="pv-ref ${r.cls || ''}" x1="${padL}" y1="${y(r.v).toFixed(1)}" x2="${W - padR}" y2="${y(r.v).toFixed(1)}"/>
      ${r.label ? `<text class="pv-ref-label" x="${W - padR}" y="${(y(r.v) - 5).toFixed(1)}" text-anchor="end">${S(r.label)}</text>` : ''}`).join('');
    const every = Math.max(1, Math.ceil(n / 10));
    const xLabels = labels.map((text, i) => (i % every === 0 || i === n - 1)
      ? `<text class="pv-axis" x="${x(i).toFixed(1)}" y="${H - padB + 18}" text-anchor="middle">${S(text)}</text>` : '').join('');
    const paths = series.map((s) => {
      let d = '', open = false;
      s.values.forEach((v, i) => {
        if (!isNum(v)) { open = false; return; }
        d += `${open ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
        open = true;
      });
      if (!d) return '';
      const fill = area && series.length <= 2 && s.fill !== false
        ? `<path class="pv-area ${s.cls || ''}" d="${d}L${x(s.values.length - 1).toFixed(1)} ${y(tick.lo).toFixed(1)}L${x(0).toFixed(1)} ${y(tick.lo).toFixed(1)}Z"/>` : '';
      return `${fill}<path class="pv-line ${s.cls || ''}" d="${d}"${s.dash ? ' stroke-dasharray="5 5"' : ''}/>`;
    }).join('');
    const dotsHtml = dots ? series.map((s) => s.values.map((v, i) => isNum(v)
      ? `<circle class="pv-dot ${(s.pointCls && s.pointCls[i]) || s.cls || ''}" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${s.r || 3.6}"><title>${S(`${labels[i] || `第 ${i + 1} 点`} · ${s.name || ''} ${fmtY(v)}`)}</title></circle>` : '').join('')).join('') : '';
    return svg(W, H, `${bandsHtml}${grid}${refsHtml}${paths}${dotsHtml}${xLabels}`, aria);
  }

  /* ── 散点 / 气泡（可带四象限底色、标签、半径编码）────────────────── */
  function scatter(opt) {
    const {points = [], W = FULL, H = 320, padL: padL0 = 56, padR = 26, padT: padT0 = 24, padB = 44,
      xDomain = null, yDomain = null, xTicks = 5, yTicks = 4, refX = null, refY = null,
      fmtX = (v) => N(v, 0), fmtY = (v) => N(v, 0), xLabel = '', yLabel = '', aria = '散点图',
      quadrants = null} = opt;
    const list = points.filter((p) => isNum(p.x) && isNum(p.y));
    if (!list.length) return empty('这一组没有可落点的记录。');
    /* 动态留白：y 轴名竖排占左侧一条；气泡最大半径 21px + 标签字高约 18px，
       顶部留够才不会让「左上角」的点标签压到轴名或跑到图外。 */
    const padL = Math.max(padL0, yLabel ? 76 : padL0);
    const padT = Math.max(padT0, 21 + 5 + 18 + 6);
    const rMax = Math.max(1, ...list.map((p) => (isNum(p.r) ? p.r : 1)));
    const norm = (d, lo, hi, count) => (Array.isArray(d)
      ? {lo: d[0], hi: d[1], ticks: niceTicks(d[0], d[1], count).ticks}
      : d || niceTicks(lo, hi, count));
    const xd = norm(xDomain, Math.min(...list.map((p) => p.x)), Math.max(...list.map((p) => p.x)), xTicks);
    const auto = norm(yDomain, Math.min(...list.map((p) => p.y)), Math.max(...list.map((p) => p.y)), yTicks);
    const yPad = (auto.hi - auto.lo) * 0.06;
    const yd = yDomain ? auto : {lo: auto.lo - yPad, hi: auto.hi + yPad, ticks: auto.ticks};
    const x = (v) => padL + (clamp(v, xd.lo, xd.hi) - xd.lo) / Math.max(1e-9, xd.hi - xd.lo) * (W - padL - padR);
    const y = (v) => padT + (H - padT - padB) - (clamp(v, yd.lo, yd.hi) - yd.lo) / Math.max(1e-9, yd.hi - yd.lo) * (H - padT - padB);
    /* 四象限：底色 + 四个角落的说明文字（位置按绘图区百分比，不依赖数据坐标） */
    const quad = quadrants && isNum(refX) && isNum(refY)
      ? `<rect class="pv-quad" x="${padL}" y="${padT}" width="${(W - padL - padR).toFixed(1)}" height="${(y(refY) - padT).toFixed(1)}"/>
         <rect class="pv-quad is-dim" x="${x(refX).toFixed(1)}" y="${padT}" width="${(W - padR - x(refX)).toFixed(1)}" height="${(y(refY) - padT).toFixed(1)}"/>
         ${(Array.isArray(quadrants) ? quadrants : []).map((text, i) => {
           if (!text) return '';
           const qx = i % 2 === 0 ? padL + 10 : W - padR - 10;
           const qy = i < 2 ? padT + 16 : H - padB - 10;
           return `<text class="pv-quad-label" x="${qx.toFixed(1)}" y="${qy.toFixed(1)}" text-anchor="${i % 2 === 0 ? 'start' : 'end'}">${S(text)}</text>`;
         }).join('')}` : '';
    const grid = `${(xd.ticks || []).filter((v) => v >= xd.lo && v <= xd.hi).map((v) => `<line class="pv-grid" x1="${x(v).toFixed(1)}" y1="${padT}" x2="${x(v).toFixed(1)}" y2="${H - padB}"/>
      <text class="pv-axis" x="${x(v).toFixed(1)}" y="${H - padB + 18}" text-anchor="middle">${S(fmtX(v))}</text>`).join('')}
      ${(yd.ticks || []).filter((v) => v >= yd.lo && v <= yd.hi).map((v) => `<line class="pv-grid" x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}"/>
      <text class="pv-axis" x="${padL - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${S(fmtY(v))}</text>`).join('')}`;
    const refs = `${isNum(refX) ? `<line class="pv-ref" x1="${x(refX).toFixed(1)}" y1="${padT}" x2="${x(refX).toFixed(1)}" y2="${H - padB}"/>` : ''}
      ${isNum(refY) ? `<line class="pv-ref" x1="${padL}" y1="${y(refY).toFixed(1)}" x2="${W - padR}" y2="${y(refY).toFixed(1)}"/>` : ''}
      ${opt.diagonal ? `<line class="pv-ref is-diag" x1="${x(xd.lo).toFixed(1)}" y1="${y(yd.lo).toFixed(1)}" x2="${x(Math.min(xd.hi, yd.hi)).toFixed(1)}" y2="${y(Math.min(xd.hi, yd.hi)).toFixed(1)}"/>` : ''}`;
    const bubbles = list.map((p) => {
      const r = 5 + Math.sqrt((isNum(p.r) ? p.r : 1) / rMax) * 16;
      const px = x(p.x), py = y(p.y);
      /* 点标签默认在上方；贴到左/右边界时改对齐方向，贴到顶部时翻到下方，别出图。 */
      const anchor = px < padL + 26 ? 'start' : px > W - padR - 26 ? 'end' : 'middle';
      const labelY = py - r - 5 < 12 ? py + r + 17 : py - r - 5;
      return `<circle class="pv-bubble ${p.cls || ''}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${r.toFixed(1)}"><title>${S(p.title || `${p.label || ''} · ${fmtX(p.x)} / ${fmtY(p.y)}`)}</title></circle>
        <text class="pv-bubble-label ${p.cls || ''}" x="${px.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="${anchor}">${S(p.label || '')}</text>`;
    }).join('');
    const axisNames = `${xLabel ? `<text class="pv-axis is-name" x="${(padL + W - padR) / 2}" y="${H - 6}" text-anchor="middle">${S(xLabel)}</text>` : ''}
      ${yLabel ? `<text class="pv-axis is-name" transform="translate(18,${((padT + H - padB) / 2).toFixed(1)}) rotate(-90)" text-anchor="middle">${S(yLabel)}</text>` : ''}`;
    return svg(W, H, `${quad}${grid}${refs}${bubbles}${axisNames}`, aria);
  }

  /* ── 分位雷达（复用选手档案页的 pl-radar-* 样式，两个页面读数一致）── */
  function radar(opt) {
    const {axes = [], series = [], size = 460, aria = '分位雷达'} = opt;
    if (!axes.length) return empty('没有可画的指标轴。');
    const cx = size / 2, cy = size / 2 + 4, R = size / 2 - 68;
    const n = axes.length;
    const point = (i, r) => {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / n;
      return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
    };
    const ring = (k) => `<polygon class="pl-radar-ring${Math.abs(k - 0.5) < 1e-6 ? ' is-mid' : ''}" points="${axes.map((_, i) => point(i, R * k).map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = axes.map((_, i) => {
      const [x, y] = point(i, R);
      return `<line class="pl-radar-spoke" x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
    }).join('');
    const labels = axes.map((axis, i) => {
      const [x, y] = point(i, R + 32);
      return `<text class="pl-radar-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${S(axis.label)}</text>`;
    }).join('');
    const midTick = `<text class="pl-radar-tick" x="${cx + 7}" y="${(cy - R * 0.5 + 4).toFixed(1)}">50</text>`;
    const shape = (values, cls) => `<polygon class="pl-radar-area ${cls}" points="${values.map((v, i) => {
      const [x, y] = point(i, R * clamp(isNum(v) ? v : 0, 0, 100) / 100);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ')}"/>`;
    const vertex = (values, cls, name) => values.map((v, i) => {
      const [x, y] = point(i, R * clamp(isNum(v) ? v : 0, 0, 100) / 100);
      return `<circle class="pl-radar-dot ${cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2"><title>${S(`${name} · ${axes[i].label} ${isNum(v) ? fmt(v, 0) : '—'} 分位`)}</title></circle>`;
    }).join('');
    const areas = series.map((s) => shape(s.values, s.cls)).join('');
    const vertices = series.map((s) => vertex(s.values, s.cls, s.name || '')).join('');
    const legend = series.length > 1
      ? `<div class="pl-radar-legend">${series.map((s) => `<span><i class="${s.cls}"></i>${S(s.name || '')}</span>`).join('')}</div>` : '';
    return `<div class="pv-radar">${svg(size, size, `${[0.25, 0.5, 0.75, 1].map(ring).join('')}${spokes}${areas}${vertices}${midTick}${labels}`, aria)}${legend}</div>`;
  }

  /* ── 环形 + 中心数（职业构成 / 胜负构成）────────────────────────── */
  function ring(opt) {
    const {items = [], size = 180, aria = '占比环形图', center = '', top = 8} = opt;
    let list = items.filter((x) => isNum(x.value) && x.value > 0).sort((a, b) => b.value - a.value);
    if (!list.length) return empty('这一组没有可统计的占比。');
    /* 图例一长就没法读：只留前 top 项，剩下的并成「其他」。 */
    if (list.length > top) {
      const rest = list.slice(top - 1);
      list = list.slice(0, top - 1).concat([{
        label: `其他 ${rest.length} 项`, value: rest.reduce((a, b) => a + b.value, 0), cls: 'is-quiet',
      }]);
    }
    const total = list.reduce((a, b) => a + b.value, 0);
    const R = size / 2 - 10, r = R * 0.64, cx = size / 2, cy = size / 2;
    let acc = 0;
    const segs = list.map((x, i) => {
      const frac = x.value / total;
      const circ = 2 * Math.PI * ((R + r) / 2);
      const dash = frac * circ, gap = circ - dash;
      const off = -acc * circ;
      acc += frac;
      return `<circle class="pv-ring-seg ${x.cls || catCls(i)}" cx="${cx}" cy="${cy}" r="${(R + r) / 2}" fill="none" stroke-width="${R - r}" stroke-dasharray="${dash.toFixed(2)} ${gap.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"><title>${S(`${x.label} · ${N(x.value, 0)}（${fmt(x.value / total * 100, 1)}%）`)}</title></circle>`;
    }).join('');
    const centerHtml = center && isNum(center.value)
      ? `<text class="pv-ring-center-val" x="${cx}" y="${cy + 2}">${S(center.text || N(center.value, 0))}</text>
         <text class="pv-ring-center-label" x="${cx}" y="${cy + 20}">${S(center.label || '')}</text>` : '';
    return `<div class="pv-ring-wrap">${svg(size, size, segs + centerHtml, aria)}
      <div class="pv-ring-legend">${list.map((x, i) => `<span><i class="${x.cls || catCls(i)}"></i>${S(x.label)}<b>${S(x.text ?? fmt(x.value / total * 100, 1) + '%')}</b></span>`).join('')}</div></div>`;
  }

  /* ── 小环形仪表：单指标分位，塞进指标砖里 ────────────────────────── */
  function gauge(opt) {
    const {value, label = '', sub = '', size = 86, aria = ''} = opt;
    const v = clamp(isNum(value) ? value : 0, 0, 100);
    const R = size / 2 - 7, cx = size / 2, cy = size / 2, circ = 2 * Math.PI * R;
    const cls = v >= 60 ? 'is-up' : v <= 40 ? 'is-down' : '';
    return `<div class="pv-gauge" role="img" aria-label="${S(aria || `${label} ${fmt(v, 0)} 分位`)}">
      ${svg(size, size, `<circle class="pv-gauge-track" cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke-width="7"/>
        <circle class="pv-gauge-arc ${cls}" cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke-width="7"
          stroke-linecap="round" stroke-dasharray="${(v / 100 * circ).toFixed(2)} ${circ.toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"/>
        <line class="pv-gauge-mid" x1="${cx}" y1="${(cy - R - 5).toFixed(1)}" x2="${cx}" y2="${(cy - R + 5).toFixed(1)}"/>
        <text class="pv-gauge-val" x="${cx}" y="${cy + 5}" text-anchor="middle">${isNum(value) ? fmt(v, 0) : '—'}</text>`, `${label} 分位仪表`)}
      <span class="pv-gauge-label">${S(label)}</span>${sub ? `<small>${S(sub)}</small>` : ''}</div>`;
  }


  /* ── 下拉筛选框 ──────────────────────────────────────────────────
     用原生 <select> + <optgroup>：键盘可操作、选项多了自动滚动、
     中文由系统渲染（不会像 SVG 文本那样发虚）。所有卡片的筛选都走它。 */
  function pvSelect(opt) {
    const {name = '', label = '', value = '', options = [], groups = null, allLabel = null, aria = ''} = opt;
    const sel = (v) => (String(value ?? '') === String(v) ? ' selected' : '');
    const optHtml = ([v, text]) => `<option value="${S(v)}"${sel(v)}>${S(text)}</option>`;
    const body = groups
      ? groups.filter((g) => g.items.length).map((g) => `<optgroup label="${S(g.label)}">${g.items.map(optHtml).join('')}</optgroup>`).join('')
      : options.map(optHtml).join('');
    return `<label class="pv-sel">
      <span class="pv-sel-label">${S(label)}</span>
      <span class="pv-sel-box">
        <select data-pdx-select="${S(name)}" aria-label="${S(aria || label || name)}">
          ${allLabel ? `<option value=""${sel('')}>${S(allLabel)}</option>` : ''}
          ${body}
        </select>
        <i class="pv-sel-caret" aria-hidden="true"></i>
      </span>
    </label>`;
  }
  const selBar = (list) => `<div class="pv-selbar">${list.filter(Boolean).join('')}</div>`;

  /* ── 筛选条 ─────────────────────────────────────────────────────── */
  function filterChips(opt) {
    const {name = '', label = '', options = [], value = '', toggle = false, aria = ''} = opt;
    const picked = String(value ?? '').split(',').filter(Boolean);
    const isOn = (key) => (toggle ? picked.includes(String(key)) : String(value ?? '') === String(key));
    return `<div class="pv-filter" role="group" aria-label="${S(aria || label || name)}">
      ${label ? `<span class="pv-filter-label">${S(label)}</span>` : ''}
      ${options.map(([key, text]) => `<button type="button" aria-pressed="${isOn(key) ? 'true' : 'false'}"
        class="${isOn(key) ? 'is-on' : ''}" ${toggle
          ? `data-pdx-toggle="${S(name)}:${S(key)}"`
          : `data-pdx-set="${S(name)}:${S(key)}"`}>${S(text)}</button>`).join('')}
    </div>`;
  }
  const filters = (groups) => `<div class="pv-filters">${groups.filter(Boolean).join('')}</div>`;
  const legend = (items) => `<div class="pv-legend">${items.map(([cls, text, dot]) =>
    `<span><i class="${cls}${dot === false ? '' : ' is-dot'}"></i>${S(text)}</span>`).join('')}</div>`;

  return {FULL, S, N, isNum, clamp, signed, svg, empty, panel, grid, line, columns, treemap, heat,
    boxplot, scatter, radar, ring, gauge, filterChips, filters, pvSelect, selBar, legend, laneCls, catCls,
    niceTicks, LANE_CLS, w, gridWidth};
}
