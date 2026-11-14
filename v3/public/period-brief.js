/* 赛训周期简报 · 默认首页 #overview
 *
 * 契约：docs/period_brief.md §2（GET /api/briefing）、§3（布局）。
 *   - 本模块自取数、自渲染、自管周期：切周期只重取简报，不写全局筛选；
 *     「自定义」用既有「数据范围」弹窗里的 from/to 作为 custom 区间。
 *   - 后端只给结论与数字（摘要句、动态指标、发现卡、证据对局、下钻链接），
 *     前端不排序、不补 0、不造词：null 一律显示「—」，缺什么就少一块。
 *   - 失败只在模块内提示并可重试，不清空外壳、也不留上一期的结论。
 *   - 空态按契约：本期 0 局 → 空态 + 训练安排 + 最近一批入口；空库交回 app.js
 *     的「还没有对局数据」弹窗（首页不整页换向导）。
 */

const PERIOD_TEXT = { today: '今日', week: '本周', month: '本月', custom: '自定义' };
const PERIOD_ORDER = ['today', 'week', 'month', 'custom'];
const DEFAULT_KIND = 'week';
const METRIC_LIMIT = 8;
const EVIDENCE_LIMIT = 2;
const NUMBER_LIMIT = 4;
/* 复盘卡「显示字段」：最多 4 项、最少 1 项；用户选择只存在控制器里。 */
const DISPLAY_LIMIT = 4;
const DISPLAY_KEY = 'pbr-watch-display-fields';
/* 关注（收藏）：只存 {id: ISO}，具体时间展示由渲染层格式化。 */
const FINDING_FAV_KEY = 'pbr-finding-favs';
const WATCH_FAV_KEY = 'pbr-watch-favs';
const KIND_TEXT = {
  advantage: '领先兑现', fight: '团战', objective: '资源', comp: '阵容',
  roster: '分路', coverage: '数据', training: '训练安排',
  loss: '失利', win: '取胜',
};
const TONES = ['up', 'down', 'flat', 'none'];

const has = (value) => typeof value === 'number' && Number.isFinite(value);
const listOf = (value) => (Array.isArray(value) ? value : []);
const plain = (value) => String(value ?? '').trim();
const textOf = (value) => {
  const text = plain(value);
  return text === '' ? '—' : text;
};
const toneOf = (value) => (TONES.includes(plain(value)) ? plain(value) : 'none');
/* 契约里的日期是 YYYY-MM-DD；界面上只留 11-09 这种短格式，跨年时保留年份。 */
const shortDate = (value) => {
  const text = plain(value);
  if (!text) return '';
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) return text;
  const currentYear = String(new Date().getFullYear());
  return match[1] === currentYear ? `${match[2]}-${match[3]}` : text;
};
const rangeText = (from, to) => {
  const left = shortDate(from);
  const right = shortDate(to);
  return left && right ? `${left} ~ ${right}` : (left || right || '');
};

function readableError(error) {
  const status = error && error.status;
  const message = plain(error && error.message);
  if (status === 404) return '简报服务暂时不可用，稍后点重试即可。';
  if (/Failed to fetch|NetworkError|Load failed|Network request failed/i.test(message)) {
    return '与工作台的连接中断了，恢复后点重试即可。';
  }
  return message && message.length <= 160 ? message : '这一期的简报暂时读不到，稍后点重试即可。';
}

/* ── 顶部：kicker + 周期切换 + 标题 + 副标题 ─────────────────────── */
function barHtml(view, ctx) {
  const { esc, icon } = ctx;
  return `<div class="pbr-bar">
    <span class="pbr-kicker">赛训周期简报</span>
    <div class="pbr-bar-actions">
      <div class="pbr-periods" role="group" aria-label="赛训周期">
        ${PERIOD_ORDER.map((key) => `<button type="button" class="pbr-period" data-pbr-period="${key}" aria-pressed="${String(view.kind === key)}">${PERIOD_TEXT[key]}</button>`).join('')}
      </div>
      <button type="button" class="control pbr-range" data-action="filter">${icon('filter')} 数据范围</button>
    </div>
  </div>`;
}

function titleHtml(view, ctx) {
  const { esc } = ctx;
  const period = (view.data && view.data.period) || {};
  const prev = period.prev || {};
  const label = plain(period.label) || PERIOD_TEXT[view.kind] || PERIOD_TEXT[DEFAULT_KIND];
  const prevLabel = plain(prev.label) || '上一周期';
  /* 范围行用短标签（上周 / 上期），避免「对比上周同期（… / 上周同期 …）」重复。 */
  const prevShort = plain(prev.shortLabel) || prevLabel;
  const range = plain(period.rangeLabel) || rangeText(period.from, period.to);
  const prevRange = plain(prev.rangeLabel) || rangeText(prev.from, prev.to);
  const scope = range ? `（${range}${prevRange ? ` / ${prevShort} ${prevRange}` : ''}）` : '';
  const coverage = view.data && view.data.available !== false
    ? plain(view.data && view.data.coverage && view.data.coverage.note)
    : '';
  return `<div class="pbr-title">
    <div class="pbr-title-copy">
      <h1>赛训总览</h1>
      <p class="pbr-sub">${esc(label)}赛训表现 · 对比${esc(prevLabel)}${scope ? `<span class="pbr-range-text">${esc(scope)}</span>` : ''}</p>
    </div>
    ${coverage ? `<p class="pbr-coverage-chip">${esc(coverage)}</p>` : ''}
  </div>`;
}

/* ── 一句战况 ─────────────────────────────────────────────────── */
function summaryHtml(data, ctx) {
  const { esc } = ctx;
  const summary = data.summary || {};
  const sentence = plain(summary.sentence);
  const note = plain(summary.note);
  return `<section class="pbr-summary is-${toneOf(summary.tone)}" aria-label="一句战况">
    <span class="pbr-summary-label">一句战况</span>
    <div class="pbr-summary-body">
      <p class="pbr-summary-sentence">${esc(sentence || '本期还没有可以总结的战况。')}</p>
      ${note ? `<p class="pbr-summary-note">${esc(note)}</p>` : ''}
    </div>
  </section>`;
}

/* ── 8 项赛训指标（顺序由后端定，前端不再排序） ───────────────── */
function rankHtml(rank, esc) {
  const tier = ['lead', 'mid', 'behind'].includes(plain(rank.tier)) ? plain(rank.tier) : 'mid';
  const text = plain(rank.text) || `${plain(rank.tierText)} ${rank.pos}/${rank.total}`;
  const percent = has(rank.percentile) ? Math.max(0, Math.min(100, rank.percentile)) : null;
  return `<span class="pbr-rank is-${tier}" title="${esc(text)}${percent === null ? '' : ` · 超过 ${Math.round(percent)}% 的对手`}">${esc(text)}</span>`;
}

/* 一条细横条：有排名画同批百分位（带 25/50/75 刻度），没排名画本项比例。 */
function meterHtml(metric, esc) {
  const bar = metric && metric.bar;
  let pct = bar && has(bar.pct) ? bar.pct : null;
  let tier = bar ? plain(bar.tier) : '';
  let isRank = bar ? plain(bar.mode) === 'rank' : false;
  /* 老报文没有 bar：退回排名里的百分位，条不空着。 */
  if (pct === null && metric && metric.rank && has(metric.rank.percentile)) {
    pct = metric.rank.percentile;
    tier = plain(metric.rank.tier);
    isRank = true;
  }
  if (pct === null) return '';
  const width = Math.max(0, Math.min(100, pct));
  const tierClass = ['lead', 'mid', 'behind'].includes(tier) ? ` is-${tier}` : '';
  const ticks = isRank
    ? '<b class="pbr-tick is-25"></b><b class="pbr-tick is-50"></b><b class="pbr-tick is-75"></b>'
    : '';
  const label = isRank ? `超过 ${Math.round(width)}% 的对手` : `本项 ${Math.round(width)}%`;
  return `<span class="pbr-meter${tierClass}${isRank ? '' : ' is-value'}" role="img" aria-label="${esc(label)}">
      <i style="width:${width.toFixed(1)}%"></i>${ticks}
    </span>`;
}

function metricsHtml(data, ctx) {
  const { esc } = ctx;
  const metrics = listOf(data.metrics)
    .filter((metric) => metric && plain(metric.label))
    .slice(0, METRIC_LIMIT);
  if (!metrics.length) return '';

  /* 上期整段没有对局时，这句话只在区头说一遍，不在 8 张卡里重复 8 次。 */
  const prev = (data.period && data.period.prev) || {};
  const prevName = plain(prev.shortLabel) || plain(prev.label) || '上期';
  const prevRange = plain(prev.rangeLabel) || rangeText(prev.from, prev.to);
  const withPrev = metrics.filter((metric) => {
    const value = plain(metric.prevValueText);
    return value && value !== '—' && value !== '-';
  }).length;
  let compareNote = '';
  if (!withPrev) {
    compareNote = `${prevName}${prevRange ? `（${prevRange}）` : ''}没有对局 · 上期暂无可比数据`;
  } else if (withPrev < metrics.length) {
    compareNote = `${prevName}有 ${metrics.length - withPrev} 项没有对局 · 这几项只看本期值`;
  } else {
    compareNote = `对比${prevName}${prevRange ? `（${prevRange}）` : ''} · 同一口径计算`;
  }

  let leadCount = 0;
  const rows = metrics.map((metric) => {
    const label = plain(metric.label);
    const prevValue = plain(metric.prevValueText);
    const delta = plain(metric.deltaText);
    const note = plain(metric.note);
    const coverage = plain(metric.coverage);
    const sub = plain(metric.valueSub);
    const hasPrev = prevValue && prevValue !== '—' && prevValue !== '-';
    const showDelta = hasPrev && delta && !/暂无可比数据/.test(delta);
    const tone = toneOf(metric.tone);
    const arrow = tone === 'up' ? '↑' : tone === 'down' ? '↓' : '';
    const rank = metric.rank && plain(metric.rank.text) ? metric.rank : null;
    if (rank && plain(rank.tier) === 'lead') leadCount += 1;
    /* 有排名的指标：大数字跟「领先/中等/落后」同色，扫一眼就知道这项是优势还是短板。 */
    const tier = rank ? plain(rank.tier) : '';
    const valueTier = ['lead', 'mid', 'behind'].includes(tier) ? ` is-${tier}` : '';
    /* 百分率已经带着分母了，右侧就不再重复「19/19 局」；没排名的才退回收数。 */
    const chip = rank ? rankHtml(rank, esc)
      : (!sub && coverage ? `<small class="pbr-metric-coverage">${esc(coverage)}</small>` : '');
    const prevLine = hasPrev
      ? `<span class="pbr-metric-prev">上期 ${esc(prevValue)}${showDelta
        ? ` <em class="pbr-metric-delta is-${tone}">${arrow}${esc(delta)}</em>` : ''}</span>`
      : '';
    const meter = meterHtml(metric, esc);
    const foot = meter || prevLine
      ? `<div class="pbr-metric-foot">${meter}${prevLine}</div>`
      : '';
    return `<div class="pbr-metric" title="${esc(note)}">
      <div class="pbr-metric-line">
        <span class="pbr-metric-label">${esc(label)}</span>
        ${chip}
        <span class="pbr-metric-value${valueTier}">${esc(textOf(metric.valueText))}${sub
          ? `<em class="pbr-metric-pct">（${esc(sub)}）</em>` : ''}</span>
      </div>
      ${foot}
    </div>`;
  }).join('');

  const peerTotal = listOf(data.metrics).reduce((max, metric) => {
    const total = metric && metric.rank && has(metric.rank.total) ? metric.rank.total : 0;
    return Math.max(max, total);
  }, 0);
  const legend = peerTotal
    ? `<p class="pbr-legend">
        <span class="pbr-legend-item"><i class="pbr-legend-dot is-lead"></i>领先</span>
        <span class="pbr-legend-item"><i class="pbr-legend-dot is-mid"></i>中等</span>
        <span class="pbr-legend-item"><i class="pbr-legend-dot is-behind"></i>落后</span>
        <span class="pbr-legend-note">排名对比本期一起训练的 ${peerTotal - 1} 支战队，同一口径；本页 <b>${leadCount}</b> 项领先</span>
      </p>`
    : '';

  return `<section class="pbr-metrics-block" aria-label="本期 8 项赛训指标">
    <div class="pbr-section-head">
      <div class="pbr-section-title">
        <h2>本期指标</h2>
        <span class="pbr-section-chip">${metrics.length} 项</span>
      </div>
      <p class="pbr-section-note">${esc(compareNote)}</p>
    </div>
    <div class="pbr-metrics">${rows}</div>
    ${legend}
  </section>`;
}

/* 区头已经统一说过「上期暂无可比数据」，卡内结论不再逐条重复；
   limitation 等内部口径保留在接口，卡面只留比赛内容。 */
const trimCompare = (value) => plain(value)
  .replace(/[；;，,]?\s*(?:昨天|上周|上月|上期)暂无可比数据。?$/, '')
  .trim();

/* 发现卡的可视化：有分母就画比例条，有本期/上期数值就画两条对比。 */
function ratioPct(value) {
  const match = plain(value).match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
  if (!match) return null;
  const part = Number(match[1]);
  const whole = Number(match[2]);
  if (!Number.isFinite(part) || !Number.isFinite(whole) || whole <= 0) return null;
  return Math.max(0, Math.min(100, (part / whole) * 100));
}

function numberValue(value) {
  const match = plain(value).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const number = Number(match[0]);
  return Number.isFinite(number) ? number : null;
}

/* 所有发现卡共用同一行「数字 + 比例条」，三张卡的分隔线与证据行才对得齐。 */
function statHtml(finding, numbers, esc) {
  const first = numbers[0];
  if (first) {
    const pct = ratioPct(first.value);
    if (pct !== null) {
      const label = plain(first.label) || '本期';
      return `<div class="pbr-stat">
        <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(label)}</span><b>${esc(textOf(first.value))}</b><em>${Math.round(pct)}%</em></span>
        <span class="pbr-stat-track"><i style="width:${pct.toFixed(1)}%"></i></span>
      </div>`;
    }
    if (numbers.length >= 2) {
      const current = numberValue(numbers[0].value);
      const previous = numberValue(numbers[1].value);
      if (current !== null && previous !== null) {
        const max = Math.max(Math.abs(current), Math.abs(previous), 0.000001);
        return `<div class="pbr-stat is-compare">
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(numbers[0].label) || '本期')}</span><b>${esc(textOf(numbers[0].value))}</b><span class="pbr-stat-track"><i style="width:${(Math.abs(current) / max * 100).toFixed(1)}%"></i></span></span>
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(numbers[1].label) || '上期')}</span><b>${esc(textOf(numbers[1].value))}</b><span class="pbr-stat-track is-prev"><i style="width:${(Math.abs(previous) / max * 100).toFixed(1)}%"></i></span></span>
        </div>`;
      }
    }
    /* 上期没有可比数据：只画本期这一行，不硬造一条 100% 的比例条。 */
    if (numberValue(first.value) !== null) {
      return `<div class="pbr-stat is-single">
        <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(first.label) || '本期')}</span><b>${esc(textOf(first.value))}</b></span>
      </div>`;
    }
  }
  return '<div class="pbr-stat is-empty"></div>';
}

function rosterHtml(finding, esc) {
  const players = listOf(finding.rosterPlayers)
    .filter((player) => player && plain(player.name))
    .slice(0, 5);
  if (!players.length) {
    const roster = plain(finding.rosterText);
    return `<div class="pbr-roster">${roster
      ? `<span class="pbr-roster-label">我方阵容</span><p class="pbr-finding-roster">${esc(roster)}</p>`
      : ''}</div>`;
  }
  /* 头像点进英雄资料：教练看到「这把谁在打、这个英雄近期什么样」可以直接跳。 */
  const items = players.map((player) => {
    const name = plain(player.name);
    const icon = plain(player.icon);
    const face = icon
      ? `<img src="${esc(icon)}" alt="" width="36" height="36" loading="lazy">`
      : `<i>${esc(name.slice(0, 1))}</i>`;
    return `<a class="pbr-roster-item" href="#hero/${encodeURIComponent(name)}" title="${esc(name)} · 打开英雄资料">
      ${face}<small>${esc(name)}</small></a>`;
  }).join('');
  return `<div class="pbr-roster"><span class="pbr-roster-label">我方阵容</span>
    <div class="pbr-roster-list">${items}</div></div>`;
}

/* 重点发现的证据压成一行：不带 note，只留「对局 + 查看」，两条并排。
   note 放到 <a title> 里：教练 hover 就能看到这局发生了什么，不占一行的版面。 */
function evidenceInlineHtml(item, esc) {
  const game = plain(item && item.game);
  const label = plain(item && item.label) || game || '对局';
  const note = plain(item && item.note);
  const tip = note ? ` title="${esc(`${label} ${note}`)}"` : '';
  const body = `<span class="pbr-evidence-label">${esc(label)}</span>
    <span class="pbr-evidence-open">查看对局 →</span>`;
  return `<li>${game
    ? `<a href="#match/${encodeURIComponent(game)}"${tip}>${body}</a>`
    : `<span class="pbr-evidence-item"${tip}>${body}</span>`}</li>`;
}

function findingHead(finding, index, esc, options) {
  const kind = KIND_TEXT[plain(finding.kind)] || '';
  const kindClass = plain(finding.kind) === 'loss' ? 'pbr-tag is-loss' : 'pbr-tag';
  const tag = kind ? `<span class="${kindClass}">${esc(kind)}</span>` : '';
  const title = `<h3>${esc(plain(finding.title) || '本期变化')}</h3>`;
  /* 重点发现行是「序号 + 标签 + 标题」；复盘卡保持原来的「标题 + 标签」。 */
  const body = options && options.tagFirst ? `${tag}${title}` : `${title}${tag}`;
  return `<div class="pbr-finding-top">
    <span class="pbr-finding-no">${String(index + 1).padStart(2, '0')}</span>
    ${body}
  </div>`;
}

/* 老报文（没有 values）仍按原来的 numbers 顺序出 4 个数字。 */
function numbersHtml(card, esc) {
  const numbers = listOf(card.numbers)
    .filter((item) => {
      const value = plain(item && item.value);
      return value && value !== '—' && value !== '-';
    })
    .slice(0, NUMBER_LIMIT);
  return `<div class="pbr-numbers">${numbers.map((item) => `<span class="pbr-num${item.focus ? ' is-focus' : ''}"><small>${esc(plain(item.label) || '本期')}</small><b>${esc(textOf(item.value))}</b></span>`).join('')}</div>`;
}

const valueText = (item) => {
  const text = plain(item && item.value);
  return text && text !== '—' && text !== '-' ? text : '';
};

/* ── 关注（收藏）────────────────────────────────────────────────
 * 纯渲染只读 view.findingFavs / view.watchFavs（{id: ISO}），
 * localStorage 只在控制器里读写；关注项排在前面、其余保持后端顺序。 */
const findingKey = (finding) => plain(finding && finding.id) || plain(finding && finding.title);

function watchCardKey(card) {
  const evidence = listOf(card && card.evidence);
  const game = plain(evidence[0] && evidence[0].game);
  return game || plain(card && card.id) || plain(card && card.title);
}

/* 关注时间：同年 MM-DD HH:mm，跨年 YYYY-MM-DD HH:mm（localStorage 里存 ISO）。 */
function favTimeText(iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return '';
  const pad = (value) => String(value).padStart(2, '0');
  const clock = `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return date.getFullYear() === new Date().getFullYear() ? clock : `${date.getFullYear()}-${clock}`;
}

function favButtonHtml(attr, key, favs, esc, label) {
  const iso = plain(favs && favs[key]);
  const on = Boolean(iso);
  const text = on ? `已关注 · ${favTimeText(iso)}` : (label || '关注');
  return `<button type="button" class="pbr-fav${on ? ' is-on' : ''}" ${attr}="${esc(key)}"
    aria-pressed="${String(on)}" title="${esc(on ? '取消关注' : '关注')}"><i class="pbr-fav-star" aria-hidden="true">${on ? '★' : '☆'}</i><span class="pbr-fav-text">${esc(text)}</span></button>`;
}

function sortedByFav(items, keyOf, favs) {
  if (!favs || !Object.keys(favs).length) return items;
  const fav = [];
  const rest = [];
  items.forEach((item) => (favs[keyOf(item)] ? fav : rest).push(item));
  return fav.concat(rest);
}

/* 重点发现的每一行（供渲染与控制器局部重画共用）。 */
function findingRowsHtml(findings, favs, esc) {
  return sortedByFav(findings, findingKey, favs)
    .map((finding, index) => findingHtml(finding, index, esc, { favType: 'finding', favs }))
    .join('');
}

/* 某组复盘卡（供渲染与控制器局部重画共用）。 */
function watchCardsHtml(field, options, esc) {
  const opts = options || {};
  return sortedByFav(watchItems(field), watchCardKey, opts.favs)
    .map((item, index) => findingHtml(item, index, esc, { ...opts, favType: 'watch' }))
    .join('');
}

/* 复盘卡数字：按「显示字段」顺序，从 card.values 里按 id 取；缺什么就写「—」。
   老报文没有 values 时退回 numbers 的同位置字段（顺序由后端保证）。 */
function displayNumbersHtml(card, options, esc) {
  const catalog = listOf(options && options.catalog);
  const displayIds = listOf(options && options.displayIds).map(plain).filter(Boolean);
  const focusId = plain(options && options.focusId);
  const values = listOf(card.values).filter((item) => item && plain(item.id));
  const fallback = listOf(card.numbers).filter((item) => valueText(item));
  const labelOf = (id) => {
    const entry = catalog.find((item) => item.id === id);
    return entry ? entry.label : '';
  };
  const entries = displayIds.map((id, index) => {
    let label = labelOf(id) || id;
    let value = '—';
    if (values.length) {
      const hit = values.find((item) => plain(item.id) === id);
      if (hit) {
        label = plain(hit.label) || label;
        value = textOf(hit.value);
      }
    } else if (fallback[index]) {
      label = plain(fallback[index].label) || label;
      value = textOf(fallback[index].value);
    }
    return { id, label, value };
  });
  return `<div class="pbr-numbers">${entries.map((entry) => `<span class="pbr-num${entry.id === focusId ? ' is-focus' : ''}${entry.value === '—' ? ' is-missing' : ''}" data-pbr-value="${esc(entry.id)}"><small>${esc(entry.label)}</small><b>${esc(entry.value)}</b></span>`).join('')}</div>`;
}

function findingHtml(finding, index, esc, options) {
  const conclusion = trimCompare(finding.conclusion);
  const opts = options || {};
  const favs = opts.favs || {};
  const evidence = listOf(finding.evidence)
    .filter((item) => item && (plain(item.label) || plain(item.game)))
    .slice(0, EVIDENCE_LIMIT);

  /* 复盘卡：一句这局发生了什么 + 显示字段数字 + 五人阵容 + 一个动作 + 关注。
     重点发现行即使 kind 是 win/loss 也按「行」渲染（用 favType 区分上下文）。 */
  if (opts.favType !== 'finding' && ['win', 'loss'].includes(plain(finding.kind))) {
    const game = evidence.length ? plain(evidence[0].game) : '';
    const cardKey = watchCardKey(finding);
    const isFav = opts.favType === 'watch' && Boolean(favs[cardKey]);
    const fav = opts.favType === 'watch' ? favButtonHtml('data-pbr-fav-watch', cardKey, favs, esc, '关注') : '';
    /* 老报文（单组）没有「显示字段」，仍按后端给的 numbers 顺序出 4 个数字。 */
    const numbersPart = listOf(opts.displayIds).length
      ? displayNumbersHtml(finding, opts, esc)
      : numbersHtml(finding, esc);
    return `<article class="pbr-finding is-watch${isFav ? ' is-fav' : ''}">
      ${findingHead(finding, index, esc)}
      <p class="pbr-conclusion">${esc(conclusion)}</p>
      ${numbersPart}
      ${rosterHtml(finding, esc)}
      <div class="pbr-watch-link">${game
        ? `<a href="#match/${encodeURIComponent(game)}">查看这局完整过程 →</a>`
        : '<span></span>'}${fav}</div>
    </article>`;
  }

  /* 重点发现行：左栏文字 + 右侧本期数值（比例条 / 上期对比），与指标面板同一视觉语言。 */
  const numbers = listOf(finding.numbers)
    .filter((item) => valueText(item))
    .slice(0, NUMBER_LIMIT);
  const key = findingKey(finding);
  const isFav = opts.favType === 'finding' && Boolean(favs[key]);
  const fav = opts.favType === 'finding' ? favButtonHtml('data-pbr-fav-finding', key, favs, esc, '关注') : '';
  return `<article class="pbr-finding${isFav ? ' is-fav' : ''}" data-finding-id="${esc(key)}">
    <div class="pbr-finding-main">
      ${findingHead(finding, index, esc, { tagFirst: true })}
      <p class="pbr-conclusion">${esc(conclusion)}</p>
      ${evidence.length
        ? `<ul class="pbr-evidence is-inline">${evidence.map((item) => evidenceInlineHtml(item, esc)).join('')}</ul>`
        : ''}
    </div>
    <div class="pbr-finding-side">${statHtml(finding, numbers, esc)}${fav ? `<div class="pbr-finding-fav">${fav}</div>` : ''}</div>
  </article>`;
}

/* 区块头共用一套：标题 + 计数胶囊，右侧可挂一句口径说明。 */
function sectionHeadHtml(title, countText, esc, note) {
  const noteText = plain(note);
  return `<div class="pbr-section-head">
    <div class="pbr-section-title">
      <h2>${esc(title)}</h2>
      ${countText ? `<span class="pbr-section-chip">${esc(countText)}</span>` : ''}
    </div>
    ${noteText ? `<p class="pbr-section-note">${esc(noteText)}</p>` : ''}
  </div>`;
}

function collectFindings(data) {
  return listOf(data.findings)
    .filter((finding) => finding && (plain(finding.title) || plain(finding.conclusion)));
}

function findingsHtml(data, view, ctx) {
  const { esc } = ctx;
  const findings = collectFindings(data);
  /* 首页这块是「先看哪几局」的入口；标题/计数/空态由后端按本期口径给，
     旧数据没有这些字段时回退到原来的「变化」文案。 */
  const title = plain(data.findingsTitle) || '本周期最值得关注的变化';
  const countText = findings.length
    ? (plain(data.findingsCountText) || `${findings.length} 条`)
    : '本期暂无';
  const emptyText = plain(data.findingsEmpty)
    || '本期与上期相比没有明显变化，没有需要单独展开的条目。';
  const head = sectionHeadHtml(title, countText, esc);
  if (!findings.length) {
    return `<section class="pbr-findings" aria-label="${esc(title)}">${head}
      <p class="pbr-findings-empty">${esc(emptyText)}</p>
    </section>`;
  }
  const favs = (view && view.findingFavs) || {};
  /* 不限条数：条数以后端为准（最多约 8 条），块内上下滚动，滚轮/键盘都能用。 */
  return `<section class="pbr-findings" aria-label="${esc(title)}">${head}
    <div class="pbr-finding-list is-scroll" tabindex="0" role="region" aria-label="${esc(title)}列表">${findingRowsHtml(findings, favs, esc)}</div>
  </section>`;
}

/* ── 最值得复盘的比赛（10 个字段各排一组；横向滑动 + 排序/字段控件） ── */
function watchItems(field) {
  return listOf(field && field.items)
    .filter((item) => item && (plain(item.title) || plain(item.conclusion)));
}

/* 显示字段目录：以后端 watchFields 的固定顺序为准，缺的 id 再从卡片的 values 里补。 */
function watchCatalogOf(data, fields) {
  const catalog = [];
  const seen = new Set();
  const push = (id, label, note) => {
    const key = plain(id);
    if (!key || seen.has(key)) return;
    seen.add(key);
    catalog.push({ id: key, label: plain(label) || key, note: plain(note) });
  };
  fields.forEach((field) => push(field.id, field.label, field.note));
  const cards = listOf(data.watch).concat(...fields.map((field) => watchItems(field)));
  cards.forEach((card) => {
    listOf(card && card.values).forEach((value) => push(value && value.id, value && value.label, ''));
  });
  return catalog;
}

/* 显示字段的选中集合：控制器传进来的用户选择优先，其次 payload 默认，最后目录前 4 项。 */
function displayPick(data, view, catalog) {
  const ids = catalog.map((entry) => entry.id);
  const pick = (source) => {
    const seen = new Set();
    const picked = [];
    listOf(source).forEach((value) => {
      const id = plain(value);
      if (id && ids.includes(id) && !seen.has(id)) {
        seen.add(id);
        picked.push(id);
      }
    });
    return picked.slice(0, DISPLAY_LIMIT);
  };
  const fromView = pick(view && view.displayFields);
  if (fromView.length) return fromView;
  const fromPayload = pick(data.watchDisplayFields);
  if (fromPayload.length) return fromPayload;
  return ids.slice(0, DISPLAY_LIMIT);
}

/* 卡片数字按「字段目录顺序」渲染：用户勾哪几项，就按目录顺序出几项。 */
function orderedDisplay(picked, catalog) {
  const ids = listOf(picked).map(plain).filter(Boolean);
  return catalog.map((entry) => entry.id).filter((id) => ids.includes(id));
}

/* 排序弹层（listbox）：一行一个字段，「字段名 + N 局 + ✓」，选中项唯一。 */
function sortPopHtml(fields, activeId, open, esc) {
  const options = fields.map((field) => {
    const id = plain(field.id);
    const label = plain(field.label) || id;
    const count = has(field.count) ? field.count : watchItems(field).length;
    const on = id === activeId;
    return `<button type="button" class="pbr-pop-option${on ? ' is-on' : ''}" role="option"
      data-pbr-sort-option="${esc(id)}" aria-selected="${String(on)}">
      <span class="pbr-pop-option-name">${esc(label)}</span>
      <span class="pbr-pop-option-count">${esc(`${count} 局`)}</span>
      <span class="pbr-pop-option-check" aria-hidden="true">${on ? '✓' : ''}</span>
    </button>`;
  }).join('');
  return `<div class="pbr-pop is-sort" id="pbr-sort-pop" data-pbr-sort-pop role="listbox" aria-label="按哪一项从差到好排"${open ? '' : ' hidden'}>
    <p class="pbr-pop-title">按这一项从差到好排</p>
    <div class="pbr-pop-list">${options}</div>
  </div>`;
}

/* 字段弹层：两列复选框，最多 4、最少 1；满 4 后未选项禁用，最后 1 个已选项也禁用。 */
function fieldsPopHtml(catalog, picked, open, esc) {
  const full = picked.length >= DISPLAY_LIMIT;
  const options = catalog.map((entry) => {
    const on = picked.includes(entry.id);
    const disabled = (!on && full) || (on && picked.length <= 1);
    const note = entry.note ? `<small title="${esc(entry.note)}">${esc(entry.note)}</small>` : '';
    return `<label class="pbr-pop-field${disabled ? ' is-disabled' : ''}">
      <input type="checkbox" data-pbr-field-option="${esc(entry.id)}"${on ? ' checked' : ''}${disabled ? ' disabled' : ''}>
      <span class="pbr-pop-field-copy"><b>${esc(entry.label)}</b>${note}</span>
    </label>`;
  }).join('');
  return `<div class="pbr-pop is-fields" id="pbr-fields-pop" data-pbr-fields-pop role="dialog" aria-label="卡片显示字段"${open ? '' : ' hidden'}>
    <p class="pbr-pop-title">卡片显示字段 · 最多 ${DISPLAY_LIMIT} 个</p>
    <div class="pbr-pop-fields">${options}</div>
    <div class="pbr-pop-foot">
      <span class="pbr-pop-count" data-pbr-field-count>已选 ${picked.length}/${DISPLAY_LIMIT}</span>
      <button type="button" class="pbr-pop-reset" data-pbr-display-reset>恢复默认</button>
    </div>
  </div>`;
}

/* 区头右侧的文本工具条：左右滚动 + 排序 + 字段，各自的弹层挂在同一容器里。 */
function watchToolsHtml(fields, catalog, picked, active, openPop, esc) {
  const activeId = plain(active.id);
  const activeLabel = plain(active.label) || activeId;
  const activeCount = has(active.count) ? active.count : watchItems(active).length;
  const sortOpen = openPop === 'sort';
  const fieldsOpen = openPop === 'fields';
  return `<div class="pbr-watch-tools">
    <div class="pbr-watch-arrows">
      <button type="button" class="pbr-arrow" data-pbr-watch-prev aria-label="上一屏复盘对局" title="向左看" disabled>‹</button>
      <button type="button" class="pbr-arrow" data-pbr-watch-next aria-label="下一屏复盘对局" title="向右看" disabled>›</button>
    </div>
    <button type="button" class="pbr-tool" data-pbr-sort-toggle aria-haspopup="listbox" aria-controls="pbr-sort-pop" aria-expanded="${String(sortOpen)}">
      <span class="pbr-tool-label">排序</span>
      <span class="pbr-tool-value" data-pbr-sort-value>${esc(activeLabel)} · ${esc(`${activeCount} 局`)}</span>
      <span class="pbr-tool-caret" aria-hidden="true">▾</span>
    </button>
    <button type="button" class="pbr-tool" data-pbr-fields-toggle aria-haspopup="dialog" aria-controls="pbr-fields-pop" aria-expanded="${String(fieldsOpen)}">
      <span class="pbr-tool-label">字段</span>
      <span class="pbr-tool-value">显示 ${picked.length} 项</span>
      <span class="pbr-tool-caret" aria-hidden="true">▾</span>
    </button>
    ${sortPopHtml(fields, activeId, sortOpen, esc)}
    ${fieldsPopHtml(catalog, picked, fieldsOpen, esc)}
  </div>`;
}

function watchGroupHtml(field, activeId, options, esc) {
  const id = plain(field.id);
  const label = plain(field.label) || id;
  const items = watchItems(field);
  const hidden = id === activeId ? '' : ' hidden';
  const cardOptions = {
    displayIds: options && options.displayIds,
    catalog: options && options.catalog,
    focusId: options && options.focusId,
    favs: options && options.favs,
  };
  if (!items.length) {
    return `<div class="pbr-finding-list is-empty" data-pbr-watch-group="${esc(id)}"
      data-watch-count="0"${hidden}>
      <p class="pbr-findings-empty">${esc(plain(field.empty) || `本期没有${label}的局。`)}</p>
    </div>`;
  }
  /* 每组是横向滑动的轨道：卡片自带边框，不再用整体面板分隔线。 */
  return `<div class="pbr-finding-list is-rail" data-pbr-watch-group="${esc(id)}"
    data-watch-count="${items.length}" tabindex="0"${hidden}>
    ${watchCardsHtml(field, cardOptions, esc)}
  </div>`;
}

function watchHtml(data, view, ctx) {
  const { esc } = ctx;
  const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
  const legacy = listOf(data.watch)
    .filter((item) => item && (plain(item.title) || plain(item.conclusion)));
  /* 旧报文没有 watch 字段时整块不渲染，避免首页多出一个空板块。 */
  if (!fields.length && !legacy.length && !plain(data.watchTitle)) return '';
  const title = plain(data.watchTitle) || '本期最值得复盘的比赛';

  /* 老报文（单组）：维持原样，不再强行造工具条/弹层/关注。 */
  if (!fields.length) {
    const head = sectionHeadHtml(title,
      plain(data.watchCountText) || `${legacy.length} 局`, esc,
      legacy.length ? '点开看完整过程' : '');
    if (!legacy.length) {
      const empty = plain(data.watchEmpty) || '本期没有可复盘的比赛过程。';
      return `<section class="pbr-findings pbr-watch" aria-label="${esc(title)}">${head}
        <p class="pbr-findings-empty">${esc(empty)}</p></section>`;
    }
    return `<section class="pbr-findings pbr-watch" aria-label="${esc(title)}">${head}
      <div class="pbr-finding-list is-rail" tabindex="0">${legacy.map((item, index) => findingHtml(item, index, esc)).join('')}</div>
    </section>`;
  }

  const catalog = watchCatalogOf(data, fields);
  const wanted = plain(view && view.watchActive) || plain(data.watchField) || plain(fields[0].id);
  const active = fields.find((field) => plain(field.id) === wanted) || fields[0];
  const activeId = plain(active.id);
  const picked = orderedDisplay(displayPick(data, view, catalog), catalog);
  const openPop = plain(view && view.openPop);
  const favs = (view && view.watchFavs) || {};
  const activeItems = watchItems(active);
  /* 区头「N 局」用后端 count（该字段本期总局数），不是这组实际渲染的条数。 */
  const activeCount = has(active.count) ? active.count : activeItems.length;
  const head = `<div class="pbr-section-head">
    <div class="pbr-section-title">
      <h2>${esc(title)}</h2>
      <span class="pbr-section-chip" data-pbr-watch-count>${activeCount > 0 ? `${activeCount} 局` : '本期暂无'}</span>
    </div>
    ${watchToolsHtml(fields, catalog, picked, active, openPop, esc)}
  </div>`;
  const groups = fields.map((field) => watchGroupHtml(field, activeId, { displayIds: picked, catalog, focusId: activeId, favs }, esc)).join('');
  return `<section class="pbr-findings pbr-watch" aria-label="${esc(title)}">${head}
    ${groups}
  </section>`;
}

/* ── 下一场约训 ───────────────────────────────────────────────── */
function nextHtml(data, ctx) {
  const { esc } = ctx;
  const next = data.next || {};
  const items = listOf(next.items).filter((item) => item && (plain(item.date) || plain(item.opponent)));
  if (next.available && items.length) {
    const rows = items.slice(0, 2).map((item) => {
      const when = [plain(item.date), plain(item.time)].filter(Boolean).join(' ');
      return `<li>
        <span class="pbr-next-when">${esc(when || '时间待定')}</span>
        <span class="pbr-next-who">${esc(plain(item.opponent) || '对手待命名')}</span>
        ${plain(item.note) ? `<span class="pbr-next-note">${esc(plain(item.note))}</span>` : ''}
      </li>`;
    }).join('');
    return `<ul class="pbr-next">${rows}</ul>`;
  }
  return `<p class="pbr-next-empty">${esc(plain(next.note) || '还没有登记下一场约训')} <a href="#plan">去登记 →</a></p>`;
}

/* ── 数据覆盖 ─────────────────────────────────────────────────── */
function coverageSentence(coverage) {
  const games = has(coverage.games) ? coverage.games : null;
  const replay = has(coverage.withReplay) ? coverage.withReplay : null;
  if (games === null) return '本期还没有可统计的对局。';
  if (games === 0) return '本期还没有收录对局。';
  if (replay === null) return `本期收录 ${games} 局。`;
  return `已收录 ${games} 局，其中 ${replay} 局可看比赛过程。`;
}

function coverageHtml(data, ctx) {
  const { esc } = ctx;
  const coverage = data.coverage || {};
  const sentence = plain(coverage.note) || coverageSentence(coverage);
  const sources = plain((data.sources || {}).note);
  const notes = listOf(data.notes).map(plain).filter(Boolean);
  return `<div class="pbr-foot-row">
    <p class="pbr-foot-label">数据覆盖</p>
    <div class="pbr-coverage-copy">
      <p>${esc(sentence)}</p>
      ${sources ? `<p class="pbr-sources">${esc(sources)}</p>` : ''}
      ${notes.length ? `<p class="pbr-notes">${esc(notes.join(' · '))}</p>` : ''}
    </div>
    <a class="pbr-all" href="#matches" data-pbr-all-games>全部对局 →</a>
  </div>`;
}

/* ── 空态 / 错误 / 读取中 ─────────────────────────────────────── */
function emptyHtml(data, view, ctx) {
  const { esc } = ctx;
  const period = data.period || {};
  const label = plain(period.label) || PERIOD_TEXT[view.kind] || PERIOD_TEXT[DEFAULT_KIND];
  const hint = data.fallback_hint || null;
  const from = plain(hint && hint.from);
  const to = plain(hint && hint.to);
  const hintLabel = plain(hint && hint.label) || rangeText(from, to);
  const reason = plain(data.reason);
  /* 后端 reason 与标题同义（「本周还没有对局（…）」）时不再重复一遍，改成说明能做什么。 */
  const range = rangeText(period.from, period.to);
  const reasonLine = reason && !reason.startsWith(`${label}还没有对局`)
    ? reason
    : `当前范围${range ? `（${range}）` : ''}没有可统计的对局；换一个周期，或先看最近一批。`;
  /* 本期 0 局时也交代上一周期的情况：教练才分得清「还没打」还是「数据没进来」。 */
  const prevNote = plain(data.empty_note);
  return `<section class="pbr-empty" aria-label="${esc(label)}暂无对局">
    <div class="pbr-empty-copy">
      <h2>${esc(label)}还没有对局</h2>
      <p class="pbr-empty-reason">${esc(reasonLine)}</p>
      ${prevNote ? `<p class="pbr-empty-prev">${esc(prevNote)}</p>` : ''}
    </div>
    <div class="pbr-empty-next">
      <p class="pbr-empty-label"><span class="pbr-foot-label">训练安排</span></p>
      ${nextHtml(data, ctx)}
    </div>
    <div class="pbr-empty-actions">
      ${from && to ? `<button type="button" class="primary" data-pbr-fallback data-from="${esc(from)}" data-to="${esc(to)}">查看最近一批（${esc(hintLabel)}）</button>` : ''}
      <a class="control" href="#ingest">去采集</a>
      ${view.hasDateScope ? '<button type="button" class="control" data-action="clear-scope">清除日期范围</button>' : ''}
      <button type="button" class="control" data-action="filter">数据范围</button>
    </div>
  </section>`;
}

function loadingHtml() {
  return `<div class="pbr-loading" role="status">
      <span class="pbr-spinner" aria-hidden="true"></span>正在读取本期简报…
    </div>
    <div class="pbr-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`;
}

function errorHtml(view, ctx) {
  const { esc, icon } = ctx;
  return `<div class="pbr-error" role="alert">
    <b>本期简报没读出来</b>
    <p>${esc(readableError(view.error))}</p>
    <div class="pbr-error-actions">
      <button type="button" class="control" data-pbr-retry>${icon('refresh')} 重试</button>
    </div>
  </div>`;
}

function dataHtml(data, view, ctx) {
  return `${summaryHtml(data, ctx)}
    ${metricsHtml(data, ctx)}
    ${findingsHtml(data, view, ctx)}
    ${watchHtml(data, view, ctx)}
    <section class="pbr-foot" aria-label="约训与数据覆盖">
      <div class="pbr-foot-row">
        <p class="pbr-foot-label">下一场约训</p>
        <div class="pbr-foot-body">${nextHtml(data, ctx)}</div>
      </div>
      ${coverageHtml(data, ctx)}
    </section>`;
}

/* 纯渲染：给浏览器与静态回归共用，不碰 DOM、不发请求。 */
export function renderBrief(view, ctx) {
  const state = view || {};
  const deps = { esc: (value) => String(value ?? ''), icon: () => '', ...(ctx || {}) };
  const data = state.data || {};
  const body = state.loading
    ? loadingHtml()
    : state.error
      ? errorHtml(state, deps)
      : data.available === false
        ? emptyHtml(data, state, deps)
        : dataHtml(data, state, deps);
  return `<header class="pbr-head">
      ${barHtml(state, deps)}
      ${titleHtml(state, deps)}
      ${state.notice ? `<p class="pbr-notice" role="status">${deps.esc(state.notice)}</p>` : ''}
    </header>${body}`;
}

/* ── 页面控制器：挂载点、周期状态、取数与重试 ─────────────────── */
export function createPeriodBrief({ esc, fmt, icon, API_BASE, getFilters, openRange, onEmptyLibrary, applyScope }) {
  const ctx = { esc, fmt, icon };
  let root = null;
  let request = null;
  let generation = 0;
  let state = { kind: DEFAULT_KIND, override: null, filterKey: null, notice: '' };
  let view = { kind: DEFAULT_KIND, data: null, loading: false, error: null, notice: '' };
  /* 复盘区状态只活在控制器里：显示字段可持久化；排序字段只影响本次渲染；弹层开关不落盘。 */
  let displayChoice = null;
  let watchActive = null;
  let openPop = null;
  /* 关注收藏：纯渲染只读，localStorage 只在这里读写。 */
  let findingFavs = {};
  let watchFavs = {};
  let favsLoaded = false;

  const filters = () => {
    try { return getFilters() || {}; } catch { return {}; }
  };
  const filterKeyOf = () => {
    const current = filters();
    return `${plain(current.from)}|${plain(current.to)}`;
  };
  const hasRange = (value) => Boolean(value && plain(value.from) && plain(value.to));

  /* ── 复盘区显示字段：目录 / 默认值 / 本地持久化（只在控制器里读写） ── */
  const watchCatalog = (data) => {
    if (!data) return [];
    const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
    if (!fields.length) return [];
    return watchCatalogOf(data, fields);
  };

  const defaultDisplay = (data, catalog) => {
    const ids = catalog.map((entry) => entry.id);
    const picked = [];
    listOf(data && data.watchDisplayFields).forEach((value) => {
      const id = plain(value);
      if (ids.includes(id) && !picked.includes(id)) picked.push(id);
    });
    return picked.length ? picked.slice(0, DISPLAY_LIMIT) : ids.slice(0, DISPLAY_LIMIT);
  };

  function readStoredDisplay() {
    try {
      if (typeof localStorage === 'undefined') return null;
      const raw = localStorage.getItem(DISPLAY_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }

  function writeStoredDisplay(ids) {
    try {
      if (typeof localStorage === 'undefined') return;
      const store = localStorage;
      store.setItem(DISPLAY_KEY, JSON.stringify(ids));
    } catch {}
  }

  /* ── 关注收藏：{id: ISO} 映射，读一次缓存，改了就写回 ── */
  function readFavMap(key) {
    try {
      if (typeof localStorage === 'undefined') return {};
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : null;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
      const map = {};
      Object.keys(parsed).forEach((id) => {
        const iso = plain(parsed[id]);
        if (id && iso) map[id] = iso;
      });
      return map;
    } catch {
      return {};
    }
  }

  function writeFavMap(key, map) {
    try {
      if (typeof localStorage === 'undefined') return;
      const store = localStorage;
      store.setItem(key, JSON.stringify(map));
    } catch {}
  }

  function ensureFavs() {
    if (favsLoaded) return;
    favsLoaded = true;
    findingFavs = readFavMap(FINDING_FAV_KEY);
    watchFavs = readFavMap(WATCH_FAV_KEY);
  }

  /* 点一次：没关注就记当前时间，已关注就删掉（回到原位置）。 */
  function toggleFavMap(map, key) {
    const next = { ...map };
    if (next[key]) delete next[key];
    else next[key] = new Date().toISOString();
    return next;
  }

  /* 用户选择 > localStorage > payload 默认 > 目录前 4 项；每次都过滤掉目录里没有的 id。 */
  function resolveDisplay(data) {
    const catalog = watchCatalog(data);
    if (!catalog.length) return [];
    const ids = catalog.map((entry) => entry.id);
    const settle = (source) => {
      const seen = new Set();
      const picked = [];
      listOf(source).forEach((value) => {
        const id = plain(value);
        if (id && ids.includes(id) && !seen.has(id)) {
          seen.add(id);
          picked.push(id);
        }
      });
      return picked.slice(0, DISPLAY_LIMIT);
    };
    if (displayChoice) {
      const kept = settle(displayChoice);
      if (kept.length) return kept;
    }
    const stored = settle(readStoredDisplay());
    if (stored.length) {
      displayChoice = stored;
      return stored;
    }
    displayChoice = defaultDisplay(data, catalog);
    return displayChoice;
  }

  function currentRange() {
    if (state.kind !== 'custom') return null;
    if (hasRange(state.override)) return state.override;
    const current = filters();
    return hasRange(current) ? { from: current.from, to: current.to } : null;
  }

  /* 全局数据范围变了（数据范围弹窗、或「全部对局」下钻）就跟着走：
     有 from/to → 自定义区间；清空 → 回本周。周期按钮本身从不写 filters。 */
  function syncWithFilters() {
    const key = filterKeyOf();
    const current = filters();
    const ranged = Boolean(plain(current.from) && plain(current.to));
    if (state.filterKey === null) {
      state.filterKey = key;
      if (ranged) state.kind = 'custom';
      return;
    }
    if (key === state.filterKey) {
      if (state.kind === 'custom' && !state.override && !ranged) state.kind = DEFAULT_KIND;
      return;
    }
    state.filterKey = key;
    if (state.kind === 'custom') {
      state.override = null;
      if (!ranged) {
        state.kind = DEFAULT_KIND;
        state.notice = '已清除日期范围，简报回到本周。';
      }
    } else if (ranged) {
      state.kind = 'custom';
      state.notice = '';
    }
  }

  function briefUrl() {
    const current = filters();
    const params = new URLSearchParams();
    params.set('period', state.kind);
    const range = currentRange();
    if (state.kind === 'custom' && range) {
      params.set('from', range.from);
      params.set('to', range.to);
    }
    const source = listOf(current.source).map(plain).filter(Boolean);
    params.set('source', source.length ? source.join(',') : 'db,bundle');
    if (current.validation) params.set('validation', '1');
    return `${API_BASE}/api/briefing?${params.toString()}`;
  }

  function paint() {
    if (!root || !root.isConnected) return;
    ensureFavs();
    const current = filters();
    const scope = Boolean(plain(current.from) || plain(current.to));
    const data = view.data || null;
    const displayFields = data && listOf(data.watchFields).length ? resolveDisplay(data) : null;
    root.innerHTML = renderBrief({
      ...view,
      hasDateScope: scope,
      displayFields,
      watchActive,
      openPop,
      findingFavs,
      watchFavs,
    }, ctx);
    root.setAttribute('aria-busy', String(Boolean(view.loading)));
    syncArrows();
  }

  /* 左右滚动箭头：只控制当前可见分组的横向轨道，到两端就禁用。 */
  function watchRail() {
    return root ? root.querySelector('.pbr-watch [data-pbr-watch-group]:not([hidden])') : null;
  }

  function syncArrows() {
    if (!root) return;
    const prev = root.querySelector('[data-pbr-watch-prev]');
    const next = root.querySelector('[data-pbr-watch-next]');
    if (!prev || !next) return;
    const rail = watchRail();
    if (!rail) {
      prev.disabled = true;
      next.disabled = true;
      return;
    }
    const max = rail.scrollWidth - rail.clientWidth;
    prev.disabled = rail.scrollLeft <= 1;
    next.disabled = max <= 1 || rail.scrollLeft >= max - 1;
  }

  function scrollWatch(direction) {
    const rail = watchRail();
    if (!rail) return;
    const amount = Math.max(220, Math.round(rail.clientWidth * 0.9));
    const reduce = typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const target = rail.scrollLeft + direction * amount;
    try {
      rail.scrollTo({ left: target, behavior: reduce ? 'auto' : 'smooth' });
    } catch {
      rail.scrollLeft = target;
    }
  }

  /* 横向滚动时同步箭头禁用态（scroll 不冒泡，用捕获监听）。 */
  function onScroll(event) {
    const rail = event.target;
    if (!rail || !rail.matches || !rail.matches('[data-pbr-watch-group]')) return;
    if (rail.hasAttribute('hidden')) return;
    syncArrows();
  }

  /* 重画整块但不让键盘/滚动跳走：还原滚动位置，再把焦点放回同一个控件。 */
  function repaint(focusSelector) {
    if (!root || !root.isConnected) return;
    const scroller = typeof document === 'undefined' ? null : document.scrollingElement;
    const top = scroller ? scroller.scrollTop : 0;
    paint();
    if (scroller && top) scroller.scrollTop = top;
    if (!focusSelector) return;
    const node = root.querySelector(focusSelector);
    if (!node) return;
    try { node.focus({ preventScroll: true }); } catch { node.focus(); }
  }

  /* 打开/关闭弹层只切 DOM 属性，不重画：焦点留在触发按钮上，页面不跳。 */
  function syncPops() {
    if (!root) return;
    const sortToggle = root.querySelector('[data-pbr-sort-toggle]');
    const fieldsToggle = root.querySelector('[data-pbr-fields-toggle]');
    const sortPop = root.querySelector('[data-pbr-sort-pop]');
    const fieldsPop = root.querySelector('[data-pbr-fields-pop]');
    if (sortToggle) sortToggle.setAttribute('aria-expanded', String(openPop === 'sort'));
    if (fieldsToggle) fieldsToggle.setAttribute('aria-expanded', String(openPop === 'fields'));
    if (sortPop) sortPop.toggleAttribute('hidden', openPop !== 'sort');
    if (fieldsPop) fieldsPop.toggleAttribute('hidden', openPop !== 'fields');
  }

  function focusKeep(node) {
    if (!node) return;
    try { node.focus({ preventScroll: true }); } catch { node.focus(); }
  }

  function focusTool(kind) {
    if (!root) return;
    focusKeep(root.querySelector(kind === 'sort' ? '[data-pbr-sort-toggle]' : '[data-pbr-fields-toggle]'));
  }

  function togglePop(kind) {
    openPop = openPop === kind ? null : kind;
    syncPops();
  }

  function closePop() {
    if (!openPop) return;
    openPop = null;
    syncPops();
  }

  function stopRequest() {
    if (request) {
      try { request.abort(); } catch {}
      request = null;
    }
  }

  async function load() {
    /* 自定义周期没有区间时退回本周（数据范围弹窗被取消或只填了一端）。 */
    if (state.kind === 'custom' && !currentRange()) {
      state.kind = DEFAULT_KIND;
      state.override = null;
      state.notice = '自定义周期需要开始和结束日期，已显示本周。';
    }
    const own = ++generation;
    stopRequest();
    watchActive = null;
    openPop = null;
    const controller = new AbortController();
    request = controller;
    view = { kind: state.kind, data: null, loading: true, error: null, notice: state.notice };
    paint();
    try {
      const response = await fetch(briefUrl(), { signal: controller.signal, cache: 'no-store' });
      if (own !== generation) return;
      if (!response.ok) {
        const error = new Error('简报暂时读不到');
        error.status = response.status;
        throw error;
      }
      const payload = await response.json();
      if (own !== generation) return;
      const data = payload && typeof payload === 'object' ? payload : {};
      view = { kind: state.kind, data, loading: false, error: null, notice: state.notice };
      paint();
      /* 空库：本期没有对局、也没有更早的一批可看 → 交回首页的入库弹窗。 */
      if (data.available === false && !hasRange(data.fallback_hint) && typeof onEmptyLibrary === 'function') {
        const stamp = own;
        requestAnimationFrame(() => { if (stamp === generation) onEmptyLibrary(); });
      }
    } catch (error) {
      if (own !== generation || (error && (error.name === 'AbortError' || error.code === 20))) return;
      view = { kind: state.kind, data: null, loading: false, error, notice: state.notice };
      paint();
    }
  }

  function choosePeriod(key) {
    if (!PERIOD_TEXT[key]) return;
    if (key === 'custom') {
      state.kind = 'custom';
      state.override = null;
      state.notice = '';
      if (hasRange(filters())) load();
      if (typeof openRange === 'function') openRange();
      return;
    }
    state.kind = key;
    state.override = null;
    state.notice = '';
    load();
  }

  /* 「查看最近一批」：只切简报的 custom 区间，不写全局筛选。 */
  function showFallback(from, to) {
    if (!from || !to) return;
    state.kind = 'custom';
    state.override = { from, to };
    state.notice = '';
    load();
  }

  /* 「全部对局」：把本期的 from/to 交给对局页（它只认全局筛选），再走默认跳转。 */
  function openAllGames() {
    if (typeof applyScope !== 'function') return;
    const period = (view.data && view.data.period) || {};
    const range = currentRange();
    const from = plain(period.from) || (range && range.from) || '';
    const to = plain(period.to) || (range && range.to) || '';
    if (!from || !to) return;
    applyScope({ from, to });
  }

  /* 排序弹层里点一项：切分组、同步按钮/计数/高亮，关闭弹层，焦点回「排序」。 */
  function chooseSort(option) {
    const id = plain(option.dataset.pbrSortOption);
    const ids = listOf(view.data && view.data.watchFields).map((field) => plain(field && field.id));
    if (!id || !ids.includes(id)) return;
    watchActive = id;
    openPop = null;
    repaint(null);
    focusTool('sort');
  }

  /* 字段弹层里勾/取消一项：立即改卡片数字；弹层保持打开、焦点回同一个复选框。 */
  function chooseField(input) {
    const id = plain(input.dataset.pbrFieldOption);
    const data = view.data || {};
    const ids = watchCatalog(data).map((entry) => entry.id);
    if (!id || !ids.includes(id)) return;
    const current = resolveDisplay(data);
    if (current.includes(id)) {
      if (current.length <= 1) return;
      displayChoice = current.filter((value) => value !== id);
    } else {
      if (current.length >= DISPLAY_LIMIT) return;
      displayChoice = [...current, id];
    }
    writeStoredDisplay(displayChoice);
    openPop = 'fields';
    repaint(null);
    const box = root && Array.from(root.querySelectorAll('[data-pbr-field-option]'))
      .find((node) => node.dataset.pbrFieldOption === id);
    focusKeep(box);
  }

  function resetDisplay() {
    const data = view.data || {};
    const catalog = watchCatalog(data);
    if (!catalog.length) return;
    displayChoice = defaultDisplay(data, catalog);
    writeStoredDisplay(displayChoice);
    openPop = 'fields';
    repaint(null);
    focusKeep(root && root.querySelector('[data-pbr-display-reset]'));
  }

  /* 关注一条发现：只重画发现列表（不整页 paint），保持 scrollTop、焦点回到同一按钮。 */
  function toggleFindingFav(button) {
    const id = plain(button.dataset.pbrFavFinding);
    if (!id) return;
    ensureFavs();
    findingFavs = toggleFavMap(findingFavs, id);
    writeFavMap(FINDING_FAV_KEY, findingFavs);
    const list = root && root.querySelector('.pbr-findings:not(.pbr-watch) .pbr-finding-list');
    if (!list) return;
    const top = list.scrollTop;
    list.innerHTML = findingRowsHtml(collectFindings(view.data || {}), findingFavs, ctx);
    list.scrollTop = top;
    const next = Array.from(root.querySelectorAll('[data-pbr-fav-finding]'))
      .find((node) => node.dataset.pbrFavFinding === id);
    focusKeep(next);
  }

  /* 关注一局复盘：重画所有分组的卡片（跨组共享关注态），逐个恢复 scrollLeft、焦点回按钮。 */
  function toggleWatchFav(button) {
    const key = plain(button.dataset.pbrFavWatch);
    if (!key) return;
    ensureFavs();
    watchFavs = toggleFavMap(watchFavs, key);
    writeFavMap(WATCH_FAV_KEY, watchFavs);
    const data = view.data || {};
    const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
    if (!fields.length) return;
    const catalog = watchCatalog(data);
    const wanted = watchActive || plain(data.watchField) || plain(fields[0].id);
    const active = fields.find((field) => plain(field.id) === wanted) || fields[0];
    const picked = orderedDisplay(displayPick(data, { displayFields: resolveDisplay(data) }, catalog), catalog);
    const options = { displayIds: picked, catalog, focusId: plain(active.id), favs: watchFavs };
    const rails = Array.from(root.querySelectorAll('.pbr-watch [data-pbr-watch-group]'));
    const lefts = new Map();
    rails.forEach((rail) => lefts.set(rail.dataset.pbrWatchGroup, rail.scrollLeft));
    rails.forEach((rail) => {
      const field = fields.find((item) => plain(item.id) === rail.dataset.pbrWatchGroup);
      if (!field || !watchItems(field).length) return;
      rail.innerHTML = watchCardsHtml(field, options, ctx);
    });
    rails.forEach((rail) => { rail.scrollLeft = lefts.get(rail.dataset.pbrWatchGroup) || 0; });
    syncArrows();
    const rail = watchRail();
    const next = rail && Array.from(rail.querySelectorAll('[data-pbr-fav-watch]'))
      .find((node) => node.dataset.pbrFavWatch === key);
    focusKeep(next);
  }

  function onFieldChange(event) {
    const input = event.target.closest('[data-pbr-field-option]');
    if (!input) return;
    chooseField(input);
  }

  /* Esc 关闭弹层并把焦点还给触发按钮；点弹层外部只关闭，不抢焦点。 */
  function onDocumentKeyDown(event) {
    if (event.key !== 'Escape' || !openPop) return;
    const kind = openPop;
    openPop = null;
    syncPops();
    focusTool(kind);
  }

  function onDocumentPointerDown(event) {
    if (!openPop) return;
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;
    if (target.closest('.pbr-pop') || target.closest('.pbr-tool')) return;
    openPop = null;
    syncPops();
  }

  function onClick(event) {
    const target = event.target;
    const favFinding = target.closest('[data-pbr-fav-finding]');
    if (favFinding) {
      toggleFindingFav(favFinding);
      return;
    }
    const favWatch = target.closest('[data-pbr-fav-watch]');
    if (favWatch) {
      toggleWatchFav(favWatch);
      return;
    }
    if (target.closest('[data-pbr-watch-prev]')) {
      scrollWatch(-1);
      return;
    }
    if (target.closest('[data-pbr-watch-next]')) {
      scrollWatch(1);
      return;
    }
    if (target.closest('[data-pbr-sort-toggle]')) {
      togglePop('sort');
      return;
    }
    if (target.closest('[data-pbr-fields-toggle]')) {
      togglePop('fields');
      return;
    }
    const sortOption = target.closest('[data-pbr-sort-option]');
    if (sortOption) {
      chooseSort(sortOption);
      return;
    }
    if (target.closest('[data-pbr-display-reset]')) {
      resetDisplay();
      return;
    }
    const fallback = target.closest('[data-pbr-fallback]');
    if (fallback) {
      showFallback(fallback.dataset.from, fallback.dataset.to);
      return;
    }
    const periodButton = target.closest('[data-pbr-period]');
    if (periodButton) {
      choosePeriod(periodButton.dataset.pbrPeriod);
      return;
    }
    if (target.closest('[data-pbr-retry]')) {
      load();
      return;
    }
    /* 指标卡只读：不挂跳转，避免点到就离开首页。 */
    if (target.closest('[data-pbr-all-games]')) {
      /* 不拦截默认跳转：hash 变化后 app.js 会用刚写入的筛选加载 #matches。 */
      openAllGames();
      return;
    }
  }

  let docBound = false;
  function bindDocument() {
    if (docBound || typeof document === 'undefined') return;
    docBound = true;
    document.addEventListener('keydown', onDocumentKeyDown);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);
  }
  function unbindDocument() {
    if (!docBound || typeof document === 'undefined') return;
    docBound = false;
    document.removeEventListener('keydown', onDocumentKeyDown);
    document.removeEventListener('pointerdown', onDocumentPointerDown, true);
  }

  return {
    mount(node) {
      if (!node) return;
      root = node;
      if (root.dataset.pbrBound !== '1') {
        root.dataset.pbrBound = '1';
        root.addEventListener('click', onClick);
        root.addEventListener('change', onFieldChange);
        /* scroll 不冒泡，用捕获监听同步横向轨道两端箭头。 */
        root.addEventListener('scroll', onScroll, true);
      }
      bindDocument();
      syncWithFilters();
      load();
    },
    dispose() {
      generation += 1;
      stopRequest();
      unbindDocument();
      if (root) root.removeEventListener('scroll', onScroll, true);
      openPop = null;
      root = null;
    },
    /* 供外壳在「同一路由重渲」时保留当前周期；这里只暴露只读状态。 */
    state: () => ({ kind: state.kind }),
  };
}
