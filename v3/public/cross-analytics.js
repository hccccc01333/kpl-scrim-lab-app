/* 通用跨局分析内核（与 DOM 无关、与局数无关）
 * 输入：全量对局的轻量向量数组（后端 /api/cross/vectors 一次给出）
 * 输出：固定 10 张结论卡 + 一条审计读数；所有图的数据点数恒定，不随 N 增长。
 *
 * 设计前提：结论必须基于「总体分布 + 分层 + 效应量 + 可复现性」，
 * 不能是「这 11 局里挑一局讲故事」。N=11 与 N=30000 走同一套计算，
 * 区别只在置信区间宽度与分级标签，不在代码路径。
 */

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

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
const mmss = (s) => {
  const v = Math.max(0, Math.round(num(s) ? s : 0));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
};

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

/* 01 共性：把这一个月的局并在一起，反复出现的特征是什么 */
function a01(ctx) {
  const { rows } = ctx;
  const timed = rows.slice().sort(byOrder);
  const withAt10 = rows.filter((r) => num(r.at10));
  const lead = withAt10.filter((r) => r.at10 > 0).length;
  const decided = rows.filter((r) => r.result === 'win' || r.result === 'loss');
  const wins = decided.filter((r) => r.result === 'win').length;
  const laneShare = LANES.map((lane) => {
    const arr = rows.map((r) => (r.lanes[lane] || {}).gold).filter(num);
    return { lane, n: arr.length, share: arr.length ? arr.filter((v) => v > 0).length / arr.length : null };
  }).filter((x) => x.n >= 2 && x.share != null);
  const best = laneShare.slice().sort((a, b) => b.share - a.share)[0];
  const worst = laneShare.slice().sort((a, b) => a.share - b.share)[0];
  const durMed = median(vals(rows.map((r) => r.duration)));
  const items = timed.map((r, i) => ({
    label: r.date ? String(r.date).slice(5) : (r.clock || ''),
    value: num(r.at10) ? r.at10 : null,
    result: r.result,
    sub: String(r.opponent || '').trim(),
    time: r.clock || '',
    at: i + 1,
    key: r.key,
  }));
  return {
    id: '01', name: '共性', group: '这段时间', ask: '这一个月的局并在一起，反复出现的是什么？',
    title: withAt10.length
      ? `这 ${rows.length} 局里，<em>${withAt10.length}</em> 局有 10 分钟经济，其中 <em>${lead}</em> 局领先`
      : `这 ${rows.length} 局还没有可读的 10 分钟经济`,
    plain: best && worst
      ? `五路里最稳的是${best.lane}（${pct(best.share)} 的局领先），最不稳的是${worst.lane}（${pct(worst.share)}）。典型一局打 ${mmss(durMed)}。`
      : '分路样本还不够，先把对局补全。',
    chart: { type: 'scatter', items },
    train: worst ? `把「${worst.lane}领先率」定成这个月的训练指标：现在 ${pct(worst.share)}，下一批看能不能过 50%。` : '先把分路数据补齐。',
    review: '按时间看这一批局',
    actKeys: timed.slice(0, 60).map((r) => r.key),
    method: '每局一格、按开赛时间排；格子颜色＝这一局 10 分钟经济差（本队减对手），灰＝这一局没有可读的经济曲线。五路领先率＝该路经济差为正的局占比。',
    grade: grade(withAt10.length),
    repro: null,
  };
}

/* 02 赢输对比：赢的局和输的局，差在哪一项 */
function a02(ctx) {
  const { rows } = ctx;
  const win = rows.filter((r) => r.result === 'win');
  const loss = rows.filter((r) => r.result === 'loss');
  const agg = (list, get) => median(vals(list.map(get)));
  const laneGold = (list, lane) => agg(list, (r) => (r.lanes[lane] || {}).gold);
  const killOf = (r) => (num(r.killsOwn) && num(r.killsFoe) ? r.killsOwn - r.killsFoe : null);
  const fmt = (v, unit) => {
    if (!num(v)) return '—';
    if (unit === 'pm') return `${sign(v)} 金币/分`;
    if (unit === 'gold') return `${sign(v)} 金币`;
    return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v))} 个`;
  };
  const item = (label, get, unit) => {
    const w = agg(win, get), l = agg(loss, get);
    return { label, win: w, loss: l, winText: fmt(w, unit), lossText: fmt(l, unit) };
  };
  const at10 = item('10 分钟经济差', (r) => r.at10, 'gold');
  const items = [
    at10,
    item('终局经济差', (r) => r.finalDiff, 'gold'),
    item('人头差', killOf, 'kill'),
    ...LANES.map((lane) => item(`${lane}（每分钟）`, (r) => (r.lanes[lane] || {}).gold, 'pm')),
  ];
  const laneRows = LANES.map((lane) => ({ lane, win: laneGold(win, lane), loss: laneGold(loss, lane) }));
  const worstLane = laneRows.slice().sort((a, b) => Math.abs((b.win || 0) - (b.loss || 0)) - Math.abs((a.win || 0) - (a.loss || 0)))[0];
  const allNeg = laneRows.every((x) => num(x.loss) && x.loss < 0);
  const allPos = laneRows.every((x) => num(x.win) && x.win > 0);
  const decided = win.length + loss.length;
  return {
    id: '02', name: '赢输对比', group: '这段时间', ask: '赢的局和输的局，差在哪一项？',
    title: decided
      ? `赢的 ${win.length} 局，10 分钟就领先 <em>${sign(at10.win || 0)}</em> 金币；输的 ${loss.length} 局，10 分钟落后 <em>${Math.abs(Math.round(at10.loss || 0)).toLocaleString('zh-CN')}</em> 金币`
      : '还没有标了胜负的局',
    plain: decided
      ? `${allNeg && allPos ? '赢的局五路金币全是正的，输的局五路全是负的' : '五路金币在赢、输两边互有正负'}；差得最多的是${worstLane ? worstLane.lane : '—'}${worstLane ? `（每分钟 ${sign(worstLane.win || 0)} 对 ${sign(worstLane.loss || 0)}）` : ''}。`
      : '',
    chart: { type: 'compare', items, winN: win.length, lossN: loss.length },
    train: worstLane
      ? `${worstLane.lane}是这一个月差得最多的一路，下一批先把它的开局和资源处理列成专项。`
      : '先把胜负标全。',
    review: `看输的 ${loss.length} 局`,
    actKeys: loss.slice(0, 60).map((r) => r.key),
    method: '把局按胜负分成两组，同一个项目左右并排比：取两组的典型值，金币一律是本队减对手。只算标了胜负的局，没标胜负的不进对比。',
    grade: grade(decided),
    repro: null,
  };
}

/* 03 下限风险：比赛日谁最稳、哪一路最可能掉链子 */
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
    title: `<em>${worst ? worst.label : '—'}</em> 最容易崩：<em>${worst ? pct(worst.bad) : '—'}</em> 的局这条线落后，最差的几局到 <em>${worst ? sign(worst.p10) : '—'}</em> 金币/分钟`,
    plain: `教练看的是下限不是平均：${best ? best.label : '—'}最稳，${worst ? worst.label : '—'}要提前准备预案。`,
    chart: { type: 'range', items },
    train: worst ? `给${worst.label}安排对线专项，并准备轮换/换线预案；目标是让最差10%对局也不落后。` : '补齐分路数据。',
    review: `看${worst ? worst.label : ''}最差的 ${Math.min(riskKeys.length, 20)} 局`,
    actKeys: riskKeys,
    method: '按分路取「分均经济差」的 P10 / P50 / P90，爆雷率＝该路经济差为负的局占比；上下限用分位数，不受单局极值影响。',
    grade: grade(worst ? worst.n : 0),
    repro: null,
  };
}

/* 04 突出点：打得最顺和最难的局，差在哪一段 */
function a04(ctx) {
  const { rows } = ctx;
  const scored = rows.filter((r) => num(r.at10)).sort((a, b) => b.at10 - a.at10);
  if (scored.length < 6) {
    return {
      id: '04', name: '突出点', group: '这段时间', ask: '打得好和打不动的局差在哪？',
      title: '局数还不够分出「最顺」和「最难」', plain: '至少要有 6 局可读的 10 分钟经济。',
      chart: { type: 'timeline', items: [] }, train: '继续攒局。', review: '看这一批局', actKeys: [],
      method: '按 10 分钟经济差排序，取前后各 5 局。', grade: grade(scored.length), repro: null,
    };
  }
  const k = Math.min(5, Math.max(2, Math.floor(scored.length / 4)));
  const best = scored.slice(0, k);
  const worst = scored.slice(-k).reverse();
  const floorBest = best[best.length - 1].at10;
  const ceilWorst = worst[0].at10;
  const seg = (list, key) => median(list.map((r) => (r.seg || {})[key]).filter(num));
  const bestEarly = seg(best, 'early'), bestMid = seg(best, 'mid');
  const worstEarly = seg(worst, 'early'), worstMid = seg(worst, 'mid');
  const pack = (list, tone) => list.map((r) => ({
    label: `${r.date ? String(r.date).slice(5) : ''} ${String(r.opponent || '').trim() || '未填对手'}`.trim(),
    value: Math.round(r.at10),
    sub: r.result === 'win' ? '胜' : r.result === 'loss' ? '负' : '',
    key: r.key, tone,
  }));
  return {
    id: '04', name: '突出点', group: '这段时间', ask: '打得最顺和最难的局，差在哪一段？',
    title: `最顺的 ${k} 局，10 分钟都在 <em>${sign(floorBest)}</em> 以上；最难的 ${k} 局，都在 <em>${sign(ceilWorst)}</em> 以下`,
    plain: `最顺的一批，对线期就 ${sign(bestEarly)}、发育期再 ${sign(bestMid)}；最难的一批，对线期 ${sign(worstEarly)}、发育期 ${sign(worstMid)}。`,
    chart: { type: 'split', left: { label: `最顺的 ${k} 局`, items: pack(best, 'pos') }, right: { label: `最难的 ${k} 局`, items: pack(worst, 'neg') } },
    train: worstMid != null && worstMid < 0
      ? '最难的一批主要输在发育期：把 4–10 分钟的资源交换列成专项，比换阵容更直接。'
      : '把最顺那批的开局处理抄成模板，下一批复现。',
    review: `看这 ${k * 2} 局`,
    actKeys: [...best, ...worst].map((r) => r.key),
    method: '按 10 分钟经济差排序取最顺/最难各几局（最多 5 局），再把每局拆成 0–4 / 4–10 / 10 分钟后三段的净增，看差在哪一段。',
    grade: grade(scored.length),
    repro: null,
  };
}

/* 05 异常点：过程和结果对不上的局，最该先复盘 */
function a05(ctx) {
  const { rows } = ctx;
  const durs = vals(rows.map((r) => r.duration));
  const durQ3 = quantile(durs, 0.75);
  const groups = [
    { name: '逆风赢', trait: '10 分钟落后，最后赢了', test: (r) => r.result === 'win' && num(r.at10) && r.at10 < 0 },
    { name: '领先被翻', trait: '10 分钟领先，最后输了', test: (r) => r.result === 'loss' && num(r.at10) && r.at10 > 0 },
    { name: '超长', trait: '时长明显长于这批局', test: (r) => num(r.duration) && num(durQ3) && r.duration > durQ3 * 1.25 },
  ];
  const items = groups.map((g) => {
    const list = rows.filter(g.test);
    return { name: g.name, trait: g.trait, n: list.length, pct: rows.length ? list.length / rows.length : 0, keys: list.map((r) => r.key), top: list[0] ? list[0].key : '' };
  }).filter((x) => x.n > 0).sort((a, b) => b.n - a.n);
  const total = items.reduce((s, x) => s + x.n, 0);
  const leadFlip = items.find((x) => x.name === '领先被翻');
  const comeback = items.find((x) => x.name === '逆风赢');
  return {
    id: '05', name: '异常点', group: '这段时间', ask: '哪几局的走向和结果对不上？',
    title: total
      ? `有 <em>${total}</em> 局不正常：${items.map((x) => `${x.n} 局${x.name}`).join('、')}`
      : '这批局没有明显不正常的局',
    plain: total
      ? `${items.map((x) => `${x.name} ${x.n} 局（${x.trait}）`).join('；')}。这几局最该先看。`
      : '过程和结果一致，按常规复盘节奏走。',
    chart: { type: 'types', items },
    train: items[0] && items[0].name === '超长'
      ? '超长局最多，先练收尾：推进节奏、大龙决策，别把优势拖成拉锯。'
      : (leadFlip && leadFlip.n ? '把「领先后的 10 分钟」单列成一课：资源交换、大龙决策、推进节奏。' : '保持常规复盘。'),
    review: '看这几局',
    actKeys: items.flatMap((x) => x.keys).slice(0, 60),
    method: '按胜负与 10 分钟经济差的方向判断背离：赢了但 10 分钟落后＝逆风赢；输了但 10 分钟领先＝领先被翻；时长超过这批局上四分位的 1.25 倍＝超长局。',
    grade: grade(rows.length),
    repro: null,
  };
}

/* 03 下限风险：比赛日不能赌状态 */

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
    title: !items.length ? '当前局数还不足以分类'
      : clustered ? `按经济走势，这 ${src.length} 局分成 <em>${items.length}</em> 类，<em>${steady ? steady.name : '—'}</em> 的下限最高`
        : `按开局态势分成 <em>${items.length}</em> 组，<em>${steady ? steady.name : '—'}</em> 的下限更高`,
    plain: !items.length ? '局数够了会自动分类，不会拿几局硬凑出「体系」。'
      : clustered ? `占比最大的是「${top.name}」${pct(top.pct)}。这一类是按经济曲线走向分的，不等于具体阵容；比赛日优先用下限高的那一类，不是平均赢得多的。`
        : '这里只是按 10 分钟经济差分两组对照，不是分体系；局数够了会自动切成按走势分类。',
    chart: { type: 'systems', items: items.slice(0, 4).map(({ keys, ...x }) => x) },
    train: !items.length ? '继续积累同条件对局。'
      : clustered ? `下一阶段固定「${steady ? steady.name : '—'}」为主打法，其余只作针对性备选。`
        : '分组只作对照：把「开局受压」那组的开局处理列成训练项，下一批看这组占比是否下降。',
    review: !items.length ? '看偏离度最高的局' : clustered ? `看「${steady ? steady.name : '—'}」的代表局` : `看「${steady ? steady.name : '—'}」这一组`,
    actKeys: steady ? steady.keys.slice(0, 60) : [],
    method: `${clustered ? '形状聚类' : '小样本降级：按 10′ 中位分组对照'}；取每局 0%/20%/40%/60%/80%/100% 时长处的经济差并去基线（按时长对齐，长短局可比），固定上限 400 条拟合 k-means、按轮廓系数在 k=2..4 中选优，再把全部局按最近中心线性归类；每套给出占比、P10 下限与前后半方向复现。`,
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
      ? `同样这套打法，打不同的${dim === 'opponent' ? '对手' : '版本'}，终局经济差最多差 <em>${sign(Math.abs(gap))}</em> 金币`
      : `各套打法在不同${dim === 'opponent' ? '对手' : '版本'}下表现接近，暂时不用换`,
    plain: gap && Math.abs(gap) > 1500 ? '差得最多的是两种打法，赛前准备可以据此排；先看格子里的局数够不够。' : '当前没有足够证据支持按对手换打法。',
    chart: { type: 'matrix', rows: scripts, cols, cells: cells.map((row) => row.map(({ keys, ...x }) => x)), dimLabel: dim === 'opponent' ? '对手' : '版本' },
    train: gap && Math.abs(gap) > 1500 ? '把「按对手选体系」写进赛前准备清单，并在下一批验证是否成立。' : '维持单一主体系，减少临场切换成本。',
    review: '圈出最优组合的局',
    actKeys: hi ? hi.keys.slice(0, 60) : [],
    method: '按 10 分钟经济差把局分为四类节奏，与对手/版本交叉取终局经济差中位；每格标注覆盖局数，少于 2 局不参与极值比较。',
    grade: grade(flat.reduce((s, c) => s + c.n, 0)),
    repro: null,
  };
}

/* 08 优势归因：优势是哪一段、哪一路挣来的 —— 段用教练口径 0–4 / 4–10 / 10+ */
const PHASES = [
  { key: 'early', label: '0–4 对线期' },
  { key: 'mid', label: '4–10 发育期' },
  { key: 'late', label: '10 分钟后' },
];
function a08(ctx) {
  const { rows } = ctx;
  const segs = PHASES.map((p) => {
    const arr = vals(rows.map((r) => (r.seg || {})[p.key]));
    return { key: p.key, label: p.label, value: arr.length ? median(arr) : null, n: arr.length };
  }).filter((s) => s.n >= 2 && num(s.value));
  const total = sum(segs.map((s) => Math.abs(s.value)));
  const windows = segs.map((s) => ({ ...s, pct: total ? Math.abs(s.value) / total : 0 }));
  const peak = windows.slice().sort((a, b) => b.value - a.value)[0];
  const worst = windows.slice().sort((a, b) => a.value - b.value)[0];
  const lanes = LANES.map((lane) => {
    const arr = vals(rows.map((r) => (r.lanes[lane] || {}).damage));
    return { label: lane, pct: arr.length ? median(arr) : 0, n: arr.length };
  });
  const lanePeak = lanes.slice().sort((a, b) => b.pct - a.pct)[0];
  const laneTotal = sum(lanes.map((l) => Math.abs(l.pct)));
  const laneChart = lanes.map((l) => ({ ...l, pct: laneTotal ? Math.abs(l.pct) / laneTotal : 0 }));
  const early = windows.find((w) => w.key === 'early');
  const late = windows.find((w) => w.key === 'late');
  return {
    id: '08', name: '优势归因分析', group: '结构与归因', ask: '优势是哪一段、哪一路挣来的？',
    title: peak
      ? `${peak.label} 拉开最多：这段平均多 <em>${sign(peak.value)}</em> 金币${worst && worst.value < 0 ? `；${worst.label} 反而被追回 <em>${sign(Math.abs(worst.value))}</em>` : ''}`
      : '三个阶段贡献接近，没有明显的主胜段',
    plain: peak
      ? `${early && late ? `对线期${early.value >= 0 ? '小赚' : '吃亏'} ${sign(early.value)}、后期${late.value >= 0 ? '继续扩大' : '被追回'} ${sign(late.value)}。` : ''}输出差最突出的是${lanePeak ? lanePeak.label : '—'}。`
      : '别把训练押在单一时段。',
    chart: { type: 'contrib', windows, lanes: laneChart },
    train: peak ? `把「${peak.label}」的${lanePeak ? lanePeak.label : ''}处理设为主练项，下一批比较这一段净增有没有提高。` : '保持均衡训练。',
    review: '看这一段净增最高的局',
    actKeys: (() => { const k = peak ? peak.key : 'early'; return rows.filter((r) => num((r.seg || {})[k])).sort((a, b) => ((b.seg || {})[k] || 0) - ((a.seg || {})[k] || 0)).slice(0, 30).map((r) => r.key); })(),
    method: '按教练口径切三段：0–4 对线、4–10 发育、10 分钟后；每局取三段的经济差净增，跨局取典型值。营地经济序列约 30 秒一点，240 秒与 600 秒的值由插值得到，误差约 ±15 秒，所以只说「这一段」不说具体哪一分钟。分路用「分均输出差」的典型值。',
    grade: grade(peak ? peak.n : 0),
    repro: reproducible(rows, (s) => {
      const a = vals(s.map((r) => (r.seg || {}).mid));
      const b = vals(s.map((r) => (r.seg || {}).late));
      return median(b) - median(a);
    }),
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
    plain: `10 分钟落后的局，后半程经济差典型变化 ${sign(recovered || 0)} 金币；收官是能练的，不是天赋。`,
    chart: { type: 'trans', states: names, m },
    train: shrunk.length && bigLead.length >= 3 ? '把「领先后的收官节奏」列为专项：推进节奏、资源交换与大龙决策。' : '继续积累领先局样本。',
    review: '回看优势被缩小的局',
    actKeys: shrunk.map((d) => d.r.key).slice(0, 60),
    method: `按本批 10 分钟经济差的 P25/中位/P75 把每局编为四态，统计到终局的状态转移；优势收窄比例用 Wilson 95% CI ${ci ? `${pct(ci[0])}~${pct(ci[1])}` : '—'}。全胜样本下用连续经济差而非胜负，避免结果变量无方差。`,
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
    return '整体偏离';
  };
  const groups = new Map();
  for (const x of odd) { const k = label(x); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(x); }
  const items = [...groups.entries()].map(([name, list]) => ({
    name, n: list.length, pct: list.length / Math.max(1, rows.length),
    trait: name === '大优掉速' ? '10 分钟领先明显，终局优势收窄' : name === '慢热但翻盘' ? '开局落后，后程把经济差追回' : name === '超长拉扯局' ? '时长明显长于这批局的典型水平' : '多项指标同时偏离本批常态',
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
    method: '对终局经济差 / 10′ 经济差 / 时长 / 人头差做 MAD 稳健标准化，取距离前 20% 的局，按主导偏离方向归为类型；类型按占比排序，不给单例结论。',
    grade: grade(odd.length),
    repro: null,
  };
}

/* 11 英雄账本：我们选过的英雄，哪个真赢 */
function a11(ctx) {
  const { rows } = ctx;
  const map = new Map();
  for (const r of rows) {
    for (const hero of (Array.isArray(r.heroes) ? r.heroes : [])) {
      const e = map.get(hero) || { hero, games: 0, wins: 0, decided: 0, at10: [], keys: [] };
      e.games += 1;
      e.keys.push(r.key);
      if (r.result === 'win') e.wins += 1;
      if (r.result === 'win' || r.result === 'loss') e.decided += 1;
      if (num(r.at10)) e.at10.push(r.at10);
      map.set(hero, e);
    }
  }
  const items = [...map.values()]
    .sort((a, b) => b.games - a.games || b.wins - a.wins)
    .slice(0, 8)
    .map((e) => ({
      label: e.hero, games: e.games, wins: e.wins, decided: e.decided,
      rate: e.decided ? e.wins / e.decided : null,
      at10: e.at10.length ? median(e.at10) : null, keys: e.keys,
    }));
  const top = items[0];
  const ranked = items.filter((x) => x.decided >= 2).sort((a, b) => (b.rate || 0) - (a.rate || 0));
  const best = ranked[0], worst = ranked[ranked.length - 1];
  const noWin = items.filter((x) => x.decided >= 2 && x.wins === 0);
  const played = map.size;
  return {
    id: '11', name: '英雄账本', group: 'BP 与阵容', ask: '我们选过的英雄，哪个真赢、哪个白选？',
    title: top
      ? `选得最多的是 <em>${top.label}</em>（${top.games} 局 ${top.wins} 胜）${best && best.label !== top.label ? `，最能赢的是 <em>${best.label}</em> ${best.wins}/${best.decided}` : ''}`
      : '这批局还没记到阵容',
    plain: noWin.length
      ? `「${noWin.map((x) => x.label).join('、')}」一局没赢，要么换 pick，要么先看是不是被这套阵容克制。`
      : ranked.length ? `胜率从 ${pct(best.rate)} 到 ${pct(worst.rate)}，pick 之间的差距是实打实的。` : '有胜负的样本还少，先别用这张表定死 pick。',
    chart: { type: 'ledger', items: items.map(({ keys, ...x }) => x), total: played },
    train: best ? `把「${best.label}」排进主练体系；「${worst ? worst.label : '—'}」先查是不是被克制，别直接弃用。` : '继续攒局。',
    review: '看这些局的阵容',
    actKeys: top ? top.keys : [],
    method: '按我方五人阵容里的英雄计局；胜负只算有结果的局，没标胜负的局只进场次不进胜率。',
    grade: grade(items.length ? items.reduce((s, x) => s + x.games, 0) / items.length : 0),
    repro: null,
  };
}

/* 12 对手账本：对谁打得顺、对谁吃力 */
function a12(ctx) {
  const { rows } = ctx;
  const map = new Map();
  for (const r of rows) {
    const name = String(r.opponent || '').trim() || '未标注对手';
    const e = map.get(name) || { name, games: 0, wins: 0, decided: 0, at10: [], dur: [], keys: [] };
    e.games += 1;
    e.keys.push(r.key);
    if (r.result === 'win') e.wins += 1;
    if (r.result === 'win' || r.result === 'loss') e.decided += 1;
    if (num(r.at10)) e.at10.push(r.at10);
    if (num(r.duration)) e.dur.push(r.duration);
    map.set(name, e);
  }
  const items = [...map.values()]
    .sort((a, b) => b.games - a.games)
    .slice(0, 8)
    .map((e) => ({
      label: e.name, games: e.games, wins: e.wins, decided: e.decided,
      rate: e.decided ? e.wins / e.decided : null,
      at10: e.at10.length ? median(e.at10) : null, dur: e.dur.length ? mean(e.dur) : null,
      keys: e.keys,
    }));
  const ranked = items.filter((x) => x.decided >= 2).sort((a, b) => (b.rate || 0) - (a.rate || 0));
  const easy = ranked[0], hard = ranked[ranked.length - 1];
  const unknown = items.find((x) => x.label === '未标注对手');
  return {
    id: '12', name: '对手账本', group: '对手', ask: '我们对谁打得顺、对谁一直吃力？',
    title: easy && hard && easy.label !== hard.label
      ? `对 <em>${easy.label}</em> 最顺（${easy.wins}/${easy.decided} 胜）${easy.at10 != null ? `、10 分钟 ${sign(easy.at10)} 金币` : ''}；对 <em>${hard.label}</em> 最吃力（${hard.wins}/${hard.decided} 胜）`
      : `这批对局来自 ${items.length} 个对手，样本还没拉开差距`,
    plain: unknown
      ? `有 ${unknown.games} 局还没填对手名，那部分进不了账本——在「对局档案」补上队名就能算进来。`
      : '同一个对手打得多了，这张表就能看出他们的惯用打法。',
    chart: { type: 'ledger', items: items.map(({ keys, ...x }) => x), total: items.length },
    train: hard ? `下一场准备先按「打 ${hard.label}」做针对性 BP；对 ${easy.label} 保持现有方案。` : '继续补对手名。',
    review: hard ? `看对 ${hard.label} 的局` : '看这批对局',
    actKeys: hard ? hard.keys : [],
    method: '按对手名分组；胜负只算有结果的局，10 分钟经济差取中位，时长为平均值。',
    grade: grade(rows.filter((r) => String(r.opponent || '').trim()).length),
    repro: null,
  };
}

/* ── 对外入口 ─────────────────────────────────────────────────── */
/* 13 资源与推塔：控龙、推塔，赢的局和输的局差多少 */
function a13(ctx) {
  const { rows } = ctx;
  const withObj = rows.filter((r) => r.obj && num(r.obj.dragonOwn) && num(r.obj.dragonFoe));
  const win = withObj.filter((r) => r.result === 'win');
  const loss = withObj.filter((r) => r.result === 'loss');
  const rateOf = (r) => {
    const t = (r.obj ? r.obj.dragonOwn + r.obj.dragonFoe : 0);
    return t ? r.obj.dragonOwn / t : null;
  };
  const avg = (list, get) => {
    const a = vals(list.map(get));
    return a.length ? mean(a) : null;
  };
  const fmtV = (v, unit) => (!num(v) ? '—' : unit === '%' ? `${Math.round(v)}%` : unit === '座' || unit === '条' ? `${v.toFixed(1)} ${unit}` : `${v.toFixed(1)} ${unit}`);
  const mk = (label, get, unit) => ({
    label,
    win: avg(win, get),
    loss: avg(loss, get),
    winText: fmtV(avg(win, get), unit),
    lossText: fmtV(avg(loss, get), unit),
  });
  const rate = (r) => {
    const v = rateOf(r);
    return v == null ? null : v * 100;
  };
  const rateGroup = (list) => {
    const o = sum(list.map((r) => (r.obj ? r.obj.dragonOwn : 0)));
    const f = sum(list.map((r) => (r.obj ? r.obj.dragonFoe : 0)));
    return o + f ? o / (o + f) * 100 : null;
  };
  const items = [
    { label: '控龙率', win: rateGroup(win), loss: rateGroup(loss), winText: fmtV(rateGroup(win), '%'), lossText: fmtV(rateGroup(loss), '%') },
    mk('场均拿龙', (r) => (r.obj ? r.obj.dragonOwn : null), '条'),
    mk('场均丢龙', (r) => (r.obj ? r.obj.dragonFoe : null), '条'),
    mk('场均推塔', (r) => (r.obj ? r.obj.towerOwn : null), '座'),
    mk('场均被推塔', (r) => (r.obj ? r.obj.towerFoe : null), '座'),
  ];
  const allRate = vals(withObj.map((r) => rateGroup([r])));
  const ownSum = sum(withObj.map((r) => r.obj.dragonOwn));
  const foeSum = sum(withObj.map((r) => r.obj.dragonFoe));
  const overallRate = rateGroup(withObj);
  const towerAvg = avg(withObj, (r) => r.obj.towerOwn);
  return {
    id: '13', name: '资源与推塔', group: '资源与团战', ask: '龙和塔，我们控得住吗？',
    title: num(overallRate)
      ? `控龙率 <em>${Math.round(overallRate)}%</em>：这 ${withObj.length} 局拿了 <em>${ownSum}</em> 条龙、丢了 <em>${foeSum}</em> 条`
      : '还没有可读的资源数据（需要关联官方回放）',
    plain: num(overallRate)
      ? `赢的局控龙 ${items[0].winText}、推 ${items[3].winText}；输的局控龙 ${items[0].lossText}、推 ${items[3].lossText}。`
      : '在「采集 → 通道校对」里给对局挂上官方回放，这项才有数。',
    chart: { type: 'compare', hero: { value: num(overallRate) ? `${Math.round(overallRate)}%` : '—', label: '控龙率', cls: 'gold' }, items, winN: win.length, lossN: loss.length },
    train: num(overallRate) && overallRate >= 60
      ? `控龙率已经 ${Math.round(overallRate)}%，下一批守住这个数；重点转到「优势转推进」：场均 ${num(towerAvg) ? towerAvg.toFixed(1) : '—'} 座塔还能再多。`
      : `控龙率 ${num(overallRate) ? Math.round(overallRate) : '—'}% 偏低：把开局 2 分钟第一条龙前的站位和惩戒伤害列成专项。`,
    review: '看输的局',
    actKeys: loss.slice(0, 60).map((r) => r.key),
    method: '从回放事件里数龙和塔：暴君/暗影暴君/暗影主宰/风暴龙王算龙，防御塔和水晶算塔，按拿到的一方计。只算有回放的局。',
    grade: grade(withObj.length),
    repro: null,
  };
}

/* 14 死亡与团战：死多少、打几波团、团战赢几波 */
function a14(ctx) {
  const { rows } = ctx;
  const withDeath = rows.filter((r) => r.death && num(r.death.own));
  const withFight = rows.filter((r) => r.fight && num(r.fight.n));
  const win = rows.filter((r) => r.result === 'win');
  const loss = rows.filter((r) => r.result === 'loss');
  const avg = (list, get) => {
    const a = vals(list.map(get));
    return a.length ? mean(a) : null;
  };
  const fmtV = (v, unit) => (!num(v) ? '—' : unit === '%' ? `${Math.round(v)}%` : `${v.toFixed(1)} ${unit}`);
  const mk = (label, get, unit) => ({
    label,
    win: avg(win, get),
    loss: avg(loss, get),
    winText: fmtV(avg(win, get), unit),
    lossText: fmtV(avg(loss, get), unit),
  });
  const fightRate = (r) => (r.fight && num(r.fight.n) && num(r.fight.win) ? r.fight.win / r.fight.n * 100 : null);
  const fightGroup = (list) => {
    const n = sum(list.map((r) => (r.fight ? r.fight.n : 0)));
    const w = sum(list.map((r) => (r.fight ? r.fight.win : 0)));
    return n ? w / n * 100 : null;
  };
  const items = [
    mk('场均死亡', (r) => (r.death ? r.death.own : null), '次'),
    mk('场均击杀', (r) => (r.death ? r.death.foe : null), '次'),
    mk('场均团战', (r) => (r.fight ? r.fight.n : null), '波'),
    { label: '团战胜率', win: fightGroup(win), loss: fightGroup(loss), winText: fmtV(fightGroup(win), '%'), lossText: fmtV(fightGroup(loss), '%') },
    mk('反野', (r) => (r.buff ? r.buff.anti : null), '次'),
    mk('被反野', (r) => (r.buff ? r.buff.stolen : null), '次'),
  ];
  const deathAvg = avg(withDeath, (r) => r.death.own);
  const winDeath = avg(win, (r) => (r.death ? r.death.own : null));
  const lossDeath = avg(loss, (r) => (r.death ? r.death.own : null));
  const overallFight = fightGroup(withFight);
  return {
    id: '14', name: '死亡与团战', group: '资源与团战', ask: '死得多不多、团战打得赢吗？',
    title: num(deathAvg)
      ? `场均死 <em>${deathAvg.toFixed(1)}</em> 次；${num(overallFight) ? `团战胜率 <em>${Math.round(overallFight)}%</em>` : '团战胜率暂时算不出'}`
      : '还没有可读的死亡数据（需要关联官方回放）',
    plain: num(winDeath) && num(lossDeath)
      ? `赢的局场均死 ${winDeath.toFixed(1)} 次，输的局 ${lossDeath.toFixed(1)} 次，差 ${Math.abs(lossDeath - winDeath).toFixed(1)} 次。`
      : '在「采集 → 通道校对」里给对局挂上官方回放，这项才有数。',
    chart: { type: 'compare', hero: { value: num(deathAvg) ? deathAvg.toFixed(1) : '—', label: '场均死亡', cls: 'gold' }, items, winN: win.length, lossN: loss.length },
    train: num(lossDeath) && num(winDeath) && lossDeath - winDeath > 2
      ? '输的局比赢的局多死这么多：先把「无谓掉点」列成一课，比练团战更直接。'
      : '保持现在的团战节奏，下一批看团战胜率有没有提高。',
    review: '看输的局',
    actKeys: loss.slice(0, 60).map((r) => r.key),
    method: '死亡和团战都来自回放：死亡数按阵营计，团战按回放里的团战段计，击杀多的一方算赢。只算有回放的局。',
    grade: grade(rows.filter((r) => r.death && num(r.death.own)).length),
    repro: null,
  };
}

/* 15 切 C 与首杀：抓到几次对方后排、开局谁先见血 */
function a15(ctx) {
  const { rows } = ctx;
  const withCut = rows.filter((r) => r.cut && num(r.cut.n));
  const win = withCut.filter((r) => r.result === 'win');
  const loss = withCut.filter((r) => r.result === 'loss');
  const avg = (list, get) => {
    const a = vals(list.map(get));
    return a.length ? mean(a) : null;
  };
  const firstRate = (list) => {
    const known = list.filter((r) => num(r.cut.first));
    return known.length ? sum(list.map((r) => (num(r.cut.first) ? r.cut.first : 0))) / known.length * 100 : null;
  };
  const fmtV = (v, unit) => (!num(v) ? '—' : unit === '%' ? `${Math.round(v)}%` : `${v.toFixed(1)} ${unit}`);
  const mk = (label, get, unit) => ({
    label, win: avg(win, get), loss: avg(loss, get), winText: fmtV(avg(win, get), unit), lossText: fmtV(avg(loss, get), unit),
  });
  const items = [
    mk('场均切 C', (r) => (r.cut ? r.cut.n : null), '次'),
    { label: '先拿首杀', win: firstRate(win), loss: firstRate(loss), winText: fmtV(firstRate(win), '%'), lossText: fmtV(firstRate(loss), '%') },
  ];
  const cutAvg = avg(withCut, (r) => r.cut.n);
  const fr = firstRate(withCut);
  return {
    id: '15', name: '切 C 与首杀', group: '资源与团战', ask: '抓得到对方后排吗？开局谁先见血？',
    title: num(cutAvg)
      ? `场均切 C <em>${cutAvg.toFixed(1)}</em> 次；${num(fr) ? `<em>${Math.round(fr)}%</em> 的局我们先拿到首杀` : '首杀暂时算不出'}`
      : '还没有可读的击杀数据（需要关联官方回放）',
    plain: num(cutAvg)
      ? `赢的局场均切 C ${items[0].winText}、先拿首杀 ${items[1].winText}；输的局 ${items[0].lossText}、${items[1].lossText}。`
      : '在「采集 → 通道校对」里挂上官方回放，这项才有数。',
    chart: { type: 'compare', hero: { value: num(cutAvg) ? cutAvg.toFixed(1) : '—', label: '场均切 C', cls: 'gold' }, items, winN: win.length, lossN: loss.length },
    train: num(cutAvg) && cutAvg < 1
      ? '场均切 C 不到 1 次：把「对抗路/打野绕后切后排」的路线和时机单列一节课。'
      : '保持现在的抓后排节奏，下一批看首杀率能不能过 55%。',
    review: '看输的局',
    actKeys: loss.slice(0, 60).map((r) => r.key),
    method: '切 C＝我方对抗路或打野击杀对方中路/发育路；首杀＝这一局第一次击杀是谁拿的。都来自回放击杀记录，只算有回放的局。',
    grade: grade(withCut.length),
    repro: null,
  };
}

/* 16 英雄组合：哪两个英雄一起上最稳 */
function a16(ctx) {
  const { rows } = ctx;
  const map = new Map();
  for (const r of rows) {
    const hs = (r.heroes || []).filter(Boolean).slice(0, 5);
    if (hs.length < 2) continue;
    for (let i = 0; i < hs.length; i++) {
      for (let j = i + 1; j < hs.length; j++) {
        const key = [hs[i], hs[j]].sort().join('+');
        const e = map.get(key) || { heroes: [hs[i], hs[j]], games: 0, wins: 0, decided: 0, keys: [] };
        e.games += 1;
        e.keys.push(r.key);
        if (r.result === 'win') e.wins += 1;
        if (r.result === 'win' || r.result === 'loss') e.decided += 1;
        map.set(key, e);
      }
    }
  }
  const all = [...map.values()];
  const items = all.filter((e) => e.games >= 2 && e.decided >= 2)
    .sort((a, b) => (b.wins / b.decided) - (a.wins / a.decided) || b.games - a.games)
    .slice(0, 8)
    .map((e) => ({
      label: e.heroes.join(' + '), games: e.games, wins: e.wins, decided: e.decided,
      rate: e.decided ? e.wins / e.decided : null, keys: e.keys,
    }));
  const solid = items.filter((x) => x.games >= 3);
  const best = solid[0] || items[0];
  const worst = items.slice().sort((a, b) => (a.rate || 0) - (b.rate || 0))[0];
  return {
    id: '16', name: '英雄组合', group: 'BP 与阵容', ask: '哪两个英雄一起上最稳？',
    title: best
      ? `「<em>${best.label}</em>」${best.games} 局 ${best.wins} 胜${worst && worst.label !== best.label ? `；「${worst.label}」${worst.decided} 局只赢 ${worst.wins} 局` : ''}`
      : '组合样本还不够，至少要有 2 局同组合',
    plain: best
      ? `这里只算一起上场的次数，不等于这俩有配合；但同一个组合反复出现还一直赢，就值得固定下来。`
      : '继续攒局。',
    chart: { type: 'ledger', items: items.map(({ keys, ...x }) => x), total: all.length },
    train: best ? `把「${best.label}」固定成主选组合，下一批看它遇到强队还成不成立。` : '继续攒局。',
    review: '看这些局的阵容',
    actKeys: best ? best.keys.slice(0, 60) : [],
    method: '把每局我方五人两两配对，统计同一对英雄一起上场的局数与胜负；只列一起上过 2 局以上、且至少有 2 局分出胜负的组合。',
    grade: grade(rows.length),
    repro: null,
  };
}

/* 17 团战账本：以多打少、以少打多、谁先开团 */
function a17(ctx) {
  const { rows } = ctx;
  const withFk = rows.filter((r) => r.fk);
  const sumKey = (key) => withFk.reduce((acc, r) => {
    const b = (r.fk || {})[key];
    if (b) { acc.n += b.n || 0; acc.win += b.win || 0; }
    return acc;
  }, { n: 0, win: 0 });
  const defs = [
    ['adv', '多打少'],
    ['even', '人数相同'],
    ['dis', '少打多'],
    ['first', '我们先拿到首杀'],
    ['firstAgainst', '对方先拿到首杀'],
  ];
  const items = defs.map(([key, label]) => {
    const s = sumKey(key);
    return { label, games: s.n, wins: s.win, decided: s.n, rate: s.n ? s.win / s.n : null };
  }).filter((x) => x.games > 0 && x.rate != null);
  const get = (label) => items.find((x) => x.label === label) || { games: 0, wins: 0, rate: null };
  const adv = get('多打少');
  const dis = get('少打多');
  const first = get('我们先拿到首杀');
  const back = get('对方先拿到首杀');
  const totalBattles = items.reduce((s, x) => s + x.games, 0);
  return {
    id: '17', name: '团战账本', group: '资源与团战', ask: '以多打少的团赢没赢？谁先开团？',
    title: totalBattles
      ? `以多打少的 ${adv.games} 波团赢了 <em>${adv.wins}</em> 波${dis.games ? `；以少打多的 ${dis.games} 波只赢 <em>${dis.wins}</em> 波` : ''}`
      : '还没有可读的团战数据（需要关联官方回放）',
    plain: totalBattles
      ? `我们先拿到这一波团首杀的 ${first.games} 波，胜率 ${num(first.rate) ? pct(first.rate) : '—'}；对方先拿到的 ${back.games} 波，胜率 ${num(back.rate) ? pct(back.rate) : '—'}。`
      : '在「采集 → 通道校对」里挂上官方回放，这项才有数。',
    chart: { type: 'ledger', items: items.map(({ ...x }) => x), total: totalBattles },
    train: num(dis.rate) && dis.rate < 0.4
      ? '少打多的团胜率太低：先把「不接少打多」写进纪律，比练操作见效快。'
      : '团战结构还算健康，下一批看以多打少的胜率能不能过 80%。',
    review: '看输的局',
    actKeys: withFk.filter((r) => r.result === 'loss').slice(0, 60).map((r) => r.key),
    method: '按每波团双方参战人数分桶：我方人多＝多打少，人少＝少打多；「先拿到首杀」按这一波团第一次击杀归谁判断（不是谁先动手，回放里没有开团时刻）。只算有回放的局。',
    grade: grade(withFk.length),
    repro: null,
  };
}

/* 18 打野节奏：前 10 分钟在不在对方半区 */
function a18(ctx) {
  const { rows } = ctx;
  const withJ = rows.filter((r) => r.jungle && num(r.jungle.crossShare));
  const win = withJ.filter((r) => r.result === 'win');
  const loss = withJ.filter((r) => r.result === 'loss');
  const avg = (list, get) => {
    const a = vals(list.map(get));
    return a.length ? mean(a) : null;
  };
  const fmt = (v, kind) => {
    if (!num(v)) return '—';
    if (kind === 'pct') return `${Math.round(v * 100)}%`;
    if (kind === 'sec') return `${Math.round(v)} 秒`;
    return `${v.toFixed(1)} 次`;
  };
  const mk = (label, get, kind) => ({
    label, win: avg(win, get), loss: avg(loss, get),
    winText: fmt(avg(win, get), kind), lossText: fmt(avg(loss, get), kind),
  });
  const items = [
    mk('过河时间占比', (r) => (r.jungle ? r.jungle.crossShare : null), 'pct'),
    mk('首次过河', (r) => (r.jungle ? r.jungle.firstCross : null), 'sec'),
    mk('深入野区占比', (r) => (r.jungle ? r.jungle.deepShare : null), 'pct'),
    mk('反野次数', (r) => (r.buff ? r.buff.anti : null), 'n'),
    mk('被反野次数', (r) => (r.buff ? r.buff.stolen : null), 'n'),
  ];
  const share = avg(withJ, (r) => r.jungle.crossShare);
  const firstCross = avg(withJ, (r) => r.jungle.firstCross);
  const anti = avg(withJ, (r) => (r.buff ? r.buff.anti : null));
  const deep = avg(withJ, (r) => r.jungle.deepShare);
  return {
    id: '18', name: '打野节奏', group: '资源与团战', ask: '打野前期在不在对方半区？是在反野还是在跑？',
    title: num(share)
      ? `打野前 10 分钟有 <em>${Math.round(share * 100)}%</em> 的时间在对方半区${num(firstCross) ? `，第一次过河在第 <em>${Math.round(firstCross)}</em> 秒` : ''}`
      : '还没有逐秒位置数据（需要按通道校对挂上官方回放）',
    plain: num(share)
      ? `其中真正进到野区腹地的只有 ${num(deep) ? Math.round(deep * 100) : '—'}%；反野场均 ${num(anti) ? anti.toFixed(1) : '—'} 次。过河多、反野少，说明是在跑路线，不是在反野。`
      : '位置数据来自官方回放，一局一个文件；缺了就整张卡留空，不补 0。',
    chart: { type: 'compare', hero: { value: num(share) ? `${Math.round(share * 100)}%` : '—', label: '过河时间占比', cls: 'gold' }, items, winN: win.length, lossN: loss.length },
    train: num(share) && num(anti) && share > 0.15 && anti < 2
      ? '过河时间不低、反野却少：把「过河去干什么」写清楚——是抓边还是进野区，两条路线分开练。'
      : num(share) && share < 0.08
        ? '打野前期基本不过河：先练「第一次过河的时机」，再看反野。'
        : '保持现在的打野路线，下一批看反野次数有没有提高。',
    review: '看输的局',
    actKeys: loss.slice(0, 60).map((r) => r.key),
    method: '取 0–10 分钟逐秒坐标（1 Hz），按 x+y 投影到「己方—对方」轴：越过河道 8 个单位算过河，超过 25 算深入野区。反野次数来自 BUFF 击杀事件，不由位置推算。口径见 docs/jungle_position_spec.md。',
    grade: grade(withJ.length),
    repro: null,
  };
}

/* 19 选手榜：逐人场均死亡、参团、分均经济 */
function a19(ctx) {
  const { rows } = ctx;
  const map = new Map();
  for (const r of rows) {
    for (const p of (r.pl || [])) {
      if (p.camp !== r.camp || !p.name) continue;
      const e = map.get(p.name) || { name: p.name, pos: p.pos, games: 0, d: [], part: [], gpm: [] };
      e.games += 1;
      if (num(p.d)) e.d.push(p.d);
      if (num(p.part)) e.part.push(p.part);
      if (num(p.gpm)) e.gpm.push(p.gpm);
      map.set(p.name, e);
    }
  }
  const all = [...map.values()].filter((e) => e.games >= 3 && e.d.length);
  const pool = all.length >= 3 ? all : [...map.values()].filter((e) => e.games >= 2 && e.d.length);
  const items = pool.map((e) => {
    const dd = mean(e.d);
    const pp = e.part.length ? mean(e.part) : null;
    const gg = e.gpm.length ? mean(e.gpm) : null;
    return {
      name: e.name, pos: e.pos, games: e.games, value: dd,
      label: `${e.name}${e.pos ? ' · ' + e.pos : ''}`, text: `${dd.toFixed(1)} 次`,
      sub: `${num(pp) ? Math.round(pp) + '% 参团' : '参团 —'} · ${num(gg) ? Math.round(gg) : '—'} 金币/分 · ${e.games} 局`,
    };
  }).sort((a, b) => b.value - a.value);
  const top = items[0];
  const low = items.slice().sort((a, b) => a.value - b.value)[0];
  const adcOver = items.filter((x) => x.pos === '发育路' && x.value > 2);
  return {
    id: '19', name: '选手榜', group: '五路与人', ask: '谁死得多、谁活得稳？',
    title: top
      ? `${top.name} 场均死 <em>${top.value.toFixed(1)}</em> 次最多（${top.games} 局）${adcOver.length ? `；${adcOver.length} 名发育路超过 2 次` : ''}`
      : '还没有选手样本（至少要有 2 局）',
    plain: top && low
      ? `${low.name} 最稳，场均 ${low.value.toFixed(1)} 次。死亡按局算，只统计出场 2 局以上的人。`
      : '继续攒局。',
    chart: { type: 'bars', hero: top ? { value: top.value.toFixed(1), label: `场均死亡最多 · ${top.name}`, cls: 'neg' } : null, items },
    train: adcOver.length
      ? `发育路有 ${adcOver.length} 人场均死亡超过 2 次：先看是不是站位和保护问题，再谈输出。`
      : '按常规节奏走，下一批看场均死亡有没有下降。',
    review: '看这些人的局',
    actKeys: rows.filter((r) => (r.pl || []).some((p) => p.camp === r.camp && p.name === (top ? top.name : ''))).slice(0, 60).map((r) => r.key),
    method: '按昵称汇总我方每一局的表现：场均死亡＝总死亡 ÷ 出场局数；参团率与分均经济取营地十人面板的原值。只统计出场 2 局以上的人。',
    grade: grade(all.length),
    repro: null,
  };
}

/* 20 位置对位：同一条路，我们的人和对面的人差多少 */
function a20(ctx) {
  const { rows } = ctx;
  const lanes = LANES.map((lane) => {
    const g = [], dm = [], dd = [];
    for (const r of rows) {
      const own = (r.pl || []).find((p) => p.camp === r.camp && p.pos === lane);
      const foe = (r.pl || []).find((p) => p.camp !== r.camp && p.pos === lane);
      if (!own || !foe) continue;
      if (num(own.gpm) && num(foe.gpm)) g.push(own.gpm - foe.gpm);
      if (num(own.dpm) && num(foe.dpm)) dm.push(own.dpm - foe.dpm);
      if (num(own.d) && num(foe.d)) dd.push(own.d - foe.d);
    }
    return { lane, g: g.length ? median(g) : null, d: dm.length ? median(dm) : null, dd: dd.length ? median(dd) : null, n: g.length };
  }).filter((x) => x.n);
  if (!lanes.length) {
    return {
      id: '20', name: '位置对位', group: '五路与人', ask: '同一条路，我们和对面差多少？',
      title: '还没有同位置对位样本', plain: '需要双方同一条路都有数据的局。',
      chart: { type: 'bars', items: [] }, train: '继续攒局。', review: '看这批局', actKeys: [],
      method: '每局把双方同分路的人配对，比较分均经济、分均输出和死亡。', grade: grade(0), repro: null,
    };
  }
  const items = lanes.map((x) => ({
    label: x.lane, value: x.g, text: `${sign(x.g)} 金币/分`,
    sub: `输出 ${num(x.d) ? sign(x.d) : '—'} · 死亡 ${num(x.dd) ? sign(x.dd) : '—'} · ${x.n} 组`,
  }));
  const best = lanes.slice().sort((a, b) => b.g - a.g)[0];
  const worst = lanes.slice().sort((a, b) => a.g - b.g)[0];
  const dmgTop = lanes.slice().sort((a, b) => (b.d || 0) - (a.d || 0))[0];
  return {
    id: '20', name: '位置对位', group: '五路与人', ask: '同一条路，我们和对面差多少？',
    title: worst.g < 0
      ? `<em>${best.lane}</em> 同位置领先最多（<em>${sign(best.g)}</em> 金币/分），<em>${worst.lane}</em> 落后最多（<em>${sign(worst.g)}</em>）`
      : `五路同位置都领先：<em>${best.lane}</em> 最多（<em>${sign(best.g)}</em> 金币/分），<em>${worst.lane}</em> 最少（<em>${sign(worst.g)}</em>）`,
    plain: `输出差最大的是${dmgTop ? dmgTop.lane : '—'}（${dmgTop && num(dmgTop.d) ? sign(dmgTop.d) : '—'} 伤害/分）。每局同一条路两个人配对，只算双方都有数的局。`,
    chart: { type: 'bars', hero: { value: `${sign(best.g)}`, label: `${best.lane} · 同位置分均领先`, cls: 'gold' }, items },
    train: best.g < 0
      ? '五条路对位都不占优：先把每条路的开局处理拆开，别只练团战。'
      : `把${worst.lane}的对线单列出来练：同位置差 ${sign(worst.g)} 金币/分。`,
    review: '看落后的局',
    actKeys: rows.filter((r) => (r.pl || []).some((p) => p.pos === worst.lane)).slice(0, 60).map((r) => r.key),
    method: '每局把双方同分路的人配对，分别算分均经济差、分均输出差、场均死亡差；金币和伤害都是本队减对手，按局取典型值。',
    grade: grade(lanes.reduce((s, x) => s + x.n, 0)),
    repro: null,
  };
}

/* 21 团战伤害结构：每波团里，谁在打、谁在扛 */
function a21(ctx) {
  const { rows } = ctx;
  const withFs = rows.filter((r) => r.fs && Object.keys(r.fs).length);
  const acc = {};
  for (const r of withFs) {
    for (const pos of LANES) {
      const cell = r.fs[pos];
      if (!cell || !num(cell.n) || !cell.n) continue;
      const e = acc[pos] || { h: 0, t: 0, n: 0 };
      e.h += (cell.hurtShare || 0) * cell.n;
      e.t += (cell.takenShare || 0) * cell.n;
      e.n += cell.n;
      acc[pos] = e;
    }
  }
  const items = LANES.filter((p) => acc[p]).map((pos) => {
    const e = acc[pos];
    const h = e.h / e.n, t = e.t / e.n;
    return { label: pos, win: h * 100, loss: t * 100, winText: `${Math.round(h * 100)}%`, lossText: `${Math.round(t * 100)}%` };
  });
  if (!items.length) {
    return {
      id: '21', name: '团战伤害结构', group: '资源与团战', ask: '每波团谁在打、谁在扛？',
      title: '还没有团战明细（需要关联官方回放）', plain: '在「采集 → 通道校对」里挂上官方回放，这项才有数。',
      chart: { type: 'bars', items: [] }, train: '先把回放挂上。', review: '看这批局', actKeys: [],
      method: '从每波团的十人明细算我方各分路的伤害占比与承伤占比。', grade: grade(0), repro: null,
    };
  }
  const topHurt = items.slice().sort((a, b) => b.win - a.win)[0];
  const topTaken = items.slice().sort((a, b) => b.loss - a.loss)[0];
  return {
    id: '21', name: '团战伤害结构', group: '资源与团战', ask: '每波团谁在打、谁在扛？',
    title: `<em>${topHurt.label}</em> 打伤害最多（<em>${topHurt.winText}</em>），<em>${topTaken.label}</em> 扛伤最多（<em>${topTaken.lossText}</em>）`,
    plain: '占比是同一条路在每波团里占我方总伤害/总承伤的平均值；每条路占比独立算，不能相加。',
    chart: { type: 'compare', headers: ['伤害占比', '承伤占比'], hero: { value: topHurt.winText, label: `${topHurt.label} · 团战伤害占比`, cls: 'gold' }, items, winN: 0, lossN: 0 },
    train: topTaken && topHurt && topTaken.label === topHurt.label
      ? '同一个位置又打又扛：先看是不是前排没人接，别只夸他。'
      : `把${topTaken ? topTaken.label : '前排'}的承伤和${topHurt ? topHurt.label : '后排'}的伤害对起来看，确认是不是在替他扛。`,
    review: '看这些局的团战',
    actKeys: withFs.slice(0, 60).map((r) => r.key),
    method: '每波团先算我方总伤害/总承伤，再看每条路占多少，最后按分路取平均。只算有回放、且我方有人参战的团。',
    grade: grade(withFs.length),
    repro: null,
  };
}

/* 22 优势兑现：10 分钟领先之后，把优势换成资源、再换成胜负 */
function a22(ctx) {
  const { rows } = ctx;
  const decided = rows.filter((r) => num(r.at10) && (r.result === 'win' || r.result === 'loss'));
  const lead = decided.filter((r) => r.at10 > 0);
  const behind = decided.filter((r) => r.at10 <= 0);
  const hasDragon = (r) => !!(r.obj && num(r.obj.dragonOwn) && r.obj.dragonOwn > 0);
  const hasTower = (r) => !!(r.obj && num(r.obj.towerOwn) && num(r.obj.towerFoe) && r.obj.towerOwn > r.obj.towerFoe);
  const stat = (list) => {
    const w = list.filter((r) => r.result === 'win').length;
    return { n: list.length, w, rate: list.length ? w / list.length : null };
  };
  const steps = [
    { label: '10 分钟领先', ...stat(lead) },
    { label: '领先 + 拿到龙', ...stat(lead.filter(hasDragon)) },
    { label: '领先 + 推塔占优', ...stat(lead.filter(hasTower)) },
    { label: '领先 + 龙和塔都做到', ...stat(lead.filter((r) => hasDragon(r) && hasTower(r))) },
  ].filter((s) => s.n > 0).sort((a, b) => (a.rate || 0) - (b.rate || 0));
  const base = stat(lead);
  const best = steps.slice().sort((a, b) => (b.rate || 0) - (a.rate || 0))[0];
  const comeback = stat(behind.filter((r) => r.result === 'win'));
  const items = steps.map((s) => ({
    label: s.label, value: (s.rate || 0) * 100,
    text: `${Math.round((s.rate || 0) * 100)}%`,
    sub: `${s.w}/${s.n} 局`,
  }));
  return {
    id: '22', name: '优势兑现', group: '资源与团战', ask: '10 分钟领先之后，优势换成了什么？',
    title: base.n
      ? `10 分钟领先的 ${base.n} 局赢下 <em>${base.w}</em> 局（${pct(base.rate)}）${best && best.label !== '10 分钟领先' ? `；做到「${best.label.replace('领先 + ', '')}」的 ${best.n} 局赢 <em>${best.w}</em> 局` : ''}`
      : '还没有可读的领先局面（需要 10 分钟经济差与胜负）',
    plain: base.n
      ? `10 分钟落后的 ${behind.length} 局翻回 ${comeback.w} 局（${pct(comeback.rate)}）。领先不只是看经济差，要看有没有换成龙和塔。`
      : '先补齐 10 分钟经济差。',
    chart: { type: 'bars', hero: { value: base.n ? pct(base.rate) : '—', label: '10 分钟领先的兑现率', cls: 'gold' }, items },
    train: best && base.rate != null && (best.rate || 0) - base.rate > 0.05
      ? `领先之后补上「${best.label.replace('领先 + ', '')}」，胜率能从 ${pct(base.rate)} 提到 ${pct(best.rate)}——把它写进领先局的打法要求。`
      : '领先局的兑现已经比较稳，下一批看落后局能不能翻回更多。',
    review: '看领先没赢的局',
    actKeys: lead.filter((r) => r.result === 'loss').slice(0, 60).map((r) => r.key),
    method: '先筛 10 分钟经济差为正且分出胜负的局，再看这些局里有没有拿到龙、推塔是否多于对手；每一步都单独算胜率，不是因果链。',
    grade: grade(base.n),
    repro: null,
  };
}

/* 23 对手阵容：同一个对手反复用哪几个人 */
function a23(ctx) {
  const { rows } = ctx;
  const withFoe = rows.filter((r) => Array.isArray(r.heroesFoe) && r.heroesFoe.length >= 2);
  const oppMap = new Map();
  for (const r of withFoe) {
    const opp = String(r.opponent || '').trim() || '未填对手';
    const e = oppMap.get(opp) || { games: 0, combos: new Map() };
    e.games += 1;
    const hs = r.heroesFoe;
    for (let i = 0; i < hs.length; i++) {
      for (let j = i + 1; j < hs.length; j++) {
        const key = [hs[i], hs[j]].sort().join('+');
        const c = e.combos.get(key) || { heroes: [hs[i], hs[j]], games: 0, ourWins: 0 };
        c.games += 1;
        if (r.result === 'win') c.ourWins += 1;
        e.combos.set(key, c);
      }
    }
    oppMap.set(opp, e);
  }
  const items = [...oppMap.entries()].map(([opp, e]) => {
    const top = [...e.combos.values()].sort((a, b) => b.games - a.games)[0];
    if (!top) return null;
    return {
      label: `${opp} · ${top.heroes.join(' + ')}`,
      opp, games: top.games, wins: top.ourWins, decided: top.games,
      rate: top.games ? top.ourWins / top.games : null, oppGames: e.games,
    };
  }).filter(Boolean).sort((a, b) => b.games - a.games);
  const top = items[0];
  const worst = items.slice().filter((x) => x.decided >= 2).sort((a, b) => (a.rate || 0) - (b.rate || 0))[0];
  return {
    id: '23', name: '对手阵容', group: '对手', ask: '同一个对手反复用哪几个人？',
    title: top
      ? `对 ${top.opp}（${top.oppGames} 局），他们最常用「<em>${top.label.split(' · ')[1]}</em>」，出现 ${top.games} 次`
      : '对手阵容还读不到（需要十人面板）',
    plain: top
      ? `我们对着这套组合 ${top.games} 局赢 ${top.wins} 局${worst && worst.label !== top.label ? `；最吃亏的是「${worst.label.split(' · ')[1]}」${worst.decided} 局只赢 ${worst.wins} 局` : ''}。`
      : '先把对手名补上，这张表才有意义。',
    chart: { type: 'ledger', items: items.map(({ opp, oppGames, ...x }) => x), total: oppMap.size },
    train: worst && worst.rate != null && worst.rate < 0.4
      ? `对手这套「${worst.label.split(' · ')[1]}」我们只赢 ${worst.decided} 局里的 ${worst.wins} 局：赛前准备要单独准备破解。`
      : '继续补对手名，样本够了再谈针对性 BP。',
    review: '看这些局',
    actKeys: withFoe.slice(0, 60).map((r) => r.key),
    method: '按对手名分组，把他们每局五人两两配对，取出现次数最多的一组；胜率是按我们视角算的（我们赢的比例），只统计有对手阵容的局。',
    grade: grade(withFoe.length),
    repro: null,
  };
}

export function analyzeCohort(vectors) {
  const ctx = prepare(vectors);
  const cards = ctx.n ? [a01, a02, a03, a04, a05, a06, a07, a08, a09, a10, a11, a12, a13, a14, a15, a16, a17, a18, a19, a20, a21, a22, a23].map((f) => {
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
