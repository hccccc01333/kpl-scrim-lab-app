/* 深度分析单条页：基于营地十人面板 + 营地官方回放同步的可运行分析，
   作为各模块（比赛 / 战队 / 选手 / 英雄 / BP / 对比）子页签的独立页，
   每条分析呈现目的 / 深度 / 样本 / 图形 / 诚实边界。
   可分边的分析带「视角」选项框：全部 / 我方 / 对方（按对手战队）/ 对比。 */
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (v, d = 1) => v === null || v === undefined || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: d});
const signed = (v, d = 1) => v === null || v === undefined || !Number.isFinite(Number(v)) ? '—' : `${Number(v) > 0 ? '+' : ''}${fmt(v, d)}`;
const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const LANE_COLORS = ['#3b6ce8', '#2aa79b', '#e08a3c', '#7a6bd6', '#d95f6b', '#93a1b5'];
const DEPTH_COLOR = {D0: '#8a97a9', D1: '#7fa3e8', D2: '#3b6ce8', D3: '#2aa79b', D4: '#7a6bd6', D5: '#b9c2cf'};
const CAMP_COLOR = {'蓝': '#3b6ce8', '红': '#d95f6b'};
const SIDE_COLOR = {own: '#3b6ce8', opp: '#d95f6b'};
const LANE_INDEX = {'对抗路': 0, '中路': 1, '发育路': 2, '打野': 3, '游走': 4, '未标注': 5};
const laneColor = label => {
  const i = label in LANE_INDEX ? LANE_INDEX[label] : (Number(String(label).replace(/\D/g, '')) || 5);
  return LANE_COLORS[i] || LANE_COLORS[5];
};

function extent(values, zero = false) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (!clean.length) return [0, 1];
  let lo = Math.min(...clean), hi = Math.max(...clean);
  if (zero) lo = Math.min(0, lo);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * .06;
  return [lo - pad, hi + pad];
}
function axis(w, h, l, r, t, b, xd, yd, xfmt = fmt, yfmt = fmt) {
  let out = '';
  for (let i = 0; i <= 4; i++) {
    const y = h - b - (h - t - b) * i / 4, x = l + (w - l - r) * i / 4;
    out += `<line x1="${l}" x2="${w - r}" y1="${y}" y2="${y}" class="dp-grid"/>`;
    out += `<text x="${l - 9}" y="${y + 4}" text-anchor="end" class="dp-axis">${yfmt(yd[0] + (yd[1] - yd[0]) * i / 4)}</text>`;
    out += `<text x="${x}" y="${h - b + 20}" text-anchor="middle" class="dp-axis">${xfmt(xd[0] + (xd[1] - xd[0]) * i / 4)}</text>`;
  }
  return out;
}
const tip = text => ` data-tip="${esc(String(text).replace(/\s+/g, ' ').slice(0, 240))}"`;
/* 对局行的可读名：后端新字段 label 优先，旧数据继续用 id / game。 */
const gameLabel = item => {
  if (item === null || item === undefined) return '—';
  if (typeof item !== 'object') return String(item);
  return item.label || item.start || item.id || item.game || item.match || '—';
};

function matrix(payload, opts = {}) {
  const heroNames = opts.heroNames instanceof Set ? opts.heroNames : null;
  const isHeroCol = name => opts.boldCols === true || (heroNames ? heroNames.has(name) : false);
  const {rows, cols, cells, unit} = payload;
  const w = 980, cw = Math.min(74, Math.max(48, (w - 176) / cols.length)), ch = 42, l = 176, t = 62;
  const h = t + rows.length * ch + 46;
  const max = Math.max(1, ...cells.flat().map(c => c.value || 0));
  let out = `<svg viewBox="0 0 ${l + cols.length * cw + 20} ${h}" width="100%" class="dp-svg" role="img" aria-label="分路交叉矩阵">`;
  cols.forEach((c, j) => { out += `<text x="${l + j * cw + cw / 2}" y="${t - 12}" text-anchor="middle" class="dp-col-label${isHeroCol(c) ? ' dp-hero-name' : ''}">${esc(c.length > 5 ? c.slice(0, 5) : c)}</text>`; });
  rows.forEach((row, i) => {
    out += `<text x="${l - 12}" y="${t + i * ch + ch / 2 + 4}" text-anchor="end" class="dp-row-label">${esc(row)}</text>`;
    cells[i].forEach((cell, j) => {
      const x = l + j * cw + 2, y = t + i * ch + 2, cwv = cw - 4, chv = ch - 4;
      const v = cell.value, filled = v !== null && cell.n >= 3;
      const alpha = filled ? Math.min(1, Math.abs(v) / max) : 0;
      const bg = filled ? `rgba(59,108,232,${(.08 + alpha * .78).toFixed(3)})` : '#f3f6fb';
      const color = filled && alpha > .55 ? '#fff' : '#2a3a55';
      out += `<g${tip(`${row} × ${cols[j]}：${filled ? fmt(v) + ' ' + unit : '样本不足'} · n=${cell.n}`)}><rect x="${x}" y="${y}" width="${cwv}" height="${chv}" rx="5" fill="${bg}" ${filled ? '' : 'class="dp-hatch"'}/><text x="${x + cwv / 2}" y="${y + chv / 2 + 4}" text-anchor="middle" class="dp-cell" fill="${color}">${filled ? fmt(v, v >= 100 ? 0 : 1) : '—'}</text>${cell.n && cell.n < 3 ? `<text x="${x + cwv - 5}" y="${y + 11}" text-anchor="end" class="dp-cell-n">${cell.n}</text>` : ''}</g>`;
    });
  });
  out += `<text x="${l}" y="${h - 12}" class="dp-axis">颜色越深数值越高 · 斜纹格样本太少，不作参考</text></svg>`;
  const extras = payload.laneStats ? `<div class="dp-inline-stats">${payload.laneStats.map(s => `<div><span>${esc(s.label)}</span><b>${fmt(s.median)}</b><small>${s.n} 行</small></div>`).join('')}</div>` : '';
  const items = payload.items ? `<div class="dp-inline-bars">${payload.items.slice(0, 10).map(i => `<div class="dp-inline-bar"><span>${esc(i.label)}</span><i style="width:${Math.min(100, i.pct * 2)}%"></i><b>${i.count}</b></div>`).join('')}</div>` : '';
  return `<div class="dp-scroll">${out}</div>${extras}${items}`;
}

function scatter(payload, compact = false) {
  const pts = (payload.points || []).filter(p => Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)));
  const w = compact ? 460 : 860, h = compact ? 330 : 420, l = 62, r = 24, t = 22, b = 52;
  if (!pts.length) return '<div class="dp-empty">该指标组合下没有同时有效的样本。</div>';
  const xd = extent(pts.map(p => p.x)), yd = extent(pts.map(p => p.y));
  const X = v => l + (v - xd[0]) / (xd[1] - xd[0]) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="散点图">${axis(w, h, l, r, t, b, xd, yd)}`;
  if (payload.ref) {
    if (Number.isFinite(payload.ref.x)) out += `<line x1="${X(payload.ref.x)}" x2="${X(payload.ref.x)}" y1="${t}" y2="${h - b}" class="dp-median"/>`;
    if (Number.isFinite(payload.ref.y)) out += `<line x1="${l}" x2="${w - r}" y1="${Y(payload.ref.y)}" y2="${Y(payload.ref.y)}" class="dp-median"/>`;
  }
  pts.forEach(p => {
    const c = p.group ? laneColor(p.group) : '#3b6ce8';
    out += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${compact ? 4.2 : 5.2}" fill="${c}" fill-opacity=".68" stroke="${c}"${tip(`${p.label} · ${p.group || ''} · X ${fmt(p.x)} · Y ${fmt(p.y)}${p.detail ? ' · ' + p.detail : ''}`)}/>`;
  });
  const groups = [...new Set(pts.map(p => p.group).filter(Boolean))].sort();
  out += `<text x="${l}" y="${h - 8}" class="dp-axis">${esc(payload.xLabel || '')} →</text><text x="${l - 44}" y="${t - 6}" class="dp-axis">${esc(payload.yLabel || '')}</text></svg>`;
  const legend = groups.map(g => `<span><i style="background:${laneColor(g)}"></i>${esc(g)}</span>`).join('');
  return `${out}<div class="dp-legend">${legend}<span class="dp-legend-note">${pts.length} 个样本 · 虚线 = 平均线${payload.corr != null ? ` · 同步程度 r = ${fmt(payload.corr, 2)}` : ''}</span></div>`;
}

function chain(payload) {
  const lanes = payload.lanes || [];
  const max = Math.max(1, ...lanes.map(l => l.p90 || 0));
  const laneBars = `<div class="dp-lane-bars">${lanes.map(l => `<div class="dp-lane-row"><span>${esc(l.label)}<small>${l.n} 行</small></span><div class="dp-lane-track">
    <i class="dp-lane-range" style="left:${(l.p25 || 0) / max * 100}%;width:${Math.max(0, ((l.p75 || 0) - (l.p25 || 0)) / max * 100)}%"></i>
    <i class="dp-lane-p90" style="left:${(l.p90 || 0) / max * 100}%"></i>
    <i class="dp-lane-median" style="left:${(l.p50 || 0) / max * 100}%"></i>
    <b style="left:${Math.min(97, (l.p90 || 0) / max * 100)}%">P90 ${fmt(l.p90, 0)}</b></div></div>`).join('')}</div>`;
  return `<div class="dp-chain">${payload.links.map(link => `<section class="dp-chain-card"><h3>${esc(link.title)}<small>r = ${fmt(link.corr, 2)}</small></h3>${scatter(link, true)}</section>`).join('')}</div>
    <div class="dp-subhead">补刀的分路分布 <span>粗带 = 一半人的区间 · 竖线 = 平均值 · 刻度 = 前列水平</span></div>${laneBars}`;
}

function impact(payload) {
  const labels = payload.metricLabels || {}, rows = payload.rows || [];
  const keys = Object.keys(labels);
  const head = keys.map(k => `<th>${esc(labels[k])}<small>携带 / 未携带 / 差</small></th>`).join('');
  const body = rows.map(r => `<tr><th>${esc(r.label)}<small>${r.withN} / ${r.withoutN} 人</small></th>${keys.map(k => {
    const d = r.deltas[k] || {}, v = d.delta;
    const tone = v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '';
    return `<td><div class="dp-impact-cell"><span>${fmt(d.with, 2)} <em>/</em> ${fmt(d.without, 2)}</span><b class="${tone}">${signed(v, 2)}</b></div></td>`;
  }).join('')}</tr>`).join('');
  const biggest = rows.map(r => ({label: r.label, v: r.deltas[keys[0]]?.delta})).filter(x => x.v != null).sort((a, b) => b.v - a.v);
  return `<div class="dp-finding"><b>带 ${esc(payload.metricLabels?.[keys[0]] || '')}差异最明显的是：${esc(biggest[0]?.label || '—')} ${signed(biggest[0]?.v, 2)}</b><span>两组平均水平的差，不能当装备因果</span></div>
    <div class="dp-scroll"><table class="dp-table dp-impact-table"><thead><tr><th>装备 <small>样本</small></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function timeline(payload) {
  const games = (payload.games || []).filter(g => g.avgGpm !== null);
  const w = 980, h = 250, l = 62, r = 24, t = 24, b = 46;
  const yd = extent(games.map(g => g.avgGpm)), xd = [0, Math.max(1, games.length - 1)];
  const X = i => l + i / Math.max(1, games.length - 1) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="逐局节奏">${axis(w, h, l, r, t, b, xd, yd, v => `第 ${Math.round(v) + 1} 局`, v => fmt(v, 0))}`;
  out += `<path d="${games.map((g, i) => `${i ? 'L' : 'M'}${X(i)},${Y(g.avgGpm)}`).join(' ')}" fill="none" stroke="#3b6ce8" stroke-width="2.4"/>`;
  games.forEach((g, i) => out += `<circle cx="${X(i)}" cy="${Y(g.avgGpm)}" r="4" fill="#3b6ce8"${tip(`${gameLabel(g)} · ${fmt(g.duration ? g.duration / 60 : null)} 分 · 分均经济 ${fmt(g.avgGpm, 0)} · 补刀 ${fmt(g.avgCs, 0)}`)}/>`);
  out += `</svg>`;
  const hours = payload.hours || [], maxH = Math.max(1, ...hours.map(x => x.count));
  const hourBars = hours.map(x => `<div class="dp-hour"><span>${x.hour}时</span><i style="height:${Math.max(3, x.count / maxH * 74)}px"></i><b>${x.count}</b></div>`).join('');
  return `<div class="dp-subhead">逐局分均经济 <span>${games.length} 局按开始时刻排序</span></div>${out}
    <div class="dp-two-col"><section><div class="dp-subhead">对局时段分布 <span>营地 startTime 的小时</span></div><div class="dp-hours">${hourBars}</div></section>
    <section><div class="dp-subhead">时长 × 产出效率 <span>r = ${fmt(payload.scatter?.corr, 2)}</span></div>${scatter(payload.scatter || {points: []}, true)}</section></div>`;
}

function economy(payload) {
  const curves = payload.curves || [], grid = payload.grid || [], marks = payload.landmarks || [];
  const all = curves.flatMap(c => c.points.map(p => p[1]));
  const yd = extent(all, true), maxT = Math.max(1, ...curves.map(c => c.duration || 0));
  const tiles = curves.map(c => {
    const w = 210, h = 74, l = 4, r = 4, t = 8, b = 8;
    const X = v => l + v / maxT * (w - l - r);
    const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
    const last = c.points.at(-1)?.[1] || 0;
    const color = last >= 0 ? '#3b6ce8' : '#d95f6b';
    return `<div class="dp-spark"${tip(`${gameLabel(c)} · 时长 ${clock(c.duration || 0)} · 末次经济差 ${fmt(last, 0)}`)}><span>${esc(gameLabel(c))} <small>${clock(c.duration || 0)}</small></span>
      <svg viewBox="0 0 ${w} ${h}" width="100%"><line x1="${l}" x2="${w - r}" y1="${Y(0)}" y2="${Y(0)}" class="dp-median"/>
      <path d="${c.points.map((p, i) => `${i ? 'L' : 'M'}${X(p[0])},${Y(p[1])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="1.9"/></svg></div>`;
  }).join('');
  const maxAbs = Math.max(1, ...grid.flatMap(g => marks.map(m => Math.abs(g.diffAt[m] || 0))));
  const table = `<div class="dp-scroll"><table class="dp-table dp-landmark-table"><thead><tr><th>对局</th>${marks.map(m => `<th>${m / 60} 分</th>`).join('')}<th>胜方</th></tr></thead><tbody>${grid.map(g => {
    const name = gameLabel(g);
    return `<tr><th>${esc(name)}</th>${marks.map(m => {
      const v = g.diffAt[m];
      return `<td class="${v == null ? 'dp-missing' : ''}" style="${v == null ? '' : `background:${v >= 0 ? `rgba(59,108,232,${.06 + Math.abs(v) / maxAbs * .5})` : `rgba(217,95,107,${.06 + Math.abs(v) / maxAbs * .5})`}`}"${tip(`${name} · ${m / 60} 分 · 蓝−红 ${fmt(v, 0)}`)}>${signed(v, 0)}</td>`;
    }).join('')}<td${tip(`${name} · 胜方 ${g.winCamp === '1' ? '蓝方' : g.winCamp === '2' ? '红方' : '未记录'}`)}>${g.winCamp === '1' ? '蓝' : g.winCamp === '2' ? '红' : '—'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
  const lead = payload.leadAt10 || {};
  return `<div class="dp-finding"><b>10 分钟检查点：${lead.n || 0} 局有实测，其中蓝方领先 ${lead.blueLead || 0} 局，最终蓝方获胜 ${lead.blueLeadWins || 0} 局</b><span>只看已覆盖的检查点，不外推到终局</span></div>
    <div class="dp-subhead">${curves.length} 局经济差过程 <span>同一纵轴 · 蓝线为蓝方领先、红线为落后 · 30 秒一个实测点</span></div><div class="dp-sparks">${tiles}</div>
    <div class="dp-subhead">检查点矩阵 <span>蓝 − 红 · 深色 = 差距大 · — = 该时点没有数据</span></div>${table}`;
}

function events(payload) {
  const colors = ['#3b6ce8', '#2aa79b', '#e08a3c', '#7a6bd6', '#d95f6b'];
  const names = payload.names || [], minutes = payload.minutes || [];
  const w = 980, h = 280, l = 60, r = 20, t = 22, b = 44;
  const max = Math.max(1, ...minutes.map(m => names.reduce((s, k) => s + (m.values[k] || 0), 0)));
  const bw = (w - l - r) / Math.max(1, minutes.length) - 2;
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="事件密度">${axis(w, h, l, r, t, b, [0, minutes.length], [0, max], v => `${Math.round(v)} 分`, v => fmt(v, 0))}`;
  minutes.forEach((m, i) => {
    let acc = 0;
    names.forEach((k, j) => {
      const v = m.values[k] || 0; if (!v) return;
      const hh = v / max * (h - t - b), y = h - b - acc / max * (h - t - b) - hh;
      out += `<rect x="${l + i * (bw + 2)}" y="${y}" width="${bw}" height="${hh}" fill="${colors[j % colors.length]}"${tip(`${m.minute}:00 · ${k} · ${v} 次`)}/>`;
      acc += v;
    });
  });
  out += `</svg><div class="dp-legend">${names.map((k, j) => `<span><i style="background:${colors[j % colors.length]}"></i>${esc(k)} · ${fmt(payload.totals?.[k] || 0, 0)} 条</span>`).join('')}</div>`;
  const swings = payload.swings || [];
  const positive = swings.filter(s => s.delta > 0).length;
  const rows = swings.slice(0, 24).map(s => `<tr><td>${esc(gameLabel(s))}</td><td>${clock(s.t)}</td><td>${esc(s.type)}</td><td>${s.camp === '1' ? '蓝' : s.camp === '2' ? '红' : '—'}</td><td>${signed(s.before, 0)}</td><td>${signed(s.after, 0)}</td><td class="${s.delta >= 0 ? 'pos' : 'neg'}">${signed(s.delta, 0)}</td></tr>`).join('');
  return `${out}<div class="dp-finding"><b>${payload.swingCount || 0} 个资源事件可算前后 swing，其中 ${positive} 个事件后经济差上行</b><span>时间关联，不是资源导致经济的证据</span></div>
    <div class="dp-subhead">事件前后 60 秒经济差变化 <span>前 24 条</span></div><div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>时刻</th><th>事件</th><th>触发方</th><th>前 60s</th><th>后 60s</th><th>变化</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function map(payload) {
  const bounds = payload.bounds || [-60, 60], size = 600, pad = 26;
  const S = v => pad + (v - bounds[0]) / (bounds[1] - bounds[0]) * (size - pad * 2);
  const heat = payload.heat || [], maxHeat = Math.max(1, ...heat.map(h => h.n));
  const cell = S(10) - S(0);
  let out = `<div class="dp-map-tools"><label>轨迹对局 <select data-game-select>${(payload.games || []).map(g => `<option value="${esc(g.id)}"${g.id === payload.selected ? ' selected' : ''}>${esc(gameLabel(g))} · ${clock(g.duration || 0)}</option>`).join('')}</select></label>
    <div class="dp-map-actions"><button data-track-all="default">默认 2 人</button><button data-track-all="show">全部显示</button><button data-track-all="hide">只看热区</button></div><span>橙色热区 = 全部对局聚合 · 蓝红轨迹 = 所选对局</span></div>`;
  out += `<div class="dp-map-layout"><div class="dp-map-canvas"><svg viewBox="0 0 ${size} ${size}" width="100%" class="dp-svg" role="img" aria-label="战场热区与轨迹">`;
  out += `<rect x="${pad}" y="${pad}" width="${size - pad * 2}" height="${size - pad * 2}" rx="10" fill="#f8fafd" stroke="#dfe6f2"/>`;
  for (let g = -40; g <= 40; g += 20) {
    out += `<line x1="${S(g)}" x2="${S(g)}" y1="${pad}" y2="${size - pad}" stroke="#e9eef7"/><line x1="${pad}" x2="${size - pad}" y1="${S(g)}" y2="${S(g)}" stroke="#e9eef7"/>`;
  }
  out += `<path d="M${S(-55)},${S(55)} L${S(55)},${S(-55)}" stroke="#cbd6e8" stroke-dasharray="5 5" fill="none"/>`;
  out += `<path d="M${S(-55)},${S(-55)} L${S(55)},${S(55)}" stroke="#e6ebf4" fill="none"/>`;
  heat.forEach(h => out += `<rect x="${S(h.x)}" y="${S(h.y)}" width="${cell.toFixed(1)}" height="${cell.toFixed(1)}" fill="#e08a3c" opacity="${(.06 + h.n / maxHeat * .58).toFixed(3)}"${tip(`网格 (${h.x}, ${h.y}) · ${h.n.toLocaleString('zh-CN')} 个逐秒位置点`)}/>`);
  out += `<g id="dp-tracks">${(payload.tracks || []).map((tr, i) => `<path data-track="${i}" d="${(tr.points || []).map((p, k) => `${k ? 'L' : 'M'}${S(p[0])},${S(p[1])}`).join(' ')}" fill="none" stroke="${CAMP_COLOR[tr.camp] || '#3b6ce8'}" stroke-width="0.9" stroke-linejoin="round" opacity=".32"${i >= 2 ? ' style="display:none"' : ''}/>`).join('')}</g>`;
  out += `<circle cx="${S(-50)}" cy="${S(-50)}" r="6" fill="#3b6ce8"/><circle cx="${S(50)}" cy="${S(50)}" r="6" fill="#d95f6b"/><text x="${S(-50) + 10}" y="${S(-50) - 8}" class="dp-axis">蓝方基地</text><text x="${S(50) - 10}" y="${S(50) + 18}" text-anchor="end" class="dp-axis">红方基地</text></svg></div>`;
  out += `<aside class="dp-map-side"><div class="dp-subhead">轨迹图层 <span>默认 2 人，点击开关</span></div><div class="dp-track-legend">${(payload.tracks || []).map((tr, i) => `<button class="dp-track-toggle ${i < 2 ? 'active' : 'off'}" data-track-toggle="${i}"><i style="background:${CAMP_COLOR[tr.camp] || '#3b6ce8'}"></i>${esc(tr.hero || tr.label)}<small>${esc(tr.lane)} · ${tr.points.length} 点</small></button>`).join('')}</div>
    <div class="dp-finding"><b>${(payload.tracks || []).length} 人走位 · ${(payload.tracks || []).reduce((s, t) => s + t.points.length, 0).toLocaleString('zh-CN')} 个位置点</b><span>蓝 / 红按阵营着色；每秒一个位置点</span></div></aside></div>`;
  return out;
}

function lanespace(payload) {
  const rows = payload.rows || [];
  const w = 860, l = 130, r = 90, h = 60 + rows.length * 46;
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="分路推进深度">`;
  rows.forEach((row, i) => {
    const y = 34 + i * 46, c = laneColor(row.lane);
    out += `<text x="${l - 12}" y="${y + 13}" text-anchor="end" class="dp-row-label">${esc(row.lane)}<tspan class="dp-axis"> · ${row.players} 人</tspan></text>`;
    out += `<line x1="${l}" x2="${w - r}" y1="${y + 8}" y2="${y + 8}" stroke="#e9eef7" stroke-width="8" stroke-linecap="round"/>`;
    out += `<line x1="${l}" x2="${l + (w - r - l) * .5}" y1="${y + 8}" y2="${y + 8}" stroke="#dfe6f2" stroke-width="8" stroke-linecap="round"/>`;
    const x = l + (w - r - l) * row.depth;
    out += `<rect x="${l + (w - r - l) * row.p10}" y="${y + 3}" width="${Math.max(2, (w - r - l) * (row.p90 - row.p10))}" height="10" rx="4" fill="${c}" opacity=".22"${tip(`${row.lane} · P10 ${fmt(row.p10, 2)} / P90 ${fmt(row.p90, 2)}`)}/>`;
    out += `<circle cx="${x}" cy="${y + 8}" r="6" fill="${c}"${tip(`${row.lane} · 平均推进深度 ${fmt(row.depth, 2)} · 活动离散 ${fmt(row.spread, 2)} · 过河道 ${fmt(row.crossings, 1)} 次`)}/>`;
    out += `<text x="${w - r + 10}" y="${y + 12}" class="dp-axis">${fmt(row.depth, 2)} · ${fmt(row.crossings, 1)} 次</text>`;
  });
  out += `<text x="${l}" y="${h - 8}" class="dp-axis">0 = 自家基地 → 0.5 河道 → 1 = 敌方基地 · 浅带 = 常见活动范围</text></svg>`;
  return `${out}<div class="dp-scroll"><table class="dp-table"><thead><tr><th>分路</th><th>人局数</th><th>平均推进深度</th><th>活动离散度</th><th>平均过河道</th><th>P10</th><th>P90</th></tr></thead><tbody>${rows.map(r => `<tr><th>${esc(r.lane)}</th><td>${r.players}</td><td>${fmt(r.depth, 3)}</td><td>${fmt(r.spread, 3)}</td><td>${fmt(r.crossings, 1)}</td><td>${fmt(r.p10, 3)}</td><td>${fmt(r.p90, 3)}</td></tr>`).join('')}</tbody></table></div>`;
}

function pace(payload) {
  const phases = payload.phases || [];
  const cards = phases.map(p => `<div class="dp-phase"><span>${esc(p.phase)}</span><b>${fmt(p.depth, 3)}</b><small>平均推进深度</small><div><em>${fmt(p.spread, 1)}</em> 格平均离散 · ${p.samples} 次采样</div></div>`).join('');
  const series = payload.series || [];
  const all = series.flatMap(s => s.points);
  const w = 860, h = 300, l = 62, r = 24, t = 24, b = 46;
  const xd = extent(all.map(p => p[0])), yd = extent(all.map(p => p[1]));
  const X = v => l + (v - xd[0]) / (xd[1] - xd[0]) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="分路推进深度随时间">${axis(w, h, l, r, t, b, xd, yd, v => `${Math.round(v)} 分`, v => fmt(v, 2))}`;
  out += `<line x1="${l}" x2="${w - r}" y1="${Y(.5)}" y2="${Y(.5)}" class="dp-median"/>`;
  series.forEach(s => {
    const c = laneColor(s.label);
    out += `<path d="${s.points.map((p, i) => `${i ? 'L' : 'M'}${X(p[0])},${Y(p[1])}`).join(' ')}" fill="none" stroke="${c}" stroke-width="2.2"/>`;
    s.points.forEach(p => out += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="3.2" fill="${c}"${tip(`${s.label} · 第 ${p[0]} 分 · 深度 ${fmt(p[1], 2)}`)}/>`);
  });
  out += `</svg><div class="dp-legend">${series.map(s => `<span><i style="background:${laneColor(s.label)}"></i>${esc(s.label)}</span>`).join('')}<span class="dp-legend-note">虚线为河道（0.5）</span></div>`;
  return `<div class="dp-phases">${cards}</div><div class="dp-subhead">各分路推进深度随比赛时间 <span>每分钟一条 = 该分路所有对局的平均位置</span></div>${out}`;
}

function baseline(payload) {
  const rows = payload.rows || [];
  const max = Math.max(1, ...rows.map(r => Math.max(r.value || 0, r.p90 || 0)));
  const P = v => Math.min(98, (v || 0) / max * 100);
  return `<div class="dp-baseline"><div class="dp-baseline-head"><span>身份 / 分路</span><span>样本</span><span>${esc(payload.metric)} · 相对同位置平均</span><span>分位</span></div>
  ${rows.map(r => `<div class="dp-baseline-row"><div><b>${esc(r.player)}</b><small>${esc(r.lane)} · ${esc((r.heroes || []).join(' / ') || '—')}</small></div><span class="dp-num">${r.n}</span>
    <div class="dp-bullet"><i class="dp-bullet-p75" style="left:${P(r.p75)}%;width:${Math.max(0, P(r.p90) - P(r.p75))}%"></i><i class="dp-bullet-base" style="left:${P(r.baseline)}%"></i><i class="dp-bullet-value" style="left:${P(r.value)}%"${tip(`${r.player} · 本人 ${fmt(r.value)} · 同位置平均 ${fmt(r.baseline)} · 前列区间 ${fmt(r.p75)}–${fmt(r.p90)}`)}></i></div>
    <span class="dp-num">${r.percentile === null ? '—' : fmt(r.percentile, 0) + '%'}</span></div>`).join('')}</div>
  <div class="dp-legend"><span><i style="background:#c9d8f5"></i>同位置前列区间</span><span><i style="background:#8a97a9"></i>同位置平均</span><span><i style="background:#3b6ce8"></i>本人</span></div>`;
}

function camp(payload) {
  const rows = payload.rows || [];
  const max = Math.max(1, ...rows.flatMap(r => [r.blue || 0, r.red || 0]));
  const bars = rows.map(r => `<div class="dp-camp-row"><span>${esc(r.label)}<small>${r.blueN} / ${r.redN} 人</small></span>
    <div class="dp-camp-bars"><div><i style="width:${(r.blue || 0) / max * 100}%"></i><b>${fmt(r.blue, 0)}</b></div><div><i class="red" style="width:${(r.red || 0) / max * 100}%"></i><b>${fmt(r.red, 0)}</b></div></div>
    <b class="${(r.deltaPct || 0) >= 0 ? 'pos' : 'neg'}">${signed(r.deltaPct, 1)}%</b></div>`).join('');
  const diffs = (payload.byMatch || []).filter(d => d.diff !== null);
  return `<div class="dp-legend"><span><i style="background:#3b6ce8"></i>蓝方平均水平</span><span><i style="background:#d95f6b"></i>红方平均水平</span><span class="dp-legend-note">最右为蓝相对红的差异 %</span></div>${bars}
    <div class="dp-subhead">逐局团队经济差 <span>蓝 − 红 · ${diffs.length} 局</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>蓝方</th><th>红方</th><th>差值</th></tr></thead><tbody>${diffs.slice(0, 18).map(d => `<tr><th>${esc(gameLabel(d))}</th><td>${fmt(d.blue, 0)}</td><td>${fmt(d.red, 0)}</td><td class="${d.diff >= 0 ? 'pos' : 'neg'}">${signed(d.diff, 0)}</td></tr>`).join('')}</tbody></table></div>`;
}

function bp(payload) {
  const bars = (list, color) => list.map(i => `<div class="dp-inline-bar"><span>${esc(i.label)}</span><i style="width:${Math.min(100, i.value / Math.max(1, list[0].value) * 100)}%;background:${color}"></i><b>${i.value}</b></div>`).join('');
  const objs = payload.objectives || [];
  const withResult = objs.filter(o => o.result !== null && o.result !== undefined);
  return `<div class="dp-two-col"><section><div class="dp-subhead">禁用频率 <span>队侧 ${objs.length} 份</span></div>${bars(payload.bans || [], '#d95f6b')}</section>
  <section><div class="dp-subhead">选用频率 <span>队侧 ${objs.length} 份</span></div>${bars(payload.picks || [], '#3b6ce8')}</section></div>
  <div class="dp-subhead">龙与塔控制 <span>终局计数</span></div>
  <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>阵营</th><th>推塔</th><th>资源计数</th><th>团队经济</th><th>赛果字段</th></tr></thead><tbody>${objs.slice(0, 14).map(o => `<tr><td>${esc(gameLabel(o))}</td><td>${esc(o.camp)}</td><td>${fmt(o.towers, 0)}</td><td>${fmt(o.dragons, 0)}</td><td>${fmt(o.money, 0)}</td><td>${o.result == null ? '—' : esc(o.result)}</td></tr>`).join('')}</tbody></table></div>
  <div class="dp-finding"><b>${withResult.length} / ${objs.length} 个队侧有胜负字段</b><span>资源与胜负的关系只做描述，不做统计推断</span></div>`;
}

function stability(payload) {
  const rows = payload.rows || [], max = Math.max(1, ...rows.map(r => r.ceiling || 0));
  const P = v => (v || 0) / max * 100;
  return `<div class="dp-baseline"><div class="dp-baseline-head"><span>英雄</span><span>样本</span><span>${esc(payload.metric)} 逐局分布 · 最差 → 最好</span><span>波动</span></div>
  ${rows.map(r => `<div class="dp-baseline-row"><div><b class="dp-hero-name">${esc(r.label)}</b><small>平均 ${fmt(r.mean, 2)} · 中位局 ${fmt(r.p50, 2)}</small></div><span class="dp-num">${r.n}</span>
    <div class="dp-bullet"><i class="dp-bullet-range" style="left:${P(r.p10)}%;width:${Math.max(1, P(r.p90) - P(r.p10))}%"></i><i class="dp-bullet-extreme" style="left:${P(r.floor)}%"></i><i class="dp-bullet-extreme" style="left:${P(r.ceiling)}%"></i><i class="dp-bullet-value" style="left:${P(r.p50)}%"${tip(`${r.label} · 最差 ${fmt(r.floor, 2)} · 常见 ${fmt(r.p10, 2)}–${fmt(r.p90, 2)} · 中位局 ${fmt(r.p50, 2)} · 最好 ${fmt(r.ceiling, 2)}`)}></i></div>
    <span class="dp-num">${fmt(r.sd, 2)}</span></div>`).join('')}</div>
  <div class="dp-legend"><span><i style="background:#c9d8f5"></i>常见区间</span><span><i style="background:#8a97a9"></i>最差 / 最好局</span><span><i style="background:#3b6ce8"></i>中位局</span></div>`;
}

function killrhythm(payload) {
  const minutes = payload.minutes || [], phases = payload.phases || [];
  const w = 980, h = 252, l = 56, r = 20, t = 18, b = 44;
  const lo = Math.min(0, ...minutes.map(m => m.minute));
  const hi = Math.max(1, ...minutes.map(m => m.minute)) + 1;
  const X = m => l + (m - lo) / (hi - lo) * (w - l - r);
  const max = Math.max(1, ...minutes.map(m => m.blue + m.red));
  const bw = Math.max(2, (w - l - r) / Math.max(1, hi - lo) - 2);
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="逐次击杀分钟分布">${axis(w, h, l, r, t, b, [lo, hi], [0, max], v => `${Math.round(v)} 分`, v => fmt(v, 0))}`;
  minutes.forEach(m => {
    let acc = 0;
    [['blue', '#3b6ce8', '蓝方'], ['red', '#d95f6b', '红方']].forEach(([key, color, label]) => {
      const v = m[key] || 0;
      if (!v) return;
      const hh = v / max * (h - t - b);
      out += `<rect x="${X(m.minute)}" y="${h - b - acc / max * (h - t - b) - hh}" width="${bw}" height="${hh}" fill="${color}"${tip(`${m.minute}:00 · ${label}击杀 ${v} 次`)}/>`;
      acc += v;
    });
  });
  out += `</svg><div class="dp-legend"><span><i style="background:#3b6ce8"></i>蓝方击杀</span><span><i style="background:#d95f6b"></i>红方击杀</span><span class="dp-legend-note">每一格 = 1 分钟 · 数据为实测击杀时刻，不是按总比分摊平</span></div>`;
  const fb = payload.firstBlood || {};
  const headline = `<div class="dp-finding"><b>首杀常见在 ${clock(fb.p25 || 0)} – ${clock(fb.p75 || 0)}，平均水平 ${clock(fb.median || 0)}（${fb.n || 0} 局）</b><span>60 秒内 ≥3 杀的爆发窗口共 ${fmt(payload.burstCount, 0)} 个</span></div>`;
  const phaseCards = `<div class="dp-inline-stats">${phases.map(p => `<div><span>${esc(p.label)}</span><b>${fmt(p.n, 0)} 次</b><small>占 ${fmt(p.pct)}% · ${fmt(p.rate, 2)} 杀/分</small></div>`).join('')}</div>`;
  const sizes = payload.sizes || [], maxSize = Math.max(1, ...sizes.map(s => s.fights));
  const sizeBars = `<div class="dp-inline-bars">${sizes.map(s => `<div class="dp-inline-bar"><span>${fmt(s.kills, 0)} 杀团战</span><i style="width:${s.fights / maxSize * 100}%"></i><b>${s.fights}</b></div>`).join('')}</div>`;
  const burstRows = (payload.bursts || []).slice(0, 14).map(b => `<tr><td>${esc(gameLabel(b))}</td><td>${clock(b.t)}</td><td><b>${fmt(b.n, 0)}</b></td><td>${b.n >= 5 ? '高强度' : '交火密集'}</td></tr>`).join('');
  const ledgerRows = (payload.ledger || []).map(k => `<tr><td>${esc(gameLabel(k))}</td><td>${clock(k.t)}</td><td><span class="dp-camp-dot ${k.camp === '蓝' ? 'blue' : 'red'}"></span>${esc(k.killer)}</td><td>→</td><td>${esc(k.victim)}</td><td>${esc(k.fight)}</td></tr>`).join('');
  return `${headline}${out}${phaseCards}
    <div class="dp-two-col"><div><div class="dp-subhead">团战规模分布 <span>每场团战的击杀数</span></div>${sizeBars}</div>
    <div><div class="dp-subhead">爆发窗口 Top 14 <span>单局单分钟击杀数</span></div><div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>时刻</th><th>击杀</th><th>标记</th></tr></thead><tbody>${burstRows || '<tr><td colspan="4">无</td></tr>'}</tbody></table></div></div></div>
    <div class="dp-subhead">逐次击杀流水 <span>前 30 条 · 「谁击杀谁」来自官方 killInfo</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>时刻</th><th>击杀者</th><th></th><th>被击杀</th><th>团战</th></tr></thead><tbody>${ledgerRows || '<tr><td colspan="6">无</td></tr>'}</tbody></table></div>`;
}

function fightscatter(payload) {
  const pts = (payload.points || []).filter(p => Number.isFinite(Number(p.hurt)) && Number.isFinite(Number(p.taken)));
  if (!pts.length) return '<div class="dp-empty">没有达到参团次数门槛的英雄。</div>';
  const w = 880, h = 400, l = 66, r = 24, t = 22, b = 52;
  const xd = extent(pts.map(p => p.hurt)), yd = extent(pts.map(p => p.taken));
  const X = v => l + (v - xd[0]) / (xd[1] - xd[0]) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  const med = payload.medians || {};
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="团战输出承伤散点">${axis(w, h, l, r, t, b, xd, yd, v => fmt(v, 0), v => fmt(v, 0))}`;
  if (Number.isFinite(med.hurt)) out += `<line x1="${X(med.hurt)}" x2="${X(med.hurt)}" y1="${t}" y2="${h - b}" class="dp-median"/>`;
  if (Number.isFinite(med.taken)) out += `<line x1="${l}" x2="${w - r}" y1="${Y(med.taken)}" y2="${Y(med.taken)}" class="dp-median"/>`;
  pts.forEach(p => {
    const c = CAMP_COLOR[p.camp] || '#3b6ce8';
    out += `<circle cx="${X(p.hurt)}" cy="${Y(p.taken)}" r="${(4 + Math.sqrt(p.n) * 1.05).toFixed(1)}" fill="${c}" fill-opacity=".58" stroke="${c}"${tip(`${p.hero} · ${p.camp}方 · 参团 ${p.n} 次 · 场均输出 ${fmt(p.hurt, 0)} · 场均承伤 ${fmt(p.taken, 0)} · 控制 ${fmt(p.ctrl, 0)} · 支援率 ${fmt(p.supportRate)}%`)}/>`;
  });
  out += `<text x="${l}" y="${h - 8}" class="dp-axis">团战场均输出 →</text><text x="${l - 50}" y="${t - 6}" class="dp-axis">场均承伤 →</text></svg>`;
  out += `<div class="dp-legend"><span><i style="background:#3b6ce8"></i>蓝方多数</span><span><i style="background:#d95f6b"></i>红方多数</span><span class="dp-legend-note">${pts.length} 个英雄 · 点越大参团越多 · 虚线 = 平均线 · 参团少于 5 次的 ${fmt(payload.excluded, 0)} 个英雄未画入</span></div>`;
  const rows = (payload.table || []).map(p => `<tr><th>${esc(p.hero)}<small>${p.camp}方 · 参团 ${p.n}</small></th><td>${fmt(p.hurt, 0)}</td><td>${fmt(p.taken, 0)}</td><td>${fmt(p.ctrl, 0)}</td><td>${fmt(p.supportRate)}%</td><td>${fmt(p.kills, 0)}/${fmt(p.deaths, 0)}/${fmt(p.assists, 0)}</td><td>${fmt(p.firstWin)}%</td></tr>`).join('');
  return `${out}<div class="dp-subhead">团战贡献表 <span>按场均输出排序 · Top 16</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>英雄</th><th>输出</th><th>承伤</th><th>控制</th><th>支援率</th><th>K/D/A</th><th>先手同阵营</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function deathmap(payload) {
  const bounds = payload.bounds || [-60, 60], size = 560, pad = 26;
  const S = v => pad + (v - bounds[0]) / (bounds[1] - bounds[0]) * (size - pad * 2);
  const heat = payload.heat || [], maxHeat = Math.max(1, ...heat.map(h => h.n));
  const cell = S(10) - S(0);
  let out = `<div class="dp-map-canvas"><svg viewBox="0 0 ${size} ${size}" width="100%" class="dp-svg" role="img" aria-label="死亡位置热区">`;
  out += `<rect x="${pad}" y="${pad}" width="${size - pad * 2}" height="${size - pad * 2}" fill="#f7f9fd" stroke="#e4e9f2"/>`;
  out += `<line x1="${pad}" y1="${pad}" x2="${size - pad}" y2="${size - pad}" stroke="#dce4f1" stroke-dasharray="6 5"/>`;
  out += `<line x1="${pad}" y1="${size / 2}" x2="${size - pad}" y2="${size / 2}" stroke="#eef2f8"/>`;
  out += `<line x1="${size / 2}" y1="${pad}" x2="${size / 2}" y2="${size - pad}" stroke="#eef2f8"/>`;
  heat.forEach(h => out += `<rect x="${S(h.x)}" y="${S(h.y)}" width="${cell.toFixed(1)}" height="${cell.toFixed(1)}" fill="#d95f6b" opacity="${(.10 + Math.pow(h.n / maxHeat, .65) * .78).toFixed(3)}"${tip(`网格 (${h.x}, ${h.y}) · ${h.n} 次死亡`)}/>`);
  out += `<circle cx="${S(-50)}" cy="${S(-50)}" r="7" fill="#3b6ce8" stroke="#fff" stroke-width="2"/><text x="${S(-50) + 12}" y="${S(-50) + 4}" class="dp-map-label">蓝方基地</text>`;
  out += `<circle cx="${S(50)}" cy="${S(50)}" r="7" fill="#d95f6b" stroke="#fff" stroke-width="2"/><text x="${S(50) - 12}" y="${S(50) + 4}" text-anchor="end" class="dp-map-label">红方基地</text>`;
  out += `</svg><div class="dp-legend"><span><i style="background:#d95f6b"></i>颜色越深 = 死亡越密集</span><span class="dp-legend-note">${heat.length} 个网格 · 实测坐标</span></div></div>`;
  const phases = payload.phases || [], maxPhase = Math.max(1, ...phases.map(p => p.n));
  const phaseBars = `<div class="dp-inline-bars">${phases.map(p => `<div class="dp-inline-bar"><span>${esc(p.label)}</span><i style="width:${p.n / maxPhase * 100}%"></i><b>${p.n}</b></div>`).join('')}</div>`;
  const campRows = (payload.camps || []).map(c => `<tr><th>${esc(c.camp)}方</th><td>${fmt(c.n, 0)}</td><td>${fmt(c.avgDepth, 3)}</td><td>${fmt(c.enemyHalfPct)}%</td><td>${clock(c.avgTime || 0)}</td></tr>`).join('');
  const mins = payload.minutes || [], maxMin = Math.max(1, ...mins.map(m => m.n));
  const minBars = `<div class="dp-minute-bars">${mins.map(m => `<i style="height:${(m.n / maxMin * 100).toFixed(1)}%"${tip(`${m.minute}:00 · ${m.n} 次死亡`)}></i>`).join('')}</div>`;
  return `<div class="dp-death-layout">${out}<div class="dp-death-side">
    <div class="dp-subhead">死亡时间分布 <span>按阶段</span></div>${phaseBars}
    <div class="dp-subhead">蓝红死亡位置 <span>推进深度 0→1 为蓝→红基地</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>阵营</th><th>死亡</th><th>平均深度</th><th>敌方半场</th><th>中位时刻</th></tr></thead><tbody>${campRows}</tbody></table></div>
    <div class="dp-subhead">逐分钟死亡数 <span>实测点，不插值</span></div>${minBars}
  </div></div>`;
}

/* 掉点经济：官方 deathPosArr × revivePosArr 的实测阵亡→复活窗口。
   对齐赛训组「逐人金币差」图，并额外给出过程曲线与不重复计数的集群口径。 */
function dropwindow(payload) {
  const games = payload.games || [], teams = payload.teams || [];
  const curve = payload.curve || [], head = payload.headline || {};
  const chains = (payload.chains || []).slice().sort((a, b) => a.t - b.t);
  const duration = payload.duration || 1;
  const selectedGame = games.find(g => String(g.id) === String(payload.selected));
  const currentName = payload.selectedLabel || (selectedGame ? gameLabel(selectedGame) : (payload.selected || '—'));
  const multi = chains.filter(c => c.n >= 2).length;
  const tools = `<div class="dp-map-tools"><label>对局 <select data-game-select>${games.map(g =>
    `<option value="${esc(g.id)}"${g.id === payload.selected ? ' selected' : ''}>${esc(gameLabel(g))} · ${fmt(g.deaths, 0)} 次阵亡 · ${clock(g.duration || 0)}</option>`).join('')}</select></label>
    <span>差值为本队减对手 · 金币约数 · 「终」= 阵亡后未复活至终局</span></div>`;
  const title = `<div class="dp-drop-title"><h3>对局 ${esc(currentName)} ｜ ${fmt(head.deaths, 0)} 次阵亡 · 逐人金币差</h3>
    <p>每笔依次显示阵亡时差值、复活时差值与两者之差；正数损失 = 该玩家所在方经济差恶化。</p></div>`;
  const stats = `<div class="dp-inline-stats">
    <div><span>本局阵亡</span><b>${fmt(head.deaths, 0)} 次</b><small>含 ${fmt(head.final, 0)} 次终局未复活</small></div>
    <div><span>掉点集群</span><b>${fmt(head.chains, 0)} 个</b><small>${multi} 个为多人连锁</small></div>
    <div><span>集群净摆动合计</span><b>${fmt(head.chainSwing, 0)}</b><small>蓝−红 · 不重复计数</small></div>
    <div><span>逐笔损失合计</span><b>${signed(head.sumWindowLoss, 0)}</b><small>含窗口重叠，仅作逐人比较</small></div>
    <div><span>最贵一笔</span><b>${esc(head.worst?.hero || '—')} ${signed(head.worst?.loss, 0)}</b><small>${head.worst ? clock(head.worst.t) + ' · 被 ' + esc(head.worst.killer || '—') + ' 击杀' : '—'}</small></div>
  </div>`;
  const cards = teams.map(team => {
    const people = team.people.map(p => {
      const rows = p.windows.length ? p.windows.map(win => {
        const tone = win.loss > 0 ? 'neg' : win.loss < 0 ? 'pos' : '';
        const endLabel = clock(win.end) + (win.final ? ' <em>终</em>' : '');
        const info = `${currentName} · ${p.hero} · ${clock(win.t)}–${clock(win.end)} · 差值 ${signed(win.diffStart, 0)} → ${signed(win.diffEnd, 0)} · 损失 ${signed(win.loss, 0)} · 击杀者 ${win.killer || '—'} · 团战 ${win.fight || '—'} · 坐标 (${fmt(win.x, 0)}, ${fmt(win.y, 0)}) · ${win.final ? '终局未复活' : '实测复活'}`;
        return `<div class="dp-drop-row"${tip(info)}>
          <span class="dp-drop-clock">${clock(win.t)} → ${endLabel}</span>
          <span class="dp-drop-diffs">${signed(win.diffStart, 0)} → ${signed(win.diffEnd, 0)}</span>
          <span class="dp-drop-loss ${tone}">损失 ${signed(win.loss, 0)}</span>
        </div>`;
      }).join('') : '<div class="dp-drop-zero">零阵亡</div>';
      return `<div class="dp-drop-player"><div class="dp-drop-player-head"><b>${esc(p.hero || '—')}</b><span>${esc(p.lane)}</span>
        <small>${p.n ? `${p.n} 次 · 逐笔合计 ${signed(p.totalLoss, 0)}` : '本局未阵亡'}</small></div>${rows}</div>`;
    }).join('');
    return `<section class="dp-drop-team ${team.camp === '蓝' ? 'blue' : 'red'}">
      <div class="dp-drop-team-head"><b>${team.camp}方</b><span>${fmt(team.deaths, 0)} 次阵亡</span><small>逐笔合计 ${signed(team.totalLoss, 0)}（含重叠）</small></div>${people}</section>`;
  }).join('');

  const w = 980, h = 250, l = 62, r = 20, t = 18, b = 42;
  const yd = extent(curve.map(p => p[1]), true);
  const X = v => l + Math.min(1, Math.max(0, v / duration)) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  let svg = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="掉点窗口与经济差过程">${axis(w, h, l, r, t, b, [0, duration], yd, v => clock(v), v => fmt(v, 0))}`;
  svg += `<line x1="${l}" x2="${w - r}" y1="${Y(0)}" y2="${Y(0)}" class="dp-median"/>`;
  svg += `<path d="${curve.map((p, i) => `${i ? 'L' : 'M'}${X(p[0])},${Y(p[1])}`).join(' ')}" fill="none" stroke="#3b6ce8" stroke-width="2"/>`;
  teams.forEach(team => team.people.forEach(p => p.windows.forEach(win => {
    const blue = team.camp === '蓝' ? win.diffStart : -win.diffStart;
    const y = Y(Math.max(yd[0], Math.min(yd[1], blue)));
    const color = win.loss > 0 ? '#d95f6b' : '#2aa79b';
    svg += `<line x1="${X(win.t)}" x2="${X(win.end)}" y1="${y}" y2="${y}" stroke="${color}" stroke-width="2.6" opacity=".6"${tip(`${currentName} · ${p.hero} · ${clock(win.t)} → ${clock(win.end)} · 损失 ${signed(win.loss, 0)}`)}/>`;
    svg += `<circle cx="${X(win.t)}" cy="${y}" r="2.5" fill="${CAMP_COLOR[team.camp]}" opacity=".9"/>`;
    if (win.final) svg += `<circle cx="${X(win.end)}" cy="${y}" r="3.4" fill="none" stroke="${color}" stroke-width="1.3"/>`;
  })));
  svg += `</svg><div class="dp-legend"><span><i style="background:#3b6ce8"></i>蓝−红经济差曲线</span><span><i style="background:#d95f6b"></i>本队经济差恶化</span><span><i style="background:#2aa79b"></i>本队经济差改善</span><span class="dp-legend-note">短横线 = 阵亡→复活窗口 · 空心圈 = 终局未复活</span></div>`;

  const chainRows = chains.map(c => `<tr><td>${esc(gameLabel(c))}</td><td>${clock(c.t)} → ${clock(c.end)}</td>
    <td><b>${c.n}</b>${c.n >= 2 ? ' <small>连锁</small>' : ''}</td><td>${c.blue} / ${c.red}</td>
    <td>${signed(c.startBlue, 0)} → ${signed(c.endBlue, 0)}</td>
    <td class="${c.swing >= 0 ? 'pos' : 'neg'}">${signed(c.swing, 0)}</td><td>${c.final ? '含终局' : ''}</td></tr>`).join('');
  return `${tools}${title}${stats}
    <div class="dp-subhead">逐人掉点流水 <span>两列按阵营 · 每人每笔一个窗口 · 悬停看击杀者 / 团战 / 坐标</span></div>
    <div class="dp-drop-teams">${cards}</div>
    <div class="dp-subhead">掉点窗口 vs 团队经济差过程 <span>蓝−红 · 30 秒一个实测金币点</span></div>${svg}
    <div class="dp-subhead">掉点集群 <span>重叠窗口合并，团队经济摆动只计一次</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>窗口</th><th>阵亡数</th><th>蓝 / 红</th><th>蓝−红 起 → 止</th><th>净摆动</th><th>标记</th></tr></thead><tbody>${chainRows || '<tr><td colspan="7">无</td></tr>'}</tbody></table></div>`;
}

function dropScatter(points, medianLoss) {
  const clean = (points || []).filter(p => Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)));
  if (!clean.length) return '<div class="dp-empty">没有可绘制的掉点窗口。</div>';
  const ys = clean.map(p => Number(p.y)).sort((a, b) => a - b);
  const lo = ys[Math.floor(ys.length * .01)], hi = ys[Math.floor(ys.length * .99)];
  const shown = clean.filter(p => p.y >= lo && p.y <= hi), hidden = clean.length - shown.length;
  const w = 980, h = 300, l = 66, r = 20, t = 20, b = 46;
  const xd = [0, Math.max(1, ...shown.map(p => Number(p.x)))], yd = extent(shown.map(p => p.y), true);
  const X = v => l + (v - xd[0]) / (xd[1] - xd[0]) * (w - l - r);
  const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="掉点损失时间分布">${axis(w, h, l, r, t, b, xd, yd, v => `${fmt(v, 0)} 分`, v => fmt(v, 0))}`;
  out += `<line x1="${l}" x2="${w - r}" y1="${Y(0)}" y2="${Y(0)}" class="dp-median"/>`;
  if (medianLoss != null && medianLoss >= yd[0] && medianLoss <= yd[1]) {
    out += `<line x1="${l}" x2="${w - r}" y1="${Y(medianLoss)}" y2="${Y(medianLoss)}" stroke="#e08a3c" stroke-width="1.2" stroke-dasharray="4 4"/>`;
  }
  shown.forEach(p => out += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="3.4" fill="${CAMP_COLOR[p.group] || '#3b6ce8'}" fill-opacity=".5" ${p.final ? 'stroke="#e08a3c" stroke-width="1.4"' : ''}${tip(`${p.label} · 第 ${fmt(p.x, 1)} 分 · 损失 ${signed(p.y, 0)} · ${p.detail}`)}/>`);
  out += `<text x="${l}" y="${h - 8}" class="dp-axis">阵亡时刻 →</text><text x="${l - 52}" y="${t - 6}" class="dp-axis">损失（金币）→</text></svg>`;
  return `${out}<div class="dp-legend"><span><i style="background:#3b6ce8"></i>蓝方阵亡</span><span><i style="background:#d95f6b"></i>红方阵亡</span><span><i style="background:#e08a3c"></i>橙圈 = 终局未复活 · 橙虚线 = 平均损失</span><span class="dp-legend-note">${shown.length} 笔 · 图外截去 ${hidden} 个极端点</span></div>`;
}

function dropimpact(payload) {
  const s = payload.summary || {}, phases = payload.phases || [], lanes = payload.lanes || [];
  const heroes = payload.heroes || [], outcome = payload.outcome || [], flips = payload.flips || {};
  const stats = `<div class="dp-inline-stats">
    <div><span>掉点窗口</span><b>${fmt(s.n, 0)} 笔</b><small>${fmt(s.games, 0)} 局官方回放</small></div>
    <div><span>实测复活</span><b>${fmt(s.revivePct)}%</b><small>${fmt(s.revived, 0)} / ${fmt(s.n, 0)} 笔</small></div>
    <div><span>复活窗口平均</span><b>${fmt(s.medianWindow, 0)} 秒</b><small>常见 ${fmt(s.p25Window, 0)} – ${fmt(s.p75Window, 0)} 秒</small></div>
    <div><span>单笔损失平均</span><b>${signed(s.medianLoss, 0)}</b><small>前列水平 ${signed(s.p75Loss, 0)} / ${signed(s.p90Loss, 0)}</small></div>
    <div><span>经济差恶化占比</span><b>${fmt(s.positivePct)}%</b><small>${fmt(s.positive, 0)} 笔损失为正</small></div>
    <div><span>掉点集群</span><b>${fmt(s.chainCount, 0)} 个</b><small>${fmt(s.multiChains, 0)} 个为多人连锁</small></div>
  </div>`;
  const late = phases.find(p => p.label.indexOf('后期') >= 0) || {};
  const early = phases.find(p => p.label.indexOf('前期') >= 0) || {};
  const finding = `<div class="dp-finding"><b>后期掉点平均损失 ${signed(late.avgLoss, 0)}，前期仅 ${signed(early.avgLoss, 0)}；${fmt(s.multiChains, 0)} / ${fmt(s.chainCount, 0)} 个集群是多人连锁</b><span>逐笔损失含重叠，团队级口径看集群净摆动</span></div>`;
  const phaseCards = `<div class="dp-phases">${phases.map(p => `<div class="dp-phase"><span>${esc(p.label)}</span><b>${fmt(p.n, 0)} 笔</b><small>占 ${fmt(p.pct)}% · 未复活 ${fmt(p.finalPct)}%</small><div><em>${signed(p.avgLoss, 0)}</em> 平均损失 · 中位 ${signed(p.medianLoss, 0)}</div></div>`).join('')}</div>`;
  const laneRows = lanes.map(l => `<tr><th>${esc(l.label)}</th><td>${fmt(l.n, 0)}</td><td>${signed(l.avgLoss, 0)}</td><td>${signed(l.medianLoss, 0)}</td><td>${signed(l.p90Loss, 0)}</td><td>${fmt(l.finalPct)}%</td></tr>`).join('');
  const heroRows = heroes.slice(0, 12).map(h => `<tr><th>${esc(h.hero)}<small>${h.n} 笔窗口</small></th><td>${signed(h.avgLoss, 0)}</td><td>${signed(h.medianLoss, 0)}</td><td>${signed(h.p90Loss, 0)}</td><td>${fmt(h.medianWindow, 0)}s</td><td>${fmt(h.finalPct)}%</td></tr>`).join('');
  const outcomeRows = outcome.map(o => `<tr><th>${esc(o.label)}</th><td>${fmt(o.n, 0)}</td><td>${signed(o.avgLoss, 0)}</td><td>${signed(o.medianLoss, 0)}</td><td>${fmt(o.finalPct)}%</td></tr>`).join('');
  const flipCards = `<div class="dp-inline-stats">
    <div><span>领先 → 落后</span><b>${fmt(flips.leadLost, 0)} 笔</b><small>窗口内经济差翻转</small></div>
    <div><span>领先保持</span><b>${fmt(flips.leadKept, 0)} 笔</b><small>阵亡时本队领先</small></div>
    <div><span>落后 → 反超</span><b>${fmt(flips.deficitRecovered, 0)} 笔</b><small>窗口内经济差翻转</small></div>
    <div><span>落后持续</span><b>${fmt(flips.deficitKept, 0)} 笔</b><small>阵亡时本队落后</small></div>
  </div>`;
  const topRows = (payload.top || []).map(t => `<tr><td>${esc(gameLabel(t))}</td><td>${clock(t.t)} → ${clock(t.end)}${t.final ? ' 终' : ''}</td><td>${esc(t.hero)}</td><td>${esc(t.camp)}</td><td>${esc(t.killer || '—')}</td><td>${signed(t.diffStart, 0)} → ${signed(t.diffEnd, 0)}</td><td class="neg">${signed(t.loss, 0)}</td></tr>`).join('');
  const chainRows = (payload.chains || []).map(c => `<tr><td>${esc(gameLabel(c))}</td><td>${clock(c.t)} → ${clock(c.end)}</td><td>${c.n} 人</td><td>${c.blue} / ${c.red}</td><td>${signed(c.startBlue, 0)} → ${signed(c.endBlue, 0)}</td><td class="${c.swing >= 0 ? 'pos' : 'neg'}">${signed(c.swing, 0)}</td></tr>`).join('');
  return `${stats}${finding}
    <div class="dp-subhead">全部掉点：时刻 × 单笔损失 <span>每点一次阵亡窗口 · 正数 = 本队经济差恶化</span></div>${dropScatter(payload.points, s.medianLoss)}
    <div class="dp-subhead">掉点阶段 <span>按阵亡时刻分段，不是按复活时刻</span></div>${phaseCards}
    <div class="dp-two-col"><div><div class="dp-subhead">分路编码 × 掉点代价 <span>位置为营地原始编码</span></div>
      <div class="dp-scroll"><table class="dp-table"><thead><tr><th>分路</th><th>笔数</th><th>平均</th><th>中位</th><th>高位</th><th>未复活</th></tr></thead><tbody>${laneRows}</tbody></table></div></div>
      <div><div class="dp-subhead">英雄 × 掉点代价 <span>窗口 ≥ 8 笔 · 已剔除 ${fmt(payload.heroExcluded, 0)} 个英雄</span></div>
      <div class="dp-scroll"><table class="dp-table"><thead><tr><th>英雄</th><th>平均</th><th>中位</th><th>高位</th><th>窗口中位</th><th>未复活</th></tr></thead><tbody>${heroRows}</tbody></table></div></div></div>
    <div class="dp-subhead">胜负对照与经济差翻转 <span>描述性对照，不是胜因推断</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局结果</th><th>掉点笔数</th><th>平均损失</th><th>中位损失</th><th>终局未复活占比</th></tr></thead><tbody>${outcomeRows}</tbody></table></div>${flipCards}
    <div class="dp-subhead">最贵的 20 笔掉点 <span>按单笔损失降序 · 含击杀者</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>窗口</th><th>阵亡英雄</th><th>阵营</th><th>击杀者</th><th>本队差值 起 → 止</th><th>损失</th></tr></thead><tbody>${topRows}</tbody></table></div>
    <div class="dp-subhead">摆动最大的 15 个掉点集群 <span>蓝−红净摆动，重叠窗口只计一次</span></div>
    <div class="dp-scroll"><table class="dp-table"><thead><tr><th>对局</th><th>集群窗口</th><th>阵亡人数</th><th>蓝 / 红</th><th>蓝−红 起 → 止</th><th>净摆动</th></tr></thead><tbody>${chainRows}</tbody></table></div>`;
}

/* 下钻：cs_conversion / cross_resource_output 的「按选手」表，
   以及英雄相关分析底部的英雄页入口。字段未就绪时整段不渲染。 */
const HERO_ANALYSES = new Set(['cross_lane_hero', 'equip_matrix', 'equip_impact', 'stability']);

function rowPlayer(row) {
  const name = row?.label ?? row?.playerLabel ?? row?.playerName ?? row?.player ?? row?.name ?? '';
  if (!name) return {name: '', bound: false};
  const rawBound = row?.bound ?? row?.claimed;
  const looksAnonymous = /^P\d+$/i.test(String(name));
  return {name: String(name), bound: rawBound === null || rawBound === undefined ? !looksAnonymous : Boolean(rawBound)};
}

function playerCell(row) {
  const {name, bound} = rowPlayer(row);
  if (!name) return '<span class="dp-player-unbound">—</span>';
  if (!bound) return `<span class="dp-player-unbound">${esc(name)}</span> <span class="dp-tag-unbound">未认领</span>`;
  return `<a class="dp-player-link" href="#player/${encodeURIComponent(name)}">${esc(name)}</a>`;
}

function sampleCount(row) {
  const value = row?.n ?? row?.samples ?? row?.sample ?? row?.games ?? row?.count ?? row?.matches;
  return value === null || value === undefined ? '—' : fmt(value, 0);
}

function metricValue(row, keys) {
  for (const source of [row, row?.metrics, row?.stats, row?.values]) {
    if (!source || typeof source !== 'object') continue;
    for (const key of keys) {
      const value = source[key];
      if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) continue;
      return Number(value);
    }
  }
  return null;
}

function byPlayerSection(analysisId, payload, label = '') {
  if (analysisId !== 'cs_conversion' && analysisId !== 'cross_resource_output') return '';
  const rows = Array.isArray(payload?.byPlayer) ? payload.byPlayer : [];
  if (!rows.length) return '';
  const isCs = analysisId === 'cs_conversion';
  const head = isCs
    ? '<th>选手</th><th>样本</th><th>补刀</th><th>总经济</th><th>对英雄输出</th><th>转化比</th>'
    : '<th>选手</th><th>样本</th><th>经济占比</th><th>输出占比</th><th>输出 − 经济</th>';
  const body = rows.map(row => {
    if (isCs) {
      const cs = metricValue(row, ['cs', 'csTotal', 'avgCs', 'csAvg', 'csMedian', 'csPerGame']);
      const gold = metricValue(row, ['gold', 'avgGold', 'goldAvg', 'totalGold', 'goldMedian']);
      const damage = metricValue(row, ['heroDamage', 'damage', 'avgDamage', 'avgHeroDamage', 'heroHurt', 'heroDamageAvg']);
      const conversion = metricValue(row, ['conversion', 'hurtTransRate', 'transRate', 'damageConversion', 'avgConversion']);
      return `<tr><th>${playerCell(row)}</th><td>${sampleCount(row)}</td><td>${fmt(cs, 0)}</td><td>${fmt(gold, 0)}</td><td>${fmt(damage, 0)}</td><td>${fmt(conversion, 2)}</td></tr>`;
    }
    const goldShare = metricValue(row, ['goldShare', 'goldSharePct', 'avgGoldShare', 'x', 'goldPct']);
    const damageShare = metricValue(row, ['damageShare', 'damageSharePct', 'avgDamageShare', 'y', 'damagePct']);
    let gap = metricValue(row, ['shareGap', 'shareGapPp', 'gap', 'diff', 'delta']);
    if (gap === null && goldShare !== null && damageShare !== null) gap = damageShare - goldShare;
    return `<tr><th>${playerCell(row)}</th><td>${sampleCount(row)}</td><td>${fmt(goldShare, 1)}%</td><td>${fmt(damageShare, 1)}%</td><td class="${gap === null ? '' : gap >= 0 ? 'pos' : 'neg'}">${gap === null ? '—' : signed(gap, 1)}</td></tr>`;
  }).join('');
  return `<div class="dp-subhead">${label ? esc(label) + ' · ' : ''}按选手 <span>已认领的选手可直接进选手页 · 未认领只显示 P0X</span></div>
    <div class="dp-by-player dp-scroll"><table class="dp-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function firstHeroFor(analysisId, payload) {
  if (analysisId === 'cross_lane_hero') return (payload?.cols || [])[0] || '';
  if (analysisId === 'stability') return payload?.rows?.[0]?.label || '';
  const listed = Array.isArray(payload?.heroes) ? payload.heroes[0] : null;
  if (typeof listed === 'string') return listed;
  return listed?.hero || listed?.heroName || listed?.label || '';
}

function heroDrillLink(analysisId, payload, heroChoice, fallbackHero) {
  if (!HERO_ANALYSES.has(analysisId)) return '';
  const hero = heroChoice || firstHeroFor(analysisId, payload) || fallbackHero || '';
  if (!hero) return '';
  return `<div class="dp-drill-footer"><a href="#hero/${encodeURIComponent(hero)}">去英雄页看逐局 · ${esc(hero)} →</a></div>`;
}

const RENDERERS = {matrix, scatter, chain, impact, timeline, economy, events, map,
                   lanespace, pace, baseline, camp, bp, stability,
                   killrhythm, fightscatter, deathmap, dropwindow, dropimpact};

/* 区块/单条页共享的图形交互：轨迹开关、对局选择、悬停提示 */
function bindDepthTools(wrap, tooltip, {onGameSelect}) {
  wrap.addEventListener('click', event => {
    const all = event.target.closest('[data-track-all]');
    if (all) {
      const mode = all.dataset.trackAll;
      const on = i => mode === 'show' ? true : mode === 'default' ? i < 2 : false;
      wrap.querySelectorAll('[data-track]').forEach((path, i) => { path.style.display = on(i) ? '' : 'none'; });
      wrap.querySelectorAll('[data-track-toggle]').forEach((btn, i) => {
        btn.classList.toggle('off', !on(i));
        btn.classList.toggle('active', on(i));
      });
      return;
    }
    const toggle = event.target.closest('[data-track-toggle]');
    if (toggle) {
      const path = wrap.querySelector(`[data-track="${toggle.dataset.trackToggle}"]`);
      const off = toggle.classList.toggle('off');
      toggle.classList.toggle('active', !off);
      if (path) path.style.display = off ? 'none' : '';
    }
  });
  wrap.addEventListener('change', event => {
    const select = event.target.closest('[data-game-select]');
    if (select && onGameSelect) onGameSelect(select.value);
  });
  wrap.addEventListener('mouseover', event => {
    const target = event.target.closest('[data-tip]');
    if (!target) { tooltip.hidden = true; return; }
    tooltip.textContent = target.dataset.tip;
    tooltip.hidden = false;
  });
  wrap.addEventListener('mousemove', event => {
    if (tooltip.hidden) return;
    const box = wrap.getBoundingClientRect();
    tooltip.style.left = Math.min(box.width - 260, Math.max(8, event.clientX - box.left + 14)) + 'px';
    tooltip.style.top = Math.max(8, event.clientY - box.top - 40) + 'px';
  });
  wrap.addEventListener('mouseout', event => {
    if (!event.relatedTarget || !wrap.contains(event.relatedTarget)) tooltip.hidden = true;
  });
}

/* 轻量目录页：按方向分组列出当前模块可用的深度分析，不画图。
   ids 决定收录与组内顺序；不传时展示整个目录。 */
const HUB_DIRECTIONS = ['交叉', '补刀', '装备', '时间', '空间', '对比', 'BP 与资源', '稳定性', '击杀', '掉点'];

export async function renderDepthHub(container, {api, isCurrent, ids, title, module}) {
  const catalog = await api('/api/depth/catalog');
  if (isCurrent && !isCurrent()) return;
  const all = Array.isArray(catalog.analyses) ? catalog.analyses : [];
  const byId = new Map(all.map(a => [a.id, a]));
  const wantedIds = ids instanceof Set ? [...ids]
    : typeof ids === 'string' ? ids.split(',').map(id => id.trim()).filter(Boolean) : ids;
  const wanted = Array.isArray(wantedIds) && wantedIds.length ? wantedIds : null;
  const picked = [];
  if (wanted) {
    const seen = new Set();
    wanted.forEach(id => {
      const analysis = byId.get(id);
      if (analysis && !seen.has(analysis.id)) {
        seen.add(analysis.id);
        picked.push(analysis);
      }
    });
  } else {
    picked.push(...all);
  }
  const counts = catalog.counts || {};
  const scopeText = counts.games === null || counts.games === undefined
    ? (counts.replayGames === null || counts.replayGames === undefined ? '营地十人面板与官方回放' : `官方回放 ${fmt(counts.replayGames, 0)} 局`)
    : `营地十人面板 ${fmt(counts.games, 0)} 局 · 官方回放 ${fmt(counts.replayGames, 0)} 局`;

  const groups = new Map();
  picked.forEach(a => {
    const direction = a.direction || '其他';
    if (!groups.has(direction)) groups.set(direction, []);
    groups.get(direction).push(a);
  });
  const directionOrder = HUB_DIRECTIONS.filter(d => groups.has(d));
  [...groups.keys()].filter(d => !HUB_DIRECTIONS.includes(d)).forEach(d => directionOrder.push(d));

  const item = a => `<a class="dp-hub-item" href="#depth/${encodeURIComponent(a.id)}">
      <span class="dp-hub-item-main">
        <span class="dp-hub-item-title"><span class="dp-dir-chip">${esc(a.direction || '')}</span>${esc(a.title)}</span>
        <span class="dp-hub-sub">${esc(a.subtitle || '')}</span>
      </span>
      <span class="dp-hub-samples" title="${esc(a.samples || '')}">样本 ${esc(a.samples || '—')}</span>
    </a>`;
  const groupHtml = directionOrder.map(direction => `<section class="dp-hub-group" aria-label="${esc(direction)}">
      <h3 class="dp-hub-dir">${esc(direction)}</h3>
      <div class="dp-hub-items">${groups.get(direction).map(item).join('')}</div>
    </section>`).join('');

  container.innerHTML = `<section class="dp-hub">
    <div class="dp-hub-head">
      <div><span class="dp-hub-eyebrow">${esc(module || '深度分析')} · 分析目录</span><h2>${esc(title || '深度分析')}</h2></div>
      <span class="dp-hub-count">${picked.length} 条 · ${groups.size} 个方向</span>
    </div>
    <div class="dp-scope">
      <span class="dp-scope-tag">数据口径</span>
      <span class="dp-scope-main"><b>${esc(scopeText)}</b></span>
      <span class="dp-scope-note">独立数据源，不随顶栏筛选变化</span>
    </div>
    ${groupHtml || '<div class="dp-empty">这个模块暂时没有可用的深度分析。</div>'}
  </section>`;
}

/* 单条分析页（#depth/<id>，从各模块页签行进入）。
   可分边的分析带「视角」选项框：全部 / 我方 / 对方（可按对手战队）/ 对比。
   我方阵营由营地取数账号（head.acntCamp）自动识别；教练在「对局分边」可覆盖并命名对手。 */
export async function renderDepthEntry(container, {api, isCurrent, id, module = '深度分析'}) {
  const catalog = await api('/api/depth/catalog');
  if (isCurrent && !isCurrent()) return;
  const a = (catalog.analyses || []).find(x => x.id === id);
  if (!a) {
    container.innerHTML = `<div class="page-heading"><div><h1>没有这条分析</h1><p>深度分析目录里找不到「${esc(id)}」，可能已被调整；从各模块页签进入。</p></div></div>`;
    return;
  }
  const campMeta = catalog.campMeta || {};
  const opponents = campMeta.opponents || [];
  // sided=false：双边过程图（逐局节奏 / 经济差 / 事件密度 / 击杀节奏）与蓝红视角体检，
  // 本来就是两方对照，单边过滤没有意义，不出现视角选项框。
  const sided = a.sided !== false;
  // meta.filters 是后端新契约（side / player / hero 的子集）；旧数据没有时退回 sided。
  const rawFilters = a.filters;
  const metaFilters = Array.isArray(rawFilters)
    ? rawFilters
    : typeof rawFilters === 'string' ? rawFilters.split(',').map(x => x.trim()).filter(Boolean) : null;
  const allowSide = metaFilters ? metaFilters.includes('side') : sided;
  const allowPlayer = metaFilters ? metaFilters.includes('player') : false;
  const allowHero = metaFilters ? metaFilters.includes('hero') : false;
  const catalogPlayers = Array.isArray(catalog.players) ? catalog.players
    : Array.isArray(catalog.playersCatalog) ? catalog.playersCatalog : [];
  const catalogHeroes = Array.isArray(catalog.heroes) ? catalog.heroes
    : Array.isArray(catalog.heroCatalog) ? catalog.heroCatalog
      : Array.isArray(catalog.heroesCatalog) ? catalog.heroesCatalog : [];
  const playerOptions = catalogPlayers.map(p => {
    const label = String(typeof p === 'string' ? p : (p?.label || p?.player || p?.name || ''));
    const bound = typeof p === 'object' && p !== null && p.bound !== null && p.bound !== undefined
      ? Boolean(p.bound)
      : !/^P\d+$/i.test(label);
    return {label, bound};
  }).filter((p, i, list) => p.label && list.findIndex(x => x.label === p.label) === i);
  const heroOptions = catalogHeroes
    .map(h => typeof h === 'string' ? h : (h?.label || h?.hero || h?.heroName || h?.name || ''))
    .filter((h, i, list) => h && list.indexOf(h) === i);
  const campStatus = campMeta.games
    ? `我方阵营 ${campMeta.manual ? '手动' : '自动识别'} ${campMeta.auto + campMeta.manual}/${campMeta.games} 局 · 对手已命名 ${campMeta.named} 局`
    : '';
  const sideControl = allowSide && campMeta.games ? `<label>视角 <select data-side-select>
        <option value="">全部</option>
        <option value="own">我方</option>
        <option value="opp">对方（全部对手）</option>
        ${opponents.map(o => `<option value="opp|${esc(o.name)}">对方 · ${esc(o.name)}（${o.games} 局）</option>`).join('')}
        <option value="compare">对比 · 我方 vs 对方</option>
      </select></label>` : '';
  const playerControl = allowPlayer && playerOptions.length ? `<label>选手 <select data-player-select>
        <option value="">全部选手</option>
        ${playerOptions.map(p => `<option value="${esc(p.label)}" class="${p.bound ? '' : 'dp-option-unbound'}">${esc(p.label)} · ${p.bound ? '已认领' : '未认领'}</option>`).join('')}
      </select></label>` : '';
  const heroControl = allowHero && heroOptions.length ? `<label>英雄 <select data-hero-select>
        <option value="">全部英雄</option>
        ${heroOptions.map(h => `<option value="${esc(h)}">${esc(h)}</option>`).join('')}
      </select></label>` : '';
  const sideNote = allowSide && campMeta.games
    ? `<span class="dp-side-note">${esc(campStatus)}${campMeta.named < campMeta.games ? ` · <a href="#identity">去对局分边命名对手 →</a>` : ''}</span>`
    : '';
  const toolControls = [sideControl, playerControl, heroControl].filter(Boolean);
  const sideTools = toolControls.length ? `<div class="dp-side-tools">${toolControls.join('')}${sideNote}</div>` : '';
  const wrap = document.createElement('section');
  wrap.className = 'dp-entry';
  wrap.innerHTML = `<div class="page-heading"><div>
      <span class="page-eyebrow">${esc(module)} · 深度分析</span>
      <h1>${esc(a.title)}</h1>
      <p>${esc(a.subtitle || '')}</p>
      <div class="page-facts"><span>样本：${esc(a.samples)}</span><span>营地口径，不随顶栏筛选变化</span>${campStatus && !allowSide ? `<span>${esc(campStatus)}</span>` : ''}</div></div>
      <div class="heading-actions"><span class="pill neutral">${esc(a.direction || '')}</span></div></div>
    <div class="dp-detail-head">
      <div class="dp-purpose"><span>这张图回答</span><p>${esc(a.purpose)}</p></div>
      <div class="dp-facts"><div><span>怎么读</span><b></b></div>
        <div><span>注意</span><b class="dp-boundary">${esc(a.boundary)}</b></div></div>
    </div>
    ${sideTools}
    <div class="dp-entry-main"><div class="dp-loading">正在计算…</div></div>
    <div class="dp-tooltip" hidden></div>`;
  container.appendChild(wrap);

  const main = wrap.querySelector('.dp-entry-main');
  const tooltip = wrap.querySelector('.dp-tooltip');
  const cache = new Map();
  let sideChoice = '', playerChoice = '', heroChoice = '', gameChoice = '';

  const buildQuery = side => {
    const params = new URLSearchParams();
    if (gameChoice) params.set('game', gameChoice);
    if (playerChoice) params.set('player', playerChoice);
    if (heroChoice) params.set('hero', heroChoice);
    if (side) {
      const [kind, team] = side.split('|');
      params.set('side', kind);
      if (team) params.set('team', team);
    }
    const q = params.toString();
    return q ? '?' + q : '';
  };
  const renderOptions = {heroNames: id === 'cross_lane_hero' ? new Set(heroOptions) : null, boldCols: id === 'cross_lane_hero'};
  const fallbackHero = heroOptions[0] || '';

  const panel = (label, tone, html) =>
    `<section class="dp-chart-card dp-compare-panel ${tone}"><div class="dp-compare-tag ${tone}">${esc(label)}</div>${html}</section>`;

  /* 对比模式的散点叠画：我方 / 对方同轴两色，各自带平均虚线 */
  function scatterCompare(own, opp) {
    const pick = p => (p.points || []).filter(q => Number.isFinite(Number(q.x)) && Number.isFinite(Number(q.y)));
    const pts = [...pick(own).map(p => ({...p, side: 'own'})), ...pick(opp).map(p => ({...p, side: 'opp'}))];
    if (!pts.length) return '<div class="dp-empty">两侧都没有有效样本。</div>';
    const w = 860, h = 420, l = 62, r = 24, t = 22, b = 52;
    const xd = extent(pts.map(p => p.x)), yd = extent(pts.map(p => p.y));
    const X = v => l + (v - xd[0]) / (xd[1] - xd[0]) * (w - l - r);
    const Y = v => h - b - (v - yd[0]) / (yd[1] - yd[0]) * (h - t - b);
    let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" class="dp-svg" role="img" aria-label="我方对方对比散点">${axis(w, h, l, r, t, b, xd, yd)}`;
    [['own', own], ['opp', opp]].forEach(([side, payload]) => {
      const color = SIDE_COLOR[side];
      if (payload.ref && Number.isFinite(payload.ref.x)) out += `<line x1="${X(payload.ref.x)}" x2="${X(payload.ref.x)}" y1="${t}" y2="${h - b}" stroke="${color}" stroke-dasharray="3 5" stroke-width="1.2" opacity=".65"/>`;
      if (payload.ref && Number.isFinite(payload.ref.y)) out += `<line x1="${l}" x2="${w - r}" y1="${Y(payload.ref.y)}" y2="${Y(payload.ref.y)}" stroke="${color}" stroke-dasharray="3 5" stroke-width="1.2" opacity=".65"/>`;
    });
    pts.forEach(p => {
      const c = SIDE_COLOR[p.side];
      out += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4.6" fill="${c}" fill-opacity=".55" stroke="${c}"${tip(`${p.side === 'own' ? '我方' : '对方'} · ${p.label} · ${p.group || ''} · X ${fmt(p.x)} · Y ${fmt(p.y)}${p.detail ? ' · ' + p.detail : ''}`)}/>`;
    });
    out += `<text x="${l}" y="${h - 8}" class="dp-axis">${esc(own.xLabel || '')} →</text><text x="${l - 44}" y="${t - 6}" class="dp-axis">${esc(own.yLabel || '')}</text></svg>`;
    const rOf = p => p.corr == null ? '—' : fmt(p.corr, 2);
    const legend = `<div class="dp-legend"><span><i style="background:${SIDE_COLOR.own}"></i>我方 ${pick(own).length} 样本 · r ${rOf(own)}</span><span><i style="background:${SIDE_COLOR.opp}"></i>对方 ${pick(opp).length} 样本 · r ${rOf(opp)}</span><span class="dp-legend-note">同色虚线 = 各自平均线 · 相关不看因果</span></div>`;
    return `${out}${legend}`;
  }

  function compareHtml(own, opp) {
    if (own.payload.viz === 'scatter' && opp.payload.viz === 'scatter') {
      return scatterCompare(own.payload, opp.payload)
        + byPlayerSection(id, own.payload, '我方')
        + byPlayerSection(id, opp.payload, '对方');
    }
    const renderer = RENDERERS[own.payload.viz] || (() => '<div class="dp-empty">该图形尚未接入。</div>');
    return panel('我方', 'own', renderer(own.payload, renderOptions) + byPlayerSection(id, own.payload))
      + panel('对方', 'opp', renderer(opp.payload, renderOptions) + byPlayerSection(id, opp.payload));
  }

  async function drawCompare() {
    const key = id + '|compare|' + buildQuery('');
    if (!cache.has(key)) main.innerHTML = '<div class="dp-loading">正在计算…</div>';
    try {
      if (!cache.has(key)) {
        const [own, opp] = await Promise.all([
          api('/api/depth/analysis/' + encodeURIComponent(id) + buildQuery('own')),
          api('/api/depth/analysis/' + encodeURIComponent(id) + buildQuery('opp')),
        ]);
        if (isCurrent && !isCurrent()) return;
        cache.set(key, {payload: {viz: own.payload.viz, own: own.payload, opp: opp.payload}});
      }
      const result = cache.get(key);
      main.innerHTML = compareHtml({payload: result.payload.own}, {payload: result.payload.opp})
        + heroDrillLink(id, result.payload.own, heroChoice, fallbackHero);
      const noteEl = wrap.querySelector('.dp-facts b');
      if (noteEl) noteEl.textContent = result.payload.own.note || '';
    } catch (error) {
      main.innerHTML = `<div class="dp-empty">该分析读取失败：${esc(error.message)}</div>`;
    }
  }

  async function draw(query = '') {
    const key = id + query;
    if (!cache.has(key)) main.innerHTML = '<div class="dp-loading">正在计算…</div>';
    try {
      if (!cache.has(key)) {
        const result = await api('/api/depth/analysis/' + encodeURIComponent(id) + query);
        if (isCurrent && !isCurrent()) return;
        cache.set(key, result);
      }
      const result = cache.get(key);
      const renderer = RENDERERS[result.payload.viz] || (() => '<div class="dp-empty">该图形尚未接入。</div>');
      main.innerHTML = `<section class="dp-chart-card">${renderer(result.payload, renderOptions)}${byPlayerSection(id, result.payload)}</section>`
        + heroDrillLink(id, result.payload, heroChoice, fallbackHero);
      const noteEl = wrap.querySelector('.dp-facts b');
      if (noteEl) noteEl.textContent = result.payload.note || '';
    } catch (error) {
      main.innerHTML = `<div class="dp-empty">该分析读取失败：${esc(error.message)}</div>`;
    }
  }

  async function redraw() {
    if (sideChoice === 'compare') return drawCompare();
    return draw(buildQuery(sideChoice));
  }

  await redraw();
  // 掉点经济等分析带对局下拉；切对局 / 视角 / 选手 / 英雄都要按当前组合重算
  bindDepthTools(wrap, tooltip, {onGameSelect: value => {gameChoice = value; redraw();}});
  wrap.addEventListener('change', event => {
    const select = event.target.closest('[data-side-select],[data-player-select],[data-hero-select]');
    if (!select) return;
    if (select.hasAttribute('data-side-select')) sideChoice = select.value;
    else if (select.hasAttribute('data-player-select')) playerChoice = select.value;
    else heroChoice = select.value;
   