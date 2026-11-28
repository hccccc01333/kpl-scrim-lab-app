/* 本队资料整页：战队信息 + 可自定义职称的人员配置；保存后展示本队资料卡。 */
import { glyph } from './ui-icons.js';

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const CSS_HREF = new URL('./team-profile.css?v=20261123staff4', import.meta.url).href;
const ROLE_DEFAULTS = [
  { key: 'headCoach', title: '主教练' },
  { key: 'viceCoach', title: '副教练' },
  { key: 'assistantCoach', title: '助教' },
  { key: 'dataAnalyst', title: '数据分析师' },
  { key: 'psychologist', title: '心理辅导' },
];
const BASE_FIELDS = ['teamName', 'league', 'season', 'organization'];

export function createTeamProfilePage(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc
    : (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const notify = typeof h.notify === 'function' ? h.notify : null;
  let root = null;
  let bound = false;
  let profile = {};
  let staffRows = [];
  let editing = true;
  let loading = true;
  let saving = false;
  let notice = '';

  function ensureCss() {
    if (document.querySelector('link[data-team-profile-css]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = CSS_HREF;
    link.dataset.teamProfileCss = '1';
    document.head.appendChild(link);
  }

  async function api(path, options = {}) {
    const response = await fetch(`${API_BASE}/api/${path}`, { cache: 'no-store', ...options });
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail || ''; } catch {}
      throw new Error(detail || `读取失败（${response.status}）`);
    }
    return response.json();
  }

  function say(message) {
    notice = String(message || '');
    paintNotice();
    if (notice && notify) notify(notice);
  }
  function paintNotice() {
    const node = root?.querySelector('[data-tp-notice]');
    if (!node) return;
    node.textContent = notice;
    node.hidden = !notice;
  }

  function normalizeRows(raw) {
    const list = Array.isArray(raw) && raw.length ? raw : ROLE_DEFAULTS.map((role) => ({
      ...role, name: profile[role.key] || '',
    }));
    const rows = list.filter((r) => r && typeof r === 'object').map((r, i) => ({
      key: String(r.key || `custom-${i}`),
      title: String(r.title || ''),
      name: String(r.name || ''),
    }));
    return rows.length ? rows : ROLE_DEFAULTS.map((role) => ({ ...role, name: '' }));
  }

  function staffRowHtml(row, i) {
    const id = `tp-role-${i}`;
    return `<div class="tp-role" data-tp-staff-row="${i}">
      <label for="${id}-title">职称<input id="${id}-title" name="staffTitle_${i}" maxlength="30" value="${esc(row.title)}" placeholder="如：主教练"></label>
      <label for="${id}-name">姓名<input id="${id}-name" name="staffName_${i}" maxlength="30" value="${esc(row.name)}" placeholder="真实姓名"></label>
      <button type="button" class="tp-role-remove" data-tp-remove="${i}" aria-label="删除第 ${i + 1} 项人员配置">${glyph('trash', { size: 16 })}</button>
    </div>`;
  }

  function cardHtml() {
    const name = String(profile.teamName || '').trim();
    const badges = [profile.league, profile.season].filter((x) => String(x || '').trim());
    const people = staffRows;
    const updated = profile.updatedAt ? String(profile.updatedAt).replace('T', ' ').slice(0, 16) : '';
    return `<article class="tp-card-view" aria-label="本队资料卡">
      <div class="tp-card-top">
        <div><span class="tp-card-tag">本队资料卡</span><h2>${esc(name)}</h2>
          <div class="tp-card-badges">${badges.map((b) => `<span>${esc(b)}</span>`).join('')}</div></div>
        <button type="button" class="control" data-tp-edit>${glyph('edit', { size: 18 })}编辑资料</button>
      </div>
      <dl class="tp-card-meta">
        <div><dt>组织</dt><dd>${esc(profile.organization || '—')}</dd></div>
        <div><dt>联赛 / 等级</dt><dd>${esc(profile.league || '—')}</dd></div>
        <div><dt>赛季</dt><dd>${esc(profile.season || '—')}</dd></div>
        <div><dt>最近更新</dt><dd>${esc(updated || '—')}</dd></div>
      </dl>
      <div class="tp-card-people">
        <h3>人员配置</h3>
        <div class="tp-people-grid">${people.length ? people.map((row) => {
          const named = String(row.name || '').trim();
          if (!named) return `<button type="button" class="tp-person is-empty" data-tp-edit aria-label="添加${esc(row.title || '教练组成员')}姓名">
            <span class="tp-person-avatar" aria-hidden="true">＋</span>
            <span class="tp-person-copy"><b>添加姓名</b><small>${esc(row.title || '教练组成员')}</small></span>
            <i class="tp-person-go" aria-hidden="true">→</i>
          </button>`;
          return `<div class="tp-person is-filled">
            <span class="tp-person-avatar" aria-hidden="true">${esc(named.slice(0, 1))}</span>
            <span class="tp-person-copy"><b>${esc(named)}</b><small>${esc(row.title || '教练组成员')}</small></span>
          </div>`;
        }).join('') : `<p class="tp-empty">${glyph('players', { size: 20 })}<b>还没有人员配置</b><span>点上方「编辑资料」添加</span></p>`}</div>
      </div>
    </article>`;
  }

  function formHtml() {
    return `<form class="feature-form tp-form" data-tp-form novalidate aria-labelledby="tp-form-title">
      <fieldset><legend id="tp-form-title">战队信息</legend>
        <div class="tp-grid">
          <label for="tp-teamName">战队名称 *<input id="tp-teamName" name="teamName" required maxlength="50" placeholder="如：成都 AG 超玩会" value="${esc(profile.teamName || '')}"></label>
          <label for="tp-league">联赛 / 等级<input id="tp-league" name="league" maxlength="40" list="tp-league-options" placeholder="如：KPL" value="${esc(profile.league || '')}"></label>
          <label for="tp-season">赛季<input id="tp-season" name="season" maxlength="40" placeholder="如：2026 春季赛" value="${esc(profile.season || '')}"></label>
          <label for="tp-organization">组织<input id="tp-organization" name="organization" maxlength="60" placeholder="如：AG 电子竞技俱乐部" value="${esc(profile.organization || '')}"></label>
        </div>
        <datalist id="tp-league-options"><option value="KPL"></option><option value="K甲"></option><option value="女子联赛"></option></datalist>
      </fieldset>
      <fieldset><legend>人员配置</legend>
        <div class="tp-roles" data-tp-roles>${staffRows.map(staffRowHtml).join('')}</div>
        <button type="button" class="control tp-add" data-tp-add>${glyph('players', { size: 18 })}添加岗位</button>
      </fieldset>
      <div class="form-footer"><p class="form-status" role="status" aria-live="polite"></p>
        <button class="primary" type="submit" ${saving ? 'disabled' : ''}>${glyph('shield', { size: 18 })}${saving ? '保存中…' : '保存本队资料'}</button></div>
    </form>`;
  }

  function render() {
    if (!root) return;
    root.innerHTML = `<div class="page sx-page tp-page">
      <header class="tp-head tp-head--clean"><h1>本队</h1></header>
      <p class="tp-notice" data-tp-notice role="status" aria-live="polite" hidden></p>
      ${loading ? '<p class="tp-loading">正在读取本队资料…</p>'
        : (editing || !profile.teamName ? formHtml() : cardHtml())}
    </div>`;
    paintNotice();
  }

  function readForm() {
    const form = root?.querySelector('[data-tp-form]');
    if (!form) return null;
    const base = {};
    for (const key of BASE_FIELDS) base[key] = form.querySelector(`[name="${key}"]`)?.value ?? '';
    const staff = staffRows.map((_, i) => ({
      key: staffRows[i].key,
      title: form.querySelector(`[name="staffTitle_${i}"]`)?.value ?? '',
      name: form.querySelector(`[name="staffName_${i}"]`)?.value ?? '',
    }));
    return { base, staff };
  }

  function syncAndRender(mutator) {
    const read = readForm();
    if (read) { profile = { ...profile, ...read.base }; staffRows = read.staff; }
    mutator?.();
    render();
  }

  async function load() {
    loading = true; render();
    try {
      const data = await api('v3/workspace/overview');
      profile = data?.overview?.profile || {};
      staffRows = normalizeRows(profile.staff);
      editing = !String(profile.teamName || '').trim();
    } catch (error) {
      say(error.message || '本队资料读取失败。');
    } finally {
      loading = false; render();
    }
  }

  async function onSubmit(event) {
    const form = event.target.closest('[data-tp-form]');
    if (!form || !root?.contains(form)) return;
    event.preventDefault();
    const read = readForm();
    if (!read) return;
    const field = form.querySelector('[name="teamName"]');
    if (!String(read.base.teamName || '').trim()) {
      field.setAttribute('aria-invalid', 'true');
      field.focus();
      say('请先填写战队名称。');
      return;
    }
    field.removeAttribute('aria-invalid');
    const staff = read.staff.map((row) => ({
      ...row,
      title: String(row.title).trim(), name: String(row.name).trim(),
    })).filter((row) => row.title || row.name);
    const roleName = (key) => (staff.find((row) => row.key === key) || {}).name || '';
    const payload = {
      ...read.base,
      coach: roleName('headCoach'),
      viceCoach: roleName('viceCoach'),
      assistantCoach: roleName('assistantCoach'),
      dataAnalyst: roleName('dataAnalyst'),
      psychologist: roleName('psychologist'),
      staff,
      updatedAt: new Date().toISOString(),
    };
    saving = true; render();
    try {
      const data = await api('studio/profile', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      profile = { ...profile, ...payload, ...(data || {}) };
      staffRows = normalizeRows(profile.staff);
      editing = false;
      say('本队资料已保存。');
    } catch (error) {
      editing = true;
      say(error.message || '保存失败，请稍后再试。');
    } finally {
      saving = false; render();
    }
  }

  function onClick(event) {
    if (!root?.contains(event.target)) return;
    const add = event.target.closest('[data-tp-add]');
    if (add) {
      syncAndRender(() => staffRows.push({ key: `custom-${Date.now().toString(36)}`, title: '', name: '' }));
      return;
    }
    const remove = event.target.closest('[data-tp-remove]');
    if (remove) {
      const index = Number(remove.dataset.tpRemove);
      syncAndRender(() => staffRows.splice(index, 1));
      return;
    }
    if (event.target.closest('[data-tp-edit]')) {
      const read = readForm();
      if (read) { profile = { ...profile, ...read.base }; staffRows = read.staff; }
      editing = true; render();
    }
  }

  function mount(node) {
    if (!node) return;
    ensureCss();
    if (!bound) {
      node.addEventListener('submit', onSubmit);
      node.addEventListener('click', onClick);
      bound = true;
    }
    root = node;
    load();
  }
  function dispose() {
    if (root && bound) {
      root.removeEventListener('submit', onSubmit);
      root.removeEventListener('click', onClick);
      bound = false;
    }
    root = null;
  }
  return { render, mount, dispose, load: () => { if (root) load(); } };
}

export default createTeamProfilePage;
