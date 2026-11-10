/* 跨局分析（通用版）
   两块数据各司其职：
   - 全量轻量向量（/api/cross/vectors）→ 通用跨局分析，结论基于全部对局的总体，
     与分页、明细窗口解耦；分析内核在 cross-analytics.js，纯计算、可对 N 局压测。
   - 最近明细窗口 → 逐局对照台 / 本批参照 / 分路对位，点进某局再取完整详情。
   布局：一块一行，全部内容块全宽纵向排列。 */

import { analyzeCohort } from './cross-analytics.js';
import { renderViz } from './cross-viz.js';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const sum = (arr) => arr.reduce((s, v) => s + (num(v) ? v : 0), 0);
const avg = (arr) => (arr.length ? sum(arr) / arr.length : null);
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

function median(arr) {
  if (!arr.length) return null;
  const s = arr.slice().sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

function interpSeries(pts, t) {
  if (!pts || !pts.length) return null;
  if (t <= pts[0][0]) return pts[0][1];
  if (t >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][0] >= t) {
      const [ta, va] = pts[i - 1], [tb, vb] = pts[i];
      return va + (vb - va) * (t - ta) / Math.max(1, tb - ta);
    }
  }
  return null;
}

export function createCrossPage(h) {
  const { esc, fmt, pct, diff, time, portrait } = h;
  let sortKey = 'date';
  let sliceSession = '';
  let sliceVersion = '';
  let filterResult = '';
  let filterOpp = '';
  let lastRows = [];
  let lastMeta = { total: 0, limit: 200 };
  let lastCards = new Map();
  let lastRowIndex = new Map();

  const heroIcon = null;

  /* ── 单局：把一局所需的读数一次性算齐 ───────────────────────── */
  function buildMatch(row) {
    const d = row.detail || {};
    const players = Array.isArray(row.players) ? row.players : [];
    const ownCamp = row.ownCamp || 'blue';
    const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';
    const sign = ownCamp === 'blue' ? 1 : -1;
    const own = players.filter((p) => p.camp === ownCamp);
    const foe = players.filter((p) => p.camp === foeCamp);
    // 缺时长保持 null：以前缺省成 0 会让「最短一局」显示 0:00 并污染极值，
    // 行内也显示成 0:00。显示端 num()/time() 会把 null 显示为「—」。
    const duration = num(row.duration) && row.duration > 0 ? row.duration
      : (num(d.duration) && d.duration > 0 ? d.duration : null);

    const scores = d.scores || {};
    let ownKills = num(scores[ownCamp]) ? scores[ownCamp] : sum(own.map((p) => p.kills));
    let foeKills = num(scores[foeCamp]) ? scores[foeCamp] : sum(foe.map((p) => p.kills));
    if (!ownKills && !foeKills) {
      const tt = d.teamTotals || {};
      ownKills = (tt[ownCamp] || {}).totals ? tt[ownCamp].totals.kills : null;
      foeKills = (tt[foeCamp] || {}).totals ? tt[foeCamp].totals.kills : null;
    }

    const econ = [];
    for (const p of (d.process && d.process.timeline) || []) {
      if (!num(p.gameTime)) continue;
      let v = null;
      if (num(p.blueGold) && num(p.redGold)) v = (p.blueGold - p.redGold) * sign;
      else if (num(p.goldDiff)) v = p.goldDiff * sign;
      if (num(v)) econ.push([p.gameTime, v]);
    }
    let finalDiff = econ.length ? econ[econ.length - 1][1] : null;
    if (!num(finalDiff) && d.teamTotals) {
      const a = (d.teamTotals[ownCamp] || {}).totals || {};
      const b = (d.teamTotals[foeCamp] || {}).totals || {};
      if (num(a.gold) && num(b.gold)) finalDiff = a.gold - b.gold;
    }

    const laneDiff = {};
    for (const lane of LANES) {
      const p = own.find((x) => x.position === lane);
      const q = foe.find((x) => x.position === lane);
      if (!p || !q || !duration) continue;
      laneDiff[lane] = {
        gold: ((num(p.gold) ? p.gold : 0) - (num(q.gold) ? q.gold : 0)) / duration * 60,
        damage: ((num(p.damage) ? p.damage : 0) - (num(q.damage) ? q.damage : 0)) / duration * 60,
        taken: ((num(p.taken) ? p.taken : 0) - (num(q.taken) ? q.taken : 0)) / duration * 60,
      };
    }

    const lineup = LANES.map((lane) => own.find((p) => p.position === lane)).filter(Boolean);
    for (const p of own) if (lineup.length < 5 && !lineup.includes(p)) lineup.push(p);
    const mvp = own.slice().sort((a, b) => (num(b.gold) ? b.gold : 0) - (num(a.gold) ? a.gold : 0))[0] || null;

    const frontline = frontlineOf(row, ownCamp, duration);
    const bp = d.campBp || {};
    const bans = [...((bp.bans || {}).left || []), ...((bp.bans || {}).right || [])]
      .map((x) => x && x.name).filter(Boolean);
    const replay = row.replay || {};
    const fights = (replay.fights || []).length;
    const deathsOwn = (replay.deaths || []).filter((x) => x.camp === ownCamp).length;
    const deathsFoe = (replay.deaths || []).filter((x) => x.camp === foeCamp).length;

    /* 真实开赛时刻：同一天的多局训练只有按时刻才能谈「进程」 */
    const startText = bp.startTime || '';
    const st = /(\d{1,2}):(\d{2})/.exec(startText);
    const startMin = st ? Number(st[1]) * 60 + Number(st[2]) : null;
    const startClock = st ? st[0] : '';
    const heroes = own.map((p) => p.hero).filter(Boolean);

    /* 5 分钟窗口的经济差净变化；预留 8 段覆盖长局，空段在汇总时按实际覆盖剔除 */
    const windows = [];
    for (let k = 0; k < 8; k++) {
      const t0 = k * 300, t1 = (k + 1) * 300;
      if (!duration || duration < t1) { windows.push(null); continue; }
      const v0 = interpSeries(econ, t0), v1 = interpSeries(econ, t1);
      windows.push(num(v0) && num(v1) ? v1 - v0 : null);
    }

    return {
      key: row.key,
      date: row.date || d.dateText || '',
      opponent: row.opponent || '',
      title: (row.opponent || '').trim() || d.title || row.session || '训练赛',
      session: row.session || d.session || '',
      version: row.version || d.version || '',
      result: row.result || '',
      duration, ownCamp, ownKills, foeKills,
      killMargin: num(ownKills) && num(foeKills) ? ownKills - foeKills : null,
      econ, at10: interpSeries(econ, 600), finalDiff,
      frontEnd: frontline && frontline.length ? frontline[frontline.length - 1][1] : null,
      frontMean: frontline && frontline.length ? avg(frontline.map((p) => p[1])) : null,
      lineup, mvp, laneDiff, bans, fights, deathsOwn, deathsFoe,
      startText, startClock, startMin, heroes, windows,
    };
  }

  /* 位置数据缺 camp 时按「前五蓝 / 后五红」回落，保证每局都算得出阵线 */
  function frontlineOf(row, ownCamp, duration) {
    const pos = row.positions;
    if (!pos || !pos.players || !pos.players.length) return null;
    const step = pos.step || 2;
    const list = pos.players.map((s, i) => ({ camp: s.camp || (i < 5 ? 'blue' : 'red'), points: s.points || [] }));
    const own = list.filter((s) => s.camp === ownCamp && s.points.length);
    if (own.length < 4) return null;
    const forward = ownCamp === 'blue' ? 1 : -1;
    const len = Math.min(...own.map((s) => s.points.length));
    const total = Math.min(duration || Infinity, (len - 1) * step);
    if (!total || total <= 0) return null;
    const out = [];
    for (let t = 0; t <= total; t += 15) {
      const i = Math.round(t / step);
      const vals = own.map((s) => {
        const pt = s.points[i];
        if (!pt || !num(pt[0]) || !num(pt[1])) return null;
        const p = clamp((pt[0] + pt[1] + 112) / 224, 0, 1);
        return forward > 0 ? p : 1 - p;
      }).filter((v) => num(v));
      if (vals.length >= 3) out.push([t / total, avg(vals)]);
    }
    return out.length > 2 ? out : null;
  }

  /* ── 本批汇总：结论与参照都从这里取 ─────────────────────────── */
  const METRICS = [
    { key: 'finalDiff', label: '终局经济差', fmt: (v) => diff(Math.round(v)) },
    { key: 'at10', label: '10′ 经济差', fmt: (v) => diff(Math.round(v)) },
    { key: 'killMargin', label: '人头差', fmt: (v) => diff(Math.round(v)) },
    { key: 'duration', label: '时长', fmt: (v) => time(v) },
    { key: 'frontEnd', label: '阵线终值', fmt: (v) => Math.round(v * 100) + '%' },
  ];

  function summarize(list) {
    const decided = list.filter((m) => m.result === 'win' || m.result === 'loss');
    const wins = decided.filter((m) => m.result === 'win').length;
    const values = (key) => list.map((m) => m[key]).filter(num).sort((a, b) => a - b);
    const med = (key) => median(values(key));
    const dates = list.map((m) => m.date).filter(Boolean).sort();
    const sessions = new Set(list.map((m) => m.session).filter(Boolean));
    const opponents = new Set(list.map((m) => m.opponent).filter(Boolean));
    return {
      list, count: list.length, decided: decided.length, wins,
      losses: decided.length - wins,
      rate: decided.length ? wins / decided.length * 100 : null,
      at10Med: med('at10'), finalMed: med('finalDiff'),
      durAvg: avg(values('duration')),
      killAvg: avg(values('killMargin')),
      span: dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} → ${dates[dates.length - 1]}`) : '—',
      sessions: sessions.size, opponents: opponents.size,
    };
  }

  /* ── 图形：经济差迷你曲线（一局一条，不叠加） ─────────────────── */
  function spark(m, cls = '') {
    const pts = m.econ;
    if (!pts || pts.length < 2) return '<span class="cx-spark-none">—</span>';
    const W = 120, H = 34, PAD = 3;
    const vals = pts.map((p) => p[1]);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const span = hi - lo || 1;
    const spanT = Math.max(1, m.duration || pts[pts.length - 1][0]);
    const x = (t) => PAD + clamp(t / spanT, 0, 1) * (W - PAD * 2);
    const y = (v) => H - PAD - ((v - lo) / span) * (H - PAD * 2);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    const area = `${line} L${x(pts[pts.length - 1][0]).toFixed(1)},${y(0).toFixed(1)} L${x(pts[0][0]).toFixed(1)},${y(0).toFixed(1)} Z`;
    const tone = (num(m.finalDiff) && m.finalDiff < 0) ? 'loss' : 'win';
    const mark = m.duration > 600 ? `<line class="cx-spark-mark" x1="${x(600).toFixed(1)}" x2="${x(600).toFixed(1)}" y1="${PAD}" y2="${H - PAD}"/>` : '';
    return `<svg class="cx-spark ${tone} ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(m.date + ' 经济差走势')}">
      <line class="cx-spark-zero" x1="${PAD}" x2="${W - PAD}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>
      ${mark}<path class="cx-spark-area" d="${area}"/><path class="cx-spark-line" d="${line}"/>
    </svg>`;
  }

  /* ── 结论卡 ─────────────────────────────────────────────────── */
  /* 赛训组说「金币」，不说「金」 */
  const yuan = (t) => String(t == null ? '' : t).replace(/金(?!币)/g, '金币');

  function headline(a) {
    const n = a.count;
    const lead = num(a.at10Med) ? `${diff(Math.round(a.at10Med))} 金币` : null;
    let claim;
    if (a.decided >= 2 && a.rate === 100) claim = `${n} 局全胜，10 分钟中位领先 <em>${lead || '—'}</em>`;
    else if (a.decided >= 2) claim = `${n} 局 ${a.wins} 胜 ${a.losses} 负，10 分钟经济差 <em>${lead || '—'}</em>`;
    else claim = `${n} 局训练序列，10 分钟经济差 <em>${lead || '—'}</em>`;
    return claim;
  }

  function factLine(a) {
    const bits = [];
    if (num(a.durAvg)) bits.push(`平均 ${time(a.durAvg)} 结束`);
    if (num(a.killAvg)) bits.push(`场均净胜 ${fmt(a.killAvg, 1)} 个人头`);
    if (num(a.finalMed)) bits.push(`终局经济差典型 ${diff(Math.round(a.finalMed))} 金币`);
    bits.push(`本批 ${a.sessions} 个训练组`);
    return bits.join(' · ');
  }

  function heroCard(a, ordered, total) {
    const metrics = [
      ['10 分钟经济差', num(a.at10Med) ? diff(Math.round(a.at10Med)) : '—', `${a.list.filter((m) => num(m.at10)).length} 局可读`],
      ['终局经济差', num(a.finalMed) ? diff(Math.round(a.finalMed)) : '—', '本队减对手'],
      ['平均时长', num(a.durAvg) ? time(a.durAvg) : '—', '从开赛到结算'],
      ['场均人头差', num(a.killAvg) ? diff(Math.round(a.killAvg)) : '—', '十人结算面板'],
    ];
    /* 每局一格：一局点一下直接进那局复盘，不在这里做对照表 */
    const filmList = ordered.slice(0, 40);
    const film = filmList.map((m, i) => {
      const tone = m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : 'na';
      const label = `${m.date || ''} ${m.title || ''} · ${m.result === 'win' ? '胜' : m.result === 'loss' ? '负' : '未标胜负'}`;
      return `<a class="cx-film-cell ${tone}" href="#match/${encodeURIComponent(m.key)}" title="${esc(label)}">
        <span>${String(i + 1).padStart(2, '0')}</span>${spark(m)}</a>`;
    }).join('');
    const filmHint = total > filmList.length ? `先放 ${filmList.length} 格 / 共 ${fmt(total)} 局` : '点一格进那局复盘';
    const score = `${a.wins}<i>:</i>${a.losses}`;
    return `<header class="cx-hero">
      <div class="cx-hero-top">
        <div class="cx-kicker">这段时间 <span>/ 每局一格</span><small>${fmt(a.count)} 局 · ${esc(a.span)} · ${fmt(a.opponents)} 个对手</small></div>
        <div class="cx-hero-score"><b>${score}</b><small>胜 : 负${num(a.rate) ? ` · ${Math.round(a.rate)}% 胜率` : ''}</small></div>
      </div>
      <h1 class="cx-claim">${headline(a)}</h1>
      <p class="cx-fact">${esc(factLine(a))}</p>
      <div class="cx-hero-metrics">${metrics.map(([k, v, note]) => `<div class="cx-hm"><small>${k}</small><b>${esc(v)}</b><i>${esc(note)}</i></div>`).join('')}</div>
      <div class="cx-film"><span class="cx-film-label">逐局经济走势</span><div class="cx-film-cells">${film}</div><span class="cx-film-hint">${esc(filmHint)}</span></div>
      <p class="cx-hero-source">口径：王者营地面板经济采样（约 30 秒一点）与官方回放事件；经济差＝本队减对手。这一页全部结论都基于当前范围内的 ${fmt(a.count)} 局。</p>
    </header>`;
  }

  /* ── 范围条：版本 / 训练组 / 对手 / 胜负 + 一句样本说明 ───────── */
  function scopeBar(allRows, a, meta, options) {
    const { versions = [], sessions = [], opponents = [] } = options || {};
    const active = !!(sliceVersion || sliceSession || filterOpp || filterResult);
    const sel = (key, label, list, value) => `<label class="cx-select cx-filter"><span>${label}</span><select data-cx-filter="${key}">
      <option value="">全部</option>${list.map((v) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
    const widthNote = meta.total > allRows.length
      ? `共 ${fmt(meta.total)} 局，这一页按最近 ${fmt(allRows.length)} 局算`
      : `共 ${fmt(meta.total)} 局`;
    return `<div class="cx-toolbar">
      <div class="cx-lede"><b>当前范围 ${fmt(a.count)} 局</b><span>${esc(widthNote)} · 下面所有结论都按这个范围重算</span></div>
      <div class="cx-controls">
        <input class="cx-search" type="search" data-cx-opp value="${esc(filterOpp)}" placeholder="搜对手 / 日期" aria-label="搜索对局">
        ${sel('version', '版本', versions, sliceVersion)}
        ${sel('session', '训练组', sessions, sliceSession)}
        ${sel('opponent', '对手', opponents, filterOpp)}
        <label class="cx-select cx-filter"><span>胜负</span><select data-cx-filter="result">
          <option value="">全部</option>
          <option value="win"${filterResult === 'win' ? ' selected' : ''}>只看胜</option>
          <option value="loss"${filterResult === 'loss' ? ' selected' : ''}>只看负</option>
        </select></label>
        ${active ? '<button type="button" class="cx-filter-clear" data-cx-clear-filters>清除筛选</button>' : ''}
      </div>
    </div>`;
  }

  /* 逐局对照台已按赛训组反馈移除：一局一局的对照交给单局复盘，
     跨局这一页只留结论卡与「按钮展开的局列表」。 */

  /* ── 参照栏：跨局数字只出现在这里 ───────────────────────────── */
  /* ── 分路对位：体素板 ───────────────────────────────────────── */
  function laneBoard(list) {
    const cols = [['gold', '分均经济差'], ['damage', '分均输出差'], ['taken', '分均承伤差']];
    const rows = LANES.map((lane) => {
      const vals = cols.map(([key]) => {
        const arr = list.map((m) => (m.laneDiff[lane] || {})[key]).filter(num);
        return arr.length ? avg(arr) : null;
      });
      return { lane, vals };
    });
    /* 每列单独定标：输出差是万级、经济差是百级，共用一个峰值会让前两列全是一格 */
    const peaks = cols.map((_, ci) => Math.max(1, ...rows.map((r) => Math.abs(r.vals[ci] || 0)).filter(num)));
    const cells = rows.map((r) => `<div class="cx-lane-row"><span class="cx-lane-name">${esc(r.lane)}</span>${r.vals.map((v, ci) => {
      if (!num(v)) return '<div class="cx-cell none"><b>—</b><div class="cx-vox"></div></div>';
      const tone = v >= 0 ? 'pos' : 'neg';
      const blocks = clamp(Math.ceil(Math.abs(v) / peaks[ci] * 8), 1, 8);
      const vox = Array.from({ length: 8 }, (_, i) => `<i class="${i < blocks ? 'on' : ''}"></i>`).join('');
      return `<div class="cx-cell ${tone}"><b>${diff(Math.round(v))}</b><div class="cx-vox">${vox}</div></div>`;
    }).join('')}</div>`).join('');
    return `<section class="cx-lanes">
      <div class="cx-lanes-head"><div><h2>分路对位</h2><p>五个位置在 ${fmt(list.length)} 局里的平均分差；一格一个数字，方块数＝差距大小。</p></div>
        <div class="cx-lanes-legend"><span class="pos">本队高</span><span class="neg">对手高</span></div></div>
      <div class="cx-lanes-grid"><div class="cx-lane-row cx-lane-head"><span>位置</span>${cols.map(([, label]) => `<span>${label}</span>`).join('')}</div>${cells}</div>
      <p class="cx-lanes-note">口径：同分路本队减对手，按局时长折算为每分钟；正数＝本队高。数据来自十人结算面板。</p>
    </section>`;
  }

  /* ── 挖掘：这批局真正能说出来的结论 ─────────────────────────── */
  /* ── 通用跨局分析区 ─────────────────────────────────────────────
     结论的输入是「全部对局的轻量向量」，不是当前分页窗口，也不是挑出来的一局。
     每张卡固定四层：人话结论 → 一张能看懂的图 → 训练安排 + 圈定动作 → 统计口径。
     图的元素数恒定，与局数无关。 */
  const cardActions = new Map();
  const snum = (v) => (v >= 0 ? '+' : '−') + Math.round(Math.abs(num(v) ? v : 0)).toLocaleString('zh-CN');
  const pnum = (v) => `${Math.round((num(v) ? v : 0) * 100)}%`;
  const tone = (v) => (num(v) && v < 0 ? 'neg' : 'pos');
  const barW = (v, max) => `${clamp(Math.abs(num(v) ? v : 0) / Math.max(1, max) * 100, 2, 100).toFixed(1)}%`;

  /* ── 高级可视化（白底）──────────────────────────────────────────
     每张分析两块可切换视图；所有图形元素可悬停读数、可点选圈定对应局；
     视图切换与数据重算都带过渡动画。图元素数量恒定，与局数无关。 */
  const vizViews = {};
  let vizRows = [];
  const VIZ_META = {
    '01': ['典型水平', '按对手看'], '02': ['差别来自哪', '排个序'],
    '03': ['最差的10%对局', '落后的局'], '04': ['一段段看', '差距稳不稳'],
    '05': ['走势', '每段时间'], '06': ['几套打法', '哪套最稳'],
    '07': ['打谁用哪套', '排个序'], '08': ['赢在哪段', '赢在哪路'],
    '09': ['领先守得住吗', '各状态局数'], '10': ['先看哪类', '各类多少局'],
  };
  const HUMAN = {
    '同条件下的自然波动': '同一批对手里的起伏', '阵营': '蓝红方差别',
    '版本': '换了版本', '对手': '换了对手', '训练组': '换了训练组',
  };
  const humanLabel = (v) => HUMAN[v] || v;
  const coachMethod = (text) => String(text == null ? '' : text)
    .replace(/P10\/P25\/P50\/P75\/P90/g, '最好 / 最差各一成的局与典型水平')
    .replace(/σ²_组间 \/ \(σ²_组间 \+ σ²_组内\)/g, '按组拆开算波动')
    .replace(/单因素随机效应方差成分/g, '把波动按来源拆开')
    .replace(/方差成分/g, '波动来源')
    .replace(/95% 置信区间/g, '可信范围')
    .replace(/Cliff's δ/g, '两组差距')
    .replace(/固定种子 bootstrap/g, '反复抽样')
    .replace(/bootstrap/g, '反复抽样')
    .replace(/CUSUM/g, '累计偏移')
    .replace(/MAD 稳健标准化/g, '按典型波动做标准化')
    .replace(/MAD/g, '稳健')
    .replace(/k-means/g, '轨迹分型')
    .replace(/轮廓系数/g, '分型质量')
    .replace(/Wilson 95% CI/g, '比例的可信范围')
    .replace(/Wilson/g, '比例区间')
    .replace(/CVaR/g, '最差情形')
    .replace(/分位数/g, '按局排序后的档位')
    .replace(/爆雷率/g, '落后的局占比')
    .replace(/中位(数)?/g, '典型水平')
    .replace(/P10/g, '最差的10%对局').replace(/P25/g, '偏低的四分之一')
    .replace(/P50/g, '典型水平').replace(/P75/g, '偏高的四分之一').replace(/P90/g, '最好的10%对局')
    .replace(/10′/g, '10 分钟');
  const aesc = (v) => esc(String(v == null ? '' : v));
  const tipAttr = (text) => `data-cx-tip="${aesc(text)}"`;
  const selAttr = (sel) => `data-cx-sel="${aesc(sel || '')}"`;
  const vgrid = (x0, x1, y0, y1, n = 4) => Array.from({ length: n }, (_, i) => {
    const y = (y0 + (y1 - y0) * i / (n - 1)).toFixed(1);
    return `<line class="cx-vgrid" x1="${x0}" x2="${x1}" y1="${y}" y2="${y}"/>`;
  }).join('');
  const vbar = (label, value, width, cls, tipText, sel) => `<div class="cx-vb" ${tipAttr(tipText)} ${selAttr(sel)}>
    <span>${aesc(label)}</span><i><b class="${cls || ''}" style="width:${width}"></b></i><em>${aesc(value)}</em></div>`;
  const vsize = (arr, get, fallback = 1) => Math.max(fallback, ...arr.map((x) => Math.abs(num(get(x)) ? get(x) : 0)));

  function switchViz(id, key) {
    vizViews[id] = key;
    const wrap = [...document.querySelectorAll('[data-cx-viz]')].find((el) => el.dataset.cxViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-cx-view-btn]').forEach((b) => b.classList.toggle('is-on', b.dataset.cxViewBtn === key));
    wrap.querySelectorAll('.cx-view').forEach((v) => {
      const on = v.dataset.cxView === key;
      v.hidden = !on;
      v.classList.remove('is-enter');
      if (on) { void v.offsetWidth; v.classList.add('is-enter'); }
    });
  }

  function showVizTip(target, event) {
    const wrap = target.closest('[data-cx-viz]');
    if (!wrap) return;
    const tip = wrap.querySelector('.cx-viz-tip');
    if (!tip) return;
    tip.textContent = target.dataset.cxTip || '';
    tip.hidden = false;
    const box = wrap.querySelector('.cx-viz-stage').getBoundingClientRect();
    const x = clamp(event.clientX - box.left + 12, 8, Math.max(8, box.width - 230));
    const y = clamp(event.clientY - box.top - 34, 6, Math.max(6, box.height - 40));
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }
  function hideVizTips() {
    document.querySelectorAll('.cx-viz-tip').forEach((t) => { t.hidden = true; });
  }

  /* ── 页签：按赛训组的问法分四块 ─────────────────────────────── */
  const CARD_NAMES = {
    '01': '共性', '02': '赢的局和输的局差在哪', '03': '哪条路最容易崩',
    '04': '突出点', '05': '异常点', '06': '我们练的几套打法',
    '07': '这套打谁更划算', '08': '优势是哪一段挣来的', '09': '领先以后守得住吗',
    '10': '明天先看哪几局', '11': '英雄账本', '12': '对手账本',
    '13': '资源与推塔', '14': '死亡与团战', '15': '切 C 与首杀', '16': '英雄组合', '17': '团战账本', '18': '打野节奏',
    '19': '选手榜', '20': '位置对位', '21': '团战伤害结构', '22': '优势兑现', '23': '对手阵容',
  };
  const TABS = [
    { key: 'trend', label: '这段时间', note: '变好还是变差', ids: ['01', '02', '08', '04', '05'],
      lede: '把这一个月的局并在一起看三件事：反复出现的（共性）、最顺和最难的（突出）、过程和结果对不上的（异常）。' },
    { key: 'bp', label: 'BP 与阵容', note: '下一场怎么选', ids: ['11', '16', '06', '07'],
      lede: '把「选过的英雄、两人一起上最稳的组合、打过的几套阵容、这套打谁划算」攒成一本账，赛前直接翻。' },
    { key: 'lanes', label: '五路与人', note: '谁该练什么', ids: ['03', '20', '09', '19'],
      lede: '五条路分开看：同位置对位谁占优、哪条路的下限最低、领先守不守得住、谁死得最多。' },
    { key: 'res', label: '资源与团战', note: '龙、塔、团战', ids: ['13', '14', '15', '17', '18', '21', '22'],
      lede: '龙和塔控不控得住、每局死几次、团战赢几波、抓不抓得到对方后排、打野在不在对方半区、团战里谁在打谁在扛、领先之后换成了什么。' },
    { key: 'opponents', label: '对手', note: '下次打谁怎么打', ids: ['12', '23'],
      lede: '同一个对手打得多了，就能看出他们的惯用打法和常用组合，以及我们一贯吃亏的地方。' },
  ];

  /* ── 结论卡：一句人话 + 一张图 + 按钮展开的局列表 ─────────────── */
  function cardHtml(c, rowIndex) {
    const name = CARD_NAMES[c.id] || c.name || '';
    const covered = Number((c.grade && c.grade.n) || 0);
    const insufficient = covered < 2;
    const keys = (c.actKeys || []).filter(Boolean);
    const listHtml = keys.slice(0, 80).map((key) => {
      const v = rowIndex.get(key) || {};
      const res = v.result === 'win' ? 'win' : v.result === 'loss' ? 'loss' : 'na';
      const read = num(v.at10) ? `10 分钟 ${diff(Math.round(v.at10))} 金币`
        : num(v.finalDiff) ? `终局 ${diff(Math.round(v.finalDiff))} 金币` : '—';
      return `<a class="cx-act-row" href="#match/${encodeURIComponent(key)}">
        <span class="cx-act-date">${esc(String(v.date || '—').slice(5) || '—')}</span>
        <span class="cx-act-opp">${esc(v.opponent || '未填对手')}</span>
        <span class="cx-act-res ${res}">${res === 'win' ? '胜' : res === 'loss' ? '负' : '—'}</span>
        <span class="cx-act-read">${esc(read)}</span>
        <span class="cx-act-go">→</span>
      </a>`;
    }).join('');
    const more = keys.length > 80 ? '<p class="cx-act-more">只列前 80 局，整批请用下面的导出。</p>' : '';
    return `<article class="cx-find cx-cf" id="cx-analysis-${aesc(c.id)}">
      <div class="cx-cf-top"><span class="cx-find-kicker">${esc(name)}</span><span class="cx-find-sample">覆盖 ${covered} 局</span></div>
      ${insufficient
        ? '<h3 class="cx-cf-title cx-cf-title-muted">先攒够 2 局可用样本，再看这项结论</h3>'
        : `<h3 class="cx-cf-title">${yuan(c.title)}</h3>`}
      <div class="cx-cf-canvas">${insufficient
        ? `<div class="cx-cf-insufficient"><b>样本不足</b><p>这个分析至少需要 2 局可用样本，当前覆盖 ${covered} 局。先把对局补全（或在「采集」补挂官方回放），再看这项结论。</p></div>`
        : renderViz(c.chart, c, { rows: vizRows, view: (id) => vizViews[id] || 'a' })}</div>
      ${insufficient ? '' : `<p class="cx-cf-plain">${esc(yuan(c.plain || ''))}</p>`}
      <div class="cx-cf-foot">
        ${insufficient ? '' : `<div class="cx-cf-train"><span>怎么用</span><p>${esc(yuan(c.train))}</p></div>`}
        ${keys.length ? `<button type="button" class="cx-act-btn" data-cx-act="${aesc(c.id)}" aria-expanded="false" aria-controls="cx-act-list-${aesc(c.id)}">看这 ${keys.length} 局 <span>↓</span></button>` : ''}
      </div>
      ${keys.length ? `<div class="cx-act-list" id="cx-act-list-${aesc(c.id)}" data-cx-act-list="${aesc(c.id)}" hidden>
        ${listHtml}${more}
        <button type="button" class="cx-act-export" data-cx-export-keys="${aesc(c.id)}">导出这 ${keys.length} 局 CSV</button>
      </div>` : ''}
      <p class="cx-cf-method"><b>怎么算的</b> ${esc(yuan(coachMethod(c.method)))}</p>
    </article>`;
  }

  function tabsHtml(active) {
    return `<div class="md-tabs cx-tabs" role="tablist" aria-label="跨局分析页签">
      ${TABS.map((t) => `<button type="button" class="md-tab" data-cx-tab="${t.key}" role="tab" aria-selected="${t.key === active}">
        <b>${esc(t.label)}</b><small>${esc(t.note)}</small></button>`).join('')}
    </div>`;
  }

  function paneHtml(tab, cards, rowIndex, active, laneHtml) {
    const list = tab.ids.map((id) => cards.get(id)).filter(Boolean);
    const body = list.length ? `<div class="cx-finds-grid">${list.map((c) => cardHtml(c, rowIndex)).join('')}</div>` : '';
    return `<div class="cx-pane" data-cx-pane="${tab.key}"${tab.key === active ? '' : ' hidden'}>
      <p class="cx-pane-lede">${esc(tab.lede)}</p>${body}${tab.key === 'lanes' ? laneHtml : ''}
    </div>`;
  }


  /* ── 页面 ───────────────────────────────────────────────────── */
  function sortList(list) {
    const copy = list.slice();
    if (sortKey === 'date') copy.sort((x, y) => String(y.date).localeCompare(String(x.date)) || String(y.key).localeCompare(String(x.key)));
    else copy.sort((x, y) => (num(y[sortKey]) ? y[sortKey] : -Infinity) - (num(x[sortKey]) ? x[sortKey] : -Infinity));
    return copy;
  }

  /* 分析范围：版本 / 训练组 / 结果 / 关键词。结论一律按这个范围的全量算 */
  function scopedRows(allRows) {
    const q = filterOpp.trim().toLowerCase();
    return allRows.filter((r) => {
      if (sliceVersion && (r.version || '') !== sliceVersion) return false;
      if (sliceSession && (r.session || '') !== sliceSession) return false;
      if (filterResult && r.result !== filterResult) return false;
      if (q) {
        const hay = `${r.opponent || ''} ${(r.detail && r.detail.title) || ''} ${r.date || ''} ${r.session || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function filterVectors(vec) {
    const q = filterOpp.trim().toLowerCase();
    return (vec || []).filter((v) => {
      if (sliceVersion && (v.version || '') !== sliceVersion) return false;
      if (sliceSession && (v.session || '') !== sliceSession) return false;
      if (filterResult && v.result !== filterResult) return false;
      if (q && !`${v.opponent || ''} ${v.date || ''} ${v.session || ''}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  /* 页签存在地址里：#cross/<tab>，刷新与分享都停在原页 */
  function activeTab() {
    const parts = String(location.hash || '').replace(/^#/, '').split('?')[0].split('/');
    const key = parts[0] === 'cross' ? parts[1] : parts[2];
    return TABS.some((t) => t.key === key) ? key : 'trend';
  }

  function render(allRows, meta = {}) {
    if (!allRows || !allRows.length) {
      return '<div class="page cx-page"><section class="section cx-blank"><h1>还没有已确认的对局</h1><p>先到「对局档案」完成一局归档，跨局对照会自动排开。</p><a class="primary" href="#matches">去对局档案 →</a></section></div>';
    }
    lastRows = allRows;
    lastMeta = {
      total: num(meta.total) ? meta.total : allRows.length,
      limit: num(meta.limit) ? meta.limit : allRows.length,
      cohort: meta.cohort || lastMeta.cohort || null,
    };
    let rows = scopedRows(allRows);
    if (!rows.length && (sliceVersion || sliceSession)) {
      /* 换了一批数据、旧切片失效时回到全量，但不抹掉用户主动的搜索 */
      sliceVersion = '';
      sliceSession = '';
      rows = scopedRows(allRows);
    }
    if (!rows.length) {
      return '<div class="page cx-page"><section class="section cx-blank"><h1>当前范围没有对局</h1><p>换一个对手、版本或胜负，全部结论会按新范围重算。</p><button type="button" class="primary" data-cx-clear>清除筛选 →</button></section></div>';
    }
    const list = rows.map(buildMatch);
    const a = summarize(list);
    const ordered = sortList(list);
    const vectors = filterVectors((lastMeta.cohort && lastMeta.cohort.vectors) || []);
    vizRows = vectors;
    const result = analyzeCohort(vectors);
    const rowIndex = new Map(vectors.map((v) => [v.key, v]));
    const cards = new Map();
    for (const c of result.cards) cards.set(c.id, c);
    lastCards = cards;
    lastRowIndex = rowIndex;
    const uniq = (key, cap) => [...new Set(vectors.map((v) => String(v[key] || '').trim()).filter(Boolean))].sort().slice(0, cap);
    const tab = activeTab();
    const lanes = laneBoard(list);
    return `<div class="page cx-page" data-cx-tab-active="${tab}">
      ${heroCard(a, ordered, ordered.length)}
      ${tabsHtml(tab)}
      ${scopeBar(allRows, a, lastMeta, { versions: uniq('version', 30), sessions: uniq('session', 30), opponents: uniq('opponent', 50) })}
      ${TABS.map((t) => paneHtml(t, cards, rowIndex, tab, lanes)).join('')}
      <p class="cx-source">数据来源：王者营地面板（十人结算 / 经济采样）、官方回放事件与逐秒位置。经济差一律为本队减对手，负数是落后。</p>
    </div>`;
  }

  /* ── 交互 ───────────────────────────────────────────────────── */
  function rerender() {
    const host = document.querySelector('#content');
    if (host && lastRows.length) host.innerHTML = render(lastRows, lastMeta);
  }

  /* 导出范围跟着按钮走：卡片展开的那几十局，就是导出的那几十局 */
  function exportCsv(id) {
    const keys = (lastCards.get(id) || []).filter(Boolean);
    if (!keys.length) return;
    const head = ['日期', '对手', '胜负', '时长(秒)', '10分钟经济差', '终局经济差'];
    const lines = [head.join(',')];
    keys.forEach((key) => {
      const v = lastRowIndex.get(key) || {};
      const cells = [v.date || '', v.opponent || '',
        v.result === 'win' ? '胜' : v.result === 'loss' ? '负' : '',
        num(v.duration) ? Math.round(v.duration) : '',
        num(v.at10) ? Math.round(v.at10) : '',
        num(v.finalDiff) ? Math.round(v.finalDiff) : ''];
      lines.push(cells.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(','));
    });
    const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '跨局分析-这批局.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function bind(root) {
    if (bind.done) return;
    bind.done = true;
    root.addEventListener('click', (event) => {
      if (!event.target.closest) return;
      /* 局列表整行是链接，交给路由处理 */
      if (event.target.closest('.cx-open') || event.target.closest('.cx-act-row')) return;
      const tabBtn = event.target.closest('[data-cx-tab]');
      if (tabBtn) {
        const page = tabBtn.closest('.cx-page');
        const key = tabBtn.dataset.cxTab;
        if (!page || !key) return;
        page.dataset.cxTabActive = key;
        page.querySelectorAll('[data-cx-tab]').forEach((n) => n.setAttribute('aria-selected', String(n.dataset.cxTab === key)));
        page.querySelectorAll('[data-cx-pane]').forEach((p) => { p.hidden = p.dataset.cxPane !== key; });
        try { history.replaceState(null, '', `#cross/${key}`); } catch { /* 嵌入式浏览器禁 replaceState，忽略 */ }
        const tabs = page.querySelector('.cx-tabs');
        if (tabs) tabs.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return;
      }
      const actBtn = event.target.closest('[data-cx-act]');
      if (actBtn) {
        const id = actBtn.dataset.cxAct;
        const list = document.querySelector(`[data-cx-act-list="${CSS.escape(id)}"]`);
        if (!list) return;
        const open = list.hidden;
        list.hidden = !open;
        actBtn.setAttribute('aria-expanded', String(open));
        actBtn.innerHTML = actBtn.innerHTML.replace(open ? '↓' : '↑', open ? '↑' : '↓');
        return;
      }
      const exportBtn = event.target.closest('[data-cx-export-keys]');
      if (exportBtn) { exportCsv(exportBtn.dataset.cxExportKeys); return; }
      const viewBtn = event.target.closest('[data-cx-view-btn]');
      if (viewBtn) { switchViz(viewBtn.dataset.cxVizId, viewBtn.dataset.cxViewBtn); return; }
      if (event.target.closest('[data-cx-clear-filters]') || event.target.closest('[data-cx-clear]')) {
        filterResult = ''; filterOpp = ''; sliceVersion = ''; sliceSession = '';
        rerender(); return;
      }
    });
    root.addEventListener('mousemove', (event) => {
      const t = event.target.closest ? event.target.closest('[data-cx-tip]') : null;
      if (t) showVizTip(t, event); else hideVizTips();
    });
    root.addEventListener('mouseleave', hideVizTips);
    root.addEventListener('change', (event) => {
      const node = event.target.closest ? event.target.closest('[data-cx-opp],[data-cx-filter]') : null;
      if (!node) return;
      if (node.dataset.cxFilter) {
        const key = node.dataset.cxFilter, value = node.value;
        if (key === 'version') sliceVersion = value;
        else if (key === 'session') sliceSession = value;
        else if (key === 'opponent') filterOpp = value;
        else if (key === 'result') filterResult = value;
        rerender(); return;
      }
      filterOpp = node.value;
      rerender();
    });
  }

  return { render, bind };
}
