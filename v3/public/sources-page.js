/* 采集的三个素材来源页：截图 OCR / 录屏 / 回放。
 *
 * 全部走 V1 的根接口：
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

const V1_API = '/api/';

async function v1(path, { method = 'GET', body, signal, raw } = {}) {
  const init = { method, cache: 'no-store', signal };
  if (raw) {
    init.body = raw;
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(V1_API + path, init);
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* 非 JSON */ }
    throw new Error(typeof detail === 'string' ? detail
      : '采集接口不可用。素材页需要由 server.py 提供（V2 独立运行时不带采集）。');
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
    progress: '', poll: null };
  const PAGE_TITLE = { shots: '截图 OCR', videos: '录屏', replays: '回放' };

  // ---------------- 数据 ----------------

  async function load(name, _key, signal) {
    state.name = name;
    let value;
    if (name === 'shots') {
      const [images, channels] = await Promise.all([
        v1('postgame/images', { signal }),
        v1('channels', { signal }).catch(() => ({ channels: [] })),
      ]);
      value = { images, channels };
    } else if (name === 'videos') {
      const [recordings, status] = await Promise.all([
        v1('recordings', { signal }),
        v1('ocr/status', { signal }).catch(() => ({})),
      ]);
      value = { recordings, status };
    } else if (name === 'capture') {
      const [spec, channels] = await Promise.all([
        fetch('/assets/capture-guide/requirements.json', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null)).catch(() => null),
        v1('channels', { signal }).catch(() => ({ channels: [] })),
      ]);
      value = { spec, channels };
    } else {
      const [replays, channels] = await Promise.all([
        v1('replays', { signal }),
        v1('channels', { signal }).catch(() => ({ channels: [] })),
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

  // ---------------- 截图 ----------------

  function shotsPage(value) {
    const groups = value.images?.groups || [];
    const images = value.images?.images || [];
    const channels = value.channels?.channels || [];

    const imageById = new Map(images.map((image) => [image.id, image]));
    const totalWarn = groups.reduce((sum, group) => sum + (group.warnings || []).length, 0);
    const pages = groups.reduce((sum, group) => sum + (group.imageIds || []).length, 0);
    const matched = groups.filter((group) => group.match?.date).length;

    const cards = groups.map((group, index) => {
      const match = group.match || {};
      const open = state.openGroup === String(index);
      const ids = group.imageIds || [];
      const players = group.players || [];
      const warned = (group.warnings || []).length;
      const score = match.score ? `${match.score.left} : ${match.score.right}` : '—';
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
        return `<span class="shot-player"><small>${side}${(player.slot ?? 0) + 1}</small><b>${text(nick)}</b><i>${text(hero)}</i></span>`;
      }).join('');

      return `<article class="shot-card">
        <header class="shot-head">
          <div><h3>${esc(match.date || '未归档的一局')}${match.time ? ` · ${esc(match.time)}` : ''}</h3>
            <p>${esc(match.mode || '模式未知')} · ${seconds(match.durationSec)} · ${esc(score)} · ${match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '结果未知'}</p></div>
          <div class="shot-meta"><span>${ids.length} 页</span>${warned ? `<span class="result pending">${warned} 条提示</span>` : '<span class="result">无提示</span>'}</div>
        </header>
        <div class="shot-players">${playerList || '<span class="capture-hint">这一组还没有识别出选手。</span>'}</div>
        <details class="shot-detail" ${open ? 'open' : ''} data-open-group="${index}">
          <summary>查看 ${ids.length} 页明细与提示</summary>
          <ol class="shot-pages">${pageList}</ol>
          ${(group.warnings || []).length ? `<ul class="shot-warnings">${group.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
        </details>
        <footer class="shot-actions">
          <select data-shot-channel="${index}"><option value="">选择采集通道…</option>${channelOptions(channels)}</select>
          <button class="control" data-source-action="attach-shots" data-group="${index}" ${ids.length ? '' : 'disabled'}>挂到所选通道</button>
        </footer>
      </article>`;
    }).join('');

    return withPage('截图 OCR', '兜底路径：营地十人面板拿不到时才走这里 —— 七张截图 + 一段录屏，两者一起才能过审核门槛。纯本机识别，不联网。',
      scopeNote()
      + noticeBox()
      + stats([
        ['截图分组', fmt(groups.length), `${fmt(matched)} 组已识别出对局日期`],
        ['截图页数', fmt(pages), `共 ${images.length} 张`],
        ['待处理提示', fmt(totalWarn), totalWarn ? '展开各组查看具体条目' : '当前没有问题项'],
        ['可挂载组', fmt(groups.filter((g) => (g.imageIds || []).length).length), '有页面才能挂到通道'],
      ])
      + uploadBlock()
      + block('已识别的截图分组', '每组对应一局；挂载后该局的截图来源会标记为完成。',
        `<div class="shot-grid">${cards || empty('还没有识别过赛后截图。')}</div>`)
      , false);
  }

  function uploadBlock() {
    return block('上传截图', '支持 PNG / JPEG / WebP，可一次多选；上传后自动排队识别。',
      `<div class="capture-inline-form">
        <label>选择截图<input type="file" multiple accept="image/png,image/jpeg,image/webp" data-source-file="images"></label>
        <button class="primary" data-source-action="upload-shots" ${state.busy === 'upload' ? 'disabled' : ''}>${state.busy === 'upload' ? '正在上传…' : '上传并识别'}</button>
       </div>
       <p class="capture-hint">识别在本机完成；一页通常几秒，Mimo 精读在 CPU 上整页约 2–3 分钟。</p>`,
      `<button class="control" data-source-action="refresh">${icon('refresh')} 刷新</button>`);
  }

  // ---------------- 录屏 ----------------


  // ---------------- 录屏上传 ----------------

  const FPS_OPTIONS = [['0.5', '0.5 fps（更快）'], ['1', '1 fps（推荐）'], ['2', '2 fps（更细）']];
  const ENGINE_OPTIONS = [['mimo', 'Mimo 精读 + 快速布局'], ['rapid', '仅快速布局']];

  function stopPoll() {
    if (state.poll) { clearInterval(state.poll); state.poll = null; }
  }

  /** 有任务在跑时每 3 秒刷新一次；任务清空后自动停。 */
  function startPoll() {
    stopPoll();
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

  function uploadVideosBlock(value) {
    const status = value.status || {};
    const statsInfo = value.recordings?.stats || {};
    const ready = Boolean(status.ffmpeg && status.ffprobe);
    const maxBytes = Number(statsInfo.maxBytes || 0);

    const fpsOptions = FPS_OPTIONS.map(([v, label]) =>
      `<option value="${v}" ${state.fps === v ? 'selected' : ''}>${esc(label)}</option>`).join('');
    const engineOptions = ENGINE_OPTIONS.map(([v, label]) =>
      `<option value="${v}" ${state.engine === v ? 'selected' : ''}>${esc(label)}</option>`).join('');

    const body = `<div class="capture-inline-form">
        <label>录像文件<input type="file" accept="video/*,.mp4,.mov,.mkv,.webm,.avi" data-source-file="video" ${ready ? '' : 'disabled'}></label>
        <label>采样帧率<select data-recording-fps>${fpsOptions}</select></label>
        <label>识别方式<select data-recording-engine>${engineOptions}</select></label>
        <button class="primary" data-source-action="upload-recording" ${ready ? '' : 'disabled'}>
          ${state.busy === 'upload' ? '正在上传…' : '上传并识别'}</button>
      </div>
      <p class="capture-hint" data-upload-progress>${esc(state.progress || '')}</p>
      <p class="capture-hint">上限 ${bytes(maxBytes)} · 识别在本机完成；Mimo 精读在 CPU 上偏慢，只是看时间轴和金币可以选「仅快速布局」。</p>`;

    return block('上传录屏', '一份完整录像即可；上传后自动排队识别，不需要再手工触发。', body);
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
      setNotice('上传失败，请确认本地服务仍在运行。', true);
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
      try {
        await v1(`recordings/${encodeURIComponent(payload.id)}/ocr`
          + `?fps=${encodeURIComponent(state.fps)}`
          + `&engine=${encodeURIComponent(state.engine)}`
          + '&force=false', { method: 'POST' });
        state.busy = '';
        state.progress = '';
        setNotice('已开始识别，进度会自动刷新。');
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
      await v1(`recordings/${encodeURIComponent(id)}/ocr`
        + `?fps=${encodeURIComponent(state.fps)}`
        + `&engine=${encodeURIComponent(state.engine)}`
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
    const statsInfo = value.recordings?.stats || {};
    const ocr = value.status || {};
    const ffmpegOk = Boolean(ocr.ffmpeg && ocr.ffprobe);

    const rows = recordings.map((recording) => {
      const report = recording.report || {};
      const coverage = report.coverage || {};
      const ratio = recording.status === 'done' ? 100 : Number(recording.progress || 0);
      const evidence = (recording.evidence || []).length;
      return `<article class="shot-card">
        <header class="shot-head">
          <div><h3>${text(recording.name)}</h3>
            <p>${seconds(recording.video?.duration)} · ${recording.video?.width || '—'}×${recording.video?.height || '—'} · ${recording.video?.fps || '—'} fps · ${bytes(recording.size)}</p></div>
          <div class="shot-meta">
            <span class="result ${recording.status === 'done' ? '' : 'pending'}">${esc(recording.stage || recording.status || '未知')}</span>
            <span>${ratio}%</span>
          </div>
        </header>
        <div class="shot-players">
          <span class="shot-player"><small>采样</small><b>${fmt(coverage.samples)}</b><i>帧</i></span>
          <span class="shot-player"><small>计时</small><b>${fmt(coverage.clock)}</b><i>帧</i></span>
          <span class="shot-player"><small>蓝方击杀</small><b>${fmt(coverage.blueKills)}</b><i>次</i></span>
          <span class="shot-player"><small>红方击杀</small><b>${fmt(coverage.redKills)}</b><i>次</i></span>
          <span class="shot-player"><small>证据帧</small><b>${fmt(evidence)}</b><i>张</i></span>
          <span class="shot-player"><small>提示</small><b>${fmt(report.warnings)}</b><i>条</i></span>
        </div>
        ${recording.error ? `<p class="capture-hint is-error">${esc(recording.error)}</p>` : ''}
        <footer class="shot-actions">
          <span class="capture-hint">${report.available ? '识别报告已生成' : '还没有识别报告'} · 引擎 ${text(recording.engine)} · 采样 ${text(recording.sampleFps)} fps</span>
          <button class="control" data-source-action="rerun-recording" data-recording="${esc(recording.id)}"
            ${Number(recording.progress) > 0 && recording.status !== 'done' ? 'disabled' : ''}>
            ${state.busy === `rerun-${recording.id}` ? '正在提交…' : '重新识别'}</button>
        </footer>
      </article>`;
    }).join('');

    return withPage('录屏', '兜底路径：与七张截图成对使用；已导入营地十人面板时不需要录屏。',
      scopeNote()
      + noticeBox()
      + (ffmpegOk ? '' : `<div class="capture-notice is-error" role="status">未检测到 ffmpeg / ffprobe，录屏抽帧不可用。请先安装并加入 PATH。</div>`)
      + stats([
        ['本机录屏', fmt(recordings.length), `占用 ${bytes(statsInfo.bytes)} / 上限 ${bytes(statsInfo.maxBytes)}`],
        ['已出报告', fmt(recordings.filter((r) => r.report?.available).length), '识别完成后可生成报告'],
        ['识别中', fmt(recordings.filter((r) => r.status && r.status !== 'done').length), '按进度显示'],
        ['剩余空间', bytes(statsInfo.freeBytes), '录屏目录所在磁盘'],
      ])
      + block('本机录屏', '一份录屏对应一次抽帧识别，不创建正式比赛，也不进入英雄胜率。',
        `<div class="shot-grid">${rows || empty('还没有上传过录屏。')}</div>`)
      + uploadVideosBlock(value)
      , false);
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
          <select data-replay-channel="${index}"><option value="">选择采集通道…</option>${channelOptions(channels)}</select>
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
        ['采集通道', fmt(channels.length), '可挂载到任一通道'],
      ])
      + block('回放文件', '回放只补位置与指令，不补赛后统计；终局数值仍以截图或数据包为准。',
        `<div class="shot-grid">${cards || empty('还没有解析过回放文件。')}</div>`)
      , false);
  }

  function backLink() {
    return '<p class="sv-back"><a class="control" href="#ingest">← 返回营地同步</a></p>';
  }

  function scopeNote() {
    return backLink() + '<div class="scope-note"><span>口径</span> 本页直接读 V1 的本机素材库，'
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

    return withPage('导入表格', '选填 · 补充 —— 只在营地与截图都没有某个字段时才需要手填。表格必须按下面的列结构，否则导入后进不了平台。',
      backLink()
      + noticeBox()
      + block('上传与预览', '支持 CSV / TSV / XLSX / XLSM，单个文件不超过 20 MB。先预览识别结果，确认后再导入。', upload)
      + block('表格长什么样', '一行一个人，一局正好十行。',
        `<div class="sv-spec-grid">
          <div><b>行数</b><span>${fmt(sheet.rows)} 行（我方 5 + 对方 5）</span></div>
          <div><b>阵营</b><span>${(sheet.sides || []).map((s) => (s === 'blue' ? 'blue（蓝方）' : 'red（红方）')).join(' / ')}，每方 5 行</span></div>
          <div><b>分路</b><span>${esc(lanes)}，每方每个分路各 1 人</span></div>
          <div><b>唯一性</b><span>选手昵称十行不重复；每方英雄不重复</span></div>
        </div>
        <p class="capture-hint">多局或跨局汇总不要放进本局表格，走「批量导入」。</p>`)
      + block('字段要求', `共 ${sheet.columns.length} 列，其中 ${requiredCount} 列必填。`,
        `<div class="table-wrap sv-spec-wrap"><table class="sv-spec-table"><thead><tr>
          <th>列名</th><th>字段</th><th>要求</th><th>规则</th>
        </tr></thead><tbody>${columnRows}</tbody></table></div>`)
      + block('模板与示例', '直接用模板填，列名不要改；示例文件可以对照格式。',
        `<div class="sv-downloads">
          <a class="control" href="/assets/capture-guide/match-template.xlsx" download>${icon('sources')} 下载 XLSX 模板</a>
          <a class="control" href="/assets/capture-guide/match-template.csv" download>${icon('sources')} 下载 CSV 模板</a>
          <a class="control" href="/assets/capture-guide/match-example.csv" download>${icon('sources')} 下载示例</a>
        </div>`)
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
        const uploaded = await v1(`images?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
        if (uploaded?.id) {
          await v1(`postgame/images/${encodeURIComponent(uploaded.id)}/ocr`, { method: 'POST' });
          done += 1;
        }
      } catch (error) {
        failed.push(`${file.name}：${error.message}`);
      }
    }
    state.busy = '';
    await refresh();
    setNotice(failed.length
      ? `已识别 ${done} 张，失败 ${failed.length} 张：${failed[0]}`
      : `已上传并识别 ${done} 张截图。`, failed.length > 0);
    paint();
  }

  async function attachShots(index) {
    const select = document.querySelector(`[data-shot-channel="${index}"]`);
    const channelId = select?.value;
    if (!channelId) { setNotice('先为这一组选择一个采集通道。', true); paint(); return; }
    const groups = state.value?.images?.groups || [];
    const imageIds = groups[Number(index)]?.imageIds || [];
    if (!imageIds.length) { setNotice('这一组没有可挂载的截图。', true); paint(); return; }
    state.busy = 'attach';
    setNotice(`正在把 ${imageIds.length} 页截图挂到通道…`);
    paint();
    try {
      await v1(`channels/${encodeURIComponent(channelId)}/screenshot`, { method: 'POST', body: { imageIds } });
      await refresh();
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
    if (!channelId) { setNotice('先为这份回放选择一个采集通道。', true); paint(); return; }
    state.busy = 'attach';
    setNotice('正在挂载回放…');
    paint();
    try {
      await v1(`channels/${encodeURIComponent(channelId)}/replay`, { method: 'POST', body: { replayId } });
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
    if (action === 'attach-replay') {
      await attachReplay(button.dataset.index, button.dataset.replay);
      return true;
    }
    return false;
  }

  function change(event) {
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
    if (location.hash !== '#videos') stopPoll();
  }

  return { load, render, click, change, afterRender };
}
