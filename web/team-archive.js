/* 战队档案：只展示教练手动录入的战队，卡片式一览。
   与「绑定 / 录入」区分开：录入页负责填字段，这里负责看清数据库里到底有多少战队、
   它们关联了哪些比赛，以及删除 / 改名会影响什么。

   为什么需要这一页：比赛卡片上的「1 vs A」是每场比赛自己存的文本，把 A 从战队名录里
   删掉并不会改写历史比赛，于是 A 还挂在标题上。这里把「比赛里出现、但档案里没有」
   的对手单独列出来，教练可以直接建档 / 并入已有战队 / 清空，从根上统一口径。

   保险：每次变更都会先把「战队名录 + 选手归属 + 被改动比赛的对手名」做成快照，
   写进本机历史（最多 20 条）。撤销按倒序回放快照，可以一直退回到任意一次变更前。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const norm = value => String(value ?? '').trim().toLowerCase();
const num = value => Number(value || 0).toLocaleString('zh-CN');
const HISTORY_KEY = 'kpl-team-archive-history-v1';
const MAX_HISTORY = 20;
const RESULT = {win: '胜', loss: '负', draw: '平', unknown: '待确认'};

const uid = prefix => `${prefix}-` + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
const fmtTime = ts => {
  try { return new Date(ts).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}); }
  catch { return '—'; }
};
const matchLabel = m => {
  const name = String(m.opponent || '').trim() || m.title || m.key || '未命名对局';
  const date = m.dateText || m.date || '日期未记录';
  return `${date} · ${name}`;
};

export async function renderTeamArchive(container, {api, workspace, isCurrent, toast, onChanged}) {
  let settings = {};
  let matches = [];
  let history = [];
  let expanded = new Set();
  let historyOpen = false;
  let notice = '';
  let busy = false;

  try { history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { history = []; }
  if (!Array.isArray(history)) history = [];
  const saveHistory = () => {
    history = history.slice(0, MAX_HISTORY);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history)); } catch { /* 隐私模式下只保留本次会话 */ }
  };

  const loadData = async () => {
    const [state, first] = await Promise.all([
      api('/api/state'),
      api('/api/studio/view/matches?source=db,bundle,sheet&includePartial=1&limit=500'),
    ]);
    if (isCurrent && !isCurrent()) return false;
    settings = state.settings || {};
    const list = [...(first.matches || [])];
    const total = Number(first.total) || list.length;
    // 影响面必须覆盖全部比赛，不能只看第一页。
    while (list.length < total && list.length < 5000) {
      const page = await api('/api/studio/view/matches?source=db,bundle,sheet&includePartial=1&limit=500&offset=' + list.length);
      if (isCurrent && !isCurrent()) return false;
      const part = page.matches || [];
      if (!part.length) break;
      list.push(...part);
    }
    matches = list;
    return true;
  };

  if (!await loadData()) return;

  // ---- 数据视图 ----
  const ownName = () => (settings.teamName || '本队').trim();
  const teams = () => (settings.teams || []).map(t => ({...t}));
  const roster = () => settings.roster || [];
  const teamKey = t => String(t.id || t.name || '');
  const usageMap = () => {
    const map = new Map();
    for (const m of matches) {
      const name = String(m.opponent || '').trim();
      if (!name) continue;
      const key = norm(name);
      if (!map.has(key)) map.set(key, {name, matches: []});
      map.get(key).matches.push(m);
    }
    return map;
  };
  const usageFor = (name, map = usageMap()) => map.get(norm(name))?.matches || [];
  const orphans = map => [...map.values()]
    .filter(entry => entry.name !== ownName() && !teams().some(t => norm(t.name) === norm(entry.name)))
    .sort((a, b) => b.matches.length - a.matches.length);

  const statOf = list => {
    const wins = list.filter(m => m.result === 'win').length;
    const losses = list.filter(m => m.result === 'loss').length;
    const dates = list.map(m => m.date || m.dateText || '').filter(Boolean).sort();
    return {games: list.length, wins, losses, last: dates[dates.length - 1] || ''};
  };
  const matchRows = (list, limit = 8) => `<div class="ta-match-list">
    ${list.slice(0, limit).map(m => `<a class="ta-match-row" href="#match/${encodeURIComponent(m.key || '')}">
      <span>${esc(m.dateText || m.date || '日期未记录')}</span>
      <b>${esc(String(m.opponent || '').trim() || m.title || '未命名对局')}</b>
      <small>${esc(RESULT[m.result] || '待确认')}</small><i>查看 →</i>
    </a>`).join('') || '<div class="ta-empty">没有关联比赛</div>'}
    ${list.length > limit ? `<div class="ta-match-more">还有 ${num(list.length - limit)} 场，去「比赛档案」按对手筛选查看</div>` : ''}
  </div>`;

  const cardHtml = (team, index, map) => {
    const list = usageFor(team.name, map);
    const stat = statOf(list);
    const members = roster().filter(p => norm(p.team || '') === norm(team.name)).length;
    const key = teamKey(team);
    const open = expanded.has('t:' + key);
    return `<article class="ta-team-card" data-team-key="${esc(key)}">
      <header class="ta-team-head">
        <span class="ta-index">${String(index + 1).padStart(2, '0')}</span>
        <div class="ta-team-title"><h3>${esc(team.name)}</h3>
          <span>${esc(team.short || '未填简称')}</span></div>
        <span class="ta-tag">手动录入</span>
      </header>
      <dl class="ta-team-meta">
        <div><dt>主教练</dt><dd>${esc(team.coach || '未填写')}</dd></div>
        <div><dt>名下选手</dt><dd>${num(members)} 人</dd></div>
        <div><dt>最近交手</dt><dd>${esc(stat.last || '—')}</dd></div>
      </dl>
      ${team.note ? `<p class="ta-team-note">${esc(team.note)}</p>` : ''}
      <div class="ta-team-stats">
        <div><b>${num(stat.games)}</b><span>关联比赛</span></div>
        <div><b>${num(stat.wins)}<small>胜</small> ${num(stat.losses)}<small>负</small></b><span>交手结果</span></div>
        <div><b class="${stat.games ? '' : 'is-dim'}">${stat.games ? '已关联' : '未使用'}</b><span>档案状态</span></div>
      </div>
      <footer class="ta-team-actions">
        <button class="ta-btn" type="button" data-ta="toggle-team" data-key="${esc(key)}">${open ? '收起比赛' : `关联比赛 (${stat.games})`}</button>
        <button class="ta-btn" type="button" data-ta="rename" data-key="${esc(key)}">统一名称</button>
        <button class="ta-btn danger" type="button" data-ta="delete" data-key="${esc(key)}">删除</button>
      </footer>
      ${open ? matchRows(list) : ''}
    </article>`;
  };

  const ownCardHtml = () => {
    const stat = statOf(matches);
    const members = roster().filter(p => !p.team || norm(p.team) === norm(ownName())).length;
    return `<article class="ta-team-card is-own">
      <header class="ta-team-head">
        <span class="ta-index">00</span>
        <div class="ta-team-title"><h3>${esc(ownName())}</h3><span>出现在所有比赛标题与报告抬头</span></div>
        <span class="ta-tag own">本队</span>
      </header>
      <dl class="ta-team-meta">
        <div><dt>主教练</dt><dd>${esc(settings.coach || '未填写')}</dd></div>
        <div><dt>赛季 / 阶段</dt><dd>${esc(settings.season || '未填写')}</dd></div>
        <div><dt>名录选手</dt><dd>${num(members)} 人</dd></div>
      </dl>
      <div class="ta-team-stats">
        <div><b>${num(matches.length)}</b><span>全部比赛</span></div>
        <div><b>${num(stat.wins)}<small>胜</small> ${num(stat.losses)}<small>负</small></b><span>赛果</span></div>
        <div><b>${num(teams().length)}</b><span>已录入对手</span></div>
      </div>
      <footer class="ta-team-actions"><a class="ta-btn" href="#profile">去录入修改 →</a></footer>
    </article>`;
  };

  const orphanHtml = (entry, map) => {
    const key = 'o:' + norm(entry.name);
    const open = expanded.has(key);
    const stat = statOf(entry.matches);
    const canMerge = teams().length > 0;
    return `<div class="ta-orphan-row">
      <div class="ta-orphan-main">
        <div><b>${esc(entry.name)}</b><span class="ta-warn-tag">未建档</span></div>
        <small>${num(stat.games)} 场比赛仍用这个对手名 · ${esc(stat.last ? '最近 ' + stat.last : '无日期')}</small>
      </div>
      <div class="ta-orphan-actions">
        <button class="ta-btn" type="button" data-ta="toggle-orphan" data-name="${esc(entry.name)}">${open ? '收起' : '看比赛'}</button>
        <button class="ta-btn primary" type="button" data-ta="register" data-name="${esc(entry.name)}">录入档案</button>
        ${canMerge ? `<button class="ta-btn" type="button" data-ta="merge" data-name="${esc(entry.name)}">并入已有</button>` : ''}
        <button class="ta-btn danger" type="button" data-ta="clear-orphan" data-name="${esc(entry.name)}">清空对手名</button>
      </div>
      ${open ? matchRows(entry.matches) : ''}
    </div>`;
  };

  const historyHtml = () => `<div class="ta-history-list">
    ${history.length ? history.map((entry, index) => `<div class="ta-history-row ${entry.undone ? 'is-undone' : ''}">
      <span class="ta-history-time">${esc(fmtTime(entry.at))}</span>
      <div class="ta-history-main"><b>${esc(entry.label)}</b><small>${esc(entry.summary || '')}</small></div>
      <span class="ta-history-state">${entry.status === 'failed' ? '部分失败' : entry.undone ? '已撤销' : '已生效'}</span>
      <button class="ta-btn" type="button" data-ta="restore" data-index="${index}">恢复到此</button>
    </div>`).join('') : '<div class="ta-empty">还没有变更。删除、建档、改名都会在这里留一条可恢复的快照。</div>'}
  </div>`;

  const template = () => {
    const map = usageMap();
    const list = teams();
    const orphanList = orphans(map);
    const registeredGames = list.reduce((sum, team) => sum + usageFor(team.name, map).length, 0);
    const canUndo = history.some(entry => !entry.undone);
    return `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">TEAM ARCHIVE · 战队档案</span>
        <h1>战队档案</h1>
        <p>这里只放教练手动录入的战队。比赛里出现过、但没建档的对手会单独列出，方便把队名统一到同一支战队。</p>
        <div class="page-facts">
          <span>已建档 <b>${num(list.length + 1)}</b> 支（含本队）</span>
          <span>关联比赛 ${num(registeredGames)} 场</span>
          <span class="${orphanList.length ? 'fact-warn' : ''}">未建档对手 ${num(orphanList.length)} 个</span>
          <span>全部比赛 ${num(matches.length)} 场</span>
          <span>历史快照 ${num(history.length)} 条</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#profile">去录入 →</a>
        <a class="button" href="#matches">比赛档案</a>
      </div>
    </div>

    ${notice ? `<div class="ta-notice"><span>${esc(notice)}</span>${canUndo ? '<button class="ta-btn primary" type="button" data-ta="undo">撤销上一步</button>' : ''}</div>` : ''}

    ${orphanList.length ? `<section class="ta-alert">
      <div><b>有 ${num(orphanList.length)} 个对手名只存在于比赛里</b>
      <p>例如比赛卡片上的「1 vs A」：A 被移出名录后，历史比赛的对手名不会自动消失。下面可以直接建档、并入已有战队，或清空这些比赛的对手名。</p></div>
      <a class="button" href="#ta-orphans">去统一 →</a>
    </section>` : `<section class="ta-alert is-clean"><div><b>对手口径已统一</b><p>比赛里出现的对手名都在战队档案里，没有孤立队名。</p></div></section>`}

    <section class="ta-section">
      <div class="ta-section-head"><div><h2>已录入战队</h2><p>共 ${num(list.length + 1)} 支 · 卡片里的比赛数来自全部已导入记录（含验证数据）</p></div>
        <button class="button" type="button" data-ta="undo-top"${canUndo ? '' : ' disabled'}>撤销上一步</button></div>
      <div class="ta-grid">${ownCardHtml()}${list.map((t, i) => cardHtml(t, i, map)).join('')}</div>
      ${list.length ? '' : '<p class="ta-section-hint">目前只有本队。可以在「录入」里添加对手战队，比赛卡片里出现过的对手也能在下方一键建档。</p>'}
    </section>

    <section class="ta-section" id="ta-orphans">
      <div class="ta-section-head"><div><h2>未建档对手</h2><p>出现在比赛对手字段、但战队档案里没有的名字；处理后卡片标题和筛选口径才会一致</p></div></div>
      <div class="ta-orphans">${orphanList.length
        ? orphanList.map(entry => orphanHtml(entry, map)).join('')
        : '<div class="ta-empty">没有孤立队名。所有比赛的对手都能在档案里找到。</div>'}</div>
    </section>

    <section class="ta-section">
      <div class="ta-section-head"><div><h2>变更历史</h2><p>每次变更前会保存完整快照：战队名录、选手归属，以及被改动比赛的对手名</p></div>
        <button class="button" type="button" data-ta="toggle-history">${historyOpen ? '收起' : '展开'}历史 (${history.length})</button></div>
      ${historyOpen ? historyHtml() : ''}
      <p class="ta-history-note">快照保存在本机浏览器，最多 ${MAX_HISTORY} 条；刷新页面、重开工作台都还在。「恢复到此」会按顺序回放之后的变更，把档案退回到那一步之前。</p>
    </section>`;
  };

  const paint = () => { container.innerHTML = template(); };
  const refresh = async () => {
    const ok = await loadData();
    if (!ok) return;
    await onChanged?.();
    paint();
  };
  paint();

  // ---- 写接口 ----
  const putSettings = async payload => {
    const response = await fetch('/api/settings', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.detail || '战队名录保存失败');
  };
  const patchMatches = async entries => {
    const groups = new Map();
    for (const item of entries) {
      const value = String(item.opponent ?? '');
      if (!groups.has(value)) groups.set(value, []);
      groups.get(value).push(item.key);
    }
    for (const [opponent, keys] of groups) {
      for (let i = 0; i < keys.length; i += 200) {
        const response = await fetch('/api/studio/match-meta', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({keys: keys.slice(i, i + 200), patch: {opponent}}),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(result.detail || '比赛对手名写入失败');
        if (!result.ok) throw Error(result.failed?.[0]?.detail || '部分比赛的对手名写入失败');
      }
    }
  };
  const snapshot = keys => ({
    teams: teams().map(t => ({...t})),
    rosterTeam: Object.fromEntries(roster().map(p => [p.id, p.team || ownName()])),
    matchOpponents: keys.map(key => ({key, opponent: String(matches.find(m => m.key === key)?.opponent || '').trim()})),
  });
  const applySnapshot = async entry => {
    const current = await api('/api/state');
    const s = current.settings || {};
    const before = entry.before || {};
    const teamMap = before.rosterTeam || {};
    await putSettings({
      ...s,
      teams: (before.teams || []).map(t => ({...t})),
      roster: (s.roster || []).map(p => ({...p, team: teamMap[p.id] ?? p.team ?? s.teamName})),
    });
    await patchMatches(before.matchOpponents || []);
  };
  const mutate = async ({label, kind, summary, teams: nextTeams, roster: nextRoster, matchOpponents = [], keys = []}) => {
    const before = snapshot(keys);
    const entry = {id: uid('h'), at: Date.now(), label, kind, summary, before, undone: false, status: 'ok'};
    history.unshift(entry);
    saveHistory();
    let error = null;
    try {
      await putSettings({...settings, teams: nextTeams, roster: nextRoster});
      if (matchOpponents.length) await patchMatches(matchOpponents);
    } catch (e) { error = e; entry.status = 'failed'; saveHistory(); }
    if (error) { toast?.(error.message, true); entry.summary = `${summary} · 写入失败：${error.message}`; saveHistory(); }
    expanded = new Set();
    await refresh();
    return !error;
  };
  const restoreUpTo = async index => {
    busy = true;
    try {
      for (let i = 0; i <= index && i < history.length; i++) await applySnapshot(history[i]);
      for (let i = 0; i <= index && i < history.length; i++) history[i].undone = true;
      saveHistory();
      notice = `已恢复到「${history[Math.min(index, history.length - 1)]?.label || '该版本'}」之前的状态`;
      historyOpen = true;
      await refresh();
      toast?.('已恢复，战队名录、选手归属与比赛对手名都回到了变更前');
    } catch (error) { toast?.(error.message, true); }
    finally { busy = false; }
  };
  const undo = async () => {
    const index = history.findIndex(entry => !entry.undone);
    if (index < 0) return toast?.('没有可撤销的变更', true);
    await restoreUpTo(index);
  };

  // ---- 弹窗 ----
  const openDialog = (titleText, html, mount) => {
    const dialog = document.querySelector('#detail-dialog');
    const title = document.querySelector('#detail-title');
    const body = document.querySelector('#detail-body');
    if (!dialog || !body) return;
    if (dialog.open) dialog.close();
    if (title) title.textContent = titleText;
    body.innerHTML = html;
    dialog.showModal();
    const close = () => dialog.close();
    mount?.(body, close);
  };
  const dialogActions = (confirmLabel = '确认') => `<div class="ta-dialog-actions">
    <button class="button" type="button" data-close>取消</button>
    <button class="button primary" type="button" data-confirm>${esc(confirmLabel)}</button>
  </div>`;
  const bindDialog = (body, close, onConfirm) => {
    body.querySelector('[data-close]')?.addEventListener('click', close);
    const confirm = body.querySelector('[data-confirm]');
    confirm?.addEventListener('click', async () => {
      if (busy) return;
      busy = true; confirm.disabled = true;
      try { await onConfirm(body, close); }
      finally { busy = false; confirm.disabled = false; }
    });
  };
  const impactHtml = (list, lead = '') => `${lead ? `<p class="ta-dialog-lead">${lead}</p>` : ''}
    <div class="ta-impact">${list.slice(0, 8).map(m => `<div class="ta-impact-row">
      <span>${esc(m.dateText || m.date || '日期未记录')}</span>
      <b>${esc(String(m.opponent || '').trim() || m.title || '未命名对局')}</b>
      <small>${esc(RESULT[m.result] || '待确认')}</small></div>`).join('') || '<div class="ta-empty">没有关联比赛</div>'}
      ${list.length > 8 ? `<div class="ta-match-more">还有 ${num(list.length - 8)} 场比赛会受影响</div>` : ''}
    </div>`;

  const openDelete = team => {
    const list = usageFor(team.name);
    const members = roster().filter(p => norm(p.team || '') === norm(team.name));
    openDialog('删除战队', `<div class="ta-dialog">
      <p class="ta-dialog-lead">删除「<b>${esc(team.name)}</b>」会影响 <b>${num(list.length)} 场比赛</b>。这些比赛的对手信息会失去档案关联：</p>
      ${impactHtml(list, '')}
      ${members.length ? `<p class="ta-dialog-note">另有 <b>${num(members.length)} 名选手</b>挂在这支战队下，删除后会回到本队。</p>` : ''}
      <div class="ta-choice">
        <label><input type="radio" name="ta-delete-mode" value="clear" checked><span>
          <b>同时清空这些比赛的对手名（推荐）</b>
          <small>比赛标题不再出现「${esc(team.name)}」，之后可在「比赛档案 / 补全档案」重新指定</small></span></label>
        <label><input type="radio" name="ta-delete-mode" value="keep"><span>
          <b>只从档案移除，比赛对手名保留</b>
          <small>这些名字会进入下方「未建档对手」，不会被改动</small></span></label>
      </div>
      <p class="ta-dialog-note">变更会写入历史快照，随时可以撤销。</p>
      ${dialogActions('确认删除')}
    </div>`, (body, close) => bindDialog(body, close, async (root, done) => {
      const mode = root.querySelector('input[name="ta-delete-mode"]:checked')?.value || 'clear';
      const changed = mode === 'clear' ? list.map(m => ({key: m.key, opponent: ''})) : [];
      const ok = await mutate({
        label: `删除「${team.name}」`, kind: 'delete',
        summary: `${num(list.length)} 场比赛受影响${mode === 'clear' ? ' · 对手名已清空' : ' · 对手名保留'}`,
        teams: teams().filter(t => teamKey(t) !== teamKey(team)),
        roster: roster().map(p => norm(p.team || '') === norm(team.name) ? {...p, team: ownName()} : {...p}),
        matchOpponents: changed,
        keys: changed.map(item => item.key),
      });
      if (ok) {
        notice = `已删除「${team.name}」 · ${mode === 'clear' ? `${num(list.length)} 场比赛对手名已清空` : '比赛对手名保留'} · 可撤销`;
        historyOpen = true;
        paint();
      }
      done();
    }));
  };

  const openRename = team => {
    const list = usageFor(team.name);
    openDialog('统一战队名称', `<div class="ta-dialog">
      <p class="ta-dialog-lead">把「<b>${esc(team.name)}</b>」改成统一的队名；已有比赛的对手名可以一起改。</p>
      <label class="ta-field"><span>新的战队名称</span><input id="ta-new-name" maxlength="50" value="${esc(team.name)}"></label>
      <label class="ta-check"><input type="checkbox" id="ta-sync-matches" checked><span>同步更新 ${num(list.length)} 场比赛的对手名</span></label>
      ${list.length ? impactHtml(list, `以下 ${num(list.length)} 场比赛会改写成新队名：`) : ''}
      <p class="ta-dialog-note">新队名不能与已有的战队或本队重名；变更可撤销。</p>
      ${dialogActions('确认改名')}
    </div>`, (body, close) => bindDialog(body, close, async (root, done) => {
      const name = String(root.querySelector('#ta-new-name')?.value || '').trim();
      if (!name) { toast?.('请填写战队名称', true); return; }
      if (norm(name) === norm(ownName()) || teams().some(t => teamKey(t) !== teamKey(team) && norm(t.name) === norm(name))) {
        toast?.('已有同名战队，请改用「并入已有」或换一个名字', true); return;
      }
      const sync = root.querySelector('#ta-sync-matches')?.checked;
      const changed = sync ? list.map(m => ({key: m.key, opponent: name})) : [];
      const ok = await mutate({
        label: `「${team.name}」改名为「${name}」`, kind: 'rename',
        summary: `${num(changed.length)} 场比赛对手名同步更新`,
        teams: teams().map(t => teamKey(t) === teamKey(team) ? {...t, name} : {...t}),
        roster: roster().map(p => norm(p.team || '') === norm(team.name) ? {...p, team: name} : {...p}),
        matchOpponents: changed,
        keys: changed.map(item => item.key),
      });
      if (ok) { notice = `已统一为「${name}」 · ${num(changed.length)} 场比赛同步更新 · 可撤销`; historyOpen = true; paint(); }
      done();
    }));
  };

  const openRegister = name => {
    const list = usageFor(name);
    openDialog('录入战队档案', `<div class="ta-dialog">
      <p class="ta-dialog-lead">把「<b>${esc(name)}</b>」正式录入战队档案？</p>
      <p class="ta-dialog-note">这 ${num(list.length)} 场比赛会自动关联到它，比赛对手名保持不变。想改简称、教练、备注，可以去「录入」页补。</p>
      ${impactHtml(list, `将关联的 ${num(list.length)} 场比赛：`)}
      ${dialogActions('录入档案')}
    </div>`, (body, close) => bindDialog(body, close, async (root, done) => {
      const ok = await mutate({
        label: `录入「${name}」`, kind: 'register', summary: `关联 ${num(list.length)} 场比赛`,
        teams: [...teams(), {id: uid('team'), name, short: '', coach: '', note: ''}],
        roster: roster().map(p => ({...p})), keys: [],
      });
      if (ok) { notice = `已录入「${name}」 · ${num(list.length)} 场比赛自动关联 · 可撤销`; historyOpen = true; paint(); }
      done();
    }));
  };

  const openMerge = name => {
    const list = usageFor(name);
    const options = teams().filter(t => norm(t.name) !== norm(name));
    if (!options.length) { toast?.('还没有可并入的战队，请先建档', true); return; }
    openDialog('并入已有战队', `<div class="ta-dialog">
      <p class="ta-dialog-lead">把「<b>${esc(name)}</b>」的 ${num(list.length)} 场比赛归到哪支战队？</p>
      <label class="ta-field"><span>目标战队</span><select id="ta-merge-target">
        ${options.map(t => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join('')}
      </select></label>
      <p class="ta-dialog-note">只改比赛对手名，档案里的战队数量不变。用于把「A」「A 队」这类写法统一起来；变更可撤销。</p>
      ${impactHtml(list, `以下 ${num(list.length)} 场比赛会被改写：`)}
      ${dialogActions('确认并入')}
    </div>`, (body, close) => bindDialog(body, close, async (root, done) => {
      const target = String(root.querySelector('#ta-merge-target')?.value || '').trim();
      if (!target) { toast?.('请选择目标战队', true); return; }
      const changed = list.map(m => ({key: m.key, opponent: target}));
      const ok = await mutate({
        label: `「${name}」并入「${target}」`, kind: 'merge', summary: `${num(list.length)} 场比赛对手名改写`,
        teams: teams().map(t => ({...t})), roster: roster().map(p => ({...p})),
        matchOpponents: changed, keys: changed.map(item => item.key),
      });
      if (ok) { notice = `已把「${name}」的 ${num(list.length)} 场比赛并入「${target}」 · 可撤销`; historyOpen = true; paint(); }
      done();
    }));
  };

  const openClear = name => {
    const list = usageFor(name);
    openDialog('清空比赛对手名', `<div class="ta-dialog">
      <p class="ta-dialog-lead">清空「<b>${esc(name)}</b>」在 ${num(list.length)} 场比赛里的对手名？</p>
      <p class="ta-dialog-note">这些比赛的标题将不再显示该队名，档案完整度里的「对手」一项会记为缺失；可在「比赛档案 / 补全档案」重新填写。变更可撤销。</p>
      ${impactHtml(list, `将失去对手信息的 ${num(list.length)} 场比赛：`)}
      ${dialogActions('确认清空')}
    </div>`, (body, close) => bindDialog(body, close, async (root, done) => {
      const changed = list.map(m => ({key: m.key, opponent: ''}));
      const ok = await mutate({
        label: `清空「${name}」的对手名`, kind: 'clear', summary: `${num(list.length)} 场比赛对手名清空`,
        teams: teams().map(t => ({...t})), roster: roster().map(p => ({...p})),
        matchOpponents: changed, keys: changed.map(item => item.key),
      });
      if (ok) { notice = `已清空「${name}」在 ${num(list.length)} 场比赛里的对手名 · 可撤销`; historyOpen = true; paint(); }
      done();
    }));
  };

  // ---- 点击分发 ----
  container.addEventListener('click', async event => {
    const button = event.target.closest('[data-ta]');
    if (!button || button.disabled || busy) return;
    const action = button.dataset.ta;
    const key = button.dataset.key || '';
    const name = button.dataset.name || '';

    if (action === 'undo' || action === 'undo-top') { await undo(); return; }
    if (action === 'toggle-history') { historyOpen = !historyOpen; paint(); return; }
    if (action === 'restore') {
      const index = Number(button.dataset.index);
      if (!Number.isInteger(index) || !history[index]) return;
      if (!confirm(`恢复到第 ${index + 1} 条变更之前？这之后的 ${index} 条变更会一起回退。`)) return;
      await restoreUpTo(index);
      return;
    }
    if (action === 'toggle-team') {
      const id = 't:' + key;
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      paint(); return;
    }
    if (action === 'toggle-orphan') {
      const id = 'o:' + norm(name);
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      paint(); return;
    }
    if (action === 'delete') {
      const team = teams().find(t => teamKey(t) === key);
      if (team) openDelete(team);
      return;
    }
    if (action === 'rename') {
      const team = teams().find(t => teamKey(t) === key);
      if (team) openRename(team);
      return;
    }
    if (action === 'register') { if (name) openRegister(name); return; }
    if (action === 'merge') { if (name) openMerge(name); return; }
    if (action === 'clear-orphan') { if (name) openClear(name); }
  });
}
