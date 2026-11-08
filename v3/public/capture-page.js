/* 采集页 —— V1 的采集链路在 V2 界面里的实现。
 *
 * 数据与写操作都走 V1 的根接口（不是 V3 自己的只读接口）：
 *   GET  /api/channels            采集通道
 *   GET  /api/camp/sync           授权状态 + 已同步对局
 *   GET  /api/camp/config         营地选手白名单
 *   POST /api/camp/auth/qr        生成授权二维码 -> {taskId, qrcodeBase64}
 *   GET  /api/camp/auth/poll      轮询 -> {status: waiting|scanned|success|error|expired|canceled}
 *   POST /api/camp/auth/cancel    取消本次会话
 *   POST /api/camp/auth/clear     删除登录凭证
 *   POST /api/camp/resolve        分享链接 -> {userId, nickname}
 *   POST /api/camp/list           拉某位选手的最近对局 -> {entries[], gaming?}
 *   POST /api/camp/sync           入库所选对局（按 campUserId 分组）
 *   POST /api/camp/config         保存白名单 {players:[{campUserId, nickname}]}
 *
 * 只有从 server.py 启动的 V3 根路径才带采集接口；单独跑 v3/serve.py（开发/演示）时
 * 这些接口不存在，页面会给出明确提示而不是空白。
 */

const V1_API = '/api/';

/* 采集来源档位 —— 与 web/capture-guide/requirements.json、
   web/collection-guide.js 里的既有措辞保持一致，不要另造词。 */
const SOURCE_TIERS = [
  ['官方回放链接', { label: '唯一必采', key: 'must' }, '每局都要有；在通道校对里关联本局网页回放', ''],
  ['营地数据自动采集', { label: '推荐主路径', key: 'primary' }, '教练号授权后每天增量拉取，BP 与十人面板都能覆盖', '#ingest'],
  ['七张赛后截图', { label: '兜底路径', key: 'fallback' }, '营地拿不到十人面板时使用，需与录屏成对', '#shots'],
  ['完整录屏', { label: '兜底路径', key: 'fallback' }, '与七张截图一起凑齐审核门槛', '#videos'],
  ['标准表格', { label: '选填 · 补充', key: 'extra' }, '手填补充或校正字段，需要按模板列结构', '#capture'],
];

async function v1(path, { method = 'GET', body, signal } = {}) {
  const response = await fetch(V1_API + path, {
    method,
    cache: 'no-store',
    signal,
    ...(body === undefined ? {} : {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
  if (!response.ok) {
    let body;
    try { body = await response.json(); } catch { /* 非 JSON */ }
    const detail = body?.detail;
    // 404 = 这条采集接口根本没挂载（V2 独立运行时只提供只读分析接口）。
    // FastAPI 的 404 正文是固定的 "Not Found"，直接抛给教练看等于什么都没说明。
    if (response.status === 404) {
      const missing = new Error('采集接口未挂载。采集页需要由 server.py 提供（V2 独立运行时不带采集链路）。');
      missing.unavailable = true;
      throw missing;
    }
    const message = typeof detail === 'string' && detail !== 'Not Found'
      ? detail
      : '采集接口不可用。采集页需要由 server.py 提供（V2 独立运行时不带采集）。';
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
  };

  function stopPoll() {
    if (state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
  }

  function paint() {
    const root = document.querySelector('#content');
    if (root && state.value) {
      root.innerHTML = view(state.value);
      bindFilter();
    }
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  async function reloadValue() {
    state.value = await load('ingest', '', undefined);
  }

  // ---------------- 数据 ----------------

  async function load(_name, _key, signal) {
    try {
      const [channels, sync, config, catalog, matchesView] = await Promise.all([
        v1('channels', { signal }),
        v1('camp/sync', { signal }),
        v1('camp/config', { signal }).catch(() => ({ players: [] })),
        // 英雄图标与阵容：拿不到时只是不显示头像，不影响主流程
        v1('catalog', { signal }).catch(() => ({ entries: [] })),
        v1('studio/view/matches', { signal }).catch(() => ({ matches: [] })),
      ]);
      // 保存一份，供写操作后局部重绘（paint）使用
      state.value = { channels, sync, config, catalog, matchesView };
      const auth = sync?.auth || {};
      state.authIssue = auth.authorized && auth.expired ? (auth.reason || '营地登录态已失效。') : '';
      return state.value;
    } catch (error) {
      // 宿主没有采集接口：交给页面说清楚，而不是让通用错误框显示 "Not Found"。
      if (!error?.unavailable) throw error;
      state.value = null;
      return { unavailable: true };
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
    if (channel.saved?.status === 'saved') return ['saved', '已入库'];
    if (channel.review?.status === 'reviewed') return ['reviewed', '已复核'];
    return ['draft', '待审核'];
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

  function heroesCell(channel, ctx) {
    const heroes = ctx.heroesByKey.get(channel.saved?.bundleKey) || [];
    if (!heroes.length) return '<span class="chan-heroes is-empty">—</span>';
    return `<span class="chan-heroes">${heroes.slice(0, 5).map((name) => {
      const icon = ctx.iconByName.get(name);
      return icon
        ? `<img src="${esc(icon)}" alt="${esc(name)}" title="${esc(name)}" loading="lazy">`
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
    const meta = [mode, duration(match.durationSec)].filter(Boolean).join(' · ');

    const version = String(match.version || '').split(/[\s/]/)[0];
    return `<div class="chan-row" data-chan-open="${esc(channel.id)}" title="点击进入逐项校对">
      ${scoreCell(match)}
      <span class="chan-main">
        <b>${esc(match.opponent ? `对阵 ${match.opponent}` : '对手未标注')}</b>
        <small>${esc(meta || '没有更多字段')}</small>
      </span>
      ${heroesCell(channel, ctx)}
      ${sourceCell(channel)}
      <span class="chan-session" title="${esc(match.session || '')}">${esc(match.session || '—')}</span>
      <span class="chan-version" title="${esc(match.version || '')}">${esc(version || '—')}</span>
      <span class="chan-updated">${esc(stamp(channel.updatedAt) || '—')}</span>
      <span class="chan-state">
        ${seed ? '<i class="chip is-seed" title="种子脚本写入的测试数据，不参与正式统计">验证</i>' : ''}
        <i class="chip ${status === 'saved' ? 'is-done' : 'is-pending'}">${esc(label)}</i>
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
      return [match.opponent, match.session, match.mode, match.date]
        .filter(Boolean).join(' ').toLowerCase().includes(q);
    });
  }

  function countingLine(total, pending, visible, filtering, seedCount) {
    const base = `共 ${total} 条${pending ? `，其中 ${pending} 条待入库` : ''}`;
    const seed = seedCount ? `，其中 ${seedCount} 条是验证数据` : '';
    return `${base}${seed}${filtering ? `；筛选后 ${visible} 条` : ''}。点任意一条进入逐项校对。`;
  }

  /** 只重绘通道列表，避免每次输入都整体重绘导致输入框失焦。 */
  function repaintChannels() {
    const host = document.querySelector('[data-ingest-list]');
    if (!host || !state.value) return;
    const list = state.value.channels?.channels || [];
    const ordered = [...list.filter((channel) => channel.saved?.status !== 'saved'),
      ...list.filter((channel) => channel.saved?.status === 'saved')];
    host.innerHTML = renderChannelList(filterChannels(ordered), lookups());
    const clear = document.querySelector('[data-capture-action="clear-filter"]');
    if (clear) clear.hidden = !(state.query || state.fromDate || state.toDate);
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
      const channel = await v1(`channels/${encodeURIComponent(id)}`);
      box.innerHTML = draftSummary(channel, lookups());
      box.dataset.loaded = '1';
    } catch (error) {
      box.innerHTML = `<p class="capture-hint is-error">读取失败：${esc(error.message)}</p>`;
    }
  }

  /** 按日期分组，日期只在组头出现一次。 */
  function renderChannelList(channels, ctx) {
    if (!channels.length) {
      return '<div class="empty">没有符合条件的通道。</div>';
    }
    const groups = new Map();
    for (const channel of channels) {
      const date = String(channel.match?.date || '未标日期');
      if (!groups.has(date)) groups.set(date, []);
      groups.get(date).push(channel);
    }
    return [...groups.entries()].map(([date, rows]) => {
      const saved = rows.filter((channel) => channel.saved?.status === 'saved').length;
      return `<div class="chan-group">
        <div class="chan-group-head"><b>${esc(date)}</b>
          <span>${rows.length} 条${saved === rows.length ? ' · 全部已入库' : ` · ${rows.length - saved} 条待入库`}</span></div>
        <div class="chan-rows">${rows.map((channel) => channelRow(channel, ctx)).join('')}</div>
      </div>`;
    }).join('');
  }

  // ---------------- 授权卡 ----------------

  // ---------------- 状态条与连接卡 ----------------

  /** 深色主面板：只回答一个问题 —— 今天这一步该做什么。状态作为脚注附在同一块里。 */
  function heroCard(ctx) {
    const { auth, players, pending } = ctx;
    const expired = Boolean(auth.authorized && (auth.expired || state.authIssue));
    const issue = state.authIssue || auth.reason || '营地登录态已失效。';

    let step;
    let title;
    let desc;
    let action = '';

    if (expired) {
      step = '第 1 步';
      title = '营地授权已失效，需要补充授权';
      desc = `${issue}重新扫码补充授权后，沿用原来的选手白名单；已入库的数据不受影响。`;
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
      title = `入库所选 ${count} 局`;
      desc = '入库后会生成采集通道，还需要补素材并逐项核对，通过后才会进入正式统计。';
      action = `<button class="hero-cta" data-capture-action="import">入库 ${count} 局</button>`;
    } else {
      step = '已完成';
      title = '今天没有需要入库的新对局';
      desc = pending
        ? `还有 ${pending} 条通道待补素材或复核，可以在下面「采集通道」里逐条处理。`
        : '所有采集通道都已入库。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="hero-cta" data-capture-action="scroll-channels">查看 ${pending} 条</button>`
        : '';
    }

    const syncText = ctx.daysAgo === null ? '还没拉取过'
      : ctx.daysAgo === 0 ? '今天拉取过' : `${ctx.daysAgo} 天前拉取`;
    const dot = (ok) => `<i class="hero-dot ${ok ? 'is-ok' : 'is-warn'}"></i>`;

    return `<section class="next-hero">
      <div class="hero-main">
        <span class="hero-eyebrow">下一步 · ${esc(step)}</span>
        <h2>${esc(title)}</h2>
        <p>${esc(desc)}</p>
      </div>
      ${action ? `<div class="hero-action">${action}</div>` : ''}
      <div class="hero-stats">
        <span>${dot(auth.authorized && !expired)}营地授权 <b>${expired ? '失效' : auth.authorized ? '正常' : '未授权'}</b></span>
        <span>${dot(players.length > 0)}营地选手 <b>${fmt(players.length)}</b></span>
        <span>${dot(true)}采集通道 <b>${fmt(ctx.channels)}</b><small>· ${ctx.pending ? `${ctx.pending} 待入库` : '全部已入库'}</small></span>
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

    let actions;
    if (!ready) {
      actions = `<button class="primary" data-capture-action="auth-start">${icon('search')} 扫码授权</button>`;
    } else {
      actions = `<div class="conn-actions">
        <button class="control" data-capture-action="auth-check" ${checking ? 'disabled' : ''}>${checking ? '检测中…' : '检测授权'}</button>
        <button class="${expired ? 'primary' : 'control'}" data-capture-action="auth-start">${icon('refresh')} ${expired ? '补充授权' : '重新扫码'}</button>
        <button class="control" data-capture-action="auth-clear">删除凭证</button></div>`;
    }

    // 授权失效时把「补充授权」放在最显眼的位置；二维码展开后让出位置给扫码。
    const alert = expired && !state.qr
      ? `<div class="conn-alert" role="alert">
          <div class="conn-alert-copy"><b>营地授权已失效，爬取已暂停</b>
            <small>${esc(issue)}重新扫码补充授权后即可继续拉取；已入库的数据不受影响。</small></div>
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
      ? `<ul class="conn-list">${players.map((player) => `<li>
          <b>${esc(player.nickname || '未命名')}</b><small>${text(player.campUserId)}</small>
          <button class="conn-x" data-capture-action="player-remove" data-camp-user="${esc(player.campUserId)}" aria-label="移除这个选手">×</button>
        </li>`).join('')}</ul>`
      : '';

    const playersBody = `<div class="conn-players">
      <div class="conn-players-head"><h3>选手白名单</h3><span class="conn-count">${fmt(players.length)} 位</span></div>
      ${players.length ? '' : '<p class="conn-empty">还没有绑定选手 —— 填好下面这一栏，拉取就有东西可读了。</p>'}
      <form data-capture-form="player" class="conn-form">
        <textarea name="identity" rows="3" autocomplete="off" spellcheck="false"
          placeholder="一行一个营地 ID，也可以直接粘贴多条分享链接"></textarea>
        <div class="conn-form-foot">
          <p>支持换行、逗号或空格分隔，链接会自动解析。每场必上的号一位就够 —— 一局详情自带双方十人面板。</p>
          <button class="primary" type="submit">批量添加</button>
        </div>
      </form>${list}</div>`;

    return block('营地连接', '授权一次，之后每天点「拉取对局」；凭证只存在本机。',
      `<div class="conn-body">${alert}${authBody}${playersBody}</div>`, actions);
  }

  // ---------------- 对局列表 ----------------

  function pullBlock(players) {
    const list = state.list;
    const checked = Object.keys(state.checked).length;
    const blocked = Boolean(state.authIssue);
    const blockedHint = blocked
      ? '<p class="capture-hint is-warn">营地授权已失效，拉取会失败 —— 先点「补充授权」重新扫码。</p>'
      : '';
    const right = `<div class="capture-actions">
      ${blocked ? '<button class="primary" data-capture-action="auth-start">补充授权</button>' : ''}
      <button class="control" data-capture-action="pull" ${state.busy === 'pull' || !players.length || blocked ? 'disabled' : ''}>${state.busy === 'pull' ? '正在拉取…' : '拉取对局'}</button>
      <button class="primary" data-capture-action="import" ${checked ? '' : 'disabled'}>入库所选 ${checked} 局</button></div>`;

    if (!players.length) {
      return block('拉取对局', '绑定选手后，这里会列出他们最近的战绩供你勾选。',
        `${blockedHint}<p class="capture-hint">还没有可拉取的选手 —— 先在上面「营地连接」里绑定一位。</p>`, right);
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
        `${blockedHint}<p class="capture-hint"><i class="chip ${stale ? 'is-warn' : 'is-idle'}">${esc(syncNote)}</i>${stale ? ' 训练赛后记得拉一次。' : ''}</p>
         <p class="capture-hint">${state.listNote || '点右上角「拉取对局」开始。'}</p>`, right);
    }
    if (!list.length) {
      return block('拉取对局', '最近没有新的对局。', `${blockedHint}<p class="capture-hint">${esc(state.listNote || '选手最近没有可拉取的对局。')}</p>`, right);
    }

    // 营地对局的 gameSeq 与采集通道 id 不是一套编号；用 camp details 里
    // 「gameSeq → channelId」的映射来判断这一局是否已经在库里
    const importedSeqs = new Set(
      (state.value?.sync?.details || [])
        .filter((detail) => detail.channelId)
        .map((detail) => String(detail.gameSeq)),
    );

    const rows = list.map((entry) => {
      const seq = String(entry.gameSeq);
      const already = entry.imported || importedSeqs.has(seq);
      const checkedAttr = state.checked[seq] && !already ? 'checked' : '';
      return `<label class="ingest-row is-check ${already ? 'is-in' : ''}">
        <input type="checkbox" data-capture-check="${esc(seq)}" ${checkedAttr} ${already ? 'disabled' : ''}>
        <span class="ingest-date"><b>${esc(stamp(new Date(Number(entry.dtEventTime || 0)).toISOString()).slice(0, 5) || '--')}</b></span>
        <span class="ingest-main"><b>对局 ${text(seq)}</b><small>${esc(entry.mapName || '营地对局')} · ${esc(entry.ownerName || entry.owner || '未标注选手')}</small></span>
        <span class="ingest-chips">
          ${already ? '<i class="chip is-in">库里已有</i>' : '<i class="chip is-pending">待入库</i>'}
        </span>
      </label>`;
    }).join('');

    const dup = list.filter((entry) => entry.imported || importedSeqs.has(String(entry.gameSeq))).length;
    return block('拉取对局',
      `共 ${list.length} 局，已勾选 ${checked} 局${dup ? `；其中 ${dup} 局库里已有，已自动排除` : ''}。入库后会生成采集通道，再补素材与核对。`,
      `<div class="ingest-list">${rows}</div>
       <p class="capture-hint">${esc(state.busy === 'import' ? '正在入库并轮询进度…' : (state.listNote || ''))}</p>`, right);
  }

  // ---------------- 页面 ----------------

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
      title = `第 4 步 · 入库所选 ${count} 局`;
      desc = '入库后会生成采集通道，还需要补素材并逐项核对，通过后才会进入正式统计。';
      action = `<button class="primary" data-capture-action="import">入库所选 ${count} 局</button>`;
    } else {
      title = '今天没有需要入库的新对局';
      desc = pending
        ? `还有 ${pending} 条通道待补素材或复核，可以在下面「采集通道」里逐条处理。`
        : '所有采集通道都已入库。下次训练赛结束后重新拉取即可。';
      action = pending
        ? `<button class="control" data-capture-action="scroll-channels">查看待入库 ${pending} 条</button>`
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
      return withPage('营地同步', '这个预览地址没有采集接口；同一个界面换一个地址就带采集。',
        `<div class="capture-notice is-error" role="status">采集接口未挂载：当前页面由 v3/serve.py 单独提供，只带只读分析接口，不含营地的扫码授权、拉取与入库。</div>`
        + block('用 8766 的根地址即可', 'server.py 已经把 V3 界面和采集接口放在同一个进程、同一份 data/ 里。',
          `<p>只运行一次 <code>启动工作台.bat</code>，然后打开 <a href="http://127.0.0.1:8766/#ingest">http://127.0.0.1:8766/#ingest</a>：界面与这里完全一样，采集可以直接扫码授权、拉取与入库，不需要再开第二个程序。</p>`
          + `<p><button class="control" data-action="refresh">重新读取</button></p>`), false);
    }
    const list = value?.channels?.channels || [];
    const sync = value?.sync || {};
    const details = sync.details || [];
    const auth = sync.auth || {};
    const players = value?.config?.players || sync.config?.players || [];

    const saved = list.filter((channel) => channel.saved?.status === 'saved').length;
    const waiting = list.filter((channel) => channel.saved?.status !== 'saved').length;
    const ready = list.filter((channel) => channel.sourceStatus?.complete).length;

    const pendingChannels = list.filter((channel) => channel.saved?.status !== 'saved');
    const orderedChannels = [...pendingChannels, ...list.filter((channel) => channel.saved?.status === 'saved')];
    const visibleChannels = filterChannels(orderedChannels);
    const seedCount = list.filter(isSeedChannel).length;
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
        `<span class="result ${detail.channelId ? '' : 'pending'}">${detail.channelId ? '已入库' : '未入库'}</span>`,
        text(when(detail)), text(detail.gameSeq), text(detail.mapName || '营地对局'), kdaText(detail)]))
      : '';

    const authDetail = auth.authorized
      ? `${auth.nickname || '已登录'}${stamp(auth.loginAt) ? ` · ${stamp(auth.loginAt)}` : ''}`
      : '需要在王者营地扫码授权';

    const notice = state.notice
      ? `<div class="capture-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`
      : '';

    const scopeNote = '<div class="scope-note"><span>口径</span> 本页直接读 V1 的采集通道与营地同步结果，'
      + '不受顶部「数据范围」影响；营地来源可能包含非训练赛。</div>';

    return withPage('营地同步', '授权一次，之后每天增量拉取；营地能覆盖的字段就不必再走截图或录屏。',
      notice
      + heroCard({
        auth, players, pending: pendingChannels.length,
        channels: list.length, daysAgo,
      })
      + connectionBlock(auth, players)
      + (players.length ? pullBlock(players) : '')
      + block('采集流水',
        countingLine(list.length, pendingChannels.length, visibleChannels.length, filtering, seedCount),
        `<div class="flow-bar">
          <label class="flow-search">${icon('search')}
            <input type="search" data-ingest-query value="${esc(state.query)}"
              placeholder="搜索对手、训练组或日期" aria-label="搜索采集流水"></label>
          <div class="seg" role="group" aria-label="数据范围">
            <button data-ingest-scope="all" class="${state.scope === 'all' ? 'is-on' : ''}">全部 <i>${list.length}</i></button>
            <button data-ingest-scope="real" class="${state.scope === 'real' ? 'is-on' : ''}">真实 <i>${list.length - seedCount}</i></button>
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
        </div>` : ''}
        <div class="ingest-list" data-ingest-list>${renderChannelList(visibleChannels, lookups())}</div>`)
      + `<details class="tier-fold"><summary>采集来源档位 —— 营地拿不到时才需要走其它来源</summary>
          <div class="sv-tiers">${SOURCE_TIERS.map(([name, tier, note, href]) => `<div class="sv-tier is-${tier.key}">
            <span class="sv-tier-tag">${esc(tier.label)}</span>
            <b>${esc(name)}</b>
            <small>${esc(note)}</small>
            ${href ? `<a class="sv-tier-go" href="${esc(href)}">打开 →</a>` : '<span class="sv-tier-go is-none">无需单独操作</span>'}
          </div>`).join('')}</div></details>`
      , false);
  }

  // ---------------- 交互 ----------------

  function startPoll(taskId) {
    stopPoll();
    state.poll = setInterval(async () => {
      if (!state.qr || state.qr.taskId !== taskId) { stopPoll(); return; }
      try {
        const result = await v1(`camp/auth/poll?taskId=${encodeURIComponent(taskId)}`);
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
    paint();
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
          const resolved = await v1('camp/resolve', { method: 'POST', body: { url: token } });
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
      if (added.length) await v1('camp/config', { method: 'POST', body: { players } });
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

  async function removePlayer(campUserId) {
    state.busy = 'player';
    try {
      const players = (state.value?.config?.players || [])
        .filter((player) => player.campUserId !== campUserId);
      await v1('camp/config', { method: 'POST', body: { players } });
      setNotice('已移除该选手。');
      await reloadValue();
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function pullList() {
    const players = state.value?.config?.players || [];
    if (!players.length) { setNotice('先在「营地选手」里添加选手。', true); paint(); return; }
    state.busy = 'pull';
    state.list = null;
    state.checked = {};
    setNotice('');
    state.listNote = '正在读取…';
    paint();
    const merged = new Map();
    const problems = [];
    let authProblem = '';
    for (const player of players) {
      try {
        const result = await v1('camp/list', { method: 'POST', body: { campUserId: player.campUserId, lastTime: 0 } });
        for (const entry of result.entries || []) {
          const existing = merged.get(entry.gameSeq);
          if (existing) { existing.owners.push(player.nickname || player.campUserId); continue; }
          merged.set(entry.gameSeq, { ...entry,
            ownerName: player.nickname || `选手 ${String(player.campUserId).slice(-4)}`,
            ownerCampUserId: player.campUserId });
        }
        if (result.gaming) problems.push(`${player.nickname || '选手'} 有一局进行中，未包含在列表里`);
      } catch (error) {
        problems.push(`${player.nickname || player.campUserId}：${error.message}`);
        if (error.authInvalid) {
          // 登录态失效时继续查其他选手只会重复失败，直接停下并提示补充授权。
          authProblem = error.reason || error.message || '营地登录态已失效';
          break;
        }
      }
    }
    state.list = [...merged.values()].sort((a, b) => Number(b.dtEventTime || 0) - Number(a.dtEventTime || 0));
    const importedSeqs = new Set((state.value?.sync?.details || [])
      .filter((detail) => detail.channelId)
      .map((detail) => String(detail.gameSeq)));
    for (const entry of state.list) {
      if (!entry.imported && !importedSeqs.has(String(entry.gameSeq))) setChecked(entry.gameSeq, true);
    }
    state.listNote = problems.join('；');
    state.busy = '';
    if (authProblem) {
      state.authIssue = authProblem;
      setNotice('营地授权已失效，拉取已停止。请补充授权后再试。', true);
      await reloadValue();
    } else {
      setNotice(`拉到 ${state.list.length} 局，已自动勾选未入库的。`);
    }
    paint();
  }

  async function importSelected() {
    const chosen = (state.list || []).filter((entry) => state.checked[entry.gameSeq]);
    if (!chosen.length) { setNotice('请先勾选要入库的对局。', true); paint(); return; }
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
    setNotice(`正在入库 ${chosen.length} 局…`);
    paint();
    try {
      for (const [campUserId, group] of groups) {
        await v1('camp/sync', { method: 'POST', body: { campUserId, nickname: group.nickname, entries: group.entries } });
        // 同步是后台任务，轮询到结束再走下一组
        let status = null;
        for (let i = 0; i < 120; i += 1) {
          status = await v1('camp/sync');
          if (!status.running) break;
          await new Promise((resolve) => setTimeout(resolve, 3000));
        }
        const authFailure = (status?.result?.players || []).find((item) => item.authInvalid);
        if (authFailure) {
          const error = new Error(authFailure.reason || authFailure.error || '营地登录态已失效');
          error.authInvalid = true;
          throw error;
        }
      }
      state.list = null;
      state.checked = {};
      await reloadValue();
      setNotice('所选对局已入库，采集通道已自动生成。');
    } catch (error) {
      if (error.authInvalid) {
        state.authIssue = error.message;
        setNotice('营地授权已失效，这次入库没有完成。请补充授权后重新拉取。', true);
        await reloadValue();
      } else {
        setNotice(error.message, true);
      }
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
      const result = await v1(`camp/auth/check${force ? '?force=1' : ''}`, { method: 'POST' });
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
        const folded = document.querySelector('.tier-fold');
        const host = document.querySelectorAll('#content .section')[4] || folded;
        if (host) host.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return true;
      }
      if (action === 'auth-check') { await checkAuth(true); return true; }
      if (action === 'auth-start') {
        try {
          state.busy = 'auth';
          setNotice('正在生成二维码…');
          paint();
          state.qr = await v1('camp/auth/qr', { method: 'POST' });
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
          try { await v1(`camp/auth/cancel?taskId=${encodeURIComponent(taskId)}`, { method: 'POST' }); } catch { /* 会自行过期 */ }
        }
        paint();
        return true;
      }
      if (action === 'auth-clear') {
        if (!window.confirm('删除本机的营地登录凭证？删除后需要重新扫码。')) return true;
        try {
          await v1('camp/auth/clear', { method: 'POST' });
          await reloadValue();
          setNotice('凭证已删除。');
        } catch (error) {
          setNotice(error.message, true);
        }
        paint();
        return true;
      }
      if (action === 'pull') { await pullList(); return true; }
      if (action === 'import') { await importSelected(); return true; }
      if (action === 'player-remove') { await removePlayer(button.dataset.campUser); return true; }
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
