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
    return `<div class="bp-slot" data-slot="${kind}:${side}:${index}"><small>${index + 1}</small><div class="bp-pick"><select class="bp-lane" data-bp-lane aria-label="${sideLabel}侧${label}第${index + 1}位分路">${laneOptions(lane)}</select><select class="bp-hero" data-capture-bp="${kind}:${side}:${index}" aria-label="${sideLabel}侧${label}第${index + 1}位英雄">${heroOptions(lane, value)}</select><span class="bp-hero-preview" data-bp-preview hidden></span></div></div>`;
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

async function loadCampPrefill(root, channelId, toast) {
  let channel;
  try {
    const response = await fetch('/api/channels/' + encodeURIComponent(channelId));
    if (!response.ok) return;
    channel = await response.json();
  } catch {
    return;
  }
  const camp = (channel.sources || {}).camp || {};
  const banNames = camp.banNames || {};
  const players = camp.players || [];
  const prefill = {
    bans: {left: (banNames.blue || []).slice(), right: (banNames.red || []).slice()},
    picks: {
      left: players.filter(p => p.camp === 'blue').map(p => p.hero).filter(Boolean),
      right: players.filter(p => p.camp === 'red').map(p => p.hero).filter(Boolean),
    },
  };
  const filledIn = {bans: {left: [], right: []}, picks: {left: [], right: []}};
  root.querySelectorAll('[data-capture-bp]').forEach(field => {
    const [kind, side] = field.dataset.captureBp.split(':');
    if (field.value && filledIn[kind] && filledIn[kind][side]) filledIn[kind][side].push(field.value);
  });
  const rows = [];
  for (const [kind, label] of [['bans', '禁用'], ['picks', '选用']]) {
    for (const [side, sideLabel] of [['left', '蓝方'], ['right', '红方']]) {
      const names = prefill[kind][side].filter(name => !filledIn[kind][side].includes(name));
      if (!names.length) continue;
      rows.push(`<div class="bp-prefill-row" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:6px 0"><span style="min-width:64px;font-size:12px;opacity:.7">${sideLabel}${label}</span>${names.map(name => `<button type="button" class="bp-prefill-chip" draggable="true" data-prefill="${kind}:${side}:${esc(name)}" title="${esc(name)} · 拖到槽位，或点击填入下一个空位" style="display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 3px;border:1px solid rgba(127,127,127,.35);border-radius:999px;background:transparent;cursor:grab;font:inherit;color:inherit"><span>${esc(name)}</span></button>`).join('')}</div>`);
    }
  }
  if (!rows.length) return;
  const section = root.querySelector('.bp-capture');
  const grid = section?.querySelector('.bp-grid');
  if (!section || !grid) return;
  const holder = document.createElement('div');
  holder.className = 'bp-prefill';
  holder.innerHTML = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:2px"><p class="note" style="margin:0">营地接口已获取以下英雄（顺序未知）：<strong>拖到槽位</strong>，或按手序点击自动填下一个空位。</p><button type="button" data-bp-undo class="button ghost" disabled style="padding:2px 10px;font-size:12px">撤销</button><span class="note" style="margin:0;font-size:11px;opacity:.6">Ctrl+Z</span></div>${rows.join('')}`;
  grid.parentElement.insertBefore(holder, grid);
  loadHeroCatalog().then(catalog => {
    if (!holder.isConnected) return;
    const icons = Object.fromEntries((catalog.entries || [])
      .filter(entry => entry.kind === 'hero' && entry.icon)
      .map(entry => [entry.name, entry.icon]));
    holder.querySelectorAll('[data-prefill]').forEach(chip => {
      const name = chip.dataset.prefill.split(':').slice(2).join(':');
      const icon = icons[name];
      if (icon) {
        chip.innerHTML = `<img src="${esc(icon)}" alt="${esc(name)}" draggable="false" style="width:26px;height:26px;border-radius:50%;object-fit:cover"><span>${esc(name)}</span>`;
      }
    });
  });

  const undoStack = [];
  const undoButton = holder.querySelector('[data-bp-undo]');
  const chips = () => [...holder.querySelectorAll('[data-prefill]')];
  const slotFields = (kind, side) => [...root.querySelectorAll(`[data-capture-bp^="${kind}:${side}:"]`)];
  const setSlot = (key, value) => {
    const field = root.querySelector(`[data-capture-bp="${key}"]`);
    if (!field) return null;
    const before = field.value;
    field.value = value;
    field.dispatchEvent(new Event('change', {bubbles: true}));
    return before;
  };
  const refresh = () => {
    undoButton.disabled = !undoStack.length;
    chips().forEach(chip => {
      const [kind, side] = chip.dataset.prefill.split(':');
      const name = chip.dataset.prefill.split(':').slice(2).join(':');
      const used = slotFields(kind, side).some(field => field.value === name);
      chip.disabled = used;
      chip.style.opacity = used ? '.35' : '1';
      chip.style.cursor = used ? 'default' : 'grab';
    });
  };
  const pushUndo = entry => { undoStack.push(entry); refresh(); };
  const undo = () => {
    const entry = undoStack.pop();
    if (!entry) return;
    for (const item of entry) setSlot(item.key, item.before);
    refresh();
  };
  undoButton.onclick = undo;
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && holder.isConnected) {
      event.preventDefault();
      undo();
    }
  });
  chips().forEach(chip => {
    chip.addEventListener('dragstart', event => {
      event.dataTransfer.setData('text/plain', 'chip:' + chip.dataset.prefill);
      event.dataTransfer.effectAllowed = 'copy';
    });
    chip.onclick = () => {
      const [kind, side] = chip.dataset.prefill.split(':');
      const name = chip.dataset.prefill.split(':').slice(2).join(':');
      const empty = slotFields(kind, side).find(field => !field.value);
      if (!empty) {
        toast('该边已填满，可直接拖到要替换的槽位', true);
        return;
      }
      const key = empty.dataset.captureBp;
      pushUndo([{key, before: setSlot(key, name)}]);
    };
  });
  root.querySelectorAll('[data-slot]').forEach(slot => {
    slot.addEventListener('dragover', event => {
      event.preventDefault();
      slot.style.outline = '2px dashed rgba(83,74,183,.6)';
      slot.style.outlineOffset = '2px';
    });
    slot.addEventListener('dragleave', () => { slot.style.outline = ''; });
    slot.addEventListener('drop', event => {
      event.preventDefault();
      slot.style.outline = '';
      const payload = event.dataTransfer.getData('text/plain') || '';
      if (!payload.startsWith('chip:')) return;
      const [kind, side, name] = payload.slice(5).split(':');
      const [slotKind, slotSide] = slot.dataset.slot.split(':');
      if (kind !== slotKind || side !== slotSide) {
        toast('只能拖到同边、同类（禁用配禁用 / 选用配选用）的槽位', true);
        return;
      }
      const key = slot.dataset.slot;
      pushUndo([{key, before: setSlot(key, name)}]);
    });
  });
  refresh();
}

export function bindBpEditor(root, save, toast, options = {}) {
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
  if (options.channelId) loadCampPrefill(root, options.channelId, toast);
  loadHeroCatalog().then(catalog => {
    if (!root.isConnected) return;
    const icons = Object.fromEntries((catalog.entries || [])
      .filter(entry => entry.kind === 'hero' && entry.icon)
      .map(entry => [entry.name, entry.icon]));
    const extra = Object.keys(icons).filter(name => !(name in heroLanes));
    pickers.forEach(picker => enhancePicker(picker, icons, extra));
  });
}
