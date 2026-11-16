/* 大场挖掘卡片（series_insight 的前端渲染）
 *
 * 只做排版与图表，所有口径、分母、模型质量由 series_insight 提供。
 * 命名空间：si-*；颜色沿用 cross.css 的语义色，明暗主题自动跟随。
 */

const KIND_LABEL = {
  economy: '经济', fight: '团战', draft: 'BP', player: '选手',
  objective: '资源', similar: '历史对照', quality: '数据质量',
};
const SEV_LABEL = { high: '高优先', medium: '中优先', low: '低优先' };
const CONF_LABEL = { high: '高置信', medium: '中置信', low: '低置信' };
const TAG_LABEL = {
  comfort: '舒适', stretch: '生疏', strong: '强', weak: '弱',
  contested: '热', novel: '新', unpicked: '未选', banOnly: '仅B',
};
const SIDE_LABEL = { own: '我', foe: '敌', ownBan: '我B', foeBan: '敌B' };
const METRIC_LABEL = {
  samples: '样本点', games: '对局', auc: 'AUC', aucAt10: '10′ AUC',
  per1000At10: '10′ 每千经济', per1000At20: '20′ 每千经济', baseRate: '原始胜率',
  n: '样本', k: 'k', ownApps: '我方出场', foeApps: '对方出场',
  players: '选手', coverage: '有基线', corpusGames: '语料', historySeries: '历史大场',
};

export function renderInsightCards(data, h) {
  const insight = data && data.insight;
  if (!insight || !insight.available) return {};
  const { esc, fmt, num, card } = h;

  const gold = (v) => fmt.signed(v);
  const pct = (v, digits = 1) => (num(v) ? `${Number(v).toFixed(digits)}%` : '—');
  const ratioPct = (v, digits = 1) => (num(v) ? pct(v * 100, digits) : '—');
  const fixed = (v, digits = 1) => fmt.fixed(v, digits);
  const count = (v) => fmt.count(v);
  const ciText = (ci) => (Array.isArray(ci) ? `${pct(ci[0], 0)}–${pct(ci[1], 0)}` : '—');
  const conversionLine = (row, base) => (row && row.enough
    ? `${row.wins}/${row.n}（${pct(row.rate)}）· 历史 ${pct(base?.rate)}`
    : row && row.n ? `样本不足（${row.n} 局）` : '样本不足');
  const matchLink = (key, index) => `<a class="si-match-link" href="#match/${encodeURIComponent(key)}">G${esc(String(index ?? '—'))}</a>`;
  const heroChip = (hero) => {
    const name = typeof hero === 'string' ? hero : hero?.name;
    const apps = typeof hero === 'object' ? hero?.apps : null;
    const value = typeof hero === 'object' ? hero?.value : null;
    const tone = num(value) ? (value > 0.02 ? 'is-good' : value < -0.02 ? 'is-bad' : '') : '';
    const tags = (hero?.tags || []).map((tag) => `<span class="si-hero-tag">${esc(TAG_LABEL[tag] || tag)}</span>`).join('');
    return `<span class="si-hero-chip ${tone}" title="出场 ${num(apps) ? count(apps) : '—'} 局${num(value) ? ` · BP 价值 ${fmt.signed(value, 3)}` : ''}"><b>${esc(name || '—')}</b>${num(apps) ? `<i>${count(apps)}</i>` : ''}${tags}</span>`;
  };

  function links(list) {
    const seen = new Set();
    const items = [];
    for (const item of list || []) {
      if (!item || !item.matchKey) continue;
      const id = `${item.matchKey}:${item.gameIndex}`;
      if (seen.has(id)) continue;
      seen.add(id);
      items.push(matchLink(item.matchKey, item.gameIndex));
    }
    return items.slice(0, 10).join('');
  }

  function insightCard(item) {
    const evidence = (item.evidence || []).map((text) => `<span>${esc(text)}</span>`).join('');
    const gameLinks = links(item.links);
    return `<article class="si-insight is-${esc(item.severity || 'low')}">
      <div class="si-insight-head">
        <span class="si-kind">${esc(KIND_LABEL[item.kind] || item.kind || '')}</span>
        <b>${esc(item.title || '')}</b>
        <em>${esc(SEV_LABEL[item.severity] || item.severity || '')} · ${esc(CONF_LABEL[item.confidence] || item.confidence || '')}</em>
      </div>
      <p>${esc(item.detail || '')}</p>
      ${evidence ? `<div class="si-evidence">${evidence}</div>` : ''}
      ${gameLinks ? `<div class="si-links"><span>证据局</span>${gameLinks}</div>` : ''}
    </article>`;
  }

  function qualityBanner(quality) {
    const issues = [];
    if (quality && (quality.duplicates || []).length) {
      const text = quality.duplicates.slice(0, 4)
        .map((group) => group.gameIndexes.map((index) => `G${index}`).join('/'))
        .join('、');
      issues.push(`<li><b>重复局</b> ${esc(text)} 的过程数据完全相同：跨局比例会重复计算，先核实采集/编组。</li>`);
    }
    if (quality && ((quality.draftInvalid || []).length || (quality.sameRoster || []).length)) {
      const items = quality.draftInvalid?.length ? quality.draftInvalid : quality.sameRoster;
      issues.push(`<li><b>阵容异常</b> ${esc(items.slice(0, 6).map((item) => `G${item.gameIndex}`).join('、'))} 的 BP 名单缺失或双方相同，已从 BP 汇总剔除。</li>`);
    }
    if (!issues.length) return '';
    return `<div class="si-quality"><b>数据质量提示</b><ul>${issues.join('')}</ul></div>`;
  }

  function wpChart(flow) {
    const rows = (flow?.games || []).filter((game) => num(game.at10) && num(game.finalDiff));
    if (!rows.length) return '<p class="xc-muted">经济差数据不足，先看下方逐局结果。</p>';
    const leadRows = rows.filter((game) => game.at10 > 0);
    if (!leadRows.length) return '<p class="xc-muted">本期没有 10 分钟领先的局，直接看下方逐局结果。</p>';
    const wins = leadRows.filter((game) => game.result === 'win');
    const losses = leadRows.filter((game) => game.result === 'loss');
    const avg = (list, key) => list.length ? list.reduce((sum, item) => sum + (Number(item[key]) || 0), 0) / list.length : 0;
    const split = avg(leadRows, 'at10');
    const winFinal = wins.length ? avg(wins, 'finalDiff') : null;
    const lossFinal = losses.length ? avg(losses, 'finalDiff') : null;
    const max = Math.max(1000, Math.abs(split), Math.abs(winFinal || 0), Math.abs(lossFinal || 0)) * 1.18;
    const x = { start: 30, split: 330, end: 690 };
    const zero = 120;
    const y = (value) => zero - (Number(value) || 0) / max * 96;
    const splitY = y(split);
    const winY = winFinal == null ? null : y(winFinal);
    const lossY = lossFinal == null ? null : y(lossFinal);
    const winPath = winY == null ? '' : `<path class="si-branch-area is-win" d="M${x.split},${splitY} L${x.end},${winY} L${x.end},${splitY} Z"></path>
      <path class="si-branch-line is-win" d="M${x.split},${splitY} L${x.end},${winY}"></path>
      <circle class="si-branch-dot is-win" cx="${x.end}" cy="${winY}" r="5"></circle>`;
    const lossPath = lossY == null ? '' : `<path class="si-branch-area is-loss" d="M${x.split},${splitY} L${x.end},${lossY} L${x.end},${splitY} Z"></path>
      <path class="si-branch-line is-loss" d="M${x.split},${splitY} L${x.end},${lossY}"></path>
      <circle class="si-branch-dot is-loss" cx="${x.end}" cy="${lossY}" r="5"></circle>`;
    const techRows = rows.map((game) => `<tr>
      <td class="num"><a class="si-match-link" href="#match/${encodeURIComponent(game.matchKey)}">G${game.gameIndex}</a></td>
      <td><span class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span></td>
      <td class="num">${gold(game.at10)}</td>
      <td class="num">${gold(game.finalDiff)}</td>
      <td class="num">${game.wp ? pct(game.wp.at10) : '—'}</td>
      <td class="num">${game.wp ? pct(game.wp.end) : '—'}</td>
    </tr>`).join('');
    return `<div class="si-branch">
      <svg class="si-branch-svg" viewBox="0 0 720 240" preserveAspectRatio="none" role="img" aria-label="三局经济差分叉图">
        <line class="si-branch-grid" x1="0" x2="720" y1="48" y2="48"></line>
        <line class="si-branch-grid" x1="0" x2="720" y1="120" y2="120"></line>
        <line class="si-branch-grid" x1="0" x2="720" y1="192" y2="192"></line>
        <line class="si-branch-zero" x1="0" x2="720" y1="120" y2="120"></line>
        ${winPath}${lossPath}
        <path class="si-branch-stem" d="M${x.start},${zero} L${x.split},${splitY}"></path>
        <circle class="si-branch-dot is-stem" cx="${x.start}" cy="${zero}" r="3.5"></circle>
        <circle class="si-branch-dot is-split" cx="${x.split}" cy="${splitY}" r="5"></circle>
      </svg>
      <div class="si-branch-labels">
        <span>0′</span>
        <span>10′ · ${leadRows.length} 局都领先 ${gold(split)}</span>
        <span>终局 · ${wins.length ? `守住 ${wins.length} 局 ${gold(winFinal)}` : ''}${wins.length && losses.length ? ' / ' : ''}${losses.length ? `被翻 ${losses.length} 局 ${gold(lossFinal)}` : ''}</span>
      </div>
      <div class="si-branch-legend">
        <span><i class="is-stem"></i>0–10′ 都领先</span>
        ${wins.length ? `<span><i class="is-win"></i>守住并扩大 ${wins.length} 局</span>` : ''}
        ${losses.length ? `<span><i class="is-loss"></i>被翻 ${losses.length} 局</span>` : ''}
      </div>
      <div class="si-flow-stats">
        <div><span>10 分钟领先</span><b>${leadRows.length} / ${rows.length}</b></div>
        <div><span>领先后守住</span><b>${wins.length} / ${leadRows.length}</b></div>
        <div><span>三局终局差</span><b>${gold(rows.reduce((sum, game) => sum + game.finalDiff, 0))}</b></div>
      </div>
    </div>
    <details class="si-tech">
      <summary>逐局参考胜率（历史模型，不是本场预测）</summary>
      <div class="xc-table-wrap"><table class="xc-table">
        <thead><tr><th>局</th><th>结果</th><th class="num">10′ 差</th><th class="num">终局差</th><th class="num">参考胜率 · 10′</th><th class="num">参考胜率 · 终局</th></tr></thead>
        <tbody>${techRows}</tbody>
      </table></div>
      <p class="si-tech-note">参考胜率来自历史经济差模型，只说明“这种经济差在历史上通常值多少胜率”，不是对本场的预测。</p>
    </details>`;
  }


  function phaseVisual(phase, fight) {
    const rows = phase?.winLoss || [];
    const games = phase?.perGame || [];
    const fightRows = fight?.perGame || [];
    if (!rows.length && !games.length) return '<p class="xc-muted">阶段数据不足。</p>';
    const max = Math.max(1, ...rows.flatMap((row) => [Math.abs(Number(row.winMean) || 0), Math.abs(Number(row.lossMean) || 0)]));
    const widthOf = (value) => `${(Math.abs(Number(value) || 0) / max * 50).toFixed(1)}%`;
    const barOf = (value, cls) => `<i class="si-phase-bar is-${cls} ${Number(value) >= 0 ? 'is-pos' : 'is-neg'}" style="width:${widthOf(value)}"></i>`;
    const chart = rows.map((row) => `<div class="si-phase-row">
      <span class="si-phase-label">${esc(row.label)}</span>
      <span class="si-phase-track">${barOf(row.winMean, 'win')}${barOf(row.lossMean, 'loss')}</span>
      <span class="si-phase-values">
        <span><small>赢局</small><b class="is-win">${gold(row.winMean)}</b></span>
        <span><small>输局</small><b class="is-loss">${gold(row.lossMean)}</b></span>
      </span>
    </div>`).join('');
    const gameRows = games.map((game) => {
      const resource = fightRows.find((item) => Number(item.gameIndex) === Number(game.gameIndex)) || {};
      const decider = game.decider === 'early' ? '0–4′' : game.decider === 'mid' ? '4–10′' : game.decider === 'late' ? '10′+' : '—';
      const cell = (label, value) => `<span class="si-phase-cell"><small>${label}</small><b class="${Number(value) >= 0 ? 'is-up' : 'is-down'}">${gold(value)}</b></span>`;
      const resources = [];
      if (resource.dragon10Diff != null) resources.push(`龙 ${fmt.signed(resource.dragon10Diff)}`);
      if (resource.tower10Diff != null) resources.push(`塔 ${fmt.signed(resource.tower10Diff)}`);
      if (resource.fightRate != null) resources.push(`团 ${pct(resource.fightRate)}`);
      return `<div class="si-phase-game">
        <span class="si-bp-game"><a class="si-match-link" href="#match/${encodeURIComponent(game.matchKey)}">G${game.gameIndex}</a><i class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</i></span>
        <span class="si-phase-cells">${cell('0–4′', game.early)}${cell('4–10′', game.mid)}${cell('10′+', game.late)}</span>
        <span class="si-phase-key">关键 ${decider}</span>
        <span class="si-phase-res">${resources.join(' · ') || '—'}</span>
      </div>`;
    }).join('');
    const lateRow = rows[rows.length - 1];
    const takeaway = lateRow && num(lateRow.winMean) && num(lateRow.lossMean)
      ? `<div class="si-phase-takeaway"><b>分水岭</b><span>10 分钟后，赢局 ${gold(lateRow.winMean)}，输局 ${gold(lateRow.lossMean)}；差 ${gold(lateRow.winMean - lateRow.lossMean)}。领先能不能兑现，主要看这一段。</span></div>`
      : '';
    return `<div class="si-phase">
      <div class="si-phase-chart">${chart}</div>
      <div class="si-phase-legend"><span><i class="is-win"></i>赢局均值</span><span><i class="is-loss"></i>输局均值</span><span>横条从中间零点向两侧伸</span></div>
      <div class="si-phase-games">${gameRows}</div>
      ${takeaway}
    </div>`;
  }

  function conversionRow(label, row, baseline) {
    const delta = row && baseline && num(row.rate) && num(baseline.rate) ? row.rate - baseline.rate : null;
    const enough = row?.enough;
    const detail = enough
      ? `${row.wins}/${row.n} 局${baseline?.enough ? ` · 历史 ${pct(baseline.rate)}（${baseline.wins}/${baseline.n}）` : ''}`
      : row?.n ? `样本不足（${row.n} 局）` : '样本不足';
    const deltaHtml = num(delta) ? `<em class="${delta >= 0 ? 'is-up' : 'is-down'}">${fmt.signed(delta, 1)}pp</em>` : '';
    return `<div class="si-conv-row">
      <span>${esc(label)}</span>
      <b class="${enough ? '' : 'is-na'}">${enough ? pct(row.rate) : '—'}</b>
      <small>${detail}${deltaHtml}</small>
    </div>`;
  }

  function phaseTable(phase, fight) {
    const rows = (phase?.perGame || []).map((game) => {
      const resource = (fight?.perGame || []).find((item) => Number(item.gameIndex) === Number(game.gameIndex)) || {};
      const decider = game.decider === 'early' ? '0–4′' : game.decider === 'mid' ? '4–10′' : game.decider === 'late' ? '10′+' : '—';
      return `<tr>
        <td class="num"><a class="si-match-link" href="#match/${encodeURIComponent(game.matchKey)}">G${game.gameIndex}</a></td>
        <td><span class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span></td>
        <td class="num ${tone(game.early)}">${gold(game.early)}</td>
        <td class="num ${tone(game.mid)}">${gold(game.mid)}</td>
        <td class="num ${tone(game.late)}">${gold(game.late)}</td>
        <td>${decider}</td>
        <td class="num">${resource.dragon10Diff == null ? '—' : fmt.signed(resource.dragon10Diff)}</td>
        <td class="num">${resource.tower10Diff == null ? '—' : fmt.signed(resource.tower10Diff)}</td>
        <td class="num">${pct(resource.fightRate)}</td>
      </tr>`;
    }).join('');
    const phaseRows = (phase?.winLoss || []).map((item) => `<tr>
      <td>${esc(item.label)}</td><td class="num">${gold(item.winMean)}</td><td class="num">${gold(item.lossMean)}</td>
      <td class="num">${gold(item.diff)}</td><td class="num">${item.winN}/${item.lossN}</td>
    </tr>`).join('');
    return `<div class="xc-table-wrap"><table class="xc-table">
      <thead><tr><th>局</th><th>结果</th><th class="num">0–4′</th><th class="num">4–10′</th><th class="num">10′+</th><th>关键阶段</th><th class="num">10′ 龙</th><th class="num">10′ 塔</th><th class="num">团战</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="si-subhead">赢局 vs 输局（均值）</div>
    <div class="xc-table-wrap"><table class="xc-table"><thead><tr><th>阶段</th><th class="num">赢局</th><th class="num">输局</th><th class="num">差</th><th class="num">n</th></tr></thead><tbody>${phaseRows}</tbody></table></div>`;
  }

  function tone(value) {
    if (!num(value)) return '';
    if (value >= 1200) return 'is-good-2';
    if (value >= 300) return 'is-good-1';
    if (value <= -1200) return 'is-bad-2';
    if (value <= -300) return 'is-bad-1';
    return '';
  }

  function conversionTile(label, row, baseline) {
    const delta = row && baseline && num(row.rate) && num(baseline.rate) ? row.rate - baseline.rate : null;
    return `<div class="si-tile">
      <span>${esc(label)}</span>
      <b>${row?.enough ? pct(row.rate) : '—'}</b>
      <small>${row?.enough ? `${row.wins}/${row.n}` : row?.n ? `样本不足（${row.n} 局）` : '样本不足'}${baseline?.enough ? ` · 历史 ${pct(baseline.rate)}（${baseline.wins}/${baseline.n}）` : ''}${num(delta) ? ` · ${fmt.signed(delta, 1)}pp` : ''}</small>
    </div>`;
  }

  function shapeSpark(values) {
    const W = 96;
    const H = 30;
    const max = Math.max(1, ...values.map((value) => Math.abs(value)));
    const x = [2, W / 2, W - 2];
    const y = (value) => H / 2 - (value / max) * (H / 2 - 4);
    const points = values.map((value, index) => `${x[index].toFixed(1)},${y(value).toFixed(1)}`).join(' ');
    const dots = values.map((value, index) => `<circle class="${value >= 0 ? 'is-win' : 'is-loss'}" cx="${x[index].toFixed(1)}" cy="${y(value).toFixed(1)}" r="2.6" />`).join('');
    return `<svg class="si-shape-spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="早期到后期的经济曲线"><line class="si-shape-zero" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" /><polyline points="${points}" /><g>${dots}</g></svg>`;
  }

  function shapeCard(phase) {
    const clusters = phase?.clusters?.clusters || [];
    const path = phase?.path || [];
    if (!clusters.length) return '<p class="xc-muted">经济时间轴不足，暂不做局面形态归类。</p>';
    const pathHtml = path.map((label, index) => `<span class="si-path-pill ${label ? '' : 'na'}">G${index + 1}<b>${esc(label || '—')}</b></span>`).join('<i class="si-path-arrow">→</i>');
    const grouped = new Map();
    for (const cluster of clusters) {
      const raw = cluster.label || '未命名';
      const key = raw.includes('后程失守') ? '后程失守'
        : raw.includes('全程压制') ? '全程压制'
          : raw.includes('后程发力') ? '后程发力'
            : raw.includes('翻盘') ? '逆风翻盘'
              : raw.includes('拉锯') ? '拉锯' : raw;
      const item = grouped.get(key) || { label: key, n: 0, early: 0, mid: 0, late: 0 };
      const weight = Number(cluster.n) || 0;
      item.n += weight;
      item.early += (cluster.early || 0) * weight;
      item.mid += (cluster.mid || 0) * weight;
      item.late += (cluster.late || 0) * weight;
      grouped.set(key, item);
    }
    const desc = {
      '全程压制': '从头领先到尾，基本没给对手机会',
      '后程失守': '前中期领先，10 分钟后被追回或反超',
      '后程发力': '前中期落后，后面追回来',
      '逆风翻盘': '大部分时间落后，最后赢下',
      '拉锯': '领先和落后反复交换',
      '全程被动': '从头落后到尾',
    };
    const rows = [...grouped.values()]
      .sort((a, b) => b.n - a.n)
      .map((item) => {
        const early = item.n ? item.early / item.n : 0;
        const mid = item.n ? item.mid / item.n : 0;
        const late = item.n ? item.late / item.n : 0;
        return `<div class="si-shape-row" title="早期 ${fmt.signed(early * 1000)} · 中期 ${fmt.signed(mid * 1000)} · 后期 ${fmt.signed(late * 1000)}">
          <span class="si-shape-copy"><b>${esc(item.label)}</b><small>${esc(desc[item.label] || '经济曲线的走向')}</small></span>
          ${shapeSpark([early * 1000, mid * 1000, late * 1000])}
          <em>${count(item.n)} 局</em>
        </div>`;
      }).join('');
    const gameShapes = (phase?.perGame || []).map((game) => `<div class="si-shape-game">
      <span class="si-shape-game-id"><b>G${game.gameIndex}</b><em class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em></span>
      ${shapeSpark([game.early, game.mid, game.late])}
      <span class="si-shape-game-vals">${gold(game.early)} <i>→</i> ${gold(game.mid)} <i>→</i> ${gold(game.late)}</span>
    </div>`).join('');
    return `<div class="si-path">${pathHtml}</div>
      ${gameShapes ? `<div class="si-subhead">本场三局曲线</div><div class="si-shape-games">${gameShapes}</div>` : ''}
      <div class="si-subhead">语料里的形态</div>
      <div class="si-shapes">${rows}</div>
      <p class="xc-card-note">小图从左到右＝早期 / 中期 / 后期；点在零线上方＝领先，下方＝落后。只描述走势，不判断强弱。</p>`;
  }

  function draftCard(draft) {
    const series = draft?.series || {};
    const games = draft?.games || [];
    const verdictOf = (game) => game.edge > 0 ? ['BP 占优', 'is-up']
      : game.edge < 0 ? ['BP 下风', 'is-down'] : ['BP 持平', 'is-flat'];
    const edgeGames = games.filter((game) => game.edge > 0).length;
    const winGames = games.filter((game) => game.result === 'win');
    const winEdges = winGames.filter((game) => game.edge > 0).length;
    const rows = games.map((game) => {
      const [label, tone] = verdictOf(game);
      return `<div class="si-bp-row">
        <span class="si-bp-game"><a class="si-match-link" href="#match/${encodeURIComponent(game.matchKey)}">G${game.gameIndex}</a><i class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</i></span>
        <span class="si-bp-verdict ${tone}">${label}</span>
        <span class="si-bp-comfort">常用 ${ratioPct(game.ownComfort)} · 少用 ${ratioPct(game.ownStretch)}</span>
        <span class="si-bp-new">${(game.newOwn || []).length ? `新增 ${esc((game.newOwn || []).join('、'))}` : '没有新增英雄'}</span>
      </div>`;
    }).join('');
    const heroes = (draft?.heroes || []).slice(0, 14).map(heroChip).join('');
    const techRows = games.map((game) => `<tr class="${game.valid ? '' : 'is-thin'}">
      <td class="num"><a class="si-match-link" href="#match/${encodeURIComponent(game.matchKey)}">G${game.gameIndex}</a></td>
      <td><span class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span></td>
      <td class="num">${game.ownValue == null ? '—' : fmt.signed(game.ownValue, 3)}</td>
      <td class="num">${game.foeValue == null ? '—' : fmt.signed(game.foeValue, 3)}</td>
      <td class="num">${game.edge == null ? '—' : fmt.signed(game.edge, 3)}</td>
      <td>${esc(game.edgeLabel || '—')}</td>
      <td class="num">${ratioPct(game.ownComfort)}</td>
      <td class="num">${ratioPct(game.ownStretch)}</td>
    </tr>`).join('');
    return `<div class="si-factline">
      <span><b>${edgeGames}/${games.length}</b> 局 BP 占优</span>
      <span><b>${winEdges}/${winGames.length}</b> 赢局占优</span>
      <span>常用 <b>${ratioPct(series.comfortShare)}</b> · 少用 <b>${ratioPct(series.stretchShare)}</b></span>
      <span>英雄池 <b>${count(series.uniqueOwn)} / ${count(series.uniqueFoe)}</b></span>
    </div>
    <div class="si-bp-rows">${rows}</div>
    <div class="si-subhead">本场涉及的英雄（按热度排序）</div>
    <div class="si-hero-chips">${heroes || '<span class="xc-muted">没有可用阵容。</span>'}</div>
    ${series.invalidGames ? `<p class="xc-card-note">${count(series.invalidGames)} 局阵容异常，已从 BP 汇总剔除。</p>` : ''}
    <details class="si-tech">
      <summary>逐局 BP 价值明细（模型差值）</summary>
      <div class="xc-table-wrap"><table class="xc-table">
        <thead><tr><th>局</th><th>结果</th><th class="num">我方</th><th class="num">对方</th><th class="num">差值</th><th>判定</th><th class="num">常用</th><th class="num">少用</th></tr></thead>
        <tbody>${techRows}</tbody>
      </table></div>
      <p class="si-tech-note">BP 价值＝按历史胜率向 50% 收缩后的差值；只说明选人相对历史的高低，不是本场胜负的原因。</p>
    </details>`;
  }

  function sparkline(perGame) {
    const values = (perGame || []).map((game) => (num(game.composite) ? game.composite : null));
    if (values.filter((value) => value !== null).length < 2) return '<span class="xc-muted">—</span>';
    const W = 78;
    const H = 22;
    const scale = (value) => H / 2 - Math.max(-2.4, Math.min(2.4, value)) / 2.4 * (H / 2 - 3);
    const points = values.map((value, index) => (value === null ? null : [3 + index * (W - 6) / Math.max(1, values.length - 1), scale(value)]));
    const line = points.map((point, index) => (point ? `${index && points[index - 1] ? 'L' : 'M'}${point[0].toFixed(1)},${point[1].toFixed(1)}` : '')).filter(Boolean).join(' ');
    const dots = points.map((point, index) => {
      if (!point) return '';
      const result = perGame[index]?.result;
      return `<circle class="${result === 'win' ? 'win' : result === 'loss' ? 'loss' : 'na'}" cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.2"/>`;
    }).join('');
    return `<svg class="si-player-spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="状态分逐局走势"><line x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}"/><path d="${line}"/>${dots}</svg>`;
  }

  function playerCard(players) {
    const list = players?.players || [];
    const lineup = players?.lineup || {};
    if (!list.length) return '<p class="xc-muted">没有十人面板数据。</p>';
    const statusOf = (player) => player.composite > 0.3 ? ['↑ 高于平时', 'is-up']
      : player.composite < -0.3 ? ['↓ 低于平时', 'is-down'] : ['→ 接近平时', 'is-flat'];
    const trendOf = (player) => player.trend > 0.15 ? '走高' : player.trend < -0.15 ? '走低' : '平稳';
    const formText = { hot: '近况热', cold: '近况冷', stable: '近况稳' };
    const cards = list.map((player) => {
      const [status, tone] = statusOf(player);
      const baseline = player.baseline === 'player' ? `对比个人 ${count(player.baselineGames)} 局`
        : player.baseline === 'position' ? `对比同位置 ${count(player.baselineGames)} 局` : '无基线';
      return `<article class="si-player-card ${tone}">
        <header>
          <span class="si-player-ava">${esc((player.name || '?').slice(0, 1))}</span>
          <span class="si-player-id"><b title="${esc(player.name)}">${esc(player.name)}</b><small title="${esc(baseline)}">${esc(player.position)} · ${count(player.games)} 局</small></span>
          <em class="si-player-status ${tone}">${status}</em>
        </header>
        <div class="si-player-metrics">
          <span><small>KDA</small><b>${fixed(player.kda, 2)}</b></span>
          <span><small>分均经济</small><b>${fixed(player.gpm, 0)}</b></span>
          <span><small>分均输出</small><b>${fixed(player.dpm, 0)}</b></span>
          <span><small>参团</small><b>${pct(player.part)}</b></span>
          <span><small>对位经济</small><b class="${num(player.laneGold) ? (player.laneGold >= 0 ? 'is-up' : 'is-down') : ''}">${gold(player.laneGold)}<small>/分</small></b></span>
        </div>
        <footer>
          <span>${formText[player.form] || ''}${player.form ? ' · ' : ''}状态${trendOf(player)}</span>
          ${sparkline(player.perGame)}
          <small>逐局状态 · 右为最近</small>
        </footer>
      </article>`;
    }).join('');
    const rows = list.map((player) => `<tr>
      <td><b>${esc(player.name)}</b><small>${esc(player.position)}</small></td>
      <td class="num">${count(player.games)}</td>
      <td class="num">${fixed(player.kda, 2)}</td>
      <td class="num">${fixed(player.gpm, 0)}</td>
      <td class="num">${fixed(player.dpm, 0)}</td>
      <td class="num">${pct(player.part)}</td>
      <td class="num ${tone((player.laneGold || 0) * 60)}">${gold(player.laneGold)}<small>/分</small></td>
      <td class="num ${player.composite > 0.3 ? 'is-good-1' : player.composite < -0.3 ? 'is-bad-1' : ''}">${fmt.signed(player.composite, 2)}</td>
      <td><span class="si-form ${esc(player.form)}">${player.form === 'hot' ? '热' : player.form === 'cold' ? '冷' : player.form === 'stable' ? '稳' : '—'}</span><small>${esc(player.baseline === 'player' ? `个人 ${player.baselineGames} 局` : player.baseline === 'position' ? `同位置 ${player.baselineGames} 局` : '无基线')}</small></td>
      <td class="num">${fmt.signed(player.trend, 2)}</td>
      <td class="num">${fixed(player.consistency, 2)}</td>
      <td>${sparkline(player.perGame)}</td>
    </tr>`).join('');
    const teamStatus = num(lineup.teamComposite)
      ? (lineup.teamComposite > 0.15 ? '高于平时' : lineup.teamComposite < -0.15 ? '低于平时' : '接近平时')
      : '—';
    return `<div class="si-factline">
      <span><b>${count(lineup.unique)}</b> 人上场 · ${lineup.stable ? '五人均打满' : '存在轮换/缺局'}</span>
      <span>团队状态 <b>${teamStatus}</b></span>
      <span>有基线 <b>${count(lineup.baselineCoverage)}/${count(list.length)}</b></span>
      <span>不排名 · 数值明细在下方折叠</span>
    </div>
    <div class="si-player-grid">${cards}</div>
    <details class="si-tech">
      <summary>逐人技术明细（状态分 / 趋势 / 波动）</summary>
      <div class="xc-table-wrap"><table class="xc-table si-player-table">
        <thead><tr><th>选手</th><th class="num">局</th><th class="num">KDA</th><th class="num">GPM</th><th class="num">DPM</th><th class="num">参团</th><th class="num">对位经济</th><th class="num">状态分</th><th>基线</th><th class="num">趋势</th><th class="num">波动</th><th>逐局</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="si-tech-note">状态分＝GPM/DPM/参团/KDA/死亡相对个人（≥4 局）或同位置（≥8 局）基线的 z-score 复合，向 0 收缩；主卡片只显示「高于/接近/低于平时」，数值放这里。</p>
    </details>`;
  }

  function similarCard(similar) {
    const series = similar?.series || {};
    const games = similar?.games || [];
    const cards = (series.series || []).map((item) => {
      const diffs = (item.differences || []).slice(0, 3).map((diff) => {
        const value = diff.unit === 'pct' ? `${fixed(diff.delta, 1)}pp`
          : diff.unit === 'seconds' ? `${fmt.signed(diff.delta)}s` : `${fmt.signed(diff.delta)}`;
        const label = diff.key === 'at10' ? '10′差'
          : diff.key === 'early' ? '0–4′'
            : diff.key === 'mid' ? '4–10′'
              : diff.key === 'late' ? '10′+' : diff.label;
        return `<span>${esc(label)} ${value}</span>`;
      }).join('');
      const tone = item.similarity >= 0.6 ? 'is-close' : item.similarity >= 0.45 ? 'is-mid' : 'is-far';
      const label = item.similarity >= 0.6 ? '很像' : item.similarity >= 0.45 ? '较像' : '一般';
      return `<a class="si-similar-card" href="#biggame/${encodeURIComponent(item.seriesId)}" title="相似度 ${fixed(item.similarity, 3)}">
        <div class="si-similar-head"><b>${esc(item.opponent || '对手待补')}</b><em class="si-sim-label ${tone}">${label}</em></div>
        <span>BO${esc(String(item.bestOf || '—'))} · ${item.score?.us || 0}:${item.score?.them || 0} · ${esc(String(item.date || '').slice(0, 10))}</span>
        <small>${diffs || '无共同指标'}</small>
      </a>`;
    }).join('');
    const rows = games.map((game) => {
      const rate = num(game.expectedWinRate) ? game.expectedWinRate : null;
      const wins = rate != null && num(game.n) ? Math.round(rate / 100 * game.n) : null;
      const tone = rate == null ? 'is-flat' : rate >= 55 ? 'is-up' : rate <= 45 ? 'is-down' : 'is-flat';
      const neighbors = (game.neighbors || []).slice(0, 3).map((item) =>
        `<a class="si-match-link" href="#match/${encodeURIComponent(item.matchKey)}">${esc(item.result === 'win' ? '胜' : '负')}·${esc(String(item.date || '').slice(5, 10))}</a>`).join('');
      return `<div class="si-similar-row">
        <span class="si-similar-game"><b>G${game.gameIndex}</b><em class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em></span>
        <span class="si-similar-bar"><i class="${tone}" style="width:${rate == null ? 0 : rate.toFixed(1)}%"></i></span>
        <span class="si-similar-copy"><b>${rate == null ? '—' : pct(rate)}</b><small>历史相似 ${count(game.n)} 场${wins != null ? ` · 约 ${wins} 胜` : ''}</small></span>
        <span class="si-similar-neighbors">${neighbors || '<em class="xc-muted">—</em>'}</span>
      </div>`;
    }).join('');
    return `${cards ? `<div class="si-similar-grid">${cards}</div>` : `<p class="xc-muted">${esc(series.note || '历史大场不足。')}</p>`}
      <div class="si-subhead">每局放进历史相似局里看</div>
      <div class="si-similar-rows">${rows || '<p class="xc-muted">没有可对照的逐局数据。</p>'}</div>
      <p class="xc-card-note">条形＝历史相似局里赢的比例；只做历史对照，不是对本场的预测。</p>
      <details class="si-tech">
        <summary>逐局相似局明细（7 个邻居 / 区间）</summary>
        <div class="xc-table-wrap"><table class="xc-table">
          <thead><tr><th>局</th><th>结果</th><th class="num">参考胜率</th><th>95% 区间</th><th class="num">邻居</th><th>最像的局</th></tr></thead>
          <tbody>${games.map((game) => `<tr>
            <td class="num">G${game.gameIndex}</td>
            <td><span class="si-result ${game.result === 'win' ? 'win' : game.result === 'loss' ? 'loss' : 'na'}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span></td>
            <td class="num">${game.expectedWinRate == null ? '—' : pct(game.expectedWinRate)}</td>
            <td>${ciText(game.ci)}</td>
            <td class="num">${count(game.n)}</td>
            <td>${(game.neighbors || []).slice(0, 3).map((item) => `<a class="si-match-link" href="#match/${encodeURIComponent(item.matchKey)}">${esc(item.result === 'win' ? '胜' : '负')}·${esc(String(item.date || '').slice(5, 10))}</a>`).join('') || '—'}</td>
          </tr>`).join('')}</tbody>
        </table></div>
        <p class="si-tech-note">相似局用经济阶段、团战、资源、时长做 kNN；参考胜率取 7 个邻居，Beta(2,2) 平滑，避免全胜/全负给出 100%/0%。</p>
      </details>`;
  }

  function methodsCard(data, insight) {
    const methods = insight.methods || [];
    const sample = insight.sample || {};
    const coverage = data.coverage || {};
    const methodsHtml = methods.map((method) => {
      const metrics = Object.entries(method.metrics || {})
        .filter(([, value]) => value !== null && value !== undefined)
        .map(([key, value]) => `<span>${esc(METRIC_LABEL[key] || key)} <b>${esc(key === 'baseRate' ? `${value}%` : String(value))}</b></span>`).join('');
      return `<div class="si-method">
        <div class="si-method-head"><b>${esc(method.name)}</b><span class="si-rel ${method.reliable ? 'ok' : 'warn'}">${method.reliable ? '可用' : '参考'}</span></div>
        <p>${esc(method.detail)}</p>
        ${metrics ? `<div class="si-metrics">${metrics}</div>` : ''}
      </div>`;
    }).join('');
    const caveats = [...new Set([...(data.caveats || []), ...(insight.caveats || [])])]
      .map((item) => `<li>${esc(item)}</li>`).join('');
    return `<div class="si-cov">
      <span><b>${count(sample.games)}</b> 本场局数</span>
      <span><b>${count(sample.targetGamesWithResult)}</b> 有胜负</span>
      <span><b>${count(sample.at10Games)}</b> 有 10′</span>
      <span><b>${count(sample.fightGames)}</b> 有团战</span>
      <span><b>${count(sample.eventGames)}</b> 有事件</span>
      <span><b>${count(sample.playerGames)}</b> 有选手面板</span>
      <span><b>${count(sample.orderKnownGames)}</b> 有手序</span>
      <span><b>${count(sample.corpusGames)}</b> 历史语料（原始 ${count(sample.corpusRawGames)}）</span>
      <span><b>${count(sample.corpusSeries)}</b> 历史大场</span>
      <span><b>${count(coverage.withDetail)}</b> 有明细</span>
    </div>
    <div class="si-subhead">方法</div>
    ${methodsHtml || '<p class="xc-muted">没有可用方法说明。</p>'}
    <div class="si-subhead">覆盖与口径</div>
    <ul class="si-caveats-list">${caveats || '<li>没有额外口径警示。</li>'}</ul>`;
  }

  const summary = insight.summary || {};
  const sample = insight.sample || {};
  const flow = insight.flow || {};
  const phase = insight.phase || {};
  const draft = insight.draft || {};
  const players = insight.players || {};
  const fight = insight.fight || {};
  const similar = insight.similar || {};
  const quality = insight.quality || {};

  const digest = card({
    id: 'insight-digest', span: 5, kicker: '挖掘结论',
    sample: `${insight.insights?.length || 0} 条 · ${sample.games || 0} 局`,
    title: esc(digestTitle(insight)),
    lede: '每条结论都带样本量与可点进的证据局；关联不是因果。',
    body: `<div class="si-insights">${(insight.insights || []).map(insightCard).join('') || '<p class="xc-muted">没有达到证据阈值的信号。</p>'}</div>`,
    note: `<span>历史语料 <b>${count(sample.corpusGames)}</b> 局（原始 ${count(sample.corpusRawGames)} 局）</span><span>本场 <b>${count(sample.games)}</b> 局</span>`,
    method: '经济→胜率模型排除本系列赛；英雄价值按过程指纹去重后做经验贝叶斯收缩；相似局 kNN 排除同系列赛对局。',
  });

  const flowGames = flow.games || [];
  const leadGames = flowGames.filter((game) => num(game.at10) && game.at10 > 0);
  const leadHolds = leadGames.filter((game) => game.result === 'win').length;
  const leadCollapses = leadGames.filter((game) => game.result === 'loss').length;
  const flowTitle = flowGames.length
    ? `${leadGames.length} 局 10 分钟领先，赢下 ${leadHolds} 局${leadCollapses ? `，${leadCollapses} 局被翻` : ''}`
    : '过程数据不足，暂不画走势';
  const flowCard = card({
    id: 'insight-flow', span: 7, kicker: '大场走势',
    sample: `${flowGames.length} 局`,
    title: flowTitle,
    lede: `0–10 分钟 ${leadGames.length} 局都领先；10 分钟后，${leadHolds} 局继续扩大${leadCollapses ? `，${leadCollapses} 局被翻` : ''}。`,
    body: wpChart(flow),
    note: '主图是「都领先 → 分叉」；逐局参考胜率与模型明细收在下面折叠，避免把模型概率当成预测。',
    method: flow.model?.reliable
      ? `经济差→胜率参考模型：L2 逻辑回归（经济差 × 分钟交互），按对局分组 5 折交叉验证，训练集排除本系列赛；模型 ${flow.model.games} 局 / ${flow.model.n} 个检查点，AUC ${fixed(flow.model.auc, 3)}，10 分钟 AUC ${fixed(flow.model.aucAt10, 3)}。`
      : '模型区分度不足或样本不足，参考胜率只作形状参考。',
  });

  const phaseCard = card({
    id: 'insight-phase', span: 7, kicker: '阶段与资源',
    sample: `${phase.perGame?.length || 0} 局`,
    title: phaseTitle(phase),
    lede: '先看哪一段经济差与结果同向，再看 10 分钟资源与团战转化；短局/缺过程的局不补 0。',
    body: `${phaseVisual(phase, fight)}
      <div class="si-subhead">领先后的资源兑现</div>
      <div class="si-conv si-conv-2">
        ${conversionRow('10′ 领先', fight.series?.ahead10, fight.baseline?.ahead10)}
        ${conversionRow('领先且有资源', fight.series?.ahead10Obj, fight.baseline?.ahead10Obj)}
      </div>
      <details class="si-tech"><summary>逐局阶段与资源明细</summary>${phaseTable(phase, fight)}<p class="si-tech-note">阶段口径：0–4 分钟 / 4–10 分钟 / 10 分钟后；资源只统计有回放事件的局；团战胜率以有击杀的团为分母。</p></details>`,
    method: '阶段口径：0–4 分钟 / 4–10 分钟 / 10 分钟后；资源只统计有回放事件的局；团战胜率以有击杀的团为分母。',
  });

  const shapePanel = card({
    id: 'insight-shape', span: 5, kicker: '局面形态',
    sample: `${phase.clusters?.n || 0} 局语料`,
    title: phase.path?.filter(Boolean).length ? `形态路径：${phase.path.filter(Boolean).join(' → ')}` : '形态聚类',
    lede: '把每局经济曲线归成「全程压制 / 后程失守 / 后程发力 / 逆风翻盘 / 拉锯」；只描述走向，不解释原因。',
    body: `${shapeCard(phase)}<div class="si-subhead">团战与收尾</div><div class="si-conv si-conv-2">
      ${conversionRow('团战胜率 ≥60%', fight.series?.fightHigh, fight.baseline?.fightHigh)}
      ${conversionRow('团战胜率 ≤40%', fight.series?.fightLow, fight.baseline?.fightLow)}
    </div>`,
    method: '6 点相对时间经济曲线，标准化后 k-means（固定随机种子）；标签是启发式命名；兑现率只统计有资源/团战的局。',
  });

  const draftPanel = card({
    id: 'insight-draft', span: 12, kicker: 'BP 价值',
    sample: `${draft.games?.length || 0} 局`,
    title: draftTitle(draft),
    lede: '先看每局占优/下风，再看常用英雄与对手回应；模型差值收在下方折叠。',
    body: draftCard(draft),
    method: '按「选到该英雄的一方」统计胜率，Beta-Binomial 收缩（先验 8 局）+ Wilson 区间；已排除本系列赛，并按过程指纹去重语料。',
  });

  const playerPanel = card({
    id: 'insight-players', span: 12, kicker: '选手状态',
    sample: `${players.players?.length || 0} 人`,
    title: playerTitle(players),
    lede: '先看谁高于/低于平时：卡片按个人（或同位置）基线判断，不排名；数值明细收在下方折叠。',
    body: playerCard(players),
    method: 'GPM / DPM / 参团 / KDA / 死亡相对个人（≥4 局）或同位置（≥8 局）基线做 z-score，复合后向 0 收缩；不含沟通/指挥/视野。',
  });

  const similarPanel = card({
    id: 'insight-similar', span: 12, kicker: '历史对照',
    sample: `${similar.games?.length || 0} 局`,
    title: similar.series?.available ? `最像的 ${similar.series.series?.length || 0} 场大场` : '历史大场不足',
    lede: '先看最像的历史大场，再看每局在相似局里赢的比例；相似不是预测。',
    body: similarCard(similar),
    method: 'z-score 特征 + 欧氏距离（逐局 k=7）/ 余弦相似度（大场）；排除本系列赛对局，只做历史对照。',
  });

  const methodsPanel = `<details class="xc-method-panel" id="xc-insight-methods">
    <summary>
      <span class="xc-kicker">方法与口径</span>
      <b>这场大场能回答什么、不能回答什么</b>
      <small>模型质量、语料去重、覆盖与所有 caveat 都在这里；样本不足时对应模块会自动降级。</small>
      <em>展开</em>
    </summary>
    <div class="xc-method-body">${methodsCard(data, insight)}</div>
  </details>`;

  return {
    digest, flow: flowCard, phase: phaseCard, shape: shapePanel,
    draft: draftPanel, players: playerPanel, similar: similarPanel,
    methods: methodsPanel,
  };
}

function digestTitle(insight) {
  const list = insight?.insights || [];
  const clean = (text) => String(text || '').replace(/\s+(?=[一-龥])/g, '').trim();
  const quality = list.find((item) => item.kind === 'quality');
  const rest = list.filter((item) => item.kind !== 'quality');
  if (quality && rest.length) return `先核实一组重复局；${clean(rest[0].title)}。`;
  if (quality) return '先核实一组重复局，再使用本页结论。';
  if (rest.length) return `${clean(rest[0].title)}。`;
  return '本场没有达到证据阈值的信号。';
}

function phaseTitle(phase) {
  const rows = (phase?.winLoss || []).filter((row) => row.diff != null);
  if (!rows.length) return '阶段经济差';
  const top = rows.slice().sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))[0];
  const word = top.diff > 0 ? '赢局更高' : '输局更高';
  return `${top.label}是最大分水岭（${word} ${fmtSigned(top.diff)}）`;
}

function draftTitle(draft) {
  const series = draft?.series || {};
  if (series.edgeMean == null) return 'BP 价值与英雄池';
  if (series.winEdge == null || series.lossEdge == null) return `BP 端平均 ${fmtSigned(series.edgeMean, 3)}`;
  if (series.winEdge > 0.03 && series.lossEdge > 0.03) return 'BP 端整体占优，但优势没有稳定转化';
  if (series.winEdge > 0.03 && series.lossEdge <= 0.03) return 'BP 端优势集中在赢局';
  if (series.winEdge <= 0.03 && series.lossEdge < -0.03) return 'BP 端下风局基本都输了';
  return `BP 端平均 ${fmtSigned(series.edgeMean, 3)}`;
}

function playerTitle(players) {
  const list = (players?.players || []).filter((player) => player.composite != null);
  if (!list.length) return '选手状态';
  const hot = list.filter((player) => player.composite >= 0.8).length;
  const cold = list.filter((player) => player.composite <= -0.8).length;
  if (hot || cold) return `${hot} 人高于基线、${cold} 人低于基线`;
  return '选手状态都在基线附近';
}

function fmtSigned(value, digits = 0) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const abs = digits ? Math.abs(value).toFixed(digits) : Math.abs(Math.round(value)).toLocaleString('zh-CN');
  return `${value < 0 ? '−' : '+'}${abs}`;
}
