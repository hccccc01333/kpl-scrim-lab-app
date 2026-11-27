/* 跨局分析 · 游戏数据分析内核（2026-11-15 重构）
 *
 * 输入：/api/cross/vectors 的全量轻量向量（一局一行）。
 * 输出：按赛训问法组织好的结构化结论，不做 DOM、不读时间系统、不补 0。
 *
 * 组织方式（游戏分析师口径）：
 *   1. 样本与覆盖：先说明这批局能回答什么、不能回答什么；
 *   2. 战绩与走势：胜率区间、经济差、前后半变化；
 *   3. 赢法画像：赢局/输局在游戏维度上的差异，按影响排序；
 *   4. 稳定性：领先被翻、落后翻盘、超长局、崩盘局；
 *   5. 对线、前期、经济路径、资源兑现、团战；
 *   6. BP 与阵容：五路签名、功能标签、英雄池、组合、蓝红方、ban；
 *   7. 对手习惯与对位账本。
 *
 * 统计只负责“别被小样本骗”：比率给 Wilson 区间，数值给典型值与 P10–P90，
 * 组间比较用 Cliff's δ / 比率差，方向型结论做前后半复现。所有结论都带 n。
 */

export const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
export const PHASES = [
  { key: 'early', label: '0–4 对线期' },
  { key: 'mid', label: '4–10 发育期' },
  { key: 'late', label: '10 分钟后' },
];
const PHASE_CHECKPOINTS = [0, 5, 10, 15, 20, 25];
/* 10 分钟金币门槛（赛训组 2026-11 口径）：从单一 1,000 改为两档——
   ≥3,000「明显」优势/劣势、≥5,000「巨大」优势/劣势。
   两档同时计算、同时展示，不互相替代；顶层 throw/comeback 仍取 3,000 档，
   旧调用方（逐局 drilldown、翻盘局分布图）不用改结构也能跟着新门槛走。
   注意：analysis_period.LEAD_AT10 是「周期简报」的另一套口径，不是这里的来源。 */
export const LEAD_TIERS = [
  { threshold: 3000, word: '明显' },
  { threshold: 5000, word: '巨大' },
];
export const BIG_LEAD_AT10 = LEAD_TIERS[0].threshold;
export const HUGE_LEAD_AT10 = LEAD_TIERS[1].threshold;

/* ── 基础统计 ─────────────────────────────────────────────────── */
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const vals = (a) => (a || []).filter(num);
const sum = (a) => (a || []).reduce((s, x) => s + (num(x) ? x : 0), 0);
const mean = (a) => { const v = vals(a); return v.length ? sum(v) / v.length : null; };
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const byOrder = (a, b) => String(a.order || '').localeCompare(String(b.order || '')) || String(a.key || '').localeCompare(String(b.key || ''));

function quantile(a, p) {
  const s = vals(a).slice().sort((x, y) => x - y);
  if (!s.length) return null;
  const i = (s.length - 1) * clamp(p, 0, 1);
  const lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}
const median = (a) => quantile(a, 0.5);
const sd = (a) => {
  const v = vals(a);
  if (v.length < 2) return 0;
  const m = mean(v);
  return Math.sqrt(sum(v.map((x) => (x - m) ** 2)) / (v.length - 1));
};


function cliffs(a, b) {
  const A = vals(a), B = vals(b);
  if (!A.length || !B.length) return null;
  const bs = B.slice().sort((x, y) => x - y);
  let gt = 0, lt = 0;
  for (const x of A) {
    let lo = 0, hi = bs.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (bs[mid] < x) lo = mid + 1; else hi = mid;
    }
    gt += lo;
    lt += bs.length - lo;
  }
  return (gt - lt) / (A.length * B.length);
}

function wilson(k, n, z = 1.96) {
  if (!n) return null;
  const p = k / n;
  const d = 1 + z * z / n;
  const c = (p + z * z / (2 * n)) / d;
  const h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

function rateOf(k, n) {
  if (!n) return { k: 0, n: 0, value: null, ci: null };
  return { k, n, value: k / n, ci: wilson(k, n) };
}

/* 经验贝叶斯收缩：小样本胜率向整体基线回归，避免 1 局 1 胜 = 100%。 */
function shrink(k, n, baseline, prior = 8) {
  if (!n) return null;
  const base = num(baseline) ? baseline : 0.5;
  return (k + prior * base) / (n + prior);
}

function halves(rows) {
  const list = rows.slice().sort(byOrder);
  const cut = Math.floor(list.length / 2);
  return [list.slice(0, cut), list.slice(cut)];
}

function signDirection(v) {
  if (!num(v) || Math.abs(v) < 1e-9) return 0;
  return v > 0 ? 1 : -1;
}

/* 同一指标在前后半是否同向：方向型结论的最低复现门槛。 */
function reproduce(rows, fn) {
  const [early, late] = halves(rows);
  if (early.length < 3 || late.length < 3) return null;
  const a = fn(early), b = fn(late);
  if (!num(a) || !num(b)) return null;
  return signDirection(a) === signDirection(b) && signDirection(a) !== 0;
}

/* ── 格式化（页面与内核共用，避免两套口径）───────────────────── */
const minus = (v) => String(v).replace(/^-/, '−');
const group = (v) => Math.abs(Math.round(v)).toLocaleString('zh-CN');
const signed = (v, digits = 0) => {
  if (!num(v)) return '—';
  const abs = digits ? Math.abs(v).toFixed(digits) : group(v);
  return `${v < 0 ? '−' : '+'}${abs}`;
};
const count = (v) => (!num(v) ? '—' : Math.round(v).toLocaleString('zh-CN'));
const fixed = (v, digits = 1) => (!num(v) ? '—' : minus(v.toFixed(digits)));
const pct = (v, digits = 0) => (!num(v) ? '—' : `${(v * 100).toFixed(digits)}%`);
const duration = (sec) => {
  if (!num(sec)) return '—';
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
const unitText = (v, unit) => {
  if (!num(v)) return '—';
  if (unit === 'rate') return pct(v, 0);
  if (unit === 'pct') return pct(v, 0);
  if (unit === 'sec') return duration(v);
  if (unit === 'gold') return `${signed(v)} 金币`;
  if (unit === 'perMin') return `${signed(v)} 金币/分`;
  if (unit === 'kill') return `${signed(v)} 个`;
  if (unit === 'tower') return `${signed(v)} 座`;
  if (unit === 'count') return `${fixed(v)} 次`;
  if (unit === 'fight') return `${fixed(v)} 波`;
  return fixed(v);
};
const rateText = (r) => (r && r.n ? `${r.k}/${r.n}（${pct(r.value)}）` : '样本不足');

export const fmt = { num, vals, sum, mean, median, quantile, sd, cliffs, wilson, shrink, signed, count, fixed, pct, duration, unitText, rateText };

/* ── 向量预处理：所有分析只读这里的派生量 ───────────────────── */
function prepare(vectors) {
  return (vectors || []).filter((v) => v && v.key).map((v) => {
    const camp = v.camp === 'red' ? 'red' : 'blue';
    const result = v.result === 'win' || v.result === 'loss' ? v.result : '';
    const g = Array.isArray(v.g) ? v.g.map((x) => (num(x) ? x : null)) : [];
    const pl = Array.isArray(v.pl) ? v.pl.filter((p) => p && p.camp) : [];
    const ownPlayers = pl.filter((p) => p.camp === camp);
    return {
      ...v,
      camp,
      result,
      decided: !!result,
      at10: num(v.at10) ? v.at10 : null,
      final: num(v.finalDiff) ? v.finalDiff : null,
      at4: num(v.at4) ? v.at4 : null,
      g,
      w: Array.isArray(v.w) ? v.w : [],
      s: Array.isArray(v.s) ? v.s : [],
      seg: v.seg && typeof v.seg === 'object' ? v.seg : {},
      obj: v.obj && typeof v.obj === 'object' ? v.obj : {},
      death: v.death && typeof v.death === 'object' ? v.death : {},
      fight: v.fight && typeof v.fight === 'object' ? v.fight : {},
      buff: v.buff && typeof v.buff === 'object' ? v.buff : {},
      cut: v.cut && typeof v.cut === 'object' ? v.cut : {},
      fk: v.fk && typeof v.fk === 'object' ? v.fk : null,
      first: v.first && typeof v.first === 'object' ? v.first : null,
      objAt10: v.objAt10 && typeof v.objAt10 === 'object' ? v.objAt10 : null,
      jungle: v.jungle && typeof v.jungle === 'object' ? v.jungle : {},
      lanes: v.lanes && typeof v.lanes === 'object' ? v.lanes : {},
      heroes: Array.isArray(v.heroes) ? v.heroes.filter(Boolean) : [],
      heroesFoe: Array.isArray(v.heroesFoe) ? v.heroesFoe.filter(Boolean) : [],
      bans: Array.isArray(v.bans) ? v.bans.filter(Boolean) : [],
      bansOwn: Array.isArray(v.bansOwn) ? v.bansOwn.filter(Boolean) : null,
      bansFoe: Array.isArray(v.bansFoe) ? v.bansFoe.filter(Boolean) : null,
      compOwn: Array.isArray(v.compOwn) ? v.compOwn.filter(Boolean) : null,
      compFoe: Array.isArray(v.compFoe) ? v.compFoe.filter(Boolean) : null,
      pl: ownPlayers,
      plAll: pl,
      km: num(v.killsOwn) && num(v.killsFoe) ? v.killsOwn - v.killsFoe : null,
      order: v.order || `${v.date || ''} ${v.clock || ''}`,
    };
  });
}

/* ── 单局派生量 ───────────────────────────────────────────────── */
const laneValue = (r, lane, key) => {
  const cell = r.lanes[lane];
  return cell && num(cell[key]) ? cell[key] : null;
};
const dragonRate = (r) => {
  const own = r.obj.dragonOwn, foe = r.obj.dragonFoe;
  if (!num(own) || !num(foe) || own + foe <= 0) return null;
  return own / (own + foe);
};
const towerDiff = (r) => {
  const own = r.obj.towerOwn, foe = r.obj.towerFoe;
  return num(own) && num(foe) ? own - foe : null;
};
const fightRate = (r) => {
  if (num(r.fight.decidedN) && r.fight.decidedN > 0 && num(r.fight.decidedWin)) {
    return r.fight.decidedWin / r.fight.decidedN;
  }
  // 兼容旧服务端：没有 decidedN 时退回总团战，但页面会标注分母。
  if (num(r.fight.n) && r.fight.n > 0 && num(r.fight.win)) return r.fight.win / r.fight.n;
  return null;
};
const firstSide = (r, key) => {
  const side = r.first && r.first[`${key}Side`];
  return side === 'own' ? 'own' : side === 'foe' ? 'foe' : null;
};
const firstRate = (r, key) => {
  const side = firstSide(r, key);
  return side == null ? null : side === 'own' ? 1 : 0;
};
const ownPlayerAt = (r, pos) => r.pl.find((p) => p.pos === pos) || null;

/* ── 覆盖与口径 ───────────────────────────────────────────────── */
function coverageOf(rows) {
  const dates = rows.map((r) => String(r.date || '')).filter(Boolean).sort();
  const withAt10 = rows.filter((r) => num(r.at10)).length;
  const withEcon = rows.filter((r) => num(r.ecoPoints) && r.ecoPoints > 0).length;
  const withReplay = rows.filter((r) => r.hasReplay).length;
  const withLineup = rows.filter((r) => r.heroes.length >= 5).length;
  const withPlayers = rows.filter((r) => r.plAll.length >= 10).length;
  const withComp = rows.filter((r) => Array.isArray(r.compOwn) && r.compOwn.length).length;
  const withFirst = rows.filter((r) => r.first && (r.first.bloodT != null || r.first.dragonT != null || r.first.towerT != null)).length;
  const withObj10 = rows.filter((r) => r.objAt10).length;
  const withBansOwn = rows.filter((r) => Array.isArray(r.bansOwn)).length;
  const series = new Set(rows.map((r) => r.seriesId).filter(Boolean)).size;
  const withSeries = rows.filter((r) => r.seriesId).length;
  const opponents = new Set(rows.map((r) => String(r.opponent || '').trim()).filter(Boolean)).size;
  const unknownOpp = rows.filter((r) => !String(r.opponent || '').trim()).length;
  const versions = new Set(rows.map((r) => String(r.version || '').trim()).filter(Boolean)).size;
  const sessions = new Set(rows.map((r) => String(r.session || '').trim()).filter(Boolean)).size;
  const decided = rows.filter((r) => r.decided).length;
  const caveats = [];
  if (!rows.length) caveats.push('当前范围没有对局，先放宽时间或赛制。');
  else if (rows.length < 10) caveats.push(`当前只有 ${rows.length} 局，所有结论只作观察，不据此定训练方向。`);
  if (rows.length && withEcon / rows.length < 0.8) {
    caveats.push(`经济过程覆盖 ${withEcon}/${rows.length} 局；曲线与 10 分钟差只按可读局计算。`);
  }
  if (rows.length && versions < 2) caveats.push('版本字段没有形成可比较的分层，本次不做版本对比。');
  if (rows.length && sessions < 2) caveats.push('训练组标注少，本次不做训练组分层。');
  if (!withSeries) caveats.push('当前范围没有编入系列赛的局；系列赛页签为空，编组后才按 BO 连续对局分析。');
  else if (withSeries / rows.length < 0.3) {
    caveats.push(`仅 ${withSeries} 局编入系列赛（${series} 组）；系列赛页签只代表已编组部分。`);
  }
  if (withComp && withComp / rows.length < 0.8) caveats.push('阵容功能标签只覆盖部分对局，BP 页签按可读局计算。');
  if (withFirst && withFirst / rows.length < 0.8) caveats.push('一血/一龙/一塔需要回放，只有部分对局参与前期节奏。');
  if (unknownOpp) caveats.push(`${unknownOpp} 局对手未标注，对手账本不计入这些局。`);
  return {
    n: rows.length, decided, dates: { from: dates[0] || '', to: dates[dates.length - 1] || '' },
    opponents, unknownOpp, series, withSeries, versions, sessions,
    econ: withEcon, at10: withAt10, replay: withReplay, lineup: withLineup,
    players: withPlayers, comp: withComp, first: withFirst, obj10: withObj10, bansOwn: withBansOwn,
    caveats,
  };
}

/* ── 1. 战绩与走势 ────────────────────────────────────────────── */
function recordOf(rows) {
  const decided = rows.filter((r) => r.decided);
  const wins = decided.filter((r) => r.result === 'win').length;
  const losses = decided.length - wins;
  const rate = decided.length ? wins / decided.length : null;
  const at10 = vals(rows.map((r) => r.at10));
  const final = vals(rows.map((r) => r.final));
  const dur = vals(rows.map((r) => r.duration));
  const km = vals(rows.map((r) => r.km));
  return {
    n: rows.length, decided: decided.length, wins, losses, rate,
    ci: decided.length ? wilson(wins, decided.length) : null,
    at10: { n: at10.length, med: median(at10), p25: quantile(at10, 0.25), p75: quantile(at10, 0.75) },
    final: { n: final.length, med: median(final), p25: quantile(final, 0.25), p75: quantile(final, 0.75) },
    duration: { n: dur.length, avg: mean(dur), med: median(dur) },
    km: { n: km.length, avg: mean(km), med: median(km) },
    span: (() => {
      const dates = rows.map((r) => String(r.date || '')).filter(Boolean).sort();
      if (!dates.length) return '';
      return dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} → ${dates[dates.length - 1]}`;
    })(),
  };
}

function trendOf(rows) {
  const ordered = rows.slice().sort(byOrder);
  const points = ordered.map((r, i) => ({
    i, key: r.key, date: r.date || '', clock: r.clock || '', opponent: r.opponent || '',
    result: r.result || '', at10: r.at10, final: r.final, duration: r.duration || null,
  }));
  const winAt10 = (list) => {
    const arr = vals(list.map((r) => r.at10));
    return arr.length ? median(arr) : null;
  };
  const winRate = (list) => {
    const d = list.filter((r) => r.decided);
    return d.length ? d.filter((r) => r.result === 'win').length / d.length : null;
  };
  const [early, late] = halves(ordered.filter((r) => r.decided));
  const earlyAt10 = winAt10(early), lateAt10 = winAt10(late);
  const earlyRate = winRate(early), lateRate = winRate(late);
  const at10Delta = num(earlyAt10) && num(lateAt10) ? lateAt10 - earlyAt10 : null;
  const rateDelta = num(earlyRate) && num(lateRate) ? lateRate - earlyRate : null;
  const direction = !num(at10Delta) ? null
    : Math.abs(at10Delta) < 300 ? 'flat' : at10Delta > 0 ? 'up' : 'down';
  const conflict = num(at10Delta) && num(rateDelta)
    && signDirection(at10Delta) !== 0 && signDirection(rateDelta) !== 0
    && signDirection(at10Delta) !== signDirection(rateDelta);
  const window = Math.min(10, Math.max(3, Math.floor(points.length / 4)));
  const rolling = points.map((p, i) => {
    const from = Math.max(0, i - window + 1);
    const slice = points.slice(from, i + 1);
    const arr = vals(slice.map((x) => x.at10));
    const dec = slice.filter((x) => x.result === 'win' || x.result === 'loss');
    return {
      i: p.i,
      at10: arr.length ? median(arr) : null,
      winRate: dec.length >= 3 ? dec.filter((x) => x.result === 'win').length / dec.length : null,
    };
  });
  return {
    points, rolling, window,
    early: { n: early.length, at10: earlyAt10, rate: earlyRate, span: [early[0]?.date || '', early[early.length - 1]?.date || ''] },
    late: { n: late.length, at10: lateAt10, rate: lateRate, span: [late[0]?.date || '', late[late.length - 1]?.date || ''] },
    at10Delta, rateDelta, direction, conflict,
  };
}

/* ── 2. 赢法画像：赢局/输局在游戏维度上的差异 ────────────────── */
const DRIVER_METRICS = [
  { key: 'at10', label: '10 分钟经济差', unit: 'gold', kind: 'num', get: (r) => r.at10, better: 'high' },
  { key: 'final', label: '终局经济差', unit: 'gold', kind: 'num', get: (r) => r.final, better: 'high' },
  { key: 'km', label: '人头差', unit: 'kill', kind: 'num', get: (r) => r.km, better: 'high' },
  { key: 'dragon', label: '控龙率', unit: 'rate', kind: 'rate', get: dragonRate, better: 'high' },
  { key: 'tower', label: '推塔差', unit: 'tower', kind: 'num', get: towerDiff, better: 'high' },
  { key: 'deaths', label: '全队场均死亡', unit: 'count', kind: 'num', get: (r) => (num(r.death.own) ? r.death.own : null), better: 'low' },
  { key: 'fight', label: '团战胜率', unit: 'rate', kind: 'rate', get: fightRate, better: 'high' },
  { key: 'firstBlood', label: '一血率', unit: 'rate', kind: 'rate', get: (r) => firstRate(r, 'blood'), better: 'high' },
  { key: 'firstDragon', label: '一龙率', unit: 'rate', kind: 'rate', get: (r) => firstRate(r, 'dragon'), better: 'high' },
  { key: 'firstTower', label: '一塔率', unit: 'rate', kind: 'rate', get: (r) => firstRate(r, 'tower'), better: 'high' },
  { key: 'duration', label: '时长', unit: 'sec', kind: 'num', get: (r) => (num(r.duration) ? r.duration : null), better: 'neutral' },
  { key: 'jungle', label: '打野过河占比', unit: 'pct', kind: 'num', get: (r) => (num(r.jungle.crossShare) ? r.jungle.crossShare : null), better: 'high' },
  { key: 'cut', label: '场均切 C', unit: 'count', kind: 'num', get: (r) => (num(r.cut.n) ? r.cut.n : null), better: 'high' },
  ...LANES.map((lane) => ({
    key: `lane:${lane}`, label: `${lane}分均经济差`, unit: 'perMin', kind: 'num',
    get: (r) => laneValue(r, lane, 'gold'), better: 'high',
  })),
];

function driversOf(rows) {
  const win = rows.filter((r) => r.result === 'win');
  const loss = rows.filter((r) => r.result === 'loss');
  const list = DRIVER_METRICS.map((m) => {
    const wv = vals(win.map(m.get));
    const lv = vals(loss.map(m.get));
    if (!wv.length || !lv.length) return null;
    const wMed = median(wv), lMed = median(lv);
    const effect = m.kind === 'rate'
      ? (mean(wv) - mean(lv))
      : cliffs(wv, lv);
    const reliability = Math.min(1, Math.min(wv.length, lv.length) / 8);
    const impact = Math.abs(effect || 0) * reliability;
    const repro = reproduce(rows.filter((r) => r.decided && num(m.get(r))), (part) => {
      const a = vals(part.filter((r) => r.result === 'win').map(m.get));
      const b = vals(part.filter((r) => r.result === 'loss').map(m.get));
      if (!a.length || !b.length) return null;
      return m.kind === 'rate' ? mean(a) - mean(b) : cliffs(a, b);
    });
    return {
      ...m, winN: wv.length, lossN: lv.length, n: wv.length + lv.length,
      win: m.kind === 'rate' ? mean(wv) : wMed,
      loss: m.kind === 'rate' ? mean(lv) : lMed,
      winText: unitText(m.kind === 'rate' ? mean(wv) : wMed, m.unit),
      lossText: unitText(m.kind === 'rate' ? mean(lv) : lMed, m.unit),
      effect, impact, repro,
    };
  }).filter(Boolean).filter((m) => Math.abs(m.effect || 0) > 1e-9);
  list.sort((a, b) => b.impact - a.impact);
  return list;
}

function winConditionOf(drivers) {
  const strong = drivers.filter((d) => d.n >= 6 && Math.abs(d.effect) > 0.08);
  if (!strong.length) return null;
  const top = strong.slice(0, 3);
  const labels = top.map((d) => d.label);
  const first = top[0];
  const direction = first.better === 'low'
    ? (first.effect < 0 ? '赢的局更低' : '赢的局反而更高')
    : (first.effect > 0 ? '赢的局更高' : '赢的局反而更低');
  return {
    labels,
    text: `赢输差得最明显的是${labels[0]}、${labels[1] || labels[0]}、${labels[2] || labels[1] || labels[0]}；${first.label}${direction}。`,
    strongest: first,
  };
}

/* ── 3. 稳定性与风险 ──────────────────────────────────────────── */
/* 单档风险账本：3,000 / 5,000 各算一份，命中数与分母必须同档，不能串档相除。 */
function riskTierOf(rows, threshold) {
  const withAt10 = rows.filter((r) => num(r.at10));
  const decided = rows.filter((r) => r.decided);
  const withFinal = decided.filter((r) => num(r.final));
  const lead = withAt10.filter((r) => r.at10 > 0);
  const bigLead = withAt10.filter((r) => r.at10 >= threshold);
  const behind = withAt10.filter((r) => r.at10 < 0);
  const bigBehind = withAt10.filter((r) => r.at10 <= -threshold);
  const leadWin = lead.filter((r) => r.result === 'win').length;
  const throwN = bigLead.filter((r) => r.result === 'loss').length;
  const comebackN = bigBehind.filter((r) => r.result === 'win').length;
  const longGames = rows.filter((r) => num(r.duration) && r.duration >= 1200).length;
  const withDur = rows.filter((r) => num(r.duration)).length;
  const blowLoss = withFinal.filter((r) => r.final <= -10000).length;
  const blowWin = withFinal.filter((r) => r.final >= 10000).length;
  const shrink = bigLead.filter((r) => num(r.final) && r.final < r.at10).length;
  return {
    threshold,
    lead: rateOf(leadWin, lead.length),
    throw: rateOf(throwN, bigLead.length),
    comeback: rateOf(comebackN, bigBehind.length),
    behind: rateOf(behind.length, withAt10.length),
    shrink: rateOf(shrink, bigLead.length),
    long: rateOf(longGames, withDur),
    blowLoss: rateOf(blowLoss, withFinal.length),
    blowWin: rateOf(blowWin, withFinal.length),
    /* 每个计数都带上「是哪几局」：页面上的「看这 11 局」直接用这份 key 列表。 */
    keys: {
      lead: lead.map((r) => r.key),
      leadWin: lead.filter((r) => r.result === 'win').map((r) => r.key),
      bigLead: bigLead.map((r) => r.key),
      throw: bigLead.filter((r) => r.result === 'loss').map((r) => r.key),
      behind: behind.map((r) => r.key),
      comeback: bigBehind.filter((r) => r.result === 'win').map((r) => r.key),
      shrink: bigLead.filter((r) => num(r.final) && r.final < r.at10).map((r) => r.key),
      blowLoss: withFinal.filter((r) => r.final <= -10000).map((r) => r.key),
      blowWin: withFinal.filter((r) => r.final >= 10000).map((r) => r.key),
    },
  };
}

function riskOf(rows) {
  const base = riskTierOf(rows, BIG_LEAD_AT10);
  const tiers = {};
  for (const { threshold } of LEAD_TIERS) tiers[threshold] = riskTierOf(rows, threshold);
  const dist = (key) => {
    const a = vals(rows.map((r) => r[key]));
    return { n: a.length, p10: quantile(a, 0.1), p25: quantile(a, 0.25), p50: median(a), p75: quantile(a, 0.75), p90: quantile(a, 0.9) };
  };
  return {
    ...base, tiers,
    at10: dist('at10'), final: dist('final'), duration: dist('duration'),
  };
}

/* ── 4. 五路对位与选手执行 ────────────────────────────────────── */
function laneOf(rows) {
  const lanes = LANES.map((lane) => {
    const gold = vals(rows.map((r) => laneValue(r, lane, 'gold')));
    const damage = vals(rows.map((r) => laneValue(r, lane, 'damage')));
    const taken = vals(rows.map((r) => laneValue(r, lane, 'taken')));
    const ahead = rows.filter((r) => num(laneValue(r, lane, 'gold')) && laneValue(r, lane, 'gold') > 0);
    const behind = rows.filter((r) => num(laneValue(r, lane, 'gold')) && laneValue(r, lane, 'gold') < 0);
    const winAhead = ahead.filter((r) => r.result === 'win').length;
    const winBehind = behind.filter((r) => r.result === 'win').length;
    return {
      lane, n: gold.length, med: median(gold), p10: quantile(gold, 0.1), p90: quantile(gold, 0.9),
      damage: median(damage), taken: median(taken),
      ahead: ahead.length, aheadRate: gold.length ? ahead.length / gold.length : null,
      winAhead: rateOf(winAhead, ahead.length), winBehind: rateOf(winBehind, behind.length),
    };
  }).filter((x) => x.n);
  const best = lanes.slice().sort((a, b) => (b.med || 0) - (a.med || 0))[0] || null;
  const floor = lanes.slice().sort((a, b) => (a.p10 || 0) - (b.p10 || 0))[0] || null;
  const mostAhead = lanes.slice().sort((a, b) => (b.aheadRate || 0) - (a.aheadRate || 0))[0] || null;
  return { lanes, best, floor, mostAhead };
}

function playerExecutionOf(rows) {
  const map = new Map();
  for (const r of rows) {
    for (const p of r.pl) {
      if (!p.name || !p.pos) continue;
      const key = `${p.name}|${p.pos}`;
      const e = map.get(key) || { name: p.name, pos: p.pos, games: 0, gpm: [], dpm: [], part: [], d: [] };
      e.games += 1;
      if (num(p.gpm)) e.gpm.push(p.gpm);
      if (num(p.dpm)) e.dpm.push(p.dpm);
      // 营地参团率给的是 0–100；统一折成 0–1，页面只按一种刻度显示。
      if (num(p.part)) e.part.push(p.part > 1.5 ? p.part / 100 : p.part);
      if (num(p.d)) e.d.push(p.d);
      map.set(key, e);
    }
  }
  return [...map.values()].filter((e) => e.games >= 3)
    .map((e) => ({
      name: e.name, pos: e.pos, games: e.games,
      gpm: mean(e.gpm), dpm: mean(e.dpm), part: e.part.length ? mean(e.part) : null, deaths: mean(e.d),
    }))
    .sort((a, b) => LANES.indexOf(a.pos) - LANES.indexOf(b.pos) || (b.gpm || 0) - (a.gpm || 0));
}

/* ── 4b. 选手执行：我方逐人 + 对方同位置基准 ─────────────────────
 * 游走不看经济与输出（营地有值，但那一栏对游走没有解释力），页面用横杠；
 * 承伤对四条路都有意义，所以五路统一给承伤，不给「游走也比分均输出」。 */
const EXEC_KEYS = ['gpm', 'dpm', 'dmgShare', 'tpm', 'part', 'd', 'ctrl', 'heal', 'twr', 'rating'];
const execAcc = () => ({ games: 0, heroes: [], buckets: Object.fromEntries(EXEC_KEYS.map((k) => [k, []])) });
function execPush(e, p) {
  e.games += 1;
  if (p.hero) e.heroes.push(p.hero);
  for (const key of EXEC_KEYS) {
    const v = key === 'part' ? (num(p.part) ? (p.part > 1.5 ? p.part / 100 : p.part) : null) : p[key];
    if (num(v)) e.buckets[key].push(v);
  }
}
function execOut(e) {
  const out = { games: e.games, heroes: e.heroes };
  for (const key of EXEC_KEYS) out[key] = e.buckets[key].length ? mean(e.buckets[key]) : null;
  return out;
}
function executionOf(rows) {
  const own = new Map();
  const foe = new Map();
  for (const r of rows) {
    const foePlayers = r.plAll.filter((p) => p.camp && p.camp !== r.camp);
    const ownDpm = r.pl.reduce((sum, p) => sum + (num(p.dpm) ? p.dpm : 0), 0);
    const foeDpm = foePlayers.reduce((sum, p) => sum + (num(p.dpm) ? p.dpm : 0), 0);
    /* 输出占比 = 个人分均输出 / 本队五人分均输出之和。分均与伤害同除时长，
       占比不受局时长影响；比直接摆分均伤害更适合跨位置比较。 */
    for (const p of r.pl) {
      if (!p.pos) continue;
      const key = `${p.pos}|${p.name || '—'}`;
      const e = own.get(key) || { pos: p.pos, name: p.name || '—', ...execAcc() };
      execPush(e, { ...p, dmgShare: ownDpm && num(p.dpm) ? p.dpm / ownDpm : null });
      own.set(key, e);
    }
    for (const p of foePlayers) {
      if (!p.pos) continue;
      const e = foe.get(p.pos) || { pos: p.pos, ...execAcc() };
      execPush(e, { ...p, dmgShare: foeDpm && num(p.dpm) ? p.dpm / foeDpm : null });
      foe.set(p.pos, e);
    }
  }
  const item = (e) => ({ ...execOut(e), pos: e.pos, name: e.name });
  const ownRows = [...own.values()].map(item)
    .sort((a, b) => LANES.indexOf(a.pos) - LANES.indexOf(b.pos) || b.games - a.games);
  const foeRows = {};
  for (const e of foe.values()) foeRows[e.pos] = execOut(e);
  return { own: ownRows, foe: foeRows, n: rows.filter((r) => r.pl.length).length };
}

/* ── 4c. 英雄类型：五路打法选择（我方 / 对方同一口径）───────────── */
const ARCH_ORDER = {
  对抗路: ['战边', '坦边'], 打野: ['刺野', '战野', '坦野'], 中路: ['法刺', '工具人'],
  发育路: ['游射', '呆射'], 游走: ['开团辅', '保护辅', '功能辅'],
};
function archetypeOf(rows) {
  const UNKNOWN = new Set(['', '待分类', '未标注', '其他']);
  /* 老缓存里中路还叫「法核」；赛训组 2026-11-19 明确只有「法刺」。
     读到旧值就地归一，避免整张图把中路拆成两个类型。 */
  const normArch = (value) => (value === '法核' ? '法刺' : value);
  const build = (side) => {
    const map = new Map();
    const unknown = new Map();
    for (const r of rows) {
      const list = side === 'own' ? r.pl : r.plAll.filter((p) => p.camp !== r.camp);
      for (const p of list) {
        if (!p.pos) continue;
        /* 该分路没登记类型时（营地/工作簿没给这一路），退回英雄默认分路的类型：
           教练要的是「这个英雄是什么类型」，不是看一个「待分类」占位。
           真正一个类型都没有的英雄才单列一句。 */
        const laneArch = p.arch && !UNKNOWN.has(p.arch) ? normArch(p.arch) : '';
        const arch = laneArch || (p.archDefault && !UNKNOWN.has(p.archDefault) ? normArch(p.archDefault) : '');
        if (!arch) {
          const u = unknown.get(p.pos) || { pos: p.pos, games: 0, heroes: [] };
          u.games += 1;
          if (p.hero) u.heroes.push(p.hero);
          unknown.set(p.pos, u);
          continue;
        }
        const key = `${p.pos}|${arch}`;
        const e = map.get(key) || { pos: p.pos, arch, games: 0, wins: 0, decided: 0, heroes: [], inferred: 0 };
        e.games += 1;
        if (!laneArch) e.inferred += 1;
        e.heroes.push(p.hero);
        if (r.result === 'win') e.wins += 1;
        if (r.decided) e.decided += 1;
        map.set(key, e);
      }
    }
    const total = new Map();
    for (const e of map.values()) total.set(e.pos, (total.get(e.pos) || 0) + e.games);
    return LANES.map((lane) => {
      const items = [...map.values()].filter((e) => e.pos === lane).map((e) => ({
        ...e, label: e.arch, share: total.get(lane) ? e.games / total.get(lane) : null,
        rate: rateOf(e.wins, e.decided),
        top: [...new Set(e.heroes)].slice(0, 4),
      }));
      const order = ARCH_ORDER[lane] || [];
      items.sort((a, b) => (order.indexOf(a.arch) + 1 || 99) - (order.indexOf(b.arch) + 1 || 99) || b.games - a.games);
      const miss = unknown.get(lane);
      return {
        lane, n: total.get(lane) || 0, items,
        unknown: miss ? { games: miss.games, heroes: [...new Set(miss.heroes)] } : null,
      };
    }).filter((x) => x.n);
  };
  return { own: build('own'), foe: build('foe') };
}

/* ── 4d. BP 对位台：指定英雄被怎么 ban / 被谁打 / 哪些队怎么配 ───── */
function banIndexMap(rows, listKey, hero) {
  const out = [0, 0, 0, 0, 0];
  let hit = 0;
  for (const r of rows) {
    const list = r[listKey] || [];
    const i = list.indexOf(hero);
    if (i >= 0) {
      out[Math.min(i, 4)] += 1;
      hit += 1;
    }
  }
  return { byTurn: out, games: hit };
}
function ourHeroTarget(rows, heroes) {
  const want = (Array.isArray(heroes) ? heroes : [heroes]).filter(Boolean).slice(0, 4);
  const hero = want[0];
  if (!hero) return null;
  const picked = rows.filter((r) => want.every((h) => r.heroes.includes(h)));
  const decided = picked.filter((r) => r.decided);
  const wins = picked.filter((r) => r.result === 'win').length;
  const ban = banIndexMap(rows, 'bansFoe', hero);
  const banOwn = banIndexMap(rows, 'bansOwn', hero);
  const ban2 = want[1] ? banIndexMap(rows, 'bansFoe', want[1]) : null;
  // 没被 ban 的时候，对方同位置拿什么来打：只按「我方这条路上的是这个英雄」取对方同位置。
  const respMap = new Map();
  for (const r of picked) {
    const mine = r.pl.find((p) => p.hero === hero);
    if (!mine || !mine.pos) continue;
    const theirs = r.plAll.find((p) => p.camp !== r.camp && p.pos === mine.pos && p.hero);
    if (!theirs) continue;
    const e = respMap.get(theirs.hero) || { hero: theirs.hero, games: 0, foeWins: 0, ownWins: 0, heroes: [] };
    e.games += 1;
    e.heroes.push(mine.hero);
    if (r.result === 'loss') e.foeWins += 1;
    if (r.result === 'win') e.ownWins += 1;
    respMap.set(theirs.hero, e);
  }
  const responses = [...respMap.values()].sort((a, b) => b.games - a.games || b.foeWins - a.foeWins)
    .slice(0, 8).map((e) => ({ ...e, foeRate: rateOf(e.foeWins, e.games) }));
  // 我方这套（一个或两个英雄）在场的局里，对方整条阵容是什么组合。
  const comboMap = new Map();
  for (const r of picked) {
    const hs = [...new Set(r.heroesFoe)].filter(Boolean);
    for (let i = 0; i < hs.length; i++) {
      for (let j = i + 1; j < hs.length; j++) {
        const key = [hs[i], hs[j]].sort().join('+');
        const e = comboMap.get(key) || { heroes: [hs[i], hs[j]].sort(), games: 0, foeWins: 0 };
        e.games += 1;
        if (r.result === 'loss') e.foeWins += 1;
        comboMap.set(key, e);
      }
    }
  }
  const combos = [...comboMap.values()].sort((a, b) => b.games - a.games || b.foeWins - a.foeWins)
    .slice(0, 5).map((e) => ({ ...e, foeRate: rateOf(e.foeWins, e.games) }));
  const byOpponent = [];
  const oppMap = new Map();
  for (const r of picked) {
    const name = String(r.opponent || '').trim() || '未标注对手';
    const e = oppMap.get(name) || { name, games: 0, wins: 0, decided: 0, heroes: new Map() };
    e.games += 1;
    if (r.result === 'win') e.wins += 1;
    if (r.decided) e.decided += 1;
    const mine = r.pl.find((p) => p.hero === hero);
    const theirs = mine && r.plAll.find((p) => p.camp !== r.camp && p.pos === mine.pos && p.hero);
    if (theirs) e.heroes.set(theirs.hero, (e.heroes.get(theirs.hero) || 0) + 1);
    oppMap.set(name, e);
  }
  for (const e of [...oppMap.values()].sort((a, b) => b.games - a.games).slice(0, 6)) {
    byOpponent.push({
      name: e.name, games: e.games, wins: e.wins, rate: rateOf(e.wins, e.decided),
      responses: [...e.heroes.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([h, n]) => ({ hero: h, games: n })),
    });
  }
  return {
    hero, heroes: want, want, games: picked.length, decided: decided.length, wins,
    rate: rateOf(wins, decided.length),
    ban, ban2, banOwn, responses, combos, byOpponent,
    banTotal: ban.games + picked.length,
  };
}
function foeHeroPairing(rows, heroOrHeroes) {
  /* 反过来看：所选英雄（1–4 个，2 个以上按组合）同时在「对方」阵容出现时，
     各队还拿谁来跟它搭。传字符串仍按单英雄处理，兼容旧调用方。 */
  const heroes = (Array.isArray(heroOrHeroes) ? heroOrHeroes : [heroOrHeroes]).filter(Boolean).slice(0, 4);
  if (!heroes.length) return null;
  const hero = heroes[0];
  const isCombo = heroes.length > 1;
  const picked = rows.filter((r) => heroes.every((h) => r.heroesFoe.includes(h)));
  const foeWins = picked.filter((r) => r.result === 'loss').length;
  /* 组合下「ban 过其中任意一个」按局去重，不重复计数。 */
  const ban = isCombo
    ? { games: rows.filter((r) => heroes.some((h) => (r.bansOwn || []).includes(h))).length }
    : banIndexMap(rows, 'bansOwn', hero);
  const partnerMap = new Map();
  for (const r of picked) {
    for (const h of [...new Set(r.heroesFoe)].filter((x) => x && !heroes.includes(x))) {
      const e = partnerMap.get(h) || { hero: h, games: 0, foeWins: 0 };
      e.games += 1;
      if (r.result === 'loss') e.foeWins += 1;
      partnerMap.set(h, e);
    }
  }
  const partners = [...partnerMap.values()].sort((a, b) => b.games - a.games || b.foeWins - a.foeWins)
    .slice(0, 10).map((e) => ({ ...e, foeRate: rateOf(e.foeWins, e.games) }));
  const byOpponent = [];
  const oppMap = new Map();
  for (const r of picked) {
    const name = String(r.opponent || '').trim() || '未标注对手';
    const e = oppMap.get(name) || { name, games: 0, foeWins: 0, partners: new Map() };
    e.games += 1;
    if (r.result === 'loss') e.foeWins += 1;
    for (const h of [...new Set(r.heroesFoe)].filter((x) => x && !heroes.includes(x))) {
      e.partners.set(h, (e.partners.get(h) || 0) + 1);
    }
    oppMap.set(name, e);
  }
  for (const e of [...oppMap.values()].sort((a, b) => b.games - a.games).slice(0, 6)) {
    byOpponent.push({
      name: e.name, games: e.games, rate: rateOf(e.foeWins, e.games),
      partners: [...e.partners.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([h, n]) => ({ hero: h, games: n })),
    });
  }
  return { hero, heroes, want: heroes, isCombo, games: picked.length, foeWins, rate: rateOf(foeWins, picked.length), ban, partners, byOpponent };
}

/* ── 5. 前期节奏 ──────────────────────────────────────────────── */
function earlyOf(rows) {
  const firstRows = rows.filter((r) => r.first);
  const event = (key) => {
    const own = firstRows.filter((r) => firstSide(r, key) === 'own');
    const foe = firstRows.filter((r) => firstSide(r, key) === 'foe');
    const times = vals(firstRows.map((r) => r.first[`${key}T`]));
    return {
      own: own.length, foe: foe.length, n: own.length + foe.length,
      rate: own.length + foe.length ? own.length / (own.length + foe.length) : null,
      avgT: mean(times),
      // 拿到的用时（只算我方拿到的那几局）：教练看的是「几分钟拿到」，不是百分比。
      ownT: vals(own.map((r) => r.first[`${key}T`])),
      winOwn: rateOf(own.filter((r) => r.result === 'win').length, own.filter((r) => r.decided).length),
      winFoe: rateOf(foe.filter((r) => r.result === 'win').length, foe.filter((r) => r.decided).length),
    };
  };
  const at4 = vals(rows.map((r) => r.at4));
  const jungle = rows.filter((r) => num(r.jungle.crossShare));
  const obj10 = rows.filter((r) => r.objAt10);
  return {
    n: rows.length,
    firstN: firstRows.filter((r) => firstSide(r, 'blood') || firstSide(r, 'dragon') || firstSide(r, 'tower')).length,
    blood: event('blood'), dragon: event('dragon'), tower: event('tower'),
    at4: { n: at4.length, med: median(at4), leadRate: at4.length ? at4.filter((v) => v > 0).length / at4.length : null },
    jungle: {
      n: jungle.length, cross: median(jungle.map((r) => r.jungle.crossShare)),
      deep: median(jungle.map((r) => r.jungle.deepShare).filter(num)),
      first: median(jungle.map((r) => r.jungle.firstCross).filter(num)),
      // 秒数口径：过河总时长 / 深入野区总时长（0–10 分钟逐秒坐标），教练比百分比好懂。
      crossSec: median(jungle.map((r) => r.jungle.crossSec).filter(num)),
      deepSec: median(jungle.map((r) => r.jungle.deepSec).filter(num)),
      // 中位数是 0 时说明一半以上的局根本没进深区，光给 0 秒没信息量：
      // 补「进入的局数」与「进入的局平均秒数」。
      deepGames: jungle.filter((r) => num(r.jungle.deepSec) && r.jungle.deepSec > 0).length,
      deepMeanIn: mean(jungle.map((r) => r.jungle.deepSec).filter((v) => num(v) && v > 0)),
      anti: mean(jungle.map((r) => r.buff.anti).filter(num)),
      stolen: mean(jungle.map((r) => r.buff.stolen).filter(num)),
      antiRed: mean(jungle.map((r) => r.buff.antiRed).filter(num)),
      antiBlue: mean(jungle.map((r) => r.buff.antiBlue).filter(num)),
      stolenRed: mean(jungle.map((r) => r.buff.stolenRed).filter(num)),
      stolenBlue: mean(jungle.map((r) => r.buff.stolenBlue).filter(num)),
    },
    obj10: obj10.length ? {
      n: obj10.length,
      dragonOwn: mean(obj10.map((r) => r.objAt10.dragonOwn)),
      dragonFoe: mean(obj10.map((r) => r.objAt10.dragonFoe)),
      towerOwn: mean(obj10.map((r) => r.objAt10.towerOwn)),
      towerFoe: mean(obj10.map((r) => r.objAt10.towerFoe)),
    } : null,
  };
}

/* ── 6. 经济路径与滚雪球 ──────────────────────────────────────── */
/* 一句「10 分钟领先 ≥3,000 金币的 2 局」教练第一反应是「哪 2 局、各领先多少」。
   标签复用逐局卡片口径：日期 + 对手（有局序再带 G），缺字段退回 key，不补 0。 */
const gameLabelOf = (r) => {
  const day = String(r.date || '').slice(5);
  const who = r.opponent ? `对阵${r.opponent}` : '';
  const g = num(r.gameIndex) ? `G${r.gameIndex}` : '';
  return [g, day, who].filter(Boolean).join(' ') || String(r.key || '');
};

function pathOf(rows) {
  const checkpoints = PHASE_CHECKPOINTS.map((minute) => {
    const idx = minute / 5;
    const pick = (list) => {
      const a = vals(list.filter((r) => num(r.duration) && r.duration >= minute * 60).map((r) => r.g[idx]));
      return { n: a.length, med: median(a), p25: quantile(a, 0.25), p75: quantile(a, 0.75) };
    };
    return {
      minute,
      win: pick(rows.filter((r) => r.result === 'win')),
      loss: pick(rows.filter((r) => r.result === 'loss')),
      all: pick(rows),
    };
  });
  const phase = PHASES.map((p) => {
    const w = vals(rows.filter((r) => r.result === 'win').map((r) => r.seg[p.key]));
    const l = vals(rows.filter((r) => r.result === 'loss').map((r) => r.seg[p.key]));
    return { ...p, win: median(w), loss: median(l), nWin: w.length, nLoss: l.length };
  });
  const leadAt = (threshold) => rows.filter((r) => num(r.at10) && r.at10 >= threshold);
  const lead10 = leadAt(BIG_LEAD_AT10);
  const leadTiers = Object.fromEntries(LEAD_TIERS.map(({ threshold }) => {
    const list = leadAt(threshold);
    return [threshold, {
      n: list.length,
      wins: list.filter((r) => r.result === 'win').length,
    }];
  }));
  const leadWin = lead10.filter((r) => r.result === 'win').length;
  const leadShrink = lead10.filter((r) => num(r.final) && r.final < r.at10).length;
  const lateGain = vals(rows.filter((r) => num(r.at10) && num(r.final)).map((r) => r.final - r.at10));
  // 逐局明细：教练看到「2 局」会追问是哪几局、各领先多少，直接带出来，别只给计数。
  // 按时间正序，和逐局卡片保持一致；at10 是我方视角的 10 分钟经济差（金币）。
  const leadGames = lead10.slice().sort(byOrder).map((r) => ({
    key: r.key,
    label: gameLabelOf(r),
    at10: r.at10,
    result: r.result,
  }));
  /* 阶段锚点曲线：教练按 0–4 / 4–10 / 10–结束 三段读比赛，
     所以曲线只落在这四个锚点上（开局 / 4′ / 10′ / 终局），每段带 n。
     仍取「常见值」（中位数）：2 局就是这 2 局，不伪装成稳定平均。 */
  const anchors = [
    { key: 'start', label: '开局', minute: 0 },
    { key: 'at4', label: '4′', minute: 4 },
    { key: 'at10', label: '10′', minute: 10 },
    { key: 'final', label: '终局', minute: null },
  ];
  const anchorPick = (list, key) => {
    if (key === 'start') {
      const n = list.filter((r) => num(r.at4) || num(r.at10) || num(r.final)).length;
      return { n, med: n ? 0 : null };
    }
    const v = vals(list.map((r) => r[key]));
    return { n: v.length, med: median(v) };
  };
  const curve = anchors.map((a) => ({
    ...a,
    win: anchorPick(rows.filter((r) => r.result === 'win'), a.key),
    loss: anchorPick(rows.filter((r) => r.result === 'loss'), a.key),
  }));
  return {
    checkpoints, phase, curve,
    lead: {
      n: lead10.length, wins: leadWin, rate: rateOf(leadWin, lead10.length), shrink: rateOf(leadShrink, lead10.length),
      games: leadGames,
      /* 教练问「领先那几局到底领先多少」，给这些局各自的 10 分钟金币与均值，
         不给固定门槛值；两档样本量分列在 tiers，口径一眼可对。 */
      tiers: leadTiers,
      avgAt10: leadGames.length ? mean(leadGames.map((g) => g.at10)) : null,
    },
    lateGain: { n: lateGain.length, med: median(lateGain) },
  };
}

/* ── 7. 资源与兑现 ────────────────────────────────────────────── */
function objectiveOf(rows) {
  const withObj = rows.filter((r) => num(r.obj.dragonOwn) && num(r.obj.dragonFoe));
  const dragonOwn = sum(withObj.map((r) => r.obj.dragonOwn));
  const dragonFoe = sum(withObj.map((r) => r.obj.dragonFoe));
  const towerRows = withObj.filter((r) => num(r.obj.towerOwn) && num(r.obj.towerFoe));
  const towerOwn = towerRows.map((r) => r.obj.towerOwn);
  const towerFoe = towerRows.map((r) => r.obj.towerFoe);
  const lead = rows.filter((r) => num(r.at10) && r.at10 > 0 && r.decided);
  const step = (label, list) => ({
    label, n: list.length, wins: list.filter((r) => r.result === 'win').length,
    rate: rateOf(list.filter((r) => r.result === 'win').length, list.length),
    keys: list.map((r) => r.key),
  });
  const hasDragon = (r) => num(r.obj.dragonOwn) && r.obj.dragonOwn > 0;
  const hasTower = (r) => num(r.obj.towerOwn) && num(r.obj.towerFoe) && r.obj.towerOwn > r.obj.towerFoe;
  const steps = [
    step('10 分钟领先', lead),
    step('领先 + 拿到龙', lead.filter(hasDragon)),
    step('领先 + 推塔占优', lead.filter(hasTower)),
    step('领先 + 龙塔都做到', lead.filter((r) => hasDragon(r) && hasTower(r))),
  ];
  const behind = rows.filter((r) => num(r.at10) && r.at10 < 0 && r.decided);
  return {
    n: withObj.length,
    dragon: { own: dragonOwn, foe: dragonFoe, rate: dragonOwn + dragonFoe ? dragonOwn / (dragonOwn + dragonFoe) : null },
    tower: { own: mean(towerOwn), foe: mean(towerFoe), diff: mean(towerRows.map((r) => r.obj.towerOwn - r.obj.towerFoe)) },
    steps,
    comeback: { n: behind.length, wins: behind.filter((r) => r.result === 'win').length, rate: rateOf(behind.filter((r) => r.result === 'win').length, behind.length) },
  };
}

/* ── 8. 团战结构 ──────────────────────────────────────────────── */
function fightOf(rows) {
  const withFight = rows.filter((r) => num(r.fight.n));
  const decidedN = sum(withFight.map((r) => (num(r.fight.decidedN) ? r.fight.decidedN : 0)));
  const decidedWin = sum(withFight.map((r) => (num(r.fight.decidedWin) ? r.fight.decidedWin : 0)));
  const bucket = (key) => {
    const list = rows.map((r) => r.fk && r.fk[key]).filter((x) => x && num(x.n) && x.n > 0);
    const n = sum(list.map((x) => x.n));
    const wins = sum(list.map((x) => x.win));
    return { n, wins, rate: rateOf(wins, n) };
  };
  const deaths = vals(rows.map((r) => r.death.own));
  const fightsPerGame = vals(rows.map((r) => r.fight.n));
  const cut = vals(rows.map((r) => r.cut.n));
  const fsMap = new Map();
  for (const r of rows) {
    if (!r.fs) continue;
    for (const lane of LANES) {
      const cell = r.fs[lane];
      if (!cell || !num(cell.n) || !cell.n) continue;
      const e = fsMap.get(lane) || { lane, hurt: 0, taken: 0, n: 0 };
      e.hurt += (cell.hurtShare || 0) * cell.n;
      e.taken += (cell.takenShare || 0) * cell.n;
      e.n += cell.n;
      fsMap.set(lane, e);
    }
  }
  return {
    n: withFight.length,
    decided: rateOf(decidedWin, decidedN),
    totalN: sum(withFight.map((r) => r.fight.n)),
    adv: bucket('adv'), even: bucket('even'), dis: bucket('dis'),
    first: bucket('first'), firstAgainst: bucket('firstAgainst'),
    deaths: { n: deaths.length, avg: mean(deaths) },
    perGame: { n: fightsPerGame.length, avg: mean(fightsPerGame) },
    cut: { n: cut.length, avg: mean(cut) },
    damage: LANES.map((lane) => {
      const e = fsMap.get(lane);
      return e ? { lane, hurt: e.hurt / e.n, taken: e.taken / e.n, n: e.n } : null;
    }).filter(Boolean),
  };
}

/* ── 9. BP 与阵容 ─────────────────────────────────────────────── */
function draftOf(rows) {
  const decided = rows.filter((r) => r.decided);
  const baseline = decided.length ? decided.filter((r) => r.result === 'win').length / decided.length : null;

  const compMap = new Map();
  for (const r of rows) {
    for (const tag of (r.compOwn || [])) {
      const e = compMap.get(tag) || { tag, games: 0, wins: 0, decided: 0, at10: [] };
      e.games += 1;
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
      if (num(r.at10)) e.at10.push(r.at10);
      compMap.set(tag, e);
    }
  }
  const comps = [...compMap.values()].map((e) => ({
    tag: e.tag, games: e.games, wins: e.wins, decided: e.decided,
    rate: rateOf(e.wins, e.decided), at10: e.at10.length ? median(e.at10) : null,
    share: rows.length ? e.games / rows.length : null,
  })).sort((a, b) => b.games - a.games);

  const signature = LANES.map((lane) => {
    const map = new Map();
    for (const r of rows) {
      const p = ownPlayerAt(r, lane);
      if (!p || !p.hero) continue;
      const e = map.get(p.hero) || { hero: p.hero, arch: p.arch || '', games: 0, wins: 0, decided: 0 };
      e.games += 1;
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
      map.set(p.hero, e);
    }
    return {
      lane,
      heroes: [...map.values()].sort((a, b) => b.games - a.games).slice(0, 4)
        .map((e) => ({ ...e, rate: rateOf(e.wins, e.decided) })),
    };
  });

  const compsFoe = (() => {
    const map = new Map();
    for (const r of rows) {
      for (const tag of (r.compFoe || [])) {
        const e = map.get(tag) || { tag, games: 0, wins: 0, decided: 0 };
        e.games += 1;
        if (r.result === 'loss') e.wins += 1;
        if (r.decided) e.decided += 1;
        map.set(tag, e);
      }
    }
    return [...map.values()].map((e) => ({
      ...e, rate: rateOf(e.wins, e.decided), share: rows.length ? e.games / rows.length : null,
    })).sort((a, b) => b.games - a.games);
  })();

  const heroMap = new Map();
  const heroFoeMap = new Map();
  const banFoeMap = new Map();
  for (const r of rows) {
    for (const hero of r.heroes) {
      const e = heroMap.get(hero) || { hero, games: 0, wins: 0, decided: 0, at10: [], keys: [] };
      e.games += 1;
      e.keys.push(r.key);
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
      if (num(r.at10)) e.at10.push(r.at10);
      heroMap.set(hero, e);
    }
    for (const hero of r.heroesFoe) {
      // 对方英雄池：胜率是「我方胜率」，所以计数用 result === 'win' 保持一致口径。
      const e = heroFoeMap.get(hero) || { hero, games: 0, wins: 0, decided: 0, at10: [] };
      e.games += 1;
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
      if (num(r.at10)) e.at10.push(r.at10);
      heroFoeMap.set(hero, e);
    }
    for (const hero of (r.bansFoe || [])) {
      const e = banFoeMap.get(hero) || { hero, games: 0, wins: 0, decided: 0 };
      e.games += 1;
      if (r.result === 'win') e.wins += 1;
      if (r.decided) e.decided += 1;
      banFoeMap.set(hero, e);
    }
  }
  const heroes = [...heroMap.values()].map((e) => ({
    hero: e.hero, games: e.games, wins: e.wins, decided: e.decided,
    rate: rateOf(e.wins, e.decided),
    shrunk: shrink(e.wins, e.decided, baseline),
    at10: e.at10.length ? median(e.at10) : null,
    keys: e.keys,
  })).sort((a, b) => b.games - a.games || (b.shrunk || 0) - (a.shrunk || 0));
  const heroesFoe = [...heroFoeMap.values()].map((e) => ({
    hero: e.hero, games: e.games, wins: e.wins, decided: e.decided,
    rate: rateOf(e.wins, e.decided),
    at10: e.at10.length ? median(e.at10) : null,
  })).sort((a, b) => b.games - a.games);

  const pairMap = (side) => {
    const pairs = new Map();
    for (const r of rows) {
      const hs = [...new Set(side === 'own' ? r.heroes : r.heroesFoe)].filter(Boolean).slice(0, 5);
      if (hs.length < 2) continue;
      for (let i = 0; i < hs.length; i++) {
        for (let j = i + 1; j < hs.length; j++) {
          const key = [hs[i], hs[j]].sort().join('+');
          const e = pairs.get(key) || { heroes: [hs[i], hs[j]], games: 0, wins: 0, decided: 0, keys: [] };
          e.games += 1;
          e.keys.push(r.key);
          if (r.result === 'win') e.wins += 1;
          if (r.decided) e.decided += 1;
          pairs.set(key, e);
        }
      }
    }
    const decided = rows.filter((r) => r.decided);
    const build = (min) => [...pairs.values()].map((e) => ({
      heroes: e.heroes, label: e.heroes.join(' + '), n: e.decided, games: e.games, wins: e.wins,
      rate: rateOf(e.wins, e.decided), keys: e.keys.slice(0, 30),
    })).filter((x) => x.n >= min && x.rate && num(x.rate.value));
    let floor = 3;
    let list = build(3);
    if (!list.length) { floor = 2; list = build(2); }
    // 递增胜率排序：只给「跟不带它比」的差值留给我方的组合卡；对方组合只看自己的胜率。
    for (const x of list) {
      const keys = new Set(x.keys);
      const rest = decided.filter((r) => !keys.has(r.key));
      const restRate = rest.length ? rest.filter((r) => r.result === 'win').length / rest.length : null;
      x.lift = num(restRate) ? x.rate.value - restRate : null;
      x.otherRate = restRate;
      x.otherN = rest.length;
    }
    const total = rows.filter((r) => (side === 'own' ? r.heroes : r.heroesFoe).length >= 2).length;
    const sorted = list.sort((a, b) => (b.lift ?? -9) - (a.lift ?? -9));
    /* 同一套五人阵容会派生 10 组双人组合，铺出来就是十行一模一样的数据：
       按「同一批局」去重，只留第一组，卡的语义变成「这套阵容打了几局、赢几局」。 */
    const seen = new Set();
    const unique = sorted.filter((x) => {
      const sig = [...x.keys].sort().join('|');
      if (seen.has(sig)) return false;
      seen.add(sig);
      return true;
    });
    return { list: unique, all: sorted, floor, count: unique.length, total };
  };
  const ownPool = pairMap('own');
  const foePool = pairMap('foe');
  const ownPairs = ownPool.list;
  const foePairs = foePool.list;

  const sides = ['blue', 'red'].map((side) => {
    const list = decided.filter((r) => r.camp === side);
    const wins = list.filter((r) => r.result === 'win').length;
    const at10 = vals(list.map((r) => r.at10));
    return { side, n: list.length, wins, rate: rateOf(wins, list.length), at10: at10.length ? median(at10) : null };
  });

  const bansOwn = [...new Map([...rows.flatMap((r) => (r.bansOwn || []).map((hero) => [hero, null]))]).keys()]
    .map((hero) => {
      const list = rows.filter((r) => (r.bansOwn || []).includes(hero));
      const wins = list.filter((r) => r.result === 'win').length;
      return { hero, games: list.length, rate: rateOf(wins, list.filter((r) => r.decided).length) };
    }).sort((a, b) => b.games - a.games);
  const bansFoe = [...new Map([...rows.flatMap((r) => (r.bansFoe || []).map((hero) => [hero, null]))]).keys()]
    .map((hero) => {
      const list = rows.filter((r) => (r.bansFoe || []).includes(hero));
      const wins = list.filter((r) => r.result === 'win').length;
      return { hero, games: list.length, rate: rateOf(wins, list.filter((r) => r.decided).length) };
    }).sort((a, b) => b.games - a.games);

  return {
    baseline, comps, compsFoe, signature, heroes, heroesFoe,
    pairs: { best: ownPairs.slice(0, 4), worst: ownPairs.slice(-4).reverse(), n: ownPairs.length, foe: foePairs },
    pairPool: ownPool, pairPoolFoe: foePool,
    sides, bansOwn, bansFoe,
    coverage: { comp: rows.filter((r) => r.compOwn).length, bans: rows.filter((r) => Array.isArray(r.bansOwn)).length, arch: rows.filter((r) => r.pl.some((p) => p.arch)).length },
  };
}

/* ── 10. 对手 ─────────────────────────────────────────────────── */
function opponentOf(rows) {
  const groups = new Map();
  for (const r of rows) {
    const name = String(r.opponent || '').trim() || '未标注对手';
    const e = groups.get(name) || { name, list: [] };
    e.list.push(r);
    groups.set(name, e);
  }
  const items = [...groups.values()].map(({ name, list }) => {
    const decided = list.filter((r) => r.decided);
    const wins = decided.filter((r) => r.result === 'win').length;
    const at10 = vals(list.map((r) => r.at10));
    const final = vals(list.map((r) => r.final));
    const dur = vals(list.map((r) => r.duration));
    const laneMed = LANES.map((lane) => {
      const a = vals(list.map((r) => laneValue(r, lane, 'gold')));
      return { lane, med: median(a), n: a.length };
    }).filter((x) => x.n);
    const heroes = (() => {
      const m = new Map();
      for (const r of list) for (const h of r.heroesFoe) {
        const e = m.get(h) || { hero: h, games: 0, wins: 0, decided: 0 };
        e.games += 1;
        if (r.result === 'win') e.wins += 1;
        if (r.decided) e.decided += 1;
        m.set(h, e);
      }
      return [...m.values()].sort((a, b) => b.games - a.games).slice(0, 3)
        .map((e) => ({ ...e, rate: rateOf(e.wins, e.decided) }));
    })();
    const firstBlood = list.filter((r) => firstSide(r, 'blood') === 'own').length;
    const firstBloodN = list.filter((r) => firstSide(r, 'blood')).length;
    const dragon = list.filter((r) => num(dragonRate(r)));
    const dragonOwn = sum(dragon.map((r) => r.obj.dragonOwn));
    const dragonFoe = sum(dragon.map((r) => r.obj.dragonFoe));
    const towerDiffVals = vals(list.map(towerDiff));
    const dates = list.map((r) => String(r.date || '')).filter(Boolean).sort();
    const sides = { blue: list.filter((r) => r.camp === 'blue').length, red: list.filter((r) => r.camp === 'red').length };
    const traits = [];
    if (dur.length && median(dur) >= 1000) traits.push('偏慢');
    if (dur.length && median(dur) < 780) traits.push('偏快');
    if (dragonOwn + dragonFoe && dragonOwn / (dragonOwn + dragonFoe) >= 0.6) traits.push('控龙强');
    if (firstBloodN && firstBlood / firstBloodN >= 0.6) traits.push('前期主动');
    if (towerDiffVals.length && mean(towerDiffVals) <= -3) traits.push('推塔压制');
    return {
      name, n: list.length, decided: decided.length, wins, losses: decided.length - wins,
      rate: rateOf(wins, decided.length),
      at10: at10.length ? median(at10) : null,
      final: final.length ? median(final) : null,
      duration: dur.length ? mean(dur) : null,
      lane: { best: laneMed.slice().sort((a, b) => (b.med || 0) - (a.med || 0))[0] || null, worst: laneMed.slice().sort((a, b) => (a.med || 0) - (b.med || 0))[0] || null },
      heroes, firstBlood: rateOf(firstBlood, firstBloodN),
      dragon: dragonOwn + dragonFoe ? dragonOwn / (dragonOwn + dragonFoe) : null,
      towerDiff: mean(towerDiffVals),
      sides, traits,
      lastDate: dates[dates.length - 1] || '',
      keys: list.map((r) => r.key),
    };
  }).sort((a, b) => b.n - a.n);
  const ranked = items.filter((x) => x.decided >= 3 && num(x.rate.value));
  const easiest = ranked.slice().sort((a, b) => (b.rate.value || 0) - (a.rate.value || 0))[0] || null;
  const hardest = ranked.slice().sort((a, b) => (a.rate.value || 0) - (b.rate.value || 0))[0] || null;
  const unknown = items.find((x) => x.name === '未标注对手') || null;
  return { items, easiest, hardest, unknown };
}

/* ── 对外入口 ─────────────────────────────────────────────────── */
export function analyzeCohort(vectors) {
  const rows = prepare(vectors);
  const coverage = coverageOf(rows);
  const record = recordOf(rows);
  const trend = trendOf(rows);
  const drivers = driversOf(rows);
  const risk = riskOf(rows);
  const lane = laneOf(rows);
  const players = playerExecutionOf(rows);
  const early = earlyOf(rows);
  const path = pathOf(rows);
  const objective = objectiveOf(rows);
  const fight = fightOf(rows);
  const draft = draftOf(rows);
  const opponents = opponentOf(rows);
  return {
    total: rows.length,
    // 「看这 N 局」需要按 key 反查原始逐局：页面只读，不改口径。
    rows,
    coverage, record, trend, drivers,
    winCondition: winConditionOf(drivers),
    risk, lane, players, early, path, objective, fight, draft, opponents,
    execution: executionOf(rows),
    archetypes: archetypeOf(rows),
    // BP 对位台按「点哪个英雄」现算：只在这一批局里查，不跨到范围外。
    bp: {
      target: (heroes) => ourHeroTarget(rows, heroes),
      pairing: (heroes) => foeHeroPairing(rows, heroes),
    },
    // 兼容旧调用方：不再有 23 张卡，但保留一个可遍历的结论数量。
    cardCount: [drivers.length > 0, early.firstN > 0, objective.n > 0, fight.n > 0, draft.heroes.length > 0, opponents.items.length > 0].filter(Boolean).length,
  };
}

/* 导出内部纯函数，供 scripts/test_cross_analytics.mjs 做口径回归。 */
export const internals = {
  prepare, coverageOf, recordOf, trendOf, driversOf, riskOf, laneOf, playerExecutionOf, earlyOf,
  pathOf, objectiveOf, fightOf, draftOf, opponentOf, executionOf, archetypeOf, ourHeroTarget, foeHeroPairing,
  quantile, median, wilson, cliffs, shrink, rateOf, halves, reproduce, gameLabelOf,
};
