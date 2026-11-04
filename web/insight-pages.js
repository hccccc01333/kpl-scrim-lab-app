/* KPL 风格的扩展页面：对手档案、BP、组合、精选对局、训练纪录。 */
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value))
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
const RESULT = {win: '胜', loss: '负', draw: '平', unknown: '待确认'};
const SOURCE = {db: '确认记录', bundle: '数据包', sheet: '表格', capture: '截图候选'};

function pageHeader(eyebrow, title, subtitle, facts, actions) {
  return `<div class="page-heading"><div><span class="page-eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p>${esc(subtitle)}</p><div class="page-facts">${facts.map(item => `<span>${esc(item)}</span>`).join('')}</div></div><div class="heading-actions">${actions}<button class="button" data-print>打印 / PDF</button></div></div>`;
}

function heroIcons(catalog) {
  return Object.fromEntries(((catalog?.entries) || []).filter(entry => entry.kind === 'hero' && entry.icon).map(entry => [entry.name, entry.icon]));
}

function heroIcon(name, icons, className = 'lineup-hero') {
  const icon = icons[name];
  return `<span class="${className}">${icon ? `<img src="${esc(icon)}" alt="" loading="lazy">` : `<b>${esc((name || '?')[0])}</b>`}</span>`;
}

function matchResult(result) {
  const tone = result === 'win' ? 'win' : result === 'loss' ? 'loss' : result === 'draw' ? 'draw' : 'unknown';
  return `<span class="match-result ${tone}">${RESULT[result] || '待确认'}</span>`;
}

function duration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return '时长未记录';
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
}

function matchCard(match, icons) {
  const left = match.scores?.left ?? '—', right = match.scores?.right ?? '—';
  return `<article class="match-card"><div class="match-card-top"><span class="match-date">${esc(match.date || '日期待定')}<small>${esc(match.session || '日常训练')}</small></span>${matchResult(match.result)}</div><div class="match-card-main"><h3>${esc(match.opponent ? 'vs ' + match.opponent : match.title || '未命名比赛')}</h3><div class="match-score"><span>左</span><b>${esc(left)}</b><em>:</em><b>${esc(right)}</b><span>右</span></div></div><div class="match-card-meta"><span>${duration(match.duration)}</span><span>${num(match.players)} 人</span><span>${esc(SOURCE[match.source] || match.source || '来源待确认')}</span></div><div class="match-card-actions"><a class="button" href="#match/${esc(match.key)}">打开对局 →</a></div></article>`;
}

export async function renderOpponent(container, {api, workspace, isCurrent, query, filters}, name) {
  const [matchesView, processView, raw, catalog] = await Promise.all([
    api('/api/studio/view/matches' + query()), api('/api/studio/view/process' + query()),
    api('/api/studio/dataset', {dataset: 'records', filters, deduplicate: true}),
    api('/api/catalog').catch(() => ({entries: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const icons = heroIcons(catalog);
  const matches = (matchesView.matches || []).filter(match => match.opponent === name);
  if (!matches.length) {
    container.innerHTML = `<a class="back-link" href="#team">← 返回团队复盘</a>` + pageHeader('OPPONENT · 对手档案', name, '当前筛选下没有与这个对手的比赛。', ['0 场'], `<a class="button" href="#team">团队复盘</a>`) + `<section class="panel"><div class="empty-state"><strong>还没有这名对手的记录</strong>确认比赛时填写对手名称后，交手记录和对手英雄会自动汇总。<br><a href="#matches">查看比赛档案 →</a></div></section>`;
    return;
  }
  const processMap = new Map((processView.matches || []).map(match => [match.key, match]));
  const enemyRows = (raw.rows || []).filter(row => !row.isOwn && row.opponent === name);
  const counts = new Map();
  enemyRows.forEach(row => { if (row.hero) counts.set(row.hero, (counts.get(row.hero) || 0) + 1); });
  const heroPool = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  const wins = matches.filter(match => match.result === 'win').length;
  const losses = matches.filter(match => match.result === 'loss').length;
  const unknown = matches.length - wins - losses;
  const diffs = matches.map(match => processMap.get(match.key)?.finalDiff).filter(Number.isFinite);
  const avgDiff = diffs.length ? diffs.reduce((sum, value) => sum + value, 0) / diffs.length : null;
  const recent = matches.slice(0, 4).map(match => `${match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '待确认'}`).join(' · ');
  const heroCards = heroPool.map(([hero, count]) => `<a class="hero-card" href="#hero/${encodeURIComponent(hero)}">${heroIcon(hero, icons, 'hero-card-icon')}<span class="hero-card-name"><strong>${esc(hero)}</strong><small>${count} 次出场</small></span><span class="hero-card-stats"><span>对手使用</span></span></a>`).join('');
  container.innerHTML = `<a class="back-link" href="#team">← 返回团队复盘</a>`
    + pageHeader('OPPONENT · 对手档案', name, '交手记录、对手英雄和时间轴汇总；只使用已确认比赛。', [`${matches.length} 场`, `${wins} 胜 · ${losses} 负${unknown ? ` · ${unknown} 待确认` : ''}`, `平均终局经济差 ${avgDiff == null ? '—' : `${avgDiff >= 0 ? '+' : ''}${num(avgDiff)}`}`, `最近 ${recent}`], `<a class="button" href="#team">团队复盘 →</a>`)
    + `<div class="team-summary"><div class="team-kpi"><span>交手场次</span><b>${matches.length}</b><small>场</small></div><div class="team-kpi"><span>胜率</span><b>${wins + losses ? `${num(wins / (wins + losses) * 100, 1)}%` : '—'}</b><small>${wins + losses} 场有胜负</small></div><div class="team-kpi"><span>平均终局经济差</span><b>${avgDiff == null ? '—' : `${avgDiff >= 0 ? '+' : ''}${num(avgDiff)}`}</b><small>本队 − 对手</small></div><div class="team-kpi"><span>对手英雄</span><b>${heroPool.length}</b><small>个英雄有记录</small></div></div>`
    + `<section class="panel"><div class="panel-head"><div><h2>对手常用英雄</h2><p>来自双方十人记录中的对手阵营。</p></div><span class="pill">${heroPool.length} 个</span></div><div class="panel-body">${heroCards ? `<div class="hero-card-grid">${heroCards}</div>` : '<div class="empty-state">当前记录没有对手英雄字段。</div>'}</div></section>`
    + `<div class="section-heading"><h2>交手记录</h2></div><div class="match-card-grid">${matches.map(match => matchCard(match, icons)).join('')}</div>`
    + `<div class="section-heading"><h2>下一步</h2></div><div class="next-grid"><a class="next-card" href="#team"><strong>看团队复盘</strong><span>经济节奏、资源、BP 和对手档案</span><em>→</em></a><a class="next-card" href="#matches"><strong>查看全部比赛</strong><span>按日期、选手和英雄筛选</span><em>→</em></a><a class="next-card" href="#topics/player_pairs"><strong>查看双人搭档</strong><span>英雄池、搭档、经济转折</span><em>→</em></a></div>`;
}

export async function renderBp(container, {api, isCurrent, query}) {
  const [data, catalog] = await Promise.all([api('/api/studio/view/bp' + query()), api('/api/catalog').catch(() => ({entries: []}))]);
  if (isCurrent && !isCurrent()) return;
  const icons = heroIcons(catalog);
  const bans = data.bans || [], picks = data.ownPicks || [], orders = data.orderEffect || [], opponents = data.opponents || [];
  const hasData = Number(data.matchesWithBp) > 0 || bans.length || picks.length || opponents.length;
  const maxBan = Math.max(1, ...bans.map(item => Number(item.count) || 0));
  const banRows = bans.map(item => `<div class="bp-row">${heroIcon(item.hero, icons, 'bp-hero-icon')}<strong>${esc(item.hero)}</strong><span class="bp-bar"><i style="width:${Math.round((Number(item.count) || 0) / maxBan * 100)}%"></i></span><b>${num(item.count)}</b></div>`).join('');
  const pickRows = picks.map(item => `<div class="bp-row">${heroIcon(item.hero, icons, 'bp-hero-icon')}<strong>${esc(item.hero)}</strong><span class="bp-bar"><i style="width:${Math.round((Number(item.count) || 0) / Math.max(1, ...picks.map(p => Number(p.count) || 0)) * 100)}%"></i></span><b>${num(item.count)}</b><small>${item.winRate == null ? '' : `胜率 ${num(item.winRate)}%`}</small></div>`).join('');
  const orderCards = orders.map(item => `<div class="order-card"><span>第 ${num(item.order)} 手</span><b>${item.n ? `${num(item.wins / item.n * 100, 0)}%` : '—'}</b><small>${num(item.wins)} 胜 / ${num(item.n)} 场</small></div>`).join('');
  container.innerHTML = pageHeader('DRAFT · BP 分析', 'BP 记录', '禁用、选用、先后手和对手 BP；只读取校对时填写的 ban/pick。', [`${num(data.matchesWithBp)} 场有 BP`, `${bans.length} 个禁用英雄`, `${picks.length} 个选用英雄`, `${opponents.length} 个对手`], `<a class="button" href="#matches">比赛档案</a>`)
    + (hasData
      ? `<div class="bp-grid"><section class="panel"><div class="panel-head"><div><h2>禁用榜</h2><p>按出现次数排序。</p></div></div><div class="panel-body">${banRows || '<div class="empty-state">没有禁用记录。</div>'}</div></section><section class="panel"><div class="panel-head"><div><h2>本队选用</h2><p>只统计已填写 pick 的比赛。</p></div></div><div class="panel-body">${pickRows || '<div class="empty-state">没有选用记录。</div>'}</div></section></div><section class="panel"><div class="panel-head"><div><h2>本方选用手序</h2><p>本方第 1–5 次选用的已知赛果胜率；手序不等于蓝红方先后手。</p></div></div><div class="panel-body"><div class="order-grid">${orderCards}</div></div></section>`
      : `<section class="panel"><div class="empty-state"><strong>还没有结构化 BP 记录</strong>在校对比赛时填写双方 ban/pick，BP 页会自动生成禁用榜、选用和先后手统计。<br><a href="#matches">去比赛档案填写 →</a></div></section>`);
}

export async function renderCombos(container, {api, isCurrent, query}) {
  const base = {dataset: 'records', metric: 'damage', filters: {sources: ['db', 'bundle', 'sheet'], includePartial: true}};
  const [heroResult, playerResult, catalog] = await Promise.all([
    api('/api/studio/research', {...base, topic: 'hero_combos'}),
    api('/api/studio/research', {...base, topic: 'player_pairs'}),
    api('/api/catalog').catch(() => ({entries: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const icons = heroIcons(catalog);
  const heroRows = heroResult.rows || [], playerRows = playerResult.rows || [];
  const comboCard = (row, hero) => `<article class="combo-card">${hero ? `<div class="combo-heroes">${heroIcon(row.a, icons, 'combo-icon')}${heroIcon(row.b, icons, 'combo-icon')}</div>` : `<div class="combo-heroes"><span class="combo-avatar">${esc((row.a || '?').slice(0, 2))}</span><span class="combo-avatar">${esc((row.b || '?').slice(0, 2))}</span></div>`}<h3>${esc(row.a)} + ${esc(row.b)}</h3><div class="combo-stats"><span>共现 <b>${num(row.n)}</b></span><span>胜率 <b>${row.winRate == null ? '—' : `${num(row.winRate)}%`}</b></span><span>Lift <b>${num(row.lift, 2)}</b></span></div></article>`;
  container.innerHTML = pageHeader('COMBO · 组合', '英雄组合与双人搭档', '完整五英雄阵容的实际共现；至少共现 2 次才进入结果。Lift 描述共现，不代表因果。', [`${heroRows.length} 组英雄组合`, `${playerRows.length} 组双人搭档`, '完整阵容门槛'], `<a class="button" href="#topics/player_pairs">双人搭档</a>`)
    + `<section class="panel"><div class="panel-head"><div><h2>英雄组合</h2><p>同队两名英雄的实际共现、胜率和独立选用基线。</p></div><span class="pill">${heroRows.length} 组</span></div><div class="panel-body">${heroRows.length ? `<div class="combo-grid">${heroRows.slice(0, 30).map(row => comboCard(row, true)).join('')}</div>` : `<div class="empty-state">当前没有达到共现门槛的英雄组合；需要完整五人阵容且至少共现 2 次。</div>`}</div></section>`
    + `<section class="panel"><div class="panel-head"><div><h2>双人搭档</h2><p>基于稳定选手 ID 的同队搭档；未绑定昵称不进入。</p></div><span class="pill">${playerRows.length} 组</span></div><div class="panel-body">${playerRows.length ? `<div class="combo-grid">${playerRows.slice(0, 30).map(row => comboCard(row, false)).join('')}</div>` : `<div class="empty-state">当前没有达到门槛的双人搭档；需要稳定选手身份和完整五人阵容。</div>`}</div></section>`;
}

export async function renderFeatured(container, {api, isCurrent, query}) {
  const data = await api('/api/studio/view/process' + query());
  if (isCurrent && !isCurrent()) return;
  const all = data.matches || [];
  const featured = all.map(match => {
    const reasons = [];
    if (match.leadAt10 && !match.win) reasons.push('领先被翻');
    if (!match.leadAt10 && match.win) reasons.push('落后逆转');
    if (match.finalDiff != null && Math.abs(match.finalDiff) < 3000) reasons.push('经济接近');
    if (Number(match.signFlips) >= 2) reasons.push('经济反复');
    if (Number(match.killsPerMinute) >= 1.2) reasons.push('高击杀');
    return {match, reasons};
  }).filter(item => item.reasons.length).sort((a, b) => b.reasons.length - a.reasons.length || Math.abs(a.match.finalDiff || 0) - Math.abs(b.match.finalDiff || 0)).slice(0, 12);
  const card = ({match, reasons}) => `<article class="match-card"><div class="match-card-top"><span class="match-date">${esc(match.date || '日期待补')}<small>覆盖 ${num(match.coverage, 1)}%</small></span>${matchResult(match.win ? 'win' : 'loss')}</div><div class="match-card-main"><h3>${esc(match.opponent ? 'vs ' + match.opponent : '未命名比赛')}</h3><div class="match-score"><b>${match.finalDiff == null ? '—' : `${match.finalDiff >= 0 ? '+' : ''}${num(match.finalDiff)}`}</b><span>终局经济差</span></div></div><div class="match-card-tags">${reasons.map(reason => `<span>${esc(reason)}</span>`).join('')}<span>${num(match.killsPerMinute, 1)} 击杀/分</span></div><div class="match-card-actions"><a class="button" href="#match/${esc(match.key)}">打开对局 →</a></div></article>`;
  container.innerHTML = pageHeader('FEATURED · 精选对局', '值得回看的局', '按领先被翻、落后逆转、经济接近、经济反复和高击杀挑出；只使用已有时间轴的比赛。', [`${all.length} 场有时间轴`, `${featured.length} 场入选`, `覆盖门槛 60%`], `<a class="button" href="#matches">比赛档案</a>`)
    + (featured.length ? `<div class="match-card-grid">${featured.map(card).join('')}</div>` : `<section class="panel"><div class="empty-state"><strong>当前没有符合精选条件的局</strong>筛选条件是领先被翻、落后逆转、经济接近、经济反复或高击杀；比赛增加后会自动出现。<br><a href="#matches">查看比赛档案 →</a></div></section>`);
}

export async function renderRecords(container, {api, isCurrent, query}) {
  const [matchesView, processView] = await Promise.all([api('/api/studio/view/matches' + query()), api('/api/studio/view/process' + query())]);
  if (isCurrent && !isCurrent()) return;
  const matches = matchesView.matches || [], process = processView.matches || [];
  const processMap = new Map(process.map(match => [match.key, match]));
  const records = [];
  const validDuration = matches.filter(match => Number(match.duration) > 0);
  if (validDuration.length) records.push({label: '最长对局', value: duration(Math.max(...validDuration.map(match => Number(match.duration)))), note: '按已记录时长', match: validDuration.reduce((a, b) => Number(a.duration) >= Number(b.duration) ? a : b)});
  if (validDuration.length) records.push({label: '最短对局', value: duration(Math.min(...validDuration.map(match => Number(match.duration)))), note: '按已记录时长', match: validDuration.reduce((a, b) => Number(a.duration) <= Number(b.duration) ? a : b)});
  const withDiff = process.filter(match => Number.isFinite(Number(match.finalDiff)));
  if (withDiff.length) records.push({label: '最大终局经济差', value: `${Math.max(...withDiff.map(match => Number(match.finalDiff))) >= 0 ? '+' : ''}${num(Math.max(...withDiff.map(match => Number(match.finalDiff))))}`, note: '本队 − 对手', match: withDiff.reduce((a, b) => Number(a.finalDiff) >= Number(b.finalDiff) ? a : b)});
  if (withDiff.length) records.push({label: '最接近的对局', value: `${num(Math.abs(Math.min(...withDiff.map(match => Math.abs(Number(match.finalDiff))))))}`, note: '绝对经济差最小', match: withDiff.reduce((a, b) => Math.abs(Number(a.finalDiff)) <= Math.abs(Number(b.finalDiff)) ? a : b)});
  const withKills = matches.filter(match => match.scores?.left != null || match.scores?.right != null);
  if (withKills.length) records.push({label: '总击杀最高', value: num(Math.max(...withKills.map(match => Number(match.scores.left || 0) + Number(match.scores.right || 0)))), note: '双方击杀合计', match: withKills.reduce((a, b) => (Number(a.scores.left || 0) + Number(a.scores.right || 0)) >= (Number(b.scores.left || 0) + Number(b.scores.right || 0)) ? a : b)});
  const flips = withDiff.filter(match => Number(match.signFlips) > 0);
  if (flips.length) records.push({label: '经济反复最多', value: `${Math.max(...flips.map(match => Number(match.signFlips)))} 次`, note: '经济差方向变化', match: flips.reduce((a, b) => Number(a.signFlips) >= Number(b.signFlips) ? a : b)});
  const card = record => `<article class="record-card"><span>${esc(record.label)}</span><b>${esc(record.value)}</b><small>${esc(record.note)}</small>${record.match ? `<a class="text-link" href="#match/${esc(record.match.key)}">${esc(record.match.opponent ? 'vs ' + record.match.opponent : record.match.date || '打开对局')} →</a>` : ''}</article>`;
  container.innerHTML = pageHeader('RECORDS · 训练纪录', '训练赛纪录', '从已确认比赛的时长、比分、经济差和时间轴计算；没有过程数据的纪录不计算。', [`${matches.length} 份记录`, `${process.length} 场有时间轴`, `${records.length} 项纪录`], `<a class="button" href="#matches">比赛档案</a>`)
    + (matches.length ? `<div class="record-grid">${records.map(card).join('')}</div>` : `<section class="panel"><div class="empty-state"><strong>还没有比赛记录</strong>先采集并确认比赛，纪录会随比赛增加自动更新。<br><a href="#capture">采集一局 →</a></div></section>`);
}
