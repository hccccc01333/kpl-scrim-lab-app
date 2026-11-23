/* 正式比赛线上表格录入（白金画廊）
 *
 * 路由建议：#official-entry（由 app.js 接线，本模块不抢 #content 的渲染权）。
 * 数据不另起一套：POST /api/studio/official-entry 把一场 BO 的每一局写成
 * 现有 channels 体系里的通道（matchType='formal'），可再经既有
 * /api/channels/{id}/review、/save 进入正式统计。
 * 赛后数据图只上传做附件（POST /api/images?name=...），不做 OCR。
 *
 * 导出：OFFICIAL_ENTRY_HASH / officialEntryPage() / initOfficialEntry(container)
 *      mountOfficialEntry(container) / autoMountOfficialEntry()
 */

import { glyph, deco, plus } from './ui-icons.js';

const API = {
  entry: '/api/studio/official-entry',
  pending: '/api/studio/workspace/formal-entries/pending',
  images: '/api/images',
  competitions: '/api/studio/workspace/competitions',
  notes: '#match-notes',
};

export const OFFICIAL_ENTRY_HASH = '#official-entry';
export const MATCH_TYPE = 'formal';
const MAX_IMAGE_BYTES = 12 * 1024 * 1024; // 与 server.py MAX_IMAGE 同口径
const MAX_IMAGES_PER_GAME = 4;
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const BO_FORMATS = [1, 3, 5, 7];
const SIDES = [{ value: 'left', label: '蓝方（我方在左）' }, { value: 'right', label: '红方（我方在右）' }];

/** HTML 转义：所有来自输入、接口或 data-* 的字符串进模板前都要过这里。 */
export function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}
const text = (value) => String(value == null ? '' : value).trim();

function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

async function api(path, { method = 'GET', body, raw, headers } = {}) {
  const init = { method, cache: 'no-store' };
  if (raw !== undefined) {
    init.body = raw;
    if (headers) init.headers = headers;
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch { /* 非 JSON */ }
    if (response.status === 413) throw new Error('图片超过服务器 12 MB 上限，请压缩后再试。');
    if (response.status === 404) throw new Error('录入接口暂时读不到，请稍后重试。');
    throw new Error(typeof detail === 'string' && detail ? detail : '保存失败，请稍后重试。');
  }
  try { return await response.json(); }
  catch { throw new Error('接口返回的不是 JSON，请确认打开的是赛训工作台。'); }
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function rate(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.min(100, Math.max(0, Math.round(n * 10) / 10));
}

/* ── 表格片段 ─────────────────────────────────────────────────── */

function lineupHtml(side, gameNo) {
  const rows = LANES.map((lane, slot) => `<tr>
      <th scope="row">${esc(lane)}</th>
      <td><input type="text" name="id" maxlength="24" autocomplete="off" autocapitalize="none"
          spellcheck="false" aria-label="第${gameNo}局 ${side === 'left' ? '蓝方' : '红方'}${lane}比赛ID"></td>
      <td><input type="text" name="hero" maxlength="16" autocomplete="off" spellcheck="false"
          aria-label="第${gameNo}局 ${side === 'left' ? '蓝方' : '红方'}${lane}英雄"></td>
      <td><input type="number" min="0" max="99" name="kills" aria-label="第${gameNo}局 ${side}${lane}击杀"></td>
      <td><input type="number" min="0" max="99" name="deaths" aria-label="第${gameNo}局 ${side}${lane}死亡"></td>
      <td><input type="number" min="0" max="99" name="assists" aria-label="第${gameNo}局 ${side}${lane}助攻"></td>
      <td><input type="number" min="0" step="1" name="gold" aria-label="第${gameNo}局 ${side}${lane}总经济"></td>
      <td><input type="number" min="0" step="1" name="damage" aria-label="第${gameNo}局 ${side}${lane}输出伤害"></td>
      <td><input type="number" min="0" step="1" name="taken" aria-label="第${gameNo}局 ${side}${lane}承受伤害"></td>
      <td><input type="number" min="0" max="100" step="0.1" name="participation" aria-label="第${gameNo}局 ${side}${lane}参团率%"></td>
      <td><input type="number" min="0" max="40" step="0.1" name="rating" aria-label="第${gameNo}局 ${side}${lane}评分"></td>
      <td><input type="hidden" name="slot" value="${slot}"></td>
    </tr>`).join('');
  return `<div class="oe-lineup">
      <table class="oe-lineup-table">
        <caption>${side === 'left' ? '蓝方' : '红方'} · 五人阵容</caption>
        <thead><tr><th scope="col">位置</th><th scope="col">比赛ID</th><th scope="col">英雄</th><th scope="col">击杀</th><th scope="col">死亡</th><th scope="col">助攻</th><th scope="col">经济</th><th scope="col">伤害</th><th scope="col">承伤</th><th scope="col">参团%</th><th scope="col">评分</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function resultOptions() {
  // 全字段选填：胜负默认「未记」，不替教练猜一个「胜」写进数据。
  return '<option value="">未记</option><option value="win">胜</option><option value="loss">负</option>';
}
function firstOptions() {
  return '<option value="">未记</option><option value="own">我方</option><option value="foe">对方</option>';
}

function gameRowHtml(gameNo) {
  return `<tr class="oe-game" data-oe-game="${gameNo}">
    <th scope="row" data-label="局次">第 ${gameNo} 局</th>
    <td data-label="比分">
      <div class="oe-pair"><input type="number" min="0" max="99" name="scoreOwn" aria-label="第${gameNo}局我方击杀" inputmode="numeric">
        <span>:</span><input type="number" min="0" max="99" name="scoreFoe" aria-label="第${gameNo}局对方击杀" inputmode="numeric"></div>
    </td>
    <td data-label="胜负"><select name="result" aria-label="第${gameNo}局胜负">${resultOptions()}</select></td>
    <td data-label="时长">
      <div class="oe-pair"><input type="number" min="0" max="90" name="durationMin" aria-label="第${gameNo}局时长（分）" inputmode="numeric"><span>分</span>
        <input type="number" min="0" max="59" name="durationSec" aria-label="第${gameNo}局时长（秒）" inputmode="numeric"><span>秒</span></div>
    </td>
    <td data-label="一血"><select name="firstBlood" aria-label="第${gameNo}局一血">${firstOptions()}</select></td>
    <td data-label="一塔"><select name="firstTower" aria-label="第${gameNo}局一塔">${firstOptions()}</select></td>
    <td data-label="分均经济（我/敌）">
      <div class="oe-pair"><input type="number" min="0" step="1" name="gpmOwn" aria-label="第${gameNo}局我方分均经济"><span>/</span>
        <input type="number" min="0" step="1" name="gpmFoe" aria-label="第${gameNo}局对方分均经济"></div>
    </td>
    <td data-label="暴君控制率%"><input type="number" min="0" max="100" step="0.1" name="tyrant" aria-label="第${gameNo}局暴君控制率"></td>
    <td data-label="主宰控制率%"><input type="number" min="0" max="100" step="0.1" name="lord" aria-label="第${gameNo}局主宰控制率"></td>
    <td data-label="暗影暴君%"><input type="number" min="0" max="100" step="0.1" name="shadowTyrant" aria-label="第${gameNo}局暗影暴君控制率"></td>
    <td data-label="暗影主宰%"><input type="number" min="0" max="100" step="0.1" name="shadowLord" aria-label="第${gameNo}局暗影主宰控制率"></td>
    <td data-label="推塔（我/敌）">
      <div class="oe-pair"><input type="number" min="0" max="99" name="towersOwn" aria-label="第${gameNo}局我方推塔"><span>/</span>
        <input type="number" min="0" max="99" name="towersFoe" aria-label="第${gameNo}局对方推塔"></div>
    </td>
    <td data-label="10分钟经济差"><input type="number" step="1" name="at10" aria-label="第${gameNo}局10分钟经济差（我方−对方）"></td>
    <td data-label="十人阵容">
      <details class="oe-lineup-details"><summary>填写十人阵容</summary>
        ${lineupHtml('left', gameNo)}${lineupHtml('right', gameNo)}
      </details>
    </td>
    <td data-label="赛后数据图">
      <div class="oe-shots" data-oe-shots="${gameNo}">
        <button type="button" class="oe-mini" data-oe-add-image="${gameNo}">${glyph('capture', { size: 14 })}贴数据图</button>
        <div class="oe-shot-list" data-oe-shot-list></div>
      </div>
    </td>
    <td data-label="操作"><button type="button" class="oe-mini oe-mini-danger oe-mini-icon" data-oe-remove-game="${gameNo}"
      aria-label="删除第${gameNo}局" title="删除第${gameNo}局">${glyph('trash', { size: 14 })}</button></td>
  </tr>`;
}

/** 返回整页 HTML 字符串；lead 在路由里把它塞进 #content。 */
export function officialEntryPage() {
  return `<section class="oe-page" data-official-entry-page>
    <header class="oe-head">
      <div><span class="oe-kicker">正式比赛 · 线上表格录入</span>
        ${deco('divider-title')}
        <h1>录入一场 BO 系列赛</h1>
        <p class="oe-intro">逐局填写官方赛后数据，字段全部选填——现场没确认的可以先空着，之后补录。赛后截图可作为附件随对局保存。</p></div>
      <a class="oe-link" href="${API.notes}">${glyph('book', { size: 14 })}赛后笔记 ${glyph('arrow-up', { size: 14, cls: 'oe-ext' })}</a>
    </header>

    <form class="oe-series" data-oe-form novalidate aria-label="逐局正式比赛录入">
      <fieldset class="oe-fieldset">
        <legend>比赛信息 <small class="oe-optional-note">全部字段选填：先保存现场能确认的，其余回头补录。</small></legend>
        <div class="oe-grid">
          <div class="oe-pending" data-oe-pending hidden></div>
          <div class="oe-field"><label for="oe-date">比赛日期（选填）</label>
            <input type="date" id="oe-date" name="date" value="${today()}" aria-invalid="false"></div>
          <div class="oe-field"><label for="oe-opponent">对手（选填）</label>
            <input type="text" id="oe-opponent" name="opponent" maxlength="40" autocomplete="off" spellcheck="false" aria-invalid="false"></div>
          <div class="oe-field"><label for="oe-event">赛事</label>
            <input type="text" id="oe-event" name="event" maxlength="40" list="oe-events" autocomplete="off">
            <datalist id="oe-events" data-oe-events></datalist></div>
          <div class="oe-field"><label for="oe-bo">BO 赛制</label>
            <select id="oe-bo" name="boFormat" data-oe-bo>${BO_FORMATS.map((n) => `<option value="${n}"${n === 5 ? ' selected' : ''}>BO${n}</option>`).join('')}</select></div>
          <div class="oe-field"><label for="oe-side">我方阵营</label>
            <select id="oe-side" name="ownSide">${SIDES.map((s) => `<option value="${s.value}">${esc(s.label)}</option>`).join('')}</select></div>
          <div class="oe-field"><label for="oe-version">版本（选填）</label>
            <input type="text" id="oe-version" name="version" maxlength="24" autocomplete="off"></div>
          <div class="oe-field"><label for="oe-reviewer">录入人</label>
            <input type="text" id="oe-reviewer" name="reviewer" maxlength="24" value="教练" autocomplete="name"></div>
          <div class="oe-field"><label for="oe-replay">官方回放链接（选填）</label>
            <input type="url" id="oe-replay" name="replayLink" maxlength="300" inputmode="url" spellcheck="false" aria-invalid="false">
            <span class="oe-field-error" id="oe-replay-error" hidden>${glyph('warning', { size: 14 })}请填写完整链接（http:// 或 https:// 开头）</span></div>
        </div>
        <input type="hidden" name="matchType" value="${MATCH_TYPE}">
      </fieldset>

      <div class="oe-tablewrap" tabindex="0" role="region" aria-labelledby="oe-games-caption">
        <table class="oe-games">
          <caption id="oe-games-caption">逐局数据 · 一行一局</caption>
          <thead><tr>
            <th scope="col">局次</th><th scope="col">比分</th><th scope="col">胜负</th><th scope="col">时长</th>
            <th scope="col">一血</th><th scope="col">一塔</th><th scope="col">分均经济</th>
            <th scope="col">暴君%</th><th scope="col">主宰%</th><th scope="col">暗影暴君%</th><th scope="col">暗影主宰%</th>
            <th scope="col">十人阵容</th><th scope="col">赛后数据图</th><th scope="col">操作</th>
          </tr></thead>
          <tbody data-oe-games>${BO_FORMATS.includes(5) ? Array.from({ length: 5 }, (_, i) => gameRowHtml(i + 1)).join('') : ''}</tbody>
        </table>
      </div>
      <div class="oe-actions">
        <button type="button" class="oe-btn" data-oe-add-game>${plus({ size: 14 })}加一局</button>
        <button type="submit" class="oe-btn oe-btn-primary" data-oe-save>${glyph('pick', { size: 16 })}保存到正式比赛</button>
        <p class="oe-status" role="status" aria-live="polite" aria-atomic="true" data-oe-status></p>
      </div>
      <div class="oe-toast" role="status" aria-live="polite" data-oe-toast hidden></div>
      <div class="oe-result" data-oe-result hidden></div>
    </form>

    <dialog class="oe-dialog oe-image-dialog" data-oe-image-dialog aria-labelledby="oe-img-title">
      <h2 id="oe-img-title">贴官方赛后数据图</h2>
      <p class="oe-dialog-hint">支持选择文件或直接 Ctrl/⌘ + V 粘贴截图；单张不超过 12 MB，每局最多 ${MAX_IMAGES_PER_GAME} 张。图片仅作附件，字段请手工填写。</p>
      <div class="oe-drop" data-oe-drop role="button" tabindex="0" aria-label="选择或拖入图片"
        aria-describedby="oe-drop-hint">
        <span class="oe-drop-symbol">${glyph('capture', { size: 32, cls: 'oe-drop-capture' })}</span>
        <p id="oe-drop-hint">点击选择图片，或把截图拖到这里；也可 Ctrl/⌘ + V 粘贴</p>
        <input type="file" accept="image/png,image/jpeg,image/webp" data-oe-file autofocus
          aria-label="选择 PNG、JPEG 或 WebP 图片">
      </div>
      <div class="oe-img-preview" data-oe-preview></div>
      <p class="oe-err" role="alert" data-oe-img-error></p>
      <form method="dialog" class="oe-dialog-actions" aria-label="截图操作">
        <button type="submit" value="cancel" class="oe-btn">取消</button>
        <button type="button" class="oe-btn oe-btn-primary" data-oe-upload>${glyph('export', { size: 15 })}上传并附到本局</button>
      </form>
    </dialog>
  </section>`;
}

/* ── 逻辑 ─────────────────────────────────────────────────────── */

export function initOfficialEntry(container) {
  if (!container) return null;
  if (container.__officialEntryApi && container.querySelector('[data-oe-form]')) {
    return container.__officialEntryApi;
  }
  container.innerHTML = officialEntryPage();

  const form = container.querySelector('[data-oe-form]');
  const tbody = container.querySelector('[data-oe-games]');
  const status = container.querySelector('[data-oe-status]');
  const resultBox = container.querySelector('[data-oe-result]');
  const dialog = container.querySelector('[data-oe-image-dialog]');
  const fileInput = dialog.querySelector('[data-oe-file]');
  const preview = dialog.querySelector('[data-oe-preview]');
  const imgError = dialog.querySelector('[data-oe-img-error]');
  const shots = new Map(); // gameNo -> [{id, name, url}]
  const toast = container.querySelector('[data-oe-toast]');
  const drop = dialog.querySelector('[data-oe-drop]');
  let imageGameNo = 0;
  let pendingFile = null;
  let pendingUrl = '';
  let busy = false;
  let toastTimer = 0;
  let toastAction = null;

  /* 错误不只靠颜色：按 kind 注入语义图标（图标本身 aria-hidden，文字仍由状态区承担）。 */
  const say = (message, kind = '') => {
    const icon = kind === 'error' ? glyph('warning', { size: 14 })
      : kind === 'ok' ? glyph('victory', { size: 14 })
        : kind === 'warn' ? glyph('warning', { size: 14 }) : '';
    status.innerHTML = `${icon}${esc(message || '')}`;
    status.className = `oe-status${kind ? ` is-${kind}` : ''}`;
  };
  const fail = (error) => say(error?.message || '操作失败，请稍后重试。', 'error');

  /* 轻量撤销条：比原生 confirm 不打断录入，8 秒内可撤回删局/删图。 */
  function hideToast() {
    clearTimeout(toastTimer);
    toast.hidden = true;
    toast.innerHTML = '';
    toastAction = null;
  }
  function showToast(message, action) {
    clearTimeout(toastTimer);
    toastAction = typeof action === 'function' ? action : null;
    toast.innerHTML = `<span>${esc(message)}</span>${toastAction
      ? '<button type="button" class="oe-toast-undo" data-oe-undo>撤销</button>' : ''}`;
    toast.hidden = false;
    toastTimer = setTimeout(hideToast, 9000);
  }

  function renderShots(gameNo) {
    const holder = container.querySelector(`[data-oe-shots="${gameNo}"] [data-oe-shot-list]`);
    if (!holder) return;
    const list = shots.get(gameNo) || [];
    holder.innerHTML = list.map((image) => `<span class="oe-shot">
        <img src="/api/images/${encodeURIComponent(image.id)}" alt="${esc(image.name)}赛后数据图" loading="lazy">
        <button type="button" class="oe-shot-x" data-oe-remove-image="${gameNo}" data-image-id="${esc(image.id)}"
          aria-label="移除图片 ${esc(image.name)}" title="移除">${glyph('trash', { size: 14 })}</button>
      </span>`).join('');
  }

  /* 重编号必须同步所有携带局号的属性：否则图片/删除按钮仍指向旧 gameNo。 */
  function renumberGames() {
    [...tbody.querySelectorAll('[data-oe-game]')].forEach((row, index) => {
      const no = index + 1;
      row.dataset.oeGame = String(no);
      row.querySelectorAll('[data-oe-add-image],[data-oe-remove-game],[data-oe-shots],[data-oe-remove-image]')
        .forEach((el) => {
          if (el.hasAttribute('data-oe-add-image')) el.dataset.oeAddImage = String(no);
          if (el.hasAttribute('data-oe-remove-game')) el.dataset.oeRemoveGame = String(no);
          if (el.hasAttribute('data-oe-shots')) el.dataset.oeShots = String(no);
          if (el.hasAttribute('data-oe-remove-image')) el.dataset.oeRemoveImage = String(no);
        });
      const label = row.querySelector('th[data-label="局次"]');
      if (label) label.textContent = `第 ${no} 局`;
      row.querySelectorAll('[aria-label],[title]').forEach((el) => {
        for (const attr of ['aria-label', 'title']) {
          const value = el.getAttribute(attr);
          if (value && /第\d+局/.test(value)) el.setAttribute(attr, value.replace(/第\d+局/g, `第${no}局`));
        }
      });
      renderShots(no);
    });
  }

  function setGameCount(count) {
    const current = [...tbody.querySelectorAll('[data-oe-game]')];
    if (count > current.length) {
      for (let i = current.length; i < count; i++) tbody.insertAdjacentHTML('beforeend', gameRowHtml(i + 1));
    } else if (count < current.length) {
      current.slice(count).forEach((row) => {
        shots.delete(Number(row.dataset.oeGame));
        row.remove();
      });
    }
    renumberGames();
  }

  /* 删中间局：迁移 shots 键并保留可撤销的节点引用（节点离线后 input.value 仍在）。 */
  function removeGame(row) {
    const rows = [...tbody.querySelectorAll('[data-oe-game]')];
    if (rows.length <= 1) { say('至少要保留一局。', 'error'); return; }
    const no = Number(row.dataset.oeGame);
    const index = rows.indexOf(row);
    const maxNo = Math.max(...rows.map((r) => Number(r.dataset.oeGame)));
    const removedShots = (shots.get(no) || []).slice();
    const node = row;
    node.remove();
    shots.delete(no);
    for (let n = no + 1; n <= maxNo; n++) {
      if (shots.has(n)) { shots.set(n - 1, shots.get(n)); shots.delete(n); }
    }
    renumberGames();
    say(`已删除第 ${no} 局。`);
    showToast(`已删除第 ${no} 局`, () => {
      const now = [...tbody.querySelectorAll('[data-oe-game]')];
      tbody.insertBefore(node, now[index] || null);
      for (let n = maxNo; n >= no + 1; n--) {
        if (shots.has(n - 1)) { shots.set(n, shots.get(n - 1)); shots.delete(n - 1); }
      }
      if (removedShots.length) shots.set(no, removedShots);
      renumberGames();
      say('已撤销删除。', 'ok');
    });
  }

  function clearPending() {
    pendingFile = null;
    if (pendingUrl) URL.revokeObjectURL(pendingUrl);
    pendingUrl = '';
    fileInput.value = '';
    preview.innerHTML = '';
    imgError.textContent = '';
  }

  function openImageDialog(gameNo) {
    imageGameNo = gameNo;
    clearPending();
    dialog.showModal();
  }

  function acceptFile(file) {
    imgError.textContent = '';
    if (!file) return;
    // 粘贴进来的图片偶尔没有 type，交给后端 Pillow 校验并给可读错误。
    if (file.type && !/^image\/(png|jpeg|webp)$/i.test(file.type)) {
      imgError.textContent = '只支持 PNG、JPEG、WebP 图片。';
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      imgError.textContent = `这张图 ${(file.size / 1048576).toFixed(1)} MB，超过 12 MB 上限，请压缩后再上传。`;
      return;
    }
    pendingFile = file;
    if (pendingUrl) URL.revokeObjectURL(pendingUrl);
    pendingUrl = URL.createObjectURL(file);
    preview.innerHTML = `<img src="${esc(pendingUrl)}" alt="待上传的赛后数据图预览">`;
  }

  async function uploadPending() {
    if (!pendingFile) { imgError.textContent = '请先选择或粘贴一张图片。'; return; }
    const list = shots.get(imageGameNo) || [];
    if (list.length >= MAX_IMAGES_PER_GAME) {
      imgError.textContent = `每局最多 ${MAX_IMAGES_PER_GAME} 张数据图，请先移除一张。`;
      return;
    }
    const button = dialog.querySelector('[data-oe-upload]');
    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `${glyph('refresh', { size: 14, cls: 'oe-spin' })}上传中…`;
    imgError.textContent = '正在上传…';
    try {
      const saved = await api(`${API.images}?name=${encodeURIComponent(pendingFile.name.slice(0, 100))}`, {
        method: 'POST', raw: pendingFile, headers: { 'Content-Type': pendingFile.type },
      });
      const id = text(saved?.id);
      if (!id) throw new Error('图片已上传，但接口没有返回图片 ID。');
      shots.set(imageGameNo, [...list, { id, name: pendingFile.name.slice(0, 100) }]);
      renderShots(imageGameNo);
      clearPending();
      dialog.close();
      say('数据图已附上，请继续手填本局字段。', 'ok');
    } catch (error) {
      imgError.textContent = error?.message || '上传失败，请重试。';
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      button.innerHTML = originalLabel;
    }
  }

  function readLineups(row) {
    const tables = [...row.querySelectorAll('.oe-lineup-table')];
    const toPlayers = (table) => {
      const body = table?.tBodies?.[0]; // 只取 tbody，杜绝把表头/杂行读成第 6 人
      if (!body) return [];
      return [...body.rows]
        .filter((tr) => tr.querySelector('[name="slot"]')) // 再兜一层：无 slot 的行不可能是阵容行
        .map((tr) => {
          const num = (name) => {
            const value = Number(tr.querySelector(`[name="${name}"]`)?.value);
            return Number.isFinite(value) ? value : null;
          };
          return {
          slot: Number(tr.querySelector('[name="slot"]')?.value),
          lane: text(tr.querySelector('[name="id"]')?.closest('td')?.previousElementSibling?.textContent),
          id: text(tr.querySelector('[name="id"]')?.value),
          hero: text(tr.querySelector('[name="hero"]')?.value),
          kills: num('kills'), deaths: num('deaths'), assists: num('assists'),
          gold: num('gold'), damage: num('damage'), taken: num('taken'),
          participation: num('participation'), rating: num('rating'),
          };
        })
        .filter((p) => Number.isInteger(p.slot) && p.slot >= 0 && p.slot < LANES.length)
        .sort((a, b) => a.slot - b.slot);
    };
    return { left: toPlayers(tables[0]), right: toPlayers(tables[1]) };
  }

  /** 每方恰好 5 人（5 个位置）的结构校验；空阵容仍算 5 个空槽位，不拦正常录入。 */
  function lineupsComplete(row) {
    const { left, right } = readLineups(row);
    return left.length === LANES.length && right.length === LANES.length;
  }

  /* 字段级内联错误：aria-describedby 仅在错误显示时挂上，避免隐藏文案被读屏提前念出。
     2026-11-22 反馈：字段全部选填，只校验「填了但格式不对」的情况（回放链接）。 */
  const ERROR_FIELDS = ['oe-replay'];
  function setFieldState(id, invalid) {
    const el = form.querySelector(`#${id}`);
    if (!el) return;
    const err = container.querySelector(`#${id}-error`);
    if (err) err.hidden = !invalid;
    el.setAttribute('aria-invalid', invalid ? 'true' : 'false');
    if (!err) return;
    const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter((x) => x && x !== err.id);
    if (invalid) ids.push(err.id);
    if (ids.length) el.setAttribute('aria-describedby', ids.join(' '));
    else el.removeAttribute('aria-describedby');
  }
  function syncField(el) {
    if (!el?.id || !ERROR_FIELDS.includes(el.id)) return;
    setFieldState(el.id, el.matches(':user-invalid'));
  }
  function validateSeries(payload) {
    const problems = [];
    const check = (id, ok, msg) => {
      setFieldState(id, !ok);
      if (!ok) problems.push({ el: form.querySelector(`#${id}`), msg });
    };
    const replay = form.querySelector('#oe-replay');
    check('oe-replay', !replay?.value || replay.checkValidity(), '回放链接需以 http:// 或 https:// 开头');
    return problems;
  }

  function collect() {
    const series = Object.fromEntries(new FormData(form).entries());
    const games = [...tbody.querySelectorAll('[data-oe-game]')].map((row) => {
      const field = (name) => text(row.querySelector(`[name="${name}"]`)?.value);
      const list = shots.get(Number(row.dataset.oeGame)) || [];
      const durationSec = (num(field('durationMin')) || 0) * 60 + (num(field('durationSec')) || 0);
      return {
        gameNo: Number(row.dataset.oeGame),
        scores: { own: num(field('scoreOwn')), foe: num(field('scoreFoe')) },
        result: field('result'),
        durationSec: durationSec || null,
        firstBlood: field('firstBlood'),
        firstTower: field('firstTower'),
        keyMetrics: {
          gpmOwn: num(field('gpmOwn')), gpmFoe: num(field('gpmFoe')),
          tyrantRate: rate(field('tyrant')), lordRate: rate(field('lord')),
          shadowTyrantRate: rate(field('shadowTyrant')), shadowLordRate: rate(field('shadowLord')),
        },
        teamStats: {
          towersOwn: num(field('towersOwn')), towersFoe: num(field('towersFoe')),
          at10: num(field('at10')),
        },
        lineups: readLineups(row),
        imageIds: list.map((item) => item.id),
        imageNames: list.map((item) => item.name),
      };
    });
    return {
      matchType: MATCH_TYPE,
      competitionId: (() => {
        try { return localStorage.getItem('training-current-competition') || ''; } catch { return ''; }
      })(),
      date: text(series.date), opponent: text(series.opponent), event: text(series.event),
      boFormat: num(series.boFormat) || 5, ownSide: text(series.ownSide),
      version: text(series.version), reviewer: text(series.reviewer),
      replayLink: text(series.replayLink),
      games,
    };
  }

  async function loadPending() {
    const box = document.querySelector('[data-oe-pending]');
    if (!box) return;
    try {
      const data = await fetch(API.pending)
        .then((r) => (r.ok ? r.json() : null));
      const entries = (data && data.entries) || [];
      if (!entries.length) { box.hidden = true; return; }
      box.hidden = false;
      box.innerHTML = `<b>待补全速记（先登记归属与对手库，这里转正进统计）</b><ul>${entries.map((e) => `
        <li><button type="button" class="control" data-oe-pick="${esc(e.match_key)}"
          data-oe-date="${esc(e.date || '')}" data-oe-opponent="${esc(e.opponent || '')}"
          data-oe-score="${esc(e.score || '')}" data-oe-lineup='${esc(e.formalEntry?.lineup ? JSON.stringify(e.formalEntry.lineup) : '[]')}'>转正补全</button>
        <span>${esc(e.date || '')} · ${esc(e.opponent || '')} · ${esc(e.score || '')} · ${esc(e.formalEntry?.depth || 'result')}</span></li>`).join('')}</ul>`;
    } catch { box.hidden = true; }
  }

  function prefillPending(entryKey) {
    const btn = document.querySelector(`[data-oe-pick="${entryKey}"]`);
    if (!btn) return;
    const dateInput = root.querySelector('#oe-date');
    const opponentInput = root.querySelector('#oe-opponent');
    if (dateInput && btn.dataset.oeDate) dateInput.value = btn.dataset.oeDate;
    if (opponentInput && btn.dataset.oeOpponent) opponentInput.value = btn.dataset.oeOpponent;
    try {
      const lineup = JSON.parse(btn.dataset.oeLineup || '[]');
      if (lineup.length) say(`已载入速记（${lineup.length} 行阵容，请核对逐局数据后保存转正）。`);
    } catch {}
  }

  async function runImport(fileInput) {
    const status = root.querySelector('[data-oe-import-status]');
    const file = fileInput.files?.[0];
    if (!file) { status.textContent = '请先选文件'; return; }
    let competition = '';
    try { competition = localStorage.getItem('training-current-competition') || ''; } catch {}
    if (!competition) { status.textContent = '先选赛事'; return; }
    const form = new FormData();
    form.append('file', file);
    form.append('competitionId', competition);
    status.textContent = '导入中…';
    try {
      const response = await fetch(`${API_BASE}/api/studio/official-entry/import`, {
        method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok) { status.textContent = data.detail || '导入失败'; return; }
      status.textContent = `导入 ${data.saved} 场（${data.dedup} 场已存在）${data.failed.length ? '，' + data.failed.length + ' 行报错' : ''}`;
    } catch (error) {
      status.textContent = error.message || '导入失败';
    }
  }

  async function save() {
    if (busy) return;
    const payload = collect();
    const problems = validateSeries(payload);
    if (problems.length) {
      say(`还有 ${problems.length} 处需要修改：${problems.map((p) => p.msg).join('；')}。`, 'error');
      problems[0].el?.focus();
      return;
    }
    if (!payload.games.length) { say('至少要有一局。', 'error'); return; }
    const badLineup = [...tbody.querySelectorAll('[data-oe-game]')].find((row) => !lineupsComplete(row));
    if (badLineup) {
      say('十人阵容每方必须恰好 5 人，请检查后重试。', 'error');
      const details = badLineup.querySelector('.oe-lineup-details');
      if (details) {
        details.open = true;
        details.querySelector('summary')?.scrollIntoView({ block: 'nearest' });
      }
      return;
    }
    busy = true;
    const button = form.querySelector('[data-oe-save]');
    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `${glyph('refresh', { size: 14, cls: 'oe-spin' })}保存中…`;
    say('正在保存…');
    try {
      const data = await api(API.entry, { method: 'POST', body: payload });
      const channels = data?.channels || [];
      resultBox.hidden = false;
      resultBox.innerHTML = `<h2>${glyph('victory', { size: 18 })}已保存 ${channels.length} 局</h2>
        <p>${data.finalized ? '已写入正式统计。' : '已写入采集通道，尚未进入正式统计；可在采集页复核后保存。'}
          ${data.warning ? `<br><span class="oe-warn">${esc(data.warning)}</span>` : ''}</p>
        <ul>${channels.map((item) => `<li>${esc(item.matchKey)} · 第 ${esc(item.gameNo)} 局
          <a href="#match-notes" data-oe-note-link="${esc(item.matchKey)}">写赛后笔记</a></li>`).join('')}</ul>`;
      say(`已保存 ${channels.length} 局。`, 'ok');
    } catch (error) {
      say(error?.message || '保存失败。', 'error');
    } finally {
      busy = false;
      button.disabled = false;
      button.removeAttribute('aria-busy');
      button.innerHTML = originalLabel;
    }
  }

  form.addEventListener('submit', (event) => { event.preventDefault(); save(); });
  form.addEventListener('blur', (event) => syncField(event.target), true);
  form.addEventListener('input', (event) => syncField(event.target));
  form.addEventListener('change', (event) => syncField(event.target), true);
  container.addEventListener('toggle', (event) => {
    const details = event.target.closest?.('.oe-lineup-details');
    if (details?.open) details.querySelector('summary')?.scrollIntoView({ block: 'nearest' });
  }, true);
  loadPending();
  root.querySelector('[data-oe-import-run]')?.addEventListener('click', () => {
    runImport(root.querySelector('[data-oe-import-file]'));
  });
  container.addEventListener('click', (event) => {
    const pick = event.target.closest('[data-oe-pick]');
    if (pick) prefillPending(pick.dataset.oePick);

    const undo = event.target.closest('[data-oe-undo]');
    if (undo) { const action = toastAction; hideToast(); action?.(); return; }
    const addGame = event.target.closest('[data-oe-add-game]');
    if (addGame) { setGameCount(tbody.querySelectorAll('[data-oe-game]').length + 1); return; }
    const removeGameBtn = event.target.closest('[data-oe-remove-game]');
    if (removeGameBtn) {
      removeGame(removeGameBtn.closest('[data-oe-game]'));
      return;
    }
    const addImage = event.target.closest('[data-oe-add-image]');
    if (addImage) { openImageDialog(Number(addImage.dataset.oeAddImage)); return; }
    const removeImage = event.target.closest('[data-oe-remove-image]');
    if (removeImage) {
      const no = Number(removeImage.dataset.oeRemoveImage);
      const previous = (shots.get(no) || []).slice();
      shots.set(no, previous.filter((item) => item.id !== removeImage.dataset.imageId));
      renderShots(no);
      showToast('已移除赛后数据图', () => { shots.set(no, previous); renderShots(no); say('已恢复数据图。', 'ok'); });
      return;
    }
    const noteLink = event.target.closest('[data-oe-note-link]');
    if (noteLink) {
      event.preventDefault();
      // 独立笔记页读取 hash 查询参数；lead 接线后可换成其路由 API。
      location.hash = `match-notes?match_key=${encodeURIComponent(noteLink.dataset.oeNoteLink)}`;
    }
  });
  container.querySelector('[data-oe-bo]')?.addEventListener('change', (event) => {
    setGameCount(num(event.target.value) || 1);
    say(`已切换为 BO${event.target.value}，请核对逐局数据。`);
  });
  fileInput.addEventListener('change', () => acceptFile(fileInput.files?.[0]));

  /* 拖放区：点击整块/键盘 Enter·Space 都能唤起文件选择，拖入文件走与粘贴相同的 acceptFile。 */
  drop.addEventListener('click', (event) => {
    if (event.target === fileInput) return; // 原生 Choose File 自己会触发 change，别重复弹窗
    fileInput.click();
  });
  drop.addEventListener('keydown', (event) => {
    if (event.target !== drop || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    fileInput.click();
  });
  for (const type of ['dragenter', 'dragover']) {
    drop.addEventListener(type, (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
      drop.classList.add('is-dragover');
    });
  }
  for (const type of ['dragleave', 'dragend']) {
    drop.addEventListener(type, (event) => {
      if (type === 'dragleave' && drop.contains(event.relatedTarget)) return;
      drop.classList.remove('is-dragover');
    });
  }
  drop.addEventListener('drop', (event) => {
    event.preventDefault();
    drop.classList.remove('is-dragover');
    const file = event.dataTransfer?.files?.[0];
    if (file) acceptFile(file);
    else imgError.textContent = '请拖入 PNG、JPEG 或 WebP 图片。';
  });
  // 拖到弹窗其它位置也不要让浏览器直接打开图片（丢掉本次录入）。
  dialog.addEventListener('dragover', (event) => event.preventDefault());
  dialog.addEventListener('drop', (event) => event.preventDefault());

  dialog.addEventListener('paste', (event) => {
    const item = [...(event.clipboardData?.items || [])].find((entry) => /^image\//i.test(entry.type));
    if (item) { event.preventDefault(); acceptFile(item.getAsFile()); }
  });
  dialog.querySelector('[data-oe-upload]')?.addEventListener('click', uploadPending);
  dialog.addEventListener('close', () => { imageGameNo = 0; });

  // 赛事候选：读不到不阻塞录入。
  api(API.competitions).then((data) => {
    const list = container.querySelector('[data-oe-events]');
    if (!list) return;
    list.innerHTML = (data?.competitions || []).map((item) => `<option value="${esc(item.name || item.title || item.id)}"></option>`).join('');
  }).catch(() => { /* 赛事候选是增强项 */ });

  const apiHandle = { collect, save, setGameCount, destroy: () => { dialog.close(); clearPending(); hideToast(); } };
  container.__officialEntryApi = apiHandle;
  return apiHandle;
}

/** 直接把页面挂到容器（等同 init，保留别名方便接线）。 */
export function mountOfficialEntry(container) { return initOfficialEntry(container); }

/** 可选自动挂载：只在容器显式标记 data-official-entry-page 时生效，不抢 #content 路由。 */
export function autoMountOfficialEntry(root = document) {
  const nodes = root.querySelectorAll('[data-official-entry-host]:not([data-oe-ready])');
  nodes.forEach((node) => { node.dataset.oeReady = '1'; initOfficialEntry(node); });
}

if (typeof document !== 'undefined') {
  const start = () => autoMountOfficialEntry(document);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}
