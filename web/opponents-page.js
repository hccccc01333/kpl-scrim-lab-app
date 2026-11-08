/* 对手归属：教练在这里给对手战队命名，并把对方选手指到所属战队。
   默认归属来自营地十人面板的阵营签名；手动指派写覆盖层，不改原始比赛。
   页面用「一行一队 + 展开明细」的紧凑结构，几十支战队也不会无限长。 */
import {esc, num, stats, table, emptyTip, pageHero, details} from '/assets/design/ui.js';
import {toast} from '/assets/design/toast.js';
import {skeleton} from '/assets/design/ui.js';

const playerTable = (players, teams, currentTeamId) => table(
  ['选手', '主路', {label: '出场', align: 'right'}, '所属战队'],
  players.map(player => [
    `<b>${esc(player.name)}</b>`,
    esc(player.lanes.join(' / ') || '—'),
    {v: num(player.games), cls: 'num'},
    `<select data-player="${esc(player.id)}" data-default="${esc(player.defaultTeam || '')}">
      <option value="">未归属</option>${teams.map(team =>
        `<option value="${esc(team.id)}"${team.id === (player.defaultTeam || currentTeamId) ? ' selected' : ''}>${esc(team.displayName)}</option>`).join('')}
    </select>`,
  ]));

export async function renderOpponents(container, {api, isCurrent}) {
  container.innerHTML = skeleton('cards');
  const data = await api('/api/studio/opponents');
  if (isCurrent && !isCurrent()) return;

  const teams = data.teams || [];
  const unassigned = data.unassigned || [];
  const totalPlayers = num(data.total || 0);

  const teamRow = team => {
    const manual = team.players.filter(player => player.manual).length;
    return `<div class="op-team">
      <details class="details op-fold">
        <summary>
          <b class="op-name">${esc(team.displayName)}</b>
          ${team.named ? '' : '<span class="card-tag">待命名</span>'}
          <span class="op-count">${num(team.players.length)} 人 · ${manual ? `${num(manual)} 人手改 · ` : ''}出场 ${num(team.games || team.players.reduce((sum, p) => sum + p.games, 0))} 局</span>
        </summary>
        <div class="details-body">
          ${team.players.length
            ? playerTable(team.players, teams, team.id)
            : emptyTip('这支战队还没有可识别的选手。')}
        </div>
      </details>
    </div>`;
  };

  container.innerHTML = pageHero({
    kicker: 'ROSTER · 对手归属',
    title: '对手战队与选手归属',
    lead: ['默认归属来自营地十人面板的<b>同局五人阵容</b>；同一名选手出现在多支队时，在这里手动指定所属战队。',
      '手动指派只写覆盖层，不改原始比赛。展开一支战队才能看到它的选手表。'],
    meta: [`${num(teams.length)} 支对手`, `${totalPlayers} 名选手`, `${num(unassigned.length)} 人未归属`],
  }) + `<div class="filterbar" style="margin-bottom:12px">
      <input data-search placeholder="搜选手名，跨队查找…" style="max-width:280px">
    </div>`
    + stats([
      ['对手战队', num(teams.length), '按阵容签名聚类'],
      ['对手选手', totalPlayers, '营地十人面板'],
      ['未归属', num(unassigned.length), unassigned.length ? '需要指定' : '全部已归属'],
      ['待命名', num(teams.filter(team => !team.named).length), '点队名旁标签的战队去改名'],
    ])
    + (teams.length ? `<div class="op-list" data-team-list>${teams.map(teamRow).join('')}</div>`
      : emptyTip('还没有对手数据；先去采集几场训练赛。'))
    + (unassigned.length ? details(`未归属选手（${num(unassigned.length)} 人）`,
      playerTable(unassigned, teams, ''), {label: '展开未归属选手'}) : '')
    + details('口径说明', `<div class="block-note">
        1. 默认归属 = 该选手最近一次出现的五人阵容所属战队；同队同局才会聚到一起。<br>
        2. 手动指定后，该选手在「教练档案 / 对手分析」里始终算作你指定的战队。<br>
        3. 战队被合并时，其选手会跟随并入目标战队。
      </div>`, {label: '展开口径说明'});

  container.querySelectorAll('select[data-player]').forEach(select => {
    select.onchange = async () => {
      const playerId = select.dataset.player;
      select.disabled = true;
      try {
        await api('/api/studio/opponents/assign', {playerId, teamId: select.value || null});
        await renderOpponents(container, {api, isCurrent});
      } catch (error) {
        select.disabled = false;
        toast.error('保存失败：' + error.message);
      }
    };
  });

  const search = container.querySelector('[data-search]');
  search.oninput = () => {
    const q = search.value.trim().toLowerCase();
    container.querySelectorAll('[data-team-list] .op-team').forEach(block => {
      if (!q) { block.hidden = false; return; }
      const hit = block.querySelectorAll('tbody tr b, .op-name').length
        && [...block.querySelectorAll('tbody tr b, .op-name')]
          .some(node => node.textContent.toLowerCase().includes(q));
      block.hidden = !hit;
    });
  };
}
