/* 选手板块六页 —— 名单与状态 / 选手档案 / 选手认领 / 选手与位置 / 选手对比 / 单人详情
   同一份数据源：/api/v3/players-board（营地十人面板逐人逐局记录）。
   视觉语言沿用英雄页 / BP 页：深墨报头 + KPI 条 + 结论句 + 筛选条 +
   锚点导航 + 一块一行。所有分位都在同位置内部计算，不跨位置比较。
   单人详情不另开接口：名单、对局、搭档都从同一份 board 里算。
   选手档案照 KPL 赛研的选手卡：头像 + 名字/位置 + 一个大指标 + 一行战绩摘要。 */

export function createPlayers(h) {
  const {esc, fmt, pct, diff, portrait, block, empty, reload} = h;
  const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
  const text = (x) => esc(x ?? '—');
  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  const clamp = (v) => Math.max(0, Math.min(100, typeof v === 'number' && Number.isFinite(v) ? v : 0));
  const num = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? fmt(v, d) : '—');
  const track = (v, cls = '') => `<div class="pl-track"><i class="${cls}" style="width:${clamp(v)}%"></i></div>`;
  const mono = (name) => `<span class="pl-ava">${esc(String(name || '?').trim().slice(0, 1) || '?')}</span>`;
  const resCls = (r) => r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : 'is-none';
  const resWord = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '—';
  const tone = (t) => t === 'up' ? '上升' : t === 'down' ? '下滑' : '持平';
  const toneArrow = (t) => t === 'up' ? '↑' : t === 'down' ? '↓' : '→';
  const st = {lane: '', min: 1, sort: 'games', trend: '', q: '', a: '', b: '', side: 'own', board: null,
    /* 选手档案页自己的筛选状态，和名单页互不影响；默认按出场排，避免 1 局的高 KDA 霸榜。 */
    pa: {q: '', side: 'own', lane: '', sort: 'games', min: 1, claim: '', opponent: '', day: '', page: 1, view: 'grid', picked: []},
    /* 最近对比过的选手（对比页快捷入口）。 */
    recent: [],
    /* 对比页的「对路」筛选，空 = 全部位置。 */
    cmpLane: '',
    /* 从哪一页点进单人详情，返回就回哪一页（带上当时的筛选 hash）。 */
    returnTo: null};
  /* 单人详情页：任何昵称都按同一路由打开，名字里的 / 与 ? 由 encodeURIComponent 兜住。 */
  const href = (name) => '#playerdetail/' + encodeURIComponent(String(name ?? ''));
  const meanOf = (values) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const sdOf = (values) => {
    const m = meanOf(values);
    return values.length > 1 && m != null ? Math.sqrt(values.reduce((a, b) => a + (b - m) ** 2, 0) / values.length) : null;
  };
  const medianOf = (values) => {
    if (!values.length) return null;
    const list = [...values].sort((a, b) => a - b);
    const mid = list.length >> 1;
    return list.length % 2 ? list[mid] : (list[mid - 1] + list[mid]) / 2;
  };
  const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  function dayParts(day) {
    const hit = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day || ''));
    if (!hit) return {label: String(day || '日期未记录'), week: ''};
    const date = new Date(Number(hit[1]), Number(hit[2]) - 1, Number(hit[3]));
    const valid = !Number.isNaN(date.getTime());
    return {label: `${hit[2]}-${hit[3]}`, week: valid ? WEEK[date.getDay()] : ''};
  }
  /* 对局按天分组：board.games 已经按开赛时间倒序，顺序扫一遍即可。 */
  function groupDays(games) {
    const days = [];
    for (const game of games) {
      const key = game.day || '';
      let bucket = days[days.length - 1];
      if (!bucket || bucket.day !== key) days.push(bucket = {day: key, games: []});
      bucket.games.push(game);
    }
    return days;
  }

  const kpi = (cells) => `<div class="hero-kpi pl-kpi" role="group" aria-label="关键指标">${cells.map(([label, value, note, bar, warn]) =>
    `<div class="hero-kpi-cell${warn ? ' is-warn' : ''}"><span>${esc(label)}</span><strong>${value}</strong>${typeof bar === 'number' ? `<div class="hero-kpi-track"><i style="width:${clamp(bar)}%"></i></div>` : ''}<p>${esc(note || '')}</p></div>`).join('')}</div>`;
  const anchors = (labels) => `<nav class="hero-anchor-nav" aria-label="模块快速导航">${labels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;
  const masthead = (title, sub, kpiHtml, extra = '') => `<header class="hero-masthead"><div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${extra}<button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;
  const brief = (html) => `<div class="hero-brief">${html}</div>`;
  const select = (key, label, options, value) => `<label>${esc(label)}<select data-pl-filter="${key}">${options.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
  const poolLabel = (pool) => st.q.trim()
    ? `找到 ${fmt(pool.count)} 人 · 共 ${fmt(pool.base ?? pool.count)} 人`
    : `共 ${fmt(pool.count)} 人符合条件`;

  const byName = (board, name) => (board.players || []).find(p => p.name === name) || null;
  const ownOf = (board) => (board.players || []).filter(p => p.side === 'own');

  /* ── 一、名单与状态 ─────────────────────────────────────────────── */
  function rosterRows(board) {
    const own = ownOf(board);
    const byMember = new Map(own.filter(p => p.memberId).map(p => [p.memberId, p]));
    return (board.roster || []).map((slot) => {
      const player = slot.member ? byMember.get(slot.memberId) : byName(board, slot.player);
      const name = slot.member || slot.player || '';
      const games = player ? player.games : 0;
      const hint = slot.member && !games && slot.player ? `<small class="pl-slot-hint">候选 <a href="${esc(href(slot.player))}">${esc(slot.player)}</a> · ${fmt(slot.games)} 局</small>` : '';
      const nameHtml = name ? `<a class="pl-name-link" href="${esc(href(name))}">${esc(name)}</a>` : '暂无出场';
      return `<div class="pl-slot">
        <span class="pl-lane">${esc(slot.lane)}</span>
        <span class="pl-slot-name">${mono(name)}<span class="pl-slot-meta"><b>${nameHtml}</b>${hint}</span>
          <span class="pl-slot-actions">${slot.member
            ? '<em class="pl-tag is-bound">已认领</em>'
            : `<em class="pl-tag">待认领</em>${slot.player ? `<button type="button" class="pl-link" data-pl-name="${esc(slot.player)}">命名</button>` : ''}`}</span></span>
        <span class="pl-metric pl-slot-games"><small>出场</small><b>${fmt(games)}</b></span>
        <span class="pl-metric pl-slot-wr"><small>胜率</small><b>${pct(player?.winRate)}</b></span>
        <span class="pl-metric pl-slot-score"><small>表现分</small><b>${num(player?.score, 1)}</b></span>
        <span class="pl-slot-bar">${track(player?.score || 0)}</span>
      </div>`;
    }).join('');
  }

  function playerCard(p) {
    const form = p.form || {};
    return `<article class="pl-card">
      <div class="pl-card-top"><a class="pl-card-id" href="${esc(href(p.name))}">${mono(p.name)}<span><b>${esc(p.name)}</b><small>${esc(p.lane)} · ${fmt(p.games)} 局</small></span></a>
        ${form.available ? `<em class="pl-form is-${esc(form.tone)}">${toneArrow(form.tone)} ${num(form.delta, 1)}</em>` : ''}</div>
      <div class="pl-card-figures">
        <div><small>胜率</small><b>${pct(p.winRate)}</b></div>
        <div><small>KDA</small><b>${num(p.kda, 2)}</b></div>
        <div><small>分均经济</small><b>${num(p.gpm)}</b></div>
        <div><small>分均输出</small><b>${num(p.dpm)}</b></div>
      </div>
      <div class="pl-card-score">${track(p.score || 0)}<span>表现分 <b>${num(p.score, 1)}</b> · 分均经济超过同位置 ${pct(p.percent?.gpm)}</span></div>
      <div class="pl-card-heroes">${(p.heroes || []).filter(x => x.hero).slice(0, 4).map(x => portrait(x.hero)).join('')}<small>${(p.heroes || []).filter(x => x.hero).slice(0, 3).map(x => esc(x.hero) + ' ' + fmt(x.games)).join(' / ') || '暂无英雄记录'}</small></div>
      <div class="pl-card-actions"><a class="pl-link" href="${esc(href(p.name))}">个人页 →</a><button type="button" class="pl-link" data-pl-pick="${esc(p.name)}">放入对比</button></div>
    </article>`;
  }

  function spark(points, option) {
    // option.w/h：并排小图用更小的 viewBox，否则 10 单位的字被缩到 5px
    const w = option?.w || 1000, h = option?.h || 180, padX = 34, padTop = 22, padBottom = 30;
    const values = points.map(p => p.rating).filter(v => typeof v === 'number');
    if (!values.length) return empty('这名选手还没有带评分的对局。');
    const lo = Math.floor(Math.min(...values) - 1), hi = Math.ceil(Math.max(...values) + 1);
    const span = Math.max(1, hi - lo);
    const x = (i) => padX + (points.length === 1 ? (w - padX * 2) / 2 : i * (w - padX * 2) / (points.length - 1));
    const y = (v) => h - padBottom - (v - lo) / span * (h - padTop - padBottom);
    const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.rating).toFixed(1)}`).join(' ');
    const area = `${line} L${x(points.length - 1).toFixed(1)} ${h - padBottom} L${padX} ${h - padBottom} Z`;
    const grid = [0, 0.5, 1].map(k => {
      const value = lo + span * k;
      return `<line class="pl-spark-grid" x1="${padX}" y1="${y(value).toFixed(1)}" x2="${w - padX}" y2="${y(value).toFixed(1)}"/>
        <text class="pl-spark-axis" x="4" y="${(y(value) + 3).toFixed(1)}">${value.toFixed(0)}</text>`;
    }).join('');
    const dots = points.map((p, i) => `<circle class="pl-spark-dot ${resCls(p.result)}" cx="${x(i).toFixed(1)}" cy="${y(p.rating).toFixed(1)}" r="4"><title>${esc(p.at || p.day || '')} ${esc(p.hero || '')} ${resWord(p.result)} 评分 ${num(p.rating, 1)}</title></circle>`).join('');
    const step = Math.max(1, Math.ceil(points.length / 6));
    const labelOf = (p) => {
      const stamp = String(p.at || p.day || '');
      return stamp.length >= 16 ? stamp.slice(5, 16) : stamp.slice(5) || '';
    };
    const slots = [];
    points.forEach((p, i) => { if (i % step === 0 || i === points.length - 1) slots.push(i); });
    // 末位标签必须留；和它挤在一起的前一个直接去掉，宁可少一个刻度
    const lastX = x(points.length - 1);
    const keep = slots.filter((i) => i === points.length - 1 || Math.abs(x(i) - lastX) > w * 0.12);
    let lastLabel = '';
    const labels = keep.map((i) => {
      const label = labelOf(points[i]);
      if (label === lastLabel) return '';
      lastLabel = label;
      return `<text class="pl-spark-axis" x="${Math.min(w - padX, Math.max(padX, x(i))).toFixed(1)}" y="${h - 8}" text-anchor="middle">${esc(label)}</text>`;
    }).join('');
    return `<svg class="pl-spark" viewBox="0 0 ${w} ${h}" role="img" aria-label="逐局评分走势">${grid}
      <path class="pl-spark-area" d="${area}"/><path class="pl-spark-line" d="${line}"/>${dots}${labels}</svg>`;
  }

  function poolRows(board) {
    const own = ownOf(board);
    const q = st.q.trim().toLowerCase();
    const base = own.filter(p => p.games >= st.min && (!st.lane || p.lane === st.lane));
    const pool = q ? base.filter(p => String(p.name).toLowerCase().includes(q)) : [...base];
    const sorters = {
      games: (a, b) => b.games - a.games || (b.score || 0) - (a.score || 0),
      score: (a, b) => (b.score || 0) - (a.score || 0) || b.games - a.games,
      winRate: (a, b) => (b.winRate || 0) - (a.winRate || 0) || b.games - a.games,
      kda: (a, b) => (b.kda || 0) - (a.kda || 0) || b.games - a.games,
      gpm: (a, b) => (b.gpm || 0) - (a.gpm || 0) || b.games - a.games,
    };
    const rows = pool.sort(sorters[st.sort] || sorters.games).slice(0, 14);
    if (!rows.length) return {
      html: empty(q ? `没有昵称包含「${st.q.trim()}」的选手。` : '当前条件下没有选手。降低最少局数或换位置。'),
      count: 0, base: base.length,
    };
    const head = `<div class="pl-row is-head"><span></span><span>选手</span><span>胜率</span><span>KDA</span><span>分均经济</span><span>输出占比</span><span class="pl-row-bar">表现分</span><span></span></div>`;
    return {count: pool.length, base: base.length, html: head + rows.map((p, i) => `<div class="pl-row" data-pl-goto="${esc(p.name)}">
      <span class="pl-no">${String(i + 1).padStart(2, '0')}</span>
      <span class="pl-row-name">${mono(p.name)}<span class="pl-row-title"><a href="${esc(href(p.name))}">${esc(p.name)}</a>${p.memberId ? '' : '<em class="pl-tag is-pending">待命名</em>'}</span><small>${esc(p.lane)} · ${fmt(p.games)} 局${p.laneMix?.length > 1 ? ' · 兼 ' + esc(p.laneMix.slice(1).map(x => x.lane).join('/')) : ''}</small></span>
      <span class="pl-metric"><small>胜率</small><b>${pct(p.winRate)}</b></span>
      <span class="pl-metric"><small>KDA</small><b>${num(p.kda, 2)}</b></span>
      <span class="pl-metric"><small>分均经济</small><b>${num(p.gpm)}</b></span>
      <span class="pl-metric"><small>输出占比</small><b>${pct(p.damageShare)}</b></span>
      <span class="pl-row-bar">${p.games >= 2 ? `${track(p.score || 0)}<em>${num(p.score, 1)}</em>` : '<em class="is-thin">单局样本</em>'}</span>
      <button type="button" class="pl-link" data-pl-pick="${esc(p.name)}">对比</button>
    </div>`).join('')};
  }

  /* 行内迷你走势：无坐标轴，只画线、面积和胜负点，用于榜单行。 */
  function miniSpark(points, w = 120, h = 28) {
    const values = points.map(p => p.rating).filter(v => typeof v === 'number');
    if (values.length < 2) return '<span class="pl-mini-empty">—</span>';
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = Math.max(0.1, hi - lo);
    const x = (i) => 2 + i * (w - 4) / (points.length - 1);
    const y = (v) => h - 3 - (v - lo) / span * (h - 6);
    const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.rating).toFixed(1)}`).join(' ');
    const area = `${line} L${x(points.length - 1).toFixed(1)} ${h - 1} L2 ${h - 1} Z`;
    const dots = points.map((p, i) => `<circle class="pl-mini-dot ${resCls(p.result)}" cx="${x(i).toFixed(1)}" cy="${y(p.rating).toFixed(1)}" r="1.7"/>`).join('');
    return `<svg class="pl-mini-spark" viewBox="0 0 ${w} ${h}" role="img" aria-label="逐局评分走势"><path class="pl-mini-area" d="${area}"/><path class="pl-mini-line" d="${line}"/>${dots}</svg>`;
  }

  function trendBlock(board, comparable) {
    const player = byName(board, st.trend) || comparable[0] || ownOf(board)[0];
    if (!player) return block('状态走势', '逐局营地评分', empty('本期还没有选手记录。'));
    const points = [...(player.recent || [])].reverse();
    const head = `<div class="pl-trend-head"><label>选手<select data-pl-filter="trend">${comparable.map(p => `<option value="${esc(p.name)}" ${p.name === player.name ? 'selected' : ''}>${esc(p.name)} · ${fmt(p.games)} 局</option>`).join('')}</select></label>
      <span>近 ${fmt(points.length)} 场 营地评分 · 金点为负局 · 点按可看单场</span></div>`;
    const form = player.form || {};
    const note = form.available
      ? `近 3 场平均 <b>${num(form.recent, 1)}</b>，此前 3 场 <b>${num(form.prior, 1)}</b>，${tone(form.tone)} <b>${num(form.delta, 1)}</b>。`
      : `评分样本 ${fmt(form.samples || 0)} 场，不足 6 场不给趋势结论，只展示单场分布。`;
    return block('状态走势', '同一名选手自己的逐局评分，不跨选手排名；点按圆点看单场。', `${head}${spark(points)}<p class="pl-note">${note}</p>`);
  }

  /* 最近对局与阵容：一局一行，按训练日折叠。
     旧版把 6 局的十人名单全部铺开，整块接近页面四成高度；
     现在默认只展开最近一天，其余按天收起，全部记录交给「全部对局」。 */
  function lineupsBlock(board) {
    const games = board.games || [];
    const days = groupDays(games);
    if (!days.length) return block('最近对局与阵容', '按训练日折叠', empty('本期还没有对局。'));
    const mini = (p, enemy) => `<a class="pl-mini${enemy ? ' is-enemy' : ''}" href="${esc(href(p.name))}" title="${esc(p.name)} · ${esc(p.hero || '英雄未记录')} · KDA ${num(p.kda, 1)}${enemy ? ' · 对手侧' : ''}"><span class="pl-mini-ava">${portrait(p.hero)}</span><b>${esc(p.name)}</b></a>`;
    const rowsOf = (list) => list.map((g) => {
      const opp = g.opponent || '对手未标注';
      const opponent = g.match
        ? `<a class="pl-gopp is-link" href="#match/${encodeURIComponent(g.match)}" title="打开该局复盘">${esc(opp)}</a>`
        : `<span class="pl-gopp" title="${esc(opp)}">${esc(opp)}</span>`;
      return `<div class="pl-gline ${resCls(g.result)}">
        <span class="pl-gres ${resCls(g.result)}">${resWord(g.result)}</span>
        ${opponent}
        <span class="pl-gdur">${num(g.duration, 1)} 分</span>
        <span class="pl-gcamp">${esc(g.ownCamp || '')}</span>
        <div class="pl-gside" aria-label="本队五人">${(g.own || []).map(p => mini(p, false)).join('')}</div>
        <div class="pl-gside is-enemy" aria-label="对手五人">${(g.enemy || []).map(p => mini(p, true)).join('')}</div>
      </div>`;
    }).join('');
    const shown = days.slice(0, 3);
    const body = shown.map((d, i) => {
      const wins = d.games.filter(g => g.result === 'win').length;
      const losses = d.games.filter(g => g.result === 'loss').length;
      const opps = [...new Set(d.games.map(g => g.opponent || '对手未标注'))];
      const {label, week} = dayParts(d.day);
      return `<details class="pl-day" ${i === 0 ? 'open' : ''}>
        <summary class="pl-day-head">
          <b>${esc(label)}</b><small>${esc(week)}</small>
          <span class="pl-day-count">${fmt(d.games.length)} 局</span>
          <span class="pl-day-record">${fmt(wins)} 胜 · ${fmt(losses)} 负</span>
          <span class="pl-day-opp" title="${esc(opps.join(' / '))}">${esc(opps.slice(0, 2).join(' / '))}${opps.length > 2 ? ` 等 ${fmt(opps.length)} 支` : ''}</span>
          <span class="pl-day-caret" aria-hidden="true"></span>
        </summary>
        <div class="pl-day-body">${rowsOf(d.games)}</div>
      </details>`;
    }).join('');
    const rest = days.length - shown.length;
    const foot = `<p class="pl-note">共 <b>${fmt(games.length)}</b> 局 · <b>${fmt(days.length)}</b> 个训练日${rest > 0 ? `；这里折叠最近 3 天，其余 ${fmt(rest)} 天见对局档案` : ''}。行首胜负为本队视角，两侧名字都能点进个人页。</p>`;
    return block('最近对局与阵容', '按训练日折叠：左边本队五人、右边对手五人。点名字进个人页。',
      `<div class="pl-days">${body}</div>${foot}`, '<a href="#matches">全部对局 →</a>');
  }

  function playersPage(board) {
    st.board = board;
    const s = board.summary || {};
    const identity = board.identity || {};
    const unclaimedList = (identity.entries || []).filter(x => !x.bound).sort((a, b) => b.matches - a.matches);
    const unclaimedTop = unclaimedList.slice(0, 5);
    const unclaimedGames = unclaimedList.reduce((n, x) => n + x.matches, 0);
    const identityReady = (s.bound || 0) > 0;
    const own = ownOf(board);
    const comparable = own.filter(p => p.games >= 2).sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
    const single = own.filter(p => p.games === 1).length;
    const top = comparable[0] || own[0] || {};
    const wins = own.reduce((n, p) => n + p.wins, 0), decided = own.reduce((n, p) => n + p.decided, 0);
    const head = masthead('名单与状态', '本期谁在打、谁有可比样本、状态往哪走。表现分按同位置分位合成，50 即分路平均。', kpi([
      ['对局', fmt(s.games), `${fmt(s.days)} 个训练日`],
      ['本队侧出场', `${fmt(s.ownPlayers)} 人`, '按营地昵称去重'],
      ['可跨局比较', `${fmt(comparable.length)} 人`, '出场 ≥ 2 局'],
      ['已认领', `${fmt(s.bound)} 人`, `名单 ${fmt((board.identity.members || []).length)} 人`, undefined, !identityReady],
      ['本队胜率', pct(s.winRate), `${fmt(s.wins)} 胜 / ${fmt(s.decided)} 局`, s.winRate],
    ]));
    const summaryLine = brief(`本期 <b>${fmt(s.games)} 局</b>训练赛、<b>${fmt(s.days)} 个训练日</b>：本队侧 <b>${fmt(s.ownPlayers)} 个昵称</b>出场，其中 <b>${fmt(comparable.length)} 人</b>跨 2 局以上，<b>${fmt(single)} 人</b>只打了 1 局；位置覆盖 <b>${fmt(s.positions)} / 5</b>，同场 ≥ 2 局的固定搭档 <b>${fmt(s.pairs)} 组</b>。${top.name
      ? `出场最多是 <b>${esc(top.name)}</b>（<b>${fmt(top.games)} 局</b>、胜率 <b>${pct(top.winRate)}</b>、表现分 <b>${num(top.score, 1)}</b>）。`
      : ''}先认领名单，状态与对比才会按选手而不是昵称累计。`);
    const claimBand = unclaimedList.length ? `<div class="pl-claim">
      <div class="pl-claim-head"><span class="pl-claim-kicker">身份待确认</span><b>${fmt(unclaimedList.length)} 个昵称还没命名</b><p>覆盖 ${fmt(unclaimedGames)} 人次出场。命名并归队后，名单、状态与对比才会按选手累计，而不是按单局昵称。</p></div>
      <div class="pl-claim-list">${unclaimedTop.map(x => `<span class="pl-claim-item">${mono(x.label)}<span><b>${esc(x.label)}</b><small>${esc(x.lane || '位置未记录')} · ${fmt(x.matches)} 局</small></span><button type="button" class="pl-link" data-pl-name="${esc(x.label)}">命名</button></span>`).join('')}</div>
      <span class="pl-claim-links"><a class="pl-claim-all" href="#playerarchive?claim=unbound">全部 ${fmt(unclaimedList.length)} 个 →</a><a class="pl-claim-all" href="#identity">管理认领 →</a></span>
    </div>` : '';
    const slots = block('位置名册', '五个位置一行：已认领就直接显示名单选手，未认领给出本期出场最多的候选。',
      `<div class="pl-slots">${rosterRows(board)}</div>`);
    /* 状态榜：跨选手比状态，取代原来的「单选手走势 + 4 张可比卡片」。
       form 只在评分样本 ≥ 6 场时给出，所以本期可能只有 1–2 行，页面上直接说明。 */
    const formRows = own.filter(p => p.form?.available)
      .sort((a, b) => (b.form.delta || 0) - (a.form.delta || 0));
    const formBlock = block('状态榜', '近 3 场与之前 3 场的营地评分差；只有评分样本 ≥ 6 场的选手入榜，单人逐局走势在个人页。',
      formRows.length
        ? `<div class="pl-form-list">${formRows.map(p => `<a class="pl-form-row" href="${esc(href(p.name))}">
            ${mono(p.name)}
            <span class="pl-form-main"><b>${esc(p.name)}</b><small>${esc(p.lane)} · ${fmt(p.games)} 局 · 评分 ${fmt(p.form.samples)} 场</small></span>
            <span class="pl-form-nums">近 3 场 <b>${num(p.form.recent, 1)}</b> · 此前 <b>${num(p.form.prior, 1)}</b></span>
            <span class="pl-form-spark" aria-hidden="true">${miniSpark([...(p.recent || [])].reverse())}</span>
            <em class="pl-form-delta is-${esc(p.form.tone)}">${toneArrow(p.form.tone)} ${num(p.form.delta, 1)}</em>
          </a>`).join('')}</div><p class="pl-note">本期评分样本 ≥ 6 场的选手只有 <b>${fmt(formRows.length)}</b> 人；其余选手能在个人页看到逐局评分，但不足以给趋势结论。</p>`
        : empty('本期还没有评分样本足够的选手。'),
      '<a href="#playerarchive">全部选手档案 →</a>');
    /* 固定搭档：同阵营双人共现，含只同场 1 局的；五人组只有在完全相同的五人才算。 */
    const duoBlock = (() => {
      const duos = (board.duos || []).slice(0, 8);
      if (!duos.length) return block('固定搭档', '同阵营双人组合', empty('本期还没有双人同场记录。'));
      const repeats = (board.lineups || []).filter((item) => item.games >= 2).length;
      const baseline = board.summary?.winRate;
      const rows = duos.map((d) => {
        const delta = d.winRate != null && typeof baseline === 'number' ? d.winRate - baseline : null;
        return `<div class="pl-duo-row">
        ${mono(d.a)}${mono(d.b)}
        <span class="pl-duo-names"><b>${esc(d.a)}</b><span>+</span><b>${esc(d.b)}</b></span>
        <span class="pl-duo-bar" aria-hidden="true"><i style="width:${d.winRate == null ? 0 : clamp(d.winRate)}%"></i></span>
        <span class="pl-duo-games">${fmt(d.games)} 局</span>
        <em>${d.winRate == null ? '—' : pct(d.winRate)}</em>
        <small class="pl-duo-delta ${delta == null ? '' : delta >= 0 ? 'is-pos' : 'is-neg'}">${delta == null ? '' : `${diff(Math.round(delta))} pp`}</small>
      </div>`;
      }).join('');
      return block('固定搭档', '同阵营同局共现的双人组合，按同场局数排；组合胜率只算有胜负的局。',
        `<div class="pl-duos">${rows}</div><p class="pl-note">${repeats ? `完全相同的五人组出现 <b>${fmt(repeats)}</b> 组。` : '本期没有重复出现过的完全五人组（营地昵称每局都在变），所以只看双人组合。'}</p>`);
    })();
    /* 训练日一览：按天汇总局数与胜负，数量少时直接铺开。 */
    const dayBlock = (() => {
      const days = groupDays(board.games || []);
      if (!days.length) return '';
      const rows = days.map((d) => {
        const wins = d.games.filter((g) => g.result === 'win').length;
        const losses = d.games.filter((g) => g.result === 'loss').length;
        const decided = wins + losses;
        const rate = decided ? wins / decided * 100 : null;
        const total = Math.max(1, d.games.length);
        const {label, week} = dayParts(d.day);
        return `<div class="pl-daylist-row"><b>${esc(label)}</b><small>${esc(week)}</small><span>${fmt(d.games.length)} 局</span><span>${fmt(wins)} 胜 ${fmt(losses)} 负</span><div class="pl-daylist-track"><i class="is-win" style="width:${wins / total * 100}%"></i><i class="is-loss" style="width:${losses / total * 100}%"></i></div><em>${pct(rate)}</em></div>`;
      }).join('');
      return block('训练日一览', '按天汇总局数与胜负；状态与阵容都按天看，不跨天平均。', `<div class="pl-daylist">${rows}</div>`);
    })();
    const hist = (() => {
      const buckets = [['1 局', p => p.games === 1], ['2–5 局', p => p.games >= 2 && p.games <= 5],
        ['6–10 局', p => p.games >= 6 && p.games <= 10], ['11 局以上', p => p.games >= 11]];
      const max = Math.max(1, ...buckets.map(([, test]) => own.filter(test).length));
      return block('出场结构', '本队侧选手按出场局数分布，能看出样本集中度。',
        `<div class="pl-hist">${buckets.map(([label, test]) => {
          const n = own.filter(test).length;
          return `<div class="pl-hist-row"><span>${esc(label)}</span><div class="pl-hist-track"><i style="width:${n / max * 100}%"></i></div><b>${fmt(n)} 人</b><small>${pct(own.length ? n / own.length * 100 : null)}</small></div>`;
        }).join('')}</div><p class="pl-note">1 局样本占 ${pct(own.length ? single / own.length * 100 : null)}：这些昵称只能进选手池，不能参与状态与对比结论。`);
    })();
    const lineups = lineupsBlock(board);
    const panels = [slots, formBlock, duoBlock, dayBlock, hist, lineups];
    return `<div class="page hero-detail-page page-wide" data-pl-page="players">${head}${summaryLine}${claimBand}${anchors(['位置名册', '状态榜', '固定搭档', '训练日', '出场结构', '最近对局'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 二、选手档案（KPL 赛研式选手卡） ─────────────────────────────
     卡片结构照 KPL 赛研的 player-grid：
       头像 + 名字/位置 + 一个大指标（跟着排序变） + 一行「阵营 · 局数 · 胜率 · MVP · 参团」
     整张卡片是链接，落到已有的单人详情页。 */
  const PA_SORTS = [
    ['kda', 'KDA', (p) => p.kda, (p) => num(p.kda, 2)],
    ['mvp', 'MVP', (p) => p.mvp, (p) => fmt(p.mvp)],
    ['winRate', '胜率', (p) => p.winRate, (p) => pct(p.winRate)],
    ['games', '局数', (p) => p.games, (p) => fmt(p.games)],
    ['damageShare', '输出', (p) => p.damageShare, (p) => pct(p.damageShare)],
    ['score', '表现分', (p) => p.score, (p) => num(p.score, 1)],
  ];
  const PA_PAGE_SIZE = 32;
  const paSortOf = (key) => PA_SORTS.find((item) => item[0] === key) || PA_SORTS[0];

  /* 对手 / 训练日切片：取该切片下的个人聚合；没有切片就返回全局。 */
  function paSplit(p) {
    if (st.pa.day) return (p.splits?.day || {})[st.pa.day] || null;
    if (st.pa.opponent) return (p.splits?.opponent || {})[st.pa.opponent] || null;
    return null;
  }
  const paVm = (p) => {
    const slice = paSplit(p);
    return slice ? {...p, ...slice, sliced: true} : p;
  };
  const paSliceOn = () => Boolean(st.pa.day || st.pa.opponent);
  const paSliceLabel = () => st.pa.day ? `${st.pa.day} 当天的局` : (st.pa.opponent ? `对阵 ${st.pa.opponent} 的局` : '');
  /* 详情链接带上当前切片，详情页据此切换口径。 */
  const paDetailHref = (name) => {
    const params = new URLSearchParams();
    if (st.pa.opponent) params.set('opp', st.pa.opponent);
    if (st.pa.day) params.set('day', st.pa.day);
    const query = params.toString();
    return href(name) + (query ? '?' + query : '');
  };
  /* 档位：按全局表现分（同位置分位均值）分 S/A/B/C；切片时不改口径。 */
  const paTier = (score) => (typeof score === 'number'
    ? (score >= 75 ? 'S' : score >= 60 ? 'A' : score >= 45 ? 'B' : 'C') : '');

  function paRows(board, state = st.pa) {
    const q = state.q.trim().toLowerCase();
    const value = paSortOf(state.sort)[2];
    const sliceOn = paSliceOn();
    return (board.players || [])
      .filter((p) => !sliceOn || paSplit(p))
      .map(paVm)
      .filter((p) => (!q || String(p.name).toLowerCase().includes(q))
        && (!state.side || p.side === state.side)
        && (!state.lane || p.lane === state.lane)
        && (!state.claim || (state.claim === 'bound' ? !!p.bound : !p.bound))
        && (p.games || 0) >= state.min)
      .sort((a, b) => {
        /* 缺失值永远排最后，不把「没数据」当成 0 参与排序。 */
        const left = typeof value(a) === 'number' ? value(a) : null;
        const right = typeof value(b) === 'number' ? value(b) : null;
        if (left == null && right == null) return b.games - a.games;
        if (left == null) return 1;
        if (right == null) return -1;
        return right - left || b.games - a.games;
      });
  }

  /* 分页：当前页从 st.pa.page 取，越界自动夹回。 */
  function paPage(board) {
    const rows = paRows(board);
    const pages = Math.max(1, Math.ceil(rows.length / PA_PAGE_SIZE));
    const page = Math.min(Math.max(1, Number(st.pa.page) || 1), pages);
    st.pa.page = page;
    const start = (page - 1) * PA_PAGE_SIZE;
    return {rows, total: rows.length, pages, page, start, list: rows.slice(start, start + PA_PAGE_SIZE)};
  }

  /* 筛选状态写进 URL：刷新、分享、从位置页带 lane 参数过来都能还原。 */
  function paReadHash() {
    const query = String(location.hash.split('?')[1] || '');
    if (!query) return;
    const params = new URLSearchParams(query);
    if (params.has('q')) st.pa.q = params.get('q') || '';
    if (params.has('side')) st.pa.side = params.get('side') || '';
    if (params.has('lane')) st.pa.lane = params.get('lane') || '';
    if (params.has('sort')) st.pa.sort = params.get('sort') || 'games';
    if (params.has('min')) st.pa.min = Number(params.get('min')) || 1;
    if (params.has('claim')) st.pa.claim = params.get('claim') || '';
    if (params.has('opp')) st.pa.opponent = params.get('opp') || '';
    else if (params.has('opponent')) st.pa.opponent = params.get('opponent') || '';
    if (params.has('day')) st.pa.day = params.get('day') || '';
    if (params.has('view')) st.pa.view = params.get('view') === 'list' ? 'list' : 'grid';
    if (params.has('page')) st.pa.page = Number(params.get('page')) || 1;
  }
  function paWriteHash() {
    if (!document.querySelector('[data-pl-page="archive"]')) return;
    const params = new URLSearchParams();
    if (st.pa.q) params.set('q', st.pa.q);
    if (st.pa.side) params.set('side', st.pa.side);
    if (st.pa.lane) params.set('lane', st.pa.lane);
    if (st.pa.sort !== 'games') params.set('sort', st.pa.sort);
    if (st.pa.min > 1) params.set('min', String(st.pa.min));
    if (st.pa.claim) params.set('claim', st.pa.claim);
    if (st.pa.opponent) params.set('opp', st.pa.opponent);
    if (st.pa.day) params.set('day', st.pa.day);
    if (st.pa.view !== 'grid') params.set('view', st.pa.view);
    if (st.pa.page > 1) params.set('page', String(st.pa.page));
    const query = params.toString();
    const next = '#playerarchive' + (query ? '?' + query : '');
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  function paCard(p, sortKey) {
    const sort = paSortOf(sortKey);
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const meta = [
      p.side === 'own' ? '本队' : '对手',
      `${fmt(p.games)}局`,
      `胜率${pct0(p.winRate)}`,
      `MVP${fmt(p.mvp)}`,
      `参团${pct0(p.participation)}`,
    ];
    const tier = paTier(p.score);
    const sliceTitle = p.sliced ? ` · 切片：${paSliceLabel()}` : '';
    return `<div class="pa-cell">
      <a class="pa-card${p.bound ? '' : ' is-unbound'}" href="${esc(paDetailHref(p.name))}" title="${esc(p.name)} · ${esc(p.lane || '位置未记录')}${p.bound ? '' : ' · 待认领'}${sliceTitle} · 打开个人页">
        <span class="pa-ava" aria-hidden="true">${esc(String(p.name).trim().slice(0, 1) || '?')}${tier ? `<i class="pa-tier is-${tier.toLowerCase()}${p.sliced ? ' is-global' : ''}" title="${p.sliced ? '全局档位（不随切片变化）' : '按全局表现分的档位'}">${tier}</i>` : ''}</span>
        <span class="pa-main">
          <span class="pa-top">
            <span class="pa-name"><b>${esc(p.name)}</b>${p.lane ? `<em>${esc(p.lane)}</em>` : ''}</span>
            <span class="pa-big"><strong>${sort[3](p)}</strong><small>${esc(sort[1])}</small></span>
          </span>
          <span class="pa-meta">${meta.map(esc).join(' · ')}</span>
        </span>
      </a>
      <button type="button" class="pa-preview" data-pa-drawer="${esc(p.name)}" aria-label="预览 ${esc(p.name)} 的档案">预览</button>
    </div>`;
  }

  function paGrid(board) {
    const {list, total} = paPage(board);
    if (!total) return empty('没有符合条件的选手，换个位置或降低最少局数。');
    return `<div class="pa-grid">${list.map((p) => paCard(p, st.pa.sort)).join('')}</div>`;
  }

  /* 列表视图：一行一人，列与 KPL 赛研的表格式一致。 */
  function paList(board) {
    const {list, total} = paPage(board);
    if (!total) return empty('没有符合条件的选手，换个位置或降低最少局数。');
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const picked = st.pa.picked || [];
    const row = (p) => `<div class="pa-row${p.bound ? '' : ' is-unbound'}" data-pa-goto="${esc(p.name)}">
      <input type="checkbox" class="pa-check" data-pa-check="${esc(p.name)}" ${picked.includes(p.name) ? 'checked' : ''} aria-label="选择 ${esc(p.name)} 参与对比">
      <a class="pa-row-name" href="${esc(paDetailHref(p.name))}">${mono(p.name)}<b>${esc(p.name)}</b>${p.lane ? `<em>${esc(p.lane)}</em>` : ''}${p.bound ? '' : '<em class="is-unbound-tag">待认领</em>'}</a>
      <span>${p.side === 'own' ? '本队' : '对手'}</span>
      <span>${fmt(p.games)} 局</span>
      <span>${pct0(p.winRate)}</span>
      <span>${num(p.kda, 2)}</span>
      <span>${fmt(p.mvp)}</span>
      <span>${pct0(p.participation)}</span>
      <span>${pct0(p.damageShare)}</span>
      <span>${num(p.score, 1)}</span>
    </div>`;
    return `<div class="pa-list"><div class="pa-row is-head"><span></span><span>选手</span><span>阵营</span><span>局数</span><span>胜率</span><span>KDA</span><span>MVP</span><span>参团</span><span>输出</span><span>表现分</span></div>${list.map(row).join('')}</div>`;
  }

  function paBody(board) {
    return st.pa.view === 'list' ? paList(board) : paGrid(board);
  }

  function paPager(board) {
    const {total, pages, page, start, list} = paPage(board);
    if (!total) return '';
    return `<div class="pa-pager">
      <span>第 ${fmt(start + 1)}–${fmt(start + list.length)} 人 · 共 ${fmt(total)} 人</span>
      <span class="pa-pager-btns">
        <button type="button" class="control" data-pa-page="prev" ${page <= 1 ? 'disabled' : ''} aria-label="上一页">‹</button>
        <span class="pa-pager-no">${fmt(page)} / ${fmt(pages)}</span>
        <button type="button" class="control" data-pa-page="next" ${page >= pages ? 'disabled' : ''} aria-label="下一页">›</button>
      </span></div>`;
  }

  /* 勾选状态常驻筛选条：切到网格视图也能看到选了谁、清空、直接对比。 */
  function paPickedBar() {
    const picked = st.pa.picked || [];
    if (!picked.length) return '';
    return `<span class="pa-picked" aria-live="polite">
      <b>已选 ${picked.length}/2</b>${picked.map((name) => `<i>${esc(name)}</i>`).join('')}
      <button type="button" class="pl-link" data-pa-clear-picked>清空</button>
      <button type="button" class="pl-link" data-pa-compare-picked ${picked.length === 2 ? '' : 'disabled'}>对比 →</button>
    </span>`;
  }

  /* 领跑摘要：跟着筛选/切片变，和 KPL 赛研的 brief 一行同款。 */
  function paLeaders(board) {
    const rows = paRows(board);
    if (!rows.length) return '当前筛选没有选手。';
    const stable = rows.filter((p) => (p.games || 0) >= 2);
    const pool = stable.length ? stable : rows;
    const top = (list, key) => [...list].filter((p) => typeof p[key] === 'number').sort((a, b) => b[key] - a[key])[0];
    const kda = top(pool, 'kda'), mvp = top(rows, 'mvp'), dmg = top(pool, 'damageShare'), wr = top(pool, 'winRate');
    const parts = [];
    if (kda) parts.push(`KDA 领跑 <b>${esc(kda.name)}</b>（${num(kda.kda, 2)} · ${fmt(kda.games)} 局）`);
    if (mvp) parts.push(`MVP 最多 <b>${esc(mvp.name)}</b>（${fmt(mvp.mvp)} 次）`);
    if (dmg) parts.push(`输出占比最高 <b>${esc(dmg.name)}</b>（${pct(dmg.damageShare)}）`);
    if (wr) parts.push(`胜率最高 <b>${esc(wr.name)}</b>（${pct(wr.winRate)}）`);
    const prefix = paSliceOn() ? `切片「${esc(paSliceLabel())}」；` : '';
    const suffix = paSliceOn() ? '（KDA / 胜率 / 输出按切片统计，表现分与档位仍是全局口径）' : '';
    const baseCount = (board.players || []).filter((p) =>
      (!st.pa.q.trim() || String(p.name).toLowerCase().includes(st.pa.q.trim().toLowerCase()))
      && (!st.pa.side || p.side === st.pa.side)
      && (!st.pa.lane || p.lane === st.pa.lane)
      && (!st.pa.claim || (st.pa.claim === 'bound' ? !!p.bound : !p.bound))).length;
    const excluded = baseCount - rows.length;
    return `${prefix}当前筛选 <b>${fmt(rows.length)}</b> 人；${parts.join('；')}。${suffix}${excluded > 0 ? `另有 ${fmt(excluded)} 人因切片或最少局数被排除。` : ''}`;
  }

  function exportArchive() {
    const board = st.board;
    if (!board) return;
    const rows = paRows(board);
    const head = ['昵称', '阵营', '位置', '局数', '胜率%', 'KDA', 'MVP', '参团率%', '输出占比%', '经济占比%', '承伤占比%', '表现分'];
    const cell = (v) => (typeof v === 'number' && Number.isFinite(v) ? String(v) : '');
    const body = rows.map((p) => [
      p.name, p.side === 'own' ? '本队' : '对手', p.lane || '', cell(p.games), cell(p.winRate),
      cell(p.kda), cell(p.mvp), cell(p.participation), cell(p.damageShare), cell(p.goldShare), cell(p.takenShare), cell(p.score),
    ]);
    const csv = [head, ...body].map((line) => line.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const blob = new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `选手档案-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function archivePage(board) {
    st.board = board;
    paReadHash();
    const players = board.players || [];
    const own = players.filter((p) => p.side === 'own');
    const enemy = players.length - own.length;
    const ready = players.filter((p) => p.games >= 2);
    const mvps = players.reduce((sum, p) => sum + (p.mvp || 0), 0);
    const rows = paRows(board);
    const paSelect = (key, label, options, value) => `<label>${esc(label)}<select data-pa-filter="${key}" aria-label="${esc(label)}">${options.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
    const head = masthead('选手档案', '逐人档案卡：头像、位置、局数、胜率、KDA、MVP 与参团一眼可比；点卡片进个人页看同位置分位、关键局与搭档。', kpi([
      ['入档选手', `${fmt(players.length)} 人`, `本队 ${fmt(own.length)} · 对手 ${fmt(enemy)}`],
      ['可跨局比较', `${fmt(ready.length)} 人`, '出场 ≥ 2 局'],
      ['本队出场', `${fmt(own.reduce((n, p) => n + p.games, 0))} 人次`, '按营地昵称去重'],
      ['MVP 合计', `${fmt(mvps)} 局`, '营地面板 gradeGame'],
      ['最高 KDA', num([...ready].sort((a, b) => (b.kda || 0) - (a.kda || 0))[0]?.kda, 2), '出场 ≥ 2 局的选手'],
      ['最佳表现分', num([...ready].sort((a, b) => (b.score || 0) - (a.score || 0))[0]?.score, 1), '同位置分位均值'],
      ['筛选命中', `${fmt(rows.length)} 人`, '当前筛选条件下'],
    ]));
    const summary = brief(`共 <b>${fmt(players.length)}</b> 个昵称有营地面板记录（本队 <b>${fmt(own.length)}</b>、对手 <b>${fmt(enemy)}</b>），其中 <b>${fmt(ready.length)}</b> 人跨 2 局以上。卡片按当前排序把最值得看的一项放大显示；点进去是同一份数据的单人详情，不另开口径。`);
    const sliceValue = st.pa.opponent ? `opp:${st.pa.opponent}` : st.pa.day ? `day:${st.pa.day}` : '';
    const sliceSelect = () => {
      const groups = [];
      const opponents = (board.opponents || []).map((o) => `<option value="opp:${esc(o.name)}" ${sliceValue === 'opp:' + o.name ? 'selected' : ''}>${esc(o.name)} · ${fmt(o.games)} 局</option>`);
      const days = (board.days || []).map((d) => `<option value="day:${esc(d)}" ${sliceValue === 'day:' + d ? 'selected' : ''}>${esc(d)}</option>`);
      if (opponents.length) groups.push(`<optgroup label="按对手切片">${opponents.join('')}</optgroup>`);
      if (days.length) groups.push(`<optgroup label="按训练日切片">${days.join('')}</optgroup>`);
      return `<label>切片<select data-pa-filter="slice" aria-label="按对手或训练日切片"><option value="" ${sliceValue ? '' : 'selected'}>全部对局</option>${groups.join('')}</select></label>`;
    };
    const bar = `<div class="hero-filterbar pa-filterbar">
      <label>搜索<input data-pa-search value="${esc(st.pa.q)}" placeholder="选手名，如：信则有" autocomplete="off" spellcheck="false" aria-label="搜索选手昵称"></label>
      ${paSelect('side', '阵营', [['', '全部'], ['own', '本队'], ['enemy', '对手']], st.pa.side)}
      ${paSelect('lane', '位置', [['', '全部位置'], ...LANES.map((x) => [x, x])], st.pa.lane)}
      ${sliceSelect()}
      ${paSelect('sort', '排序', PA_SORTS.map(([key, label]) => [key, `按${label}`]), st.pa.sort)}
      ${paSelect('claim', '认领', [['', '全部'], ['bound', '已认领'], ['unbound', '待认领']], st.pa.claim)}
      ${paSelect('min', '最少局数', [['1', '不限'], ['2', '≥ 2 局'], ['6', '≥ 6 局']], st.pa.min)}
      <span class="pl-filter-count" data-pa-count>共 ${fmt(rows.length)} 人</span>
      ${st.pa.claim === 'unbound' ? '<a class="pa-claim-link" href="#identity">管理认领 →</a>' : ''}
      <span data-pa-picked>${paPickedBar()}</span>
      <span class="pa-tools">
        <span class="pa-view" role="group" aria-label="展示方式">
          <button type="button" data-pa-view="grid" class="${st.pa.view === 'grid' ? 'is-active' : ''}" aria-pressed="${st.pa.view === 'grid'}">网格</button>
          <button type="button" data-pa-view="list" class="${st.pa.view === 'list' ? 'is-active' : ''}" aria-pressed="${st.pa.view === 'list'}">列表</button>
        </span>
        <button type="button" class="control" data-pa-export>导出 CSV</button>
      </span></div>`;
    return `<div class="page hero-detail-page page-wide" data-pl-page="archive">
      ${head}${summary}
      <div class="pa-leaders" data-pa-leaders>${paLeaders(board)}</div>
      ${bar}
      <div data-pa-body>${paBody(board)}</div>
      <div data-pa-pager>${paPager(board)}</div>
      <p class="pl-note">数据来自营地十人面板；胜率只以有胜负的局为分母，MVP 与评分取自营地面板 gradeGame。点卡片进个人页，同位置分位只在各自位置内计算。</p>
    </div>`;
  }

  /* ── 三、选手认领 ─────────────────────────────────────────────── */
  function identityPage(board) {
    st.board = board;
    const s = board.summary || {};
    const identity = board.identity || {};
    const members = identity.members || [];
    const aliases = identity.aliases || {};
    const entries = identity.entries || [];
    const unclaimed = entries.filter(x => !x.bound);
    const claimedGames = entries.filter(x => x.bound).reduce((n, x) => n + x.matches, 0);
    const totalGames = entries.reduce((n, x) => n + x.matches, 0);
    const top = unclaimed.slice(0, 5);
    const head = masthead('选手认领', '身份维护（不在选手栏里常驻）：把营地昵称并到本队名单后，名单、位置与对比都按选手累计，而不是按单局昵称。', kpi([
      ['本队名单', `${fmt(members.length)} 人`, '建档里的本队选手'],
      ['已认领昵称', `${fmt(entries.length - unclaimed.length)} 个`, `共 ${fmt(entries.length)} 个本队侧昵称`],
      ['待认领', `${fmt(unclaimed.length)} 个`, '按出场排序'],
      ['认领覆盖', pct(totalGames ? claimedGames / totalGames * 100 : null), `${fmt(claimedGames)} / ${fmt(totalGames)} 人次`],
      ['映射记录', `${fmt(entries.reduce((n, x) => n + (x.accountIds || []).length, 0))} 条`, '游戏ID → 选手'],
      ['前五覆盖', `${fmt(top.reduce((n, x) => n + x.matches, 0))} 人次`, '待认领里出场最多的五个'],
    ]), '<a class="control" href="#players">← 名单与状态</a>');
    const summaryLine = brief(unclaimed.length
      ? `<b>${fmt(unclaimed.length)} 个</b>本队侧昵称还没认领，覆盖 <b>${fmt(totalGames - claimedGames)} 人次</b>出场。按出场排，前 ${fmt(Math.min(5, top.length))} 个（${top.map(x => `<b>${esc(x.label)}</b> ${fmt(x.matches)} 局`).join('、')}）覆盖了 <b>${fmt(top.reduce((n, x) => n + x.matches, 0))} 人次</b>，先把这几个认领，名单与对比立刻可用。`
      : `本队侧 <b>${fmt(entries.length)} 个昵称</b>已全部认领，名单、位置与对比都按选手累计。`);
    const memberSelect = members.map(m => `<option value="${esc(m.id)}">${esc(m.label || m.name)}${m.position ? ' · ' + esc(m.position) : ''}</option>`).join('');
    const labelSelect = entries.map(x => `<option value="${esc(x.label)}">${esc(x.label)} · ${fmt(x.matches)} 局${x.lane ? ' · ' + esc(x.lane) : ''}${x.bound ? ' · 已认领' : ''}</option>`).join('');
    const claimForm = `<form class="feature-form" data-feature-form="identityClaim" data-aliases="${esc(JSON.stringify(aliases))}">
      <label>对局昵称<select name="label">${labelSelect}</select></label>
      <label>本队选手<select name="playerId">${memberSelect || '<option value="">名单为空，先在下方添加选手</option>'}</select></label>
      <div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit" ${members.length ? '' : 'disabled'}>确认认领</button></div></form>`;
    const rosterForm = `<form class="feature-form" data-feature-form="identityRoster">
      <label>选手名称<input name="name" required maxlength="40" placeholder="例如：星澜·牧川"></label>
      <label>位置<select name="position"><option value="">待确认</option>${LANES.map(x => `<option value="${x}">${x}</option>`).join('')}</select></label>
      <div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit">添加本队选手</button></div></form>`;
    const membersHtml = members.length
      ? `<div class="pl-members">${members.map(m => `<div class="pl-member">${mono(m.label || m.name)}<span><b>${esc(m.label || m.name)}</b><small>${esc(m.position || '位置待填')} · ${fmt(entries.filter(x => x.memberId === m.id).reduce((n, x) => n + (x.accountIds || []).length, 0))} 个游戏ID</small></span></div>`).join('')}</div>`
      : '<p class="pl-note">名单还是空的：先添加本队选手，再回到上面对昵称做认领。</p>';
    /* 映射只认账号表：游戏ID → 选手。旧版按昵称字符串写的 aliases 只作兜底。 */
    const mappedRows = entries.filter(x => x.bound && (x.nicknames || []).length);
    const aliasHtml = mappedRows.length
      ? `<div class="pl-maps">${mappedRows.map((x) => {
        const nicknames = (x.nicknames || []).join(' / ');
        const member = members.find(m => m.id === x.memberId);
        return `<div class="pl-map">${mono(nicknames)}<b>${esc(nicknames)}</b><i>→</i><span>${esc(member ? (member.label || member.name) : (x.name || x.label))}</span><small>${fmt(x.matches)} 局${(x.accountIds || []).length > 1 ? ` · ${(x.accountIds || []).length} 个账号` : ''}</small></div>`;
      }).join('')}</div>`
      : '<p class="pl-note">还没有命名过的游戏ID。到「赛训 → 数据准备 → 身份对照」给游戏ID起名，这里就会显示映射。</p>';
    /* 待认领名单不再重复渲染一份：档案页有「认领 = 待认领」筛选，点进去直接命名。 */
    const topUnclaimed = unclaimed.slice(0, 3);
    const candidateBlock = block('待认领昵称', '名单页的昵称列表已并进档案页：按「认领 = 待认领」筛选，点任意选手即可命名。',
      `<div class="pl-cands-cta">
        <a class="pl-link" href="#playerarchive?claim=unbound">打开档案 · 待认领 ${fmt(unclaimed.length)} 个 →</a>
        <span>${topUnclaimed.map(x => `<b>${esc(x.label)}</b> ${fmt(x.matches)} 局`).join(' · ') || '全部已认领'}</span>
      </div>`);
    const impact = block('认领之后会变什么', '三个页面按选手而不是昵称重新累计。',
      `<div class="pl-impact">
        <div><b>名单与状态</b><span>认领后的选手进入位置名册，状态与走势按选手跨局累计。</span></div>
        <div><b>选手与位置</b><span>按名单位置归类，未认领昵称只作为位置样本，不进名单统计。</span></div>
        <div><b>选手对比</b><span>可选对象从昵称换成选手，历史场次合并后再算分位。</span></div>
      </div>`);
    const unclaimedSelect = unclaimed.map(x => `<option value="${esc(x.label)}">${esc(x.label)} · ${fmt(x.matches)} 局</option>`).join('');
    const nameForm = `<form class="feature-form" data-feature-form="identityName">
      <label>对局昵称<select name="label">${unclaimedSelect || '<option value="">没有待命名昵称</option>'}</select></label>
      <label>选手名称<input name="name" required maxlength="40" placeholder="例如：星澜·牧川"></label>
      <label>位置<select name="position"><option value="">待确认</option>${LANES.map(x => `<option value="${x}">${x}</option>`).join('')}</select></label>
      <label>所属战队<input name="team" maxlength="40" value="${esc(s.teamName || '')}" placeholder="默认本队"></label>
      <div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit" ${unclaimed.length ? '' : 'disabled'}>命名并归队</button></div></form>`;
    const panels = [block('本队名单', '名单是认领的前提；位置用于位置名册与同位置分位。', `<div class="pl-forms">${membersHtml}${rosterForm}</div>`),
      block('命名并归队', '昵称还没有对应选手时用这里：起名、选位置、填战队，一次写入名单与昵称映射；之后名单、状态与对比都按这名选手累计。', `<div class="pl-forms">${nameForm}</div>`),
      block('认领一个昵称', '确认该昵称确属这名本队选手后保存；同一昵称只能属于一名选手。', `<div class="pl-forms">${claimForm}</div>`),
      candidateBlock, block('已建立的映射', '游戏ID → 选手的唯一映射（player_accounts）；删掉映射这里也就没了，历史对局不改。', aliasHtml), impact];
    return `<div class="page hero-detail-page page-wide" data-pl-page="identity">${head}${summaryLine}${anchors(['本队名单', '命名归队', '认领昵称', '待认领', '映射', '影响'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 四、选手与位置 ───────────────────────────────────────────── */
  function lanePage(board) {
    st.board = board;
    const lanes = board.lanes || [];
    const own = ownOf(board);
    const ownGames = lanes.reduce((n, x) => n + (x.own?.games || 0), 0);
    const enemyGames = lanes.reduce((n, x) => n + (x.enemy?.games || 0), 0);
    const best = [...lanes].filter(x => x.own?.winRate != null).sort((a, b) => b.own.winRate - a.own.winRate)[0];
    const worst = [...lanes].filter(x => x.own?.winRate != null).sort((a, b) => a.own.winRate - b.own.winRate)[0];
    const gpmGap = lanes.length ? lanes.reduce((n, x) => n + ((x.own?.gpm || 0) - (x.enemy?.gpm || 0)), 0) / lanes.filter(x => x.own?.gpm && x.enemy?.gpm).length : null;
    /* 同位置经济差最吃亏的一条路（本队 − 对手）。 */
    const gapRows = lanes.map((x) => ({lane: x.lane, gap: (x.own?.gpm || 0) - (x.enemy?.gpm || 0)}))
      .filter((x) => x.gap < 0).sort((a, b) => a.gap - b.gap);
    const weakestGap = gapRows[0] || null;
    const head = masthead('选手与位置', '五条分路各自的经济、输出与参团：谁的位置在赢，赢在哪一段。', kpi([
      ['位置', '5 条', '对抗 / 打野 / 中路 / 发育 / 游走'],
      ['本队人次', fmt(ownGames), '按面板逐位置计数'],
      ['对手人次', fmt(enemyGames), '同口径'],
      ['分均经济差', `${gpmGap >= 0 ? '+' : ''}${num(gpmGap)}`, '本队 − 对手 · 五位置均值', gpmGap > 0 ? 60 : 40],
      ['最强位置', best ? esc(best.lane) : '—', best ? `胜率 ${pct(best.own.winRate)}` : ''],
      ['最弱位置', worst ? esc(worst.lane) : '—', worst ? `胜率 ${pct(worst.own.winRate)}` : ''],
      ['位置内选手', `${fmt(new Set(own.map(p => p.lane)).size)} 组`, '按主位置归类'],
    ]));
    const summaryLine = brief(best
      ? `本队五位置里 <b>${esc(best.lane)}</b> 最稳（胜率 <b>${pct(best.own.winRate)}</b>、分均 <b>${num(best.own.gpm)}</b> 金、参团 <b>${pct(best.own.participation)}</b>），<b>${esc(worst?.lane || '—')}</b> 最弱（<b>${pct(worst?.own.winRate)}</b>）。全位置分均经济${gpmGap >= 0 ? '领先' : '落后'}对手 <b>${num(Math.abs(gpmGap || 0))}</b> 金，差距主要来自${gpmGap >= 0 ? '补刀与野区效率' : '被压线与资源丢失'}。${weakestGap ? `同位置经济差最吃亏的是 <b>${esc(weakestGap.lane)}</b>（场均 <b>${diff(Math.round(weakestGap.gap))}</b> 金）。` : ''}`
      : '本期还没有位置样本。');
    const rows = lanes.map((x) => {
      const o = x.own || {}, e = x.enemy || {};
      const maxGpm = Math.max(1, o.gpm || 0, e.gpm || 0);
      const maxDpm = Math.max(1, o.dpm || 0, e.dpm || 0);
      return `<div class="pl-lane-row">
        <span class="pl-lane">${esc(x.lane)}</span>
        <span class="pl-lane-wr"><b>${pct(o.winRate)}</b><div class="pl-track"><i style="width:${o.winRate == null ? 0 : clamp(o.winRate)}%"></i></div><small>本队胜率 · ${fmt(o.games)} 人次</small></span>
        <span class="pl-lane-pair"><div class="pl-dual"><i class="is-own" style="width:${(o.gpm || 0) / maxGpm * 100}%"></i><i class="is-enemy" style="width:${(e.gpm || 0) / maxGpm * 100}%"></i></div><span><b>${num(o.gpm)}</b><em>${num(e.gpm)}</em></span></span>
        <span class="pl-lane-pair"><div class="pl-dual"><i class="is-own" style="width:${(o.dpm || 0) / maxDpm * 100}%"></i><i class="is-enemy" style="width:${(e.dpm || 0) / maxDpm * 100}%"></i></div><span><b>${num(o.dpm)}</b><em>${num(e.dpm)}</em></span></span>
        <span class="pl-metric"><small>参团率</small><b>${pct(o.participation)}</b></span>
        <span class="pl-metric"><small>位置内人数</small><b>${fmt(o.players)}</b></span>
      </div>`;
    }).join('');
    const strength = block('位置强度对照', '同一标尺下本队与对手的分均经济、分均输出；胜率按有胜负的面板计。',
      `<div class="pl-lanes"><div class="pl-lanes-head"><span>位置</span><span>本队胜率</span><span>分均经济</span><span>分均输出</span><span>参团率</span><span>人数</span></div>${rows}</div>
       <p class="pl-note">条形深色为本队、浅色为对手，两条各自按位置内最大值缩放，跨位置不比长度。</p>`);
    const byLane = LANES.map((lane) => {
      const all = own.filter(p => p.lane === lane);
      const ranked = [...all].sort((a, b) => (b.games - a.games) || ((b.score || 0) - (a.score || 0)));
      const ready = all.filter(p => p.games >= 2).sort((a, b) => (b.score || 0) - (a.score || 0));
      return {lane, list: [...ready, ...ranked.filter(p => !ready.includes(p))].slice(0, 3)};
    }).filter(x => x.list.length);
    const inside = block('位置内选手', '每个位置列 3 人（先跨 2 局以上、再按出场补齐）；其余在档案页按位置筛。',
      `<div class="pl-lane-cols">${byLane.map(col => `<div class="pl-lane-col">
        <b>${esc(col.lane)}<a class="pl-lane-col-all" href="#playerarchive?lane=${encodeURIComponent(col.lane)}&min=2">全部 →</a></b>${col.list.map(p => `<a class="pl-lane-player" href="${esc(href(p.name))}">${mono(p.name)}<span>${esc(p.name)}<small>${fmt(p.games)} 局 · 胜率 ${pct(p.winRate)}</small></span><em class="${p.games >= 2 ? '' : 'is-thin'}">${p.games >= 2 ? num(p.score, 1) : '单局'}</em></a>`).join('')}
      </div>`).join('')}</div>`);
    const depth = (() => {
      const maxPlayers = Math.max(1, ...lanes.map(x => x.own?.players || 0));
      const totalPlayers = lanes.reduce((n, x) => n + (x.own?.players || 0), 0);
      const totalGames = lanes.reduce((n, x) => n + (x.own?.games || 0), 0);
      const rows = lanes.map((x) => {
        const people = x.own?.players || 0;
        const games = x.own?.games || 0;
        const per = people ? games / people : 0;
        const tone = per >= 2 ? 'is-stable' : per >= 1.5 ? 'is-mid' : 'is-thin';
        return `<div class="pl-depth-row">
          <span>${esc(x.lane)}</span>
          <div class="pl-depth-track"><i style="width:${people / maxPlayers * 100}%"></i></div>
          <b>${fmt(people)} 人</b>
          <span class="pl-depth-per"><em>${num(per, 1)}</em> 局/人</span>
          <small class="pl-depth-tone ${tone}">${per >= 2 ? '稳定' : per >= 1.5 ? '一般' : '轮换'}</small>
        </div>`;
      }).join('');
      return block('位置深度', '条长 = 该位置出场过的不同昵称数；局/人 = 人均样本，越高说明这个位置越固定。',
        `<div class="pl-depth">${rows}</div><p class="pl-note">五位置合计 <b>${fmt(totalPlayers)}</b> 个位置昵称（跨位置会重复计）、<b>${fmt(totalGames)}</b> 人次；人均低于 1.5 局的位置基本还在轮换。</p>`);
    })();
    const diffs = {};
    for (const lane of LANES) diffs[lane] = [];
    for (const game of board.games || []) {
      const o = new Map(), e = new Map();
      for (const p of game.own || []) if (!o.has(p.lane)) o.set(p.lane, p);
      for (const p of game.enemy || []) if (!e.has(p.lane)) e.set(p.lane, p);
      for (const lane of LANES) {
        const a = o.get(lane), b = e.get(lane);
        if (a && b) diffs[lane].push(a.gold - b.gold);
      }
    }
    /* 经济差：所有位置共用一条 ±峰值 的对称刻度，条长可直接横向比较。 */
    const gapPeak = (() => {
      const raw = Math.max(0, ...LANES.map((name) => {
        const values = diffs[name] || [];
        return values.length ? Math.abs(values.reduce((a, b) => a + b, 0) / values.length) : 0;
      }));
      return Math.max(500, Math.ceil(raw / 250) * 250);
    })();
    const matchup = block('同位置经济差', '逐局把本队与对手同位置对位，取终局经济差；这是对线期到终局的净结果。',
      `<div class="pl-matchup">
        <div class="pl-matchup-head"><span></span><div class="pl-axis"><i>${diff(-gapPeak)}</i><i>0</i><i>${diff(gapPeak)}</i></div><span></span><span></span></div>
        ${LANES.map(lane => {
        const list = diffs[lane];
        if (!list.length) return `<div class="pl-matchup-row"><span>${esc(lane)}</span><div class="pl-bipole is-empty"></div><em>无对位样本</em><small></small></div>`;
        const avg = list.reduce((a, b) => a + b, 0) / list.length;
        const ahead = list.filter(v => v > 0).length;
        return `<div class="pl-matchup-row"><span>${esc(lane)}</span>
          <div class="pl-bipole"><i class="${avg >= 0 ? 'is-pos' : 'is-neg'}" style="width:${Math.min(50, Math.abs(avg) / gapPeak * 50)}%"></i></div>
          <b class="${avg >= 0 ? 'is-pos' : 'is-neg'}">${diff(Math.round(avg))}</b>
          <small>领先 ${fmt(ahead)} / ${fmt(list.length)} 局</small></div>`;
      }).join('')}</div><p class="pl-note">经济差按同位置同局配对，未配对的面板不计入；横轴为 ±${fmt(gapPeak)} 金的对称刻度，正值为本队领先，条长可跨位置直接比。</p>`);
    const multi = own.filter(p => (p.laneMix || []).length > 1).sort((a, b) => b.games - a.games).slice(0, 8);
    const multiBlock = block('多位置选手', '会打两个以上位置的选手：轮换与临场补位的主要来源。',
      multi.length ? `<div class="pl-multi">${multi.map(p => `<a class="pl-multi-row" href="${esc(href(p.name))}">${mono(p.name)}<b>${esc(p.name)}</b>${(p.laneMix || []).map(x => `<span>${esc(x.lane)} <em>${fmt(x.games)}</em></span>`).join('')}<small>共 ${fmt(p.games)} 局</small></a>`).join('')}</div>` : empty('本期没有跨位置出场的选手。'));
    const panels = [strength, inside, depth, matchup, multiBlock];
    return `<div class="page hero-detail-page page-wide" data-pl-page="lane">${head}${summaryLine}${anchors(['位置强度', '位置内选手', '位置深度', '同位置经济差', '多位置'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 五、选手对比 ─────────────────────────────────────────────── */
  const METRICS = [
    ['kda', 'KDA', 2, ''],
    ['gpm', '分均经济', 0, ''],
    ['dpm', '分均输出', 0, ''],
    ['participation', '参团率', 1, '%'],
    ['damageShare', '输出占比', 1, '%'],
    ['goldShare', '经济占比', 1, '%'],
    ['takenShare', '承伤占比', 1, '%'],
    ['dtpm', '分均承伤', 0, ''],
  ];
  const showValue = (v, digits, unit) => typeof v === 'number' ? `${fmt(v, digits)}${unit}` : '—';

  function radar(series) {
    const size = 340, cx = size / 2, cy = size / 2 + 6, R = size / 2 - 58;
    const axes = METRICS.slice(0, 6);
    const point = (i, r) => {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / axes.length;
      return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
    };
    const ring = (k) => `<polygon class="pl-radar-ring${Math.abs(k - 0.5) < 1e-6 ? ' is-mid' : ''}" points="${axes.map((_, i) => point(i, R * k).map(v => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = axes.map((_, i) => { const [x, y] = point(i, R); return `<line class="pl-radar-spoke" x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join('');
    const labels = axes.map((axis, i) => {
      const [x, y] = point(i, R + 28);
      return `<text class="pl-radar-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${esc(axis[1])}</text>`;
    }).join('');
    const midTick = `<text class="pl-radar-tick" x="${cx + 7}" y="${(cy - R * 0.5 + 4).toFixed(1)}">50</text>`;
    const areas = series.map(x => `<polygon class="pl-radar-area ${x.cls}" points="${x.values.map((v, i) => point(i, R * clamp(v) / 100).map(n => n.toFixed(1)).join(',')).join(' ')}"/>`).join('');
    const dots = series.map(x => x.values.map((v, i) => { const [px, py] = point(i, R * clamp(v) / 100); return `<circle class="pl-radar-dot ${x.cls}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="3.4"><title>${esc(axes[i][1])} ${num(v, 0)} 分位</title></circle>`; }).join('')).join('');
    return `<svg class="pl-radar-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="同位置分位雷达">${[0.25, 0.5, 0.75, 1].map(ring).join('')}${spokes}${areas}${dots}${midTick}${labels}</svg>`;
  }

  function comparePage(board) {
    st.board = board;
    const pool = (board.players || []).filter(p => p.games >= 1).sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
    /* 先选对路、再选选手：对路只收窄候选；切路时当前人选不在该路，就换成该路前两名。 */
    const lanePool = st.cmpLane ? pool.filter(p => p.lane === st.cmpLane) : pool;
    const candidates = lanePool.length ? lanePool : pool;
    const eligible = candidates.filter(p => p.games >= 2);
    const firstOther = (list, name) => list.find(p => p.name !== name);
    const inCandidates = (name) => candidates.some(p => p.name === name);
    if (!st.a || !inCandidates(st.a)) st.a = (eligible[0] || candidates[0] || {}).name || '';
    if (!st.b || st.b === st.a || !inCandidates(st.b)) {
      st.b = ((firstOther(eligible, st.a) || firstOther(candidates, st.a) || {}).name) || st.a;
    }
    const A = byName(board, st.a) || candidates[0], B = byName(board, st.b) || candidates[1] || candidates[0];
    if (!A || !B) return `<div class="page hero-detail-page" data-pl-page="compare">${masthead('选手对比', '选择两名选手并列对比。', '')}${empty('本期还没有可对比的选手。')}</div>`;
    const group = (list, current) => {
      const own = list.filter(p => p.side === 'own'), enemy = list.filter(p => p.side === 'enemy');
      const opts = (arr) => arr.map(p => `<option value="${esc(p.name)}" ${p.name === current ? 'selected' : ''}>${esc(p.name)} · ${esc(p.lane)} · ${fmt(p.games)} 局</option>`).join('');
      return `${own.length ? `<optgroup label="本队侧">${opts(own)}</optgroup>` : ''}${enemy.length ? `<optgroup label="对手侧">${opts(enemy)}</optgroup>` : ''}`;
    };
    const laneStable = st.cmpLane ? candidates.filter(p => p.games >= 2).length : null;
    const picker = `<div class="hero-filterbar pl-picker" role="group" aria-label="选择对路与对比选手">
      <label>对路<select data-pl-filter="lane" aria-label="对路"><option value="">全部位置</option>${LANES.map(l => `<option value="${esc(l)}" ${st.cmpLane === l ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
      <label>选手 A<select data-pl-filter="a" aria-label="选手 A">${group(candidates, A.name)}</select></label>
      <span class="pl-vs-mark">VS</span>
      <label>选手 B<select data-pl-filter="b" aria-label="选手 B">${group(candidates, B.name)}</select></label>
      <button type="button" class="control" data-pl-swap aria-label="交换两名选手">交换</button>
      ${(st.recent || []).length ? `<span class="pl-recent" aria-label="最近对比">最近：${(st.recent || []).slice(0, 4).map(n => `<button type="button" data-pl-recent="${esc(n)}">${esc(n)}</button>`).join('')}</span>` : ''}
      <span class="pl-filter-count">先选对路可只看同路选手 · 分位只在各自位置内比较</span>
      ${st.cmpLane && laneStable < 2 ? `<span class="pl-filter-count is-warn">该路只有 ${fmt(laneStable)} 人打了 ≥2 局，对比样本偏薄</span>` : ''}</div>`;
    const scoreOf = (p, key) => p.percent?.[key];
    const rows = METRICS.map(([key, label, digits, unit]) => {
      const a = A[key], b = B[key];
      const max = Math.max(1, Math.abs(a || 0), Math.abs(b || 0));
      const aWin = typeof a === 'number' && typeof b === 'number' && a > b;
      const bWin = typeof a === 'number' && typeof b === 'number' && b > a;
      return `<div class="pl-compare-row">
        <span class="pl-compare-label">${esc(label)}</span>
        <span class="pl-compare-a ${aWin ? 'is-lead' : ''}">${showValue(a, digits, unit)}</span>
        <div class="pl-compare-bars"><i class="is-a ${aWin ? 'is-lead' : ''}" style="width:${Math.abs(a || 0) / max * 50}%"></i><i class="is-b ${bWin ? 'is-lead' : ''}" style="width:${Math.abs(b || 0) / max * 50}%"></i></div>
        <span class="pl-compare-b ${bWin ? 'is-lead' : ''}">${showValue(b, digits, unit)}</span>
      </div>`;
    }).join('');
    const head = masthead('选手对比', '把两名选手放在同一组指标上：原始值并列，分位只在各自位置内计算。', kpi([
      ['选手 A', `<a class="pl-kpi-link" href="${esc(href(A.name))}">${esc(A.name)}</a>`, `${esc(A.lane)} · ${fmt(A.games)} 局 · 胜率 ${pct(A.winRate)}`],
      ['选手 B', `<a class="pl-kpi-link" href="${esc(href(B.name))}">${esc(B.name)}</a>`, `${esc(B.lane)} · ${fmt(B.games)} 局 · 胜率 ${pct(B.winRate)}`],
      ['表现分差', `${A.score != null && B.score != null ? (A.score - B.score >= 0 ? '+' : '') + num(A.score - B.score, 1) : '—'}`, 'A − B · 同位置分位'],
      ['场次差', `${A.games - B.games >= 0 ? '+' : ''}${fmt(A.games - B.games)}`, '样本量差异'],
      ['同场对局', fmt((board.games || []).filter(g => [...(g.own || []), ...(g.enemy || [])].some(x => x.name === A.name) && [...(g.own || []), ...(g.enemy || [])].some(x => x.name === B.name)).length), '两人同时在场'],
      ['英雄池', `${fmt((A.heroes || []).length)} / ${fmt((B.heroes || []).length)}`, '各自主用英雄数'],
    ]));
    const summaryLine = brief(`A <b><a class="pl-kpi-link" href="${esc(href(A.name))}">${esc(A.name)}</a></b>（${esc(A.lane)}，${fmt(A.games)} 局）与 B <b><a class="pl-kpi-link" href="${esc(href(B.name))}">${esc(B.name)}</a></b>（${esc(B.lane)}，${fmt(B.games)} 局）：${A.score != null && B.score != null
      ? `表现分 <b>${num(A.score, 1)}</b> 对 <b>${num(B.score, 1)}</b>，${Math.abs(A.score - B.score) < 5 ? '两人在同一档' : `相差 <b>${num(Math.abs(A.score - B.score), 1)}</b> 分`}。`
      : ''}${A.lane !== B.lane ? `两人不在同一位置，原始值只能看形状，强弱以各自位置分位为准。` : '同位置对比，分位可直接横向读。'}`);
    const metricBlock = block('指标对位', '左侧 A、右侧 B，条形按两者最大值缩放；深色一端为该项领先。', `<div class="pl-compare-head"><span>指标</span><span class="pl-compare-a"><a href="${esc(href(A.name))}">${esc(A.name)}</a></span><span></span><span class="pl-compare-b"><a href="${esc(href(B.name))}">${esc(B.name)}</a></span></div><div class="pl-compare-rows">${rows}</div>`);
    const radarBlock = block('同位置分位雷达', '六项分位：越靠外越强，50 为分路平均。数值为各自位置内的百分位。',
      `<div class="pl-radar-grid"><div class="pl-radar-wrap">${radar([
        {name: A.name, cls: 'is-a', values: METRICS.slice(0, 6).map(([key]) => scoreOf(A, key) || 0)},
        {name: B.name, cls: 'is-b', values: METRICS.slice(0, 6).map(([key]) => scoreOf(B, key) || 0)},
      ])}<div class="pl-radar-legend"><span><i class="is-a"></i>${esc(A.name)}</span><span><i class="is-b"></i>${esc(B.name)}</span></div></div>
      <div class="pl-percent-table">${METRICS.slice(0, 6).map(([key, label]) => `<div><span>${esc(label)}</span><b>${num(scoreOf(A, key), 0)}</b><em>${num(scoreOf(B, key), 0)}</em></div>`).join('')}</div></div>`);
    const heroA = new Set((A.heroes || []).map(x => x.hero));
    const heroB = new Set((B.heroes || []).map(x => x.hero));
    const both = [...heroA].filter(x => heroB.has(x));
    const poolBlock = block('英雄池对照', '各自主用英雄（营地面板 Top 6）的重合与差异。',
      `<div class="pl-pool-cols">
        <div><b>仅 ${esc(A.name)}</b><span class="pl-pool-chips">${[...heroA].filter(x => !heroB.has(x)).map(h => `<span>${portrait(h)}${esc(h)}</span>`).join('') || '<em>无</em>'}</span></div>
        <div class="is-both ${both.length ? '' : 'is-empty'}"><b>两人都用</b><span class="pl-pool-chips">${both.map(h => `<span>${portrait(h)}${esc(h)}</span>`).join('') || '<em>无重合</em>'}</span></div>
        <div><b>仅 ${esc(B.name)}</b><span class="pl-pool-chips">${[...heroB].filter(x => !heroA.has(x)).map(h => `<span>${portrait(h)}${esc(h)}</span>`).join('') || '<em>无</em>'}</span></div>
      </div>`);
    const shared = (board.games || []).filter(g => {
      const names = [...(g.own || []), ...(g.enemy || [])].map(x => x.name);
      return names.includes(A.name) && names.includes(B.name);
    }).slice(0, 8);
    const sharedBlock = block('同场记录', '两人同时在场的对局；同一阵营看配合，不同阵营看对位。',
      shared.length ? `<div class="pl-shared"><div class="pl-shared-row is-head"><b>日期</b><span>对手</span><em>结果</em><span class="pl-shared-line">${esc(A.name)}</span><span class="pl-shared-line">${esc(B.name)}</span></div>${shared.map((g, i) => {
        const inOwn = (g.own || []).some(x => x.name === A.name) && (g.own || []).some(x => x.name === B.name);
        const lineOf = (name) => {
          const item = [...(g.own || []), ...(g.enemy || [])].find(x => x.name === name);
          return item ? `<i class="pl-hp">${portrait(item.hero)}</i>${esc(item.hero || '未知')} <b>${num(item.kda, 1)}</b>` : '—';
        };
        const sameDay = i > 0 && shared[i - 1].day === g.day;
        return `<div class="pl-shared-row"><b>${sameDay ? '' : esc(g.day || '')}</b><span>${esc(g.opponent || '对手未标注')}</span><em class="${resCls(g.result)}">${resWord(g.result)}${inOwn ? '' : ' · 对位'}</em><span class="pl-shared-line">${lineOf(A.name)}</span><span class="pl-shared-line">${lineOf(B.name)}</span></div>`;
      }).join('')}</div>` : empty('两人还没有同场记录。'));
    const seriesBlock = block('逐局评分', '各自最近 12 场的营地评分，纵轴同尺度。',
      `<div class="pl-two-series">${[[A, 'is-a'], [B, 'is-b']].map(([p, cls]) => `<div class="pl-series ${cls}"><b><a href="${esc(href(p.name))}">${esc(p.name)}</a></b>${spark([...(p.recent || [])].reverse(), {w: 520, h: 168})}</div>`).join('')}</div>`);
    const panels = [metricBlock, radarBlock, poolBlock, sharedBlock, seriesBlock];
    return `<div class="page hero-detail-page page-wide" data-pl-page="playercompare">${head}${summaryLine}${picker}${anchors(['指标对位', '分位雷达', '英雄池', '同场记录', '逐局评分'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 六、单人详情 ─────────────────────────────────────────────── */
  /* 不新增接口：个人聚合与分位来自 board.players，搭档与逐局名单来自 board.games。
     分位口径与对比页一致 —— 只在同位置内部比较，跨位置只看原始值不看分位。 */
  const SOLO_METRICS = [
    ['kda', 'KDA', 2, ''],
    ['gpm', '分均经济', 0, ''],
    ['dpm', '分均输出', 0, ''],
    ['participation', '参团率', 1, '%'],
    ['goldShare', '经济占比', 1, '%'],
    ['damageShare', '输出占比', 1, '%'],
    ['takenShare', '承伤占比', 1, '%'],
  ];
  const STYLE_DIMS = [
    ['gpm', '资源投入'],
    ['dpm', '输出产出'],
    ['participation', '团战参与'],
    ['takenShare', '承伤承担'],
    ['kda', '生存收割'],
    ['goldShare', '经济份额'],
  ];

  function soloPage(board, name) {
    st.board = board;
    const players = board.players || [];
    const player = players.find(p => p.name === name);
    if (!player) {
      const back = st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">
        <header class="hero-masthead"><div class="page-intro"><div class="pls-head">
          <a class="hero-back" href="${esc(back.href)}">← ${esc(back.label)}</a>
          <div class="pls-id"><div><h1>未找到这名选手</h1><p>链接里的昵称在当前数据里没有出场记录，可能已换号或本期未参赛。</p></div></div></div></div></header>
        <div class="hero-detail-grid"><section class="section"><div class="section-heading"><div><h2>回到名单</h2><p>本队全部昵称都在名单与状态页。</p></div></div><p class="pl-note">也可以直接在选手池里点名字进入个人页。</p><div class="pls-empty-actions"><a class="pl-link" href="#players">← 名单与状态</a><a class="pl-link" href="#compare">选手与位置</a></div></section></div></div>`;
    }
    const isOwn = player.side === 'own';
    const lane = player.lane || '';
    /* 切片：档案带过来的 ?opp= / ?day=。原始值按切片算，分位/档位仍是全局口径。 */
    const query = new URLSearchParams(String(location.hash.split('?')[1] || ''));
    const sliceKey = query.get('opp') ? {kind: 'opponent', key: query.get('opp')}
      : query.get('day') ? {kind: 'day', key: query.get('day')} : null;
    const sliceRow = sliceKey ? ((player.splits || {})[sliceKey.kind] || {})[sliceKey.key] : null;
    const sliceName = sliceKey ? (sliceKey.kind === 'opponent' ? `对阵 ${sliceKey.key}` : `${sliceKey.key} 当天`) : '';
    const base = sliceRow ? {...player, ...sliceRow} : player;
    const peers = players.filter(p => p.lane === lane && p.games >= 1);
    const ownPeers = peers.filter(p => p.side === 'own').length;
    const enemyPeers = peers.length - ownPeers;
    const percentOf = (key) => (typeof player.percent?.[key] === 'number' ? player.percent[key] : null);
    const valuesOf = (key) => peers.map(p => p[key]).filter(v => typeof v === 'number');
    const rankOf = (key) => {
      if (typeof player[key] !== 'number') return null;
      return peers.filter(p => typeof p[key] === 'number' && p[key] > player[key]).length + 1;
    };
    const form = player.form || {};
    const recentAll = [...(player.recent || [])];
    const recent = sliceKey
      ? recentAll.filter(g => (sliceKey.kind === 'opponent' ? g.opponent === sliceKey.key : g.day === sliceKey.key))
      : recentAll;
    const rated = recent.filter(g => typeof g.rating === 'number').sort((a, b) => b.rating - a.rating);
    const losses = Math.max(0, (base.decided || 0) - (base.wins || 0));
    const scoreRank = typeof player.score === 'number'
      ? players.filter(p => p.lane === lane && typeof p.score === 'number' && p.score > player.score).length + 1 : null;

    const kpiHtml = kpi([
      ['出场', `${fmt(base.games)} 局`, `${fmt(base.wins)} 胜 ${fmt(losses)} 负`],
      ['胜率', pct(base.winRate), base.decided ? `${fmt(base.wins)} / ${fmt(base.decided)} 有胜负` : '暂无有胜负对局', base.winRate],
      ['表现分', num(player.score, 1), scoreRank ? `同位置第 ${fmt(scoreRank)} / ${fmt(peers.length)}` : '同位置分位均值', player.score],
      ['KDA', num(base.kda, 2), rankOf('kda') ? `同位置第 ${fmt(rankOf('kda'))} 位` : '无同位置样本'],
      ['分均经济', num(base.gpm), '营地结算 gold / 分钟'],
      ['分均输出', num(base.dpm), '营地结算 hurt / 分钟'],
      ['近况', form.available ? `${toneArrow(form.tone)} ${num(form.delta, 1)}` : '样本不足',
        form.available ? `近 3 场 ${num(form.recent, 1)} · 此前 ${num(form.prior, 1)}` : `评分 ${fmt(form.samples || 0)} 场`],
    ]);

    /* 返回按钮跟着来源走：从档案点进来就回档案（带筛选），从名册/位置/对比点进来就回对应页。 */
    const back = st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
    const backExtra = String(back.href).startsWith('#players') ? '' : '<a class="hero-back is-quiet" href="#players">名单与状态</a>';
    const head = `<header class="hero-masthead"><div class="page-intro"><div class="pls-head">
      <span class="pls-back-row"><a class="hero-back" href="${esc(back.href)}">← ${esc(back.label)}</a>${backExtra}</span>
      <div class="pls-id"><span class="pls-ava" aria-hidden="true">${esc(String(player.name).trim().slice(0, 1) || '?')}</span>
        <div><h1>${esc(player.name)}</h1><p>${esc(lane || '位置未记录')} · ${isOwn ? '本队侧' : '对手侧'} · ${player.bound ? '已认领' : '待认领昵称'}${(player.laneMix || []).length > 1 ? ` · 兼 ${esc(player.laneMix.slice(1).map(x => x.lane).join(' / '))}` : ''}</p>
        ${sliceKey ? `<span class="pls-slice">切片：<b>${esc(sliceName)}</b> · ${fmt(base.games)} 局 · <a href="${esc(href(player.name))}">切回全局</a></span>` : ''}</div></div></div>
      <div class="intro-actions">${player.bound ? '' : `<button class="control" data-pl-name="${esc(player.name)}">命名并归队</button>`}<button class="control" data-pl-pick-b="${esc(player.name)}">放入对比</button><button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;

    const dims = SOLO_METRICS.map(([key, label]) => ({key, label, value: percentOf(key)})).filter(d => d.value != null);
    const rankedDims = [...dims].sort((a, b) => b.value - a.value);
    const best = rankedDims[0], worst = rankedDims[rankedDims.length - 1];
    const briefHtml = brief(`${sliceKey ? `切片 <b>${esc(sliceName)}</b>：<b>${fmt(base.games)} 局</b>、${fmt(base.wins)} 胜 ${fmt(losses)} 负（胜率 <b>${pct(base.winRate)}</b>）。分位与档位仍是全局口径。<br>` : ''}全局 <b>${fmt(player.games)} 局</b>、${fmt(player.wins)} 胜 ${fmt(player.games - player.wins)} 负（胜率 <b>${pct(player.winRate)}</b>），表现分 <b>${num(player.score, 1)}</b>（50 = 分路平均）。${best && rankedDims.length > 1 ? `同位置最强的是 <b>${esc(best.label)}</b>（${num(best.value, 0)} 分位），最弱的是 <b>${esc(worst.label)}</b>（${num(worst.value, 0)} 分位）。` : ''}${form.available ? `近 3 场平均评分 <b>${num(form.recent, 1)}</b>，比此前 3 场${form.delta >= 0 ? '高' : '低'} <b>${num(Math.abs(form.delta), 1)}</b>。` : '营地评分不足 6 场，暂不给趋势结论。'}`);

    /* 同位置分位：条形为分位，右侧给原始值、位置中位与名次 */
    const metricRows = SOLO_METRICS.map(([key, label, digits, unit]) => {
      const value = sliceKey ? base[key] : player[key];
      const percent = percentOf(key);
      const median = medianOf(valuesOf(key));
      const rank = rankOf(key);
      const width = percent == null ? 0 : clamp(percent);
      return `<div class="pls-metric${percent == null ? ' is-none' : ''}">
        <span class="pls-metric-k">${esc(label)}</span>
        <div class="pls-metric-bar"><i style="width:${width}%"></i><em aria-hidden="true"></em></div>
        <b class="pls-metric-v">${showValue(value, digits, unit)}</b>
        <small class="pls-metric-med">位置中位 ${showValue(median, digits, unit)}</small>
        <small class="pls-metric-pct">${percent == null ? '无样本' : `超过 ${num(percent, 0)}%`}</small>
        <small class="pls-metric-rank">${rank ? `第 ${fmt(rank)} / ${fmt(peers.length)}` : '—'}</small>
      </div>`;
    }).join('');
    const scoreParts = ['kda', 'gpm', 'dpm', 'participation']
      .map(key => [SOLO_METRICS.find(item => item[0] === key)?.[1], percentOf(key)]);
    const metricNote = `<p class="pl-note">${sliceKey ? '原始值按切片统计，分位与名次为全局口径；' : ''}同位置样本 <b>${fmt(peers.length)}</b> 人（本队 <b>${fmt(ownPeers)}</b> · 对手 <b>${fmt(enemyPeers)}</b>）。分位 = 在该位置里超过百分之多少，不跨位置比较；表现分 <b>${num(player.score, 1)}</b> = ${scoreParts.map(([label, value]) => `${esc(label)} ${num(value, 1)}`).join(' · ')} 的平均。</p>`;
    const percentileBlock = block('同位置分位', '七项同位置百分位 · 条形越满越靠前，竖线为 50（分路平均）。', `<div class="pls-metrics">${metricRows}</div>${metricNote}`);

    /* 打法画像：分位阈值给标签，再给一句读法；阈值写在页面上，避免黑箱 */
    const tags = [];
    const addTag = (key, hiText, loText) => {
      const value = percentOf(key);
      if (value == null) return;
      const label = STYLE_DIMS.find(item => item[0] === key)?.[1] || key;
      if (value >= 65) tags.push({cls: 'is-hi', text: hiText, note: `${label} ${num(value, 0)} 分位`});
      else if (value <= 35) tags.push({cls: 'is-lo', text: loText, note: `${label} ${num(value, 0)} 分位`});
    };
    addTag('gpm', '资源优先', '让出资源');
    addTag('dpm', '输出核心', '输出偏低');
    addTag('participation', '团战参与', '独立行动');
    addTag('takenShare', '前排承伤', '后排站位');
    addTag('kda', '生存稳定', '阵亡偏多');
    addTag('goldShare', '吃线核心', '份额偏低');
    const gp = percentOf('gpm'), dp = percentOf('dpm'), part = percentOf('participation'),
      taken = percentOf('takenShare'), kdaPct = percentOf('kda');
    let role = '分位样本不足，先按原始值读，不下角色结论。';
    if ([gp, dp, part, taken, kdaPct].every(v => v != null)) {
      if (taken >= 65 && dp <= 40) role = '前排承伤型：伤害和站位交给团队，个人产出本来就不在报表上。';
      else if (gp >= 65 && dp >= 65) role = '发育输出型：资源给到他、产出也落在他身上。';
      else if (part >= 65 && gp <= 40) role = '节奏支援型：经济让出去，靠参团与支援创造价值。';
      else if (kdaPct >= 65 && dp >= 40) role = '稳健执行型：不冒风险、指标均衡，适合放在体系位。';
      else if (gp <= 40 && dp <= 40) role = '功能位：不占资源也不吃输出，主要提供控制与视野。';
      else role = '均衡型：各项分位不极端，强项随对手与阵容摆动。';
    }
    const styleBars = STYLE_DIMS.map(([key, label]) => {
      const value = percentOf(key);
      return `<div class="pls-style-row"><span>${esc(label)}</span><div class="pls-style-track"><i style="width:${value == null ? 0 : clamp(value)}%"></i><em aria-hidden="true"></em></div><b>${value == null ? '—' : num(value, 0)}</b></div>`;
    }).join('');
    const styleBlock = block('打法画像', '标签由同位置分位按固定阈值生成（≥65 / ≤35），只做快速读法，不作为结论。',
      `${tags.length ? `<div class="pls-tags">${tags.slice(0, 5).map(t => `<span class="pls-tag ${t.cls}"><b>${esc(t.text)}</b><i>${esc(t.note)}</i></span>`).join('')}</div>` : ''}
       <div class="pls-styles">${styleBars}</div>
       <p class="pl-note">${esc(role)}</p>`);

    /* 逐局表现：评分走势 + 稳定性 + 明细 */
    const ratings = recent.map(g => g.rating).filter(v => typeof v === 'number');
    const kdas = recent.map(g => g.kda).filter(v => typeof v === 'number');
    const meanRating = meanOf(ratings);
    const sdRating = sdOf(ratings);
    const meanKda = meanOf(kdas);
    const cvKda = meanKda ? sdOf(kdas) / meanKda : null;
    const stability = `<div class="pls-kpis">${[
      [`近 ${fmt(recent.length)} 局评分`, num(meanRating, 1), '营地 gradeGame 均值'],
      ['评分波动', sdRating == null ? '—' : `±${num(sdRating, 1)}`, '标准差，越小越稳'],
      ['KDA 波动系数', cvKda == null ? '—' : num(cvKda, 2), '标准差 ÷ 均值'],
      ['MVP', `${fmt(player.mvp)} 局`, player.games ? `占 ${pct(player.mvp / player.games * 100)}` : '—'],
    ].map(([label, value, note]) => `<div><span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('')}</div>`;
    const gameRows = recent.map(g => `<div class="pls-game">
      <span class="pls-gday">${esc(String(g.at || g.day || '').slice(5))}</span>
      <span class="pls-gopp">${esc(g.opponent || '对手未标注')}</span>
      <span class="pls-ghero"><i class="pl-hp">${portrait(g.hero)}</i>${esc(g.hero || '未知')}</span>
      <span class="pls-glane">${esc(g.lane || '—')}</span>
      <em class="pls-gres ${resCls(g.result)}">${resWord(g.result)}</em>
      <b class="pls-gkda">${num(g.kda, 1)}</b>
      <b class="pls-ggpm">${num(g.gpm)}</b>
      <b class="pls-gdpm">${num(g.dpm)}</b>
      <b class="pls-grate">${num(g.rating, 1)}${g.mvp ? '<i class="pls-mvp">MVP</i>' : ''}</b>
    </div>`).join('');
    const gameBlock = block('逐局表现', '最近 12 局的营地结算，按开赛时间倒序；评分与 MVP 都取自营地面板。',
      `${stability}${ratings.length ? `<div class="pls-spark-head"><b>评分走势</b><small>近 ${fmt(recent.length)} 局 · 金点为负局 · 点按圆点看单场</small></div>${spark([...recent].reverse())}` : ''}
       <div class="pls-games">${recent.length ? `<div class="pls-game is-head"><span>日期</span><span>对手</span><span>英雄</span><span>分路</span><span>结果</span><span>KDA</span><span>分均经济</span><span>分均输出</span><span>评分</span></div>${gameRows}` : empty('这名选手还没有逐局记录。')}</div>`);

    /* 关键局：近 12 局评分的最高 / 最低各 3 局 */
    const high = rated.slice(0, Math.min(3, rated.length));
    const low = rated.slice(Math.max(0, rated.length - 3)).reverse();
    const keyCard = (g, cls) => `<div class="pls-key ${cls}">
      <span class="pls-key-day">${esc(String(g.at || g.day || '').slice(5))}</span>
      <i class="pl-hp">${portrait(g.hero)}</i>
      <span class="pls-key-main"><b>${esc(g.hero || '未知英雄')}</b><small>${esc(g.opponent || '对手未标注')}${g.lane ? ` · ${esc(g.lane)}` : ''}</small></span>
      <em class="${resCls(g.result)}">${resWord(g.result)}</em>
      <b class="pls-key-rate">${num(g.rating, 1)}</b>
      <small class="pls-key-kda">KDA ${num(g.kda, 1)}</small>
    </div>`;
    const keyBlock = rated.length >= 4
      ? block('关键局', '近 12 局里评分最高与最低各 3 局。本平台没有系列赛决胜局标记，这里用逐局评分极值代替。',
        `<div class="pls-key-cols"><div><b>高光局</b>${high.map(g => keyCard(g, 'is-high')).join('')}</div><div><b>低谷局</b>${low.map(g => keyCard(g, 'is-low')).join('')}</div></div>`)
      : block('关键局', '评分极值', empty('评分样本不足 4 局，先看逐局表现。'));

    /* 同局对位：每局同位置的对手是谁、终局经济差多少。数据全在 board.games，不用另开接口。 */
    const gameById = new Map((board.games || []).map((g) => [g.id, g]));
    const oppSide = isOwn ? 'enemy' : 'own';
    const matchups = recent.map((g) => {
      const game = gameById.get(g.gameId);
      if (!game) return null;
      const self = (game[player.side] || []).find((x) => x.name === player.name);
      if (!self) return null;
      const foe = (game[oppSide] || []).find((x) => x.lane === (g.lane || lane));
      if (!foe) return null;
      return {at: g.at || g.day, hero: self.hero || g.hero, foeName: foe.name, foeHero: foe.hero, diff: (self.gold || 0) - (foe.gold || 0), result: g.result};
    }).filter(Boolean).slice(0, 10);
    const matchupBlock = (() => {
      if (!matchups.length) return block('同局对位', '同位置对手', empty('最近的对局里没有可对位的同位置记录。'));
      const total = matchups.length;
      const avg = matchups.reduce((sum, item) => sum + item.diff, 0) / total;
      const ahead = matchups.filter((item) => item.diff > 0).length;
      const rows = matchups.map((item) => `<div class="pls-duel-row">
        <span class="pls-duel-day">${esc(String(item.at || '').slice(5))}</span>
        <span class="pls-duel-hero"><i class="pl-hp">${portrait(item.hero)}</i>${esc(item.hero || '未知')}</span>
        <span class="pls-duel-foe"><i class="pl-hp">${portrait(item.foeHero)}</i>${esc(item.foeName)}<small>${esc(item.foeHero || '未知')}</small></span>
        <b class="${item.diff >= 0 ? 'is-pos' : 'is-neg'}">${diff(item.diff)}</b>
        <em class="${resCls(item.result)}">${resWord(item.result)}</em>
      </div>`).join('');
      return block('同局对位', '每局对位的同位置对手与终局经济差；正值为我方领先。',
        `<div class="pls-duels"><div class="pls-duel-row is-head"><span>日期</span><span>我的英雄</span><span>对位对手</span><span>经济差</span><span>结果</span></div>${rows}</div>
         <p class="pl-note">共 <b>${fmt(total)}</b> 局有可对位记录，场均 <b>${diff(Math.round(avg))}</b> 金，领先 <b>${fmt(ahead)} / ${fmt(total)}</b> 局。</p>`);
    })();

    /* 搭档：同阵营共现（对手侧按对手阵营算） */
    const partnerMap = new Map();
    for (const game of board.games || []) {
      const lineup = (isOwn ? game.own : game.enemy) || [];
      if (!lineup.some(x => x.name === player.name)) continue;
      const teamWin = isOwn ? game.result : (game.result === 'win' ? 'loss' : game.result === 'loss' ? 'win' : game.result);
      for (const mate of lineup) {
        if (mate.name === player.name) continue;
        const item = partnerMap.get(mate.name) || {name: mate.name, games: 0, wins: 0, decided: 0, heroes: new Map()};
        item.games += 1;
        if (teamWin === 'win' || teamWin === 'loss') {
          item.decided += 1;
          if (teamWin === 'win') item.wins += 1;
        }
        if (mate.hero) item.heroes.set(mate.hero, (item.heroes.get(mate.hero) || 0) + 1);
        partnerMap.set(mate.name, item);
      }
    }
    const partners = [...partnerMap.values()]
      .sort((a, b) => b.games - a.games || b.wins - a.wins || a.name.localeCompare(b.name))
      .slice(0, 8);
    const partnerRows = partners.map(p => {
      const mateHero = [...p.heroes].sort((a, b) => b[1] - a[1])[0]?.[0] || '';
      return `<a class="pls-partner" href="${esc(href(p.name))}">
        ${mono(p.name)}
        <span class="pls-partner-main"><b>${esc(p.name)}</b><small>同场 ${fmt(p.games)} 局${p.decided ? ` · 组合胜率 ${pct(p.wins / p.decided * 100)}` : ''}</small></span>
        <i class="pl-hp" title="${esc(mateHero || '英雄未记录')}">${portrait(mateHero)}</i>
      </a>`;
    }).join('');
    const partnerBlock = block('搭档', '同阵营同局共现；组合胜率只算有胜负的局，缺胜负的局只计同场次数。',
      partners.length ? `<div class="pls-partners">${partnerRows}</div><p class="pl-note">最多列 8 人，按同场局数排。点名字进对方个人页。</p>` : empty('还没有同阵营的同场记录。'));

    /* 英雄池：出场与胜率同源；旧服务端没有 decided 字段时只显示出场 */
    const heroes = (player.heroes || []).filter(x => x.hero).slice(0, 6);
    const heroDecided = heroes.some(x => typeof x.decided === 'number');
    const maxHeroGames = Math.max(1, ...heroes.map(x => x.games));
    const heroRows = heroes.map(x => {
      const decided = x.decided || 0;
      return `<div class="pls-hero">
        <i class="pl-hp">${portrait(x.hero)}</i>
        <span class="pls-hero-main"><b>${esc(x.hero)}</b><small>${fmt(x.games)} 局${decided ? ` · ${fmt(x.wins)} 胜 ${fmt(decided - x.wins)} 负` : ''}${typeof x.rating === 'number' ? ` · 评分 ${num(x.rating, 1)}` : ''}${typeof x.kda === 'number' ? ` · KDA ${num(x.kda, 2)}` : ''}</small></span>
        <div class="pls-hero-track"><i style="width:${x.games / maxHeroGames * 100}%"></i></div>
        ${heroDecided ? `<b>${decided ? pct(x.wins / decided * 100) : '—'}</b>` : ''}
      </div>`;
    }).join('');
    const heroBlock = block('英雄池', 'Top 6 出场英雄，胜率只以有胜负的局为分母。',
      heroes.length ? `<div class="pls-heroes${heroDecided ? '' : ' is-simple'}">${heroRows}</div>` : empty('这名选手还没有英雄记录。'));

    /* 同位置其他选手：这一页的出入口，点名字继续下钻 */
    const others = peers.filter(p => p.name !== player.name)
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    const peerRows = others.slice(0, 8).map((p, i) => `<a class="pls-peer" href="${esc(href(p.name))}">
      <span class="pl-no">${String(i + 1).padStart(2, '0')}</span>
      ${mono(p.name)}
      <span class="pls-peer-main"><b>${esc(p.name)}</b><small>${fmt(p.games)} 局 · ${p.side === 'own' ? '本队' : '对手'}${p.bound ? ' · 已认领' : ''}</small></span>
      <b class="pls-peer-score">${num(p.score, 1)}</b>
      <em class="pls-peer-bar">${track(p.score || 0)}</em>
    </a>`).join('');
    const peerBlock = block('同位置选手', `同一位置共 ${fmt(peers.length)} 人（本队 ${fmt(ownPeers)} · 对手 ${fmt(enemyPeers)}），按表现分排。`,
      peerRows ? `<div class="pls-peers">${peerRows}</div><p class="pl-note">表现分只对跨 2 局以上的样本有意义；1 局样本的名次会随单场波动。</p>` : empty('这个位置没有其他选手。'));

    const panels = [percentileBlock, styleBlock, gameBlock, matchupBlock, keyBlock, partnerBlock, heroBlock, peerBlock];
    return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${briefHtml}${anchors(['同位置分位', '打法画像', '逐局表现', '同局对位', '关键局', '搭档', '英雄池', '同位置选手'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 交互 ─────────────────────────────────────────────────────── */
  function pageRoot() {
    return document.querySelector('[data-pl-page]');
  }
  function refreshPool() {
    const board = st.board, root = pageRoot();
    if (!board || !root) return;
    const target = root.querySelector('[data-pl-pool]');
    if (!target) return;
    const pool = poolRows(board);
    target.innerHTML = pool.html;
    const count = root.querySelector('[data-pl-count]');
    if (count) count.textContent = poolLabel(pool);
  }
  function refreshArchive() {
    const board = st.board, root = pageRoot();
    if (!board || !root) return;
    const body = root.querySelector('[data-pa-body]');
    if (body) body.innerHTML = paBody(board);
    const pager = root.querySelector('[data-pa-pager]');
    if (pager) pager.innerHTML = paPager(board);
    const leaders = root.querySelector('[data-pa-leaders]');
    if (leaders) leaders.innerHTML = paLeaders(board);
    const count = root.querySelector('[data-pa-count]');
    if (count) count.textContent = `共 ${fmt(paRows(board).length)} 人`;
    const picked = root.querySelector('[data-pa-picked]');
    if (picked) picked.innerHTML = paPickedBar();
    const claimLink = root.querySelector('.pa-claim-link');
    if (claimLink) claimLink.hidden = st.pa.claim !== 'unbound';
    root.querySelectorAll('[data-pa-view]').forEach((button) => {
      const on = button.dataset.paView === st.pa.view;
      button.classList.toggle('is-active', on);
      button.setAttribute('aria-pressed', String(on));
    });
    paWriteHash();
  }
  /* 对比页整体重渲染（保留滚动位置）；延后一帧，避免在事件派发中替换 DOM。 */
  function refreshCompare() {
    const board = st.board, page = pageRoot();
    if (!board || !page) return;
    const scroll = window.scrollY;
    if (document.activeElement && page.contains(document.activeElement)) document.activeElement.blur();
    setTimeout(() => {
      if (!page.isConnected) return;
      page.outerHTML = comparePage(board);
      window.scrollTo(0, scroll);
    }, 0);
  }
  function change(event) {
    /* 对比页：输入/选择选手（精确匹配才切换，避免打字过程中反复重渲染）。 */
    const pickInput = event.target.closest('[data-pl-pick-input]');
    if (pickInput) {
      const key = pickInput.dataset.plPickInput;
      const target = byName(st.board, pickInput.value.trim());
      if (!target || st[key] === target.name) return true;
      const otherKey = key === 'a' ? 'b' : 'a';
      const previous = st[key];
      st[key] = target.name;
      if (st.a === st.b) st[otherKey] = previous && previous !== target.name ? previous : '';
      st.recent = [target.name, ...(st.recent || []).filter(n => n !== target.name)].slice(0, 5);
      refreshCompare();
      return true;
    }
    if (event.target.matches('[data-pa-search]')) {
      st.pa.q = event.target.value || '';
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    const pa = event.target.closest('[data-pa-filter]');
    if (pa) {
      const key = pa.dataset.paFilter;
      if (key === 'slice') {
        const value = pa.value || '';
        st.pa.opponent = value.startsWith('opp:') ? value.slice(4) : '';
        st.pa.day = value.startsWith('day:') ? value.slice(4) : '';
      } else {
        st.pa[key] = key === 'min' ? (Number(pa.value) || 1) : pa.value;
      }
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    if (event.target.matches('[data-pl-search]')) {
      st.q = event.target.value || '';
      refreshPool();
      return true;
    }
    const control = event.target.closest('[data-pl-filter]');
    if (!control) return false;
    const key = control.dataset.plFilter;
    const value = control.value;
    if (key === 'min') st.min = Number(value) || 1;
    else if (key === 'sort') st.sort = value;
    else if (key === 'trend') {
      st.trend = value;
      const board = st.board, root = pageRoot();
      const comparable = ownOf(board).filter(p => p.games >= 2).sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
      const section = control.closest('.section');
      if (section) section.outerHTML = trendBlock(board, comparable);
      return true;
    } else if (key === 'lane') {
      st.cmpLane = value;
      const lanePool = value
        ? (st.board?.players || []).filter(p => p.lane === value && p.games >= 1)
        : (st.board?.players || []).filter(p => p.games >= 1);
      if (lanePool.length) {
        const ranked = [...lanePool].sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
        const names = new Set(lanePool.map(p => p.name));
        if (!names.has(st.a)) st.a = ranked[0].name;
        if (!names.has(st.b) || st.b === st.a) {
          const stableB = ranked.filter(p => p.name !== st.a && p.games >= 2);
          const anyB = ranked.filter(p => p.name !== st.a);
          st.b = (stableB[0] || anyB[0] || ranked[0]).name;
        }
      }
      refreshCompare();
      return true;
    } else if (key === 'a' || key === 'b') {
      const otherKey = key === 'a' ? 'b' : 'a';
      const previous = st[key];
      st[key] = value;
      // 两侧不能是同一个人：撞车时把另一侧换成改之前的自己，等价于左右对调
      if (st.a === st.b) st[otherKey] = previous && previous !== value ? previous : '';
      const board = st.board;
      const page = pageRoot();
      if (page && board) {
        const scroll = window.scrollY;
        page.outerHTML = comparePage(board);
        window.scrollTo(0, scroll);
      }
      return true;
    }
    refreshPool();
    return true;
  }
  /* 档案抽屉：不跳页看同位置分位 / 标签 / 搭档 / 最近三局。 */
  function drawerHtml(player) {
    const board = st.board || {};
    const percent = player.percent || {};
    const tier = paTier(player.score);
    const metrics = SOLO_METRICS.map(([key, label, digits, unit]) => {
      const value = percent[key];
      return `<div class="pld-metric"><span>${esc(label)}</span><div class="pld-track"><i style="width:${value == null ? 0 : clamp(value)}%"></i></div><b>${showValue(player[key], digits, unit)}</b><em>${value == null ? '—' : num(value, 0)}</em></div>`;
    }).join('');
    const tags = [];
    [['gpm', '资源优先', '让出资源'], ['dpm', '输出核心', '输出偏低'], ['participation', '团战参与', '独立行动'],
      ['takenShare', '前排承伤', '后排站位'], ['kda', '生存稳定', '阵亡偏多']].forEach(([key, hi, lo]) => {
      const value = percent[key];
      if (value == null) return;
      if (value >= 65) tags.push([hi, 'is-hi']);
      else if (value <= 35) tags.push([lo, 'is-lo']);
    });
    const mates = new Map();
    for (const game of board.games || []) {
      const lineup = (player.side === 'own' ? game.own : game.enemy) || [];
      if (!lineup.some(x => x.name === player.name)) continue;
      for (const mate of lineup) {
        if (mate.name === player.name) continue;
        const item = mates.get(mate.name) || {name: mate.name, games: 0};
        item.games += 1;
        mates.set(mate.name, item);
      }
    }
    const partners = [...mates.values()].sort((a, b) => b.games - a.games).slice(0, 3);
    const recent = (player.recent || []).slice(0, 3);
    return `<aside class="pl-drawer" id="pl-drawer" role="dialog" aria-label="${esc(player.name)} 的档案预览">
      <header class="pld-head">
        <span class="pld-ava">${esc(String(player.name).trim().slice(0, 1) || '?')}${tier ? `<i class="pa-tier is-${tier.toLowerCase()}">${tier}</i>` : ''}</span>
        <div><h2>${esc(player.name)}</h2><p>${esc(player.lane || '位置未记录')} · ${player.side === 'own' ? '本队' : '对手'} · ${player.bound ? '已认领' : '待认领'}</p></div>
        <button type="button" class="head-button" data-drawer-close aria-label="关闭档案预览">×</button>
      </header>
      <div class="pld-body">
        <div class="pld-kpis">
          <div><small>出场</small><b>${fmt(player.games)} 局</b></div>
          <div><small>胜率</small><b>${pct(player.winRate)}</b></div>
          <div><small>KDA</small><b>${num(player.kda, 2)}</b></div>
          <div><small>表现分</small><b>${num(player.score, 1)}</b></div>
        </div>
        <section><h3>同位置分位</h3>${metrics}</section>
        ${tags.length ? `<section><h3>自动标签</h3><div class="pld-tags">${tags.slice(0, 5).map(([text, cls]) => `<span class="pls-tag ${cls}"><b>${esc(text)}</b></span>`).join('')}</div></section>` : ''}
        ${partners.length ? `<section><h3>搭档</h3>${partners.map(p => `<div class="pld-row"><span>${esc(p.name)}</span><small>同场 ${fmt(p.games)} 局</small></div>`).join('')}</section>` : ''}
        ${recent.length ? `<section><h3>最近 ${fmt(recent.length)} 局</h3>${recent.map(g => `<div class="pld-row"><span>${esc(String(g.at || g.day || '').slice(5))} · ${esc(g.hero || '未知')}</span><small>${resWord(g.result)} · KDA ${num(g.kda, 1)} · 评分 ${num(g.rating, 1)}</small></div>`).join('')}</section>` : ''}
      </div>
      <footer class="pld-foot"><a class="primary" href="${esc(paDetailHref(player.name))}" data-drawer-close>打开完整个人页 →</a></footer>
    </aside>`;
  }
  function openDrawer(name) {
    const player = byName(st.board, name);
    if (!player) return;
    let wrap = document.querySelector('#pl-drawer-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'pl-drawer-wrap';
      wrap.className = 'pl-drawer-wrap';
      document.body.appendChild(wrap);
      document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
    }
    wrap.innerHTML = `<div class="pl-drawer-scrim" data-drawer-close></div>${drawerHtml(player)}`;
    wrap.classList.add('is-open');
    document.body.classList.add('pl-drawer-open');
    wrap.querySelectorAll('[data-drawer-close]').forEach(el => el.addEventListener('click', closeDrawer));
    wrap.querySelector('.pld-head button')?.focus();
  }
  function closeDrawer() {
    const wrap = document.querySelector('#pl-drawer-wrap');
    if (!wrap) return;
    wrap.classList.remove('is-open');
    wrap.innerHTML = '';
    document.body.classList.remove('pl-drawer-open');
  }

  /* 详情页「放入对比」：先选对手，再进对比页。同位置优先，可搜索全部。 */
  function pickDialog(name) {
    const board = st.board;
    const me = byName(board, name);
    if (!me) return;
    let dialog = document.querySelector('#pl-pick-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pl-pick-dialog';
      dialog.className = 'pl-pick-dialog';
      document.body.appendChild(dialog);
    }
    const row = (p) => `<button type="button" class="pl-pick-row" data-pick-b="${esc(p.name)}">
      ${mono(p.name)}
      <span class="pl-pick-row-main"><b>${esc(p.name)}</b><small>${esc(p.lane || '位置未记录')} · ${fmt(p.games)} 局${typeof p.score === 'number' ? ` · 表现分 ${num(p.score, 1)}` : ''}</small></span>
      <em>${p.side === 'own' ? '本队' : '对手'}</em>
    </button>`;
    const sameLane = (board.players || []).filter(p => p.name !== name && p.lane === me.lane)
      .sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 12);
    dialog.innerHTML = `<div class="dialog-head"><div><h2>和谁对比？</h2><p>${esc(name)} · ${esc(me.lane || '位置未记录')}；先列同位置，可搜索其他选手。</p></div><button type="button" class="head-button" data-pick-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <label>搜索选手<input type="search" data-pick-search placeholder="输入昵称" autocomplete="off" aria-label="搜索对比选手"></label>
        <div class="pl-pick-list" data-pick-list>${sameLane.map(row).join('') || '<p class="pl-note">这个位置没有其他选手。</p>'}</div>
      </div>`;
    const list = dialog.querySelector('[data-pick-list]');
    const search = dialog.querySelector('[data-pick-search]');
    search.addEventListener('input', () => {
      const text = search.value.trim().toLowerCase();
      const found = (board.players || []).filter(p => p.name !== name && (!text || p.name.toLowerCase().includes(text)))
        .sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 30);
      list.innerHTML = found.length ? found.map(row).join('') : '<p class="pl-note">没有匹配的选手。</p>';
    });
    dialog.querySelectorAll('[data-pick-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) { dialog.close(); return; }
      const pick = event.target.closest('[data-pick-b]');
      if (!pick) return;
      st.a = name;
      st.b = pick.dataset.pickB;
      st.recent = [st.b, ...(st.recent || []).filter(n => n !== st.b)].slice(0, 5);
      dialog.close();
      location.hash = '#playercompare';
    });
    dialog.showModal();
    setTimeout(() => search.focus(), 30);
  }

  function nameDialog(label) {
    let dialog = document.querySelector('#pl-name-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pl-name-dialog';
      document.body.appendChild(dialog);
    }
    const team = (st.board && st.board.summary && st.board.summary.teamName) || '';
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>命名并归队</h2><p>把「${esc(label)}」归到一名选手和一支战队；保存后这些记录并入该选手。</p></div><button type="button" class="head-button" data-pl-name-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <div class="date-fields"><label>对局昵称<input value="${esc(label)}" readonly></label><label>选手名称<input name="name" required maxlength="40" value="${esc(label)}"></label></div>
        <div class="date-fields"><label>位置<select name="position"><option value="">待确认</option>${LANES.map(x => `<option>${x}</option>`).join('')}</select></label><label>所属战队<input name="team" maxlength="40" value="${esc(team)}" placeholder="默认本队"></label></div>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-pl-name-close>取消</button><button class="primary" type="submit">保存并归队</button></div></form>`;
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('.filter-error');
    dialog.querySelectorAll('[data-pl-name-close]').forEach(b => b.addEventListener('click', () => dialog.close()));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const payload = {label, name: data.get('name'), position: data.get('position'), team: data.get('team')};
      if (!String(payload.name || '').trim()) { error.textContent = '请填写选手名称。'; return; }
      const button = form.querySelector('button[type=submit]');
      button.disabled = true;
      fetch(`${API_BASE}/api/v3/identity/name`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
        .then(async (response) => {
          const body = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(body.detail || '保存失败');
          dialog.close();
          if (reload) reload();
        })
        .catch((err) => { button.disabled = false; error.textContent = err.message; });
    });
    dialog.showModal();
  }

  function click(event) {
    /* 对比页：交换、最近使用；详情页：放入对比时先选对手。 */
    if (event.target.closest('[data-pl-swap]')) {
      const first = st.a; st.a = st.b; st.b = first;
      refreshCompare();
      return true;
    }
    const recentBtn = event.target.closest('[data-pl-recent]');
    if (recentBtn) {
      const name = recentBtn.dataset.plRecent;
      if (byName(st.board, name)) {
        const previous = st.a;
        st.a = name;
        if (st.b === name) st.b = previous && previous !== name ? previous : '';
        st.recent = [name, ...(st.recent || []).filter(n => n !== name)].slice(0, 5);
        refreshCompare();
      }
      return true;
    }
    const pickB = event.target.closest('[data-pl-pick-b]');
    if (pickB) { pickDialog(pickB.dataset.plPickB); return true; }
    const drawerBtn = event.target.closest('[data-pa-drawer]');
    if (drawerBtn) { openDrawer(drawerBtn.dataset.paDrawer); return true; }
    /* 任何进单人详情的链接先记下来源页，详情页的「返回」按来源走，
       不再固定回名单与状态；hash 原样带上，筛选与翻页都能还原。 */
    const detailLink = event.target.closest('a[href^="#playerdetail/"]');
    if (detailLink) {
      const page = document.querySelector('[data-pl-page]');
      const source = page && page.dataset.plPage;
      const labels = {players: '名单与状态', archive: '选手档案', lane: '选手与位置', playercompare: '选手对比', solo: '选手详情'};
      if (source && labels[source]) {
        st.returnTo = {href: location.hash || ('#' + source), label: labels[source]};
      }
      return false;
    }
    const name = event.target.closest('[data-pl-name]');
    if (name) { nameDialog(name.dataset.plName); return true; }
    const pick = event.target.closest('[data-pl-pick]');
    if (pick) {
      st.a = pick.dataset.plPick;
      st.b = '';
      location.hash = '#playercompare';
      return true;
    }
    /* 选手档案：翻页、网格/列表切换、导出 CSV、行内对比 */
    const paCompare = event.target.closest('[data-pa-compare]');
    if (paCompare) {
      st.a = paCompare.dataset.paCompare;
      st.b = '';
      location.hash = '#playercompare';
      return true;
    }
    /* 列表视图勾选：最多 2 人，够了就能直接进对比 */
    const paCheck = event.target.closest('[data-pa-check]');
    if (paCheck) {
      const name = paCheck.dataset.paCheck;
      const picked = st.pa.picked || (st.pa.picked = []);
      if (paCheck.checked) {
        if (!picked.includes(name)) picked.push(name);
        while (picked.length > 2) picked.shift();
      } else {
        const index = picked.indexOf(name);
        if (index >= 0) picked.splice(index, 1);
      }
      refreshArchive();
      return true;
    }
    if (event.target.closest('[data-pa-clear-picked]')) {
      st.pa.picked = [];
      refreshArchive();
      return true;
    }
    if (event.target.closest('[data-pa-compare-picked]')) {
      const [a, b] = st.pa.picked || [];
      if (a && b) {
        st.a = a;
        st.b = b;
        location.hash = '#playercompare';
      }
      return true;
    }
    const paGoto = event.target.closest('[data-pa-goto]');
    if (paGoto && !event.target.closest('button, a, input')) {
      location.hash = href(paGoto.dataset.paGoto);
      return true;
    }
    const paPage = event.target.closest('[data-pa-page]');
    if (paPage) {
      const step = paPage.dataset.paPage === 'prev' ? -1 : 1;
      st.pa.page = Math.max(1, (Number(st.pa.page) || 1) + step);
      refreshArchive();
      return true;
    }
    const paView = event.target.closest('[data-pa-view]');
    if (paView) {
      st.pa.view = paView.dataset.paView;
      refreshArchive();
      return true;
    }
    if (event.target.closest('[data-pa-export]')) { exportArchive(); return true; }
    /* 选手池整行可点：行内的按钮与链接优先，其余位置进个人页 */
    const goto = event.target.closest('[data-pl-goto]');
    if (goto && !event.target.closest('button, a')) {
      const target = goto.dataset.plGoto;
      if (target) {
        location.hash = href(target);
        return true;
      }
    }
    return false;
  }
  return {playersPage, archivePage, identityPage, lanePage, comparePage, soloPage, change, click};
}
