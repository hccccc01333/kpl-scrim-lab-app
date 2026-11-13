/* 选手与位置 · 可视化重构
   与「通用跨局分析」「英雄对比」同一套设计语言：白底、大读数、一分析一形态、
   每卡两个可切换视图、图形可悬停读数、点选聚焦分路、教练语言、无解释小字。
   数据：/api/v3/players-board 的 lanes（五路本队 / 对手聚合）与 games（逐局十人）。 */

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const es = (v) => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const n0 = (v) => (isNum(v) ? Math.round(v).toLocaleString('zh-CN') : '—');
const n1 = (v) => (isNum(v) ? v.toFixed(1) : '—');
const pc = (v) => (isNum(v) ? Math.round(v) + '%' : '—');
const sg = (v) => { const r = Math.round(isNum(v) ? v : 0) || 0; return (r < 0 ? '−' : '+') + Math.abs(r).toLocaleString('zh-CN'); };
const sg1 = (v) => (v < 0 ? '−' : '+') + Math.abs(isNum(v) ? v : 0).toFixed(1);
/* 战队说「金币」，不说「金」 */
const yuan = (t) => String(t == null ? '' : t).replace(/金(?!币)/g, '金币');
const tip = (t) => `data-lv-tip="${es(yuan(t))}"`;
const laneAttr = (l) => `data-lane="${es(l)}"`;
const wOf = (v, max) => `${clamp((Math.abs(isNum(v) ? v : 0) / Math.max(1, max)) * 100, 0, 100).toFixed(1)}%`;
const quant = (arr, p) => {
  const s = arr.filter(isNum).slice().sort((a, b) => a - b);
  if (!s.length) return 0;
  const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
};

const LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走'];
const laneRank = (name) => { const i = LANE_ORDER.indexOf(name); return i < 0 ? 99 : i; };

const VIEWS = {
  '01': ['五路分均', '差多少'],
  '02': ['五路胜率', '赢在哪几路'],
  '03': ['中位与区间', '各路的形状'],
  '04': ['每路几人', '人均几局'],
  '05': ['谁打哪几路', '补位量'],
  '06': ['每路第一', '全名单'],
  '07': ['五路参团', '对比对手'],
};

export function createLaneBoard({ esc = es } = {}) {
  const state = { board: null, views: {}, lane: '', tab: 'lanes', scope: 'roster' };
  const viewOf = (id) => state.views[id] || 'a';

  /* ── 通用零件 ─────────────────────────────────────────────── */
  function shell(id, a, b) {
    const meta = VIEWS[id] || ['看图', '换个角度'];
    const cur = viewOf(id);
    const one = (k, html) => `<div class="hc-view${cur === k ? ' is-enter' : ''}" data-lv-view="${k}"${cur === k ? '' : ' hidden'}>${html}</div>`;
    return `<div class="hcv" data-lv-viz="${id}">
      <div class="hcv-bar"><div class="hcv-switch" role="group" aria-label="切换视图">
        <button type="button" data-lv-view-btn="a" data-lv-viz="${id}" class="${cur === 'a' ? 'is-on' : ''}">${es(meta[0])}</button>
        <button type="button" data-lv-view-btn="b" data-lv-viz="${id}" class="${cur === 'b' ? 'is-on' : ''}">${es(meta[1])}</button>
      </div></div>
      <div class="hcv-stage">${one('a', a)}${one('b', b)}<div class="hcv-tip" hidden></div></div>
    </div>`;
  }
  const view = (hero, body) => `<div class="hcv-view"><div class="hcv-hero">${hero}</div><div class="hcv-body">${body}</div></div>`;
  const big = (v, label, cls = '') => `<div class="hcv-figure ${cls}"><b>${esc(yuan(v))}</b><span>${esc(yuan(label))}</span></div>`;

  function card(id, name, title, chart, action, method, href) {
    return `<article class="hc-card" id="lv-analysis-${id}">
      <div class="hc-card-top"><span class="hc-kicker">${id} / 选手与位置</span></div>
      <div class="hc-card-name">${es(name)}</div>
      <h3 class="hc-card-title">${yuan(title)}</h3>
      <div class="hc-card-canvas">${chart}</div>
      <div class="hc-card-foot"><div class="hc-train"><span>怎么用</span><p>${es(yuan(action))}</p></div>
        <a class="hc-open" href="${esc(href)}">${esc(name.replace('分析', ''))}明细 →</a></div>
      <p class="hc-method"><b>怎么算的</b> ${es(yuan(method))}</p>
    </article>`;
  }
  const pctBar = (v, cls, extra = '') => `<i class="pb-bar ${extra}"><b class="${cls}" style="width:${clamp(isNum(v) ? v : 0, 0, 100).toFixed(1)}%"></b></i>`;

  /* ── 数据准备 ─────────────────────────────────────────────── */
  function prepare(board, scopeMode = 'roster') {
    const games = (board.games || []).filter(Boolean);
    const lanes = (board.lanes || []).filter((x) => x && x.lane).slice()
      .sort((a, b) => laneRank(a.lane) - laneRank(b.lane));
    /* 本队名单＝已认领的名单选手；全部出场＝我方阵营出现过的所有昵称（含未认领）。
       一个都没认领时，本队名单没有意义，直接按全部出场算，并把这个状态说清楚。 */
    const ownAll = (board.players || []).filter((p) => p && p.side === 'own');
    const rostered = ownAll.filter((p) => p.bound || p.memberId);
    const mode = scopeMode === 'roster' && !rostered.length ? 'all' : scopeMode;
    const ownPlayers = mode === 'all' ? ownAll : rostered;
    const ownNames = new Set(ownPlayers.map((p) => p.name));

    const gap = (l) => (isNum(l.own?.gpm) && isNum(l.enemy?.gpm) ? l.own.gpm - l.enemy.gpm : null);
    const gaps = lanes.map(gap).filter(isNum);
    const meanGap = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : null;

    const diffs = {};
    for (const l of lanes) diffs[l.lane] = [];
    for (const g of games) {
      const o = new Map(), e = new Map();
      for (const p of g.own || []) if (p && p.lane && !o.has(p.lane)) o.set(p.lane, p);
      for (const p of g.enemy || []) if (p && p.lane && !e.has(p.lane)) e.set(p.lane, p);
      for (const l of lanes) {
        const a = o.get(l.lane), b = e.get(l.lane);
        if (a && b && isNum(a.gold) && isNum(b.gold)) diffs[l.lane].push(a.gold - b.gold);
      }
    }
    const stats = {};
    for (const l of lanes) {
      const list = diffs[l.lane];
      stats[l.lane] = {
        n: list.length,
        med: quant(list, 0.5),
        p10: quant(list, 0.1),
        p90: quant(list, 0.9),
        ahead: list.filter((v) => v > 0).length,
        behind: list.filter((v) => v < 0).length,
      };
    }
    const peak = Math.max(300, Math.ceil(Math.max(1, ...lanes.map((l) => Math.max(Math.abs(stats[l.lane].p10), Math.abs(stats[l.lane].p90)))) / 250) * 250);

    const byWin = lanes.filter((l) => isNum(l.own?.winRate)).slice()
      .sort((a, b) => b.own.winRate - a.own.winRate);
    const byMed = lanes.filter((l) => stats[l.lane].n).slice()
      .sort((a, b) => stats[a.lane].med - stats[b.lane].med);
    const byPer = lanes.map((l) => {
      const people = l.own?.players || 0, gs = l.own?.games || 0;
      return { lane: l.lane, people, games: gs, per: people ? gs / people : 0 };
    }).sort((a, b) => a.per - b.per);

    const lanePool = (lane) => ownPlayers.filter((p) => p.lane === lane);
    const topOfLane = (lane) => {
      const all = lanePool(lane);
      const ready = all.filter((p) => (p.games || 0) >= 2).sort((a, b) => (b.score || 0) - (a.score || 0));
      const rest = all.filter((p) => (p.games || 0) < 2).sort((a, b) => (b.games || 0) - (a.games || 0) || (b.score || 0) - (a.score || 0));
      return [...ready, ...rest][0] || null;
    };
    const leaders = lanes.map((l) => ({ lane: l.lane, p: topOfLane(l.lane) })).filter((x) => x.p);
    const ranked = ownPlayers.slice().sort((a, b) => (b.score || 0) - (a.score || 0) || (b.games || 0) - (a.games || 0));
    const multi = ownPlayers.filter((p) => (p.laneMix || []).length > 1)
      .sort((a, b) => (b.games || 0) - (a.games || 0)).slice(0, 8);

    const part = lanes.filter((l) => isNum(l.own?.participation));
    const partAvg = part.length ? part.reduce((s, l) => s + l.own.participation, 0) / part.length : null;

    return {
      games, lanes, ownPlayers, ownNames, diffs, stats, peak, meanGap,
      best: byWin[0] || null, worstWin: byWin[byWin.length - 1] || null,
      worstMed: byMed[0] || null, thin: byPer[0] || null,
      byPer, leaders, ranked, multi, partAvg,
      scope: {
        games: games.length,
        slots: lanes.reduce((s, l) => s + (l.own?.games || 0), 0),
        players: ownPlayers.length,
        roster: rostered.length,
        all: ownAll.length,
        mode,
        unclaimed: !rostered.length,
      },
    };
  }

  /* ── 01 分路经济分析 ──────────────────────────────────────── */
  function card01(d) {
    const maxGpm = Math.max(1, ...d.lanes.map((l) => Math.max(l.own?.gpm || 0, l.enemy?.gpm || 0)));
    const A = view(
      big(sg(d.meanGap), '五路分均经济差 · 本队 − 对手', d.meanGap >= 0 ? 'gold' : 'neg'),
      `<div class="pb-duals">${d.lanes.map((l) => {
        const o = l.own?.gpm || 0, e = l.enemy?.gpm || 0, g = o - e;
        return `<div class="pb-dual" ${laneAttr(l.lane)} ${tip(`${l.lane} · 本队分均 ${n0(o)} 金 · 对手 ${n0(e)} 金 · 差 ${sg(g)} 金`)}>
          <span class="pb-dual-name">${es(l.lane)}</span>
          <span class="pb-dual-bars">
            <i class="pb-bar"><b class="gold" style="width:${wOf(o, maxGpm)}"></b></i>
            <i class="pb-bar"><b class="teal" style="width:${wOf(e, maxGpm)}"></b></i>
          </span>
          <span class="pb-dual-vals"><b>${n0(o)}</b><em>${n0(e)}</em></span>
          <strong class="pb-dual-gap ${g < 0 ? 'neg' : 'pos'}">${sg(g)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const maxAbs = Math.max(1, ...d.lanes.map((l) => Math.abs((l.own?.gpm || 0) - (l.enemy?.gpm || 0))));
    const B = view(
      big(`${d.lanes.filter((l) => (l.own?.gpm || 0) > (l.enemy?.gpm || 0)).length}`, '条路经济领先对手', 'teal'),
      `<div class="cxv-bipolars">${d.lanes.map((l) => {
        const g = (l.own?.gpm || 0) - (l.enemy?.gpm || 0);
        const width = clamp(Math.abs(g) / maxAbs * 50, 1.2, 50);
        return `<div class="cxv-bipolar" ${laneAttr(l.lane)} ${tip(`${l.lane} · ${sg(g)} 金/分`)}>
          <span>${es(l.lane)}</span>
          <i class="cxv-bi-track"><em></em><b class="${g < 0 ? 'neg' : ''}" style="${g < 0 ? 'right:50%' : 'left:50%'};width:${width.toFixed(1)}%"></b></i>
          <strong class="${g < 0 ? 'neg' : ''}">${sg(g)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const aheadLanes = d.lanes.filter((l) => (l.own?.gpm || 0) > (l.enemy?.gpm || 0)).length;
    const title = d.meanGap >= 0
      ? `五条路的钱加起来，每分钟比对手多 <em>${sg(d.meanGap)}</em> 金币，${aheadLanes} 条路压过对手`
      : `五条路的钱加起来，每分钟比对手少 <em>${sg(Math.abs(d.meanGap))}</em> 金币，只有 ${aheadLanes} 条路顶得住`;
    return card('01', '分路经济分析', title, shell('01', A, B),
      '先看落后那条路的经济来源，再决定是换线、让资源还是改开局。',
      '分均值＝该路全部出场局的金币总量 ÷ 出场分钟；对手同口径，五路合计取有对位样本的均值。',
      '#playerarchive?min=2');
  }

  /* ── 02 分路胜率分析 ──────────────────────────────────────── */
  function card02(d) {
    const best = d.best;
    const A = view(
      big(best ? pc(best.own.winRate) : '—', best ? `${best.lane} · 五路最高胜率` : '胜率', 'gold'),
      `<div class="hcv-bullets">${d.lanes.map((l) => {
        const wr = l.own?.winRate;
        return `<div class="hcv-bullet" ${laneAttr(l.lane)} ${tip(`${l.lane} · 胜率 ${pc(wr)} · ${n0(l.own?.games)} 人次`)}>
          <span class="hcv-bullet-name">${es(l.lane)}<small>${n0(l.own?.games)} 人次</small></span>
          <i class="hcv-bullet-track"><b style="width:${clamp(isNum(wr) ? wr : 0, 0, 100).toFixed(1)}%"></b><em style="left:50%"></em></i>
          <strong>${pc(wr)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const total = d.lanes.reduce((s, l) => s + (l.own?.games || 0), 0);
    const totalWins = d.lanes.reduce((s, l) => s + Math.round((l.own?.games || 0) * (l.own?.winRate || 0) / 100), 0);
    const B = view(
      big(`${n0(totalWins)}`, `人次里赢下 · 共 ${n0(total)} 人次`, 'teal'),
      `<div class="pb-splits">${d.lanes.map((l) => {
        const g = l.own?.games || 0, wr = l.own?.winRate || 0;
        const wins = Math.round(g * wr / 100), losses = Math.max(0, g - wins);
        return `<div class="pb-split" ${laneAttr(l.lane)} ${tip(`${l.lane} · ${n0(wins)} 胜 ${n0(losses)} 负 · 胜率 ${pc(wr)}`)}>
          <span>${es(l.lane)}</span>
          <i class="pb-split-bar"><b class="gold" style="width:${clamp(wr, 0, 100).toFixed(1)}%"></b><b class="clay" style="width:${clamp(100 - wr, 0, 100).toFixed(1)}%"></b></i>
          <em>${n0(wins)} 胜 · ${n0(losses)} 负</em>
        </div>`;
      }).join('')}</div>`
    );
    const title = best
      ? `<em>${es(best.lane)}</em> 五路最稳：<em>${pc(best.own.winRate)}</em> 胜率、${n0(best.own.games)} 人次；${es(d.worstWin?.lane || '—')} 掉到 ${pc(d.worstWin?.own?.winRate)}`
      : '本期还没有分路胜负样本';
    return card('02', '分路胜率分析', title, shell('02', A, B),
      '胜率低的那条路优先排对位训练，胜率高的一条别拆散。',
      '胜率＝该路有胜负的人次里赢下的比例；中线为本期全队胜率，条越过中线即为正贡献。',
      '#playerarchive?min=2');
  }

  /* ── 03 同路对位分析 ──────────────────────────────────────── */
  function card03(d) {
    const pk = d.peak;
    const worst = d.worstMed;
    const worstMed = worst ? d.stats[worst.lane].med : null;
    const A = view(
      big(worst ? sg(Math.round(worstMed)) : '—', worst ? `${worst.lane} · 同路终局经济差 · 金币` : '经济差', worstMed < 0 ? 'neg' : 'gold'),
      `<div class="pb-bands">${d.lanes.map((l) => {
        const s = d.stats[l.lane];
        const toX = (v) => clamp((v + pk) / (2 * pk) * 100, 0, 100);
        const left = toX(s.p10), right = toX(s.p90), mid = toX(s.med);
        return `<div class="pb-band-row" ${laneAttr(l.lane)} ${tip(`${l.lane} · ${s.n} 局 · 中位 ${sg(Math.round(s.med))} 金 · 大致 ${sg(Math.round(s.p10))} ~ ${sg(Math.round(s.p90))}`)}>
          <span class="pb-band-name">${es(l.lane)}</span>
          <span class="pb-band-track">
            <span class="pb-band-zero"></span>
            <span class="pb-band-area" style="left:${left.toFixed(1)}%;width:${Math.max(1, right - left).toFixed(1)}%"></span>
            <span class="pb-band-med ${s.med < 0 ? 'neg' : ''}" style="left:${mid.toFixed(1)}%"></span>
          </span>
          <strong class="${s.med < 0 ? 'neg' : ''}">${sg(Math.round(s.med))}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const bins = 8;
    const counts = {};
    let maxCount = 1;
    for (const l of d.lanes) {
      const row = new Array(bins).fill(0);
      for (const v of d.diffs[l.lane]) {
        const k = clamp(Math.floor((v + pk) / (2 * pk) * bins), 0, bins - 1);
        row[k] += 1;
      }
      counts[l.lane] = row;
      maxCount = Math.max(maxCount, ...row);
    }
    const B = view(
      big(`${d.lanes.reduce((s, l) => s + d.stats[l.lane].ahead, 0)}`, `局同路对位里经济领先 · 全部 ${n0(d.lanes.reduce((s, l) => s + d.stats[l.lane].n, 0))} 组`, 'teal'),
      `<div class="pb-hists">${d.lanes.map((l) => {
        const row = counts[l.lane];
        return `<div class="pb-hist-row" ${laneAttr(l.lane)} ${tip(`${l.lane} · 落后 ${d.stats[l.lane].behind} 局 / 领先 ${d.stats[l.lane].ahead} 局 · 刻度 ±${n0(pk)} 金`)}>
          <span class="pb-hist-name">${es(l.lane)}</span>
          <span class="pb-hist-bars">${row.map((c, i) => `<i class="${i < bins / 2 ? 'neg' : 'pos'}" style="height:${(c / maxCount * 100).toFixed(1)}%"></i>`).join('')}</span>
          <strong class="${d.stats[l.lane].med < 0 ? 'neg' : ''}">${sg(Math.round(d.stats[l.lane].med))}</strong>
        </div>`;
      }).join('')}</div>
      <div class="pb-hist-axis"><span>${sg(-pk)}</span><span>0</span><span>${sg(pk)}</span></div>`
    );
    const title = worst
      ? `<em>${es(worst.lane)}</em> ${worstMed < 0 ? '同路最吃亏' : '同路领先最少'}：终局经济差典型 <em>${sg(Math.round(worstMed))}</em> 金币，${n0(d.stats[worst.lane].n)} 局里领先 ${n0(d.stats[worst.lane].ahead)} 局`
      : '本期还没有同路对位样本';
    return card('03', '同路对位分析', title, shell('03', A, B),
      '把这条路单独拎出来看录像，先解决对线期的资源丢失。',
      '逐局把本队与对手同分路的两人配对，取终局金币差；上下缘按该路全部配对局计算。',
      '#playerarchive?min=2');
  }

  /* ── 04 位置深度分析 ──────────────────────────────────────── */
  function card04(d) {
    const maxPeople = Math.max(1, ...d.lanes.map((l) => l.own?.players || 0));
    const A = view(
      big(`${d.ownPlayers.length}`, '名本队选手分布在五条路', 'gold'),
      `<div class="hcv-rows">${d.lanes.map((l) => {
        const people = l.own?.players || 0, gs = l.own?.games || 0;
        return `<div class="hcv-row" ${laneAttr(l.lane)} ${tip(`${l.lane} · ${n0(people)} 人 · ${n0(gs)} 人次`)}>
          <span class="hcv-row-label">${es(l.lane)}<small>${n0(gs)} 人次</small></span>
          <i class="hcv-track"><b style="width:${wOf(people, maxPeople)}"></b></i>
          <em class="hcv-row-val">${n0(people)} 人</em>
        </div>`;
      }).join('')}</div>`
    );
    const thin = d.thin;
    const B = view(
      big(thin ? n1(thin.per) : '—', thin ? `${thin.lane} · 人均出场局数` : '人均局数', 'teal'),
      `<div class="hcv-bullets">${d.byPer.map((x) => {
        const tone = x.per >= 2 ? 'gold' : x.per >= 1.5 ? 'teal' : 'clay';
        return `<div class="hcv-bullet" ${laneAttr(x.lane)} ${tip(`${x.lane} · ${n0(x.people)} 人打了 ${n0(x.games)} 人次 · 人均 ${n1(x.per)} 局`)}>
          <span class="hcv-bullet-name">${es(x.lane)}</span>
          <i class="hcv-bullet-track"><b class="${tone}" style="width:${wOf(x.per, Math.max(3, ...d.byPer.map((y) => y.per)))}"></b><em style="left:66.7%"></em></i>
          <strong>${n1(x.per)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const title = thin
      ? `<em>${es(thin.lane)}</em> 最薄：${n0(thin.people)} 人分摊 ${n0(thin.games)} 人次，人均 <em>${n1(thin.per)}</em> 局`
      : '本期还没有分路人次样本';
    return card('04', '位置深度分析', title, shell('04', A, B),
      '人均低于 1.5 局的路先固定一人，再谈战术；否则每次都在重新磨合。',
      '人数＝该路出场过的不同昵称；人均＝该路人次 ÷ 人数，标记线为稳定轮换参考值 2 局。',
      '#playerarchive?min=1');
  }

  /* ── 05 轮换分析 ──────────────────────────────────────────── */
  function card05(d) {
    const rows = d.multi;
    const lanes = d.lanes.map((l) => l.lane);
    const cellMax = Math.max(1, ...rows.flatMap((p) => (p.laneMix || []).map((x) => x.games)));
    const A = view(
      big(`${rows.length}`, '名选手打过两个以上位置', 'gold'),
      `<div class="cxv-mtx" style="grid-template-columns:132px repeat(${lanes.length},minmax(0,1fr))">
        <span></span>${lanes.map((l) => `<span class="cxv-mtx-col">${es(l)}</span>`).join('')}
        ${rows.map((p) => `<span class="cxv-mtx-row">${esc(p.name)}</span>${lanes.map((lane) => {
        const hit = (p.laneMix || []).find((x) => x.lane === lane);
        const n = hit ? hit.games : 0;
        return `<span class="cxv-mtx-cell ${n ? '' : 'thin'}" style="--w:${(n / cellMax * .55 + .06).toFixed(2)}" ${tip(`${p.name} · ${lane} ${n || 0} 局`)}>
          <b>${n || '—'}</b><small>${n ? Math.round(n / Math.max(1, p.games) * 100) + '%' : '·'}</small></span>`;
      }).join('')}`).join('')}
      </div>`
    );
    const maxGames = Math.max(1, ...rows.map((p) => p.games || 0));
    const B = view(
      big(`${rows.reduce((s, p) => s + Math.max(0, (p.laneMix || []).length - 1), 0)}`, '个跨位置出场记录', 'teal'),
      `<div class="hcv-rows">${rows.map((p) => {
        const main = (p.laneMix || []).slice().sort((a, b) => b.games - a.games)[0];
        return `<div class="hcv-row" ${tip(`${p.name} · 共 ${n0(p.games)} 局 · 主位置 ${main ? main.lane : '—'}`)}>
          <span class="hcv-row-label">${esc(p.name)}<small>${(p.laneMix || []).map((x) => x.lane).join(' / ')}</small></span>
          <i class="hcv-track"><b style="width:${wOf(p.games, maxGames)}"></b></i>
          <em class="hcv-row-val">${n0(p.games)} 局</em>
        </div>`;
      }).join('')}</div>`
    );
    const top = rows[0];
    const title = top
      ? `<em>${esc(top.name)}</em> 打了 ${(top.laneMix || []).length} 个位置、共 <em>${n0(top.games)}</em> 局，是轮换的主要来源`
      : '本期没有跨位置出场的选手';
    return card('05', '轮换分析', title, shell('05', A, B),
      '跨位置的选手先定主位，再用第二个位置做临场补位，不要两头都当主力。',
      '按出场局数取前 8 名跨位置选手；格内局数为该位置的出场次数，百分比为占该选手全部出场的比例。',
      '#playerarchive?min=2');
  }

  /* ── 06 位置内选手分析 ────────────────────────────────────── */
  function card06(d) {
    const leaders = d.leaders;
    const settled = leaders.filter((x) => (x.p.games || 0) >= 2);
    const best = (settled.length ? settled : leaders).slice().sort((a, b) => (b.p.score || 0) - (a.p.score || 0))[0];
    const A = view(
      big(best ? n1(best.p.score) : '—', best ? `${best.lane} · ${best.p.name} · 评分` : '评分', 'gold'),
      `<div class="pb-tiles">${leaders.map((x) => `<a class="pb-tile" href="#playerdetail/${encodeURIComponent(x.p.name)}" ${laneAttr(x.lane)} ${tip(`${x.lane} · ${x.p.name} · ${n0(x.p.games)} 局 · 胜率 ${pc(x.p.winRate)} · 评分 ${n1(x.p.score)}`)}>
        <span class="pb-tile-lane">${es(x.lane)}</span>
        <b class="pb-tile-name">${esc(x.p.name)}</b>
        <strong class="pb-tile-score">${n1(x.p.score)}</strong>
        <span class="pb-tile-meta">${n0(x.p.games)} 局 · ${pc(x.p.winRate)}</span>
      </a>`).join('')}</div>`
    );
    const top = d.ranked.slice(0, 10);
    const maxScore = Math.max(1, ...top.map((p) => p.score || 0));
    const B = view(
      big(`${d.ranked.length}`, '名本队选手参与评分', 'teal'),
      `<div class="hcv-rows">${top.map((p) => `<a class="hcv-row" href="#playerdetail/${encodeURIComponent(p.name)}" ${tip(`${p.name} · ${p.lane || '位置未知'} · ${n0(p.games)} 局 · 胜率 ${pc(p.winRate)} · 评分 ${n1(p.score)}`)}>
        <span class="hcv-row-label">${esc(p.name)}<small>${esc(p.lane || '位置未知')} · ${n0(p.games)} 局</small></span>
        <i class="hcv-track"><b style="width:${wOf(p.score, maxScore)}"></b></i>
        <em class="hcv-row-val">${n1(p.score)}</em>
      </a>`).join('')}</div>`
    );
    const mostPlayed = leaders.slice().sort((a, b) => (b.p.games || 0) - (a.p.games || 0))[0];
    const title = best
      ? `五路第一里 <em>${esc(best.p.name)}</em> ${n0(best.p.games)} 局评分 <em>${n1(best.p.score)}</em>；出场最多的是 <em>${esc(mostPlayed?.p.name || '—')}</em> ${n0(mostPlayed?.p.games)} 局`
      : '本期还没有位置内选手样本';
    return card('06', '位置内选手分析', title, shell('06', A, B),
      '每路先认一个第一人，第二人按补位能力选，不要按单局爆发选。',
      '每路先取 2 局以上的选手按评分排序，样本不足的按出场递增补齐；评分由同位置分位合成。',
      '#playerarchive?min=2');
  }

  /* ── 07 团战参与分析 ──────────────────────────────────────── */
  function card07(d) {
    const list = d.lanes.filter((l) => isNum(l.own?.participation));
    const top = list.slice().sort((a, b) => (b.own.participation || 0) - (a.own.participation || 0))[0];
    const A = view(
      big(top ? pc(top.own.participation) : '—', top ? `${top.lane} · 五路参团最高` : '参团率', 'gold'),
      `<div class="hcv-bullets">${list.map((l) => `<div class="hcv-bullet" ${laneAttr(l.lane)} ${tip(`${l.lane} · 本队 ${pc(l.own.participation)} · 对手 ${pc(l.enemy?.participation)}`)}>
        <span class="hcv-bullet-name">${es(l.lane)}<small>对手 ${pc(l.enemy?.participation)}</small></span>
        <i class="hcv-bullet-track"><b style="width:${clamp(l.own.participation, 0, 100).toFixed(1)}%"></b><em style="left:${clamp(d.partAvg || 0, 0, 100).toFixed(1)}%"></em></i>
        <strong>${pc(l.own.participation)}</strong>
      </div>`).join('')}</div>`
    );
    const maxAbs = Math.max(1, ...list.map((l) => Math.abs((l.own.participation || 0) - (l.enemy?.participation || 0))));
    const B = view(
      big(`${list.filter((l) => (l.own.participation || 0) > (l.enemy?.participation || 0)).length}`, '条路的团战参与高于对手', 'teal'),
      `<div class="cxv-bipolars">${list.map((l) => {
        const g = (l.own.participation || 0) - (l.enemy?.participation || 0);
        return `<div class="cxv-bipolar" ${laneAttr(l.lane)} ${tip(`${l.lane} · 本队 ${pc(l.own.participation)} · 对手 ${pc(l.enemy?.participation)} · 差 ${sg1(g)} 个百分点`)}>
          <span>${es(l.lane)}</span>
          <i class="cxv-bi-track"><em></em><b class="${g < 0 ? 'neg' : ''}" style="${g < 0 ? 'right:50%' : 'left:50%'};width:${clamp(Math.abs(g) / maxAbs * 50, 1.2, 50).toFixed(1)}%"></b></i>
          <strong class="${g < 0 ? 'neg' : ''}">${sg1(g)}</strong>
        </div>`;
      }).join('')}</div>`
    );
    const title = top
      ? `<em>${es(top.lane)}</em> 团战参与最高 <em>${pc(top.own.participation)}</em>，全队均值 ${pc(d.partAvg)}`
      : '本期还没有参团样本';
    return card('07', '团战参与分析', title, shell('07', A, B),
      '参团低但胜率高的路可以少打团；参团高却不赢的路，先查是不是白跑。',
      '参团率＝该路参与击杀的回合占本队总击杀的比例，取该路全部出场局的均值。',
      '#playerarchive?min=2');
  }

  /* ── 组装页面 ─────────────────────────────────────────────── */
  const TABS = [
    { key: 'lanes', label: '五路强弱', note: '谁在赢、钱在哪' },
    { key: 'roster', label: '轮换与人', note: '深度、补位、用人' },
  ];

  function page(d) {
    const s = d.scope;
    const best = d.best;
    const worstMed = d.worstMed;
    const claim = best
      ? `<em>${es(best.lane)}</em> 五路最能拉开差距：分均多 <em>${sg((best.own?.gpm || 0) - (best.enemy?.gpm || 0))}</em> 金币、胜率 <em>${pc(best.own.winRate)}</em>`
      : '先补齐分路样本，再看五路强弱';
    const wm = worstMed ? d.stats[worstMed.lane].med : null;
    const fact = worstMed
      ? `${es(worstMed.lane)} ${wm < 0 ? '最吃亏' : '领先最少'}——同路终局经济差典型 <em>${sg(Math.round(wm))}</em> 金币，${n0(d.stats[worstMed.lane].n)} 局里 <em>${n0(d.stats[worstMed.lane].ahead)}</em> 局领先；${es(d.thin?.lane || '—')} 人均 <em>${n1(d.thin?.per)}</em> 局，五路最薄。`
      : '';
    const laneStrip = d.lanes.map((l) => {
      const g = (l.own?.gpm || 0) - (l.enemy?.gpm || 0);
      return `<div class="pb-lane" ${laneAttr(l.lane)} ${tip(`${l.lane} · 胜率 ${pc(l.own?.winRate)} · 分均 ${n0(l.own?.gpm)} 金币 · 差 ${sg(g)}`)}>
        <span class="pb-lane-name">${es(l.lane)}</span>
        <b class="pb-lane-wr">${pc(l.own?.winRate)}</b>
        <span class="pb-lane-gap ${g < 0 ? 'neg' : 'pos'}">${sg(g)}</span>
        <i class="pb-lane-bar"><b style="width:${clamp(l.own?.winRate || 0, 0, 100).toFixed(1)}%"></b></i>
      </div>`;
    }).join('');
    const scopeLabel = s.mode === 'all' ? '全部出场昵称' : '本队名单';
    const scopeSwitch = `<div class="lv-scope" role="group" aria-label="统计范围">
      <button type="button" data-lv-scope="roster" class="${s.mode === 'roster' ? 'is-on' : ''}" aria-pressed="${s.mode === 'roster'}"${s.unclaimed ? ' disabled title="还没有认领本队选手"' : ''}>本队名单 · ${n0(s.roster)} 人</button>
      <button type="button" data-lv-scope="all" class="${s.mode === 'all' ? 'is-on' : ''}" aria-pressed="${s.mode === 'all'}">全部出场 · ${n0(s.all)} 个昵称</button>
    </div>`;
    const tabs = `<div class="md-tabs lv-tabs" role="tablist" aria-label="选手与位置页签">${TABS.map((t) => `<button type="button" class="md-tab" data-lv-tab="${t.key}" role="tab" aria-selected="${state.tab === t.key}"><b>${es(t.label)}</b><small>${es(t.note)}</small></button>`).join('')}</div>`;
    const pane = (key, body) => `<div class="lv-pane" data-lv-pane="${key}"${state.tab === key ? '' : ' hidden'}>
      <p class="lv-lede">${key === 'lanes'
        ? '看五条路各自的分均金币、胜率、同路对位和团战参与：谁在赢、钱在哪、对线谁吃亏。'
        : `看人：每路几个人、谁在补位、每路的第一人。当前按「${scopeLabel}」统计${s.unclaimed ? '；还没有认领本队选手，先按全部出场算，认领后会自动切回本队名单' : ''}。`}</p>
      <section class="hc-cards">${body}</section>
    </div>`;
    return `<div class="page pb-page lv-page">
      <div class="page-intro pb-intro"><div><h1>选手与位置</h1><p>五条路分开看：谁在赢、金币从哪来、对线谁吃亏。</p></div>
        <div class="intro-actions">${scopeSwitch}<button class="control" data-action="refresh">刷新数据</button></div></div>
      <section class="pb-hero">
        <div class="pb-hero-top"><span class="pb-kicker">选手与位置 · 五路对照</span>
          <span class="pb-scope">${n0(s.games)} 局 · ${n0(s.slots)} 人次 · 按${scopeLabel}统计 ${n0(s.players)} 名选手</span></div>
        <h2 class="pb-claim">${claim}</h2>
        <p class="pb-fact">${fact}</p>
        <div class="pb-lanes">${laneStrip}</div>
      </section>
      ${tabs}
      ${pane('lanes', card01(d) + card02(d) + card03(d) + card07(d))}
      ${pane('roster', card04(d) + card05(d) + card06(d))}
      <p class="hc-source">数据来源：王者营地十人结算逐局面板；同路对位按分路配对，未配对的面板不计入。「本队名单」只统计已认领的选手，「全部出场」把未认领的昵称也算进来。</p>
    </div>`;
  }

  /* ── 交互 ─────────────────────────────────────────────────── */
  function switchView(id, key) {
    state.views[id] = key;
    const wrap = [...document.querySelectorAll('[data-lv-viz]')].find((el) => el.dataset.lvViz === id);
    if (!wrap) return;
    wrap.querySelectorAll('[data-lv-view-btn]').forEach((b) => b.classList.toggle('is-on', b.dataset.lvViewBtn === key));
    wrap.querySelectorAll('.hc-view').forEach((v) => {
      const on = v.dataset.lvView === key;
      v.hidden = !on;
      v.classList.remove('is-enter');
      if (on) { void v.offsetWidth; v.classList.add('is-enter'); }
    });
  }
  function showTip(target, event) {
    const wrap = target.closest('[data-lv-viz]');
    if (!wrap) return;
    const box = wrap.querySelector('.hcv-tip'), stage = wrap.querySelector('.hcv-stage');
    if (!box || !stage) return;
    box.textContent = target.dataset.lvTip || '';
    box.hidden = false;
    const r = stage.getBoundingClientRect();
    box.style.left = `${clamp(event.clientX - r.left + 12, 8, Math.max(8, r.width - 250))}px`;
    box.style.top = `${clamp(event.clientY - r.top - 38, 6, Math.max(6, r.height - 40))}px`;
  }
  function focusLane(lane) {
    state.lane = state.lane === lane ? '' : lane;
    document.querySelectorAll('.lv-page [data-lane]').forEach((el) => {
      el.classList.toggle('is-lane-on', !!state.lane && el.dataset.lane === state.lane);
      el.classList.toggle('is-lane-off', !!state.lane && el.dataset.lane !== state.lane);
    });
  }
  function redraw() {
    if (!state.board) return;
    const host = document.querySelector('.lv-page');
    if (host) host.outerHTML = page(prepare(state.board, state.scope));
  }

  document.addEventListener('click', (event) => {
    const t = event.target;
    if (!t.closest || !t.closest('.lv-page')) return;
    const tabBtn = t.closest('[data-lv-tab]');
    if (tabBtn) {
      state.tab = tabBtn.dataset.lvTab;
      document.querySelectorAll('.lv-page [data-lv-tab]').forEach((n) => n.setAttribute('aria-selected', String(n.dataset.lvTab === state.tab)));
      document.querySelectorAll('.lv-page [data-lv-pane]').forEach((p) => { p.hidden = p.dataset.lvPane !== state.tab; });
      return;
    }
    const scopeBtn = t.closest('[data-lv-scope]');
    if (scopeBtn) {
      if (state.scope === scopeBtn.dataset.lvScope) return;
      state.scope = scopeBtn.dataset.lvScope;
      state.lane = '';
      redraw();
      return;
    }
    const vb = t.closest('[data-lv-view-btn]');
    if (vb) { switchView(vb.dataset.lvViz, vb.dataset.lvViewBtn); return; }
    if (t.closest('a')) return;
    const lane = t.closest('[data-lane]');
    if (lane) focusLane(lane.dataset.lane);
  });
  document.addEventListener('mousemove', (event) => {
    const t = event.target.closest ? event.target.closest('[data-lv-tip]') : null;
    if (t && t.closest('.lv-page')) showTip(t, event);
    else document.querySelectorAll('.lv-page .hcv-tip').forEach((x) => { x.hidden = true; });
  });

  function render(value) {
    if (value) state.board = value;
    const board = state.board;
    if (!board) return '<div class="page"><div class="loading">正在汇总位置样本…</div></div>';
    const d = prepare(board, state.scope);
    if (!d.lanes.length) return '<div class="page"><div class="empty">当前范围没有位置样本。</div></div>';
    return page(d);
  }

  return { render };
}
