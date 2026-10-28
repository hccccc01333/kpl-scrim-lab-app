import { openIconReview } from '/assets/icon-review.js';
const $ = (q) => document.querySelector(q);
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => crypto.randomUUID();
const heroes = '阿古朵 阿轲 艾琳 安琪拉 敖隐 白起 百里守约 百里玄策 扁鹊 不知火舞 蔡文姬 曹操 嫦娥 程咬金 成吉思汗 大乔 达摩 大司命 狄仁杰 典韦 貂蝉 东皇太一 盾山 朵莉亚 伽罗 干将莫邪 高渐离 戈娅 宫本武藏 公孙离 鬼谷子 关羽 海月 韩信 后羿 黄忠 花木兰 姬小满 姜子牙 金蝉 镜 伽罗 狂铁 铠 兰陵王 澜 老夫子 莱西奥 李白 李信 李元芳 廉颇 刘邦 刘备 刘禅 鲁班大师 鲁班七号 露娜 吕布 马超 马可波罗 蒙犽 蒙恬 梦奇 芈月 米莱狄 明世隐 墨子 哪吒 娜可露露 牛魔 女娲 盘古 裴擒虎 司空震 司马懿 苏烈 孙膑 孙策 孙尚香 孙悟空 孙权 沈梦溪 上官婉儿 沈梦溪 少司缘 太乙真人 西施 夏侯惇 夏洛特 项羽 小乔 雅典娜 亚连 亚瑟 杨戬 杨玉环 瑶 曜 影 弈星 嬴政 云缨 云中君 虞姬 元歌 甄姬 张飞 张良 赵怀真 赵云 钟馗 钟无艳 周瑜 猪八戒 庄周 诸葛亮 '.split(' ');
$('#hero-list').innerHTML = [...new Set(heroes)].filter(x=>!x.includes('?')).sort((a,b)=>a.localeCompare(b,'zh')).map(h=>`<option value="${esc(h)}">`).join('');
let state, draft, dirty = false, currentPage = '', analysisTab = 'heroes', toastTimer, busy = false;
const ocrResults = new Map(); let iconCatalog = {entries:[]};
const fields = [ ['kills','击杀'], ['deaths','死亡'], ['assists','助攻'], ['gold','总经济'], ['damage','输出'], ['taken','承伤'], ['participation','参团 %'], ['rating','评分'] ];
const positions = ['对抗路','打野','中路','发育路','游走'];
const fmt = (n, decimals=1) => n === null || n === undefined ? '—' : Number(n).toLocaleString('zh-CN',{maximumFractionDigits:decimals});
const pct = (wins,games) => games ? Math.round(wins/games*100)+'%' : '—';
const localDate = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());

async function api(url, method='GET', value) {
  const response = await fetch(url, {method, ...(value === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(value)})});
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '请求失败，请检查输入');
  return result;
}
function toast(message,error=false){ const t=$('#toast'); t.textContent=message;t.hidden=false;t.classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,error?8500:4500); }
async function refresh(){const results=await Promise.all([api('/api/state'),api('/api/catalog')]);state=results[0];iconCatalog=results[1];if(iconCatalog.entries.length)document.querySelector('#hero-list').innerHTML=iconCatalog.entries.filter(e=>e.kind==='hero').map(e=>'<option value=' + String.fromCharCode(34) + esc(e.name) + String.fromCharCode(34) + '>').join('');$('#team-label').textContent=state.settings.teamName;$('#match-count').textContent=state.matches.filter(m=>m.status!=='archived').length;}
function heading(eyebrow,title,subtitle,action=''){return `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${esc(title)}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;}
const newButton = '<a class="button" href="#new"><span class="plus">+</span>录入训练赛</a>';
function metrics(){const s=state.summary;return `<div class="metrics">${[
  ['已确认训练赛',s.games,'局','草稿与已归档比赛不计入','≡'],
  ['训练赛胜率',pct(s.wins,s.games),'',`${s.wins} 胜 / ${s.games-s.wins} 负`,'↗'],
  ['已使用英雄',s.heroes.length,'位','本队已确认的英雄出场','◇'],
  ['待校对草稿',s.drafts,'局','核对后才进入正式统计','◷']
].map(([label,value,unit,note,icon])=>`<div class="metric"><div class="metric-label">${label}<span class="metric-icon">${icon}</span></div><div class="metric-number">${value}<small>${unit}</small></div><div class="metric-note">${note}</div></div>`).join('')}</div>`;}
const orderedMatches=()=>[...state.matches].sort((a,b)=>(b.date||'').localeCompare(a.date||'')||(b.updatedAt||0)-(a.updatedAt||0));
function resultTag(m){return m.status==='draft'?'<span class="tag amber">待校对</span>':m.status==='archived'?'<span class="tag gray">已归档</span>':m.side===m.winner?'<span class="tag">胜利</span>':'<span class="tag amber">失利</span>';}
function overview(){
  const recent=orderedMatches().filter(m=>m.status!=='archived').slice(0,4);
  $('#content').innerHTML=heading('TRAIN · REVIEW · IMPROVE','把每一场训练，变成下一场的进步','从赛后截图到团队复盘，让训练数据持续积累。',newButton)+metrics()+`
  <div class="overview-grid"><section class="panel"><div class="panel-header"><div><h2>开始记录一场训练赛</h2><div class="panel-subtitle">SCREENSHOT TO INSIGHT</div></div><span class="tag">赛后截图入库</span></div><div class="start-area"><div class="drop-hero" id="home-drop" tabindex="0" role="button" aria-label="上传赛后截图"><div class="upload-symbol">↥</div><h3>把赛后截图交给训练室</h3><p>战绩页与数据页一起上传，识别后核对保存。<br>支持多张截图，也可以先手动记录。</p><a class="button" href="#new">＋ 新建比赛记录</a><p class="formats">PNG / JPG / WEBP · 单张不超过 12 MB · 本机识别</p></div><div class="steps"><div class="step"><span><b>1</b>上传截图</span>同一局的页面放在一起</div><div class="step"><span><b>2</b>核对数据</span>确认阵营、队员与识别值</div><div class="step"><span><b>3</b>沉淀分析</span>自动汇总英雄和队员表现</div></div></div></section>
  <section class="panel"><div class="panel-header"><h2>训练记录</h2><a href="#matches" class="button ghost">全部记录 ↗</a></div>${recent.length?recent.map(m=>`<a class="recent-row" href="#edit/${m.id}"><div><strong>vs ${esc(m.opponent||'尚未填写对手')}</strong><small>${esc(m.date||'日期待补充')} · ${esc(m.session||'日常训练')}</small></div>${resultTag(m)}</a>`).join(''):'<div class="empty"><strong>训练档案，从第一局开始</strong>保存的比赛会出现在这里，<br>每条统计都能回到原始记录。</div>'}<div class="side-note"><h3>先确认，再统计</h3><p>识别结果保留为候选，校对后才入库。英雄头像与队员身份目前需要手动确认。</p><a class="button ghost" href="#roster">${state.settings.roster.length?'管理队员名单':'先建立队员名单'} →</a></div></section></div>
  <section class="panel section-gap"><div class="panel-header"><h2>英雄训练表现</h2><a href="#analysis" class="button ghost">查看分析 ↗</a></div>${state.summary.heroes.length?summaryTable(state.summary.heroes.slice(0,5),'heroes'):'<div class="empty">正式入库后，这里将展示英雄出场、胜率与表现。数据不足时不做强弱评级。</div>'}</section>`;
  const drop=$('#home-drop');drop.onclick=e=>{if(!e.target.closest('a'))location.hash='new';};drop.onkeydown=e=>{if(e.key==='Enter')location.hash='new';};
  drop.ondragover=e=>e.preventDefault();drop.ondrop=async e=>{e.preventDefault();location.hash='new';setTimeout(()=>uploadFiles(e.dataTransfer.files),100);};
}
function matchesPage(){
 $('#content').innerHTML=heading('MATCH ARCHIVE','训练赛档案','保留过程，积累对手与阵容经验。',newButton)+`<div class="toolbar"><input class="control" id="search-matches" placeholder="搜索对手、备注、训练分组" aria-label="搜索比赛"><select class="control" id="status-filter" style="width:135px"><option value="active">全部有效记录</option><option value="confirmed">已确认</option><option value="draft">待校对</option><option value="archived">已归档</option></select><span class="filters-count" id="list-count"></span></div><section class="panel"><div class="table-wrap"><table><thead><tr><th>日期 / 分组</th><th>对手</th><th>比分（左 : 右）</th><th>本队阵营</th><th>状态 / 结果</th><th>备注</th><th></th></tr></thead><tbody id="match-rows"></tbody></table></div></section>`;
 const draw=()=>{const q=$('#search-matches').value.toLowerCase(),status=$('#status-filter').value;const list=orderedMatches().filter(m=>(status==='active'?m.status!=='archived':m.status===status)&&[m.opponent,m.notes,m.session].join(' ').toLowerCase().includes(q));$('#list-count').textContent=`${list.length} 条记录`;$('#match-rows').innerHTML=list.length?list.map(m=>`<tr><td><strong>${esc(m.date||'日期待填写')}</strong><div class="helper">${esc(m.session||'日常训练')}</div></td><td>${esc(m.opponent||'待填写')}</td><td>${esc(m.scores?.left||'—')} : ${esc(m.scores?.right||'—')}</td><td>${m.side==='left'?'左侧':m.side==='right'?'右侧':'待确认'}</td><td>${resultTag(m)}</td><td class="note-cell">${esc(m.notes||'—')}</td><td><a class="button ghost" href="#edit/${m.id}">查看 / 校对 →</a></td></tr>`).join(''):'<tr><td colspan="7" class="empty">暂无符合条件的记录。新建一场训练赛，或调整筛选条件。</td></tr>';};
 $('#search-matches').oninput=draw;$('#status-filter').onchange=draw;draw();
}
function summaryTable(rows,kind){
 const label={heroes:'英雄',players:'队员',opponents:'对手',lineups:'本队五人英雄组合'}[kind];
 const personal=['heroes','players'].includes(kind);
 return `<div class="table-wrap"><table><thead><tr><th>${label}</th><th>出场 / 比赛数</th><th>胜场 / 胜率</th>${personal?'<th>场均 K / D / A</th><th>场均输出 / 样本</th><th>场均承伤 / 样本</th><th>场均经济 / 样本</th>':''}<th>证据</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td>${r.games}</td><td>${r.wins} 胜 · ${pct(r.wins,r.games)}<span class="winbar"><i style="width:${r.wins/r.games*100}%"></i></span></td>${personal?`<td>${fmt(r.kills)} / ${fmt(r.deaths)} / ${fmt(r.assists)}</td><td>${fmt(r.damage,0)} <span class="helper">/ ${r.damageSamples} 局</span></td><td>${fmt(r.taken,0)} <span class="helper">/ ${r.takenSamples} 局</span></td><td>${fmt(r.gold,0)} <span class="helper">/ ${r.goldSamples} 局</span></td>`:''}<td><button class="button ghost" data-evidence="${esc(r.key)}">逐局查看 ↗</button></td></tr>`).join('')}</tbody></table></div>`;
}
async function analysisPage(){
 $('#content').innerHTML=heading('TEAM INSIGHTS','英雄与队员分析','统计基于已确认比赛；缺失数据不当作零，胜率始终展示样本量。')+`<div class="tabs">${Object.entries({heroes:'英雄训练',players:'队员表现',opponents:'对手记录',lineups:'阵容记录'}).map(([key,label])=>`<button class="tab ${analysisTab===key?'active':''}" data-tab="${key}">${label}</button>`).join('')}</div><div class="toolbar"><label>起始日期<input type="date" class="control" id="from-date"></label><label>结束日期<input type="date" class="control" id="to-date"></label><input class="control" id="filter-opponent" placeholder="筛选对手" aria-label="筛选对手"><input class="control" id="filter-version" placeholder="筛选版本" aria-label="筛选版本"><select class="control" style="width:145px" id="filter-player" aria-label="筛选队员"><option value="">全部出场队员</option>${state.settings.roster.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></div><section class="panel" id="analysis-table"></section><section id="drilldown" class="panel section-gap" hidden></section>`;
 let drawSeq=0;
 const draw=async()=>{
  const seq=++drawSeq, params=new URLSearchParams();
  for(const [id,key] of [['from-date','from'],['to-date','to'],['filter-opponent','opponent'],['filter-version','version'],['filter-player','player']])params.set(key,$('#'+id).value);
  if(params.get('from')&&params.get('to')&&params.get('from')>params.get('to')){toast('起始日期不能晚于结束日期',true);return;}
  try{const summary=await api('/api/summary?'+params);if(seq!==drawSeq)return;const rows=summary[analysisTab];$('#analysis-table').innerHTML=rows.length?summaryTable(rows,analysisTab)+`<div class="summary-footnote">范围内 ${summary.games} 局已确认比赛。场均值仅使用有该项数据的对局；未按时长标准化，不直接用于跨位置评级。英雄组合按五人英雄集合统计。</div>`:'<div class="empty"><strong>这个范围内还没有可统计的比赛</strong>先将训练赛校对入库，或调整筛选范围。</div>';document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>drilldown(rows.find(r=>r.key===b.dataset.evidence)));}catch(e){toast(e.message,true);}
 };
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{analysisTab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(t=>t.classList.toggle('active',t===b));$('#drilldown').hidden=true;draw();});
 for(const id of ['from-date','to-date','filter-opponent','filter-version','filter-player'])$('#'+id).oninput=draw;
 await draw();
}
function drilldown(row){const box=$('#drilldown');if(!box||!row)return;box.hidden=false;box.innerHTML=`<div class="panel-header"><h2>${esc(row.name)} · 比赛证据</h2><span class="tag gray">${row.games} 局</span></div>`+row.matchIds.map(id=>state.matches.find(m=>m.id===id)).filter(Boolean).map(m=>`<a class="recent-row" href="#edit/${esc(m.id)}"><div><strong>vs ${esc(m.opponent)}</strong><small>${esc(m.date)} · ${esc(m.session||'日常训练')}</small></div>${resultTag(m)}</a>`).join('');box.scrollIntoView({behavior:'smooth',block:'nearest'});}
function blankMatch(){return {id:uid(),revision:0,status:'draft',date:'',side:'',winner:'',opponent:'',version:'',session:'',duration:'',notes:'',bp:'',reviewed:false,scores:{left:'',right:''},imageIds:[],players:['left','right'].flatMap(side=>Array.from({length:5},(_,slot)=>({side,slot,hero:'',playerId:'',position:'',equipment:'',...Object.fromEntries(fields.map(([k])=>[k,'']))}))),ocrAudit:[]};}
function remember(){dirty=true;draft.reviewed=false;const check=$('#reviewed');if(check)check.checked=false;const hint=$('#save-hint');if(hint)hint.textContent='有未保存修改 · 请保存草稿或重新确认入库';try{localStorage.setItem('training-unsaved',JSON.stringify(draft));}catch{} }
function field(label,name,type='text',placeholder=''){return `<label class="field">${label}<input data-meta="${name}" type="${type}" value="${esc(draft[name])}" placeholder="${placeholder}"></label>`;}
function sideSelect(name,label){return `<label class="field">${label}<select data-meta="${name}"><option value="">请确认</option><option value="left" ${draft[name]==='left'?'selected':''}>截图左侧</option><option value="right" ${draft[name]==='right'?'selected':''}>截图右侧</option></select></label>`;}
function playerTable(side){return `<section class="panel editor-panel"><div class="panel-header"><h2>${side==='left'?'左侧':'右侧'}五人 <span class="tag gray">${draft.side===side?'本队':'请按截图顺序对应'}</span></h2><span class="helper">空值保留未知 · k = 千 · 绿色框为识别候选</span></div><div class="table-wrap"><table class="editor-table"><thead><tr><th>#</th><th>队员身份</th><th>英雄</th><th>实际分路</th>${fields.map(([,name])=>`<th>${name}</th>`).join('')}<th>装备</th></tr></thead><tbody>${draft.players.filter(p=>p.side===side).map(p=>`<tr data-row="${side}-${p.slot}"><td class="row-num">${p.slot+1}</td><td><select aria-label="${side}第${p.slot+1}行队员" class="player-input name" data-player="${p.side}-${p.slot}" data-key="playerId"><option value="">${draft.side===side?'关联本队队员':'对手 / 未关联'}</option>${state.settings.roster.map(r=>`<option value="${esc(r.id)}" ${r.id===p.playerId?'selected':''}>${esc(r.name)}</option>`).join('')}</select></td><td><input class="player-input hero" list="hero-list" data-player="${p.side}-${p.slot}" data-key="hero" aria-label="${side}第${p.slot+1}行英雄" value="${esc(p.hero)}" placeholder="手动选择"></td><td><select class="player-input" data-player="${p.side}-${p.slot}" data-key="position" aria-label="实际分路"><option value="">待确认</option>${positions.map(pos=>`<option ${p.position===pos?'selected':''}>${pos}</option>`).join('')}</select></td>${fields.map(([key])=>`<td><input class="player-input ${p.sources?.[key]?'source-ocr':''}" inputmode="decimal" data-player="${p.side}-${p.slot}" data-key="${key}" aria-label="${side}第${p.slot+1}行${key}" value="${esc(p[key])}" placeholder="—" title="${p.sources?.[key]?esc('识别原文：'+p.sources[key].raw+'；模型置信度：'+Math.round(p.sources[key].confidence*100)+'%。请人工核对。'):'未录入即为未知'}"></td>`).join('')}<td><input class="player-input name" data-player="${p.side}-${p.slot}" data-key="equipment" aria-label="装备" value="${esc(p.equipment||'')}" placeholder="待补充"></td></tr>`).join('')}</tbody></table></div></section>`;}
function editor(){
 const existing=state.matches.some(m=>m.id===draft.id), archived=draft.status==='archived';
 $('#content').innerHTML=`<a href="#matches" class="back-link">← 返回比赛档案</a>`+heading('MATCH WORKBENCH',existing?'校对与复盘':'记录一场新的训练赛','先建立一局，再把这局的战绩页、数据页放在一起。',resultTag(draft))+`
 ${!state.settings.roster.length?'<div class="notice">尚未建立队员名单。你可以先保存草稿，再到“战队名单”添加队员后关联本队五人。</div>':''}
 <div class="editor-layout"><div><section class="panel editor-panel"><div class="panel-header"><h2>比赛信息</h2><span class="helper">本队不固定在左侧，请根据截图确认</span></div><div class="form-section"><div class="form-grid">${field('比赛日期','date','date')}${field('对手名称','opponent','text','例如：周三训练对手')}${field('训练分组 / 大场','session','text','例如：晚训 BO5 · 第 1 局')}${sideSelect('side','本队在截图中的位置')}${sideSelect('winner','本局胜方')}${field('游戏版本','version','text','例如：S42 / 补丁日期')}${field('时长（分钟，可留空）','duration','text','例如：22.92')}<label class="field">左侧击杀比分<input data-score="left" value="${esc(draft.scores.left)}" inputmode="numeric" placeholder="待确认"></label><label class="field">右侧击杀比分<input data-score="right" value="${esc(draft.scores.right)}" inputmode="numeric" placeholder="待确认"></label></div></div></section></div>
 <aside class="panel"><div class="panel-header"><h2>原始截图</h2><span class="tag gray" id="image-count">${draft.imageIds.length} 张</span></div><div class="evidence-conflict notice" id="evidence-conflicts" hidden></div><div class="evidence-list" id="evidence-list"></div></aside></div>
 <div class="notice green">识别结果不会直接进入统计。请逐行对应截图确认队员和英雄；画面上下排列不代表分路。只录入一张图也可以，未提供的数据保持为空。</div>
 <div id="player-tables">${playerTable('left')}${playerTable('right')}</div>
 <section class="panel"><div class="panel-header"><h2>训练复盘</h2><span class="helper">先记录事实，再写判断</span></div><div class="form-section"><div class="form-grid"><label class="field wide">BP / 阵容要点<textarea data-meta="bp" placeholder="可记录禁用英雄、选人顺序、预期打法；未知时留空。">${esc(draft.bp)}</textarea></label><label class="field wide">本局复盘要点<textarea data-meta="notes" placeholder="例如：08:30 暴君争夺前队伍站位分散，下次训练重点检查集合时间。">${esc(draft.notes)}</textarea></label></div></div></section>
 <label class="check-row"><input type="checkbox" id="reviewed" ${draft.reviewed?'checked':''}>我已核对同局截图、本队阵营、胜负，以及本队五人的身份和英雄。缺失数据保留为空。</label>
 <div class="editor-actions"><div><span class="helper" id="save-hint">${existing?'本局已保存，修改后请重新保存':'尚未入库 · 草稿不计入统计'}</span>${existing?`<button class="button ghost" id="archive-match">${archived?'恢复为草稿':'归档此局'}</button>`:''}</div><div><button class="button secondary" id="save-draft">保存草稿</button><button class="button" id="confirm-match">确认数据并入库 →</button></div></div>`;
 bindEditor();renderEvidence();hydrateEvidence();
}
function bindEditor(){
 document.querySelectorAll('[data-meta]').forEach(el=>el.oninput=()=>{draft[el.dataset.meta]=el.value;remember();if(el.dataset.meta==='side'){const ownBadges=document.querySelectorAll('#player-tables .panel-header .tag');ownBadges.forEach((b,i)=>b.textContent=draft.side===['left','right'][i]?'本队':'请按截图顺序对应');}});
 document.querySelectorAll('[data-score]').forEach(el=>el.oninput=()=>{draft.scores[el.dataset.score]=el.value;remember();});
 bindPlayers();$('#reviewed').onchange=e=>{draft.reviewed=e.target.checked;dirty=true;document.querySelector('#save-hint').textContent='核对状态已改变 · 请保存或确认入库';};
 $('#save-draft').onclick=()=>saveDraft('draft');$('#confirm-match').onclick=()=>saveDraft('confirmed');
 if($('#archive-match'))$('#archive-match').onclick=()=>{if(confirm(draft.status==='archived'?'恢复为草稿后，可重新核对入库。':'归档后本局将退出统计，记录与截图仍保留。继续？'))saveDraft(draft.status==='archived'?'draft':'archived');};
}
function bindPlayers(){document.querySelectorAll('[data-player]').forEach(el=>el.oninput=()=>{const p=draft.players.find(p=>`${p.side}-${p.slot}`===el.dataset.player);if(['hero','equipment'].includes(el.dataset.key)){draft.iconReviews=(draft.iconReviews||[]).filter(r=>!(r.side===p.side&&r.slot===p.slot&&r.kind===(el.dataset.key==='hero'?'hero':'equipment')));if(el.dataset.key==='equipment')p.equipmentSlots=[];}p[el.dataset.key]=el.value;remember();});}
async function hydrateEvidence(){
 const id=draft.id;
 const missing=draft.imageIds.filter(imageId=>!ocrResults.has(imageId)&&state.images.some(im=>im.id===imageId&&im.recognized));
 if(!missing.length)return;
 const results=await Promise.allSettled(missing.map(async imageId=>({imageId,result:await api('/api/images/'+imageId+'/recognition')})));
 let changed=false;
 for(const entry of results){if(entry.status==='fulfilled'&&entry.value.result){ocrResults.set(entry.value.imageId,entry.value.result);changed=true;}else if(entry.status==='rejected')toast('部分历史识别结果未能加载，可点击本地识别重试',true);}
 if(changed&&currentPage==='editor'&&draft.id===id)renderEvidence();
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
 container.innerHTML=draft.imageIds.map(id=>{const info=state.images.find(im=>im.id===id),r=ocrResults.get(id);return `<div class="evidence-card"><img src="/api/images/${id}" data-preview="${id}" alt="${esc(info?.name||'本局截图')}"><div class="evidence-info"><div class="evidence-name">${esc(info?.name||'截图')}</div><div class="evidence-actions"><button class="button ghost" data-ocr="${id}">${r?'重新识别':'本地识别'}</button><button class="button ghost" data-unlink="${id}">移出本局</button></div><div id="ocr-${id}" class="evidence-status">${r?`${r.kind==='data'?'数据页':r.kind==='score'?'战绩页':'未匹配页面'} · 比分 ${esc(r.scores.left||'?')} : ${esc(r.scores.right||'?')}`:'等待识别或手动录入'}</div>${r?`<div class="evidence-actions"><button class="button secondary" data-apply="${id}" ${r.kind==='unknown'?'disabled':''}>填入空白字段</button>${r.visuals?.length?`<button class="button secondary" data-icon-review="${id}">图标核对</button>`:''}</div>${evidenceCorrectionForm(id,r)}<details><summary class="helper" style="margin-top:9px;cursor:pointer">原始文字与限制</summary><div class="evidence-warnings">${r.warnings.map(esc).join('<br>')}</div><div class="raw-text">${r.tokens.map(t=>esc(t.text)).join(' · ')}</div></details>`:''}</div></div>`;}).join('')+`<label class="mini-upload">＋ 添加本局截图<small>战绩页 / 数据页 · 支持多选</small><input id="image-file" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden></label>`;
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
 const buttons=[$('#save-draft'),$('#confirm-match')];buttons.forEach(b=>b.disabled=true);
 try{draft=await api('/api/matches','POST',{...draft,status});dirty=false;localStorage.removeItem('training-unsaved');await refresh();editor();toast(status==='confirmed'?'已确认入库，训练统计已更新':status==='archived'?'已归档，记录与截图仍保留':'草稿已保存');}
 catch(e){toast(e.message,true);}finally{buttons.forEach(b=>b.disabled=false);}
}
function rosterPage(){
 $('#content').innerHTML=heading('TEAM ROSTER','建立自己的训练名单','使用稳定的队员身份关联比赛，昵称修改后仍能保留历史记录。')+`<section class="panel"><div class="panel-header"><h2>战队与队员</h2><span class="tag gray">${state.settings.roster.length} 位队员</span></div><div class="roster-form"><label class="field" style="max-width:380px;margin-bottom:25px">战队名称<input id="team-name" value="${esc(state.settings.teamName)}" maxlength="50"></label><div class="roster-grid">${state.settings.roster.map(p=>`<div class="roster-entry"><span class="initial">${esc(p.name[0])}</span><input class="control" data-roster="${esc(p.id)}" aria-label="队员昵称" value="${esc(p.name)}" maxlength="50"></div>`).join('')}</div><div class="roster-add"><input class="control" id="new-player" placeholder="添加队员昵称" maxlength="50"><button class="button secondary" id="add-player">＋ 添加队员</button></div><p class="helper">队员可以是首发或替补，每局单独确认实际出场五人。现有队员保留身份，支持修改昵称。</p><button class="button" id="save-roster">保存战队设置</button></div></section>`;
 const collect=()=>({...state.settings,teamName:$('#team-name').value.trim(),roster:state.settings.roster.map(p=>({...p,name:document.querySelector(`[data-roster="${CSS.escape(p.id)}"]`).value.trim()}))});
 const save=async(add=false)=>{try{const s=collect();if(add){const name=$('#new-player').value.trim();if(!name)throw Error('请填写新队员昵称');s.roster.push({id:uid(),name});}await api('/api/settings','PUT',s);await refresh();rosterPage();toast('战队名单已保存');}catch(e){toast(e.message,true);}};
 $('#add-player').onclick=()=>save(true);$('#save-roster').onclick=()=>save();$('#new-player').onkeydown=e=>{if(e.key==='Enter')save(true);};
}
async function route(){
 const hash=location.hash.slice(1)||'overview';
 if(dirty&&currentPage==='editor'&&hash!==`edit/${draft.id}`){if(!confirm('当前比赛有未保存修改。离开前建议保存草稿。仍要离开？')){history.replaceState(null,'','#edit/'+draft.id);return;}dirty=false;}
 if(busy){toast('正在处理截图，请完成后再切换');history.replaceState(null,'','#edit/'+draft.id);return;}
 const page=hash.startsWith('edit/')||hash==='new'?'editor':hash;
 currentPage=page;document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===(page==='editor'?'matches':page)));
 $('#breadcrumb').textContent='工作空间 / '+({overview:'训练概览',matches:'比赛档案',analysis:'英雄与队员',roster:'战队名单',editor:'比赛校对'}[page]||'训练概览');
 if(page==='editor'){
  const id=hash.split('/')[1];const existing=state.matches.find(m=>m.id===id);
  if(hash==='new'){
   let buffered;try{buffered=JSON.parse(localStorage.getItem('training-unsaved'));}catch{}
   draft=buffered&&confirm('发现一条尚未保存的草稿，继续填写它？')?buffered:blankMatch();
   history.replaceState(null,'','#edit/'+draft.id);
  }else if(existing)draft=structuredClone(existing);
  else if(!draft||draft.id!==id){let buffered;try{buffered=JSON.parse(localStorage.getItem('training-unsaved'));}catch{}if(buffered?.id===id)draft=buffered;else{toast('没有找到该比赛，已返回档案',true);location.hash='matches';return;}}
  editor();
 }else if(page==='matches')matchesPage();else if(page==='analysis')await analysisPage();else if(page==='roster')rosterPage();else overview();
 window.scrollTo(0,0);
}
$('#close-dialog').onclick=()=>$('#image-dialog').close();
$('#backup').onclick=()=>{const a=document.createElement('a');a.href='/api/backup';a.download=`训练室备份-${localDate()}.json`;a.click();};
$('#restore').onclick=()=>$('#backup-file').click();
$('#mobile-backup').onclick=()=>$('#backup').click();
$('#mobile-restore').onclick=()=>$('#restore').click();
$('#backup-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>120*1024*1024)throw Error('备份大于 120 MB，请联系开发者处理');const data=JSON.parse(await file.text());if(!confirm('把备份中的记录合并到本机？相同 ID 的比赛会保留本机版本，不覆盖。'))return;const result=await api('/api/restore','POST',data);await refresh();await route();toast(`恢复完成：新增 ${result.added} 局，跳过 ${result.skipped} 条已有记录`);}catch(error){toast(error.message,true);}finally{e.target.value='';}};
window.addEventListener('hashchange',()=>route().catch(e=>toast(e.message,true)));
window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
$('#content').innerHTML='<div class="loading">正在打开本机训练空间…</div>';
try{await refresh();await route();}catch(e){$('#content').innerHTML=`<div class="notice">工作台未能连接本地服务：${esc(e.message)}。请确认启动窗口仍在运行。</div>`;}
