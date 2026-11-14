/* Pure, per-match recap guards. Missing evidence is null, never zero or enemy-owned. */
export const normalizedCamp = (camp) => ({ left: 'blue', right: 'red' })[camp] || camp;

export function sampleNear(rows, time, getTime = (row) => row.t, maxGapSeconds = 45) {
  if (!Number.isFinite(time) || !Array.isArray(rows)) return null;
  let best = null;
  let distance = Infinity;
  for (const row of rows) {
    const pointTime = getTime(row);
    if (!Number.isFinite(pointTime)) continue;
    const gap = Math.abs(pointTime - time);
    if (gap < distance) { best = row; distance = gap; }
  }
  return distance <= maxGapSeconds ? best : null;
}

export function teamTotal(players, camp, field) {
  const members = (players || []).filter((p) => normalizedCamp(p.camp) === normalizedCamp(camp));
  if (members.length !== 5 || members.some((p) => p.partial === true || !Number.isFinite(p[field]))) return null;
  return members.reduce((sum, p) => sum + p[field], 0);
}

export function economyDirection(delta) {
  if (!Number.isFinite(delta)) return '未知';
  return delta > 0 ? '利于本队' : delta < 0 ? '利于对手' : '持平';
}

export function eventSide(killerCamp, ownCamp) {
  const killer = normalizedCamp(killerCamp);
  const own = normalizedCamp(ownCamp);
  if (!['blue', 'red'].includes(killer) || !['blue', 'red'].includes(own)) return null;
  return killer === own ? 'own' : 'foe';
}

export function laneRealisation(verdict, laneGoldDiff) {
  if (!Number.isFinite(laneGoldDiff)) return null;
  if (verdict === '压制') return laneGoldDiff > 0;
  if (verdict === '劣势') return laneGoldDiff < 0;
  return null;
}
