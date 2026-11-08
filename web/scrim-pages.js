/* 赛训自有页面：约定计划 / 交手记录 / 教练档案
   三个页面共用 design/ui.js 的组件，数据全部来自 /api/studio/*。 */
import {esc, num, pct, stats, panel, table, emptyTip, pageHero, hBars, lineChart, brief, details, bindLineChart, ring, wlDots} from '/assets/design/ui.js';
import {toast} from '/assets/design/toast.js';
import {mountEChart, econOption, disposeECharts} from '/assets/design/echarts.js';
import {depthSection, bindDepthSections} from '/assets/depth-section.js';
import {skeleton} from '/assets/design/ui.js';

/* ---------------- 约定计划：教练登记 ---------------- */
export async function renderPlan(container, {api, isCurrent}) {
  container.innerHTML = skeleton('table');
  const [data, opponents] = await Promise.all([
    api('/api/studio/plans'),
    api('/api/studio/opponents').catch(() => ({teams: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const plans = data.plans || [];
  const options = (opponents.teams || []).map(team =>
    `<option value="${esc(team.displayName)}">${esc(team.displayName)}</option>`).join('');

  const today = new Date().toISOString().slice(0, 10);
  const upcoming = plans.filter(p => p.date >= today && p.status !== 'done');
  const past = plans.filter(p => p.date < today || p.status === 'done');

  const row = plan => [
    `<b>${esc(plan.date)}</b>${plan.time ? ' ' + esc(plan.time) : ''}`,
    esc(plan.opponent || '—'),
    esc(plan.mode || '—'),
    esc(plan.note || '—'),
    `<span class="card-tag ${plan.status === 'done' ? 'is-win' : ''}">${plan.status === 'done' ? '已完成' : '待进行'}</span>`,
    `<button type="button" class="link" data-done="${esc(plan.id)}">标记完成</button>
     <button type="button" class="link" data-drop="${esc(plan.id)}">删除</button>`,
  ];

  const first = !plans.length;
  const presets = [
    {date: today, time: '19:00', opponent: '', mode: '训练赛', note: '重点练前期节奏与一塔协同'},
    {date: today, time: '20:00', opponent: '', mode: 'BP 演练', note: '针对下一场对手的版本答案'},
    {date: today, time: '21:00', opponent: '', mode: '复盘', note: '回顾本周经济转折与掉点'},
  ];
  const presetRow = preset => `<button type="button" class="link" data-preset="${esc(JSON.stringify(preset))}">
    ${esc(preset.mode)} ${esc(preset.time)} · ${esc(preset.note)}</button>`;

  container.innerHTML = pageHero({
    kicker: 'PLAN · 约定计划',
    title: '训练赛约定计划',
    lead: ['教练在这里登记<b>下一场约谁、什么时候、练什么</b>。完成的计划可以一键标记，方便回看排期节奏。'],
    meta: [`${num(upcoming.length)} 场待进行`, `${num(past.length)} 场已完成`],
  }) + stats([
    ['待进行', num(upcoming.length), '今天及以后'],
    ['已完成', num(past.length), '含历史'],
    ['登记总数', num(plans.length), '全部计划'],
    ['最近一场', upcoming.length ? esc(upcoming[upcoming.length - 1].date) : '—', '按日期'],
  ]) + panel('登记一场', `
    <form class="filterbar" style="border:0;padding:0;background:transparent" data-plan-form>
      <label class="fld"><span>日期</span><input type="date" name="date" value="${today}" required></label>
      <label class="fld"><span>时间</span><input type="time" name="time"></label>
      <label class="fld"><span>对手</span><input name="opponent" list="plan-opponents" placeholder="对手战队">
        <datalist id="plan-opponents">${options}</datalist></label>
      <label class="fld"><span>练什么</span>
        <select name="mode">
          <option value="训练赛">训练赛</option>
          <option value="复盘">复盘</option>
          <option value="BP 演练">BP 演练</option>
          <option value="体测">体测</option>
        </select></label>
      <label class="fld" style="flex:1 1 220px"><span>备注</span><input name="note" placeholder="重点、阵容、版本"></label>
      <button type="submit" class="primary">加入计划</button>
    </form>`)
    + (first ? panel('第一次登记？点一条直接带入表单', `
      <div class="block-note">${presets.map(presetRow).join('<br>')}</div>
      <div class="block-note" style="margin-top:8px">登记后对手名会带进「交手记录」「约定计划」的复盘口径；当天训练赛打完，采集页的图会自动挂到这局上。</div>`)
      : '')
    + panel('待进行', upcoming.length
      ? table(['时间', '对手', '形式', '备注', '状态', '操作'], upcoming.map(row))
      : emptyTip('还没有待进行的计划。'), {note: `${upcoming.length} 场`})
    + (past.length ? panel('已完成 / 历史', table(['时间', '对手', '形式', '备注', '状态', '操作'], past.map(row)),
      {note: `${past.length} 场`}) : '');

  const form = container.querySelector('[data-plan-form]');
  form.onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form));
    await api('/api/studio/plans', payload);
    if (isCurrent && !isCurrent()) return;
    renderPlan(container, {api, isCurrent});
  };
  container.querySelectorAll('[data-preset]').forEach(button => {
    button.onclick = () => {
      const preset = JSON.parse(button.dataset.preset);
      form.elements.date.value = preset.date;
      form.elements.time.value = preset.time;
      form.elements.mode.value = preset.mode;
      form.elements.note.value = preset.note;
      form.elements.opponent.focus();
      form.scrollIntoView({behavior: 'smooth', block: 'center'});
    };
  });
  container.querySelectorAll('[data-drop]').forEach(button => {
    button.onclick = async () => {
      const plan = plans.find(item => item.id === button.dataset.drop);
      await api('/api/studio/plans/delete', {id: button.dataset.drop});
      toast.success('计划已删除', {
        action: plan ? {label: '撤销', fn: () => api('/api/studio/plans', plan)} : null,
      });
      renderPlan(container, {api, isCurrent});
    };
  });
  container.querySelectorAll('[data-done]').forEach(button => {
    button.onclick = async () => {
      const plan = plans.find(item => item.id === button.dataset.done);
      if (!plan) return;
      await api('/api/studio/plans', {...plan, status: 'done'});
      renderPlan(container, {api, isCurrent});
    };
  });
}

/* ---------------- 交手记录：本方 vs 对手 ---------------- */
export async function renderH2H(container, {api, isCurrent}) {
  container.innerHTML = skeleton('page');
  const data = await api('/api/studio/teams');
  if (isCurrent && !isCurrent()) return;
  const own = data.own || {};
  const teams = (data.teams || []).slice().sort((a, b) => b.matches - a.matches);

  // 自动提炼结论
  const allWin = teams.filter(team => team.winRate === 100 && team.matches >= 2);
  const winless = teams.filter(team => team.winRate === 0 && team.matches >= 2);
  const findings = [];
  if (teams.length) findings.push({
    text: `交手最多：${esc(teams[0].displayName)}（${num(teams[0].matches)} 局，胜率 ${
      teams[0].winRate == null ? '—' : num(teams[0].winRate, 1) + '%'}）`,
    note: `最近 ${esc(teams[0].lastSeen || '—')}`,
  });
  if (allWin.length) findings.push({
    text: `尚未赢过的对手 ×${num(allWin.length)}`,
    note: allWin.slice(0, 3).map(team => esc(team.displayName)).join('、'),
  });
  if (winless.length) findings.push({
    text: `全胜压制 ×${num(winless.length)}`,
    note: winless.slice(0, 3).map(team => esc(team.displayName)).join('、'),
  });

  container.innerHTML = pageHero({
    kicker: 'HEAD TO HEAD · 交手记录',
    title: '交手记录',
    lead: ['只统计我方与各对手的真实交锋：局数、胜负、胜率和首末次交手时间。',
      '点任意一行进入该队的完整档案（雷达、分路、组合）。'],
    meta: [`${num(teams.length)} 支对手`, `${num(own.matches)} 局`],
  }) + stats([
    ['对手战队', num(teams.length), '有交锋记录'],
    ['我方对局', num(own.matches), '营地十人面板'],
    ['我方胜率', own.winRate == null ? '—' : `${ring(own.winRate, {label: '我方胜率'})}`, `${num(own.wins)} 胜 ${num(own.losses)} 负`],
    ['全胜对手', num(teams.filter(t => t.winRate === 100).length), '样本 ≥1 局'],
  ]) + (findings.length ? brief(findings) : '') + panel('逐队交锋', table(
    ['对手', {label: '交手', align: 'right'}, {label: '胜-负', align: 'right'},
     {label: '胜率', align: 'right'}, '近况', '首次', '最近', ''],
    teams.map(team => [
      `<b>${esc(team.displayName)}</b>${team.named ? '' : ' <span class="card-tag">待命名</span>'}`,
      {v: num(team.matches), cls: 'num'},
      {v: `${num(team.wins)}-${num(team.losses)}`, cls: 'num'},
      {v: team.winRate == null ? '—' : pct(team.winRate), cls: 'num'},
      wlDots(team.games, {max: 8}) || '—',
      esc(team.firstSeen || '—'), esc(team.lastSeen || '—'),
      `<a href="#ref/team.html?id=${encodeURIComponent(team.displayName)}">查看档案 →</a>`,
    ])), {note: `${teams.length} 支 · 按交手局数排序；近况 = 最近 8 局`})
    + details('口径说明', `<div class="block-note">
        1. 对手由营地十人面板的阵容签名聚类得到；同一批五人自动归为一队。<br>
        2. 胜负只统计有明确结果的局，未记录胜方的不计入胜率。<br>
        3. 未命名的战队按首次出现顺序编号，可在「对手归属」里改名。
      </div>`, {label: '展开口径说明'});
}

/* ---------------- 教练档案 ---------------- */
export async function renderCoach(container, {api, isCurrent}) {
  container.innerHTML = skeleton('cards');
  const data = await api('/api/studio/coach');
  if (isCurrent && !isCurrent()) return;
  const teams = data.teams || [];

  const teamCard = team => panel(
    `${team.name}${team.named ? '' : '（待命名）'}`,
    `<label class="fld" style="max-width:320px"><span>对方教练</span>
        <input data-team="${esc(team.id)}" value="${esc(team.coach || '')}" placeholder="填写教练名"></label>
     <div style="margin-top:12px">${team.players.length
       ? `<div class="chips">${team.players.map(player =>
         `<span class="chip">${esc(player.name)}<small>${esc(player.lanes.join('/') || '—')} · ${num(player.games)} 局</small></span>`).join('')}</div>`
       : emptyTip('暂无选手')}</div>`,
    {note: `${team.players.length} 人`}
  );

  container.innerHTML = pageHero({
    kicker: 'COACH · 教练档案',
    title: '教练档案',
    lead: ['本队教练在下面直接填写；对手战队的教练名也可以补录，用于赛后复盘和 BP 分析备注。',
      '选手指到哪支战队，在「对手归属」里改。'],
    meta: [`${num(teams.length)} 支对手`, `${num(teams.reduce((sum, t) => sum + t.players.length, 0))} 名对手选手`],
  }) + panel('本队教练', `<label class="fld" style="max-width:320px"><span>教练姓名</span>
      <input data-own value="${esc(data.own?.coach || '')}" placeholder="填写本队教练"></label>`,
    {note: '保存后用于档案页署名'})
    + `<div class="hd-grid">${teams.map(teamCard).join('')}</div>`
    + panel('口径说明', `<div class="block-note">
        1. 教练名只存覆盖层，不改原始比赛。<br>
        2. 对手阵容来自营地十人面板，归属可在「对手归属」调整。<br>
        3. 本队教练写入项目设置，导出报告时会带上署名。
      </div>`);

  const save = async (payload) => { await api('/api/studio/coach', payload); };
  const own = container.querySelector('[data-own]');
  own.onblur = () => save({name: own.value});
  container.querySelectorAll('input[data-team]').forEach(input => {
    input.onblur = () => save({teamId: input.dataset.team, name: input.value});
  });
}

/* ---------------- 版本对比 ---------------- */
export async function renderVersions(container, {api, isCurrent}) {
  container.innerHTML = skeleton('table');
  const data = await api('/api/studio/view/matches?limit=1000');
  if (isCurrent && !isCurrent()) return;
  const matches = (data.matches || []).filter(m => m.version);

  const groups = new Map();
  for (const match of matches) {
    const key = String(match.version).trim();
    const group = groups.get(key) || {version: key, games: 0, wins: 0, losses: 0,
      minutes: 0, opponents: new Set(), first: '', last: ''};
    group.games += 1;
    if (match.result === 'win') group.wins += 1;
    if (match.result === 'loss') group.losses += 1;
    if (match.duration) group.minutes += match.duration / 60;
    if (match.opponent) group.opponents.add(match.opponent);
    if (match.date) {
      if (!group.first || match.date < group.first) group.first = match.date;
      if (!group.last || match.date > group.last) group.last = match.date;
    }
    groups.set(key, group);
  }
  const versions = [...groups.values()].sort((a, b) => (a.first || '').localeCompare(b.first || ''));

  if (!versions.length) {
    container.innerHTML = pageHero({kicker: 'VERSION · 版本对比', title: '版本对比',
      lead: ['当前没有带<b>版本号</b>的对局。营地不提供版本，需要在导入后由教练补录。'],
      meta: ['0 个版本']})
      + panel('下一步', `<div class="block-note">版本字段在「待确认」里按局补录；补完这里会自动分组。</div>
        <div style="margin-top:10px"><a class="button primary" href="#pending">去补版本 →</a></div>`);
    return;
  }

  const rate = group => (group.wins + group.losses) ? group.wins / (group.wins + group.losses) * 100 : null;
  const avgMin = group => group.games ? group.minutes / group.games : null;
  const pick = (index) => versions[Math.min(index, versions.length - 1)];
  const a = pick(0), b = pick(versions.length - 1);

  const metrics = [
    ['对局数', g => g.games, v => num(v)],
    ['胜率', rate, v => v == null ? '—' : pct(v)],
    ['平均时长', avgMin, v => v == null ? '—' : Number(v).toFixed(1) + ' 分'],
    ['对手数', g => g.opponents.size, v => num(v)],
  ];
  const rows = metrics.map(([label, get, fmt]) => {
    const av = get ? get(a) : null;
    const bv = get ? get(b) : null;
    const diff = av != null && bv != null && typeof av === 'number' && typeof bv === 'number' ? bv - av : null;
    return [
      label,
      {v: fmt(av), cls: 'num'},
      {v: fmt(bv), cls: 'num'},
      {v: diff == null ? '—' : `${diff > 0 ? '▲' : diff < 0 ? '▼' : ''} ${
        typeof av === 'number' && !Number.isInteger(av) ? Math.abs(diff).toFixed(1) : num(Math.abs(diff))}`,
       cls: `num delta ${diff > 0 ? 'is-pos' : diff < 0 ? 'is-neg' : ''}`},
    ];
  });
  rows.unshift(['胜 - 负',
    {v: `${num(a.wins)} - ${num(a.losses)}`, cls: 'num'},
    {v: `${num(b.wins)} - ${num(b.losses)}`, cls: 'num'},
    {v: '—', cls: 'num'}]);
  rows.push(['时间范围',
    {v: `${esc(a.first || '—')} → ${esc(a.last || '—')}`, cls: 'num'},
    {v: `${esc(b.first || '—')} → ${esc(b.last || '—')}`, cls: 'num'},
    {v: '—', cls: 'num'}]);

  // 自动提炼结论
  const rated = versions.filter(group => rate(group) != null);
  const bestV = rated.slice().sort((x, y) => rate(y) - rate(x))[0];
  const worstV = rated.slice().sort((x, y) => rate(x) - rate(y))[0];
  const findings = [];
  if (bestV && bestV !== worstV) findings.push({
    text: `胜率最高 ${esc(bestV.version)}：${num(rate(bestV), 1)}%`,
    note: `${num(bestV.games)} 局 · ${num(bestV.wins)}-${num(bestV.losses)}`,
  });
  if (worstV) findings.push({
    text: `胜率最低 ${esc(worstV.version)}：${num(rate(worstV), 1)}%`,
    note: `${num(worstV.games)} 局 · ${num(worstV.wins)}-${num(worstV.losses)}`,
  });
  if (a && b && a !== b) {
    const rateDiff = rate(a) != null && rate(b) != null ? rate(b) - rate(a) : null;
    if (rateDiff != null) findings.push({
      text: `${esc(a.version)} → ${esc(b.version)} 胜率 ${rateDiff > 0 ? '+' : ''}${num(rateDiff, 1)} pct`,
      note: '最新版 − 最早版',
    });
  }

  container.innerHTML = pageHero({
    kicker: 'VERSION · 版本对比',
    title: '版本对比',
    lead: ['按比赛记录的<b>版本号</b>分组，比较不同版本下的局数、胜率、时长与对手面。',
      '训练赛没有赛段概念，版本是唯一稳定的横向口径。'],
    meta: [`${num(versions.length)} 个版本`, `${num(matches.length)} 局带版本`],
  }) + stats([
    ['版本数', num(versions.length), '按版本号去重'],
    ['最早版本', esc(a.version), esc(a.first || '—')],
    ['最新版本', esc(b.version), esc(b.last || '—')],
    ['带版本对局', num(matches.length), '全部对局中'],
  ]) + (findings.length ? brief(findings) : '') + details(
    `${num(versions.length)} 个版本的一览`,
    table(
      ['版本', {label: '局数', align: 'right'}, {label: '胜-负', align: 'right'},
       {label: '胜率', align: 'right'}, {label: '均时长', align: 'right'}, '时间范围'],
      versions.map(group => [
        `<b>${esc(group.version)}</b>`,
        {v: num(group.games), cls: 'num'},
        {v: `${num(group.wins)}-${num(group.losses)}`, cls: 'num'},
        {v: rate(group) == null ? '—' : pct(rate(group)), cls: 'num'},
        {v: avgMin(group) == null ? '—' : Number(avgMin(group)).toFixed(1) + ' 分', cls: 'num'},
        `${esc(group.first || '—')} → ${esc(group.last || '—')}`,
      ])), {label: '展开版本一览'})
    + panel(`对比：${a.version} → ${b.version}`,
      table(['指标', {label: a.version, align: 'right'}, {label: b.version, align: 'right'},
             {label: '差', align: 'right'}], rows),
      {note: '最早版本 vs 最新版本；差为「最新 − 最早」'})
    + details('口径说明', `<div class="block-note">
        1. 版本号取自比赛记录；没有版本的局不参与分组。<br>
        2. 胜率只统计有明确胜负的局。<br>
        3. 平均时长按有记录的局长计算。
      </div>`, {label: '展开口径说明'});
}

/* ---------------- 待确认队列 ---------------- */
let _pendingFocus = null;   // 确认后回焦：{row, field} 行列坐标
export async function renderPending(container, {api, isCurrent}) {
  container.innerHTML = skeleton('cards');
  let data = await api('/api/studio/workspace/pending');
  if (isCurrent && !isCurrent()) return;
  // 队列为空时自动跑一次预填（幂等），避免第一次进来只看到一片空白
  if (!(data.total > 0)) {
    await api('/api/studio/workspace/prefill/run', {});
    data = await api('/api/studio/workspace/pending');
    if (isCurrent && !isCurrent()) return;
  }
  const rows = data.rows || [];
  const FIELD_CN = {enemy_team_id: '对手', session: '训练组', version: '版本', rules: '规则', pick_order: 'BP 手序'};
  const SOURCE_CN = {'derived:cluster': '推断·阵容', 'derived:session': '推断·时间', placeholder: '待填', 'auto:camp': '营地'};

  const fieldRow = (matchKey, field) => `<div class="pending-field">
      <span class="pending-label">${FIELD_CN[field.field] || field.field}</span>
      <input data-match="${esc(matchKey)}" data-field="${esc(field.field)}"
        value="${esc(field.value || '')}" placeholder="${field.value ? '' : '待填写'}">
      <span class="pending-source">${SOURCE_CN[field.source] || esc(field.source)}</span>
      <button type="button" class="link" data-confirm="${esc(matchKey)}|${esc(field.field)}">确认</button>
    </div>`;

  // 批量补字段：同一字段类型还有 ≥2 个待填时，给一个一次填完的入口
  const batchFields = [];
  rows.forEach(row => row.fields.forEach(field => {
    const hit = batchFields.find(item => item.field === field.field);
    if (hit) hit.count += 1;
    else batchFields.push({field: field.field, label: FIELD_CN[field.field] || field.field, count: 1});
  }));
  const batchBar = batchFields.filter(item => item.count >= 2).map(item => `
    <div class="pending-batch-row">
      <span class="pending-label">${esc(item.label)}</span>
      <input data-batch-field="${esc(item.field)}" placeholder="填一次，应用到 ${item.count} 局">
      <button type="button" class="link" data-batch="${esc(item.field)}">全部应用</button>
    </div>`).join('');

  container.innerHTML = pageHero({
    kicker: 'PENDING · 待确认',
    title: '待确认队列',
    lead: ['导入后自动预填：日期、阵营、胜负、比分、对手由营地直接带入；训练组按日期推断；版本与规则营地没有，需要你填。',
      '<b>回车确认并跳到下一个字段</b>；全场相同的值（如版本）用上面的批量入口一次填完。'],
    meta: [`${num(data.total)} 局待处理`, `${num(data.fields)} 个字段`],
  }) + (batchBar ? panel(`批量补字段`, `<div class="pending-batch">${batchBar}</div>`,
      {note: '只应用到还没确认的局'}) : '')
    + `<div class="filterbar"><button type="button" class="primary" data-run>运行预填</button></div>`
    + (rows.length ? rows.map(row => panel(
      `${row.date || '日期待补'} · ${row.opponent || '对手待补'}`,
      row.fields.map(field => fieldRow(row.matchKey, field)).join(''),
      {note: row.winner ? `胜方 ${esc(row.winner)}` : ''}
    )).join('') : panel('当前没有待确认字段', `<div class="block-note">
        ${data.fields === 0 ? '所有可确认字段都已处理完；新导入的对局会自动出现在这里。' : '还没有生成待确认项。'}
      </div><div style="margin-top:10px"><a class="button" href="#setup">回到建档向导 →</a>
      <a class="button" href="#matches" style="margin-left:8px">查看比赛档案</a></div>`));

  container.querySelector('[data-run]').onclick = async () => {
    await api('/api/studio/workspace/prefill/run', {});
    renderPending(container, {api, isCurrent});
  };
  container.querySelectorAll('[data-confirm]').forEach(button => {
    button.onclick = async () => {
      const [matchKey, field] = button.dataset.confirm.split('|');
      const input = container.querySelector(`input[data-match="${matchKey}"][data-field="${field}"]`);
      const value = input ? input.value.trim() : '';
      if (!value) { input?.focus(); return; }
      // 记住当前位置，重渲染后把焦点还给下一个字段（回车工作流）
      const panels = [...container.querySelectorAll('section.panel')];
      const panelEl = button.closest('section.panel');
      _pendingFocus = {row: panels.indexOf(panelEl), field: fieldsIndexOf(button, panelEl)};
      button.disabled = true;
      try {
        await api('/api/studio/workspace/pending/confirm', {matchKey, field, value});
        toast.success('已确认');
        renderPending(container, {api, isCurrent});
      } catch (error) {
        button.disabled = false;
        toast.error('保存失败：' + error.message);
      }
    };
  });
  // 回车 = 确认当前字段
  container.querySelectorAll('input[data-match]').forEach(input => {
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      input.closest('.pending-field')?.querySelector('[data-confirm]')?.click();
    });
  });
  // 批量应用
  container.querySelectorAll('[data-batch]').forEach(button => {
    button.onclick = async () => {
      const field = button.dataset.batch;
      const input = container.querySelector(`input[data-batch-field="${field}"]`);
      const value = (input?.value || '').trim();
      if (!value) { input?.focus(); return; }
      button.disabled = true;
      let done = 0, failed = 0;
      for (const row of rows) {
        if (!row.fields.some(item => item.field === field)) continue;
        try {
          await api('/api/studio/workspace/pending/confirm', {matchKey: row.matchKey, field, value});
          done += 1;
        } catch (error) { failed += 1; }
      }
      if (failed) toast.error(`已应用 ${done} 局，${failed} 局失败`);
      else toast.success(`已应用到 ${done} 局`);
      renderPending(container, {api, isCurrent});
    };
  });

  // 回焦下一个字段
  if (_pendingFocus && _pendingFocus.row >= 0) {
    const panels = [...container.querySelectorAll('section.panel')];
    const target = panels[_pendingFocus.row];
    const inputs = target ? [...target.querySelectorAll('input[data-match]')] : [];
    const next = inputs[_pendingFocus.field] || inputs[0];
    if (next) { next.focus(); next.scrollIntoView({block: 'center', behavior: 'smooth'}); }
    _pendingFocus = null;
  }

  function fieldsIndexOf(button, panelEl) {
    const fields = [...panelEl.querySelectorAll('.pending-field')];
    return Math.max(0, fields.indexOf(button.closest('.pending-field')) + 1);
  }
}

/* ---------------- 经济转折与兑现（A8 / A9） ---------------- */
export async function renderEconomy(container, {api, isCurrent}) {
  container.innerHTML = skeleton('chart');
  const [a8, a9] = await Promise.all([
    api('/api/studio/analysis/turning-points?limit=24'),
    api('/api/studio/analysis/advantage'),
  ]);
  if (isCurrent && !isCurrent()) return;

  const swingRows = (a8.rows || []).map(row => [
    esc(row.game),
    `${Math.round(row.start)}–${Math.round(row.end)} 秒`,
    {v: (row.delta > 0 ? '+' : '') + num(row.delta), cls: `num delta ${row.delta > 0 ? 'is-pos' : 'is-neg'}`},
    row.ownAdvantage ? '我方' : '对方',
    row.candidates.length
      ? row.candidates.map(item => `<span class="chip">${esc(item.type)} ${Math.round(item.t)}s</span>`).join(' ')
      : '—',
  ]);

  const bucketRows = (a9.buckets || []).map(bucket => [
    esc(bucket.bucket),
    {v: num(bucket.n), cls: 'num'},
    {v: `${num(bucket.wins)}`, cls: 'num'},
    {v: bucket.winRate == null ? '—' : pct(bucket.winRate), cls: 'num'},
    {v: bucket.ciLow == null ? '—' : `${pct(bucket.ciLow, 0)} – ${pct(bucket.ciHigh, 0)}`, cls: 'num'},
    bucket.enough
      ? '<span class="card-tag is-win">样本足够</span>'
      : '<span class="card-tag">样本不足</span>',
  ]);

  const seriesKeys = Object.keys(a8.series || {});

  // 自动提炼结论
  const topSwing = (a8.rows || [])[0];
  const usableBuckets = (a9.buckets || []).filter(b => b.winRate != null && b.n >= 5);
  const sortedBuckets = (usableBuckets.length ? usableBuckets
    : (a9.buckets || []).filter(b => b.winRate != null)).sort((a, b) => b.winRate - a.winRate);
  const findings = [];
  if (topSwing) findings.push({
    text: `最大经济转折 ${topSwing.delta > 0 ? '+' : ''}${num(topSwing.delta)}`,
    note: `${esc(topSwing.game)} ${Math.round(topSwing.start)}–${Math.round(topSwing.end)}s`,
  });
  if (sortedBuckets.length) {
    const best = sortedBuckets[0];
    const worst = sortedBuckets[sortedBuckets.length - 1];
    findings.push({
      text: `「${best.bucket}」胜率 ${num(best.winRate, 1)}%`,
      note: `${num(best.n)} 局${best.n < 10 ? ' · 样本小' : ''}`,
    });
    if (sortedBuckets.length >= 2 && worst !== best) findings.push({
      text: `「${worst.bucket}」胜率 ${num(worst.winRate, 1)}%`,
      note: `${num(worst.n)} 局${worst.n < 10 ? ' · 样本小' : ''}`,
    });
  }

  container.innerHTML = pageHero({
    kicker: 'ECONOMY · 经济转折与兑现',
    title: '经济转折与兑现',
    lead: ['<b>经济转折</b>：按 30/60/120 秒窗口找经济差突变，列出窗口内±60 秒的资源/团战候选事件。',
      '<b>优势兑现</b>：十分经济差分桶后看最终胜率，附 Wilson 95% 区间。',
      '经济点是回放给出的约 30 秒采样，按索引均匀铺到时间轴，标「近似」。'],
    meta: [`${num(a8.games)} 局有经济序列`, `${num(a9.games)} 局可算兑现`],
  }) + (findings.length ? brief(findings) : '') + stats([
    ['可用局数', num(a8.games), '回放带团队经济'],
    ['转折窗口', num(a8.total), '按阈值筛出'],
    ['兑现样本', num(a9.overall?.n || 0), '有胜负且十分钟有采样'],
    ['兑现胜率', a9.overall?.winRate == null ? '—' : pct(a9.overall.winRate), '全部样本'],
  ]) + (seriesKeys.length ? panel('经济差走势与转折窗口',
    `<label class="fld" style="max-width:260px;margin-bottom:10px"><span>选择对局</span>
      <select data-econ-game>${seriesKeys.map(key => `<option value="${esc(key)}">${esc(key)}</option>`).join('')}</select></label>
     <div data-econ-chart></div>
     <div class="block-note">阴影为检出的转折窗口：绿色我方扩大领先，红色被反超/缩小。</div>`,
    {note: `${num(seriesKeys.length)} 局有序列`}) : '')
    + panel('优势兑现率（按十分经济差分桶）',
      hBars((a9.buckets || []).filter(bucket => bucket.winRate != null).map(bucket => ({
        label: `${bucket.bucket}（${num(bucket.n)} 局）`,
        value: bucket.winRate,
      })), {unit: '%', digits: 1, ref: 50})
      + `<div class="block-note">分桶按我方视角；样本 &lt; 10 局的桶只作观察。</div>`,
      {note: '胜率 %'})
    + details(`全部 ${num(a8.total)} 个转折窗口`, table(
      ['对局', '窗口', {label: '经济差变化', align: 'right'}, '变化方向', '同期候选事件'],
      swingRows, {empty: '没有超过阈值的经济变化窗口。'}), {label: '展开完整转折表'})
    + details('分桶明细与 95% 区间', table(
      ['分桶', {label: '局数', align: 'right'}, {label: '胜', align: 'right'},
       {label: '胜率', align: 'right'}, {label: '95% 区间', align: 'right'}, '样本'],
      bucketRows, {empty: '没有可算的对局。'}), {label: '展开分桶表'})
    + details('口径说明', `<div class="block-note">
        1. 经济差 = 蓝 − 红的团队金币；换算到我方视角后分桶：落后 &lt; −500、持平 ±500、小优 500–1500、大优 &gt; 1500。<br>
        2. 转折阈值取「1000 金币」与「全部窗口 |Δ| 的 P90」较大者，避免小波动刷屏。<br>
        3. 候选事件只是同一时间窗内发生的事，<b>不代表因果</b>。<br>
        4. 样本 &lt; 10 局的分桶只给观察，不给转化率结论。
      </div>`, {label: '展开口径说明'});

  const selectGame = container.querySelector('[data-econ-game]');
  const chartBox = container.querySelector('[data-econ-chart]');
  if (selectGame && chartBox) {
    const paintChart = async () => {
      const item = (a8.series || {})[selectGame.value];
      if (!item) { chartBox.innerHTML = emptyTip('这局没有经济序列。'); return; }
      const points = item.diff.map((value, index) => ({
        x: index * item.duration / Math.max(1, item.diff.length - 1),
        y: value,
      }));
      const host = chartBox.querySelector('.ech') || document.createElement('div');
      host.className = 'ech';
      host.style.height = '320px';
      if (!host.parentElement) chartBox.innerHTML = '', chartBox.appendChild(host);
      try {
        await mountEChart(host, econOption(points, item.swings || []));
      } catch (error) {
        chartBox.innerHTML = lineChart(points, {unit: '经济差（蓝 − 红）', markers: item.swings || []});
        bindLineChart(chartBox);
      }
    };
    selectGame.onchange = paintChart;
    paintChart();
  }
}

/* ---------------- B1 对手画像 ---------------- */
export async function renderOppProfiles(container, {api, isCurrent}) {
  container.innerHTML = skeleton('cards');
  const data = await api('/api/studio/analysis/opponents?min=3');
  if (isCurrent && !isCurrent()) return;
  const profiles = data.profiles || [];
  const ready = profiles.filter(item => item.available);

  // 自动提炼结论：最强对手 / 最稳阵容 / 样本最多
  const byWin = ready.slice().sort((a, b) => (b.winRate || 0) - (a.winRate || 0));
  const byStable = ready.filter(item => item.stability != null).sort((a, b) => b.stability - a.stability);
  const byGames = profiles.slice().sort((a, b) => b.games - a.games);
  const findings = [];
  if (byWin.length) findings.push({
    text: `胜率最高的对手：${esc(byWin[0].name)} ${num(byWin[0].winRate, 1)}%`,
    note: `${num(byWin[0].wins)} 胜 / ${num(byWin[0].games)} 局`,
  });
  if (byStable.length) findings.push({
    text: `阵容最稳定：${esc(byStable[0].name)}（${pct(byStable[0].stability)}）`,
    note: '首发重合比例',
  });
  if (byGames.length && byGames[0].games > 0) findings.push({
    text: `交手最多：${esc(byGames[0].name)}（${num(byGames[0].games)} 局）`,
    note: byGames[0].available ? '样本充足' : '暂不足 3 局',
  });

  const card = item => {
    if (!item.available) {
      return panel(item.name, `<div class="block-note">${esc(item.reason)}</div>`, {note: `${num(item.games)} 局`});
    }
    const metrics = Object.values(item.metrics || {}).map(metric =>
      `<div class="opp-metric"><span>${esc(metric.label)}</span><b>${metric.value == null ? '—' : num(metric.value, 2)}</b></div>`).join('');
    const heroes = (item.heroes || []).slice(0, 5)
      .map(hero => `<span class="chip">${esc(hero.hero)}<small>${num(hero.games)} 局</small></span>`).join('');
    const players = (item.players || []).slice(0, 6).map(player =>
      `<div class="opp-player"><b>${esc(player.name || player.id)}</b>
        <span>${esc(player.lane || '—')} · ${num(player.games)} 局</span>
        <small>${(player.heroes || []).map(hero => esc(hero.hero)).join(' / ') || '—'}</small></div>`).join('');
    return panel(item.name, `
      <div class="opp-head">
        ${ring(item.winRate, {label: '对手胜率'})}
        <div class="opp-head-txt"><b>对手胜率 ${pct(item.winRate)}</b>
          <span>阵容稳定度 ${item.stability == null ? '—' : pct(item.stability)} · 置信度 ${esc(item.confidence)}</span></div>
      </div>
      <div class="opp-metrics" style="margin-top:10px">${metrics}</div>
      <div class="chips" style="margin-top:12px">${heroes}</div>
      <div class="opp-players" style="margin-top:10px">${players}</div>`,
      {note: `${num(item.games)} 局 · ${num(item.wins)} 胜`});
  };

  container.innerHTML = pageHero({
    kicker: 'OPPONENT · 对手画像',
    title: '对手画像',
    lead: ['同一对手 ≥3 局才出画像：常用英雄、逐人英雄池、指标均值、阵容稳定度。',
      '不足 3 局的对手只显示「样本不足」，不硬给结论。'],
    meta: [`${num(profiles.length)} 支对手`, `${num(ready.length)} 支可画像`],
  }) + stats([
    ['对手总数', num(profiles.length), '按阵容签名聚类'],
    ['可出画像', num(ready.length), '≥3 局'],
    ['样本不足', num(profiles.length - ready.length), '只列单局记录'],
    ['对局总数', num((data.rows || 0)), '对手侧人次'],
  ]) + (findings.length ? brief(findings) : '')
    + (ready.length ? `<div class="hd-grid">${ready.map(card).join('')}</div>` : '')
    + (profiles.length
      ? (ready.length ? '' : emptyTip('还没有攒够 3 局的对手；下面的单局对手攒够样本后会自动出画像。'))
        + details(`单局对手 · ${num(profiles.length - ready.length)} 支`,
          table(
            ['对手', {label: '交手', align: 'right'}, {label: '胜-负', align: 'right'}, '状态'],
            profiles.filter(item => !item.available).map(item => [
              esc(item.name), {v: num(item.games), cls: 'num'},
              item.wins != null ? `${num(item.wins)}-${num(item.games - item.wins)}` : '—',
              esc(item.reason || '样本不足'),
            ]), {empty: '没有样本不足的对手。'}),
          {label: '展开单局对手列表'})
      : emptyTip('还没有对手数据；先去采集几场训练赛。'))
    + panel('口径说明', `<div class="block-note">
        1. 对手由营地十人面板的五人阵容签名聚类；同一批五人自动成一队。<br>
        2. 胜率是<b>对手视角</b>（对手赢下的局 / 交手局数）。<br>
        3. 阵容稳定度 = 各局首发与首局首发的重合比例均值；100% 表示五人不换。<br>
        4. 样本不足不输出画像，也不参与排序。
      </div>`);
}

/* ---------------- B3 训练效果 ---------------- */
export async function renderEffect(container, {api, isCurrent}) {
  container.innerHTML = skeleton('table');
  const [data, players] = await Promise.all([
    api('/api/studio/analysis/training-effect'),
    api('/api/studio/workspace/players').catch(() => ({players: []})),
  ]);
  if (isCurrent && !isCurrent()) return;
  const results = data.results || [];
  const options = (players.players || []).map(player =>
    `<option value="${esc(player.id)}">${esc(player.name)}（${esc(player.team_id)}）</option>`).join('');

  const row = item => {
    const effect = item.effect || {};
    if (!effect.available) {
      return [esc(item.goal), esc(item.metric), esc(item.start_date || '—'),
        {v: effect.reason || '—', cls: 'muted'}, '', '', ''];
    }
    const sign = effect.delta > 0 ? '▲' : effect.delta < 0 ? '▼' : '';
    return [
      esc(item.goal), esc(effect.label || item.metric), esc(item.start_date || '—'),
      {v: `${num(effect.preMean, 2)} → ${num(effect.postMean, 2)}`, cls: 'num'},
      {v: `${sign} ${num(Math.abs(effect.delta), 2)}`, cls: `num delta ${effect.delta > 0 ? 'is-pos' : effect.delta < 0 ? 'is-neg' : ''}`},
      {v: effect.effectSize == null ? '—' : Number(effect.effectSize).toFixed(2), cls: 'num'},
      {v: effect.targetRate == null ? '—' : pct(effect.targetRate), cls: 'num'},
      {v: `${num(effect.nPre)} / ${num(effect.nPost)}`, cls: 'num'},
    ];
  };

  // 自动提炼结论
  const valid = results.filter(item => item.effect?.available);
  const improved = valid.filter(item => item.effect.delta > 0)
    .sort((a, b) => b.effect.delta - a.effect.delta);
  const findings = [];
  if (results.length) findings.push({
    text: `${num(valid.length)} / ${num(results.length)} 条干预有前后对比`,
    note: '前后各需 ≥5 人次',
  });
  if (improved.length) findings.push({
    text: `${esc(improved[0].goal)}：${esc(improved[0].effect.label || improved[0].metric)} ${
      improved[0].effect.delta > 0 ? '+' : ''}${num(improved[0].effect.delta, 2)}`,
    note: `Cohen's d ${improved[0].effect.effectSize == null ? '—' : Number(improved[0].effect.effectSize).toFixed(2)}`,
  });
  if (valid.length > improved.length) findings.push({
    text: `${num(valid.length - improved.length)} 条指标持平或下滑`,
    note: '展开下方明细看逐条差值',
  });

  container.innerHTML = pageHero({
    kicker: 'EFFECT · 训练效果',
    title: '训练效果',
    lead: ['登记一条训练干预（目标 / 干预措施 / 起止 / 适用选手 / 指标 / 目标值），系统按日期切前后两段对比。',
      '只做<b>描述性前后对比</b>：均值、差值、Cohen\'s d、目标达成率，不宣称因果。'],
    meta: [`${num(results.length)} 条干预`, '前后各需 ≥5 人次'],
  }) + panel('登记干预', `
    <form class="filterbar" style="border:0;padding:0;background:transparent" data-training-form>
      <label class="fld"><span>目标</span><input name="goal" placeholder="提升十分钟经济差" required></label>
      <label class="fld"><span>干预措施</span><input name="intervention" placeholder="对线专项 + 每日复盘" required></label>
      <label class="fld"><span>开始</span><input type="date" name="startDate" required></label>
      <label class="fld"><span>结束</span><input type="date" name="endDate"></label>
      <label class="fld"><span>指标</span>
        <select name="metric">
          <option value="kda">KDA</option><option value="gpm">分均经济</option>
          <option value="dpm">分均输出</option><option value="tpm">分均承伤</option>
          <option value="participation">参团率</option>
        </select></label>
      <label class="fld"><span>目标值</span><input name="target" type="number" step="0.1" placeholder="可选"></label>
      <label class="fld" style="flex:1 1 220px"><span>适用选手</span>
        <select name="playerIds" multiple size="3">${options}</select></label>
      <button type="submit" class="primary">保存干预</button>
    </form>`)
    + (!results.length ? panel('第一次登记？点一条直接带入表单', `
      <div class="block-note">
        <button type="button" class="link" data-demo='{"goal":"提升十分钟经济差","metric":"gpm","target":"50"}'>提升十分钟经济差 · 指标 分均经济 · 目标 +50</button><br>
        <button type="button" class="link" data-demo='{"goal":"降低前期死亡","metric":"kda","target":"0.5"}'>降低前期死亡 · 指标 KDA · 目标 +0.5</button><br>
        <button type="button" class="link" data-demo='{"goal":"提高参团率","metric":"participation","target":"5"}'>提高参团率 · 指标 参团率 · 目标 +5</button>
      </div>
      <div class="block-note" style="margin-top:8px">登记后照常打一段训练赛，回来这里看前后对比；前后各需 ≥5 人次，系统只做描述性对比。</div>`)
      : '')
    + (findings.length ? brief(findings) : '') + details(
      results.length ? `全部 ${num(results.length)} 条干预的前后对比` : '还没有训练干预记录',
      table(
        ['目标', '指标', '开始', {label: '前 → 后', align: 'right'}, {label: '差值', align: 'right'},
         {label: "Cohen's d", align: 'right'}, {label: '目标达成', align: 'right'}, {label: '样本 前/后', align: 'right'}],
        results.map(row), {empty: '还没有训练干预记录。'}), {label: '展开干预明细'})
    + details('口径说明', `<div class="block-note">
        1. 干预前 = 开始日期之前的对局；干预后 = 结束日期（无则开始日期）之后的对局。<br>
        2. 指标按人次聚合（不是按局），选手留空表示全队。<br>
        3. Cohen's d = 均值差 / 合并标准差；样本 &lt; 10 标 low 置信度。<br>
        4. 这是描述性对比，<b>不代表干预有效或因果</b>。
      </div>`, {label: '展开口径说明'});

  const form = container.querySelector('[data-training-form]');
  container.querySelectorAll('[data-demo]').forEach(button => {
    button.onclick = () => {
      const demo = JSON.parse(button.dataset.demo);
      form.elements.goal.value = demo.goal;
      form.elements.metric.value = demo.metric;
      form.elements.target.value = demo.target;
      form.elements.startDate.focus();
      form.scrollIntoView({behavior: 'smooth', block: 'center'});
    };
  });
  form.onsubmit = async event => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData);
    payload.playerIds = formData.getAll('playerIds');
    if (payload.target === '') delete payload.target;
    await api('/api/studio/workspace/training', payload);
    renderEffect(container, {api, isCurrent});
  };
}

/* ---------------- 建档向导（8.5.1 五步） ---------------- */
export async function renderSetup(container, {api, isCurrent}) {
  container.innerHTML = skeleton('page');
  const [teams, players, matches, pending] = await Promise.all([
    api('/api/studio/workspace/teams'),
    api('/api/studio/workspace/players'),
    api('/api/studio/view/matches?limit=1'),
    api('/api/studio/workspace/pending').catch(() => ({total: 0, fields: 0})),
  ]);
  if (isCurrent && !isCurrent()) return;

  const own = (teams.teams || []).find(team => team.id === 'team-own') || (teams.teams || [])[0] || null;
  const playerList = players.players || [];
  const matchCount = matches.total || 0;

  const steps = [
    {
      key: 'team', title: '战队信息', done: Boolean(own && own.name && own.name !== '我方战队'),
      body: `<form class="filterbar" style="border:0;padding:0;background:transparent" data-team-form>
        <label class="fld"><span>队名</span><input name="name" value="${esc(own?.name || '')}" placeholder="例如：青岚" required></label>
        <label class="fld"><span>简称</span><input name="shortName" value="${esc(own?.short_name || '')}"></label>
        <label class="fld"><span>赛区</span>
          <select name="league"><option value="">未设置</option>
            ${['KPL', '次级', '青训', '大众'].map(item => `<option value="${item}"${own?.league === item ? ' selected' : ''}>${item}</option>`).join('')}
          </select></label>
        <label class="fld"><span>教练</span><input name="coach" value="${esc(own?.coach || '')}"></label>
        <label class="fld"><span>分析师</span><input name="analyst" value="${esc(own?.analyst || '')}"></label>
        <button type="submit" class="primary">保存</button>
      </form>`,
    },
    {
      key: 'roster', title: '选手名单', done: playerList.length >= 5,
      body: `${playerList.length ? `<div class="chips">${playerList.map(player =>
        `<span class="chip">${esc(player.name)}<small>${esc(player.position || '—')}</small></span>`).join('')}</div>` : emptyTip('还没有登记选手。')}
        <form class="filterbar" style="border:0;padding:0;background:transparent;margin-top:10px" data-player-form>
          <label class="fld"><span>选手名</span><input name="name" placeholder="比赛 ID" required></label>
          <label class="fld"><span>分路</span>
            <select name="position">${['对抗路', '打野', '中路', '发育路', '游走'].map(lane => `<option value="${lane}">${lane}</option>`).join('')}</select></label>
          <label class="fld"><span>别名</span><input name="aliases" placeholder="多个用逗号分隔"></label>
          <button type="submit" class="primary">添加选手</button>
        </form>`,
    },
    {
      key: 'auth', title: '营地授权', done: null,
      body: `<div class="block-note">营地授权在采集页完成：扫码后同步最近对局，平台会自动带入日期、阵营、胜负、比分与十人面板。</div>
        <div style="margin-top:10px"><a class="button" href="#capture">去采集页授权 →</a></div>`,
    },
    {
      key: 'import', title: '历史导入', done: matchCount > 0,
      body: `<div class="block-note">当前已入库 <b>${num(matchCount)}</b> 局。历史对局在采集页按日期范围同步。</div>
        <div style="margin-top:10px"><a class="button" href="#capture">去导入历史 →</a>
        <a class="button" href="#matches" style="margin-left:8px">查看比赛档案</a></div>`,
    },
    {
      key: 'prefill', title: '预填确认', done: (pending.fields || 0) === 0,
      body: `<div class="block-note">待确认 <b>${num(pending.fields || 0)}</b> 个字段（共 ${num(pending.total || 0)} 局）。
        营地能给的字段已自动带入，剩下的（版本、规则、训练组）需要你确认。</div>
        <div style="margin-top:10px"><button type="button" class="button" data-run-prefill>运行预填</button>
        <a class="button" href="#pending" style="margin-left:8px">打开待确认队列 →</a></div>`,
    },
  ];

  const doneCount = steps.filter(step => step.done === true).length;
  const requiredSteps = steps.filter(step => step.done !== null);
  const nextStep = requiredSteps.find(step => step.done === false);
  const stepHtml = steps.map((step, index) => `<section class="panel setup-step" id="step-${esc(step.key)}">
      <h2 class="panel-title">${index + 1}. ${esc(step.title)}
        <em>${step.done === true ? '已完成' : step.done === false ? '待完成' : '按需'}</em></h2>
      ${step.body}
    </section>`).join('');

  const nextAction = nextStep ? panel('从这一步继续', `<div class="block-note">
      建档进度 <b>${num(doneCount)} / ${num(requiredSteps.length)}</b>，当前卡在<b>「${esc(nextStep.title)}」</b>。
      ${nextStep.key === 'team' ? '先填队名，后面的选手名单才能挂到本队下。'
        : nextStep.key === 'roster' ? '至少登记 5 名选手（分路别填错），录入和分位分析都靠它认人。'
        : nextStep.key === 'import' ? '导入历史对局后，所有分析页才会有数据。' : ''}
    </div><div style="margin-top:10px"><a class="button primary" href="#step-${esc(nextStep.key)}">继续「${esc(nextStep.title)}」→</a>
      <a class="button" href="#guide" style="margin-left:8px">看使用教程</a></div>`)
    : panel('建档完成', `<div class="block-note">五步全部就绪。日常只需要：<b>采集 → 待确认 → 看分析</b>。</div>
      <div style="margin-top:10px"><a class="button primary" href="#overview">去首页看总览 →</a>
      <a class="button" href="#teams" style="margin-left:8px">战队档案</a>
      <a class="button" href="#compare" style="margin-left:8px">对比工作台</a></div>`);

  container.innerHTML = pageHero({
    kicker: 'SETUP · 建档向导',
    title: '建档向导',
    lead: ['五步把平台跑起来：战队信息 → 选手名单 → 营地授权 → 历史导入 → 预填确认。',
      '每一步都可以稍后再说；不影响采集，只影响对应分析。'],
    meta: [`${num(doneCount)} / ${num(requiredSteps.length)} 步完成`, `已入库 ${num(matchCount)} 局`],
  }) + `<div class="sd-strip">${steps.map((step, index) => `
      <a class="sd-cell ${step.done === true ? 'is-done' : step.done === false ? 'is-todo' : 'is-opt'}" href="#step-${esc(step.key)}">
        <span class="sd-state">${step.done === true ? '✓' : index + 1}</span>
        <b>${esc(step.title)}</b>
        <small>${step.done === true ? '已完成' : step.done === false ? '待完成' : '按需'}</small>
      </a>`).join('')}</div>`
    + nextAction
    + stepHtml;

  const teamForm = container.querySelector('[data-team-form]');
  if (teamForm) teamForm.onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(teamForm));
    payload.id = own?.id || 'team-own';
    await api('/api/studio/workspace/teams', payload);
    renderSetup(container, {api, isCurrent});
  };

  const playerForm = container.querySelector('[data-player-form]');
  if (playerForm) playerForm.onsubmit = async event => {
    event.preventDefault();
    const raw = Object.fromEntries(new FormData(playerForm));
    const aliases = String(raw.aliases || '').split(/[,，\s]+/).filter(Boolean);
    await api('/api/studio/workspace/players', {
      teamId: own?.id || 'team-own', name: raw.name, position: raw.position, aliases,
    });
    renderSetup(container, {api, isCurrent});
  };

  const runPrefill = container.querySelector('[data-run-prefill]');
  if (runPrefill) runPrefill.onclick = async () => {
    await api('/api/studio/workspace/prefill/run', {});
    location.hash = '#pending';
  };
}
