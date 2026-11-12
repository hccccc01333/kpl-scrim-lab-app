/* 采集页 —— 采集链路在 V3 界面里的实现。
 *
 * V3 是单应用：采集接口与分析接口同属 server.py 一个进程。
 * 演示实例也是同一份 server.py，只把 KPL_DATA_DIR 指向隔离的演示库，
 * 所以采集链路同样可用；数据暂时读不到时页面内自动重试。
 *
 * 数据与写操作都走工作台根接口：
 *   GET  /api/channels            缺失值审查记录
 *   GET  /api/camp/sync           授权状态 + 已同步对局
 *   GET  /api/camp/config         营地选手白名单
 *   POST /api/camp/auth/qr        生成授权二维码 -> {taskId, qrcodeBase64}
 *   GET  /api/camp/auth/poll      轮询 -> {status: waiting|scanned|success|error|expired|canceled}
 *   POST /api/camp/auth/cancel    取消本次会话
 *   POST /api/camp/auth/clear     删除登录凭证
 *   POST /api/camp/resolve        分享链接 -> {userId, nickname}
 *   POST /api/camp/list           拉某位选手的最近对局 -> {entries[], gaming?}
 *   POST /api/camp/sync           同步所选对局（按 campUserId 分组；无缺失自动进正式统计）
 *   POST /api/camp/config         保存白名单 {players:[{campUserId, nickname}]}
 *
 * 单个接口暂时读不到时按空数据处理，页面给重试入口，不中断整页。
 */

const ROOT_API = '/api/';

/* 采集来源档位 —— 与 web/capture-guide/requirements.json、
   web/collection-guide.js 里的既有措辞保持一致，不要另造词。 */
const SOURCE_TIERS = [
  ['官方回放链接', { label: '营地路径必采', key: 'must' }, '营地通道必须有；截图/录屏新录入通道不要求', ''],
  ['营地数据自动采集', { label: '推荐主路径', key: 'primary' }, '教练号授权后每天增量拉取，BP 与十人面板都能覆盖；营地只保留约一个月', '#ingest'],
  ['七张赛后截图', { label: '补采 / 新录入', key: 'fallback' }, '已有对局缺素材时补采；超过一个月的老局直接新录入一局', '#shots'],
  ['完整录屏', { label: '补采 / 新录入', key: 'fallback' }, '同上；十人阵容清楚即可新录入', '#videos'],
  ['标准表格', { label: '选填 · 补充', key: 'extra' }, '手填补充或校正字段，需要按模板列结构', '#capture'],
];

async function api(path, { method = 'GET', body, raw, signal } = {}) {
  const options = { method, cache: 'no-store', signal };
  if (raw !== undefined) {
    options.body = raw;                 // 上传原始文件（截图），不包 JSON
  } else if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(ROOT_API + path, options);
  if (!response.ok) {
    let body;
    try { body = await response.json(); } catch { /* 非 JSON */ }
    const detail = body?.detail;
    // 接口暂时读不到：整页保留采集框架，不把英文 "Not Found" 或运维话术摆给教练。
    if (response.status === 404) {
      const missing = new Error('采集数据暂时读不到。');
      missing.unavailable = true;
      throw missing;
    }
    const message = typeof detail === 'string' && detail !== 'Not Found'
      ? detail
      : '采集数据暂时读不到，请稍后重试。';
    const error = new Error(message);
    if (body && typeof body === 'object') {
      error.authInvalid = Boolean(body.authInvalid);
      error.reason = typeof body.reason === 'string' ? body.reason : '';
      error.code = body.code || '';
    }
    throw error;
  }
  return response.json();
}

function stamp(iso) {
  const value = String(iso || '');
  return value.length >= 16 ? `${value.slice(5, 10)} ${value.slice(11, 16)}` : '';
}

/** 本地日期 YYYY-MM-DD，供新录入表单默认值。 */
function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/* 营地列表的 dtEventTime 是 epoch「秒」且是对局记录发送时间，不是开赛时间：
   以前直接 new Date(Number(...)) 当毫秒用，全部显示成 1970-01-21。
   真实开赛时间优先用后端按 camp_time 口径算好的 startedAt（北京时间 ISO），
   其次用营地自带的 gametime（"MM-DD HH:MM"），最后才按秒补算。 */
function matchTime(entry) {
  const started = String(entry?.startedAt || '');
  if (started.length >= 16) return { day: started.slice(5, 10), clock: started.slice(11, 16), full: `${started.slice(0, 10)} ${started.slice(11, 16)}` };
  const gametime = String(entry?.gametime || '').trim();
  if (gametime) {
    const parts = gametime.split(/\s+/);
    return { day: parts[0] || '', clock: parts[1] || '', full: gametime };
  }
  const sec = Number(entry?.dtEventTime || 0);
  const used = Number(entry?.usedTime || 0);
  if (sec > 0) {
    // 转成 Date 后按 UTC+8 取字段，避免浏览器本地时区把北京时间又偏一次。
    const d = new Date((sec - used) * 1000 + 8 * 3600 * 1000);
    const p = (n) => String(n).padStart(2, '0');
    return { day: `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
      clock: `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`,
      full: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}` };
  }
  return { day: '--', clock: '', full: '' };
}

function matchMinutes(sec) {
  const value = Number(sec || 0);
  if (!value) return '';
  return `${Math.floor(value / 60)}分${String(Math.round(value % 60)).padStart(2, '0')}秒`;
}

/* 营地只提供最近一个月的战局详情：更早的局拉详情会直接返回
   -30457「暂不支持查看一个月前的战绩详情」。与 tools/camp_sync.DETAIL_TTL_DAYS
   同一口径；后端 /api/camp/list 也会带 campDetailAvailable，优先用它。 */
const CAMP_DETAIL_TTL_DAYS = 31;

function campDetailExpired(entry) {
  if (entry?.campDetailAvailable === false) return true;
  if (entry?.campDetailAvailable === true) return false;
  const started = String(entry?.startedAt || '');
  const fromText = started.length >= 10 ? Date.parse(started) : NaN;
  const moment = Number.isFinite(fromText) ? fromText : Number(entry?.dtEventTime || 0) * 1000;
  if (!moment) return false;
  return Date.now() - moment > CAMP_DETAIL_TTL_DAYS * 86400000;
}

/** 胜负口径：gameresult 1=胜 2=负（被查选手视角）。 */
function resultChip(entry) {
  const result = Number(entry?.gameresult || 0);
  if (result !== 1 && result !== 2) return '';
  return `<i class="ingest-won ${result === 1 ? 'is-win' : 'is-loss'}">${result === 1 ? '胜' : '负'}</i>`;
}

export function createCapture(h) {
  const { esc, fmt, table, block, stats, empty, withPage, icon } = h;
  const text = (value) => esc(value === null || value === undefined || value === '' ? '—' : value);

  const state = {
    value: null,
    qr: null,
    poll: null,
    list: null,
    checked: {},
    busy: '',
    notice: '',
    listNote: '',
    authIssue: '',
    authCheckedAt: 0,
    authProbe: null,
    query: '',
    fromDate: '',
    toDate: '',
    scope: 'all',
    range: 'all',
    // 拉取/入库进度：phase、已处理数、总数、当前对局、已拿到的局数。
    progress: null,
    // 上一次同步的结果，留在卡片里直到下次拉取：写入 / 待审 / 没拉全。
    summary: null,
    // 同步结束时右下角那张结果卡；切到别的页面也还在，直到关闭或超时。
    widgetResult: null,
    widgetTimer: null,
    // 营地连接默认收起（授权正常且有选手时），点「展开管理」才铺开。
    connOpen: false,
    // 「新录入一局」表单：营地拿不到的老对局走截图 / 录屏，直接新建一局并录入（不是补采）。
    backfillOpen: false,
    pullCursor: null,
    pullHasMore: false,
    pullPages: 0,
  };

  function stopPoll() {
    if (state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
  }

  /* 全局进度/结果卡挂在 body 上，不随 #content 换页被销毁：同步在后台跑，
     切到对局档案或选手页也能在右下角看到进度和结果。 */
  let widgetHost = null;

  function ensureWidgetHost() {
    if (widgetHost && document.body.contains(widgetHost)) return widgetHost;
    widgetHost = document.createElement('div');
    widgetHost.id = 'cap-sync-widget';
    widgetHost.setAttribute('role', 'status');
    widgetHost.setAttribute('aria-live', 'polite');
    widgetHost.addEventListener('click', (event) => {
      if (event.target.closest('[data-cap-widget-close]')) {
        state.widgetResult = null;
        if (state.widgetTimer) { clearTimeout(state.widgetTimer); state.widgetTimer = null; }
        renderWidget();
      }
    });
    document.body.appendChild(widgetHost);
    return widgetHost;
  }

  function widgetHtml() {
    if (state.progress) {
      return `<div class="cap-progress-float is-live">
        ${progressInner(state.progress)}
        <p class="cap-widget-foot"><a href="#ingest">回到营地同步</a><span>切页面也会继续</span></p>
      </div>`;
    }
    const result = state.widgetResult;
    if (!result) return '';
    const parts = [`${fmt(result.saved)} 局进入正式统计`];
    if (result.review) parts.push(`${fmt(result.review)} 局待缺失值审查`);
    if (result.unsupported) parts.push(`${fmt(result.unsupported)} 局营地无详情`);
    if (result.failed) parts.push(`${fmt(result.failed)} 局没拉全`);
    return `<div class="cap-progress-float is-done${result.failed ? ' is-error' : ''}">
      <div class="cap-progress-head"><b>同步结束 · 共 ${fmt(result.total)} 局</b>
        <button type="button" class="cap-widget-x" data-cap-widget-close aria-label="关闭同步提示">×</button></div>
      <div class="cap-widget-text">${esc(parts.join(' · '))}</div>
      ${result.note ? `<small>${esc(result.note)}</small>` : ''}
      <p class="cap-widget-foot"><a href="#ingest">查看营地同步</a></p>
    </div>`;
  }

  function renderWidget() {
    const host = ensureWidgetHost();
    const html = widgetHtml();
    host.innerHTML = html;
    host.hidden = !html;
  }

  function paint(keepScroll = false) {
    const root = document.querySelector('#content');
    // 同步在后台跑的时候用户可能已经切走：这时只更新右下角，别把别的页面重绘成采集页。
    if (!location.hash.startsWith('#ingest')) { renderWidget(); return; }
    if (root && state.value) {
      // 勾选一局就把整页换掉会让列表跳回原处，逐个取消勾选时要保持当前位置。
      const anchor = keepScroll ? window.scrollY : null;
      root.innerHTML = view(state.value);
      bindFilter();
      if (anchor !== null) window.scrollTo(0, anchor);
    }
    renderWidget();
  }

  /** 统一的进度条：教练能看见「第几步、处理到第几局、还剩多少」。 */
  function progressInner(p) {
    const total = Math.max(1, Number(p.total) || 1);
    const done = Math.min(total, Math.max(0, Number(p.done) || 0));
    const percent = Math.round((done / total) * 100);
    const phase = p.phase === 'channel' ? '正在写入正式统计'
      : p.phase === 'done' ? '正在收尾'
        : p.phase === 'list' ? '正在读取对局列表' : '正在同步对局详情';
    const detail = p.current ? ` · 对局 ${p.current}` : '';
    const count = p.phase === 'list'
      ? `已翻 ${done} / ${total} 页${p.matches ? ` · 已拿到 ${p.matches} 局` : ''}`
      : `${done} / ${total} 局${detail}`;
    return `<div class="cap-progress-head"><b>${esc(p.label || phase)}</b>
        <span>${esc(count)}</span></div>
      <div class="cap-progress-track"><i style="width:${percent}%"></i></div>
      ${p.note ? `<small>${esc(p.note)}</small>` : ''}`;
  }

  function progressBar() {
    if (!state.progress) return '';
    return `<div class="cap-progress" role="status" aria-live="polite">${progressInner(state.progress)}</div>`;
  }

  /* 卡片里的进度条会随页面滚动跑出视口；同步一跑十几分钟，教练得能一直看见。 */
  /** 只刷新进度条节点，避免每翻一页都整页重绘导致勾选框失焦、滚动跳动。 */
  function paintProgress() {
    document.querySelectorAll('[data-cap-progress]').forEach((host) => {
      host.innerHTML = progressBar();
    });
    renderWidget();
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  async function reloadValue() {
    state.value = await load('ingest', '', undefined);
  }

  // ---------------- 数据 ----------------

  let unavailableRetries = 0;
  async function load(_name, _key, signal) {
    try {
      const [initialChannels, sync, config, catalog, matchesView, shots, recordings] = await Promise.all([
        api('channels', { signal }),
        api('camp/sync', { signal }),
        api('camp/config', { signal }).catch(() => ({ players: [] })),
        // 英雄图标与阵容：拿不到时只是不显示头像，不影响主流程
        api('catalog', { signal }).catch(() => ({ entries: [] })),
        api('studio/view/matches', { signal }).catch(() => ({ matches: [] })),
        // 两个 OCR 窗口：读不到时显示 0，不影响营地主流程
        api('postgame/images', { signal }).catch(() => ({ images: [], groups: [] })),
        api('recordings', { signal }).catch(() => ({ recordings: [], jobs: [] })),
      ]);
      // camp/sync 会补齐历史详情并自动通过完整对局；如果这次确实写了，
      // channels 可能比它先返回，再读一次保证首屏就是最新状态。
      const backfilled = Number(sync?.backfill?.created || 0);
      const backfillSaved = Number(sync?.backfill?.saved || 0);
      const finalized = Number(sync?.finalize?.passed || 0);
      let channels = initialChannels;
      if (backfilled > 0 || finalized > 0) {
        channels = await api('channels', { signal });
      }
      // 保存一份，供写操作后局部重绘（paint）使用
      state.value = { channels, sync, config, catalog, matchesView, shots, recordings };
      unavailableRetries = 0;
      const auth = sync?.auth || {};
      state.authIssue = auth.authorized && auth.expired ? (auth.reason || '营地登录态已失效。') : '';
      const autoPassedCount = finalized + backfillSaved;
      if ((backfilled > 0 || finalized > 0) && !state.notice) {
        setNotice(autoPassedCount > 0
          ? `已自动通过 ${autoPassedCount} 局无缺失值的营地对局，直接进入正式统计。`
          : `已从本机缓存的营地详情补建 ${backfilled} 条缺失值审查记录。`);
      }
      return state.value;
    } catch (error) {
      if (!error?.unavailable) throw error;
      /* 静态资源与路由表可能短暂错配：先静默重试，别急着把整页换成错误卡。 */
      if (signal?.aborted || unavailableRetries >= 2) {
        unavailableRetries = 0;
        state.value = null;
        return { unavailable: true };
      }
      unavailableRetries += 1;
      await new Promise((resolve) => setTimeout(resolve, 350 * unavailableRetries));
      if (signal?.aborted) { unavailableRetries = 0; return { unavailable: true }; }
      return load(_name, _key, signal);
    }
  }

  /** 由当前数据构建两个索引：英雄名→图标、对局 key→本队阵容。 */
  function lookups() {
    const iconByName = new Map(
      (state.value?.catalog?.entries || [])
        .filter((entry) => entry.kind === 'hero' && entry.icon)
        .map((entry) => [entry.name, entry.icon]),
    );
    const heroesByKey = new Map(
      (state.value?.matchesView?.matches || []).map((match) => [match.key, match.heroes || []]),
    );
    return { iconByName, heroesByKey };
  }

  // ---------------- 渲染小件 ----------------

  function channelState(channel) {
    if (channel.saved?.status === 'saved') return ['saved', '已进正式统计'];
    if (channel.review?.status === 'reviewed') return ['reviewed', '待保存'];
    const missing = (channel.missing || []).length;
    return ['draft', missing ? `缺 ${missing} 项` : '待通过'];
  }

  function when(detail) {
    return detail.gametime || stamp(detail.startedAt) || stamp(detail.eventAt) || '时间未知';
  }

  function kdaText(detail) {
    const values = Array.isArray(detail.kda) ? detail.kda : null;
    if (!values || values.every((v) => v === null || v === undefined)) return '—';
    return values.map((v) => (v === null || v === undefined ? '—' : v)).join(' / ');
  }

  function duration(sec) {
    const value = Number(sec || 0);
    if (!value) return '';
    return `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')}`;
  }

  /** 比分统一成「我方 : 对方」，不受蓝红方影响；我方加粗。 */
  function scoreCell(match) {
    const scores = match.scores;
    if (!scores) return '<span class="chan-score is-empty">—</span>';
    const own = match.ownSide === 'left' ? scores.left : match.ownSide === 'right' ? scores.right : null;
    const enemy = match.ownSide === 'left' ? scores.right : match.ownSide === 'right' ? scores.left : null;
    if (own === null || enemy === null) {
      return `<span class="chan-score"><b>${esc(scores.left ?? '—')}</b><i>:</i><span>${esc(scores.right ?? '—')}</span></span>`;
    }
    const won = match.winner === match.ownSide;
    return `<span class="chan-score ${match.winner ? (won ? 'is-win' : 'is-loss') : ''}"><b>${esc(own)}</b><i>:</i><span>${esc(enemy)}</span></span>`;
  }

  const SOURCE_KEYS = [
    ['official', '官方回放'], ['camp', '营地'], ['table', '表格'],
    ['video', '录屏'], ['screenshot', '截图'], ['replay', '回放'],
  ];

  function sourceCell(channel) {
    const counts = channel.sourceStatus?.counts || {};
    const present = SOURCE_KEYS.filter(([key]) => Number(counts[key] || 0) > 0);
    const missing = SOURCE_KEYS.filter(([key]) => !Number(counts[key] || 0));
    const detail = present.map(([key, label]) => `${label} ${counts[key]}`).join(' · ');
    const title = `${present.length}/${SOURCE_KEYS.length} 类来源${detail ? `\n${detail}` : ''}`
      + (missing.length ? `\n缺：${missing.map(([, label]) => label).join('、')}` : '');
    const dots = SOURCE_KEYS.map(([key, label]) => `<i class="src-dot ${Number(counts[key] || 0) > 0 ? 'is-on' : ''}" title="${esc(label)}"></i>`).join('');
    return `<span class="chan-src" title="${esc(title)}"><b>${present.length}/${SOURCE_KEYS.length}</b><span class="src-dots">${dots}</span></span>`;
  }

  function heroesCell(channel, ctx, match) {
    let heroes = ctx.heroesByKey.get(channel.saved?.bundleKey) || [];
    // 刚入库、还没保存成正式对局的通道，直接显示这局本人用的英雄。
    if (!heroes.length && match?.heroName) heroes = [match.heroName];
    if (!heroes.length) return '<span class="chan-heroes is-empty">—</span>';
    return `<span class="chan-heroes">${heroes.slice(0, 5).map((name) => {
      const icon = ctx.iconByName.get(name) || (match?.heroIcon || '');
      return icon
        ? `<img src="${esc(icon)}" alt="${esc(name)}" title="${esc(name)}">`
        : `<i title="${esc(name)}">${esc(name.slice(0, 1))}</i>`;
    }).join('')}</span>`;
  }

  /** 与后端 analysis_data._is_seed_match 同一口径。 */
  function isSeedChannel(channel) {
    const match = channel.match || {};
    const session = String(match.session || '');
    const opponent = String(match.opponent || '');
    const reviewer = String(channel.review?.reviewedBy || '');
    return session.includes('验证数据') || opponent.includes('排位验证') || reviewer === '验证脚本';
  }

  function channelRow(channel, ctx) {
    const [status, label] = channelState(channel);
    const seed = isSeedChannel(channel);
    const match = channel.match || {};
    const mode = match.mode && match.mode !== '模式未知' ? match.mode : '';
    // 营地入库的通道没有「对手」（由教练在校对页录入），标题直接用这局
    // 真实的时间与模式，不摆「对手未标注 / 没有更多字段」这类占位。
    const clock = match.gametime || stamp(match.startedAt) || '';
    const title = match.opponent ? `对阵 ${match.opponent}`
      : [clock, mode].filter(Boolean).join(' · ') || (match.gameSeq ? `对局 ${match.gameSeq}` : '营地对局');
    const result = Number(match.gameresult || 0);
    const resultText = result === 1 ? '胜' : result === 2 ? '负' : '';
    const kda = Array.isArray(match.kda) ? match.kda.filter((v) => v !== null && v !== undefined).join('/') : '';
    // 标题已经给出时间、模式和胜负；这里先把「这把是谁、打了什么、打了多久」
    // 放在前面，别让重复字段把对局号与选手名挤出可视区。有对手时标题换成
    // 「对阵 X」，时间和模式要补回 meta，避免这类通道反而看不到时间。
    const meta = [
      ...(match.opponent ? [clock, mode] : []),
      [match.heroName, kda].filter(Boolean).join(' '),
      duration(match.durationSec),
      match.gradeGame ? `评分 ${match.gradeGame}` : '',
      match.roleJobName || '',
      match.gameSeq ? `对局 ${match.gameSeq}` : '',
      match.ownerName || ''].filter(Boolean).join(' · ');

    const version = String(match.version || '').split(/[\s/]/)[0];
    const missing = channel.missing || [];
    const missingText = missing.map((item) => `${item.label}缺${item.missing}/10`).join(' · ');
    const chipClass = status === 'saved' ? 'is-done'
      : missing.length ? 'is-warn' : status === 'reviewed' ? 'is-ok' : 'is-pending';
    return `<div class="chan-row" data-chan-open="${esc(channel.id)}" title="点击进入缺失值审查">
      ${scoreCell(match)}
      <span class="chan-main">
        <b>${resultText ? `<i class="ingest-won ${result === 1 ? 'is-win' : 'is-loss'}">${resultText}</i>` : ''}${esc(title)}</b>
        <small title="${esc(meta)}">${esc(meta || '—')}</small>
        ${missing.length ? `<small class="chan-missing" title="${esc(missingText)}">缺：${esc(missingText)} · 点此逐条审查</small>` : ''}
      </span>
      ${heroesCell(channel, ctx, match)}
      ${sourceCell(channel)}
      <span class="chan-session" title="${esc(match.session || '')}">${esc(match.session || '—')}</span>
      <span class="chan-version" title="${esc(match.version || '')}">${esc(version || '—')}</span>
      <span class="chan-updated">${esc(stamp(channel.updatedAt) || '—')}</span>
      <span class="chan-state">
        ${seed ? '<i class="chip is-seed" title="种子脚本写入的测试数据，不参与正式统计">验证</i>' : ''}
        <i class="chip ${chipClass}">${esc(label)}</i>
      </span>
      <span class="chan-spacer"></span>
      <button class="chan-exp" data-chan-expand="${esc(channel.id)}" aria-expanded="false" aria-label="展开十人草稿">⌄</button>
    </div>
    <div class="chan-draft" data-draft-for="${esc(channel.id)}" hidden></div>`;
  }

  /** 通道筛选：对手 / 训练组 / 模式 / 日期文本 + 日期区间。 */
  /** 日期区间：预设按「今天」回溯，选自定义时用输入值。 */
  function rangeBounds() {
    if (state.range === 'custom') return [state.fromDate, state.toDate];
    if (state.range === 'all') return ['', ''];
    const days = state.range === '7' ? 7 : 30;
    const start = new Date();
    start.setDate(start.getDate() - days);
    return [start.toISOString().slice(0, 10), ''];
  }

  function filterChannels(channels) {
    const q = (state.query || '').trim().toLowerCase();
    const [from, to] = rangeBounds();
    return channels.filter((channel) => {
      const seed = isSeedChannel(channel);
      if (state.scope === 'real' && seed) return false;
      if (state.scope === 'seed' && !seed) return false;
      const match = channel.match || {};
      const date = String(match.date || '');
      if (from && date && date < from) return false;
      if (to && date && date > to) return false;
      if (!q) return true;
      return [match.opponent, match.session, match.mode, match.date,
        match.gametime, match.startedAt, match.gameSeq, match.heroName,
        match.ownerName, match.roleJobName]
        .filter(Boolean).join(' ').toLowerCase().includes(q);
    });
  }

  function countingLine(total, missing, visible, filtering, autoPassed) {
    const base = `共 ${total} 条待处理${missing ? `，其中 ${missing} 条有缺失值` : '，全部无缺失值'}`;
    const auto = autoPassed ? `；${autoPassed} 条已自动进入正式统计` : '';
    return `${base}${auto}${filtering ? `；筛选后 ${visible} 条` : ''}。点任意一条进入逐项审查。`;
  }

  /** 只重绘通道列表，避免每次输入都整体重绘导致输入框失焦。 */
  function repaintChannels() {
    if (!state.value) return;
    const list = state.value.channels?.channels || [];
    const pending = list.filter((channel) => channel.saved?.status !== 'saved');
    const camp = pending.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) > 0);
    const ocr = pending.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) === 0);
    const filtering = Boolean(state.query || state.scope !== 'all' || state.range !== 'all'
      || (state.range === 'custom' && (state.fromDate || state.toDate)));
    const campHost = document.querySelector('[data-ingest-list="camp"]');
    if (campHost) {
      campHost.innerHTML = renderChannelList(filterChannels(camp), lookups(), filtering,
        '营地同步的局都已自动进入正式统计，没有需要人工审核的记录。');
    }
    const ocrHost = document.querySelector('[data-ingest-list="ocr"]');
    if (ocrHost) {
      ocrHost.innerHTML = renderChannelList(filterChannels(ocr), lookups(), filtering,
        '还没有截图 / 录屏新录入的局。营地一个月窗口外的老局在这里新录入。');
    }
    const clear = document.querySelector('[data-capture-action="clear-filter"]');
    if (clear) clear.hidden = !(state.query || state.fromDate || state.toDate
      || state.scope !== 'all' || state.range !== 'all');
  }

  function bindFilter() {
    const input = document.querySelector('[data-ingest-query]');
    if (input && !input.dataset.bound) {
      input.dataset.bound = '1';
      input.addEventListener('input', () => {
        state.query = input.value;
        repaintChannels();
        const again = document.querySelector('[data-ingest-query]');
        if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
      });
    }
    document.querySelectorAll('[data-ingest-scope]').forEach((button) => {
      if (button.dataset.bound) return;
      button.dataset.bound = '1';
      button.addEventListener('click', () => { state.scope = button.dataset.ingestScope; paint(); });
    });
    document.querySelectorAll('[data-ingest-range]').forEach((button) => {
      if (button.dataset.bound) return;
      button.dataset.bound = '1';
      button.addEventListener('click', () => { state.range = button.dataset.ingestRange; paint(); });
    });
    for (const [selector, key] of [['[data-ingest-from]', 'fromDate'], ['[data-ingest-to]', 'toDate']]) {
      const el = document.querySelector(selector);
      if (el && !el.dataset.bound) {
        el.dataset.bound = '1';
        el.addEventListener('change', () => { state[key] = el.value; paint(); });
      }
    }
  }

  /** 十人草稿摘要：昵称 + 英雄图标 + 评分，两侧各五人。 */
  function draftSummary(channel, ctx) {
    const players = (channel.draft || {}).players || [];
    if (!players.length) {
      return '<p class="capture-hint">这局还没有生成草稿数据，先挂素材或拉取营地面板。</p>';
    }
    const rows = players.map((player) => {
      const icon = ctx.iconByName.get(player.hero);
      const rating = player.fields?.rating?.value;
      const side = player.side === 'left' ? '左' : '右';
      const pending = player.heroStatus && player.heroStatus !== 'exact';
      return `<span class="draft-item">
        <small>${side}${(player.slot ?? 0) + 1}</small>
        ${icon ? `<img src="${esc(icon)}" alt="" loading="lazy">` : '<i class="draft-hero">?</i>'}
        <b title="${esc(player.nickname || '')}">${esc(player.nickname || '—')}</b>
        <em class="${pending ? 'is-warn' : ''}">${rating === undefined || rating === null ? '—' : fmt(rating, 1)}</em>
      </span>`;
    }).join('');
    return `<div class="draft-grid">${rows}</div>
      <div class="draft-foot">
        <span>评分来自草稿，未复核前仅供参考</span>
        <a class="control" href="#review/${esc(channel.id)}">进入逐项校对 →</a>
      </div>`;
  }

  async function toggleDraft(button) {
    const id = button.dataset.chanExpand;
    const box = document.querySelector(`[data-draft-for="${id}"]`);
    if (!box) return;
    const open = button.getAttribute('aria-expanded') === 'true';
    if (open) {
      button.setAttribute('aria-expanded', 'false');
      box.hidden = true;
      return;
    }
    button.setAttribute('aria-expanded', 'true');
    box.hidden = false;
    if (box.dataset.loaded) return;
    box.innerHTML = '<p class="capture-hint">正在读取十人草稿…</p>';
    try {
      const channel = await api(`channels/${encodeURIComponent(id)}`);
      box.innerHTML = draftSummary(channel, lookups());
      box.dataset.loaded = '1';
    } catch (error) {
      box.innerHTML = `<p class="capture-hint is-error">读取失败：${esc(error.message)}</p>`;
    }
  }

  /** 按日期分组，日期只在组头出现一次。 */
  function renderChannelList(channels, ctx, filtered = false, emptyText = '') {
    if (!channels.length) {
      return `<p class="review-empty">${esc(filtered
        ? '当前筛选下没有待审查记录。'
        : (emptyText || '没有缺失值，营地对局已自动进入正式统计。'))}</p>`;
    }
    const groups = new Map();
    for (const channel of channels) {
      const date = String(channel.match?.date || '未标日期');
      if (!groups.has(date)) groups.set(date, []);
      groups.get(date).push(channel);
    }
    return [...groups.entries()].map(([date, rows]) => {
      const missing = rows.filter((channel) => (channel.missing || []).length).length;
      return `<div class="chan-group">
        <div class="chan-group-head"><b>${esc(date)}</b>
          <span>${rows.length} 条${missing ? ` · ${missing} 条有缺失值` : ' · 可一键通过'}</span></div>
        <div class="chan-rows">${rows.map((channel) => channelRow(channel, ctx)).join('')}</div>
      </div>`;
    }).join('');
  }

  // ---------------- 授权卡 ----------------

  // ---------------- 状态条与连接卡 ----------------

  /** 深色主面板：只回答一个问题 —— 今天这一步该做什么。状态作为脚注附在同一块里。 */
  function heroCard(ctx) {
    const { auth, players, pending, missing, autoPassed } = ctx;
    const expired = Boolean(auth.authorized && (auth.expired || state.authIssue));
    const issue = state.authIssue || auth.reason || '营地登录态已失效。';

    let step;
    let title;
    let desc;
    let action = '';

    if (expired) {
      step = '第 1 步';
      title = '营地授权已失效，需要补充授权';
      desc = `${issue}重新扫码补充授权后，沿用原来的选手白名单；已进入正式统计的数据不受影响。`;
      action = '<button class="hero-cta" data-capture-action="auth-start">补充授权</button>';
    } else if (!auth.authorized) {
      step = '第 1 步';
      title = '授权王者营地';
      desc = '用教练号扫码授权一次，凭证只存在本机。之后每天拉取都不必再扫。';
      action = '<button class="hero-cta" data-capture-action="auth-start">扫码授权</button>';
    } else if (!players.length) {
      step = '第 2 步';
      title = '绑定一位选手的营地 ID';
      desc = '挑每场必上的号（通常是队长）。让他在王者营地分享任意一局战绩并复制链接，粘贴到下方即可自动解析。';
 
      action = '<button class="hero-cta" data-capture-action="focus-player">去添加</button>';
    } else if (!state.list) {
      step = '第 3 步';
      title = '拉取最近对局';
      desc = `读取 ${players.length} 位选手的最近战绩，按对局去重后让你勾选；进行中的对局不包含在内。`;
      action = '<button class="hero-cta" data-capture-action="pull">拉取对局</button>';
    } else if (Object.keys(state.checked).length) {
      const count = Object.keys(state.checked).length;
      step = '第 4 步';
      title = `同步所选 ${count} 局`;
      desc = '同步后无缺失值的对局会直接进入正式统计；只有缺英雄或面板字段的局才进入「缺失值审查」。';
      action = `<button class="hero-cta" data-capture-action="import">同步 ${count} 局</button>`;
    } else {
      step = '已完成';
      title = '今天没有需要同步的新对局';
      desc = pending
        ? `还有 ${pending} 条在缺失值审查${missing ? `，其中 ${missing} 条有缺失值` : ''}；无缺失的局已直接进入正式统计。`
        : '无缺失值的对局都已进入正式统计。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="hero-cta" data-capture-action="scroll-channels">查看 ${pending} 条</button>`
        : '';
    }

    const syncText = ctx.daysAgo === null ? '还没拉取过'
      : ctx.daysAgo === 0 ? '今天拉取过' : `${ctx.daysAgo} 天前拉取`;
    const dot = (ok) => `<i class="hero-dot ${ok ? 'is-ok' : 'is-warn'}"></i>`;

    // 授权正常、选手也在时，「下一步」只是一句提示：压成一条，把首屏让给拉取列表。
    return `<section class="next-hero ${ctx.compact ? 'is-compact' : ''}" data-tour="collect-hero">
      <div class="hero-main">
        <span class="hero-eyebrow">下一步 · ${esc(step)}</span>
        <h2>${esc(title)}</h2>
        <p>${esc(desc)}</p>
      </div>
      ${ctx.compact
        ? `<div class="hero-compact-note">${esc(syncText)}${pending ? ` · ${fmt(pending)} 条待审` : ''}</div>`
        : (action ? `<div class="hero-action">${action}</div>` : '')}
      <div class="hero-stats">
        <span>${dot(auth.authorized && !expired)}营地授权 <b>${expired ? '失效' : auth.authorized ? '正常' : '未授权'}</b></span>
        <span>${dot(players.length > 0)}营地选手 <b>${fmt(players.length)}</b></span>
        <span>${dot(!pending)}缺失值审查 <b>${fmt(pending)}</b><small>· ${autoPassed ? `${autoPassed} 已自动进统计` : '无待审'}</small></span>
        <span class="hero-sync">${esc(syncText)}</span>
      </div>
    </section>`;
  }

  function connectionBlock(auth, players) {
    const ready = Boolean(auth.authorized);
    const expired = ready && Boolean(auth.expired || state.authIssue);
    const issue = state.authIssue || auth.reason || '营地登录态已失效。';
    const checking = state.busy === 'auth-check';
    const checkedAt = state.authProbe?.valid === true
      ? state.authProbe.checkedAt
      : (auth.checkedAt && !auth.expired ? auth.checkedAt : '');

    // 已经授权、也有选手时，这条只在需要改配置时才展开，省下首屏一大块。
    if (ready && !expired && players.length && !state.connOpen) {
      return `<section class="section conn-fold" data-tour="camp-connect">
        <div class="conn-fold-main">
          <b>营地连接</b>
          <span class="chip is-done">已授权</span>
          <small>${esc(auth.nickname || '已登录')}${stamp(auth.loginAt) ? ` · 授权于 ${stamp(auth.loginAt)}` : ''} · ${fmt(players.length)} 位选手</small>
        </div>
        <div class="capture-actions">
          <button class="control" data-capture-action="conn-toggle">展开管理</button>
        </div>
      </section>`;
    }

    let actions;
    if (!ready) {
      actions = `<button class="primary" data-capture-action="auth-start">${icon('search')} 扫码授权</button>`;
    } else {
      actions = `<div class="conn-actions">
        <button class="control" data-capture-action="auth-check" ${checking ? 'disabled' : ''}>${checking ? '检测中…' : '检测授权'}</button>
        <button class="${expired ? 'primary' : 'control'}" data-capture-action="auth-start">${icon('refresh')} ${expired ? '补充授权' : '重新扫码'}</button>
        <button class="control" data-capture-action="auth-clear">删除凭证</button>
        ${players.length ? '<button class="control" data-capture-action="conn-toggle">收起</button>' : ''}</div>`;
    }

    // 授权失效时把「补充授权」放在最显眼的位置；二维码展开后让出位置给扫码。
    const alert = expired && !state.qr
      ? `<div class="conn-alert" role="alert">
          <div class="conn-alert-copy"><b>营地授权已失效，爬取已暂停</b>
            <small>${esc(issue)}重新扫码补充授权后即可继续拉取；已进入正式统计的数据不受影响。</small></div>
          <button class="primary" data-capture-action="auth-start">补充授权</button>
        </div>`
      : '';

    let authBody;
    if (state.qr) {
      authBody = `<div class="capture-qr"><img src="data:image/png;base64,${esc(state.qr.qrcodeBase64 || '')}" alt="营地授权二维码">
        <div><p class="capture-qr-note">用王者营地 App 扫码，并在手机上确认授权。</p>
        <p class="capture-qr-status">${esc(state.notice?.message || '等待扫码…')}</p>
        <button class="control" data-capture-action="auth-cancel">取消这次授权</button></div></div>`;
    } else if (expired) {
      authBody = `<div class="conn-auth is-stale"><i class="conn-dot"></i>
        <div class="conn-auth-main"><b>${esc(auth.nickname || '已登录')}</b>
          <small>营地 ID ${text(auth.userId)}${stamp(auth.loginAt) ? ` · 授权于 ${stamp(auth.loginAt)}` : ''} · 登录态已失效</small></div>
        <span class="chip is-warn">授权失效</span></div>`;
    } else if (ready) {
      authBody = `<div class="conn-auth is-ok"><i class="conn-dot"></i>
        <div class="conn-auth-main"><b>${esc(auth.nickname || '已登录')}</b>
          <small>营地 ID ${text(auth.userId)}${stamp(auth.loginAt) ? ` · 授权于 ${stamp(auth.loginAt)}` : ''}${checkedAt ? ` · 最近检测 ${stamp(checkedAt)}` : ''}</small></div>
        <span class="chip is-done">已授权</span></div>`;
    } else {
      authBody = `<div class="conn-auth is-off"><i class="conn-dot"></i>
        <div class="conn-auth-main"><b>还没有营地凭证</b><small>扫码授权后才能拉取选手的最近对局</small></div>
        <span class="chip is-idle">未授权</span></div>`;
    }

    const list = players.length
      ? `<ul class="conn-list">${players.map((player) => {
          const off = player.enabled === false;
          return `<li class="${off ? 'is-off' : ''}">
            <label class="conn-pick" title="取消勾选后，拉取对局会跳过这个号">
              <input type="checkbox" ${off ? '' : 'checked'}
                data-capture-action="player-toggle" data-camp-user="${esc(player.campUserId)}">
              <span>拉取</span>
            </label>
            <b>${esc(player.nickname || '未命名')}</b><small>${text(player.campUserId)}</small>
            <button class="conn-rename" data-capture-action="player-rename" data-camp-user="${esc(player.campUserId)}">改名</button>
            <button class="conn-x" data-capture-action="player-remove" data-camp-user="${esc(player.campUserId)}" aria-label="移除这个选手">×</button>
          </li>`;
        }).join('')}</ul>`
      : '';

    const playersBody = `<div class="conn-players" data-tour="camp-players">
      <div class="conn-players-head"><h3>选手白名单</h3><span class="conn-count">${fmt(players.length)} 位 · 勾选 ${fmt(players.filter((p) => p.enabled !== false).length)} 位</span></div>
      <div class="conn-keytip">
        <div><b>只绑一个每场都上的号就够</b><span>一局详情自带双方十人面板，不用每个选手都绑。</span></div>
        <div><b>看不到某位选手的战绩？</b><span>让他在王者营地「隐私设置」里把教练加入白名单，否则拉不到他的对局。</span></div>
        <div><b>这里的「改名」只是本机备注</b><span>比赛里的游戏ID → 选手ID 在「赛训 → 数据准备 → 身份对照」里统一改，一处命名处处生效。</span></div>
      </div>
      ${players.length ? '' : '<p class="conn-empty">还没有绑定选手 —— 填好下面这一栏，拉取就有东西可读了。</p>'}
      <details class="camp-link-help" data-tour="camp-link">
        <summary>怎么拿到这条链接？（带图步骤）</summary>
        <div class="camp-link-body">
          <p class="camp-link-intro">这一步每位选手只做一次，配的是<strong>「选手是谁」</strong>，不是某一局：用他分享出来的营地链接解析出<strong>营地 ID</strong> 存进下面的白名单。之后每天点「拉取对局」就能同步他最近的比赛，不用再找他要链接。</p>
          <ol class="camp-link-steps">
            <li>
              <span class="camp-link-num">01</span>
              <div><strong>在王者营地打开这一局结算页，分享到微信</strong>
                <p>打完停在结算页（也可以从「战绩」打开任意一局进「回顾分析」），点右上角「…」→「分享」→ 发给教练或文件传输助手。微信里会收到一张来源标「王者营地」的卡片。</p>
                <figure class="camp-link-shot"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-entry.jpg" target="_blank" rel="noopener" aria-label="查看分享入口大图"><img src="/assets/capture-guide/camp-share-entry.jpg" alt="王者营地对局结算页，右上角「…」是分享入口" loading="lazy"></a><figcaption>图 1 · 结算页右上角「…」→ 分享到微信（点图看大图）</figcaption></figure>
              </div>
            </li>
            <li>
              <span class="camp-link-num">02</span>
              <div><strong>在微信里长按卡片，点「用默认浏览器打开」</strong>
                <p>长按这张营地卡片 → 选绿色的「用默认浏览器打开」（或「打开方式」里挑一个浏览器）。微信内置浏览器看不到完整地址，必须跳到外部浏览器才拿得到下面那串链接。</p>
                <figure class="camp-link-shot is-menu"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-wechat.png" target="_blank" rel="noopener" aria-label="查看微信操作大图"><img src="/assets/capture-guide/camp-share-wechat.png" alt="微信里长按营地分享卡片，选择用默认浏览器打开" loading="lazy"></a><figcaption>图 2 · 微信长按消息 →「用默认浏览器打开」（点图看大图）</figcaption></figure>
              </div>
            </li>
            <li>
              <span class="camp-link-num">03</span>
              <div><strong>复制浏览器地址栏里的整条链接</strong>
                <p>打开后地址栏是 <code>https://camp.qq.com/h5/webdist/mp-redirect/index.html?</code> 开头的一长串，关键参数是 <code>userId</code>（营地 ID）、<code>roleId</code> 和 <code>gameSeq</code>。页面提示「此站点正在尝试打开 Weixin」直接关掉，不影响复制。长按地址栏 → 全选 → 复制，<strong>整条都要</strong>。</p>
                <figure class="camp-link-shot is-wide"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-browser.png" target="_blank" rel="noopener" aria-label="查看地址栏链接大图"><img src="/assets/capture-guide/camp-share-browser.png" alt="浏览器地址栏里的营地分享完整链接，含 userId 等参数" loading="lazy"></a><figcaption>图 3 · 地址栏里 ? 后面的 userId 等参数一个都不能少（点图看大图）</figcaption></figure>
              </div>
            </li>
            <li>
              <span class="camp-link-num">04</span>
              <div><strong>粘到下面输入框，点「批量添加」</strong>
                <p>整条粘进来，不用手抄 ID；解析出的营地 ID 会存进白名单，昵称先占位，可以直接改。一位选手保存后长期有效。</p></div>
            </li>
          </ol>
          <p>链接里 <code>userId=</code> 后面才是营地 ID，<code>roleId=</code> 是角色 ID，不要混；漏参数会提示「链接里没有营地 ID」。也可以直接填 5–15 位数字的营地 ID，或粘 <code>cu.qq.com</code> 短链（会自动展开）；<strong>微信小程序跳转链不能用</strong>，必须按第 02 步在浏览器里打开再复制。</p>
          <p>只绑一个每场都上的号就够 —— 一局详情自带双方十人面板。选手战绩对教练不可见时，请他在营地「隐私设置」里把教练加入白名单。</p>
        </div>
      </details>
      <form data-capture-form="player" class="conn-form">
        <textarea name="identity" rows="3" autocomplete="off" spellcheck="false"
          placeholder="一行一个营地 ID，也可以直接粘贴多条分享链接"></textarea>
        <div class="conn-form-foot">
          <p>支持换行、逗号或空格分隔，链接会自动解析。每场必上的号一位就够 —— 一局详情自带双方十人面板。</p>
          <button class="primary" type="submit">批量添加</button>
        </div>
      </form>${list}</div>`;

    return block('营地连接', '授权一次，之后每天点「拉取对局」；凭证只存在本机。',
      `<div class="conn-body">${alert}${authBody}${playersBody}</div>`, actions, 'data-tour="camp-connect"');
  }

  // ---------------- 对局列表 ----------------

  /** 上一次同步到底进了多少局：写入 / 待审 / 营地无详情 / 没拉全，一直留在卡片里。 */
  function summaryLine() {
    const s = state.summary;
    if (!s) return '';
    const parts = [`<b>上次同步 ${fmt(s.total)} 局</b>`];
    parts.push(`<span class="cap-sum-ok">${fmt(s.saved)} 局进入正式统计</span>`);
    if (s.review) parts.push(`<span class="cap-sum-warn">${fmt(s.review)} 局待缺失值审查</span>`);
    if (s.unsupported) parts.push(`<span class="cap-sum-warn">${fmt(s.unsupported)} 局营地无详情</span>`);
    if (s.failed) parts.push(`<span class="cap-sum-warn">${fmt(s.failed)} 局没拉全，可重试</span>`);
    const problems = (s.problems || []).filter(Boolean).slice(0, 2);
    return `<div class="cap-summary${s.failed && !s.saved && !s.unsupported ? ' is-error' : ''}">
      ${parts.join('')}${problems.length ? `<small>${esc(problems.join('；'))}</small>` : ''}
    </div>`;
  }

  function pullBlock(players) {
    const allPlayers = players;
    players = players.filter((player) => player.enabled !== false);
    const list = state.list;
    const checked = Object.keys(state.checked).length;
    const blocked = Boolean(state.authIssue);
    const blockedHint = blocked
      ? '<p class="capture-hint is-warn">营地授权已失效，拉取会失败 —— 先点「补充授权」重新扫码。</p>'
      : '';
    const moreAction = state.pullHasMore
      ? `<button class="control" data-capture-action="pull-more" ${state.busy ? 'disabled' : ''}>继续拉取更早的对局</button>`
      : '';
    const right = `<div class="capture-actions">
      ${blocked ? '<button class="primary" data-capture-action="auth-start">补充授权</button>' : ''}
      ${moreAction}
      <button class="control" data-capture-action="check-all" ${list && list.some((entry) => !entry.imported && !entry.channelReady && !campDetailExpired(entry)) ? '' : 'disabled'}>全选</button>
      <button class="control" data-capture-action="check-none">全部取消勾选</button>
      <button class="control" data-capture-action="pull" ${state.busy === 'pull' || !players.length || blocked ? 'disabled' : ''}>${state.busy === 'pull' ? '正在拉取…' : list ? '重新拉取' : '拉取对局'}</button>
      <button class="${checked ? 'primary' : 'control'}" data-capture-action="import" ${checked && !state.busy ? '' : 'disabled'}>${state.busy === 'import' ? `同步中 ${checked} 局…` : `同步所选 ${checked} 局`}</button></div>`;

    const flow = `${summaryLine()}<div data-cap-progress>${progressBar()}</div>`;
    if (!allPlayers.length) {
      return block('拉取对局', '绑定选手后，这里会列出他们最近的战绩供你勾选。',
        `<div class="cap-body">${flow}${blockedHint}<p class="capture-hint">还没有可拉取的选手 —— 先在上面「营地连接」里绑定一位。</p></div>`, right, 'data-tour="camp-pull"');
    }
    if (!players.length) {
      const offNames = allPlayers.map((p) => p.nickname || p.campUserId).join('、');
      return block('拉取对局', '所有选手都取消了勾选。',
        `<div class="cap-body">${flow}${blockedHint}<p class="capture-hint is-warn">当前白名单里 ${esc(offNames)} 都取消勾选了。在「营地连接」里勾上至少一个号再拉取。</p></div>`,
        right, 'data-tour="camp-pull"');
    }
    const lastSync = (state.value?.sync?.details || []).reduce(
      (max, detail) => Math.max(max, Number(detail.syncedAt) || 0), 0);
    const daysAgo = lastSync ? Math.floor((Date.now() / 1000 - lastSync) / 86400) : null;
    const syncNote = daysAgo === null ? '还没有拉取过'
      : daysAgo === 0 ? '上次拉取：今天'
        : `上次拉取：${daysAgo} 天前`;

    if (!list) {
      const stale = daysAgo !== null && daysAgo >= 1;
      return block('拉取对局', `将读取 ${players.length} 位选手的最近对局，按对局去重后让你勾选。`,
        `<div class="cap-body">${flow}${blockedHint}<p class="capture-hint"><i class="chip ${stale ? 'is-warn' : 'is-idle'}">${esc(syncNote)}</i>${stale ? ' 训练赛后记得拉一次。' : ''}</p>
         <p class="capture-hint">${state.listNote || '点右上角「拉取对局」开始。'}</p></div>`, right, 'data-tour="camp-pull"');
    }
    if (!list.length) {
      return block('拉取对局', '最近没有新的对局。', `<div class="cap-body">${flow}${blockedHint}<p class="capture-hint">${esc(state.listNote || '选手最近没有可拉取的对局。')}</p></div>`, right, 'data-tour="camp-pull"');
    }

    const entryRow = (entry) => {
      const seq = String(entry.gameSeq);
      const already = Boolean(entry.imported);
      // 已建好审查记录（十人面板已挂上）的局不再重复拉详情；
      // 只有详情缺失或详情已缓存但还没建记录的局才可勾选。
      const inReview = !already && Boolean(entry.channelReady);
      // 营地只保留最近一个月的战局详情；更早的局反复拉也只会拿到 -30457。
      const expired = !already && !inReview && campDetailExpired(entry);
      const needsDetail = !already && !inReview && !expired && Boolean(entry.channelExists);
      const needsChannel = !already && !inReview && !expired && !needsDetail && Boolean(entry.detailCached);
      const selectable = !already && !inReview && !expired;
      const checkedAttr = state.checked[seq] && selectable ? 'checked' : '';
      const when = matchTime(entry);
      const mode = String(entry.mapName || '营地对局');
      const hero = String(entry.heroName || (entry.heroId ? `英雄 ${entry.heroId}` : ''));
      const kda = [entry.killcnt, entry.deadcnt, entry.assistcnt]
        .map((v) => (v === null || v === undefined || v === '' ? '—' : v)).join('/');
      const bits = [mode, hero ? `${hero} ${kda}` : '', matchMinutes(entry.usedTime),
        entry.gradeGame ? `评分 ${entry.gradeGame}` : '', entry.roleJobName || '',
        entry.desc || ''].filter(Boolean).join(' · ');
      const extra = [entry.ownerName || entry.owner || '', `对局 ${seq}`].filter(Boolean).join(' · ');
      const stateChip = already ? '<i class="chip is-in">已进统计</i>'
        : inReview ? '<i class="chip is-warn" title="十人面板已挂上，等缺失值审查处理">待审查</i>'
          : expired ? '<i class="chip is-idle" title="营地只提供最近一个月的战局详情；这局要走截图或录屏「新录入一局」">营地无详情</i>'
            : needsDetail ? '<i class="chip is-warn" title="审查记录已建，但十人面板还没挂上；同步会补详情">通道待补详情</i>'
              : needsChannel ? '<i class="chip is-warn" title="详情已缓存，同步时不用重新下载，只补建审查记录">补建记录</i>'
                : '<i class="chip is-pending">待同步</i>';
      return `<label class="ingest-row is-check ${!selectable ? 'is-in' : ''}">
        <input type="checkbox" data-capture-check="${esc(seq)}" ${checkedAttr} ${!selectable ? 'disabled' : ''}>
        <span class="ingest-date"><b>${esc(when.day || '--')}</b><small>${esc(when.clock || '时间未知')}</small></span>
        <span class="ingest-main"><b>${resultChip(entry)}<span>${esc(when.clock || when.day)} ${esc(mode)}</span></b>
          <small title="${esc(bits)}">${esc(bits)}</small>
          <small class="ingest-extra">${esc(extra)}</small></span>
        <span class="ingest-chips">
          ${stateChip}
        </span>
      </label>`;
    };

    // 按「等待同步 / 已在审查 / 已进统计 / 营地无详情」分桶：后两类收进折叠，不占篇幅。
    const pendingRows = list.filter((entry) => !entry.imported && !entry.channelReady
      && !campDetailExpired(entry));
    const reviewRows = list.filter((entry) => !entry.imported && entry.channelReady);
    const importedRows = list.filter((entry) => entry.imported);
    const expiredRows = list.filter((entry) => !entry.imported && !entry.channelReady
      && campDetailExpired(entry));

    const moreHint = state.pullHasMore
      ? `已翻 ${state.pullPages} 页，还能继续拉更早的。`
      : `已翻 ${state.pullPages} 页，已到底。`;
    const fold = (rows, label, extra = '') => (rows.length
      ? `<details class="ingest-fold${extra}"><summary>${esc(label)} <i>${fmt(rows.length)}</i> 局</summary>
          <div class="ingest-list">${rows.map(entryRow).join('')}</div></details>`
      : '');

    const expiredCallout = expiredRows.length ? `<div class="ingest-callout" role="status">
      <div class="ingest-callout-copy">
        <b>${fmt(expiredRows.length)} 局营地无详情</b>
        <span>营地只保留最近一个月的对局详情（手机营地 App 里也打不开）。这些局不是补采，要用截图或录屏「新录入一局」直接建档。</span>
      </div>
      <div class="capture-actions">
        <button class="control" data-capture-action="backfill-open">新录入一局</button>
        <button class="control" data-capture-action="jump-ocr">去截图 / 录屏 →</button>
      </div>
    </div>` : '';

    const pendingList = pendingRows.length
      ? `<div class="ingest-list">${pendingRows.map(entryRow).join('')}</div>`
      : `<p class="capture-hint">${reviewRows.length || importedRows.length || expiredRows.length
        ? '没有待同步的新局；下面的折叠里有已进统计和营地无详情的局。'
        : '没有可同步的新局。'}</p>`;

    // 列表一长，顶部的「全部取消勾选」要滚回去才点得到；底下再放一条同样的出口。
    const clearBar = checked
      ? `<div class="capture-actions ingest-clear">
          <span class="capture-hint">已勾选 ${fmt(checked)} 局</span>
          <button class="control" data-capture-action="check-none">全部取消勾选</button>
        </div>`
      : '';

    return block('拉取对局',
      `待同步 ${fmt(pendingRows.length)} · 已进统计 ${fmt(importedRows.length)}`
      + `${expiredRows.length ? ` · 营地无详情 ${fmt(expiredRows.length)}` : ''}`
      + `${reviewRows.length ? ` · 待审查 ${fmt(reviewRows.length)}` : ''}`
      + ` · 已勾选 ${fmt(checked)}。${moreHint}`,
      `<div class="cap-body">${flow}${expiredCallout}${pendingList}${clearBar}`
      + fold(importedRows, '已进正式统计')
      + fold(expiredRows, '营地无详情（超过一个月）', ' is-warn')
      + fold(reviewRows, '已在缺失值审查')
      + `<p class="capture-hint">${esc(state.busy === 'import' ? '正在同步并写入正式统计…' : (state.listNote || ''))}</p></div>`,
      right, 'data-tour="camp-pull"');
  }

  // ---------------- 页面 ----------------

  /** 两个 OCR 窗口：截图与录屏，就地能看到进度、能上传，不必先跳去别的页。 */
  function ocrWindows(shots, recordings) {
    const images = shots?.images || [];
    const groups = shots?.groups || [];
    const recs = recordings?.recordings || [];
    const jobs = recordings?.jobs || [];
    const running = jobs.filter((job) => ['queued', 'running'].includes(job.status)).length;
    const recent = groups[0];
    const shotNote = images.length
      ? `${fmt(groups.length)} 组 · ${fmt(images.length)} 张${recent?.match?.date ? ` · 最近 ${recent.match.date}` : ''}`
      : '还没有上传过截图';
    const recNote = recs.length
      ? `${fmt(recs.length)} 段录屏${running ? ` · ${fmt(running)} 个识别中` : ''}`
      : '还没有上传过录屏';
    return `<section class="section cap-ocr" id="ocr-windows" data-tour="camp-ocr">
      <div class="section-heading"><div><h2>截图 / 录屏 OCR</h2>
        <p>营地窗口外的老局走这条：同一局七张赛后截图，或一段完整录屏（十人阵容清楚）。识别完可以补到已有对局，也可以直接「新录入一局」；OCR 出来的字段要人工审核一遍。</p></div>
      </div>
      <div class="ocr-windows">
        <article class="ocr-window">
          <header><b>截图 OCR</b><i class="chip ${images.length ? 'is-ok' : 'is-idle'}">${esc(shotNote)}</i></header>
          <p>七张赛后结算图：战绩（装备型）、战绩（KDA 占比）、数据、输出、生存、发育、团队。
            传图用微信要勾「原图」或改用 QQ 发文件，被压缩的图识别时会被提示重传。</p>
          <div class="ocr-actions">
            <label class="control ocr-file">选择截图<input type="file" multiple
              accept="image/png,image/jpeg,image/webp" data-ingest-shots></label>
            <button class="primary" data-capture-action="upload-shots" ${state.busy === 'shots' ? 'disabled' : ''}>
              ${state.busy === 'shots' ? '上传识别中…' : '上传并识别'}</button>
            <a class="ocr-more" href="#shots">完整页 →</a>
          </div>
        </article>
        <article class="ocr-window">
          <header><b>录屏 OCR</b><i class="chip ${recs.length ? 'is-ok' : 'is-idle'}">${esc(recNote)}</i></header>
          <p>每局一段完整录像：加载页十人阵容 5 秒 → 1 倍速整局 → 结算页 5 秒，团队面板常开。</p>
          <div class="ocr-actions">
            <a class="primary" href="#videos">上传录屏 →</a>
            <a class="control" href="/assets/collection-guide.html?section=video"
               target="_blank" rel="noopener">拍摄要求</a>
            <a class="ocr-more" href="#videos">完整页 →</a>
          </div>
        </article>
      </div>
    </section>`;
  }

  /** 营地拿不到的老对局：先新录入一局（建通道），再去截图/录屏页把识别结果录入到这一局。 */
  function backfillPanel() {
    if (!state.backfillOpen) return '';
    return `<section class="section backfill-panel" data-tour="camp-backfill">
      <div class="section-heading"><div><h2>新录入一局</h2>
        <p>营地一个月窗口外的历史数据（超过一个月、选手隐藏战绩等）：营地没有可补采的通道，先建一局，再到截图 / 录屏页把识别结果录入到这一局。</p></div>
        <div class="capture-actions"><button class="control" data-capture-action="backfill-close">取消</button></div></div>
      <div class="backfill-fields">
        <label>比赛日期<input type="date" data-backfill="date" value="${today()}"></label>
        <label>训练组 / 对手<input type="text" data-backfill="session" maxlength="40" autocomplete="off" placeholder="如 0917 训练赛 / 对手名"></label>
        <button class="primary" data-capture-action="backfill-create" ${state.busy ? 'disabled' : ''}>
          ${state.busy === 'backfill' ? '正在建…' : '建好这局，去传截图'}</button>
      </div>
      <p class="capture-hint">建好后会跳到「截图 OCR」：七张截图识别完，在卡片左侧「补采到已有对局」里选中这一局（已预选）补进去；也可以在录屏页用「补采到已有对局」补一段完整录像。补完再去校对页核对保存。
        <a class="cap-guide-link" href="/assets/collection-guide.html?section=screenshots" target="_blank" rel="noopener">先看拍摄要求 →</a></p>
    </section>`;
  }

  /** 按当前状态给出「今天这一步该做什么」，只显示一个动作。 */
  function guideCard(auth, players, pending) {
    let title;
    let desc;
    let action = '';

    if (!auth.authorized) {
      title = '第 1 步 · 授权王者营地';
      desc = '用教练号扫码授权一次，凭证只存在本机。之后每天拉取都不必再扫。';
      action = '<button class="primary" data-capture-action="auth-start">扫码授权</button>';
    } else if (!players.length) {
      title = '第 2 步 · 绑定一位选手的营地 ID';
      desc = '挑每场必上的号（通常是队长）。让他在王者营地分享任意一局战绩到微信并复制链接，'
        + '把链接粘贴到下方「营地选手」的输入框即可，会自动解析出 ID。一局详情自带双方十人面板，所以一个号就够。';
      action = '<button class="control" data-capture-action="focus-player">去添加</button>';
    } else if (!state.list) {
      title = '第 3 步 · 拉取最近对局';
      desc = `会读取 ${players.length} 位选手的最近战绩，按对局去重后让你勾选；进行中的对局不会包含在内。`;
      action = '<button class="primary" data-capture-action="pull">拉取对局</button>';
    } else if (Object.keys(state.checked).length) {
      const count = Object.keys(state.checked).length;
      title = `第 4 步 · 同步所选 ${count} 局`;
      desc = '同步后无缺失值的对局直接进入正式统计；只有缺英雄或面板字段的局才进缺失值审查。';
      action = `<button class="primary" data-capture-action="import">同步所选 ${count} 局</button>`;
    } else {
      title = '今天没有需要同步的新对局';
      desc = pending
        ? `还有 ${pending} 条在缺失值审查，可以在下面逐条确认。`
        : '无缺失值的对局都已进入正式统计。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="control" data-capture-action="scroll-channels">查看 ${pending} 条</button>`
        : '';
    }

    return `<section class="guide-card" data-guide>
      <div class="guide-body"><span class="guide-eyebrow">下一步</span>
        <h2>${esc(title)}</h2><p>${esc(desc)}</p></div>
      ${action ? `<div class="guide-action">${action}</div>` : ''}
    </section>`;
  }

  function view(value) {
    if (value?.unavailable) {
      return withPage('营地同步', '营地数据暂时读不到，已经自动重试过；点一次读取即可。',
        `<div class="capture-notice" role="status">营地数据还没返回，稍后会自动补上。</div>`
        + block('重新读取', '数据恢复后会自动补上，也可以现在重试一次。',
          `<p><button class="control" data-action="refresh">重新读取</button></p>`), false);
    }
    const list = value?.channels?.channels || [];
    const sync = value?.sync || {};
    const details = sync.details || [];
    const auth = sync.auth || {};
    const players = value?.config?.players || sync.config?.players || [];

    // 缺失值审查只列还没进入正式统计的通道：无缺失的会自动通过，
    // 有缺失的留在这里逐条确认；已自动通过的不再占用审查列表。
    const pendingChannels = list.filter((channel) => channel.saved?.status !== 'saved');
    const missingChannels = pendingChannels.filter((channel) => (channel.missing || []).length);
    const autoPassed = list.filter((channel) => channel.saved?.status === 'saved').length;
    const visibleChannels = filterChannels(pendingChannels);
    const seedCount = pendingChannels.filter(isSeedChannel).length;
    const filtering = Boolean(state.query || state.scope !== 'all'
      || state.range !== 'all' || (state.range === 'custom' && (state.fromDate || state.toDate)));

    // 上次同步距今几天 —— 教练容易忘了每天拉
    const lastSync = details.reduce((max, detail) => Math.max(max, Number(detail.syncedAt) || 0), 0);
    const daysAgo = lastSync ? Math.floor((Date.now() / 1000 - lastSync) / 86400) : null;

    const ordered = [...details].sort((a, b) => {
      const byLink = Number(Boolean(b.channelId)) - Number(Boolean(a.channelId));
      if (byLink) return byLink;
      const left = a.startedAt || a.eventAt || '';
      const right = b.startedAt || b.eventAt || '';
      if (left && right) return right.localeCompare(left);
      return left ? -1 : right ? 1 : 0;
    });
    // 只有对局 ID、没有时间也没有数值的记录不进首屏 —— 它们占位置但不提供信息
    const meaningful = ordered.filter((detail) => detail.gametime
      || (Array.isArray(detail.kda) && detail.kda.some((v) => v !== null && v !== undefined)));
    const headPool = (meaningful.length ? meaningful : ordered).slice(0, 8);
    const head = headPool;
    const rest = ordered.filter((detail) => !head.includes(detail));
    const restTable = rest.length
      ? table(['状态', '时间', '对局', '模式', 'KDA'], rest.map((detail) => [
        `<span class="result ${detail.channelId ? '' : 'pending'}">${detail.channelId ? '已进统计' : '未同步'}</span>`,
        text(when(detail)), text(detail.gameSeq), text(detail.mapName || '营地对局'), kdaText(detail)]))
      : '';

    const authDetail = auth.authorized
      ? `${auth.nickname || '已登录'}${stamp(auth.loginAt) ? ` · ${stamp(auth.loginAt)}` : ''}`
      : '需要在王者营地扫码授权';

    const notice = state.notice
      ? `<div class="capture-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`
      : '';

    // 授权正常 + 有选手时不再需要「下一步」引导：页面按 连接 → 拉取 → OCR → 审查 排。
    const ready = Boolean(auth.authorized) && !(auth.expired || state.authIssue);
    const compact = ready && players.length > 0;

    // 两条采集通道分开审查：营地字段齐全自动入库；截图/录屏 OCR 的局必须人工确认。
    const campChannels = pendingChannels.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) > 0);
    const ocrChannels = pendingChannels.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) === 0);
    const passableChannels = ocrChannels.filter((channel) => !(channel.missing || []).length);

    const reviewActions = `<div class="capture-actions">
      <button class="control" data-capture-action="backfill-open">新录入一局（截图/录屏）</button>
      ${passableChannels.length ? `<button class="primary" data-capture-action="approve-clean" ${state.busy ? 'disabled' : ''}>
        ${state.busy === 'approve' ? '正在通过…' : `一键通过无缺失 ${passableChannels.length} 条`}</button>` : ''}
    </div>`;

    const flowBar = `<div class="flow-bar">
      <label class="flow-search">${icon('search')}
        <input type="search" data-ingest-query value="${esc(state.query)}"
          placeholder="搜索对局审查" aria-label="搜索对局审查"></label>
      <div class="seg" role="group" aria-label="数据范围">
        <button data-ingest-scope="all" class="${state.scope === 'all' ? 'is-on' : ''}">全部 <i>${pendingChannels.length}</i></button>
        <button data-ingest-scope="real" class="${state.scope === 'real' ? 'is-on' : ''}">真实 <i>${pendingChannels.length - seedCount}</i></button>
        <button data-ingest-scope="seed" class="${state.scope === 'seed' ? 'is-on' : ''}">验证 <i>${seedCount}</i></button>
      </div>
      <div class="seg" role="group" aria-label="时间范围">
        <button data-ingest-range="all" class="${state.range === 'all' ? 'is-on' : ''}">全部时间</button>
        <button data-ingest-range="7" class="${state.range === '7' ? 'is-on' : ''}">近 7 天</button>
        <button data-ingest-range="30" class="${state.range === '30' ? 'is-on' : ''}">近 30 天</button>
        <button data-ingest-range="custom" class="${state.range === 'custom' ? 'is-on' : ''}">自定义</button>
      </div>
      ${filtering ? '<button class="flow-clear" data-capture-action="clear-filter">清除筛选</button>' : ''}
    </div>
    ${state.range === 'custom' ? `<div class="flow-dates">
      <label>从<input type="date" data-ingest-from value="${esc(state.fromDate)}"></label>
      <label>到<input type="date" data-ingest-to value="${esc(state.toDate)}"></label>
    </div>` : ''}`;

    const campGroup = `<section class="review-group${campChannels.length ? '' : ' is-empty'}">
      <header>
        <b>王者营地</b>
        <i class="chip ${campChannels.length ? 'is-warn' : 'is-done'}">${campChannels.length ? `${fmt(campChannels.length)} 条待处理` : '无需审核'}</i>
        <small>营地同步的局字段齐全，自动进入正式统计，不走人工审核。</small>
      </header>
      ${''}<div data-ingest-list="camp">${renderChannelList(filterChannels(campChannels), lookups(), filtering,
        '营地同步的局都已自动进入正式统计，没有需要人工审核的记录。')}</div>
    </section>`;

    const ocrGroup = `<section class="review-group${ocrChannels.length ? '' : ' is-empty'}">
      <header>
        <b>截图 / 录屏 OCR</b>
        <i class="chip ${ocrChannels.length ? 'is-warn' : 'is-idle'}">${fmt(ocrChannels.length)} 条待审核</i>
        <small>OCR 出来的字段可能有缺，逐条确认后才能保存。</small>
      </header>
      ${''}<div data-ingest-list="ocr">${renderChannelList(filterChannels(ocrChannels), lookups(), filtering,
        '还没有截图 / 录屏新录入的局。营地一个月窗口外的老局在这里新录入。')}</div>
    </section>`;

    const reviewBlock = block('对局审查',
      `王者营地同步的局不用人工审核；截图 / 录屏 OCR 的局必须逐条确认（共 ${fmt(ocrChannels.length)} 条待处理）。`,
      `<div class="cap-body">${flowBar}<div class="review-split">${campGroup}${ocrGroup}</div></div>`,
      reviewActions, 'data-tour="camp-flow"');

    const connection = connectionBlock(auth, players);
    const work = players.length ? pullBlock(players) : '';

    return withPage('营地同步', '授权一次，之后每天增量拉取；营地一个月窗口外的老局用截图 / 录屏新录入。',
      `<div class="cap-page">
        ${notice}
        ${compact ? '' : heroCard({
          auth, players, pending: pendingChannels.length, missing: missingChannels.length,
          autoPassed, channels: list.length, daysAgo, compact,
        })}
        ${connection}
        ${work}
        ${backfillPanel()}
        ${ocrWindows(value?.shots, value?.recordings)}
        ${reviewBlock}
        <details class="tier-fold"><summary>采集来源档位 —— 营地窗口内走同步，窗口外 / 缺素材走截图 / 录屏</summary>
          <div class="sv-tiers">${SOURCE_TIERS.map(([name, tier, note, href]) => `<div class="sv-tier is-${tier.key}">
            <span class="sv-tier-tag">${esc(tier.label)}</span>
            <b>${esc(name)}</b>
            <small>${esc(note)}</small>
            ${href ? `<a class="sv-tier-go" href="${esc(href)}">打开 →</a>` : '<span class="sv-tier-go is-none">无需单独操作</span>'}
          </div>`).join('')}</div></details>
      </div>`, false);
  }

  // ---------------- 交互 ----------------

  function startPoll(taskId) {
    stopPoll();
    state.poll = setInterval(async () => {
      if (!state.qr || state.qr.taskId !== taskId) { stopPoll(); return; }
      try {
        const result = await api(`camp/auth/poll?taskId=${encodeURIComponent(taskId)}`);
        if (result.status === 'scanned') { setNotice('已扫码，请在手机上确认…'); paint(); return; }
        if (result.status === 'waiting') return;
        if (result.status === 'success') {
          stopPoll();
          state.qr = null;
          state.authIssue = '';
          state.authProbe = null;
          state.authCheckedAt = Date.now();
          setNotice(`已授权：${result.nickname || result.userId || ''}`);
          await reloadValue();
          paint();
          return;
        }
        if (result.status === 'error') {
          stopPoll();
          state.qr = null;
          setNotice(result.message || '授权失败，请重新扫码', true);
          paint();
          return;
        }
        if (result.status === 'expired' || result.status === 'canceled') {
          stopPoll();
          state.qr = null;
          setNotice(result.status === 'canceled' ? '已在手机上取消，可以重新扫码。' : '二维码已过期，请重新扫码。', true);
          paint();
        }
      } catch (error) {
        setNotice(`轮询失败：${error.message}`, true);
        paint();
      }
    }, 2500);
  }

  function setChecked(gameSeq, on) {
    if (on) state.checked[gameSeq] = true;
    else delete state.checked[gameSeq];
  }

  function change(event) {
    const box = event.target.closest('[data-capture-check]');
    if (!box) return false;
    setChecked(box.dataset.captureCheck, box.checked);
    paint(true);
    return true;
  }

  /** 一行一个，也接受逗号 / 空格分隔；链接会逐个解析出营地 ID。 */
  function splitIdentities(raw) {
    return String(raw || '')
      .split(/[\s,，;；]+/)
      .map((part) => part.trim())
      .filter(Boolean);
  }

  async function submitPlayer(form) {
    const input = form.querySelector('[name="identity"]');
    const tokens = splitIdentities(input?.value);
    if (!tokens.length) return;

    state.busy = 'player';
    setNotice(`正在处理 ${tokens.length} 个营地 ID…`);
    paint();

    const players = [...(state.value?.config?.players || [])];
    const added = [];
    const failed = [];

    for (const token of tokens) {
      try {
        let campUserId = token;
        let nickname = '';
        if (!/^\d{5,15}$/.test(token)) {
          const resolved = await api('camp/resolve', { method: 'POST', body: { url: token } });
          campUserId = String(resolved.userId || '');
          nickname = resolved.nickname || '';
          if (!/^\d{5,15}$/.test(campUserId)) throw new Error('链接里没有营地 ID');
        }
        if (players.some((player) => player.campUserId === campUserId)) {
          failed.push(`${campUserId}（已存在）`);
          continue;
        }
        players.push({ campUserId, nickname: nickname || `选手 ${campUserId.slice(-4)}` });
        added.push(nickname || campUserId);
      } catch (error) {
        failed.push(`${token.slice(0, 18)}：${error.message}`);
      }
    }

    try {
      if (added.length) await api('camp/config', { method: 'POST', body: { players } });
      await reloadValue();
      const parts = [];
      if (added.length) parts.push(`已添加 ${added.length} 位：${added.join('、')}`);
      if (failed.length) parts.push(`${failed.length} 个没成功：${failed.slice(0, 3).join('；')}`);
      setNotice(parts.join('；') || '没有可添加的内容。', failed.length > 0 && !added.length);
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function updatePlayer(campUserId, patchValue) {
    state.busy = 'player';
    try {
      const players = (state.value?.config?.players || []).map((player) => (
        player.campUserId === campUserId ? { ...player, ...patchValue } : player));
      await api('camp/config', { method: 'POST', body: { players } });
      await reloadValue();
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function renamePlayer(campUserId) {
    const current = (state.value?.config?.players || [])
      .find((player) => player.campUserId === campUserId);
    const answer = window.prompt('这个选手叫什么？（只影响本机显示）', current?.nickname || '');
    if (answer === null) return;
    const name = answer.trim().slice(0, 40);
    if (!name) { setNotice('昵称不能为空。', true); return; }
    await updatePlayer(campUserId, { nickname: name });
    setNotice('已改名。');
  }

  async function togglePlayer(campUserId, enabled) {
    await updatePlayer(campUserId, { enabled });
    setNotice(enabled ? '已加入拉取。' : '已停止拉取该选手，历史数据不受影响。');
  }

  async function removePlayer(campUserId) {
    state.busy = 'player';
    try {
      const players = (state.value?.config?.players || [])
        .filter((player) => player.campUserId !== campUserId);
      await api('camp/config', { method: 'POST', body: { players } });
      setNotice('已移除该选手。');
      await reloadValue();
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  const PULL_PAGES_PER_RUN = 12; // 一次最多翻 12 页（约 150 局），避免长时间卡住
  const PULL_PAGE_CAP = 500;    // 单次拉取的对局硬上限，防止历史战绩无限翻

  async function pullList(extend = false) {
    if (state.busy) return; // 顶部「下一步」和卡片里都有拉取按钮，别让它们叠着跑
    const allPlayers = state.value?.config?.players || [];
    if (!allPlayers.length) { setNotice('先在「营地选手」里添加选手。', true); paint(); return; }
    const players = allPlayers.filter((player) => player.enabled !== false);
    if (!players.length) { setNotice('白名单里的号都取消勾选了，先勾上至少一个再拉取。', true); paint(); return; }
    state.busy = 'pull';
    if (!extend) {
      state.list = null;
      state.checked = {};
      state.pullCursor = null;
      state.pullHasMore = false;
      state.pullPages = 0;
      state.summary = null;
      state.widgetResult = null;
    }
    setNotice('');
    state.listNote = '正在读取…';
    state.progress = { phase: 'list', label: extend ? '正在继续拉取更早的对局' : '正在读取对局列表',
      done: 0, total: PULL_PAGES_PER_RUN, current: '', matches: 0,
      note: '按开赛时间从新到旧翻页，已拿到的局会实时累加' };
    paint();
    const merged = new Map();
    if (extend && state.list) {
      for (const entry of state.list) merged.set(String(entry.gameSeq), entry);
    }
    const problems = [];
    let authProblem = '';
    let hasMore = false;
    const cursors = (extend && state.pullCursor && typeof state.pullCursor === 'object')
      ? { ...state.pullCursor } : {};
    let pages = 0;

    for (const player of players) {
      let cursor = Number(cursors[player.campUserId] || 0);
      for (let page = 0; pages < PULL_PAGES_PER_RUN; page += 1) {
        state.progress = { phase: 'list', label: extend ? '正在继续拉取更早的对局' : '正在读取对局列表',
          done: pages, total: PULL_PAGES_PER_RUN, current: '', matches: merged.size,
          note: `第 ${pages + 1} 页 · 已拿到 ${merged.size} 局 · ${player.nickname || '选手'}` };
        paintProgress();
        let result;
        try {
          result = await api('camp/list', { method: 'POST',
            body: { campUserId: player.campUserId, lastTime: cursor } });
        } catch (error) {
          problems.push(`${player.nickname || player.campUserId}：${error.message}`);
          if (error.authInvalid) {
            authProblem = error.reason || error.message || '营地登录态已失效';
          }
          break;
        }
        const batch = result.entries || [];
        for (const entry of batch) {
          const key = String(entry.gameSeq);
          const existing = merged.get(key);
          if (existing) { (existing.owners ||= []).push(player.nickname || player.campUserId); continue; }
          merged.set(key, { ...entry,
            owners: [player.nickname || player.campUserId],
            ownerName: player.nickname || `选手 ${String(player.campUserId).slice(-4)}`,
            ownerCampUserId: player.campUserId });
        }
        pages += 1;
        state.pullPages += 1;
        if (result.gaming) problems.push(`${player.nickname || '选手'} 有一局进行中，未包含在列表里`);
        const more = Boolean(result.hasMore) && merged.size < PULL_PAGE_CAP;
        const rawCursor = Number(result.lastTime || 0);
        // 游标是递减的 epoch 秒；没有下一页、游标无效或不再递减就停。
        const advanced = rawCursor > 0 && (cursor === 0 || rawCursor < cursor);
        hasMore = more && advanced;
        cursor = advanced ? rawCursor : cursor;
        cursors[player.campUserId] = cursor;
        if (!hasMore) break;
      }
      if (authProblem) break;
    }
    const nextCursor = cursors;

    state.list = [...merged.values()].sort(
      (a, b) => Number(b.dtEventTime || 0) - Number(a.dtEventTime || 0));
    state.pullHasMore = hasMore && pages >= PULL_PAGES_PER_RUN;
    state.pullCursor = state.pullHasMore ? nextCursor : null;
    for (const entry of state.list) {
      // 已进统计、已有待审查记录（十人面板已挂上）、或超出营地详情保留期的局不再自动勾选。
      setChecked(entry.gameSeq, !entry.imported && !entry.channelReady && !campDetailExpired(entry));
    }
    state.listNote = problems.join('；');
    state.busy = '';
    state.progress = null;
    if (authProblem) {
      state.authIssue = authProblem;
      setNotice('营地授权已失效，拉取已停止。请补充授权后再试。', true);
      await reloadValue();
    } else {
      const expired = state.list.filter((entry) => !entry.imported && !entry.channelReady
        && campDetailExpired(entry)).length;
      const fresh = state.list.filter((entry) => !entry.imported && !entry.channelReady
        && !campDetailExpired(entry)).length;
      setNotice(`拉到 ${state.list.length} 局（翻 ${pages} 页），已自动勾选 ${fresh} 局。`
        + (expired ? `另有 ${expired} 局营地无详情，在列表下方单独折叠。` : ''));
    }
    paint();
  }

  async function importSelected() {
    if (state.busy) return; // 顶部「下一步」的同步按钮与卡片按钮共用同一批勾选
    const chosen = (state.list || []).filter((entry) => state.checked[entry.gameSeq]
      && !entry.imported && !entry.channelReady);
    if (!chosen.length) { setNotice('请先勾选要同步的对局。', true); paint(); return; }
    const groups = new Map();
    for (const entry of chosen) {
      const draft = { ...entry };
      delete draft.owners;
      delete draft.ownerName;
      delete draft.ownerCampUserId;
      delete draft.imported;
      const key = entry.ownerCampUserId;
      if (!groups.has(key)) groups.set(key, { nickname: entry.ownerName || '', entries: [] });
      groups.get(key).entries.push(draft);
    }
    state.busy = 'import';
    state.summary = null;
    state.widgetResult = null;
    state.progress = { phase: 'detail', label: '正在同步对局详情', done: 0,
      total: chosen.length, current: '', note: '同步后会直接进入正式统计，缺字段的局才进缺失值审查' };
    setNotice(`正在同步 ${chosen.length} 局…`);
    paint();
    let savedTotal = 0;
    let reviewTotal = 0;
    let unsupportedTotal = 0;
    const problems = [];
    try {
      for (const [campUserId, group] of groups) {
        await api('camp/sync', { method: 'POST', body: { campUserId, nickname: group.nickname, entries: group.entries } });
        // 同步是后台任务，轮询到结束再走下一组；进度来自后端的真实处理计数。
        // 单局详情请求间隔约 2 秒，一次最多 360 局，轮询上限留足 30 分钟。
        let status = null;
        for (let i = 0; i < 1800; i += 1) {
          status = await api('camp/sync');
          if (status?.error) throw new Error(status.error);
          const p = status?.progress || {};
          if (status.running) {
            state.progress = { phase: p.phase || 'detail', label: p.phase === 'channel' ? '正在写入正式统计' : '正在同步对局详情',
              done: Number(p.done) || 0, total: Number(p.total) || chosen.length,
              current: p.current || '', note: `本批 ${group.entries.length} 局 · ${group.nickname || '选手'} · 可以切到别的页面，进度在右下角` };
            paintProgress();
          } else {
            state.progress = { phase: 'done', label: '同步完成，正在刷新', done: chosen.length,
              total: chosen.length, current: '' };
            paintProgress();
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
        const results = status?.result?.players || [];
        if (!results.length) {
          throw new Error(status?.error || '同步没有返回结果，可能被中断了，请重试。');
        }
        const authFailure = results.find((item) => item.authInvalid);
        if (authFailure) {
          const error = new Error(authFailure.reason || authFailure.error || '营地登录态已失效');
          error.authInvalid = true;
          throw error;
        }
        for (const item of results) {
          if (item.ok === false) {
            problems.push(item.error || item.reason || '营地同步失败');
            continue;
          }
          const report = item.channels || {};
          savedTotal += Number(report.saved) || 0;
          reviewTotal += Number(report.review) || 0;
          // 官方回放（经济曲线 / 事件 / 团战 / 逐秒位置）是同步后单独补拉的：
          // 失败以前完全不显示，通道看着「同步完成」，分析页却全是空图。
          const official = report.official || {};
          const officialFailed = Number(official.failed) || 0;
          if (official.error) {
            problems.push(`官方回放没拉全：${official.error}`);
          } else if (officialFailed > 0) {
            const first = (official.items || []).find(
              (row) => row.status === 'failed' && row.error);
            problems.push(`${officialFailed} 局官方回放没拉到${first ? `（${first.error}）` : ''}`);
          }
          const summary = item.summary || {};
          // 营地超过一个月就不再提供战局详情（-30457）：这批局只能走截图/录屏，
          // 不算「拉取失败」，也不再让它们反复勾选重试。
          const unsupported = new Set((summary.unsupportedSeqs || []).map(String));
          unsupportedTotal += unsupported.size;
          if (summary.aborted) problems.push(summary.aborted);
          else if (Number(summary.failed) > 0) {
            const first = (summary.errors || [])[0];
            problems.push(`${summary.failed} 局详情没拉到${first ? `（${first.message}）` : ''}`);
          }
          if (unsupported.size) {
            problems.push(`${unsupported.size} 局早于一个月，营地不提供详情，需用截图/录屏新录入一局`);
          }
          // 逐局回填状态：写好/待审/营地无详情的局不再勾选，没拉到的继续留着可以重试。
          for (const row of report.items || []) {
            const seq = String(row.gameSeq || '');
            if (!seq) continue;
            const entry = (state.list || []).find((item) => String(item.gameSeq) === seq);
            if (row.status === 'saved' || row.status === 'review') {
              if (entry) {
                entry.channelReady = true;
                if (row.status === 'saved') entry.imported = true;
              }
              delete state.checked[seq];
            } else if (unsupported.has(seq)) {
              if (entry) entry.unsupported = true;
              delete state.checked[seq];
            } else if (row.status === 'failed' && row.error) {
              problems.push(`对局 ${seq}：${row.error}`);
            }
          }
        }
      }
      const written = savedTotal + reviewTotal;
      const left = Math.max(0, chosen.length - written - unsupportedTotal);
      state.summary = { total: chosen.length, saved: savedTotal, review: reviewTotal,
        unsupported: unsupportedTotal, failed: left, problems };
      if (!written && !unsupportedTotal) {
        // 一局都没写进去、也没有「营地本来就给不了」的，按失败提示，别报成功。
        throw new Error(problems[0] || '这一批一局都没能写入，请重试或补充授权后再拉。');
      }
      if (left) {
        // 还有没拉全的局：保留列表（已写好的会自动变成「已进统计」），方便直接重试。
        state.checked = Object.fromEntries(Object.entries(state.checked)
          .filter(([seq]) => (state.list || []).some((entry) => String(entry.gameSeq) === seq
            && !entry.imported && !entry.channelReady)));
      } else if (!unsupportedTotal) {
        state.list = null;
        state.checked = {};
        state.pullHasMore = false;
        state.pullCursor = null;
      } else {
        state.checked = {};
      }
      await reloadValue();
      const tail = [
        reviewTotal ? `${reviewTotal} 局待缺失值审查` : '',
        unsupportedTotal ? `${unsupportedTotal} 局营地无详情（早于一个月），请用截图/录屏新录入一局` : '',
        left ? `${left} 局没拉全，仍留在列表里可以重试` : '',
      ].filter(Boolean).join('；');
      setNotice(`本次同步 ${chosen.length} 局：${savedTotal} 局进入正式统计${tail ? `；${tail}` : '，全部无缺失值'}。`,
        !written && !unsupportedTotal ? true : false);
      state.widgetResult = { total: chosen.length, saved: savedTotal, review: reviewTotal,
        unsupported: unsupportedTotal, failed: left,
        note: unsupportedTotal ? '营地只提供最近一个月的战局详情。' : '' };
    } catch (error) {
      if (error.authInvalid) {
        state.authIssue = error.message;
        setNotice('营地授权已失效，这次同步没有完成。请补充授权后重新拉取。', true);
        await reloadValue();
      } else {
        state.summary = state.summary || { total: chosen.length, saved: savedTotal,
          review: reviewTotal, unsupported: unsupportedTotal,
          failed: Math.max(0, chosen.length - savedTotal - reviewTotal - unsupportedTotal), problems };
        state.widgetResult = { total: chosen.length, saved: savedTotal, review: reviewTotal,
          unsupported: unsupportedTotal,
          failed: Math.max(0, chosen.length - savedTotal - reviewTotal - unsupportedTotal),
          note: error.message };
        setNotice(`同步失败：${error.message}`, true);
      }
    } finally {
      state.busy = '';
      state.progress = null;
      if (state.widgetResult) {
        if (state.widgetTimer) clearTimeout(state.widgetTimer);
        state.widgetTimer = setTimeout(() => {
          state.widgetResult = null;
          state.widgetTimer = null;
          renderWidget();
        }, 30000);
      }
      paint();
    }
  }

  /** 一键通过：只处理没有缺失值的通道，有缺失值的留在审查区逐条确认。 */
  async function approveClean() {
    const list = state.value?.channels?.channels || [];
    const passable = list.filter((channel) => channel.saved?.status !== 'saved'
      && !(channel.missing || []).length);
    if (!passable.length) {
      setNotice('没有无缺失值、待通过的通道。', true);
      paint();
      return;
    }
    state.busy = 'approve';
    setNotice(`正在通过 ${passable.length} 条无缺失通道…`);
    paint();
    try {
      const result = await api('channels/approve', {
        method: 'POST',
        body: { channelIds: passable.map((channel) => channel.id), reviewedBy: '本机一键通过' },
      });
      await reloadValue();
      const passed = (result.passed || []).length;
      const skipped = (result.skipped || []).length;
      setNotice(skipped
        ? `已通过 ${passed} 条；${skipped} 条仍有缺失值，留在缺失值审查。`
        : `已通过 ${passed} 条，全部写入正式统计。`);
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  /** 就地传七张截图：上传 → 排队识别 → 刷新两个 OCR 窗口与审查列表。 */
  async function uploadIngestShots() {
    const input = document.querySelector('[data-ingest-shots]');
    const files = input?.files ? [...input.files] : [];
    if (!files.length) { setNotice('先选择要上传的截图。', true); paint(); return; }
    state.busy = 'shots';
    setNotice(`正在上传 ${files.length} 张截图…`);
    paint();
    let done = 0;
    const failed = [];
    for (const file of files) {
      try {
        const uploaded = await api(`images?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
        if (uploaded?.id) {
          await api(`postgame/images/${encodeURIComponent(uploaded.id)}/ocr`, { method: 'POST' });
          done += 1;
        }
      } catch (error) {
        failed.push(`${file.name}：${error.message}`);
      }
    }
    state.busy = '';
    await reloadValue();
    setNotice(failed.length
      ? `已上传识别 ${done} 张，失败 ${failed.length} 张：${failed[0]}`
      : `已上传并识别 ${done} 张截图；识别完去「截图完整页」补到已有对局，或新录入一局。`, failed.length > 0);
    paint();
  }

  /** 新录入一局：先建一条 OCR 录入通道，并把通道 id 带到截图页预选「补采到已有对局」。 */
  async function createBackfillMatch() {
    const date = String(document.querySelector('[data-backfill="date"]')?.value || '').trim();
    const session = String(document.querySelector('[data-backfill="session"]')?.value || '').trim();
    if (!date && !session) { setNotice('至少填比赛日期或训练组。', true); paint(); return; }
    state.busy = 'backfill';
    try {
      const channel = await api('channels', {
        method: 'POST',
        body: { match: { date, session }, entry: { mode: 'ocr', primary: '' } },
      });
      try { sessionStorage.setItem('cap-new-channel', channel.id); } catch { /* 无痕模式 */ }
      state.backfillOpen = false;
      await reloadValue();
      setNotice(`已新建一局（录像/截图录入）：${date || session}。去传七张截图或一段录屏，补采到这一局。`);
      location.hash = '#shots';
    } catch (error) {
      setNotice(`建局失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  /** 主动检测授权：拉取前就知道登录态是否还能用，避免点一次失败一次。 */
  async function checkAuth(force) {
    const auth = state.value?.sync?.auth || {};
    if (!auth.authorized || state.busy) return;
    state.busy = 'auth-check';
    paint();
    try {
      const result = await api(`camp/auth/check${force ? '?force=1' : ''}`, { method: 'POST' });
      state.authCheckedAt = Date.now();
      state.authProbe = result;
      if (result.valid === false) {
        state.authIssue = result.reason || '营地登录态已失效';
        if (force) setNotice('营地授权已失效，拉取会失败。请补充授权后再试。', true);
      } else if (result.valid === true) {
        state.authIssue = '';
        if (force) setNotice('营地授权检测通过。');
      } else if (result.reason && force) {
        // 断网 / 接口异常：只提示检测失败，不把本地凭证判死。
        setNotice(result.reason, true);
      }
      await reloadValue();
    } catch (error) {
      if (force) setNotice(`检测失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function click(event) {
    const expander = event.target.closest('[data-chan-expand]');
    if (expander) { await toggleDraft(expander); return true; }
    const row = event.target.closest('[data-chan-open]');
    if (row && !event.target.closest('a')) { location.hash = `#review/${row.dataset.chanOpen}`; return true; }

    const button = event.target.closest('[data-capture-action]');
    if (button) {
      const action = button.dataset.captureAction;
      if (action === 'expand-draft') {
        await toggleDraft(button);
        return true;
      }
      if (action === 'clear-filter') {
        state.query = ''; state.fromDate = ''; state.toDate = '';
        state.scope = 'all'; state.range = 'all';
        paint();
        return true;
      }
      if (action === 'focus-player') {
        const input = document.querySelector('[data-capture-form="player"] input[name="identity"]');
        if (input) { input.scrollIntoView({ block: 'center', behavior: 'smooth' }); input.focus(); }
        return true;
      }
      if (action === 'scroll-channels') {
        // 区块顺序会随「营地连接」折叠而变，按标记找，别用下标。
        const host = document.querySelector('[data-tour="camp-flow"]');
        if (host) host.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return true;
      }
      if (action === 'check-all') {
        const list = state.list || [];
        state.checked = Object.fromEntries(list
          .filter((entry) => !entry.imported && !entry.channelReady && !campDetailExpired(entry))
          .map((entry) => [entry.gameSeq, true]));
        paint();
        return true;
      }
      if (action === 'check-none') {
        // 拉取完会自动勾上所有待同步的局；这里必须一次清空，不能逼教练逐个点。
        const dropped = Object.keys(state.checked).length;
        state.checked = {};
        setNotice(dropped ? `已取消全部 ${dropped} 局的勾选。` : '当前没有勾选的对局。');
        paint(true);
        return true;
      }
      if (action === 'auth-check') { await checkAuth(true); return true; }
      if (action === 'auth-start') {
        try {
          state.busy = 'auth';
          setNotice('正在生成二维码…');
          paint();
          state.qr = await api('camp/auth/qr', { method: 'POST' });
          startPoll(state.qr.taskId);
          setNotice('等待扫码…');
        } catch (error) {
          state.qr = null;
          setNotice(error.message, true);
        } finally {
          state.busy = '';
          paint();
        }
        return true;
      }
      if (action === 'auth-cancel') {
        const taskId = state.qr?.taskId;
        stopPoll();
        state.qr = null;
        setNotice('已取消这次授权。');
        if (taskId) {
          try { await api(`camp/auth/cancel?taskId=${encodeURIComponent(taskId)}`, { method: 'POST' }); } catch { /* 会自行过期 */ }
        }
        paint();
        return true;
      }
      if (action === 'auth-clear') {
        if (!window.confirm('删除本机的营地登录凭证？删除后需要重新扫码。')) return true;
        try {
          await api('camp/auth/clear', { method: 'POST' });
          await reloadValue();
          setNotice('凭证已删除。');
        } catch (error) {
          setNotice(error.message, true);
        }
        paint();
        return true;
      }
      if (action === 'pull') { await pullList(); return true; }
      if (action === 'pull-more') { await pullList(true); return true; }
      if (action === 'import') { await importSelected(); return true; }
      if (action === 'approve-clean') { await approveClean(); return true; }
      if (action === 'conn-toggle') { state.connOpen = !state.connOpen; paint(); return true; }
      if (action === 'backfill-open') { state.backfillOpen = true; paint(); return true; }
      if (action === 'backfill-close') { state.backfillOpen = false; paint(); return true; }
      if (action === 'backfill-create') { await createBackfillMatch(); return true; }
      if (action === 'upload-shots') { await uploadIngestShots(); return true; }
      if (action === 'jump-ocr') {
        const host = document.getElementById('ocr-windows');
        if (host) host.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return true;
      }
      if (action === 'player-remove') { await removePlayer(button.dataset.campUser); return true; }
    if (action === 'player-rename') { await renamePlayer(button.dataset.campUser); return true; }
    if (action === 'player-toggle') {
      await togglePlayer(button.dataset.campUser, button.checked);
      return true;
    }
    }

    const form = event.target.closest('[data-capture-form="player"]');
    if (form && event.target.closest('button[type="submit"]')) {
      event.preventDefault();
      await submitPlayer(form);
      return true;
    }
    return false;
  }

  function afterRender() {
    // 切走页面时停掉轮询，避免旧页继续打接口
    if (!location.hash.startsWith('#ingest')) { stopPoll(); return; }
    // 首屏由 features 渲染，不经过 paint()，这里补一次筛选绑定
    bindFilter();
    // 每次回到采集页最多自动检测一次授权；点「检测授权」可强制重查。
    const auth = state.value?.sync?.auth;
    if (auth?.authorized && Date.now() - state.authCheckedAt > 10 * 60 * 1000) checkAuth(false);
  }

  return { load, render: view, click, change, afterRender };
}


