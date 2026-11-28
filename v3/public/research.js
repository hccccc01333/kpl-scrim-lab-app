
import { glyph } from './ui-icons.js';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
/* 周报「重点战队」是教练自己维护的名单，不是固定三项。 */
const FOCUS_OPTIONS_KEY = 'sx-weekly-focus-options';
const DEFAULT_FOCUS_OPTIONS = ['KA女子队','SPK','AA俱乐部'];
function readFocusOptions() {
  try {
    const raw = JSON.parse(localStorage.getItem(FOCUS_OPTIONS_KEY) || 'null');
    if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  } catch {}
  return [...DEFAULT_FOCUS_OPTIONS];
}
function saveFocusOptions(list) {
  try { localStorage.setItem(FOCUS_OPTIONS_KEY, JSON.stringify(list)); } catch {}
}
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
  return summary+(chart?section('样本概览',`${labels[metric]||metric} · 最多显示前 8 条`,chart):'')+section('结果明细',`${rows.length} 条结果 · ${result.sourceRows??'—'} 条本队输入记录`,table(cols.map(k=>labels[k]||k),rows.map(row=>cols.map(k=>value(row[k])))))+`<div class="scope-note research-note-body"><span>报告正文</span><p>${text(result.note||'这份快照还没有文字结论，请结合上方结果明细复核。')}</p></div>`+(result.warnings?.length?`<div class="scope-note"><span>来源提示</span>${result.warnings.map(text).join('；')}</div>`:'');
 }
 function reports(data) {
  const reports=data.reports||[];
  const latest=reports[0]?.createdAt?.slice(0,10)||'—';
  const reportCards=reports.map(r=>`<a class="profile-card report-card" href="#report/${encodeURIComponent(r.id)}"><div class="profile-card-top"><span>${text('分析快照')}</span><b>${text((r.createdAt||'').slice(0,10))}</b></div><h3>${text(r.title)}</h3><span>${glyph('book', { size: 18 })}查看报告</span></a>`).join('');
  const intro=`<section class="sx-report-hero">
    <div class="sx-report-copy"><span class="sx-eyebrow">报告库</span><h2>把分析结论保存成可复核的快照</h2><p>先选周期与重点战队，再生成周报；历史报告会保留当时的样本和计算口径。</p></div>
    <div class="sx-report-stats"><div class="sx-report-stat"><b>${fmt(reports.length)}</b><span>已保存报告</span></div><div class="sx-report-stat"><b>${text(latest)}</b><span>最近保存</span></div></div>
  </section>`;
  const library=reports.length
    ?`<section class="section"><div class="section-heading"><div><h2>已保存报告</h2></div></div><div class="profiles-grid sx-report-grid">${reportCards}</div></section>`
    :`<section class="section sx-report-empty"><div class="sx-report-empty-icon">${glyph('book', { size: 30 })}</div><div><h2>还没有保存的报告</h2><p>在上方「生成训练周报」选择起始日与重点战队，第一份报告生成后会自动保存到这里。</p></div></section>`;
  const reportHeader=`<div class="page-intro"><div><h1>报告库</h1></div><div class="intro-actions"><button class="control icon-control" data-action="refresh" aria-label="刷新数据">${glyph('refresh', { size: 18 })}</button></div></div>`;
  const now=new Date();
  const monday=new Date(now); monday.setDate(now.getDate() - (now.getDay()+6)%7);
  const today=`${monday.getFullYear()}-${String(monday.getMonth()+1).padStart(2,'0')}-${String(monday.getDate()).padStart(2,'0')}`;
  let focusTeams=[];
  try { const raw=JSON.parse(localStorage.getItem('sx-weekly-focus-teams')||'[]'); if(Array.isArray(raw)) focusTeams=raw.map(String); } catch {}
  const focusOptions=readFocusOptions();
  const focusBoxes=`<fieldset class="sx-week-focus"><legend>重点战队 · 可自己添加 / 改名 / 删除</legend>
    <div class="sx-week-focus-list">${focusOptions.map((name,i)=>`<span class="sx-week-focus-row">
      <label><input type="checkbox" data-sx-week-team value="${text(name)}" ${focusTeams.includes(name)?'checked':''}>${text(name)}</label>
      <button type="button" class="sx-week-focus-icon sx-week-focus-icon--large" data-sx-focus-rename="${i}" title="改名" aria-label="改名 ${text(name)}">${glyph('edit', { size: 18 })}</button>
      <button type="button" class="sx-week-focus-icon sx-week-focus-icon--large is-del" data-sx-focus-remove="${i}" title="删除" aria-label="删除 ${text(name)}">${glyph('trash', { size: 18 })}</button>
    </span>`).join('')}</div>
    <div class="sx-week-focus-add"><label for="sx-focus-new">添加战队</label><input id="sx-focus-new" type="text" data-sx-focus-new placeholder="输入战队名"><button type="button" data-sx-focus-add>${glyph('pick', { size: 18 })}添加</button></div>
  </fieldset>`;
  const weekBuilder=`<section class="section sx-week-builder"><div class="section-heading"><div><h2>生成训练周报</h2></div></div><div class="sx-week-form"><label>周报起始日<input type="date" data-sx-week-start value="${today}"></label><button type="button" class="primary" data-sx-week-go>${glyph('export', { size: 18 })}生成周报</button><button type="button" class="control" data-sx-week-template>${glyph('edit', { size: 18 })}配置周报模板</button></div>${focusBoxes}</section>`;
  return `<div class="page feature-page sx-page sx-report-page">${reportHeader}${weekBuilder}${intro}${library}</div>`;
 }
 function report(data){return `<div class="page feature-page">${header(data.title,`保存于 ${data.createdAt}`)}<a class="depth-back" href="#reports">${glyph('home', { size: 18 })}返回报告</a><div class="scope-note"><span>结果快照</span>保存当时的数据与口径。</div>${body(data.result)}</div>`}
 return {reports,report};
}
