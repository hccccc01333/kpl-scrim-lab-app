/**
 * 赛事快照桥接：把六个规则模块的「当下内容」与「赛事快照」连起来。
 * 快照存在 /api/v3/rule-snapshots；各模块自己的读写仍走原来的接口。
 */
const DEFAULT_API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

export const SNAPSHOT_MODULES = [
  { key: 'hero_tags', label: '英雄标签', hint: '全部英雄的分路 / 类型 / 能力矩阵' },
  { key: 'counters', label: '克制关系', hint: '英雄克制英雄 + 组合克制组合' },
  { key: 'misc', label: '其他规则', hint: '异常判定 / 指标口径 / 风格标签等' },
  { key: 'lineup_tags', label: '阵容标签', hint: '阵容标签表（整份）' },
  { key: 'combos', label: '组合池设置', hint: '自定义双人 / 三人组合池' },
  { key: 'grade_rules', label: '规则设置', hint: '分路 × 字段的评级规则' },
];

export function currentCompetitionId() {
  try {
    return localStorage.getItem('training-current-competition') || '';
  } catch { return ''; }
}

export function currentCompetitionName() {
  try {
    return localStorage.getItem('training-current-competition-name') || '';
  } catch { return ''; }
}

function apiBase() {
  // 各页面注入的 API_BASE 一致；缺省时按模块所在目录推导。
  return DEFAULT_API_BASE;
}

export async function fetchCompetitions(API_BASE = apiBase()) {
  const response = await fetch(`${API_BASE}/api/studio/workspace/competitions`,
    { headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new Error(`赛事列表读取失败（${response.status}）`);
  const data = await response.json();
  return Array.isArray(data?.competitions) ? data.competitions : [];
}

export async function loadSnapshots(API_BASE = apiBase()) {
  const response = await fetch(`${API_BASE}/api/v3/rule-snapshots`,
    { headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new Error(`快照读取失败（${response.status}）`);
  return response.json();
}

function moduleEndpoint(module, API_BASE) {
  if (module === 'combos') return `${API_BASE}/api/v3/custom-combos`;
  if (module === 'grade_rules') return `${API_BASE}/api/v3/grade-rules`;
  if (module === 'lineup_tags') return `${API_BASE}/api/v3/lineup-tags`;
  return `${API_BASE}/api/v3/rules-center/${module}`;
}

export async function fetchLiveDoc(module, API_BASE = apiBase()) {
  const response = await fetch(moduleEndpoint(module, API_BASE),
    { headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new Error(`当前内容读取失败（${response.status}）`);
  return response.json();
}

/** 把整份当下内容存成当前赛事的快照。调用方应先确保页面改动已保存。 */
export async function saveSnapshot(module, competitionId, summary = '', API_BASE = apiBase()) {
  if (!competitionId) throw new Error('请先在顶栏选择赛事，再保存快照。');
  const doc = await fetchLiveDoc(module, API_BASE);
  const response = await fetch(`${API_BASE}/api/v3/rule-snapshots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ competitionId, module, doc, summary }),
  });
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch { /* 非 JSON 响应 */ }
    throw new Error(detail || `快照保存失败（${response.status}）`);
  }
  document.dispatchEvent(new CustomEvent('rule-snapshots:changed', { detail: { module, competitionId } }));
  return response.json();
}

function restorePayload(module, snapshotDoc, liveDoc) {
  const revision = Number(liveDoc?.revision) || 0;
  if (module === 'combos') {
    return { revision, pairs: snapshotDoc.pairs, trios: snapshotDoc.trios };
  }
  if (module === 'grade_rules') {
    return { revision, subjects: snapshotDoc.subjects };
  }
  if (module === 'lineup_tags') {
    return { revision, tags: snapshotDoc.tags };
  }
  const doc = { ...snapshotDoc, revision };
  return { revision, doc, summary: '从赛事快照恢复当前内容' };
}

/** 用某赛事的快照覆盖模块的当下内容；revision 取当下值，避免乐观锁冲突。 */
export async function restoreSnapshot(module, snapshotDoc, API_BASE = apiBase()) {
  if (!snapshotDoc || typeof snapshotDoc !== 'object') throw new Error('快照内容无效。');
  const live = await fetchLiveDoc(module, API_BASE);
  const payload = restorePayload(module, snapshotDoc, live);
  const response = await fetch(moduleEndpoint(module, API_BASE), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch { /* 非 JSON 响应 */ }
    throw new Error(detail || `恢复快照失败（${response.status}）`);
  }
  document.dispatchEvent(new CustomEvent('rule-snapshots:restored', { detail: { module } }));
  return response.json();
}

export async function deleteSnapshot(module, competitionId, API_BASE = apiBase()) {
  const response = await fetch(`${API_BASE}/api/v3/rule-snapshots`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ competitionId, module }),
  });
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch { /* 非 JSON 响应 */ }
    throw new Error(detail || `快照删除失败（${response.status}）`);
  }
  document.dispatchEvent(new CustomEvent('rule-snapshots:changed', { detail: { module, competitionId } }));
  return response.json();
}

/** 把快照 doc 压成一行摘要，避免快照中心大段刷屏。 */
export function snapshotBrief(module, doc = {}) {
  if (module === 'counters') {
    return `英雄 ${(doc.heroPairs || []).length} 条 · 组合 ${(doc.comboPairs || []).length} 条`;
  }
  if (module === 'hero_tags') {
    return `${Object.keys(doc.heroes || {}).length} 个英雄标签`;
  }
  if (module === 'misc') return `${(doc.entries || []).length} 条规则`;
  if (module === 'lineup_tags') return `${(doc.tags || []).length} 个阵容标签`;
  if (module === 'combos') {
    return `双人 ${(doc.pairs || []).length} · 三人 ${(doc.trios || []).length}`;
  }
  if (module === 'grade_rules') {
    const subjects = Object.values(doc.subjects || {});
    return `${subjects.length} 个分路 · ${subjects.reduce((n, group) => n + Object.keys(group || {}).length, 0)} 个字段`;
  }
  return '';
}
