import {hasDraftContent,isRecoverableDraft} from '/assets/draft-state.mjs?v=2';
import {kplTeams,teamPresetSource,teamPresetLabel} from '/assets/team-presets.js?v=1';
import { renderReview } from '/assets/review-page.js?v=6';
import { renderReplays } from '/assets/replays-page.js?v=10';
import { FEATURES } from '/assets/features.js?v=1';
import { renderRecordings } from '/assets/recordings-page.js?v=4';
import { renderScreenshots } from '/assets/screenshot-page.js?v=10';
import { renderChannels, renderChannel } from '/assets/channels-page.js?v=16';
import { renderStats } from '/assets/stats-page.js?v=9';
import { openIconReview } from '/assets/icon-review.js?v=6';
const embedded = document.body.dataset.platform === 'unified';
const $ = (q) => document.querySelector(q);
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => crypto.randomUUID();
const heroes = '阿古朵 阿轲 艾琳 安琪拉 敖隐 白起 百里守约 百里玄策 扁鹊 不知火舞 蔡文姬 曹操 嫦娥 程咬金 成吉思汗 大乔 达摩 大司命 狄仁杰 典韦 貂蝉 东皇太一 盾山 朵莉亚 伽罗 干将莫邪 高渐离 戈娅 宫本武藏 公孙离 鬼谷子 关羽 海月 韩信 后羿 黄忠 花木兰 姬小满 姜子牙 金蝉 镜 伽罗 狂铁 铠 兰陵王 澜 老夫子 莱西奥 李白 李信 李元芳 廉颇 刘邦 刘备 刘禅 鲁班大师 鲁班七号 露娜 吕布 马超 马可波罗 蒙犽 蒙恬 梦奇 芈月 米莱狄 明世隐 墨子 哪吒 娜可露露 牛魔 女娲 盘古 裴擒虎 司空震 司马懿 苏烈 孙膑 孙策 孙尚香 孙悟空 孙权 沈梦溪 上官婉儿 沈梦溪 少司缘 太乙真人 西施 夏侯惇 夏洛特 项羽 小乔 雅典娜 亚连 亚瑟 杨戬 杨玉环 瑶 曜 影 弈星 嬴政 云缨 云中君 虞姬 元歌 甄姬 张飞 张良 赵怀真 赵云 钟馗 钟无艳 周瑜 猪八戒 庄周 诸葛亮 '.split(' ');
$('#hero-list').innerHTML = [...new Set(heroes)].filter(x=>!x.includes('?')).sort((a,b)=>a.localeCompare(b,'zh')).map(h=>`<option value="${esc(h)}">`).join('');
let state, draft, dirty = false, currentPage = '', toastTimer, busy = false;
const ocrResults = new Map(); let iconCatalog = {entries:[]};
const fields = [ ['kills','击杀'], ['deaths','死亡'], ['assists','助攻'], ['gold','总经济'], ['damage','输出'], ['taken','承伤'], ['participation','参团 %'], ['rating','评分'] ];
const positions = ['对抗路','打野','中路','发育路','游走'];
const FOCUS_METRICS = {
  kda:{label:'KDA',scope:'player'}, deaths:{label:'场均死亡',scope:'player'},
  dpm:{label:'分均输出',scope:'player'}, tpm:{label:'分均承伤',scope:'player'},
  participation:{label:'参团率',scope:'player'}, laneDiff:{label:'对线经济差',scope:'position'},
  win:{label:'胜负',scope:'team'}, teamGoldDiff:{label:'终局经济差',scope:'team'},
};
const fmt = (n, decimals=1) => n === null || n === undefined ? '—' : Number(n).toLocaleString('zh-CN',{maximumFractionDigits:decimals});
const pct = (wins,games) => games ? Math.round(wins/games*100)+'%' : '—';
const localDate = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());

async function api(url, method='GET', value) {
  const response = await fetch(url, {method, ...(value === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(value)})});
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '请求失败，请检查输入');
  if(embedded&&method!=='GET')window.dispatchEvent(new CustomEvent('platform-data-changed'));
  return result;
}
function toast(message,error=false){ const t=$('#toast'); t.textContent=message;t.hidden=false;t.classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,error?8500:4500); }
async function refresh(){const results=await Promise.all([api('/api/state'),api('/api/catalog')]);state=results[0];iconCatalog=results[1];if(iconCatalog.entries.length)document.querySelector('#hero-list').innerHTML=iconCatalog.entries.filter(e=>e.kind==='hero').map(e=>'<option value=' + String.fromCharCode(34) + esc(e.name) + String.fromCharCode(34) + '>').join('');$('#team-label').textContent=state.settings.teamName;$('#match-count').textContent=state.matches.filter(m=>m.status!=='archived').length;}
function heading(title,subtitle,action='',stats=''){return `<div class="page-heading"><div><h1>${esc(title)}</h1><p class="subtitle">${subtitle}</p></div>${stats?`<div class="band-stats">${stats}</div>`:''}${action?`<div class="band-action">${action}</div>`:''}</div>`;}
const bandStat=(label,value,note='',hot=false)=>`<div class="band-stat${hot?' hot':''}"><span>${label}</span><b>${value}</b>${note?`<small>${note}</small>`:''}</div>`;
const newButton = '<a class="button" href="#new"><span class="plus">+</span>录入训练赛</a>';
const orderedMatches=()=>[...state.matches].sort((a,b)=>(b.date||'').localeCompare(a.date||'')||(b.updatedAt||0)-(a.updatedAt||0));
function resultTag(m){return m.status==='draft'?'<span class="tag amber">待校对</span>':m.status==='archived'?'<span class="tag gray">已归档</span>':m.side===m.winner?'<span class="tag">胜利</span>':'<span class="tag red">失利</span>';}
function teamPresetOptions(teamName){
 const custom=teamName && !kplTeams.includes(teamName);
 return `<option value="__custom__"${!teamName?' selected':''}>＋ 自定义战队（在下一栏填写）</option>`
  +(custom?`<option value="${esc(teamName)}" selected>${esc(teamName)} · 我的自定义战队</option>`:'')
  +kplTeams.map(name=>`<option${name===teamName?' selected':''}>${esc(name)}</option>`).join('');
}
function overview(){
  const s=state.summary,recent=orderedMatches().filter(m=>m.status!=='archived').slice(0,4),hasData=s.games>0||s.drafts>0;
  const stats=hasData?bandStat('已确认',s.games,'局')+bandStat('训练赛胜率',pct(s.wins,s.games),`${s.wins} 胜 / ${s.games-s.wins} 负`,true)+bandStat('已用英雄',s.heroes.length,'位')+bandStat('待校对',s.drafts,'局'):'';
  $('#content').innerHTML=heading('训练概览','录入赛后截图，校对后自动汇总英雄与队员数据。',newButton,stats)
   +`<div class="overview-grid${hasData?'':' solo'}"><section class="panel"><div class="panel-header"><div><h2>训练记录</h2><div class="panel-subtitle">未归档的比赛排在最前</div></div><a href="#matches" class="button ghost">全部记录 →</a></div>${recent.length?recent.map(m=>`<a class="recent-row" href="#edit/${m.id}"><div><strong>vs ${esc(m.opponent||'对手待填写')}</strong><small>${esc(m.date||'日期待补充')} · ${esc(m.session||'日常训练')}</small></div>${resultTag(m)}</a>`).join(''):`<div class="empty"><strong>还没有比赛记录</strong>录入第一场训练赛后，这里会按时间列出每局与核对状态。<div class="start-strip" style="justify-content:center;margin-top:14px"><a class="button" href="#new">录入训练赛</a>${state.settings.roster.length?'':'<a class="button secondary" href="#roster">先建立队员名单</a>'}</div></div>`}</section>
   ${hasData?`<section class="panel"><div class="panel-header"><h2>本队英雄表现</h2><a href="#analysis" class="button ghost">查看分析 →</a></div>${state.summary.heroes.length?summaryTable(state.summary.heroes.slice(0,5),'heroes'):'<div class="empty">正式入库后，这里将展示英雄出场、胜率与表现。数据不足时不做强弱评级。</div>'}</section>`:''}</div>`;
}
function matchesPage(){
 $('#content').innerHTML=heading('训练赛档案','按对手、分组与状态检索已保存的比赛。',newButton)+`<div class="toolbar"><input class="control" id="search-matches" placeholder="搜索对手、备注、训练分组" aria-label="搜索比赛"><select class="control" id="status-filter" style="width:135px"><option value="active">全部有效记录</option><option value="confirmed">已确认</option><option value="draft">待校对</option><option value="archived">已归档</option></select><span class="filters-count" id="list-count"></span></div><section class="panel"><div class="table-wrap"><table><thead><tr><th>日期 / 分组</th><th>对手</th><th>比分（左 : 右）</th><th>本队阵营</th><th>状态 / 结果</th><th>备注</th><th></th></tr></thead><tbody id="match-rows"></tbody></table></div></section>`;
 const draw=()=>{const q=$('#search-matches').value.toLowerCase(),status=$('#status-filter').value;const list=orderedMatches().filter(m=>(status==='active'?m.status!=='archived':m.status===status)&&[m.opponent,m.notes,m.session].join(' ').toLowerCase().includes(q));$('#list-count').textContent=`${list.length} 条记录`;$('#match-rows').innerHTML=list.length?list.map(m=>`<tr><td><strong>${esc(m.date||'日期待填写')}</strong><div class="helper">${esc(m.session||'日常训练')}</div></td><td>${esc(m.opponent||'待填写')}</td><td>${esc(m.scores?.left||'—')} : ${esc(m.scores?.right||'—')}</td><td>${m.side==='left'?'左侧':m.side==='right'?'右侧':'待确认'}</td><td>${resultTag(m)}</td><td class="note-cell">${esc(m.notes||'—')}</td><td><a class="button ghost" href="#review/${m.id}">复盘报告</a> <a class="button ghost" href="#edit/${m.id}">校对 →</a></td></tr>`).join(''):'<tr><td colspan="7" class="empty">暂无符合条件的记录。新建一场训练赛，或调整筛选条件。</td></tr>';};
 $('#search-matches').oninput=draw;$('#status-filter').onchange=draw;draw();
}
function summaryTable(rows,kind,mode='totals'){
 const label={heroes:'英雄',players:'队员',opponents:'对手',lineups:'本队五人英雄组合'}[kind];
 const personal=['heroes','players'].includes(kind), normalized=mode==='rates';
 const header=normalized?'<th>输出 / 分钟 · 样本</th><th>经济 / 分钟 · 样本</th><th>承伤 / 分钟 · 样本</th><th>场均输出 / 经济占比</th><th>汇总 KDA · 样本</th>':'<th>场均 K / D / A</th><th>场均输出 / 样本</th><th>场均承伤 / 样本</th><th>场均经济 / 样本</th>';
 const cell=(value,samples,decimals=1)=>`${fmt(value,decimals)} <span class="helper">/ ${samples||0} 局</span>`;
 return `<div class="table-wrap"><table><thead><tr><th>${label}</th><th>出场 / 比赛数</th><th>胜场 / 胜率</th>${personal?'<th>实际分路</th>'+header:''}<th>证据</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td>${r.games}</td><td>${r.wins} 胜 · ${pct(r.wins,r.games)}<span class="winbar"><i style="width:${r.wins/r.games*100}%"></i></span></td>${personal?`<td>${esc(r.positions?.join(' / ')||'未确认')}<div class="helper">${r.unknownPositionSamples?`${r.unknownPositionSamples} 局位置未确认`:''}</div></td>${normalized?`<td>${cell(r.damagePerMinute,r.damagePerMinuteSamples)}</td><td>${cell(r.goldPerMinute,r.goldPerMinuteSamples)}</td><td>${cell(r.takenPerMinute,r.takenPerMinuteSamples)}</td><td>${r.damageShare==null?'—':fmt(r.damageShare)+'%'} / ${r.goldShare==null?'—':fmt(r.goldShare)+'%'}<div class="helper">各 ${r.damageShareSamples||0} / ${r.goldShareSamples||0} 局</div></td><td>${cell(r.kda,r.kdaSamples,2)}</td>`:`<td>${fmt(r.kills)} / ${fmt(r.deaths)} / ${fmt(r.assists)}</td><td>${cell(r.damage,r.damageSamples,0)}</td><td>${cell(r.taken,r.takenSamples,0)}</td><td>${cell(r.gold,r.goldSamples,0)}</td>`}`:''}<td><button class="button ghost" data-evidence="${esc(r.key)}">逐局查看 ↗</button></td></tr>`).join('')}</tbody></table></div>`;
}
function drilldown(row){const box=$('#drilldown');if(!box||!row)return;box.hidden=false;box.innerHTML=`<div class="panel-header"><h2>${esc(row.name)} · 比赛证据</h2><span class="tag gray">${row.games} 局</span></div>`+row.matchIds.map(id=>state.matches.find(m=>m.id===id)).filter(Boolean).map(m=>`<a class="recent-row" href="#edit/${esc(m.id)}"><div><strong>vs ${esc(m.opponent)}</strong><small>${esc(m.date)} · ${esc(m.session||'日常训练')}</small></div>${resultTag(m)}</a>`).join('');box.scrollIntoView({behavior:'smooth',block:'nearest'});}
function normalizeBp(bp){
 const base={bans:{left:[],right:[]},picks:{left:[],right:[]},firstPick:'',notes:''};
 if(bp&&typeof bp==='object'){
  for(const side of ['left','right']){
   base.bans[side]=Array.isArray(bp.bans?.[side])?bp.bans[side].slice(0,4):[];
   base.picks[side]=Array.isArray(bp.picks?.[side])?bp.picks[side].slice(0,5):[];
  }
  base.firstPick=bp.firstPick||'';base.notes=bp.notes||'';
 }else if(typeof bp==='string'){base.notes=bp;}
 return base;
}
const OBJECTIVE_LABELS={tyrant:'暴君',dominator:'主宰',storm:'风暴龙王'};
const bpSlots=(kind,side,count,values)=>Array.from({length:count},(_,i)=>
 `<input class="player-input bp-slot" list="hero-list" data-bp-kind="${kind}" data-bp-side="${side}" data-bp-index="${i}" aria-label="${side==='left'?'左':'右'}侧${kind==='ban'?'禁用':'选用'}第${i+1}位" value="${esc(values[side]?.[i]||'')}" placeholder="—">`).join('');
function bpPanel(){
 const bp=normalizeBp(draft.bp);
 return `<section class="panel editor-panel"><div class="panel-header"><h2>BP 记录</h2><span class="helper">按手序填写；留空视为未记录，不影响入库</span></div><div class="form-section">
 <div class="bp-grid">${['left','right'].map(side=>`<div class="bp-side">
   <div class="bp-side-head"><strong>${side==='left'?'截图左侧':'截图右侧'}</strong>${draft.side===side?'<span class="tag blue">本队</span>':''}</div>
   <div class="bp-row-label">禁用（按顺序，最多 4）</div><div class="bp-slots">${bpSlots('ban',side,4,bp.bans)}</div>
   <div class="bp-row-label">选用（按手序，最多 5）</div><div class="bp-slots">${bpSlots('pick',side,5,bp.picks)}</div>
 </div>`).join('')}</div>
 <div class="bp-meta"><label class="field">一手方<select data-bp-firstpick aria-label="一手方"><option value="">未记录</option><option value="left" ${bp.firstPick==='left'?'selected':''}>左侧</option><option value="right" ${bp.firstPick==='right'?'selected':''}>右侧</option></select></label>
 <label class="field wide">BP 备注<textarea data-bp-notes rows="2" placeholder="选人思路、预期打法等自由记录。">${esc(bp.notes)}</textarea></label></div>
 </div></section>`;
}
function objectivesPanel(){
 const rows=Object.entries(OBJECTIVE_LABELS).map(([type,label])=>`<div class="obj-row"><div class="obj-label">${label}</div>
   ${['left','right'].map(side=>{
     const list=(draft.events||[]).filter(e=>e.type===type&&e.side===side);
     return `<div class="obj-cell"><div class="obj-head"><span class="obj-side ${side==='right'?'red':''}">${side==='left'?'左':'右'}</span>
       <button class="button ghost" data-obj-add="${type}:${side}" aria-label="添加${label}">＋ 记一次</button></div>
       ${list.map((event,i)=>`<div class="obj-entry"><input class="player-input obj-time" data-obj-time="${type}:${side}:${i}"
         value="${esc(event.t||'')}" placeholder="分:秒，可空" pattern="[0-9]{1,3}:[0-5][0-9]" aria-label="${label}第${i+1}次时间"><input class="obj-time-slider" type="range" min="0" max="${draft.duration?Math.round(Number(draft.duration)*60):7200}" step="1" value="${event.t?event.t.split(':').reduce((a,b)=>a*60+Number(b),0):0}" data-obj-slider="${type}:${side}:${i}" aria-label="拖动设置${label}第${i+1}次时间">
         <button class="button ghost" data-obj-remove="${type}:${side}:${i}" aria-label="移除">✕</button></div>`).join('')||'<span class="helper">未记录</span>'}</div>`;
   }).join('')}</div>`).join('');
 const towers=side=>(draft.events||[]).filter(e=>e.type==='tower'&&e.side===side).length;
 const first=(draft.events||[]).find(e=>e.type==='firstTower');
 return `<section class="panel editor-panel"><div class="panel-header"><h2>资源速记</h2><span class="helper">计数必填、时间可选；复盘回放时补分钟数，OCR 数据后续自动预填</span></div><div class="form-section" id="objectives-editor">
 <div class="obj-row obj-tower-row"><div class="obj-label">推塔数</div>
   ${['left','right'].map(side=>`<div class="obj-cell"><div class="obj-head"><span class="obj-side ${side==='right'?'red':''}">${side==='left'?'左':'右'}</span>
     <span><button class="button ghost" data-obj-tower="${side}:-1" aria-label="减少">－</button> <strong class="obj-count">${towers(side)}</strong> <button class="button ghost" data-obj-tower="${side}:1" aria-label="增加">＋</button></span></div></div>`).join('')}</div>
 <div class="obj-row"><div class="obj-label">一塔归属</div><div class="obj-cell obj-cell-wide"><select class="player-input" data-obj-first aria-label="一塔归属" style="max-width:180px">
   <option value="">未记录</option><option value="left" ${first?.side==='left'?'selected':''}>左侧</option><option value="right" ${first?.side==='right'?'selected':''}>右侧</option></select></div></div>
 ${rows}
 <p class="helper">事件会保存到本局记录，用于资源控制率与塔数差统计；时间用于后续与经济曲线对齐。</p>
 </div></section>`;
}
function bindObjectives(){
 const box=document.querySelector('#objectives-editor');if(!box)return;
 box.addEventListener('click',event=>{
  const add=event.target.closest('[data-obj-add]');
  if(add){const [type,side]=add.dataset.objAdd.split(':');draft.events.push({type,side,t:null});remember();objectivesRefresh();return;}
  const remove=event.target.closest('[data-obj-remove]');
  if(remove){const [type,side,index]=remove.dataset.objRemove.split(':');
    let seen=0;draft.events=draft.events.filter(e=>{if(e.type===type&&e.side===side){seen+=1;return seen!==Number(index)+1;}return true;});
    remember();objectivesRefresh();return;}
  const tower=event.target.closest('[data-obj-tower]');
  if(tower){const [side,delta]=tower.dataset.objTower.split(':');
    if(Number(delta)>0)draft.events.push({type:'tower',side,t:null});
    else{const index=draft.events.map(e=>`${e.type}:${e.side}`).lastIndexOf(`tower:${side}`);if(index>=0)draft.events.splice(index,1);}
    remember();objectivesRefresh();}
 });
 box.addEventListener('change',event=>{
  const first=event.target.closest('[data-obj-first]');
  if(first){draft.events=(draft.events||[]).filter(e=>e.type!=='firstTower');
    if(first.value)draft.events.push({type:'firstTower',side:first.value,t:null});remember();}
 });
 box.addEventListener('input',event=>{
  const slider=event.target.closest('[data-obj-slider]');if(slider){const input=slider.parentElement.querySelector('[data-obj-time]'),seconds=Number(slider.value);input.value=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');input.dispatchEvent(new Event('input',{bubbles:true}));return;}
  const time=event.target.closest('[data-obj-time]');
  if(time){const [type,side,index]=time.dataset.objTime.split(':');
    let seen=0;const target=(draft.events||[]).find(e=>{if(e.type===type&&e.side===side){seen+=1;return seen===Number(index)+1;}return false;});
    if(target){target.t=time.value.trim()||null;const slider=time.parentElement.querySelector('[data-obj-slider]');if(slider&&/^\d+:[0-5]\d$/.test(time.value))slider.value=time.value.split(':').reduce((a,b)=>a*60+Number(b),0);}remember();}
 });
}
function objectivesRefresh(){const box=document.querySelector('#objectives-editor');if(!box)return;box.closest('section').outerHTML=objectivesPanel();bindObjectives();}
async function hydrateFocus(){
 const box=document.querySelector('#focus-links');if(!box)return;
 try{
  const result=await api('/api/focus');
  if(currentPage!=='editor')return;
  const active=result.items.filter(item=>item.status!=='archived');
  draft.focusIds=Array.isArray(draft.focusIds)?draft.focusIds:[];
  box.innerHTML=`<div class="focus-chips">${active.length?active.map(item=>`<label class="focus-chip ${draft.focusIds.includes(item.id)?'on':''}">
    <input type="checkbox" data-focus-link="${esc(item.id)}" ${draft.focusIds.includes(item.id)?'checked':''}>
    ${esc(item.title)}<span class="helper">${esc(FOCUS_METRICS[item.metric]?.label||item.metric)}</span></label>`).join(''):'<span class="helper">还没有训练重点，可在下方创建。</span>'}</div>
  <details class="focus-create"><summary>＋ 新建训练重点</summary>
   <div class="focus-create-form"><input class="control" id="focus-title" placeholder="重点标题，例如：中路支援偏慢" maxlength="80">
   <select class="control" id="focus-metric" aria-label="指标">${Object.entries(FOCUS_METRICS).map(([key,item])=>`<option value="${key}">${item.label}（${{player:'队员',position:'分路',team:'全队'}[item.scope]}）</option>`).join('')}</select>
   <select class="control" id="focus-scope" aria-label="对象"></select>
   <select class="control" id="focus-direction" aria-label="方向"><option value="up">越高越好</option><option value="down">越低越好</option></select>
   <button class="button secondary" id="focus-create">创建并关联</button></div></details>`;
  box.querySelectorAll('[data-focus-link]').forEach(input=>input.onchange=()=>{
   draft.focusIds=box.querySelectorAll('[data-focus-link]:checked').length
     ?[...box.querySelectorAll('[data-focus-link]:checked')].map(input=>input.dataset.focusLink):[];
   box.querySelectorAll('.focus-chip').forEach(chip=>chip.classList.toggle('on',chip.querySelector('input').checked));remember();});
  const metricSelect=box.querySelector('#focus-metric'),scopeSelect=box.querySelector('#focus-scope');
  const renderScope=()=>{const spec=FOCUS_METRICS[metricSelect.value];
   scopeSelect.innerHTML=spec.scope==='player'?state.settings.roster.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')
    :spec.scope==='position'?positions.map(p=>`<option>${p}</option>`).join(''):'<option value="">全队</option>';
   scopeSelect.disabled=spec.scope==='team';};
  metricSelect.onchange=renderScope;renderScope();
  box.querySelector('#focus-create').onclick=async()=>{
   try{const created=await api('/api/focus','POST',{title:box.querySelector('#focus-title').value,metric:metricSelect.value,
     scopeType:FOCUS_METRICS[metricSelect.value].scope,scopeId:scopeSelect.value,direction:box.querySelector('#focus-direction').value});
    draft.focusIds=[...(draft.focusIds||[]),created.id];remember();toast('训练重点已创建并关联本局');hydrateFocus();}
   catch(e){toast(e.message,true);}
  };
 }catch(e){box.innerHTML='<span class="helper">训练重点读取失败。</span>';}
}
function blankMatch(){return {id:uid(),revision:0,status:'draft',date:'',side:'',winner:'',opponent:'',version:'',session:'',duration:'',notes:'',bp:{bans:{left:[],right:[]},picks:{left:[],right:[]},firstPick:'',notes:''},events:[],focusIds:[],reviewed:false,scores:{left:'',right:''},imageIds:[],players:['left','right'].flatMap(side=>Array.from({length:5},(_,slot)=>({side,slot,hero:'',playerId:'',position:'',equipment:'',...Object.fromEntries(fields.map(([k])=>[k,'']))}))),ocrAudit:[]};}
function remember(){dirty=hasDraftContent(draft);draft.reviewed=false;const check=$('#reviewed');if(check)check.checked=false;const hint=$('#save-hint');if(hint)hint.textContent=dirty?'有未保存修改 · 请保存草稿或重新确认入库':'尚未填写内容';try{if(dirty)localStorage.setItem('training-unsaved',JSON.stringify(draft));else localStorage.removeItem('training-unsaved');}catch{} }
function field(label,name,type='text',placeholder=''){return `<label class="field">${label}<input data-meta="${name}" type="${type}" value="${esc(draft[name])}" placeholder="${placeholder}"></label>`;}
function sideSelect(name,label){return `<label class="field">${label}<select data-meta="${name}"><option value="">请确认</option><option value="left" ${draft[name]==='left'?'selected':''}>截图左侧</option><option value="right" ${draft[name]==='right'?'selected':''}>截图右侧</option></select></label>`;}
function playerTable(side){const ownSide=draft.side===side,rosterOptions=p=>ownSide?state.settings.roster.map(r=>`<option value="${esc(r.id)}" ${r.id===p.playerId?'selected':''}>${esc(r.name)}</option>`).join(''):'';return `<section class="panel editor-panel"><div class="panel-header"><h2>${side==='left'?'左侧':'右侧'}五人 <span class="tag gray">${ownSide?'本队':draft.side?'对手':'请先确认本队阵营'}</span></h2><span class="helper">空值保留未知 · k = 千 · 金色框为识别候选</span></div><div class="table-wrap"><table class="editor-table"><thead><tr><th>#</th><th>队员身份</th><th>英雄</th><th>实际分路</th>${fields.map(([,name])=>`<th>${name}</th>`).join('')}<th>装备</th></tr></thead><tbody>${draft.players.filter(p=>p.side===side).map(p=>`<tr data-row="${side}-${p.slot}"><td class="row-num">${p.slot+1}</td><td><select aria-label="${side}第${p.slot+1}行队员" class="player-input name" data-player="${p.side}-${p.slot}" data-key="playerId"><option value="">${ownSide?'关联本队队员':draft.side?'对手 / 不关联本队':'请先确认本队阵营'}</option>${rosterOptions(p)}</select></td><td><input class="player-input hero" list="hero-list" data-player="${p.side}-${p.slot}" data-key="hero" aria-label="${side}第${p.slot+1}行英雄" value="${esc(p.hero)}" placeholder="手动选择"></td><td><select class="player-input" data-player="${p.side}-${p.slot}" data-key="position" aria-label="实际分路"><option value="">待确认</option>${positions.map(pos=>`<option ${p.position===pos?'selected':''}>${pos}</option>`).join('')}</select></td>${fields.map(([key])=>`<td><input class="player-input ${p.sources?.[key]?'source-ocr':''}" inputmode="decimal" data-player="${p.side}-${p.slot}" data-key="${key}" aria-label="${side}第${p.slot+1}行${key}" value="${esc(p[key])}" placeholder="—" title="${p.sources?.[key]?esc('识别原文：'+p.sources[key].raw+'；模型置信度：'+Math.round(p.sources[key].confidence*100)+'%。请人工核对。'):'未录入即为未知'}"></td>`).join('')}<td><input class="player-input name" data-player="${p.side}-${p.slot}" data-key="equipment" aria-label="装备" value="${esc(p.equipment||'')}" placeholder="待补充"></td></tr>`).join('')}</tbody></table></div></section>`;}
function editor(){
 const existing=state.matches.some(m=>m.id===draft.id), archived=draft.status==='archived';
 draft.bp=normalizeBp(draft.bp);draft.events=Array.isArray(draft.events)?draft.events:[];draft.focusIds=Array.isArray(draft.focusIds)?draft.focusIds:[];
 $('#content').innerHTML=`<a href="#matches" class="back-link">← 返回比赛档案</a>`+heading(existing?'校对与复盘':'记录一场新的训练赛','先建立一局，再把这局的战绩页、数据页放在一起。',resultTag(draft)+(existing?`<a class="button secondary" href="#review/${draft.id}">查看复盘报告</a>`:''))+`
 ${!state.settings.roster.length?'<div class="notice">尚未建立队员名单。你可以先保存草稿，再到“战队名单”添加队员后关联本队五人。</div>':''}
 <div class="editor-layout"><div><section class="panel editor-panel"><div class="panel-header"><h2>比赛信息</h2><span class="helper">本队不固定在左侧，请根据截图确认</span></div><div class="form-section"><div class="form-grid">${field('比赛日期','date','date')}${field('对手名称','opponent','text','例如：周三训练对手')}${field('训练分组 / 大场','session','text','例如：晚训 BO5 · 第 1 局')}${sideSelect('side','本队在截图中的位置')}${sideSelect('winner','本局胜方')}${field('游戏版本','version','text','例如：S42 / 补丁日期')}${durationControl()}<label class="field">左侧击杀比分<input data-score="left" value="${esc(draft.scores.left)}" inputmode="numeric" placeholder="待确认"></label><label class="field">右侧击杀比分<input data-score="right" value="${esc(draft.scores.right)}" inputmode="numeric" placeholder="待确认"></label></div></div></section></div>
 <aside class="panel"><div class="panel-header"><h2>原始截图</h2><span class="tag gray" id="image-count">${draft.imageIds.length} 张</span></div><div class="evidence-conflict notice" id="evidence-conflicts" hidden></div><div class="evidence-list" id="evidence-list"></div></aside></div>
 <div class="notice green">识别结果不会直接进入统计。请逐行对应截图确认队员和英雄；画面上下排列不代表分路。只录入一张图也可以，未提供的数据保持为空。</div>
 <div id="player-tables">${playerTable('left')}${playerTable('right')}</div>
 ${bpPanel()}
 ${objectivesPanel()}
 <section class="panel"><div class="panel-header"><h2>训练复盘</h2><span class="helper">先记录事实，再写判断</span></div><div class="form-section"><div class="form-grid"><label class="field wide">本局复盘要点<textarea data-meta="notes" placeholder="例如：08:30 暴君争夺前队伍站位分散，下次训练重点检查集合时间。">${esc(draft.notes)}</textarea></label><div class="field wide" id="focus-links"><span>关联训练重点（本局暴露的问题）</span><span class="helper">正在读取重点库…</span></div></div></div></section>
 <label class="check-row"><input type="checkbox" id="reviewed" ${draft.reviewed?'checked':''}>我已核对同局截图、本队阵营、胜负，以及本队五人的身份和英雄。缺失数据保留为空。</label>
 <div class="editor-actions"><div><span class="helper" id="save-hint">${existing?'本局已保存，修改后请重新保存':'尚未入库 · 草稿不计入统计'}</span>${existing?`<button class="button ghost" id="archive-match">${archived?'恢复为草稿':'归档此局'}</button>`:''}</div><div><button class="button secondary" id="save-draft">保存草稿</button><button class="button" id="confirm-match">确认数据并入库 →</button></div></div>`;
 bindEditor();bindObjectives();renderEvidence();hydrateEvidence();hydrateFocus();
}
function bindEditor(){
 bindDuration();
 document.querySelectorAll('[data-meta]').forEach(el=>el.oninput=()=>{draft[el.dataset.meta]=el.value;remember();if(el.dataset.meta==='side'){if(draft.side)draft.players.forEach(p=>{if(p.side!==draft.side)p.playerId='';});const tables=document.querySelector('#player-tables');if(tables){tables.innerHTML=playerTable('left')+playerTable('right');bindPlayers();}}});
 document.querySelectorAll('[data-score]').forEach(el=>el.oninput=()=>{draft.scores[el.dataset.score]=el.value;remember();});
 document.querySelectorAll('[data-bp-kind]').forEach(el=>el.oninput=()=>{const kind=el.dataset.bpKind,side=el.dataset.bpSide,index=Number(el.dataset.bpIndex);
  const group=kind==='ban'?'bans':'picks';const list=draft.bp[group][side];
  while(list.length<=index)list.push('');list[index]=el.value.trim();remember();});
 document.querySelectorAll('[data-bp-firstpick]').forEach(el=>el.onchange=()=>{draft.bp.firstPick=el.value;remember();});
 document.querySelectorAll('[data-bp-notes]').forEach(el=>el.oninput=()=>{draft.bp.notes=el.value;remember();});
 bindPlayers();$('#reviewed').onchange=e=>{draft.reviewed=e.target.checked;dirty=true;document.querySelector('#save-hint').textContent='核对状态已改变 · 请保存或确认入库';};
 $('#save-draft').onclick=()=>saveDraft('draft');$('#confirm-match').onclick=()=>saveDraft('confirmed');
 if($('#archive-match'))$('#archive-match').onclick=()=>{if(confirm(draft.status==='archived'?'恢复为草稿后，可重新核对入库。':'归档后本局将退出统计，记录与截图仍保留。继续？'))saveDraft(draft.status==='archived'?'draft':'archived');};
}
function bindPlayers(){document.querySelectorAll('[data-player]').forEach(el=>el.oninput=()=>{const p=draft.players.find(p=>`${p.side}-${p.slot}`===el.dataset.player);if(['hero','equipment'].includes(el.dataset.key)){draft.iconReviews=(draft.iconReviews||[]).filter(r=>!(r.side===p.side&&r.slot===p.slot&&r.kind===(el.dataset.key==='hero'?'hero':'equipment')));if(el.dataset.key==='equipment')p.equipmentSlots=[];}p[el.dataset.key]=el.value;if(el.dataset.key==='playerId'&&!p.position){p.position=state.settings.roster.find(r=>r.id===el.value)?.position||'';const row=el.closest('tr');row.querySelector('[data-key=position]').value=p.position;}remember();});}
async function hydrateEvidence(){
 const id=draft.id;
 const missing=draft.imageIds.filter(imageId=>!ocrResults.has(imageId)&&state.images.some(im=>im.id===imageId&&im.recognized));
 if(!missing.length)return;
 const results=await Promise.allSettled(missing.map(async imageId=>({imageId,result:await api('/api/images/'+imageId+'/recognition')})));
 let changed=false;
 for(const entry of results){if(entry.status==='fulfilled'&&entry.value.result){ocrResults.set(entry.value.imageId,entry.value.result);changed=true;}else if(entry.status==='rejected')toast('部分历史识别结果未能加载，可点击本地识别重试',true);}
 if(changed&&currentPage==='editor'&&draft.id===id)renderEvidence();
}
function downloadText(name,content,mime){
 const url=URL.createObjectURL(new Blob([content],{type:mime})),anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function reviewPage(id){
 $('#content').innerHTML='<div class="loading">正在读取已保存的比赛记录…</div>';
 try{const r=await api('/api/matches/'+encodeURIComponent(id)+'/review');if(currentPage!=='review'||location.hash!=='#review/'+id)return;
 renderReview($('#content'),r,{onImage:imageId=>{$('#full-image').src='/api/images/'+imageId;$('#image-dialog').showModal();},onExport:report=>downloadText(`训练复盘-${report.date||'待定'}-${report.id}.json`,JSON.stringify(report,null,2),'application/json;charset=utf-8')});
 }catch(e){toast(e.message,true);if(currentPage==='review')$('#content').innerHTML='<div class="notice">无法读取这条比赛，请回到比赛档案确认记录是否已保存。</div>';}
}
function evidenceCorrectionForm(id,r){
 const review=draft.evidenceReviews?.[id]||{},scores={...r.scores,...review.scores};
 return `<details class="page-correction"><summary>校正本张比分 / 日期${Object.keys(review).length?' · 已有校正':''}</summary><p class="helper">仅修正这张截图的识别信息，不改原始结果。看不清可留空；先排除不同比赛，再纠正误读。</p><div class="page-correction-grid">${['left','right'].map(side=>`<label class="field">${side==='left'?'左':'右'}侧比分<input data-page-score="${side}" data-image="${id}" value="${esc(scores[side]??'')}" inputmode="numeric" placeholder="未知"></label>`).join('')}<label class="field">截图日期<input type="date" data-page-date="${id}" value="${esc('date' in review?review.date:r.meta?.date||'')}"></label></div></details>`;
}
function updateEvidenceConflicts(){
 const node=$('#evidence-conflicts');if(!node)return;
 const results=draft.imageIds.map(id=>{const r=ocrResults.get(id);if(!r)return null;const edit=draft.evidenceReviews?.[id]||{};return {scores:{...r.scores,...edit.scores},date:'date' in edit?edit.date:r.meta?.date};}).filter(Boolean);
 const messages=[];
 for(const side of ['left','right']){const values=new Set(results.map(r=>r.scores[side]).filter(v=>v!==undefined&&v!=='').map(Number));if(values.size>1)messages.push(`${side==='left'?'左':'右'}侧比分不一致（${[...values].join(' / ')}）`);}
 const dates=new Set(results.map(r=>r.date).filter(Boolean));if(dates.size>1)messages.push('截图日期不一致');
 node.hidden=!messages.length;node.textContent=messages.join('；')+'。请先核对是否为同一局，正式入库前须处理。';
}
function renderEvidence(){
 const container=$('#evidence-list');if(!container)return;
 container.innerHTML=draft.imageIds.map(id=>{const info=state.images.find(im=>im.id===id),r=ocrResults.get(id);return `<div class="evidence-card"><img src="/api/images/${id}" data-preview="${id}" alt="${esc(info?.name||'本局截图')}"><div class="evidence-info"><div class="evidence-name">${esc(info?.name||'截图')}</div><div class="evidence-actions"><button class="button ghost" data-ocr="${id}">${r?'重新识别':'本地识别'}</button><button class="button ghost" data-unlink="${id}">移出本局</button></div><div id="ocr-${id}" class="evidence-status">${r?`${r.kind==='data'?'数据页':r.kind==='score'?'战绩页':'未匹配页面'} · 比分 ${esc(r.scores.left||'?')} : ${esc(r.scores.right||'?')}`:info?.postgame?'分页采集已写入；团队字段请回截图采集查看':'等待识别或手动录入'}</div>${r?`<div class="evidence-actions"><button class="button secondary" data-apply="${id}" ${r.kind==='unknown'?'disabled':''}>填入空白字段</button>${r.visuals?.length?`<button class="button secondary" data-icon-review="${id}">图标核对</button>`:''}</div>${evidenceCorrectionForm(id,r)}<details><summary class="helper" style="margin-top:9px;cursor:pointer">原始文字与限制</summary><div class="evidence-warnings">${r.warnings.map(esc).join('<br>')}</div><div class="raw-text">${r.tokens.map(t=>esc(t.text)).join(' · ')}</div></details>`:''}</div></div>`;}).join('')+`<label class="mini-upload">＋ 添加本局截图<small>战绩页 / 数据页 · 支持多选</small><input id="image-file" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden></label>`;
 $('#image-count').textContent=draft.imageIds.length+' 张';$('#image-file').onchange=e=>uploadFiles(e.target.files);
 container.ondragover=e=>e.preventDefault();container.ondrop=e=>{e.preventDefault();uploadFiles(e.dataTransfer.files);};
 container.querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>{$('#full-image').src='/api/images/'+b.dataset.preview;$('#image-dialog').showModal();});
 container.querySelectorAll('[data-ocr]').forEach(b=>b.onclick=()=>runOCR(b.dataset.ocr));
 container.querySelectorAll('[data-icon-review]').forEach(b=>b.onclick=()=>reviewIcons(b.dataset.iconReview));
 container.querySelectorAll('[data-page-score]').forEach(input=>input.oninput=()=>{draft.evidenceReviews??={};const review=draft.evidenceReviews[input.dataset.image]??={};review.scores??={};review.scores[input.dataset.pageScore]=input.value;review.editedAt=new Date().toISOString();remember();updateEvidenceConflicts();});
 container.querySelectorAll('[data-page-date]').forEach(input=>input.oninput=()=>{draft.evidenceReviews??={};const review=draft.evidenceReviews[input.dataset.pageDate]??={};review.date=input.value;review.editedAt=new Date().toISOString();remember();updateEvidenceConflicts();});
 updateEvidenceConflicts();
 container.querySelectorAll('[data-apply]').forEach(b=>b.onclick=()=>applyOCR(b.dataset.apply));
 container.querySelectorAll('[data-unlink]').forEach(b=>b.onclick=()=>{if(confirm('将此截图移出当前比赛？原始图片仍保留在本地数据库。')){draft.imageIds=draft.imageIds.filter(id=>id!==b.dataset.unlink);draft.iconReviews=(draft.iconReviews||[]).filter(r=>r.imageId!==b.dataset.unlink);if(draft.evidenceReviews)delete draft.evidenceReviews[b.dataset.unlink];remember();renderEvidence();}});
}
async function uploadFiles(files){
 if(!draft||currentPage!=='editor')return;
 if(busy){toast('正在处理截图，请稍候');return;}
 busy=true;
 try{for(const file of files){if(draft.imageIds.length>=20)throw Error('每局最多关联 20 张截图');const response=await fetch('/api/images?name='+encodeURIComponent(file.name),{method:'POST',body:file});const result=await response.json();if(!response.ok)throw Error(result.detail||'上传失败');if(draft.imageIds.includes(result.id)){toast('这张截图已在本局中，不重复添加');continue;}state.images.push(result);draft.imageIds.push(result.id);remember();renderEvidence();await runOCR(result.id);}}
 catch(e){toast(e.message,true);}finally{busy=false;}
}
async function runOCR(id){
 const status=$('#ocr-'+id);if(status)status.textContent='正在本机识别，请稍候…';
 document.querySelectorAll(`[data-ocr="${id}"]`).forEach(b=>b.disabled=true);
 try{const r=await api('/api/images/'+id+'/ocr'+(ocrResults.has(id)?'?refresh=true':''),'POST');ocrResults.set(id,r);if(currentPage==='editor'&&draft.imageIds.includes(id))renderEvidence();}
 catch(e){toast(e.message,true);if(status)status.textContent='未完成识别，可继续手动录入';document.querySelectorAll(`[data-ocr="${id}"]`).forEach(b=>b.disabled=false);}
}
function applyOCR(id){
 const r=ocrResults.get(id);if(!r)return;
 const corrected=draft.evidenceReviews?.[id]||{};
 const effectiveScores={...r.scores,...corrected.scores};
 const effectiveMeta={...r.meta,...('date' in corrected?{date:corrected.date}:{})};
 for(const side of ['left','right']){if(effectiveScores[side]!==undefined&&effectiveScores[side]!==''&&draft.scores[side]!==''&&Number(effectiveScores[side])!==Number(draft.scores[side])){toast('比分冲突：请核对两张图是否同局，或在页面信息校正中修正 OCR 误读。',true);return;}}
 let count=0,conflicts=0;
 for(const [key,value] of Object.entries(effectiveScores)){if(draft.scores[key]===''&&value!==''){draft.scores[key]=value;count++;}}
 for(const [key,value] of Object.entries(effectiveMeta||{})){if(!draft[key]){draft[key]=value;count++;}}
 for(const row of r.players){const p=draft.players.find(p=>p.side===row.side&&p.slot===row.slot);if(!p)continue;for(const [key,source] of Object.entries(row.fields)){if(p[key]===''||p[key]===null||p[key]===undefined){p[key]=source.value;p.sources??={};p.sources[key]={...source,imageId:id};count++;}else if(String(p[key])!==String(source.value))conflicts++;}}
 draft.ocrAudit??=[];draft.ocrAudit.push({imageId:id,appliedAt:new Date().toISOString(),count,conflicts});remember();editor();toast(`填入 ${count} 个空白字段${conflicts?'；'+conflicts+' 处已有值保留，请对照截图核对':''}。英雄与队员请手动确认。`);
}
function reviewIcons(imageId){
 const result=ocrResults.get(imageId);if(!result)return;
 openIconReview({imageId,result,draft,catalog:iconCatalog,onApply:choices=>{
   draft.iconReviews??=[];
   for(const choice of choices){
     const p=draft.players.find(p=>p.side===choice.side&&p.slot===choice.slot);
     draft.iconReviews=draft.iconReviews.filter(r=>!(r.side===choice.side&&r.slot===choice.slot&&r.kind===choice.kind&&r.index===choice.index));
     draft.iconReviews.push({imageId,catalogId:choice.catalogId,name:choice.name,kind:choice.kind,side:choice.side,slot:choice.slot,index:choice.index,box:choice.box,reviewedAt:new Date().toISOString()});
     if(choice.kind==='hero'){p.hero=choice.name;}
     else{p.equipmentSlots=Array.from({length:6},(_,i)=>p.equipmentSlots?.[i]||null);p.equipmentSlots[choice.index]={id:choice.catalogId,name:choice.name};p.equipment=p.equipmentSlots.map(e=>e?.name||'未识别').join(' / ');}
   }
   draft.ocrAudit??=[];draft.ocrAudit.push({imageId,appliedAt:new Date().toISOString(),type:'icon-review',count:choices.length});remember();editor();toast(`已应用 ${choices.length} 项图标选择，请确认入库；英雄名称不参与头像学习。`);
 }});
}
async function saveDraft(status){
 if(busy){toast('截图处理完成后再保存');return;}
 if(!hasDraftContent(draft)){toast('尚未填写任何内容，无需保存空白草稿',true);return;}
 const buttons=[$('#save-draft'),$('#confirm-match')];buttons.forEach(b=>b.disabled=true);
 try{draft=await api('/api/matches','POST',{...draft,status});dirty=false;localStorage.removeItem('training-unsaved');await refresh();editor();toast(status==='confirmed'?'已确认入库，训练统计已更新':status==='archived'?'已归档，记录与截图仍保留':'草稿已保存');}
 catch(e){toast(e.message,true);}finally{buttons.forEach(b=>b.disabled=false);}
}
function rosterPage(){
 const laneOptions=value=>`<option value="">分路待确认</option>${positions.map(pos=>`<option${pos===value?' selected':''}>${pos}</option>`).join('')}`;
 $('#content').innerHTML=heading('战队与选手名单','选择内置战队或填写自定义队名；为每位选手设置默认分路，每局仍可单独调整。')+`<section class="panel"><div class="panel-header"><h2>战队设置</h2><span class="tag gray">${state.settings.roster.length} 位队员</span></div><div class="roster-form"><div class="form-grid"><label class="field">参赛层级<select id="team-league">${['KPL','次级联赛','普通战队'].map(v=>`<option${v===(state.settings.league||'普通战队')?' selected':''}>${v}</option>`).join('')}</select></label><label class="field">战队选择<select id="team-preset">${teamPresetOptions(state.settings.teamName)}</select></label><label class="field">战队名称（可自定义）<input id="team-name" value="${esc(state.settings.teamName)}" maxlength="50"></label></div><p class="helper">内置名单：<a href="${teamPresetSource}" target="_blank" rel="noopener">${teamPresetLabel}</a>。改名或新队可直接填写自定义名称。</p><div class="roster-grid">${state.settings.roster.map(p=>`<div class="roster-entry"><span class="initial">${esc(p.name[0])}</span><label class="field">选手昵称<input class="control" data-roster="${esc(p.id)}" value="${esc(p.name)}" maxlength="50"></label><label class="field">默认分路<select data-roster-lane="${esc(p.id)}">${laneOptions(p.position)}</select></label></div>`).join('')}</div><div class="roster-add"><input class="control" id="new-player" aria-label="新队员昵称" placeholder="添加队员昵称" maxlength="50"><select id="new-player-lane" class="control" aria-label="新队员默认分路">${laneOptions('')}</select><button class="button secondary" id="add-player">＋ 添加队员</button></div><p class="helper">默认分路用于录入建议，不覆盖历史对局的实际分路。首发、替补均可加入。</p><button class="button primary" id="save-roster">保存战队设置</button></div></section>`;
 $('#team-preset').onchange=()=>{const value=$('#team-preset').value;if(value==='__custom__'){$('#team-name').focus();$('#team-name').select();return;}if(value){$('#team-name').value=value;$('#team-league').value='KPL';}};
 const collect=()=>({...state.settings,league:$('#team-league').value,teamName:$('#team-name').value.trim(),roster:state.settings.roster.map(p=>({...p,name:document.querySelector(`[data-roster="${CSS.escape(p.id)}"]`).value.trim(),position:document.querySelector(`[data-roster-lane="${CSS.escape(p.id)}"]`).value}))});
 const save=async(add=false)=>{try{const s=collect();if(add){const name=$('#new-player').value.trim();if(!name)throw Error('请填写新队员昵称');s.roster.push({id:uid(),name,position:$('#new-player-lane').value});}await api('/api/settings','PUT',s);await refresh();rosterPage();toast('战队名单已保存');}catch(e){toast(e.message,true);}};
 $('#add-player').onclick=()=>save(true);$('#save-roster').onclick=()=>save();$('#new-player').onkeydown=e=>{if(e.key==='Enter')save(true);};
}
function durationControl(){
 const seconds=draft.duration===''||draft.duration==null?null:Math.round(Number(draft.duration)*60);
 return `<div class="field duration-control"><span>对局时长 · 分 : 秒（可留空）</span><div class="duration-inputs"><input id="duration-minutes" type="number" min="0" max="120" step="1" aria-label="对局时长分钟" placeholder="分" value="${seconds===null?'':Math.floor(seconds/60)}"><b>:</b><input id="duration-seconds" type="number" min="0" max="59" step="1" aria-label="对局时长秒" placeholder="秒" value="${seconds===null?'':seconds%60}"><button type="button" class="text-link" id="duration-clear">留空</button></div><input id="duration-slider" type="range" min="0" max="7200" step="1" value="${seconds||0}" aria-label="拖动设置对局时长"><output id="duration-readout">${seconds===null?'时长未知':Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0')}</output></div>`;
}
function bindDuration(){
 const minute=$('#duration-minutes'),second=$('#duration-seconds'),slider=$('#duration-slider'),output=$('#duration-readout');
 const set=seconds=>{draft.duration=seconds===null?'':seconds/60;minute.value=seconds===null?'':Math.floor(seconds/60);second.value=seconds===null?'':seconds%60;slider.value=seconds||0;output.textContent=seconds===null?'时长未知':Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');remember();};
 slider.oninput=()=>set(Number(slider.value));
 const fromInputs=()=>{if(minute.value===''&&second.value===''){set(null);return;}if(!minute.checkValidity()||!second.checkValidity()){(minute.checkValidity()?second:minute).reportValidity();return;}set(Math.min(7200,Number(minute.value||0)*60+Number(second.value||0)));};
 minute.onchange=fromInputs;second.onchange=fromInputs;$('#duration-clear').onclick=()=>set(null);
}

async function route(){
 const hash=location.hash.slice(1)||'overview';
 if(dirty&&currentPage==='editor'&&hash!==`edit/${draft.id}`){if(!confirm('当前比赛有未保存修改。离开前建议保存草稿。仍要离开？')){history.replaceState(null,'','#edit/'+draft.id);return;}dirty=false;}
 if(busy){toast('正在处理截图，请完成后再切换');history.replaceState(null,'','#edit/'+draft.id);return;}
 const page=hash.startsWith('edit/')||hash==='new'?'editor':hash.startsWith('review/')?'review':hash.startsWith('channel/')?'channel':hash==='analysis'?'stats':hash;
 currentPage=page;if(!embedded)document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===(['editor','review'].includes(page)?'matches':page==='channel'?'channels':page)));
 if(page==='editor'){
  const id=hash.split('/')[1];const existing=state.matches.find(m=>m.id===id);
  if(hash==='new'){
   let buffered;try{buffered=JSON.parse(localStorage.getItem('training-unsaved'));}catch{}
   const recoverable=isRecoverableDraft(buffered,state.matches);
   if(!recoverable)localStorage.removeItem('training-unsaved');
   const restore=recoverable&&confirm('发现一条尚未保存的草稿，继续填写它？');
   draft=restore?buffered:blankMatch();dirty=!!restore;
   if(recoverable&&!restore)localStorage.removeItem('training-unsaved');
   history.replaceState(null,'','#edit/'+draft.id);
  }else if(existing&&draft?.id===id&&dirty){}else if(existing){let buffered;try{buffered=JSON.parse(localStorage.getItem('training-unsaved'));}catch{}const recover=buffered?.id===id&&isRecoverableDraft(buffered,state.matches);if(recover&&confirm('本局有未保存的修改，恢复继续填写？')){draft=buffered;dirty=true;}else{draft=structuredClone(existing);dirty=false;if(buffered?.id===id)localStorage.removeItem('training-unsaved');}}
  else if(!draft||draft.id!==id){let buffered;try{buffered=JSON.parse(localStorage.getItem('training-unsaved'));}catch{}if(buffered?.id===id&&isRecoverableDraft(buffered,state.matches)){draft=buffered;dirty=true;}else{toast('没有找到该比赛，已返回档案',true);location.hash='matches';return;}}
  editor();
 }else if(page==='replays'){if(!FEATURES.replay){location.hash='channels';return;}await renderReplays($('#content'),{api,toast,isCurrent:()=>currentPage==='replays'&&location.hash.slice(1)===hash});}else if(page==='recordings')await renderRecordings($('#content'),{api,toast,isCurrent:()=>currentPage==='recordings'&&location.hash.slice(1)===hash});else if(page==='screenshots')await renderScreenshots($('#content'),{api,toast,isCurrent:()=>currentPage==='screenshots'&&location.hash.slice(1)===hash});else if(page==='channels')await renderChannels($('#content'),{api,toast,isCurrent:()=>currentPage==='channels'&&location.hash.slice(1)===hash});else if(page==='channel')await renderChannel($('#content'),{api,toast,isCurrent:()=>currentPage==='channel'&&location.hash.slice(1)===hash,id:hash.split('/')[1]});else if(page==='review')await reviewPage(hash.split('/')[1]);else if(page==='matches')matchesPage();else if(page==='training')await renderStats($('#content'),{api,toast,isCurrent:()=>currentPage==='training'&&location.hash.slice(1)===hash,initialTab:'focus'});else if(page==='stats')await renderStats($('#content'),{api,toast,isCurrent:()=>currentPage==='stats'&&location.hash.slice(1)===hash});else if(page==='roster')rosterPage();else overview();
 window.scrollTo(0,0);
}
$('#close-dialog').onclick=()=>$('#image-dialog').close();
$('#backup').onclick=()=>{const a=document.createElement('a');a.href=embedded?'/api/studio/project-backup':'/api/backup';a.download=`训练室备份-${localDate()}.json`;a.click();};
$('#restore').onclick=()=>$('#backup-file').click();
$('#mobile-backup').onclick=()=>$('#backup').click();
$('#mobile-restore').onclick=()=>$('#restore').click();
$('#backup-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>120*1024*1024)throw Error('备份大于 120 MB，请联系开发者处理');const text=await file.text();if(!confirm('把备份中的记录合并到本机？相同 ID 的比赛会保留本机版本，不覆盖。'))return;const response=await fetch(embedded?'/api/studio/project-restore':'/api/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:text});const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'恢复失败');await refresh();if(embedded)window.dispatchEvent(new Event('hashchange'));else await route();toast(`恢复完成：新增 ${result.added} 局，跳过 ${result.skipped} 条已有记录${result.replaysAddedOrUpdated?`，回放新增/更新 ${result.replaysAddedOrUpdated} 份`:''}`);}catch(error){toast(error.message,true);}finally{e.target.value='';}};
if(!embedded)window.addEventListener('hashchange',()=>route().catch(e=>toast(e.message,true)));
window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
if(!embedded){
$('#content').innerHTML='<div class="loading">正在打开本机训练空间…</div>';
try{await refresh();await route();}catch(e){$('#content').innerHTML=`<div class="notice">工作台未能连接本地服务：${esc(e.message)}。请确认启动窗口仍在运行。</div>`;}

}
export async function renderWorkbench(){const expected=location.hash;await refresh();if(location.hash!==expected)return;await route();}
export function deactivateWorkbench(){currentPage='';}
export function allowWorkbenchNavigation(hash){
 if(busy){toast('截图处理完成后再切换');history.replaceState(null,'','#edit/'+draft.id);return false;}
 if(dirty&&currentPage==='editor'&&hash!==`edit/${draft.id}`){if(!confirm('当前比赛有未保存修改，仍要离开？')){history.replaceState(null,'','#edit/'+draft.id);return false;}dirty=false;}
 return true;
}
