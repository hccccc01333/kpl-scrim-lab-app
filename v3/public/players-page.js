/* 选手板块三页 —— 选手档案 / 选手对比 / 单人详情
   单人详情实现已拆到 player-detail.js，本文件保留共用工具与交互。
   同一份数据源：/api/v3/players-board（营地十人面板逐人逐局记录）。
   视觉语言沿用英雄页 / BP 页：深墨报头 + KPI 条 + 结论句 + 筛选条 +
   锚点导航 + 一块一行。所有分位都在同位置内部计算，不跨位置比较。
   单人详情不另开接口：名单、对局、搭档都从同一份 board 里算。
   选手档案照 KPL 赛研的选手卡：头像 + 名字/位置 + 一个大指标 + 一行战绩摘要。
   认领与命名就在档案页完成（卡片名字旁、顶部身份条），不再单设名单页与认领页。 */

import {createPlayerDetail} from './player-detail.js?v=20261126allplayers';
import {createProfileUI} from './player-profile-ui.js';
import { glyph } from './ui-icons.js';

export function createPlayers(h) {
  const {esc, fmt, pct, diff, portrait, block, empty, reload} = h;
  const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
  const text = (x) => esc(x ?? '—');
  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  const clamp = (v) => Math.max(0, Math.min(100, typeof v === 'number' && Number.isFinite(v) ? v : 0));
  const num = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? fmt(v, d) : '—');
  const mono = (name) => `<span class="pl-ava">${esc(String(name || '?').trim().slice(0, 1) || '?')}</span>`;
  const resCls = (r) => r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : 'is-none';
  const resWord = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '—';
  const tone = (t) => t === 'up' ? '上升' : t === 'down' ? '下滑' : '持平';
  const toneArrow = (t) => t === 'up' ? '↑' : t === 'down' ? '↓' : '→';
  const st = {a: '', b: '', board: null, ids: null,
    /* 选手档案页的筛选状态；默认按出场排，避免 1 局的高 KDA 霸榜。
       mode 留空表示「按数据自动定」：有选手ID 先看 ID，一个都没有就直接看游戏名。 */
    pa: {q: '', side: 'own', team: '', lane: '', sort: 'games', min: 1, claim: '', slice: '', page: 1,
      view: 'grid', mode: '', picked: [], expanded: [],
      /* 主页档案筛选：百段下限 / 巅峰分下限 / 只要千强 / 只要某个实力 / 只要有档案。 */
      segMin: 0, peakMin: 0, top1000: false, strength: '', hasProfile: false},
    /* 最近对比过的选手（对比页快捷入口）。 */
    recent: [],
    /* 对比页的「对路」筛选，空 = 全部位置。 */
    cmpLane: '',
    /* 从哪一页点进单人详情，返回就回哪一页（带上当时的筛选 hash）。 */
    returnTo: null,
    /* 单人详情的时间窗口：默认近 3 个训练日，点周期按钮切换。 */
    pd: {mode: 'd3'},
    /* 选手主页档案（百段 / 巅峰分 / 千强 / 实力），按营地名索引；null = 还没加载。 */
    profiles: null, profileMeta: null};
  /* 主页档案的读写与对话框单独一个模块：卡片上的档案条、详情页的一段、录入弹窗都走它。 */
  const profileUI = createProfileUI({
    esc, fmt, st,
    apiBase: API_BASE,
    refresh: () => {
      const root = pageRoot();
      if (!root) return;
      if (root.dataset.plPage === 'archive') refreshArchive();
      else if (root.dataset.plPage === 'solo' && st.pd && st.pd.name) {
        const scroll = window.scrollY;
        root.outerHTML = soloPage(st.pd.board, st.pd.name, st.pd.detail, st.pd.comboPool);
        window.scrollTo(0, scroll);
      }
    },
  });
  const detailPage = createPlayerDetail({esc, fmt, portrait, block, empty, st, profile: profileUI});
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
  /* 标题下的说明小字已移除；sub 仅保留入参兼容调用方。 */
  const masthead = (title, sub, kpiHtml, extra = '') => `<header class="hero-masthead"><div class="page-intro"><div><h1>${glyph('compare', { size: 20 })}${esc(title)}</h1></div><div class="intro-actions">${extra}<button class="control" data-action="refresh">${glyph('refresh', { size: 18 })}刷新数据</button></div></div>${kpiHtml}</header>`;
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
    /* 选了具体对手就只留那支队的人：阵营是「本队 / 对手」这一层，队伍是再下一层。 */
    const teams = state.team ? paTeamsCached(board) : null;
    return (board.players || [])
      .filter((p) => !sliceOn || paSplit(p))
      .filter((p) => !teams || teams.teamOf(p.name).team === state.team)
      .map(paVm)
      /* 认领之后 p.name 是选手ID，营地昵称只剩在 nicknames 里 —— 搜索两个都要认。 */
      .filter((p) => (!q || String(p.name).toLowerCase().includes(q)
        || (p.nicknames || []).some((n) => String(n).toLowerCase().includes(q)))
        && (!state.side || p.side === state.side)
        && (!state.lane || p.lane === state.lane)
        && (!state.claim || (state.claim === 'bound' ? !!p.bound : !p.bound))
        && (p.games || 0) >= state.min)
      /* 主页档案的筛选（百段 / 巅峰分 / 千强 / 实力）：没有档案的号开了任一条件就不显示。 */
      .filter((p) => profileUI.matches(p, state))
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
     team 现在是「选手ID 所属战队」筛选：值为战队名，__none__ 表示未归队；
     slice 是对手 / 训练日合一的切片位，旧链接的 opp / opponent / day 照样能打开。 */
  const PA_HASH_KEYS = ['q', 'side', 'team', 'lane', 'sort', 'min', 'claim', 'view'];
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
    if (st.pa.team) params.set('team', st.pa.team);
    if (st.pa.lane) params.set('lane', st.pa.lane);
    if (st.pa.slice) params.set('slice', st.pa.slice);
    if (st.pa.sort !== 'games') params.set('sort', st.pa.sort);
    if (st.pa.min > 1) params.set('min', String(st.pa.min));
    if (st.pa.claim) params.set('claim', st.pa.claim);
    if (st.pa.view !== 'grid') params.set('view', st.pa.view);
    /* ID 是默认视图，只在「按游戏名」时写，URL 保持最短。 */
    if (st.pa.mode === 'name') params.set('mode', 'name');
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

  /* 选手档案的战队筛选：按选手ID主数据的战队归属过滤，不看对局里临时标了谁。
     战队名优先用 ID 主数据里的 teamId 反查，没挂上的再退回 teamName；
     两者都没有就归到「未归队」。选项从当前名单里长出来，不会留着已删除战队的空项。 */
  const PA_TEAM_NONE = '__none__';
  const teamOf = (group) => (group.teamId && idTeamName(group.teamId)) || group.teamName || '';
  function teamCounts(board) {
    const counts = new Map();
    for (const g of idGroups(board)) {
      const name = teamOf(g) || PA_TEAM_NONE;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]
      || (a[0] === PA_TEAM_NONE ? 1 : b[0] === PA_TEAM_NONE ? -1 : a[0].localeCompare(b[0], 'zh')));
  }
  function teamSelect(board) {
    const options = [`<option value="">全部战队</option>`]
      .concat(teamCounts(board).map(([name, count]) => `<option value="${esc(name)}"${st.pa.team === name ? ' selected' : ''}>${esc(name === PA_TEAM_NONE ? '未归队' : name)} · ${count} 人</option>`));
    return `<label class="arch-team-filter" for="pa-team"><span>战队</span>
      <span class="arch-select is-team"><select id="pa-team" name="team" data-pa-team>${options.join('')}</select></span></label>`;
  }
  function paFilteredGroups(board) {
    let groups = idGroups(board);
    const q = st.pa.q.trim().toLowerCase();
    if (q) groups = groups.filter((g) => String(g.name).toLowerCase().includes(q)
      || g.names.some((p) => String(p.name).toLowerCase().includes(q)));
    if (st.pa.team) {
      groups = st.pa.team === PA_TEAM_NONE
        ? groups.filter((g) => !teamOf(g))
        : groups.filter((g) => teamOf(g) === st.pa.team);
    }
    return groups;
  }

  /* 同一战队的选手 ID 收进一个大战队框；未归队始终放在最后。 */
  function paIdTeams(board) {
    const grouped = Map.groupBy(paFilteredGroups(board), (group) =>
      group.teamId || (group.teamName ? `name:${group.teamName}` : PA_TEAM_NONE));
    return [...grouped].map(([key, groups]) => ({
      key,
      name: teamOf(groups[0]) || PA_TEAM_NONE,
      groups,
    })).toSorted((a, b) => {
      if (a.name === PA_TEAM_NONE || b.name === PA_TEAM_NONE) {
        return a.name === b.name ? 0 : a.name === PA_TEAM_NONE ? 1 : -1;
      }
      return b.groups.length - a.groups.length || a.name.localeCompare(b.name, 'zh');
    });
  }

  /* ── 档案页组件（arch = archive） ─────────────────────────────────
     2026-11-16 整页重做。旧版的问题不在配色，在排版：
       · 内容缩在 1560 的中间，左右两条空边比内容还抢眼；
       · 标签 10–11px、卡片读数 18px，离屏幕一米根本读不出来；
       · 每个区块都是「白底 + 一根发丝边」，没有厚度也没有选中态。
     这一版把横向用满（对齐顶部导航的 1640），字号上两档，卡片做成
     有釉面、有内高光、有两层投影的实物：悬停抬起来，选中描一圈。
     结构也从「一行行往下堆」改成「报头两栏 → 四个最高 → 工具条 →
     三列宽卡 → 名字索引」，每一段都占满整行。 */
  const LANE_MARK = {'对抗路': '抗', '打野': '野', '中路': '中', '发育路': '发', '游走': '游'};
  const laneMark = (lane) => LANE_MARK[lane] || (lane ? String(lane).slice(0, 1) : '·');

  const ICON = {
    refresh: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.4 8a5.4 5.4 0 1 1-1.7-3.9"/><path d="M13.6 2.2v3.4h-3.4"/></svg>',
    search: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.4"/><path d="m10.4 10.4 3.4 3.4"/></svg>',
    grid: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="1.6" y="1.6" width="5" height="5" rx="1.2"/><rect x="9.4" y="1.6" width="5" height="5" rx="1.2"/><rect x="1.6" y="9.4" width="5" height="5" rx="1.2"/><rect x="9.4" y="9.4" width="5" height="5" rx="1.2"/></svg>',
    list: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M2.4 4.2h11.2M2.4 8h11.2M2.4 11.8h11.2"/></svg>',
    export: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2v7.4m0 0 2.9-2.9M8 9.6 5.1 6.7"/><path d="M2.4 12.4v1.2h11.2v-1.2"/></svg>',
  };

  /* 认领位：名字右边唯一入口。未认领是一个很轻的「＋ 认领」；
     已认领不重复写 ID 名（名字本身就是 ID 名），改写这个人的营地昵称，几个号就写 +N。 */
  function paClaimChip(board, p) {
    if (p.bound && p.memberId) {
      const nicks = (p.nicknames || []).filter(Boolean);
      const label = nicks.length ? nicks[0] : '已认领';
      const more = nicks.length > 1 ? ` +${nicks.length - 1}` : '';
      const tip = nicks.length ? `营地昵称：${nicks.join(' · ')}` : '已认领到选手ID';
      return `<span class="arch-claim is-done" title="${esc(tip)}">${esc(label)}${more}</span>`;
    }
    return `<button type="button" class="arch-claim" data-pa-claim="${esc(p.name)}" title="把「${esc(p.name)}」认到一名选手ID 上">${glyph('players', { size: 18 })}认领</button>`;
  }

  /* 近几局的评分走势。四个「最高」卡靠它撑起右半边，
     不然一张 380 宽的卡里只放一个 8.42，剩下全是空气。 */
  const archSparkValues = (p) => (p.recent || []).slice(0, 8).reverse()
    .map((g) => g.rating).filter((v) => typeof v === 'number');
  function archSpark(p, w = 104, h = 34) {
    const values = archSparkValues(p);
    if (values.length < 2) return '';
    const pad = 5;
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = Math.max(1, hi - lo);
    const x = (i) => pad + i * (w - pad * 2) / (values.length - 1);
    const y = (v) => h - pad - (v - lo) / span * (h - pad * 2);
    const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
    const area = `${line} L${x(values.length - 1).toFixed(1)} ${h - pad} L${pad} ${h - pad} Z`;
    const dots = values.map((v, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="1.9"/>`).join('');
    return `<svg class="arch-spark" viewBox="0 0 ${w} ${h}" role="img" aria-label="近 ${values.length} 局评分走势"><path class="arch-spark-area" d="${area}"/><path class="arch-spark-line" d="${line}"/>${dots}</svg>`;
  }

  /* 常用英雄：真实英雄头像，三到四个，撑住卡片右下角。
     没有英雄记录就留一行灰字，卡片结构不跟着样本多少变。 */
  function archHeroes(p, limit = 4) {
    const heroes = (p.heroes || []).filter((x) => x && x.hero).slice(0, limit);
    if (!heroes.length) return '<span class="arch-heroes is-empty">还没有英雄记录</span>';
    return `<span class="arch-heroes">${heroes.map((x) =>
      `<span class="arch-hero" title="${esc(x.hero)} · ${fmt(x.games)} 局">${portrait(x.hero)}</span>`).join('')}</span>`;
  }


  /* 一张卡就是一个人：只打过 1 局的号也照样是卡，只是读数换个说法 ——
     大数字改成那 1 局的 KDA，胜率位置给「胜 / 负 · 只 1 局」的标记，
     四个读数换成局数、参团、输出、经济，既没假装它有胜率，也没把它降级成一行灰字。 */
  /* 档案字段（巅峰分 / A-B-C 由 cardStrip 给）：擅长英雄、是否指挥、首发替补。
     指挥沿用档案「备注」里的约定（写「主指挥」即可），首发替补取选手ID主数据 role。 */
  function paProfileTags(p) {
    const out = [];
    const profile = profileUI.of(p);
    const heroes = (profile && profile.heroPower || []).slice(0, 3).map((x) => x.hero).filter(Boolean);
    if (heroes.length) out.push(`<span class="pf-tag">擅长 ${esc(heroes.join(' / '))}</span>`);
    if (profile && /指挥/.test(profile.note || '')) out.push('<span class="pf-tag is-cmd">指挥</span>');
    const info = p.memberId ? idInfo(p.memberId) : null;
    if (info && info.role) out.push(`<span class="pf-tag is-role">${info.role === 'main' ? '首发' : '替补'}</span>`);
    return out.length ? `<div class="pf-tags">${out.join('')}</div>` : '';
  }
  function paCard(board, p) {
    const thin = (p.games || 0) < 2;
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const lane = p.lane || '位置未记录';
    const nicks = (p.nicknames || []).filter(Boolean);
    const who = nicks.length && nicks[0] !== p.name ? `${p.name}（营地昵称 ${nicks.join(' / ')}）` : p.name;
    const last = ((p.recent || [])[0] || {}).day || '';
    const tip = `${who} · ${lane} · ${p.side === 'own' ? '本队' : '对手'}${p.bound ? '' : ' · 待认领'}${p.sliced ? ' · 切片：' + paSliceLabel() : ''} · 打开个人页`;
    const win = typeof p.winRate === 'number' && !thin;
    const solo = p.wins > 0 ? 'win' : (p.decided ? 'loss' : '');
    const heroFig = thin ? num(p.kda, 2) : (win ? fmt(p.winRate, 0) : '—');
    return `<article class="arch-card${thin ? ' is-thin' : ''}${p.side === 'enemy' ? ' is-enemy' : ''}" data-pa-goto="${esc(p.name)}" title="${esc(tip)}">
      <header class="arch-card-top">
        <span class="arch-lane" data-side="${esc(p.side)}" aria-hidden="true">${esc(laneMark(p.lane))}</span>
        <a class="arch-card-name" href="${esc(paDetailHref(p.name))}">${esc(p.name)}</a>
        ${last ? `<small class="arch-card-when">${esc(String(last).slice(5))}</small>` : ''}
        ${paClaimChip(board, p)}
      </header>
      <div class="arch-card-main">
        <span class="arch-card-hero">
          <b>${heroFig}${!thin && win ? '<i>%</i>' : ''}</b>
          <small>${thin ? '单场 KDA' : '胜率'}</small>
          ${thin
            ? `<span class="arch-solo${solo ? ' is-' + solo : ''}">${solo === 'win' ? '胜' : solo === 'loss' ? '负' : '—'}<i>只 1 局</i></span>`
            : `<span class="arch-meter" aria-hidden="true"><i style="width:${win ? clamp(p.winRate) : 0}%"></i></span>`}
        </span>
        <dl class="arch-card-reads">
          ${thin
            ? `<div><dt>局数</dt><dd>1</dd></div>
               <div><dt>参团</dt><dd>${pct0(p.participation)}</dd></div>
               <div><dt>输出</dt><dd>${pct0(p.damageShare)}</dd></div>
               <div><dt>经济</dt><dd>${pct0(p.goldShare)}</dd></div>`
            : `<div><dt>KDA</dt><dd>${num(p.kda, 2)}</dd></div>
               <div><dt>局数</dt><dd>${fmt(p.games)}</dd></div>
               <div><dt>MVP</dt><dd>${fmt(p.mvp)}</dd></div>
               <div><dt>参团</dt><dd>${pct0(p.participation)}</dd></div>`}
        </dl>
      </div>
      ${profileUI.cardStrip(p)}
      ${paProfileTags(p)}
      <footer class="arch-card-foot">
        ${archHeroes(p)}
      </footer>
    </article>`;
  }

  /* 按战队分框：本队一框，每支对手战队一框，框里全部游戏名都用同一张卡。
     一队先铺 18 张（按局数排），剩下的用「展开全部」打开。 */
    const PA_TEAM_SHOW = 18;
  /* 本队名：summary 里没有或只是「1」这种占位值时直接写「本队」，
     否则标题会变成「1 [本队]」这种读不出意思的东西。 */
  const paOwnTeam = (board) => {
    const name = String(board?.summary?.teamName || board?.identity?.teamName || '').trim();
    return !name || /^\d+$/.test(name) ? '本队' : name;
  };

  /* 每个号属于哪支战队：本队按战队主数据，对手按所在局的 opponent。
     同一个昵称出现在两支队伍里（改名、转会、重名）时，算出场更多的那一队。 */
  function paTeams(board) {    const own = paOwnTeam(board);
    const map = new Map();
    const touch = (name) => {
      let item = map.get(name);
      if (!item) { item = {own: 0, teams: new Map()}; map.set(name, item); }
      return item;
    };
    for (const game of board.games || []) {
      const foe = String(game.opponent || '').trim() || '未匹配战队';
      for (const p of game.own || []) if (p && p.name) touch(p.name).own += 1;
      for (const p of game.enemy || []) if (p && p.name) {
        const item = touch(p.name);
        item.teams.set(foe, (item.teams.get(foe) || 0) + 1);
      }
    }
    return {
      own,
      teamOf(name) {
        const item = map.get(name);
        if (!item) return {team: '未匹配战队', side: 'enemy'};
        if (item.own) return {team: own, side: 'own'};
        const top = [...item.teams.entries()].sort((a, b) => b[1] - a[1])[0];
        return {team: top ? top[0] : '未匹配战队', side: 'enemy'};
      },
    };
  }

  /* 同一份 board 上「号 → 战队」只算一遍：筛选、分组、计数都要用，
     每帧重算 1000 多次没必要。board 换了（刷新、切片）就重来。 */
  let paTeamsMemo = {board: null, value: null};
  function paTeamsCached(board) {
    if (paTeamsMemo.board !== board) paTeamsMemo = {board, value: paTeams(board)};
    return paTeamsMemo.value;
  }

  /* 本队在前，对手按出场局数排，认不出战队的垫底。 */
  function paGroups(board) {
    const teams = paTeamsCached(board);
    const groups = new Map();
    for (const p of paRows(board)) {
      const {team, side} = teams.teamOf(p.name);
      let group = groups.get(team);
      if (!group) { group = {team, side, rows: [], games: 0}; groups.set(team, group); }
      group.rows.push(p);
      group.games += p.games || 0;
    }
    const rank = (g) => (g.side === 'own' ? 0 : g.team === '未匹配战队' ? 2 : 1);
    const list = [...groups.values()].sort((a, b) => rank(a) - rank(b) || b.games - a.games || b.rows.length - a.rows.length);
    for (const group of list) {
      group.rows.sort((a, b) => (b.games || 0) - (a.games || 0) || (b.score || 0) - (a.score || 0));
    }
    return list;
  }

  function paTeamSection(board, group) {
    const expanded = (st.pa.expanded || []).includes(group.team);
    const shown = expanded ? group.rows : group.rows.slice(0, PA_TEAM_SHOW);
    const rest = group.rows.length - shown.length;
    const stable = group.rows.filter((p) => (p.games || 0) >= 2).length;
    const more = rest > 0 || expanded
      ? `<button type="button" class="arch-team-more" data-pa-team-more="${esc(group.team)}" aria-expanded="${expanded}">${glyph(expanded ? 'ban' : 'players', { size: 18 })}${expanded ? '收起' : `展开全部 ${fmt(group.rows.length)} 个`}</button>`
      : '';
    /* 标题已经是「本队」时不再重复挂一个「本队」标签。 */
    const tag = group.side === 'own' && group.team === '本队'
      ? ''
      : `<span class="arch-team-tag is-${group.side}">${group.side === 'own' ? '本队' : '对手'}</span>`;
    return `<section class="arch-team" data-team="${esc(group.team)}">
      <header class="arch-team-head">
        <h2>${esc(group.team)}${tag}</h2>
        <p><b>${fmt(group.rows.length)}</b> 个游戏名 · <b>${fmt(stable)}</b> 个能跨局看 · 共 <b>${fmt(group.games)}</b> 局</p>
        ${more}
      </header>
      <div class="arch-grid">${shown.map((p) => paCard(board, p)).join('')}</div>
      ${rest > 0 ? `<p class="arch-team-foot">还有 ${fmt(rest)} 个游戏名没铺开，点「展开全部」一起看。</p>` : ''}
    </section>`;
  }

  function paGrid(board) {
    const groups = paGroups(board);
    if (!groups.length) return empty('没有符合条件的游戏名，换个位置或把局数放宽。');
    return `<div class="arch-teams">${groups.map((group) => paTeamSection(board, group)).join('')}</div>`;
  }

  /* 列表视图：和网格同一批行，只是排成表。样本不足的行数字写「—」，不用 1 局算 100%。 */
  function paList(board) {
    const rows = paRows(board);
    if (!rows.length) return empty('没有符合条件的游戏名，换个位置或把局数放宽。');
    const pct0 = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${fmt(v, 0)}%` : '—');
    const row = (p) => {
      const thin = (p.games || 0) < 2;
      const val = (v, digits) => (thin ? '—' : num(v, digits));
      return `<div class="arch-row${thin ? ' is-thin' : ''}" data-pa-goto="${esc(p.name)}">
      <a class="arch-row-name" href="${esc(paDetailHref(p.name))}"><i class="arch-lane" data-side="${esc(p.side)}" aria-hidden="true">${esc(laneMark(p.lane))}</i><b>${esc(p.name)}</b>${paClaimChip(board, p)}</a>
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
    return `<div class="arch-list"><div class="arch-row is-head"><span>游戏名</span><span>阵营</span><span>位置</span><span>局数</span><span>胜率</span><span>KDA</span><span>MVP</span><span>参团</span><span>输出</span><span>表现分</span></div>${rows.map(row).join('')}</div>`;
  }

  function paBody(board) {
    /* 选手档案只做选手池展示：一律按选手ID聚合，游戏名不在这里出现。
       匹配（游戏名 → 选手ID）只在「匹配与编组」完成。 */
    return paIdList(board);
  }

  /* 顶部看点：四个数字，用真实英雄头像旁边那条走势撑住右半边。
     四个卡同构：上面一行标签，中间大数字 + 走势，下面是谁、打了多少局。
     整张卡是链接，直接进个人页。 */
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
    return cells.map(([label, value, unit, p]) => {
      const trend = archSpark(p);
      const samples = archSparkValues(p).length;
      return `<a class="arch-hl" href="${esc(paDetailHref(p.name))}" title="${esc(p.name)} · ${fmt(p.games)} 局 · 打开个人页">
      <span class="arch-hl-kicker">${esc(label)}</span>
      <span class="arch-hl-fig"><b>${value}${unit ? `<i>${esc(unit)}</i>` : ''}</b>${trend ? `<span class="arch-hl-trend">${trend}<small>近 ${samples} 局评分</small></span>` : ''}</span>
      <span class="arch-hl-who"><b>${esc(p.name)}</b><i>${fmt(p.games)} 局</i></span>
    </a>`;
    }).join('');
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

  /* 一个选手ID一张卡：ID 名 + 位置 + 聚合数据 + 转会 / 离队 / 删除。 */
  function paIdCard(group) {
    const hasTeam = Boolean(group.teamId || group.teamName);
    const lane = group.position || group.lane || '位置未填';
    const figures = [
      ['局', group.games ? fmt(group.games) : '—'],
      ['胜率', group.games ? pct(group.winRate) : '—'],
      ['KDA', group.games ? num(group.kda, 2) : '—'],
      ['表现分', group.games ? num(group.score, 1) : '—'],
    ];
    /* 选手档案是纯 ID 池：游戏名不在这里展示，挂接/解绑只在「匹配与编组」做。 */
    const linked = group.names.length > 0;
    /* 只有挂了游戏名的选手ID才有对局可看：点标题进详情页，多个号的数据合并。
        还没匹配的只显示提示，不给入口（点进去也是空页）。 */
    const title = linked
      ? `<a class="arch-id-title-link" href="${esc(href(group.name))}" title="打开 ${esc(group.name)} 的选手详情">${esc(group.name)}</a>`
      : `<b>${esc(group.name)}</b>`;
    const state = linked ? '有对局数据' : '暂无数据';
    /* 一行一个选手ID：谁 → 打成什么样 → 能做什么，三段从左到右。 */
    return `<article class="arch-id${group.names.length ? ' is-openable' : ''}" data-pa-id-card="${esc(group.id)}"${group.names.length ? ` data-pl-goto="${esc(group.name)}"` : ''}>
      <header class="arch-id-head">
        <span class="arch-id-mark" aria-hidden="true">${esc(String(group.name).trim().slice(0, 1) || '?')}</span>
        <span class="arch-id-title">
          ${title}
          <small class="arch-id-meta">
            <span class="arch-id-lane">${esc(lane)}</span>
            <span class="arch-id-state${linked ? ' is-linked' : ''}"><i aria-hidden="true"></i>${state}</span>
          </small>
        </span>
      </header>
      <span class="arch-id-figs">${figures.map(([k, v]) => `<span><b>${v}</b><small>${k}</small></span>`).join('')}</span>
      <footer class="arch-id-foot">
        <button type="button" data-pa-id-edit="${esc(group.id)}">${glyph('edit', { size: 18 })}编辑 / 转会</button>
        ${hasTeam
          ? `<button type="button" data-pa-id-leave="${esc(group.id)}">${glyph('export', { size: 18 })}移出战队</button>`
          : `<button type="button" data-pa-id-join="${esc(group.id)}">${glyph('home', { size: 18 })}加入战队</button>`}
        <button type="button" class="is-danger" data-pa-id-delete="${esc(group.id)}" data-id-name="${esc(group.name)}">${glyph('trash', { size: 18 })}删除选手ID</button>
      </footer>
    </article>`;
  }

  function paIdList(board) {
    const all = idGroups(board);
    const teams = paIdTeams(board);
    if (!teams.length) {
      return all.length
        ? empty('没有符合条件的选手ID，换个关键词再试。')
        : `<section class="arch-sec is-guide">
            <div class="arch-sec-head">
              <h2>${glyph('players', { size: 20 })}选手池还是空的</h2>
            </div>
          </section>`;
    }
    const ownName = String(board.summary?.teamName || '').trim();
    return `<div class="arch-teams">${teams.map((team, index) => {
      const titleId = `pa-team-title-${index}`;
      const label = team.name === PA_TEAM_NONE ? '未归队' : team.name;
      const tagClass = ownName && team.name === ownName ? 'is-own' : 'is-enemy';
      const indexLabel = String(index + 1).padStart(2, '0');
      return `<section class="arch-team" data-pa-team-group="${esc(team.key)}" aria-labelledby="${titleId}">
        <header class="arch-team-head">
          <span class="arch-team-index" aria-hidden="true">${indexLabel}</span>
          <h2 id="${titleId}">${esc(label)}</h2>
          <span class="arch-team-tag ${tagClass}">${fmt(team.groups.length)} 名选手</span>
        </header>
        <div class="arch-ids">${team.groups.map(paIdCard).join('')}</div>
      </section>`;
    }).join('')}</div>`;
  }

  /* 选手档案 = 选手池的纯展示：只按选手ID整合，不做认领、不做游戏名匹配。
     游戏名 → 选手ID 的挂接只在「匹配与编组」完成；这里只读选手主数据与
     聚合表现。战队归属取自选手ID主数据，本队框里不会再混进别队的游戏名。 */
  function archivePage(board, identity) {
    st.board = board;
    st.ids = identity || {players: [], teams: []};
    st.pa.mode = 'id';
    paReadHash();
    st.pa.mode = 'id';
    const ids = paFilteredGroups(board);
    const linkedTotal = ids.filter((group) => group.names.length > 0).length;
    const teamTotal = paIdTeams(board).length;

    const hero = `<header class="arch-head"><div class="arch-top">
      <div class="arch-title-block">
        <p class="arch-kicker">PLAYER ARCHIVE <span>/</span> 选手身份与表现</p>
        <h1>选手档案</h1>
        <p class="arch-subtitle">按战队集中管理选手 ID、对局数据与归属。</p>
      </div>
      <div class="arch-id-summary" aria-label="选手档案概览">
        <div><b>${fmt(ids.length)}</b><span>选手 ID</span></div>
        <div><b>${fmt(teamTotal)}</b><span>战队</span></div>
        <div><b>${fmt(linkedTotal)}</b><span>已有对局</span></div>
      </div>
    </div></header>`;
    const bar = `<div class="arch-bar is-id" data-pa-bar>
      <label class="arch-search">${ICON.search}
        <input data-pa-search value="${esc(st.pa.q)}" placeholder="搜选手ID" autocomplete="off" spellcheck="false" aria-label="搜索选手ID">
      </label>
      ${teamSelect(board)}
      <div class="arch-bar-end">
        <span class="arch-count" data-pa-count>${fmt(ids.length)} 个选手ID</span>
        <button type="button" class="arch-btn is-primary" data-pa-add-player>${glyph('players', { size: 18 })}新建选手ID</button>
      </div>
    </div>`;
    return `<div class="page arch-page" data-pl-page="archive">
      ${hero}
      ${bar}
      <div data-pa-body>${paBody(board)}</div>
      <p class="arch-note">${glyph('warning', { size: 16 })}转会不改已经打完的局</p>
    </div>`;
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
      <button type="button" class="control" data-pl-swap aria-label="交换两名选手">${glyph('compare', { size: 18 })}交换</button>
      ${(st.recent || []).length ? `<span class="pl-recent" aria-label="最近对比">最近：${(st.recent || []).slice(0, 4).map(n => `<button type="button" data-pl-recent="${esc(n)}">${esc(n)}</button>`).join('')}</span>` : ''}
      ${st.cmpLane && laneStable < 2 ? `<span class="pl-filter-count is-warn">${glyph('warning', { size: 16 })}该路只有 ${fmt(laneStable)} 人打了 ≥2 局，对比样本偏薄</span>` : ''}</div>`;
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
  function soloPage(board, name, detail, comboPool, kplBaseline) {
    /* 后端对已匹配的游戏名会自动切到选手ID口径；路由参数也跟着换，
       头部标题 / 换选手下拉 / 深链才和数据里的名字一致。 */
    if (detail && detail.identity && detail.identity.bound && detail.summary && detail.summary.name) {
      name = detail.summary.name;
    }
    st.pd = {...(st.pd || {}), board, name, detail,
      kplBaseline: kplBaseline || (st.pd && st.pd.kplBaseline) || null,
      comboPool: comboPool || (st.pd && st.pd.comboPool) || null};
    const pool = ((board && board.players) || []).filter((p) => p && p.name && (p.games || 0) >= 1);
    const own = pool.filter((p) => p.side === 'own');
    /* 「换选手」下拉也走选手ID：挂了多个游戏名的只出现一次，名字一律 ID。 */
    const membersById = new Map((((board && board.identity && board.identity.members) || []))
      .map((m) => [String(m.id), m]));
    const labelOf = (p) => {
      const owner = membersById.get(String(p.memberId || ''));
      return owner ? (owner.label || owner.name || p.name) : p.name;
    };
    st.pd.roster = [...new Set((own.length >= 2 ? own : pool).map(labelOf))];
    /* 第一次进这个人时，用 URL 里的筛选参数回填；之后以内存为准（内存会同步回 URL）。 */
    const fromUrl = readFilterHash();
    if (fromUrl && st.pd.hashFor !== name) {
      st.pd.ui = {...(st.pd.ui || {}), ...fromUrl};
      st.pd.hashFor = name;
    }
    /* 深链指定了 KPL 赛事时，基准要按那一项赛事重算，不能拿全部赛事冒充。 */
    const wantedLeague = st.pd.ui && st.pd.ui.kplLeague;
    if (wantedLeague && (st.pd.kplBaseline || {}).league !== wantedLeague && !st.pd.kplFetching) {
      st.pd.kplFetching = true;
      fetch(`${API_BASE}/api/v3/kpl/lane-baseline?league=${encodeURIComponent(wantedLeague)}`,
        {headers: {Accept: 'application/json'}})
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (data) { st.pd.kplBaseline = data; refreshSolo(); } })
        .catch(() => {})
        .finally(() => { st.pd.kplFetching = false; });
    }
    bindSoloKeys();
    bindTrendDrag();
    /* 深链直接进详情时，档案可能还没加载过：拉一次，回来整页重画。 */
    profileUI.ensure();
    return detailPage.render(board, name, detail, st.pd.kplBaseline);
  }

  /* 标准线（评级规则）异步取到后重画一次详情页；只影响单人页，不动档案筛选。 */
  document.addEventListener('pdx:rules-ready', () => {
    const root = pageRoot();
    if (!root || root.dataset.plPage !== 'solo' || !st.pd || !st.pd.name) return;
    const scroll = window.scrollY;
    root.outerHTML = soloPage(st.pd.board, st.pd.name, st.pd.detail, st.pd.comboPool);
    window.scrollTo(0, scroll);
  });
  document.addEventListener('grade-rules:saved', () => {
    if (st.pd) delete st.pd.gradeRules;
  });

  /* ── 筛选 ↔ URL：教练可以把「某人对抗路视图」整条链接发出去 ────────── */
  /* ── 筛选 ↔ URL：教练可以把「某人 近5日 游走 项羽」整条链接发出去 ──────
     前六个是切片（范围 / 自定义起止 / 分路 / 英雄 / 对手 / 结果 / 门槛），
     后面是各卡自己的那一维；旧的 lane/period 键继续认，老链接不会失效。 */
  const FILTER_KEYS = ['range', 'from', 'to', 'lane', 'hero', 'opp', 'res', 'min',
    'benchLane', 'bench', 'benchField', 'benchSource', 'kplLeague',
    'heroLane', 'roleView', 'cmpHero', 'cmpMetric', 'period', 'dayMetric', 'dayLane',
    'extreme', 'winLane', 'stab', 'stabMetric', 'matrix',
    'counterMetric', 'comboSort', 'comboHero', 'altHero', 'heroMetric', 'heroTop'];
  function readFilterHash() {
    const q = String(location.hash || '').split('?')[1];
    if (!q) return null;
    const params = new URLSearchParams(q);
    const out = {};
    for (const key of FILTER_KEYS) {
      const val = params.get(key);
      if (val) out[key] = val;
    }
    return Object.keys(out).length ? out : null;
  }
  function writeFilterHash() {
    if (!st.pd || !st.pd.name) return;
    const ui = st.pd.ui || {};
    const params = new URLSearchParams();
    for (const key of FILTER_KEYS) {
      const val = ui[key];
      if (typeof val === 'string' && val && val !== '全部') params.set(key, val);
    }
    const q = params.toString();
    const base = `#playerdetail/${encodeURIComponent(st.pd.name)}`;
    const next = q ? `${base}?${q}` : base;
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ── 键盘：← → 换选手（教练挨个过队员时比点下拉快）────────────────── */
  let soloKeysBound = false;
  function bindSoloKeys() {
    if (soloKeysBound) return;
    soloKeysBound = true;
    document.addEventListener('keydown', (event) => {
      if (!st.pd || !st.pd.roster || !st.pd.name) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const el = event.target;
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const roster = st.pd.roster;
      const at = roster.indexOf(st.pd.name);
      if (at < 0 || roster.length < 2) return;
      const step = event.key === 'ArrowRight' ? 1 : roster.length - 1;
      const next = roster[(at + step) % roster.length];
      if (!next || next === st.pd.name) return;
      event.preventDefault();
      location.hash = '#playerdetail/' + encodeURIComponent(next);
    });
  }

  /* ── 英雄池变动：两栏卡片区按住拖动（滚轮交给原生 overflow-y） ─────
     事件委托在 document 上，整页重画后依然有效。只有真的拖过 4px 才拦
     后面的 click，不然卡片里的英雄链接会被误伤。 */
  let trendDragBound = false;
  function bindTrendDrag() {
    if (trendDragBound) return;
    trendDragBound = true;
    document.addEventListener('dragstart', (event) => {
      if (event.target.closest('[data-pool-scroll]')) event.preventDefault();
    });
    document.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'mouse' || event.button !== 0) return;
      const box = event.target.closest('[data-pool-scroll]');
      if (!box || box.scrollHeight <= box.clientHeight) return;
      const startY = event.clientY;
      const startTop = box.scrollTop;
      let moved = false;
      const move = (e) => {
        const dy = e.clientY - startY;
        if (!moved && Math.abs(dy) < 4) return;
        if (!moved) { moved = true; box.classList.add('is-dragging'); }
        e.preventDefault();
        box.scrollTop = startTop - dy;
      };
      const stop = () => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', stop);
        document.removeEventListener('pointercancel', stop);
        if (!moved) return;
        box.classList.remove('is-dragging');
        const swallow = (e) => { e.preventDefault(); e.stopPropagation(); };
        box.addEventListener('click', swallow, {capture: true, once: true});
        setTimeout(() => box.removeEventListener('click', swallow, true), 0);
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', stop);
      document.addEventListener('pointercancel', stop);
    });
  }

  /* ── 交互 ─────────────────────────────────────────────────────── */
  function pageRoot() {
    return document.querySelector('[data-pl-page]');
  }
  function refreshArchive() {
    const board = st.board, root = pageRoot();
    if (!board || !root) return;
    const ids = paFilteredGroups(board);
    const body = root.querySelector('[data-pa-body]');
    if (body) body.innerHTML = paBody(board);
    const count = root.querySelector('[data-pa-count]');
    if (count) count.textContent = `${fmt(ids.length)} 个选手ID`;
    const summary = root.querySelector('.arch-id-summary');
    if (summary) {
      const values = [ids.length, paIdTeams(board).length, ids.filter((group) => group.names.length > 0).length];
      summary.querySelectorAll('b').forEach((node, index) => { node.textContent = fmt(values[index]); });
    }
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
    /* 单人详情：下拉筛选框（分路 / 指标 / 英雄 / 类型）换了就写进 st.pd.ui 再重画。 */
    /* 换选手：直接跳到另一个人的详情页，不用回档案页再点一次。 */
    const sw = event.target.closest('[data-pl-switch-player]');
    if (sw && sw.value) {
      location.hash = '#playerdetail/' + encodeURIComponent(sw.value);
      return true;
    }
    const pdxSel = event.target.closest('[data-pdx-select]');
    if (pdxSel && st.pd && st.pd.detail) {
      st.pd.ui = {...(st.pd.ui || {}), [pdxSel.dataset.pdxSelect]: pdxSel.value};
      writeFilterHash();
      if (pdxSel.dataset.pdxSelect === 'kplLeague') {
        const league = pdxSel.value;
        fetch(`${API_BASE}/api/v3/kpl/lane-baseline?league=${encodeURIComponent(league)}`,
          {headers: {Accept: 'application/json'}})
          .then((r) => (r.ok ? r.json() : null))
          .then((data) => { if (data) { st.pd.kplBaseline = data; refreshSolo(); } })
          .catch(() => {});
        return true;
      }
      refreshSolo();
      return true;
    }
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
    /* 战队筛选：按选手ID的归属过滤。和搜索框是「且」的关系，两个条件可叠加。 */
    if (event.target.matches('[data-pa-team]')) {
      st.pa.team = event.target.value || '';
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    const pa = event.target.closest('[data-pa-filter]');
    if (pa) {
      const key = pa.dataset.paFilter;
      st.pa[key] = ['min', 'segMin', 'peakMin'].includes(key)
        ? (key === 'min' ? (Number(pa.value) || 1) : (Number(pa.value) || 0))
        : pa.value;
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
        <button type="button" class="head-button" data-drawer-close aria-label="关闭档案预览">${glyph('ban', { size: 16 })}</button>
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
    dialog.innerHTML = `<div class="dialog-head"><div><h2>${glyph('compare', { size: 18 })}和谁对比？</h2><p>${esc(name)} · ${esc(me.lane || '位置未记录')}</p></div><button type="button" class="head-button" data-pick-close aria-label="关闭">${glyph('ban', { size: 16 })}</button></div>
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
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>${glyph('players', { size: 18 })}认领游戏名</h2>
        <p class="dialog-consequence">${glyph('warning', { size: 16 })}${esc(label)} · ${fmt(games)} 局 · ${fmt(accounts.length)} 个账号，认领后并入该 ID</p></div><button type="button" class="head-button" data-pl-name-close aria-label="关闭">${glyph('ban', { size: 16 })}</button></div>
      <div class="dialog-body">
        <div class="nm-modes" role="radiogroup" aria-label="认领方式">
          <label class="nm-mode"><input type="radio" name="mode" value="claim" ${preferCreate ? '' : 'checked'} ${roster.length ? '' : 'disabled'}><span><b>挂到已有选手ID</b><small>${roster.length ? `共 ${fmt(roster.length)} 个ID，可搜名字或战队` : '还没有选手ID，先新建一个'}</small></span></label>
          <label class="nm-mode"><input type="radio" name="mode" value="create" ${preferCreate ? 'checked' : ''}><span><b>新建选手ID</b><small>起真名、选战队，同时建 ID 与映射</small></span></label>
        </div>
        <div class="nm-pane" data-nm-pane="claim" ${preferCreate ? 'hidden' : ''}>
          <label>搜索选手ID<input data-nm-search placeholder="名字 / 战队" autocomplete="off"></label>
          <div class="nm-idlist" data-nm-list>${roster.map(idRow).join('') || `<p class="nm-empty">${glyph('players', { size: 20 })}<b>还没有选手ID</b><span>切到「新建选手ID」</span></p>`}</div>
          <input type="hidden" name="playerId" value="">
        </div>
        <div class="nm-pane" data-nm-pane="create" ${preferCreate ? '' : 'hidden'}>
          <div class="date-fields"><label>选手ID<input name="name" maxlength="40" value="" placeholder="真名，如：陈泽彬" autocomplete="off"></label>
            <label>所属战队<select name="teamId"><option value="">暂不归属（进入选手池）</option>${teamOptions}</select></label></div>
          <fieldset class="sx-pos-field"><legend>位置（可多选，第一个是主位置）</legend><div class="sx-pos-chips">${LANES.map(x => `<label class="sx-pos-chip"><input type="checkbox" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
        </div>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-pl-name-close>${glyph('ban', { size: 18 })}取消</button><button class="primary" type="submit" title="认错后可在选手ID卡上解绑">${glyph('shield', { size: 18 })}<span data-nm-submit-label>${preferCreate ? '新建并认领' : '确认认领'}</span></button></div></form>`;
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('.filter-error');
    const submit = form.querySelector('button[type=submit]');
    const picked = form.querySelector('input[name=playerId]');
    const list = form.querySelector('[data-nm-list]');
    const search = form.querySelector('[data-nm-search]');
    const syncMode = () => {
      const mode = form.querySelector('input[name=mode]:checked')?.value || 'create';
      form.querySelectorAll('[data-nm-pane]').forEach((pane) => { pane.hidden = pane.dataset.nmPane !== mode; });
      const label = submit.querySelector('[data-nm-submit-label]');
      if (label) label.textContent = mode === 'claim' ? '确认认领' : '新建并认领';
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
        list.innerHTML = found.map(idRow).join('') || `<p class="nm-empty">${glyph('players', { size: 18 })}没有匹配的选手ID</p>`;
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
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>${glyph('players', { size: 18 })}新建选手ID</h2></div><button type="button" class="head-button" data-add-player-close aria-label="关闭">${glyph('ban', { size: 16 })}</button></div>
      <div class="dialog-body">
        <div class="date-fields"><label>选手ID<input name="name" required maxlength="40" placeholder="例如：小义"></label>
          <label>所属战队<select name="team" title="新战队请到「赛训 → 数据准备」建档"><option value="">暂不归属（进入选手池）</option>${teamOptions}</select></label></div>
        <fieldset class="sx-pos-field"><legend>位置</legend><div class="sx-pos-chips">${LANES.map(x => `<label class="sx-pos-chip"><input type="radio" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-add-player-close>${glyph('ban', { size: 18 })}取消</button><button class="primary" type="submit">${glyph('shield', { size: 18 })}新建选手ID</button></div></form>`;
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
    dialog.innerHTML = `<form><div class="dialog-head"><div><h2>${glyph('edit', { size: 18 })}编辑选手ID</h2></div><button type="button" class="head-button" data-edit-id-close aria-label="关闭">${glyph('ban', { size: 16 })}</button></div>
      <div class="dialog-body">
        <div class="date-fields"><label>选手ID<input name="name" required maxlength="40" value="${esc(info.name || '')}"></label>
          <label>位置<select name="position"><option value="">待确认</option>${LANES.map((x) => `<option value="${x}" ${info.position === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label></div>
        <label>所属战队<select name="teamId"><option value="">暂不归属（进入选手池）</option>${teamOptions}</select></label>
        <p class="dialog-consequence">${glyph('warning', { size: 16 })}换战队不影响历史，已打完的对局仍记在原战队名下</p>
        <p class="filter-error" role="alert"></p></div>
      <div class="dialog-actions"><button type="button" class="control" data-edit-id-close>${glyph('ban', { size: 18 })}取消</button><button class="primary" type="submit">${glyph('shield', { size: 18 })}保存</button></div></form>`;
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

  /* 单人详情整页重画：只换这一页，载荷已在 st.pd 里，不重新请求接口。
     重画是同步的，滚动位置先存后还原；点完筛选按钮焦点回到同一颗按钮，
     键盘连续切换分路时不会掉焦点。 */
  function refreshSolo(keepAttr) {
    const root = pageRoot();
    if (!root || !st.pd || !st.pd.detail) return;
    const scroll = window.scrollY;
    const host = document.createElement('div');
    host.innerHTML = soloPage(st.pd.board, st.pd.name, st.pd.detail, st.pd.comboPool);
    const next = host.firstElementChild;
    if (!next) return;
    root.replaceWith(next);
    window.scrollTo(0, scroll);
    if (keepAttr) {
      const el = document.querySelector(`[${keepAttr}]`);
      if (el) el.focus({preventScroll: true});
    }
  }

  function click(event) {
    /* 单人详情：卡内筛选（分路 / 指标 / 口径 / 时间窗口）。
       data-pdx-set 是单选（再点一次同一个就取消、回到全部），data-pdx-toggle 是多选（最多留 4 个）。
       选择结果写进 st.pd.ui，由 readFilters 统一校验，再到整页重画。 */
    /* 整页打印（教练整份给领队） */
    if (event.target.closest('[data-pdx-print]')) {
      window.print();
      return true;
    }
    /* 一键重置本页所有筛选 */
    if (event.target.closest('[data-pdx-reset]')) {
      if (st.pd) { st.pd.ui = {}; writeFilterHash(); refreshSolo(); }
      return true;
    }
    /* 回到顶部（不写 hash，避免触发路由重渲染） */
    if (event.target.closest('[data-pdx-top]')) {
      window.scrollTo({top: 0, behavior: 'smooth'});
      return true;
    }
    const setter = event.target.closest('[data-pdx-set],[data-pdx-toggle]');
    if (setter) {
      const toggle = setter.hasAttribute('data-pdx-toggle');
      const raw = (toggle ? setter.dataset.pdxToggle : setter.dataset.pdxSet) || '';
      const at = raw.indexOf(':');
      if (at > 0 && st.pd && st.pd.detail) {
        const name = raw.slice(0, at), value = raw.slice(at + 1);
        const ui = (st.pd.ui = st.pd.ui || {});
        if (toggle) {
          /* 多选第一次点的时候 st.pd.ui 里还没有这个键，用当前已按下的按钮当起点，
             否则会把默认选中的几个英雄一起清掉。 */
          let cur = String(ui[name] ?? '').split(',').filter(Boolean);
          if (!cur.length) {
            const box = setter.closest('.pv-filter');
            cur = box ? [...box.querySelectorAll('[aria-pressed="true"]')]
              .map((btn) => (btn.dataset.pdxToggle || '').split(':').slice(1).join(':')).filter(Boolean) : [];
          }
          const next = cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value];
          ui[name] = next.slice(-4).join(',');
        } else {
          /* 单选再点一次同一个 = 取消，回到「全部」；写空串，writeFilterHash 会把它从 URL 里去掉。 */
          ui[name] = String(ui[name] ?? '') === value ? '' : value;
        }
        writeFilterHash();
        refreshSolo(`${toggle ? 'data-pdx-toggle' : 'data-pdx-set'}="${raw}"`);
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
    const editId = event.target.closest('[data-pa-id-edit]');
    if (editId) { editIdentity(editId.dataset.paIdEdit); return true; }
    const leaveId = event.target.closest('[data-pa-id-leave]');
    if (leaveId) { leaveIdentity(leaveId.dataset.paIdLeave); return true; }
    const joinId = event.target.closest('[data-pa-id-join]');
    if (joinId) { editIdentity(joinId.dataset.paIdJoin); return true; }
    const deleteId = event.target.closest('[data-pa-id-delete]');
    if (deleteId) { deleteIdentity(deleteId.dataset.paIdDelete, deleteId.dataset.idName); return true; }
    /* 阵营用分段按钮，不用下拉：三个选项就那三个，下拉要多点一次。
       点「本队 / 对手 / 全部」时把「具体对手」清掉，两层不会叠在一起。 */
    const sideBtn = event.target.closest('[data-pa-side]');
    if (sideBtn) {
      st.pa.side = 'own';
      st.pa.team = '';
      st.pa.page = 1;
      refreshArchive();
      return true;
    }
    /* 卡片 / 详情页的「档案」：同一个弹窗，采不到就手填。 */
    const profileBtn = event.target.closest('[data-pa-profile]');
    if (profileBtn) {
      event.preventDefault();
      event.stopPropagation();
      profileUI.open(profileBtn.dataset.paProfile || '');
      return true;
    }
    if (event.target.closest('[data-pa-add-player]')) { addPlayerDialog(); return true; }
    /* 任何进单人详情的链接先记下来源页，详情页的「返回」按来源走，
       hash 原样带上，筛选与翻页都能还原。 */
    const detailLink = event.target.closest('a[href^="#playerdetail/"]');
    if (detailLink) {
      const page = document.querySelector('[data-pl-page]');
      const source = page && page.dataset.plPage;
      const labels = {archive: '选手档案', playercompare: '选手对比', solo: '选手详情'};
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
    /* 选手分析：翻页、网格/列表切换、导出 CSV */
    const paCompare = event.target.closest('[data-pa-compare]');
    if (paCompare) {
      st.a = paCompare.dataset.paCompare;
      st.b = '';
      location.hash = '#playercompare';
      return true;
    }
    const paGoto = event.target.closest('[data-pa-goto]');
    if (paGoto && !event.target.closest('button, a, input')) {
      location.hash = href(paGoto.dataset.paGoto);
      return true;
    }
    const teamMore = event.target.closest('[data-pa-team-more]');
    if (teamMore) {
      const key = teamMore.dataset.paTeamMore || '';
      const list = st.pa.expanded || (st.pa.expanded = []);
      const at = list.indexOf(key);
      if (at >= 0) list.splice(at, 1);
      else list.push(key);
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
  return {archivePage, comparePage, soloPage, change, click};
}
