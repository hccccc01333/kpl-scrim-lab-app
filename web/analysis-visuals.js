import {finite,extent,median,percentile,rollingMean,wilson,cleanTimeline,segments,sampleCount} from '/assets/analysis-math.mjs?v=1';

const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (value,digits=1) => finite(value)===null?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits});
const clock = value => `${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;
const metrics = {
  gpm:{label:'分均经济',unit:'金币 / 分钟',digits:0}, dpm:{label:'分均输出',unit:'伤害 / 分钟',digits:0},
  kda:{label:'KDA',unit:'比值',digits:2}, participation:{label:'参团率',unit:'%',digits:1},
  goldShare:{label:'经济占比',unit:'%',digits:1}, damageShare:{label:'输出占比',unit:'%',digits:1},
  takenShare:{label:'承伤占比',unit:'%',digits:1}, winRate:{label:'胜率',unit:'%',digits:1},
  gold:{label:'总经济',unit:'金币',digits:0}, damage:{label:'输出',unit:'伤害',digits:0}, rating:{label:'评分',unit:'分',digits:1},
};
const colors = {a:'#416be8',b:'#df8c39',blue:'#416be8',red:'#da6b76'};
const cleanups = new Set();
const observedRoots = new WeakMap();
export function disposeAnalysisVisuals(){for(const cleanup of cleanups)cleanup();cleanups.clear();}
function resize(root,draw){
  const previous=observedRoots.get(root);if(previous){previous();cleanups.delete(previous);}
  let width=0;
  const observer=new ResizeObserver(entries=>{const next=Math.round(entries[0].contentRect.width);if(Math.abs(next-width)>3){width=next;draw();}});
  const cleanup=()=>observer.disconnect();observer.observe(root);cleanups.add(cleanup);observedRoots.set(root,cleanup);
}
const shell=(title,description,body,extra='')=>`<section class="panel av-panel"><div class="panel-head"><div><span class="av-eyebrow">PERFORMANCE LAB</span><h2>${title}</h2><p>${description}</p></div>${extra}</div>${body}</section>`;
const empty=message=>`<div class="av-empty">${message}</div>`;
function grid(w,h,l,r,t,b,xd,yd,xFormat=fmt,yFormat=fmt){
  let html='';const seenX=new Set(),dx=xd[1]-xd[0],dy=yd[1]-yd[0];
  for(let i=0;i<=4;i++){
    const x=l+(w-l-r)*i/4,y=h-b-(h-t-b)*i/4;
    html+=`<line x1="${l}" x2="${w-r}" y1="${y}" y2="${y}" class="av-gridline"/><text x="${l-12}" y="${y+4}" text-anchor="end" class="av-axis-label">${yFormat(yd[0]+(yd[1]-yd[0])*i/4,dy<=2?2:dy<=12?1:0)}</text>`;
    const text=xFormat(xd[0]+(xd[1]-xd[0])*i/4,dx<=2?2:dx<=12?1:0);
    if(text&&!seenX.has(text)){html+=`<text x="${x}" y="${h-b+25}" text-anchor="middle" class="av-axis-label">${text}</text>`;seenX.add(text);}
  }
  return html;
}
function csvDownload(rows,kind){
  const columns=['kda','gpm','dpm','participation','winRate'];
  const quote=value=>`"${String(value??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')}"`;
  const data=[['对象','样本数','已知赛果',...columns.map(key=>metrics[key].label)],...rows.map(row=>[kind==='hero'?row.hero:row.label,sampleCount(row),row.decided,...columns.map(key=>finite(row[key]))])];
  const url=URL.createObjectURL(new Blob(['\ufeff'+data.map(row=>row.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`${kind==='hero'?'英雄':'选手'}-当前探索.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export function mountPerformanceExplorer(root,rows,{kind='player'}={}){
  if(!root)return;
  const state={x:'gpm',y:'dpm',view:'scatter',search:'',minimum:1,sort:'gpm',descending:true,page:0,selected:null};
  const name=row=>kind==='hero'?row.hero:row.label;
  const href=row=>`#${kind}/${encodeURIComponent(name(row))}`;
  const options=selected=>['gpm','dpm','kda','participation','goldShare','damageShare','takenShare'].map(key=>`<option value="${key}"${selected===key?' selected':''}>${metrics[key].label}</option>`).join('');
  root.innerHTML=shell('表现探索','把产出、资源与样本放在一起看；选择一个对象继续核对。',`<div class="av-controls"><div class="av-segment" aria-label="探索视图"><button data-view="scatter" class="active">表现散点</button><button data-view="matrix">指标矩阵</button></div><label>横轴<select data-axis="x">${options('gpm')}</select></label><label>纵轴<select data-axis="y">${options('dpm')}</select></label><label>最低样本<select data-minimum><option value="1">1 场</option><option value="3">3 场</option><option value="5">5 场</option><option value="10">10 场</option></select></label><label class="av-search">查找对象<input data-search type="search" placeholder="${kind==='hero'?'英雄名':'选手昵称'}"></label></div><div class="av-explorer-layout"><div class="av-explorer-main"><div class="av-plot-title"></div><div class="av-plot"></div><div class="av-chart-foot"></div></div><aside class="av-inspector" aria-live="polite"></aside></div>`,`<button class="button" data-export>导出当前数据</button>`);
  let filtered=[];
  function inspect(row){
    state.selected=row;
    const box=root.querySelector('.av-inspector');
    if(!row){box.innerHTML='<span class="av-eyebrow">OBJECT DETAIL</span><h3>点选一个对象</h3><p>查看原值、有效样本，再进入详情或对比。</p>';return;}
    const interval=wilson(row.wins,row.decided);
    box.innerHTML=`<span class="av-eyebrow">${kind==='hero'?'HERO':'PLAYER'} PROFILE</span><h3>${esc(name(row))}</h3><p>${fmt(sampleCount(row),0)} ${kind==='hero'?'次出场':'场比赛'} · ${kind==='player'?(row.bound?'已绑定身份':'昵称未绑定'):((row.players||[]).length+' 名使用选手')}</p><dl>${[state.x,state.y,'kda','participation'].filter((key,i,list)=>list.indexOf(key)===i).map(key=>`<div><dt>${metrics[key].label}</dt><dd>${fmt(row[key],metrics[key].digits)}<small>${key==='kda'?'':metrics[key].unit}</small></dd></div>`).join('')}</dl><div class="av-win-sample"><span>胜率 <b>${fmt(row.winRate)}${finite(row.winRate)!==null?'%':''}</b></span><small>${fmt(row.wins,0)} 胜 / ${fmt(row.decided,0)} 场有胜负</small>${interval?`<div class="av-interval-track"><i style="left:${interval[0]}%;width:${interval[1]-interval[0]}%"></i></div><small>95% Wilson 区间 ${fmt(interval[0])}%–${fmt(interval[1])}%</small><details><summary>如何理解区间</summary><p>按独立胜负样本近似计算，只反映样本不确定性；同场多名选手并非独立观察，小样本不作实力评级。</p></details>`:''}</div><a class="button primary" href="${href(row)}">查看${kind==='hero'?'英雄':'选手'}详情 ↗</a><a class="av-detail-link" href="#compare/${kind}/${encodeURIComponent(name(row))}">以此对象建立对比 →</a>`;
    root.querySelectorAll('[data-point]').forEach(point=>point.classList.toggle('selected',filtered[Number(point.dataset.point)]===row));
  }
  function scatter(){
    const good=filtered.map((row,index)=>({row,index,x:finite(row[state.x]),y:finite(row[state.y])})).filter(p=>p.x!==null&&p.y!==null).sort((a,b)=>sampleCount(b.row)-sampleCount(a.row)).slice(0,120);
    if(!good.length)return empty('当前条件下没有横轴、纵轴都有效的对象。可降低最低样本或更换指标。');
    const w=Math.max(300,Math.round(root.querySelector('.av-plot').clientWidth)),h=390,l=65,r=22,t=26,b=52;
    const xd=extent(good.map(p=>p.x)),yd=extent(good.map(p=>p.y));
    if(good.every(p=>p.x>=0))xd[0]=Math.max(0,xd[0]);if(good.every(p=>p.y>=0))yd[0]=Math.max(0,yd[0]);
    const x=v=>l+(v-xd[0])/(xd[1]-xd[0])*(w-l-r),y=v=>h-b-(v-yd[0])/(yd[1]-yd[0])*(h-t-b);
    const mx=median(good.map(p=>p.x)),my=median(good.map(p=>p.y));
    return `<svg viewBox="0 0 ${w} ${h}" role="group" aria-label="${metrics[state.x].label}与${metrics[state.y].label}散点图">${grid(w,h,l,r,t,b,xd,yd)}<line x1="${x(mx)}" x2="${x(mx)}" y1="${t}" y2="${h-b}" class="av-median"/><line x1="${l}" x2="${w-r}" y1="${y(my)}" y2="${y(my)}" class="av-median"/>${good.map(p=>`<circle data-point="${p.index}" cx="${x(p.x)}" cy="${y(p.y)}" r="${Math.min(17,7+Math.sqrt(sampleCount(p.row))*1.8)}" fill="${finite(p.row.winRate)===null?'#91a0b5':p.row.winRate>=50?colors.a:colors.b}" class="av-bubble" tabindex="0" role="button" aria-label="${esc(name(p.row))}，${metrics[state.x].label} ${fmt(p.x)}，${metrics[state.y].label} ${fmt(p.y)}，样本 ${sampleCount(p.row)}"><title>${esc(name(p.row))} · ${fmt(p.x)} / ${fmt(p.y)} · 样本 ${sampleCount(p.row)}</title></circle>`).join('')}</svg><div class="av-axis-caption"><span>横轴 ${metrics[state.x].label} · ${metrics[state.x].unit}</span><span>纵轴 ${metrics[state.y].label} · ${metrics[state.y].unit}</span></div><div class="av-legend"><span><i style="background:${colors.a}"></i>胜率 ≥ 50%</span><span><i style="background:${colors.b}"></i>胜率 &lt; 50%</span><span><i style="background:#91a0b5"></i>胜负未知</span><span>圆越大，样本越多 · 虚线为中位数</span></div>`;
  }
  function matrix(){
    const keys=['kda','gpm','dpm','participation','winRate'];
    const subset=filtered.slice(state.page*40,state.page*40+40);
    return `<div class="av-matrix-scroll"><table class="av-matrix"><thead><tr><th>${kind==='hero'?'英雄':'选手'}</th><th>样本</th>${keys.map(key=>`<th><button data-sort="${key}">${metrics[key].label}${state.sort===key?(state.descending?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead><tbody>${subset.map(row=>`<tr><th><button data-point="${filtered.indexOf(row)}">${esc(name(row))}</button></th><td>${sampleCount(row)}</td>${keys.map(key=>{const rank=percentile(row[key],filtered.map(r=>r[key]));return `<td class="${rank===null?'av-missing':''}" style="${rank===null?'':`background:hsl(221 76% ${97-rank*.27}%)`}" title="${rank===null?'缺失值':`列内分位 ${fmt(rank,0)}% · 不跨指标比较原始量纲`}">${fmt(row[key],metrics[key].digits)}${key==='winRate'&&rank!==null?'%':''}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div><div class="av-pagination"><button class="button" data-page="-1" ${state.page===0?'disabled':''}>上一页</button><span>${state.page+1} / ${Math.max(1,Math.ceil(filtered.length/40))}</span><button class="button" data-page="1" ${(state.page+1)*40>=filtered.length?'disabled':''}>下一页</button></div><div class="av-axis-caption">单元格显示原值，底色只表示该列当前对象内的分位；浅色较低、深色较高，斜纹为缺失。</div>`;
  }
  function draw(){
    filtered=rows.filter(row=>sampleCount(row)>=state.minimum&&String(name(row)||'').toLowerCase().includes(state.search.toLowerCase())).slice().sort((a,b)=>{const av=finite(a[state.sort]),bv=finite(b[state.sort]);if(av===null)return bv===null?0:1;if(bv===null)return -1;return (av-bv)*(state.descending?-1:1);});
    state.page=Math.min(state.page,Math.max(0,Math.ceil(filtered.length/40)-1));
    root.querySelector('.av-plot-title').innerHTML=`<strong>${state.view==='scatter'?`${metrics[state.x].label} × ${metrics[state.y].label}`:'多指标表现矩阵'}</strong><span>${filtered.length} 个对象 · 筛选只作用于本探索视图</span>`;
    root.querySelector('.av-plot').innerHTML=filtered.length?(state.view==='scatter'?scatter():matrix()):empty('没有符合当前条件的对象。');
    root.querySelector('.av-chart-foot').textContent=state.view==='scatter'?'点选圆点检查原值，Tab / Enter 也可操作。密集数据最多绘制样本最多的 120 个对象；跨分路不直接作能力比较。':'可点击列名排序，点击名字检查对象。每页最多 40 行。';
    if(state.selected&&!filtered.includes(state.selected))state.selected=null;
    inspect(state.selected||filtered[0]);
  }
  root.addEventListener('click',event=>{
    const point=event.target.closest('[data-point]');if(point){inspect(filtered[Number(point.dataset.point)]);return;}
    const view=event.target.closest('[data-view]');if(view){state.view=view.dataset.view;root.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===view));root.querySelectorAll('[data-axis]').forEach(el=>el.parentElement.hidden=state.view==='matrix');draw();return;}
    const sort=event.target.closest('[data-sort]');if(sort){state.descending=state.sort===sort.dataset.sort?!state.descending:true;state.sort=sort.dataset.sort;draw();return;}
    const page=event.target.closest('[data-page]');if(page){state.page+=Number(page.dataset.page);draw();return;}
    if(event.target.closest('[data-export]'))csvDownload(filtered,kind);
  });
  root.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('circle[data-point]')){event.preventDefault();inspect(filtered[Number(event.target.dataset.point)]);}});
  root.querySelectorAll('[data-axis]').forEach(select=>select.onchange=()=>{state[select.dataset.axis]=select.value;draw();});
  root.querySelector('[data-minimum]').onchange=event=>{state.minimum=Number(event.target.value);state.page=0;draw();};
  root.querySelector('[data-search]').oninput=event=>{state.search=event.target.value;state.page=0;draw();};
  draw();resize(root.querySelector('.av-explorer-main'),draw);
}

export function comparisonVisual(a,b,definitions,pool){
  return shell('差异一眼看清','蓝色 A、橙色 B；每个指标使用独立刻度，保留原值与单位。',`<div class="av-dumbbells">${definitions.map(([key,label,digits])=>{
    const av=finite(a[key]),bv=finite(b[key]),values=pool.map(row=>finite(row[key])).filter(value=>value!==null),max=Math.max(1,...values,av??0,bv??0),x=v=>15+v/max*270;
    return `<div class="av-dumbbell"><div class="av-dumbbell-name"><strong>${label}</strong><small>${metrics[key]?.unit||''}</small></div><div class="av-dumbbell-plot"><svg viewBox="0 0 300 40" role="img" aria-label="${label}：A ${fmt(av,digits)}，B ${fmt(bv,digits)}"><line x1="15" x2="285" y1="20" y2="20" stroke="#e6ebf4" stroke-width="4"/>${av!==null&&bv!==null?`<line x1="${x(av)}" x2="${x(bv)}" y1="20" y2="20" stroke="#b6c4de" stroke-width="4"/>`:''}${av!==null?`<circle cx="${x(av)}" cy="14" r="6" fill="${colors.a}"/>`:''}${bv!==null?`<circle cx="${x(bv)}" cy="26" r="6" fill="${colors.b}"/>`:''}</svg><div><small>0</small><small>${fmt(max,0)}</small></div></div><div class="av-dumbbell-values"><span class="av-a">${fmt(av,digits)}</span><span class="av-b">${fmt(bv,digits)}</span><small>A − B ${av!==null&&bv!==null?`${av-bv>0?'+':''}${fmt(av-bv,digits)}`:'—'}</small></div></div>`;
  }).join('')}</div><p class="av-chart-foot">刻度上限取当前筛选同类对象的有效最大值；差值是描述，不是综合能力评级。缺失不显示成零。</p>`);
}

export function mountEconomyTimeline(root,points){
  if(!root)return;
  const good=cleanTimeline(points);let selected=good.length-1,mode='diff',xScale=null;
  if(!good.length){root.innerHTML=empty('没有可用经济观测点；不外推或补零。');return;}
  root.innerHTML=`<div class="av-timeline-toolbar"><div class="av-segment"><button data-economy="diff" class="active">经济差</button><button data-economy="total">双方经济</button></div><span>蓝方 − 红方 · ${good.length} 个实测点</span></div><div class="av-timeline-readout" aria-live="polite"></div><div class="av-timeline-plot"></div><label class="av-range-label">选择观测时刻<input type="range" min="0" max="${good.length-1}" value="${selected}" step="1" aria-label="经济时间轴观测点"></label><div class="av-axis-caption"><span>观测 ${clock(good[0].gameTime)}–${clock(good.at(-1).gameTime)}</span><span>拖动游标或使用方向键 · 断开处为超过 120 秒的缺口</span></div>`;
  function readout(){const p=good[selected];root.querySelector('.av-timeline-readout').innerHTML=`<div><span>当前观测</span><strong>${clock(p.gameTime)}</strong></div><div><span>蓝方经济</span><strong class="av-a">${fmt(p.blueGold,0)}</strong></div><div><span>红方经济</span><strong class="av-red">${fmt(p.redGold,0)}</strong></div><div><span>蓝 − 红</span><strong>${p.diff>0?'+':''}${fmt(p.diff,0)}</strong></div>`;root.querySelector('input').setAttribute('aria-valuetext',`${clock(p.gameTime)}，蓝方 ${p.blueGold}，红方 ${p.redGold}，差值 ${p.diff}`);}
  function updateSelection(){const box=root.querySelector('.av-timeline-plot');if(!box||!xScale)return;const cursor=box.querySelector('.av-cursor');if(cursor){const xv=xScale(good[selected].gameTime);cursor.setAttribute('x1',xv);cursor.setAttribute('x2',xv);}box.querySelectorAll('[data-time-index]').forEach((el,index)=>el.setAttribute('r',index===selected?6:3));readout();}
  function draw(){
    const box=root.querySelector('.av-timeline-plot'),w=Math.max(300,Math.round(box.clientWidth)),h=320,l=65,r=22,t=20,b=44;
    const xd=[good[0].gameTime,Math.max(good[0].gameTime+1,good.at(-1).gameTime)],yd=extent(mode==='diff'?good.map(p=>p.diff):good.flatMap(p=>[p.blueGold,p.redGold]),{zero:true});
    const x=v=>l+(v-xd[0])/(xd[1]-xd[0])*(w-l-r),y=v=>h-b-(v-yd[0])/(yd[1]-yd[0])*(h-t-b);
    xScale=x;
    const lines=segments(good).map(segment=>(mode==='diff'?['diff']:['blueGold','redGold']).map(key=>`<path d="${segment.map((p,i)=>`${i?'L':'M'}${x(p.gameTime)},${y(p[key])}`).join(' ')}" fill="none" stroke="${key==='redGold'?colors.red:colors.a}" stroke-width="2.5" stroke-linejoin="round"/>`).join('')).join('');
    box.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="group" aria-label="交互经济时间轴">${grid(w,h,l,r,t,b,xd,yd,v=>clock(v),fmt)}${mode==='diff'?`<line x1="${l}" x2="${w-r}" y1="${y(0)}" y2="${y(0)}" stroke="#a5b6d0" stroke-dasharray="4 4"/>`:''}${lines}<line x1="${x(good[selected].gameTime)}" x2="${x(good[selected].gameTime)}" y1="${t}" y2="${h-b}" class="av-cursor"/>${good.map((p,i)=>`<circle data-time-index="${i}" cx="${x(p.gameTime)}" cy="${y(mode==='diff'?p.diff:p.blueGold)}" r="${i===selected?6:3}" fill="${colors.a}" class="av-time-point"><title>${clock(p.gameTime)} · ${fmt(p.diff,0)}</title></circle>`).join('')}</svg>`;
    readout();
  }
  root.querySelector('input').oninput=event=>{selected=Number(event.target.value);updateSelection();};
  root.addEventListener('click',event=>{const modeButton=event.target.closest('[data-economy]');if(modeButton){mode=modeButton.dataset.economy;root.querySelectorAll('[data-economy]').forEach(b=>b.classList.toggle('active',b===modeButton));draw();return;}const point=event.target.closest('[data-time-index]');if(point){selected=Number(point.dataset.timeIndex);root.querySelector('input').value=selected;updateSelection();}});
  draw();resize(root,draw);
}

export function mountEntityTrend(root,rows,metric){
  if(!root)return;
  const info=metrics[metric]||{label:metric,unit:'',digits:1};
  const rolling=rollingMean(rows,metric,5),values=rows.map(row=>finite(row[metric])),count=values.filter(v=>v!==null).length;
  if(!count){root.innerHTML=empty('当前范围没有该指标的有效观测；缺失值保留为空。');return;}
  if(count===1){
    // 只有一条观测时折线退化成单点，画出来是一大片空白；改为一条读数。
    const index=values.findIndex(v=>v!==null),row=rows[index]||{};
    root.innerHTML=`<div class="av-trend-single"><div class="av-trend-single-main"><span>${esc(info.label)}</span><b>${fmt(values[index],info.digits)}<em>${esc(info.unit)}</em></b></div><p><strong>${esc(row.date||'日期未记录')} · ${esc(row.hero||row.label||'本局')}</strong><br>当前只有 1 条有效观测，画折线看不出走势；再导入一局，这里会变成逐局曲线。</p></div>`;
    root.onclick=null;root.onkeydown=null;
    return;
  }
  root.innerHTML=`<div class="av-trend-head"><span><i></i>逐局原值 <i class="rolling"></i>近5条记录均值</span><span>${count} / ${rows.length} 行有效</span></div><div class="av-trend-plot"></div><div class="av-trend-detail" aria-live="polite"></div>`;
  let selected=values.findLastIndex(v=>v!==null);
  function inspect(index){selected=index;const row=rows[index];root.querySelector('.av-trend-detail').innerHTML=`<div><strong>${esc(row.date||'日期未记录')} · ${esc(row.hero||row.label||'本局')}</strong><span>${info.label} ${fmt(values[index],info.digits)} ${info.unit} · 近5条记录均值 ${fmt(rolling[index].value,info.digits)}（${rolling[index].n} 个有效值）</span></div><a class="button" href="#match/${encodeURIComponent(row.matchKey)}">查看本局 ↗</a>`;}
  function draw(){
    const box=root.querySelector('.av-trend-plot'),w=Math.max(300,Math.round(box.clientWidth)),h=280,l=65,r=22,t=25,b=44,yd=extent(values),xd=[1,Math.max(2,rows.length)];
    const x=i=>rows.length===1?(l+w-r)/2:l+i/(rows.length-1)*(w-l-r),y=v=>h-b-(v-yd[0])/(yd[1]-yd[0])*(h-t-b);
    const line=source=>source.map((value,i)=>value===null?'':`${i===0||source[i-1]===null?'M':'L'}${x(i)},${y(value)}`).join(' ');
    box.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="group" aria-label="${info.label}逐局走势">${grid(w,h,l,r,t,b,xd,yd,v=>rows.length===1?'':String(Math.round(v)),fmt)}<path d="${line(values)}" class="av-trend-line"/><path d="${line(rolling.map(p=>p.value))}" class="av-rolling-line"/>${values.map((value,i)=>value===null?'':`<circle data-trend-index="${i}" cx="${x(i)}" cy="${y(value)}" r="5" fill="${colors.a}" tabindex="0" role="button" aria-label="第 ${i+1} 个记录，${esc(rows[i].date)}，${info.label} ${fmt(value)}"><title>${esc(rows[i].date)} · ${fmt(value)}</title></circle>`).join('')}</svg><div class="av-axis-caption">横轴为当前对象的记录顺序，保留缺失位置；纵轴 ${info.label}（${info.unit}）。${rows.length===1?'当前只有一个有效记录，不生成趋势判断。':''}</div>`;
    inspect(selected);
  }
  root.onclick=event=>{const point=event.target.closest('[data-trend-index]');if(point)inspect(Number(point.dataset.trendIndex));};
  root.onkeydown=event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('[data-trend-index]')){event.preventDefault();inspect(Number(event.target.dataset.trendIndex));}};
  draw();resize(root,draw);
}

export function processMatrix(data){
  const landmarks=[120,300,600,900],rows=data.matches||[],all=rows.flatMap(row=>landmarks.map(t=>finite(row.diffAt?.[t]))).filter(v=>v!==null),maximum=Math.max(1,...all.map(Math.abs));
  if(!rows.length)return '';
  return shell('经济节奏矩阵','每一行是一局，每一列是一个比赛时点；以本队 − 对手为方向。',`<div class="av-process-matrix-scroll"><table class="av-process-matrix"><thead><tr><th>比赛 / 赛果</th>${landmarks.map(t=>`<th>${t/60} 分钟<small>${fmt(data.aggregate?.landmarkSamples?.[t],0)} 局有效</small></th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr><th><a href="#match/${encodeURIComponent(row.key)}"><strong>${esc(row.date||'日期待补')} · ${esc(row.opponent||'训练赛')}</strong><small>${row.win===true?'胜':row.win===false?'负':'胜负未知'} · 观测至 ${finite(row.observedEnd)!==null?clock(row.observedEnd):'—'}</small></a></th>${landmarks.map(t=>{const value=finite(row.diffAt?.[t]);return `<td class="${value===null?'av-missing':''}" style="${value===null?'':`background:${value>=0?`hsl(221 79% ${97-Math.abs(value)/maximum*30}%)`:`hsl(27 85% ${97-Math.abs(value)/maximum*29}%)`}`}" title="${value===null?'该检查点没有可用观测，或跨越大于120秒的缺口':'本队经济 − 对手经济；相邻有效观测之间可能线性估算'}">${value===null?'—':(value>0?'+':'')+fmt(value,0)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div><div class="av-legend"><span><i style="background:#85a5ef"></i>本队领先</span><span><i style="background:#ebbc8b"></i>本队落后</span><span>— 未覆盖，不外推 · 最多展示最近 60 局</span></div>`);
}
