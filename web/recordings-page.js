import {renderCollectionGuide} from '/assets/collection-guide.js?v=6';
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, digits = 0) => v == null ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: digits});
const bytes = (v) => v == null ? '—' : v >= 1024 ** 3 ? `${(v / 1024 ** 3).toFixed(2)} GB` : v >= 1024 ** 2 ? `${(v / 1024 ** 2).toFixed(1)} MB` : `${Math.round(v / 1024)} KB`;
const clock = (v) => v == null ? '—' : `${Math.floor(v / 60)}:${String(Math.floor(v % 60)).padStart(2, '0')}`;
const pct = (v, digits = 1) => v == null ? '—' : `${Number(v).toFixed(digits)}%`;
const when = (v) => v ? new Date(v * 1000).toLocaleString('zh-CN', {hour12: false}) : '—';
const STATUS = {uploaded: '待识别', queued: '排队中', running: '识别中', done: '已完成', error: '失败', cancelled: '已取消'};
const SIDE = {blue: '蓝方', red: '红方'};
let pollTimer = null;
let selectedId = null;
let reportCache = {};

function statusTag(meta, job) {
  const status = job && ['queued', 'running'].includes(job.status) ? job.status : meta.status;
  const klass = status === 'done' ? '' : status === 'error' ? 'red' : status === 'running' || status === 'queued' ? 'amber' : 'gray';
  return `<span class="tag ${klass}">${STATUS[status] || esc(status)}</span>`;
}

function progressBar(meta, job) {
  if (!job || !['queued', 'running'].includes(job.status)) return '';
  return `<div class="recording-progress" title="${esc(job.stage || '')}"><i style="width:${Math.max(2, Math.min(100, Number(job.progress) || 0))}%"></i></div>
    <small class="helper">${esc(job.stage || '')} ${job.progress != null ? `· ${job.progress}%` : ''}</small>`;
}

function engineStatus(status) {
  const mimo = status?.mimo || {};
  const rapid = status?.rapid || {};
  return `<div class="recording-engine-grid">
    <div class="recording-engine ${mimo.available ? 'ok' : 'bad'}"><span>Mimo OCR</span><strong>${mimo.available ? 'mimo-ocr-0' : '未找到模型'}</strong><small>${mimo.available ? `本地 · ${esc(mimo.device || 'cpu')} · 缓存 ${num(mimo.cacheFiles)} 张` : esc(mimo.note || '请设置 MIMO_OCR_MODEL')}</small></div>
    <div class="recording-engine ${rapid.available ? 'ok' : 'bad'}"><span>快速布局</span><strong>RapidOCR</strong><small>${rapid.available ? '逐帧 HUD / 计时 / 金币 / 击杀' : '未安装 rapidocr-onnxruntime'}</small></div>
    <div class="recording-engine ${status?.ffmpeg && status?.ffprobe ? 'ok' : 'bad'}"><span>视频解码</span><strong>ffmpeg</strong><small>${status?.ffmpeg && status?.ffprobe ? '已就绪' : '未找到 ffmpeg / ffprobe'}</small></div>
    <div class="recording-engine"><span>任务队列</span><strong>${(status?.jobs || []).filter(job => ['queued', 'running'].includes(job.status)).length}</strong><small>单线程；避免 CPU 争抢</small></div>
  </div>`;
}

function checklist() {
  return `<details class="recording-check"><summary>录屏采集要求 / 核对清单</summary>
    <ol>
      <li><b>完整回放：</b>从回放列表或加载页开始录，录到结算或至少录完整局；中途不要暂停、倍速或剪辑。</li>
      <li><b>固定 16:9：</b>建议 1600×900 或更高；不要竖屏、画中画、裁切或加遮挡。</li>
      <li><b>打开面板：</b>对局中定期打开记分板（战绩页）几秒；团队面板布局保持打开时，逐帧 KDA/金币最完整。</li>
      <li><b>加载页：</b>保留双方五人英雄与昵称卡片；这是英雄身份的主证据。</li>
      <li><b>一局一个文件：</b>不要把多局拼在一个视频里；不同局请分开上传。</li>
      <li><b>只读：</b>识别在本机完成，不上传云端，不修改游戏或回放文件。</li>
    </ol>
    <p class="helper">Mimo 精读会读取加载页英雄/昵称和记分板名字；逐帧计时、金币、击杀仍由快速布局引擎读取。CPU 上 1 fps 约 1–2 分钟，Mimo 精读再加 1–3 分钟。</p>
  </details>`;
}

function lineups(report) {
  const data = report?.lineups || {};
  const camp = (side) => {
    const rows = data[side] || [];
    if (!rows.length) return `<div class="recording-lineup"><h3>${SIDE[side]}</h3><p class="helper">未读到加载页阵容。</p></div>`;
    return `<div class="recording-lineup"><h3>${SIDE[side]} <small>${rows.filter(row => row.hero).length}/5 英雄</small></h3>
      ${rows.map(row => `<div class="recording-player"><span>${row.slot + 1}</span><strong>${esc(row.hero || '未识别')}</strong>
        <small>${esc(row.nickname || '未读昵称')}</small>${row.heroStatus === 'candidate' ? '<em>候选</em>' : ''}${row.heroSource === 'mimo' ? '<em class="mimo">Mimo</em>' : ''}</div>`).join('')}</div>`;
  };
  return `<div class="recording-lineups">${camp('blue')}${camp('red')}</div>`;
}

function timeline(report) {
  const rows = (report?.timeline || []).slice(-10);
  if (!rows.length) return '<p class="helper">没有可用的对局时间轴。</p>';
  return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>蓝金币</th><th>红金币</th><th>经济差</th><th>蓝击杀</th><th>红击杀</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${clock(row.gameTime)}</td><td>${num(row.blueGold)}</td><td>${num(row.redGold)}</td><td>${row.goldDiff == null ? '—' : (row.goldDiff >= 0 ? '+' : '') + num(row.goldDiff)}</td><td>${num(row.blueKills)}</td><td>${num(row.redKills)}</td></tr>`).join('')}
  </tbody></table></div>`;
}

function scoreboard(report) {
  const snapshots = (report?.scoreboard?.snapshots || []).filter(item => item.valid).slice(-2);
  if (!snapshots.length) return '<p class="helper">没有通过校验的记分板快照；只在打开记分板时才有逐人经济。</p>';
  return snapshots.map(snapshot => `<div class="recording-snapshot"><strong>${clock(snapshot.gameTime)} 快照</strong>
    <div class="table-wrap"><table><thead><tr><th>阵营</th><th>行</th><th>英雄</th><th>KDA</th><th>金币</th></tr></thead><tbody>
    ${(snapshot.players || []).map(player => `<tr><td>${SIDE[player.camp] || esc(player.camp)}</td><td>${(player.row ?? 0) + 1}</td><td>${esc(player.hero || '—')}</td><td>${(player.kda || []).join('/') || '—'}</td><td>${num(player.gold)}</td></tr>`).join('')}
    </tbody></table></div></div>`).join('');
}

function mimoTeamPanel(report) {
  const frames = report?.mimo?.teamPanel || [];
  if (!frames.length) return '';
  return `<div class="recording-mimo"><div class="panel-header"><h2>Mimo 团队面板快照</h2><span class="tag">${frames.length} 个时间点</span></div>
    ${frames.map(frame => `<div class="recording-snapshot"><strong>${frame.gameTime == null ? '时间未读' : clock(frame.gameTime)}</strong> ${frame.complete ? '<span class="tag">双方齐全</span>' : '<span class="tag amber">部分</span>'}
      <div class="table-wrap"><table><thead><tr><th>阵营</th><th>行</th><th>KDA</th><th>累计金币</th></tr></thead><tbody>
      ${['blue', 'red'].flatMap(camp => (frame[camp] || []).map((row, index) => `<tr><td>${SIDE[camp]}</td><td>${index + 1}</td><td>${(row.kda || []).join('/')}</td><td>${num(row.gold)}</td></tr>`)).join('')}
      </tbody></table></div></div>`).join('')}
    <p class="helper">Mimo 只读面板里的 KDA 和累计金币；行序按队伍槽位，英雄身份仍以加载页/阵容为准。</p>
  </div>`;
}

function evidence(meta) {
  const files = meta.evidence || [];
  if (!files.length) return '';
  return `<div class="recording-evidence">${files.map(name => `<a href="/api/recordings/${encodeURIComponent(meta.id)}/evidence/${encodeURIComponent(name)}" target="_blank" rel="noopener"><img src="/api/recordings/${encodeURIComponent(meta.id)}/evidence/${encodeURIComponent(name)}" alt="${esc(name)}" loading="lazy"><small>${esc(name)}</small></a>`).join('')}</div>`;
}

function detail(meta, report) {
  if (!meta) return '';
  const job = (meta._job || null);
  const coverage = report?.coverage || meta.report?.coverage || {};
  const scenes = report?.scenes || [];
  const match = report?.match || meta.report?.match || {};
  const title = match.title?.value || match.mode || meta.name;
  return `<section class="panel section-gap recording-detail">
    <div class="panel-header"><div><h2>${esc(title)}</h2><div class="panel-subtitle">${esc(meta.name)} · ${bytes(meta.size)} · ${clock(meta.video?.duration)} · ${meta.video?.width || '—'}×${meta.video?.height || '—'} · ${meta.video?.fps ? Number(meta.video.fps).toFixed(2) + ' fps' : 'fps 未知'}</div></div>
      <div class="capture-group-actions">${statusTag(meta, job)}${meta.reportAvailable ? `<button class="button secondary" data-export="${esc(meta.id)}">导出报告 JSON</button>` : ''}<button class="button ghost" data-close-detail>收起</button></div></div>
    <div class="form-section">
      ${job && ['queued', 'running'].includes(job.status) ? `<div class="notice">${esc(job.stage || '识别中')} ${job.progress != null ? `· ${job.progress}%` : ''}<div class="recording-progress"><i style="width:${Math.max(2, job.progress || 0)}%"></i></div></div>` : ''}
      ${meta.error ? `<div class="notice red">${esc(meta.error)}</div>` : ''}
      ${!report ? `<div class="empty">${meta.reportAvailable ? '正在读取报告…' : '还没有识别报告。'}</div>` : `
        <div class="metrics recording-metrics">
          <div class="metric"><div class="metric-label">阵容英雄</div><div class="metric-number">${num(coverage.lineupHeroes)}<small>/10</small></div><div class="metric-note">加载页+同局核对</div></div>
          <div class="metric"><div class="metric-label">阶段</div><div class="metric-number recording-small">${scenes.length ? esc(scenes.map(scene => ({replay_list: '列表', loading: '加载', game: '对局', unknown: '未知'}[scene.type] || scene.type)).join(' →')) : '—'}</div><div class="metric-note">${report.replayDuration ? `回放总时长 ${clock(report.replayDuration)}` : '总时长未读到'}</div></div>
          <div class="metric"><div class="metric-label">对局覆盖</div><div class="metric-number">${num(report.samples?.length)}<small>帧</small></div><div class="metric-note">${clock(report.samples?.at(-1)?.gameTime)} 结束 · ${report.sampleFps || meta.sampleFps || 1} fps</div></div>
          <div class="metric"><div class="metric-label">Mimo 精读</div><div class="metric-number recording-small">${report.mimo?.available ? '已启用' : '未启用'}</div><div class="metric-note">${report.mimo?.calls != null ? `${report.mimo.calls} 次短读取` : '快速布局结果'}</div></div>
        </div>
        ${report.warnings?.length ? `<div class="notice">${report.warnings.map(esc).join('<br>')}</div>` : ''}
        <div class="panel-header"><h2>十人阵容</h2><span class="helper">行序不是分路；英雄名以印刷文字为准</span></div>
        ${lineups(report)}
        <div class="recording-columns">
          <div><div class="panel-header"><h2>经济与击杀时间轴</h2><span class="tag gray">最近 10 点</span></div>${timeline(report)}</div>
          <div><div class="panel-header"><h2>记分板快照</h2><span class="tag gray">仅打开时可见</span></div>${scoreboard(report)}</div>
        </div>
        ${mimoTeamPanel(report)}
        ${report.mimo ? `<div class="recording-mimo"><div class="panel-header"><h2>Mimo 精读记录</h2><span class="tag ${report.mimo.available ? '' : 'amber'}">${report.mimo.available ? 'mimo-ocr-0' : '未执行'}</span></div>
          ${report.mimo.error ? `<div class="notice">${esc(report.mimo.error)}</div>` : ''}
          ${report.mimo.warnings?.length ? `<div class="notice">${report.mimo.warnings.map(esc).join('<br>')}</div>` : ''}
          <p class="helper">${report.mimo.calls != null ? `${report.mimo.calls} 次调用` : ''} ${report.mimo.elapsedMs != null ? `· ${(report.mimo.elapsedMs / 1000).toFixed(1)} 秒` : ''} ${report.mimo.version ? `· ${esc(report.mimo.version)}` : ''}。逐帧数值仍来自快速布局引擎，Mimo 只补加载页/记分板文字。</p>
        </div>` : ''}
        ${evidence(meta)}
      `}
    </div>
  </section>`;
}

function recordingRow(meta, job, reports) {
  const selected = meta.id === selectedId;
  const summary = meta.report || {};
  const ready = meta.reportAvailable;
  return `<tr class="${selected ? 'selected' : ''}">
    <td><strong>${esc(meta.name)}</strong><div class="helper">${esc(meta.id.slice(0, 12))} · ${when(meta.createdAt)}</div>${progressBar(meta, job)}</td>
    <td>${clock(meta.video?.duration)}<div class="helper">${meta.video?.width || '—'}×${meta.video?.height || '—'} · ${bytes(meta.size)}</div></td>
    <td>${statusTag(meta, job)}<div class="helper">${esc(meta.engine || '未识别')} ${meta.sampleFps ? `· ${meta.sampleFps} fps` : ''}</div></td>
    <td>${ready ? `<strong>${num(summary.lineupHeroes)}/10</strong><div class="helper">英雄 · 警告 ${num(summary.warnings)}</div>` : '<span class="helper">尚无报告</span>'}</td>
    <td><div class="capture-row-actions">
      <button class="button ghost" data-select="${esc(meta.id)}">${ready ? '查看报告' : '查看'}</button>
      ${ready ? `<button class="button ghost" data-rerun="${esc(meta.id)}">重新识别</button>` : `<button class="button secondary" data-run="${esc(meta.id)}">开始识别</button>`}
      ${job && ['queued', 'running'].includes(job.status) ? `<button class="button ghost" data-cancel="${esc(job.id)}">取消</button>` : ''}
      <button class="button ghost" data-delete="${esc(meta.id)}">删除</button>
    </div></td>
  </tr>`;
}

export async function renderRecordings(container, {api, toast, isCurrent}) {
  let data = {recordings: [], stats: {}, jobs: []};
  let status = {};
  let busy = false;
  let engineChoice = localStorage.getItem('recording-engine') || 'mimo';
  let fpsChoice = localStorage.getItem('recording-fps') || '1';

  const load = async () => {
    const [list, ocrStatus] = await Promise.all([
      api('/api/recordings?t=' + Date.now()),
      api('/api/ocr/status?t=' + Date.now()),
    ]);
    data = list;
    status = ocrStatus;
    for (const meta of data.recordings || []) {
      meta._job = (data.jobs || []).find(job => job.targetId === meta.id);
    }
  };

  const draw = () => {
    if (!isCurrent()) return;
    const recordings = data.recordings || [];
    const stats = data.stats || {};
    const free = Number(stats.freeBytes) || 0;
    const selected = recordings.find(item => item.id === selectedId);
    container.innerHTML = `<div class="page-heading"><div><h1>录屏采集</h1>
      <p class="subtitle">把回放录屏交给本机：快速布局读取时间轴与面板，Mimo 精读加载页和记分板文字。</p></div>
      <span class="tag amber">本机识别 · 实验分析</span></div>
      ${free < 256 * 1024 * 1024 ? `<div class="notice red"><strong>录屏目录剩余空间不足。</strong>当前 ${bytes(free)}，至少需要 256 MB；请清理磁盘，或把 KPL_RECORDINGS 指向其他盘。</div>` : ''}
      ${renderCollectionGuide('video')}
      ${engineStatus(status)}
      <div class="metrics capture-metrics">
        <div class="metric"><div class="metric-label">本机录屏</div><div class="metric-number">${num(recordings.length)}<small>份</small></div><div class="metric-note">${bytes(stats.bytes)} · 剩余 ${bytes(free)}</div></div>
        <div class="metric"><div class="metric-label">已完成报告</div><div class="metric-number">${num(recordings.filter(item => item.reportAvailable).length)}<small>份</small></div><div class="metric-note">可导出 JSON 交给采集通道</div></div>
        <div class="metric"><div class="metric-label">识别引擎</div><div class="metric-number recording-small">Mimo + 快速</div><div class="metric-note">Mimo 只读关键帧，逐帧仍走快速引擎</div></div>
        <div class="metric"><div class="metric-label">队列</div><div class="metric-number">${num((data.jobs || []).filter(job => ['queued', 'running'].includes(job.status)).length)}</div><div class="metric-note">单线程执行，避免 CPU 争抢</div></div>
      </div>
      <section class="panel"><div class="panel-header"><div><h2>上传一份录屏</h2><div class="panel-subtitle">一局一个文件；上传后自动开始识别</div></div><span class="helper">mp4 / mov / mkv / webm</span></div>
      <div class="form-section"><div class="recording-upload">
        <label class="field">录像文件<input id="recording-file" type="file" accept="video/*,.mp4,.mov,.mkv,.webm,.avi" required></label>
        <label class="field">采样帧率<select id="recording-fps"><option value="0.5">0.5 fps（更快）</option><option value="1">1 fps（推荐）</option><option value="2">2 fps（更细）</option></select></label>
        <label class="field">识别方式<select id="recording-engine"><option value="mimo">Mimo 精读 + 快速布局</option><option value="rapid">仅快速布局</option></select></label>
        <button class="button" id="recording-upload">上传并识别</button>
      </div>
      <div class="helper" id="recording-progress" role="status">识别在本机完成；不上传云端。Mimo 在 CPU 上较慢，但只读关键帧。</div>
      ${checklist()}</div></section>
      <section class="panel section-gap"><div class="panel-header"><h2>本机录屏</h2><span class="tag gray">${recordings.length} 份</span></div>
      ${recordings.length ? `<div class="table-wrap"><table class="recording-table"><thead><tr><th>文件</th><th>时长 / 画面</th><th>状态</th><th>报告</th><th></th></tr></thead><tbody>${recordings.map(meta => recordingRow(meta, meta._job, reportCache)).join('')}</tbody></table></div>` : '<div class="empty"><strong>还没有录屏</strong>先上传一份完整回放；英雄、计时、金币和记分板快照会保存在本机。</div>'}</section>
      <div id="recording-detail">${selected ? detail(selected, reportCache[selected.id]) : ''}</div>
      <p class="summary-footnote">录屏分析不创建正式比赛，也不进入英雄胜率。英雄/昵称仍需人工核对；完整终局输出、承伤和参团率应以赛后截图或数据包为准。</p>`;

    const fileInput = container.querySelector('#recording-file');
    const fps = container.querySelector('#recording-fps');
    const engine = container.querySelector('#recording-engine');
    if (fps) fps.value = fpsChoice;
    if (engine) engine.value = engineChoice;
    if (fps) fps.onchange = () => { fpsChoice = fps.value; localStorage.setItem('recording-fps', fpsChoice); };
    if (engine) engine.onchange = () => { engineChoice = engine.value; localStorage.setItem('recording-engine', engineChoice); };
    const uploadButton = container.querySelector('#recording-upload');
    if (uploadButton) uploadButton.onclick = () => upload(fileInput?.files[0], fpsChoice, engineChoice);
    container.querySelectorAll('[data-select]').forEach(button => button.onclick = () => select(button.dataset.select));
    container.querySelectorAll('[data-run]').forEach(button => button.onclick = () => run(button.dataset.run, false));
    container.querySelectorAll('[data-rerun]').forEach(button => button.onclick = () => run(button.dataset.rerun, true));
    container.querySelectorAll('[data-cancel]').forEach(button => button.onclick = () => cancel(button.dataset.cancel));
    container.querySelectorAll('[data-delete]').forEach(button => button.onclick = () => remove(button.dataset.delete));
    container.querySelectorAll('[data-export]').forEach(button => button.onclick = () => exportReport(button.dataset.export));
    const close = container.querySelector('[data-close-detail]');
    if (close) close.onclick = () => { selectedId = null; draw(); };
  };

  const select = async (id) => {
    selectedId = id;
    if (!reportCache[id]) {
      try { reportCache[id] = await api('/api/recordings/' + encodeURIComponent(id) + '/report'); }
      catch { reportCache[id] = null; }
    }
    if (isCurrent()) { draw(); container.querySelector('#recording-detail')?.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  };

  const upload = (file, fps, engine) => {
    if (busy || !file) { if (!file) toast('请选择录像文件', true); return; }
    if (!(status.ffmpeg && status.ffprobe)) { toast('未找到 ffmpeg / ffprobe，请先安装并加入 PATH', true); return; }
    if (Number(file.size) > Number(data.stats.maxBytes || 0)) { toast(`录像请小于 ${bytes(data.stats.maxBytes)}`, true); return; }
    busy = true;
    const progress = container.querySelector('#recording-progress');
    if (progress) progress.textContent = '正在上传录像…';
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/recordings?name=' + encodeURIComponent(file.name));
    xhr.upload.onprogress = event => {
      if (progress && event.lengthComputable) progress.textContent = `正在上传 ${bytes(event.loaded)} / ${bytes(event.total)}…`;
    };
    xhr.onerror = () => { busy = false; toast('上传失败，请确认本地服务仍在运行', true); };
    xhr.onload = async () => {
      try {
        let value = {};
        try { value = JSON.parse(xhr.responseText || '{}'); } catch {}
        if (xhr.status < 200 || xhr.status >= 300) throw Error(value.detail || '上传失败');
        if (progress) progress.textContent = '上传完成，正在排队识别…';
        await run(value.id, false);
      } catch (error) { busy = false; toast(error.message, true); }
    };
    xhr.send(file);
  };

  const run = async (id, force) => {
    try {
      const job = await api(`/api/recordings/${encodeURIComponent(id)}/ocr?fps=${encodeURIComponent(fpsChoice)}&engine=${encodeURIComponent(engineChoice)}&force=${force ? 'true' : 'false'}`, 'POST');
      toast(force ? `已开始重新识别（任务 ${job.id}）` : `已开始识别（任务 ${job.id}）`);
      selectedId = id;
      await load();
      draw();
      schedulePoll();
    } catch (error) {
      busy = false;
      toast(error.message, true);
    }
  };

  const cancel = async (jobId) => {
    try { await api('/api/ocr/jobs/' + encodeURIComponent(jobId) + '/cancel', 'POST'); await load(); draw(); toast('已请求取消任务'); }
    catch (error) { toast(error.message, true); }
  };

  const remove = async (id) => {
    if (!confirm('删除这份录屏、报告和证据帧？原视频会从本机删除，无法恢复。')) return;
    try {
      await api('/api/recordings/' + encodeURIComponent(id), 'DELETE');
      if (selectedId === id) selectedId = null;
      delete reportCache[id];
      await load(); draw(); toast('已删除');
    } catch (error) { toast(error.message, true); }
  };

  const exportReport = async (id) => {
    try {
      const report = reportCache[id] || await api('/api/recordings/' + encodeURIComponent(id) + '/report');
      reportCache[id] = report;
      download(`录屏识别-${id.slice(0, 8)}.json`, JSON.stringify(report, null, 2));
    } catch (error) { toast(error.message, true); }
  };

  const schedulePoll = () => {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      if (!isCurrent()) return;
      try {
        await load();
        const running = (data.recordings || []).some(item => ['queued', 'running'].includes(item.status));
        if (running) {
          if (selectedId) {
            try { reportCache[selectedId] = await api('/api/recordings/' + encodeURIComponent(selectedId) + '/report'); }
            catch {}
          }
          draw();
          schedulePoll();
        } else {
          draw();
          busy = false;
        }
      } catch { /* keep the last rendered state */ }
    }, 1800);
  };

  clearTimeout(pollTimer);
  container.innerHTML = '<div class="loading">正在打开本机录屏库…</div>';
  try {
    await load();
    const running = (data.recordings || []).some(item => ['queued', 'running'].includes(item.status));
    draw();
    if (running) schedulePoll();
  } catch (error) {
    if (isCurrent()) container.innerHTML = '<div class="notice">录屏库读取失败，请确认本地服务仍在运行。</div>';
    toast(error.message, true);
  }
}

function download(name, content) {
  const url = URL.createObjectURL(new Blob([content], {type: 'application/json;charset=utf-8'}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
