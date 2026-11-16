/* 选手详情页（2026-11-15 重构）
   数据：/api/v3/players-board + /api/v3/player-detail?player=
   结构：深墨报头 → 五块纵向模块（综合画像 / 英雄池与英雄类型 / 逐局表现与趋势 /
        对位与反制 / 搭档阵容与 BP），每块内若干张只读分析卡。
   口径：所有分位、排名、专项指标都按「这一局实际打的分路」算；不再给统一综合分。
        输出三套口径分开写清：总输出 / 对英雄输出 / 输出占比，互不混用。 */
export function createPlayerDetail(h) {
  const {esc, fmt, portrait, block, empty, st} = h;
  const S = (v) => esc(String(v ?? ''));
  const N = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? fmt(v, d) : '—');
  const P = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? fmt(v, d) + '%' : '—');
  const clamp = (v) => Math.max(0, Math.min(100, typeof v === 'number' && Number.isFinite(v) ? v : 0));
  const mean = (list, get = (x) => x) => {
    const vals = list.map(get).filter((v) => typeof v === 'number' && Number.isFinite(v));
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const sd = (list, get = (x) => x) => {
    const vals = list.map(get).filter((v) => typeof v === 'number' && Number.isFinite(v));
    const m = mean(vals);
    return vals.length > 1 && m != null
      ? Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / vals.length) : null;
  };
  const median = (values) => {
    const v = values.filter((x) => typeof x === 'number' && Number.isFinite(x)).sort((a, b) => a - b);
    if (!v.length) return null;
    const m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  };
  const percentile = (values, value) => {
    const v = values.filter((x) => typeof x === 'number' && Number.isFinite(x));
    if (!v.length || typeof value !== 'number' || !Number.isFinite(value)) return null;
    const below = v.filter((x) => x < value).length;
    const equal = v.filter((x) => x === value).length;
    return (below + equal * 0.5) / v.length * 100;
  };
  const group = (list, fn) => {
    const map = new Map();
    for (const item of list) {
      const key = fn(item) || '';
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    }
    return map;
  };
  const win = (list) => {
    const decided = list.filter((r) => r.result === 'win' || r.result === 'loss').length;
    const wins = list.filter((r) => r.result === 'win').length;
    return {games: list.length, wins, decided, rate: decided ? wins / decided * 100 : null};
  };
  const wilson = (wins, n) => {
    if (!n) return [null, null];
    const z = 1.96, p = wins / n, d = 1 + z * z / n;
    const c = (p + z * z / (2 * n)) / d;
    const half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, (c - half) * 100), Math.min(100, (c + half) * 100)];
  };
  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  /* 排行榜最低有效局数：1 局样本不进榜、单独列。
     分位不用选手级均值（这批数据里绝大多数游戏名只出现 1 局，会变成自己跟自己比），
     改用同分路逐局记录的分布，样本基础按「N 局」写在页面上。 */
  const LANE_MIN = 2;
  const CAPS = ['强开', '保护', '爆发', '持续输出', '前排', '清线', '支援', '运营', '容错'];
  const METRICS = [
    ['kda', 'KDA', 'killCnt / deadCnt / assistCnt', '(击杀 + 助攻) ÷ 死亡'],
    ['gpm', '分均经济', 'money', '经济 ÷ 时长（分）'],
    ['dpm', '分均总输出', 'totalHurtCnt', '总伤害 ÷ 时长（分），含兵线与野怪'],
    ['hdpm', '分均对英雄输出', 'totalHeroHurtCnt', '对英雄伤害 ÷ 时长（分）'],
    ['damageShare', '输出占比', 'totalHurtCnt', '本人总伤害 ÷ 本队 5 人总伤害'],
    ['participation', '参团率', 'joinGamePercent', '营地参团率 × 100'],
    ['takenShare', '承伤占比', 'totalBehurtCnt', '本人承伤 ÷ 本队 5 人承伤'],
    ['ctrlPerMin', '分均控制', 'ctrlTime', '控制时长 ÷ 时长（分）'],
    ['rating', '评分', 'gradeGame', '营地结算评分'],
    ['goldShare', '经济占比', 'money', '本人经济 ÷ 本队 5 人经济'],
    ['dtpm', '分均承伤', 'totalBehurtCnt', '承伤 ÷ 时长（分）'],
    ['monsterCoin', '野怪经济', 'monsterCoin', '营地面板野怪经济'],
  ];
  const metricName = (key) => (METRICS.find((m) => m[0] === key) || [key, key])[1];
  const LANE_FOCUS = {
    '游走': ['participation', 'takenShare', 'ctrlPerMin', 'kda', 'rating', 'dtpm'],
    '打野': ['gpm', 'monsterCoin', 'participation', 'hdpm', 'rating', 'kda'],
    '对抗路': ['hdpm', 'damageShare', 'takenShare', 'gpm', 'kda', 'rating'],
    '中路': ['hdpm', 'damageShare', 'gpm', 'participation', 'kda', 'rating'],
    '发育路': ['hdpm', 'damageShare', 'gpm', 'goldShare', 'kda', 'rating'],
  };
  const laneDist = (c, lane, key) => ((c.laneDistributions || {})[lane] || {})[key] || [];
  const lanePctile = (c, lane, key, value) => percentile(laneDist(c, lane, key), value);
  const laneValid = (c, lane) => (c.laneSamples[lane] || []).filter((s) => s.games >= LANE_MIN);

  /* ── 原语 ───────────────────────────────────────────────────────── */
  const card = (no, title, lead, body, foot = '') => `<article class="pdx-card">
    <div class="pdx-card-head"><span class="pdx-no">${S(no)}</span><div>
      <h3>${S(title)}</h3><p class="pdx-lead">${lead}</p></div></div>
    <div class="pdx-card-body">${body}</div>
    ${foot ? `<p class="pdx-foot">${foot}</p>` : ''}</article>`;
  const table = (headers, rows, cls = '') => rows.length
    ? `<div class="pdx-scroll"><table class="pdx-tbl ${cls}"><thead><tr>${headers.map((x) => `<th>${S(x)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((x) => `<td>${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
    : empty('这一组还没有可对照的记录。');
  const kpis = (items) => `<div class="pdx-kpis">${items.map(([label, value, note]) =>
    `<div><span>${S(label)}</span><strong>${value}</strong><small>${S(note || '')}</small></div>`).join('')}</div>`;
  const bars = (items) => `<div class="pdx-bars">${items.map(([label, value, max, note]) =>
    `<div class="pdx-bar"><span>${S(label)}</span><div class="pdx-bar-track"><i style="width:${clamp(max ? value / max * 100 : 0)}%"></i></div><b>${value}</b><small>${S(note || '')}</small></div>`).join('')}</div>`;
  const heroCell = (hero) => `<span class="pdx-hero"><i class="pl-hp">${portrait(hero)}</i>${S(hero || '未知')}</span>`;
  const resTag = (r) => `<em class="pdx-res ${r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : ''}">${r === 'win' ? '胜' : r === 'loss' ? '负' : '—'}</em>`;
  const dateOf = (r) => S(String(r.at || r.day || '').slice(5, 16));
  const gameLink = (r) => r.match
    ? `<a class="pdx-link" href="#match/${encodeURIComponent(r.match)}">复盘 ↗</a>` : '';
  const signed = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v)
    ? `${v > 0 ? '+' : ''}${fmt(v, d)}` : '—');
  const detailRows = (title, rows) => rows.length
    ? `<details class="pdx-details"><summary>${S(title)} · ${fmt(rows.length)} 行</summary>${rows.join('')}</details>` : '';

  /* ── 时间维度原语：训练日窗口 / 环比 / 同比 ────────────────────────
     口径沿用 BP 沙盘的 period_compare：环比 = 前一个等长窗口，同比 = 去年同日期。
     训练赛日期不连续，所以「近 N 个训练日」按有对局的日期切片，不按自然日回退；
     自然日空档既不进本期，也不进上期，避免把没训练的日子算成 0 局。
     同比只认去年同日期，数据不够就留空，不拿「上个月」冒充同比。 */
  const DAY_MS = 86400000;
  const dayOf = (r) => String((r && (r.day || r.at)) || '').slice(0, 10);
  const dayStamp = (text) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || ''));
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
  };
  const stampDay = (ms) => new Date(ms).toISOString().slice(0, 10);
  const shiftDay = (text, n) => {
    const ms = dayStamp(text);
    return ms == null ? '' : stampDay(ms + n * DAY_MS);
  };
  const shiftYear = (text) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || ''));
    if (!m) return '';
    const year = Number(m[1]) - 1, month = Number(m[2]), day = Number(m[3]);
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return `${year}-${m[2]}-${String(Math.min(day, last)).padStart(2, '0')}`;
  };
  const daysOf = (list) => [...new Set(list.map(dayOf).filter((day) => dayStamp(day) != null))].sort();
  const rangeText = (days) => !days.length ? '—'
    : days.length === 1 ? days[0] : `${days[0]} ~ ${days[days.length - 1]}`;
  const PERIOD_MODES = [
    ['d3', '近 3 个训练日', 3],
    ['d5', '近 5 个训练日', 5],
    ['week', '本周 vs 上周同期', 0],
  ];
  const PERIOD_KEYS = [
    ['games', '场次', 0, 'games'],
    ['winRate', '胜率', 1, 'pct'],
    ['rating', '平均评分', 2, 'num'],
    ['kda', 'KDA', 2, 'num'],
    ['gpm', '分均经济', 0, 'num'],
    ['hdpm', '分均对英雄输出', 0, 'num'],
    ['damageShare', '输出占比', 1, 'pct'],
    ['participation', '参团率', 1, 'pct'],
    ['takenShare', '承伤占比', 1, 'pct'],
    ['ctrlPerMin', '分均控制', 2, 'num'],
    ['mvpRate', 'MVP 率', 1, 'pct'],
    ['mainShare', '主位置占比', 1, 'pct'],
  ];
  const PERIOD_DIGITS = Object.fromEntries(PERIOD_KEYS.map(([key, , digits]) => [key, digits]));
  const PERIOD_MIN = 3;

  function periodWindow(rows, mode) {
    const allDays = daysOf(rows);
    if (!allDays.length) return null;
    const anchor = allDays[allDays.length - 1];
    let curFrom = '', curTo = '', prevFrom = '', prevTo = '', label = '', prevLabel = '', expected = 0;
    if (mode === 'week') {
      const anchorMs = dayStamp(anchor);
      const weekday = (new Date(anchorMs).getUTCDay() + 6) % 7; // 周一 = 0
      curFrom = stampDay(anchorMs - weekday * DAY_MS);
      curTo = anchor;
      prevFrom = shiftDay(curFrom, -7);
      prevTo = shiftDay(prevFrom, weekday);
      label = `本周（数据截至 ${curTo.slice(5)}）`;
      prevLabel = `上周同期（${prevFrom.slice(5)} ~ ${prevTo.slice(5)}）`;
    } else {
      const n = Number((PERIOD_MODES.find((item) => item[0] === mode) || [])[2]) || 3;
      const curDays = allDays.slice(-n);
      const prevDays = allDays.slice(Math.max(0, allDays.length - n * 2), Math.max(0, allDays.length - n));
      curFrom = curDays[0] || '';
      curTo = curDays[curDays.length - 1] || '';
      prevFrom = prevDays[0] || '';
      prevTo = prevDays[prevDays.length - 1] || '';
      label = `近 ${n} 个训练日（${rangeText(curDays)}）`;
      prevLabel = `前 ${n} 个训练日（${rangeText(prevDays)}）`;
      expected = n;
    }
    const within = (r, from, to) => {
      const day = dayOf(r);
      return Boolean(day && from && to && day >= from && day <= to);
    };
    const yoyFrom = shiftYear(curFrom), yoyTo = shiftYear(curTo);
    const current = rows.filter((r) => within(r, curFrom, curTo));
    const previous = rows.filter((r) => within(r, prevFrom, prevTo));
    const yoy = rows.filter((r) => within(r, yoyFrom, yoyTo));
    return {mode, label, prevLabel, curFrom, curTo, prevFrom, prevTo, yoyFrom, yoyTo,
      expected, current, previous, yoy,
      currentDays: daysOf(current), previousDays: daysOf(previous), yoyDays: daysOf(yoy)};
  }

  function periodAgg(list, mainLane) {
    const w = win(list), days = daysOf(list);
    return {
      games: list.length, wins: w.wins, decided: w.decided, winRate: w.rate,
      rating: mean(list, (r) => r.rating),
      kda: mean(list, (r) => r.kda),
      gpm: mean(list, (r) => r.gpm),
      hdpm: mean(list, (r) => r.hdpm),
      damageShare: mean(list, (r) => r.damageShare),
      participation: mean(list, (r) => r.participation),
      takenShare: mean(list, (r) => r.takenShare),
      ctrlPerMin: mean(list, (r) => r.ctrlPerMin),
      mvpRate: list.length ? list.filter((r) => r.mvp).length / list.length * 100 : null,
      mainShare: list.length ? list.filter((r) => r.lane === mainLane).length / list.length * 100 : null,
      days: days.length, from: days[0] || '', to: days[days.length - 1] || '',
    };
  }

  const periodValue = (key, value, digits, kind) => {
    if (kind === 'games') return typeof value === 'number' && Number.isFinite(value) ? `${fmt(value)} 局` : '—';
    if (kind === 'pct') return P(value);
    return N(value, digits);
  };
  const periodUnit = (key, kind) => kind === 'pct' ? ' pp' : key === 'games' ? ' 局' : '';
  const deltaTag = (value, key, kind, option = {}) => {
    const digits = option.digits ?? (PERIOD_DIGITS[key] ?? 1);
    const empty = option.empty || '—';
    if (value == null || !Number.isFinite(value)) return `<em class="pdx-delta is-na">${S(empty)}</em>`;
    if (Math.abs(value) < 0.05) return '<em class="pdx-delta is-flat">持平</em>';
    return `<em class="pdx-delta ${value > 0 ? 'is-up' : 'is-down'}">${value > 0 ? '+' : ''}${fmt(value, digits)}${periodUnit(key, kind)}</em>`;
  };
  const periodDelta = (key, current, other) => {
    if (!other || !other.games) return {value: null, empty: '无对局'};
    if (!current || !current.games) return {value: null, empty: '本期无对局'};
    if (key !== 'games' && (current.games < PERIOD_MIN || other.games < PERIOD_MIN)) {
      return {value: null, empty: '样本不足'};
    }
    const value = current[key] - other[key];
    return Number.isFinite(value) ? {value, empty: ''} : {value: null, empty: '—'};
  };
  const deltaWord = (key, kind, current, other) => {
    const delta = periodDelta(key, current, other);
    if (delta.value == null) return delta.empty;
    const digits = PERIOD_DIGITS[key] ?? 1;
    return `${delta.value > 0 ? '+' : ''}${fmt(delta.value, digits)}${periodUnit(key, kind)}`;
  };

  /* ── 模块 1：选手综合画像 ────────────────────────────────────────── */
  function buildPortrait(c) {
    const out = [];
    const id = c.identity, accounts = id.accountIds || [], nicks = id.nicknames || [];

    // 01 身份与数据合并状态
    {
      const body = `<div class="pdx-identity">
        <div class="pdx-id-main"><span class="pdx-id-ava">${S(String(c.name).slice(0, 1))}</span>
          <div><b>${S(c.name)}</b><small>游戏名 · 营地昵称</small></div>
          <span class="pdx-badge ${id.bound ? 'is-ok' : 'is-warn'}">${id.bound ? '已认领到选手ID' : '待认领昵称'}</span></div>
        <div class="pdx-id-grid">
          <div><span>真实选手ID</span><b>${id.playerId ? S(id.playerId) : '未认领'}</b></div>
          <div><span>归属战队</span><b>${id.teamName ? S(id.teamName) : '未归队'}</b></div>
          <div><span>营地账号</span><b>${fmt(accounts.length)} 个</b></div>
          <div><span>关联游戏名</span><b>${fmt(nicks.length)} 个</b></div>
        </div>
        <p class="pdx-line">本页 <b>${fmt(c.rows.length)} 局</b>全部按游戏名「${S(c.name)}」合并统计，挂在 <b>${fmt(accounts.length)}</b> 个营地账号下${nicks.length > 1 ? `，出现过 ${fmt(nicks.length)} 个游戏名` : ''}。${id.bound
          ? '已挂到选手ID；改名、转会、解绑只改当前归属，历史对局不回写。'
          : '尚未挂到选手ID，这段数据不会随改名或转会合并到其他选手名下。'}</p>
        ${id.bound ? '' : `<button class="control" data-pl-name="${S(c.name)}">命名并归队</button>`}
      </div>`;
      out.push(card('01', '身份与数据合并状态',
        `<b>${fmt(c.rows.length)} 局</b>集中在 <b>${fmt(nicks.length)} 个游戏名</b>、<b>${fmt(accounts.length)} 个营地账号</b>，当前${id.bound ? '已认领' : '待认领'}。`,
        body, '营地昵称 = 游戏名；教练命名的真名 = 选手ID。历史对局按当时的游戏名保留。'));
    }

    // 02 主副位置能力对比
    {
      const rowsHtml = c.laneOrder.map((lane) => {
        const list = c.byLane.get(lane) || [], w = win(list);
        const main = lane === c.mainLane;
        return [`<b>${S(lane)}</b> <i class="pdx-chip ${main ? '' : 'is-quiet'}">${main ? '主' : '副'}</i>`,
          fmt(list.length), P(w.rate), N(mean(list, (r) => r.kda), 2),
          P(mean(list, (r) => r.participation)), N(mean(list, (r) => r.gpm)),
          N(mean(list, (r) => r.hdpm)), N(mean(list, (r) => r.rating), 1),
          P(list.length ? list.filter((r) => r.mvp).length / list.length * 100 : null)];
      });
      const mainList = c.byLane.get(c.mainLane) || [];
      const rest = c.rows.length - mainList.length;
      const sideLanes = c.laneOrder.filter((l) => l !== c.mainLane);
      out.push(card('02', '主副位置能力对比',
        `主位置 <b>${S(c.mainLane)} ${fmt(mainList.length)} 局</b>（胜率 <b>${P(win(mainList).rate)}</b>），副位置 <b>${fmt(rest)} 局</b>覆盖 <b>${fmt(sideLanes.length)} 个位置</b>。`,
        table(['实际分路', '场次', '胜率', 'KDA', '参团率', '分均经济', '分均对英雄输出', '评分', 'MVP率'], rowsHtml),
        '每一行只统计该选手真正打这个分路的局；总场次可汇总，分路指标不混算。'));
    }

    // 03 分路专项指标
    {
      const body = c.laneOrder.map((lane) => {
        const list = c.byLane.get(lane) || [];
        const keys = LANE_FOCUS[lane] || LANE_FOCUS['中路'];
        const cells = keys.map((key) => {
          const value = mean(list, (r) => r[key]);
          const med = median(laneDist(c, lane, key));
          const p = lanePctile(c, lane, key, value);
          const digits = key === 'kda' || key === 'ctrlPerMin' ? 2 : 1;
          return `<div class="pdx-focus-cell"><span>${S(metricName(key))}</span>
            <b>${N(value, digits)}</b><small>同位置中位 ${N(med, digits)} · ${p == null ? '样本不足' : `${fmt(p, 0)} 分位`}</small></div>`;
        }).join('');
        return `<div class="pdx-lane-block"><div class="pdx-lane-title"><b>${S(lane)}</b>
          <span>${fmt(list.length)} 局 · ${lane === c.mainLane ? '主位置' : '副位置'} · 同分路 ${fmt(laneDist(c, lane, keys[0]).length)} 局参照</span></div>
          <div class="pdx-focus">${cells}</div></div>`;
      }).join('');
      out.push(card('03', '分路专项指标',
        `游走看参团 / 承伤 / 控制 / 支援，打野看经济 / 野区资源 / 团战，输出位看对英雄输出；<b>${fmt(c.laneOrder.length)} 个分路各自一套指标</b>。`,
        body, '指标按分路分别展示，不再用四个分位平均成一个统一综合分。'));
    }

    // 04 指标异常分位
    {
      const items = [];
      for (const lane of c.laneOrder) {
        const list = c.byLane.get(lane) || [];
        if (list.length < LANE_MIN) continue;
        for (const [key, label] of METRICS.map((m) => [m[0], m[1]])) {
          const value = mean(list, (r) => r[key]);
          const p = lanePctile(c, lane, key, value);
          if (p == null || (p < 80 && p > 20)) continue;
          items.push([`<b>${S(lane)}</b>`, S(label), N(value, 2),
            `<b class="${p >= 80 ? 'is-hi' : 'is-lo'}">${fmt(p, 0)} 分位</b>`,
            p >= 80 ? '明显偏高' : '明显偏低',
            `本人 ${fmt(list.length)} 局 · 参照 ${fmt(laneDist(c, lane, key).length)} 局`]);
        }
      }
      items.sort((a, b) => Number(String(b[3]).replace(/\D/g, '')) - Number(String(a[3]).replace(/\D/g, '')));
      const hi = items.filter((r) => r[4] === '明显偏高').length;
      out.push(card('04', '指标异常分位',
        `同分路逐局分布里 <b>${fmt(items.length)} 项</b>指标越出 20 / 80 分位线，其中偏高 <b>${fmt(hi)} 项</b>、偏低 <b>${fmt(items.length - hi)} 项</b>。`,
        table(['分路', '指标', '本人均值', '分位', '判定', '样本基础'], items),
        `分位参照是同一实际分路的全部逐局记录（每路约 200 局），不是选手均值；排行榜另设 ≥ ${LANE_MIN} 局的选手门槛。`));
    }

    // 05 对手强度分层
    {
      const strength = new Map(c.opponents.map((o) => [o.name, o.winRate]));
      const byOpp = group(c.rows, (r) => r.opponentTeam || '对手未标注');
      const rowsHtml = [...byOpp].map(([opp, list]) => {
        const w = win(list), teamRate = strength.get(opp);
        const tier = teamRate == null ? '未分层' : teamRate < 45 ? '强对手' : teamRate <= 65 ? '中等对手' : '较弱对手';
        const duels = list.filter((r) => r.foe);
        const goldDiff = mean(duels, (r) => r.gold - (r.foe.gold || 0));
        return [`<b>${S(opp)}</b>`, teamRate == null ? '—' : P(teamRate),
          `<i class="pdx-chip ${tier === '强对手' ? 'is-warn' : 'is-quiet'}">${S(tier)}</i>`,
          fmt(list.length), P(w.rate), N(mean(list, (r) => r.rating), 1),
          N(mean(list, (r) => r.gpm)), signed(goldDiff)];
      }).sort((a, b) => Number(String(b[1]).replace('%', '')) - Number(String(a[1]).replace('%', '')));
      const comparable = [...byOpp.values()].filter((l) => l.length >= 3);
      const rates = comparable.map((l) => win(l).rate || 0);
      out.push(card('05', '对手强度分层',
        `面对 <b>${fmt(byOpp.size)} 支对手</b>，其中 ≥ 3 局的 <b>${fmt(comparable.length)} 支</b>个人胜率从 <b>${P(rates.length ? Math.min(...rates) : null)}</b> 到 <b>${P(rates.length ? Math.max(...rates) : null)}</b>。`,
        table(['对手战队', '本队交手胜率', '强度层', '本人场次', '本人胜率', '评分', '分均经济', '对位经济差'], rowsHtml),
        '强度层按本队对该对手的交手胜率划分：< 45% 强、45–65% 中、> 65% 较弱。经济差为本人减同分路对手的终局经济。'));
    }

    // 06 统计特征与战术判断分开
    {
      const list = c.byLane.get(c.mainLane) || [];
      const keys = ['participation', 'takenShare', 'ctrlPerMin', 'hdpm', 'gpm', 'kda'];
      const left = keys.map((key) => {
        const value = mean(list, (r) => r[key]);
        const p = lanePctile(c, c.mainLane, key, value);
        return `<div class="pdx-stat-row"><span>${S(metricName(key))}</span><b>${N(value, 2)}</b>
          <small>${p == null ? '同分路样本不足' : `同分路 ${fmt(p, 0)} 分位`}</small></div>`;
      }).join('');
      const right = [
        ['资源是否主动让出', '面板只有终局经济，看不出队内分配意图'],
        ['是否由他先手开团', '强开是英雄能力标签，不等于该选手的开团次数'],
        ['生存来自站位还是保护', 'KDA 高也可能来自队友保护或对手强度'],
        ['支援是否到达关键团战', '参团率是结果代理，不是到场时间'],
      ].map(([t, d]) => `<div class="pdx-judge-row"><b>${S(t)}</b><small>${S(d)}</small></div>`).join('');
      out.push(card('06', '统计特征与战术判断',
        `${S(c.mainLane)}的 <b>${fmt(keys.length)} 项可观察数值</b>与 <b>4 项需回放确认的判断</b>分开陈列，不互相代替。`,
        `<div class="pdx-split"><div><h4>统计特征 · 营地面板可观察</h4>${left}</div>
         <div><h4>战术判断 · 营地面板不能判定</h4>${right}</div></div>`,
        '左栏只报数值和同位置分位；右栏是需要录像才能下的结论，本页不替教练下。'));
    }

    // 07 同位置对标（最低有效局数）
    {
      const all = c.laneSamples[c.mainLane] || [];
      const valid = all.filter((s) => s.games >= LANE_MIN);
      const weak = all.filter((s) => s.games < LANE_MIN);
      const rowsHtml = valid.slice(0, 10).map((s, i) => [
        `<b>${String(i + 1).padStart(2, '0')}</b>`,
        s.name === c.name ? `<b>${S(s.name)}</b>` : S(s.name),
        fmt(s.games), P(s.winRate), N(s.kda, 2), N(s.hdpm), P(s.participation), N(s.rating, 1),
      ]);
      out.push(card('07', '同位置对标',
        `${S(c.mainLane)} 共 <b>${fmt(all.length)} 人</b>；达到 <b>${LANE_MIN} 局</b>门槛的 <b>${fmt(valid.length)} 人</b>进榜，<b>${fmt(weak.length)} 人</b>单独列出。`,
        table(['#', '选手', '场次', '胜率', 'KDA', '分均对英雄输出', '参团率', '评分'], rowsHtml) +
        `<details class="pdx-details"><summary>未达 ${LANE_MIN} 局门槛的 ${fmt(weak.length)} 人（不参与排名）</summary>
          <p class="pdx-line">${S(weak.slice(0, 40).map((s) => `${s.name} ${s.games} 局`).join(' · '))}${weak.length > 40 ? ' …' : ''}</p></details>`,
        '榜单按出场场次排，只给单项原始值，不再用统一综合分排序；1 局样本不会出现在前列。本批数据里多数游戏名只出场 1 局，达门槛人数少时榜单仅作展示。'));
    }

    // 08 指标口径
    {
      const rowsHtml = METRICS.map(([key, label, field, calc]) =>
        [S(label), `<code>${S(field)}</code>`, S(calc), key === 'dpm' ? '仅作总量参照' : key === 'damageShare' ? '占比，不与分均输出混用' : '本页主口径']);
      out.push(card('08', '指标口径',
        `分均总输出、分均对英雄输出、输出占比是<b>三个不同量</b>，页面各自标明来源字段。`,
        table(['页面指标', '营地面板字段', '计算方式', '用法'], rowsHtml),
        '原来「分均输出」写的是营地结算 hurt / 分钟（总伤害），与输出占比容易混读；本页默认采用对英雄输出。'));
    }
    return out;
  }

  /* ── 模块 2：英雄池与英雄类型 ────────────────────────────────────── */
  function heroBench(board, selfName) {
    const map = new Map();
    for (const g of board.games || []) {
      const ownWin = g.result === 'win', ownLose = g.result === 'loss';
      for (const [side, arr] of [['own', g.own || []], ['enemy', g.enemy || []]]) {
        const won = side === 'own' ? ownWin : ownLose;
        for (const p of arr) {
          if (!p.hero || p.name === selfName) continue;
          const it = map.get(p.hero) || {games: 0, wins: 0, decided: 0, kda: [], gold: []};
          it.games += 1;
          if (ownWin || ownLose) {
            it.decided += 1;
            if (won) it.wins += 1;
          }
          if (typeof p.kda === 'number') it.kda.push(p.kda);
          if (typeof p.gold === 'number') it.gold.push(p.gold);
          map.set(p.hero, it);
        }
      }
    }
    return map;
  }
  function buildHeroes(c) {
    const out = [];
    const byHero = c.byHero;
    const heroList = [...byHero].filter(([hero]) => hero)
      .sort((a, b) => b[1].length - a[1].length);
    const maxGames = Math.max(1, ...heroList.map(([, list]) => list.length));

    // 01 英雄使用全表
    {
      const rowsHtml = heroList.map(([hero, list]) => {
        const w = win(list), tag = c.meta[hero] || {};
        const lanes = [...new Set(list.map((r) => r.lane))].join(' / ');
        return [heroCell(hero), S(tag.type || '未分类'), S(lanes), fmt(list.length),
          P(w.rate), N(mean(list, (r) => r.rating), 1), N(mean(list, (r) => r.kda), 2),
          P(mean(list, (r) => r.participation)), N(mean(list, (r) => r.hdpm)),
          S((tag.caps || []).join(' · ') || '—'),
          S(String(list[list.length - 1].day || ''))];
      });
      const head = rowsHtml.slice(0, 12);
      const rest = rowsHtml.slice(12);
      out.push(card('01', '英雄使用全表',
        `共使用 <b>${fmt(heroList.length)} 个英雄</b>，出场最多的是 <b>${S(heroList[0]?.[0] || '—')} ${fmt(heroList[0]?.[1].length || 0)} 局</b>（胜率 <b>${P(win(heroList[0]?.[1] || []).rate)}</b>）。`,
        table(['英雄', '职业', '实际分路', '场次', '胜率', '评分', 'KDA', '参团率', '分均对英雄输出', '战术能力', '最近使用'], head) +
        (rest.length ? `<details class="pdx-details"><summary>其余 ${fmt(rest.length)} 个英雄</summary>${table(['英雄', '职业', '实际分路', '场次', '胜率', '评分', 'KDA', '参团率', '分均对英雄输出', '战术能力', '最近使用'], rest)}</details>` : ''),
        '胜率分母是有胜负的局；能力标签来自赛训组 133 英雄 × 9 维能力矩阵，描述英雄本身，不代表选手发挥。'));
    }

    // 02 第一层：分路类型（实际 vs 英雄默认分路）
    {
      const rowsHtml = c.laneOrder.map((lane) => {
        const list = c.byLane.get(lane) || [];
        const defaults = group(list, (r) => r.heroDefaultLane || '未标注');
        const same = (defaults.get(lane) || []).length;
        return [`<b>${S(lane)}</b>`, fmt(list.length),
          `${fmt(same)} 局`, P(list.length ? same / list.length * 100 : null),
          S([...defaults].filter(([k]) => k !== lane).map(([k, v]) => `${k} ${v.length} 局`).join(' · ') || '无换位')];
      });
      out.push(card('02', '第一层 · 分路类型',
        `<b>${fmt(c.laneOrder.length)} 个实际分路</b>，其中英雄默认分路与实际分路一致的局占 <b>${P(c.rows.length ? c.rows.filter((r) => r.heroDefaultLane === r.lane).length / c.rows.length * 100 : null)}</b>。`,
        table(['实际分路', '场次', '同默认分路', '一致率', '换位分布'], rowsHtml),
        '分路类型回答「选手主要打什么位置、能否换位」；实际分路取营地面板 battleRecords.position，默认分路取英雄元数据。'));
    }

    // 03 第二层：英雄职业
    {
      const byType = group(c.rows, (r) => r.heroType || '未分类');
      const items = [...byType].sort((a, b) => b[1].length - a[1].length)
        .map(([type, list]) => [S(type), fmt(list.length),
          P(c.rows.length ? list.length / c.rows.length * 100 : null), P(win(list).rate),
          N(mean(list, (r) => r.rating), 1), S([...new Set(list.map((r) => r.hero))].slice(0, 6).join(' · '))]);
      out.push(card('03', '第二层 · 英雄职业',
        `英雄池覆盖 <b>${fmt(byType.size)} 类职业</b>，占比最高的是 <b>${S([...byType].sort((a, b) => b[1].length - a[1].length)[0]?.[0] || '—')}</b> <b>${P(c.rows.length ? Math.max(...[...byType.values()].map((l) => l.length)) / c.rows.length * 100 : null)}</b>。`,
        table(['职业类型', '场次', '占比', '该职业胜率', '评分', '代表英雄'], items),
        '职业元数据来自 resources/hero_tags.json 的 defaultType（坦边 / 战野 / 法核 / 游射 / 开团辅 等），已覆盖全部在库英雄。'));
    }

    // 04 第三层：战术能力覆盖
    {
      const capGames = new Map(CAPS.map((cap) => [cap, 0]));
      for (const r of c.rows) for (const cap of r.caps || []) capGames.set(cap, (capGames.get(cap) || 0) + 1);
      const max = Math.max(1, ...capGames.values());
      const items = CAPS.map((cap) => {
        const n = capGames.get(cap) || 0;
        const list = c.rows.filter((r) => (r.caps || []).includes(cap));
        return [S(cap), fmt(n), P(c.rows.length ? n / c.rows.length * 100 : null),
          P(win(list).rate), n];
      });
      out.push(card('04', '第三层 · 战术能力',
        `英雄池覆盖 <b>${fmt(items.filter((i) => i[1] !== '0').length)} / 9</b> 项阵容功能，覆盖最广的是 <b>${S([...items].sort((a, b) => b[4] - a[4])[0]?.[0] || '—')}</b>。`,
        bars(items.map(([label, n, rate, wr]) => [label, n, max, `覆盖 ${rate} · 胜率 ${wr}`])),
        '统计的是「所用英雄具备的能力」，不是「选手打出来的效果」；两者下一张卡分开对照。'));
    }

    // 05 第四层：实际使用风格（英雄能力 vs 打出来的表现）
    {
      const styleDefs = [
        ['经济型', 'gpm', '强开'], ['输出型', 'hdpm', '持续输出'],
        ['承伤型', 'takenShare', '前排'], ['团战参与型', 'participation', '支援'],
        ['资源控制型', 'monsterCoin', '运营'],
      ];
      const rowsHtml = styleDefs.map(([label, key, cap]) => {
        const tagged = c.rows.filter((r) => (r.caps || []).includes(cap));
        const others = c.rows.filter((r) => !(r.caps || []).includes(cap));
        const a = mean(tagged, (r) => r[key]), b = mean(others, (r) => r[key]);
        const p = percentile(c.rows.map((r) => r[key]).filter((v) => typeof v === 'number'), a);
        return [`<b>${S(label)}</b>`, S(metricName(key)), fmt(tagged.length), N(a, 1),
          fmt(others.length), N(b, 1), signed(a == null || b == null ? null : a - b, 1),
          p == null ? '—' : `${fmt(p, 0)} 分位`];
      });
      out.push(card('05', '第四层 · 实际使用风格',
        `把「英雄有这个能力」与「这些局实际打出多少」并排放：<b>${fmt(styleDefs.length)} 类风格</b>逐类给出差值。`,
        table(['风格', '观察指标', '带该能力标签的局', '这些局的均值', '其它局', '其它局均值', '差值', '本人分布位置'], rowsHtml),
        '例：鲁班大师带强开与保护标签，不代表选手每局都打出了开团或保护；差值只描述这批局的结果差异。'));
    }

    // 06 个人常用英雄 与 同英雄选手对照（拆开）
    {
      const bench = heroBench(c.board, c.name);
      const top = heroList.slice(0, 8);
      const rowsHtml = top.map(([hero, list]) => {
        const w = win(list), b = bench.get(hero);
        const bRate = b && b.decided ? b.wins / b.decided * 100 : null;
        return [heroCell(hero), fmt(list.length), P(w.rate), N(mean(list, (r) => r.rating), 1),
          b ? fmt(b.games) : '—', b ? P(bRate) : '—',
          b && bRate != null && w.rate != null ? signed(w.rate - bRate, 1) : '—',
          b && b.games >= 3 ? '样本可比' : '同英雄样本不足'];
      });
      out.push(card('06', '个人常用英雄 与 同英雄选手对照',
        `个人常用 <b>${S(top[0]?.[0] || '—')} ${fmt(top[0]?.[1].length || 0)} 局</b>；同英雄其他选手样本单独成列，不足 3 局的不下比较结论。`,
        table(['英雄', '本人场次', '本人胜率', '本人评分', '同英雄其他选手场次', '同英雄胜率', '胜率差', '样本判定'], rowsHtml),
        '左侧是个人常用英雄分析，右侧是同英雄选手基准；两件事拆开，不再因为后者没数据就让整块空白。'));
    }
    return out;
  }

  function buildTime(c) {
    const out = [];
    const pd = st.pd || (st.pd = {});
    const mode = PERIOD_MODES.some(([key]) => key === pd.mode) ? pd.mode : 'd3';
    const period = periodWindow(c.rows, mode);
    if (!period) {
      return [card('01', '周期对比 · 环比 / 同比',
        '这批对局没有可用的训练日日期，切不出时间窗口。',
        empty('需要营地面板的对局日期（day）才能做环比 / 同比。'),
        '不按空日期补 0，也不把无日期对局硬塞进某一期。')];
    }
    const cur = periodAgg(period.current, c.mainLane);
    const prev = periodAgg(period.previous, c.mainLane);
    const yoy = periodAgg(period.yoy, c.mainLane);
    const allDays = daysOf(c.rows), firstDay = allDays[0] || '—';
    const range = (from, to) => from && to ? (from === to ? from : `${from} ~ ${to}`) : '—';
    const tools = `<div class="pdx-period-tools" role="group" aria-label="周期口径">${PERIOD_MODES.map(([key, label]) =>
      `<button type="button" data-pd-window="${key}" aria-pressed="${key === mode}">${S(label)}</button>`).join('')}</div>`;
    const tile = (cls, title, from, to, agg, note) => {
      if (!agg.games) {
        const span = range(from, to);
        return `<article class="pdx-period-tile is-empty"><span>${S(title)}</span><b>无对局</b>
          <small>${span === '—' ? '没有可比较的训练日' : `${S(span)} 没有记录`}</small></article>`;
      }
      return `<article class="pdx-period-tile ${cls}"><span>${S(title)}</span><b>${S(range(from, to))}</b>
        <small>${fmt(agg.games)} 局 · ${fmt(agg.days)} 个训练日${note ? ` · ${S(note)}` : ''}</small>
        <div class="pdx-period-nums"><em>胜率 <b>${P(agg.winRate)}</b></em><em>评分 <b>${N(agg.rating, 2)}</b></em><em>KDA <b>${N(agg.kda, 2)}</b></em></div>
      </article>`;
    };

    // 01 周期对比 · 环比 / 同比
    {
      const prevNote = period.expected && period.expected > period.previousDays.length
        ? `上期只有 ${fmt(period.previousDays.length)} 个训练日（数据起点）` : '';
      const performance = !prev.games
        ? `本期胜率 <b>${P(cur.winRate)}</b>、平均评分 <b>${N(cur.rating, 2)}</b>；上期无对局，环比留空。`
        : prev.games < PERIOD_MIN
          ? `本期胜率 <b>${P(cur.winRate)}</b>、平均评分 <b>${N(cur.rating, 2)}</b>；上期仅 ${fmt(prev.games)} 局，不到 ${PERIOD_MIN} 局门槛，环比只列原始值。`
          : `本期胜率 <b>${P(cur.winRate)}</b>，较上期 <b>${deltaWord('winRate', 'pct', cur, prev)}</b>；平均评分 <b>${N(cur.rating, 2)}</b>，较上期 <b>${deltaWord('rating', 'num', cur, prev)}</b>。`;
      const lead = `${S(period.label)} 共 <b>${fmt(cur.games)} 局</b>、<b>${fmt(cur.days)} 个训练日</b>；`
        + `${S(period.prevLabel)} 共 <b>${fmt(prev.games)} 局</b>。` + performance
        + (yoy.games
          ? `去年同期 ${S(range(period.yoyFrom, period.yoyTo))} 有 <b>${fmt(yoy.games)} 局</b>，同比列按同日期口径计算。`
          : `去年同期 ${S(range(period.yoyFrom, period.yoyTo))} 没有对局，同比列留空，不做硬同比。`);
      const prevHas = prev.games > 0, yoyHas = yoy.games > 0;
      const rowsHtml = PERIOD_KEYS.map(([key, label, digits, kind]) => {
        const prevDelta = periodDelta(key, cur, prev);
        const yoyDelta = periodDelta(key, cur, yoy);
        return [`<b>${S(label)}</b>`,
          periodValue(key, cur[key], digits, kind),
          prevHas ? periodValue(key, prev[key], digits, kind) : '—',
          deltaTag(prevDelta.value, key, kind, {digits, empty: prevHas ? prevDelta.empty : '—'}),
          yoyHas ? periodValue(key, yoy[key], digits, kind) : '—',
          deltaTag(yoyDelta.value, key, kind, {digits, empty: yoyHas ? yoyDelta.empty : '—'})];
      });
      out.push(card('01', '周期对比 · 环比 / 同比',
        lead,
        tools + `<div class="pdx-period-grid">
          ${tile('is-current', `本期 · ${period.label.split('（')[0]}`, period.curFrom, period.curTo, cur, '')}
          ${tile('', '环比 · 上期', period.prevFrom, period.prevTo, prev, prevNote)}
          ${tile('', '同比 · 去年同日期', period.yoyFrom, period.yoyTo, yoy, '')}
        </div>` + table(['指标', '本期', '上期（环比）', '环比变化', '去年同期（同比）', '同比变化'], rowsHtml, 'is-period'),
        `环比 = 前一个等长训练日窗口（按这名选手有对局的日期计）；同比 = 去年同日期，不是自然年。任一侧不足 ${PERIOD_MIN} 局时只列原始值、不给变化；变化只描述数值方向，不判断好坏。主位置占比按全量画像的主位置计；无日期的局不进时间窗口。pp = 百分点。当前最早训练日 ${firstDay}。`));
    }

    // 02 训练日逐日走势（含较前一训练日的环比）
    {
      const byDay = group(c.rows, (r) => dayOf(r) || '未标注日期');
      const dayList = [...byDay.keys()].filter((day) => day !== '未标注日期').sort();
      const daily = dayList.map((day) => ({day, agg: periodAgg(byDay.get(day) || [], c.mainLane)}));
      const dayDelta = (item, index, key, kind) => {
        if (index === 0) return deltaTag(null, key, kind, {empty: '—'});
        const before = daily[index - 1];
        if (!before || !before.agg.games) return deltaTag(null, key, kind, {empty: '前日无对局'});
        if (item.agg.games < PERIOD_MIN || before.agg.games < PERIOD_MIN) {
          return deltaTag(null, key, kind, {empty: '样本不足'});
        }
        return deltaTag(item.agg[key] - before.agg[key], key, kind, {digits: PERIOD_DIGITS[key]});
      };
      const rowsHtml = daily.map((item, index) => {
        const cell = (key, kind, value) => `<span class="pdx-dv"><b>${value}</b>${dayDelta(item, index, key, kind)}</span>`;
        return [`<b>${S(item.day)}</b>`, fmt(item.agg.games),
          cell('winRate', 'pct', P(item.agg.winRate)),
          cell('rating', 'num', N(item.agg.rating, 2)),
          cell('kda', 'num', N(item.agg.kda, 2)),
          cell('gpm', 'num', N(item.agg.gpm)),
          cell('hdpm', 'num', N(item.agg.hdpm)),
          cell('participation', 'pct', P(item.agg.participation))];
      });
      const rated = daily.filter((item) => typeof item.agg.rating === 'number');
      const best = [...rated].sort((a, b) => b.agg.rating - a.agg.rating)[0];
      const worst = [...rated].sort((a, b) => a.agg.rating - b.agg.rating)[0];
      const last = daily[daily.length - 1];
      const lead = `<b>${fmt(daily.length)} 个训练日</b>、<b>${fmt(c.rows.length)} 局</b>；评分最高 <b>${S(best?.day || '—')}</b>（${N(best?.agg.rating, 2)}），`
        + `最低 <b>${S(worst?.day || '—')}</b>（${N(worst?.agg.rating, 2)}）；最近一日 <b>${S(last?.day || '—')}</b> 胜率 <b>${P(last?.agg.winRate)}</b>、评分 <b>${N(last?.agg.rating, 2)}</b>。`;
      out.push(card('02', '训练日逐日走势',
        lead,
        kpis([['训练日', fmt(daily.length), rangeText(dayList)],
          ['日均场次', N(c.rows.length / Math.max(1, daily.length), 1), '按有对局的日期'],
          ['最近一日', last ? S(last.day) : '—', last ? `${fmt(last.agg.games)} 局 · 胜率 ${P(last.agg.winRate)}` : '—']]) +
        table(['训练日', '局数', '胜率 Δ', '评分 Δ', 'KDA Δ', '分均经济 Δ', '对英雄输出 Δ', '参团率 Δ'], rowsHtml, 'is-period-wide'),
        '训练日 = 这名选手有对局的日期；Δ 对比前一个训练日，不按自然日连续，空档日不参与比较。任一侧不足 3 局只列原始值。'));
    }

    // 03 分路周期对比
    {
      const curLanes = group(period.current, (r) => r.lane || '未记录');
      const prevLanes = group(period.previous, (r) => r.lane || '未记录');
      const laneKeys = [...new Set([...curLanes.keys(), ...prevLanes.keys()])]
        .sort((a, b) => (curLanes.get(b) || []).length - (curLanes.get(a) || []).length
          || (prevLanes.get(b) || []).length - (prevLanes.get(a) || []).length);
      const rowsHtml = laneKeys.map((lane) => {
        const a = periodAgg(curLanes.get(lane) || [], c.mainLane);
        const b = periodAgg(prevLanes.get(lane) || [], c.mainLane);
        const shareA = cur.games ? a.games / cur.games * 100 : null;
        const shareB = prev.games ? b.games / prev.games * 100 : null;
        const dRating = periodDelta('rating', a, b);
        const dWin = periodDelta('winRate', a, b);
        const emptyNote = !b.games ? '上期未打' : !a.games ? '本期未打' : '样本不足';
        return [`<b>${S(lane)}</b>${lane === c.mainLane ? ' <i class="pdx-chip">主</i>' : ''}`,
          fmt(a.games), P(shareA), P(a.winRate), N(a.rating, 2), N(a.kda, 2),
          fmt(b.games), P(shareB), P(b.winRate), N(b.rating, 2),
          deltaTag(dRating.value, 'rating', 'num', {digits: 2, empty: emptyNote}),
          deltaTag(dWin.value, 'winRate', 'pct', {digits: 1, empty: emptyNote})];
      });
      const mainA = curLanes.get(c.mainLane) || [], mainB = prevLanes.get(c.mainLane) || [];
      const dropped = laneKeys.filter((lane) => (prevLanes.get(lane) || []).length && !(curLanes.get(lane) || []).length);
      const added = laneKeys.filter((lane) => (curLanes.get(lane) || []).length && !(prevLanes.get(lane) || []).length);
      const lead = `本期实际分路 <b>${fmt(curLanes.size)} 个</b>、上期 <b>${fmt(prevLanes.size)} 个</b>；主位置 <b>${S(c.mainLane)}</b> `
        + `本期 ${fmt(mainA.length)} 局（<b>${P(cur.games ? mainA.length / cur.games * 100 : null)}</b>），`
        + `上期 ${fmt(mainB.length)} 局（<b>${P(prev.games ? mainB.length / prev.games * 100 : null)}</b>）。`
        + (dropped.length ? `本期未打 ${S(dropped.join(' / '))}。` : '')
        + (added.length ? `本期新打 ${S(added.join(' / '))}。` : '');
      out.push(card('03', '分路周期对比',
        lead,
        `<p class="pdx-period-read">当前周期：${S(period.label)} vs ${S(period.prevLabel)}</p>` +
        table(['分路', '本期场次', '本期占比', '本期胜率', '本期评分', '本期KDA', '上期场次', '上期占比', '上期胜率', '上期评分', '评分环比', '胜率环比'], rowsHtml, 'is-period-wide'),
        '分路按每局实际分路（营地面板 position）；本期/上期任一侧不足 3 局的分路只列原始值，不判变化。'));
    }

    // 04 英雄池周期变化
    {
      const curHeroes = group(period.current, (r) => r.hero || '未知');
      const prevHeroes = group(period.previous, (r) => r.hero || '未知');
      const heroKeys = [...new Set([...curHeroes.keys(), ...prevHeroes.keys()])];
      const heroRows = heroKeys.map((hero) => ({
        hero,
        cur: periodAgg(curHeroes.get(hero) || [], c.mainLane),
        prev: periodAgg(prevHeroes.get(hero) || [], c.mainLane),
      })).sort((a, b) => b.cur.games - a.cur.games || b.prev.games - a.prev.games
        || String(a.hero).localeCompare(String(b.hero)));
      const heroDelta = (a, b, key, kind) => {
        if (!a.games || !b.games) return deltaTag(null, key, kind, {empty: !b.games ? '上期未用' : '本期未用'});
        if (a.games < PERIOD_MIN || b.games < PERIOD_MIN) return deltaTag(null, key, kind, {empty: '样本不足'});
        return deltaTag(a[key] - b[key], key, kind, {digits: PERIOD_DIGITS[key]});
      };
      const head = ['英雄', '本期场次', '本期胜率', '本期评分', '上期场次', '上期胜率', '场次变化', '胜率变化', '判定'];
      const rowOf = (item) => {
        const a = item.cur, b = item.prev;
        const sample = a.games >= PERIOD_MIN && b.games >= PERIOD_MIN ? '样本可比'
          : a.games < PERIOD_MIN ? '本期样本少' : '上期样本少';
        return [heroCell(item.hero), fmt(a.games), P(a.winRate), N(a.rating, 1), fmt(b.games), P(b.winRate),
          deltaTag(a.games - b.games, 'games', 'games', {digits: 0}),
          heroDelta(a, b, 'winRate', 'pct'),
          `<i class="pdx-chip ${sample === '样本可比' ? '' : 'is-quiet'}">${S(sample)}</i>`];
      };
      const curNames = [...curHeroes.keys()].filter((hero) => (curHeroes.get(hero) || []).length);
      const prevNames = [...prevHeroes.keys()].filter((hero) => (prevHeroes.get(hero) || []).length);
      const both = curNames.filter((hero) => prevNames.includes(hero));
      const fresh = curNames.filter((hero) => !prevNames.includes(hero))
        .sort((a, b) => (curHeroes.get(b) || []).length - (curHeroes.get(a) || []).length);
      const gone = prevNames.filter((hero) => !curNames.includes(hero))
        .sort((a, b) => (prevHeroes.get(b) || []).length - (prevHeroes.get(a) || []).length);
      const chips = (list, emptyText) => list.length
        ? `<div class="pdx-hero-chips">${list.slice(0, 12).map((hero) => heroCell(hero)).join('')}${list.length > 12 ? `<span class="pdx-chip is-quiet">…另 ${fmt(list.length - 12)} 个</span>` : ''}</div>`
        : `<p class="pdx-line">${S(emptyText)}</p>`;
      const visible = heroRows.slice(0, 14), rest = heroRows.slice(14);
      const lead = `本期使用 <b>${fmt(curNames.length)} 个英雄</b>，上期 <b>${fmt(prevNames.length)} 个</b>；`
        + `重合 <b>${fmt(both.length)} 个</b>，本期新增 <b>${fmt(fresh.length)} 个</b>，上期用过但本期未用 <b>${fmt(gone.length)} 个</b>。`;
      out.push(card('04', '英雄池周期变化',
        lead,
        `<p class="pdx-period-read">当前周期：${S(period.label)} vs ${S(period.prevLabel)}</p>` +
        `<div class="pdx-split">
          <div><h4>本期新增 / 重启使用</h4>${chips(fresh, '本期没有新英雄。')}</div>
          <div><h4>上期用过、本期未用</h4>${chips(gone, '上期用过的英雄本期都还在用。')}</div>
        </div>` +
        table(head, visible.map(rowOf), 'is-period') +
        (rest.length ? `<details class="pdx-details"><summary>其余 ${fmt(rest.length)} 个英雄</summary>${table(head, rest.map(rowOf), 'is-period')}</details>` : ''),
        '英雄池变化只说明使用分布变了，不等于英雄强度变化；上期未用的英雄不判胜率变化。'));
    }
    return out;
  }

  /* ── 模块 3：逐局表现与趋势 ──────────────────────────────────────── */
  function sparkBins(rows) {
    const rated = rows.filter((r) => typeof r.rating === 'number');
    if (rated.length < 2) return empty('带评分的局不足 2 场。');
    const size = Math.max(4, Math.ceil(rated.length / 12));
    const bins = [];
    for (let i = 0; i < rated.length; i += size) {
      const part = rated.slice(i, i + size);
      bins.push({from: part[0].day || '', n: part.length,
        avg: mean(part, (r) => r.rating), lo: Math.min(...part.map((r) => r.rating)),
        hi: Math.max(...part.map((r) => r.rating)), wins: win(part).wins});
    }
    const w = 1000, hgt = 190, pad = 30;
    const lo = Math.floor(Math.min(...bins.map((b) => b.lo)) - 0.5);
    const hi = Math.ceil(Math.max(...bins.map((b) => b.hi)) + 0.5);
    const span = Math.max(1, hi - lo);
    const x = (i) => pad + i * (w - pad * 2) / Math.max(1, bins.length - 1);
    const y = (v) => hgt - 28 - (v - lo) / span * (hgt - 56);
    const line = bins.map((b, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(b.avg).toFixed(1)}`).join(' ');
    const grid = [0, 0.5, 1].map((k) => {
      const v = lo + span * k;
      return `<line x1="${pad}" y1="${y(v).toFixed(1)}" x2="${w - pad}" y2="${y(v).toFixed(1)}" class="pdx-grid"/>
        <text x="4" y="${(y(v) + 4).toFixed(1)}" class="pdx-axis">${v.toFixed(1)}</text>`;
    }).join('');
    const dots = bins.map((b, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(b.avg).toFixed(1)}" r="5" class="pdx-dot">
      <title>${S(b.from)} · ${fmt(b.n)} 局 · 均分 ${N(b.avg, 2)} · ${fmt(b.wins)} 胜</title></circle>`).join('');
    const labels = bins.map((b, i) => i % 2 === 0 || i === bins.length - 1
      ? `<text x="${x(i).toFixed(1)}" y="${hgt - 6}" text-anchor="middle" class="pdx-axis">${S(String(b.from).slice(5))}</text>` : '').join('');
    return `<svg class="pdx-spark" viewBox="0 0 ${w} ${hgt}" role="img" aria-label="全量评分走势">
      ${grid}<path d="${line}" class="pdx-spark-line"/>${dots}${labels}</svg>`;
  }
  function buildTrend(c) {
    const out = [];
    const rows = c.rows, desc = c.desc;
    const ratings = rows.map((r) => r.rating).filter((v) => typeof v === 'number');

    /* 时间维度四张卡放在趋势模块最前：先看周期口径与逐日变化，再看全量异常与极值。 */
    out.push(...buildTime(c));

    // 05 全量评分走势
    out.push(card('05', '全量评分走势',
      `<b>${fmt(ratings.length)} 局</b>有营地评分，整体均值 <b>${N(mean(ratings), 2)}</b>、波动 <b>±${N(sd(ratings), 2)}</b>。`,
      kpis([['有评分场次', fmt(ratings.length), '营地 gradeGame'],
        ['平均评分', N(mean(ratings), 2), '全量'],
        ['评分标准差', `±${N(sd(ratings), 2)}`, '越小越稳'],
        ['训练日跨度', fmt(c.detail.summary?.days || 0), '按营地面板日期']]) + sparkBins(rows),
      '按时间顺序每若干局分一箱画均值，点上是该箱最低 / 最高评分；金点不表示胜负，胜负在逐局明细里。'));

    // 06 评分异常检测（近 3 / 5 / 10 vs 历史基线）
    {
      const base = ratings.slice(0, Math.max(0, ratings.length - 10));
      const baseMean = mean(base), baseSd = sd(base);
      const windows = [3, 5, 10].map((n) => {
        const part = ratings.slice(-n);
        const m = mean(part);
        const delta = m == null || baseMean == null ? null : m - baseMean;
        const half = baseSd == null || !part.length ? 0 : 1.96 * baseSd / Math.sqrt(part.length);
        const abnormal = delta != null && baseSd != null && Math.abs(delta) > half;
        return [`<b>近 ${fmt(n)} 局</b>`, fmt(part.length), N(m, 2),
          baseMean == null ? '—' : `${N(baseMean - half, 2)} ~ ${N(baseMean + half, 2)}`,
          signed(delta, 2), abnormal ? '<b class="is-hi">超出区间</b>' : '在区间内'];
      });
      const abnormalCount = windows.filter((r) => r[5].includes('超出')).length;
      out.push(card('06', '评分异常检测',
        `以 <b>${fmt(base.length)} 局</b>历史评分做基线（<b>${N(baseMean, 2)} ± ${N(baseSd, 2)}</b>），近 3 / 5 / 10 局里有 <b>${fmt(abnormalCount)} 个窗口</b>越出 95% 区间。`,
        table(['窗口', '实际局数', '窗口均分', '基线 95% 区间', '与基线差', '判定'], windows),
        '区间 = 基线均值 ± 1.96 × 基线标准差 ÷ √窗口局数；基线取最早的部分对局，不含被检测的窗口。'));
    }

    // 07 胜率异常检测 + 置信区间
    {
      const byDay = group(rows, (r) => r.day || '未标注日期');
      const total = win(rows);
      const items = [...byDay].map(([day, list]) => {
        const w = win(list), ci = wilson(w.wins, w.decided);
        return [S(day), fmt(list.length), `${fmt(w.wins)} / ${fmt(w.decided)}`, P(w.rate),
          ci[0] == null ? '—' : `${N(ci[0], 1)}% ~ ${N(ci[1], 1)}%`,
          total.rate != null && w.rate != null ? signed(w.rate - total.rate, 1) : '—'];
      }).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
      const allCi = wilson(total.wins, total.decided);
      out.push(card('07', '胜率异常检测',
        `按训练日切 <b>${fmt(byDay.size)} 个窗口</b>，整体胜率 <b>${P(total.rate)}</b>（95% 区间 <b>${N(allCi[0], 1)}% ~ ${N(allCi[1], 1)}%</b>）。`,
        table(['训练日', '场次', '胜 / 有胜负', '胜率', 'Wilson 95% 区间', '与整体差'], items),
        '置信区间用 Wilson 法，小样本会自动变宽；区间与整体重叠的窗口不判为异常。'));
    }

    // 08 稳定性分层
    {
      const layers = [
        ['按英雄', (r) => r.hero], ['按分路', (r) => r.lane], ['按对手', (r) => r.opponentTeam || '未标注'],
      ];
      const body = layers.map(([label, fn]) => {
        const g = group(rows, fn);
        const items = [...g].filter(([, list]) => list.length >= 2)
          .sort((a, b) => b[1].length - a[1].length).slice(0, 8).map(([k, list]) => {
            const rs = list.map((r) => r.rating).filter((v) => typeof v === 'number');
            const ks = list.map((r) => r.kda).filter((v) => typeof v === 'number');
            const km = mean(ks), ksd = sd(ks);
            return [S(k), fmt(list.length), N(mean(rs), 2), `±${N(sd(rs), 2)}`,
              N(km, 2), km ? N(ksd / km, 2) : '—'];
          });
        return `<div class="pdx-layer"><h4>${S(label)}</h4>${table(['分组', '场次', '评分均值', '评分波动', 'KDA 均值', 'KDA 变异系数'], items)}</div>`;
      }).join('');
      out.push(card('08', '稳定性分析',
        `按英雄 / 分路 / 对手三层各看 <b>8 个分组</b>，评分波动与 KDA 变异系数一起读。`,
        body, '变异系数 = 标准差 ÷ 均值，越小越稳；只列 ≥ 2 局的分组，1 局不参与波动统计。'));
    }

    // 09 英雄切换影响
    {
      const recent = rows.slice(-20), prior = rows.slice(-40, -20);
      const dist = (list) => {
        const g = group(list, (r) => r.heroType || '未分类');
        return [...g].sort((a, b) => b[1].length - a[1].length).slice(0, 5)
          .map(([k, v]) => `${k} ${fmt(v.length)}`).join(' · ');
      };
      const capDist = (list) => {
        const counts = new Map();
        for (const r of list) for (const cap of r.caps || []) counts.set(cap, (counts.get(cap) || 0) + 1);
        return [...counts].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `${k} ${fmt(v)}`).join(' · ');
      };
      const rowsHtml = [
        ['<b>此前 20 局</b>', fmt(prior.length), P(win(prior).rate), N(mean(prior, (r) => r.rating), 2), S(dist(prior)), S(capDist(prior))],
        ['<b>最近 20 局</b>', fmt(recent.length), P(win(recent).rate), N(mean(recent, (r) => r.rating), 2), S(dist(recent)), S(capDist(recent))],
        ['<b>变化</b>', '—', signed(win(recent).rate == null || win(prior).rate == null ? null : win(recent).rate - win(prior).rate, 1),
          signed(mean(recent, (r) => r.rating) == null || mean(prior, (r) => r.rating) == null ? null : mean(recent, (r) => r.rating) - mean(prior, (r) => r.rating), 2),
          '见上两行职业分布', '见上两行能力分布'],
      ];
      const rateDelta = win(recent).rate == null || win(prior).rate == null ? null : win(recent).rate - win(prior).rate;
      out.push(card('09', '英雄切换影响',
        `最近 20 局胜率比此前 20 局<b>${rateDelta == null ? '—' : rateDelta >= 0 ? '高' : '低'} <b>${N(Math.abs(rateDelta || 0), 1)}</b> 个百分点</b>，同期英雄职业与能力标签分布一并对照。`,
        table(['窗口', '场次', '胜率', '评分', '英雄职业分布（前 5）', '能力标签分布（前 4）'], rowsHtml),
        '只说明「表现变化是否伴随英雄类型 / 使用分布改变」，不从时间先后推因果。'));
    }

    // 10 高分局 / 低分局（不再叫关键局）
    {
      const rated = rows.filter((r) => typeof r.rating === 'number').sort((a, b) => b.rating - a.rating);
      const line = (r) => `<div class="pdx-extreme"><span>${dateOf(r)}</span>${heroCell(r.hero)}
        <small>${S(r.opponentTeam || '对手未标注')} · ${S(r.lane)}</small>${resTag(r.result)}
        <b>${N(r.rating, 1)}</b><small>KDA ${N(r.kda, 1)}</small>${gameLink(r)}</div>`;
      const high = rated.slice(0, 5), low = rated.slice(-5).reverse();
      out.push(card('10', '高分局 / 低分局',
        `全量 <b>${fmt(rated.length)} 局</b>评分里，最高 <b>${N(rated[0]?.rating, 1)}</b>、最低 <b>${N(rated[rated.length - 1]?.rating, 1)}</b>，各列 5 局。`,
        `<div class="pdx-split"><div><h4>高分局 · 评分最高 5 局</h4>${high.map(line).join('')}</div>
         <div><h4>低分局 · 评分最低 5 局</h4>${low.map(line).join('')}</div></div>`,
        '这两组是评分极值，不是比赛关键局；「关键局」要有系列赛节点证据，见下一张。'));
    }

    // 11 系列赛节点局
    {
      const withSeries = rows.filter((r) => r.series);
      const bySeries = group(withSeries, (r) => r.series.id);
      const nodes = [];
      for (const [sid, list] of bySeries) {
        const best = list[0].series.bestOf || 3;
        const last = [...list].sort((a, b) => (a.series.index || 0) - (b.series.index || 0)).at(-1);
        if (!last) continue;
        nodes.push([S(String(last.series.date || '').slice(0, 10)), S(sid),
          `BO${fmt(best)} 第 ${fmt(last.series.index)} 局`, heroCell(last.hero),
          S(last.opponentTeam || '对手未标注'), resTag(last.result), N(last.rating, 1), gameLink(last)]);
      }
      out.push(card('11', '系列赛节点局',
        `该选手参与 <b>${fmt(bySeries.size)} 个系列赛</b>、<b>${fmt(withSeries.length)} 局</b>有赛制归属，下列是每个系列赛的最后一局。`,
        table(['日期', '系列赛', '节点', '英雄', '对手', '结果', '评分', ''], nodes.slice(0, 20)),
        '系列赛归属来自训练台账 training_series_games；只有带赛制记录的局才称得上关键局。'));
    }

    // 12 逐局明细
    {
      const rowsHtml = desc.slice(0, 30).map((r) => [dateOf(r), S(r.opponentTeam || '对手未标注'),
        heroCell(r.hero), S(r.lane), resTag(r.result), N(r.kda, 2), N(r.gpm),
        N(r.hdpm), P(r.participation), N(r.rating, 1), gameLink(r)]);
      out.push(card('12', '逐局明细',
        `按开赛时间倒序列出最近 <b>${fmt(Math.min(30, desc.length))} / ${fmt(desc.length)} 局</b>，每行可直达单局复盘。`,
        table(['时间', '对手', '英雄', '分路', '结果', 'KDA', '分均经济', '分均对英雄输出', '参团率', '评分', ''], rowsHtml),
        '分均输出统一用 totalHeroHurtCnt；总输出与输出占比在综合画像的口径表里单独说明。'));
    }
    return out;
  }

  /* ── 模块 4：对位与反制 ──────────────────────────────────────────── */
  function buildMatchup(c) {
    const out = [];
    const duels = c.rows.filter((r) => r.foe);
    const diffOf = (r) => r.gold - (r.foe.gold || 0);

    // 01 终局同分路对位
    {
      const rowsHtml = c.desc.filter((r) => r.foe).slice(0, 20).map((r) => [dateOf(r),
        heroCell(r.hero), `<span class="pdx-hero"><i class="pl-hp">${portrait(r.foe.hero)}</i>${S(r.foe.name)}<small>${S(r.foe.hero)}</small></span>`,
        S(r.lane), signed(diffOf(r)), resTag(r.result), gameLink(r)]);
      const avg = mean(duels, diffOf);
      const ahead = duels.filter((r) => diffOf(r) > 0).length;
      out.push(card('01', '终局同分路对位',
        `<b>${fmt(duels.length)} / ${fmt(c.rows.length)} 局</b>能找到同分路对手，场均终局经济差 <b>${signed(avg)}</b>，领先 <b>${fmt(ahead)} 局</b>。`,
        kpis([['可对位局数', fmt(duels.length), '全量，不止最近 10 局'],
          ['场均经济差', signed(avg), '本人 − 同分路对手'],
          ['领先局', `${fmt(ahead)} / ${fmt(duels.length)}`, '终局经济为正'],
          ['对位胜率', P(win(duels).rate), '这些局的胜负']]) +
        table(['时间', '本人英雄', '同分路对手', '分路', '终局经济差', '结果', ''], rowsHtml),
        '这是终局结算口径的对位，只看双方最终经济；对线期过程对抗在下一张单独列。'));
    }

    // 02 对线期过程对抗（面板代理，明确区分）
    {
      const rowsHtml = c.laneOrder.map((lane) => {
        const list = duels.filter((r) => r.lane === lane);
        if (!list.length) return null;
        const csDiff = mean(list, (r) => (r.cs || 0) - (r.foe.cs || 0));
        const kdaDiff = mean(list, (r) => (r.kda || 0) - (r.foe.kda || 0));
        const partDiff = mean(list, (r) => (r.participation || 0) - (r.foe.participation || 0));
        return [`<b>${S(lane)}</b>`, fmt(list.length), signed(csDiff, 1), signed(kdaDiff, 2),
          signed(partDiff, 1), P(win(list).rate)];
      }).filter(Boolean);
      out.push(card('02', '对线期对抗 · 面板代理',
        `<b>${fmt(duels.length)} 局</b>同分路对位的补刀差、KDA 差、参团差按分路陈列，作为对线结果的面板代理。`,
        table(['分路', '对位局数', '补刀差', 'KDA 差', '参团率差', '这些局胜率'], rowsHtml),
        '对线期 1v1、早期死亡时间点、支援到场归回放时间轴；本卡是终局代理口径，不与上一张的终局经济差混读，不称「对线强弱」。'));
    }

    // 03 英雄对位矩阵
    {
      const mine = [...group(duels, (r) => r.hero)].sort((a, b) => b[1].length - a[1].length).slice(0, 6);
      const foes = [...group(duels, (r) => r.foe.hero)].sort((a, b) => b[1].length - a[1].length).slice(0, 6);
      const heads = ['本人英雄 \\ 对手英雄', ...foes.map(([k]) => S(k || '未知'))];
      const rowsHtml = mine.map(([hero]) => [heroCell(hero), ...foes.map(([foeHero]) => {
        const cell = duels.filter((r) => r.hero === hero && r.foe.hero === foeHero);
        if (!cell.length) return '<span class="pdx-none">—</span>';
        const w = win(cell), d = mean(cell, diffOf);
        return `<span class="pdx-cell"><b>${fmt(cell.length)} 局</b><small>胜 ${P(w.rate)} · ${signed(d)} 金</small></span>`;
      })]);
      out.push(card('03', '英雄对位矩阵',
        `本人常用 <b>${fmt(mine.length)} 个英雄</b> × 对手同分路 <b>${fmt(foes.length)} 个英雄</b>，格子给历史场次、胜率与终局经济差。`,
        table(heads, rowsHtml, 'is-matrix'),
        '矩阵只统计「本人英雄 × 同分路对手英雄」同时成立的局，空格表示这批对局里没出现过这个组合。'));
    }

    // 04 对位表现趋势
    {
      const pairs = group(duels, (r) => `${r.hero} vs ${r.foe.hero}`);
      const items = [...pairs].filter(([, list]) => list.length >= 2)
        .sort((a, b) => b[1].length - a[1].length).slice(0, 10).map(([key, list]) => {
          const half = Math.ceil(list.length / 2);
          const early = list.slice(0, half), late = list.slice(half);
          return [S(key), fmt(list.length), P(win(early).rate), signed(mean(early, diffOf)),
            P(win(late).rate), signed(mean(late, diffOf)),
            S(String(early[0].day || '')) + ' → ' + S(String(late[late.length - 1].day || ''))];
        });
      out.push(card('04', '对位表现趋势',
        `<b>${fmt(items.length)} 组</b>相同英雄对位出现过 2 次以上，按时间前后各切一半对照结果与经济差。`,
        table(['英雄对位', '总场次', '前半胜率', '前半经济差', '后半胜率', '后半经济差', '时间跨度'], items),
        '同一对位跨时间比较，样本不足 2 局的组合不进表。'));
    }

    // 05 反制胜率
    {
      const byHero = group(duels, (r) => r.hero);
      const rowsHtml = [];
      for (const [hero, list] of byHero) {
        if (list.length < 3) continue;
        const byFoe = group(list, (r) => r.foe.hero);
        for (const [foeHero, cell] of byFoe) {
          const w = win(cell);
          rowsHtml.push([heroCell(hero), heroCell(foeHero), fmt(cell.length),
            `${fmt(w.wins)} / ${fmt(w.decided)}`, P(w.rate), signed(mean(cell, diffOf))]);
        }
      }
      rowsHtml.sort((a, b) => Number(String(b[2])) - Number(String(a[2])));
      out.push(card('05', '反制胜率',
        `本人常用英雄（≥ 3 局）面对指定敌方英雄共 <b>${fmt(rowsHtml.length)} 组</b>历史交手，按场次排序。`,
        table(['本人英雄', '敌方同分路英雄', '场次', '胜 / 有胜负', '胜率', '场均经济差'], rowsHtml.slice(0, 24)),
        '这里的「面对」是同分路对位；敌方组合胜率需要同一局里多个指定英雄同时出现，本表按单个对手英雄统计。'));
    }

    // 06 对位差异来源
    {
      const layers = [
        ['按英雄', group(duels, (r) => r.hero)],
        ['按阵营', group(duels, (r) => r.camp || '未标注')],
        ['按对手', group(duels, (r) => r.opponentTeam || '未标注')],
        ['按时长', group(duels, (r) => (r.duration || 0) <= 12 ? '≤ 12 分钟' : (r.duration || 0) <= 16 ? '12–16 分钟' : '> 16 分钟')],
      ];
      const body = layers.map(([label, g]) => {
        const items = [...g].filter(([, list]) => list.length >= 2)
          .sort((a, b) => b[1].length - a[1].length).slice(0, 8).map(([k, list]) =>
            [S(k), fmt(list.length), signed(mean(list, diffOf)), P(win(list).rate),
              N(mean(list, (r) => r.gpm))]);
        return `<div class="pdx-layer"><h4>${S(label)}</h4>${table(['条件', '场次', '终局经济差', '胜率', '本人分均经济'], items)}</div>`;
      }).join('');
      out.push(card('06', '对位差异来源',
        `把 <b>${fmt(duels.length)} 局</b>终局经济差按英雄 / 阵营 / 对手 / 时长四组条件拆开看，找差异集中在哪一类条件。`,
        body, '这是条件分层描述，不是因果归因；同一局会同时出现在多个分层里。'));
    }
    return out;
  }

  /* ── 模块 5：搭档、阵容与 BP ──────────────────────────────────────── */
  function buildTeam(c) {
    const out = [];
    const rows = c.rows;

    // 搭档聚合
    const partnerMap = new Map();
    for (const r of rows) {
      for (const mate of r.mates || []) {
        if (!mate.name) continue;
        const it = partnerMap.get(mate.name) || {name: mate.name, games: 0, wins: 0, decided: 0,
          lanes: new Map(), heroes: new Map(), pairs: new Map(), days: [], opps: new Map()};
        it.games += 1;
        if (r.result === 'win' || r.result === 'loss') {
          it.decided += 1;
          if (r.result === 'win') it.wins += 1;
        }
        it.lanes.set(mate.lane, (it.lanes.get(mate.lane) || 0) + 1);
        if (mate.hero) it.heroes.set(mate.hero, (it.heroes.get(mate.hero) || 0) + 1);
        if (mate.hero && r.hero) {
          const key = `${r.hero} × ${mate.hero}`;
          const pair = it.pairs.get(key) || {games: 0, wins: 0, decided: 0};
          pair.games += 1;
          if (r.result === 'win' || r.result === 'loss') {
            pair.decided += 1;
            if (r.result === 'win') pair.wins += 1;
          }
          it.pairs.set(key, pair);
        }
        if (r.day) it.days.push(r.day);
        if (r.opponentTeam) it.opps.set(r.opponentTeam, (it.opps.get(r.opponentTeam) || 0) + 1);
        partnerMap.set(mate.name, it);
      }
    }
    const partners = [...partnerMap.values()].sort((a, b) => b.games - a.games || b.wins - a.wins);
    const topOf = (map) => [...map].sort((a, b) => b[1] - a[1])[0]?.[0] || '—';

    // 01 固定搭档
    {
      const items = partners.slice(0, 10).map((p) => {
        const w = {rate: p.decided ? p.wins / p.decided * 100 : null};
        const days = [...new Set(p.days)].sort();
        const cond = [...p.opps].sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => `${k} ${v} 局`).join(' · ');
        return [`<b>${S(p.name)}</b>`, S(topOf(p.lanes)), fmt(p.games), P(w.rate),
          S(topOf(p.heroes)), S(topOf(p.pairs) || '—'),
          S(days.length ? `${days[0]} ~ ${days[days.length - 1]}` : '—'), S(cond || '—')];
      });
      out.push(card('01', '固定搭档表现',
        `同场最多的是 <b>${S(partners[0]?.name || '—')} ${fmt(partners[0]?.games || 0)} 局</b>（组合胜率 <b>${P(partners[0]?.decided ? partners[0].wins / partners[0].decided * 100 : null)}</b>）。`,
        table(['搭档', '常打分路', '同场场次', '组合胜率', '搭档常用英雄', '最常见双英雄组合', '共同参赛日期', '共同对手条件'], items),
        '同场 = 同一局同阵营；组合胜率只算有胜负的局，日期与对手条件给的是这批共同参赛的范围。'));
    }

    // 02 双英雄组合
    {
      const allPairs = new Map();
      for (const p of partners) {
        for (const [key, v] of p.pairs) {
          const it = allPairs.get(key) || {games: 0, wins: 0, decided: 0, mate: p.name};
          it.games += v.games; it.wins += v.wins; it.decided += v.decided;
          allPairs.set(key, it);
        }
      }
      const items = [...allPairs].filter(([, v]) => v.games >= 2)
        .sort((a, b) => b[1].games - a[1].games).slice(0, 16).map(([key, v]) =>
          [S(key), S(v.mate), fmt(v.games), `${fmt(v.wins)} / ${fmt(v.decided)}`,
            P(v.decided ? v.wins / v.decided * 100 : null)]);
      out.push(card('02', '双英雄组合',
        `「本人英雄 × 搭档英雄」共 <b>${fmt(allPairs.size)} 组</b>，其中 <b>${fmt(items.length)} 组</b>出场 ≥ 2 局。`,
        table(['双英雄组合', '搭档', '场次', '胜 / 有胜负', '组合胜率'], items),
        '这一张统计具体英雄组合，不只是两人同场；1 局组合不进表。'));
    }

    // 03 五人阵容
    {
      const lineups = group(rows, (r) => [...(r.lineup || [])].sort().join(' · '));
      const items = [...lineups].sort((a, b) => b[1].length - a[1].length).slice(0, 12).map(([key, list]) =>
        [`<span class="pdx-lineup">${key.split(' · ').map((x) => heroCell(x)).join('')}</span>`,
          fmt(list.length), `${fmt(win(list).wins)} / ${fmt(win(list).decided)}`, P(win(list).rate),
          N(mean(list, (r) => r.rating), 1), S(String(list[list.length - 1].day || ''))]);
      const repeated = [...lineups.values()].filter((l) => l.length >= 2).length;
      out.push(card('03', '五人阵容查询',
        `该选手参与过 <b>${fmt(lineups.size)} 套</b>不同五英雄阵容，其中 <b>${fmt(repeated)} 套</b>重复出场；每套阵容单独给历史胜率。`,
        table(['五人阵容', '场次', '胜 / 有胜负', '胜率', '本人评分', '最近使用'], items),
        '阵容按同阵营五个英雄的名字集合归并，与站位顺序无关。'));
    }

    // 04 阵容类型适配（能力覆盖自动分层，代替人工标签）
    {
      const coverage = new Map();
      for (const r of rows) {
        const caps = new Set();
        for (const hero of r.lineup || []) for (const cap of (c.meta[hero] || {}).caps || []) caps.add(cap);
        const n = caps.size;
        const tier = n >= 7 ? '覆盖 ≥ 7 项' : n >= 5 ? '覆盖 5–6 项' : '覆盖 ≤ 4 项';
        const it = coverage.get(tier) || {games: 0, wins: 0, decided: 0, caps: []};
        it.games += 1;
        if (r.result === 'win' || r.result === 'loss') {
          it.decided += 1;
          if (r.result === 'win') it.wins += 1;
        }
        it.caps.push(n);
        coverage.set(tier, it);
      }
      const items = [...coverage].sort((a, b) => b[1].games - a[1].games).map(([tier, v]) =>
        [`<b>${S(tier)}</b>`, fmt(v.games), P(v.decided ? v.wins / v.decided * 100 : null),
          N(mean(v.caps), 1), N(mean(rows.filter((r) => {
            const caps = new Set();
            for (const hero of r.lineup || []) for (const cap of (c.meta[hero] || {}).caps || []) caps.add(cap);
            return caps.size >= 7 ? tier === '覆盖 ≥ 7 项' : caps.size >= 5 ? tier === '覆盖 5–6 项' : tier === '覆盖 ≤ 4 项';
          }), (r) => r.rating), 1)]);
      out.push(card('04', '阵容类型适配',
        `按五人阵容覆盖的 <b>9 项战术能力</b>自动分层，覆盖最广的一组打了 <b>${fmt(Math.max(...[...coverage.values()].map((v) => v.games)))} 局</b>。`,
        table(['阵容功能覆盖', '场次', '胜率', '平均覆盖项', '本人评分'], items),
        '分层由英雄能力标签自动算出，不依赖人工维护的战术体系标签。'));
    }

    // 05 阵容变化
    {
      const recent = rows.slice(-20), prior = rows.slice(-40, -20);
      const dist = (list, key) => {
        const g = group(list, key);
        return [...g].sort((a, b) => b[1].length - a[1].length).slice(0, 6)
          .map(([k, v]) => `${k} ${fmt(v.length)}`).join(' · ');
      };
      const items = [
        ['<b>此前 20 局 · 队友英雄</b>', S(dist(prior, (r) => (r.mates || [])[0]?.hero || '—'))],
        ['<b>最近 20 局 · 队友英雄</b>', S(dist(recent, (r) => (r.mates || [])[0]?.hero || '—'))],
        ['<b>此前 20 局 · 敌方阵容</b>', S(dist(prior, (r) => (r.enemyLineup || []).slice().sort().join('·')))],
        ['<b>最近 20 局 · 敌方阵容</b>', S(dist(recent, (r) => (r.enemyLineup || []).slice().sort().join('·')))],
        ['<b>同期评分</b>', `${N(mean(prior, (r) => r.rating), 2)} → ${N(mean(recent, (r) => r.rating), 2)}`],
      ];
      out.push(card('05', '阵容变化分析',
        `对比最近与此前各 20 局的队友英雄、敌方阵容，同期本人评分从 <b>${N(mean(prior, (r) => r.rating), 2)}</b> 到 <b>${N(mean(recent, (r) => r.rating), 2)}</b>。`,
        table(['窗口 / 维度', '出现最多的组合'], items),
        '敌方阵容按五个英雄集合归并；这里描述分布变化，不把变化当成表现变化的原因。'));
    }

    // 06 异常归因辅助
    {
      const rated = rows.filter((r) => typeof r.rating === 'number').sort((a, b) => a.rating - b.rating);
      const low = rated.slice(0, Math.max(3, Math.ceil(rated.length * 0.2)));
      const layers = [
        ['英雄', (r) => r.hero], ['分路', (r) => r.lane], ['对手', (r) => r.opponentTeam || '未标注'],
        ['阵营', (r) => r.camp || '未标注'], ['阵容覆盖', (r) => {
          const caps = new Set();
          for (const hero of r.lineup || []) for (const cap of (c.meta[hero] || {}).caps || []) caps.add(cap);
          return caps.size >= 7 ? '≥ 7 项' : caps.size >= 5 ? '5–6 项' : '≤ 4 项';
        }],
      ];
      const items = layers.map(([label, fn]) => {
        const g = group(low, fn);
        const top = [...g].sort((a, b) => b[1].length - a[1].length).slice(0, 3);
        return [S(label), fmt(low.length), S(top.map(([k, v]) => `${k} ${v.length} 局`).join(' · ')),
          P(win(low).rate), N(mean(low, (r) => r.rating), 2)];
      });
      out.push(card('06', '异常归因辅助',
        `评分最低的 <b>${fmt(low.length)} 局</b>（<b>${P(win(low).rate)}</b> 胜率、均分 <b>${N(mean(low, (r) => r.rating), 2)}</b>）按五组条件拆开看集中在哪里。`,
        table(['条件维度', '低分局数', '最集中的前 3 个条件', '这批局胜率', '这批局均分'], items),
        '条件分层只帮教练圈定该回看哪几局，不自动给出原因。'));
    }

    // 07 全局 BP 英雄消耗
    {
      const withSeries = rows.filter((r) => r.series);
      const bySeries = group(withSeries, (r) => r.series.id);
      const allHeroes = new Set(rows.map((r) => r.hero).filter(Boolean));
      const items = [...bySeries].map(([sid, list]) => {
        const ordered = [...list].sort((a, b) => (a.series.index || 0) - (b.series.index || 0));
        const best = ordered[0].series.bestOf || 3;
        const used = ordered.map((r) => r.hero);
        const left = [...allHeroes].filter((x) => !used.includes(x)).length;
        return [S(String(ordered[0].series.date || '').slice(0, 10)), S(sid), `BO${fmt(best)}`,
          S(used.map((x, i) => `第 ${i + 1} 局 ${x}`).join(' · ')),
          fmt(used.length), fmt(left), `<div class="pdx-mini-track"><i style="width:${clamp(used.length / best * 100)}%"></i></div>`];
      }).slice(0, 20);
      out.push(card('07', '全局 BP 英雄消耗',
        `<b>${fmt(bySeries.size)} 个系列赛</b>、<b>${fmt(withSeries.length)} 局</b>有赛制归属；本人历史英雄池共 <b>${fmt(allHeroes.size)} 个</b>。`,
        table(['日期', '系列赛', '赛制', '已用英雄（按局序）', '已用', '池内剩余', '赛程进度'], items),
        '全局 BP 下同一系列赛已用英雄不再可用；「池内剩余」= 本人历史用过的英雄减去该系列赛已用。'));
    }

    // 08 英雄替代候选
    {
      const common = [...group(rows, (r) => r.hero)].filter(([, list]) => list.length >= 3)
        .sort((a, b) => b[1].length - a[1].length).slice(0, 5);
      const exp = group(rows, (r) => r.hero);
      const items = [];
      for (const [hero, list] of common) {
        const base = c.meta[hero] || {};
        const lane = base.lane || list[0].heroDefaultLane || list[0].lane;
        const caps = base.caps || [];
        const candidates = Object.entries(c.meta).filter(([name, tag]) => {
          if (name === hero || !tag.lane || tag.lane !== lane) return false;
          return (tag.caps || []).filter((x) => caps.includes(x)).length >= 2;
        }).map(([name, tag]) => ({name, tag, used: (exp.get(name) || []).length}))
          .sort((a, b) => b.used - a.used || (b.tag.caps || []).filter((x) => caps.includes(x)).length
            - (a.tag.caps || []).filter((x) => caps.includes(x)).length).slice(0, 3);
        items.push([heroCell(hero), fmt(list.length), S(lane), S(caps.join(' · ') || '—'),
          candidates.map((x) => `${heroCell(x.name)}<small>${x.used ? `本人 ${x.used} 局` : '未用过'}</small>`).join('') || '—']);
      }
      out.push(card('08', '英雄替代候选',
        `为 <b>${fmt(items.length)} 个常用英雄</b>按同分路 + 能力标签重叠 ≥ 2 项找候选，优先列本人已有使用经验的。`,
        table(['常用英雄', '场次', '默认分路', '能力标签', '可考察的替代英雄（最多 3 个）'], items),
        '候选来自英雄能力矩阵，按标签相似 + 本人实际使用经验排序，是考察名单不是上场推荐。'));
    }
    return out;
  }

  /* ── 页面装配 ────────────────────────────────────────────────────── */
  function render(board, name, detail) {
    const rows = (detail && detail.rows) || [];
    if (!rows.length) {
      const back = st && st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">
        <header class="hero-masthead"><div class="page-intro"><div class="pls-head">
          <a class="hero-back" href="${S(back.href)}">← ${S(back.label)}</a>
          <div class="pls-id"><div><h1>未找到这名选手</h1>
            <p>链接里的游戏名在当前营地面板里没有出场记录。</p></div></div></div></div></header>
        <div class="hero-detail-grid"><section class="section"><div class="section-heading"><div>
          <h2>回到选手档案</h2><p>本队全部游戏名都在选手档案页，未认领的会标出来。</p></div></div>
          <p class="pl-note"><a class="pl-link" href="#playerarchive">← 选手档案</a></p></section></div></div>`;
    }
    const identity = detail.identity || {};
    const byLane = group(rows, (r) => r.lane);
    const laneOrder = LANES.filter((l) => byLane.has(l));
    for (const lane of byLane.keys()) if (!laneOrder.includes(lane)) laneOrder.push(lane);
    const mix = identity.laneMix || [];
    const mainLane = (mix[0] && mix[0].lane) || laneOrder[0] || '未记录';
    const ctx = {
      board, name, detail, rows, identity,
      desc: [...rows].reverse(),
      laneSamples: detail.laneSamples || {}, laneDistributions: detail.laneDistributions || {},
      meta: detail.heroMeta || {},
      opponents: detail.opponents || [], byLane, laneOrder, mainLane,
      byHero: group(rows, (r) => r.hero),
    };
    const total = win(rows);
    const mainList = byLane.get(mainLane) || [];
    const recent10 = rows.slice(-10);
    const baseRatings = rows.slice(0, Math.max(0, rows.length - 10)).map((r) => r.rating).filter((v) => typeof v === 'number');
    const recentRating = mean(recent10, (r) => r.rating);
    const seriesGames = rows.filter((r) => r.series).length;
    const kpiHtml = `<div class="hero-kpi pl-kpi" role="group" aria-label="关键指标">${[
      ['出场', `${fmt(rows.length)} 局`, `${fmt(total.wins)} 胜 ${fmt(total.decided - total.wins)} 负`],
      ['胜率', P(total.rate), `${fmt(total.wins)} / ${fmt(total.decided)} 有胜负`],
      ['主位置', S(mainLane), `${fmt(mainList.length)} 局 · 胜率 ${P(win(mainList).rate)}`],
      ['副位置覆盖', `${fmt(laneOrder.length - 1)} 个位置`, `${fmt(rows.length - mainList.length)} 局`],
      ['英雄池', `${fmt(ctx.byHero.size)} 个英雄`, `覆盖 ${fmt(new Set(rows.map((r) => r.heroType).filter(Boolean)).size)} 类职业`],
      ['近 10 局评分', N(recentRating, 2), baseRatings.length ? `此前基线 ${N(mean(baseRatings), 2)}` : '基线样本不足'],
      ['系列赛', `${fmt(new Set(rows.filter((r) => r.series).map((r) => r.series.id)).size)} 场`, `${fmt(seriesGames)} 局有赛制归属`],
    ].map(([label, value, note]) => `<div class="hero-kpi-cell"><span>${S(label)}</span><strong>${value}</strong><p>${S(note)}</p></div>`).join('')}</div>`;

    const back = st && st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
    const backExtra = String(back.href).startsWith('#playerarchive')
      ? '' : `<a class="hero-back is-quiet" href="#playerarchive">选手档案</a>`;
    const head = `<header class="hero-masthead"><div class="page-intro"><div class="pls-head">
      <span class="pls-back-row"><a class="hero-back" href="${S(back.href)}">← ${S(back.label)}</a>${backExtra}</span>
      <div class="pls-id"><span class="pls-ava" aria-hidden="true">${S(String(name).trim().slice(0, 1) || '?')}</span>
        <div><h1>${S(name)}</h1><p>${S(mainLane)} · ${identity.side === 'own' ? '本队侧' : '对手侧'} · ${identity.bound ? '已认领' : '待认领昵称'} · ${fmt(laneOrder.length)} 个实际分路 · ${fmt(rows.length)} 局</p></div></div></div>
      <div class="intro-actions">${identity.bound ? '' : `<button class="control" data-pl-name="${S(name)}">命名并归队</button>`}<button class="control" data-pl-pick-b="${S(name)}">放入对比</button><button class="control" data-action="refresh">刷新数据</button></div></div>${kpiHtml}</header>`;

    const briefHtml = `<div class="hero-brief">全局 <b>${fmt(rows.length)} 局</b>、${fmt(total.wins)} 胜 ${fmt(total.decided - total.wins)} 负（胜率 <b>${P(total.rate)}</b>）。主位置 <b>${S(mainLane)} ${fmt(mainList.length)} 局</b>，另外 <b>${fmt(rows.length - mainList.length)} 局</b>分布在 ${fmt(laneOrder.length - 1)} 个副位置；所有分位、专项指标与排名都按各自实际分路计算，不再给统一综合分。</div>`;

    const modules = [
      ['portrait', '选手综合画像', '按实际分路看优势短板、统计特征与同位置对标', buildPortrait],
      ['heroes', '英雄池与英雄类型', '英雄使用、职业覆盖、能力标签与实际使用风格四层分开', buildHeroes],
      ['trend', '逐局表现与周期趋势', '周期对比、逐日走势、异常检测、稳定性、高分局与系列赛节点', buildTrend],
      ['matchup', '对位与反制分析', '终局对位与对线期代理分开，再看英雄对位矩阵与条件差异', buildMatchup],
      ['team', '搭档与阵容适配', '固定搭档、双英雄组合、五人阵容、全局 BP 消耗与替代候选', buildTeam],
    ];
    const nav = `<nav class="hero-anchor-nav" aria-label="模块快速导航">${modules.map(([, label], i) =>
      `<button type="button" data-hero-scroll="${i}">${S(label)}</button>`).join('')}</nav>`;
    const sections = modules.map(([key, label, sub, build]) =>
      block(label, sub, `<div class="pdx-cards">${build(ctx).join('')}</div>`, '', `data-pdx-module="${S(label)}" data-pdx-key="${S(key)}"`)).join('');
    return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${briefHtml}${nav}<div class="hero-detail-grid">${sections}</div></div>`;
  }

  return {render};
}
