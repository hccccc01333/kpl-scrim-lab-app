/* BP 分析模块：五个功能分区 + 图表可视化。工作台 #bp 专用。 */
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value))
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits}) : '—';
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const duration = seconds => {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return '';
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
};

const TABS = [
  {key: 'overview', no: '01', name: '总览', desc: '结论与全局指标'},
  {key: 'matches', no: '02', name: '逐局 BP', desc: '每局双方禁用与阵容'},
  {key: 'heroes', no: '03', name: '英雄热度', desc: '禁用 · 选用 · 针对度'},
  {key: 'comps', no: '04', name: '阵容体系', desc: '五人阵容 · 共现 · 分路'},
  {key: 'context', no: '05', name: '对手与赛果', desc: '对手习惯 · 蓝红方 · 手序'},
  {key: 'depth', no: '06', name: '深度洞察', desc: '营地全量 · 独立口径'},
];

function heroIcons(catalog) {
  return Object.fromEntries(((catalog?.entries) || []).filter(e => e.kind === 'hero' && e.icon).map(e => [e.name, e.icon]));
}

function face(name, icons, meta, cls = 'bp2-face') {
  const info = (meta && meta[name]) || {};
  const src = info.icon || icons[name] || (info.id ? `/catalog/icons/hero-${info.id}.png` : '');
  const initial = esc(String(name || '?')[0]);
  // 离线免安装包拿不到营地兜底 URL 时退回首字方块，不留破图
  return `<span class="${cls}" title="${esc(name)}" data-initial="${initial}">${src
    ? `<img src="${esc(src)}" alt="${esc(name)}" onerror="this.parentElement.classList.add('is-missing');this.remove()">`
    : `<b>${initial}</b>`}</span>`;
}

function panel(title, sub, body, pill, extra = '') {
  return `<section class="panel bp2-card ${extra}"><div class="panel-head"><div><h2>${esc(title)}</h2><p>${esc(sub)}</p></div>${pill ? `<span class="pill">${esc(pill)}</span>` : ''}</div><div class="panel-body">${body || '<div class="empty-state">暂无数据</div>'}</div></section>`;
}

/* ---------- 图表 ---------- */

/* 禁用压力象限：横轴出场、纵轴禁用，气泡用官方头像裁切 */
function scatterSvg(pressure, icons, meta) {
  const items = (pressure || []).slice(0, 26);
  if (!items.length) return '<div class="empty-state">没有禁用压力数据。</div>';
  const W = 820, H = 340, L = 54, R = 26, T = 22, B = 48;
  const maxX = Math.max(4, ...items.map(x => Number(x.picks) || 0));
  const maxY = Math.max(4, ...items.map(x => Number(x.bans) || 0));
  const px = v => L + (v / maxX) * (W - L - R);
  const py = v => H - B - (v / maxY) * (H - T - B);
  const midX = maxX / 2, midY = maxY / 2;
  const xm = px(midX), ym = py(midY);
  const quads = `
    <rect x="${L}" y="${T}" width="${xm - L}" height="${ym - T}" fill="#fdf5e6"/>
    <rect x="${xm}" y="${T}" width="${W - R - xm}" height="${ym - T}" fill="#f3f0fb"/>
    <rect x="${L}" y="${ym}" width="${xm - L}" height="${H - B - ym}" fill="#f8fafc"/>
    <rect x="${xm}" y="${ym}" width="${W - R - xm}" height="${H - B - ym}" fill="#ecf9f7"/>`;
  const ticks = [0, maxX / 2, maxX].map(v => `<line x1="${px(v)}" y1="${T}" x2="${px(v)}" y2="${H - B}" stroke="#e6ebf3" stroke-dasharray="3 4"/><text x="${px(v)}" y="${H - B + 18}" text-anchor="middle" class="bp2-ax">${num(v)}</text>`).join('')
    + [0, maxY / 2, maxY].map(v => `<line x1="${L}" y1="${py(v)}" x2="${W - R}" y2="${py(v)}" stroke="#e6ebf3" stroke-dasharray="3 4"/><text x="${L - 10}" y="${py(v) + 4}" text-anchor="end" class="bp2-ax">${num(v)}</text>`).join('');
  const axis = `<line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="#cbd5e3"/><line x1="${L}" y1="${T}" x2="${L}" y2="${H - B}" stroke="#cbd5e3"/>`;
  const labels = `
    <text x="${L}" y="14" class="bp2-ax-title">↑ 禁用次数</text>
    <text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle" class="bp2-ax-title">选用次数 →</text>`;
  const ranked = [...items].sort((a, b) => (b.bans + b.picks) - (a.bans + a.picks)).slice(0, 8).map(x => x.hero);
  const defs = [], dots = [], placed = [];
  items.forEach((item, i) => {
    const x = px(Number(item.picks) || 0), y = py(Number(item.bans) || 0);
    const r = clamp(7 + Math.sqrt(Number(item.appearance) || 1) * 2.1, 8, 17);
    const info = (meta && meta[item.hero]) || {};
    const src = info.icon || icons[item.hero] || (info.id ? `/catalog/icons/hero-${info.id}.png` : '');
    const cid = `bp2-clip-${i}`;
    const hot = Number(item.banRate) >= 70;
    const stroke = hot ? '#d79b32' : '#2fa89c';
    defs.push(`<clipPath id="${cid}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}"/></clipPath>`);
    const labelY = y + r + 13;
    const showLabel = ranked.includes(item.hero) && labelY < H - B + 6
      && !placed.some(pos => Math.abs(pos.y - labelY) < 16 && Math.abs(pos.x - x) < 78);
    if (showLabel) placed.push({x, y: labelY});
    dots.push(`<g class="bp2-dot"><title>${esc(item.hero)} · 禁用 ${num(item.bans)} / 选用 ${num(item.picks)} / 禁用率 ${num(item.banRate)}%</title>`
      + `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r + 2).toFixed(1)}" fill="#fff" stroke="${stroke}" stroke-width="2"/>`
      + (src ? `<image href="${esc(src)}" x="${(x - r).toFixed(1)}" y="${(y - r).toFixed(1)}" width="${(2 * r).toFixed(1)}" height="${(2 * r).toFixed(1)}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${cid})"/>`
        : `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="#dfe7f2"/><text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="middle" class="bp2-ax">${esc(String(item.hero)[0])}</text>`)
      + (showLabel ? `<text x="${x.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" class="bp2-dot-label">${esc(item.hero)}</text>` : '')
      + '</g>');
  });
  return `<svg class="bp2-svg bp2-scatter" viewBox="0 0 ${W} ${H}" role="img" aria-label="禁用压力象限图"><defs>${defs.join('')}</defs>${quads}${ticks}${axis}${dots.join('')}${labels}</svg>`
    + `<div class="bp2-quad-legend"><span><i style="background:#fdf5e6"></i>高禁 · 低选 <b>被针对</b></span><span><i style="background:#f3f0fb"></i>高禁 · 高选 <b>争夺</b></span><span><i style="background:#ecf9f7"></i>低禁 · 高选 <b>放养</b></span><span><i style="background:#f8fafc"></i>低热度</span><small>悬停气泡可看具体数字</small></div>`;
}

/* 双人共现热力矩阵 */
function pairMatrix(pairs, icons, meta) {
  const weight = new Map();
  (pairs || []).forEach(p => {
    weight.set(p.a, (weight.get(p.a) || 0) + p.n);
    weight.set(p.b, (weight.get(p.b) || 0) + p.n);
  });
  const heroes = [...weight.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(e => e[0]);
  if (heroes.length < 2) return '<div class="empty-state">共现样本不足。</div>';
  const lookup = new Map();
  (pairs || []).forEach(p => { lookup.set(`${p.a}|${p.b}`, p.n); lookup.set(`${p.b}|${p.a}`, p.n); });
  const max = Math.max(1, ...(pairs || []).map(p => p.n));
  const head = '<div class="bp2-mx-corner">共现</div>' + heroes.map(h => `<div class="bp2-mx-head">${face(h, icons, meta, 'bp2-face is-tiny')}<span>${esc(h)}</span></div>`).join('');
  const rows = heroes.map(a => `<div class="bp2-mx-rowhead">${face(a, icons, meta, 'bp2-face is-tiny')}<span>${esc(a)}</span></div>` + heroes.map(b => {
    if (a === b) return '<div class="bp2-mx-cell is-diag">·</div>';
    const v = lookup.get(`${a}|${b}`) || 0;
    const alpha = v ? (0.14 + 0.72 * v / max).toFixed(2) : 0;
    return `<div class="bp2-mx-cell" ${v ? `style="background:rgba(47,111,228,${alpha})"` : ''} title="${esc(a)} + ${esc(b)} · 共现 ${num(v)} 次"><span>${v || ''}</span></div>`;
  }).join('')).join('');
  return `<div class="bp2-matrix" style="--mx-cols:${heroes.length}">${head}${rows}</div>`
    + '<div class="bp2-legend"><span class="bp2-legend-scale"><i style="background:#f1f5fb"></i><i style="background:rgba(47,111,228,.25)"></i><i style="background:rgba(47,111,228,.55)"></i><i style="background:rgba(47,111,228,.86)"></i></span>少 → 多　格子数字 = 同队共现场次</div>';
}

/* 环形图 */
function ringSvg(segments, center, sub) {
  const r = 44, c = 2 * Math.PI * r;
  let offset = 0;
  const arcs = segments.filter(s => s.value > 0).map(s => {
    const len = c * s.value / Math.max(1, segments.reduce((sum, x) => sum + x.value, 0));
    const arc = `<circle cx="60" cy="60" r="${r}" fill="none" stroke="${s.color}" stroke-width="15" stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 60 60)"/>`;
    offset += len;
    return arc;
  }).join('');
  return `<div class="bp2-ring"><svg viewBox="0 0 120 120" role="img" aria-label="${esc(center)}"><circle cx="60" cy="60" r="${r}" fill="none" stroke="#eef2f8" stroke-width="15"/>${arcs}<text x="60" y="58" text-anchor="middle" class="bp2-ring-value">${esc(center)}</text><text x="60" y="76" text-anchor="middle" class="bp2-ring-sub">${esc(sub)}</text></svg></div>`;
}

/* 分路禁用/选用堆叠条 */
function laneChart(lanes, icons, meta) {
  const max = Math.max(1, ...(lanes || []).map(x => (x.bans || 0) + (x.picks || 0)));
  return `<div class="bp2-lanes">${(lanes || []).map(item => {
    const b = item.bans || 0, p = item.picks || 0;
    const heroes = (item.heroes || []).slice(0, 3).map(([name]) => face(name, icons, meta, 'bp2-face is-tiny')).join('');
    return `<div class="bp2-lane"><strong>${esc(item.lane)}</strong>
      <div class="bp2-stack"><i class="is-ban" style="width:${(b / max * 100).toFixed(1)}%"></i><i class="is-pick" style="width:${(p / max * 100).toFixed(1)}%"></i></div>
      <span class="bp2-lane-num">禁 ${num(b)} · 选 ${num(p)}</span><div class="bp2-lane-faces">${heroes}</div></div>`;
  }).join('')}</div><div class="bp2-legend"><span><i style="background:#d79b32"></i>禁用</span><span><i style="background:#2fa89c"></i>选用</span><small>条长按同一标尺，可直接跨分路比较</small></div>`;
}

/* 蓝红方对比 + 胜率环 */
function sideChart(sides) {
  const l = sides.left || {}, r = sides.right || {};
  const max = Math.max(1, l.bans || 0, r.bans || 0, l.picks || 0, r.picks || 0);
  const bar = (label, a, b) => `<div class="bp2-vs"><em>${label}</em>
    <span class="bp2-vs-left"><i style="width:${((a || 0) / max * 100).toFixed(1)}%"></i></span><b>${num(a || 0)}</b>
    <span class="bp2-vs-right"><i style="width:${((b || 0) / max * 100).toFixed(1)}%"></i></span><b>${num(b || 0)}</b></div>`;
  return `<div class="bp2-side-chart">
    <div class="bp2-side-head"><span>左方 / 蓝</span><span>右方 / 红</span></div>
    ${bar('禁用', l.bans, r.bans)}${bar('选用', l.picks, r.picks)}
    <div class="bp2-rings">${ringSvg([{value: l.winRate || 0, color: '#3b78e0'}], `${num(l.winRate || 0)}%`, '左方胜率')}
      ${ringSvg([{value: r.winRate || 0, color: '#e0645c'}], `${num(r.winRate || 0)}%`, '右方胜率')}</div>
    <div class="bp2-inline-note">胜率按阵营统计，样本含偏差时仅作描述，不用于判断阵营强弱。</div></div>`;
}

/* 手序柱 */
function orderChart(orders, firstPick, manualN) {
  const bars = (orders || []).map(item => {
    const pct = item.n ? item.wins / item.n * 100 : 0;
    return `<div class="bp2-obar"><div class="bp2-obar-track"><i style="height:${item.n ? Math.max(8, pct).toFixed(1) : 0}%"></i></div>
      <b>${item.n ? `${num(pct, 0)}%` : '—'}</b><span>第 ${num(item.order)} 手</span><small>${num(item.n)} 场</small></div>`;
  }).join('');
  const first = (firstPick || []).length ? `<div class="bp2-subhead">先后手</div><div class="bp2-first">${firstPick.map(item => `<div><strong>${esc(item.label)}</strong><b>${item.n ? `${num(item.winRate)}%` : '—'}</b><small>${num(item.wins)} 胜 / ${num(item.n)} 场</small></div>`).join('')}</div>` : '';
  const note = manualN ? '' : '<div class="bp2-inline-note is-strong">营地终局名单不含 pick 顺序与一手方；本功能当前 0 场人工录入，需要在「比赛校对」页按 1–5 楼手序填写 BP 后才有数据。</div>';
  return note + `<div class="bp2-obars">${bars}</div>${first}`;
}

/* 榜单行 */
function rankRow(item, max, note, tone, icons, meta) {
  const count = Number(item.count) || 0;
  return `<div class="bp2-rank ${tone}">${face(item.hero, icons, meta, 'bp2-face is-row')}
    <div class="bp2-rank-main"><div class="bp2-rank-top"><strong>${esc(item.hero)}</strong><b>${num(count)}</b></div>
    <div class="bp2-track"><i style="width:${(count / max * 100).toFixed(1)}%"></i></div><small>${note}</small></div></div>`;
}

export async function renderBp(container, {api, isCurrent, query}) {
  const [data, catalog] = await Promise.all([
    api('/api/studio/view/bp' + query()),
    api('/api/catalog').catch(() => ({entries: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const icons = heroIcons(catalog), meta = data.heroMeta || {};
  const ico = (name, cls) => face(name, icons, meta, cls);
  const bans = data.bans || [], picks = data.ownPicks || [], enemies = data.enemyPicks || [];
  const orders = data.orderEffect || [], opponents = data.opponents || [], rows = data.matches || [];
  const pressure = data.pressure || [], lanes = data.lanes || [], pairs = data.pairs || [];
  const comps = data.compositions || [], sides = data.sides || {};
  const totals = data.totals || {}, n = Number(data.matchesWithBp) || 0;
  const manualN = Number(data.manualBpMatches) || 0, campN = Number(data.campBpMatches) || 0;
  const topBan = bans[0], topPick = picks[0];
  const topLane = [...lanes].sort((a, b) => (b.bans || 0) - (a.bans || 0))[0];

  const headline = topBan
    ? `${n} 场 BP 里，${topBan.hero}被禁 ${topBan.count} 次居首，${topPick ? `${topPick.hero}是我方出场最多的英雄` : '选用名单已接入'}`
    : `${n} 场 BP 记录已就绪`;
  const hero = `<div class="bp2-hero">
    <div class="bp2-voxel" aria-hidden="true">${Array.from({length: 9}, (_, i) => `<i class="${[0, 2, 4, 6, 8].includes(i) ? 'is-gold' : 'is-teal'}"></i>`).join('')}</div>
    <div class="bp2-hero-main"><span class="page-eyebrow">DRAFT INTELLIGENCE · BP 分析</span>
      <h1>${esc(headline).replace(/(\d+(?:\.\d+)?)/g, '<em>$1</em>')}</h1>
      <div class="page-facts"><span>${num(n)} 场有 BP</span><span>营地 ${num(campN)} · 人工 ${num(manualN)}</span><span>${num(totals.bans)} 次禁用</span><span>${num(totals.heroes)} 个英雄</span></div>
    </div>
    <div class="bp2-hero-stats">
      <div><b>${num(totals.bans || 0)}</b><span>禁用总次数</span></div>
      <div><b>${num(totals.picks || 0)}</b><span>选用总次数</span></div>
      <div><b>${num(totals.heroes || 0)}</b><span>涉及英雄</span></div>
    </div>
    <div class="heading-actions"><a class="button" href="#matches">比赛档案</a><button class="button" data-print>打印 / PDF</button></div>
  </div>`;

  const sourceBar = `<div class="bp2-source">
    <span class="bp2-source-item"><i class="is-camp"></i>营地自动 <b>${num(campN)}</b> 场</span>
    <span class="bp2-source-item"><i class="is-manual"></i>人工录入 <b>${num(manualN)}</b> 场</span>
    ${data.sampleWarning ? `<span class="bp2-source-alert">注意 · ${esc(data.sampleWarning)}</span>` : ''}
    ${Number(data.pendingCampMatches) > 0 ? `<a class="bp2-source-pending" href="#capture">另有 ${num(data.pendingCampMatches)} 局营地详情未入库 · 去勾选入库 →</a>` : ''}
  </div>`;

  if (!n) {
    container.innerHTML = hero + sourceBar + `<section class="panel"><div class="empty-state"><strong>还没有 BP 记录</strong>在采集页同步营地战绩并核对入库，或在比赛校对页填写双方 ban/pick；营地名单会自动生成禁用榜、选用、阵容和分路统计。<br><a href="#matches">去比赛档案 →</a></div></section>`;
    return;
  }

  /* ---------- 01 总览 ---------- */
  const kpi = (label, value, sub, tone) => `<div class="team-kpi bp2-kpi ${tone}"><span>${esc(label)}</span><b>${value}</b><small>${esc(sub)}</small></div>`;
  const kpis = `<div class="team-summary bp2-kpis">
    ${kpi('有 BP 对局', num(n), `营地 ${num(campN)} · 人工 ${num(manualN)}`, 'is-blue')}
    ${kpi('禁用总次数', num(totals.bans || 0), `${bans.length} 个英雄被禁`, 'is-gold')}
    ${kpi('选用总次数', num(totals.picks || 0), `本队 ${picks.length} / 对手 ${enemies.length} 个英雄`, 'is-teal')}
    ${kpi('阵容与组合', `${num(comps.length)} / ${num(pairs.length)}`, '套阵容 / 组双人共现', 'is-violet')}</div>`;
  const findings = [
    {tone: 'is-gold', label: '最被针对', hero: topBan?.hero, value: topBan ? `${num(topBan.count)} 次` : '—',
      text: topBan ? `${topBan.hero} 在 ${n} 场里被禁 ${topBan.count} 次${pressure.find(x => x.hero === topBan.hero)?.picks === 0 ? '，且从未出场' : ''}。` : '暂无禁用数据。', tab: 'heroes'},
    {tone: 'is-teal', label: '本队核心', hero: topPick?.hero, value: topPick ? `${num(topPick.count)} 次` : '—',
      text: topPick ? `${topPick.hero} 出场 ${topPick.count} 次，覆盖 ${num(topPick.count / n * 100)}% 的对局。` : '暂无选用数据。', tab: 'comps'},
    {tone: 'is-blue', label: '分路倾斜', badge: topLane?.lane, value: topLane ? `${num(topLane.bans)} 次` : '—',
      text: topLane ? `${topLane.lane} 位被禁 ${topLane.bans} 次，占全部禁用 ${num(topLane.bans / Math.max(1, totals.bans) * 100, 1)}%。` : '暂无分路数据。', tab: 'comps'},
  ].map(item => `<button class="bp2-finding ${item.tone}" data-bp2-tab="${item.tab}"><span>${esc(item.label)}</span>
    ${item.badge ? `<span class="bp2-lane-badge">${esc(item.badge)}</span>` : (item.hero ? ico(item.hero, 'bp2-face is-find') : '')}<b>${item.value}</b><p>${esc(item.text)}</p><em>查看 ${esc(TABS.find(t => t.key === item.tab)?.name || '')} →</em></button>`).join('');
  const rankMini = (list, tone, getNote) => {
    const max = Math.max(1, ...list.map(x => Number(x.count) || 0));
    return list.slice(0, 6).map(item => rankRow(item, max, getNote(item), tone, icons, meta)).join('');
  };
  const overview = kpis
    + `<div class="bp2-section"><h2>三条关键发现</h2><p>从当前样本直接读出，点击卡片进入对应功能。</p></div><div class="bp2-findings">${findings}</div>`
    + `<div class="bp2-grid">${panel('禁用 Top 6', '双方禁用合计，按次数排序。', rankMini(bans, 'is-gold', x => `占 ${num((x.count || 0) / n * 100)}% 场次`), `Top 6 / ${bans.length}`, 'bp2-rank-card')
      }${panel('本队选用 Top 6', '我方阵营出场次数。', rankMini(picks, 'is-teal', x => x.winRate == null ? '胜负未定' : `胜率 ${num(x.winRate)}%`), `Top 6 / ${picks.length}`, 'bp2-rank-card')}</div>`
    + `<div class="bp2-grid">${panel('分路热度', '各分路禁用 / 选用对比。', laneChart(lanes, icons, meta), `${lanes.length} 类`)
      }${panel('蓝红方概览', '按阵营汇总禁用、选用与赛果。', sideChart(sides), '2 个阵营')}</div>`
    + `<div class="bp2-section"><h2>六个功能</h2><p>按用途拆开，避免把入库样本、人工手序和营地全量口径混在一起看。</p></div>
      <div class="bp2-entry">${TABS.map(t => `<button data-bp2-tab="${t.key}" class="bp2-entry-card"><span>${t.no}</span><strong>${esc(t.name)}</strong><small>${esc(t.desc)}</small><em>→</em></button>`).join('')}</div>`;

  /* ---------- 02 逐局 BP ---------- */
  const matchBoard = (row, hidden = false) => {
    const stats = row.teamStats || {}, l = stats.left || {}, r = stats.right || {};
    const split = (label, key) => {
      const a = Number(l[key]) || 0, b = Number(r[key]) || 0, t = a + b || 1;
      return `<div class="bp2-split"><em>${label}</em><span class="bp2-split-bar"><i class="is-left" style="width:${(a / t * 100).toFixed(1)}%"></i><i class="is-right" style="width:${(b / t * 100).toFixed(1)}%"></i></span><small>${num(l[key] ?? 0)} : ${num(r[key] ?? 0)}</small></div>`;
    };
    const side = (key, label) => {
      const banList = (row.bans || {})[key] || [], pickList = (row.picks || {})[key] || [];
      const slots = (list, banned) => Array.from({length: 5}, (_, i) => {
        const item = list[i];
        return item ? `<div class="bp2-slot ${banned ? 'is-ban' : ''}">${ico(item.name)}</div>` : '<div class="bp2-slot is-empty"></div>';
      }).join('');
      return `<div class="bp2-side is-${key}"><div class="bp2-side-title"><strong>${label}</strong>
        ${row.ownSide === key ? '<span class="bp2-chip is-own">我方</span>' : ''}
        ${row.winnerSide === key ? '<span class="bp2-chip is-win">胜方</span>' : ''}</div>
        <div class="bp2-slot-row"><em>禁用</em>${slots(banList, true)}</div>
        <div class="bp2-slot-row"><em>选用</em>${slots(pickList, false)}</div></div>`;
    };
    const hasStats = l.money != null || r.money != null;
    return `<article class="bp2-match" ${hidden ? 'hidden' : ''} data-source="${esc(row.source || '')}">
      <div class="bp2-match-head"><div><strong>${esc(row.dateText || row.date || '日期待补')}</strong> · ${esc(row.opponent || row.title || '未标注对手')}
        <span class="bp2-meta">${esc(row.mapName || '')}${duration(row.duration) ? ` · ${duration(row.duration)}` : ''}</span></div>
        <div class="bp2-match-tags"><span class="bp2-chip ${row.source === 'camp' ? 'is-camp' : 'is-manual'}">${row.source === 'camp' ? '营地自动' : '人工录入'}</span>
        <span class="bp2-chip ${row.result === 'win' ? 'is-win' : row.result === 'loss' ? 'is-loss' : ''}">${row.result === 'win' ? '胜' : row.result === 'loss' ? '负' : '待确认'}</span></div></div>
      <div class="bp2-board">${side('left', '左方 / 蓝')}${side('right', '右方 / 红')}</div>
      ${hasStats ? `<div class="bp2-splits">${split('经济', 'money')}${split('击杀', 'killCnt')}${split('推塔', 'towerCnt')}</div>` : ''}
    </article>`;
  };
  const matches = `<div class="bp2-toolbar"><div class="bp2-filters">
      <button class="is-active" data-bp2-source="all">全部 ${num(rows.length)}</button>
      <button data-bp2-source="camp">营地 ${num(rows.filter(x => x.source === 'camp').length)}</button>
      <button data-bp2-source="manual">人工 ${num(rows.filter(x => x.source !== 'camp').length)}</button></div>
      <span class="bp2-toolbar-note">默认显示前 6 局，可展开全部</span></div>
    <div class="bp2-match-list">${rows.map((row, i) => matchBoard(row, i >= 6)).join('')}</div>
    ${rows.length > 6 ? '<button class="bp2-more" data-bp2-more>展开全部 ' + num(rows.length) + ' 局 ↓</button>' : ''}`;

  /* ---------- 03 英雄热度 ---------- */
  const banSet = new Set(bans.map(x => x.hero));
  const pickSet = new Set([...picks, ...enemies].map(x => x.hero));
  const onlyBan = [...banSet].filter(x => !pickSet.has(x)).length;
  const onlyPick = [...pickSet].filter(x => !banSet.has(x)).length;
  const both = [...banSet].filter(x => pickSet.has(x)).length;
  const pressureRows = pressure.slice(0, 10).map(item => `<div class="bp2-prow">${ico(item.hero, 'bp2-face is-row')}
    <strong>${esc(item.hero)}</strong><span>禁 ${num(item.bans)} · 选 ${num(item.picks)}</span>
    <div class="bp2-track is-thin"><i style="width:${clamp(Number(item.banRate) || 0, 0, 100).toFixed(1)}%"></i></div>
    <b>${num(item.banRate)}%</b></div>`).join('');
  const heroesPanel = `<div class="bp2-lead">${panel('禁用压力象限', '纵轴被禁次数、横轴出场次数；金框 = 禁用率 ≥ 70%，气泡大小 = 总热度。', scatterSvg(pressure, icons, meta), `${pressure.length} 个英雄`, 'bp2-wide')}
    <div class="bp2-ring-card">${ringSvg([
      {value: onlyBan, color: '#d79b32'}, {value: onlyPick, color: '#2fa89c'}, {value: both, color: '#3b78e0'},
    ], `${num(onlyBan + onlyPick + both)}`, '榜单英雄')}
      <div class="bp2-ring-legend"><span><i style="background:#d79b32"></i>只被禁 ${num(onlyBan)}</span><span><i style="background:#2fa89c"></i>只出场 ${num(onlyPick)}</span><span><i style="background:#3b78e0"></i>两者都有 ${num(both)}</span></div>
      <div class="bp2-ring-note">按三张榜单可见英雄统计；全量去重英雄 ${num(totals.heroes || 0)} 个。</div></div></div>`
    + `<div class="bp2-three">${panel('禁用榜', '按出现次数排序，含双方禁用。',
        rankMini(bans.slice(0, 10), 'is-gold', x => `占 ${num((x.count || 0) / n * 100)}% 场次`), `Top 10 / ${bans.length}`, 'bp2-rank-card')
      }${panel('本队选用', '我方阵营出场次数。',
        rankMini(picks.slice(0, 10), 'is-teal', x => x.winRate == null ? '胜负未定' : `胜率 ${num(x.winRate)}%`), `Top 10 / ${picks.length}`, 'bp2-rank-card')
      }${panel('对手选用', '对手阵营出场次数。',
        rankMini(enemies.slice(0, 10), 'is-blue', x => `占 ${num((x.count || 0) / n * 100)}% 场次`), `Top 10 / ${enemies.length}`, 'bp2-rank-card')}</div>`
    + panel('禁用率 Top 10', '被禁次数 / (被禁 + 出场)，越高说明越常被针对。', pressureRows, `Top 10 / ${pressure.length}`);

  /* ---------- 04 阵容体系 ---------- */
  const compCards = comps.slice(0, 8).map(item => `<div class="bp2-comp"><div class="bp2-comp-faces">${(item.heroes || []).map(name => ico(name)).join('')}</div>
    <div class="bp2-comp-meta"><strong>${num(item.count)} 次</strong><small>${item.winRate == null ? '胜负未定' : `胜率 ${num(item.winRate)}%`}</small></div></div>`).join('');
  const maxPair = Math.max(1, ...pairs.map(x => x.n));
  const pairList = pairs.slice(0, 9).map(item => `<div class="bp2-pair">${ico(item.a, 'bp2-face is-row')}${ico(item.b, 'bp2-face is-row')}
    <div class="bp2-pair-main"><strong>${esc(item.a)} + ${esc(item.b)}</strong><div class="bp2-track is-thin"><i style="width:${(item.n / maxPair * 100).toFixed(1)}%"></i></div></div>
    <b>${num(item.n)}</b><small>${item.winRate == null ? '' : `${num(item.winRate)}%`}</small></div>`).join('');
  const repeated = comps.filter(x => x.count > 1).length;
  const compsPanel = panel('五人阵容', repeated ? `${repeated} 套阵容重复出现。` : `${comps.length} 套阵容均只出现 1 次，样本内没有重复体系。`,
    compCards ? `<div class="bp2-comp-grid">${compCards}</div>` : '', `${comps.length} 套`)
    + `<div class="bp2-grid">${panel('双人共现矩阵', '出现频率最高的 8 个英雄两两同队场次；数字越大颜色越深。', pairMatrix(pairs, icons, meta), `${pairs.length} 组`, 'bp2-matrix-card')
      }${panel('共现 Top 9', '同队两名英雄的共现次数。', pairList, `Top 9 / ${pairs.length}`)}</div>`
    + panel('分路分布', '禁用 / 选用按英雄主分路归类；实测位置优先，静态参考表兜底。', laneChart(lanes, icons, meta), `${lanes.length} 类`);

  /* ---------- 05 对手与赛果 ---------- */
  const opponentCards = opponents.map(item => {
    const chips = list => (list || []).map(x => `<span class="bp2-hchip">${ico(x.name || x[0], 'bp2-face is-tiny')}<b>${esc(x.name || x[0])}</b><small>×${num(x.count || x[1])}</small></span>`).join('');
    return `<div class="bp2-opponent"><div class="bp2-opponent-head"><strong>${esc(item.opponent || '未标注对手')}</strong><span>${num(item.matches)} 局交手</span></div>
      <div class="bp2-opponent-line"><em>常禁</em><div class="bp2-chips">${chips(item.banHeroes || item.bans) || '<span class="bp2-empty">无记录</span>'}</div></div>
      <div class="bp2-opponent-line"><em>常用</em><div class="bp2-chips">${chips(item.pickHeroes || item.picks) || '<span class="bp2-empty">无记录</span>'}</div></div></div>`;
  }).join('');
  const contextPanel = `<div class="bp2-grid">${panel('对手 BP 习惯', '按对手聚合的禁用与选用频率；对手未命名时归到「未标注对手」。', opponentCards, `${opponents.length} 个`)
    }${panel('蓝红方概览', '按阵营汇总禁用、选用与赛果。', sideChart(sides), '2 个阵营')}</div>`
    + panel('手序与先后手', '仅人工录入的 1–5 楼顺序参与；描述性统计，不代表因果。', orderChart(orders, data.firstPickEffect, manualN), `${num(manualN)} 场人工`)
    + panel('样本口径', '读数前必须知道的三件事。', `<div class="bp2-caveats">
      <div><b>01</b><span><strong>来源</strong>营地终局名单 ${num(campN)} 场 + 人工手序 ${num(manualN)} 场；人工录入优先，两类来源不混算手序。</span></div>
      <div><b>02</b><span><strong>偏差</strong>${esc(data.sampleWarning || '当前样本无胜负偏差提示。')}</span></div>
      <div><b>03</b><span><strong>缺口</strong>本地另有 ${num(data.pendingCampMatches || 0)} 局营地详情未入库。到「采集」页的营地战绩清单勾选并拉取、核对入库后，本页统计自动纳入；本页不直接写数据。<a href="#capture">去采集 →</a></span></div></div>`, '必读');

  /* ---------- 06 深度洞察：营地口径的分析已并入顶部页签行「BP 资源」 ---------- */
  const depthPanel = `<div class="bp2-depth-note"><strong>已并入页签</strong>
    <span>营地全量口径的 ban/pick 与龙塔资源分析，现在是顶部页签行里的「BP 资源」，点开即达、口径更清楚。</span></div>
    <div class="bp2-depth-slot" id="bp2-depth-slot"><a class="button primary" href="#depth/resource_bp">打开「BP 资源」分析 →</a></div>`;

  /* ---------- 挂载与交互 ---------- */
  const params = new URLSearchParams(location.search);
  let active = params.get('tab') || '';
  if (!TABS.some(t => t.key === active)) { try { active = sessionStorage.getItem('bp2.tab') || ''; } catch (_) { /* 隐私模式 */ } }
  if (!TABS.some(t => t.key === active)) active = 'overview';
  const contents = {overview, matches, heroes: heroesPanel, comps: compsPanel, context: contextPanel, depth: depthPanel};
  const tabs = `<nav class="bp2-tabs" aria-label="BP 功能分区">${TABS.map(t => `<button data-bp2-tab="${t.key}" class="${t.key === active ? 'is-active' : ''}"><span>${t.no}</span><strong>${esc(t.name)}</strong><small>${esc(t.desc)}</small></button>`).join('')}</nav>`;
  const panels = `<div class="bp2-panels">${TABS.map(t => `<div class="bp2-panel" data-panel="${t.key}" ${t.key === active ? '' : 'hidden'}>${contents[t.key]}</div>`).join('')}</div>`;
  container.innerHTML = hero + sourceBar + tabs + panels;

  const setTab = key => {
    const tab = TABS.find(t => t.key === key);
    if (!tab) return;
    container.querySelectorAll('.bp2-tabs [data-bp2-tab]').forEach(el => el.classList.toggle('is-active', el.dataset.bp2Tab === tab.key));
    container.querySelectorAll('[data-panel]').forEach(el => { el.hidden = el.dataset.panel !== tab.key; });
    const url = new URL(location.href);
    url.searchParams.set('tab', tab.key);
    history.replaceState(null, '', url.pathname + url.search + url.hash);
    try { sessionStorage.setItem('bp2.tab', tab.key); } catch (_) { /* 忽略 */ }
    const nav = container.querySelector('.bp2-tabs');
    if (nav) {
      const top = nav.getBoundingClientRect().top + window.scrollY - 76;
      window.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
    }
  };
  container.addEventListener('click', event => {
    const tabButton = event.target.closest('[data-bp2-tab]');
    if (tabButton && container.contains(tabButton)) { setTab(tabButton.dataset.bp2Tab); return; }
    const sourceButton = event.target.closest('[data-bp2-source]');
    if (sourceButton) {
      const value = sourceButton.dataset.bp2Source;
      container.querySelectorAll('[data-bp2-source]').forEach(el => el.classList.toggle('is-active', el === sourceButton));
      container.querySelectorAll('.bp2-match').forEach(el => { el.hidden = value !== 'all' && el.dataset.source !== value; });
      return;
    }
    if (event.target.closest('[data-bp2-more]')) {
      container.querySelectorAll('.bp2-match').forEach(el => { el.hidden = false; });
      const button = container.querySelector('[data-bp2-more]');
      if (button) button.remove();
    }
  });
}
