/**
 * 快照中心：按赛事卡查看六类规则的整份快照。
 * 右键思路：当下内容随便改；快照是赛事级的定格。跨赛事覆盖会弹警告确认。
 */
import {
  SNAPSHOT_MODULES, currentCompetitionId, currentCompetitionName,
  fetchCompetitions, loadSnapshots, saveSnapshot, restoreSnapshot,
  deleteSnapshot, snapshotBrief,
} from './rule-snapshots.js?v=20261124snap';
import { glyph } from './ui-icons.js';

const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

export function createSnapshotCenter(h = {}) {
  const esc = typeof h.esc === 'function' ? h.esc : (v) => String(v ?? '');
  const API_BASE = h.API_BASE ?? DEFAULT_API_BASE;
  const icon = typeof h.icon === 'function' ? h.icon : () => '';
  const notify = typeof h.notify === 'function' ? h.notify : null;
  const portrait = typeof h.portrait === 'function' ? h.portrait : (name) =>
    `<span class="portrait portrait-placeholder sc-hero-img" aria-label="${esc(name || '未知英雄')}">${esc((name || '?')[0])}</span>`;
  const uid = 'sc-' + Math.random().toString(36).slice(2, 9);

  let root = null;
  let controller = null;
  const state = {
    competitions: [], snapshots: {}, loading: false,
    open: {}, pending: null, busy: '', notice: '', noticeError: false,
  };

  const MODULE_ROUTE = {
    hero_tags: 'rules', counters: 'rules', misc: 'rules',
    lineup_tags: 'lineup-tags', combos: 'combo-pool', grade_rules: 'grade-rules',
  };
  const compById = (id) => state.competitions.find((c) => String(c.id) === String(id));
  const compLabel = (c) => c?.name || c?.id || '未命名赛事';
  const compRange = (c) => [String(c?.date || '').slice(0, 10), String(c?.end_date || '').slice(0, 10)]
    .filter(Boolean).join(' ~ ') || '未填时间';
  const snapshotAt = (compId, module) => state.snapshots?.competitions?.[compId]?.[module] || null;
  const today = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  /** 已结束的赛事不展示历史快照：口径早已过期，不能被误回滚。 */
  const isExpired = (comp) => {
    const end = String(comp?.end_date || '').slice(0, 10);
    return Boolean(end) && end < today();
  };
  const visibleSnapshot = (compId, module) => (isExpired(compById(compId)) ? null : snapshotAt(compId, module));
  const compCount = (id) => SNAPSHOT_MODULES.filter((m) => visibleSnapshot(id, m.key)).length;
  const lastSavedAt = (comp) => SNAPSHOT_MODULES
    .map((m) => visibleSnapshot(comp.id, m.key)?.savedAt)
    .filter(Boolean)
    .sort()
    .pop();
  const shortTime = (value) => String(value || '').slice(0, 16).replace('T', ' ');

  function announce(text, options = {}) {
    if (notify) notify(text, options);
    state.notice = String(text || '');
    state.noticeError = Boolean(options.error);
    const node = root?.querySelector('[data-sc-status]');
    if (node) {
      node.textContent = text;
      node.hidden = false;
      node.classList.toggle('is-error', Boolean(options.error));
    }
  }

  async function load() {
    if (!root) return;
    state.loading = true;
    paintStatus();
    try {
      const [comps, snaps] = await Promise.all([
        fetchCompetitions(API_BASE), loadSnapshots(API_BASE),
      ]);
      state.competitions = comps;
      state.snapshots = snaps;
      paint();
    } catch (error) {
      announce(error.message || '快照中心读取失败。', { error: true });
    } finally {
      state.loading = false;
      paintStatus();
    }
  }

  function paintStatus() {
    const node = root?.querySelector('[data-sc-status]');
    if (!node) return;
    const message = state.busy || (state.loading ? '正在读取快照…' : state.notice);
    node.hidden = !message;
    node.textContent = message;
    node.classList.toggle('is-error', !state.busy && !state.loading && state.noticeError);
  }

  /** 快照里的英雄一律用头像展示；名字只放在 title / aria-label 里，不占正文。 */
  const heroAvatars = (names = []) => {
    const list = (Array.isArray(names) ? names : [names]).filter(Boolean);
    if (!list.length) return '<span class="sc-mini">—</span>';
    return `<span class="sc-heroes">${list.map((name) =>
      `<span class="sc-hero" title="${esc(name)}">${portrait(name, 'sc-hero-img')}</span>`).join('')}</span>`;
  };

  function previewHtml(module, doc = {}) {
    if (module === 'counters') {
      const rows = [...(doc.heroPairs || []), ...(doc.comboPairs || [])].slice(0, 30);
      return `<ul class="sc-preview-list">${rows.map((r) => {
        const a = r.aHeroes || (r.a ? [r.a] : []);
        const b = r.bHeroes || (r.b ? [r.b] : []);
        return `<li>${heroAvatars(a)} <b>→</b> ${heroAvatars(b)} <span class="sc-mini">${esc(r.strength || '')}</span></li>`;
      }).join('') || '<li>空规则表</li>'}</ul>`;
    }
    if (module === 'hero_tags') {
      const names = Object.keys(doc.heroes || {}).slice(0, 80);
      return `<p class="sc-mini">共 ${Object.keys(doc.heroes || {}).length} 个英雄标签</p>${heroAvatars(names)}`;
    }
    if (module === 'misc') {
      return `<ul class="sc-preview-list">${(doc.entries || []).slice(0, 30)
        .map((r) => `<li>${esc(r.group || '')} · ${esc(r.key || '')}：${esc(String(r.value ?? '').slice(0, 120))}</li>`).join('') || '<li>空规则表</li>'}</ul>`;
    }
    if (module === 'lineup_tags') {
      return `<ul class="sc-preview-list">${(doc.tags || []).slice(0, 30)
        .map((r) => `<li><b>${esc(r.name || r.id || '')}</b> ${heroAvatars(r.heroes || [])}</li>`).join('') || '<li>空标签表</li>'}</ul>`;
    }
    if (module === 'combos') {
      const rows = [...(doc.pairs || []), ...(doc.trios || [])].slice(0, 30);
      return `<ul class="sc-preview-list">${rows.map((r) => `<li>${heroAvatars(r.heroes || [])}</li>`).join('') || '<li>空组合池</li>'}</ul>`;
    }
    if (module === 'grade_rules') {
      const parts = Object.entries(doc.subjects || {}).slice(0, 8).map(([subject, fields]) =>
        `<li>${esc(subject)}：${Object.entries(fields || {}).slice(0, 8)
          .map(([field, rule]) => `${esc(field)}${rule?.active === false ? '（停用）' : ''}`).join('、')}</li>`);
      return `<ul class="sc-preview-list">${parts.join('') || '<li>空规则表</li>'}</ul>`;
    }
    return `<pre class="sc-json">${esc(JSON.stringify(doc, null, 2).slice(0, 3000))}</pre>`;
  }

  function moduleHtml(comp, module) {
    const expired = isExpired(comp);
    const snap = visibleSnapshot(comp.id, module.key);
    const open = state.open[`${comp.id}::${module.key}`];
    const stateWord = snap ? '已打包' : expired ? '已结束' : '未打包';
    const brief = snap ? snapshotBrief(module.key, snap.doc) : stateWord;
    return `<div class="sc-module${open ? ' is-open' : ''}${snap ? ' is-ready' : ''}${expired ? ' is-expired' : ''}">
      <button type="button" class="sc-module-head" data-sc-toggle="${esc(comp.id)}::${esc(module.key)}"
        aria-expanded="${open ? 'true' : 'false'}">
        <span class="sc-mark" aria-hidden="true">${snap ? '✓' : expired ? '—' : '○'}</span>
        <span class="sc-module-name">${esc(module.label)}</span>
        <span class="sc-module-brief">${esc(brief)}</span>
        <span class="sc-module-meta">${snap ? `r${snap.revision} · ${esc(shortTime(snap.savedAt))}` : '—'}</span>
        <span class="sc-caret" aria-hidden="true"></span>
      </button>
      ${open ? `<div class="sc-module-body">
        <p class="sc-module-hint">${esc(module.hint)} <a href="#${MODULE_ROUTE[module.key] || 'rules'}">去编辑当下内容 →</a></p>
        ${expired ? `<p class="sc-expired-note">赛事已结束：历史快照不再展示，也不能回滚；只能用当下内容打包覆盖，供归档留痕。</p>
          <div class="sc-actions">
            <button type="button" class="primary" data-sc-expired-pack="${esc(comp.id)}::${esc(module.key)}">${glyph('export', { size: 18 })}用当下覆盖此快照</button>
          </div>`
        : snap ? `<div class="sc-snapshot-preview">${previewHtml(module.key, snap.doc)}</div>
          <div class="sc-actions">
            <button type="button" class="primary" data-sc-restore="${esc(comp.id)}::${esc(module.key)}">${glyph('refresh', { size: 18 })}用此快照覆盖当下</button>
            <button type="button" class="control" data-sc-overwrite="${esc(comp.id)}::${esc(module.key)}">${glyph('export', { size: 18 })}用当下覆盖此快照</button>
            <button type="button" class="control sc-danger" data-sc-delete="${esc(comp.id)}::${esc(module.key)}">${glyph('trash', { size: 18 })}删除快照</button>
          </div>`
        : `<div class="sc-actions">
            <button type="button" class="primary" data-sc-overwrite="${esc(comp.id)}::${esc(module.key)}">${glyph('export', { size: 18 })}用当下打包此赛事快照</button>
          </div>`}
      </div>` : ''}
    </div>`;
  }

  function html() {
    const current = currentCompetitionId();
    return `<div class="sc-page">
      <section class="section sc-lead">
        <div class="section-heading"><div>
          <h1>快照中心</h1>
          <p class="sc-lede">规则是全局共享的，改一处会影响所有赛事的复盘。这里给每场赛事留一份<span class="sc-em">当下内容的定格</span>：需要时把旧快照取回当下，或把当下重新打包归档。已结束的赛事只留记录，不再回滚口径。</p>
        </div>
          <div class="sc-lead-actions">
            <span class="sc-current" data-sc-current></span>
            <button type="button" class="control" data-sc-packall disabled aria-describedby="${uid}-packall-help">${glyph('export', { size: 18 })}一键打包当前赛事</button>
            <button type="button" class="control" data-sc-refresh>${glyph('refresh', { size: 18 })}刷新</button>
          </div></div>
        <p class="sc-packall-help" id="${uid}-packall-help" data-sc-packall-help>先在顶栏选择赛事，才能一键打包六类规则。</p>
        <p class="sc-status" data-sc-status hidden></p>
      </section>
      <section class="sc-how" aria-label="使用说明">
        <details data-sc-how>
          <summary class="sc-how-title">怎么用：打包 / 取回 / 留痕</summary>
          <div class="sc-how-body">
            <ol class="sc-how-steps">
              <li><b>打包</b><span>在对应赛事卡里，把当下六类规则整份存成快照</span></li>
              <li><b>取回</b><span>展开一份快照，点「用此快照覆盖当下」回到那个版本</span></li>
              <li><b>留痕</b><span>跨赛事覆盖会先确认；已结束赛事只允许按当下打包覆盖</span></li>
            </ol>
            <div class="sc-legend">
              <span><i class="sc-legend-dot is-ready"></i>已打包</span>
              <span><i class="sc-legend-dot is-empty"></i>未打包</span>
              <span><i class="sc-legend-dot is-current"></i>当前赛事</span>
              <span class="sc-legend-note">六类：${SNAPSHOT_MODULES.map((m) => esc(m.label)).join(' · ')}</span>
            </div>
          </div>
        </details>
      </section>
      <div class="sc-section-head"><h2>赛事快照</h2><span data-sc-grid-count></span></div>
      <div class="sc-grid" data-sc-grid></div>
      <dialog class="sc-dialog" data-sc-dialog aria-labelledby="${uid}-dialog-title" closedby="closerequest">
        <div class="sc-dialog-head"><h2 id="${uid}-dialog-title" data-sc-dialog-title>确认覆盖</h2></div>
        <div class="sc-dialog-body" data-sc-dialog-body></div>
        <div class="sc-dialog-foot">
          <button type="button" class="control" data-sc-cancel autofocus>${glyph('ban', { size: 18 })}取消</button>
          <button type="button" class="primary" data-sc-confirm>${glyph('pick', { size: 18 })}确认覆盖</button>
        </div>
      </dialog>
    </div>`;
  }

  function paint() {
    if (!root) return;
    const current = currentCompetitionId();
    const cur = root.querySelector('[data-sc-current]');
    if (cur) cur.textContent = current
      ? `当前赛事：${currentCompetitionName() || compLabel(compById(current)) || current}`
      : '当前赛事：未选择（顶栏「选择赛事」）';
    const packAll = root.querySelector('[data-sc-packall]');
    if (packAll) {
      packAll.disabled = !current || Boolean(state.busy);
      packAll.title = current ? '把当前赛事的六类规则一起打包' : '请先在顶栏选择赛事';
    }
    const packHelp = root.querySelector('[data-sc-packall-help]');
    if (packHelp) packHelp.textContent = current
      ? `将打包到：${currentCompetitionName() || compLabel(compById(current)) || current}`
      : '未选择赛事：请先在顶栏选择赛事，才能一键打包六类规则。';
    const grid = root.querySelector('[data-sc-grid]');
    if (!grid) return;
    const comps = state.competitions;
    const countNode = root.querySelector('[data-sc-grid-count]');
    if (countNode) countNode.textContent = comps.length ? `${comps.length} 个赛事` : '';
    grid.innerHTML = comps.length ? comps.map((comp) => {
      const count = compCount(comp.id);
      const isCurrent = String(comp.id) === String(current);
      const expired = isExpired(comp);
      const saved = lastSavedAt(comp);
      const status = expired ? '已结束' : isCurrent ? '当前赛事' : '历史赛事';
      return `<article class="sc-card${isCurrent ? ' is-current' : ''}${expired ? ' is-ended' : ''}">
        <header class="sc-card-head">
          <div class="sc-card-title"><h3>${esc(compLabel(comp))}</h3><p>${esc(compRange(comp))}</p></div>
          <div class="sc-badges">
            <span class="sc-badge ${expired ? 'is-ended' : isCurrent ? 'is-current' : ''}">${status}</span>
            <span class="sc-badge is-count">${expired ? '历史快照已隐藏' : `${count}/${SNAPSHOT_MODULES.length} 已打包`}</span>
          </div>
        </header>
        ${expired ? '' : `<div class="sc-progress" role="img" aria-label="已打包 ${count} / ${SNAPSHOT_MODULES.length}">
          <i style="inline-size:${Math.round(count / SNAPSHOT_MODULES.length * 100)}%"></i>
        </div>`}
        ${expired ? '' : `<div class="sc-card-meta">
          <span>${saved ? `最近打包 ${esc(shortTime(saved))}` : '还没有打包任何快照'}</span>
        </div>`}
        ${expired ? `<div class="sc-ended-empty" role="note">
          <b>历史快照已隐藏</b>
          <p>赛事已结束：六类旧快照统一不展示，也不能回滚。需要留痕时，可用当下内容重新打包归档。</p>
          <button type="button" class="control" data-sc-expired-packall="${esc(comp.id)}">${glyph('export', { size: 18 })}用当下打包六类快照</button>
        </div>` : `<div class="sc-modules">${SNAPSHOT_MODULES.map((m) => moduleHtml(comp, m)).join('')}</div>`}
      </article>`;
    }).join('') : `<div class="sc-empty">${glyph('calendar', { size: 28 })}<b>还没有赛事卡</b><a class="control" href="#competitions">${glyph('calendar', { size: 18 })}创建赛事</a></div>`;
    paintStatus();
  }

  function confirmDialog({ title, body, danger = false, onConfirm }) {
    const dialog = root?.querySelector('[data-sc-dialog]');
    if (!dialog) return;
    dialog.querySelector('[data-sc-dialog-title]').textContent = title;
    dialog.querySelector('[data-sc-dialog-body]').innerHTML = body;
    dialog.querySelector('.sc-dialog-foot').classList.toggle('is-danger', danger);
    state.pending = onConfirm;
    dialog.showModal();
  }

  function warnCross(from, to, action) {
    return `<p class="sc-warn">${glyph('warning', { size: 18 })}注意：你正在把「${esc(from)}」的内容覆盖到「${esc(to)}」的${esc(action)}。</p>
      <p>跨赛事覆盖会让两份赛事的规则关系混在一起，历史复盘可能读到不属于该赛事的克制 / 标签口径。请先确认这是你想要的，三思后行。</p>`;
  }

  async function withBusy(label, fn) {
    state.busy = label;
    paintStatus();
    try { await fn(); }
    catch (error) { announce(error.message || '操作失败。', { error: true }); }
    finally {
      state.busy = '';
      paintStatus();
      await load();
    }
  }

  function onClick(event) {
    const refresh = event.target.closest('[data-sc-refresh]');
    if (refresh) { load(); return; }
    const packAll = event.target.closest('[data-sc-packall]');
    if (packAll) {
      const id = currentCompetitionId();
      if (!id) { announce('请先在顶栏选择赛事。', { error: true }); return; }
      withBusy('正在打包六个模块…', async () => {
        for (const m of SNAPSHOT_MODULES) await saveSnapshot(m.key, id, `${m.label} · 一键打包`, API_BASE);
        announce(`已把六个模块打包到「${currentCompetitionName() || id}」。`);
      });
      return;
    }
    const toggle = event.target.closest('[data-sc-toggle]');
    if (toggle) {
      const key = toggle.dataset.scToggle;
      state.open[key] = !state.open[key];
      paint();
      return;
    }
    if (event.target.closest('[data-sc-cancel]')) {
      root?.querySelector('[data-sc-dialog]')?.close();
      state.pending = null;
      return;
    }
    if (event.target.closest('[data-sc-confirm]')) {
      const fn = state.pending;
      state.pending = null;
      root?.querySelector('[data-sc-dialog]')?.close();
      if (fn) fn();
      return;
    }
    const expiredPackAll = event.target.closest('[data-sc-expired-packall]');
    if (expiredPackAll) {
      const compId = expiredPackAll.dataset.scExpiredPackall;
      const comp = compById(compId);
      if (!isExpired(comp)) return;
      confirmDialog({ title: '确认归档已结束赛事', danger: true,
        body: `<p>将用当下六类规则覆盖「${esc(compLabel(comp))}」的历史归档。旧快照不会展示，也不能回滚。</p><p>确定继续吗？</p>`,
        onConfirm: () => withBusy('正在按当下内容打包六类快照…', async () => {
          for (const m of SNAPSHOT_MODULES) await saveSnapshot(m.key, compId, `${m.label} · 已结束赛事按当下归档`, API_BASE);
          announce(`已用当下六类规则归档「${compLabel(comp)}」。`);
        }) });
      return;
    }
    const expiredPack = event.target.closest('[data-sc-expired-pack]');
    if (expiredPack) {
      const [compId, module] = expiredPack.dataset.scExpiredPack.split('::');
      const mod = SNAPSHOT_MODULES.find((m) => m.key === module);
      withBusy('正在按当下内容打包…', async () => {
        await saveSnapshot(module, compId, `${mod.label} · 已结束赛事按当下打包`, API_BASE);
        announce(`已用当下${mod.label}覆盖「${compLabel(compById(compId))}」的快照。`);
      });
      return;
    }
    const restore = event.target.closest('[data-sc-restore]');
    if (restore) {
      const [compId, module] = restore.dataset.scRestore.split('::');
      if (isExpired(compById(compId))) return;
      const snap = snapshotAt(compId, module);
      const mod = SNAPSHOT_MODULES.find((m) => m.key === module);
      const cross = String(compId) !== String(currentCompetitionId());
      const run = () => withBusy('正在恢复快照…', async () => {
        await restoreSnapshot(module, snap.doc, API_BASE);
        announce(`已用「${compLabel(compById(compId))}」的${mod.label}快照覆盖当下。`);
      });
      if (cross) {
        confirmDialog({
          title: '跨赛事恢复确认',
          danger: true,
          body: warnCross(compLabel(compById(compId)), currentCompetitionName() || '当前赛事', '当下内容'),
          onConfirm: run,
        });
      } else run();
      return;
    }
    const overwrite = event.target.closest('[data-sc-overwrite]');
    if (overwrite) {
      const [compId, module] = overwrite.dataset.scOverwrite.split('::');
      if (isExpired(compById(compId))) return;
      const mod = SNAPSHOT_MODULES.find((m) => m.key === module);
      const cross = String(compId) !== String(currentCompetitionId());
      const run = () => withBusy('正在打包快照…', async () => {
        await saveSnapshot(module, compId, `${mod.label} · 快照中心打包`, API_BASE);
        announce(`已把当下${mod.label}覆盖到「${compLabel(compById(compId))}」快照。`);
      });
      confirmDialog({
        title: cross ? '跨赛事覆盖警告' : '覆盖快照确认',
        danger: cross,
        body: cross
          ? warnCross(currentCompetitionName() || '当前赛事', compLabel(compById(compId)), '赛事快照')
          : `<p>将用当下的「${esc(mod.label)}」整份覆盖「${esc(compLabel(compById(compId)))}」的快照。旧快照会被替换，确定继续吗？</p>`,
        onConfirm: run,
      });
      return;
    }
    const del = event.target.closest('[data-sc-delete]');
    if (del) {
      const [compId, module] = del.dataset.scDelete.split('::');
      if (isExpired(compById(compId))) return;
      const mod = SNAPSHOT_MODULES.find((m) => m.key === module);
      confirmDialog({
        title: '删除快照',
        danger: true,
        body: `<p>确定删除「${esc(compLabel(compById(compId)))}」的${esc(mod.label)}快照吗？删除后该赛事这一项就回到「未打包」状态。</p>`,
        onConfirm: () => withBusy('正在删除快照…', async () => {
          await deleteSnapshot(module, compId, API_BASE);
          announce(`已删除${mod.label}快照。`);
        }),
      });
    }
  }

  function bind(node) {
    node.addEventListener('click', onClick);
  }
  function dispose() {
    if (root) root.removeEventListener('click', onClick);
    controller?.abort();
    controller = null;
    root = null;
    state.pending = null;
  }
  function mount(node) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    root.innerHTML = html();
    bind(root);
    controller = new AbortController();
    load();
  }

  return { html, render: html, mount, dispose, rerender: paint };
}

export default createSnapshotCenter;
