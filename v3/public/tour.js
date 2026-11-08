/** A short, real-click introduction to the platform. */

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
export function createTour() {
  const key='training-v2-tour-complete-v1';
  let step=-1, active=false, started=false;
  const layer=document.createElement('div'); layer.className='tour-layer'; layer.hidden=true; document.body.append(layer);
  const steps=[
    {title:'从一场对局开始', text:'赛训数据从比赛档案出发。请点击顶部的「对局」。', selector:()=>{
      const desktop=document.querySelector('[data-nav="matches"]');
      if(desktop?.getClientRects().length) return desktop;
      const mobile=document.querySelector('.mobile-menu:not([hidden]) a[href="#matches"]');
      return mobile || document.querySelector('.menu-button');
    }},
    {title:'打开对局复盘', text:'点击一场比赛，查看双方阵容、经济曲线和赛内事件。', selector:()=>document.querySelector('.match-row')},
    {title:'切换舒适的主题', text:'点击这里，浅色和深色主题可以随时切换。', selector:()=>document.querySelector('.theme-button')},
    {title:'选择数据范围', text:'点击「数据范围」，可以按日期、来源和验证数据筛选。各专题若有不同口径，会在页面说明。', selector:()=>document.querySelector('[data-action="filter"]')},
  ];
  const finish=()=>{active=false;step=-1;layer.hidden=true;layer.innerHTML='';localStorage.setItem(key,'1')};
  function card(title,text,buttons,progress='') { return `<div class="tour-card" role="dialog" aria-label="使用教程" aria-live="polite"><div class="tour-card-top"><span>使用教程 ${progress}</span><button data-tour="skip" aria-label="关闭教程">×</button></div><h2>${title}</h2><p>${text}</p><div class="tour-actions">${buttons}</div></div>`; }
  function visible(target){return !!target?.getClientRects().length;}
  function draw(){
    if(!active)return;
    layer.hidden=false;
    if(step===-1){layer.innerHTML=`<div class="tour-full"></div>${card('欢迎来到赛训数据','跟着四次点击，找到对局、复盘、主题与数据范围。也可以随时从顶部的问号重新打开教程。','<button class="tour-quiet" data-tour="skip">稍后再看</button><button class="primary" data-tour="begin">开始体验 →</button>')}`;return}
    if(step>=steps.length){layer.innerHTML=`<div class="tour-full"></div>${card('准备好了','现在可以继续查看对手、英雄与赛训分析；演示数据入口可用来熟悉完整流程。','<button class="primary" data-tour="finish">开始使用</button>','04 / 04')}`;return}
    const item=steps[step],target=item.selector(), found=visible(target);
    if(!found){layer.innerHTML=`<div class="tour-full"></div>${card(item.title,'当前页面没有可操作的目标，可以先跳过这一步。','<button class="tour-quiet" data-tour="skip">跳过教程</button><button class="primary" data-tour="next">下一步 →</button>',`${String(step+1).padStart(2,'0')} / 04`)}`;return}
    let r=target.getBoundingClientRect();
    // Keep the target clear of the bottom instruction card on small screens.
    if (r.bottom > innerHeight - Math.min(250, innerHeight*.3) || r.top < 8) {
      target.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'});
      r=target.getBoundingClientRect();
    }
    const pad=5, x=Math.max(0,r.left-pad),y=Math.max(0,r.top-pad),w=Math.min(innerWidth-x,r.width+pad*2),h=Math.min(innerHeight-y,r.height+pad*2);
    const blocker=(left,top,width,height)=>`<div class="tour-blocker" style="left:${left}px;top:${top}px;width:${Math.max(0,width)}px;height:${Math.max(0,height)}px"></div>`;
    const message=step===0&&target.classList.contains('menu-button')?'请先点击右上角菜单，然后选择「对局」。':item.text;
    layer.innerHTML=blocker(0,0,innerWidth,y)+blocker(0,y,x,h)+blocker(x+w,y,innerWidth-x-w,h)+blocker(0,y+h,innerWidth,innerHeight-y-h)+`<div class="tour-outline" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px"></div>`+card(item.title,message,'<button class="tour-quiet" data-tour="skip">跳过教程</button><span class="tour-hint">请点击高亮区域</span>',`${String(step+1).padStart(2,'0')} / 04`);
    const panel=layer.querySelector('.tour-card'), cardRect=panel.getBoundingClientRect();
    if (cardRect.top < y+h && cardRect.bottom > y && y > cardRect.height+24) {panel.style.top='16px';panel.style.bottom='auto';}
  }
  layer.addEventListener('click',event=>{
    const action=event.target.closest('[data-tour]')?.dataset.tour;
    if(action==='skip'||action==='finish')finish();
    if(action==='begin'||action==='next'){step++;draw()}
  });
  document.addEventListener('click',event=>{
    if(!active||step<0||step>=steps.length||layer.contains(event.target))return;
    const target=steps[step].selector(); if(!target||!target.contains(event.target))return;
    if(step===0&&target.classList.contains('menu-button')){setTimeout(draw,60);return}
    if(step===3){setTimeout(()=>{finish();const body=document.querySelector('#filters .dialog-body');if(body)body.insertAdjacentHTML('afterbegin','<p class="tour-complete">教程完成。你可以在这里选择范围，然后点击应用。</p>')},40);return}
    step++; setTimeout(draw,180);
  },true);
  document.addEventListener('keydown',event=>{if(active&&event.key==='Escape')finish()});
  window.addEventListener('resize',()=>{if(active)draw()});
  window.addEventListener('scroll',()=>{if(active&&step>=0&&step<steps.length)draw()},{passive:true});
  return {
    start(){active=true;started=true;step=-1;draw()},
    afterRender(){if(active){setTimeout(draw,80);return}if(!started&&!localStorage.getItem(key)){started=true;setTimeout(()=>{active=true;step=-1;draw()},300)}}
  };
}
