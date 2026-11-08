/* 数据看板：一屏看清「打了多少、赢在哪、谁在产出、英雄怎么用」。
   与团队复盘的分工：复盘给判断，看板给事实与明细入口。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null
  ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits})
  : '—';
// 柱子上的数字要能一眼读完：超过一千用 k，完整值放在 title 里。
const compact = value => {
  if (!Number.isFinite(Number(value))) return '—';
  const v = Number(value);
  if (Math.abs(v) < 1000) return signed(v);
  const sign = v > 0 ? '+' : '-';
  return `${sign}${(Math.abs(v) / 1000).toFixed(1)}k`;
};

const signed = (value, digits = 0) => {
  if (!Number.isFinite(Number(value)) || value === null) return '—';
  const v = Number(value);
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}`;
};
const RESULT = {win: '胜', loss: '负', draw: '平', unknown: '待确认'};

function clock(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return '—';
  const s = Math.round(Number(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function kpi(label, value, unit, note, tone = '') {
  return `<article class="db-kpi ${tone}">
    <span>${esc(label)}</span>
    <b>${value}${unit ? `<small>${esc(unit)}</small>` : ''}</b>
    <p>${esc(note)}</p>
  </article>`;
}

function diffColumns(matches) {
  const usable = matches.filter(m => m.goldDiff != null);
  if (!usable.length) {
    return `<div class="db-empty">这 ${matches.length} 场都没有可用的经济时间轴，画不出经济差。补全「时长 + 时间轴」后自动出现。</div>`;
  }
  const ordered = usable.slice().sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')) || String(a.key).localeCompare(String(b.key)));
  const max = Math.max(...ordered.map(m => Math.abs(m.goldDiff)), 1);
  const dateCount = ordered.reduce((acc, m) => acc.set(m.date, (acc.get(m.date) || 0) + 1), new Map());
  return `<div class="db-columns">
    ${ordered.map((m, idx) => {
      const up = m.goldDiff >= 0;
      const h = Math.max(3, Math.round(Math.abs(m.goldDiff) / max * 96));
      const label = (dateCount.get(m.date) || 0) > 1 ? `#${idx + 1}` : (m.date || '').slice(5);
      return `<div class="db-column" title="${esc(m.opponent || m.title || '')} ${signed(m.goldDiff)}">
        <span class="db-column-value ${up ? 'up' : 'down'}">${compact(m.goldDiff)}</span>
        <div class="db-column-track"><i class="${up ? 'up' : 'down'}" style="height:${h}%"></i></div>
        <span class="db-column-label">${esc(label)}</span>
        <span class="db-column-result ${m.result}">${RESULT[m.result] || '?'}</span>
      </div>`;
    }).join('')}
  </div>
  <p class="db-note">每根柱是一局，柱向上代表领先。同名日期用 #序号 区分；纵轴按本批最大值等比缩放（${num(max)}）。</p>`;
}

function heroBars(heroes) {
  if (!heroes.length) return '<div class="db-empty">还没有英雄使用记录。</div>';
  const top = heroes.slice(0, 10);
  const max = Math.max(...top.map(h => Number(h.picks) || 0), 1);
  return `<div class="db-bars">${top.map(h => `<div class="db-bar-row">
    <span class="db-bar-name">${esc(h.hero)}</span>
    <span class="db-bar-track"><i style="width:${Math.round((h.picks || 0) / max * 100)}%"></i></span>
    <b>${num(h.picks)}</b>
    <small>${h.winRate == null ? '—' : `${num(h.winRate, 0)}%`}</small>
  </div>`).join('')}</div>
  <p class="db-note">条形为出场次数；右侧是使用该英雄的场次胜率。</p>`;
}

function playerTable(players) {
  if (!players.length) return '<div class="db-empty">还没有本队选手的逐局数据。</div>';
  const top = players.filter(p => p.games >= 1).slice(0, 12);
  return `<div class="db-table-scroll"><table class="db-table db-player-table"><thead><tr>
    <th>选手</th><th>出场</th><th>KDA</th><th>场均击杀 / 死亡 / 助攻</th><th>场均经济</th><th>场均输出</th><th>胜率</th><th>英雄数</th>
  </tr></thead><tbody>${top.map(p => `<tr>
    <td class="main-cell">${esc(p.label)}${p.bound ? '' : '<span class="db-unbound">未绑定</span>'}</td>
    <td class="num">${num(p.games)}</td>
    <td class="num">${num(p.kda, 2)}</td>
    <td class="num muted">${num(p.kills / p.games, 1)} / ${num(p.deaths / p.games, 1)} / ${num(p.assists / p.games, 1)}</td>
    <td class="num">${num(p.avgGold)}</td>
    <td class="num">${num(p.avgDamage)}</td>
    <td class="num">${p.winRate == null ? '—' : `${num(p.winRate, 0)}%`}</td>
    <td class="num">${num(p.heroes.size)}</td>
  </tr>`).join('')}</tbody></table></div>
  <p class="db-note">未绑定的昵称可能是同一个人的不同 ID，绑定后会在选手身份里合并。${players.length > 12 ? `共 ${players.length} 个昵称，此处显示前 12。` : ''}</p>`;
}

/* 终局扩展指标（B 组）：营地面板实测值。每张卡同时给本队中位数、全样本对照、
   P25–P75 分布带和数据覆盖率，避免「多几列数字但没回答任何问题」。 */
const EXT_METRICS = [
  {key: 'cs', label: '补刀', unit: '次', digits: 0},
  {key: 'jungleGold', label: '野怪经济', unit: '金', digits: 0},
  {key: 'control', label: '控制效果', unit: '', digits: 0},
  {key: 'healing', label: '治疗量', unit: '', digits: 0},
  {key: 'towerDamage', label: '对塔伤害', unit: '', digits: 0},
  {key: 'damageConversion', label: '伤害转化比', unit: '', digits: 2},
  {key: 'takenPerDeath', label: '每死承伤', unit: '', digits: 0},
];

const extNum = value => (Number.isFinite(Number(value)) && value !== null && value !== ''
  ? Number(value) : null);

function quantile(sorted, p) {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0];
  const pos = (sorted.length - 1) * p;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function extValues(rows, key) {
  // 后端对缺失的 damageConversion / takenPerDeath 会用 A 组派生并标记
  // derivedFields。派生比值（输出/经济）与营地实测口径不同，按
  // docs/metric_registry.md 的纪律「不与实测值混算」，这里直接剔除派生行。
  return rows
    .filter(row => !(row.derivedFields || []).includes(key))
    .map(row => extNum(row[key]))
    .filter(value => value !== null).sort((a, b) => a - b);
}

function extendedSection(ownRows, allRows) {
  const total = allRows.length;
  const cards = EXT_METRICS.map(metric => {
    const own = extValues(ownRows, metric.key);
    const all = extValues(allRows, metric.key);
    const p25 = quantile(own, 0.25), p50 = quantile(own, 0.5), p75 = quantile(own, 0.75);
    const reference = quantile(all, 0.5);
    const delta = p50 != null && reference != null ? p50 - reference : null;
    const deltaPct = delta != null && reference ? delta / Math.abs(reference) * 100 : null;
    const coverage = ownRows.length ? own.length / ownRows.length * 100 : 0;
    const tone = delta == null || delta === 0 ? 'flat' : delta > 0 ? 'pos' : 'neg';
    // 用全样本 P90 做尺度上限，避免个别极端值把分布带压成一条线。
    const scale = Math.max(1, (quantile(all, 0.9) || 0) * 1.15, p75 || 0);
    const P = value => Math.max(0, Math.min(100, (value || 0) / scale * 100));
    const rangeTitle = p25 != null ? `P25 ${num(p25, metric.digits)} / P50 ${num(p50, metric.digits)} / P75 ${num(p75, metric.digits)}` : '暂无样本';
    const cmp = deltaPct == null ? '全样本暂无对照'
      : `全样本 ${num(reference, metric.digits)} · <em class="${tone}">${signed(deltaPct, 1)}%</em>`;
    return `<article class="db-ext-card">
      <div class="db-ext-top"><b>${esc(metric.label)}</b><span>${own.length}/${ownRows.length} 行有值</span></div>
      <div class="db-ext-value ${p50 == null ? 'empty' : ''}">${p50 == null ? '—' : num(p50, metric.digits)}${p50 != null && metric.unit ? `<small>${esc(metric.unit)}</small>` : ''}</div>
      <div class="db-ext-cmp">本队中位 · ${cmp}</div>
      <div class="db-ext-range" title="${esc(rangeTitle)}">
        ${p25 != null ? `<i style="left:${P(p25).toFixed(1)}%;width:${Math.max(1, P(p75) - P(p25)).toFixed(1)}%"></i>` : ''}
        ${p50 != null ? `<b style="left:${P(p50).toFixed(1)}%"></b>` : ''}
      </div>
      <div class="db-ext-cov"><i style="width:${coverage.toFixed(1)}%"></i></div>
      <div class="db-ext-foot">
        <span>${p25 == null ? 'P25 — · P75 —' : `P25 ${num(p25, metric.digits)} · P75 ${num(p75, metric.digits)}`}</span>
        <span>覆盖 ${num(coverage, 0)}%</span>
      </div>
    </article>`;
  }).join('');

  const withData = EXT_METRICS.some(metric => extValues(allRows, metric.key).length);
  // 补刀不会被派生，用它是否缺失判断该行所在对局有没有导入营地面板。
  const noPanel = allRows.filter(row => extNum(row.cs) === null).length;
  return `${withData ? `<div class="db-ext-grid">${cards}</div>` : `<div class="db-ext-empty">
      当前筛选下没有营地十人面板的扩展指标。导入营地详情后本区会自动出现；未导入的对局保持缺失，不估算、不派生。
    </div>`}
    <p class="db-ext-note"><b>口径</b>：只统计营地 <code>battledetail</code> 十人面板实测终局值；
      「全样本」含对手十人，只作整体对照，<b>不是同分路基线</b>。
      当前筛选 ${num(total)} 行、本队 ${num(ownRows.length)} 行，其中 ${num(noPanel)} 行所在对局没有营地面板 → 显示缺失。
      <b>伤害转化比 / 每死承伤</b>在缺面板时后端会用 A 组派生（输出÷经济、承伤÷死亡）并标记
      <code>derivedFields</code>，与营地实测不是同一口径，本区已剔除派生值、<b>不与实测混算</b>。
      若已开启「排除验证数据」，历史测试数据被剔除后样本会明显变少。
      分路按营地坐标映射为中文路名：对抗路 / 打野 / 中路 / 发育路 / 游走，本页不给出分路结论。</p>`;
}

function matchRows(matches) {
  if (!matches.length) return '<div class="db-empty">还没有比赛记录。</div>';
  return `<div class="db-table-scroll"><table class="db-table"><thead><tr>
    <th>日期</th><th>对手 / 标题</th><th>比分</th><th>经济差</th><th>时长</th><th>缺项</th>
  </tr></thead><tbody>${matches.slice(0, 12).map(m => {
    const s = m.scores || {};
    const own = m.ownCamp === 'blue' ? s.blue ?? s.left : m.ownCamp === 'red' ? s.red ?? s.right : s.left;
    const enemy = m.ownCamp === 'blue' ? s.red ?? s.right : m.ownCamp === 'red' ? s.blue ?? s.left : s.right;
    return `<tr class="clickable" data-open="${esc(m.key)}">
      <td>${esc(m.date || '—')}</td>
      <td class="main-cell">${esc(m.opponent || m.title || '未命名')}${m.isSeed ? '<span class="db-seed">测试</span>' : ''}</td>
      <td>${own != null && enemy != null ? `${num(own)}:${num(enemy)}` : '—'}</td>
      <td class="num ${m.goldDiff == null ? '' : m.goldDiff >= 0 ? 'up' : 'down'}">${m.goldDiff == null ? '—' : signed(m.goldDiff)}</td>
      <td class="num">${clock(m.duration)}</td>
      <td class="muted">${(m.missing || []).length ? esc(m.missing.join('、')) : '完整'}</td>
    </tr>`;
  }).join('')}</tbody></table></div>`;
}

export async function renderDashboard(container, {api, workspace, isCurrent, query, filters}) {
  const [matchesView, dataset] = await Promise.all([
    api('/api/studio/view/matches' + query() + '&limit=200&offset=0'),
    api('/api/studio/dataset', {dataset: 'records', filters: {...filters, includePartial: true}, deduplicate: true}),
  ]);
  if (isCurrent && !isCurrent()) return;
  const matches = matchesView.matches || [];
  const summary = matchesView.summary || {};
  const quality = workspace?.overview?.dataQuality || null;
  const teamName = workspace?.overview?.teamName || '本队';
  const ownRows = (dataset.rows || []).filter(row => row.isOwn);

  // 本队英雄使用：只统计自己这边，避免把对手英雄算进英雄池。
  const heroMap = new Map();
  ownRows.forEach(row => {
    if (!row.hero) return;
    const item = heroMap.get(row.hero) || {hero: row.hero, picks: 0, wins: 0, decided: 0, kills: 0, gold: 0};
    item.picks += 1;
    if (row.result === 'win') item.wins += 1;
    if (row.result === 'win' || row.result === 'loss') item.decided += 1;
    item.kills += Number(row.kills) || 0;
    item.gold += Number(row.gold) || 0;
    heroMap.set(row.hero, item);
  });
  const heroes = [...heroMap.values()].map(h => ({
    ...h, winRate: h.decided ? h.wins / h.decided * 100 : null,
  })).sort((a, b) => b.picks - a.picks || (b.winRate ?? -1) - (a.winRate ?? -1));

  // 队员产出：按昵称聚合，未绑定的标注出来。
  const playerMap = new Map();
  ownRows.forEach(row => {
    const key = row.label || '未识别';
    const item = playerMap.get(key) || {label: key, bound: !!row.bound, games: 0, kills: 0, deaths: 0, assists: 0, gold: 0, damage: 0, taken: 0, wins: 0, decided: 0, heroes: new Set()};
    item.games += 1;
    item.bound = item.bound || !!row.bound;
    item.kills += Number(row.kills) || 0;
    item.deaths += Number(row.deaths) || 0;
    item.assists += Number(row.assists) || 0;
    item.gold += Number(row.gold) || 0;
    item.damage += Number(row.damage) || 0;
    item.taken += Number(row.taken) || 0;
    if (row.result === 'win') item.wins += 1;
    if (row.result === 'win' || row.result === 'loss') item.decided += 1;
    if (row.hero) item.heroes.add(row.hero);
    playerMap.set(key, item);
  });
  const players = [...playerMap.values()]
    .map(p => ({...p, kda: (p.kills + p.assists) / Math.max(1, p.deaths),
      avgGold: p.gold / Math.max(1, p.games), avgDamage: p.damage / Math.max(1, p.games),
      winRate: p.decided ? p.wins / p.decided * 100 : null}))
    .sort((a, b) => b.games - a.games || b.kda - a.kda);

  const decided = Number(summary.wins || 0) + Number(summary.losses || 0);
  const winRate = decided ? Number(summary.wins || 0) / decided * 100 : null;
  const diffs = matches.map(m => m.goldDiff).filter(v => v != null);
  const avgDiff = diffs.length ? diffs.reduce((a, b) => a + b, 0) / diffs.length : null;
  const kills = matches.map(m => m.own?.kills).filter(v => v != null);
  const deaths = matches.map(m => m.own?.deaths).filter(v => v != null);
  const avgKills = kills.length ? kills.reduce((a, b) => a + b, 0) / kills.length : null;
  const avgDeaths = deaths.length ? deaths.reduce((a, b) => a + b, 0) / deaths.length : null;
  const durations = matches.map(m => m.duration).filter(Boolean);
  const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
  const timelineCount = matches.filter(m => m.hasTimeline).length;

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">DASHBOARD · 数据看板</span>
        <h1>${esc(teamName)} 数据看板</h1>
        <p>事实层：打了多少、每局差多少、英雄怎么用、数据缺在哪。判断和结论在团队复盘。</p>
        <div class="page-facts">
          <span>${num(matches.length)} 场</span>
          <span>${num(timelineCount)} 场有经济时间轴</span>
          <span>${num(heroes.length)} 个英雄有记录</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#team">团队复盘</a>
        <a class="button" href="#matches">比赛档案</a>
        <a class="button" href="#depth/compare_camp">蓝红数据体检</a>
        <a class="button" href="#lab">统计实验</a>
        <button class="button" data-print>打印 / PDF</button>
      </div>
    </div>

    <section class="db-kpis">
      ${kpi('比赛场次', num(matches.length), '场', `${num(decided)} 场有胜负 · ${num((summary.complete) || 0)} 场十人齐全`)}
      ${kpi('胜率', winRate == null ? '—' : num(winRate, 1), '%', `${num(summary.wins)} 胜 ${num(summary.losses)} 负`, winRate != null && winRate >= 50 ? 'good' : 'warn')}
      ${kpi('场均终局经济差', avgDiff == null ? '—' : signed(avgDiff), '', diffs.length ? `${diffs.length} 场可算` : '缺时间轴', avgDiff == null ? 'dim' : avgDiff >= 0 ? 'good' : 'bad')}
      ${kpi('场均击杀 / 死亡', avgKills == null ? '—' : `${num(avgKills, 1)} / ${num(avgDeaths, 1)}`, '', '本队五人合计', '')}
      ${kpi('场均时长', avgDuration == null ? '—' : clock(avgDuration), '', durations.length ? `${durations.length} 场有记录` : '缺时长', avgDuration == null ? 'dim' : '')}
      ${kpi('全库档案完整度', quality?.score == null ? '—' : num(quality.score), '%', quality?.seedMatches ? `含 ${quality.seedMatches} 场验证数据` : '全库字段检查', (quality?.score ?? 0) >= 75 ? 'good' : 'warn')}
    </section>

    <div class="db-two">
      <section class="tp-card">
        <header><h2>逐局经济差</h2><p>一眼看出哪几局是压着打、哪几局是咬牙赢</p></header>
        ${diffColumns(matches)}
      </section>
      <section class="tp-card">
        <header><h2>本队英雄使用</h2><p>只看我方；出场次数与胜率，判断英雄池是否过窄</p></header>
        ${heroBars(heroes)}
      </section>
    </div>

    <section class="tp-card db-ext">
      <header><h2>终局扩展指标</h2><p>营地十人面板实测 · 本队中位数与全样本对照，缺失显示 —，不估算</p></header>
      ${extendedSection(ownRows, dataset.rows || [])}
    </section>

    <section class="tp-card">
      <header><h2>队员产出</h2><p>按出场场次平均，不是分均；对局时长已由营地结算面板补齐，分均换算在过程分析中计算</p></header>
      ${playerTable(players)}
    </section>

    <section class="tp-card">
      <header><h2>逐局明细</h2><p>最近 12 场；点任意一行进入对局详情</p></header>
      ${matchRows(matches)}
    </section>

    ${quality && (quality.checks || []).some(c => c.missing > 0) ? `<section class="tp-card db-gaps">
      <header><h2>数据缺口</h2><p>这些缺口直接影响上面的数字怎么读</p></header>
      <div class="db-gap-grid">${quality.checks.map(c => `<div class="db-gap ${c.missing ? 'bad' : 'ok'}">
        <div><strong>${esc(c.label)}</strong><span>${c.missing ? `缺 ${c.missing}/${c.total}` : '齐全'}</span></div>
        <div class="db-gap-track"><i style="width:${c.total ? Math.round((c.total - c.missing) / c.total * 100) : 0}%"></i></div>
        <p>${esc(c.hint)}</p>
      </div>`).join('')}</div>
      <div class="pf-actions"><a class="button primary" href="#matches">去补全档案</a></div>
    </section>` : ''}
  `;

  container.addEventListener('click', (event) => {
    const row = event.target.closest('[data-open]');
    if (row) location.hash = '#match/' + encodeURIComponent(row.dataset.open);
  });
}
