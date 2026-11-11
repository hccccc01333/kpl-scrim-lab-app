import assert from 'node:assert/strict';
import {hasDraftContent,isRecoverableDraft} from '../web/draft-state.mjs';
const blank=()=>({id:'generated',revision:0,status:'draft',date:'',scores:{left:'',right:''},bp:{bans:{left:[],right:[]},picks:{left:[],right:[]},firstPick:'',notes:''},players:Array.from({length:10},(_,i)=>({side:i<5?'left':'right',slot:i%5,hero:'',playerId:'',sources:{},equipmentSlots:[],reviewed:false}))});
assert.equal(hasDraftContent(blank()),false);
assert.equal(isRecoverableDraft(blank()),false);
for (const key of ['date','opponent','notes','duration']) {const d=blank();d[key]=key==='duration'?0:'填写内容';assert.equal(isRecoverableDraft(d),true);}
const d=blank();d.players[0].kills=0;assert.equal(hasDraftContent(d),true);
assert.equal(isRecoverableDraft(d,[structuredClone(d)]),false);
const reordered={...d,players:d.players.map(p=>Object.fromEntries(Object.entries(p).reverse())),revision:99,reviewed:true};
assert.equal(isRecoverableDraft(reordered,[d]),false);
reordered.players[0].kills=1;assert.equal(isRecoverableDraft(reordered,[d]),true);
assert.equal(isRecoverableDraft({...d,players:[]}),false);
console.log('草稿判定：空白、零值、实际修改、已保存快照、键顺序与格式校验通过');
