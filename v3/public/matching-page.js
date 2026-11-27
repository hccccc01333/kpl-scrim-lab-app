/* 匹配页（route #matching）
   采集进来的只是裸对局：十个游戏名，没有阵营/对手/选手 ID。
   这里先把游戏名挂到选手 ID（规则集优先），再由命中的选手确定红蓝方和对手战队。
   规则集可增删改：同一游戏名以后自动复用；冲突/新号进异常，交给教练挂钩。 */
import { glyph } from './ui-icons.js';

export function createMatchingPage(h) {
  const { esc, API_BASE, icon } = h;
  let root = null;
  let state = null;
  let generation = 0;
  let controller = null;

  /* 红蓝两侧统一按这个分路顺序排：对抗路 → 打野 → 中路 → 发育路 → 游走。
     没标分路的排最后，toSorted 是稳定排序，同档保持原顺序。 */
  const LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
  const laneRank = (position) => {
    const i = LANE_ORDER.indexOf(String(position || '').trim());
    return i < 0 ? LANE_ORDER.length : i;
  };
  /* 选手档案里的位置写法可能与对局采到的不一致（上路/射手/辅助…），
     按位置自动挂 ID 前先归一到五个标准分路，避免同义写法漏匹配。 */
  const LANE_ALIASES = {
    '上路': '对抗路', '上单': '对抗路', '对抗': '对抗路', 'top': '对抗路',
    '野': '打野', 'jungle': '打野', 'mid': '中路',
    '射手': '发育路', '下路': '发育路', '发育': '发育路', 'adc': '发育路',
    '辅助': '游走', '辅': '游走', 'support': '游走',
  };
  const laneKey = (position) => {
    const text = String(position || '').trim();
    return LANE_ALIASES[text] || LANE_ALIASES[text.toLowerCase()] || text;
  };
  /* 这几种置信度都是系统猜的：教练点「确认」后转成 manual，才算复核过。 */
  const AUTO_CONFIDENCES = new Set(['rule', 'pool', 'name', 'position']);
  const SOURCE_LABELS = { rule: '规则自动', pool: '昵称池', name: '同名匹配', position: '按位置' };

  const json = async (path, options) => {
    const response = await fetch(`${API_BASE}/api${path}`, {
      cache: 'no-store', signal: controller?.signal, ...(options || {}),
    });
    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      try { const body = await response.json(); message = body.detail || message; } catch {}
      throw new Error(message);
    }
    return response.json();
  };

  async function bootstrap() {
    const current = ++generation;
    controller?.abort();
    controller = new AbortController();
    root.innerHTML = '<div class="mb-loading">正在读取对局、本队选手、对方战队与规则集…</div>';
    try {
      const [vectors, workspace, wsPlayers, identity, pool, rules, meta, savedMatches] = await Promise.all([
        json('/cross/vectors'),
        // 归档/合并过的战队卡仍被历史匹配关系引用，必须一起取回，
        // 否则已确认的对手会被误判成未确认，teamLabel 还会显示裸 ID。
        json('/studio/workspace/teams?include_archived=true'),
        json('/studio/workspace/players'),
        json('/v3/identity/players'),
        json('/studio/workspace/nickname-pool'),
        json('/studio/matching/rules'),
        json('/studio/match-meta'),
        /* 老版本后端没有这个读回接口：拿不到就退回原规则推断，不让整页打不开。 */
        json('/studio/matching/players').catch(() => ({ rows: [] })),
      ]);
      if (current !== generation) return;
      /* 本队战队也在 teams 主数据里，但它不是对手：匹配页的对方战队下拉、
         对手候选选手都不能把它算进去，否则会把本队 ID 挂成对手。 */
      const ownTeamId = String(workspace.ownTeamId || '');
      const wsTeams = (workspace.teams || [])
        .filter((t) => String(t.id || '') !== ownTeamId);
      const teamNames = Object.fromEntries(wsTeams.map((t) => [t.id, t.name]));
      /* 本队候选：只认「本队」里的选手 ID，不把其他战队倒进这个下拉框。 */
      const ownCandidates = (identity.players || []).map((p) => ({
        id: p.id, name: p.name || p.campUserId || p.id,
        campUserId: p.campUserId || '', teamId: p.teamId || '',
        teamName: '本队', position: p.position || '', source: 'own',
      }));
      /* 对手候选：按对方战队页的战队卡分组；没选战队时这个下拉框不给人。 */
      const enemyByTeam = {};
      (wsPlayers.players || []).forEach((p) => {
        const key = p.team_id || '';
        if (key && key === ownTeamId) return;   // 本队选手不进对手候选
        (enemyByTeam[key] = enemyByTeam[key] || []).push({
          id: p.id, name: p.name || p.camp_user_id || p.id,
          campUserId: p.camp_user_id || '', teamId: key,
          teamName: teamNames[key] || '对手战队', position: p.position || '', source: 'enemy',
        });
      });
      const nickVotes = {};
      (pool.rows || []).forEach((row) => {
        const side = row.side === 'own' || row.side === 'enemy' ? row.side : '';
        const nickname = String(row.nickname || '').trim();
        const id = String(row.player_id || '').trim();
        if (!side || !nickname || !id) return;
        const key = `${side}|${nickname}`;
        nickVotes[key] = nickVotes[key] || {};
        nickVotes[key][id] = (nickVotes[key][id] || 0) + 1;
      });
      const games = (vectors.vectors || []).map((vector) => {
        const ownCamp = vector.camp === 'red' ? 'red' : 'blue';
        const sides = { blue: [], red: [] };
        (vector.pl || []).forEach((p) => {
          const camp = p.camp === 'red' ? 'red' : 'blue';
          const side = camp === ownCamp ? 'own' : 'enemy';
          sides[camp].push({
            name: String(p.name || '').trim(), camp, side,
            slot: sides[camp].length, position: p.pos || '', hero: p.hero || '',
            playerId: '', teamId: '', confidence: '',
          });
        });
        return {
          key: String(vector.key || ''), date: vector.date || '', clock: vector.clock || '',
          opponent: vector.opponent || '', opponentTeamId: vector.opponentTeamId || '',
          result: vector.result || '', ownCamp, sides,
          enemyTeamId: vector.opponentTeamId && teamNames[vector.opponentTeamId]
            ? vector.opponentTeamId : '', teamAuto: false, teamConflict: false, dirty: false,
          archived: Boolean(meta?.meta?.[String(vector.key || '')]?.matchingArchived),
          editing: false, editBackup: null,
        };
      });
      /* 归档局读回保存时落库的十人匹配。更新后战队改名/ID 变化、规则失效、
         昵称池重建，都不能把已经对上的对手一侧重新变成待匹配。
         用 confidence='saved' 标记为历史记录：applyRulesAll 不重算这些行。 */
      const savedBySlot = new Map();
      (savedMatches?.rows || []).forEach((row) => {
        if (!row?.matchKey || !row?.playerId) return;
        savedBySlot.set(`${row.matchKey}|${row.side}|${row.slot}`, row);
      });
      games.forEach((game) => {
        if (!game.archived) return;
        Object.values(game.sides).flat().forEach((row) => {
          const saved = savedBySlot.get(`${game.key}|${row.camp}|${row.slot}`);
          if (!saved) return;
          row.playerId = String(saved.playerId);
          row.teamId = String(saved.teamId || '');
          row.confidence = 'saved';
        });
      });
      state = {
        games, ownCandidates, enemyByTeam, teamNames, wsTeams,
        teamOptions: wsTeams.map((t) => ({ id: t.id,
          name: (t.name || '未命名战队') + (t.status === 'archived' ? '（已归档）' : '') })),
        rules: (rules.rules || []).map((r) => ({ ...r, enabled: Boolean(r.enabled) })),
        nickVotes, selected: games.find((g) => !g.archived)?.key || games[0]?.key || '',
        filter: 'pending', query: '', status: '', ruleTeamFilter: '',
      };
      applyRulesAll(false);
      render();
    } catch (error) {
      if (current !== generation || error.name === 'AbortError') return;
      root.innerHTML = `<section class="mb-error">${glyph('warning', { size: 28 })}<b>读取失败</b><p>${esc(error.message)}</p><button type="button" class="control" data-mb-retry>${glyph('refresh', { size: 18 })}重试</button></section>`;
    }
  }

  /* ── 规则集 ─────────────────────────────────────────────────────── */
  function ruleFor(side, nickname, scope) {
    if (!state) return null;
    return state.rules.find((r) => r.enabled && r.side === side
      && r.nickname === nickname && (r.scope || '') === (scope || ''));
  }

  function candidatesFor(side, game) {
    if (side === 'own') return state.ownCandidates;
    return game.enemyTeamId ? (state.enemyByTeam[game.enemyTeamId] || []) : [];
  }

  function candidateById(side, id, game) {
    return candidatesFor(side, game).find((p) => p.id === id)
      || (side === 'enemy' ? Object.values(state.enemyByTeam).flat().find((p) => p.id === id) : null)
      || (side === 'own' ? state.ownCandidates.find((p) => p.id === id) : null);
  }

  /* 规则命中优先；规则还没建时，用昵称池的历史投票兜底（不写库）。 */
  function resolveCandidate(row, game) {
    const scope = row.side === 'enemy' ? (game.enemyTeamId || '') : '';
    const rule = ruleFor(row.side, row.name, scope)
      || (row.side === 'enemy' && scope ? ruleFor(row.side, row.name, '') : null);
    if (rule) {
      const exact = candidateById(row.side, rule.playerId, game);
      if (exact) return { player: exact, confidence: 'rule' };
    }
    const votes = state.nickVotes[`${row.side}|${row.name}`] || {};
    const winner = Object.entries(votes).sort((a, b) => b[1] - a[1])[0];
    if (winner) {
      const voted = candidateById(row.side, winner[0], game);
      if (voted) return { player: voted, confidence: 'pool' };
    }
    const exact = candidatesFor(row.side, game).find((p) => p.name === row.name);
    return exact ? { player: exact, confidence: 'name' } : { player: null, confidence: '' };
  }

  function applyRulesAll(markDirty = true) {
    if (!state) return;
    state.games.forEach((game) => {
      Object.values(game.sides).flat().forEach((row) => {
        /* 归档局读回的已保存匹配：规则、候选、战队 ID 怎么变都不重算，
           否则更新之后已归档的 10/10 会退回 5/10。 */
        if (row.confidence === 'saved') return;
        /* 人工复核过、或刚按位置填好的 ID，只要仍属于当前可选范围就保留，
           别让规则重算把位置匹配当成「没命中规则」清空。 */
        if (row.playerId && (row.confidence === 'manual' || row.confidence === 'position')
          && candidatesFor(row.side, game).some((p) => p.id === row.playerId)) return;
        const { player, confidence } = resolveCandidate(row, game);
        if (!player) {
          if (row.playerId && confidence !== 'manual') {
            row.playerId = ''; row.teamId = ''; row.confidence = '';
            if (markDirty) game.dirty = true;
          }
          return;
        }
        if (row.playerId !== player.id || row.teamId !== player.teamId) {
          row.playerId = player.id; row.teamId = player.teamId; row.confidence = confidence;
          if (markDirty) game.dirty = true;
        }
      });
      const enemyRows = (game.sides.blue || []).concat(game.sides.red || [])
        .filter((r) => r.side === 'enemy');
      const matched = enemyRows.filter((r) => r.playerId);
      game.teamAuto = false;
      game.teamConflict = false;
      if (enemyRows.length && matched.length === enemyRows.length) {
        const teamIds = new Set(matched.map((r) => r.teamId).filter(Boolean));
        if (teamIds.size === 1) {
          const id = [...teamIds][0];
          if (id && (!game.enemyTeamId || game.enemyTeamId === id)) {
            game.enemyTeamId = id; game.teamAuto = true;
            if (markDirty) game.dirty = true;
          }
        } else if (teamIds.size > 1) {
          game.teamConflict = true;
        }
      }
    });
  }

  function upsertRule(rule) {
    const index = state.rules.findIndex((r) => r.id === rule.id);
    if (index >= 0) state.rules[index] = { ...rule, enabled: Boolean(rule.enabled) };
    else state.rules.push({ ...rule, enabled: Boolean(rule.enabled) });
  }

  async function persistRule(row, game) {
    if (!row.playerId) return;
    const side = row.side;
    const teamId = side === 'enemy' ? (game.enemyTeamId || row.teamId || '') : '';
    const payload = {
      side, nickname: row.name, playerId: row.playerId, teamId,
      scope: side === 'enemy' ? (game.enemyTeamId || '') : '',
      enabled: true, notes: '匹配页人工确认',
    };
    try {
      const body = await json('/studio/matching/rules', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      upsertRule(body.rule);
      state.status = `已把「${row.name}」挂到 ${row.playerId}，同名对局会自动复用。`;
      applyRulesAll(true);
      render();
    } catch (error) {
      state.status = `规则保存失败：${error.message}`;
      render();
    }
  }

  /* 选定对手战队后，把这支队按分路填进对手一侧的五个位置。
     已经人工复核（manual）的行不动；同一位置有多个候选时取第一个并在
     状态里提醒教练复核，不静默选人。 */
  function autoMatchByPosition(game) {
    if (!game || !game.enemyTeamId || (game.archived && !game.editing)) {
      return { filled: 0, ambiguous: 0 };
    }
    const pools = {};
    (state.enemyByTeam[game.enemyTeamId] || []).forEach((p) => {
      const key = laneKey(p.position);
      if (key) (pools[key] = pools[key] || []).push(p);
    });
    let filled = 0;
    let ambiguous = 0;
    Object.values(game.sides).flat().forEach((row) => {
      if (row.side !== 'enemy' || row.confidence === 'manual' || row.confidence === 'saved') return;
      const pool = pools[laneKey(row.position)] || [];
      if (!pool.length) return;
      if (pool.length > 1) ambiguous += 1;
      const pick = pool.find((p) => p.name === row.name) || pool[0];
      if (row.playerId === pick.id && row.teamId === pick.teamId) return;
      row.playerId = pick.id;
      row.teamId = pick.teamId;
      row.confidence = 'position';
      game.dirty = true;
      filled += 1;
    });
    return { filled, ambiguous };
  }

  function clearEnemyIds(game) {
    let cleared = 0;
    Object.values(game.sides).flat().forEach((row) => {
      if (row.side !== 'enemy' || !row.playerId) return;
      row.playerId = ''; row.teamId = ''; row.confidence = '';
      cleared += 1;
    });
    return cleared;
  }

  function reviewPending(game) {
    return Object.values(game.sides).flat()
      .filter((row) => row.playerId && AUTO_CONFIDENCES.has(row.confidence)).length;
  }
  function reviewTotal() {
    return state ? state.games.reduce((n, game) => n + reviewPending(game), 0) : 0;
  }

  /* 一行的匹配来源 + 复核按钮：自动挂上的 ID 都要教练点一下才算数。 */
  function matchMetaHtml(game, camp, row) {
    if (!row.playerId) return '<span class="mb-src is-blank">待匹配</span>';
    if (row.confidence === 'manual' || row.confidence === 'saved') return '<span class="mb-src is-done">✓ 已复核</span>';
    if (!AUTO_CONFIDENCES.has(row.confidence)) return '';
    return `<span class="mb-src is-${esc(row.confidence)}">${SOURCE_LABELS[row.confidence] || '自动'}</span>`
      + `<button type="button" class="mb-confirm" data-mb-confirm-row="${esc(game.key)}" data-mb-camp="${camp}" data-mb-slot="${row.slot}"`
      + ` aria-label="确认 ${esc(row.name)} 匹配到 ${esc(row.playerId)}" title="确认这条自动匹配">✓ 确认</button>`;
  }

  /* ── 展示 ───────────────────────────────────────────────────────── */
  function visibleGames() {
    if (!state) return [];
    const query = state.query.toLocaleLowerCase('zh-CN');
    /* 待匹配对局按对局时间从早到晚排。date 是 YYYY-MM-DD、clock 是 HH:MM，
       拼起来就是可字符串比较的本地墙上时间（无时区偏移）。 */
    const byTime = (a, b) => {
      const ka = `${a.date || ''} ${a.clock || ''}`.trim();
      const kb = `${b.date || ''} ${b.clock || ''}`.trim();
      if (!ka) return 1;
      if (!kb) return -1;
      return ka.localeCompare(kb);
    };
    /* toSorted 不改动 state.games，避免影响 selected 等按原顺序建立的引用；
       老浏览器没有 toSorted 时退回 slice().sort()。 */
    const filtered = state.games.filter((game) => {
      const rows = (game.sides.blue || []).concat(game.sides.red || []);
      /* 「待匹配」= 还没保存归档；「已匹配」= 已保存归档、默认只读。 */
      if (state.filter === 'pending' && game.archived) return false;
      if (state.filter === 'matched' && !game.archived) return false;
      if (!query) return true;
      return `${game.date} ${game.opponent} ${rows.map((r) => r.name).join(' ')}`
        .toLocaleLowerCase('zh-CN').includes(query);
    });
    return filtered.toSorted ? filtered.toSorted(byTime) : filtered.slice().sort(byTime);
  }

  function derived(game) {
    const rows = (game.sides.blue || []).concat(game.sides.red || []);
    const matched = rows.filter((r) => r.playerId).length;
    const ownRows = rows.filter((r) => r.side === 'own' && r.playerId);
    const enemyCounts = {};
    rows.filter((r) => r.side === 'enemy' && r.teamId).forEach((r) => {
      enemyCounts[r.teamId] = (enemyCounts[r.teamId] || 0) + 1;
    });
    const top = Object.entries(enemyCounts).sort((a, b) => b[1] - a[1])[0];
    const ownSide = ownRows.length >= 3 ? (ownRows[0]?.camp === 'blue' ? '蓝方' : '红方') : null;
    const alerts = rows.filter((r) => rowAlert(game, r)).length + (game.teamConflict ? 1 : 0);
    return { matched, total: rows.length, ownSide, alerts,
      enemyVote: top ? `${state.teamNames[top[0]] || top[0]} · ${top[1]}/5` : null };
  }

  /* 可保存/归档的局：有未保存改动，或十人全匹配且没有异常但还没归档。 */
  function saveTargets() {
    if (!state) return [];
    return state.games.filter((game) => {
      if (game.dirty || game.editing) return true;
      if (game.archived) return false;
      const info = derived(game);
      return info.matched === info.total && info.alerts === 0;
    });
  }

  function rowAlert(game, row) {
    if (!row.playerId) return '';
    if (row.side === 'enemy' && game.enemyTeamId && row.teamId
      && row.teamId !== game.enemyTeamId) return 'ID 不属于所选战队';
    const ids = new Set();
    state.games.forEach((g) => (g.sides.blue || []).concat(g.sides.red || []).forEach((r) => {
      if (r.side === row.side && r.name === row.name && r.playerId) ids.add(r.playerId);
    }));
    if (ids.size > 1) return '同名出现多个 ID';
    return '';
  }

  function teamLabel(id) {
    if (!id) return '未确定';
    return state.teamNames[id] || state.teamOptions.find((t) => t.id === id)?.name || id;
  }

  function playerOptions(side, currentId, game) {
    if (side === 'enemy' && !game.enemyTeamId) {
      return '<option value="">先确认对手战队，才能选对手选手 ID</option>';
    }
    const list = candidatesFor(side, game);
    const groups = {};
    list.forEach((p) => {
      const label = side === 'own' ? '本队选手' : (p.teamName || '对手战队');
      (groups[label] = groups[label] || []).push(p);
    });
    const body = Object.entries(groups).map(([label, members]) => {
      const options = members.map((p) => `<option value="${esc(p.id)}"${p.id === currentId ? ' selected' : ''}>${esc(p.name)}${p.campUserId ? ` · ID ${esc(p.campUserId)}` : ''}${p.position ? ` · ${esc(p.position)}` : ''}</option>`).join('');
      return `<optgroup label="${esc(label)}">${options}</optgroup>`;
    }).join('');
    return `<option value=""${currentId ? '' : ' selected'}>— 未匹配 —</option>${body}`;
  }

  function renderList(games) {
    if (!games.length) return `<div class="mb-blank">${glyph('matches', { size: 28 })}<b>没有符合条件的对局</b></div>`;
    return games.map((game) => {
      const info = derived(game);
      return `<button type="button" class="mb-game${game.key === state.selected ? ' is-active' : ''}" data-mb-game="${esc(game.key)}" aria-current="${game.key === state.selected ? 'true' : 'false'}">
        <span class="mb-game-top"><b>${esc(game.date || '未知日期')} ${esc(game.clock || '')}</b><em class="mb-result is-${esc(game.result || 'unknown')}">${game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</em></span>
        <span class="mb-game-sub">${esc(game.opponent || teamLabel(game.enemyTeamId))}${game.archived ? ' · 已归档' : game.dirty ? ' · 待保存' : ''}</span>
        <span class="mb-game-meter"><i style="inline-size:${Math.round(info.matched / Math.max(1, info.total) * 100)}%"></i></span>
        <small>${info.matched}/${info.total} 已匹配${info.alerts ? ` · ${info.alerts} 处异常` : ''}${game.archived ? ' · 只读' : ''}</small>
      </button>`;
    }).join('');
  }

  function renderDetail(game) {
    if (!game) return `<div class="mb-blank">${glyph('players', { size: 28 })}<b>选一局开始匹配</b></div>`;
    const info = derived(game);
    const locked = game.archived && !game.editing;
    const teamOptions = state.teamOptions.map((t) => `<option value="${esc(t.id)}"${t.id === game.enemyTeamId ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
    const campBlock = (camp) => {
      const role = camp === game.ownCamp ? 'own' : 'enemy';
      const rows = game.sides[camp] || [];
      /* 只排展示顺序，不改 rows 本身：row.slot 是 change/save 用来定位原始行的索引。 */
      const ordered = rows.toSorted
        ? rows.toSorted((a, b) => laneRank(a.position) - laneRank(b.position))
        : rows.slice().sort((a, b) => laneRank(a.position) - laneRank(b.position));
      const rowsHtml = ordered.map((row) => {
        const alert = rowAlert(game, row);
        return `<tr class="${alert ? 'is-alert' : ''}">
          <th scope="row"><span class="mb-pos">${esc(row.position || '—')}</span></th>
          <td><b class="mb-nick">${esc(row.name)}</b><small>${esc(row.hero || '')}</small></td>
          <td><div class="mb-match-cell">
            <select data-mb-player="${esc(game.key)}" data-mb-camp="${camp}" data-mb-slot="${row.slot}" aria-label="把 ${esc(row.name)} 匹配到选手 ID"${locked ? ' disabled' : ''}>${playerOptions(role, row.playerId, game)}</select>
            <span class="mb-match-meta">${matchMetaHtml(game, camp, row)}${alert ? `<span class="mb-alert" role="status">${esc(alert)}</span>` : ''}</span>
          </div></td>
          <td><span class="mb-dot${row.playerId ? ' is-on' : ''}" title="${row.playerId ? '已匹配' : '待匹配'}"></span></td>
        </tr>`;
      }).join('');
      return `<section class="mb-side">
        <header><b>${camp === 'blue' ? '蓝方' : '红方'}</b><span>${role === 'own' ? '本队一侧 · 本队选手 ID' : '对手一侧 · 所选战队 ID'}</span></header>
        <div class="mb-table-wrap" role="region" tabindex="0" aria-label="${camp === 'blue' ? '蓝方' : '红方'}选手匹配">
          <table class="mb-table"><thead><tr><th scope="col">位置</th><th scope="col">游戏名</th><th scope="col">选手 ID</th><th scope="col">状态</th></tr></thead><tbody>${rowsHtml}</tbody></table>
        </div>
      </section>`;
    };
    return `<div class="mb-detail-head${locked ? ' is-locked' : ''}">
        <div><span class="mb-eyebrow">对局 ${esc(game.date || '')} ${esc(game.clock || '')}</span><h2>${esc(game.opponent || '未标注对手')}</h2>
          ${game.archived ? `<span class="mb-lock-badge">${locked ? '已归档 · 只读' : '编辑中'}</span>` : ''}</div>
        <div class="mb-detail-actions">
          <span class="mb-detail-score">${info.matched}/${info.total} 已匹配${info.alerts ? ` · ${info.alerts} 处异常` : ''}</span>
          ${game.archived ? (locked
            ? `<button type="button" class="control" data-mb-edit>${glyph('edit', { size: 18 })}编辑</button>`
            : `<button type="button" class="control" data-mb-cancel-edit>${glyph('ban', { size: 18 })}取消编辑</button>`) : ''}
        </div>
      </div>
      <div class="mb-derived">
        <div><span>我方阵营</span><b data-derived="camp">${esc(info.ownSide || '待选手匹配后确定')}</b></div>
        <div><span>对手战队（按命中选手推导）</span><b data-derived="enemy">${esc(game.teamAuto ? `规则自动确认 · ${teamLabel(game.enemyTeamId)}` : info.enemyVote || '待确定')}</b></div>
        <label><span>手动确认对手战队${game.teamAuto ? '（规则已 5/5 命中，可覆盖）' : ''}</span><select data-mb-team="${esc(game.key)}" aria-label="确认这局的对手战队"${locked ? ' disabled' : ''}><option value="">由选手匹配推导</option>${teamOptions}</select></label>
      </div>
      ${game.teamConflict ? '<p class="mb-warning" role="status">对手一侧 5 个 ID 来自不同战队，规则无法自动确认；请教练核对是否换人/换小号。</p>' : ''}
      <div class="mb-sides">${campBlock('blue')}${campBlock('red')}</div>`;
  }

  function renderRules() {
    /* 战队筛选：本队 + 出现在规则/战队目录里的每个对手战队。 */
    const ruleTeams = new Map();
    ruleTeams.set('__own__', '本队');
    state.teamOptions.forEach((t) => ruleTeams.set(t.id, t.name));
    state.rules.forEach((rule) => {
      const value = ruleTeamValue(rule);
      if (value && value !== '__own__' && !ruleTeams.has(value)) ruleTeams.set(value, teamLabel(value));
    });
    const teamFilterOptions = [...ruleTeams.entries()]
      .map(([value, name]) => `<option value="${esc(value)}"${value === state.ruleTeamFilter ? ' selected' : ''}>${esc(name)}</option>`).join('');
    const visibleRules = state.ruleTeamFilter
      ? state.rules.filter((rule) => ruleTeamValue(rule) === state.ruleTeamFilter)
      : state.rules;
    const rows = visibleRules.map((rule) => `<tr>
      <th scope="row">${rule.side === 'own' ? '本队' : '对手'}</th>
      <td class="mb-rule-map" aria-label="游戏名 ${esc(rule.nickname)} 对应选手 ${esc(playerName(rule.playerId))}，ID ${esc(rule.playerId)}">
        <b>${esc(rule.nickname)}</b>
        <span class="mb-rule-arrow" aria-hidden="true">→</span>
        <span class="mb-rule-person">${esc(playerName(rule.playerId))}</span>
        <small>ID ${esc(rule.playerId)}</small>
      </td>
      <td>${esc(rule.scope ? teamLabel(rule.scope) : rule.teamId ? teamLabel(rule.teamId) : '—')}</td>
      <td>${rule.enabled ? '启用' : '停用'}</td>
      <td class="mb-rule-ops"><button type="button" class="control" data-mb-rule-edit="${esc(rule.id)}">${glyph('edit', { size: 18 })}编辑</button>
        <button type="button" class="control is-danger" data-mb-rule-del="${esc(rule.id)}" aria-label="删除规则 ${esc(rule.nickname)} 对应 ${esc(playerName(rule.playerId))}">${glyph('trash', { size: 18 })}删除</button></td>
    </tr>`).join('');
    return `<section class="mb-rules" aria-labelledby="mb-rules-caption">
      <div class="mb-rules-head"><div><h2 id="mb-rules-caption">匹配规则集</h2></div>
        <div class="mb-rule-tools">
          <label class="mb-rule-filter"><span>战队筛选</span><select data-mb-rule-team-filter aria-label="按战队筛选匹配规则">
            <option value="">全部战队</option>${teamFilterOptions}
          </select></label>
          <button type="button" class="mb-primary" data-mb-rule-add>${glyph('edit', { size: 18 })}新增规则</button>
        </div></div>
      <div class="mb-rule-wrap" role="region" tabindex="0" aria-labelledby="mb-rules-caption">
        <table class="mb-rule-table"><thead><tr><th scope="col">阵营</th><th scope="col">游戏名 → 对应选手</th><th scope="col">限定战队</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5" class="mb-blank">${state.ruleTeamFilter ? '该战队还没有规则。切到「全部战队」查看其它队伍。' : '还没有规则。手动确认一次匹配后会自动生成。'}</td></tr>`}</tbody></table>
      </div>
      <dialog class="mb-dialog" data-mb-rule-dialog aria-labelledby="mb-rule-title"></dialog>
      <dialog class="mb-dialog mb-dialog-sm" data-mb-rule-confirm aria-labelledby="mb-confirm-title">
        <h2 id="mb-confirm-title">删除规则</h2><p data-mb-confirm-text></p>
        <div class="mb-dialog-actions"><button type="button" class="control" data-mb-rule-close autofocus>${glyph('ban', { size: 18 })}取消</button>
          <button type="button" class="control is-danger" data-mb-rule-confirm-ok>${glyph('trash', { size: 18 })}确认删除</button></div>
      </dialog>
    </section>`;
  }

  function render() {
    if (!state || !root) return;
    /* render() 会整体重建 root.innerHTML，.mb-list 这个滚动容器也跟着被换掉，
       scrollTop 归零——往下滚动点某局时人会「弹回顶部」。重建前记下位置，
       重建后还原，点选对局就停在原地。切换筛选时由调用方显式清零。 */
    const listScroll = root.querySelector('.mb-list')?.scrollTop || 0;
    const games = visibleGames();
    if (!games.some((g) => g.key === state.selected)) state.selected = games[0]?.key || '';
    const pending = state.games.reduce((n, g) => n + (g.sides.blue || []).concat(g.sides.red || []).filter((r) => !r.playerId).length, 0);
    const pendingGames = state.games.filter((g) => !g.archived).length;
    const doneGames = state.games.length - pendingGames;
    const dirty = state.games.filter((g) => g.dirty).length;
    const alerts = state.games.reduce((n, g) => n + derived(g).alerts, 0);
    const targets = saveTargets().length;
    const currentGame = state.games.find((g) => g.key === state.selected);
    const canAuto = Boolean(currentGame?.enemyTeamId && (!currentGame.archived || currentGame.editing));
    const reviewing = reviewTotal();
    root.innerHTML = `<section class="mb-page">
      <header class="mb-head"><h1>匹配</h1></header>
      <ol class="mb-guide" aria-label="匹配流程">
        <li><b>1</b><span>选一局对局</span></li>
        <li><b>2</b><span>确认对手战队 · ID 按位置自动填</span></li>
        <li><b>3</b><span>复核标记 → 保存归档</span></li>
      </ol>
      <div class="mb-stats">
        <div><span>待配对局</span><b>${pendingGames}</b></div>
        <div><span>已归档对局</span><b>${doneGames}</b></div>
        <div><span>未匹配游戏名</span><b>${pending}</b></div>
        <div><span>待复核 ID</span><b data-mb-stat-review>${reviewing}</b></div>
        <div><span>异常待确认</span><b>${alerts}</b></div>
        <div><span>待保存改动</span><b data-mb-stat-dirty>${dirty}</b></div>
      </div>
      <div class="mb-body">
        <div class="mb-toolbar">
          <div class="mb-filters" role="group" aria-label="按匹配状态筛选">
            ${[['pending', '待匹配', 'clock'], ['matched', '已匹配', 'victory']].map(([key, label, ico]) => `<button type="button" data-mb-filter="${key}" aria-pressed="${state.filter === key}">${glyph(ico, { size: 18 })}${label}</button>`).join('')}
          </div>
          <label class="mb-search"><span>搜索对局 / 游戏名</span><input type="search" data-mb-query value="${esc(state.query)}" autocomplete="off" autocorrect="off" spellcheck="false"></label>
          <button type="button" class="mb-tool" data-mb-autofill${canAuto ? '' : ' disabled'} title="按对手战队选手的分路，把这局对手一侧的 ID 自动填好">${glyph('refresh', { size: 18 })}按位置匹配</button>
          <button type="button" class="mb-tool mb-review" data-mb-review${reviewing ? '' : ' disabled'} title="逐条定位自动匹配、等待教练确认的 ID">${glyph('shield', { size: 18 })}复核 <b data-mb-review-count>${reviewing}</b></button>
          <button type="button" class="mb-primary mb-save" data-mb-save${targets ? '' : ' disabled'}>${glyph('export', { size: 20 })}<span>保存并归档${targets ? `（${targets} 局）` : ''}</span></button>
        </div>
        <p class="mb-status" role="status">${esc(state.status || '')}</p>
        <div class="mb-workspace">
          <div class="mb-list-wrap"><div class="mb-list-head">${state.filter === 'matched' ? '已归档对局' : '待匹配对局'} <span>${games.length} 局</span></div><div class="mb-list">${renderList(games)}</div></div>
          <div class="mb-detail" data-mb-detail>${renderDetail(state.games.find((g) => g.key === state.selected) || games[0])}</div>
        </div>
        ${renderRules()}
      </div>
    </section>`;
    const list = root.querySelector('.mb-list');
    if (list) list.scrollTop = listScroll;
  }

  function refreshDerived() {
    const game = state.games.find((g) => g.key === state.selected);
    if (!game || !root) return;
    const info = derived(game);
    const camp = root.querySelector('[data-derived="camp"]');
    if (camp) camp.textContent = info.ownSide || '待选手匹配后确定';
    const enemy = root.querySelector('[data-derived="enemy"]');
    if (enemy) enemy.textContent = game.teamAuto
      ? `规则自动确认 · ${teamLabel(game.enemyTeamId)}` : info.enemyVote || '待确定';
    const save = root.querySelector('[data-mb-save]');
    const targets = saveTargets().length;
    if (save) {
      save.disabled = !targets;
      save.innerHTML = `${glyph('export', { size: 20 })}<span>保存并归档${targets ? `（${targets} 局）` : ''}</span>`;
    }
  }

  /* 复核一条后只更新计数，不整页重绘，避免焦点和列表滚动位置丢失。 */
  function refreshReviewUi() {
    const total = reviewTotal();
    const stat = root?.querySelector('[data-mb-stat-review]');
    if (stat) stat.textContent = String(total);
    const count = root?.querySelector('[data-mb-review-count]');
    if (count) count.textContent = String(total);
    const button = root?.querySelector('[data-mb-review]');
    if (button) button.disabled = !total;
    const dirtyNode = root?.querySelector('[data-mb-stat-dirty]');
    if (dirtyNode) dirtyNode.textContent = String(state.games.filter((g) => g.dirty).length);
  }

  function distinctNicknames(side) {
    const names = new Set();
    state.games.forEach((game) => (game.sides.blue || []).concat(game.sides.red || [])
      .forEach((row) => { if (row.side === side && row.name) names.add(row.name); }));
    return [...names].sort((a, b) => a.localeCompare(b, 'zh'));
  }

  function ruleTeamValue(rule) {
    if (!rule) return '__own__';
    return rule.side === 'enemy' ? (rule.teamId || rule.scope || '') : '__own__';
  }

  /* 规则表只显示选手档案里的名字：那边改名，这里刷新后就跟着改。
     找不到档案才退回 ID，不做任何自行拼接。 */
  function playerName(id) {
    if (!id) return '—';
    const all = [...state.ownCandidates, ...Object.values(state.enemyByTeam).flat()];
    return all.find((p) => p.id === id)?.name || id;
  }

  function refreshRuleOptions(dialog, rule, preservePlayer = true) {
    const teamSelect = dialog.querySelector('#mb-rule-team');
    const nickSelect = dialog.querySelector('#mb-rule-nick');
    const playerSelect = dialog.querySelector('#mb-rule-player');
    if (!teamSelect || !nickSelect || !playerSelect) return;
    const value = teamSelect.value;
    const side = value === '__own__' ? 'own' : 'enemy';
    const teamId = side === 'enemy' ? value : '';
    const keepNick = rule?.nickname || nickSelect.value;
    /* 换战队时不能把上一支战队的 ID 带过去，否则看起来像没筛选。 */
    const keepPlayer = preservePlayer ? (rule?.playerId || playerSelect.value) : '';
    const names = distinctNicknames(side);
    if (keepNick && !names.includes(keepNick)) names.unshift(keepNick);
    nickSelect.innerHTML = `<option value="" disabled selected>${names.length ? '先选游戏名' : '这侧还没有采集到游戏名'}</option>`
      + names.map((n) => `<option value="${esc(n)}"${n === keepNick ? ' selected' : ''}>${esc(n)}</option>`).join('');
    const list = [...(side === 'own' ? state.ownCandidates : (state.enemyByTeam[teamId] || []))];
    if (keepPlayer && !list.some((p) => p.id === keepPlayer)) {
      list.unshift({ id: keepPlayer, name: keepPlayer, campUserId: '', position: '' });
    }
    playerSelect.innerHTML = `<option value="" disabled${keepPlayer ? '' : ' selected'}>${list.length ? '先选选手 ID' : '这个战队还没有选手 ID，请先在对方战队页建档'}</option>`
      + list.map((p) => `<option value="${esc(p.id)}"${p.id === keepPlayer ? ' selected' : ''}>${esc(p.name)}${p.campUserId ? ` · ID ${esc(p.campUserId)}` : ''}${p.position ? ` · ${esc(p.position)}` : ''}</option>`).join('');
  }

  function openRuleDialog(rule) {
    const dialog = root?.querySelector('[data-mb-rule-dialog]');
    if (!dialog) return;
    const edit = Boolean(rule);
    const selectedTeam = ruleTeamValue(rule);
    const ownSelected = selectedTeam === '__own__' ? ' selected' : '';
    const teamItems = state.teamOptions.map((t) => `<option value="${esc(t.id)}"${selectedTeam === t.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
    dialog.innerHTML = `<form data-mb-rule-form data-rule-id="${esc(rule?.id || '')}" aria-labelledby="mb-rule-title">
      <div class="dialog-head"><div><h2 id="mb-rule-title">${edit ? '编辑匹配规则' : '新增匹配规则'}</h2></div>
        <button type="button" class="head-button" data-mb-rule-close aria-label="关闭">${glyph('ban', { size: 18 })}</button></div>
      <div class="dialog-body">
        <label for="mb-rule-team">① 所属战队 <em>必选</em></label>
        <select id="mb-rule-team" name="teamId" required data-mb-rule-team autofocus>
          <optgroup label="本队"><option value="__own__"${ownSelected}>本队（固定）</option></optgroup>
          <optgroup label="对方战队">${teamItems || '<option value="">暂无对方战队卡</option>'}</optgroup>
        </select>
        <label for="mb-rule-nick">② 游戏名 <em>必选</em></label>
        <select id="mb-rule-nick" name="nickname" required data-mb-rule-nick></select>
        <label for="mb-rule-player">③ 选手 ID <em>必选</em></label>
        <select id="mb-rule-player" name="playerId" required data-mb-rule-player-select></select>
        <label for="mb-rule-notes">④ 备注（可选）</label>
        <input id="mb-rule-notes" name="notes" maxlength="200" value="${esc(rule?.notes || '')}" placeholder="例如：换小号 / 教练确认">
        <label class="mb-check"><input type="checkbox" name="enabled"${!edit || rule?.enabled ? ' checked' : ''}> 启用这条规则</label>
        <p class="mb-form-error" role="alert"></p>
      </div>
      <div class="dialog-actions"><button type="button" class="control" data-mb-rule-close>${glyph('ban', { size: 18 })}取消</button>
        <button type="submit" class="mb-primary">${glyph(edit ? 'pick' : 'edit', { size: 18 })}${edit ? '保存修改' : '新增规则'}</button></div>
    </form>`;
    refreshRuleOptions(dialog, rule);
    dialog.showModal();
    dialog.querySelector('#mb-rule-team')?.focus();
  }

  function closeDialog(target) {
    const dialog = target?.closest('dialog');
    if (dialog?.open) dialog.close();
  }

  function click(event) {
    if (!root || !root.contains(event.target)) return;
    if (event.target.closest('[data-mb-retry]')) { bootstrap(); return; }
    const gameBtn = event.target.closest('[data-mb-game]');
    if (gameBtn) { state.selected = gameBtn.dataset.mbGame; render(); return; }
    const filter = event.target.closest('[data-mb-filter]');
    if (filter) {
      state.filter = filter.dataset.mbFilter;
      render();
      /* 切换筛选后是一批新的对局，列表从头看更符合预期。 */
      const list = root.querySelector('.mb-list');
      if (list) list.scrollTop = 0;
      return;
    }
    if (event.target.closest('[data-mb-edit]')) {
      const game = state.games.find((g) => g.key === state.selected);
      if (!game || !game.archived) return;
      game.editBackup = {
        enemyTeamId: game.enemyTeamId, teamAuto: game.teamAuto,
        rows: Object.values(game.sides).flat().map((r) => ({
          camp: r.camp, slot: r.slot, playerId: r.playerId, teamId: r.teamId, confidence: r.confidence,
        })),
      };
      game.editing = true;
      state.status = '已解锁这一局，改完点保存结果即可重新归档。';
      render();
      return;
    }
    if (event.target.closest('[data-mb-cancel-edit]')) {
      const game = state.games.find((g) => g.key === state.selected);
      if (!game || !game.editBackup) return;
      game.enemyTeamId = game.editBackup.enemyTeamId;
      game.teamAuto = game.editBackup.teamAuto;
      game.editBackup.rows.forEach((saved) => {
        const row = (game.sides[saved.camp] || []).find((r) => String(r.slot) === String(saved.slot));
        if (!row) return;
        row.playerId = saved.playerId; row.teamId = saved.teamId; row.confidence = saved.confidence;
      });
      game.editBackup = null;
      game.editing = false;
      game.dirty = false;
      state.status = '已取消编辑，这一局恢复为只读归档。';
      render();
      return;
    }
    if (event.target.closest('[data-mb-autofill]')) {
      const game = state.games.find((g) => g.key === state.selected);
      if (!game) return;
      const result = autoMatchByPosition(game);
      state.status = game.enemyTeamId
        ? `已按位置填入 ${result.filled} 个对手 ID${result.ambiguous ? `；${result.ambiguous} 个位置有多名候选，请复核` : ''}。确认无误后再保存。`
        : '先在「手动确认对手战队」里选对手，才能按位置匹配。';
      render();
      return;
    }
    if (event.target.closest('[data-mb-review]')) {
      const inFilter = (g) => state.filter === 'matched' ? Boolean(g.archived) : !g.archived;
      let pending = state.games.filter((g) => reviewPending(g) && inFilter(g));
      if (!pending.length) {
        const any = state.games.find((g) => reviewPending(g));
        if (!any) return;
        state.filter = any.archived ? 'matched' : 'pending';
        pending = [any];
      }
      const target = pending.find((g) => g.key === state.selected) || pending[0];
      state.selected = target.key;
      render();
      const first = root.querySelector('[data-mb-confirm-row]');
      state.status = `已定位到 ${target.date || ''} 的待复核 ID（共 ${reviewTotal()} 条），逐条点「✓ 确认」。`;
      const bar = root.querySelector('.mb-status');
      if (bar) bar.textContent = state.status;
      first?.focus();
      return;
    }
    const confirmRow = event.target.closest('[data-mb-confirm-row]');
    if (confirmRow) {
      const game = state.games.find((g) => g.key === confirmRow.dataset.mbConfirmRow);
      if (!game) return;
      const row = (game.sides[confirmRow.dataset.mbCamp] || [])
        .find((r) => String(r.slot) === String(confirmRow.dataset.mbSlot));
      if (!row) return;
      row.confidence = 'manual';
      game.dirty = true;
      const meta = confirmRow.closest('.mb-match-meta');
      if (meta) meta.innerHTML = '<span class="mb-src is-done">✓ 已复核</span>';
      state.status = `已复核「${row.name}」→ ${row.playerId}；还剩 ${reviewTotal()} 条待复核。`;
      const bar = root.querySelector('.mb-status');
      if (bar) bar.textContent = state.status;
      refreshReviewUi();
      (root.querySelector('[data-mb-confirm-row]') || root.querySelector('[data-mb-save]'))?.focus();
      return;
    }
    if (event.target.closest('[data-mb-save]')) { save(); return; }
    if (event.target.closest('[data-mb-rule-add]')) { openRuleDialog(null); return; }
    const ruleEdit = event.target.closest('[data-mb-rule-edit]');
    if (ruleEdit) {
      openRuleDialog(state.rules.find((r) => r.id === ruleEdit.dataset.mbRuleEdit));
      return;
    }
    const ruleDel = event.target.closest('[data-mb-rule-del]');
    if (ruleDel) {
      const rule = state.rules.find((r) => r.id === ruleDel.dataset.mbRuleDel);
      if (!rule) return;
      const dialog = root.querySelector('[data-mb-rule-confirm]');
      dialog.querySelector('[data-mb-confirm-text]').textContent = `确定删除「${rule.nickname} → ${rule.playerId}」这条规则？已保存的对局不会被回改。`;
      const ok = dialog.querySelector('[data-mb-rule-confirm-ok]');
      ok.onclick = async () => {
        dialog.close();
        try {
          await json('/studio/matching/rules/delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: rule.id }),
          });
          state.rules = state.rules.filter((r) => r.id !== rule.id);
          state.status = `已删除规则「${rule.nickname} → ${rule.playerId}」。`;
        } catch (error) {
          state.status = `删除失败：${error.message}`;
        }
        render();
      };
      dialog.showModal();
      dialog.querySelector('[data-mb-rule-close]')?.focus();
      return;
    }
    if (event.target.closest('[data-mb-rule-close]')) { closeDialog(event.target); return; }
  }

  function change(event) {
    if (!root || !root.contains(event.target)) return;
    const filterSelect = event.target.closest('[data-mb-rule-team-filter]');
    if (filterSelect) {
      state.ruleTeamFilter = filterSelect.value || '';
      render();
      return;
    }
    const ruleDialog = event.target.closest('[data-mb-rule-dialog]');
    if (ruleDialog && event.target.matches('[data-mb-rule-team]')) {
      refreshRuleOptions(ruleDialog, null, false);
      return;
    }
    const selector = event.target.closest('[data-mb-player]');
    if (selector) {
      const game = state.games.find((g) => g.key === selector.dataset.mbPlayer);
      if (!game || (game.archived && !game.editing)) return;
      const camp = selector.dataset.mbCamp;
      const row = (game.sides[camp] || []).find((r) => String(r.slot) === selector.dataset.mbSlot);
      if (!row) return;
      const player = candidateById(row.side, selector.value, game);
      row.playerId = player ? player.id : '';
      row.teamId = player ? player.teamId : '';
      row.confidence = 'manual';
      game.dirty = true;
      persistRule(row, game);
      return;
    }
    const teamSelect = event.target.closest('[data-mb-team]');
    if (teamSelect) {
      const game = state.games.find((g) => g.key === teamSelect.dataset.mbTeam);
      if (!game || (game.archived && !game.editing)) return;
      game.enemyTeamId = teamSelect.value;
      game.teamAuto = false;
      game.dirty = true;
      if (!game.enemyTeamId) {
        const cleared = clearEnemyIds(game);
        state.status = `已改为由选手匹配推导对手战队${cleared ? `，清除 ${cleared} 个旧对手 ID` : ''}。`;
        render();
        return;
      }
      /* 换队后旧 ID 不能留：只保留仍属于新战队的匹配，其余交给位置匹配重填。 */
      let kept = 0;
      const roster = state.enemyByTeam[game.enemyTeamId] || [];
      Object.values(game.sides).flat().forEach((row) => {
        if (row.side !== 'enemy' || !row.playerId) return;
        if (roster.some((p) => p.id === row.playerId)) { kept += 1; return; }
        row.playerId = ''; row.teamId = ''; row.confidence = '';
      });
      const auto = autoMatchByPosition(game);
      applyRulesAll(true);
      state.status = `已确认对手「${teamLabel(game.enemyTeamId)}」：按位置填入 ${auto.filled} 个 ID${kept ? `、保留 ${kept} 个原匹配` : ''}${auto.ambiguous ? `；${auto.ambiguous} 个位置有多名候选，请复核` : ''}。`;
      render();
    }
  }

  async function submit(event) {
    const form = event.target.closest('[data-mb-rule-form]');
    if (!form || !root?.contains(form)) return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const teamValue = String(data.teamId || '');
    const side = teamValue === '__own__' ? 'own' : 'enemy';
    const teamId = side === 'enemy' ? teamValue : '';
    const error = !teamValue ? '请先选择所属战队。'
      : !String(data.nickname || '').trim() ? '请先选择游戏名。'
      : !String(data.playerId || '').trim() ? '请先选择选手 ID。' : '';
    const box = form.querySelector('.mb-form-error');
    if (box) box.textContent = error;
    if (error) return;
    const payload = {
      id: form.dataset.ruleId || '', side, nickname: String(data.nickname).trim(),
      playerId: String(data.playerId).trim(), teamId,
      scope: side === 'enemy' ? teamId : '',
      enabled: Boolean(data.enabled), notes: data.notes || '',
    };
    try {
      const body = await json('/studio/matching/rules', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      upsertRule(body.rule);
      closeDialog(form);
      state.status = `规则「${payload.nickname} → ${payload.playerId}」已保存。`;
      applyRulesAll(true);
    } catch (err) {
      if (box) box.textContent = err.message || '保存失败';
      return;
    }
    render();
  }

  function input(event) {
    if (!root || !root.contains(event.target) || !event.target.matches('[data-mb-query]')) return;
    state.query = event.target.value || '';
    const list = root.querySelector('.mb-list');
    if (list) list.innerHTML = renderList(visibleGames());
    const head = root.querySelector('.mb-list-head span');
    if (head) head.textContent = `${visibleGames().length} 局`;
  }

  async function save() {
    const targets = saveTargets();
    if (!targets.length) return;
    const button = root.querySelector('[data-mb-save]');
    if (button) button.disabled = true;
    state.status = '正在保存…';
    const status = root.querySelector('.mb-status');
    if (status) status.textContent = state.status;
    try {
      const playerRows = [];
      const teamRows = [];
      targets.forEach((game) => {
        (game.sides.blue || []).concat(game.sides.red || []).forEach((row) => playerRows.push({
          matchKey: game.key, side: row.camp, role: row.side, slot: row.slot,
          name: row.name, position: row.position, hero: row.hero,
          playerId: row.playerId, teamId: row.teamId, ownCamp: game.ownCamp,
        }));
        teamRows.push({
          matchKey: game.key, ownTeamId: '', enemyTeamId: game.enemyTeamId,
          ownCamp: game.ownCamp, opponentName: game.opponent,
        });
      });
      await json('/studio/matching/players', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows: playerRows }),
      });
      if (teamRows.some((row) => row.enemyTeamId || row.ownCamp)) {
        await json('/studio/matching/teams', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rows: teamRows }),
        });
      }
      /* 只有十人全匹配、没有异常的局才归档；未完成的仍留在待匹配里。 */
      const archiveKeys = targets.filter((game) => {
        const info = derived(game);
        return info.matched === info.total && info.alerts === 0;
      }).map((game) => game.key);
      if (archiveKeys.length) {
        await json('/studio/matching/archive', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keys: archiveKeys, archived: true }),
        });
      }
      targets.forEach((game) => {
        game.dirty = false;
        if (archiveKeys.includes(game.key)) {
          game.archived = true;
          game.editing = false;
          game.editBackup = null;
        }
      });
      const left = state.games.filter((g) => !g.archived).length;
      state.status = `已保存 ${playerRows.length} 条选手匹配；${archiveKeys.length} 局归档并锁定。还剩 ${left} 局待匹配。`;
    } catch (error) {
      state.status = `保存失败：${error.message}`;
    }
    render();
  }

  function mount(node) {
    if (!node) return;
    if (root && root !== node) dispose();
    root = node;
    root.addEventListener('click', click);
    root.addEventListener('change', change);
    root.addEventListener('input', input);
    root.addEventListener('submit', submit);
    bootstrap();
  }

  function dispose() {
    controller?.abort();
    controller = null;
    generation += 1;
    if (root) {
      root.removeEventListener('click', click);
      root.removeEventListener('change', change);
      root.removeEventListener('input', input);
      root.removeEventListener('submit', submit);
      root = null;
    }
    state = null;
  }

  return { mount, dispose, rerender: render, state: () => state };
}
