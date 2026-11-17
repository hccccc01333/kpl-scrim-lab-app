
/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
/** Source-backed research summaries and saved snapshots. */
export function createResearch({esc,fmt,table,icon,pageIntro}) {
 const labels={label:'选手',hero:'英雄',position:'位置',n:'样本',value:'当前值',referenceRows:'参照行数',referencePlayers:'参照选手',percentile:'分位',p50:'中位数',p75:'P75',p90:'P90',bound:'已绑定',mean:'均值',recentMean:'最近均值',recentN:'近期样本',change:'变化',std:'标准差',p10:'P10',iqr:'四分位距',heroes:'英雄数',topHero:'最常用英雄',topShare:'头部占比',hhi:'集中度',effectiveHeroes:'有效英雄数',entropy:'熵',games:'对局',decided:'有胜负',wins:'胜场',losses:'负场',winRate:'胜率',date:'日期',session:'训练组',opponent:'对手',gold4:'4 分钟经济差',gold10:'10 分钟经济差',goldEnd:'末次经济差',earlyDelta:'前期变化',midDelta:'中期变化',lateDelta:'后期变化',result:'结果',matchKey:'对局',startMinute:'开始（分）',endMinute:'结束（分）',goldChange:'经济变化',perspective:'视角',note:'备注'};
 const text=x=>esc(x??'—'); const value=x=>x==null?'—':typeof x==='number'?fmt(x,2):typeof x==='boolean'?(x?'是':'否'):typeof x==='object'?text(JSON.stringify(x)):text(x);
 const header=(title,sub)=>pageIntro(title,sub);
 const section=(title,sub,body)=>body?`<section class="section"><div class="section-heading"><div><h2>${text(title)}</h2><p>${text(sub||'')}</p></div></div>${body}</section>`:'';
 function body(result) {
  const rows=result.rows||[], cols=result.columns||[];
  const metrics=['effectiveHeroes','winRate','recentMean','mean','n']; const metric=metrics.find(k=>cols.includes(k)&&rows.some(r=>typeof r[k]==='number'&&r[k]>=0));
  const chartRows=metric?rows.filter(r=>typeof r[metric]==='number'&&r[metric]>=0).slice(0,8):[];const max=Math.max(1,...chartRows.map(r=>r[metric]));
  const chart=chartRows.length?`<div class="research-bars">${chartRows.map((r,i)=>`<div><span>${text(r.label||r.hero||r.opponent||r.date||('样本 '+(i+1)))}</span><div><i style="width:${Math.max(0,Math.min(100,r[metric]/max*100))}%"></i></div><b>${value(r[metric])}</b></div>`).join('')}</div>`:'';
  const summary=result.summary?`<div class="research-summary">${Object.entries(result.summary).map(([k,v])=>`<div><span>${text(k)}</span><b>${value(v)}</b></div>`).join('')}</div>`:'';
  return summary+(chart?section('样本概览',`${labels[metric]||metric} · 最多显示前 8 条`,chart):'')+section('结果明细',`${rows.length} 条结果 · ${result.sourceRows??'—'} 条本队输入记录`,table(cols.map(k=>labels[k]||k),rows.map(row=>cols.map(k=>value(row[k])))))+`<div class="scope-note"><span>计算说明</span>${text(result.note||'请结合样本量查看结果。')}</div>`+(result.warnings?.length?`<div class="scope-note"><span>来源提示</span>${result.warnings.map(text).join('；')}</div>`:'');
 }
 function reports(data) {
  const reports=data.reports||[];
  const latest=reports[0]?.createdAt?.slice(0,10)||'—';
  const reportCards=reports.map(r=>`<a class="profile-card report-card" href="#report/${encodeURIComponent(r.id)}"><div class="profile-card-top"><span>${text('分析快照')}</span><b>${text((r.createdAt||'').slice(0,10))}</b></div><h3>${text(r.title)}</h3><p>${text('分析快照')} · 保存时的结果与口径</p><span>查看报告 →</span></a>`).join('');
  const intro=`<section class="sx-report-hero">
    <div class="sx-report-copy"><span class="sx-eyebrow">REPORT LIBRARY</span><h2>把分析结论保存成可复核的快照</h2><p>保存时会一并记录数据范围、结果和数据指纹；源数据变化后，旧报告仍能按当时的口径回看。</p></div>
    <div class="sx-report-stats"><div><b>${reports.length}</b><span>已保存报告</span></div><div><b>${text(latest)}</b><span>最近保存</span></div></div>
  </section>`;
  const library=reports.length?`<section class="section"><div class="section-heading"><div><h2>已保存报告</h2><p>共 ${reports.length} 份，按保存时间倒序。</p></div></div><div class="profiles-grid sx-report-grid">${reportCards}</div></section>`:'';
  const reportHeader=`<div class="page-intro"><div><h1>复盘与报告</h1><p>训练效果与已保存的分析快照放在同一处；报告保留当时的数据范围和结果。</p></div><div class="intro-actions"><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></div></div>`;
  const reviewNav=`<nav class="sx-subnav" aria-label="复盘子页面"><a href="#reports" aria-current="page">报告库</a><a href="#effect">训练效果</a></nav>`;
  const now=new Date();
  const monday=new Date(now); monday.setDate(now.getDate() - (now.getDay()+6)%7);
  const today=`${monday.getFullYear()}-${String(monday.getMonth()+1).padStart(2,'0')}-${String(monday.getDate()).padStart(2,'0')}`;
  const weekBuilder=`<section class="section sx-week-builder"><div class="section-heading"><div><h2>生成训练周报</h2><p>默认从本周一开始，汇总 7 天内的训练课、对局、目标和复盘；打开后可以打印或保存 PDF。</p></div></div><div class="sx-week-form"><label>周报起始日<input type="date" data-sx-week-start value="${today}"></label><button type="button" class="primary" data-sx-week-go>生成周报 →</button></div></section>`;
  return `<div class="page feature-page sx-page sx-report-page">${reportHeader}${reviewNav}${weekBuilder}${intro}${library}</div>`;
 }
 function report(data){return `<div class="page feature-page">${header(data.title,`保存于 ${data.createdAt}`)}<a class="depth-back" href="#reports">← 返回报告</a><div class="scope-note"><span>结果快照</span>以下内容为保存时的数据与口径，不会随源数据变化。</div>${body(data.result)}</div>`}
 return {reports,report};
}
