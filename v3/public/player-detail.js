/* 选手详情页（2026-11-17 第三版：切片驱动的分析页）

   为什么重写这一版：
   上一版是「一张图装下所有东西」——46 个英雄全铺进矩形树图、8 个训练日全塞进
   热力网格、每张卡各自一个分路下拉。一个赛季下来训练日到 40+、英雄到 50+，
   图就开始挤、开始切边（7 栏面板里画 1200px 的图，右边被切掉 470px），
   教练也没法只看「近 5 日 × 游走 × 项羽」这一段。

   这一版的做法：
   1. 一个切片（范围 / 分路 / 英雄 / 对手 / 结果 / 英雄门槛）统领整页，
      所有卡都只看这一段，不再各卡一个分路下拉；
   2. 图按「占几栏」算宽度，绝不横向溢出；热力列多了横向滚动、行头吸左；
   3. 英雄默认画前 13 个，剩下的并入「其他 N 个英雄」，点方块 = 切到该英雄；
   4. 每张卡保留自己真正特有的一维（指标 / 越线方向 / 窗口 / 视角），
      不再重复问「哪条路」；
   5. 样本太少时给结论卡而不是画一堆碎图（低于门槛的英雄只报数量）。

   口径不变：所有分位、排名都按「这一局实际打的分路」算，不给统一综合分。 */
import {createPlayerViz} from './player-viz.js?v=20261126pdrefine1';
import { glyph } from './ui-icons.js';

export function createPlayerDetail(h) {
  const {esc, fmt, portrait, block, empty, st, profile} = h;
  const V = createPlayerViz({esc, fmt});
  const {S, N, isNum, clamp, selBar, panel, grid, w} = V;
  const P = (v, d = 1) => (isNum(v) ? fmt(v, d) + '%' : '—');
  const signed = (v, d = 0) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmt(v, d)}` : '—');

  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

  /* ── 同分路「标准线」：赛训组评级规则 ──────────────────────────────
     与设置页 / 对局复盘共用 /api/v3/grade-rules：没保存过也返回内置默认阈值，
     所以标准线永远有数可画。取到后派发一次事件，让外层把详情页重画一次。 */
  const RULES_URL = new URL('../api/v3/grade-rules', import.meta.url).href;
  let rulesPending = null;
  function ensureGradeRules() {
    if (st && st.pd && st.pd.gradeRules) return Promise.resolve(st.pd.gradeRules);
    if (!rulesPending) {
      rulesPending = fetch(RULES_URL, {cache: 'no-store'})
        .then((response) => response.ok ? response.json() : null)
        .then((doc) => {
          rulesPending = null;
          if (doc && doc.subjects) {
            if (st) { st.pd = st.pd || {}; st.pd.gradeRules = doc; }
            document.dispatchEvent(new CustomEvent('pdx:rules-ready'));
          }
          return doc;
        })
        .catch(() => { rulesPending = null; return null; });
    }
    return rulesPending;
  }
  /* 元组是 [逐局字段, 规则字段, 页签标签]。10 分钟经济不在评级规则表里，
     用赛训组手填口径补一份合成规则；阈值与对局页的 gold10Grade 保持一致。 */
  const BENCH_FIELDS = [
    ['gold10', 'gold10', '10 分钟经济'],
    ['gpm', 'gpm', '分均经济'], ['participation', 'participation', '参团率'],
    ['dpm', 'dpm', '分均输出'], ['dtpm', 'tpm', '分均承伤'],
  ];
  const GOLD10_THRESHOLDS = {
    '对抗路': [7400, 7000, 6800], '发育路': [7400, 7000, 6800],
    '中路': [5500, 5500, 5500], '打野': [8000, 8000, 8000],
    '打野·野核': [8000, 8000, 8000], '打野·坦野': [6800, 6800, 6800],
  };
  /* 分路 → 规则主体。打野按英雄标签兜底（本页拿不到本局打野刀）：和后端
     grade_rules.subject_for / 对局页 subjectOf 同一口径，不再固定取野核。 */
  function rulesFor(doc, lane, hero, heroLaneTypes, blade) {
    // 未保存过的规则是内置默认档位，其他页面都不拿它评级，这里也不拿。
    if (!doc || !doc.saved || !doc.subjects) return null;
    let keys = [lane];
    if (lane === '打野') {
      const lanes = (heroLaneTypes || {})[hero] || {};
      const jungle = String(lanes['打野'] || '');
      // 装备判定的打野刀优先，和单局页 grade_rules.subject_for 同口径；
      // 没有 blade 时才退回英雄静态标签。
      const derived = blade && blade.kind === 'tank' ? '打野·坦野'
        : blade && blade.kind === 'core' ? '打野·野核'
          : jungle.includes('坦野') ? '打野·坦野'
            : jungle ? '打野·野核' : '';
      keys = [derived, '打野·野核', '打野·坦野', '打野'].filter(Boolean);
    }
    for (const key of keys) if (doc.subjects[key]) return {key, fields: doc.subjects[key]};
    return null;
  }
  function mainHeroOf(rows) {
    const counts = new Map();
    for (const row of rows || []) {
      if (row.hero) counts.set(row.hero, (counts.get(row.hero) || 0) + 1);
    }
    return [...counts].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0]?.[0] || '';
  }

  /* 指标登记表：一处定义，全页共用标签、小数位和单位口径。 */
  const FIELDS = {
    games: {label: '场次', digits: 0, kind: 'int'},
    winRate: {label: '胜率', digits: 1, kind: 'pct'},
    heroWinRate: {label: '英雄胜率', digits: 1, kind: 'pct'},
    mvpRate: {label: 'MVP 率', digits: 1, kind: 'pct'},
    mainShare: {label: '主位置占比', digits: 1, kind: 'pct'},
    kda: {label: 'KDA', digits: 2, kind: 'num'},
    gpm: {label: '分均经济', digits: 0, kind: 'num'},
    hdpm: {label: '分均对英雄输出', digits: 0, kind: 'num'},
    dpm: {label: '分均总输出', digits: 0, kind: 'num'},
    damageShare: {label: '输出占比', digits: 1, kind: 'pct'},
    goldShare: {label: '经济占比', digits: 1, kind: 'pct'},
    takenShare: {label: '承伤占比', digits: 1, kind: 'pct'},
    participation: {label: '参团率', digits: 1, kind: 'pct'},
    assists: {label: '助攻', digits: 1, kind: 'num'},
    taken: {label: '场均承伤', digits: 0, kind: 'num'},
    dtpm: {label: '分均承伤', digits: 0, kind: 'num'},
    ctrlPerMin: {label: '分均控制', digits: 2, kind: 'num'},
    monsterCoin: {label: '野怪经济', digits: 0, kind: 'num'},
  };
  const fieldLabel = (key) => (FIELDS[key] || {label: key}).label;
  const fieldDigits = (key) => (FIELDS[key] || {digits: 1}).digits;
  const fieldKind = (key) => (FIELDS[key] || {kind: 'num'}).kind;
  const showVal = (key, v) => {
    if (!isNum(v)) return '—';
    if (fieldKind(key) === 'pct') return P(v, fieldDigits(key));
    if (fieldKind(key) === 'int') return `${fmt(v)} 局`;
    return N(v, fieldDigits(key));
  };
  const deltaVal = (key, d) => {
    if (!isNum(d)) return '—';
    if (fieldKind(key) === 'pct') return `${d > 0 ? '+' : ''}${fmt(d, fieldDigits(key))} pp`;
    if (fieldKind(key) === 'int') return `${d > 0 ? '+' : ''}${fmt(d)} 局`;
    return signed(d, fieldDigits(key));
  };
  const TEAM_BENCH_METRICS = ['winRate', 'kda', 'gpm', 'dpm', 'hdpm', 'participation', 'assists', 'dtpm', 'taken'];
  const KPL_BENCH_METRICS = ['winRate', 'heroWinRate', 'kda', 'participation', 'assists', 'gpm', 'dpm', 'hdpm', 'dtpm', 'taken'];
  const RADAR_SHORT = {
    kda: 'KDA', gpm: '经济', hdpm: '对英雄输出', damageShare: '输出占比', goldShare: '经济占比',
    takenShare: '承伤占比', participation: '参团', ctrlPerMin: '控制', dtpm: '分均承伤',
    monsterCoin: '野区', dpm: '总输出', winRate: '胜率', mvpRate: 'MVP',
  };
  const LANE_FOCUS = {
    '游走': ['participation', 'takenShare', 'ctrlPerMin', 'kda', 'winRate', 'dtpm'],
    '打野': ['gpm', 'monsterCoin', 'participation', 'hdpm', 'winRate', 'kda'],
    '对抗路': ['hdpm', 'damageShare', 'takenShare', 'gpm', 'kda', 'winRate'],
    '中路': ['hdpm', 'damageShare', 'gpm', 'participation', 'kda', 'winRate'],
    '发育路': ['hdpm', 'damageShare', 'gpm', 'goldShare', 'kda', 'winRate'],
  };
  const RESULT_TXT = {win: '胜', loss: '负', unknown: '—'};

  /* ── 统计小工具 ─────────────────────────────────────────────────── */
  const mean = (list, get = (x) => x) => {
    const vals = list.map(get).filter(isNum);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const sd = (list, get = (x) => x) => {
    const vals = list.map(get).filter(isNum);
    const m = mean(vals);
    return vals.length > 1 && m != null ? Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / vals.length) : null;
  };
  const median = (values) => {
    const v = values.filter(isNum).sort((a, b) => a - b);
    if (!v.length) return null;
    const m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  };
  const percentile = (values, value) => {
    const v = values.filter(isNum);
    if (!v.length || !isNum(value)) return null;
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
  const laneDist = (c, lane, key) => ((c.laneDistributions || {})[lane] || {})[key] || [];
  function laneDistOf(rows) {
    const keys = ['kda', 'gpm', 'dpm', 'hdpm', 'participation', 'takenShare',
      'damageShare', 'goldShare', 'ctrlPerMin', 'dtpm', 'monsterCoin'];
    const out = {};
    for (const r of rows) {
      const cell = out[r.lane] || (out[r.lane] = {});
      for (const key of keys) if (isNum(r[key])) (cell[key] || (cell[key] = [])).push(r[key]);
    }
    return out;
  }
  const lanePctile = (c, lane, key, value) => percentile(laneDist(c, lane, key), value);
  /* KPL 打野在 BP 包里拆成坦野/野核，按人次合并成一路再对标。 */
  const kplLaneCell = (baseline, lane) => {
    const lanes = (baseline && baseline.lanes) || {};
    if (lane !== '打野') return lanes[lane] || null;
    const parts = ['打野·坦野', '打野·野核'].map((name) => lanes[name]).filter(Boolean);
    if (!parts.length) return null;
    const games = parts.reduce((sum, cell) => sum + (cell.games || 0), 0);
    if (!games) return null;
    const wins = parts.reduce((sum, cell) => sum + (cell.wins || 0), 0);
    const heroSamples = parts.reduce((sum, cell) => sum + (cell.heroWinSamples || 0), 0);
    const heroSum = parts.reduce((sum, cell) => sum + (isNum(cell.heroWinRate) ? cell.heroWinRate * (cell.heroWinSamples || 0) : 0), 0);
    const merged = {games, wins, winRate: wins / games * 100,
      heroWinRate: heroSamples ? heroSum / heroSamples : null, heroWinSamples: heroSamples,
      samples: {winRate: games, heroWinRate: heroSamples}};
    for (const field of KPL_BENCH_METRICS) {
      if (field === 'winRate' || field === 'heroWinRate') continue;
      let sum = 0, n = 0;
      for (const cell of parts) {
        const samples = cell.samples && isNum(cell.samples[field]) ? cell.samples[field] : (isNum(cell[field]) ? cell.games || 0 : 0);
        if (samples > 0 && isNum(cell[field])) { sum += cell[field] * samples; n += samples; }
      }
      merged[field] = n ? sum / n : null;
      merged.samples[field] = n;
    }
    return merged;
  };
  /* 本人常用英雄在 KPL 的外部胜率：按这名选手在该分路的每一局取英雄胜率均值。 */
  const selfHeroKplWr = (rows, heroStats) => {
    let sum = 0, n = 0;
    for (const row of rows || []) {
      const wr = (heroStats[row.hero] || {}).winRate;
      if (isNum(wr)) { sum += wr; n += 1; }
    }
    return n ? sum / n : null;
  };

  /* ── 指标对照卡：本人值 vs 同位置中位 + 一针见血的差距判断 + 环比 ────
     不用仪表盘和百分位数字（赛训组要看具体数值），用语义徽章直接说清高低。 */
  const diffVerdict = (pct, myVal, midVal) => {
    if (!isNum(pct) || !isNum(myVal) || !isNum(midVal)) return {level: 'na', text: '样本不足'};
    const rel = midVal !== 0 ? (myVal - midVal) / Math.abs(midVal) * 100 : null;
    const gap = isNum(rel) ? ` ${rel > 0 ? '+' : ''}${fmt(rel, 0)}%` : '';
    if (pct >= 85) return {level: 'top', text: `远高于中位${gap}`};
    if (pct >= 65) return {level: 'high', text: `高于中位${gap}`};
    if (pct >= 40) return {level: 'mid', text: `接近中位${gap}`};
    if (pct >= 20) return {level: 'low', text: `低于中位${gap}`};
    return {level: 'bottom', text: `远低于中位${gap}`};
  };
  /* metric: {label, key, my, mid, pct, prev, prevLabel}
     prev 为上期同口径数值；有则显示环比。 */
  const metricCard = (metric) => {
    const {key, my, mid, pct, prev, prevLabel} = metric;
    const v = diffVerdict(pct, my, mid);
    const delta = isNum(my) && isNum(prev) ? my - prev : null;
    let trend = '';
    if (isNum(delta) && Math.abs(delta) > 1e-9) {
      const up = delta > 0;
      trend = `<span class="pm-trend ${up ? 'is-up' : 'is-down'}"><i aria-hidden="true">${up ? '↑' : '↓'}</i>较${S(prevLabel || '上期')} ${deltaVal(key, delta)}</span>`;
    } else if (isNum(delta)) {
      trend = `<span class="pm-trend is-flat">与${S(prevLabel || '上期')}持平</span>`;
    }
    return `<div class="pm-metric">
      <div class="pm-metric-top"><span class="pm-metric-label">${S(metric.label)}</span><span class="pm-verdict is-${v.level}">${S(v.text)}</span></div>
      <div class="pm-metric-value">${showVal(key, my)}</div>
      <div class="pm-metric-mid">同位置中位 <b>${showVal(key, mid)}</b></div>
      ${trend ? `<div class="pm-metric-trend">${trend}</div>` : ''}
    </div>`;
  };

  /* KPL 对标卡：只比两边都真实存在的字段，不套用本队分位。 */
  const kplCompareCard = (key, my, ref, leagueLabel) => {
    const diff = isNum(my) && isNum(ref) ? my - ref : null;
    const level = diff == null ? 'na' : diff > 0.05 ? 'top' : diff < -0.05 ? 'low' : 'mid';
    const pct = fieldKind(key) === 'pct';
    const verdict = diff == null ? '样本不足'
      : Math.abs(diff) < 0.05 ? '持平 KPL'
        : `${diff > 0 ? '高于' : '低于'} KPL ${N(Math.abs(diff), pct ? 1 : fieldDigits(key))}${pct ? ' 个百分点' : ''}`;
    return `<div class="pm-metric">
      <div class="pm-metric-top"><span class="pm-metric-label">${S(fieldLabel(key))}</span><span class="pm-verdict is-${level}">${S(verdict)}</span></div>
      <div class="pm-metric-value">${isNum(my) ? showVal(key, my) : na('—', '没有可比数据')}</div>
      <div class="pm-metric-mid">KPL ${S(leagueLabel)} <b>${isNum(ref) ? showVal(key, ref) : '—'}</b></div>
    </div>`;
  };

  /* ── 时间维度：训练日 / 周 / 环比窗口 ──────────────────────────── */
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
  const daysOf = (list) => [...new Set(list.map(dayOf).filter((day) => dayStamp(day) != null))].sort();
  const rangeText = (days) => !days.length ? '—' : days.length === 1 ? days[0] : `${days[0]} ~ ${days[days.length - 1]}`;
  const weekStart = (day) => {
    const ms = dayStamp(day);
    if (ms == null) return '';
    const weekday = (new Date(ms).getUTCDay() + 6) % 7;
    return stampDay(ms - weekday * DAY_MS);
  };

  /* ── 切片：整页唯一的筛选口径 ─────────────────────────────────────
     范围 / 分路 / 英雄 / 对手 / 结果 / 英雄门槛，六个维度都写在 st.pd.ui 里，
     也同步到 URL（教练可以把「某人 近5日 游走 项羽」整条链接发出去）。 */
  const RANGE_MODES = [['all', '全量'], ['d3', '近 3 个训练日'], ['d5', '近 5 个训练日'], ['d10', '近 10 个训练日'], ['custom', '自定义区间']];
  const MIN_MODES = [['1', '全部英雄'], ['2', '≥ 2 局'], ['3', '≥ 3 局'], ['5', '≥ 5 局']];
  const PERIOD_MODES = [['d3', '近 3 个训练日'], ['d5', '近 5 个训练日'], ['week', '本周 vs 上周']];

  const stateUI = () => ((st && (st.pd = st.pd || {})) ? (st.pd.ui = st.pd.ui || {}) : {});
  const one = (allowed, value, fallback) => (allowed.includes(value) ? value : fallback);
  const isDay = (v) => /^\d{4}-\d{2}-\d{2}$/.test(String(v || ''));

  function buildScope(allRows) {
    const ui = stateUI();
    const allDays = daysOf(allRows);
    const last = allDays[allDays.length - 1] || '';
    const range = one(RANGE_MODES.map((m) => m[0]), ui.range, 'all');
    const customFrom = isDay(ui.from) ? ui.from : '';
    const customTo = isDay(ui.to) ? ui.to : '';
    let from = '', to = last;
    if (range === 'custom') {
      from = customFrom || allDays[0] || '';
      to = customTo || last;
      if (from && to && from > to) { const t = from; from = to; to = t; }
    } else if (range !== 'all') {
      const n = Number(range.slice(1)) || 3;
      from = allDays.slice(-n)[0] || '';
      to = last;
    }
    const inRange = (r) => {
      const d = dayOf(r);
      if (!d) return range === 'all';
      if (from && d < from) return false;
      if (to && d > to) return false;
      return true;
    };
    const rows0 = allRows.filter(inRange);
    const lanes = LANES.filter((lane) => rows0.some((r) => r.lane === lane))
      .concat([...new Set(rows0.map((r) => r.lane).filter((lane) => lane && !LANES.includes(lane)))]);
    const lane = one(['全部', ...lanes], ui.lane, '全部');
    const heroCounts = [...group(rows0.filter((r) => r.hero), (r) => r.hero)]
      .sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
    const hero = one(['全部', ...heroCounts.map(([name]) => name)], ui.hero, '全部');
    const opps = [...new Set(rows0.map((r) => r.opponentTeam || r.opponent).filter(Boolean))].sort();
    const opp = one(['全部', ...opps], ui.opp, '全部');
    const res = one(['全部', 'win', 'loss'], ui.res, '全部');
    const min = Number(one(MIN_MODES.map((m) => m[0]), String(ui.min || '1'), '1'));
    const rows = rows0.filter((r) => (lane === '全部' || r.lane === lane)
      && (hero === '全部' || r.hero === hero)
      && (opp === '全部' || (r.opponentTeam || r.opponent) === opp)
      && (res === '全部' || r.result === res));
    const w = win(rows);
    return {
      range, from, to, customFrom, customTo, lane, hero, opp, res, min,
      rows, lanes, opps, heroCounts, allDays, days: daysOf(rows), wins: w.wins, decided: w.decided, rate: w.rate,
    };
  }
  /* 卡片顶部的「范围」一行：把当前切片说人话，教练一眼知道自己在看哪一段。 */
  function scopeText(scope) {
    const bits = [];
    if (scope.range === 'custom') bits.push(`${scope.from || '—'} ~ ${scope.to || '—'}`);
    else if (scope.range === 'all') bits.push(`全量 ${fmt(scope.allDays.length)} 个训练日`);
    else bits.push((RANGE_MODES.find((m) => m[0] === scope.range) || [])[1] || scope.range);
    if (scope.lane !== '全部') bits.push(scope.lane);
    if (scope.hero !== '全部') bits.push(scope.hero);
    if (scope.opp !== '全部') bits.push(`对手 ${scope.opp}`);
    if (scope.res !== '全部') bits.push(RESULT_TXT[scope.res] || scope.res);
    bits.push(`${fmt(scope.rows.length)} 局`);
    return bits.join(' · ');
  }
  function scopeIsDefault(scope) {
    return scope.range === 'all' && scope.lane === '全部' && scope.hero === '全部'
      && scope.opp === '全部' && scope.res === '全部' && scope.min === 1;
  }

  /* ── 渲染原语 ───────────────────────────────────────────────────── */
  let cardSeq = 0;
  let cardN = null;
  let rangeLabel = '';
  const setN = (n) => { cardN = isNum(n) ? n : null; };
  const card = (no, title, lead, body, foot = '') => {
    const badge = isNum(cardN) ? `<span class="pdx-n" title="这张卡的结论建立在多少局上">N=${fmt(cardN)} 局</span>` : '';
    cardN = null;
    return `<article class="pdx-card">
    <div class="pdx-card-head">${no ? `<span class="pdx-no">${S(no)}</span>` : ''}
      <h3>${S(title)}${badge}</h3></div>
    <div class="pdx-card-body">${body}</div></article>`;
  };
  const na = (text = '无数据', title = '') => `<span class="pv-na"${title ? ` title="${S(title)}"` : ''}>${S(text)}</span>`;
  const emptyWith = (title, hint, relaxLabel = '清除切片条件') => `<div class="pv-empty2">
    ${glyph('chart', { size: 20 })}<b>${S(title)}</b><p>${S(hint)}</p>
    <button type="button" class="pv-relax" data-pdx-reset>${glyph('refresh', { size: 18 })}${S(relaxLabel)}</button></div>`;
  const heroTag = (hero, note) => `<a class="pv-hero" href="#hero/${encodeURIComponent(String(hero || ''))}"
    title="打开英雄页：${S(hero || '未知')}">${portrait(hero)}<b>${S(hero || '未知')}</b>${note ? `<small>${S(note)}</small>` : ''}</a>`;
  const heroPlain = (hero) => `<span class="pv-hero">${portrait(hero)}<b>${S(hero || '未知')}</b></span>`;
  const resChip = (r) => `<em class="pv-chip ${r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : 'is-quiet'}">${RESULT_TXT[r] || '—'}</em>`;
  const stats = (items) => `<div class="pv-stats">${items.map(([label, value, note]) =>
    `<div><span>${S(label)}</span><strong>${value}</strong><small>${S(note || '')}</small></div>`).join('')}</div>`;
  const note = () => '';
  const laneClsOf = (lane) => V.LANE_CLS[lane] || 'is-c6';
  /* 胜率在表格里要一眼分好坏：≥55% 绿、≤45% 棕、中间走正文色。 */
  const rateCls = (rate) => (!isNum(rate) ? '' : rate >= 55 ? 'is-good' : rate <= 45 ? 'is-bad' : '');

  /* 卡片自己的那一维（指标 / 方向 / 视角）仍是下拉，因为它们不跨卡。 */
  function cardSelect(name, label, options, value) {
    return V.pvSelect({name, label, value, options});
  }

  /* 吸顶高度：顶部那条 masthead 导航和二级标签栏都是 sticky 的，
     切片条要停在它们下面，而不是被压在后面。把已知的吸顶元素量一遍取最低边。 */
  function stickyTop() {
    try {
      const known = ['.desk-bar', 'header.masthead', '.secondary-wrap', '.site-header', '.app-bar', '.topbar'];
      let bottom = 0;
      for (const sel of known) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const cs = window.getComputedStyle(el);
        if (cs.position !== 'sticky' && cs.position !== 'fixed') continue;
        bottom = Math.max(bottom, (parseFloat(cs.top) || 0) + el.offsetHeight);
      }
      return Math.round(bottom) + 8;
    } catch (err) { return 8; }
  }

  /* ── 切片条：吸顶，改一项整页重算 ───────────────────────────────── */
  function scopeBar(c) {
    const s = c.scope;
    /* 选项文案要短：六个下拉 + 一条命中摘要要挤在同一行里，
       写成「游走（48 局）」就会把摘要顶到第二行，吸顶条白高 40px。 */
    const laneOptions = [['全部', `全部 ${fmt(s.rows.length)}`]]
      .concat(s.lanes.map((lane) => [lane, `${lane} ${fmt((c.byLane.get(lane) || []).length)}`]));
    const heroGroups = s.lanes.map((lane) => ({
      label: lane,
      items: s.heroCounts.filter(([, list]) => list.some((r) => r.lane === lane))
        .map(([hero, list]) => [hero, `${hero} · ${fmt(list.length)}`]),
    })).filter((g) => g.items.length);
    const oppOptions = [['全部', '全部对手']].concat(s.opps.map((o) => [o, o]));
    /* 英雄按分路分组：46 个英雄平铺成一长串下拉是找不着的，分组 + 系统自带
       的首字跳转（敲「项」直接到项羽）比自绘弹层更稳。 */
    const heroSel = V.pvSelect({
      name: 'hero', label: '英雄', value: s.hero === '全部' ? '' : s.hero,
      allLabel: `全部 ${fmt(s.heroCounts.length)} 个`, groups: heroGroups,
    });
    const rate = isNum(s.rate) ? P(s.rate) : '—';
    /* 摘要写短：「5 天 / 24 英雄」比「5 个训练日 / 24 个英雄」省一行宽度，
       完整口径在每张卡的「范围」那行里。 */
    const hits = `<div class="pdx-hit">
      <span><b>${fmt(s.rows.length)}</b> 局</span>
      <span>胜率 <b>${rate}</b></span>
      <span><b>${fmt(s.days.length)}</b> 天</span>
      <span><b>${fmt(c.topHeroes.length)}</b> 英雄</span>
      ${scopeIsDefault(s) ? '' : `<button type="button" class="pv-reset is-scope" data-pdx-reset>${glyph('refresh', { size: 18 })}清除切片</button>`}
    </div>`;
    const custom = s.range === 'custom' ? `<label class="pv-sel is-scope"><span class="pv-sel-label">起</span>
        <span class="pv-sel-box"><input type="date" data-pdx-select="from" value="${S(s.customFrom || s.from || '')}"
          min="${S(s.allDays[0] || '')}" max="${S(s.allDays[s.allDays.length - 1] || '')}" aria-label="起始训练日"></span></label>
      <label class="pv-sel is-scope"><span class="pv-sel-label">止</span>
        <span class="pv-sel-box"><input type="date" data-pdx-select="to" value="${S(s.customTo || s.to || '')}"
          min="${S(s.allDays[0] || '')}" max="${S(s.allDays[s.allDays.length - 1] || '')}" aria-label="结束训练日"></span></label>` : '';
    return `<div class="pdx-scope" role="region" aria-label="分析切片">
      <div class="pdx-scope-row">
        ${V.pvSelect({name: 'range', label: '范围', value: s.range, options: RANGE_MODES})}
        ${custom}
        ${V.pvSelect({name: 'lane', label: '分路', value: s.lane, options: laneOptions})}
        ${heroSel}
        ${s.opps.length > 1 ? V.pvSelect({name: 'opp', label: '对手', value: s.opp, options: oppOptions}) : ''}
        ${V.pvSelect({name: 'res', label: '结果', value: s.res, options: [['全部', '胜 + 负'], ['win', '只看胜'], ['loss', '只看负']]})}
        ${V.pvSelect({name: 'min', label: '英雄门槛', value: String(s.min), options: MIN_MODES})}
      </div>
      ${hits}
    </div>`;
  }

  /* ══ 模块 0 · 同分路对比：自家 vs 规则标准线 ═════════════════════════
     旧版这里画的是「本人 − 同分路对手」的经济差；按验收口径改成自家与
     赛训组标准线对照：黄色横线是达标线，左边把规则三档原样贴出来当标准，
     不再拿任何一个对手当基准。没样本的项按 0 显示，不画成「—」。 */
  function buildBench(c, f) {
    const lane = c.focusLane;
    const doc = st && st.pd && st.pd.gradeRules;
    const heroTypes = (st && st.pd && st.pd.detail && st.pd.detail.heroLaneTypes) || {};
    const laneRows = c.byLane.get(lane) || [];
    const mainHero = mainHeroOf(laneRows);
    const bladeRow = laneRows.find((row) => row && row.blade && row.hero === mainHero);
    const rule = rulesFor(doc, lane, mainHero, heroTypes, bladeRow && bladeRow.blade);
    /* 标准线是分路口径（规则按 focusLane 取），「本人」必须取同一分路的局；
       以前用 c.scope.rows 把其它分路也算进来，同一个选手这一页会同时出现
       618（全部）和 586（中路）两个数，教练看到的就是对不上。 */
    const rows = c.byLane.get(lane) || [];
    /* 规则字段 + 手填的 10 分钟经济合成一份字段表；gold10 不进评级规则接口，
       但口径与对局页的 10 分钟经济评级一致，教练填过就能在这里对照。 */
    // 设置页没勾选生效的字段不参与标准线表；gold10 是手填合成项，不受 active 管。
    const fields = Object.fromEntries(Object.entries(rule ? rule.fields : {})
      .filter(([, item]) => item && item.active !== false));
    const gold10Ts = GOLD10_THRESHOLDS[rule && rule.key] || GOLD10_THRESHOLDS[lane];
    if (gold10Ts) fields.gold10 = {label: '10 分钟经济', key: 'gold10', unit: '金', thresholds: gold10Ts};
    // 元组第一个是逐局字段、第二个才是规则字段（分均承伤 dtpm → tpm），按规则字段过滤。
    const options = BENCH_FIELDS
      .filter(([, ruleKey]) => fields[ruleKey])
      .map(([key, ruleKey, label]) => [key, ruleKey, label]);
    const pickKey = one(options.map(([key]) => key), f.benchField, options[0] ? options[0][0] : 'gpm');
    const active = options.find(([key]) => key === pickKey) || options[0];
    const ruleItem = active ? fields[active[1]] : null;
    const thresholds = (ruleItem && Array.isArray(ruleItem.thresholds)) ? ruleItem.thresholds : null;
    const pass = thresholds ? thresholds[2] : null;
    const fmtBench = (v, unit) => {
      if (!isNum(v)) return '—';
      const suffix = unit || (ruleItem && ruleItem.unit) || '';
      return fmt(v, Math.abs(v) < 20 ? 1 : 0) + (suffix ? ` ${suffix}` : '');
    };
    const rowValue = (row, ruleKey) => row[ruleKey === 'tpm' ? 'dtpm' : ruleKey];

    /* 左边贴规则：卓越 / 优秀 / 达标三档 + 本人在当前切片的均值。 */
    const ruleRows = options.map(([key, ruleKey, label]) => {
      const r = fields[ruleKey] || {};
      const vals = rows.map((row) => rowValue(row, ruleKey)).filter(isNum);
      const mine = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      const ts = Array.isArray(r.thresholds) ? r.thresholds : [];
      return `<tr><th scope="row">${S(label)}</th>
        <td>${fmtBench(ts[0], r.unit)}</td><td>${fmtBench(ts[1], r.unit)}</td><td>${fmtBench(ts[2], r.unit)}</td>
        <td class="is-mine">${fmtBench(mine, r.unit)}</td></tr>`;
    }).join('');
    const rulesTable = rule
      ? `<div class="pv-rules-wrap" role="region" tabindex="0" aria-labelledby="pdx-rules-cap">
           <table class="pv-rules-table"><caption id="pdx-rules-cap">${S(rule.key)} · 赛训组标准线</caption>
             <thead><tr><th scope="col">指标</th><th scope="col">卓越</th><th scope="col">优秀</th><th scope="col">达标</th><th scope="col">本人</th></tr></thead>
             <tbody>${ruleRows}</tbody></table></div>`
      : emptyWith('标准线还没加载出来', '评级规则正在读取；到「赛训 → 规则设置」保存过后，这里会按你保存的阈值重画。');

    const ownVals = active ? rows.map((row) => rowValue(row, active[1])).filter(isNum) : [];
    const mine = ownVals.length ? ownVals.reduce((a, b) => a + b, 0) / ownVals.length : null;
    const chart = active && isNum(pass)
      ? (!isNum(mine)
        ? emptyWith(pickKey === 'gold10' ? '这几局还没有 10 分钟经济' : '这一项暂无样本',
          pickKey === 'gold10' ? '在对局复盘的「10 分钟经济」里由教练填过后，这里会按本切片均值画出来。'
            : '当前切片没有可用样本，换个范围或清除切片条件。')
        : V.columns({
          labels: [S(active[2])],
          series: [{values: [mine], cls: 'is-mark', texts: [fmtBench(mine)]}],
          refs: [{v: pass, label: '达标线', cls: 'is-standard', text: fmtBench(pass)}],
          W: w(7), H: 320, padL: 88, padR: 22, maxBarW: 96, forceZero: true,
          fmtV: fmtBench, aria: `${S(active[2])}：本人 ${fmtBench(mine)}，达标线 ${fmtBench(pass)}`,
        }))
      : emptyWith('这条标准线还没有达标阈值', '到「赛训 → 规则设置」给这一路补上阈值。');
    const tools = options.length > 1
      ? selBar([cardSelect('benchField', '看哪项', options.map(([key, , label]) => [key, label]), pickKey)]) : '';

    return [card('00', '同分路对比', '',
      tools + grid([
        panel('规则标准线', rulesTable, {span: 5}),
        panel('本人 vs 达标线', chart, {span: 7}),
      ]), '')];
  }

  /* ══ 模块 1 · 综合画像 ═════════════════════════════════════════════ */
  function buildPortrait(c, f) {
    const out = [];
    const scope = c.scope;

    /* 01 身份与数据合并状态（身份是全量口径，不随切片变） */
    {
      const id = c.identity, accounts = id.accountIds || [], nicks = id.nicknames || [];
      const body = `<div class="pv-id-main"><span class="pv-id-ava">${S(String(c.name).slice(0, 1))}</span>
          <div><b>${S(c.name)}</b><small>选手ID · 已合并 ${fmt(nicks.length)} 个游戏名</small></div>
          <span class="pv-badge ${id.bound ? 'is-ok' : 'is-warn'}">${id.bound ? '已匹配' : '未匹配'}</span></div>
        <div class="pv-id-grid">
          <div><span>归属战队</span><b>${id.teamName ? S(id.teamName) : '未归队'}</b></div>
          <div><span>常用位置</span><b>${S(c.mainLane || id.lane || '未记录')}</b></div>
          <div><span>营地账号</span><b>${fmt(accounts.length)} 个</b></div>
          <div><span>关联游戏名</span><b>${fmt(nicks.length)} 个</b></div>
        </div>
        ${id.bound ? '' : `<button class="control" data-pl-name="${S(c.name)}" style="margin-top:14px">${glyph('players', { size: 18 })}命名并归队</button>`}`;
      out.push(card('01', '身份与数据合并状态',
        `<b>${fmt(c.allRows.length)} 局</b>按选手ID合并：<b>${fmt(nicks.length)} 个游戏名</b>、<b>${fmt(accounts.length)} 个营地账号</b>，本页全部按选手ID展示。`,
        body,
        '游戏名只在「匹配与编组」里维护；一个选手ID下的多个号，对局数据在这里合并统计。'));
    }

    /* 02 位置能力：分路取切片，切片是「全部」时用主位置 */
    {
      const lane = c.focusLane;
      const list = c.byLane.get(lane) || [];
      const keys = LANE_FOCUS[lane] || LANE_FOCUS['中路'];
      const w2 = win(list);
      /* 本人值用所选范围本身；上期是紧邻它的等长窗口（prevByLane）。 */
      const prevList = c.prevByLane.get(lane) || [];
      const pcts = keys.map((key) => lanePctile(c, lane, key, mean(list, (r) => r[key])));
      /* 每项写清：本人具体数值 / 同位置中位 / 一针见血的差距判断 / 较上期环比。 */
      const tiles = `<div class="pm-grid">${keys.map((key, i) => metricCard({
        key, label: fieldLabel(key),
        my: mean(list, (r) => r[key]),
        mid: median(laneDist(c, lane, key)),
        pct: pcts[i],
        prev: mean(prevList, (r) => r[key]),
        prevLabel: c.prevLabel,
      })).join('')}</div>`;
      setN(list.length);
      out.push(card('02', '位置能力 · 专项指标',
        `切片内的分路是 <b>${S(lane)}</b>（${scope.lane === '全部' ? '没限定分路，取主位置' : '来自上方「分路」'}）：<b>${fmt(list.length)} 局</b>、胜率 <b>${P(w2.rate)}</b>；下方数值与所选范围一致。`,
        panel('六项专项指标 · 本人 vs 同位置中位', tiles, {span: 12,
          foot: `本期＝所选范围，上期＝${S(c.prevLabel)}（等长）。差距基于同位置分位；中位参照全量逐局记录。`}),
        '样本不足 2 局的指标照样给值，但不判分位。'));
    }

    /* 03 同位置对标：本队选手排行，或切到 KPL 某项赛事的同位置平均线。
       KPL 选项由真实字段与有效样本数决定；旧局没回填详细指标时只显示胜率类。 */
    {
      const lane = c.focusLane;
      const isKpl = f.benchSource === 'kpl';
      const leagueLabel = f.kplLeague || '全部 KPL 赛事';
      const kplCell = isKpl ? kplLaneCell(c.kplBaseline, lane) : null;
      const all = (c.laneSamples[lane] || []);
      const kplFields = new Set((c.kplBaseline && c.kplBaseline.fields) || ['winRate', 'heroWinRate']);
      const kplSamples = (kplCell && kplCell.samples) || {};
      const hasKplSample = (metric) => {
        if (!kplCell) return false;
        if (isNum(kplSamples[metric])) return kplSamples[metric] > 0;
        if (metric === 'winRate') return (kplCell.games || 0) > 0;
        if (metric === 'heroWinRate') return (kplCell.heroWinSamples || 0) > 0;
        return false;
      };
      const metricOptions = (isKpl ? KPL_BENCH_METRICS : TEAM_BENCH_METRICS)
        .filter((metric) => isKpl ? kplFields.has(metric) && hasKplSample(metric) : all.some((s) => isNum(s[metric])))
        .map((metric) => [metric, fieldLabel(metric)]);
      if (!metricOptions.length) metricOptions.push(['winRate', '胜率']);
      const key = one(metricOptions.map(([metric]) => metric), f.bench, metricOptions[0][0]);
      const valid = all.filter((s) => s.games >= 2 && isNum(s[key]));
      const scored = valid.slice().sort((a, b) => b[key] - a[key]);
      const top = scored.slice(0, 11);
      const selfIn = top.some((s) => s.name === c.name);
      const selfRow = selfIn ? null : scored.find((s) => s.name === c.name);
      const rows = selfRow ? [...top, selfRow] : top;
      const rank = scored.findIndex((s) => s.name === c.name) + 1;
      const sourceSelect = V.pvSelect({name: 'benchSource', label: '对标范围', value: f.benchSource,
        groups: [{label: '本队', items: [['', '本队同位置']]},
          {label: 'KPL', items: [['kpl', 'KPL 同位置平均']]}]});
      const metricSelect = cardSelect('bench', '指标', metricOptions, key);
      const leagueSelect = isKpl ? V.pvSelect({name: 'kplLeague', label: 'KPL 赛事', value: f.kplLeague,
        options: [['', '全部 KPL 赛事']].concat((c.kplBaseline.leagues || [])
          .map((l) => [l.name, `${l.name} · ${fmt(l.games)} 局`]))}) : '';
      const tools = selBar([sourceSelect, leagueSelect, metricSelect]);
      const curSelf = c.byLane.get(lane) || [];
      const selfGames = curSelf.length;
      const selfRate = win(curSelf).rate;
      const selfKda = mean(curSelf, (r) => r.kda);
      const selfMetric = (metric) => metric === 'winRate' ? selfRate
        : metric === 'heroWinRate' ? selfHeroKplWr(curSelf, c.kplHeroStats)
          : mean(curSelf, (r) => r[metric]);
      const selfValue = selfMetric(key);
      const refValue = kplCell ? kplCell[key] : null;
      const chart = isKpl
        ? (() => {
          const bars = [{name: '本人', value: selfValue, mark: true},
            {name: `${lane} KPL 平均`, value: refValue, mark: false}]
            .filter((r) => isNum(r.value));
          return bars.length ? V.columns({
            labels: bars.map((r) => r.name),
            labelsHtml: bars.map((r) => `<span${r.mark ? ' class="pv-col-self"' : ''}>${S(r.name)}</span>`),
            series: [{values: bars.map((r) => r.value), clsAt: bars.map((r) => (r.mark ? 'is-mark' : 'is-flat')),
              texts: bars.map((r) => showVal(key, r.value))}],
            W: Math.min(w(8), 460), H: 280, padL: 56, padR: 16, maxBarW: 120, baseline: 'auto',
            fmtV: (v) => fieldKind(key) === 'pct' ? `${N(v, 1)}%` : N(v, fieldDigits(key) > 1 ? 2 : 1),
            refs: [], aria: `${fieldLabel(key)}：本人 ${showVal(key, selfValue)}，${lane} KPL 平均 ${showVal(key, refValue)}`,
          }) : emptyWith(`这项赛事没有该分路的 KPL ${fieldLabel(key)} 样本`,
            `${leagueLabel} 的官方逐局数据里没有 ${S(lane)} 的可用${S(fieldLabel(key))}记录。`);
        })()
        : (rows.length ? V.columns({
          labels: rows.map((s) => s.name),
          labelsHtml: rows.map((s) => (s.name === c.name ? `<span class="pv-col-self">${S(s.name)}</span>` : `<span>${S(s.name)}</span>`)),
          series: [{values: rows.map((s) => s[key]),
            clsAt: rows.map((s) => (s.name === c.name ? 'is-mark' : 'is-flat')),
            texts: rows.map((s) => showVal(key, s[key]))}],
          /* 只有两三个人时别把图拉满 8 栏：柱会浮在巨大的空槽里。 */
          W: Math.min(w(8), 220 + rows.length * 150), H: 280,
          padL: 56, padR: 16, maxBarW: 96, baseline: 'auto',
          fmtV: (v) => N(v, fieldDigits(key) > 1 ? 2 : 1),
          refs: median(scored.map((x) => x[key])) == null ? []
            : [{v: median(scored.map((x) => x[key])), label: '同位置中位'}],
          aria: `同位置选手 ${fieldLabel(key)} 排行`,
        }) : emptyWith('这一路还没有达标的选手',
          `本人${lane}只有 ${fmt((c.byLane.get(lane) || []).length)} 局，同位置里也没有达到 2 局门槛的人。`));
      const prevSelf = c.prevByLane.get(lane) || [];
      const gauges = isKpl
        ? (() => {
          const secondaryKey = key === 'winRate' ? 'heroWinRate' : 'winRate';
          return `<div class="pm-grid pm-grid--two">${[
            kplCompareCard(key, selfValue, refValue, leagueLabel),
            kplCompareCard(secondaryKey, selfMetric(secondaryKey), kplCell && kplCell[secondaryKey], leagueLabel),
          ].join('')}</div>`;
        })()
        : `<div class="pm-grid pm-grid--three">${[
          metricCard({key: 'games', label: '场次', my: selfGames, mid: median(all.map((s) => s.games)),
            pct: percentile(all.map((s) => s.games), selfGames),
            prev: c.prevByLane.size ? prevSelf.length : null, prevLabel: c.prevLabel}),
          metricCard({key: 'winRate', label: '胜率', my: selfRate, mid: median(all.map((s) => s.winRate)),
            pct: percentile(all.map((s) => s.winRate), selfRate),
            prev: win(prevSelf).rate, prevLabel: c.prevLabel}),
          metricCard({key: 'kda', label: 'KDA', my: selfKda, mid: median(all.map((s) => s.kda)),
            pct: percentile(all.map((s) => s.kda), selfKda),
            prev: mean(prevSelf, (r) => r.kda), prevLabel: c.prevLabel}),
        ].join('')}</div>`;
      const sampleN = isKpl
        ? (isNum(kplSamples[key]) ? kplSamples[key] : key === 'winRate' ? (kplCell && kplCell.games) || 0
          : key === 'heroWinRate' ? (kplCell && kplCell.heroWinSamples) || 0 : 0)
        : valid.length;
      setN(sampleN);
      const summary = isKpl
        ? `${S(leagueLabel)} · ${S(lane)} 共 <b>${fmt((kplCell && kplCell.games) || 0)}</b> 人次；${S(fieldLabel(key))} 本人 <b>${showVal(key, selfValue)}</b>，KPL <b>${showVal(key, refValue)}</b>，本指标 <b>${fmt(sampleN)}</b> 样本。`
        : `${S(lane)} 共 <b>${fmt(all.length)} 人</b>，达 <b>2 局</b>门槛 <b>${fmt(valid.length)} 人</b>；按 <b>${S(fieldLabel(key))}</b> 排，本人 <b>${rank ? `第 ${fmt(rank)} 位` : na('未进榜', '本人该分路不足 2 局，不进榜')}</b>。`;
      out.push(card('03', isKpl ? `KPL 同位置对标 · ${lane}` : `同位置对标 · ${lane}`, summary,
        tools + grid([
          panel(isKpl ? `本人 vs ${lane} KPL 平均 · ${fieldLabel(key)}` : `按${fieldLabel(key)}排行 · 前 ${fmt(rows.length)} 人`,
            chart, {span: 8, foot: isKpl ? '数据来源：KPL 官方 BP + 选手终局统计 + KPL 英雄外部胜率'
              : '强调色柱 = 本人，灰色柱 = 同位置其他人'}),
          panel(isKpl ? '本人 vs KPL · 数值与差距' : '本人三项 · 数值与差距', gauges,
            {span: 4, foot: isKpl ? `赛事：${S(leagueLabel)}；只比双方都有真实样本的字段`
              : `中位参照 ${fmt(all.length)} 名同位置选手；环比为${S(c.prevLabel)}`}),
        ]),
        isKpl ? 'KPL 指标来自官方单局选手终局面板；旧局未回填时只列可用指标，选赛事后按该赛事全部对局重算。'
          : '榜单只给单项原始值，不用统一综合分排序；1 局样本不进榜，避免一次高光把人顶到前面。'));
    }

    return out;
  }

  /* ══ 模块 2 · 英雄池 ═══════════════════════════════════════════════ */
  function heroBench(board, ownNames) {
    const exclude = new Set((ownNames || []).map(String));
    const map = new Map();
    for (const g of board.games || []) {
      const ownWin = g.result === 'win', ownLose = g.result === 'loss';
      for (const [side, arr] of [['own', g.own || []], ['enemy', g.enemy || []]]) {
        const won = side === 'own' ? ownWin : ownLose;
        for (const p of arr) {
          if (!p.hero || exclude.has(p.name)) continue;
          const it = map.get(p.hero) || {games: 0, wins: 0, decided: 0, kdas: []};
          it.games += 1;
          if (ownWin || ownLose) {
            it.decided += 1;
            if (won) it.wins += 1;
          }
          if (isNum(p.kda)) it.kdas.push(p.kda);
          map.set(p.hero, it);
        }
      }
    }
    for (const it of map.values()) it.kda = mean(it.kdas);
    return map;
  }

  function buildHeroes(c, f) {
    const out = [];
    const scope = c.scope;
    /* 门槛以下的英雄不进图，只报数量：一局英雄不该占一块面积。 */
    const pool = c.topHeroes.filter(([, list]) => list.length >= scope.min);
    const below = c.topHeroes.length - pool.length;
    const banned = below ? `另有 <b>${fmt(below)} 个英雄</b>不足 ${fmt(scope.min)} 局，未进图（把「英雄门槛」调到全部可看）。` : '';

    /* 01 英雄使用：矩形树图（面积 = 场次 / 颜色 = 分路）+ 职业环形
       一个赛季能有 120 多个英雄，全铺进一块面积图只会碎成细线：
       只画前 12 个（面积按这 12 个之间的相对场次），剩下的报数量不进图。 */
    {
      const TOP_TILES = 12;
      const shown = pool.slice(0, TOP_TILES);
      const rest = pool.slice(TOP_TILES);
      const restGames = rest.reduce((a, [, list]) => a + list.length, 0);
      const restText = rest.length
        ? `另有 <b>${fmt(rest.length)} 个英雄</b>合计 <b>${fmt(restGames)} 局</b>（占 ${P(scope.rows.length ? restGames / scope.rows.length * 100 : null)}）没进面积图，大多是只打了 1–2 局的零散场次；把「英雄门槛」调到 2 局以上，这些场次就不进统计了。`
        : '';
      const treemapItems = shown.map(([hero, list]) => {
        const wv = win(list);
        const lanes = [...new Set(list.map((r) => r.lane))];
        const share = scope.rows.length ? list.length / scope.rows.length * 100 : 0;
        return {
          label: hero, value: list.length, pick: hero, cls: laneClsOf(lanes[0]),
          icon: portrait(hero),
          sub: `${fmt(list.length)} 局 · 占 ${P(share)} · 胜率 ${P(wv.rate)}`,
          title: `${hero} · ${fmt(list.length)} 局 · 出场占比 ${P(share)} · 胜率 ${P(wv.rate)} · 分路 ${lanes.join('/')}`,
        };
      });
      const byType = [...group(scope.rows, (r) => r.heroType || '未分类')].sort((a, b) => b[1].length - a[1].length);
      const ringItems = byType.map(([type, list], i) => ({label: type, value: list.length, cls: V.catCls(i)}));
      const tmEmpty = pool.length
        ? V.treemap({items: treemapItems, W: w(7), H: 330, pickName: 'hero', top: TOP_TILES + 1, aria: '英雄出场场次的矩形树图'})
        : emptyWith('门槛把英雄全筛掉了',
          `切片里没有英雄达到 ${fmt(scope.min)} 局。把「英雄门槛」调回「全部英雄」，或者放宽范围 / 去掉分路限制。`,
          '清除切片条件');
      setN(scope.rows.length);
      out.push(card('01', '英雄使用图谱',
        `切片内用了 <b>${fmt(pool.length)} 个达标英雄</b>，出场最多 ${heroTag((pool[0] || [])[0] || '—')} <b>${fmt(pool[0] ? pool[0][1].length : 0)} 局</b>；方块面积 = 前 ${fmt(Math.min(shown.length, TOP_TILES))} 个英雄之间的相对场次，点方块切到该英雄。`,
        grid([
          panel(`英雄出场面积${rest.length ? ` · 前 ${fmt(shown.length)} 个` : ''}`, tmEmpty, {
            span: 7, foot: '颜色：对抗 / 打野 / 中路 / 发育 / 游走；点方块 = 整页只看这位英雄，再点一次回到全部',
          }),
          panel('职业构成', V.ring({
            items: ringItems, size: 200, aria: '英雄职业构成', top: 8,
            center: {value: scope.rows.length, label: '切片场次', text: `${fmt(scope.rows.length)}`},
          }), {span: 5, foot: `覆盖 ${fmt(byType.length)} 类职业`}),
        ]) + (restText ? note(restText) : '') + (below ? note(banned) : ''),
        '职业元数据来自 resources/hero_tags.json 的 defaultType；面积只算次数，不代表强度。'));
    }

    return out;
  }

  /* 上期 / 本期英雄卡对照：共有英雄排最前、左右同头像对齐，各期独有放分隔线后 */
  const trendDelta = (d) => !d
    ? '<em class="pv-trend-delta is-flat">→</em>'
    : `<em class="pv-trend-delta ${d > 0 ? 'is-up' : 'is-down'}">${d > 0 ? '▲' : '▼'}${fmt(Math.abs(d))}</em>`;
  function heroCompareHtml(period) {
    const listOf = (list) => {
      const map = new Map();
      for (const [hero, set] of group(list, (r) => r.hero || '未知')) map.set(hero, set.length);
      return map;
    };
    const prevCount = listOf(period.previous);
    const curCount = listOf(period.current);
    const byGames = (a, b) => b.n - a.n || String(a.hero).localeCompare(String(b.hero), 'zh');
    const shared = [...prevCount].filter(([hero]) => curCount.has(hero))
      .map(([hero, from]) => ({hero, from, to: curCount.get(hero)}))
      .sort((a, b) => (b.from + b.to) - (a.from + a.to) || b.to - a.to
        || String(a.hero).localeCompare(String(b.hero), 'zh'));
    const prevOnly = [...prevCount].filter(([hero]) => !curCount.has(hero))
      .map(([hero, n]) => ({hero, n})).sort(byGames);
    const curOnly = [...curCount].filter(([hero]) => !prevCount.has(hero))
      .map(([hero, n]) => ({hero, n})).sort(byGames);
    const cell = (item, cls, delta, title) => {
      if (!item) return '<div class="pv-trend-cell is-empty" aria-hidden="true"></div>';
      return `<a class="pv-trend-cell${cls ? ' ' + cls : ''}" href="#hero/${encodeURIComponent(item.hero)}" draggable="false"
          title="${S(title || `${item.hero} · ${fmt(item.n)} 局`)}">
          <span class="pv-trend-face">${portrait(item.hero)}</span>
          <b class="pv-trend-name">${S(item.hero)}</b>
          <strong class="pv-trend-n">${fmt(item.n)}<small> 局</small>${delta == null ? '' : trendDelta(delta)}</strong>
        </a>`;
    };
    const pair = (left, right) => `<div class="pv-trend-row">${left}${right}</div>`;
    const sharedRows = shared.map((x) => pair(
      cell({hero: x.hero, n: x.from}, '', null, `${x.hero} · 上期 ${fmt(x.from)} 局`),
      cell({hero: x.hero, n: x.to}, '', x.to - x.from,
        `${x.hero} · 上期 ${fmt(x.from)} 局 → 本期 ${fmt(x.to)} 局`),
    )).join('');
    const splitCount = Math.max(prevOnly.length, curOnly.length);
    const splitter = splitCount
      ? '<div class="pv-trend-sep"><span>上期有 · 本期无</span><span>本期有 · 上期无</span></div>' : '';
    const splitRows = Array.from({length: splitCount}, (_, i) =>
      pair(cell(prevOnly[i], 'is-gone', null), cell(curOnly[i], 'is-new', null))).join('');
    return sharedRows + splitter + splitRows;
  }

  /* ══ 模块 3 · 周期与英雄池变动 ═══════════════════════════════════ */
  function buildTrend(c, f) {
    const out = [];
    const rows = c.scope.rows;
    const period = periodWindow(rows, f.period);

    /* 01 英雄池变动：左「上期」右「本期」，一行一对英雄卡，逐行对齐 */
    {
      const tools = selBar([
        cardSelect('period', '窗口', PERIOD_MODES.map(([key, label]) => [key, label]), f.period),
      ]);
      if (!period) {
        out.push(card('', '英雄池变动', '', `<div class="pdx-center">${tools}</div>` + V.empty('需要对局日期，才能切出上期和本期。'), ''));
      } else {
        const board = `<div class="pv-trend-scroll" data-pool-scroll tabindex="0" role="group" aria-label="上期与本期英雄出场对照，可滚动或按住拖动">
          <div class="pv-trend-head"><span>上期 · ${S(period.prevLabel)}</span><span>本期 · ${S(period.label)}</span></div>
          ${heroCompareHtml(period)}
        </div>`;
        out.push(card('', '英雄池变动', '', `<div class="pdx-center">${tools}</div>` + board, ''));
      }
    }
    return out;
  }

  /* 环形窗口：整页切换周期时用（趋势卡单独用 periodWindow） */
  function periodWindow(rows, mode) {
    const allDays = daysOf(rows);
    if (!allDays.length) return null;
    const anchor = allDays[allDays.length - 1];
    let curFrom = '', curTo = '', prevFrom = '', prevTo = '', label = '', prevLabel = '', expected = 0;
    if (mode === 'week') {
      const anchorMs = dayStamp(anchor);
      const weekday = (new Date(anchorMs).getUTCDay() + 6) % 7;
      curFrom = stampDay(anchorMs - weekday * DAY_MS);
      curTo = anchor;
      prevFrom = shiftDay(curFrom, -7);
      prevTo = shiftDay(prevFrom, weekday);
      label = '本周';
      prevLabel = '上周同期';
    } else {
      /* d3 / d5 这类模式的天数就写在 id 里，不要另外维护一张表 */
      const n = Number(String(mode).replace(/\D/g, '')) || 3;
      const curDays = allDays.slice(-n);
      const prevDays = allDays.slice(Math.max(0, allDays.length - n * 2), Math.max(0, allDays.length - n));
      curFrom = curDays[0] || '';
      curTo = curDays[curDays.length - 1] || '';
      prevFrom = prevDays[0] || '';
      prevTo = prevDays[prevDays.length - 1] || '';
      label = `近 ${n} 个训练日`;
      prevLabel = `前 ${n} 个训练日`;
      expected = n;
    }
    const within = (r, from, to) => {
      const day = dayOf(r);
      return Boolean(day && from && to && day >= from && day <= to);
    };
    return {
      mode, label, prevLabel, curFrom, curTo, prevFrom, prevTo, expected,
      current: rows.filter((r) => within(r, curFrom, curTo)),
      previous: rows.filter((r) => within(r, prevFrom, prevTo)),
    };
  }

  /* ══ 模块 4 · 双英雄组合与替代候选 ════════════════════════════════ */
  function buildTeam(c, f) {
    const out = [];
    const scope = c.scope;
    const rows = scope.rows;
    const focusHero = scope.hero !== '全部' ? scope.hero : '';

    /* 01 双英雄组合：改成「搭档榜」——一行一组，全部列出、可排序。
       原来的 8×6 热力矩阵空格多、还只露前 48 格，组合越多越看不全；
       榜单是 1 维排序列表，组合再多也只是往下滚，永远显示全部。 */
    {
      /* 组合口径只认组合池里定义过的搭档；没进池的同场共现不算「组合」。 */
      const poolPairs = ((st.pd && st.pd.comboPool && st.pd.comboPool.pairs) || []);
      const poolKeys = new Set(poolPairs.map((p) => [...(p.heroes || [])].sort().join('|')));
      const allPairs = new Map();
      for (const r of rows) {
        if (!r.hero) continue;
        for (const mate of r.mates || []) {
          if (!mate.name || !mate.hero) continue;
          const key = [r.hero, mate.hero].sort().join('|');
          if (!poolKeys.has(key)) continue;
          const it = allPairs.get(key) || {a: r.hero, b: mate.hero, mate: mate.name, games: 0, wins: 0, decided: 0};
          it.games += 1;
          if (r.result === 'win' || r.result === 'loss') {
            it.decided += 1;
            if (r.result === 'win') it.wins += 1;
          }
          allPairs.set(key, it);
        }
      }
      const list = [...allPairs.values()].filter((v) => v.games >= 2);
      const rateOf = (x) => (x.decided ? x.wins / x.decided * 100 : null);
      /* 按胜率排时只认 ≥3 局的组合：2 局 100% 不该压过 12 局 75%。
         没有够格的就退回按场次，避免整页空榜。 */
      const byWin = f.comboSort === 'winRate';
      const solid = list.filter((x) => x.games >= 3);
      const pool = byWin && solid.length ? solid : list;
      const ranked = pool.slice().sort((a, b) => byWin
        ? (rateOf(b) ?? -1) - (rateOf(a) ?? -1) || b.games - a.games
        : b.games - a.games || (rateOf(b) ?? -1) - (rateOf(a) ?? -1));
      const top = ranked[0];
      const tools = selBar([cardSelect('comboSort', '排序', [['games', '按场次'], ['winRate', '按胜率']], f.comboSort)]);
      const comboRow = (x, i) => {
        const rate = rateOf(x);
        return `<div class="pv-combo-row${focusHero && x.a !== focusHero ? ' is-dim' : ''}">
          <span class="pv-combo-rank">${String(i + 1).padStart(2, '0')}</span>
          <span class="pv-combo-pair">
            <span class="pv-combo-hero">${heroPlain(x.a)}</span>
            <i class="pv-combo-plus" aria-hidden="true">+</i>
            <span class="pv-combo-hero">${heroPlain(x.b)}</span>
          </span>
          <span class="pv-combo-games"><b>${fmt(x.games)}</b><small>局</small></span>
          <span class="pv-combo-rate ${rateCls(rate)}">
            <b>${P(rate)}</b>
            <i class="pv-combo-bar" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, rate ?? 0))}%"></i></i>
          </span>
        </div>`;
      };
      const board = `<div class="pv-combo">
        <div class="pv-combo-row is-head" aria-hidden="true"><span>#</span><span>本人英雄 + 搭档英雄</span><span>场次</span><span>组合胜率</span></div>
        <div class="pv-combo-scroll" data-combo-scroll tabindex="0" role="group" aria-label="搭档组合排行，可滚动">
          ${ranked.length ? ranked.map(comboRow).join('')
            : `<p class="pv-empty">${poolKeys.size ? '组合池里的搭档在这个切片里没有出场 2 局以上。' : '组合池还没加载出来。'}</p>`}
        </div>
      </div>`;
      setN(allPairs.size);
      out.push(card('01', '双英雄组合',
        `组合池内「本人英雄 × 搭档英雄」共 <b>${fmt(allPairs.size)} 组</b>，出场 ≥ 2 局 <b>${fmt(list.length)} 组</b>${byWin ? '（按胜率排只认 ≥3 局）' : ''}；${byWin ? '胜率最高' : '用得最多'}的是 ${top ? `<b>${heroPlain(top.a)} + ${heroPlain(top.b)}</b>` : '—'}（${fmt(top ? top.games : 0)} 局 · ${P(top ? rateOf(top) : null)}）。`,
        tools + board,
        '只统计组合池里定义过的双人组合；同场共现但没进池的搭档不算组合。'));
    }

    /* 02 英雄替代候选：能力覆盖表
       之前这里画的是「与主英雄的能力重合百分比」——同分路候选本来就按
       ≥2 项重合筛过，于是七根柱子齐刷刷 100%，图上什么也没说。
       现在改成逐行对照：缺的这几项能力他能不能补、我打没打过、别人打出来什么样。 */
    {
      const common = c.topHeroes.filter(([, list]) => list.length >= 3);
      const picked = common.find(([hero]) => hero === focusHero) || common[0] || null;
      if (!picked) {
        out.push(card('02', '英雄替代候选', '这个切片里没有出场 3 局以上的英雄，谈不上替代。',
          V.empty('常用英雄样本不足。'), ''));
      } else {
        const [hero, list] = picked;
        const base = c.meta[hero] || {};
        const lane = base.lane || list[0].heroDefaultLane || list[0].lane;
        const caps = base.caps || [];
        const bench = c.bench || new Map();
        const kplStats = (st.pd && st.pd.detail && st.pd.detail.kplHeroStats) || {};
        const candidates = Object.entries(c.meta)
          .filter(([name, tag]) => name !== hero && tag.lane && tag.lane === lane)
          .map(([name, tag]) => {
            const shared = (tag.caps || []).filter((x) => caps.includes(x));
            const mine = c.byHero.get(name) || [];
            const wv = win(mine);
            const peer = bench.get(name);
            const kpl = kplStats[name];
            return {
              name, tag, shared, miss: caps.filter((x) => !(tag.caps || []).includes(x)),
              used: mine.length, rate: wv.rate,
              peerRate: peer && peer.decided ? peer.wins / peer.decided * 100 : null,
              peerGames: peer ? peer.games : 0,
              kplRate: kpl ? kpl.winRate : null, kplPicks: kpl ? kpl.picks : 0,
            };
          })
          .filter((x) => x.shared.length >= 2)
          .sort((a, b) => b.used - a.used || b.shared.length - a.shared.length
            || (b.peerRate ?? -1) - (a.peerRate ?? -1))
          .slice(0, 12);
        const tried = candidates.filter((x) => x.used).length;
        /* 主英雄的能力标签常常只有 2 项，候选都过了 ≥2 项的门槛，
           「能补什么」这一列就会千篇一律。所以只在这一列放**差异**：
           候选多出来的能力标出来，缺的也标出来，完全一样就写「同上」。 */
        const rows = candidates.map((x) => {
          const extra = (x.tag.caps || []).filter((cap) => !caps.includes(cap));
          const pills = [
            x.miss.length ? `<i class="pv-cap is-off">缺 ${S(x.miss.join('、'))}</i>` : '',
            ...extra.slice(0, 4).map((cap) => `<i class="pv-cap is-on">${S(cap)}</i>`),
          ].join('');
          const capCell = pills || '<span class="pv-cand-none">同上（能力完全覆盖）</span>';
          const mineTxt = x.used
            ? `<b>${fmt(x.used)}</b> 局 · <em class="${rateCls(x.rate)}">${P(x.rate)}</em>`
            : '<span class="pv-cand-none">没用过</span>';
          const peerTxt = x.peerGames
            ? `${fmt(x.peerGames)} 局 · <em class="${rateCls(x.peerRate)}">${P(x.peerRate)}</em>`
            : '<span class="pv-cand-none">无同英雄样本</span>';
          const kplTxt = isNum(x.kplRate)
            ? `<em class="${rateCls(x.kplRate)}">${P(x.kplRate)}</em><small>${fmt(x.kplPicks)} 局</small>`
            : '<span class="pv-cand-none">无 KPL 样本</span>';
          /* 最后给一句人话结论：教练扫一眼就知道这条该不该跟。 */
          let verdict = '样本不足，先观察', vcls = '';
          if (!x.used && !x.peerGames) { verdict = '没样本，纯名单'; }
          else if (x.used && isNum(x.rate) && x.rate >= 55) { verdict = '自己打过，能赢'; vcls = 'is-good'; }
          else if (x.used && isNum(x.peerRate) && x.peerRate >= 55) { verdict = '自己打得一般，别队行'; vcls = 'is-warn'; }
          else if (!x.used && isNum(x.peerRate) && x.peerRate >= 55) { verdict = '别队用得行，可以试'; vcls = 'is-good'; }
          else if (x.used) { verdict = '自己打过，没赢'; vcls = 'is-bad'; }
          else if (x.peerGames >= 5) { verdict = '别队也没打出来'; vcls = 'is-bad'; }
          return `<div class="pv-cand-row${x.used ? ' is-used' : ''}" role="row">
            <span class="pv-cand-hero" role="cell">${heroTag(x.name)}</span>
            <span class="pv-cand-caps" role="cell">${capCell}</span>
            <span class="pv-cand-num" role="cell">${mineTxt}</span>
            <span class="pv-cand-num" role="cell">${peerTxt}</span>
            <span class="pv-cand-num pv-cand-kpl" role="cell" title="KPL 职业赛该英雄胜率">${kplTxt}</span>
            <span class="pv-cand-verdict ${vcls}" role="cell">${S(verdict)}</span>
          </div>`;
        }).join('');
        const headRow = `<div class="pv-cand-row is-head" role="row">
          <span role="columnheader">可替代的英雄</span>
          <span role="columnheader">比 ${S(hero)} 多 / 少的能力</span>
          <span role="columnheader">本人已用</span>
          <span role="columnheader">同英雄其他人</span>
          <span role="columnheader" title="KPL 职业赛该英雄胜率">KPL 胜率</span>
          <span role="columnheader">怎么读</span>
        </div>`;
        const body = candidates.length
          ? `<div class="pv-cands" role="table" aria-label="替代英雄能力覆盖表">${headRow}${rows}</div>`
          : emptyWith('同分路里没有能补这几项的英雄',
            `${S(lane)} 上再没有第二个带 ≥2 项「${S(caps.join(' / ') || '核心能力')}」的英雄。换一个主英雄看，或去英雄页查跨分路的替代。`,
            '清除切片条件');
        const listNote = candidates.length
          ? note(`候选取「同默认分路 + 至少 2 项能力重合」，按本人是否打过排序：<b>${fmt(tried)} / ${fmt(candidates.length)}</b> 个你已经用过，其余是还没试过的备选。`)
          : '';
        out.push(card('02', '英雄替代候选',
          `${heroTag(hero)} 在 <b>${S(lane)}</b> 的能力标签是 ${S(caps.join('、') || '未标注')}，同分路能补上其中 ≥2 项的有 <b>${fmt(candidates.length)} 个</b>英雄。`,
          grid([
            panel(`${hero} 的能力 → 谁来补`, body, {
              span: 12,
              foot: '「本人已用」「同英雄其他人」是训练赛样本，「KPL 胜率」是职业赛参照，两边不混算',
            })]),
          '能力标签来自 resources/hero_tags.json，是英雄机制的粗分类；同英雄其他人的样本取同一批对局里别队的记录，不含本人。'));
      }
    }
    return out;
  }

  /* ══ 页面装配 ══════════════════════════════════════════════════════ */
  function render(board, name, detail, kplBaseline) {
    cardSeq = 0;
    ensureGradeRules();
    const allRows = (detail && detail.rows) || [];
    const back = st && st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
    /* 空态里给几个本队选手直达入口：按选手ID去重，挂多个游戏名的只出现一次。
       链接万一传错键（例如只传了数字 ID），教练不用回档案页重新翻名单。 */
    const peerLinks = () => {
      const members = new Map((((board && board.identity && board.identity.members) || []))
        .map((m) => [String(m.id), m]));
      const seen = new Map();
      for (const p of ((board && board.players) || [])) {
        if (!p || !p.name || p.side !== 'own') continue;
        const owner = members.get(String(p.memberId || ''));
        const label = owner ? (owner.label || owner.name || p.name) : p.name;
        const games = p.games || 0;
        const prev = seen.get(label);
        if (!prev || games > prev.games) seen.set(label, {label, games});
      }
      return [...seen.values()].sort((a, b) => b.games - a.games).slice(0, 6)
        .map((x) => `<a class="pdx-empty-peer" href="#playerdetail/${encodeURIComponent(x.label)}">${S(x.label)} · ${fmt(x.games)} 局</a>`).join('');
    };
    const emptyHead = (title, sub) => `<header class="hero-masthead"><div class="page-intro"><div class="pls-head">
      <span class="pls-back-row"><a class="hero-back" href="${S(back.href)}">← ${S(back.label)}</a></span>
      <div class="pls-id"><div><h1>${S(title)}</h1><p class="pls-meta">${S(sub)}</p></div></div></div></div></header>`;
    if (!allRows.length) {
      const peers = peerLinks();
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">
        ${emptyHead('未找到这名选手', '换一个游戏名，或从下面的本队选手里选')}
        <div class="hero-detail-grid"><section class="section"><div class="pdx-empty">
          <span class="pdx-empty-icon" aria-hidden="true">?</span>
          <h2>没有「${S(name)}」的对局记录</h2>
          <p>选手个人页按<b>游戏名</b>或<b>选手 ID</b>取数，当前营地面板里没有 <code>${S(name)}</code> 的出场。先回档案页确认名字，再打开对应选手。</p>
          <div class="pdx-empty-actions"><a class="control is-primary" href="${S(back.href)}">${glyph('players', {size: 18})}回到${S(back.label)}</a><button type="button" class="control" data-action="refresh">${glyph('refresh', {size: 18})}刷新数据</button></div>
          ${peers ? `<div class="pdx-empty-peers"><span>本队选手：</span>${peers}</div>` : ''}
        </div></section></div></div>`;
    }

    /* ── 切片 → 全页唯一的取数口径 ─────────────────────────────────── */
    const scope = buildScope(allRows);
    const rows = scope.rows;
    const identity = detail.identity || {};
    const byLane = group(rows, (r) => r.lane);
    const laneOrder = LANES.filter((lane) => byLane.has(lane));
    for (const lane of byLane.keys()) if (!laneOrder.includes(lane)) laneOrder.push(lane);
    const mix = identity.laneMix || [];
    const mainLane = (mix[0] && mix[0].lane) || laneOrder[0] || '未记录';
    const focusLane = scope.lane !== '全部' ? scope.lane : mainLane;
    const byHero = group(rows.filter((r) => r.hero), (r) => r.hero);
    const topHeroes = [...byHero].sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
    /* 环比口径与顶部范围选择器一致：
       本期 = 你选的范围（rows）；上期 = 紧邻该范围之前、等长的训练日。
       选「近 10 个训练日」就是本期 10 天 vs 前 10 天，不再另挑窗口。 */
    const prevCtx = (() => {
      const allDays = daysOf(allRows);
      const curDays = daysOf(rows);
      const n = curDays.length;
      if (!n || !allDays.length) return {prev: new Map(), label: '上期'};
      const firstIdx = allDays.indexOf(curDays[0]);
      const startIdx = firstIdx < 0 ? allDays.length - n : firstIdx;
      const prevDays = allDays.slice(Math.max(0, startIdx - n), startIdx);
      const prevRows = allRows.filter((r) => { const d = dayOf(r); return d && prevDays.includes(d); });
      return {prev: group(prevRows, (r) => r.lane), label: `前 ${n} 个训练日`};
    })();
    const ctx = {
      board, name, detail, allRows, rows, identity, scope, focusLane,
      prevByLane: prevCtx.prev, prevLabel: prevCtx.label,
      desc: [...rows].reverse(),
      laneSamples: detail.laneSamples || {},
      laneDistributions: detail.laneDistributions || laneDistOf(allRows),
      kplBaseline: kplBaseline || {leagues: [], lanes: {}},
      kplHeroStats: detail.kplHeroStats || {},
      meta: detail.heroMeta || {}, opponents: detail.opponents || [],
      bench: heroBench(board, (detail.identity && detail.identity.ownNames) || [name]),
      byLane, laneOrder, mainLane, byHero, topHeroes,
    };
    rangeLabel = scopeText(scope);
    const f = readFilters(ctx);

    /* ── 头部：身份 + 全量 KPI（切片统计在切片条里，两者不混）────────── */
    const total = win(allRows);
    const mainList = group(allRows, (r) => r.lane).get(mainLane) || [];
    const allLaneCount = new Set(allRows.map((r) => r.lane).filter(Boolean)).size;
    const kpiHtml = `<div class="hero-kpi pl-kpi" role="group" aria-label="关键指标">${[
      ['出场', `${fmt(allRows.length)} 局`, `${fmt(total.wins)} 胜 ${fmt(total.decided - total.wins)} 负`],
      ['胜率', P(total.rate), `${fmt(total.wins)} / ${fmt(total.decided)} 有胜负`],
      ['主位置', S(mainLane), `${fmt(mainList.length)} 局 · 胜率 ${P(win(mainList).rate)}`],
      ['副位置覆盖', `${fmt(allLaneCount - 1)} 个位置`, `${fmt(allRows.length - mainList.length)} 局`],
      ['英雄池', `${fmt(new Set(allRows.map((r) => r.hero).filter(Boolean)).size)} 个英雄`,
        `覆盖 ${fmt(new Set(allRows.map((r) => r.heroType).filter(Boolean)).size)} 类职业`],
      ['训练日', `${fmt(daysOf(allRows).length)} 个`, rangeText(daysOf(allRows))],
    ].map(([label, value, noteText], i) => `<div class="hero-kpi-cell${i < 2 ? ' is-key' : ''}"><span>${S(label)}</span><strong>${value}</strong><p>${S(noteText)}</p></div>`).join('')}</div>`;

    const allPlayers = ((board && board.players) || []).filter((p) => p && p.name && (p.games || 0) >= 1);
    const regulars = allPlayers.filter((p) => p.side === 'own' && (p.games || 0) >= 3);
    const ownSide = allPlayers.filter((p) => p.side === 'own');
    const pick = [regulars, ownSide, allPlayers].find((list) => list.length >= 2) || allPlayers;
    /* 换选手下拉按选手ID去重：挂多个游戏名的只出现一次，名字一律 ID。 */
    const membersById = new Map((((board && board.identity && board.identity.members) || []))
      .map((m) => [String(m.id), m]));
    const rosterById = new Map();
    for (const p of pick) {
      const owner = membersById.get(String(p.memberId || ''));
      const label = owner ? (owner.label || owner.name || p.name) : p.name;
      const games = p.games || 0, bound = p.bound ? 1 : 0;
      const prev = rosterById.get(label);
      if (!prev || bound > prev.bound || (bound === prev.bound && games > prev.games)) {
        rosterById.set(label, {label, games, bound});
      }
    }
    const roster = [...rosterById.values()]
      .sort((a, b) => b.bound - a.bound || b.games - a.games)
      .map((it) => [it.label, it.games]);
    const picked = new Set([st && st.a, st && st.b].filter(Boolean));
    const inCompare = picked.has(name);
    const compareCount = picked.size;

    const backExtra = String(back.href).startsWith('#playerarchive')
      ? '' : `<a class="hero-back is-quiet" href="#playerarchive">选手档案</a>`;
    /* 头部的 DOM 结构一次写清楚：header > page-intro > (pls-head, intro-actions)，
       再跟一条 KPI 带。少一个 </div> 浏览器就会把后面整页拆到根节点外面去。 */
    const head = `<header class="hero-masthead"><div class="page-intro">
      <div class="pls-head">
        <span class="pls-back-row"><a class="hero-back" href="${S(back.href)}">← ${S(back.label)}</a>${backExtra}</span>
        <div class="pls-id">
          <span class="pls-ava" aria-hidden="true">${S(String(name).trim().slice(0, 1) || '?')}</span>
          <div class="pls-id-copy">
            <h1>${S(name)}</h1>
            <p class="pls-meta">
              <span class="pls-chip is-role">${S(mainLane)}</span>
              <span class="pls-chip">${identity.side === 'own' ? '本队' : '对手'}</span>
              <span class="pls-chip${identity.bound ? ' is-ok' : ' is-warn'}">${identity.bound ? '已匹配' : '未匹配'}</span>
              <span class="pls-chip">${fmt(allRows.length)} 局</span>
            </p>
          </div>
        </div>
      </div>
      <div class="intro-actions">${roster.length > 1 ? `<label class="pv-sel is-head"><span class="pv-sel-label">换选手</span>
          <span class="pv-sel-box"><select data-pl-switch-player aria-label="切换到其他选手">
            ${roster.map(([who, games]) => `<option value="${S(who)}"${who === name ? ' selected' : ''}>${S(who)} · ${fmt(games)} 局</option>`).join('')}
          </select><i class="pv-sel-caret" aria-hidden="true"></i></span></label>` : ''}<span class="pv-pos" title="按出场数排序的位置，可用键盘 ← → 切换">第 ${fmt(Math.max(1, roster.findIndex(([who]) => who === name) + 1))} / ${fmt(roster.length)} 位</span>${identity.bound || identity.side === 'enemy' ? '' : `<button class="control" data-pl-name="${S(name)}">${glyph('players', { size: 18 })}命名并归队</button>`}${compareCount >= 2
          ? `<a class="control is-primary is-on" href="#playercompare">${glyph('compare', { size: 18 })}去看对比（${compareCount}/2）</a>`
          : `<button class="control is-primary${inCompare ? ' is-on' : ''}" data-pl-pick-b="${S(name)}">${glyph('compare', { size: 18 })}${inCompare ? `已放入对比（${compareCount}/2）` : '放入对比'}</button>`}<button class="control" data-action="refresh">${glyph('refresh', { size: 18 })}刷新数据</button></div>
    </div></header>${kpiHtml}`;

    const modules = [
      ['bench', '同分路对比', '自家 vs 规则标准线', (c, ff) => buildBench(c, ff)],
      ['portrait', '选手综合画像', '位置能力、同位置对标', (c, ff) => buildPortrait(c, ff)],
      ['heroes', '英雄池', '使用图谱与同英雄对照', (c, ff) => buildHeroes(c, ff)],
      ['trend', '英雄池变动', '', (c, ff) => buildTrend(c, ff)],
      ['team', '组合与替代', '双英雄组合矩阵与英雄替代候选', (c, ff) => buildTeam(c, ff)],
    ];
    /* 模块导航留在页面流；只让切片条吸顶，避免窄屏被两层工具栏占满。 */
    const moduleNav = `<nav class="hero-anchor-nav pdx-nav" aria-label="模块快速导航">
      ${modules.map(([, label], i) => `<button type="button" data-hero-scroll="${i}">${String(i + 1).padStart(2, '0')} ${S(label)}</button>`).join('')}
      <span class="pv-keyhint" aria-hidden="true"><kbd>←</kbd><kbd>→</kbd>换选手</span>
      <button type="button" class="pv-reset" data-pdx-print title="打印整页（可在对话框里存成 PDF）">${glyph('export', { size: 18 })}整页 PDF</button>
      <button type="button" class="pv-reset" data-pdx-reset title="把所有切片与卡片筛选恢复默认">${glyph('refresh', { size: 18 })}重置全部</button>
    </nav>`;
    const dock = `<div class="pdx-dock" style="--pdx-top:${stickyTop()}px">${scopeBar(ctx)}</div>`;

    /* 切片命中 0 局时不再画一堆空图：直接给一张能让教练退回上一步的卡 */
    if (!rows.length) {
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${moduleNav}${dock}
        <div class="hero-detail-grid"><section class="section" data-pdx-module="空切片" data-pdx-key="empty">
          <div class="pdx-cards">${card('00', '这个切片里没有对局', '范围、分路、英雄、对手、结果五个条件叠在一起，把数据筛空了。',
            emptyWith('当前切片 0 局', `${scopeText(scope)} —— 换个范围或去掉一个条件就能看到数据。`),
            '切片条上的「清除切片」会把这五个条件一起恢复成全量。')}</div>
        </section></div>
        <button type="button" class="pv-top" data-pdx-top aria-label="回到顶部" title="回到顶部">${glyph('arrow-up', { size: 18 })}</button></div>`;
    }

    const sections = modules.map(([key, label, sub, build], i) =>
      block(`${String(i + 1).padStart(2, '0')} / ${label}`, sub,
        `<div class="pdx-cards">${build(ctx, f).join('')}</div>`, '',
        `data-pdx-module="${S(label)}" data-pdx-key="${S(key)}"`)).join('');
    return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${moduleNav}${dock}<div class="hero-detail-grid">${sections}</div>
      <button type="button" class="pv-top" data-pdx-top aria-label="回到顶部" title="回到顶部">${glyph('arrow-up', { size: 18 })}</button></div>`;
  }

  /* ── 卡片级筛选：只留不跨卡的维度，分路/英雄/时间都归切片条 ────── */
  function readFilters(c) {
    const ui = stateUI();
    const leagueNames = (c.kplBaseline.leagues || []).map((l) => l.name);
    const f = {
      bench: one([...new Set([...TEAM_BENCH_METRICS, ...KPL_BENCH_METRICS])], ui.bench, 'winRate'),
      benchSource: one(['', 'kpl'], ui.benchSource, ''),
      kplLeague: one(leagueNames.includes(ui.kplLeague) ? [ui.kplLeague] : [], ui.kplLeague, ''),
      benchField: one(BENCH_FIELDS.map(([key]) => key), ui.benchField, 'gold10'),
      period: one(PERIOD_MODES.map((m) => m[0]), ui.period, 'd3'),
      comboSort: one(['games', 'winRate'], ui.comboSort, 'games'),
    };
    Object.assign(ui, f);
    return f;
  }

  return {render};
}
