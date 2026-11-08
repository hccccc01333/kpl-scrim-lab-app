/* 选手板块五页 —— 名单与状态 / 选手认领 / 选手与位置 / 选手对比 / 单人详情
   同一份数据源：/api/v2/players-board（营地十人面板逐人逐局记录）。
   视觉语言沿用英雄页 / BP 页：深墨报头 + KPI 条 + 结论句 + 筛选条 +
   锚点导航 + 一块一行。所有分位都在同位置内部计算，不跨位置比较。
   单人详情不另开接口：名单、对局、搭档都从同一份 board 里算。 */

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
  const st = {lane: '', min: 1, sort: 'games', trend: '', q: '', a: '', b: '', side: 'own', board: null};
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

  const kpi = (cells) => `<div class="hero-kpi pl-kpi">${cells.map(([label, value, note, bar, warn]) =>
    `<div class="hero-kpi-cell${warn ? ' is-warn' : ''}"><span>${esc(label)}</span><strong>${value}</strong>${typeof bar === 'number' ? `<div class="hero-kpi-track"><i style="width:${clamp(bar)}%"></i></div>` : ''}<p>${esc(note || '')}</p></div>`).join('')}</div>`;
  const anchors = (labels) => `<nav class="hero-anchor-nav" aria-label="模块快速导航">${labels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;
  const masthead = (title, sub, kpiHtml) => `<header class="hero-masthead"><div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;
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
      const hint = slot.member && !games && slot.player ? `<small class="pl-slot-hint">候选 ${esc(slot.player)} · ${fmt(slot.games)} 局</small>` : '';
      const nameHtml = name ? `<a class="pl-name-link" href="${esc(href(name))}">${esc(name)}</a>` : '暂无出场';
      return `<div class="pl-slot">
        <span class="pl-lane">${esc(slot.lane)}</span>
        <span class="pl-slot-name">${mono(name)}<span class="pl-slot-meta"><b>${nameHtml}</b>${hint}</span>${slot.member
          ? '<em class="pl-tag is-bound">已认领</em>'
          : `<em class="pl-tag">待认领</em>${slot.player ? `<button type="button" class="pl-link" data-pl-name="${esc(slot.player)}">命名</button>` : ''}`}</span>
        <span class="pl-metric pl-slot-games"><small>出场</small><b>${fmt(games)}</b></span>
        <span class="pl-metric pl-slot-wr"><small>胜率</small><b>${pct(player?.winRate)}</b></span>
        <span class="pl-metric pl-slot-score"><small>表现分</small><b>${num(player?.score, 1)}</b></span>
        <span class="pl-slot-bar">${track(player?.score || 0)}<small>同位置分位</small></span>
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
      ['位置覆盖', `${fmt(s.positions)} / 5`, '本期出现过的位置'],
      ['固定搭档', `${fmt(s.pairs)} 组`, '同场 ≥ 2 局'],
    ]));
    const summaryLine = brief(`本期 <b>${fmt(s.games)} 局</b>训练赛、<b>${fmt(s.days)} 个训练日</b>：本队侧 <b>${fmt(s.ownPlayers)} 个昵称</b>出场，其中 <b>${fmt(comparable.length)} 人</b>跨 2 局以上，<b>${fmt(single)} 人</b>只打了 1 局。${top.name
      ? `出场最多是 <b>${esc(top.name)}</b>（<b>${fmt(top.games)} 局</b>、胜率 <b>${pct(top.winRate)}</b>、表现分 <b>${num(top.score, 1)}</b>），也是本期唯一的长样本。`
      : ''}先认领名单，状态与对比才会按选手而不是昵称累计。`);
    const claimBand = unclaimedList.length ? `<div class="pl-claim">
      <div class="pl-claim-head"><span class="pl-claim-kicker">身份待确认</span><b>${fmt(unclaimedList.length)} 个昵称还没命名</b><p>覆盖 ${fmt(unclaimedGames)} 人次出场。命名并归队后，名单、状态与对比才会按选手累计，而不是按单局昵称。</p></div>
      <div class="pl-claim-list">${unclaimedTop.map(x => `<span class="pl-claim-item">${mono(x.label)}<span><b>${esc(x.label)}</b><small>${esc(x.lane || '位置未记录')} · ${fmt(x.matches)} 局</small></span><button type="button" class="pl-link" data-pl-name="${esc(x.label)}">命名</button></span>`).join('')}</div>
      <a class="pl-claim-all" href="#identity">全部 ${fmt(unclaimedList.length)} 个 →</a>
    </div>` : '';
    const pool = poolRows(board);
    const filterBar = `<div class="hero-filterbar pl-filterbar">
      ${select('lane', '位置', [['', '全部位置'], ...LANES.map(x => [x, x])], st.lane)}
      ${select('min', '最少局数', [['1', '不限局数'], ['2', '≥ 2 局'], ['6', '≥ 6 局']], st.min)}
      ${select('sort', '排序', [['games', '按出场'], ['score', '按表现分'], ['winRate', '按胜率'], ['kda', '按 KDA'], ['gpm', '按分均经济']], st.sort)}
      <label>搜昵称<input type="search" data-pl-search value="${esc(st.q)}" placeholder="输入昵称关键字" autocomplete="off" spellcheck="false"></label>
      <span class="pl-filter-count" data-pl-count>${poolLabel(pool)}</span></div>`;
    const slots = block('位置名册', '五个位置一行：已认领就直接显示名单选手，未认领给出本期出场最多的候选。',
      `<div class="pl-slots">${rosterRows(board)}</div>`);
    const comparableBlock = block(identityReady ? '可跨局比较的选手' : '可跨局比较的昵称',
      identityReady ? `出场 ≥ 2 局的 ${fmt(comparable.length)} 人；其余 ${fmt(single)} 人是单局样本，只进选手池。`
        : `出场 ≥ 2 局的 ${fmt(comparable.length)} 个昵称；还没命名，只能按昵称横向比较，命名后才会并成选手。`,
      `<div class="pl-grid ${comparable.length <= 4 ? 'is-tight' : ''}">${comparable.map(playerCard).join('') || empty('本期还没有跨 2 局的选手。')}</div>`);
    const codex = block('选手池', `按出场、表现分或位置筛选；表现分 = 同位置 KDA / 分均经济 / 分均输出 / 参团率的平均分位。${identityReady ? '' : ' 当前行内都是营地昵称，尚未命名。'}`,
      `${filterBar}<div class="pl-rows" data-pl-pool>${pool.html}</div>`);
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
    const panels = [slots, comparableBlock, trendBlock(board, comparable), codex, hist, lineups];
    return `<div class="page hero-detail-page" data-pl-page="players">${head}${summaryLine}${claimBand}${anchors(['位置名册', '可比选手', '状态走势', '选手池', '出场结构', '最近对局'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 二、选手认领 ─────────────────────────────────────────────── */
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
    const head = masthead('选手认领', '把营地昵称并到本队名单：认领之后，名单、位置与对比都按选手累计，而不是按单局昵称。', kpi([
      ['本队名单', `${fmt(members.length)} 人`, '建档里的本队选手'],
      ['已认领昵称', `${fmt(entries.length - unclaimed.length)} 个`, `共 ${fmt(entries.length)} 个本队侧昵称`],
      ['待认领', `${fmt(unclaimed.length)} 个`, '按出场排序'],
      ['认领覆盖', pct(totalGames ? claimedGames / totalGames * 100 : null), `${fmt(claimedGames)} / ${fmt(totalGames)} 人次`],
      ['映射记录', `${fmt(Object.keys(aliases).length)} 条`, '人工确认的昵称 → 选手'],
      ['前五覆盖', `${fmt(top.reduce((n, x) => n + x.matches, 0))} 人次`, '待认领里出场最多的五个'],
    ]));
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
      ? `<div class="pl-members">${members.map(m => `<div class="pl-member">${mono(m.label || m.name)}<span><b>${esc(m.label || m.name)}</b><small>${esc(m.position || '位置待填')} · ${fmt(Object.values(aliases).filter(id => id === m.id).length)} 个昵称</small></span></div>`).join('')}</div>`
      : '<p class="pl-note">名单还是空的：先添加本队选手，再回到上面对昵称做认领。</p>';
    const aliasHtml = Object.keys(aliases).length
      ? `<div class="pl-maps">${Object.entries(aliases).map(([label, id]) => {
        const member = members.find(m => m.id === id);
        const entry = entries.find(x => x.label === label);
        return `<div class="pl-map">${mono(label)}<b>${esc(label)}</b><i>→</i><span>${esc(member ? (member.label || member.name) : '已删除的选手')}</span><small>${fmt(entry?.matches || 0)} 局</small></div>`;
      }).join('')}</div>`
      : '<p class="pl-note">还没有人工映射。认领会写进建档，下一次同步仍然有效。</p>';
    // 富条目（带同场队友）优先，缺的用认领表兜底
    const rich = new Map((board.unclaimed || []).map(x => [x.name, x]));
    const candidates = unclaimed.slice(0, 12).map(x => {
      const hit = rich.get(x.label) || {};
      return {...x, mates: hit.teammates || []};
    });
    const candidateBlock = block('待认领昵称', '按出场局数排序，附常用英雄与同场最多的人，方便确认这人是谁；行尾直接命名。',
      `<div class="pl-cands">${candidates.map((x, i) => `<div class="pl-cand">
        <span class="pl-no">${String(i + 1).padStart(2, '0')}</span>
        ${mono(x.label)}
        <span class="pl-cand-name"><b>${esc(x.label)}</b><small>${esc(x.lane || '位置未记录')} · 胜率 ${pct(x.winRate)}${x.mates.length ? ` · <i>同场最多 ${esc(x.mates[0].name)} ${fmt(x.mates[0].games)} 局</i>` : ''}</small></span>
        <span class="pl-cand-heroes">${(x.heroes || []).map(portrait).join('') || '<small>暂无英雄</small>'}</span>
        <span class="pl-cand-games"><b>${fmt(x.matches)}</b><small>局</small></span>
        <button type="button" class="pl-link" data-pl-name="${esc(x.label)}">命名</button>
      </div>`).join('') || empty('全部昵称都已认领。')}</div>
      ${unclaimed.length > candidates.length ? `<p class="pl-note">按出场排，这里列前 <b>${fmt(candidates.length)}</b> 个；共 <b>${fmt(unclaimed.length)}</b> 个待认领，其余可在上方「命名并归队」的下拉里选。</p>` : unclaimed.length ? `<p class="pl-note">共 <b>${fmt(unclaimed.length)}</b> 个待认领昵称，已全部列出。</p>` : ''}`);
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
      candidateBlock, block('已建立的映射', '人工确认过的昵称映射，来自建档设置。', aliasHtml), impact];
    return `<div class="page hero-detail-page" data-pl-page="identity">${head}${summaryLine}${anchors(['本队名单', '命名归队', '认领昵称', '待认领', '映射', '影响'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 三、选手与位置 ───────────────────────────────────────────── */
  function lanePage(board) {
    st.board = board;
    const lanes = board.lanes || [];
    const own = ownOf(board);
    const ownGames = lanes.reduce((n, x) => n + (x.own?.games || 0), 0);
    const enemyGames = lanes.reduce((n, x) => n + (x.enemy?.games || 0), 0);
    const best = [...lanes].filter(x => x.own?.winRate != null).sort((a, b) => b.own.winRate - a.own.winRate)[0];
    const worst = [...lanes].filter(x => x.own?.winRate != null).sort((a, b) => a.own.winRate - b.own.winRate)[0];
    const gpmGap = lanes.length ? lanes.reduce((n, x) => n + ((x.own?.gpm || 0) - (x.enemy?.gpm || 0)), 0) / lanes.filter(x => x.own?.gpm && x.enemy?.gpm).length : null;
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
      ? `本队五位置里 <b>${esc(best.lane)}</b> 最稳（胜率 <b>${pct(best.own.winRate)}</b>、分均 <b>${num(best.own.gpm)}</b> 金、参团 <b>${pct(best.own.participation)}</b>），<b>${esc(worst?.lane || '—')}</b> 最弱（<b>${pct(worst?.own.winRate)}</b>）。全位置分均经济${gpmGap >= 0 ? '领先' : '落后'}对手 <b>${num(Math.abs(gpmGap || 0))}</b> 金，差距主要来自${gpmGap >= 0 ? '补刀与野区效率' : '被压线与资源丢失'}。`
      : '本期还没有位置样本。');
    const rows = lanes.map((x) => {
      const o = x.own || {}, e = x.enemy || {};
      const maxGpm = Math.max(1, o.gpm || 0, e.gpm || 0);
      const maxDpm = Math.max(1, o.dpm || 0, e.dpm || 0);
      return `<div class="pl-lane-row">
        <span class="pl-lane">${esc(x.lane)}</span>
        <span class="pl-lane-wr"><b>${pct(o.winRate)}</b><small>本队胜率 · ${fmt(o.games)} 人次</small></span>
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
    const inside = block('位置内选手', '每个位置先列跨 2 局以上的选手，再按出场补齐；表现分只对跨局样本给出。点选手进个人页。',
      `<div class="pl-lane-cols">${byLane.map(col => `<div class="pl-lane-col">
        <b>${esc(col.lane)}</b>${col.list.map(p => `<a class="pl-lane-player" href="${esc(href(p.name))}">${mono(p.name)}<span>${esc(p.name)}<small>${fmt(p.games)} 局 · 胜率 ${pct(p.winRate)}</small></span><em class="${p.games >= 2 ? '' : 'is-thin'}">${p.games >= 2 ? num(p.score, 1) : '单局'}</em></a>`).join('')}
      </div>`).join('')}</div>`);
    const depth = (() => {
      const maxPlayers = Math.max(1, ...lanes.map(x => x.own?.players || 0));
      return block('位置深度', '每个位置有多少人在打、合计多少人次：人多而人次分散，说明位置还在轮换。',
        `<div class="pl-depth">${lanes.map(x => `<div class="pl-depth-row"><span>${esc(x.lane)}</span><div class="pl-depth-track"><i style="width:${(x.own?.players || 0) / maxPlayers * 100}%"></i></div><b>${fmt(x.own?.players)} 人</b><small>${fmt(x.own?.games)} 人次</small></div>`).join('')}</div>`);
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
    const matchup = block('同位置经济差', '逐局把本队与对手同位置对位，取终局经济差；这是对线期到终局的净结果。',
      `<div class="pl-matchup">${LANES.map(lane => {
        const list = diffs[lane];
        if (!list.length) return `<div class="pl-matchup-row"><span>${esc(lane)}</span><em>无对位样本</em></div>`;
        const avg = list.reduce((a, b) => a + b, 0) / list.length;
        const ahead = list.filter(v => v > 0).length;
        const peak = Math.max(1200, ...LANES.map((name) => {
          const values = diffs[name] || [];
          return values.length ? Math.abs(values.reduce((a, b) => a + b, 0) / values.length) : 0;
        }));
        return `<div class="pl-matchup-row"><span>${esc(lane)}</span>
          <div class="pl-bipole"><i class="${avg >= 0 ? 'is-pos' : 'is-neg'}" style="width:${Math.min(50, Math.abs(avg) / (peak * 1.15) * 50)}%"></i></div>
          <b class="${avg >= 0 ? 'is-pos' : 'is-neg'}">${diff(Math.round(avg))}</b>
          <small>领先 ${fmt(ahead)} / ${fmt(list.length)} 局</small></div>`;
      }).join('')}</div><p class="pl-note">经济差按同位置同局配对，未配对的面板不计入；正值为本队领先。</p>`);
    const multi = own.filter(p => (p.laneMix || []).length > 1).sort((a, b) => b.games - a.games).slice(0, 8);
    const multiBlock = block('多位置选手', '会打两个以上位置的选手：轮换与临场补位的主要来源。',
      multi.length ? `<div class="pl-multi">${multi.map(p => `<a class="pl-multi-row" href="${esc(href(p.name))}">${mono(p.name)}<b>${esc(p.name)}</b>${(p.laneMix || []).map(x => `<span>${esc(x.lane)} <em>${fmt(x.games)}</em></span>`).join('')}<small>共 ${fmt(p.games)} 局</small></a>`).join('')}</div>` : empty('本期没有跨位置出场的选手。'));
    const panels = [strength, inside, depth, matchup, multiBlock];
    return `<div class="page hero-detail-page" data-pl-page="lane">${head}${summaryLine}${anchors(['位置强度', '位置内选手', '位置深度', '同位置经济差', '多位置'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 四、选手对比 ─────────────────────────────────────────────── */
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
    const size = 320, cx = size / 2, cy = size / 2 + 6, R = size / 2 - 54;
    const axes = METRICS.slice(0, 6);
    const point = (i, r) => {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / axes.length;
      return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
    };
    const ring = (k) => `<polygon class="pl-radar-ring" points="${axes.map((_, i) => point(i, R * k).map(v => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = axes.map((_, i) => { const [x, y] = point(i, R); return `<line class="pl-radar-spoke" x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join('');
    const labels = axes.map((axis, i) => {
      const [x, y] = point(i, R + 26);
      return `<text class="pl-radar-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${esc(axis[1])}</text>`;
    }).join('');
    const areas = series.map(x => `<polygon class="pl-radar-area ${x.cls}" points="${x.values.map((v, i) => point(i, R * clamp(v) / 100).map(n => n.toFixed(1)).join(',')).join(' ')}"/>`).join('');
    const dots = series.map(x => x.values.map((v, i) => { const [px, py] = point(i, R * clamp(v) / 100); return `<circle class="pl-radar-dot ${x.cls}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="3"/>`; }).join('')).join('');
    return `<svg class="pl-radar-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="同位置分位雷达">${[0.25, 0.5, 0.75, 1].map(ring).join('')}${spokes}${areas}${dots}${labels}</svg>`;
  }

  function comparePage(board) {
    st.board = board;
    const pool = (board.players || []).filter(p => p.games >= 1).sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
    const eligible = pool.filter(p => p.games >= 2);
    const firstOther = (list, name) => list.find(p => p.name !== name);
    if (!st.a) st.a = (eligible[0] || pool[0] || {}).name || '';
    if (!st.b) st.b = ((firstOther(eligible, st.a) || firstOther(pool, st.a) || {}).name) || st.a;
    const A = byName(board, st.a) || pool[0], B = byName(board, st.b) || pool[1] || pool[0];
    if (!A || !B) return `<div class="page hero-detail-page" data-pl-page="compare">${masthead('选手对比', '选择两名选手并列对比。', '')}${empty('本期还没有可对比的选手。')}</div>`;
    const group = (list, current) => {
      const own = list.filter(p => p.side === 'own'), enemy = list.filter(p => p.side === 'enemy');
      const opts = (arr) => arr.map(p => `<option value="${esc(p.name)}" ${p.name === current ? 'selected' : ''}>${esc(p.name)} · ${esc(p.lane)} · ${fmt(p.games)} 局</option>`).join('');
      return `${own.length ? `<optgroup label="本队侧">${opts(own)}</optgroup>` : ''}${enemy.length ? `<optgroup label="对手侧">${opts(enemy)}</optgroup>` : ''}`;
    };
    const picker = `<div class="hero-filterbar pl-picker">
      <label>选手 A<select data-pl-filter="a">${group(pool, A.name)}</select></label>
      <span class="pl-vs-mark">VS</span>
      <label>选手 B<select data-pl-filter="b">${group(pool, B.name)}</select></label>
      <span class="pl-filter-count">同位置分位口径 · 只在各自位置内比较</span></div>`;
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
    return `<div class="page hero-detail-page" data-pl-page="playercompare">${head}${summaryLine}${picker}${anchors(['指标对位', '分位雷达', '英雄池', '同场记录', '逐局评分'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
  }

  /* ── 五、单人详情 ─────────────────────────────────────────────── */
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
      return `<div class="page hero-detail-page" data-pl-page="solo">
        <header class="hero-masthead"><div class="page-intro"><div class="pls-head">
          <a class="hero-back" href="#players">← 名单与状态</a>
          <div class="pls-id"><div><h1>未找到这名选手</h1><p>链接里的昵称在当前数据里没有出场记录，可能已换号或本期未参赛。</p></div></div></div></div></header>
        <div class="hero-detail-grid"><section class="section"><div class="section-heading"><div><h2>回到名单</h2><p>本队全部昵称都在名单与状态页。</p></div></div><p class="pl-note">也可以直接在选手池里点名字进入个人页。</p><div class="pls-empty-actions"><a class="pl-link" href="#players">← 名单与状态</a><a class="pl-link" href="#compare">选手与位置</a></div></section></div></div>`;
    }
    const isOwn = player.side === 'own';
    const lane = player.lane || '';
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
    const recent = [...(player.recent || [])];
    const rated = recent.filter(g => typeof g.rating === 'number').sort((a, b) => b.rating - a.rating);
    const losses = Math.max(0, (player.decided || 0) - (player.wins || 0));
    const scoreRank = typeof player.score === 'number'
      ? players.filter(p => p.lane === lane && typeof p.score === 'number' && p.score > player.score).length + 1 : null;

    const kpiHtml = kpi([
      ['出场', `${fmt(player.games)} 局`, `${fmt(player.wins)} 胜 ${fmt(losses)} 负`],
      ['胜率', pct(player.winRate), player.decided ? `${fmt(player.wins)} / ${fmt(player.decided)} 有胜负` : '暂无有胜负对局', player.winRate],
      ['表现分', num(player.score, 1), scoreRank ? `同位置第 ${fmt(scoreRank)} / ${fmt(peers.length)}` : '同位置分位均值', player.score],
      ['KDA', num(player.kda, 2), rankOf('kda') ? `同位置第 ${fmt(rankOf('kda'))} 位` : '无同位置样本'],
      ['分均经济', num(player.gpm), '营地结算 gold / 分钟'],
      ['分均输出', num(player.dpm), '营地结算 hurt / 分钟'],
      ['近况', form.available ? `${toneArrow(form.tone)} ${num(form.delta, 1)}` : '样本不足',
        form.available ? `近 3 场 ${num(form.recent, 1)} · 此前 ${num(form.prior, 1)}` : `评分 ${fmt(form.samples || 0)} 场`],
    ]);

    const head = `<header class="hero-masthead"><div class="page-intro"><div class="pls-head">
      <a class="hero-back" href="#players">← 名单与状态</a>
      <div class="pls-id"><span class="pls-ava" aria-hidden="true">${esc(String(player.name).trim().slice(0, 1) || '?')}</span>
        <div><h1>${esc(player.name)}</h1><p>${esc(lane || '位置未记录')} · ${isOwn ? '本队侧' : '对手侧'} · ${player.bound ? '已认领' : '待认领昵称'}${(player.laneMix || []).length > 1 ? ` · 兼 ${esc(player.laneMix.slice(1).map(x => x.lane).join(' / '))}` : ''}</p></div></div></div>
      <div class="intro-actions">${player.bound ? '' : `<button class="control" data-pl-name="${esc(player.name)}">命名并归队</button>`}<a class="control" href="#playercompare" data-pl-pick="${esc(player.name)}">放入对比</a><button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;

    const dims = SOLO_METRICS.map(([key, label]) => ({key, label, value: percentOf(key)})).filter(d => d.value != null);
    const rankedDims = [...dims].sort((a, b) => b.value - a.value);
    const best = rankedDims[0], worst = rankedDims[rankedDims.length - 1];
    const briefHtml = brief(`本期 <b>${fmt(player.games)} 局</b>、${fmt(player.wins)} 胜 ${fmt(losses)} 负（胜率 <b>${pct(player.winRate)}</b>），表现分 <b>${num(player.score, 1)}</b>（50 = 分路平均）。${best && rankedDims.length > 1 ? `同位置最强的是 <b>${esc(best.label)}</b>（${num(best.value, 0)} 分位），最弱的是 <b>${esc(worst.label)}</b>（${num(worst.value, 0)} 分位）。` : ''}${form.available ? `近 3 场平均评分 <b>${num(form.recent, 1)}</b>，比此前 3 场${form.delta >= 0 ? '高' : '低'} <b>${num(Math.abs(form.delta), 1)}</b>。` : '营地评分不足 6 场，暂不给趋势结论。'}`);

    /* 同位置分位：条形为分位，右侧给原始值、位置中位与名次 */
    const metricRows = SOLO_METRICS.map(([key, label, digits, unit]) => {
      const value = player[key];
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
    const metricNote = `<p class="pl-note">同位置样本 <b>${fmt(peers.length)}</b> 人（本队 <b>${fmt(ownPeers)}</b> · 对手 <b>${fmt(enemyPeers)}</b>）。分位 = 在该位置里超过百分之多少，不跨位置比较；表现分 <b>${num(player.score, 1)}</b> = ${scoreParts.map(([label, value]) => `${esc(label)} ${num(value, 1)}`).join(' · ')} 的平均。</p>`;
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
        <span class="pls-hero-main"><b>${esc(x.hero)}</b><small>${fmt(x.games)} 局${decided ? ` · ${fmt(x.wins)} 胜 ${fmt(decided - x.wins)} 负` : ''}</small></span>
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

    const panels = [percentileBlock, styleBlock, gameBlock, keyBlock, partnerBlock, heroBlock, peerBlock];
    return `<div class="page hero-detail-page" data-pl-page="solo">${head}${briefHtml}${anchors(['同位置分位', '打法画像', '逐局表现', '关键局', '搭档', '英雄池', '同位置选手'])}<div class="hero-detail-grid">${panels.join('')}</div></div>`;
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
  function change(event) {
    if (event.target.matches('[data-pl-search]')) {
      st.q = event.target.value || '';
      refreshPool();
      return true;
    }
    const control = event.target.closest('[data-pl-filter]');
    if (!control) return false;
    const key = control.dataset.plFilter;
    const value = control.value;
    if (key === 'lane') st.lane = value;
    else if (key === 'min') st.min = Number(value) || 1;
    else if (key === 'sort') st.sort = value;
    else if (key === 'trend') {
      st.trend = value;
      const board = st.board, root = pageRoot();
      const comparable = ownOf(board).filter(p => p.games >= 2).sort((a, b) => b.games - a.games || (b.score || 0) - (a.score || 0));
      const section = control.closest('.section');
      if (section) section.outerHTML = trendBlock(board, comparable);
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
      fetch(`${API_BASE}/api/v2/identity/name`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
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
    const name = event.target.closest('[data-pl-name]');
    if (name) { nameDialog(name.dataset.plName); return true; }
    const pick = event.target.closest('[data-pl-pick]');
    if (pick) {
      st.a = pick.dataset.plPick;
      st.b = '';
      location.hash = '#playercompare';
      return true;
    }
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
  return {playersPage, identityPage, lanePage, comparePage, soloPage, change, click};
}
