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
  let focusKey = '';
  let sortKey = 'date';
  let sliceSession = '';
  let sliceVersion = '';
  let filterResult = '';
  let filterOpp = '';
  let pageSize = 20;
  let page = 0;
  let lastRows = [];
  let lastMeta = { total: 0, limit: 200 };
  let lastView = null;
  let scopeKeys = null;

  const heroIcon = (name, cls = '') => {
    if (!name) return '<span class="cx-portrait-blank">?</span>';
    const html = portrait
      ? portrait(name, cls)
      : `<span class="portrait portrait-placeholder ${cls}">${esc(name.slice(0, 1))}</span>`;
    return html.replace('loading="lazy"', 'loading="eager"');
  };

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

  const RANK_KEYS = ['finalDiff', 'at10', 'killMargin', 'duration', 'frontEnd', 'fights'];

  function summarize(list) {
    const decided = list.filter((m) => m.result === 'win' || m.result === 'loss');
    const wins = decided.filter((m) => m.result === 'win').length;
    const values = (key) => list.map((m) => m[key]).filter(num).sort((a, b) => a - b);
    const med = (key) => median(values(key));
    const dates = list.map((m) => m.date).filter(Boolean).sort();
    const sessions = new Set(list.map((m) => m.session).filter(Boolean));
    const opponents = new Set(list.map((m) => m.opponent).filter(Boolean));
    /* 排名用预排序数组 + 二分，逐局渲染不再 O(N²) */
    const rankIndex = {};
    for (const key of RANK_KEYS) rankIndex[key] = values(key);
    return {
      list, count: list.length, decided: decided.length, wins,
      losses: decided.length - wins,
      rate: decided.length ? wins / decided.length * 100 : null,
      at10Med: med('at10'), finalMed: med('finalDiff'),
      durAvg: avg(values('duration')),
      killAvg: avg(values('killMargin')),
      span: dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} → ${dates[dates.length - 1]}`) : '—',
      sessions: sessions.size, opponents: opponents.size, rankIndex,
    };
  }

  function rankOf(a, key, value) {
    if (!num(value)) return null;
    const vals = a.rankIndex[key] || [];
    if (!vals.length) return null;
    let lo = 0, hi = vals.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (vals[mid] <= value) lo = mid + 1;
      else hi = mid;
    }
    return { rank: vals.length - lo + 1, total: vals.length };
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
  function headline(a) {
    const n = a.count;
    const lead = num(a.at10Med) ? `${diff(Math.round(a.at10Med))} 金` : null;
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
    if (num(a.finalMed)) bits.push(`终局经济差中位 ${diff(Math.round(a.finalMed))} 金`);
    bits.push(`本批 ${a.sessions} 个训练组`);
    return bits.join(' · ');
  }

  function heroCard(a, visible, total) {
    const metrics = [
      ['10′ 经济差', num(a.at10Med) ? diff(Math.round(a.at10Med)) : '—', `${a.list.filter((m) => num(m.at10)).length} 局可读`],
      ['终局经济差中位', num(a.finalMed) ? diff(Math.round(a.finalMed)) : '—', '本队 − 对手'],
      ['平均时长', num(a.durAvg) ? time(a.durAvg) : '—', '从开赛到结算'],
      ['场均人头差', num(a.killAvg) ? diff(Math.round(a.killAvg)) : '—', '十人结算面板'],
    ];
    /* 缩略带只承担一个可视窗口：当前页前 24 格，横向滚动，不随 N 局撑爆 */
    const filmList = visible.slice(0, 24);
    const film = filmList.map((m, i) => {
      const tone = m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : 'na';
      return `<button type="button" class="cx-film-cell ${tone}${m.key === focusKey ? ' is-focus' : ''}" data-cx-focus="${esc(m.key)}" title="${esc(`${m.date || ''} ${m.title} · ${m.result === 'win' ? '胜' : m.result === 'loss' ? '负' : '未标注'}`)}">
        <span>${String(i + 1).padStart(2, '0')}</span>${spark(m)}</button>`;
    }).join('');
    const filmHint = total > filmList.length ? `本页 ${filmList.length} 格 / 共 ${fmt(total)} 局` : '点一格聚焦';
    const score = `${a.wins}<i>:</i>${a.losses}`;
    return `<header class="cx-hero">
      <div class="cx-hero-top">
        <div class="cx-kicker">训练序列 <span>/ 逐局对照</span><small>${fmt(a.count)} 局 · ${esc(a.span)} · ${fmt(a.opponents)} 个对手</small></div>
        <div class="cx-hero-score"><b>${score}</b><small>胜 : 负${num(a.rate) ? ` · ${Math.round(a.rate)}% 胜率` : ''}</small></div>
      </div>
      <h1 class="cx-claim">${headline(a)}</h1>
      <p class="cx-fact">${esc(factLine(a))}</p>
      <div class="cx-hero-metrics">${metrics.map(([k, v, note]) => `<div class="cx-hm"><small>${k}</small><b>${esc(v)}</b><i>${esc(note)}</i></div>`).join('')}</div>
      <div class="cx-film"><span class="cx-film-label">逐局经济走势</span><div class="cx-film-cells">${film}</div><span class="cx-film-hint">${esc(filmHint)}</span></div>
      <p class="cx-hero-source">口径：王者营地面板经济采样（约 30 秒一点）与官方回放事件；经济差＝本队减对手。本页全部结论基于当前范围内的 ${fmt(a.count)} 局。</p>
    </header>`;
  }

  /* ── 工具行：范围、筛选、排序、每页条数 ─────────────────────── */
  function toolbar(allRows, a, meta) {
    const widthNote = meta.total > allRows.length
      ? `共 ${fmt(meta.total)} 局，分析窗口取最近 ${fmt(allRows.length)} 局`
      : `共 ${fmt(meta.total)} 局`;
    return `<div class="cx-toolbar">
      <div class="cx-lede"><b>当前范围 ${fmt(a.count)} 局</b><span>${esc(widthNote)} · 一局一块，一块一行</span></div>
      <div class="cx-controls">
        <input class="cx-search" type="search" data-cx-opp value="${esc(filterOpp)}" placeholder="搜对手 / 标题 / 日期" aria-label="搜索对局">
        <label class="cx-select"><span>排序</span><select data-cx-sort>
          <option value="date"${sortKey === 'date' ? ' selected' : ''}>按时间</option>
          <option value="finalDiff"${sortKey === 'finalDiff' ? ' selected' : ''}>按终局经济差</option>
          <option value="at10"${sortKey === 'at10' ? ' selected' : ''}>按 10′ 经济差</option>
          <option value="duration"${sortKey === 'duration' ? ' selected' : ''}>按时长</option>
        </select></label>
        <label class="cx-select"><span>每页</span><select data-cx-page-size>
          <option value="20"${pageSize === 20 ? ' selected' : ''}>20 局</option>
          <option value="50"${pageSize === 50 ? ' selected' : ''}>50 局</option>
          <option value="0"${pageSize === 0 ? ' selected' : ''}>全部</option>
        </select></label>
        <button type="button" class="cx-export" data-cx-export>导出 CSV</button>
      </div>
    </div>`;
  }

  /* ── 对照台：一行一局 ───────────────────────────────────────── */
  function rowHtml(m, i, a) {
    const tone = m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : 'na';
    const rank = rankOf(a, 'finalDiff', m.finalDiff);
    const lineup = m.lineup.slice(0, 5).map((p) => `<span class="cx-lineup-item" title="${esc(`${p.position || ''} ${p.label || ''} ${p.hero || ''}`)}">${heroIcon(p.hero, 'cx-portrait')}</span>`).join('');
    const bits = [`${m.fights} 次团战`, `本队 ${m.deathsOwn} / 对手 ${m.deathsFoe} 次阵亡`];
    if (num(m.frontEnd)) bits.push(`阵线终值 ${Math.round(m.frontEnd * 100)}%`);
    if (m.mvp && m.mvp.hero) bits.push(`最高经济 ${m.mvp.hero}`);
    const story = bits.join(' · ');
    return `<div class="cx-row${m.key === focusKey ? ' is-focus' : ''}" data-cx-row="${esc(m.key)}" data-cx-focus="${esc(m.key)}">
      <span class="cx-num">${String(i + 1).padStart(2, '0')}</span>
      <span class="cx-match"><b>${esc(m.title)}</b><small>${esc(m.date || '—')} · ${esc(m.session || '训练赛')} · ${m.ownCamp === 'blue' ? '蓝方' : '红方'}</small></span>
      <span class="cx-score ${tone}"><b>${num(m.ownKills) ? fmt(m.ownKills) : '—'}</b><i>:</i><b>${num(m.foeKills) ? fmt(m.foeKills) : '—'}</b><small>${tone === 'win' ? '胜' : tone === 'loss' ? '负' : '—'}</small></span>
      <span class="cx-dur">${time(m.duration)}</span>
      <span class="cx-curve">${spark(m)}</span>
      <span class="cx-check"><small>10′</small><b class="${num(m.at10) && m.at10 >= 0 ? 'pos' : 'neg'}">${num(m.at10) ? diff(Math.round(m.at10)) : '—'}</b></span>
      <span class="cx-check"><small>终局</small><b class="${num(m.finalDiff) && m.finalDiff >= 0 ? 'pos' : 'neg'}">${num(m.finalDiff) ? diff(Math.round(m.finalDiff)) : '—'}</b></span>
      <span class="cx-rank">${rank ? `<b>${rank.rank}</b><small>/ ${rank.total} 局</small>` : '<b>—</b><small>—</small>'}</span>
      <span class="cx-lineup">${lineup}</span>
      <a class="cx-open" href="#match/${encodeURIComponent(m.key)}" aria-label="复盘这一局">→</a>
      <span class="cx-story">${esc(story)}</span>
    </div>`;
  }

  function boardHtml(ordered, a, visible, offset, pages) {
    const head = `<div class="cx-row cx-head"><span>编号</span><span>对局</span><span>比分</span><span>时长</span><span>经济差走势</span><span>10′</span><span>终局经济差</span><span>本批位次</span><span>本队阵容</span><span></span></div>`;
    const pager = pages > 1
      ? `<div class="cx-pager">
          <button type="button" class="cx-page-btn" data-cx-page="prev"${page === 0 ? ' disabled' : ''}>← 上一页</button>
          <span>第 <b>${page + 1}</b> / ${pages} 页 · 本页 ${visible.length} 局 · 共 ${fmt(ordered.length)} 局</span>
          <button type="button" class="cx-page-btn" data-cx-page="next"${page >= pages - 1 ? ' disabled' : ''}>下一页 →</button>
        </div>`
      : `<div class="cx-pager"><span>共 ${fmt(ordered.length)} 局，已全部列出</span></div>`;
    return `<section class="cx-board">
      <div class="cx-board-head"><h2>逐局对照</h2><p>一局一块、一块一行；点一块设为聚焦，下方参照块跟着变，点箭头进入这一局复盘。</p></div>
      <div class="cx-rows">${head}${visible.map((m, i) => rowHtml(m, offset + i, a)).join('')}</div>
      ${pager}
    </section>`;
  }

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

  /* 点选图形元素 → 圈定对应的一批局；sel 是紧凑语义描述，不随局数膨胀 */
  function probeKeys(sel, vectors) {
    const bits = String(sel || '').split(':');
    const kind = bits[0];
    const take = (arr, n = 60) => arr.slice(0, n).map((v) => v.key).filter(Boolean);
    const byValue = (get, desc = true) => vectors.slice().filter((v) => num(get(v)))
      .sort((a, b) => desc ? get(b) - get(a) : get(a) - get(b));
    const timed = () => vectors.slice().sort((a, b) => String(a.order || '') < String(b.order || '') ? -1 : 1);
    switch (kind) {
      case 'band': { const lo = Number(bits[1]), hi = Number(bits[2]); return take(vectors.filter((v) => num(v.at10) && v.at10 >= lo && v.at10 <= hi)); }
      case 'val': { const dim = bits[1], value = bits.slice(2).join(':'); return take(vectors.filter((v) => String(v[dim] || '未标注') === value)); }
      case 'dim': { const label = bits[1] || ''; const dim = label.indexOf('对手') >= 0 ? 'opponent' : label.indexOf('训练') >= 0 ? 'session' : 'version'; const counts = new Map(); for (const v of vectors) { const k = String(v[dim] || '未标注'); counts.set(k, (counts.get(k) || 0) + 1); } const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]; return top ? take(vectors.filter((v) => String(v[dim] || '未标注') === top[0])) : []; }
      case 'lane': { const name = bits[1]; return take(byValue((v) => v.lanes && v.lanes[name] ? v.lanes[name].gold : null, false)); }
      case 'win': { const k = Number(bits[1]); return take(byValue((v) => v.w && v.w[k])); }
      case 'seg': case 'bucket': { const i = Number(bits[1]), n = kind === 'seg' ? 6 : 24; const t = timed(); const start = Math.floor(i * t.length / n), end = kind === 'seg' ? Math.floor((i + 1) * t.length / n) : start + Math.max(1, Math.ceil(t.length / n)); return take(t.slice(start, end)); }
      case 'sys': { const i = Number(bits[1]); const ats = vectors.map((v) => v.at10).filter(num).sort((a, b) => a - b); const cut = ats[Math.floor(ats.length / 2)] || 0; return take(vectors.filter((v) => num(v.at10) && (i % 2 === 0 ? v.at10 >= cut : v.at10 < cut))); }
      case 'state': { const i = Number(bits[1]); const ats = vectors.map((v) => v.at10).filter(num).sort((a, b) => a - b); const q = (p) => ats[Math.floor((ats.length - 1) * p)] || 0; const q1 = q(.25), q2 = q(.5), q3 = q(.75); return take(vectors.filter((v) => num(v.at10) && (i === 0 ? v.at10 <= q1 : i === 1 ? v.at10 > q1 && v.at10 <= q2 : i === 2 ? v.at10 > q2 && v.at10 <= q3 : v.at10 > q3))); }
      case 'key': return [bits.slice(1).join(':')].filter(Boolean);
      default: return [];
    }
  }

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

  function cohortCard(c) {
    cardActions.set(c.id, c.actKeys || []);
    /* 覆盖不足 2 局时，曲线/分位/结论都不可靠：显示样本不足说明，不输出 +0 与空图。 */
    const covered = Number((c.grade && c.grade.n) || 0);
    const insufficient = covered < 2;
    const grade = `<span class="cx-grade g${c.grade.level}">${esc(c.grade.label)}</span>`;
    const repro = c.repro === null || c.repro === undefined ? '' : (c.repro ? '<span class="cx-repro ok">前后半可复现</span>' : '<span class="cx-repro no">前后半未复现</span>');
    const flag = c.flag ? `<span class="cx-repro ok">${esc(c.flag)}</span>` : '';
    const count = (c.actKeys || []).length;
    return `<article class="cx-find cx-cf" id="cx-analysis-${aesc(c.id)}">
      <div class="cx-cf-top"><span class="cx-find-kicker">${esc(c.id)} / ${esc(c.group)}</span><div class="cx-cf-flags">${grade}${repro}${flag}</div></div>
      <div class="cx-cf-name">${esc(c.name || '')}</div>
      ${insufficient
        ? '<h3 class="cx-cf-title cx-cf-title-muted">先攒够 2 局可用样本，再看这项结论</h3>'
        : `<h3 class="cx-cf-title">${c.title}</h3>`}
      <div class="cx-cf-canvas">${insufficient
        ? `<div class="cx-cf-insufficient"><b>样本不足</b><p>这个分析至少需要 2 局可用样本，当前覆盖 ${covered} 局。先把对局补全（或在「采集」补挂官方回放），再看这项结论。</p></div>`
        : renderViz(c.chart, c, { rows: vizRows, view: (id) => vizViews[id] || 'a' })}</div>
      <div class="cx-cf-foot">
        ${insufficient ? '' : `<div class="cx-cf-train"><span>训练安排</span><p>${esc(c.train)}</p></div>`}
        <button type="button" class="cx-act-btn" data-cx-act="${esc(c.id)}" ${count ? '' : 'disabled'}>${esc(c.review)} · 圈定 ${count} 局 <span>→</span></button>
      </div>
      <p class="cx-cf-method"><b>怎么算的</b> ${esc(coachMethod(c.method))} <span>覆盖 ${c.grade.n} 局</span></p>
    </article>`;
  }

  function cohortSection(result, totalAll, vectors) {
    if (!result || !result.cards.length) return '';
    const a = result.audit;
    const all = vectors || [];
    const uniq = (key, cap) => [...new Set(all.map((v) => String(v[key] || '').trim()).filter(Boolean))].sort().slice(0, cap);
    const versions = uniq('version', 30);
    const sessions = uniq('session', 30);
    const opponents = uniq('opponent', 50);
    const sel = (key, label, list, value) => `<label class="cx-select cx-filter"><span>${label}</span><select data-cx-filter="${key}">
      <option value="">全部</option>${list.map((v) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
    const resultSel = `<label class="cx-select cx-filter"><span>结果</span><select data-cx-filter="result">
      <option value=""${filterResult ? '' : ' selected'}>全部</option>
      <option value="win"${filterResult === 'win' ? ' selected' : ''}>胜</option>
      <option value="loss"${filterResult === 'loss' ? ' selected' : ''}>负</option>
    </select></label>`;
    const active = !!(sliceVersion || sliceSession || filterOpp || filterResult);
    return `<section class="cx-cohort">
      <div class="cx-cohort-head">
        <div class="cx-cohort-heading"><h2>通用跨局分析</h2><span class="cx-cohort-scope">当前 ${fmt(result.total)} 局 / 共 ${fmt(totalAll)} 局</span></div>
        <div class="cx-audit">证据充分 ${a.strong} 条 · 前后半一致 ${a.held}/${a.checked}</div>
      </div>
      <div class="cx-cohort-filters">
        ${sel('version', '版本', versions, sliceVersion)}
        ${sel('session', '训练组', sessions, sliceSession)}
        ${sel('opponent', '对手', opponents, filterOpp)}
        ${resultSel}
        ${active ? '<button type="button" class="cx-filter-clear" data-cx-clear-filters>清除筛选</button>' : ''}
      </div>
      <div class="cx-viz-index" role="group" aria-label="分析直达">${result.cards.map((c) => `<button type="button" data-cx-jump="${aesc(c.id)}">${aesc(c.name)}</button>`).join('')}</div>
      <div class="cx-finds-grid">${result.cards.map(cohortCard).join('')}</div>
    </section>`;
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
      if (scopeKeys && !scopeKeys.has(r.key)) return false;
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
      return '<div class="page cx-page"><section class="section cx-blank"><h1>当前范围没有对局</h1><p>换一个结果、对手关键词或训练组，全部结论会按新范围重算。</p><button type="button" class="primary" data-cx-clear>清除筛选 →</button></section></div>';
    }
    const list = rows.map(buildMatch);
    const a = summarize(list);
    const ordered = sortList(list);
    const size = pageSize > 0 ? pageSize : ordered.length;
    const pages = Math.max(1, Math.ceil(ordered.length / size));
    page = clamp(page, 0, pages - 1);
    const offset = page * size;
    const visible = ordered.slice(offset, offset + size);
    if (!focusKey || !list.some((m) => m.key === focusKey)) focusKey = ordered[0].key;
    lastView = { a, ordered, visible };
    const vectors = filterVectors((lastMeta.cohort && lastMeta.cohort.vectors) || []);
    vizRows = vectors;
    const cohort = analyzeCohort(vectors);
    const cohortTotal = (lastMeta.cohort && lastMeta.cohort.total) || allRows.length;
    return `<div class="page cx-page">
      ${heroCard(a, visible, ordered.length)}
      ${toolbar(allRows, a, lastMeta)}
      ${scopeKeys ? `<div class="cx-scope-bar">已圈定 ${fmt(scopeKeys.size)} 局用于逐局对照；上方全部结论仍基于${cohort.total < cohortTotal ? '当前范围' : '全量'}总体 <button type="button" data-cx-unscope>清除圈定 →</button></div>` : ''}
      <div class="cx-main">
        ${boardHtml(ordered, a, visible, offset, pages)}
      </div>
      ${cohortSection(cohort, cohortTotal, (lastMeta.cohort && lastMeta.cohort.vectors) || [])}
      ${laneBoard(list)}
      <p class="cx-source">数据来源：王者营地面板（十人结算 / 经济采样）、官方回放事件与逐秒位置。阵线按五人平均推进归一化；经济差一律为本队减对手。</p>
    </div>`;
  }

  /* ── 交互 ───────────────────────────────────────────────────── */
  function rerender(toBoard) {
    const host = document.querySelector('#content');
    if (host && lastRows.length) host.innerHTML = render(lastRows, lastMeta);
    if (toBoard) {
      const board = document.querySelector('.cx-board');
      if (board) board.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  function paintFocus(scroll) {
    const rootEl = document.querySelector('.cx-page');
    if (!rootEl || !lastView) return;
    rootEl.querySelectorAll('[data-cx-row]').forEach((el) => el.classList.toggle('is-focus', el.dataset.cxRow === focusKey));
    rootEl.querySelectorAll('[data-cx-focus].cx-film-cell').forEach((el) => el.classList.toggle('is-focus', el.dataset.cxFocus === focusKey));
    if (scroll) {
      const target = rootEl.querySelector(`[data-cx-row="${CSS.escape(focusKey)}"]`);
      if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function exportCsv() {
    if (!lastView) return;
    const head = ['编号', '日期', '对局', '训练组', '胜负', '本队人头', '对手人头', '时长(秒)', '10分钟经济差', '终局经济差', '阵线终值'];
    const lines = [head.join(',')];
    lastView.ordered.forEach((m, i) => {
      const cells = [i + 1, m.date, m.title, m.session,
        m.result === 'win' ? '胜' : m.result === 'loss' ? '负' : '',
        num(m.ownKills) ? m.ownKills : '', num(m.foeKills) ? m.foeKills : '',
        m.duration || '', num(m.at10) ? Math.round(m.at10) : '',
        num(m.finalDiff) ? Math.round(m.finalDiff) : '',
        num(m.frontEnd) ? (m.frontEnd * 100).toFixed(1) + '%' : ''];
      lines.push(cells.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','));
    });
    const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '跨局逐局对照.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function bind(root) {
    if (bind.done) return;
    bind.done = true;
    root.addEventListener('click', (event) => {
      if (event.target.closest && event.target.closest('.cx-open')) return;
      const jump = event.target.closest ? event.target.closest('[data-cx-jump]') : null;
      if (jump) { const el = document.getElementById(`cx-analysis-${jump.dataset.cxJump}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
      const viewBtn = event.target.closest ? event.target.closest('[data-cx-view-btn]') : null;
      if (viewBtn) { switchViz(viewBtn.dataset.cxVizId, viewBtn.dataset.cxViewBtn); return; }
      const probe = event.target.closest ? event.target.closest('[data-cx-sel]') : null;
      if (probe && probe.dataset.cxSel) {
        const keys = probeKeys(probe.dataset.cxSel, (lastMeta.cohort && lastMeta.cohort.vectors) || []);
        if (keys.length) { scopeKeys = new Set(keys); page = 0; hideVizTips(); rerender(true); }
        return;
      }
      const node = event.target.closest
        ? event.target.closest('[data-cx-focus],[data-cx-export],[data-cx-result],[data-cx-page],[data-cx-clear],[data-cx-clear-filters],[data-cx-act],[data-cx-unscope]')
        : null;
      if (!node) return;
      if (node.hasAttribute('data-cx-export')) { exportCsv(); return; }
      if (node.hasAttribute('data-cx-unscope')) { scopeKeys = null; page = 0; rerender(false); return; }
      if (node.hasAttribute('data-cx-act')) {
        const keys = (cardActions.get(node.dataset.cxAct) || []).filter(Boolean);
        scopeKeys = keys.length ? new Set(keys) : null;
        page = 0;
        rerender(true);
        return;
      }
      if (node.hasAttribute('data-cx-clear')) {
        filterResult = ''; filterOpp = ''; sliceVersion = ''; sliceSession = ''; scopeKeys = null; page = 0;
        rerender(false); return;
      }
      if (node.hasAttribute('data-cx-clear-filters')) {
        filterResult = ''; filterOpp = ''; sliceVersion = ''; sliceSession = ''; scopeKeys = null; page = 0;
        rerender(false); return;
      }
      if (node.hasAttribute('data-cx-result')) {
        filterResult = node.dataset.cxResult; page = 0;
        rerender(false); return;
      }
      if (node.hasAttribute('data-cx-page')) {
        if (node.disabled) return;
        page = Math.max(0, page + (node.dataset.cxPage === 'next' ? 1 : -1));
        rerender(true); return;
      }
      if (node.dataset.cxFocus) {
        focusKey = node.dataset.cxFocus;
        paintFocus(node.classList.contains('cx-film-cell'));
      }
    });
    root.addEventListener('mousemove', (event) => {
      const t = event.target.closest ? event.target.closest('[data-cx-tip]') : null;
      if (t) showVizTip(t, event); else hideVizTips();
    });
    root.addEventListener('mouseleave', hideVizTips);
    root.addEventListener('change', (event) => {
      const node = event.target.closest
        ? event.target.closest('[data-cx-sort],[data-cx-slice],[data-cx-page-size],[data-cx-opp],[data-cx-filter]')
        : null;
      if (!node) return;
      if (node.dataset.cxFilter) {
        const key = node.dataset.cxFilter, value = node.value;
        if (key === 'version') sliceVersion = value;
        else if (key === 'session') sliceSession = value;
        else if (key === 'opponent') filterOpp = value;
        else if (key === 'result') filterResult = value;
        scopeKeys = null; page = 0;
        rerender(false); return;
      }
      if (node.hasAttribute('data-cx-sort')) sortKey = node.value;
      else if (node.hasAttribute('data-cx-page-size')) { pageSize = Number(node.value); page = 0; }
      else if (node.hasAttribute('data-cx-opp')) { filterOpp = node.value; page = 0; }
      else if (node.dataset.cxSlice === 'version') sliceVersion = node.value;
      else sliceSession = node.value;
      rerender(false);
    });
  }

  return { render, bind };
}
