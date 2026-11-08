/* 对比工作台：教练用多选框拉出任意几个对象，做数据 / 对位 / 层次三种对比。
   数据全部来自既有接口：
   - 选手 / 英雄指标：/api/studio/view/players、/view/heroes
   - 战队指标与分位：/api/studio/teams
   - 对位样本：/api/studio/view/lane-matchups（同分路双方的经济差与 KDA 差） */
import {esc, num, stats, panel, table, emptyTip, pageHero, insights, details, radarCard} from '/assets/design/ui.js';
import {skeleton} from '/assets/design/ui.js';
import {appendDepthSections, depthSection, bindDepthSections} from '/assets/depth-section.js';

const SERIES_COLORS = ['var(--accent)', 'var(--side-red)', 'var(--pos)', 'var(--warn)'];
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

const PLAYER_METRICS = [
  {key: 'winRate', label: '胜率', unit: '%', digits: 1, higher: true},
  {key: 'kda', label: 'KDA', digits: 2, higher: true},
  {key: 'gpm', label: '分均经济', digits: 0, higher: true},
  {key: 'dpm', label: '分均输出', digits: 0, higher: true},
  {key: 'tpm', label: '分均承伤', digits: 0, higher: false},
  {key: 'participation', label: '参团率', unit: '%', digits: 1, higher: true},
];
const HERO_METRICS = [
  {key: 'winRate', label: '胜率', unit: '%', digits: 1, higher: true},
  {key: 'kda', label: 'KDA', digits: 2, higher: true},
  {key: 'gpm', label: '分均经济', digits: 0, higher: true},
  {key: 'dpm', label: '分均输出', digits: 0, higher: true},
  {key: 'picks', label: '出场数', digits: 0, higher: true},
];
const TEAM_METRICS = [
  {key: 'winRate', label: '胜率', unit: '%', digits: 1, higher: true},
  {key: 'kda', label: 'KDA', digits: 2, higher: true},
  {key: 'gpm', label: '分均经济', digits: 0, higher: true},
  {key: 'dpm', label: '分均输出', digits: 0, higher: true},
  {key: 'dtpm', label: '分均承伤', digits: 0, higher: false},
  {key: 'towerPerGame', label: '场均推塔', digits: 1, higher: true},
];

/* 池内分位：higher=true 表示数值越大分位越高；承伤类反向。 */
function poolPercentile(values, value, higher) {
  const vals = values.filter(v => v != null);
  if (value == null || vals.length < 3) return null;
  const hit = vals.filter(v => (higher ? v <= value : v >= value)).length;
  return Math.round(hit / vals.length * 100);
}

const fmtValue = (metric, value) => value == null ? '—'
  : `${num(value, metric.digits)}${metric.unit || ''}`;

/* ---------------- 状态 ---------------- */
const S = {
  type: 'player',       // 数据页：player | hero | team
  picked: {},           // kind -> [id]；数据页最多 4 个，对位页每槽 1 个
  lane: '全部',
  tierLane: '全部', tierMetric: 'gpm',
  open: '', search: '', // picker 弹层
};

function seg(current, options, attr) {
  return `<div class="seg" data-${attr}>${options.map(([key, label]) =>
    `<button type="button" class="${key === current ? 'is-active' : ''}" data-seg="${esc(key)}">${esc(label)}</button>`).join('')}</div>`;
}

/* ---------------- 多选选择框 ---------------- */
function picker(kind, items, max, {single = false, cls = ''} = {}) {
  const picked = [...new Set(S.picked[kind] || [])].filter(id => items.some(item => item.id === id));
  const seen = new Set();
  const chips = items.filter(item => picked.includes(item.id) && !seen.has(item.id) && seen.add(item.id));
  const open = S.open === kind;
  return `<div class="cl-picker ${cls}" data-picker="${kind}">
    <div class="cl-tray">
      ${chips.length ? chips.map(item => `<span class="cl-chip" style="--chip:${item.color || 'var(--accent)'}">
          ${esc(item.name)}${item.own ? ' <em class="cl-own">我方</em>' : ''}<button type="button" data-remove="${esc(item.id)}" title="移除">×</button></span>`).join('')
        : `<span class="cl-hint">${single ? '点右侧选择' : `点「＋ 添加」拉对象进来（最多 ${max} 个）`}</span>`}
      <button type="button" class="cl-add" data-open="${kind}" ${!single && picked.length >= max ? 'disabled' : ''}>＋ 添加</button>
    </div>
    <div class="cl-menu" data-menu="${kind}" ${open ? '' : 'hidden'}>
      <div class="cl-menu-head">
        <input data-search placeholder="搜索名称…" value="${esc(S.search)}">
        <button type="button" class="link" data-close>收起</button>
      </div>
      <div class="cl-list"></div>
    </div>
  </div>`;
}

function bindPicker(root, kind, items, rerender, {single = false} = {}) {
  const box = root.querySelector(`[data-picker="${kind}"]`);
  if (!box) return;
  const menu = box.querySelector('.cl-menu');
  const paint = () => {
    const q = (S.search || '').trim().toLowerCase();
    const filtered = q ? items.filter(item => item.name.toLowerCase().includes(q)
      || (item.sub || '').toLowerCase().includes(q)) : items;
    menu.querySelector('.cl-list').innerHTML = filtered.length ? filtered.map(item => `
      <button type="button" class="cl-item" data-pick="${esc(item.id)}">
        <span class="cl-item-name">${item.icon ? `<img class="cl-avatar" src="${esc(item.icon)}" alt="">` : ''}${esc(item.name)}${item.own ? ' <em class="cl-own">我方</em>' : ''}</span>
        <span class="cl-item-sub">${esc(item.sub || '')}</span>
      </button>`).join('') : '<div class="cl-none">没有匹配的对象。</div>';
    menu.querySelectorAll('[data-pick]').forEach(button => {
      button.onclick = () => {
        const id = button.dataset.pick;
        if (single) { S.picked[kind] = [id]; S.open = ''; }
        else if (!(S.picked[kind] || []).includes(id)) S.picked[kind] = [...(S.picked[kind] || []), id];
        rerender();
      };
    });
  };
  box.querySelector('[data-open]').onclick = () => { S.open = S.open === kind ? '' : kind; S.search = ''; rerender(); };
  menu.querySelector('[data-close]').onclick = () => { S.open = ''; rerender(); };
  const search = menu.querySelector('[data-search]');
  search.oninput = () => { S.search = search.value; paint(); };
  paint();
  box.querySelectorAll('[data-remove]').forEach(button => {
    button.onclick = () => {
      S.picked[kind] = (S.picked[kind] || []).filter(id => id !== button.dataset.remove);
      rerender();
    };
  });
}

function bindSeg(root, attr, handler) {
  root.querySelectorAll(`[data-${attr}] [data-seg]`).forEach(button => {
    button.onclick = () => handler(button.dataset.seg);
  });
}

/* ---------------- 数据对比 ---------------- */
function compareDataView(root, D, rerender) {
  const kind = S.type;
  const catalog = D.catalog[kind];
  const chosen = (S.picked[kind] || []).map(id => catalog.byId[id]).filter(Boolean);
  const max = 4;
  const head = `<div class="cl-toolbar">
      ${seg(kind, [['player', '选手'], ['hero', '英雄'], ['team', '战队']], 'type')}
      ${picker(kind, catalog.items, max)}
    </div>`;

  if (!chosen.length) {
    const suggest = catalog.items.slice(0, 6).map(item =>
      `<button type="button" class="link" data-quick="${esc(item.id)}">${esc(item.name)}</button>`).join(' · ');
    root.innerHTML = head + panel('开始一次对比', `<div class="block-note">
        从选择框拉 2–4 个对象；只选 1 个时按「对象 vs 池中位」出对照。<br>
        常用：${suggest || '暂无可选对象'}</div>`);
    root.querySelectorAll('[data-quick]').forEach(button => {
      button.onclick = () => {
        S.picked[kind] = [...(S.picked[kind] || []), button.dataset.quick];
        rerender();
      };
    });
    bindPicker(root, kind, catalog.items, rerender);
    bindSeg(root, 'type', value => { S.type = value; S.open = ''; rerender(); });
    return;
  }

  const metrics = kind === 'player' ? PLAYER_METRICS : kind === 'hero' ? HERO_METRICS : TEAM_METRICS;
  const pool = D.pool[kind];
  const statOf = entity => metrics.map(metric => {
    const value = entity.raw[metric.key];
    return {...metric, value,
      rank: poolPercentile(pool.map(row => row[metric.key]), value, metric.higher)};
  });
  const series = chosen.map((entity, index) => ({
    name: entity.name,
    color: SERIES_COLORS[index % SERIES_COLORS.length],
    values: Object.fromEntries(statOf(entity).map(stat => [stat.key, stat.rank ?? 0])),
  }));

  const cards = chosen.map((entity, index) => `<article class="cl-card" style="--chip:${SERIES_COLORS[index % SERIES_COLORS.length]}">
      <h3>${entity.icon ? `<img class="cl-avatar" src="${esc(entity.icon)}" alt="">` : ''}${esc(entity.name)}${entity.own ? ' <em class="cl-own">我方</em>' : ''}</h3>
      <p>${esc(entity.sub || '')}</p>
    </article>`).join('');

  const medianOf = key => {
    const vals = pool.map(row => row[key]).filter(v => v != null).sort((a, b) => a - b);
    return vals.length ? vals[Math.floor(vals.length / 2)] : null;
  };
  const tableRows = metrics.map(metric => {
    const values = chosen.map(entity => entity.raw[metric.key]);
    const valid = values.filter(v => v != null);
    let best = null;
    if (valid.length && chosen.length > 1) {
      const top = metric.higher ? Math.max(...valid) : Math.min(...valid);
      const bottom = metric.higher ? Math.min(...valid) : Math.max(...valid);
      best = top === bottom ? null : top;   // 全部持平时不加高亮
    }
    return [
      metric.label + (metric.higher === false ? ' <em class="cl-low">越低越好</em>' : ''),
      ...values.map(value => ({v: fmtValue(metric, value),
        cls: `num${value != null && value === best ? ' is-best' : ''}`})),
      {v: fmtValue(metric, medianOf(metric.key)), cls: 'num muted'},
    ];
  });

  const chips = [];
  metrics.forEach(metric => {
    const entries = chosen.map(entity => ({entity, value: entity.raw[metric.key]}))
      .filter(row => row.value != null);
    if (entries.length < 2) return;
    const best = entries.slice().sort((a, b) => metric.higher ? b.value - a.value : a.value - b.value)[0];
    const worst = entries.slice().sort((a, b) => metric.higher ? a.value - b.value : b.value - a.value)[0];
    if (best.entity === worst.entity || best.value === worst.value) return;
    chips.push({tone: 'neutral',
      text: `${metric.label}：${best.entity.name} ${fmtValue(metric, best.value)} 领先（最低 ${worst.entity.name} ${fmtValue(metric, worst.value)}）`});
  });

  root.innerHTML = head
    + `<div class="cl-cards">${cards}</div>`
    + (chosen.length >= 2
      ? `<div class="cmp-grid"><div>${radarCard({dims: metrics.map(metric => ({key: metric.key, label: metric.label})), series, legend: true})}</div>
        <div>${panel('指标对照', table(
          ['指标', ...chosen.map(entity => entity.name), '池中位'], tableRows,
          {empty: '没有可比指标。'}), {note: '雷达为池内分位（0–100），P50 虚线为池内中位；表为原值，加粗列为该项最优'})}</div></div>`
      : panel('对象 vs 池中位', table(
          ['指标', chosen[0].name, '池中位'],
          metrics.map(metric => [metric.label,
            {v: fmtValue(metric, chosen[0].raw[metric.key]), cls: 'num'},
            {v: fmtValue(metric, medianOf(metric.key)), cls: 'num muted'}]),
          {empty: '没有可比指标。'}), {note: '只选 1 个对象时，与全部同类对象的中位数对照'}))
    + (chips.length ? insights([{label: '对比结论', chips}]) : '')
    + details('分位明细', table(
      ['对象', ...metrics.map(metric => metric.label)],
      chosen.map(entity => [esc(entity.name),
        ...statOf(entity).map(stat => ({v: stat.rank == null ? '—' : `P${stat.rank}`, cls: 'num'}))]),
      {empty: '样本不足，分位不可用。'}), {label: '展开分位表'});

  bindPicker(root, kind, catalog.items, rerender);
  bindSeg(root, 'type', value => { S.type = value; S.open = ''; rerender(); });
}

/* ---------------- 对位对比 ---------------- */
function compareMatchupView(root, D, rerender) {
  const ownId = (S.picked['matchup-own'] || [])[0] || '';
  const enemyId = (S.picked['matchup-enemy'] || [])[0] || '';
  const ownPlayers = D.playerItems.filter(item => item.own);
  const enemyOptions = D.playerItems.filter(item => !item.own);

  const head = `<div class="cl-toolbar">
    ${picker('matchup-own', ownPlayers, 1, {single: true, cls: 'cl-narrow'})}
    <span class="cl-vs">对位</span>
    ${picker('matchup-enemy', enemyOptions, 1, {single: true})}
    ${seg(S.lane, [['全部', '全部'], ...LANES.map(lane => [lane, lane])], 'lane')}
  </div>`;

  // 高频对位对，快速入口
  const pairCount = new Map();
  D.matchups.forEach(row => {
    if (!row.ownLabel || !row.enemyLabel) return;
    const key = `${row.ownLabel}|${row.enemyLabel}`;
    pairCount.set(key, (pairCount.get(key) || 0) + 1);
  });
  const topPairs = [...pairCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);

  if (!ownId || !enemyId) {
    root.innerHTML = head + panel('选一对对手', `<div class="block-note">
        左边选我方选手，右边选对方选手，只统计<b>同分路直接对位</b>的样本（终局经济差、KDA 差、对位胜负）。<br>
        高频对位：${topPairs.map(([key, count]) => {
          const [own, enemy] = key.split('|');
          return `<button type="button" class="link" data-pair="${esc(own)}|${esc(enemy)}">${esc(own)} × ${esc(enemy)}（${num(count)}）</button>`;
        }).join(' · ') || '还没有对位样本。'}</div>`);
    root.querySelectorAll('[data-pair]').forEach(button => {
      button.onclick = () => {
        const [own, enemy] = button.dataset.pair.split('|');
        S.picked['matchup-own'] = [own];
        S.picked['matchup-enemy'] = [enemy];
        rerender();
      };
    });
    bindPicker(root, 'matchup-own', ownPlayers, rerender, {single: true});
    bindPicker(root, 'matchup-enemy', enemyOptions, rerender, {single: true});
    bindSeg(root, 'lane', value => { S.lane = value; rerender(); });
    return;
  }

  const ownName = ownPlayers.find(item => item.id === ownId)?.name || ownId;
  const enemyName = enemyOptions.find(item => item.id === enemyId)?.name || enemyId;
  const rows = D.matchups.filter(row =>
    row.ownLabel === ownId && row.enemyLabel === enemyId
    && (S.lane === '全部' || row.position === S.lane));
  const n = rows.length;
  const ahead = rows.filter(row => row.diff > 0);
  const decided = rows.filter(row => row.win != null);
  const wins = rows.filter(row => row.win === true);
  const aheadWins = ahead.filter(row => row.win === true);
  const avgDiff = n ? rows.reduce((sum, row) => sum + row.diff, 0) / n : null;
  const kdaRows = rows.filter(row => row.kdaDiff != null);
  const avgKda = kdaRows.length ? kdaRows.reduce((sum, row) => sum + row.kdaDiff, 0) / kdaRows.length : null;

  const findings = [];
  if (n) {
    findings.push({text: `${esc(ownName)} 对 ${esc(enemyName)}：${num(n)} 次同路对位`,
      note: S.lane === '全部' ? '全部分路' : S.lane});
    if (ahead.length) findings.push({
      text: `经济领先率 ${num(ahead.length / n * 100, 0)}%`,
      note: `领先时 ${num(aheadWins.length)}/${num(ahead.length)} 胜 · 场均差 ${avgDiff > 0 ? '+' : ''}${num(avgDiff, 0)}`,
    });
    if (decided.length) findings.push({
      text: `对位局我方胜率 ${num(wins.length / decided.length * 100, 1)}%`,
      note: `${num(wins.length)} 胜 / ${num(decided.length)} 局定胜负`,
    });
    if (avgKda != null) findings.push({
      text: `KDA 差 ${avgKda > 0 ? '+' : ''}${num(avgKda, 2)}`,
      note: '我方 − 对方，同路局',
    });
  }

  const heroMap = new Map();
  rows.forEach(row => {
    const key = `${row.ownHero || '—'}|${row.enemyHero || '—'}`;
    const item = heroMap.get(key) || {own: row.ownHero || '—', enemy: row.enemyHero || '—',
      n: 0, diff: 0, wins: 0, decided: 0};
    item.n += 1; item.diff += row.diff;
    if (row.win != null) { item.decided += 1; if (row.win) item.wins += 1; }
    heroMap.set(key, item);
  });
  const heroRows = [...heroMap.values()].sort((a, b) => b.n - a.n).map(item => [
    `<b>${esc(item.own)}</b>`, esc(item.enemy), {v: num(item.n), cls: 'num'},
    {v: `${item.diff > 0 ? '+' : ''}${num(item.diff / item.n, 0)}`,
     cls: `num ${item.diff > 0 ? 'is-pos' : item.diff < 0 ? 'is-neg' : ''}`},
    {v: item.decided ? `${num(item.wins)}-${num(item.decided - item.wins)}` : '—', cls: 'num'},
  ]);

  root.innerHTML = head
    + (n ? stats([
        ['对位样本', num(n), S.lane === '全部' ? '全部分路' : S.lane],
        ['经济领先率', num(ahead.length / n * 100, 0) + '%', `${num(ahead.length)} 次领先`],
        ['场均经济差', avgDiff == null ? '—' : (avgDiff > 0 ? '+' : '') + num(avgDiff, 0), '我方 − 对方'],
        ['对位局胜率', decided.length ? num(wins.length / decided.length * 100, 1) + '%' : '—', `${num(decided.length)} 局定胜负`],
      ])
      + `<div class="brief-list">${findings.map(item =>
          `<div class="brief-row"><b>${item.text}</b><span>${esc(item.note || '')}</span></div>`).join('')}</div>`
      + panel('英雄组合对位', table(
        ['我方英雄', '对方英雄', {label: '对位', align: 'right'}, {label: '场均经济差', align: 'right'},
         {label: '胜负', align: 'right'}], heroRows, {empty: '没有样本。'}))
      + details('逐局明细', table(
        ['对局', '日期', '分路', '我方英雄', '对方英雄', {label: '经济差', align: 'right'},
         {label: 'KDA 差', align: 'right'}, '结果'],
        rows.map(row => [
          `<a href="#match/${esc(row.matchKey)}">${esc(row.opponent || row.matchKey)}</a>`,
          esc(row.date || '—'), esc(row.position),
          esc(row.ownHero || '—'), esc(row.enemyHero || '—'),
          {v: (row.diff > 0 ? '+' : '') + num(row.diff, 0), cls: `num ${row.diff > 0 ? 'is-pos' : row.diff < 0 ? 'is-neg' : ''}`},
          {v: row.kdaDiff == null ? '—' : (row.kdaDiff > 0 ? '+' : '') + num(row.kdaDiff, 2), cls: 'num'},
          row.win == null ? '—' : row.win ? '<span class="card-tag is-win">胜</span>' : '<span class="card-tag is-loss">负</span>',
        ]), {empty: '没有逐局样本。'}), {label: '展开逐局明细'})
    : emptyTip('这两名选手没有同分路对位的记录；试试换人，或放宽到「全部」分路。'));

  bindPicker(root, 'matchup-own', ownPlayers, rerender, {single: true});
  bindPicker(root, 'matchup-enemy', enemyOptions, rerender, {single: true});
  bindSeg(root, 'lane', value => { S.lane = value; rerender(); });
}

/* ---------------- 层次对比 ---------------- */
function compareTierView(root, D, rerender) {
  const metric = PLAYER_METRICS.find(item => item.key === S.tierMetric) || PLAYER_METRICS[2];
  const poolRows = D.players.filter(player =>
    (S.tierLane === '全部' || (player.positions || []).includes(S.tierLane))
    && player[metric.key] != null && player.matches >= 2);

  const head = `<div class="cl-toolbar">
    ${seg(S.tierLane, [['全部', '全部'], ...LANES.map(lane => [lane, lane])], 'tier-lane')}
    ${seg(S.tierMetric, PLAYER_METRICS.map(item => [item.key, item.label]), 'tier-metric')}
  </div>`;

  if (!poolRows.length) {
    root.innerHTML = head + emptyTip('这个分路暂时没有可比样本（至少 2 局）。');
    bindSeg(root, 'tier-lane', value => { S.tierLane = value; rerender(); });
    bindSeg(root, 'tier-metric', value => { S.tierMetric = value; rerender(); });
    return;
  }

  const sorted = poolRows.slice()
    .sort((a, b) => metric.higher ? b[metric.key] - a[metric.key] : a[metric.key] - b[metric.key]);
  const max = Math.max(...sorted.map(row => row[metric.key]));
  const min = Math.min(0, Math.min(...sorted.map(row => row[metric.key])));
  const span = max - min || 1;
  const values = sorted.map(row => row[metric.key]);

  const bars = sorted.map((row, index) => {
    const width = Math.max(2, (row[metric.key] - min) / span * 100);
    const rank = poolPercentile(values, row[metric.key], metric.higher);
    const topHeroIcon = (row.heroes || [])[0] ? (D.heroIcons || {})[row.heroes[0].hero] || '' : '';
    return `<div class="cl-rank ${row.own ? 'is-own' : ''}">
      <span class="cl-rank-pos">${index + 1}</span>
      <span class="cl-rank-name">${topHeroIcon ? `<img class="cl-avatar" src="${esc(topHeroIcon)}" alt="">` : ''}${esc(row.label)}${row.own ? ' <em class="cl-own">我方</em>' : ''}</span>
      <span class="cl-rank-bar"><i style="width:${width.toFixed(1)}%"></i></span>
      <b class="cl-rank-val">${fmtValue(metric, row[metric.key])}</b>
      <span class="cl-rank-pct">${rank == null ? '' : 'P' + rank}</span>
    </div>`;
  }).join('');

  const ownRows = sorted.filter(row => row.own);
  const findings = [];
  if (ownRows.length) {
    const positions = ownRows.map(row => sorted.indexOf(row) + 1);
    findings.push({text: `我方 ${num(ownRows.length)} 人在榜：最高第 ${Math.min(...positions)} 名`,
      note: `${S.tierLane === '全部' ? '全部分路' : S.tierLane} · ${metric.label}`});
    const best = ownRows.slice()
      .sort((a, b) => metric.higher ? b[metric.key] - a[metric.key] : a[metric.key] - b[metric.key])[0];
    findings.push({text: `${esc(best.label)} ${fmtValue(metric, best[metric.key])}`,
      note: `超过池内 ${poolPercentile(values, best[metric.key], metric.higher) ?? '—'}% 的对象`});
  }

  root.innerHTML = head
    + (findings.length ? `<div class="brief-list">${findings.map(item =>
        `<div class="brief-row"><b>${item.text}</b><span>${esc(item.note || '')}</span></div>`).join('')}</div>` : '')
    + panel(`${metric.label} 排行 · ${S.tierLane === '全部' ? '全部分路' : S.tierLane}`,
      `<div class="cl-ranks">${bars}</div>`,
      {note: `共 ${num(sorted.length)} 人（≥2 局）；蓝底 = 我方选手，P = 池内分位`})
    + details('完整名单与指标', table(
      ['#', '选手', '分路', {label: metric.label, align: 'right'}, {label: '局数', align: 'right'}, '常用英雄'],
      sorted.map((row, index) => [index + 1,
        `${esc(row.label)}${row.own ? ' <em class="cl-own">我方</em>' : ''}`,
        esc((row.positions || []).join('/')),
        {v: fmtValue(metric, row[metric.key]), cls: 'num'},
        {v: num(row.matches), cls: 'num'},
        esc((row.heroes || []).slice(0, 3).map(hero => hero.hero).join(' / ')),
      ]), {empty: '没有样本。'}), {label: '展开完整名单'});

  bindSeg(root, 'tier-lane', value => { S.tierLane = value; rerender(); });
  bindSeg(root, 'tier-metric', value => { S.tierMetric = value; rerender(); });
}

/* ---------------- 主入口 ---------------- */
export async function renderCompareLab(container, {api, isCurrent}) {
  container.innerHTML = skeleton('cards');
  const [playersRes, heroesRes, teamsRes, matchupRes, catalogRes] = await Promise.all([
    api('/api/studio/view/players'),
    api('/api/studio/view/heroes?compact=1&own=1'),
    api('/api/studio/teams'),
    api('/api/studio/view/lane-matchups'),
    api('/api/catalog').catch(() => ({entries: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const players = (playersRes.players || []).map(player => ({...player}));
  const heroes = heroesRes.heroes || [];
  const teams = teamsRes.teams || [];
  const own = teamsRes.own || {};
  const matchups = matchupRes.rows || [];

  // 我方 / 对手标记：对手选手名单来自战队聚类
  const opponentNames = new Set();
  teams.forEach(team => (team.players || []).forEach(player => opponentNames.add(player.name)));
  players.forEach(player => { player.own = !opponentNames.has(player.label); });

  const playerItems = [];
  const seenLabels = new Set();
  players.forEach(player => {
    if (!player.label || seenLabels.has(player.label)) return;
    seenLabels.add(player.label);
    playerItems.push({
      id: player.label, name: player.label, own: player.own,
      sub: `${num(player.matches)} 局 · KDA ${player.kda == null ? '—' : num(player.kda, 2)} · ${(player.positions || []).join('/') || '—'}`,
    });
  });
  const heroIcons = {};
  (catalogRes.entries || []).filter(entry => entry.kind === 'hero' && entry.icon)
    .forEach(entry => { heroIcons[entry.name] = entry.icon; });
  const heroItems = heroes.map(hero => ({
    id: hero.hero, name: hero.hero, own: true, icon: heroIcons[hero.hero] || '',
    sub: `${num(hero.picks)} 次 · 胜率 ${hero.winRate == null ? '—' : num(hero.winRate, 1)}%`,
  }));
  const ownRaw = {winRate: own.winRate, ...(own.metrics || {})};
  const teamItems = [{id: '__own', name: '我方战队', own: true,
    sub: `${num(own.matches)} 局 · 胜率 ${own.winRate == null ? '—' : num(own.winRate, 1)}%`}]
    .concat(teams.map(team => ({
      id: team.id, name: team.displayName, own: false,
      sub: `${num(team.matches)} 局 · 胜率 ${team.winRate == null ? '—' : num(team.winRate, 1)}%`,
    })));

  const D = {
    players, matchups, playerItems, heroIcons,
    catalog: {
      player: {items: playerItems, byId: Object.fromEntries(playerItems.map(item =>
        [item.id, {id: item.id, name: item.name, own: item.own,
          raw: players.find(player => player.label === item.id) || {}}]))},
      hero: {items: heroItems, byId: Object.fromEntries(heroItems.map(item =>
        [item.id, {id: item.id, name: item.name, own: true, icon: item.icon, raw: heroes.find(hero => hero.hero === item.id) || {}}]))},
      team: {items: teamItems, byId: Object.fromEntries(teamItems.map(item =>
        [item.id, {id: item.id, name: item.name, own: item.own,
          raw: item.id === '__own' ? ownRaw : teams.find(team => team.id === item.id) || {}}]))},
    },
    pool: {
      player: players,
      hero: heroes,
      team: [ownRaw, ...teams],
    },
  };

  const tab = ['data', 'matchup', 'tier'].includes(location.hash.split('/')[1])
    ? location.hash.split('/')[1] : 'data';
  const tabs = [['data', '数据对比'], ['matchup', '对位对比'], ['tier', '层次对比']];

  const render = () => {
    const content = document.getElementById('cl-content');
    if (!content) return;
    if (tab === 'matchup') compareMatchupView(content, D, render);
    else if (tab === 'tier') compareTierView(content, D, render);
    else compareDataView(content, D, render);
  };

  container.innerHTML = pageHero({
    kicker: 'COMPARE LAB · 对比工作台',
    title: '对比工作台',
    lead: ['想比什么就拉什么：<b>数据对比</b>拉 2–4 个选手 / 英雄 / 战队看雷达与指标差，<b>对位对比</b>选我方与对方选手看同路直接交锋，<b>层次对比</b>把所有对象放进同一把尺子里排位。'],
    meta: [`${num(players.length)} 名选手`, `${num(heroes.length)} 个英雄`, `${num(teams.length)} 支对手`, `${num(matchups.length)} 个对位样本`],
  }) + `<div class="cl-tabs">${tabs.map(([key, label]) =>
      `<a class="cl-tab ${tab === key ? 'active' : ''}" href="#compare${key === 'data' ? '' : '/' + key}">${label}</a>`).join('')}</div>
    <div id="cl-content"></div>
    <div id="cl-depth"></div>`;

  render();
  appendDepthSections(container, [{id: 'compare_camp', note: '蓝红阵营偏差'}], {api, isCurrent});

  /* 层级深度图：选手层 / 英雄层各挂对应的深度分析，随层级切换重绘 */
  let lastType = null;
  const paintDepth = () => {
    if (S.type === lastType) return;
    lastType = S.type;
    const box = container.querySelector('#cl-depth');
    if (!box) return;
    const specs = S.type === 'player'
      ? [{id: 'cs_conversion', note: '补刀与发育转化'}, {id: 'cross_resource_output', note: '经济与输出产出'}]
      : S.type === 'hero'
        ? [{id: 'cross_lane_hero', note: '补刀对照'}, {id: 'equip_matrix', note: '出装分布'},
           {id: 'equip_impact', note: '装备对照'}, {id: 'stability', note: '英雄波动'}]
        : [];
    box.innerHTML = specs.map(spec => depthSection(spec)).join('');
    bindDepthSections(box, {api, isCurrent});
  };
  paintDepth();
  container.querySelectorAll('[data-type] [data-seg]').forEach(button => {
    button.addEventListener('click', () => setTimeout(paintDepth, 0));
  });
  if (!container.dataset.clOutside) {
    container.dataset.clOutside = '1';
    document.addEventListener('click', event => {
      if (!S.open || event.target.closest('.cl-picker')) return;
      S.open = '';
      const content = document.getElementById('cl-content');
      if (content) content.querySelectorAll('.cl-menu:not([hidden])')
        .forEach(menu => { menu.hidden = true; });
    }, true);
  }
}
