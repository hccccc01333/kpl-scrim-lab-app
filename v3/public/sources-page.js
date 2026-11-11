/* 采集的三个素材来源页：截图 OCR / 录屏 / 回放。
 *
 * 全部走工作台根接口：
 *   GET  /api/postgame/images        截图与其识别结果（images + groups）
 *   GET  /api/recordings             本机录屏及识别报告
 *   GET  /api/replays                回放解析结果
 *   GET  /api/channels               挂载时的通道候选
 *   POST /api/images?name=<文件名>    上传截图原始文件（body 即文件）
 *   POST /api/postgame/images/{id}/ocr  重新识别一张截图
 *   POST /api/channels/{id}/screenshot  {imageIds:[...]}
 *   POST /api/channels/{id}/replay      {replayId}
 *
 * 录屏目前只读：挂载接口要求重新上传视频流，留在下一轮。
 */

const ROOT_API = '/api/';

async function api(path, { method = 'GET', body, signal, raw } = {}) {
  const init = { method, cache: 'no-store', signal };
  if (raw) {
    init.body = raw;
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(ROOT_API + path, init);
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* 非 JSON */ }
    const usable = typeof detail === 'string' && !/^Not Found$|^Internal Server Error$/i.test(detail);
    throw new Error(usable ? detail : '素材数据暂时读不到，请稍后重试。');
  }
  return response.json();
}

function stamp(epochOrIso) {
  if (epochOrIso === null || epochOrIso === undefined) return '';
  if (typeof epochOrIso === 'number') {
    const d = new Date(epochOrIso * 1000);
    return Number.isNaN(d.getTime()) ? '' : `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  const text = String(epochOrIso);
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text;
}

function bytes(n) {
  const value = Number(n || 0);
  if (!value) return '0 B';
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${value} B`;
}

function seconds(n) {
  const value = Number(n || 0);
  if (!value) return '—';
  const m = Math.floor(value / 60);
  const s = Math.round(value % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function createSources(h) {
  const { esc, fmt, block, stats, empty, withPage, icon, table } = h;
  const text = (value) => esc(value === null || value === undefined || value === '' ? '—' : value);

  const state = { name: '', value: null, busy: '', notice: null, openGroup: '',
    fps: localStorage.getItem('v3-recording-fps') || '1',
    engine: localStorage.getItem('v3-recording-engine') || 'mimo',
    progress: '', poll: null, pollFor: '', install: null, installWatch: null,
    engineOpen: null };
  const PAGE_TITLE = { shots: '截图 OCR', videos: '录屏', replays: '回放' };

  // ---------------- 数据 ----------------

  async function load(name, _key, signal) {
    state.name = name;
    let value;
    if (name === 'shots') {
      const [images, channels, status, install] = await Promise.all([
        api('postgame/images', { signal }),
        api('channels', { signal }).catch(() => ({ channels: [] })),
        api('ocr/status', { signal }).catch(() => ({})),
        api('ocr/install', { signal }).catch(() => null),
      ]);
      value = { images, channels, status, install };
    } else if (name === 'videos') {
      const [recordings, status, channels, install] = await Promise.all([
        api('recordings', { signal }),
        api('ocr/status', { signal }).catch(() => ({})),
        api('channels', { signal }).catch(() => ({ channels: [] })),
        api('ocr/install', { signal }).catch(() => null),
      ]);
      value = { recordings, status, channels, install };
    } else if (name === 'capture') {
      const [spec, channels] = await Promise.all([
        fetch('/assets/capture-guide/requirements.json', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null)).catch(() => null),
        api('channels', { signal }).catch(() => ({ channels: [] })),
      ]);
      value = { spec, channels };
    } else {
      const [replays, channels] = await Promise.all([
        api('replays', { signal }),
        api('channels', { signal }).catch(() => ({ channels: [] })),
      ]);
      value = { replays, channels };
    }
    state.value = value;
    return value;
  }

  function paint() {
    const root = document.querySelector('#content');
    if (root && state.value) root.innerHTML = render(state.name, state.value);
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  async function refresh() {
    state.value = await load(state.name, '', undefined);
  }

  function noticeBox() {
    if (!state.notice) return '';
    return `<div class="capture-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`;
  }

  function channelOptions(channels, selected) {
    return (channels || []).map((channel) => {
      const match = channel.match || {};
      const label = `${match.date || '无日期'} · ${match.session || '未命名'} · ${match.scores ? `${match.scores.left}:${match.scores.right}` : '无比分'}`;
      return `<option value="${esc(channel.id)}" ${channel.id === selected ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');
  }

  /** 采集页「补录一局」新建的通道，带过来预选，省得在几十条里翻。 */
  function pendingChannelId() {
    try { return sessionStorage.getItem('cap-new-channel') || ''; } catch { return ''; }
  }

  function clearPendingChannel() {
    try { sessionStorage.removeItem('cap-new-channel'); } catch { /* 无痕模式 */ }
  }

  // ---------------- 截图 / 录屏：共用的引导件 ----------------

  /* 七个页签与 requirements.json 一一对应；页面里直接摆出来，教练不用再去翻采集规范。 */
  const SHOT_PAGES = [
    ['01', 'score', '战绩 · 装备型', '比分、胜负、时长、十人 KDA 与装备', '01-score-equipment.jpg'],
    ['02', 'kda', '战绩 · KDA 占比', '击杀、死亡、助攻及各自占比', '02-score-kda.jpg'],
    ['03', 'data', '数据', '输出、承伤、经济、参团率', '03-data.jpg'],
    ['04', 'output', '输出', '输出伤害、伤害转化比', '04-output.jpg'],
    ['05', 'survival', '生存', '承受伤害、每死承伤', '05-survival.jpg'],
    ['06', 'farming', '发育', '总经济、野怪经济、补刀', '06-farming.jpg'],
    ['07', 'team', '团队', '参团率、控制效果、治疗量、对塔', '07-team.jpg'],
  ];
  const SHOT_TYPES = SHOT_PAGES.map(([, type]) => type);

  function steps(items, active) {
    return `<ol class="src-steps">${items.map(([title, hint], index) => {
      const cls = index < active ? 'is-done' : index === active ? 'is-on' : '';
      return `<li class="${cls}"><i>${index < active ? '✓' : index + 1}</i>
        <span><b>${esc(title)}</b><small>${esc(hint)}</small></span></li>`;
    }).join('')}</ol>`;
  }

  function uploadZone({ id, accept, multiple, title, hint, note }) {
    return `<label class="src-drop" for="${id}">
      <input id="${id}" type="file" accept="${accept}" ${multiple ? 'multiple' : ''} data-source-file="${id === 'shot-files' ? 'images' : 'video'}">
      <b>${esc(title)}</b><span>${esc(hint)}</span>
      <small data-file-note>${esc(note || '还没有选择文件')}</small>
    </label>`;
  }

  // ---------------- OCR 引擎：状态 + 一键安装 ----------------

  function mimoState(value) {
    const install = state.install || value?.install || null;
    const status = value?.status || {};
    const mimo = status.mimo || install?.mimo || {};
    const rapid = status.rapid || {};
    const ffmpeg = Boolean(status.ffmpeg && status.ffprobe);
    const ffmpegSource = status.ffmpegSource || '';
    const depsReady = Boolean(mimo.device) && mimo.device !== 'unavailable';
    const modelReady = Boolean(mimo.available);
    const freeBytes = Number(status.storage?.dbFreeBytes || 0);
    const recordingsBytes = Number(status.recordings?.bytes || 0);
    return {
      install, mimo, rapid, ffmpeg, ffmpegSource, depsReady, modelReady, freeBytes, recordingsBytes,
      diskEnough: !freeBytes || freeBytes >= 4 * 1024 ** 3,
      running: Boolean(install?.running),
      ready: depsReady && modelReady,
    };
  }

  function enginePanel(value) {
    const s = mimoState(value);
    const install = s.install || {};
    const percent = Math.max(0, Math.min(100, Number(install.percent) || 0));
    const open = state.engineOpen === null ? !s.ready : Boolean(state.engineOpen);
    const mimoLabel = s.ready ? '已安装' : s.running ? `安装中 ${percent}%` : '未安装';
    const mimoChip = s.ready ? 'is-done' : s.running ? 'is-pending' : 'is-idle';

    let mimoBody = '';
    if (s.running) {
      mimoBody = `<div class="src-engine-progress">
        <div class="src-bar"><i style="width:${percent}%"></i></div>
        <small>${esc(install.message || '正在安装…')}${percent ? ` · ${percent}%` : ''}</small>
      </div>`;
    } else if (install.phase === 'error') {
      mimoBody = `<div class="src-engine-meta is-error">${esc(install.error || install.message || '安装失败')}</div>`;
    } else if (s.ready) {
      mimoBody = `<div class="src-engine-meta is-ok">已安装${s.mimo.device === 'cuda' ? '（CUDA 加速）' : '（CPU）'}，不用重启；数值和昵称比主 OCR 更准。</div>`;
    } else {
      mimoBody = `<div class="src-engine-meta">可选增强：数值和昵称更准，CPU 上整页约 2–3 分钟。装不装都不影响主 OCR。</div>`
        + (s.diskEnough ? '' : `<div class="src-engine-meta is-error">磁盘只剩 ${bytes(s.freeBytes)}，安装至少要 4 GB。
            ${s.recordingsBytes ? `录屏缓存占了 ${bytes(s.recordingsBytes)}，可以在录屏页删掉旧录像；` : ''}
            也可以把工作台换到空间更大的盘再装。</div>`);
    }
    const installButton = s.ready || s.running ? ''
      : `<button class="primary" data-source-action="install-mimo" ${s.diskEnough ? '' : 'disabled'}>${install.phase === 'error' ? '重试安装' : s.diskEnough ? '安装 Mimo' : '安装 Mimo（需 4 GB）'}</button>`;
    const rapidButton = s.rapid.available || s.running ? ''
      : `<button class="control" data-source-action="install-rapid" ${(!s.freeBytes || s.freeBytes >= 1024 ** 3) ? '' : 'disabled'}>安装主 OCR</button>`;

    return `<section class="section src-engine${open ? ' is-open' : ''}" data-engine-panel>
      <div class="src-engine-bar">
        <b>识别引擎</b>
        <span class="chip ${s.rapid.available ? 'is-done' : 'is-warn'}">主 OCR ${s.rapid.available ? '就绪' : '缺失'}</span>
        <span class="chip ${mimoChip}">Mimo ${esc(mimoLabel)}</span>
        <span class="chip ${s.ffmpeg ? 'is-done' : 'is-warn'}">ffmpeg ${s.ffmpeg ? '可用' : '未检测到'}</span>
        <span class="src-engine-spacer"></span>
        ${open ? '' : installButton}
        <button class="control" data-source-action="engine-toggle">${open ? '收起' : '详情'}</button>
      </div>
      ${open ? `<div class="src-engine-body">
        <div class="src-engine-row">
          <b>主 OCR · rapidocr</b>
          <i class="chip ${s.rapid.available ? 'is-done' : 'is-warn'}">${s.rapid.available ? '已就绪' : '缺失'}</i>
          <small>随安装包发布，每页几秒；日常识别用它就够。</small>
          ${rapidButton}
        </div>
        <div class="src-engine-row">
          <b>Mimo 精读</b>
          <i class="chip ${mimoChip}">${esc(mimoLabel)}</i>
          <div class="src-engine-main">${mimoBody}</div>
          ${installButton}
        </div>
        <div class="src-engine-row">
          <b>ffmpeg</b>
          <i class="chip ${s.ffmpeg ? 'is-done' : 'is-warn'}">${s.ffmpeg ? '可用' : '未检测到'}</i>
          <div class="src-engine-main">${s.ffmpeg
            ? `<small>录屏抽帧已可用${s.ffmpegSource === 'bundled' ? '（应用内安装）'
                : s.ffmpegSource === 'path' ? '（系统 PATH）' : ''}。</small>`
            : '<small>录屏抽帧要用它。点「安装 ffmpeg」自动下载约 200 MB 解压到程序目录，'
              + '不用改系统 PATH，也不需要管理员权限。</small>'}</div>
          ${s.ffmpeg ? '' : `<button class="control" data-source-action="install-ffmpeg"
            ${s.running ? 'disabled' : ''}>安装 ffmpeg</button>`}
        </div>
      </div>` : ''}
      <div class="src-engine-foot">
        <button class="control" data-source-action="recheck-engine">重新检测</button>
        <span>${s.running ? '安装可以切页面，装好后右下角会提示。'
          : s.rapid.available
            ? 'Mimo 约 2–4 GB（含模型），首次视网速 10–40 分钟；不装也不影响主 OCR。'
            : `主 OCR 约 200 MB，装好就能识别；Mimo 另需 2–4 GB。当前磁盘剩余 ${bytes(s.freeBytes)}。`}</span>
      </div>
    </section>`;
  }

  // 安装进度挂在 body 上：切到对局、选手页也能看到，装完给提示。
  let installWidget = null;

  function ensureInstallWidget() {
    if (installWidget && document.body.contains(installWidget)) return installWidget;
    installWidget = document.createElement('div');
    installWidget.id = 'ocr-install-widget';
    installWidget.setAttribute('role', 'status');
    installWidget.setAttribute('aria-live', 'polite');
    installWidget.addEventListener('click', (event) => {
      if (event.target.closest('[data-install-widget-close]')) renderInstallWidget(null);
    });
    document.body.appendChild(installWidget);
    return installWidget;
  }

  function renderInstallWidget(status) {
    const host = ensureInstallWidget();
    if (!status || (!status.running && !['done', 'error'].includes(status.phase))) {
      host.hidden = true;
      host.innerHTML = '';
      return;
    }
    const percent = Math.max(0, Math.min(100, Number(status.percent) || 0));
    host.hidden = false;
    if (status.running) {
      const label = status.target === 'rapid' ? '主 OCR' : 'Mimo 精读';
      host.innerHTML = `<div class="cap-progress-float is-live">
        <div class="cap-progress-head"><b>正在安装${label}</b><span>${percent}%</span></div>
        <div class="cap-progress-track"><i style="width:${percent}%"></i></div>
        <small>${esc(status.message || '')}</small>
        <p class="cap-widget-foot"><a href="#shots">回到截图 OCR</a><span>可以切页面</span></p>
      </div>`;
    } else if (status.phase === 'done') {
      host.innerHTML = `<div class="cap-progress-float is-done">
        <div class="cap-progress-head"><b>${status.target === 'rapid' ? '主 OCR 已装好' : 'Mimo 已装好'}</b>
          <button type="button" class="cap-widget-x" data-install-widget-close aria-label="关闭">×</button></div>
        <div class="cap-widget-text">不用重启，回到 OCR 页就能直接用。</div>
        <p class="cap-widget-foot"><a href="#shots">去截图 OCR</a></p>
      </div>`;
    } else {
      host.innerHTML = `<div class="cap-progress-float is-done is-error">
        <div class="cap-progress-head"><b>安装失败</b>
          <button type="button" class="cap-widget-x" data-install-widget-close aria-label="关闭">×</button></div>
        <div class="cap-widget-text">${esc(status.error || status.message || '未知错误')}</div>
        <p class="cap-widget-foot"><a href="#shots">回到 OCR 页重试</a></p>
      </div>`;
    }
  }

  function isOcrPage() {
    return location.hash === '#shots' || location.hash === '#videos';
  }

  function paintEngine(status) {
    const host = document.querySelector('[data-engine-panel]');
    if (!host || !state.value) return;
    const value = { ...state.value, install: status || state.install };
    host.outerHTML = enginePanel(value);
  }

  function startInstallWatch() {
    if (state.installWatch) return;
    state.installWatch = setInterval(async () => {
      let status;
      try { status = await api('ocr/install'); } catch { return; }
      state.install = status;
      renderInstallWidget(status);
      if (isOcrPage()) paintEngine(status);
      if (status.running) return;
      clearInterval(state.installWatch);
      state.installWatch = null;
      if (status.phase === 'done') {
        setNotice(status.target === 'rapid'
          ? '主 OCR 已安装完成，可以直接上传截图识别了。'
          : status.target === 'ffmpeg'
            ? 'ffmpeg 已就绪，录屏抽帧可以直接用了。'
            : 'Mimo 精读已安装完成，可以直接用，不用重启。');
      }
      if (status.phase === 'error') setNotice(`安装失败：${status.error || status.message}`, true);
      setTimeout(() => renderInstallWidget(null), 15000);
      if (isOcrPage()) { await refresh(); paint(); } else { paintEngine(status); }
    }, 2000);
  }

  async function installOcr(target) {
    try {
      await api(`ocr/install?target=${encodeURIComponent(target)}`, { method: 'POST' });
      state.install = await api('ocr/install');
      setNotice(target === 'rapid'
        ? '已开始安装主 OCR，可以切页面；装好后右下角会提示。'
        : target === 'ffmpeg'
          ? '已开始下载 ffmpeg（约 200 MB），可以切页面；装好后右下角会提示。'
          : '已开始安装 Mimo，可以切页面；装好后右下角会提示。');
      if (isOcrPage()) paint();
      renderInstallWidget(state.install);
      startInstallWatch();
    } catch (error) {
      setNotice(error.message, true);
      paint();
    }
  }

  function shotGuide() {
    return `<section class="section src-guide" data-tour="shots-guide">
      <div class="section-heading"><div><h2>一局要拍齐这七张</h2>
        <p>同一个结算页把七个页签各截一张；「战绩」有两种显示方式，所以合计七张。少一张就不算齐。</p></div>
        <div class="capture-actions"><a class="control" href="#videos">还要录屏 · 去录屏页 →</a></div>
      </div>
      <ol class="src-shots">${SHOT_PAGES.map(([no, , name, fields, file]) => `<li>
        <a href="/assets/capture-guide/${file}" target="_blank" rel="noopener" title="点开看大图">
          <img src="/assets/capture-guide/${file}" alt="${esc(name)}" loading="lazy"></a>
        <b><i>${no}</i>${esc(name)}</b><small>${esc(fields)}</small>
      </li>`).join('')}</ol>
      <p class="src-note">示例图里昵称已经打码，只是教学用；<b>你上传的截图不要打码</b>——识别要靠昵称和数值，遮住反而要人工补十行。</p>
      <ul class="src-rules">
        <li><b>同一局</b>七张的日期、比分、十人阵容要一致</li>
        <li><b>保留</b>顶部比分与日期、双方十人、列名、底部页签</li>
        <li><b>不要</b>裁切、拼图、遮挡字段、加边框文字</li>
        <li><b>原图</b>PNG / JPEG / WebP，别用聊天软件压过的图</li>
      </ul>
    </section>`;
  }

  /** 一组的七页覆盖度：缺哪页直接点名。 */
  function groupCoverage(group, imageById) {
    const present = new Set((group.imageIds || [])
      .map((id) => imageById.get(id)?.pageType).filter(Boolean));
    const missing = SHOT_PAGES.filter(([, type]) => !present.has(type));
    return { present, missing, count: SHOT_TYPES.length - missing.length };
  }

  // ---------------- 截图 ----------------

  function shotsPage(value) {
    const groups = value.images?.groups || [];
    const images = value.images?.images || [];
    const channels = value.channels?.channels || [];
    const imageById = new Map(images.map((image) => [image.id, image]));
    const identified = groups.reduce((sum, group) => sum + (group.imageIds || []).length, 0);
    const complete = groups.filter((group) => groupCoverage(group, imageById).missing.length === 0).length;
    const active = groups.length ? 2 : images.length ? 1 : 0;

    const cards = groups.map((group, index) => {
      const match = group.match || {};
      const open = state.openGroup === String(index);
      const ids = group.imageIds || [];
      const players = group.players || [];
      const { present, missing, count } = groupCoverage(group, imageById);
      const score = match.score ? `${match.score.left} : ${match.score.right}` : '比分未识别';
      const dots = SHOT_PAGES.map(([, type, name]) =>
        `<i class="src-cov-dot ${present.has(type) ? 'is-on' : ''}" title="${esc(name)}${present.has(type) ? '' : '（缺）'}"></i>`).join('');
      const pageList = ids.map((id) => {
        const image = imageById.get(id);
        return `<li><b>${esc(image?.tab || image?.pageType || '页面')}</b>
          <span>${text(image?.name)}</span>
          <small>${(image?.warnings || []).length ? `${image.warnings.length} 条提示` : '无提示'}</small></li>`;
      }).join('');
      const playerList = players.slice(0, 10).map((player) => {
        const side = player.side === 'left' ? '左' : '右';
        const nick = player.nickname?.value || player.nickname?.raw || '';
        const hero = player.hero?.value || player.hero?.raw || '';
        return `<span class="shot-player is-mini"><small>${side}${(player.slot ?? 0) + 1}</small><b>${text(nick)}</b><i>${text(hero)}</i></span>`;
      }).join('');

      return `<article class="shot-card${missing.length ? ' is-warn' : ' is-ok'}">
        <header class="shot-head">
          <div><h3>${esc(match.date || '未归档的一局')}${match.time ? ` · ${esc(match.time)}` : ''}</h3>
            <p>${esc(match.mode || '模式未知')} · ${seconds(match.durationSec)} · ${esc(score)} · ${match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '结果未知'}</p></div>
          <span class="src-badge ${missing.length ? 'is-warn' : 'is-ok'}">${count} / 7 页${missing.length ? ` · 缺 ${missing.map(([, , name]) => name).join('、')}` : ' · 齐了'}</span>
        </header>
        <div class="src-cov">${dots}<small>${missing.length ? `还差 ${missing.length} 页` : '七页齐全'}</small></div>
        <div class="shot-players">${playerList || '<span class="capture-hint">这一组还没有识别出选手。</span>'}</div>
        <details class="shot-detail" ${open ? 'open' : ''} data-open-group="${index}">
          <summary>${ids.length} 页明细${(group.warnings || []).length ? ` · ${group.warnings.length} 条提示` : ''}</summary>
          <ol class="shot-pages">${pageList}</ol>
          ${(group.warnings || []).length ? `<ul class="shot-warnings">${group.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
        </details>
        <footer class="shot-actions">
          <select data-shot-channel="${index}"><option value="">挂到哪一局…</option>${channelOptions(channels, pendingChannelId())}</select>
          <button class="primary" data-source-action="attach-shots" data-group="${index}" ${ids.length ? '' : 'disabled'}>挂到这一局</button>
        </footer>
      </article>`;
    }).join('');

    return withPage('截图 OCR', '营地拿不到的局走这条：同一局七张赛后截图。拍什么、传到哪、挂给谁，这一页里都能做完。',
      `<div class="src-page">
        ${noticeBox()}
        ${steps([['拍齐七张', '同一局，七个页签'], ['上传识别', '本机识别，不联网'], ['挂到对局', '把分组挂到那一局']], active)}
        ${enginePanel(value)}
        ${shotGuide()}
        <section class="section src-upload" data-tour="shots-upload">
          <div class="section-heading"><div><h2>上传这七张</h2>
            <p>可一次多选；上传后按日期和比分自动分组，识别完在下面挂到对应对局。</p></div>
            <div class="capture-actions">
              <span class="src-count">${fmt(images.length)} 张 · ${fmt(groups.length)} 组</span>
              <button class="control" data-source-action="refresh">${icon('refresh')} 刷新</button>
            </div>
          </div>
          <div class="src-upload-body">
            ${uploadZone({ id: 'shot-files', accept: 'image/png,image/jpeg,image/webp', multiple: true,
              title: '选择截图', hint: 'PNG / JPEG / WebP，可一次多选' })}
            <button class="primary" data-source-action="upload-shots" ${state.busy === 'upload' ? 'disabled' : ''}>
              ${state.busy === 'upload' ? '正在上传…' : '上传并识别'}</button>
          </div>
          <p class="capture-hint">识别在本机完成；一页通常几秒，Mimo 精读整页约 2–3 分钟，可以先去挂别的组。</p>
        </section>
        <section class="section src-results" data-tour="shots-results">
          <div class="section-heading"><div><h2>识别结果</h2>
            <p>${groups.length
              ? `共 ${fmt(groups.length)} 组 · ${fmt(complete)} 组七页齐全；每组挂到一局后，这局的截图来源就算完成。`
              : '上传后这里会按日期和比分自动分组，一组对应一局。'}</p></div></div>
          <div class="shot-grid">${cards || `<p class="src-empty">还没有识别过赛后截图。先传一局的七张图。</p>`}</div>
        </section>
      </div>`, false);
  }

  // ---------------- 录屏 ----------------


  // ---------------- 录屏上传 ----------------

  const FPS_OPTIONS = [['0.5', '0.5 fps（更快）'], ['1', '1 fps（推荐）'], ['2', '2 fps（更细）']];
  const ENGINE_OPTIONS = [['mimo', 'Mimo 精读 + 快速布局'], ['rapid', '仅快速布局']];

  function stopPoll() {
    if (state.poll) { clearInterval(state.poll); state.poll = null; }
    state.pollFor = '';
  }

  /** 有任务在跑时每 3 秒刷新一次；任务清空后自动停。 */
  function startPoll() {
    stopPoll();
    state.pollFor = 'videos';
    state.poll = setInterval(async () => {
      try {
        const value = await load('videos', '', undefined);
        if (state.name !== 'videos') { stopPoll(); return; }
        paint();
        const jobs = value.recordings?.jobs || [];
        const busyJobs = jobs.filter((job) => ['queued', 'running'].includes(job.status)).length;
        const busyFiles = (value.recordings?.recordings || [])
          .some((rec) => rec.status && !['done', 'error', 'canceled'].includes(rec.status));
        if (!busyJobs && !busyFiles) stopPoll();
      } catch { /* 单次失败不打断轮询 */ }
    }, 3000);
  }

  function videoGuide(maxBytes) {
    return `<section class="section src-guide" data-tour="videos-guide">
      <div class="section-heading"><div><h2>一局要录成这样</h2>
        <p>从回放列表 / 加载页开始，到赛后结算页停；中间不剪辑、不拖进度、不开倍速。</p></div>
        <div class="capture-actions"><a class="control" href="#shots">还要七张截图 · 去截图页 →</a></div>
      </div>
      <ol class="src-timeline">
        <li><i>1</i><div><b>开始 · 约 5 秒</b><span>录到回放列表 / 加载页，双方十人英雄和昵称要清楚，再完整录到局内 00:00。</span></div></li>
        <li><i>2</i><div><b>整局 · 1 倍速</b><span>保留顶部时钟、比分、双方团队金币；团队面板尽量全程开着。</span></div></li>
        <li><i>3</i><div><b>结束 · 约 5 秒</b><span>录过水晶结束、胜负动画，停在赛后战绩页再停止。</span></div></li>
      </ol>
      <div class="src-examples">
        <figure><a href="/assets/capture-guide/recording-loading.png" target="_blank" rel="noopener">
          <img src="/assets/capture-guide/recording-loading.png" alt="加载页示例" loading="lazy"></a>
          <figcaption>加载页：双方十人英雄 + 昵称</figcaption></figure>
        <figure><a href="/assets/capture-guide/recording-panel.png" target="_blank" rel="noopener">
          <img src="/assets/capture-guide/recording-panel.png" alt="团队面板示例" loading="lazy"></a>
          <figcaption>团队面板：双方各五人 KDA + 累计金币</figcaption></figure>
      </div>
      <p class="src-note">示例里昵称已经打码，只是教学用；<b>你录的原片不用做任何处理</b>，直接上传完整录像即可。</p>
      <ul class="src-rules">
        <li><b>记分板</b>00:30、之后每 5 分钟、结束前，各开 ≥5 秒</li>
        <li><b>格式</b>横屏 1080p / 30 fps；mp4、mov、mkv、webm</li>
        <li><b>大小</b>单文件上限 ${bytes(maxBytes)}</li>
        <li><b>不要</b>剪辑、倍速、单英雄可用金币代替累计经济</li>
      </ul>
    </section>`;
  }

  function uploadVideosBlock(value) {
    const status = value.status || {};
    const statsInfo = value.recordings?.stats || {};
    const recordings = value.recordings?.recordings || [];
    const ready = Boolean(status.ffmpeg && status.ffprobe);
    const maxBytes = Number(statsInfo.maxBytes || 0);

    const fpsOptions = FPS_OPTIONS.map(([v, label]) =>
      `<option value="${v}" ${state.fps === v ? 'selected' : ''}>${esc(label)}</option>`).join('');
    const engineOptions = ENGINE_OPTIONS.map(([v, label]) => {
      const usable = v !== 'mimo' || mimoState(value).ready;
      const selected = state.engine === v && usable;
      return `<option value="${v}" ${selected ? 'selected' : ''} ${usable ? '' : 'disabled'}>${esc(label)}${usable ? '' : '（未安装）'}</option>`;
    }).join('');

    return `<section class="section src-upload" data-tour="videos-upload">
      <div class="section-heading"><div><h2>上传录像</h2>
        <p>一份完整录像即可；上传后自动排队抽帧识别，不用再手工触发。</p></div>
        <div class="capture-actions">
          <span class="src-count">${fmt(recordings.length)} 段 · ${bytes(statsInfo.bytes)} / ${bytes(maxBytes)}</span>
        </div>
      </div>
      <div class="src-upload-body">
        ${uploadZone({ id: 'video-file', accept: 'video/*,.mp4,.mov,.mkv,.webm,.avi', multiple: false,
          title: '选择录像', hint: 'mp4 / mov / mkv / webm，上限 ' + bytes(maxBytes) })}
        <label class="src-field">采样帧率<select data-recording-fps>${fpsOptions}</select></label>
        <label class="src-field">识别方式<select data-recording-engine>${engineOptions}</select></label>
        <button class="primary" data-source-action="upload-recording" ${ready ? '' : 'disabled'}>
          ${state.busy === 'upload' ? '正在上传…' : '上传并识别'}</button>
      </div>
      <p class="src-progress" data-upload-progress>${esc(state.progress || '')}</p>
      <p class="capture-hint">识别在本机完成。Mimo 精读更细但慢（CPU 上整段偏久）；只想看时间轴和金币，选「仅快速布局」。</p>
    </section>`;
  }

  function uploadRecording() {
    const input = document.querySelector('[data-source-file="video"]');
    const file = input?.files?.[0];
    const status = state.value?.status || {};
    const maxBytes = Number(state.value?.recordings?.stats?.maxBytes || 0);

    if (!file) { setNotice('先选择要上传的录像文件。', true); paint(); return; }
    if (!(status.ffmpeg && status.ffprobe)) {
      setNotice('未找到 ffmpeg / ffprobe，录屏抽帧不可用。请先安装并加入 PATH。', true);
      paint();
      return;
    }
    if (maxBytes && Number(file.size) > maxBytes) {
      setNotice(`录像 ${bytes(file.size)} 超过上限 ${bytes(maxBytes)}。`, true);
      paint();
      return;
    }

    const setProgress = (text) => {
      state.progress = text;
      const el = document.querySelector('[data-upload-progress]');
      if (el) el.textContent = text;
    };

    state.busy = 'upload';
    setProgress('正在上传录像…');
    paint();

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/recordings?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) setProgress(`正在上传 ${bytes(event.loaded)} / ${bytes(event.total)}…`);
    };
    xhr.onerror = () => {
      state.busy = '';
      setNotice('这次上传没有完成，请重试一次。', true);
      paint();
    };
    xhr.onload = async () => {
      let payload = {};
      try { payload = JSON.parse(xhr.responseText || '{}'); } catch { /* 非 JSON */ }
      if (xhr.status < 200 || xhr.status >= 300) {
        state.busy = '';
        setNotice(payload.detail || `上传失败（${xhr.status}）`, true);
        paint();
        return;
      }
      setProgress('上传完成，正在排队识别…');
      // 选了 Mimo 但没装：自动退回主 OCR，并说明原因，不让上传白等。
      const engine = state.engine === 'mimo' && !mimoState(state.value).ready ? 'rapid' : state.engine;
      try {
        await api(`recordings/${encodeURIComponent(payload.id)}/ocr`
          + `?fps=${encodeURIComponent(state.fps)}`
          + `&engine=${encodeURIComponent(engine)}`
          + '&force=false', { method: 'POST' });
        state.busy = '';
        state.progress = '';
        setNotice(engine === 'mimo'
          ? '已开始识别，进度会自动刷新。'
          : '没装 Mimo，这次用主 OCR 识别；装好后可以点「重新识别」再跑一遍。');
        await refresh();
        paint();
        startPoll();
      } catch (error) {
        state.busy = '';
        setNotice(`已上传但排队失败：${error.message}`, true);
        paint();
      }
    };
    xhr.send(file);
  }

  async function rerunRecording(id) {
    state.busy = `rerun-${id}`;
    setNotice('正在提交重新识别…');
    paint();
    try {
      const engine = state.engine === 'mimo' && !mimoState(state.value).ready ? 'rapid' : state.engine;
      await api(`recordings/${encodeURIComponent(id)}/ocr`
        + `?fps=${encodeURIComponent(state.fps)}`
        + `&engine=${encodeURIComponent(engine)}`
        + '&force=true', { method: 'POST' });
      await refresh();
      setNotice('已重新提交识别。');
      paint();
      startPoll();
    } catch (error) {
      setNotice(error.message, true);
      paint();
    } finally {
      state.busy = '';
    }
  }

  function videosPage(value) {
    const recordings = value.recordings?.recordings || [];
    const channels = value.channels?.channels || [];
    const statsInfo = value.recordings?.stats || {};
    const ocr = value.status || {};
    const ffmpegOk = Boolean(ocr.ffmpeg && ocr.ffprobe);
    const done = recordings.filter((rec) => rec.report?.available).length;
    const running = recordings.filter((rec) => rec.status && !['done', 'error', 'canceled'].includes(rec.status)).length;
    const active = running ? 1 : recordings.length ? 2 : 0;

    const rows = recordings.map((recording) => {
      const report = recording.report || {};
      const coverage = report.coverage || {};
      const ratio = recording.status === 'done' ? 100 : Number(recording.progress || 0);
      const evidence = (recording.evidence || []).length;
      const warningCount = Number(report.warnings || 0);
      const statusText = recording.status === 'done' ? '识别完成'
        : recording.status === 'error' ? '识别失败'
          : recording.stage || '排队中';
      return `<article class="shot-card${recording.status === 'done' ? ' is-ok' : ''}">
        <header class="shot-head">
          <div><h3>${text(recording.name)}</h3>
            <p>${seconds(recording.video?.duration)} · ${recording.video?.width || '—'}×${recording.video?.height || '—'} · ${recording.video?.fps || '—'} fps · ${bytes(recording.size)}</p></div>
          <span class="src-badge ${recording.status === 'done' ? 'is-ok' : recording.status === 'error' ? 'is-warn' : 'is-doing'}">${esc(statusText)}</span>
        </header>
        <div class="src-bar" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, ratio))}%"></i></div>
        <div class="shot-players">
          <span class="shot-player is-mini"><small>进度</small><b>${ratio}</b><i>%</i></span>
          <span class="shot-player is-mini"><small>采样</small><b>${fmt(coverage.samples)}</b><i>帧</i></span>
          <span class="shot-player is-mini"><small>计时</small><b>${fmt(coverage.clock)}</b><i>帧</i></span>
          <span class="shot-player is-mini"><small>击杀</small><b>${fmt(coverage.blueKills)} : ${fmt(coverage.redKills)}</b><i>蓝 : 红</i></span>
          <span class="shot-player is-mini"><small>证据帧</small><b>${fmt(evidence)}</b><i>张</i></span>
          <span class="shot-player is-mini"><small>提示</small><b>${fmt(warningCount)}</b><i>条</i></span>
        </div>
        ${recording.error ? `<p class="capture-hint is-error">${esc(recording.error)}</p>` : ''}
        <footer class="shot-actions">
          <select data-recording-channel="${esc(recording.id)}">
            <option value="">挂到哪一局…</option>${channelOptions(channels)}
          </select>
          <button class="primary" data-source-action="attach-recording" data-recording="${esc(recording.id)}"
            ${report.available ? '' : 'disabled'} title="${report.available ? '' : '先识别出报告才能挂载'}">把报告挂到这一局</button>
          <button class="control" data-source-action="rerun-recording" data-recording="${esc(recording.id)}"
            ${Number(recording.progress) > 0 && recording.status !== 'done' ? 'disabled' : ''}>
            ${state.busy === `rerun-${recording.id}` ? '正在提交…' : '重新识别'}</button>
        </footer>
      </article>`;
    }).join('');

    return withPage('录屏 OCR', '与七张截图成对使用：每局一段完整录像。录什么、怎么传、挂到哪一局，这一页里都能做完。',
      `<div class="src-page">
        ${noticeBox()}
        ${ffmpegOk ? '' : `<div class="capture-notice is-error" role="status">未检测到 ffmpeg / ffprobe，录屏抽帧不可用。请先安装并加入 PATH。</div>`}
        ${steps([['录一局', '加载页 → 整局 → 结算'], ['上传识别', '本机抽帧，不联网'], ['挂到对局', '把报告挂到那一局']], active)}
        ${enginePanel(value)}
        ${videoGuide(Number(statsInfo.maxBytes || 0))}
        ${uploadVideosBlock(value)}
        <section class="section src-results" data-tour="videos-results">
          <div class="section-heading"><div><h2>本机录屏</h2>
            <p>${recordings.length
              ? `共 ${fmt(recordings.length)} 段 · ${fmt(done)} 段已出报告${running ? ` · ${fmt(running)} 段识别中` : ''}；识别完成后把报告挂到对应对局。`
              : '还没有上传过录屏。上传后这里按状态显示进度与报告。'}</p></div>
            <div class="capture-actions"><button class="control" data-source-action="refresh">${icon('refresh')} 刷新</button></div>
          </div>
          <div class="shot-grid">${rows || `<p class="src-empty">还没有上传过录屏。先按上面的三段录一局。</p>`}</div>
        </section>
      </div>`, false);
  }

  /** 把某段录屏的识别报告挂到一局（报告 JSON 直接作为请求体）。 */
  async function attachRecording(id) {
    const select = document.querySelector(`[data-recording-channel="${id}"]`);
    const channelId = select?.value;
    if (!channelId) { setNotice('先选要挂到哪一局。', true); paint(); return; }
    state.busy = `attach-${id}`;
    setNotice('正在挂载录屏报告…');
    paint();
    try {
      const report = await api(`recordings/${encodeURIComponent(id)}/report`);
      await api(`channels/${encodeURIComponent(channelId)}/video?name=${encodeURIComponent(`录像报告-${id}.json`)}`,
        { method: 'POST', raw: JSON.stringify(report) });
      await refresh();
      setNotice('录屏报告已挂到这一局；和七张截图凑齐后就能在缺失值审查里保存。');
    } catch (error) {
      setNotice(`挂载失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  // ---------------- 回放 ----------------

  function replaysPage(value) {
    const replays = value.replays?.replays || [];
    const channels = value.channels?.channels || [];

    const cards = replays.map((replay, index) => {
      const header = replay.header || {};
      const blocks = replay.blocks || [];
      const abc = replay.abc || {};
      const paired = replay.pairingStatus || '';
      const players = blocks.slice(0, 10).map((block) => `<span class="shot-player${block.self ? ' is-self' : ''}">
        <small>${block.camp === 1 ? '蓝' : '红'}${(block.position ?? 0) + 1}</small>
        <b>${text(block.name)}</b><i>${text(block.heroName)}</i></span>`).join('');
      return `<article class="shot-card">
        <header class="shot-head">
          <div><h3>${text(header.nickname || header.userName || '未命名回放')}</h3>
            <p>版本 ${text((header.versions || []).join(' / '))} · ${fmt(header.totalFrameNum)} 帧 · ${bytes(abc.size)}</p></div>
          <div class="shot-meta">
            <span class="result">${esc(replay.parserVersion || '已解析')}</span>
            ${paired ? `<span class="result pending">${esc(paired)}</span>` : ''}
          </div>
        </header>
        <div class="shot-players">${players || '<span class="capture-hint">没有解析出参战名单。</span>'}</div>
        <details class="shot-detail">
          <summary>查看十人指令与评分</summary>
          ${table(['阵营', '分路', '昵称', '英雄', '评分', '金币事件', '技能事件'],
            blocks.map((block) => [
              block.camp === 1 ? '蓝' : '红',
              `第 ${(block.position ?? 0) + 1} 路`,
              text(block.name), text(block.heroName),
              fmt(block.score, 1), fmt(block.goldEvents), fmt(block.skillEvents)]))}
        </details>
        <footer class="shot-actions">
          <select data-replay-channel="${index}"><option value="">选择要挂载的对局…</option>${channelOptions(channels, pendingChannelId())}</select>
          <button class="control" data-source-action="attach-replay" data-replay="${esc(abc.sha256 || '')}" data-index="${index}">挂到所选通道</button>
        </footer>
      </article>`;
    }).join('');

    return withPage('回放（研究中）', '尚不作为采集来源：回放解析的字段口径还没定下来，先别把这里的结论当正式数据。',
      backLink()
      + `<div class="capture-notice is-error" role="status">回放解析还在研究中，没有接入采集档位。页面仅供内部查看，不要据此入库。</div>`
      + stats([
        ['已解析回放', fmt(replays.length), '来自本机回放文件'],
        ['已配对的', fmt(replays.filter((r) => !r.pairingStatus).length), '没有配对冲突的'],
        ['十人齐全', fmt(replays.filter((r) => (r.blocks || []).length >= 10).length), '解析出完整名单'],
        ['对局通道', fmt(channels.length), '可挂载到任一审查记录'],
      ])
      + block('回放文件', '回放只补位置与指令，不补赛后统计；终局数值仍以截图或数据包为准。',
        `<div class="shot-grid">${cards || empty('还没有解析过回放文件。')}</div>`)
      , false);
  }

  function backLink() {
    return '<p class="sv-back"><a class="control" href="#ingest">← 返回营地同步</a></p>';
  }

  function scopeNote() {
    return backLink() + '<div class="scope-note"><span>口径</span> 本页直接读本机素材库，'
      + '不受顶部「数据范围」影响；素材可能包含非训练赛。</div>';
  }


  // ---------------- 导入表格 ----------------

  function tablePage(value) {
    const spec = value?.spec;
    const sheet = spec?.sheet;

    const upload = `<div class="upload-area">
      <span class="upload-icon">${icon('sources')}</span>
      <h2>选择本局十人表</h2>
      <p>先选择文件，检查工作表、字段和数据粒度；预览阶段不会改动原始文件，也不会写入正式统计。</p>
      <label class="primary upload-button">选择表格<input type="file" data-import-file accept=".csv,.tsv,.xlsx,.xlsm"></label>
      <p data-import-status role="status"></p>
    </div><div data-import-preview></div>`;

    if (!sheet) {
      return withPage('导入表格', '选填 · 补充 —— 只在营地与截图都没有某个字段时才需要手填。',
        backLink()
        + noticeBox()
        + block('上传', '支持 CSV / TSV / XLSX / XLSM，单个文件不超过 20 MB。', upload)
        + `<div class="capture-notice is-error" role="status">读取不到字段规格文件 capture-guide/requirements.json，无法展示字段要求。请确认通过 server.py 启动（该文件由 /assets 提供）。</div>`, false);
    }

    const requiredCount = sheet.columns.filter((column) => column.required).length;
    const columnRows = sheet.columns.map((column) => `<tr class="${column.required ? 'is-required' : ''}">
      <td class="tbl-col-name">${esc(column.name)}</td>
      <td class="tbl-col-field"><code>${esc(column.field)}</code></td>
      <td class="tbl-col-flag">${column.required ? '<span class="result pending">必填</span>' : '<span class="tbl-optional">选填</span>'}</td>
      <td class="tbl-col-rule">${esc(column.rule)}</td>
    </tr>`).join('');

    const lanes = (sheet.positions || []).join(' / ');

    return withPage('导入表格', '选填 · 补充 —— 表格只进分析数据集（在「数据范围」里勾「表格导入」查看），不写营地口径的正式统计；正式统计仍要本局营地回放。',
      backLink()
      + noticeBox()
      + block('上传与预览', '支持 CSV / TSV / XLSX / XLSM，单个文件不超过 20 MB。先预览识别结果，确认后再导入。', upload)
      + block('表格长什么样', '一行一个人，一局正好十行。',
        `<div class="sv-spec-grid">
          <div><b>行数</b><span>${fmt(sheet.rows)} 行（我方 5 + 对方 5）</span></div>
          <div><b>阵营</b><span>${(sheet.sides || []).map((s) => (s === 'blue' ? 'blue（蓝方）' : 'red（红方）')).join(' / ')}，每方 5 行</span></div>
          <div><b>分路</b><span>${esc(lanes)}，每方每个分路各 1 人</span></div>
          <div><b>唯一性</b><span>选手昵称十行不重复；每方英雄不重复</span></div>
          <div><b>本队阵营</b><span>blue 或 red，十行一致；多局逐局不同</span></div>
        </div>
        <p class="capture-hint">同一张表可以往下追加多局：每局十行、对局ID不同；跨局汇总不要放进来。</p>`)
      + block('字段要求', `共 ${sheet.columns.length} 列，其中 ${requiredCount} 列必填。`,
        `<div class="table-wrap sv-spec-wrap"><table class="sv-spec-table"><thead><tr>
          <th>列名</th><th>字段</th><th>要求</th><th>规则</th>
        </tr></thead><tbody>${columnRows}</tbody></table></div>`)
      + block('模板与示例', '模板列名不要改；示例可以对照格式，其中「十人一局」那份填好了完整数据，可以直接试导入。',
        `<div class="sv-downloads">
          <a class="control" href="/assets/capture-guide/match-template.xlsx" download>${icon('sources')} 下载 XLSX 模板</a>
          <a class="control" href="/assets/capture-guide/match-template.csv" download>${icon('sources')} 下载 CSV 模板</a>
          <a class="control" href="/assets/capture-guide/match-example.csv" download>${icon('sources')} 下载示例（对照格式）</a>
          <a class="control" href="/assets/capture-guide/match-sample.csv" download>${icon('sources')} 下载示例 · 十人一局（可直接试导入）</a>
        </div>
        <p class="capture-hint">示例是虚构数据。试导入后在「数据范围 → 表格导入」勾选才看得到；正式记录请换掉对局 ID、日期和十人数据。</p>`)
      + block('最常见的三个错', '导入失败的绝大多数都是这三种。',
        `<ul class="sv-pitfalls">
          <li><b>对局 ID 十行不一致</b> —— 同一局十行必须同一个 ID，且不能用示例里的编号。</li>
          <li><b>数值写成「1.2万」</b> —— 金币、输出、承伤都要原始整数，不要带单位或缩写。</li>
          <li><b>参团率写成 0.625</b> —— 要 0–100 的数值，直接写 62.5。</li>
        </ul>`)
      , false);
  }

  // ---------------- 渲染分发 ----------------

  function render(name, value) {
    if (name === 'capture') return tablePage(value);
    if (name === 'shots') return shotsPage(value);
    if (name === 'videos') return videosPage(value);
    if (name === 'replays') return replaysPage(value);
    return withPage(PAGE_TITLE[name] || '素材', '', empty('未知素材页。'), false);
  }

  // ---------------- 交互 ----------------

  async function uploadShots() {
    const input = document.querySelector('[data-source-file="images"]');
    const files = input?.files ? [...input.files] : [];
    if (!files.length) { setNotice('先选择要上传的截图。', true); paint(); return; }
    state.busy = 'upload';
    setNotice(`正在上传 ${files.length} 张截图…`);
    paint();
    const failed = [];
    let done = 0;
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
    await refresh();
    setNotice(failed.length
      ? `已上传 ${done} 张，失败 ${failed.length} 张：${failed[0]}`
      : `已上传 ${done} 张截图，识别排队中；识别完会自动分组，不用手动刷新。`, failed.length > 0);
    paint();
    startShotsPoll();
  }

  /** 截图 OCR 是排队跑的：上传后自动轮询，等所有图都进了分组就停。 */
  function startShotsPoll() {
    stopPoll();
    state.pollFor = 'shots';
    let ticks = 0;
    state.poll = setInterval(async () => {
      ticks += 1;
      try {
        const value = await load('shots', '', undefined);
        if (state.name !== 'shots') { stopPoll(); return; }
        paint();
        const images = value.images?.images || [];
        const groups = value.images?.groups || [];
        const grouped = new Set(groups.flatMap((group) => group.imageIds || []));
        const pending = images.filter((image) => !grouped.has(image.id)).length;
        if (!pending || ticks >= 30) {
          stopPoll();
          if (!pending) setNotice(`七张截图已识别并分组（${groups.length} 组）。`);
          paint();
        }
      } catch { /* 单次失败不打断轮询 */ }
    }, 4000);
  }

  async function attachShots(index) {
    const select = document.querySelector(`[data-shot-channel="${index}"]`);
    const channelId = select?.value;
    if (!channelId) { setNotice('先为这一组选择一个要挂载的对局。', true); paint(); return; }
    const groups = state.value?.images?.groups || [];
    const imageIds = groups[Number(index)]?.imageIds || [];
    if (!imageIds.length) { setNotice('这一组没有可挂载的截图。', true); paint(); return; }
    state.busy = 'attach';
    setNotice(`正在把 ${imageIds.length} 页截图挂到通道…`);
    paint();
    try {
      await api(`channels/${encodeURIComponent(channelId)}/screenshot`, { method: 'POST', body: { imageIds } });
      await refresh();
      // 补录过来的那局已经用上了，别再预选下一次。
      if (pendingChannelId() === channelId) clearPendingChannel();
      setNotice(`已挂载 ${imageIds.length} 页截图到该通道。`);
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function attachReplay(index, replayId) {
    const select = document.querySelector(`[data-replay-channel="${index}"]`);
    const channelId = select?.value;
    if (!channelId) { setNotice('先为这份回放选择一个要挂载的对局。', true); paint(); return; }
    state.busy = 'attach';
    setNotice('正在挂载回放…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(channelId)}/replay`, { method: 'POST', body: { replayId } });
      await refresh();
      setNotice('回放已挂到该通道。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function click(event) {
    const button = event.target.closest('[data-source-action]');
    if (!button) return false;
    const action = button.dataset.sourceAction;
    if (action === 'refresh') {
      state.notice = null;
      await refresh();
      paint();
      return true;
    }
    if (action === 'upload-shots') { await uploadShots(); return true; }
    if (action === 'upload-recording') { uploadRecording(); return true; }
    if (action === 'rerun-recording') { await rerunRecording(button.dataset.recording); return true; }
    if (action === 'attach-shots') { await attachShots(button.dataset.group); return true; }
    if (action === 'attach-recording') { await attachRecording(button.dataset.recording); return true; }
    if (action === 'install-mimo') { await installOcr('mimo'); return true; }
    if (action === 'install-rapid') { await installOcr('rapid'); return true; }
    if (action === 'install-ffmpeg') { await installOcr('ffmpeg'); return true; }
    if (action === 'engine-toggle') { state.engineOpen = !(state.engineOpen ?? false); paint(); return true; }
    if (action === 'recheck-engine') { await refresh(); setNotice('已重新检测引擎状态。'); paint(); return true; }
    if (action === 'attach-replay') {
      await attachReplay(button.dataset.index, button.dataset.replay);
      return true;
    }
    return false;
  }

  function change(event) {
    const files = event.target.closest('[data-source-file]');
    if (files) {
      const picked = files.files ? [...files.files] : [];
      const note = files.closest('.src-drop')?.querySelector('[data-file-note]');
      if (note) {
        note.textContent = picked.length
          ? `已选择 ${picked.length} 个：${picked.slice(0, 3).map((file) => file.name).join('、')}${picked.length > 3 ? '…' : ''}`
          : '还没有选择文件';
      }
      return true;
    }
    const fps = event.target.closest('[data-recording-fps]');
    if (fps) { state.fps = fps.value; localStorage.setItem('v3-recording-fps', fps.value); return true; }
    const engine = event.target.closest('[data-recording-engine]');
    if (engine) { state.engine = engine.value; localStorage.setItem('v3-recording-engine', engine.value); return true; }
    return false;
  }

  function afterRender() {
    // 切换页签时清掉上一次的提示，避免串页
    if (!['#shots', '#videos', '#replays'].includes(location.hash)) state.notice = null;
    // 离开录屏页就停掉轮询，别继续打接口
    if (state.pollFor && location.hash !== '#' + state.pollFor) stopPoll();
    // 安装是服务端的活：回到 OCR 页发现还在装，就接着显示进度（切页面不会中断）。
    const install = state.value?.install;
    if (install && (install.running || install.phase === 'done' || install.phase === 'error')) {
      state.install = install;
      if (install.running) {
        renderInstallWidget(install);
        startInstallWatch();
      }
    }
  }

  return { load, render, click, change, afterRender };
}





