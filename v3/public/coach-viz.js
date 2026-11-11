/* 教练档案 · 可视化重构
   主语是选中的对手教练，参照系是全部对局。全页只讲执教与 BP 决策：
   战绩、边位、禁用、英雄池、阵容对位、用人与禁用的偏好画像；
   不混入经济 / 推塔 / 击杀这类选手层面的产出指标。
   与「通用跨局分析」「英雄对比」同一套语言：白底、大读数、一分析一形态、
   每卡两个可切换视图、悬停读数、点选换教练、无解释小字。 */

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const es = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n0 = (v) => (isNum(v) ? Math.round(v).toLocaleString('zh-CN') : '—');
const n1 = (v) => (isNum(v) ? v.toFixed(1) : '—');
const pc = (v) => (isNum(v) ? Math.round(v) + '%' : '—');
const sg = (v) => { const r = Math.round(isNum(v) ? v : 0) || 0; return (r < 0 ? '−' : '+') + Math.abs(r).toLocaleString('zh-CN'); };
const tip = (t) => `data-cv-tip="${es(t)}"`;
const wOf = (v, max) => `${clamp((Math.abs(isNum(v) ? v : 0) / Math.max(1, max)) * 100, 0, 100).toFixed(1)}%`;
const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);

const LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
const laneRank = (x) => { const i = LANES.indexOf(x); return i < 0 ? 99 : i; };
const sideName = (s) => (s === 'blue' ? '蓝方' : s === 'red' ? '红方' : '边位未知');

const VIEWS = {
  '01': ['教练席位', '同侪站位'],
  '02': ['两种边位', '本教练的边位'],
  '03': ['全场禁用热度', '禁得准不准'],
  '04': ['五路热门英雄', '本教练的英雄'],
  '05': ['五路对位', '谁拿到更热的英雄'],
  '06': ['教练画像', '四项读数'],
};

export function createCoachBoard({ esc = es } = {}) {
  const state = { board: null, roster: null, teamId: '', views: {} };
  const viewOf = (id) => state.views[id] || 'a';

  /* ── 通用零件 ─────────────────────────────────────────────── */
  function shell(id, a, b) {
    const meta = VIEWS[id] || ['看图', '换个角度'];
    const cur = viewOf(id);
    const one = (k, html) => `<div class="hc-view${cur === k ? ' is-enter' : ''}" data-cv-view="${k}"${cur === k ? '' : ' hidden'}>${html}</div>`;
    return `<div class="hcv" data-cv-viz="${id}">
      <div class="hcv-bar"><div class="hcv-switch" role="group" aria-label="切换视图">
        <button type="button" data-cv-view-btn="a" data-cv-viz="${id}" class="${cur === 'a' ? 'is-on' : ''}">${es(meta[0])}</button>
        <button type="button" data-cv-view-btn="b" data-cv-viz="${id}" class="${cur === 'b' ? 'is-on' : ''}">${es(meta[1])}</button>
      </div></div>
      <div class="hcv-stage">${one('a', a)}${one('b', b)}<div class="hcv-tip" hidden></div></div>
    </div>`;
  }
  const view = (hero, body) => `<div class="hcv-view"><div class="hcv-hero">${hero}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${esc(v)}</b><span>${esc(label)}</span></div>`;
  const icon = (hero, cls = '') => (hero && hero.icon
    ? `<img class="portrait ${cls}" src="${esc(hero.icon)}" alt="${esc(hero.name || '')}">`
    : `<span class="portrait portrait-placeholder ${cls}">${es((hero && hero.name || '?')[0])}</span>`);

  function card(id, name, title, chart, action, method) {
    return `<article class="hc-card" id="cv-analysis-${id}">
      <div class="hc-card-top"><span class="hc-kicker">${id} / 教练档案</span></div>
      <div class="hc-card-name">${es(name)}</div>
      <h3 class="hc-card-title">${title}</h3>
      <div class="hc-card-canvas">${chart}</div>
      <div class="hc-card-foot"><div class="hc-train"><span>怎么用</span><p>${esc(action)}</p></div>
        <a class="hc-open" href="#teambp">战队 BP →</a></div>
      <p class="hc-method"><b>怎么算的</b> ${esc(method)}</p>
    </article>`;
  }

  /* ── 数据准备 ─────────────────────────────────────────────── */
  function normalize(g, teamName) {
    return {
      key: g.key, start: g.start, day: g.day, teamId: g.teamId || '',
      coach: g.coach || '', team: teamName || '',
      side: g.side === 'blue' ? 'red' : g.side === 'red' ? 'blue' : '',
      won: g.result === 'loss' ? true : g.result === 'win' ? false : null,
      duration: g.duration,
      picks: (g.picks?.enemy || []).filter((p) => p && p.name),
      bans: (g.bans?.enemy || []).filter((p) => p && p.name),
      oppPicks: (g.picks?.own || []).filter((p) => p && p.name),
      oppBans: (g.bans?.own || []).filter((p) => p && p.name),
    };
  }

  function prepare(board) {
    const teamName = new Map((board.teams || []).map((t) => [t.id, t.name]));
    const all = (board.games || []).filter(Boolean).map((g) => normalize(g, teamName.get(g.teamId)));
    const mine = all.filter((g) => g.teamId === state.teamId);
    const wins = mine.filter((g) => g.won === true).length;
    const losses = mine.filter((g) => g.won === false).length;
    const played = all.filter((g) => g.won !== null);

    /* 全场热度：教练一方选用 / 禁用，以及对手（本队）的选用。 */
    const heat = (key) => {
      const map = new Map();
      for (const g of all) for (const h of g[key]) {
        const cur = map.get(h.name) || { name: h.name, icon: h.icon, lane: h.lane, n: 0 };
        cur.n += 1;
        if (!cur.lane && h.lane) cur.lane = h.lane;
        map.set(h.name, cur);
      }
      return map;
    };
    const pickHeat = heat('picks');
    const oppPickHeat = heat('oppPicks');
    const banHeat = new Map();
    for (const g of all) for (const h of [...g.bans, ...g.oppBans]) {
      const cur = banHeat.get(h.name) || { name: h.name, icon: h.icon, n: 0 };
      cur.n += 1; banHeat.set(h.name, cur);
    }
    const byN = (map) => [...map.values()].sort((a, b) => b.n - a.n);
    const picks = byN(pickHeat), bans = byN(banHeat);
    const maxPick = Math.max(1, ...picks.map((x) => x.n));
    const maxBan = Math.max(1, ...bans.map((x) => x.n));

    const byLane = LANES.map((lane) => ({ lane, list: picks.filter((p) => p.lane === lane).slice(0, 3) }));

    /* 每位教练：战绩 + 用人与禁用的热门程度。 */
    const byCoach = new Map();
    for (const g of all) {
      if (!g.teamId) continue;
      const cur = byCoach.get(g.teamId) || { teamId: g.teamId, name: g.coach || teamName.get(g.teamId) || '未命名', team: g.team, games: 0, wins: 0, losses: 0, pickSum: 0, pickN: 0, banSum: 0, banN: 0 };
      cur.games += 1;
      if (g.won === true) cur.wins += 1;
      if (g.won === false) cur.losses += 1;
      for (const p of g.picks) { cur.pickSum += (pickHeat.get(p.name)?.n || 1); cur.pickN += 1; }
      for (const b of g.bans) { cur.banSum += (banHeat.get(b.name)?.n || 1); cur.banN += 1; }
      byCoach.set(g.teamId, cur);
    }
    const coaches = [...byCoach.values()].map((c) => ({
      ...c,
      winRate: c.wins + c.losses ? c.wins / (c.wins + c.losses) * 100 : null,
      pickHeat: c.pickN ? c.pickSum / c.pickN : null,
      banHeat: c.banN ? c.banSum / c.banN : null,
    })).sort((a, b) => (b.winRate ?? -1) - (a.winRate ?? -1) || (b.pickHeat || 0) - (a.pickHeat || 0));

    const sideStats = ['blue', 'red'].map((side) => {
      const list = played.filter((g) => g.side === side);
      const w = list.filter((g) => g.won === true).length;
      return { side, n: list.length, wins: w, winRate: list.length ? w / list.length * 100 : null };
    });

    const last = mine[0] || null;
    const pickRank = coaches.slice().sort((a, b) => (b.pickHeat || 0) - (a.pickHeat || 0))
      .findIndex((c) => c.teamId === state.teamId) + 1;
    const banRank = coaches.slice().sort((a, b) => (b.banHeat || 0) - (a.banHeat || 0))
      .findIndex((c) => c.teamId === state.teamId) + 1;
    return {
      all, mine, wins, losses, played, coaches, picks, bans, maxPick, maxBan, byLane,
      pickHeat, oppPickHeat, banHeat, sideStats, last, pickRank, banRank,
      self: coaches.find((c) => c.teamId === state.teamId) || null,
    };
  }

  /* ── 01 带队战绩分析 ──────────────────────────────────────── */
  function card01(d, team, name) {
    const seats = d.coaches.map((c) => {
      const tone = c.winRate === null ? 'thin' : c.winRate >= 50 ? 'win' : 'loss';
      const rec = `${n0(c.wins)} 胜 ${n0(c.losses)} 负`;
      return `<button type="button" class="pb-seat ${tone}${c.teamId === state.teamId ? ' is-on' : ''}" data-cv-pick="${esc(c.teamId)}" ${tip(`${c.name} · ${c.team} · ${rec} · 选用热度 ${n1(c.pickHeat)}`)}>
        <b>${esc(c.name)}</b><em>${rec}</em></button>`;
    }).join('');
    const A = view(
      big(`${n0(d.wins)} 胜 ${n0(d.losses)} 负`, `${name} 带队战绩 · ${n0(d.mine.length)} 局`, d.wins >= d.losses ? 'gold' : 'neg'),
      `<div class="pb-seats">${seats}</div>`
    );
    const sorted = d.coaches.slice().sort((a, b) => (b.pickHeat || 0) - (a.pickHeat || 0));
    const maxRate = Math.max(1, ...sorted.map((c) => c.pickHeat || 0));
    const top = sorted.slice(0, 8);
    const self = d.self;
    const inTop = self && top.some((c) => c.teamId === self.teamId);
    const rows = (inTop || !self ? top : [...top.slice(0, 7), self]);
    const B = view(
      big(`${n0(d.pickRank)}`, `位 / ${n0(d.coaches.length)} 位教练 · 按选用热度`, 'teal'),
      `<div class="hcv-rows">${rows.map((c) => `<div class="hcv-row${c.teamId === state.teamId ? ' is-on' : ''}" ${tip(`${c.name} · ${c.team} · 选用热度 ${n1(c.pickHeat)} · 战绩 ${n0(c.wins)} 胜 ${n0(c.losses)} 负`)}>
        <span class="hcv-row-label">${esc(c.name)}<small>${esc(c.team)}</small></span>
        <i class="hcv-track"><b style="width:${wOf(c.pickHeat, maxRate)}"></b></i>
        <em class="hcv-row-val">${n1(c.pickHeat)}</em>
      </div>`).join('')}</div>`
    );
    const title = d.mine.length
      ? `<em>${esc(name)}</em> 带队 <em>${n0(d.wins)} 胜 ${n0(d.losses)} 负</em>；选用热度 <em>${n1(d.self?.pickHeat)}</em>，在 ${n0(d.coaches.length)} 位教练里排第 ${n0(d.pickRank)}`
      : `还没有 ${esc(name)} 的执教对局`;
    return card('01', '带队战绩分析', title, shell('01', A, B),
      '点席位换教练；胜负接近时，看谁拿到的英雄更热。',
      '战绩按教练一方统计；选用热度＝该教练每局五个英雄在全部对局里的平均出场次数。');
  }

  /* ── 02 边位偏好分析 ──────────────────────────────────────── */
  function card02(d, name) {
    const cols = d.sideStats.map((s) => `<div class="pb-side ${s.side}">
      <span class="pb-side-name">${sideName(s.side)}</span>
      <strong>${pc(s.winRate)}</strong>
      <span class="pb-side-meta">${n0(s.n)} 场 · ${n0(s.wins)} 胜</span>
      <i class="pb-bar"><b class="${s.side === 'blue' ? 'blue' : 'clay'}" style="width:${clamp(s.winRate || 0, 0, 100).toFixed(1)}%"></b></i>
    </div>`).join('');
    const selfSide = d.last?.side || '';
    const A = view(
      big(sideName(selfSide), `${name} 最近一局的边位`, 'gold'),
      `<div class="pb-sides">${cols}</div>`
    );
    const ref = d.sideStats.find((s) => s.side === selfSide);
    const mineWr = d.mine.length ? d.wins / Math.max(1, d.wins + d.losses) * 100 : null;
    const B = view(
      big(selfSide ? sideName(selfSide) : '—', `${name} 的边位`, 'teal'),
      `<div class="cxv-duo">
        <div class="cxv-duo-side"><span>本教练在${sideName(selfSide)}</span><b>${pc(mineWr)}</b><small>${n0(d.mine.length)} 局 · ${n0(d.wins)} 胜</small></div>
        <i class="cxv-duo-arrow">→</i>
        <div class="cxv-duo-side"><span>全场${sideName(selfSide)}</span><b>${pc(ref?.winRate)}</b><small>${n0(ref?.n)} 场 · ${n0(ref?.wins)} 胜</small></div>
        <em class="${isNum(mineWr) && isNum(ref?.winRate) && mineWr < ref.winRate ? 'neg' : ''}">${sg((mineWr || 0) - (ref?.winRate || 0))}<small>个百分点</small></em>
      </div>`
    );
    const blue = d.sideStats[0], red = d.sideStats[1];
    const title = `全场蓝方 <em>${pc(blue.winRate)}</em>、红方 <em>${pc(red.winRate)}</em>；${esc(name)} 最近一局走 <em>${sideName(selfSide)}</em>`;
    return card('02', '边位偏好分析', title, shell('02', A, B),
      '蓝红差距大时，赛前把训练赛优先约在吃亏的那一方。',
      '边位按教练一方记录；胜率＝该边位有胜负的对局里赢下的比例。');
  }

  /* ── 03 禁用策略分析 ──────────────────────────────────────── */
  function card03(d, name) {
    const top = d.bans.slice(0, 10);
    const A = view(
      big(`${n0(d.bans.length)}`, '个不同英雄被禁过 · 全场', 'gold'),
      `<div class="pb-heat">${top.map((b) => `<div class="pb-heat-row" ${tip(`${b.name} · 全场被禁 ${b.n} 次`)}>
        ${icon(b)}
        <span class="pb-heat-name">${esc(b.name)}</span>
        <i class="pb-bar"><b class="gold" style="width:${wOf(b.n, d.maxBan)}"></b></i>
        <strong>${n0(b.n)}</strong>
      </div>`).join('')}</div>`
    );
    const mineBans = d.last ? d.last.bans : [];
    const hit = mineBans.filter((b) => (d.oppPickHeat.get(b.name)?.n || 0) > 0).length;
    const maxUsed = Math.max(1, ...d.picks.map((x) => x.n));
    const B = view(
      big(`${n0(hit)} / ${n0(mineBans.length)}`, '禁到了本队的常用英雄', 'teal'),
      `<div class="pb-heat">${mineBans.map((b) => {
        const used = d.oppPickHeat.get(b.name)?.n || 0;
        const heat = d.banHeat.get(b.name)?.n || 0;
        return `<div class="pb-heat-row" ${tip(`${b.name} · 本队用过 ${used} 次 · 全场被禁 ${heat} 次`)}>
          ${icon(b)}
          <span class="pb-heat-name">${esc(b.name)}<small>${used ? `本队用过 ${used} 次` : '本队没用过'}</small></span>
          <i class="pb-bar"><b class="${used ? 'teal' : 'wash'}" style="width:${wOf(used, maxUsed)}"></b></i>
          <strong>${n0(used)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const title = mineBans.length
      ? `${esc(name)} 的 <em>${n0(mineBans.length)}</em> 个禁用里，<em>${n0(hit)}</em> 个是本队的常用英雄；全场最热的是 <em>${esc(d.bans[0]?.name || '—')}</em>（${n0(d.bans[0]?.n)} 次）`
      : '还没有这位教练的禁用记录';
    return card('03', '禁用策略分析', title, shell('03', A, B),
      '禁到本队常用英雄才算针对；只禁热门，等于按版本走。',
      '热度＝全场双方全部禁用记录里的出现次数；本队用过＝该英雄在本队全部选用里的次数。');
  }

  /* ── 04 英雄池分析 ────────────────────────────────────────── */
  function card04(d, name) {
    const A = view(
      big(`${n0(d.picks.length)}`, '个不同英雄被选过 · 全场', 'gold'),
      `<div class="pb-pool">${d.byLane.map((col) => `<div class="pb-pool-col">
        <span class="pb-pool-lane">${esc(col.lane)}</span>
        ${col.list.length ? col.list.map((p) => `<div class="pb-pool-hero" ${tip(`${p.name} · ${col.lane} · 全场被选 ${p.n} 次`)}>${icon(p)}<b>${esc(p.name)}</b><em>${n0(p.n)}</em></div>`).join('') : '<span class="pb-pool-empty">—</span>'}
      </div>`).join('')}</div>`
    );
    const minePicks = d.last ? d.last.picks.slice().sort((a, b) => laneRank(a.lane) - laneRank(b.lane)) : [];
    const B = view(
      big(`${n0(minePicks.length)}`, `${name} 最近一局的五个英雄`, 'teal'),
      `<div class="pb-heat">${minePicks.map((p) => {
        const n = d.pickHeat.get(p.name)?.n || 0;
        return `<div class="pb-heat-row" ${tip(`${p.name} · ${p.lane || '分路未知'} · 全场被选 ${n} 次`)}>
          ${icon(p)}
          <span class="pb-heat-name">${esc(p.name)}<small>${esc(p.lane || '分路未知')}</small></span>
          <i class="pb-bar"><b class="teal" style="width:${wOf(n, d.maxPick)}"></b></i>
          <strong>${n0(n)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const lanes = new Set(minePicks.map((p) => p.lane)).size;
    const hottest = minePicks.slice().sort((a, b) => (d.pickHeat.get(b.name)?.n || 0) - (d.pickHeat.get(a.name)?.n || 0))[0];
    const title = `${esc(name)} 最近一局覆盖 <em>${n0(lanes)}</em> 条分路，选人里全场最热的是 <em>${esc(hottest?.name || '—')}</em>`;
    return card('04', '英雄池分析', title, shell('04', A, B),
      '英雄池窄的队伍，第二轮直接按热门位去 ban。',
      '热度＝全部对局里该英雄被选中的次数；分路按营地终局名单标注。');
  }

  /* ── 05 阵容对位分析 ──────────────────────────────────────── */
  function card05(d, name) {
    const last = d.last;
    const pairs = LANES.map((lane) => ({
      lane,
      a: (last?.picks || []).find((p) => p.lane === lane) || null,
      b: (last?.oppPicks || []).find((p) => p.lane === lane) || null,
    }));
    const heatOf = (p) => (p ? (d.pickHeat.get(p.name)?.n || 1) : 0);
    const oppHeatOf = (p) => (p ? (d.oppPickHeat.get(p.name)?.n || 1) : 0);
    const hotter = pairs.filter((x) => x.a && x.b && heatOf(x.a) > oppHeatOf(x.b)).length;
    const A = view(
      big(`${n0(hotter)} / 5`, '条路拿到更热门的英雄', hotter >= 3 ? 'gold' : 'neg'),
      `<div class="pb-mu-head"><span>${esc(name)}</span><span></span><span>本队</span></div>
      <div class="pb-matchups">${pairs.map((x) => `<div class="pb-mu" ${tip(`${x.lane} · 本教练 ${x.a?.name || '空'}（全场 ${heatOf(x.a)} 次）· 本队 ${x.b?.name || '空'}（全场 ${oppHeatOf(x.b)} 次）`)}>
        <span class="pb-mu-side">${x.a ? `${icon(x.a)}<b>${esc(x.a.name)}</b>` : '<b class="pb-mu-empty">空</b>'}</span>
        <span class="pb-mu-lane">${esc(x.lane)}</span>
        <span class="pb-mu-side is-opp">${x.b ? `<b>${esc(x.b.name)}</b>${icon(x.b)}` : '<b class="pb-mu-empty">空</b>'}</span>
      </div>`).join('')}</div>`
    );
    const rows = pairs.filter((x) => x.a || x.b);
    const maxDiff = Math.max(1, ...rows.map((x) => Math.abs(heatOf(x.a) - oppHeatOf(x.b))));
    const B = view(
      big(`${n0(rows.reduce((s, x) => s + heatOf(x.a), 0))}`, '五路英雄的全场出场总次数', 'teal'),
      `<div class="cxv-bipolars">${rows.map((x) => {
        const gap = heatOf(x.a) - oppHeatOf(x.b);
        return `<div class="cxv-bipolar" ${tip(`${x.lane} · 本教练 ${x.a?.name || '空'} ${heatOf(x.a)} 次 · 本队 ${x.b?.name || '空'} ${oppHeatOf(x.b)} 次`)}>
          <span>${esc(x.lane)}</span>
          <i class="cxv-bi-track"><em></em><b class="${gap < 0 ? 'neg' : ''}" style="${gap < 0 ? 'right:50%' : 'left:50%'};width:${clamp(Math.abs(gap) / maxDiff * 50, 1.2, 50).toFixed(1)}%"></b></i>
          <strong class="${gap < 0 ? 'neg' : ''}">${sg(gap)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const title = last
      ? `五路对位里 <em>${n0(hotter)}</em> 条路拿到更热门的英雄；本教练用 <em>${esc(pairs.find((x) => x.a)?.a?.name || '—')}</em> 打 <em>${esc(pairs.find((x) => x.b)?.b?.name || '—')}</em>`
      : '还没有可对照的阵容';
    return card('05', '阵容对位分析', title, shell('05', A, B),
      '热门英雄让给本队，就用对位英雄做针对性训练，不要硬抢。',
      '按分路一对一配对，热度取该英雄在全部对局里的出场次数；差值为本教练 − 本队。');
  }

  /* ── 06 教练画像分析 ──────────────────────────────────────── */
  function card06(d, name) {
    const pts = d.coaches.filter((c) => isNum(c.pickHeat) && isNum(c.banHeat));
    const xs = pts.map((c) => c.pickHeat), ys = pts.map((c) => c.banHeat);
    const xMin = Math.min(...xs), xMax = Math.max(1, ...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const xPos = (v) => 6 + (v - xMin) / Math.max(0.001, xMax - xMin) * 88;
    const yPos = (v) => 8 + (v - yMin) / Math.max(0.001, yMax - yMin) * 84;
    const dots = pts.map((c) => `<i class="pb-dot${c.teamId === state.teamId ? ' is-on' : ''}${c.winRate !== null && c.winRate < 50 ? ' neg' : ''}"
      style="left:${xPos(c.pickHeat).toFixed(1)}%;bottom:${yPos(c.banHeat).toFixed(1)}%"
      ${tip(`${c.name} · 选用热度 ${n1(c.pickHeat)} · 禁用热度 ${n1(c.banHeat)} · ${n0(c.wins)} 胜 ${n0(c.losses)} 负`)}></i>`).join('');
    const A = view(
      big(d.self ? n1(d.self.pickHeat) : '—', `${name} 的选用热度 · 全场均值 ${n1(avg(pts.map((c) => c.pickHeat)))}`, 'gold'),
      `<div class="pb-scatter">
        <span class="pb-sc-x"></span><span class="pb-sc-y"></span>
        <span class="pb-sc-lab yt">禁得偏热</span><span class="pb-sc-lab yb">禁得偏冷</span>
        ${dots}
      </div>
      <div class="pb-sc-axis"><span>英雄偏冷</span><span>选用热度</span><span>英雄偏热</span></div>`
    );
    const self = d.self;
    const pickRank = d.pickRank, banRank = d.banRank;
    const laneCount = new Set((d.last?.picks || []).map((p) => p.lane)).size;
    const B = view(
      big(self ? `第 ${n0(pickRank)}` : '—', `位 / ${n0(pts.length)} 位 · 选用热度`, 'teal'),
      `<div class="hcv-rows">
        <div class="hcv-row" ${tip('选用热度越高，越倾向版本热门')}><span class="hcv-row-label">选用热度<small>全场第 ${n0(pickRank)}</small></span><i class="hcv-track"><b style="width:${wOf(self?.pickHeat, xMax)}"></b></i><em class="hcv-row-val">${n1(self?.pickHeat)}</em></div>
        <div class="hcv-row" ${tip('禁用热度越高，越倾向跟版本 ban')}><span class="hcv-row-label">禁用热度<small>全场第 ${n0(banRank)}</small></span><i class="hcv-track"><b class="teal" style="width:${wOf(self?.banHeat, yMax)}"></b></i><em class="hcv-row-val">${n1(self?.banHeat)}</em></div>
        <div class="hcv-row" ${tip('最近一局的分路覆盖')}><span class="hcv-row-label">分路覆盖<small>最近一局</small></span><i class="hcv-track"><b style="width:${wOf(laneCount, 5)}"></b></i><em class="hcv-row-val">${n0(laneCount)} / 5</em></div>
        <div class="hcv-row" ${tip('最近一局的边位')}><span class="hcv-row-label">最近边位<small>${esc(sideName(d.last?.side))}</small></span><i class="hcv-track"><b style="width:${d.last?.side === 'blue' ? 100 : 0}%;background:var(--blue)"></b></i><em class="hcv-row-val">${esc(sideName(d.last?.side))}</em></div>
      </div>`
    );
    const title = self
      ? `${esc(name)} 选用热度 <em>${n1(self.pickHeat)}</em>、禁用热度 <em>${n1(self.banHeat)}</em>，在 ${n0(pts.length)} 位教练里分别排第 ${n0(pickRank)} 与第 ${n0(banRank)}`
      : '还没有这位教练的 BP 记录';
    return card('06', '教练画像分析', title, shell('06', A, B),
      '偏热的教练按版本准备；偏冷的教练要给冷门英雄单独留训练位。',
      '选用 / 禁用热度＝该教练每局五个英雄（或五个禁用）在全部对局里的平均出场次数。');
  }

  /* ── 组装页面 ─────────────────────────────────────────────── */
  function page(d, team, name) {
    const last = d.last;
    const lineup = last ? last.picks.slice().sort((a, b) => laneRank(a.lane) - laneRank(b.lane))
      .map((p) => `<span class="pb-lineup-item">${icon(p)}<em>${esc(p.lane || '')}</em></span>`).join('') : '';
    const bans = last ? last.bans.map((b) => `<span>${esc(b.name)}</span>`).join(' / ') : '';
    const banHit = last ? last.bans.filter((b) => (d.oppPickHeat.get(b.name)?.n || 0) > 0).length : 0;
    const claim = d.mine.length && last
      ? `最近一局 <em>${sideName(last.side)}</em> ${last.won ? '取胜' : last.won === false ? '落败' : ''}：<em>${n0(last.bans.length)}</em> 个禁用里 <em>${n0(banHit)}</em> 个禁到本队常用英雄`
      : `还没有 ${esc(name)} 的执教对局`;
    const fact = last
      ? `选用 ${last.picks.map((p) => esc(p.name)).join(' / ') || '—'}；禁用 ${bans || '—'}。`
      : '';
    const options = (state.board.teams || []).map((t) => {
      const n = (state.roster?.teams || []).find((x) => x.id === t.id)?.coach || t.coach || t.name;
      return `<option value="${esc(t.id)}"${t.id === state.teamId ? ' selected' : ''}>${esc(n)} · ${esc(t.name)}</option>`;
    }).join('');
    const names = ['带队战绩分析', '边位偏好分析', '禁用策略分析', '英雄池分析', '阵容对位分析', '教练画像分析'];
    return `<div class="page pb-page cv-page">
      <div class="page-intro pb-intro"><div><h1>教练档案</h1><p>只看执教与 BP：战绩、边位、禁用、英雄池、阵容对位。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>
      <section class="pb-hero pb-coach-hero">
        <div class="pb-hero-top"><span class="pb-kicker">教练档案 · 对手教练</span>
          <span class="pb-scope">${n0(d.all.length)} 场参照 · ${n0(d.coaches.length)} 位教练</span></div>
        <div class="pb-coach-main">
          <div class="pb-coach-id">
            <span class="pb-coach-team">${esc(team.name || '')}</span>
            <h2 class="pb-coach-name">${esc(name)}</h2>
            <p class="pb-coach-rec"><b>${n0(d.wins)}</b> 胜 <b>${n0(d.losses)}</b> 负 · ${n0(d.mine.length)} 局</p>
          </div>
          <div class="pb-coach-lineup"><span class="pb-lineup-label">最近一局选用</span><div class="pb-lineup">${lineup || '<em class="pb-lineup-empty">—</em>'}</div></div>
        </div>
        <h3 class="pb-claim">${claim}</h3>
        <p class="pb-fact">${fact}</p>
      </section>
      <div class="pb-toolbar">
        <label class="hc-filter"><span>对手教练</span><select data-cv-coach>${options}</select></label>
        <span class="hc-toolbar-count">${n0(d.mine.length)} 局执教记录 · 点席位图也能换教练</span>
        <details class="pb-entry"><summary>录入教练姓名</summary>
          <form class="feature-form pb-entry-form" data-feature-form="coach">
            <label>战队<select name="teamId"><option value="">本队</option>${(state.board.teams || []).map((t) => `<option value="${esc(t.id)}"${t.id === state.teamId ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
            <label>教练姓名<input name="name" maxlength="40" value="${esc(state.roster?.own?.coach || '')}" placeholder="可留空"></label>
            <button class="primary" type="submit">保存</button>
            <p class="form-status" role="status"></p>
          </form>
        </details>
      </div>
      <div class="hc-index" role="group" aria-label="分析直达">${names.map((x, i) => `<button type="button" data-cv-jump="0${i + 1}">${es(x)}</button>`).join('')}</div>
      <section class="hc-cards">
        ${card01(d, team, name)}${card02(d, name)}${card03(d, name)}${card04(d, name)}${card05(d, name)}${card06(d, name)}
      </section>
      <p class="hc-source">数据来源：王者营地终局名单；营地不含禁选先后顺序，本页不做手序推断。</p>
    </div>`;
  }

  /* ── 交互 ─────────────────────────────────────────────────── */
  function rerender() {
    const el = document.querySelector('.cv-page');
    if (el) el.outerHTML = render(null, null);
  }
  function switchView(id, key) {
    state.views[id] = key;
    const wrap = [...document.querySelectorAll('[data-cv-viz]')].find((el) => el.dataset.cvViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-cv-view-btn]').forEach((b) => b.classList.toggle('is-on', b.dataset.cvViewBtn === key));
    wrap.querySelectorAll('.hc-view').forEach((v) => {
      const on = v.dataset.cvView === key;
      v.hidden = !on;
      v.classList.remove('is-enter');
      if (on) { void v.offsetWidth; v.classList.add('is-enter'); }
    });
  }
  function showTip(target, event) {
    const wrap = target.closest('[data-cv-viz]');
    if (!wrap) return;
    const box = wrap.querySelector('.hcv-tip'), stage = wrap.querySelector('.hcv-stage');
    if (!box || !stage) return;
    box.textContent = target.dataset.cvTip || '';
    box.hidden = false;
    const r = stage.getBoundingClientRect();
    box.style.left = `${clamp(event.clientX - r.left + 12, 8, Math.max(8, r.width - 250))}px`;
    box.style.top = `${clamp(event.clientY - r.top - 38, 6, Math.max(6, r.height - 40))}px`;
  }
  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.cv-page')) return;
    const jump = t.closest('[data-cv-jump]');
    if (jump) { const el = document.getElementById(`cv-analysis-${jump.dataset.cvJump}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const vb = t.closest('[data-cv-view-btn]');
    if (vb) { switchView(vb.dataset.cvViz, vb.dataset.cvViewBtn); return; }
    const pick = t.closest('[data-cv-pick]');
    if (pick && pick.dataset.cvPick) { state.teamId = pick.dataset.cvPick; rerender(); }
  });
  document.addEventListener('change', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.cv-page')) return;
    if (t.hasAttribute('data-cv-coach')) { state.teamId = t.value; rerender(); }
  });
  document.addEventListener('mousemove', (event) => {
    const t = event.target.closest ? event.target.closest('[data-cv-tip]') : null;
    if (t && t.closest('.cv-page')) showTip(t, event);
    else document.querySelectorAll('.cv-page .hcv-tip').forEach((x) => { x.hidden = true; });
  });

  function render(value, roster) {
    if (value) state.board = value;
    if (roster) state.roster = roster;
    const board = state.board;
    if (!board) return '<div class="page"><div class="loading">正在汇总教练样本…</div></div>';
    const teams = (board.teams || []).filter((t) => (board.games || []).some((g) => g.teamId === t.id));
    if (!teams.length) return '<div class="page"><div class="empty">当前范围没有可用的教练记录。</div></div>';
    if (!state.teamId || !teams.some((t) => t.id === state.teamId)) state.teamId = teams[0].id;
    const team = teams.find((t) => t.id === state.teamId) || teams[0];
    const name = (state.roster?.teams || []).find((x) => x.id === team.id)?.coach || team.coach || team.name;
    const d = prepare({ ...board, teams });
    return page(d, team, name);
  }

  return { render };
}
