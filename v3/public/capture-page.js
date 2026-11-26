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
import { glyph } from './ui-icons.js';

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

/* 采集请求带上当前赛事，后端据此把本批对局盖到统一数据范围。 */
function currentCaptureContext() {
  try {
    return { competitionId: localStorage.getItem('training-current-competition') || '' };
  } catch { return { competitionId: '' }; }
}

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
  /* 只有单页应用的静态服务器会对任意路径回 200 的 index.html；
     解析不出 JSON 说明这个地址不是工作台，按「接口不在」处理，页面才说得出原因。 */
  try {
    return await response.json();
  } catch {
    const missing = new Error('采集数据暂时读不到。');
    missing.unavailable = true;
    throw missing;
  }
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

/* 采集页的六个页签：营地同步 / 截图 / 录屏 / 回放 / 审查 / 已采集对局。
   2026-11-16：前四个后段原先是独立页面（#shots / #videos / #replays / #review），
   现在是同一个采集页的页签；旧链接仍然可用，路由把它们都映射回 #ingest。
   2026-11-24：加 #imported，列出库里已落库的对局，删掉后可回营地同步重爬。 */
const CAPTURE_HASHES = ['#ingest', '#shots', '#videos', '#replays', '#review', '#imported'];

export function createCapture(h) {
  const { esc, fmt, table, block, stats, empty, withPage, icon } = h;
  const text = (value) => esc(value === null || value === undefined || value === '' ? '—' : value);
  /* 素材页与审查明细在 features.js 里比采集页晚创建，用 getter 晚绑定。 */
  const sourcePages = () => h.sources?.();
  const reviewPages = () => h.review?.();

  const onCapturePage = () => CAPTURE_HASHES.some((hash) => location.hash.startsWith(hash));

  const state = {
    value: null,
    qr: null,
    poll: null,
    list: null,
    checked: {},
    busy: '',
    notice: '',
    /* 只有 /api/channels 读不到时的降级说明；camp/sync 挂了才算整页读不到。 */
    degraded: '',
    /* 整页读不到时的判定结果：{ cause: not-workbench|api-mismatch|offline, origin, port }。 */
    failure: null,
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
    // 刷新后从服务端接回的后台同步任务；只启一个，避免重复轮询。
    syncResume: null,
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
    // 上一次整页取数的时刻：切页签不算刷新，短时间内的重复进入直接复用，避免每点一下都重拉 1MB。
    loadedAt: 0,
    // 「审查」页签里正在看的那一条明细（#review/<id>）。
    reviewValue: null,
  };

  /** 当前 hash 落在采集页的哪个页签（旧链接 #shots/#videos/#replays/#review 一律映射进来）。 */
  function routeParts() {
    const [path] = location.hash.slice(1).split('?');
    const [name = '', sub = ''] = path.split('/');
    let id = sub || '';
    try { id = decodeURIComponent(id); } catch { /* 非法编码就按原文 */ }
    const tab = { ingest: 'camp', shots: 'shots', videos: 'videos', replays: 'replays',
      review: 'review', imported: 'imported' }[name];
    return { tab: tab || 'camp', id: tab === 'review' ? id : '' };
  }

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
    if (!onCapturePage()) { renderWidget(); return; }
    if (root && state.value) {
      // 勾选一局就把整页换掉会让列表跳回原处，逐个取消勾选时要保持当前位置。
      const anchor = keepScroll ? window.scrollY : null;
      root.innerHTML = view(state.value);
      bindFilter();
      if (anchor !== null) window.scrollTo(0, anchor);
    }
    renderWidget();
  }

  function syncPhaseLabel(phase) {
    return phase === 'official' ? '正在补拉官方回放（放慢速度，避免限流）'
      : phase === 'channel' ? '正在写入正式统计'
        : phase === 'done' ? '正在收尾'
          : phase === 'list' ? '正在读取对局列表' : '正在同步对局详情';
  }

  /** 统一的进度条：教练能看见「第几步、处理到第几局、还剩多少」。 */
  function progressInner(p) {
    const total = Math.max(1, Number(p.total) || 1);
    const done = Math.min(total, Math.max(0, Number(p.done) || 0));
    const percent = Math.round((done / total) * 100);
    const phase = syncPhaseLabel(p.phase);
    const detail = p.current ? ` · 对局 ${p.current}` : '';
    const count = p.phase === 'list'
      ? `已翻 ${done} / ${total} 页${p.matches ? ` · 已拿到 ${p.matches} 局` : ''}`
      : `${done} / ${total} 局${detail}`;
    // 原生 <progress> 自带进度条语义与读屏播报；不往里面塞文字，也不给它设焦点。
    return `<div class="cap-progress-head"><b>${esc(p.label || phase)}</b>
        <span>${esc(count)}</span></div>
      <progress class="cap-progress-track" max="100" value="${percent}"
        aria-label="同步进度：${esc(phase)}，${esc(count)}"></progress>
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

  /** 服务端同步跑在后台线程里：刷新页面只重来前端，任务不会停。首屏读到
      running=true 时把进度条接回来并继续轮询，别让用户以为同步失败。 */
  function resumeSyncIfRunning(sync) {
    if (!sync?.running || state.syncResume) return;
    state.syncResume = String(sync.startedAt || 'live');
    const apply = (status) => {
      const p = status?.progress || {};
      state.progress = {
        phase: p.phase || 'detail',
        label: `${syncPhaseLabel(p.phase)}（刷新后已接回）`,
        done: Number(p.done) || 0,
        total: Math.max(1, Number(p.total) || 1),
        current: p.current || '',
        note: '同步在后台继续，不用重新点；进度会自动更新',
      };
      paintProgress();
    };
    apply(sync);
    const timer = setInterval(async () => {
      try {
        const status = await api('camp/sync');
        if (status?.error) throw new Error(status.error);
        if (status.running) { apply(status); return; }
        clearInterval(timer);
        state.syncResume = null;
        state.progress = null;
        setNotice('');
        await reloadValue();
        setNotice('后台同步已完成，数据已刷新。');
        paint();
      } catch (error) {
        clearInterval(timer);
        state.syncResume = null;
        state.progress = null;
        setNotice(`接回后台同步失败：${error.message}`, true);
        paint();
      }
    }, 1200);
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  /* 删除确认用原生 <dialog>：焦点约束、Esc 和背景 inert 都由浏览器给，
     不用手写 focus trap，也比 window.confirm 更少打断当前操作。 */
  let deleteDialog = null;
  function ensureDeleteDialog() {
    if (deleteDialog && document.body.contains(deleteDialog)) return deleteDialog;
    deleteDialog = document.createElement('dialog');
    deleteDialog.id = 'cap-delete-dialog';
    deleteDialog.setAttribute('aria-labelledby', 'cap-delete-title');
    deleteDialog.innerHTML = `<h1 id="cap-delete-title">删除这条已采集对局？</h1>
      <p class="cap-delete-detail" data-cap-delete-detail></p>
      <p class="capv-hint">${glyph('warning', { size: 18 })}删除会清掉这一局的阵容、BP 等关联数据。</p>
      <form method="dialog">
        <button value="cancel" autofocus>${glyph('ban', { size: 18 })}取消</button>
        <button value="delete" class="cap-delete-confirm">${glyph('trash', { size: 18 })}删除</button>
      </form>`;
    document.body.appendChild(deleteDialog);
    return deleteDialog;
  }

  function confirmMatchDelete(key, title) {
    return new Promise((resolve) => {
      const dialog = ensureDeleteDialog();
      dialog.querySelector('[data-cap-delete-detail]').textContent = `${title}（${key}）`;
      // Esc / 取消不写 returnValue，上一轮的值不能漏到这一轮。
      dialog.returnValue = '';
      const onClose = () => {
        dialog.removeEventListener('close', onClose);
        const confirmed = dialog.returnValue === 'delete';
        dialog.returnValue = '';
        resolve(confirmed);
      };
      dialog.addEventListener('close', onClose);
      dialog.showModal();
    });
  }

  async function deleteMatch(key) {
    state.busy = 'delete-match';
    try {
      const result = await api('camp/delete-match', { method: 'POST', body: { matchKey: key } });
      await reloadValue();
      setNotice(`已删除对局${result.channelsReset ? '，营地通道已重置，可回「营地同步」重新勾选' : ''}。`);
    } catch (error) {
      setNotice(`删除失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function reloadValue() {
    // 写操作之后要把数据换成最新的，必须绕开「切页签不重取」的短期缓存。
    state.value = await load('ingest', '', undefined, true);
  }

  // ---------------- 数据 ----------------

  /* 「读不到」有三种完全不同的原因，页面必须分开说，否则教练只能看到一句
     「暂时读不到」：接口本身不在（开的不是工作台那个地址）、工作台没在跑、
     工作台在线但采集接口异常。判据是工作台独有的 /api/health。 */
  async function probeWorkbench() {
    try {
      const response = await fetch(ROOT_API + 'health', { cache: 'no-store' });
      if (!response.ok) return { ok: false, status: response.status };
      const payload = await response.json().catch(() => ({}));
      return { ok: true, status: response.status, pid: payload.pid || 0, version: payload.version || '' };
    } catch {
      return { ok: false, status: 0 };
    }
  }

  async function classifyFailure() {
    const health = await probeWorkbench();
    const port = String(location.port || '');
    if (health.ok) return { cause: 'api-mismatch', origin: location.origin, port };
    if (health.status === 404) {
      // 工作台默认端口上 404：多半是旧版本没这套接口，而不是开错了地址。
      return { cause: port === '8766' ? 'api-mismatch' : 'not-workbench', origin: location.origin, port };
    }
    return { cause: 'offline', origin: location.origin, port };
  }

  let unavailableRetries = 0;
  /* 采集页的五个页签共用一份数据：切页签时 hash 变了，但没必要把渠道、营地同步、
     目录、素材重新拉一遍（跨局明细那份就有 400KB）。显式刷新（fresh）才重取。 */
  const LOAD_TTL_MS = 15000;

  async function load(_name, _key, signal, fresh = false) {
    const route = routeParts();
    const cached = !fresh && state.value && Date.now() - state.loadedAt < LOAD_TTL_MS;
    if (cached) {
      await loadReviewDetail(route, signal);
      return state.value;
    }
    try {
      // 次要数据并行取；拿不到只是少块内容，不该把整页拖成错误卡。
      const extras = Promise.all([
        api('camp/config', { signal }).catch(() => ({ players: [] })),
        // 英雄图标与阵容：拿不到时只是不显示头像，不影响主流程
        api('catalog', { signal }).catch(() => ({ entries: [] })),
        api('studio/view/matches', { signal }).catch(() => ({ matches: [] })),
        // 截图 / 录屏 / 回放三块：同一个采集页里的页签，一起取，切换不再请求
        api('postgame/images', { signal }).catch(() => ({ images: [], groups: [] })),
        api('recordings', { signal }).catch(() => ({ recordings: [], jobs: [] })),
        api('ocr/status', { signal }).catch(() => ({})),
        api('ocr/install', { signal }).catch(() => null),
        api('replays', { signal }).catch(() => ({ replays: [] })),
        // 回放补拉：按钮要显示「还能补几局」，拿不到就退回 0，不影响主流程。
        api('official/coverage', { signal }).catch(() => null),
      ]);
      /* 两个核心接口分开取：只挂审查列表时页面照常铺开（降级），
         不会因为一半数据没回来就把授权、拉取、OCR 全藏起来。
         camp/sync 挂了才是整页不可信 —— 授权、选手、已同步对局都从它来。 */
      const [channelsResult, syncResult] = await Promise.allSettled([
        api('channels', { signal }),
        api('camp/sync', { signal }),
      ]);
      if (syncResult.status === 'rejected') throw syncResult.reason;
      const sync = syncResult.value;
      // camp/sync 会补齐历史详情并自动通过完整对局；如果这次确实写了，
      // channels 可能比它先返回，再读一次保证首屏就是最新状态。
      const backfilled = Number(sync?.backfill?.created || 0);
      const backfillSaved = Number(sync?.backfill?.saved || 0);
      const finalized = Number(sync?.finalize?.passed || 0);
      let channels;
      if (channelsResult.status === 'fulfilled') {
        channels = channelsResult.value;
        if (backfilled > 0 || finalized > 0) channels = await api('channels', { signal });
      } else {
        channels = { channels: [] };
        if (!channelsResult.reason?.unavailable) throw channelsResult.reason;
      }
      const [config, catalog, matchesView, shots, recordings, ocrStatus, ocrInstall, replays, coverage] = await extras;
      // 保存一份，供写操作后局部重绘（paint）使用
      state.value = { channels, sync, config, catalog, matchesView, shots, recordings,
        ocrStatus, ocrInstall, replays, officialCoverage: coverage };
      state.loadedAt = Date.now();
      // 后台同步不会因为刷新页面而停：首屏发现还在跑，就把进度条接回来继续轮询。
      resumeSyncIfRunning(sync);
      hydrateSections();
      await loadReviewDetail(route, signal);
      state.degraded = channelsResult.status === 'rejected' ? '对局审查列表' : '';
      state.failure = null;
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
      /* 网络层断开交给 app.js 的全局重连（它会自动重新加载这一页）；
         这里只处理接口层「回来了但没这个地址」。 */
      if (!error?.unavailable) throw error;
      /* 静态资源与路由表可能短暂错配：先静默重试，别急着把整页换成错误卡。 */
      if (signal?.aborted) return { unavailable: true, failure: state.failure };
      if (unavailableRetries < 3) {
        unavailableRetries += 1;
        await new Promise((resolve) => setTimeout(resolve, 300 * 2 ** (unavailableRetries - 1)));
        if (!signal?.aborted) return load(_name, _key, signal);
      }
      unavailableRetries = 0;
      state.value = null;
      state.failure = await classifyFailure();
      return { unavailable: true, failure: state.failure };
    }
  }

  /** 把三块素材数据交给 sources-page，并约定「重绘 / 重取」都回到采集页。 */
  function hydrateSections() {
    const pages = sourcePages();
    if (!pages?.hydrate) return;
    pages.hydrate({
      shots: sourceValue('shots'),
      videos: sourceValue('videos'),
      replays: sourceValue('replays'),
    }, {
      repaint: () => paint(),
      reload: () => reloadSections(),
    });
  }

  function sourceValue(name) {
    const value = state.value || {};
    const channels = value.channels || { channels: [] };
    if (name === 'shots') {
      return { images: value.shots, channels,
        status: value.ocrStatus || {}, install: value.ocrInstall || null };
    }
    if (name === 'videos') {
      return { recordings: value.recordings, channels,
        status: value.ocrStatus || {}, install: value.ocrInstall || null };
    }
    return { replays: value.replays, channels };
  }

  /** 素材页上的上传 / 补采结束后重取这三块（不动营地与目录）。 */
  async function reloadSections() {
    if (!state.value) return;
    const [shots, recordings, replays, ocrStatus, ocrInstall] = await Promise.all([
      api('postgame/images').catch(() => state.value.shots),
      api('recordings').catch(() => state.value.recordings),
      api('replays').catch(() => state.value.replays),
      api('ocr/status').catch(() => state.value.ocrStatus),
      api('ocr/install').catch(() => state.value.ocrInstall),
    ]);
    state.value = { ...state.value, shots, recordings, replays, ocrStatus, ocrInstall };
    hydrateSections();
    paint();
  }

  /** 「审查」页签里点开某一条时的明细；重绘回到采集页，不再换成独立页。 */
  async function loadReviewDetail(route, signal) {
    const pages = reviewPages();
    if (!pages) return;
    if (route.tab !== 'review' || !route.id) {
      state.reviewValue = null;
      pages.hydrate(null);
      return;
    }
    pages.hydrate(async () => {
      // 保存 / 标记复核之后：重取这一条明细和审查列表，再重绘，别留在旧数据上。
      state.loadedAt = 0;
      await reloadValue().catch(() => {});
      paint(true);
    });
    try {
      state.reviewValue = await pages.load('review', route.id, signal);
    } catch {
      state.reviewValue = null;
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
    const shortMissing = missing.map((item) => item.label).slice(0, 4).join('、')
      + (missing.length > 4 ? ` 等 ${missing.length} 项` : '');
    return `<div class="capv-review-row${result === 1 ? ' is-win' : result === 2 ? ' is-loss' : ''}" data-chan-open="${esc(channel.id)}" title="点击进入缺失值审查">
      <span class="capv-review-score"><small>比分</small>${scoreCell(match)}</span>
      <span class="capv-review-main">
        <span class="capv-review-title">${resultText ? `<i class="capv-result ${result === 1 ? 'is-win' : 'is-loss'}">${resultText}</i>` : ''}<b>${esc(title)}</b></span>
        <small class="capv-review-meta" title="${esc(meta)}">${esc(meta || '—')}</small>
        ${missing.length ? `<small class="capv-review-missing" title="${esc(missingText)}">缺 ${esc(shortMissing)} · 点此逐条审查</small>` : ''}
      </span>
      <span class="capv-review-heroes">${heroesCell(channel, ctx, match)}</span>
      <span class="capv-review-side">
        ${sourceCell(channel)}
        <span class="capv-review-updated" title="最近更新">更新 ${esc(stamp(channel.updatedAt) || '—')}</span>
        <span class="capv-review-state">
          ${seed ? '<span class="capv-state is-seed" title="种子脚本写入的测试数据，不参与正式统计">验证</span>' : ''}
          <span class="capv-state ${chipClass}">${esc(label)}</span>
        </span>
      </span>
      <button class="capv-expand" data-chan-expand="${esc(channel.id)}" aria-expanded="false" aria-label="展开十人草稿">⌄</button>
    </div>
    <div class="capv-draft" data-draft-for="${esc(channel.id)}" hidden></div>`;
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
        '营地同步的局都已自动进入正式统计，没有需要补全的记录。');
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

  /** 原生 <dialog> 只负责打开：Esc / 焦点 / 背景 inert 交给浏览器，不自建焦点陷阱。 */
  function bindDialogs() {
    document.querySelectorAll('[data-cap-dialog-open]').forEach((button) => {
      if (button.dataset.boundDialog) return;
      button.dataset.boundDialog = '1';
      button.addEventListener('click', () => {
        const dialog = document.getElementById(button.dataset.capDialogOpen);
        if (dialog && !dialog.open) dialog.showModal();
      });
    });
    document.querySelectorAll('[data-cap-dialog-close]').forEach((button) => {
      if (button.dataset.boundDialogClose) return;
      button.dataset.boundDialogClose = '1';
      button.addEventListener('click', () => button.closest('dialog')?.close());
    });
  }

  function bindFilter() {
    bindDialogs();
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
      return `<div class="capv-day">
        <div class="capv-day-head"><b>${esc(date)}</b>
          <span>${rows.length} 条${missing ? '' : ' · 可一键通过'}</span></div>
        <div class="capv-review-rows">${rows.map((channel) => channelRow(channel, ctx)).join('')}</div>
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
      action = `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="auth-start">${glyph('shield', { size: 18 })}补充授权</button>`;
    } else if (!auth.authorized) {
      step = '第 1 步';
      title = '授权王者营地';
      desc = '用教练号扫码授权一次，凭证只存在本机。之后每天拉取都不必再扫。';
      action = `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="auth-start">${glyph('shield', { size: 18 })}扫码授权</button>`;
    } else if (!players.length) {
      step = '第 2 步';
      title = '绑定一位选手的营地 ID';
      desc = '挑每场必上的号（通常是队长）。让他在王者营地分享任意一局战绩并复制链接，粘贴到下方即可自动解析。';
 
      action = `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="focus-player">${glyph('pick', { size: 18 })}去添加</button>`;
    } else if (!state.list) {
      step = '第 3 步';
      title = '拉取最近对局';
      desc = `读取 ${players.length} 位选手的最近战绩，按对局去重后让你勾选；进行中的对局不包含在内。`;
      action = `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="pull">${glyph('refresh', { size: 18 })}拉取对局</button>`;
    } else if (Object.keys(state.checked).length) {
      const count = Object.keys(state.checked).length;
      step = '第 4 步';
      title = `同步所选 ${count} 局`;
      desc = '同步后无缺失值的对局会直接进入正式统计；只有缺英雄或面板字段的局才进入「缺失值审查」。';
      action = `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="import">${glyph('export', { size: 18 })}同步 ${count} 局</button>`;
    } else {
      step = '已完成';
      title = '今天没有需要同步的新对局';
      desc = pending
        ? `还有 ${pending} 条在缺失值审查${missing ? `，其中 ${missing} 条有缺失值` : ''}；无缺失的局已直接进入正式统计。`
        : '无缺失值的对局都已进入正式统计。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="ds-btn ds-btn-primary hero-cta" data-capture-action="scroll-channels">${glyph('book', { size: 18 })}查看 ${pending} 条</button>`
        : '';
    }

    const syncText = ctx.daysAgo === null ? '还没拉取过'
      : ctx.daysAgo === 0 ? '今天拉取过' : `${ctx.daysAgo} 天前拉取`;
    const syncShort = ctx.daysAgo === null ? '还没拉取过'
      : ctx.daysAgo === 0 ? '今天' : `${ctx.daysAgo} 天前`;
    const stepNo = (step.match(/第\s*(\d+)\s*步/) || [])[1] || '';
    const fact = (ok, label, value) => `<span class="capv-fact">
      <i class="capv-dot ${ok ? 'is-ok' : 'is-idle'}" aria-hidden="true"></i>
      <span>${esc(label)}</span><b>${esc(value)}</b></span>`;

    return `<section class="capv-next" data-tour="collect-hero">
      <div class="capv-next-copy">
        <span class="capv-kicker">下一步 · ${esc(step)}</span>
        <h2>${esc(title)}</h2>
        ${expired ? `<p class="capv-hint is-warn">${glyph('warning', { size: 18 })}<span>${esc(issue)}</span></p>` : ''}
        <div class="capv-facts">
          ${fact(auth.authorized && !expired, '营地授权', expired ? '失效' : auth.authorized ? '正常' : '未授权')}
          ${fact(players.length > 0, '营地选手', `${fmt(players.length)} 位`)}
          ${fact(!pending, '待审查', `${fmt(pending)} 条`)}
          <span class="capv-fact is-plain"><i class="capv-dot is-idle" aria-hidden="true"></i><span>上次拉取</span><b>${esc(syncShort)}</b></span>
        </div>
      </div>
      <div class="capv-next-side">
        <span class="capv-next-num" aria-hidden="true">${stepNo ? stepNo.padStart(2, '0') : '✓'}</span>
        ${action ? `<div class="capv-next-action">${action}</div>` : ''}
        ${pending && autoPassed ? `<small class="capv-next-note">${fmt(autoPassed)} 局已自动进入正式统计</small>` : ''}
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

    // 选手行：窄卡与展开管理共用。data-* 原样保留，事件仍由 features.js 统一分发。
    const playerRow = (player, manage = false) => {
      const off = player.enabled === false;
      const name = player.nickname || '未命名';
      return `<div class="capv-player${off ? ' is-off' : ''}">
        <span class="capv-avatar" aria-hidden="true">${esc(name.replace(/^选手\s*/, '').slice(0, 1) || '选')}</span>
        <span class="capv-player-copy"><b>${esc(name)}</b><small>营地 ID ${text(player.campUserId)}</small></span>
        ${manage ? `<span class="capv-player-actions">
          <button type="button" class="capv-textbtn" data-capture-action="player-rename" data-camp-user="${esc(player.campUserId)}">改名</button>
          <button type="button" class="capv-textbtn is-danger" data-capture-action="player-remove" data-camp-user="${esc(player.campUserId)}" aria-label="移除选手 ${esc(name)}">移除</button>
        </span>` : ''}
        <label class="capv-switch" title="${off ? '当前跳过这个号' : '拉取对局时会读取这个号'}">
          <input type="checkbox" ${off ? '' : 'checked'} data-capture-action="player-toggle" data-camp-user="${esc(player.campUserId)}">
          <span aria-hidden="true"></span>
          <em>${off ? '跳过' : '拉取'}</em>
        </label>
      </div>`;
    };

    // 已经授权、也有选手时，连接收成右栏一张窄卡，首屏让给拉取列表。
    // 二维码展开时必须回到主栏，否则窄卡里看不到扫码图。
    if (ready && !expired && players.length && !state.connOpen && !state.qr) {
      return `<section class="capv-card capv-conn is-compact" data-tour="camp-connect">
        <header class="capv-conn-head">
          <div class="capv-conn-id">
            <i class="capv-dot is-ok" aria-hidden="true"></i>
            <div><h3>营地连接</h3><p>${esc(auth.nickname || '已登录')} · 营地 ID ${text(auth.userId)}</p></div>
          </div>
          <span class="capv-state is-ok">已授权</span>
        </header>
        <dl class="capv-facts-list">
          <div><dt>授权时间</dt><dd>${stamp(auth.loginAt) || '—'}</dd></div>
          <div><dt>拉取选手</dt><dd>${fmt(players.filter((p) => p.enabled !== false).length)} / ${fmt(players.length)} 位</dd></div>
        </dl>
        <div class="capv-players is-compact">${players.map((p) => playerRow(p, false)).join('')}</div>
        <footer class="capv-conn-foot">
          <button type="button" class="capv-link" data-capture-action="conn-toggle">全部管理 <span aria-hidden="true">→</span></button>
          <details class="capv-menu">
            <summary class="capv-link is-muted">连接管理</summary>
            <div class="capv-menu-pop">
              <button type="button" data-capture-action="auth-check" ${checking ? 'disabled' : ''}>${checking ? '检测中…' : '检测授权'}</button>
              <button type="button" data-capture-action="auth-start">重新扫码</button>
              <button type="button" class="is-danger" data-capture-action="auth-clear">删除凭证</button>
            </div>
          </details>
        </footer>
      </section>`;
    }

    // 连接管理收进原生 details 菜单：检测/重扫是次级操作，删除凭证是危险操作（标红、不占常驻位置）。
    const connMenu = `<details class="capv-menu">
      <summary class="capv-link is-muted">连接管理 <span aria-hidden="true">⌄</span></summary>
      <div class="capv-menu-pop">
        <button type="button" data-capture-action="auth-check" ${checking ? 'disabled' : ''}>${checking ? '检测中…' : '检测授权'}</button>
        <button type="button" data-capture-action="auth-start">${expired ? '补充授权' : '重新扫码'}</button>
        <button type="button" class="is-danger" data-capture-action="auth-clear">删除凭证</button>
      </div>
    </details>`;
    let actions;
    if (!ready) {
      /* 首次授权的主按钮在上面的「下一步」卡；这里是同一动作的描边主按钮入口。 */
      actions = `<button class="ds-btn ds-btn-primary" type="button" data-capture-action="auth-start">${icon('search')} 扫码授权</button>`;
    } else {
      actions = `<div class="capv-head-tools">${connMenu}
        ${players.length ? '<button class="capv-link" type="button" data-capture-action="conn-toggle">收起 <span aria-hidden="true">⌃</span></button>' : ''}</div>`;
    }

    // 授权失效时把「补充授权」放在最显眼的位置；二维码展开后让出位置给扫码。
    const alert = expired && !state.qr
      ? `<div class="capv-alert" role="alert">
          <i class="capv-dot is-warn" aria-hidden="true"></i>
          <div class="capv-alert-copy"><b>营地授权已失效，拉取已暂停</b>
            <p>${esc(issue)}重新扫码补充授权后即可继续拉取；已进入正式统计的数据不受影响。</p></div>
          <button class="ds-btn ds-btn-primary" type="button" data-capture-action="auth-start">${glyph('shield', { size: 18 })}补充授权</button>
        </div>`
      : '';

    let authBody;
    if (state.qr) {
      authBody = `<div class="capv-auth-box is-qr">
        <div class="capv-qr"><img src="data:image/png;base64,${esc(state.qr.qrcodeBase64 || '')}" alt="营地授权二维码"></div>
        <div class="capv-qr-copy">
          <span class="capv-kicker">等待扫码</span>
          <b>用王者营地 App 扫一扫</b>
          <p>在手机上确认授权，页面会自动继续。</p>
          <p class="capv-qr-status" role="status">${esc(state.notice?.message || '等待扫码…')}</p>
          <button type="button" class="capv-link" data-capture-action="auth-cancel">取消这次授权</button>
        </div>
      </div>`;
    } else if (expired) {
      authBody = `<div class="capv-auth-box is-warn">
        <div class="capv-auth-top"><i class="capv-dot is-warn" aria-hidden="true"></i><span class="capv-state is-warn">授权失效</span></div>
        <b class="capv-auth-name">${esc(auth.nickname || '已登录')}</b>
        <p>营地 ID ${text(auth.userId)}</p>
        <div class="capv-auth-meta">${stamp(auth.loginAt) ? `<span>授权于 ${esc(stamp(auth.loginAt))}</span>` : ''}<span>拉取已暂停</span></div>
      </div>`;
    } else if (ready) {
      authBody = `<div class="capv-auth-box is-ok">
        <div class="capv-auth-top"><i class="capv-dot is-ok" aria-hidden="true"></i><span class="capv-state is-ok">已授权</span>${state.authProbe?.valid === false ? '<span class="capv-state is-warn">最近检测未通过</span>' : ''}</div>
        <b class="capv-auth-name">${esc(auth.nickname || '已登录')}</b>
        <p>营地 ID ${text(auth.userId)}</p>
        <div class="capv-auth-meta">
          ${stamp(auth.loginAt) ? `<span>授权于 ${esc(stamp(auth.loginAt))}</span>` : ''}
          ${checkedAt ? `<span>最近检测 ${esc(stamp(checkedAt))}</span>` : ''}
          <span>凭证只存在本机</span>
        </div>
      </div>`;
    } else {
      authBody = `<div class="capv-auth-box">
        <div class="capv-auth-top"><i class="capv-dot is-idle" aria-hidden="true"></i><span class="capv-state">未授权</span></div>
        <b class="capv-auth-name">还没有营地凭证</b>
        <p>扫码授权后才能拉取选手的最近对局；凭证只存在本机，不会上传。</p>
      </div>`;
    }

    // 选手白名单：一行一个选手，勾选 / 改名 / 移除都在行内。
    // 所有 data-* 与 data-camp-user 原样保留，事件委托在 features.js 按字符串分发。
    const list = players.length
      ? `<div class="capv-players is-manage">${players.map((player) => playerRow(player, true)).join('')}</div>`
      : '<p class="capv-empty-copy">还没有绑定选手。点右上「批量添加」，填入营地 ID 或分享链接即可。</p>';

    // 批量添加与操作说明都移进原生 <dialog>：Esc / 焦点由浏览器管理，不自造焦点陷阱。
    const playersBody = `<div class="capv-players-box" data-tour="camp-players">
      <header class="capv-subhead">
        <div><h3>选手白名单</h3><p>${fmt(players.length)} 位 · 勾选 ${fmt(players.filter((p) => p.enabled !== false).length)} 位</p></div>
        <div class="capv-subhead-actions">
          <span class="capv-hint" data-tour="camp-link">获取分享链接
            <button class="capv-help" type="button" data-cap-dialog-open="cap-help-dialog" aria-label="查看获取链接的帮助">${glyph('book', { size: 18 })}</button></span>
          <button class="ds-btn ds-btn-secondary" type="button" data-cap-dialog-open="cap-add-dialog">${glyph('pick', { size: 18 })}批量添加</button>
        </div>
      </header>
      <p class="capv-hint is-warn">${glyph('warning', { size: 18 })}战绩对教练不可见时，需把教练加入营地白名单。</p>
      ${list}
      <dialog class="ds-help-dialog" id="cap-help-dialog" aria-labelledby="cap-help-title">
        <div class="ds-dialog-head"><h2 id="cap-help-title">怎么拿到营地分享链接？</h2>
          <form method="dialog"><button class="ds-dialog-x" value="cancel" autofocus aria-label="关闭帮助">×</button></form></div>
        <div class="ds-dialog-body ds-help-body">
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
        <div class="ds-dialog-foot"><form method="dialog"><button class="ds-btn ds-btn-secondary" value="ok">知道了</button></form></div>
      </dialog>
      <dialog class="ds-add-dialog" id="cap-add-dialog" aria-labelledby="cap-add-title">
        <div class="ds-dialog-head"><h2 id="cap-add-title">批量添加选手</h2>
          <form method="dialog"><button class="ds-dialog-x" value="cancel" aria-label="关闭批量添加">×</button></form></div>
        <form data-capture-form="player" class="conn-form ds-player-form">
          <div class="ds-dialog-body">
            <label class="ds-field-label" for="cap-identities">营地 ID 或分享链接</label>
            <textarea id="cap-identities" name="identity" rows="6" autocomplete="off" spellcheck="false" autofocus
              placeholder="一行一个营地 ID，也可以直接粘贴多条分享链接"></textarea>
          </div>
          <div class="ds-dialog-foot">
            <button class="ds-btn ds-btn-quiet" type="button" data-cap-dialog-close>${glyph('ban', { size: 18 })}取消</button>
            <button class="ds-btn ds-btn-primary" type="submit">${glyph('pick', { size: 18 })}批量添加</button>
          </div>
        </form>
      </dialog>
    </div>`;

    return `<section class="capv-card capv-conn is-manage" data-tour="camp-connect">
      <header class="capv-panel-head">
        <div class="capv-panel-title">
          <span class="capv-kicker">授权与选手</span>
          <h2>营地连接</h2>
        </div>
        ${actions}
      </header>
      ${alert}
      <div class="capv-conn-body">
        <div class="capv-auth-col">${authBody}</div>
        <div class="capv-players-col">${playersBody}</div>
      </div>
    </section>`;
  }

  // ---------------- 对局列表 ----------------

  /** 上一次同步到底进了多少局：写入 / 待审 / 营地无详情 / 没拉全，一直留在卡片里。 */
  function summaryLine() {
    const s = state.summary;
    if (!s) return '';
    const parts = [`<b>上次同步 ${fmt(s.total)} 局</b>`];
    parts.push(`<span class="capv-sum-ok">${fmt(s.saved)} 局进入正式统计</span>`);
    if (s.review) parts.push(`<span class="capv-sum-warn">${fmt(s.review)} 局待缺失值审查</span>`);
    if (s.unsupported) parts.push(`<span class="capv-sum-warn">${fmt(s.unsupported)} 局营地无详情</span>`);
    if (s.failed) parts.push(`<span class="capv-sum-warn">${fmt(s.failed)} 局没拉全，可重试</span>`);
    const problems = (s.problems || []).filter(Boolean).slice(0, 2);
    return `<div class="capv-summary${s.failed && !s.saved && !s.unsupported ? ' is-error' : ''}">
      <span class="capv-summary-main">${parts.join('')}</span>
      ${problems.length ? `<small>${esc(problems.join('；'))}</small>` : ''}
    </div>`;
  }

  function pullBlock(players) {
    const allPlayers = players;
    players = players.filter((player) => player.enabled !== false);
    const list = state.list;
    const checked = Object.keys(state.checked).length;
    const blocked = Boolean(state.authIssue);
    const blockedHint = blocked
      ? `<p class="capv-hint is-warn">${glyph('warning', { size: 18 })}营地授权已失效，请先补充授权。</p>`
      : '';
    const moreAction = state.pullHasMore
      ? `<button class="ds-btn ds-btn-secondary" type="button" data-capture-action="pull-more" ${state.busy ? 'disabled' : ''}>继续拉取更早</button>`
      : '';
    const hasList = Boolean(list && list.length);
    const coverage = state.value?.officialCoverage || {};
    const fillable = Number(coverage.fillable) || 0;
    const lastSync = (state.value?.sync?.details || []).reduce(
      (max, detail) => Math.max(max, Number(detail.syncedAt) || 0), 0);
    const daysAgo = lastSync ? Math.floor((Date.now() / 1000 - lastSync) / 86400) : null;
    const lastLabel = daysAgo === null ? '还没拉过' : daysAgo === 0 ? '今天' : `${daysAgo} 天前`;
    const channels = state.value?.channels?.channels || [];
    const autoPassed = channels.filter((channel) => channel.saved?.status === 'saved').length;
    const needReview = channels.filter((channel) => channel.saved?.status !== 'saved').length;

    // 全选 / 补拉 / 重拉都是次操作；唯一的实心按钮留给「同步所选」。
    const right = `<div class="capv-actions">
      ${blocked ? `<button class="ds-btn ds-btn-primary" type="button" data-capture-action="auth-start">${glyph('shield', { size: 18 })}补充授权</button>` : ''}
      ${fillable ? `<button class="ds-btn ds-btn-secondary" type="button" data-capture-action="backfill-official" ${state.busy ? 'disabled' : ''} title="按较慢速度逐局补拉，避免被营地限流；每次最多 10 局">${state.busy === 'backfill' ? '补拉回放中…' : `补拉缺失回放 ${fillable} 局`}</button>` : ''}
      ${moreAction}
      ${hasList ? `<button class="ds-btn ds-btn-quiet" type="button" data-capture-action="check-all" ${list.some((entry) => !entry.imported && !entry.channelReady && !campDetailExpired(entry)) ? '' : 'disabled'}>全选</button>
      <button class="ds-btn ds-btn-quiet" type="button" data-capture-action="check-none" ${checked ? '' : 'disabled'}>取消勾选</button>
      <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="pull" ${state.busy === 'pull' || !players.length || blocked ? 'disabled' : ''}>${state.busy === 'pull' ? '正在拉取…' : '重新拉取'}</button>
      <button class="ds-btn ${checked ? 'ds-btn-primary' : 'ds-btn-secondary'}" type="button" data-capture-action="import" ${checked && !state.busy ? '' : 'disabled'}>${glyph('export', { size: 18 })}${state.busy === 'import' ? `同步中 ${checked} 局…` : `同步所选 ${checked} 局`}</button>` : ''}
    </div>`;

    const statsStrip = `<div class="capv-metrics">
      <span class="capv-metric"><small>上次拉取</small><b>${esc(lastLabel)}</b></span>
      <span class="capv-metric"><small>已进正式统计</small><b>${fmt(autoPassed)}<em>局</em></b></span>
      ${needReview
        ? `<button class="capv-metric is-todo" type="button" data-capture-action="scroll-channels" title="跳转到对局审查中的待办条目"><small>待补全 · 待办</small><b>${fmt(needReview)}<em>条</em></b><i aria-hidden="true">→</i></button>`
        : `<span class="capv-metric"><small>待补全</small><b>0<em>条</em></b></span>`}
      <span class="capv-metric"><small>已绑定营地号</small><b>${players.length}<em>个</em></b></span>
    </div>`;

    const chip = blocked ? '<span class="capv-state is-warn">授权失效</span>'
      : !allPlayers.length ? '<span class="capv-state">待绑定选手</span>'
        : !players.length ? '<span class="capv-state is-warn">已全部跳过</span>'
          : hasList ? '<span class="capv-state is-ok">已读取</span>'
            : '<span class="capv-state">可拉取</span>';

    const panel = (body, headActions = right) => `<section class="capv-card capv-pull" data-tour="camp-pull">
      <header class="capv-panel-head">
        <div class="capv-panel-title">
          <div class="capv-title-line"><span class="capv-kicker">营地同步 · 第 3 步</span>${chip}</div>
          <h2>拉取对局</h2>
        </div>
        ${headActions}
      </header>
      ${statsStrip}
      <div class="capv-pull-body">${body}</div>
    </section>`;

    const flow = `${summaryLine()}<div data-cap-progress>${progressBar()}</div>`;

    const authReady = Boolean(state.value?.sync?.auth?.authorized) && !state.authIssue;
    if (!allPlayers.length) {
      return panel(`<div class="capv-empty">
        <span class="capv-empty-glyph">${icon('players')}</span>
        <div class="capv-empty-copy"><b>${authReady ? '还没有可拉取的选手' : '先完成营地授权'}</b>
          <p>${authReady
            ? '先在「营地连接」里绑定一位每场都上的号，之后拉取会自动带上双方十人面板。'
            : '扫码授权后用一位每场都上的号建立白名单，再回来拉取最近对局。'}</p></div>
        <button class="ds-btn ds-btn-primary" type="button" data-capture-action="${authReady ? 'focus-player' : 'auth-start'}">${authReady ? '去绑定选手' : '扫码授权'}</button>
      </div>${flow}`);
    }
    if (!players.length) {
      const offNames = allPlayers.map((p) => p.nickname || p.campUserId).join('、');
      return panel(`<div class="capv-empty is-warn">
        <span class="capv-empty-glyph">${icon('players')}</span>
        <div class="capv-empty-copy"><b>所有选手都取消了拉取</b><p>当前白名单里 ${esc(offNames)} 都被跳过了。到「营地连接」里打开至少一个号再拉取。</p></div>
        <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="conn-toggle">去营地连接</button>
      </div>${flow}`);
    }

    if (!list) {
      const stale = daysAgo !== null && daysAgo >= 1;
      const note = [state.listNote || '',
        stale ? '上次拉取已超过一天，训练赛后记得再拉一次。' : ''].filter(Boolean).join(' ');
      return panel(`${flow}${blockedHint}<div class="capv-empty">
        <span class="capv-empty-glyph">${icon('ingest')}</span>
        <div class="capv-empty-copy"><b>${daysAgo === null ? '还没有拉取过对局' : `上次拉取在${lastLabel}`}</b>
          <p>${esc(note || '营地只保留最近 30 天的对局详情；训练赛结束后当天拉取，才能自动补全十人面板。')}</p></div>
        <button class="ds-btn ds-btn-primary" type="button" data-capture-action="pull" ${state.busy === 'pull' || blocked ? 'disabled' : ''}>${glyph('refresh', { size: 18 })}${state.busy === 'pull' ? '正在拉取…' : '拉取最近对局'}</button>
      </div>`);
    }
    if (!list.length) {
      return panel(`${flow}${blockedHint}<div class="capv-empty">
        <span class="capv-empty-glyph">${icon('ingest')}</span>
        <div class="capv-empty-copy"><b>最近没有可拉取的新对局</b><p>${esc(state.listNote || '选手最近没有新的战绩；营地只保留最近 30 天的对局详情。')}</p></div>
        <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="pull" ${state.busy === 'pull' || blocked ? 'disabled' : ''}>${glyph('refresh', { size: 18 })}重新拉取</button>
      </div>`);
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
      const stateChip = already ? '<span class="capv-state is-ok">已进统计</span>'
        : inReview ? '<span class="capv-state is-warn" title="十人面板已挂上，等缺失值审查处理">待审查</span>'
          : expired ? '<span class="capv-state" title="营地只提供最近一个月的战局详情；这局要走截图或录屏「新录入一局」">营地无详情</span>'
            : needsDetail ? '<span class="capv-state is-warn" title="审查记录已建，但十人面板还没挂上；同步会补详情">待补详情</span>'
              : needsChannel ? '<span class="capv-state is-warn" title="详情已缓存，同步时不用重新下载，只补建审查记录">补建记录</span>'
                : '<span class="capv-state">待同步</span>';
      const titleBits = [mode, hero ? `${hero} ${kda}` : ''].filter(Boolean).join(' · ');
      const metaBits = [matchMinutes(entry.usedTime),
        entry.gradeGame ? `评分 ${entry.gradeGame}` : '', entry.roleJobName || '',
        extra].filter(Boolean).join(' · ');
      return `<label class="capv-game${!selectable ? ' is-in' : ''}">
        <input type="checkbox" data-capture-check="${esc(seq)}" ${checkedAttr} ${!selectable ? 'disabled' : ''}>
        <span class="capv-game-date"><b>${esc(when.day || '--')}</b><small>${esc(when.clock || '时间未知')}</small></span>
        <span class="capv-game-main">
          <span class="capv-game-title">${resultChip(entry)}<b>${esc(titleBits)}</b></span>
          <small title="${esc(bits)}">${esc(metaBits)}</small>
        </span>
        <span class="capv-game-side">${stateChip}</span>
      </label>`;
    };

    // 按「等待同步 / 已在审查 / 已进统计 / 营地无详情」分桶：后两类收进折叠，不占篇幅。
    const pendingRows = list.filter((entry) => !entry.imported && !entry.channelReady
      && !campDetailExpired(entry));
    const reviewRows = list.filter((entry) => !entry.imported && entry.channelReady);
    const importedRows = list.filter((entry) => entry.imported);
    const expiredRows = list.filter((entry) => !entry.imported && !entry.channelReady
      && campDetailExpired(entry));

    const fold = (rows, label, extra = '') => (rows.length
      ? `<details class="capv-fold-list${extra}"><summary><span>${esc(label)}</span><em>${fmt(rows.length)} 局</em><i aria-hidden="true">⌄</i></summary>
          <div class="capv-games">${rows.map(entryRow).join('')}</div></details>`
      : '');

    const expiredCallout = expiredRows.length ? `<div class="capv-callout" role="status">
      <span class="capv-callout-icon" aria-hidden="true">!</span>
      <div class="capv-callout-copy">
        <b>${fmt(expiredRows.length)} 局超出营地详情窗口</b>
        <p>营地只保留最近一个月的对局详情（手机营地 App 里也打不开）。这些局不是补采，要用截图或录屏「新录入一局」直接建档。</p>
      </div>
      <div class="capv-actions">
        <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="backfill-open">${glyph('capture', { size: 18 })}新录入一局</button>
        <button class="ds-btn ds-btn-quiet" type="button" data-capture-action="jump-ocr">去截图 / 录屏 →</button>
      </div>
    </div>` : '';

    const pendingList = pendingRows.length
      ? `<div class="capv-games">${pendingRows.map(entryRow).join('')}</div>`
      : `<div class="capv-hint capv-hint-empty">${glyph('victory', { size: 28 })}<b>没有待同步的新局</b></div>`;

    // 列表一长，顶部的「全部取消勾选」要滚回去才点得到；底下再放一条同样的出口。
    const clearBar = checked
      ? `<div class="capv-selection-bar">
          <span>已勾选 <b>${fmt(checked)}</b> 局</span>
          <button class="ds-btn ds-btn-quiet" type="button" data-capture-action="check-none">全部取消</button>
          <button class="ds-btn ds-btn-primary" type="button" data-capture-action="import" ${state.busy ? 'disabled' : ''}>${glyph('export', { size: 18 })}${state.busy === 'import' ? `同步中 ${checked} 局…` : `同步所选 ${checked} 局`}</button>
        </div>`
      : '';

    const footNote = state.busy === 'import' ? '正在同步并写入正式统计…' : (state.listNote || '');
    return panel(`${flow}${expiredCallout}${pendingList}${clearBar}`
      + fold(importedRows, '已进正式统计')
      + fold(expiredRows, '营地无详情（超过一个月）', ' is-warn')
      + fold(reviewRows, '已在缺失值审查')
      + (footNote ? `<p class="capv-hint">${esc(footNote)}</p>` : ''));
  }

  // ---------------- 页面 ----------------

  /** 营地拿不到的老对局：先新录入一局（建通道），再去截图/录屏页把识别结果录入到这一局。 */
  function backfillPanel() {
    if (!state.backfillOpen) {
      return `<div class="capv-backfill-intro">
        <div><b>营地一个月窗口外的老局</b>
          <p>超过一个月、或选手隐藏了战绩的局，营地没有可补采的通道；先在这里建一局，再去截图 / 录屏页把识别结果录进这一局。</p></div>
        <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="backfill-open">${glyph('capture', { size: 18 })}新录入一局</button>
      </div>`;
    }
    return `<div class="capv-backfill" data-tour="camp-backfill">
      <div class="capv-backfill-head">
        <div><h3>新录入一局</h3></div>
        <button class="ds-btn ds-btn-quiet" type="button" data-capture-action="backfill-close">${glyph('ban', { size: 18 })}取消</button>
      </div>
      <div class="capv-backfill-fields">
        <label>比赛日期<input type="date" data-backfill="date" value="${today()}"></label>
        <label>训练组 / 对手<input type="text" data-backfill="session" maxlength="40" autocomplete="off" placeholder="如 0917 训练赛 / 对手名"></label>
        <button class="ds-btn ds-btn-primary" type="button" data-capture-action="backfill-create" ${state.busy ? 'disabled' : ''}>
          ${state.busy === 'backfill' ? '正在建…' : '建好这局，去传截图'}</button>
      </div>
      <p class="capv-hint">${glyph('book', { size: 18 })}<a href="/assets/collection-guide.html?section=screenshots" target="_blank" rel="noopener">查看拍摄要求</a></p>
    </div>`;
  }

  /** 按当前状态给出「今天这一步该做什么」，只显示一个动作。 */
  function guideCard(auth, players, pending) {
    let title;
    let desc;
    let action = '';

    if (!auth.authorized) {
      title = '第 1 步 · 授权王者营地';
      desc = '用教练号扫码授权一次，凭证只存在本机。之后每天拉取都不必再扫。';
      action = '<button class="ds-btn ds-btn-primary" type="button" data-capture-action="auth-start">扫码授权</button>';
    } else if (!players.length) {
      title = '第 2 步 · 绑定一位选手的营地 ID';
      desc = '挑每场必上的号（通常是队长）。让他在王者营地分享任意一局战绩到微信并复制链接，'
        + '把链接粘贴到下方「营地选手」的输入框即可，会自动解析出 ID。一局详情自带双方十人面板，所以一个号就够。';
      action = '<button class="ds-btn ds-btn-secondary" type="button" data-capture-action="focus-player">去添加</button>';
    } else if (!state.list) {
      title = '第 3 步 · 拉取最近对局';
      desc = `会读取 ${players.length} 位选手的最近战绩，按对局去重后让你勾选；进行中的对局不会包含在内。`;
      action = '<button class="ds-btn ds-btn-primary" type="button" data-capture-action="pull">拉取对局</button>';
    } else if (Object.keys(state.checked).length) {
      const count = Object.keys(state.checked).length;
      title = `第 4 步 · 同步所选 ${count} 局`;
      desc = '同步后无缺失值的对局直接进入正式统计；只有缺英雄或面板字段的局才进缺失值审查。';
      action = `<button class="ds-btn ds-btn-primary" type="button" data-capture-action="import">同步所选 ${count} 局</button>`;
    } else {
      title = '今天没有需要同步的新对局';
      desc = pending
        ? `还有 ${pending} 条在缺失值审查，可以在下面逐条确认。`
        : '无缺失值的对局都已进入正式统计。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="ds-btn ds-btn-secondary" type="button" data-capture-action="scroll-channels">查看 ${pending} 条</button>`
        : '';
    }

    return `<section class="guide-card" data-guide>
      <div class="guide-body"><h2>${esc(title)}</h2></div>
      ${action ? `<div class="guide-action">${action}</div>` : ''}
    </section>`;
  }

  /* 读不到采集数据时的那张卡：先说清是哪一种「读不到」，再给一个真能走通的下一步。
     以前只有「营地数据暂时读不到 + 重新读取」，开错地址的人会一直点同一个不会生效的按钮。 */
  function unavailableCard(failure) {
    const cause = failure?.cause || 'unknown';
    const origin = esc(failure?.origin || location.origin);
    let title = '营地数据暂时读不到';
    let body = '工作台还没把数据返回来；点「重新读取」再试一次。';
    let actions = `<button class="primary" data-action="refresh">${glyph('refresh', { size: 18 })}重新读取</button>`;
    if (cause === 'not-workbench') {
      /* 这个地址背后没有工作台进程（预览 / 静态服务器就是这样）：换地址才有效。 */
      const host = location.hostname || '127.0.0.1';
      const workbench = `http://${host}:8766`;
      title = '这个地址没有采集数据';
      body = `你现在打开的是 <b>${origin}</b>，它只有页面、没有采集接口。`
        + `采集数据在工作台进程里，用「启动工作台」打开的地址重新进入即可，通常是 <b>${esc(workbench)}/</b>。`;
      actions = `<a class="primary" href="${esc(workbench)}/#ingest">去工作台</a>`
        + '<button class="control" data-action="refresh">重新读取</button>';
    } else if (cause === 'api-mismatch') {
      title = '采集接口没有响应';
      body = '工作台在线，但采集接口没返回数据。重启一次工作台（关掉窗口后重新双击「启动工作台」）通常就能恢复。';
    } else if (cause === 'offline') {
      title = '工作台没有响应';
      body = '工作台可能正在重启，或者还没启动。启动后这一页会自动重新读取，也可以现在手动再试一次。';
    }
    return `<div class="cap-page capv-page"><section class="capv-offline" role="status">
      <div class="capv-offline-main">
        <span class="capv-offline-dot" aria-hidden="true"></span>
        <div><span class="capv-kicker">采集服务</span><h2>${esc(title)}</h2><p>${body}</p></div>
      </div>
      <div class="capv-actions">${actions}</div>
    </section></div>`;
  }

  function view(value) {
    if (value?.unavailable) {
      /* 状态卡本身承担标题、原因与下一步；页面副标题仍说明这一页是做什么的，
         也不再摆「数据范围」——那个按钮在这时点了没有任何意义。 */
      return withPage('营地同步', '',
        unavailableCard(value.failure || state.failure), false, '', false);
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

    const notice = [
      /* 只有审查列表没读到：页面其余部分照常可用，别为了半边数据把整页停掉。 */
      state.degraded
        ? `<div class="capv-notice is-error" role="status">${esc(state.degraded)}暂时读不到，页面其余部分照常；点右上角刷新可重试。</div>`
        : '',
      state.notice
        ? `<div class="capv-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`
        : '',
    ].join('');

    // 授权正常 + 有选手时不再需要「下一步」引导：页面按 连接 → 拉取 → OCR → 审查 排。
    const ready = Boolean(auth.authorized) && !(auth.expired || state.authIssue);
    const compact = ready && players.length > 0;

    // 两条采集通道分开审查：营地字段齐全自动入库；截图/录屏 OCR 的局必须人工确认。
    const campChannels = pendingChannels.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) > 0);
    const ocrChannels = pendingChannels.filter((channel) => Number(channel.sourceStatus?.counts?.camp || 0) === 0);
    const passableChannels = ocrChannels.filter((channel) => !(channel.missing || []).length);

    const reviewActions = `<div class="capv-actions">
      <button class="ds-btn ds-btn-secondary" type="button" data-capture-action="backfill-open">${glyph('capture', { size: 18 })}新录入一局</button>
      ${passableChannels.length ? `<button class="ds-btn ds-btn-primary" type="button" data-capture-action="approve-clean" ${state.busy ? 'disabled' : ''}>
        ${state.busy === 'approve' ? '正在通过…' : `一键通过无缺失 ${passableChannels.length} 条`}</button>` : ''}
    </div>`;

    const flowBar = `<div class="capv-filterbar">
      <label class="capv-search">${icon('search')}
        <input type="search" data-ingest-query value="${esc(state.query)}"
          placeholder="搜索对手 / 训练组 / 英雄" aria-label="搜索对局审查"></label>
      <div class="capv-seg" role="group" aria-label="数据范围">
        <button data-ingest-scope="all" class="${state.scope === 'all' ? 'is-on' : ''}">全部 <i>${pendingChannels.length}</i></button>
        <button data-ingest-scope="real" class="${state.scope === 'real' ? 'is-on' : ''}">真实 <i>${pendingChannels.length - seedCount}</i></button>
        <button data-ingest-scope="seed" class="${state.scope === 'seed' ? 'is-on' : ''}">验证 <i>${seedCount}</i></button>
      </div>
      <div class="capv-seg" role="group" aria-label="时间范围">
        <button data-ingest-range="all" class="${state.range === 'all' ? 'is-on' : ''}">全部时间</button>
        <button data-ingest-range="7" class="${state.range === '7' ? 'is-on' : ''}">近 7 天</button>
        <button data-ingest-range="30" class="${state.range === '30' ? 'is-on' : ''}">近 30 天</button>
        <button data-ingest-range="custom" class="${state.range === 'custom' ? 'is-on' : ''}">自定义</button>
      </div>
      ${filtering ? '<button class="capv-clear" type="button" data-capture-action="clear-filter">清除筛选</button>' : ''}
    </div>
    ${state.range === 'custom' ? `<div class="capv-dates">
      <label>从<input type="date" data-ingest-from value="${esc(state.fromDate)}"></label>
      <label>到<input type="date" data-ingest-to value="${esc(state.toDate)}"></label>
    </div>` : ''}`;

    const campGroup = `<section class="capv-group${campChannels.length ? '' : ' is-empty'}">
      <header class="capv-group-head">
        <div class="capv-group-title"><b>王者营地</b>
          <span class="capv-state ${campChannels.length ? 'is-warn' : 'is-ok'}">${campChannels.length ? `${fmt(campChannels.length)} 条待补全` : '无需补全'}</span></div>
        <p>营地同步的局字段齐全就自动进正式统计；缺字段的留在这里补全后再入库。</p>
      </header>
      <div data-ingest-list="camp">${renderChannelList(filterChannels(campChannels), lookups(), filtering,
        '营地同步的局都已自动进入正式统计，没有需要人工审核的记录。')}</div>
    </section>`;

    const ocrGroup = `<section class="capv-group${ocrChannels.length ? '' : ' is-empty'}">
      <header class="capv-group-head">
        <div class="capv-group-title"><b>截图 / 录屏 OCR</b>
          <span class="capv-state ${ocrChannels.length ? 'is-warn' : 'is-ok'}">${ocrChannels.length ? `${fmt(ocrChannels.length)} 条待审核` : '无需审核'}</span></div>
        <p>OCR 识别的字段可能有缺，逐条确认后才能保存。</p>
      </header>
      <div data-ingest-list="ocr">${renderChannelList(filterChannels(ocrChannels), lookups(), filtering,
        '还没有截图 / 录屏新录入的局。营地一个月窗口外的老局在这里新录入。')}</div>
    </section>`;

    const reviewBlock = `<section class="capv-card capv-review-panel" data-tour="camp-flow">
      <header class="capv-panel-head">
        <div class="capv-panel-title">
          <div class="capv-title-line"><span class="capv-kicker">对局审查 · 第 5 步</span>
            <span class="capv-state ${pendingChannels.length ? 'is-warn' : 'is-ok'}">${pendingChannels.length ? `${fmt(pendingChannels.length)} 条待处理` : '已清空'}</span></div>
          <h2>对局审查</h2>
        </div>
        ${reviewActions}
      </header>
      <div class="capv-review-filters">${flowBar}</div>
      <div class="capv-review-groups">${campGroup}${ocrGroup}</div>
    </section>`;

    const connection = connectionBlock(auth, players);
    const work = pullBlock(players);
    const { tab, id } = routeParts();
    const shotGroups = value?.shots?.groups?.length || 0;
    const recordingCount = value?.recordings?.recordings?.length || 0;
    const replayCount = value?.replays?.replays?.length || 0;

    /* 一个采集页，六步做成页签：营地同步 → 截图 / 录屏（窗口外新录入）→ 回放
       → 审查 → 已采集对局。以前前四块是独立页面，链接互相跳、数据各取一遍。 */
    const collectedCount = (value?.matchesView?.matches || []).length;
    const tabs = [
      ['camp', '营地同步', '', '#ingest'],
      ['shots', '截图 OCR', shotGroups ? `${shotGroups} 组` : '', '#shots'],
      ['videos', '录屏', recordingCount ? `${recordingCount} 段` : '', '#videos'],
      ['replays', '回放', replayCount ? `${replayCount} 段` : '', '#replays'],
      ['review', '对局审查', pendingChannels.length ? `${pendingChannels.length} 条` : '', '#review'],
      ['imported', '已采集对局', collectedCount ? `${collectedCount} 局` : '', '#imported'],
    ];
    const tabBar = `<nav class="capv-tabs" aria-label="采集步骤">${tabs.map(([key, label, count, href], index) =>
      `<a class="capv-tab${tab === key ? ' is-on' : ''}" href="${href}"${tab === key ? ' aria-current="page"' : ''}>
        <span class="capv-tab-no" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span>
        <span class="capv-tab-name">${esc(label)}</span>
        ${count ? `<span class="capv-tab-count">${esc(count)}</span>` : ''}
      </a>`).join('')}</nav>`;

    const tiers = `<div class="capv-tiers">${SOURCE_TIERS.map(([name, tier, note, href]) => `<div class="capv-tier is-${tier.key}">
      <span class="capv-tier-tag">${esc(tier.label)}</span>
      <div class="capv-tier-copy"><b>${esc(name)}</b><small>${esc(note)}</small></div>
      ${href ? `<a class="capv-tier-go" href="${esc(href)}">打开 →</a>` : '<span class="capv-tier-go is-none">无需单独操作</span>'}
    </div>`).join('')}</div>`;

    const reviewTeaser = `<a class="capv-rail-card capv-todo${pendingChannels.length ? '' : ' is-clear'}" href="#review">
      <div class="capv-todo-head"><span class="capv-kicker">对局审查</span><span aria-hidden="true">→</span></div>
      <b class="capv-todo-num">${fmt(pendingChannels.length)}<em>条</em></b>
      <p>${pendingChannels.length
        ? `营地 ${fmt(campChannels.length)} 条 · 截图 / 录屏 ${fmt(ocrChannels.length)} 条`
        : '字段全部齐全，没有待处理记录'}</p>
    </a>`;

    const guide = `<details class="capv-rail-card capv-guide">
      <summary><div><span class="capv-kicker">素材说明</span><b>各类素材能补哪些数据</b></div><i aria-hidden="true">⌄</i></summary>
      ${tiers}
    </details>`;

    const connInRail = !state.connOpen && !state.qr;
    const backfillFold = `<details class="capv-panel-fold"${state.backfillOpen ? ' open' : ''}>
      <summary><span>补录历史对局</span><em>营地窗口外的老局</em><i aria-hidden="true">⌄</i></summary>
      <div class="capv-panel-fold-body">${backfillPanel()}</div>
    </details>`;

    const campPanel = compact
      ? `<div class="capv-layout">
          <div class="capv-main">${connInRail ? '' : connection}${work}${backfillFold}</div>
          <aside class="capv-rail">${connInRail ? connection : ''}${reviewTeaser}${guide}</aside>
        </div>`
      : `${heroCard({
        auth, players, pending: pendingChannels.length, missing: missingChannels.length,
        autoPassed, channels: list.length, daysAgo, compact,
      })}
        ${connection}
        ${work}
        ${backfillFold}
        <details class="capv-card capv-guide is-wide">
          <summary><div><span class="capv-kicker">素材说明</span><b>各类素材能补哪些数据</b></div><i aria-hidden="true">⌄</i></summary>
          ${tiers}
        </details>`;

    const embedded = (name) => `<div class="cap-embed" data-source-section="${name}">${
      sourcePages()?.body?.(name, sourceValue(name)) || ''}</div>`;

    const reviewPanel = id
      ? `<div class="cap-embed capv-embed cap-review" data-review-embed="${esc(id)}">${
        (reviewPages()?.snapshot?.(id) || state.reviewValue)
          ? reviewPages()?.body?.(id, reviewPages()?.snapshot?.(id) || state.reviewValue, true) || ''
          : '<p class="capv-hint">正在读取这一局的审查明细…</p>'}</div>`
      : reviewBlock;

    /* 已采集对局：库里已经落库的局。删掉后营地列表会重新标成可同步，
       再走一遍「营地同步」就能把这一局重爬回来。 */
    /* 已采集对局按采集时间从早到晚排。date 是 YYYY-MM-DD，startTime 是
       "MM-DD HH:MM"，拼成年-月-日 + 时刻即可按字符串比较（无时区偏移）。
       用 toSorted 返回副本，别改动 state.value 里的原始顺序。 */
    const collectedTime = (m) => {
      const day = String(m.date || '');
      const raw = String(m.startTime || '');
      const clock = raw.includes(' ') ? raw.slice(raw.indexOf(' ') + 1) : raw;
      return `${day} ${clock}`.trim();
    };
    const collectedCmp = (a, b) => {
      const ka = collectedTime(a);
      const kb = collectedTime(b);
      if (!ka) return 1;
      if (!kb) return -1;
      return ka.localeCompare(kb);
    };
    const collectedAll = value?.matchesView?.matches || [];
    const collectedRows = collectedAll.toSorted
      ? collectedAll.toSorted(collectedCmp)   // 不改动 state 里的原数组
      : collectedAll.slice().sort(collectedCmp); // 老浏览器兜底
    const heroIcons = new Map(
      (value?.catalog?.entries || [])
        .filter((entry) => entry.kind === 'hero' && entry.icon)
        .map((entry) => [entry.name, entry.icon]),
    );
    /* 跟单局分析同一套读法：时间 + 对手 + 胜负 + 双方英雄头像。
       采集通道、来源这些内部字段不再露给赛训组。 */
    const importPanel = `<section class="capv-card capv-collected">
      <div class="section-heading"><div><h2>已采集对局</h2>
        <p>${glyph('warning', { size: 18 })}删除会把这一局从对局库里真正删掉，阵容、BP 等关联数据一并断开。</p>
      </div></div>
      <div class="capture-rows capv-collected-rows" role="list" aria-label="已采集对局列表">
        ${collectedRows.map((m) => {
          const key = String(m.key || '');
          const day = String(m.date || '');
          const start = String(m.startTime || '').trim();
          const clock = start.includes(' ') ? start.slice(start.indexOf(' ') + 1) : '';
          const result = { win: '胜', loss: '负', draw: '平' }[m.result] || '—';
          const pairs = (m.lineup || []).filter((p) => p.own || p.enemy).slice(0, 5);
          const ownHeroes = pairs.length ? pairs.map((p) => p.own) : (m.heroes || []).slice(0, 5);
          const foeHeroes = pairs.map((p) => p.enemy);
          const face = (hero, foe) => {
            if (!hero) return '<span class="ml-cell is-empty"></span>';
            const icon = heroIcons.get(hero);
            const img = /^\/catalog\/icons\/hero-\d+\.png$/.test(icon || '')
              ? `<img class="portrait" src="${esc(icon)}" alt="${esc(hero)}" loading="lazy">`
              : `<span class="portrait portrait-placeholder" aria-label="${esc(hero)}">${esc(String(hero)[0])}</span>`;
            return `<span class="ml-cell${foe ? ' is-foe' : ''}" title="${esc((foe ? '对方 ' : '我方 ') + hero)}">${img}</span>`;
          };
          const lineup = `<span class="match-lineup archive-lineup" title="左组本队 · 右组对面，同一顺序即同分路对位">
            <span class="ml-side is-own"><small>我方</small><span class="ml-faces">${ownHeroes.map((h) => face(h, false)).join('')}</span></span>
            ${foeHeroes.some(Boolean)
              ? `<span class="ml-vs" aria-hidden="true">VS</span><span class="ml-side is-foe"><small>对方</small><span class="ml-faces">${foeHeroes.map((h) => face(h, true)).join('')}</span></span>`
              : ''}</span>`;
          return `<div class="match-row-wrap" role="listitem" data-match-key="${esc(key)}">
            <div class="match-row">
              <span class="match-date"><b>${esc(day.slice(5) || '日期未知')}</b><small>${esc(clock || day.slice(0, 4) || '')}</small></span>
              <span class="match-opponent"><b title="${esc(m.opponent || '')}">${esc(m.opponent || '对手未标注')}</b><small>${esc(m.mode || '训练赛')}</small></span>
              <span class="result ${esc(m.result || '')}" title="结果">${result}</span>
              ${lineup}
              <button type="button" class="capv-collected-del" data-capture-action="delete-match"
                data-match-key="${esc(key)}" aria-label="删除对局 ${esc(m.opponent || key)}">删除</button>
            </div>
          </div>`;
        }).join('') || '<p class="capv-collected-empty">库里还没有对局，先去「营地同步」拉几局。</p>'}
      </div>
    </section>`;

    const panels = {
      camp: campPanel,
      shots: embedded('shots'),
      videos: embedded('videos'),
      replays: embedded('replays'),
      review: reviewPanel,
      imported: importPanel,
    };

    return withPage('采集', '',
      `<div class="cap-page capv-page">
        ${notice}
        ${tabBar}
        ${panels[tab] || panels.camp}
      </div>`, false, '', false);
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
    form.closest('dialog')?.close(); // 提交后立刻关弹窗，后续整页重绘不会留下悬空对话框

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

  async function backfillOfficial() {
    if (state.busy) return;
    const coverage = state.value?.officialCoverage || {};
    if (!Number(coverage.fillable)) {
      setNotice('清单里没有可补的回放；营地只保留最近一个月的回放。', true);
      paint();
      return;
    }
    state.busy = 'backfill';
    setNotice('正在补拉缺失回放：逐局放慢速度，避免被营地限流…');
    paint();
    try {
      const result = await api('official/backfill', { method: 'POST', body: { limit: 10 } });
      const report = result?.report || {};
      const imported = Number(report.imported) || 0;
      const attached = Number(report.attached) || 0;
      const failed = Number(report.failed) || 0;
      const limited = Number(report.rateLimited) || 0;
      const parts = [];
      if (imported) parts.push(`新拉 ${imported} 局`);
      if (attached) parts.push(`挂上 ${attached} 局`);
      if (failed) parts.push(`${failed} 局没拉到`);
      if (limited) parts.push(`${limited} 次被限流已退避`);
      setNotice(parts.length
        ? `回放补拉：${parts.join('，')}。`
        : '没有可补的回放；营地只保留最近一个月的回放。', failed > 0);
    } catch (error) {
      setNotice(`补拉回放失败：${error.message}`, true);
    } finally {
      state.busy = '';
      await reloadValue().catch(() => {});
    }
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
        await api('camp/sync', { method: 'POST', body: {
          campUserId, nickname: group.nickname, entries: group.entries,
          ...currentCaptureContext(),
        } });
        // 同步是后台任务，轮询到结束再走下一组；进度来自后端的真实处理计数。
        // 单局详情请求间隔约 2 秒，一次最多 360 局，轮询上限留足 30 分钟。
        let status = null;
        for (let i = 0; i < 1800; i += 1) {
          status = await api('camp/sync');
          if (status?.error) throw new Error(status.error);
          const p = status?.progress || {};
          if (status.running) {
            const phaseLabel = syncPhaseLabel(p.phase);
            state.progress = { phase: p.phase || 'detail', label: phaseLabel,
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
            problems.push(`${officialFailed} 局官方回放没拉到${first ? `（${first.error}）` : ''}；稍后可点「补拉缺失回放」重试`);
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
        const form = document.querySelector('[data-capture-form="player"]');
        const input = form?.querySelector('[name="identity"]');
        const dialog = form?.closest('dialog');
        if (dialog && !dialog.open) dialog.showModal();
        if (input) input.focus();
        return true;
      }
      if (action === 'scroll-channels') {
        // 采集页的审查区在「对局审查」页签；不在页签上时直接切过去。
        const host = document.querySelector('[data-tour="camp-flow"]');
        if (host) host.scrollIntoView({ block: 'start', behavior: 'smooth' });
        else location.hash = '#review';
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
      if (action === 'backfill-official') { await backfillOfficial(); return true; }
      if (action === 'import') { await importSelected(); return true; }
      if (action === 'delete-match') {
        const key = button.dataset.matchKey || '';
        const title = button.closest('tr')?.querySelector('.capv-collected-title')?.textContent || key;
        if (!await confirmMatchDelete(key, title)) return true;
        await deleteMatch(key);
        return true;
      }
      if (action === 'approve-clean') { await approveClean(); return true; }
      if (action === 'conn-toggle') { state.connOpen = !state.connOpen; paint(); return true; }
      if (action === 'backfill-open') {
        state.backfillOpen = true;
        if (routeParts().tab !== 'camp') location.hash = '#ingest';
        else paint();
        return true;
      }
      if (action === 'backfill-close') { state.backfillOpen = false; paint(); return true; }
      if (action === 'backfill-create') { await createBackfillMatch(); return true; }
      if (action === 'upload-shots') { await uploadIngestShots(); return true; }
      if (action === 'jump-ocr') {
        const host = document.getElementById('ocr-windows');
        if (host) host.scrollIntoView({ block: 'start', behavior: 'smooth' });
        else location.hash = '#shots';
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
    const { tab } = routeParts();
    // 换页签 / 切走页面就停掉营地授权轮询，避免旧页签继续打接口
    if (tab !== 'camp') stopPoll();
    // 首屏由 features 渲染，不经过 paint()，这里补一次筛选绑定
    bindFilter();
    // 每次回到采集页最多自动检测一次授权；点「检测授权」可强制重查。
    const auth = state.value?.sync?.auth;
    if (tab === 'camp' && auth?.authorized && Date.now() - state.authCheckedAt > 10 * 60 * 1000) checkAuth(false);
  }

  return { load, render: view, click, change, afterRender };
}


