/* BP 模块内嵌研究组件：结论、条件 BP、英雄绝活、协同与真实证据。
   只消费后端可复现事实；不用前端凭终局名单编造选禁顺序。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const views = [
  ['focus', '赛前重点'], ['habits', '选禁习惯'], ['version', '版本环境'],
  ['players', '选手英雄池'], ['combos', '阵容协同'], ['counter', '阵容反制'],
  ['changes', '策略变化'], ['sandbox', 'BP 分支']
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
    // BP 原始营地编号未必是对局路由 ID；只有完成严格数据关联才生成下钻。
    const href = g.source === 'scrim' && g.processMatchKey
      ? '#match/' + encodeURIComponent(g.processMatchKey) : '';
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


function priorityView(report) {
  const rows=report.bpStudies?.priorities||[];
  if(!rows.length)return '';
  return `<section class="bpi-priorities">
    <div class="bpi-priority-title"><h3>赛前关注优先级</h3>
      <span>真实对局 · 条件对照 · 谨慎判断</span></div>
    <div class="bpi-priority-grid">${rows.map((r,i)=>`<article class="bpi-priority">
      <div class="bpi-card-top"><span>${String(i+1).padStart(2,'0')}</span>
        <em class="${r.level==='重点'?'is-up':''}">${safe(r.level)}</em></div>
      <h4>${safe(r.title)}</h4>
      <p>${safe(r.detail)}</p>
      <div class="bpi-priority-action"><strong>赛前怎么用</strong><span>${safe(r.action)}</span></div>
      ${evidenceDetails(r.evidence, '核查实际比赛')}
    </article>`).join('')}</div>
  </section>`;
}


function scrimPreviousHistory(planner){
  if(planner.game===1)return [];
  const lines=text=>text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  const own=lines(planner.historyOwn),enemy=lines(planner.historyEnemy);
  if(own.length!==planner.game-1||enemy.length!==planner.game-1){
    throw new Error('第 '+planner.game+' 局需要双方此前 '+(planner.game-1)+' 局的完整选人记录（一行一局）。');
  }
  const parse=line=>line.split(/[，,、\s]+/).filter(Boolean);
  return own.map((line,i)=>{
    const a=parse(line),b=parse(enemy[i]);
    if(a.length!==5||b.length!==5){
      throw new Error('第 '+(i+1)+' 局双方每行都必须各有 5 个英雄，以逗号分隔。');
    }
    return {game:i+1,picks:{'本队':a,'对手':b}};
  });
}

function scrimHeroButtons(planner){
  const snap=planner.snapshot;
  if(!snap?.nextAction)return '';
  const all=snap.legalCandidates||[];
  const query=planner.search.trim().toLowerCase();
  const matched=query?all.filter(h=>h.toLowerCase().includes(query)):all;
  const visible=matched.slice(0,36);
  const icons=planner.catalog?.icons||{};
  return `<div class="bpi-scrim-result-count">合法候选 ${count(all.length)} 个
     ${query?' · 匹配 '+count(matched.length)+' 个':''}，${matched.length>36?'显示前 36 个，搜索可查看更多':''}</div>
    <div class="bpi-scrim-herolist">${visible.map(hero=>`<button type="button"
      data-bpi-scrim-hero="${safe(hero)}">${heroBadge(hero,icons)}</button>`).join('')}</div>
    ${!matched.length?'<p class="bpi-subtle">没有匹配的合法英雄；请调整搜索或上一手选择。</p>':''}`;
}

function scrimPlannerView(planner){
 const next=planner.snapshot?.nextAction;
 const maxGames={BO3:3,BO5:5,BO7:7}[planner.bo]||3;
 const ownSide=planner.side==='blue'?'1':'2';
 const acting=next?(next.camp===ownSide?'本队':'对手'):'';
 const previous=planner.snapshot?.historyPickCounts;
 return `<section class="bpi-panel bpi-scrim-panel">
   <header><h3>训练赛 · BO 全局 BP 合法选禁沙盘</h3><span>15 手 · 仅训练赛规则</span></header>
   <p class="bpi-explain">每局先 Ban：蓝 → 红 → 蓝 → 红 → 蓝（共 5 个 Ban）；
     再 Pick：蓝 1 → 红 2 → 蓝 2 → 红 2 → 蓝 2 → 红 1（共 10 个 Pick）。
     BO3 / BO5 / BO7 中，两队分别不能重复选择自己本系列赛此前已经 Pick 的英雄；换边后继续生效。</p>
   <div class="bpi-scrim-settings">
     <label>系列赛制<select data-bpi-scrim-bo>
       ${['BO3','BO5','BO7'].map(x=>`<option value="${x}" ${x===planner.bo?'selected':''}>${x}</option>`).join('')}
     </select></label>
     <label>第几局<select data-bpi-scrim-game>
       ${Array.from({length:maxGames},(_,i)=>i+1).map(i=>`<option value="${i}" ${i===planner.game?'selected':''}>第 ${i} 局</option>`).join('')}
     </select></label>
     <label>本队阵营<select data-bpi-scrim-side>
       <option value="blue" ${planner.side==='blue'?'selected':''}>蓝方</option>
       <option value="red" ${planner.side==='red'?'selected':''}>红方</option>
     </select></label>
   </div>
   ${planner.game>1?`<div class="bpi-scrim-history">
     <strong>此前已完成的 ${planner.game-1} 局选人</strong>
     <p class="bpi-explain">一行对应一局，每行 5 个英雄，用逗号分隔。按稳定战队身份填写，换边也不要交换输入框。此处只核对录入的一致性，尚未自动与比赛 ID 比对。</p>
     <div class="bpi-scrim-history-columns">
       <label>本队此前 Pick 英雄
         <textarea data-bpi-scrim-history-own rows="3" placeholder="例如：花木兰，镜，小乔，公孙离，张飞">${safe(planner.historyOwn)}</textarea></label>
       <label>对手此前 Pick 英雄
         <textarea data-bpi-scrim-history-enemy rows="3" placeholder="例如：马超，赵云，沈梦溪，孙尚香，太乙真人">${safe(planner.historyEnemy)}</textarea></label>
     </div>
     <button class="bpi-scrim-apply" type="button" data-bpi-scrim-validate>校验录入历史的格式与禁复用</button>
     ${previous?`<span class="bpi-scrim-proof">已通过录入一致性检查：本队 ${count(previous['本队'])} 个 · 对手 ${count(previous['对手'])} 个（不代表已与真实比赛匹配）</span>`:''}
   </div>`:''}
   ${planner.error?`<div class="bpi-scrim-error" role="alert">${safe(planner.error)}</div>`:''}
   <div class="bpi-scrim-stage">
      <div><span>本局已完成 ${planner.events.length} / 15 手</span>
        <b>${next?`第 ${next.order} 手 · ${acting}（${next.camp==='1'?'蓝方':'红方'}）${next.action==='ban'?'Ban':'Pick'}`:
           planner.snapshot?'本局 BP 已完成':'需要校验后继续'}</b></div>
      <div class="bpi-scrim-progress"><i style="width:${planner.events.length/15*100}%"></i></div>
   </div>
   <div class="bpi-scrim-history-steps">
      ${planner.events.map(ev=>`<span><b>${ev.order}.</b> ${ev.camp==='1'?'蓝':'红'}${ev.action==='ban'?'禁':'选'} ${safe(ev.hero)}</span>`).join('')||
        '<p class="bpi-subtle">本局还没有选禁操作，准备开始第一手 Ban。</p>'}
   </div>
   <div class="bpi-scrim-actionbar">
     <button type="button" data-bpi-scrim-back ${!planner.events.length?'disabled':''}>撤回上一步</button>
     <button type="button" data-bpi-scrim-reset ${!planner.events.length?'disabled':''}>重置本局</button>
     ${planner.snapshot&&!next&&planner.game<maxGames?
       '<button type="button" data-bpi-scrim-next-game>保存本局选人并进入下一局</button>':''}
     ${planner.loading?'<span>正在校验合法动作…</span>':''}
   </div>
   ${next?`<div class="bpi-scrim-picklist">
      <div class="bpi-scrim-pickhead"><strong>选择这一手的合法英雄</strong>
        <span>当前所有已禁/已选英雄不可再次操作</span></div>
      <input type="search" data-bpi-scrim-search value="${safe(planner.search)}"
       placeholder="搜索英雄名称…" aria-label="搜索合法 BP 英雄">
      <div data-bpi-scrim-candidates>${scrimHeroButtons(planner)}</div>
   </div>`:
     planner.snapshot?`<div class="bpi-scrim-finished">双方各完成 5 次 Pick，本局选禁结束。
       ${planner.game===maxGames?'BO 系列赛所有可选局次已到达上限。':'可将这一局的选人加入全局历史后开始下一局。'}</div>`:
     '<p class="bpi-subtle">完成系列赛历史校验后，将显示下一手的合法英雄。</p>'}
   <div class="bpi-research-alert"><b>规则校验 ≠ 最优阵容建议</b>
     <p>这是训练赛专属的合法动作校验与全局 BP 交互工具。目前尚未绑定选手个人英雄池时，候选只代表规则允许，不代表选手熟练；也不把当前搜索结果称作 MCTS 最优 BP。</p>
   </div>
 </section>`;
}

function fullDraftView(report, nodeId) {
  const d=report.bpStudies?.draftTree||{};
  const nodes=d.nodes||[];
  if(!nodes.length||!report.team)return note('请先选择具有完整逐手 BP 记录的战队',
     '从真实逐手选禁中构造决策树；没有顺序的终局名单不会生成推演分支。');
  const ids=new Map(nodes.map(n=>[n.id,n]));
  let cur=ids.get(nodeId)||ids.get(0);
  if(!cur)return note('当前数据无法生成决策树','请选择其他版本或对手。');
  const chain=[];
  let cursor=cur;
  while(cursor && cursor.id!==0){
    chain.unshift(cursor);
    cursor=ids.get(cursor.parent);
  }
  const next=nodes.filter(n=>n.parent===cur.id).sort((a,b)=>b.games-a.games).slice(0,15);
  const explored=d.indexedGames||0;
  const actorName=actor=>actor==='team'?'目标战队':'对方战队';
  const stepName=(n)=>`${actorName(n.actor)}${n.action==='pick'?'选择':'禁用'}`;
  return `<section class="bpi-panel bpi-tree-panel">
    <header><h3>完整 BP 历史决策树</h3>
      <span>${count(explored)} 局索引 · ${count(d.orderedGames)} 局完整顺序</span></header>
    <p class="bpi-explain">从实际第一手开始逐轮点击，直到整套 BP 完成。每条路径均存在于历史数据；${d.limited?'为控制页面体积，仅取近期一部分完整比赛。':'按当前战队和筛选范围展示。'}</p>
    <div class="bpi-tree-toolbar">
      <button type="button" data-bpi-tree-reset ${cur.id===0?'disabled':''}>回到第一手</button>
      <button type="button" data-bpi-tree-back ${cur.id===0?'disabled':''}>上一步</button>
      <span>当前分支包含 ${count(cur.games)} 场真实比赛</span>
    </div>
    <div class="bpi-tree-path">
      <span>起点</span>
      ${chain.map((n,i)=>`<button type="button" data-bpi-tree-node="${n.id}" title="查看该步的后续选择">
        <small>${i+1} · ${safe(actorName(n.actor))}</small>
        <span>${heroBadge(n.hero,report.icons)}</span>
        <small>${n.action==='pick'?'Pick':'Ban'}</small>
      </button>`).join('')}
    </div>
    <div class="bpi-tree-current">
      <div><strong>${next.length?'历史下一手选择':'这一分支的 BP 已结束'}</strong>
        <span>${next.length?'点击任一实际出现过的选禁，继续研究后续分支。':'可打开比赛依据或返回上一步比较其他选择。'}</span></div>
      ${next.length?`<div class="bpi-tree-options">${next.map(n=>`<button type="button" data-bpi-tree-node="${n.id}">
        <span class="bpi-tree-option-top">${safe(stepName(n))}<b>${count(n.games)} 场</b></span>
        ${heroBadge(n.hero,report.icons)}
        ${shareBar(cur.games?Math.round(n.games/cur.games*1000)/10:0)}
        <small>占当前历史分支 ${cur.games?pct(n.games*100/cur.games):'—'}</small>
      </button>`).join('')}</div>`:''}
    </div>
    ${evidenceDetails(cur.evidence, '查看当前 BP 路径对应比赛')}
    <div class="bpi-research-alert"><b>这是多轮历史推演，不是自动求解最优 BP</b>
      <p>只能沿真实比赛出现过的分支前进，不能给未观察到的英雄组合编造胜率。分支频率反映过去的选择习惯；样本数量越少，结论越不稳定。</p></div>
  </section>`;
}

function findingCards(report) {
  if (!report.findings?.length) return note('当前没有足够证据生成重点结论',
    '可以切换对手或正式比赛数据查看；系统不会用零星胜率编造规律。');
  const labels = {preference:'英雄偏好', response:'条件回应', change:'周期变化',
    combo:'阵容组合', process:'比赛节奏', 'hero-outcome':'战绩异动',
    patch:'版本变化', priority:'首手优先级', pool:'选手英雄集中'};
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


function banResponseRows(items,icons) {
  if (!items?.length)return note('被禁用后的选人样本不足',
    '需要有完整 BP 顺序且同一禁用条件至少出现两局；不能根据终局名单猜测对手想拿哪个英雄。');
  return `<div class="bpi-response-grid">${items.slice(0,10).map(r=>`<article class="bpi-response">
    <div class="bpi-response-heroes">${heroBadge(r.trigger,icons)}
      <span class="bpi-arrow">对方禁用 →</span>${heroBadge(r.response,icons)}</div>
    <div class="bpi-response-bottom"><strong>${count(r.games)} / ${count(r.opportunities)} 局</strong>
      <span>出现占比 ${pct(r.share)}</span></div>
    ${shareBar(r.share)}
    ${evidenceDetails(r.evidence,'查看实际 BP')}
  </article>`).join('')}</div>`;
}

function fullLineupRows(rows,icons) {
  if(!rows?.length)return note('没有完整五人阵容','只有双方选人身份完整、胜负已记录的比赛才可研究整套阵容。');
  return `<div class="bpi-lineups">${rows.slice(0,10).map(r=>`<article class="bpi-lineup">
    <div class="bpi-combo-heroes">${r.heroes.map(h=>heroBadge(h,icons)).join('')}</div>
    <div class="bpi-lineup-metrics"><strong>${count(r.games)} 局</strong>
      <span>历史胜率 ${pct(r.winRate)} · ${count(r.wins)} / ${count(r.decided)} 胜</span>
      ${r.decided? `<small>95% 区间 ${pct(r.interval?.[0])}–${pct(r.interval?.[1])}</small>`:''}
    </div>${evidenceDetails(r.evidence,'查看完整阵容的对局')}
  </article>`).join('')}</div>`;
}


function sideRoundView(study, icons, activeSide) {
  const sides=study?.sides || [];
  if(!sides.length)return note('暂无蓝红方对照','请选择有真实 BP 记录的战队。');
  const rounds=(study?.rounds || []).filter(r=>r.side===activeSide);
  const stage=[...new Set(rounds.filter(r=>r.action==='pick').map(r=>r.round))];
  return `<section class="bpi-panel">
    <header><h3>蓝方和红方，选禁习惯一样吗？</h3><span>只比较当前战队</span></header>
    <div class="bpi-side-tiles">${sides.map(row=>`<div class="bpi-side-card">
      <div><b>${safe(row.label)}</b><span>${count(row.games)} 局</span></div>
      <strong>${pct(row.winRate)}</strong>
      <small>${count(row.wins)} / ${count(row.decided)} 胜 · 胜率区间 ${row.interval ? pct(row.interval[0]) + '–' + pct(row.interval[1]) : '—'}</small>
      ${evidenceDetails(row.evidence, '查看该侧比赛')}
    </div>`).join('')}</div>
    <p class="bpi-explain">不同边的胜率可能受阵容、对手和场次影响，不代表蓝红方本身造成了胜率差。</p>
    <div class="bpi-round-head">
      <h4>逐轮英雄优先级</h4>
      <div class="bpi-round-toggle" role="group" aria-label="蓝红方筛选">
        <button type="button" data-bpi-side="1" aria-pressed="${activeSide==='1'}">蓝方</button>
        <button type="button" data-bpi-side="2" aria-pressed="${activeSide==='2'}">红方</button>
      </div>
    </div>
    ${stage.length ? `<div class="bpi-round-list">${stage.map(step=>{
       const picks=rounds.filter(r=>r.action==='pick'&&r.round===step)
         .sort((a,b)=>b.games-a.games).slice(0,4);
       return `<div class="bpi-round-block">
         <div class="bpi-round-label">第 ${step} 次选用</div>
         <div class="bpi-round-entries">${picks.map(row=>`<article>
           <div>${heroBadge(row.hero,icons)}<b>${count(row.games)} / ${count(row.opportunities)} 局</b></div>
           ${shareBar(row.share)}${evidenceDetails(row.evidence,'比赛依据')}
         </article>`).join('')}</div>
       </div>`;
    }).join('')}</div>` :
      note('没有足够的完整顺序记录','必须先取得经过校验的逐手 Pick/Ban 事件，才会统计每一轮的英雄。')}
    <details class="bpi-method"><summary>查看各次禁用的英雄</summary>
      <div class="bpi-round-entries">${rounds.filter(r=>r.action==='ban'&&r.games>=2)
        .slice(0,20).map(row=>`<article><div>${heroBadge(row.hero,icons)}
          <small>第 ${row.round} 次禁用</small><b>${count(row.games)} / ${count(row.opportunities)} 局</b></div>
          ${shareBar(row.share)}${evidenceDetails(row.evidence,'BP 证据')}</article>`).join('') ||
          '没有足够的多场次禁用记录'}</div>
    </details>
  </section>`;
}

function versionView(report){
  const v=report.bpStudies?.version||{};
  const options=v.options||[];
  return `<section class="bpi-panel">
    <header><h3>版本环境与英雄优先级</h3><span>比较真实游戏版本</span></header>
    <p class="bpi-explain">当前范围有明确游戏版本标签 ${count(v.coverage?.knownGames)} / ${count(v.coverage?.games)} 局。缺失版本的比赛不参与跨版本比较，不把赛事年份当作游戏版本。</p>
    <div class="bpi-version-list">${options.map(row=>`<div class="bpi-version-chip">
      <b>${safe(row.name)}</b><span>${count(row.games)} 局</span>
      <small>最近记录 ${safe(row.lastDate||'—')}</small></div>`).join('')||
      '<p class="bpi-subtle">现有数据未包含可用的游戏版本字段，需要先接入真实 patch 标识。</p>'}</div>
    <h4 class="bpi-section-sub">最近两个已知版本的选禁变化</h4>
    ${v.available ? `<p class="bpi-explain">${safe(v.before)} → ${safe(v.after)}。仅比较同一战队、同一来源的选禁比例。</p>
      <div class="bpi-version-rows">${v.changes.map(row=>`<article class="bpi-version-row">
        <div>${heroBadge(row.hero,report.icons)}
          <span>${row.action==='pick'?'选用':'禁用'}</span>
          <b class="${row.changePP>0?'is-up':row.changePP<0?'is-down':''}">${sign(row.changePP)}</b></div>
        <div class="bpi-period-bar"><small>${safe(v.before)} · ${count(row.oldCount)} / ${count(row.oldGames)} 局</small>${shareBar(row.oldShare)}</div>
        <div class="bpi-period-bar"><small>${safe(v.after)} · ${count(row.newCount)} / ${count(row.newGames)} 局</small>${shareBar(row.newShare)}</div>
        ${row.action==='pick'&&row.oldDecided&&row.newDecided?
          `<p class="bpi-subtle">历史胜率：${pct(row.oldWinRate)} → ${pct(row.newWinRate)}
            · 有效赛果 ${count(row.oldDecided)} / ${count(row.newDecided)} 局。出场条件不同，不能据此证明英雄被加强或削弱。</p>`:''}
        ${evidenceDetails(row.evidence,'查看当前版本比赛')}
      </article>`).join('')||
        '<p class="bpi-subtle">两个版本均有记录，但还不足以得出稳定的优先级变化。</p>'}</div>`:
      note('暂时无法做跨版本比较','需要至少两个不同的真实游戏版本，且各自有足够场次。')}
  </section>`;
}

function poolView(report){
 const rows=report.bpStudies?.players || [];
 return `<section class="bpi-panel">
   <header><h3>选手英雄池：谁常用什么？</h3><span>已确认选手—英雄对应</span></header>
   <p class="bpi-explain">查看英雄池宽度、常用英雄和历史表现。单凭常用或高胜率，不能直接定义绝活或英雄限制优先级。</p>
   ${rows.length?`<div class="bpi-pool-grid">${rows.slice(0,15).map(r=>`<article class="bpi-pool">
     <header><div><h4>${safe(r.player)}</h4><small>${safe(r.team)} · ${safe(r.lane||'分路未知')}</small></div>
       <span>${count(r.uniqueHeroes)} 个英雄 · ${count(r.games)} 局</span></header>
     ${r.heroes.slice(0,6).map(h=>`<div class="bpi-pool-row">
       ${heroBadge(h.hero,report.icons)}
       <div>${shareBar(h.share)}<small>${count(h.games)} 局 · 胜率 ${pct(h.winRate)}</small></div>
       ${evidenceDetails(h.evidence,'对局')}
     </div>`).join('')}
   </article>`).join('')}</div>`:
   note('缺少经过核验的选手英雄数据','需要明确选手身份与每局使用英雄的对应关系。')}
 </section>`;
}

function matchupsView(report){
 const rows=report.bpStudies?.matchups || [];
 const own=report.bpStudies?.ownVsTarget || {};
 const bySize=(size,data=rows)=>(data||[]).filter(r=>r.size===size).slice(0,size===5?5:8);
 const section=(size,title,data=rows)=>`<section class="bpi-panel">
   <header><h3>${title}</h3><span>真实对局 · ${size} 英雄对方核心</span></header>
   <p class="bpi-explain">仅统计对方阵容包含这些英雄时，我方实际使用过的应对英雄和历史胜负。没有发生过的 BP 选择不能据此预测效果。</p>
   ${bySize(size,data).length?`<div class="bpi-matchups-grid">${bySize(size,data).map(r=>`<article class="bpi-matchup">
     <div class="bpi-matchup-core">${r.enemyCore.map(h=>heroBadge(h,report.icons)).join('')}
       <span>对方核心</span></div>
     <div class="bpi-matchup-response"><span>曾选用</span>${heroBadge(r.candidate,report.icons)}</div>
     <div class="bpi-matchup-stats"><b>${count(r.games)} / ${count(r.opportunities)} 局</b>
       <span>历史 ${count(r.wins)} / ${count(r.decided)} 胜 · ${pct(r.winRate)}</span></div>
     ${evidenceDetails(r.evidence,'核查历史交手')}
   </article>`).join('')}</div>`:
   note('目前没有足够的同阵容对抗记录','需要更多真实交手；未发生过的阵容不能给出假胜率。')}
 </section>`;
 const ourPreview=(report.source==='scrim'&&report.team!=='本队'&&report.team) ?
   `<section class="bpi-panel"><header><h3>本队面对 ${safe(report.team)} 时，曾怎样应对？</h3>
      <span>本队真实训练赛 · ${count(own.games)} 局</span></header>
      <p class="bpi-explain">${safe(own.reason||'')}
        本队英雄池已知 ${count(own.ownPool?.length)} 个常见英雄，历史选择不能冒充新 BP 的胜率预测。</p>
      ${own.games<2?note('目前对抗样本不足','不足两局时仅保留对局事实，不生成成套反制排序。'):
        section(2,'本队曾用的英雄，应对对方双英雄核心',own.candidates)}
     </section>`:'' ;
 return ourPreview+section(2,'该战队历史对阵双英雄核心的选择')+
   section(3,'该战队历史对阵三英雄核心的选择')+
   section(5,'该战队历史完整阵容交手');
}

function twoStepView(report, trigger){
 const rows=report.bpStudies?.twoStep||[];
 const selected=rows.find(x=>x.trigger===trigger)||rows[0];
 if(!selected)return note('暂无完整后续 BP 分支','需要至少出现过一次对手 Pick → 我方 Pick → 对方下一次 Pick 的真实顺序。');
 const group=[...new Set(rows.map(r=>r.trigger))];
 return `<section class="bpi-panel">
   <header><h3>两步 BP 历史分支</h3><span>实际发生过的下一手</span></header>
   <div class="bpi-sandbox-controls"><label>对方先选
     <select data-bpi-trigger><option value="">选择英雄</option>
       ${group.map(h=>`<option value="${safe(h)}" ${selected.trigger===h?'selected':''}>${safe(h)}</option>`).join('')}
     </select></label><span>只根据完整合法的历史逐手记录</span></div>
   <div class="bpi-branch-trigger">${heroBadge(selected.trigger,report.icons)}
     <span>→ 我方选择 → 对方再选</span><small>${count(selected.games)} 局出现此触发</small></div>
   <div class="bpi-branches">${selected.branches.map(b=>`<article class="bpi-branch">
     <div>${heroBadge(b.ownPick,report.icons)}<span>→</span>${heroBadge(b.enemyNext,report.icons)}</div>
     <strong>${count(b.games)} / ${count(b.opportunities)} 局</strong>
     <small>在该回应后对方选此英雄，占 ${pct(b.share)}</small>
     ${shareBar(b.share)}${evidenceDetails(b.evidence,'核查此分支')}
   </article>`).join('')}</div>
   <div class="bpi-research-alert"><b>历史分支不等于最优 BP</b>
     <p>这里未模拟未发生的英雄替换，也未声称已获得完整规则搜索或对局收益预测；完整 BP 博弈需在合法英雄池与严格回测通过后才可启用。</p></div>
 </section>`;
}


function conditionalPolicyView(report){
 const v=report.bpStudies?.nextPickPolicy||{};
 return `<section class="bpi-panel">
   <header><h3>对手下一手，真的能预测得更准吗？</h3>
     <span>蓝红方 × 选人轮次 × 对手已选英雄</span></header>
   <p class="bpi-explain">将历史比赛按日期分为学习与测试两段：普通基线只看蓝红方和第几次选人，条件模型额外考虑对手之前已经选出的英雄。两者只预测当时尚未被选禁的英雄。</p>
   ${v.status==='tested' ? `<div class="bpi-model-compare">
     <div><small>普通选人预测 · Top-3</small><strong>${pct(v.baselineTop3)}</strong></div>
     <div><small>条件选人预测 · Top-3</small><strong>${pct(v.conditionTop3)}</strong></div>
     <div><small>未见比赛差异</small><strong class="${v.supported?'is-up':''}">${sign(v.gainPP)}</strong></div>
   </div><p class="bpi-subtle">前期训练 ${count(v.trainGames)} 局，后期测试 ${count(v.testGames)} 局 ·
     测试 ${count(v.testDecisions)} 次实际选择 · 有条件样本覆盖 ${pct(v.coverage)}。
     ${safe(v.reason)}</p>` :
     note('条件预测暂无足够数据',v.reason||'需要足够多的完整逐手 BP 和多个不同日期。')}
   ${v.contexts?.length ? `<h4 class="bpi-section-sub">历史上出现过的条件选人规律</h4>
     <div class="bpi-policy-contexts">${v.contexts.slice(0,10).map(r=>`<article class="bpi-policy-context">
       <div class="bpi-card-top"><span>${r.side==='1'?'蓝方':'红方'} · 第 ${count(r.slot)} 次选用</span>
         <em>样本 ${count(r.decisions)} 次</em></div>
       <p class="bpi-policy-premise">对方之前选过 ${heroBadge(r.opponentHero,report.icons)}</p>
       ${r.options.map(opt=>`<div class="bpi-policy-option">
         ${heroBadge(opt.hero,report.icons)}<b>${count(opt.games)} / ${count(r.decisions)} 次</b>
         <span>${pct(opt.share)}</span></div>`).join('')}
       ${evidenceDetails(r.evidence,'查看训练集比赛')}
     </article>`).join('')}</div>`:''}
   <div class="bpi-research-alert"><b>预测能力不是 BP 方案收益</b>
     <p>即便下一手命中率更高，也不表示这些英雄就是我方最好的选择；只有后续日期的测试结果才能用于判断对手行为模型是否有效。</p></div>
 </section>`;
}

function habitView(report, activeSide) {
  return sideRoundView(report.bpStudies?.draft,report.icons,activeSide) + `<div class="bpi-cols">
    <section class="bpi-panel"><header><h3>最常选择的英雄</h3><span>本队或所选战队</span></header>
      <p class="bpi-explain">蓝条为当前对象的使用占比，细线为同来源全部战队的参照。</p>
      ${rankRows(report.picks, report.icons, 'picks')}</section>
    <section class="bpi-panel"><header><h3>最常禁用的英雄</h3><span>历史禁用习惯</span></header>
      <p class="bpi-explain">禁用次数反映偏好，不直接说明某英雄不可处理或具备克制关系。</p>
      ${rankRows(report.bans,report.icons,'bans')}</section></div>
    <section class="bpi-panel">
      <header><h3>对手先选后，我们如何回应？</h3><span>仅使用完整选禁事件</span></header>
      ${responseRows(report.responses,report.icons)}
    </section>
    <section class="bpi-panel"><header><h3>对手禁掉某英雄后，我们第一时间拿了谁？</h3>
      <span>真实选禁事件 · 不能推断意图</span></header>
      <p class="bpi-explain">只展示禁用发生后下一次实际选用的英雄，不把它叫作唯一替代英雄。</p>
      ${banResponseRows(report.banResponses,report.icons)}
    </section>${conditionalPolicyView(report)}${validationPanel(report.validation)}`;
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


function interactionPanel(study) {
  const m=study||{};
  const tested=m.status==='tested';
  return `<section class="bpi-panel">
    <header><h3>英雄组合是否真的提供额外信息？</h3><span>复杂模型必须经过未来比赛验证</span></header>
    <p class="bpi-explain">同时比较基础模型（蓝红方、单英雄、对手、已知版本）与增加双英雄、三英雄及敌我英雄交互的模型；严格按比赛日期切分训练和测试，不把全部历史训练结果当验证结果。</p>
    ${tested ? `<div class="bpi-model-compare">
      <div><small>普通英雄模型 · Brier</small><strong>${Number(m.baseline?.brier).toFixed(4)}</strong></div>
      <div><small>加入组合交互 · Brier</small><strong>${Number(m.extended?.brier).toFixed(4)}</strong></div>
      <div><small>历史时间外评估</small><strong class="${m.improved?'is-up':'is-down'}">${m.improved?'得到增量支持':'尚未超越基线'}</strong></div>
    </div>
    <p class="bpi-subtle">训练 ${count(m.train)} 局，后续测试 ${count(m.test)} 局；只有 Brier 和 Log Loss 均改善时才显示交互信号。${safe(m.reason)}</p>`:
      note('样本不足，暂不显示高阶英雄协同排名',m.reason||
        '需要足够的已知胜负与不同日期对局，否则高阶模型可能只记住历史阵容。')}
    ${m.improved && m.signals?.length ? `<div class="bpi-signal-grid">${m.signals.slice(0,12).map(r=>`<article class="bpi-signal">
      <span>${r.type==='pair'?'双英雄组合':r.type==='trio'?'三英雄组合':'敌我英雄交互'}</span>
      <div>${r.heroes.map(h=>heroBadge(h,null)).join('')}</div>
      <strong class="${r.coefficient>0?'is-up':'is-down'}">${safe(r.interpretation)}</strong>
      <small>训练集出现 ${count(r.trainGames)} 局 · 正则化系数 ${Number(r.coefficient).toFixed(3)}</small>
    </article>`).join('')}</div>`:''}
    <div class="bpi-research-alert"><b>这些不是确定的英雄克制关系</b>
      <p>模型的交互系数代表在已知记录及当前模型结构下的额外相关信号；不能直接推算更换英雄后的获胜概率。测试失败或样本不足时，系统不输出“强协同”结论。</p></div>
  </section>`;
}

function comboView(report) {
  return `<div class="bpi-panel">
    <header><h3>双人 / 三人阵容协同</h3><span>控制小样本的探索性比较</span></header>
    <p class="bpi-explain">“偏离”表示组合历史表现相对单英雄基准的收缩后差异，不等于这套组合产生了同等因果收益，也不能只凭胜率判断克制。</p>
    <h4 class="bpi-section-sub">双人组合</h4>${comboTiles(report.pairs,report.icons,'两英雄')}
    <h4 class="bpi-section-sub">三人核心</h4>${comboTiles(report.trios,report.icons,'三英雄')}
    <h4 class="bpi-section-sub">完整五人阵容的实战表现</h4>
    <p class="bpi-explain">列出真实出现过的五人阵容、胜负与小样本区间，不把一次胜利当作稳定强势。</p>
    ${fullLineupRows(report.fullLineups,report.icons)}
  </div>${interactionPanel(report.bpStudies?.interactions)}`;
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


function goldDiff(value) {
  return n(value) === null ? '暂无可用数据' :
    (value > 0 ? '+' : '') + Math.round(value).toLocaleString('zh-CN');
}

function processView(report) {
  const x=report.processStudy || {};
  const at=x.checkpoints || {};
  const timeline=[['120','2 分钟'],['240','4 分钟'],['600','10 分钟']];
  const hasData=timeline.some(([key])=>(at[key]?.games||0)>0);
  const cells=timeline.map(([key,name])=>{
    const row=at[key] || {};
    return `<article class="bpi-stage">
      <span class="bpi-stage-title">${name} · 双方队伍经济差</span>
      <strong class="bpi-stage-value ${row.meanDiff>0?'is-up':row.meanDiff<0?'is-down':''}">
        ${goldDiff(row.meanDiff)}</strong>
      <div class="bpi-stage-meta">有效 ${count(row.games)} 局 · 领先占比 ${pct(row.aheadRate)}</div>
      ${row.aheadDecided ? `<div class="bpi-stage-meta">领先的 ${count(row.aheadDecided)} 局里，
        ${count(row.aheadWins)} 局最终获胜（${pct(row.leadConversion)}）</div>`:''}
      ${shareBar(row.aheadRate)}
      ${evidenceDetails(row.evidence,'查看阶段经济对应比赛')}
    </article>`;
  }).join('');
  const players=(x.playerLanes || []).filter(v=>v.n4||v.n10).slice(0,18);
  const heroTempo=(x.heroTempo || []).slice(0,10);
  return `<div class="bpi-panel">
    <header><h3>一套阵容拿到后，前中期怎么打？</h3><span>BP × 回放经济时间轴</span></header>
    <p class="bpi-explain">只统计完成双方阵容和回放身份校验的对局。匹配成功 ${count(x.linkedGames)} /
      ${count(report.scope?.games)} 局；经济差为所选战队减对方战队。</p>
    ${hasData ? `<div class="bpi-stage-grid">${cells}</div>` :
      note('没有足够可信的比赛过程数据',
        '比赛阵容能统计，但必须匹配到同日、同阵营、十个英雄相同的唯一回放后，才能展示 2/4/10 分钟经济差。')}
    <h4 class="bpi-section-sub">选手对位：究竟在哪个阶段经济落后？</h4>
    <p class="bpi-explain">只有明确双方同路英雄，并存在同一时点的个人经济快照，才计算同路经济差。
      对线经济落后也可能来自换线和支援，不能直接贴“对线弱”标签。</p>
    ${players.length ? `<div class="bpi-lane-grid">${players.map(row=>`<article class="bpi-lane">
      <div class="bpi-lane-head">${heroBadge(row.hero,report.icons)}
         <strong>${safe(row.player)}</strong><small>${safe(row.lane)}</small></div>
      <div class="bpi-lane-metrics">
        <div><span>4 分钟同路经济差</span><strong>${goldDiff(row.diff4)}</strong>
             <small>有效 ${count(row.n4)} 局</small></div>
        <div><span>10 分钟同路经济差</span><strong>${goldDiff(row.diff10)}</strong>
             <small>有效 ${count(row.n10)} 局</small></div>
      </div>
      ${evidenceDetails(row.evidence,'查看同路对位比赛')}
    </article>`).join('')}</div>` :
    note('尚无可以核验的个人经济快照','需要同时确认选手、英雄、分路和双方个人经济；不会用队伍经济推算个人经济。')}
    <h4 class="bpi-section-sub">不同英雄阵容的 10 分钟节奏</h4>
    ${heroTempo.length ? `<div class="bpi-tempo-list">${heroTempo.map(row=>`<div class="bpi-tempo-row">
      ${heroBadge(row.hero,report.icons)}<strong>${goldDiff(row.avgTeamDiff10)}</strong>
      <small>${count(row.processGames)} 局过程 / ${count(row.games)} 局选用</small>
      ${evidenceDetails(row.evidence,'过程证据')}
    </div>`).join('')}</div>` :
    note('暂无能比较的阵容过程样本','此处至少需要两个拥有 10 分钟完整经济证据的同英雄阵容。')}
    <div class="bpi-research-alert"><b>如何使用这些数据？</b>
      <p>先观察阵容和队伍节奏的对应关系，再打开具体比赛，核查对位、换线、支援和资源争夺。当前仅是描述性比较，不自动推出因果结论。</p></div>
  </div>`;
}

function diagnosticView(report) {
  const rows=(report.heroWinShifts || []).slice(0,10);
  if(!rows.length) return `<div class="bpi-panel"><header><h3>英雄战绩异动研究</h3><span>前后周期条件对照</span></header>
    ${note('近期没有达到研究门槛的战绩异动',
      '需至少两个不同训练日，前后时间段各有三局以上该英雄的有效赛果，且胜率变化超过 15 个百分点；此时不强行归因。')}</div>`;
  function drift(items,icons){
    return `<div class="bpi-drift-list">${(items||[]).filter(v=>Math.abs(v.changePP)>=10).slice(0,4).map(v=>`<div>
      ${heroBadge(v.hero,icons)}<span>前 ${count(v.previousGames)} 次 → 近 ${count(v.recentGames)} 次</span>
      <strong class="${v.changePP>0?'is-up':v.changePP<0?'is-down':''}">${sign(v.changePP)}</strong>
    </div>`).join('') || '<span class="bpi-subtle">未发现达到展示阈值的搭配比例变化</span>'}</div>`;
  }
  return `<div class="bpi-panel">
    <header><h3>英雄胜率变化：到底哪些条件一起变了？</h3>
      <span>前后周期 · 仅比较已知赛果</span></header>
    <p class="bpi-explain">先检查样本和区间，再对照队友英雄、敌方英雄及 10 分钟经济变化。下列条件可能同时变化，不能自动断言哪项造成了胜率变化。</p>
    <div class="bpi-diagnostics">${rows.map(row=>`<article class="bpi-diagnostic">
      <header><div>${heroBadge(row.hero,report.icons)}<small>切分日期 ${safe(row.cutDate)}</small></div>
        <strong class="${row.changePP>0?'is-up':row.changePP<0?'is-down':''}">${sign(row.changePP)}</strong></header>
      <div class="bpi-period-grid">
        <div><span>较早比赛</span><strong>${pct(row.previousWinRate)}</strong>
          <small>${count(row.previousWins)} / ${count(row.previousGames)} 胜 · 区间
             ${pct(row.previousInterval?.[0])}–${pct(row.previousInterval?.[1])}</small></div>
        <div><span>近期比赛</span><strong>${pct(row.recentWinRate)}</strong>
          <small>${count(row.recentWins)} / ${count(row.recentGames)} 胜 · 区间
             ${pct(row.recentInterval?.[0])}–${pct(row.recentInterval?.[1])}</small></div>
      </div>
      <div class="bpi-context-grid">
        <div><h4>队友搭配的变化</h4>${drift(row.partnerChanges,report.icons)}</div>
        <div><h4>面对的英雄变化</h4>${drift(row.enemyChanges,report.icons)}</div>
      </div>
      <div class="bpi-diff-context"><b>10 分钟队伍经济差</b>
        <span>较早：${goldDiff(row.previousTeamDiff10)}</span>
        <span>近期：${goldDiff(row.recentTeamDiff10)}</span></div>
      <div class="bpi-diagnostic-evidence">
        ${evidenceDetails(row.previousEvidence,'查看较早比赛')}
        ${evidenceDetails(row.recentEvidence,'查看近期比赛')}
      </div>
    </article>`).join('')}</div>
    <div class="bpi-research-alert"><b>这是候选解释，而不是确定归因</b>
      <p>对照显示队友、对位、赛程变化线索；要判定“换某英雄造成了变化”，仍需控制选手、版本和对手强度，且历史数据必须有足够可比比赛。</p></div>
  </div>`;
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
    mode:'overview', view:'focus', trigger:'', side:'1', version:'',treeNode:0,report:null, error:'',
    scrim:{bo:'BO3',game:1,side:'blue',historyOwn:'',historyEnemy:'',events:[],
      snapshot:null,catalog:null,loading:false,error:'',search:'',serial:0}};

  function body() {
    const report=state.report;
    if (!report) return '<div class="bpi-loading">正在读取 BP 研究结果…</div>';
    if (!report.scope?.games && !(state.source==='scrim' && state.view==='sandbox'))
      return note('当前范围没有可分析的 BP 比赛',
      '可切换正式比赛 / 训练赛，或选择其他战队。无比赛时不会显示伪造的胜率与阵容建议。');
    switch (state.view) {
      case 'habits': return habitView(report,state.side);
      case 'version': return versionView(report);
      case 'players': return poolView(report) + playerView(report);
      case 'combos': return comboView(report);
      case 'counter': return matchupsView(report);
      case 'changes': return changeView(report) + diagnosticView(report);
      case 'tempo': return processView(report);
      case 'diagnostics': return diagnosticView(report);
      case 'sandbox': return (state.source==='scrim'?scrimPlannerView(state.scrim):'')
        +fullDraftView(report,state.treeNode)
        +'<details class="bpi-archive"><summary>补充：按英雄查看跨不同局面的历史两步回应</summary>'
        +twoStepView(report,state.trigger)+'</details>';
      default: return `<section class="bpi-intro-brief">
          <h3>这段时间最值得关注的 BP 现象</h3>
          <p>从选禁频率、真实 BP 回应、阵容组合和周期变化中选出有比赛证据的发现。</p>
        </section>${priorityView(report)}${findingCards(report)}
        <div class="bpi-shortcuts"><button type="button" data-bpi-view="habits">查看选禁路径</button>
        <button type="button" data-bpi-view="players">研究选手绝活</button>
        <button type="button" data-bpi-view="combos">研究阵容协同</button>
        <button type="button" data-bpi-view="counter">研究阵容反制</button>
        <button type="button" data-bpi-view="changes">研究 BP 异动</button></div>`;
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
        <label class="bpi-team-select">游戏版本
          <select data-bpi-version>
            <option value="" ${!state.version?'selected':''}>全部已记录版本</option>
            ${(report?.bpStudies?.version?.options||[]).map(row=>`<option value="${safe(row.name)}"
              ${state.version===row.name?'selected':''}>${safe(row.name)} · ${count(row.games)} 局</option>`).join('')}
          </select></label>
        <span class="bpi-data-note">${report?`逐手 BP 记录 ${count(report.scope?.orderedGames)} 局 · 不跨来源混算`:'正在读取…'}</span>
      </div>
      ${report?.bpStudies?.ruleCoverage ? `<div class="bpi-rules-caption">
        <strong>${state.source==='scrim'?'训练赛 · 5 Ban + 10 Pick · 全局 BP':'KPL · 赛事原始 BP 顺序'}</strong>
        <span>${state.source==='scrim'?
          `符合训练赛 15 手顺序 ${count(report.bpStudies.ruleCoverage.scrim15)} 局；
          其他训练赛 ${count(report.bpStudies.ruleCoverage.scrimUnknown)} 局缺少新规则核验；
          BO3/BO5/BO7 跨局已选英雄还需完整系列赛历史`:
          `历史逐手记录 ${count(report.bpStudies.ruleCoverage.kplRecorded)} 局；
          不套用训练赛规则，后续合法动作依赛事赛制决定`}</span>
      </div>`:''}
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
    if(state.version)params.set('version',state.version);
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
      if(state.view==='sandbox'&&state.source==='scrim')void refreshScrim();
    } catch(error) {
      if(controller.signal.aborted || root!==state.root)return;
      state.error=error.message || '数据读取失败';paint();
    }
  }

  async function refreshScrim(){
    const planner=state.scrim;
    const serial=++planner.serial;
    planner.snapshot=null;planner.loading=true;planner.error='';
    paint();
    try {
      const history=scrimPreviousHistory(planner);
      if(!planner.catalog) {
        const catRes=await fetch(API_BASE+'/api/v3/bp-scrim/catalog',
          {cache:'no-store',headers:{Accept:'application/json'}});
        if(!catRes.ok)throw new Error('无法载入本地训练赛英雄词表');
        const cat=await catRes.json();
        if(serial!==planner.serial)return;
        planner.catalog=cat;
      }
      const blueTeam=planner.side==='blue'?'本队':'对手';
      const redTeam=planner.side==='red'?'本队':'对手';
      const data={source:'scrim',bo:planner.bo,gameNumber:planner.game,
        blueTeam,redTeam,history,events:planner.events};
      const response=await fetch(API_BASE+'/api/v3/bp-scrim/next',{
        method:'POST',cache:'no-store',
        headers:{'Content-Type':'application/json',Accept:'application/json'},
        body:JSON.stringify(data)});
      if(!response.ok) {
        const error=await response.json().catch(()=>({}));
        throw new Error(error.detail||'训练赛合法动作校验失败');
      }
      const result=await response.json();
      if(serial!==planner.serial)return;
      planner.snapshot=result;
    }catch(error) {
      if(serial!==planner.serial)return;
      planner.error=error.message||'训练赛 BP 状态校验失败';
    }finally {
      if(serial===planner.serial){planner.loading=false;paint();}
    }
  }

  function finishScrimGame(){
    const planner=state.scrim;
    if(planner.events.length!==15||planner.snapshot?.nextAction ||
       planner.game>=({BO3:3,BO5:5,BO7:7}[planner.bo]||3))return;
    const picks=camp=>planner.events.filter(e=>e.action==='pick'&&e.camp===camp)
      .map(e=>e.hero);
    const own=picks(planner.side==='blue'?'1':'2');
    const enemy=picks(planner.side==='blue'?'2':'1');
    if(own.length!==5||enemy.length!==5)return;
    planner.historyOwn+=(planner.historyOwn.trim()?'\n':'')+own.join('，');
    planner.historyEnemy+=(planner.historyEnemy.trim()?'\n':'')+enemy.join('，');
    planner.game+=1;planner.events=[];planner.snapshot=null;planner.search='';
    void refreshScrim();
  }

  function bind(root) {
    if(root.dataset.bpiBound)return;
    root.dataset.bpiBound='1';
    root.addEventListener('click', event=>{
      const choose=event.target.closest('[data-bpi-scrim-hero]');
      if(choose){
        const planner=state.scrim;
        const hero=choose.dataset.bpiScrimHero;
        const next=planner.snapshot?.nextAction;
        if(next && !planner.loading && planner.snapshot.legalCandidates.includes(hero)){
          planner.events.push({order:next.order,action:next.action,
            camp:next.camp,hero});
          planner.search='';void refreshScrim();
        }
        return;
      }
      if(event.target.closest('[data-bpi-scrim-back]')){
        if(state.scrim.events.length){state.scrim.events.pop();void refreshScrim();}
        return;
      }
      if(event.target.closest('[data-bpi-scrim-reset]')){
        state.scrim.events=[];void refreshScrim();return;
      }
      if(event.target.closest('[data-bpi-scrim-next-game]')){
        finishScrimGame();return;
      }
      if(event.target.closest('[data-bpi-scrim-validate]')){
        state.scrim.events=[];void refreshScrim();return;
      }
      const tree=event.target.closest('[data-bpi-tree-node]');
      if(tree){
        const next=Number(tree.dataset.bpiTreeNode);
        if(Number.isInteger(next)&&state.report?.bpStudies?.draftTree?.nodes?.some(n=>n.id===next)){
          state.treeNode=next;paint();
        }
        return;
      }
      if(event.target.closest('[data-bpi-tree-reset]')){
        state.treeNode=0;paint();return;
      }
      if(event.target.closest('[data-bpi-tree-back]')){
        const cur=state.report?.bpStudies?.draftTree?.nodes?.find(n=>n.id===state.treeNode);
        state.treeNode=cur?.parent??0;paint();return;
      }
      const side=event.target.closest('[data-bpi-side]');
      if(side){state.side=side.dataset.bpiSide;paint();return;}
      const source=event.target.closest('[data-bpi-source]');
      if(source){
        const next=source.dataset.bpiSource;
        if(next===state.source)return;
        state.source=next;state.team=next==='scrim'?'本队':'';state.version='';state.trigger='';state.treeNode=0;
        void load();return;
      }
      const view=event.target.closest('[data-bpi-view]');
      if(view){
        state.view=view.dataset.bpiView;
        if(state.view==='sandbox')state.trigger='';
        paint();
        if(state.view==='sandbox'&&state.source==='scrim')void refreshScrim();
      }
    });
    root.addEventListener('change', event=>{
      const planner=state.scrim;
      if(event.target.matches('[data-bpi-scrim-bo]')){
        planner.bo=event.target.value;planner.game=1;planner.events=[];
        planner.historyOwn='';planner.historyEnemy='';planner.search='';
        void refreshScrim();return;
      }
      if(event.target.matches('[data-bpi-scrim-game]')){
        planner.game=Number(event.target.value);planner.events=[];planner.search='';
        void refreshScrim();return;
      }
      if(event.target.matches('[data-bpi-scrim-side]')){
        planner.side=event.target.value;planner.events=[];planner.search='';
        void refreshScrim();return;
      }
      if(event.target.matches('[data-bpi-team]')){
        state.team=event.target.value;state.trigger='';state.treeNode=0;void load();
      }
      if(event.target.matches('[data-bpi-version]')){
        state.version=event.target.value;state.trigger='';state.treeNode=0;void load();
      }
      if(event.target.matches('[data-bpi-trigger]')){
        state.trigger=event.target.value;paint();
      }
    });
    root.addEventListener('input', event=>{
      const planner=state.scrim;
      if(event.target.matches('[data-bpi-scrim-history-own]')){
        planner.historyOwn=event.target.value;
      }else if(event.target.matches('[data-bpi-scrim-history-enemy]')){
        planner.historyEnemy=event.target.value;
      }else if(event.target.matches('[data-bpi-scrim-search]')){
        planner.search=event.target.value;
        const target=root.querySelector('[data-bpi-scrim-candidates]');
        if(target)target.innerHTML=scrimHeroButtons(planner);
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
    state.trigger='';state.side='1';state.version='';state.treeNode=0;state.report=null;state.error='';
    bind(root);void load();
  }
  return {mount};
}
