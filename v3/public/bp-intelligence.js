/* BP 模块内嵌研究组件：结论、条件 BP、英雄绝活、协同与真实证据。
   只消费后端可复现事实；不用前端凭终局名单编造选禁顺序。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const views = [
  ['focus', '赛训重点'], ['habits', '选禁习惯'], ['players', '选手绝活'],
  ['combos', '阵容协同'], ['changes', '近期变化'], ['sandbox', 'BP 推演']
];
const safe = (value) => String(value == null ? '' : value)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n = (value) => typeof value === 'number' && Number.isFinite(value) ? value : null;
const pct = (value) => n(value) === null ? '—' : n(value).toFixed(1) + '%';
const sign = (value) => n(value) === null ? '—' : (value > 0 ? '+' : '') + value.toFixed(1) + 'pp';
const clamp = (value) => Math.min(100, Math.max(0, n(value) || 0));
const count = (value) => (n(value) || 0).toLocaleString('zh-CN');

function evidenceRows(records) {
  const list = Array.isArray(records) ? records : [];
  if (!list.length) return '<p class="bpi-subtle">暂无可展开的逐局证据。</p>';
  return `<ol class="bpi-evidence-list">${list.map(g => {
    const title = [g.date, g.team, g.enemy ? '对阵 ' + g.enemy : '',
      g.result === null ? '胜负未知' : g.result ? '胜利' : '失利'].filter(Boolean).join(' · ');
    const href = g.source === 'scrim' ? '#match/' + encodeURIComponent(g.id) : '';
    return `<li>${href
      ? `<a href="${safe(href)}">${safe(title)}</a>`
      : `<span>${safe(title)} · 比赛 ${safe(g.matchId || g.id)}</span>`}
      </li>`;
  }).join('')}</ol>`;
}

function evidenceDetails(records, label='查看对应比赛') {
  return `<details class="bpi-evidence"><summary>${safe(label)} <span>${(records || []).length} 局记录</span></summary>
    ${evidenceRows(records)}</details>`;
}

function heroBadge(hero, icons) {
  const url = icons && icons[hero];
  const image = typeof url === 'string' && /^\/catalog\/icons\/hero-\d+\.png$/.test(url);
  return `<span class="bpi-hero" title="${safe(hero)}"><span class="bpi-hero-photo">${image
    ? `<img src="${safe(url)}" alt="" loading="lazy">`
    : safe(String(hero || '?').slice(0, 1))}</span><span>${safe(hero)}</span></span>`;
}

function shareBar(value, secondary) {
  const first = clamp(value);
  const second = clamp(secondary);
  return `<div class="bpi-share"><span class="bpi-track"><i style="width:${first}%"></i></span>
    ${n(secondary) === null ? '' :
      `<span class="bpi-base">参照 ${pct(secondary)} · <i style="width:${second}%"></i></span>`}</div>`;
}

function note(title, detail) {
  return `<div class="bpi-note"><strong>${safe(title)}</strong><p>${safe(detail)}</p></div>`;
}

function headline(report) {
  const s = report.scope || {};
  const overall = !report.team;
  const sourceTitle = report.source === 'kpl' ? 'KPL 正式比赛' : '训练赛';
  return `<div class="bpi-stats">
    <div><span>研究对局</span><b>${count(s.games)}</b><small>${safe(sourceTitle)} · 不重复计数</small></div>
    <div><span>完整 BP 顺序</span><b>${count(s.orderedGames)}</b><small>可研究选禁先后和条件回应</small></div>
    <div><span>可识别选手</span><b>${count(s.playerGames)}</b><small>可分析选手与英雄的关系</small></div>
    <div><span>${overall ? '研究范围' : '当前战队胜率'}</span><b>${overall ? '全部战队' : pct(s.winRate)}</b>
      <small>${overall ? '请选择战队研究胜率' :
        `${count(s.wins)} 胜 / ${count(s.decided)} 局有效赛果`}</small></div>
  </div>`;
}

function findingCards(report) {
  if (!report.findings?.length) return note('当前没有足够证据生成重点结论',
    '可以切换对手或正式比赛数据查看；系统不会用零星胜率编造规律。');
  const labels = {preference:'英雄偏好', response:'条件回应', change:'周期变化', combo:'阵容组合'};
  return `<div class="bpi-finding-grid">${report.findings.map((f,i)=>
    `<article class="bpi-finding">
      <div class="bpi-card-top"><span>${String(i+1).padStart(2,'0')}</span><em>${safe(labels[f.kind] || '比赛发现')}</em></div>
      <h3>${safe(f.title)}</h3><p class="bpi-finding-main">${safe(f.detail)}</p>
      <p class="bpi-subtle">${safe(f.note)}</p>
      ${evidenceDetails(f.evidence)}
    </article>`).join('')}</div>`;
}

function rankRows(items, icons, type) {
  const rows = (items || []).slice(0, 12);
  if (!rows.length) return note('暂时没有可用记录', '更换战队或时间范围后可重新查看。');
  return `<div class="bpi-ranks">${rows.map((row, i) => `<article class="bpi-rank">
    <span class="bpi-index">${String(i+1).padStart(2,'0')}</span>
    <div class="bpi-rank-main">
      <div class="bpi-rank-head">${heroBadge(row.hero,icons)}
        <strong>${count(row.games)} 局</strong><small>占 ${pct(row.share)}</small></div>
      ${shareBar(row.share, row.baselineShare)}
      <div class="bpi-rank-foot">${type === 'bans' ? '禁用倾向' :
        `该英雄出场的历史胜率 ${pct(row.winRate)} · ${count(row.decided)} 局已知赛果`}
        <span>同来源整体使用率：${pct(row.baselineShare)}</span></div>
      ${evidenceDetails(row.evidence,'查看出现的比赛')}
    </div>
  </article>`).join('')}</div>`;
}

function validationPanel(v) {
  if(!v)return `<div class="bpi-research-alert"><b>历史预测效果尚待验证</b>
    <p>需要足够多、跨多个日期的完整 BP 对局，才能用后续未参与建模的比赛检验预测是否有用。目前只展示实际历史回应。</p></div>`;
  const better=v.changePP>0;
  return `<section class="bpi-panel bpi-validation">
    <header><h3>这套规律能预测后续比赛吗？</h3><span>历史时间外验证</span></header>
    <div class="bpi-check-figures">
      <div><span>根据对手历史回应</span><strong>${pct(v.conditionalTop3)}</strong></div>
      <div><span>只按常用英雄猜测</span><strong>${pct(v.baselineTop3)}</strong></div>
      <div><span>额外提升</span><strong class="${better?'is-up':v.changePP<0?'is-down':''}">${sign(v.changePP)}</strong></div>
    </div>
    <p class="bpi-explain">先用 ${count(v.trainGames)} 局早期比赛学习，再用 ${count(v.testGames)} 局后续比赛检验；
       共 ${count(v.testCases)} 次真实选人决策，其中 ${count(v.conditionCases)} 次有足够的同条件历史记录。</p>
    <p class="bpi-subtle">${better
      ? '历史测试中条件回应比简单频率更有参考价值，但并不保证下一场命中。'
      : '本次测试尚未证明条件回应优于常用英雄频率，不能把它当成稳定预判。'}</p>
  </section>`;
}

function habitView(report) {
  return `<div class="bpi-cols">
    <section class="bpi-panel"><header><h3>最常选择的英雄</h3><span>本队或所选战队</span></header>
      <p class="bpi-explain">蓝条为当前对象的使用占比，细线为同来源全部战队的参照。</p>
      ${rankRows(report.picks, report.icons, 'picks')}</section>
    <section class="bpi-panel"><header><h3>最常禁用的英雄</h3><span>历史禁用习惯</span></header>
      <p class="bpi-explain">禁用次数反映偏好，不直接说明某英雄不可处理或具备克制关系。</p>
      ${rankRows(report.bans,report.icons,'bans')}</section></div>
    <section class="bpi-panel">
      <header><h3>对手先选后，我们如何回应？</h3><span>仅使用完整选禁事件</span></header>
      ${responseRows(report.responses,report.icons)}
    </section>${validationPanel(report.validation)}`;
}

function responseRows(responses, icons) {
  const rows = (responses || []).slice(0, 14);
  if (!rows.length) return note('当前无法可靠分析选禁顺序',
    '请确认有逐手 Ban/Pick 事件；只知道终局五人阵容不能还原对手下一手。');
  return `<div class="bpi-response-grid">${rows.map(row => `<article class="bpi-response">
    <div class="bpi-response-heroes">${heroBadge(row.trigger, icons)}
       <span class="bpi-arrow">对方先选 →</span>${heroBadge(row.response, icons)}</div>
    <div class="bpi-response-bottom"><strong>${count(row.games)} / ${count(row.opportunities)} 局</strong>
      <span>出现占比 ${pct(row.share)}</span></div>
    ${shareBar(row.share)}
    ${evidenceDetails(row.evidence,'看这几局的 BP')}
  </article>`).join('')}</div>`;
}

function matchupHtml(rows, icons) {
  const selected=(rows||[]).slice(0,8);
  if(!selected.length)return '';
  return `<section class="bpi-matchup-section"><h4 class="bpi-section-sub">历史英雄对位</h4>
    <p class="bpi-explain">同一分路的双方英雄交手记录。胜负不能直接说明对线单挑强弱。</p>
    <div class="bpi-response-grid">${selected.map(r=>`<article class="bpi-response">
      <div class="bpi-response-heroes">${heroBadge(r.hero,icons)}
      <span class="bpi-arrow">对位</span>${heroBadge(r.enemy,icons)}</div>
      <div class="bpi-response-bottom"><strong>${count(r.games)} 局</strong><span>历史赛果 ${pct(r.winRate)}</span></div>
      ${evidenceDetails(r.evidence)}
    </article>`).join('')}</div>
  </section>`;
}

function playerView(report) {
  const players = (report.players || []).slice(0, 18);
  return `<div class="bpi-panel"><header><h3>选手 · 英雄特长研究</h3><span>比较同英雄使用者</span></header>
    <p class="bpi-explain">“相对表现”使用带收缩的历史赛果估计，削弱小样本极端胜率；不将其解释为对线能力或个人因果贡献。</p>
    ${players.length ? `<div class="bpi-players">${players.map(p => `<article class="bpi-player">
      <div class="bpi-player-head">${heroBadge(p.hero,report.icons)}
        <div><b>${safe(p.player)}</b><small>${safe(p.lane || '分路待确认')}</small></div></div>
      <div class="bpi-player-signal"><span>${count(p.games)} 局 · 历史胜率 ${pct(p.winRate)}</span>
        <b class="${p.relativeSignal>0?'is-up':p.relativeSignal<0?'is-down':''}">${sign(p.relativeSignal)}</b></div>
      <p>与同英雄参照的收缩后差异 · 参照胜率 ${pct(p.reference)}</p>
      ${n(p.heroDamagePer1000Gold)!==null
        ? `<p class="bpi-player-output">终局对英雄伤害 / 千经济：<b>${count(p.heroDamagePer1000Gold)}</b>（仅做产出参考，不等于团战能力）</p>` : ''}
      ${evidenceDetails(p.evidence,'查看选手对局')}
    </article>`).join('')}</div>` :
      note('选手与英雄的身份数据不足','需要准确的选手—英雄—分路映射；不按终局五个英雄的排列猜测使用者。')}
    ${matchupHtml(report.matchups,report.icons)}
    <div class="bpi-research-alert"><b>进一步判断绝活强在哪里</b>
      <p>对线经济、补刀、转线、团战进场与资源争夺必须来自对应比赛过程。当前没有逐项真实过程证据时，不生成“对线强”“打团强”的断言。</p></div>
    </div>`;
}

function comboTiles(rows, icons, type) {
  if (!rows?.length) return note('组合样本暂时不足','完整阵容需要双方五个英雄身份可信；极少出场的组合不生成优势判定。');
  return `<div class="bpi-combo-grid">${rows.slice(0,12).map((r,i)=>`<article class="bpi-combo">
    <div class="bpi-card-top"><span>${type} · ${String(i+1).padStart(2,'0')}</span><em>${count(r.games)} 局</em></div>
    <div class="bpi-combo-heroes">${r.heroes.map(h=>heroBadge(h,icons)).join('')}</div>
    <div class="bpi-combo-metrics"><div><small>历史胜率</small><strong>${pct(r.winRate)}</strong></div>
      <div><small>单英雄参照</small><strong>${pct(r.reference)}</strong></div>
      <div><small>收缩后偏离</small><strong>${sign(r.relativeSignal)}</strong></div></div>
    ${evidenceDetails(r.evidence,'查看组合比赛')}
  </article>`).join('')}</div>`;
}

function comboView(report) {
  return `<div class="bpi-panel">
    <header><h3>双人 / 三人阵容协同</h3><span>控制小样本的探索性比较</span></header>
    <p class="bpi-explain">“偏离”表示组合历史表现相对单英雄基准的收缩后差异，不等于这套组合产生了同等因果收益，也不能只凭胜率判断克制。</p>
    <h4 class="bpi-section-sub">双人组合</h4>${comboTiles(report.pairs,report.icons,'两英雄')}
    <h4 class="bpi-section-sub">三人核心</h4>${comboTiles(report.trios,report.icons,'三英雄')}
  </div>`;
}

function seriesHtml(rows,icons) {
  if(!rows?.length)return '';
  return `<div class="bpi-series"><h4 class="bpi-section-sub">BO 系列赛：连续两局如何调整 BP？</h4>
    <p class="bpi-explain">只比较同一系列赛内相邻局的真实阵容和禁用变化；不是模型推测出的教练意图。</p>
    <div class="bpi-response-grid">${rows.slice(0,8).map(r=>`<article class="bpi-response">
      <strong>第 ${r.previous} 局 → 第 ${r.current} 局</strong>
      <div class="bpi-series-note">替换选用英雄 · ${count(r.newPicks.length)} 个</div>
      <div class="bpi-combo-heroes">${r.newPicks.map(x=>heroBadge(x,icons)).join('') || '<small>未更换</small>'}</div>
      <div class="bpi-series-note">变化禁用 · ${count(r.newBans.length)} 个</div>
      ${evidenceDetails(r.evidence,'查看两局比赛')}
    </article>`).join('')}</div>
  </div>`;
}

function changeView(report) {
  const changes = report.changes || [];
  return `<section class="bpi-panel"><header><h3>近期英雄选择发生了什么变化？</h3>
    <span>对照前半段 / 后半段比赛</span></header>
    <p class="bpi-explain">按时间将当前范围的比赛分成前后两段；这里观察的是选人比例变化，不将变化自动归因于版本、战队策略或选手状态。</p>
    ${changes.length ? `<div class="bpi-changes">${changes.map(r=>`<article class="bpi-change">
      <div class="bpi-change-title">${heroBadge(r.hero,report.icons)}
        <strong class="${r.changePP>0?'is-up':r.changePP<0?'is-down':''}">${sign(r.changePP)}</strong></div>
      <div class="bpi-two-bars">
        <label>较早比赛 · ${r.before}/${r.beforeGames} 局</label>${shareBar(r.previousShare)}
        <label>最近比赛 · ${r.after}/${r.afterGames} 局</label>${shareBar(r.recentShare)}
      </div>${evidenceDetails(r.evidence,'查看近期比赛')}
    </article>`).join('')}</div>` :
    note('当前比赛数量不足以进行周期对照','至少需要八局可按日期排序的记录；更少时只展示原始选禁，不绘制变化趋势。')}
    ${seriesHtml(report.seriesAdjustments,report.icons)}
  </section>`;
}

function counterCards(rows,icons) {
  const list=(rows||[]).slice(0,8);
  return `<section class="bpi-counter-history">
    <h4 class="bpi-section-sub">历史交手时，曾使用哪些英雄应对？</h4>
    <p class="bpi-explain">统计同一局中我方选用与敌方指定英雄的共现。不能据此证明克制或预测更换英雄后的赛果。</p>
    ${list.length ? `<div class="bpi-response-grid">${list.map(r=>`<article class="bpi-response">
      <div class="bpi-response-heroes">${heroBadge(r.candidateHero,icons)}
      <span class="bpi-arrow">对方 ${heroBadge(r.enemyHero,icons)}</span></div>
      <div class="bpi-response-bottom"><strong>${count(r.games)} / ${count(r.againstGames)} 局</strong>
      <span>实际赛果 ${pct(r.winRate)}</span></div>
      <p class="bpi-subtle">${r.decided ? `历史胜率的区间参考：${pct(r.interval[0])}–${pct(r.interval[1])}` : '没有可判断的赛果'}</p>
      ${evidenceDetails(r.evidence,'查看曾经的对抗')}
    </article>`).join('')}</div>`
    :note('没有足够的同英雄历史交手','当前来源与战队的历史样本不足，不能凭英雄印象给出反制结论。')}
  </section>`;
}

function sandboxView(report, trigger) {
  const choices = [...new Set([...(report.responses || []).map(x=>x.trigger), ...(report.counterCandidates || []).map(x=>x.enemyHero)])].sort((a,b)=>a.localeCompare(b,'zh'));
  const picked = choices.includes(trigger) ? trigger : (choices[0] || '');
  const rows = (report.responses || []).filter(x=>x.trigger===picked);
  const counters=(report.counterCandidates || []).filter(x=>x.enemyHero===picked);
  return `<section class="bpi-panel bpi-sandbox">
    <header><h3>BP 历史回应推演</h3><span>基于真实选禁顺序</span></header>
    <p class="bpi-explain">选择对方已经选出的英雄，查看所选战队过去在看到它之后的首次选用。这里不是最优阵容推荐，也没有模拟尚未打过的比赛胜率。</p>
    <div class="bpi-sandbox-controls"><label>对手已选
      <select data-bpi-trigger><option value="">选择英雄</option>${choices.map(h=>
        `<option value="${safe(h)}" ${h===picked?'selected':''}>${safe(h)}</option>`).join('')}</select>
    </label><span>只统计顺序完整的 BP 对局</span></div>
    ${picked ? `<div class="bpi-sandbox-branch">
       <div class="bpi-sandbox-node"><small>对方先选</small>${heroBadge(picked, report.icons)}</div>
       <span class="bpi-sandbox-link">我们此前的选择</span>
       <div class="bpi-sandbox-options">${responseRows(rows,report.icons)}</div></div>` :
       note('暂无可分析的历史回应','请切换到拥有完整逐手 BP 记录的赛事或战队。')}
    ${picked ? counterCards(counters,report.icons) : ""}
    <div class="bpi-research-alert"><b>下一步可用来做什么？</b><p>先看对手条件回应，再比较我方选手英雄池与阵容组合；如果没有足够相近的历史 BP 局面，必须保持“待验证”，不能捏造一条最优解。</p></div>
  </section>`;
}

export function createBpIntelligence({currentQuery=()=>''} = {}) {
  const state = {root:null, controller:null, source:'scrim', team:'本队',
    mode:'overview', view:'focus', trigger:'', report:null, error:''};

  function body() {
    const report=state.report;
    if (!report) return '<div class="bpi-loading">正在读取 BP 研究结果…</div>';
    if (!report.scope?.games) return note('当前范围没有可分析的 BP 比赛',
      '可切换正式比赛 / 训练赛，或选择其他战队。无比赛时不会显示伪造的胜率与阵容建议。');
    switch (state.view) {
      case 'habits': return habitView(report);
      case 'players': return playerView(report);
      case 'combos': return comboView(report);
      case 'changes': return changeView(report);
      case 'sandbox': return sandboxView(report,state.trigger);
      default: return `<section class="bpi-intro-brief">
          <h3>这段时间最值得关注的 BP 现象</h3>
          <p>从选禁频率、真实 BP 回应、阵容组合和周期变化中选出有比赛证据的发现。</p>
        </section>${findingCards(report)}
        <div class="bpi-shortcuts"><button type="button" data-bpi-view="habits">查看选禁路径</button>
        <button type="button" data-bpi-view="players">研究选手绝活</button>
        <button type="button" data-bpi-view="combos">研究阵容协同</button></div>`;
    }
  }

  function paint() {
    const root=state.root;
    if (!root || !root.isConnected) return;
    const report=state.report;
    const teams=report?.teams || [];
    const hasTeam=teams.some(t=>t.name===state.team);
    root.innerHTML=`<div class="bpi">
      <div class="bpi-heading"><div><span class="bpi-eyebrow">BP RESEARCH · 赛训分析</span>
        <h2>BP 情报研究</h2>
        <p>从英雄选择和比赛过程找规律，点开每项发现核查真实对局。</p></div>
        <span class="bpi-scope-note">历史事实 ≠ 反制结论</span></div>
      <div class="bpi-toolbar">
        <div class="bpi-source" role="group" aria-label="比赛来源">
          <button type="button" data-bpi-source="scrim" aria-pressed="${state.source==='scrim'}">训练赛</button>
          <button type="button" data-bpi-source="kpl" aria-pressed="${state.source==='kpl'}">KPL 正式比赛</button>
        </div>
        <label class="bpi-team-select">研究对象
          <select data-bpi-team>
            <option value="" ${!state.team?'selected':''}>${state.source==='kpl'?'联盟大盘':'全部战队'}</option>
            ${teams.map(t=>`<option value="${safe(t.name)}" ${t.name===state.team?'selected':''}>
              ${safe(t.name)} · ${count(t.games)} 局</option>`).join('')}
            ${state.team&&!hasTeam?`<option selected value="${safe(state.team)}">${safe(state.team)} · 暂无记录</option>`:''}
          </select></label>
        <span class="bpi-data-note">${report?`完整 BP ${count(report.scope?.orderedGames)} 局 · 数据不跨来源混算`:'正在读取…'}</span>
      </div>
      ${report ? headline(report) : ''}
      <div class="bpi-view-tabs" role="group" aria-label="BP 研究内容">
        ${views.map(([id,label])=>`<button type="button" data-bpi-view="${id}" aria-pressed="${id===state.view}">${label}</button>`).join('')}
      </div>
      <div class="bpi-view" aria-live="polite">${state.error ?
         note('BP 情报暂时读不到',state.error) : body()}</div>
      ${report ? `<details class="bpi-method"><summary>数据口径与研究限制</summary>
        <ul>${(report.limitations||[]).map(x=>`<li>${safe(x)}</li>`).join('')}</ul>
        <p>研究结果提供历史证据，不替代教练的赛前判断。完整因果推断、BP 博弈搜索与逐帧战术识别需要额外模型训练和时间外回测。</p>
      </details>`:''}
    </div>`;
  }

  async function load() {
    const root=state.root;
    state.controller?.abort();
    const controller=new AbortController();
    state.controller=controller;
    state.report=null; state.error=''; paint();
    const params=new URLSearchParams({source:state.source,team:state.team});
    try {
      const global=new URLSearchParams(currentQuery().replace(/^\?/,''));
      if(global.get('from'))params.set('from',global.get('from'));
      if(global.get('to'))params.set('to',global.get('to'));
      const response=await fetch(API_BASE+'/api/v3/bp-intelligence?'+params.toString(),{
        signal:controller.signal,cache:'no-store',headers:{Accept:'application/json'}});
      if(!response.ok){
        const error=await response.json().catch(()=>({}));
        throw new Error(error.detail || '数据服务暂时不可用');
      }
      const report=await response.json();
      if(controller.signal.aborted || root!==state.root) return;
      state.report=report; paint();
    } catch(error) {
      if(controller.signal.aborted || root!==state.root)return;
      state.error=error.message || '数据读取失败';paint();
    }
  }

  function bind(root) {
    if(root.dataset.bpiBound)return;
    root.dataset.bpiBound='1';
    root.addEventListener('click', event=>{
      const source=event.target.closest('[data-bpi-source]');
      if(source){
        const next=source.dataset.bpiSource;
        if(next===state.source)return;
        state.source=next;state.team=next==='scrim'?'本队':'';state.trigger='';
        void load();return;
      }
      const view=event.target.closest('[data-bpi-view]');
      if(view){
        state.view=view.dataset.bpiView;
        if(state.view==='sandbox')state.trigger='';
        paint();
      }
    });
    root.addEventListener('change', event=>{
      if(event.target.matches('[data-bpi-team]')){
        state.team=event.target.value;state.trigger='';void load();
      }
      if(event.target.matches('[data-bpi-trigger]')){
        state.trigger=event.target.value;paint();
      }
    });
  }

  function mount(root,{mode='overview',team=null}={}) {
    if(!root)return;
    if(state.root===root && state.report)return;
    state.root=root;state.mode=mode;
    state.source='scrim';
    state.team=team==null ? '本队' : team;
    state.view=mode==='team'?'habits':mode==='counter'?'sandbox':'focus';
    state.trigger='';state.report=null;state.error='';
    bind(root);void load();
  }
  return {mount};
}
