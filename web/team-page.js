/* 团队复盘：一屏回答「我们强在哪、输在哪、下一步练什么」。
   原则：先给结论，再给证据；样本不足时明说，不拿 1 场当规律。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
const signed = (value, digits = 0) => {
  if (!Number.isFinite(Number(value)) || value === null) return '—';
  const v = Number(value);
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}`;
};

const PHASES = [
  {key: 'early', label: '前期', range: '0–4 分', tone: 'early'},
  {key: 'mid', label: '中期', range: '4–10 分', tone: 'mid'},
  {key: 'late', label: '后期', range: '10 分以后', tone: 'late'},
];

function economyChart(matches) {
  const series = matches.filter(m => (m.points || []).length > 1);
  if (!series.length) return '<div class="tp-empty">还没有可用于画曲线的经济时间轴。</div>';
  const W = 940, H = 320, L = 62, R = 26, T = 20, B = 40;
  const maxT = Math.max(...series.map(m => m.points[m.points.length - 1][0]), 600);
  const allDiffs = series.flatMap(m => m.points.map(p => p[1]));
  const bound = Math.max(2000, Math.max(...allDiffs.map(Math.abs)));
  const pad = bound * 0.12;
  const yMax = bound + pad, yMin = -bound - pad;
  const x = t => L + (t / maxT) * (W - L - R);
  const y = v => T + (yMax - v) / (yMax - yMin) * (H - T - B);

  const ticks = [];
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (yMax - yMin) * i / 4;
    ticks.push(`<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#eef2f8"/>
      <text x="${L - 9}" y="${y(v) + 3.5}" text-anchor="end" fill="#98a3b4" font-size="10.5">${signed(v)}</text>`);
  }
  const bands = [[0, 240, '前期'], [240, 600, '中期'], [600, maxT, '后期']].map(([a, b, label]) => {
    if (a >= maxT) return '';
    const x1 = x(a), x2 = x(Math.min(b, maxT));
    return `<rect x="${x1}" y="${T}" width="${Math.max(0, x2 - x1)}" height="${H - T - B}" fill="#f8fafd"/>
      <text x="${(x1 + x2) / 2}" y="${T + 12}" text-anchor="middle" fill="#aab4c4" font-size="10.5">${label}</text>`;
  }).join('');
  const zero = `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="#c9d3e3" stroke-dasharray="3 3"/>`;
  const paths = series.map((m, i) => {
    const color = i === 0 ? '#2f6fe4' : ['#7c9cf0', '#9db4e8', '#b6c7ea'][i % 3];
    const d = m.points.map((p, idx) => `${idx ? 'L' : 'M'}${x(p[0])} ${y(p[1])}`).join(' ');
    const last = m.points[m.points.length - 1];
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" opacity="${i === 0 ? 1 : .5}"/>
      <circle cx="${x(last[0])}" cy="${y(last[1])}" r="3" fill="${color}"/>`;
  }).join('');
  const xTicks = [0, 4, 10, 15, 20].filter(t => t <= maxT / 60 || t === 0)
    .map(m => `<text x="${x(m * 60)}" y="${H - B + 18}" text-anchor="middle" fill="#98a3b4" font-size="10.5">${m}分</text>`).join('');
  const legend = series.length > 1
    ? `<div class="tp-chart-legend">${series.slice(0, 4).map((m, i) => `<span><i style="background:${i === 0 ? '#2f6fe4' : '#9db4e8'}"></i>${esc(m.opponent ? 'vs ' + m.opponent : m.date || `第 ${i + 1} 场`)}</span>`).join('')}${series.length > 4 ? `<span>…共 ${series.length} 场</span>` : ''}</div>`
    : '';
  return `<svg viewBox="0 0 ${W} ${H}" class="tp-chart" role="img" aria-label="经济差随时间变化">${bands}${ticks}${zero}${paths}${xTicks}</svg>
    ${legend}
    <p class="tp-chart-note">纵轴为本队 − 对手经济差；线上方为领先。阴影分区是复盘用的三段口径。</p>`;
}

function verdictCards(aggregate, matches, quality) {
  const cards = [];
  const games = Number(aggregate.games) || 0;

  if (aggregate.leadAt10Games) {
    const conv = aggregate.leadAt10Conversion;
    cards.push({
      tone: conv != null && conv >= 70 ? 'good' : 'warn',
      label: '10 分钟领先转化',
      value: conv == null ? '—' : `${num(conv, 0)}%`,
      note: `${num(aggregate.leadAt10Games)} 场 10 分钟领先，赢下 ${num(Math.round(aggregate.leadAt10Games * (conv || 0) / 100))} 场`,
      verdict: '对照领先后赢下与输掉的场次',
    });
  }
  if (aggregate.blownLeads) {
    cards.push({tone: 'bad', label: '被翻盘', value: num(aggregate.blownLeads), note: '领先 2,000 以上仍输掉', verdict: '需要复盘中期决策'});
  }
  if (aggregate.comebacks) {
    cards.push({tone: 'good', label: '翻盘', value: num(aggregate.comebacks), note: '落后 2,000 以上仍赢下', verdict: '回看经济差回升的区间'});
  }
  const d10 = aggregate.avgDiffAt?.['600'];
  if (d10 != null) {
    cards.push({
      tone: d10 >= 0 ? 'good' : 'bad', label: '10 分钟经济差',
      value: signed(d10), note: `${num(aggregate.landmarkSamples?.['600'])} 场均值`,
      verdict: d10 >= 0 ? '前中期节奏在我们这边' : '前中期被压，需要看对线与打野节奏',
    });
  }
  if (quality?.score != null) {
    const gaps = (quality.checks || []).filter(c => c.missing > 0);
    cards.push({
      tone: quality.score >= 75 ? 'good' : 'warn', label: '档案字段覆盖',
      value: `${num(quality.score)}%`, note: gaps.length ? gaps.map(g => g.label).slice(0, 2).join('、') + ' 缺失' : '检查字段齐全',
      verdict: '按当前对局范围计算',
    });
  }
  return cards.map(c => `<article class="tp-verdict ${c.tone}">
    <span>${esc(c.label)}</span>
    <b>${c.value}</b>
    <small>${esc(c.note)}</small>
    <em>${esc(c.verdict)}</em>
  </article>`).join('');
}

function phaseTable(aggregate, matches) {
  const phases = aggregate.avgPhases || {};
  const rows = PHASES.map(p => {
    const value = phases[p.key];
    const tone = value == null ? 'dim' : value >= 0 ? 'up' : 'down';
    return `<div class="tp-phase ${p.tone}">
      <div class="tp-phase-head"><strong>${p.label}</strong><span>${p.range}</span></div>
      <b class="${tone}">${value == null ? '—' : signed(value)}</b>
      <small>${value == null ? '该段没有可算的经济差' : '段末经济差'}</small>
    </div>`;
  }).join('');
  const observed = matches.map(m => m.observedEnd).filter(Number.isFinite);
  const ended = observed.length ? Math.max(...observed) / 60 : null;
  return `<div class="tp-phases">${rows}</div>
    <p class="tp-chart-note">${ended == null ? '' : `当前最长可观测到 ${num(ended, 1)} 分钟；`}三段口径为 0–4 / 4–10 / 10+，与赛训组复盘表一致。</p>`;
}

function strengthList(aggregate, matches, quality) {
  const items = [];
  const d10 = aggregate.avgDiffAt?.['600'];
  if (d10 != null) {
    items.push(d10 >= 1500
      ? {tone: 'good', title: '前 10 分钟能建立优势', detail: `10 分钟平均 ${signed(d10)}，说明对线期与第一波资源节奏有效。`}
      : d10 <= -1500
        ? {tone: 'bad', title: '前 10 分钟吃亏', detail: `10 分钟平均 ${signed(d10)}，优先复盘对线细节与打野第一轮路线。`}
        : {tone: 'warn', title: '前 10 分钟基本五五开', detail: `10 分钟平均 ${signed(d10)}，胜负更多取决于中期决策。`});
  }
  if (aggregate.leadAt10Games && aggregate.leadAt10Conversion != null) {
    items.push(aggregate.leadAt10Conversion >= 70
      ? {tone: 'good', title: '领先局收得住', detail: `${num(aggregate.leadAt10Games)} 场领先局转化率 ${num(aggregate.leadAt10Conversion, 0)}%。`}
      : {tone: 'bad', title: '领先局收不住', detail: `领先局转化率仅 ${num(aggregate.leadAt10Conversion, 0)}%，重点看 10–15 分钟的推进与开团选择。`});
  }
  const gaps = (quality?.checks || []).filter(c => c.missing > 0);
  if (gaps.length) {
    items.push({
      tone: 'warn', title: '结论的适用范围有限',
      detail: `${gaps.map(g => `${g.label} 缺 ${g.missing}/${g.total}`).join('；')}。补齐后这些判断会重新计算。`,
    });
  }
  if (!items.length) {
    items.push({tone: 'warn', title: '还不足以判断强弱项', detail: '需要「时间轴 + 时长」同时具备的对局，建议先补全档案。'});
  }
  return items.map(i => `<div class="tp-strength ${i.tone}">
    <span class="tp-dot"></span>
    <div><strong>${esc(i.title)}</strong><p>${esc(i.detail)}</p></div>
  </div>`).join('');
}

export async function renderTeam(container, {api, workspace, isCurrent, query}) {
  const [processData, matchesView] = await Promise.all([
    api('/api/studio/view/process' + query()),
    api('/api/studio/view/matches' + query() + '&limit=1'),
  ]);
  if (isCurrent && !isCurrent()) return;
  const teamName = workspace?.overview?.teamName || '本队';
  const aggregate = processData.aggregate || {};
  const matches = processData.matches || [];
  const summary = matchesView.summary || {};
  const quality = processData.dataQuality;
  const total = Number(matchesView.total) || 0;
  const wins = Number(summary.wins) || 0;
  const losses = Number(summary.losses) || 0;
  const games = Number(aggregate.games) || 0;
  const coverage = total ? Math.round(games / total * 100) : 0;

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">TEAM · 团队复盘</span>
        <h1>${esc(teamName)} 团队复盘</h1>
        <p>先看结论，再看证据。所有判断都标注样本量；样本不够时只说方向。</p>
        <div class="page-facts">
          <span>${num(total)} 场记录</span>
          <span>${num(wins)} 胜 ${num(losses)} 负</span>
          <span>${num(games)} 场可做经济分析（${num(coverage)}%）</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#matches">比赛档案</a>
        <button class="button" data-print>打印 / PDF</button>
      </div>
    </div>

    ${!games ? `<div class="ar-empty"><strong>还没有可复盘的完整对局</strong>
      <p>团队复盘需要「经济时间轴 + 比赛时长」。当前 ${num(total)} 场里 ${num(games)} 场满足，请检查经济时间轴或调整筛选条件。</p>
      <a class="button primary" href="#matches">去补全档案</a></div>`
    : `<section class="tp-verdicts">${verdictCards(aggregate, matches, quality)}</section>

      <section class="tp-card">
        <header><h2>经济差走势</h2><p>横轴是局内时间，纵轴是本队 − 对手。看三条线：什么时候领先、什么时候被追、什么时候拉开。</p></header>
        ${economyChart(matches)}
      </section>

      <div class="tp-two">
        <section class="tp-card">
          <header><h2>三段经济</h2><p>段末经济差，正数代表我们领先</p></header>
          ${phaseTable(aggregate, matches)}
        </section>
        <section class="tp-card">
          <header><h2>强弱项判断</h2><p>由上方数据自动推导，样本不足会标注</p></header>
          <div class="tp-strengths">${strengthList(aggregate, matches, quality)}</div>
        </section>
      </div>

      <section class="tp-card tp-next">
        <header><h2>下一步</h2><p>按优先级排列</p></header>
        <ol class="tp-todo">
          ${(quality?.checks || []).filter(c => c.missing > 0).slice(0, 3).map(c =>
            `<li><strong>补齐${esc(c.label)}</strong><span>${esc(c.hint)}（缺 ${c.missing}/${c.total}）</span><a href="#matches">去补 →</a></li>`).join('')
            || '<li><strong>档案已齐</strong><span>可以开始逐局复盘与对手准备。</span><a href="#featured">看精选对局 →</a></li>'}
        </ol>
      </section>`}
  `;
}
