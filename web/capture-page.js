import {renderCollectionGuide} from '/assets/collection-guide.js?v=6';
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const SOURCES = [
  {key: 'official', label: '王者营地链接', required: true, hint: '官方过程数据：约30秒金币、事件、逐秒位置', href: '#channels'},
  {key: 'screenshots', label: '七张赛后截图', required: true, hint: '终局 KDA、经济、输出、承伤、参团的权威来源', href: '#screenshots'},
  {key: 'video', label: '一段完整录屏', required: true, hint: '逐帧时间轴与面板快照，识别在本机完成', href: '#recordings'},
  {key: 'table', label: '标准表格', required: false, hint: '选填：补齐或校正十人字段，一局十行', href: '#import'},
  {key: 'replay', label: '回放文件', required: false, hint: '选填：.abc / .ope，补名单、MVP 与评分', href: '#replays'},
];

const STEPS = [
  ['建立本局', '填写日期、对手和训练分组，创建采集通道；之后的材料都挂到这一局下。'],
  ['挂上材料', '必采为营地链接、七张截图和一段完整录屏；表格与回放文件选填。解析结果自动合并成跨来源草稿。'],
  ['审核保存', '字段冲突会保留待核对；人工审核通过后写入分析平台，可回溯每一份来源。'],
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
      <section class="panel section-gap"><div class="panel-header"><h2>本局要挂的五类材料</h2>
        <span class="tag gray">必采三项 · 选填两项</span></div>
        <div class="capture-source">
          ${SOURCES.map(source => `<a class="capture-source-item" href="${source.href}"><strong>${esc(source.label)}${source.required ? ' <em class="tag amber">必需</em>' : ' <em class="tag gray">选填</em>'}</strong><p>${esc(source.hint)}</p></a>`).join('')}
        </div>
        <p class="helper">已保存的比赛也可以在比赛详情里补录 BP 和漏采的材料；批量粘贴营地分享链接在采集通道页。</p></section>
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
