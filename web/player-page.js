/* 选手表现：只负责「看数据」，不做身份绑定。
   绑定统一在「绑定」组（录入 / 对局分边），战队卡片在「战队档案」，这里只在未绑定时提示。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

const COLUMNS = [
  {key: 'games', label: '场次', align: 'num'},
  {key: 'kda', label: 'KDA', align: 'num'},
  {key: 'participation', label: '参团率', align: 'num', unit: '%'},
  {key: 'goldShare', label: '经济占比', align: 'num', unit: '%'},
  {key: 'damageShare', label: '输出占比', align: 'num', unit: '%'},
  {key: 'avgGold', label: '场均经济', align: 'num'},
  {key: 'avgDamage', label: '场均输出', align: 'num'},
  {key: 'winRate', label: '胜率', align: 'num', unit: '%'},
  {key: 'heroCount', label: '英雄数', align: 'num'},
];

function sparkline(points, {width = 132, height = 34} = {}) {
  if (!points.length) return '';
  if (points.length === 1) {
    return `<svg class="pl-spark" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <circle cx="${width / 2}" cy="${height / 2}" r="3" fill="#2f6fe4"/>
    </svg>`;
  }
  const values = points.map(p => p.value);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const x = i => 4 + i / (points.length - 1) * (width - 8);
  const y = v => height - 4 - (v - min) / span * (height - 8);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(' ');
  return `<svg class="pl-spark" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <path d="${d}" fill="none" stroke="#2f6fe4" stroke-width="1.6" stroke-linejoin="round"/>
    ${points.map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="2" fill="#2f6fe4"><title>${esc(p.label)}：${num(p.value, 2)}</title></circle>`).join('')}
  </svg>`;
}

function metric(label, value, note) {
  return `<div class="pl-metric"><span>${esc(label)}</span><b>${value}</b><small>${esc(note)}</small></div>`;
}

function trendCard(player, position, series) {
  const heroes = (player.heroes || []).slice(0, 6);
  const winRate = player.decided ? player.winRate : null;
  const recent = series.slice(-6);
  return `<article class="pl-card">
    <header>
      <span class="pl-avatar">${esc((player.label || '?').slice(0, 2))}</span>
      <div class="pl-id">
        <h3>${esc(player.label)}</h3>
        <p>${position ? `${esc(position)} · ` : ''}${num(player.games)} 场${player.games < 3 ? ' · 样本偏少' : ''}</p>
      </div>
      ${winRate == null ? '' : `<span class="pl-winrate ${winRate >= 50 ? 'good' : 'bad'}">${num(winRate, 0)}%</span>`}
    </header>
    <div class="pl-trend">
      <div class="pl-trend-head"><span>逐局 KDA</span><small>${recent.length > 1 ? `最近 ${recent.length} 场` : '仅 1 场'}</small></div>
      ${sparkline(recent.map(r => ({value: r.kda, label: r.date || r.label})))}
    </div>
    <div class="pl-metrics">
      ${metric('KDA', num(player.kda, 2), `${num(player.kills)}/${num(player.deaths)}/${num(player.assists)}`)}
      ${metric('参团率', player.participation == null ? '—' : `${num(player.participation, 0)}%`, '本队击杀参与')}
      ${metric('经济占比', player.goldShare == null ? '—' : `${num(player.goldShare, 1)}%`, '队内份额')}
      ${metric('输出占比', player.damageShare == null ? '—' : `${num(player.damageShare, 1)}%`, '队内份额')}
    </div>
    ${heroes.length ? `<div class="pl-heroes">${heroes.map(h => `<span>${esc(h.hero)} <b>${num(h.matches)}</b></span>`).join('')}</div>` : ''}
    <footer><a class="pl-link" href="#player/${encodeURIComponent(player.label)}">看逐局记录 →</a></footer>
  </article>`;
}

export async function renderPlayers(container, {api, workspace, isCurrent}) {
  // 只统计本队：heroes/players 聚合包含对手，会把敌方同名昵称也算进来。
  const dataset = await api('/api/studio/dataset', {
    dataset: 'records',
    filters: {sources: ['db', 'bundle', 'sheet'], includePartial: true, excludeSeeds: localStorage.getItem('excludeSeeds') === '1'},
    deduplicate: true,
  });
  if (isCurrent && !isCurrent()) return;
  const rows = (dataset.rows || []).filter(row => row.isOwn);
  const grouped = new Map();
  rows.forEach(row => {
    // 按昵称合并：同一个人在不同对局可能分到蓝/红方，camp 前缀不应拆开身份。
    const key = row.label || '未识别';
    const item = grouped.get(key) || {
      key, label: row.label || '未识别', bound: false, games: 0, wins: 0, decided: 0,
      kills: 0, deaths: 0, assists: 0, gold: 0, damage: 0,
      participation: [], goldShare: [], damageShare: [], heroes: new Map(), lastDate: '',
      series: [],
    };
    item.bound = item.bound || !!row.bound;
    item.games += 1;
    if (row.result === 'win') item.wins += 1;
    if (row.result === 'win' || row.result === 'loss') item.decided += 1;
    for (const k of ['kills', 'deaths', 'assists', 'gold', 'damage']) {
      if (Number.isFinite(Number(row[k]))) item[k] += Number(row[k]);
    }
    if (Number.isFinite(Number(row.participation))) item.participation.push(Number(row.participation));
    if (Number.isFinite(Number(row.goldShare))) item.goldShare.push(Number(row.goldShare));
    if (Number.isFinite(Number(row.damageShare))) item.damageShare.push(Number(row.damageShare));
    if (row.hero) item.heroes.set(row.hero, (item.heroes.get(row.hero) || 0) + 1);
    if (row.date && row.date > item.lastDate) item.lastDate = row.date;
    item.series.push({
      date: row.date, label: row.date || '',
      kda: (Number(row.kills) + Number(row.assists)) / Math.max(1, Number(row.deaths)),
      hero: row.hero,
    });
    grouped.set(key, item);
  });
  const avg = list => list.length ? list.reduce((a, b) => a + b, 0) / list.length : null;
  const players = [...grouped.values()].map(p => ({
    ...p,
    kda: (p.kills + p.assists) / Math.max(1, p.deaths),
    winRate: p.decided ? p.wins / p.decided * 100 : null,
    participation: avg(p.participation),
    goldShare: avg(p.goldShare),
    damageShare: avg(p.damageShare),
    avgGold: p.gold / Math.max(1, p.games),
    avgDamage: p.damage / Math.max(1, p.games),
    heroCount: p.heroes.size,
    heroes: [...p.heroes.entries()].sort((a, b) => b[1] - a[1]).map(([hero, matches]) => ({hero, matches})),
    series: p.series.sort((a, b) => String(a.date || '').localeCompare(String(b.date || ''))),
  }));

  const members = (workspace?.profile?.members || []).filter(m => !m.archived);
  const memberOf = name => members.find(m => (m.label || m.name) === name) || null;
  const positionOf = name => (memberOf(name) || {}).position || '';
  const tagsOf = name => (memberOf(name) || {}).tags || [];
  const bound = players.filter(p => p.bound).sort((a, b) => b.games - a.games);
  const unbound = players.filter(p => !p.bound);
  const ranked = players.slice().sort((a, b) => b.games - a.games || b.kda - a.kda);
  const totalMatches = workspace?.overview?.matches || 0;
  const coverage = players.length ? Math.round(bound.length / players.length * 100) : 0;

  let sortKey = 'games';
  let sortDir = -1;

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">PLAYERS · 选手数据</span>
        <h1>选手表现</h1>
        <p>本队选手的产出、经济份额、参团与英雄池。身份绑定在「绑定」里完成，这里只读数据。</p>
        <div class="page-facts">
          <span>${num(players.length)} 个本队身份</span>
          <span>${num(bound.length)} 个已绑定</span>
          <span>${num(totalMatches)} 场记录</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#compare/player">选手对比</a>
        <button class="button" data-print>打印 / PDF</button>
      </div>
    </div>

    ${coverage < 100 ? `<div class="pl-coverage">
      <div class="pl-coverage-main">
        <strong>身份覆盖率 ${num(coverage)}%</strong>
        <span>${num(players.length - bound.length)} 个昵称还没绑定：它们仍会出现在下面的排行里，但可能与同一名选手重复计数。</span>
      </div>
      <a class="pl-coverage-link" href="#identity">去绑定 →</a>
    </div>` : ''}

    ${!players.length ? `<div class="pl-empty pl-empty-lg">
      <strong>还没有本队选手数据</strong>
      <p>导入比赛并确认阵营后，本队十人数据会出现在这里。</p>
      <a class="button primary" href="#capture">导入比赛</a>
    </div>` : `
      <section class="pl-section">
        <header>
          <h2>产出排行</h2>
          <p>全部 ${num(players.length)} 个本队身份；点表头切换排序，五人局平均份额 20%</p>
          <div class="pl-filters">
            <button class="pl-filter${' active'}" data-filter="all">全部 ${num(players.length)}</button>
            <button class="pl-filter" data-filter="bound">已绑定 ${num(bound.length)}</button>
            <button class="pl-filter" data-filter="unbound">未绑定 ${num(unbound.length)}</button>
            <button class="pl-filter active" data-mingames="2" title="隐藏只出现 1 场的身份">只看 2 场以上</button>
          </div>
        </header>
        <div class="table-scroll">
          <table class="data-table pl-rank" id="pl-rank">
            <thead><tr>
              <th class="pl-th-name">选手</th>
              <th class="pl-th-lane">分路</th>
              <th>身份</th>
              ${COLUMNS.map(c => `<th class="${c.align}" data-sort="${c.key}">${c.label}${sortKey === c.key ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
        <div class="pl-more" id="pl-more"></div>
      </section>

      <section class="pl-section">
        <header><h2>趋势与英雄池</h2><p>折线是该身份逐局 KDA；只列场次最多的前 6 个，避免单场噪声</p></header>
        <div class="pl-grid">${ranked.slice(0, 6).map(p => trendCard(p, positionOf(p.label), p.series)).join('')}</div>
      </section>
    `}
  `;

  const tbody = container.querySelector('#pl-rank tbody');
  const moreBox = container.querySelector('#pl-more');
  let filter = 'all';
  let limit = 25;
  let minGames = 2;

  const source = () => {
    const base = filter === 'bound' ? bound : filter === 'unbound' ? unbound : players;
    return minGames > 1 ? base.filter(p => p.games >= minGames) : base;
  };

  const paintRows = () => {
    if (!tbody) return;
    const sorted = source().slice().sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (va == null && vb == null) return String(a.label).localeCompare(String(b.label));
      if (va == null) return 1;
      if (vb == null) return -1;
      return (Number(va) - Number(vb)) * sortDir;
    });
    const rows = sorted.slice(0, limit);
    const hidden = (filter === 'bound' ? bound : filter === 'unbound' ? unbound : players).length - sorted.length;
    tbody.innerHTML = rows.map(p => `<tr class="${p.bound ? '' : 'unbound'}">
      <td class="main-cell"><a class="pl-name-link" href="#player/${encodeURIComponent(p.label)}">${esc(p.label)}</a>${tagsOf(p.label).map(t => `<span class="pl-tag">${esc(t)}</span>`).join('')}</td>
      <td>${esc(positionOf(p.label) || '—')}</td>
      <td><span class="pl-badge ${p.bound ? 'bound' : ''}">${p.bound ? '已绑定' : '未绑定'}</span></td>
      ${COLUMNS.map(c => `<td class="${c.align}">${p[c.key] == null ? '—' : num(p[c.key], c.key === 'kda' ? 2 : c.unit === '%' ? 1 : 0)}${c.unit && p[c.key] != null ? c.unit : ''}</td>`).join('')}
    </tr>`).join('');
    if (moreBox) {
      if (!sorted.length) {
        moreBox.innerHTML = `<p class="pl-note">当前条件下没有选手。${minGames > 1 ? '试试关闭「只看 2 场以上」。' : ''}</p>`;
        return;
      }
      const foldNote = hidden > 0
        ? `<p class="pl-note">另有 ${num(hidden)} 个身份只因出现场次少被折叠，点「显示全部场次」查看。</p>` : '';
      moreBox.innerHTML = (sorted.length > limit
        ? `<button class="button" id="pl-show-all">显示全部 ${num(sorted.length)} 人</button>`
        : '') + foldNote;
      const btn = moreBox.querySelector('#pl-show-all');
      if (btn) btn.onclick = () => { limit = sorted.length; paintRows(); };
    }
  };
  paintRows();

  container.addEventListener('click', (event) => {
    const minBtn = event.target.closest('[data-mingames]');
    if (minBtn) {
      minGames = minGames > 1 ? 1 : 2;
      limit = 25;
      minBtn.classList.toggle('active', minGames > 1);
      minBtn.textContent = minGames > 1 ? '只看 2 场以上' : '显示全部场次';
      paintRows();
      return;
    }
    const filterBtn = event.target.closest('[data-filter]');
    if (filterBtn) {
      filter = filterBtn.dataset.filter;
      limit = 25;
      container.querySelectorAll('[data-filter]').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === filter));
      paintRows();
      return;
    }
    const th = event.target.closest('[data-sort]');
    if (!th) return;
    const key = th.dataset.sort;
    if (sortKey === key) sortDir *= -1;
    else { sortKey = key; sortDir = -1; }
    container.querySelectorAll('[data-sort]').forEach(cell => {
      const base = COLUMNS.find(c => c.key === cell.dataset.sort)?.label || '';
      cell.textContent = base + (cell.dataset.sort === sortKey ? (sortDir < 0 ? ' ↓' : ' ↑') : '');
    });
    paintRows();
  });
}
