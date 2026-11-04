from pathlib import Path

# --- datasets page ---
p = Path('web/pipeline-page.js')
s = p.read_text(encoding='utf-8')
start = s.index('export async function renderDatasets(')
new = r'''export async function renderDatasets(container,{api,toast,isCurrent,onUse}){
 const d=await api('/api/studio/datasets');if(!isCurrent())return;
 const list=d.datasets||[];
 const totalRows=list.reduce((sum,item)=>sum+Number(item.after?.rows||0),0);
 const totalGroups=list.reduce((sum,item)=>sum+Number(item.after?.matches||0),0);
 const cards=list.map(item=>`<article class="research-card"><div class="research-card-top"><span class="research-badge ${item.exploratory?'amber':''}">${item.exploratory?'候选探索':'比赛数据'}</span><span class="research-date">${esc(new Date(item.createdAt).toLocaleString('zh-CN'))}</span></div><h3><button class="text-link" data-dataset-detail="${item.id}">${esc(item.title)}</button></h3><div class="research-stats"><span><b>${item.after.rows}</b> 行</span><span><b>${item.after.matches}</b> 组内容</span></div><div class="research-actions"><button class="button" data-dataset-use="${item.id}">用于分析</button><button class="button" data-dataset-model="${item.id}">用于建模</button><button class="text-link" data-dataset-detail="${item.id}">清洗记录</button></div></article>`).join('');
 container.innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">RESEARCH · 数据集</span><h1>数据集</h1><p>每次保存保留独立快照、清洗规则与修订记录；源数据修改不会覆盖历史结果。</p><div class="page-facts"><span>${list.length} 个数据集</span><span>${totalRows} 行</span><span>${totalGroups} 组内容</span></div></div><a class="button primary" href="#clean">清洗并建立数据集 ${'${''}'}</a></div>`
 + (list.length?`<div class="research-card-grid">${cards}</div>`:`<section class="panel"><div class="empty-state"><strong>还没有保存的数据集</strong>先在清洗页预览并保存，结果会作为独立快照保留。<br><a href="#clean">清洗并建立数据集 →</a></div></section>`)
 + `<div id="dataset-detail"></div>`;
 container.querySelectorAll('[data-dataset-use],[data-dataset-model]').forEach(button=>button.onclick=()=>onUse(button.dataset.datasetUse||button.dataset.datasetModel,!!button.dataset.datasetModel));
 container.querySelectorAll('[data-dataset-detail]').forEach(button=>button.onclick=async()=>{try{const value=await api('/api/studio/datasets/'+button.dataset.datasetDetail);if(!isCurrent())return;const box=container.querySelector('#dataset-detail');box.innerHTML=`<div class="section-heading"><h2>${esc(value.title)} · 清洗记录</h2><span class="note" title="用于确认源数据未变化">数据版本 ${esc(value.fingerprint.slice(0,12))}</span></div><section class="panel"><div class="panel-body"><p class="note">输入 ${value.before.rows} 行，输出 ${value.after.rows} 行，${value.logs.length} 条变更。</p><details><summary class="note">清洗规则</summary><pre class="dataset-rule-text">${esc(JSON.stringify(value.rules,null,2))}</pre></details><details><summary class="note">逐项变更</summary><pre class="dataset-rule-text">${esc(JSON.stringify(value.logs.slice(0,200),null,2))}</pre></details></div></section>`;box.scrollIntoView({behavior:'smooth',block:'nearest'});}catch(error){toast(error.message,true);}});
}
'''
p.write_text(s[:start] + new, encoding='utf-8')
print('datasets replaced')

# --- reports page ---
p = Path('web/studio.js')
s = p.read_text(encoding='utf-8')
start = s.index('async function reportsPage(token){')
end = s.index('async function showReport(id)')
new2 = r'''async function reportsPage(token){
 const d=await api('/api/studio/reports');if(token!==generation)return;
 const list=d.reports||[];
 const totalMatches=list.reduce((sum,item)=>sum+Number(item.matches||0),0);
 const methods=new Set(list.map(item=>item.method)).size;
 const methodName=item=>workspace.methods.find(m=>m.key===item.method)?.name||workspace.topics?.find(t=>'topic:'+t.key===item.method)?.name||item.method;
 const cards=list.map(item=>`<article class="research-card"><div class="research-card-top"><span class="research-badge">${esc(methodName(item))}</span><span class="research-date">${esc(new Date(item.createdAt).toLocaleString('zh-CN'))}</span></div><h3><button class="text-link" data-report="${item.id}">${esc(item.title)}</button></h3><div class="research-stats"><span><b>${item.matches}</b> 场记录</span></div><div class="research-actions"><button class="button" data-report="${item.id}">查看记录</button><a class="button" href="/api/studio/reports/${item.id}/export" target="_blank" rel="noopener">导出 HTML</a></div></article>`).join('');
 $('#content').innerHTML=`<div class="page-heading"><div><span class="page-eyebrow">RESEARCH · 研究记录</span><h1>研究记录</h1><p>保存分析设置、结果快照和观察，之后按同一口径复查。</p><div class="page-facts"><span>${list.length} 条记录</span><span>${totalMatches} 场记录</span><span>${methods} 种方法</span></div></div><div class="heading-actions"><a class="button" href="/api/studio/backup">备份记录</a><button class="button" id="restore-research">恢复备份</button><input type="file" id="research-file" accept=".json" hidden><a class="button primary" href="#lab">新建分析 ${icon('arrow')}</a></div></div>`
 + (list.length?`<div class="research-card-grid">${cards}</div>`:`<section class="panel"><div class="empty-state"><strong>还没有保存的研究记录</strong>在分析实验运行结果后，填写标题和观察即可保存。<br><a href="#lab">进入分析实验 →</a></div></section>`)
 + `<p class="note">研究记录保存当时的数据快照与筛选条件。源数据后续修改不会覆盖历史结果；本页备份包含研究结果和清洗数据集。</p>`;
 $('#restore-research').onclick=()=>$('#research-file').click();
 $('#research-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>20*1024*1024)return toast('备份文件应小于 20 MB',true);try{const r=await api('/api/studio/restore',JSON.parse(await f.text()));toast(`已恢复 ${r.added} 条，跳过已有 ${r.skipped} 条`);render();}catch(err){toast(err.message,true);}};
}
'''
p.write_text(s[:start] + new2 + s[end:], encoding='utf-8')
print('reports replaced')
