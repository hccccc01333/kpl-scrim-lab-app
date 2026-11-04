// A generated id, default slots and validation flags are not user content.
const present = value => value !== null && value !== undefined && String(value).trim() !== '';
export function hasDraftContent(draft) {
 if (!draft || typeof draft !== 'object') return false;
 if (['date','side','winner','opponent','version','session','duration','notes'].some(key=>present(draft[key]))) return true;
 if (Object.values(draft.scores||{}).some(present)) return true;
 if (['imageIds','events','focusIds'].some(key=>Array.isArray(draft[key])&&draft[key].length)) return true;
 const bp=draft.bp||{};
 if (present(bp.firstPick)||present(bp.notes)||['bans','picks'].some(key=>Object.values(bp[key]||{}).some(values=>Array.isArray(values)&&values.some(present)))) return true;
 return (draft.players||[]).some(player=>['hero','playerId','position','equipment','kills','deaths','assists','gold','damage','taken','participation','rating'].some(key=>present(player[key])));
}
export function isRecoverableDraft(draft, saved=[]) {
 if (!hasDraftContent(draft)||!draft.id||!Array.isArray(draft.players)||draft.players.length!==10) return false;
 const match=saved.find(item=>item.id===draft.id);
 if (!match) return true;
 // Ignore local bookkeeping when detecting a stale buffer of a saved record.
 const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().filter(key=>!['reviewed','updatedAt','createdAt','revision'].includes(key)).map(key=>[key,canonical(value[key])])):value;
 const clean=value=>JSON.stringify(canonical(value));
 return clean(draft)!==clean(match);
}
