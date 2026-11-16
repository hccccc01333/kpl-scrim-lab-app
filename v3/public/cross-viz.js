/* 跨局分析 · 图表层（2026-11-15 重构）
 *
 * 只画形状，文字全部走 HTML；viewBox 固定，线宽 non-scaling。
 * 每张图最多两个视图：A 主视图 / B 换角度。点元素可进单局复盘。
 * 数据形状由 cross-analytics.js 产出，本文件不改口径。
 */

const num = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const esc = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const signed = (v, digits = 0) => {
  if (!num(v)) return '—';
  const abs = digits ? Math.abs(v).toFixed(digits) : Math.round(Math.abs(v)).toLocaleString('zh-CN');
  return `${v < 0 ? '−' : '+'}${abs}`;
};
const pct = (v, digits = 0) => (!num(v) ? '—' : `${(v * 100).toFixed(digits)}%`);
const dur = (v) => {
  if (!num(v)) return '—';
  const s = Math.max(0, Math.round(v));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
const unit = (v, u) => {
  if (!num(v)) return '—';
  if (u === 'rate' || u === 'pct') return pct(v);
  if (u === 'sec') return dur(v);
  if (u === 'gold') return `${signed(v)} 金币`;
  if (u === 'perMin') return `${signed(v)} 金币/分`;
  if (u === 'kill') return `${signed(v)} 个`;
  if (u === 'tower') return `${signed(v)} 座`;
  if (u === 'count') return `${signed(v)} 次`;
  if (u === 'count1') return `${signed(v, 1)} 次`;
  if (u === 'fight') return `${signed(v)} 波`;
  return signed(v);
};
const tip = (t) => `data-xc-tip="${esc(t)}"`;
const widthOf = (v, max) => `${clamp(Math.abs(num(v) ? v : 0) / Math.max(1e-9, max) * 100, 1, 100).toFixed(1)}%`;
const signedCls = (v) => (num(v) && v < 0 ? 'neg' : 'pos');

function shell(chart, ctx, labelA, labelB, bodyA, bodyB) {
  const id = chart.id || 'viz';
  const cur = (ctx && ctx.view && ctx.view(id)) || 'a';
  const one = (key, html) => `<div class="xv-view" data-xc-view="${key}"${cur === key ? '' : ' hidden'}>${html}</div>`;
  return `<div class="xv" data-xc-viz="${esc(id)}">
    <div class="xv-head">
      <div class="xv-switch" role="group" aria-label="切换视图">
        <button type="button" data-xc-view-btn="a" data-xc-viz-id="${esc(id)}" class="${cur === 'a' ? 'is-on' : ''}">${esc(labelA)}</button>
        <button type="button" data-xc-view-btn="b" data-xc-viz-id="${esc(id)}" class="${cur === 'b' ? 'is-on' : ''}">${esc(labelB)}</button>
      </div>
    </div>
    <div class="xv-stage">${one('a', bodyA)}${one('b', bodyB)}<div class="xv-tip" hidden></div></div>
  </div>`;
}

function view(figure, body = '') {
  /* shell() 已经提供带 data-xc-view 的外层；这里只出内容，避免嵌套 .xv-view 被切换逻辑误隐藏。 */
  return `<div class="xv-figure">${figure}</div>${body}`;
}

function chartSvg(height, inner) {
  return `<div class="xv-chartbox" style="height:${height}px"><svg class="xv-shape" viewBox="0 0 1000 ${height}" preserveAspectRatio="none" aria-hidden="true">${inner}</svg></div>`;
}

function grid(h, n = 4) {
  return Array.from({ length: n + 1 }, (_, i) =>
    `<line class="grid" x1="0" x2="1000" y1="${(h * i / n).toFixed(1)}" y2="${(h * i / n).toFixed(1)}" vector-effect="non-scaling-stroke"/>`).join('');
}

function polyline(points, cls = '', w = 2) {
  const d = points.filter((p) => p && num(p.y)).map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  return d ? `<path class="line ${cls}" d="${d}" stroke-width="${w}" vector-effect="non-scaling-stroke"/>` : '';
}

function axis(labels) {
  return `<div class="xv-axis">${labels.map((x) => `<span>${esc(x)}</span>`).join('')}</div>`;
}

function legend(items) {
  return `<span class="xv-legend">${items.map(([tone, text]) => `<i class="${tone}"></i>${esc(text)}`).join('')}</span>`;
}

function empty(text) {
  return `<div class="xv-empty">${esc(text)}</div>`;
}

/* ── 走势：逐局经济差 / 滚动胜率 ─────────────────────────────── */
function trend(chart, ctx) {
  const allPoints = (chart.points || []).filter((p) => p && (num(p.at10) || num(p.final)));
  if (!allPoints.length) return empty('这批局缺少经济曲线，走势暂时画不出来。');
  const cap = 160;
  const list = allPoints.length > cap ? allPoints.slice(-cap) : allPoints;
  const offset = allPoints.length - list.length;
  const rolling = chart.rolling || [];
  const vals = list.map((p) => p.at10).filter(num);
  const max = Math.max(500, ...vals.map((v) => Math.abs(v)));
  const H = 190;
  const xOf = (i) => (list.length <= 1 ? 500 : (i + 0.5) / list.length * 1000);
  const yOf = (v) => H / 2 - (v / max) * (H / 2 - 22);
  const dots = list.map((p, i) => {
    if (!num(p.at10)) return '';
    const tone = p.result === 'win' ? 'win' : p.result === 'loss' ? 'loss' : 'na';
    const title = `${p.date || ''} ${p.clock || ''}${p.opponent ? ' · ' + p.opponent : ''} · ${p.result === 'win' ? '胜' : p.result === 'loss' ? '负' : '未标胜负'} · 10 分钟 ${signed(p.at10)} 金币`;
    return `<a class="xv-dot ${tone}" style="left:${(xOf(i) / 10).toFixed(2)}%;top:${(yOf(p.at10) / H * 100).toFixed(2)}%"
      href="#match/${encodeURIComponent(p.key)}" title="${esc(title)}" ${tip(title)}></a>`;
  }).join('');
  const rollPts = list.map((p, i) => {
    const r = rolling[offset + i] || rolling[i] || {};
    return { x: xOf(i), y: num(r.at10) ? yOf(r.at10) : null };
  });
  const area = (() => {
    const valid = list.map((p, i) => ({ i, v: p.at10 })).filter((x) => num(x.v));
    if (valid.length < 2) return '';
    const line = valid.map((x, k) => `${k ? 'L' : 'M'}${xOf(x.i).toFixed(1)},${yOf(x.v).toFixed(1)}`).join(' ');
    const first = valid[0], last = valid[valid.length - 1];
    return `${line} L${xOf(last.i).toFixed(1)},${yOf(0).toFixed(1)} L${xOf(first.i).toFixed(1)},${yOf(0).toFixed(1)} Z`;
  })();
  const A = view(
    `<div class="xv-chartwrap">
      ${chartSvg(H, `${grid(H)}<line class="zero" x1="0" x2="1000" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>
        ${area ? `<path class="area" d="${area}"/>` : ''}
        ${polyline(rollPts, 'roll', 2.4)}`)}
      <span class="xv-y-lab top">${signed(max)}</span>
      <span class="xv-y-lab mid">0</span>
      <span class="xv-y-lab bottom">${signed(-max)}</span>
      ${dots}
    </div>
    ${axis([list[0].date || '', '按开赛时间 →', list[list.length - 1].date || ''])}
    ${legend([['win', '胜'], ['loss', '负'], ['roll', '滚动常见值']])}
    <p class="xv-note">点一下进那局复盘；线是最近 ${chart.window || 5} 局的常见经济差。${allPoints.length > list.length ? `只画最近 ${list.length} 局（共 ${allPoints.length} 局可读）。` : ''}</p>`
  );
  const ratePts = list.map((p, i) => {
    const r = rolling[offset + i] || rolling[i] || {};
    return { x: xOf(i), y: num(r.winRate) ? H - 20 - r.winRate * (H - 40) : null };
  });
  const B = view(
    `<div class="xv-chartwrap">
      ${chartSvg(H, `${grid(H)}<line class="zero" x1="0" x2="1000" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>
        ${polyline(ratePts, 'winline', 2.4)}`)}
      <span class="xv-y-lab top">100%</span>
      <span class="xv-y-lab mid">50%</span>
      <span class="xv-y-lab bottom">0%</span>
    </div>
    ${axis([list[0].date || '', `滚动 ${chart.window || 10} 局胜率`, list[list.length - 1].date || ''])}
    <p class="xv-note">胜率按最近 10 局滚动；点少时线会断，是样本不足，不是 0。</p>`
  );
  return shell({ ...chart, id: chart.id || 'trend' }, ctx, '经济差走势', '滚动胜率', A, B);
}

/* ── 赢法画像：输/赢同刻度对照 ────────────────────────────────── */
function profile(chart, ctx) {
  const items = (chart.items || []).slice(0, 8);
  if (!items.length) return empty('还没有足够的胜负样本做赢输对照。');
  const rowsHtml = items.map((x) => {
    const m = x.kind === 'rate' ? 1 : Math.max(1e-9, Math.abs(num(x.win) ? x.win : 0), Math.abs(num(x.loss) ? x.loss : 0));
    const at = (v) => clamp((num(v) ? v : 0) / m, -1, 1) * 50;
    const left = at(x.loss), right = at(x.win);
    const diff = num(x.win) && num(x.loss) ? x.win - x.loss : null;
    return `<div class="xv-dumb-row" ${tip(`${x.label}：赢的局 ${x.winText}，输的局 ${x.lossText}；差 ${unit(diff, x.unit)}；覆盖 ${x.n} 局`)}>
      <span class="xv-row-label">${esc(x.label)}<small>${x.n} 局</small></span>
      <i class="xv-dumb-axis">
        <b class="xv-dumb-zero"></b>
        <b class="xv-dumb-link" style="left:${Math.min(50 + left, 50 + right).toFixed(1)}%;width:${Math.max(1.2, Math.abs(right - left)).toFixed(1)}%"></b>
        <b class="xv-dumb-dot loss" style="left:${(50 + left).toFixed(1)}%"></b>
        <b class="xv-dumb-dot win" style="left:${(50 + right).toFixed(1)}%"></b>
      </i>
      <span class="xv-dumb-values"><span class="loss">输 ${esc(x.lossText)}</span><span class="win">赢 ${esc(x.winText)}</span></span>
    </div>`;
  }).join('');
  const A = view(
    `<div class="xv-dumb">${rowsHtml}</div>
     <div class="xv-dumb-legend"><span><i style="background:var(--xc-loss)"></i>输的局</span><span><i style="background:var(--xc-win)"></i>赢的局</span></div>
     <p class="xv-note">同一行左右同刻度、不同行各自按本行量级缩放：看离中线的距离，不要跨行比长度。控龙率、团战胜率等比例项按 0–100% 刻度。</p>`
  );
  const ranked = items.slice().sort((a, b) => Math.abs(b.effect || 0) - Math.abs(a.effect || 0));
  const B = view(
    `<div class="xv-rows compact">${ranked.map((x) => `<div class="xv-row" ${tip(`${x.label} · ${x.winText} 对 ${x.lossText}`)}>
      <span class="xv-row-label">${esc(x.label)}<small>${x.repro === true ? '前后半同向' : x.repro === false ? '方向未复现' : '样本不足'}</small></span>
      <i class="xv-track"><b class="${num(x.effect) && x.effect < 0 ? 'neg' : ''}" style="width:${widthOf(x.effect, 1)}"></b></i>
      <em class="xv-row-val">${esc(x.kind === 'rate' ? `${signed((x.effect || 0) * 100)} 个百分点` : signed(x.effect, 2))}</em>
    </div>`).join('')}</div>
    <p class="xv-note">红点＝输局平均，绿点＝赢局平均；两点差得越远，这项在赢局和输局里越不一样。</p>`
  );
  return shell({ ...chart, id: chart.id || 'profile' }, ctx, '赢 / 输对照', '按差距排序', A, B);
}

/* ── 分布：P10–P90 区间 ───────────────────────────────────────── */
function distribution(chart, ctx) {
  const items = (chart.items || []).filter((x) => num(x.p50));
  if (!items.length) return empty('还没有足够的样本看范围。');
  const all = items.flatMap((x) => [x.p10, x.p90]).filter(num);
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const span = Math.max(1, hi - lo);
  const at = (v) => clamp((v - lo) / span * 100, 0, 100);
  const A = view(
    `<div class="xv-range">${items.map((x) => {
      const lowWord = x.unit === 'sec' ? '最短' : '最低';
      const highWord = x.unit === 'sec' ? '最长' : '最高';
      return `<div class="xv-range-row" ${tip(`${x.label}：${lowWord} ${unit(x.p10, x.unit)}，常见 ${unit(x.p50, x.unit)}，${highWord} ${unit(x.p90, x.unit)}；${x.n} 局`)}>
      <span class="xv-row-label">${esc(x.label)}<small>${x.n} 局</small></span>
      <span class="xv-range-main">
        <span class="xv-range-track">
          <b class="xv-range-zero" style="left:${at(0).toFixed(1)}%"></b>
          <b class="xv-range-band" style="left:${at(x.p10).toFixed(1)}%;width:${Math.max(0.8, at(x.p90) - at(x.p10)).toFixed(1)}%"></b>
          <b class="xv-range-mid" style="left:${at(x.p50).toFixed(1)}%"></b>
        </span>
        <span class="xv-range-ends"><span>${lowWord} ${esc(unit(x.p10, x.unit))}</span><span>${highWord} ${esc(unit(x.p90, x.unit))}</span></span>
      </span>
      <em class="xv-row-val">${esc(unit(x.p50, x.unit))}</em>
    </div>`;
    }).join('')}</div>
    <p class="xv-note">横条是中间 80% 的局（P10–P90），竖线是常见值（P50）；右侧数字也是常见值。先看范围有多宽，再看常见值。</p>`
  );
  const B = view(
    `<div class="xv-table-wrap"><table class="xv-table">
      <thead><tr><th>指标</th><th class="num">低端</th><th class="num">常见</th><th class="num">高端</th><th class="num">样本</th></tr></thead>
      <tbody>${items.map((x) => `<tr><td>${esc(x.label)}</td><td class="num">${esc(unit(x.p10, x.unit))}</td><td class="num"><b>${esc(unit(x.p50, x.unit))}</b></td><td class="num">${esc(unit(x.p90, x.unit))}</td><td class="num">${x.n}</td></tr>`).join('')}</tbody>
    </table></div>
    <p class="xv-note">低端 / 高端指 10% 分位，常见值指中位数；只描述分布，不解释原因。</p>`
  );
  return shell({ ...chart, id: chart.id || 'dist' }, ctx, '范围', '数字', A, B);
}

/* ── 经济路径：累计差 + 阶段净增 ─────────────────────────────── */
function path(chart, ctx) {
  const cps = chart.checkpoints || [];
  const phase = chart.phase || [];
  const all = cps.flatMap((c) => [c.win.med, c.loss.med, c.win.p25, c.win.p75, c.loss.p25, c.loss.p75]).filter(num);
  if (!all.length) return empty('还没有可读的经济曲线。');
  const H = 200;
  const max = Math.max(1000, ...all.map((v) => Math.abs(v)));
  const xOf = (i) => 30 + (i / Math.max(1, cps.length - 1)) * 940;
  const yOf = (v) => H / 2 - (v / max) * (H / 2 - 24);
  const band = (key, cls) => {
    const valid = cps.map((c, i) => ({ i, v: c[key].med, lo: c[key].p25, hi: c[key].p75 })).filter((x) => num(x.v) && num(x.lo) && num(x.hi));
    if (valid.length < 2) return '';
    const up = valid.map((x, k) => `${k ? 'L' : 'M'}${xOf(x.i).toFixed(1)},${yOf(x.hi).toFixed(1)}`).join(' ');
    const down = valid.slice().reverse().map((x) => `L${xOf(x.i).toFixed(1)},${yOf(x.lo).toFixed(1)}`).join(' ');
    return `<path class="band ${cls}" d="${up} ${down} Z"/>`;
  };
  const line = (key, cls) => polyline(cps.map((c, i) => ({ x: xOf(i), y: num(c[key].med) ? yOf(c[key].med) : null })), cls, 2.4);
  const A = view(
    `<div class="xv-chartwrap">
      ${chartSvg(H, `${grid(H)}<line class="zero" x1="0" x2="1000" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/>
        ${band('win', 'win')}${band('loss', 'loss')}${line('win', 'winline')}${line('loss', 'lossline')}`)}
      <span class="xv-y-lab top">${signed(max)}</span><span class="xv-y-lab mid">0</span><span class="xv-y-lab bottom">${signed(-max)}</span>
    </div>
    ${axis(cps.map((c) => `${c.minute}′`))}
    ${legend([['win', '赢的局'], ['loss', '输的局']])}
    <p class="xv-note">每个点是该分钟的常见经济差；色带是多数局的波动范围。样本随分钟变少，最后几分钟只作参考。</p>`
  );
  const pmax = Math.max(1, ...phase.flatMap((p) => [Math.abs(p.win || 0), Math.abs(p.loss || 0)]));
  const B = view(
    `<div class="xv-phases">${phase.map((p) => `<div class="xv-phase" ${tip(`${p.label}：赢的局常见净增 ${signed(p.win)}，输的局 ${signed(p.loss)}`)}>
      <span class="xv-phase-label">${esc(p.label)}</span>
      <div class="xv-phase-bars">
        <i class="xv-phase-bar win" style="width:${widthOf(p.win, pmax)}"></i>
        <i class="xv-phase-bar loss" style="width:${widthOf(p.loss, pmax)}"></i>
      </div>
      <span class="xv-phase-vals"><b class="win">${signed(p.win)}</b><b class="loss">${signed(p.loss)}</b></span>
    </div>`).join('')}</div>
    ${legend([['win', '赢的局'], ['loss', '输的局']])}
    <p class="xv-note">阶段净增 = 该阶段结束时的经济差 − 阶段开始时的经济差；三段相加约等于终局差。</p>`
  );
  return shell({ ...chart, id: chart.id || 'path' }, ctx, '累计路径', '阶段净增', A, B);
}

/* ── 五路：区间 + 领先率 ──────────────────────────────────────── */
function laneRange(chart, ctx) {
  const lanes = chart.lanes || [];
  if (!lanes.length) return empty('还没有同位置双方都有的对局。');
  const all = lanes.flatMap((x) => [x.p10, x.p90]).filter(num);
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const span = Math.max(1, hi - lo);
  const at = (v) => clamp((v - lo) / span * 100, 0, 100);
  const A = view(
    `<div class="xv-range">${lanes.map((x) => `<div class="xv-range-row" ${tip(`${x.lane}：常见 ${unit(x.med, 'perMin')}，最差 10% ${unit(x.p10, 'perMin')}，最好 10% ${unit(x.p90, 'perMin')}；领先 ${pct(x.aheadRate)}（${x.ahead}/${x.n} 局）`)}>
      <span class="xv-row-label">${esc(x.lane)}<small>${x.n} 局</small></span>
      <span class="xv-range-main">
        <span class="xv-range-track">
          <b class="xv-range-zero" style="left:${at(0).toFixed(1)}%"></b>
          <b class="xv-range-band" style="left:${at(x.p10).toFixed(1)}%;width:${Math.max(0.8, at(x.p90) - at(x.p10)).toFixed(1)}%"></b>
          <b class="xv-range-mid" style="left:${at(x.med).toFixed(1)}%"></b>
        </span>
        <span class="xv-range-ends"><span>${signed(x.p10)}</span><span>${signed(x.p90)}</span></span>
      </span>
      <em class="xv-row-val ${signedCls(x.med)}">${signed(x.med)}</em>
    </div>`).join('')}</div>
    <p class="xv-note">单位：金币/分（本队同位置减对手）。竖线是常见值，绿/红点在零线两侧。</p>`
  );
  const B = view(
    `<div class="xv-table-wrap"><table class="xv-table">
      <thead><tr><th>分路</th><th class="num">常见</th><th class="num">最差 10%</th><th class="num">领先率</th><th class="num">领先时胜率</th><th class="num">落后时胜率</th><th class="num">输出/承伤差</th></tr></thead>
      <tbody>${lanes.map((x) => `<tr><td>${esc(x.lane)}</td><td class="num ${signedCls(x.med)}">${signed(x.med)}</td><td class="num">${signed(x.p10)}</td><td class="num">${pct(x.aheadRate)}</td><td class="num">${x.winAhead.n ? pct(x.winAhead.value) : '—'}</td><td class="num">${x.winBehind.n ? pct(x.winBehind.value) : '—'}</td><td class="num">${signed(x.damage)} / ${signed(x.taken)}</td></tr>`).join('')}</tbody>
    </table></div>
    <p class="xv-note">领先/落后按该路经济差正负分；胜率分母是该状态下分出胜负的局。</p>`
  );
  return shell({ ...chart, id: chart.id || 'lanes' }, ctx, '分路区间', '领先与胜率', A, B);
}

/* ── 兑现漏斗 ─────────────────────────────────────────────────── */
function funnel(chart, ctx) {
  const steps = chart.steps || [];
  if (!steps.length) return empty('还没有可算的领先兑现样本。');
  const max = Math.max(1, ...steps.map((s) => s.rate.value || 0));
  const A = view(
    `<div class="xv-funnel">${steps.map((s) => `<div class="xv-funnel-row" ${tip(`${s.label}：${s.wins}/${s.n} 局获胜（${pct(s.rate.value)}）`)}>
      <span class="xv-row-label">${esc(s.label)}<small>${s.wins}/${s.n} 局</small></span>
      <i class="xv-track"><b style="width:${widthOf(s.rate.value, max)}"></b></i>
      <em class="xv-row-val">${pct(s.rate.value)}</em>
    </div>`).join('')}</div>
    <p class="xv-note">每一步都是「10 分钟领先的局里满足该条件的子集」，不是因果链；子集样本会变少。</p>`
  );
  const B = view(
    `<div class="xv-table-wrap"><table class="xv-table">
      <thead><tr><th>条件</th><th class="num">局数</th><th class="num">胜</th><th class="num">胜率</th><th class="num">可信范围</th></tr></thead>
      <tbody>${steps.map((s) => `<tr><td>${esc(s.label)}</td><td class="num">${s.n}</td><td class="num">${s.wins}</td><td class="num"><b>${pct(s.rate.value)}</b></td><td class="num">${s.rate.ci ? `${pct(s.rate.ci[0])}–${pct(s.rate.ci[1])}` : '—'}</td></tr>`).join('')}</tbody>
    </table></div>`
  );
  return shell({ ...chart, id: chart.id || 'funnel' }, ctx, '兑现率', '读数', A, B);
}

/* ── 团战：分桶 + 伤害结构 ────────────────────────────────────── */
function fight(chart, ctx) {
  const buckets = [
    ['多打少', chart.adv], ['人数相同', chart.even], ['少打多', chart.dis],
    ['我们先拿首杀', chart.first], ['对方先拿首杀', chart.firstAgainst],
  ].filter(([, x]) => x && x.n > 0);
  const damage = (chart.damage || []).filter((x) => x && num(x.hurt));
  if (!buckets.length && !damage.length) return empty('还没有可读的团战数据。');
  const A = buckets.length ? view(
    `<div class="xv-rows compact">${buckets.map(([label, x]) => `<div class="xv-row" ${tip(`${label}：${x.wins}/${x.n} 波获胜（${pct(x.rate.value)}）`)}>
      <span class="xv-row-label">${esc(label)}<small>${x.wins}/${x.n} 波</small></span>
      <i class="xv-track"><b style="width:${widthOf(x.rate.value, 1)}"></b></i>
      <em class="xv-row-val">${pct(x.rate.value)}</em>
    </div>`).join('')}</div>
    <p class="xv-note">只统计有击杀的团战；零击杀的拉扯团不计入胜率分母。</p>`
  ) : empty('没有分桶团战数据。');
  const B = damage.length ? view(
    `<div class="xv-table-wrap"><table class="xv-table">
      <thead><tr><th>分路</th><th class="num">团战伤害占比</th><th class="num">团战承伤占比</th><th class="num">样本</th></tr></thead>
      <tbody>${damage.map((x) => `<tr><td>${esc(x.lane)}</td><td class="num">${pct(x.hurt)}</td><td class="num">${pct(x.taken)}</td><td class="num">${x.n}</td></tr>`).join('')}</tbody>
    </table></div>
    <p class="xv-note">占比是同一条路在每波团里占我方总伤害/总承伤的平均值；每条路独立，不能相加。</p>`
  ) : empty('没有团战伤害结构。');
  return shell({ ...chart, id: chart.id || 'fight' }, ctx, '团战分桶', '伤害结构', A, B);
}

/* ── 通用条形列表（英雄池、ban、对手英雄）───────────────────── */
function bars(chart, ctx) {
  const items = (chart.items || []).filter((x) => x && num(x.value));
  if (!items.length) return empty(chart.empty || '还没有样本。');
  const max = Math.max(1, ...items.map((x) => Math.abs(x.value)));
  const itemUnit = (x) => unit(x.value, x.unit || chart.unit);
  const A = view(
    `<div class="xv-rows compact">${items.map((x) => `<div class="xv-row" ${tip(x.tip || `${x.label} · ${itemUnit(x)}`)}>
      <span class="xv-row-label">${esc(x.label)}${x.sub ? `<small>${esc(x.sub)}</small>` : ''}</span>
      <i class="xv-track"><b class="${num(x.value) && x.value < 0 ? 'neg' : ''}" style="width:${widthOf(x.value, max)}"></b></i>
      <em class="xv-row-val">${esc(itemUnit(x))}</em>
    </div>`).join('')}</div>
    ${chart.note ? `<p class="xv-note">${esc(chart.note)}</p>` : ''}`
  );
  const B = view(
    `<div class="xv-table-wrap"><table class="xv-table">
      <thead><tr><th>项目</th><th class="num">读数</th><th class="num">样本</th></tr></thead>
      <tbody>${items.map((x) => `<tr><td>${esc(x.label)}</td><td class="num">${esc(itemUnit(x))}</td><td class="num">${x.n == null ? '—' : x.n}</td></tr>`).join('')}</tbody>
    </table></div>`
  );
  return shell({ ...chart, id: chart.id || 'bars' }, ctx, '条形', '读数', A, B);
}

const RENDERERS = { trend, profile, distribution, path, laneRange, funnel, fight, bars };

export function renderViz(chart, ctx = {}) {
  if (!chart || !chart.type) return '';
  const fn = RENDERERS[chart.type];
  return fn ? fn(chart, ctx) : '';
}
