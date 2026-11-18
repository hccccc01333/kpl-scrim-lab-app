/* BP 工作台图表层（2026-11）
 *
 * 教练明确否掉了“细长横条”这种占地方又没有信息量的画法。这里只做
 * 真正用满版面的图：英雄气泡散点、区间点图、哑铃对比、Ban 位热力图、
 * 体系雷达、窗口斜率图。全部是原生 SVG 字符串，无第三方依赖，
 * 颜色跟随全站青瓷 token，暗色主题自动适配。
 *
 * 所有图只负责“画”，口径与数字由 bp_studio.py 提供；样本不足时
 * 图会退化为点/空态，不补值。
 */

export function createBpViz({esc, portrait, short = (value) => String(value ?? '')}) {
  const LANE_COLOR = {
    对抗路: '#a9663f', 打野: '#2f7a5f', 中路: '#4a6fa8',
    发育路: '#a8842f', 游走: '#7357a6', 未记录: '#6f7d76',
  };
  const PALETTE = ['#246b63', '#a8842f', '#a9663f', '#4a6fa8', '#7357a6', '#2f7a5f'];

  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const has = (n) => typeof n === 'number' && Number.isFinite(n);
  const escId = (text) => String(text || '').replace(/[^A-Za-z0-9_-]/g, '');
  const niceStep = (range, count = 4) => {
    const raw = Math.max(0.0001, range / Math.max(1, count));
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / pow;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
    return step * pow;
  };
  const fmt1 = (n) => has(n) ? (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, '') : '—';

  function wrap(width, height, body, cls = '') {
    return `<svg class="bv ${cls}" viewBox="0 0 ${width} ${height}" role="img"
      preserveAspectRatio="xMidYMid meet">${body}</svg>`;
  }

  /* 圆形英雄头像：SVG image + clipPath，比纯色点更好认。 */
  function marker(hero, cx, cy, radius, uid, ring = '') {
    const id = `bvc-${escId(uid)}`;
    return `<defs><clipPath id="${id}"><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${radius.toFixed(1)}"/></clipPath></defs>
      <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(radius + 1.6).toFixed(1)}"
        fill="#fff" stroke="${ring || 'rgba(20,54,48,.18)'}" stroke-width="1"/>
      <image href="" x="${(cx - radius).toFixed(1)}" y="${(cy - radius).toFixed(1)}"
        width="${(radius * 2).toFixed(1)}" height="${(radius * 2).toFixed(1)}"
        clip-path="url(#${id})" preserveAspectRatio="xMidYMid slice" data-bv-hero="${esc(hero)}"/>`;
  }

  /* 用 HTML 的 portrait() 取图标地址，再回填到 SVG image 上。 */
  function markerWithIcon(hero, cx, cy, radius, uid, ring) {
    const html = portrait(hero, 'bv-src');
    const match = /src="([^"]+)"/.exec(html);
    if (!match) {
      return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${radius.toFixed(1)}"
        fill="${LANE_COLOR.未记录}"/><text x="${cx.toFixed(1)}" y="${(cy + 3).toFixed(1)}"
        text-anchor="middle" class="bv-initial">${esc((hero || '?')[0])}</text>`;
    }
    const url = match[1].replace(/&amp;/g, '&');
    const id = `bvc-${escId(uid)}`;
    return `<defs><clipPath id="${id}"><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${radius.toFixed(1)}"/></clipPath></defs>
      <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(radius + 1.4).toFixed(1)}"
        fill="#fff" stroke="${ring || 'rgba(20,54,48,.16)'}" stroke-width="1"/>
      <image href="${url}" x="${(cx - radius).toFixed(1)}" y="${(cy - radius).toFixed(1)}"
        width="${(radius * 2).toFixed(1)}" height="${(radius * 2).toFixed(1)}"
        clip-path="url(#${id})" preserveAspectRatio="xMidYMid slice"/>
      <title>${esc(hero)}</title>`;
  }

  function axisText(x, y, text, cls = 'bv-label', anchor = 'middle') {
    return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" class="${cls}" text-anchor="${anchor}">${esc(text)}</text>`;
  }

  /* ── 气泡散点：英雄优先级 ───────────────────────────────────────────
     x = Ban 率，y = 胜率，半径 = Pick 次数，颜色 = 分路。中位数十字把
     版面分成四个象限：右上“非 Ban 必选”、右下“被 Ban 但胜率不高”…
     比一排进度条更能看出该先拿谁。 */
  function heroScatter(rows, {width = 1100, height = 440, onlyLane = '',
    xKey = 'banRate', yKey = 'winRate', sizeKey = 'picks', minDecided = 8, minY = 30} = {}) {
    const points = (rows || []).filter((row) => has(row[xKey]) && has(row[yKey])
      && (row.decided || 0) >= minDecided && row[yKey] >= minY
      && (!onlyLane || row.lane === onlyLane));
    if (points.length < 3) {
      return `<div class="bv-empty">样本不足，散点图暂不绘制（至少 3 个英雄有 4 局以上胜负）。</div>`;
    }
    const pad = {left: 58, right: 26, top: 30, bottom: 46};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const rawMax = Math.max(...points.map((p) => p[xKey] || 0));
    const xStep = niceStep(Math.max(4, rawMax), 4);
    const xMax = Math.max(xStep, Math.ceil(rawMax / xStep) * xStep);
    const ys = points.map((p) => p[yKey]);
    const yStep = niceStep(Math.max(4, Math.max(...ys) - Math.min(...ys) + 4), 4);
    const yMin = Math.max(25, Math.floor((Math.min(...ys) - 1) / yStep) * yStep);
    const yMax = Math.min(100, Math.ceil((Math.max(...ys) + 1) / yStep) * yStep);
    const x = (v) => pad.left + clamp(v, 0, xMax) / xMax * plotW;
    const y = (v) => pad.top + (1 - (clamp(v, yMin, yMax) - yMin) / Math.max(1, yMax - yMin)) * plotH;
    const maxPick = Math.max(...points.map((p) => p[sizeKey] || 1));
    const radius = (p) => 5 + Math.sqrt((p[sizeKey] || 1) / maxPick) * 14;
    const midX = [...points].sort((a, b) => (a[xKey] || 0) - (b[xKey] || 0))[Math.floor(points.length / 2)]?.[xKey] || 0;
    const sorted = [...points].sort((a, b) => (a[sizeKey] || 0) - (b[sizeKey] || 0));
    const grid = [];
    for (let value = 0; value <= xMax + 0.001; value += xStep) {
      const gx = x(value);
      grid.push(`<line x1="${gx.toFixed(1)}" y1="${pad.top}" x2="${gx.toFixed(1)}" y2="${pad.top + plotH}" class="bv-grid"/>`);
      grid.push(axisText(gx, height - 20, `${fmt1(value)}%`, 'bv-tick'));
    }
    for (let value = yMin; value <= yMax + 0.001; value += yStep) {
      const gy = y(value);
      grid.push(`<line x1="${pad.left}" y1="${gy.toFixed(1)}" x2="${pad.left + plotW}" y2="${gy.toFixed(1)}" class="bv-grid"/>`);
      grid.push(axisText(pad.left - 10, gy + 3.5, `${fmt1(value)}%`, 'bv-tick', 'end'));
    }
    const quad = `
      <line x1="${x(midX).toFixed(1)}" y1="${pad.top}" x2="${x(midX).toFixed(1)}" y2="${pad.top + plotH}" class="bv-quad"/>
      <line x1="${pad.left}" y1="${y(50).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(50).toFixed(1)}" class="bv-quad"/>`;
    const dots = sorted.map((p, index) => {
      const r = radius(p);
      const color = LANE_COLOR[p.lane] || LANE_COLOR.未记录;
      return `<g class="bv-marker" data-bps-hero-card="${esc(p.hero)}" style="cursor:pointer">
        ${markerWithIcon(p.hero, x(p[xKey]), y(p[yKey]), r, `hero-${index}`, color)}
        <title>${esc(p.hero)} · ${xKey === 'banRate' ? 'Ban' : 'Pick'} ${fmt1(p[xKey])}% · 胜率 ${fmt1(p[yKey])}% · ${p[sizeKey] || 0} 次</title>
      </g>`;
    }).join('');
    /* 标签：先登记所有气泡的占地，再给优先级最高的 12 个找空位，避免压在别的英雄上。 */
    const boxes = [];
    for (const p of points) {
      const r = radius(p) + 3;
      const px = x(p[xKey]);
      const py = y(p[yKey]);
      boxes.push({x0: px - r, x1: px + r, y0: py - r, y1: py + r});
    }
    const labelOf = (p) => {
      const px = x(p[xKey]);
      const py = y(p[yKey]);
      const r = radius(p) + 5;
      const nameW = String(p.hero).length * 13 + 6;
      const options = [
        {tx: px, ty: py - r - 7, anchor: 'middle', x0: px - nameW / 2, x1: px + nameW / 2, y0: py - r - 17, y1: py - r - 5},
        {tx: px + r + 3, ty: py + 4, anchor: 'start', x0: px + r, x1: px + r + nameW, y0: py - 8, y1: py + 5},
        {tx: px - r - 3, ty: py + 4, anchor: 'end', x0: px - r - nameW, x1: px - r, y0: py - 8, y1: py + 5},
        {tx: px, ty: py + r + 15, anchor: 'middle', x0: px - nameW / 2, x1: px + nameW / 2, y0: py + r + 5, y1: py + r + 17},
      ];
      for (const option of options) {
        if (option.x0 < 2 || option.x1 > width - 2) continue;
        const hit = boxes.some((box) => !(option.x1 < box.x0 || option.x0 > box.x1
          || option.y1 < box.y0 || option.y0 > box.y1));
        if (hit) continue;
        boxes.push(option);
        return axisText(option.tx, option.ty, short(p.hero), 'bv-hero-label', option.anchor);
      }
      return '';
    };
    const labels = [...points].sort((a, b) => (b.priority || 0) - (a.priority || 0))
      .slice(0, 12).map(labelOf).join('');
    return wrap(width, height, `<g class="bv-zoom-inner">${grid}${quad}${dots}${labels}</g>
      ${axisText(pad.left - 12, 16, '胜率 ↑', 'bv-axis-title', 'start')}
      ${axisText(pad.left + plotW, height - 3, `${xKey === 'banRate' ? 'Ban 率' : 'Pick 率'} →`, 'bv-axis-title', 'end')}`,
      'bv-scatter');
  }

  /* ── 通用气泡：组合 / 对手英雄的“使用 × 收益”象限 ────────────────── */
  function dotScatter(points, {width = 760, height = 320, xKey = 'share', yKey = 'relative',
    sizeKey = 'games', labelKey = 'label', xLabel = '使用率', yLabel = '相对基准',
    xMax = null, yMin = -20, yMax = 20, labelTop = 8, midY = 0} = {}) {
    const list = (points || []).filter((row) => has(row[xKey]) && has(row[yKey]));
    if (list.length < 3) return '<div class="bv-empty">样本不足，象限图暂不绘制。</div>';
    const pad = {left: 48, right: 20, top: 20, bottom: 38};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const maxX = xMax || Math.max(2, Math.ceil(Math.max(...list.map((row) => row[xKey])) / 2) * 2);
    const lowY = Math.min(yMin, Math.floor(Math.min(...list.map((row) => row[yKey])) / 5) * 5);
    const highY = Math.max(yMax, Math.ceil(Math.max(...list.map((row) => row[yKey])) / 5) * 5);
    const x = (v) => pad.left + clamp(v, 0, maxX) / maxX * plotW;
    const y = (v) => pad.top + (1 - (clamp(v, lowY, highY) - lowY) / Math.max(1, highY - lowY)) * plotH;
    const maxSize = Math.max(1, ...list.map((row) => row[sizeKey] || 1));
    const grid = [];
    for (let i = 0; i <= 4; i += 1) {
      const gx = pad.left + (plotW * i) / 4;
      grid.push(`<line x1="${gx}" y1="${pad.top}" x2="${gx}" y2="${pad.top + plotH}" class="bv-grid"/>`);
      grid.push(axisText(gx, height - 16, `${fmt1((maxX * i) / 4)}%`, 'bv-tick'));
    }
    for (let i = 0; i <= 4; i += 1) {
      const gy = pad.top + (plotH * i) / 4;
      grid.push(`<line x1="${pad.left}" y1="${gy}" x2="${pad.left + plotW}" y2="${gy}" class="bv-grid"/>`);
      grid.push(axisText(pad.left - 8, gy + 3.5, `${fmt1(highY - ((highY - lowY) * i) / 4)}`, 'bv-tick', 'end'));
    }
    const dots = [...list].sort((a, b) => (a[sizeKey] || 0) - (b[sizeKey] || 0)).map((row, index) => {
      const r = 4 + Math.sqrt((row[sizeKey] || 1) / maxSize) * 11;
      const tone = row[yKey] >= 0 ? 'is-good' : 'is-bad';
      return `<g><circle cx="${x(row[xKey]).toFixed(1)}" cy="${y(row[yKey]).toFixed(1)}" r="${r.toFixed(1)}"
        class="bv-bubble ${tone}"/>
        <title>${esc(row[labelKey])} · ${xLabel} ${fmt1(row[xKey])}% · ${yLabel} ${fmt1(row[yKey])}pp · ${row[sizeKey] || 0} 局</title></g>`;
    }).join('');
    const placed = list.map((row) => {
      const radius = 4 + Math.sqrt((row[sizeKey] || 1) / maxSize) * 11 + 2;
      return {x0: x(row[xKey]) - radius, x1: x(row[xKey]) + radius,
        y0: y(row[yKey]) - radius, y1: y(row[yKey]) + radius};
    });
    const labels = [...list].sort((a, b) => (b[sizeKey] || 0) - (a[sizeKey] || 0)).slice(0, labelTop)
      .map((row) => {
        const px = x(row[xKey]);
        const py = y(row[yKey]);
        const radius = 4 + Math.sqrt((row[sizeKey] || 1) / maxSize) * 11;
        const name = short(String(row[labelKey])).replace(' + ', '·');
        const boxW = name.length * 11 + 8;
        const option = {tx: px, ty: py - radius - 6, anchor: 'middle',
          x0: px - boxW / 2, x1: px + boxW / 2, y0: py - radius - 16, y1: py - radius - 4};
        if (option.x0 < 2 || option.x1 > width - 2) return '';
        if (placed.some((box) => !(option.x1 < box.x0 || option.x0 > box.x1
          || option.y1 < box.y0 || option.y0 > box.y1))) return '';
        placed.push(option);
        return axisText(option.tx, option.ty, name, 'bv-hero-label', option.anchor);
      }).join('');
    return wrap(width, height, `${grid}
      <line x1="${pad.left}" y1="${y(midY).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(midY).toFixed(1)}" class="bv-quad"/>
      <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotH}" class="bv-axis"/>
      ${dots}${labels}
      ${axisText(pad.left + plotW / 2, height - 2, `${xLabel} →`, 'bv-axis-title')}
      ${axisText(pad.left, pad.top - 8, `${yLabel} ↑`, 'bv-axis-title', 'start')}`);
  }


  /* ── 区间点图：胜率 + Wilson 区间，替代横条 ───────────────────────── */
  function dotCI(rows, {labelKey = 'label', valueKey = 'winRate', lowKey = 'interval',
    max = 100, width = 720, rowHeight = 34, suffix = '%', leftWidth = 118} = {}) {
    const list = (rows || []).filter((row) => has(row[valueKey]));
    if (!list.length) return '<div class="bv-empty">暂无可用样本。</div>';
    const height = list.length * rowHeight + 26;
    const left = leftWidth;
    const right = width - 54;
    const x = (value) => left + clamp(value, 0, max) / max * (right - left);
    const ticks = [0, 25, 50, 75, 100].map((value) => `
      <line x1="${x(value)}" y1="14" x2="${x(value)}" y2="${height - 16}" class="bv-grid"/>
      ${axisText(x(value), height - 3, `${value}%`, 'bv-tick')}`).join('');
    const rowsHtml = list.map((row, index) => {
      const cy = 24 + index * rowHeight;
      const low = Array.isArray(row[lowKey]) ? row[lowKey][0] : null;
      const high = Array.isArray(row[lowKey]) ? row[lowKey][1] : null;
      const sample = row.decided ?? row.games ?? 0;
      const dot = x(row[valueKey]);
      const tone = row[valueKey] >= 55 ? 'is-good' : row[valueKey] <= 45 ? 'is-bad' : '';
      /* 区间宽于 55pp 说明样本太少，画出来只是噪声，只留点。 */
      const showCI = sample >= 6 && low != null && high != null && (high - low) <= 55;
      return `<g>
        ${showCI ? `<line x1="${x(low)}" y1="${cy}" x2="${x(high)}" y2="${cy}" class="bv-ci"/>
          <line x1="${x(low)}" y1="${cy - 4}" x2="${x(low)}" y2="${cy + 4}" class="bv-ci-cap"/>
          <line x1="${x(high)}" y1="${cy - 4}" x2="${x(high)}" y2="${cy + 4}" class="bv-ci-cap"/>` : ''}
        <circle cx="${dot}" cy="${cy}" r="5.5" class="bv-dot ${tone}"/>
        ${axisText(left - 12, cy + 4, row[labelKey], 'bv-row-label', 'end')}
        ${axisText(dot + 12, cy + 4, `${fmt1(row[valueKey])}${suffix}`, 'bv-value', 'start')}
      </g>`;
    }).join('');
    return wrap(width, height, `${ticks}${rowsHtml}`);
  }

  /* ── 哑铃对比：KPL 份额 vs 本队份额 ───────────────────────────────── */
  function dumbbell(rows, {aKey = 'kplShare', bKey = 'ownShare', labelKey = 'hero',
    width = 760, rowHeight = 36, aLabel = 'KPL', bLabel = '本队', leftWidth = 104} = {}) {
    const list = (rows || []).filter((row) => has(row[aKey]) || has(row[bKey])).slice(0, 10);
    if (!list.length) return '<div class="bv-empty">两边都还没有可比较的应对。</div>';
    const height = list.length * rowHeight + 40;
    const left = leftWidth;
    const right = width - 24;
    const max = Math.max(10, Math.ceil(Math.max(...list.map((row) => Math.max(row[aKey] || 0, row[bKey] || 0))) / 10) * 10);
    const x = (value) => left + clamp(value, 0, max) / max * (right - left);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => `
      <line x1="${x(max * ratio)}" y1="26" x2="${x(max * ratio)}" y2="${height - 18}" class="bv-grid"/>
      ${axisText(x(max * ratio), height - 4, `${fmt1(max * ratio)}%`, 'bv-tick')}`).join('');
    const body = list.map((row, index) => {
      const cy = 38 + index * rowHeight;
      const a = has(row[aKey]) ? x(row[aKey]) : null;
      const b = has(row[bKey]) ? x(row[bKey]) : null;
      return `<g>
        ${a != null && b != null ? `<line x1="${a}" y1="${cy}" x2="${b}" y2="${cy}" class="bv-link"/>` : ''}
        ${a != null ? `<circle cx="${a}" cy="${cy}" r="4.5" class="bv-dot is-hollow"/>` : ''}
        ${b != null ? `<circle cx="${b}" cy="${cy}" r="6" class="bv-dot is-own"/>` : ''}
        ${axisText(left - 10, cy + 4, short(row[labelKey]), 'bv-row-label', 'end')}
        ${a == null ? axisText(x(0) + 8, cy + 4, '未用过', 'bv-muted', 'start') : ''}
      </g>`;
    }).join('');
    const legend = `<g transform="translate(${left},18)">
      <circle cx="0" cy="-4" r="4.5" class="bv-dot is-hollow"/><text x="8" y="0" class="bv-tick">${esc(aLabel)} 常用份额</text>
      <circle cx="128" cy="-4" r="6" class="bv-dot is-own"/><text x="138" y="0" class="bv-tick">${esc(bLabel)} 份额</text>
    </g>`;
    return wrap(width, height, `${ticks}${legend}${body}`);
  }

  /* ── 热力图：对手第 N 手 Ban 谁 ───────────────────────────────────── */
  function handHeatmap(hands, {width = 900, leftWidth = 92, colWidth = 198,
    rowHeight = 40, colors = null} = {}) {
    const list = (hands || []).filter((hand) => (hand.heroes || []).length);
    if (!list.length) return '<div class="bv-empty">没有逐手 Ban 记录。</div>';
    const maxCount = Math.max(1, ...list.flatMap((hand) => (hand.heroes || []).map((row) => row.count || 0)));
    const rowsCount = Math.max(...list.map((hand) => (hand.heroes || []).length));
    const height = rowsCount * rowHeight + 46;
    const head = list.map((hand, col) => {
      const cx = leftWidth + col * colWidth;
      return `<g><text x="${cx + 12}" y="20" class="bv-col-title">第 ${hand.hand || col + 1} 手</text>
        <text x="${cx + 12}" y="35" class="bv-tick">${hand.games || 0} 局</text></g>`;
    }).join('');
    const cells = [];
    list.forEach((hand, col) => {
      (hand.heroes || []).forEach((row, index) => {
        const count = row.count || 0;
        const intensity = count / maxCount;
        const cx = leftWidth + col * colWidth;
        const cy = 44 + index * rowHeight;
        const color = (colors && colors[col]) || '#246b63';
        const mid = cy + (rowHeight - 5) / 2;
        cells.push(`<rect x="${cx}" y="${cy}" width="${colWidth - 8}" height="${rowHeight - 5}" rx="8"
          fill="${color}" opacity="${(0.1 + intensity * 0.5).toFixed(2)}"/>
          ${markerWithIcon(row.hero, cx + 17, mid, 12, `heat-${col}-${index}`)}
          <text x="${cx + 34}" y="${mid + 4}" class="bv-cell-label">${esc(short(row.hero))}</text>
          <text x="${cx + colWidth - 14}" y="${mid + 4}" class="bv-cell-count" text-anchor="end">${count}</text>`);
      });
    });
    return wrap(width, height, `${head}${cells.join('')}`);
  }

  /* ── 体系雷达：本队 vs 对手 ───────────────────────────────────────── */
  function radar(rows, {width = 420, height = 420, aKey = 'ownShare', bKey = 'enemyShare',
    labelKey = 'system', aLabel = '本队', bLabel = '对手'} = {}) {
    const list = (rows || []).filter((row) => has(row[aKey]) || has(row[bKey])).slice(0, 8);
    if (list.length < 3) return '<div class="bv-empty">体系样本不足 3 项，雷达暂不绘制。</div>';
    const cx = width / 2;
    const cy = height / 2 + 4;
    const radius = Math.min(width, height) / 2 - 62;
    const max = Math.max(10, ...list.map((row) => Math.max(row[aKey] || 0, row[bKey] || 0)));
    const angle = (index) => (Math.PI * 2 * index) / list.length - Math.PI / 2;
    const point = (index, value) => [cx + Math.cos(angle(index)) * radius * (value / max),
      cy + Math.sin(angle(index)) * radius * (value / max)];
    const rings = [0.25, 0.5, 0.75, 1].map((ratio) => {
      const pts = list.map((_, index) => point(index, max * ratio).map((n) => n.toFixed(1)).join(',')).join(' ');
      return `<polygon points="${pts}" class="bv-ring"/>`;
    }).join('');
    const spokes = list.map((row, index) => {
      const [px, py] = point(index, max);
      const [lx, ly] = point(index, max * 1.18);
      return `<line x1="${cx}" y1="${cy}" x2="${px.toFixed(1)}" y2="${py.toFixed(1)}" class="bv-spoke"/>
        <text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="bv-radar-label"
          text-anchor="${Math.abs(lx - cx) < 20 ? 'middle' : lx > cx ? 'start' : 'end'}">${esc(row[labelKey])}</text>`;
    }).join('');
    const polygon = (key, cls) => {
      const pts = list.map((row, index) => point(index, row[key] || 0).map((n) => n.toFixed(1)).join(',')).join(' ');
      return `<polygon points="${pts}" class="${cls}"/>`;
    };
    const dotsA = list.map((row, index) => `<circle cx="${point(index, row[aKey] || 0)[0].toFixed(1)}"
      cy="${point(index, row[aKey] || 0)[1].toFixed(1)}" r="3.2" class="bv-radar-dot is-a"/>`).join('');
    const dotsB = list.map((row, index) => `<circle cx="${point(index, row[bKey] || 0)[0].toFixed(1)}"
      cy="${point(index, row[bKey] || 0)[1].toFixed(1)}" r="3.2" class="bv-radar-dot is-b"/>`).join('');
    const legend = `<g transform="translate(${cx - 70}, ${height - 10})">
      <circle cx="0" cy="-4" r="4" class="bv-radar-dot is-a"/><text x="9" y="0" class="bv-tick">${esc(aLabel)}</text>
      <circle cx="86" cy="-4" r="4" class="bv-radar-dot is-b"/><text x="95" y="0" class="bv-tick">${esc(bLabel)}</text></g>`;
    return wrap(width, height, `${rings}${spokes}${polygon(aKey, 'bv-radar-area is-a')}${polygon(bKey, 'bv-radar-area is-b')}${dotsA}${dotsB}${legend}`);
  }

  /* ── 斜率图：窗口前后变化 ─────────────────────────────────────────── */
  function slope(rows, {width = 720, rowHeight = 30, fromKey = 'previous', toKey = 'current',
    valueKey = 'winRate', labelKey = 'hero', suffix = '%'} = {}) {
    const list = (rows || []).filter((row) => has(row[fromKey]?.[valueKey]) || has(row[toKey]?.[valueKey])).slice(0, 8);
    if (!list.length) return '<div class="bv-empty">没有可比较的窗口变化。</div>';
    const height = list.length * rowHeight + 34;
    const values = list.flatMap((row) => [row[fromKey]?.[valueKey], row[toKey]?.[valueKey]]).filter(has);
    const min = Math.max(0, Math.floor(Math.min(...values) / 5) * 5 - 5);
    const max = Math.min(100, Math.ceil(Math.max(...values) / 5) * 5 + 5);
    const left = 120;
    const x = (value) => left + (clamp(value, min, max) - min) / Math.max(1, max - min) * (width - left - 90);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = min + (max - min) * ratio;
      return `<line x1="${x(value)}" y1="20" x2="${x(value)}" y2="${height - 16}" class="bv-grid"/>
        ${axisText(x(value), height - 3, `${fmt1(value)}%`, 'bv-tick')}`;
    }).join('');
    const body = list.map((row, index) => {
      const cy = 32 + index * rowHeight;
      const from = row[fromKey]?.[valueKey];
      const to = row[toKey]?.[valueKey];
      const up = has(from) && has(to) ? to >= from : false;
      return `<g>
        ${has(from) && has(to) ? `<line x1="${x(from)}" y1="${cy}" x2="${x(to)}" y2="${cy}"
          class="bv-slope ${up ? 'is-up' : 'is-down'}"/>` : ''}
        ${has(from) ? `<circle cx="${x(from)}" cy="${cy}" r="4" class="bv-dot is-hollow"/>` : ''}
        ${has(to) ? `<circle cx="${x(to)}" cy="${cy}" r="5.5" class="bv-dot ${up ? 'is-good' : 'is-bad'}"/>` : ''}
        ${axisText(left - 10, cy + 4, short(row[labelKey]), 'bv-row-label', 'end')}
        ${has(to) ? axisText(x(to) + 10, cy + 4, `${fmt1(to)}${suffix}`, 'bv-value', 'start') : ''}
      </g>`;
    }).join('');
    return wrap(width, height, `${ticks}${body}`);
  }

  /* ── 组合气泡：一对英雄头像并排，按局数放大 ─────────────────────── */
  function comboScatter(points, {width = 760, height = 320, xKey = 'share', yKey = 'relative',
    sizeKey = 'games', labelKey = 'label', labelTop = 6} = {}) {
    const list = (points || []).filter((row) => has(row[xKey]) && has(row[yKey]));
    if (list.length < 3) return '<div class="bv-empty">样本不足，象限图暂不绘制。</div>';
    const pad = {left: 52, right: 24, top: 24, bottom: 42};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xStep = niceStep(Math.max(4, Math.max(...list.map((row) => row[xKey]))), 4);
    const xMax = Math.max(xStep, Math.ceil(Math.max(...list.map((row) => row[xKey])) / xStep) * xStep);
    const lowY = Math.floor((Math.min(...list.map((row) => row[yKey])) - 2) / 5) * 5;
    const highY = Math.ceil((Math.max(...list.map((row) => row[yKey])) + 2) / 5) * 5;
    const x = (v) => pad.left + clamp(v, 0, xMax) / xMax * plotW;
    const y = (v) => pad.top + (1 - (clamp(v, lowY, highY) - lowY) / Math.max(1, highY - lowY)) * plotH;
    const maxSize = Math.max(1, ...list.map((row) => row[sizeKey] || 1));
    const radius = (row) => 6.5 + Math.sqrt((row[sizeKey] || 1) / maxSize) * 7;
    const grid = [];
    for (let value = 0; value <= xMax + 0.001; value += xStep) {
      grid.push(`<line x1="${x(value).toFixed(1)}" y1="${pad.top}" x2="${x(value).toFixed(1)}" y2="${pad.top + plotH}" class="bv-grid"/>`);
      grid.push(axisText(x(value), height - 18, `${fmt1(value)}%`, 'bv-tick'));
    }
    for (let value = lowY; value <= highY + 0.001; value += Math.max(5, (highY - lowY) / 4)) {
      grid.push(`<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>`);
      grid.push(axisText(pad.left - 9, y(value) + 3.5, `${fmt1(value)}`, 'bv-tick', 'end'));
    }
    const zero = `<line x1="${pad.left}" y1="${y(0).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(0).toFixed(1)}" class="bv-quad"/>`;
    const dots = [...list].sort((a, b) => (a[sizeKey] || 0) - (b[sizeKey] || 0)).map((row, index) => {
      const r = radius(row);
      const cx = x(row[xKey]);
      const cy = y(row[yKey]);
      const pair = (row.heroes || []).slice(0, 2);
      const offset = r * 0.46;
      return `<g class="bv-marker" data-bps-combo-row="${esc((row.heroes || []).join(','))}" style="cursor:pointer">
        ${pair.map((hero, slot) => markerWithIcon(hero, cx + (slot === 0 ? -offset : offset), cy,
          r * 0.78, `combo-${index}-${slot}`)).join('')}
        <title>${esc(row[labelKey])} · ${row[sizeKey] || 0} 局 · 使用 ${fmt1(row[xKey])}% · 基准 ${fmt1(row[yKey])}pp</title>
      </g>`;
    }).join('');
    /* 标签：只给前 6 个，并避开已占位置。 */
    const boxes = list.map((row) => {
      const r = radius(row) + 2;
      return {x0: x(row[xKey]) - r, x1: x(row[xKey]) + r, y0: y(row[yKey]) - r, y1: y(row[yKey]) + r};
    });
    const labels = [...list].sort((a, b) => (b[sizeKey] || 0) - (a[sizeKey] || 0)).slice(0, labelTop)
      .map((row) => {
        const cx = x(row[xKey]);
        const cy = y(row[yKey]) + radius(row) + 13;
        const name = short(String(row[labelKey])).replace(' + ', '·');
        const boxW = name.length * 10 + 8;
        const box = {x0: cx - boxW / 2, x1: cx + boxW / 2, y0: cy - 10, y1: cy + 3};
        if (box.x0 < 2 || box.x1 > width - 2) return '';
        if (boxes.some((other) => !(box.x1 < other.x0 || box.x0 > other.x1
          || box.y1 < other.y0 || box.y0 > other.y1))) return '';
        boxes.push(box);
        return axisText(cx, cy, name, 'bv-hero-label');
      }).join('');
    return wrap(width, height, `${grid}${zero}${dots}${labels}
      ${axisText(pad.left - 12, 14, '相对基准 ↑', 'bv-axis-title', 'start')}
      ${axisText(pad.left + plotW, height - 2, '使用率 →', 'bv-axis-title', 'end')}`);
  }

  /* ── 英雄云：头像打包成云，大小 = 出场，外圈颜色 = 胜率 ───────────── */
  function heroCloud(rows, {width = 700, height = 340} = {}) {
    const list = (rows || []).filter((row) => (row.picks || 0) > 0).slice(0, 16);
    if (list.length < 3) return '<div class="bv-empty">样本不足，英雄云暂不绘制。</div>';
    const max = Math.max(...list.map((row) => row.picks || 1));
    const placed = [];
    const cx = width / 2;
    const cy = height / 2;
    const items = [...list].sort((a, b) => (b.picks || 0) - (a.picks || 0)).map((row, order) => {
      const radius = 18 + Math.sqrt((row.picks || 1) / max) * 26;
      let best = null;
      for (let step = 0; step < 900; step += 1) {
        const angle = step * 0.55;
        const dist = 4 * Math.sqrt(step) * 6;
        const x = cx + Math.cos(angle) * dist;
        const y = cy + Math.sin(angle) * dist * 0.62;
        if (x - radius < 8 || x + radius > width - 8 || y - radius < 8 || y + radius > height - 8) continue;
        const hit = placed.some((other) => Math.hypot(other.x - x, other.y - y) < other.r + radius + 5);
        if (hit) continue;
        best = {x, y, r: radius};
        break;
      }
      if (!best) best = {x: cx, y: cy, r: radius};
      placed.push(best);
      const wr = row.winRate;
      const ring = wr == null ? '#8a958e' : wr >= 55 ? '#2f8a76' : wr <= 45 ? '#b3574c' : '#c9a26b';
      return `<g class="bv-cloud-item">
        <circle cx="${best.x.toFixed(1)}" cy="${best.y.toFixed(1)}" r="${(best.r + 2).toFixed(1)}"
          fill="#fff" stroke="${ring}" stroke-width="2"/>
        ${markerWithIcon(row.hero, best.x, best.y, best.r, `cloud-${order}`)}
        <text x="${best.x.toFixed(1)}" y="${(best.y + best.r + 13).toFixed(1)}" text-anchor="middle"
          class="bv-cloud-label">${esc(short(row.hero))}</text>
        <title>${esc(row.hero)} · ${row.picks} 次 Pick · 胜率 ${fmt1(wr)}%</title>
      </g>`;
    }).join('');
    return wrap(width, height, items);
  }

  /* ── 头像象限：x = 场次，y = 对手胜率，四个象限看“打谁有效” ───────── */
  function portraitQuadrant(rows, {width = 700, height = 340, xKey = 'games',
    yKey = 'opponentWinRate', labelKey = 'hero'} = {}) {
    const list = (rows || []).filter((row) => has(row[xKey]) && has(row[yKey]));
    if (list.length < 3) return '<div class="bv-empty">样本不足，象限图暂不绘制。</div>';
    const pad = {left: 46, right: 20, top: 26, bottom: 38};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xStep = niceStep(Math.max(3, Math.max(...list.map((row) => row[xKey]))), 3);
    const xMax = Math.max(xStep, Math.ceil(Math.max(...list.map((row) => row[xKey])) / xStep) * xStep);
    const x = (v) => pad.left + clamp(v, 0, xMax) / xMax * plotW;
    const y = (v) => pad.top + (1 - clamp(v, 0, 100) / 100) * plotH;
    const grid = [];
    for (let value = 0; value <= xMax + 0.001; value += xStep) {
      grid.push(`<line x1="${x(value).toFixed(1)}" y1="${pad.top}" x2="${x(value).toFixed(1)}" y2="${pad.top + plotH}" class="bv-grid"/>`);
      grid.push(axisText(x(value), height - 18, `${Math.round(value)}`, 'bv-tick'));
    }
    for (let i = 0; i <= 4; i += 1) {
      const value = 100 - i * 25;
      grid.push(`<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>`);
      grid.push(axisText(pad.left - 8, y(value) + 3.5, `${value}%`, 'bv-tick', 'end'));
    }
    const boxes = [];
    const labeled = new Set([...list].sort((a, b) => (b[xKey] || 0) - (a[xKey] || 0))
      .slice(0, 6).map((row) => row[labelKey]));
    const dots = list.map((row, index) => {
      const radius = 12 + Math.sqrt((row[xKey] || 1) / xMax) * 9;
      const cx = x(row[xKey]);
      const cy = y(row[yKey]);
      let label = '';
      if (labeled.has(row[labelKey])) {
        const name = short(String(row[labelKey]));
        const half = name.length * 5.6;
        const options = [
          {tx: cx, ty: cy + radius + 12, anchor: 'middle', x0: cx - half, x1: cx + half,
            y0: cy + radius, y1: cy + radius + 13},
          {tx: cx, ty: cy - radius - 5, anchor: 'middle', x0: cx - half, x1: cx + half,
            y0: cy - radius - 15, y1: cy - radius - 2},
          {tx: cx + radius + 3, ty: cy + 3.5, anchor: 'start', x0: cx + radius,
            x1: cx + radius + half * 2, y0: cy - 7, y1: cy + 5},
        ];
        for (const option of options) {
          if (option.x0 < 2 || option.x1 > width - 2) continue;
          if (boxes.some((other) => !(option.x1 < other.x0 || option.x0 > other.x1
            || option.y1 < other.y0 || option.y0 > other.y1))) continue;
          boxes.push({x0: option.x0, x1: option.x1, y0: option.y0, y1: option.y1});
          label = axisText(option.tx, option.ty, name, 'bv-hero-label', option.anchor);
          break;
        }
      }
      return `<g class="bv-marker" style="cursor:pointer">
        ${markerWithIcon(row[labelKey], cx, cy, radius, `quad-${index}`)}${label}
        <title>${esc(row[labelKey])} · ${row[xKey]} 局 · 对手胜率 ${fmt1(row[yKey])}%</title>
      </g>`;
    }).join('');
    return wrap(width, height, `${grid}
      <line x1="${pad.left}" y1="${y(50).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(50).toFixed(1)}" class="bv-quad"/>
      ${dots}
      ${axisText(pad.left - 12, 14, '对手胜率 ↑', 'bv-axis-title', 'start')}
      ${axisText(pad.left + plotW, height - 2, '对局数 →', 'bv-axis-title', 'end')}`);
  }

  /* ── 类型排行：第一手 Ban 的类型，点 + 轨道，可点选联动 ───────────── */
  function typeRank(rows, laneOf, {width = 460, focus = '', attr = 'data-bps-type-focus'} = {}) {
    const list = (rows || []).filter((row) => (row.share || 0) > 0).slice(0, 10);
    if (!list.length) return '<div class="bv-empty">没有第一手 Ban 的类型样本。</div>';
    const height = list.length * 34 + 22;
    const left = 76;
    const right = width - 46;
    const max = Math.max(10, Math.ceil(Math.max(...list.map((row) => row.share || 0)) / 10) * 10);
    const x = (v) => left + (v / max) * (right - left);
    const ticks = [0, 0.5, 1].map((ratio) => {
      const value = max * ratio;
      return `<line x1="${x(value)}" y1="8" x2="${x(value)}" y2="${height - 8}" class="bv-grid"/>
        <text x="${x(value)}" y="${height - 1}" class="bv-tick" text-anchor="middle">${fmt1(value)}%</text>`;
    }).join('');
    const body = list.map((row, index) => {
      const cy = 22 + index * 34;
      const dim = focus && focus !== row.type;
      const lane = laneOf?.(row.type) || '';
      const color = LANE_COLOR[lane] || '#6f7d76';
      return `<g class="bv-rank-row ${dim ? 'is-dim' : ''}" ${attr}="${esc(row.type)}" style="cursor:pointer">
        <rect x="0" y="${cy - 15}" width="${width}" height="30" fill="transparent" class="bv-hit"/>
        <text x="${left - 10}" y="${cy + 4}" text-anchor="end" class="bv-row-label">${esc(row.type)}</text>
        <line x1="${left}" y1="${cy}" x2="${right}" y2="${cy}" class="bv-track"/>
        <circle cx="${x(row.share)}" cy="${cy}" r="${focus === row.type ? 7 : 5}" fill="${color}"/>
        <text x="${x(row.share) + 12}" y="${cy + 4}" class="bv-value">${fmt1(row.share)}%</text>
        <text x="${x(row.share) + 52}" y="${cy + 4}" class="bv-muted">${row.count || 0} 次</text>
        <title>${esc(row.type)} · ${fmt1(row.share)}% · ${row.count || 0} 次</title>
      </g>`;
    }).join('');
    return wrap(width, height, `${ticks}${body}`);
  }

  /* 多条折线：同一个类型在 1–5 手 / 不同月份的份额变化 */
  function typeLines(series, {width = 560, height = 280, xLabels = [], focus = '',
    suffix = '%', attr = 'data-bps-type-focus', maxY = 100} = {}) {
    if (!series?.length || !series[0]?.values?.length) {
      return '<div class="bv-empty">样本不足，趋势暂不绘制。</div>';
    }
    const pad = {left: 42, right: 108, top: 20, bottom: 30};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const count = series[0].values.length;
    const x = (index) => pad.left + (plotW * index) / Math.max(1, count - 1);
    const y = (value) => pad.top + plotH - (clamp(value, 0, maxY) / maxY) * plotH;
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = maxY * ratio;
      return `<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>
        <text x="${pad.left - 8}" y="${(y(value) + 3.4).toFixed(1)}" class="bv-tick" text-anchor="end">${Math.round(value)}</text>`;
    }).join('');
    const ticks = xLabels.map((label, index) => `
      <text x="${x(index)}" y="${height - 10}" class="bv-tick" text-anchor="middle">${esc(label)}</text>`).join('');
    /* 末端标签先按最后一点排序，再拉开最小间距，避免六条线挤成一坨。 */
    const labelSlots = series.map((line) => ({
      label: line.label, color: line.color,
      y: y(line.values[line.values.length - 1]),
    })).sort((a, b) => a.y - b.y);
    const minGap = 18;
    let cursor = pad.top + 4;
    for (const slot of labelSlots) {
      slot.y = Math.max(slot.y, cursor);
      cursor = slot.y + minGap;
    }
    const overflow = (labelSlots[labelSlots.length - 1]?.y || 0) - (height - pad.bottom + 8);
    if (overflow > 0) for (const slot of labelSlots) slot.y -= overflow;
    const labelMap = new Map(labelSlots.map((slot) => [slot.label, slot]));
    const lines = series.map((line) => {
      const dim = focus && focus !== line.label;
      const points = line.values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
      const last = line.values[line.values.length - 1];
      const slot = labelMap.get(line.label) || {y: y(last)};
      return `<g class="bv-line-row ${dim ? 'is-dim' : ''}" ${attr}="${esc(line.label)}" style="cursor:pointer">
        <polyline points="${points}" fill="none" stroke="transparent" stroke-width="14"
          stroke-linejoin="round" stroke-linecap="round" style="pointer-events:stroke"/>
        <polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="${focus === line.label ? 2.8 : 1.8}"
          stroke-linejoin="round" stroke-linecap="round"/>
        ${line.values.map((value, index) => `<circle cx="${x(index).toFixed(1)}" cy="${y(value).toFixed(1)}"
          r="${focus === line.label ? 3.4 : 2.4}" fill="${line.color}"><title>${esc(line.label)} · ${esc(xLabels[index] || '')} ${fmt1(value)}${suffix}</title></circle>`).join('')}
        <line x1="${(width - pad.right + 2).toFixed(1)}" y1="${y(last).toFixed(1)}"
          x2="${(width - pad.right + 10).toFixed(1)}" y2="${slot.y.toFixed(1)}" class="bv-line-lead" stroke="${line.color}"/>
        <text x="${width - 4}" y="${(slot.y + 3.5).toFixed(1)}" text-anchor="end" class="bv-line-label"
          fill="${line.color}">${esc(line.label)}</text>
      </g>`;
    }).join('');
    return wrap(width, height, `${grid}${ticks}${lines}`);
  }

  /* ── 核数点图：横轴核数、纵轴胜率、点大小 = 局数，不用平均数 ──────── */
  function coreDots(rows, {width = 460, height = 260} = {}) {
    const list = (rows || []).filter((row) => row.games > 0);
    if (!list.length) return '<div class="bv-empty">没有完整阵容。</div>';
    const pad = {left: 44, right: 26, top: 26, bottom: 40};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xMin = Math.min(...list.map((row) => row.cores)) - 0.5;
    const xMax = Math.max(...list.map((row) => row.cores)) + 0.5;
    const x = (v) => pad.left + ((v - xMin) / Math.max(1, xMax - xMin)) * plotW;
    const y = (v) => pad.top + (1 - clamp(v, 0, 100) / 100) * plotH;
    const maxGames = Math.max(...list.map((row) => row.games || 1));
    const grid = [0, 25, 50, 75, 100].map((value) => `
      <line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>
      <text x="${pad.left - 8}" y="${(y(value) + 3.4).toFixed(1)}" class="bv-tick" text-anchor="end">${value}</text>`).join('');
    const dots = list.map((row) => {
      const radius = 9 + Math.sqrt((row.games || 1) / maxGames) * 14;
      const cy = y(row.winRate);
      return `<g class="bv-core-item">
        <circle cx="${x(row.cores)}" cy="${cy}" r="${radius}" fill="#246b63" fill-opacity=".16" stroke="#246b63" stroke-width="1.4"/>
        <text x="${x(row.cores)}" y="${cy + 4}" text-anchor="middle" class="bv-core-inner">${fmt1(row.winRate)}%</text>
        <text x="${x(row.cores)}" y="${height - 22}" text-anchor="middle" class="bv-row-label">${row.cores} 核</text>
        <text x="${x(row.cores)}" y="${height - 8}" text-anchor="middle" class="bv-muted">${row.games} 局 · ${fmt1(row.share)}%</text>
        <title>${row.cores} 核 · ${row.games} 局 · 胜率 ${fmt1(row.winRate)}%</title>
      </g>`;
    }).join('');
    return wrap(width, height, `${grid}${dots}
      <text x="${pad.left - 10}" y="14" class="bv-axis-title">胜率 ↑</text>`);
  }

  /* ── 英雄池：Pick 率 × 胜率，头像点，四象限 ───────────────────────── */
  function poolScatter(rows, {width = 760, height = 360, maxHeroes = 12} = {}) {
    const list = (rows || []).filter((row) => (row.picks || 0) > 0 && has(row.winRate))
      .sort((a, b) => (b.picks || 0) - (a.picks || 0)).slice(0, maxHeroes);
    if (list.length < 3) return '<div class="bv-empty">样本不足，英雄池暂不绘制。</div>';
    const pad = {left: 46, right: 22, top: 26, bottom: 40};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xMax = Math.max(10, Math.ceil(Math.max(...list.map((row) => row.pickRate || 0)) / 10) * 10);
    const ys = list.map((row) => row.winRate);
    const yMin = Math.max(20, Math.floor((Math.min(...ys) - 4) / 10) * 10);
    const yMax = Math.min(100, Math.ceil((Math.max(...ys) + 4) / 10) * 10);
    const x = (v) => pad.left + clamp(v, 0, xMax) / xMax * plotW;
    const y = (v) => pad.top + (1 - (clamp(v, yMin, yMax) - yMin) / Math.max(1, yMax - yMin)) * plotH;
    const maxPicks = Math.max(...list.map((row) => row.picks || 1));
    const radius = (row) => 8 + Math.sqrt((row.picks || 1) / maxPicks) * 11;
    const grid = [];
    for (let i = 0; i <= 4; i += 1) {
      const value = (xMax * i) / 4;
      grid.push(`<line x1="${x(value).toFixed(1)}" y1="${pad.top}" x2="${x(value).toFixed(1)}" y2="${pad.top + plotH}" class="bv-grid"/>`);
      grid.push(axisText(x(value), height - 18, `${fmt1(value)}%`, 'bv-tick'));
    }
    for (let value = yMin; value <= yMax; value += (yMax - yMin) / 4) {
      grid.push(`<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>`);
      grid.push(axisText(pad.left - 8, y(value) + 3.5, `${fmt1(value)}%`, 'bv-tick', 'end'));
    }
    const boxes = list.map((row) => {
      const r = radius(row) + 3;
      return {x0: x(row.pickRate) - r, x1: x(row.pickRate) + r,
        y0: y(row.winRate) - r, y1: y(row.winRate) + r};
    });
    const dots = list.map((row, index) => {
      const r = radius(row);
      return `<g class="bv-marker" data-bps-hero-card="${esc(row.hero)}" style="cursor:pointer">
        ${markerWithIcon(row.hero, x(row.pickRate), y(row.winRate), r, `pool-${index}`)}
        <title>${esc(row.hero)} · Pick ${fmt1(row.pickRate)}% · 胜率 ${fmt1(row.winRate)}% · Ban ${fmt1(row.banRate)}%</title>
      </g>`;
    }).join('');
    const labels = [...list].sort((a, b) => (b.picks || 0) - (a.picks || 0)).map((row) => {
      const cx = x(row.pickRate);
      const cy = y(row.winRate);
      const r = radius(row) + 5;
      const name = short(row.hero);
      const half = name.length * 5.6;
      const options = [
        {tx: cx, ty: cy + r + 11, anchor: 'middle', x0: cx - half, x1: cx + half, y0: cy + r, y1: cy + r + 12},
        {tx: cx, ty: cy - r - 4, anchor: 'middle', x0: cx - half, x1: cx + half, y0: cy - r - 14, y1: cy - r - 2},
        {tx: cx + r + 2, ty: cy + 3.5, anchor: 'start', x0: cx + r, x1: cx + r + half * 2, y0: cy - 7, y1: cy + 5},
        {tx: cx - r - 2, ty: cy + 3.5, anchor: 'end', x0: cx - r - half * 2, x1: cx - r, y0: cy - 7, y1: cy + 5},
      ];
      for (const option of options) {
        if (option.x0 < 2 || option.x1 > width - 2) continue;
        if (boxes.some((other) => !(option.x1 < other.x0 || option.x0 > other.x1
          || option.y1 < other.y0 || option.y0 > other.y1))) continue;
        boxes.push({x0: option.x0, x1: option.x1, y0: option.y0, y1: option.y1});
        return axisText(option.tx, option.ty, name, 'bv-hero-label', option.anchor);
      }
      return '';
    }).join('');
    return wrap(width, height, `${grid}
      <line x1="${pad.left}" y1="${y(50).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(50).toFixed(1)}" class="bv-quad"/>
      ${dots}${labels}
      ${axisText(pad.left - 10, 14, '胜率 ↑', 'bv-axis-title', 'start')}
      ${axisText(pad.left + plotW, height - 2, 'Pick 率 →', 'bv-axis-title', 'end')}`);
  }

  /* ── 类型克制矩阵：对面类型 × 我们类型，颜色 = 胜率 ───────────────── */
  function typeCounterMatrix(matrixData, laneOf, {width = 760, cell = 58, leftW = 92, topH = 62} = {}) {
    const rows = matrixData?.rows || [];
    const cols = matrixData?.cols || [];
    if (!rows.length || !cols.length) return '<div class="bv-empty">样本不足，克制矩阵暂不绘制。</div>';
    const height = topH + rows.length * cell + 30;
    const cells = [];
    rows.forEach((enemy, ri) => {
      cols.forEach((own, ci) => {
        const data = matrixData.matrix?.[ri]?.[ci] || {};
        const games = data.games || 0;
        const wr = data.winRate;
        const x = leftW + ci * cell;
        const y = topH + ri * cell;
        if (!games || wr == null) {
          cells.push(`<rect x="${x}" y="${y}" width="${cell - 3}" height="${cell - 3}" rx="8" class="bv-mx-empty"/>`);
          return;
        }
        const reliable = (data.decided || 0) >= 3;
        const color = wr >= 55 ? '#2f8a76' : wr <= 45 ? '#b3574c' : '#c9a26b';
        const opacity = reliable ? 0.12 + Math.min(1, games / 24) * 0.4 : 0.08;
        cells.push(`<g data-r="${ri}" data-c="${ci}"><rect x="${x}" y="${y}" width="${cell - 3}" height="${cell - 3}" rx="8"
          fill="${color}" fill-opacity="${opacity.toFixed(2)}"/>
          <text x="${x + (cell - 3) / 2}" y="${y + (cell - 3) / 2 + 1}" text-anchor="middle" class="bv-mx-value">${reliable ? `${fmt1(wr)}%` : '·'}</text>
          <text x="${x + (cell - 3) / 2}" y="${y + (cell - 3) / 2 + 14}" text-anchor="middle" class="bv-mx-sub">${games} 局</text>
          <title>对面 ${esc(enemy)} × 我们 ${esc(own)} · ${games} 局 · 胜率 ${fmt1(wr)}%</title></g>`);
      });
    });
    const top = cols.map((own, ci) => {
      const cx = leftW + ci * cell + (cell - 3) / 2;
      return `<text x="${cx}" y="${topH - 12}" text-anchor="middle" class="bv-mx-head">${esc(own)}</text>`;
    }).join('');
    const left = rows.map((enemy, ri) => {
      const cy = topH + ri * cell + (cell - 3) / 2;
      return `<text x="${leftW - 10}" y="${cy + 4}" text-anchor="end" class="bv-mx-label">${esc(enemy)}</text>`;
    }).join('');
    return `<svg class="bv bv-matrix" viewBox="0 0 ${width} ${height}" role="img"
      data-left="${leftW}" data-top="${topH}" data-cell="${cell}"
      data-rows="${rows.length}" data-cols="${cols.length}">${top}${left}${cells.join('')}
      <text x="${leftW + cols.length * cell / 2}" y="${topH - 32}" text-anchor="middle" class="bv-col-title">我们出的类型 →</text>
      <text x="${width - 14}" y="${height - 6}" text-anchor="end" class="bv-tick">「·」= 有胜负样本不足 3 局，不参与判断</text>
      <text x="8" y="${topH + rows.length * cell / 2}" class="bv-axis-title"
        transform="rotate(-90 8 ${topH + rows.length * cell / 2})" text-anchor="middle">对面类型 →</text></svg>`;
  }

  /* ── 英雄关系环：克制 / 被克制 / 最佳搭档三向环绕头像 ─────────────── */
  function heroRing(data, {width = 640, height = 360} = {}) {
    if (!data?.available) return `<div class="bv-empty">${esc(data?.reason || '没有关系数据。')}</div>`;
    const cx = width / 2;
    const cy = 158;
    const radius = 96;
    const rad = (angle) => angle * Math.PI / 180;
    const point = (angle, r = radius) => [cx + r * Math.cos(rad(angle)), cy + r * Math.sin(rad(angle))];
    const arc = (a0, a1, color) => {
      const [x0, y0] = point(a0);
      const [x1, y1] = point(a1);
      return `<path d="M${x0.toFixed(1)},${y0.toFixed(1)} A${radius},${radius} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}"
        fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round" opacity=".22"/>`;
    };
    const groups = [
      {title: '克制谁', color: '#246b63', angles: [-160, -120, -80],
        items: data.counters || [], metric: (item) => `+${fmt1(item.excess)}pp`},
      {title: '被谁克制', color: '#a94b40', angles: [-20, 20, 60],
        items: data.counteredBy || [], metric: (item) => `-${fmt1(item.excess)}pp`},
      {title: '最佳搭档', color: '#4a6fa8', angles: [100, 140, 180],
        items: data.partners || [], metric: (item) => `${item.n} 局`},
    ];
    const marks = [];
    let uid = 0;
    for (const group of groups) {
      const used = group.items.slice(0, group.angles.length);
      if (!used.length) continue;
      marks.push(arc(group.angles[0] - 12, group.angles[used.length - 1] + 12, group.color));
      used.forEach((item, index) => {
        const angle = group.angles[index];
        const [x, y] = point(angle);
        const [lx, ly] = point(angle, radius + 30);
        const anchor = Math.cos(rad(angle)) > 0.35 ? 'start'
          : Math.cos(rad(angle)) < -0.35 ? 'end' : 'middle';
        marks.push(`<g>
          ${markerWithIcon(item.hero, x, y, 12, `ring-${uid++}`, group.color)}
          <text x="${lx.toFixed(1)}" y="${(ly - 2).toFixed(1)}" class="bv-ring-hero" text-anchor="${anchor}">${esc(short(item.hero))}</text>
          <text x="${lx.toFixed(1)}" y="${(ly + 11).toFixed(1)}" class="bv-ring-metric" text-anchor="${anchor}" fill="${group.color}">${group.metric(item)}</text>
        </g>`);
      });
    }
    marks.push(`${markerWithIcon(data.hero, cx, cy, 44, 'ring-center', '#0e2f2b')}
      <text x="${cx}" y="${cy + 60}" class="bv-ring-center">${esc(short(data.hero))}</text>`);
    const stats = data.stats || {};
    marks.push(`<g transform="translate(${cx - 150}, ${height - 40})">
      <circle cx="5" cy="-4" r="4" fill="#246b63"/><text x="14" y="0" class="bv-ring-stat">克制谁</text>
      <circle cx="88" cy="-4" r="4" fill="#a94b40"/><text x="97" y="0" class="bv-ring-stat">被谁克制</text>
      <circle cx="182" cy="-4" r="4" fill="#4a6fa8"/><text x="191" y="0" class="bv-ring-stat">最佳搭档</text>
    </g>`);
    marks.push(`<g transform="translate(${cx - 126}, ${height - 16})">
      <text x="0" y="0" class="bv-ring-stat">Pick <tspan class="bv-ring-stat-v">${stats.pickRate == null ? '—' : `${fmt1(stats.pickRate)}%`}</tspan></text>
      <text x="86" y="0" class="bv-ring-stat">Ban <tspan class="bv-ring-stat-v">${stats.banRate == null ? '—' : `${fmt1(stats.banRate)}%`}</tspan></text>
      <text x="166" y="0" class="bv-ring-stat">胜率 <tspan class="bv-ring-stat-v">${stats.winRate == null ? '—' : `${fmt1(stats.winRate)}%`}</tspan></text>
    </g>`);
    return wrap(width, height, marks.join(''));
  }

  /* ── BP 决策树：当前节点 → 前 3 个候选 → 各自前 2 个后续，水平展开 ── */
  function decisionTreeMap(data, pathIds, {width = 780, height = 420, branch = 3} = {}) {
    const nodes = data?.nodes || [];
    if (!data?.available || !nodes.length) {
      return `<div class="bv-empty">${esc(data?.reason || '没有可展开的手序。')}</div>`;
    }
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const children = new Map();
    for (const node of nodes) {
      if (!children.has(node.parent)) children.set(node.parent, []);
      children.get(node.parent).push(node);
    }
    const path = (pathIds || []).map((id) => byId.get(id)).filter(Boolean);
    const current = path.length ? path[path.length - 1] : null;
    const parentKey = current ? current.id : '0';
    const siblings = [...(children.get(parentKey) || [])]
      .sort((a, b) => (b.count - a.count) || String(a.hero).localeCompare(String(b.hero)));
    const total = siblings.reduce((sum, node) => sum + node.count, 0) || 1;
    const first = siblings.slice(0, Math.max(2, branch));
    if (!first.length) return `<div class="bv-empty">这条路径之后没有更长的已核验样本。</div>`;
    height = Math.max(320, 120 + (first.length - 1) * 100);
    const gap = Math.min(110, (height - 120) / Math.max(1, first.length - 1));
    const startY = (height - (first.length - 1) * gap) / 2 - 10;
    first.forEach((node, index) => { node._y = startY + index * gap; });
    const currentY = first.reduce((sum, node) => sum + node._y, 0) / first.length;
    const x0 = 78;
    const x1 = 330;
    const x2 = 600;
    const tone = (node) => {
      if (node.actor === 'team') {
        return node.action === 'ban'
          ? {color: '#a94b40', dash: '5 4'} : {color: '#246b63', dash: ''};
      }
      return node.action === 'ban'
        ? {color: '#a86a2a', dash: '5 4'} : {color: '#4a6fa8', dash: ''};
    };
    const edges = [];
    const marks = [];
    marks.push(`<g>
      <circle cx="${x0}" cy="${currentY.toFixed(1)}" r="9" fill="#0e2f2b" stroke="#fff" stroke-width="2"/>
      ${current ? markerWithIcon(current.hero, x0, currentY, 18, 'dt-current', '#0e2f2b') : ''}
      <text x="${x0}" y="${(currentY - 54).toFixed(1)}" class="bv-tree-hand">${current ? '当前选择' : 'BP 开始'}</text>
      ${current ? `<text x="${x0}" y="${(currentY - 36).toFixed(1)}" class="bv-tree-side" fill="#0e2f2b">${current.level} 手 · ${current.action === 'ban' ? 'BAN' : 'PICK'} · ${current.actor === 'team' ? '我方' : '对方'}</text>` : ''}
      <text x="${x0}" y="${(currentY + 40).toFixed(1)}" class="bv-tree-hero">${current ? esc(short(current.hero)) : '第 1 手'}</text>
    </g>`);
    first.forEach((node, index) => {
      const paint = tone(node);
      const share = node.count / total;
      edges.push(`<path d="M${x0 + 20},${currentY.toFixed(1)} C${(x0 + 120).toFixed(1)},${currentY.toFixed(1)} ${(x1 - 100).toFixed(1)},${node._y.toFixed(1)} ${x1 - 18},${node._y.toFixed(1)}"
        fill="none" stroke="${paint.color}" stroke-width="${(1.2 + 5 * share).toFixed(1)}"
        ${paint.dash ? `stroke-dasharray="${paint.dash}"` : ''} opacity="${(0.35 + 0.55 * share).toFixed(2)}" stroke-linecap="round"/>`);
      marks.push(`<g class="bv-dt-node" data-bps-decision-pick="${esc(node.id)}">
        <title>${esc(node.hero)} · ${node.count} 局 · 胜率 ${node.winRate == null ? '—' : fmt1(node.winRate) + '%'}</title>
        <text x="${x1}" y="${(node._y - 36).toFixed(1)}" class="bv-tree-hand" fill="${paint.color}">${node.level} 手 · ${node.action === 'ban' ? 'BAN' : 'PICK'} · ${node.actor === 'team' ? '我方' : '对方'}</text>
        ${markerWithIcon(node.hero, x1, node._y, 15, `dt-${index}`, paint.color)}
        <text x="${x1}" y="${(node._y + 30).toFixed(1)}" class="bv-tree-hero">${esc(short(node.hero))}</text>
        <text x="${x1}" y="${(node._y + 43).toFixed(1)}" class="bv-tree-count">${node.count} 局 · ${Math.round(share * 100)}%</text>
        <rect x="${x1 - 44}" y="${(node._y + 50).toFixed(1)}" width="88" height="5" rx="2.5" fill="#e3efe9"/>
        <rect x="${x1 - 44}" y="${(node._y + 50).toFixed(1)}" width="${(88 * share).toFixed(1)}" height="5" rx="2.5" fill="#2f8a76"/>
        <text x="${x1}" y="${(node._y + 68).toFixed(1)}" class="bv-tree-count">路径胜率 ${node.winRate == null ? '—' : `${fmt1(node.winRate)}%`}</text>
      </g>`);
      const grand = [...(children.get(node.id) || [])]
        .sort((a, b) => b.count - a.count).slice(0, 2);
      grand.forEach((item, slot) => {
        const cy = node._y + (slot - (grand.length - 1) / 2) * 44;
        const alt = tone(item);
        edges.push(`<path d="M${x1 + 18},${node._y.toFixed(1)} C${(x1 + 70).toFixed(1)},${node._y.toFixed(1)} ${(x2 - 60).toFixed(1)},${cy.toFixed(1)} ${x2 - 14},${cy.toFixed(1)}"
          fill="none" stroke="${alt.color}" stroke-width="1.2"
          ${alt.dash ? `stroke-dasharray="${alt.dash}"` : ''} opacity=".45"/>`);
        marks.push(`<g class="bv-dt-node" data-bps-decision-pick="${esc(node.id)},${esc(item.id)}">
          <title>${esc(item.hero)} · ${item.count} 局</title>
          ${markerWithIcon(item.hero, x2, cy, 11, `dt-${index}-${slot}`, alt.color)}
          <text x="${x2}" y="${(cy + 24).toFixed(1)}" class="bv-tree-alt">${item.action === 'ban' ? 'BAN' : 'PICK'} ${esc(short(item.hero))} ${item.count}</text>
        </g>`);
      });
    });
    return wrap(width, height, `${edges.join('')}${marks.join('')}`);
  }

  /* ── BP 时序流：同一手同一英雄合并成一个节点，边宽 = 局数，像地铁汇流图 ── */
  function draftFlowMap(data, {width = 1080, height = 480} = {}) {
    const all = (data?.nodes || []).filter((node) => node.level > 0);
    if (!data?.available || !all.length) {
      return `<div class="bv-empty">${esc(data?.reason || '没有可用的手序样本。')}</div>`;
    }
    const depth = Math.max(2, Number(data.depth) || 6);
    const perCol = depth >= 18 ? 68 : 92;
    const canvasWidth = Math.max(width, depth * perCol + 150);
    if (depth > 12) height = Math.max(height, 520);
    const keyOf = (node) => `${node.level}:${node.actor}:${node.action}:${node.hero}`;
    const merged = new Map();
    const sourceKey = new Map();
    for (const node of all) {
      const key = keyOf(node);
      sourceKey.set(node.id, key);
      const row = merged.get(key);
      if (row) {
        row.count += node.count;
        row.wins += node.wins || 0;
        row.decided += node.decided || 0;
      } else {
        merged.set(key, {key, level: node.level, action: node.action, actor: node.actor,
          hero: node.hero, count: node.count, wins: node.wins || 0, decided: node.decided || 0});
      }
    }
    const edgeCounts = new Map();
    for (const node of all) {
      const parentKey = node.parent === '0' ? '0' : sourceKey.get(node.parent);
      if (!parentKey) continue;
      const key = `${parentKey}>${sourceKey.get(node.id)}`;
      edgeCounts.set(key, (edgeCounts.get(key) || 0) + node.count);
    }
    const byLevel = new Map();
    for (const node of merged.values()) {
      if (!byLevel.has(node.level)) byLevel.set(node.level, []);
      byLevel.get(node.level).push(node);
    }
    const levels = [...byLevel.keys()].sort((a, b) => a - b);
    const top = 88;
    const bottom = 84;
    for (const level of levels) {
      const list = byLevel.get(level).sort((a, b) => b.count - a.count || a.hero.localeCompare(b.hero));
      const gap = (height - top - bottom) / Math.max(1, list.length - 1);
      list.forEach((node, index) => {
        node._y = list.length === 1 ? (top + height - bottom) / 2 : top + index * gap;
      });
    }
    const parentsOf = new Map();
    for (const [edge, count] of edgeCounts) {
      const [parentKey, childKey] = edge.split('>');
      if (parentKey === '0') continue;
      const parent = merged.get(parentKey);
      const child = merged.get(childKey);
      if (!parent || !child) continue;
      if (!parentsOf.has(childKey)) parentsOf.set(childKey, []);
      parentsOf.get(childKey).push({parent, count});
    }
    for (let round = 0; round < 4; round += 1) {
      for (const level of levels.slice(1)) {
        const list = byLevel.get(level);
        for (const node of list) {
          const parents = parentsOf.get(node.key) || [];
          const total = parents.reduce((sum, item) => sum + item.count, 0);
          if (total) node._y = parents.reduce((sum, item) => sum + item.parent._y * item.count, 0) / total;
        }
        list.sort((a, b) => a._y - b._y);
        const gap = 54;
        for (let index = 1; index < list.length; index += 1) {
          if (list[index]._y - list[index - 1]._y < gap) list[index]._y = list[index - 1]._y + gap;
        }
        const overflow = list.length ? list[list.length - 1]._y - (height - bottom) : 0;
        if (overflow > 0) for (const node of list) node._y -= overflow;
        const under = list.length ? top - list[0]._y : 0;
        if (under > 0) for (const node of list) node._y += under;
      }
    }
    const first = byLevel.get(levels[0]) || [];
    const rootY = first.length ? first.reduce((sum, node) => sum + node._y, 0) / first.length : height / 2;
    const left = 56;
    const right = 104;
    const colW = (canvasWidth - left - right) / Math.max(1, depth - 1);
    const xOf = (level) => left + (level - 1) * colW;
    const maxCount = Math.max(1, ...[...merged.values()].map((node) => node.count));
    const maxEdge = Math.max(1, ...edgeCounts.values());
    const tone = (node) => {
      if (node.actor === 'team') {
        return node.action === 'ban'
          ? {color: '#a94b40', dash: '5 4'} : {color: '#246b63', dash: ''};
      }
      return node.action === 'ban'
        ? {color: '#a86a2a', dash: '5 4'} : {color: '#4a6fa8', dash: ''};
    };
    const headers = levels.map((level) => {
      const list = byLevel.get(level);
      const lead = list[0];
      const paint = tone(lead);
      return `<text x="${xOf(level).toFixed(1)}" y="40" class="bv-tree-hand" fill="${paint.color}">${level} 手 · ${lead.action === 'ban' ? 'BAN' : 'PICK'}</text>
        <text x="${xOf(level).toFixed(1)}" y="54" class="bv-tree-side" fill="${paint.color}">${lead.actor === 'team' ? '我方' : '对方'}</text>`;
    }).join('');
    const edges = [];
    for (const [edge, count] of edgeCounts) {
      const [parentKey, childKey] = edge.split('>');
      const child = merged.get(childKey);
      if (!child) continue;
      const paint = tone(child);
      const y0 = parentKey === '0' ? rootY : merged.get(parentKey)?._y;
      if (!Number.isFinite(y0) || !Number.isFinite(child._y)) continue;
      const x0 = parentKey === '0' ? left - 26 : xOf(merged.get(parentKey).level);
      const x1 = xOf(child.level);
      const mid = (x0 + x1) / 2;
      const stroke = 1.2 + 4.4 * (count / maxEdge);
      edges.push(`<path d="M${(x0 + 12).toFixed(1)},${y0.toFixed(1)} C${mid.toFixed(1)},${y0.toFixed(1)} ${mid.toFixed(1)},${child._y.toFixed(1)} ${(x1 - 12).toFixed(1)},${child._y.toFixed(1)}"
        fill="none" stroke="${paint.color}" stroke-width="${stroke.toFixed(1)}"
        ${paint.dash ? `stroke-dasharray="${paint.dash}"` : ''}
        opacity="${(0.18 + 0.4 * (count / maxEdge)).toFixed(2)}" stroke-linecap="round"/>`);
    }
    const marks = [];
    let uid = 0;
    marks.push(`<circle cx="${(left - 26).toFixed(1)}" cy="${rootY.toFixed(1)}" r="9"
      fill="#0e2f2b" stroke="#fff" stroke-width="2"/>
      <text x="${(left - 26).toFixed(1)}" y="${(rootY + 26).toFixed(1)}" class="bv-tree-root">BP 开始</text>`);
    for (const node of merged.values()) {
      if (!Number.isFinite(node._y)) continue;
      const x = xOf(node.level);
      const paint = tone(node);
      const radius = 10 + 5 * Math.sqrt(node.count / maxCount);
      marks.push(`<g><title>${esc(node.hero)} · ${node.count} 局 · 胜率 ${node.decided ? fmt1(node.wins / node.decided * 100) + '%' : '—'}</title>
        ${markerWithIcon(node.hero, x, node._y, radius, `flow-${uid++}`, paint.color)}</g>
        <text x="${x.toFixed(1)}" y="${(node._y + radius + 14).toFixed(1)}" class="bv-tree-hero">${esc(short(node.hero))}</text>
        ${node.count > 1 ? `<text x="${x.toFixed(1)}" y="${(node._y + radius + 26).toFixed(1)}" class="bv-tree-count">${node.count} 局</text>` : ''}`);
    }
    return wrap(canvasWidth, height, `${headers}${edges.join('')}${marks.join('')}`)
      .replace('<svg ', `<svg style="min-width:${canvasWidth}px" `);
  }

  /* ── 类型时间轴：第一手 Ban 的类型份额按月堆叠 ─────────────────────── */
  function typeTimeline(timeline, laneOf, {width = 1200, height = 240} = {}) {
    const months = (timeline || []).filter((item) => (item.types || []).length);
    if (months.length < 2) return '<div class="bv-empty">月份太少，时间轴暂不绘制。</div>';
    const totals = new Map();
    for (const month of months) {
      for (const row of month.types || []) {
        totals.set(row.type, (totals.get(row.type) || 0) + (row.count || 0));
      }
    }
    const topTypes = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([type]) => type);
    const series = topTypes.map((type) => months.map((month) => {
      const total = (month.types || []).reduce((sum, row) => sum + (row.count || 0), 0) || 1;
      const hit = (month.types || []).find((row) => row.type === type);
      return hit ? (hit.count / total) * 100 : 0;
    }));
    const pad = {left: 40, right: 110, top: 22, bottom: 34};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const x = (index) => pad.left + (plotW * index) / Math.max(1, months.length - 1);
    const y = (value) => pad.top + plotH - (value / 100) * plotH;
    const stacks = months.map((_, index) => {
      let acc = 0;
      return series.map((line) => {
        const start = acc;
        acc += line[index];
        return {start, end: acc};
      });
    });
    const palette = ['#8fe0c8', '#c9a26b', '#9db7e8', '#e8a0a0', '#b8a6e8'];
    const paths = topTypes.map((type, ti) => {
      const top = stacks.map((stack, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(stack[ti].end).toFixed(1)}`).join(' ');
      const bottom = [...stacks].reverse().map((stack, rev) => {
        const index = stacks.length - 1 - rev;
        return `L${x(index).toFixed(1)},${y(stack[ti].start).toFixed(1)}`;
      }).join(' ');
      const color = palette[ti % palette.length];
      return `<path d="${top} ${bottom} Z" fill="${color}" fill-opacity=".24" stroke="${color}" stroke-width="1.2"/>`;
    }).join('');
    /* 右侧类型标签按末点位置排序后强制 13px 间距，避免几条线收在一起时文字叠住。 */
    const labels = topTypes.map((type, ti) => {
      const last = stacks[stacks.length - 1][ti];
      return {type, color: palette[ti % palette.length],
        y: y((last.start + last.end) / 2)};
    }).sort((a, b) => a.y - b.y);
    const gap = 13;
    const maxY = pad.top + plotH;
    for (let index = 1; index < labels.length; index += 1) {
      if (labels[index].y - labels[index - 1].y < gap) labels[index].y = labels[index - 1].y + gap;
    }
    for (let index = labels.length - 1; index >= 0; index -= 1) {
      const ceiling = maxY - (labels.length - 1 - index) * gap;
      if (labels[index].y > ceiling) labels[index].y = ceiling;
    }
    const labelText = labels.map((item) => `<text x="${x(months.length - 1) + 10}"
      y="${(item.y + 3.4).toFixed(1)}" class="bv-stream-label" fill="${item.color}">${esc(item.type)}</text>`).join('');
    const grid = [0, 25, 50, 75, 100].map((value) => `
      <line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>
      <text x="${pad.left - 8}" y="${(y(value) + 3.4).toFixed(1)}" class="bv-tick" text-anchor="end">${value}</text>`).join('');
    const ticks = months.map((month, index) => `
      <text x="${x(index)}" y="${height - 12}" class="bv-tick" text-anchor="middle">${esc(String(month.month).slice(2))}</text>`).join('');
    return wrap(width, height, `${grid}${paths}${labelText}${ticks}`);
  }

  /* ── 组合矩阵：英雄 × 英雄，格子颜色 = 相对基准，深浅 = 局数 ─────── */
  function comboMatrix(pairs, {width = 780, cell = 42, labelW = 104, topH = 66} = {}) {
    const rows = (pairs || []).filter((row) => (row.heroes || []).length === 2);
    if (rows.length < 6) return '<div class="bv-empty">组合样本不足，矩阵暂不绘制。</div>';
    /* 先取局数最高的 26 组，再由这些组合里的英雄构成矩阵，避免“14×14 大半是空格”。 */
    const topPairs = [...rows].sort((a, b) => (b.games || 0) - (a.games || 0)).slice(0, 26);
    const weight = new Map();
    for (const row of topPairs) {
      for (const hero of row.heroes) weight.set(hero, (weight.get(hero) || 0) + (row.games || 0));
    }
    const nodes = [...weight.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([hero]) => hero);
    const index = new Map(nodes.map((hero, i) => [hero, i]));
    const n = nodes.length;
    const height = topH + n * cell + 26;
    const grid = rows.filter((row) => row.heroes.every((hero) => index.has(hero)));
    const byPair = new Map(grid.map((row) => [[index.get(row.heroes[0]), index.get(row.heroes[1])]
      .sort((a, b) => a - b).join('-'), row]));
    const maxGames = Math.max(1, ...grid.map((row) => row.games || 0));
    const cells = [];
    for (let i = 0; i < n; i += 1) {
      for (let j = i + 1; j < n; j += 1) {
        const row = byPair.get(`${i}-${j}`);
        const x = labelW + j * cell;
        const y = topH + i * cell;
        if (!row) {
          cells.push(`<rect x="${x}" y="${y}" width="${cell - 2}" height="${cell - 2}" rx="6" class="bv-mx-empty"/>`);
          continue;
        }
        const rel = row.relative;
        const intensity = 0.18 + ((row.games || 0) / maxGames) * 0.62;
        const color = rel == null ? '#6f7d76' : rel >= 0 ? '#2f8a76' : '#b3574c';
        cells.push(`<g class="bv-mx-cell">
          <rect x="${x}" y="${y}" width="${cell - 2}" height="${cell - 2}" rx="6"
            fill="${color}" fill-opacity="${intensity.toFixed(2)}"/>
          <text x="${x + (cell - 2) / 2}" y="${y + (cell - 2) / 2 + 3.4}" text-anchor="middle"
            class="bv-mx-value">${row.games || 0}</text>
          <title>${esc(row.heroes[0])} + ${esc(row.heroes[1])} · ${row.games || 0} 局 · 胜率 ${fmt1(row.winRate)}% · 基准 ${rel == null ? '—' : (rel > 0 ? '+' : '') + fmt1(rel)}pp</title>
        </g>`);
      }
    }
    const top = nodes.map((hero, i) => {
      const cx = labelW + i * cell + (cell - 2) / 2;
      return `<g>${markerWithIcon(hero, cx, 22, 13, `mx-top-${i}`)}
        <text x="${cx}" y="${topH - 8}" text-anchor="end" class="bv-mx-head"
          transform="rotate(-52 ${cx} ${topH - 8})">${esc(short(hero))}</text></g>`;
    }).join('');
    const left = nodes.map((hero, i) => {
      const cy = topH + i * cell + (cell - 2) / 2;
      return `<g>${markerWithIcon(hero, labelW - 26, cy, 12, `mx-left-${i}`)}
        <text x="${labelW - 44}" y="${cy + 3.6}" text-anchor="end" class="bv-mx-label">${esc(short(hero))}</text></g>`;
    }).join('');
    const legend = `<g transform="translate(${labelW}, ${height - 8})">
      <rect x="0" y="-10" width="10" height="10" rx="2" fill="#2f8a76" fill-opacity=".6"/>
      <text x="14" y="-1" class="bv-tick">跑赢基准</text>
      <rect x="96" y="-10" width="10" height="10" rx="2" fill="#b3574c" fill-opacity=".6"/>
      <text x="110" y="-1" class="bv-tick">低于基准</text>
      <text x="196" y="-1" class="bv-tick">格子数字 = 同队同局；颜色越深局数越多</text>
    </g>`;
    return wrap(width, height, `${top}${left}${cells.join('')}${legend}
      <line x1="${labelW}" y1="${topH - 2}" x2="${labelW + n * cell}" y2="${topH - 2}" class="bv-grid"/>`);
  }

  /* ── 类型轮盘：第一手 Ban 的类型份额，做成同心扇形 ───────────────── */
  function typeWheel(rows, laneOf, {size = 380, total = 0, title = '第一手 Ban'} = {}) {
    const list = (rows || []).filter((row) => (row.share || 0) > 0).slice(0, 9);
    if (list.length < 2) return '<div class="bv-empty">样本不足，类型轮盘暂不绘制。</div>';
    const cx = size / 2;
    const cy = size / 2;
    const outer = size / 2 - 54;
    const inner = outer * 0.58;
    let angle = -Math.PI / 2;
    const gap = 0.012;
    const sectors = list.map((row, index) => {
      const span = Math.max(0.02, ((row.share || 0) / 100) * Math.PI * 2 - gap);
      const start = angle + gap / 2;
      const end = start + span;
      angle += span + gap;
      const lane = laneOf?.(row.type) || '';
      const color = LANE_COLOR[lane] || '#6f7d76';
      const point = (a, r) => [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
      const [x1, y1] = point(start, outer);
      const [x2, y2] = point(end, outer);
      const [x3, y3] = point(end, inner);
      const [x4, y4] = point(start, inner);
      const large = span > Math.PI ? 1 : 0;
      const mid = (start + end) / 2;
      const [lx, ly] = point(mid, outer + 20);
      const anchorText = Math.abs(lx - cx) < 12 ? 'middle' : lx > cx ? 'start' : 'end';
      const showLabel = (row.share || 0) >= 3;
      return `<g class="bv-wheel-sector">
        <path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${outer},${outer} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)}
          L${x3.toFixed(1)},${y3.toFixed(1)} A${inner},${inner} 0 ${large} 0 ${x4.toFixed(1)},${y4.toFixed(1)} Z"
          fill="${color}" fill-opacity="${(0.22 + index * 0.05).toFixed(2)}" stroke="${color}" stroke-opacity=".55"/>
        ${showLabel ? `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="bv-wheel-label" text-anchor="${anchorText}">${esc(row.type)}</text>
        <text x="${lx.toFixed(1)}" y="${(ly + 14).toFixed(1)}" class="bv-wheel-value" text-anchor="${anchorText}">${fmt1(row.share)}%</text>` : ''}
        <title>${esc(row.type)} · ${fmt1(row.share)}% · ${row.count || 0} 次</title>
      </g>`;
    }).join('');
    return wrap(size, size, `
      <circle cx="${cx}" cy="${cy}" r="${outer}" class="bv-wheel-track"/>
      <circle cx="${cx}" cy="${cy}" r="${inner}" class="bv-wheel-track"/>
      ${sectors}
      <text x="${cx}" y="${cy - 4}" text-anchor="middle" class="bv-wheel-center">${total || ''}</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" class="bv-wheel-caption">${esc(title)} · 次数</text>`);
  }

  /* ── 位次流：五条分路在 1–5 手的份额带 ───────────────────────────── */
  function slotStream(slots, laneOf, {width = 720, height = 300, laneOrder = []} = {}) {
    if (!slots?.length) return '<div class="bv-empty">没有逐手 Pick 记录。</div>';
    const lanes = laneOrder.length ? laneOrder
      : [...new Set(slots.flatMap((slot) => (slot.types || []).map((row) => laneOf?.(row.type)))
        .filter(Boolean))];
    const series = lanes.map((lane) => slots.map((slot) => {
      const total = slot.types.reduce((sum, row) => sum + (row.share || 0), 0) || 1;
      const value = slot.types.filter((row) => laneOf?.(row.type) === lane)
        .reduce((sum, row) => sum + (row.share || 0), 0);
      return (value / total) * 100;
    }));
    /* 堆叠图的上限是每个位次的合计（≈100），不是单条分路的最高值，
       否则上面几层会算出负坐标、溢出到别的面板上。 */
    const stackTotals = slots.map((_, index) => series.reduce((sum, line) => sum + line[index], 0));
    const max = Math.max(10, ...stackTotals);
    const pad = {left: 34, right: 96, top: 26, bottom: 30};
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const x = (index) => pad.left + (plotW * index) / Math.max(1, slots.length - 1);
    const y = (value) => pad.top + plotH - (value / max) * plotH;
    const stacks = slots.map((_, index) => {
      let acc = 0;
      return series.map((line) => {
        const start = acc;
        acc += line[index];
        return {start, end: acc};
      });
    });
    const paths = lanes.map((lane, laneIndex) => {
      const top = stacks.map((stack, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(stack[laneIndex].end).toFixed(1)}`).join(' ');
      const bottom = [...stacks].reverse().map((stack, revIndex) => {
        const index = stacks.length - 1 - revIndex;
        return `L${x(index).toFixed(1)},${y(stack[laneIndex].start).toFixed(1)}`;
      }).join(' ');
      const last = stacks[stacks.length - 1][laneIndex];
      return `<path d="${top} ${bottom} Z" fill="${LANE_COLOR[lane] || '#6f7d76'}" fill-opacity=".2"
        stroke="${LANE_COLOR[lane] || '#6f7d76'}" stroke-width="1.2"/>
        <text x="${x(slots.length - 1) + 10}" y="${(y((last.end + last.start) / 2) + 3).toFixed(1)}"
          class="bv-stream-label" fill="${LANE_COLOR[lane] || '#6f7d76'}">${esc(lane)}</text>`;
    }).join('');
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = max * ratio;
      return `<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${pad.left + plotW}" y2="${y(value).toFixed(1)}" class="bv-grid"/>
        <text x="${pad.left - 8}" y="${(y(value) + 3.4).toFixed(1)}" class="bv-tick" text-anchor="end">${Math.round(value)}</text>`;
    }).join('');
    const ticks = slots.map((slot, index) => `
      <line x1="${x(index)}" y1="${pad.top}" x2="${x(index)}" y2="${pad.top + plotH}" class="bv-grid"/>
      <text x="${x(index)}" y="${height - 10}" class="bv-tick" text-anchor="middle">${slot.slot} 手</text>`).join('');
    return wrap(width, height, `${grid}${ticks}${paths}
      <text x="${pad.left}" y="14" class="bv-axis-title">占比 %</text>`);
  }

  /* ── 核数环：外环份额，内环胜率 ──────────────────────────────────── */
  function coreRadial(rows, {size = 300, avg = null} = {}) {
    const list = (rows || []).filter((row) => row.games > 0);
    if (!list.length) return '<div class="bv-empty">没有完整阵容。</div>';
    const cx = size / 2;
    const cy = size / 2;
    const outer = size / 2 - 34;
    const inner = outer - 22;
    const shareMax = Math.max(...list.map((row) => row.share || 0));
    let angle = -Math.PI / 2;
    const arcs = list.map((row, index) => {
      const span = ((row.share || 0) / Math.max(1, shareMax)) * (Math.PI * 0.55);
      const start = angle + 0.04;
      const end = start + span;
      angle = end + 0.05;
      const point = (a, r) => [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
      const [x1, y1] = point(start, outer);
      const [x2, y2] = point(end, outer);
      const [x3, y3] = point(end, inner);
      const [x4, y4] = point(start, inner);
      const color = ['#8fe0c8', '#c9a26b', '#9db7e8', '#e8a0a0'][index % 4];
      const [wx1, wy1] = point(start, inner - 12);
      const [wx2, wy2] = point(start + Math.max(0.02, ((row.winRate || 0) / 100) * (Math.PI * 0.55)), inner - 12);
      const [mx, my] = point((start + end) / 2, outer + 15);
      return `<g>
        <path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${outer},${outer} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}
          L${x3.toFixed(1)},${y3.toFixed(1)} A${inner},${inner} 0 0 0 ${x4.toFixed(1)},${y4.toFixed(1)} Z"
          fill="${color}" fill-opacity=".26" stroke="${color}" stroke-opacity=".7"/>
        <path d="M${wx1.toFixed(1)},${wy1.toFixed(1)} A${inner - 12},${inner - 12} 0 0 1 ${wx2.toFixed(1)},${wy2.toFixed(1)}"
          class="bv-core-win" stroke="${color}"/>
        <text x="${mx.toFixed(1)}" y="${my.toFixed(1)}" class="bv-core-label" text-anchor="middle">${row.cores} 核</text>
        <text x="${mx.toFixed(1)}" y="${(my + 13).toFixed(1)}" class="bv-core-value" text-anchor="middle">${fmt1(row.share)}%</text>
        <title>${row.cores} 核 · ${row.games} 局 · 胜率 ${fmt1(row.winRate)}%</title>
      </g>`;
    }).join('');
    return wrap(size, size, `${arcs}
      <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="bv-wheel-center">${avg ?? '—'}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" class="bv-wheel-caption">平均核数</text>`);
  }

  /* ── 类型 × 位次点阵：每格一个圆，面积 = 占比 ─────────────────────── */
  function dotMatrix(rows, cols, cells, {width = 780, rowHeight = 32, leftWidth = 110,
    colWidth = 104, tone = ''} = {}) {
    if (!rows.length || !cols.length) return '<div class="bv-empty">没有可用的类型样本。</div>';
    const values = cells.flat().map((cell) => (has(cell) ? cell : 0));
    const max = Math.max(1, ...values);
    const height = rows.length * rowHeight + 34;
    const head = cols.map((col, index) => {
      const x = leftWidth + index * colWidth + colWidth / 2;
      return `<text x="${x.toFixed(1)}" y="16" text-anchor="middle" class="bv-col-title">${esc(col.label)}</text>
        ${col.sub ? `<text x="${x.toFixed(1)}" y="29" text-anchor="middle" class="bv-tick">${esc(col.sub)}</text>` : ''}`;
    }).join('');
    const body = rows.map((row, rowIndex) => {
      const cy = 46 + rowIndex * rowHeight;
      const label = `<text x="${leftWidth - 10}" y="${cy + 4}" text-anchor="end" class="bv-row-label">${esc(row.label)}</text>`;
      const dots = cols.map((col, colIndex) => {
        const value = has(cells[rowIndex]?.[colIndex]) ? cells[rowIndex][colIndex] : 0;
        const radius = value > 0 ? 2.4 + Math.sqrt(value / max) * 8.5 : 0;
        const cx = leftWidth + colIndex * colWidth + colWidth / 2;
        if (!radius) return `<circle cx="${cx}" cy="${cy}" r="1.6" class="bv-zero-dot"/>`;
        return `<g><circle cx="${cx}" cy="${cy}" r="${radius.toFixed(1)}" class="bv-matrix-dot ${tone}"/>
          <title>${esc(row.label)} · ${esc(col.label)} ${fmt1(value)}%</title>
          ${value >= 8 ? `<text x="${cx}" y="${cy + 3.4}" text-anchor="middle" class="bv-matrix-value">${Math.round(value)}</text>` : ''}</g>`;
      }).join('');
      return `<g>${label}${dots}</g>`;
    }).join('');
    return wrap(width, height, `${head}${body}`);
  }

  /* ── Ban 位环：四个 Ban 位的份额做成同心环，比四条横条更像“手序” ── */
  function handRing(hands, {size = 168, label = 'Ban 位'} = {}) {
    const list = (hands || []).filter((row) => has(row.share));
    if (!list.length) return '<div class="bv-empty">没有 Ban 记录。</div>';
    const cx = size / 2;
    const cy = size / 2;
    const colors = ['#123f39', '#246b63', '#5b9a86', '#c9a26b'];
    let start = -Math.PI / 2;
    const arcs = list.map((row, index) => {
      const sweep = (clamp(row.share || 0, 0, 100) / 100) * Math.PI * 2;
      const end = start + sweep;
      const r = size / 2 - 10 - index * 13;
      const p = (angle, radius) => [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius];
      const [x1, y1] = p(start + 0.02, r);
      const [x2, y2] = p(Math.max(start + 0.02, end - 0.02), r);
      const large = sweep > Math.PI ? 1 : 0;
      const path = sweep <= 0.03 ? '' : `M${x1.toFixed(1)},${y1.toFixed(1)}
        A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)}`;
      start = end + 0.05;
      return `<path d="${path}" fill="none" stroke="${colors[index % colors.length]}"
        stroke-width="9" stroke-linecap="round" opacity="${0.55 + index * 0.12}"/>`;
    }).join('');
    const legend = list.map((row, index) => `
      <text x="${size + 14}" y="${18 + index * 20}" class="bv-tick">
        <tspan fill="${colors[index % colors.length]}" font-weight="800">●</tspan>
        ${esc(`第 ${row.hand} 手`)} · ${fmt1(row.share)}%</text>`).join('');
    return `<div class="bv-handring" style="width:${size + 118}px">
      <svg viewBox="0 0 ${size + 118} ${size}" style="width:${size + 118}px;height:${size}px">
        <circle cx="${cx}" cy="${cy}" r="${size / 2 - 10}" fill="none" class="bv-ring"/>
        ${arcs}
        <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="bv-handring-title">${esc(label)}</text>
        <text x="${cx}" y="${cy + 14}" text-anchor="middle" class="bv-tick">第一轮 ${fmt1((list[0]?.share || 0) + (list[1]?.share || 0))}%</text>
        ${legend}
      </svg>
    </div>`;
  }

  /* ── 环形占比：单个百分比 ─────────────────────────────────────────── */
  function donut(value, {label = '', size = 78, stroke = 9, tone = ''} = {}) {
    const radius = (size - stroke) / 2 - 2;
    const cx = size / 2;
    const circle = 2 * Math.PI * radius;
    const pctValue = has(value) ? clamp(value, 0, 100) : 0;
    return `<div class="bv-donut ${tone}" style="width:${size}px;height:${size}px">
      <svg viewBox="0 0 ${size} ${size}" aria-hidden="true">
        <circle cx="${cx}" cy="${cx}" r="${radius}" fill="none" class="bv-donut-track" stroke-width="${stroke}"/>
        <circle cx="${cx}" cy="${cx}" r="${radius}" fill="none" class="bv-donut-value" stroke-width="${stroke}"
          stroke-linecap="round" stroke-dasharray="${circle.toFixed(1)}"
          stroke-dashoffset="${(circle * (1 - pctValue / 100)).toFixed(1)}"
          transform="rotate(-90 ${cx} ${cx})"/>
      </svg>
      <span>${has(value) ? `${fmt1(value)}%` : '—'}${label ? `<small>${esc(label)}</small>` : ''}</span>
    </div>`;
  }

  /* ── 迷你趋势（保留：线图，不是条）──────────────────────────────── */
  function spark(points, {key = 'pickRate', w = 120, h = 32, tone = 'accent'} = {}) {
    const values = (points || []).map((point) => (typeof point === 'number' ? point : point?.[key]))
      .filter(has);
    if (values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(1, max - min);
    const step = w / (values.length - 1);
    const y = (value) => h - 4 - ((value - min) / span) * (h - 10);
    const line = values.map((value, index) =>
      `${index ? 'L' : 'M'}${(index * step).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
    return `<svg class="bv-spark ${tone}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path class="bv-spark-area" d="${line} L${w},${h} L0,${h} Z"></path>
      <path class="bv-spark-line" d="${line}"></path></svg>`;
  }


  /* 卡片内的“上一窗口 → 当前窗口”迷你斜率，不带坐标轴，避免和卡片文字重复。 */
  function miniDelta(from, to, {width = 220, height = 30, min = 0, max = 100} = {}) {
    if (!has(from) || !has(to)) return '';
    const low = Math.min(min, from, to);
    const high = Math.max(max, from, to);
    const x0 = 10;
    const x1 = width - 10;
    const y = (value) => height - 5 - ((clamp(value, low, high) - low) / Math.max(1, high - low)) * (height - 10);
    const up = to >= from;
    return `<svg class="bv-mini" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <line x1="${x0}" y1="${height - 5}" x2="${x1}" y2="${height - 5}" class="bv-mini-axis"/>
      <line x1="${x0}" y1="${y(from)}" x2="${x1}" y2="${y(to)}" class="bv-mini-line ${up ? 'is-up' : 'is-down'}"/>
      <circle cx="${x0}" cy="${y(from)}" r="3.4" class="bv-mini-dot is-from"/>
      <circle cx="${x1}" cy="${y(to)}" r="4.4" class="bv-mini-dot ${up ? 'is-up' : 'is-down'}"/>
    </svg>`;
  }

  /* 行内区间点：一个点 + Wilson 须，替代横条 */
  function intervalDot(value, intervalArr, {width = 104, height = 20, min = 0, max = 100} = {}) {
    if (!has(value)) return '<span class="bv-muted">—</span>';
    const x = (v) => 7 + (clamp(v, min, max) - min) / Math.max(1, max - min) * (width - 14);
    const low = Array.isArray(intervalArr) ? intervalArr[0] : null;
    const high = Array.isArray(intervalArr) ? intervalArr[1] : null;
    const tone = value >= 55 ? 'is-good' : value <= 45 ? 'is-bad' : '';
    return `<svg class="bv-iDot" viewBox="0 0 ${width} ${height}" style="width:${width}px;height:${height}px" aria-hidden="true">
      ${low != null && high != null ? `<line x1="${x(low).toFixed(1)}" y1="${height / 2}" x2="${x(high).toFixed(1)}" y2="${height / 2}" class="bv-ci"/>
        <line x1="${x(low).toFixed(1)}" y1="${height / 2 - 3}" x2="${x(low).toFixed(1)}" y2="${height / 2 + 3}" class="bv-ci-cap"/>
        <line x1="${x(high).toFixed(1)}" y1="${height / 2 - 3}" x2="${x(high).toFixed(1)}" y2="${height / 2 + 3}" class="bv-ci-cap"/>` : ''}
      <line x1="${x(50).toFixed(1)}" y1="3" x2="${x(50).toFixed(1)}" y2="${height - 3}" class="bv-quad"/>
      <circle cx="${x(value).toFixed(1)}" cy="${height / 2}" r="3.8" class="bv-dot ${tone}"/>
    </svg>`;
  }

  return {heroScatter, dotScatter, dotCI, dumbbell, handHeatmap, handRing, radar, slope,
    donut, spark, intervalDot, miniDelta, comboScatter, comboMatrix, heroCloud, portraitQuadrant, poolScatter, typeRank, typeLines, coreDots, typeCounterMatrix, typeTimeline, draftFlowMap, decisionTreeMap, heroRing, dotMatrix, typeWheel, slotStream, coreRadial, LANE_COLOR, PALETTE};

}
