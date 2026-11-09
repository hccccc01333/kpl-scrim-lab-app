/* 逐项校对 —— 简单版。
 *
 * 定位：营地给的十人数据在这里核对与修改。不做跨来源冲突判定 ——
 * 营地是权威来源，其它渠道本来就可能出错，没必要让教练逐条仲裁。
 *
 * 接口（工作台根路径）：
 *   GET   /api/channels/{id}
 *   PATCH /api/channels/{id}/draft   {players:[{side,slot,hero?,fields:{...}}]}
 *   POST  /api/channels/{id}/review  {reviewedBy, notes}
 *   POST  /api/channels/{id}/save
 */

const ROOT_API = '/api/';

async function api(path, { method = 'GET', body, signal } = {}) {
  const response = await fetch(ROOT_API + path, {
    method,
    cache: 'no-store',
    signal,
    ...(body === undefined ? {} : {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* 非 JSON */ }
    throw new Error(typeof detail === 'string' ? detail : '采集接口不可用。校对页需要由 server.py 提供。');
  }
  return response.json();
}

const FIELDS = [
  ['kills', '击杀'], ['deaths', '死亡'], ['assists', '助攻'], ['gold', '经济'],
  ['damage', '输出'], ['taken', '承伤'], ['participation', '参团'], ['rating', '评分'],
];

const COL_KEY = 'v3-review-col-widths';
const DEFAULT_COLS = [52, 130, 140, 72, 62, 62, 82, 92, 82, 62, 62];

function loadColWidths() {
  try {
    const raw = JSON.parse(localStorage.getItem(COL_KEY) || 'null');
    if (Array.isArray(raw) && raw.length === DEFAULT_COLS.length) {
      return raw.map((w) => Math.max(40, Math.min(400, Number(w) || 60)));
    }
  } catch { /* 坏数据回退默认 */ }
  return [...DEFAULT_COLS];
}

const SOURCE_LABEL = {
  official: '官方回放', camp: '营地', table: '表格',
  video: '录屏', screenshot: '截图', replay: '回放',
};

function stamp(value) {
  const text = String(value || '');
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text;
}

function seconds(n) {
  const value = Number(n || 0);
  return value ? `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')}` : '';
}

export function createReview(h) {
  const { esc, icon, empty } = h;
  const text = (v) => esc(v === null || v === undefined || v === '' ? '—' : v);

  const state = { id: '', channel: null, busy: '', notice: null, notes: '',
    colWidths: typeof localStorage === 'undefined' ? [...DEFAULT_COLS] : loadColWidths() };

  async function load(_name, key, signal) {
    state.id = key || '';
    if (!state.id) return { channel: null };
    const channel = await api(`channels/${encodeURIComponent(state.id)}`, { signal });
    state.channel = channel;
    return { channel };
  }

  async function refresh() {
    state.channel = await api(`channels/${encodeURIComponent(state.id)}`);
  }

  function paint() {
    const root = document.querySelector('#content');
    if (root && state.channel) {
      root.innerHTML = view(state.id, { channel: state.channel });
      bindNotes();
    }
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  // ---------------- 组件 ----------------

  function valueCell(player, field, label) {
    const value = (player.fields || {})[field]?.value;
    const blank = value === null || value === undefined || value === '';
    return `<td class="ed-num"><input class="ed-input is-num${blank ? ' is-blank' : ''}"
      data-draft-side="${esc(player.side)}" data-draft-slot="${player.slot}" data-draft-field="${field}"
      type="number" step="any" inputmode="decimal" value="${esc(blank ? '' : value)}"
      aria-label="${esc(`${label} · ${player.side === 'left' ? '左' : '右'}${(player.slot ?? 0) + 1}`)}"></td>`;
  }

  function table(channel) {
    const players = (channel.draft || {}).players || [];
    if (!players.length) return empty('这局还没有营地十人面板。先补详情，再来核对。');
    let lastSide = null;
    const rows = players.map((player) => {
      const split = lastSide !== null && player.side !== lastSide;
      lastSide = player.side;
      return `<tr class="${split ? 'is-split' : ''}">
        <td class="ed-side"><i>${player.side === 'left' ? '左' : '右'}</i>${(player.slot ?? 0) + 1}</td>
        <td class="ed-name" title="${esc(player.nickname || '')}">${text(player.nickname)}</td>
        <td><input class="ed-input is-text" data-draft-side="${esc(player.side)}" data-draft-slot="${player.slot}"
          data-draft-field="hero" value="${esc(player.hero || '')}" aria-label="英雄"></td>
        ${FIELDS.map(([field, label]) => valueCell(player, field, label)).join('')}
      </tr>`;
    }).join('');

    const widths = state.colWidths;
    const total = widths.reduce((sum, w) => sum + w, 0);
    const labels = ['位置', '昵称', '英雄', ...FIELDS.map(([, label]) => label)];
    const grip = (index) => `<i class="col-grip" data-grip="${index}" title="拖动调整列宽"></i>`;
    const head = labels.map((label, index) => {
      const cls = index === 0 ? ' class="ed-side-h"' : index > 2 ? ' class="ed-num"' : '';
      return `<th${cls}>${esc(label)}${grip(index)}</th>`;
    }).join('');

    return `<div class="ed-wrap"><table class="ed-table" style="width:${total}px">
      <colgroup>${widths.map((w) => `<col style="width:${w}px">`).join('')}</colgroup>
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function header(channel) {
    const match = channel.match || {};
    const review = channel.review || {};
    const saved = channel.saved || {};
    const reviewed = review.status === 'reviewed';
    const isSaved = saved.status === 'saved';
    const hasPlayers = Boolean((channel.draft?.players || []).length);
    const left = match.scores?.left;
    const right = match.scores?.right;
    // 营地列表先建、详情还没补上的局没有比分；不要显示成 null : null。
    const score = left === null || left === undefined
      ? (right === null || right === undefined ? '比分未记录' : `— : ${right}`)
      : (right === null || right === undefined ? `${left} : —` : `${left} : ${right}`);
    const won = match.winner && match.ownSide ? match.winner === match.ownSide : null;
    const result = won === null ? '结果未知' : won ? '胜' : '负';
    const blocked = isSaved || !reviewed || state.busy;

    return `<section class="ed-top">
      <div>
        <div class="ed-meta">${text(match.date)} · ${text(match.session)} · ${text(match.mode)}${seconds(match.durationSec) ? ` · ${seconds(match.durationSec)}` : ''}</div>
        <div class="ed-score">
          <strong>${esc(score)}</strong>
          <span class="chip ${won === null ? 'is-idle' : won ? 'is-done' : 'is-warn'}">${esc(result)}</span>
          ${isSaved ? '<span class="chip is-done">已进正式统计</span>' : reviewed ? '<span class="chip is-ok">已复核</span>' : '<span class="chip is-pending">缺失值审查</span>'}
        </div>
      </div>
      <div class="ed-top-actions">
        <button class="control" data-review-action="save-draft" ${state.busy || !hasPlayers ? 'disabled' : ''}>
          ${state.busy === 'draft' ? '正在保存…' : '保存修改'}</button>
        <button class="primary" data-review-action="save-formal" ${blocked ? 'disabled' : ''}
          title="${isSaved ? '已经进入正式统计' : reviewed ? '写入正式统计' : '需要先在右侧标记复核'}">
          ${state.busy === 'save' ? '正在写入…' : (isSaved ? '已进正式统计' : '保存到正式统计')}</button>
      </div>
    </section>`;
  }

  function aside(channel) {
    const review = channel.review || {};
    const reviewed = review.status === 'reviewed';
    const ready = Boolean((channel.draft?.players || []).length) && Boolean(channel.sourceStatus?.complete);
    const counts = channel.sourceStatus?.counts || {};
    const required = channel.sourceStatus?.requiredSources || [];

    const sources = Object.keys(SOURCE_LABEL).map((key) => {
      const count = Number(counts[key] || 0);
      return `<li class="${count ? '' : 'is-off'}${required.includes(key) ? ' is-required' : ''}">
        <b>${esc(SOURCE_LABEL[key])}</b><small>${count || '缺失'}</small></li>`;
    }).join('');

    const log = (channel.changeLog || []).slice(-6).reverse()
      .map((item) => `<li><span>${stamp(item.at)}</span>${esc(item.action || '')}</li>`).join('');

    return `<aside class="ed-aside">
      <section class="ed-card"><h3>素材来源</h3><ul class="ed-sources">${sources}</ul></section>
      <section class="ed-card">
        <h3>复核</h3>
        ${!ready
          ? '<p class="ed-hint is-warn">这局还没有可核对的十人面板，先补详情。</p>'
          : reviewed
            ? `<p class="ed-hint">${text(review.reviewedBy)} · ${stamp(review.reviewedAt)}${review.notes ? `<br>${esc(review.notes)}` : ''}</p>`
            : '<p class="ed-hint">改完数据后，填一句备注并标记复核，才能保存到正式统计。</p>'}
        <textarea data-review-notes rows="2" placeholder="例如：按营地十人面板核对，输出以营地总伤害为准">${esc(state.notes)}</textarea>
        <button class="control ed-wide" data-review-action="review" ${state.busy || !ready ? 'disabled' : ''}>
          ${state.busy === 'review' ? '正在标记…' : (reviewed ? '更新复核备注' : '标记为已复核')}</button>
      </section>
      <section class="ed-card"><h3>变更记录</h3>
        <ul class="ed-log">${log || '<li class="ed-hint">还没有记录</li>'}</ul></section>
    </aside>`;
  }

  function view(id, value) {
    const channel = value?.channel;
    if (!channel) {
      return `<div class="page"><p class="capture-notice is-error">审查记录 ${esc(id)} 不存在。</p>
        <p><a class="control" href="#ingest">${icon('arrow')} 回到营地同步</a></p></div>`;
    }
    const notice = state.notice
      ? `<div class="capture-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`
      : '';
    const stale = channel.saved?.status === 'saved' && channel.review?.status !== 'reviewed'
      ? `<div class="capture-notice is-error" role="status">草稿已改动，但正式统计里仍是上一版。重新标记复核并保存后才会更新。</div>`
      : '';
    const missing = channel.draft?.missing || [];
    const missingText = missing.map((item) => `${item.label}缺${item.missing}/10`).join('、');
    const players = channel.draft?.players || [];
    const gameSeq = channel.official?.source?.gameSeq || channel.match?.gameSeq || '';
    const repairNote = players.length ? '' : `<div class="capture-notice is-error" role="status">
      <b>这局还没有营地十人面板。</b>先补挂本机详情，或回采集页重新拉取并同步这一局。
      <div class="notice-actions">
        ${gameSeq ? `<button class="control" data-review-action="attach-camp" ${state.busy ? 'disabled' : ''}>${state.busy === 'attach' ? '正在补挂…' : '补挂本机详情'}</button>` : ''}
        <a class="control" href="#ingest">回采集页重新同步</a>
      </div></div>`;
    const missingNote = missing.length
      ? `<div class="capture-notice is-error" role="status"><b>仍有 ${missing.length} 项缺失：</b>${esc(missingText)}。补齐后可直接保存；确认保留缺失，也可标记复核后保存。</div>`
      : '';
    const title = `${channel.match?.session || '未命名训练组'} · 缺失值审查`;

    return `<div class="page">
      <div class="page-intro"><div><h1>${esc(title)}</h1>
        <p>数据以营地十人面板为准，可直接修改；保存后需要重新标记复核。</p></div>
        <div class="intro-actions"><a class="control" href="#ingest">${icon('arrow')} 返回缺失值审查</a></div></div>
      ${notice}
      ${stale}
      ${repairNote}
      ${missingNote}
      ${header(channel)}
      <div class="ed-layout">
        <section class="ed-main">
          <div class="ed-panel-head"><h2>十人数据</h2>
            <span>拖表头边界可调列宽 · 改完点右上角「保存修改」</span></div>
          ${table(channel)}
        </section>
        ${aside(channel)}
      </div>
    </div>`;
  }

  // ---------------- 交互 ----------------

  function bindNotes() {
    document.querySelectorAll('[data-review-notes]').forEach((el) => {
      if (el.dataset.bound) return;
      el.dataset.bound = '1';
      el.addEventListener('input', () => { state.notes = el.value; });
    });
  }

  function collectPlayers() {
    const map = new Map();
    document.querySelectorAll('[data-draft-field]').forEach((input) => {
      const key = `${input.dataset.draftSide}-${input.dataset.draftSlot}`;
      if (!map.has(key)) {
        map.set(key, { side: input.dataset.draftSide, slot: Number(input.dataset.draftSlot), fields: {} });
      }
      const item = map.get(key);
      if (input.dataset.draftField === 'hero') item.hero = input.value.trim();
      else item.fields[input.dataset.draftField] = input.value;
    });
    return [...map.values()];
  }

  async function saveDraft() {
    const players = collectPlayers();
    if (!players.length) { setNotice('没有可保存的数据。', true); paint(); return; }
    state.busy = 'draft';
    setNotice('正在保存…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/draft`, { method: 'PATCH', body: { players } });
      await refresh();
      setNotice('已保存。复核状态已失效，需要重新标记复核。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function attachCamp() {
    const gameSeq = state.channel?.official?.source?.gameSeq || state.channel?.match?.gameSeq || '';
    if (!gameSeq) {
      setNotice('这局没有营地对局号，请回采集页重新拉取。', true);
      paint();
      return;
    }
    state.busy = 'attach';
    setNotice('正在补挂本机营地详情…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/camp`, {
        method: 'POST', body: { gameSeq },
      });
      await refresh();
      setNotice('已补挂营地十人面板。');
    } catch (error) {
      setNotice(`${error.message} 回采集页重新同步这一局。`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function markReviewed() {
    if (!(state.channel?.draft?.players || []).length) {
      setNotice('这局还没有十人面板，先补详情。', true);
      paint();
      return;
    }
    const missing = state.channel?.draft?.missing || [];
    if (missing.length) {
      const text = missing.map((item) => `${item.label}缺${item.missing}/10`).join('、');
      if (!window.confirm(`这局仍有 ${missing.length} 项缺失：${text}。\n\n确认按当前数据标记复核吗？标记后仍可保存到正式统计。`)) return;
    }
    state.busy = 'review';
    setNotice('正在标记复核…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/review`, {
        method: 'POST', body: { reviewedBy: '本机复核', notes: state.notes },
      });
      await refresh();
      setNotice('已标记为已复核，可以保存到正式统计。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function saveFormal() {
    const missing = state.channel?.draft?.missing || [];
    const text = missing.length
      ? `\n\n这局仍有 ${missing.length} 项缺失：${missing.map((item) => `${item.label}缺${item.missing}/10`).join('、')}。`
      : '';
    if (!window.confirm(`保存到正式统计？这会写入比赛记录。${text}`)) return;
    state.busy = 'save';
    setNotice('正在写入正式统计…');
    paint();
    try {
      const result = await api(`channels/${encodeURIComponent(state.id)}/save`, { method: 'POST' });
      await refresh();
      const key = result?.bundle?.key || result?.channel?.saved?.bundleKey || '';
      setNotice(key ? `已进入正式统计，比赛标识 ${key}` : '已保存到正式统计。');
    } catch (error) {
      setNotice(`保存失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function click(event) {
    const button = event.target.closest('[data-review-action]');
    if (!button) return false;
    const action = button.dataset.reviewAction;
    if (action === 'save-draft') { await saveDraft(); return true; }
    if (action === 'attach-camp') { await attachCamp(); return true; }
    if (action === 'review') { await markReviewed(); return true; }
    if (action === 'save-formal') { await saveFormal(); return true; }
    return false;
  }

  function bindColResize() {
    const table = document.querySelector('.ed-table');
    if (!table) return;
    const cols = table.querySelectorAll('colgroup col');
    document.querySelectorAll('[data-grip]').forEach((grip) => {
      if (grip.dataset.bound) return;
      grip.dataset.bound = '1';
      grip.addEventListener('mousedown', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const index = Number(grip.dataset.grip);
        const startX = event.clientX;
        const startWidth = state.colWidths[index];
        const onMove = (moveEvent) => {
          const width = Math.max(40, Math.min(400, startWidth + moveEvent.clientX - startX));
          state.colWidths[index] = Math.round(width);
          if (cols[index]) cols[index].style.width = `${width}px`;
          table.style.width = `${state.colWidths.reduce((sum, w) => sum + w, 0)}px`;
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.body.classList.remove('col-resizing');
          try { localStorage.setItem(COL_KEY, JSON.stringify(state.colWidths)); } catch { /* 忽略 */ }
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.body.classList.add('col-resizing');
      });
    });
  }

  function afterRender() { bindNotes(); bindColResize(); }

  return { load, render: view, click, afterRender };
}
