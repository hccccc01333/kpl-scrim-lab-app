/* 通用跨局分析 · 可视化层
   白底、大读数、一分析一形态。所有视图共用 shell：
   - 两个可切换视图（switchViz 依赖 data-cx-view-btn / data-cx-view / .cx-view）
   - 图形元素可悬停读数（data-cx-tip）、点选圈定（data-cx-sel）
   - 图元素数量恒定，与局数无关；文字用 HTML 保证清晰，SVG 只画曲线。
   probeKeys 的 sel 语义沿用 band / val / dim / lane / win / seg / bucket / sys / state / key。 */

const num = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const esc = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const signed = (v) => (v < 0 ? '−' : '+') + Math.round(Math.abs(num(v) ? v : 0)).toLocaleString('zh-CN');
const pct = (v) => `${Math.round((num(v) ? v : 0) * 100)}%`;
/* 战队说「金币」，不说「金」 */
const yuan = (t) => String(t == null ? '' : t).replace(/金(?!币)/g, '金币');
const signedCls = (v) => (num(v) && v < 0 ? 'neg' : 'pos');
const tip = (t) => `data-cx-tip="${esc(yuan(t))}"`;
const sel = (s) => `data-cx-sel="${esc(s || '')}"`;
const maxOf = (arr, get, fb = 1) => Math.max(fb, ...arr.map((x) => Math.abs(num(get(x)) ? get(x) : 0)));
const widthOf = (v, max) => `${clamp(Math.abs(num(v) ? v : 0) / Math.max(1, max) * 100, 1.5, 100).toFixed(1)}%`;

const HUMAN = {
  '同条件下的自然波动': '同一批对手里的起伏',
  '阵营': '蓝红方差别',
  '版本': '换了版本',
  '对手': '换了对手',
  '训练组': '换了训练组',
};
const SHORT = {
  '同条件下的自然波动': '局内起伏',
  '阵营': '蓝红方',
  '版本': '换版本',
  '对手': '换对手',
  '训练组': '换训练组',
};
const human = (v) => HUMAN[v] || v;
const short = (v) => SHORT[v] || String(v).slice(0, 5);

const VIEWS = {
  '01': ['经济差散点', '领先 / 落后局数'],
  '02': ['左右对比', '哪项差最多'],
  '04': ['最顺 / 最难', '按日期看'],
  '02': ['差别来自哪', '排个序'],
  '03': ['最差的10%对局', '哪路最常落后'],
  '04': ['一段段看', '分段对照'],
  '05': ['整段走势', '每段时间'],
  '06': ['几套打法', '哪套最稳'],
  '07': ['打谁用哪套', '组合排序'],
  '08': ['赢在哪段', '赢在哪路'],
  '09': ['领先守得住吗', '各状态局数'],
  '10': ['先看哪类', '各类多少局'],
  '11': ['按出场', '按胜率'],
  '12': ['按出场', '按胜率'],
  '15': ['左右对比', '哪项差最多'],
  '16': ['按出场', '按胜率'],
  '17': ['按波数', '按胜率'],
  '18': ['左右对比', '哪项差最多'],
  '19': ['场均死亡', '按大小'],
  '20': ['按位置', '按大小'],
  '21': ['伤害 / 承伤', '按大小'],
  '22': ['按胜率', '按兑现'],
  '23': ['按出场', '按胜率'],
};

/* ── 通用零件 ─────────────────────────────────────────────────── */

function shell(card, ctx, a, b) {
  const meta = VIEWS[card.id] || ['看图', '换个角度'];
  const cur = ctx.view(card.id);
  const one = (key, html) => `<div class="cx-view${cur === key ? ' is-enter' : ''}" data-cx-view="${key}"${cur === key ? '' : ' hidden'}>${html}</div>`;
  return `<div class="cxv" data-cx-viz="${esc(card.id)}">
    <div class="cxv-bar">
      <div class="cxv-switch" role="group" aria-label="切换视图">
        <button type="button" data-cx-view-btn="a" data-cx-viz-id="${esc(card.id)}" class="${cur === 'a' ? 'is-on' : ''}">${esc(meta[0])}</button>
        <button type="button" data-cx-view-btn="b" data-cx-viz-id="${esc(card.id)}" class="${cur === 'b' ? 'is-on' : ''}">${esc(meta[1])}</button>
      </div>
    </div>
    <div class="cxv-stage cx-viz-stage">${one('a', a)}${one('b', b)}<div class="cx-viz-tip" hidden></div></div>
  </div>`;
}

function view(hero, body) {
  return `<div class="cxv-view"><div class="cxv-hero">${hero}</div><div class="cxv-body">${body}</div></div>`;
}

function big(value, label, cls = '') {
  return `<div class="cxv-figure ${cls}"><b>${esc(yuan(value))}</b><span>${esc(yuan(label))}</span></div>`;
}

function note() {
  return '';
}

function rows(items, render) {
  return `<div class="cxv-rows">${items.map(render).join('')}</div>`;
}

function barRow(label, value, width, cls, tipText, selText, sub = '') {
  return `<div class="cxv-row" ${tip(tipText)} ${sel(selText)}>
    <span class="cxv-row-label">${esc(yuan(label))}${sub ? `<small>${esc(yuan(sub))}</small>` : ''}</span>
    <i class="cxv-track"><b class="${cls}" style="width:${width}"></b></i>
    <em class="cxv-row-val ${cls}">${esc(yuan(value))}</em>
  </div>`;
}

/* SVG 折线：viewBox 固定，线宽不随拉伸变形，文字全部交给 HTML */
function chartSvg(height, inner) {
  return `<svg class="cxv-chart" viewBox="0 0 1000 ${height}" preserveAspectRatio="none" role="img" aria-label="趋势图">${inner}</svg>`;
}
function gridLines(h, n = 4) {
  return Array.from({ length: n + 1 }, (_, i) =>
    `<line class="cxv-grid" x1="0" x2="1000" y1="${(h * i / n).toFixed(1)}" y2="${(h * i / n).toFixed(1)}" vector-effect="non-scaling-stroke"/>`).join('');
}
function polyline(points, cls, w = 3) {
  const d = points.filter((p) => p && num(p.y)).map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  return `<path class="cxv-line ${cls}" d="${d}" stroke-width="${w}" vector-effect="non-scaling-stroke"/>`;
}

/* ── 01 分层基准分析 ──────────────────────────────────────────── */
function bands(c, card, ctx) {
  const lo = num(c.lo) ? c.lo : 0, hi = num(c.hi) ? c.hi : 1;
  const span = Math.max(1, hi - lo);
  const at = (v) => clamp(((num(v) ? v : 0) - lo) / span * 100, 1, 99);
  const pool = (ctx.rows || []).filter((v) => num(v.at10));
  const near = (t) => pool.slice().sort((a, b) => Math.abs(a.at10 - t) - Math.abs(b.at10 - t))[0];
  const tag = (v) => v ? `${v.opponent || '训练赛'} ${v.clock || ''}`.trim().slice(0, 14) : '';
  const low = near(lo), mid = near(c.p50), high = near(hi);

  const A = view(
    big(signed(c.p50), '这支队 10 分钟的典型领先', 'gold') + note('高于这条线算打得好，低于它先找原因'),
    `<div class="cxv-anchors">
      <div><span>最差的10%对局</span><b>${signed(lo)}</b><small>${esc(tag(low))}</small></div>
      <div class="is-mid"><span>典型水平</span><b>${signed(c.p50)}</b><small>${esc(tag(mid))}</small></div>
      <div><span>最好的10%对局</span><b>${signed(hi)}</b><small>${esc(tag(high))}</small></div>
    </div>
    <div class="cxv-scale" ${tip(`大多数局在 ${signed(c.p25)} ~ ${signed(c.p75)} 金之间，点这里圈出这批局`)} ${sel(`band:${c.p25}:${c.p75}`)}>
      <i class="cxv-fill" style="left:${at(c.p25).toFixed(1)}%;width:${(at(c.p75) - at(c.p25)).toFixed(1)}%"></i>
      <i class="cxv-mid" style="left:${at(c.p50).toFixed(1)}%"></i>
      <i class="cxv-dot" style="left:${at(lo).toFixed(1)}%" ${tip(`最差的10%对局：${tag(low)} · ${signed(lo)} 金`)} ${sel(`band:${lo}:${c.p25}`)}></i>
      <i class="cxv-dot alt" style="left:${at(hi).toFixed(1)}%" ${tip(`最好的10%对局：${tag(high)} · ${signed(hi)} 金`)} ${sel(`band:${c.p75}:${hi}`)}></i>
    </div>
    <div class="cxv-ticks"><span>${signed(lo)}</span><span>${signed(c.p25)}</span><span>${signed(c.p50)}</span><span>${signed(c.p75)}</span><span>${signed(hi)}</span></div>`
  );

  const strata = c.strata || [];
  const list = strata.length
    ? strata.slice(0, 6).map((s) => ({ label: s.label, value: s.p50, sub: `${s.n} 局`, selv: `val:opponent:${String(s.label).split('·').pop().trim()}` }))
    : [['最差10%对局', c.lo, `band:${lo}:${c.p25}`], ['偏低', c.p25, `band:${c.p25}:${c.p50}`], ['典型', c.p50, `band:${c.p50}:${c.p75}`], ['偏高', c.p75, `band:${c.p75}:${hi}`], ['最好10%对局', c.hi, `band:${c.p75}:${hi}`]]
      .map(([label, value, selv]) => ({ label, value, sub: '', selv }));
  const mx = maxOf(list, (x) => x.value);
  const B = view(
    big(strata.length ? `${strata.length} 组` : '五档', strata.length ? '可对比的对手 / 版本分组' : '从最差到最好的五个档位', 'teal') + note('每根条都能点，直接圈出这批局'),
    rows(list, (x) => barRow(x.label, signed(x.value), widthOf(x.value, mx), x.value < 0 ? 'neg' : 'gold', `${x.label} · ${signed(x.value)} 金`, x.selv, x.sub))
  );
  return shell(card, ctx, A, B);
}

/* ── 02 波动来源分析 ──────────────────────────────────────────── */
function stack(c, card, ctx) {
  const parts = (c.parts || []).filter((p) => p.share > 0.005);
  const top = parts.slice().sort((a, b) => b.share - a.share)[0] || { label: '—', share: 0 };
  const R = 74, CIRC = 2 * Math.PI * R;
  let acc = 0;
  const arcs = parts.map((p, i) => {
    const len = p.share * CIRC;
    const el = `<circle class="cxv-arc s${i % 5}" cx="100" cy="100" r="${R}" fill="none" stroke-width="30" stroke-dasharray="${len.toFixed(2)} ${(CIRC - len).toFixed(2)}" stroke-dashoffset="${(-acc).toFixed(2)}" transform="rotate(-90 100 100)" ${tip(`${human(p.label)}占 ${pct(p.share)}，点这里圈出相关对局`)} ${sel(`dim:${p.label}`)}/>`;
    acc += len;
    return el;
  }).join('');
  const legend = parts.map((p, i) => `<div class="cxv-lg-row" ${tip(`${human(p.label)}占 ${pct(p.share)}`)} ${sel(`dim:${p.label}`)}>
      <i class="s${i % 5}"></i><span>${esc(human(p.label))}</span><b>${pct(p.share)}</b>
      <u class="s${i % 5}" style="width:${(p.share * 100).toFixed(1)}%"></u></div>`).join('');
  const A = view(
    big(pct(top.share), `起伏主要来自「${short(top.label)}」`, 'teal') + note('同一批对手里的自然起伏，还是外部条件变了'),
    `<div class="cxv-split">
      <svg class="cxv-donut" viewBox="0 0 200 200" role="img" aria-label="波动来源分解">
        <circle class="cxv-arc-bg" cx="100" cy="100" r="${R}" fill="none" stroke-width="30"/>${arcs}
        <text class="cxv-donut-num" x="100" y="100" text-anchor="middle">${pct(top.share)}</text>
        <text class="cxv-donut-lab" x="100" y="122" text-anchor="middle">${esc(short(top.label))}</text>
      </svg>
      <div class="cxv-legend">${legend}</div>
    </div>`
  );
  const sorted = parts.slice().sort((a, b) => b.share - a.share);
  const mx = maxOf(sorted, (p) => p.share, 0.01);
  const B = view(
    big(`${parts.length} 项`, '把经济差起伏按来源拆开', 'gold') + note('占比越大，评价队员状态时越要先扣掉它'),
    rows(sorted, (p) => barRow(human(p.label), pct(p.share), widthOf(p.share, mx), 'gold', `${human(p.label)}占 ${pct(p.share)}`, `dim:${p.label}`))
  );
  return shell(card, ctx, A, B);
}

/* ── 03 下限风险分析 ──────────────────────────────────────────── */
function range(c, card, ctx) {
  const items = c.items || [];
  const worst = items.slice().sort((a, b) => (num(a.p10) ? a.p10 : 0) - (num(b.p10) ? b.p10 : 0))[0] || { label: '—', p10: 0, bad: 0 };
  const risky = items.slice().sort((a, b) => b.bad - a.bad)[0] || worst;
  const A = view(
    big(pct(risky.bad), `${risky.label} · 对线落后的局占比`, 'neg'),
    rows(items.slice().sort((a, b) => b.bad - a.bad), (x) => barRow(x.label, pct(x.bad), widthOf(x.bad, 1), x.bad > 0.3 ? 'neg' : 'gold', `${x.label} · ${pct(x.bad)} 的局对线落后 · 最差10%对局 ${signed(x.p10)} 金`, `lane:${x.label}`, `最差10%对局 ${signed(x.p10)} 金`))
    + `<div class="cxv-ticks"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>`
  );
  const mx = maxOf(items.flatMap((x) => [x.p10, x.p90]), (v) => v);
  const B = view(
    big(signed(worst.p10), `${worst.label} · 最差10%对局`, 'neg'),
    `<div class="cxv-bipolars">${items.map((x) => `
      <div class="cxv-bipolar" ${tip(`${x.label}：最差的10%对局 ${signed(x.p10)} 金、典型 ${signed(x.p50)} 金、最好 ${signed(x.p90)} 金；${pct(x.bad)} 的局对线落后`)} ${sel(`lane:${x.label}`)}>
        <span>${esc(x.label)}</span>
        <i class="cxv-bi-track"><em></em>
          <b class="neg" style="right:50%;width:${(Math.max(0, -(num(x.p10) ? x.p10 : 0)) / mx * 50).toFixed(1)}%"></b>
          <b style="left:50%;width:${(Math.max(0, num(x.p90) ? x.p90 : 0) / mx * 50).toFixed(1)}%"></b></i>
        <strong class="${signedCls(x.p10)}">${signed(x.p10)}</strong>
      </div>`).join('')}</div>
      <div class="cxv-ticks"><span>${signed(-mx)}</span><span>0</span><span>${signed(mx)}</span></div>`
  );
  return shell(card, ctx, A, B);
}
function segments(c, card, ctx) {
  const items = (c.items || []).slice(0, 8);
  const first = items[0], last = items[items.length - 1];
  const effect = first && last ? (num(last.value) ? last.value : 0) - (num(first.value) ? first.value : 0) : 0;
  const H = 170;
  const all = items.flatMap((s) => [s.lo, s.hi, s.value]).filter(num);
  const lo = Math.min(0, ...all), hi = Math.max(1, ...all), span = Math.max(1, hi - lo);
  const x = (i) => items.length === 1 ? 500 : 40 + i / (items.length - 1) * 920;
  const y = (v) => H - 18 - ((v - lo) / span) * (H - 40);
  const pts = items.map((s, i) => ({ x: x(i), y: y(num(s.value) ? s.value : 0) }));
  let A;
  if (items.length < 3) {
    A = view(
      big(signed(effect), '首段到末段的 10 分钟经济差变化', effect >= 0 ? 'gold' : 'neg'),
      `<div class="cxv-duo">
        <div class="cxv-duo-side"><span>最早一段</span><b>${signed(first ? first.value : 0)}</b><small>${esc((first && first.from) || '开赛')} 起 · ${first ? first.n : 0} 局</small></div>
        <i class="cxv-duo-arrow">→</i>
        <div class="cxv-duo-side"><span>最近一段</span><b>${signed(last ? last.value : 0)}</b><small>${esc((last && last.from) || '收官')} 起 · ${last ? last.n : 0} 局</small></div>
        <em class="${signedCls(effect)}">${signed(effect)}<small>净变化</small></em>
      </div>`
    );
  } else {
    const band = `<path class="cxv-band-area" d="${items.map((s, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(num(s.hi) ? s.hi : s.value || 0).toFixed(1)}`).join(' ')} ${items.slice().reverse().map((s, j) => `L${x(items.length - 1 - j).toFixed(1)},${y(num(s.lo) ? s.lo : s.value || 0).toFixed(1)}`).join(' ')} Z"/>`;
    A = view(
      big(signed(effect), '首段到末段的 10 分钟经济差变化', effect >= 0 ? 'gold' : 'neg'),
      `${chartSvg(H, `${gridLines(H)}${band}
        <line class="cxv-zero" x1="0" x2="1000" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/>
        ${polyline(pts, 'gold', 3.5)}
        ${items.map((s, i) => `<g ${tip(`${s.label}${s.from ? '（' + s.from + ' 起）' : ''} · ${s.n} 局 · 典型 ${signed(s.value)} 金 · 可信范围 ${signed(s.lo)} ~ ${signed(s.hi)}`)} ${sel(`seg:${i}`)}>
          <circle class="cxv-point" cx="${x(i).toFixed(1)}" cy="${y(num(s.value) ? s.value : 0).toFixed(1)}" r="6" vector-effect="non-scaling-stroke"/>
          <rect class="cxv-hit" x="${(x(i) - 40).toFixed(1)}" y="0" width="80" height="${H}"/></g>`).join('')}`)}
        <div class="cxv-ticks">${items.map((s) => `<span>${esc(s.from || s.label)}</span>`).join('')}</div>`
    );
  }
  const mx = maxOf(items, (s) => s.value);
  const B = view(
    big(signed(last ? last.value : 0), '最近一段的典型水平', 'teal'),
    rows(items, (s, i) => barRow(`${s.label}${s.from ? ' · ' + s.from : ''}`, signed(s.value), widthOf(s.value, mx), signedCls(s.value) === 'neg' ? 'neg' : 'gold', `${s.label} · ${s.n} 局 · 可信范围 ${signed(s.lo)} ~ ${signed(s.hi)}`, `seg:${i}`))
  );
  return shell(card, ctx, A, B);
}
function rolling(c, card, ctx) {
  const p = c.points || [];
  const H = 170;
  const vs = p.map((q) => q.v).filter(num);
  const lo = Math.min(0, ...vs), hi = Math.max(1, ...vs), span = Math.max(1, hi - lo);
  const x = (i) => p.length <= 1 ? 500 : 20 + i / (p.length - 1) * 960;
  const y = (v) => H - 16 - ((v - lo) / span) * (H - 38);
  const pts = p.map((q, i) => num(q.v) ? { x: x(i), y: y(q.v) } : null);
  const valid = pts.filter(Boolean);
  const line = valid.length ? polyline(valid, 'teal', 3.5) : '';
  const area = valid.length > 1 ? `<path class="cxv-area" d="${line.replace(/^<path[^>]*d="/, '').replace(/"[^>]*><\/path>$/, '')} L${valid[valid.length - 1].x.toFixed(1)},${y(0).toFixed(1)} L${valid[0].x.toFixed(1)},${y(0).toFixed(1)} Z"/>` : '';
  const ci = c.changeIndex;
  const change = num(ci) && ci >= 0
    ? `<line class="cxv-change" x1="${x(ci).toFixed(1)}" x2="${x(ci).toFixed(1)}" y1="4" y2="${H}" vector-effect="non-scaling-stroke"/>` : '';
  const last = vs.length ? vs[vs.length - 1] : 0;
  const A = view(
    big(signed(last), '最近一段时间的典型水平', 'teal') + note(change ? '金色竖线是检测到的水平变化位置' : '按开赛顺序滚动，逐个时间段看走势'),
    `${chartSvg(H, `${gridLines(H)}<line class="cxv-zero" x1="0" x2="1000" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/>${area}${line}${change}
      ${p.map((q, i) => num(q.v) ? `<circle class="cxv-point sm" cx="${x(i).toFixed(1)}" cy="${y(q.v).toFixed(1)}" r="4" vector-effect="non-scaling-stroke" ${tip(`${q.label || '第 ' + (i + 1) + ' 段'} · 典型 ${signed(q.v)} 金 · 点这里圈出这段局`)} ${sel(`bucket:${i}`)}/>` : '').join('')}`)}
      <div class="cxv-ticks"><span>${esc(c.from || '')}</span><span>开赛顺序 →</span><span>${esc(c.to || '')}</span></div>`
  );
  const bw = 960 / Math.max(1, p.length);
  const colW = Math.min(bw * .68, 56);
  const B = view(
    big(`${p.length} 段`, '按开赛顺序均分的时间段', 'gold') + note('每根柱是一段的典型水平，点一下圈出这段局'),
    chartSvg(H, `${gridLines(H)}<line class="cxv-zero" x1="0" x2="1000" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/>
      ${p.map((q, i) => { const v = num(q.v) ? q.v : 0, yy = y(v); return `<rect class="cxv-col${v < 0 ? ' neg' : ''}" x="${(x(i) - colW / 2).toFixed(1)}" y="${Math.min(yy, y(0)).toFixed(1)}" width="${colW.toFixed(1)}" height="${Math.max(2, Math.abs(yy - y(0))).toFixed(1)}" rx="2" ${tip(`${q.label || '第 ' + (i + 1) + ' 段'} · 典型 ${signed(q.v)} 金`)} ${sel(`bucket:${i}`)}/>`; }).join('')}${change}`)
  );
  return shell(card, ctx, A, B);
}

/* ── 06 打法体系分析 ──────────────────────────────────────────── */
function systems(c, card, ctx) {
  const items = (c.items || []).slice(0, 4);
  const H = 170;
  const allMax = maxOf(items.flatMap((s) => s.curve || []), (v) => v, 1);
  const colors = ['gold', 'teal', 'blue', 'clay'];
  const curves = items.map((s, i) => {
    const pts = (s.curve || []).slice(0, 6).map((v, j) => ({ x: 40 + j / 5 * 920, y: H / 2 - (num(v) ? v : 0) / allMax * 60 }));
    return polyline(pts, colors[i % 4], i === 0 ? 4 : 2.5);
  }).join('');
  const legend = items.map((s, i) => `<div class="cxv-sys-row" ${tip(`${s.name} · ${s.n} 局 · 占比 ${pct(s.pct)} · 终局下限 ${signed(s.floor)}`)} ${sel(`sys:${i}`)}>
      <i class="${colors[i % 4]}"></i><span>${esc(s.name)}</span><b>${pct(s.pct)}</b><em>${s.n} 局</em></div>`).join('');
  const A = view(
    big(`${items.length}`, '类不同的经济走势', 'gold') + note('每条线是一类局从开局到收官的经济差走势'),
    `<div class="cxv-split chart-first">${chartSvg(H, `${gridLines(H)}<line class="cxv-zero" x1="0" x2="1000" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>${curves}`)}
      <div class="cxv-sys-legend">${legend}</div></div>
      <div class="cxv-ticks"><span>开局</span><span>20%</span><span>40%</span><span>60%</span><span>80%</span><span>收官</span></div>`
  );
  const sorted = items.slice().sort((a, b) => (num(b.floor) ? b.floor : 0) - (num(a.floor) ? a.floor : 0));
  const mx = maxOf(sorted, (s) => s.floor);
  const B = view(
    big(signed(sorted[0] ? sorted[0].floor : 0), `${sorted[0] ? sorted[0].name : '—'} 的终局下限`, 'teal') + note('比赛日优先用下限高的那套，不是平均赢最多的那套'),
    rows(sorted, (s) => barRow(s.name, signed(s.floor), widthOf(s.floor, mx), signedCls(s.floor) === 'neg' ? 'neg' : 'gold', `${s.name} · ${s.n} 局 · 下限 ${signed(s.floor)}`, `sys:${items.indexOf(s)}`))
  );
  return shell(card, ctx, A, B);
}

/* ── 07 体系适配分析 ──────────────────────────────────────────── */
function matrix(c, card, ctx) {
  const rs = c.rows || [], rawCols = c.cols || [], cells = c.cells || [];
  const keep = rawCols.map((_, j) => j).filter((j) => cells.some((row) => row[j] && row[j].n >= 2));
  const use = keep.length ? keep : rawCols.map((_, j) => j);
  const cols = use.map((j) => rawCols[j]);
  const flat = cells.flat().filter((x) => num(x.v));
  const mx = maxOf(flat, (x) => x.v);
  const dimKey = c.dimLabel === '对手' ? 'opponent' : 'version';
  const best = flat.slice().sort((a, b) => b.v - a.v)[0];
  const combos = [];
  rs.forEach((r, i) => use.forEach((src, j) => {
    const cell = (cells[i] || [])[src];
    if (cell && cell.n >= 1 && num(cell.v)) combos.push({ label: `${r} × ${cols[j]}`, v: cell.v, n: cell.n, s: `val:${dimKey}:${cols[j]}` });
  }));
  combos.sort((a, b) => b.v - a.v);
  const valid = combos.filter((x) => x.n >= 2);
  let A;
  if (valid.length < 3) {
    const hi = valid[0] || combos[0], lo = valid[valid.length - 1] || combos[combos.length - 1];
    const gap = hi && lo ? hi.v - lo.v : 0;
    A = view(
      big(signed(gap), '组合之间的终局经济差差距', 'gold'),
      `<div class="cxv-duo">
        <div class="cxv-duo-side"><span>赢得最多的组合</span><b>${signed(hi ? hi.v : 0)}</b><small>${esc(hi ? hi.label : '—')} · ${hi ? hi.n : 0} 局</small></div>
        <i class="cxv-duo-arrow">→</i>
        <div class="cxv-duo-side"><span>另一组合</span><b>${signed(lo ? lo.v : 0)}</b><small>${esc(lo ? lo.label : '—')} · ${lo ? lo.n : 0} 局</small></div>
        <em class="${signedCls(gap)}">${signed(gap)}<small>差距</small></em>
      </div>`
    );
  } else {
    const colName = (x) => (String(x) === '未标注' ? '对手未填' : String(x).slice(0, 8));
    A = view(
      big(best ? signed(best.v) : '—', '表现最好的一个组合', 'gold') + note(),
      `<div class="cxv-mtx" style="grid-template-columns:110px repeat(${Math.max(1, cols.length)},minmax(0,1fr))">
        <span></span>${cols.map((x) => `<span class="cxv-mtx-col">${esc(colName(x))}</span>`).join('')}
        ${rs.map((r, i) => `<span class="cxv-mtx-row">${esc(r)}</span>${use.map((src) => (cells[i] || [])[src] || { n: 0 }).map((cell, j) => `<span class="cxv-mtx-cell ${cell.n < 2 ? 'thin' : signedCls(cell.v)}" style="--w:${(num(cell.v) ? Math.abs(cell.v) / mx * .55 + .08 : .05).toFixed(2)}" ${tip(`${r} 打 ${cols[j]} · ${cell.n} 局${cell.n >= 2 ? ' · 平均赢 ' + signed(cell.v) + ' 金' : ''}`)} ${sel(`val:${dimKey}:${cols[j]}`)}>
          <b>${cell.n < 2 ? (cell.n ? '样本少' : '—') : signed(cell.v)}</b><small>${cell.n} 局</small></span>`).join('')}`).join('')}
      </div>`
    );
  }
  const cmx = maxOf(combos.slice(0, 8), (x) => x.v);
  const B = view(
    big(`${combos.length}`, '个有对局的组合', 'teal'),
    rows(combos.slice(0, 8), (x) => barRow(x.label, signed(x.v), widthOf(x.v, cmx), signedCls(x.v) === 'neg' ? 'neg' : 'gold', `${x.label} · ${x.n} 局 · 平均 ${signed(x.v)} 金`, x.s, `${x.n} 局`))
  );
  return shell(card, ctx, A, B);
}
function contrib(c, card, ctx) {
  const w = (c.windows || []).slice(0, 10), l = (c.lanes || []).slice(0, 5);
  const peak = w.slice().sort((a, b) => (num(b.value) ? b.value : 0) - (num(a.value) ? a.value : 0))[0];
  const H = 190;
  const mid = H / 2;
  const mx = maxOf(w, (x) => x.value);
  const bw = 1000 / Math.max(1, w.length);
  const colW = Math.min(bw * .62, 96);
  /* 零线放中间：正收益往上、掉经济往下，负数不会被画成正的 */
  const scale = (H / 2 - 16) / mx;
  const y = (v) => mid - (num(v) ? v : 0) * scale;
  const A = view(
    big(signed(peak ? peak.value : 0), `${peak ? String(peak.label).replace('′', ' 分钟') : '—'} 是主要胜源`, 'gold') + note('往上是这段挣到的经济，往下是这段被对手追回的'),
    `${chartSvg(H, `${gridLines(H)}<line class="cxv-zero" x1="0" x2="1000" y1="${mid.toFixed(1)}" y2="${mid.toFixed(1)}" vector-effect="non-scaling-stroke"/>
      ${w.map((x, i) => { const v = num(x.value) ? x.value : 0; const top = Math.min(y(v), mid); return `<rect class="cxv-col${i === w.indexOf(peak) ? ' is-peak' : ''}${v < 0 ? ' neg' : ''}" x="${(i * bw + (bw - colW) / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${colW.toFixed(1)}" height="${Math.max(3, Math.abs(mid - y(v))).toFixed(1)}" rx="3" ${tip(`${String(x.label).replace('′', ' 分钟')} · ${x.n} 局 · 平均拉开 ${signed(x.value)} 金`)} ${sel(`win:${i}`)}/>`; }).join('')}`)}
      <div class="cxv-ticks cols" style="grid-template-columns:repeat(${Math.max(1, w.length)},minmax(0,1fr))">${w.map((x) => `<span>${esc(String(x.label).replace('′', ' 分钟'))}<b>${signed(x.value)}</b></span>`).join('')}</div>`
  );
  const lmx = maxOf(l, (x) => x.pct, 0.01);
  const B = view(
    big(l.length ? pct(Math.max(...l.map((x) => x.pct || 0))) : '—', '单路最大贡献', 'teal') + note('把总优势拆到五条路，看是哪一路在扛'),
    rows(l, (x) => barRow(x.label, pct(x.pct), widthOf(x.pct, lmx), 'gold', `${x.label} · 这一路的贡献 ${pct(x.pct)}`, `lane:${x.label}`))
  );
  return shell(card, ctx, A, B);
}

/* ── 09 领先守成分析 ──────────────────────────────────────────── */
function trans(c, card, ctx) {
  const states = c.states || [], m = c.m || [];
  const total = Math.max(1, ...m.flat());
  let held = 0, all = 0;
  m.forEach((row, i) => { row.forEach((v, j) => { all += v; if (i === j) held += v; }); });
  const active = m.map((row, i) => ({ i, n: row.reduce((a, b) => a + b, 0) })).filter((x) => x.n > 0);
  let A;
  if (active.length <= 1 && active.length) {
    const row = m[active[0].i];
    const end = row.indexOf(Math.max(...row));
    A = view(
      big(pct(row[active[0].i] / Math.max(1, active[0].n)), '开局优势守到收官的局', 'gold'),
      `<div class="cxv-flow">
        <div class="cxv-flow-side"><span>开局</span><b>${esc(states[active[0].i])}</b><small>${active[0].n} 局</small></div>
        <i class="cxv-flow-line" ${tip(`${esc(states[active[0].i])} → ${esc(states[end])} · ${row[end]} 局`)} ${sel(`state:${active[0].i}`)}><em style="width:${pct(row[end] / Math.max(1, active[0].n))}"></em></i>
        <div class="cxv-flow-side"><span>收官</span><b>${esc(states[end])}</b><small>${row[end]} 局</small></div>
      </div>`
    );
  } else {
    A = view(
    big(pct(all ? held / all : 0), '开局优势守到收官的局', 'gold') + note(''),
    `<div class="cxv-mtx states" style="grid-template-columns:110px repeat(${Math.max(1, states.length)},minmax(0,1fr))">
      <span></span>${states.map((s) => `<span class="cxv-mtx-col">收官 ${esc(s)}</span>`).join('')}
      ${m.map((row, i) => `<span class="cxv-mtx-row">开局 ${esc(states[i])}</span>${row.map((v, j) => `<span class="cxv-mtx-cell ${i === j ? 'diag' : signedCls(v - row[i])}" style="--w:${(v / total * .6 + .05).toFixed(2)}" ${tip(`开局${states[i]} → 收官${states[j]} · ${v} 局`)} ${sel(`state:${i}`)}>
        <b>${v ? pct(v / Math.max(1, row.reduce((a, b) => a + b, 0))) : '—'}</b><small>${v} 局</small></span>`).join('')}`).join('')}
    </div>`
    );
  }
  const B = view(
    big(`${all}`, '纳入统计的局', 'teal') + note('按开局状态分组，看每组有多少局稳住了'),
    rows(m.map((row, i) => { const sum = Math.max(1, row.reduce((a, b) => a + b, 0)); return { label: `开局${states[i]}`, v: row[i] / sum, n: sum, i }; }),
      (x) => barRow(x.label, `${x.n} 局`, widthOf(x.v, 1), 'gold', `开局${states[x.i]} · ${x.n} 局，其中 ${pct(x.v)} 稳住`, `state:${x.i}`, `${pct(x.v)} 稳住`))
  );
  return shell(card, ctx, A, B);
}

/* ── 10 复盘队列分析 ──────────────────────────────────────────── */
function types(c, card, ctx) {
  const items = (c.items || []).slice(0, 3);
  const total = items.reduce((s, x) => s + (x.n || 0), 0);
  const A = view(
    big(`${total}`, '局值得优先复盘', 'gold') + note('按类型归类，不再凭印象挑一局'),
    `<div class="cxv-tiles ${items.length === 1 ? 'one' : items.length === 2 ? 'two' : ''}" style="grid-template-columns:repeat(${Math.max(1, items.length)},minmax(0,1fr))">${items.map((x) => `<div class="cxv-tile" ${tip(`${x.name} · ${x.n} 局 · ${pct(x.pct)} · ${x.trait}`)} ${sel(x.top ? `key:${x.top}` : '')}>
      <span class="cxv-tile-num">${x.n}<small>局</small></span>
      <b>${esc(x.name)}</b><p>${esc(x.trait)}</p>
      ${x.top ? `<a class="cx-open" href="#match/${encodeURIComponent(x.top)}">打开代表局 →</a>` : '<span class="cxv-tile-hint">看下面展开的局</span>'}
    </div>`).join('')}</div>`
  );
  const mx = maxOf(items, (x) => x.n);
  const B = view(
    big(`${items.length}`, '类需要复盘的对局', 'teal') + note('每类给一个代表局，点条形圈出整批'),
    rows(items, (x) => barRow(x.name, `${x.n} 局`, widthOf(x.n, mx), 'gold', `${x.name} · ${x.n} 局 · ${pct(x.pct)}`, x.top ? `key:${x.top}` : '', `${pct(x.pct)}`))
  );
  return shell(card, ctx, A, B);
}

/* ── 11/12 账本：出场与胜率两栏 ──────────────────────────────── */
function ledger(c, card, ctx) {
  const items = (c.items || []).filter((x) => x && x.label);
  const noun = card && card.id === '12' ? '对手' : '英雄';
  if (!items.length) {
    return shell(card, ctx, view(big('—', `还没有${noun}样本`, 'neg'), ''), view(big('—', '换不了角度', 'neg'), ''));
  }
  const byGames = items.slice().sort((a, b) => b.games - a.games);
  const byRate = items.filter((x) => (x.decided || 0) >= 2).slice().sort((a, b) => (b.rate || 0) - (a.rate || 0));
  const lead = byGames[0];
  const maxG = Math.max(1, ...byGames.map((x) => x.games));
  const A = view(
    big(`${lead.games}`, `${lead.label} · 出场最多`, 'gold') + note('条长＝出场局数，右边写的是这批局里的胜负'),
    rows(byGames, (x) => barRow(x.label, `${x.games} 局`, widthOf(x.games, maxG), x.rate != null && x.rate < 0.5 ? 'neg' : 'gold',
      `${x.label} · ${x.games} 局 · ${x.wins} 胜${x.decided ? ' · 胜率 ' + pct(x.rate) : ''}`, '',
      x.decided ? `${x.wins} 胜 · ${pct(x.rate)}` : '还没分胜负'))
  );
  const best = byRate[0];
  const B = byRate.length >= 2
    ? view(
      big(pct(best.rate), `${best.label} · 胜率最高`, 'teal') + note('只算有胜负的局；局数少的先当线索'),
      rows(byRate, (x) => barRow(x.label, pct(x.rate), widthOf(x.rate, 1), x.rate < 0.5 ? 'neg' : 'gold',
        `${x.label} · ${x.wins} 胜 ${Math.max(0, x.decided - x.wins)} 负`, '', `${x.wins}/${x.decided} 局`))
    )
    : view(big('—', '有胜负的样本还不够', 'neg'),
      '<p class="cxv-empty-note">至少要有 2 局分出胜负，才排得动胜率。先把对局的结果补上。</p>');
  return shell(card, ctx, A, B);
}

/* ── 01 一局一格：按时间把局排开 ─────────────────────────────── */
function timeline(c, card, ctx) {
  const items = c.items || [];
  if (!items.length) {
    return shell(card, ctx, view(big('0', '局，按时间排开', 'neg'), ''), view(big('—', '还没有样本', 'neg'), ''));
  }
  const known = items.filter((x) => num(x.value));
  const lead = known.filter((x) => x.value > 0).length;
  const A = view(
    big(`${items.length}`, '局，按时间排开', 'gold') + note('金＝这一局 10 分钟领先，红＝落后，灰＝这局没有经济曲线；点一格进复盘'),
    `<div class="cxv-strip">${items.map((x) => {
      const v = num(x.value) ? x.value : null;
      const cls = v == null ? 'na' : v > 0 ? 'pos' : 'neg';
      const res = x.result === 'win' ? 'win' : x.result === 'loss' ? 'loss' : 'na';
      const resText = res === 'win' ? '胜' : res === 'loss' ? '负' : '未标胜负';
      return `<a class="cxv-cell ${cls} ${res}" href="#match/${encodeURIComponent(x.key)}" ${tip(`${x.label}${x.sub ? ' ' + x.sub : ''} · ${resText} · ${v == null ? '没有经济曲线' : '10 分钟 ' + signed(v) + ' 金币'}`)}>
        <b>${v == null ? '—' : signed(v)}</b><small>${esc(x.label)}</small></a>`;
    }).join('')}</div>`
  );
  const groups = new Map();
  for (const x of items) {
    const k = x.label || '未标日期';
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(x);
  }
  const dayRows = [...groups.entries()].slice(0, 10).map(([label, list]) => {
    const k = list.filter((x) => num(x.value));
    return { label, n: list.length, lead: k.filter((x) => x.value > 0).length, known: k.length };
  });
  const B = view(
    big(`${known.length ? pct(lead / known.length) : '—'}`, '有经济曲线的局里，10 分钟领先的比例', 'teal') + note('按训练日分组，看是哪几天领先'),
    rows(dayRows, (x) => barRow(x.label, `${x.lead}/${x.n} 局`, widthOf(x.known ? x.lead / x.known : 0, 1), 'gold',
      `${x.label} · ${x.n} 局里 ${x.lead} 局领先`, '', x.known ? `领先 ${pct(x.lead / x.known)}` : '无经济曲线'))
  );
  return shell(card, ctx, A, B);
}

/* ── 01 散点：一局一个点，按时间排 ───────────────────────────── */
function scatter(c, card, ctx) {
  const all = c.items || [];
  const items = all.filter((x) => num(x.value));
  if (!items.length) {
    return shell(card, ctx, view(big('0', '局有 10 分钟经济', 'neg'), ''), view(big('—', '还没有样本', 'neg'), ''));
  }
  const max = Math.max(500, ...items.map((x) => Math.abs(x.value)));
  const n = items.length;
  const xOf = (i) => (n === 1 ? 50 : 8 + (i / (n - 1)) * 84);
  const yOf = (v) => 50 + (v / max) * 40;
  const lead = items.filter((x) => x.value > 0).length;
  const first = items[0], last = items[items.length - 1];
  const A = view(
    big(`${n}`, '局，一局一个点', 'gold') + note('金点＝这局 10 分钟领先，红点＝落后；左边早、右边晚；点一下进复盘'),
    `<div class="cxv-sc">
      <i class="cxv-sc-zero"></i>
      <span class="cxv-sc-lab top">${signed(max)}</span>
      <span class="cxv-sc-lab mid">0</span>
      <span class="cxv-sc-lab bot">${signed(-max)}</span>
      ${items.map((x, i) => {
        const res = x.result === 'win' ? '胜' : x.result === 'loss' ? '负' : '未标胜负';
        const tipText = `${x.label} ${x.time || ''}${x.sub ? ' · ' + x.sub : ''} · ${res} · 10 分钟 ${signed(x.value)} 金币`;
        return `<a class="cxv-sc-dot ${x.value >= 0 ? 'pos' : 'neg'}" style="left:${xOf(i).toFixed(2)}%;bottom:${yOf(x.value).toFixed(2)}%" href="#match/${encodeURIComponent(x.key)}" ${tip(tipText)}><i></i></a>`;
      }).join('')}
      <div class="cxv-sc-ticks"><span>${esc(first.label)}${first.time ? ' ' + esc(first.time) : ''}</span><span>按开赛时间 →</span><span>${esc(last.label)}${last.time ? ' ' + esc(last.time) : ''}</span></div>
    </div>`
  );
  const noData = all.length - items.length;
  const B = view(
    big(`${pct(lead / items.length)}`, '有经济的局里，10 分钟领先的比例', 'teal'),
    rows([
      { label: '10 分钟领先', n: lead, cls: 'gold' },
      { label: '10 分钟落后', n: items.length - lead, cls: 'neg' },
      { label: '没有经济曲线', n: noData, cls: '' },
    ], (x) => barRow(x.label, `${x.n} 局`, widthOf(x.n, all.length), x.cls, `${x.label} · ${x.n} 局`, '', all.length ? pct(x.n / all.length) : ''))
  );
  return shell(card, ctx, A, B);
}

/* ── 04 突出点：最顺的一批 vs 最难的一批 ─────────────────────── */
function split(c, card, ctx) {
  const left = c.left || { label: '最顺', items: [] };
  const right = c.right || { label: '最难', items: [] };
  const all = [...(left.items || []), ...(right.items || [])];
  if (!all.length) {
    return shell(card, ctx, view(big('—', '还没有样本', 'neg'), ''), view(big('—', '换不了角度', 'neg'), ''));
  }
  const max = Math.max(1, ...all.map((x) => Math.abs(num(x.value) ? x.value : 0)));
  const col = (side, cls) => `<div class="cxv-split-col">
      <div class="cxv-split-head">${esc(side.label)}</div>
      ${(side.items || []).map((x) => `<a class="cxv-split-row" href="#match/${encodeURIComponent(x.key)}" ${tip(`${x.label} · ${signed(x.value)} 金币`)}>
        <span>${esc(x.label)}</span><i><b class="${cls}" style="width:${widthOf(x.value, max)}"></b></i><em class="${cls}">${signed(x.value)}</em></a>`).join('')}
    </div>`;
  const A = view(
    big(`${all.length}`, '局：最顺的一批 vs 最难的一批', 'gold') + note('左边最顺、右边最难，条长是 10 分钟经济差'),
    `<div class="cxv-split2">${col(left, 'pos')}${col(right, 'neg')}</div>`
  );
  const byDate = all.slice().sort((a, b) => String(a.label).localeCompare(String(b.label)));
  const B = view(
    big(`${byDate.length}`, '局按日期排', 'teal') + note('同一批局换个顺序看：最顺和最难的局分别落在哪天'),
    rows(byDate, (x) => barRow(x.label, signed(x.value), widthOf(x.value, max), num(x.value) < 0 ? 'neg' : 'gold',
      `${x.label} · ${signed(x.value)} 金币`, '', x.sub || ''))
  );
  return shell(card, ctx, A, B);
}

/* ── 02 赢输对比：左右两栏，同一项目对齐 ─────────────────────── */
function compare(c, card, ctx) {
  const items = (c.items || []).filter((x) => x && x.label);
  const winN = num(c.winN) ? c.winN : 0;
  const lossN = num(c.lossN) ? c.lossN : 0;
  if (!items.length) {
    return shell(card, ctx, view(big('—', '还没有胜负样本', 'neg'), ''), view(big('—', '换不了角度', 'neg'), ''));
  }
  const max = Math.max(1, ...items.flatMap((x) => [Math.abs(num(x.win) ? x.win : 0), Math.abs(num(x.loss) ? x.loss : 0)]));
  /* 每一行按自己这一行的最大值缩放：不同单位（次 / 条 / % / 座）不能共用一把尺 */
  const wOf = (v, rowMax) => `${clamp(Math.abs(num(v) ? v : 0) / Math.max(1, rowMax) * 100, 2, 100).toFixed(1)}%`;
  const toneOf = (v) => (num(v) && v < 0 ? 'neg' : 'pos');
  const hero = c.hero || { value: `${winN} : ${lossN}`, label: '赢的局 : 输的局', cls: 'gold' };
  const heads = c.headers || [`赢的 ${winN} 局`, `输的 ${lossN} 局`];
  const A = view(
    big(hero.value, hero.label, hero.cls || 'gold') + note('左栏是赢的局，右栏是输的局，同一个项目上下对齐；每行按自己这一行缩放'),
    `<div class="cxv-cmp">
      <div class="cxv-cmp-head"><span></span><span>${esc(heads[0])}</span><span>${esc(heads[1])}</span></div>
      ${items.map((x) => {
        const rowMax = Math.max(1, Math.abs(num(x.win) ? x.win : 0), Math.abs(num(x.loss) ? x.loss : 0));
        return `<div class="cxv-cmp-row">
        <span class="cxv-cmp-label">${esc(yuan(x.label))}</span>
        <span class="cxv-cmp-side"><b class="${toneOf(x.win)}">${esc(yuan(x.winText))}</b><span class="cxv-cmp-track"><i class="cxv-cmp-bar ${toneOf(x.win)}" style="width:${wOf(x.win, rowMax)}"></i></span></span>
        <span class="cxv-cmp-side"><b class="${toneOf(x.loss)}">${esc(yuan(x.lossText))}</b><span class="cxv-cmp-track"><i class="cxv-cmp-bar ${toneOf(x.loss)}" style="width:${wOf(x.loss, rowMax)}"></i></span></span>
      </div>`; }).join('')}
    </div>`
  );
  const gapOf = (x) => Math.abs((num(x.win) ? x.win : 0) - (num(x.loss) ? x.loss : 0));
  const ranked = items.slice().sort((a, b) => gapOf(b) - gapOf(a));
  const gmax = Math.max(1, ...items.map(gapOf));
  const B = view(
    big(`${ranked[0] ? ranked[0].label : '—'}`, '差得最多的一项', 'teal') + note('条越长，赢的局和输的局差得越多'),
    rows(ranked, (x) => barRow(x.label, gapOf(x).toLocaleString('zh-CN'), widthOf(gapOf(x), gmax), 'gold',
      `${x.label} · 赢的局 ${x.winText}，输的局 ${x.lossText}`, '', `${x.winText} → ${x.lossText}`))
  );
  return shell(card, ctx, A, B);
}

/* ── 通用条形榜：一行一项，可带副标题 ───────────────────────── */
function bars(c, card, ctx) {
  const items = (c.items || []).filter((x) => x && x.label);
  if (!items.length) {
    return shell(card, ctx, view(big('—', '还没有样本', 'neg'), ''), view(big('—', '换不了角度', 'neg'), ''));
  }
  const max = Math.max(1, ...items.map((x) => Math.abs(num(x.value) ? x.value : 0)));
  const hero = c.hero || { value: `${items.length}`, label: '项', cls: 'gold' };
  const A = view(
    big(hero.value, hero.label, hero.cls || 'gold') + note(c.note || '条长＝这一项的大小，右边是数值'),
    rows(items, (x) => barRow(x.label, x.text, widthOf(x.value, max), num(x.value) < 0 ? 'neg' : 'gold',
      `${x.label} · ${x.text}${x.sub ? ' · ' + x.sub : ''}`, '', x.sub || ''))
  );
  const sorted = items.slice().sort((a, b) => Math.abs(num(b.value) ? b.value : 0) - Math.abs(num(a.value) ? a.value : 0));
  const B = view(
    big(`${sorted.length}`, '项按大小排', 'teal'),
    rows(sorted, (x) => barRow(x.label, x.text, widthOf(x.value, max), num(x.value) < 0 ? 'neg' : 'gold',
      `${x.label} · ${x.text}`, '', x.sub || ''))
  );
  return shell(card, ctx, A, B);
}

const RENDERERS = {
  bands, stack, range, segments, rolling, systems, matrix, contrib, trans, types, ledger, compare, timeline, split, scatter, bars,
};

export function renderViz(chart, card, ctx) {
  const fn = RENDERERS[chart && chart.type];
  if (!fn) return '';
  return fn(chart || {}, card, ctx);
}
