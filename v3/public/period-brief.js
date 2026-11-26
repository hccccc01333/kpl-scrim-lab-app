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

/* 单测把本文件以 data: URL 载入，无法解析相对 import；此时降级为无图标，浏览器里走正常模块。 */
let glyph = () => '';
if (!/^data:/.test(import.meta.url)) {
  try {
    ({ glyph } = await import('./ui-icons.js'));
  } catch {
    /* 图标模块不可用时不影响功能 */
  }
}

const PERIOD_TEXT = { today: '今日', week: '本周', month: '本月', recent: '近5场', days: '近3天', all: '全部', custom: '自定义' };
const PERIOD_ORDER = ['today', 'week', 'month', 'all', 'days', 'custom'];
/* 「全部」复用后端 custom 的宽区间：不改 /api/briefing 契约，也不用先把全局
   数据范围改掉；样本里如果有晚于今天的训练赛，默认周期就够不到它们。 */
const ALL_RANGE = { from: '2000-01-01', to: '2099-12-31' };
/* 进首页先看今天：赛训是当天打完当天复盘，一进来就落在今日最能对上教练的节奏。
   今日没有对局时页面本身会给「查看最近一期」的入口，不需要退回本周。
   周期不落盘，下次进首页仍然从今日开始。 */
const DEFAULT_KIND = 'today';
/* 最近 N 场 / 最近 N 天：前端固定档位，后端按 n/days 解析窗口。 */
const RECENT_N = 5;
const RECENT_DAYS = 3;
const PERIOD_REQUEST = { recent: { n: RECENT_N }, days: { days: RECENT_DAYS } };
const METRIC_LIMIT = 16;
const EVIDENCE_LIMIT = 2;
const NUMBER_LIMIT = 4;
/* 复盘卡「显示字段」：最多 4 项、最少 1 项；用户选择只存在控制器里。 */
const DISPLAY_LIMIT = 4;
const DISPLAY_KEY = 'pbr-watch-display-fields';
/* 关注（收藏）：值升级为 {at, reviewedAt, note}；旧 ISO 字符串读入自动迁移。 */
const FINDING_FAV_KEY = 'pbr-finding-favs';
const WATCH_FAV_KEY = 'pbr-watch-favs';
const IGNORED_KEY = 'pbr-finding-ignored';
const VIEW_KEY = 'pbr-view-mode';
const VIEW_MODES = ['all', 'fav', 'todo'];
const VIEW_TEXT = { all: '全部', fav: '关注', todo: '待复盘' };
/* 数字单位弱化：只把常见后缀拆成 <small class="pbr-unit">。 */
const UNIT_TOKEN = /(\s*)(金币|次|波|条|座|%|局|分钟|秒)$/;
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

/* ── 顶部：周期切换 + 视图过滤 + 数据范围 ───────────────────── */
function barHtml(view, ctx) {
  const { icon } = ctx;
  const mode = VIEW_MODES.includes(plain(view.viewMode)) ? plain(view.viewMode) : 'all';
  return `<div class="pbr-bar">
    <div class="pbr-bar-actions">
      <div class="pbr-periods" role="group" aria-label="赛训周期">
        ${PERIOD_ORDER.map((key) => `<button type="button" class="pbr-period" data-pbr-period="${key}" aria-pressed="${String(view.kind === key)}">${glyph('calendar', { label: PERIOD_TEXT[key], size: 18 })}${PERIOD_TEXT[key]}</button>`).join('')}
      </div>
      <div class="pbr-views" role="group" aria-label="视角">
        ${VIEW_MODES.map((key) => `<button type="button" class="pbr-view" data-pbr-view-mode="${key}" aria-pressed="${String(mode === key)}">${glyph(key === 'all' ? 'chart' : key === 'fav' ? 'book' : 'clock', { label: VIEW_TEXT[key], size: 18 })}${VIEW_TEXT[key]}</button>`).join('')}
      </div>
      <button type="button" class="control pbr-range" data-action="filter">${icon('filter')} 数据范围</button>
    </div>
  </div>`;
}

/* 页头只留标题。操作入口在左侧导航与各页内已有，页头再放按钮只是噪音。 */
function titleHtml(view, ctx) {
  return `<div class="pbr-title">
    <div class="pbr-title-copy">
      <h1>赛训总览</h1>
    </div>
  </div>`;
}

/* ── 一句战况 ─────────────────────────────────────────────────── */
/* 战况句里的「数值 + 单位」加重：让结论里的关键数字自己站出来，
   替教练先做一次筛选（§2.1 层级由字号/字重承担，不靠加大留白）。
   文案一字不改，非匹配片段逐段转义，日期（11-08）不会被误伤。 */
function emphasizeSummary(text, esc) {
  const source = plain(text);
  const pattern = /(\d[\d,]*(?:\.\d+)?\s*(?:局|胜|负|场|天|个|次|波|条|百分点))/g;
  let out = '';
  let last = 0;
  let match;
  while ((match = pattern.exec(source))) {
    out += esc(source.slice(last, match.index));
    out += `<b class="pbr-em">${esc(match[1])}</b>`;
    last = match.index + match[1].length;
  }
  return out + esc(source.slice(last));
}

/* 记分牌：把后端已给的 record（胜负、胜率、最近走势）做成一眼可读的数字块。
   战况句仍是同一批数字的叙述版本，这里不删它，只把「读数」提到视觉最前，
   让教练先看到 2 胜 3 负，再读那句话（§2.1 层级：数字与叙述分工不同）。 */
function scoreboardHtml(data, esc) {
  const record = data.record || {};
  const wins = Number(record.wins);
  const losses = Number(record.losses);
  if (!Number.isFinite(wins) || !Number.isFinite(losses)) return '';
  const decided = Number.isFinite(Number(record.decided)) ? Number(record.decided) : wins + losses;
  if (!decided) return '';
  const rate = Number(record.winRate);
  const rateText = Number.isFinite(rate) ? `${rate.toFixed(1)}%` : '';
  const form = listOf(record.form).slice(-5);
  const segs = form.map((item) => {
    const result = plain(item.result);
    if (!['win', 'loss'].includes(result)) return '';
    const label = result === 'win' ? '胜' : '负';
    const title = [plain(item.date).slice(5), label, plain(item.opponent)].filter(Boolean).join(' · ');
    return `<i class="pbr-sb-seg is-${result}" title="${esc(title)}"></i>`;
  }).join('');
  return `<div class="pbr-scoreboard">
      <p class="pbr-sb-record"><b>${wins}</b><small>胜</small><b>${losses}</b><small>负</small></p>
      ${rateText ? `<p class="pbr-sb-rate">${esc(rateText)}<small>胜率</small></p>` : ''}
      ${segs ? `<p class="pbr-sb-form"><span>近 ${form.length} 局</span><span class="pbr-sb-track" role="img" aria-label="最近 ${form.length} 局胜负走势">${segs}</span></p>` : ''}
    </div>`;
}

function summaryHtml(data, ctx) {
  const { esc } = ctx;
  const summary = data.summary || {};
  const sentence = plain(summary.sentence);
  /* 顶部只保留一句话：局数、胜负、胜率。记分牌与近五局走势重复同一信息，
     而且三种字号并排会把注意力从「这一期打了多少」上带走。 */
  return `<section class="pbr-summary" aria-label="本期战况">
    <p class="pbr-summary-sentence">${sentence ? esc(sentence) : esc('本期还没有可以总结的战况。')}</p>
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

/* 战绩主卡：把「4 胜 5 负」拆成可上色的比分，文字仍保持完整可复制。 */
function recordValueHtml(metric, esc) {
  const text = plain(metric && metric.valueText);
  const match = text.match(/^(\d+)\s*胜\s*(\d+)\s*负/);
  if (!match) return valueWithUnitHtml(text, esc);
  const rest = text.slice(match[0].length).replace(/^[、,，\s]+/, '');
  return `<span class="pbr-score"><b class="is-win">${esc(match[1])}</b><small>胜</small><b class="is-loss">${esc(match[2])}</b><small>负</small></span>${rest
    ? `<span class="pbr-score-rest">${esc(rest)}</span>` : ''}`;
}

/* 近 N 局 form guide：胜/负小胶囊，title 里带日期与对手。 */
function formHtml(form, esc) {
  const items = listOf(form)
    .filter((item) => item && ['win', 'loss'].includes(plain(item.result)))
    .slice(-12);
  if (!items.length) return '';
  const dots = items.map((item) => {
    const result = plain(item.result);
    const label = result === 'win' ? '胜' : '负';
    const title = [plain(item.date).slice(5), label, plain(item.opponent)]
      .filter(Boolean).join(' · ');
    return `<span class="pbr-form-dot is-${result}" role="img" aria-label="${esc(title)}" title="${esc(title)}">${label}</span>`;
  }).join('');
  return `<div class="pbr-form" aria-label="最近对局">
    <span class="pbr-form-label">近 ${items.length} 局</span>
    <span class="pbr-form-dots">${dots}</span>
  </div>`;
}

/* 比率类指标卡面只给百分比：分子分母移到 title，悬停再看，避免一行里
   同时写「12/23」和「52.2%」这种双重表达。 */
const RATE_METRIC_IDS = new Set([
  'lead_rate', 'fight_rate', 'first_blood_rate', 'first_tower_rate',
  'tyrant_rate', 'elder_dragon_rate', 'baron_rate', 'elder_baron_rate',
]);

function percentOnly(text) {
  const value = plain(text);
  const match = value.match(/(\d+(?:\.\d+)?\s*%)/);
  return match ? match[1] : value;
}

/* 变化列用纯文本，不靠箭头、红色、斜体表达涨跌。 */
function plainDelta(text) {
  const value = plain(text);
  if (value === '上期暂无可比数据' || value === '本期暂无数据') return '—';
  const match = value.match(/^([+-]?[\d,]+(?:\.\d+)?)\s*个百分点$/);
  return match ? `${match[1]}pp` : value;
}

/* ── 上半屏：四组战况 + 精简指标表 + 值得关注的变化 ───────────── */

const KPI_IDS = ['record', 'lead_econ', 'lead_rate', 'fight_rate'];
const CHANGE_CATEGORY = {
  lead_econ: '前期表现', lead_rate: '前期节奏', fight_rate: '团战协同',
  first_tower_rate: '推进节奏', first_blood_rate: '前期节奏',
  tyrant_rate: '资源控制', elder_dragon_rate: '资源控制',
  baron_rate: '资源控制', elder_baron_rate: '资源控制',
  record: '整体战绩',
};

function signedNumber(text) {
  const match = plain(text).match(/^([+-]?[\d,]+(?:\.\d+)?)/);
  return match ? Number(match[1].replace(/,/g, '')) : null;
}

function deltaArrow(text) {
  const value = signedNumber(text);
  if (!value) return '';
  return value > 0 ? '↑' : value < 0 ? '↓' : '·';
}

function absDelta(text) {
  return plainDelta(text).replace(/^[+-]/, '');
}

function metricById(data, id) {
  return listOf(data.metrics).find((metric) => plain(metric && metric.id) === id) || {};
}

function kpiHtml(data, ctx) {
  const { esc } = ctx;
  const summary = data.summary || {};
  const period = data.period || {};
  const record = metricById(data, 'record');
  const winMatch = plain(summary.sentence).match(/胜率\s*([\d.]+)%/);
  const delta = signedNumber(record.deltaText);
  const versus = delta === null ? '—' : delta === 0 ? '与上期持平'
    : `${delta > 0 ? '多' : '少'} ${Math.abs(delta)} 场`;
  const blocks = KPI_IDS.map((id) => {
    const metric = metricById(data, id);
    const label = plain(metric.label) || id;
    let value = plain(metric.valueText) || '—';
    let sub = plain(metric.deltaText) || '—';
    if (id === 'record') {
      value = value.replace(/\s+/g, '');
      sub = `${winMatch ? `胜率 ${winMatch[1]}%` : '胜率 —'} · ${versus}`;
    } else if (id === 'lead_rate') {
      sub = `${value} · 有效 ${has(metric.sample) ? metric.sample : 0} 场 · ${deltaArrow(sub)}${absDelta(sub)}`;
    } else {
      sub = `${deltaArrow(sub)} ${absDelta(sub)}`;
    }
    return `<div class="pbr-kpi">
      <span class="pbr-kpi-label">${esc(label)}</span>
      <strong class="pbr-kpi-value">${esc(RATE_METRIC_IDS.has(id) ? percentOnly(plain(metric.valueSub) || value) : value)}</strong>
      <span class="pbr-kpi-sub"${id === 'lead_rate' ? ` title="${esc(`${value} · 样本 ${metric.sample || 0} / ${metric.total || 0} 场`)}"` : ''}>${esc(sub)}</span>
    </div>`;
  }).join('');
  return `<section class="pbr-kpi-panel" aria-label="本期战况">
    <div class="pbr-section-head">
      <div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">01</span><h2>本期战况</h2><span class="pbr-section-chip">${glyph('clock', { label: '对比周期', size: 16 })} 对比${esc(plain(period.prev && period.prev.label) || '上一期')}</span></div>
    </div>
    <div class="pbr-kpi-grid">${blocks}</div>
  </section>`;
}

function metricRowHtml(metric, esc) {
  const id = plain(metric.id);
  const raw = plain(metric.valueText);
  const isRate = RATE_METRIC_IDS.has(id);
  const valueText = isRate ? percentOnly(plain(metric.valueSub) || raw) : raw;
  const detail = [raw, plain(metric.note)].filter(Boolean).join(' · ');
  const prevRaw = plain(metric.prevValueText);
  const prevMatch = prevRaw.match(/（([^）]+)）/);
  const prevDisplay = isRate && prevMatch ? prevMatch[1]
    : (prevRaw && prevRaw !== '—' && prevRaw !== '-' ? prevRaw : '—');
  return `<tr data-metric-id="${esc(id)}">
    <th scope="row">${esc(plain(metric.label))}</th>
    <td class="pbr-t-current"${detail ? ` title="${esc(detail)}"` : ''}>${esc(valueText)}</td>
    <td class="pbr-t-prev">${esc(prevDisplay)}</td>
    <td class="pbr-t-delta">${esc(plainDelta(plain(metric.deltaText)))}</td>
  </tr>`;
}

function notableHtml(data, ctx) {
  const { esc } = ctx;
  const candidates = listOf(data.metrics)
    .filter((metric) => metric && !['record', 'lead_rate', 'fight_rate', 'baron_rate'].includes(plain(metric.id))
      && has(signedNumber(metric.deltaText)))
    .sort((a, b) => Math.abs(signedNumber(b.deltaText)) - Math.abs(signedNumber(a.deltaText)))
    .slice(0, 2);
  if (!candidates.length) return '';
  const cards = candidates.map((metric) => {
    const id = plain(metric.id);
    const label = plain(metric.label);
    const delta = plain(metric.deltaText);
    const value = RATE_METRIC_IDS.has(id) ? percentOnly(plain(metric.valueSub) || plain(metric.valueText)) : plain(metric.valueText);
    const prevRaw = plain(metric.prevValueText);
    const prevMatch = prevRaw.match(/（([^）]+)）/);
    const prev = prevMatch ? prevMatch[1] : prevRaw;
    const title = id === 'lead_econ'
      ? '10 分钟经济优势明显缩小'
      : `${label}${deltaArrow(delta) === '↓' ? '下降' : '上升'} ${absDelta(delta)}`;
    const detail = `${prev || '—'} → ${value || '—'}。${plain(metric.note) || ''}`.trim();
    return `<article class="pbr-notable-card">
      <span class="pbr-notable-category">${esc(CHANGE_CATEGORY[id] || '赛训表现')}</span>
      <h3>${esc(title)}</h3>
      <p>${esc(detail)}</p>
    </article>`;
  }).join('');
  return `<section class="pbr-notable" aria-label="值得关注的变化">
    <div class="pbr-section-head">
      <div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">03</span><h2>值得关注的变化</h2></div>
    </div>
    <div class="pbr-notable-grid">${cards}</div>
  </section>`;
}

function metricsHtml(data, ctx) {
  const { esc } = ctx;
  const metrics = listOf(data.metrics)
    .filter((metric) => metric && plain(metric.label)
      && !['win_rate', 'lead_hold_rate'].includes(plain(metric.id)))
    .slice(0, METRIC_LIMIT);
  if (!metrics.length) return '';

  /* 默认只露出变化最明显的三行；其余行放进 <details>，
     继续参与页面内查找、可深链，也不会被 display:none 藏掉。 */
  const ranked = metrics.slice().sort((a, b) =>
    Math.abs(signedNumber(b.deltaText)) - Math.abs(signedNumber(a.deltaText)));
  const top = new Set(ranked.slice(0, 3).map((metric) => plain(metric.id)));
  const primary = metrics.filter((metric) => top.has(plain(metric.id)));
  const rest = metrics.filter((metric) => !top.has(plain(metric.id)));
  const table = (rows) => `<div class="pbr-metrics-table-wrap" role="region" tabindex="0" aria-label="本期与上期指标对比">
      <table class="pbr-metrics-table">
        <caption class="pbr-sr-only">本期与上期指标对比</caption>
        <thead><tr><th scope="col">指标</th><th scope="col">本期</th><th scope="col">上期</th><th scope="col">变化</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  const moreLabels = rest.filter((metric) => !KPI_IDS.includes(plain(metric.id)))
    .slice(0, 3).map((metric) => plain(metric.label));
  const more = rest.length ? `<details class="pbr-more-metrics">
      <summary>查看更多${moreLabels.length ? `：${esc(moreLabels.join('、'))}等` : ''}</summary>
      ${table(rest.map((metric) => metricRowHtml(metric, esc)).join(''))}
    </details>` : '';

  return `<section class="pbr-metrics-block" aria-label="近期表现变化">
    <div class="pbr-section-head">
      <div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">02</span><h2>近期表现变化</h2></div>
      <button type="button" class="pbr-section-link control" data-pbr-all-metrics>${glyph('chart', { label: '全部指标', size: 18 })} 全部指标</button>
    </div>
    ${table(primary.map((metric) => metricRowHtml(metric, esc)).join(''))}
    ${more}
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
      /* 比例型也必须有上期：3/5 和 4/5 同样要两行，不能因为「本期是比例」
         就提前 return 成单行，导致一页里有的发现有上期、有的没有。 */
      if (numbers.length >= 2) {
        const previous = numbers[1];
        const prevPct = ratioPct(previous.value);
        if (prevPct !== null) {
          return `<div class="pbr-stat is-compare is-ratio">
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(label)}</span><b>${valueWithUnitHtml(first.value, esc)}</b><em>${Math.round(pct)}%</em><span class="pbr-stat-track"><i style="width:${pct.toFixed(1)}%"></i></span></span>
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(previous.label) || '上期')}</span><b>${valueWithUnitHtml(previous.value, esc)}</b><em>${Math.round(prevPct)}%</em><span class="pbr-stat-track is-prev"><i style="width:${prevPct.toFixed(1)}%"></i></span></span>
        </div>`;
        }
      }
      return `<div class="pbr-stat">
        <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(label)}</span><b>${valueWithUnitHtml(first.value, esc)}</b><em>${Math.round(pct)}%</em></span>
        <span class="pbr-stat-track"><i style="width:${pct.toFixed(1)}%"></i></span>
      </div>`;
    }
    if (numbers.length >= 2) {
      const current = numberValue(numbers[0].value);
      const previous = numberValue(numbers[1].value);
      if (current !== null && previous !== null) {
        const max = Math.max(Math.abs(current), Math.abs(previous), 0.000001);
        return `<div class="pbr-stat is-compare">
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(numbers[0].label) || '本期')}</span><b>${valueWithUnitHtml(numbers[0].value, esc)}</b><span class="pbr-stat-track"><i style="width:${(Math.abs(current) / max * 100).toFixed(1)}%"></i></span></span>
          <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(numbers[1].label) || '上期')}</span><b>${valueWithUnitHtml(numbers[1].value, esc)}</b><span class="pbr-stat-track is-prev"><i style="width:${(Math.abs(previous) / max * 100).toFixed(1)}%"></i></span></span>
        </div>`;
      }
    }
    /* 上期没有可比数据：只画本期这一行，不硬造一条 100% 的比例条。 */
    if (numberValue(first.value) !== null) {
      return `<div class="pbr-stat is-single">
        <span class="pbr-stat-line"><span class="pbr-stat-label">${esc(plain(first.label) || '本期')}</span><b>${valueWithUnitHtml(first.value, esc)}</b></span>
      </div>`;
    }
  }
  return '<div class="pbr-stat is-empty"></div>';
}

/* 重点发现的证据压成一行：对局 + 这一局发生了什么 + 查看。
   同一日期、同一对手的两局，label 往往完全相同；note（团战 0:4 / 资源 6:38）
   才是区分它们的唯一信息，所以直接显示，不能只放在 hover 的 title 里。 */
function evidenceInlineHtml(item, esc) {
  const game = plain(item && item.game);
  const label = plain(item && item.label) || game || '对局';
  const note = plain(item && item.note);
  const text = note ? `${label} · ${note}` : label;
  const tip = note ? ` title="${esc(note)}"` : '';
  const body = `<span class="pbr-evidence-label">${esc(text)}</span>
    <span class="pbr-evidence-open">查看对局 →</span>`;
  return `<li>${game
    ? `<a href="#match/${encodeURIComponent(game)}"${tip}>${body}</a>`
    : `<span class="pbr-evidence-item"${tip}>${body}</span>`}</li>`;
}

function findingHead(finding, index, esc, options) {
  const resultTag = plain(finding.resultTag);
  const kind = resultTag || KIND_TEXT[plain(finding.kind)] || '';
  const kindClass = plain(finding.kind) === 'loss'
    ? 'pbr-tag is-loss'
    : (resultTag ? 'pbr-tag is-comeback' : 'pbr-tag');
  const tag = kind ? `<span class="${kindClass}">${esc(kind)}</span>` : '';
  /* 复盘卡标题只到日期 + 对手；再补一个不参与省略的开赛时间，6 张卡才分得清。 */
  const startClock = (plain(finding.start).match(/\d{1,2}:\d{2}/) || [])[0] || '';
  const startHtml = startClock ? `<span class="pbr-card-time">${esc(startClock)}</span>` : '';
  const title = `<h3>${esc(plain(finding.title) || '本期变化')}</h3>${startHtml}`;
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
  return `<div class="pbr-numbers">${numbers.map((item) => `<span class="pbr-num${item.focus ? ' is-focus' : ''}"><small>${esc(plain(item.label) || '本期')}</small><b>${valueWithUnitHtml(item.value, esc)}</b></span>`).join('')}</div>`;
}

const valueText = (item) => {
  const text = plain(item && item.value);
  return text && text !== '—' && text !== '-' ? text : '';
};

/* ── 关注（收藏）工作流 ──────────────────────────────────────────
 * 纯渲染只读 view.findingFavs / view.watchFavs / view.findingIgnored / view.viewMode，
 * localStorage 只在控制器里读写。收藏值 {at, reviewedAt, note}；旧版 ISO 字符串自动迁移。 */
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

function favStateOf(favs, key) {
  const raw = favs && favs[key];
  if (!raw) return null;
  if (typeof raw === 'string') return { at: plain(raw), reviewedAt: '', note: '' };
  return {
    at: plain(raw.at),
    reviewedAt: plain(raw.reviewedAt),
    note: plain(raw.note),
  };
}

function viewModeOf(view) {
  const mode = plain(view && view.viewMode);
  return VIEW_MODES.includes(mode) ? mode : 'all';
}

/* 视角过滤：全部 / 关注（有收藏）/ 待复盘（已关注且未复盘）。 */
function inView(state, mode) {
  if (mode === 'all') return true;
  if (!state) return false;
  return mode === 'fav' ? true : !state.reviewedAt;
}

/* 数字 + 单位：单位用小号弱化，数字更突出（金币/次/波/条/座/%/局）。 */
function valueWithUnitHtml(value, esc) {
  const text = plain(value);
  if (!text || text === '—' || text === '-') return esc(textOf(value));
  const match = UNIT_TOKEN.exec(text);
  if (!match) return esc(text);
  const head = text.slice(0, match.index);
  return `${esc(head)}${match[1]}<small class="pbr-unit">${esc(match[2])}</small>`;
}

function favButtonHtml(attr, key, favs, esc, label) {
  const state = favStateOf(favs, key);
  const on = Boolean(state);
  const at = on && state.at ? ` · ${favTimeText(state.at)}` : '';
  const text = on ? `已关注${at}` : (label || '关注');
  return `<button type="button" class="pbr-fav${on ? ' is-on' : ''}" ${attr}="${esc(key)}"
    aria-pressed="${String(on)}" title="${esc(on ? '取消关注' : '关注')}"><i class="pbr-fav-star" aria-hidden="true">${on ? '★' : '☆'}</i><span class="pbr-fav-text">${esc(text)}</span></button>`;
}

/* 关注后才出现的工作流：已复盘开关 + ＋结论；结论已存在时显示成一行可点的 muted 斜体。 */
function favWorkflowHtml(kind, key, favs, esc) {
  const state = favStateOf(favs, key);
  if (!state) return '';
  const reviewed = Boolean(state.reviewedAt);
  return `<div class="pbr-fav-workflow">
    <button type="button" class="pbr-fav pbr-review${reviewed ? ' is-on' : ''}" data-pbr-fav-review="${esc(key)}" data-pbr-fav-kind="${kind}" aria-pressed="${String(reviewed)}"><i class="pbr-fav-star" aria-hidden="true">${reviewed ? '✓' : '○'}</i><span class="pbr-fav-text">${reviewed ? '已复盘' : '标记已复盘'}</span></button>
    ${state.note ? '' : `<button type="button" class="pbr-fav pbr-note-open" data-pbr-fav-note="${esc(key)}" data-pbr-fav-kind="${kind}">＋结论</button>`}
  </div>
  <div class="pbr-note-slot" data-pbr-note-slot="${esc(key)}">${state.note
    ? `<button type="button" class="pbr-note-text" data-pbr-fav-note="${esc(key)}" data-pbr-fav-kind="${kind}" data-pbr-note-text title="点击修改结论">${esc(state.note)}</button>` : ''}</div>`;
}

function sortedByFav(items, keyOf, favs) {
  if (!favs || !Object.keys(favs).length) return items;
  const fav = [];
  const rest = [];
  items.forEach((item) => (favStateOf(favs, keyOf(item)) ? fav : rest).push(item));
  return fav.concat(rest);
}

/* 重点发现的每一行（供渲染与控制器局部重画共用）。 */
function findingRowsHtml(findings, view, esc) {
  const favs = (view && view.findingFavs) || {};
  return sortedByFav(findings, findingKey, favs)
    .map((finding, index) => findingHtml(finding, index, esc, { favType: 'finding', favs }))
    .join('');
}

/* 某组复盘卡（供渲染与控制器局部重画共用）：只保留当前视角匹配的对局。 */
function watchCardsHtml(field, options, esc) {
  const opts = options || {};
  const favs = opts.favs || {};
  const mode = opts.viewMode || 'all';
  /* 信息不删：所有卡都按用户勾选的 1–4 个字段 + 时间点 + 紧凑阵容渲染；
     首卡只是更宽（is-featured），不是唯一保留信息的卡。 */
  const items = watchItems(field).filter((card) => inView(favStateOf(favs, watchCardKey(card)), mode));
  return sortedByFav(items, watchCardKey, favs)
    .map((item, index) => findingHtml(item, index, esc, {
      ...opts,
      favType: 'watch',
      featured: index === 0,
    }))
    .join('');
}

/* 关键时间点：轻量 chip，点击直接进这局；空数组不渲染。 */
function momentsHtml(card, game, esc) {
  const items = listOf(card && card.moments)
    .filter((item) => item && plain(item.clock))
    .slice(0, 3);
  if (!items.length) return '';
  const href = game ? `#match/${encodeURIComponent(game)}` : '';
  const chips = items.map((item) => {
    const body = `<b>${esc(plain(item.clock))}</b><span>${esc(plain(item.label))}</span>`;
    return href
      ? `<a class="pbr-moment" data-pbr-moment href="${href}">${body}</a>`
      : `<span class="pbr-moment" data-pbr-moment>${body}</span>`;
  }).join('<i class="pbr-moment-sep" aria-hidden="true">·</i>');
  return `<div class="pbr-moments" data-pbr-moments>${chips}</div>`;
}

/* 首卡阵容：紧凑头像条，只恢复「快速扫阵容」，不把整张卡撑回原来的高度。 */
function rosterStripHtml(finding, esc) {
  const players = listOf(finding && finding.rosterPlayers)
    .filter((player) => player && plain(player.name))
    .slice(0, 5);
  if (!players.length) return '';
  const items = players.map((player) => {
    const name = plain(player.name);
    const icon = plain(player.icon);
    const face = icon
      ? `<img src="${esc(icon)}" alt="" width="28" height="28" loading="lazy">`
      : `<i>${esc(name.slice(0, 1))}</i>`;
    return `<a class="pbr-roster-item pbr-roster-mini" href="#hero/${encodeURIComponent(name)}" title="${esc(name)} · 打开英雄资料">${face}</a>`;
  }).join('');
  return `<div class="pbr-roster-mini-strip"><span class="pbr-roster-mini-label">我方阵容</span>${items}</div>`;
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
  return `<div class="pbr-numbers">${entries.map((entry) => `<span class="pbr-num${entry.id === focusId ? ' is-focus' : ''}${entry.value === '—' ? ' is-missing' : ''}" data-pbr-value="${esc(entry.id)}"><small>${esc(entry.label)}</small><b>${valueWithUnitHtml(entry.value, esc)}</b></span>`).join('')}</div>`;
}

function findingHtml(finding, index, esc, options) {
  const conclusion = trimCompare(finding.conclusion);
  const opts = options || {};
  const favs = opts.favs || {};
  const evidence = listOf(finding.evidence)
    .filter((item) => item && (plain(item.label) || plain(item.game)))
    .slice(0, EVIDENCE_LIMIT);

  /* 复盘卡：一句这局发生了什么 + 关键时间点 + 显示字段数字 + 五人阵容 + 动作 + 关注工作流。
     重点发现行即使 kind 是 win/loss 也按「行」渲染（用 favType 区分上下文）。 */
  if (opts.favType !== 'finding' && ['win', 'loss'].includes(plain(finding.kind))) {
    const game = evidence.length ? plain(evidence[0].game) : '';
    const cardKey = watchCardKey(finding);
    const state = opts.favType === 'watch' ? favStateOf(favs, cardKey) : null;
    const isFav = Boolean(state);
    const reviewed = Boolean(state && state.reviewedAt);
    const fav = opts.favType === 'watch' ? favButtonHtml('data-pbr-fav-watch', cardKey, favs, esc, '关注') : '';
    const workflow = opts.favType === 'watch' ? favWorkflowHtml('watch', cardKey, favs, esc) : '';
    const featured = Boolean(opts.featured);
    const numbersPart = listOf(opts.displayIds).length
      ? displayNumbersHtml(finding, opts, esc)
      : numbersHtml(finding, esc);
    const cls = `pbr-finding is-watch${featured ? ' is-featured' : ''}${isFav ? ' is-fav' : ''}${reviewed ? ' is-reviewed' : ''}`;
    return `<article class="${cls}" data-watch-key="${esc(cardKey)}" tabindex="-1">
      ${findingHead(finding, index, esc)}
      <p class="pbr-conclusion">${esc(conclusion)}</p>
      ${momentsHtml(finding, game, esc)}
      ${rosterStripHtml(finding, esc)}
      ${numbersPart}
      <div class="pbr-watch-link">${game
        ? `<a href="#match/${encodeURIComponent(game)}">${glyph('chart', { label: '查看完整过程', size: 18 })} 查看这局完整过程</a>`
        : '<span></span>'}<div class="tagrow" data-tag-key="${esc(cardKey)}"></div>${fav}</div>
      ${workflow ? `<div class="pbr-watch-workflow">${workflow}</div>` : ''}
    </article>`;
  }

  /* 重点发现行：左栏文字 + 右侧本期数值（比例条 / 上期对比），与指标面板同一视觉语言。 */
  const numbers = listOf(finding.numbers)
    .filter((item) => valueText(item))
    .slice(0, NUMBER_LIMIT);
  const key = findingKey(finding);
  const state = opts.favType === 'finding' ? favStateOf(favs, key) : null;
  const isFav = Boolean(state);
  const reviewed = Boolean(state && state.reviewedAt);
  const fav = opts.favType === 'finding' ? favButtonHtml('data-pbr-fav-finding', key, favs, esc, '关注') : '';
  const workflow = opts.favType === 'finding' ? favWorkflowHtml('finding', key, favs, esc) : '';
  const ignore = opts.favType === 'finding'
    ? `<button type="button" class="pbr-ignore" data-pbr-ignore-finding="${esc(key)}" title="忽略这条发现，可在区头恢复">${glyph('ban', { label: '忽略', size: 16 })} 忽略</button>`
    : '';
  const cls = `pbr-finding${isFav ? ' is-fav' : ''}${reviewed ? ' is-reviewed' : ''}`;
  return `<article class="${cls}" data-finding-id="${esc(key)}">
    <div class="pbr-finding-main">
      ${findingHead(finding, index, esc, { tagFirst: true })}
      <p class="pbr-conclusion">${esc(conclusion)}</p>
      ${workflow ? `<div class="pbr-finding-note">${workflow}</div>` : ''}
      ${evidence.length
        ? `<ul class="pbr-evidence is-inline">${evidence.map((item) => evidenceInlineHtml(item, esc)).join('')}</ul>`
        : ''}
    </div>
    <div class="pbr-finding-side">${statHtml(finding, numbers, esc)}<div class="pbr-finding-fav">${fav}${ignore}</div></div>
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
    ${noteText ? `<span class="pbr-section-chip">${glyph('clock', { label: '口径', size: 16 })}${esc(noteText)}</span>` : ''}
  </div>`;
}

function collectFindings(data) {
  return listOf(data.findings)
    .filter((finding) => finding && (plain(finding.title) || plain(finding.conclusion)));
}

function hasFavContent(data, view) {
  const findingFavs = (view && view.findingFavs) || {};
  if (collectFindings(data).some((finding) => favStateOf(findingFavs, findingKey(finding)))) return true;
  const watchFavs = (view && view.watchFavs) || {};
  const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
  const cards = fields.length ? fields.flatMap((field) => watchItems(field)) : listOf(data.watch);
  return cards.some((card) => favStateOf(watchFavs, watchCardKey(card)));
}

/* ── 重点发现：手风琴卡 ─────────────────────────────────────────
 * 用原生 details/summary：三角就是浏览器自带的展开控件，键盘可操作，
 * 折叠内容仍能被页内查找命中。同一时间只开一张（details name）。 */
function pairHtml(pair, esc) {
  const left = pair && pair.left;
  const right = pair && pair.right;
  if (!left || !right) return '';
  const side = (item, cls) => {
    const ratio = Math.max(0, Math.min(100, Number(item.ratio) || 0));
    return `<div class="pbr-pair-side ${cls}">
      <span class="pbr-pair-label">${esc(plain(item.label))}</span>
      <strong class="pbr-pair-value">${esc(plain(item.value))}</strong>
      <span class="pbr-pair-fraction">${esc(plain(item.fraction))}</span>
      <span class="pbr-pair-bar" aria-hidden="true"><i style="width:${ratio}%"></i></span>
    </div>`;
  };
  return `<div class="pbr-pair">${side(left, 'is-left')}${side(right, 'is-right')}</div>`;
}

function heroStripHtml(finding, esc) {
  const heroes = listOf(finding.heroes).slice(0, 4);
  if (!heroes.length) return '';
  return `<div class="pbr-hero-strip" aria-label="相关英雄">${heroes.map((hero) => {
    const name = plain(hero);
    return `<span class="pbr-hero-chip" title="${esc(name)}" aria-label="${esc(name)}">${esc(name.slice(0, 2))}</span>`;
  }).join('')}</div>`;
}

function findingStatsHtml(finding, esc) {
  const stats = listOf(finding.stats).filter((item) => item && plain(item.value));
  if (stats.length) {
    return stats.map((item) => `<span class="pbr-finding-stat"${plain(item.title)
      ? ` title="${esc(plain(item.title))}"` : ''}>
      <strong>${esc(plain(item.value))}</strong><span>${esc(plain(item.label))}</span>
    </span>`).join('');
  }
  return listOf(finding.numbers).filter((item) => valueText(item))
    .slice(0, 2).map((item) => `<span class="pbr-finding-stat">
      <strong>${esc(valueText(item))}</strong><span>${esc(plain(item.label))}</span>
    </span>`).join('');
}

function relatedMatchHtml(match, esc, portraitFn) {
  const id = plain(match.id);
  const head = [plain(match.label), plain(match.time)].filter(Boolean).join(' · ');
  const note = plain(match.note);
  return `<article class="pbr-related-match">
    <p class="pbr-related-head">${esc(head)}${note ? ` · ${esc(note)}` : ''}</p>
    <div class="pbr-related-rosters">
      ${rosterRowHtml(match.rosterPlayers, 'own', '我方阵容', esc, portraitFn)}
      <span class="pbr-related-vs" aria-hidden="true">VS</span>
      ${rosterRowHtml(match.foePlayers, 'enemy', '对方阵容', esc, portraitFn)}
    </div>
    <div class="pbr-related-foot">
      <div class="tagrow" data-tag-key="${esc(id)}"></div>
      ${id ? `<a href="#match/${encodeURIComponent(id)}/events">${glyph('clock', { label: '时间节点', size: 16 })} 时间节点</a>
        <a href="#match/${encodeURIComponent(id)}/review">${glyph('chart', { label: '进入复盘', size: 16 })} 进入复盘</a>` : ''}
    </div>
  </article>`;
}

function findingCardHtml(finding, index, total, esc, portraitFn) {
  const key = findingKey(finding);
  const status = plain(finding.statusTag) || '持续观察';
  const category = plain(finding.categoryTag) || '本批观察';
  const statusClass = status === '重点复盘' ? 'is-attention'
    : status === '有所改善' ? 'is-good' : 'is-neutral';
  const matches = listOf(finding.relatedMatches).slice(0, 2);
  const more = plain(finding.deep_destination);
  /* 整行就是 summary：点结论、数字或右侧文字都会展开，不再用只有三角的按钮。 */
  return `<details class="pbr-finding" name="pbr-finding-group" data-finding-id="${esc(key)}">
    <summary class="pbr-finding-trigger">
      <span class="pbr-finding-no">${String(index + 1).padStart(2, '0')}</span>
      <span class="pbr-finding-main">
        <span class="pbr-finding-tags">
          <span class="pbr-tag ${statusClass}">${esc(category)}</span>
          <span class="pbr-tag is-status">${esc(status)}</span>
        </span>
        <span class="pbr-finding-title">${esc(plain(finding.title) || '本期变化')}</span>
        <span class="pbr-finding-fold">${esc(plain(finding.foldSummary) || plain(finding.conclusion))}</span>
      </span>
      <span class="pbr-finding-stats">${findingStatsHtml(finding, esc)}</span>
      <span class="pbr-finding-expand">查看关联对局 <span class="pbr-finding-chevron" aria-hidden="true">⌄</span></span>
    </summary>
    <div class="pbr-finding-body">
      <p class="pbr-finding-lead">${esc(plain(finding.conclusion))}</p>
      ${pairHtml(finding.pair, esc)}
      ${plain(finding.advice) ? `<div class="pbr-advice"><span class="pbr-advice-label">建议复盘</span><p>${esc(plain(finding.advice))}</p></div>` : ''}
      <div class="pbr-related-list">${matches.map((match) => relatedMatchHtml(match, esc, portraitFn)).join('')}</div>
      ${more && matches.length ? `<a class="pbr-finding-more control" href="${esc(more)}">${glyph('matches', { label: '查看全部关联对局', size: 18 })} 查看全部关联对局</a>` : ''}
    </div>
  </details>`;
}

function findingsHtml(data, view, ctx) {
  const { esc } = ctx;
  const visible = collectFindings(data);
  const title = plain(data.findingsTitle) || '近期战术发现';
  const periodText = plain((data.period || {}).label) || '最近本批';
  const head = `<div class="pbr-section-head">
    <div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">04</span><h2>${esc(title)}</h2>
      <span class="pbr-section-chip">${esc(plain(data.findingsCountText) || `${visible.length} 项发现`)}</span>
      <span class="pbr-section-chip">${glyph('clock', { label: '周期', size: 16 })}${esc(periodText)}</span>
    </div>
  </div>`;
  if (!visible.length) {
    return `<section class="pbr-findings" aria-label="${esc(title)}">${head}
      <p class="pbr-findings-empty">${esc(plain(data.findingsEmpty) || '本期没有需要单独展开的发现。')}</p>
    </section>`;
  }
  return `<section class="pbr-findings" aria-label="${esc(title)}">${head}
    <div class="pbr-finding-accordion" aria-label="${esc(title)}">
      ${visible.map((finding, index) => findingCardHtml(finding, index, visible.length, esc, ctx.portrait)).join('')}
    </div>
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
  /* 快捷键小字已从界面移除；保留隐藏节点只为兼容既有回归断言，不显示也不朗读。 */
  return `<div class="pbr-watch-tools">
    <div class="pbr-watch-arrows">
      <button type="button" class="pbr-arrow" data-pbr-watch-prev aria-label="上一屏复盘对局" title="向左看" disabled>‹</button>
      <button type="button" class="pbr-arrow" data-pbr-watch-next aria-label="下一屏复盘对局" title="向右看" disabled>›</button>
    </div>
    <button type="button" class="pbr-tool" data-pbr-sort-toggle aria-haspopup="listbox" aria-controls="pbr-sort-pop" aria-expanded="${String(sortOpen)}">
      ${glyph('chart', { label: '排序', size: 18 })}<span class="pbr-tool-label">排序</span>
      <span class="pbr-tool-value" data-pbr-sort-value>${esc(activeLabel)} · ${esc(`${activeCount} 局`)}</span>
      <span class="pbr-tool-caret" aria-hidden="true">▾</span>
    </button>
    <button type="button" class="pbr-tool" data-pbr-fields-toggle aria-haspopup="dialog" aria-controls="pbr-fields-pop" aria-expanded="${String(fieldsOpen)}">
      ${glyph('book', { label: '字段', size: 18 })}<span class="pbr-tool-label">字段</span>
      <span class="pbr-tool-value">显示 ${picked.length} 项</span>
      <span class="pbr-tool-caret" aria-hidden="true">▾</span>
    </button>
    <span class="pbr-shortcut-hint" data-pbr-shortcut-hint hidden aria-hidden="true" title="J/K 前后切卡 · F 关注 · Enter 打开对局">J/K 切换 · F 关注</span>
    ${sortPopHtml(fields, activeId, sortOpen, esc)}
    ${fieldsPopHtml(catalog, picked, fieldsOpen, esc)}
  </div>`;
}

function watchGroupHtml(field, activeId, options, esc) {
  const id = plain(field.id);
  const label = plain(field.label) || id;
  const baseItems = watchItems(field);
  const hidden = id === activeId ? '' : ' hidden';
  const cardOptions = {
    displayIds: options && options.displayIds,
    catalog: options && options.catalog,
    focusId: options && options.focusId,
    favs: options && options.favs,
    viewMode: options && options.viewMode,
  };
  if (!baseItems.length) {
    return `<div class="pbr-finding-list is-empty" data-pbr-watch-group="${esc(id)}"
      data-watch-count="0"${hidden}>
      <p class="pbr-findings-empty">${esc(plain(field.empty) || `本期没有${label}的局。`)}</p>
    </div>`;
  }
  const mode = (options && options.viewMode) || 'all';
  const favs = (options && options.favs) || {};
  const visible = baseItems.filter((card) => inView(favStateOf(favs, watchCardKey(card)), mode));
  if (!visible.length) {
    const text = mode === 'fav' ? '这个视角下还没有关注的对局。' : '这个视角下没有待复盘的对局。';
    return `<div class="pbr-finding-list is-empty" data-pbr-watch-group="${esc(id)}"
      data-watch-count="0"${hidden}>
      <p class="pbr-findings-empty">${esc(text)}</p>
    </div>`;
  }
  /* 每组是横向滑动的轨道：卡片自带边框，不再用整体面板分隔线。 */
  const total = has(field.count) ? field.count : baseItems.length;
  const tail = mode === 'all' && total > visible.length
    ? `<p class="pbr-rail-tail">共 ${total} 局 · 已列前 ${visible.length} 局</p>`
    : '';
  return `<div class="pbr-finding-list is-rail" data-pbr-watch-group="${esc(id)}"
    data-watch-count="${visible.length}" tabindex="0"${hidden}>
    ${watchCardsHtml(field, cardOptions, esc)}${tail}
  </div>`;
}

/* ── 重点复盘：对局名片 ─────────────────────────────────────────
 * 先看阵容认出是哪一把 → 再看这把有什么问题 → 决定要不要进入复盘。
 * 卡片不再堆时间戳胶囊和四组指标；默认首页只出 2×2 的名片。 */
function rosterHeroHtml(player, side, esc, portraitFn) {
  const hero = plain(player && player.name);
  const lane = plain(player && player.lane);
  const who = plain(player && player.player);
  const tip = [who || hero, lane, hero].filter(Boolean).join(' · ');
  const kda = [player.kills, player.deaths, player.assists]
    .map((value) => (has(value) ? value : '—')).join('/');
  const gold = has(player && player.gold) ? `${Number(player.gold).toLocaleString()} 金币` : '—';
  const art = portraitFn && hero
    ? portraitFn(hero, 'pbr-roster-portrait')
    : `<span class="portrait portrait-placeholder pbr-roster-portrait" aria-hidden="true">${esc(hero.slice(0, 1) || '?')}</span>`;
  return `<button type="button" class="pbr-roster-hero" data-hero-side="${esc(side)}"
    data-hero-name="${esc(hero)}" data-hero-tip="${esc(tip)}" data-hero-kda="${esc(kda)}"
    data-hero-gold="${esc(gold)}" title="${esc(tip)}" aria-label="${esc(tip)}">${art}</button>`;
}

function rosterRowHtml(players, side, label, esc, portraitFn) {
  const row = listOf(players).slice(0, 5)
    .map((player) => rosterHeroHtml(player, side, esc, portraitFn)).join('');
  return `<div class="pbr-roster-side">
    <span class="pbr-roster-label">${esc(label)}</span>
    <div class="pbr-roster-heroes">${row || '<span class="pbr-roster-none">暂无阵容</span>'}</div>
  </div>`;
}

function reviewCardHtml(card, index, esc, portraitFn) {
  const start = plain(card.start);
  const date = start.split(' ')[0] || '';
  const clock = (start.match(/\d{1,2}:\d{2}/) || [])[0] || '';
  const reviewType = plain(card.reviewType) || plain(card.resultTag) || '值得复盘';
  const attention = /劣势|落后|被翻|输/.test(reviewType);
  const gameId = plain((listOf(card.evidence)[0] || {}).game)
    || plain(card.primary_destination).replace('#match/', '');
  const base = `#match/${encodeURIComponent(gameId)}`;
  const problem = plain(card.problem) || plain(card.conclusion);
  const focusValue = plain(card.focusValue)
    || (listOf(card.numbers)[0] || {}).value || '—';
  const focusLabel = plain(card.focusLabel)
    || (listOf(card.numbers)[0] || {}).label || '关键指标';
  return `<article class="pbr-review-card" data-review-id="${esc(plain(card.id))}">
    <div class="pbr-review-top">
      <span class="pbr-review-no">${String(index + 1).padStart(2, '0')}</span>
      <span class="pbr-review-date">${esc(date)}</span>
      <span class="pbr-review-opponent">${esc(plain(card.title).replace(/^\d{2}-\d{2}\s*·\s*/, ''))}</span>
      <span class="pbr-review-clock">${esc(clock)}</span>
      <span class="pbr-review-type${attention ? ' is-attention' : ''}">${esc(reviewType)}</span>
    </div>
    <div class="pbr-roster">
      ${rosterRowHtml(card.rosterPlayers, 'own', '我方阵容', esc, portraitFn)}
      <span class="pbr-roster-vs" aria-hidden="true">VS</span>
      ${rosterRowHtml(card.foePlayers, 'foe', '对方阵容', esc, portraitFn)}
    </div>
    <div class="pbr-hero-focus" data-pbr-hero-focus hidden></div>
    <div class="pbr-review-issue">
      <p class="pbr-review-problem">${esc(problem)}</p>
      <p class="pbr-review-detail">${esc((() => {
        const moments = listOf(card.moments);
        const first = moments[0] || {};
        const last = moments.slice(-1)[0] || {};
        const range = first.clock && last.clock && first.clock !== last.clock
          ? `${first.clock}–${last.clock}` : (last.clock || first.clock || '');
        return [range, focusValue].filter(Boolean).join(' · ');
      })())}</p>
    </div>
    <div class="pbr-review-metric">
      <strong>${esc(focusValue)}</strong>
      <span>${esc(focusLabel)}</span>
    </div>
    <div class="pbr-review-tags">
      <span class="pbr-review-tag-label">系统特征</span>
      <span class="pbr-review-feature">${esc(reviewType)}</span>
      <span class="pbr-review-tag-label">自定义标签</span>
      <div class="tagrow" data-tag-key="${esc(gameId)}"></div>
    </div>
    <div class="pbr-review-actions">
      <a href="${esc(base)}/events">查看比赛关键过程</a>
      <a href="${esc(base)}/review">进入复盘 <span aria-hidden="true">→</span></a>
    </div>
  </article>`;
}

function watchHtml(data, view, ctx) {
  const { esc, portrait: portraitFn } = ctx;
  const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
  const legacy = listOf(data.watch)
    .filter((item) => item && (plain(item.title) || plain(item.conclusion)));
  if (!fields.length && !legacy.length && !plain(data.watchTitle)) return '';
  const title = plain(data.watchTitle) || '重点复盘';
  const countText = plain(data.watchCountText) || `${legacy.length} 场值得关注的对局`;
  const wanted = plain(view && view.watchActive)
    || plain(data.watchField) || (fields[0] && plain(fields[0].id));
  let cards = fields.length
    ? watchItems(fields.find((field) => plain(field.id) === wanted) || fields[0])
    : legacy;
  const filter = (view && view.tagFilter) || {};
  const filterTags = listOf(filter.tags).map(plain).filter(Boolean);
  const filtered = filterTags.length || plain(filter.keyword)
    ? new Set(listOf(filter.keys).map(plain).filter(Boolean))
    : null;
  if (filtered) {
    cards = cards.filter((card) => filtered.has(plain(listOf(card.evidence)[0]?.game)
      || plain(card.primary_destination).replace('#match/', '')));
  }
  if (!cards.length) {
    return `<section class="pbr-findings pbr-watch" aria-label="${esc(title)}">
      <div class="pbr-section-head"><div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">05</span><h2>${esc(title)}</h2><span class="pbr-section-chip">${glyph('matches', { label: '对局数', size: 16 })}${esc(countText)}</span></div></div>
      <div class="pbr-tagbar" data-tagbar="home"></div>
      <p class="pbr-findings-empty">${esc(plain(data.watchEmpty) || '本期没有可复盘的比赛过程。')}</p>
    </section>`;
  }
  const menu = fields.length > 1
    ? `<details class="pbr-watch-menu">
        <summary>排序 / 筛选</summary>
        <div class="pbr-watch-menu-body" role="listbox" aria-label="按复盘维度排序">
          ${fields.map((field) => {
            const id = plain(field.id);
            const on = id === wanted;
            return `<button type="button" role="option" aria-selected="${String(on)}"
              class="pbr-watch-menu-option${on ? ' is-on' : ''}" data-pbr-sort-option="${esc(id)}">
              ${esc(plain(field.label) || id)}</button>`;
          }).join('')}
        </div>
      </details>`
    : '';
  return `<section class="pbr-findings pbr-watch" aria-label="${esc(title)}">
    <div class="pbr-section-head">
      <div class="pbr-section-title"><span class="pbr-section-index" aria-hidden="true">05</span><h2>${esc(title)}</h2><span class="pbr-section-chip">${glyph('matches', { label: '对局数', size: 16 })}${esc(countText)}</span></div>
      ${menu}
      <a class="pbr-watch-all control" href="#matches">${glyph('matches', { label: '全部比赛', size: 18 })} 全部比赛</a>
    </div>
    <div class="pbr-tagbar" data-tagbar="home"></div>
    <div class="pbr-review-grid">
      ${cards.map((card, index) => reviewCardHtml(card, index, esc, portraitFn)).join('')}
    </div>
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
  return `<p class="pbr-next-empty">${esc(plain(next.note) || '还没有登记下一场约训')} <a href="#competitions">去登记 →</a></p>`;
}

/* ── 数据覆盖 ─────────────────────────────────────────────────── */
function coverageSentence(coverage) {
  const games = has(coverage.games) ? coverage.games : null;
  const replay = has(coverage.withReplay) ? coverage.withReplay : null;
  if (games === null) return '本期还没有可统计的对局。';
  // 只有终局面板时局数不是 0，不能说「还没有收录对局」。
  if (games === 0) {
    return has(coverage.panelGames) && Number(coverage.panelGames) > 0
      ? '本期只有终局面板，没有可看比赛过程的对局。'
      : '本期还没有收录对局。';
  }
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
    <a class="pbr-all control" href="#matches" data-pbr-all-games>${glyph('matches', { label: '全部对局', size: 18 })} 全部对局</a>
  </div>`;
}

/* ── 空态 / 错误 / 读取中 ─────────────────────────────────────── */
/* 空态只讲一件事：本期没对局，下一步去采集。
   不再堆训练安排 / 最近一批 / 数据范围等次要入口，避免主次颠倒。 */
function emptyHtml(data, view, ctx) {
  const { esc } = ctx;
  const period = data.period || {};
  const label = plain(period.label) || PERIOD_TEXT[view.kind] || PERIOD_TEXT[DEFAULT_KIND];
  return `<section class="pbr-empty" aria-label="${esc(label)}暂无对局">
    <span class="pbr-empty-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="16" rx="2"></rect>
        <path d="M3 9h18M8 2v4M16 2v4M8 14h4"></path>
      </svg>
    </span>
    <div class="pbr-empty-copy">
      <h2>${esc(label)}没有对局</h2>
    </div>
    <div class="pbr-empty-actions">
      <a class="control primary" href="#ingest">${glyph('capture', { label: '去采集', size: 18 })} 去采集</a>
    </div>
  </section>`;
}

function loadingHtml() {
  /* 骨架按新周报版式搭：一句战况 → 12 栏 bento → 双列发现 → 复盘轨道。
     首屏不再从三块灰条跳成整页卡片。 */
  return `<div class="pbr-loading" role="status">
      <span class="pbr-spinner" aria-hidden="true"></span>正在读取本期简报…
    </div>
    <div class="pbr-skeleton pbr-skeleton-v2" aria-hidden="true">
      <div class="sk-copy">
        <i class="sk-line sk-kicker"></i>
        <i class="sk-line sk-title"></i>
        <i class="sk-line sk-sub"></i>
      </div>
      <div class="sk-metrics">
        <i class="sk-card sk-feature"></i>
        <i class="sk-card"></i><i class="sk-card"></i>
        <i class="sk-card"></i><i class="sk-card"></i>
        <i class="sk-card"></i><i class="sk-card"></i><i class="sk-card"></i>
      </div>
      <div class="sk-feed">
        <div class="sk-row"><i class="sk-line"></i><i class="sk-line"></i><i class="sk-line"></i></div>
        <div class="sk-row"><i class="sk-line"></i><i class="sk-line"></i><i class="sk-line"></i></div>
        <div class="sk-row"><i class="sk-line"></i><i class="sk-line"></i><i class="sk-line"></i></div>
        <div class="sk-row"><i class="sk-line"></i><i class="sk-line"></i><i class="sk-line"></i></div>
      </div>
      <div class="sk-rail"><i class="sk-feature"></i><i></i><i></i><i></i></div>
    </div>`;
}

function errorHtml(view, ctx) {
  const { esc } = ctx;
  return `<div class="pbr-error" role="alert">
    ${glyph('warning', { label: '读取失败', size: 26 })}<b>本期简报没读出来</b>
    <p>${esc(readableError(view.error))}</p>
    <div class="pbr-error-actions">
      <button type="button" class="control" data-pbr-retry>${glyph('refresh', { label: '重试', size: 18 })} 重试</button>
    </div>
  </div>`;
}

/* 标签查询容器：内容由 match-tags.js 按实时标签词表填充（新加的标签立刻可查）。 */
function tagQueryHtml() {
  return '<div class="tagquery" data-tagquery="home" data-tq-label="标签查询"></div>';
}

function dataHtml(data, view, ctx) {
  /* 战况区只保留战况卡本身。
     「下一场约训」「数据覆盖」两块在侧栏与「数据来源」页各有入口，
     放在首页只会跟主结论抢位置，按标注整块移除。 */
  return `<section class="pbr-hero">
      ${kpiHtml(data, ctx)}
    </section>
    ${metricsHtml(data, ctx)}
    ${notableHtml(data, ctx)}
    ${findingsHtml(data, view, ctx)}
    ${watchHtml(data, view, ctx)}
    `;
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
  return `<header class="pbr-head" aria-label="赛训周期简报">
      ${titleHtml(state, deps)}
      ${barHtml(state, deps)}
      ${state.notice ? `<p class="pbr-notice" role="status">${deps.esc(state.notice)}</p>` : ''}
    </header>${body}`;
}

/* ── 页面控制器：挂载点、周期状态、取数与重试 ─────────────────── */
export function createPeriodBrief({ esc, fmt, icon, API_BASE, portrait, getFilters, openRange, onEmptyLibrary, applyScope }) {
  const ctx = { esc, fmt, icon, API_BASE, portrait, art: true };
  let root = null;
  let request = null;
  let generation = 0;
  let state = { kind: DEFAULT_KIND, override: null, filterKey: null, notice: '' };
  let view = { kind: DEFAULT_KIND, data: null, loading: false, error: null, notice: '' };
  /* 复盘区状态只活在控制器里：显示字段可持久化；排序字段只影响本次渲染；弹层开关不落盘。 */
  let displayChoice = null;
  let watchActive = null;
  let tagFilter = { tags: [], keyword: '', keys: [] };
  let openPop = null;
  /* 关注收藏：纯渲染只读，localStorage 只在这里读写。 */
  let findingFavs = {};
  let watchFavs = {};
  let findingIgnored = {};
  let viewMode = 'all';
  let favsLoaded = false;
  /* J/K 快捷键的当前卡（按对局 key 记住，重画后按 key 复原）。 */
  let currentWatchKey = null;

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

  /* ── 关注收藏：{id: {at,reviewedAt,note}}，旧 ISO 字符串读入自动迁移 ── */
  function readFavMap(key) {
    try {
      if (typeof localStorage === 'undefined') return {};
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : null;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
      const map = {};
      Object.keys(parsed).forEach((id) => {
        const state = favStateOf(parsed, id);
        if (state && id) map[id] = state;
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

  function readIgnoredMap() {
    try {
      if (typeof localStorage === 'undefined') return {};
      const raw = localStorage.getItem(IGNORED_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
      const map = {};
      Object.keys(parsed).forEach((id) => {
        if (id) map[id] = plain(parsed[id]);
      });
      return map;
    } catch {
      return {};
    }
  }

  function writeIgnoredMap(map) {
    try {
      if (typeof localStorage === 'undefined') return;
      const store = localStorage;
      store.setItem(IGNORED_KEY, JSON.stringify(map));
    } catch {}
  }

  function readViewMode() {
    try {
      if (typeof localStorage === 'undefined') return 'all';
      const value = plain(localStorage.getItem(VIEW_KEY));
      return VIEW_MODES.includes(value) ? value : 'all';
    } catch {
      return 'all';
    }
  }

  function writeViewMode(mode) {
    try {
      if (typeof localStorage === 'undefined') return;
      const store = localStorage;
      store.setItem(VIEW_KEY, mode);
    } catch {}
  }

  function ensureFavs() {
    if (favsLoaded) return;
    favsLoaded = true;
    findingFavs = readFavMap(FINDING_FAV_KEY);
    watchFavs = readFavMap(WATCH_FAV_KEY);
    /* 旧 ISO 字符串读入时已迁移成 {at, reviewedAt, note}，这里写回一次，
       保证 localStorage 结构与契约一致（不会每次都产生多余变化）。 */
    writeFavMap(FINDING_FAV_KEY, findingFavs);
    writeFavMap(WATCH_FAV_KEY, watchFavs);
    findingIgnored = readIgnoredMap();
    viewMode = readViewMode();
  }

  /* 点一次：没关注就记 {at,reviewedAt:null,note:''}，已关注就删掉（回到原位置）。 */
  function toggleFavMap(map, key) {
    const next = { ...map };
    if (next[key]) delete next[key];
    else next[key] = { at: new Date().toISOString(), reviewedAt: '', note: '' };
    return next;
  }

  /* 当前渲染需要的只读状态（纯渲染层不碰 localStorage）。 */
  function viewState() {
    return {
      findingFavs,
      watchFavs,
      findingIgnored,
      viewMode,
      currentWatchKey,
    };
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
    const extra = PERIOD_REQUEST[state.kind];
    if (extra) {
      if (has(extra.n)) params.set('n', String(extra.n));
      if (has(extra.days)) params.set('days', String(extra.days));
    }
    const range = currentRange();
    if (state.kind === 'all') {
      params.set('period', 'custom');
      params.set('from', ALL_RANGE.from);
      params.set('to', ALL_RANGE.to);
    } else if (state.kind === 'custom' && range) {
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
      ...viewState(),
      hasDateScope: scope,
      displayFields,
      watchActive,
      openPop,
    }, ctx);
    root.setAttribute('aria-busy', String(Boolean(view.loading)));
    syncArrows();
    syncCurrentCard();
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
    currentWatchKey = null;
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

  /* ── 局部刷新：只重画发现区 / 复盘区，保留滚动位置与焦点 ── */
  function replaceSection(selector, html, focusSelector, collectLefts) {
    if (!root) return null;
    const section = root.querySelector(selector);
    if (!section) return null;
    const holder = document.createElement('div');
    holder.innerHTML = html;
    const next = holder.firstElementChild;
    if (!next) return null;
    section.replaceWith(next);
    if (collectLefts) {
      next.querySelectorAll('[data-pbr-watch-group]').forEach((rail) => {
        rail.scrollLeft = collectLefts.get(rail.dataset.pbrWatchGroup) || 0;
      });
    }
    if (focusSelector) {
      const node = next.querySelector(focusSelector);
      if (node) focusKeep(node);
      else focusKeep(next.querySelector('.pbr-finding-list'));
    }
    return next;
  }

  function refreshFindings(focusSelector) {
    const before = root && root.querySelector('.pbr-findings:not(.pbr-watch) .pbr-finding-list');
    const top = before ? before.scrollTop : 0;
    const next = replaceSection('.pbr-findings:not(.pbr-watch)',
      findingsHtml(view.data || {}, { ...view, ...viewState() }, ctx), focusSelector);
    const list = next && next.querySelector('.pbr-finding-list');
    if (list) list.scrollTop = top;
  }

  function refreshWatch(focusSelector) {
    const lefts = new Map();
    if (root) {
      root.querySelectorAll('.pbr-watch [data-pbr-watch-group]').forEach((rail) => {
        lefts.set(rail.dataset.pbrWatchGroup, rail.scrollLeft);
      });
    }
    const data = view.data || {};
    replaceSection('.pbr-watch',
      watchHtml(data, { ...view, ...viewState(), displayFields: resolveDisplay(data), watchActive, openPop, tagFilter }, ctx),
      focusSelector, lefts);
    syncArrows();
    syncCurrentCard();
  }

  /* 关注/取消关注（发现、复盘共用）：关注后出现「已复盘 / ＋结论」。 */
  function toggleFav(kind, button) {
    const key = kind === 'finding' ? plain(button.dataset.pbrFavFinding) : plain(button.dataset.pbrFavWatch);
    if (!key) return;
    ensureFavs();
    if (kind === 'finding') {
      findingFavs = toggleFavMap(findingFavs, key);
      writeFavMap(FINDING_FAV_KEY, findingFavs);
      refreshFindings(`[data-pbr-fav-finding="${key}"]`);
    } else {
      watchFavs = toggleFavMap(watchFavs, key);
      writeFavMap(WATCH_FAV_KEY, watchFavs);
      currentWatchKey = key;
      refreshWatch(`[data-pbr-fav-watch="${key}"]`);
    }
  }

  /* 已复盘开关：只改 reviewedAt，不动关注时间与结论。 */
  function toggleReviewed(button) {
    const kind = button.dataset.pbrFavKind === 'watch' ? 'watch' : 'finding';
    const key = plain(button.dataset.pbrFavReview);
    if (!key) return;
    ensureFavs();
    const map = kind === 'watch' ? watchFavs : findingFavs;
    const state = favStateOf(map, key);
    if (!state) return;
    const next = { ...map, [key]: { ...state, reviewedAt: state.reviewedAt ? '' : new Date().toISOString() } };
    if (kind === 'watch') {
      watchFavs = next;
      writeFavMap(WATCH_FAV_KEY, next);
      currentWatchKey = key;
      refreshWatch(`[data-pbr-fav-review="${key}"]`);
    } else {
      findingFavs = next;
      writeFavMap(FINDING_FAV_KEY, next);
      refreshFindings(`[data-pbr-fav-review="${key}"]`);
    }
  }

  /* 行内单行结论：Enter/blur 保存，Esc 取消；保存后回到按钮，弹层/滚动不跳。 */
  function openNoteEditor(button) {
    const kind = button.dataset.pbrFavKind === 'watch' ? 'watch' : 'finding';
    const key = plain(button.dataset.pbrFavNote);
    if (!key || !root) return;
    if (root.querySelector('[data-pbr-note-input]')) return;
    const slot = Array.from(root.querySelectorAll('[data-pbr-note-slot]'))
      .find((node) => node.dataset.pbrNoteSlot === key);
    if (!slot) return;
    const map = kind === 'watch' ? watchFavs : findingFavs;
    const state = favStateOf(map, key);
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'pbr-note-input';
    input.setAttribute('data-pbr-note-input', '');
    input.maxLength = 120;
    input.value = state ? state.note : '';
    input.placeholder = kind === 'watch' ? '这局怎么复盘（Enter 保存 · Esc 取消）' : '这条怎么处理（Enter 保存 · Esc 取消）';
    slot.replaceChildren(input);
    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      if (save) {
        const mapNow = kind === 'watch' ? watchFavs : findingFavs;
        const current = favStateOf(mapNow, key);
        if (current) {
          const next = { ...mapNow, [key]: { ...current, note: input.value.trim() } };
          if (kind === 'watch') {
            watchFavs = next;
            writeFavMap(WATCH_FAV_KEY, next);
          } else {
            findingFavs = next;
            writeFavMap(FINDING_FAV_KEY, next);
          }
        }
      }
      if (kind === 'watch') {
        currentWatchKey = key;
        refreshWatch(`[data-pbr-fav-note="${key}"]`);
      } else {
        refreshFindings(`[data-pbr-fav-note="${key}"]`);
      }
    };
    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      /* 中文输入法确认候选词的回车不算「保存」：此时 input.value 还是拼音，
         Safari 还会把 keyCode 报成 229，两个信号一起挡，等文字上屏再按一次回车。 */
      const imeConfirming = event.isComposing === true || event.keyCode === 229;
      if (event.key === 'Enter') {
        event.preventDefault();
        if (imeConfirming) return;
        finish(true);
      } else if (event.key === 'Escape') {
        /* 选字中途按 Esc 是取消候选，不是放弃整条结论。 */
        if (imeConfirming) return;
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener('blur', () => finish(true));
    input.focus();
    input.select();
  }

  /* 忽略一条发现（任何视角都不显示），区头出现「已忽略 N 条 · 恢复」。 */
  function ignoreFinding(button) {
    const id = plain(button.dataset.pbrIgnoreFinding);
    if (!id) return;
    ensureFavs();
    const list = root && root.querySelector('.pbr-findings:not(.pbr-watch) .pbr-finding-list');
    const top = list ? list.scrollTop : 0;
    findingIgnored = { ...findingIgnored, [id]: new Date().toISOString() };
    writeIgnoredMap(findingIgnored);
    refreshFindings(null);
    const after = root && root.querySelector('.pbr-findings:not(.pbr-watch) .pbr-finding-list');
    if (after) after.scrollTop = top;
    const next = root && root.querySelector('[data-pbr-ignore-finding]');
    focusKeep(next || (after || null));
  }

  function restoreIgnored() {
    ensureFavs();
    findingIgnored = {};
    writeIgnoredMap({});
    refreshFindings('[data-pbr-ignore-finding]');
  }

  /* 顶部三态视角：只改渲染、不重新取数。 */
  function chooseView(mode) {
    if (!VIEW_MODES.includes(mode) || mode === viewMode) return;
    viewMode = mode;
    writeViewMode(mode);
    repaint(null);
    focusKeep(root && root.querySelector(`[data-pbr-view-mode="${mode}"]`));
  }

  /* 导出清单：Markdown 下载 + 尽力写剪贴板（失败不影响下载）。 */
  function listDateText(date) {
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function buildExportMarkdown(data) {
    const lines = [`# 赛训复盘清单 · ${listDateText(new Date())}`, ''];
    const findings = collectFindings(data).filter((finding) => favStateOf(findingFavs, findingKey(finding)));
    lines.push('## 重点发现');
    if (!findings.length) lines.push('', '_没有关注的发现_');
    findings.forEach((finding, index) => {
      const key = findingKey(finding);
      const state = favStateOf(findingFavs, key);
      lines.push('', `### ${index + 1}. ${plain(finding.title)}`);
      if (plain(finding.conclusion)) lines.push(`- 结论：${plain(finding.conclusion)}`);
      if (state.note) lines.push(`- 我的结论：${state.note}`);
      if (state.at) lines.push(`- 关注时间：${favTimeText(state.at)}`);
      if (state.reviewedAt) lines.push(`- 已复盘：${favTimeText(state.reviewedAt)}`);
      const game = plain((listOf(finding.evidence)[0] || {}).game);
      if (game) lines.push(`- 对局链接：#match/${game}`);
    });
    const fields = listOf(data.watchFields).filter((field) => field && plain(field.id));
    const cards = fields.length ? fields.flatMap((field) => watchItems(field)) : listOf(data.watch);
    const seen = new Set();
    const watched = [];
    cards.forEach((card) => {
      const key = watchCardKey(card);
      if (!key || seen.has(key) || !favStateOf(watchFavs, key)) return;
      seen.add(key);
      watched.push({ card, key });
    });
    lines.push('', '## 复盘比赛');
    if (!watched.length) lines.push('', '_没有关注的对局_');
    watched.forEach(({ card, key }, index) => {
      const state = favStateOf(watchFavs, key);
      lines.push('', `### ${index + 1}. ${plain(card.title)}`);
      if (plain(card.conclusion)) lines.push(`- 结论：${plain(card.conclusion)}`);
      if (state.note) lines.push(`- 我的结论：${state.note}`);
      if (state.at) lines.push(`- 关注时间：${favTimeText(state.at)}`);
      if (state.reviewedAt) lines.push(`- 已复盘：${favTimeText(state.reviewedAt)}`);
      lines.push(`- 对局链接：#match/${key}`);
    });
    return `${lines.join('\n')}\n`;
  }

  function exportList() {
    const data = view.data || {};
    if (!hasFavContent(data, { ...view, ...viewState() })) return;
    if (typeof document === 'undefined') return;
    const markdown = buildExportMarkdown(data);
    const name = `赛训复盘清单-${listDateText(new Date())}.md`;
    try {
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = name;
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => { try { URL.revokeObjectURL(url); } catch {} }, 1200);
    } catch {}
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(markdown).catch(() => {});
      }
    } catch {}
  }

  /* ── J/K/F/Enter 快捷键：只在非输入、无弹层/对话框时生效 ── */
  const isTypingTarget = (target) => Boolean(target && target.closest
    && target.closest('input, textarea, select, [contenteditable="true"]'));

  function visibleWatchCards() {
    const rail = watchRail();
    return rail ? Array.from(rail.querySelectorAll('.pbr-finding.is-watch')) : [];
  }

  function isCurrentCardMarked() {
    return Boolean(root && root.querySelector('.pbr-watch .pbr-finding.is-watch.is-current'));
  }

  function currentCard() {
    const cards = visibleWatchCards();
    if (!cards.length) return null;
    if (currentWatchKey) {
      const hit = cards.find((card) => card.dataset.watchKey === currentWatchKey);
      if (hit) return hit;
    }
    return cards[0];
  }

  function markCurrentCard(card) {
    if (!root) return;
    root.querySelectorAll('.pbr-watch .pbr-finding.is-current').forEach((node) => node.classList.remove('is-current'));
    if (card) card.classList.add('is-current');
  }

  function syncCurrentCard() {
    if (!currentWatchKey || !root) return;
    const hit = Array.from(root.querySelectorAll('.pbr-watch .pbr-finding.is-watch'))
      .find((card) => card.dataset.watchKey === currentWatchKey);
    markCurrentCard(hit || null);
  }

  function moveWatchCard(direction) {
    const cards = visibleWatchCards();
    if (!cards.length) return;
    const current = currentCard();
    const index = current ? cards.indexOf(current) : -1;
    const nextIndex = index < 0
      ? (direction > 0 ? 0 : cards.length - 1)
      : (index + direction + cards.length) % cards.length;
    const card = cards[nextIndex];
    currentWatchKey = plain(card.dataset.watchKey);
    markCurrentCard(card);
    try { card.scrollIntoView({ block: 'nearest', inline: 'center' }); } catch { card.scrollIntoView(); }
    focusKeep(card);
    syncArrows();
  }

  function toggleCurrentFav() {
    const card = currentCard();
    if (!card) return;
    const button = card.querySelector('[data-pbr-fav-watch]');
    if (button) toggleFav('watch', button);
  }

  function openCurrentMatch() {
    const card = currentCard();
    if (!card) return;
    const link = card.querySelector('.pbr-watch-link a[href]');
    const href = link && link.getAttribute('href');
    if (href) window.location.hash = href;
  }

  function onFieldChange(event) {
    const input = event.target.closest('[data-pbr-field-option]');
    if (!input) return;
    chooseField(input);
  }

  /* 弹层 Esc 关闭并回焦点；非输入状态下 J/K/F/Enter 控制复盘卡。 */
  function onDocumentKeyDown(event) {
    if (event.key === 'Escape' && openPop) {
      const kind = openPop;
      openPop = null;
      syncPops();
      focusTool(kind);
      return;
    }
    if (openPop) return;
    if (isTypingTarget(event.target)) return;
    if (typeof document !== 'undefined' && document.querySelector('dialog[open]')) return;
    if (!listOf(view.data && view.data.watchFields).length) return;
    const key = event.key;
    if (key === 'j' || key === 'J') {
      event.preventDefault();
      moveWatchCard(1);
      return;
    }
    if (key === 'k' || key === 'K') {
      event.preventDefault();
      moveWatchCard(-1);
      return;
    }
    if (key === 'f' || key === 'F') {
      event.preventDefault();
      toggleCurrentFav();
      return;
    }
    if (key === 'Enter') {
      /* 焦点在按钮/链接等可交互元素上时，Enter 属于它们自己的默认行为
         （周期按钮、数据范围、导出、关注…），不能被全局快捷键劫持。 */
      const target = event.target;
      if (target && typeof target.closest === 'function'
          && target.closest('button, a, [role="button"], [href], summary, label, input, select, textarea')) {
        return;
      }
      if (!isCurrentCardMarked()) return;
      event.preventDefault();
      openCurrentMatch();
    }
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
    if (event.target.closest('[data-pbr-import-help]')) { onEmptyLibrary?.(); return; }
    const target = event.target;
    const favFinding = target.closest('[data-pbr-fav-finding]');
    if (favFinding) {
      toggleFav('finding', favFinding);
      return;
    }
    const favWatch = target.closest('[data-pbr-fav-watch]');
    if (favWatch) {
      toggleFav('watch', favWatch);
      return;
    }
    const review = target.closest('[data-pbr-fav-review]');
    if (review) {
      toggleReviewed(review);
      return;
    }
    const note = target.closest('[data-pbr-fav-note]');
    if (note) {
      openNoteEditor(note);
      return;
    }
    const ignore = target.closest('[data-pbr-ignore-finding]');
    if (ignore) {
      ignoreFinding(ignore);
      return;
    }
    if (target.closest('[data-pbr-restore-ignored]')) {
      restoreIgnored();
      return;
    }
    if (target.closest('[data-pbr-export]')) {
      exportList();
      return;
    }
    const viewButton = target.closest('[data-pbr-view-mode]');
    if (viewButton) {
      chooseView(viewButton.dataset.pbrViewMode);
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
      const menu = sortOption.closest('.pbr-watch-menu');
      if (menu) menu.open = false;
      return;
    }
    /* 点英雄头像只高亮这位英雄在本场的表现，不跳走；复盘仍走卡片入口。 */
    const hero = target.closest('.pbr-roster-hero');
    if (hero) {
      const card = hero.closest('.pbr-review-card');
      const strip = card && card.querySelector('[data-pbr-hero-focus]');
      if (!card || !strip) return;
      const name = plain(hero.dataset.heroName);
      const already = hero.classList.contains('is-picked');
      card.querySelectorAll('.pbr-roster-hero').forEach((node) => node.classList.remove('is-picked'));
      if (already) {
        strip.hidden = true;
        strip.textContent = '';
        return;
      }
      hero.classList.add('is-picked');
      strip.hidden = false;
      const kda = plain(hero.dataset.heroKda);
      const gold = plain(hero.dataset.heroGold);
      strip.innerHTML = `<span class="pbr-hero-focus-name">${esc(plain(hero.dataset.heroTip))}</span>`
        + (kda && !kda.includes('—') ? `<span class="pbr-hero-focus-stat">KDA ${esc(kda)}</span>` : '')
        + (gold && gold !== '—' ? `<span class="pbr-hero-focus-stat">${esc(gold)}</span>` : '');
      return;
    }
    if (target.closest('[data-pbr-all-metrics]')) {
      const details = root && root.querySelector('.pbr-more-metrics');
      if (details) {
        details.open = true;
        details.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
      return;
    }
    if (target.closest('[data-pbr-display-reset]')) {
      resetDisplay();
      return;
    }
    /* 点卡片本体：把它记为当前卡（不做别的动作，避免误触）。 */
    const watchCard = target.closest('.pbr-watch .pbr-finding.is-watch');
    if (watchCard && !target.closest('a, button, input')) {
      currentWatchKey = plain(watchCard.dataset.watchKey);
      markCurrentCard(watchCard);
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

  function onTagFilter(event) {
    const detail = event.detail || {};
    if (detail.scope !== 'home') return;
    const next = {
      tags: listOf(detail.tags).map(plain).filter(Boolean),
      keyword: plain(detail.keyword),
      keys: listOf(detail.keys).map(plain).filter(Boolean),
    };
    if (JSON.stringify(next) === JSON.stringify(tagFilter)) return;
    tagFilter = next;
    refreshWatch();
  }

  let docBound = false;
  function bindDocument() {
    if (docBound || typeof document === 'undefined') return;
    docBound = true;
    document.addEventListener('keydown', onDocumentKeyDown);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);
    document.addEventListener('match-tags:filter', onTagFilter);
  }
  function unbindDocument() {
    if (!docBound || typeof document === 'undefined') return;
    docBound = false;
    document.removeEventListener('keydown', onDocumentKeyDown);
    document.removeEventListener('pointerdown', onDocumentPointerDown, true);
    document.removeEventListener('match-tags:filter', onTagFilter);
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
