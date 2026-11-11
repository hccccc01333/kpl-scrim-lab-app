import { groupFor, groupLabel } from './navigation.js';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
/** V3 presentation for source-backed depth analyses. */
export function createDepth({esc,fmt,pct,table,icon}) {
  const safeTitles={cross_resource_output:'经济投入与输出分布',cross_lane_hero:'分路与英雄的补刀分布',cs_conversion:'补刀、经济与输出',space_heatmap:'位置热区与单局轨迹',space_deaths:'死亡位置分布',time_cross_match:'训练节奏与效率',time_events:'资源与事件分布',cross_teamfight_contribution:'团战贡献分布',death_point_economy:'掉点前后的经济变化',death_point_impact:'掉点窗口观察',equip_impact:'终局装备与表现对照',stability:'英雄表现波动',compare_baseline:'同位置数据参照',compare_camp:'蓝红阵营对照',resource_bp:'禁选与资源统计'};
  const labels={label:'对象',name:'名称',hero:'英雄',player:'选手',lane:'分路',n:'样本',games:'对局',count:'次数',value:'数值',mean:'均值',median:'中位数',p10:'P10',p25:'P25',p50:'P50',p75:'P75',p90:'P90',sd:'标准差',floor:'低值',blue:'蓝方',red:'红方',blueN:'蓝方样本',redN:'红方样本',deltaPct:'差异 %',depth:'推进深度',spread:'队形间距',crossings:'跨线次数',avgLoss:'平均差值',medianLoss:'中位差值',finalPct:'占比 %',phase:'阶段',pct:'占比 %',hurt:'输出',taken:'承伤',ctrl:'控制',kills:'击杀',deaths:'阵亡',assists:'助攻',start:'时间',duration:'时长',avgGpm:'平均分均经济',avgCs:'平均补刀',avgGold:'平均经济',withN:'携带样本',withoutN:'未携带样本',group:'分组',x:'横轴',y:'纵轴',t:'时间',id:'编号',camp:'阵营',result:'结果',towers:'防御塔',dragons:'资源',money:'经济',metric:'指标'};
  const text=v=>esc(v??'—');
  const nice=v=>typeof v==='number'?fmt(v,2):typeof v==='boolean'?(v?'是':'否'):Array.isArray(v)?v.map(nice).join('、'):v&&typeof v==='object'?Object.entries(v).map(([k,x])=>`${labels[k]||k}: ${nice(x)}`).join(' / '):text(v);
  const panel=(title,note,body)=>body?`<section class="section depth-panel"><div class="section-heading"><div><h2>${esc(title)}</h2><p>${esc(note||'')}</p></div></div>${body}</section>`:'';
  const number=v=>typeof v==='number'&&Number.isFinite(v);
  function scatter(points,xLabel,yLabel){
    const data=points.filter(p=>number(p.x)&&number(p.y)); if(!data.length)return '';
    const xmin=Math.min(...data.map(p=>p.x)),xmax=Math.max(...data.map(p=>p.x));
    const ymin=Math.min(...data.map(p=>p.y)),ymax=Math.max(...data.map(p=>p.y));
    const x=v=>60+(v-xmin)/(xmax-xmin||1)*590, y=v=>210-(v-ymin)/(ymax-ymin||1)*170;
    return `<div class="depth-chart"><svg viewBox="0 0 700 255" role="img" aria-label="${esc(xLabel)}与${esc(yLabel)}的散点图，${data.length} 个样本">
      ${[0,.25,.5,.75,1].map(t=>`<line x1="60" x2="650" y1="${210-170*t}" y2="${210-170*t}" class="grid-line"/><text x="50" y="${214-170*t}" text-anchor="end" class="axis-text">${fmt(ymin+(ymax-ymin)*t,1)}</text>`).join('')}
      ${data.map(p=>`<circle cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="3.5" class="depth-dot" tabindex="0"><title>${text(p.label||p.hero||'样本')} · ${text(xLabel)} ${fmt(p.x,2)} · ${text(yLabel)} ${fmt(p.y,2)}</title></circle>`).join('')}
      <text x="60" y="230" class="axis-text">${fmt(xmin,1)}</text><text x="650" y="230" text-anchor="end" class="axis-text">${fmt(xmax,1)}</text><text x="355" y="251" text-anchor="middle" class="axis-text">${text(xLabel)}</text></svg><div class="depth-chart-foot"><span>${text(yLabel)}</span><span>${data.length} 个有效样本 · 悬停或聚焦点查看</span></div></div>`;
  }
  function line(points,label){
    const data=(points||[]).filter(p=>Array.isArray(p)&&number(p[0])&&number(p[1])).sort((a,b)=>a[0]-b[0]);if(data.length<2)return '';
    const xmin=data[0][0],xmax=data.at(-1)[0],ymin=Math.min(0,...data.map(p=>p[1])),ymax=Math.max(0,...data.map(p=>p[1]));
    const x=v=>60+(v-xmin)/(xmax-xmin||1)*590,y=v=>200-(v-ymin)/(ymax-ymin||1)*160;
    const path=data.map((p,i)=>`${i?'L':'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    return `<div class="depth-chart"><svg viewBox="0 0 700 240" role="img" aria-label="${esc(label)}，${data.length} 个有效点">${[0,.5,1].map(t=>`<line x1="60" x2="650" y1="${200-160*t}" y2="${200-160*t}" class="grid-line"/><text x="49" y="${204-160*t}" text-anchor="end" class="axis-text">${fmt(ymin+(ymax-ymin)*t,1)}</text>`).join('')}<path d="${path}" class="curve"/>${data.map(p=>`<circle class="depth-dot" cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="3.4"><title>${fmt(p[0],1)} · ${fmt(p[1],2)}</title></circle>`).join('')}<text x="60" y="225" class="axis-text">${fmt(xmin,1)}</text><text x="650" y="225" text-anchor="end" class="axis-text">${fmt(xmax,1)}</text></svg><div class="depth-chart-foot"><span>${text(label)}</span><span>${data.length} 个采样点</span></div></div>`;
  }
  function heat(payload){
    const [low,high]=payload.bounds||[-60,60]; const all=payload.heat||[];const valid=all.filter(p=>number(p.x)&&number(p.y)&&number(p.n)&&p.x>=low&&p.x<=high&&p.y>=low&&p.y<=high);if(!valid.length)return '';
    const max=Math.max(...valid.map(p=>p.n),1);const x=v=>(v-low)/(high-low)*400,y=v=>400-(v-low)/(high-low)*400;
    return `<div class="heat-layout"><div class="map-board"><svg viewBox="0 0 400 400" role="img" aria-label="位置点聚合热区，${valid.length} 个有效网格"><path d="M0 400 400 0M-20 280 120 420M280 -20 420 120" class="map-guide"/>${valid.map(p=>`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="${Math.max(4,Math.sqrt(p.n/max)*20)}" fill="var(--heat)" opacity="${(.16+.64*p.n/max).toFixed(2)}"><title>网格 ${fmt(p.x)}, ${fmt(p.y)} · ${fmt(p.n)} 个点</title></circle>`).join('')}</svg></div><div class="heat-caption"><span class="eyebrow">位置分布</span><h3>观察活动区域</h3><p>圆点越大、颜色越深，表示该网格记录越多。底图为坐标示意，不代表游戏地图纹理。</p><div><i></i> 较少 <span class="heat-gradient"></span> 较多</div>${all.length>valid.length?`<p>排除 ${all.length-valid.length} 个超出地图范围的网格。</p>`:''}</div></div>`;
  }
  function tracks(payload){
    const [low,high]=payload.bounds||[-60,60];
    const x=v=>(v-low)/(high-low)*400,y=v=>400-(v-low)/(high-low)*400;
    const lines=(payload.tracks||[]).map(t=>({...t, valid:(t.points||[]).filter(p=>Array.isArray(p)&&number(p[0])&&number(p[1])&&p[0]>=low&&p[0]<=high&&p[1]>=low&&p[1]<=high)})).filter(t=>t.valid.length>=2);
    if(!lines.length)return '';
    return `<div class="heat-layout"><div class="map-board tracks-board"><svg viewBox="0 0 400 400" role="img" aria-label="所选对局 ${lines.length} 名选手的抽样轨迹"><path d="M0 400 400 0M-20 280 120 420M280 -20 420 120" class="map-guide"/>${lines.map(t=>`<polyline points="${t.valid.map(p=>`${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ')}" class="track-line ${t.camp==='蓝'?'blue':'red'}"><title>${text(t.label)} · ${text(t.camp)}方 · ${t.valid.length} 个采样点</title></polyline>`).join('')}</svg></div><div class="heat-caption"><span class="eyebrow">单局轨迹</span><h3>${text(payload.selectedLabel||'所选对局')}</h3><p>每条线代表一名选手的抽样位置；悬停线条可查看英雄。线条连接不表示逐帧运动。</p><div><span class="track-key blue"></span> 蓝方 <span class="track-key red"></span> 红方</div></div></div>`;
  }
  function matrix(p){
    if(!p.rows?.length||!p.cols?.length)return '';
    const vals=p.cells.flat().map(c=>typeof c==='object'?c?.value:c).filter(number);const max=Math.max(...vals.map(Math.abs),1);
    const cells=p.rows.map((row,i)=>`<span class="matrix-label">${text(row)}</span>${p.cols.map((col,j)=>{const cell=p.cells[i]?.[j],v=typeof cell==='object'?cell?.value:cell,n=typeof cell==='object'?cell?.n:null;return `<span class="matrix-cell" style="--cell-alpha:${number(v)?Math.min(.8,.1+Math.abs(v)/max*.7):0}" title="${esc(String(row)+' · '+String(col)+'：'+(number(v)?fmt(v,1):'无数据')+(n!=null?'，样本 '+n:''))}" aria-label="${esc(String(row)+'，'+String(col)+'，'+(number(v)?fmt(v,1):'无数据'))}"></span>`}).join('')}`).join('');
    const rows=p.rows.map((row,i)=>[text(row),...p.cols.map((_,j)=>{const cell=p.cells[i]?.[j];return nice(typeof cell==='object'?cell?.value:cell)})]);
    return `<div class="matrix-scroll"><div class="matrix-grid" style="--matrix-cols:${p.cols.length}"><span></span>${p.cols.map(c=>`<span class="matrix-col">${text(c)}</span>`).join('')}${cells}</div></div><p class="depth-note">${text(p.unit||'')} · 颜色越深表示数值越大，悬停色块可查看具体值和样本。</p>${table(['分组',...p.cols],rows)}`;
  }
  function objectTable(title,items){
    const list=items.filter(x=>x&&typeof x==='object'&&!Array.isArray(x));if(!list.length)return '';
    const keys=[...new Set(list.flatMap(x=>Object.keys(x)))].filter(k=>!['points','tracks','bound','id'].includes(k) && list.some(x=>x[k]!=null && (typeof x[k]!=='object'||Array.isArray(x[k])&&x[k].length<6||['metrics','deltas'].includes(k)))).slice(0,8);
    if(!keys.length)return '';
    const metric=['pct','value','avgLoss','medianLoss','mean','depth','count','n','avgGpm','blue','final','kills'].find(k=>keys.includes(k)&&list.some(x=>number(x[k])&&x[k]>=0));
    let visual='';
    if(metric){const samples=list.filter(x=>number(x[metric])&&x[metric]>=0).slice(0,8);const max=Math.max(1,...samples.map(x=>x[metric]));visual=`<div class="insight-bars">${samples.map((x,i)=>`<div><span>${text(x.label||x.hero||x.player||x.lane||x.phase||x.camp||x.game||('样本 '+(i+1)))}</span><div><i style="width:${x[metric]/max*100}%"></i></div><b>${fmt(x[metric],2)}</b></div>`).join('')}</div><p class="depth-note">${text(labels[metric]||metric)} · 展示前 ${samples.length} 项，条形长度按当前展示范围缩放。</p>`}
    else visual=`<div class="fact-grid">${list.slice(0,6).map((item,i)=>`<article><h3>${text(item.label||item.hero||item.player||item.lane||item.game||('记录 '+(i+1)))}</h3>${keys.filter(k=>!['label','hero','player','lane'].includes(k)).slice(0,4).map(k=>`<p><span>${text(labels[k]||k)}</span><b>${nice(item[k])}</b></p>`).join('')}</article>`).join('')}</div>`;
    return panel(title,`共 ${list.length} 条；空值不补零。`,visual+table(keys.map(k=>labels[k]||k),list.slice(0,80).map(row=>keys.map(k=>nice(row[k])))));
  }
  function output(result){
    const p=result.payload||{}, visual=[];
    if(p.heat?.length)visual.push(panel('空间分布',p.note||'',heat(p)));
    if(p.tracks?.length)visual.push(panel('单局走位轨迹','所选对局的抽样轨迹；可在上方切换对局。',tracks(p)));
    if(p.viz==='matrix')visual.push(panel('分布矩阵',p.note||'',matrix(p)));
    if(p.points?.some(x=>number(x.x)&&number(x.y)))visual.push(panel('样本分布',p.note||'',scatter(p.points,p.xLabel||'横轴',p.yLabel||'纵轴')));
    else if(p.viz==='fightscatter'&&p.points?.length)visual.push(panel('团战输出与承伤',p.note||'',scatter(p.points.map(x=>({...x,x:x.hurt,y:x.taken,label:x.hero})),'输出','承伤')));
    if(p.scatter?.points?.length)visual.push(panel('样本分布',p.note||'',scatter(p.scatter.points,p.scatter.xLabel||'横轴',p.scatter.yLabel||'纵轴')));
    for(const link of p.links||[])if(link.points?.length)visual.push(panel(link.title,`相关系数 ${number(link.corr)?fmt(link.corr,2):'不可用'}；相关不代表因果。`,scatter(link.points,link.xLabel||'横轴',link.yLabel||'纵轴')));
    if(p.series?.length)visual.push(panel('趋势',`首条系列：${p.series[0].label}；其余数据见下方明细。`,line(p.series[0].points,p.series[0].label)));
    if(p.curves?.length)visual.push(panel('经济曲线',`首条对局：${p.curves[0].label}；检查点请以对局时长和实际采样为准。`,line(p.curves[0].points,'蓝方经济差')));
    if(Array.isArray(p.curve)&&p.curve.length&&Array.isArray(p.curve[0]))visual.push(panel('经济变化',p.note||'',line(p.curve,'经济差')));
    const skip=new Set(['heat','points','cells','rows','cols','links','series','curves','curve','games']);
    if(Array.isArray(p.rows)&&p.viz!=='matrix')visual.push(objectTable('分析明细',p.rows));
    for(const [key,items] of Object.entries(p)) if(!skip.has(key)&&Array.isArray(items)&&items.length&&typeof items[0]==='object'&&!Array.isArray(items[0]))visual.push(objectTable(({byPlayer:'选手明细',lanes:'分路汇总',heroes:'英雄汇总',players:'选手汇总',phases:'阶段汇总',grid:'对局检查点',minutes:'逐分钟记录',items:'装备汇总',bans:'禁用统计',picks:'选用统计',objectives:'资源明细',table:'团战明细',outcome:'胜负分组',top:'事件明细',chains:'关联事件',swings:'变化窗口',ledger:'事件记录',sizes:'团战规模',roads:'对位明细'})[key]||key,items));
    return visual.filter(Boolean).join('')||panel('暂无可视化样本',p.note||'当前数据没有足够的可用字段。','<div class="empty">该专题暂无可展示的有效数据。</div>');
  }
  function anchorBar(payload){
    let id='';
    try{id=new URLSearchParams(location.hash.split('?')[1]||'').get('match')||''}catch{}
    if(!id)return '';
    const label=(payload.games||[]).find(g=>String(g.id)===String(id))?.label||id;
    return `<div class="depth-anchor"><span>当前对局 <b>${esc(label)}</b> · 下方是全部训练赛的分布；本页由这一局进入，可随时回到它的复盘</span><a href="#match/${encodeURIComponent(id)}">回到这一局复盘 ↗</a></div>`;
  }
  function topic(value){
    const {meta,payload}=value;
    const gameSelect=payload.games?.length?`<label>选择对局<select data-depth-filter="game"><option value="">默认范围</option>${payload.games.map(g=>`<option value="${esc(g.id)}" ${payload.selected===g.id?'selected':''}>${text(g.label)}</option>`).join('')}</select></label>`:'';
    const sideSelect=meta.sided?`<label>观察阵营<select data-depth-filter="side"><option value="">双方</option><option value="own">本队</option><option value="opp">对手</option></select></label>`:'';
    return `<div class="page feature-page depth-page"><div class="page-intro"><div><a class="depth-back" href="#${groupFor('topic',meta.id)}">← 返回${groupLabel[groupFor('topic',meta.id)]}</a><h1>${text(safeTitles[meta.id]||meta.title)}</h1><p>${text(meta.subtitle)}</p></div></div>${anchorBar(payload)}<div class="scope-note"><span>数据口径</span>${text(meta.boundary)}　${text(meta.samples)}。本专题使用全部营地面板与关联回放，可能包含非训练赛；不受首页数据范围控制。</div>${gameSelect||sideSelect?`<div class="depth-filters" data-depth-id="${esc(meta.id)}">${gameSelect}${sideSelect}<span data-depth-status role="status"></span></div>`:''}<div data-depth-output>${output(value)}</div></div>`;
  }
  let pendingRequest;
  async function change(event){
    if(event.type!=='change' || !event.target.matches('[data-depth-filter]'))return false;
    pendingRequest?.abort(); pendingRequest=new AbortController(); const currentRequest=pendingRequest;
    const wrapper=event.target.closest('[data-depth-id]'), q=new URLSearchParams();wrapper.querySelectorAll('[data-depth-filter]').forEach(el=>{if(el.value)q.set(el.dataset.depthFilter,el.value)});
    const status=wrapper.querySelector('[data-depth-status]');status.textContent='正在更新…';
    try{const r=await fetch(API_BASE + '/api/depth/analysis/'+encodeURIComponent(wrapper.dataset.depthId)+'?'+q,{signal:currentRequest.signal});if(!r.ok)throw Error('读取失败');const value=await r.json();if(!currentRequest.signal.aborted&&wrapper.isConnected){document.querySelector('[data-depth-output]').innerHTML=output(value);status.textContent='已更新'}}catch{if(!currentRequest.signal.aborted&&wrapper.isConnected)status.textContent='读取失败，请重试。'}return true;
  }
  return {topic,change};
}
