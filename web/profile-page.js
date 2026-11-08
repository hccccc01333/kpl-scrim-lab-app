/* 录入：本队 + 对手战队名录 + 选手身份（职业 ID / 真名）。
   卡片式浏览、删除影响预览与撤销历史在「战队档案」页（#teams），这里只负责填字段。
   身份标签规则：跨战队显示「战队.选手名」（如 重庆狼队.小胖），本队只显示选手名。
   同一名选手的大小号通过「昵称 → 选手身份」认领归并，不再用一个游戏昵称当身份。

   交互约定（2026-11-06）：
   - 「我的战队」保存一次后进入只读态，出现「修改」，保存按钮灰置。
   - 「首发五人」用同一套选手头像池拖到分路，落下即自动保存；点击也能自动入位。
   - 「战队名录」支持本次会话内的撤销与历史恢复。
   - 「选手身份」合并了原「认领游戏昵称」：一张卡、一个头像池、一个保存入口。
     选中的身份既是编辑对象，也是下方待认领昵称的认领目标。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const LANE_HINT = {对抗路: '开团 / 边线压制', 打野: '节奏 / 资源', 中路: '支援 / 消耗', 发育路: '输出核心', 游走: '视野 / 保人'};
const HISTORY_KEY = 'pf-teams-history';

function uid(prefix = 'p') {
  return `${prefix}-` + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
}
const cloneTeams = list => list.map(t => ({...t}));

export async function renderProfile(container, {api, workspace, isCurrent, toast, onSaved}) {
  const [state, identity] = await Promise.all([
    api('/api/state'),
    api('/api/studio/identity').catch(() => ({unbound: [], aliases: {}})),
  ]);
  if (isCurrent && !isCurrent()) return;

  const settings = state.settings || {};
  const teamName = (settings.teamName || '我的训练队').trim();
  const roster = (settings.roster || []).map(p => ({...p, tags: Array.isArray(p.tags) ? [...p.tags] : []}));
  const teams = (settings.teams || []).map(t => ({...t}));
  const aliases = {...(settings.aliases || {})};
  const unbound = identity.unbound || [];
  const matchMeta = {...(identity.matchMeta || {})};
  const overview = workspace?.overview || {};

  // 开赛时间只在部分数据源里有；有值才推断时段，没有就明确标「未记录」，不臆造上午/下午。
  const clockOf = value => {
    const raw = String(value || '');
    const match = raw.match(/(?:^|[ T])(\d{1,2}):(\d{2})/);
    if (!match) return null;
    const hour = Number(match[1]);
    if (!Number.isFinite(hour) || hour < 0 || hour > 23) return null;
    return {hour, text: `${String(hour).padStart(2, '0')}:${match[2]}`};
  };
  const periodOf = value => {
    const clock = clockOf(value);
    if (!clock) return '';
    return clock.hour < 12 ? '上午' : clock.hour < 18 ? '下午' : '晚间';
  };
  const durationOf = seconds => {
    const value = Number(seconds);
    return Number.isFinite(value) && value > 0 ? `${Math.round(value / 60)} 分钟` : '';
  };

  const active = () => roster;
  const aliasesFor = id => Object.keys(aliases).filter(label => aliases[label] === id);
  const teamOptions = () => [teamName, ...teams.map(t => t.name)].filter(Boolean);
  const identityOf = (member) => {
    const team = (member.team || '').trim();
    const name = (member.name || '').trim();
    return team && team !== teamName && name ? `${team}.${name}` : name;
  };

  const laneOf = player => player.position || '';
  const starterMap = () => {
    const map = new Map();
    for (const lane of LANES) {
      const found = active().find(p => laneOf(p) === lane && p.id);
      if (found) map.set(lane, found.id);
    }
    return map;
  };
  const pending = unbound.filter(item => !aliases[item.label]).slice(0, 60);

  const progressOf = () => {
    let score = 0;
    const items = [];
    const hasTeam = teamName !== '我的训练队';
    items.push({label: '战队名称', ok: hasTeam}); score += hasTeam ? 1 : 0;
    const hasCoach = !!overview.coach;
    items.push({label: '主教练', ok: hasCoach}); score += hasCoach ? 1 : 0;
    const filled = starterMap().size;
    items.push({label: `首发五人（${filled}/5）`, ok: filled === 5}); score += filled === 5 ? 1 : 0;
    const named = active().filter(m => aliasesFor(m.id).length).length;
    items.push({label: `选手已认领（${named}）`, ok: named > 0}); score += named > 0 ? 1 : 0;
    return {score: Math.round(score / 4 * 100), items};
  };
  const progressHtml = () => {
    const p = progressOf();
    return `<section class="pf-progress ${p.score >= 75 ? 'good' : p.score >= 40 ? 'mid' : 'bad'}">
      <div class="pf-progress-head">
        <b>${p.score}<small>%</small></b>
        <div>
          <strong>建档进度</strong>
          <div class="pf-progress-items">${p.items.map(i => `<span class="${i.ok ? 'ok' : ''}">${i.ok ? '✓' : '○'} ${esc(i.label)}</span>`).join('')}</div>
        </div>
      </div>
      <p>${p.score === 100
        ? '建档完成。之后导入比赛都会自动套用这套身份。'
        : '没填的部分不阻塞导入，但相关分析会缺一块：例如选手没认领昵称，同一个人会被拆成好几个。'}</p>
    </section>`;
  };

  // ---- 交互状态（重绘前统一 sync，避免丢失未保存的输入） ----
  const profileDraft = {
    team: teamName,
    coach: overview.coach || '',
    season: overview.season || '',
    org: workspace?.profile?.organization || '',
  };
  const hasProfile = teamName !== '我的训练队' || !!profileDraft.coach || !!profileDraft.season || !!profileDraft.org;
  let teamEditMode = !hasProfile;
  let selectedId = roster.find(p => (p.name || '').trim() && p.name !== '新选手')?.id || roster[0]?.id || '';
  let historyOpen = false;
  let openGroups = new Set();
  let groupsInitialized = false;
  let laneStatus = '拖动选手到分路，自动保存';
  let laneSaving = false;
  let teamsHistory = (() => {
    try { return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; }
  })();
  let lastTeamsSnapshot = cloneTeams(teams);

  const isFilled = p => {
    const name = (p.name || '').trim();
    return !!name && name !== '新选手';
  };
  const initials = (p, size = '') => {
    if (!isFilled(p)) return '＋';
    const name = (p.name || '').trim();
    return size === 'xs' ? name.slice(0, 1) : name.slice(0, 2);
  };
  const avatarHtml = (p, opts = {}) => {
    const {size = '', action = '', label = '', active = false, title = '', asStatic = false} = opts;
    const cls = ['pf-avatar', size, isFilled(p) ? 'is-filled' : 'is-empty', active ? 'is-active' : '', asStatic ? 'is-static' : ''].filter(Boolean).join(' ');
    const text = isFilled(p) ? identityOf(p) || p.name : '待填身份';
    // 静态头像用于按钮内部的展示，避免 <button> 嵌套 <button>。
    if (asStatic) {
      return `<span class="${cls}" data-avatar-id="${esc(p.id)}" title="${esc(title || text)}"><span>${esc(initials(p, size))}</span></span>`;
    }
    const attrs = [
      'type="button"', `class="${cls}"`, `data-avatar-id="${esc(p.id)}"`,
      action ? `data-avatar-action="${esc(action)}"` : '',
      label ? `data-avatar-label="${esc(label)}"` : '',
      `title="${esc(title || text)}"`, `aria-label="${esc(title || text)}"`,
    ].filter(Boolean).join(' ');
    return `<button ${attrs}><span>${esc(initials(p, size))}</span></button>`;
  };

  const memberRowHtml = p => `<div class="pf-member" data-id="${esc(p.id)}">
    <div class="pf-member-main">
      <input class="pf-member-name" maxlength="50" value="${esc(p.name)}" aria-label="选手名" placeholder="职业 ID / 真名">
      <span class="pf-member-preview">${esc((p.team || teamName) !== teamName ? identityOf(p) : '')}</span>
    </div>
    <select class="pf-member-team" aria-label="所属战队">
      ${teamOptions().map(t => `<option value="${esc(t)}"${(p.team || teamName) === t ? ' selected' : ''}>${esc(t)}</option>`).join('')}
    </select>
    <select class="pf-member-lane" aria-label="默认分路">
      <option value=""${!p.position ? ' selected' : ''}>未设分路</option>
      ${LANES.map(l => `<option value="${l}"${p.position === l ? ' selected' : ''}>${l}</option>`).join('')}
    </select>
    <input class="pf-member-tags" maxlength="60" value="${esc((p.tags || []).join('，'))}" aria-label="标签" placeholder="标签：首发，小号">
    <input class="pf-member-camp" maxlength="15" inputmode="numeric" value="${esc(p.campUserId || '')}" aria-label="营地 ID" placeholder="营地 ID（选填）">
    <button class="pf-member-remove" type="button" data-remove="${esc(p.id)}" title="移出名单">移出</button>
  </div>`;

  const starterHtml = () => {
    const pool = roster.filter(p => !LANES.includes(laneOf(p)));
    return `<div class="pf-starter-layout">
      <div class="pf-lanes">
        ${LANES.map(lane => {
          const p = roster.find(x => laneOf(x) === lane);
          return `<div class="pf-lane-slot ${p ? 'is-filled' : ''}" data-lane="${lane}">
            <div class="pf-lane-label"><b>${lane}</b><small>${LANE_HINT[lane]}</small></div>
            ${p ? `<div class="pf-slot-player" data-player-id="${esc(p.id)}" draggable="true">${avatarHtml(p, {size: 'sm', action: 'lane-slot'})}<span class="pf-slot-name">${esc(identityOf(p) || '未命名')}</span><button class="pf-slot-clear" type="button" data-clear-lane="${lane}" title="移回选手池">×</button></div>`
              : '<span class="pf-slot-empty">拖选手到这里</span>'}
          </div>`;
        }).join('')}
      </div>
      <div class="pf-pool" data-drop="pool">
        <div class="pf-pool-head"><b>选手池</b><small>${pool.length} 人 · 拖到左侧，或点一下自动入位</small></div>
        <div class="pf-pool-chips">
          ${pool.length ? pool.map(p => `<div class="pf-pool-chip" data-player-id="${esc(p.id)}" draggable="true">${avatarHtml(p, {size: 'md', action: 'lane-pool'})}<span>${esc(identityOf(p) || '未命名')}</span></div>`).join('')
            : '<span class="pf-pool-empty">都已分好位置</span>'}
        </div>
      </div>
    </div>
    <div class="pf-autosave ${laneStatus.includes('失败') ? 'is-error' : ''}">${esc(laneStatus)}</div>`;
  };

  // 待认领昵称：目标身份就是上方选中的那个人，每项不再重复一整排头像。
  const bindListHtml = (items = pending) => {
    if (!items.length) return '<div class="pf-empty">没有待认领的昵称。导入新比赛后会出现在这里。</div>';
    const current = roster.find(p => p.id === selectedId);
    const currentName = current ? (identityOf(current) || current.name || '未命名') : '';
    return `<div class="pf-bind-list">
      ${items.map(item => {
        const owner = roster.find(p => p.id === aliases[item.label]);
        const detail = `${item.matches ? `${item.matches} 场` : ''}${item.heroes?.length ? ` · 常用 ${item.heroes.slice(0, 3).map(esc).join('、')}` : ''}${item.lastDate ? ` · 最近 ${esc(item.lastDate)}` : ''}`;
        return `<div class="pf-bind ${owner ? 'is-bound' : ''}" data-label="${esc(item.label)}">
          <div class="pf-bind-name"><strong>${esc(item.label)}</strong><small>${detail}</small></div>
          <div class="pf-bind-target">
            ${owner
              ? `<button class="pf-bind-owner" type="button" data-edit-owner="${esc(owner.id)}" title="查看并编辑这名选手">${avatarHtml(owner, {size: 'xs', asStatic: true})}<b>${esc(identityOf(owner) || owner.name)}</b></button>
                 ${owner.id !== selectedId ? `<button class="pf-bind-move" type="button" data-claim-label="${esc(item.label)}" title="改认领给当前选中的身份">改给当前身份</button>` : ''}
                 <button class="pf-bind-cancel" type="button" data-unbind="${esc(item.label)}" title="取消认领，回到待认领">取消</button>`
              : `<button class="pf-bind-claim" type="button" data-claim-label="${esc(item.label)}"${current ? '' : ' disabled'} title="认领给当前选中的身份">${current ? avatarHtml(current, {size: 'xs', asStatic: true}) : ''}<span>认领给 ${esc(currentName || '当前身份')}</span></button>
                 <button class="pf-bind-new" type="button" data-bind-new="${esc(item.label)}" title="为这个昵称新建身份">＋ 新建</button>`}
          </div>
        </div>`;
      }).join('')}
    </div>`;
  };

  // 按「对局场次」归类待认领昵称：教练只打开当天要处理的那一场，不必在整包选手里翻。
  // 同一昵称出现在多场时会分别列在对应场次下；认领是全局的，任一处认领后所有场次同步。
  const claimGroups = () => {
    const sessions = new Map();
    const loose = [];
    pending.forEach(item => {
      const keys = (item.matchKeys || []).filter(key => matchMeta[key]);
      if (!keys.length) { loose.push(item); return; }
      keys.forEach(key => {
        if (!sessions.has(key)) sessions.set(key, []);
        sessions.get(key).push(item);
      });
    });
    const groups = [...sessions.entries()].map(([key, items]) => {
      const meta = matchMeta[key];
      const clock = clockOf(meta.startTime);
      return {
        key,
        date: (meta.date || '').slice(0, 10) || '日期未记录',
        period: periodOf(meta.startTime),
        time: clock?.text || '',
        title: meta.title || meta.opponent || meta.session || '',
        duration: durationOf(meta.duration),
        items,
        bound: items.filter(item => aliases[item.label]).length,
      };
    });
    groups.sort((a, b) => b.date.localeCompare(a.date)
      || (a.time || '99:99').localeCompare(b.time || '99:99')
      || a.key.localeCompare(b.key));
    if (loose.length) groups.push({
      key: '__loose__', date: '未关联对局', period: '', time: '', title: '没有场次信息的昵称',
      duration: '', items: loose, bound: loose.filter(item => aliases[item.label]).length,
    });
    return groups;
  };

  const bindGroupsHtml = () => {
    const groups = claimGroups();
    if (!groups.length) return '<div class="pf-empty">没有待认领的昵称。导入新比赛后会出现在这里。</div>';
    if (!groupsInitialized) { openGroups.add(groups[0].key); groupsInitialized = true; }
    const allOpen = groups.every(group => openGroups.has(group.key));
    let lastDate = '';
    let index = 0;
    const rows = groups.map(group => {
      let dateHead = '';
      if (group.date !== lastDate) {
        lastDate = group.date;
        index = 0;
        const sameDate = groups.filter(item => item.date === group.date);
        const periodOrder = ['上午', '下午', '晚间'];
        const periods = [...new Set(sameDate.map(item => item.period).filter(Boolean))]
          .sort((a, b) => periodOrder.indexOf(a) - periodOrder.indexOf(b));
        dateHead = `<div class="pf-date-head"><b>${esc(group.date)}</b><small>${sameDate.length} 场 · ${periods.length ? periods.map(esc).join(' / ') : '开赛时间未记录'}</small></div>`;
      }
      index += 1;
      const open = openGroups.has(group.key);
      return `${dateHead}<div class="pf-group ${open ? 'is-open' : ''}">
        <button class="pf-group-head" type="button" data-toggle-group="${esc(group.key)}" aria-expanded="${open}">
          <span class="pf-group-chevron">${open ? '▾' : '▸'}</span>
          <span class="pf-group-title">
            <b>第 ${index} 场</b>
            ${group.period ? `<em class="pf-period">${esc(group.period)}${group.time ? ` ${esc(group.time)}` : ''}</em>` : ''}
            <span>${esc(group.title || '未命名对局')}</span>
          </span>
          <span class="pf-group-meta">${group.duration ? `${esc(group.duration)} · ` : ''}${group.items.length} 人 · 已认领 ${group.bound}</span>
        </button>
        ${open ? `<div class="pf-group-body">${bindListHtml(group.items)}</div>` : ''}
      </div>`;
    }).join('');
    return `<div class="pf-claim-groups">
      <div class="pf-groups-bar">
        <span>${groups.length} 场对局 · 按场次展开，认领一次全场同步</span>
        <button class="button ghost" type="button" id="pf-toggle-all" data-toggle-all="${allOpen ? 'collapse' : 'expand'}">${allOpen ? '全部收起' : '全部展开'}</button>
      </div>
      ${rows}
    </div>`;
  };

  const historyHtml = () => `<div class="pf-history">
    ${teamsHistory.length ? teamsHistory.map((entry, index) => `<div class="pf-history-row">
      <span>${new Date(entry.at).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', second: '2-digit'})}</span>
      <b>${esc(entry.label)}</b><small>${entry.teams?.length ?? 0} 支战队</small>
      <button class="button ghost" type="button" data-restore="${index}">恢复</button>
    </div>`).join('') : '<div class="pf-empty">还没有变更记录。添加、编辑或删除战队后会留痕。</div>'}
    <p class="pf-history-note">只记录本次会话内的编辑前后快照；恢复后仍需点「保存战队名录」写入。</p>
  </div>`;

  // 一张卡闭环：上面定义身份（点头像写一个人），下面把游戏昵称认领给选中的身份。
  const identityHtml = () => {
    const selected = roster.find(p => p.id === selectedId);
    const filledCount = roster.filter(isFilled).length;
    const boundCount = Object.keys(aliases).length;
    const claimed = selected ? aliasesFor(selected.id) : [];
    return `<section class="pf-card pf-identity-card">
      <header>
        <div>
          <h2>选手身份</h2>
          <p>点头像写一个人的职业 ID 或真名，再点下面的游戏昵称认领给 TA；大小号因此合并成同一个人</p>
        </div>
        <div class="pf-header-actions">
          <span class="pf-count">${roster.length} 个身份 · ${pending.length} 个待认领</span>
          <button class="button" type="button" id="pf-add">＋ 添加选手</button>
        </div>
      </header>

      <div class="pf-identity-define">
        <div class="pf-roster-pool">
          ${roster.map(p => avatarHtml(p, {size: 'lg', action: 'select-player', active: p.id === selectedId})).join('')}
          <button class="pf-avatar is-add" type="button" id="pf-avatar-add" title="添加选手">＋</button>
        </div>
        ${selected ? `<div class="pf-identity-editor">
          <div class="pf-identity-current">
            <span class="pf-current-label">当前身份</span>
            <b>${esc(identityOf(selected) || selected.name || '未命名')}</b>
            <span class="pf-claimed-chips">${claimed.length
              ? claimed.map(label => `<span class="pf-claimed-chip">${esc(label)}<button type="button" data-unbind="${esc(label)}" title="取消认领">×</button></span>`).join('')
              : '<em>还没认领昵称</em>'}</span>
          </div>
          ${memberRowHtml(selected)}
        </div>` : '<div class="pf-empty">点上面的头像，填写这名选手的身份信息。</div>'}
        <p class="pf-roster-hint">已填 <b>${filledCount}/${roster.length}</b> · 彩色边框＝已填身份，灰色＝待补</p>
      </div>

      <div class="pf-identity-claim">
        <div class="pf-subhead">
          <div>
            <b>待认领的游戏昵称</b>
            <small>先点开要看的那一场，再点「认领给…」归到上面选中的身份；已认领的点名字可跳去编辑那个人</small>
          </div>
          <div class="pf-subhead-actions">
            <span class="pf-count pf-bind-count">已认领 ${boundCount}</span>
            <button class="button ghost" type="button" id="pf-auto">按同名自动认领</button>
          </div>
        </div>
        <div id="pf-bind-wrap">${bindGroupsHtml()}</div>
      </div>

      <div class="pf-actions">
        <span class="pf-actions-hint">一次保存：选手名单 + 昵称归属</span>
        <button class="button primary" type="button" id="pf-save-identity">保存身份与认领</button>
      </div>
    </section>`;
  };

  const template = () => {
    const boundCount = Object.keys(aliases).length;
    return `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">PROFILE · 录入</span>
        <h1>${esc(teamName)}</h1>
        <p>先建战队，再建选手身份，最后把数据包里的游戏昵称认领到身份上。大小号因此能合并成同一个人。</p>
        <div class="page-facts">
          <span>教练 ${esc(overview.coach || '未填写')}</span>
          <span>战队 ${1 + teams.length} 支</span>
          <span>选手 ${active().length} 人</span>
          <span>已认领昵称 ${boundCount} 个</span>
          <span>待认领 ${unbound.length} 个</span>
        </div>
      </div>
      <div class="heading-actions">
        <a class="button" href="#teams">看战队档案 →</a>
        <a class="button" href="#players">看选手数据</a>
        <a class="button primary" href="#matches">去比赛档案 →</a>
      </div>
    </div>

    ${progressHtml()}

    <div class="pf-grid">
      <section class="pf-card pf-team-card ${teamEditMode ? 'is-editing' : 'is-saved'}">
        <header><div><h2>我的战队</h2><p>出现在所有报告抬头与标题</p></div></header>
        <div class="pf-form">
          <label class="pf-field"><span>战队名称</span><input id="pf-team" maxlength="50" value="${esc(profileDraft.team)}" placeholder="如：成都AG超玩会"${teamEditMode ? '' : ' readonly'}></label>
          <label class="pf-field"><span>主教练</span><input id="pf-coach" maxlength="30" value="${esc(profileDraft.coach)}" placeholder="如：张三"${teamEditMode ? '' : ' readonly'}></label>
          <label class="pf-field"><span>赛季 / 阶段</span><input id="pf-season" maxlength="40" value="${esc(profileDraft.season)}" placeholder="如：2026 秋季赛 · 常规赛"${teamEditMode ? '' : ' readonly'}></label>
          <label class="pf-field"><span>所属俱乐部</span><input id="pf-org" maxlength="60" value="${esc(profileDraft.org)}" placeholder="选填"${teamEditMode ? '' : ' readonly'}></label>
        </div>
        <div class="pf-actions">
          ${teamEditMode ? '' : '<span class="pf-saved-hint">已保存 · 点「修改」可编辑</span><button class="button" type="button" id="pf-edit-team">修改</button>'}
          <button class="button primary" type="button" id="pf-save-team"${teamEditMode ? '' : ' disabled'}>保存战队信息</button>
        </div>
      </section>

      <section class="pf-card">
        <header><div><h2>首发五人</h2><p>把选手拖到分路，落下即生效；点一下也能自动入位</p></div></header>
        <div id="pf-starter-wrap">${starterHtml()}</div>
      </section>
    </div>

    <section class="pf-card">
      <header>
        <div><h2>战队名录</h2><p>把见过的对手战队也建进来；选手可按战队归类，跨战队显示为「战队.选手名」</p></div>
        <div class="pf-header-actions">
          <button class="button ghost" type="button" id="pf-undo-teams"${teamsHistory.length ? '' : ' disabled'}>撤销</button>
          <button class="button ghost" type="button" id="pf-history-toggle">历史${teamsHistory.length ? ` (${teamsHistory.length})` : ''}</button>
          <button class="button" type="button" id="pf-add-team">＋ 添加战队</button>
        </div>
      </header>
      ${historyOpen ? historyHtml() : ''}
      <div class="pf-teams">
        <div class="pf-team-row own">
          <span class="pf-team-name">${esc(teamName)}<b>本队</b></span>
          <span class="pf-team-meta">${esc(overview.coach || '教练未填')}</span>
          <span class="pf-team-count">${active().filter(m => (m.team || teamName) === teamName).length} 人</span>
        </div>
        ${teams.length ? teams.map(t => `<div class="pf-team-row" data-team="${esc(t.id)}">
          <input class="pf-team-input" data-team-field="name" value="${esc(t.name)}" maxlength="50" aria-label="战队名称" placeholder="战队名称">
          <input class="pf-team-input short" data-team-field="short" value="${esc(t.short || '')}" maxlength="20" aria-label="简称" placeholder="简称">
          <input class="pf-team-input coach" data-team-field="coach" value="${esc(t.coach || '')}" maxlength="30" aria-label="教练" placeholder="教练">
          <span class="pf-team-count">${active().filter(m => m.team === t.name).length} 人</span>
          <button class="pf-member-remove" type="button" data-remove-team="${esc(t.id)}">删除</button>
        </div>`).join('') : '<div class="pf-empty">还没有其它战队。打过的对手可以在这里建档，之后就能按战队归类选手。</div>'}
      </div>
      ${teams.length ? '<div class="pf-actions"><button class="button" type="button" id="pf-save-teams">保存战队名录</button></div>' : ''}
    </section>

    ${identityHtml()}
  `;
  };

  // ---- 数据同步与重绘 ----
  const collectProfile = () => {
    const map = {'pf-team': 'team', 'pf-coach': 'coach', 'pf-season': 'season', 'pf-org': 'org'};
    Object.entries(map).forEach(([id, key]) => {
      const input = container.querySelector(`#${id}`);
      if (input) profileDraft[key] = input.value;
    });
  };
  const collectRoster = () => {
    container.querySelectorAll('.pf-member').forEach(row => {
      const player = roster.find(p => p.id === row.dataset.id);
      if (!player) return;
      const nameInput = row.querySelector('.pf-member-name');
      const laneSelect = row.querySelector('.pf-member-lane');
      if (!nameInput || !laneSelect) return;
      player.name = nameInput.value.trim() || player.name;
      player.position = laneSelect.value;
      player.team = row.querySelector('.pf-member-team')?.value || teamName;
      const tags = row.querySelector('.pf-member-tags')?.value || '';
      player.tags = tags.split(/[，,、\s]+/).map(t => t.trim()).filter(Boolean).slice(0, 8);
      player.campUserId = (row.querySelector('.pf-member-camp')?.value || '').trim();
    });
  };
  const collectTeams = () => {
    teams.forEach(team => {
      const row = container.querySelector(`[data-team="${CSS.escape(team.id)}"]`);
      if (!row) return;
      row.querySelectorAll('[data-team-field]').forEach(input => {
        team[input.dataset.teamField] = input.value.trim();
      });
    });
  };
  const syncAll = () => { collectProfile(); collectTeams(); collectRoster(); };
  const paint = () => {
    syncAll();
    const y = window.scrollY;
    container.innerHTML = template();
    window.scrollTo(0, y);
  };
  const paintStarters = () => {
    const wrap = container.querySelector('#pf-starter-wrap');
    if (wrap) wrap.innerHTML = starterHtml();
  };
  const paintProgress = () => {
    const panel = container.querySelector('.pf-progress');
    if (panel) panel.outerHTML = progressHtml();
  };
  const paintIdentity = () => {
    syncAll();
    const card = container.querySelector('.pf-identity-card');
    if (!card) return;
    const scroll = card.querySelector('.pf-bind-list')?.scrollTop || 0;
    const y = window.scrollY;
    card.outerHTML = identityHtml();
    const list = container.querySelector('.pf-bind-list');
    if (list) list.scrollTop = scroll;
    window.scrollTo(0, y);
  };

  const saveSettings = async (patch = {}) => {
    const payload = {
      ...settings,
      teamName: patch.teamName ?? teamName,
      roster: patch.roster ?? roster,
      aliases: patch.aliases ?? aliases,
      teams: patch.teams ?? teams,
    };
    const response = await fetch('/api/settings', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.detail || '保存失败');
  };

  // ---- 战队名录：撤销 / 历史 ----
  const persistHistory = () => {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(teamsHistory)); } catch { /* 隐私模式下忽略 */ }
  };
  const pushHistory = label => {
    teamsHistory.unshift({at: Date.now(), label, teams: cloneTeams(lastTeamsSnapshot)});
    teamsHistory = teamsHistory.slice(0, 12);
    persistHistory();
  };
  const restoreTeams = entry => {
    teams.splice(0, teams.length, ...cloneTeams(entry.teams || []));
    lastTeamsSnapshot = cloneTeams(teams);
    historyOpen = false;
    paint();
  };

  // ---- 首发五人：拖动即自动保存 ----
  const movePlayer = async (id, lane) => {
    if (laneSaving) return;
    const player = roster.find(p => p.id === id);
    if (!player) return;
    laneSaving = true;
    syncAll();
    const before = new Map(roster.map(p => [p.id, laneOf(p)]));
    if (lane) roster.forEach(p => { if (p.id !== id && laneOf(p) === lane) p.position = ''; });
    player.position = lane || '';
    laneStatus = '保存中…';
    paintStarters();
    try {
      await saveSettings({roster, teams});
      laneStatus = '已自动保存 · 拖动即时生效';
      paintProgress();
    } catch (error) {
      before.forEach((position, pid) => {
        const p = roster.find(x => x.id === pid);
        if (p) p.position = position;
      });
      laneStatus = `保存失败，已恢复：${error.message}`;
      toast?.(error.message, true);
    } finally {
      laneSaving = false;
      paintStarters();
    }
  };

  const openPlayerDialog = nickname => {
    const dialog = document.querySelector('#detail-dialog');
    const title = document.querySelector('#detail-title');
    const body = document.querySelector('#detail-body');
    if (!dialog || !body) return;
    title.textContent = '新建选手身份';
    body.innerHTML = `<div class="pf-new">
      <p class="pf-new-lead">游戏昵称 <b>${esc(nickname)}</b> 会认领到这名选手。多个昵称可以指向同一个身份（大小号）。</p>
      <label class="pf-fix-field"><span>选手名（职业 ID / 真名）</span>
        <input id="np-name" maxlength="50" value="${esc(nickname)}" placeholder="如：小胖"></label>
      <div class="ar-fix-row">
        <label class="pf-fix-field"><span>所属战队</span>
          <select id="np-team">${teamOptions().map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('')}</select></label>
        <label class="pf-fix-field"><span>位置</span>
          <select id="np-lane"><option value="">未设分路</option>${LANES.map(l => `<option value="${l}">${l}</option>`).join('')}</select></label>
      </div>
      <label class="pf-fix-field"><span>标签（逗号分隔）</span>
        <input id="np-tags" maxlength="60" value="小号" placeholder="首发，替补，小号"></label>
      <div class="pf-actions"><button class="button" type="button" id="np-cancel">取消</button><button class="button primary" type="button" id="np-save">创建并认领</button></div>
    </div>`;
    dialog.showModal();
    const close = () => dialog.close();
    body.querySelector('#np-cancel').onclick = close;
    body.querySelector('#np-save').onclick = () => {
      syncAll();
      const name = body.querySelector('#np-name').value.trim();
      if (!name) return alert('请填写选手名');
      const member = {
        id: uid(), name,
        team: body.querySelector('#np-team').value || teamName,
        position: body.querySelector('#np-lane').value,
        tags: body.querySelector('#np-tags').value.split(/[，,、\s]+/).map(t => t.trim()).filter(Boolean).slice(0, 8),
      };
      roster.push(member);
      aliases[nickname] = member.id;
      selectedId = member.id;
      close();
      paint();
      toast?.(`已创建 ${identityOf(member)} 并认领「${nickname}」，记得保存`);
    };
  };

  paint();

  // ---- 点击分发 ----
  container.addEventListener('click', async (event) => {
    const avatar = event.target.closest('[data-avatar-action]');
    if (avatar) {
      const id = avatar.dataset.avatarId;
      const action = avatar.dataset.avatarAction;
      if (action === 'select-player') { selectedId = id; paintIdentity(); return; }
      if (action === 'lane-slot') return;
      if (action === 'lane-pool') {
        const used = new Set(roster.filter(p => LANES.includes(laneOf(p))).map(laneOf));
        const free = LANES.find(l => !used.has(l));
        if (free) await movePlayer(id, free);
        else toast?.('五个分路都已占满，先把一个拖回选手池', true);
        return;
      }
    }

    const btn = event.target.closest('button');
    if (!btn) return;

    if (btn.dataset.bindNew) { openPlayerDialog(btn.dataset.bindNew); return; }

    if (btn.dataset.toggleGroup) {
      const key = btn.dataset.toggleGroup;
      if (openGroups.has(key)) openGroups.delete(key);
      else openGroups.add(key);
      paintIdentity();
      return;
    }
    if (btn.dataset.toggleAll) {
      if (btn.dataset.toggleAll === 'expand') claimGroups().forEach(group => openGroups.add(group.key));
      else openGroups.clear();
      paintIdentity();
      return;
    }

    // 认领：目标就是当前选中的身份，不再每项重复一排头像
    if (btn.dataset.claimLabel) {
      if (!selectedId) { toast?.('先在上面点一个选手身份', true); return; }
      aliases[btn.dataset.claimLabel] = selectedId;
      paintIdentity();
      return;
    }
    if (btn.dataset.unbind) {
      delete aliases[btn.dataset.unbind];
      paintIdentity();
      return;
    }
    if (btn.dataset.editOwner) {
      selectedId = btn.dataset.editOwner;
      paintIdentity();
      toast?.('已切换到这名选手，可在上方编辑');
      return;
    }

    if (btn.dataset.clearLane) {
      const p = roster.find(x => laneOf(x) === btn.dataset.clearLane);
      if (p) await movePlayer(p.id, '');
      return;
    }

    if (btn.id === 'pf-edit-team') {
      teamEditMode = true;
      paint();
      container.querySelector('#pf-team')?.focus();
      return;
    }

    if (btn.id === 'pf-save-team') {
      btn.disabled = true;
      try {
        const response = await fetch('/api/studio/profile', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            teamName: container.querySelector('#pf-team').value.trim(),
            coach: container.querySelector('#pf-coach').value.trim(),
            season: container.querySelector('#pf-season').value.trim(),
            organization: container.querySelector('#pf-org').value.trim(),
          }),
        });
        if (!response.ok) throw Error((await response.json()).detail || '保存失败');
        toast?.('战队信息已保存');
        await onSaved?.();
        location.reload();
      } catch (error) { toast?.(error.message, true); }
      finally { btn.disabled = false; }
      return;
    }

    if (btn.id === 'pf-add-team') {
      pushHistory('添加战队');
      const team = {id: uid('team'), name: '', short: '', coach: '', note: ''};
      teams.push(team);
      lastTeamsSnapshot = cloneTeams(teams);
      paint();
      container.querySelector(`[data-team="${CSS.escape(team.id)}"] [data-team-field="name"]`)?.focus();
      return;
    }

    if (btn.dataset.removeTeam) {
      const team = teams.find(t => t.id === btn.dataset.removeTeam);
      if (!team) return;
      collectTeams();
      const used = active().filter(m => m.team === team.name).length;
      if (used && !confirm(`${team.name} 下还有 ${used} 名选手。删除战队后他们会回到本队，确定继续？`)) return;
      pushHistory(`删除「${team.name || '未命名战队'}」`);
      roster.forEach(m => { if (m.team === team.name) m.team = teamName; });
      teams.splice(teams.indexOf(team), 1);
      lastTeamsSnapshot = cloneTeams(teams);
      paint();
      return;
    }

    if (btn.id === 'pf-undo-teams') {
      const entry = teamsHistory.shift();
      if (!entry) return;
      persistHistory();
      restoreTeams(entry);
      toast?.('已撤销上一步，记得保存战队名录');
      return;
    }

    if (btn.id === 'pf-history-toggle') { historyOpen = !historyOpen; paint(); return; }

    if (btn.dataset.restore !== undefined) {
      const index = Number(btn.dataset.restore);
      const entry = teamsHistory[index];
      if (!entry) return;
      teamsHistory = teamsHistory.slice(index + 1);
      persistHistory();
      restoreTeams(entry);
      toast?.('已恢复到该版本，记得保存战队名录');
      return;
    }

    if (btn.id === 'pf-save-teams') {
      btn.disabled = true;
      try {
        collectTeams();
        if (teams.some(t => !t.name)) throw Error('战队名称不能为空');
        await saveSettings({teams});
        toast?.('战队名录已保存');
        await onSaved?.();
        location.reload();
      } catch (error) { toast?.(error.message, true); }
      finally { btn.disabled = false; }
      return;
    }

    if (btn.id === 'pf-add' || btn.id === 'pf-avatar-add') {
      const member = {id: uid(), name: '新选手', team: teamName, position: '', tags: []};
      roster.push(member);
      selectedId = member.id;
      paint();
      container.querySelector('.pf-member-name')?.focus();
      return;
    }

    if (btn.dataset.remove) {
      const id = btn.dataset.remove;
      const member = roster.find(p => p.id === id);
      if (!member) return;
      const bound = aliasesFor(id);
      if (bound.length && !confirm(`${identityOf(member)} 还认领着 ${bound.length} 个昵称（${bound.slice(0, 3).join('、')}）。移出后这些昵称会回到待认领，确定？`)) return;
      bound.forEach(label => { delete aliases[label]; });
      roster.splice(roster.indexOf(member), 1);
      if (selectedId === id) selectedId = roster[0]?.id || '';
      paint();
      toast?.(`已移出 ${identityOf(member)}，保存名单后删除`);
      return;
    }

    if (btn.id === 'pf-auto') {
      const byName = new Map(active().map(p => [p.name, p.id]));
      let hits = 0;
      pending.forEach(item => {
        const id = byName.get(item.label);
        if (id && !aliases[item.label]) { aliases[item.label] = id; hits++; }
      });
      paintIdentity();
      toast?.(hits ? `已按同名认领 ${hits} 个昵称，记得保存` : '没有新的同名昵称，需要手动选择');
      return;
    }

    if (btn.id === 'pf-save-identity') {
      btn.disabled = true;
      try {
        syncAll();
        await saveSettings({roster, aliases, teams});
        toast?.('身份与认领已保存');
        await onSaved?.();
        location.reload();
      } catch (error) { toast?.(error.message, true); }
      finally { btn.disabled = false; }
    }
  });

  // ---- 变更事件：字段编辑留痕 + 身份预览 ----
  container.addEventListener('change', event => {
    const field = event.target.closest('[data-team-field]');
    if (field) {
      pushHistory('编辑战队字段');
      collectTeams();
      lastTeamsSnapshot = cloneTeams(teams);
      paintHistoryControls();
      return;
    }
    const row = event.target.closest('.pf-member');
    if (row && (event.target.classList.contains('pf-member-name') || event.target.classList.contains('pf-member-team'))) {
      const preview = row.querySelector('.pf-member-preview');
      if (preview) {
        const name = row.querySelector('.pf-member-name')?.value.trim() || '';
        const team = row.querySelector('.pf-member-team')?.value || '';
        preview.textContent = team && team !== teamName && name ? `${team}.${name}` : '';
      }
      refreshAvatars();
    }
  });

  container.addEventListener('input', event => {
    if (!event.target.classList.contains('pf-member-name')) return;
    const row = event.target.closest('.pf-member');
    const preview = row?.querySelector('.pf-member-preview');
    if (preview) {
      const name = event.target.value.trim();
      const team = row.querySelector('.pf-member-team')?.value || '';
      preview.textContent = team && team !== teamName && name ? `${team}.${name}` : '';
    }
    refreshAvatars();
  });

  // 输入选手名时实时更新头像文字与边框，不重绘（避免丢焦点）
  const refreshAvatars = () => {
    const row = container.querySelector('.pf-member');
    if (!row) return;
    const id = row.dataset.id;
    const player = roster.find(p => p.id === id);
    if (!player) return;
    const nameInput = row.querySelector('.pf-member-name');
    if (nameInput) player.name = nameInput.value.trim() || player.name;
    container.querySelectorAll(`[data-avatar-id="${CSS.escape(id)}"]`).forEach(node => {
      const filled = isFilled(player);
      node.classList.toggle('is-filled', filled);
      node.classList.toggle('is-empty', !filled);
      const span = node.querySelector('span');
      if (span) span.textContent = initials(player, node.classList.contains('xs') ? 'xs' : '');
    });
    const hint = container.querySelector('.pf-roster-hint b');
    if (hint) hint.textContent = `${roster.filter(isFilled).length}/${roster.length}`;
  };

  const paintHistoryControls = () => {
    const undo = container.querySelector('#pf-undo-teams');
    if (undo) undo.disabled = !teamsHistory.length;
    const toggle = container.querySelector('#pf-history-toggle');
    if (toggle) toggle.textContent = `历史${teamsHistory.length ? ` (${teamsHistory.length})` : ''}`;
    if (historyOpen) {
      const panel = container.querySelector('.pf-history');
      if (panel) panel.outerHTML = historyHtml();
    }
  };

  // ---- 拖拽：选手池 ⇄ 分路槽位 ----
  container.addEventListener('dragstart', event => {
    const source = event.target.closest('[data-player-id]');
    if (!source) return;
    event.dataTransfer.setData('text/plain', source.dataset.playerId);
    event.dataTransfer.effectAllowed = 'move';
    source.classList.add('is-dragging');
  });
  container.addEventListener('dragend', () => {
    container.querySelectorAll('.is-dragging').forEach(node => node.classList.remove('is-dragging'));
    container.querySelectorAll('.is-over').forEach(node => node.classList.remove('is-over'));
  });
  container.addEventListener('dragover', event => {
    const zone = event.target.closest('[data-lane], [data-drop="pool"]');
    if (!zone) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    zone.classList.add('is-over');
  });
  container.addEventListener('dragleave', event => {
    const zone = event.target.closest('[data-lane], [data-drop="pool"]');
    if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-over');
  });
  container.addEventListener('drop', event => {
    const zone = event.target.closest('[data-lane], [data-drop="pool"]');
    if (!zone) return;
    event.preventDefault();
    zone.classList.remove('is-over');
    const id = event.dataTransfer.getData('text/plain');
    if (id) movePlayer(id, zone.dataset.lane || '');
  });
}
