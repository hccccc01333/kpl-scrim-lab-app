/* Replay player: renders a ``kpl-replay-state-v1`` document as an input-layer
 * replay.  The document comes from /api/replays/<id>/state, which is decoded
 * from the .abc/.ope pair; it carries no HP, gold income, KDA or trajectories,
 * so the player never draws them.  Anything the container lacks is shown as a
 * declared gap instead of a fabricated value. */

const FPS = 60;
const TEAM = { 1: 'blue', 2: 'red' };
const TEAM_LABEL = { blue: '蓝方', red: '红方' };
const FAMILIES = [
  ['m', '移动', '#6ea8fe'],
  ['a', '攻击', '#f08a6c'],
  ['s', '技能', '#c9a227'],
  ['c', 'CC指令', '#9b8cff'],
  ['am', '瞄准', '#57c7a3'],
];

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function niceMax(value) {
  if (!value || value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const scaled = value / exp;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * exp;
}

function state() {
  return {
    doc: null,
    second: 0,
    playing: false,
    speed: 1,
    raf: 0,
    last: 0,
    series: null,
  };
}

const store = state();

/* ---------------------------------------------------------------- data --- */

function buildSeries(doc) {
  const players = doc.players.slice().sort((a, b) => (a.entityId - b.entityId));
  const byId = new Map(players.map((p) => [p.entityId, p]));
  const maxSpend = niceMax(Math.max(0, ...players.map((p) => p.goldSpentFinal || 0)));
  const maxLevel = doc.timeline.reduce(
    (acc, frame) => Math.max(acc, ...frame.p.map((cell) => cell.lv || 0)), 1);
  return { players, byId, maxSpend, maxLevel: Math.max(maxLevel, 15) };
}

function frameAt(second) {
  const timeline = store.doc.timeline;
  const index = Math.floor(Math.min(Math.max(second, 0), timeline.length - 1));
  return timeline[index];
}

function cellOf(frame, entityId) {
  return frame.p.find((cell) => cell.e === entityId) || null;
}

/* --------------------------------------------------------------- canvas --- */

function lineChart(canvas, series, valueOf, maxValue, colours) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 600;
  const height = canvas.clientHeight || 180;
  if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const padLeft = 38;
  const padBottom = 18;
  const plotW = width - padLeft - 8;
  const plotH = height - padBottom - 8;
  const timeline = store.doc.timeline;
  const span = Math.max(1, timeline.length - 1);

  ctx.strokeStyle = 'rgba(255,255,255,.10)';
  ctx.lineWidth = 1;
  ctx.font = '10px system-ui, sans-serif';
  ctx.fillStyle = 'rgba(255,255,255,.42)';
  for (let i = 0; i <= 4; i += 1) {
    const y = 8 + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + plotW, y);
    ctx.stroke();
    const value = Math.round(maxValue * (1 - i / 4));
    ctx.fillText(String(value), 4, y + 3);
  }
  for (let m = 0; m <= Math.floor(span / 60); m += 1) {
    const x = padLeft + (plotW * (m * 60)) / span;
    ctx.fillText(mmss(m * 60), x - 12, height - 5);
  }

  for (const player of series.players) {
    const colour = colours(player);
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    let started = false;
    timeline.forEach((frame, index) => {
      const cell = cellOf(frame, player.entityId);
      const value = cell ? valueOf(cell) : null;
      if (value == null) { started = false; return; }
      const x = padLeft + (plotW * index) / span;
      const y = 8 + plotH * (1 - Math.min(1, value / maxValue));
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    });
    ctx.stroke();
  }

  // playhead
  const px = padLeft + (plotW * store.second) / span;
  ctx.strokeStyle = 'rgba(255,255,255,.65)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(px, 4);
  ctx.lineTo(px, 8 + plotH);
  ctx.stroke();
}

/* ----------------------------------------------------------------- view --- */

function teamColour(player) {
  return player.team === 'blue' ? '#6ea8fe' : '#f08a6c';
}

function renderHeader(doc) {
  const match = doc.match || {};
  const winner = match.winningCamp;
  return `<header class="rp-head">
    <div>
      <p class="rp-eyebrow">输入层回放 · kpl-replay-state-v1</p>
      <h1>${esc(mmss(match.durationSec || 0))} 对局 <span class="rp-win">${esc(TEAM_LABEL[winner] || '胜负未知')}获胜</span></h1>
      <p class="rp-sub">${esc((doc.source.build || []).join(' / ') || '构建未知')} · ${esc(String(doc.source.totalFrames || ''))} 帧 · ${esc(String(doc.source.frameHz || ''))} Hz</p>
    </div>
    <div class="rp-head-note">所有数值来自 <b>.abc/.ope 解码</b>。容器不含 HP、金币收入、KDA 与轨迹，因此本页不显示这些；缺失原因见页脚。</div>
  </header>`;
}

function renderRoster(series) {
  const rows = series.players.map((player) => `
    <button class="rp-chip" data-entity="${player.entityId}" style="--team:${teamColour(player)}">
      <span class="rp-chip-team">${esc(TEAM_LABEL[player.team] || '?')}</span>
      <b>${esc(player.hero || '未知英雄')}</b>
      <small>${esc(player.player || '')}</small>
      ${player.mvp ? '<em class="rp-mvp">MVP</em>' : ''}
      <span class="rp-chip-stat" data-stat="${player.entityId}"></span>
    </button>`).join('');
  return `<div class="rp-roster">${rows}</div>`;
}

function renderPlans(player) {
  const plans = player.loadoutPlans || [];
  if (!plans.length) return '';
  const rows = plans.map((plan) => `
    <li><b>${esc(plan.name)}</b>
      <span>${esc((plan.items || []).filter((it) => it.id)
        .map((it) => it.name || `#${it.id}`).join(' → '))}</span>
    </li>`).join('');
  return `<details class="rp-plans"><summary>出装方案 ${plans.length}</summary><ul>${rows}</ul></details>`;
}

function renderPlayerCards(series) {
  const cards = series.players.map((player) => `
    <article class="rp-card" data-card="${player.entityId}">
      <div class="rp-card-head">
        <span class="rp-dot" style="background:${teamColour(player)}"></span>
        <b>${esc(player.hero || '未知英雄')}</b>
        <small>${esc(player.player || '')}</small>
        ${player.rating != null ? `<i>评分 ${esc(player.rating)}</i>` : ''}
      </div>
      <dl>
        <div><dt>等级</dt><dd data-f="lv">—</dd></div>
        <div><dt>累计花费</dt><dd data-f="gs">—</dd></div>
        <div><dt>技能点</dt><dd data-f="learn">—</dd></div>
        <div><dt>出装数</dt><dd data-f="buy">—</dd></div>
      </dl>
      <div class="rp-bars" data-bars></div>
      ${renderPlans(player)}
    </article>`).join('');
  return `<div class="rp-cards">${cards}</div>`;
}

function renderCharts(series) {
  return `<div class="rp-charts">
    <figure class="rp-chart">
      <figcaption>累计金币花费（支出账本，非收入）</figcaption>
      <canvas data-chart="gold"></canvas>
    </figure>
    <figure class="rp-chart">
      <figcaption>英雄等级（技能点推导）</figcaption>
      <canvas data-chart="level"></canvas>
    </figure>
  </div>`;
}

function renderTimeline(doc) {
  return `<div class="rp-timeline">
    <button class="rp-play" data-act="toggle" aria-label="播放/暂停">▶</button>
    <input class="rp-range" type="range" min="0" max="${Math.max(0, doc.timeline.length - 1)}" value="0" step="1">
    <output class="rp-clock">00:00</output>
    <select class="rp-speed" data-act="speed">
      <option value="0.5">0.5×</option>
      <option value="1" selected>1×</option>
      <option value="2">2×</option>
      <option value="4">4×</option>
    </select>
  </div>`;
}

function renderEvents() {
  return `<section class="rp-events">
    <h2>当前时间附近的事件</h2>
    <ol data-events></ol>
  </section>`;
}

function renderAnchors(doc) {
  const anchors = doc.anchors || [];
  if (!anchors.length) return '';
  return `<section class="rp-anchors">
    <h2>稀疏坐标锚点（${anchors.length} 条，仅 ${new Set(anchors.map((a) => a.e)).size} 名玩家）</h2>
    <div class="rp-anchors-body">
      <figure><canvas data-anchor-map width="300" height="300"></canvas>
        <figcaption>位置消息世界坐标（标尺未校准，按观测范围归一化）</figcaption></figure>
      <ol class="rp-anchor-list" data-anchor-list></ol>
    </div>
    <p class="rp-anchors-note">这些是回放写入的位置消息样本，不是连续轨迹；两点之间没有插值。</p>
  </section>`;
}

function drawAnchors(series) {
  const canvas = document.querySelector('[data-anchor-map]');
  const list = document.querySelector('[data-anchor-list]');
  if (!canvas) return;
  const anchors = store.doc.anchors || [];
  const xs = anchors.map((a) => a.x);
  const ys = anchors.map((a) => a.y);
  const minX = Math.min(...xs) - 2000;
  const maxX = Math.max(...xs) + 2000;
  const minY = Math.min(...ys) - 2000;
  const maxY = Math.max(...ys) + 2000;
  const spanX = maxX - minX;
  const spanY = maxY - minY;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const size = 300;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);
  ctx.strokeStyle = 'rgba(255,255,255,.08)';
  for (let i = 0; i <= 4; i += 1) {
    const p = (size * i) / 4;
    ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, size); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(size, p); ctx.stroke();
  }
  const now = store.second;
  const heroOf = new Map(series.players.map((p) => [p.entityId, p.hero || '']));
  const teamOf = new Map(series.players.map((p) => [p.entityId, p.team]));
  const near = [];
  for (const a of anchors) {
    const x = ((a.x - minX) / spanX) * size;
    const y = size - ((a.y - minY) / spanY) * size;
    const isNear = Math.abs(a.t - now) <= 30;
    if (isNear) near.push(a);
    ctx.fillStyle = teamOf.get(a.e) === 'blue' ? '#6ea8fe' : '#f08a6c';
    ctx.globalAlpha = isNear ? 1 : 0.35;
    ctx.beginPath();
    ctx.arc(x, y, isNear ? 5 : 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  if (list) {
    const rows = near.slice(0, 12).map((a) => `
      <li><time>${esc(mmss(a.t))}</time><b>${esc(heroOf.get(a.e) || a.e)}</b>
        <small>kind ${esc(a.kind)} · (${fmt(a.x)}, ${fmt(a.y)})</small></li>`).join('');
    list.innerHTML = rows || '<li class="rp-empty">当前时刻附近没有锚点。</li>';
  }
}

function renderOpe(doc) {
  const ope = doc.ope;
  if (!ope) {
    return `<section class="rp-ope"><h2>.ope 操作流</h2>
      <p class="rp-ope-empty">这份回放没有配套的 .ope 文件，因此没有本地操作流可显示。</p></section>`;
  }
  const types = Object.entries(ope.typeCounts || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 8);
  const maxType = Math.max(1, ...types.map(([, value]) => value));
  const typeRows = types.map(([name, value]) => `
    <li><span>${esc(name)}</span><i style="width:${(value / maxType) * 100}%"></i><b>${value}</b></li>`).join('');
  const strict = ope.mode === 'strict-layouts';
  const consumed = strict
    ? `${fmt(ope.streamEnd)} / ${fmt(ope.streamBytes)} 字节`
    : `${(ope.coveragePct ?? 0).toFixed(3)}%`;
  const repairs = (ope.repairs || []).map((row) => `
    <li><code>0x${(row.wall || 0).toString(16)}</code>
        <span>${row.shift > 0 ? '+' : ''}${row.shift}</span>
        <small>推进至 0x${(row.dpReachAfter || 0).toString(16)}</small></li>`).join('');
  const tailNote = ope.truncatedTail
    ? '流尾有一条被录制器截断的记录，已显式标记（truncatedTail）。'
    : '';
  return `<section class="rp-ope">
    <h2>.ope 本地玩家操作流${strict ? '（严格布局解码）' : '（边界修复模式）'}</h2>
    <div class="rp-ope-stats">
      <div><b>${fmt(ope.records)}</b><span>结构化记录</span></div>
      <div><b>${esc(consumed)}</b><span>已消费字节</span></div>
      <div><b>${fmt(strict ? ope.tentativeRecords : ope.repairCount)}</b>
        <span>${strict ? '推断布局记录' : '边界修复点'}</span></div>
      <div><b>${fmt(strict ? ope.ambiguousChoices : ope.unityRegressions)}</b>
        <span>${strict ? '歧义选择点' : 'unity 时钟下降'}</span></div>
    </div>
    ${tailNote ? `<p class="rp-ope-caveat">${esc(tailNote)}</p>` : ''}
    <div class="rp-ope-body">
      <figure>
        <figcaption>记录类型 Top 8</figcaption>
        <ul class="rp-ope-types">${typeRows}</ul>
      </figure>
      <figure>
        <figcaption>${strict ? '流尾截断' : '边界修复点（每个跳过/回退的字节都在这里）'}</figcaption>
        <ul class="rp-ope-repairs">${repairs
          || (ope.truncatedTail
            ? `<li class="rp-ope-empty">截断于 0x${Number(ope.truncatedTail.offset || 0).toString(16)}（${esc(ope.truncatedTail.hex || '')}）</li>`
            : '<li class="rp-ope-empty">无需修复，直接解析到末尾。</li>')}</ul>
      </figure>
    </div>
    <p class="rp-ope-caveat">${esc(ope.caveat || '')}</p>
  </section>`;
}

function fmt(value) {
  if (value == null) return '—';
  return Number(value).toLocaleString('zh-CN');
}

function renderGaps(doc) {
  const items = Object.entries(doc.missing || {})
    .map(([key, why]) => `<li><b>${esc(key)}</b>${esc(why)}</li>`).join('');
  return `<footer class="rp-gaps">
    <h2>文件里没有、因此没有画的字段</h2>
    <ul>${items}</ul>
  </footer>`;
}

/* ------------------------------------------------------------ animation --- */

function settleBar(series, entityId) {
  const frame = frameAt(store.second);
  const cell = cellOf(frame, entityId);
  const card = document.querySelector(`[data-card="${entityId}"]`);
  if (!cell || !card) return;
  card.querySelector('[data-f="lv"]').textContent = cell.lv ?? '—';
  card.querySelector('[data-f="gs"]').textContent = cell.gs != null ? cell.gs : '—';
  const player = series.byId.get(entityId);
  card.querySelector('[data-f="learn"]').textContent = player ? player.learnCount : '—';
  card.querySelector('[data-f="buy"]').textContent = player ? player.purchaseCount : '—';
  const bars = card.querySelector('[data-bars]');
  const max = Math.max(1, ...FAMILIES.map(([key]) => cell[key] || 0));
  bars.innerHTML = FAMILIES.map(([key, label, colour]) => {
    const value = cell[key] || 0;
    const hint = key === 'c'
      ? 'CC 指令同步（朝向/停止/落点），不是控制效果'
      : label;
    return `<span title="${esc(hint)} ${value}"><i style="width:${(value / max) * 100}%;background:${colour}"></i><u>${esc(label)}</u><b>${value}</b></span>`;
  }).join('');
  const chip = document.querySelector(`[data-stat="${entityId}"]`);
  if (chip) chip.textContent = `Lv${cell.lv ?? '—'} · ${cell.gs != null ? cell.gs : '—'}g`;
}

function settleEvents(doc) {
  const list = document.querySelector('[data-events]');
  if (!list) return;
  const now = store.second;
  const window = 45;
  const rows = [];
  for (const item of doc.events.purchases) {
    if (item.t >= now - window && item.t <= now + 6) rows.push({ t: item.t, kind: 'buy', item });
  }
  for (const item of doc.events.learns) {
    if (item.t >= now - window && item.t <= now + 6) rows.push({ t: item.t, kind: 'learn', item });
  }
  rows.sort((a, b) => b.t - a.t);
  const names = new Map(store.series.players.map((p) => [p.entityId, p.hero || '']));
  list.innerHTML = rows.slice(0, 14).map((row) => {
    const hero = esc(names.get(row.item.entityId) || '');
    if (row.kind === 'buy') {
      return `<li><time>${esc(mmss(row.t))}</time><span class="rp-k rp-k-buy">出装</span><b>${hero}</b> ${esc(row.item.name || '')} ${row.item.price != null ? `<i>${row.item.price}g</i>` : ''}</li>`;
    }
    return `<li><time>${esc(mmss(row.t))}</time><span class="rp-k rp-k-skill">加点</span><b>${hero}</b> 技能槽 ${esc(row.item.slot)}</li>`;
  }).join('') || '<li class="rp-empty">这一时间附近没有出装或加点事件。</li>';
}

function settleClock(doc) {
  const clock = document.querySelector('.rp-clock');
  if (clock) clock.textContent = `${mmss(store.second)} / ${mmss(doc.timeline.length - 1)}`;
  const range = document.querySelector('.rp-range');
  if (range && Number(range.value) !== store.second) range.value = String(store.second);
}

function drawCharts(series) {
  const gold = document.querySelector('[data-chart="gold"]');
  const level = document.querySelector('[data-chart="level"]');
  if (gold) {
    lineChart(gold, series, (cell) => cell.gs, series.maxSpend, teamColour);
  }
  if (level) {
    lineChart(level, series, (cell) => cell.lv, series.maxLevel, teamColour);
  }
}

function draw() {
  if (!store.doc || !store.series) return;
  const series = store.series;
  for (const player of series.players) settleBar(series, player.entityId);
  settleClock(store.doc);
  settleEvents(store.doc);
  drawAnchors(series);
  drawCharts(series);
}

/* -------------------------------------------------------------- control --- */

function tick(now) {
  if (!store.playing || !store.doc) return;
  const delta = (now - store.last) / 1000;
  store.last = now;
  const last = store.doc.timeline.length - 1;
  store.second = Math.min(last, store.second + delta * store.speed);
  draw();
  if (store.second >= last) {
    store.playing = false;
    document.querySelector('.rp-play').textContent = '▶';
    return;
  }
  store.raf = requestAnimationFrame(tick);
}

function bind(root) {
  root.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-act="toggle"]');
    if (toggle) {
      store.playing = !store.playing;
      toggle.textContent = store.playing ? '❚❚' : '▶';
      if (store.playing) {
        store.last = performance.now();
        store.raf = requestAnimationFrame(tick);
      } else {
        cancelAnimationFrame(store.raf);
      }
      return;
    }
    const chip = event.target.closest('[data-entity]');
    if (chip) {
      const card = document.querySelector(`[data-card="${chip.dataset.entity}"]`);
      card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });
  root.addEventListener('input', (event) => {
    if (event.target.matches('.rp-range')) {
      store.second = Number(event.target.value);
      draw();
    }
    if (event.target.matches('.rp-speed')) {
      store.speed = Number(event.target.value);
    }
  });
  window.addEventListener('resize', () => store.series && drawCharts(store.series));
  window.addEventListener('keydown', (event) => {
    if (event.key === ' ' && event.target === document.body) {
      event.preventDefault();
      document.querySelector('[data-act="toggle"]')?.click();
    }
  });
}

/* ----------------------------------------------------------------- boot --- */

export async function mount(root, replayId) {
  root.innerHTML = '<div class="rp-loading">正在解码 .abc/.ope 并建立时间轴…</div>';
  let doc;
  try {
    const response = await fetch(`/api/replays/${encodeURIComponent(replayId)}/state`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `接口返回 ${response.status}`);
    }
    doc = await response.json();
  } catch (error) {
    root.innerHTML = `<div class="rp-error">回放状态加载失败：${esc(error.message || error)}</div>`;
    return;
  }
  if (!doc.timeline || !doc.timeline.length) {
    root.innerHTML = '<div class="rp-error">这份解码结果没有时间轴。</div>';
    return;
  }
  store.doc = doc;
  store.second = 0;
  store.playing = false;
  store.series = buildSeries(doc);

  root.innerHTML = `<div class="rp-root">
    ${renderHeader(doc)}
    ${renderRoster(store.series)}
    ${renderTimeline(doc)}
    ${renderCharts(store.series)}
    ${renderPlayerCards(store.series)}
    ${renderEvents()}
    ${renderAnchors(doc)}
    ${renderOpe(doc)}
    ${renderGaps(doc)}
  </div>`;
  bind(root);
  draw();
}
