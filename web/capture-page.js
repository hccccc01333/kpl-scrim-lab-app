import {renderCollectionGuide} from '/assets/collection-guide.js?v=7';
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// 与 web/capture-guide/requirements.json (collection-v3) 及 channel_store.py 的双合规口径一致：
// 唯一必采 = official；审核门槛 = 营地十人面板 或 七图+录屏；table/replay 始终选填。
const SOURCE_LEVELS = {
  required: {text: '必需', cls: 'amber'},
  recommended: {text: '推荐', cls: 'blue'},
  fallback: {text: '兜底', cls: 'gray'},
  optional: {text: '选填', cls: 'gray'},
};
const SOURCES = [
  {key: 'official', label: '王者营地链接', level: 'required', hint: '唯一必采：官方过程数据（约 30 秒经济、事件、逐秒位置）', href: '#channels'},
  {key: 'camp', label: '营地自动同步', level: 'recommended', hint: '推荐主路径：教练扫码一次，每天勾选拉取 BP 与十人完整面板', href: '#channels'},
  {key: 'screenshots', label: '七张赛后截图', level: 'fallback', hint: '兜底路径：与完整录屏一起，可替代营地十人面板完成审核', href: '#screenshots'},
  {key: 'video', label: '一段完整录屏', level: 'fallback', hint: '兜底路径：与七张截图一起提供过程时间轴与面板快照', href: '#recordings'},
  {key: 'table', label: '标准表格', level: 'optional', hint: '选填：补齐或校正十人字段，一局十行', href: '#import'},
  {key: 'replay', label: '回放文件', level: 'optional', hint: '选填：.abc / .ope，补名单与评分', href: '#replays'},
];

const STEPS = [
  ['建立本局', '填写日期、对手和训练分组，创建采集通道；之后的材料都挂到这一局下。'],
  ['挂上材料', '唯一必采是本局营地回放链接；推荐用营地自动同步导入十人面板，或按传统兜底补齐七张截图与一段完整录屏。'],
  ['审核保存', '两条合规路径任一齐备即可审核；字段冲突保留待核对，审核通过后写入分析平台，可回溯每一份来源。'],
];

export async function renderCapture(container, {api, toast, isCurrent}) {
  let busy = false;
  let inputs = {
    date: localStorage.getItem('capture-date') || '',
    opponent: localStorage.getItem('capture-opponent') || '',
    session: localStorage.getItem('capture-session') || '',
    version: localStorage.getItem('capture-version') || '',
  };
  const draw = (statusText = '') => {
    if (!isCurrent()) return;
    container.innerHTML = `<div class="capture-page">
      <div class="page-heading"><div><span class="page-eyebrow">DATA · 采集一局</span>
        <h1>采集一局</h1>
        <p>把一局训练赛的全部证据挂到同一个通道：先建局，再按清单放材料，审核后进入分析。</p></div>
        <a class="button ghost" href="#channels">已有本局？打开采集通道 →</a></div>
      <div class="capture-steps">
        ${STEPS.map(([title, text], index) => `<div><span>${index + 1}</span><strong>${esc(title)}</strong><p>${esc(text)}</p></div>`).join('')}
      </div>
      <section class="panel section-gap"><div class="panel-header"><div><h2>建立本局</h2>
        <div class="panel-subtitle">日期、对手、训练分组至少填一项；创建后进入通道页继续关联材料</div></div></div>
        <form id="capture-create-form" class="form-section">
          <div class="form-grid">
            <label class="field">比赛日期<input id="capture-date" type="date" value="${esc(inputs.date)}"></label>
            <label class="field">对手<input id="capture-opponent" value="${esc(inputs.opponent)}" placeholder="例如：周三训练对手"></label>
            <label class="field">训练分组<input id="capture-session" value="${esc(inputs.session)}" placeholder="例如：晚训 · 第 1 组"></label>
            <label class="field">版本<input id="capture-version" value="${esc(inputs.version)}" placeholder="例如：S42"></label>
          </div>
          <div class="channel-actions"><button class="button" type="submit">创建采集通道</button>
            <span id="capture-create-status" class="helper" role="status">${esc(statusText)}</span></div>
        </form></section>
      <section class="panel section-gap"><div class="panel-header"><div><h2>本局要挂的六类材料</h2>
        <div class="panel-subtitle">先满足唯一必采，再二选一凑齐审核门槛；其余按需补充</div></div>
        <span class="tag gray">1 必需 · 1 推荐 · 2 兜底 · 2 选填</span></div>
        <div class="capture-sources">
          ${SOURCES.map((source, index) => {
            const level = SOURCE_LEVELS[source.level];
            return `<a class="capture-source" href="${source.href}">
              <span class="capture-source-index">${String(index + 1).padStart(2, '0')}</span>
              <h2>${esc(source.label)}</h2>
              <span class="tag ${level.cls}">${level.text}</span>
              <p>${esc(source.hint)}</p>
              <span class="capture-source-cta">前往关联 →</span></a>`;
          }).join('')}
        </div>
        <p class="helper">审核门槛：营地十人面板<strong>或</strong>「七张截图 + 一段完整录屏」任一齐备即可；表格与回放文件始终选填。已保存的比赛可在比赛详情补录 BP，批量粘贴营地分享链接在采集通道页。</p></section>
      ${renderCollectionGuide()}
    </div>`;
    const form = container.querySelector('#capture-create-form');
    if (form) form.onsubmit = onSubmit;
    ['date', 'opponent', 'session', 'version'].forEach(key => {
      const input = container.querySelector(`#capture-${key}`);
      if (input) input.oninput = () => {
        inputs[key] = input.value;
        localStorage.setItem(`capture-${key}`, input.value);
      };
    });
  };
  const onSubmit = async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    const status = container.querySelector('#capture-create-status');
    const button = container.querySelector('#capture-create-form button');
    if (button) button.disabled = true;
    if (status) status.textContent = '正在创建…';
    try {
      // 本页由 studio.js 壳调用，其 api() 为两参形态：api(url, body) 即 POST
      const channel = await api('/api/channels', {'match': {
        date: inputs.date, opponent: inputs.opponent,
        session: inputs.session, version: inputs.version,
      }});
      ['date', 'opponent', 'session', 'version'].forEach(key => localStorage.removeItem(`capture-${key}`));
      location.hash = '#channel/' + encodeURIComponent(channel.id);
    } catch (error) {
      if (status) status.textContent = `创建失败：${error.message || error}`;
      if (button) button.disabled = false;
    } finally { busy = false; }
  };
  draw();
}
