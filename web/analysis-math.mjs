// Shared, DOM-free calculations. Missing observations remain missing.
export function finite(value) {
  if (value === null || value === undefined || typeof value === 'boolean' || (typeof value === 'string' && !value.trim())) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function extent(values, {zero = false} = {}) {
  const good = values.map(finite).filter(value => value !== null);
  if (!good.length) return [0, 1];
  let min = Math.min(...good), max = Math.max(...good);
  if (zero) { min = Math.min(0, min); max = Math.max(0, max); }
  if (min === max) { const pad = Math.abs(min) * .1 || 1; min -= pad; max += pad; }
  const pad = (max - min) * .08;
  return [min - pad, max + pad];
}

export function median(values) {
  const good = values.map(finite).filter(value => value !== null).sort((a,b)=>a-b);
  const n = good.length;
  return n ? (good[Math.floor((n-1)/2)] + good[Math.ceil((n-1)/2)]) / 2 : null;
}

export function percentile(value, values) {
  value = finite(value);
  const good = values.map(finite).filter(item => item !== null);
  if (value === null || !good.length) return null;
  if (good.every(item=>item===good[0])) return 50;
  return (good.filter(item=>item<value).length + good.filter(item=>item===value).length/2) / good.length * 100;
}

export function rollingMean(rows, key, window = 5) {
  return rows.map((row,index) => {
    const values = rows.slice(Math.max(0,index-window+1),index+1).map(item=>finite(item[key])).filter(value=>value!==null);
    return {value:values.length ? values.reduce((a,b)=>a+b,0)/values.length : null,n:values.length};
  });
}

export function wilson(wins, decided) {
  wins = finite(wins); decided = finite(decided);
  if (wins === null || decided === null || decided <= 0 || wins < 0 || wins > decided || !Number.isInteger(wins) || !Number.isInteger(decided)) return null;
  const z = 1.959963984540054, p = wins/decided, denominator = 1+z*z/decided;
  const center = (p+z*z/(2*decided))/denominator;
  const half = z*Math.sqrt(p*(1-p)/decided+z*z/(4*decided*decided))/denominator;
  return [Math.max(0,center-half)*100,Math.min(1,center+half)*100];
}

export function cleanTimeline(points) {
  const observed = new Map();
  for (const point of points || []) {
    const t = finite(point.gameTime), blue = finite(point.blueGold), red = finite(point.redGold);
    if (t === null || blue === null || red === null || Math.min(t,blue,red)<0) continue;
    observed.set(t,{...point,gameTime:t,blueGold:blue,redGold:red,diff:blue-red});
  }
  return [...observed.values()].sort((a,b)=>a.gameTime-b.gameTime);
}

export function segments(points, maxGap = 120) {
  const result = [];
  for (const point of points) {
    const current = result.at(-1);
    if (!current || point.gameTime-current.at(-1).gameTime>maxGap) result.push([point]);
    else current.push(point);
  }
  return result;
}

export function sampleCount(row) { return finite(row.matches ?? row.picks) ?? 0; }
