/* 总览：先回答“从哪开始”，再展示数据状态与最近比赛。 */
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value))
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';

const ICONS = {
  capture: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  matches: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  players: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2"/>',
  team: '<path d="M12 3 3 7v6c0 5 9 8 9 8s9-3 9-8V7zM8 12l3 3 5-6"/>',
  topics: '<path d="M4 3v17h17M8 15l4-5 4 3 5-8"/>',
  stats: '<path d="M4 18V6M4 18h16M8 15v-4M13 15V7M18 15v-6"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.stats}</svg>`;

const RESULT_TEXT = {win: '胜', loss: '负', draw: '平', unknown: '待确认'};
const resultClass = result => result === 'win' ? 'win' : result === 'loss' ? 'loss' : result === 'draw' ? 'draw' : 'unknown';

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return '时长未记录';
  const value = Number(seconds);
  return `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')}`;
}

function statusBar(label, value, total, note = '') {
  const safeTotal = Number(total) || 0;
  const safeValue = Number(value) || 0;
  const percent = safeTotal ? Math.max(0, Math.min(100, Math.round(safeValue / safeTotal * 100))) : 0;
  return `<div class="home-bar"><div class="home-bar-head"><span>${esc(label)}</span><b>${num(safeValue)}<small> / ${num(safeTotal)}</small></b></div><div class="home-bar-track"><i style="width:${percent}%"></i></div>${note ? `<p>${esc(note)}</p>` : ''}</div>`;
}

function taskCard(href, iconName, title, question, description, cta) {
  return `<a class="home-card" href="${href}">
    <span class="home-card-icon">${icon(iconName)}</span>
    <h3>${esc(title)}</h3>
    <strong>${esc(question)}</strong>
    <p>${esc(description)}</p>
    <span class="home-card-cta">${esc(cta)} ${icon('arrow')}</span>
  </a>`;
}

export async function renderHome(container, { workspace, api, isCurrent, features = [] }) {
  const overview = workspace?.overview || {};
  const recent = workspace?.recent || [];
  const datasets = workspace?.datasets || [];
  const coverage = overview.coverage || {};
  const inventory = overview.inventory || {};
  const identity = workspace?.identity || {};
  const matches = Number(overview.matches) || 0;
  const wins = Number(overview.wins) || 0;
  const decided = Number(overview.decided) || 0;
  const teamName = overview.teamName || '本队';
  const warnings = [...new Set([...(workspace?.warnings || []), ...(overview.warnings || [])])];
  const recentRows = recent.slice(0, 6);
  let pendingChannels = 0;
  try {
    const result = await api('/api/channels');
    if (isCurrent && !isCurrent()) return;
    pendingChannels = (result.channels || []).filter(channel => channel.saved?.status !== 'saved').length;
  } catch {
    if (isCurrent && !isCurrent()) return;
    pendingChannels = Number(inventory.drafts) || 0;
  }
  const next = pendingChannels > 0
    ? {title: `有 ${num(pendingChannels)} 场比赛待完成采集`, detail: '补齐表格、截图、录屏或回放，校对十人名单后保存为比赛记录。', label: '继续处理', href: '#channels'}
    : matches === 0
      ? {title: '先采集第一局', detail: '从赛后截图、录屏、表格或回放入手；一局一个采集通道，审核后才进入正式统计。', label: '采集第一局', href: '#capture'}
      : Number(inventory.drafts) > 0
        ? {title: `有 ${num(inventory.drafts)} 份草稿待校对`, detail: '补齐比分、十人名单、英雄和阵营，确认后再入库。', label: '去校对', href: '#matches'}
        : {title: '从最近一局开始复盘', detail: '看十人明细、经济节奏和原始截图；需要时再保存数据集或检查选手、英雄与团队节奏。', label: '查看比赛档案', href: '#matches'};

  const checks = overview.dataQuality?.checks || [];
  const missingChecks = checks.filter(c => Number(c.missing) > 0);
  const nameReady = Boolean(teamName) && teamName !== '我的训练队';
  const profileReady = nameReady && !missingChecks.length;
  const steps = [
    {no: '01', title: '导入比赛', note: matches ? `已有 ${num(matches)} 场` : '还没有比赛记录', href: '#capture', done: matches > 0},
    {no: '02', title: '建档', note: profileReady ? '战队、教练、首发已齐' : (missingChecks.length ? `还差 ${missingChecks.length} 项 · ${missingChecks.slice(0, 2).map(c => c.label).join('、')}` : '填战队名、教练、首发'), href: '#profile', done: profileReady},
    {no: '03', title: '看复盘', note: decided ? `${num(decided)} 场可分胜负` : '需要一场完整记录', href: '#team', done: decided > 0},
  ];
  const stepsHtml = profileReady ? '' : `<section class="product-steps" aria-label="建档三步">
    <div class="product-steps-head"><span>SETUP</span><strong>三步开始</strong><a href="#profile">去建档 →</a></div>
    <div class="product-steps-row">${steps.map((step, index) => `<a class="product-step${step.done ? ' done' : ''}${!step.done && steps.findIndex(item => !item.done) === index ? ' current' : ''}" href="${step.href}"><b>${step.done ? '✓' : step.no}</b><div><strong>${esc(step.title)}</strong><span>${esc(step.note)}</span></div></a>`).join('')}</div>
  </section>`;

  const latest = recentRows[0];
  const listRows = recentRows.slice(1, 5);
  let detail = null, heroIcons = {};
  if (latest) {
    const results = await Promise.allSettled([api('/api/studio/match/' + encodeURIComponent(latest.key)), api('/api/catalog')]);
    if (isCurrent && !isCurrent()) return;
    if (results[0].status === 'fulfilled') detail = results[0].value;
    if (results[1].status === 'fulfilled') heroIcons = Object.fromEntries((results[1].value.entries || []).filter(e => e.kind === 'hero' && e.icon).map(e => [e.name, e.icon]));
  }
  const matchHref = m => '#match/' + encodeURIComponent(m.key);
  const score = m => [m.scores?.left ?? m.scores?.blue ?? '—', m.scores?.right ?? m.scores?.red ?? '—'];
  const campText = m => ['blue','left'].includes(m.ownCamp) ? '本队蓝方' : ['red','right'].includes(m.ownCamp) ? '本队红方' : '本队阵营待确认';
  const avatars = camp => (detail?.players || []).filter(p => (['red','right'].includes(p.camp || p.side) ? 'red' : 'blue') === camp).slice(0,5).map(p => `<a class="spotlight-hero" href="#hero/${encodeURIComponent(p.hero || '')}" title="${esc(p.hero || '英雄待确认')} · ${esc(p.label || '选手待确认')}">${heroIcons[p.hero] ? `<img src="${esc(heroIcons[p.hero])}" alt="${esc(p.hero)}">` : `<span>${esc((p.hero || '?')[0])}</span>`}</a>`).join('');
  container.innerHTML = `<div class="home product-home">
    <section class="product-intro">
      <div class="product-intro-copy"><span class="product-eyebrow"><i></i> ${esc(teamName)} · 赛训分析</span><h1>每一场训练，<br>都有下一步的方向。</h1><p>看懂比赛，了解选手，找到值得深入复盘的关键。</p><div class="product-intro-actions"><a class="button primary" href="${latest ? matchHref(latest) : '#capture'}">${latest ? '复盘最近一局' : '导入第一场比赛'} ${icon('arrow')}</a><a class="product-secondary" href="#analysis">全部功能 →</a></div><div class="product-intro-note">比赛 · 选手 · 英雄与阵容<span>结论可回查，数据有出处</span></div></div>
      <div class="match-spotlight">${latest ? `<div class="spotlight-top"><span><i></i> 最近一局</span><span>${esc(latest.date || '日期待补')} · ${esc(formatDuration(latest.duration))}</span></div><a class="spotlight-title" href="${matchHref(latest)}">${esc(latest.opponent ? '对阵 ' + latest.opponent : latest.title || '训练赛')} ${icon('arrow')}</a><div class="spotlight-score"><div><span class="spotlight-camp blue">蓝方</span><div class="spotlight-roster">${avatars('blue')}</div></div><strong>${esc(score(latest)[0])}<em>:</em>${esc(score(latest)[1])}</strong><div><span class="spotlight-camp red">红方</span><div class="spotlight-roster">${avatars('red')}</div></div></div><div class="spotlight-bottom"><span class="home-result ${resultClass(latest.result)}">${RESULT_TEXT[latest.result] || '待确认'}</span><span>${campText(latest)}</span><span>${latest.hasTimeline ? '含经济时间轴' : '暂无时间轴'}</span><a href="${matchHref(latest)}">进入复盘 ↗</a></div>` : `<div class="spotlight-empty"><span>MATCH / 01</span><h2>第一份比赛，<br>就是分析的起点。</h2><p>从截图、表格、录屏或回放开始。<br>完成校对后，比赛会出现在这里。</p><a href="#capture">选择导入方式 →</a></div>`}</div>
    </section>
    <section class="product-statline" aria-label="赛训概况"><a href="#matches"><b>${num(matches)}</b><span>场比赛记录</span></a><a href="#matches"><b>${decided ? num(wins / decided * 100,1) + '<small>%</small>' : '—'}</b><span>胜率 · ${num(decided)} 场有胜负</span></a><a href="#players"><b>${num(overview.ownPlayers ?? overview.players)}</b><span>个本队身份</span></a><a href="#heroes"><b>${num(overview.ownHeroes ?? overview.heroes)}</b><span>个本队英雄</span></a></section>
    ${overview.dataQuality?.seedMatches ? `<p class="product-statline-note">其中 ${num(overview.dataQuality.seedMatches)} 场为验证数据，胜率与英雄数包含测试局；清理后再对外汇报。</p>` : ''}
    ${stepsHtml}
    ${pendingChannels || Number(inventory.drafts) ? `<section class="product-resume"><div><strong>${esc(next.title)}</strong><span>${esc(next.detail)}</span></div><a class="button" href="${next.href}">${esc(next.label)} →</a></section>` : ''}
    <section class="product-recent"><div class="product-section-heading"><div><span>RECENT MATCHES</span><h2>从比赛出发</h2></div><a href="#matches">全部比赛 ${icon('arrow')}</a></div>
      ${listRows.length ? `<div class="product-match-list">${listRows.map((m,i) => `<a class="product-match-row" href="${matchHref(m)}"><span class="product-match-number">${String(i+1).padStart(2,'0')}</span><span class="home-result ${resultClass(m.result)}">${RESULT_TEXT[m.result] || '待确认'}</span><div class="product-match-name"><strong>${esc(m.opponent ? '对阵 ' + m.opponent : m.title || '训练赛')}</strong><span>${esc(m.date || '日期待补')} · ${esc(formatDuration(m.duration))} · ${campText(m)}</span></div><strong class="product-match-score">${esc(score(m)[0])}<em>:</em>${esc(score(m)[1])}<small>蓝 / 红</small></strong><div class="product-match-data"><span>${m.complete ? '完整终局' : '部分记录'}</span><small>${m.hasTimeline ? '经济过程可回看' : '时间轴待补'}</small></div><span class="product-row-cta">复盘 ↗</span></a>`).join('')}</div>` : `<div class="product-no-matches">${recentRows.length ? '<strong>暂时只有这一场</strong><p>再导入一场，就能在这里看出走势和变化。</p>' : '<strong>还没有比赛记录</strong><p>导入素材并完成校对，就能查看双方阵容与比赛表现。</p>'}<a class="button" href="#capture">导入比赛 →</a></div>`}
    </section>
    <section class="product-explore"><div class="product-section-heading"><div><span>GO DEEPER</span><h2>你想了解什么？</h2></div><span>选一个问题，进入对应分析</span></div><div class="product-explore-grid">${taskCard('#players','players','选手表现','表现如何，状态怎样？','从有效场数、KDA、经济与英雄池，进入个人比赛记录。','查看选手')}${taskCard('#heroes','team','英雄与阵容','英雄池里还有哪些选择？','查看出场、胜率与使用选手，再比较英雄表现。','查看英雄')}${taskCard('#team','topics','团队复盘','优势建立在哪个阶段？','结合经济时间轴、资源记录与对手交手情况复盘。','查看团队')}</div></section>
    <div class="product-bottom"><a href="#capture"><strong>补充一场比赛</strong><span>截图 / 表格 / 录屏 / 回放</span>${icon('arrow')}</a><a href="#topics/hero_pool"><strong>检查英雄池</strong><span>出场分布 / 使用集中度 / 有效英雄数</span>${icon('arrow')}</a><a href="#sources"><strong>了解当前数据</strong><span>${num(coverage.completeMatches)} 场完整终局 · ${num(coverage.timelineMatches)} 场有时间轴</span>${icon('arrow')}</a></div>
    ${features.length ? `<details class="home-directory home-directory-fold"><summary><span>全部功能</span><small>按任务查找 ${features.reduce((sum,g) => sum + g.items.length,0)} 个入口</small></summary><div class="home-directory-grid">${features.map(group => `<section class="directory-group"><h3>${esc(group.group)}</h3>${group.items.map(item => `<a class="directory-link" href="#${esc(item.key)}"><span>${esc(item.label)}</span><small>${esc(item.description || '')}</small></a>`).join('')}</section>`).join('')}</div></details>` : ''}
    ${warnings.length ? `<details class="home-warnings"><summary>${warnings.length} 条数据提示</summary>${warnings.slice(0,8).map(item => `<p>${esc(item)}</p>`).join('')}</details>` : ''}
  </div>`;
}
