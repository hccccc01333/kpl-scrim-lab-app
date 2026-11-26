import { normalizedCamp, sampleNear } from './match-recap-metrics.js';
import { glyph } from './ui-icons.js';
/* 单局深度分析：比赛脉搏 / 总量 / 阶段对比 / 十人面板 / 十人热区 / 对位深区。
   全部为纯函数式构建，数据来自 /api/matches/<key>、/api/replay/<key>、/api/positions/<key>。
   视觉口径：深墨蓝底 + 金（本队）· 青（对手）+ 等宽数字 + 体素方块。 */

const MAP = 60;          // 地图坐标半径（营地回放为 [-57, 57]）
const GRID = 20;         // 热区网格（每格 6 个坐标单位）
const DEEP = 0.66;       // 深区阈值（推进进度）
const HALF = 0.5;        // 半区阈值（越过中线即入侵）
const STILL_SECONDS = 12; // 连续静止超过该秒数视为死亡/暂停，样本剔除（与全景页一致）
const PROX_RADIUS = 22.5; // 集结半径：地图对角线 149.91 的 15%
const PROX_SECONDS = 5;   // 集结需持续时长
/* 并线（教练 2026-11-10 第四波口径）：兵线在的时候，同一条路上本队 2～3 个人一起吃
   这波线。交汇点会随推塔前后移动（也可能被反推到自家二塔甚至高地前），所以只按
   「这波兵已经出了」切窗口，不假定交汇位置；三路走廊用回放坐标里的定值折线。
   阈值都收在这里，改口径只改这一处。 */
const WAVE_FIRST = 10;        // 第一波兵线出发（docs/economy_rules.md §4.1：10+33(n−1)）
const WAVE_GAP = 33;          // 波次间隔
const LANE_CORRIDOR = 15;     // 到该路折线的距离上限（塔位内缩约 15）
const LANE_CLUSTER = 20;      // 一起吃线的彼此距离上限
const LANE_BASE = 34;         // 己方基地半径内不算（出生点压在边路延长线上）
const LANE_HOLD = 4;          // 同处最短时长
/* 热区画布：每格 HEAT_PX 像素（内部渲染分辨率，CSS 再缩放到卡片宽度） */
const HEAT_PX = 24;
/* 四个红蓝 BUFF 的点位（±60 坐标）：不是拍的，按回放 killbuff 事件
   （dtID 10=蓝 / 11=红、dtCamp 归属）的击杀时刻取击杀者坐标中位数反推——
   蓝方蓝 (−30,0)、蓝方红 (0,−33)、红方蓝 (30,0)、红方红 (0,33)，镜像对得上。
   营地回放坐标没有官方图例，这四个点就是「教练能认出来的地标」。 */
const MAP_BUFFS = [
  { x: -30, y: 0, kind: 'blue', owner: 'blue' },
  { x: 0, y: -33, kind: 'red', owner: 'blue' },
  { x: 30, y: 0, kind: 'blue', owner: 'red' },
  { x: 0, y: 33, kind: 'red', owner: 'red' },
];
const MAP_BASES = [
  { x: -52, y: -54, owner: 'blue' },
  { x: 52, y: 54, owner: 'red' },
];
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
          stat.waves.push({ t: bucket.t, wave: bucket.wave, lane: bucket.lane, size: bucket.size, who: [...bucket.who] });
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
  /* 赛训组自定义评级（grade-rules 设置页）：注入后可给选手字段显示档位徽标；
     未保存规则时注入的函数返回 null，界面不显示徽标，退回原展示。 */
  const fieldGrade = h.fieldGrade || (() => null);
  const subjectOf = h.subjectOf || (() => '');
  const phaseWindows = h.phases || ((duration) => {
    const total = Number(duration) > 0 ? Number(duration) : 0;
    return [['0–4', 0, 240], ['4–10', 240, 600], ['10–结束', 600, Infinity]]
      .map(([label, start, end]) => {
        const a = Math.min(start, total);
        const b = Math.min(end === Infinity ? total : end, total);
        return { label, start: a, end: Math.max(a, b) };
      });
  });

  /* ── 总量：总经济 / 击杀 / 输出 / 承伤（附每分钟值，跨时长可比） ───── */
  function totals(m) {
    const own = m.own || {}, foe = m.enemy || {};
    const duration = Number(m.duration) > 0 ? Number(m.duration) : null;
    const perMinute = (value) => duration && num(value) ? value / duration * 60 : null;
    const items = [
      ['总经济', own.gold, foe.gold, (v) => fmt(v)],
      ['击杀', own.kills, foe.kills, (v) => fmt(v)],
      ['输出', own.damage, foe.damage, (v) => fmt(v)],
      ['承伤', own.taken, foe.taken, (v) => fmt(v)],
    ];
    const cells = items.map(([label, a, b, show]) => {
      const total = (num(a) ? a : 0) + (num(b) ? b : 0);
      const share = num(a) && num(b) && total > 0 ? a / total * 100 : 50;
      const ownPm = perMinute(a), foePm = perMinute(b);
      const sub = ownPm !== null && foePm !== null
        ? `${fmt(ownPm, 1)} : ${fmt(foePm, 1)} /分` : '';
      return `<div class="tot">
        <div class="tot-label">${esc(label)}</div>
        <div class="tot-nums"><b class="own">${show(a)}</b><span>:</span><b class="foe">${show(b)}</b></div>
        <div class="tot-bar"><i class="own" style="width:${share.toFixed(1)}%"></i><i class="foe"></i></div>
        <div class="tot-sub">${sub}</div>
      </div>`;
    }).join('');
    return `<div class="tot-head">
        <h1>总量</h1>
        <span class="chip own">${esc(m.ownName || '本队')}</span>
        <span class="vs">vs</span>
        <span class="chip foe">${esc(m.foeName || '对手')}</span>
      </div>
      <div class="tot-grid">${cells}</div>`;
  }

  /* ── 比赛脉搏 ─────────────────────────────────────────────────────
     图形沿用设计稿（design-redblue/本局结论_红蓝渐变版.html）的横轴与配色，
     但 2026-11-22 教练要求结论卡「变小」：卡片不再锁 881×734，脉搏图
     改成独立矮画布（881×200），悬停坐标同步缩短。 */
  function pulse(series, events, duration, camps) {
    if (!series.length) return '';
    const W = 881, H = 200;
    const L = 78, R = 838, ZERO = 102, UNIT = 58;   // UNIT = 满量程对应的像素
    const t0 = series[0].t, t1 = series.at(-1).t;
    const span = Math.max(1, t1 - t0);
    const absMax = Math.max(1000, ...series.map((p) => Math.abs(p.diff)));
    const limit = Math.max(10000, Math.ceil(absMax / 5000) * 5000);
    const x = (t) => L + (t - t0) / span * (R - L);
    const y = (v) => ZERO - v / limit * UNIT;
    const top = ZERO - UNIT, bot = ZERO + UNIT;
    const tip = series.at(-1);

    /* 阶段色块 + 段名：设计稿三块底色（我方侧极淡蓝 / 中段更淡 / 对侧淡红） */
    const wins = duration > 0 ? phaseWindows(duration) : [];
    const bandFill = ['rgba(45,110,190,0.045)', 'rgba(45,110,190,0.018)', 'rgba(190,60,60,0.035)'];
    let bands = '', bandLabels = '';
    wins.forEach((w, i) => {
      const a = Math.max(w.start, t0), b = Math.min(w.end, t1);
      if (b <= a) return;
      const xa = x(a), xb = x(b);
      bands += `<rect x="${xa.toFixed(1)}" y="${ZERO - UNIT}" width="${(xb - xa).toFixed(1)}" height="${(UNIT * 2.24).toFixed(1)}" fill="${bandFill[i] || bandFill[1]}"/>`;
      bandLabels += `<text x="${((xa + xb) / 2).toFixed(1)}" y="${ZERO - UNIT - 11}" text-anchor="middle" class="mp-band-label">${esc(w.label)}</text>`;
    });

    /* 横向网格 + 左侧刻度：±5k / ±10k …，0 单独画实线 */
    const stepSize = limit >= 20000 ? 10000 : 5000;
    let grid = '';
    for (let v = -limit; v <= limit; v += stepSize) {
      if (v === 0) continue;
      const yy = y(v);
      grid += `<line x1="${L}" x2="${R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" class="mp-grid"/>`;
      grid += `<text x="${L - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" class="mp-axis">${v / 1000}k</text>`;
    }
    grid += `<line x1="${L}" x2="${R}" y1="${ZERO}" y2="${ZERO}" class="mp-zero"/>`;
    grid += `<text x="${L - 8}" y="${ZERO + 4}" text-anchor="end" class="mp-axis">0</text>`;

    /* 曲线 + 面积 + 每个采样点的小圆点（设计稿是逐点画点，不是只画端点） */
    const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.diff).toFixed(1)}`).join(' ');
    const dots = series.map((p) => `<circle cx="${x(p.t).toFixed(1)}" cy="${y(p.diff).toFixed(1)}" r="3" class="mp-dot"/>`).join('');

    /* 事件标记：菱形＝龙 / 圆＝BUFF / 方＝防御塔 / 大方＝水晶，画在曲线上方 13px */
    const diffAt = (t) => sampleNear(series, t)?.diff ?? null;
    const markKind = (e) => {
      if (e.kind === 'structure') return /水晶/.test(e.label || '') ? 'core' : 'tower';
      return /BUFF/.test(e.label || '') ? 'buff' : 'dragon';
    };
    const shapeOf = (kind, cx, cy) => {
      if (kind === 'tower') return `<rect x="${(cx - 4).toFixed(1)}" y="${(cy - 4).toFixed(1)}" width="8" height="8" rx="1"/>`;
      if (kind === 'core') return `<rect x="${(cx - 5.5).toFixed(1)}" y="${(cy - 5.5).toFixed(1)}" width="11" height="11" rx="2"/>`;
      if (kind === 'buff') return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4"/>`;
      return `<path d="M${cx.toFixed(1)},${(cy - 5.5).toFixed(1)} L${(cx + 5.5).toFixed(1)},${cy.toFixed(1)} L${cx.toFixed(1)},${(cy + 5.5).toFixed(1)} L${(cx - 5.5).toFixed(1)},${cy.toFixed(1)} Z"/>`;
    };
    const markList = (events || []).filter((e) => num(e.t) && e.t >= t0 && e.t <= t1
      && (e.kind === 'resource' || e.kind === 'structure') && num(diffAt(e.t)));
    const marks = markList.map((e, i) => {
      const killer = normalizedCamp(e.killerCamp);
      const c = !['blue', 'red'].includes(killer) ? 'unknown' : killer === normalizedCamp(camps.own) ? 'own' : 'foe';
      const cx = x(e.t), cy = y(diffAt(e.t)) - 13;
      return `<g class="mp-mark ${c} ${markKind(e)}" data-mark="${i}" tabindex="0" role="button"
        aria-label="${esc(time(e.t) + ' ' + (e.label || ''))}"><title>${esc(time(e.t) + ' · ' + (e.label || '') + ' · ' + (e.killerHero || e.killer || ''))}</title>${shapeOf(markKind(e), cx, cy)}</g>`;
    }).join('');

    return `<div class="mp" data-pulse data-t0="${t0}" data-t1="${t1}" data-duration="${duration}">
      <div class="mp-readout">
        <span><small>指针时刻</small><b class="clock" data-pulse-clock>${time(t0)}</b></span>
        <span><small class="own">本队经济</small><b data-pulse-blue>${fmt(series[0].own)}</b></span>
        <span><small class="foe">对手经济</small><b data-pulse-red>${fmt(series[0].foe)}</b></span>
        <span><small>经济差</small><b data-pulse-diff>${diff(series[0].diff)}</b></span>
        <span class="mp-at" data-pulse-at hidden></span>
      </div>
      <div class="mp-card" data-pulse-card hidden></div>
    </div>
    <div class="mp-chart">
      <svg class="mp-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img"
      aria-label="经济差随时间变化，共 ${series.length} 个采样点">
      <defs>
        <linearGradient id="mp-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#2f7fe0" stop-opacity=".30"/>
          <stop offset="1" stop-color="#2f7fe0" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${bands}
      ${bandLabels}
      ${grid}
      <path d="${line} L${x(tip.t).toFixed(1)},${ZERO} L${x(t0).toFixed(1)},${ZERO} Z" fill="url(#mp-area)"/>
      <path d="${line}" class="mp-curve"/>
      ${dots}
      <circle cx="${x(tip.t).toFixed(1)}" cy="${y(tip.diff).toFixed(1)}" r="4.5" class="mp-end"/>
      <text x="58" y="${H - 10}" class="mp-axis mp-axis-x">${time(t0)}</text>
      <text x="838" y="${H - 10}" text-anchor="end" class="mp-axis mp-axis-x">${time(t1)}</text>
      <rect class="mp-hit" x="${L}" y="${top}" width="${R - L}" height="${bot - top}" fill="transparent"/>
      ${marks}<!-- 必须画在 mp-hit 之后：命中矩形覆盖整张图，放前面会把标记盖住，
                  鼠标点不开事件浮层（指针移动仍冒泡到 svg，读数不受影响）。 -->
      <g class="mp-cursor" hidden>
        <line x1="0" x2="0" y1="${top}" y2="${bot}"/>
        <circle cx="0" cy="0" r="5"/>
      </g>
      </svg>
    </div>`;
  }

  /* ── 阶段对比（1:1 设计稿 7 列卡片式）─────────────────────────── */
  function phaseTable(rows) {
    if (!rows.length) return '';
    const head = `<div class="ph-head"><h1>阶段对比</h1><span class="tag">本局描述</span></div>
      <div class="ph-cols"><span>阶段</span><span>本队 / 分</span><span>对手 / 分</span>
      <span>净差 / 分</span><span>红蓝BUFF</span><span>防御塔</span><span>入侵</span></div>`;
    const body = rows.map((r) => {
      /* 赛训组 2026-11-19：阶段对比里的横向细长条删除，只留数字。 */
      const econ = (side, value) => `<div class="ph-econ">
        <small>${side === 'own' ? '本队经济' : '对手经济'} / 分</small>
        <div class="pv"><b class="${side}">${diff(value)}</b></div>
      </div>`;
      const net = num(r.net)
        ? `<b class="${r.net >= 0 ? 'up' : 'down'}">${r.net >= 0 ? '本队多' : '对手多'} ${fmt(Math.abs(r.net))}</b>`
        : '—';
      return `<div class="phase">
        <div class="ph-name"><b>${esc(r.label)}</b><small>${esc(r.range)}</small></div>
        ${econ('own', r.ownGain, r.ownPct)}
        ${econ('foe', r.foeGain, r.foePct)}
        <div class="ph-net"><small>净差 / 分</small>${net}</div>
        <div class="ph-mini"><small>红蓝BUFF</small><b>${fmt(r.res.own)} : ${fmt(r.res.foe)}</b></div>
        <div class="ph-mini"><small>防御塔</small><b>${fmt(r.struct.own)} : ${fmt(r.struct.foe)}</b></div>
        <div class="ph-mini"><small>入侵</small><b class="inv">${r.invade === null ? '—' : pct(r.invade)}</b></div>
      </div>`;
    }).join('');
    return `<div class="md-phase-table">${head}${body}</div>`;
  }

  /* ── 十人面板：对位比较 / 同队比较 ───────────────────────────────── */
  const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  /* 对位筛选按设计稿顺序：对抗路 / 打野 / 中路 / 发育路 / 游走。 */
  const LANE_TABS = ['对抗路', '打野', '中路', '发育路', '游走'];
  const read = (p, key) => (p && num(p[key]) ? p[key] : null);
  const laneOf = (p) => (LANES.includes(p.position) ? p.position : '游走');
  let panelMode = 'duel';
  let panelLane = LANE_TABS[0];
  let duelMode = 'half'; // 半区 >50%（入侵）优先显示
  let panelBound = false;
  let heatLane = LANES[0];
  let heatState = null;
  let heatBound = false;
  let heatTimer = null;
  let heatSpeed = 1;      // 播放倍速：1× / 2× / 4×（循环切换）
  const HEAT_SPEEDS = [1, 2, 4];
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
    /* 分路名单可能缺人 / 重复（营地 position 字段偶发异常），
       duelView 会给缺员分路传 undefined；这里统一判空，避免整局页被一个空选手打断。 */
    const cutOf = (p) => (p && killStats ? killStats.get(`${p.camp}-${p.hero}`) : null);
    const surviveOf = (p) => (p && survival ? survival.get(`${p.camp}-${p.hero}`) : null);
    const roamOf = (p) => (p && roam ? roam.get(`${p.camp}-${p.hero}`) : null);
    const joinOf = (p) => (p && join ? join.get(`${p.camp}-${p.slot}`) : null);
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
    // Do not draw missing dimensions as zero-length radar spokes.
    const plotMetrics = metrics.filter((m) => num(m.get(a)) && num(m.get(b)));
    const n = plotMetrics.length;
    if (n < 3) return '<div class="md-fl-empty">可比较指标不足</div>';
    const size = 132, c = size / 2, R = 44;
    const angle = (i) => -Math.PI / 2 + i * Math.PI * 2 / n;
    const pt = (i, r) => [c + Math.cos(angle(i)) * r, c + Math.sin(angle(i)) * r];
    const scale = plotMetrics.map((m) => Math.max(1, m.get(a), m.get(b)));
    const area = (p, side) => {
      if (!p) return '';
      const points = plotMetrics.map((m, i) => pt(i, Math.max(2.5, clamp(m.get(p) / scale[i], 0, 1) * R)));
      return `<polygon class="md-fl-area ${side}" points="${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}"/>`;
    };
    const ring = (k) => `<polygon class="md-fl-ring" points="${plotMetrics.map((_, i) => pt(i, R * k).map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
    const spokes = plotMetrics.map((_, i) => {
      const [x, y] = pt(i, R);
      return `<line class="md-fl-spoke" x1="${c}" y1="${c}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
    }).join('');
    /* 轴标签去掉：132px 里放 5 个中文标签会被 viewBox 裁掉一半，看起来像乱码。
       右侧每一行就是同一顺序的轴，标签在那一边已经有了。 */
    const name = `${(a && (a.label || a.hero)) || '本队'} 与 ${(b && (b.label || b.hero)) || '对手'}`;
    return `<svg class="md-fl" viewBox="0 0 ${size} ${size}" role="img" aria-label="对位雷达：${esc(name)}">${[0.34, 0.67, 1].map(ring).join('')}${spokes}${area(a, 'own')}${area(b, 'foe')}</svg>`;
  }

  /* 对位表按设计稿（design-redblue/十人面板_优化版.html）：
     一路一张干净表格，列＝指标 / 本队 / 对手 / 相对差距 / 结论；
     相对差距用「(本队−对手)÷对手」，和设计稿的 +406%、-40%、少 60% 同口径。
     不再画雷达和条。 */
  const panelPick = (players, camp) => {
    const map = new Map();
    for (const p of players) if (p.camp === camp) map.set(laneOf(p), p);
    return map;
  };

  const gapOf = (a, b) => {
    if (!num(a) || !num(b)) return null;
    if (a === b) return { value: 0, text: '持平' };
    if (b === 0) return { value: null, text: a > 0 ? '对手 0' : '—' };
    return { value: (a - b) / Math.abs(b) * 100, text: null };
  };

  const levelOf = (gap, capMid = false) => {
    if (!gap) return 'near';
    if (gap.text === '持平') return 'near';
    if (gap.value === null) return 'big';
    const abs = Math.abs(gap.value);
    if (abs < 10) return 'near';
    if (abs < 100 || capMid) return 'mid';
    return 'big';
  };

  const LEVEL_LABEL = { near: '接近', mid: '明显', big: '大幅' };
  const LEVEL_CLASS = { near: 'is-near', mid: 'is-mid', big: 'is-big' };

  function duelMetricDefs(duration, killStats) {
    const cutOf = (p) => (p && killStats ? killStats.get(`${p.camp}-${p.hero}`) : null);
    const minutes = Number(duration) > 0 ? duration / 60 : 0;
    return [
      { label: '分均经济', field: 'gpm', get: (p) => gpmOf(p, duration), text: (v) => fmt(Math.round(v)) },
      { label: '经济转输出', get: (p) => read(p, 'damageConversion'), text: (v) => fmt(v, 2) },
      /* 「承受」展示总量，但评级按赛训口径用分均承伤 tpm（越低越好）。 */
      { label: '承受', field: 'tpm', get: (p) => read(p, 'taken'), gradeValue: (p) => minutes ? read(p, 'taken') / minutes : null, text: (v) => fmt(v), word: '更高' },
      { label: '对塔伤害', get: (p) => read(p, 'towerDamage'), text: (v) => fmt(v) },
      { label: '切入', get: (p) => (killStats ? (cutOf(p)?.cutC || 0) : null), text: (v) => fmt(v) },
      { label: '死亡', field: 'deaths', get: (p) => read(p, 'deaths'), text: (v) => fmt(v), death: true },
      { label: '参团', field: 'participation', get: (p) => read(p, 'participation'), text: (v) => pct(v) },
    ];
  }
  /* 某个选手在指定指标上的赛训评级徽标；无规则/无值返回空串。 */
  function gradeBadge(def, player) {
    if (!def?.field || !player || typeof fieldGrade !== 'function') return '';
    const value = def.gradeValue ? def.gradeValue(player) : def.get(player);
    const lv = fieldGrade(subjectOf(player), def.field, value);
    return lv ? `<em class="md-grade ${lv.level}" title="赛训规则：${esc(lv.label)}">${esc(lv.label)}</em>` : '';
  }

  function duelView(players, ownCamp, duration, killStats, lane, open = panelLane === lane) {
    const mine = panelPick(players, ownCamp);
    const theirs = panelPick(players, ownCamp === 'blue' ? 'red' : 'blue');
    const a = mine.get(lane), b = theirs.get(lane);
    const who = (p, side) => (p
      ? `<div class="md-duel-player ${side}">${portrait(p.hero, 'md-duel-face')}
          <span><b>${esc(p.hero || p.label || '—')}</b><small>${esc(p.label || '—')}</small></span></div>`
      : `<div class="md-duel-player ${side} is-empty"><span class="md-duel-face is-empty">?</span>
          <span><b>未匹配</b><small>—</small></span></div>`);
    const defs = duelMetricDefs(duration, killStats);
    let ownWins = 0, foeWins = 0, near = 0, big = 0;
    const rows = defs.map((def) => {
      const x = def.get(a), y = def.get(b);
      const gap = gapOf(x, y);
      const level = levelOf(gap, def.death);
      const hasGap = Boolean(gap);
      let gapText = '—';
      if (hasGap) {
        if (gap.text) gapText = gap.text;
        else if (gap.value === null) gapText = '—';
        else {
          const value = `${gap.value > 0 ? '+' : ''}${fmt(gap.value)}%`;
          gapText = def.death
            ? `${gap.value < 0 ? '少' : '多'} ${fmt(Math.abs(gap.value))}%`
            : value;
        }
      }
      const diff = num(x) && num(y) ? x - y : null;
      /* 死亡是「越少越好」，其余指标都是越高越好。 */
      const better = !num(x) || !num(y) || diff === 0 ? ''
        : def.death ? (diff < 0 ? 'own' : 'foe') : (diff > 0 ? 'own' : 'foe');
      if (level !== 'near') {
        if (better === 'own') { ownWins += 1; if (level === 'big') big += 1; }
        else if (better === 'foe') foeWins += 1;
      } else if (num(x) && num(y)) near += 1;
      const winner = better;
      const verdict = !num(x) || !num(y) || diff === null
        ? '<span class="md-duel-j is-mute">—</span>'
        : level === 'near'
          ? '<span class="md-duel-j is-mute">基本接近</span>'
          : `<span class="md-duel-j is-${winner}">${winner === 'own' ? '本队' : '对手'}${def.word || LEVEL_LABEL[level]}${def.word ? '' : '优'}</span>`;
      const badgeA = gradeBadge(def, a), badgeB = gradeBadge(def, b);
      return `<div class="md-duel-row">
        <span class="md-duel-name">${def.label}<i class="md-duel-level ${LEVEL_CLASS[level]}">${LEVEL_LABEL[level]}</i></span>
        <b class="md-duel-num">${num(x) ? def.text(x) : '—'}${badgeA}</b>
        <b class="md-duel-num">${num(y) ? def.text(y) : '—'}${badgeB}</b>
        <b class="md-duel-gap ${winner ? 'is-' + winner : 'is-mute'}">${gapText}</b>
        ${verdict}
      </div>`;
    }).join('');
    const summary = [
      `本队 <b>${ownWins}</b> 项占优${big ? `（<b>${big}</b> 项大幅）` : ''}`,
      `对手 <b>${foeWins}</b> 项占优`,
      near ? `<b>${near}</b> 项接近` : '',
    ].filter(Boolean).join(' · ');
    return `<div class="md-duel-card" data-md-lane-view="${lane}"${open ? '' : ' hidden'}>
      <div class="md-duel-top">
        ${who(a, 'own')}
        <div class="md-duel-summary">${summary}</div>
        ${who(b, 'foe')}
      </div>
      <div class="md-duel-head"><span>指标</span><span>本队</span><span>对手</span><span>相对差距</span><span>结论</span></div>
      <div class="md-duel-rows">${rows}</div>
    </div>`;
  }

  function teamTable(players, camp, label, side, inv) {
    const team = players.filter((p) => p.camp === camp)
      .sort((a, b) => LANE_TABS.indexOf(laneOf(a)) - LANE_TABS.indexOf(laneOf(b))).slice(0, 5);
    if (!team.length) return '';
    const defs = [
      { label: '经济', get: (p) => read(p, 'gold'), share: true },
      { label: '输出', get: (p) => read(p, 'damage'), share: true },
      { label: '承受', get: (p) => read(p, 'taken'), share: true },
      { label: '团战', get: (p) => read(p, 'participation'), share: false },
      { label: '发育', get: (p) => read(p, 'cs'), share: true },
      { label: '入侵', get: (p) => (inv ? (inv.get(`${p.camp}-${p.slot}`)?.rate ?? null) : null), share: false },
    ];
    const sums = defs.map((def, i) => (def.share
      ? team.reduce((sum, p) => sum + (num(def.get(p)) ? def.get(p) : 0), 0)
      : null));
    const values = team.map((p) => defs.map((def, i) => {
      const v = def.get(p);
      if (!num(v)) return null;
      if (!def.share) return v;
      return sums[i] > 0 ? v / sums[i] * 100 : null;
    }));
    const ranks = defs.map((_, i) => {
      const sorted = values.map((row) => row[i]).filter((v) => num(v)).sort((a, b) => b - a);
      return new Map(sorted.map((v, index) => [v, index + 1]));
    });
    const cols = `grid-template-columns:190px repeat(${defs.length}, minmax(0,1fr))`;
    const head = `<div class="md-team-row md-team-head" style="${cols}"><span>选手</span>${defs.map((def) => `<span>${def.label}</span>`).join('')}</div>`;
    const body = team.map((p, r) => `<div class="md-team-row" style="${cols}">
      <span class="md-team-who">${portrait(p.hero, 'md-team-face')}<span><b>${esc(p.hero || p.label || '—')}</b><small>${esc(p.label || '—')}</small></span></span>
      ${values[r].map((v, i) => {
        const rank = num(v) ? ranks[i].get(v) : null;
        const first = rank === 1;
        return `<span class="md-team-cell${first ? ' is-first' : ''}">${num(v) ? `<b>${pct(v)}</b>` : '<b>—</b>'}<i>${rank ? ['1st', '2nd', '3rd', '4th', '5th'][rank - 1] || '' : ''}</i></span>`;
      }).join('')}
    </div>`).join('');
    return `<div class="md-team-card ${side}">
      <div class="md-team-title">${esc(label)}<span>${team.length} 人</span></div>
      ${head}${body}
    </div>`;
  }

  function panel(players, ownCamp, positions, duration, kills, fights, deaths) {
    if (!players || !players.length) return `<div class="empty">这场比赛还没有十人面板数据。</div>`;
    if (!ownCamp) return `<div class="empty">阵营未知，无法做同队比较。</div>`;
    /* 兼容 ownCamp 为 left / right 的历史写法 */
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    const foeCamp = camp === 'blue' ? 'red' : 'blue';
    const ownName = `本队 · ${camp === 'blue' ? '蓝方' : '红方'}`;
    const foeName = `对手 · ${foeCamp === 'blue' ? '蓝方' : '红方'}`;
    const inv = positions && positions.players && positions.players.length ? invasionStats(positions, players, duration) : null;
    /* 对位比较已由首屏五路表的「详细数据」就地展开，面板只保留队内名次。 */
    return `<div class="md-panel" data-md-panel>
      <div class="md-panel-view" data-md-view="team">
        <div class="md-panel-subtitle">同队比较 · 队内名次</div>
        <div class="md-teams">${teamTable(players, camp, ownName, 'own', inv)}${teamTable(players, foeCamp, foeName, 'foe', inv)}</div>
      </div>
    </div>`;
  }

  /* 首屏五路表的「详细数据」：一次生成五条对位的完整卡片，点击时只切 hidden。 */
  function laneViews(players, ownCamp, duration, kills) {
    if (!players || !players.length) return {};
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    if (camp !== 'blue' && camp !== 'red') return {};
    const killStats = kills && kills.length ? killStatsFor(players, kills) : null;
    return Object.fromEntries(LANE_TABS.map((lane) => [lane, duelView(players, camp, duration, killStats, lane, true)]));
  }

  function bindPanel(root) {
    if (panelBound) return;
    panelBound = true;
    const syncLane = (box) => {
      box.querySelectorAll('[data-md-lane]').forEach((b) => {
        const on = b.dataset.mdLane === panelLane;
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-selected', String(on));
      });
      box.querySelectorAll('[data-md-lane-view]').forEach((view) => {
        view.hidden = view.dataset.mdLaneView !== panelLane;
      });
    };
    root.addEventListener('click', (event) => {
      if (!event.target.closest) return;
      const laneHit = event.target.closest('[data-md-lane]');
      if (laneHit) {
        const box = laneHit.closest('[data-md-panel]');
        if (!box) return;
        panelLane = laneHit.dataset.mdLane;
        syncLane(box);
        return;
      }
      const hit = event.target.closest('[data-md-panel-mode]');
      if (!hit) return;
      const mode = hit.dataset.mdPanelMode;
      const box = hit.closest('[data-md-panel]');
      if (!box) return;
      panelMode = mode;
      box.querySelectorAll('[data-md-panel-mode]').forEach((b) => {
        const on = b.dataset.mdPanelMode === mode;
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-selected', String(on));
      });
      box.querySelectorAll('[data-md-view]').forEach((view) => {
        view.hidden = view.dataset.mdView !== mode;
      });
    });
    /* 初始只显示当前分路；服务端已经按 panelLane 渲染过一次，但重进页面时状态会保持。 */
    root.querySelectorAll('[data-md-panel]').forEach(syncLane);
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
  /* ── 疑似打野并线（设计稿 design-redblue/疑似打野并线_优化版.html）─────────
     只保留 0–4 对线期：卡内数字、时间轴、表格全部只覆盖 0:00–4:00。
     口径仍交给 joinLaneStats（兵线波次出发后，打野和该路队友聚成 2～3 人待满 4 秒）。 */
  function jungleJoin(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    if (camp !== 'blue' && camp !== 'red') return '';
    const foeCamp = camp === 'blue' ? 'red' : 'blue';
    const join = joinLaneStats(positions, players, laneOf);
    const laneOfPlayer = new Map((players || []).map((p) => [`${p.camp}-${p.slot}`, laneOf(p)]));
    const EARLY_END = 240;
    const EARLY_TOTAL = Math.min(EARLY_END, Number(duration) > 0 ? Number(duration) : EARLY_END) || EARLY_END;
    const LANE_ROWS = ['对抗路', '中路', '发育路'];
    const jungler = (side) => {
      const player = (players || []).find((p) => p.camp === side && laneOf(p) === '打野');
      if (!player) return null;
      const stat = join.get(`${player.camp}-${player.slot}`) || { waves: [] };
      const waves = (stat.waves || []).filter((wave) => num(wave.t) && wave.t <= EARLY_END);
      const lanes = { 对抗路: 0, 中路: 0, 发育路: 0 };
      for (const wave of waves) if (lanes[wave.lane] != null) lanes[wave.lane] += 1;
      return {
        player, waves, lanes,
        total: waves.length,
        triples: waves.filter((wave) => wave.size >= 3).length,
      };
    };
    const own = jungler(camp);
    const foe = jungler(foeCamp);
    if (!own && !foe) return '';
    const pctOf = (value) => `${clamp(value / EARLY_TOTAL * 100, 0, 100).toFixed(2)}%`;

    const laneDots = (entry, side, lane) => {
      if (!entry) return '';
      return entry.waves.filter((wave) => wave.lane === lane).map((wave) => {
        const lanes = [...new Set((wave.who || []).map((key) => laneOfPlayer.get(key)).filter(Boolean))];
        const label = `${time(wave.t)} · ${lanes.length ? lanes.join(' + ') : lane} · ${wave.size} 人`;
        return `<i class="md-jl-dot ${side}${wave.size >= 3 ? ' is-trio' : ''}"`
          + ` style="left:${pctOf(wave.t)}" title="${esc(label)}"></i>`;
      }).join('');
    };
    const laneRow = (lane) => `<div class="md-jl-row">
        <span class="md-jl-lane">${lane}</span>
        <div class="md-jl-track">
          <div class="md-jl-marks own">${laneDots(own, 'own', lane)}</div>
          <span class="md-jl-line"></span>
          <div class="md-jl-marks foe">${laneDots(foe, 'foe', lane)}</div>
        </div>
        <span class="md-jl-rowcount"><b class="own">${own ? own.lanes[lane] : 0}</b> / <b class="foe">${foe ? foe.lanes[lane] : 0}</b></span>
      </div>`;

    const card = (entry, side) => {
      if (!entry) return `<article class="md-jl-card ${side} is-empty"><div class="md-jl-tag">${side === 'own' ? '本队' : '对手'}打野</div><p>这局没有这个位置的位置数据</p></article>`;
      const player = entry.player;
      return `<article class="md-jl-card ${side}">
        <div class="md-jl-tag">${side === 'own' ? '本队' : '对手'}打野</div>
        <div class="md-jl-who">${portrait(player.hero, 'md-jl-face')}<span><b>${esc(player.hero || player.label || '—')}</b><small>${esc(player.label || '—')}</small></span></div>
        <div class="md-jl-big">${entry.total}<em>次并线</em></div>
        <div class="md-jl-chips"><span>三人 ${entry.triples}</span><span>双人 ${entry.total - entry.triples}</span></div>
        <div class="md-jl-seg"><span>0–4 对线期</span><b>${entry.total}</b></div>
      </article>`;
    };

    const gap = own && foe ? own.total - foe.total : null;
    const verdict = gap === null ? '缺少打野位置数据'
      : gap === 0 ? '两队打平' : gap > 0 ? `本队多 ${gap} 次` : `对手多 ${Math.abs(gap)} 次`;
    const totalOwn = own ? own.total : 0;
    const totalFoe = foe ? foe.total : 0;

    const tableRows = LANE_ROWS.map((lane) => {
      const a = own ? own.lanes[lane] : 0;
      const b = foe ? foe.lanes[lane] : 0;
      const diff = a === b ? '0 次' : a > b ? `本队多 ${a - b} 次` : `对手多 ${b - a} 次`;
      const tone = a === b ? 'is-mute' : a > b ? 'is-own' : 'is-foe';
      return `<div class="md-jl-tr">
        <span class="md-jl-tlane">${lane}</span>
        <b class="${a === b ? 'is-mute' : a > b ? 'is-win own' : 'is-lose own'}">${a}</b>
        <b class="${a === b ? 'is-mute' : b > a ? 'is-win foe' : 'is-lose foe'}">${b}</b>
        <b class="${tone}">${diff}</b>
      </div>`;
    }).join('');
    const totalTone = totalOwn === totalFoe ? 'is-mute' : totalOwn > totalFoe ? 'is-own' : 'is-foe';
    const totalDiff = totalOwn === totalFoe ? '0 次' : totalOwn > totalFoe ? `本队多 ${totalOwn - totalFoe} 次` : `对手多 ${totalFoe - totalOwn} 次`;

    return `<div class="md-jl">
      <div class="md-jl-cards">
        ${card(own, 'own')}
        <div class="md-jl-mid">
          <small>并线</small>
          <b class="${gap === null ? 'is-mute' : gap > 0 ? 'own' : gap < 0 ? 'foe' : 'is-mute'}">${gap === null ? '—' : `${gap > 0 ? '+' : ''}${gap}`}</b>
          <span>${esc(verdict)}</span>
          <div class="md-jl-legend">
            <span><i class="md-jl-dot own"></i>本队</span>
            <span><i class="md-jl-dot foe"></i>对手</span>
            <span><i class="md-jl-dot is-trio"></i>大点＝三人并线</span>
          </div>
        </div>
        ${card(foe, 'foe')}
      </div>
      <div class="md-jl-timeline">
        <div class="md-jl-title">0–4 对线期 · 并线时刻</div>
        ${LANE_ROWS.map(laneRow).join('')}
        <div class="md-jl-axis"><span>0:00</span><span>1:00</span><span>2:00</span><span>3:00</span><span>4:00</span></div>
      </div>
      <div class="md-jl-table">
        <div class="md-jl-tr head"><span class="md-jl-tlane">并线发生分路</span><span>本队次数</span><span>对手次数</span><span>分路差</span></div>
        ${tableRows}
        <div class="md-jl-tr total"><span class="md-jl-tlane">合计</span>
          <b class="${totalOwn >= totalFoe ? 'is-win own' : 'is-lose own'}">${totalOwn}</b>
          <b class="${totalFoe >= totalOwn ? 'is-win foe' : 'is-lose foe'}">${totalFoe}</b>
          <b class="${totalTone}">${totalDiff}</b></div>
      </div>
    </div>`;
  }

  /* ── 中野辅集结与 BUFF（设计稿 design-redblue/中野辅与入侵_优化版.html）──
     只留集结率 / 集结次数 / 红蓝 BUFF / 推塔矩阵；
     最长集结、平均间距、说明段全部删除。 */
  function cohesion(positions, players, ownCamp, duration, events, kills, extras = {}) {
    if (!positions || !positions.players?.length) return '';
    const prox = proximity(positions, players);
    if (!prox.size) return '';
    const buffs = extras.buffs || [];
    const towerGrid = extras.towers || null;
    const ownSide = ownCamp === 'blue' ? 'blue' : 'red';
    const foeSide = ownSide === 'blue' ? 'red' : 'blue';
    const buffCount = (camp, word) => (buffs.length
      ? buffs.filter((b) => b.killer === camp && String(b.name || '').includes(word)).length
      : null);
    const towerCell = (camp, tier, lane) => (towerGrid ? (towerGrid[camp]?.[tier]?.[lane] || 0) : 0);
    const card = (camp) => {
      const item = prox.get(camp);
      const side = camp === ownSide ? 'own' : 'foe';
      const name = camp === 'blue' ? '蓝方' : '红方';
      const title = `${camp === ownSide ? '本队' : '对手'} · ${name}`;
      if (!item) return `<article class="md-coh-card ${side}"><div class="md-coh-title">${title}</div><p class="md-coh-empty">缺少中/野/辅位置数据</p></article>`;
      const red = buffCount(camp, '红');
      const blue = buffCount(camp, '蓝');
      const towerRows = ['一塔', '二塔', '高地塔'].map((tier) => `<div class="md-coh-tw-row"><span>${tier}</span>
        ${['上路', '中路', '下路'].map((lane) => `<span>${towerCell(camp, tier, lane)}</span>`).join('')}</div>`).join('');
      return `<article class="md-coh-card ${side}">
        <div class="md-coh-title">${title}</div>
        <div class="md-coh-rate"><b>${pct(item.rate)}</b><span>集结率</span></div>
        <div class="md-coh-times"><b>${fmt(item.count)}</b><span>次集结</span></div>
        <div class="md-coh-rule"></div>
        <div class="md-coh-sub">红蓝 BUFF</div>
        <div class="md-coh-buff"><span>红 BUFF <b>${red === null ? '—' : red}</b></span><span>蓝 BUFF <b>${blue === null ? '—' : blue}</b></span></div>
        <div class="md-coh-sub">推塔（上路 / 中路 / 下路）</div>
        <div class="md-coh-tw">
          <div class="md-coh-tw-head"><span></span><span>上路</span><span>中路</span><span>下路</span></div>
          ${towerRows}
        </div>
      </article>`;
    };
    const ownItem = prox.get(ownSide), foeItem = prox.get(foeSide);
    const rateDiff = ownItem && foeItem && num(ownItem.rate) && num(foeItem.rate) ? ownItem.rate - foeItem.rate : null;
    const countDiff = ownItem && foeItem ? ownItem.count - foeItem.count : null;
    const bits = [];
    if (rateDiff !== null) {
      bits.push(rateDiff >= 0
        ? `集结率本队高 <b>+${fmt(rateDiff, 1)}pp</b>`
        : `集结率对手高 <i>+${fmt(Math.abs(rateDiff), 1)}pp</i>`);
    }
    if (countDiff !== null) {
      bits.push(countDiff >= 0
        ? `集结多 <b>${fmt(countDiff)} 次</b>`
        : `集结少 <i>${fmt(Math.abs(countDiff))} 次</i>`);
    }
    const vs = (label, value, side) => `<div><small>${label}</small><b class="${side}">${value}</b></div>`;
    return `<div class="md-coh-wrap">
      ${bits.length ? `<p class="md-coh-summary">${bits.join(' · ')}</p>` : ''}
      <div class="md-coh-grid">
        ${card(ownSide)}
        <div class="md-coh-vs">
          ${vs('集结率', rateDiff === null ? '—' : `${rateDiff >= 0 ? '+' : ''}${fmt(rateDiff, 1)}pp`, rateDiff === null ? 'is-mute' : rateDiff >= 0 ? 'own' : 'foe')}
          ${vs('集结次数', countDiff === null ? '—' : `${countDiff >= 0 ? '+' : ''}${fmt(countDiff)}`, countDiff === null ? 'is-mute' : countDiff >= 0 ? 'own' : 'foe')}
        </div>
        ${card(foeSide)}
      </div>
    </div>`;
  }

  /* ── 热区：时间窗 + 十人 / 对位两视图（canvas 重绘） ─────────────── */
  function heat(positions, players, ownCamp, duration, replay) {
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
      return { camp: src.camp, slot: src.slot, points: src.points, cells, enemy, mask, info };
    });
    const total = duration || (list[0] ? list[0].points.length * step : 0);
    heatState = { step, duration: total, list };
    /* 赛训组口径的三段：0–4 / 4–10 / 10–结束（标签本身就是时间段） */
    const phaseLabel = ['0–4', '4–10', '10–结束'];

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
          ${canvas(p, HEAT_PX)}
          <div class="hl-meta"><b data-heat-pct="${p.camp}-${p.slot}">—</b> 在对侧半区</div>
        </div>` : '<div class="hl-side empty">没有对位数据</div>');
      return `<article class="md-heat-lane" data-lane="${lane}"${lane === heatLane ? '' : ' hidden'}>
        <div class="hl-pair">${one(own, 'own')}${one(foe, 'foe')}</div>
      </article>`;
    }).join('');

    /* 时间轴上的事件刻度：团战 / 掉点。教练最常问的是「这次团战之前他们怎么走的」，
       所以给可点的刻度，点一下就跳到那一刻，不用拖滑块估位置。 */
    const marks = [];
    for (const fight of (replay?.fights || [])) {
      if (num(fight.t)) marks.push({ t: fight.t, kind: 'fight', label: `团战 ${time(fight.t)}` });
    }
    for (const death of (replay?.deaths || [])) {
      if (num(death.t)) marks.push({ t: death.t, kind: 'death', label: `掉点 ${time(death.t)}` });
    }
    marks.sort((a, b) => a.t - b.t);
    const markHtml = marks.slice(0, 60).map((mark) => {
      const left = clamp(mark.t / Math.max(1, total) * 100, 0, 100).toFixed(2);
      return `<button type="button" class="md-heat-mark is-${mark.kind}" style="left:${left}%"
        data-heat-seek="${Math.round(mark.t)}" title="${esc(mark.label)}（点击跳到这一刻）"
        aria-label="${esc(mark.label)}"></button>`;
    }).join('');

    return `<div class="md-heatwrap" data-md-heat>
      <div class="md-panel-bar">
        <button type="button" class="md-heat-play" data-heat-play aria-pressed="false" title="播放 / 暂停（空格）">${glyph('refresh', { size: 18 })} 播放</button>
        <button type="button" class="md-heat-speed" data-heat-speed title="播放速度（快捷键 S 切换）">${glyph('clock', { size: 18 })} ${heatSpeed}×</button>
        <div class="md-heat-track">
          <input type="range" class="md-heat-range" data-heat-range min="0" max="${Math.round(total)}" step="${step}" value="${Math.round(total)}" aria-label="热区时间轴">
          <div class="md-heat-marks" aria-label="事件刻度">${markHtml}</div>
        </div>
        <span class="md-heat-clock" data-heat-clock>—</span>
        <label class="md-heat-pick"><span>分路</span>
          <select data-heat-lane aria-label="选择分路">
            ${LANES.map((lane) => `<option value="${lane}"${lane === heatLane ? ' selected' : ''}>${lane}</option>`).join('')}
          </select>
        </label>
      </div>
      <div class="md-heat-phases" data-heat-phases>
        ${phaseLabel.map((label, i) =>
          `<button type="button" class="md-heat-phase" data-heat-phase="${[240, 600, Math.round(total)][i]}" title="跳到${label}（快捷键 ${i + 1}）">${glyph('clock', { size: 18 })} ${label}</button>`).join('')}
      </div>
      <div class="md-heats md-heats-lane" data-heat-lanes>${laneCards}</div>
      <div class="md-heat-legend">
        <span><i class="sw is-own"></i>本队</span>
        <span><i class="sw is-foe"></i>对手</span>
        <span><i class="sw is-buff"></i>红 / 蓝＝野区 BUFF</span>
        <span><i class="sw is-dot"></i>末端圆点＝当前时刻</span>
        <span><i class="sw is-ring"></i>描边格＝在对侧半区</span>
        <span><i class="sw is-mark fight"></i>团战刻度　<i class="sw is-mark death"></i>掉点刻度</span>
      </div>
      <p class="md-panel-note">底图：三路（对抗路 / 中路 / 发育路）、河道、双方基地与四个红蓝 BUFF 点位（BUFF 位置由回放 killbuff 事件的击杀时刻坐标反推，与本局坐标同一套 ±60）。窗口 ${HEAT_WINDOW} 秒随指针滚动；静止 ≥12 秒的样本已剔除。格子颜色越深＝停留越久，细线是他这 90 秒的走位。分期按赛训组口径：对线 0–4、发育 4–10、10 分钟以后算后期。</p>
    </div>`;
  }

  function heatCounts(list, i0, i1) {
    const out = new Map();
    let max = 1;
    for (const p of list) {
      const counts = new Uint16Array(GRID * GRID);
      const enemyCells = new Uint8Array(GRID * GRID);
      const end = Math.min(i1, p.cells.length - 1);
      let enemy = 0, total = 0;
      for (let i = i0; i <= end; i++) {
        const cell = p.cells[i];
        if (cell < 0) continue;
        counts[cell] += 1;
        if (counts[cell] > max) max = counts[cell];
        total += 1;
        if (p.enemy[i]) { enemy += 1; enemyCells[cell] = 1; }
      }
      out.set(`${p.camp}-${p.slot}`, { counts, enemyCells, enemy, total });
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
      heatSprites = { own: make('31, 111, 207'), foe: make('207, 63, 63') };
    }
    return heatSprites[side === 'foe' ? 'foe' : 'own'];
  }

  function drawHeat(canvas, data, max, side, player, i0, i1) {
    const ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) return;
    const size = canvas.width;
    const cell = size / GRID;
    const rgb = side === 'foe' ? '207, 63, 63' : '31, 111, 207';
    ctx.clearRect(0, 0, size, size);

    drawHeatMap(ctx, size);
    drawHeatCells(ctx, data, max, rgb, size, cell);
    drawHeatPath(ctx, player, rgb, size, cell, i0, i1);
  }

  /* 地图底图：blur 之前先有「这是哪」，否则热区只是浮在灰底上的方块。
     坐标与本局位置同一套 ±60（x 向右、y 向上），绘制时 y 翻成屏幕坐标。
     红蓝 BUFF 的位置不是拍的：按回放 killbuff（dtID 10=蓝 / 11=红、dtCamp 归属）
     的击杀时刻取击杀者坐标中位数，四个点分别是蓝方蓝 (−30,0)、蓝方红 (0,−33)、
     红方蓝 (30,0)、红方红 (0,33)，中心和镜像都对得上。 */
  function drawHeatMap(ctx, size) {
    const X = (v) => (v + MAP) / (MAP * 2) * size;
    const Y = (v) => size - (v + MAP) / (MAP * 2) * size;
    const team = { blue: '31, 111, 207', red: '207, 63, 63' };
    ctx.save();
    /* 两侧半区底色：蓝方在下半（左下到右上），红方在上半——一眼能分「哪边是我们的」 */
    ctx.fillStyle = 'rgba(91, 143, 196, .07)';
    ctx.beginPath();
    ctx.moveTo(0, size); ctx.lineTo(size, 0); ctx.lineTo(0, 0); ctx.closePath(); ctx.fill();
    ctx.fillStyle = 'rgba(206, 106, 106, .06)';
    ctx.beginPath();
    ctx.moveTo(size, 0); ctx.lineTo(size, size); ctx.lineTo(0, size); ctx.closePath(); ctx.fill();
    /* 河道：与中路垂直的那条对角线 */
    ctx.strokeStyle = 'rgba(96, 150, 176, .16)';
    ctx.lineWidth = size * 0.062;
    ctx.beginPath();
    ctx.moveTo(X(-MAP), Y(MAP));
    ctx.lineTo(X(MAP), Y(-MAP));
    ctx.stroke();
    /* 三路：对抗路＝左竖+上横，发育路＝下横+右竖，中路＝对角线（与并线口径同一组折线） */
    ctx.strokeStyle = 'rgba(226, 236, 241, .30)';
    ctx.lineWidth = Math.max(1.6, size * 0.009);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const path of Object.values(LANE_PATH)) {
      ctx.beginPath();
      path.forEach(([x, y], index) => (index ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.stroke();
    }
    /* 基地：圆＋「基地」小字，蓝左下、红右上 */
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `400 ${Math.max(7, size * 0.034)}px "Microsoft YaHei", "Microsoft YaHei UI", sans-serif`;
    for (const base of MAP_BASES) {
      const cx = X(base.x), cy = Y(base.y), r = size * 0.045;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${team[base.owner]}, .18)`;
      ctx.fill();
      ctx.strokeStyle = `rgba(${team[base.owner]}, .55)`;
      ctx.lineWidth = 1.3;
      ctx.stroke();
      ctx.fillStyle = `rgba(${team[base.owner]}, .95)`;
      ctx.fillText('基地', cx, cy + 0.5);
    }
    /* 红蓝 BUFF：填充色＝BUFF 种类，外圈＝归属方（蓝圈是蓝方野区、红圈是红方野区） */
    const r = Math.max(3.4, size * 0.021);
    ctx.font = `400 ${Math.max(7, size * 0.034)}px "Microsoft YaHei", "Microsoft YaHei UI", sans-serif`;
    for (const buff of MAP_BUFFS) {
      const cx = X(buff.x), cy = Y(buff.y);
      const color = buff.kind === 'red' ? '216, 96, 96' : '96, 148, 214';
      ctx.beginPath();
      ctx.arc(cx, cy, r + Math.max(1.2, size * 0.007), 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${team[buff.owner]}, .85)`;
      ctx.lineWidth = Math.max(1.2, size * 0.006);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${color}, .92)`;
      ctx.fill();
      ctx.fillStyle = 'rgba(250, 252, 253, .96)';
      ctx.fillText(buff.kind === 'red' ? '红' : '蓝', cx, cy + 0.5);
    }
    ctx.restore();
  }

  /* 停留热区：每格按停留时长分 5 档填色；对侧半区的格子加描边，
     这样「压过去多远、在对面待了多久」一眼能分出来。 */
  function drawHeatCells(ctx, data, max, rgb, size, cell) {
    const steps = 5;
    for (let i = 0; i < data.counts.length; i++) {
      const n = data.counts[i];
      if (!n) continue;
      const level = clamp(Math.ceil((n / max) * steps), 1, steps);
      const alpha = 0.2 + (level / steps) * 0.6;
      const gx = i % GRID;
      const gy = Math.floor(i / GRID);
      const px = gx * cell + 0.5, py = (GRID - 1 - gy) * cell + 0.5;
      ctx.fillStyle = `rgba(${rgb},${alpha.toFixed(2)})`;
      ctx.fillRect(px, py, cell - 1, cell - 1);
      if (data.enemyCells && data.enemyCells[i]) {
        ctx.strokeStyle = `rgba(${rgb},.95)`;
        ctx.lineWidth = 1;
        ctx.strokeRect(px + 0.25, py + 0.25, cell - 1.5, cell - 1.5);
      }
    }
  }

  /* 走位：把窗口里的采样点连成一条淡线，末端画当前所在位置。
     格子只说「待多久」，线才说「怎么走的、从哪绕的」。 */
  function drawHeatPath(ctx, player, rgb, size, cell, i0, i1) {
    if (!player || !player.points) return;
    const end = Math.min(i1, player.points.length - 1);
    const sx = (v) => (v + MAP) / (MAP * 2) * size;
    const sy = (v) => size - (v + MAP) / (MAP * 2) * size;
    let started = false;
    ctx.save();
    ctx.strokeStyle = `rgba(${rgb},.72)`;
    ctx.lineWidth = Math.max(1, cell * 0.16);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    let head = null;
    for (let i = Math.max(0, i0); i <= end; i++) {
      const point = player.points[i];
      if (!point || !player.mask || !player.mask[i]) { started = false; continue; }
      const [x, y] = point;
      if (x === 0 && y === 0) { started = false; continue; }
      if (!started) { ctx.moveTo(sx(x), sy(y)); started = true; } else ctx.lineTo(sx(x), sy(y));
      head = point;
    }
    ctx.stroke();
    /* 末端：当前时刻的位置，套一圈深色描边压住底下的格子 */
    const last = player.points[end];
    if (last && (!player.mask || player.mask[end]) && !(last[0] === 0 && last[1] === 0)) head = last;
    if (head) {
      ctx.beginPath();
      ctx.arc(sx(head[0]), sy(head[1]), Math.max(2.5, cell * 0.3), 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${rgb},1)`;
      ctx.fill();
      ctx.strokeStyle = 'rgba(8, 18, 26, .85)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.restore();
  }

  /* 时间轴读数：值缺失 / 非法时退回窗口末尾。
     以前这里直接送 Number(slider.value)，滑块值一旦是空串就变成 0，
     画面停在「0:00–0:00」——只画出出生点那一格（2026-11-17 修）。 */
  function heatAt(box) {
    const slider = box && box.querySelector('[data-heat-range]');
    const value = Number(slider && slider.value);
    if (Number.isFinite(value) && value >= 0) return value;
    return heatState ? heatState.duration : 0;
  }

  function paintHeat(t) {
    if (!heatState) return;
    const box = document.querySelector('[data-md-heat]');
    if (!box) return;
    const { step, duration, list } = heatState;
    const at = clamp(Number.isFinite(t) ? t : duration, 0, duration);
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
      const player = list.find((p) => `${p.camp}-${p.slot}` === canvas.dataset.heatCard);
      if (data) drawHeat(canvas, data, max, canvas.dataset.side, player, i0, i1);
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
    let at = heatAt(box);
    if (at >= heatState.duration - heatState.step) at = 0;
    heatTimer = setInterval(() => {
      if (!document.contains(box)) { stopHeat(); return; }
      at += heatState.step * 3 * heatSpeed;
      paintHeat(at);
      if (at >= heatState.duration) stopHeat();
    }, 200);
  }

  /* 翻译时间轴上的操作：±N 秒、跳到分期、跳到事件刻度。 */
  function heatSeek(delta) {
    const box = document.querySelector('[data-md-heat]');
    if (!box || !heatState) return;
    stopHeat();
    paintHeat(clamp(heatAt(box) + delta, 0, heatState.duration));
  }

  function heatJump(t) {
    const box = document.querySelector('[data-md-heat]');
    if (!box || !heatState) return;
    stopHeat();
    paintHeat(clamp(t, 0, heatState.duration));
  }

  function cycleHeatSpeed(button) {
    const index = HEAT_SPEEDS.indexOf(heatSpeed);
    heatSpeed = HEAT_SPEEDS[(index + 1) % HEAT_SPEEDS.length];
    const target = button || document.querySelector('[data-heat-speed]');
    if (target) {
      target.textContent = `${heatSpeed}×`;
      target.dataset.speed = String(heatSpeed);
    }
    /* 播放中改速度：重启计时器，让新速度立刻生效。 */
    const play = document.querySelector('[data-heat-play]');
    if (heatTimer && play) { stopHeat(); toggleHeat(play); }
  }

  /* 键盘：空格播放/暂停、← → 前后 10 秒、1/2/3 跳分期、S 切倍速。
     只在「地图」页签可见、且焦点不在输入框/下拉里时生效，避免抢打字。 */
  function heatKey(event) {
    if (!heatState) return;
    const pane = document.querySelector('[data-md-pane="map"]');
    if (!pane || pane.hidden) return;
    const tag = (event.target?.tagName || '').toLowerCase();
    if (['input', 'select', 'textarea'].includes(tag) || event.target?.isContentEditable) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.code === 'Space') {
      const play = document.querySelector('[data-heat-play]');
      if (play) { event.preventDefault(); toggleHeat(play); }
      return;
    }
    if (event.key === 'ArrowLeft') { event.preventDefault(); heatSeek(-10); return; }
    if (event.key === 'ArrowRight') { event.preventDefault(); heatSeek(10); return; }
    if (['1', '2', '3'].includes(event.key)) {
      const stops = [240, 600, heatState.duration];
      event.preventDefault();
      heatJump(stops[Number(event.key) - 1]);
      return;
    }
    if (event.key === 's' || event.key === 'S') { event.preventDefault(); cycleHeatSpeed(); }
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
        const speed = event.target.closest ? event.target.closest('[data-heat-speed]') : null;
        if (speed) { cycleHeatSpeed(speed); return; }
        const seek = event.target.closest ? event.target.closest('[data-heat-seek]') : null;
        if (seek) { heatJump(Number(seek.dataset.heatSeek)); return; }
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
        paintHeat(heatAt(box));
      });
      document.addEventListener('keydown', heatKey);
    }
    const box = document.querySelector('[data-md-heat]');
    if (!box || !heatState) return;
    box.querySelectorAll('[data-lane]').forEach((row) => { row.hidden = row.dataset.lane !== heatLane; });
    const pick = box.querySelector('[data-heat-lane]');
    if (pick) pick.value = heatLane;
    const speed = box.querySelector('[data-heat-speed]');
    if (speed) speed.textContent = `${heatSpeed}×`;
    paintHeat(heatAt(box));
  }

  /* ── 战斗拆成两块：团战（点地图看本波）与掉点（筛选/点选看单次） ──────
     原来团战和掉点挤在同一块板子里：地图混点、列表混队、结论也混。
     现在各自一块：
       团战 = 团战地图 + 本波伤害/承伤/控制 + 全队团战贡献 + 团战分析；
       掉点 = 掉点地图 + 掉点列表 + 选中掉点详情 + 掉点分析。
     两块共用官方回放的 battles/deaths 与逐秒位置，口径一致、互不遮挡。 */
  const PHASE_LABELS = ['0–4', '4–10', '10–结束'];
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
      <div class="md-ftl-head"><b>${glyph('matches', { label: '团战时间线', size: 18 })} 团战时间线</b><span>${fmt(fightCount)} 波</span></div>
      <div class="md-ftl">${fightsInfo.map((item) => `<button type="button" class="md-ftl-chip ${resultTone(item.result)}${item.index === fightDefaultIndex ? ' is-on' : ''}" data-fight-chip="${item.index}" title="${esc(`${time(item.t)} · ${item.ownParts.length}v${item.foeParts.length} · 击杀 ${item.ownKills}:${item.foeKills}`)}">
        <span>${time(item.t)}</span><i></i><em>${item.ownKills}:${item.foeKills}</em><small>${num(item.swing) ? diff(item.swing) : '—'}</small>
      </button>`).join('')}</div>
    </div>` : '';
    const mapReady = fightsInfo.some((x) => x.center);
    const fightBoard = !fightCount ? '' : `<div class="md-board md-board-fight" data-md-fights>
      <div class="md-board-head">
        <div class="md-board-title"><b>${glyph('heatmap', { label: '团战地图', size: 18 })} 团战地图</b><span>${fmt(fightCount)} 场团战</span></div>
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
        if (firstFights.length) parts.push(`我方首杀的 ${firstFights.length} 波 ${firstWins} 胜`);
        if (foeFirst.length) parts.push(`对方首杀 ${foeFirst.length} 波，我方 ${foeFirstWins} 胜`);
        if (fiveVfive.length) parts.push(`5v5 团战 ${fiveVfive.length} 波、赢下 ${fiveWins} 波`);
        else if (fullFights.length) parts.push(`大团（≥8 人）${fullFights.length} 波、赢下 ${fullFights.filter((x) => x.result === 'win').length} 波`);
        if (bestFight && num(bestFight.swing)) {
          parts.push(`最大单波经济差变化 ${diff(bestFight.swing)}（${time(bestFight.t)}）`);
        }
        if (num(avgTotal)) parts.push(`平均每波 ${avgTotal.toFixed(1)} 人参战`);
        if (num(avgEnd)) parts.push(`平均每波持续 ${avgEnd.toFixed(0)} 秒`);
      }
      return parts.join('；');
    })();
    const fullFights = fiveVfive.length ? fiveVfive : fightsInfo.filter((x) => x.total >= 8);
    const fullWins = fullFights.filter((x) => x.result === 'win').length;
    const fightTiles = [
      ['团战', `${fightCount}<small>波</small>`, `${fightWins} 胜 · ${fightLosses} 负${fightDraws ? ` · ${fightDraws} 平` : ''}`],
      ['首杀团战', `${firstWins}<i>/</i>${firstFights.length || 0}`, firstFights.length ? `首杀后赢下` : '没有我方首杀记录'],
      [fiveVfive.length ? '5v5 团战' : '大团（≥8 人）', `${fullWins}<i>/</i>${fullFights.length || 0}`,
        fullFights.length ? (fiveVfive.length ? '满编团战胜率' : '大团团战胜率') : '本局没有大团'],
      ['最大单波', `${bestFight && num(bestFight.swing) ? diff(bestFight.swing) : '—'}`, bestFight ? `${time(bestFight.t)} · ${resultText(bestFight.result)}` : '没有经济差采样'],
    ];
    const fightSizes = [
      ...sizeBuckets.filter((b) => b.n).map((b) => `<span class="md-fight-size"><b>${b.label}</b><i>${b.n} 波</i><em>${b.wins} 胜</em></span>`),
      ...phaseFights.filter((b) => b.n).map((b) => `<span class="md-fight-size is-phase"><b>${b.label}</b><i>${b.n} 波</i><em>${b.wins} 胜</em></span>`),
    ].join('');
    const fightKeys = keyFights.length ? `<div class="md-fight-keys"><b>${glyph('victory', { label: '关键团战', size: 18 })} 关键团战</b>${keyFights.map((item) => `<button type="button" data-fight-jump="${item.index}">
      ${glyph('matches', { size: 16 })} <span>${time(item.t)}</span>
      <i class="${resultTone(item.result)}">${resultText(item.result)}</i>
      <em>${num(item.swing) ? diff(item.swing) : '—'}</em>
    </button>`).join('')}</div>` : '';
    const fightAnalysis = `<div class="md-viz-analysis md-bprev ${fightBadge[1]}">
      <div class="md-bprev-head"><b>团战分析</b><span class="md-bprev-badge ${fightBadge[1]}">${fightBadge[0]}</span></div>
      <p class="md-bprev-lede">${fightLede || '这局回放没有团战账本'}。</p>
      <div class="md-bprev-stats">${fightTiles.map(([label, value, note]) => `<div class="md-bprev-stat"><span class="md-bprev-stat-label">${label}</span><span class="md-bprev-stat-value">${value}</span><span class="md-bprev-stat-note">${note}</span></div>`).join('')}</div>
      ${fightSizes ? `<div class="md-fight-splits">${fightSizes}</div>` : ''}
      ${fightKeys}
      <p class="md-bprev-thin">口径：团战点来自官方回放 battles，点大小＝参战人数，颜色＝该波击杀差；胜负按该波击杀数，经济差取开团前 30 秒到结束后 30 秒的变化（本队视角，未经自然增长或其他事件校正）。</p>
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
        <span class="md-dr-warn">${glyph('warning', { size: 16 })}</span>
        <span class="md-dr-time">${time(row.d.t)}</span>
        <span class="md-dr-side ${own ? 'own' : 'foe'}">${own ? '我方' : '对方'}</span>
        <span class="md-dr-hero">${esc(row.d.hero || '—')}</span>
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
        <div class="md-board-title"><b>${glyph('heatmap', { label: '掉点地图', size: 18 })} 掉点地图</b><span>${fmt(rows.length)} 次阵亡 · 我方 ${fmt(ownDeaths.length)} / 对手 ${fmt(foeDeaths.length)}</span></div>
        ${picker}
      </div>
      <div class="md-board-body">
        <div class="md-board-map">
          ${rows.some((row) => row.hasPos) ? `<svg viewBox="0 0 ${SIZE} ${SIZE}" role="img" aria-label="掉点位置分布">${grid}${mapBase}${deathLeaders}${deathDots}${deathHalo}</svg>`
            : '<div class="md-map-empty">这局没有逐秒位置，掉点无法落图；右侧列表与详情仍可用。</div>'}
          <div class="md-death-tip" data-death-tip hidden></div>
          <p class="md-board-legend"><span class="own"><i class="death"></i>我方阵亡</span><span class="foe"><i class="death"></i>对手阵亡</span><span><i class="size"></i>点越大，经济影响越大</span>${rows.filter((row) => row.hasPos).length < rows.length ? `<span>仅 ${rows.filter((row) => row.hasPos).length}/${rows.length} 次有位置</span>` : ''}</p>
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

  /* ── 入侵时长：半区（>50%，即入侵）/ 深区（>66%）双口径，共用一张表 ──
     2026-11-20 赛训组第二轮：
     ① 数字回归墨色，整张表只留「差距最大」那一行用色；
     ② 口径切换真的能点（原来只有按钮、没有事件）；
     ③ 0–4 / 4–10 / 10+ 并进表头，和下面的列严格对齐，不再单独浮一行。 */
  /* 中文时长：≥60 秒「X分XX秒」，不足 60 秒「N秒」（赛训组口径，不用 xx:xx） */
  const durText = (sec) => {
    const s = Math.round(sec);
    return s < 60 ? `${s}秒` : `${Math.floor(s / 60)}分${String(s % 60).padStart(2, '0')}秒`;
  };

  function duel(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
    const wins = phaseWindows(duration);
    const step = positions.step || 2;
    const laneOfPlayer = (p) => (LANES.includes(p.position) ? p.position : '游走');
    const foeCamp = ownCamp === 'blue' ? 'red' : 'blue';

    /* 逐人逐段秒数：进入对侧半区 / 深区的时长，两种口径各采一次 */
    const collect = (threshold) => {
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
      return index;
    };

    const table = (mode) => {
      const index = collect(mode === 'deep' ? DEEP : HALF);
      const ownLabel = mode === 'deep' ? '本队 · 推进到对侧深区' : '本队 · 进入对侧半区';
      const foeLabel = mode === 'deep' ? '对手 · 推进到本队深区' : '对手 · 进入本队半区';
      const rows = LANES.map((lane) => {
        const ownEntry = index.get(`${ownCamp}-${lane}`) || null;
        const foeEntry = index.get(`${foeCamp}-${lane}`) || null;
        const secs = (entry) => (entry ? entry.seconds.slice() : [null, null, null]);
        const total = (list) => list.reduce((sum, v) => sum + (num(v) ? v : 0), 0);
        const ownSecs = secs(ownEntry);
        const foeSecs = secs(foeEntry);
        /* 一边没有这名选手的位置（分路标错 / 缺位置）时不给差距：
           拿 0 当对手时长会把「没数据」说成「本队多 10 分钟」。 */
        const comparable = ownSecs.some(num) && foeSecs.some(num);
        return { lane, ownSecs, foeSecs, own: total(ownSecs), foe: total(foeSecs), comparable };
      });
      /* 三种分期共用一把尺子：条长就是绝对秒数，不按分期各自归一 */
      const peak = Math.max(1, ...rows.flatMap((r) => r.ownSecs.concat(r.foeSecs)).filter(num));
      const paired = rows.filter((r) => r.comparable);
      /* 合计只算两边都有位置的「可比」分路：缺一边的路不能拿 0 当对手时长，
         否则「对手根本没被记录」会被说成「本队多 10 分钟」。
         五路全缺时也不能回退到 rows —— 那样算出的合计会和下面
         「缺位置不计入合计」的说明自相矛盾，直接给「无法合计」。 */
      const noPair = !paired.length;
      const sumRows = paired;
      const ownTot = sumRows.reduce((sum, r) => sum + r.own, 0);
      const foeTot = sumRows.reduce((sum, r) => sum + r.foe, 0);
      const gap = foeTot - ownTot;
      /* 表里只强调一行：合计差距方向上的最大差 */
      const dir = gap >= 0 ? 1 : -1;
      const worst = paired.length
        ? paired.reduce((pick, r) => ((r.foe - r.own) * dir > (pick.foe - pick.own) * dir ? r : pick), paired[0])
        : null;

      const cell = (sec) => {
        if (!num(sec)) return '<span class="iv-cell is-empty"><b>—</b></span>';
        if (!sec) return '<span class="iv-cell is-zero"><b>0</b></span>';
        const width = Math.max(4, Math.round(sec / peak * 100));
        return `<span class="iv-cell"><b>${durText(sec)}</b>`
          + `<i class="iv-meter"><em style="width:${width}%"></em></i></span>`;
      };
      const body = rows.map((r) => {
        const d = r.foe - r.own;
        const diffText = !r.comparable ? '—' : d > 0 ? `对手多 ${durText(d)}` : d < 0 ? `本队多 ${durText(-d)}` : '持平';
        const mark = r.comparable && r === worst && d !== 0 ? (d > 0 ? ' is-worst' : ' is-best') : '';
        const naCls = r.comparable ? '' : ' is-na';
        return `<div class="iv-row">
          <span class="iv-lane">${r.lane}</span>
          <div class="iv-cells own">${r.ownSecs.map(cell).join('')}</div>
          <div class="iv-cells foe">${r.foeSecs.map(cell).join('')}</div>
          <span class="iv-diff${mark}${naCls}">${diffText}</span>
        </div>`;
      }).join('');
      const head = `<div class="iv-head">
        <span class="iv-h-lane">分路</span>
        <div class="iv-h-group"><b><i class="iv-dot own"></i>${ownLabel}</b>
          <div class="iv-h-phases"><i>0–4 分钟</i><i>4–10 分钟</i><i>10 分钟后</i></div></div>
        <div class="iv-h-group"><b><i class="iv-dot foe"></i>${foeLabel}</b>
          <div class="iv-h-phases"><i>0–4 分钟</i><i>4–10 分钟</i><i>10 分钟后</i></div></div>
        <span class="iv-h-diff">差距</span>
      </div>`;
      const ratio = ownTot && foeTot ? (foeTot / ownTot) : null;
      const mid = noPair
        ? '<span>无法合计</span><b>—</b>'
        : gap > 0
          ? `<span>对手多</span><b class="is-behind">+${durText(gap)}</b>${ratio ? `<small>约 ${ratio.toFixed(1)} 倍</small>` : ''}`
          : gap < 0
            ? `<span>本队多</span><b class="is-ahead">+${durText(-gap)}</b>${ratio ? `<small>约 ${(1 / ratio).toFixed(1)} 倍</small>` : ''}`
            : '<span>两边合计</span><b>持平</b>';
      const sum = `<div class="iv-sum">
        <div class="iv-sum-cell"><span><i class="iv-dot own"></i>本队</span><b>${noPair ? '—' : durText(ownTot)}</b></div>
        <div class="iv-sum-cell mid">${mid}</div>
        <div class="iv-sum-cell foe"><span>对手<i class="iv-dot foe"></i></span><b>${noPair ? '—' : durText(foeTot)}</b></div>
      </div>`;
      const ahead = paired.filter((r) => r.foe > r.own).length;
      const behind = paired.filter((r) => r.own > r.foe).length;
      const lead = (r) => durText(Math.abs(r.foe - r.own));
      const take = (() => {
        if (noPair) return '没有可对比的分路，本局不给合计差距';
        if (!gap) return '两队入侵时长合计持平';
        if (!worst) return `合计${gap > 0 ? '对手' : '本队'}多 ${durText(Math.abs(gap))}`;
        if (gap > 0 && ahead) return `${ahead} 条分路对手更久，<b>${worst.lane}差最多 ${lead(worst)}</b>`;
        if (gap < 0 && behind) return `${behind} 条分路本队更久，<b>${worst.lane}领先最多 ${lead(worst)}</b>`;
        return `合计${gap > 0 ? '对手' : '本队'}多 ${durText(Math.abs(gap))}`;
      })();
      /* 有一边没这名选手的位置：不编差距，写清哪一路缺 */
      const missing = rows.filter((r) => !r.comparable)
        .map((r) => `${r.lane}${r.ownSecs.some(num) ? '对手' : '本队'}无位置`);
      const caveat = missing.length ? `<span class="iv-note-caveat">（${missing.join('、')}，不计入合计）</span>` : '';
      return `${sum}<div class="iv-table">${head}${body}</div><p class="iv-note">${take}${caveat}</p>`;
    };

    const view = (mode, body) => `<div class="iv-view" id="iv-view-${mode}" data-iv-view="${mode}"
      role="tabpanel" aria-labelledby="iv-tab-${mode}"${duelMode === mode ? '' : ' hidden'}>${body}</div>`;
    const tab = (mode, text) => `<button type="button" role="tab" id="iv-tab-${mode}"
      class="iv-tab${duelMode === mode ? ' is-on' : ''}" aria-selected="${duelMode === mode}"
      aria-controls="iv-view-${mode}" tabindex="${duelMode === mode ? '0' : '-1'}"
      data-iv-mode-btn="${mode}">${glyph(mode === 'half' ? 'shield' : 'heatmap', { size: 18 })} ${text}</button>`;
    /* 半区优先：初始口径 half（切过深区就尊重上次选择） */
    return `<div class="md-invasion" data-md-duel>
      <div class="iv-bar"><div class="iv-tabs" role="tablist" aria-label="入侵口径">${tab('half', '半区 &gt;50%')}${tab('deep', '深区 &gt;66%')}</div></div>
      ${view('half', table('half'))}
      ${view('deep', table('deep'))}
    </div>`;
  }

  /* 口径切换：两份表都已渲染，点一下只切 hidden（原来只有按钮、没有事件） */
  function setDuelMode(mode) {
    duelMode = mode === 'deep' ? 'deep' : 'half';
    const box = document.querySelector('[data-md-duel]');
    if (!box) return;
    box.querySelectorAll('[data-iv-mode-btn]').forEach((btn) => {
      const on = btn.dataset.ivModeBtn === duelMode;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-selected', String(on));
      btn.tabIndex = on ? 0 : -1;
    });
    box.querySelectorAll('[data-iv-view]').forEach((view) => {
      view.hidden = view.dataset.ivView !== duelMode;
    });
  }

  let duelBound = false;
  function bindDuel(root) {
    if (!duelBound) {
      duelBound = true;
      root.addEventListener('click', (event) => {
        const hit = event.target.closest ? event.target.closest('[data-iv-mode-btn]') : null;
        if (!hit) return;
        setDuelMode(hit.dataset.ivModeBtn);
      });
      /* 方向键在半区/深区之间移动焦点并切换，tab 的相关属性由 setDuelMode 统一同步。 */
      root.addEventListener('keydown', (event) => {
        const hit = event.target.closest?.('[data-iv-mode-btn]');
        if (!hit || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
        const tabs = [...(hit.closest('.iv-tabs')?.querySelectorAll('[data-iv-mode-btn]') || [])];
        if (tabs.length < 2) return;
        const at = tabs.indexOf(hit);
        const next = tabs[(at + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        event.preventDefault();
        next.focus();
        setDuelMode(next.dataset.ivModeBtn);
      });
    }
    setDuelMode(duelMode);
  }

  /* ── 交互：比赛脉搏指针 ─────────────────────────────────────────── */
  /* 增量替换会反复调用 bindPulse（异步回放到达时）：「点外面收起浮层」
     只在 document 上挂一次，各次的 box/card 只登记进表；旧 DOM 脱离文档后
     顺手清掉，不再每次重渲染都留一个捕获旧节点的闭包。 */
  const pulseCards = new Set();
  let pulseDismissBound = false;
  function bindPulse(root, series, events, ownCamp) {
    const box = root.querySelector('[data-pulse]');
    if (!box || !series.length) return;
    /* 图表 SVG 在读数条下面的 .mp-chart 里，从脉搏容器取 */
    const svg = box.parentElement?.querySelector('.mp-svg') || box.querySelector('.mp-svg');
    const cursor = svg?.querySelector('.mp-cursor');
    const line = cursor?.querySelector('line');
    const dot = cursor?.querySelector('circle');
    const clock = box.querySelector('[data-pulse-clock]');
    const ownOut = box.querySelector('[data-pulse-blue]');
    const foeOut = box.querySelector('[data-pulse-red]');
    const diffOut = box.querySelector('[data-pulse-diff]');
    const atOut = box.querySelector('[data-pulse-at]');
    if (!svg || !cursor) return;

    const t0 = Number(box.dataset.t0), t1 = Number(box.dataset.t1);
    /* 与 pulse() 的矮画布一致：881 × 200，x 轴 78→838，零线 102，满量程 58px */
    const W = 881, L = 78, R = 838, ZERO = 102, UNIT = 58;
    const absMax = Math.max(1000, ...series.map((p) => Math.abs(p.diff)));
    const limit = Math.max(10000, Math.ceil(absMax / 5000) * 5000);
    const nearest = (t) => series.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a, series[0]);

    const move = (event) => {
      const rect = svg.getBoundingClientRect();
      const px = clamp(event.clientX - rect.left, 0, rect.width);
      const vx = px / rect.width * W;                 // 换算回画布坐标
      const t = t0 + (vx - L) / (R - L) * (t1 - t0);
      const point = nearest(clamp(t, t0, t1));
      const x = L + (point.t - series[0].t) / Math.max(1, series.at(-1).t - series[0].t) * (R - L);
      const y = ZERO - point.diff / limit * UNIT;
      cursor.removeAttribute('hidden');
      line.setAttribute('x1', x.toFixed(1)); line.setAttribute('x2', x.toFixed(1));
      line.setAttribute('y1', (ZERO - UNIT).toFixed(1)); line.setAttribute('y2', (ZERO + UNIT).toFixed(1));
      dot.setAttribute('cx', x.toFixed(1)); dot.setAttribute('cy', y.toFixed(1));
      clock.textContent = time(point.t);
      ownOut.textContent = fmt(point.own);
      foeOut.textContent = fmt(point.foe);
      diffOut.textContent = diff(point.diff);
      const near = (events || []).filter((e) => num(e.t) && Math.abs(e.t - point.t) <= 45)
        .sort((a, b) => Math.abs(a.t - point.t) - Math.abs(b.t - point.t))[0];
      if (atOut) atOut.textContent = near
        ? `${time(near.t)} ${near.kind === 'structure' ? '建筑' : near.kind === 'resource' ? '资源' : '击杀'} · ${near.killer || near.killerHero || ''}`
        : '该时刻附近没有记录事件';
    };
    const card = box.querySelector('[data-pulse-card]');
    if (card) {
      pulseCards.add({ box, card });
      if (!pulseDismissBound) {
        pulseDismissBound = true;
        document.addEventListener('pointerdown', (event) => {
          for (const entry of [...pulseCards]) {
            if (!entry.box.isConnected) { pulseCards.delete(entry); continue; }
            if (!entry.box.contains(event.target) && entry.card) entry.card.hidden = true;
          }
        });
      }
    }
    const markList = (events || []).filter((e) => num(e.t) && (e.kind === 'resource' || e.kind === 'structure'));
    const showCard = (index, event) => {
      const item = markList[Number(index)];
      if (!card || !item) return;
      const side = item.killerCamp === ownCamp ? 'own' : 'foe';
      const sideText = item.killerCamp ? (side === 'own' ? '我方' : '对手') : '';
      card.innerHTML = `<b>${time(item.t)} · ${esc(item.label || item.name || '')}</b>
        <span class="mp-card-side ${side}">${sideText}${item.killerHero || item.killer ? ' · ' + esc(item.killerHero || item.killer) : ''}</span>
        <small>${item.kind === 'structure' ? '建筑' : '资源'} · 官方回放事件</small>`;
      /* 浮卡以整张脉搏卡为定位父级；2026-11-22 起脉搏已移出结论卡。 */
      const host = (box.closest('.ms-pulse-card, #match-verdict') || box).getBoundingClientRect();
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
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', () => { cursor.setAttribute('hidden', ''); });
  }

  /* ── 事件时间轴（2026-11-19）：资源与推塔水晶两条横向时间轴 ─────────
     事件以竖线插入时间带，外端挂官方图标胶囊；悬停/聚焦弹出卡片显示
     时间、事件、归属与参与者头像。密集事件上下错层避免重叠。 */
  const RES_ICON = {
    '暴君': 'kpl-svg/charts/objective-icon-tyrant.svg', '主宰': 'kpl-svg/charts/objective-icon-overlord.svg',
    /* 本地 SVG 资产比旧 PNG 更清楚，21px 胶囊里也能看清龙形；水晶暂无独立图标，沿用塔。 */
    '暗影暴君': 'kpl-svg/charts/objective-icon-shadow-tyrant.svg', '暗影主宰': 'kpl-svg/charts/objective-icon-shadow-overlord.svg',
    '风暴龙王': 'kpl-svg/charts/objective-icon-storm-dragon.svg', '塔': 'kpl-svg/charts/objective-icon-tower.svg', '水晶': 'kpl-svg/charts/objective-icon-tower.svg'
  };
  const iconUrl = (name, foe = false) => {
    /* 塔/水晶按阵营取色：我方蓝塔、对方红塔，外圈颜色与图标本体保持一致。 */
    const foeIcon = foe && (name === '塔' || name === '水晶');
    const file = foeIcon ? 'kpl-svg/charts/objective-icon-tower-red.svg'
      : (RES_ICON[name] || 'kpl-svg/charts/objective-icon-tower.svg');
    return `static/${file}`;
  };

  function timeline(events, ownCamp, duration, players) {
    const list = (events || []).filter((e) => num(e.t) && (e.kind === 'resource' || e.kind === 'structure') && e.name !== '野怪');
    if (!list.length) return '';
    const end = Math.max(Number(duration) || 0, ...list.map((e) => Number(e.t) || 0)) || 1;

    const iconOf = (e) => {
      if (e.kind === 'structure') return /水晶/.test(e.name || '') ? '水晶' : '塔';
      const n = e.name || '';
      if (/风暴|龙王/.test(n)) return '风暴龙王';
      if (/暗影暴君/.test(n)) return '暗影暴君';
      if (/暗影主宰/.test(n)) return '暗影主宰';
      if (/主宰/.test(n)) return '主宰';
      if (/暴君/.test(n)) return '暴君';
      return '暴君';
    };
    const kindText = (e) => e.label || (e.kind === 'structure'
      ? (/水晶/.test(e.name || '') ? '水晶' : '防御塔')
      : (e.name || iconOf(e)));

    const wins = phaseWindows(end);
    const PHASE_NAMES = ['对线期', '发育期', '后期'];
    const segs = wins.map((win, i) => {
      const width = Math.max(0, Math.min(100, (win.end - win.start) / end * 100));
      return `<div class="tl-seg s${i + 1}" style="width:${width.toFixed(2)}%">${PHASE_NAMES[i] || ''}<em>${esc(win.label)}</em></div>`;
    }).join('');
    const tickTimes = (() => {
      const base = end > 300
        ? [0, 180, 360, 540, 720].filter((t) => t < end - 20)
        : [0, end / 3, end * 2 / 3];
      return [...new Set([...base.map((t) => Math.round(t)), Math.round(end)])];
    })();

    const axis = (rows, isLane) => {
      const sorted = rows.slice().sort((a, b) => a.t - b.t);
      const ownN = sorted.filter((e) => e.killerCamp === ownCamp).length;
      const foeN = sorted.filter((e) => e.killerCamp && e.killerCamp !== ownCamp).length;
      const ticks = tickTimes.map((t) => `<span style="left:${(t / end * 100).toFixed(2)}%">${time(t)}</span>`).join('');
      const nodes = sorted.map((e) => {
        const pct = clamp((Number(e.t) || 0) / end * 100, 0, 100);
        const own = e.killerCamp === ownCamp;
        const camp = own ? 'own' : 'foe';
        const parts = (e.participants || []).filter((p) => p && p.hero);
        const who = parts.slice(0, 8).map((p) => `<span class="tl-who">${portrait(p.hero, 'tl-face')}<em>${esc(p.hero)}</em></span>`).join('');
        const icon = iconOf(e);
        return `<span class="tl-ev ${camp}" style="left:${pct.toFixed(2)}%" data-pct="${pct.toFixed(3)}"
          tabindex="0" data-time="${time(e.t)}" data-icon="${icon}" data-kind="${esc(kindText(e))}"
          data-result="${own ? '我方拿下' : '对手拿下'}"
          data-note="${parts.length ? `${parts.length} 人参与` : '回放未记录参与者'}"
          data-who="${encodeURIComponent(who)}">
          <span class="tl-cap"><span class="tl-ic"><img src="${iconUrl(icon, !own)}" alt=""></span><span class="tl-time">${time(e.t)}</span></span>
          <span class="tl-stem"></span></span>`;
      }).join('');
      return `<div class="tl-axis ${isLane ? 'tl-lane' : 'tl-res'}">
        <div class="tl-head"><b>${isLane ? '推塔与水晶' : '关键资源'}</b><span><i class="own">${ownN}</i> 我方 · <i class="foe">${foeN}</i> 对手 · 共 ${sorted.length} 事件</span></div>
        <div class="tl-ticks">${ticks}</div>
        <div class="tl-track"><div class="tl-band">${segs}</div>${nodes}</div>
      </div>`;
    };

    const legendNames = ['暴君', '主宰', '暗影暴君', '暗影主宰', '风暴龙王'];
    const legend = `<div class="tl-legend">
      ${legendNames.map((n) => {
        const count = list.filter((e) => e.kind === 'resource' && iconOf(e) === n).length;
        return `<span class="${count ? '' : 'unused'}"><img src="${iconUrl(n)}" alt=""><em>${n}</em><b class="${count ? '' : 'off'}">${count || '本局 0'}</b></span>`;
      }).join('')}</div>`;

    return `<div class="md-timeline" data-md-timeline>
      ${legend}
      ${axis(list.filter((e) => e.kind === 'resource'), false)}
      ${axis(list.filter((e) => e.kind === 'structure'), true)}
      <div class="tl-pop" data-tl-pop hidden></div>
    </div>`;
  }

  /* 时间轴事件分层：按实际像素宽度做区间排层（不靠固定百分比猜），
     6 条泳道 u0/d0/u1/d1/u2/d2，密集簇（14:14/14:25、15:00/15:08/15:11）
     自动上下错开；页签从隐藏变可见时 ResizeObserver 会重排。 */
  function bindTimeline(root) {
    const box = root && root.querySelector('[data-md-timeline]');
    if (!box || box.dataset.tlBound) return;
    box.dataset.tlBound = '1';
    const pop = box.querySelector('[data-tl-pop]');
    if (!pop) return;
    const LANES = ['u0', 'd0', 'u1', 'd1', 'u2', 'd2'];
    const layoutAxis = (axis) => {
      const track = axis.querySelector('.tl-track');
      if (!track) return;
      const width = track.clientWidth;
      if (!width) return;
      const nodes = [...track.querySelectorAll('.tl-ev')]
        .sort((a, b) => Number(a.dataset.pct) - Number(b.dataset.pct));
      const lanes = new Map(LANES.map((lane) => [lane, []]));
      nodes.forEach((node, index) => {
        const x = Number(node.dataset.pct) / 100 * width;
        const cap = node.querySelector('.tl-cap');
        const w = Math.max(56, cap ? cap.offsetWidth : 84);
        const order = index % 2 ? ['d0', 'u0', 'd1', 'u1', 'd2', 'u2'] : LANES;
        let best = null, bestDist = -1;
        for (const lane of order) {
          const used = lanes.get(lane);
          const conflict = used.some((o) => Math.abs(o.x - x) < (o.w + w) / 2 + 4);
          if (!conflict) { best = lane; break; }
          const dist = used.reduce((min, o) => Math.min(min, Math.abs(o.x - x)), Infinity);
          if (dist > bestDist) { bestDist = dist; best = lane; }
        }
        const lane = best || 'u0';
        node.classList.remove(...LANES);
        node.classList.add(lane);
        lanes.get(lane).push({ x, w });
      });
    };
    const layoutAll = () => box.querySelectorAll('.tl-axis').forEach(layoutAxis);
    layoutAll();
    if (window.ResizeObserver && !box._tlRO) {
      box._tlRO = new ResizeObserver(() => layoutAll());
      box.querySelectorAll('.tl-track').forEach((track) => box._tlRO.observe(track));
    }

    const place = (x, y) => {
      pop.hidden = false;
      const w = pop.offsetWidth || 248;
      const h = pop.offsetHeight || 180;
      let left = x + 14;
      let top = y - 24;
      if (left + w > window.innerWidth - 12) left = x - w - 14;
      if (left < 12) left = 12;
      if (top + h > window.innerHeight - 12) top = window.innerHeight - h - 12;
      if (top < 12) top = 12;
      pop.style.left = `${left}px`;
      pop.style.top = `${top}px`;
    };
    const fill = (el) => {
      let who = '';
      try { who = decodeURIComponent(el.dataset.who || ''); } catch { who = ''; }
      const own = el.classList.contains('own');
      pop.className = 'tl-pop on ' + (own ? 'own' : 'foe');
      pop.innerHTML = `<div class="tl-pop-head"><img src="${iconUrl(el.dataset.icon, el.classList.contains('foe'))}" alt="">
          <div><span>${esc(el.dataset.time || '')}</span><b>${esc(el.dataset.kind || '')}</b></div></div>
        <div class="tl-pop-side ${own ? 'own' : 'foe'}">${esc(el.dataset.result || '')}</div>
        <div class="tl-pop-note">${esc(el.dataset.note || '')}</div>
        ${who ? `<div class="tl-pop-parts">${who}</div>` : ''}`;
    };
    const showAt = (el, x, y) => {
      fill(el);
      place(x, y);
    };
    const hide = () => { pop.hidden = true; };
    box.querySelectorAll('.tl-ev').forEach((el) => {
      el.addEventListener('mouseenter', (event) => showAt(el, event.clientX, event.clientY));
      el.addEventListener('mousemove', (event) => showAt(el, event.clientX, event.clientY));
      el.addEventListener('mouseleave', hide);
      el.addEventListener('focus', () => {
        const r = el.getBoundingClientRect();
        showAt(el, r.right, r.top);
      });
      el.addEventListener('blur', hide);
    });
    box.addEventListener('mouseleave', hide);
  }

  /* 横滑卡片：卡片被容器右缘齐边切断时，给「还能往右滑」一个可见提示。
     只在右侧确实还有内容时显示渐隐 + 小箭头；滑到底自动消失，
     不改变卡片尺寸、排序、滚动口径。 */
  const hscrollRO = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver((entries) => entries.forEach((e) => syncHScrollHint(e.target))) : null;
  function syncHScrollHint(el) {
    const more = el.scrollWidth - el.clientWidth - el.scrollLeft > 8;
    el.closest('.md-hscroll')?.classList.toggle('can-scroll-right', more);
  }
  function bindHScrollHints(root) {
    (root || document).querySelectorAll('.md-hscroll').forEach((wrap) => {
      if (wrap.dataset.hsBound) return;
      const track = wrap.querySelector('.md-mu-grid, .md-ct-list');
      if (!track) return;
      wrap.dataset.hsBound = '1';
      track.addEventListener('scroll', () => syncHScrollHint(track), { passive: true });
      hscrollRO?.observe(track);
      syncHScrollHint(track);
      /* 鼠标可直接按住卡片拖动；原生横滑仍保留触摸惯性与键盘方向键。 */
      if (!track.hasAttribute('tabindex')) {
        track.tabIndex = 0;
        track.setAttribute('role', 'region');
        track.setAttribute('aria-label', '可横向滑动的卡片列表');
      }
      let dragging = false, startX = 0, startLeft = 0, moved = false;
      track.addEventListener('pointerdown', (ev) => {
        if (ev.pointerType !== 'mouse' || ev.button !== 0) return;
        if (ev.target.closest('a, button, input, select, textarea')) return;
        dragging = true; moved = false;
        startX = ev.clientX; startLeft = track.scrollLeft;
        track.setPointerCapture?.(ev.pointerId);
        track.classList.add('is-dragging');
      });
      track.addEventListener('pointermove', (ev) => {
        if (!dragging) return;
        const dx = ev.clientX - startX;
        if (Math.abs(dx) > 3) moved = true;
        track.scrollLeft = startLeft - dx;
      });
      const stop = (ev) => {
        if (!dragging) return;
        dragging = false;
        track.releasePointerCapture?.(ev.pointerId);
        track.classList.remove('is-dragging');
        if (moved) {
          track.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); }, { capture: true, once: true });
        }
      };
      track.addEventListener('pointerup', stop);
      track.addEventListener('pointercancel', stop);
    });
  }

  return { totals, pulse, phaseTable, panel, laneViews, heat, duel, jungleJoin, cohesion, battle, timeline, bindPulse, bindPanel, bindHeat, bindBattle, bindTimeline, bindDuel, bindHScrollHints };
}
