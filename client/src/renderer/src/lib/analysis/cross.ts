// @ts-nocheck
/* 从 v3/public/cross-analytics.js 原样移植的通用跨局分析内核。
   输入为 /api/cross/vectors 的轻量向量；纯函数、固定 10 张结论卡。 */

/* 通用跨局分析内核（与 DOM 无关、与局数无关）
 * 输入：全量对局的轻量向量数组（后端 /api/cross/vectors 一次给出）
 * 输出：固定 10 张结论卡 + 一条审计读数；所有图的数据点数恒定，不随 N 增长。
 *
 * 设计前提：结论必须基于「总体分布 + 分层 + 效应量 + 可复现性」，
 * 不能是「这 11 局里挑一局讲故事」。N=11 与 N=30000 走同一套计算，
 * 区别只在置信区间宽度与分级标签，不在代码路径。
 */

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const WINDOW_MIN = 5;

/* ── 基础统计 ─────────────────────────────────────────────────── */
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const vals = (a) => a.filter(num);
const srt = (a) => vals(a).slice().sort((x, y) => x - y);
const mean = (a) => { const v = vals(a); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
const sum = (a) => a.reduce((s, x) => s + (num(x) ? x : 0), 0);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function quantile(a, p) {
  const s = srt(a);
  if (!s.length) return null;
  const i = (s.length - 1) * clamp(p, 0, 1);
  const lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}
const median = (a) => quantile(a, 0.5);
const sd = (a) => { const v = vals(a); if (v.length < 2) return 0; const m = mean(v); return Math.sqrt(sum(v.map((x) => (x - m) ** 2)) / (v.length - 1)); };
const mad = (a) => { const m = median(a); return median(vals(a).map((x) => Math.abs(x - m))) || 0; };

/* 固定种子 LCG：保证 bootstrap 结果可复现，截图与验收不会漂 */
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
}
function bootstrapDiff(a, b, B = 240) {
  if (a.length < 2 || b.length < 2) return null;
  const r = rng(20261108), out = [];
  for (let k = 0; k < B; k++) {
    let sa = 0, sb = 0;
    for (let i = 0; i < a.length; i++) sa += a[Math.floor(r() * a.length)];
    for (let i = 0; i < b.length; i++) sb += b[Math.floor(r() * b.length)];
    out.push(sa / a.length - sb / b.length);
  }
  out.sort((x, y) => x - y);
  return [out[Math.floor(B * 0.025)], out[Math.floor(B * 0.975)]];
}
const medianCi = (a) => {
  const s = srt(a), n = s.length;
  if (n < 4) return null;
  const z = 1.96 * Math.sqrt(n) / 2;
  return [s[clamp(Math.floor(n / 2 - z), 0, n - 1)], s[clamp(Math.ceil(n / 2 + z), 0, n - 1)]];
};
/* Cliff's delta：不要求正态分布，对离群稳健 */
function cliffs(a, b) {
  if (!a.length || !b.length) return null;
  let gt = 0, lt = 0;
  const bs = srt(b);
  for (const x of a) {
    let lo = 0, hi = bs.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (bs[mid] < x) lo = mid + 1; else hi = mid; }
    gt += bs.length - lo; lt += lo;
  }
  return (gt - lt) / (a.length * b.length);
}
function wilson(k, n) {
  if (!n) return [0, 0];
  const p = k / n, z = 1.96, d = 1 + z * z / n;
  const c = (p + z * z / (2 * n)) / d, h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
/* 置信分级是精度读数，不是免责横幅 */
function grade(n, ci, effect) {
  let label = '线索级', level = 0;
  if (n >= 60) { label = '证据充分'; level = 2; }
  else if (n >= 20) { label = '可作为线索'; level = 1; }
  if (level > 0 && ci && num(effect) && Math.abs(effect) > 1e-9 && (ci[1] - ci[0]) / Math.abs(effect) > 1.8) {
    label = '方向未定'; level = 1;
  }
  return { label, level, n };
}
const pct = (v) => `${Math.round(clamp(v, 0, 1) * 100)}%`;
const byOrder = (a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0);
const sign = (v) => (v >= 0 ? '+' : '−') + Math.abs(Math.round(v)).toLocaleString('zh-CN');

/* 按时间顺序切前后半，检验方向型结论能否复现 */
function halves(rows) {
  const t = rows.slice().sort(byOrder);
  const i = Math.floor(t.length / 2);
  return [t.slice(0, i), t.slice(i)];
}
function reproducible(rows, fn) {
  const [x, y] = halves(rows);
  if (x.length < 3 || y.length < 3) return null;
  const a = fn(x), b = fn(y);
  if (!num(a) || !num(b)) return null;
  return a === 0 || b === 0 ? Math.abs(a - b) < Math.abs(a || 1) : a > 0 === b > 0;
}

/* 单因素方差成分：把指标波动拆给「版本 / 对手 / 训练组 / 阵营 / 局内自然波动」 */
function varianceParts(rows, key, dims) {
  const all = rows.filter((r) => num(r[key]));
  const grand = mean(all.map((r) => r[key]));
  const sst = sum(all.map((r) => (r[key] - grand) ** 2));
  if (all.length < 4 || !sst) return [];
  const parts = [];
  for (const dim of dims) {
    const groups = new Map();
    for (const r of all) {
      const g = String(r[dim] || '未标注');
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(r[key]);
    }
    if (groups.size < 2) { parts.push({ dim, share: 0 }); continue; }
    let ssb = 0, harmonic = 0;
    for (const arr of groups.values()) { ssb += arr.length * (mean(arr) - grand) ** 2; harmonic += 1 / arr.length; }
    const k = groups.size / harmonic;
    const msb = ssb / (groups.size - 1);
    const msw = Math.max(0, (sst - ssb) / (all.length - groups.size));
    const vb = Math.max(0, (msb - msw) / k);
    parts.push({ dim, share: vb / (vb + msw) });
  }
  const explained = sum(parts.map((p) => p.share));
  const scale = explained > 1 ? 1 / explained : 1;
  const out = parts.map((p) => ({ label: ({ version: '版本', opponent: '对手', session: '训练组', camp: '阵营' })[p.dim] || p.dim, share: p.share * scale }));
  out.push({ label: '同条件下的自然波动', share: Math.max(0, 1 - sum(out.map((p) => p.share))) });
  return out;
}

/* 分层结构画像：局数增长后必然跨版本 / 训练组 / 对手。
   若某维度既与开赛顺序关联（前后半分布差），又解释了指标波动，
   那它就是「训练效应」的混淆变量，必须在层内比较，否则把版本更替当成进步。 */
function strataProfile(rows) {
  const dims = [['version', '版本'], ['session', '训练组'], ['opponent', '对手']];
  const counts = {};
  for (const [dim] of dims) counts[dim] = new Set(rows.map((r) => String(r[dim] || '未标注'))).size;
  const [early, late] = halves(rows);
  let best = null;
  if (early.length >= 4 && late.length >= 4) {
    for (const [dim, label] of dims) {
      if (counts[dim] < 2) continue;
      const dist = (list) => {
        const m = new Map();
        for (const r of list) { const k = String(r[dim] || '未标注'); m.set(k, (m.get(k) || 0) + 1); }
        return new Map([...m.entries()].map(([k, v]) => [k, v / list.length]));
      };
      const a = dist(early), b = dist(late);
      const keys = new Set([...a.keys(), ...b.keys()]);
      let tvd = 0;
      for (const k of keys) tvd += Math.abs((a.get(k) || 0) - (b.get(k) || 0));
      tvd /= 2;
      const share = (varianceParts(rows, 'at10', [dim]).find((x) => x.label === label) || {}).share || 0;
      const score = tvd * (0.5 + share);
      if (!best || score > best.score) best = { dim, label, tvd, share, score };
    }
  }
  /* 小样本下 share 估计不稳，因此只要「分层构成随开赛顺序明显变化」就触发保护：
     宁可不下训练有效的结论，也不能把版本更替记成进步。 */
  return { counts, confounder: best && best.tvd >= 0.28 ? best : null };
}

/* ── 向量预处理：任何分析都只读这里的派生量 ─────────────────────── */
function prepare(vectors) {
  const rows = (vectors || []).filter((v) => v && v.key).map((v) => {
    const g = Array.isArray(v.g) ? v.g : [];
    const w = Array.isArray(v.w) ? v.w : [];
    return {
      ...v,
      at10: num(v.at10) ? v.at10 : (num(g[2]) ? g[2] : null),
      final: num(v.finalDiff) ? v.finalDiff : null,
      g, w, s: Array.isArray(v.s) ? v.s : [],
      km: num(v.killsOwn) && num(v.killsFoe) ? v.killsOwn - v.killsFoe : null,
      order: v.order || `${v.date || ''} ${v.clock || ''}`,
      lanes: v.lanes || {},
      heroes: Array.isArray(v.heroes) ? v.heroes : [],
      bans: Array.isArray(v.bans) ? v.bans : [],
    };
  });
  const withFinal = rows.filter((r) => num(r.final));
  return { rows, withFinal, n: rows.length, strata: strataProfile(rows) };
}

/* 轨迹特征：6 个检查点 + 终局，标准化后用于形状聚类 */
function shape(r) {
  const pts = (r.s && r.s.length >= 6 ? r.s : r.g.slice(0, 6)).slice(0, 6);
  if (pts.filter(num).length < 4) return null;
  const base = pts.find(num) || 0;
  return pts.map((v) => (num(v) ? v - base : 0));
}
function kmeans(data, k, iters = 24) {
  if (data.length < k) return null;
  const dim = data[0].length;
  const centers = data.filter((_, i) => i % Math.max(1, Math.floor(data.length / k)) === 0).slice(0, k).map((x) => x.slice());
  while (centers.length < k) centers.push(data[centers.length % data.length].slice());
  let assign = new Array(data.length).fill(0);
  for (let t = 0; t < iters; t++) {
    let changed = false;
    data.forEach((row, i) => {
      let best = 0, bd = Infinity;
      centers.forEach((c, j) => { const d = sum(row.map((v, q) => (v - c[q]) ** 2)); if (d < bd) { bd = d; best = j; } });
      if (assign[i] !== best) { assign[i] = best; changed = true; }
    });
    for (let j = 0; j < k; j++) {
      const members = data.filter((_, i) => assign[i] === j);
      if (members.length) centers[j] = Array.from({ length: dim }, (_, q) => mean(members.map((m) => m[q])));
    }
    if (!changed && t > 2) break;
  }
  return { centers, assign };
}
function silhouette(data, assign) {
  const k = new Set(assign).size;
  if (k < 2 || data.length <= k) return 0;
  let total = 0, count = 0;
  data.forEach((row, i) => {
    const dist = (j) => {
      const g2 = data.filter((_, q) => assign[q] === j);
      if (!g2.length) return Infinity;
      return mean(g2.filter((_, q) => q !== i).map((m) => Math.sqrt(sum(row.map((v, z) => (v - m[z]) ** 2)))));
    };
    const a = dist(assign[i]);
    const b = Math.min(...Array.from({ length: k }, (_, j) => j).filter((j) => j !== assign[i]).map(dist));
    if (num(a) && num(b) && Math.max(a, b) > 0) { total += (b - a) / Math.max(a, b); count++; }
  });
  return count ? total / count : 0;
}

/* ── 10 个通用分析族 ───────────────────────────────────────────── */

/* 01 分层基准带：什么叫「正常」 */
function a01(ctx) {
  const { rows, n } = ctx;
  const arr = vals(rows.map((r) => r.at10));
  const sorted = srt(arr);
  const qat = (p) => {
    if (!sorted.length) return null;
    const i = (sorted.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  };
  const q10 = qat(0.1), q25 = qat(0.25), q50 = qat(0.5), q75 = qat(0.75), q90 = qat(0.9);
  const ci = medianCi(arr);
  const byDim = ['version', 'opponent', 'session'].map((dim) => {
    const groups = new Map();
    for (const r of rows) if (num(r.at10)) {
      const k = String(r[dim] || '未标注');
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r.at10);
    }
    const usable = [...groups.entries()].filter(([, v]) => v.length >= 2);
    return { dim, groups: usable.length >= 2 ? usable.sort((a, b) => b[1].length - a[1].length).slice(0, 6) : [] };
  });
  const strata = byDim.flatMap(({ dim, groups }) => groups.map(([label, v]) => ({
    label: `${({ version: '版本', opponent: '对手', session: '训练组' })[dim]} · ${label}`, p50: median(v), n: v.length,
  }))).slice(0, 8);
  const spread = strata.length > 1 ? Math.max(...strata.map((s) => s.p50)) - Math.min(...strata.map((s) => s.p50)) : null;
  const title = spread && Math.abs(spread) > 1500
    ? `同一支队伍，换个对手/版本，10 分钟金差能差 <em>${sign(spread)}</em> 金`
    : `这批 ${n} 局里，10 分钟金差一半在 <em>${sign(q50 || 0)}</em> 金以上`;
  return {
    id: '01', name: '分层基准分析', group: '基准与稳定', ask: '我们这支队，正常水平到底在哪？',
    title,
    plain: spread && Math.abs(spread) > 1500
      ? '所以别拿一个总平均数当标准，要看具体是哪个版本、打哪个对手。'
      : '这条带子就是基线：高于它算打得好，低于它要先找原因。',
    chart: { type: 'bands', lo: q10, p25: q25, p50: q50, p75: q75, hi: q90, strata, noStrata: !strata.length },
    train: `把 ${sign(q25 || 0)} 金定成开局达标线，低于这条线的局单列复盘。`,
    review: '圈出低于达标线的局',
    actKeys: rows.filter((r) => num(r.at10) && r.at10 < (q25 || 0)).map((r) => r.key),
    method: `10 分钟金差 P10/P25/P50/P75/P90；中位 95% 置信区间为 ${ci ? `${sign(ci[0])} ~ ${sign(ci[1])}` : '—'}；分层按版本/对手/训练组，仅列 ≥2 局的分层。`,
    grade: grade(arr.length, ci, q50),
    repro: reproducible(rows.filter((r) => num(r.at10)), (s) => median(s.map((r) => r.at10))),
  };
}

/* 02 波动来源：状态问题还是环境问题 */
function a02(ctx) {
  const { rows } = ctx;
  const parts = varianceParts(rows, 'final', ['version', 'opponent', 'session', 'camp']);
  const top = parts.slice(0, 4).sort((a, b) => b.share - a.share)[0] || { label: '自然波动', share: 0 };
  const natural = parts.find((p) => p.label === '同条件下的自然波动') || { share: 0 };
  const env = sum(parts.slice(0, 4).map((p) => p.share));
  return {
    id: '02', name: '波动来源分析', group: '基准与稳定', ask: '成绩忽高忽低，是队员状态还是对手/版本？',
    title: `终局金差的起伏，<em>${pct(env)}</em> 来自外部条件，其余是局内波动`,
    plain: `其中主要是${top.label}差异（${pct(top.share)}）。${env > 0.3 ? '单看一局金差评价队员状态并不可靠。' : '说明这套打法本身输出比较稳定。'}`,
    chart: { type: 'stack', parts: parts.filter((p) => p.share > 0.005) },
    train: top.share > 0.3
      ? `状态评估改用「同${top.label}内比较」的口径，别再用跨对手的绝对值排名。`
      : '维持当前训练节奏，用同条件内的波动做状态监控。',
    review: '按对手分层核对',
    actKeys: rows.filter((r) => String(r.opponent || '未标注') === String(rows[0] && rows[0].opponent || '')).map((r) => r.key),
    method: '单因素随机效应方差成分：σ²_组间 / (σ²_组间 + σ²_组内)，按调和平均组规模校正；四个分层各算一次后归一，余量归入局内波动。',
    grade: grade(rows.filter((r) => num(r.final)).length),
    repro: null,
  };
}

/* 03 下限风险：比赛日不能赌状态 */
function a03(ctx) {
  const { rows } = ctx;
  const items = LANES.map((lane) => {
    const arr = vals(rows.map((r) => (r.lanes[lane] || {}).gold));
    if (!arr.length) return null;
    const p10 = quantile(arr, 0.1);
    return { label: lane, p10, p50: median(arr), p90: quantile(arr, 0.9), n: arr.length, bad: arr.filter((v) => v < 0).length / arr.length };
  }).filter(Boolean);
  const worst = items.slice().sort((a, b) => a.p10 - b.p10)[0];
  const best = items.slice().sort((a, b) => b.p10 - a.p10)[0];
  const riskKeys = worst ? rows.filter((r) => num((r.lanes[worst.label] || {}).gold) && r.lanes[worst.label].gold < worst.p10).map((r) => r.key) : [];
  return {
    id: '03', name: '下限风险分析', group: '基准与稳定', ask: '比赛日谁最稳、哪一路最可能掉链子？',
    title: `<em>${worst ? worst.label : '—'}</em>下限最低：最差一成局分均 <em>${worst ? sign(worst.p10) : '—'}</em> 金，<em>${worst ? pct(worst.bad) : '—'}</em> 的局对线落后`,
    plain: `教练看的是下限不是均值：${best ? best.label : '—'}最可靠，${worst ? worst.label : '—'}需要预案。`,
    chart: { type: 'range', items },
    train: worst ? `给${worst.label}安排对线专项，并准备轮换/换线预案；目标是让最差的一成局也不落后。` : '补齐分路数据。',
    review: `回看${worst ? worst.label : ''}最差的 ${Math.min(riskKeys.length, 20)} 局`,
    actKeys: riskKeys,
    method: '按分路取「分均经济差」的 P10 / P50 / P90，爆雷率＝该路经济差为负的局占比；上下限用分位数，不受单局极值影响。',
    grade: grade(worst ? worst.n : 0),
    repro: null,
  };
}

/* 04 训练段效应：练了有没有用 */
function a04(ctx) {
  const { rows } = ctx;
  const timed = rows.filter((r) => num(r.at10)).sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
  const k = clamp(Math.floor(timed.length / 12) + 2, 2, 6);
  const segs = Array.from({ length: k }, (_, i) => {
    const part = timed.slice(Math.floor(i * timed.length / k), Math.floor((i + 1) * timed.length / k));
    const arr = vals(part.map((r) => r.at10));
    return { label: `第 ${i + 1} 段`, value: median(arr), lo: null, hi: null, n: arr.length, from: part[0] && part[0].clock, to: part[part.length - 1] && part[part.length - 1].clock, keys: part.map((r) => r.key) };
  });
  const segOf = new Map();
  segs.forEach((s, i) => s.keys.forEach((k) => segOf.set(k, i)));
  const buckets = Array.from({ length: k }, () => []);
  for (const r of timed) { const i = segOf.get(r.key); if (i !== undefined && num(r.at10)) buckets[i].push(r.at10); }
  buckets.forEach((arr, i) => { const ci = medianCi(arr); if (ci) { segs[i].lo = ci[0]; segs[i].hi = ci[1]; } });
  const first = segs[0], last = segs[segs.length - 1];
  const a = vals(timed.slice(0, Math.floor(timed.length / 3)).map((r) => r.at10));
  const b = vals(timed.slice(-Math.floor(timed.length / 3)).map((r) => r.at10));
  const effect = num(first.value) && num(last.value) ? last.value - first.value : null;
  const ci = bootstrapDiff(b, a);
  const delta = cliffs(b, a);
  const conf = ctx.strata && ctx.strata.confounder;
  let within = null;
  if (conf) {
    const layers = new Map();
    for (const r of timed) {
      const k = String(r[conf.dim] || '未标注');
      if (!layers.has(k)) layers.set(k, []);
      layers.get(k).push(r);
    }
    const effects = [];
    for (const list of layers.values()) {
      if (list.length < 6) continue;
      const h = Math.floor(list.length / 3);
      const x = vals(list.slice(0, h).map((r) => r.at10));
      const y = vals(list.slice(-h).map((r) => r.at10));
      if (x.length >= 2 && y.length >= 2) effects.push(median(y) - median(x));
    }
    if (effects.length) within = { effect: median(effects), n: effects.length,
      consistent: effects.every((v) => v > 0) || effects.every((v) => v < 0) };
  }
  const confounded = !!(conf && within && num(effect) && Math.abs(within.effect) < Math.abs(effect) * 0.55);
  const unverifiable = !!(conf && !within);
  const solid = !confounded && !unverifiable && ci && (ci[0] > 0 || ci[1] < 0) && num(delta) && Math.abs(delta) >= 0.2;
  const title = confounded
    ? `整体后段高 <em>${sign(Math.abs(effect))}</em> 金，但同一${conf.label}内只差 <em>${sign(Math.abs(within.effect))}</em> 金`
    : unverifiable
      ? `整体后段高 <em>${sign(Math.abs(effect))}</em> 金，但${conf.label}也在换，先别算训练成效`
    : solid
      ? `练到后段，10 分钟金差${effect > 0 ? '提高' : '回落'} <em>${sign(Math.abs(effect))}</em> 金，这个变化站得住`
      : `前后段相差 <em>${sign(Math.abs(effect || 0))}</em> 金，还分不清是进步还是正常起伏`;
  return {
    id: '04', name: '训练效应分析', group: '进程与效应', ask: '这一阶段练下来，到底有没有变好？',
    flag: (confounded || unverifiable) ? '已做分层校正' : '',
    title,
    plain: confounded
      ? `前后段的${conf.label}构成变了（分布差 ${pct(conf.tvd)}${conf.share > 0.08 ? `、解释 ${pct(conf.share)} 的 10′ 波动` : ''}）；把${conf.label}固定后再比，差距主要来自更替，不能算训练效果。`
      : unverifiable
        ? `前后段的${conf.label}构成明显不同（分布差 ${pct(conf.tvd)}${conf.share > 0.08 ? `、解释 ${pct(conf.share)} 的 10′ 波动` : ''}），但每个${conf.label}内的局还不够做前后对比；先按同一${conf.label}攒局，别把更替记成进步。`
      : solid ? '前后各三分之一对局，差距在统计上能站住，可以据此决定保留或调整这套训练。'
        : '差距落在噪声范围内，别急着下「练有效/没用」的结论，先攒同条件的局。',
    chart: { type: 'segments', items: segs.map(({ keys, ...x }) => x) },
    train: confounded || unverifiable ? `先把${conf.label}固定再评估这套训练；用上方切片单独看同一${conf.label}的局，别把版本更替记成训练成效。`
      : solid && effect > 0 ? '保留后段这套训练内容，下一批沿用同口径再验一次。'
        : solid ? '后段回落，先排查训练强度/阵容变动，暂不推广。' : '继续按同一口径积累样本，下一批用同样方法复验。',
    review: '回看最后一段的局',
    actKeys: last ? last.keys : [],
    method: `按真实开赛时刻均分 ${k} 段比较中位数；首/末三分之一用 Cliff's δ=${num(delta) ? delta.toFixed(2) : '—'} 与固定种子 bootstrap 95% CI ${ci ? `${sign(ci[0])} ~ ${sign(ci[1])}` : '—'} 判读。${conf ? `检测到混淆维度「${conf.label}」（前后半分布差 ${pct(conf.tvd)}${conf.share > 0.08 ? `、解释力 ${pct(conf.share)}` : ''}），${within ? `另在 ${within.n} 个层内各算一次首末差并取中位 ${sign(within.effect)} 金，避免把层间漂移当训练效应` : '但各层局数不足以做层内前后对比，因此不下训练有效结论'}。` : '已检查版本/训练组/对手分层结构，未检出混淆。'}`,
    grade: grade(timed.length, ci, confounded ? (within ? within.effect : effect) : effect),
    repro: reproducible(timed, (s) => { const x = vals(s.map((r) => r.at10)); const h = Math.floor(x.length / 2); return median(x.slice(h)) - median(x.slice(0, h)); }),
  };
}

/* 05 水平变点：从哪一局开始不一样了 */
function a05(ctx) {
  const { rows } = ctx;
  const timed = rows.filter((r) => num(r.at10)).sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
  const buckets = 24;
  const points = Array.from({ length: buckets }, (_, i) => {
    const part = timed.slice(Math.floor(i * timed.length / buckets), Math.max(Math.floor((i + 1) * timed.length / buckets), Math.floor(i * timed.length / buckets) + 1));
    const v = median(part.map((r) => r.at10));
    return { i, v, n: part.length, label: part[0] && (part[0].clock || part[0].date) };
  });
  const vv = vals(points.map((p) => p.v));
  const base = mean(vv), s = sd(vv) || 1;
  let cusum = 0, best = 0, bestAbs = 0;
  points.forEach((p, i) => {
    cusum += num(p.v) ? (p.v - base) / s : 0;
    if (Math.abs(cusum) > bestAbs) { bestAbs = Math.abs(cusum); best = i; }
  });
  const changed = timed.length >= 30 && bestAbs >= 2.2 && best >= 2 && best <= buckets - 3;
  const at = points[best];
  const around = timed.slice(Math.max(0, Math.floor(best / buckets * timed.length) - 3), Math.floor(best / buckets * timed.length) + 4);
  return {
    id: '05', name: '水平变点分析', group: '进程与效应', ask: '水平是从哪一局开始变的？',
    title: changed
      ? `在 <em>${at && (at.label || `第 ${best + 1} 个时间桶`)}</em> 附近出现一次水平${cusum > 0 ? '上移' : '下滑'}`
      : '整批局没有出现稳定的水平跃迁，波动仍在正常范围内',
    plain: changed ? `变点之后水平维持住了，值得回看那几天改了什么。${(ctx.strata && ctx.strata.confounder && ctx.strata.confounder.tvd > 0.3) ? `注意变点附近${ctx.strata.confounder.label}构成也变了，先排除${ctx.strata.confounder.label}因素。` : ''}` : (timed.length < 30 ? '这批局数还不足以区分水平跃迁和正常起伏，别从折线里硬挑转折点。' : '没有可靠变点，波动仍在正常范围内。'),
    chart: { type: 'rolling', points, changeIndex: changed ? best : -1, from: points[0] && points[0].label, to: points[points.length - 1] && points[points.length - 1].label },
    train: changed ? '把变点前后的训练内容做一次对照，确认是哪项调整带来了变化。' : '维持现有节奏，继续按开赛时刻积累，局数够了再看变点。',
    review: changed ? '回看变点前后的 7 局' : '圈出波动最大的时间桶',
    actKeys: changed ? around.map((r) => r.key) : around.map((r) => r.key),
    method: '按开赛时刻压成 24 个等距时间桶（DOM 固定），每桶取中位；对标准化残差做 CUSUM，阈值 2.2 且排除首尾桶才判为变点。',
    grade: grade(timed.length),
    repro: null,
  };
}

/* 06 打法体系：练了几套、哪套最稳 */
function a06(ctx) {
  const { rows } = ctx;
  const data = [], src = [];
  rows.forEach((r) => { const s = shape(r); if (s && num(r.final)) { data.push(s); src.push(r); } });
  let best = null;
  const CAP = 400;
  const fit = data.length > CAP ? data.filter((_, i) => i % Math.ceil(data.length / CAP) === 0) : data;
  if (fit.length >= 8) {
    const maxK = clamp(Math.floor(fit.length / 3), 2, 4);
    for (let k = 2; k <= maxK; k++) {
      const model = kmeans(fit, k);
      if (!model) continue;
      const probe = fit.slice(0, 200);
      const score = silhouette(probe, model.assign.slice(0, probe.length));
      if (!best || score > best.score) best = { ...model, score, k };
    }
  }
  let assign = null;
  if (best) {
    assign = data.map((row) => {
      let bi = 0, bd = Infinity;
      best.centers.forEach((c, j) => { const d = sum(row.map((v, q) => (v - c[q]) ** 2)); if (d < bd) { bd = d; bi = j; } });
      return bi;
    });
  }
  const items = [];
  if (best && assign) {
    for (let j = 0; j < best.k; j++) {
      const members = src.filter((_, i) => assign[i] === j);
      if (!members.length) continue;
      const curve = best.centers[j];
      const finals = vals(members.map((m) => m.final));
      const early = num(curve[2]) ? curve[2] : 0;
      items.push({
        name: early > 1200 ? '开局压制' : early < -800 ? '逆风翻盘' : curve[curve.length - 1] - curve[2] > 2500 ? '后程发力' : '均势拉扯',
        pct: members.length / src.length, n: members.length,
        curve, floor: quantile(finals, 0.1), final: median(finals),
        keys: members.map((m) => m.key), stable: reproducible(members, (s) => median(s.map((r) => r.final))),
      });
    }
  }
  const clustered = items.length > 0;
  if (!clustered) {
    const withBoth = rows.filter((r) => num(r.at10) && num(r.final));
    const cut = median(withBoth.map((r) => r.at10)) || 0;
    for (const [name, list] of [['开局占优', withBoth.filter((r) => r.at10 >= cut)], ['开局受压', withBoth.filter((r) => r.at10 < cut)]]) {
      if (!list.length) continue;
      const finals = vals(list.map((r) => r.final));
      items.push({
        name, pct: list.length / Math.max(1, withBoth.length), n: list.length,
        curve: Array.from({ length: 6 }, (_, i) => mean(list.map((r) => (r.s && num(r.s[i]) ? r.s[i] : 0))) - mean(list.map((r) => (r.s && num(r.s[0]) ? r.s[0] : 0)))),
        floor: quantile(finals, 0.1), final: median(finals), keys: list.map((r) => r.key), stable: null,
      });
    }
  }
  items.sort((a, b) => b.n - a.n);
  const top = items[0];
  const steady = items.slice().sort((a, b) => (b.floor || 0) - (a.floor || 0))[0];
  return {
    id: '06', name: '打法体系分析', group: '结构与归因', ask: '我们到底在练几套打法，哪套最稳？',
    title: !items.length ? '当前局数还不足以分型'
      : clustered ? `${src.length >= 60 ? '稳定识别' : '初步分'}出 <em>${items.length}</em> 套打法，<em>${steady ? steady.name : '—'}</em>下限最高`
        : `按开局态势分出 <em>${items.length}</em> 组，<em>${steady ? steady.name : '—'}</em>下限更高`,
    plain: !items.length ? '分型会在局数足够后自动生效，不会拿几局硬凑出「体系」。'
      : clustered ? `占比最大的是「${top.name}」${pct(top.pct)}；比赛日优先用下限高的那套，不是平均赢最多的那套。`
        : '这不是形状聚类，只是按 10 分钟金差分两组对照；局数够了会自动切成体系识别。',
    chart: { type: 'systems', items: items.slice(0, 4).map(({ keys, ...x }) => x) },
    train: !items.length ? '继续积累同条件对局。'
      : clustered ? `下一阶段固定「${steady ? steady.name : '—'}」为主体系，其余只作针对性备选。`
        : '分组只作对照：把「开局受压」那组的开局处理列成训练项，下一批看这组占比是否下降。',
    review: !items.length ? '圈出偏离度最高的局' : clustered ? `回看「${steady ? steady.name : '—'}」的代表局` : `回看「${steady ? steady.name : '—'}」这一组`,
    actKeys: steady ? steady.keys.slice(0, 60) : [],
    method: `${clustered ? '形状聚类' : '小样本降级：按 10′ 中位分组对照'}；取每局 0%/20%/40%/60%/80%/100% 时长处的金差并去基线（按时长对齐，长短局可比），固定上限 400 条拟合 k-means、按轮廓系数在 k=2..4 中选优，再把全部局按最近中心线性归类；每套给出占比、P10 下限与前后半方向复现。`,
    grade: grade(src.length),
    repro: items.length ? items.filter((x) => x.stable === true).length / items.length : null,
  };
}

/* 07 体系 × 条件：哪套打谁更好 */
function a07(ctx) {
  const { rows } = ctx;
  const scriptOf = (r) => {
    if (!num(r.at10) || !num(r.final)) return '数据不足';
    return r.at10 >= 1500 ? '开局压制' : r.at10 <= -1500 ? '逆风局' : r.final - r.at10 > 3000 ? '后程发力' : '均势拉扯';
  };
  const scripts = [...new Set(rows.map(scriptOf))].filter((s) => s !== '数据不足').slice(0, 4);
  const dims = ['opponent', 'version'];
  let dim = dims.find((d) => new Set(rows.map((r) => r[d] || '未标注')).size > 1) || 'opponent';
  const cols = [...new Set(rows.map((r) => r[dim] || '未标注'))].slice(0, 4);
  const cells = scripts.map((s) => cols.map((c) => {
    const sub = rows.filter((r) => scriptOf(r) === s && (r[dim] || '未标注') === c && num(r.final));
    return { v: median(sub.map((r) => r.final)), n: sub.length, keys: sub.map((r) => r.key) };
  }));
  const flat = cells.flat().filter((c) => c.n >= 2 && num(c.v));
  const hi = flat.slice().sort((a, b) => b.v - a.v)[0];
  const lo = flat.slice().sort((a, b) => a.v - b.v)[0];
  const gap = hi && lo ? hi.v - lo.v : null;
  return {
    id: '07', name: '体系适配分析', group: '结构与归因', ask: '哪套打法，打哪类对手/版本更划算？',
    title: gap && Math.abs(gap) > 1500
      ? `体系 × ${dim === 'opponent' ? '对手' : '版本'}的组合之间，终局金差最多差 <em>${sign(gap)}</em> 金`
      : `各套打法在不同${dim === 'opponent' ? '对手' : '版本'}下表现接近，暂时不用按对手切体系`,
    plain: gap && Math.abs(gap) > 1500 ? '差得最多的是两种组合，赛前准备可以据此选体系，但先核对格子里的局数。' : '当前没有足够证据支持按对手换体系。',
    chart: { type: 'matrix', rows: scripts, cols, cells: cells.map((row) => row.map(({ keys, ...x }) => x)), dimLabel: dim === 'opponent' ? '对手' : '版本' },
    train: gap && Math.abs(gap) > 1500 ? '把「按对手选体系」写进赛前准备清单，并在下一批验证是否成立。' : '维持单一主体系，减少临场切换成本。',
    review: '圈出最优组合的局',
    actKeys: hi ? hi.keys.slice(0, 60) : [],
    method: '按 10 分钟金差把局分为四类节奏，与对手/版本交叉取终局金差中位；每格标注覆盖局数，少于 2 局不参与极值比较。',
    grade: grade(flat.reduce((s, c) => s + c.n, 0)),
    repro: null,
  };
}

/* 08 优势归因：赢下的优势从哪一段、哪一路来 */
function a08(ctx) {
  const { rows } = ctx;
  let segCount = 0;
  for (const r of rows) if (r.w && r.w.length > segCount) segCount = r.w.length;
  segCount = segCount || 8;
  const segs = Array.from({ length: segCount }, (_, k) => {
    const arr = vals(rows.map((r) => r.w[k]));
    return { label: `${k * WINDOW_MIN}–${(k + 1) * WINDOW_MIN}′`, value: median(arr), n: arr.length };
  }).filter((s) => s.n >= 2 && num(s.value));
  const total = sum(segs.map((s) => Math.abs(s.value)));
  const windows = segs.map((s) => ({ ...s, pct: total ? Math.abs(s.value) / total : 0 }));
  const peak = windows.slice().sort((a, b) => b.value - a.value)[0];
  const lanes = LANES.map((lane) => {
    const arr = vals(rows.map((r) => (r.lanes[lane] || {}).damage));
    return { label: lane, pct: arr.length ? median(arr) : 0, n: arr.length };
  });
  const lanePeak = lanes.slice().sort((a, b) => b.pct - a.pct)[0];
  const laneTotal = sum(lanes.map((l) => Math.abs(l.pct)));
  const laneChart = lanes.map((l) => ({ ...l, pct: laneTotal ? Math.abs(l.pct) / laneTotal : 0 }));
  return {
    id: '08', name: '优势归因分析', group: '结构与归因', ask: '优势主要是哪一段、哪一路挣来的？',
    title: peak
      ? `<em>${peak.label}</em> 贡献最大，单段净增 <em>${sign(peak.value)}</em> 金`
      : '各时段贡献接近，没有明显的主胜源',
    plain: peak ? `输出差最突出的是${lanePeak ? lanePeak.label : '—'}，训练资源优先投到这段时间与这条路。` : '别把训练押在单一时段。',
    chart: { type: 'contrib', windows, lanes: laneChart },
    train: peak ? `把 ${String(peak.label).replace('′', ' 分钟')} 的${lanePeak ? lanePeak.label : ''}联动设为主练项，下一批比较这一段的净增有没有提高。` : '保持均衡训练。',
    review: '圈出该段净增最高的局',
    actKeys: (() => { const wi = peak ? windows.indexOf(peak) : 0; return rows.filter((r) => num(r.w[wi])).sort((a, b) => (b.w[wi] || 0) - (a.w[wi] || 0)).slice(0, 30).map((r) => r.key); })(),
    method: `窗口数按本批最长时长动态生成（当前 ${segCount} 段，覆盖到 ${segCount * WINDOW_MIN} 分钟，仅保留有 ≥2 局的段）；每局按 5 分钟窗口取金差净增，跨局取中位后做加性贡献分解；分路用「分均输出差」中位。经济为约 30 秒采样，故最小可信窗口为 5 分钟，不做分钟级因果。`,
    grade: grade(peak ? peak.n : 0),
    repro: reproducible(rows, (s) => { const a = vals(s.map((r) => r.w[2])); const b = vals(s.map((r) => r.w[3])); return median(b) - median(a); }),
  };
}

/* 09 领先守成：优势会不会被还回去 */
function a09(ctx) {
  const { rows } = ctx;
  const pairs = rows.filter((r) => num(r.at10) && num(r.final));
  const ats = vals(pairs.map((r) => r.at10));
  const q1 = quantile(ats, 0.25), q3 = quantile(ats, 0.75);
  const mid = median(ats);
  const state = (v) => (v <= q1 ? 0 : v <= mid ? 1 : v <= q3 ? 2 : 3);
  const names = ['大劣', '小劣', '小优', '大优'];
  const m = Array.from({ length: 4 }, () => [0, 0, 0, 0]);
  const delta = [];
  for (const r of pairs) {
    const s = state(r.at10);
    const e = state(r.final);
    m[s][e]++;
    delta.push({ r, s, e, change: r.final - r.at10 });
  }
  const bigLead = delta.filter((d) => d.s === 3);
  const shrunk = bigLead.filter((d) => d.change < 0);
  const ci = wilson(shrunk.length, bigLead.length);
  const behind = delta.filter((d) => d.s <= 1);
  const recovered = median(behind.map((d) => d.change));
  return {
    id: '09', name: '领先守成分析', group: '状态与决策', ask: '领先之后会不会松？落后还能不能追？',
    title: bigLead.length
      ? `10 分钟大优的 <em>${bigLead.length}</em> 局里，<em>${shrunk.length}</em> 局后半程把优势打小`
      : '暂时没有足够的大优样本判断收官能力',
    plain: `10 分钟落后的局，后半程金差中位变化 ${sign(recovered || 0)} 金；收官是能练的，不是天赋。`,
    chart: { type: 'trans', states: names, m },
    train: shrunk.length && bigLead.length >= 3 ? '把「领先后的收官节奏」列为专项：推进节奏、资源交换与大龙决策。' : '继续积累领先局样本。',
    review: '回看优势被缩小的局',
    actKeys: shrunk.map((d) => d.r.key).slice(0, 60),
    method: `按本批 10 分钟金差的 P25/中位/P75 把每局编为四态，统计到终局的状态转移；优势收窄比例用 Wilson 95% CI ${ci ? `${pct(ci[0])}~${pct(ci[1])}` : '—'}。全胜样本下用连续金差而非胜负，避免结果变量无方差。`,
    grade: grade(bigLead.length, [ci[0] * 100, ci[1] * 100], shrunk.length / Math.max(1, bigLead.length) * 100),
    repro: null,
  };
}

/* 10 复盘队列：明天先看哪一类局 */
function a10(ctx) {
  const { rows } = ctx;
  const keys = ['final', 'at10', 'duration', 'km'];
  const robust = {};
  for (const k of keys) {
    const arr = vals(rows.map((r) => r[k]));
    robust[k] = { m: median(arr), s: mad(arr) || sd(arr) || 1 };
  }
  const scored = rows.map((r) => {
    let d2 = 0, parts = [];
    for (const k of keys) {
      if (!num(r[k])) continue;
      const z = (r[k] - robust[k].m) / (1.4826 * robust[k].s);
      d2 += z * z; parts.push({ k, z });
    }
    return { r, dist: Math.sqrt(d2), parts };
  }).filter((x) => x.dist > 0);
  const cut = quantile(scored.map((x) => x.dist), 0.8) || Infinity;
  const odd = scored.filter((x) => x.dist >= cut);
  const label = (x) => {
    const z = (k) => (x.parts.find((p) => p.k === k) || {}).z || 0;
    if (z('duration') > 1) return '超长拉扯局';
    if (z('at10') < -0.8 && z('final') > 0) return '慢热但翻盘';
    if (z('at10') > 0.8 && z('final') < 0) return '大优掉速';
    if (z('km') < -1) return '人头吃亏但赢下';
    return '多维反常局';
  };
  const groups = new Map();
  for (const x of odd) { const k = label(x); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(x); }
  const items = [...groups.entries()].map(([name, list]) => ({
    name, n: list.length, pct: list.length / Math.max(1, rows.length),
    trait: name === '大优掉速' ? '10 分钟领先明显，终局优势收窄' : name === '慢热但翻盘' ? '开局落后，后程把金差追回' : name === '超长拉扯局' ? '时长明显长于这批局的典型水平' : '多项指标同时偏离本批常态',
    keys: list.map((x) => x.r.key), top: (list.slice().sort((a, b) => b.dist - a.dist)[0] || {}).r?.key || '',
  })).sort((a, b) => b.n - a.n).slice(0, 3);
  const first = items[0];
  return {
    id: '10', name: '复盘队列分析', group: '状态与决策', ask: '明天先复盘哪一类局？',
    title: first
      ? `优先看「<em>${first.name}</em>」这一类的 <em>${first.n}</em> 局`
      : '这批局没有明显成类的反常局',
    plain: first ? '按类型复盘比按单局复盘划算：同一类问题一次改掉，而不是每局各说各话。' : '维持常规复盘节奏。',
    chart: { type: 'types', items: items.map(({ keys, ...x }) => x) },
    train: first ? `把「${first.name}」的共性问题转成一条训练要求，下一批检查该类占比是否下降。` : '维持常规节奏。',
    review: first ? `把 ${first.n} 局排进明天复盘` : '圈出偏离度最高的局',
    actKeys: first ? first.keys.slice(0, 60) : scored.slice().sort((a, b) => b.dist - a.dist).slice(0, 10).map((x) => x.r.key),
    method: '对终局金差 / 10′ 金差 / 时长 / 人头差做 MAD 稳健标准化，取距离前 20% 的局，按主导偏离方向归为类型；类型按占比排序，不给单例结论。',
    grade: grade(odd.length),
    repro: null,
  };
}

/* ── 对外入口 ─────────────────────────────────────────────────── */
export function analyzeCohort(vectors) {
  const ctx = prepare(vectors);
  const cards = ctx.n ? [a01, a02, a03, a04, a05, a06, a07, a08, a09, a10].map((f) => {
    try { return f(ctx); } catch { return null; }
  }).filter(Boolean) : [];
  const checked = cards.filter((c) => c.repro !== null && c.repro !== undefined);
  const held = checked.filter((c) => c.repro === true).length;
  return {
    cards,
    total: ctx.n,
    audit: {
      checked: checked.length,
      held,
      rate: checked.length ? held / checked.length : null,
      strong: cards.filter((c) => c.grade.level === 2).length,
      lead: cards.filter((c) => c.grade.level === 1).length,
      thin: cards.filter((c) => c.grade.level === 0).length,
      strata: { ...ctx.strata, total: ctx.n },
    },
  };
}

export const cohortLanes = LANES;
