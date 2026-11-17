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
import {createPlayerViz} from './player-viz.js';

export function createPlayerDetail(h) {
  const {esc, fmt, portrait, block, empty, st, profile} = h;
  const V = createPlayerViz({esc, fmt});
  const {S, N, isNum, clamp, selBar, panel, grid, w} = V;
  const P = (v, d = 1) => (isNum(v) ? fmt(v, d) + '%' : '—');
  const signed = (v, d = 0) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmt(v, d)}` : '—');

  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

  /* 指标登记表：一处定义，全页共用标签、小数位和单位口径。 */
  const FIELDS = {
    games: {label: '场次', digits: 0, kind: 'int'},
    winRate: {label: '胜率', digits: 1, kind: 'pct'},
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
    rating: {label: '评分', digits: 1, kind: 'num'},
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
  const RADAR_SHORT = {
    kda: 'KDA', gpm: '经济', hdpm: '对英雄输出', damageShare: '输出占比', goldShare: '经济占比',
    takenShare: '承伤占比', participation: '参团', ctrlPerMin: '控制', rating: '评分', dtpm: '分均承伤',
    monsterCoin: '野区', dpm: '总输出', winRate: '胜率', mvpRate: 'MVP',
  };
  const LANE_FOCUS = {
    '游走': ['participation', 'takenShare', 'ctrlPerMin', 'kda', 'rating', 'dtpm'],
    '打野': ['gpm', 'monsterCoin', 'participation', 'hdpm', 'rating', 'kda'],
    '对抗路': ['hdpm', 'damageShare', 'takenShare', 'gpm', 'kda', 'rating'],
    '中路': ['hdpm', 'damageShare', 'gpm', 'participation', 'kda', 'rating'],
    '发育路': ['hdpm', 'damageShare', 'gpm', 'goldShare', 'kda', 'rating'],
  };
  /* 「指标全景」矩阵用的 12 项指标 */
  const PANEL_KEYS = ['rating', 'kda', 'gpm', 'hdpm', 'damageShare', 'goldShare', 'participation', 'takenShare', 'ctrlPerMin', 'dtpm', 'monsterCoin', 'mvpRate'];
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
      'damageShare', 'goldShare', 'rating', 'ctrlPerMin', 'dtpm', 'monsterCoin'];
    const out = {};
    for (const r of rows) {
      const cell = out[r.lane] || (out[r.lane] = {});
      for (const key of keys) if (isNum(r[key])) (cell[key] || (cell[key] = [])).push(r[key]);
    }
    return out;
  }
  const lanePctile = (c, lane, key, value) => percentile(laneDist(c, lane, key), value);

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
  let foldedCards = new Set();
  let cardN = null;
  let rangeLabel = '';
  const setN = (n) => { cardN = isNum(n) ? n : null; };
  const card = (no, title, lead, body, foot = '') => {
    const id = 'c' + (++cardSeq);
    const folded = foldedCards.has(id);
    const badge = isNum(cardN) ? `<span class="pdx-n" title="这张卡的结论建立在多少局上">N=${fmt(cardN)} 局</span>` : '';
    cardN = null;
    return `<article class="pdx-card${folded ? ' is-folded' : ''}" data-pdx-fold-id="${id}">
    <div class="pdx-card-head"><span class="pdx-no">${S(no)}</span><div>
      <h3>${S(title)}${badge}</h3><p class="pdx-lead">${lead}</p></div>
      <span class="pdx-tools">
        <button type="button" class="pdx-fold" data-pdx-fold="${id}" aria-expanded="${folded ? 'false' : 'true'}"
          title="折叠 / 展开这张卡">⌄</button>
        <button type="button" class="pdx-shot" data-pdx-shot="${id}"
          title="只打印这张卡（系统打印对话框里可选存为 PDF 或图片）">⤓</button>
      </span></div>
    <p class="pdx-range">范围：${S(rangeLabel)}</p>
    <div class="pdx-card-body">${body}</div>
    ${foot ? `<p class="pdx-foot">${foot}</p>` : ''}</article>`;
  };
  const na = (text = '无数据', title = '') => `<span class="pv-na"${title ? ` title="${S(title)}"` : ''}>${S(text)}</span>`;
  const emptyWith = (title, hint, relaxLabel = '清除切片条件') => `<div class="pv-empty2">
    <b>${S(title)}</b><p>${S(hint)}</p>
    <button type="button" class="pv-relax" data-pdx-reset>${S(relaxLabel)}</button></div>`;
  const heroTag = (hero, note) => `<a class="pv-hero" href="#hero/${encodeURIComponent(String(hero || ''))}"
    title="打开英雄页：${S(hero || '未知')}">${portrait(hero)}<b>${S(hero || '未知')}</b>${note ? `<small>${S(note)}</small>` : ''}</a>`;
  const heroPlain = (hero) => `<span class="pv-hero">${portrait(hero)}<b>${S(hero || '未知')}</b></span>`;
  const resChip = (r) => `<em class="pv-chip ${r === 'win' ? 'is-win' : r === 'loss' ? 'is-loss' : 'is-quiet'}">${RESULT_TXT[r] || '—'}</em>`;
  const stats = (items) => `<div class="pv-stats">${items.map(([label, value, note]) =>
    `<div><span>${S(label)}</span><strong>${value}</strong><small>${S(note || '')}</small></div>`).join('')}</div>`;
  const note = (text) => `<p class="pv-note">${text}</p>`;
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
      const known = ['header.masthead', '.secondary-wrap', '.site-header', '.app-bar', '.topbar'];
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
      ${scopeIsDefault(s) ? '' : `<button type="button" class="pv-reset is-scope" data-pdx-reset>清除切片</button>`}
    </div>`;
    const custom = s.range === 'custom' ? `<label class="pv-sel is-scope"><span class="pv-sel-label">起</span>
        <span class="pv-sel-box"><input type="date" data-pdx-select="from" value="${S(s.customFrom || s.from || '')}"
          min="${S(s.allDays[0] || '')}" max="${S(s.allDays[s.allDays.length - 1] || '')}" aria-label="起始训练日"></span></label>
      <label class="pv-sel is-scope"><span class="pv-sel-label">止</span>
        <span class="pv-sel-box"><input type="date" data-pdx-select="to" value="${S(s.customTo || s.to || '')}"
          min="${S(s.allDays[0] || '')}" max="${S(s.allDays[s.allDays.length - 1] || '')}" aria-label="结束训练日"></span></label>` : '';
    return `<div class="pdx-scope" role="region" aria-label="分析切片" style="--pdx-top:${stickyTop()}px">
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

  /* ══ 模块 1 · 综合画像 ═════════════════════════════════════════════ */
  function buildPortrait(c, f) {
    const out = [];
    const scope = c.scope;

    /* 01 身份与数据合并状态（身份是全量口径，不随切片变） */
    {
      const id = c.identity, accounts = id.accountIds || [], nicks = id.nicknames || [];
      const body = `<div class="pv-id-main"><span class="pv-id-ava">${S(String(c.name).slice(0, 1))}</span>
          <div><b>${S(c.name)}</b><small>游戏名 · 营地昵称</small></div>
          <span class="pv-badge ${id.bound ? 'is-ok' : 'is-warn'}">${id.bound ? '已认领到选手ID' : '待认领昵称'}</span></div>
        <div class="pv-id-grid">
          <div><span>真实选手ID</span><b>${id.playerId ? S(id.playerId) : '未认领'}</b></div>
          <div><span>归属战队</span><b>${id.teamName ? S(id.teamName) : '未归队'}</b></div>
          <div><span>营地账号</span><b>${fmt(accounts.length)} 个</b></div>
          <div><span>关联游戏名</span><b>${fmt(nicks.length)} 个</b></div>
        </div>
        ${id.bound ? '' : `<button class="control" data-pl-name="${S(c.name)}" style="margin-top:14px">命名并归队</button>`}`;
      out.push(card('01', '身份与数据合并状态',
        `<b>${fmt(c.allRows.length)} 局</b>集中在 <b>${fmt(nicks.length)} 个游戏名</b>、<b>${fmt(accounts.length)} 个营地账号</b>，当前${id.bound ? '已认领' : '待认领'}。`,
        body,
        '营地昵称 = 游戏名，教练命名的真名 = 选手ID；历史对局按当时的游戏名保留，改名不回写。'));
    }

    /* 02 位置能力：分路取切片，切片是「全部」时用主位置 */
    {
      const lane = c.focusLane;
      const list = c.byLane.get(lane) || [];
      const keys = LANE_FOCUS[lane] || LANE_FOCUS['中路'];
      const mainKeys = LANE_FOCUS[c.mainLane] || LANE_FOCUS['中路'];
      const w2 = win(list);
      const pcts = keys.map((key) => lanePctile(c, lane, key, mean(list, (r) => r[key])));
      const axes = keys.map((key, i) => ({label: RADAR_SHORT[key] || fieldLabel(key), value: pcts[i]}));
      const series = [{cls: 'is-a', name: `${lane} · 本人`, values: pcts}];
      if (lane !== c.mainLane) {
        const mainList = c.byLane.get(c.mainLane) || [];
        series.push({
          cls: 'is-b', name: `${c.mainLane} · 主位置`,
          values: mainKeys.map((key) => lanePctile(c, c.mainLane, key, mean(mainList, (r) => r[key]))),
        });
      }
      const tiles = `<div class="pv-tiles3">${keys.map((key, i) => V.gauge({
        value: pcts[i], label: fieldLabel(key),
        sub: `本人 ${showVal(key, mean(list, (r) => r[key]))} · 中位 ${showVal(key, median(laneDist(c, lane, key)))}`,
      })).join('')}</div>`;
      setN(list.length);
      out.push(card('02', '位置能力 · 专项指标',
        `切片内的分路是 <b>${S(lane)}</b>（${scope.lane === '全部' ? '没限定分路，取主位置' : '来自上方「分路」'}）：<b>${fmt(list.length)} 局</b>、胜率 <b>${P(w2.rate)}</b>；`
        + `仪表刻度是「同位置分位」，50 就是中位。`,
        grid([
          panel('六项指标 · 同位置分位', V.radar({axes, series, size: 460, aria: `${lane} 六项专项指标的分位雷达`}), {
            span: 5, foot: lane === c.mainLane ? `单线 = 本人在本分路的相对位置；同类参照 ${fmt(laneDist(c, lane, keys[0]).length)} 局`
              : '实线 = 切片分路，虚线 = 主位置对照',
          }),
          panel('专项指标仪表', tiles, {span: 7, foot: '环 = 同位置分位，数字 = 分位值，下方是本人数值与中位'}),
        ]),
        '分位参照是同实际分路的全部逐局记录（全量，不随切片变）；样本不足 2 局的指标照样给值，但不判分位。'));
    }

    /* 03 指标越线：分路 × 12 项指标的热力矩阵 */
    {
      const lanesInScope = scope.lane === '全部' ? c.laneOrder : [scope.lane];
      const rows = lanesInScope.map((lane) => {
        const list = c.byLane.get(lane) || [];
        return {
          label: lane, labelHtml: `${S(lane)}<small class="pv-heat-count">${fmt(list.length)} 局</small>`,
          cls: lane === c.mainLane ? 'is-self' : '',
          cells: PANEL_KEYS.map((key) => {
            const p = lanePctile(c, lane, key, mean(list, (r) => r[key]));
            if (p == null) return {v: null};
            const dim = f.anomalyDir === 'all'
              || (f.anomalyDir === 'hi' && p >= 80) || (f.anomalyDir === 'lo' && p <= 20);
            return {
              v: dim ? p : 50, text: `${fmt(p, 0)}`,
              cls: dim ? '' : 'is-muted',
              title: `${lane} ${fieldLabel(key)} · 本人 ${showVal(key, mean(list, (r) => r[key]))} · 同位置 ${Math.round(p)} 分位`,
            };
          }),
        };
      });
      const tools = selBar([
        cardSelect('anomalyDir', '越线', [['all', '看全部'], ['hi', '只看偏高'], ['lo', '只看偏低']], f.anomalyDir),
      ]);
      let count = 0;
      for (const lane of lanesInScope) {
        const list = c.byLane.get(lane) || [];
        if (list.length < 2) continue;
        for (const key of PANEL_KEYS) {
          const p = lanePctile(c, lane, key, mean(list, (r) => r[key]));
          if (p != null && (p >= 80 || p <= 20)) count += 1;
        }
      }
      setN(scope.rows.length);
      out.push(card('03', '指标越线矩阵',
        `${fmt(lanesInScope.length)} 条实际分路 × ${fmt(PANEL_KEYS.length)} 项指标的分位矩阵；当前切片共 <b>${fmt(count)} 格</b>越出 20 / 80 分位线。`,
        tools + grid([panel('同分路分位热力', V.heat({
          rows,
          cols: PANEL_KEYS.map((key) => ({label: RADAR_SHORT[key] || fieldLabel(key)})),
          diverging: true, aria: '分路与指标的分位热力矩阵', headW: 132, colW: 78, fit: w(12),
          fmtV: (v) => `${fmt(v, 0)} 分位`,
          legend: '<span>越左越靠后</span><i></i><span>越右越靠前</span><span style="margin-left:8px">50 = 同位置中位</span>',
        }), {span: 12, foot: '颜色深浅 = 离中位的距离；格子里的数字是分位值。分路一栏想只看一条，用上方「分路」切片。'})]),
        '分位参照是同实际分路的全部逐局记录，不是选手均值；越线只说明分布位置，不判断好坏。'));
    }

    /* 04 同位置对标：同一指标的选手排行柱 + 三个分位仪表 */
    {
      const lane = c.focusLane;
      const key = f.bench;
      const all = (c.laneSamples[lane] || []);
      const valid = all.filter((s) => s.games >= 2 && isNum(s[key]));
      const scored = valid.slice().sort((a, b) => b[key] - a[key]);
      const top = scored.slice(0, 11);
      const selfIn = top.some((s) => s.name === c.name);
      const selfRow = selfIn ? null : scored.find((s) => s.name === c.name);
      const rows = selfRow ? [...top, selfRow] : top;
      const rank = scored.findIndex((s) => s.name === c.name) + 1;
      const tools = selBar([cardSelect('bench', '指标', [
        ['rating', '评分'], ['winRate', '胜率'], ['kda', 'KDA'], ['hdpm', '对英雄输出'], ['participation', '参团率'],
      ], key)]);
      const chart = rows.length ? V.columns({
        labels: rows.map((s) => s.name),
        labelsHtml: rows.map((s) => s.name === c.name ? `<span class="pv-col-self">${S(s.name)}</span>` : `<span>${S(s.name)}</span>`),
        series: [{
          values: rows.map((s) => s[key]),
          clsAt: rows.map((s) => (s.name === c.name ? 'is-mark' : 'is-flat')),
          texts: rows.map((s) => showVal(key, s[key])),
        }],
        W: w(8), H: 280, padL: 44, padR: 12, maxBarW: 40, baseline: 'auto',
        fmtV: (v) => N(v, fieldDigits(key) > 1 ? 2 : 1),
        refs: median(scored.map((x) => x[key])) == null ? []
          : [{v: median(scored.map((x) => x[key])), label: '同位置中位'}],
        aria: `同位置选手 ${fieldLabel(key)} 排行`,
      }) : emptyWith('这一路还没有达标的选手',
        `本人${lane}只有 ${fmt((c.byLane.get(lane) || []).length)} 局，同位置里也没有达到 2 局门槛的人。`);
      const selfGames = (c.byLane.get(lane) || []).length;
      const selfRate = win(c.byLane.get(lane) || []).rate;
      const selfRating = mean(c.byLane.get(lane) || [], (r) => r.rating);
      const pGames = percentile(all.map((s) => s.games), selfGames);
      const pRate = percentile(all.map((s) => s.winRate), selfRate);
      const pRating = percentile(all.map((s) => s.rating), selfRating);
      const gauges = `<div class="pv-tiles3">${[
        V.gauge({value: pGames, label: '场次分位', sub: `${fmt(selfGames)} 局`}),
        V.gauge({value: pRate, label: '胜率分位', sub: P(selfRate)}),
        V.gauge({value: pRating, label: '评分分位', sub: N(selfRating, 2)}),
      ].join('')}</div>`;
      setN(valid.length);
      out.push(card('04', `同位置对标 · ${lane}`,
        `${S(lane)} 共 <b>${fmt(all.length)} 人</b>，达 <b>2 局</b>门槛 <b>${fmt(valid.length)} 人</b>；按 <b>${S(fieldLabel(key))}</b> 排，本人 <b>${rank ? `第 ${fmt(rank)} 位` : na('未进榜', '本人该分路不足 2 局，不进榜')}</b>。`,
        tools + grid([
          panel(`按${fieldLabel(key)}排行 · 前 ${fmt(rows.length)} 人`, chart, {span: 8, foot: '强调色柱 = 本人，灰色柱 = 同位置其他人'}),
          panel('本人三项分位', gauges, {span: 4, foot: `参照 ${fmt(all.length)} 名同位置选手`}),
        ])
        + (all.length - valid.length ? note(`另有 <b>${fmt(all.length - valid.length)} 人</b>只打了 1 局或缺少该项数据，不进榜。`) : ''),
        '榜单只给单项原始值，不用统一综合分排序；1 局样本不进榜，避免一次高光把人顶到前面。'));
    }

    return out;
  }

  /* ══ 模块 2 · 英雄池 ═══════════════════════════════════════════════ */
  function heroBench(board, selfName) {
    const map = new Map();
    for (const g of board.games || []) {
      const ownWin = g.result === 'win', ownLose = g.result === 'loss';
      for (const [side, arr] of [['own', g.own || []], ['enemy', g.enemy || []]]) {
        const won = side === 'own' ? ownWin : ownLose;
        for (const p of arr) {
          if (!p.hero || p.name === selfName) continue;
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

  /* 训练日一多（一整个赛季 40 天以上）就不按天铺列，自动并成周，
     免得热力图变成一排 6px 宽的竖线。 */
  function dayColumns(rows) {
    const days = daysOf(rows);
    if (days.length <= 21) return days.map((day) => ({key: day, label: day.slice(5), days: [day], weekly: false}));
    const map = new Map();
    for (const day of days) {
      const key = weekStart(day);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(day);
    }
    return [...map].map(([key, list]) => ({
      key, days: list, weekly: true,
      label: list.length > 1 ? `${list[0].slice(5)}~${list[list.length - 1].slice(5)}` : list[0].slice(5),
    }));
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
        return {
          label: hero, value: list.length, pick: hero, cls: laneClsOf(lanes[0]),
          icon: portrait(hero),
          sub: `${fmt(list.length)} 局 · 胜率 ${P(wv.rate)}`,
          title: `${hero} · ${fmt(list.length)} 局 · 胜率 ${P(wv.rate)} · 评分 ${N(mean(list, (r) => r.rating), 1)} · 分路 ${lanes.join('/')}`,
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
            span: 7, foot: '颜色：对抗 / 打野 / 中路 / 发育 / 游走；点方块 = 把整页切到这位英雄，再点一次（下拉里选「全部」）取消',
          }),
          panel('职业构成', V.ring({
            items: ringItems, size: 200, aria: '英雄职业构成', top: 8,
            center: {value: scope.rows.length, label: '切片场次', text: `${fmt(scope.rows.length)}`},
          }), {span: 5, foot: `覆盖 ${fmt(byType.length)} 类职业`}),
        ]) + (restText ? note(restText) : '') + (below ? note(banned) : ''),
        '职业元数据来自 resources/hero_tags.json 的 defaultType；面积只算次数，不代表强度。'));
    }

    /* 02 使用节奏：英雄 × 训练日热力（列多则滚动/按周）+ 实际 × 默认分路 */
    if (!pool.length) {
      out.push(card('02', '使用节奏与分路类型',
        `没有英雄达到 ${fmt(scope.min)} 局门槛，这段节奏看不出规律。`,
        emptyWith('门槛把英雄全筛掉了',
          `切片里 ${fmt(scope.rows.length)} 局分散在 ${fmt(c.topHeroes.length)} 个英雄上，没有一个到 ${fmt(scope.min)} 局。把「英雄门槛」调到「全部英雄」再看。`,
          '清除切片条件'),
        '一局英雄撑不起节奏判断，所以门槛会把它们整体挡在图表外。'));
    } else {
      const cols = dayColumns(scope.rows);
      const heatHeroes = pool.slice(0, 9);
      const heatRows = heatHeroes.map(([hero, list]) => ({
        label: hero, labelHtml: heroPlain(hero),
        cells: cols.map((col) => {
          const hit = list.filter((r) => col.days.includes(dayOf(r)));
          const n = hit.length;
          const wv = win(hit);
          return n
            ? {v: n, text: fmt(n), title: `${hero} · ${col.label} · ${fmt(n)} 局 · 胜率 ${P(wv.rate)}`}
            : {v: null};
        }),
      }));
      const defaults = [...new Set(scope.rows.map((r) => r.heroDefaultLane).filter(Boolean))];
      const defCols = LANES.filter((x) => defaults.includes(x));
      const swapRows = c.laneOrder.map((lane) => {
        const list = c.byLane.get(lane) || [];
        return {
          label: lane,
          labelHtml: `${S(lane)}<small class="pv-heat-count">${fmt(list.length)} 局</small>`,
          cells: defCols.map((def) => {
            const n = list.filter((r) => r.heroDefaultLane === def).length;
            return n ? {v: n, text: fmt(n), title: `${lane} 实际分路 · 默认 ${def} · ${fmt(n)} 局`} : {v: null};
          }),
        };
      });
      const swapped = scope.rows.filter((r) => r.heroDefaultLane && r.heroDefaultLane !== r.lane).length;
      setN(scope.rows.length);
      out.push(card('02', '使用节奏与分路类型',
        `切片内 <b>${fmt(cols.length)}</b> ${cols.length && cols[0].weekly ? '周' : '个训练日'}的使用分布，以及 <b>${fmt(swapped)} 局</b>（<b>${P(scope.rows.length ? swapped / scope.rows.length * 100 : null)}</b>）打的不是英雄默认分路。`,
        grid([
          panel(`英雄 × 训练日${cols.length && cols[0].weekly ? '（按周合并）' : ''}`, V.heat({
            rows: heatRows, cols: cols.map((col) => ({label: col.label})),
            aria: '英雄与训练日的使用次数热力网格', empty: '', headW: 150, colW: 52, fit: w(7),
            legend: '<span>少</span><i></i><span>多</span><span style="margin-left:8px">空格 = 那段时间没用</span>',
            fmtV: (v) => `${fmt(v)} 局`,
          }), {span: 7, foot: '列多时横向滚动（行头吸左）；训练日超过 21 天自动按周合并'}),
          panel('实际分路 × 默认分路', V.heat({
            rows: swapRows, cols: defCols.map((x) => ({label: x})),
            aria: '实际分路与英雄默认分路的对应矩阵', empty: '', headW: 118, colW: 52, fit: w(5),
            legend: '<span>格子里是局数</span>', fmtV: (v) => `${fmt(v)} 局`,
          }), {span: 5, foot: '对角线 = 按默认分路打，其余 = 换位'}),
        ]),
        '实际分路取营地面板 battleRecords.position，默认分路取英雄元数据；两边都按局计。'));
    }

    /* 03 常用英雄对比：切片英雄优先，没选就用出场最多的 */
    {
      const bench = c.bench || new Map();
      const hero = scope.hero !== '全部' ? scope.hero : ((pool[0] || c.topHeroes[0] || [])[0] || '');
      const key = f.cmpMetric;
      const list = c.byHero.get(hero) || [];
      const wv = win(list);
      const mine = key === 'games' ? list.length : key === 'winRate' ? wv.rate : mean(list, (r) => r[key]);
      const b = bench.get(hero);
      const theirs = !b ? null : key === 'games' ? b.games : key === 'winRate' ? (b.decided ? b.wins / b.decided * 100 : null) : b.kda;
      const laneOf = list.length ? [...group(list, (r) => r.lane)].sort((x, y) => y[1].length - x[1].length)[0][0] : c.focusLane;
      const laneList = c.byLane.get(laneOf) || [];
      const laneVal = key === 'games' ? laneList.length : key === 'winRate' ? win(laneList).rate : mean(laneList, (r) => r[key]);
      const tools = selBar([
        cardSelect('cmpMetric', '指标', [['winRate', '胜率'], ['games', '场次'], ['kda', 'KDA']], key),
      ]);
      const cols = [
        {label: '本人', value: mine, cls: 'is-mark', note: `${fmt(list.length)} 局`},
        {label: '别的选手用同英雄', value: theirs, cls: 'is-flat', note: b ? `${fmt(b.games)} 局` : '无样本'},
        {label: `${laneOf}整体`, value: laneVal, cls: 'is-na', note: `${fmt(laneList.length)} 局`},
      ];
      const chart = V.columns({
        labels: cols.map((x) => x.label),
        series: [{values: cols.map((x) => x.value), clsAt: cols.map((x) => x.cls),
          texts: cols.map((x) => showVal(key, x.value))}],
        W: w(12), H: 320, padL: 64, padR: 20, maxBarW: 120,
        yMin: key === 'winRate' ? 0 : null, yMax: key === 'winRate' ? 100 : null,
        baseline: key === 'winRate' ? 'zero' : 'auto',
        fmtV: (v) => (fieldKind(key) === 'pct' ? `${fmt(v, 0)}%` : N(v, fieldDigits(key))),
        refs: key === 'winRate' ? [{v: 50, label: '五五开'}] : [],
        aria: `${hero} 的三种口径对比`,
      });
      const gap = isNum(mine) && isNum(theirs) ? mine - theirs : null;
      setN(list.length);
      out.push(card('03', '常用英雄对比',
        `现在比的是 ${heroTag(hero)} 的 <b>${S(fieldLabel(key))}</b>：本人 <b>${showVal(key, mine)}</b>，同英雄其他选手 <b>${showVal(key, theirs)}</b>，差 <b>${fieldKind(key) === 'pct' ? deltaVal(key, gap) : signed(gap, fieldDigits(key))}</b>。`
        + (scope.hero === '全部' ? '（没限定英雄，默认取出场最多的一个；用上方「英雄」切片换）' : ''),
        tools + grid([panel(`${hero} · 本人 / 同英雄其他 / 分路整体`, chart, {
          span: 12,
          right: V.legend([['is-mark', '本人', false], ['is-flat', '别的选手用同英雄', false], ['is-na', `${laneOf}整体`, false]]).replace('pv-legend', 'pv-legend is-inline'),
          foot: `柱上数字 = ${S(fieldLabel(key))}；第三根柱是本人该分路的整体水平，用来判断「是这个英雄打得差，还是这一路本来就这样」`,
        })]),
        '灰柱只统计同一批对局里其他选手用这个英雄的记录（不含本人）；样本不足 3 局只画柱不下结论。'));
    }
    return out;
  }

  /* ══ 模块 3 · 周期与英雄池变动 ═══════════════════════════════════ */
  function buildTrend(c, f) {
    const out = [];
    const rows = c.scope.rows;
    const period = periodWindow(rows, f.period);

    /* 01 英雄池变动：上期 × 本期 的二维漂移图，条目再多也不会挤在一起 */
    {
      const tools = selBar([
        cardSelect('period', '窗口', PERIOD_MODES.map(([key, label]) => [key, label]), f.period),
      ]);
      if (!period) {
        out.push(card('01', '英雄池变动', '这个切片没有可用日期，切不出两期。', tools + V.empty('需要对局日期。'), ''));
      } else {
        const curHeroes = group(period.current, (r) => r.hero || '未知');
        const prevHeroes = group(period.previous, (r) => r.hero || '未知');
        const names = [...new Set([...curHeroes.keys(), ...prevHeroes.keys()])];
        const items = names.map((hero) => ({
          hero,
          from: (prevHeroes.get(hero) || []).length,
          to: (curHeroes.get(hero) || []).length,
        })).filter((x) => x.from || x.to);
        const fresh = items.filter((x) => x.from === 0).sort((a, b) => b.to - a.to);
        const gone = items.filter((x) => x.to === 0).sort((a, b) => b.from - a.from);
        const stay = items.filter((x) => x.from && x.to);
        const top = Math.max(1, ...items.map((x) => Math.max(x.from, x.to)));
        const points = items.map((x) => {
          const diff = x.to - x.from;
          return {
            x: x.from, y: x.to, r: Math.max(1, x.from + x.to), label: x.from + x.to >= 3 ? x.hero : '',
            cls: diff > 0 ? 'is-up' : diff < 0 ? 'is-down' : 'is-flat',
            title: `${x.hero} · 上期 ${fmt(x.from)} 局 → 本期 ${fmt(x.to)} 局（${signed(diff)} 局）`,
          };
        });
        const chart = points.length ? V.scatter({
          points, W: w(12), H: 380, padL: 60, padB: 48,
          xDomain: [-0.4, top + 0.6], yDomain: [-0.4, top + 0.6],
          diagonal: true,
          fmtX: (v) => `${fmt(v, 0)} 局`, fmtY: (v) => `${fmt(v, 0)} 局`,
          xLabel: `上期出场（${period.prevLabel}）`, yLabel: `本期出场（${period.label}）`,
          aria: '英雄出场数的两期漂移散点',
        }) : emptyWith('两期之间没有可比较的英雄',
          '上一个等长窗口里这名选手没有出场记录，切不出「上期 vs 本期」。');
        const chips = (list, cls, emptyText) => list.length
          ? `<div class="pv-strip">${list.slice(0, 12).map((x) => `<span class="pv-strip-item ${cls}">${heroPlain(x.hero)}<b>${fmt(x.from || x.to)} 局</b></span>`).join('')}</div>`
          : `<p class="pv-note">${S(emptyText)}</p>`;
        out.push(card('01', '英雄池变动',
          `两期共出现 <b>${fmt(items.length)} 个英雄</b>；新增 <b>${fmt(fresh.length)} 个</b>、本期未用 <b>${fmt(gone.length)} 个</b>、两期都在用 <b>${fmt(stay.length)} 个</b>。`,
          tools + grid([
            panel('上期 → 本期 漂移', chart, {
              span: 12,
              right: V.legend([['is-up', '用得更多', false], ['is-down', '用得少', false], ['is-flat', '持平', false]]).replace('pv-legend', 'pv-legend is-inline'),
              foot: '对角线 = 两期场次相同；点在对角线上方 = 本期用得更多，下方 = 更少；点大小 = 两期总场次',
            }),
          ])
          + `<div class="pv-split"><div class="pv-block"><h4>本期新增 / 重启</h4>${chips(fresh, 'is-hi', '本期没有新英雄。')}</div>
             <div class="pv-block"><h4>上期用过、本期未用</h4>${chips(gone, 'is-lo', '上期用过的英雄本期都还在用。')}</div></div>`,
          '漂移图只说明使用次数变了，不等于英雄强度或胜率变了。'));
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

  /* ══ 模块 4 · 同分路对位 ═══════════════════════════════════════════ */
  function buildMatchup(c, f) {
    const out = [];
    const scope = c.scope;
    const duels = scope.rows.filter((r) => r.foe);
    const diffOf = (r) => r.gold - (r.foe.gold || 0);

    {
      const avg = mean(duels, diffOf);
      const ahead = duels.filter((r) => diffOf(r) > 0).length;
      const tools = selBar([
        cardSelect('mu', '视角', [['gold', '终局经济差'], ['proxy', '对线期代理']], f.mu),
      ]);
      const proxyTools = f.mu === 'proxy'
        ? selBar([cardSelect('proxy', '代理指标', [['cs', '补刀差'], ['kda', 'KDA 差'], ['participation', '参团率差']], f.proxy)])
        : '';
      let chart = '', chartFoot = '';
      if (f.mu === 'gold') {
        const recent = duels.slice(0, 20).reverse();
        chart = recent.length ? V.columns({
          labels: recent.map((r) => String(r.day || '').slice(5)),
          labelsHtml: recent.map((r) => `<span class="pv-col-face ${r.result === 'win' ? 'is-win' : 'is-loss'}">${portrait(r.hero)}</span>`),
          series: [{
            values: recent.map(diffOf),
            clsAt: recent.map((r) => (diffOf(r) >= 0 ? 'is-up' : 'is-down')),
            texts: recent.map((r) => signed(diffOf(r))),
          }],
          W: w(12), H: 330, padL: 60, padR: 16, maxBarW: 30, showValues: recent.length <= 22,
          fmtV: (v) => signed(v), aria: '逐局终局经济差',
        }) : emptyWith('这个切片里没有可对位的局',
          scope.lane !== '全部'
            ? `切片里的 ${scope.lane} 对局没有同分路对手面板（对手阵容可能没采全）。`
            : '切片里找不到同分路的对手面板（对手阵容可能没采全）。');
        chartFoot = '柱 = 终局经济差（金币）：柱在 0 线之上为领先，之下为落后；柱下头像是本人所用英雄，绿框胜 / 棕框负';
      } else {
        const key = f.proxy;
        const label = {cs: '补刀差', kda: 'KDA 差', participation: '参团率差'}[key];
        const lanes = c.laneOrder.filter((lane) => duels.some((r) => r.lane === lane));
        const vals = lanes.map((lane) => {
          const list = duels.filter((r) => r.lane === lane);
          return mean(list, (r) => (r[key] || 0) - (r.foe[key] || 0));
        });
        chart = V.columns({
          labels: lanes,
          series: [{
            values: vals, clsAt: vals.map((v) => (v >= 0 ? 'is-up' : 'is-down')),
            texts: vals.map((v) => signed(v, key === 'kda' ? 2 : key === 'participation' ? 1 : 0)),
          }],
          W: w(12), H: 320, padL: 60, padR: 16, maxBarW: 64,
          fmtV: (v) => signed(v), aria: `各分路的${label}`,
        });
        chartFoot = `柱 = 各分路的${label}（本人 − 同分路对手）`;
      }
      setN(duels.length);
      out.push(card('01', '同分路对位',
        `<b>${fmt(duels.length)} / ${fmt(scope.rows.length)} 局</b>能找到同分路对手，场均终局经济差 <b>${signed(avg)} 金币</b>，领先 <b>${fmt(ahead)} 局</b>。`,
        stats([
          ['可对位局数', fmt(duels.length), '切片内全部，不止最近 10 局'],
          ['场均经济差', signed(avg), '本人 − 同分路对手（金币）'],
          ['领先局', `${fmt(ahead)} / ${fmt(duels.length)}`, '终局经济为正'],
          ['对位胜率', P(win(duels).rate), '这些局的胜负'],
        ]) + tools + proxyTools
        + grid([panel(f.mu === 'gold' ? '逐局终局经济差 · 最近 20 局' : '对线期代理', chart, {span: 12, foot: chartFoot})]),
        '终局口径只看双方最终经济；对线期 1v1、早期死亡点要回放，代理指标只作对照。'));
    }
    return out;
  }

  /* ══ 模块 5 · 双英雄组合与替代候选 ════════════════════════════════ */
  function buildTeam(c, f) {
    const out = [];
    const scope = c.scope;
    const rows = scope.rows;
    const focusHero = scope.hero !== '全部' ? scope.hero : '';

    /* 01 双英雄组合：本人英雄 × 搭档英雄 的矩阵，组合本来就是二维的 */
    {
      const allPairs = new Map();
      for (const r of rows) {
        if (!r.hero) continue;
        for (const mate of r.mates || []) {
          if (!mate.name || !mate.hero) continue;
          const key = `${r.hero}|${mate.hero}`;
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
      const inside = [...allPairs.values()].sort((a, b) => b.games - a.games);
      const mineRows = [...group(inside, (v) => v.a)].sort((x, y) => y[1].length - x[1].length);
      const shownRows = (focusHero ? mineRows.filter(([mineHero]) => mineHero === focusHero)
        .concat(mineRows.filter(([mineHero]) => mineHero !== focusHero)) : mineRows).slice(0, 6);
      const cols = [...group(inside, (v) => v.b)].sort((x, y) => y[1].length - x[1].length).slice(0, 8).map(([b]) => b);
      const heatRows = shownRows.map(([mineHero]) => ({
        label: mineHero, labelHtml: heroPlain(mineHero),
        cls: focusHero && mineHero !== focusHero ? 'is-dim' : (focusHero ? 'is-self' : ''),
        cells: cols.map((mateHero) => {
          const it = allPairs.get(`${mineHero}|${mateHero}`);
          if (!it) return {v: null};
          const rate = it.decided ? it.wins / it.decided * 100 : null;
          return {
            v: it.games, text: `${fmt(it.games)}`, sub: P(rate),
            title: `${mineHero} + ${mateHero} · ${fmt(it.games)} 局 · 组合胜率 ${P(rate)} · 搭档 ${it.mate}`,
          };
        }),
      }));
      const best = list.slice().sort((a, b) => (b.decided ? b.wins / b.decided : 0) - (a.decided ? a.wins / a.decided : 0) || b.games - a.games)[0];
      setN(allPairs.size);
      out.push(card('01', '双英雄组合',
        `切片内「本人英雄 × 搭档英雄」共 <b>${fmt(allPairs.size)} 组</b>，出场 ≥ 2 局 <b>${fmt(list.length)} 组</b>；最稳的是 ${best ? `<b>${heroPlain(best.a)} + ${heroPlain(best.b)}</b>` : '—'}（${P(best && best.decided ? best.wins / best.decided * 100 : null)}）。`
        + (focusHero ? `当前已聚焦 ${S(focusHero)}。` : '用上方「英雄」切片可聚焦某一位。'),
        grid([
          panel(focusHero ? `${focusHero} 的搭档组合（纵轴第一行）` : '组合矩阵（本人 × 搭档）', V.heat({
            rows: heatRows,
            cols: cols.map((hero) => ({label: hero, iconHtml: heroPlain(hero)})),
            aria: '本人英雄与搭档英雄的组合矩阵', headW: 168, colW: 100, fit: w(12),
            legend: '<span>格子里是组合场次，小字是组合胜率</span><span style="margin-left:8px">空格 = 没同场过 2 局以上</span>',
            fmtV: (v) => `${fmt(v)} 局`,
          }), {span: 12, foot: '横轴 = 搭档英雄，纵轴 = 本人英雄；组合本来就是二维关系，只列前 8 × 6，够看清主力搭配'})]),
        '组合胜率分母只算有胜负的局；1 局组合不进图，样本太薄看不出稳定度。'));
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
        const candidates = Object.entries(c.meta)
          .filter(([name, tag]) => name !== hero && tag.lane && tag.lane === lane)
          .map(([name, tag]) => {
            const shared = (tag.caps || []).filter((x) => caps.includes(x));
            const mine = c.byHero.get(name) || [];
            const wv = win(mine);
            const peer = bench.get(name);
            return {
              name, tag, shared, miss: caps.filter((x) => !(tag.caps || []).includes(x)),
              used: mine.length, rate: wv.rate,
              peerRate: peer && peer.decided ? peer.wins / peer.decided * 100 : null,
              peerGames: peer ? peer.games : 0,
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
            <span class="pv-cand-verdict ${vcls}" role="cell">${S(verdict)}</span>
          </div>`;
        }).join('');
        const headRow = `<div class="pv-cand-row is-head" role="row">
          <span role="columnheader">可替代的英雄</span>
          <span role="columnheader">比 ${S(hero)} 多 / 少的能力</span>
          <span role="columnheader">本人已用</span>
          <span role="columnheader">同英雄其他人</span>
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
              foot: '点英雄名进英雄页查细节；「本人已用」和「同英雄其他人」两列才是决策依据 —— 能力对得上但没打过，只能算考察名单',
            })]),
          '能力标签来自 resources/hero_tags.json，是英雄机制的粗分类；同英雄其他人的样本取同一批对局里别队的记录，不含本人。'));
      }
    }
    return out;
  }

  /* ══ 页面装配 ══════════════════════════════════════════════════════ */
  function render(board, name, detail) {
    cardSeq = 0;
    try {
      foldedCards = new Set(JSON.parse(window.localStorage.getItem('pdx.fold') || '[]'));
    } catch (err) { foldedCards = new Set(); }
    const allRows = (detail && detail.rows) || [];
    const back = st && st.returnTo && st.returnTo.href ? st.returnTo : {href: '#playerarchive', label: '选手档案'};
    if (!allRows.length) {
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">
        <header class="hero-masthead"><div class="page-intro"><div class="pls-head">
          <a class="hero-back" href="${S(back.href)}">← ${S(back.label)}</a>
          <div class="pls-id"><div><h1>未找到这名选手</h1>
            <p>链接里的游戏名在当前营地面板里没有出场记录。</p></div></div></div></div></header>
        <div class="hero-detail-grid"><section class="section"><div class="section-heading"><div>
          <h2>回到选手档案</h2><p>本队全部游戏名都在选手档案页，未认领的会标出来。</p></div></div>
          <p class="pl-note"><a class="pl-link" href="#playerarchive">← 选手档案</a></p></section></div></div>`;
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
    const ctx = {
      board, name, detail, allRows, rows, identity, scope, focusLane,
      desc: [...rows].reverse(),
      laneSamples: detail.laneSamples || {},
      laneDistributions: detail.laneDistributions || laneDistOf(allRows),
      meta: detail.heroMeta || {}, opponents: detail.opponents || [],
      bench: heroBench(board, name),
      byLane, laneOrder, mainLane, byHero, topHeroes,
    };
    rangeLabel = scopeText(scope);
    const f = readFilters(ctx);

    /* ── 头部：身份 + 全量 KPI（切片统计在切片条里，两者不混）────────── */
    const total = win(allRows);
    const mainList = group(allRows, (r) => r.lane).get(mainLane) || [];
    const allLaneCount = new Set(allRows.map((r) => r.lane).filter(Boolean)).size;
    const recent10 = allRows.slice(-10);
    const baseRatings = allRows.slice(0, Math.max(0, allRows.length - 10)).map((r) => r.rating).filter(isNum);
    const kpiHtml = `<div class="hero-kpi pl-kpi" role="group" aria-label="关键指标">${[
      ['出场', `${fmt(allRows.length)} 局`, `${fmt(total.wins)} 胜 ${fmt(total.decided - total.wins)} 负`],
      ['胜率', P(total.rate), `${fmt(total.wins)} / ${fmt(total.decided)} 有胜负`],
      ['主位置', S(mainLane), `${fmt(mainList.length)} 局 · 胜率 ${P(win(mainList).rate)}`],
      ['副位置覆盖', `${fmt(allLaneCount - 1)} 个位置`, `${fmt(allRows.length - mainList.length)} 局`],
      ['英雄池', `${fmt(new Set(allRows.map((r) => r.hero).filter(Boolean)).size)} 个英雄`,
        `覆盖 ${fmt(new Set(allRows.map((r) => r.heroType).filter(Boolean)).size)} 类职业`],
      ['近 10 局评分', N(mean(recent10, (r) => r.rating), 2), baseRatings.length ? `此前基线 ${N(mean(baseRatings), 2)}` : '基线样本不足'],
      ['训练日', `${fmt(daysOf(allRows).length)} 个`, rangeText(daysOf(allRows))],
    ].map(([label, value, noteText]) => `<div class="hero-kpi-cell"><span>${S(label)}</span><strong>${value}</strong><p>${S(noteText)}</p></div>`).join('')}</div>`;

    const allPlayers = ((board && board.players) || []).filter((p) => p && p.name && (p.games || 0) >= 1);
    const regulars = allPlayers.filter((p) => p.side === 'own' && (p.games || 0) >= 3);
    const ownSide = allPlayers.filter((p) => p.side === 'own');
    const pick = [regulars, ownSide, allPlayers].find((list) => list.length >= 2) || allPlayers;
    const roster = pick
      .map((p) => [p.name, p.games || 0, p.bound ? 1 : 0])
      .sort((a, b) => b[2] - a[2] || b[1] - a[1]);
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
          <div><h1>${S(name)}</h1><p>${S(mainLane)} · ${identity.side === 'own' ? '本队侧' : '对手侧'} · ${identity.bound ? '已认领' : '待认领昵称'} · ${fmt(allLaneCount)} 个实际分路 · ${fmt(allRows.length)} 局</p></div>
        </div>
      </div>
      <div class="intro-actions">${roster.length > 1 ? `<label class="pv-sel is-head"><span class="pv-sel-label">换选手</span>
          <span class="pv-sel-box"><select data-pl-switch-player aria-label="切换到其他选手">
            ${roster.map(([who, games]) => `<option value="${S(who)}"${who === name ? ' selected' : ''}>${S(who)} · ${fmt(games)} 局</option>`).join('')}
          </select><i class="pv-sel-caret" aria-hidden="true"></i></span></label>` : ''}<span class="pv-pos" title="按出场数排序的位置，可用键盘 ← → 切换">第 ${fmt(Math.max(1, roster.findIndex(([who]) => who === name) + 1))} / ${fmt(roster.length)} 位</span>${identity.bound ? '' : `<button class="control" data-pl-name="${S(name)}">命名并归队</button>`}${compareCount >= 2
          ? `<a class="control is-on" href="#playercompare">去看对比（${compareCount}/2）→</a>`
          : `<button class="control${inCompare ? ' is-on' : ''}" data-pl-pick-b="${S(name)}">${inCompare ? `已放入对比（${compareCount}/2）` : '放入对比'}</button>`}<button class="control" data-action="refresh">刷新数据</button></div>
    </div>${kpiHtml}</header>`;

    const briefHtml = `<div class="hero-brief">全量 <b>${fmt(allRows.length)} 局</b>、${fmt(total.wins)} 胜 ${fmt(total.decided - total.wins)} 负（胜率 <b>${P(total.rate)}</b>）。主位置 <b>${S(mainLane)} ${fmt(mainList.length)} 局</b>；下面的分析只看上方切片里的 <b>${fmt(rows.length)} 局</b>，切一下就能把「一整个赛季」收成「这几天的这一路」。所有分位、排名都按各自实际分路计算，不给统一综合分。</div>`;

    const modules = [
      ['portrait', '选手综合画像', '位置能力、指标越线矩阵、同位置对标', (c, ff) => buildPortrait(c, ff)],
      ['heroes', '英雄池', '使用图谱、使用节奏与同英雄对照', (c, ff) => buildHeroes(c, ff)],
      ['trend', '英雄池变动', '上期 × 本期出场漂移与进出池', (c, ff) => buildTrend(c, ff)],
      ['matchup', '同分路对位', '逐局终局经济差与对线期代理', (c, ff) => buildMatchup(c, ff)],
      ['team', '组合与替代', '双英雄组合矩阵与英雄替代候选', (c, ff) => buildTeam(c, ff)],
    ];
    /* 吸顶的只有切片条：模块导航跟着页面滚走（它是「跳到哪一节」的入口，
       读完一段不会再回头点）。吸顶高度按顶部导航实测，别把切片条塞到它后面。 */
    const dock = `<nav class="hero-anchor-nav" aria-label="模块快速导航">
        ${modules.map(([, label], i) => `<button type="button" data-hero-scroll="${i}">${S(label)}</button>`).join('')}
        <span class="pv-keyhint" aria-hidden="true"><kbd>←</kbd><kbd>→</kbd>换选手</span>
        <button type="button" class="pv-reset" data-pdx-print title="打印整页（可在对话框里存成 PDF）">整页 PDF</button>
        <button type="button" class="pv-reset" data-pdx-reset title="把所有切片与卡片筛选恢复默认">重置全部</button>
      </nav>
      ${scopeBar(ctx)}`;

    /* 切片命中 0 局时不再画一堆空图：直接给一张能让教练退回上一步的卡 */
    if (!rows.length) {
      return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${briefHtml}${dock}
        <div class="hero-detail-grid"><section class="section" data-pdx-module="空切片" data-pdx-key="empty">
          <div class="pdx-cards">${card('00', '这个切片里没有对局', '范围、分路、英雄、对手、结果五个条件叠在一起，把数据筛空了。',
            emptyWith('当前切片 0 局', `${scopeText(scope)} —— 换个范围或去掉一个条件就能看到数据。`),
            '切片条上的「清除切片」会把这五个条件一起恢复成全量。')}</div>
        </section></div>
        <button type="button" class="pv-top" data-pdx-top aria-label="回到顶部" title="回到顶部">↑</button></div>`;
    }

    const sections = modules.map(([key, label, sub, build]) =>
      block(label, sub, `<div class="pdx-cards">${build(ctx, f).join('')}</div>`, '', `data-pdx-module="${S(label)}" data-pdx-key="${S(key)}"`)).join('');
    const profileRow = (st.board && (st.board.players || []).find((p) => p.name === name))
      || {name, nicknames: (identity && identity.nicknames) || []};
    const profileBlock = profile ? profile.summary(profileRow) : '';
    return `<div class="page hero-detail-page page-wide" data-pl-page="solo">${head}${profileBlock}${briefHtml}${dock}<div class="hero-detail-grid">${sections}</div>
      <button type="button" class="pv-top" data-pdx-top aria-label="回到顶部" title="回到顶部">↑</button></div>`;
  }

  /* ── 卡片级筛选：只留不跨卡的维度，分路/英雄/时间都归切片条 ────── */
  function readFilters(c) {
    const ui = stateUI();
    const f = {
      anomalyDir: one(['all', 'hi', 'lo'], ui.anomalyDir, 'all'),
      bench: one(['rating', 'winRate', 'kda', 'hdpm', 'participation'], ui.bench, 'rating'),
      cmpMetric: one(['winRate', 'games', 'kda'], ui.cmpMetric, 'winRate'),
      period: one(PERIOD_MODES.map((m) => m[0]), ui.period, 'd3'),
      mu: one(['gold', 'proxy'], ui.mu, 'gold'),
      proxy: one(['cs', 'kda', 'participation'], ui.proxy, 'cs'),
    };
    Object.assign(ui, f);
    return f;
  }

  return {render};
}
