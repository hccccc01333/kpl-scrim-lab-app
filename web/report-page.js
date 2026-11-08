/* 赛前简报：挑一个对手，把交手记录、对手画像、分路对位、版本表现
   汇成一份可打印的一页简报。数据全部来自既有接口，只做汇总与结论。 */
import {esc, num, pct, stats, panel, table, emptyTip, pageHero, brief, details, skeleton} from '/assets/design/ui.js';
import {wlDots} from '/assets/design/ui.js';

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];

export async function renderBriefing(container, {api, isCurrent}) {
  container.innerHTML = skeleton('page');
  const [teamsRes, oppRes, matchupRes, matchesRes] = await Promise.all([
    api('/api/studio/teams'),
    api('/api/studio/analysis/opponents?min=1').catch(() => ({profiles: []})),
    api('/api/studio/view/lane-matchups'),
    api('/api/studio/view/matches?limit=500'),
  ]);
  if (isCurrent && !isCurrent()) return;

  const teams = teamsRes.teams || [];
  const own = teamsRes.own || {};
  const profiles = oppRes.profiles || [];
  const matchups = matchupRes.rows || [];
  const allMatches = matchesRes.matches || [];
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const selected = params.get('team')
    || teams.slice().sort((a, b) => b.matches - a.matches)[0]?.displayName || '';

  const team = teams.find(item => item.displayName === selected) || teams[0];
  if (!team) {
    container.innerHTML = pageHero({kicker: 'REPORT · 赛前简报', title: '赛前简报',
      lead: ['还没有对手数据：先采集几场训练赛，再回来生成简报。']});
    return;
  }

  const profile = profiles.find(item => item.name === team.displayName);
  const theirNames = new Set((team.players || []).map(player => player.name));
  const vsMatches = allMatches.filter(match => (match.opponent || '') === team.displayName);
  const vsRows = matchups.filter(row => theirNames.has(row.enemyLabel));

  /* 自动结论 */
  const findings = [];
  if (team.winRate != null && team.matches) {
    findings.push({text: `历史交手 ${num(team.wins)} 胜 ${num(team.losses)} 负（${pct(team.winRate)}）`,
      note: `共 ${num(team.matches)} 局`});
  }
  if (profile?.stability != null) {
    findings.push({text: `对手阵容稳定度 ${pct(profile.stability)}`,
      note: Number(profile.stability) >= 70 ? '基本不换人，可按固定五人准备' : '常换人，准备分路对位比准备个人更稳'});
  }
  if (vsRows.length) {
    const ahead = vsRows.filter(row => row.diff > 0).length;
    findings.push({text: `同路对位经济领先率 ${num(ahead / vsRows.length * 100, 0)}%`,
      note: `${num(vsRows.length)} 个对位样本`});
  }
  if (vsMatches.length >= 2) {
    const decided = vsMatches.filter(match => match.result === 'win' || match.result === 'loss');
    const wins = decided.filter(match => match.result === 'win').length;
    if (decided.length) findings.push({text: `我方对其胜率 ${num(wins / decided.length * 100, 0)}%`,
      note: `${num(wins)} 胜 / ${num(decided.length)} 局定胜负`});
  }

  /* 分路对位聚合（对手选手参与的同路样本） */
  const laneAgg = LANES.map(lane => {
    const rows = vsRows.filter(row => row.position === lane);
    if (!rows.length) return null;
    const ahead = rows.filter(row => row.diff > 0).length;
    const decided = rows.filter(row => row.win != null);
    const wins = rows.filter(row => row.win === true).length;
    return {lane, n: rows.length,
      diff: rows.reduce((sum, row) => sum + row.diff, 0) / rows.length,
      aheadRate: ahead / rows.length * 100,
      winRate: decided.length ? wins / decided.length * 100 : null};
  }).filter(Boolean).sort((a, b) => b.diff - a.diff);

  /* 版本表现（双方交手的局） */
  const versionMap = new Map();
  vsMatches.forEach(match => {
    const key = match.version || '版本待补';
    const item = versionMap.get(key) || {version: key, games: 0, wins: 0, losses: 0};
    item.games += 1;
    if (match.result === 'win') item.wins += 1;
    if (match.result === 'loss') item.losses += 1;
    versionMap.set(key, item);
  });
  const versionRows = [...versionMap.values()].sort((a, b) => b.games - a.games)
    .map(item => [`<b>${esc(item.version)}</b>`, {v: num(item.games), cls: 'num'},
      {v: `${num(item.wins)}-${num(item.losses)}`, cls: 'num'},
      {v: (item.wins + item.losses) ? pct(item.wins / (item.wins + item.losses) * 100) : '—', cls: 'num'}]);

  /* 我方近期（最近 5 局） */
  const recent = allMatches.slice(0, 5).map(match => ({
    label: match.opponent ? `vs ${match.opponent}` : (match.title || match.key),
    meta: match.date || '', result: match.result,
  }));

  const laneBars = laneAgg.map(item => `<div class="cl-rank ${item.diff > 0 ? '' : 'is-lag'}">
      <span class="cl-rank-name">${esc(item.lane)}</span>
      <span class="cl-rank-bar"><i style="width:${Math.min(100, Math.abs(item.diff) / 3000 * 100).toFixed(0)}%"></i></span>
      <b class="cl-rank-val">${item.diff > 0 ? '+' : ''}${num(item.diff, 0)}</b>
      <span class="cl-rank-pct">${num(item.aheadRate, 0)}% 领先</span>
    </div>`).join('') || emptyTip('还没有与该队选手的同路对位样本。');

  const resultTag = result => result === 'win'
    ? '<span class="card-tag is-win">胜</span>'
    : result === 'loss' ? '<span class="card-tag is-loss">负</span>' : '<span class="card-tag">待定</span>';

  container.innerHTML = pageHero({
    kicker: 'REPORT · 赛前简报',
    title: `赛前简报 · ${esc(team.displayName)}`,
    lead: ['交手记录、对手画像、分路对位、版本表现一页看完，教练会前直接打印带走。',
      '换对手用下面的选择框；结论都是描述性统计，口径见各模块页。'],
    meta: [`${num(team.matches)} 局交手`, `最近 ${esc(team.lastSeen || '—')}`],
  }) + `<div class="filterbar no-print">
      <label class="fld"><span>对手</span>
        <select id="report-team">${teams.map(item =>
          `<option value="${esc(item.displayName)}"${item.displayName === team.displayName ? ' selected' : ''}>${esc(item.displayName)}</option>`).join('')}</select></label>
      <button type="button" class="primary" data-print>打印 / 导出 PDF</button>
      <a class="button" href="#report?team=${encodeURIComponent(team.displayName)}" id="report-refresh">刷新数据</a>
    </div>`
    + (findings.length ? brief(findings) : '')
    + stats([
      ['历史交手', `${num(team.wins)}-${num(team.losses)}`, `共 ${num(team.matches)} 局`],
      ['我方对其胜率', team.winRate == null ? '—' : pct(team.winRate), '有胜负的局'],
      ['对手稳定度', profile?.stability == null ? '—' : pct(profile.stability), '首发重合比例'],
      ['对位样本', num(vsRows.length), '同路直接对位'],
    ])
    + panel('分路对位观察', laneBars, {note: '横条 = 场均经济差（我方视角），3000 金封顶'})
    + `<div class="cmp-grid"><div>${
        panel('对手常用与核心选手', profile && profile.available ? `
          <div class="chips">${(profile.heroes || []).slice(0, 6).map(hero =>
            `<span class="chip">${esc(hero.hero)}<small>${num(hero.games)} 局</small></span>`).join('')}</div>
          <div class="opp-players" style="margin-top:10px">${(profile.players || []).slice(0, 5).map(player =>
            `<div class="opp-player"><b>${esc(player.name || player.id)}</b>
              <span>${esc(player.lane || '—')} · ${num(player.games)} 局</span>
              <small>${(player.heroes || []).map(hero => esc(hero.hero)).join(' / ') || '—'}</small></div>`).join('')}</div>`
        : emptyTip(profile?.reason || '该队样本不足，还没有画像。'), {note: '来自对手画像'})}</div>
      <div>${panel('版本表现', table(
        ['版本', {label: '局数', align: 'right'}, {label: '胜-负', align: 'right'}, {label: '胜率', align: 'right'}],
        versionRows, {empty: '补录版本号后这里会自动分组。'}), {note: '双方交手的局'})}</div></div>`
    + panel('我方近期状态', `<div style="margin-bottom:10px">${wlDots(
        allMatches.slice(0, 10).map(match => ({
          win: match.result === 'win' ? true : match.result === 'loss' ? false : null,
          start: match.date,
        })), {max: 10}) || emptyTip('还没有对局。')}</div><div class="brief-list">${recent.map(item =>
        `<div class="brief-row"><b>${esc(item.label)}</b><span>${esc(item.meta)} 　${resultTag(item.result)}</span></div>`).join('')}</div>`,
      {note: '点条 = 最近 10 局（全部对手）'})
    + details('口径说明', `<div class="block-note">
        1. 交手与胜负来自营地十人面板的阵容聚类与明确胜负局。<br>
        2. 分路对位只统计同分路双方都确认的样本；经济差为终局值。<br>
        3. 稳定度 = 各局首发与首局首发的重合比例均值。<br>
        4. 本页所有数字都是描述性统计，不构成因果结论。
      </div>`, {label: '展开口径说明'});

  const select = container.querySelector('#report-team');
  select.onchange = () => { location.hash = `#report?team=${encodeURIComponent(select.value)}`; };
  document.title = `赛前简报 · ${team.displayName} · 赛训分析`;
}
