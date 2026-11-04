import {heroLanes, lanes, lanesOf} from '/assets/hero-lanes.js?v=1';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const primaryLane = name => lanesOf(name)[0] || '';
const sortNames = names => [...names].sort((a, b) => a.localeCompare(b, 'zh'));
let catalogPromise = null;

function option(name, selected) {
  return `<option value="${esc(name)}"${name === selected ? ' selected' : ''}>${esc(name)}</option>`;
}

function heroOptions(lane, selected = '', extra = []) {
  const all = sortNames([...new Set([...Object.keys(heroLanes), ...extra])]);
  const included = lane ? all.filter(name => lanesOf(name).includes(lane)) : all;
  let html;
  if (lane) {
    html = included.map(name => option(name, selected)).join('');
  } else {
    html = [...lanes, '未分类'].map(group => {
      const names = included.filter(name => (primaryLane(name) || '未分类') === group);
      return names.length ? `<optgroup label="${group}">${names.map(name => option(name, selected)).join('')}</optgroup>` : '';
    }).join('');
  }
  const empty = '<option value="">未知</option>';
  if (selected && !included.includes(selected)) {
    return empty + `<option value="${esc(selected)}" selected>${esc(selected)}（未收录）</option>` + html;
  }
  return empty + html;
}

function laneOptions(selected = '') {
  return `<option value=""${selected ? '' : ' selected'}>全部分路</option>` +
    lanes.map(lane => `<option value="${esc(lane)}"${lane === selected ? ' selected' : ''}>${esc(lane)}</option>`).join('');
}

export function bpEditorHtml(bp = {}) {
  if (typeof bp === 'string') bp = {notes: bp};
  if (!bp || typeof bp !== 'object') bp = {};
  return `<section class="panel section-gap bp-capture"><div class="panel-head panel-header"><div><h2>BP 录入 / 补录</h2><p>先选分路可缩小英雄范围；分路只作为筛选，不写入 BP 数据。未知手序留空位，选用按本方第 1–5 手排列。</p></div></div><div class="panel-body form-section"><div class="bp-grid">${['left','right'].map(side => `<div class="bp-side"><h3>${side === 'left' ? '左侧（分析蓝方）' : '右侧（分析红方）'}</h3>${[['bans','禁用',4],['picks','选用',5]].map(([kind,label,count]) => `<p>${label} · 按手序</p><div class="bp-slots">${Array.from({length: count}, (_, index) => {
    const value = bp[kind]?.[side]?.[index] || '';
    const lane = primaryLane(value);
    const sideLabel = side === 'left' ? '左' : '右';
    return `<div class="bp-slot"><small>${index + 1}</small><div class="bp-pick"><select class="bp-lane" data-bp-lane aria-label="${sideLabel}侧${label}第${index + 1}位分路">${laneOptions(lane)}</select><select class="bp-hero" data-capture-bp="${kind}:${side}:${index}" aria-label="${sideLabel}侧${label}第${index + 1}位英雄">${heroOptions(lane, value)}</select><span class="bp-hero-preview" data-bp-preview hidden></span></div></div>`;
  }).join('')}</div>`).join('')}</div>`).join('')}</div><div class="bp-meta"><label class="field">一手方<select data-capture-first><option value="">未知</option><option value="left"${bp.firstPick === 'left' ? ' selected' : ''}>左侧</option><option value="right"${bp.firstPick === 'right' ? ' selected' : ''}>右侧</option></select></label><label class="field">备注<textarea data-capture-notes maxlength="2000">${esc(bp.notes)}</textarea></label></div><div class="channel-actions"><button class="button primary" data-save-bp>保存 BP</button><span role="status" data-bp-status>可单独补录，不需要重传截图或录像。</span></div></div></section>`;
}

function loadHeroCatalog() {
  if (!catalogPromise) {
    catalogPromise = fetch('/api/catalog')
      .then(response => response.ok ? response.json() : {entries: []})
      .catch(() => ({entries: []}));
  }
  return catalogPromise;
}

function enhancePicker(picker, icons, extra) {
  const laneSelect = picker.querySelector('[data-bp-lane]');
  const heroSelect = picker.querySelector('[data-capture-bp]');
  const preview = picker.querySelector('[data-bp-preview]');
  if (!laneSelect || !heroSelect) return;
  const updatePreview = () => {
    const icon = icons[heroSelect.value];
    preview.innerHTML = icon ? `<img src="${esc(icon)}" alt="">` : '';
    preview.hidden = !icon;
  };
  const current = heroSelect.value;
  heroSelect.innerHTML = heroOptions(laneSelect.value, current, extra);
  updatePreview();
  laneSelect.onchange = () => {
    const value = heroSelect.value;
    const keep = !laneSelect.value || lanesOf(value).includes(laneSelect.value);
    heroSelect.innerHTML = heroOptions(laneSelect.value, keep ? value : '', extra);
    updatePreview();
  };
  heroSelect.onchange = updatePreview;
}

export function bindBpEditor(root, save, toast) {
  const button = root.querySelector('[data-save-bp]');
  button.onclick = async () => {
    const bp = {bans: {left: [], right: []}, picks: {left: [], right: []},
      firstPick: root.querySelector('[data-capture-first]').value,
      notes: root.querySelector('[data-capture-notes]').value};
    root.querySelectorAll('[data-capture-bp]').forEach(field => {
      const [kind, side, index] = field.dataset.captureBp.split(':');
      bp[kind][side][index] = field.value.trim();
    });
    button.disabled = true;
    try {
      await save(bp);
      root.querySelector('[data-bp-status]').textContent = 'BP 已保存，分析数据已更新';
      toast('BP 已保存');
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  };
  const pickers = [...root.querySelectorAll('.bp-pick')];
  if (!pickers.length) return;
  loadHeroCatalog().then(catalog => {
    if (!root.isConnected) return;
    const icons = Object.fromEntries((catalog.entries || [])
      .filter(entry => entry.kind === 'hero' && entry.icon)
      .map(entry => [entry.name, entry.icon]));
    const extra = Object.keys(icons).filter(name => !(name in heroLanes));
    pickers.forEach(picker => enhancePicker(picker, icons, extra));
  });
}
