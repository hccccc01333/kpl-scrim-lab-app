const esc = (v='') => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const keyOf = r => `${r.side}-${r.slot}-${r.kind}-${r.index}`;
export function openIconReview({imageId,result,draft,catalog,onApply}) {
  const dialog=document.createElement('dialog');dialog.className='icon-review-dialog';
  dialog.setAttribute('aria-label','英雄名称与装备核对');
  const selected=new Map((draft.iconReviews||[]).filter(r=>r.imageId===imageId).map(r=>[keyOf(r),r.catalogId]));
  let side='left',slot=0,kind='hero',query='';
  const cropURL=r=>`/api/images/${imageId}/crop?`+new URLSearchParams(Object.fromEntries(['x1','y1','x2','y2'].map((k,i)=>[k,r.box[i]])));
  const entries=new Map(catalog.entries.map(e=>[e.id,e]));
  const render=()=>{
    const regions=(result.visuals||[]).filter(r=>r.side===side&&r.slot===slot&&r.kind===kind);
    dialog.innerHTML=`<div class="icon-review-heading"><div><p class="eyebrow">VISUAL REVIEW</p><h2>英雄名称与装备核对</h2></div><button class="button secondary" data-close>关闭</button></div><p class="helper">左侧为当前截图裁剪。英雄以头像下方名字为准，近似文字须确认。装备证据不足时保留未知，可搜索目录手动选择。</p><div class="icon-review-controls"><label class="field">截图栏位<select id="icon-row">${['left','right'].flatMap(s=>Array.from({length:5},(_,i)=>{const p=draft.players.find(p=>p.side===s&&p.slot===i);return `<option value="${s}-${i}" ${s===side&&i===slot?'selected':''}>${s==='left'?'左':'右'}侧第 ${i+1} 人${p.hero?' · '+esc(p.hero):''}</option>`;})).join('')}</select></label><div class="tabs"><button class="tab ${kind==='hero'?'active':''}" data-kind="hero">英雄名称</button>${result.kind==='score'?`<button class="tab ${kind==='equipment'?'active':''}" data-kind="equipment">六格装备</button>`:''}</div><input class="control" id="icon-query" placeholder="搜索完整目录，找不到可继续手工填写" value="${esc(query)}" aria-label="搜索英雄或装备"></div><div class="icon-regions">${regions.map(r=>{
      let candidates=r.candidates||[];
      if(query.trim())candidates=catalog.entries.filter(e=>e.kind===kind&&e.name.includes(query.trim())).slice(0,30);
      const chosen=entries.get(selected.get(keyOf(r)));
      return `<section class="icon-region"><div class="icon-source"><img class="${kind==='hero'?'name-crop':''}" src="${cropURL(r)}" alt="${kind==='hero'?'头像下方名字':'第'+(r.index+1)+'格装备'}原图裁剪"><div><strong>${kind==='hero'?'头像下方名字':'装备第 '+(r.index+1)+' 格'}</strong><span>${chosen?'已选：'+esc(chosen.name):'尚未选择，保留未知'}</span></div></div><div class="icon-candidates">${candidates.map(e=>`<button class="icon-candidate ${selected.get(keyOf(r))===e.id?'selected':''}" data-region="${keyOf(r)}" data-entry="${esc(e.id)}">${e.icon?`<img src="${esc(e.icon)}" alt="">`:'<span class="missing-icon">?</span>'}<span>${esc(e.name)}<small>${e.source==='name-ocr'?(e.distance?'近似文字 · ':'文字匹配 · ')+esc(e.raw):e.similarity!==undefined?'相似度 '+e.similarity.toFixed(3)+(e.source==='reviewed'?' · 本机核对样本':''):'目录选择'}</small></span></button>`).join('')||'<p class="helper">没有可靠识别结果。请搜索目录核对，或保留未知。</p>'}</div>${chosen?`<button class="button ghost" data-unselect="${keyOf(r)}">取消这一项的候选选择</button>`:''}</section>`;
    }).join('')}</div><div class="icon-review-footer"><span class="helper">选择 ${selected.size} 项 · 英雄按文字核对，装备样本仅作辅助参照</span><button class="button" id="apply-icons">应用已选图标</button></div>`;
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    dialog.querySelector('#icon-row').onchange=e=>{[side,slot]=e.target.value.split('-');slot=Number(slot);query='';render();};
    dialog.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{kind=b.dataset.kind;query='';render();});
    dialog.querySelector('#icon-query').oninput=e=>{const at=e.target.selectionStart;query=e.target.value;render();const input=dialog.querySelector('#icon-query');input.focus();input.setSelectionRange(at,at);};
    dialog.querySelectorAll('[data-entry]').forEach(b=>b.onclick=()=>{selected.set(b.dataset.region,b.dataset.entry);render();});
    dialog.querySelectorAll('[data-unselect]').forEach(b=>b.onclick=()=>{selected.delete(b.dataset.unselect);render();});
    dialog.querySelector('#apply-icons').onclick=()=>{
      const choices=(result.visuals||[]).filter(r=>selected.has(keyOf(r))).map(r=>{const entry=entries.get(selected.get(keyOf(r)));return {...r,imageId,catalogId:entry.id,name:entry.name};});
      if(!choices.length){dialog.close();return;}
      const changed=choices.filter(r=>r.kind==='hero'&&draft.players.find(p=>p.side===r.side&&p.slot===r.slot)?.hero&&draft.players.find(p=>p.side===r.side&&p.slot===r.slot).hero!==r.name);
      const equipmentChanges=choices.filter(r=>r.kind==='equipment'&&draft.players.find(p=>p.side===r.side&&p.slot===r.slot)?.equipment);
      if((changed.length||equipmentChanges.length)&&!confirm('所选图标将更新对应英雄或装备内容。请确认已对照截图核对。'))return;
      onApply(choices);dialog.close();
    };
  };
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  document.body.append(dialog);render();dialog.showModal();
}
