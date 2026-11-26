/* 重点关注对局：教练人工标记「这一局要拿去跟队员谈」。
 *
 * 复用 match-tags.js 的后端覆盖层，不新建一套存储：
 *   重点        —— 主标记，有它就算已关注
 *   重点:选手状态 / 重点:操作失误 / 重点:决策失误 / 重点:团队配合 / 重点:对手针对
 *              —— 原因标签，可多选，用于跨局统计
 *   tagNotes['重点'] —— 教练写下的「拿去对照的事实」，打开复盘时直接可见。
 *
 * 任何位置放 <button data-focus-match="key" ...> 都能打开同一个对话框；
 * 保存后派发 focus:change，页面自行刷新。
 */

import { glyph } from './ui-icons.js';
import {
  tagsOf, tagNotesOf, tagsReady, setMatchTags,
} from './match-tags.js';

export const FOCUS_TAG = '重点';
export const REASONS = ['选手状态', '操作失误', '决策失误', '团队配合', '对手针对'];
const REASON_TAGS = REASONS.map((name) => `${FOCUS_TAG}:${name}`);

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));
const text = (v) => String(v ?? '').trim();

let dialog = null;
let current = null;

/* 筛选状态放在模块里：保存关注后整页重绘，教练刚选的原因和搜索词不丢。 */
export const focusUi = { reason: '', query: '', onlyFocused: true };

export function applyFocusFilters() {
  const root = document.querySelector('[data-focus-page]');
  if (!root) return;
  const query = text(focusUi.query).toLowerCase();
  let visible = 0;
  root.querySelectorAll('[data-focus-row]').forEach((row) => {
    const reasons = (row.dataset.focusReasons || '').split('|').filter(Boolean);
    const hay = (row.dataset.focusText || '').toLowerCase();
    const show = (!focusUi.onlyFocused || row.dataset.focusIs === '1')
      && (!focusUi.reason || reasons.includes(focusUi.reason))
      && (!query || hay.includes(query));
    row.hidden = !show;
    if (show) visible++;
  });
  const count = root.querySelector('[data-focus-count]');
  if (count) count.textContent = `${visible} / ${root.querySelectorAll('[data-focus-row]').length} 局`;
  root.querySelectorAll('[data-focus-filter]').forEach((chip) => {
    chip.setAttribute('aria-pressed', String(chip.dataset.focusFilter === focusUi.reason));
  });
  const only = root.querySelector('[data-focus-only]');
  if (only) {
    only.setAttribute('aria-pressed', String(focusUi.onlyFocused));
    only.innerHTML = `${glyph('compare', { size: 16 })}<span>${focusUi.onlyFocused ? '只看已关注' : '显示全部对局'}</span>`;
  }
}

document.addEventListener('click', (event) => {
  const chip = event.target.closest?.('[data-focus-filter]');
  if (chip) {
    focusUi.reason = chip.dataset.focusFilter === focusUi.reason ? '' : chip.dataset.focusFilter;
    applyFocusFilters();
    return;
  }
  const only = event.target.closest?.('[data-focus-only]');
  if (only) {
    focusUi.onlyFocused = !focusUi.onlyFocused;
    /* 空状态下没有行可切，交给页面重绘一次，把 104 局列表渲染出来。 */
    if (!document.querySelector('[data-focus-row]')) {
      document.dispatchEvent(new CustomEvent('focus:change'));
      return;
    }
    applyFocusFilters();
  }
});

document.addEventListener('input', (event) => {
  if (!event.target.matches?.('[data-focus-search]')) return;
  focusUi.query = event.target.value;
  applyFocusFilters();
});

export function isFocused(key) {
  return tagsOf(key).includes(FOCUS_TAG);
}

export function reasonsOf(key) {
  return tagsOf(key).filter((tag) => REASON_TAGS.includes(tag)).map((tag) => tag.slice(FOCUS_TAG.length + 1));
}

export function focusNote(key) {
  return text(tagNotesOf(key)[FOCUS_TAG]);
}

export function focusStats(matches) {
  const counts = Object.fromEntries(REASONS.map((name) => [name, 0]));
  let focused = 0;
  let noted = 0;
  for (const match of matches || []) {
    if (!isFocused(match.key)) continue;
    focused++;
    if (focusNote(match.key)) noted++;
    for (const reason of reasonsOf(match.key)) {
      if (reason in counts) counts[reason]++;
    }
  }
  return { focused, noted, counts };
}

function metaLine(d) {
  const bits = [];
  if (d.date) bits.push(String(d.date).slice(0, 10));
  if (d.result) bits.push({ win: '胜', loss: '负', draw: '平' }[d.result] || d.result);
  if (d.score) bits.push(`比分 ${d.score}`);
  if (d.duration) bits.push(`时长 ${d.duration}`);
  if (d.diff !== undefined && d.diff !== null && d.diff !== '') bits.push(`经济差 ${d.diff}`);
  return bits.join(' · ');
}

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.className = 'focus-dialog';
  dialog.setAttribute('aria-labelledby', 'focus-dialog-title');
  dialog.innerHTML = `
    <form method="dialog" class="focus-dialog-head">
      <div class="focus-dialog-heading">
        <h2 id="focus-dialog-title">关注这一局</h2>
        <p class="focus-dialog-meta" data-focus-meta></p>
      </div>
      <button type="submit" value="cancel" class="focus-dialog-close" aria-label="关闭关注窗口">${glyph('ban', { size: 18 })}</button>
    </form>
    <form class="focus-dialog-form" data-focus-form aria-label="保存重点关注">
      <fieldset class="focus-reasons">
        <legend>为什么关注这一局</legend>
        <div class="focus-reason-grid">
          ${REASONS.map((name, i) => `<label class="focus-reason"><input type="checkbox" value="${esc(name)}" data-focus-reason${i === 0 ? ' autofocus' : ''}><span>${esc(name)}</span></label>`).join('')}
        </div>
      </fieldset>
      <label class="focus-note-field">
        <span>拿去对照的事实 / 要追问的点</span>
        <textarea data-focus-note rows="4" maxlength="300" placeholder="例：14 分钟第二波小龙团，打野先手交大后被集火；赛后看视野和沟通。"></textarea>
      </label>
      <div class="focus-dialog-actions">
        <button type="button" class="control focus-unfollow" data-focus-unfollow>${glyph('trash', { size: 18 })}取消关注</button>
        <button type="submit" class="control primary focus-save">${glyph('pick', { size: 18 })}保存关注</button>
      </div>
    </form>`;
  document.body.appendChild(dialog);

  dialog.querySelector('[data-focus-form]').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!current) return;
    const save = dialog.querySelector('.focus-save');
    save.disabled = true;
    const reasons = [...dialog.querySelectorAll('[data-focus-reason]:checked')].map((box) => box.value);
    const note = text(dialog.querySelector('[data-focus-note]').value);
    const nextTags = [...new Set([
      ...tagsOf(current.key).filter((tag) => tag !== FOCUS_TAG && !REASON_TAGS.includes(tag)),
      FOCUS_TAG,
      ...reasons.map((name) => `${FOCUS_TAG}:${name}`),
    ])];
    const nextNotes = { ...tagNotesOf(current.key) };
    if (note) nextNotes[FOCUS_TAG] = note;
    else delete nextNotes[FOCUS_TAG];
    try {
      await setMatchTags(current.key, nextTags, nextNotes);
      dialog.close();
      document.dispatchEvent(new CustomEvent('focus:change', { detail: { key: current.key } }));
    } catch (error) {
      window.alert(error.message || '关注保存失败');
    } finally {
      save.disabled = false;
    }
  });

  dialog.querySelector('[data-focus-unfollow]').addEventListener('click', async (event) => {
    if (!current) return;
    const button = event.currentTarget;
    button.disabled = true;
    const nextTags = tagsOf(current.key).filter((tag) => tag !== FOCUS_TAG && !REASON_TAGS.includes(tag));
    const nextNotes = { ...tagNotesOf(current.key) };
    delete nextNotes[FOCUS_TAG];
    try {
      await setMatchTags(current.key, nextTags, nextNotes);
      dialog.close();
      document.dispatchEvent(new CustomEvent('focus:change', { detail: { key: current.key, removed: true } }));
    } catch (error) {
      window.alert(error.message || '取消关注失败');
    } finally {
      button.disabled = false;
    }
  });

  return dialog;
}

export function openFocusDialog(trigger) {
  if (!trigger) return;
  const key = text(trigger.dataset.focusMatch);
  if (!key) return;
  current = {
    key,
    opponent: text(trigger.dataset.focusOpponent),
  };
  const node = ensureDialog();
  node.querySelector('[data-focus-meta]').textContent = metaLine({
    date: trigger.dataset.focusDate,
    result: trigger.dataset.focusResult,
    score: trigger.dataset.focusScore,
    duration: trigger.dataset.focusDuration,
    diff: trigger.dataset.focusDiff,
  }) || key;
  node.querySelector('#focus-dialog-title').textContent = current.opponent
    ? `关注 · ${current.opponent}` : '关注这一局';
  const active = reasonsOf(key);
  node.querySelectorAll('[data-focus-reason]').forEach((box) => {
    box.checked = active.includes(box.value);
  });
  node.querySelector('[data-focus-note]').value = focusNote(key);
  node.querySelector('[data-focus-unfollow]').hidden = !isFocused(key);
  node.showModal();
}

document.addEventListener('click', (event) => {
  const trigger = event.target.closest?.('[data-focus-match]');
  if (!trigger) return;
  event.preventDefault();
  openFocusDialog(trigger);
});

tagsReady().then(() => document.dispatchEvent(new CustomEvent('focus:ready')));
