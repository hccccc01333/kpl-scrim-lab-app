/* Analyst-first homepage. Every information card navigates to a real workbench route.
   Keep sample provenance and drill-downs; never invent an inbox count. */
export function renderWorkspaceHome(payload, h) {
  const { esc, fmt, pct, time, portrait, route, icon, chart, score, resultName, sides, filters } = h;
  const summary = payload?.summary || {};
  const matches = Array.isArray(payload?.matches) ? payload.matches : [];
  const team = payload?.team || {};
  const process = payload?.process || {};
  const count = Number.isFinite(summary.matches) ? summary.matches : matches.length;
  const decided = Number.isFinite(summary.decided) ? summary.decided : 0;
  const wins = Number.isFinite(summary.wins) ? summary.wins : 0;
  const lost = Math.max(0, decided - wins);
  const heroes = Array.isArray(summary.topHeroes) ? summary.topHeroes : [];
  const latest = matches[0] || null;
  const dates = [...new Set(matches.map(m => m.date).filter(Boolean))].sort();
  const scope = dates.length > 1 ? `${dates[0]} 至 ${dates.at(-1)}` : dates.length ? `截至 ${dates[0]}` : '尚无日期';
  const scopeLabel = filters?.from || filters?.to ? `筛选范围 · ${scope}` : `数据范围 · ${scope}`;
  const iconArrow = icon('arrow');
  const metric = (href, eyebrow, value, detail, ico) => `
    <a class="wh-metric wh-link" href="${esc(href)}" aria-label="${esc(eyebrow + '：' + value + '，进入' + detail)}">
      <span class="wh-metric-top"><span>${esc(eyebrow)}</span>${icon(ico)}</span>
      <strong>${value}</strong><small>${esc(detail)}</small>
    </a>`;
  const actions = [
    ['ingest', '#ingest', '01', '采集与入库', '同步营地、导入截图与录屏', 'ingest'],
    ['decision', '#decision', '02', '赛训决策', '聚焦问题、查看证据与复盘', 'decision'],
    ['cross', '#cross', '03', '跨局研究', '识别趋势、关键事件与异常', 'matches'],
    ['bpcounter', '#bpcounter', '04', 'BP 抗针对', '对手禁选与我方英雄池', 'bp'],
    ['opponents', '#opponents', '05', '对手侦察', '研究对手的英雄与习惯', 'teams'],
    ['playerarchive', '#playerarchive', '06', '选手档案', '个人数据、分路与状态', 'players'],
    ['plan', '#plan', '07', '比赛与训练', '约训、计划与赛训记录', 'setup'],
    ['reports', '#reports', '08', '复盘报告', '研究成果与训练效果', 'matches'],
  ];
  const tiles = actions.map(([key, href, no, title, description, ico]) => `
    <a class="wh-tile wh-link" href="${esc(href)}" data-wh-target="${esc(key)}">
      <span class="wh-tile-head"><span class="wh-icon">${icon(ico)}</span><small>${no}</small></span>
      <strong>${esc(title)}</strong><span class="wh-tile-desc">${esc(description)}</span>
      <span class="wh-tile-arrow" aria-hidden="true">${iconArrow}</span>
    </a>`).join('');

  const latestHref = latest ? route('match', latest.key) : '#ingest';
  const latestBody = latest ? `
    <div class="wh-spot-head"><span>最近一局 · ${esc(latest.date || '日期待核对')}</span><span class="wh-spot-meta">${time(latest.duration)}</span></div>
    <div class="wh-spot-match"><div><small>本队</small><b>${esc(summary.teamName || '本队')}</b></div>
      <div class="wh-spot-result"><span>${esc(resultName[latest.result] || '结果未知')}</span><strong>${score(latest)}</strong></div>
      <div><small>对手</small><b>${esc(latest.opponent || '对手待命名')}</b></div></div>
    <div class="wh-spot-foot"><div class="wh-spot-heroes">${(latest.heroes || []).slice(0, 5).map(hero => portrait(hero)).join('') || '<span>阵容未记录</span>'}</div>
      <span>进入本局复盘 ${iconArrow}</span></div>` : `
    <div class="wh-spot-head">暂无最近对局</div><strong class="wh-spot-empty">先录入一场训练赛</strong>
    <div class="wh-spot-foot">打开采集入口 ${iconArrow}</div>`;
  const recent = matches.slice(0, 4).map(m => `
    <a class="wh-recent-row wh-link" href="${esc(route('match', m.key))}">
      <span class="wh-recent-date">${esc(m.date || '未标日期')}</span>
      <span class="wh-recent-name">${esc(m.opponent || '对手待命名')}<small>${esc(resultName[m.result] || '结果未知')}</small></span>
      <strong>${score(m)}</strong><span class="wh-recent-arrow">${iconArrow}</span>
    </a>`).join('') || '<p class="wh-empty">暂无对局；完成数据采集后这里会出现最近的比赛。</p>';
  const heroRows = heroes.slice(0, 4).map(item => `
    <a class="wh-hero-row wh-link" href="${esc(route('matches', 'hero=' + item.hero))}">
      ${portrait(item.hero)}<span><b>${esc(item.hero)}</b><small>${esc((item.positions || []).join(' / ') || '分路未标注')}</small></span>
      <strong>${fmt(item.picks)}<small>次出场</small></strong><span class="wh-row-arrow">${iconArrow}</span>
    </a>`).join('') || '<p class="wh-empty">当前范围暂无英雄数据。</p>';

  /* Preserve the overview's established 30-second alignment and thin-tail gate. */
  const games = (process.matches || []).filter(game => (game.points || []).length);
  const buckets = new Map();
  for (const game of games) for (const [t, value] of game.points || []) {
    if (!Number.isFinite(t) || !Number.isFinite(value)) continue;
    const key = Math.round(t / 30) * 30;
    const cell = buckets.get(key) || { sum: 0, n: 0 };
    cell.sum += value;
    cell.n += 1;
    buckets.set(key, cell);
  }
  const ordered = [...buckets.entries()].sort((a, b) => a[0] - b[0]);
  const minimum = Math.max(3, Math.round(games.length * 0.45));
  let end = ordered.length - 1;
  while (end >= 0 && ordered[end][1].n < minimum) end -= 1;
  const avgCurve = end >= 1 ? ordered.slice(0, end + 1).map(([t, cell]) => [t, Math.round(cell.sum / cell.n)]) : [];
  const averaged = games.length >= 3 && avgCurve.length >= 2;
  const curve = averaged ? avgCurve : (process.matches?.[0]?.points || []);
  const curveLabel = averaged ? `${games.length} 局平均，30 秒对齐，尾部低样本已截断` : '最近一局可用时间轴';
  const curveHtml = chart(curve, '本队经济差', averaged ? { note: `${games.length} 局平均 · ${curve.length} 个时间点` } : {});
  return `<div class="page home wh-home">
    <header class="wh-welcome">
      <div class="wh-welcome-copy"><span class="wh-eyebrow">KPL · ANALYST WORKSPACE</span>
        <h1>赛训工作台</h1>
        <p>从数据采集到战术研究、对局复盘和训练验证。${esc(scopeLabel)}${filters?.validation ? ' · 包含验证数据' : ''}</p>
      </div>
      <div class="wh-welcome-actions">
        <button type="button" class="wh-outline-action" data-action="filter">${icon('filter')} 数据范围</button>
        <a class="wh-solid-action wh-link" href="#ingest">新对局入库 ${iconArrow}</a>
      </div>
    </header>

    <section class="wh-priorities" aria-label="恢复工作">
      <a class="wh-spotlight wh-link" href="${esc(latestHref)}">${latestBody}</a>
      <div class="wh-side-actions">
        <a class="wh-next wh-link" href="#pending">
          <span class="wh-next-symbol">${icon('inbox')}</span><span><small>数据准备</small><b>待处理与数据核对</b>
          <em data-wh-inbox-count>读取待办中…</em></span><span class="wh-next-arrow">${iconArrow}</span>
        </a>
        <a class="wh-next wh-link" href="#plan">
          <span class="wh-next-symbol">${icon('setup')}</span><span><small>训练管理</small><b>约训与训练计划</b>
          <em>管理日程、训练目标与复盘</em></span><span class="wh-next-arrow">${iconArrow}</span>
        </a>
        <a class="wh-next wh-link" href="#sources">
          <span class="wh-next-symbol">${icon('sources')}</span><span><small>数据链路</small><b>数据来源与完整性</b>
          <em>查看采集来源与数据可用性</em></span><span class="wh-next-arrow">${iconArrow}</span>
        </a>
      </div>
    </section>

    <section class="wh-metrics" aria-label="当前范围的赛训概览">
      ${metric('#matches', '已记录对局', fmt(count) + ' 局', '进入对局档案', 'matches')}
      ${metric('#tempo', '有时间轴对局', fmt(summary.coverage?.timelineMatches) + ' 局', '进入经济与节奏分析', 'decision')}
      ${metric('#matches', '有胜负结果', fmt(decided) + ' 局', `${fmt(wins)} 胜 · ${fmt(lost)} 负，查看详情`, 'teams')}
      ${metric('#heroes', '当前常用英雄', heroes.length ? esc(heroes[0].hero) : '待录入', '查看英雄研究', 'heroes')}
    </section>

    <section class="wh-section-block" aria-labelledby="wh-work-title">
      <div class="wh-section-header"><div><span class="wh-kicker">WORKFLOW</span><h2 id="wh-work-title">从这里进入工作</h2>
        <p>按分析师工作流程组织，卡片直接进入对应模块。</p></div></div>
      <div class="wh-tiles">${tiles}</div>
    </section>

    <div class="home-decision" id="home-decision" data-home-decision></div>

    <section class="wh-research-layout" aria-label="数据研究与最近活动">
      <a class="wh-trend wh-link" href="#tempo">
        <div class="wh-panel-head"><div><span class="wh-kicker">TREND</span><h2>经济趋势研究</h2><p>${esc(curveLabel)}</p></div>
          <span class="wh-open" aria-hidden="true">${iconArrow}</span></div>
        <div class="wh-trend-visual">${curveHtml}</div>
        <div class="wh-panel-foot">进入阶段经济与时间轴分析 ${iconArrow}</div>
      </a>
      <section class="wh-simple-panel">
        <a class="wh-panel-head wh-head-link wh-link" href="#heroes"><div><span class="wh-kicker">HERO STUDY</span>
          <h2>本队英雄观察</h2><p>基于当前筛选范围的出场记录</p></div><span class="wh-open">${iconArrow}</span></a>
        <div class="wh-hero-list">${heroRows}</div>
      </section>
    </section>
    <section class="wh-simple-panel wh-latest-panel">
      <a class="wh-panel-head wh-head-link wh-link" href="#matches"><div><span class="wh-kicker">RECENT MATCHES</span>
        <h2>近期对局</h2><p>直接打开比赛复盘，或进入对局档案检索更多记录。</p></div>
        <span class="wh-open">${iconArrow}</span></a>
      <div class="wh-recent-list">${recent}</div>
    </section>
  </div>`;
}
