/* 选手板块四页 —— 选手档案 / 选手与位置 / 选手对比 / 单人详情
   单人详情实现已拆到 player-detail.js，本文件保留共用工具与交互。
   同一份数据源：/api/v3/players-board（营地十人面板逐人逐局记录）。
   视觉语言沿用英雄页 / BP 页：深墨报头 + KPI 条 + 结论句 + 筛选条 +
   锚点导航 + 一块一行。所有分位都在同位置内部计算，不跨位置比较。
   单人详情不另开接口：名单、对局、搭档都从同一份 board 里算。
   选手档案照 KPL 赛研的选手卡：头像 + 名字/位置 + 一个大指标 + 一行战绩摘要。
   认领与命名就在档案页完成（卡片名字旁、顶部身份条），不再单设名单页与认领页。 */

import {createPlayerDetail} from './player-detail.js';

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
  const st = {a: '', b: '', board: null, ids: null,
    /* 选手档案页的筛选状态；默认按出场排，避免 1 局的高 KDA 霸榜。
       mode 留空表示「按数据自动定」：有选手ID 先看 ID，一个都没有就直接看游戏名。 */
    pa: {q: '', side: '', lane: '', sort: 'games', min: 1, claim: '', slice: '', page: 1,
      view: 'grid', mode: '', picked: []},
    /* 最近对比过的选手（对比页快捷入口）。 */
    recent: [],
    /* 对比页的「对路」筛选，空 = 全部位置。 */
    cmpLane: '',
    /* 从哪一页点进单人详情，返回就回哪一页（带上当时的筛选 hash）。 */
    returnTo: null,
    /* 单人详情的时间窗口：默认近 3 个训练日，点周期按钮切换。 */
    pd: {mode: 'd3'}};
  const detailPage = createPlayerDetail({esc, fmt, portrait, block, empty, st});
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
  const kpi = (cells) => `<div class="hero-kpi pl-kpi" role="group" aria-label="关键指标">${cells.map(([label, value, note, bar, warn]) =>
    `<div class="hero-kpi-cell${warn ? ' is-warn' : ''}"><span>${esc(label)}</span><strong>${value}</strong>${typeof bar === 'number' ? `<div class="hero-kpi-track"><i style="width:${clamp(bar)}%"></i></div>` : ''}<p>${esc(note || '')}</p></div>`).join('')}</div>`;
  const anchors = (labels) => `<nav class="hero-anchor-nav" aria-label="模块快速导航">${labels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;
  const masthead = (title, sub, kpiHtml, extra = '') => `<header class="hero-masthead"><div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${extra}<button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;
  const brief = (html) => `<div class="hero-brief">${html}</div>`;

  const byName = (board, name) => (board.players || []).find(p => p.name === name) || null;
  const ownOf = (board) => (board.players || []).filter(p => p.side === 'own');

  /* ── 逐局评分折线（单人页 / 对比页共用） ─────────────────────────── */
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
  const paSortOf = (key) => PA_SORTS.find((item) => item[0] === key) || PA_SORTS[0];

  /* 切片位：'opp:队名' 或 'day:2026-11-13'。对手与训练日共用同一个参数，
     筛选条上只有一个「范围」下拉，URL 上也只有一个 slice，不再开三套字段。 */
  const splitSlice = (value) => {
    const text = String(value || '');
    const at = text.indexOf(':');
    return at < 0 ? ['', text] : [text.slice(0, at), text.slice(at + 1)];
  };
  /* 取该切片下的个人聚合；没有切片就返回全局。 */
  function paSplit(p) {
    if (!st.pa.slice) return null;
    const [kind, value] = splitSlice(st.pa.slice);
    if (kind === 'day') return (p.splits?.day || {})[value] || null;
    if (kind === 'opp') return (p.splits?.opponent || {})[value] || null;
    return null;
  }
  const paVm = (p) => {
    const slice = paSplit(p);
    return slice ? {...p, ...slice, sliced: true} : p;
  };
  const paSliceOn = () => Boolean(st.pa.slice);
  const paSliceLabel = () => {
    if (!st.pa.slice) return '';
    const [kind, value] = splitSlice(st.pa.slice);
    return kind === 'day' ? `${value} 当天` : `对阵 ${value}`;
  };
  /* 详情页仍读 opp / day 两个参数（那边没改），这里只做一次转换。 */
  const paDetailHref = (name) => {
    const params = new URLSearchParams();
    const [kind, value] = splitSlice(st.pa.slice);
    if (kind === 'opp' && value) params.set('opp', value);
    if (kind === 'day' && value) params.set('day', value);
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
      /* 认领之后 p.name 是选手ID，营地昵称只剩在 nicknames 里 —— 搜索两个都要认。 */
      .filter((p) => (!q || String(p.name).toLowerCase().includes(q)
        || (p.nicknames || []).some((n) => String(n).toLowerCase().includes(q)))
        && (!state.side || p.side === state.side)
        && (!state.lane || p.lane === state.lane)
        && (!state.claim || (state.claim === 'bound' ? !!p.bound : !p.bound))
        && (p.games || 0) >= state.min)
      .sort((a, b) => {
        /* 打过 2 局以上的永远排在只打 1 局的前面：主动按 KDA / 胜率排时，
           1 局的 8.5 KDA、100% 胜率会把真正有样本的人挤到后面去。 */
        const ga = (a.games || 0) >= 2 ? 1 : 0;
        const gb = (b.games || 0) >= 2 ? 1 : 0;
        if (ga !== gb) return gb - ga;
        /* 缺失值永远排最后，不把「没数据」当成 0 参与排序。 */
        const left = typeof value(a) === 'number' ? value(a) : null;
        const right = typeof value(b) === 'number' ? value(b) : null;
        if (left == null && right == null) return b.games - a.games;
        if (left == null) return 1;
        if (right == null) return -1;
        return right - left || b.games - a.games;
      });
  }

  /* 档案页的 URL 参数：读写共用一张字段表，谁也不会漏。
     slice 是对手 / 训练日合一的切片位；旧链接的 opp / opponent / day 照样能打开。 */
  const PA_HASH_KEYS = ['q', 'side', 'lane', 'sort', 'min', 'claim', 'view', 'page'];
  function paReadHash() {
    const query = String(location.hash.split('?')[1] || '');
    if (!query) return;
    const params = new URLSearchParams(query);
    for (const key of PA_HASH_KEYS) {
      if (!params.has(key)) continue;
      const raw = params.get(key) || '';
      st.pa[key] = key === 'min' || key === 'page' ? (Number(raw) || 1) : raw;
    }
    if (params.has('slice')) st.pa.slice = params.get('slice') || '';
    else if (params.has('opp')) st.pa.slice = 'opp:' + (params.get('opp') || '');
    else if (params.has('opponent')) st.pa.slice = 'opp:' + (params.get('opponent') || '');
    else if (params.has('day')) st.pa.slice = 'day:' + (params.get('day') || '');
    if (st.pa.view !== 'list') st.pa.view = 'grid';
    /* 没写 mode 就交给数据决定（有选手ID先看 ID，一个都没有就直接看游戏名）。 */
    if (params.has('mode')) st.pa.mode = params.get('mode') === 'id' ? 'id' : 'name';
  }
  function paWriteHash() {
    if (!document.querySelector('[data-pl-page="archive"]')) return;
    const params = new URLSearchParams();
    if (st.pa.q) params.set('q', st.pa.q);
    if (st.pa.side) params.set('side', st.pa.side);
    if (st.pa.lane) params.set('lane', st.pa.lane);
    if (st.pa.slice) params.set('slice', st.pa.slice);
    if (st.pa.sort !== 'games') params.set('sort', st.pa.sort);
    if (st.pa.min > 1) params.set('min', String(st.pa.min));
    if (st.pa.claim) params.set('claim', st.pa.claim);
    if (st.pa.view !== 'grid') params.set('view', st.pa.view);
    /* ID 是默认视图，只在「按游戏名」时写，URL 保持最短。 */
    if (st.pa.mode === 'name') params.set('mode', 'name');
    if (st.pa.page > 1) params.set('page', String(st.pa.page));
    const query = params.toString();
    const next = '#playerarchive' + (query ? '?' + query : '');
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ── 身份：选手ID ⇄ 游戏名 ──────────────────────────────────────
     一个选手ID（真名）可以挂多个游戏名（小号 / 改名 / 换号）；
     游戏名认领到哪个ID、ID 在哪个战队，都是可改的映射，历史对局记录不动。
     ID 清单来自 /v3/identity/players，战队清单来自同一份接口。 */
  const idRoster = () => (st.ids && st.ids.players) || [];
  const idTeams = () => (st.ids && st.ids.teams) || [];
  const idInfo = (playerId) => idRoster().find((x) => x.id === playerId) || null;
  const idTeamName = (teamId) => (idTeams().find((t) => t.id === teamId) || {}).name || '';
  /* 按选手ID聚合：同一ID下的多个游戏名合并成一行，指标按局数加权。 */
  function idGroups(board) {
    const map = new Map();
    for (const p of board.players || []) {
      if (!p.memberId) continue;
      let group = map.get(p.memberId);
      if (!group) {
        const info = idInfo(p.memberId) || {};
        map.set(p.memberId, group = {
          id: p.memberId, name: info.name || p.name, teamId: info.teamId || '',
          teamName: info.teamName || '', position: info.position || '',
          positionList: info.positions || [], accounts: 0,
          names: [], games: 0, wins: 0, decided: 0, mvp: 0, _kda: 0, _score: 0, _rated: 0,
          sides: new Set(), lanes: new Map(),
        });
      }
      group.names.push(p);
      group.accounts += (p.accountIds || []).length || 1;
      group.games += p.games || 0;
      group.wins += p.wins || 0;
      group.decided += p.decided || 0;
      group.mvp += p.mvp || 0;
      if (typeof p.kda === 'number') { group._kda += p.kda * (p.games || 1); group._rated += (p.games || 1); }
      if (typeof p.score === 'number') group._score += p.score * (p.games || 1);
      group.sides.add(p.side);
      group.lanes.set(p.lane, (group.lanes.get(p.lane) || 0) + (p.games || 0));
    }
    const rows = [...map.values()].map((g) => ({
      ...g,
      kda: g._rated ? g._kda / g._rated : null,
      score: g._rated ? g._score / g._rated : null,
      winRate: g.decided ? g.wins / g.decided * 100 : null,
      side: g.sides.has('own') ? 'own' : 'enemy',
      lane: [...g.lanes.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || g.position || '',
      nameCount: g.names.length,
    }));
    /* 只建了 ID、还没挂游戏名的也要出现（选手ID 允许先建后认领）。 */
    for (const info of idRoster()) {
      if (!map.has(info.id)) {
        rows.push({id: info.id, name: info.name, teamId: info.teamId, teamName: info.teamName,
          position: info.position, positionList: info.positions || [], accounts: info.accounts,
          names: [], games: 0, wins: 0, decided: 0, mvp: 0, kda: null, score: null,
          winRate: null, side: 'own', lane: info.position || '', nameCount: 0});
      }
    }
    return rows.sort((a, b) => b.games - a.games || String(a.name).localeCompare(String(b.name), 'zh'));
  }

  /* ── 档案页组件（rs = roster） ────────────────────────────────────
     整页只有一种卡片：位置块 + 名字/认领 + 右侧一个数字。
     样本不足的号只降灰、不换结构 —— 「有的卡有头像有的没有」正是廉价感的来源。 */
  const LANE_MARK = {'对抗路': '抗', '打野': '野', '中路': '中', '发育路': '发', '游走': '游'};
  const laneMark = (lane) => LANE_MARK[lane] || (lane ? String(lane).slice(0, 1) : '·');

  /* 认领位：名字右边唯一入口。未认领是一个很轻的「+ 认领」；
     已认领不重复写 ID 名（名字本身就是 ID 名），改写这个人的营地昵称，几个号就写 +N。 */
  function paClaimChip(board, p) {
    if (p.bound && p.memberId) {
      const nicks = (p.nicknames || []).filter(Boolean);
      const label = nicks.length ? nicks[0] : '已认领';
      const more = nicks.length > 1 ? ` +${nicks.length - 1}` : '';
      const tip = nicks.length ? `营地昵称：${nicks.join(' · ')}` : '已认领到选手ID';
      return `<span class="rs-claim is-done" title="${esc(tip)}">${esc(label)}${more}</span>`;
    }
    return `<span class="rs-claim" role="button" tabindex="0" data-pa-claim="${esc(p.name)}" title="把「${esc(p.name)}」认到一名选手ID 上">认领</span>`;
  }

  /* 卡内两段：上行「位置 + 名字 + 认领」，下行三个等宽读数。
     读数固定为胜率 / KDA / 局数，不跟着排序变 —— 卡片换位置时结构不变，扫视才不用重新认。 */
  function paCard(board, p) {
    const thin = (p.games || 0) < 2;
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const lane = p.lane || '位置未记录';
    const nicks = (p.nicknames || []).filter(Boolean);
    const who = nicks.length && nicks[0] !== p.name ? `${p.name}（营地昵称 ${nicks.join(' / ')}）` : p.name;
    const tip = `${who} · ${lane} · ${p.side === 'own' ? '本队' : '对手'}${p.bound ? '' : ' · 待认领'}${p.sliced ? ' · 切片：' + paSliceLabel() : ''} · 打开个人页`;
    const cell = (value, key) => `<span><b>${value}</b><small>${key}</small></span>`;
    return `<a class="rs-card${thin ? ' is-thin' : ''}" href="${esc(paDetailHref(p.name))}" title="${esc(tip)}">
      <span class="rs-card-top">
        <span class="rs-pos" data-side="${esc(p.side)}" title="${esc(lane)}" aria-hidden="true">${esc(laneMark(p.lane))}</span>
        <b class="rs-card-name">${esc(p.name)}</b>
        ${paClaimChip(board, p)}
      </span>
      <span class="rs-card-metrics">
        ${cell(thin ? '—' : pct0(p.winRate), '胜率')}
        ${cell(thin ? '—' : num(p.kda, 2), 'KDA')}
        ${cell(fmt(p.games), '局')}
      </span>
    </a>`;
  }

  /* 分两段：能跨局看的在前，只出场过 1 局的在后。
     两段各自内部完全同构，段头把「为什么分开」写清楚，读者不会以为漏了内容。 */
  const PA_STABLE_CAP = 24, PA_ROOKIE_PAGE = 36;
  function paLayout(board) {
    const all = paRows(board);
    const stable = all.filter((p) => (p.games || 0) >= 2);
    const rookie = all.filter((p) => (p.games || 0) < 2);
    const pages = Math.max(1, Math.ceil(rookie.length / PA_ROOKIE_PAGE));
    const page = Math.min(Math.max(1, Number(st.pa.page) || 1), pages);
    st.pa.page = page;
    const start = (page - 1) * PA_ROOKIE_PAGE;
    return {
      all, stable: stable.slice(0, PA_STABLE_CAP), stableTotal: stable.length,
      rookie: rookie.slice(start, start + PA_ROOKIE_PAGE), rookieTotal: rookie.length,
      pages, page, start,
    };
  }

  /* 只出场过 1 局的号：一行一个名字，做成名录。
     860 个号如果一人一张 72px 的卡，会把上面 6 个真正有样本的人彻底淹掉。
     每行不再挂「认领」二字（重复 860 遍就是噪音），悬停这一行才出现。 */
  function paRosterRow(board, p) {
    const tip = `${p.name} · ${p.lane || '位置未记录'} · 只打过 1 局${p.bound ? '' : ' · 待认领'}`;
    return `<a class="rs-roster-item" href="${esc(paDetailHref(p.name))}" title="${esc(tip)}">
      <i class="rs-dot" data-side="${esc(p.side)}" aria-hidden="true"></i>
      <b>${esc(p.name)}</b>
      <small>${esc(p.lane || '位置未记录')} · ${p.side === 'own' ? '本队' : '对手'}</small>
      ${paClaimChip(board, p)}
    </a>`;
  }

  function paGrid(board) {
    const lay = paLayout(board);
    if (!lay.all.length) return empty('没有符合条件的游戏名，换个位置或把局数放宽。');
    const stable = lay.stable.length ? `<section class="rs-sec is-stable">
      <div class="rs-sec-head">
        <h2>能跨局看的<b>${fmt(lay.stableTotal)}</b>${lay.stableTotal > lay.stable.length ? `<i>先显示 ${fmt(lay.stable.length)} 个</i>` : ''}</h2>
        <p>出场 2 局以上，胜率与 KDA 才有比较意义。</p>
      </div>
      <div class="rs-grid">${lay.stable.map((p) => paCard(board, p, st.pa.sort)).join('')}</div>
    </section>` : '';
    const rookie = lay.rookie.length ? `<section class="rs-sec is-rookie">
      <div class="rs-sec-head">
        <h2>只出场过 1 局<b>${fmt(lay.rookieTotal)}</b></h2>
        <p>样本不够，只留名字；认过人以后这些号会自动并到对应选手ID。</p>
      </div>
      <div class="rs-roster">${lay.rookie.map((p) => paRosterRow(board, p)).join('')}</div>
    </section>` : '';
    return stable + rookie;
  }

  /* 列表视图：和网格同一批行，只是排成表。样本不足的行数字写「—」，不用 1 局算 100%。 */
  function paList(board) {
    const lay = paLayout(board);
    if (!lay.all.length) return empty('没有符合条件的游戏名，换个位置或把局数放宽。');
    const rows = [...lay.stable, ...lay.rookie];
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const picked = st.pa.picked || [];
    const row = (p) => {
      const thin = (p.games || 0) < 2;
      const val = (v, digits) => (thin ? '—' : num(v, digits));
      return `<div class="rs-row${thin ? ' is-thin' : ''}" data-pa-goto="${esc(p.name)}">
      <input type="checkbox" class="rs-check" data-pa-check="${esc(p.name)}" ${picked.includes(p.name) ? 'checked' : ''} aria-label="选择 ${esc(p.name)} 参与对比">
      <a class="rs-row-name" href="${esc(paDetailHref(p.name))}"><i>${esc(laneMark(p.lane))}</i><b>${esc(p.name)}</b>${paClaimChip(board, p)}</a>
      <span>${p.side === 'own' ? '本队' : '对手'}</span>
      <span>${esc(p.lane || '—')}</span>
      <span>${fmt(p.games)}</span>
      <span>${thin ? '—' : pct0(p.winRate)}</span>
      <span>${val(p.kda, 2)}</span>
      <span>${thin ? '—' : fmt(p.mvp)}</span>
      <span>${thin ? '—' : pct0(p.participation)}</span>
      <span>${thin ? '—' : pct0(p.damageShare)}</span>
      <span>${val(p.score, 1)}</span>
    </div>`;
    };
    return `<div class="rs-list"><div class="rs-row is-head"><span></span><span>游戏名</span><span>阵营</span><span>位置</span><span>局数</span><span>胜率</span><span>KDA</span><span>MVP</span><span>参团</span><span>输出</span><span>表现分</span></div>${rows.map(row).join('')}</div>`;
  }

  function paBody(board) {
    if (st.pa.mode === 'id') return paIdList(board);
    return st.pa.view === 'list' ? paList(board) : paGrid(board);
  }

  function paPager(board) {
    if (st.pa.mode === 'id') return '';
    const lay = paLayout(board);
    if (!lay.rookieTotal) return '';
    return `<div class="rs-pager">
      <span>第 <b>${fmt(lay.start + 1)}–${fmt(lay.start + lay.rookie.length)}</b> 个 · 共 ${fmt(lay.rookieTotal)} 个</span>
      <span class="rs-pager-btns">
        <button type="button" data-pa-page="prev" ${lay.page <= 1 ? 'disabled' : ''} aria-label="上一页">‹</button>
        <small>${fmt(lay.page)} / ${fmt(lay.pages)}</small>
        <button type="button" data-pa-page="next" ${lay.page >= lay.pages ? 'disabled' : ''} aria-label="下一页">›</button>
      </span></div>`;
  }

  /* 勾选状态常驻筛选条：切到网格视图也能看到选了谁、清空、直接对比。 */
  function paPickedBar() {
    const picked = st.pa.picked || [];
    if (!picked.length) return '';
    return `<span class="rs-picked" aria-live="polite">
      <b>已选 ${picked.length}/2</b>
      <i title="${esc(picked.join(' · '))}">${picked.map((name) => esc(name)).join(' · ')}</i>
      <button type="button" data-pa-clear-picked>清空</button>
      <button type="button" data-pa-compare-picked ${picked.length === 2 ? '' : 'disabled'}>对比 →</button>
    </span>`;
  }

  /* 顶部看点：四个数字，和下面的选手卡同一套盒子（白底 + 发丝边框），
     只是更薄。放在裸背景上的四根数字，会和卡片区打架 —— 这正是「有的有卡有的没有」。 */
  function paHighlights(board) {
    const pool = paRows(board).filter((p) => (p.games || 0) >= 5);
    if (pool.length < 3) return '';
    const best = (key) => [...pool].filter((p) => typeof p[key] === 'number').sort((a, b) => b[key] - a[key])[0];
    const kda = best('kda'), dmg = best('damageShare'), wr = best('winRate');
    const mvp = [...pool].sort((a, b) => (b.mvp || 0) - (a.mvp || 0))[0];
    const cells = [
      kda && ['KDA 最高', num(kda.kda, 2), '', kda],
      mvp && mvp.mvp ? ['MVP 最多', fmt(mvp.mvp), '次', mvp] : null,
      dmg && ['输出占比', pct(dmg.damageShare), '', dmg],
      wr && ['胜率最高', pct(wr.winRate), '', wr],
    ].filter(Boolean);
    if (!cells.length) return '';
    return cells.map(([label, value, unit, p]) => `<div class="rs-hl">
      <span class="rs-hl-label">${esc(label)}</span>
      <span class="rs-hl-fig"><b>${value}${unit ? `<i>${esc(unit)}</i>` : ''}</b></span>
      <small class="rs-hl-who" title="${esc(p.name)} · ${fmt(p.games)} 局">${esc(p.name)} · ${fmt(p.games)} 局</small>
    </div>`).join('');
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

  /* 认领进度：整页的核心状态只讲一次，放在报头右侧。
     不用圆环 —— 0/866 的空环看起来像组件坏了；一条 0% 的横条本身就是「还没开始」。 */
  function rsProgress(percent, bound, total) {
    const shown = percent > 0 && percent < 1 ? fmt(percent, 1) : fmt(percent, 0);
    /* 认了 1 个号就是 0.x%：给一条最小可见宽度，否则看起来像没开始。 */
    const raw = Math.max(0, Math.min(100, percent));
    const width = (raw > 0 ? Math.max(raw, 0.7) : 0).toFixed(1);
    return `<div class="rs-progress" data-pa-idbar role="img" aria-label="已认领 ${fmt(bound)} / ${fmt(total)} 个游戏名">
      <span class="rs-progress-head"><small>认领进度</small><b>${shown}<i>%</i></b></span>
      <span class="rs-progress-track"><i style="width:${width}%"></i></span>
      <span class="rs-progress-foot">已认领 <b>${fmt(bound)}</b> / ${fmt(total)} 个游戏名</span>
    </div>`;
  }

  /* 一个选手ID一张卡：ID 名 + 战队 + 挂着的游戏名（可解绑）+ 转会 / 离队 / 删除。 */
  function paIdCard(group) {
    const team = group.teamName || (group.teamId ? idTeamName(group.teamId) : '') || '未归队';
    const lane = group.position || group.lane || '位置未填';
    const figures = group.games ? [
      ['局', fmt(group.games)],
      ['胜率', pct(group.winRate)],
      ['KDA', num(group.kda, 2)],
      ['表现分', num(group.score, 1)],
    ] : [];
    /* 一个 ID 下的每个游戏名都单独成一条，可以逐个解绑（认错号、换号、收窄小号范围）。 */
    const chips = [];
    for (const p of group.names) {
      const labels = (p.nicknames || []).filter(Boolean);
      for (const label of (labels.length ? labels : [p.name])) chips.push({label});
    }
    const names = chips.length
      ? chips.map((item) => `<span class="rs-name-chip" title="${esc(item.label)}">
          <b>${esc(item.label)}</b>
          <button type="button" data-pa-unmap="${esc(item.label)}" aria-label="把 ${esc(item.label)} 从这个选手ID解绑" title="解绑这个游戏名（历史对局不变）">×</button>
        </span>`).join('')
      /* 空卡不能只写「还没有」，给一个能点的下一步，右半边才不空。 */
      : `<span class="rs-id-empty">还没有挂游戏名</span>
         <button type="button" class="rs-id-go" data-pa-mode="name" data-pa-pending="1">去「按游戏名」认一个 →</button>`;
    /* 一行一个选手ID：谁 → 挂了哪几个号 → 打成什么样 → 能做什么，四段从左到右。
       以前是一张 430px 的卡塞四块内容，右半边永远空着；铺成一行反而没有空位。 */
    return `<article class="rs-id" data-pa-id-card="${esc(group.id)}">
      <header class="rs-id-head">
        <span class="rs-id-mark" aria-hidden="true">${esc(String(group.name).trim().slice(0, 1) || '?')}</span>
        <span class="rs-id-title">
          <b>${esc(group.name)}</b>
          <small>${esc(team)} · ${esc(lane)} · ${fmt(group.nameCount)} 个游戏名</small>
        </span>
      </header>
      <div class="rs-id-names">${names}</div>
      <span class="rs-id-figs">${figures.map(([k, v]) => `<span><b>${v}</b><small>${k}</small></span>`).join('')}</span>
      <footer class="rs-id-foot">
        <button type="button" data-pa-id-edit="${esc(group.id)}">编辑 / 转会</button>
        <button type="button" data-pa-id-leave="${esc(group.id)}" ${group.teamId ? '' : 'disabled'}>移出战队</button>
        <button type="button" class="is-danger" data-pa-id-delete="${esc(group.id)}" data-id-name="${esc(group.name)}">删除选手ID</button>
      </footer>
    </article>`;
  }

  function paIdList(board) {
    const all = idGroups(board);
    const q = st.pa.q.trim().toLowerCase();
    let groups = all;
    if (st.pa.side) groups = groups.filter((g) => g.side === st.pa.side);
    if (st.pa.claim === 'bound') groups = groups.filter((g) => g.names.length);
    if (st.pa.claim === 'unbound') groups = groups.filter((g) => !g.names.length);
    if (q) groups = groups.filter((g) => String(g.name).toLowerCase().includes(q)
      || g.names.some((p) => String(p.name).toLowerCase().includes(q)));
    if (!groups.length) {
      /* 一个 ID 都还没有：别给一张白页，直接把出场最多的待认领游戏名摆出来，就地开始。 */
      if (!all.length) {
        /* 一个 ID 都还没有：别给一张白页。把出场最多的待认领号按「局数」排出来，
           行宽撑满、局数靠右，一眼就知道先认谁。 */
        const pending = (board.players || []).filter((p) => !p.memberId)
          .sort((a, b) => (b.games || 0) - (a.games || 0)).slice(0, 10);
        const list = pending.map((p) => `<a class="rs-pick" href="${esc(paDetailHref(p.name))}"
            title="${esc(p.name)} · ${esc(p.lane || '位置未记录')} · ${fmt(p.games)} 局 · 打开个人页">
            <span class="rs-pos" data-side="${esc(p.side)}" aria-hidden="true">${esc(laneMark(p.lane))}</span>
            <span class="rs-pick-name"><b>${esc(p.name)}</b>
              <small>${esc(p.lane || '位置未记录')} · ${p.side === 'own' ? '本队' : '对手'}</small></span>
            <span class="rs-pick-fig"><b>${fmt(p.games)}</b><small>局</small></span>
            ${paClaimChip(board, p)}
          </a>`).join('');
        return `<section class="rs-sec is-guide">
          <div class="rs-sec-head">
            <h2>还没有选手ID</h2>
            <p>先在上方建一个 ID（真名 + 战队），再从下面这几个出场最多的号认过去；认错随时可以解绑。</p>
          </div>
          <div class="rs-picks">${list || empty('还没有营地记录，先去「采集」拉一场。')}</div>
        </section>`;
      }
      return empty('没有符合条件的选手ID，换个关键词或筛选。');
    }
    return `<div class="rs-ids">${groups.map(paIdCard).join('')}</div>`;
  }

  /* 档案页：深色封面板 + 一排控件 + 两段卡片。
     这个页面要回答的只有两件事 —— 谁是谁（认领）、这个人打成什么样（表现）；
     所以报头只放一句结论 + 一个进度环 + 四个事实，其余全让给名单本身。 */
  function archivePage(board, identity) {
    st.board = board;
    st.ids = identity || {players: [], teams: []};
    paReadHash();
    /* 没指定看哪种就按数据决定：有选手ID 先看 ID，一个都没有就直接看游戏名。 */
    if (!st.pa.mode) st.pa.mode = idRoster().length ? 'id' : 'name';
    /* 切片指向的目标可能已经不在本轮数据里（换对手、删训练日），落到「全部对局」。 */
    if (st.pa.slice) {
      const [kind, value] = splitSlice(st.pa.slice);
      const alive = kind === 'opp' ? (board.opponents || []).some((o) => o.name === value)
        : kind === 'day' ? (board.days || []).includes(value) : false;
      if (!alive) st.pa.slice = '';
    }
    const sum = board.summary || {};
    const players = board.players || [];
    const total = players.length;
    const own = players.filter((p) => p.side === 'own').length;
    const enemy = total - own;
    const bound = players.filter((p) => p.memberId).length;
    const ready = players.filter((p) => (p.games || 0) >= 2).length;
    const ids = idGroups(board);
    const onId = st.pa.mode === 'id';
    const percent = total ? bound / total * 100 : 0;

    /* 标题只讲一句结论：数字最大，结论第二，其余全灰 —— 三层就够，不要再加第四层。 */
    const headline = !bound
      ? `<b>${fmt(total)}</b><em>个游戏名，</em><strong>一个都还没认领</strong>`
      : bound >= total
        ? `<b>${fmt(total)}</b><strong>个游戏名全部认完</strong>`
        : `<b>${fmt(bound)}</b><em>个游戏名已认领，</em><strong>还剩 ${fmt(total - bound)} 个待认</strong>`;

    const hero = `<header class="rs-hero">
      <div class="rs-hero-top">
        <span class="rs-eyebrow">选手档案 · ROSTER</span>
        <span class="rs-modes" role="group" aria-label="按什么看">
          <button type="button" data-pa-mode="id" class="${onId ? 'is-active' : ''}" aria-pressed="${onId}">按选手ID</button>
          <button type="button" data-pa-mode="name" class="${onId ? '' : 'is-active'}" aria-pressed="${!onId}">按游戏名</button>
        </span>
        <button type="button" class="rs-ghost" data-pa-add-player>＋ 新建选手ID</button>
        <button type="button" class="rs-ghost is-icon" data-action="refresh" title="刷新数据" aria-label="刷新数据">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.4 8a5.4 5.4 0 1 1-1.7-3.9"/><path d="M13.6 2.2v3.4h-3.4"/></svg>
        </button>
      </div>
      <div class="rs-hero-main">
        <div class="rs-hero-copy">
          <h1>${headline}</h1>
          <p>本队 <b>${fmt(own)}</b> 个昵称、对手 <b>${fmt(enemy)}</b> 个，来自 <b>${fmt(sum.games || 0)}</b> 局训练赛。认出同一个人的几个号就并成一个选手ID，打完的局不改。</p>
        </div>
        ${rsProgress(percent, bound, total)}
      </div>
      <dl class="rs-facts">
        <div><dt>选手ID</dt><dd>${fmt(ids.length)}</dd></div>
        <div><dt>能跨局比较</dt><dd>${fmt(ready)}</dd></div>
        <div><dt>训练日</dt><dd>${fmt((board.days || []).length)}</dd></div>
        <div><dt>对手战队</dt><dd>${fmt((board.opponents || []).length)}</dd></div>
      </dl>
    </header>`;

    const seg = [['', '全部'], ['own', '本队'], ['enemy', '对手']].map(([v, t]) =>
      `<button type="button" data-pa-side="${v}" class="${st.pa.side === v ? 'is-active' : ''}" aria-pressed="${st.pa.side === v}">${t}</button>`).join('');

    const sliceInner = `<option value="" ${st.pa.slice ? '' : 'selected'}>全部对局</option>`
      + ((board.opponents || []).length ? `<optgroup label="按对手">${(board.opponents || []).map((o) => `<option value="opp:${esc(o.name)}" ${st.pa.slice === 'opp:' + o.name ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</optgroup>` : '')
      + ((board.days || []).length ? `<optgroup label="按训练日">${(board.days || []).map((d) => `<option value="day:${esc(d)}" ${st.pa.slice === 'day:' + d ? 'selected' : ''}>${esc(d)}</option>`).join('')}</optgroup>` : '');

    const searchIcon = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.4"/><path d="m10.4 10.4 3.4 3.4"/></svg>`;
    const gridIcon = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="1.6" y="1.6" width="5" height="5" rx="1.2"/><rect x="9.4" y="1.6" width="5" height="5" rx="1.2"/><rect x="1.6" y="9.4" width="5" height="5" rx="1.2"/><rect x="9.4" y="9.4" width="5" height="5" rx="1.2"/></svg>`;
    const listIcon = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M2.4 4.2h11.2M2.4 8h11.2M2.4 11.8h11.2"/></svg>`;
    const exportIcon = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2v7.4m0 0 2.9-2.9M8 9.6 5.1 6.7"/><path d="M2.4 12.4v1.2h11.2v-1.2"/></svg>`;

    /* 工具条分三组：找谁（搜索）→ 圈范围（阵营/位置/对局）→ 怎么排（排序/下限）。
       组间一条竖线 + 更大的间距，比九个控件等距排一排更容易读。 */
    const nameBar = `<div class="rs-bar" data-pa-bar>
      <label class="rs-search">${searchIcon}
        <input data-pa-search value="${esc(st.pa.q)}" placeholder="搜游戏名，如：信则有" autocomplete="off" spellcheck="false" aria-label="搜索游戏名">
      </label>
      <div class="rs-set">
        <div class="rs-seg" role="group" aria-label="阵营">${seg}</div>
        <select data-pa-filter="lane" aria-label="位置">
          <option value="">全部位置</option>${LANES.map((x) => `<option value="${esc(x)}" ${st.pa.lane === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}
        </select>
        <select data-pa-filter="slice" aria-label="范围" class="is-wide">${sliceInner}</select>
      </div>
      <span class="rs-div" aria-hidden="true"></span>
      <div class="rs-set">
        <select data-pa-filter="sort" aria-label="排序">${PA_SORTS.map(([key, label]) => `<option value="${key}" ${st.pa.sort === key ? 'selected' : ''}>按${esc(label)}排</option>`).join('')}</select>
        <select data-pa-filter="min" aria-label="局数下限">
          <option value="1" ${Number(st.pa.min) === 1 ? 'selected' : ''}>全部局数</option>
          <option value="2" ${Number(st.pa.min) === 2 ? 'selected' : ''}>至少 2 局</option>
          <option value="6" ${Number(st.pa.min) === 6 ? 'selected' : ''}>至少 6 局</option>
        </select>
        <button type="button" class="rs-pill${st.pa.claim === 'unbound' ? ' is-on' : ''}" data-pa-filter-claim="${st.pa.claim === 'unbound' ? '' : 'unbound'}" aria-pressed="${st.pa.claim === 'unbound'}">只看待认领</button>
      </div>
      <span class="rs-tools">
        <span data-pa-picked>${paPickedBar()}</span>
        <span class="rs-count" data-pa-count>${fmt(paRows(board).length)} 个游戏名</span>
        <div class="rs-view" role="group" aria-label="展示方式">
          <button type="button" data-pa-view="grid" class="${st.pa.view === 'grid' ? 'is-active' : ''}" aria-pressed="${st.pa.view === 'grid'}" title="网格">${gridIcon}</button>
          <button type="button" data-pa-view="list" class="${st.pa.view === 'list' ? 'is-active' : ''}" aria-pressed="${st.pa.view === 'list'}" title="列表">${listIcon}</button>
        </div>
        <button type="button" class="rs-icon" data-pa-export title="导出 CSV" aria-label="导出 CSV">${exportIcon}</button>
      </span>
    </div>`;

    const idBar = `<div class="rs-bar is-id" data-pa-bar>
      <label class="rs-search">${searchIcon}
        <input data-pa-search value="${esc(st.pa.q)}" placeholder="搜选手ID 或游戏名" autocomplete="off" spellcheck="false" aria-label="搜索选手ID或游戏名">
      </label>
      <div class="rs-set">
        <div class="rs-seg" role="group" aria-label="阵营">${seg}</div>
        <select data-pa-filter="claim" aria-label="挂名">
          <option value="" ${st.pa.claim ? '' : 'selected'}>全部选手ID</option>
          <option value="bound" ${st.pa.claim === 'bound' ? 'selected' : ''}>已挂游戏名</option>
          <option value="unbound" ${st.pa.claim === 'unbound' ? 'selected' : ''}>还没挂游戏名</option>
        </select>
      </div>
      <span class="rs-tools">
        <span class="rs-count" data-pa-count>${fmt(ids.length)} 个选手ID</span>
        <button type="button" class="rs-cta" data-pa-add-player>新建选手ID</button>
      </span>
    </div>`;

    const highlights = onId ? '' : paHighlights(board);
    return `<div class="page hero-detail-page page-wide" data-pl-page="archive">
      ${hero}
      <div class="rs-hls" data-pa-highlights ${highlights ? '' : 'hidden'}>${highlights}</div>
      <div data-pa-bar>${onId ? idBar : nameBar}</div>
      <div data-pa-body>${paBody(board)}</div>
      <div data-pa-pager>${paPager(board)}</div>
      <p class="rs-note">游戏名是营地昵称，选手ID 是你起的真名。改名、转会、解绑只改当前归属，已经打完的局不改；胜率只以有胜负的局为分母。</p>
    </div>`;
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

  /* 具体实现拆到 player-detail.js：五块纵向模块，全部按实际分路统计。
     单人详情的时间窗口状态与详情载荷都存在 st.pd 里，切换周期时只重画这一页，
     不重新请求接口，也不改变其他页面的筛选。 */
  function soloPage(board, name, detail) {
    st.pd = {...(st.pd || {}), board, name, detail};
    return detailPage.render(board, name, detail);
  }

  /* ── 交互 ─────────────────────────────────────────────────────── */
  function pageRoot() {
    return document.querySelector('[data-pl-page]');
  }
  function refreshArchive() {
    const board = st.board, root = pageRoot();
    if (!board || !root) return;
    const body = root.querySelector('[data-pa-body]');
    if (body) body.innerHTML = paBody(board);
    const pager = root.querySelector('[data-pa-pager]');
    if (pager) pager.innerHTML = paPager(board);
    const hls = root.querySelector('[data-pa-highlights]');
    if (hls) {
      const html = st.pa.mode === 'id' ? '' : paHighlights(board);
      hls.innerHTML = html;
      hls.hidden = !html;
    }
    const count = root.querySelector('[data-pa-count]');
    if (count) count.textContent = st.pa.mode === 'id'
      ? `${fmt(idGroups(board).length)} 个选手ID`
      : `${fmt(paRows(board).length)} 个游戏名`;
    const picked = root.querySelector('[data-pa-picked]');
    if (picked) picked.innerHTML = paPickedBar();
    /* 进度环跟着认领结果变：认完一个不用整页重画。 */
    const ring = root.querySelector('[data-pa-idbar]');
    if (ring) {
      const players = board.players || [];
      const bound = players.filter((p) => p.memberId).length;
      ring.outerHTML = rsProgress(players.length ? bound / players.length * 100 : 0, bound, players.length);
    }
    root.querySelectorAll('[data-pa-filter]').forEach((el) => {
      const want = String(st.pa[el.dataset.paFilter] ?? '');
      if (el.value !== want) el.value = want;
    });
    root.querySelectorAll('[data-pa-side]').forEach((el) => {
      const on = (el.dataset.paSide || '') === st.pa.side;
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-pressed', String(on));
    });
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
      st.pa[key] = key === 'min' ? (Number(pa.value) || 1) : pa.value;
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    if (event.target.matches('[data-pl-search]')) {
      return true;
    }
    const control = event.target.closest('[data-pl-filter]');
    if (!control) return false;
    const key = control.dataset.plFilter;
    const value = control.value;
    if (key === 'lane') {
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

  /* 认领：把一个营地昵称（游戏名）挂到某支战队的选手ID上。
     - 挂到已有ID → 多个游戏名共用一个ID（小号 / 改名前后）
     - 新建ID     → 起 ID 名、选战队，同时建选手与映射
     本队和对手的号都走这一条；写的是账号映射，已经打完的局不改。 */
  function nameDialog(label, opts = {}) {
    let dialog = document.querySelector('#pl-name-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pl-name-dialog';
      dialog.className = 'nm-dialog';
      document.body.appendChild(dialog);
    }
    const board = st.board || {};
    const player = byName(board, label);
    const games = player ? player.games : 0;
    const accounts = (player && player.accountIds) || [];
    const roster = idRoster();
    const teams = idTeams();
    const preferCreate = opts.prefer === 'create' || !roster.length;
    const teamOptions = teams.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
    const idRow = (info) => `<button type="button" class="nm-id-row" data-nm-pick="${esc(info.id)}" data-nm-name="${esc(info.name)}">
        <i class="nm-id-ava" aria-hidden="true">${esc(String(info.name).trim().slice(0, 1) || '?')}</i>
        <span><b>${esc(info.name)}</b>
        <small>${esc(info.teamName || '未归队')}${info.position ? ' · ' + esc(info.position) : ''}${info.accounts ? ` · 已有 ${fmt(info.accounts)} 个游戏名` : ' · 还没挂游戏名'}</small></span>
      </button>`;
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>认领游戏名</h2><p>「${esc(label)}」出场 ${fmt(games)} 局、涉及 ${fmt(accounts.length)} 个游戏账号。认到一个选手ID后，这些记录并入该 ID；同一个 ID 可以挂多个游戏名。</p></div><button type="button" class="head-button" data-pl-name-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <div class="nm-modes" role="radiogroup" aria-label="认领方式">
          <label class="nm-mode"><input type="radio" name="mode" value="claim" ${preferCreate ? '' : 'checked'} ${roster.length ? '' : 'disabled'}><span><b>挂到已有选手ID</b><small>${roster.length ? `共 ${fmt(roster.length)} 个ID，可搜名字或战队` : '还没有选手ID，先新建一个'}</small></span></label>
          <label class="nm-mode"><input type="radio" name="mode" value="create" ${preferCreate ? 'checked' : ''}><span><b>新建选手ID</b><small>起真名、选战队，同时建 ID 与映射</small></span></label>
        </div>
        <div class="nm-pane" data-nm-pane="claim" ${preferCreate ? 'hidden' : ''}>
          <label>搜索选手ID<input data-nm-search placeholder="名字 / 战队" autocomplete="off"></label>
          <div class="nm-idlist" data-nm-list>${roster.map(idRow).join('') || '<p class="nm-hint">选手ID 还是空的。</p>'}</div>
          <input type="hidden" name="playerId" value="">
          <p class="nm-hint">同一个游戏名只能属于一个 ID；认错可以在选手ID卡上解绑。</p>
        </div>
        <div class="nm-pane" data-nm-pane="create" ${preferCreate ? '' : 'hidden'}>
          <div class="date-fields"><label>选手ID<input name="name" maxlength="40" value="" placeholder="真名，如：陈泽彬" autocomplete="off"></label>
            <label>所属战队<select name="teamId"><option value="">未归队</option>${teamOptions}</select></label></div>
          <fieldset class="sx-pos-field"><legend>位置（可多选，第一个是主位置）</legend><div class="sx-pos-chips">${LANES.map(x => `<label class="sx-pos-chip"><input type="checkbox" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
        </div>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-pl-name-close>取消</button><button class="primary" type="submit">${preferCreate ? '新建并认领' : '确认认领'}</button></div></form>`;
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('.filter-error');
    const submit = form.querySelector('button[type=submit]');
    const picked = form.querySelector('input[name=playerId]');
    const list = form.querySelector('[data-nm-list]');
    const search = form.querySelector('[data-nm-search]');
    const syncMode = () => {
      const mode = form.querySelector('input[name=mode]:checked')?.value || 'create';
      form.querySelectorAll('[data-nm-pane]').forEach((pane) => { pane.hidden = pane.dataset.nmPane !== mode; });
      submit.textContent = mode === 'claim' ? '确认认领' : '新建并认领';
      error.textContent = '';
    };
    form.querySelectorAll('input[name=mode]').forEach((radio) => radio.addEventListener('change', syncMode));
    syncMode();
    if (list) {
      list.addEventListener('click', (event) => {
        const hit = event.target.closest('[data-nm-pick]');
        if (!hit) return;
        picked.value = hit.dataset.nmPick;
        picked.dataset.name = hit.dataset.nmName || '';
        list.querySelectorAll('[data-nm-pick]').forEach((row) => row.classList.toggle('is-picked', row === hit));
      });
      search.addEventListener('input', () => {
        const text = search.value.trim().toLowerCase();
        const found = roster.filter((info) => !text
          || String(info.name).toLowerCase().includes(text)
          || String(info.teamName || '').toLowerCase().includes(text));
        list.innerHTML = found.map(idRow).join('') || '<p class="nm-hint">没有匹配的选手ID。</p>';
        picked.value = '';
        picked.dataset.name = '';
      });
    }
    dialog.querySelectorAll('[data-pl-name-close]').forEach(b => b.addEventListener('click', () => dialog.close()));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const mode = data.get('mode') || 'create';
      const positions = data.getAll('position').map((value) => String(value || '')).filter(Boolean);
      let payloads;
      if (mode === 'claim') {
        const playerId = String(picked.value || '');
        if (!playerId) { error.textContent = '先在列表里点一个选手ID。'; return; }
        const name = picked.dataset.name || '';
        payloads = accounts.map((accountId) => ({accountId, playerId, name, position: ''}));
      } else {
        const name = String(data.get('name') || '').trim();
        if (!name) { error.textContent = '请填写选手ID。'; return; }
        payloads = accounts.map((accountId) => ({accountId, name, positions, position: positions[0] || '',
          teamId: data.get('teamId') || ''}));
      }
      /* 没有账号ID的老记录：退回按昵称提交，后端只会在本队侧找账号。 */
      if (!payloads.length) {
        const fallback = mode === 'claim'
          ? {label, playerId: picked.value, name: picked.dataset.name || ''}
          : {label, name: data.get('name'), positions, position: positions[0] || '', teamId: data.get('teamId') || ''};
        payloads = [fallback];
      }
      submit.disabled = true;
      postEach('/api/v3/identity/name', payloads)
        .then(() => { dialog.close(); if (reload) reload(); })
        .catch((err) => { submit.disabled = false; error.textContent = err.message; });
    });
    dialog.showModal();
  }

  /* 新建选手ID：只建 ID（可以暂不挂游戏名）。之后在「按游戏名」把营地昵称认过来。 */
  function addPlayerDialog() {
    let dialog = document.querySelector('#pl-add-player-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pl-add-player-dialog';
      dialog.className = 'nm-dialog';
      document.body.appendChild(dialog);
    }
    const teams = idTeams();
    const teamOptions = teams.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join('');
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>新建选手ID</h2><p>选手ID 是你起的真名（如「小义」），一个 ID 之后可以挂多个游戏名。只建 ID、不挂号也可以。</p></div><button type="button" class="head-button" data-add-player-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <div class="date-fields"><label>选手ID<input name="name" required maxlength="40" placeholder="例如：小义"></label>
          <label>所属战队<select name="team"><option value="">未归队</option>${teamOptions}</select></label></div>
        <fieldset class="sx-pos-field"><legend>位置</legend><div class="sx-pos-chips">${LANES.map(x => `<label class="sx-pos-chip"><input type="radio" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
        <p class="nm-hint">战队下拉来自战队主数据；新战队请先到「赛训 → 数据准备」建档，或直接在认领时新建。</p>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-add-player-close>取消</button><button class="primary" type="submit">建 ID</button></div></form>`;
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('.filter-error');
    const submit = form.querySelector('button[type=submit]');
    dialog.querySelectorAll('[data-add-player-close]').forEach(b => b.addEventListener('click', () => dialog.close()));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const name = String(data.get('name') || '').trim();
      if (!name) { error.textContent = '请填写选手ID。'; return; }
      submit.disabled = true;
      postJson('/api/v3/identity/players', {name, position: data.get('position') || '', team: data.get('team') || ''})
        .then(() => { dialog.close(); if (reload) reload(); })
        .catch((err) => { submit.disabled = false; error.textContent = err.message; });
    });
    dialog.showModal();
  }

  /* ── 身份写操作：都只改「当前挂谁名下」，历史对局不动 ───────────── */
  /* 串行提交：认领 / 解绑要一个账号一个账号写，避免并发触发同一行的写锁。 */
  function postJson(url, payload) {
    return fetch(`${API_BASE}${url}`, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)}).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || '保存失败');
      return body;
    });
  }
  async function postEach(url, payloads) {
    for (const payload of payloads) await postJson(url, payload);
  }

  /* 解绑一个游戏名：只断映射，历史局与统计不改。
     按昵称去账号表里找 accountId —— 一个昵称可能对应多个账号（换号/多端），一起解。 */
  async function unmapIdentity(nickname) {
    let rows = [];
    try {
      const res = await fetch(`${API_BASE}/api/v3/identity/accounts?q=${encodeURIComponent(nickname)}`).then((r) => r.json());
      rows = (res.rows || []).filter((row) => row.nickname === nickname && row.accountId);
    } catch (err) {
      window.alert('读取账号失败：' + err.message);
      return;
    }
    if (!rows.length) { window.alert(`「${nickname}」没有可解绑的游戏账号。`); return; }
    if (!window.confirm(`把「${nickname}」从当前选手ID上解绑？\n它的 ${rows.length} 个游戏账号会回到「待认领」，已经打完的局不变。`)) return;
    postEach('/api/v3/identity/accounts/unmap', rows.map((row) => ({accountId: row.accountId})))
      .then(() => { if (reload) reload(); })
      .catch((err) => window.alert(err.message));
  }

  /* 编辑选手ID：改名、改位置、换战队（转会）。历史不变，只改当前归属。 */
  function editIdentity(playerId) {
    const info = idInfo(playerId) || {};
    let dialog = document.querySelector('#pl-edit-id-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pl-edit-id-dialog';
      dialog.className = 'nm-dialog';
      document.body.appendChild(dialog);
    }
    const teams = idTeams();
    const teamOptions = teams.map((t) => `<option value="${esc(t.id)}" ${t.id === info.teamId ? 'selected' : ''}>${esc(t.name)}</option>`).join('');
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>编辑选手ID</h2><p>改名、换战队（转会）、改位置都只改「现在归谁」；已经打完的局仍按当时的对手与阵容记录。</p></div><button type="button" class="head-button" data-edit-id-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <div class="date-fields"><label>选手ID<input name="name" required maxlength="40" value="${esc(info.name || '')}"></label>
          <label>位置<select name="position"><option value="">待确认</option>${LANES.map((x) => `<option value="${x}" ${info.position === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label></div>
        <label>所属战队<select name="teamId"><option value="">未归队</option>${teamOptions}</select></label>
        <p class="nm-hint">换战队不影响历史：换队之前的对局仍记在原对手名下，换队之后的新对局按新战队统计。</p>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-edit-id-close>取消</button><button class="primary" type="submit">保存</button></div></form>`;
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('.filter-error');
    const submit = form.querySelector('button[type=submit]');
    dialog.querySelectorAll('[data-edit-id-close]').forEach((b) => b.addEventListener('click', () => dialog.close()));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const name = String(data.get('name') || '').trim();
      if (!name) { error.textContent = '请填写选手ID。'; return; }
      submit.disabled = true;
      postJson('/api/v3/identity/players', {id: playerId, name, position: data.get('position') || '', team: '', teamId: data.get('teamId') || ''})
        .then(() => { dialog.close(); if (reload) reload(); })
        .catch((err) => { submit.disabled = false; error.textContent = err.message; });
    });
    dialog.showModal();
  }

  function leaveIdentity(playerId) {
    const info = idInfo(playerId) || {};
    if (!window.confirm(`把「${info.name || '这个选手ID'}」移出${info.teamName || '当前战队'}？\n选手ID 和它的游戏名都保留，只是不再属于任何战队；历史对局不变。`)) return;
    postJson('/api/v3/identity/players', {id: playerId, name: info.name || '', position: info.position || '', teamId: ''})
      .then(() => { if (reload) reload(); })
      .catch((err) => window.alert(err.message));
  }

  function deleteIdentity(playerId, name) {
    if (!window.confirm(`删除选手ID「${name}」？\n它挂着的游戏名会回到「待认领」，已经打完的局不变。`)) return;
    postJson('/api/v3/identity/players/delete', {playerId})
      .then(() => { if (reload) reload(); })
      .catch((err) => window.alert(err.message));
  }

  function click(event) {
    /* 单人详情：周期口径切换（近 3 / 近 5 个训练日 / 本周 vs 上周同期）。
       只换「逐局表现与周期趋势」模块里的卡片，保留页面外壳、锚点导航和其他模块；
       详情载荷已在 st.pd 里，不再请求接口。 */
    const pdWindow = event.target.closest('[data-pd-window]');
    if (pdWindow) {
      const mode = pdWindow.dataset.pdWindow;
      if (st.pd && st.pd.detail && (mode === 'd3' || mode === 'd5' || mode === 'week')) {
        st.pd.mode = mode;
        const root = pageRoot();
        const current = root && root.querySelector('[data-pdx-key="trend"] .pdx-cards');
        if (root && current) {
          const holder = document.createElement('div');
          holder.innerHTML = soloPage(st.pd.board, st.pd.name, st.pd.detail);
          const next = holder.querySelector('[data-pdx-key="trend"] .pdx-cards');
          if (next) {
            current.innerHTML = next.innerHTML;
            root.querySelector(`[data-pd-window="${mode}"]`)?.focus({preventScroll: true});
          }
        } else if (root) {
          const scroll = window.scrollY;
          root.outerHTML = soloPage(st.pd.board, st.pd.name, st.pd.detail);
          window.scrollTo(0, scroll);
        }
      }
      return true;
    }
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
    /* 档案卡上的「认领」：卡片本身是链接，先拦下来再开对话框。 */
    const claimBtn = event.target.closest('[data-pa-claim]');
    if (claimBtn) {
      event.preventDefault();
      event.stopPropagation();
      nameDialog(claimBtn.dataset.paClaim);
      return true;
    }
    /* 按选手ID / 按游戏名：换视图整页重画（两套筛选条不同）。 */
    const modeBtn = event.target.closest('[data-pa-mode]');
    if (modeBtn) {
      const mode = modeBtn.dataset.paMode === 'name' ? 'name' : 'id';
      const wantPending = modeBtn.dataset.paPending === '1';
      if (mode !== st.pa.mode || wantPending) {
        st.pa.mode = mode;
        if (wantPending) st.pa.claim = 'unbound';
        st.pa.page = 1;
        const root = pageRoot();
        const board = st.board;
        if (root && board) {
          const scroll = window.scrollY;
          /* 先写 URL 再重画：archivePage 会重新读一遍 hash，
             如果这时候 hash 里还是旧的 mode=name，切到 ID 会被立刻读回去。 */
          paWriteHash();
          root.outerHTML = archivePage(board, st.ids);
          window.scrollTo(0, scroll);
          paWriteHash();
        }
      }
      return true;
    }
    const unmapBtn = event.target.closest('[data-pa-unmap]');
    if (unmapBtn) { unmapIdentity(unmapBtn.dataset.paUnmap); return true; }
    const editId = event.target.closest('[data-pa-id-edit]');
    if (editId) { editIdentity(editId.dataset.paIdEdit); return true; }
    const leaveId = event.target.closest('[data-pa-id-leave]');
    if (leaveId) { leaveIdentity(leaveId.dataset.paIdLeave); return true; }
    const deleteId = event.target.closest('[data-pa-id-delete]');
    if (deleteId) { deleteIdentity(deleteId.dataset.paIdDelete, deleteId.dataset.idName); return true; }
    /* 阵营用分段按钮，不用下拉：三个选项就那三个，下拉要多点一次。 */
    const sideBtn = event.target.closest('[data-pa-side]');
    if (sideBtn) {
      st.pa.side = sideBtn.dataset.paSide || '';
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    const claimFilter = event.target.closest('[data-pa-filter-claim]');
    if (claimFilter) {
      st.pa.claim = claimFilter.dataset.paFilterClaim || '';
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    if (event.target.closest('[data-pa-add-player]')) { addPlayerDialog(); return true; }
    /* 任何进单人详情的链接先记下来源页，详情页的「返回」按来源走，
       hash 原样带上，筛选与翻页都能还原。 */
    const detailLink = event.target.closest('a[href^="#playerdetail/"]');
    if (detailLink) {
      const page = document.querySelector('[data-pl-page]');
      const source = page && page.dataset.plPage;
      const labels = {archive: '选手档案', lane: '选手与位置', playercompare: '选手对比', solo: '选手详情'};
      if (source && labels[source]) {
        st.returnTo = {href: location.hash || ('#' + source), label: labels[source]};
      }
      return false;
    }
    const name = event.target.closest('[data-pl-name]');
    if (name) { nameDialog(name.dataset.plName, {prefer: 'create'}); return true; }
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
  return {archivePage, lanePage, comparePage, soloPage, change, click};
}
