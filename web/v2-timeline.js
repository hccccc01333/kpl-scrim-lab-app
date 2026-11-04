const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtGold = v => v == null ? '—' : Math.round(Number(v)).toLocaleString('zh-CN');
const fmtK = v => v == null ? '—' : Number(v) >= 1000 ? (Number(v) / 1000).toFixed(1) + 'k' : String(Math.round(Number(v)));
const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const normName = s => String(s ?? '').replace(/[\uFE0F\uFE0E]/g, '').trim();
const heroIcon = id => id == null ? '' : `/catalog/icons/hero-${id}.png`;
const itemIcon = id => id == null ? '' : `/catalog/icons/equipment-${id}.png`;

const STYLE_ID = 'v2d-style';
function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
.v2d{--blue:#2563eb;--red:#dc2626;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc;
  background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:18px;color:var(--ink);
  font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.v2d-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.v2d-title{font-size:18px;font-weight:700;letter-spacing:.2px}
.v2d-sub{color:var(--muted);font-size:12px;margin-top:2px}
.v2d-time{font-variant-numeric:tabular-nums;font-size:28px;font-weight:700;line-height:1}
.v2d-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.v2d-btn{border:1px solid var(--line);background:#fff;border-radius:9px;padding:6px 10px;cursor:pointer;
  font:inherit;color:var(--ink)}
.v2d-btn.active{background:var(--ink);color:#fff;border-color:var(--ink)}
.v2d-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.v2d-chip{font-size:11px;padding:3px 8px;border-radius:999px;background:#eef2ff;color:#3730a3;white-space:nowrap}
.v2d-chip.warn{background:#fef3c7;color:#92400e}
.v2d-chip.gray{background:#f1f5f9;color:#475569}
.v2d-card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px}
.v2d-chart-wrap{position:relative;margin-top:14px}
.v2d-chart{display:block;width:100%;height:auto;cursor:crosshair}
.v2d-tip{position:absolute;pointer-events:none;background:rgba(15,23,42,.92);color:#fff;border-radius:8px;
  padding:6px 8px;font-size:11px;line-height:1.5;white-space:nowrap;transform:translate(-50%,-115%);
  opacity:0;transition:opacity .12s}
.v2d-cursor{stroke:#94a3b8;stroke-width:1;stroke-dasharray:3 3}
.v2d-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.v2d-team-label{display:flex;align-items:center;gap:6px;font-weight:700;font-size:12px;margin:2px 0 6px}
.v2d-team-label i{width:8px;height:8px;border-radius:2px;display:inline-block}
.v2d-player{display:flex;gap:10px;align-items:flex-start;padding:9px 4px;border-top:1px solid #f1f5f9}
.v2d-player:first-of-type{border-top:0}
.v2d-avatar{width:40px;height:40px;border-radius:9px;object-fit:cover;background:#e2e8f0;flex:0 0 auto}
.v2d-avatar.fallback{display:flex;align-items:center;justify-content:center;font-weight:700;color:#475569}
.v2d-pmain{min-width:0;flex:1}
.v2d-pname{font-weight:650;font-size:12.5px;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v2d-lvl{background:#eef2ff;color:#3730a3;border-radius:6px;padding:0 5px;font-size:10.5px;font-weight:700}
.v2d-lvl.warn{background:#fef3c7;color:#92400e}
.v2d-phero{color:var(--muted);font-size:11px;margin-top:1px}
.v2d-pstats{display:flex;gap:10px;align-items:baseline;margin-top:5px;flex-wrap:wrap}
.v2d-gold{font-size:17px;font-weight:750;font-variant-numeric:tabular-nums}
.v2d-gold small{font-size:10px;color:var(--muted);font-weight:500;margin-left:2px}
.v2d-kda{font-variant-numeric:tabular-nums;font-size:12px;color:#334155}
.v2d-kda b{color:var(--ink)}
.v2d-bar{height:5px;background:#f1f5f9;border-radius:99px;overflow:hidden;margin-top:6px}
.v2d-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#22c55e,#16a34a)}
.v2d-bar i.unknown{background:#cbd5e1;width:100%!important;opacity:.5}
.v2d-events{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.v2d-ev{font-size:10px;padding:1px 5px;border-radius:5px;background:#f1f5f9;color:#475569;white-space:nowrap}
.v2d-ev.m{background:#eff6ff;color:#1d4ed8}.v2d-ev.a{background:#fff7ed;color:#c2410c}
.v2d-ev.s{background:#f5f3ff;color:#6d28d9}.v2d-ev.b{background:#ecfdf5;color:#047857}
.v2d-items{display:flex;gap:3px;align-items:center;margin-top:7px;flex-wrap:wrap}
.v2d-items img{width:22px;height:22px;border-radius:5px;object-fit:cover;background:#f1f5f9}
.v2d-items img.next{opacity:.32;filter:grayscale(.4)}
.v2d-items .plus{font-size:10px;color:var(--muted)}
.v2d-items .empty{font-size:10px;color:var(--muted)}
.v2d-lower{display:grid;grid-template-columns:200px 1fr;gap:12px;margin-top:14px}
.v2d-map{position:relative;aspect-ratio:1;border:1px solid var(--line);border-radius:12px;background:
  linear-gradient(135deg,#eff6ff 0 49%,#fff7ed 50% 100%);overflow:hidden}
.v2d-map svg{position:absolute;inset:0;width:100%;height:100%}
.v2d-map .tag{position:absolute;left:8px;bottom:6px;font-size:10px;color:var(--muted)}
.v2d-density{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px}
.v2d-density .bars{display:flex;align-items:flex-end;gap:1px;height:52px;margin-top:6px}
.v2d-density .bars i{flex:1;background:#bfdbfe;border-radius:2px 2px 0 0;min-height:2px}
.v2d-density .bars i.on{background:#2563eb}
.v2d-foot{margin-top:12px;color:var(--muted);font-size:11px}
.v2d-empty{padding:24px;color:var(--muted);text-align:center}
@media(max-width:900px){.v2d-grid,.v2d-lower{grid-template-columns:1fr}}
`;
  document.head.appendChild(style);
}

function aggregate(rows) {
  const bySecond = new Map();
  const playerMap = new Map();
  for (const row of rows) {
    const sec = row.second;
    if (!bySecond.has(sec)) bySecond.set(sec, []);
    bySecond.get(sec).push(row);
    if (!playerMap.has(row.entity_id)) {
      playerMap.set(row.entity_id, {
        id: row.entity_id, name: row.player, hero: row.hero,
        camp: String(row.camp) === '1' ? 1 : 2, unit: row.unit,
      });
    }
  }
  const team = {1: {gold: new Map(), kills: new Map()}, 2: {gold: new Map(), kills: new Map()}};
  for (const row of rows) {
    const camp = String(row.camp) === '1' ? 1 : 2;
    if (row.gold != null) team[camp].gold.set(row.second, (team[camp].gold.get(row.second) || 0) + Number(row.gold));
    if (row.kills != null) team[camp].kills.set(row.second, (team[camp].kills.get(row.second) || 0) + Number(row.kills));
  }
  return {bySecond, players: [...playerMap.values()], team};
}

function niceStep(max) {
  const raw = Math.max(max / 5, 1000);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

function seriesPath(map, x, y, seconds = 694) {
  const pts = [];
  for (let s = 0; s < seconds; s += 1) {
    if (map.has(s)) pts.push([s, map.get(s)]);
  }
  if (!pts.length) return '';
  return pts.map(([s, v], i) => `${i ? 'L' : 'M'}${x(s).toFixed(2)},${y(v).toFixed(2)}`).join('');
}

function killTicks(map) {
  const secs = [...map.keys()].sort((a, b) => a - b);
  const out = [];
  let prev = 0;
  for (const s of secs) {
    const v = Math.round(map.get(s));
    if (v > prev) { out.push({s, v, delta: v - prev}); prev = v; }
  }
  return out;
}

function renderChart(host, data, onSeek) {
  const W = 1000, H = 320, ml = 54, mr = 26, mt = 18, mb = 32;
  const maxGold = Math.max(1000, ...[...data.team[1].gold.values()], ...[...data.team[2].gold.values()]);
  const step = niceStep(maxGold);
  const yMax = Math.ceil(maxGold / step) * step;
  const x = s => ml + (W - ml - mr) * s / 693;
  const y = v => H - mb - (H - mt - mb) * v / yMax;
  const ticksY = [];
  for (let v = 0; v <= yMax + 1; v += step) ticksY.push(v);
  const ticksX = [0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660, 693];
  const gridY = ticksY.map(v => `<line x1="${ml}" y1="${y(v).toFixed(1)}" x2="${W - mr}" y2="${y(v).toFixed(1)}" stroke="#eef2f7" stroke-width="1"/>
    <text x="${ml - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#94a3b8">${v >= 1000 ? (v / 1000) + 'k' : v}</text>`).join('');
  const gridX = ticksX.map(s => `<line x1="${x(s).toFixed(1)}" y1="${mt}" x2="${x(s).toFixed(1)}" y2="${H - mb}" stroke="#f4f6fa" stroke-width="1"/>
    <text x="${x(s).toFixed(1)}" y="${H - 10}" text-anchor="middle" font-size="10" fill="#94a3b8">${clock(s)}</text>`).join('');
  const sparse = data.team[1].gold.size < 20 && data.team[2].gold.size < 20;
  const bluePath = sparse ? '' : seriesPath(data.team[1].gold, x, y);
  const redPath = sparse ? '' : seriesPath(data.team[2].gold, x, y);
  const dot = (map, color) => sparse ? [...map.entries()].map(([s, v]) =>
    `<circle cx="${x(s).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.5" fill="${color}"><title>${clock(s)} · ${Math.round(v)}</title></circle>`).join('') : '';
  const area = (path, color) => path ? `<path d="${path} L${x(693).toFixed(1)},${H - mb} L${x(0).toFixed(1)},${H - mb} Z" fill="${color}" opacity=".08"/>` : '';
  const blueKills = killTicks(data.team[1].kills).map(k =>
    `<rect x="${(x(k.s) - 1).toFixed(1)}" y="${H - mb - 7}" width="2" height="7" fill="#2563eb" opacity=".55"><title>${clock(k.s)} 蓝方击杀 +${k.delta}</title></rect>`).join('');
  const redKills = killTicks(data.team[2].kills).map(k =>
    `<rect x="${(x(k.s) - 1).toFixed(1)}" y="${H - mb - 7}" width="2" height="7" fill="#dc2626" opacity=".55"><title>${clock(k.s)} 红方击杀 +${k.delta}</title></rect>`).join('');
  host.innerHTML = `<svg class="v2d-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="团队经济曲线">
    <defs><linearGradient id="v2d-blue" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2563eb" stop-opacity=".22"/><stop offset="1" stop-color="#2563eb" stop-opacity="0"/></linearGradient>
    <linearGradient id="v2d-red" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#dc2626" stop-opacity=".18"/><stop offset="1" stop-color="#dc2626" stop-opacity="0"/></linearGradient></defs>
    ${gridY}${gridX}
    ${area(bluePath, 'url(#v2d-blue)')}${area(redPath, 'url(#v2d-red)')}
    ${dot(data.team[1].gold, '#2563eb')}${dot(data.team[2].gold, '#dc2626')}
    ${sparse ? `<text x="${W - mr}" y="${mt - 4}" text-anchor="end" font-size="10" fill="#92400e">仅检查点 · 未连线</text>` : ''}
    <path d="${bluePath}" fill="none" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="${redPath}" fill="none" stroke="#dc2626" stroke-width="2.2" stroke-linejoin="round"/>
    ${blueKills}${redKills}
    <g class="v2d-cursor-group" opacity=".9">
      <line class="v2d-cursor" x1="${x(0)}" y1="${mt}" x2="${x(0)}" y2="${H - mb}"/>
      <circle id="v2d-dot-b" r="3.5" fill="#2563eb" stroke="#fff" stroke-width="1.5"/>
      <circle id="v2d-dot-r" r="3.5" fill="#dc2626" stroke="#fff" stroke-width="1.5"/>
    </g>
    <text x="${ml}" y="${mt - 4}" font-size="10" fill="#2563eb" font-weight="600">蓝方经济</text>
    <text x="${ml + 64}" y="${mt - 4}" font-size="10" fill="#dc2626" font-weight="600">红方经济</text>
  </svg>`;
  const svg = host.querySelector('svg');
  const tip = document.createElement('div');
  tip.className = 'v2d-tip';
  host.appendChild(tip);
  const cursorLine = svg.querySelector('.v2d-cursor');
  const dotB = svg.querySelector('#v2d-dot-b');
  const dotR = svg.querySelector('#v2d-dot-r');
  const setCursor = (second, showTip) => {
    const bx = data.team[1].gold.get(second);
    const rx = data.team[2].gold.get(second);
    cursorLine.setAttribute('x1', x(second)); cursorLine.setAttribute('x2', x(second));
    if (bx != null) { dotB.setAttribute('cx', x(second)); dotB.setAttribute('cy', y(bx)); dotB.style.display = ''; } else dotB.style.display = 'none';
    if (rx != null) { dotR.setAttribute('cx', x(second)); dotR.setAttribute('cy', y(rx)); dotR.style.display = ''; } else dotR.style.display = 'none';
    if (showTip) {
      tip.style.left = (x(second) / W * 100) + '%';
      tip.style.top = (Math.min(y(bx ?? 0), y(rx ?? 0)) / H * 100) + '%';
      tip.innerHTML = `${clock(second)} · 蓝 ${fmtGold(bx)} · 红 ${fmtGold(rx)}`;
      tip.style.opacity = '1';
    } else { tip.style.opacity = '0'; }
  };
  svg.addEventListener('pointermove', event => {
    const rect = svg.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width * W;
    const second = Math.max(0, Math.min(693, Math.round((px - ml) / (W - ml - mr) * 693)));
    setCursor(second, true);
  });
  svg.addEventListener('pointerleave', () => setCursor(currentSecond, false));
  svg.addEventListener('click', event => {
    const rect = svg.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width * W;
    const second = Math.max(0, Math.min(693, Math.round((px - ml) / (W - ml - mr) * 693)));
    onSeek(second);
  });
  let currentSecond = 0;
  return {setCursor, setSecond(second) { currentSecond = second; setCursor(second, false); }};
}

function playerCard(row, hero, build, second) {
  const camp = String(row.camp) === '1' ? 1 : 2;
  const kdaConf = row.kda_confidence || 'unknown';
  const approx = kdaConf === 'anchor' || kdaConf === 'measured' ? '' : '≈';
  const k = Number(row.kills || 0), d = Number(row.deaths || 0), a = Number(row.assists || 0);
  const kda = `${approx}${Math.round(k)}/${Math.round(d)}/${Math.round(a)}`;
  const hp = row.hp_ratio == null ? null : Math.max(0, Math.min(1, Number(row.hp_ratio)));
  const hpLabel = hp == null ? '—' : Math.round(hp * 100) + '%';
  const level = row.level == null ? '?' : row.level;
  const lvlWarn = row.level_confidence === 'last-known';
  const items = (build?.items || []).filter(item => item.t <= second).slice(-4);
  const next = (build?.items || []).find(item => item.t > second);
  const itemHtml = [
    ...items.map(item => `<img src="${itemIcon(item.id)}" alt="${esc(item.name)}" title="${esc(item.name)} ${clock(item.t)}">`),
    next ? `<span class="plus">+</span><img class="next" src="${itemIcon(next.id)}" alt="${esc(next.name)}" title="下一件 ${esc(next.name)} ${clock(next.t)}">` : '',
  ].filter(Boolean).join('');
  const events = [
    ['m', '移', row.events_move], ['a', '攻', row.events_attack], ['s', '技', row.events_skill],
    ['b', '购', row.events_buy], ['', 'CC', row.events_cc],
  ].filter(([, , n]) => Number(n) > 0)
    .map(([cls, label, n]) => `<span class="v2d-ev ${cls}">${label} ${n}</span>`).join('');
  return `<div class="v2d-player">
    ${hero && hero.id ? `<img class="v2d-avatar" src="${heroIcon(hero.id)}" alt="${esc(row.hero)}">`
      : `<div class="v2d-avatar fallback">${esc((row.hero || '?').slice(0, 1))}</div>`}
    <div class="v2d-pmain">
      <div class="v2d-pname">${esc(row.player)}<span class="v2d-lvl ${lvlWarn ? 'warn' : ''}" title="等级来源：${esc(row.level_confidence || '')}">Lv ${level}</span></div>
      <div class="v2d-phero">${esc(row.hero || '')}${camp === 1 ? '' : ''}</div>
      <div class="v2d-pstats"><span class="v2d-gold">${fmtGold(row.gold)}<small>金</small></span><span class="v2d-kda">KDA <b>${kda}</b></span></div>
      <div class="v2d-bar" title="资源比例（引擎 +0x08/+0x10，与 UI 血条不一致，待验证）"><i class="${hp == null ? 'unknown' : ''}" style="width:${hp == null ? 100 : Math.round(hp * 100)}%"></i></div>
      <div class="v2d-events">${events || '<span class="v2d-ev">本秒无事件</span>'}</div>
      <div class="v2d-items">${itemHtml || '<span class="empty">未出装</span>'}</div>
    </div>
  </div>`;
}

function renderMinimap(host, rows) {
  const W = 180, H = 180, pad = 12;
  const toUV = (x, z) => [(Number(x) + 60000) / 120000, (Number(z) + 60000) / 120000];
  const points = rows.filter(row => row.x != null && row.z != null).map(row => {
    const [u, v] = toUV(row.x, row.z);
    return {row, cx: pad + Math.max(0, Math.min(1, u)) * (W - 2 * pad), cy: pad + Math.max(0, Math.min(1, v)) * (H - 2 * pad)};
  });
  host.innerHTML = `<div class="v2d-map">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="位置估算">
      <line x1="${W / 2}" y1="4" x2="${W / 2}" y2="${H - 4}" stroke="#cbd5e1" stroke-dasharray="3 3"/>
      <line x1="4" y1="${H / 2}" x2="${W - 4}" y2="${H / 2}" stroke="#cbd5e1" stroke-dasharray="3 3"/>
      ${points.map(p => `<circle cx="${p.cx.toFixed(1)}" cy="${p.cy.toFixed(1)}" r="5" fill="${String(p.row.camp) === '1' ? '#2563eb' : '#dc2626'}" fill-opacity=".85" stroke="#fff" stroke-width="1.5"><title>${esc(p.row.player)} ${esc(p.row.hero)} · 估算</title></circle>`).join('')}
    </svg><span class="tag">位置估算 · 非坐标</span></div>`;
}

function renderDensity(host, rows, second) {
  const bins = new Map();
  for (const row of rows) {
    const bin = Math.floor(row.second / 10) * 10;
    const n = (row.events_move || 0) + (row.events_attack || 0) + (row.events_skill || 0)
      + (row.events_buy || 0) + (row.events_cc || 0) + (row.events_aim || 0);
    bins.set(bin, (bins.get(bin) || 0) + n);
  }
  const max = Math.max(1, ...bins.values());
  const bars = [...bins.entries()].sort((a, b) => a[0] - b[0]).map(([s, n]) =>
    `<i class="${Math.floor(second / 10) * 10 === s ? 'on' : ''}" style="height:${Math.max(3, Math.round(n / max * 48))}px" title="${clock(s)} +${n}"></i>`).join('');
  host.innerHTML = `<div class="v2d-density"><div class="panel-subtitle" style="margin:0">事件密度 · 每 10 秒（十人合计）</div><div class="bars">${bars}</div></div>`;
}

export async function renderV2Timeline(host, {api, replayId, heroes = []}) {
  ensureStyle();
  host.innerHTML = '<div class="v2d-empty">正在加载 V2 时间轴…</div>';
  try {
    const load = async path => {
      const response = await fetch(path);
      if (response.status === 404) return null;
      const value = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(value.detail || '读取失败');
      return value;
    };
    const [metaResponse, data, builds] = await Promise.all([
      load(`/api/replays/${encodeURIComponent(replayId)}/v2-timeline/meta`),
      load(`/api/replays/${encodeURIComponent(replayId)}/v2-timeline`),
      load(`/api/replays/${encodeURIComponent(replayId)}/v2-timeline/builds`).catch(() => ({players: {}})),
    ]);
    if (!metaResponse || !data) {
      host.innerHTML = '<div class="v2d-empty">这份回放还没有生成 V2 状态时间轴；导入检查点后可按实测字段生成。</div>';
      return;
    }
    const meta = metaResponse.meta || {};
    const rows = data.rows || [];
    if (!rows.length) { host.innerHTML = '<div class="v2d-empty">V2 时间轴没有数据。</div>'; return; }
    const heroMap = new Map((heroes || []).map(item => [normName(item.name), item]));
    const buildMap = new Map(Object.entries((builds || {}).players || {}).map(([name, value]) => [normName(name), value]));
    const agg = aggregate(rows);
    let second = 94;
    let playing = false;
    let speed = 4;
    let timer = null;

    host.innerHTML = `<section class="v2d">
      <div class="v2d-head">
        <div><div class="v2d-title">V2 状态时间轴</div>
          <div class="v2d-sub">团队经济 · 十人状态 · 出装 · 事件密度</div>
          <div class="v2d-chips">
            <span class="v2d-chip">经济：检查点实测 + 段间插值</span>
            <span class="v2d-chip warn">位置：估算，仅趋势</span>
            <span class="v2d-chip warn">资源比例：与 UI 血条不一致，待验证</span>
            <span class="v2d-chip gray">${fmtK(meta.rows)} 行 / ${meta.players} 人 / 1 Hz</span>
          </div>
        </div>
        <div style="text-align:right">
          <div class="v2d-time" id="v2d-time">1:34</div>
          <div class="v2d-controls" style="justify-content:flex-end;margin-top:8px">
            <button class="v2d-btn" id="v2d-play" type="button">▶ 播放</button>
            <button class="v2d-btn" data-speed="1" type="button">1x</button>
            <button class="v2d-btn active" data-speed="4" type="button">4x</button>
            <button class="v2d-btn" data-speed="8" type="button">8x</button>
          </div>
        </div>
      </div>
      <div class="v2d-chart-wrap" id="v2d-chart"></div>
      <input id="v2d-scrub" type="range" min="0" max="693" value="0" step="1" style="width:100%;margin-top:10px;accent-color:#2563eb">
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
        ${[[94,'01:34'],[165,'02:45'],[300,'05:00'],[466,'07:46'],[693,'结算']].map(([s,label]) => `<button class="v2d-btn" data-jump="${s}" type="button">${label}</button>`).join('')}
      </div>
      <div class="v2d-grid">
        <div><div class="v2d-team-label" style="color:#2563eb"><i style="background:#2563eb"></i>蓝方</div><div id="v2d-blue-cards"></div></div>
        <div><div class="v2d-team-label" style="color:#dc2626"><i style="background:#dc2626"></i>红方</div><div id="v2d-red-cards"></div></div>
      </div>
      <div class="v2d-lower"><div id="v2d-map"></div><div id="v2d-density"></div></div>
      <div class="v2d-foot">${(meta.caveats || []).map(esc).join('；')}。缺失字段保持“—”，估算值不进入正式统计。</div>
    </section>`;

    const chartHost = host.querySelector('#v2d-chart');
    const chart = renderChart(chartHost, agg, value => { stop(); setSecond(value); });
    const scrub = host.querySelector('#v2d-scrub');
    const timeLabel = host.querySelector('#v2d-time');
    const playBtn = host.querySelector('#v2d-play');
    const blueHost = host.querySelector('#v2d-blue-cards');
    const redHost = host.querySelector('#v2d-red-cards');
    const mapHost = host.querySelector('#v2d-map');
    const densityHost = host.querySelector('#v2d-density');

    const paint = () => {
      timeLabel.textContent = clock(second);
      scrub.value = String(second);
      chart.setSecond(second);
      const at = agg.bySecond.get(second) || [];
      const blue = at.filter(row => String(row.camp) === '1').sort((a, b) => (a.unit || 0) - (b.unit || 0));
      const red = at.filter(row => String(row.camp) === '2').sort((a, b) => (a.unit || 0) - (b.unit || 0));
      blueHost.innerHTML = blue.map(row => playerCard(row, heroMap.get(normName(row.player)), buildMap.get(normName(row.player)), second)).join('');
      redHost.innerHTML = red.map(row => playerCard(row, heroMap.get(normName(row.player)), buildMap.get(normName(row.player)), second)).join('');
      renderMinimap(mapHost, at);
      renderDensity(densityHost, rows, second);
    };
    const setSecond = value => { second = Math.max(0, Math.min(693, value)); paint(); };
    const stop = () => { playing = false; if (timer) clearInterval(timer); timer = null; playBtn.textContent = '▶ 播放'; };
    const play = () => {
      if (playing) { stop(); return; }
      playing = true; playBtn.textContent = '⏸ 暂停';
      timer = setInterval(() => {
        second += 1;
        if (second >= 693) { second = 693; stop(); }
        paint();
      }, Math.max(60, 1000 / speed));
    };
    playBtn.onclick = play;
    host.querySelectorAll('[data-speed]').forEach(btn => btn.onclick = () => {
      speed = Number(btn.dataset.speed);
      host.querySelectorAll('[data-speed]').forEach(other => other.classList.toggle('active', other === btn));
      if (playing) { stop(); play(); }
    });
    host.querySelectorAll('[data-jump]').forEach(btn => btn.onclick = () => { stop(); setSecond(Number(btn.dataset.jump)); });
    scrub.oninput = () => { stop(); setSecond(Number(scrub.value)); };
    paint();
  } catch (error) {
    host.innerHTML = `<div class="v2d-empty">V2 时间轴读取失败：${esc(error.message)}</div>`;
  }
}
