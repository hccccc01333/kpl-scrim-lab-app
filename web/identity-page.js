/* 对局分边与认领：先确定这一局我方在蓝/红哪边，再把两边的昵称认领到选手身份。
   一个昵称一个坑——认错了可以解绑或改绑，不会出现「显示已绑定但下拉是不绑定」。
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

  const membersOf = team => roster.filter(m => (m.team || ownTeam) === team);

  const teamSelect = (camp, current) => `<select class="idp-team" data-team-select="${camp}">
    <option value=""${current ? '' : ' selected'}>选择战队…</option>
    ${draftTeams.map(t => `<option value="${esc(t)}"${t === current ? ' selected' : ''}>${esc(t)}</option>`).join('')}
    <option value="__new__">＋ 新建战队…</option>
  </select>`;

  const playerRow = (match, side, player, index) => {
    const isOwn = side.isOwn;
    const nickname = player.label;
    const boundId = (isOwn ? aliases : enemyAliases)[nickname] || '';
    const options = membersOf(isOwn ? ownTeam : (side.teamName === '对手待填写' ? '' : side.teamName));
    const list = options.length ? options : roster;
    return `<div class="idp-player" data-camp="${side.camp}" data-nick="${esc(nickname)}" data-bound="${boundId ? '1' : '0'}">
      <span class="idp-index">${index + 1}</span>
      <div class="idp-who">
        <strong>${esc(nickname)}</strong>
        <small>${esc(player.hero || '英雄未识别')}${boundId ? ` · 已认领 ${esc(identityOf(roster.find(m => m.id === boundId) || {}, ownTeam))}` : ''}</small>
      </div>
      <select class="idp-bind" data-bind="${esc(nickname)}" data-own="${isOwn ? '1' : '0'}">
        <option value="">未认领</option>
        ${list.map(m => `<option value="${esc(m.id)}"${m.id === boundId ? ' selected' : ''}>${esc(identityOf(m, ownTeam))}${m.position ? ` · ${m.position}` : ''}</option>`).join('')}
        <option value="__new__">＋ 新建选手身份…</option>
      </select>
      <button class="idp-unbind" type="button" data-unbind="${esc(nickname)}" data-own="${isOwn ? '1' : '0'}" ${boundId ? '' : 'disabled'} title="解除这条认领">解绑</button>
    </div>`;
  };

  const sideBlock = (match, side) => {
    const current = side.isOwn ? ownTeam : (side.teamName === '对手待填写' ? '' : side.teamName);
    return `<div class="idp-side ${side.isOwn ? 'own' : 'enemy'}" data-side="${side.camp}" data-own="${side.isOwn ? '1' : '0'}">
      <header class="idp-side-head">
        <span class="idp-camp ${side.camp}">${CAMP_NAME[side.camp] || side.camp}${side.side === 'left' ? ' / 左侧' : ' / 右侧'}</span>
        ${teamSelect(side.camp, current)}
        <span class="idp-side-role">${side.isOwn ? '本队' : (current ? '对手' : '待指定')}</span>
      </header>
      <div class="idp-players">
        ${(side.players || []).map((p, i) => playerRow(match, side, p, i)).join('')}
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
        <h1>对局分边与认领</h1>
        <p>先选这一局本队在蓝方还是红方，再给两边填战队、把游戏昵称认领到选手身份。认错了可以解绑或直接改绑。</p>
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
      <span>两边的战队下拉决定「这五个人属于谁」。选错边就把两边的战队对调；昵称认领后显示为「战队.选手名」，同一个人的小号认领到同一身份即可合并。认领与解绑会立即保存。先点「自动认领」让系统跑一遍，存疑的再交给教练。</span>
      <label class="idp-only"><input type="checkbox" id="idp-only-unclaimed"> 只看未认领</label>
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
    const isOwn = side.dataset.own === '1';
    const team = side.querySelector('[data-team-select]').value;
    const pool = team ? membersOf(team) : roster;
    const list = pool.length ? pool : roster;
    side.querySelectorAll('.idp-bind').forEach(select => {
      const value = select.value;
      select.innerHTML = `<option value="">未认领</option>` + list.map(m =>
        `<option value="${esc(m.id)}"${m.id === value ? ' selected' : ''}>${esc(identityOf(m, ownTeam))}${m.position ? ` · ${m.position}` : ''}</option>`).join('')
        + `<option value="__new__">＋ 新建选手身份…</option>`;
    });
    side.querySelector('.idp-side-role').textContent = team === ownTeam ? '本队' : (team ? '对手' : '待指定');
  };

  const applyBind = (row) => {
    if (!row) return;
    const side = row.closest('.idp-side');
    const team = side.querySelector('[data-team-select]').value;
    const isOwn = team === ownTeam;
    const select = row.querySelector('.idp-bind');
    const nick = select.dataset.bind;
    const table = isOwn ? aliases : enemyAliases;
    // 只改当前这一侧的表：同一个昵称可能在不同对局出现在两边。
    if (select.value) table[nick] = select.value;
    else delete table[nick];
  };

  const saveMatch = async (card) => {
    const key = card.dataset.idpKey;
    const sides = [...card.querySelectorAll('.idp-side')].map(side => {
      const team = side.querySelector('[data-team-select]').value;
      return {
        camp: side.dataset.side,
        team,
        own: team === ownTeam,
        binds: [...side.querySelectorAll('.idp-bind')].map(sel => ({
          nick: sel.dataset.bind, value: sel.value,
        })),
      };
    });
    const ownSide = sides.find(side => side.team === ownTeam);
    if (!ownSide) throw Error('两边的战队里必须有一边是「' + ownTeam + '」');
    const other = sides.find(side => side !== ownSide);
    if (other && other.team === ownSide.team) throw Error('两边不能是同一支战队');
    const opponent = other ? (other.team === ownTeam ? '' : other.team) : '';

    await fetch(`/api/studio/match-meta/${encodeURIComponent(key)}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ownCamp: ownSide.camp, opponent: opponent || ''}),
    }).then(async r => { if (!r.ok) throw Error((await r.json()).detail || '保存分边失败'); });

    sides.forEach(side => {
      side.binds.forEach(bind => {
        const table = side.own ? aliases : enemyAliases;
        if (bind.value) table[bind.nick] = bind.value;
        else delete table[bind.nick];
      });
    });
    card.querySelectorAll('.idp-side').forEach(side => {
      const isOwnSide = side.querySelector('[data-team-select]').value === ownTeam;
      side.dataset.own = isOwnSide ? '1' : '0';
      side.classList.toggle('own', isOwnSide);
      side.classList.toggle('enemy', !isOwnSide);
      side.querySelectorAll('.idp-bind').forEach(sel => sel.dataset.own = isOwnSide ? '1' : '0');
      side.querySelectorAll('.idp-unbind').forEach(btn => btn.dataset.own = isOwnSide ? '1' : '0');
    });
  };

  const persist = async () => {
    const payload = {
      ...settings,
      teamName: ownTeam,
      roster,
      aliases,
      enemyAliases,
      teams: draftTeams.filter(t => t !== ownTeam).map(name => {
        const existing = (settings.teams || []).find(t => t.name === name);
        return existing || {id: 'team-' + Math.random().toString(36).slice(2, 9), name, short: '', coach: '', note: ''};
      }),
    };
    const response = await fetch('/api/settings', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    if (!response.ok) throw Error((await response.json().catch(() => ({}))).detail || '保存认领失败');
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
    toast?.('已保存分边与认领');
    await onSaved?.();
    location.reload();
  };

  container.addEventListener('change', (event) => {
    if (event.target.id === 'idp-only-unclaimed') {
      container.classList.toggle('only-unclaimed', event.target.checked);
    }
  }, true);

  container.addEventListener('click', async (event) => {
    const unbind = event.target.closest('[data-unbind]');
    if (unbind) {
      const row = unbind.closest('.idp-player');
      const select = row.querySelector('.idp-bind');
      select.value = '';
      unbind.disabled = true;
      row.querySelector('.idp-who small').textContent = row.querySelector('.idp-who small').textContent.split(' · 已认领')[0];
      row.dataset.bound = '0';
      applyBind(row);
      schedulePersist('已解除认领');
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
      return;
    }

    const bind = event.target.closest('.idp-bind');
    if (bind) {
      const row = bind.closest('.idp-player');
      if (bind.value === '__new__') {
        const side = bind.closest('.idp-side');
        const team = side.querySelector('[data-team-select]').value || ownTeam;
        const nickname = bind.dataset.bind;
        const name = prompt(`新建选手身份（所属战队：${team}）`, nickname);
        if (!name?.trim()) { bind.value = ''; return; }
        const member = {
          id: 'p-' + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3),
          name: name.trim().slice(0, 50), team, position: '', tags: [],
        };
        roster.push(member);
        bind.insertAdjacentHTML('afterbegin',
          `<option value="${esc(member.id)}">${esc(identityOf(member, ownTeam))}</option>`);
        bind.value = member.id;
        toast?.(`已新建 ${identityOf(member, ownTeam)}，记得保存`);
      }
      const btn = row.querySelector('.idp-unbind');
      btn.disabled = !bind.value;
      const hint = row.querySelector('.idp-who small');
      const hero = hint.textContent.split(' · 已认领')[0];
      const member = roster.find(m => m.id === bind.value);
      hint.textContent = member ? `${hero} · 已认领 ${identityOf(member, ownTeam)}` : hero;
      bind.closest('.idp-player').dataset.bound = bind.value ? '1' : '0';
      applyBind(bind.closest('.idp-player'));
      schedulePersist('认领已更新');
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
