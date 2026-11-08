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

export function createMatchDeep(h) {
  const { esc, fmt, pct, diff, time, portrait } = h;

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

    const bands = duration > 0 ? ['对线期', '转线期', '决胜期'].map((name, i) => {
      const a = Math.max(duration * i / 3, t0), b = Math.min(duration * (i + 1) / 3, t1);
      if (b <= a) return '';
      const xa = x(a), xb = x(b);
      return `<rect x="${xa.toFixed(1)}" y="${TOP}" width="${(xb - xa).toFixed(1)}" height="${BOT - TOP}" class="mp-band${i % 2 ? ' alt' : ''}"/>
        <text x="${((xa + xb) / 2).toFixed(1)}" y="${TOP - 9}" text-anchor="middle" class="mp-band-label">${name}</text>`;
    }).join('') : '';

    const zero = low < 0 ? `<line x1="${L}" x2="${R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="mp-zero"/>` : '';

    /* 事件标记：资源菱形、建筑方块，按阵营着色，落在曲线同一高度 */
    const diffAt = (t) => {
      let best = series[0];
      for (const p of series) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
      return best.diff;
    };
    const marks = (events || []).filter((e) => num(e.t) && e.t >= t0 && e.t <= t1 && (e.kind === 'resource' || e.kind === 'structure'))
      .map((e) => {
        const c = e.killerCamp === camps.own ? 'own' : 'foe';
        const cy = y(diffAt(e.t)) - 13;
        const shape = e.kind === 'structure'
          ? `<rect x="${(x(e.t) - 4).toFixed(1)}" y="${(cy - 4).toFixed(1)}" width="8" height="8" rx="1.5"/>`
          : `<path d="M${x(e.t).toFixed(1)},${(cy - 5).toFixed(1)} L${(x(e.t) + 5).toFixed(1)},${cy.toFixed(1)} L${x(e.t).toFixed(1)},${(cy + 5).toFixed(1)} L${(x(e.t) - 5).toFixed(1)},${cy.toFixed(1)} Z"/>`;
        return `<g class="mp-mark ${c}"><title>${esc(time(e.t) + ' · ' + (e.kind === 'structure' ? '建筑' : '资源') + ' · ' + (e.killer || ''))}</title>${shape}</g>`;
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
        ${marks}
        <circle cx="${x(tip.t).toFixed(1)}" cy="${y(tip.diff).toFixed(1)}" r="4.5" class="mp-end"/>
        <g class="mp-cursor" hidden>
          <line x1="0" x2="0" y1="${TOP}" y2="${BOT}"/>
          <circle cx="0" cy="0" r="5"/>
        </g>
        <rect class="mp-hit" x="${L}" y="${TOP}" width="${R - L}" height="${BOT - TOP}"/>
      </svg>
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
  let heatMode = 'ten';
  let heatState = null;
  let heatBound = false;
  let heatTimer = null;
  const HEAT_WINDOW = 90; // 热区时间窗（秒）

  /* 入侵：以对侧半区（推进进度 > 50%）为准；连续 2 个采样（≈4 秒）才算一次。
     静止 ≥12 秒的样本（阵亡停留等）既不计入分子也不计入分母。 */
  function invasionStats(positions, players, duration) {
    const step = positions.step || 2;
    const meta = new Map(players.map((p) => [`${p.camp}-${p.slot}`, p]));
    const phaseOf = (t) => (duration > 0 ? Math.min(2, Math.floor(t / (duration / 3))) : 0);
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
    const labels = metrics.map((m, i) => {
      const [x, y] = pt(i, R + 12);
      return `<text class="md-fl-label" x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="middle">${m.label}</text>`;
    }).join('');
    const name = `${(a && (a.label || a.hero)) || '本队'} 与 ${(b && (b.label || b.hero)) || '对手'}`;
    return `<svg class="md-fl" viewBox="0 0 ${size} ${size}" role="img" aria-label="对位雷达：${esc(name)}">${[0.34, 0.67, 1].map(ring).join('')}${spokes}${area(a, 'own')}${area(b, 'foe')}${labels}</svg>`;
  }

  function duelView(players, ownCamp, metrics) {
    const pick = (camp) => {
      const map = new Map();
      for (const p of players) if (p.camp === camp) map.set(laneOf(p), p);
      return map;
    };
    const mine = pick(ownCamp), theirs = pick(ownCamp === 'blue' ? 'red' : 'blue');
    const who = (p, side) => (p
      ? `<span class="md-vs-id ${side}">${portrait(p.hero)}<span><b>${esc(p.label || p.hero || '—')}</b><small>${esc(p.hero || '—')}</small></span></span>`
      : `<span class="md-vs-id ${side} empty">未匹配</span>`);
    const rows = LANES.map((lane) => {
      const a = mine.get(lane), b = theirs.get(lane);
      const bars = metrics.map((m) => {
        const x = m.get(a), y = m.get(b);
        const sum = (x || 0) + (y || 0);
        const share = sum > 0 ? (x || 0) / sum * 100 : 50;
        const lead = (x || 0) > (y || 0) ? 'own' : (x || 0) < (y || 0) ? 'foe' : 'tie';
        const tip = m.tip
          ? [a, b].filter(Boolean).map((p) => `${p.label || p.hero || '—'}：${m.tip(p)}`).join(' / ')
          : '';
        return `<div class="md-vsm" data-lead="${lead}"${tip ? ` title="${esc(tip)}"` : ''}>
          <span class="md-vsm-label">${m.label}</span>
          <b class="md-vsm-num own">${num(x) ? m.text(x) : '—'}</b>
          <span class="md-vsm-track"><i style="width:${share.toFixed(1)}%"></i></span>
          <b class="md-vsm-num foe">${num(y) ? m.text(y) : '—'}</b>
        </div>`;
      }).join('');
      return `<article class="md-vs">
        <div class="md-vs-head"><span class="md-vs-lane">${lane}</span>${who(a, 'own')}${who(b, 'foe')}</div>
        <div class="md-vs-body">${pairRadar(a, b, metrics)}<div class="md-vs-metrics">${bars}</div></div>
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

  function panel(players, ownCamp, positions, duration) {
    if (!players || !players.length) return `<div class="empty">这场比赛还没有十人面板数据。</div>`;
    if (!ownCamp) return `<div class="empty">阵营未知，无法做对位比较。</div>`;
    /* 兼容 ownCamp 为 left / right 的历史写法 */
    const camp = ownCamp === 'left' ? 'blue' : ownCamp === 'right' ? 'red' : ownCamp;
    const foeCamp = camp === 'blue' ? 'red' : 'blue';
    const ownName = `本队 · ${camp === 'blue' ? '蓝方' : '红方'}`;
    const foeName = `对手 · ${foeCamp === 'blue' ? '蓝方' : '红方'}`;
    const inv = positions && positions.players && positions.players.length ? invasionStats(positions, players, duration) : null;
    const metrics = buildMetrics(inv);
    const tab = (mode, text) => `<button type="button" role="tab" class="md-seg-btn${panelMode === mode ? ' is-on' : ''}"
      aria-selected="${panelMode === mode}" data-md-panel-mode="${mode}">${text}</button>`;
    const note = inv
      ? '对位看同分路两人的形状差；同队看资源分配。入侵 = 进入对侧半区的时间占比，悬停可看次数与首次时间'
      : '对位看同分路两人的形状差；同队看资源在本队内部的分配（本局没有位置数据，入侵列缺省）';
    return `<div class="md-panel" data-md-panel>
      <div class="md-panel-bar">
        <div class="md-seg" role="tablist" aria-label="十人面板口径">${tab('duel', '对位比较')}${tab('team', '同队比较')}</div>
        <p class="md-panel-note">${note}</p>
      </div>
      <div class="md-panel-view" data-md-view="duel"${panelMode === 'duel' ? '' : ' hidden'}>${duelView(players, camp, metrics)}</div>
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

    const side = (p) => (p.camp === ownCamp ? 'own' : 'foe');
    const canvas = (p, size) => `<canvas class="md-heat-canvas" width="${GRID * size}" height="${GRID * size}"
      data-heat-card="${p.camp}-${p.slot}" data-camp="${p.camp}" data-side="${side(p)}"
      role="img" aria-label="${esc((p.info.label || p.info.hero || '') + ' 位置热区')}"></canvas>`;
    const ten = list.map((p) => `<article class="md-heat ${side(p)}">
        <div class="md-heat-top"><span><b>${esc(p.info.hero || '—')}</b><small>${esc(p.info.label || p.info.nickname || '—')}</small></span>
          <em data-heat-share="${p.camp}-${p.slot}">—<small>敌方半区</small></em></div>
        ${canvas(p, 7)}
      </article>`).join('');
    const laneCards = LANES.map((lane) => {
      const own = list.find((p) => p.camp === ownCamp && laneOf(p.info) === lane);
      const foe = list.find((p) => p.camp !== ownCamp && laneOf(p.info) === lane);
      if (!own && !foe) return '';
      const one = (p, kind) => (p ? `<div class="md-heat-pair-card">
          ${canvas(p, 6)}
          <span class="md-heat-pair-name"><i class="${kind}"></i>${esc(p.info.label || p.info.hero || '—')}</span>
        </div>` : '<div class="md-heat-pair-card empty">—</div>');
      return `<article class="md-heat md-heat-lane">
        <div class="md-heat-top"><b>${lane}</b></div>
        <div class="md-heat-pairs">${one(own, 'own')}${one(foe, 'foe')}</div>
      </article>`;
    }).join('');

    const tab = (mode, text) => `<button type="button" role="tab" class="md-seg-btn${heatMode === mode ? ' is-on' : ''}"
      aria-selected="${heatMode === mode}" data-md-heat-mode="${mode}">${text}</button>`;
    return `<div class="md-heatwrap" data-md-heat>
      <div class="md-panel-bar">
        <button type="button" class="md-heat-play" data-heat-play aria-pressed="false">播放</button>
        <input type="range" class="md-heat-range" data-heat-range min="0" max="${Math.round(total)}" step="${step}" value="${Math.round(total)}" aria-label="热区时间轴">
        <span class="md-heat-clock" data-heat-clock>—</span>
        <div class="md-seg" role="tablist" aria-label="热区视图">${tab('ten', '十人')}${tab('lane', '对位')}</div>
      </div>
      <div class="md-panel-view" data-md-heat-view="ten"${heatMode === 'ten' ? '' : ' hidden'}>
        <div class="md-heats">${ten}</div>
      </div>
      <div class="md-panel-view" data-md-heat-view="lane"${heatMode === 'lane' ? '' : ' hidden'}>
        <div class="md-heats md-heats-lane">${laneCards}</div>
      </div>
      <p class="md-panel-note">窗口 ${HEAT_WINDOW} 秒随指针滚动；静止 ≥12 秒的样本已剔除。对位视图把同一路的两个人并排放，金为本队、青为对手。</p>
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

  function drawHeat(canvas, counts, max, side) {
    const ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) return;
    const cell = canvas.width / GRID;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const rgb = side === 'foe' ? '94, 201, 190' : '216, 178, 106';
    for (let i = 0; i < counts.length; i++) {
      const n = counts[i];
      if (!n) continue;
      const alpha = 0.16 + Math.pow(n / max, 0.55) * 0.84;
      ctx.fillStyle = `rgba(${rgb}, ${alpha.toFixed(3)})`;
      ctx.fillRect((i % GRID) * cell, (GRID - 1 - Math.floor(i / GRID)) * cell, cell, cell);
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
        const hit = event.target.closest ? event.target.closest('[data-heat-play],[data-md-heat-mode]') : null;
        if (!hit) return;
        if (hit.hasAttribute('data-heat-play')) { toggleHeat(hit); return; }
        const mode = hit.dataset.mdHeatMode;
        const box = hit.closest('[data-md-heat]');
        if (!box) return;
        heatMode = mode;
        box.querySelectorAll('[data-md-heat-mode]').forEach((b) => {
          const on = b.dataset.mdHeatMode === mode;
          b.classList.toggle('is-on', on);
          b.setAttribute('aria-selected', String(on));
        });
        box.querySelectorAll('[data-md-heat-view]').forEach((view) => { view.hidden = view.dataset.mdHeatView !== mode; });
        paintHeat(Number(box.querySelector('[data-heat-range]')?.value || 0));
      });
    }
    const box = document.querySelector('[data-md-heat]');
    if (!box || !heatState) return;
    const slider = box.querySelector('[data-heat-range]');
    paintHeat(Number(slider ? slider.value : heatState.duration));
  }

  /* ── 对位纵深：同一张表，深区（>66%）/ 半区（>50%，即入侵）双口径 ── */
  function duel(positions, players, ownCamp, duration) {
    if (!positions || !positions.players?.length) return '';
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
          const phase = duration > 0 ? Math.min(2, Math.floor(t / (duration / 3))) : 0;
          seconds[phase] += step;
        }
        index.set(`${src.camp}-${laneOfPlayer(info)}`, { info, seconds });
      }
      const rows = LANES.map((lane) => {
        const own = index.get(`${ownCamp}-${lane}`);
        const foe = index.get(`${foeCamp}-${lane}`);
        const cell = (entry, side) => {
          if (!entry) return `<span class="md-duel-cell ${side} empty">—</span>`;
          return entry.seconds.map((sec) => `<span class="md-duel-cell ${side}">
            <b>${fmt(sec)}<small>秒</small></b>
            <span class="md-vox">${'<i></i>'.repeat(clamp(Math.round(sec / 10), 0, 10)) || '<i class="zero"></i>'}</span>
          </span>`).join('');
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
      <p class="md-panel-note">${caption}</p>${body}</div>`;
    const tab = (mode, text) => `<button type="button" role="tab" class="md-seg-btn${duelMode === mode ? ' is-on' : ''}"
      aria-selected="${duelMode === mode}" data-md-duel-mode="${mode}">${text}</button>`;
    return `<div class="md-depth" data-md-duel>
      <div class="md-panel-bar">
        <div class="md-seg" role="tablist" aria-label="纵深口径">${tab('deep', '深区 >66%')}${tab('half', '半区 >50%（入侵）')}</div>
        <p class="md-panel-note">静止 ≥12 秒的样本（阵亡停留等）已剔除，与全景页同口径</p>
      </div>
      ${view('deep', table(DEEP, '本队 · 推进到对侧深区', '对手 · 推进到本队深区'),
        '推进进度超过 66% 记为一侧深区；方块数表示停留时长，每格约 10 秒，最多 10 格')}
      ${view('half', table(HALF, '本队 · 进入对侧半区', '对手 · 进入本队半区'),
        '越过中线（推进进度 > 50%）即算进入对侧半区，也就是入侵；同一套采样，只换了阈值')}
    </div>`;
  }

  /* ── 交互：比赛脉搏指针 ─────────────────────────────────────────── */
  function bindPulse(root, series, events) {
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
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', () => { cursor.setAttribute('hidden', ''); });
  }

  return { totals, pulse, phaseTable, panel, heat, duel, cohesion, bindPulse, bindPanel, bindHeat };
}
