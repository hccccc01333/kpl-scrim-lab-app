/* 单局深度分析：比赛脉搏 / 总量 / 阶段对比 / 十人面板 / 十人热区 / 对位深区。
   全部为纯函数式构建，数据来自 /api/matches/<key>、/api/replay/<key>、/api/positions/<key>。
   视觉口径：深墨蓝底 + 金（本队）· 青（对手）+ 等宽数字 + 体素方块。 */

const MAP = 60;          // 地图坐标半径（营地回放为 [-57, 57]）
const GRID = 16;         // 热区网格
const DEEP = 0.66;       // 深区阈值（推进进度）
const HALF = 0.5;        // 半区阈值（越过中线即入侵）
const STILL_SECONDS = 12; // 连续静止超过该秒数视为死亡/暂停，样本剔除（与全景页一致）
const PROX_RADIUS = 22.5; // 集结半径：地图对角线 149.91 的 15%
const PROX_SECONDS = 5;   // 集结需持续时长
/* 并线（教练 2026-11-10 第四波口径）：兵线在的时候，同一条路上本队 2～3 个人一起吃
   这波线。交汇点会随推塔前后移动（也可能被反推到自家二塔甚至高地前），所以只按
   「这波兵已经出了」切窗口，不假定交汇位置；三路走廊用回放坐标里的定值折线。
   阈值都收在这里，改口径只改这一处。 */
const WAVE_FIRST = 10;        // 第一波兵线出发（README.md §4.1：10+33(n−1)）
const WAVE_GAP = 33;          // 波次间隔
const LANE_CORRIDOR = 15;     // 到该路折线的距离上限（塔位内缩约 15）
const LANE_CLUSTER = 20;      // 一起吃线的彼此距离上限
const LANE_BASE = 34;         // 己方基地半径内不算（出生点压在边路延长线上）
const LANE_HOLD = 4;          // 同处最短时长
/* 三条路的折线（营地坐标 ±57，塔位内缩在各边 42 处）：
   对抗路＝左侧竖段接上边横段，发育路＝下边横段接右侧竖段，中路＝对角线。 */
const LANE_PATH = {
  '对抗路': [[-42, -58], [-42, 42], [58, 42]],
  '发育路': [[-58, -42], [42, -42], [42, 58]],
  '中路': [[-58, -58], [58, 58]],
};

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const num = (v) => typeof v === 'number' && Number.isFinite(v);

/* 推进进度：0 = 蓝方基地，1 = 红方基地 */
function progress(x, y) {
  return clamp((x + y + 112) / 224, 0, 1);
}

/* 静止样本掩码：连续相同的坐标点达到 STILL_SECONDS 后剔除，
   与 mapping/match_review.py 的 _active_mask（STILL_RUN=12）同口径。
   位置按 step 秒降采样，所以换算成采样点数。 */
function activeMask(points, step) {
  const limit = Math.max(1, Math.round(STILL_SECONDS / (step || 1)));
  const mask = [];
  let run = 0;
  for (let i = 0; i < points.length; i++) {
    const same = i > 0 && points[i][0] === points[i - 1][0] && points[i][1] === points[i - 1][1];
    run = same ? run + 1 : 0;
    mask.push(run < limit);
  }
  return mask;
}

/* 并线（教练 2026-11-10 第四波口径）：兵线在的时候，同一条路上本队 2～3 个人一起吃
   这波线。教练补充：**组里必须有打野**——射手 + 辅助这种固定搭档不算并线，
   打野 + 对抗 / 打野 + 中路 / 打野 + 射手 / 打野 + 中路 + 辅助 才算。
   交汇点会随推塔前后移动（也可能被反推到自家二塔甚至高地前），所以只按
   「这波兵已经出了」切窗口，不假定交汇位置：第 n 波在 10+33(n−1) 秒出发，
   到第 n+1 波出发之间就是这一波的窗口。路用 LANE_PATH 折线上的距离判。
   一次并线 = 同一波、同一条路上，2～3 人聚成一组、组里有打野和这条路的对线选手，
   持续 ≥ LANE_HOLD 秒；一波一线最多记一次。5 人以上算团战/推进，不算并线。
   己方基地内、坐标 (0,0) 占位、阵亡冻结样本都不计。
   输出按「阵营-槽位」索引：{ total, lanes, waves: [{t, wave, lane, size}] }，
   口径写在页面上：近似值，只做同局两队横向比较，不进评级。
   `laneOf` 由调用方注入（面板里按 position 字段取分路）。 */
export function joinLaneStats(positions, players, laneOf) {
  const out = new Map();
  if (!positions || !Array.isArray(positions.players) || !positions.players.length) return out;
  const step = positions.step || 2;
  const laneBySlot = new Map();
  for (const p of players || []) {
    if (!p || p.slot === undefined || p.slot === null) continue;
    const lane = laneOf(p);
    if (lane) laneBySlot.set(`${p.camp}-${p.slot}`, lane);
  }
  const crewByCamp = { blue: [], red: [] };
  for (const src of positions.players) {
    const key = `${src.camp}-${src.slot}`;
    const lane = laneBySlot.get(key) || '';
    (crewByCamp[src.camp] || (crewByCamp[src.camp] = [])).push({
      key, lane, points: src.points, camp: src.camp,
    });
  }
  const laneDistance = (x, y, lane) => {
    const path = LANE_PATH[lane];
    let best = Infinity;
    for (let i = 0; i < path.length - 1; i += 1) {
      const [ax, ay] = path[i];
      const [bx, by] = path[i + 1];
      const dx = bx - ax;
      const dy = by - ay;
      const length = dx * dx + dy * dy;
      const t = length ? clamp(((x - ax) * dx + (y - ay) * dy) / length, 0, 1) : 0;
      best = Math.min(best, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
    }
    return best;
  };
  const perPlayer = new Map();
  const note = (key) => {
    if (!perPlayer.has(key)) perPlayer.set(key, { total: 0, lanes: {}, waves: [] });
    return perPlayer.get(key);
  };
  for (const camp of ['blue', 'red']) {
    const crew = crewByCamp[camp] || [];
    if (!crew.length) continue;
    const base = camp === 'blue' ? [-58, -58] : [58, 58];
    const masks = new Map(crew.map((item) => [item.key, activeMask(item.points || [], step)]));
    for (const lane of Object.keys(LANE_PATH)) {
      const owner = crew.find((item) => item.lane === lane);
      const members = crew.filter((item) => Array.isArray(item.points) && item.points.length);
      if (!owner || !Array.isArray(owner.points) || members.length < 2) continue;
      const waves = new Map();
      const length = Math.max(...members.map((item) => item.points.length));
      for (let i = 0; i * step < length; i += 1) {
        const second = i * step;
        if (second < WAVE_FIRST) continue;
        const wave = Math.floor((second - WAVE_FIRST) / WAVE_GAP) + 1;
        const here = [];
        for (const item of members) {
          let point = item.points[i];
          if (!Array.isArray(point)) continue;
          if (point[0] === 0 && point[1] === 0) continue;
          if (!(masks.get(item.key) || [])[i]) continue;
          if (Math.hypot(point[0] - base[0], point[1] - base[1]) <= LANE_BASE) continue;
          if (laneDistance(point[0], point[1], lane) > LANE_CORRIDOR) continue;
          here.push({ item, point });
        }
        if (here.length < 2) continue;
        /* 按彼此距离 ≤ LANE_CLUSTER 连通分组，取「含该路对线选手、且含打野」的那一组：
           教练 2026-11-10 补的口径——射手 + 辅助这种固定搭档不算并线，并线要有打野参与。 */
        const groups = [];
        for (const row of here) {
          const hit = groups.filter((group) => group.some(
            (other) => Math.hypot(row.point[0] - other.point[0], row.point[1] - other.point[1]) <= LANE_CLUSTER));
          const merged = [row];
          for (const group of hit) {
            merged.push(...group);
            groups.splice(groups.indexOf(group), 1);
          }
          groups.push(merged);
        }
        const home = groups.find((group) => group.some((row) => row.item.key === owner.key)
          && group.some((row) => row.item.lane === '打野'));
        if (!home || home.length < 2 || home.length > 3) continue;
        const bucket = waves.get(wave) || { t: second, wave, lane, size: 0, who: [] };
        bucket.size = Math.max(bucket.size, home.length);
        const sec = (bucket.sec || 0) + step;
        waves.set(wave, { ...bucket, sec, who: [...new Set([...bucket.who, ...home.map((row) => row.item.key)])] });
      }
      for (const bucket of waves.values()) {
        if ((bucket.sec || 0) < LANE_HOLD) continue;
        for (const key of bucket.who) {
          const stat = note(key);
          stat.total += 1;
          stat.lanes[lane] = (stat.lanes[lane] || 0) + 1;
          stat.waves.push({ t: bucket.t, wave: bucket.wave, lane: bucket.lane, size: bucket.size });
        }
      }
    }
  }
  for (const [key, stat] of perPlayer.entries()) {
    stat.waves.sort((a, b) => a.t - b.t);
    out.set(key, stat);
  }
  return out;
}

export function createMatchDeep(h) {
  const { esc, fmt, pct, diff, time, portrait } = h;
  /* 阶段口径由 app 注入（对线 0–4′、发育 4–10′、后期 10′+）。 */
  const gpmOf = h.gpmOf || ((player, duration) => {
    if (!player || !Number.isFinite(player.gold)) return null;
    const minutes = Number(duration) > 0 ? duration / 60 : null;
    return minutes ? player.gold / minutes : null;
  });
  const goldGrade = h.goldGrade || (() => null);
  const phaseWindows = h.phases || ((duration) => {
    const total = Number(duration) > 0 ? Number(duration) : 0;
    return [['对线期', 0, 240], ['发育期', 240, 600], ['后期', 600, Infinity]]
      .map(([label, start, end]) => {
        const a = Math.min(start, total);
        const b = Math.min(end === Infinity ? total : end, total);
        return { label, start: a, end: Math.max(a, b) };
      });
  });

  /* ── 总量：总经济 / 击杀 / 输出 / 承伤 ───────────────────────────── */
  function totals(m) {
    const own = m.own || {}, foe = m.enemy || {};
    const items = [
      ['总经济', own.gold, foe.gold, (v) => fmt(v)],
      ['击杀', own.kills, foe.kills, (v) => fmt(v)],
      ['输出', own.damage, foe.damage, (v) => fmt(v)],
      ['承伤', own.taken ?? foe.damage, foe.taken ?? own.damage, (v) => fmt(v)],
    ];
    const cells = items.map(([label, a, b, show]) => {
      const total = (num(a) ? a : 0) + (num(b) ? b : 0);
      const share = total > 0 && num(a) ? a / total * 100 : 50;
      return `<div class="md-total">
        <span>${esc(label)}</span>
        <div class="md-total-pair"><b>${show(a)}</b><i>:</i><b class="foe">${show(b)}</b></div>
        <div class="md-total-bar"><i style="width:${share.toFixed(1)}%"></i></div>
      </div>`;
    }).join('');
    return `<div class="md-totals">${cells}</div>`;
  }

  /* ── 比赛脉搏：经济差曲线 + 事件标记 + 可拖动指针 ───────────────── */
  function pulse(series, events, duration, camps) {
    if (!series.length) return '';
    const W = 1000, H = 300, L = 58, R = 982, TOP = 26, BOT = 250;
    const t0 = series[0].t, t1 = series.at(-1).t;
    const span = Math.max(1, t1 - t0);
    const absMax = Math.max(1000, ...series.map((p) => Math.abs(p.diff)));
    const limit = Math.ceil(absMax / 5000) * 5000;
    const low = Math.min(0, ...series.map((p) => p.diff)) < 0 ? -limit : 0;
    const high = limit;
    const x = (t) => L + (t - t0) / span * (R - L);
    const y = (v) => TOP + (high - v) / (high - low) * (BOT - TOP);
    const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.diff).toFixed(1)}`).join(' ');
    const tip = series.at(-1);

    const steps = [];
    const stepSize = limit >= 20000 ? 10000 : 5000;
    for (let v = low; v <= high; v += stepSize) steps.push(v);

    const bands = duration > 0 ? phaseWindows(duration).map((w, i) => {
      const a = Math.max(w.start, t0), b = Math.min(w.end, t1);
      if (b <= a) return '';
      const xa = x(a), xb = x(b);
      return `<rect x="${xa.toFixed(1)}" y="${TOP}" width="${(xb - xa).toFixed(1)}" height="${BOT - TOP}" class="mp-band${i % 2 ? ' alt' : ''}"/>
        <text x="${((xa + xb) / 2).toFixed(1)}" y="${TOP - 9}" text-anchor="middle" class="mp-band-label">${w.label}</text>`;
    }).join('') : '';

    const zero = low < 0 ? `<line x1="${L}" x2="${R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="mp-zero"/>` : '';

    /* 事件标记：龙/野怪/塔/水晶各有自己的形状，点位可点开看具体是什么。
       形状区别是为了让教练不用悬停也能分出「这是红 BUFF 还是中路一塔」。 */
    const diffAt = (t) => {
      let best = series[0];
      for (const p of series) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
      return best.diff;
    };
    const markKind = (e) => {
      if (e.kind === 'structure') return /水晶/.test(e.label || '') ? 'core' : 'tower';
      return /BUFF/.test(e.label || '') ? 'buff' : 'dragon';
    };
    const shapeOf = (kind, cx, cy) => {
      if (kind === 'tower') return `<rect x="${(cx - 4).toFixed(1)}" y="${(cy - 4).toFixed(1)}" width="8" height="8" rx="1.5"/>`;
      if (kind === 'core') return `<rect x="${(cx - 5.5).toFixed(1)}" y="${(cy - 5.5).toFixed(1)}" width="11" height="11" rx="2"/>`;
      if (kind === 'buff') return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4"/>`;
      return `<path d="M${cx.toFixed(1)},${(cy - 5.5).toFixed(1)} L${(cx + 5.5).toFixed(1)},${cy.toFixed(1)} L${cx.toFixed(1)},${(cy + 5.5).toFixed(1)} L${(cx - 5.5).toFixed(1)},${cy.toFixed(1)} Z"/>`;
    };
    const markList = (events || []).filter((e) => num(e.t) && e.t >= t0 && e.t <= t1
      && (e.kind === 'resource' || e.kind === 'structure'));
    const marks = markList.map((e, i) => {
      const c = e.killerCamp === camps.own ? 'own' : 'foe';
      const cx = x(e.t), cy = y(diffAt(e.t)) - 13;
      return `<g class="mp-mark ${c} ${markKind(e)}" data-mark="${i}" tabindex="0" role="button"
        aria-label="${esc(time(e.t) + ' ' + (e.label || ''))}"><title>${esc(time(e.t) + ' · ' + (e.label || '') + ' · ' + (e.killerHero || e.killer || ''))}</title>${shapeOf(markKind(e), cx, cy)}</g>`;
    }).join('');

    return `<div class="mp" data-pulse data-t0="${t0}" data-t1="${t1}" data-duration="${duration}">
      <div class="mp-readout">
        <span class="mp-clock"><small>指针时刻</small><b data-pulse-clock>${time(t0)}</b></span>
        <span><small class="own">本队经济</small><b data-pulse-blue>${fmt(series[0].own)}</b></span>
        <span><small class="foe">对手经济</small><b data-pulse-red>${fmt(series[0].foe)}</b></span>
        <span><small>经济差</small><b data-pulse-diff>${diff(series[0].diff)}</b></span>
        <span class="mp-at" data-pulse-at>拖动或点按曲线，查看任意时刻</span>
      </div>
      <svg class="mp-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="经济差随时间变化，共 ${series.length} 个采样点">
        <defs><linearGradient id="mp-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style="stop-color:var(--md-gold);stop-opacity:.34"/>
          <stop offset="1" style="stop-color:var(--md-gold);stop-opacity:0"/>
        </linearGradient></defs>
        ${bands}
        <line class="mp-grid" x1="${L}" x2="${R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>
        ${steps.filter((v) => v !== 0).map((v) => `<line class="mp-grid" x1="${L}" x2="${R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>
          <text x="${L - 10}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" class="mp-axis">${fmt(v / 1000, 0)}k</text>`).join('')}
        <text x="${L - 10}" y="${(y(0) + 4).toFixed(1)}" text-anchor="end" class="mp-axis">0</text>
        ${zero}
        <path d="${line} L${x(tip.t).toFixed(1)},${y(0).toFixed(1)} L${x(t0).toFixed(1)},${y(0).toFixed(1)} Z" fill="url(#mp-area)"/>
        <path d="${line}" class="mp-curve"/>
        <rect class="mp-hit" x="${L}" y="${TOP}" width="${R - L}" height="${BOT - TOP}"/>
        ${marks}
        <circle cx="${x(tip.t).toFixed(1)}" cy="${y(tip.diff).toFixed(1)}" r="4.5" class="mp-end"/>
        <g class="mp-cursor" hidden>
          <line x1="0" x2="0" y1="${TOP}" y2="${BOT}"/>
          <circle cx="0" cy="0" r="5"/>
        </g>
      </svg>
      <div class="mp-card" data-pulse-card hidden></div>
      <div class="mp-axis-row"><span>${time(t0)}</span><span>${time(t1)}</span></div>
    </div>`;
  }

  /* ── 阶段对比：经济差 / 阶段变化 / 资源 / 建筑 / 入侵 ─────────────── */
  function phaseTable(rows) {
    if (!rows.length) return '';
    const head = `<div class="md-phase-head"><span>阶段</span><span>本队增长</span><span>对手增长</span><span>净差</span><span>资源</span><span>建筑</span><span>入侵</span></div>`;
    const body = rows.map((r) => `<div class="md-phase-line">
      <span class="md-phase-tag">${esc(r.label)}<small>${esc(r.range)}</small></span>
      <span class="md-phase-gain own"><b>${diff(r.ownGain)}</b><i style="--v:${r.ownPct}"></i></span>
      <span class="md-phase-gain foe"><b>${diff(r.foeGain)}</b><i style="--v:${r.foePct}"></i></span>
      <span class="md-phase-net ${r.net >= 0 ? 'own' : 'foe'}">${diff(r.net)}</span>
      <span class="md-phase-duo"><b>${fmt(r.res.own)}</b><i>:</i><b class="foe">${fmt(r.res.foe)}</b></span>
      <span class="md-phase-duo"><b>${fmt(r.struct.own)}</b><i>:</i><b class="foe">${fmt(r.struct.foe)}</b></span>
      <span class="md-phase-inv">${r.invade === null ? '—' : pct(r.invade)}</span>
    </div>`).join('');
    return `<div class="md-phase-table">${head}${body}</div>`;
  }

  /* ── 十人面板：对位比较 / 同队比较 ───────────────────────────────── */
  const LANES = ['对抗路', '发育路', '中路', '打野', '游走'];
  const read = (p, key) => (p && num(p[key]) ? p[key] : null);
  const laneOf = (p) => (LANES.includes(p.position) ? p.position : '游走');
  let panelMode = 'duel';
  let duelMode = 'deep';
  let panelBound = false;
  let heatLane = LANES[0];
  let heatState = null;
  let heatBound = false;
  let heatTimer = null;
  let battleState = null;
  let battleBound = false;
  const HEAT_WINDOW = 90; // 热区时间窗（秒）

  /* 入侵：以对侧半区（推进进度 > 50%）为准；连续 2 个采样（≈4 秒）才算一次。
     静止 ≥12 秒的样本（阵亡停留等）既不计入分子也不计入分母。 */
  function invasionStats(positions, players, duration) {
    const step = positions.step || 2;
    const meta = new Map(players.map((p) => [`${p.camp}-${p.slot}`, p]));
    const wins = phaseWindows(duration);
    const phaseOf = (t) => {
      for (let i = 0; i < wins.length; i++) if (t < wins[i].end) return i;
      return Math.max(0, wins.length - 1);
    };
    const out = new Map();
    for (const src of positions.players) {
      const info = meta.get(`${src.camp}-${src.slot}`) || {};
      const forward = src.camp === 'blue' ? 1 : -1;
      const mask = activeMask(src.points, step);
      let total = 0, inside = 0, run = 0, runStart = 0, episodes = 0, first = null, longest = 0, peak = 0;
      const phaseIn = [0, 0, 0], phaseAll = [0, 0, 0];
      const windows = [];
      const close = (lastIndex) => {
        if (run >= 2) {
          episodes += 1;
          longest = Math.max(longest, run * step);
          windows.push([runStart * step, (lastIndex + 1) * step]);
        }
        run = 0;
      };
      for (let i = 0; i < src.points.length; i++) {
        const [x, y] = src.points[i];
        if (!mask[i]) { close(i - 1); continue; }
        const prog = clamp((x + y + 112) / 224, 0, 1);
        const depth = forward > 0 ? prog : 1 - prog;
        const phase = phaseOf(i * step);
        total += 1;
        phaseAll[phase] += 1;
        if (depth > peak) peak = depth;
        if (depth > HALF) {
          if (first === null) first = i * step;
          if (!run) runStart = i;
          run += 1;
          inside += 1;
          phaseIn[phase] += 1;
        } else close(i - 1);
      }
      close(src.points.length - 1);
      out.set(`${src.camp}-${src.slot}`, {
        label: info.label, hero: info.hero, camp: src.camp,
        rate: total ? inside / total * 100 : null,
        phases: phaseAll.map((n, k) => (n ? phaseIn[k] / n * 100 : null)),
        episodes, first, longest, peak: peak * 100, windows, seconds: total * step,
      });
    }
    return out;
  }

  const METRIC_BASE = [
    { key: 'gold', label: '经济', text: (v) => fmt(v) },
    { key: 'damage', label: '输出', text: (v) => fmt(v) },
    { key: 'taken', label: '承伤', text: (v) => fmt(v) },
    { key: 'participation', label: '参团', text: (v) => pct(v), rate: true },
    { key: 'cs', label: '发育', text: (v) => fmt(v) },
  ];

  /* 击杀账本：官方回放 battle.killInfo 逐次记录 killerObjID → objID。
     切C口径 = 击杀者分路为对抗路/打野，且被击杀者是对方中路/发育路。 */
  function killStatsFor(players, kills) {
    const stats = new Map();
    const laneOfHero = new Map();
    for (const p of players || []) laneOfHero.set(`${p.camp}-${p.hero}`, laneOf(p));
    for (const k of kills || []) {
      const key = `${k.killerCamp}-${k.killer}`;
      const row = stats.get(key) || { kills: 0, cutC: 0, targets: [] };
      row.kills += 1;
      const victimLane = laneOfHero.get(`${k.victimCamp}-${k.victim}`) || '';
      if (['中路', '发育路'].includes(victimLane)) {
        row.cutC += 1;
        if (!row.targets.includes(k.victim)) row.targets.push(k.victim);
      }
      stats.set(key, row);
    }
    return stats;
  }

  /* 打团存活：每场团战从开始到本人死亡（或团战结束）的秒数。
     `fights[].details` 是参战者，`deaths[]` 是死亡时刻；死亡时间落在团战窗口内
     才算这波阵亡，窗口外不算。 */
  function fightSurvival(players, fights, deaths) {
    const result = new Map();
    const deathRows = (deaths || []).slice().sort((a, b) => a.t - b.t);
    for (const fight of fights || []) {
      const start = Number(fight.t), end = Number(fight.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) continue;
      for (const row of fight.details || []) {
        const key = `${row.camp}-${row.hero}`;
        if (!row.hero) continue;
        const stat = result.get(key) || { seconds: 0, fights: 0, survived: 0 };
        const died = deathRows.find((d) => d.hero === row.hero && d.camp === row.camp
          && d.t >= start - 1 && d.t <= end + 1);
        stat.seconds += died ? Math.max(0, died.t - start) : end - start;
        stat.fights += 1;
        if (!died) stat.survived += 1;
        result.set(key, stat);
      }
    }
    return result;
  }

  /* 跑图（中单）：逐秒位置累计移动距离，换算成每分钟。位置数据是营地坐标，
     单位与地图一致；这里只做相对比较，不当作真实米数。 */
  function roamStats(positions, duration) {
    const result = new Map();
    const minutes = Number(duration) > 0 ? Number(duration) / 60 : null;
    if (!minutes) return result;
    for (const p of positions?.players || []) {
      if (!p.hero || !Array.isArray(p.points) || p.points.length < 2) continue;
      let distance = 0;
      for (let i = 1; i < p.points.length; i += 1) {
        const [x1, y1] = p.points[i - 1];
        const [x2, y2] = p.points[i];
        distance += Math.hypot(x2 - x1, y2 - y1);
      }
      result.set(`${p.camp}-${p.hero}`, distance / minutes);
    }
    return result;
  }

  /* 对位比较口径（教练 2026-11-10 第二/三波）：每个位置只显示该位置
     该看的指标。分均经济带评级、经济转输出判断无效输出、死亡 >2 预警；
     切C = 击杀对方中路/发育路（回放 killInfo，见上）。 */
  function metricPool(inv, duration, killStats, survival, roam, join) {
    const entry = (p) => (p ? inv.get(`${p.camp}-${p.slot}`) : null);
    const cutOf = (p) => (killStats ? killStats.get(`${p.camp}-${p.hero}`) : null);
    const surviveOf = (p) => (survival ? survival.get(`${p.camp}-${p.hero}`) : null);
    const roamOf = (p) => (roam ? roam.get(`${p.camp}-${p.hero}`) : null);
    const joinOf = (p) => (join ? join.get(`${p.camp}-${p.slot}`) : null);
    return {
      gpm: { label: '分均经济', text: (v) => fmt(Math.round(v)), grade: true,
        get: (p) => gpmOf(p, duration) },
      conversion: { label: '经济转输出', text: (v) => fmt(v, 2),
        get: (p) => read(p, 'damageConversion') },
      damage: { label: '输出', text: (v) => fmt(v), get: (p) => read(p, 'damage') },
      taken: { label: '承伤', text: (v) => fmt(v), get: (p) => read(p, 'taken') },
      participation: { label: '参团', text: (v) => pct(v), rate: true,
        get: (p) => read(p, 'participation') },
      deaths: { label: '死亡', text: (v) => fmt(v), noBar: true,
        get: (p) => read(p, 'deaths'), alert: (v) => v > 2 },
      cs: { label: '发育', text: (v) => fmt(v), get: (p) => read(p, 'cs') },
      jungle: { label: '野怪经济', text: (v) => fmt(v), get: (p) => read(p, 'jungleGold') },
      control: { label: '控制时长', text: (v) => fmt(v), get: (p) => read(p, 'control') },
      healing: { label: '治疗量', text: (v) => fmt(v), get: (p) => read(p, 'healing') },
      takenPerDeath: { label: '每死承伤', text: (v) => fmt(v), get: (p) => read(p, 'takenPerDeath') },
      tower: { label: '对塔伤害', text: (v) => fmt(v), get: (p) => read(p, 'towerDamage') },
      rating: { label: '评分', text: (v) => fmt(v, 1), get: (p) => read(p, 'rating') },
      cutC: killStats ? {
        label: '切C', text: (v) => fmt(v), noBar: true,
        get: (p) => { const s = cutOf(p); return s ? s.cutC : 0; },
        tip: (p) => {
          const s = cutOf(p);
          if (!s) return '';
          return s.cutC
            ? `击杀对方中路/发育路 ${s.cutC} 次${s.targets.length ? '：' + s.targets.join('、') : ''} · 本局总击杀 ${s.kills}`
            : `本局总击杀 ${s.kills}，没有击杀对方中路/发育路`;
        },
      } : null,
      survival: survival ? {
        label: '打团存活', text: (v) => `${fmt(v, 1)} 秒`, noBar: true,
        get: (p) => { const s = surviveOf(p); return s && s.fights ? s.seconds / s.fights : null; },
        tip: (p) => {
          const s = surviveOf(p);
          if (!s || !s.fights) return '本局没有参战记录';
          return `${s.fights} 波团战，存活 ${s.survived} 波（${pct(s.survived / s.fights * 100)}），场均存活 ${fmt(s.seconds / s.fights, 1)} 秒`;
        },
      } : null,
      roam: roam ? {
        label: '跑图', text: (v) => `${fmt(v)}/分`, noBar: true,
        get: (p) => { const v = roamOf(p); return num(v) ? v : null; },
        tip: (p) => {
          const v = roamOf(p);
          return num(v) ? `本局平均每分钟移动 ${fmt(v)} 个地图单位（位置数据累计）；用于同位置横向比较` : '';
        },
      } : null,
      joinLane: join ? {
        label: '并线', text: (v) => `${fmt(v)} 次`, noBar: true,
        get: (p) => { const s = joinOf(p); return s ? s.total : null; },
        tip: (p) => {
          const s = joinOf(p);
          if (!s) return '本局没有逐秒位置，算不了并线';
          const parts = Object.keys(LANE_PATH)
            .filter((lane) => s.lanes[lane])
            .map((lane) => `${lane} ${s.lanes[lane]}`);
          const first = s.waves.length ? time(s.waves[0].t) : null;
          return [`本局并线 ${s.total} 次`, parts.join(' · '), first ? `第一次 ${first}` : '',
            '口径：那波兵出发后，和打野在走廊里聚成 2～3 人并待满 4 秒，一波一线记一次；射手+辅助这种固定搭档不算'].filter(Boolean).join(' · ');
        },
      } : null,
      invade: inv ? {
        label: '入侵', text: (v) => pct(v), rate: true,
        get: (p) => { const s = entry(p); return s ? s.rate : null; },
        tip: (p) => {
          const s = entry(p);
          if (!s) return '';
          return `前 ${pct(s.phases[0])} / 中 ${pct(s.phases[1])} / 后 ${pct(s.phases[2])} · ${s.episodes} 次 · 首次 ${s.first === null ? '—' : time(s.first)} · 最长 ${fmt(s.longest)} 秒 · 纵深峰值 ${pct(s.peak)}`;
        },
      } : null,
    };
  }
  /* 分路关注的指标（来自教练第三波；视野价值/控龙率等待数据源）。
     切C 只对对抗路/打野有意义（回放 killInfo 可算，其余分路按同口径也能出数）。 */
  const LANE_METRICS = {
    '对抗路': ['gpm', 'conversion', 'taken', 'tower', 'cutC', 'deaths', 'participation'],
    '打野': ['gpm', 'jungle', 'joinLane', 'damage', 'cutC', 'invade', 'deaths', 'participation'],
    '中路': ['gpm', 'conversion', 'damage', 'roam', 'control', 'deaths', 'participation'],
    '发育路': ['gpm', 'conversion', 'damage', 'survival', 'deaths', 'cs', 'participation'],
    '游走': ['participation', 'control', 'healing', 'takenPerDeath', 'taken', 'deaths'],
  };

  /* 营地派生卡片（dataBehaviorV2）里，每个位置先亮一张教练点名的：
     辅助的视野价值、中单/射手的「经济转有效伤害」、打野的「反野总经济」、
     对抗路的「对位经济差」。这些卡片营地按分路自适应下发，可能整局没有，
     所以缺了就显示「—」并在悬停里说明，不补 0。 */
  const LANE_TILE = {
    '对抗路': '对位经济差',
    '打野': '反野总经济',
    '中路': '经济转有效伤害',
    '发育路': '经济转有效伤害',
    '游走': '视野价值',
  };

  function campTileOf(player, name) {
    const list = (player && player.campTiles) || [];
    return list.find((tile) => tile.name === name) || null;
  }

  function tileText(player, name) {
    const hit = campTileOf(player, name);
    if (!hit) return { text: '—', tip: `这一局营地没有给这个位置下发「${name}」` };
    const note = hit.note ? ` · 营地同位置对比 ${hit.note}` : '';
    return { text: hit.raw, tip: `${hit.hint || name}${note} · 营地口径未公开，只做同局参考` };
  }

  /* 两名选手的全部营地卡片：默认收起，展开才占高度。 */
  function tileDetails(a, b) {
    const total = ((a && a.campTiles) || []).length + ((b && b.campTiles) || []).length;
    if (!total) return '';
    const groups = [['lane', '分路表现'], ['team', '团队贡献'], ['fight', '战斗操作']];
    const column = (player, side) => {
      const list = (player && player.campTiles) || [];
      if (!list.length) return `<div class="md-camp-col ${side}"><b>${esc(player?.label || player?.hero || '—')}</b><p class="md-camp-empty">没有下发卡片</p></div>`;
      const body = groups.map(([key, label]) => {
        const items = list.filter((tile) => tile.group === key);
        if (!items.length) return '';
        return `<div class="md-camp-group"><b>${label}</b>${items.map((tile) => `<span title="${esc(tile.hint || tile.name)}${tile.note ? ' · 营地同位置对比 ' + esc(tile.note) : ''}"><i>${esc(tile.name)}</i><em>${esc(tile.raw)}</em></span>`).join('')}</div>`;
      }).join('');
      return `<div class="md-camp-col ${side}"><b>${esc(player?.label || player?.hero || '—')}</b>${body}</div>`;
    };
    return `<details class="md-camp"><summary>营地卡片 ${total} 条 <small>分路表现 / 团队贡献 / 战斗操作，营地原文，口径未公开</small></summary>
      <div class="md-camp-body">${column(a, 'own')}${column(b, 'foe')}</div></details>`;
  }

  function buildMetrics(inv) {
    const metrics = METRIC_BASE.map((m) => ({ ...m, get: (p) => read(p, m.key) }));
    if (!inv) return metrics;
    const entry = (p) => (p ? inv.get(`${p.camp}-${p.slot}`) : null);
    metrics.push({
      key: 'invade', label: '入侵', text: (v) => pct(v), rate: true,
      get: (p) => { const s = entry(p); return s ? s.rate : null; },
      tip: (p) => {
        const s = entry(p);
        if (!s) return '';
        return `前 ${pct(s.phases[0])} / 中 ${pct(s.phases[1])} / 后 ${pct(s.phases[2])} · ${s.episodes} 次 · 首次 ${s.first === null ? '—' : time(s.first)} · 最长 ${fmt(s.longest)} 秒 · 纵深峰值 ${pct(s.peak)}`;
      },
    });
    return metrics;
  }

  /* 一张雷达同时画两人：每个轴按两人最大值归一，形状差就是同分路的差 */
  function pairRadar(a, b, metrics) {
    const n = metrics.length;
    const size = 132, c = size / 2, R = 44;
    const angle = (i) => -Math.PI / 2 + i * Math.PI * 2 / n;
    const pt = (i, r) => [c + Math.cos(angle(i)) * r, c + Math.sin(angle(i)) * r];
    const scale = metrics.map((m) => Math.max(1, m.get(a) || 0, m.get(b) || 0));
    const area = (p, side) => {
      if (!p) return '';
      const points = metrics.map((m, i) => pt(i, Math.max(2.5, clamp((m.get(p) || 0) / scale[i], 0, 1) * R)));
      return `<polygon class="md-fl-area ${side}" points="${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}"/>`;
    };
    const ring = (k) => `<polygon class="md-fl-ring" points="${metrics.map((_, i) => pt(i, R * k).map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = metrics.map((_, i) => {
      const [x, y] = pt(i, R);
      return `<line class="md-fl-spoke" x1="${c}" y1="${c}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
    }).join('');
    /* 轴标签去掉：132px 里放 5 个中文标签会被 viewBox 裁掉一半，看起来像乱码。
       右侧每一行就是同一顺序的轴，标签在那一边已经有了。 */
    const name = `${(a && (a.label || a.hero)) || '本队'} 与 ${(b && (b.label || b.hero)) || '对手'}`;
    return `<svg class="md-fl" viewBox="0 0 ${size} ${size}" role="img" aria-label="对位雷达：${esc(name)}">${[0.34, 0.67, 1].map(ring).join('')}${spokes}${area(a, 'own')}${area(b, 'foe')}</svg>`;
  }

  function duelView(players, ownCamp, pool) {
    const pick = (camp) => {
      const map = new Map();
      for (const p of players) if (p.camp === camp) map.set(laneOf(p), p);
      return map;
    };
    const mine = pick(ownCamp), theirs = pick(ownCamp === 'blue' ? 'red' : 'blue');
    const who = (p, side) => (p
      ? `<span class="md-vs-id ${side}">${portrait(p.hero)}<span><b>${esc(p.label || p.hero || '—')}</b><small>${esc(p.hero || '—')}</small></span></span>`
      : `<span class="md-vs-id ${side} empty">未匹配</span>`);
    /* 数值列固定给评级章留一格：不然带「优秀」的那一行数字会往左缩，
       整列数字右边缘参差，看起来像没对齐。没评级也占位（空白）。 */
    const numCell = (side, value, chip = '', extra = '') => `<b class="md-vsm-num ${side}${extra}">${
      value === null || value === undefined ? '<span class="md-vsm-val">—</span>' : `<span class="md-vsm-val">${value}</span>`
    }<em class="md-grade${chip ? ' ' + chip.level : ' is-blank'}">${chip ? chip.label : ''}</em></b>`;
    const rows = LANES.map((lane) => {
      const a = mine.get(lane), b = theirs.get(lane);
      const metrics = (LANE_METRICS[lane] || Object.keys(pool))
        .map((key) => pool[key]).filter(Boolean);
      const bars = metrics.map((m) => {
        const x = m.get(a), y = m.get(b);
        const tip = m.tip
          ? [a, b].filter(Boolean).map((p) => `${p.label || p.hero || '—'}：${m.tip(p)}`).join(' / ')
          : '';
        const chipX = m.grade && num(x) ? goldGrade(lane, x) : null;
        const chipY = m.grade && num(y) ? goldGrade(lane, y) : null;
        if (m.noBar) {
          const alertX = m.alert && num(x) && m.alert(x);
          const alertY = m.alert && num(y) && m.alert(y);
          return `<div class="md-vsm" data-lead="tie"${tip ? ` title="${esc(tip)}"` : ''}>
            <span class="md-vsm-label">${m.label}</span>
            ${numCell('own', num(x) ? m.text(x) : null, null, alertX ? ' is-alert' : '')}
            <span class="md-vsm-track is-flat"></span>
            ${numCell('foe', num(y) ? m.text(y) : null, null, alertY ? ' is-alert' : '')}
          </div>`;
        }
        const sum = (x || 0) + (y || 0);
        const share = sum > 0 ? (x || 0) / sum * 100 : 50;
        const lead = (x || 0) > (y || 0) ? 'own' : (x || 0) < (y || 0) ? 'foe' : 'tie';
        return `<div class="md-vsm" data-lead="${lead}"${tip ? ` title="${esc(tip)}"` : ''}>
          <span class="md-vsm-label">${m.label}</span>
          ${numCell('own', num(x) ? m.text(x) : null, chipX)}
          <span class="md-vsm-track"><i style="width:${share.toFixed(1)}%"></i></span>
          ${numCell('foe', num(y) ? m.text(y) : null, chipY)}
        </div>`;
      }).join('');
      const tileName = LANE_TILE[lane];
      const ownTile = tileText(a, tileName);
      const foeTile = tileText(b, tileName);
      const tileRow = `<div class="md-vsm md-vsm-camp" data-lead="tie">
        <span class="md-vsm-label" title="营地十人面板的分路派生卡片">${tileName}</span>
        <b class="md-vsm-num own" title="${esc(ownTile.tip)}"><span class="md-vsm-val">${esc(ownTile.text)}</span><em class="md-grade is-blank"></em></b>
        <span class="md-vsm-track is-flat"></span>
        <b class="md-vsm-num foe" title="${esc(foeTile.tip)}"><span class="md-vsm-val">${esc(foeTile.text)}</span><em class="md-grade is-blank"></em></b>
      </div>`;
      return `<article class="md-vs">
        <div class="md-vs-head"><span class="md-vs-lane">${lane}</span>${who(a, 'own')}${who(b, 'foe')}</div>
        <div class="md-vs-body">${pairRadar(a, b, metrics)}<div class="md-vs-metrics">${bars}${tileRow}</div></div>
        ${tileDetails(a, b)}
      </article>`;
    }).join('');
    return `<div class="md-duels">${rows}</div>`;
  }

  function teamTable(players, camp, label, side, metrics, inv) {
    const team = players.filter((p) => p.camp === camp)
      .sort((a, b) => LANES.indexOf(laneOf(a)) - LANES.indexOf(laneOf(b))).slice(0, 5);
    if (!team.length) return '';
    const cols = `grid-template-columns:92px repeat(${metrics.length}, minmax(0, 1fr))`;
    const totals = metrics.map((m) => team.reduce((sum, p) => sum + (m.get(p) || 0), 0));
    const values = team.map((p) => metrics.map((m, i) => {
      const v = m.get(p);
      if (!num(v)) return null;
      return m.rate ? v : (totals[i] ? v / totals[i] * 100 : 0);
    }));
    const scale = metrics.map((_, i) => Math.max(1, ...values.map((row) => row[i] ?? 0)));
    const head = `<div class="md-tg-row md-tg-head" style="${cols}"><span>选手</span>${metrics.map((m) => `<span>${m.label}</span>`).join('')}</div>`;
    const body = team.map((p, r) => `<div class="md-tg-row" style="${cols}">
      <span class="md-tg-who"><b>${esc(p.label || p.hero || '—')}</b><small>${esc(p.hero || '—')}</small></span>
      ${values[r].map((v, i) => (v === null
        ? '<span class="md-tg-cell empty">—</span>'
        : `<span class="md-tg-cell"${metrics[i].tip ? ` title="${esc(metrics[i].tip(p))}"` : ''}><i style="--a:${(v / scale[i]).toFixed(2)}"></i><b>${pct(v)}</b></span>`)).join('')}
    </div>`).join('');
    let note = inv
      ? '经济 / 输出 / 承伤 / 发育为队内份额，参团、入侵为比率'
      : '经济 / 输出 / 承伤 / 发育为队内份额，参团为参团率';
    if (inv) {
      const pick = (p) => inv.get(`${p.camp}-${p.slot}`);
      const rates = team.map((p) => pick(p)?.rate).filter((v) => num(v));
      const episodes = team.reduce((sum, p) => sum + (pick(p)?.episodes || 0), 0);
      const firsts = team.map((p) => pick(p)?.first).filter((v) => num(v));
      if (rates.length) {
        note += ` · 全队入侵 ${pct(rates.reduce((a, b) => a + b, 0) / rates.length)}`;
        if (episodes) note += `，共 ${fmt(episodes)} 次`;
        if (firsts.length) note += `，首次 ${time(Math.min(...firsts))}`;
      }
    }
    return `<div class="md-team ${side}">
      <div class="md-team-top"><b>${esc(label)}</b><span>${team.length} 人</span></div>
      <div class="md-tg">${head}${body}</div>
      <p class="md-team-note">${note}</p>
    </div>`;
  }

  function panel(players, ownCamp, positions, duration, kills, fights, deaths) {
    if (!players || !players.length) return `<div class="empty">这场比赛还没有十人面板数据。</div>`;
    if (!ownCamp) return `<div class="empty">阵营未知，无法做对位比较。</div>`;
    /* 兼容 ownCamp 为 left / right 的历史写法 */
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    const foeCamp = camp === 'blue' ? 'red' : 'blue';
    const ownName = `本队 · ${camp === 'blue' ? '蓝方' : '红方'}`;
    const foeName = `对手 · ${foeCamp === 'blue' ? '蓝方' : '红方'}`;
    const inv = positions && positions.players && positions.players.length ? invasionStats(positions, players, duration) : null;
    const join = positions && positions.players && positions.players.length
      ? joinLaneStats(positions, players, laneOf) : null;
    const metrics = buildMetrics(inv);
    const pool = metricPool(inv, duration, killStatsFor(players, kills),
      fightSurvival(players, fights, deaths), roamStats(positions, duration), join);
    const tab = (mode, text) => `<button type="button" role="tab" class="md-seg-btn${panelMode === mode ? ' is-on' : ''}"
      aria-selected="${panelMode === mode}" data-md-panel-mode="${mode}">${text}</button>`;
    const note = inv
      ? '对位看同分路两人的形状差；同队看资源分配。入侵 = 进入对侧半区的时间占比，悬停可看次数与首次时间；并线按兵线波次算（近似）'
      : '对位看同分路两人的形状差；同队看资源在本队内部的分配（本局没有位置数据，入侵与并线缺省）';
    return `<div class="md-panel" data-md-panel>
      <div class="md-panel-bar">
        <div class="md-seg" role="tablist" aria-label="十人面板口径">${tab('duel', '对位比较')}${tab('team', '同队比较')}</div>
        <p class="md-panel-note">${note}</p>
      </div>
      <div class="md-panel-view" data-md-view="duel"${panelMode === 'duel' ? '' : ' hidden'}>${duelView(players, camp, pool)}</div>
      <div class="md-panel-view" data-md-view="team"${panelMode === 'team' ? '' : ' hidden'}>
        <div class="md-teams">${teamTable(players, camp, ownName, 'own', metrics, inv)}${teamTable(players, foeCamp, foeName, 'foe', metrics, inv)}</div>
      </div>
    </div>`;
  }

  function bindPanel(root) {
    if (panelBound) return;
    panelBound = true;
    root.addEventListener('click', (event) => {
      const hit = event.target.closest ? event.target.closest('[data-md-panel-mode],[data-md-duel-mode]') : null;
      if (!hit) return;
      const isPanel = Boolean(hit.dataset.mdPanelMode);
      const mode = isPanel ? hit.dataset.mdPanelMode : hit.dataset.mdDuelMode;
      const box = hit.closest(isPanel ? '[data-md-panel]' : '[data-md-duel]');
      if (!box) return;
      if (isPanel) panelMode = mode; else duelMode = mode;
      box.querySelectorAll(isPanel ? '[data-md-panel-mode]' : '[data-md-duel-mode]').forEach((b) => {
        const on = (isPanel ? b.dataset.mdPanelMode : b.dataset.mdDuelMode) === mode;
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-selected', String(on));
      });
      box.querySelectorAll(isPanel ? '[data-md-view]' : '[data-md-duel-view]').forEach((view) => {
        view.hidden = (isPanel ? view.dataset.mdView : view.dataset.mdDuelView) !== mode;
      });
    });
  }

  /* ── 中野辅集结：三人两两距离 ≤ 22.5（对角线 15%）且持续 ≥ 5 秒 ──── */
  function proximity(positions, players) {
    const out = new Map();
    if (!positions || !positions.players?.length) return out;
    const step = positions.step || 2;
    const meta = new Map(players.map((p) => [`${p.camp}-${p.slot}`, p]));
    const trio = ['中路', '打野', '游走'];
    const pick = (camp) => trio.map((lane) => positions.players.find((src) => {
      const info = meta.get(`${src.camp}-${src.slot}`);
      return src.camp === camp && info && laneOf(info) === lane;
    }));
    const pairs = [[0, 1], [0, 2], [1, 2]];
    for (const camp of ['blue', 'red']) {
      const three = pick(camp);
      if (three.some((src) => !src)) continue;
      const masks = three.map((src) => activeMask(src.points, step));
      const n = Math.min(...three.map((src) => src.points.length));
      let valid = 0, forming = 0, run = 0, count = 0, longest = 0, gapSum = 0;
      const close = () => {
        if (run * step >= PROX_SECONDS) { count += 1; longest = Math.max(longest, run * step); }
        run = 0;
      };
      for (let i = 0; i < n; i++) {
        if (!masks.every((mask) => mask[i])) { close(); continue; }
        const pts = three.map((src) => src.points[i]);
        const distances = pairs.map(([a, b]) => Math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]));
        valid += 1;
        gapSum += (distances[0] + distances[1] + distances[2]) / 3;
        if (distances.every((d) => d <= PROX_RADIUS)) { run += 1; forming += 1; } else close();
      }
      close();
      out.set(camp, {
        rate: valid ? forming / valid * 100 : null,
        count, longest,
        gap: valid ? gapSum / valid : null,
        seconds: valid * step,
      });
    }
    return out;
  }

  /* 入侵窗口的结果归因：击杀取团战账本（kills），目标取官方事件流（资源/建筑）。
     窗口取 [进入 -5 秒, 离开 +10 秒]，同一事件/击杀只记一次。 */
  function invadeSummary(inv, events, kills) {
    const out = new Map();
    if (!inv) return out;
    for (const camp of ['blue', 'red']) {
      const entries = [...inv.values()].filter((item) => item.camp === camp);
      if (!entries.length) continue;
      const windows = entries.flatMap((item) => item.windows);
      const won = new Set(), lost = new Set(), objects = new Set();
      for (const [start, end] of windows) {
        for (const kill of kills || []) {
          if (!num(kill.t) || kill.t < start - 5 || kill.t > end + 10) continue;
          const key = `${kill.t}-${kill.killer}-${kill.victim}`;
          if (kill.killerCamp === camp) won.add(key);
          else if (kill.victimCamp === camp) lost.add(key);
        }
        for (const event of events || []) {
          if (!num(event.t) || event.t < start - 5 || event.t > end + 10) continue;
          objects.add(`${event.kind}-${event.t}-${event.id || ''}`);
        }
      }
      out.set(camp, {
        episodes: entries.reduce((sum, item) => sum + item.episodes, 0),
        kills: won.size, lost: lost.size, objects: objects.size,
      });
    }
    return out;
  }

  /* ── 打野并线：三段（0–4 / 4–10 / 10 分钟后）× 三路，两队对照 ────────
     口径完全交给 joinLaneStats（那波兵出发后，打野和该路队友在走廊里聚成 2～3 人、
     待满 4 秒算一次，一波一线一次）；这里只负责把它画清楚。 */
  function jungleJoin(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    if (camp !== 'blue' && camp !== 'red') return '';
    const foeCamp = camp === 'blue' ? 'red' : 'blue';
    const join = joinLaneStats(positions, players, laneOf);
    const wins = phaseWindows(duration);
    const phaseOf = (t) => {
      const index = wins.findIndex((w) => t < w.end);
      return index < 0 ? wins.length - 1 : index;
    };
    const jungler = (side) => {
      const player = (players || []).find((p) => p.camp === side && laneOf(p) === '打野');
      if (!player) return null;
      const stat = join.get(`${player.camp}-${player.slot}`) || { total: 0, lanes: {}, waves: [] };
      const phases = wins.map(() => 0);
      const lanes = { '对抗路': 0, '中路': 0, '发育路': 0 };
      const grid = wins.map(() => ({ '对抗路': 0, '中路': 0, '发育路': 0 }));
      for (const wave of stat.waves) {
        const index = phaseOf(wave.t);
        phases[index] += 1;
        lanes[wave.lane] = (lanes[wave.lane] || 0) + 1;
        if (grid[index]) grid[index][wave.lane] = (grid[index][wave.lane] || 0) + 1;
      }
      return {
        player, stat, phases, lanes, grid,
        total: stat.waves.length,
        triples: stat.waves.filter((wave) => wave.size >= 3).length,
      };
    };
    const own = jungler(camp);
    const foe = jungler(foeCamp);
    if (!own && !foe) return '';
    const total = duration && duration > 0 ? duration : 1;
    const pctOf = (value) => `${clamp(value / total * 100, 0, 100).toFixed(2)}%`;

    /* 每条路的点只画在该路上：把全量点按路分一次，避免三行重复画一遍 */
    const laneDots = (side, lane) => {
      const entry = side === 'own' ? own : foe;
      if (!entry) return '';
      return entry.stat.waves.filter((wave) => wave.lane === lane).map((wave) => {
        const label = `${time(wave.t)} · ${wave.lane} · ${wave.size} 人`;
        return `<i class="md-jg-dot ${side}${wave.size >= 3 ? ' is-trio' : ''}"`
          + ` style="--x:${pctOf(wave.t)}" title="${esc(label)}"></i>`;
      }).join('');
    };
    /* 三段分界：每条路的轨道里画一条竖虚线，横跨整条时间轴 */
    const cuts = wins.slice(1).map((win) => `<span class="md-jg-cut" style="left:${pctOf(win.start)}"></span>`).join('');
    const laneRow = (lane) => `<div class="md-jg-row">
        <span class="md-jg-lane">${lane}</span>
        <div class="md-jg-track">
          ${cuts}
          <div class="md-jg-marks own">${laneDots('own', lane)}</div>
          <span class="md-jg-line"></span>
          <div class="md-jg-marks foe">${laneDots('foe', lane)}</div>
        </div>
        <span class="md-jg-rowcount"><b class="own">${own ? own.lanes[lane] || 0 : 0}</b><em>/</em><b class="foe">${foe ? foe.lanes[lane] || 0 : 0}</b></span>
      </div>`;

    const bands = wins.map((win) => {
      const left = clamp(win.start / total * 100, 0, 100);
      const width = clamp((win.end - win.start) / total * 100, 0, 100);
      return `<span class="md-jg-band" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%">`
        + `<em>${esc(win.label)}</em></span>`;
    }).join('');

    const card = (entry, side) => {
      if (!entry) return `<div class="md-jg-card ${side} is-empty"><span class="md-jg-tag">${side === 'own' ? '本队' : '对手'}打野</span><p>这局没有这个位置的位置数据</p></div>`;
      const player = entry.player;
      const peak = Math.max(1, ...entry.phases);
      /* 最后一段时长每局不一样（10 分钟后到结束），只给这一段折算成「次 / 10 分钟」 */
      const last = wins[wins.length - 1];
      const lastSeconds = last ? Math.max(0, last.end - last.start) : 0;
      const phases = wins.map((win, index) => {
        const isLast = index === wins.length - 1;
        const rate = isLast && lastSeconds >= 60
          ? `<small class="md-jg-rate">${(entry.phases[index] / (lastSeconds / 600)).toFixed(1)}/10 分</small>`
          : '';
        return `<span class="md-jg-phase">
          <small>${esc(win.label)}</small><b>${entry.phases[index]}</b>${rate}
          <i style="--v:${(entry.phases[index] / peak).toFixed(2)}"></i></span>`;
      }).join('');
      return `<div class="md-jg-card ${side}">
        <span class="md-jg-tag">${side === 'own' ? '本队' : '对手'}打野</span>
        <div class="md-jg-who">${portrait(player.hero)}<span><b>${esc(player.label || player.hero || '—')}</b><small>${esc(player.hero || '—')}</small></span></div>
        <div class="md-jg-big">${entry.total}<em>次并线</em></div>
        <div class="md-jg-chips">
          <span class="md-jg-chip is-trio">三人 <b>${entry.triples}</b></span>
          <span class="md-jg-chip">双人 <b>${entry.total - entry.triples}</b></span>
        </div>
        <div class="md-jg-phases">${phases}</div>
      </div>`;
    };

    const head = `<span>路</span>${wins.map((win) => `<span>${esc(win.label)}</span>`).join('')}<span>合计</span>`;
    const body = ['对抗路', '中路', '发育路'].map((lane) => {
      const cells = wins.map((_, index) => {
        const ownValue = own ? own.grid[index][lane] || 0 : 0;
        const foeValue = foe ? foe.grid[index][lane] || 0 : 0;
        const heat = clamp((ownValue + foeValue) / 3, 0, 1);
        const dim = ownValue + foeValue === 0;
        return `<span class="md-jg-cell${dim ? ' is-zero' : ''}" style="--k:${heat.toFixed(2)}">`
          + `<b class="own">${ownValue}</b><em>/</em><b class="foe">${foeValue}</b></span>`;
      }).join('');
      const ownTotal = own ? own.lanes[lane] || 0 : 0;
      const foeTotal = foe ? foe.lanes[lane] || 0 : 0;
      return `<div class="md-jg-trow"><span class="md-jg-tlane">${lane}</span>${cells}`
        + `<span class="md-jg-total"><b class="own">${ownTotal}</b><em>/</em><b class="foe">${foeTotal}</b></span></div>`;
    }).join('');

    const best = (entry) => {
      if (!entry) return '';
      const top = ['对抗路', '中路', '发育路']
        .map((lane) => [lane, entry.lanes[lane] || 0])
        .sort((a, b) => b[1] - a[1])[0];
      if (!top || !top[1]) return '';
      const early = entry.phases[0] || 0;
      return `${top[0]}最多（${top[1]} 次）· 对线期 ${early} 次`;
    };
    const line = (side, entry) => (entry
      ? `<p class="md-jg-line-${side}">${side === 'own' ? '本队' : '对手'}打野 <b>${entry.total}</b> 次并线，${esc(best(entry))}</p>`
      : '');
    const gap = own && foe ? own.total - foe.total : null;
    const verdict = gap === null
      ? ''
      : `${gap === 0 ? '两队打野并线次数持平' : `本队打野${gap > 0 ? '多' : '少'} ${Math.abs(gap)} 次`}`;

    return `<div class="md-jg">
      <div class="md-jg-cards">${card(own, 'own')}
        <div class="md-jg-vs"><b>并线</b>
          ${gap === null ? '' : `<strong class="${gap >= 0 ? 'own' : 'foe'}">${gap > 0 ? '+' : ''}${gap}</strong>`}
          <span>${esc(verdict)}</span>
          <i class="md-jg-key"><em class="md-jg-dot own"></em>本队<em class="md-jg-dot foe"></em>对手</i>
          <i class="md-jg-key"><em class="md-jg-dot is-trio"></em>三人并线</i>
        </div>
        ${card(foe, 'foe')}</div>
      <div class="md-jg-timeline">
        <div class="md-jg-bands">${bands}</div>
        <div class="md-jg-rows">${['对抗路', '中路', '发育路'].map(laneRow).join('')}</div>
        <div class="md-jg-axis"><span>0:00</span>${wins.slice(1).map((win) => `<span>${time(win.start)}</span>`).join('')}<span>${time(total)}</span></div>
      </div>
      <div class="md-jg-table"><div class="md-jg-thead">${head}</div>${body}</div>
      <p class="md-jg-tcap">表格读法：格子里 <b class="own">本队</b> / <b class="foe">对手</b> 的打野并线次数，底色越深＝两队在这条路这一段的并线越多。</p>
      <p class="md-jg-note">${line('own', own)}${line('foe', foe)}
        <span>怎么算：第 n 波兵 10+33(n−1) 秒出发，打野和该路队友在走廊里 2～3 人聚在一起满 4 秒算一次，一波一线最多一次；组里必须有打野——射手 + 辅助这种固定搭档不算；基地内、阵亡与 5 人推挤不计。最后一段按时长折算成「次 / 10 分钟」。近似值，只做同局横向比较。</span></p>
    </div>`;
  }

  /* ── 中野辅与入侵：两队对照 ─────────────────────────────────────── */
  function cohesion(positions, players, ownCamp, duration, events, kills) {
    if (!positions || !positions.players?.length) return '';
    const prox = proximity(positions, players);
    if (!prox.size) return '';
    const inv = invadeSummary(invasionStats(positions, players, duration), events, kills);
    const card = (camp) => {
      const item = prox.get(camp);
      const side = camp === ownCamp ? 'own' : 'foe';
      const name = camp === 'blue' ? '蓝方' : '红方';
      const title = `${camp === ownCamp ? '本队' : '对手'} · ${name}`;
      if (!item) return `<article class="md-coh ${side}"><header><b>${title}</b><span>中野辅</span></header><p class="md-coh-empty">缺少中/野/辅位置数据</p></article>`;
      const invade = inv.get(camp);
      const row = (label, value) => `<span><small>${label}</small><b>${value}</b></span>`;
      return `<article class="md-coh ${side}">
        <header><b>${title}</b><span>中野辅集结</span></header>
        <div class="md-coh-nums">
          ${row('集结率', pct(item.rate))}
          ${row('集结次数', fmt(item.count))}
          ${row('最长集结', item.longest ? `${fmt(item.longest)} 秒` : '—')}
          ${row('平均间距', num(item.gap) ? fmt(item.gap, 1) : '—')}
        </div>
        <p class="md-coh-invade">入侵 ${fmt(invade ? invade.episodes : 0)} 次 · 期间击杀 ${fmt(invade ? invade.kills : 0)} / 阵亡 ${fmt(invade ? invade.lost : 0)} · 资源·建筑 ${fmt(invade ? invade.objects : 0)}</p>
      </article>`;
    };
    return `<div class="md-coh-grid">${card(ownCamp)}${card(ownCamp === 'blue' ? 'red' : 'blue')}</div>`;
  }

  /* ── 热区：时间窗 + 十人 / 对位两视图（canvas 重绘） ─────────────── */
  function heat(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const step = positions.step || 2;
    const byKey = new Map(players.map((p) => [`${p.camp}-${p.slot}`, p]));
    const list = positions.players.map((src) => {
      const info = byKey.get(`${src.camp}-${src.slot}`) || src;
      const mask = activeMask(src.points, step);
      const cells = new Int16Array(src.points.length).fill(-1);
      const enemy = new Uint8Array(src.points.length);
      const forward = src.camp === 'blue' ? 1 : -1;
      for (let i = 0; i < src.points.length; i++) {
        if (!mask[i]) continue;
        const [x, y] = src.points[i];
        const gx = clamp(Math.floor((x + MAP) / (MAP * 2) * GRID), 0, GRID - 1);
        const gy = clamp(Math.floor((y + MAP) / (MAP * 2) * GRID), 0, GRID - 1);
        cells[i] = gy * GRID + gx;
        const depth = forward > 0 ? progress(x, y) : 1 - progress(x, y);
        enemy[i] = depth > HALF ? 1 : 0;
      }
      return { camp: src.camp, slot: src.slot, points: src.points, cells, enemy, info };
    });
    const total = duration || (list[0] ? list[0].points.length * step : 0);
    heatState = { step, duration: total, list };
    /* 战队口径的三段：0–4 对线、4–10 发育、10 分钟以后到结束 */
    const [label1, label2, label3] = (phaseWindows(total) || []).map((w) => w.label).concat(['后期']).slice(0, 3);
    const phaseLabel = [
      `${label1} 0–4`,
      `${label2} 4–10`,
      `${label3} 10+`,
    ];

    const side = (p) => (p.camp === ownCamp ? 'own' : 'foe');
    const canvas = (p, size) => `<canvas class="md-heat-canvas" width="${GRID * size}" height="${GRID * size}"
      data-heat-card="${p.camp}-${p.slot}" data-camp="${p.camp}" data-side="${side(p)}"
      role="img" aria-label="${esc((p.info.label || p.info.hero || '') + ' 位置热区')}"></canvas>`;
    const laneCards = LANES.map((lane) => {
      const own = list.find((p) => p.camp === ownCamp && laneOf(p.info) === lane);
      const foe = list.find((p) => p.camp !== ownCamp && laneOf(p.info) === lane);
      if (!own && !foe) return '';
      const one = (p, kind) => (p ? `<div class="hl-side ${kind}">
          <div class="hl-head"><i class="${kind}"></i><b>${esc(p.info.label || p.info.hero || '—')}</b><span>${esc(p.info.hero || '')}</span></div>
          ${canvas(p, 14)}
          <div class="hl-meta"><b data-heat-pct="${p.camp}-${p.slot}">—</b> 在对侧半区</div>
        </div>` : '<div class="hl-side empty">没有对位数据</div>');
      return `<article class="md-heat-lane" data-lane="${lane}"${lane === heatLane ? '' : ' hidden'}>
        <div class="hl-pair">${one(own, 'own')}${one(foe, 'foe')}</div>
      </article>`;
    }).join('');

    return `<div class="md-heatwrap" data-md-heat>
      <div class="md-panel-bar">
        <button type="button" class="md-heat-play" data-heat-play aria-pressed="false">播放</button>
        <input type="range" class="md-heat-range" data-heat-range min="0" max="${Math.round(total)}" step="${step}" value="${Math.round(total)}" aria-label="热区时间轴">
        <span class="md-heat-clock" data-heat-clock>—</span>
        <label class="md-heat-pick"><span>分路</span>
          <select data-heat-lane aria-label="选择分路">
            ${LANES.map((lane) => `<option value="${lane}"${lane === heatLane ? ' selected' : ''}>${lane}</option>`).join('')}
          </select>
        </label>
      </div>
      <div class="md-heat-phases" data-heat-phases>
        ${phaseLabel.map((label, i) =>
          `<button type="button" class="md-heat-phase" data-heat-phase="${[240, 600, Math.round(total)][i]}">${label}</button>`).join('')}
      </div>
      <div class="md-heats md-heats-lane" data-heat-lanes>${laneCards}</div>
      <p class="md-panel-note">窗口 ${HEAT_WINDOW} 秒随指针滚动；静止 ≥12 秒的样本已剔除。格子颜色越深＝停留越久。分期按战队口径：对线 0–4、发育 4–10、10 分钟以后算后期。</p>
    </div>`;
  }

  function heatCounts(list, i0, i1) {
    const out = new Map();
    let max = 1;
    for (const p of list) {
      const counts = new Uint16Array(GRID * GRID);
      const end = Math.min(i1, p.cells.length - 1);
      let enemy = 0, total = 0;
      for (let i = i0; i <= end; i++) {
        const cell = p.cells[i];
        if (cell < 0) continue;
        counts[cell] += 1;
        if (counts[cell] > max) max = counts[cell];
        total += 1;
        if (p.enemy[i]) enemy += 1;
      }
      out.set(`${p.camp}-${p.slot}`, { counts, enemy, total });
    }
    return { out, max };
  }

  let heatSprites = null;
  function heatSprite(side) {
    if (!heatSprites) {
      const make = (rgb) => {
        const c = document.createElement('canvas');
        c.width = 64; c.height = 64;
        const g = c.getContext('2d');
        if (!g) return c;
        const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
        grad.addColorStop(0, `rgba(${rgb},1)`);
        grad.addColorStop(0.5, `rgba(${rgb},.5)`);
        grad.addColorStop(1, `rgba(${rgb},0)`);
        g.fillStyle = grad;
        g.fillRect(0, 0, 64, 64);
        return c;
      };
      heatSprites = { own: make('216, 178, 106'), foe: make('94, 201, 190') };
    }
    return heatSprites[side === 'foe' ? 'foe' : 'own'];
  }

  function drawHeat(canvas, counts, max, side) {
    const ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) return;
    const size = canvas.width;
    const cell = size / GRID;
    const rgb = side === 'foe' ? '94, 201, 190' : '216, 178, 106';
    ctx.clearRect(0, 0, size, size);

    /* 底图：细网格 + 河道斜带（河道是 x + y ≈ 0 那条对角线，也是中线方向） */
    ctx.save();
    ctx.strokeStyle = 'rgba(128, 152, 162, .22)';
    ctx.lineWidth = 1;
    for (let k = 1; k < 4; k++) {
      const p = Math.round((k / 4) * size) + 0.5;
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, size); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(size, p); ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(38, 74, 96, .30)';
    ctx.lineWidth = size * 0.075;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(size, size); ctx.stroke();
    ctx.restore();

    /* 离散分格：每格按停留时长分 5 档填色。
       原来是径向渐变叠加，2 秒一个采样点画出来是一团糊光斑，看不出走到哪。 */
    const steps = 5;
    for (let i = 0; i < counts.length; i++) {
      const n = counts[i];
      if (!n) continue;
      const level = clamp(Math.ceil((n / max) * steps), 1, steps);
      const alpha = 0.26 + (level / steps) * 0.66;
      const gx = i % GRID;
      const gy = Math.floor(i / GRID);
      ctx.fillStyle = `rgba(${rgb},${alpha.toFixed(2)})`;
      ctx.fillRect(gx * cell + 0.5, (GRID - 1 - gy) * cell + 0.5, cell - 1, cell - 1);
    }
  }

  function paintHeat(t) {
    if (!heatState) return;
    const box = document.querySelector('[data-md-heat]');
    if (!box) return;
    const { step, duration, list } = heatState;
    const at = clamp(t, 0, duration);
    const slider = box.querySelector('[data-heat-range]');
    if (slider) slider.value = String(at);
    const from = Math.max(0, at - HEAT_WINDOW);
    const clock = box.querySelector('[data-heat-clock]');
    if (clock) clock.textContent = `${time(from)} – ${time(at)}`;
    const i0 = Math.max(0, Math.ceil(from / step));
    const i1 = Math.max(i0, Math.floor(at / step));
    const { out, max } = heatCounts(list, i0, i1);
    box.querySelectorAll('canvas[data-heat-card]').forEach((canvas) => {
      const data = out.get(canvas.dataset.heatCard);
      if (data) drawHeat(canvas, data.counts, max, canvas.dataset.side);
    });
    box.querySelectorAll('[data-heat-share]').forEach((el) => {
      const data = out.get(el.dataset.heatShare);
      if (data) el.innerHTML = `${pct(data.total ? data.enemy / data.total * 100 : 0)}<small>敌方半区</small>`;
    });
    box.querySelectorAll('[data-heat-pct]').forEach((el) => {
      const data = out.get(el.dataset.heatPct);
      if (data) el.textContent = pct(data.total ? data.enemy / data.total * 100 : 0);
    });
  }

  function stopHeat() {
    if (heatTimer) clearInterval(heatTimer);
    heatTimer = null;
    document.querySelectorAll('[data-heat-play]').forEach((b) => {
      b.setAttribute('aria-pressed', 'false');
      b.textContent = '播放';
    });
  }

  function toggleHeat(button) {
    if (heatTimer) { stopHeat(); return; }
    const box = button.closest('[data-md-heat]');
    const slider = box && box.querySelector('[data-heat-range]');
    if (!slider || !heatState) return;
    button.setAttribute('aria-pressed', 'true');
    button.textContent = '暂停';
    let at = Number(slider.value);
    if (at >= heatState.duration - heatState.step) at = 0;
    heatTimer = setInterval(() => {
      if (!document.contains(box)) { stopHeat(); return; }
      at += heatState.step * 3;
      paintHeat(at);
      if (at >= heatState.duration) stopHeat();
    }, 200);
  }

  function bindHeat(root) {
    if (!heatBound) {
      heatBound = true;
      root.addEventListener('input', (event) => {
        const slider = event.target.closest && event.target.closest('[data-heat-range]');
        if (!slider) return;
        stopHeat();
        paintHeat(Number(slider.value));
      });
      root.addEventListener('click', (event) => {
        const phase = event.target.closest ? event.target.closest('[data-heat-phase]') : null;
        if (phase) {
          stopHeat();
          root.querySelectorAll('[data-heat-phase]').forEach((b) => b.setAttribute('aria-pressed', String(b === phase)));
          paintHeat(Number(phase.dataset.heatPhase));
          return;
        }
        const hit = event.target.closest ? event.target.closest('[data-heat-play]') : null;
        if (!hit) return;
        toggleHeat(hit);
      });
      root.addEventListener('change', (event) => {
        const pick = event.target.closest && event.target.closest('[data-heat-lane]');
        if (!pick) return;
        heatLane = pick.value;
        const box = pick.closest('[data-md-heat]');
        if (!box) return;
        box.querySelectorAll('[data-lane]').forEach((row) => { row.hidden = row.dataset.lane !== heatLane; });
        paintHeat(Number(box.querySelector('[data-heat-range]')?.value || 0));
      });
    }
    const box = document.querySelector('[data-md-heat]');
    if (!box || !heatState) return;
    box.querySelectorAll('[data-lane]').forEach((row) => { row.hidden = row.dataset.lane !== heatLane; });
    const pick = box.querySelector('[data-heat-lane]');
    if (pick) pick.value = heatLane;
    const slider = box.querySelector('[data-heat-range]');
    paintHeat(Number(slider ? slider.value : heatState.duration));
  }

  /* ── 战斗拆成两块：团战（点地图看本波）与掉点（筛选/点选看单次） ──────
     原来团战和掉点挤在同一块板子里：地图混点、列表混队、结论也混。
     现在各自一块：
       团战 = 团战地图 + 本波伤害/承伤/控制 + 全队团战贡献 + 团战分析；
       掉点 = 掉点地图 + 掉点列表 + 选中掉点详情 + 掉点分析。
     两块共用官方回放的 battles/deaths 与逐秒位置，口径一致、互不遮挡。 */
  const PHASE_LABELS = ['对线期', '发育期', '后期'];
  function battle(positions, players, ownCamp, duration, series, deaths, fights) {
    const deathList = (deaths || []).filter((d) => num(d.t));
    const fightList = (fights || []).filter((f) => num(f.t));
    battleState = null;
    if (!deathList.length && !fightList.length) return null;
    const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';
    const step = (positions && positions.step) || 2;
    const srcs = (positions && positions.players) || [];
    const phases = phaseWindows(duration);
    const phaseIndex = (t) => {
      const index = phases.findIndex((p) => t >= p.start && t < p.end);
      return index < 0 ? phases.length - 1 : index;
    };

    const slotOf = (camp, hero) => {
      const p = players.find((x) => x.camp === camp && x.hero === hero);
      return p ? p.slot : null;
    };
    const srcOf = (camp, hero) => {
      const slot = slotOf(camp, hero);
      if (slot == null) return null;
      return srcs.find((s) => s.camp === camp && s.slot === slot) || null;
    };
    const pointAt = (camp, hero, t) => {
      const src = srcOf(camp, hero);
      if (!src || !src.points.length) return null;
      return src.points[clamp(Math.round(t / step), 0, src.points.length - 1)];
    };

    /* 复活时刻用「位置冻结结束」反推：死亡后坐标不动，重新移动即复活 */
    const reviveAt = (camp, hero, t0) => {
      const src = srcOf(camp, hero);
      if (!src || !src.points.length) return null;
      let i = clamp(Math.floor(t0 / step), 0, src.points.length - 1);
      const start = i;
      while (i < src.points.length - 1) {
        const [x, y] = src.points[i];
        const [nx, ny] = src.points[i + 1];
        if (nx !== x || ny !== y) break;
        i += 1;
      }
      /* 至少要静止 8 秒才认作死亡窗口，否则退回默认 20 秒（防止「站定两帧就被判成复活」） */
      return (i - start) * step >= 8 ? (i + 1) * step : null;
    };

    const interp = (t) => {
      const pts = series || [];
      if (!pts.length) return null;
      if (t <= pts[0][0]) return pts[0][1];
      if (t >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
      for (let i = 1; i < pts.length; i++) {
        if (pts[i][0] >= t) {
          const [ta, va] = pts[i - 1], [tb, vb] = pts[i];
          return va + (vb - va) * (t - ta) / Math.max(1, tb - ta);
        }
      }
      return null;
    };

    /* 反事实：用 [阵亡-120s, 阵亡-10s] 的经济差做 Theil–Sen 中位斜率，外推到复活时刻；
       损失 = 预期 − 实际。正数＝本队因这次掉点亏。中位斜率比最小二乘抗单点波动，
       再夹在 ±30 金/秒以内，避免 30 秒采样里的一次大波动把外推拉飞。 */
    const project = (t0, t1) => {
      const base = (series || []).filter(([t]) => t >= t0 - 120 && t <= t0 - 10);
      const actual = interp(t1);
      const start = interp(t0);
      const raw = num(actual) && num(start) ? actual - start : null;
      if (base.length < 2 || !num(actual)) return { raw, loss: null, confident: false };
      const slopes = [];
      for (let i = 0; i < base.length; i++) {
        for (let j = i + 1; j < base.length; j++) {
          const dt = base[j][0] - base[i][0];
          if (dt > 0) slopes.push((base[j][1] - base[i][1]) / dt);
        }
      }
      slopes.sort((a, b) => a - b);
      const slope = slopes.length ? clamp(slopes[Math.floor(slopes.length / 2)], -30, 30) : 0;
      const last = base[base.length - 1];
      const expected = last[1] + slope * (t1 - last[0]);
      return { raw, loss: expected - actual, confident: base.length >= 3 && last[0] - base[0][0] >= 60 };
    };

    const SIZE = 320, PAD = 20;
    const bx = (x) => PAD + (x + 57) / 114 * (SIZE - PAD * 2);
    const by = (y) => SIZE - PAD - ((y + 57) / 114) * (SIZE - PAD * 2);
    const grid = [1, 2, 3].map((k) => {
      const at = PAD + (k / 4) * (SIZE - PAD * 2);
      return `<line class="md-battle-grid" x1="${at.toFixed(1)}" y1="${PAD}" x2="${at.toFixed(1)}" y2="${SIZE - PAD}"/>`
        + `<line class="md-battle-grid" x1="${PAD}" y1="${at.toFixed(1)}" x2="${SIZE - PAD}" y2="${at.toFixed(1)}"/>`;
    }).join('');
    const mapBase = `<line class="md-battle-river" x1="${PAD}" y1="${PAD}" x2="${SIZE - PAD}" y2="${SIZE - PAD}"/>
      <g class="md-battle-bases">
        <circle class="base blue" cx="${bx(-49).toFixed(1)}" cy="${by(-49).toFixed(1)}" r="3.4"/>
        <circle class="base red" cx="${bx(49).toFixed(1)}" cy="${by(49).toFixed(1)}" r="3.4"/>
        <text class="base-label" x="${bx(-49).toFixed(1)}" y="${(by(-49) + 14).toFixed(1)}" text-anchor="middle">蓝</text>
        <text class="base-label" x="${bx(49).toFixed(1)}" y="${(by(49) - 8).toFixed(1)}" text-anchor="middle">红</text>
      </g>`;

    /* 点位防叠：同一片区域常有多波团战 / 多次掉点，按原坐标直接画圆会叠在一起，
       既看不清也点不准。这里做一次轻量排斥（圆点互推 + 向真实位置回弹），
       把重叠点错开；偏移超过 3px 的用一条细引线连回真实位置，位置仍然诚实。 */
    const spreadMarkers = (items) => {
      const nodes = items.filter((item) => item.center).map((item) => {
        const ax = bx(item.center[0]);
        const ay = by(item.center[1]);
        return { item, ax, ay, x: ax, y: ay, r: item.radius || 6 };
      });
      if (nodes.length < 2) {
        return nodes.map((node) => ({ ...node, moved: false }));
      }
      const inner = 12;
      for (let step = 0; step < 240; step++) {
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            const need = a.r + b.r + 3.5;
            let dx = b.x - a.x;
            let dy = b.y - a.y;
            let dist = Math.hypot(dx, dy);
            if (dist >= need) continue;
            if (dist < 0.001) {
              const angle = ((i * 7 + j * 13) % 24) / 24 * Math.PI * 2;
              dx = Math.cos(angle) * 0.01;
              dy = Math.sin(angle) * 0.01;
              dist = 0.01;
            }
            const push = (need - dist) / 2;
            const ux = dx / dist;
            const uy = dy / dist;
            a.x -= ux * push;
            a.y -= uy * push;
            b.x += ux * push;
            b.y += uy * push;
          }
        }
        for (const node of nodes) {
          node.x += (node.ax - node.x) * 0.015;
          node.y += (node.ay - node.y) * 0.015;
          node.x = clamp(node.x, inner, SIZE - inner);
          node.y = clamp(node.y, inner, SIZE - inner);
        }
      }
      return nodes.map((node) => ({
        ...node,
        moved: Math.hypot(node.x - node.ax, node.y - node.ay) > 3,
        x: Number(node.x.toFixed(1)),
        y: Number(node.y.toFixed(1)),
      }));
    };

    /* ── 团战 ───────────────────────────────────────────────────────── */
    const fightCenter = (f) => {
      const pts = (f.details || []).flatMap((d) => [0, 4, 8]
        .map((offset) => pointAt(d.camp, d.hero, f.t + offset))
        .filter(Boolean));
      if (!pts.length) return null;
      return [pts.reduce((s, p) => s + p[0], 0) / pts.length,
        pts.reduce((s, p) => s + p[1], 0) / pts.length];
    };
    const fightsInfo = fightList.map((f, index) => {
      const details = (f.details || []).filter((d) => d.hero);
      const ownParts = details.filter((d) => d.camp === ownCamp);
      const foeParts = details.filter((d) => d.camp === foeCamp);
      const ownHurt = ownParts.reduce((s, d) => s + (num(d.hurt) ? d.hurt : 0), 0);
      const foeHurt = foeParts.reduce((s, d) => s + (num(d.hurt) ? d.hurt : 0), 0);
      const ownKills = num(f[ownCamp]) ? f[ownCamp] : 0;
      const foeKills = num(f[foeCamp]) ? f[foeCamp] : 0;
      const result = ownKills > foeKills ? 'win' : ownKills < foeKills ? 'loss' : 'even';
      const tEnd = num(f.end) ? f.end : f.t + 20;
      const before = interp(Math.max(0, f.t - 30));
      const after = interp(Math.min(duration || (tEnd + 30), tEnd + 30));
      const swing = num(before) && num(after) ? after - before : null;
      return {
        index, f, t: f.t, end: tEnd, ownParts, foeParts, details,
        ownHurt, foeHurt, ownKills, foeKills, result,
        first: f.first === ownCamp ? 'own' : f.first ? 'foe' : '',
        total: details.length, center: fightCenter(f), swing,
        phase: phaseIndex(f.t),
      };
    });
    const fightLayout = spreadMarkers(fightsInfo.map((item) => ({
      center: item.center,
      radius: 3.5 + Math.min(4, (item.total || 0) * 0.4),
      ref: item,
    })));
    for (const node of fightLayout) {
      node.item.ref.layout = { x: node.x, y: node.y, r: node.r, moved: node.moved };
    }
    const fightCount = fightsInfo.length;
    const fightWins = fightsInfo.filter((x) => x.result === 'win').length;
    const fightLosses = fightsInfo.filter((x) => x.result === 'loss').length;
    const fightDraws = fightCount - fightWins - fightLosses;
    const firstFights = fightsInfo.filter((x) => x.first === 'own');
    const firstWins = firstFights.filter((x) => x.result === 'win').length;
    const foeFirst = fightsInfo.filter((x) => x.first === 'foe');
    const foeFirstWins = foeFirst.filter((x) => x.result === 'win').length;
    const swingFights = fightsInfo.filter((x) => num(x.swing));
    const bestFight = swingFights.slice().sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing))[0] || null;
    const keyFights = swingFights.slice().sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing)).slice(0, 3);
    const avgTotal = fightCount ? fightsInfo.reduce((s, x) => s + x.total, 0) / fightCount : null;
    const avgEnd = fightCount ? fightsInfo.reduce((s, x) => s + Math.max(1, x.end - x.t), 0) / fightCount : null;
    const fiveVfive = fightsInfo.filter((x) => x.ownParts.length === 5 && x.foeParts.length === 5);
    const fiveWins = fiveVfive.filter((x) => x.result === 'win').length;
    const sizeBuckets = [
      { key: 'small', label: '小团（≤4 人）', list: fightsInfo.filter((x) => x.total <= 4) },
      { key: 'mid', label: '中团（5–7 人）', list: fightsInfo.filter((x) => x.total >= 5 && x.total <= 7) },
      { key: 'big', label: '大团（≥8 人）', list: fightsInfo.filter((x) => x.total >= 8) },
    ].map((b) => ({ ...b, n: b.list.length, wins: b.list.filter((x) => x.result === 'win').length }));
    const phaseFights = PHASE_LABELS.map((label, i) => ({
      label, list: fightsInfo.filter((x) => x.phase === i),
    })).map((b) => ({ ...b, n: b.list.length, wins: b.list.filter((x) => x.result === 'win').length }));

    const resultTone = (r) => r === 'win' ? 'own' : r === 'loss' ? 'foe' : 'even';
    const resultText = (r) => r === 'win' ? '我方赢' : r === 'loss' ? '我方负' : '打平';
    const fightCard = (item) => {
      const teamBlock = (camp) => {
        const isOwn = camp === ownCamp;
        const list = (item.details || []).filter((d) => d.camp === camp)
          .sort((a, b) => (b.hurt || 0) - (a.hurt || 0));
        const teamSum = list.reduce((s, d) => s + (num(d.hurt) ? d.hurt : 0), 0);
        const rows = list.map((d) => {
          const share = teamSum ? (num(d.hurt) ? d.hurt : 0) / teamSum * 100 : null;
          return `<div class="md-fd-row ${isOwn ? 'own' : 'foe'}">
            <span class="md-fd-hero">${portrait(d.hero, 'md-fd-face')}${esc(d.hero)}</span>
            <span class="md-fd-num">${fmt(d.hurt)}</span>
            <span class="md-fd-num">${fmt(d.taken)}</span>
            <span class="md-fd-num">${fmt(num(d.hardCtrl) ? d.hardCtrl / 1000 : null, 1)}</span>
            <span class="md-fd-share"><i style="width:${share === null ? 0 : share.toFixed(0)}%"></i><small>${share === null ? '—' : pct(share)}</small></span>
          </div>`;
        }).join('');
        return `<div class="md-fd-team ${isOwn ? 'own' : 'foe'}">
          <div class="md-fd-team-head"><b>${isOwn ? '我方' : '对手'}</b><span>${list.length} 人 · 总伤害 ${fmt(teamSum)}</span></div>
          <div class="md-fd-row head"><span>英雄</span><span>伤害</span><span>承伤</span><span>控制/秒</span><span>占比</span></div>
          ${rows || '<p class="md-fd-empty">这波没有参战明细</p>'}
        </div>`;
      };
      return `<div class="md-fd">
        <div class="md-fd-head">
          <b>${time(item.t)} · 第 ${item.index + 1} 波</b>
          <span class="md-fd-tag ${resultTone(item.result)}">${resultText(item.result)}</span>
          <span class="md-fd-tag">${item.ownParts.length}v${item.foeParts.length}</span>
          <span class="md-fd-tag ${item.first === 'own' ? 'own' : item.first === 'foe' ? 'foe' : ''}">${item.first === 'own' ? '我方先手' : item.first === 'foe' ? '对方先手' : '先手未记录'}</span>
          <span class="md-fd-kills">击杀 <i>${item.ownKills}</i> : ${item.foeKills}</span>
        </div>
        <div class="md-fd-swing">经济差 <b class="${num(item.swing) ? (item.swing >= 0 ? 'up' : 'down') : ''}">${num(item.swing) ? diff(item.swing) : '—'}</b><small>开团前 30 秒 → 结束后 30 秒（本队视角）</small></div>
        <div class="md-fd-teams">${teamBlock(ownCamp)}${teamBlock(foeCamp)}</div>
        <p class="md-fd-note">伤害 / 承伤 / 控制为回放事件内数值；占比＝该队本波伤害占比。</p>
      </div>`;
    };

    const fightTable = (camp) => {
      const team = LANES.map((lane) => players.find((p) => p.camp === camp && laneOf(p) === lane)).filter(Boolean);
      const body = team.map((p) => {
        let joined = 0, hurt = 0, taken = 0, ctrl = 0, shareSum = 0, shareN = 0;
        for (const item of fightsInfo) {
          const hit = (item.details || []).find((x) => x.camp === camp && x.hero === p.hero);
          if (!hit) continue;
          joined += 1;
          hurt += num(hit.hurt) ? hit.hurt : 0;
          taken += num(hit.taken) ? hit.taken : 0;
          ctrl += num(hit.hardCtrl) ? hit.hardCtrl / 1000 : 0;
          const teamSum = camp === ownCamp ? item.ownHurt : item.foeHurt;
          if (teamSum) { shareSum += (num(hit.hurt) ? hit.hurt : 0) / teamSum * 100; shareN += 1; }
        }
        const share = shareN ? shareSum / shareN : null;
        return `<div class="md-ft-row" data-player-row="${esc(p.hero || '')}">
          <span class="md-ft-name">${esc(p.hero || p.label || '—')}</span>
          <span>${fmt(joined)}</span>
          <span>${fmt(hurt)}</span>
          <span>${fmt(taken)}</span>
          <span>${fmt(ctrl, 1)}</span>
          <span class="md-ft-cell"${num(share) ? ` style="background:rgba(216,178,106,${Math.min(0.34, share / 45 * 0.34).toFixed(3)})"` : ''}>${num(share) ? pct(share) : '—'}</span>
        </div>`;
      }).join('');
      if (!team.length) return '<p class="md-board-empty">没有该队十人面板</p>';
      return `<div class="md-ft">
        <div class="md-ft-row head"><span>选手</span><span>参战</span><span>伤害</span><span>承伤</span><span>控制/秒</span><span>均占比</span></div>
        ${body}
      </div>`;
    };

    const fightDefaultIndex = bestFight ? bestFight.index : Math.max(0, fightCount - 1);
    const fightMarks = fightLayout.map((node) => {
      const item = node.item.ref;
      const tone = resultTone(item.result);
      return `<g class="md-fight ${tone}${item.index === fightDefaultIndex ? ' is-on' : ''}"
        data-fight="${item.index}" tabindex="0" role="button"
        aria-label="${esc(`${time(item.t)} 团战 ${item.ownParts.length} 对 ${item.foeParts.length} ${resultText(item.result)}`)}">
        <circle class="dot" cx="${node.x}" cy="${node.y}" r="${node.r.toFixed(1)}"/>
        <circle class="hit" cx="${node.x}" cy="${node.y}" r="${(node.r + 2).toFixed(1)}"/>
        <title>${esc(`${time(item.t)} · ${item.ownParts.length}v${item.foeParts.length} · 击杀 ${item.ownKills}:${item.foeKills} · ${num(item.swing) ? `经济差 ${diff(item.swing)}` : '经济差 —'}`)}</title>
      </g>`;
    }).join('');
    const fightLeaders = fightLayout.filter((node) => node.moved).map((node) => {
      const item = node.item.ref;
      return `<line class="md-fight-leader" x1="${node.ax.toFixed(1)}" y1="${node.ay.toFixed(1)}" x2="${node.x}" y2="${node.y}"><title>${esc(`${time(item.t)} 实测位置`)}</title></line>`;
    }).join('');
    /* 选中环单独画在最上层：团战点会互相压叠，靠描边加深看不清 */
    const fightHalo = (() => {
      const item = fightsInfo[fightDefaultIndex];
      if (!item || !item.layout) return '';
      return `<circle class="md-fight-halo" data-fight-halo cx="${item.layout.x}" cy="${item.layout.y}" r="${(item.layout.r + 4).toFixed(1)}"/>`;
    })();
    const fightTimeline = fightCount ? `<div class="md-fight-timeline">
      <div class="md-ftl-head"><b>团战时间线</b><span>${fmt(fightCount)} 波 · 点一条选中；地图上叠在一起的点可从这里直接选</span></div>
      <div class="md-ftl">${fightsInfo.map((item) => `<button type="button" class="md-ftl-chip ${resultTone(item.result)}${item.index === fightDefaultIndex ? ' is-on' : ''}" data-fight-chip="${item.index}" title="${esc(`${time(item.t)} · ${item.ownParts.length}v${item.foeParts.length} · 击杀 ${item.ownKills}:${item.foeKills}`)}">
        <span>${time(item.t)}</span><i></i><em>${item.ownKills}:${item.foeKills}</em><small>${num(item.swing) ? diff(item.swing) : '—'}</small>
      </button>`).join('')}</div>
    </div>` : '';
    const mapReady = fightsInfo.some((x) => x.center);
    const fightBoard = !fightCount ? '' : `<div class="md-board md-board-fight" data-md-fights>
      <div class="md-board-head">
        <div class="md-board-title"><b>团战地图</b><span>${fmt(fightCount)} 场团战 · 点地图上的点，看这一波的伤害 / 承伤 / 控制</span></div>
        <p class="md-board-legend">
          <span class="own"><i class="fight"></i>我方赢</span>
          <span class="foe"><i class="fight"></i>对手赢</span>
          <span class="even"><i class="fight"></i>打平</span>
          <span><i class="size"></i>点越大，参战人数越多</span>
        </p>
      </div>
      <div class="md-board-body">
        <div class="md-board-map">
          ${mapReady ? `<svg viewBox="0 0 ${SIZE} ${SIZE}" role="img" aria-label="团战位置分布">${grid}${mapBase}${fightLeaders}${fightMarks}${fightHalo}</svg>`
            : '<div class="md-map-empty">这局没有逐秒位置，团战点无法落图；右侧仍可逐波查看。</div>'}
          <p class="md-board-legend"><span class="own"><i class="fight"></i>我方赢</span><span class="foe"><i class="fight"></i>对手赢</span>${fightsInfo.filter((x) => x.center).length < fightCount ? `<span>仅 ${fightsInfo.filter((x) => x.center).length}/${fightCount} 波有位置</span>` : ''}</p>
          <p class="md-board-hint">重叠的点已自动错开，细线指回实测位置；同一处压着多波时，连点可轮换。</p>
          <p class="md-board-hint is-hot" data-fight-hint hidden></p>
        </div>
        <div class="md-fight-panel" data-fight-panel>
          ${fightCard(bestFight || fightsInfo[fightCount - 1])}
        </div>
      </div>
      ${fightTimeline}
      <div class="md-ft-split">
        <div class="md-board-block"><h4>我方团战贡献 <small>各波累计 · 伤害占比按队内</small></h4>${fightTable(ownCamp)}</div>
        <div class="md-board-block"><h4>对手团战贡献</h4>${fightTable(foeCamp)}</div>
      </div>
    </div>`;

    const fightBadge = fightCount ? fightWins / fightCount >= 0.7 ? ['团战占优', 'is-good']
      : fightWins / fightCount >= 0.45 ? ['五五开', 'is-thin'] : ['团战吃亏', 'is-bad'] : ['无团战数据', 'is-thin'];
    const fightLede = (() => {
      const parts = [];
      const fullFights = fiveVfive.length ? fiveVfive : fightsInfo.filter((x) => x.total >= 8);
      if (fightCount) {
        parts.push(`本局 ${fightCount} 波团战我方 ${fightWins} 胜 ${fightLosses} 负${fightDraws ? ` ${fightDraws} 平` : ''}`);
        if (firstFights.length) parts.push(`我方先手的 ${firstFights.length} 波 ${firstWins} 胜`);
        if (foeFirst.length) parts.push(`对方先手 ${foeFirst.length} 波，我方 ${foeFirstWins} 胜`);
        if (fiveVfive.length) parts.push(`5v5 团战 ${fiveVfive.length} 波、赢下 ${fiveWins} 波`);
        else if (fullFights.length) parts.push(`大团（≥8 人）${fullFights.length} 波、赢下 ${fullFights.filter((x) => x.result === 'win').length} 波`);
        if (bestFight && num(bestFight.swing)) {
          parts.push(`${bestFight.swing >= 0 ? '最大收益' : '最大回撤'} ${diff(bestFight.swing)}（${time(bestFight.t)}）`);
        }
        if (num(avgTotal)) parts.push(`平均每波 ${avgTotal.toFixed(1)} 人参战`);
        if (num(avgEnd)) parts.push(`平均 ${avgEnd.toFixed(0)} 秒一波`);
      }
      return parts.join('；');
    })();
    const fullFights = fiveVfive.length ? fiveVfive : fightsInfo.filter((x) => x.total >= 8);
    const fullWins = fullFights.filter((x) => x.result === 'win').length;
    const fightTiles = [
      ['团战', `${fightCount}<small>波</small>`, `${fightWins} 胜 · ${fightLosses} 负${fightDraws ? ` · ${fightDraws} 平` : ''}`],
      ['先手团战', `${firstWins}<i>/</i>${firstFights.length || 0}`, firstFights.length ? `先手后赢下` : '没有我方先手记录'],
      [fiveVfive.length ? '5v5 团战' : '大团（≥8 人）', `${fullWins}<i>/</i>${fullFights.length || 0}`,
        fullFights.length ? (fiveVfive.length ? '满编团战胜率' : '大团团战胜率') : '本局没有大团'],
      ['最大单波', `${bestFight && num(bestFight.swing) ? diff(bestFight.swing) : '—'}`, bestFight ? `${time(bestFight.t)} · ${resultText(bestFight.result)}` : '没有经济差采样'],
    ];
    const fightSizes = [
      ...sizeBuckets.filter((b) => b.n).map((b) => `<span class="md-fight-size"><b>${b.label}</b><i>${b.n} 波</i><em>${b.wins} 胜</em></span>`),
      ...phaseFights.filter((b) => b.n).map((b) => `<span class="md-fight-size is-phase"><b>${b.label}</b><i>${b.n} 波</i><em>${b.wins} 胜</em></span>`),
    ].join('');
    const fightKeys = keyFights.length ? `<div class="md-fight-keys"><b>关键团战</b>${keyFights.map((item) => `<button type="button" data-fight-jump="${item.index}">
      <span>${time(item.t)}</span>
      <i class="${resultTone(item.result)}">${resultText(item.result)}</i>
      <em>${num(item.swing) ? diff(item.swing) : '—'}</em>
    </button>`).join('')}</div>` : '';
    const fightAnalysis = `<div class="md-viz-analysis md-bprev ${fightBadge[1]}">
      <div class="md-bprev-head"><b>团战分析</b><span class="md-bprev-badge ${fightBadge[1]}">${fightBadge[0]}</span></div>
      <p class="md-bprev-lede">${fightLede || '这局回放没有团战账本'}。</p>
      <div class="md-bprev-stats">${fightTiles.map(([label, value, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}</span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
      ${fightSizes ? `<div class="md-fight-splits">${fightSizes}</div>` : ''}
      ${fightKeys}
      <p class="md-bprev-thin">口径：团战点来自官方回放 battles，点大小＝参战人数，颜色＝该波击杀差；胜负按该波击杀数，经济差取开团前 30 秒到结束后 30 秒的变化（本队视角，已扣自然涨跌）。</p>
    </div>`;

    /* ── 掉点 ───────────────────────────────────────────────────────── */
    const rows = [];
    for (const d of deathList) {
      const hasPos = num(d.x) && num(d.y);
      const clipped = hasPos ? Math.min(reviveAt(d.camp, d.hero, d.t) || d.t + 20, duration || Infinity) : null;
      const t1 = hasPos ? Math.max(clipped, d.t + 1) : null;
      const info = hasPos && t1 - d.t >= 8 ? project(d.t, t1) : { raw: null, loss: null, confident: false };
      const impact = num(info.loss) ? -info.loss : null;
      let near = null;
      if (hasPos) {
        const me = pointAt(d.camp, d.hero, d.t);
        if (me) {
          let ally = null, enemies = 0, nearestEnemy = null;
          for (const p of players) {
            if (!p.hero || p.hero === d.hero && p.camp === d.camp) continue;
            const pt = pointAt(p.camp, p.hero, d.t);
            if (!pt) continue;
            const dist = Math.hypot(pt[0] - me[0], pt[1] - me[1]);
            if (p.camp === d.camp) {
              if (ally == null || dist < ally) ally = dist;
            } else {
              if (dist <= 12) enemies += 1;
              if (nearestEnemy == null || dist < nearestEnemy) nearestEnemy = dist;
            }
          }
          near = { ally, enemies, nearestEnemy };
        }
      }
      const adv = hasPos ? (ownCamp === 'blue' ? progress(d.x, d.y) : 1 - progress(d.x, d.y)) : null;
      const zone = adv == null ? '' : adv < 0.42 ? '己方半区' : adv < 0.58 ? '河道 / 中线' : '对方半区';
      const inFight = fightsInfo.some((item) => d.t >= item.t - 5 && d.t <= item.end + 8);
      rows.push({ d, t1, info, impact, near, zone, inFight, hasPos, shared: false });
    }
    /* 同队两人同时掉点，队级汇总会重复计入；这里只做标记，不改数 */
    for (const row of rows) {
      row.shared = rows.some((other) => other !== row && other.d.camp === row.d.camp && other.t1 != null && row.t1 != null
        && Math.min(row.t1, other.t1) - Math.max(row.d.t, other.d.t) > 5);
    }
    const deathFor = (camp) => rows.filter((row) => row.d.camp === camp);
    const ownDeaths = deathFor(ownCamp);
    const foeDeaths = deathFor(foeCamp);
    const impactSum = (list) => list.reduce((s, row) => s + (num(row.impact) ? row.impact : 0), 0);
    const ownImpact = impactSum(ownDeaths);
    const foeImpact = impactSum(foeDeaths);
    const netImpact = ownImpact + foeImpact;
    const biggest = rows.filter((row) => num(row.impact)).slice()
      .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))[0] || null;
    const heroCountText = (list, all = false) => {
      const map = new Map();
      for (const row of list) map.set(row.d.hero, (map.get(row.d.hero) || 0) + 1);
      const groups = new Map();
      for (const [hero, n] of map) groups.set(n, [...(groups.get(n) || []), hero]);
      const entries = [...groups.entries()].sort((a, b) => b[0] - a[0]);
      return (all ? entries : entries.slice(0, 2))
        .map(([n, heroes]) => `${heroes.join(' / ')} ${n} 次`).join('、');
    };
    const phaseDeaths = PHASE_LABELS.map((label, i) => ({
      label,
      own: ownDeaths.filter((row) => phaseIndex(row.d.t) === i).length,
      foe: foeDeaths.filter((row) => phaseIndex(row.d.t) === i).length,
    }));
    const ownInFight = ownDeaths.filter((row) => row.inFight).length;
    const ownFarAlly = ownDeaths.filter((row) => row.near && row.near.ally != null && row.near.ally > 15).length;
    const ownCaught = ownDeaths.filter((row) => row.near && row.near.ally != null && row.near.ally > 15 && row.near.enemies >= 1).length;
    const sortedOwn = ownDeaths.slice().sort((a, b) => a.d.t - b.d.t);
    let clusters = 0, clustered = 0;
    for (let i = 1; i < sortedOwn.length; i++) {
      if (sortedOwn[i].d.t - sortedOwn[i - 1].d.t <= 45) {
        clusters += 1;
        clustered += i === 1 || sortedOwn[i - 1].d.t - sortedOwn[i - 2].d.t > 45 ? 2 : 1;
      }
    }
    const defaultDeath = (() => {
      const target = ownDeaths.length ? ownDeaths : rows;
      return target.filter((row) => num(row.impact)).sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))[0] || target[0] || null;
    })();
    const deathCard = (row) => {
      const tone = num(row.impact) ? (row.impact < 0 ? 'down' : 'up') : '';
      const allyText = row.near && row.near.ally != null
        ? (row.near.ally <= 6 ? '在旁' : row.near.ally <= 15 ? '稍远' : '很远') : '无数据';
      const enemyText = row.near ? `${row.near.enemies} 人` : '无数据';
      return `<div class="md-dd">
        <div class="md-dd-head"><b>${time(row.d.t)}</b><span class="md-dd-hero">${portrait(row.d.hero, 'md-dd-face')}${esc(row.d.hero || '—')}</span><span class="md-dd-tag ${row.d.camp === ownCamp ? 'own' : 'foe'}">${row.d.camp === ownCamp ? '我方' : '对方'}</span></div>
        <div class="md-dd-impact ${tone}">${num(row.impact) ? diff(row.impact) : '—'}<small>本队经济影响 · 负亏正赚</small></div>
        <div class="md-dd-grid">
          <span>位置 <b>${row.zone || '—'}</b></span>
          <span>场景 <b>${row.inFight ? '团战内' : '团战外'}</b></span>
          <span>最近队友 <b>${allyText}</b></span>
          <span>附近对手 <b>${enemyText}</b></span>
          <span>修正窗口 <b>${row.t1 != null ? `${Math.round(row.t1 - row.d.t)} 秒` : '—'}</b></span>
          <span>同时掉点 <b>${row.shared ? '是' : '否'}</b></span>
        </div>
        <p class="md-dd-note">损失＝死前 120 秒经济差走势外推到复活时刻的差额，已扣自然涨跌${row.info.confident ? '' : '；低置信'}${row.shared ? '；与队友同时掉点，队级汇总会重复计入' : ''}</p>
      </div>`;
    };
    const deathTip = (row) => `<div class="dc-head"><b>${time(row.d.t)}</b><span>${esc(row.d.hero || '—')} · ${row.d.camp === ownCamp ? '我方' : '对方'}</span></div>
      <div class="dc-loss ${num(row.impact) ? (row.impact < 0 ? 'down' : 'up') : ''}">${num(row.impact) ? diff(row.impact) : '—'}<small>本队经济影响</small></div>`;
    const deathLayout = spreadMarkers(rows.map((row) => ({
      center: row.hasPos ? [row.d.x, row.d.y] : null,
      radius: 2.6 + Math.min(3.4, num(row.impact) ? Math.abs(row.impact) / 600 : 0),
      ref: row,
    })));
    for (const node of deathLayout) {
      node.item.ref.layout = { x: node.x, y: node.y, r: node.r, moved: node.moved };
    }
    const deathDots = deathLayout.map((node) => {
      const row = node.item.ref;
      const index = rows.indexOf(row);
      const tone = row.d.camp === ownCamp ? 'own' : 'foe';
      return `<g class="md-death ${tone}" data-death="${index}" tabindex="0" role="button" aria-label="${esc(`${time(row.d.t)} ${row.d.hero} 阵亡`)}">
        <circle class="dot" cx="${node.x}" cy="${node.y}" r="${node.r.toFixed(1)}"/>
        <circle class="hit" cx="${node.x}" cy="${node.y}" r="${(node.r + 2).toFixed(1)}"/>
        <title>${esc(`${time(row.d.t)} ${row.d.hero}（${row.d.camp === ownCamp ? '我方' : '对方'}）${num(row.impact) ? ` · 本队经济影响 ${diff(row.impact)}` : ''}`)}</title>
      </g>`;
    }).join('');
    const deathLeaders = deathLayout.filter((node) => node.moved).map((node) => {
      const row = node.item.ref;
      return `<line class="md-death-leader" x1="${node.ax.toFixed(1)}" y1="${node.ay.toFixed(1)}" x2="${node.x}" y2="${node.y}"><title>${esc(`${time(row.d.t)} ${row.d.hero} 实测位置`)}</title></line>`;
    }).join('');
    const deathHalo = (() => {
      if (!defaultDeath || !defaultDeath.layout) return '';
      return `<circle class="md-death-halo" data-death-halo cx="${defaultDeath.layout.x}" cy="${defaultDeath.layout.y}" r="${(defaultDeath.layout.r + 4).toFixed(1)}"/>`;
    })();
    const deathRowsHtml = rows.map((row, i) => {
      const tone = num(row.impact) ? (row.impact < 0 ? 'down' : 'up') : '';
      const own = row.d.camp === ownCamp;
      return `<button type="button" class="md-dr${own ? ' own' : ' foe'}${i === (defaultDeath ? rows.indexOf(defaultDeath) : -1) ? ' is-on' : ''}" data-death-row="${i}">
        <span class="md-dr-time">${time(row.d.t)}</span>
        <span class="md-dr-hero"><i></i>${esc(row.d.hero || '—')}<small>${own ? '我方' : '对方'}</small></span>
        <span class="md-dr-impact ${tone}">${num(row.impact) ? diff(row.impact) : '—'}</span>
      </button>`;
    }).join('');
    const picker = (() => {
      const group = (camp, title) => {
        const list = players.filter((p) => p.camp === camp && p.hero && rows.some((row) => row.d.hero === p.hero && row.d.camp === camp));
        if (!list.length) return '';
        return `<optgroup label="${title}">${list.map((p) => `<option value="${esc(p.hero || '')}">${esc(p.label || p.hero || '—')} · ${esc(p.hero || '')}</option>`).join('')}</optgroup>`;
      };
      return `<select class="md-battle-pick" data-battle-pick aria-label="只看某个选手的掉点">
        <option value="">全部选手（${rows.length} 次）</option>
        ${group(ownCamp, `我方（${ownDeaths.length} 次）`)}${group(foeCamp, `对手（${foeDeaths.length} 次）`)}
      </select>`;
    })();
    const deathBoard = `<div class="md-board md-board-death" data-md-deaths>
      <div class="md-board-head">
        <div class="md-board-title"><b>掉点地图</b><span>${fmt(rows.length)} 次阵亡 · 我方 ${fmt(ownDeaths.length)} / 对手 ${fmt(foeDeaths.length)} · 点圆点或右侧列表固定选中</span></div>
        ${picker}
      </div>
      <div class="md-board-body">
        <div class="md-board-map">
          ${rows.some((row) => row.hasPos) ? `<svg viewBox="0 0 ${SIZE} ${SIZE}" role="img" aria-label="掉点位置分布">${grid}${mapBase}${deathLeaders}${deathDots}${deathHalo}</svg>`
            : '<div class="md-map-empty">这局没有逐秒位置，掉点无法落图；右侧列表与详情仍可用。</div>'}
          <div class="md-death-tip" data-death-tip hidden></div>
          <p class="md-board-legend"><span class="own"><i class="death"></i>我方阵亡</span><span class="foe"><i class="death"></i>对手阵亡</span><span><i class="size"></i>点越大，经济影响越大</span>${rows.filter((row) => row.hasPos).length < rows.length ? `<span>仅 ${rows.filter((row) => row.hasPos).length}/${rows.length} 次有位置</span>` : ''}</p>
          <p class="md-board-hint">重叠的点已自动错开，细线指回实测位置；同一处多次掉点可连点轮换，或直接用右侧列表精确选。</p>
        </div>
        <div class="md-board-block md-dr-block">
          <h4>掉点列表 <small>按时间排 · 数值＝本队经济影响（负亏 / 正赚）</small></h4>
          <div class="md-dr-list" data-death-list>${deathRowsHtml}</div>
          <p class="md-board-empty" data-death-empty hidden>该选手这局没有掉点</p>
        </div>
        <div class="md-board-block md-dd-block">
          <h4>选中掉点 <small>本队视角经济影响</small></h4>
          <div data-death-detail>${defaultDeath ? deathCard(defaultDeath) : '<p class="md-board-empty">这局没有可定位的掉点</p>'}</div>
        </div>
      </div>
    </div>`;

    const deathBadge = !num(ownImpact) && !num(foeImpact) ? ['没有损失数据', 'is-thin']
      : netImpact >= 300 ? ['掉点端占优', 'is-good'] : netImpact <= -300 ? ['掉点端吃亏', 'is-bad'] : ['掉点互有往来', 'is-thin'];
    const deathLede = (() => {
      const parts = [];
      parts.push(`本局我方 ${ownDeaths.length} 次阵亡${num(ownImpact) ? `，合计影响 ${diff(ownImpact)}` : ''}`);
      if (foeDeaths.length) parts.push(`对方 ${foeDeaths.length} 次阵亡${num(foeImpact) ? `，我方获得 ${diff(foeImpact)}` : ''}`);
      if (ownDeaths.length) {
        parts.push(ownInFight === ownDeaths.length ? '全部死在团战里'
          : `${ownInFight} 次死在团战里、${ownDeaths.length - ownInFight} 次在团战外`);
        if (ownCaught) parts.push(`其中 ${ownCaught} 次队友不在附近、附近有对手（被抓单）`);
        parts.push(`按人看：${heroCountText(ownDeaths, true)}`);
      }
      if (biggest && num(biggest.impact)) parts.push(`最大一笔 ${time(biggest.d.t)} ${biggest.d.hero} ${diff(biggest.impact)}`);
      return parts.join('；');
    })();
    const deathTiles = [
      ['我方掉点', `${ownDeaths.length}<small>次</small>`, num(ownImpact) ? `合计 ${diff(ownImpact)}` : '没有损失估算'],
      ['对方掉点', `${foeDeaths.length}<small>次</small>`, num(foeImpact) ? `我方 ${diff(foeImpact)}` : '没有损失估算'],
      ['净收益', `${num(netImpact) ? diff(netImpact) : '—'}`, '对方掉点 − 我方掉点'],
      ['最大单笔', `${biggest && num(biggest.impact) ? diff(biggest.impact) : '—'}`, biggest ? `${time(biggest.d.t)} · ${biggest.d.hero}` : '没有可估算的掉点'],
    ];
    const phaseBars = phaseDeaths.map((p) => `<span class="md-death-phase"><b>${p.label}</b><i class="own" style="width:${Math.max(4, p.own / Math.max(1, ownDeaths.length) * 100)}%"></i><i class="foe" style="width:${Math.max(4, p.foe / Math.max(1, foeDeaths.length) * 100)}%"></i><em>我 ${p.own} · 对 ${p.foe}</em></span>`).join('');
    const zoneCounts = (list) => {
      const map = new Map();
      for (const row of list) {
        if (!row.zone) continue;
        map.set(row.zone, (map.get(row.zone) || 0) + 1);
      }
      return [...map.entries()].sort((a, b) => b[1] - a[1]).map(([zone, n]) => `${zone} ${n}`).join(' · ');
    };
    const ownPlaced = ownDeaths.filter((row) => row.zone).length;
    const deathExtra = [
      { label: '团战内 / 外', text: `我方 ${ownInFight} / ${ownDeaths.length - ownInFight} 次` },
      { label: '队友不在附近', text: ownFarAlly ? `${ownFarAlly} 次${ownCaught ? `（其中 ${ownCaught} 次被抓单）` : ''}` : '每次身边都有队友' },
      { label: '连续掉点', text: clusters ? `${clusters} 组 · ${clustered} 次 · 间隔≤45 秒` : '没有连续掉点' },
      { label: '掉点落点', text: zoneCounts(ownDeaths) ? `${zoneCounts(ownDeaths)}（有位置 ${ownPlaced}/${ownDeaths.length} 次）` : '没有位置数据' },
      { label: '掉点最多', text: ownDeaths.length ? heroCountText(ownDeaths) : '—' },
      { label: '对方掉点最多', text: foeDeaths.length ? heroCountText(foeDeaths) : '—' },
    ];
    const deathAnalysis = `<div class="md-viz-analysis md-bprev ${deathBadge[1]}">
      <div class="md-bprev-head"><b>掉点分析</b><span class="md-bprev-badge ${deathBadge[1]}">${deathBadge[0]}</span></div>
      <p class="md-bprev-lede">${deathLede || '这局回放没有掉点数据'}。</p>
      <div class="md-bprev-stats">${deathTiles.map(([label, value, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}</span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
      <div class="md-death-splits">
        <div class="md-death-phases"><b>阶段分布</b>${phaseBars}</div>
        <div class="md-death-extra">${deathExtra.map((item) => `<span><b>${item.label}</b><em>${item.text}</em></span>`).join('')}</div>
      </div>
      <p class="md-bprev-thin">口径：掉点＝一次阵亡；经济影响＝死前 120 秒经济差走势外推到复活时刻的差额（本队视角，负＝我方亏、正＝我方赚），已扣自然涨跌；位置与「身边队友/对手」取阵亡时刻的逐秒位置（12 格内算附近）。低置信的估算在详情里标注。</p>
    </div>`;

    battleState = {
      ownCamp,
      fights: fightsInfo.map((item) => ({
        index: item.index, html: fightCard(item), time: item.t,
        layout: item.layout, heroList: item.details.map((d) => d.hero),
      })),
      deaths: rows.map((row, i) => ({
        index: i, html: deathCard(row), tip: deathTip(row),
        hero: row.d.hero, camp: row.d.camp, hasPos: row.hasPos, layout: row.layout,
      })),
      selectedFight: bestFight ? bestFight.index : Math.max(0, fightCount - 1),
      selectedDeath: defaultDeath ? rows.indexOf(defaultDeath) : null,
      pick: '',
    };
    return {
      fights: fightCount ? `${fightBoard}${fightAnalysis}` : '',
      deaths: rows.length ? `${deathBoard}${deathAnalysis}` : '',
    };
  }

  /* 团战 / 掉点交互：点地图或列表固定选中；切换选手只看他的掉点。
     事件委托挂在 document 上一次，重渲染/换页签后仍然生效。 */
  function selectFight(index, jump = false) {
    if (!battleState || !battleState.fights[index]) return;
    battleState.selectedFight = index;
    const box = document.querySelector('[data-md-fights]');
    if (!box) return;
    box.querySelectorAll('[data-fight]').forEach((g) => {
      g.classList.toggle('is-on', Number(g.dataset.fight) === index);
    });
    const panel = box.querySelector('[data-fight-panel]');
    if (panel) panel.innerHTML = battleState.fights[index].html;
    box.querySelectorAll('[data-fight-chip]').forEach((chip) => {
      chip.classList.toggle('is-on', Number(chip.dataset.fightChip) === index);
    });
    /* 同一处压着多波时提示可以连点轮换 */
    const hint = box.querySelector('[data-fight-hint]');
    if (hint) {
      const item = battleState.fights[index];
      const near = item && item.layout
        ? battleState.fights.filter((other) => other !== item && other.layout
          && Math.hypot(other.layout.x - item.layout.x, other.layout.y - item.layout.y) < item.layout.r + other.layout.r + 8).length
        : 0;
      hint.hidden = !near;
      hint.textContent = near ? `这一处还压着 ${near} 波团战，再点一次切换` : '';
    }
    /* 选中环跟着走，保证压在别的圆点下面时也看得见 */
    const halo = box.querySelector('[data-fight-halo]');
    const dot = box.querySelector(`[data-fight="${index}"] .dot`);
    if (halo && dot) {
      halo.setAttribute('cx', dot.getAttribute('cx'));
      halo.setAttribute('cy', dot.getAttribute('cy'));
      halo.setAttribute('r', (Number(dot.getAttribute('r')) + 4).toFixed(1));
    }
    if (jump) {
      const node = box.querySelector(`[data-fight="${index}"]`);
      if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function selectDeath(index, jump = false) {
    if (!battleState || !battleState.deaths[index]) return;
    battleState.selectedDeath = index;
    const box = document.querySelector('[data-md-deaths]');
    if (!box) return;
    box.querySelectorAll('[data-death]').forEach((g) => {
      g.classList.toggle('is-on', Number(g.dataset.death) === index);
    });
    box.querySelectorAll('[data-death-row]').forEach((row) => {
      row.classList.toggle('is-on', Number(row.dataset.deathRow) === index);
    });
    const detail = box.querySelector('[data-death-detail]');
    if (detail) detail.innerHTML = battleState.deaths[index].html;
    const halo = box.querySelector('[data-death-halo]');
    const dot = box.querySelector(`[data-death="${index}"] .dot`);
    if (halo) {
      if (dot) {
        halo.removeAttribute('hidden');
        halo.setAttribute('cx', dot.getAttribute('cx'));
        halo.setAttribute('cy', dot.getAttribute('cy'));
        halo.setAttribute('r', (Number(dot.getAttribute('r')) + 4).toFixed(1));
      } else {
        halo.setAttribute('hidden', '');
      }
    }
    if (jump) {
      const node = box.querySelector(`[data-death="${index}"]`);
      if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  /* 只看某个选手：地图圆点与列表一起收窄；选中挪到第一个可见掉点 */
  function filterDeaths(hero) {
    const box = document.querySelector('[data-md-deaths]');
    if (!box || !battleState) return;
    battleState.pick = hero || '';
    box.dataset.pick = hero || '';
    const dotVisible = [];
    box.querySelectorAll('[data-death]').forEach((g) => {
      const info = battleState.deaths[Number(g.dataset.death)];
      const off = Boolean(hero) && !(info && info.hero === hero);
      g.classList.toggle('is-off', off);
      if (!off) dotVisible.push(Number(g.dataset.death));
    });
    const rowVisible = [];
    box.querySelectorAll('[data-death-row]').forEach((row) => {
      const info = battleState.deaths[Number(row.dataset.deathRow)];
      const off = Boolean(hero) && !(info && info.hero === hero);
      row.hidden = off;
      if (!off) rowVisible.push(Number(row.dataset.deathRow));
    });
    const empty = box.querySelector('[data-death-empty]');
    if (empty) empty.hidden = rowVisible.length > 0;
    const candidates = rowVisible.length ? rowVisible : dotVisible;
    if (!candidates.length) {
      const detail = box.querySelector('[data-death-detail]');
      if (detail) detail.innerHTML = '<p class="md-board-empty">该选手这局没有掉点</p>';
      return;
    }
    const keep = candidates.includes(battleState.selectedDeath) ? battleState.selectedDeath : candidates[0];
    selectDeath(keep);
  }

  /* 点地图：取点击位置附近的所有圆点（按距离排），用于「吸附 + 重叠时轮换」 */
  function marksNear(svg, event, selector, extra = 8) {
    if (!svg) return [];
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return [];
    const px = (event.clientX - rect.left) / rect.width * 320;
    const py = (event.clientY - rect.top) / rect.height * 320;
    const list = [];
    svg.querySelectorAll(selector).forEach((node) => {
      const dot = node.querySelector('.dot');
      if (!dot) return;
      const cx = Number(dot.getAttribute('cx'));
      const cy = Number(dot.getAttribute('cy'));
      const radius = Number(dot.getAttribute('r')) || 6;
      if (!Number.isFinite(cx) || !Number.isFinite(cy)) return;
      const dist = Math.hypot(cx - px, cy - py);
      if (dist <= radius + extra) list.push({ node, dist });
    });
    return list.sort((a, b) => a.dist - b.dist);
  }

  function bindBattle(root) {
    if (!battleBound) {
      battleBound = true;
      root.addEventListener('click', (event) => {
        const chip = event.target.closest && event.target.closest('[data-fight-chip]');
        if (chip) { selectFight(Number(chip.dataset.fightChip)); return; }
        const jump = event.target.closest && event.target.closest('[data-fight-jump]');
        if (jump) { selectFight(Number(jump.dataset.fightJump), true); return; }
        const deathRow = event.target.closest && event.target.closest('[data-death-row]');
        if (deathRow) { selectDeath(Number(deathRow.dataset.deathRow)); return; }
        /* 地图点：先吸附最近一个；如果点中的就是当前选中、且附近还有别的点，就轮换到下一个 */
        const svg = event.target.closest && event.target.closest('[data-md-fights] svg, [data-md-deaths] svg');
        if (svg) {
          const isFight = Boolean(svg.closest('[data-md-fights]'));
          const selector = isFight ? '[data-fight]' : '[data-death]';
          const near = marksNear(svg, event, selector, isFight ? 6 : 5);
          const list = isFight ? battleState.fights : battleState.deaths;
          const neighborsOf = (index) => {
            const item = list[index];
            if (!item || !item.layout) return [];
            return list.filter((other) => other.index !== index && other.layout
              && Math.hypot(other.layout.x - item.layout.x, other.layout.y - item.layout.y)
                < item.layout.r + other.layout.r + 8).map((other) => other.index);
          };
          if (near.length) {
            const current = isFight ? battleState.selectedFight : battleState.selectedDeath;
            const indices = near.map(({ node }) => Number(isFight ? node.dataset.fight : node.dataset.death));
            const clicked = event.target.closest && event.target.closest(selector);
            const clickedIndex = clicked ? Number(isFight ? clicked.dataset.fight : clicked.dataset.death) : null;
            let pick = null;
            if (clickedIndex !== null) {
              const neighbors = neighborsOf(clickedIndex);
              pick = clickedIndex === current && neighbors.length ? neighbors[0] : clickedIndex;
            } else if (indices.includes(current) && indices.length > 1) {
              pick = indices[(indices.indexOf(current) + 1) % indices.length];
            } else {
              pick = indices[0];
            }
            if (isFight) selectFight(pick); else selectDeath(pick);
          }
          return;
        }
      });
      root.addEventListener('change', (event) => {
        const pick = event.target.closest && event.target.closest('[data-battle-pick]');
        if (!pick) return;
        filterDeaths(pick.value);
      });
      root.addEventListener('pointermove', (event) => {
        const box = document.querySelector('[data-md-deaths]');
        if (!box || !battleState) return;
        const tip = box.querySelector('[data-death-tip]');
        if (!tip) return;
        const dot = event.target.closest ? event.target.closest('[data-death]') : null;
        const area = box.querySelector('.md-board-map');
        if (!dot || !area) { tip.hidden = true; return; }
        const info = battleState.deaths[Number(dot.dataset.death)];
        if (!info) { tip.hidden = true; return; }
        tip.innerHTML = info.tip;
        tip.hidden = false;
        const rect = area.getBoundingClientRect();
        tip.style.left = `${Math.max(0, Math.min(event.clientX - rect.left + 14, rect.width - 215))}px`;
        tip.style.top = `${Math.max(0, Math.min(event.clientY - rect.top + 14, Math.max(0, rect.height - 110)))}px`;
      });
    }
    const fightsBox = document.querySelector('[data-md-fights]');
    if (fightsBox && battleState) selectFight(battleState.selectedFight);
    const deathsBox = document.querySelector('[data-md-deaths]');
    if (deathsBox && battleState) {
      filterDeaths(battleState.pick || '');
      if (battleState.selectedDeath != null) selectDeath(battleState.selectedDeath);
    }
  }

  /* ── 阵线：五人平均推进进度随时间（0＝己方基地，1＝对方基地） ───── */  function frontline(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const step = positions.step || 2;
    const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';
    const prep = positions.players.map((src) => {
      const mask = activeMask(src.points, step);
      const forward = src.camp === 'blue' ? 1 : -1;
      const advance = new Float32Array(src.points.length).fill(-1);
      for (let i = 0; i < src.points.length; i++) {
        if (!mask[i]) continue;
        const [x, y] = src.points[i];
        const p = progress(x, y);
        advance[i] = forward > 0 ? p : 1 - p;
      }
      return { camp: src.camp, advance };
    });
    const len = Math.min(...prep.map((p) => p.advance.length));
    if (len < 2) return '';
    const total = Math.min(duration || Infinity, (len - 1) * step);
    const SAMPLE = 10;
    const rows = [];
    for (let t = 0; t <= total; t += SAMPLE) {
      const i = Math.min(len - 1, Math.round(t / step));
      const mean = (camp) => {
        const vals = prep.filter((p) => p.camp === camp).map((p) => p.advance[i]).filter((v) => v >= 0);
        return vals.length >= 3 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      };
      rows.push({ t, own: mean(ownCamp), foe: mean(foeCamp) });
    }
    if (rows.length < 2) return '';

    /* 3 点滑动平均：五人平均本身的抖动不该被画成锯齿 */
    const smooth = (key) => rows.map((row, i) => {
      const win = [rows[i - 1], row, rows[i + 1]].filter((r) => r && num(r[key]));
      return win.length ? win.reduce((s, r) => s + r[key], 0) / win.length : null;
    });
    const ownLine = smooth('own');
    const foeLine = smooth('foe');

    const W = 1000, H = 300, L = 48, R = 22, TOP = 28, BOT = H - 34;
    const span = Math.max(1, total);
    const x = (t) => L + (t / span) * (W - L - R);
    const y = (v) => TOP + (1 - v) * (BOT - TOP);
    const path = (vals) => {
      let d = '', open = false;
      vals.forEach((v, i) => {
        if (!num(v)) { open = false; return; }
        d += `${open ? 'L' : 'M'}${x(rows[i].t).toFixed(1)},${y(v).toFixed(1)}`;
        open = true;
      });
      return d;
    };
    const ownPath = path(ownLine);
    const lastOwn = ownLine.reduce((acc, v, i) => (num(v) ? i : acc), -1);
    const firstOwn = ownLine.findIndex((v) => num(v));
    const area = ownPath && lastOwn > firstOwn
      ? `${ownPath}L${x(rows[lastOwn].t).toFixed(1)},${BOT}L${x(rows[firstOwn].t).toFixed(1)},${BOT}Z`
      : '';
    const own = rows.filter((r) => num(r.own));
    const avg = own.length ? own.reduce((s, r) => s + r.own, 0) / own.length : null;
    const ahead = own.length ? own.filter((r) => r.own > 0.5).length / own.length * 100 : null;

    const phases = phaseWindows(total).map((w, k) => {
      const a = x(w.start), b = x(w.end);
      if (b <= a) return '';
      return `<rect class="fr-band${k % 2 ? ' alt' : ''}" x="${a.toFixed(1)}" y="${TOP}" width="${Math.max(0, b - a).toFixed(1)}" height="${BOT - TOP}"/>
        <text class="fr-band-label" x="${((a + b) / 2).toFixed(1)}" y="${TOP - 9}" text-anchor="middle">${w.label}</text>`;
    }).join('');
    const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line class="fr-grid${v === 0.5 ? ' mid' : ''}" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>
      <text class="fr-axis" x="${L - 10}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${Math.round(v * 100)}%</text>`).join('');
    const ticks = [];
    for (let t = 0; t <= total; t += 120) ticks.push(`<text class="fr-axis" x="${x(t).toFixed(1)}" y="${H - 12}" text-anchor="middle">${time(t)}</text>`);

    return `<div class="md-front">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="双方阵线随时间变化">
        <defs><linearGradient id="fr-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style="stop-color:var(--md-gold);stop-opacity:.26"/>
          <stop offset="1" style="stop-color:var(--md-gold);stop-opacity:0"/>
        </linearGradient></defs>
        ${phases}${grid}${ticks.join('')}
        <path class="fr-area" d="${area}"/>
        <path class="fr-line foe" d="${path(foeLine)}"/>
        <path class="fr-line own" d="${ownPath}"/>
      </svg>
      <div class="md-front-foot">
        <div class="md-front-legend">
          <span class="own"><i></i>本队</span>
          <span class="foe"><i></i>对手</span>
        </div>
        <div class="md-front-stats">
          <span><small>本队平均阵线</small><b>${num(avg) ? Math.round(avg * 100) + '%' : '—'}</b></span>
          <span><small>压过中线的时间</small><b>${num(ahead) ? Math.round(ahead) + '%' : '—'}</b></span>
          <span><small>口径</small><b>五人平均推进 · 3 点平滑</b></span>
        </div>
      </div>
    </div>`;
  }

  /* ── 对位纵深：同一张表，深区（>66%）/ 半区（>50%，即入侵）双口径 ── */
  function duel(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const wins = phaseWindows(duration);
    const step = positions.step || 2;
    const laneOfPlayer = (p) => (LANES.includes(p.position) ? p.position : '游走');
    const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';

    const table = (threshold, ownLabel, foeLabel) => {
      const index = new Map();
      for (const src of positions.players) {
        const info = players.find((p) => p.camp === src.camp && p.slot === src.slot);
        if (!info) continue;
        const mask = activeMask(src.points, step);
        const seconds = [0, 0, 0];
        for (let i = 0; i < src.points.length; i++) {
          if (!mask[i]) continue;
          const t = i * step;
          if (duration && t > duration) break;
          const [x, y] = src.points[i];
          const p = progress(x, y);
          const inside = src.camp === 'blue' ? p > threshold : p < 1 - threshold;
          if (!inside) continue;
          const phase = wins.findIndex((w) => t < w.end);
          seconds[phase < 0 ? seconds.length - 1 : phase] += step;
        }
        index.set(`${src.camp}-${laneOfPlayer(info)}`, { info, seconds });
      }
      const rows = LANES.map((lane) => {
        const own = index.get(`${ownCamp}-${lane}`);
        const foe = index.get(`${foeCamp}-${lane}`);
        const cell = (entry, side) => {
          if (!entry) return `<span class="md-duel-cell ${side} empty">—</span>`;
          return entry.seconds.map((sec) => (sec <= 0
            ? `<span class="md-duel-cell ${side} is-zero"><b>0<small>秒</small></b></span>`
            : `<span class="md-duel-cell ${side}">
            <b>${fmt(sec)}<small>秒</small></b>
            <span class="md-vox">${'<i></i>'.repeat(clamp(Math.round(sec / 10), 0, 10))}</span>
          </span>`)).join('');
        };
        return `<div class="md-duel-row"><span class="md-duel-lane">${lane}</span>
          <div class="md-duel-side own">${cell(own, 'own')}</div>
          <div class="md-duel-side foe">${cell(foe, 'foe')}</div></div>`;
      }).join('');
      const head = `<div class="md-duel-head"><span></span><span class="own">${ownLabel}</span><span class="foe">${foeLabel}</span></div>
        <div class="md-duel-phases"><span></span><span class="own"><i>前期</i><i>中期</i><i>后期</i></span><span class="foe"><i>前期</i><i>中期</i><i>后期</i></span></div>`;
      return `<div class="md-duel">${head}${rows}</div>`;
    };

    const view = (mode, body, caption) => `<div class="md-panel-view" data-md-duel-view="${mode}"${duelMode === mode ? '' : ' hidden'}>
      ${caption ? `<p class="md-panel-note">${caption}</p>` : ''}${body}</div>`;
    const tab = (mode, text) => `<button type="button" role="tab" class="md-seg-btn${duelMode === mode ? ' is-on' : ''}"
      aria-selected="${duelMode === mode}" data-md-duel-mode="${mode}">${text}</button>`;
    return `<div class="md-depth" data-md-duel>
      <div class="md-panel-bar">
        <div class="md-seg" role="tablist" aria-label="纵深口径">${tab('deep', '深区 >66%')}${tab('half', '半区 >50%（入侵）')}</div>
        <p class="md-panel-note">静止 ≥12 秒的样本（阵亡停留等）已剔除，与全景页同口径</p>
      </div>
      ${view('deep', table(DEEP, '本队 · 推进到对侧深区', '对手 · 推进到本队深区'), '')}
      ${view('half', table(HALF, '本队 · 进入对侧半区', '对手 · 进入本队半区'),
        '越过中线（推进进度 > 50%）即算进入对侧半区，也就是入侵；同一套采样，只换了阈值')}
    </div>`;
  }

  /* ── 交互：比赛脉搏指针 ─────────────────────────────────────────── */
  function bindPulse(root, series, events, ownCamp) {
    const box = root.querySelector('[data-pulse]');
    if (!box || !series.length) return;
    const svg = box.querySelector('.mp-svg');
    const cursor = box.querySelector('.mp-cursor');
    const line = cursor?.querySelector('line');
    const dot = cursor?.querySelector('circle');
    const clock = box.querySelector('[data-pulse-clock]');
    const ownOut = box.querySelector('[data-pulse-blue]');
    const foeOut = box.querySelector('[data-pulse-red]');
    const diffOut = box.querySelector('[data-pulse-diff]');
    const atOut = box.querySelector('[data-pulse-at]');
    if (!svg || !cursor) return;

    const t0 = Number(box.dataset.t0), t1 = Number(box.dataset.t1);
    const L = 58, R = 982, W = 1000;
    const nearest = (t) => series.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a, series[0]);

    const move = (event) => {
      const rect = svg.getBoundingClientRect();
      const px = clamp(event.clientX - rect.left, 0, rect.width);
      const t = t0 + (px / rect.width * W - L) / (R - L) * (t1 - t0);
      const point = nearest(clamp(t, t0, t1));
      const x = L + (point.t - series[0].t) / Math.max(1, series.at(-1).t - series[0].t) * (R - L);
      const absMax = Math.max(1000, ...series.map((p) => Math.abs(p.diff)));
      const limit = Math.ceil(absMax / 5000) * 5000;
      const low = Math.min(0, ...series.map((p) => p.diff)) < 0 ? -limit : 0;
      const high = limit;
      const y = 26 + (high - point.diff) / (high - low) * (250 - 26);
      cursor.removeAttribute('hidden');
      line.setAttribute('x1', x.toFixed(1)); line.setAttribute('x2', x.toFixed(1));
      dot.setAttribute('cx', x.toFixed(1)); dot.setAttribute('cy', y.toFixed(1));
      clock.textContent = time(point.t);
      ownOut.textContent = fmt(point.own);
      foeOut.textContent = fmt(point.foe);
      diffOut.textContent = diff(point.diff);
      const near = (events || []).filter((e) => num(e.t) && Math.abs(e.t - point.t) <= 45)
        .sort((a, b) => Math.abs(a.t - point.t) - Math.abs(b.t - point.t))[0];
      atOut.textContent = near
        ? `${time(near.t)} ${near.kind === 'structure' ? '建筑' : near.kind === 'resource' ? '资源' : '击杀'} · ${near.killer || near.killerHero || ''}`
        : '该时刻附近没有记录事件';
    };
    const card = box.querySelector('[data-pulse-card]');
    const markList = (events || []).filter((e) => num(e.t) && (e.kind === 'resource' || e.kind === 'structure'));
    const showCard = (index, event) => {
      const item = markList[Number(index)];
      if (!card || !item) return;
      const side = item.killerCamp === ownCamp ? 'own' : 'foe';
      const sideText = item.killerCamp ? (side === 'own' ? '我方' : '对手') : '';
      card.innerHTML = `<b>${time(item.t)} · ${item.label || item.name || ''}</b>
        <span class="mp-card-side ${side}">${sideText}${item.killerHero || item.killer ? ' · ' + (item.killerHero || item.killer) : ''}</span>
        <small>${item.kind === 'structure' ? '建筑' : '资源'} · 官方回放事件</small>`;
      const host = box.getBoundingClientRect();
      const rect = event.currentTarget.getBoundingClientRect();
      card.hidden = false;
      const left = clamp(rect.left + rect.width / 2 - host.left, 8, host.width - card.offsetWidth - 8);
      const top = rect.top - host.top - card.offsetHeight - 10;
      card.style.left = `${left}px`;
      card.style.top = `${Math.max(4, top)}px`;
    };
    svg.addEventListener('click', (event) => {
      const mark = event.target.closest('.mp-mark');
      if (!mark) return;
      event.stopPropagation();
      showCard(mark.dataset.mark, event);
    });
    svg.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const mark = event.target.closest('.mp-mark');
      if (!mark) return;
      event.preventDefault();
      showCard(mark.dataset.mark, event);
    });
    document.addEventListener('pointerdown', (event) => {
      if (!box.contains(event.target)) card && (card.hidden = true);
    });
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', () => { cursor.setAttribute('hidden', ''); });
  }

  return { totals, pulse, phaseTable, panel, heat, duel, jungleJoin, cohesion, battle, frontline, bindPulse, bindPanel, bindHeat, bindBattle };
}
