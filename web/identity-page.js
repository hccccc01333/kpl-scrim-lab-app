/* 对局分边：逐条认领/改绑/解绑统一在「录入」页，这里只做分边、对手命名和批量自动认领。
   每局两侧的十人名单只用来确认谁在哪边；每人右侧是只读的认领状态，不再重复一套下拉。
*/
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const CAMP_NAME = {blue: '蓝方', red: '红方'};

function identityOf(member, ownTeam) {
  const team = (member.team || '').trim();
  const name = (member.name || '').trim();
  return team && team !== ownTeam && name ? `${team}.${name}` : name;
}

export async function renderIdentity(container, {api, workspace, isCurrent, toast, onSaved}) {
  const [identity, state] = await Promise.all([
    api('/api/studio/identity'),
    api('/api/state'),
  ]);
  if (isCurrent && !isCurrent()) return;
  const settings = state.settings || {};
  const ownTeam = (settings.teamName || '我的训练队').trim();
  const teams = [...new Set([ownTeam, ...(settings.teams || []).map(t => t.name).filter(Boolean)])];
  const roster = (settings.roster || []).filter(p => !p.archived);
  const aliases = {...(settings.aliases || {})};
  const enemyAliases = {...(settings.enemyAliases || {})};
  const matches = identity.matchTeams || [];
  const campGames = identity.campGames || [];
  const campNamed = campGames.filter(g => g.opponent).length;
  const draftTeams = [...teams];

  const teamSelect = (camp, current) => `<select class="idp-team" data-team-select="${camp}">
    <option value=""${current ? '' : ' selected'}>选择战队…</option>
    ${draftTeams.map(t => `<option value="${esc(t)}"${t === current ? ' selected' : ''}>${esc(t)}</option>`).join('')}
    <option value="__new__">＋ 新建战队…</option>
  </select>`;

  // 认领在「录入」页做过了，这里只列十人名单，不再放认领下拉 / 解绑 / 认领状态。
  const playerRow = (side, player, index) => `<div class="idp-player" data-camp="${side.camp}" data-nick="${esc(player.label)}">
    <span class="idp-index">${index + 1}</span>
    <div class="idp-who">
      <strong>${esc(player.label)}</strong>
      <small>${esc(player.hero || '英雄未识别')}</small>
    </div>
  </div>`;

  const sideBlock = (match, side) => {
    const current = side.isOwn ? ownTeam : (side.teamName === '对手待填写' ? '' : side.teamName);
    return `<div class="idp-side ${side.isOwn ? 'own' : 'enemy'}" data-side="${side.camp}" data-own="${side.isOwn ? '1' : '0'}">
      <header class="idp-side-head">
        <span class="idp-camp ${side.camp}">${CAMP_NAME[side.camp] || side.camp}${side.side === 'left' ? ' / 左侧' : ' / 右侧'}</span>
        ${teamSelect(side.camp, current)}
        <span class="idp-side-role">${side.isOwn ? '本队' : (current ? '对手' : '待指定')}</span>
      </header>
      <div class="idp-players">
        ${(side.players || []).map((p, i) => playerRow(side, p, i)).join('')}
      </div>
    </div>`;
  };

  const matchCard = match => `<article class="idp-match" data-idp-key="${esc(match.key)}">
    <header class="idp-match-head">
      <div>
        <strong>${esc(match.date || '日期待补')} · ${esc(match.title || '训练赛')}</strong>
        <small>${esc(match.opponent ? '对手：' + match.opponent : '对手未填写')} · 本队${match.ownCamp ? CAMP_NAME[match.ownCamp] || match.ownCamp : '阵营待确认'}</small>
      </div>
      <div class="idp-match-actions">
        <button class="button" data-save-match="${esc(match.key)}">保存本局</button>
      </div>
    </header>
    <div class="idp-sides">${(match.sides || []).map(side => sideBlock(match, side)).join('')}</div>
  </article>`;

  /* 营地十人面板：我方阵营由取数账号自动识别，一般不用动；给对手命名后，
     深度分析（营地口径）会出现「我方 / 对方」视角选项框。改动即保存，不整页刷新。 */
  const campRow = g => {
    const manual = g.ownCampSource === 'manual';
    const sideText = g.ownCamp
      ? `本队${CAMP_NAME[g.ownCamp] || g.ownCamp}${manual ? '（手动）' : '（自动）'}${g.ownWin === true ? ' · 胜' : g.ownWin === false ? ' · 负' : ''}`
      : '阵营未知';
    return `<div class="idp-camp-row" data-camp-key="${esc(g.key)}" data-camp-id="${esc(g.id)}" data-auto-camp="${esc(g.ownCampSource === 'auto' ? (g.ownCamp || '') : '')}">
      <span class="idp-camp-date">${esc(g.date || g.id)}</span>
      <span class="idp-camp-side ${g.ownCamp ? (g.ownCamp === 'blue' ? 'blue' : 'red') : 'unknown'}">${esc(sideText)}</span>
      <select class="idp-camp-owncamp" title="修正我方所在阵营">
        <option value=""${manual ? '' : ' selected'}>自动识别</option>
        <option value="blue"${manual && g.ownCamp === 'blue' ? ' selected' : ''}>本队在蓝方</option>
        <option value="red"${manual && g.ownCamp === 'red' ? ' selected' : ''}>本队在红方</option>
      </select>
      <select class="idp-camp-opponent" title="命名这一局的对手">
        <option value=""${g.opponent ? '' : ' selected'}>对手未命名</option>
        ${draftTeams.filter(t => t !== ownTeam).map(t => `<option value="${esc(t)}"${t === g.opponent ? ' selected' : ''}>${esc(t)}</option>`).join('')}
        <option value="__new__">＋ 新建战队…</option>
      </select>
    </div>`;
  };

  container.innerHTML = `
    <div class="page-heading">
      <div>
        <span class="page-eyebrow">IDENTITY · 对局分边</span>
        <h1>对局分边</h1>
        <p>给每局确认本队在蓝方还是红方、对手是哪支战队。昵称认领统一在「录入」页完成，这里只显示认领结果；批量处理可点「自动认领」。</p>
        <div class="page-facts">
          <span>${matches.length} 场可核对</span>
          <span>${roster.length} 个选手身份</span>
          <span>本队已认领 ${Object.keys(aliases).length} 个昵称</span>
          <span>对手已认领 ${Object.keys(enemyAliases).length} 个昵称</span>
          <span>营地局 ${campGames.length} 局 · 对手已命名 ${campNamed} 局</span>
        </div>
      </div>
      <div class="heading-actions">
        <button class="button idp-start" data-auto-claim>自动认领</button>
        <a class="button" href="#profile">管理与建档</a>
        <button class="button primary" data-save-all>保存全部</button>
      </div>
    </div>

    <div class="idp-tip">
      <strong>怎么用</strong>
      <span>两边的战队下拉决定「这五个人属于谁」，选错边就把两边对调。逐条认领、改绑、解绑都在<a href="#profile">「录入」页</a>，本页不重复维护；右侧只是当前认领状态。想一次处理多局，点「自动认领」跑一遍，存疑的再交给教练。</span>
    </div>

    <div class="idp-auto" id="idp-auto" hidden></div>

    ${matches.length ? matches.map(matchCard).join('') : `<div class="ar-empty">
      <strong>还没有可核对的对局</strong><p>需要至少一局含十人名单的比赛。</p><a class="button primary" href="#matches">去比赛档案</a>
    </div>`}

    <section class="panel idp-camp-panel">
      <div class="panel-head"><div><h2>营地十人面板 · 分边与对手</h2>
        <p>${campGames.length} 局营地面板（深度分析的数据源）。我方阵营按取数账号自动识别，一般不用改；<b>给对手命名后，深度分析会出现「我方 / 对方」视角和对比</b>。改动即保存。</p></div></div>
      <div class="idp-camp-list">${campGames.map(campRow).join('') || `<div class="ar-empty"><strong>还没有营地十人面板</strong><p>采集营地详情后会出现在这里。</p></div>`}</div>
    </section>
  `;

  const refreshColumn = (card, camp) => {
    const side = card.querySelector(`[data-side="${camp}"]`);
    if (!side) return;
    const team = side.querySelector('[data-team-select]').value;
    side.querySelector('.idp-side-role').textContent = team === ownTeam ? '本队' : (team ? '对手' : '待指定');
  };

  // 保存分边只写 match_meta；aliases / enemyAliases 由「录入」页和自动认领维护，
  // 这里不再随页面快照回写，避免两个页面同时打开时把新认领覆盖掉。
  const saveMatch = async (card) => {
    const key = card.dataset.idpKey;
    const sides = [...card.querySelectorAll('.idp-side')].map(side => ({
      camp: side.dataset.side,
      team: side.querySelector('[data-team-select]').value,
    }));
    const ownSide = sides.find(side => side.team === ownTeam);
    if (!ownSide) throw Error('两边的战队里必须有一边是「' + ownTeam + '」');
    const other = sides.find(side => side !== ownSide);
    if (other && other.team === ownSide.team) throw Error('两边不能是同一支战队');

    await fetch(`/api/studio/match-meta/${encodeURIComponent(key)}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ownCamp: ownSide.camp, opponent: other ? other.team : ''}),
    }).then(async r => { if (!r.ok) throw Error((await r.json()).detail || '保存分边失败'); });
  };

  const persist = async () => {
    const payload = {
      ...settings,
      teamName: ownTeam,
      roster,
      teams: draftTeams.filter(t => t !== ownTeam).map(name => {
        const existing = (settings.teams || []).find(t => t.name === name);
        return existing || {id: 'team-' + Math.random().toString(36).slice(2, 9), name, short: '', coach: '', note: ''};
      }),
    };
    // 认领表不随本页回写：服务端会用库里最新的 aliases / enemyAliases 补齐。
    delete payload.aliases;
    delete payload.enemyAliases;
    const response = await fetch('/api/settings', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    if (!response.ok) throw Error((await response.json().catch(() => ({}))).detail || '保存设置失败');
  };

  let persistTimer = null;
  let persistPending = false;
  const schedulePersist = (message) => {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(async () => {
      if (persistPending) return;
      persistPending = true;
      try {
        await persist();
        toast?.(message || '已保存');
        await onSaved?.();
      } catch (error) {
        toast?.(error.message, true);
      } finally {
        persistPending = false;
      }
    }, 450);
  };

  const saveCards = async (cards) => {
    for (const card of cards) await saveMatch(card);
    await persist();
    toast?.('已保存分边与对手');
    await onSaved?.();
    location.reload();
  };

  /* ---------- 自动认领 ----------
     后端按存档战队名单给出「可自动 / 存疑」预览；这里只负责展示、收教练的判断、
     以及把可落库的那部分写到既有接口（/api/settings + /api/studio/match-meta）。
     教练判断过的对局会整局建档，下一次同类对局就能自动匹配。 */
  let autoPlan = null, autoMaxDiff = 1, autoDecisions = {}, autoNewTeams = [],
      autoOnlyReview = false, autoBusy = false;
  const autoPanel = () => container.querySelector('#idp-auto');

  const autoDecisionControls = item => {
    const key = esc(item.key);
    const chosen = autoDecisions[item.key];
    if (chosen) {
      return `<div class="idp-auto-decided">
        <span>本队${esc(CAMP_NAME[chosen.ownCamp] || chosen.ownCamp)} · 对手「${esc(chosen.opponent)}」</span>
        <button class="button tiny" type="button" data-auto-undo="${key}">撤销判断</button>
      </div>`;
    }
    const hint = item.hintCamp === 'red' ? 'red' : 'blue';
    const camps = ['blue', 'red'].map(c =>
      `<option value="${c}"${c === hint ? ' selected' : ''}>本队在${CAMP_NAME[c]}</option>`).join('');
    const teams = `<option value="">选择对手战队…</option>`
      + (autoPlan?.options?.teams || []).map(t =>
        `<option value="${esc(t)}"${t === item.currentOpponent ? ' selected' : ''}>${esc(t)}</option>`).join('')
      + `<option value="__new__">＋ 新建战队…</option>`;
    return `<div class="idp-auto-decide">
      <select data-auto-camp="${key}" aria-label="本队所在阵营">${camps}</select>
      <select data-auto-opponent="${key}" aria-label="对手战队">${teams}</select>
      <button class="button tiny" type="button" data-auto-decide="${key}">按此判断建档</button>
    </div>`;
  };

  const markReviewCards = () => {
    const byKey = new Map((autoPlan?.matches || []).map(item => [item.key, item]));
    container.querySelectorAll('.idp-match').forEach(card => {
      card.querySelectorAll('.idp-review-badge').forEach(node => node.remove());
      const item = byKey.get(card.dataset.idpKey);
      const review = item?.status === 'review';
      card.classList.toggle('is-review', review);
      if (review) {
        card.querySelector('.idp-match-head > div')?.insertAdjacentHTML('beforeend',
          `<span class="idp-review-badge">存疑 · 待教练判断</span>`);
      }
    });
  };

  const renderAutoPanel = () => {
    const panel = autoPanel();
    if (!panel || !autoPlan) return;
    const summary = autoPlan.summary;
    const applicable = summary.auto + summary.decided;
    const archive = Object.entries(summary.archiveTeams || {})
      .map(([team, count]) => `${esc(team)} ${count} 个昵称`).join(' · ') || '暂无存档';
    const rows = autoPlan.matches.map(item => {
      const badge = item.status === 'auto' ? '可自动' : item.status === 'decided' ? '教练判断' : '存疑 · 交给教练';
      const sides = (item.sides || []).length ? `<div class="idp-auto-sides">${item.sides.map(side =>
        `<span>${esc(CAMP_NAME[side.camp] || side.camp)} · ${esc(side.team)} <b>${side.hits}/${side.binds.length}</b>${
          side.unknown?.length ? ` · 新昵称：${esc(side.unknown.slice(0, 3).join('、'))}${side.unknown.length > 3 ? '…' : ''}` : ''}</span>`).join('')}</div>` : '';
      const notes = (item.notes || []).length ? `<small class="idp-auto-notes">${esc(item.notes.join('；'))}</small>` : '';
      const control = item.status === 'auto'
        ? `<div class="idp-auto-ok">本队${esc(CAMP_NAME[item.ownCampPlan] || '')} · 对手「${esc(item.opponent || '')}」</div>`
        : autoDecisionControls(item);
      return `<div class="idp-auto-row ${item.status}">
        <span class="idp-auto-badge">${badge}</span>
        <div class="idp-auto-main">
          <strong>${esc(item.date ? item.date + ' · ' : '')}${esc(item.title)}</strong>
          <small>${esc(item.reason)}</small>${sides}${notes}
        </div>
        <div class="idp-auto-ctrl">${control}</div>
      </div>`;
    }).join('');
    panel.hidden = false;
    panel.innerHTML = `
      <div class="idp-auto-head">
        <div>
          <strong>自动认领 · 预览</strong>
          <p>一侧最多 <b>${summary.maxDiff}</b> 个没见过的昵称就自动认领；2 个及以上（可能是对手开小号，或约到了新对手）交给教练。红蓝一边本队、一边对手。教练的判断会写进存档，下一次同类对局就能自动匹配。</p>
        </div>
        <div class="idp-auto-tools">
          <label>允许不同 <select data-auto-diff aria-label="允许几个没见过的昵称">
            ${[0, 1, 2].map(n => `<option value="${n}"${n === summary.maxDiff ? ' selected' : ''}>${n} 个</option>`).join('')}
          </select></label>
          <label class="idp-auto-filter"><input type="checkbox" data-auto-filter${autoOnlyReview ? ' checked' : ''}> 只看存疑</label>
          <button class="button tiny" type="button" data-auto-close>收起</button>
        </div>
      </div>
      <div class="idp-auto-summary">
        <span><b>${summary.total}</b> 局待核对</span>
        <span class="ok"><b>${applicable}</b> 局可应用</span>
        <span class="warn"><b>${summary.review}</b> 局交给教练</span>
        <span class="muted">存档：${archive}</span>
      </div>
      <div class="idp-auto-list">${rows || '<div class="idp-auto-empty">没有可核对的 5v5 对局。</div>'}</div>
      <div class="idp-auto-foot">
        <small>应用只写入「可自动」和「教练判断」的对局；存疑局保持原样。昵称认领、新建身份和分边会立即保存。</small>
        <button class="button primary" type="button" data-auto-apply${applicable ? '' : ' disabled'}>应用 ${applicable} 局</button>
      </div>`;
    container.classList.toggle('only-review', autoOnlyReview);
  };

  const loadPlan = async () => {
    if (autoBusy) return;
    autoBusy = true;
    try {
      const plan = await api('/api/studio/identity/auto-claim', {maxDiff: autoMaxDiff, decisions: autoDecisions});
      // 本轮刚新建的战队还没落库，重算预览时要补回下拉，方便教练连续判断多局。
      autoNewTeams.forEach(name => {
        if (!plan.options.teams.includes(name)) plan.options.teams.push(name);
      });
      autoPlan = plan;
      renderAutoPanel();
      markReviewCards();
    } catch (error) {
      toast?.(error.message, true);
    } finally {
      autoBusy = false;
    }
  };

  const applyPlan = async () => {
    const delta = autoPlan?.deltas;
    if (!delta?.metas?.length) { toast?.('没有可应用的结果', true); return; }
    const state = await api('/api/state');
    const next = {...(state.settings || {})};
    next.roster = [...(next.roster || []), ...delta.members];
    next.aliases = {...(next.aliases || {}), ...delta.aliases};
    next.enemyAliases = {...(next.enemyAliases || {}), ...delta.enemyAliases};
    const teams = [...(next.teams || [])];
    (delta.teams || []).forEach(name => {
      if (name && name !== next.teamName && !teams.some(t => t.name === name)) {
        teams.push({id: 'team-' + Math.random().toString(36).slice(2, 9), name, short: '', coach: '', note: ''});
      }
    });
    next.teams = teams;
    for (const meta of delta.metas) {
      const response = await fetch(`/api/studio/match-meta/${encodeURIComponent(meta.key)}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ownCamp: meta.ownCamp, opponent: meta.opponent}),
      });
      if (!response.ok) throw Error((await response.json().catch(() => ({}))).detail || '保存分边失败');
    }
    const response = await fetch('/api/settings', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(next),
    });
    if (!response.ok) throw Error((await response.json().catch(() => ({}))).detail || '保存认领失败');
    toast?.(`已自动认领 ${delta.metas.length} 局，存疑的留给教练`);
    await onSaved?.();
    location.reload();
  };

  container.addEventListener('change', async (event) => {
    if (event.target.matches('[data-auto-diff]')) {
      autoMaxDiff = Number(event.target.value) || 0;
      await loadPlan();
      return;
    }
    if (event.target.matches('[data-auto-filter]')) {
      autoOnlyReview = event.target.checked;
      container.classList.toggle('only-review', autoOnlyReview);
    }
  });

  container.addEventListener('click', async (event) => {
    const start = event.target.closest('[data-auto-claim]');
    if (start) {
      start.disabled = true;
      await loadPlan();
      start.disabled = false;
      autoPanel()?.scrollIntoView({behavior: 'smooth', block: 'start'});
      return;
    }
    if (event.target.closest('[data-auto-close]')) {
      const panel = autoPanel();
      if (panel) panel.hidden = true;
      return;
    }
    const undo = event.target.closest('[data-auto-undo]');
    if (undo) {
      delete autoDecisions[undo.dataset.autoUndo];
      await loadPlan();
      return;
    }
    const decide = event.target.closest('[data-auto-decide]');
    if (decide) {
      const key = decide.dataset.autoDecide;
      const row = decide.closest('.idp-auto-row');
      const camp = row?.querySelector('[data-auto-camp]')?.value || 'blue';
      const opponentSelect = row?.querySelector('[data-auto-opponent]');
      let opponent = opponentSelect?.value || '';
      if (opponent === '__new__') {
        const name = prompt('新战队名称（如：重庆狼队）');
        if (!name?.trim()) return;
        opponent = name.trim().slice(0, 50);
        if (!autoNewTeams.includes(opponent)) autoNewTeams.push(opponent);
        if (!autoPlan.options.teams.includes(opponent)) autoPlan.options.teams.push(opponent);
      }
      if (!opponent) { toast?.('请先选对手战队', true); return; }
      autoDecisions[key] = {ownCamp: camp, opponent};
      await loadPlan();
      return;
    }
    const apply = event.target.closest('[data-auto-apply]');
    if (apply) {
      apply.disabled = true;
      try { await applyPlan(); }
      catch (error) { toast?.(error.message, true); apply.disabled = false; }
      return;
    }

    const saveOne = event.target.closest('[data-save-match]');
    if (saveOne) {
      const card = saveOne.closest('.idp-match');
      saveOne.disabled = true;
      try { await saveCards([card]); }
      catch (error) { toast?.(error.message, true); saveOne.disabled = false; }
      return;
    }

    if (event.target.closest('[data-save-all]')) {
      const btn = event.target.closest('[data-save-all]');
      btn.disabled = true;
      try { await saveCards([...container.querySelectorAll('.idp-match')]); }
      catch (error) { toast?.(error.message, true); btn.disabled = false; }
    }
  });

  container.addEventListener('change', (event) => {
    const teamSel = event.target.closest('[data-team-select]');
    if (teamSel) {
      if (teamSel.value === '__new__') {
        const name = prompt('新战队名称（如：重庆狼队）');
        if (!name?.trim()) {
          teamSel.value = ownTeam;
          return;
        }
        const clean = name.trim().slice(0, 50);
        if (!draftTeams.includes(clean)) {
          draftTeams.push(clean);
          container.querySelectorAll('[data-team-select]').forEach(sel => {
            sel.insertAdjacentHTML('afterbegin', `<option value="${esc(clean)}">${esc(clean)}</option>`);
          });
        }
        teamSel.value = clean;
      }
      const card = teamSel.closest('.idp-match');
      refreshColumn(card, teamSel.dataset.teamSelect);
    }
  });

  /* 营地局标注：改动即保存到 match_meta（camp:<gameSeq>），与深度分析同一份覆盖层 */
  const campSave = async row => {
    const key = row.dataset.campKey;
    const ownSel = row.querySelector('.idp-camp-owncamp');
    const opponentSel = row.querySelector('.idp-camp-opponent');
    const response = await fetch(`/api/studio/match-meta/${encodeURIComponent(key)}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ownCamp: ownSel.value || '', opponent: opponentSel.value === '__new__' ? '' : (opponentSel.value || '')}),
    });
    if (!response.ok) throw Error((await response.json().catch(() => ({}))).detail || '保存营地分边失败');
    // 本地刷新阵营徽章，不整页刷新
    const badge = row.querySelector('.idp-camp-side');
    const camp = ownSel.value || row.dataset.autoCamp || '';
    const source = ownSel.value ? '（手动）' : camp ? '（自动）' : '';
    badge.textContent = camp ? `本队${CAMP_NAME[camp] || camp}${source}` : '阵营未知';
    badge.className = `idp-camp-side ${camp === 'blue' ? 'blue' : camp === 'red' ? 'red' : 'unknown'}`;
  };

  container.addEventListener('change', async event => {
    const ownSel = event.target.closest('.idp-camp-owncamp');
    const opponentSel = event.target.closest('.idp-camp-opponent');
    if (!ownSel && !opponentSel) return;
    const row = event.target.closest('.idp-camp-row');
    if (!row) return;
    try {
      if (opponentSel && opponentSel.value === '__new__') {
        const name = prompt('新战队名称（如：重庆狼队）');
        if (!name?.trim()) { opponentSel.value = ''; return; }
        const clean = name.trim().slice(0, 50);
        if (!draftTeams.includes(clean)) {
          draftTeams.push(clean);
          container.querySelectorAll('.idp-camp-opponent').forEach(sel => {
            if (sel !== opponentSel) sel.insertAdjacentHTML('beforeend', `<option value="${esc(clean)}">${esc(clean)}</option>`);
          });
          container.querySelectorAll('[data-team-select]').forEach(sel => {
            sel.insertAdjacentHTML('afterbegin', `<option value="${esc(clean)}">${esc(clean)}</option>`);
          });
        }
        opponentSel.insertAdjacentHTML('beforeend', `<option value="${esc(clean)}">${esc(clean)}</option>`);
        opponentSel.value = clean;
        schedulePersist('新战队已保存');
      }
      await campSave(row);
      toast?.('营地局已保存');
    } catch (error) {
      toast?.(error.message, true);
    }
  });
}
