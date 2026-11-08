/* ==========================================================================
   页面组件渲染 —— 结构照搬参考项目（team.html / compare.js / hero_perf_app.js）
   只做字符串拼装，不持有状态；各页面把自己的数据喂进来。
   ========================================================================== */

export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

export const num = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
export const pct = (value, digits = 1) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toFixed(digits) + '%' : '—';
export const signed = (value, digits = 1) => {
  if (!Number.isFinite(Number(value)) || value === null) return '—';
  const v = Number(value);
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`;
};

/* ---------------- 页面头 ---------------- */
export function pageHero({kicker, title, lead = [], meta = [], actions = ''}) {
  const paragraphs = (Array.isArray(lead) ? lead : [lead]).filter(Boolean)
    .map(text => `<p>${text}</p>`).join('');
  const metaLine = meta.length
    ? `<div class="ph-meta">${meta.map(item => `<span>${item}</span>`).join('')}</div>` : '';
  return `<header class="page-hero">
    ${kicker ? `<div class="ph-kicker">${esc(kicker)}</div>` : ''}
    <h1>${esc(title)}</h1>
    ${paragraphs}
    ${metaLine}
    ${actions ? `<div class="ph-actions">${actions}</div>` : ''}
  </header>`;
}

/* ---------------- 数据范围 / 筛选 ---------------- */
export function scopeBar({label = '数据范围', value = '', note = ''} = {}) {
  return `<div class="scopebar">
    <span class="scope-lab">${esc(label)}</span>
    ${value ? `<b>${esc(value)}</b>` : ''}
    ${note ? `<span class="scope-meta">${esc(note)}</span>` : ''}
  </div>`;
}

export function filterBar(inner = '') {
  return inner ? `<div class="filterbar">${inner}</div>` : '';
}

export function field(label, control) {
  return `<label class="fld"><span>${esc(label)}</span>${control}</label>`;
}

/* ---------------- 指标格 ---------------- */
export function stats(items, {cls = ''} = {}) {
  const cells = items.map(([k, v, s, tone]) => `<div class="hd-cell${tone === 'hl' ? ' hl' : ''}">
      <div class="k">${esc(k)}</div>
      <div class="v">${v}</div>
      ${s ? `<div class="s">${esc(s)}</div>` : ''}
    </div>`).join('');
  return `<div class="hd-stats${cls ? ' ' + cls : ''}">${cells}</div>`;
}

/* ---------------- 区块 ---------------- */
export function panel(title, body, {note = '', foot = '', span = false} = {}) {
  return `<section class="panel${span ? ' span-2' : ''}">
    ${title ? `<h2 class="panel-title">${esc(title)}${note ? `<em>${esc(note)}</em>` : ''}</h2>` : ''}
    <div class="panel-body">${body}</div>
    ${foot ? `<div class="panel-foot">${foot}</div>` : ''}
  </section>`;
}

export const emptyTip = (text = '当前范围没有可用记录。') => `<div class="empty-tip">${esc(text)}</div>`;

/* ---------------- 胜率环 ---------------- */
export function ring(value, {size = 46, stroke = 5, label = '胜率'} = {}) {
  if (value == null || !Number.isFinite(Number(value))) {
    return `<svg class="ring is-empty" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-label="暂无${esc(label)}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${(size - stroke) / 2}" fill="none"
        stroke="var(--line-soft)" stroke-width="${stroke}"/></svg>`;
  }
  const pctValue = Math.max(0, Math.min(100, Number(value)));
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const color = pctValue >= 50 ? 'var(--pos)' : 'var(--neg)';
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"
      role="img" aria-label="${esc(label)} ${Math.round(pctValue)}%">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--line-soft)" stroke-width="${stroke}"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
      stroke-linecap="round" stroke-dasharray="${(c * pctValue / 100).toFixed(1)} ${c.toFixed(1)}"
      transform="rotate(-90 ${size / 2} ${size / 2})"/>
    <text x="50%" y="55%" text-anchor="middle" dominant-baseline="middle"
      font-size="${Math.round(size * 0.27)}" font-weight="700" fill="var(--ink)"
      font-variant-numeric="tabular-nums">${Math.round(pctValue)}</text>
  </svg>`;
}

/* ---------------- 近况点条（胜/负小方块） ----------------
   games: [{win: true|false|null, start?}] */
export function wlDots(games, {max = 10} = {}) {
  const list = (games || []).slice(-max);
  if (!list.length) return '';
  return `<span class="wl-dots">${list.map(game => {
    const state = game.win === true ? 'w' : game.win === false ? 'l' : 'u';
    const mark = game.win === true ? '胜' : game.win === false ? '负' : '未定';
    return `<i class="${state}" title="${esc(game.start || game.date || '')} ${mark}"></i>`;
  }).join('')}</span>`;
}

/* ---------------- 骨架屏 ----------------
   kind: page（英雄+KPI+面板）| cards（卡网格）| table（长表）| chart（大图） */
export function skeleton(kind = 'page', {note = '正在读取…'} = {}) {
  const cells = `<div class="sk sk-cell"></div><div class="sk sk-cell"></div>
    <div class="sk sk-cell"></div><div class="sk sk-cell"></div>`;
  const variants = {
    page: `<div class="sk-page"><div class="sk sk-hero"></div><div class="sk-stats">${cells}</div>
      <div class="sk sk-panel"></div><div class="sk sk-panel" style="height:180px"></div></div>`,
    cards: `<div class="sk-page"><div class="sk sk-hero" style="height:70px"></div>
      <div class="sk-cards"><div class="sk sk-card"></div><div class="sk sk-card"></div>
      <div class="sk sk-card"></div><div class="sk sk-card"></div></div></div>`,
    table: `<div class="sk-page"><div class="sk sk-panel" style="height:120px"></div>
      <div class="sk sk-panel" style="height:300px"></div></div>`,
    chart: `<div class="sk-page"><div class="sk-stats">${cells}</div>
      <div class="sk sk-panel" style="height:320px"></div></div>`,
  };
  return `<div class="sk-wrap" role="status" aria-label="${esc(note)}">${variants[kind] || variants.page}</div>`;
}

/* ---------------- 表格 ----------------
   cell 可以是字符串，或 {v: html, cls: 'best'}；cls 支持 best / worst / num / delta is-pos 等 */
export function table(headers, rows, {cls = '', empty = ''} = {}) {
  if (!rows.length) return emptyTip(empty || '当前范围没有记录。');
  const head = headers.map(h => {
    const label = typeof h === 'string' ? h : h.label;
    const align = typeof h === 'string' ? '' : h.align;
    return `<th${align === 'right' ? ' class="num"' : ''}>${label}</th>`;
  }).join('');
  const body = rows.map(row => `<tr>${row.map(cell => {
    if (cell === null || cell === undefined) return '<td class="muted">—</td>';
    if (typeof cell === 'string') return `<td>${cell}</td>`;
    return `<td${cell.cls ? ` class="${cell.cls}"` : ''}>${cell.v}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="tbl-wrap"><table class="tbl ${cls}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* ---------------- 分位雷达 ----------------
   dims: [{key, label}]；series: [{name, color, values:{key: 0-100}}] */
export function radar(dims, series) {
  const W = 560, H = 472, CX = 280, CY = 246, R = 168, n = dims.length;
  const GRID = 'var(--line)';
  const LABEL = 'var(--ink-3)';
  const pt = (i, r) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [CX + Math.cos(a) * r, CY + Math.sin(a) * r];
  };
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="分位对比雷达图"><defs>`;
  series.forEach((se, si) => {
    svg += `<radialGradient id="radarGrad${si}" cx="50%" cy="50%" r="70%">`
      + `<stop offset="0%" stop-color="${se.color}" stop-opacity=".30"/>`
      + `<stop offset="100%" stop-color="${se.color}" stop-opacity=".10"/></radialGradient>`;
  });
  svg += '</defs>';
  for (let ring = 1; ring <= 5; ring += 1) {
    const rr = R * ring / 4;
    const pts = dims.map((_, i) => pt(i, rr).map(v => v.toFixed(1)).join(',')).join(' ');
    const isP50 = ring === 3;
    svg += `<polygon points="${pts}" fill="${ring === 5 ? 'rgba(105,112,128,.035)' : 'none'}" `
      + `stroke="${GRID}" stroke-width="${isP50 ? 1.4 : 1}"${isP50 ? ' stroke-dasharray="5 5"' : ''}/>`;
  }
  dims.forEach((dim, i) => {
    const p = pt(i, R);
    svg += `<line x1="${CX}" y1="${CY}" x2="${p[0].toFixed(1)}" y2="${p[1].toFixed(1)}" stroke="${GRID}"/>`;
    const lp = pt(i, R + 36);
    const anchor = lp[0] < CX - 12 ? 'end' : lp[0] > CX + 12 ? 'start' : 'middle';
    svg += `<text x="${lp[0].toFixed(1)}" y="${(lp[1] + 4).toFixed(1)}" text-anchor="${anchor}" `
      + `font-size="12.5" fill="${LABEL}" font-family="Inter,PingFang SC,sans-serif">${esc(dim.label)}</text>`;
  });
  series.forEach((se, ci) => {
    const pts = dims.map((dim, i) => pt(i, R * Math.max(0, Math.min(100, se.values?.[dim.key] ?? 0)) / 100)
      .map(v => v.toFixed(1)).join(',')).join(' ');
    svg += `<polygon points="${pts}" fill="url(#radarGrad${ci})" stroke="${se.color}" stroke-width="2.5" stroke-linejoin="round"/>`;
    dims.forEach((dim, i) => {
      const score = Math.max(0, Math.min(100, se.values?.[dim.key] ?? 0));
      const p = pt(i, R * score / 100);
      const tip = `${se.name} · ${dim.label}：分位 ${Math.round(score)}`;
      svg += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${se.color}">`
        + `<title>${esc(tip)}</title></circle>`;
    });
  });
  const avgPts = dims.map((_, i) => pt(i, R * 50 / 100).map(v => v.toFixed(1)).join(',')).join(' ');
  svg += `<polygon points="${avgPts}" fill="none" stroke="${LABEL}" stroke-width="1.5" stroke-dasharray="5 5" `
    + `stroke-linejoin="round" opacity=".9"/>`
    + `<text x="${CX}" y="${(CY - R * 0.5 - 7).toFixed(1)}" text-anchor="middle" font-size="10" fill="${LABEL}">P50</text>`;
  return svg + '</svg>';
}

export function radarCard({dims, series, legend = true}) {
  return `<div class="cmp-radar">${radar(dims, series)}
    ${legend ? `<div class="cmp-legend">${series.map(se =>
      `<span><i style="background:${se.color}"></i>${esc(se.name)}</span>`).join('')}
      <span class="cmp-avg"><i class="dash"></i>范围中位</span></div>` : ''}
  </div>`;
}

/* ---------------- 子弹图 ----------------
   rows: [{label, own:{p, text}, team:{p, text}}]，刻度固定 50/75/90 分位 */
export function bullets(rows, {note = ''} = {}) {
  if (!rows.length) return emptyTip('当前范围没有可比指标。');
  const body = rows.map(row => `<div class="hp-bench">
      <div class="hp-bench-top">${esc(row.label)}</div>
      <div class="hp-bench-val">${row.own?.text ?? '—'}${row.team ? `<small>对方 ${row.team.text}</small>` : ''}</div>
      <span class="hp-track">
        <u style="left:50%"></u><u style="left:75%"></u><u style="left:90%"></u>
        ${row.team?.p == null ? '' : `<i class="is-team" style="left:${Math.max(0, Math.min(100, row.team.p))}%"></i>`}
        ${row.own?.p == null ? '' : `<i style="left:${Math.max(0, Math.min(100, row.own.p))}%"></i>`}
      </span>
    </div>`).join('');
  return `<div class="hp-bench-grid">${body}</div>${note ? `<div class="block-note">${esc(note)}</div>` : ''}`;
}

/* ---------------- 洞察 chip ---------------- */
export function insights(groups) {
  const rows = groups.filter(group => group.chips?.length).map(group => `<div class="cmp-insight">
      <b>${esc(group.label)}</b>
      ${group.chips.map(chip => `<span class="cmp-chip ${chip.tone || 'neutral'}">${
        chip.arrow ? `<i class="cmp-arrow">${chip.arrow}</i>` : ''}${esc(chip.text)}</span>`).join('')}
    </div>`).join('');
  return rows ? `<div class="cmp-insights">${rows}</div>` : '';
}

/* ---------------- 口径说明 ---------------- */
export function rulesPanel(items, {title = '口径说明'} = {}) {
  const list = items.map(item => `<li>${item}</li>`).join('');
  return panel(title, `<ol class="block-note" style="margin:0;padding-left:1.2em">${list}</ol>`);
}

/* ---------------- 横向条形（带数值） ---------------- */
export function hBars(rows, {unit = '', digits = 0, max = null, tone = '', ref = null} = {}) {
  if (!rows.length) return emptyTip('没有可展示的数据。');
  const top = max ?? Math.max(1, ...rows.map(row => Number(row.value) || 0));
  const refTick = ref != null
    ? `<i class="h-bar-ref" style="left:${Math.max(0, Math.min(100, ref))}%" title="参考线 ${ref}${esc(unit)}"></i>` : '';
  return `<div class="h-bars${tone ? ' is-' + tone : ''}${ref != null ? ' has-ref' : ''}">${rows.map(row => {
    const value = Number(row.value) || 0;
    const width = Math.max(1.5, Math.min(100, value / top * 100));
    return `<div class="h-bar" title="${esc(String(row.label))}：${Number.isFinite(value) ? value.toFixed(digits) : '—'}${esc(unit)}">
      <span class="h-bar-label">${esc(row.label)}</span>
      <span class="h-bar-track">${refTick}<i style="width:${width.toFixed(1)}%"></i></span>
      <span class="h-bar-value">${Number.isFinite(value) ? value.toFixed(digits) : '—'}${esc(unit)}</span>
    </div>`;
  }).join('')}</div>`;
}

/* ---------------- 折线 + 区间标记 ----------------
   points: [{x(秒), y}]；markers: [{start, end, delta}] */
/* 紧凑数字与时间：数轴与悬浮提示的「印刷感」来源 */
const fmtCompact = value => {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 10000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return Math.round(value).toLocaleString('zh-CN');
};
const fmtClock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export function lineChart(points, {unit = '', markers = [], height = 220, zero = true} = {}) {
  const visible = points.filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (visible.length < 2) return emptyTip('没有足够的经济采样点。');
  const width = 860, left = 62, right = width - 18, top = 16, bottom = height - 30;
  const xs = visible.map(point => point.x);
  const ys = visible.map(point => point.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs) || 1;
  const yMin = Math.min(zero ? 0 : Math.min(...ys), ...ys);
  const yMax = Math.max(zero ? 0 : Math.max(...ys), ...ys);
  const pad = (yMax - yMin) * 0.12 || 100;
  const scaleX = value => left + (value - xMin) / (xMax - xMin || 1) * (right - left);
  const scaleY = value => bottom - (value - yMin + pad) / (yMax - yMin + pad * 2) * (bottom - top);
  const straight = visible.map(point => [scaleX(point.x), scaleY(point.y)]);
  const path = smoothPath(straight);
  const lastPt = straight[straight.length - 1];
  const y0 = scaleY(0);

  /* 数轴：5 条水平细线 + 紧凑数字；与零线重叠的刻度跳过 */
  const yTicks = Array.from({length: 5}, (_, index) => yMin + (yMax - yMin) * index / 4)
    .filter(value => Math.abs(scaleY(value) - y0) > 4);
  const xTicks = Array.from({length: 5}, (_, index) => xMin + (xMax - xMin) * index / 4);

  /* 转折带：先合并重叠窗口 */
  const merged = [];
  markers.slice().sort((a, b) => a.start - b.start).forEach(marker => {
    const last = merged[merged.length - 1];
    if (last && marker.start <= last.end) {
      last.end = Math.max(last.end, marker.end);
      last.delta = Math.abs(marker.delta) > Math.abs(last.delta) ? marker.delta : last.delta;
      return;
    }
    merged.push({...marker});
  });

  /* 领先方分色面积：在零线处把曲线切成段，蓝上红下 */
  const posQuads = [], negQuads = [];
  for (let i = 0; i < straight.length - 1; i += 1) {
    const a = straight[i], b = straight[i + 1];
    const aboveA = a[1] <= y0, aboveB = b[1] <= y0;
    if (aboveA === aboveB) {
      (aboveA ? posQuads : negQuads).push([a, b]);
    } else {
      const t = (y0 - a[1]) / (b[1] - a[1]);
      const m = [a[0] + (b[0] - a[0]) * t, y0];
      if (aboveA) { posQuads.push([a, m]); negQuads.push([m, b]); }
      else { negQuads.push([a, m]); posQuads.push([m, b]); }
    }
  }
  const quadsToPath = quads => quads.map(([a, b]) =>
    `M${a[0].toFixed(1)},${a[1].toFixed(1)}L${b[0].toFixed(1)},${b[1].toFixed(1)}`
    + `L${b[0].toFixed(1)},${y0.toFixed(1)}L${a[0].toFixed(1)},${y0.toFixed(1)}Z`).join('');

  const lastValue = visible[visible.length - 1].y;
  const pillText = (lastValue > 0 ? '+' : '') + fmtCompact(lastValue);
  const pillW = pillText.length * 7.2 + 14;
  const pillX = Math.min(right - pillW - 2, Math.max(left, lastPt[0] - pillW / 2));
  const pillY = Math.max(top + 2, lastPt[1] - 30);

  const plotPoints = visible.map(point => ({
    x: point.x, y: point.y, px: scaleX(point.x), py: scaleY(point.y),
  }));
  return `<div class="lc-wrap" data-xmax="${Math.round(xMax)}" data-points="${esc(JSON.stringify(plotPoints))}">
    <svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="经济差走势">
    ${yTicks.map(value => `<line x1="${left}" x2="${right}" y1="${scaleY(value)}" y2="${scaleY(value)}" stroke="var(--line-soft)" stroke-width="1"/>
      <text x="${left - 10}" y="${scaleY(value) + 3.5}" text-anchor="end" font-size="10.5" fill="var(--ink-4)" class="mono">${fmtCompact(value)}</text>`).join('')}
    ${xTicks.map(value => `<text x="${scaleX(value)}" y="${height - 8}" text-anchor="middle" font-size="10.5" fill="var(--ink-4)" class="mono">${fmtClock(value)}</text>`).join('')}
    ${merged.map(marker => {
      const x1 = scaleX(marker.start), x2 = Math.max(x1 + 2, scaleX(marker.end));
      const positive = (marker.delta || 0) > 0;
      const label = `转折 ${marker.delta > 0 ? '+' : ''}${fmtCompact(marker.delta)}`;
      // 右上角是单位文字的地盘，靠右的转折带不摆标注，避免打架
      const showLabel = x2 - x1 >= 64 && x2 < right - 150;
      return `<rect x="${x1.toFixed(1)}" y="${top}" width="${(x2 - x1).toFixed(1)}" height="${bottom - top}"
        fill="${positive ? 'var(--side-blue)' : 'var(--side-red)'}" opacity=".07"/>
        ${showLabel ? `<text x="${(x1 + 6).toFixed(1)}" y="${top + 13}" font-size="10" font-weight="600"
          fill="${positive ? 'var(--side-blue)' : 'var(--side-red)'}">${esc(label)}</text>` : ''}`;
    }).join('')}
    <line x1="${left}" x2="${right}" y1="${y0}" y2="${y0}" stroke="var(--ink-4)" stroke-dasharray="4 4" opacity=".75"/>
    ${y0 > top + 26 ? `<text x="${right}" y="${y0 - 6}" text-anchor="end" font-size="10" fill="var(--ink-4)">蓝方领先</text>` : ''}
    ${y0 < bottom - 12 ? `<text x="${right}" y="${y0 + 13}" text-anchor="end" font-size="10" fill="var(--ink-4)">红方领先</text>` : ''}
    <path d="${quadsToPath(posQuads)}" fill="var(--side-blue)" opacity=".10"/>
    <path d="${quadsToPath(negQuads)}" fill="var(--side-red)" opacity=".09"/>
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastPt[0].toFixed(1)}" cy="${lastPt[1].toFixed(1)}" r="3.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"/>
    <g><rect x="${pillX.toFixed(1)}" y="${pillY.toFixed(1)}" width="${pillW.toFixed(1)}" height="20" rx="5"
      fill="var(--ink)" opacity=".92"/>
      <text x="${(pillX + pillW / 2).toFixed(1)}" y="${(pillY + 14).toFixed(1)}" text-anchor="middle"
        font-size="11" font-weight="700" fill="#fff" class="mono">${esc(pillText)}</text></g>
    <text x="${right}" y="${top + 10}" text-anchor="end" font-size="10.5" fill="var(--ink-4)">${esc(unit)}</text>
  </svg><div class="lc-cross" hidden></div><div class="lc-dot" hidden></div><div class="lc-tip" hidden></div></div>`;
}

/* Catmull-Rom → 三次贝塞尔：温和平滑，不改变首尾点 */
function smoothPath(pts) {
  if (pts.length < 3) {
    return pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i += 1) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

/* 悬浮十字线 + 吸附圆点 + 时间数值：lineChart 渲染后调用一次；root 里可以有多个图。 */
export function bindLineChart(root) {
  root.querySelectorAll('.lc-wrap').forEach(wrap => {
    const svg = wrap.querySelector('svg');
    const cross = wrap.querySelector('.lc-cross');
    const dot = wrap.querySelector('.lc-dot');
    const tip = wrap.querySelector('.lc-tip');
    if (!svg || !cross || !tip || wrap.dataset.lcBound) return;
    wrap.dataset.lcBound = '1';
    let points = [];
    try { points = JSON.parse(wrap.dataset.points || '[]'); } catch (error) { points = []; }
    const hide = () => { cross.hidden = true; tip.hidden = true; if (dot) dot.hidden = true; };
    svg.addEventListener('mousemove', event => {
      if (!points.length) return hide();
      const rect = svg.getBoundingClientRect();
      const scale = 860 / rect.width;
      const vx = (event.clientX - rect.left) * scale;
      if (vx < 62 || vx > 842) return hide();
      let best = points[0];
      for (const point of points) {
        if (Math.abs(point.px - vx) < Math.abs(best.px - vx)) best = point;
      }
      const leftPct = best.px / 860 * 100;
      const topPct = Math.max(6, best.py / svg.viewBox.baseVal.height * 100);
      cross.hidden = false;
      cross.style.left = `${leftPct}%`;
      if (dot) {
        dot.hidden = false;
        dot.style.left = `${leftPct}%`;
        dot.style.top = `${best.py / svg.viewBox.baseVal.height * 100}%`;
      }
      tip.hidden = false;
      tip.style.left = `${leftPct}%`;
      tip.style.top = `${topPct}%`;
      tip.textContent = `${fmtClock(best.x)} · ${best.y > 0 ? '+' : ''}${num(best.y, 0)}`;
    });
    svg.addEventListener('mouseleave', hide);
  });
}

/* ---------------- 折叠证据（表格/长列表收进来，首屏给结论） ---------------- */
export function details(summary, body, {open = false, label = '查看完整数据'} = {}) {
  return `<details class="details"${open ? ' open' : ''}>
    <summary>${esc(label)}<span>${esc(summary)}</span></summary>
    <div class="details-body">${body}</div>
  </details>`;
}

/* 结论条：加粗数字 + 描述，一行一个发现 */
export function brief(items) {
  const rows = items.filter(item => item.text).map(item =>
    `<div class="brief-row"><b>${item.text}</b><span>${esc(item.note || '')}</span></div>`).join('');
  if (!rows) return '';
  return `<div class="brief-list">${rows}</div>`;
}
