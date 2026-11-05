import {kplTeams,teamPresetSource,teamPresetLabel,lanes} from '/assets/team-presets.js?v=1';
import {bpEditorHtml,bindBpEditor} from '/assets/bp-editor.js?v=4';
import {disposeAnalysisVisuals,mountPerformanceExplorer,comparisonVisual,mountEconomyTimeline,mountEntityTrend,processMatrix} from '/assets/analysis-visuals.js?v=2';
import {finite as metricNumber} from '/assets/analysis-math.mjs?v=1';
import {renderWorkbench,deactivateWorkbench,allowWorkbenchNavigation} from '/assets/app.js?v=unified-13';
import {renderPrepare,renderDatasets} from '/assets/pipeline-page.js?v=5';
import {renderHome} from '/assets/home-page.js?v=11';
import {renderCapture} from '/assets/capture-page.js?v=7';
import {renderOpponent,renderBp,renderCombos,renderFeatured,renderRecords} from '/assets/insight-pages.js?v=6';
import {renderPanorama,disposePanorama} from '/assets/panorama-page.js?v=16';
const $ = (q, root = document) => root.querySelector(q);
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n = (v, digits = 1) => metricNumber(v) === null ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: digits});
const names = {referenceRows:'参照行数',referencePlayers:'参照人数',percentile:'分位',p50:'中位水平',p75:'较高水平',p90:'高水平',p10:'低水平',recentMean:'近五局均值',recentN:'近期有效场数',iqr:'四分位距',change:'近期 − 全期',heroes:'英雄数',topHero:'最多使用',topShare:'最高使用占比（%）',hhi:'英雄集中度',effectiveHeroes:'有效英雄数',entropy:'英雄池熵',shareGap:'输出占比 − 经济占比（pp）',a:'成员 A',b:'成员 B',cooccurrence:'共现率（%）',expectedRate:'独立基线（%）',perspective:'观察方向',gold5:'5 分钟经济差',gold8:'8 分钟经济差',gold10:'10 分钟经济差',gold15:'15 分钟经济差',observedEnd:'观测结束（分）',startMinute:'起点（分）',endMinute:'终点（分）',goldChange:'经济差变化',session:'训练分组',losses:'负场',group:'分组',metric:'指标',unit:'单位',n:'有效行',matches:'比赛数',missing:'缺失行',mean:'均值',median:'中位数',std:'标准差',min:'最小值',q25:'下四分位',q75:'上四分位',max:'最大值',x:'指标 X',y:'指标 Y',pearson:'线性相关',spearman:'秩相关',note:'说明',date:'比赛日期',matchKey:'比赛记录',value:'逐局均值',rolling:'近 5 局均值',deviation:'稳健偏差',flag:'标记',label:'选手',hero:'英雄',position:'分路',opponent:'对手',result:'胜负',camp:'阵营',source:'来源',partial:'部分记录',bound:'身份绑定',kills:'击杀',deaths:'死亡',assists:'助攻',gold:'经济',damage:'输出',taken:'承伤',participation:'参团率',rating:'评分',kda:'KDA',gpm:'分均经济',dpm:'分均输出',tpm:'分均承伤',goldShare:'经济占比',damageShare:'输出占比',takenShare:'承伤占比',cluster:'分组',pc1:'主成分 1 载荷',pc2:'主成分 2 载荷',antecedent:'前项英雄',consequent:'后项英雄',count:'共现场次',support:'支持度',confidence:'置信度',lift:'提升度',comparison:'比较方向',design:'比较设计',nA:'A 组场次',nB:'B 组场次',difference:'均值差',ciLow:'区间下界',ciHigh:'区间上界',p:'差异显著性',effect:'效应大小',target:'目标指标',trainMatches:'训练场数',testMatches:'留出场数',cutoff:'留出起始日',mae:'留出误差',baselineMae:'基线误差',accuracy:'留出准确率',baselineAccuracy:'多数类准确率',brier:'预测误差',baselineBrier:'基线误差',weight:'标准化系数',available:'有效行',complete:'完整记录有效行',key:'字段名',title:'报告标题',coverage:'时间轴覆盖（%）',win:'获胜',diff:'终局经济差',createdAt:'保存时间',method:'分析方法',rows:'行数',version:'版本',cs:'补刀',jungleGold:'野怪经济',control:'控制效果',healing:'治疗量',towerDamage:'对塔伤害',damageConversion:'伤害转化比',takenPerDeath:'每死承伤',duration:'时长',own:'本队',enemy:'对手',ownRate:'资源控制率',winRate:'胜率',wins:'胜场',decided:'有胜负',picks:'出场',fullPicks:'完整终局',games:'场数',fullRows:'完整行',partialRows:'部分行',goldDiff:'经济差',excluded:'折叠记录',retained:'保留记录'};
const resultNames = {win:'胜',loss:'负',unknown:'待确认',draw:'平'};
const sourceNames = {db:'确认记录',bundle:'数据包',sheet:'表格',capture:'截图候选'};
const paths = {
 overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 players:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2"/>',
 team:'<path d="M12 3 3 7v6c0 5 9 8 9 8s9-3 9-8V7zM8 12l3 3 5-6"/>',
 heroes:'<path d="m12 3 8 5-3 12H7L4 8zM4 8l8 5 8-5M12 13v8"/>',
 matches:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
 lab:'<path d="M9 3h6M10 3v7L4 20h16l-6-10V3M8 14h8"/>',
 reports:'<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6"/>',
 sources:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 warning:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16v1"/>',
 chart:'<path d="M4 3v17h17M8 15l4-5 4 3 5-8"/>',
 download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.chart}</svg>`;
const nav = [
 ['首页', [['overview','首页']]],
 ['比赛', [['matches','比赛档案'],['featured','精选对局'],['records','训练纪录'],['desk','对局工作区'],['new','手工录入']]],
 ['战队', [['team','团队复盘'],['stats','数据看板'],['training','训练跟踪'],['roster','战队名单'],['topics/tempo','前期与优势转化'],['topics/swing_windows','经济转折'],['topics/session_summary','训练组汇总'],['reports','分析报告']]],
 ['选手', [['players','选手表现'],['identity','身份绑定'],['topics/player_form','近期状态'],['topics/player_pairs','双人搭档'],['topics/resource_efficiency','资源与产出']]],
 ['英雄', [['heroes','英雄与阵容'],['combos','英雄组合'],['topics/hero_benchmark','选手英雄参照'],['topics/hero_pool','英雄池'],['topics/hero_combos','阵容关联']]],
 ['BP', [['bp','BP 分析']]],
 ['对比', [['compare/player','选手对比'],['compare/hero','英雄对比']]],
 ['数据', [['capture','采集一局'],['channels','采集通道'],['import','批量导入'],['screenshots','截图采集'],['recordings','录屏采集'],['replays','回放文件'],['datasets','数据集'],['clean','数据清洗'],['sources','字段与来源'],['lab','统计实验'],['models','模型实验']]],
];
const navDescriptions = {
 overview:'从哪开始、待办和数据状态',
 capture:'表格、截图、录屏、回放挂到同一局',
 channels:'进行中的采集通道与审核',
 import:'上传 CSV/XLSX，按工作表批量落盘',
 screenshots:'分页截图识别、分组和校对',
 recordings:'录屏时间轴、记分板和关键帧',
 replays:'.abc / .ope 十人名单与评分',
 matches:'按日期、对手和赛果找比赛',
 featured:'领先被翻、落后逆转、经济接近与经济反复',
 records:'时长、比分、经济差和波动纪录',
 desk:'十人明细、字段详情和过程证据',
 new:'手工录入或重新校对一局',
 players:'近期状态、稳定性、英雄池和同位置参照',
 analysis:'按功能分类查看全部页面',
 'compare/player':'两名选手的表现、样本与指标差异',
 'compare/hero':'两个英雄的出场、胜率和产出对照',
 compare:'两名选手或两个英雄的指标对照',
 heroes:'英雄表现、阵容搭配与对位',
 team:'经济节奏、资源、BP 和对手档案',
 opponent:'交手记录、对手英雄和时间轴汇总',
 topics:'按选手、英雄、战队直达深入分析',
 'topics/hero_benchmark':'同位置同英雄的样本参照',
 'topics/hero_pool':'英雄出场分布与使用集中度',
 'topics/hero_combos':'完整阵容共现与独立基线',
 'topics/player_form':'近期状态、波动与有效样本',
 'topics/player_pairs':'稳定选手身份下的搭档表现',
 'topics/resource_efficiency':'经济投入、输出与伤害转化',
 'topics/tempo':'5 / 8 / 10 / 15 分钟优势',
 'topics/swing_windows':'真实经济变化与回看时间窗',
 'topics/session_summary':'按训练组汇总比赛和证据',
 bp:'禁用、选用、先后手和对手 BP',
 combos:'英雄组合与双人搭档的共现和基线',
 stats:'总览、队员、英雄、对手和训练闭环',
 training:'数据看板里的训练闭环与重点跟踪',
 lab:'选择数据集和方法运行分析',
 datasets:'清洗快照、数据集和发布',
 clean:'设置规则、逐行修订并生成数据集',
 models:'回归与赛前阵容模型的时间留出验证',
 reports:'保存分析结果、条件和观察',
 roster:'战队与队员身份绑定',
 identity:'把未绑定昵称映射到稳定选手',
 sources:'字段、来源与统计口径',
};
const nativePages=new Set(['channels','channel','screenshots','recordings','replays','roster','new','edit','review','training','stats']);
let workspaceDirty=false;let selectedTopic='hero_pool';let lastRenderedHash='';
function stageFor(page){
 if(page==='topics'){const key='topics/'+(location.hash.split('/')[1]||'hero_pool');return nav.find(s=>s[1].some(v=>v[0]===key))||nav[4];}
 const name={'channel':'数据','capture':'数据','edit':'比赛','review':'比赛','desk':'比赛','match':'比赛','player':'选手','hero':'英雄','opponent':'战队'}[page];
 return nav.find(s=>s[0]===name) || nav.find(s=>s[1].some(v=>v[0].split('/')[0]===page)) || nav[0];
}
function labelFor(page){
 if(page==='topics')return stageFor(page)[1].find(v=>v[0]===location.hash.slice(1))?.[1]||'英雄池';
 if(page==='compare')return location.hash.split('/')[1]==='hero'?'英雄对比':'选手对比';
 if(page==='analysis')return '全部功能';
 const detail={'channel':'采集通道','edit':'比赛校对','review':'单局复盘','desk':'对局工作区','capture':'采集一局','match':'对局详情','player':'选手详情','hero':'英雄详情','opponent':'对手档案'};
 return stageFor(page)[1].find(v=>v[0]===page)?.[1] || detail[page] || '总览';
}
function navItemActive(key, page) {
 if(key.startsWith('topics/'))return key===location.hash.slice(1);
 if(key.startsWith('compare/'))return page==='compare'&&key.split('/')[1]===(location.hash.split('/')[1]==='hero'?'hero':'player');
 return key === page
   || (key === 'channels' && page === 'channel')
   || (key === 'matches' && ['edit', 'review', 'match'].includes(page))
   || (key === 'players' && page === 'player')
   || (key === 'heroes' && page === 'hero')
   || (key === 'team' && page === 'opponent');
}
function updateNavigation(page){
 const stage=stageFor(page);
 $('#navigation').innerHTML=nav.map((s,i)=>{
   const active=s===stage;
   const first=s[1][0][0];
   const menu=s[1].length>1?`<div class="nav-menu" role="menu">${s[1].map(([key,label])=>`<a href="#${key}" class="nav-menu-link ${navItemActive(key,page)?'active':''}" role="menuitem"><span>${label}</span><small>${navDescriptions[key]||''}</small></a>`).join('')}</div>`:'';
   return `<div class="nav-group${active?' active':''}"><a href="#${first}" class="nav-item${active?' active':''}" data-stage="${i}">${s[0]}</a>${menu?`<button class="nav-menu-toggle" type="button" aria-expanded="false" aria-label="展开${s[0]}页面"><i class="nav-caret" aria-hidden="true"></i></button>`:''}${menu}</div>`;
 }).join('');
 const sub=$('#subnavigation');
 const items=stage[1];
 sub.hidden=items.length<2;
 sub.innerHTML=items.length<2?'':items.map(([key,label])=>`<a href="#${key}" class="${navItemActive(key,page)?'active':''}">${label}</a>`).join('');
 if(window.innerWidth<=1100){const active=$('#navigation .nav-group.active');if(active)$('#navigation').scrollLeft=Math.max(0,active.offsetLeft-$('#navigation').offsetLeft-$('#navigation').clientWidth/2+active.clientWidth/2);}
}
let workspace, preview, currentResult = null, currentSpec = null, generation = 0, analysisSerial = 0;
let listTab = 'players', teamTab = 'process';
const filters = {from:'',to:'',hero:'',player:'',opponent:'',version:'',sources:['db','bundle'],includePartial:false};
let datasetName = 'records', selectedMethod = 'describe', selectedMetrics = ['gold','damage','participation'];

async function api(url, value) {
 const response = await fetch(url, value === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
 const result = await response.json();
 if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '请求失败');
 return result;
}
let toastTimer;
function toast(message, error = false) {const el = $('#toast');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?6500:2800);}
function pageName(){return (location.hash.slice(1).split('/')[0] || 'overview');}
function heading(title, subtitle, action = '') {return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ''}</div>`;}
function panel(title, subtitle, body, action = '') {return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ''}</div>${action}</div><div class="panel-body">${body}</div></section>`;}
function notice(message){return `<div class="notice">${icon('warning')}<span>${message}</span></div>`;}
function pill(value, type = '') {return `<span class="pill ${type}">${esc(value)}</span>`;}
function empty(title, description, link = '#channels', label = '打开采集通道') {return `<div class="empty-state"><strong>${esc(title)}</strong>${esc(description)}${link ? `<br><a href="${esc(link)}">${esc(label)} →</a>` : ''}</div>`;}
function valueCell(value, key) {
 if (value === null || value === undefined || value === '') return '<span class="muted">—</span>';
 if (key === 'result') return pill(resultNames[value] || value,value==='win'?'':value==='loss'?'amber':'neutral');
 if (key === 'source') return pill(sourceNames[value] || value,'neutral');
 if (key === 'partial') return value ? pill('部分记录','amber') : pill('终局');
 if (key === 'bound') return value ? pill('已绑定') : pill('未绑定','neutral');
 if (key === 'matchKey') return `<button class="text-link" data-match="${esc(value)}" title="${esc(value)}">查看记录</button>`;
 if (typeof value === 'boolean') return value?'是':'否';
 if (typeof value === 'number') return `<span class="num">${n(value, ['p','pearson','spearman','support','confidence','lift','effect','brier','baselineBrier','weight'].includes(key)?4:2)}</span>`;
 if (Array.isArray(value)) return esc(value.map(v=>typeof v==='object'?v.label || v.hero || v.name || '':v).join(' / '));
 if (typeof value === 'object') return esc(JSON.stringify(value));
 return esc(value);
}
function table(rows, columns, options = {}) {
 if (!rows?.length) return empty(options.emptyTitle || '当前没有符合条件的记录',options.emptyText || '调整筛选，或导入相应字段后再查看。',options.link===undefined?'':options.link);
 const limit = options.limit || 200;
 return `<div class="table-scroll"><table class="data-table"><thead><tr>${columns.map(k=>`<th>${esc(names[k] || k)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,limit).map(r=>`<tr${options.rowKey?` class="clickable" data-match="${esc(r[options.rowKey])}"`:''}>${columns.map(k=>`<td${k==='label'||k==='hero'?' class="main-cell"':''}>${valueCell(r[k],k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${rows.length>limit?`<p class="note" style="padding:0 18px">当前显示前 ${limit} 行，共 ${rows.length} 行。导出 CSV 可查看完整结果。</p>`:''}`;
}
function metricStrip(cells) {return `<div class="metric-strip">${cells.map(c=>`<div class="metric-cell"><div class="metric-name">${c[0]}${icon(c[3] || 'chart')}</div><div class="metric-value">${c[1]}${c[4]?`<small>${c[4]}</small>`:''}</div><div class="metric-note">${c[2]}</div></div>`).join('')}</div>`;}
function coverage(rows, total) {return rows.map(r=>`<div class="coverage-row"><span>${esc(r.label)}</span><div class="bar"><i style="width:${total?Math.min(100,r.available/total*100):0}%"></i></div><span>${r.available}/${total}</span></div>`).join('');}
function chart(points, kind='line', xLabel='比赛顺序', yLabel='指标值', legend='逐局均值') {
 const good = points.filter(p=>metricNumber(p.x)!==null&&metricNumber(p.y)!==null);
 if (!good.length) return '';
 const width=760,height=235,left=64,right=24,top=18,bottom=48;
 let xmin=Math.min(...good.map(p=>Number(p.x))),xmax=Math.max(...good.map(p=>Number(p.x)));
 let ymin=Math.min(...good.map(p=>Number(p.y))),ymax=Math.max(...good.map(p=>Number(p.y)));
 if(xmin===xmax){xmin-=1;xmax+=1;}if(ymin===ymax){ymin-=1;ymax+=1;}
 const pad=(ymax-ymin)*.12;ymin-=pad;ymax+=pad;
 const xx=x=>left+(Number(x)-xmin)/(xmax-xmin)*(width-left-right),yy=y=>height-bottom-(Number(y)-ymin)/(ymax-ymin)*(height-top-bottom);
 let grid='';for(let i=0;i<=4;i++){const y=ymin+(ymax-ymin)*i/4;grid+=`<line x1="${left}" x2="${width-right}" y1="${yy(y)}" y2="${yy(y)}" stroke="#edf0eb"/><text x="${left-10}" y="${yy(y)+3}" text-anchor="end" fill="#8c978d" font-size="9">${n(y,0)}</text>`;}
 const path = kind==='line'&&good.length>1 ? `<path d="${good.map((p,i)=>`${i?'L':'M'}${xx(p.x)} ${yy(p.y)}`).join(' ')}" fill="none" stroke="#3a7958" stroke-width="2"/>` : '';
 return `<div class="chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(xLabel)}与${esc(yLabel)}">${grid}${path}${good.map(p=>`<circle cx="${xx(p.x)}" cy="${yy(p.y)}" r="${kind==='line'?3:4}" fill="#4c8463" opacity=".7"><title>${esc(p.label || '')} ${esc(p.matchKey || '')}：${n(p.y,2)}</title></circle>`).join('')}<text x="${left}" y="${height-26}" fill="#8c978d" font-size="9">${n(xmin,0)}</text><text x="${width-right}" y="${height-26}" text-anchor="end" fill="#8c978d" font-size="9">${n(xmax,0)}</text><text x="${width/2}" y="${height-6}" text-anchor="middle" fill="#778577" font-size="10">${esc(xLabel)}</text><text transform="translate(12 ${height/2}) rotate(-90)" text-anchor="middle" fill="#778577" font-size="10">${esc(yLabel)}</text></svg><div class="chart-caption"><span>● ${esc(legend)}</span><span>来源：当前筛选数据 · ${good.length} 个有效点</span></div></div>`;
}
function histogram(bins,metric){const w=760,h=210,l=60,r=25,t=16,b=47,max=Math.max(...bins.map(x=>x.count),1),space=(w-l-r)/bins.length;let marks='';for(let i=0;i<4;i++){const v=max*i/3,y=h-b-v/max*(h-t-b);marks+=`<line x1="${l}" x2="${w-r}" y1="${y}" y2="${y}" stroke="#edf0eb"/><text x="${l-10}" y="${y+3}" text-anchor="end" font-size="9" fill="#8c978d">${n(v,0)}</text>`;}return `<div class="chart-wrap"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(metric.label)}分布">${marks}${bins.map((v,i)=>`<rect x="${l+i*space+2}" y="${h-b-v.count/max*(h-t-b)}" width="${space-4}" height="${v.count/max*(h-t-b)}" fill="#67917a"><title>${n(v.low)}–${n(v.high)}：${v.count} 行</title></rect>`).join('')}<text x="${l}" y="${h-26}" font-size="9" fill="#8c978d">${n(bins[0].low,0)}</text><text x="${w-r}" y="${h-26}" text-anchor="end" font-size="9" fill="#8c978d">${n(bins[bins.length-1].high,0)}</text><text x="${w/2}" y="${h-6}" text-anchor="middle" font-size="10" fill="#778577">${esc(metric.label)}（${esc(metric.unit)}）</text><text transform="translate(13 ${h/2}) rotate(-90)" text-anchor="middle" font-size="10" fill="#778577">记录行数</text></svg><div class="chart-caption"><span>${esc(metric.label)} · 选手单局分布</span><span>来源：当前筛选数据 · ${bins.reduce((a,b)=>a+b.count,0)} 个有效值</span></div></div>`;}
function filtersHtml() {
 const options=workspace.filters;
 return `<section class="panel filterbar"><label class="field">开始日期<input type="date" id="filter-from" value="${esc(filters.from)}"></label><label class="field">结束日期<input type="date" id="filter-to" value="${esc(filters.to)}"></label><label class="field">选手<select id="filter-player"><option value="">全部选手</option>${options.players.map(p=>`<option value="${esc(p.key)}"${p.key===filters.player?' selected':''}>${esc(p.label)}</option>`).join('')}</select></label><label class="field">英雄<select id="filter-hero"><option value="">全部英雄</option>${options.heroes.map(h=>`<option${h===filters.hero?' selected':''}>${esc(h)}</option>`).join('')}</select></label><label class="field">对手<input id="filter-opponent" value="${esc(filters.opponent)}" placeholder="对手名称"></label><label class="check"><input id="filter-partial" type="checkbox"${filters.includePartial?' checked':''}>含部分记录</label><label class="check"><input id="filter-sheet" type="checkbox"${filters.sources.includes('sheet')?' checked':''}>含表格导入</label><button class="button" id="apply-filters">应用筛选</button><button class="text-link" id="reset-filters">重置</button></section>`;
}
function readFilters(){for(const k of ['from','to','player','hero','opponent']){const el=$('#filter-'+k);if(el)filters[k]=el.value;}if($('#filter-partial'))filters.includePartial=$('#filter-partial').checked;filters.sources=$('#filter-sheet')?.checked?['db','bundle','sheet']:['db','bundle'];}
function query(){const p=new URLSearchParams();for(const k of ['from','to','player','hero','opponent','version'])if(filters[k])p.set(k,filters[k]);p.set('source',filters.sources.join(','));if(filters.includePartial)p.set('includePartial','1');return '?'+p.toString();}
async function getPreview(){return api('/api/studio/dataset',{dataset:datasetName,filters,deduplicate:true});}

let deskData=null, deskSelected=null, deskMetric='gold', deskRow=0, deskSource='records';
let deskColumns=['kills','deaths','assists','gold','damage','taken','participation','rating'];
const metricInfo = key => workspace.metrics.find(m=>m.key===key) || {label:names[key]||key,unit:''};
async function researchDesk(token){
 deskData=await api('/api/studio/dataset',{dataset:deskSource,filters:{sources:['db','bundle','sheet'],includePartial:true},deduplicate:true});
 if(token!==generation)return;
 renderDesk();
}
function deskGroups(){const groups=new Map();for(const r of deskData.rows){if(!groups.has(r.matchKey))groups.set(r.matchKey,[]);groups.get(r.matchKey).push(r);}return groups;}
function renderDesk(){
 const priorX=$('.sheet-scroll')?.scrollLeft||0,priorY=$('.match-sheet')?.scrollTop||0;
 const groups=deskGroups();if(!groups.has(deskSelected)){deskSelected=groups.keys().next().value;deskRow=0;}
 const rows=groups.get(deskSelected)||[],record=workspace.recent.find(m=>m.key===deskSelected),current=rows[Math.min(deskRow,rows.length-1)];
 const title=record?.opponent?'vs '+record.opponent:record?.title || (deskSource==='screenshots'?'赛后截图组':'对局记录');
 $('#content').innerHTML=`<div class="desk-tools"><div class="desk-view-name">对局工作区</div><div class="desk-source-select"><label for="desk-source">数据</label><select id="desk-source"><option value="records"${deskSource==='records'?' selected':''}>比赛记录与表格</option><option value="screenshots"${deskSource==='screenshots'?' selected':''}>截图候选</option></select></div><span class="desk-count">${deskData.matches} 组内容 / ${deskData.total} 行</span><span class="desk-tool-spacer"></span><button class="desk-command" id="desk-export">导出当前表</button><button class="desk-command accented" id="desk-analyze">统计 / 建模 ↗</button></div>
 <div class="desk-grid"><section class="match-index"><div class="index-header"><span>对局索引</span><span>${groups.size}</span></div><div class="index-list">${[...groups].map(([key,members],i)=>{const m=workspace.recent.find(x=>x.key===key),valid=members.reduce((v,r)=>v+deskColumns.filter(k=>r[k]!==null&&r[k]!==undefined).length,0),total=members.length*deskColumns.length;return `<button class="index-match ${key===deskSelected?'selected':''}" data-desk-match="${esc(key)}"><div class="index-match-top"><span>${esc(members[0].date || '日期未记录')}</span><span class="index-number">${String(i+1).padStart(2,'0')}</span></div><strong>${esc(m?.opponent?'vs '+m.opponent:m?.title || '截图组 '+String(i+1).padStart(2,'0'))}</strong><div class="index-match-meta"><span>${members.length} 人 · ${n(valid/Math.max(1,total)*100,0)}% 字段</span><span>${m?.duration?Math.floor(m.duration/60)+':'+String(m.duration%60).padStart(2,'0'):'时长 —'}</span></div><div class="index-meter"><i style="width:${valid/Math.max(1,total)*100}%"></i></div></button>`;}).join('')}</div><div class="index-foot">${deskData.truncated?'当前索引显示前 1000 行。<br>':''}${deskSource==='screenshots'?'候选按同局截图组排列。':'内容相同的记录已折叠。'}<a href="#sources">来源与关联 ↗</a></div></section>
 <section class="match-sheet"><div class="sheet-title"><div><span class="sheet-kicker">${deskSource==='screenshots'?'SCREENSHOT':'MATCH'} / ${esc(deskSelected?deskSelected.slice(-12):'—')}</span><h1>${esc(title)}</h1></div><div class="sheet-context"><span>${esc(rows[0]?.date || '日期 —')}</span><span>${deskSource==='screenshots'?'截图候选':(resultNames[record?.result]||'胜负待确认')}</span>${deskSelected?`<button class="desk-command" data-match="${esc(deskSelected)}">原始记录 ↗</button>`:''}</div></div>
 <div class="sheet-tabbar"><span class="sheet-tab selected">十人明细</span><span class="sheet-tab-hint">点击数值查看该字段</span><details class="column-picker"><summary>显示列 ▾</summary><div>${workspace.metrics.map(m=>`<label><input type="checkbox" data-desk-column="${m.key}"${deskColumns.includes(m.key)?' checked':''}>${esc(m.label)}</label>`).join('')}</div></details></div>
 <div class="sheet-scroll">${rows.length?`<table class="sheet-table"><thead><tr><th class="rownum">#</th><th class="player-col">选手 / 英雄</th>${deskColumns.map(k=>`<th class="${k===deskMetric?'selected-column':''}"><button data-desk-metric="${k}">${esc(metricInfo(k).label)}</button><small>${esc(metricInfo(k).unit)}</small></th>`).join('')}</tr></thead><tbody>${rows.map((r,i)=>`<tr class="${i===deskRow?'selected-row':''}"><td class="rownum">${String(i+1).padStart(2,'0')}</td><td class="player-col"><div class="player-identity"><i class="camp-marker ${['blue','left'].includes(r.camp)?'camp-a':'camp-b'}"></i><div><strong>${esc(r.hero || '英雄未识别')}</strong><small title="${esc(r.label)}">${esc(r.label)}</small></div></div></td>${deskColumns.map(k=>`<td tabindex="0" aria-label="${esc(r.hero||r.label)} ${esc(metricInfo(k).label)} ${n(r[k])}" data-desk-cell="${i}:${k}" class="datum ${i===deskRow&&k===deskMetric?'selected-cell':''} ${r[k]===null||r[k]===undefined?'missing':''}">${n(r[k],k==='rating'||k==='kda'?1:0)}</td>`).join('')}</tr>`).join('')}</tbody></table>`:empty('没有可读取的记录','先从采集通道保存比赛记录。','#channels','打开采集通道')}</div>
 <div class="sheet-legend"><span><i class="camp-marker camp-a"></i>来源阵营 A</span><span><i class="camp-marker camp-b"></i>来源阵营 B</span><span>左右 / 蓝红沿用来源标签；本队身份另行确认。</span></div>
 <div class="desk-bottom"><div class="plot-heading"><h2>${esc(metricInfo(deskMetric).label)} · 本局十人</h2><span>${esc(metricInfo(deskMetric).unit)}</span></div><div id="desk-distribution">${deskBars(rows)}</div><div id="desk-timeline"></div></div></section>
 <aside class="field-inspector" id="field-inspector">${inspector(current,rows)}</aside></div><div class="desk-statusbar"><span>${deskSource==='screenshots'?'截图候选':'比赛数据'} · ${rows.length} 行 × ${deskColumns.length} 指标</span><span>${deskData.duplicates.length} 份相同内容已折叠</span><span>${current?esc(current.hero || current.label)+' / '+esc(metricInfo(deskMetric).label):'未选择单元格'}</span></div>`;
 $('#desk-source').onchange=()=>{deskSource=$('#desk-source').value;deskSelected=null;render();};
 $('#desk-analyze').onclick=()=>{datasetName=deskSource;filters.includePartial=true;location.hash='lab';};
 $('#desk-export').onclick=()=>exportRows(rows,['label','hero','camp',...deskColumns],'当前对局.csv');
 document.querySelectorAll('[data-desk-match]').forEach(el=>el.onclick=()=>{deskSelected=el.dataset.deskMatch;deskRow=0;renderDesk();});
 document.querySelectorAll('[data-desk-cell]').forEach(el=>el.onclick=()=>{const [i,k]=el.dataset.deskCell.split(':');deskRow=Number(i);deskMetric=k;renderDesk();});
 document.querySelectorAll('[data-desk-metric]').forEach(el=>el.onclick=()=>{deskMetric=el.dataset.deskMetric;renderDesk();});
 document.querySelectorAll('[data-desk-column]').forEach(el=>el.onchange=()=>{if(el.checked)deskColumns.push(el.dataset.deskColumn);else deskColumns=deskColumns.filter(k=>k!==el.dataset.deskColumn);if(!deskColumns.length)deskColumns=['gold'];if(!deskColumns.includes(deskMetric))deskMetric=deskColumns[0];renderDesk();});
 document.querySelectorAll('[data-desk-field]').forEach(el=>el.onclick=()=>{deskMetric=el.dataset.deskField;renderDesk();});if($('.sheet-scroll'))$('.sheet-scroll').scrollLeft=priorX;if($('.match-sheet'))$('.match-sheet').scrollTop=priorY;if(deskSelected&&deskSource==='records')loadDeskTimeline(deskSelected);
}
function inspector(current,rows){
 if(!current)return '<div class="inspector-title">字段详情</div>';
 const metric=metricInfo(deskMetric),all=deskData.rows.filter(r=>r.hero===current.hero&&r[deskMetric]!==null&&r[deskMetric]!==undefined),values=all.map(r=>r[deskMetric]).sort((a,b)=>a-b),median=values.length?(values[Math.floor((values.length-1)/2)]+values[Math.floor(values.length/2)])/2:null;
 return `<div class="inspector-title">字段详情<span>行 ${String(deskRow+1).padStart(2,'0')}</span></div><div class="inspector-body"><div class="field-code">${esc(deskMetric)}</div><h2>${esc(metric.label)}</h2><div class="inspected-value">${n(current[deskMetric],2)}<small>${esc(metric.unit)}</small></div><div class="inspected-subject"><strong>${esc(current.hero || '英雄未识别')}</strong><span>${esc(current.label)}</span></div><dl class="field-facts"><dt>比赛日期</dt><dd>${esc(current.date || '—')}</dd><dt>来源</dt><dd>${esc(sourceNames[current.source]||current.source)}</dd><dt>身份</dt><dd>${current.bound?'已绑定名单':'未绑定名单'}</dd><dt>记录</dt><dd>${current.partial?'部分字段':'终局记录'}</dd></dl><div class="inspector-section"><h3>同英雄参照</h3><p>当前数据集中 ${values.length} 行有效值</p><div class="reference-line"><span>中位数</span><b>${n(median,2)}</b></div><div class="reference-line"><span>当前值 − 中位数</span><b>${current[deskMetric]!==null&&current[deskMetric]!==undefined&&median!==null?n(current[deskMetric]-median,2):'—'}</b></div><p>不同对局、分路和版本未做控制，此处仅列出数值参照。</p></div><div class="inspector-section"><h3>字段完整度</h3><div class="field-map">${workspace.metrics.map(m=>`<button data-desk-field="${m.key}" class="${current[m.key]!==null&&current[m.key]!==undefined?'present':''} ${m.key===deskMetric?'inspecting':''}" title="${esc(m.label)}：${n(current[m.key])}">${esc(m.label)}</button>`).join('')}</div><p>深色：有值　空白：缺失</p></div></div>`;
}
function deskBars(rows){
 const valid=rows.filter(r=>r[deskMetric]!==null&&r[deskMetric]!==undefined);if(!valid.length)return '<div class="plot-unavailable">本局未提供该字段。</div>';
 const max=Math.max(...valid.map(r=>r[deskMetric]),1),w=860,h=190,left=66,right=24,top=16,bottom=35,space=(w-left-right)/rows.length;
 return `<svg class="desk-bars" viewBox="0 0 ${w} ${h}" role="img" aria-label="本局十人${esc(metricInfo(deskMetric).label)}"><line x1="${left}" x2="${w-right}" y1="${h-bottom}" y2="${h-bottom}" stroke="#d1d3cd"/>${rows.map((r,i)=>{const v=r[deskMetric],height=v===null||v===undefined?0:v/max*(h-top-bottom-15),x=left+i*space+space*.23;return `<rect x="${x}" y="${h-bottom-height}" width="${space*.54}" height="${height}" fill="${i===deskRow?'#b05a3c':['blue','left'].includes(r.camp)?'#7795aa':'#b28b81'}"/><text x="${x+space*.27}" y="${h-bottom-height-7}" text-anchor="middle" fill="#5b625e" font-size="10">${n(v,0)}</text><text x="${x+space*.27}" y="${h-bottom+19}" text-anchor="middle" fill="#6f7670" font-size="10">${esc(r.hero || String(i+1))}</text>`;}).join('')}<text transform="translate(15 ${h/2}) rotate(-90)" text-anchor="middle" fill="#81867d" font-size="10">${esc(metricInfo(deskMetric).unit)}</text></svg>`;
}
async function loadDeskTimeline(key){
 try{const detail=await api('/api/studio/match/'+encodeURIComponent(key));if(deskSelected!==key||pageName()!=='desk'||!$('#desk-timeline'))return;const points=(detail.process?.timeline||[]).filter(p=>p.blueGold!==null&&p.blueGold!==undefined&&p.redGold!==null&&p.redGold!==undefined);if(points.length>1)$('#desk-timeline').innerHTML='<div class="plot-heading secondary"><h2>过程片段 · 蓝红经济差</h2><span>仅显示已有时间范围</span></div>'+chart(points.map(p=>({x:p.gameTime/60,y:p.blueGold-p.redGold})),'line','局内时间（分钟）','经济差（金币）','蓝方 − 红方');}catch(error){toast(error.message,true);}
}
function exportRows(rows,keys,filename){const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"',safe=v=>typeof v==='string'&&/^[=+@\-\t\r]/.test(v)?"'"+v:v;download(new Blob(['\ufeff'+[keys.map(k=>quote(names[k]||metricInfo(k).label)).join(','),...rows.map(r=>keys.map(k=>quote(safe(r[k]))).join(','))].join('\r\n')],{type:'text/csv;charset=utf-8'}),filename);}
function methodCard(m){return `<button class="tool-card" data-method="${m.key}"><div class="tool-type"><span>${esc(m.category)}</span><span>↗</span></div><h3>${esc(m.name)}</h3><p>${esc(m.description)}</p></button>`;}
function matchesTable(rows){return table(rows.map(r=>({date:r.date,title:r.opponent?`vs ${r.opponent}`:r.title || '比赛记录',duration:r.duration?`${Math.floor(r.duration/60)}:${String(Math.round(r.duration%60)).padStart(2,'0')}`:null,source:r.source,result:r.result,partial:!r.complete,matchKey:r.key})),['date','title','duration','source','result','partial','matchKey'],{emptyText:'从采集通道保存比赛后会出现在这里。',link:'#channels'});}
function importPage(token){
 const fields=[['date','日期'],['matchId','比赛 ID'],['matchNo','场次号'],['session','训练分组'],['period','周期'],['opponent','对手'],['team','队伍'],['side','阵营'],['position','分路'],['player','选手'],['playerId','选手 ID'],['hero','英雄'],['time','局内时间'],['frame','帧'],['event','事件'],['skill','技能'],['kills','击杀'],['deaths','死亡'],['assists','助攻'],['kda','KDA'],['gold','经济'],['gpm','分均经济'],['damage','输出'],['dpm','分均输出'],['taken','承伤'],['tpm','分均承伤'],['participation','参团率'],['damageShare','输出占比'],['goldShare','经济占比'],['takenShare','承伤占比'],['rating','评分'],['win','胜负'],['winRate','胜率'],['duration','时长'],['towers','推塔'],['objectives','资源'],['level','等级'],['equipment','装备'],['runes','铭文'],['__ignore__','忽略 / 扩展列']];
 const option=(field,header)=>fields.map(([value,label])=>`<option value="${value}" ${((field||'').startsWith('extra.')?value==='__ignore__':value===field)?'selected':''}>${label}</option>`).join('');
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">IMPORT · 批量导入</span><h1>批量导入</h1><p>上传赛训组已有的 CSV/TSV/XLSX，先校对列映射，再确认落盘；不直接改正式比赛。</p><div class="page-facts"><span>CSV / TSV / XLSX / XLSM</span><span>单文件 ≤ 20 MB</span><span>列映射可改</span></div></div><a class="button" href="#matches">比赛档案</a></div>`
 +`<section class="panel"><div class="panel-head"><div><h2>导入字段与填写要求</h2><p>推荐使用十人逐局明细。可以连续追加多局：每局唯一 ID，双方各五行；不要把汇总行与逐局行混在同一个工作表。</p></div></div><div class="panel-body"><div class="collection-downloads"><a class="button primary" download href="/assets/capture-guide/match-template.csv">下载逐局 CSV 表头</a><a class="button" href="/assets/collection-guide.html?section=table" target="_blank" rel="noopener">完整字段说明与十人示例 ↗</a></div><div class="table-scroll"><table class="data-table"><thead><tr><th>字段</th><th>逐局明细要求</th><th>填写示例</th></tr></thead><tbody><tr><td>对局ID、日期</td><td>同局一致；多局 ID 不同；日期 YYYY-MM-DD</td><td>20261104-A01 · 2026-11-04</td></tr><tr><td>阵营、分路、选手、英雄</td><td>blue/red；每方五分路；一行一人</td><td>blue · 打野 · 自定义昵称 · 镜</td></tr><tr><td>击杀、死亡、助攻、经济、输出、承伤</td><td>未知留空；非负原始数，不加“万”或“k”</td><td>2 · 1 · 5 · 12345</td></tr><tr><td>参团率、评分</td><td>0–100；参团率按百分数填写</td><td>62.5 表示 62.5%</td></tr><tr><td>时长、胜负、对手</td><td>时长用秒，同局一致；胜/负/未知</td><td>900 · 胜 · 对手名称</td></tr></tbody></table></div><details><summary>已有表格 / 汇总表如何导入？</summary><p>支持 CSV/TSV/XLSX/XLSM，首行是表头。列名不同可在下一步映射；不认识的列选“忽略”。每张工作表单独识别粒度。逐局分析至少需要能定位比赛的 ID/日期/场次、选手或英雄，以及需要分析的数值指标。只有胜率/场次等汇总的数据保留为聚合数据，无法还原逐局 BP、阵容和时间线。预览中的粒度、缺失与映射提示必须检查。</p></details></div></section>`
 +`<section class="panel import-panel"><div class="panel-head"><div><h2>选择表格</h2><p>每个工作表会单独落盘，保留原始列名和映射画像。</p></div></div><div class="panel-body"><div class="import-drop"><input id="import-file" type="file" accept=".csv,.tsv,.xlsx,.xlsm" hidden><button class="button secondary" id="import-pick">选择文件</button><span id="import-filename" class="note">还没有选择文件</span><button class="button primary" id="import-upload" disabled>预览映射</button></div><div id="import-status" class="note"></div></div></section><div id="import-preview"></div><div id="import-result"></div><p class="note">导入只新增待分析表格；列名不标准时可在这里改映射，确认后才落盘。正式统计仍需在比赛档案中确认。</p>`;
 const fileInput=$('#import-file'),pick=$('#import-pick'),previewButton=$('#import-upload'),name=$('#import-filename'),status=$('#import-status'),previewBox=$('#import-preview'),result=$('#import-result');
 let selected=null;
 pick.onclick=()=>fileInput.click();
 fileInput.onchange=()=>{selected=fileInput.files?.[0]||null;name.textContent=selected?selected.name:'还没有选择文件';previewButton.disabled=!selected;previewBox.innerHTML='';result.innerHTML='';status.textContent='';};
 const previewHtml=(data,file)=>{
  const sheets=data.sheets||[];
  return `<section class="panel"><div class="panel-head"><div><h2>列映射预览</h2><p>${esc(file.name)} · ${sheets.length} 个工作表；确认后才会落盘。</p></div><button class="button primary" id="import-confirm">确认导入</button></div><div class="panel-body">${sheets.map(sheet=>{const low=(sheet.columns||[]).filter(column=>Number(column.confidence)<0.8);return `<div class="import-preview-sheet"><div class="import-preview-head"><strong>${esc(sheet.name)}</strong><span>${n(sheet.rows,0)} 行</span><small>${esc(sheet.grain||'未识别粒度')}</small></div><div class="import-map"><table class="data-table import-sample"><thead><tr>${(sheet.header||[]).map(header=>`<th>${esc(header)}</th>`).join('')}</tr></thead><tbody>${(sheet.sample||[]).slice(0,3).map(row=>`<tr>${(sheet.header||[]).map((_,index)=>`<td>${esc(row[index]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="import-map-list">${(sheet.columns||[]).map(column=>`<div class="import-map-row"><span>${esc(column.header)}</span><select data-map-sheet="${esc(sheet.name)}" data-map-header="${esc(column.header)}">${option(column.field,column.header)}</select><small>${n(Number(column.confidence)*100,0)}%</small></div>`).join('')}</div>${(sheet.unmappedColumns||[]).length?`<p class="note">未映射列：${esc(sheet.unmappedColumns.slice(0,8).join(' / '))}</p>`:''}${low.length?`<p class="note">${low.length} 列原推断置信度较低；可在上方改成明确字段。</p>`:''}${(sheet.warnings||[]).length?`<p class="note">${esc(sheet.warnings.slice(0,4).join('；'))}</p>`:''}</div>`;}).join('')}</div></section>`;
 };
 const renderResult=data=>{
  const sheets=data.sheets||[];
  result.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>导入结果</h2><p>已落盘到 imports/${esc(data.staged||'')}；刷新分析数据后可在比赛档案和数据集查看。</p></div><span class="pill">${sheets.length} 个工作表</span></div><div class="panel-body"><div class="import-sheets">${sheets.map(sheet=>`<div class="import-sheet"><strong>${esc(sheet.name)}</strong><span>${n(sheet.rows,0)} 行</span><small>${esc(sheet.grain||'未识别粒度')}${sheet.aggregated?' · 聚合表':''}</small>${(sheet.unmappedColumns||[]).length?`<small>未映射：${esc(sheet.unmappedColumns.slice(0,6).join(' / '))}</small>`:''}</div>`).join('')}</div><div class="result-meta">${data.quality?Object.entries(data.quality).map(([key,value])=>`<span>${esc(key)} <strong>${n(value,0)}</strong></span>`).join(''):''}</div>${(data.warnings||[]).length?`<details><summary class="note">查看 ${data.warnings.length} 条导入提示</summary><ul class="match-warnings">${data.warnings.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></details>`:''}<div class="import-actions"><button class="button primary" id="import-reload">刷新分析数据</button><a class="button" href="#matches">查看比赛档案</a><a class="button" href="#datasets">查看数据集</a></div></div></section>`;
  status.textContent='已落盘。点击“刷新分析数据”后读取。';
  $('#import-reload').onclick=async()=>{try{await fetch('/api/analysis/reload',{method:'POST'});toast('分析数据已刷新');}catch(error){toast(error.message,true);}};
 };
 previewButton.onclick=async()=>{
  const file=selected;if(!file)return;previewButton.disabled=true;status.textContent='正在读取并推断表头…';previewBox.innerHTML='';result.innerHTML='';
  try{
   const response=await fetch('/api/studio/import/preview?name='+encodeURIComponent(file.name),{method:'POST',body:file});const data=await response.json();if(!response.ok)throw Error(data.detail||'预览失败');
   if(token!==generation)return;
   previewBox.innerHTML=previewHtml(data,file);status.textContent='校对列映射后导入。';
   $('#import-confirm').onclick=async()=>{const button=$('#import-confirm');button.disabled=true;const mapping={};document.querySelectorAll('[data-map-sheet]').forEach(select=>{(mapping[select.dataset.mapSheet]??={})[select.dataset.mapHeader]=select.value;});try{const commit=await fetch('/api/studio/import/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({previewId:data.previewId,mapping})});const resultData=await commit.json();if(!commit.ok)throw Error(resultData.detail||'导入失败');if(token!==generation)return;renderResult(resultData);}catch(error){status.textContent='导入失败：'+error.message;button.disabled=false;}};
  }catch(error){if(token===generation){status.textContent='预览失败：'+error.message;previewBox.innerHTML=`<section class="panel"><div class="empty-state"><strong>预览失败</strong>${esc(error.message)}</div></section>`;}}
  finally{if(token===generation)previewButton.disabled=!selected;}
 };
}

async function matchesPage(token) {
 const pageSize=24;
 let offset=0,queryText='',items=[],total=0,summary={},requestId=0;
 const team=workspace?.overview?.teamName||'本队';
 const duration=m=>m.duration?`${Math.floor(m.duration/60)}:${String(Math.round(m.duration%60)).padStart(2,'0')}`:'时长未记录';
 const score=m=>{
  const left=m.scores?.left??'—',right=m.scores?.right??'—';
  const ownCamp=m.ownCamp==='blue'?'left':m.ownCamp==='red'?'right':m.ownCamp;
  if(ownCamp==='left')return {own:left,opp:right,ownLabel:team,oppLabel:m.opponent||'对手'};
  if(ownCamp==='right')return {own:right,opp:left,ownLabel:team,oppLabel:m.opponent||'对手'};
  return {own:left,opp:right,ownLabel:'左',oppLabel:'右'};
 };
 const card=m=>{
  const s=score(m),result=resultNames[m.result]||'待确认',tone=m.result==='win'?'win':m.result==='loss'?'loss':m.result==='draw'?'draw':'unknown';
  const tags=[m.complete?'终局':'部分记录',m.hasTimeline?'时间轴':'',m.hasScoreboard?'记分板':'',m.hasPov?'POV':''].filter(Boolean);
  return `<article class="match-card"><div class="match-card-top"><span class="match-date">${esc(m.date||'日期待定')}<small>${esc(m.session||'日常训练')}</small></span><span class="match-result ${tone}">${result}</span></div><div class="match-card-main"><h3>${esc(m.opponent?'vs '+m.opponent:m.title||'未命名比赛')}</h3><div class="match-score"><span>${esc(s.ownLabel)}</span><b>${esc(s.own)}</b><em>:</em><b>${esc(s.opp)}</b><span>${esc(s.oppLabel)}</span></div></div><div class="match-card-meta"><span>${duration(m)}</span><span>${n(m.players,0)} 人</span><span>${esc(sourceNames[m.source]||m.source||'来源待确认')}</span></div><div class="match-card-tags">${tags.map(tag=>`<span>${tag}</span>`).join('')}${m.warnings?`<span class="warn">${m.warnings} 条提示</span>`:''}</div><div class="match-card-actions"><a class="button" href="#match/${esc(m.key)}">查看比赛 ${icon('arrow')}</a></div></article>`;
 };
 const facts=()=>`<div class="page-facts" id="match-facts"><span>${n(total)} 份记录</span><span>${n(summary.wins)} 胜 · ${n(summary.losses)} 负${summary.unknown?` · ${n(summary.unknown)} 待确认`:''}</span><span>${n(summary.complete)} 份终局</span><span>${n(summary.sources)} 种来源</span></div>`;
 const url=(reset)=>'/api/studio/view/matches'+query()+'&limit='+pageSize+'&offset='+(reset?0:offset)+'&q='+encodeURIComponent(queryText);
 const load=async(reset)=>{
  const current=++requestId;
  const data=await api(url(reset));
  if(token!==generation||current!==requestId)return null;
  total=Number(data.total)||0;summary=data.summary||{};
  const incoming=data.matches||[];
  items=reset?incoming:items.concat(incoming);
  offset=items.length;
  return incoming;
 };
 const paint=(incoming,reset)=>{
  const box=$('#match-cards');
  if(reset)box.innerHTML=incoming.length?incoming.map(card).join(''):empty('当前筛选下没有比赛','调整日期、选手、英雄或对手筛选，或者先采集一局。','#channels','打开采集通道');
  else if(incoming.length)box.insertAdjacentHTML('beforeend',incoming.map(card).join(''));
  $('#match-table').innerHTML=matchesTable(items);
  $('#match-list-count').textContent=`${n(total)} 份记录 · 已显示 ${n(items.length)}`;
  $('#match-facts').outerHTML=facts();
  const more=$('#match-load');if(more)more.hidden=items.length>=total;
 };
 const first=await load(true);if(first===null)return;
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">MATCHES · 比赛档案</span><h1>比赛档案</h1><p>保留每份来源记录，逐场查看十人数据与过程证据；未知胜负不会被当成失利。</p>${facts()}</div><div class="heading-actions"><button class="button" data-print>打印 / PDF</button><a class="button" href="#new">手工录入 / 校对</a><a class="button primary" href="#capture">导入比赛 ${icon('arrow')}</a></div></div>`
 +`<details class="page-filter"><summary><span>筛选数据</span><small>按日期、选手、英雄或对手筛选</small></summary>${filtersHtml()}</details>`
 +`<div class="match-toolbar"><span id="match-list-count">${n(total)} 份记录 · 已显示 ${n(items.length)}</span><input class="search-field" id="match-search" placeholder="搜索记录标题、对手或日期" aria-label="搜索比赛"></div>`
 +`<div id="match-cards" class="match-card-grid">${items.length?items.map(card).join(''):empty('还没有比赛记录','先采集一局，或者手工录入一局训练赛。','#channels','打开采集通道')}</div>`
 +`<div class="match-load-more"><button class="button" id="match-load" ${items.length>=total?'hidden':''}>加载更多</button></div>`
 +`<details class="panel raw-fold"><summary>表格视图（当前 ${items.length} 行）</summary><div class="panel-body"><div id="match-table">${matchesTable(items)}</div></div></details>`;
 paint(first,true);
 let timer;
 $('#match-search').oninput=()=>{clearTimeout(timer);timer=setTimeout(async()=>{queryText=$('#match-search').value.trim();offset=0;const incoming=await load(true);if(incoming!==null)paint(incoming,true);},250);};
 $('#match-load').onclick=async()=>{const button=$('#match-load');button.disabled=true;const incoming=await load(false);if(incoming!==null)paint(incoming,false);if(button.isConnected)button.disabled=false;};
}

async function matchPage(key, token) {
 if(!key){$('#content').innerHTML=heading('对局详情','缺少比赛标识')+`<a class="button" href="#matches">返回比赛档案</a>`;return;}
 let d,catalog;
 try{[d,catalog]=await Promise.all([api('/api/studio/match/'+encodeURIComponent(key)),api('/api/catalog').catch(()=>({entries:[]}))]);}catch(error){if(token!==generation)return;$('#content').innerHTML=heading('对局详情','读取失败：'+error.message)+`<a class="button" href="#matches">返回比赛档案</a>`;return;}
 if(token!==generation)return;
 let review=null;const reviewKey=d.bundleKey||key;
 if(reviewKey)review=await api('/api/review/'+encodeURIComponent(reviewKey)).catch(()=>null);
 if(token!==generation)return;
 const icons=Object.fromEntries(((catalog?.entries)||[]).filter(e=>e.kind==='hero'&&e.icon).map(e=>[e.name,e.icon]));
 const heroIcon=hero=>icons[hero]?`<img src="${esc(icons[hero])}" alt="" loading="lazy">`:`<b>${esc((hero||'?')[0])}</b>`;
 const campOf=p=>['red','right'].includes(p.camp||p.side)?'red':'blue';
 const players=d.players||[];
 const blue=players.filter(p=>campOf(p)==='blue'),red=players.filter(p=>campOf(p)==='red');
 const sum=(list,key)=>list.reduce((total,p)=>total+(Number(p[key])||0),0);
 const totals=d.teamTotals||{};
 const bt=totals.blue?.totals||{gold:sum(blue,'gold'),kills:sum(blue,'kills'),damage:sum(blue,'damage'),taken:sum(blue,'taken')};
 const rt=totals.red?.totals||{gold:sum(red,'gold'),kills:sum(red,'kills'),damage:sum(red,'damage'),taken:sum(red,'taken')};
 const blueScore=d.scores?.blue??d.scores?.left??'—',redScore=d.scores?.red??d.scores?.right??'—';
 const own=d.ownCamp==='left'?'blue':d.ownCamp==='right'?'red':d.ownCamp;
 const campLabel=camp=>own?(camp===own?'本队':'对手'):(camp==='blue'?'蓝方':'红方');
 const dur=d.duration?`${Math.floor(d.duration/60)}:${String(Math.round(d.duration%60)).padStart(2,'0')}`:'时长未记录';
 const result=resultNames[d.result]||'待确认';
 const tone=d.result==='win'?'win':d.result==='loss'?'loss':d.result==='draw'?'draw':'unknown';
 const sourceText=(d.sources||[]).map(s=>sourceNames[s]||s).join(' / ')||'来源待确认';
 const lineup=players=>players.map(p=>`<div class="lineup-row"><span class="lineup-hero">${heroIcon(p.hero)}</span><span class="lineup-main"><strong>${p.hero?`<a href="#hero/${encodeURIComponent(p.hero)}">${esc(p.hero)}</a>`:'英雄未识别'}</strong><small>${p.label?`<a href="#player/${encodeURIComponent(p.label)}">${esc(p.label)}</a>`:'选手待确认'}${p.position?' · '+esc(p.position):''}</small></span><span class="lineup-kda">${p.kills??'—'} / ${p.deaths??'—'} / ${p.assists??'—'}</span><span class="lineup-gold">${n(p.gold,0)}</span><span class="lineup-damage">${n(p.damage,0)}</span></div>`).join('');
 const teamPanel=(camp)=>`<section class="match-team ${camp}"><div class="match-team-head"><span class="team-dot"></span><div><strong>${campLabel(camp)}</strong><small>${camp==='blue'?'蓝方':'红方'} · ${n((camp==='blue'?bt:rt).kills,0)} 击杀 · ${n((camp==='blue'?bt:rt).gold,0)} 经济</small></div></div><div class="lineup-head"><span>英雄 / 选手</span><span>KDA</span><span>经济</span><span>输出</span></div>${lineup(camp==='blue'?blue:red)}</section>`;
 const statCards=[['总经济','gold'],['击杀','kills'],['输出','damage'],['承伤','taken']].map(([label,field])=>`<div class="match-stat-card"><span>${label}</span><div><b class="blue">${n(bt[field],0)}</b><em>:</em><b class="red">${n(rt[field],0)}</b></div><small>${campLabel('blue')} / ${campLabel('red')}</small></div>`).join('');
 const timeline=(d.process?.timeline||[]).filter(p=>p.blueGold!==null&&p.blueGold!==undefined&&p.redGold!==null&&p.redGold!==undefined);
 const orderedTimeline=timeline.filter(p=>Number.isFinite(Number(p.gameTime))&&Number.isFinite(Number(p.blueGold))&&Number.isFinite(Number(p.redGold))).sort((a,b)=>Number(a.gameTime)-Number(b.gameTime));
 const diffAt=p=>Number(p.blueGold)-Number(p.redGold);
 const high=orderedTimeline.reduce((best,p)=>!best||diffAt(p)>diffAt(best)?p:best,null);
 const low=orderedTimeline.reduce((best,p)=>!best||diffAt(p)<diffAt(best)?p:best,null);
 const lastPoint=orderedTimeline.at(-1);
 const sampleTime=p=>p?`${Math.floor(Number(p.gameTime)/60)}:${String(Math.floor(Number(p.gameTime)%60)).padStart(2,'0')}`:'—';
 const economyDigest=orderedTimeline.length?`<div class="economy-digest"><div><span>采样中最大蓝方领先</span><strong>${n(Math.max(0,diffAt(high)),0)}</strong><small>${diffAt(high)>0?sampleTime(high):'观测中未领先'}</small></div><div><span>采样中最大红方领先</span><strong>${n(Math.max(0,-diffAt(low)),0)}</strong><small>${diffAt(low)<0?sampleTime(low):'观测中未领先'}</small></div><div><span>末次观测经济差（蓝 − 红）</span><strong>${diffAt(lastPoint)>0?'+':''}${n(diffAt(lastPoint),0)}</strong><small>观测至 ${sampleTime(lastPoint)} · ${orderedTimeline.length} 个点</small></div></div>`:'';
 const killCandidates=d.process?.killEvents||[];
 const eventNumber=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
 const eventConsistent=e=>{
  const finalScore=e.camp==='blue'?blueScore:e.camp==='red'?redScore:null;
  return ['blue','red'].includes(e.camp)&&['gameTime','delta','after'].every(key=>eventNumber(e[key]))
   &&Number(e.gameTime)>=0&&(!d.duration||Number(e.gameTime)<=Number(d.duration))
   &&Number.isInteger(Number(e.delta))&&Number.isInteger(Number(e.after))
   &&Number(e.delta)>0&&Number(e.after)>=Number(e.delta)
   &&(!eventNumber(finalScore)||Number(e.after)<=Number(finalScore));
 };
 const inconsistentEvents=killCandidates.filter(e=>!eventConsistent(e)).length;
 const events=inconsistentEvents?[]:killCandidates.slice().sort((a,b)=>Number(b.gameTime)-Number(a.gameTime)).slice(0,8);

 const warnings=d.warnings||[];
 const equipmentIcons=Object.fromEntries(((catalog?.entries)||[]).filter(e=>e.kind==='equipment'&&e.icon).map(e=>[e.name,e.icon]));
 const equipmentOf=player=>{
  const raw=player.equipment||player.equipmentCandidates||[];
  const list=Array.isArray(raw)?raw:Object.values(raw||{});
  return list.map(item=>typeof item==='string'?item:item?.name||item?.candidates?.[0]?.name||'').filter(Boolean);
 };
 const equipped=players.map(player=>({player,items:equipmentOf(player)})).filter(item=>item.items.length);
 const equipmentPanel=`<details class="panel raw-fold"><summary>装备记录（${equipped.length}/${players.length} 人）</summary><div class="panel-body">${equipped.length?`<div class="equip-grid">${equipped.map(({player,items})=>`<div class="equip-row"><span class="equip-player"><strong>${esc(player.hero||'英雄未识别')}</strong><small>${esc(player.label||'选手待确认')}</small></span><div class="equip-items">${items.map(item=>`<span class="equip-item">${equipmentIcons[item]?`<img src="${esc(equipmentIcons[item])}" alt="" loading="lazy">`:''}${esc(item)}</span>`).join('')}</div></div>`).join('')}</div>`:'<div class="empty-state">这场没有装备识别结果；可在截图采集或校对时补。</div>'}</div></details>`;
 const eventRows=inconsistentEvents?`<div class="notice">${inconsistentEvents} 条候选的时间、累计击杀或增量与终局比分不一致，本组暂不作为可靠击杀记录展示。</div><details class="raw-fold"><summary>查看原始候选（待校对）</summary><div class="table-scroll"><table class="data-table"><thead><tr><th>游戏秒</th><th>阵营</th><th>增量</th><th>累计</th></tr></thead><tbody>${killCandidates.slice(-50).map(e=>`<tr><td>${esc(e.gameTime)}</td><td>${esc(e.camp)}</td><td>${esc(e.delta)}</td><td>${esc(e.after)}</td></tr>`).join('')}</tbody></table></div><p class="note">保留来源原值，最多展示末 50 条；需回到录屏或来源核对。</p></details>`:events.length?events.map(e=>`<div class="match-event"><span class="event-time">${Math.floor(e.gameTime/60)}:${String(Math.round(e.gameTime%60)).padStart(2,'0')}</span><span class="event-camp ${e.camp==='red'?'red':'blue'}">${e.camp==='red'?'红':'蓝'}</span><span>+${n(e.delta,0)} 击杀</span><span class="event-total">累计 ${n(e.after,0)}</span></div>`).join(''):'<div class="empty-state">这场没有可用的击杀事件。</div>';
 const warningList=warnings.length?`<ul class="match-warnings">${warnings.slice(0,4).map(w=>`<li>${esc(w)}</li>`).join('')}</ul>${warnings.length>4?`<details><summary class="note">查看全部 ${warnings.length} 条提示</summary><ul class="match-warnings">${warnings.slice(4).map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}`:'<div class="empty-state">没有数据提示。</div>';
 const extras=`<section class="pn-extra" id="match-extra"><div class="pn-extra-head"><span class="page-eyebrow">MATCH RECORDS</span><h2>本局资料</h2><p>全景之外的来源记录：终局合计、BP 补录、截图装备与逐人明细。</p></div><div class="match-stat-strip">${statCards}</div><div id="match-bp">${bpEditorHtml(d.bp||{})}</div>${equipmentPanel}<details class="panel raw-fold"><summary id="match-full-data">十人完整数据（${players.length} 人）</summary><div class="panel-body">${table(players.map(p=>({...p,partial:p.partial})),['label','hero','camp','kills','deaths','assists','gold','damage','taken','participation','rating','partial'])}</div></details><section class="panel"><div class="panel-head"><div><h2>数据提示</h2><p>识别范围和缺失字段。</p></div></div><div class="panel-body">${warningList}</div></section></section>`;
 if(review){
  await renderPanorama($('#content'),{api,key:reviewKey,payload:review,embedded:true,isCurrent:()=>token===generation,toast});
  if(token!==generation)return;
  $('#content').insertAdjacentHTML('beforeend',extras);
  bindBpEditor($('#content'),async bp=>{await api('/api/studio/bp/'+encodeURIComponent(key),{bp,expectedBp:d.bp||{}});d.bp=bp;await fetch('/api/analysis/reload',{method:'POST'});workspaceDirty=true;},toast);
  return;
 }
 $('#content').innerHTML=`<a class="back-link" href="#matches">← 返回比赛档案</a><div class="page-heading"><div><span class="page-eyebrow">MATCH · 对局详情</span><h1>${esc(d.opponent?'vs '+d.opponent:d.title||'对局详情')}</h1><p>${esc(d.date||'日期待补')} · ${esc(d.session||'训练赛')} · ${esc(d.mode||'模式未记录')} · ${dur}</p><div class="page-facts"><span>${players.length} 人</span><span>${sourceText}</span><span>${warnings.length} 条提示</span></div></div><div class="heading-actions"><button class="button" data-print>打印 / PDF</button>${d.dbId?`<a class="button" href="#review/${encodeURIComponent(d.dbId)}">原始复盘记录</a>`:''}<a class="button" href="#matches">比赛档案</a></div></div>`
 +`<nav class="match-section-nav" aria-label="本局复盘章节"><button data-section="match-lineups">赛果与阵容</button><button data-section="match-process">经济过程</button><button data-section="match-bp">BP 补录</button><button data-section="match-full-data">十人数据</button></nav><section id="match-lineups" class="panel match-hero">${teamPanel('blue')}<div class="match-center"><span class="match-result ${tone}">${result}</span><div class="match-big-score"><b>${esc(blueScore)}</b><em>:</em><b>${esc(redScore)}</b></div><small>${dur} · ${esc(d.mode||'模式未记录')}</small><span class="match-camp-note">${own?`本队：${own==='blue'?'蓝方':'红方'}`:'本队阵营待确认'}</span></div>${teamPanel('red')}</section>`
 +`<div class="match-stat-strip">${statCards}</div>`
 +`<section id="match-process" class="panel match-timeline"><div class="panel-head"><div><h2>经济曲线</h2><p>蓝方经济 − 红方经济；正值代表蓝方领先。</p></div>${pill('时间轴','neutral')}</div><div class="panel-body">${economyDigest}<div id="interactive-match-timeline"></div></div></section>`
 +`<div class="match-columns"><section class="panel"><div class="panel-head"><div><h2>击杀记录</h2><p>按来源记录的击杀变化；时间可能不连续，不代表完整团战过程。</p></div></div><div class="panel-body">${eventRows}</div></section><section class="panel"><div class="panel-head"><div><h2>数据提示</h2><p>识别范围和缺失字段。</p></div></div><div class="panel-body">${warningList}</div></section></div>`
 +`<div id="match-bp">${bpEditorHtml(d.bp||{})}</div>`
 +equipmentPanel
 +`<details class="panel raw-fold"><summary id="match-full-data">十人完整数据（${players.length} 人）</summary><div class="panel-body">${table(players.map(p=>({...p,partial:p.partial})),['label','hero','camp','kills','deaths','assists','gold','damage','taken','participation','rating','partial'])}</div></details>`;
 bindBpEditor($('#content'),async bp=>{await api('/api/studio/bp/'+encodeURIComponent(key),{bp,expectedBp:d.bp||{}});d.bp=bp;await fetch('/api/analysis/reload',{method:'POST'});workspaceDirty=true;},toast);
 mountEconomyTimeline($('#interactive-match-timeline'),orderedTimeline);
 document.querySelectorAll('[data-section]').forEach(button=>button.onclick=()=>{const target=document.getElementById(button.dataset.section);if(target?.tagName==='SUMMARY')target.parentElement.open=true;target?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});

}


async function playersPage(token) {
 const isHero=listTab==='heroes';
 const requests=[api('/api/studio/view/'+(isHero?'heroes':'players')+query()+(isHero?'&compact=1':'')),api('/api/studio/rows'+query()+'&limit=200')];
 if(isHero)requests.push(api('/api/catalog'));
 const [data,raw,catalog]=await Promise.all(requests);if(token!==generation)return;
 const rows=isHero?data.heroes:data.players;
 const matches=Number(raw.matches)||0;
 const sampleOf=row=>Number(row.picks ?? row.matches ?? 0)||0;
 const limited=matches<3;
 const title=isHero?'英雄与阵容':'选手分析';
 const subtitle=isHero
  ? '先看英雄池和出场，再比较表现；每个数字都标出样本数。'
  : '先看有效场数，再比较产出、经济与稳定性；每个数字都标出样本数。';
 const action=rows.length>=2
  ? `<a class="button primary" href="#compare/${isHero?'hero':'player'}">建立对比 ${icon('arrow')}</a>`
  : `<a class="button" href="#capture">再采集一局 ${icon('arrow')}</a>`;
 const heroIcons=Object.fromEntries(((catalog?.entries)||[]).filter(entry=>entry.kind==='hero'&&entry.icon).map(entry=>[entry.name,entry.icon]));
 const heroCard=(row,index)=>{
  const icon=heroIcons[row.hero];
  const kda=row.kda??null, gpm=row.gpm??null, dpm=row.dpm??null;
  const badge=row.decided?`${n(row.winRate,0)}%`:'—';
  return `<a class="hero-card" href="#hero/${encodeURIComponent(row.hero)}"><span class="hero-card-icon">${icon?`<img src="${esc(icon)}" alt="" loading="lazy">`:`<b>${esc((row.hero||'?')[0])}</b>`}</span><span class="hero-card-name"><strong>${esc(row.hero)}</strong><small><b class="hero-rank">样本</b> ${n(row.picks,0)} 次 · ${(row.players||[]).length} 人</small></span><span class="hero-card-badge ${row.decided&&sampleOf(row)>=3?'':'muted'}" title="样本 ${sampleOf(row)} 次">${badge}</span><span class="hero-card-stats"><span>KDA <b>${n(kda,2)}</b></span><span>分均经济 <b>${n(gpm,1)}</b></span><span>分均输出 <b>${n(dpm,1)}</b></span></span></a>`;
 };
 const playerCard=(row,index)=>{
  const badge=row.decided?`${n(row.winRate,0)}%`:'—';
  return `<a class="hero-card player-card" href="#player/${encodeURIComponent(row.label)}"><span class="hero-card-icon player-avatar">${esc((row.label||'?').slice(0,2))}</span><span class="hero-card-name"><strong>${esc(row.label)}</strong><small><b class="hero-rank">样本</b> ${n(row.matches,0)} 局 · ${row.bound?'已绑定':'未绑定'}</small></span><span class="hero-card-badge ${row.decided&&Number(row.matches)>=3?'':'muted'}" title="样本 ${n(row.matches,0)} 局">${badge}</span><span class="hero-card-stats"><span>KDA <b>${n(row.kda,2)}</b></span><span>分均经济 <b>${n(row.gpm,1)}</b></span><span>参团 <b>${n(row.participation,0)}%</b></span></span></a>`;
 };
 const cards=rows.map((row,index)=>isHero?heroCard(row,index):playerCard(row,index)).join('');
 const sampleNote=limited?`<div class="sample-note av-sample-note">当前样本 ${matches} 局：仅描述已有表现，不作长期能力判断。</div>`:'';
 const cardPanel=`<section class="panel"><div class="panel-head"><div><h2>${isHero?'英雄池':'选手表现'}</h2><p>点卡片查看逐局记录；每个数字标出样本数。</p></div>${pill(`${rows.length} ${isHero?'个英雄':'名选手'}`,'neutral')}</div><div class="panel-body">${cards?`<div class="hero-card-grid">${cards}</div>`:empty('还没有可用记录','先采集并确认比赛，或者调整日期、选手和英雄筛选。','#capture','采集一局')}</div></section>`;
 const aggregateColumns=isHero?['hero','picks','fullPicks','winRate','kda','gpm','dpm']:['label','matches','fullRows','partialRows','winRate','kda','gpm','dpm','participation'];
 const aggregateDetails=`<details class="panel raw-fold"><summary>查看汇总表</summary><div class="panel-body"><p class="note">按有效场次比较；每行都标出出场/场次，点开逐局数据可回到原始记录。数据来自已确认比赛，截图候选不混入。</p>${table(rows,aggregateColumns)}</div></details>`;
 const rawDetails=`<details class="panel raw-fold"><summary>查看逐局数据（前 ${n(raw.rows.length,0)} / ${n(raw.total ?? raw.rows.length,0)} 行）</summary><div class="panel-body">${table(raw.rows,['label','hero','date','kills','deaths','assists','gold','damage','participation','matchKey'])}</div></details>`;
 const factLine=`<div class="page-facts"><span>${matches} 局</span><span>${rows.length} ${isHero?'个英雄':'名选手'}</span><span>${n(raw.total ?? raw.rows.length,0)} 条记录</span></div>`;
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">ANALYSIS · ${title}</span><h1>${title}</h1><p>${subtitle}</p>${factLine}</div>${action}</div>`
 +sampleNote
 +`<details class="page-filter"><summary><span>筛选数据</span><small>按日期、选手、英雄或对手筛选</small></summary>${filtersHtml()}</details>`
 +`<div id="performance-explorer"></div>`
 +cardPanel
 +rawDetails
 +aggregateDetails
 +`<div class="section-heading"><h2>下一步</h2></div><div class="next-grid"><a class="next-card" href="${isHero?'#players':'#heroes'}"><strong>${isHero?'看选手状态':'看英雄池'}</strong><span>${isHero?'近期表现、稳定性和英雄池':'出场、表现和阵容搭配'}</span><em>→</em></a><a class="next-card" href="#team"><strong>看团队节奏</strong><span>经济、资源、BP 和对手档案</span><em>→</em></a><a class="next-card" href="#topics/hero_pool"><strong>检查英雄池</strong><span>英雄池、搭档、经济转折</span><em>→</em></a></div>`;
 mountPerformanceExplorer($('#performance-explorer'),rows,{kind:isHero?'hero':'player'});
}
function analysisPage(){
 $('#content').innerHTML=heading('全部功能','按比赛、战队、选手、英雄和具体任务查找，直接进入所需页面。')
 +`<div class="feature-directory">${nav.filter(([group])=>group!=='首页').map(([group,items])=>`<section class="panel feature-directory-group"><div class="panel-head"><h2>${group}</h2><span class="pill neutral">${items.length} 项</span></div><div class="feature-directory-links">${items.map(([key,label])=>`<a href="#${key}"><strong>${label}</strong><span>${esc(navDescriptions[key]||'')}</span>${icon('arrow')}</a>`).join('')}</div></section>`).join('')}</div>`;
}

async function comparePage(token) {
 let playersView,heroesView,catalog;
 try{[playersView,heroesView,catalog]=await Promise.all([api('/api/studio/view/players'+query()),api('/api/studio/view/heroes'+query()+'&compact=1'),api('/api/catalog').catch(()=>({entries:[]}))]);}catch(error){if(token!==generation)return;$('#content').innerHTML=heading('对比','读取失败：'+error.message);return;}
 if(token!==generation)return;
 const players=playersView.players||[],heroes=heroesView.heroes||[];
 const icons=Object.fromEntries(((catalog?.entries)||[]).filter(entry=>entry.kind==='hero'&&entry.icon).map(entry=>[entry.name,entry.icon]));
 const heroIcon=hero=>icons[hero]?`<img src="${esc(icons[hero])}" alt="" loading="lazy">`:`<b>${esc((hero||'?')[0])}</b>`;
 const state={kind:location.hash.split('/')[1]==='hero'?'hero':'player',a:null,b:null};
 const list=()=>state.kind==='player'?players:heroes;
 const keyOf=item=>state.kind==='player'?item.label:item.hero;
 const metricDefs=()=>state.kind==='player'
  ? [['kda','KDA',2],['gpm','分均经济',1],['dpm','分均输出',1],['participation','参团率',0],['winRate','胜率',1]]
  : [['kda','KDA',2],['gpm','分均经济',1],['dpm','分均输出',1],['picks','出场',0],['winRate','胜率',1]];
 const fillSelects=()=>{
  const items=list();
  const options=items.map(item=>`<option value="${esc(keyOf(item))}">${esc(keyOf(item))}</option>`).join('');
  $('#compare-a').innerHTML=options;$('#compare-b').innerHTML=options;
  const requested=decodeURIComponent(location.hash.split('/')[2]||'');
  if(items.length){state.a=items.some(item=>keyOf(item)===requested)?requested:keyOf(items[0]);$('#compare-a').value=state.a;}
  if(items.length>1){state.b=keyOf(items.find(item=>keyOf(item)!==state.a));$('#compare-b').value=state.b;}
  else{state.b=state.a;$('#compare-b').value=state.b;}
 };
 const entityCard=item=>state.kind==='player'
  ? `<article class="compare-entity"><span class="compare-avatar player-avatar">${esc((item.label||'?').slice(0,2))}</span><div><h3>${esc(item.label)}</h3><p>${n(item.matches,0)} 局 · ${item.bound?'已绑定名单':'未绑定名单'}</p><small>${item.heroes?.[0]?`常用：${esc(item.heroes[0].hero)} · ${n(item.heroes[0].matches,0)} 次`:''}</small></div></article>`
  : `<article class="compare-entity"><span class="compare-avatar">${heroIcon(item.hero)}</span><div><h3>${esc(item.hero)}</h3><p>${n(item.picks,0)} 次出场 · ${(item.players||[]).length} 名选手</p><small>${item.fullPicks!=null?`完整终局 ${n(item.fullPicks,0)} 次`:''}</small></div></article>`;
 const draw=()=>{
  const items=list();
  const a=items.find(item=>keyOf(item)===state.a)||items[0];
  const b=items.find(item=>keyOf(item)===state.b)||items[1]||items[0];
  if(!a||!b||keyOf(a)===keyOf(b)){$('#compare-output').innerHTML=empty('至少需要两个对象','先采集并确认更多比赛，或切换选手/英雄类型。','#capture','采集一局');return;}
  const rows=metricDefs().map(([key,label,digits])=>{
   const av=metricNumber(a[key]),bv=metricNumber(b[key]);
   const validA=av!==null,validB=bv!==null;
   const max=Math.max(validA?Math.abs(av):0,validB?Math.abs(bv):0,1);
   const pa=validA?Math.max(2,Math.abs(av)/max*100):0,pb=validB?Math.max(2,Math.abs(bv)/max*100):0;
   const diff=validA&&validB?av-bv:null;
   const diffText=diff==null?'—':`${diff>=0?'+':''}${n(diff,digits)}`;
   return `<div class="compare-row"><span>${label}</span><div class="compare-value"><b>${validA?n(av,digits):'—'}</b><i class="compare-bar a"><em style="width:${pa}%"></em></i></div><div class="compare-value"><b>${validB?n(bv,digits):'—'}</b><i class="compare-bar b"><em style="width:${pb}%"></em></i></div><strong class="${diff==null?'':diff>=0?'up':'down'}">${diffText}</strong></div>`;
  }).join('');
  const radarDefs=state.kind==='player'?[['kda','KDA'],['gpm','分均经济'],['dpm','分均输出'],['participation','参团'],['winRate','胜率']]:[['picks','出场'],['winRate','胜率'],['kda','KDA'],['gpm','分均经济'],['dpm','分均输出']];
  const radarValue=item=>radarDefs.map(([key])=>{const value=metricNumber(item[key]);const max=Math.max(1,...items.map(row=>metricNumber(row[key])??0));return value===null?null:Math.round(value/max*100);});
  const radarHtml=`<section class="panel"><div class="panel-head"><div><h2>指标结构</h2><p>按当前筛选的同类对象最大值归一化，仅展示双方共同有效维度；跨位置不作综合能力评级。</p></div></div><div class="panel-body">${radarSvg(radarDefs.map(([,label])=>label),[{name:keyOf(a),color:'#2f6fe4',values:radarValue(a)},{name:keyOf(b),color:'#df8c39',values:radarValue(b)}])}</div></section>`;
  $('#compare-output').innerHTML=`<div class="compare-grid">${entityCard(a)}<span class="compare-vs">VS</span>${entityCard(b)}</div><div class="av-comparison-grid">${comparisonVisual(a,b,metricDefs(),items)}${radarHtml}</div><details class="panel raw-fold"><summary>查看指标原值与差值</summary><div class="panel-body"><div class="compare-head"><span>指标</span><b>${esc(keyOf(a))}</b><b>${esc(keyOf(b))}</b><strong>A − B</strong></div>${rows}</div></details><p class="note">样本数见对象卡；沿用当前日期、选手、英雄和对手筛选。分均指标按有效总量 / 有效分钟计算；KDA 按有效比赛汇总，零死亡分母按 1 计。</p>`;

 };
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">COMPARE · 对比</span><h1>选手 / 英雄对比</h1><p>选两个对象，按同一筛选比较 KDA、经济、输出和胜率。</p><div class="page-facts"><span>${players.length} 名选手</span><span>${heroes.length} 个英雄</span></div></div><div class="heading-actions"><button class="button" data-print>打印 / PDF</button><a class="button" href="#players">选手列表</a><a class="button" href="#heroes">英雄列表</a></div></div>`
 +`<section class="panel compare-picker"><div class="panel-body"><div class="compare-toolbar"><div class="compare-toggle"><button class="active" data-compare-kind="player">选手</button><button data-compare-kind="hero">英雄</button></div><label class="field">对象 A<select id="compare-a"></select></label><span class="compare-vs-text">VS</span><label class="field">对象 B<select id="compare-b"></select></label></div></div></section><div class="av-swap-row"><button class="button" id="compare-swap">交换 A / B</button><span>选择同类对象，保留原始单位与样本</span></div><div id="compare-output"></div>`;
 fillSelects();draw();
 document.querySelectorAll('[data-compare-kind]').forEach(button=>button.classList.toggle('active',button.dataset.compareKind===state.kind));
 document.querySelectorAll('[data-compare-kind]').forEach(button=>button.onclick=()=>{location.hash='compare/'+button.dataset.compareKind;});
 $('#compare-swap').onclick=()=>{[state.a,state.b]=[state.b,state.a];$('#compare-a').value=state.a;$('#compare-b').value=state.b;draw();};
 $('#compare-a').onchange=()=>{state.a=$('#compare-a').value;draw();};
 $('#compare-b').onchange=()=>{state.b=$('#compare-b').value;draw();};
}


function radarSvg(labels, series) {
 const valid=labels.map((_,i)=>i).filter(i=>series.every(item=>metricNumber(item.values[i])!==null));
 labels=valid.map(i=>labels[i]);series=series.map(item=>({...item,values:valid.map(i=>item.values[i])}));
 if(labels.length<3)return '<div class="radar-wrap"><div class="av-empty">共同有效指标少于三个，暂不绘制结构图。</div></div>';
 const size=440,cx=220,cy=220,radius=118,n=labels.length;
 if(!n)return '';
 const angle=index=>-Math.PI/2+index*2*Math.PI/n;
 const point=(index,value)=>{const r=radius*Math.max(0,Math.min(100,Number(value)||0))/100;return [cx+Math.cos(angle(index))*r,cy+Math.sin(angle(index))*r];};
 const rings=[.25,.5,.75,1].map(ratio=>`<polygon points="${labels.map((_,index)=>point(index,ratio*100).join(',')).join(' ')}" fill="none" stroke="#edf1f7"/>`).join('');
 const axes=labels.map((_,index)=>{const end=point(index,100);return `<line x1="${cx}" y1="${cy}" x2="${end[0]}" y2="${end[1]}" stroke="#edf1f7"/>`;}).join('');
 const texts=labels.map((label,index)=>{const a=angle(index),end=[cx+Math.cos(a)*(radius+48),cy+Math.sin(a)*(radius+48)];return `<text x="${end[0]}" y="${end[1]}" text-anchor="${Math.cos(angle(index))>.25?'start':Math.cos(angle(index))<-.25?'end':'middle'}" dominant-baseline="middle" fill="#667085" font-size="14">${esc(label)}</text>`;}).join('');
 const shapes=series.map(item=>`<polygon points="${item.values.map((value,index)=>point(index,value).join(',')).join(' ')}" fill="${item.color}" fill-opacity=".14" stroke="${item.color}" stroke-width="2"/>`).join('');
 const dots=series.map(item=>item.values.map((value,index)=>{const [x,y]=point(index,value);return `<circle cx="${x}" cy="${y}" r="2.5" fill="${item.color}"/>`;}).join('')).join('');
 const legend=series.map(item=>`<span><i style="background:${item.color}"></i>${esc(item.name)}</span>`).join('');
 return `<div class="radar-wrap"><svg viewBox="0 0 ${size} ${size}" role="img" aria-label="指标结构雷达图">${rings}${axes}${shapes}${dots}${texts}</svg><div class="radar-legend">${legend}</div></div>`;
}

async function entityPage(kind,name,token){
 const isHero=kind==='hero';
 if(!name){$('#content').innerHTML=heading(isHero?'英雄详情':'选手详情','缺少名称')+`<a class="button" href="#${isHero?'heroes':'players'}">返回列表</a>`;return;}
 let view,raw,catalog;
 try{[view,raw,catalog]=await Promise.all([api('/api/studio/view/'+(isHero?'heroes':'players')+query()+(isHero?'&compact=1':'')),api('/api/studio/rows'+query()+'&limit=1000&kind='+(isHero?'hero':'player')+'&name='+encodeURIComponent(name)),api('/api/catalog').catch(()=>({entries:[]}))]);}catch(error){if(token!==generation)return;$('#content').innerHTML=heading(isHero?'英雄详情':'选手详情','读取失败：'+error.message)+`<a class="button" href="#${isHero?'heroes':'players'}">返回列表</a>`;return;}
 if(token!==generation)return;
 const stat=(isHero?view.heroes:view.players).find(item=>isHero?item.hero===name:item.label===name);
 const rows=(raw.rows||[]).filter(row=>isHero?row.hero===name:row.label===name).sort((a,b)=>String(a.date||'').localeCompare(String(b.date||''))||String(a.matchKey||'').localeCompare(String(b.matchKey||'')));
 const icons=Object.fromEntries(((catalog?.entries)||[]).filter(entry=>entry.kind==='hero'&&entry.icon).map(entry=>[entry.name,entry.icon]));
 const heroIcon=hero=>icons[hero]?`<img src="${esc(icons[hero])}" alt="" loading="lazy">`:`<b>${esc((hero||'?')[0])}</b>`;
 if(!stat&&!rows.length){$('#content').innerHTML=`<a class="back-link" href="#${isHero?'heroes':'players'}">← 返回${isHero?'英雄':'选手'}列表</a>`+empty('当前筛选下没有这条记录','调整日期、选手、英雄或对手筛选后再看。','#sources','查看字段与来源');return;}
 const winRate=stat?.winRate==null?'—':`${n(stat.winRate,1)}%`;
 const sampleCount=isHero?(stat?.picks??rows.length):(stat?.matches??new Set(rows.map(row=>row.matchKey)).size);
 const kpis=isHero
  ? [['出场',n(stat?.picks??rows.length,0),'次'],['胜率',winRate,`${n(stat?.decided,0)} 局有胜负`],['KDA',n(stat?.kda,2),'汇总(击杀+助攻) / max(1,死亡)'],['分均经济',n(stat?.gpm,1),'金币 / 分钟'],['分均输出',n(stat?.dpm,1),'伤害 / 分钟'],['完整终局',n(stat?.fullPicks,0),`/ ${n(stat?.picks,0)} 次`]]
  : [['局数',n(stat?.matches??new Set(rows.map(row=>row.matchKey)).size,0),'场'],['胜率',winRate,`${n(stat?.decided,0)} 局有胜负`],['KDA',n(stat?.kda,2),'汇总(击杀+助攻) / max(1,死亡)'],['分均经济',n(stat?.gpm,1),'金币 / 分钟'],['分均输出',n(stat?.dpm,1),'伤害 / 分钟'],['参团率',n(stat?.participation,0),'%']];
 const heroPool=isHero?[]:(stat?.heroes||Object.entries(rows.reduce((map,row)=>{if(row.hero)map[row.hero]=(map[row.hero]||0)+1;return map;},{})).sort((a,b)=>b[1]-a[1]).map(([hero,count])=>({hero,matches:count})));
 const playerList=isHero?(stat?.players||[...new Set(rows.map(row=>row.label).filter(Boolean))]):[];
 const recent=rows.slice().reverse().slice(0,8);
 const recentRows=recent.length?recent.map(row=>`<a class="entity-match-row" href="#match/${esc(row.matchKey)}"><span>${esc(row.date||'日期待补')}</span><strong>${esc(isHero?(row.label||'选手待确认'):(row.hero||'英雄未识别'))}</strong><span>${row.kills??'—'} / ${row.deaths??'—'} / ${row.assists??'—'}</span><span>${n(row.gold,0)}</span><span>${n(row.damage,0)}</span><span class="match-result ${row.result==='win'?'win':row.result==='loss'?'loss':'unknown'}">${resultNames[row.result]||'—'}</span></a>`).join(''):'';
 const metricOptions=[['gold','总经济'],['damage','输出'],['participation','参团率'],['rating','评分']].map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
 const radarDefs=isHero?[['picks','出场'],['winRate','胜率'],['kda','KDA'],['gpm','分均经济'],['dpm','分均输出']]:[['kda','KDA'],['gpm','分均经济'],['dpm','分均输出'],['participation','参团'],['winRate','胜率']];
 const radarList=isHero?view.heroes:view.players;
 const radarValues=radarDefs.map(([key])=>{const value=metricNumber(stat?.[key]);const max=Math.max(1,...radarList.map(item=>metricNumber(item[key])??0));return value===null?null:Math.round(value/max*100);});
 const radarPanel=`<section class="panel entity-radar-panel"><div class="panel-head"><div><h2>指标结构</h2><p>相对当前筛选下同列表最大值，用于看形状，不是绝对评级。</p></div></div><div class="panel-body">${radarSvg(radarDefs.map(([,label])=>label),[{name:name,color:'#2f6fe4',values:radarValues}])}</div></section>`;
 $('#content').innerHTML=`<a class="back-link" href="#${isHero?'heroes':'players'}">← 返回${isHero?'英雄':'选手'}列表</a><div class="page-heading entity-heading"><div class="entity-heading-main"><span class="entity-icon ${isHero?'':'player-avatar'}">${isHero?heroIcon(name):esc((name||'?').slice(0,2))}</span><div><span class="page-eyebrow">${isHero?'HERO':'PLAYER'} · ${isHero?'英雄详情':'选手详情'}</span><h1>${esc(name)}</h1><p>${isHero?`${n(stat?.picks,0)} 次出场 · ${(stat?.players||[]).length} 名选手使用`:`${n(stat?.matches,0)} 局 · ${stat?.bound?'已绑定名单':'未绑定名单'}`}</p><div class="page-facts"><span>样本 ${n(sampleCount,0)}</span><span>胜率 ${winRate}</span><span>${rows.length} 行数据</span></div></div></div><div class="heading-actions"><button class="button" data-print>打印 / PDF</button><a class="button" href="#${isHero?'heroes':'players'}">返回列表</a><a class="button primary" href="#topics/hero_pool">英雄池 ${icon('arrow')}</a></div></div>`
 +`<div class="entity-kpi-grid">${kpis.map(([label,value,note])=>`<div class="entity-kpi"><span>${label}</span><b>${value}</b><small>${note}</small></div>`).join('')}</div>`
 +`<div class="entity-columns"><section class="panel"><div class="panel-head"><div><h2>指标走势</h2><p>按对象记录顺序；缺失不补零，同局多条记录分别展示。</p></div><select id="entity-metric">${metricOptions}</select></div><div class="panel-body" id="entity-chart"></div></section><section class="panel"><div class="panel-head"><div><h2>${isHero?'使用选手':'常用英雄'}</h2><p>${isHero?'按当前筛选记录列出':'按出场次数排序'}</p></div></div><div class="panel-body">${isHero?(playerList.length?`<div class="entity-chip-list">${playerList.map(label=>`<a class="entity-chip" href="#player/${encodeURIComponent(label)}">${esc(label)}</a>`).join('')}</div>`:empty('还没有选手记录','当前筛选下没有可用记录。','#sources','查看字段与来源')):(heroPool.length?`<div class="entity-hero-list">${heroPool.slice(0,8).map(item=>`<a class="entity-hero" href="#hero/${encodeURIComponent(item.hero)}"><span class="entity-hero-icon">${heroIcon(item.hero)}</span><strong>${esc(item.hero)}</strong><small>${n(item.matches,0)} 次</small></a>`).join('')}</div>`:empty('还没有英雄记录','当前筛选下没有可用记录。','#sources','查看字段与来源'))}</div></section></div>`
 +radarPanel
 +`<section class="panel"><div class="panel-head"><div><h2>最近比赛</h2><p>点击进入对局详情。</p></div><span class="pill">${recent.length} 局</span></div><div class="panel-body">${recentRows?`<div class="entity-match-head"><span>日期</span><span>${isHero?'选手':'英雄'}</span><span>KDA</span><span>经济</span><span>输出</span><span>结果</span></div>${recentRows}`:'<div class="empty-state">当前筛选下没有逐局记录。</div>'}</div></section>`
 +`<div class="section-heading"><h2>下一步</h2></div><div class="next-grid"><a class="next-card" href="#team"><strong>看团队复盘</strong><span>经济节奏、资源、BP 和对手档案</span><em>→</em></a><a class="next-card" href="#compare/${isHero?'hero':'player'}/${encodeURIComponent(name)}"><strong>对比${isHero?'英雄':'选手'}表现</strong><span>保留当前对象，再选择一个参照</span><em>→</em></a><a class="next-card" href="#${isHero?'players':'heroes'}"><strong>${isHero?'看选手状态':'看英雄池'}</strong><span>${isHero?'近期表现、稳定性和英雄池':'出场、表现和阵容搭配'}</span><em>→</em></a></div>`;
 mountEntityTrend($('#entity-chart'),rows,'gold');
 $('#entity-metric').onchange=()=>{mountEntityTrend($('#entity-chart'),rows,$('#entity-metric').value);};
}

function sparkline(points) {
 const good=(points||[]).filter(point=>Array.isArray(point)&&Number.isFinite(Number(point[1])));
 if(good.length<2)return '';
 const width=160,height=46,pad=3;
 const values=good.map(point=>Number(point[1]));
 const min=Math.min(0,...values),max=Math.max(0,...values);
 const span=max-min||1;
 const x=index=>pad+index/(good.length-1)*(width-2*pad);
 const y=value=>height-pad-((Number(value)-min)/span)*(height-2*pad);
 const path=good.map((point,index)=>`${index?'L':'M'}${x(index)} ${y(point[1])}`).join(' ');
 return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" aria-hidden="true"><line x1="${pad}" x2="${width-pad}" y1="${y(0)}" y2="${y(0)}" stroke="#e3e8f1" stroke-dasharray="3 3"/><path d="${path}" fill="none" stroke="#2f6fe4" stroke-width="2" stroke-linejoin="round"/></svg>`;
}

async function teamPage(token) {
 const endpoint={process:'process',matchups:'lane-matchups',bp:'bp',objectives:'objectives',scouting:'scouting'}[teamTab];
 const [data,matchList,processData]=await Promise.all([api('/api/studio/view/'+endpoint+query()),api('/api/studio/view/matches'+query()+'&limit=1'),endpoint==='process'?Promise.resolve(null):api('/api/studio/view/process'+query())]);if(token!==generation)return;
 const o=workspace.overview||{},summary=matchList.summary||{},observed=processData||data;
 const teamName=o.teamName||'本队';
 const matches=Number(matchList.total)||0,complete=Number(summary.complete)||0,timeline=Number(observed.aggregate?.games)||0;
 const decided=matches-(Number(summary.unknown)||0),wins=Number(summary.wins)||0,losses=Number(summary.losses)||0;
 const winRate=decided?`${n(wins/decided*100,1)}%`:'—';
 const winRateLabel=winRate;
 const tabs=[['process','经济节奏'],['matchups','分路对位'],['bp','BP 记录'],['objectives','资源控制'],['scouting','对手档案']];
 const tabHtml=`<div class="tabs team-tabs">${tabs.map(([key,label])=>`<button class="tab ${teamTab===key?'active':''}" data-team-tab="${key}">${label}</button>`).join('')}</div>`;
 let content='';
 if(teamTab==='process'){
  const aggregate=data.aggregate||{};
  const avgDiff=aggregate.avgDiffAt?.['600']??aggregate.avgDiffAt?.[600];
  content=`<div class="team-kpi-grid"><div class="team-kpi"><span>纳入时段分析</span><b>${n(aggregate.games,0)}</b><small>局 · 门槛 60% 覆盖</small></div><div class="team-kpi"><span>10 分钟领先转化</span><b>${aggregate.leadAt10Games?`${n(aggregate.leadAt10Conversion,0)}%`:'—'}</b><small>${n(aggregate.leadAt10Games,0)} 局可判定</small></div><div class="team-kpi"><span>平均 10 分钟经济差</span><b>${avgDiff==null?'—':`${Number(avgDiff)>=0?'+':''}${n(avgDiff,0)}`}</b><small>本队 − 对手</small></div><div class="team-kpi"><span>翻盘 / 被翻盘</span><b>${n(aggregate.comebacks,0)} / ${n(aggregate.blownLeads,0)}</b><small>只统计已知赛果</small></div></div>`
   +processMatrix(data)
   +((data.matches||[]).length?`<div class="process-grid">${data.matches.map(m=>`<article class="process-card"><div class="process-card-top"><span>${esc(m.date||'日期待补')}</span><span class="match-result ${m.win===true?'win':m.win===false?'loss':'unknown'}">${m.win===true?'胜':m.win===false?'负':'待确认'}</span></div><h3>${esc(m.opponent?'vs '+m.opponent:`${m.date||'本局'} · 训练赛`)}</h3><div class="process-card-meta"><span>覆盖 ${n(m.coverage,1)}%</span><span>末次观测差 ${m.finalDiff==null?'—':`${Number(m.finalDiff)>=0?'+':''}${n(m.finalDiff,0)}`}</span></div>${sparkline(m.points)}<div class="process-card-foot"><span>${m.leadAt10===null?'10 分钟未覆盖':m.leadAt10?'10 分钟领先':'10 分钟未领先'}</span><a class="text-link" href="#match/${esc(m.key)}">打开对局 →</a></div></article>`).join('')}</div>`:empty('还没有覆盖足够的时段分析','需要已确认本队阵营和覆盖至少 60% 的团队时间轴。','#matches','查看比赛档案'))
   +`<details class="panel raw-fold"><summary>表格视图（${(data.matches||[]).length} 局）</summary><div class="panel-body">${table((data.matches||[]).map(m=>({...m,matchKey:m.key})),['date','opponent','coverage','matchKey','win'],{emptyTitle:'当前样本未满足时段分析条件',emptyText:'片段仍可在比赛详情查看。'})}</div></details>`;
 }else if(teamTab==='matchups'){
  content=(data.rows||[]).length?`<section class="panel">${table(data.rows,['date','position','diff','win','matchKey'])}</section>`:empty('对位信息尚未齐全','双方实际分路与终局经济都确认后，可比较同位置经济差。','#matches','查看比赛档案');
 }else if(teamTab==='bp'){
  content=(data.bans||[]).length?`<section class="panel">${table(data.bans,Object.keys(data.bans[0]||{hero:'',count:''}))}</section>`:empty('还没有结构化 BP 记录','比赛校对中填写双方 ban/pick 后，可查看禁选频率与手序。','#matches','查看比赛档案');
 }else if(teamTab==='objectives'){
  const items=[['tyrant','暴君'],['dominator','主宰'],['storm','风暴龙王'],['towers','防御塔']];
  const cards=items.map(([key,label])=>{const item=(data.aggregate||{})[key]||{};const value=item.ownRate!=null?`${n(item.ownRate,0)}%`:item.avgDiff!=null?`${Number(item.avgDiff)>=0?'+':''}${n(item.avgDiff,1)}`:'—';return `<div class="team-kpi"><span>${label}</span><b>${value}</b><small>${item.matches?`${n(item.matches,0)} 局有记录`:'暂无记录'}</small></div>`;}).join('');
  content=`<div class="team-kpi-grid">${cards}</div>${(data.rows||[]).length?`<section class="panel">${table(data.rows,['date','opponent','matchKey'])}</section>`:''}`;
 }else{
  const opponents=data.opponents||[];
  content=opponents.length?`<div class="opponent-grid">${opponents.map(item=>`<a class="opponent-card" href="#opponent/${encodeURIComponent(item.opponent||'')}"><span class="opponent-avatar">${esc((item.opponent||'?').slice(0,2))}</span><div><h3>${esc(item.opponent||'未命名对手')}</h3><p>${n(item.matches,0)} 场 · ${n(item.wins,0)} 胜${item.decided?` · ${n(item.decided,0)} 场有胜负`:''}</p></div><b>${item.winRate==null?'—':`${n(item.winRate,0)}%`}</b></a>`).join('')}</div>`:empty('还没有可用的对手档案','对手名称与比赛记录关联后生成。','#matches','查看比赛档案');
 }
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">TEAM · 团队复盘</span><h1>${esc(teamName)} · 团队复盘</h1><p>把经济节奏、对位、资源和 BP 放在同一份比赛背景里。</p><div class="page-facts"><span>${matches} 局</span><span>${wins} 胜 · ${losses} 负</span><span>胜率 ${winRateLabel}</span><span>${complete} 份终局</span></div></div><div class="heading-actions"><button class="button" data-print>打印 / PDF</button><a class="button" href="#matches">比赛档案 ${icon('arrow')}</a></div></div>`
 +`<div class="team-summary"><div class="team-kpi"><span>已确认比赛</span><b>${matches}</b><small>局</small></div><div class="team-kpi"><span>胜率</span><b>${winRateLabel}</b><small>${decided} 局有胜负</small></div><div class="team-kpi"><span>完整终局</span><b>${complete}</b><small>/ ${matches} 局</small></div><div class="team-kpi"><span>可分析时间轴</span><b>${timeline}</b><small>/ ${matches} 局</small></div></div>`
 +`<details class="page-filter"><summary><span>筛选数据</span><small>按日期、选手、英雄或对手筛选</small></summary>${filtersHtml()}</details>`
 +tabHtml
 +`<div class="team-content">${content}</div>`
 +`<div class="section-heading"><h2>下一步</h2></div><div class="next-grid"><a class="next-card" href="#players"><strong>看选手状态</strong><span>近期表现、稳定性和英雄池</span><em>→</em></a><a class="next-card" href="#heroes"><strong>看英雄池</strong><span>出场、表现和阵容搭配</span><em>→</em></a><a class="next-card" href="#topics/hero_pool"><strong>检查英雄池</strong><span>英雄池、搭档、经济转折</span><em>→</em></a></div>`;
}
async function labPage(token) {
 const inModels=pageName()==='models';if(inModels&&!['regression','prediction'].includes(selectedMethod))selectedMethod='regression';
 const availableMethods=workspace.methods.filter(m=>!inModels||['regression','prediction'].includes(m.key));
 preview=await getPreview();if(token!==generation)return;
 const method=workspace.methods.find(m=>m.key===selectedMethod)||workspace.methods[0];
 const groupKeys=preview.groupValues.hero;
 const scenarios=inModels?[
  {key:'regression',title:'指标解释',question:'哪些指标和输出同向？',note:'时间留出验证，报告误差与基线',method:'regression',metrics:['gold','damage','participation'],dimension:'label'},
  {key:'prediction',title:'赛前预测',question:'已选阵容和赛前信息能否预测胜负？',note:'按时间留出比赛，不看过未来',method:'prediction',metrics:['gold','damage'],dimension:'label'},
 ]:[
  {key:'describe',title:'看分布',question:'选手/英雄的水平、波动和缺失怎么样？',note:'均值、中位数、波动和缺失',method:'describe',metrics:['gold','damage','participation'],dimension:'label'},
  {key:'trend',title:'看趋势',question:'最近几局是在上升还是回落？',note:'逐局变化与近五局均值',method:'trend',metrics:['gold','damage'],dimension:'label'},
  {key:'anomaly',title:'找异常',question:'哪几局明显偏离常态？',note:'中位数偏差标记，不当作结论',method:'anomaly',metrics:['gold','damage'],dimension:'label'},
  {key:'compare',title:'两组对比',question:'两名选手或两个英雄差多少？',note:'按比赛聚合后比较两组',method:'compare',metrics:['gold','damage'],dimension:'label'},
  {key:'correlation',title:'看相关性',question:'两个指标是否同向变化？',note:'只说明同向/反向，不说明因果',method:'correlation',metrics:['gold','damage'],dimension:'label'},
  {key:'cluster',title:'找相似',question:'哪些选手或英雄的表现接近？',note:'按多项指标分组，不是能力评级',method:'cluster',metrics:['gold','damage','participation'],dimension:'label'},
 ];
 const activeScenario=scenarios.find(s=>s.method===selectedMethod);
 const initialDimension=activeScenario?.dimension||'hero';
 const initialGroupKeys=preview.groupValues[initialDimension]||groupKeys;
 const scenarioCards=scenarios.map(s=>`<button class="scenario-card ${s.method===selectedMethod?'active':''}" data-scenario="${s.key}" data-method="${s.method}" data-metrics="${s.metrics.join(',')}" data-dimension="${s.dimension}"><span>${esc(s.question)}</span><strong>${esc(s.title)}</strong><p>${esc(s.note)}</p><em>运行 →</em></button>`).join('');
 const configHtml=`<section class="lab-config"><h3>分析设置</h3><label class="field">数据集<select id="lab-dataset"><option value="records"${datasetName==='records'?' selected':''}>比赛记录</option><option value="screenshots"${datasetName==='screenshots'?' selected':''}>截图候选 · 单独探索</option>${(workspace.datasets||[]).map(d=>`<option value="prepared:${d.id}"${datasetName==='prepared:'+d.id?' selected':''}>${esc(d.title)}</option>`).join('')}</select></label><label class="field">分析方法<select id="lab-method">${availableMethods.map(m=>`<option value="${m.key}"${selectedMethod===m.key?' selected':''}>${esc(m.name)}</option>`).join('')}</select></label><label class="field">分组字段<select id="lab-dimension">${workspace.dimensions.map(d=>`<option value="${d.key}"${d.key===initialDimension?' selected':''}>${esc(d.label)}</option>`).join('')}</select></label><div class="label-row"><span class="subtle-heading">分析指标</span><span class="note">最多 8 项</span></div><div class="metric-options">${workspace.metrics.map(m=>`<label class="check"><input type="checkbox" name="metric" value="${m.key}"${selectedMetrics.includes(m.key)?' checked':''}>${esc(m.label)}</label>`).join('')}</div><label class="field" id="regression-settings"${selectedMethod==='regression'?'':' hidden'}>目标指标<select id="lab-target">${selectedMetrics.map((k,i)=>`<option value="${k}"${i===selectedMetrics.length-1?' selected':''}>${esc(workspace.metrics.find(m=>m.key===k).label)}</option>`).join('')}</select></label><div id="compare-settings"${selectedMethod==='compare'?'':' hidden'}><label class="field">A 组<select id="lab-group-a">${initialGroupKeys.map(g=>`<option>${esc(g)}</option>`).join('')}</select></label><label class="field">B 组<select id="lab-group-b">${initialGroupKeys.map((g,i)=>`<option${i===1?' selected':''}>${esc(g)}</option>`).join('')}</select></label></div><label class="field" id="cluster-settings"${selectedMethod==='cluster'?'':' hidden'}>聚类数<select id="lab-clusters">${[2,3,4,5,6].map(v=>`<option${v===3?' selected':''}>${v}</option>`).join('')}</select></label><hr><label class="check"><input type="checkbox" id="lab-dedup" checked>折叠内容相同的记录</label><p class="note">仅影响本次计算，不修改原始数据。</p><button class="button primary" id="run-analysis">运行分析 ${icon('arrow')}</button></section>`;
 $('#content').innerHTML=heading(inModels?'模型实验':'统计实验',inModels?'先选一个建模问题；默认用时间留出验证，需要时再展开高级设置。':'先选一个分析问题。平台自动带入数据集、指标和方法；需要时再展开高级设置。',`<a class="button" href="#reports">分析报告 ${icon('arrow')}</a>`)
 +`<section class="panel lab-scenarios"><div class="panel-head"><div><h2>你想回答什么？</h2><p>点一张卡直接运行；默认使用全部已确认比赛，结果保留样本和条件。</p></div>${pill(`${preview.total} 行 · ${preview.matches} 组`,'neutral')}</div><div class="panel-body"><div class="scenario-grid">${scenarioCards}</div><p class="note">当前数据：${datasetName==='records'?'比赛记录与表格':datasetName==='screenshots'?'截图候选':'已选数据集'}；在高级设置里可以换数据集、方法、指标和分组。</p></div></section>`
 +`<section class="panel" id="result-panel"><div class="panel-head"><div><h2 id="method-title">${esc(method.name)}</h2><p id="method-description">${esc(method.description)}</p></div>${pill('本机计算')}</div><div id="result-output"><div class="result-placeholder">正在准备默认分析…</div></div></section>`
 +`<details class="panel lab-advanced"><summary>高级设置：数据集、方法、指标、分组</summary><div class="lab-advanced-body">${filtersHtml()}${configHtml}</div></details>`
 +`<details class="panel lab-sample"><summary>查看本次样本（${preview.total} 行 · ${preview.matches} 组内容）</summary><div class="panel-body">${table(preview.rows,['label','hero','date',...selectedMetrics.slice(0,3),'partial','matchKey'],{limit:12})}</div></details>`
 +`<p class="dataset-label">${datasetName==='screenshots'?'截图候选与比赛记录隔离，未进入正式统计。':'来源：已确认比赛、比赛数据包；按筛选决定是否包含表格和部分记录。'}</p>`;
 currentResult=null;currentSpec=null;
 const setMethodUi=()=>{const m=workspace.methods.find(x=>x.key===selectedMethod);if(m){$('#method-title').textContent=m.name;$('#method-description').textContent=m.description;}$('#compare-settings').hidden=selectedMethod!=='compare';$('#cluster-settings').hidden=selectedMethod!=='cluster';$('#regression-settings').hidden=selectedMethod!=='regression';document.querySelectorAll('[data-scenario]').forEach(item=>item.classList.toggle('active',item.dataset.method===selectedMethod));};
 $('#lab-dataset').onchange=()=>{datasetName=$('#lab-dataset').value;render();};
 $('#lab-method').onchange=()=>{selectedMethod=$('#lab-method').value;setMethodUi();invalidateResult();};
 $('#lab-dimension').onchange=updateGroups;
 $('#lab-dedup').onchange=invalidateResult;
 document.querySelectorAll('input[name=metric]').forEach(el=>el.onchange=()=>{selectedMetrics=[...document.querySelectorAll('input[name=metric]:checked')].map(e=>e.value);$('#lab-target').innerHTML=selectedMetrics.map((k,i)=>`<option value="${k}"${i===selectedMetrics.length-1?' selected':''}>${esc(workspace.metrics.find(m=>m.key===k).label)}</option>`).join('');invalidateResult();});
 $('#lab-target').onchange=invalidateResult;$('#lab-group-a').onchange=invalidateResult;$('#lab-group-b').onchange=invalidateResult;$('#lab-clusters').onchange=invalidateResult;
 $('#run-analysis').onclick=runLab;
 document.querySelectorAll('[data-scenario]').forEach(card=>card.onclick=()=>{selectedMethod=card.dataset.method;selectedMetrics=card.dataset.metrics.split(',').filter(Boolean);$('#lab-method').value=selectedMethod;document.querySelectorAll('input[name=metric]').forEach(el=>el.checked=selectedMetrics.includes(el.value));$('#lab-dimension').value=card.dataset.dimension||'label';updateGroups();$('#lab-target').innerHTML=selectedMetrics.map((k,i)=>`<option value="${k}"${i===selectedMetrics.length-1?' selected':''}>${esc(workspace.metrics.find(m=>m.key===k).label)}</option>`).join('');setMethodUi();runLab();});
 runLab();
}
function invalidateResult(){analysisSerial++;currentResult=null;currentSpec=null;$('#save-result')?.remove();$('#result-output').innerHTML='<div class="result-placeholder"><p>分析设置已变化。运行后查看结果。</p></div>';}
function updateGroups(){const dimension=$('#lab-dimension').value;const groups=preview.groupValues[dimension] || [];for(const [i,id] of ['lab-group-a','lab-group-b'].entries())$('#'+id).innerHTML=groups.map((g,j)=>`<option${j===i?' selected':''}>${esc(g)}</option>`).join('');invalidateResult();}
async function runLab() {
 const el=$('#run-analysis'),serial=++analysisSerial,requestGeneration=generation;el.disabled=true;el.textContent='正在计算…';
 const spec={dataset:datasetName,filters:{...filters},method:$('#lab-method').value,metrics:[...document.querySelectorAll('input[name=metric]:checked')].map(e=>e.value),dimension:$('#lab-dimension').value,groupA:$('#lab-group-a').value,groupB:$('#lab-group-b').value,clusters:Number($('#lab-clusters').value),deduplicate:$('#lab-dedup').checked};
 if(spec.method==='regression'){const target=$('#lab-target').value;spec.metrics=[...spec.metrics.filter(k=>k!==target),target];}try{const result=await api('/api/studio/run',spec);if(!$('#result-output')||serial!==analysisSerial||requestGeneration!==generation)return;currentResult=result;currentSpec=spec;const canSave=result.status==='ok'&&hasResultContent(result);$('#result-output').innerHTML=resultHtml(result)+(canSave?saveForm():'');if(canSave)$('#save-result').onclick=saveResult;}
 catch(error){toast(error.message,true);}finally{if(el.isConnected){el.disabled=false;el.innerHTML='运行分析 '+icon('arrow');}}
}
function hasResultContent(result){return Boolean(result?.rows?.length||result?.coefficients?.length||result?.members?.length);}
function resultHtml(result){
 const meta=result.meta;
 let content=`<div class="result-meta"><span><strong>${n(meta.rows,0)}</strong> 行</span><span><strong>${n(meta.matches,0)}</strong> 场记录</span><span>${meta.duplicates.length} 份内容折叠</span><span title="用于确认源数据未变化">数据版本 ${meta.fingerprint.slice(0,10)}</span></div>`;
 if(result.status!=='ok')return content+empty('当前样本还不能计算这项结果',result.reason,'','')+`<div class="result-note">所需门槛：${esc(result.required)} · 当前可用：${esc(result.available)}。可以切换统计方法，先检查分布与字段覆盖。</div>`;
 if(result.distribution?.length)content+=histogram(result.distribution,workspace.metrics.find(m=>m.key===meta.metrics[0]));if(['trend','anomaly'].includes(meta.method))content+=chart(result.rows.map((r,i)=>({x:i+1,y:r.value,matchKey:r.matchKey})), 'line','比赛顺序',workspace.metrics.find(m=>m.key===meta.metrics[0]).label);
 if(result.points?.length){const pca=meta.method==='pca';content+=chart(result.points,'scatter',pca?'主成分 1':workspace.metrics.find(m=>m.key===meta.metrics[0]).label,pca?'主成分 2':workspace.metrics.find(m=>m.key===meta.metrics[1]).label,'选手单局');}
 if(result.variance)content+=`<div class="result-note">主成分 1 解释 ${n(result.variance[0])}% 方差，主成分 2 解释 ${n(result.variance[1])}% 方差。</div>`;
 if(result.summary)content+=`<div class="result-meta">${Object.entries(result.summary).map(([k,v])=>`<span>${esc(k)} <strong>${n(v,1)}</strong></span>`).join('')}</div>`;content+=table(result.rows,result.columns,{emptyTitle:'本次没有满足条件的条目',emptyText:'方法已执行；没有达到规则频次或有效值要求的结果。',limit:25});
 if(result.coefficients)content+=table(result.coefficients,['metric','weight']);
 if(result.members)content+=`<details class="panel-body"><summary class="note">查看分组成员（${result.members.length} 行）</summary>${table(result.members,['label','hero','cluster','matchKey'])}</details>`;
 content+=`<div class="result-note">${esc(result.note || '缺失值逐指标剔除；每项结果保留各自有效行数。')}<br>${meta.warnings.map(esc).join('<br>')}</div>${hasResultContent(result)?`<div class="panel-body"><button class="button" data-export-result>导出结果 CSV ${icon('download')}</button></div>`:''}`;
 return content;
}
function saveForm(){return `<div class="report-form" id="save-form"><label class="field">报告标题<input id="report-title" maxlength="120" placeholder="如：近期发育与输出关系"></label><label class="field">观察与下一步<textarea id="report-note" maxlength="4000" placeholder="记录观察、待核实原因和后续训练安排"></textarea></label><button class="button primary" id="save-result">保存记录</button></div>`;}
async function saveResult(){const el=$('#save-result');el.disabled=true;try{await api('/api/studio/reports',{title:$('#report-title').value,note:$('#report-note').value,spec:currentSpec,fingerprint:currentResult.meta.fingerprint});toast('分析报告已保存');}catch(error){toast(error.message,true);}finally{el.disabled=false;}}

async function topicsPage(token){
 const options=workspace.topics||[];if(!options.length)return;
 const routed=location.hash.split('/')[1]||'hero_pool';selectedTopic=options.some(t=>t.key===routed)?routed:'hero_pool';const activeTopic=options.find(t=>t.key===selectedTopic);
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">${esc(stageFor('topics')[0])} · 深入分析</span><h1>${esc(activeTopic.name)}</h1><p>${esc(activeTopic.description)}</p><div class="page-facts"><span>${esc(stageFor('topics')[0])}分析</span><span>当前 ${workspace.overview.rows} 行</span><span>${workspace.overview.matches} 组内容</span></div></div><a class="button" href="#reports">分析报告 ${icon('arrow')}</a></div>`
 +`<section class="panel topic-picker"><div class="panel-body"><div class="topic-controls"><label class="field">数据集<select id="topic-dataset"><option value="records">比赛记录与表格</option><option value="screenshots">截图候选</option>${(workspace.datasets||[]).map(d=>`<option value="prepared:${d.id}">${esc(d.title)}</option>`).join('')}</select></label><label class="field">指标<select id="topic-metric">${workspace.metrics.map(m=>`<option value="${m.key}"${m.key==='damage'?' selected':''}>${esc(m.label)}</option>`).join('')}</select></label><label class="check"><input type="checkbox" id="topic-partial" checked>包含部分记录</label><button class="button primary" id="topic-run">更新分析</button></div></div></section><section class="panel" id="topic-result"><div class="result-placeholder">正在检查分析所需字段；缺少身份或过程信息时会列出条件。</div></section>`;
 if([...$('#topic-dataset').options].some(o=>o.value===datasetName))$('#topic-dataset').value=datasetName;
 const runTopic=async()=>{const button=$('#topic-run');button.disabled=true;const spec={dataset:$('#topic-dataset').value,topic:selectedTopic,metric:$('#topic-metric').value,filters:{sources:['db','bundle','sheet'],includePartial:$('#topic-partial').checked}};try{const result=await api('/api/studio/research',spec);if(token!==generation)return;currentResult=result;currentSpec=spec;const canSave=result.status==='ok'&&hasResultContent(result);$('#topic-result').innerHTML=`<div class="panel-head"><div><h2>${esc(options.find(t=>t.key===spec.topic).name)}</h2><p>${esc(options.find(t=>t.key===spec.topic).description)}</p></div></div>`+resultHtml(result)+(canSave?saveForm():'')+`<div class="result-note">分析设计参考 <a href="https://github.com/hccccc01333/kpl-research" target="_blank" rel="noopener">KPL 赛研</a> · 训练赛字段适配</div>`;if(canSave)$('#save-result').onclick=saveResult;}catch(error){toast(error.message,true);}finally{if(button.isConnected)button.disabled=false;}};
 $('#topic-run').onclick=runTopic;
 $('#topic-run').click();
}
async function identityPage(token){
 let data,state;
 try{[data,state]=await Promise.all([api('/api/studio/identity'),api('/api/state')]);}catch(error){if(token!==generation)return;$('#content').innerHTML=heading('身份绑定','读取失败：'+error.message);return;}
 if(token!==generation)return;
 const roster=state.settings?.roster||[];
 const aliases=data.aliases||{};
 const unbound=data.unbound||[];
 const rosterNames=new Set(roster.map(player=>player.name));
 const identities=data.identities||unbound;
 const matchTeams=data.matchTeams||[];
 const teamPresetOptions=teamName=>{
  const custom=teamName&&!kplTeams.includes(teamName);
  return `<option value="__custom__"${!teamName?' selected':''}>＋ 自定义战队（在下一栏填写）</option>`
   +(custom?`<option value="${esc(teamName)}" selected>${esc(teamName)} · 我的自定义战队</option>`:'')
   +kplTeams.map(name=>`<option${name===teamName?' selected':''}>${esc(name)}</option>`).join('');
 };
 const groupedOwnLabels=new Set(matchTeams.flatMap(match=>(match.sides||[]).filter(side=>side.isOwn).flatMap(side=>(side.players||[]).map(player=>player.label))));
 const labels=[...unbound.map(item=>item.label),...Object.keys(aliases).filter(label=>!unbound.some(item=>item.label===label))];
 const crossLabels=labels.filter(label=>!groupedOwnLabels.has(label));
 const options=(label,boundId='')=>`<option value="">不绑定</option>${roster.map(player=>`<option value="${esc(player.id)}"${(aliases[label]||boundId)===player.id?' selected':''}>${esc(player.name)} · ${esc(player.position||'分路未设')}</option>`).join('')}`;
 const rows=crossLabels.map(label=>{
  const item=identities.find(value=>value.label===label)||{label,rows:null,matches:null,heroes:[],lastDate:''};
  const canCreate=!rosterNames.has(label)&&!aliases[label];
  return `<tr><td class="main-cell">${esc(label)}<div class="note">${aliases[label]?'已绑定别名':'待确认身份'}</div></td><td>${n(item.rows,0)}</td><td>${n(item.matches,0)}</td><td>${esc((item.heroes||[]).slice(0,4).join(' / '))}</td><td>${esc(item.lastDate||'—')}</td><td><div class="identity-target"><select class="alias-select" data-alias-label="${esc(label)}">${options(label)}</select>${canCreate?`<button class="text-link identity-create" data-create-player="${esc(label)}">创建为队员</button>`:''}</div></td></tr>`;
 }).join('');
 const teamPanels=matchTeams.map(match=>{
  const rosterName=playerId=>roster.find(player=>player.id===playerId)?.name||'已绑定';
  const sides=(match.sides||[]).map(side=>{
   const playerRows=(side.players||[]).map((player,index)=>{
    const label=player.label;
    const boundId=aliases[label]||player.playerId||'';
    const canCreate=side.isOwn&&!rosterNames.has(label)&&!aliases[label]&&!player.playerId;
    return `<div class="identity-team-player"><span class="identity-team-index">${index+1}</span><div class="identity-team-name"><strong>${esc(label)}</strong><small>${esc(player.hero||'英雄待确认')}${boundId?` · 已绑定 ${esc(rosterName(boundId))}`:''}</small></div>${side.isOwn?`<select class="alias-select" data-alias-label="${esc(label)}">${options(label,player.playerId)}</select>${canCreate?`<button class="text-link identity-create" data-create-player="${esc(label)}">创建为队员</button>`:''}`:'<span class="tag gray">对手选手</span>'}</div>`;
   }).join('');
   const role=side.isOwn?'本队':(match.ownCamp?'对手':'待确认阵营');
   return `<div class="identity-team ${side.isOwn?'own':'opponent'}"><div class="identity-team-head"><div><strong>${esc(side.teamName||role)}</strong><small>${role} · ${side.side==='left'?'蓝方 / 左侧':'红方 / 右侧'} · ${(side.players||[]).length} 人</small></div><span class="tag ${side.isOwn?'blue':'gray'}">${role}</span></div><div class="identity-team-list">${playerRows}</div></div>`;
  }).join('');
  return `<article class="identity-match"><div class="identity-match-head"><strong>${esc(match.date||'日期待补')} · ${esc(match.title||'训练赛')}</strong><span>${esc(match.opponent?'vs '+match.opponent:'对手待填写')}</span></div><div class="identity-team-grid">${sides}</div></article>`;
 }).join('');
 const collectAliases=()=>{const next={};document.querySelectorAll('[data-alias-label]').forEach(select=>{if(select.value)next[select.dataset.aliasLabel]=select.value;});return next;};
 const saveIdentity=async(nextRoster,nextAliases)=>{
  const grouped=new Map();for(const item of identities){const id=nextAliases[item.label]||nextRoster.find(p=>p.name===item.label)?.id;if(!id)continue;for(const key of item.matchKeys||[]){const token=id+':'+key;const previous=grouped.get(token);if(previous&&previous!==item.label)throw Error('绑定冲突：'+previous+' 与 '+item.label+' 在同一局出场，不能绑定为同一选手');grouped.set(token,item.label);}}

  const response=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...state.settings,teamName:$('#identity-team-name').value.trim(),roster:nextRoster,aliases:nextAliases})});
  const result=await response.json();if(!response.ok)throw Error(result.detail||'保存失败');
  await fetch('/api/analysis/reload',{method:'POST'});toast('身份绑定已保存');render();
 };
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">IDENTITY · 身份绑定</span><h1>身份绑定</h1><p>系统按每局左右方把十名选手自动分成两队；本队昵称绑定到自己的名单，对手昵称单独保留。只影响分析视图，不修改原始比赛。</p><div class="page-facts"><span>${unbound.length} 个未绑定昵称</span><span>${Object.keys(aliases).length} 个已绑定别名</span><span>${roster.length} 名队员</span></div></div><div class="heading-actions"><a class="button" href="#roster">战队名单</a><button class="button primary" id="identity-save" >保存绑定与分路</button></div></div>`
 + (teamPanels?`<section class="panel identity-teams-panel"><div class="panel-head"><div><h2>本局十人 · 按左右方自动分组</h2><p>本队与对手各五人；只有本队昵称需要绑定到名单，对手昵称不会混入本队统计。</p></div><span class="pill">最近 ${matchTeams.length} 局</span></div><div class="panel-body">${teamPanels}</div></section>`:'')
 + `<section class="panel"><div class="panel-head"><div><h2>所属战队与默认分路</h2><p>选择内置战队，或选择“自定义战队”后填写自己的队名。分路作为录入建议，每局实际分路仍需确认。</p></div></div><div class="panel-body"><div class="form-grid"><label class="field">战队选择<select id="identity-team-preset">${teamPresetOptions(state.settings.teamName)}</select></label><label class="field">战队名称<input id="identity-team-name" maxlength="50" value="${esc(state.settings.teamName)}"></label></div><p class="note"><a href="${teamPresetSource}" target="_blank" rel="noopener">${teamPresetLabel}</a></p><div class="identity-lanes">${roster.map(player=>`<label class="field">${esc(player.name)}<select data-identity-lane="${esc(player.id)}"><option value="">待确认</option>${lanes.map(lane=>`<option${lane===player.position?' selected':''}>${lane}</option>`).join('')}</select></label>`).join('')}</div></div></section>`
 + (crossLabels.length?`<section class="panel"><div class="panel-head"><div><h2>跨局昵称与历史别名</h2><p>这些昵称不在最近五局的分组里；同一选手可有多个历史昵称，同局出场的不同昵称不能合并。</p></div><span class="pill">${crossLabels.length} 个昵称</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>昵称</th><th>行数</th><th>比赛数</th><th>常用英雄</th><th>最近日期</th><th>绑定到</th></tr></thead><tbody>${rows}</tbody></table></div></section>`:(!teamPanels&&!labels.length?`<section class="panel"><div class="empty-state"><strong>没有未绑定昵称</strong>当前比赛记录的队员身份都已绑定，或还没有可分析的记录。<br><a href="#matches">查看比赛档案 →</a></div></section>`:''))
 + (roster.length?`<p class="note">绑定后分析页会按稳定选手 ID 合并记录；原始昵称仍保留在比赛记录中。</p>`:`<p class="note">当前没有队员名单，可直接点击昵称后的“创建为队员”；也可以先到 <a href="#roster">战队名单</a> 批量建立。</p>`);
 const actionBar=document.createElement('div');actionBar.className='identity-save-bar';actionBar.innerHTML='<span>确认昵称归属后统一保存；同局身份冲突会阻止保存。</span><button class="button primary" type="button">保存绑定与分路</button>';$('#content').append(actionBar);actionBar.querySelector('button').onclick=()=>$('#identity-save').click();
 $('#identity-team-preset').onchange=()=>{const value=$('#identity-team-preset').value;if(value==='__custom__'){$('#identity-team-name').focus();$('#identity-team-name').select();return;}if(value)$('#identity-team-name').value=value;};
 const rosterWithLanes=()=>roster.map(player=>({...player,position:document.querySelector(`[data-identity-lane="${CSS.escape(player.id)}"]`)?.value||''}));
 $('#identity-save').onclick=async()=>{
  const button=$('#identity-save');button.disabled=true;
  const next={};document.querySelectorAll('[data-alias-label]').forEach(select=>{if(select.value)next[select.dataset.aliasLabel]=select.value;});
  try{await saveIdentity(rosterWithLanes(),next);}catch(error){toast(error.message,true);button.disabled=false;}
 };
 document.querySelectorAll('[data-create-player]').forEach(button=>button.onclick=async()=>{
  const label=button.dataset.createPlayer;button.disabled=true;
  const id=`local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,6)}`;
  try{await saveIdentity([...rosterWithLanes(),{id,name:label,position:''}],{...collectAliases(),[label]:id});}catch(error){toast(error.message,true);button.disabled=false;}
 });
}

async function reportsPage(token){
 const d=await api('/api/studio/reports');if(token!==generation)return;
 const list=d.reports||[];
 const totalMatches=list.reduce((sum,item)=>sum+Number(item.matches||0),0);
 const methods=new Set(list.map(item=>item.method)).size;
 const methodName=item=>workspace.methods.find(m=>m.key===item.method)?.name||workspace.topics?.find(t=>'topic:'+t.key===item.method)?.name||item.method;
 const cards=list.map(item=>`<article class="research-card"><div class="research-card-top"><span class="research-badge">${esc(methodName(item))}</span><span class="research-date">${esc(new Date(item.createdAt).toLocaleString('zh-CN'))}</span></div><h3><button class="text-link" data-report="${item.id}">${esc(item.title)}</button></h3><div class="research-stats"><span><b>${item.matches}</b> 场记录</span></div><div class="research-actions"><button class="button" data-report="${item.id}">查看记录</button><a class="button" href="/api/studio/reports/${item.id}/export" target="_blank" rel="noopener">导出 HTML</a></div></article>`).join('');
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">RESEARCH · 分析报告</span><h1>分析报告</h1><p>保存分析设置、结果快照和观察，之后按同一口径复查。</p><div class="page-facts"><span>${list.length} 条记录</span><span>${totalMatches} 场记录</span><span>${methods} 种方法</span></div></div><div class="heading-actions"><a class="button" href="/api/studio/backup">备份记录</a><button class="button" id="restore-research">恢复备份</button><input type="file" id="research-file" accept=".json" hidden><a class="button primary" href="#lab">新建分析 ${icon('arrow')}</a></div></div>`
 + (list.length?`<div class="research-card-grid">${cards}</div>`:`<section class="panel"><div class="empty-state"><strong>还没有保存的分析报告</strong>在统计实验运行结果后，填写标题和观察即可保存。<br><a href="#lab">进入统计实验 →</a></div></section>`)
 + `<p class="note">分析报告保存当时的数据快照与筛选条件。源数据后续修改不会覆盖历史结果；本页备份包含研究结果和清洗数据集。</p>`;
 $('#restore-research').onclick=()=>$('#research-file').click();
 $('#research-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>20*1024*1024)return toast('备份文件应小于 20 MB',true);try{const response=await fetch('/api/studio/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:await f.text()});const r=await response.json();if(!response.ok)throw Error(typeof r.detail==='string'?r.detail:'恢复失败');toast(`已恢复 ${r.added} 条，跳过已有 ${r.skipped} 条`);render();}catch(err){toast(err.message,true);}};
}
async function showReport(id){const report=await api('/api/studio/reports/'+encodeURIComponent(id));currentResult=report.result;currentSpec=report.result.spec;$('#detail-title').textContent=report.title;$('#detail-body').innerHTML=`<p class="inline-summary">${esc(report.note)}</p>`+resultHtml(report.result);$('#detail-dialog').showModal();}
function sourcesPage(){
 const rows=workspace.overview.rows;
 $('#content').innerHTML=heading('字段与来源','查看四类原料、字段覆盖与记录关联，保留原始证据。',`<a class="button primary" href="#channels">采集通道 ${icon('arrow')}</a>`)
 +`<div class="source-grid">${[['表格','单局明细、团队统计与自定义赛训记录。','#channels','放入表格'],['赛后截图','KDA、发育、输出、生存和团队字段。','#screenshots','查看截图'],['回放录屏','团队时间轴、记分板快照及 POV 片段。','#recordings','查看录屏'],['回放文件','十人名单、英雄、评分与版本信息。','#replays','查看回放']].map(([t,d,u,a])=>`<section class="source-box"><h2>${t}</h2><p>${d}</p><a href="${u}">${a} ↗</a></section>`).join('')}</div>`
 +`<div class="data-quality">${panel('记录关联','保留文件，不在源数据上直接合并',workspace.duplicates.length?table(workspace.duplicates,['excluded','retained']):'<p class="note">未发现字段内容完全相同的比赛记录。</p>')}${panel('统计口径','分析时保留样本、来源与适用范围',`<dl class="definition"><dt>比赛记录与截图候选</dt><dd>分别选择、分别计算；候选字段不混入确认记录。</dd><dt>完整终局与过程片段</dt><dd>默认排除部分行。完整时长缺失时不计算分均指标。</dd><dt>研究与预测</dt><dd>相关性、聚类与模型系数用于研究；赛前模型只输入已选阵容，并按时间留出比赛。</dd></dl>`)}</div>`
 +`<div class="section-heading"><h2>指标字典</h2><span class="note">当前数据共 ${rows} 行</span></div><section class="panel">${table(workspace.metrics.map(m=>({...m,metric:m.label})),['metric','key','unit','available','complete'])}</section>`;
}
async function matchDetail(key){if(key.startsWith('capture-'))return captureDetail(key);const d=await api('/api/studio/match/'+encodeURIComponent(key));$('#detail-title').textContent=(d.opponent?'vs '+d.opponent:d.title || '比赛详情')+' · '+(d.date || '日期待确认');let body=`<div class="inline-summary">${pill(resultNames[d.result] || '待确认','neutral')} <span class="key-pill">${esc(d.key)}</span> · ${esc((d.sources||[]).map(s=>sourceNames[s] || s).join(' / '))}</div>`;
 body+=table(d.players.map(p=>({...p,partial:p.partial})),['label','hero','camp','kills','deaths','assists','gold','damage','taken','participation','rating','partial']);
 const timeline=d.process?.timeline || [];
 if(timeline.length){body+='<div class="section-heading"><h2>团队经济差</h2></div>'+chart(timeline.filter(p=>p.blueGold!==null&&p.blueGold!==undefined&&p.redGold!==null&&p.redGold!==undefined).map(p=>({x:p.gameTime/60,y:p.blueGold-p.redGold})), 'line','局内时间（分钟）','经济差（金币）','蓝方经济 − 红方经济');}
 if(d.process?.scoreboardSnapshots?.length)body+=`<details><summary class="note">记分板快照 · ${d.process.scoreboardSnapshots.length} 份</summary><div class="note">过程快照保留于单局数据包，可在原分析页查看逐时内容。</div></details>`;
 if(d.warnings?.length)body+=notice(d.warnings.map(esc).join('<br>'));
 if(d.dbId)body+=`<a class="button" href="#review/${encodeURIComponent(d.dbId)}">打开原始复盘记录 ↗</a>`;
 body+=`<div class="panel-body"><a class="text-link" href="#stats">查看全部复盘专题 ↗</a></div>`;
 $('#detail-body').innerHTML=body;$('#detail-dialog').showModal();
}
async function captureDetail(key){const d=await api('/api/studio/capture/'+encodeURIComponent(key));$('#detail-title').textContent='截图候选 · 原始证据';$('#detail-body').innerHTML=notice('这些字段来自截图识别，尚未确认选手与本队身份。')+table(d.rows,['label','hero','camp','kills','deaths','assists','gold','damage','taken','rating'])+d.images.map(id=>`<a href="/api/images/${encodeURIComponent(id)}" target="_blank" rel="noopener"><img src="/api/images/${encodeURIComponent(id)}" alt="原始赛后截图" style="width:100%;height:auto;margin-top:16px"></a>`).join('');$('#detail-dialog').showModal();}
function exportCsv(){if(!currentResult?.rows?.length)return toast('当前没有可导出的结果',true);const keys=currentResult.columns;const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';const csv='\ufeff'+[keys.map(k=>quote(names[k] || k)).join(','),...currentResult.rows.map(r=>keys.map(k=>quote(typeof r[k]==='string'&&/^[=+@\-\t\r]/.test(r[k])?"'"+r[k]:r[k])).join(','))].join('\r\n');download(new Blob([csv],{type:'text/csv;charset=utf-8'}),'训练室-分析结果.csv');}
function download(blob,name){const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}

async function render(){
 const hash=location.hash.slice(1)||'overview';if(!allowWorkbenchNavigation(hash))return;
 if(hash.startsWith('panorama/')){location.replace('#match/'+hash.slice('panorama/'.length));return;}
 const token=++generation,page=pageName();if(!workspace)return;disposeAnalysisVisuals();disposePanorama();
 if(!nativePages.has(page))deactivateWorkbench();
 document.body.classList.toggle('analysis-mode',['players','heroes','player','hero','compare','team','match','bp','combos','topics','lab','models'].includes(page));document.body.classList.toggle('desk-mode',page==='desk');$('#content').classList.toggle('workbench',nativePages.has(page));
 updateNavigation(page);
 const label=labelFor(page);$('#breadcrumb').innerHTML=`<a href="#overview">首页</a>${page!=='overview'?`<span>/</span><a href="#${stageFor(page)[1][0][0]}">${esc(stageFor(page)[0])}</a>${label!==stageFor(page)[0]?`<span>/</span><strong>${esc(label)}</strong>`:''}`:'<span>/</span><strong>赛训总览</strong>'}`;if(page==='analysis')$('#breadcrumb').innerHTML='<a href="#overview">首页</a><span>/</span><strong>全部功能</strong>';document.title=label+' · 赛训分析';$('#content').innerHTML='<div class="loading">正在读取本地数据…</div>';
 try{
  if(workspaceDirty){const fresh=await api('/api/studio/workspace');if(token!==generation)return;workspace=fresh;workspaceDirty=false;}
  if(nativePages.has(page)){await renderWorkbench();if(page==='training'&&$('#content h1'))$('#content h1').textContent='训练跟踪';}
  else if(page==='overview')await renderHome($('#content'),{workspace,api,isCurrent:()=>token===generation,features:nav.map(([group,items])=>({group,items:items.map(([key,label])=>({key,label,description:navDescriptions[key]}))}))});
  else if(page==='capture')await renderCapture($('#content'),{api,toast,isCurrent:()=>token===generation});
  else if(page==='import')importPage(token);
  else if(page==='desk')await researchDesk(token);
  else if(page==='matches')await matchesPage(token);
  else if(page==='match')await matchPage(hash.split('/')[1],token);
   else if(page==='opponent')await renderOpponent($('#content'),{api,workspace,isCurrent:()=>token===generation,query,filters},decodeURIComponent(hash.split('/').slice(1).join('/')));
  else if(page==='featured')await renderFeatured($('#content'),{api,isCurrent:()=>token===generation,query});
  else if(page==='records')await renderRecords($('#content'),{api,isCurrent:()=>token===generation,query});
  else if(page==='bp')await renderBp($('#content'),{api,isCurrent:()=>token===generation,query});
  else if(page==='combos')await renderCombos($('#content'),{api,isCurrent:()=>token===generation,query});
  else if(page==='player')await entityPage('player',decodeURIComponent(hash.split('/').slice(1).join('/')),token);
  else if(page==='hero')await entityPage('hero',decodeURIComponent(hash.split('/').slice(1).join('/')),token);
  else if(page==='analysis')analysisPage();
  else if(page==='compare')await comparePage(token);
  else if(page==='players'||page==='heroes'){listTab=page;await playersPage(token);}
  else if(page==='team')await teamPage(token);
  else if(page==='lab'||page==='models')await labPage(token);
  else if(page==='topics')await topicsPage(token);
  else if(page==='clean')await renderPrepare($('#content'),{api,toast,isCurrent:()=>token===generation,workspace,onPublished:async()=>{workspace=await api('/api/studio/workspace');}});
  else if(page==='datasets')await renderDatasets($('#content'),{api,toast,isCurrent:()=>token===generation,onUse:(id,model)=>{datasetName='prepared:'+id;Object.assign(filters,{from:'',to:'',hero:'',player:'',opponent:'',includePartial:true});location.hash=model?'models':'lab';}});
  else if(page==='reports')await reportsPage(token);
  else if(page==='identity')await identityPage(token);
  else if(page==='sources')sourcesPage();
  else await researchDesk(token);
  if(token===generation && hash!==lastRenderedHash){window.scrollTo({top:0,behavior:'instant'});lastRenderedHash=hash;}
 }catch(error){if(token!==generation)return;$('#content').innerHTML=heading('数据读取失败',esc(error.message))+`<button class="button" id="retry">重新读取</button>`;$('#retry').onclick=render;}
}
document.addEventListener('click',async e=>{let target=e.target.closest('[data-method],[data-match],[data-team-tab],[data-report],[data-export-result],#apply-filters,#reset-filters');if(!target)return;if(target.dataset.match&&target.closest('#stats-body'))return;try{if(target.dataset.method){selectedMethod=target.dataset.method;if(['lab','models'].includes(pageName()))render();else location.hash='lab';}else if(target.dataset.match)await matchDetail(target.dataset.match);else if(target.dataset.report)await showReport(target.dataset.report);else if(target.dataset.teamTab){teamTab=target.dataset.teamTab;render();}else if(target.hasAttribute('data-export-result'))exportCsv();else if(target.id==='apply-filters'){readFilters();render();}else if(target.id==='reset-filters'){Object.assign(filters,{from:'',to:'',hero:'',player:'',opponent:'',version:'',sources:['db','bundle'],includePartial:false});render();}}catch(error){toast(error.message,true);}});
document.addEventListener('click',e=>{if(e.target.closest('[data-print]')){e.preventDefault();window.print();}});
$('#close-detail').onclick=()=>$('#detail-dialog').close();
$('#detail-dialog').addEventListener('click',e=>{if(e.target===$('#detail-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
function setupGlobalSearch(){
 const input=$('#global-search'),box=$('#global-search-results');if(!input||!box)return;
 const build=()=>{
  const items=[];
  nav.forEach(([group,list])=>list.forEach(([key,label])=>items.push({type:'功能',label,meta:group,href:'#'+key})));
  (workspace?.filters?.players||[]).forEach(player=>items.push({type:'选手',label:player.label,meta:player.bound?'已绑定名单':'未绑定',href:'#player/'+encodeURIComponent(player.label)}));
  (workspace?.filters?.heroes||[]).forEach(hero=>items.push({type:'英雄',label:hero,meta:'',href:'#hero/'+encodeURIComponent(hero)}));
  (workspace?.recent||[]).forEach(match=>items.push({type:'比赛',label:match.opponent?'vs '+match.opponent:match.title||match.key,meta:[match.date,match.session].filter(Boolean).join(' · '),href:'#match/'+encodeURIComponent(match.key)}));
  return items;
 };
 let searchSerial=0;
 const renderResults=items=>{
  box.innerHTML=items.length?items.map(item=>`<a class="search-result" href="${esc(item.href)}"><span class="search-type">${esc(item.type)}</span><strong>${esc(item.label)}</strong><small>${esc(item.meta||'')}</small></a>`).join(''):'<div class="search-empty">没有匹配的选手、英雄、比赛或功能。</div>';
  box.hidden=false;
 };
 const draw=async()=>{
  const raw=input.value.trim(),query=raw.toLowerCase();
  if(!query){box.hidden=true;box.innerHTML='';return;}
  const local=build().filter(item=>[item.type,item.label,item.meta].join(' ').toLowerCase().includes(query));
  renderResults(local.slice(0,12));
  const current=++searchSerial;
  try{
   const data=await api('/api/studio/view/matches?source=db,bundle,sheet&limit=8&q='+encodeURIComponent(raw));
   if(current!==searchSerial||input.value.trim()!==raw)return;
   const matches=(data.matches||[]).map(match=>({type:'比赛',label:match.opponent?'vs '+match.opponent:match.title||match.key,meta:[match.date,match.session].filter(Boolean).join(' · '),href:'#match/'+encodeURIComponent(match.key)}));
   renderResults([...local.filter(item=>item.type!=='比赛'),...matches].slice(0,12));
  }catch{/* 本地结果已经显示，网络失败时保留 */ }
 };
 input.addEventListener('input',draw);
 input.addEventListener('focus',draw);
 input.addEventListener('keydown',event=>{if(event.key==='Escape'){box.hidden=true;input.blur();}});
 box.addEventListener('click',event=>{if(event.target.closest('.search-result')){box.hidden=true;input.value='';}});
 document.addEventListener('click',event=>{if(!event.target.closest('.global-search'))box.hidden=true;});
}
document.addEventListener('click',event=>{
 const toggle=event.target.closest('.nav-menu-toggle');
 document.querySelectorAll('.nav-group.menu-open').forEach(group=>{if(group!==toggle?.parentElement){group.classList.remove('menu-open');group.querySelector('.nav-menu-toggle')?.setAttribute('aria-expanded','false');}});
 if(toggle){const open=toggle.parentElement.classList.toggle('menu-open');toggle.setAttribute('aria-expanded',String(open));}
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.nav-group.menu-open').forEach(group=>{group.classList.remove('menu-open');const button=group.querySelector('.nav-menu-toggle');button.setAttribute('aria-expanded','false');button.focus();});});
setupGlobalSearch();
updateNavigation(pageName());
$('#reload').onclick=async()=>{if(!allowWorkbenchNavigation('__refresh__'))return;const el=$('#reload');el.disabled=true;try{await api('/api/analysis/reload',{});workspace=await api('/api/studio/workspace');await render();toast('已重新读取本地数据');}catch(error){toast(error.message,true);}finally{el.disabled=false;}};
window.addEventListener('hashchange',()=>{const tools=document.querySelector('.project-tools');if(tools)tools.open=false;render();});
document.addEventListener('click',event=>{const tools=document.querySelector('.project-tools');if(tools&&!tools.contains(event.target))tools.open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){const tools=document.querySelector('.project-tools');if(tools?.open){tools.open=false;tools.querySelector('summary').focus();}}});
window.addEventListener('platform-data-changed',()=>{workspaceDirty=true;});
try{workspace=await api('/api/studio/workspace');await render();}catch(error){$('#content').innerHTML=heading('无法连接本地服务',error.message);}

document.addEventListener('keydown',e=>{const cell=e.target.closest?.('[data-desk-cell]');if(!cell||!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Enter'].includes(e.key))return;e.preventDefault();const [i,k]=cell.dataset.deskCell.split(':');const rows=deskGroups().get(deskSelected)||[];deskRow=Math.min(rows.length-1,Math.max(0,Number(i)+(e.key==='ArrowUp'?-1:e.key==='ArrowDown'?1:0)));const next=Math.min(deskColumns.length-1,Math.max(0,deskColumns.indexOf(k)+(e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:0)));deskMetric=deskColumns[next];renderDesk();document.querySelector('[data-desk-cell=\"'+deskRow+':'+deskMetric+'\"]')?.focus({preventScroll:true});});
