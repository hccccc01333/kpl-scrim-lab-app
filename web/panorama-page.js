const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits = 0) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits});
const signed = (value, digits = 0) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : `${Number(value) > 0 ? '+' : ''}${num(value, digits)}`;
const clock = value => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const total = Math.max(0, Math.round(Number(value)));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};
const pct = value => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : `${(Number(value) * 100).toFixed(0)}%`;
const CAMP = {
  blue: {label: '蓝方', color: '#2f6fe4', soft: '#eaf1ff', deep: '#1f56c4'},
  red: {label: '红方', color: '#da6b76', soft: '#fff0f1', deep: '#b64c58'},
};
const RADAR_DIMS = [
  ['grow', '发育'], ['battle', '团战'], ['survive', '生存'],
  ['hurtHero', '输出'], ['kda', 'KDA'],
];
let activeCleanup = null;

export function disposePanorama() {
  if (activeCleanup) activeCleanup();
  activeCleanup = null;
}

const heroIcon = player => player.icon
  ? `<img src="${esc(player.icon)}" alt="" loading="lazy">`
  : `<b>${esc((player.hero || '?').slice(0, 1))}</b>`;

function bullets(rows) {
  return rows.map(item => `<li>${esc(item)}</li>`).join('');
}

function radar(player, maxValues, size = 132) {
  const center = size / 2;
  const radius = size * 0.34;
  const values = RADAR_DIMS.map(([key]) => Number(player.official?.[key]));
  const usable = values.every(value => Number.isFinite(value)) && maxValues.every(value => value > 0);
  if (!usable) return `<div class="pn-radar-empty">官方评分未提供</div>`;
  const point = (index, ratio) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / RADAR_DIMS.length;
    return [center + Math.cos(angle) * radius * ratio, center + Math.sin(angle) * radius * ratio];
  };
  const ratio = index => Math.max(0.04, Math.min(1, values[index] / maxValues[index]));
  const rings = [0.33, 0.66, 1].map(level => `<polygon points="${RADAR_DIMS.map((_, index) => point(index, level).map(value => value.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="#dfe6f2" stroke-width="1"/>`).join('');
  const spokes = RADAR_DIMS.map((_, index) => {
    const [x, y] = point(index, 1);
    return `<line x1="${center}" y1="${center}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e6ebf4"/>`;
  }).join('');
  const shape = RADAR_DIMS.map((_, index) => point(index, ratio(index)).map(value => value.toFixed(1)).join(',')).join(' ');
  const labels = RADAR_DIMS.map(([, label], index) => {
    const [x, y] = point(index, 1.22);
    return `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="middle" class="pn-radar-label">${label}</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${size} ${size}" class="pn-radar" role="img" aria-label="官方评分雷达">
    ${rings}${spokes}<polygon points="${shape}" fill="${CAMP[player.camp].color}" fill-opacity=".16" stroke="${CAMP[player.camp].color}" stroke-width="2"/>${labels}
  </svg>`;
}

function playerCard(player, maxValues) {
  const camp = CAMP[player.camp];
  const kda = player.kills === null || player.deaths === null || player.assists === null
    ? '—' : `${num(player.kills)} / ${num(player.deaths)} / ${num(player.assists)}`;
  const items = (player.builds || []).slice(0, 3).map(item => item.name).filter(Boolean);
  return `<article class="pn-player-card ${player.camp}" data-pn-card="${esc(player.key)}">
    <button class="pn-player-head" data-pn-player="${esc(player.key)}" title="在战场图上查看 ${esc(player.nickname || player.hero)}">
      <span class="pn-player-icon">${heroIcon(player)}</span>
      <span class="pn-player-name"><b>${esc(player.hero || '英雄未识别')}</b><small>${esc(player.nickname || '选手待确认')}</small></span>
      ${player.mvp ? `<span class="pn-mvp ${player.mvp}">${player.mvp === 'win' ? 'MVP' : 'SVP'}</span>` : ''}
    </button>
    <div class="pn-player-kda"><b>${kda}</b><small>K / D / A</small></div>
    <div class="pn-player-body">${radar(player, maxValues)}<dl class="pn-player-stats">
      <div><dt>经济</dt><dd>${num(player.gold)}</dd></div>
      <div><dt>输出</dt><dd>${num(player.damage)}</dd></div>
      <div><dt>承伤</dt><dd>${num(player.taken)}</dd></div>
      <div><dt>参团</dt><dd>${player.participation == null ? '—' : `${num(player.participation, 1)}%`}</dd></div>
      <div><dt>评分</dt><dd>${num(player.rating, 1)}</dd></div>
    </dl></div>
    <div class="pn-player-foot"><span>${items.length ? items.map(esc).join(' · ') : '出装未覆盖'}</span><small>${(player.builds || []).length} 次购买</small></div>
  </article>`;
}

function pageHtml(d, maxValues, embedded = false) {
  const match = d.match;
  const blue = d.players.filter(player => player.camp === 'blue').sort((a, b) => (a.slot ?? 0) - (b.slot ?? 0));
  const red = d.players.filter(player => player.camp === 'red').sort((a, b) => (a.slot ?? 0) - (b.slot ?? 0));
  const scoreBlue = match.scores?.blue ?? match.scores?.left ?? '—';
  const scoreRed = match.scores?.red ?? match.scores?.right ?? '—';
  const own = match.ownCamp;
  const winner = match.winnerCamp;
  const result = winner && own ? (winner === own ? '胜' : '负') : winner ? `${CAMP[winner].label}胜` : '待确认';
  const tone = winner && own ? (winner === own ? 'win' : 'loss') : 'unknown';
  const resultCamp = winner ? CAMP[winner] : CAMP.blue;
  const lineup = camp => (camp === 'blue' ? blue : red).map(player => `<button class="pn-lineup" data-pn-player="${esc(player.key)}" title="${esc(player.nickname || '')} · ${esc(player.hero || '')}">
      <span class="pn-lineup-icon">${heroIcon(player)}</span>
      <span class="pn-lineup-name"><b>${esc(player.hero || '—')}</b><small>${esc(player.nickname || '')}</small></span>
      <span class="pn-lineup-kda">${num(player.kills)}<i>/</i>${num(player.deaths)}<i>/</i>${num(player.assists)}</span>
      ${player.mvp === 'win' ? '<span class="pn-lineup-mvp">MVP</span>' : ''}
    </button>`).join('');
  const insights = (d.insights || []).slice(0, 5).map(item => `<button class="pn-insight ${esc(item.tone || 'neutral')}" ${item.t == null ? '' : `data-pn-time="${item.t}"`}>
      <span>${esc(item.title)}</span><strong>${esc(item.value)}</strong><small>${esc(item.detail)}</small>
    </button>`).join('');
  const phaseButtons = `<div class="pn-segment" data-pn-phase>
      <button data-phase="all" class="active">全场</button>
      ${d.phases.map(phase => `<button data-phase="${esc(phase.key)}">${esc(phase.label)}</button>`).join('')}
    </div>`;
  const playerOptions = d.players.map(player => `<option value="${esc(player.key)}">${esc(player.hero || '')} · ${esc(player.nickname || '')}</option>`).join('');
  const buildRows = (camp) => (camp === 'blue' ? blue : red).map(player => {
    const items = player.builds || [];
    return `<div class="pn-build-row ${camp}">
      <span class="pn-build-name"><span class="pn-build-icon">${heroIcon(player)}</span><b>${esc(player.hero || '')}</b><small>${esc(player.nickname || '')}</small></span>
      <span class="pn-build-lane">${items.map(item => `<i class="pn-build-dot" style="left:${Math.max(0, Math.min(100, item.t / Math.max(1, match.duration) * 100))}%" title="${clock(item.t)} · ${esc(item.name)}"></i>`).join('')}</span>
      <span class="pn-build-count">${items.length}</span>
    </div>`;
  }).join('');
  const hasPosition = player => (d.positions.players?.[player.key]?.points || []).length > 0;
  const duelSlot = [3, 0, 1, 2, 4].find(slot => blue.some(player => player.slot === slot && hasPosition(player))
    && red.some(player => player.slot === slot && hasPosition(player)));
  const duelBlue = blue.find(player => duelSlot != null && player.slot === duelSlot && hasPosition(player)) || blue.find(hasPosition) || blue[0];
  const duelRed = red.find(player => duelSlot != null && player.slot === duelSlot && hasPosition(player)) || red.find(hasPosition) || red[0];
  const duelOptions = (list, chosen) => list.map(player => `<option value="${esc(player.key)}"${player.key === chosen?.key ? ' selected' : ''}>${esc(player.hero || '')} · ${esc(player.nickname || '')}</option>`).join('');
  const phaseRows = d.phases.map(phase => {
    const team = phase.team || {};
    return `<tr>
      <th><strong>${esc(phase.label)}</strong><small>${clock(phase.from)}–${clock(phase.to)}</small></th>
      <td class="${phase.goldEnd > 0 ? 'pn-positive' : phase.goldEnd < 0 ? 'pn-negative' : ''}">${signed(phase.goldEnd)}</td>
      <td>${signed(phase.goldChange)}</td>
      <td><span class="pn-mini blue">${num(phase.resources?.blue)}</span><span class="pn-mini red">${num(phase.resources?.red)}</span></td>
      <td><span class="pn-mini blue">${num(phase.structures?.blue)}</span><span class="pn-mini red">${num(phase.structures?.red)}</span></td>
      <td>${pct(team.blue?.enemyHalfRate)}</td>
      <td>${pct(team.red?.enemyHalfRate)}</td>
      <td>${pct(team.blue?.closeRate)}</td>
      <td>${pct(team.red?.closeRate)}</td>
    </tr>`;
  }).join('');
  return `<div class="panorama">
    <h1 class="pn-sr-only">${esc(match.title || '对局详情')} · 对局详情</h1>
    <div class="pn-topline">${embedded ? '<a class="back-link" href="#matches">← 返回比赛档案</a><span class="pn-topline-actions"><button class="text-link" data-print>打印 / PDF</button><a class="back-link" href="#match-extra">本局资料 ↓</a></span>' : `<a class="back-link" href="#match/${encodeURIComponent(match.key)}">← 返回对局详情</a><a class="back-link" href="#matches">比赛档案</a>`}</div>
    <header class="pn-hero">
      <div class="pn-hero-glow blue"></div><div class="pn-hero-glow red"></div>
      <div class="pn-hero-label"><span class="page-eyebrow">MATCH RECORD · 对局档案</span><span class="pn-hero-date">${esc(match.date || '日期待补')} · ${esc(match.mode || '模式未记录')}</span></div>
      <div class="pn-scoreboard">
        <div class="pn-team blue"><div class="pn-team-title"><span class="pn-dot"></span><strong>${own === 'blue' ? '本队 · 蓝方' : '蓝方'}</strong></div>${lineup('blue')}</div>
        <div class="pn-center">
          <div class="pn-result ${tone}" style="--camp:${resultCamp.color}">${esc(result)}</div>
          <div class="pn-score"><b>${esc(scoreBlue)}</b><i>:</i><b>${esc(scoreRed)}</b></div>
          <div class="pn-meta"><span>${clock(match.duration)}</span><span>${esc(match.title || '训练赛')}</span></div>
          <div class="pn-source"><span class="pn-source-dot"></span>官方回放 · 逐秒坐标 · 出装时间线</div>
        </div>
        <div class="pn-team red"><div class="pn-team-title"><span class="pn-dot"></span><strong>${own === 'red' ? '本队 · 红方' : '红方'}</strong></div>${lineup('red')}</div>
      </div>
      <div class="pn-insights">${insights}</div>
    </header>

    <section class="pn-card pn-pulse-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">ECONOMY PULSE</span><h2>比赛脉搏</h2><p>蓝方 − 红方经济差；三角为资源事件，方块为建筑摧毁。拖动或点击时间轴查看任意时刻。</p></div><div class="pn-legend"><span><i class="pn-key blue"></i>蓝方领先</span><span><i class="pn-key red"></i>红方领先</span><span><i class="pn-key diamond"></i>资源</span><span><i class="pn-key square"></i>建筑</span></div></div>
      <div class="pn-pulse-readout" id="pn-pulse-readout"></div>
      <div class="pn-pulse-chart" id="pn-pulse"></div>
      <div class="pn-scrubber"><input id="pn-time" type="range" min="0" max="${Math.max(1, Math.round(match.duration || 0))}" value="0" step="1" aria-label="比赛时间轴"><span id="pn-time-label">00:00</span></div>
    </section>

    <section class="pn-card pn-river-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">EVENT RIVER</span><h2>事件河流</h2><p>官方事件只覆盖资源与建筑；英雄击杀不在官方事件里，因此不在此处补造。</p></div><span class="pn-chip">${num(d.coverage.events)} 条事件</span></div>
      <div class="pn-river" id="pn-river"></div>
    </section>

    <section class="pn-card pn-map-card" id="pn-map-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">SPATIAL CONTROL</span><h2>战场分布</h2><p>逐秒坐标经高斯平滑生成连续密度场，蓝 / 红双通道共用同一标尺，重叠处偏亮表示双方都常驻；轨迹由浅到深表示时间推进，静止死亡样本已排除。</p></div>
        <div class="pn-map-controls"><div class="pn-segment" data-pn-team><button data-team="both" class="active">双方</button><button data-team="blue">蓝方</button><button data-team="red">红方</button></div>${phaseButtons}<select id="pn-player-select" aria-label="选择选手"><option value="">全队热区</option>${playerOptions}</select><span class="pn-play-group"><button class="button pn-play" id="pn-play">播放</button><select id="pn-speed" aria-label="播放速度"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></span></div>
      </div>
      <div class="pn-map-layout"><div class="pn-map" id="pn-map"></div><aside class="pn-map-side" id="pn-map-side"></aside></div>
    </section>

    <section class="pn-card pn-heat-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">POSITION HEATMAPS</span><h2>十人热区</h2><p>逐秒坐标经高斯平滑生成连续密度场，10 张图共用同一标尺，可直接横向比较；点击选手卡回到主地图查看轨迹。</p></div>${phaseButtons}</div>
      <div class="pn-heat-legend" id="pn-heat-legend"></div>
      <div class="pn-heat-grid" id="pn-heat-grid"></div>
    </section>

    <section class="pn-card pn-duel-card">
      <div class="pn-card-head pn-duel-head">
        <div class="pn-duel-headline"><h2 id="pn-duel-title">对位分布</h2><p>双方坐标按己方出生角镜像至左下，右上为对侧深区；六幅图共用热度与坐标标尺，阵亡等待样本已排除。</p></div>
        <div class="pn-duel-pickers">
          <label><span>蓝方</span><select id="pn-duel-blue" aria-label="选择蓝方对位选手">${duelOptions(blue, duelBlue)}</select></label>
          <span class="pn-duel-vs">VS</span>
          <label><span>红方</span><select id="pn-duel-red" aria-label="选择红方对位选手">${duelOptions(red, duelRed)}</select></label>
        </div>
      </div>
      <div id="pn-duel"></div>
      <div class="pn-duel-foot" id="pn-duel-foot"></div>
    </section>

    <section class="pn-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">PLAYER PROFILES</span><h2>十人面板</h2><p>官方五项评分按全局最大值归一化，只画形状，不把不同量纲相加成总分。</p></div><span class="pn-chip">${d.players.filter(player => player.official).length}/10 有官方评分</span></div>
      <div class="pn-player-grid">${d.players.map(player => playerCard(player, maxValues)).join('')}</div>
    </section>

    <section class="pn-card pn-build-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">BUILD TIMELINE</span><h2>出装节奏</h2><p>每次购买按时间落点；包含小件与合成件，不做“成装”推断。时间来自 .abc 帧命令，误差约 ±3 秒。</p></div><span class="pn-chip">${num(d.coverage.builds.items)} 次购买</span></div>
      <div class="pn-build-head"><span></span><span class="pn-build-axis">${[0, 0.25, 0.5, 0.75, 1].map(ratio => `<i style="left:${ratio * 100}%">${clock((match.duration || 0) * ratio)}</i>`).join('')}</span><span>件</span></div>
      ${d.coverage.builds.items ? buildRows('blue') + buildRows('red') : '<div class="pn-empty">本局没有 .abc 出装时间线。</div>'}
    </section>

    <section class="pn-card">
      <div class="pn-card-head"><div><span class="pn-eyebrow">PHASE SPLIT</span><h2>阶段对比</h2><p>经济差为蓝方 − 红方；资源与建筑按摧毁方统计；入侵率与同屏率来自逐秒坐标。</p></div></div>
      <div class="table-scroll"><table class="data-table pn-phase-table"><thead><tr><th>阶段</th><th>经济差</th><th>阶段变化</th><th>资源 蓝/红</th><th>建筑 蓝/红</th><th>蓝方入侵</th><th>红方入侵</th><th>蓝方同屏</th><th>红方同屏</th></tr></thead><tbody>${phaseRows}</tbody></table></div>
    </section>

    <details class="pn-card pn-notes"><summary>数据口径与覆盖（${esc(d.schema)}）</summary><div><ul>${bullets(d.notes || [])}</ul><div class="pn-coverage"><span>金币点 ${num(d.coverage.goldPoints)}</span><span>事件 ${num(d.coverage.events)}</span><span>坐标 ${num(d.coverage.positions.seconds)} 秒 × ${num(d.coverage.positions.players)} 人</span><span>出装 ${num(d.coverage.builds.players)} 人</span><span>英雄击杀时间轴：${d.coverage.heroKills ? '有' : '无'}</span></div></div></details>
  </div>`;
}

export async function renderPanorama(root, {api, key, isCurrent = () => true, toast = () => {}, payload = null, embedded = false}) {
  disposePanorama();
  root.innerHTML = '<div class="pn-loading"><span></span>正在拼合单局全景…</div>';
  let d = payload;
  try {
    if (!d) d = await api('/api/review/' + encodeURIComponent(key));
  } catch (error) {
    if (!isCurrent()) return;
    root.innerHTML = `<div class="pn-loading error">读取失败：${esc(error.message)}</div>`;
    return;
  }
  if (!isCurrent()) return;
  const maxValues = RADAR_DIMS.map(([dimension]) => Math.max(1, ...d.players.map(player => Number(player.official?.[dimension]) || 0)));
  root.innerHTML = pageHtml(d, maxValues, embedded);
  const byKey = new Map(d.players.map(player => [player.key, player]));
  const blue = d.players.filter(player => player.camp === 'blue');
  const red = d.players.filter(player => player.camp === 'red');
  const duration = Math.max(1, Number(d.match.duration) || d.gold.points.at(-1)?.t || 1);
  const state = {time: 0, playing: false, speed: 1, team: 'both', phase: 'all', player: ''};
  let timer = null;
  const pulse = root.querySelector('#pn-pulse');
  const river = root.querySelector('#pn-river');
  const map = root.querySelector('#pn-map');
  const timeInput = root.querySelector('#pn-time');
  const timeLabel = root.querySelector('#pn-time-label');
  const readout = root.querySelector('#pn-pulse-readout');
  const mapSide = root.querySelector('#pn-map-side');
  const playerSelect = root.querySelector('#pn-player-select');
  const playButton = root.querySelector('#pn-play');
  const speedSelect = root.querySelector('#pn-speed');
  mapSide.onclick = event => { const target = event.target.closest('[data-pn-time]'); if (target) setTime(Number(target.dataset.pnTime)); };

  const goldAt = t => {
    const points = d.gold.points;
    if (!points.length) return null;
    let best = points[0];
    for (const point of points) {
      if (point.t <= t + 0.5) best = point;
      else break;
    }
    return best;
  };
  const nearestEvent = t => {
    let best = null;
    for (const event of d.events) {
      const distance = Math.abs(event.t - t);
      if (!best || distance < Math.abs(best.t - t)) best = event;
    }
    return best && Math.abs(best.t - t) <= 20 ? best : null;
  };
  const eventText = event => {
    if (!event) return '当前时刻附近没有官方事件';
    const actor = event.killer ? `${event.killer}${event.killerHero ? `（${event.killerHero}）` : ''}` : CAMP[event.killerCamp]?.label || '未知';
    return `${clock(event.t)} · ${event.kind === 'resource' ? '资源' : '建筑'} · ${actor}${event.zone ? ` · ${event.zone === 'river' ? '河道' : event.zone === 'red_half' ? '红方半区' : '蓝方半区'}` : ''}`;
  };

  function drawPulse() {
    const width = Math.max(340, Math.round(pulse.clientWidth || 760));
    const height = 310;
    const left = 62, right = 20, top = 18, bottom = 38;
    const points = d.gold.points;
    if (!points.length) { pulse.innerHTML = '<div class="pn-empty">没有可用的经济观测点。</div>'; return; }
    const x = value => left + (Number(value) / duration) * (width - left - right);
    const min = Math.min(0, ...points.map(point => point.diff));
    const max = Math.max(0, ...points.map(point => point.diff));
    const pad = Math.max(1, (max - min) * 0.12);
    const low = min - pad, high = max + pad;
    const y = value => height - bottom - (value - low) / (high - low) * (height - top - bottom);
    const zero = y(0);
    const band = d.phases.map((phase, index) => `<rect x="${x(phase.from)}" y="${top}" width="${Math.max(0, x(phase.to) - x(phase.from))}" height="${height - top - bottom}" fill="${index % 2 ? '#f5f7fb' : '#fbfcfe'}"/>` +
      `<text x="${x(phase.from) + 8}" y="${top + 13}" class="pn-band-label">${esc(phase.label)}</text>`).join('');
    const grid = [0, 0.25, 0.5, 0.75, 1].map(ratio => {
      const value = low + (high - low) * ratio;
      return `<line x1="${left}" x2="${width - right}" y1="${y(value)}" y2="${y(value)}" class="pn-grid"/><text x="${left - 10}" y="${y(value) + 4}" text-anchor="end" class="pn-axis">${signed(value)}</text>`;
    }).join('');
    const tickStep = duration > 600 ? 120 : 60;
    const xTicks = [];
    for (let second = tickStep; second < duration; second += tickStep) {
      xTicks.push(`<text x="${x(second).toFixed(1)}" y="${height - 10}" text-anchor="middle" class="pn-axis">${clock(second)}</text>`);
    }
    const line = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.t).toFixed(1)},${y(point.diff).toFixed(1)}`).join(' ');
    const area = `M${x(points[0].t).toFixed(1)},${zero.toFixed(1)} ` +
      points.map(point => `L${x(point.t).toFixed(1)},${y(point.diff).toFixed(1)}`).join(' ') +
      ` L${x(points.at(-1).t).toFixed(1)},${zero.toFixed(1)} Z`;
    const clips = `<defs><clipPath id="pn-pos"><rect x="${left - 2}" y="${top}" width="${width - left - right + 4}" height="${Math.max(0, zero - top)}"/></clipPath><clipPath id="pn-neg"><rect x="${left - 2}" y="${zero}" width="${width - left - right + 4}" height="${Math.max(0, height - bottom - zero)}"/></clipPath><linearGradient id="pn-line" x1="0" y1="${top}" x2="0" y2="${height - bottom}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2f6fe4"/><stop offset="${Math.max(0, Math.min(1, (zero - top) / Math.max(1, height - top - bottom)))}" stop-color="#9db8e8"/><stop offset="1" stop-color="#da6b76"/></linearGradient></defs>`;
    const markers = d.events.map((event, index) => {
      const point = goldAt(event.t);
      if (!point) return '';
      const cx = x(event.t), cy = y(point.diff);
      const color = CAMP[event.killerCamp]?.color || '#7b8495';
      const shape = event.kind === 'resource'
        ? `<path d="M${cx} ${cy - 5.5} L${cx + 5.5} ${cy} L${cx} ${cy + 5.5} L${cx - 5.5} ${cy} Z" fill="${color}" stroke="#fff" stroke-width="1.2"/>`
        : `<rect x="${cx - 4.5}" y="${cy - 4.5}" width="9" height="9" rx="1.5" fill="${color}" stroke="#fff" stroke-width="1.2"/>`;
      return `<g class="pn-marker" data-pn-event="${index}" tabindex="0" role="button" aria-label="${esc(event.kind === 'resource' ? '资源事件' : '建筑事件')} ${clock(event.t)}"><title>${clock(event.t)} · ${event.kind === 'resource' ? '资源' : '建筑'} · ${esc(event.killer || '')}</title>${shape}</g>`;
    }).join('');
    pulse.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="经济差时间轴">${clips}${band}${grid}<line x1="${left}" x2="${width - right}" y1="${zero}" y2="${zero}" class="pn-zero"/>
      <path d="${area}" fill="#2f6fe4" fill-opacity=".13" clip-path="url(#pn-pos)"/>
      <path d="${area}" fill="#da6b76" fill-opacity=".13" clip-path="url(#pn-neg)"/>
      <path d="${line}" fill="none" stroke="url(#pn-line)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
      ${markers}
      <line id="pn-pulse-cursor" x1="${x(state.time)}" x2="${x(state.time)}" y1="${top}" y2="${height - bottom}" class="pn-cursor"/>
      <line id="pn-hover-line" x1="0" x2="0" y1="${top}" y2="${height - bottom}" class="pn-hover-line" visibility="hidden"/>
      <text x="${width - right}" y="${height - 10}" text-anchor="end" class="pn-axis">${clock(duration)}</text>${xTicks.join('')}
    </svg>`;
    const cursor = pulse.querySelector('#pn-pulse-cursor');
    const activeIndex = d.events.reduce((best, event, index) => {
      if (best === null) return index;
      return Math.abs(event.t - state.time) < Math.abs(d.events[best].t - state.time) ? index : best;
    }, null);
    if (activeIndex !== null && Math.abs(d.events[activeIndex].t - state.time) <= 8) {
      pulse.querySelector(`[data-pn-event="${activeIndex}"]`)?.classList.add('active');
    }
    pulse.onmousemove = event => {
      const rect = pulse.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width * width;
      const t = Math.max(0, Math.min(duration, (px - left) / Math.max(1, width - left - right) * duration));
      const lineEl = pulse.querySelector('#pn-hover-line');
      lineEl.setAttribute('x1', px); lineEl.setAttribute('x2', px); lineEl.setAttribute('visibility', 'visible');
      const point = goldAt(t);
      readout.dataset.hover = '1';
      readout.innerHTML = readoutHtml(t - t % 1, point, true);
    };
    pulse.onmouseleave = () => {
      pulse.querySelector('#pn-hover-line')?.setAttribute('visibility', 'hidden');
      readout.dataset.hover = '';
      readout.innerHTML = readoutHtml(state.time, goldAt(state.time), false);
    };
    pulse.onclick = event => {
      const marker = event.target.closest('[data-pn-event]');
      if (marker) { setTime(d.events[Number(marker.dataset.pnEvent)].t); return; }
      const rect = pulse.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width * width;
      setTime((px - left) / Math.max(1, width - left - right) * duration);
    };
    pulse.querySelectorAll('[data-pn-event]').forEach(marker => marker.onkeydown = event => {
      if (['Enter', ' '].includes(event.key)) { event.preventDefault(); setTime(d.events[Number(marker.dataset.pnEvent)].t); }
    });
    cursor.dataset.left = left; cursor.dataset.span = width - left - right;
    pulse.dataset.left = left; pulse.dataset.span = width - left - right;
    updateCursor();
  }

  function readoutHtml(t, point, hover) {
    const event = nearestEvent(t);
    const diff = point ? point.diff : null;
    return `<div class="pn-readout-time"><span>${hover ? '指针时刻' : '当前时刻'}</span><strong>${clock(t)}</strong>${point && Math.abs(point.t - t) > 1 ? `<small>经济取 ${clock(point.t)}</small>` : ''}</div>
      <div><span>蓝方经济</span><strong class="pn-blue">${num(point?.blue)}</strong></div>
      <div><span>红方经济</span><strong class="pn-red">${num(point?.red)}</strong></div>
      <div><span>经济差</span><strong class="${diff > 0 ? 'pn-blue' : diff < 0 ? 'pn-red' : ''}">${signed(diff)}</strong></div>
      <div class="pn-readout-event">${esc(eventText(event))}</div>`;
  }

  function drawRiver() {
    if (!d.events.length) { river.innerHTML = '<div class="pn-empty">本局没有官方资源/建筑事件。</div>'; return; }
    const width = Math.max(320, Math.round(river.clientWidth || 900));
    const height = 176;
    const left = 74, right = 18, top = 20, bottom = 28;
    const lanes = [
      {key: 'resource', label: '资源', y: 42},
      {key: 'structure', label: '建筑', y: 86},
      {key: 'window', label: '节奏窗', y: 132},
    ];
    const x = value => left + Number(value) / duration * (width - left - right);
    const ticks = [];
    const step = duration > 700 ? 120 : duration > 420 ? 90 : 60;
    for (let second = 0; second <= duration; second += step) ticks.push(`<line x1="${x(second)}" x2="${x(second)}" y1="${top}" y2="${height - bottom}" class="pn-grid"/><text x="${x(second)}" y="${height - 8}" text-anchor="middle" class="pn-axis">${clock(second)}</text>`);
    const laneLines = lanes.map(lane => `<line x1="${left}" x2="${width - right}" y1="${lane.y}" y2="${lane.y}" class="pn-lane"/><text x="${left - 12}" y="${lane.y + 4}" text-anchor="end" class="pn-lane-label">${lane.label}</text>`).join('');
    const markers = d.events.map((event, index) => {
      const lane = event.kind === 'resource' ? lanes[0] : lanes[1];
      const cx = x(event.t), cy = lane.y;
      const color = CAMP[event.killerCamp]?.color || '#7b8495';
      const shape = event.kind === 'resource'
        ? `<path d="M${cx} ${cy - 6} L${cx + 6} ${cy} L${cx} ${cy + 6} L${cx - 6} ${cy} Z" fill="${color}" stroke="#fff" stroke-width="1.3"/>`
        : `<rect x="${cx - 5}" y="${cy - 5}" width="10" height="10" rx="1.5" fill="${color}" stroke="#fff" stroke-width="1.3"/>`;
      return `<g class="pn-river-event" data-pn-event="${index}" tabindex="0" role="button" aria-label="${clock(event.t)} ${event.kind === 'resource' ? '资源' : '建筑'}"><title>${clock(event.t)} · ${event.kind === 'resource' ? '资源' : '建筑'} · ${esc(event.killer || '')}${event.zone ? ' · ' + event.zone : ''}</title>${shape}</g>`;
    }).join('');
    const windows = d.windows.map(window => `<rect x="${x(window.start)}" y="${lanes[2].y - 9}" width="${Math.max(3, x(window.end) - x(window.start))}" height="18" rx="9" class="pn-window"><title>${clock(window.start)}–${clock(window.end)} · ${window.events} 条事件</title></rect>`).join('');
    river.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="事件河流">${ticks}${laneLines}${windows}${markers}
      <line id="pn-river-cursor" x1="${x(state.time)}" x2="${x(state.time)}" y1="${top}" y2="${height - bottom}" class="pn-cursor"/>
    </svg>`;
    river.querySelectorAll('[data-pn-event]').forEach(marker => {
      marker.onclick = () => setTime(d.events[Number(marker.dataset.pnEvent)].t);
      marker.onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); setTime(d.events[Number(marker.dataset.pnEvent)].t); } };
    });
    river.dataset.left = left; river.dataset.span = width - left - right;
  }

  function currentPlayers() {
    if (state.player) {
      const player = byKey.get(state.player);
      return player ? [player] : [];
    }
    if (state.team === 'blue') return blue;
    if (state.team === 'red') return red;
    return [...blue, ...red];
  }

  function phaseGrid(players) {
    const grid = Array.from({length: 12}, () => Array(12).fill(0));
    for (const player of players) {
      const phases = d.positions.players[player.key]?.phases || [];
      const selected = state.phase === 'all' ? phases : phases.filter(phase => phase.key === state.phase);
      for (const phase of selected) for (let row = 0; row < 12; row += 1) for (let column = 0; column < 12; column += 1) {
        grid[row][column] += phase.heat?.[row]?.[column] || 0;
      }
    }
    return grid;
  }

  const MAP_SIZE = 460, MAP_PAD = 18;
  const mapX = x => MAP_PAD + (Number(x) + 57) / 114 * (MAP_SIZE - MAP_PAD * 2);
  const mapY = y => MAP_SIZE - MAP_PAD - (Number(y) + 57) / 114 * (MAP_SIZE - MAP_PAD * 2);
  function trailPoints() {
    if (!state.player) return [];
    return (d.positions.players[state.player]?.points || []).filter((_, index) => index % 5 === 0);
  }
  function trailProgress() {
    if (!state.player) return '';
    const player = byKey.get(state.player);
    const points = trailPoints().filter(point => point[0] <= state.time);
    if (!player || points.length < 2) return '';
    const start = player.camp === 'blue' ? [156, 194, 255] : [242, 184, 190];
    const end = player.camp === 'blue' ? [47, 111, 228] : [218, 107, 118];
    const mix = ratio => `rgb(${start.map((value, index) => Math.round(value + (end[index] - value) * ratio)).join(',')})`;
    const groups = 14;
    const size = Math.ceil(points.length / groups);
    let output = '';
    for (let group = 0; group < groups; group += 1) {
      const slice = points.slice(Math.max(0, group * size - 1), (group + 1) * size + 1);
      if (slice.length < 2) continue;
      const ratio = group / Math.max(1, groups - 1);
      const path = slice.map(([, x, y], index) => `${index ? 'L' : 'M'}${mapX(x).toFixed(1)},${mapY(y).toFixed(1)}`).join(' ');
      output += `<path d="${path}" fill="none" stroke="${mix(ratio)}" stroke-width="${(1.4 + ratio * 1.4).toFixed(2)}" stroke-opacity="${(0.3 + ratio * 0.62).toFixed(2)}" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    const first = points[0];
    return output + `<circle cx="${mapX(first[1]).toFixed(1)}" cy="${mapY(first[2]).toFixed(1)}" r="3.5" fill="#0f1a2c" stroke="${mix(0)}" stroke-width="1.5"><title>起点</title></circle>`;
  }
  function updateTrail() {
    const group = map.querySelector('#pn-trail');
    if (group) group.innerHTML = trailProgress();
  }

  function drawMap() {
    if (!d.positions.players || !Object.keys(d.positions.players).length) {
      map.innerHTML = '<div class="pn-empty">本局没有逐秒坐标，无法生成战场热区与轨迹。</div>';
      return;
    }
    const width = MAP_SIZE, height = MAP_SIZE, pad = MAP_PAD;
    const mx = mapX, my = mapY;
    const teams = state.player ? [byKey.get(state.player)?.camp]
      : state.team === 'both' ? ['blue', 'red'] : [state.team];
    const fields = teams.filter(Boolean).map(team => ({
      team,
      field: smoothGrid(phaseGrid(state.player ? [byKey.get(state.player)].filter(Boolean) : (team === 'blue' ? blue : red))),
    }));
    const heatMax = Math.max(1, ...fields.flatMap(layer => layer.field.flat()));
    const inset = (pad / width * 100).toFixed(3);
    const extent = ((width - pad * 2) / width * 100).toFixed(3);
    const heatCanvases = fields.map(layer => `<canvas class="pn-map-heat ${layer.team}" data-pn-map-heat="${layer.team}" width="256" height="256" style="left:${inset}%;top:${inset}%;width:${extent}%;height:${extent}%"></canvas>`).join('');
    const peaks = fields.map(layer => {
      let best = {row: 0, column: 0, value: 0};
      layer.field.forEach((rowData, row) => rowData.forEach((value, column) => {
        if (value > best.value) best = {row, column, value};
      }));
      if (best.value <= 0) return '';
      const cx = pad + (best.column + 0.5) / 12 * (width - pad * 2);
      const cy = height - pad - (best.row + 0.5) / 12 * (height - pad * 2);
      const color = CAMP[layer.team].color;
      return `<g class="pn-map-peak"><title>${CAMP[layer.team].label}停留峰值</title><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="${color}" stroke-opacity=".9" stroke-width="1.2"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="1.8" fill="#fff" fill-opacity=".9"/><path d="M${cx.toFixed(1)} ${(cy - 15).toFixed(1)}v4M${cx.toFixed(1)} ${(cy + 11).toFixed(1)}v4M${(cx - 15).toFixed(1)} ${cy.toFixed(1)}h4M${(cx + 11).toFixed(1)} ${cy.toFixed(1)}h4" fill="none" stroke="${color}" stroke-opacity=".7" stroke-width="1"/></g>`;
    }).join('');
    const trails = state.player ? (() => {
      const points = trailPoints();
      if (points.length < 2) return '';
      const path = points.map(([, x, y], index) => `${index ? 'L' : 'M'}${mapX(x).toFixed(1)},${mapY(y).toFixed(1)}`).join(' ');
      return `<path d="${path}" fill="none" stroke="${CAMP[byKey.get(state.player).camp].color}" stroke-width="1.1" stroke-opacity=".18" stroke-linejoin="round" stroke-linecap="round"/>`;
    })() : '';
    const eventMarkers = d.events.map((event, index) => ({event, index}))
      .filter(({event}) => event.x !== null && event.y !== null).map(({event, index}) => {
      const cx = mx(event.x), cy = my(event.y);
      const color = CAMP[event.killerCamp]?.color || '#fff';
      return `<g class="pn-map-event" data-pn-event="${index}" tabindex="0" role="button" aria-label="${clock(event.t)} 资源事件"><title>${clock(event.t)} · 资源 · ${esc(event.killer || '')}</title><path d="M${cx} ${cy - 5} L${cx + 5} ${cy} L${cx} ${cy + 5} L${cx - 5} ${cy} Z" fill="${color}" stroke="#fff" stroke-width="1.2"/></g>`;
    }).join('');
    const live = (state.player ? d.players : currentPlayers()).map(player => {
      const dot = positionAt(player.key, state.time);
      if (!dot) return '';
      return `<circle data-pn-dot="${esc(player.key)}" cx="${mx(dot[0]).toFixed(1)}" cy="${my(dot[1]).toFixed(1)}" r="${state.player === player.key ? 7 : 5}" fill="${CAMP[player.camp].color}" stroke="#fff" stroke-width="${state.player === player.key ? 2.4 : 1.5}" class="pn-live-dot"><title>${esc(player.hero || '')} · ${esc(player.nickname || '')}</title></circle>`;
    }).join('');
    const corners = [[pad, pad, 1, 1], [pad + width - pad * 2, pad, -1, 1], [pad, pad + height - pad * 2, 1, -1], [pad + width - pad * 2, pad + height - pad * 2, -1, -1]]
      .map(([x, y, dx, dy]) => `<path d="M${x} ${y + dy * 12}V${y}H${x + dx * 12}" fill="none" stroke="#8fb4ff" stroke-opacity=".3" stroke-width="1.2"/>`).join('');
    map.innerHTML = `<div class="pn-map-surface">
      <svg class="pn-map-underlay" viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs>
        <pattern id="pn-map-grid" width="35" height="35" patternUnits="userSpaceOnUse"><path d="M35 0H0V35" fill="none" stroke="#ffffff" stroke-opacity=".032"/></pattern>
        </defs>
        <rect width="${width}" height="${height}" rx="18" fill="#0d1728"/>
        <rect x="8" y="8" width="${width - 16}" height="${height - 16}" rx="14" fill="url(#pn-map-grid)" stroke="#263c5e"/>
        <path d="M${mx(-55)},${my(55)} L${mx(55)},${my(-55)}" fill="none" stroke="#3d7bb0" stroke-opacity=".075" stroke-width="54" stroke-linecap="round"/>
        <path d="M${mx(-55)},${my(55)} L${mx(55)},${my(-55)}" fill="none" stroke="#6fa8d6" stroke-opacity=".18" stroke-width="1.2" stroke-dasharray="6 8"/>
        <path d="M${mx(-45)},${my(-45)} Q${mx(-45)},${my(42)} ${mx(-6)},${my(49)} T${mx(47)},${my(45)}" fill="none" stroke="#ffffff" stroke-opacity=".035" stroke-width="8"/>
        <path d="M${mx(-45)},${my(-45)} Q${mx(42)},${my(-45)} ${mx(49)},${my(-6)} T${mx(45)},${my(47)}" fill="none" stroke="#ffffff" stroke-opacity=".035" stroke-width="8"/>
        <path d="M${mx(-45)},${my(-45)} L${mx(45)},${my(45)}" stroke="#ffffff" stroke-opacity=".035" stroke-width="8"/>
        ${corners}
        <circle cx="${mx(-48)}" cy="${my(-48)}" r="14" fill="#2f6fe4" fill-opacity=".16" stroke="#2f6fe4" stroke-opacity=".4"/>
        <circle cx="${mx(48)}" cy="${my(48)}" r="14" fill="#da6b76" fill-opacity=".16" stroke="#da6b76" stroke-opacity=".4"/>
        <text x="${mx(-48)}" y="${my(-48) + 4}" text-anchor="middle" class="pn-map-base">蓝</text>
        <text x="${mx(48)}" y="${my(48) + 4}" text-anchor="middle" class="pn-map-base">红</text>
      </svg>
      ${heatCanvases}
      <svg class="pn-map-overlay" viewBox="0 0 ${width} ${height}" role="group" aria-label="战场热区与走位">
        ${peaks}
        <g id="pn-trail">${trails}</g>
        <g id="pn-map-events">${eventMarkers}</g>
        <g id="pn-live">${live}</g>
      </svg>
      <div class="pn-map-key"><span>停留密度</span><i class="blue"></i><i class="red"></i><span>少 → 多</span></div>
    </div><div class="pn-map-clock" id="pn-map-clock">${clock(state.time)}</div>`;
    fields.forEach(layer => {
      const canvas = map.querySelector(`canvas[data-pn-map-heat="${layer.team}"]`);
      if (canvas) paintCampHeat(canvas, layer.field, heatMax, layer.team);
    });
    map.querySelectorAll('[data-pn-event]').forEach(marker => {
      marker.onclick = () => setTime(d.events[Number(marker.dataset.pnEvent)].t);
    });
    updateTrail();
  }

  function positionAt(key, time) {
    const points = d.positions.players[key]?.points || [];
    if (!points.length) return null;
    const step = d.positions.step || 2;
    const index = Math.max(0, Math.min(points.length - 1, Math.round(time / step)));
    let best = points[index];
    for (let cursor = Math.max(0, index - 1); cursor <= Math.min(points.length - 1, index + 1); cursor += 1) {
      if (Math.abs(points[cursor][0] - time) < Math.abs(best[0] - time)) best = points[cursor];
    }
    return [best[1], best[2]];
  }

  let lastTick = -1;
  function updateCursor() {
    const cursor = pulse.querySelector('#pn-pulse-cursor');
    if (cursor) {
      const left = Number(pulse.dataset.left || 0), span = Number(pulse.dataset.span || 1);
      const x = left + state.time / duration * span;
      cursor.setAttribute('x1', x); cursor.setAttribute('x2', x);
    }
    const riverCursor = river.querySelector('#pn-river-cursor');
    if (riverCursor) {
      const left = Number(river.dataset.left || 0), span = Number(river.dataset.span || 1);
      const x = left + state.time / duration * span;
      riverCursor.setAttribute('x1', x); riverCursor.setAttribute('x2', x);
    }
    const tick = Math.round(state.time);
    if (document.activeElement !== timeInput) timeInput.value = String(tick);
    timeLabel.textContent = clock(state.time);
    const mapClock = map.querySelector('#pn-map-clock');
    if (mapClock) mapClock.textContent = clock(state.time);
    // 拖动时按整秒做重操作（轨迹重绘/读数重建），避免每帧重建 SVG 造成抖动
    if (tick !== lastTick) {
      lastTick = tick;
      updateTrail();
      readout.innerHTML = readoutHtml(state.time, goldAt(state.time), false);
    }
    for (const player of d.players) {
      const dot = positionAt(player.key, state.time);
      if (!dot) continue;
      const node = map.querySelector(`[data-pn-dot="${CSS.escape(player.key)}"]`);
      if (!node) continue;
      const width = 460, pad = 18;
      node.setAttribute('cx', (pad + (dot[0] + 57) / 114 * (width - pad * 2)).toFixed(1));
      node.setAttribute('cy', (width - pad - (dot[1] + 57) / 114 * (width - pad * 2)).toFixed(1));
    }
  }

  function sideEvents() {
    const recent = d.events.slice(-4).reverse();
    if (!recent.length) return '';
    return `<div class="pn-side-events"><span class="pn-side-sub">末段事件（全场）</span>${recent.map(event => `<button data-pn-time="${event.t}"><i class="${event.killerCamp}"></i><b>${clock(event.t)}</b><span>${event.kind === 'resource' ? '资源' : '建筑'} · ${esc(event.killer || '')}</span></button>`).join('')}</div>`;
  }

  function mapStatsHtml() {
    const player = state.player ? byKey.get(state.player) : null;
    if (player) {
      const phases = d.positions.players[player.key]?.phases || [];
      const selected = state.phase === 'all' ? phases : phases.filter(phase => phase.key === state.phase);
      const weight = selected.reduce((total, phase) => total + (phase.n || 0), 0) || 1;
      const enemy = selected.reduce((total, phase) => total + (phase.enemyShare || 0) * (phase.n || 0), 0) / weight;
      const advance = Math.max(...selected.map(phase => phase.advanceMax || 0), 0);
      const avgX = selected.reduce((total, phase) => total + (phase.avgX || 0) * (phase.n || 0), 0) / weight;
      const avgY = selected.reduce((total, phase) => total + (phase.avgY || 0) * (phase.n || 0), 0) / weight;
      return `<div class="pn-side-title"><span class="pn-dot ${player.camp}"></span><div><strong>${esc(player.hero || '')}</strong><small>${esc(player.nickname || '')}</small></div></div>
        <div class="pn-side-grid">
          <div><span>累计位移</span><strong>${num(d.positions.players[player.key]?.distance)}</strong><small>网格单位</small></div>
          <div><span>最深推进</span><strong>${advance ? `${num(advance * 100)}%` : '—'}</strong><small>向敌方半区</small></div>
          <div><span>敌方半区停留</span><strong>${pct(enemy)}</strong><small>排除静止样本</small></div>
          <div><span>活动中心</span><strong>${num(avgX)}, ${num(avgY)}</strong><small>地图坐标</small></div>
        </div>
        ${sideEvents()}<p class="pn-side-note">点击十人面板中的选手可切换；轨迹按 4 秒采样绘制，热区按 2 秒坐标聚合。</p>`;
    }
    const team = state.team === 'both' ? null : state.team;
    if (team) {
      const phase = state.phase === 'all' ? null : d.phases.find(item => item.key === state.phase);
      const metrics = phase?.team?.[team] || d.positions.team?.[team] || {};
      const players = team === 'blue' ? blue : red;
      const distance = players.reduce((total, player) => total + (d.positions.players[player.key]?.distance || 0), 0);
      return `<div class="pn-side-title"><span class="pn-dot ${team}"></span><div><strong>${CAMP[team].label}全队</strong><small>${state.phase === 'all' ? '全场' : phase?.label || ''}</small></div></div>
        <div class="pn-side-grid">
          <div><span>四人以上同屏</span><strong>${pct(metrics.closeRate)}</strong><small>距队伍中心 22 格内</small></div>
          <div><span>敌方半区停留</span><strong>${pct(metrics.enemyHalfRate)}</strong><small>全队平均占比</small></div>
          <div><span>五人累计位移</span><strong>${num(distance)}</strong><small>网格单位</small></div>
          <div><span>活动半径</span><strong>${num(metrics.centroidDistance, 1)}</strong><small>队伍中心距地图中心</small></div>
        </div>
        ${sideEvents()}<p class="pn-side-note">选择具体选手可查看个人热区、最深推进与轨迹；拖动时间轴可回放十人位置。</p>`;
    }
    const phase = state.phase === 'all' ? null : d.phases.find(item => item.key === state.phase);
    const blueMetrics = phase?.team?.blue || d.positions.team?.blue || {};
    const redMetrics = phase?.team?.red || d.positions.team?.red || {};
    return `<div class="pn-side-title"><span class="pn-dot"></span><div><strong>双方对比</strong><small>${phase?.label || '全场'}</small></div></div>
      <div class="pn-side-grid">
        <div><span>蓝方同屏率</span><strong>${pct(blueMetrics.closeRate)}</strong><small>至少四人</small></div>
        <div><span>红方同屏率</span><strong>${pct(redMetrics.closeRate)}</strong><small>至少四人</small></div>
        <div><span>蓝方入侵率</span><strong>${pct(blueMetrics.enemyHalfRate)}</strong><small>敌方半区停留</small></div>
        <div><span>红方入侵率</span><strong>${pct(redMetrics.enemyHalfRate)}</strong><small>敌方半区停留</small></div>
      </div>
      ${sideEvents()}<p class="pn-side-note">热区越亮表示停留越久；选中个人后才显示轨迹。资源事件带坐标，建筑事件没有坐标，只出现在时间轴。</p>`;
  }

  function heatGridFor(player) {
    const phases = d.positions.players[player.key]?.phases || [];
    const selected = state.phase === 'all' ? phases : phases.filter(phase => phase.key === state.phase);
    const grid = Array.from({length: 12}, () => Array(12).fill(0));
    for (const phase of selected) for (let row = 0; row < 12; row += 1) for (let column = 0; column < 12; column += 1) {
      grid[row][column] += phase.heat?.[row]?.[column] || 0;
    }
    return grid;
  }

  function playerPhaseStats(player) {
    const phases = d.positions.players[player.key]?.phases || [];
    const selected = state.phase === 'all' ? phases : phases.filter(phase => phase.key === state.phase);
    const weight = selected.reduce((total, phase) => total + (phase.n || 0), 0) || 1;
    return {
      enemy: selected.reduce((total, phase) => total + (phase.enemyShare || 0) * (phase.n || 0), 0) / weight,
      advance: Math.max(...selected.map(phase => phase.advanceMax || 0), 0),
      distance: d.positions.players[player.key]?.distance || 0,
      avgX: selected.reduce((total, phase) => total + (phase.avgX || 0) * (phase.n || 0), 0) / weight,
      avgY: selected.reduce((total, phase) => total + (phase.avgY || 0) * (phase.n || 0), 0) / weight,
    };
  }

  const HEAT_RAMP = [
    [0, [16, 24, 52, 0]],
    [0.16, [58, 32, 96, 40]],
    [0.36, [132, 42, 128, 118]],
    [0.56, [214, 70, 100, 205]],
    [0.76, [250, 150, 78, 235]],
    [1, [255, 248, 214, 255]],
  ];
  const CAMP_RAMP = {
    blue: [
      [0, [8, 16, 36, 0]], [0.14, [22, 52, 104, 14]], [0.36, [34, 96, 184, 82]],
      [0.62, [62, 152, 234, 168]], [0.84, [126, 208, 252, 212]], [1, [178, 230, 255, 228]],
    ],
    red: [
      [0, [12, 12, 32, 0]], [0.14, [88, 30, 60, 14]], [0.36, [160, 48, 78, 82]],
      [0.62, [220, 80, 94, 168]], [0.84, [248, 142, 104, 212]], [1, [255, 200, 152, 228]],
    ],
  };
  function rampColor(ramp, t) {
    const value = Math.max(0, Math.min(1, t));
    for (let i = 1; i < ramp.length; i += 1) {
      const [start, from] = ramp[i - 1];
      const [end, to] = ramp[i];
      if (value <= end) {
        const ratio = (value - start) / (end - start || 1);
        return from.map((channel, j) => Math.round(channel + (to[j] - channel) * ratio));
      }
    }
    return ramp.at(-1)[1];
  }
  const heatColor = t => rampColor(HEAT_RAMP, t);
  const HEAT_LUT = Array.from({length: 256}, (_, index) => heatColor(index / 255));
  const CAMP_LUT = {
    blue: Array.from({length: 256}, (_, index) => rampColor(CAMP_RAMP.blue, index / 255)),
    red: Array.from({length: 256}, (_, index) => rampColor(CAMP_RAMP.red, index / 255)),
  };
  function paintCampHeat(canvas, field, max, tone) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = canvas.width, height = canvas.height, size = field.length;
    const image = ctx.createImageData(width, height), data = image.data;
    const lut = CAMP_LUT[tone];
    for (let py = 0; py < height; py += 1) {
      const gy = (1 - (py + 0.5) / height) * size - 0.5;
      for (let px = 0; px < width; px += 1) {
        const gx = ((px + 0.5) / width) * size - 0.5;
        let t = Math.pow(Math.max(0, bilinear(field, gx, gy)) / max, 1.12);
        t = Math.max(0, Math.min(1, (t - 0.13) / 0.87));
        const color = lut[Math.round(t * 255)];
        const offset = (py * width + px) * 4;
        data[offset] = color[0];
        data[offset + 1] = color[1];
        data[offset + 2] = color[2];
        data[offset + 3] = color[3];
      }
    }
    ctx.putImageData(image, 0, 0);
  }
  function smoothGrid(grid) {
    const size = grid.length;
    const kernel = [1, 2, 1];
    const output = Array.from({length: size}, () => Array(size).fill(0));
    for (let row = 0; row < size; row += 1) for (let column = 0; column < size; column += 1) {
      let sum = 0, weight = 0;
      for (let dr = -1; dr <= 1; dr += 1) for (let dc = -1; dc <= 1; dc += 1) {
        const r = row + dr, c = column + dc;
        if (r < 0 || r >= size || c < 0 || c >= size) continue;
        const w = kernel[dr + 1] * kernel[dc + 1];
        sum += grid[r][c] * w;
        weight += w;
      }
      output[row][column] = sum / (weight || 1);
    }
    return output;
  }
  function bilinear(field, gx, gy) {
    const size = field.length;
    const x = Math.max(0, Math.min(size - 1, gx));
    const y = Math.max(0, Math.min(size - 1, gy));
    const x0 = Math.floor(x), y0 = Math.floor(y);
    const x1 = Math.min(size - 1, x0 + 1), y1 = Math.min(size - 1, y0 + 1);
    const fx = x - x0, fy = y - y0;
    const top = field[y0][x0] * (1 - fx) + field[y0][x1] * fx;
    const bottom = field[y1][x0] * (1 - fx) + field[y1][x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }
  function paintHeat(canvas, field, max) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = canvas.width, height = canvas.height, size = field.length;
    const image = ctx.createImageData(width, height);
    const data = image.data;
    for (let py = 0; py < height; py += 1) {
      const gy = (1 - (py + 0.5) / height) * size - 0.5;
      for (let px = 0; px < width; px += 1) {
        const gx = ((px + 0.5) / width) * size - 0.5;
        let t = Math.pow(Math.max(0, bilinear(field, gx, gy)) / max, 0.82);
        t = Math.max(0, Math.min(1, (t - 0.085) / 0.915));
        const color = HEAT_LUT[Math.round(t * 255)];
        const offset = (py * width + px) * 4;
        data[offset] = color[0];
        data[offset + 1] = color[1];
        data[offset + 2] = color[2];
        data[offset + 3] = color[3];
      }
    }
    ctx.putImageData(image, 0, 0);
  }
  function miniHeatSvg(player, index) {
    const span = MAP_SIZE - MAP_PAD * 2;
    const inset = (MAP_PAD / MAP_SIZE * 100).toFixed(3);
    const extent = (span / MAP_SIZE * 100).toFixed(3);
    const stats = playerPhaseStats(player);
    const unit = span / 6;
    const gridLines = Array.from({length: 7}, (_, i) => {
      const p = (MAP_PAD + i * unit).toFixed(1);
      return `<path d="M${p} ${MAP_PAD}V${MAP_PAD + span}M${MAP_PAD} ${p}H${MAP_PAD + span}" fill="none" stroke="#ffffff" stroke-opacity=".035" stroke-width="1"/>`;
    }).join('');
    const corners = [[MAP_PAD, MAP_PAD, 1, 1], [MAP_PAD + span, MAP_PAD, -1, 1], [MAP_PAD, MAP_PAD + span, 1, -1], [MAP_PAD + span, MAP_PAD + span, -1, -1]]
      .map(([x, y, dx, dy]) => `<path d="M${x} ${y + dy * 10}V${y}H${x + dx * 10}" fill="none" stroke="#8fb4ff" stroke-opacity=".38" stroke-width="1.2"/>`).join('');
    const cx = mapX(stats.avgX).toFixed(1), cy = mapY(stats.avgY).toFixed(1);
    const cross = `<g><title>平均位置</title><circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="#ffffff" stroke-opacity=".8" stroke-width="1"/><circle cx="${cx}" cy="${cy}" r="1.8" fill="#ffffff"/><path d="M${cx} ${Number(cy) - 15}v4M${cx} ${Number(cy) + 11}v4M${Number(cx) - 15} ${cy}h4M${Number(cx) + 11} ${cy}h4" fill="none" stroke="#ffffff" stroke-opacity=".7" stroke-width="1"/></g>`;
    return `<span class="pn-heat-map" role="img" aria-label="${esc(player.hero || '')} 位置热区">
      <svg class="pn-heat-base" viewBox="0 0 ${MAP_SIZE} ${MAP_SIZE}" aria-hidden="true">
        <rect width="${MAP_SIZE}" height="${MAP_SIZE}" rx="18" fill="#0d1728"/>
        <path d="M${mapX(-55).toFixed(1)},${mapY(55).toFixed(1)} L${mapX(55).toFixed(1)},${mapY(-55).toFixed(1)}" stroke="#3d7bb0" stroke-opacity=".07" stroke-width="46" stroke-linecap="round"/>
        <path d="M${mapX(-45).toFixed(1)},${mapY(-45).toFixed(1)} L${mapX(45).toFixed(1)},${mapY(45).toFixed(1)}" stroke="#ffffff" stroke-opacity=".045" stroke-width="9"/>
        <path d="M${mapX(-45).toFixed(1)},${mapY(-45).toFixed(1)} Q${mapX(-45).toFixed(1)},${mapY(42).toFixed(1)} ${mapX(-6).toFixed(1)},${mapY(49).toFixed(1)} T${mapX(47).toFixed(1)},${mapY(45).toFixed(1)}" fill="none" stroke="#ffffff" stroke-opacity=".04" stroke-width="8"/>
        <path d="M${mapX(-45).toFixed(1)},${mapY(-45).toFixed(1)} Q${mapX(42).toFixed(1)},${mapY(-45).toFixed(1)} ${mapX(49).toFixed(1)},${mapY(-6).toFixed(1)} T${mapX(45).toFixed(1)},${mapY(47).toFixed(1)}" fill="none" stroke="#ffffff" stroke-opacity=".04" stroke-width="8"/>
        ${gridLines}
        <rect x="${MAP_PAD}" y="${MAP_PAD}" width="${span}" height="${span}" fill="none" stroke="#ffffff" stroke-opacity=".09" stroke-width="1"/>
        ${corners}
        <circle cx="${mapX(-48).toFixed(1)}" cy="${mapY(-48).toFixed(1)}" r="8" fill="#2f6fe4" fill-opacity=".14" stroke="#2f6fe4" stroke-opacity=".55" stroke-width="1"/>
        <circle cx="${mapX(48).toFixed(1)}" cy="${mapY(48).toFixed(1)}" r="8" fill="#da6b76" fill-opacity=".14" stroke="#da6b76" stroke-opacity=".55" stroke-width="1"/>
      </svg>
      <canvas class="pn-heat-canvas" width="160" height="160" data-pn-heat-idx="${index}" style="left:${inset}%;top:${inset}%;width:${extent}%;height:${extent}%"></canvas>
      <svg class="pn-heat-overlay" viewBox="0 0 ${MAP_SIZE} ${MAP_SIZE}" aria-hidden="true">${cross}</svg>
    </span>`;
  }

  function renderHeatGrid() {
    const box = root.querySelector('#pn-heat-grid');
    const legend = root.querySelector('#pn-heat-legend');
    if (!box) return;
    const empty = '<div class="pn-empty">本局没有逐秒坐标，无法生成十人热区。</div>';
    const blank = () => {
      box.innerHTML = empty;
      if (legend) legend.innerHTML = '';
    };
    if (!d.positions.players || !Object.keys(d.positions.players).length) return blank();
    const entries = d.players
      .filter(player => (d.positions.players[player.key]?.points || []).length)
      .map(player => ({player, grid: heatGridFor(player)}));
    if (!entries.length) return blank();
    const fields = entries.map(({grid}) => smoothGrid(grid));
    const max = Math.max(1, ...fields.flatMap(field => field.flat()));
    if (legend) {
      legend.innerHTML = `<span class="pn-heat-legend-label">停留时长</span>
        <span class="pn-heat-legend-end">少</span>
        <span class="pn-heat-legend-bar" aria-hidden="true"></span>
        <span class="pn-heat-legend-end">多</span>
        <span class="pn-heat-legend-scale">全局统一标尺 · 峰值 ${num(max, 1)} 采样点，10 张图不各自归一化</span>
        <span class="pn-heat-legend-note">颜色只表示停留，阵营看卡片右上角色点</span>`;
    }
    box.innerHTML = entries.map(({player}, index) => {
      const stats = playerPhaseStats(player);
      const active = state.player === player.key;
      const peak = Math.max(0, ...fields[index].flat());
      const share = Math.max(0, Math.min(100, Number(stats.enemy) * 100 || 0));
      return `<button class="pn-heat-tile ${player.camp}${active ? ' active' : ''}" data-pn-heat-player="${esc(player.key)}" aria-pressed="${active}" title="在主地图查看 ${esc(player.nickname || player.hero)} 的轨迹">
        <span class="pn-heat-head"><span class="pn-heat-icon">${heroIcon(player)}</span><span class="pn-heat-name"><b>${esc(player.hero || '')}</b><small>${esc(player.nickname || '')}</small></span><i class="pn-heat-camp ${player.camp}"></i></span>
        ${miniHeatSvg(player, index)}
        <span class="pn-heat-metric"><span>敌方半区</span><b>${pct(stats.enemy)}</b><i class="pn-heat-bar"><em style="width:${share.toFixed(1)}%"></em></i></span>
        <span class="pn-heat-sub"><span>位移 <b>${num(stats.distance)}</b></span><span>最深 <b>${stats.advance ? `${num(stats.advance * 100)}%` : '—'}</b></span><span>峰值 <b>${num(peak, 1)}</b></span></span>
      </button>`;
    }).join('');
    box.querySelectorAll('canvas[data-pn-heat-idx]').forEach(canvas => {
      const index = Number(canvas.dataset.pnHeatIdx);
      if (fields[index]) paintHeat(canvas, fields[index], max);
    });
    box.querySelectorAll('[data-pn-heat-player]').forEach(button => button.onclick = () => selectPlayer(button.dataset.pnHeatPlayer));
  }

  const DUEL_TONES = {
    gold: {line: '#e8b45c', ramp: [
      [0, [146, 106, 48, 0.3]], [0.3, [196, 143, 62, 0.66]],
      [0.65, [238, 184, 86, 0.9]], [1, [255, 233, 173, 1]],
    ]},
    teal: {line: '#4ec9c1', ramp: [
      [0, [38, 108, 112, 0.3]], [0.3, [52, 162, 162, 0.66]],
      [0.65, [88, 211, 202, 0.9]], [1, [212, 255, 247, 1]],
    ]},
  };
  const DEEP_RATIO = 0.35;
  function duelColor(tone, t) {
    const ramp = DUEL_TONES[tone].ramp;
    const value = Math.max(0, Math.min(1, t));
    for (let i = 1; i < ramp.length; i += 1) {
      const [start, from] = ramp[i - 1], [end, to] = ramp[i];
      if (value <= end) {
        const ratio = (value - start) / (end - start || 1);
        return from.map((channel, j) => j === 3
          ? (channel + (to[j] - channel) * ratio).toFixed(3)
          : Math.round(channel + (to[j] - channel) * ratio));
      }
    }
    return ramp.at(-1)[1];
  }
  function mirroredGrid(heat, camp) {
    const grid = Array.from({length: 12}, (_, row) => Array.from({length: 12}, (_, column) => heat?.[row]?.[column] || 0));
    if (camp !== 'red') return grid;
    return grid.map((_, index) => [...grid[11 - index]].reverse());
  }
  function deepSeconds(grid, step) {
    const bounds = d.positions.bounds || [-57, 57];
    const min = Number(bounds[0]), span = Number(bounds[1]) - min;
    let count = 0;
    for (let row = 0; row < 12; row += 1) for (let column = 0; column < 12; column += 1) {
      const x = min + (column + 0.5) / 12 * span;
      const y = min + (row + 0.5) / 12 * span;
      if ((x + y) / span > DEEP_RATIO) count += grid[row][column];
    }
    return count * step;
  }
  function duelMapSvg(grid, max, step, tone) {
    const span = MAP_SIZE - MAP_PAD * 2;
    const cell = span / 12;
    const bounds = d.positions.bounds || [-57, 57];
    const lo = Number(bounds[0]), hi = Number(bounds[1]), extent = hi - lo;
    const cut = DEEP_RATIO * extent;
    const edge = cut - hi;
    const voxels = [];
    for (let row = 0; row < 12; row += 1) for (let column = 0; column < 12; column += 1) {
      const value = grid[row][column];
      if (!value) continue;
      const [r, g, b, a] = duelColor(tone, Math.pow(Math.min(1, value / max), 0.68));
      const x = MAP_PAD + column * cell + 0.6;
      const y = MAP_PAD + (11 - row) * cell + 0.6;
      voxels.push(`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(cell - 1.2).toFixed(1)}" height="${(cell - 1.2).toFixed(1)}" rx="1.5" fill="rgb(${r},${g},${b})" fill-opacity="${a}"><title>${value * step} 秒</title></rect>`);
    }
    const gridLines = Array.from({length: 13}, (_, index) => {
      const p = (MAP_PAD + index * cell).toFixed(1);
      return `<path d="M${p} ${MAP_PAD}V${MAP_PAD + span}M${MAP_PAD} ${p}H${MAP_PAD + span}" fill="none" stroke="#ffffff" stroke-opacity=".035" stroke-width="1"/>`;
    }).join('');
    const corners = [[MAP_PAD, MAP_PAD, 1, 1], [MAP_PAD + span, MAP_PAD, -1, 1], [MAP_PAD, MAP_PAD + span, 1, -1], [MAP_PAD + span, MAP_PAD + span, -1, -1]]
      .map(([x, y, dx, dy]) => `<path d="M${x} ${y + dy * 10}V${y}H${x + dx * 10}" fill="none" stroke="#8fb4ff" stroke-opacity=".3" stroke-width="1.2"/>`).join('');
    const deepPoly = [[edge, hi], [hi, hi], [hi, edge]]
      .map(([x, y]) => `${mapX(x).toFixed(1)},${mapY(y).toFixed(1)}`).join(' ');
    const deepLine = `M${mapX(edge).toFixed(1)},${mapY(hi).toFixed(1)} L${mapX(hi).toFixed(1)},${mapY(edge).toFixed(1)}`;
    return `<svg viewBox="0 0 ${MAP_SIZE} ${MAP_SIZE}" role="img" aria-label="对位分布：己方出生角在左下，右上为对侧深区">
      <rect width="${MAP_SIZE}" height="${MAP_SIZE}" rx="14" fill="#0c1728"/>
      <polygon points="${deepPoly}" fill="${DUEL_TONES[tone].line}" fill-opacity=".085"/>
      <path d="M${mapX(lo).toFixed(1)},${mapY(hi).toFixed(1)} L${mapX(hi).toFixed(1)},${mapY(lo).toFixed(1)}" stroke="#3d7bb0" stroke-opacity=".075" stroke-width="38" stroke-linecap="round"/>
      ${gridLines}
      <rect x="${MAP_PAD}" y="${MAP_PAD}" width="${span}" height="${span}" fill="none" stroke="#ffffff" stroke-opacity=".09" stroke-width="1"/>
      ${corners}
      <path d="${deepLine}" fill="none" stroke="${DUEL_TONES[tone].line}" stroke-opacity=".8" stroke-width="1.8" stroke-dasharray="7 5"/>
      ${voxels.join('')}
      <circle cx="${mapX(-48).toFixed(1)}" cy="${mapY(-48).toFixed(1)}" r="6.5" fill="${DUEL_TONES[tone].line}" fill-opacity=".9" stroke="#0c1728" stroke-width="2"><title>己方出生角</title></circle>
      <circle cx="${mapX(48).toFixed(1)}" cy="${mapY(48).toFixed(1)}" r="6.5" fill="none" stroke="#ffffff" stroke-opacity=".75" stroke-width="1.6"><title>对侧出生角</title></circle>
    </svg>`;
  }

  function renderDuel() {
    const box = root.querySelector('#pn-duel');
    const title = root.querySelector('#pn-duel-title');
    const foot = root.querySelector('#pn-duel-foot');
    const blueSelect = root.querySelector('#pn-duel-blue');
    const redSelect = root.querySelector('#pn-duel-red');
    if (!box || !title || !foot || !blueSelect || !redSelect) return;
    const picks = [byKey.get(blueSelect.value), byKey.get(redSelect.value)];
    const step = Number(d.positions.step) || 2;
    const phases = d.phases || [];
    if (picks.some(player => !player) || !phases.length || !Object.keys(d.positions.players || {}).length) {
      box.innerHTML = '<div class="pn-empty">本局没有逐秒坐标，无法生成对位分布。</div>';
      title.textContent = '对位分布';
      foot.innerHTML = '';
      return;
    }
    const sides = picks.map((player, index) => {
      const tone = index === 0 ? 'gold' : 'teal';
      const playerPhases = d.positions.players[player.key]?.phases || [];
      const cells = phases.map((phase, phaseIndex) => {
        const source = playerPhases.find(item => item.key === phase.key) || playerPhases[phaseIndex] || {};
        const grid = mirroredGrid(source.heat, player.camp);
        return {phase, grid, seconds: deepSeconds(grid, step), peak: Math.max(0, ...grid.flat())};
      });
      return {player, tone, cells};
    });
    const maxPeak = Math.max(1, ...sides.flatMap(side => side.cells.map(cell => cell.peak)));
    if (!sides.some(side => side.cells.some(cell => cell.grid.some(row => row.some(Boolean))))) {
      box.innerHTML = '<div class="pn-empty">这两名选手没有逐秒坐标，无法生成对位分布。</div>';
      title.textContent = '对位分布';
      foot.innerHTML = '';
      return;
    }
    const late = phases.at(-1);
    const last = sides.map(side => side.cells.at(-1)?.seconds || 0);
    if (!last[0] && !last[1]) title.textContent = `两人${late.label}均未进入对侧深区`;
    else if (Math.abs(last[0] - last[1]) <= 4) title.textContent = `${sides[0].player.hero} 与 ${sides[1].player.hero} ${late.label}对侧深区停留接近：${num(last[0])} / ${num(last[1])} 秒`;
    else {
      const top = last[0] > last[1] ? 0 : 1, low = 1 - top;
      title.textContent = `${sides[top].player.hero} ${late.label}在对侧深区 ${num(last[top])} 秒，${sides[low].player.hero} ${num(last[low])} 秒`;
    }
    box.innerHTML = sides.map(side => {
      const total = side.cells.reduce((sum, cell) => sum + cell.seconds, 0);
      return `<div class="pn-duel-side ${side.tone}">
        <div class="pn-duel-side-head">
          <span class="pn-heat-icon">${heroIcon(side.player)}</span>
          <span class="pn-duel-name"><b>${esc(side.player.hero || '')}</b><small>${esc(side.player.nickname || '')} · ${CAMP[side.player.camp].label}</small></span>
          <span class="pn-duel-total">全场深区 <b>${num(total)}</b> 秒</span>
        </div>
        <div class="pn-duel-phases">${side.cells.map(cell => {
          const active = state.player === side.player.key && state.phase === cell.phase.key;
          return `<button class="pn-duel-cell${active ? ' active' : ''}" data-pn-duel-player="${esc(side.player.key)}" data-pn-duel-phase="${esc(cell.phase.key)}" aria-pressed="${active}" title="在主地图查看 ${esc(side.player.hero || '')} 的${esc(cell.phase.label)}轨迹">
            <span class="pn-duel-phase"><b>${esc(cell.phase.label)}</b><small>${clock(cell.phase.from)}–${clock(cell.phase.to)} · 时长 ${clock((cell.phase.to || 0) - (cell.phase.from || 0))}</small></span>
            <span class="pn-duel-map">${duelMapSvg(cell.grid, maxPeak, step, side.tone)}</span>
            <span class="pn-duel-value${cell.seconds ? '' : ' zero'}">${num(cell.seconds)}<small>秒</small></span>
            <span class="pn-duel-value-label">对侧深区停留</span>
          </button>`;
        }).join('')}</div>
      </div>`;
    }).join('');
    const bounds = d.positions.bounds || [-57, 57];
    foot.innerHTML = `<div class="pn-duel-legend">
        <span class="pn-heat-legend-label">停留密度</span>
        <span class="pn-heat-legend-end">少</span>
        <span class="pn-duel-legend-bars"><i class="gold"></i><i class="teal"></i></span>
        <span class="pn-heat-legend-end">多</span>
        <span class="pn-duel-legend-deep"><i></i>虚线右上为对侧深区</span>
        <span class="pn-heat-legend-scale">六图共用标尺 · 峰值 ${num(maxPeak)} 采样点（${num(maxPeak * step)} 秒）· 色相区分对位双方，亮度表示停留密度</span>
      </div>
      <p class="pn-duel-note">每格为地图 1/12 宽度 · 实心点为己方出生角、空心点为对侧 · 对侧深区 = 推进深度 &gt; ${Math.round(DEEP_RATIO * 100)}%（x+y &gt; ${num(DEEP_RATIO * (Number(bounds[1]) - Number(bounds[0])), 0)} 网格单位）· 红方坐标已 180° 镜像，双方己方出生角统一在左下 · 每采样点 ${step} 秒，阵亡等待与静止样本已排除</p>`;
    box.querySelectorAll('[data-pn-duel-player]').forEach(button => button.onclick = () => {
      const key = button.dataset.pnDuelPlayer, phase = button.dataset.pnDuelPhase;
      const player = byKey.get(key);
      if (!player) return;
      state.player = key;
      state.team = player.camp;
      state.phase = phase;
      playerSelect.value = key;
      root.querySelectorAll('[data-pn-phase] button').forEach(item => item.classList.toggle('active', item.dataset.phase === phase));
      root.querySelectorAll('[data-pn-card]').forEach(card => card.classList.toggle('active', card.dataset.pnCard === key));
      drawMap();
      mapSide.innerHTML = mapStatsHtml();
      renderHeatGrid();
      renderDuel();
      document.getElementById('pn-map-card')?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
    });
  }

  function selectPlayer(key) {
    const player = byKey.get(key);
    if (!player) return;
    state.player = state.player === player.key ? '' : player.key;
    if (state.player) state.team = player.camp;
    playerSelect.value = state.player;
    root.querySelectorAll('[data-pn-card]').forEach(card => card.classList.toggle('active', card.dataset.pnCard === state.player));
    drawMap();
    mapSide.innerHTML = mapStatsHtml();
    renderHeatGrid();
    renderDuel();
    if (state.player) {
      document.getElementById('pn-map-card')?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
    }
  }

  function setPhase(phase) {
    state.phase = phase;
    root.querySelectorAll('[data-pn-phase] button').forEach(item => item.classList.toggle('active', item.dataset.phase === phase));
    drawMap();
    mapSide.innerHTML = mapStatsHtml();
    renderHeatGrid();
    renderDuel();
  }

  function drawAll() {
    drawPulse();
    drawRiver();
    drawMap();
    mapSide.innerHTML = mapStatsHtml();
    renderHeatGrid();
    renderDuel();
    updateCursor();
  }

  function setTime(value) {
    state.time = Math.max(0, Math.min(duration, Number(value) || 0));
    updateCursor();
  }

  function pause() {
    state.playing = false;
    if (timer) clearInterval(timer);
    timer = null;
    playButton.textContent = '播放';
  }

  function play() {
    if (state.playing) { pause(); return; }
    if (state.time >= duration) state.time = 0;
    state.playing = true;
    playButton.textContent = '暂停';
    timer = setInterval(() => {
      if (!root.isConnected || !root.querySelector('.panorama')) { pause(); return; }
      const next = state.time + state.speed * 0.2;
      if (next >= duration) { setTime(duration); pause(); return; }
      setTime(next);
    }, 200);
  }

  root.querySelectorAll('.pn-insight[data-pn-time]').forEach(button => button.onclick = () => {
    setTime(Number(button.dataset.pnTime));
    root.querySelector('.pn-pulse-card')?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
  });
  root.querySelectorAll('[data-pn-player]').forEach(button => button.onclick = () => selectPlayer(button.dataset.pnPlayer));
  root.querySelectorAll('[data-pn-team] button').forEach(button => button.onclick = () => {
    state.team = button.dataset.team; state.player = ''; playerSelect.value = '';
    root.querySelectorAll('[data-pn-team] button').forEach(item => item.classList.toggle('active', item === button));
    root.querySelectorAll('[data-pn-card]').forEach(card => card.classList.remove('active'));
    drawMap(); mapSide.innerHTML = mapStatsHtml(); renderHeatGrid(); renderDuel();
  });
  root.querySelectorAll('[data-pn-phase] button').forEach(button => button.onclick = () => setPhase(button.dataset.phase));
  [root.querySelector('#pn-duel-blue'), root.querySelector('#pn-duel-red')].forEach(select => {
    if (select) select.onchange = () => renderDuel();
  });
  playerSelect.onchange = () => {
    if (!playerSelect.value) {
      state.player = '';
      root.querySelectorAll('[data-pn-card]').forEach(card => card.classList.remove('active'));
      drawMap(); mapSide.innerHTML = mapStatsHtml(); renderHeatGrid(); renderDuel();
      return;
    }
    if (state.player === playerSelect.value) return;
    selectPlayer(playerSelect.value);
  };
  let scrubFrame = null;
  timeInput.oninput = () => {
    if (scrubFrame) return;
    scrubFrame = requestAnimationFrame(() => {
      scrubFrame = null;
      setTime(Number(timeInput.value));
    });
  };
  playButton.onclick = play;
  speedSelect.onchange = () => { state.speed = Number(speedSelect.value) || 1; };
  const resize = () => { drawPulse(); drawRiver(); };
  const observer = new ResizeObserver(entries => {
    if (entries[0]?.contentRect.width) resize();
  });
  observer.observe(pulse);
  observer.observe(river);
  activeCleanup = () => { observer.disconnect(); if (timer) clearInterval(timer); };
  drawAll();
}
