/* The approved celadon composition. The artwork is decorative; every number comes from APIs. */
const list = (value) => Array.isArray(value) ? value : [];
const finite = (value) => typeof value === 'number' && Number.isFinite(value);

export function averageEconomy(process) {
  const games = list(process?.matches).filter((game) => list(game.points).some((point) => finite(point?.[0]) && point[0] >= 0 && finite(point?.[1])));
  const buckets = new Map();
  for (const game of games) {
    // One observation per match and 30-second bucket, so irregular sampling cannot overweight a match.
    const observations = new Map();
    for (const point of list(game.points)) {
      if (!finite(point?.[0]) || !finite(point?.[1]) || point[0] < 0) continue;
      observations.set(Math.round(point[0] / 30) * 30, point[1]);
    }
    for (const [time, value] of observations) {
      const bucket = buckets.get(time) || { sum: 0, count: 0 };
      bucket.sum += value;
      bucket.count += 1;
      buckets.set(time, bucket);
    }
  }
  const enough = Math.max(1, Math.ceil(games.length * .45));
  const points = [...buckets].sort(([a], [b]) => a - b)
    .filter(([, bucket]) => bucket.count >= enough)
    .map(([time, bucket]) => [time, Math.round(bucket.sum / bucket.count)]);
  return { points, games: games.length };
}

export function renderGallery(view, { esc, fmt, icon, chart, API_BASE = '' }) {
  const data = view.data || {};
  const period = data.period || {};
  const record = data.record || {};
  const display = (value) => finite(value) ? fmt(value) : '—';
  const date = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.slice(5).replace('-', '.') : '';
  const range = date(period.from) && date(period.to) ? `${date(period.from)} — ${date(period.to)}` : '正在读取周期';
  const form = list(record.form).slice(-12);
  const total = finite(record.decided) ? record.decided + (finite(record.unknown) ? record.unknown : 0) : undefined;
  const results = form.length ? `<div class="celadon-results"><span>近 ${form.length} 局</span><div>${form.map((item) => {
    const won = item.result === 'win';
    const title = [item.date, item.opponent, won ? '胜利' : '失利'].filter(Boolean).join(' · ');
    return `<span class="celadon-result ${won ? 'is-win' : 'is-loss'}" title="${esc(title)}" aria-label="${esc(title)}">${won ? '胜' : '负'}</span>`;
  }).join('')}</div></div>` : '';
  const cover = `<section class="celadon-cover" aria-labelledby="celadon-title">
    <img class="celadon-art" src="${API_BASE}/static/media/celadon-valley.webp" alt="" width="1756" height="896" fetchpriority="high" decoding="async">
    <div class="celadon-cover-copy">
      <h1 id="celadon-title">赛训简报</h1><p class="celadon-date">${esc(range)}</p>
      <div class="celadon-record"><span><b>${display(record.wins)}</b><small>胜</small></span><span><b>${display(record.losses)}</b><small>负</small></span><span class="celadon-game-count"><b>${display(total)}</b><small>局</small></span></div>
      <p class="celadon-cover-note">${esc(data.summary?.sentence || data.reason || '读取本期战况与复盘证据。')}</p>
      <a class="primary celadon-collect" href="#ingest">${icon('ingest')}采集对局</a>
    </div>${results}
  </section>`;

  let evidence = '';
  if (view.galleryError || view.error) {
    evidence = '<div class="celadon-evidence-error"><p>经济走势与最近对局暂时读不到，其余简报仍可查看。</p><button type="button" class="control" data-pbr-retry>重新读取</button></div>';
  } else if (!view.overview) {
    evidence = '<div class="celadon-evidence-loading" aria-label="正在读取经济走势与最近对局"><div class="ui-skeleton"></div><div class="ui-skeleton"></div></div>';
  } else {
    const overview = view.overview;
    const curve = averageEconomy(overview.process);
    const clock = (seconds) => finite(seconds) && seconds >= 0 ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '—';
    const curveNote = curve.games ? `${curve.games} 局平均 · 各时间点至少覆盖 ${Math.ceil(curve.games * .45)} 局` : '本期还没有可用的官方回放时间轴';
    const withCurves = new Set(list(overview.process?.matches).map((game) => game.key));
    const matches = list(overview.matches);
    const processMatches = matches.filter((game) => withCurves.has(game.key));
    const recent = (processMatches.length ? processMatches : matches).slice(0, 5);
    const rows = recent.map((game) => `<a class="celadon-recent-row" href="#match/${encodeURIComponent(game.key)}">
      <time>${esc(String(game.date || '').slice(5) || '日期待补')}</time><span class="celadon-opponent">${esc(game.opponent || '对手未标注')}</span><span>${clock(game.duration)}</span><span class="celadon-result ${game.result === 'win' ? 'is-win' : game.result === 'loss' ? 'is-loss' : ''}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</span>${icon('chevron')}</a>`).join('');
    evidence = `<div class="celadon-evidence-grid"><section class="celadon-economy" aria-labelledby="celadon-economy-title"><div class="celadon-section-head"><h2 id="celadon-economy-title">经济走势</h2><span>本队 − 对手</span></div>
      ${curve.points.length >= 2 ? chart(curve.points, '本期有回放对局的平均经济差', { note: esc(curveNote) }) : '<div class="celadon-chart-empty"><span>还没有完整的经济时间轴</span><p>关联官方回放后，可以在这里查看本期经济走势。</p><a href="#ingest" class="text-link">去关联回放</a></div>'}
      </section><section class="celadon-recent" aria-labelledby="celadon-recent-title"><div class="celadon-section-head"><h2 id="celadon-recent-title">最近对局</h2><a href="#matches">全部对局</a></div><div class="celadon-recent-head" aria-hidden="true"><span>日期</span><span>对手</span><span>时长</span><span>结果</span><span></span></div>${rows || '<div class="empty">本期还没有入库对局，采集第一局后会显示在这里。</div>'}<p class="celadon-source-note">${processMatches.length ? '当前周期内有时间轴的对局' : '当前周期内已入库的对局'}</p></section></div>`;
  }
  return { cover, evidence: `<div data-gallery-evidence>${evidence}</div>` };
}
