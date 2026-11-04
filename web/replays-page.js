import { renderV2Timeline } from '/assets/v2-timeline.js?v=4';
const esc=(v='')=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v==null?'—':Number(v).toLocaleString('zh-CN');
const bytes=v=>v==null?'—':num(v)+' B';
const fixed=(v,n=1)=>v==null?'—':Number(v).toFixed(n);
const pct=(v,n=1)=>v==null?'—':Number(v).toFixed(n)+'%';
const clock=v=>v==null?'—':`${Math.floor(v/60)}:${String(Math.floor(v%60)).padStart(2,'0')}`;
const checkpointImports=new Map();
const CHECKPOINT_STATE_FIELDS=['gold','kills','deaths','assists','level','hp_current','hp_max','hp_ratio','abs_hp_estimate','hp_max_abs'];
const checkpointMeasured=row=>CHECKPOINT_STATE_FIELDS.some(key=>row&&row[key]!=null);

function runtimeSection(r){
 const rt=r.runtime;
 const header=`<div class="panel-header"><div><h2>运行时赛训数据</h2><div class="panel-subtitle">GameCore 帧/事件导出 · 未导入时不补造数据</div></div>${rt?`<a class="button secondary" href="/api/replays/${esc(r.id)}/runtime/file" download>下载 JSONL</a>`:'<span class="tag gray">未导入</span>'}</div>`;
 if(!rt){
  const example=esc('{"type":"frame","frame":120,"time":120,"players":[{"playerId":"b1","heroId":101,"camp":"blue","slot":0,"gold":1200,"kills":2,"deaths":1,"assists":3,"damageDealt":6000,"damageTaken":3000}]}\n{"type":"event","frame":150,"time":150,"event":"dragon","camp":"blue"}');
  return `<section class="panel section-gap">${header}<div class="form-section"><form id="runtime-upload" data-replay-id="${esc(r.id)}"><div class="replay-import-grid"><label class="field">运行时 JSONL<input id="runtime-file" type="file" accept=".jsonl,.json" required></label><button class="button" type="submit">导入并分析</button></div><p class="helper">记录来自 GameCore 运行时采集器：一行一帧或一事件，≤ 8 MB。没有该文件时，工作台只展示回放结构，不推断经济、输出或承伤。</p><details class="runtime-schema"><summary>查看数据格式</summary><pre class="helper">${example}</pre></details></form></div></section>`;
 }
 const a=rt.analysis,c=a.coverage,t=a.teams,ev=a.events,players=a.players||[],timeline=a.timeline||[];
 const rows=players.map(p=>`<tr><td><span class="tag ${p.camp==='blue'?'':p.camp==='red'?'amber':'gray'}">${p.camp==='blue'?'蓝':p.camp==='red'?'红':'未知'}</span></td><td><strong>${esc(p.playerId)}</strong></td><td>${num(p.heroId)}</td><td>${fixed(p.metrics.kda,2)}${p.metrics.kdaPerfect?' <small>完美</small>':''}</td><td>${fixed(p.metrics.gpm,0)}</td><td>${fixed(p.metrics.xpm,0)}</td><td>${fixed(p.metrics.damagePerMin,0)}</td><td>${fixed(p.metrics.takenPerMin,0)}</td><td>${pct(p.metrics.participation)}</td><td>${pct(p.metrics.goldShare)}</td></tr>`).join('');
 const team=(name,label)=>{const full=t[name].complete&&t[name].totals.gold!=null;return `<div class="metric"><div class="metric-label">${label} · ${t[name].players}/5 人</div><div class="metric-number replay-number">${full?num(t[name].totals.gold):'—'}<small>${full?'金币':'不完整'}</small></div><div class="metric-note">${full?`击杀 ${num(t[name].totals.kills)} · 伤害 ${num(t[name].totals.damageDealt)}`:'团队合计未计算'}</div></div>`;};
 const recent=timeline.slice(-8);
 const points=recent.map(p=>`<tr><td>${clock(p.time)}</td><td>${num(p.blueGold)}</td><td>${num(p.redGold)}</td><td>${num(p.blueKills)}</td><td>${num(p.redKills)}</td></tr>`).join('');
 return `<section class="panel section-gap">${header}<div class="form-section">${a.warnings?.length?`<div class="notice">${a.warnings.map(esc).join('<br>')}</div>`:''}<div class="metrics runtime-metrics">${team('blue','蓝方')}${team('red','红方')}<div class="metric"><div class="metric-label">帧与时长</div><div class="metric-number replay-number">${num(c.frames)}<small>帧</small></div><div class="metric-note">${clock(c.durationSec)} · ${c.timeBasis==='time'?'按 time':'按 30fps 估算'}</div></div><div class="metric"><div class="metric-label">事件</div><div class="metric-number replay-number">${num(ev.total)}</div><div class="metric-note">击杀 ${num(ev.counts?.kill??0)} · 技能命中率 ${pct(ev.skillHitRate)}</div></div></div><div class="panel-header"><h2>队员指标</h2><span class="tag gray">${players.length} 人</span></div>${players.length?`<div class="table-wrap"><table class="runtime-table"><thead><tr><th>阵营</th><th>队员</th><th>英雄 ID</th><th>KDA</th><th>GPM</th><th>XPM</th><th>分均伤害</th><th>分均承伤</th><th>参团率</th><th>经济占比</th></tr></thead><tbody>${rows}</tbody></table></div>`:'<div class="empty">没有队员帧数据。</div>'}<div class="panel-header"><h2>经济与击杀时间轴</h2><span class="tag gray">最近 ${recent.length} 个采样点</span></div>${points?`<div class="table-wrap"><table><thead><tr><th>时间</th><th>蓝方金币</th><th>红方金币</th><th>蓝方击杀</th><th>红方击杀</th></tr></thead><tbody>${points}</tbody></table></div>`:'<div class="empty">两侧均有 5 人完整金币后才能画时间轴。</div>'}<div class="summary-footnote">数据来自 ${esc(rt.fileName)}（${bytes(rt.size)}，SHA-256 ${esc(rt.sha256.slice(0,12))}…）。只展示采集器提供的字段；缺失字段保持“—”。</div></div></section>`;
}

function inputsSection(r){
 return `<section class="panel section-gap" id="input-timeline"><div class="panel-header"><div><h2>英雄输入时间轴</h2><div class="panel-subtitle">packed 帧命令解码 · unit = 8 + (camp-1)*8 + 槽位（5247758 样本验证）</div></div><span class="tag amber">输入方向角 · 非世界坐标</span></div><div class="form-section"><div id="input-summary" class="helper" role="status">正在解码输入事件…</div></div><div class="form-section" id="input-chart" hidden></div></section>`;
}

function drawInputChart(host,hero,timeBase){
 const moves=hero.moves||[];
 if(!moves.length){host.hidden=false;host.innerHTML='<div class="empty">该英雄没有移动输入（AI 英雄不发输入命令）。</div>';return;}
 const fps=(timeBase&&timeBase.framesPerSecond)||15;
 const toSec=f=>((f-(timeBase&&timeBase.battleStartFrame?timeBase.battleStartFrame[0]:0))/fps);
 const fmt=t=>{const m=Math.floor(t/60),s=Math.round(t%60);return `${m}:${String(s).padStart(2,'0')}`;};
 const w=760,h=190,padX=30,padTop=30,padBottom=20;
 const f0=hero.firstFrame??moves[0][0],f1=Math.max(hero.lastFrame??moves[moves.length-1][0],f0+1);
 const x=f=>padX+(w-2*padX)*(f-f0)/(f1-f0);
 const y=d=>padTop+(h-padTop-padBottom)*(1-(Number(d)+180)/360);
 const path=moves.map((m,i)=>`${i?'L':'M'}${x(m[0]).toFixed(1)},${y(m[1]).toFixed(1)}`).join('');
 const ticks=(hero.attacks||[]).map(a=>`<line x1="${x(a[0]).toFixed(1)}" y1="${padTop-12}" x2="${x(a[0]).toFixed(1)}" y2="${padTop-2}" stroke="#b45309" stroke-width="1"/>`).join('');
 const buys=(hero.buys||[]).map(b=>`<rect x="${(x(b[0])-2).toFixed(1)}" y="${h-padBottom-7}" width="4" height="7" fill="#1d4ed8"/>`).join('');
 host.hidden=false;
 host.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%" style="height:auto;display:block;max-width:760px" role="img" aria-label="英雄输入方向时间轴"><line x1="${padX}" y1="${y(0)}" x2="${w-padX}" y2="${y(0)}" stroke="#d4d4d8" stroke-dasharray="3 3"/><line x1="${padX}" y1="${y(180)}" x2="${w-padX}" y2="${y(180)}" stroke="#e4e4e7"/><line x1="${padX}" y1="${y(-180)}" x2="${w-padX}" y2="${y(-180)}" stroke="#e4e4e7"/><text x="${padX-24}" y="${y(180)+4}" font-size="10" fill="#71717a">+180°</text><text x="${padX-24}" y="${y(0)+4}" font-size="10" fill="#71717a">0°</text><text x="${padX-24}" y="${y(-180)+4}" font-size="10" fill="#71717a">-180°</text>${ticks}<path d="${path}" fill="none" stroke="#2563eb" stroke-width="1.5"/>${buys}<text x="${padX}" y="${h-4}" font-size="10" fill="#71717a">对局 ${fmt(toSec(f0))} → ${fmt(toSec(f1))}（15 帧/秒换算，±1s）· 蓝线=输入方向角（采样） · 橙刻度=普攻 · 底部蓝块=购买装备</text></svg>`;
}

function drawPathChart(host,hero){
 const pts=hero.pathEstimate||[];
 if(pts.length<2){host.hidden=true;return;}
 const w=360,h=300,pad=20;
 const xs=pts.map(p=>p[1]),ys=pts.map(p=>p[2]);
 const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
 const span=Math.max(x1-x0,y1-y0,1);
 const X=v=>pad+(w-2*pad)*(v-x0)/span;
 const Y=v=>h-pad-(h-2*pad)*(v-y0)/span;
 const path=pts.map((p,i)=>`${i?'L':'M'}${X(p[1]).toFixed(1)},${Y(p[2]).toFixed(1)}`).join('');
 const anchors=hero.positionAnchors||[];
 let anchorPlot='';
 if(anchors.length>=2){
  const axs=anchors.map(a=>a[1]),ays=anchors.map(a=>a[2]);
  const ax0=Math.min(...axs),ax1=Math.max(...axs),ay0=Math.min(...ays),ay1=Math.max(...ays);
  const aspan=Math.max(ax1-ax0,ay1-ay0,1);
  const AX=v=>pad+(w-2*pad)*(v-ax0)/aspan;
  const AY=v=>h-pad-(h-2*pad)*(v-ay0)/aspan;
  const line=anchors.map((a,i)=>`${i?'L':'M'}${AX(a[1]).toFixed(1)},${AY(a[2]).toFixed(1)}`).join('');
  const dots=anchors.map(a=>`<circle cx="${AX(a[1]).toFixed(1)}" cy="${AY(a[2]).toFixed(1)}" r="2.5" fill="#16a34a"/>`).join('');
  anchorPlot=`<svg viewBox="0 0 ${w} ${h}" width="100%" style="height:auto;display:block" role="img" aria-label="真实位置锚点"><text x="${pad}" y="12" font-size="10" fill="#15803d">真实锚点（0x82 世界坐标，稀疏 ${anchors.length} 点）</text><path d="${line}" fill="none" stroke="#16a34a" stroke-width="1" stroke-dasharray="4 3"/>${dots}</svg>`;
 }
 host.hidden=false;
 host.innerHTML=`<div class="panel-header"><h2>位移形状（估算）</h2><span class="tag amber">漂移严重 · 非位置</span></div><div class="replay-estimate-grid"><svg viewBox="0 0 ${w} ${h}" width="100%" style="height:auto;display:block" role="img" aria-label="方向积分形状"><text x="${pad}" y="12" font-size="10" fill="#71717a">方向积分形状（每条移动输入 1 单位步进）</text><circle cx="${X(pts[0][1]).toFixed(1)}" cy="${Y(pts[0][2]).toFixed(1)}" r="3" fill="#2563eb"/><path d="${path}" fill="none" stroke="#2563eb" stroke-width="1"/><text x="${pad}" y="${h-4}" font-size="10" fill="#71717a">起点=蓝点 · 速度未知 · 死亡/静止不可分 · 锚点残差 1.8万-6.5万</text></svg>${anchorPlot}</div>`;
}

async function mountInputs(container,replayId,{api}){
 const host=container.querySelector('#input-summary');
 if(!host)return;
 container.dataset.replayId=replayId;
 try{
  const data=await api(`/api/replays/${esc(container.dataset.replayId||'')}/inputs`);
  if(data.status==='no-record-stream'){
   host.innerHTML=`<p class="helper">这份 .abc 没有 ID1075 记录流（${esc(data.error||'路径不同')}），无法解码输入时间轴；旧版样本结构见上方解析结果。</p>`;
   return;
  }
  if(data.status==='unsupported-route'&&data.singleGame){
   const sg=data.singleGame;
   const skillRows=sg.skillLevelups.map(r=>`<tr><td>${clock(r[0]/15)}</td><td>actor ${num(r[1])}</td><td>技能 ${num(r[2])}</td><td>L${num(r[3])}</td></tr>`).join('');
   const buyRows=sg.buys.map(r=>`<tr><td>${clock(r[0]/15)}</td><td>装备 ${num(r[1])}</td><td>${r[3]!=null?num(r[3]):'—'}</td></tr>`).join('');
   const fa=sg.facingAngles||[];
   let facingPlot='';
   if(fa.length>=2){
    const fw=700,fh=150,fp=26;
    const f0=fa[0][0],f1=fa[fa.length-1][0];
    const FX=v=>fp+(fw-2*fp)*(v-f0)/Math.max(1,f1-f0);
    const FY=v=>fp+(fh-2*fp)*(1-(Number(v)+180)/360);
    const fpath=fa.map((p,i)=>`${i?'L':'M'}${FX(p[0]).toFixed(1)},${FY(p[1]).toFixed(1)}`).join('');
    facingPlot=`<svg viewBox="0 0 ${fw} ${fh}" width="100%" style="height:auto;display:block" role="img" aria-label="朝向角时间轴"><line x1="${fp}" y1="${FY(0)}" x2="${fw-fp}" y2="${FY(0)}" stroke="#d4d4d8" stroke-dasharray="3 3"/><text x="${fp-20}" y="${FY(180)+4}" font-size="10" fill="#71717a">180</text><text x="${fp-20}" y="${FY(-180)+4}" font-size="10" fill="#71717a">-180</text><path d="${fpath}" fill="none" stroke="#7c3aed" stroke-width="1"/><text x="${fp}" y="${fh-4}" font-size="10" fill="#71717a">POV 英雄朝向角（度，对局 ${clock(f0/15)} → ${clock(f1/15)}，±1s）</text></svg>`;
   }
   host.innerHTML=`<div class="panel-header"><h2>单局时间轴（ID1051）</h2><span class="tag gray">actor → 英雄映射未解</span></div>${facingPlot}<div class="replay-estimate-grid section-gap"><div><div class="panel-header"><h3>技能加点 ${num(sg.skillLevelups.length)}</h3></div><div class="table-wrap"><table><thead><tr><th>对局时间</th><th>actor</th><th>技能</th><th>等级</th></tr></thead><tbody>${skillRows}</tbody></table></div></div><div><div class="panel-header"><h3>购买流水 ${num(sg.buys.length)}</h3></div><div class="table-wrap"><table><thead><tr><th>对局时间</th><th>装备</th><th>参考价</th></tr></thead><tbody>${buyRows}</tbody></table></div></div></div><p class="helper">击杀通知 ${num(sg.killNotices.length)}（成对双阵营） · 时间为 15 帧/秒换算（±1s）。actor 小 id 到英雄的映射未解；语义见 docs 5.133-5.136。</p>`;
   return;
  }
  const rows=data.heroes.map(h=>`<tr><td><span class="tag ${h.camp===1?'':'amber'}">${h.camp===1?'蓝方':'红方'}</span> 槽位 ${num((h.slot??0)+1)}</td><td><strong>${esc(h.hero||'未知英雄')}</strong>${h.self?' <small>录制者</small>':''}</td><td>${num(h.moves)}</td><td>${num(h.attacks)}</td><td>${num(h.attacksWithObj)}</td><td>${num(h.skills)}</td><td>${num(h.buys)}</td><td>${num(h.learnSkill)}</td><td>${h.firstFrame!=null?`${num(h.firstFrame)}–${num(h.lastFrame)}`:'—'}</td></tr>`).join('');
  host.innerHTML=`<div class="table-wrap"><table><thead><tr><th>阵营/槽位</th><th>英雄</th><th>移动</th><th>普攻</th><th>带目标普攻</th><th>技能</th><th>购买</th><th>学技能</th><th>活跃帧</th></tr></thead><tbody>${rows}</tbody></table></div><p class="helper">记录帧 ${num(data.frameRecords)} · 完整解析 ${num(data.fullyParsedFrames)} · 未解帧 ${num(data.unresolvedFrames)}${data.timeBase&&data.timeBase.estimatedBattleSeconds!=null?` · 对局时长 ≈ ${clock(data.timeBase.estimatedBattleSeconds)}（15 帧/秒，±1s）`:''}。移动是输入方向角（±180°，与方向技能瞄准同角度系）；人机局 AI 英雄不发输入命令。</p>`;
  const chart=container.querySelector('#input-chart');
  const movers=data.heroes.filter(h=>h.moves>0);
  if(!chart||!movers.length)return;
  chart.hidden=false;
  chart.innerHTML=`<div class="panel-header"><h2>方向时间轴</h2><span class="helper">按帧采样显示</span></div><div class="replay-import-grid"><label class="field">英雄<select id="input-hero">${movers.map(h=>`<option value="${esc(h.unit)}">${esc(h.hero||'unit '+h.unit)} · ${h.camp===1?'蓝':'红'} ${num((h.slot??0)+1)}</option>`).join('')}</select></label></div><div id="input-chart-body"></div><div id="input-path-chart" class="section-gap" hidden></div>`;
  const body=chart.querySelector('#input-chart-body');
  const show=async unit=>{
   body.innerHTML='<div class="helper">正在读取该英雄的输入事件…</div>';
   try{
    const hero=await api(`/api/replays/${esc(container.dataset.replayId)}/inputs?unit=${encodeURIComponent(unit)}`);
    drawInputChart(body,hero.hero||{},data.timeBase);
    const pathHost=chart.querySelector('#input-path-chart');
    if(pathHost)drawPathChart(pathHost,hero.hero||{});
   }catch(error){body.innerHTML=`<div class="notice">读取失败：${esc(error.message)}</div>`;}
  };
  const select=chart.querySelector('#input-hero');
  select.onchange=()=>show(select.value);
  await show(select.value);
 }catch(error){
  host.innerHTML=`<p class="helper">输入时间轴读取失败：${esc(error.message)}</p>`;
 }
}

function checkpointSection(r){
 const header=`<div class="panel-header"><div><h2>检查点状态（引擎实测）</h2><div class="panel-subtitle">state.jsonl 检查点快照 · 金币/KDA/等级按行实测 · 位置不进入本表</div></div><span class="tag gray" id="checkpoint-status">读取中…</span></div>`;
 return `<section class="panel section-gap" id="checkpoint-state">${header}<div class="form-section" id="checkpoint-state-body"><div class="helper" role="status">正在读取检查点状态…</div></div><div class="form-section"><form id="checkpoint-upload" data-replay-id="${esc(r.id)}"><div class="replay-import-grid"><label class="field">检查点状态 JSONL / JSON<input id="checkpoint-file" type="file" accept=".jsonl,.json" required></label><button class="button" type="submit">导入检查点</button></div><p class="helper">一行一个 state.jsonl 行；也接受 {"rows":[...]}。上限 200,000 行 / 64 MB。只导入引擎检查点，不从截图或插值补造金币。</p></form></div><div class="summary-footnote">金币/KDA/等级只在 sources 含 arena_stats 的行标为引擎实测；HP 为归一化采样（上限约 1000，不是绝对血量）；x/z 来自未通过验证的轨迹重建，不进入本表；插值帧未并入（独立 UI 误差上限约 1,012 金币 / 3.68 KDA，09:01）。</div></section>`;
}

function checkpointSourceTags(row){
 const sources=String(row.sources||'').split(';').map(value=>value.trim()).filter(Boolean);
 const tags=[];
 if(sources.includes('arena_stats'))tags.push('<span class="tag" title="arena_*.bin 检查点记录：金币/KDA/等级引擎实测">引擎实测</span>');
 const engineHp=row.hp_current!=null||row.hp_max!=null||row.hp_ratio!=null||row.abs_hp_estimate!=null;
 const hpSource=sources.includes('unit_object')||sources.includes('arena_unit_object')||sources.includes('arena_stats');
 if(engineHp&&hpSource)tags.push('<span class="tag blue" title="unit 对象 +0x08/+0x10 归一化血量；只有 abs_hp_estimate 非空时才是绝对估算">HP 实测</span>');
 else if(engineHp)tags.push('<span class="tag amber" title="该行有 HP 数值，但没有 unit/arena 引擎来源；不标为实测">HP 未标注来源</span>');
 if(sources.includes('event_windows'))tags.push('<span class="tag gray" title=".abc 事件窗口直接解码；只证明该帧有事件，不是状态实测">文件解码</span>');
 if(sources.includes('trajectories')||row.pos_source)tags.push('<span class="tag amber" title="轨迹重建 RMS 17.8% 地图跨度，未通过验证；本表不展示 x/z">轨迹·估算</span>');
 if(!tags.length)tags.push('<span class="tag gray">未标注来源</span>');
 return tags.join(' ');
}

function drawCheckpointState(host,data){
 const rows=Array.isArray(data.rows)?data.rows:[];
 const measured=rows.filter(checkpointMeasured);
 if(!measured.length){
  host.innerHTML=`<div class="empty">已导入 ${num(rows.length)} 行，但没有金币/KDA/等级/HP 实测字段（全是事件行）。不展示推断值。</div>`;
  return;
 }
 const ordered=[...measured].sort((a,b)=>Number(a.time_s??0)-Number(b.time_s??0)||Number(a.camp??9)-Number(b.camp??9)||Number(a.slot??9)-Number(b.slot??9)||String(a.player||'').localeCompare(String(b.player||''),'zh'));
 const shown=ordered.slice(0,600);
 const kda=row=>{
  if(row.kills==null||row.deaths==null||row.assists==null)return '—';
  return `<strong>${num(row.kills)}/${num(row.deaths)}/${num(row.assists)}</strong><div class="helper">KDA ${fixed((row.kills+row.assists)/Math.max(1,row.deaths),2)}</div>`;
 };
 const hp=row=>{
  const parts=[];
  if(row.hp_ratio!=null)parts.push(`<strong>${pct(Number(row.hp_ratio)*100,1)}</strong>`);
  if(row.hp_current!=null||row.hp_max!=null)parts.push(`<div class="helper">${row.hp_current!=null?num(row.hp_current):'—'}/${row.hp_max!=null?num(row.hp_max):'—'} 归一</div>`);
  else if(row.hp_ratio!=null)parts.push('<div class="helper">归一化比例</div>');
  if(row.abs_hp_estimate!=null)parts.push(`<div class="helper">绝对 ≈ ${num(row.abs_hp_estimate)}（估算）</div>`);
  return parts.length?parts.join(''):'—';
 };
 const tableRows=shown.map(row=>{
  const camp=row.camp===1?['蓝','blue']:row.camp===2?['红','red']:['—','gray'];
  const slot=row.slot!=null?`<div class="helper">槽位 ${num(Number(row.slot)+1)}</div>`:'';
  return `<tr><td><strong>${esc(row.time_mmss||clock(row.time_s))}</strong><div class="helper">${fixed(row.time_s,1)}s</div></td><td><span class="tag ${camp[1]}">${camp[0]}</span>${slot}</td><td><strong>${esc(row.player||'—')}</strong></td><td>${esc(row.hero||'—')}</td><td>${num(row.gold)}</td><td>${kda(row)}</td><td>${row.level!=null?num(row.level):'—'}</td><td>${hp(row)}</td><td>${checkpointSourceTags(row)}</td></tr>`;
 }).join('');
 const source=data.source||{},counts=data.counts||{},confidence=data.confidence||{};
 const times=(counts.checkpointTimes||[]).map(time=>clock(time)).join(' · ')||'—';
 const summaryTags=[`<span class="tag gray">${num(rows.length)} 行</span>`,`<span class="tag">实测状态 ${num(counts.stateRows??measured.length)}</span>`,`<span class="tag blue">金币/KDA/等级 ${counts.goldRows!=null?num(counts.goldRows):'—'}</span>`,`<span class="tag blue">HP ${counts.hpRows!=null?num(counts.hpRows):'—'}</span>`,`<span class="tag gray">检查点 ${num((counts.checkpointTimes||[]).length)} 个</span>`].join(' ');
 const confLine=`金币 ${esc(confidence.gold||'未知')} · KDA ${esc(confidence.kills||'未知')} · 等级 ${esc(confidence.level||'未知')} · HP ${esc(confidence.hp_ratio||'未知')} · 位置 ${esc(confidence.positions||'未知')}`;
 const truncation=ordered.length>shown.length?`<p class="helper">仅显示前 ${num(shown.length)} 行（共 ${num(ordered.length)} 行实测状态）。</p>`:'';
 host.innerHTML=`<div class="replay-types checkpoint-summary">${summaryTags}</div><div class="table-wrap"><table class="runtime-table checkpoint-table"><thead><tr><th>时间</th><th>阵营/槽位</th><th>选手</th><th>英雄</th><th>金币</th><th>KDA</th><th>等级</th><th>HP（比例 / 绝对）</th><th>来源标签</th></tr></thead><tbody>${tableRows}</tbody></table></div><p class="helper">检查点：${times}。事件行 ${num(counts.eventOnlyRows??0)} 行保持 null，不展示推断值。字段置信度：${confLine}。</p>${truncation}<div class="summary-footnote">来源 ${esc(source.fileName||'未提供文件名')} · ${bytes(source.size)} · SHA-256 ${esc(String(source.sha256||'').slice(0,12))}…${source.importedAt?` · 导入于 ${esc(new Date(Number(source.importedAt)*1000).toLocaleString('zh-CN'))}`:''}</div>`;
}

async function mountCheckpoints(container,replayId,{api,toast}){
 const section=container.querySelector('#checkpoint-state');
 if(!section)return;
 const host=section.querySelector('#checkpoint-state-body');
 const status=section.querySelector('#checkpoint-status');
 const form=section.querySelector('#checkpoint-upload');
 const button=form.querySelector('button');
 const markEngineTag=()=>{
  const tag=container.querySelector('#engine-source-tag');
  if(!tag)return;
  tag.className='tag';
  if(!String(tag.textContent||'').includes('运行时'))tag.textContent='引擎实测 · 检查点已导入';
 };
 const load=async()=>{
  status.className='tag gray';status.textContent='读取中…';
  try{
   const data=await api(`/api/replays/${encodeURIComponent(replayId)}/checkpoints`);
   checkpointImports.set(replayId,true);
   const measured=(data.rows||[]).filter(checkpointMeasured).length;
   status.className='tag';status.textContent=`已导入 · ${num(measured)} 行实测`;
   drawCheckpointState(host,data);
   markEngineTag();
  }catch(error){
   if(String(error.message||'').includes('尚未导入')){
    checkpointImports.delete(replayId);
    status.className='tag gray';status.textContent='未导入';
    host.innerHTML='<div class="empty">尚未导入检查点状态。导入 state.jsonl 后，这里只展示引擎在检查点实测的金币/KDA/等级/血量；缺失字段保持“—”，不插值、不补造。</div>';
   }else{
    status.className='tag amber';status.textContent='读取失败';
    host.innerHTML=`<div class="notice">检查点状态读取失败：${esc(error.message)}</div>`;
   }
  }
 };
 form.onsubmit=async event=>{
  event.preventDefault();
  const file=form.querySelector('input[type=file]').files[0];
  if(!file)return;
  button.disabled=true;
  status.className='tag amber';status.textContent='导入中…';
  try{
   const type=/\.json$/i.test(file.name)?'application/json':'application/x-ndjson';
   const response=await fetch(`/api/replays/${encodeURIComponent(replayId)}/checkpoints?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':type},body:file});
   const value=await response.json().catch(()=>({}));
   if(!response.ok)throw Error(value.detail||'检查点数据导入失败');
   form.reset();
   toast(`检查点状态已导入：${num(value.rowCount??0)} 行`);
   await load();
  }catch(error){
   status.className='tag amber';status.textContent='导入失败';
   toast(error.message,true);
  }finally{button.disabled=false;}
 };
 await load();
}

function sourceLegend(r){
 const conf=r.confidence||{};
 const hasRuntime=!!r.runtime;
 const hasCheckpoints=checkpointImports.get(r.id)===true;
 const hasSamples=!!(r.playerEvents&&r.playerEvents.positions&&r.playerEvents.positions.records);
 const tag=(label,status,note,kind,id)=>`<span class="tag ${kind||''}"${id?` id="${esc(id)}"`:''} title="${esc(note)}">${esc(label)} · ${esc(status)}</span>`;
 return `<section class="panel section-gap"><div class="panel-header"><div><h2>数据来源与置信度</h2><div class="panel-subtitle">不同来源分开标注；估算值只做趋势参考，不进入正式统计</div></div><span class="tag gray">解析档案 ${esc(r.profileId||'未匹配')}</span></div><div class="form-section"><div class="replay-types">${[
  tag('文件解码',conf.container||conf.events||(r.parserVersion?'decoded':'未使用'),'.abc 容器与帧命令直接解码，可复现',''),
  tag('引擎实测',hasRuntime||hasCheckpoints?(hasRuntime?'运行时/检查点已导入':'检查点已导入'):'未导入','GameCore 运行时导出或检查点内存采样；有检查点时间限制',hasRuntime||hasCheckpoints?'':'gray','engine-source-tag'),
  tag('UI 采样',hasSamples?'稀疏':'未使用','截图/小地图/面板读数，时间点与精度有限','amber'),
  tag('估算',conf.positions==='estimated'||hasSamples?'仅趋势':'未使用','由输入方向/插值/积分推算；当前位置验证误差约 17.8% 地图跨度','amber'),
 ].join('')}</div><p class="helper">命令流=文件解码；金币/KDA/等级=检查点引擎实测；小地图/面板=UI 采样；位置积分=估算。来源缺失时保持“未使用”，不补造数据。</p></div></section>`;
}

function v2Section(r){
 return `<div class="replay-v2-timeline" data-replay-id="${esc(r.id)}"></div>`;
}

function detail(r){
 const ope=r.ope,frames=r.frames;
 const blockLabel=b=>`${b.camp?(b.camp===1?'蓝方':'红方')+' · 槽位 '+num(b.position+1):'阵营未知'}${b.bot?' · 电脑':''}${b.self?' · 本地英雄匹配':''}`;
 const mvp=r.mvpScore||{};
 const resultText=mvp.winningCamp?`${mvp.winningCamp==='blue'?'蓝方':'红方'}胜 · MVP ${mvp.winMvp?.nickname||''}${mvp.winMvp?.hero?'（'+mvp.winMvp.hero+'）':''}${mvp.winMvp?.rating!=null?' '+Number(mvp.winMvp.rating).toFixed(2):''}`:'未解析';
 return `${sourceLegend(r)}<section class="panel section-gap"><div class="panel-header"><div><h2>文件解析结果 · ${esc(r.abcFileName)}</h2><div class="panel-subtitle">${esc(r.parserVersion)} · 仅样本版本验证</div></div><a class="button secondary" href="/api/replays/${esc(r.id)}/report" download>导出解析 JSON</a></div><div class="form-section"><div class="notice">${r.warnings.map(esc).join('<br>')}</div><div class="replay-facts"><div><span>版本</span><strong>${r.header.versions.map(esc).join(' / ')}</strong></div><div><span>本地英雄 ID 对应</span><strong>${esc(r.header.localHeroName||'未知')}</strong></div><div><span>录制昵称</span><strong>${esc(r.header.nickname||'未读取')}</strong></div><div><span>配套操作文件</span><strong>${esc(r.opeFileName||'未提供 .ope')}</strong></div><div><span>配对校验</span><strong>${ope?(r.pairingStatus==='recorder-tag-matched'?'录制者标签匹配，同局强证据':'用户选定，尚未核验同局'):'仅 .abc'}</strong></div><div><span>胜负 / MVP</span><strong>${esc(resultText)}</strong></div><div><span>总帧数</span><strong>${num(r.header.totalFrameNum||frames?.records||0)}</strong></div></div><div class="helper replay-hash">.abc SHA-256：${esc(r.abc.sha256)}</div></div><div class="panel-header"><h2>玩家块中的英雄</h2><span class="tag gray">${r.blocks.length?num(r.blocks.length)+' 个块':'未匹配布局'}</span></div>${r.blocks.length?`<div class="replay-heroes">${r.blocks.map(b=>`<div><small>块 ${b.order+1} · ${blockLabel(b)}${b.score!=null?' · 评分 '+Number(b.score).toFixed(2):''}</small><strong>${esc(b.heroName||'未知英雄')}</strong><span>${b.name?esc(b.name)+' · ':''}ID ${num(b.heroId)}${b.entityId?' · 实体 '+num(b.entityId):''} · 偏移 ${num(b.start)}${b.buyEvents!=null?' · 购买 '+num(b.buyEvents)+' 次':''}${b.skillEvents!=null?' · 技能 '+num(b.skillEvents):''}</span></div>`).join('')}</div>`:'<div class="empty">未使用其他版本的固定偏移推断十人英雄。</div>'}<div class="summary-footnote">5247758 新布局可直接读出阵营、槽位与电脑标记；旧布局仍不推断阵营。当前不自动创建比赛、不修改队员身份、不进入英雄胜率统计。</div></section>
 <div class="metrics section-gap"><div class="metric"><div class="metric-label">.abc 文件大小</div><div class="metric-number replay-number">${num(r.abc.size)}<small>B</small></div></div><div class="metric"><div class="metric-label">回放原始事件</div><div class="metric-number replay-number">${r.playerEvents&&(r.playerEvents.buyEcho||r.playerEvents.gold)?num((r.playerEvents.buyEcho||r.playerEvents.gold).unique)+'<small>购买镜像</small>':'—'}</div><div class="metric-note">${r.playerEvents&&(r.playerEvents.buyEcho||r.playerEvents.gold)?`购买 ${num((r.playerEvents.buyEcho||r.playerEvents.gold).unique)} · 技能 ${num(r.playerEvents.skills?.unique)} · 坐标 ${num(r.playerEvents.positions?.records)}`:'未解码'}</div></div><div class="metric"><div class="metric-label">${frames?'帧流记录':'尾部结构记录'}</div><div class="metric-number replay-number">${frames?num(frames.records):r.tlv.start==null?'—':num(r.tlv.records)}</div><div class="metric-note">${frames?'seq '+num(frames.firstSequence)+'–'+num(frames.lastSequence)+' · 容器记录':'容器记录数量，不是游戏事件数量'}</div></div><div class="metric"><div class="metric-label">.ope 第一层结果</div><div class="metric-number replay-number">${ope?num(ope.innerSize):'—'}<small>${ope?'B':''}</small></div></div><div class="metric"><div class="metric-label">.ope 操作流记录</div><div class="metric-number replay-number">${ope?.operatorEvents?.decoded?`${num(ope.operatorEvents.resolvedCount)}<small>/${num(ope.operatorEvents.recordCount)} 条</small>`:(ope?num(ope.operatorStreamBytes)+' B':'—')}</div><div class="metric-note">${ope?.operatorEvents?.decoded?`未定形态 ${num(ope.operatorEvents.unresolvedCount)} 段 · 多解 ${num(ope.operatorEvents.ambiguousChoices)} 处`:'操作流含义未完整解析'}</div></div></div>
 <section class="panel"><div class="panel-header"><h2>结构与覆盖说明</h2></div><div class="form-section"><div class="replay-facts"><div><span>${frames?'帧流解析状态':'尾部解析状态'}</span><strong>${esc(frames?frames.status:r.tlv.status)}</strong></div><div><span>未解释尾部</span><strong>${bytes(frames?frames.trailingBytes:r.tlv.trailingBytes)}</strong></div><div><span>操作记录时间</span><strong>${esc(ope?.timestamp||'未知')}</strong></div><div><span>十人完整状态</span><strong>尚未解码</strong></div></div>${ope?.operatorEvents?.decoded?`<div class="replay-types">${Object.entries(ope.operatorEvents.typeCounts).map(([key,count])=>`<span class="tag gray">${esc(key)} · ${num(count)}</span>`).join('')}</div><p class="helper">操作流事件 ${num(ope.operatorEvents.resolvedCount)}/${num(ope.operatorEvents.recordCount)} 条落在已验证形态上：Touch ${num(ope.operatorEvents.touchCount)} · Move ${num(ope.operatorEvents.moveCount)} · SkillUse ${num(ope.operatorEvents.skillUseCount)} · SkillSlot ${num(ope.operatorEvents.skillSlotCount)} · UIEvent ${num(ope.operatorEvents.uiEventCount)}。未定形态 ${num(ope.operatorEvents.unresolvedCount)} 段（${num(ope.operatorEvents.unresolvedBytes)} 字节）按原样标记；字段名除 frame/unityFrame/eventId 外均为推断，不是击杀、经济或十人状态。</p>`:''}${r.tlv.typeCounts?`<div class="replay-types">${Object.entries(r.tlv.typeCounts).map(([key,count])=>`<span class="tag gray">0x${esc(key)} · ${num(count)}</span>`).join('')}</div>`:''}<p class="helper">${frames?'新构建的帧流只统计了记录容器，payload 尚未映射到击杀、坐标或技能释放。':''}尾部的类型码未命名为击杀、坐标或技能释放。操作流更接近录制设备的本地操作数据；尚不能据此还原整场经济、输出或十人技能时间轴。</p></div></section>${inputsSection(r)}${checkpointSection(r)}${v2Section(r)}${runtimeSection(r)}`;
}

export async function renderReplays(container,{api,toast,isCurrent}){
 let reports=[],selected=null,uploading=false;
 const load=async()=>{const result=await api('/api/replays');reports=result.replays;};
 const draw=()=>{
  if(!isCurrent())return;
  container.innerHTML=`<div class="page-heading"><div><h1>回放文件实验室</h1><p class="subtitle">直接读取 .abc 与 .ope 的已验证结构，保留原文件与解析证据。</p></div><span class="tag amber">实验功能 · 不进入正式统计</span></div><section class="panel"><div class="panel-header"><h2>导入一份回放</h2><span class="helper">单文件 ≤ 16 MB · 本机处理</span></div><div class="form-section"><form id="replay-upload"><div class="replay-import-grid"><label class="field">回放主体 .abc（必选）<input id="replay-abc" type="file" accept=".abc" required></label><label class="field">配套 .ope（可选）<input id="replay-ope" type="file" accept=".ope"></label><button class="button" id="import-replay" type="submit">导入并解析</button></div><p class="helper">每次只导入一份回放；可以先导入 .abc，之后再次选择相同 .abc 并补充 .ope。同名、同版本都不视为已证实同局。</p><div class="helper" id="replay-progress" role="status"></div></form></div></section><section class="panel section-gap"><div class="panel-header"><h2>本机回放记录</h2><span class="tag gray">${reports.length} 份</span></div>${reports.length?`<div class="table-wrap"><table><thead><tr><th>文件</th><th>版本</th><th>英雄块</th><th>第二层操作流</th><th>状态</th><th></th></tr></thead><tbody>${reports.map(r=>`<tr><td><strong>${esc(r.abcFileName)}</strong><div class="helper">${r.ope?'已选配套 .ope':'仅主体文件'}</div></td><td>${r.header.versions.map(esc).join(' / ')}</td><td>${r.blocks.length?num(r.blocks.length):'未匹配'}</td><td>${r.ope?bytes(r.ope.operatorStreamBytes):'未提供'}</td><td><span class="tag amber">结构解析</span></td><td><button class="button ghost" data-replay-detail="${esc(r.id)}">查看结果 →</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">导入本机保存的回放文件，先核对版本与可读取字段。</div>'}</section><div id="replay-detail">${selected?detail(selected):''}</div>`;
  if(selected)mountInputs(container.querySelector('#replay-detail'),selected.id,{api});
  if(selected)mountCheckpoints(container.querySelector('#replay-detail'),selected.id,{api,toast});
  if(selected){const v2Host=container.querySelector('.replay-v2-timeline');if(v2Host)renderV2Timeline(v2Host,{api,replayId:selected.id,heroes:(selected.blocks||[]).map(b=>({name:b.name,hero:b.heroName,id:b.heroId,entity:b.entityId}))});}
  container.querySelectorAll('[data-replay-detail]').forEach(b=>b.onclick=()=>{selected=reports.find(r=>r.id===b.dataset.replayDetail);container.querySelector('#replay-detail').innerHTML=detail(selected);mountInputs(container.querySelector('#replay-detail'),selected.id,{api});mountCheckpoints(container.querySelector('#replay-detail'),selected.id,{api,toast});const v2Host=container.querySelector('.replay-v2-timeline');if(v2Host)renderV2Timeline(v2Host,{api,replayId:selected.id,heroes:(selected.blocks||[]).map(b=>({name:b.name,hero:b.heroName,id:b.heroId,entity:b.entityId}))});container.querySelector('#replay-detail').scrollIntoView({behavior:'smooth',block:'start'});});
  container.querySelector('#replay-upload').onsubmit=async event=>{
   event.preventDefault();if(uploading)return;
   const abc=container.querySelector('#replay-abc').files[0],ope=container.querySelector('#replay-ope').files[0];
   if(!abc){toast('请选择 .abc 文件',true);return;}
   if([abc,ope].some(f=>f&&f.size>16*1024*1024)){toast('单个回放文件请小于 16 MB',true);return;}
   uploading=true;container.querySelector('#import-replay').disabled=true;
   const progress=container.querySelector('#replay-progress');
   try{
    const upload=async file=>{progress.textContent='正在本机校验 '+file.name+'…';const response=await fetch('/api/replays/files?name='+encodeURIComponent(file.name),{method:'POST',body:file});const value=await response.json();if(!response.ok)throw Error(value.detail||'回放文件上传失败');return value;};
    const a=await upload(abc),o=ope?await upload(ope):null;
    progress.textContent='正在读取容器与双层压缩结构…';
    const result=await api('/api/replays/import','POST',{abcFileId:a.id,opeFileId:o?.id||null});
    selected=result.report;await load();draw();toast(result.changed?'回放已保存并解析；实验结果未计入比赛统计':'这份回放已存在，未重复导入');
   }catch(error){toast(error.message,true);if(isCurrent()){progress.textContent='未完成导入：'+error.message;container.querySelector('#import-replay').disabled=false;}}
   finally{uploading=false;}
  };
 };
 container.addEventListener('submit',async event=>{
  const form=event.target.closest('#runtime-upload');
  if(!form)return;
  event.preventDefault();
  const file=form.querySelector('input[type=file]').files[0];
  if(!file)return;
  if(file.size>8*1024*1024){toast('运行时数据请小于 8 MB',true);return;}
  const replayId=form.dataset.replayId,button=form.querySelector('button');
  button.disabled=true;
  try{
   const response=await fetch('/api/replays/'+encodeURIComponent(replayId)+'/runtime',{method:'POST',body:file});
   const value=await response.json();
   if(!response.ok)throw Error(value.detail||'运行时数据导入失败');
   await load();selected=reports.find(r=>r.id===replayId)||selected;
   if(isCurrent()){draw();toast('运行时数据已导入；只进入实验分析');}
  }catch(error){if(isCurrent())toast(error.message,true);button.disabled=false;}
 });
 container.innerHTML='<div class="loading">正在打开本机回放库…</div>';
 try{await load();draw();}catch(error){if(isCurrent())container.innerHTML='<div class="notice">回放库读取失败，请确认服务仍在运行。</div>';toast(error.message,true);}
}
