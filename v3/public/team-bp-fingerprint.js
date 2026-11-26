/* 战队详情 · 两轮 BP 指纹内核
   只消费 team_deep 的逐局 draft.events；不在这里猜时间戳，也不把同时 Ban 当先后。 */

const CORE_TYPES = new Set(['战边', '刺野', '战野', '法刺', '游射', '呆射']);
const FRONT_TYPES = new Set(['坦边', '坦野', '保护辅', '开团辅']);
const PHASES = ['ban1', 'pick1', 'ban2', 'pick2'];
const TARGET_LABELS = {
  hero: '已亮英雄', laneType: '同路同型', lane: '同路针对', archetype: '同类型针对',
  core: '核心位针对', front: '前排型针对', other: '其他', unknown: '首轮未知',
};

export const RESPONSE_PHASES = {
  'r1-p1': { label: '第一轮', source: '我方 R1 Ban', response: '对方 P1 首抢', next: '对方 P1 阵容' },
  'p1-r2': { label: '第二轮', source: '对方 P1 已亮', response: '我方 R2 Ban 针对', next: '对方 P2 补位' },
  'r2-p2': { label: '第二轮', source: '我方 R2 Ban', response: '对方 P2 补位', next: 'P2 选择' },
};

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const uniqueGames = (list) => [...new Set((list || []).filter(Boolean))];

export function resultOf(game) {
  if (game?.opponentWin === true) return 'win';
  if (game?.opponentWin === false) return 'loss';
  return null;
}

export function eventsOf(game) {
  return [...(game?.draft?.events || [])]
    .filter((event) => event?.hero && (event.action === 'ban' || event.action === 'pick'))
    .sort((a, b) => (Number(a.order) || 0) - (Number(b.order) || 0));
}

function phaseOf(event, game) {
  const raw = String(event?.phase || '');
  if (PHASES.includes(raw)) return raw;
  if (raw === 'ban' || raw === 'pick' || raw === 'decider') return raw;
  const profile = game?.draft?.ruleProfile || '';
  if (profile === 'rank-20') return event?.action === 'ban' ? 'ban' : 'pick';
  const order = Number(event?.order) || 0;
  if (order <= 4) return 'ban1';
  if (order <= 10) return 'pick1';
  return event?.action === 'ban' ? 'ban2' : 'pick2';
}

export function phaseEvents(game, phase, side = '') {
  return eventsOf(game).filter((event) => phaseOf(event, game) === phase
    && (!side || event.side === side));
}

export function roundsOf(game) {
  const rounds = {};
  for (const phase of PHASES) {
    rounds[phase] = { own: phaseEvents(game, phase, 'own'), enemy: phaseEvents(game, phase, 'enemy') };
  }
  return rounds;
}

export function targetKind(ban, firstPicks) {
  const picks = (firstPicks || []).filter((pick) => pick?.hero);
  if (!ban?.hero || !picks.length) return 'unknown';
  if (picks.some((pick) => pick.hero === ban.hero)) return 'hero';
  const sameLane = !!ban.lane && picks.some((pick) => pick.lane === ban.lane);
  const sameType = !!ban.archetype && picks.some((pick) => pick.archetype === ban.archetype);
  if (sameLane && sameType) return 'laneType';
  if (sameLane) return 'lane';
  if (sameType) return 'archetype';
  if (CORE_TYPES.has(ban.archetype) && picks.some((pick) => CORE_TYPES.has(pick.archetype))) return 'core';
  if (FRONT_TYPES.has(ban.archetype) && picks.some((pick) => FRONT_TYPES.has(pick.archetype))) return 'front';
  return 'other';
}

function countRows(items, keyOf, total = items.length) {
  const map = new Map();
  for (const item of items) {
    const key = keyOf(item);
    if (key == null || key === '') continue;
    const row = map.get(key) || { key, count: 0, list: [] };
    row.count++;
    if (item.game) row.list.push(item.game);
    map.set(key, row);
  }
  return [...map.values()]
    .map((row) => ({ ...row, games: row.count, list: uniqueGames(row.list), share: total ? row.count / total * 100 : null }))
    .sort((a, b) => b.count - a.count || String(a.key).localeCompare(String(a.key), 'zh-CN'));
}

function eventRows(entries, field, total = entries.length) {
  return countRows(entries, (entry) => entry.event?.[field] || '未标注', total)
    .map((row) => {
      const sample = entries.find((entry) => (entry.event?.[field] || '未标注') === row.key)?.event || {};
      return { ...row, value: row.key, hero: sample.hero || row.key, lane: sample.lane || '', archetype: sample.archetype || '' };
    });
}

function structureOf(games) {
  const lineups = games.map((game) => ({ game, lineup: game.sides?.enemy?.lineup }))
    .filter((entry) => entry.lineup);
  const cores = lineups.filter((entry) => finite(entry.lineup.cores));
  const fronts = lineups.filter((entry) => finite(entry.lineup.front));
  const avg = (rows, key) => {
    const values = rows.map((row) => row.lineup[key]).filter(finite);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  };
  return {
    known: lineups.length,
    coreRows: countRows(cores, (entry) => entry.lineup.cores, cores.length),
    avgCores: avg(cores, 'cores'),
    noFrontRate: fronts.length ? fronts.filter((entry) => entry.lineup.front === 0).length / fronts.length * 100 : null,
    noFrontGames: fronts.filter((entry) => entry.lineup.front === 0).map((entry) => entry.game),
    avgControls: avg(lineups, 'controls'),
    avgEngage: avg(lineups, 'engage'),
    avgPeel: avg(lineups, 'peel'),
    avgDamage: avg(lineups, 'damage'),
  };
}

function summarize(games) {
  const entries = games.map((game) => ({ game, rounds: roundsOf(game) }));
  const withGame = (entry, phase, side, index = 0) => {
    const event = entry.rounds[phase]?.[side]?.[index];
    return event ? { event, game: entry.game } : null;
  };
  const first = entries.map((entry) => withGame(entry, 'pick1', 'enemy', 0)).filter(Boolean);
  const firstBans = entries.map((entry) => withGame(entry, 'ban1', 'enemy', 0)).filter(Boolean);
  const ownFirstBans = entries.map((entry) => withGame(entry, 'ban1', 'own', 0)).filter(Boolean);
  const ownBan2 = entries.flatMap((entry) => entry.rounds.ban2.own.map((event) => ({ event, game: entry.game })));
  const enemyBan2 = entries.flatMap((entry) => entry.rounds.ban2.enemy.map((event) => ({ event, game: entry.game })));
  const enemyP2 = entries.flatMap((entry) => entry.rounds.pick2.enemy.map((event) => ({ event, game: entry.game })));
  const targetRows = ownBan2.map((entry) => ({
    ...entry,
    kind: targetKind(entry.event, roundsOf(entry.game).pick1.enemy),
  }));
  return {
    n: games.length,
    firstPickLanes: eventRows(first, 'lane'),
    firstPickHeroes: eventRows(first, 'hero'),
    firstPickTypes: eventRows(first, 'archetype'),
    firstBanLanes: eventRows(firstBans, 'lane'),
    ownFirstBanLanes: eventRows(ownFirstBans, 'lane'),
    ownBan2Lanes: eventRows(ownBan2, 'lane'),
    enemyBan2Lanes: eventRows(enemyBan2, 'lane'),
    targetKinds: countRows(targetRows, (entry) => entry.kind, targetRows.length)
      .map((row) => ({ ...row, label: TARGET_LABELS[row.key] || row.key })),
    secondPickLanes: eventRows(enemyP2, 'lane'),
    secondPickHeroes: eventRows(enemyP2, 'hero'),
    structure: structureOf(games),
  };
}

export function buildFingerprint(games) {
  const known = (games || []).filter((game) => game?.draft?.known && eventsOf(game).length);
  const win = known.filter((game) => resultOf(game) === 'win');
  const loss = known.filter((game) => resultOf(game) === 'loss');
  const unknown = known.filter((game) => resultOf(game) === null);
  return {
    known, win, loss, unknown,
    winData: summarize(win), lossData: summarize(loss),
    assumed: known.filter((game) => game.draft?.orderAssumed).length,
    parallel: known.filter((game) => eventsOf(game).some((event) => event.action === 'ban' && event.parallel)).length,
    profiles: [...new Set(known.map((game) => game.draft?.ruleProfile).filter(Boolean))],
  };
}

export function matchesCondition(game, condition) {
  if (!condition) return true;
  const rounds = roundsOf(game);
  const first = rounds.pick1.enemy[0];
  const second = rounds.pick2.enemy[0];
  const ownBan2 = rounds.ban2.own;
  switch (condition.type) {
    case 'firstPickLane': return first?.lane === condition.value;
    case 'firstPickHero': return first?.hero === condition.value;
    case 'firstPickType': return first?.archetype === condition.value;
    case 'firstBanLane': return rounds.ban1.enemy[0]?.lane === condition.value;
    case 'ownFirstBanLane': return rounds.ban1.own[0]?.lane === condition.value;
    case 'ownBan2Lane': return rounds.ban2.own.some((ban) => ban.lane === condition.value);
    case 'targetKind': return ownBan2.some((ban) => targetKind(ban, rounds.pick1.enemy) === condition.value);
    case 'secondPickLane': return second?.lane === condition.value;
    case 'secondPickHero': return second?.hero === condition.value;
    case 'core': return game.sides?.enemy?.lineup?.cores === condition.value;
    case 'noFront': return game.sides?.enemy?.lineup?.front === 0;
    default: return true;
  }
}

export function filterByCondition(games, condition) {
  return (games || []).filter((game) => matchesCondition(game, condition));
}

function sourceRow(key, event, game) {
  return {
    key, hero: event?.hero || key, lane: event?.lane || '', archetype: event?.archetype || '',
    count: 0, wins: 0, list: [], responses: new Map(), next: new Map(),
  };
}

function addResponse(row, key, event, game, label = '') {
  const item = row.responses.get(key) || { key, label: label || key, hero: event?.hero || key, lane: event?.lane || '', count: 0, list: [] };
  item.count++;
  item.list.push(game);
  row.responses.set(key, item);
}

function addNext(row, key, event, game) {
  const item = row.next.get(key) || { key, hero: event?.hero || key, lane: event?.lane || '', archetype: event?.archetype || '', count: 0, list: [] };
  item.count++;
  item.list.push(game);
  row.next.set(key, item);
}

function finishRows(map) {
  return [...map.values()].map((row) => ({
    ...row,
    games: row.count,
    list: uniqueGames(row.list),
    responses: [...row.responses.values()].map((item) => ({ ...item, list: uniqueGames(item.list) }))
      .sort((a, b) => b.count - a.count || String(a.key).localeCompare(String(b.key), 'zh-CN')),
    next: [...row.next.values()].map((item) => ({ ...item, list: uniqueGames(item.list) }))
      .sort((a, b) => b.count - a.count || String(a.key).localeCompare(String(b.key), 'zh-CN')),
  })).sort((a, b) => b.count - a.count || String(a.key).localeCompare(String(a.key), 'zh-CN'));
}

export function buildConditional(games, phase = 'p1-r2') {
  const known = (games || []).filter((game) => game?.draft?.known && eventsOf(game).length);
  const rows = new Map();
  for (const game of known) {
    const rounds = roundsOf(game);
    const result = resultOf(game);
    if (phase === 'r1-p1') {
      const first = rounds.pick1.enemy[0];
      for (const ban of rounds.ban1.own) {
        const row = rows.get(ban.hero) || sourceRow(ban.hero, ban, game);
        row.count++; row.wins += result === 'win' ? 1 : 0; row.list.push(game);
        if (first) addResponse(row, first.hero, first, game);
        for (const pick of rounds.pick1.enemy) addNext(row, pick.hero, pick, game);
        rows.set(ban.hero, row);
      }
    } else if (phase === 'r2-p2') {
      for (const ban of rounds.ban2.own) {
        const row = rows.get(ban.hero) || sourceRow(ban.hero, ban, game);
        row.count++; row.wins += result === 'win' ? 1 : 0; row.list.push(game);
        for (const pick of rounds.pick2.enemy) addResponse(row, pick.hero, pick, game);
        rows.set(ban.hero, row);
      }
    } else {
      for (const first of rounds.pick1.enemy) {
        const row = rows.get(first.hero) || sourceRow(first.hero, first, game);
        row.count++; row.wins += result === 'win' ? 1 : 0; row.list.push(game);
        for (const ban of rounds.ban2.own) {
          const kind = targetKind(ban, [first]);
          addResponse(row, kind, ban, game, TARGET_LABELS[kind] || kind);
        }
        for (const pick of rounds.pick2.enemy) addNext(row, pick.hero, pick, game);
        rows.set(first.hero, row);
      }
    }
  }
  return {
    phase, known,
    win: known.filter((game) => resultOf(game) === 'win').length,
    loss: known.filter((game) => resultOf(game) === 'loss').length,
    unknown: known.filter((game) => resultOf(game) === null).length,
    rows: finishRows(rows),
  };
}

export function trajectoryOf(game) {
  const events = eventsOf(game);
  const phases = [...new Set(events.map((event) => phaseOf(event, game)))];
  return phases.map((phase) => ({ phase, events: events.filter((event) => phaseOf(event, game) === phase) }));
}
