import { topicGroups, studyGroups, groupLabel } from './navigation.js';
import { equipIcons } from './equipment-icons.js';
import { createResearch } from './research.js';
import { createDepth } from './depth.js';
import { createCapture } from './capture-page.js';
import { createSources } from './sources-page.js';
import { createReview } from './review-page.js';
import { createPlayers } from './players-page.js';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
export const featureSections = {
  ingest: [['ingest','营地同步']],
  matches: [['matches','对局档案'], ['query','智能找局'], ['featured','精选对局'], ['records','训练纪录'], ['versions','版本对比']],
  teams: [['teams','战队档案']],
  players: [['players','名单与状态'], ['identity','选手认领'], ['compare','选手与位置'], ['playercompare','选手对比']],
  heroes: [['heroes','英雄榜'], ['herocompare','英雄对比'], ['combos','英雄组合']],
  bp: [['bp','BP 概览'], ['teambp','战队 BP'], ['coach','教练档案']],
  setup: [['setup','建档'], ['ownership','对手归属'], ['pending','待确认'], ['plan','约定计划'], ['effect','训练效果'], ['reports','分析报告']],
};

export function createFeatures(h) {
  const {esc, fmt, pct, diff, time, portrait, route, table, pageIntro, reload, currentQuery, icon, microChart, gameAnchorBar} = h;
  const depth = createDepth({esc,fmt,pct,table,icon});
  const research = createResearch({esc,fmt,table,icon,pageIntro});
  const endpoints = {
    teams:['studio/teams'], team:['studio/teams'], h2h:['studio/teams'], teamcompare:['studio/teams'], profiles:['studio/analysis/opponents'],
    capture:['sources'], identity:['v2/players-board'], players:['v2/players-board'], ownership:['studio/opponents'], coach:['v2/bp-board','studio/coach'], compare:['v2/players-board'], playercompare:['v2/players-board'], playerdetail:['v2/players-board'], heroes:['studio/camp-compare'], hero:['studio/camp-compare'], teambp:['v2/bp-board'], bp:['v2/bp-board'], herocompare:['studio/camp-compare'], query:['matches'], featured:['matches','tempo'], records:['matches','tempo'],
    combos:['studio/camp-combos?min=3'], topic:['depth/catalog'], study:['v2/research/catalog'], reports:['v2/research/reports'], report:['v2/research/reports'], economy:['v2/economy'],
    effect:['v2/effect', 'studio/workspace/players'], versions:['matches'],
    setup:['v2/workspace/overview','studio/workspace/teams','studio/workspace/players','studio/workspace/pending','v2/workspace/migration','studio/teams'],
    pending:['studio/workspace/pending','studio/workspace/teams','v2/vocab'], plan:['studio/workspace/schedules','studio/workspace/teams','v2/vocab'],
  };
  const scope = '<div class="scope-note"><span>数据口径</span> 本页使用全部营地面板及关联回放，可能包含非训练赛；首页的日期、来源与验证数据筛选不适用于此处。</div>';
  const block = (title, subtitle, body, right='', attrs='') => body ? `<section class="section" ${attrs}><div class="section-heading"><div><h2>${esc(title)}</h2><p>${esc(subtitle || '')}</p></div>${right}</div>${body}</section>` : '';
  const stats = (items) => `<div class="stats-band">${items.map(([label,value,detail]) => `<div><span>${esc(label)}</span><strong>${value}</strong><p>${esc(detail || '')}</p></div>`).join('')}</div>`;
  const empty = (s) => `<div class="empty">${esc(s)}</div>`;
  const form = (id, fields, button='保存') => `<form class="feature-form" data-feature-form="${id}">${fields}<div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit">${button}</button></div></form>`;
  const field = (label, name, value='', extra='') => `<label>${esc(label)}<input name="${esc(name)}" value="${esc(value ?? '')}" ${extra}></label>`;
  /* ── 赛训词表：版本 / 规则 / 赛制 / 训练组 ───────────────────────────
     选项来自 /api/v2/vocab（后端同一份词表）；「其他（手填）」会露出输入框，
     保存时后端归一化并登记，下次自动成为选项。训练组是可增长名词，用 combo。 */
  const VOCAB_KINDS = {version: 'versions', rules: 'rules', format: 'formats', session: 'sessions'};
  const vocabList = (vocab, fieldName) => ((vocab && vocab[VOCAB_KINDS[fieldName]]) || []);
  const vocabControl = (name, list, current, {empty = '待定'} = {}) => {
    const values = [...new Set([...(current && !list.includes(current) ? [current] : []), ...list])];
    const blank = empty === null ? '' : `<option value="" ${current ? '' : 'selected'}>${esc(empty)}</option>`;
    return `<select name="${esc(name)}" data-vocab-select="${esc(name)}">${blank}${values.map((v) => `<option value="${esc(v)}" ${v === current ? 'selected' : ''}>${esc(v)}</option>`).join('')}<option value="__custom__">其他（手填）…</option></select><input name="${esc(name)}Custom" data-vocab-custom="${esc(name)}" maxlength="40" autocomplete="off" placeholder="填写新值，保存后纳入词表" hidden>`;
  };
  const vocabSelect = (label, name, list, current, opts) => `<label>${esc(label)}${vocabControl(name, list, current, opts)}</label>`;
  const vocabCombo = (label, name, list, current, listId = 'sx-vocab-session') =>
    `<label>${esc(label)}<input name="${esc(name)}" list="${esc(listId)}" value="${esc(current ?? '')}" maxlength="40" autocomplete="off" placeholder="选已有或直接新建"><span class="sx-vocab-hint">输入新值会自动纳入词表</span></label>`;
  const vocabDatalist = (list, listId = 'sx-vocab-session') => `<datalist id="${esc(listId)}">${(list || []).map((v) => `<option value="${esc(v)}"></option>`).join('')}</datalist>`;
  /* 提交前把「其他（手填）」换成手填值；单条确认与整局批量确认共用。 */
  const applyVocabValue = (scope, payload) => {
    scope.querySelectorAll('[data-vocab-select]').forEach((select) => {
      if (select.value !== '__custom__') return;
      const custom = scope.querySelector(`[data-vocab-custom="${select.dataset.vocabSelect}"]`);
      payload[select.name] = String(custom?.value || '').trim();
    });
    return payload;
  };
  const options = (teams, value='') => `<option value="">请选择</option>${teams.map(t=>`<option value="${esc(t.id)}" ${t.id===value?'selected':''}>${esc(t.name || t.displayName)}</option>`).join('')}`;
  const select = (label, name, html) => `<label>${esc(label)}<select name="${esc(name)}">${html}</select></label>`;
  const multiTable = (head, rows) => table(head, rows);
  const sxIntro = (title, sub, right='', withFilter=true) => `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${right}${withFilter ? `<button class="control" data-action="filter">${icon('filter')} 数据范围</button>` : ''}<button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></div></div>`;
  const withPage = (title, sub, body, isScoped=true, right='', withFilter=true, sx=false) => `<div class="page feature-page${sx ? ' sx-page' : ''}">${isScoped ? `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${right}<button class="control" data-action="refresh">刷新数据</button></div></div>` : sxIntro(title,sub,right,withFilter)}${isScoped ? scope : ''}${body}</div>`;
  const isPlaceholderTeam = (name) => /^待命名/.test(String(name || '').trim());
  const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const statusLabels = {planned:'计划中', confirmed:'已确认', completed:'已完成', cancelled:'已取消'};
  const sourceName = (source) => ({placeholder:'自动生成', manual:'人工录入', migration:'迁移导入', import:'表格导入'}[source] || source || '来源未知');
  const confidenceName = (confidence) => ({high:'高可信', medium:'中可信', low:'低可信'}[confidence] || '');
  const text = x => esc(x ?? '—');
  const capture = (items, limit=12) => items.slice(0,limit);
  /* 采集页：读 V1 根接口，见 capture-page.js */
  const capturePageV1 = createCapture({esc, fmt, table, block, stats, empty, withPage, icon});
  /* 截图 / 录屏 / 回放三个素材页，见 sources-page.js */
  const sourcePages = createSources({esc, fmt, block, stats, empty, withPage, icon, table});
  /* 逐项校对，见 review-page.js */
  const reviewPage = createReview({esc, fmt, block, stats, empty, withPage, icon});
  /* 选手板块四页：名单与状态 / 选手认领 / 选手与位置 / 选手对比 */
  const playerPages = createPlayers({esc,fmt,pct,diff,portrait,block,empty,stats,reload});
  function bars(items, label, numberOf, display, limit=8) {
    const valid=items.map(item=>({item,n:numberOf(item)})).filter(x=>typeof x.n==='number'&&Number.isFinite(x.n)&&x.n>=0).slice(0,limit);
    if(!valid.length)return '';
    const max=Math.max(1,...valid.map(x=>x.n));
    return `<div class="insight-bars">${valid.map(({item,n})=>`<div><span>${text(label(item))}</span><div><i style="width:${n/max*100}%"></i></div><b>${text(display?display(item):fmt(n,1))}</b></div>`).join('')}</div>`;
  }
  /* ── 战队：KPL 赛研式卡片墙（2026-11-07）────────────────────────────
     数据来自营地终局面板（studio/teams）。对手战队由阵容聚类识别，带阵容、
     选手 ID、逐局记录与同位置百分位。本分类只写对手，不混本队聚合口径。
     卡片沿用赛研「战力分 + 分位条 + 数据格」的读法：得分 0–100，五项加权
     对手胜率 30%、分均经济 20%、KDA 20%、分均输出 15%、场均推塔 15%；
     除胜率外都用同池分位（0–100）。样本不足 3 局只作排序参考。 */
  const TM_LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  const TM_NOTE = '营地终局面板 · 与「对局档案」口径不同，两边局数可能不一致。';
  const byLaneTm = (players) => [...(players || [])].sort((a, b) => {
    const ia = TM_LANES.indexOf(a.lane), ib = TM_LANES.indexOf(b.lane);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  const tmCrest = (name) => `<span class="tm-crest">${esc((name || '?').slice(0, 1))}</span>`;
  const tmRecord = (t) => `${fmt(t.wins)} 胜 ${fmt(t.losses)} 负`;
  const tmResult = (g) => g.win === true ? ['win', '胜'] : g.win === false ? ['loss', '负'] : ['muted', '未知'];
  const tmTeamOf = (teams, id) => teams.find((t) => t.id === id)?.displayName || '未归属';
  /* 得分：五项 0–100 加权。除「对手胜率」外都用同池分位，缺失项按剩余权重归一，
     不把没有样本的指标当成 0 拉低得分。 */
  const TM_SCORE_DIMS = [['胜率', 'result', .30], ['经济', 'gpm', .20], ['对抗', 'kda', .20],
    ['输出', 'dpm', .15], ['推进', 'towerPerGame', .15]];
  const hasNum = (n) => typeof n === 'number' && Number.isFinite(n);
  const tmOppRate = (t) => {
    const decided = (t.wins || 0) + (t.losses || 0);
    return decided ? (t.losses || 0) / decided * 100 : null;
  };
  const tmK = (v) => hasNum(v) ? (Math.abs(v) >= 10000 ? fmt(v / 1000, 1) + 'k' : fmt(v)) : '—';
  const tmSignedNum = (v, digits = 0) => hasNum(v) ? (v > 0 ? '+' : '') + fmt(v, digits) : '—';
  const tmScore = (t) => {
    const p = t.percentiles || {};
    const dims = TM_SCORE_DIMS.map(([label, key, weight]) => {
      const raw = key === 'result' ? tmOppRate(t) : p[key];
      return {label, key, weight, value: hasNum(raw) ? Math.max(0, Math.min(100, raw)) : null};
    });
    const live = dims.filter((d) => d.value != null);
    if (!live.length) return null;
    const total = live.reduce((sum, d) => sum + d.weight, 0);
    const score = Math.round(live.reduce((sum, d) => sum + d.weight * d.value, 0) / total);
    return {score, grade: score >= 80 ? 'S' : score >= 60 ? 'A' : score >= 40 ? 'B' : 'C', dims, coverage: live.length};
  };
  const tmScoreBars = (t, info) => {
    const p = t.percentiles || {}, m = t.metrics || {};
    const real = {result: tmOppRate(t), gpm: m.gpm, kda: m.kda, dpm: m.dpm, towerPerGame: m.towerPerGame};
    return TM_SCORE_DIMS.map(([label, key]) => {
      const value = info?.dims.find((d) => d.key === key)?.value;
      const actual = key === 'result' ? pct(real[key])
        : key === 'dpm' ? tmK(real[key])
          : key === 'kda' ? fmt(real[key], 2)
            : key === 'towerPerGame' ? fmt(real[key], 1) : fmt(real[key]);
      const tip = value == null ? `${label}：样本不足`
        : key === 'result' ? `对手胜率 ${actual}` : `${label} ${actual} · 分位 ${Math.round(value)}`;
      return `<div class="tm-score-row${value == null ? ' is-empty' : ''}" title="${esc(tip)}">
        <span>${label}</span><span class="tm-score-track"><b style="width:${value == null ? 0 : Math.round(value)}%"></b></span><em>${value == null ? '—' : Math.round(value)}</em></div>`;
    }).join('');
  };
  const tmRadar = (info) => {
    const dims = (info?.dims || []).filter((d) => d.value != null);
    if (dims.length < 3) return '';
    const n = dims.length, cx = 95, cy = 92, R = 55;
    const pt = (index, ratio) => {
      const angle = (-90 + index * 360 / n) * Math.PI / 180;
      return [cx + Math.cos(angle) * R * ratio, cy + Math.sin(angle) * R * ratio];
    };
    const ring = (ratio) => dims.map((_, index) => pt(index, ratio).map((v) => v.toFixed(1)).join(',')).join(' ');
    const rings = [.25, .5, .75, 1].map((ratio) => `<polygon points="${ring(ratio)}" class="tm-radar-ring"/>`).join('');
    const axes = dims.map((_, index) => {
      const [x, y] = pt(index, 1);
      return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" class="tm-radar-axis"/>`;
    }).join('');
    const labels = dims.map((d, index) => {
      const [x, y] = pt(index, 1.26);
      return `<text x="${x.toFixed(1)}" y="${(y + 2).toFixed(1)}" text-anchor="middle" class="tm-radar-label">${esc(d.label)}</text>`;
    }).join('');
    const shape = dims.map((d, index) => pt(index, d.value / 100).map((v) => v.toFixed(1)).join(',')).join(' ');
    const dots = dims.map((d, index) => {
      const [x, y] = pt(index, d.value / 100);
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" class="tm-radar-dot"/>`;
    }).join('');
    return `<div class="tm-radar"><svg viewBox="0 0 190 184" role="img" aria-label="五项能力雷达">${rings}${axes}${labels}<polygon points="${shape}" class="tm-radar-shape"/>${dots}</svg></div>`;
  };
  const tmCard = (t, info, rank) => {
    const p = t.percentiles || {}, m = t.metrics || {};
    const state = t.coach ? '教练 ' + t.coach : t.named ? '已建档' : '阵容聚类 · 待命名';
    const figures = [
      ['交手', `${fmt(t.matches)} 局`, `本队 ${tmRecord(t)}`],
      ['对手胜率', pct(tmOppRate(t)), `本队 ${pct(t.winRate)}`],
      ['分均经济', fmt(m.gpm), `分位 ${fmt(p.gpm)}`],
      ['KDA', fmt(m.kda, 2), `分位 ${fmt(p.kda)}`],
      ['分均输出', tmK(m.dpm), `分位 ${fmt(p.dpm)}`],
      ['场均推塔', fmt(m.towerPerGame, 1), `分位 ${fmt(p.towerPerGame)}`],
    ].map(([label, value, note]) => `<div><span>${label}</span><b>${value}</b><small>${note}</small></div>`).join('');
    const rosterPlayers = byLaneTm(t.players).slice(0, 5);
    const roster = Array.from({length: 5}, (_, index) => {
      const pl = rosterPlayers[index];
      if (!pl) return `<span class="tm-player is-empty"><i>?</i><b>待补</b></span>`;
      const label = pl.name || '待补';
      return `<span class="tm-player" title="${esc(pl.lane || '位置未知')} · ${esc(label)}"><i>${esc(label.slice(0, 1))}</i><b>${esc(label)}</b></span>`;
    }).join('');
    const grade = info?.grade || '';
    return `<article class="tm-card${info && info.score >= 75 ? ' is-top' : ''}" data-team-row
      data-team-name="${esc([t.displayName, t.name, t.coach, ...(t.players || []).map((x) => x.name)].filter(Boolean).join(' ').toLowerCase())}"
      data-team-named="${t.named ? '1' : '0'}" data-team-games="${t.matches || 0}"
      data-team-rate="${t.winRate ?? ''}" data-team-score="${info?.score ?? ''}" data-team-last="${esc(t.lastSeen || '')}">
      <a class="tm-card-link" href="${route('team', t.id)}" aria-label="查看 ${esc(t.displayName)} 详情">
        <header class="tm-card-head">
          <span class="tm-card-no" title="得分排名">${rank ? `#${rank}` : '—'}</span>
          <span class="tm-crest is-lg">${esc((t.displayName || '?').slice(0, 1))}</span>
          <span class="tm-card-id"><b>${text(t.displayName)}</b><small>${esc(state)} · ${text(t.lastSeen)}</small></span>
          ${grade ? `<span class="tm-tier is-${grade.toLowerCase()}">${grade}</span>` : ''}
        </header>
        <div class="tm-card-score">
          <div class="tm-score-figure"><strong>${info ? info.score : '—'}</strong><small>战队得分</small><em>${info ? `${info.coverage}/5 项` : '样本不足'}</em></div>
          <div class="tm-score-bars">${tmScoreBars(t, info)}</div>
        </div>
        <div class="tm-card-figures">${figures}</div>
        <footer class="tm-card-foot">
          <div class="tm-card-roster" aria-label="选手头像与 ID">${roster}</div>
        </footer>
      </a>
      <button type="button" class="tm-rename" data-team-rename="${esc(t.id)}" data-team-label="${esc(t.displayName)}" title="给这支战队命名">命名</button>
    </article>`;
  };
  /* 列表前端视图控制：搜索（队名/选手 ID）+ 状态胶囊 + 排序 + 计数。 */
  function syncTeamList(root) {
    if (!root) return;
    const q = (root.querySelector('[data-team-search]')?.value || '').trim().toLowerCase();
    const named = root.dataset.teamFilter || '';
    const sort = root.querySelector('[data-team-sort]')?.value || 'score';
    const list = root.querySelector('[data-team-results]');
    if (!list) return;
    const unit = root.dataset.teamUnit || '支';
    const rows = [...list.querySelectorAll('[data-team-row]')];
    let shown = 0;
    for (const row of rows) {
      const ok = (!q || String(row.dataset.teamName || '').includes(q))
        && (!named || row.dataset.teamNamed === named);
      row.hidden = !ok;
      if (ok) shown++;
    }
    const order = {
      score: (a, b) => Number(b.dataset.teamScore || -1) - Number(a.dataset.teamScore || -1),
      recent: (a, b) => String(b.dataset.teamLast || '').localeCompare(String(a.dataset.teamLast || '')),
      games: (a, b) => Number(b.dataset.teamGames || 0) - Number(a.dataset.teamGames || 0),
      rate: (a, b) => Number(b.dataset.teamRate || 0) - Number(a.dataset.teamRate || 0),
      name: (a, b) => String(a.dataset.teamName || '').localeCompare(String(b.dataset.teamName || ''), 'zh'),
    }[sort];
    if (order) [...rows].sort(order).forEach((row) => list.append(row));
    const counter = root.querySelector('[data-team-count]');
    if (counter) counter.textContent = shown === rows.length ? `共 ${fmt(shown)} ${unit}` : `找到 ${fmt(shown)} ${unit} · 共 ${fmt(rows.length)} ${unit}`;
    const hint = root.querySelector('[data-team-empty]');
    if (hint) hint.hidden = shown > 0;
  }
  const mapping = {enemy_team_id:'对手战队',session:'训练组',version:'版本',rules:'规则',pick_order:'选用顺序'};
  function teamsPage(value, key, compare, bp) {
    const teams = value.teams || [];
    if (key) return teamDetail(value, key, compare, bp);
    const named = teams.filter((t) => t.named).length;
    const games = teams.reduce((sum, t) => sum + (t.matches || 0), 0);
    const wins = teams.reduce((sum, t) => sum + (t.wins || 0), 0);
    const losses = teams.reduce((sum, t) => sum + (t.losses || 0), 0);
    const thin = teams.filter((t) => (t.matches || 0) < 3).length;
    const latest = [...teams].sort((a, b) => String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')))[0];
    const lastSeen = latest ? String(latest.lastSeen || '') : '';
    const span = lastSeen.slice(0, 5) === String(teams[0]?.firstSeen || '').slice(0, 5) ? '同一天' : '跨多日';
    const decided = wins + losses;
    const ownRate = decided ? wins / decided * 100 : null;
    const scoreMap = new Map(teams.map((t) => [t.id, tmScore(t)]));
    const ranked = [...teams].filter((t) => scoreMap.get(t.id))
      .sort((a, b) => scoreMap.get(b.id).score - scoreMap.get(a.id).score);
    const rankMap = new Map(ranked.map((t, index) => [t.id, index + 1]));
    const scores = [...scoreMap.values()].filter(Boolean).map((x) => x.score);
    const avgScore = scores.length ? Math.round(scores.reduce((sum, n) => sum + n, 0) / scores.length) : null;
    const maxScore = scores.length ? Math.max(...scores) : null;
    const minScore = scores.length ? Math.min(...scores) : null;
    const cards = [...teams].sort((a, b) => (scoreMap.get(b.id)?.score ?? -1) - (scoreMap.get(a.id)?.score ?? -1));
    const toolbar = `<div class="fj-toolbar">
      <label class="fj-field"><span>搜索</span><input data-team-search placeholder="战队名 / 选手 ID"></label>
      <div class="fj-field"><span>状态</span><div class="fj-chips">
        <button type="button" class="fj-chip" data-team-chip="" aria-pressed="true">全部</button>
        <button type="button" class="fj-chip" data-team-chip="1" aria-pressed="false">已命名</button>
        <button type="button" class="fj-chip" data-team-chip="0" aria-pressed="false">待命名</button>
      </div></div>
      <label class="fj-field"><span>排序</span><select data-team-sort>
        <option value="score">评分最高</option><option value="recent">最近交手</option>
        <option value="games">交手最多</option><option value="rate">本队胜率</option><option value="name">队名</option></select></label>
      <p class="fj-count" data-team-count>共 ${fmt(teams.length)} 支</p></div>`;
    const suggestions = (value.suggestions || []).map((s) => `<li><b>${text(s.fromName || s.from || s.a)}</b> → <b>${text(s.toName || s.into || s.b)}</b><small>重合 ${text(s.overlap || '—')}</small></li>`).join('');
    const thinNote = thin ? `其中 ${fmt(thin)} 支不足 3 局，得分只作参考，不足以判断真实强弱` : '每支样本都达到 3 局，可做队间比较';
    return withPage('战队档案',
      `${fmt(teams.length)} 支对手 · ${fmt(games)} 局交手（${fmt(wins)} 胜 ${fmt(losses)} 负）· ${thinNote}`,
      lede([['识别对手', `${fmt(teams.length)} 支`, `${fmt(named)} 支已命名`],
        ['交手局数', `${fmt(games)} 局`, `${fmt(wins)} 胜 ${fmt(losses)} 负`],
        ['平均得分', avgScore == null ? '—' : `${fmt(avgScore)} 分`, maxScore == null ? '没有可用指标' : `最高 ${fmt(maxScore)} · 最低 ${fmt(minScore)}`],
        ['时间跨度', span, lastSeen ? '至 ' + lastSeen : '—'],
        ['本队胜率', pct(ownRate), ownRate == null ? '对手侧 —' : `对手侧 ${pct(100 - ownRate)}`]])
      + block('对手战力榜', '左上为得分排名。得分 0-100：对手胜率 30%，分均经济 / KDA / 分均输出 / 场均推塔合计 70%（同池分位）。样本不足 3 局只作参考，点卡片进详情，右上「命名」改名。',
        `${toolbar}<div class="tm-grid" data-team-results>${cards.map((t) => tmCard(t, scoreMap.get(t.id), rankMap.get(t.id))).join('')}<p class="tm-empty" data-team-empty hidden>没有符合条件的战队，清空搜索再试。</p>${teams.length ? '' : empty('当前没有识别到对手战队。')}</div>`)
      + block('合并重复战队', '合并会把来源战队的交手记录并入目标战队，历史保留。',
        `<div class="tm-tools">${form('merge', select('来源战队', 'from', options(teams)) + select('合并至', 'into', options(teams)), '合并战队')}</div>${suggestions ? `<ul class="tm-suggest">${suggestions}</ul>` : ''}`), false);
  }
  function teamDetail(value, key, compareData, bpData) {
    const teams = value.teams || [];
    const t = teams.find((x) => x.id === key);
    if (!t) return withPage('战队档案', '未找到这支战队。', empty('这支战队可能已被合并。'), false);
    const own = value.own || {};
    const info = tmScore(t);
    const p = t.percentiles || {};
    const cmp = compareData || {};
    const enemyPlayers = byLaneTm(cmp.players?.enemy || []);
    const enemyHeroes = [...(cmp.heroes?.enemy || [])].sort((a, b) => (b.games || 0) - (a.games || 0) || String(a.hero || '').localeCompare(String(b.hero || ''), 'zh'));
    const laneRows = (cmp.lanes || []).filter((row) => row.own || row.enemy);
    const combos2 = cmp.combos?.enemy?.combos || [];
    const combos3 = cmp.combos3?.enemy?.combos || [];
    const pool = cmp.pool?.enemy || {};
    const bpTeam = (bpData?.teams || []).find((x) => x.id === t.id);
    const games = [...(t.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const durations = games.map((g) => g.duration).filter((v) => hasNum(v) && v > 0);
    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    const oppRate = tmOppRate(t);
    const dims = (info?.dims || []).filter((d) => d.value != null).sort((a, b) => b.value - a.value);
    const topDims = dims.slice(0, 2);
    const lowDims = dims.slice(-2).reverse();
    const weakDims = lowDims.filter((d) => d.value < 60);
    const weakText = !dims.length ? '样本不足' : weakDims.length
      ? `相对短板 ${weakDims.map((d) => `${d.label} ${Math.round(d.value)}`).join('、')}`
      : '五项都在中上，没有明显短板';
    const lowTitle = !dims.length ? '样本不足' : weakDims.length ? '相对短板' : '短板不突出';
    const lowValue = !dims.length ? '—' : weakDims.length ? weakDims.map((d) => d.label).join(' / ') : '五项均衡';
    const lowNote = !dims.length ? '样本不足' : weakDims.length
      ? weakDims.map((d) => `${d.label} ${Math.round(d.value)}`).join(' · ')
      : `最低 ${lowDims[0].label} ${Math.round(lowDims[0].value)}`;
    const scoreRead = !dims.length ? '样本不足，暂无评分读法。'
      : `相对强项 ${topDims.map((d) => `${d.label} ${Math.round(d.value)}`).join('、')}；${weakText}。`;

    const tagList = [];
    const tag = (ok, label, cls) => { if (ok) tagList.push({label, cls}); };
    tag((t.matches || 0) < 3, '样本不足', 'sample');
    tag((oppRate ?? -1) >= 60, '结果占优', 'strong');
    tag((oppRate ?? 101) <= 40, '结果下风', 'weak');
    tag((p.gpm ?? -1) >= 70, '经济强', 'strong');
    tag((p.dpm ?? -1) >= 70, '输出高', 'strong');
    tag((p.kda ?? -1) >= 70, '对抗强', 'strong');
    tag((p.towerPerGame ?? -1) >= 70, '推进强', 'strong');
    tag((p.gpm ?? 101) <= 30, '经济弱', 'weak');
    tag((p.dpm ?? 101) <= 30, '输出低', 'weak');
    tag((p.kda ?? 101) <= 30, '对抗弱', 'weak');
    if (tagList.length === 1) tagList.push({label: '待观察', cls: 'neutral'});
    const tagHtml = tagList.slice(0, 5).map((x) => `<span class="tm-tag is-${x.cls}">${x.label}</span>`).join('');

    const hero = `<header class="tm-dossier">
      <div class="tm-dossier-top">
        <a class="tm-dossier-back" href="#teams">← 战队档案</a>
        <div class="tm-dossier-actions">
          <button type="button" class="tm-ghost" data-team-rename="${esc(t.id)}" data-team-label="${esc(t.displayName)}">${t.named ? '改名' : '命名'}</button>
          <button type="button" class="tm-ghost" data-action="filter">数据范围</button>
          <button type="button" class="tm-ghost" data-action="refresh">刷新</button>
        </div>
      </div>
      <div class="tm-dossier-main">
        <div class="tm-dossier-id">
          <span class="tm-dossier-crest">${esc((t.displayName || '?').slice(0, 1))}</span>
          <div class="tm-dossier-copy">
            <span class="tm-dossier-eyebrow">TEAM DOSSIER <i>/</i> 对手档案</span>
            <h1>${text(t.displayName)} ${info ? `<span class="tm-grade is-${info.grade.toLowerCase()}">${info.grade}</span>` : ''}</h1>
            <p>营地阵容聚类 · 首次 ${text(t.firstSeen)} · 最近 ${text(t.lastSeen)}</p>
            <div class="tm-tags">${tagHtml}</div>
          </div>
        </div>
        <div class="tm-dossier-score">
          <div class="tm-ring" style="--v:${info ? info.score : 0}" role="img" aria-label="${info ? `战队得分 ${info.score} 分，满分 100` : '暂无战队得分'}"><div><strong>${info ? info.score : '—'}</strong><small>/100</small></div></div>
          <div class="tm-dossier-score-copy"><span>战队得分</span><b>${info ? `${info.grade} 档` : '样本不足'}</b><small>${info ? `${info.coverage}/5 项 · ${fmt(t.matches)} 局样本` : '暂无可用指标'}</small></div>
        </div>
      </div>
      <div class="tm-dossier-stats">
        <span><small>交手</small><b>${fmt(t.matches)} 局</b></span>
        <span><small>本队战绩</small><b>${tmRecord(t)}</b></span>
        <span><small>对手胜率</small><b>${pct(oppRate)}</b></span>
        <span><small>场均时长</small><b>${time(avgDuration)}</b></span>
        <span><small>最近交手</small><b>${text(t.lastSeen)}</b></span>
      </div>
    </header>`;

    const scorePanel = `<article class="tm-panel" id="tm-score">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">SIGNAL / 01</span><h3>得分构成</h3></div><span class="tm-panel-meta">${info ? `${info.coverage}/5 项` : '样本不足'}</span></header>
      ${info ? `<div class="tm-score-body"><div class="tm-score-bars is-wide">${tmScoreBars(t, info)}</div>${tmRadar(info)}</div>` : empty('没有足够指标计算得分。')}
      <div class="tm-score-weights"><span>胜率 30%</span><span>经济 20%</span><span>对抗 20%</span><span>输出 15%</span><span>推进 15%</span></div>
      <p class="tm-score-read">${scoreRead}</p>
      <p class="tm-panel-note">胜率按对手视角；其余四项为同池分位。缺失项按剩余权重归一，不把没有样本的指标当成 0。</p>
    </article>`;

    const compareDefs = [['分均经济', 'gpm', 0], ['分均输出', 'dpm', 0], ['分均承伤', 'dtpm', 0], ['KDA', 'kda', 2], ['场均推塔', 'towerPerGame', 1]];
    const compareRows = compareDefs.map(([label, metricKey, digits]) => {
      const a = own.metrics?.[metricKey], b = t.metrics?.[metricKey];
      const max = Math.max(1, hasNum(a) ? a : 0, hasNum(b) ? b : 0);
      const diff = hasNum(a) && hasNum(b) ? b - a : null;
      return `<div class="tm-compare-row">
        <span class="tm-compare-k">${label}</span>
        <span class="tm-compare-cell is-own"><i style="--v:${(hasNum(a) ? Math.min(1, a / max) : 0).toFixed(3)}"></i><b>${fmt(a, digits)}</b><small>本队</small></span>
        <span class="tm-compare-cell is-opp"><i style="--v:${(hasNum(b) ? Math.min(1, b / max) : 0).toFixed(3)}"></i><b>${fmt(b, digits)}</b><small>对手</small></span>
        <span class="tm-compare-diff ${hasNum(diff) && diff > 0 ? 'is-up' : hasNum(diff) && diff < 0 ? 'is-down' : ''}">${tmSignedNum(diff, digits)}</span>
      </div>`;
    }).join('');
    const compareGap = compareDefs.map(([label, metricKey, digits]) => {
      const a = own.metrics?.[metricKey], b = t.metrics?.[metricKey];
      return {label, digits, diff: hasNum(a) && hasNum(b) ? b - a : null};
    }).filter((x) => hasNum(x.diff)).sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))[0];
    const comparePanel = `<article class="tm-panel" id="tm-compare">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">MATCHUP / 02</span><h3>数据对照</h3></div><span class="tm-panel-meta">对手 − 本队</span></header>
      <div class="tm-compare-legend"><span class="is-own">本队 · ${text(own.name || '')}</span><span class="is-opp">对手 · ${text(t.displayName)}</span></div>
      <div class="tm-compare-list">${compareRows}</div>
      ${compareGap ? `<p class="tm-compare-read">最大差距：<b>${compareGap.label}</b> ${tmSignedNum(compareGap.diff, compareGap.digits)}<small>对手 − 本队</small></p>` : ''}
      <p class="tm-panel-note">同一批营地对局面板；条形按两项中的较大值归一，不跨队排名。</p>
    </article>`;

    const recent = [...games].reverse().slice(-10);
    const formDots = recent.map((g) => `<span class="tm-form-dot ${g.win === true ? 'is-win' : g.win === false ? 'is-loss' : 'is-muted'}" title="${esc(g.start || '')}">${g.win === true ? '胜' : g.win === false ? '负' : '?'}</span>`).join('');
    const gameRows = games.map((g, index) => {
      const [cls, label] = tmResult(g);
      return `<div class="tm-game-row ${cls}">
        <span class="tm-game-index">${String(games.length - index).padStart(2, '0')}</span>
        <span class="tm-game-date"><b>${text(g.start || '时间未记录')}</b><small>${text(g.map || '地图未记录')}</small></span>
        <span class="tm-game-result">${label}</span>
        <span class="tm-game-duration">${time(g.duration)}<small>时长</small></span>
      </div>`;
    }).join('');
    const gamesPanel = `<article class="tm-panel" id="tm-games">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">TIMELINE / 03</span><h3>交手走势</h3></div><span class="tm-panel-meta">${fmt(games.length)} 局 · 本队视角</span></header>
      <div class="tm-form-row"><span>近 ${fmt(recent.length)} 局 · 本队</span><div class="tm-form-dots">${formDots || '<em>暂无记录</em>'}</div><span>左旧右新</span></div>
      <div class="tm-game-list">${gameRows || empty('还没有交手记录。')}</div>
    </article>`;

    const laneCards = laneRows.map((row) => {
      const o = row.own, e = row.enemy;
      const stat = (label, metricKey, digits) => {
        const ov = o?.[metricKey], ev = e?.[metricKey];
        const diff = hasNum(ov) && hasNum(ev) ? ev - ov : null;
        return `<div class="tm-duel-stat"><span>${label}</span><b>${fmt(ev, digits)}</b><small>本队 ${fmt(ov, digits)}${hasNum(diff) ? ` <em class="${diff > 0 ? 'is-up' : diff < 0 ? 'is-down' : ''}">${tmSignedNum(diff, digits)}</em>` : ''}</small></div>`;
      };
      return `<article class="tm-duel">
        <header><span class="tm-duel-lane">${esc(row.lane || '位置未知')}</span><span class="tm-duel-badge">对位</span></header>
        <div class="tm-duel-person"><i>${esc((e?.name || '?').slice(0, 1))}</i><div><b>${text(e?.name || '未记录')}</b><small>${fmt(e?.games || 0)} 局 · 对手视角</small></div></div>
        <div class="tm-duel-stats">${stat('KDA', 'kda', 2)}${stat('分均经济', 'gpm', 0)}${stat('分均输出', 'dpm', 0)}${stat('参团率', 'participation', 1)}</div>
      </article>`;
    }).join('');
    const lanePanel = `<article class="tm-panel" id="tm-lanes">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">LANE DUEL / 04</span><h3>分路对位</h3></div><span class="tm-panel-meta">${fmt(laneRows.length)} 路</span></header>
      <div class="tm-duel-grid">${laneCards || empty('还没有可用的分路明细。')}</div>
      <p class="tm-panel-note">对手选手来自营地十人面板，本队对照取同一路选手，不是全队均值。</p>
    </article>`;

    const heroTotal = pool.picks || enemyHeroes.reduce((sum, h) => sum + (h.games || 0), 0) || 1;
    const heroRows = enemyHeroes.slice(0, 8).map((h) => {
      const share = Math.min(100, (h.games || 0) / heroTotal * 100);
      const oppHeroRate = hasNum(h.winRate) ? 100 - h.winRate : null;
      return `<div class="tm-hero-line">
        <span class="tm-hero-art">${portrait(h.hero)}</span>
        <span class="tm-hero-name"><b>${text(h.hero)}</b><small>${esc(h.lane || '位置未知')} · ${fmt(h.games)} 局</small></span>
        <span class="tm-hero-cell"><small>对手胜率</small><b>${pct(oppHeroRate)}</b></span>
        <span class="tm-hero-cell"><small>KDA</small><b>${fmt(h.kda, 2)}</b></span>
        <span class="tm-hero-cell"><small>分均经济</small><b>${fmt(h.gpm)}</b></span>
        <span class="tm-hero-cell"><small>分均输出</small><b>${fmt(h.dpm)}</b></span>
        <span class="tm-hero-share"><i style="--v:${share.toFixed(1)}%"></i><small>${pct(share)}</small></span>
      </div>`;
    }).join('');
    const heroPanel = `<article class="tm-panel" id="tm-heroes">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">HERO POOL / 05</span><h3>英雄池</h3></div><span class="tm-panel-meta">${fmt(enemyHeroes.length)} 个英雄</span></header>
      <div class="tm-hero-summary">
        <span><small>英雄数</small><b>${fmt(pool.heroes ?? enemyHeroes.length)}</b></span>
        <span><small>选用次数</small><b>${fmt(pool.picks ?? heroTotal)}</b></span>
        <span><small>有效英雄</small><b>${fmt(pool.effective, 1)}</b></span>
        <span><small>集中度</small><b>${fmt(pool.hhi, 2)}</b></span>
      </div>
      <div class="tm-hero-list">${heroRows || empty('还没有可用的英雄明细。')}</div>
      <p class="tm-panel-note">有效英雄 = 1 / HHI；越高说明英雄池越分散，越低说明越依赖固定几手。</p>
    </article>`;

    const bpList = (rows, cls) => rows.slice(0, 6).map((x, index) => {
      const share = t.matches ? Math.min(100, x.count / t.matches * 100) : 0;
      return `<div class="tm-bp-row ${cls}"><span class="tm-bp-no">${String(index + 1).padStart(2, '0')}</span>${portrait(x.hero)}<b>${text(x.hero)}</b><span class="tm-bp-bar"><i style="width:${share.toFixed(1)}%"></i></span><small>${fmt(x.count)} 次 · ${pct(share)}</small></div>`;
    }).join('');
    const bpPanel = `<article class="tm-panel" id="tm-bp">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">DRAFT / 06</span><h3>BP 偏好</h3></div><span class="tm-panel-meta">${bpTeam ? `${fmt(bpTeam.games)} 局样本` : '缺失'}</span></header>
      ${bpTeam ? `<div class="tm-bp-cols">
        <div class="tm-bp-col is-pick"><header><b>常选</b><small>${fmt((bpTeam.picks || []).length)} 个英雄</small></header>${bpList(bpTeam.picks || [], 'is-pick')}</div>
        <div class="tm-bp-col is-ban"><header><b>常禁</b><small>${fmt((bpTeam.bans || []).length)} 个英雄</small></header>${bpList(bpTeam.bans || [], 'is-ban')}</div>
      </div>` : empty('还没有可用的 BP 明细。')}
      <p class="tm-panel-note">${bpTeam ? `最常选 ${text((bpTeam.picks || [])[0]?.hero || '—')}；最常禁 ${text((bpTeam.bans || [])[0]?.hero || '—')}。` : ''}次数来自营地禁选名单；手序不作猜测，只统计选择与禁用。</p>
    </article>`;

    const comboCol = (rows, size) => {
      const list = (rows || []).slice(0, 4);
      if (!list.length) return '';
      return `<div class="tm-combo-col"><header><b>${size} 人组合</b><small>${fmt(rows.length)} 组</small></header>
        ${list.map((c) => {
          const oppRate = hasNum(c.winRate) ? 100 - c.winRate : null;
          const oppSynergy = hasNum(c.synergy) ? -c.synergy : null;
          return `<div class="tm-combo-row">
            <span class="tm-combo-heroes">${(c.heroes || []).map((x) => portrait(x)).join('')}</span>
            <span class="tm-combo-copy"><b>${(c.heroes || []).map((x) => text(x)).join(' + ')}</b><small>${fmt(c.games)} 局 · 对手胜率 ${pct(oppRate)} · 协同 ${tmSignedNum(oppSynergy, 1)}</small></span>
            ${c.small ? '<span class="tm-tag is-sample">样本</span>' : ''}
          </div>`;
        }).join('')}
      </div>`;
    };
    const comboPanel = `<article class="tm-panel" id="tm-combos">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">SYNERGY / 07</span><h3>阵容组合</h3></div><span class="tm-panel-meta">${fmt(combos2.length + combos3.length)} 组</span></header>
      <div class="tm-combo-grid">${comboCol(combos2, 2)}${comboCol(combos3, 3)}${(!combos2.length && !combos3.length) ? empty('还没有可用的英雄组合。') : ''}</div>
      <p class="tm-panel-note">协同 = 组合胜率 − 各英雄单独胜率均值；样本不足的组合只作记录。</p>
    </article>`;

    const bucketDefs = [[0, 720, '≤12 分'], [720, 1200, '12-20 分'], [1200, Infinity, '>20 分']];
    const buckets = bucketDefs.map(([min, max, label]) => {
      const rows = games.filter((g) => hasNum(g.duration) && g.duration >= min && g.duration < max);
      const wins = rows.filter((g) => g.win === true).length;
      return {label, games: rows.length, wins, rate: rows.length ? wins / rows.length * 100 : null};
    });
    const bucketTotal = buckets.reduce((sum, b) => sum + b.games, 0) || 1;
    const bucketRows = buckets.map((b) => `<div class="tm-bucket-row"><span>${b.label}</span><span class="tm-bucket-bar"><i style="width:${(b.games / bucketTotal * 100).toFixed(1)}%"></i></span><b>${fmt(b.games)} 局</b><small>${b.games ? pct(b.rate) : '—'}</small></div>`).join('');
    const first = games[0]?.win;
    let streak = 0;
    for (const g of games) { if (first !== null && g.win === first) streak++; else break; }
    const streakText = first === true ? `${streak} 连胜` : first === false ? `${streak} 连败` : '—';
    const rhythmPanel = `<article class="tm-panel" id="tm-rhythm">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">TEMPO / 08</span><h3>节奏与终结</h3></div><span class="tm-panel-meta">${fmt(games.length)} 局</span></header>
      <div class="tm-rhythm-figures">
        <div><strong>${time(avgDuration)}</strong><small>场均时长</small></div>
        <div><strong>${streakText}</strong><small>本队走势</small></div>
        <div><strong>${pct(oppRate)}</strong><small>对手胜率</small></div>
      </div>
      <div class="tm-bucket-list">${bucketRows}</div>
      <p class="tm-panel-note">时长分桶只统计有时长的局；胜率按对手视角计算。</p>
    </article>`;

    const pressure = laneRows.map((row) => ({lane: row.lane, diff: (row.enemy?.dpm || 0) - (row.own?.dpm || 0), opp: row.enemy, own: row.own}))
      .filter((row) => hasNum(row.diff)).sort((a, b) => b.diff - a.diff)[0];
    const advice = [];
    advice.push(`样本 ${fmt(t.matches)} 局，${(t.matches || 0) < 3 ? '不足以判断真实强弱，重点看单局习惯' : '可做初步强弱判断'}`);
    if (bpTeam) advice.push(`常选 ${((bpTeam.picks || []).slice(0, 2).map((x) => x.hero).join(' / ') || '—')}；常禁 ${((bpTeam.bans || []).slice(0, 2).map((x) => x.hero).join(' / ') || '—')}`);
    advice.push(`场均 ${time(avgDuration)}，${first === true ? '本队最近一局取胜' : first === false ? '本队最近一局失利' : '最近结果未知'}`);
    const insightCopy = !dims.length ? '样本不足，暂不做强弱判断。'
      : `${t.displayName} 的相对强项集中在 ${topDims.map((d) => d.label).join('、')}；${weakText}。${pressure ? `对位压力最大的是 ${pressure.lane}，对手分均输出比本队同位置 ${tmSignedNum(pressure.diff, 0)}。` : ''}`;
    const insightPanel = `<article class="tm-panel tm-panel-insight" id="tm-insight">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">READ / 09</span><h3>赛前洞察</h3></div><span class="tm-panel-meta">${info ? `${info.grade} 档` : '样本不足'}</span></header>
      <div class="tm-insight-cards">
        <div class="tm-insight-card"><span>相对强项</span><b>${topDims.map((d) => d.label).join(' / ') || '—'}</b><small>${topDims.map((d) => `${d.label} ${Math.round(d.value)}`).join(' · ') || '样本不足'}</small></div>
        <div class="tm-insight-card ${weakDims.length ? 'is-weak' : 'is-neutral'}"><span>${lowTitle}</span><b>${lowValue}</b><small>${lowNote}</small></div>
        <div class="tm-insight-card is-pressure"><span>对位压力</span><b>${pressure?.lane || '—'}</b><small>${pressure ? `分均输出差 ${tmSignedNum(pressure.diff, 0)}` : '对位样本不足'}</small></div>
      </div>
      <p class="tm-insight-copy">${esc(insightCopy)}</p>
      <ul class="tm-advice">${advice.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
      <p class="tm-panel-note">以上为赛前提醒，不替代临场 BP 与选手状态判断。</p>
    </article>`;

    const quality = [
      ['对局面板', t.matches ? `${fmt(t.matches)} 局` : '缺失', (t.matches || 0) > 0],
      ['选手明细', `${fmt(enemyPlayers.length)} / 5 人`, enemyPlayers.length >= 5],
      ['英雄明细', `${fmt(enemyHeroes.length)} 个`, enemyHeroes.length > 0],
      ['BP 明细', bpTeam ? (bpTeam.available ? '可用' : '缺失') : '缺失', !!bpTeam?.available],
      ['阵容组合', combos2.length + combos3.length ? `${fmt(combos2.length + combos3.length)} 组` : '缺失', combos2.length + combos3.length > 0],
      ['样本门槛', (t.matches || 0) >= 3 ? '达标' : '不足 3 局', (t.matches || 0) >= 3],
    ];
    const qualityPanel = `<article class="tm-panel" id="tm-quality">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">COVERAGE / 10</span><h3>数据质量</h3></div><span class="tm-panel-meta">${fmt(quality.filter((x) => x[2]).length)} / ${fmt(quality.length)} 项</span></header>
      <div class="tm-quality-grid">${quality.map(([label, value, ok]) => `<div class="tm-quality-item ${ok ? 'is-ok' : 'is-warn'}"><span>${label}</span><b>${value}</b><i>${ok ? '✓' : '!'}</i></div>`).join('')}</div>
      ${cmp.warnings?.length ? `<p class="tm-panel-note is-warn">${esc(cmp.warnings.join('；'))}</p>` : ''}
    </article>`;

    const renamePanel = `<article class="tm-panel" id="tm-rename">
      <header class="tm-panel-head"><div><span class="tm-panel-kicker">MASTER DATA</span><h3>命名与维护</h3></div><span class="tm-panel-meta">${t.named ? '已命名' : '待命名'}</span></header>
      ${form('rename', `<input type="hidden" name="id" value="${esc(t.id)}">` + field('战队名称', 'name', t.name || '', 'required maxlength="40"'), '保存名称')}
      <p class="tm-panel-note">命名后，对局、BP 与报告里的对手都会显示这个名字。</p>
    </article>`;

    const layer = (id, no, en, title, sub, badge, body) => `<section class="tm-layer" id="tm-${id}">
      <header class="tm-layer-head">
        <span class="tm-layer-no">${no}</span>
        <div><span class="tm-layer-kicker">${en}</span><h2>${title}</h2><p>${esc(sub)}</p></div>
        <span class="tm-layer-badge is-${id}">${badge}</span>
      </header>
      ${body}
    </section>`;

    return `<div class="page feature-page tm-detail-page">
      ${hero}
      <nav class="tm-jump" aria-label="分析目录">
        <button type="button" data-tm-jump="tm-basic">01 基础</button>
        <button type="button" data-tm-jump="tm-lanes">02 分路</button>
        <button type="button" data-tm-jump="tm-heroes">03 英雄 / BP</button>
        <button type="button" data-tm-jump="tm-combos">04 组合</button>
        <button type="button" data-tm-jump="tm-rhythm">05 节奏</button>
        <button type="button" data-tm-jump="tm-insight">06 洞察</button>
      </nav>
      ${layer('basic', '01', 'BASIC / 基础层', '先把基本盘看清', '战绩、得分构成与同一批面板的数据对照。', '基础', `<div class="tm-layer-grid is-two">${scorePanel}${comparePanel}</div><div class="tm-layer-grid">${gamesPanel}</div>`)}
      ${layer('mid', '02', 'INTERMEDIATE / 中级层', '再看对位与习惯', '分路对位、英雄池、BP 偏好与阵容组合。', '中级', `<div class="tm-layer-grid">${lanePanel}</div><div class="tm-layer-grid is-two">${heroPanel}${bpPanel}</div><div class="tm-layer-grid">${comboPanel}</div>`)}
      ${layer('advanced', '03', 'ADVANCED / 高级层', '最后做赛前判断', '节奏、强项短板、对位压力与数据质量。', '高级', `<div class="tm-layer-grid is-two">${rhythmPanel}${insightPanel}</div><div class="tm-layer-grid is-two">${qualityPanel}${renamePanel}</div>`)}
    </div>`;
  }
  function h2h(value) {
    const games = [];
    for (const t of value.teams || []) {
      for (const g of t.games || []) games.push({ start: g.start || '', win: g.win, duration: g.duration, map: g.map || '', team: t });
    }
    games.sort((a, b) => String(b.start).localeCompare(String(a.start)));
    const wins = games.filter((g) => g.win === true).length;
    const losses = games.filter((g) => g.win === false).length;
    const foes = new Set(games.map((g) => g.team.id)).size;
    const rows = games.map((g, i) => {
      const cls = g.win === true ? 'win' : g.win === false ? 'loss' : 'muted';
      const label = g.win === true ? '胜' : g.win === false ? '负' : '未知';
      const when = g.start || '时间未记录';
      const map = g.map || '地图未记录';
      return `<a class="fj-row tm-h2h ${cls}" href="${route('team', g.team.id)}">
        <span class="fj-no">第 ${i + 1} 局</span>
        <span class="fj-main"><b>${text(g.team.displayName)}</b><small>${text(when)} · ${text(map)}</small></span>
        <span class="tm-res ${cls}">${label}</span>
        <span class="fj-num">${time(g.duration)}<small>时长</small></span>
        <span class="fj-num">${fmt(g.team.matches)}<small>与该队交手</small></span>
        <span class="fj-go">→</span></a>`;
    }).join('');
    const rate = (wins + losses) ? pct(wins / (wins + losses) * 100) : '—';
    const perTeam = foes ? fmt(games.length / foes) + ' 局' : '—';
    const head = lede([
      ['交手局数', fmt(games.length) + ' 局', fmt(foes) + ' 支对手'],
      ['结果', fmt(wins) + ' 胜 ' + fmt(losses) + ' 负', '胜率 ' + rate],
      ['每队样本', perTeam, foes === games.length ? '每支只交手 1 局' : '分布不均'],
      ['最近一局', text(games[0] ? games[0].start : ''), games[0] ? text(games[0].team.displayName) : '—'],
    ]);
    const list = '<div class="fj-list">' + (rows || empty('当前范围没有交手记录。')) + '</div>';
    return withPage('交手记录', '按时间倒序的逐局交手，胜负为本队视角 · ' + TM_NOTE, head + block('逐局交手', '点任意一行进入该对手的主页，看阵容与数据对照。', list), false);
  }
  function profiles(value) {
    const min = value.minGames || 3;
    const all = value.profiles || [];
    const ready = all.filter((p) => p.available).sort((a, b) => (b.games || 0) - (a.games || 0));
    const near = [...all].sort((a, b) => (b.games || 0) - (a.games || 0)).slice(0, 4);
    const buckets = new Map();
    for (const p of all) { const n = Math.min(p.games || 0, min); buckets.set(n, (buckets.get(n) || 0) + 1); }
    const sampleBar = `<div class="tm-samples">${[...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([n, c]) => `<div><span>${n >= min ? `${min} 局以上` : `${n} 局`}</span><i style="--v:${(c / Math.max(1, all.length)).toFixed(3)}"></i><b>${fmt(c)} 支</b></div>`).join('')}</div>`;
    const cards = ready.map((p) => `<a class="tm-profile" href="${route('team', p.id)}">
      ${tmCrest(p.name)}
      <span class="tm-profile-main"><b>${text(p.name)}</b><small>${fmt(p.games)} 局样本 · 对手胜率 ${pct(p.winRate)}</small></span>
      <span class="tm-profile-heroes">${(p.heroes || []).slice(0, 5).map((x) => portrait(x.hero)).join('')}</span>
      <span class="fj-go">→</span></a>`).join('');
    const nearRows = near.map((p) => `<a class="fj-row tm-row" href="${route('team', p.id)}">
      <span class="fj-no">${fmt(p.games)} 局</span>
      <span class="fj-main"><b>${text(p.name)}</b><small>${text(p.reason || `再来 ${min - (p.games || 0)} 局可生成画像`)}</small></span>
      <span class="tm-slot">${Array.from({ length: min }, (_, i) => `<i class="${i < (p.games || 0) ? 'on' : ''}"></i>`).join('')}</span>
      <span class="fj-num">${fmt(Math.max(0, min - (p.games || 0)))}<small>还差</small></span>
      <span class="fj-go">→</span></a>`).join('');
    if (!ready.length) {
      return withPage('对手画像', `同一支对手至少交给 ${min} 局才生成画像 · ${TM_NOTE}`,
        lede([['对手战队', `${fmt(all.length)} 支`, '阵容聚类'], ['达到门槛', '0 支', `门槛 ${min} 局`],
          ['最多交手', `${fmt(Math.max(0, ...all.map((p) => p.games || 0)))} 局`, '当前样本上限'],
          ['门槛差', `${fmt(Math.max(0, min - Math.max(0, ...all.map((p) => p.games || 0))))} 局`, '再交手多少次']])
        + block('样本分布', `按与每支对手的交手局数分布；到 ${min} 局才会出现在上方画像里。`, sampleBar)
        + block('最接近门槛', '按交手局数排列，点进去可以先看阵容与逐局。', `<div class="fj-list">${nearRows || empty('还没有对手记录。')}</div>`), false);
    }
    return withPage('对手画像', `${fmt(ready.length)} 支对手达到 ${min} 局门槛 · ${TM_NOTE}`,
      lede([['达到门槛', `${fmt(ready.length)} 支`, `共 ${fmt(all.length)} 支对手`],
        ['门槛', `${min} 局`, '同一支对手'],
        ['样本合计', `${fmt(ready.reduce((s, p) => s + (p.games || 0), 0))} 局`, '画像覆盖'],
        ['未达门槛', `${fmt(all.length - ready.length)} 支`, '见下方样本分布']])
      + block('对手画像', '点进去看阵容、常用英雄与逐局交手。', `<div class="tm-profiles">${cards}</div>`)
      + block('样本分布', '未达门槛的对手先积累样本。', sampleBar), false);
  }
  function ownership(value) {
    const teams = value.teams || [];
    const loose = value.unassigned || [];
    const members = [...loose, ...teams.flatMap((t) => t.players || [])];
    const named = teams.filter((t) => t.named).length;
    const unassigned = members.filter((p) => !p.teamId).length;
    const manual = members.filter((p) => p.manual).length;
    const playerLine = (p) => `<div class="sx-own-player">
      <span class="sx-own-avatar">${esc((p.name || '?').slice(0, 1))}</span>
      <span class="sx-own-pname"><b>${text(p.name)}</b><small>${text((p.lanes || []).join(' / ') || '位置未记录')} · ${fmt(p.games)} 场</small></span>
      <span class="sx-own-source ${p.manual ? 'is-manual' : ''}">${p.manual ? '手动确认' : p.teamId ? '阵容推断' : '未归属'}</span>
      <button type="button" class="control sx-own-action" data-sx-player-assign="${esc(p.id)}" data-player-name="${esc(p.name)}" data-team-id="${esc(p.teamId || '')}">调整</button>
    </div>`;
    const groups = [];
    if (loose.length) groups.push({
      name:'未归属选手', named:false, unassigned:loose.length,
      search:('未归属 ' + loose.map((p) => p.name).join(' ')).toLowerCase(),
      html:`<details class="sx-own-group is-loose" data-sx-own-group data-sx-name="${esc(('未归属 ' + loose.map((p) => p.name).join(' ')).toLowerCase())}" data-sx-named="0" data-sx-unassigned="${loose.length}">
        <summary><span class="sx-own-crest is-warn">!</span><span class="sx-own-title"><b>未归属选手</b><small>${loose.length} 名选手还没有战队</small></span><span class="sx-own-state is-pending">待指派</span><span class="sx-own-toggle">展开</span></summary>
        <div class="sx-own-players"><div class="sx-own-hint">先在建档页命名战队，再把这些选手指派过去。</div>${loose.map(playerLine).join('')}</div>
      </details>`,
    });
    teams.forEach((t) => {
      const players = t.players || [];
      if (!players.length) return;
      groups.push({
        name:t.displayName, named:!!t.named, unassigned:players.filter((p) => !p.teamId).length,
        search:(t.displayName + ' ' + players.map((p) => p.name).join(' ')).toLowerCase(),
        html:`<details class="sx-own-group" data-sx-own-group data-sx-name="${esc((t.displayName + ' ' + players.map((p) => p.name).join(' ')).toLowerCase())}" data-sx-named="${t.named ? '1' : '0'}" data-sx-unassigned="${players.filter((p) => !p.teamId).length}">
          <summary><span class="sx-own-crest">${esc((t.displayName || '?').slice(0, 1))}</span><span class="sx-own-title"><b>${text(t.displayName)}</b><small>${players.length} 名选手${t.named ? '' : ' · 还没命名'}</small></span><span class="sx-own-state ${t.named ? 'is-named' : 'is-pending'}">${t.named ? '已命名' : '待命名'}</span><span class="sx-own-toggle">展开</span></summary>
          <div class="sx-own-players">${t.named ? '' : `<div class="sx-own-hint">战队名仍是占位名。<button type="button" class="sx-inline-btn" data-sx-team-rename="${esc(t.id)}" data-team-name="${esc(t.displayName)}">就地命名 →</button></div>`}${players.map(playerLine).join('')}</div>
        </details>`,
      });
    });
    const groupHtml = groups.map((g, i) => g.html.replace('<details ', `<details ${i >= 5 ? 'hidden ' : ''}`)).join('');
    const toolbar = `<div class="sx-toolbar">
      <label class="sx-search">${icon('search')}<input data-sx-own-search placeholder="搜索战队或选手昵称" aria-label="搜索战队或选手"></label>
      <div class="sx-chips">
        <button type="button" class="fj-chip" data-sx-own-chip="all" aria-pressed="true">全部 ${teams.length}</button>
        <button type="button" class="fj-chip" data-sx-own-chip="unnamed" aria-pressed="false">待命名 ${teams.length - named}</button>
        ${unassigned ? `<button type="button" class="fj-chip" data-sx-own-chip="unassigned" aria-pressed="false">有未归属 ${unassigned}</button>` : ''}
      </div>
      <span class="sx-toolbar-count" data-sx-own-count>共 ${teams.length} 支 · ${members.length} 名</span>
    </div>`;
    const nextCta = teams.length - named > 0 ? `<a class="primary sx-head-cta" href="#setup">去建档命名 →</a>` : '';
    const dialog = `<dialog class="sx-dialog" id="sx-team-dialog">
      <form data-feature-form="sxTeamDialog">
        <div class="sx-dialog-head"><div><span class="sx-eyebrow">主数据维护</span><h2 data-sx-dialog-title>命名战队</h2></div><button type="button" class="sx-dialog-x" data-sx-dialog-close aria-label="关闭">×</button></div>
        <div class="sx-dialog-panel" data-sx-dialog-panel="rename">
          <input type="hidden" name="id">
          <label>战队名<input name="name" maxlength="40" placeholder="如：重庆狼队"></label>
          <label>主教练<input name="coach" maxlength="40" placeholder="可留空"></label>
          <p class="sx-dialog-note">保存后会同步到对局、BP、报告与对手归属。</p>
        </div>
        <div class="sx-dialog-panel" data-sx-dialog-panel="assign" hidden>
          <input type="hidden" name="playerId">
          <p class="sx-dialog-subject" data-sx-dialog-player></p>
          <label>所属战队<select name="teamId"><option value="">未归属</option>${teams.map((t) => `<option value="${esc(t.id)}">${esc(t.displayName)}</option>`).join('')}</select></label>
        </div>
        <p class="form-status" role="status"></p>
        <div class="sx-dialog-actions"><button type="button" class="control" data-sx-dialog-close>取消</button><button class="primary" type="submit">保存</button></div>
      </form>
    </dialog>`;
    return withPage('对手归属', `以战队为单位核对选手归属 · ${teams.length} 支战队中 ${named} 支已命名；改完立即在对局与 BP 页生效。`,
      lede([['对手战队', `${fmt(teams.length)} 支`, `${fmt(named)} 支已命名`],
        ['对手选手', `${fmt(members.length)} 名`, `${fmt(unassigned)} 名未归属`],
        ['待命名', `${fmt(teams.length - named)} 支`, '命名后显示真实队名'],
        ['手动确认', `${fmt(manual)} 名`, '其余为阵容推断']])
      + block('战队与选手', '默认展示前 5 支战队；展开后可命名战队或调整选手，搜索会跨全部战队匹配选手昵称。',
        `${toolbar}<div class="sx-own-groups" data-sx-own-groups>${groupHtml || empty('当前没有识别到对手选手。')}<p class="sx-empty" data-sx-own-empty hidden>没有符合条件的战队或选手。</p></div>
        <button class="sx-more" type="button" data-sx-own-more ${groups.length <= 5 ? 'hidden' : ''}>展开全部 ${groups.length} 组</button>`,
        `<span class="sx-count">${fmt(teams.length)} 支</span>`,'data-sx-scope="ownership"')
      + dialog, false, nextCta, false, true);
  }
  function coach(board, roster) {
    bpCoachState = { mode: 'coach', board, roster, key: roster.teams[0]?.id || board.teams[0]?.id || '' };
    return `<div class="page bp-page hero-detail-page" data-bp-subject="coach">${bpCoachHtml()}</div>`;
  }
  function identity(value) {
    const unbound=value.entries.filter(x=>!x.bound);
    const names=value.entries.map(x=>`<option value="${esc(x.label)}">${text(x.label)} · ${fmt(x.matches)} 局${x.bound?' · 已认领':''}</option>`).join('');
    const members=value.members.map(x=>`<option value="${esc(x.id)}">${text(x.name)}${x.position?' · '+text(x.position):''}</option>`).join('');
    const fields=select('对局昵称','label',names)+select('本队选手','playerId',members);
    const claim=form('identityClaim',fields,'确认认领').replace('<form class="feature-form"','<form class="feature-form" data-aliases="'+esc(JSON.stringify(value.aliases))+'"');
    const roster=form('identityRoster',field('选手名称','name','','required maxlength="40"')+select('位置','position','<option value="">待确认</option>'+['对抗路','打野','中路','发育路','游走'].map(x=>`<option value="${x}">${x}</option>`).join('')),'添加本队选手');
    const cards=`<div class="roster-chips">${value.entries.slice(0,18).map(x=>`<span><i>${text(x.label.slice(0,1))}</i><b>${text(x.label)}</b><small>${fmt(x.matches)} 局 · ${x.bound?'已认领':'待认领'}</small></span>`).join('')||empty('当前范围暂无本队昵称。')}</div>`;
    return withPage('选手认领','将对局昵称连接到本队选手，让跨对局分析使用稳定身份。',stats([['本队昵称',fmt(value.entries.length),'当前数据范围'],['待认领',fmt(unbound.length),'需要教练确认'],['本队名单',fmt(value.members.length),'有效选手'],['身份来源','人工','不会自动猜测']])+block('认领昵称','确认该昵称确属这名本队选手后保存。',claim)+block('本队名单','新增后会同时建立选手主数据。',roster)+block('昵称概览','展示前 18 个昵称；可在上方选择全部昵称。',cards),false);
  }
  function compare(value) {
    const players=value.players.own||[], lanes=value.lanes||[];
    return withPage('选手与位置对比','营地结算面板 · 统计按本队与对手分别汇总。',block('本队选手','按出场次数展示；分均指标按有时长的营地局计算。',bars(players,p=>p.name,p=>p.games,p=>`${fmt(p.games)} 局`)+multiTable(['选手','位置','场次','KDA','分均经济','分均输出','参团率'],players.map(p=>[text(p.name),text(p.lane),fmt(p.games),fmt(p.kda,2),fmt(p.gpm),fmt(p.dpm),pct(p.participation)])))+
      block('位置对比','各位置以营地数据汇总，以下展示本队分均经济；样本不足时不作能力结论。',bars(lanes,p=>p.lane,p=>p.own?.gpm,p=>`${fmt(p.own?.gpm)} 金 / 分`)+multiTable(['位置','本队场次','本队分均经济','对手场次','对手分均经济'],lanes.map(x=>[text(x.lane),fmt(x.own?.games),fmt(x.own?.gpm),fmt(x.enemy?.games),fmt(x.enemy?.gpm)]))));
  }
  /* 英雄档位沿用 KPL 赛研 common.js:tierOf —— 按胜率 55 / 50 / 45 分 S/A/B/C。
     V2 的 winRate 是 0–100 百分数，赛研是 0–1 小数，阈值按百分数写。 */
  const tierOf = (wr) => typeof wr === 'number' && Number.isFinite(wr)
    ? (wr >= 55 ? 'S' : wr >= 50 ? 'A' : wr >= 45 ? 'B' : 'C') : null;
  const tierBadge = (t) => `<span class="hero-tier is-${t || 'none'}" data-hero-tier="${t || ''}">${t || '—'}</span>`;
  function heroes(value) {
    const pool = value.pool || {};
    const rows = (value.heroes.own || []).map(p => ({ ...p, tier: tierOf(p.winRate) }));
    const tierCount = t => rows.filter(p => p.tier === t).length;
    const rated = rows.filter(p => p.tier);
    const topWr = [...rated].sort((a, b) => b.winRate - a.winRate)[0];
    const topGames = [...rows].sort((a, b) => (b.games || 0) - (a.games || 0))[0];
    const brief = `<div class="hero-brief">当前范围 <b>${fmt(value.games)} 局</b>训练赛 · <b>${fmt(rows.length)} 个英雄</b>：<b>${fmt(tierCount('S'))} 个</b>进入 S 档（胜率 ≥ 55%）${topWr ? `，胜率最高是 <b>${esc(topWr.hero)}</b>（<b>${pct(topWr.winRate)}</b>，${fmt(topWr.games)} 局）` : ''}${topGames ? `，出场最多是 <b>${esc(topGames.hero)}</b>（${fmt(topGames.games)} 局）` : ''}。点击英雄查看各位置表现。</div>`;
    const tierOptions = [['S', '≥ 55%'], ['A', '≥ 50%'], ['B', '≥ 45%'], ['C', '&lt; 45%']]
      .map(([t, cond]) => `<option value="${t}">${t} 档 · ${cond} · ${tierCount(t)} 个</option>`).join('');
    const controls = `<div class="hero-filterbar"><label>搜索英雄<input data-hero-filter="name" placeholder="输入英雄名"></label><label>档位<select data-hero-filter="tier"><option value="">全部档位</option>${tierOptions}</select></label><span class="hero-filter-count" data-hero-count>共 ${fmt(rows.length)} 个英雄</span></div>`;
    const cards = `<div class="hero-card-grid">${rows.map(p => `<a class="hero-insight-card" data-hero-row data-hero-name="${esc(p.hero || '')}" data-hero-tier="${p.tier || ''}" href="${route('hero', p.hero)}">${portrait(p.hero)}<span><b>${text(p.hero)} ${tierBadge(p.tier)}</b><small>${text(p.lane || '位置未知')} · ${fmt(p.games)} 局</small></span><strong>${pct(p.winRate)}<small>胜率</small></strong></a>`).join('') || empty('当前范围暂无英雄记录。')}</div>`;
    return withPage('英雄榜', '从营地选用与结算面板观察英雄池。',
      stats([['本队英雄数', fmt(pool.own?.heroes), '已出现英雄'], ['英雄池深度', fmt(pool.own?.effective, 1), '按选用集中度折算 · 越高越分散'], ['本队出场', fmt(pool.own?.picks), '英雄选用次数'], ['营地局数', fmt(value.games), '样本范围']]) +
      block('英雄表现', '按胜率分档展示本队出场样本，点击英雄查看各位置表现。', `<div class="hero-board">${brief}${controls}${cards}</div>`));
  }
  /* 英雄详情：照 KPL 赛研 hero.html 的对象页范式 —— 顶部返回 + KPI 统计条 +
     各位置表现 / 双人搭档 / 三人组合 / 常见出装 / 选手出装 / 出装与表现 /
     选手使用榜 / 战队使用 / 本队均值对照 / 成长曲线 / 最近出场 / 时间表现 /
     同位置对位，十三块分析，一块一行全宽。
     「选手出装」即赛研的「职业哥同款」，同一块，不另设重复模块。装备图标来自 catalog.json 本地资源 + 赛研在线映射。
     数据源 = camp-compare + camp-partners + matches + lane_matchup +
     equip_matrix / equip_impact（按 hero 过滤）+ v2/hero-detail。 */
  function heroDetail(value, partners, matchesData, matchup, equipMatrix, equipImpact, summary, key) {
    const equipImg = (name) => equipIcons[name] ? `<img class="equip-icon" src="${esc(equipIcons[name])}" alt="" loading="lazy">` : '';
    const pctClamp = (v) => Math.max(0, Math.min(100, typeof v === 'number' && Number.isFinite(v) ? v : 0));
    const deltaCls = (v) => (typeof v === 'number' && v < 0 ? 'is-neg' : 'is-pos');
    const initial = (s) => esc(String(s || '?').slice(0, 1));
    const bar = (v, cls = '') => `<div class="hz-track"><i class="${cls}" style="width:${pctClamp(v)}%"></i></div>`;
    const bipole = (v, scale = 30) => `<div class="hz-bipole"><i class="${deltaCls(v)}" style="width:${Math.min(50, Math.abs(v || 0) / scale * 50)}%"></i></div>`;
    const voxels = (v) => `<div class="hz-voxels">${Array.from({ length: 10 }, (_, i) => `<i class="${i < Math.round(pctClamp(v) / 10) ? 'is-on' : ''}"></i>`).join('')}</div>`;
    const list = ((value?.heroes?.own) || []).filter(x => x.hero === key);
    const totalGames = list.reduce((s, x) => s + (x.games || 0), 0);
    const decided = list.reduce((s, x) => s + (x.decided || 0), 0);
    const wins = list.reduce((s, x) => s + (x.wins || 0), 0);
    const winRate = decided ? wins / decided * 100 : null;
    const weighted = (field) => {
      const rows = list.filter(x => typeof x[field] === 'number' && x.games);
      const n = rows.reduce((s, x) => s + x.games, 0);
      return n ? rows.reduce((s, x) => s + x[field] * x.games, 0) / n : null;
    };
    const tier = tierOf(winRate);
    const mainLane = [...list].sort((a, b) => (b.games || 0) - (a.games || 0))[0]?.lane || '位置未记录';
    const intro = `本队 ${fmt(totalGames)} 局使用${winRate == null ? '' : ` · 胜率 ${pct(winRate)} · ${tier} 档`} · 主要打${esc(mainLane)}`;
    const kpi = `<div class="hero-kpi">${[
      ['出场', fmt(totalGames), '局', null],
      ['胜率', pct(winRate), decided ? `${fmt(wins)} 胜 / ${fmt(decided)} 局` : '暂无有胜负对局', winRate],
      ['档位', tier || '—', tier ? '按胜率划分' : '无评级', null],
      ['KDA', fmt(weighted('kda'), 2), '按场次加权', null],
      ['分均经济', fmt(weighted('gpm')), '营地结算', null],
      ['分均输出', fmt(weighted('dpm')), '营地结算', null],
      ['参团率', pct(weighted('participation')), '按场次加权', null],
    ].map(([label, val, note, meter]) => `<div class="hero-kpi-cell"><span>${label}</span><strong>${val}</strong>${meter == null ? '' : `<div class="hero-kpi-track"><i style="width:${Math.max(0, Math.min(100, meter))}%"></i></div>`}<p>${note}</p></div>`).join('')}</div>`;

    const lanePanel = block('各位置表现', '按出场位置分别统计，档位沿用英雄榜的胜率口径。', list.length ? `<div class="hz-lane-grid">${list.map(x => `<article class="hz-card hz-lane-card"><div class="hz-card-top"><b>${text(x.lane || '位置未记录')}</b>${tierBadge(tierOf(x.winRate))}<span>${fmt(x.games)} 局</span></div><div class="hz-big">${pct(x.winRate)}<small>胜率</small></div>${bar(x.winRate)}<div class="hz-metric-grid"><span>KDA<b>${fmt(x.kda, 2)}</b></span><span>分均经济<b>${fmt(x.gpm)}</b></span><span>分均输出<b>${fmt(x.dpm)}</b></span><span>参团率<b>${pct(x.participation)}</b></span></div></article>`).join('')}</div>` : empty('该英雄暂无按位置汇总的样本。'));

    const partnerRows = partners?.partners || [];
    const partnerPanel = block('常用搭档', `双人同队同局 · 共 ${fmt(partners?.pairs ?? partnerRows.length)} 组`, partnerRows.length ? `<div class="hz-partner-grid">${partnerRows.slice(0, 9).map(p => `<a class="hz-card hz-partner-card" href="${route('hero', p.partner)}"><div class="hz-duo">${portrait(key)}<span>+</span>${portrait(p.partner)}</div><div class="hz-card-main"><b>${text(p.partner)}</b><small>${fmt(p.games)} 局 · 组合胜率 ${pct(p.winRate)}</small></div><div class="hz-delta ${deltaCls(p.synergy)}">${diff(p.synergy)}<small>pp</small></div>${bipole(p.synergy)}</a>`).join('')}</div>` : empty('当前范围没有达到样本门槛的搭档组合。'));

    const trioRows = ((value?.combos3?.own?.combos) || []).filter(c => c.heroes.includes(key)).slice(0, 6);
    const trioPanel = block('核心三人组合', '同队同局共现 · 与单英雄基准比较', trioRows.length ? `<div class="hz-trio-grid">${trioRows.map(c => `<article class="hz-card hz-trio-card"><div class="hz-trio-heroes">${c.heroes.map(h => portrait(h)).join('')}</div><b class="hz-trio-name">${c.heroes.map(h => text(h)).join(' + ')}</b><div class="hz-stat-row"><span><strong>${pct(c.winRate)}</strong><small>组合胜率</small></span><span><strong>${pct(c.expected)}</strong><small>基准</small></span><span class="${deltaCls(c.synergy)}"><strong>${diff(c.synergy)}</strong><small>协同 pp</small></span></div>${bar(c.winRate)}</article>`).join('')}</div>` : empty('当前范围没有达到样本门槛的三人组合。'));

    const heroMatches = ((matchesData?.matches) || []).filter(m => (m.heroes || []).includes(key)).slice(0, 8);
    const resultLabel = { win: '胜利', loss: '失利' };
    const matchPanel = block('最近出场', '点击对局查看完整复盘。', heroMatches.length ? `<div class="hz-timeline">${heroMatches.map(m => `<a class="hz-timeline-row" href="${route('match', m.key)}"><i class="hz-dot ${m.result === 'win' ? 'is-win' : m.result === 'loss' ? 'is-loss' : ''}"></i><span class="hz-date">${text(m.date || '日期未知')}</span><b>${text(m.opponent ? '对阵 ' + m.opponent : '对手未标注')}</b><span class="hz-badge ${m.result === 'win' ? 'is-win' : m.result === 'loss' ? 'is-loss' : ''}">${resultLabel[m.result] || '结果未知'}</span><span class="hz-dur">${time(m.duration)}</span></a>`).join('')}</div>` : empty('当前范围没有该英雄的逐局记录。'));

    const heroAllMatches = ((matchesData?.matches) || []).filter(x => (x.heroes || []).includes(key));
    const grainLabel = (date, grain) => {
      if (!date) return '日期未记录';
      const [y, mo, da] = String(date).split('-').map(Number);
      if (!y) return '日期未记录';
      if (grain === 'year') return `${y} 年`;
      if (grain === 'month') return `${y}-${String(mo || 1).padStart(2, '0')}`;
      const dt = new Date(y, (mo || 1) - 1, da || 1);
      dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
      return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')} 周`;
    };
    const grains = [['week', '周'], ['month', '月'], ['year', '年']];
    const timeData = grains.map(([grain, short]) => {
      const groups = new Map();
      for (const m of heroAllMatches) {
        const k = grainLabel(m.date, grain);
        const g = groups.get(k) || { n: 0, w: 0, d: 0 };
        g.n++;
        if (m.result === 'win' || m.result === 'loss') { g.d++; if (m.result === 'win') g.w++; }
        groups.set(k, g);
      }
      const ordered = [...groups].sort((a, b) => b[0].localeCompare(a[0])).slice(0, 12);
      const maxN = Math.max(1, ...ordered.map(([, g]) => g.n));
      const total = ordered.reduce((acc, [, g]) => ({ n: acc.n + g.n, w: acc.w + g.w, d: acc.d + g.d }), { n: 0, w: 0, d: 0 });
      return { grain, short, ordered, maxN, total };
    });
    const timeTabs = `<div class="hz-time-tabs" role="group" aria-label="时间粒度">${timeData.map((t, i) => `<button type="button" data-hero-time-tab="${t.grain}" class="${i === 0 ? 'is-active' : ''}" aria-pressed="${i === 0}"><b>${t.short}</b><em>${fmt(t.ordered.length)} 段</em></button>`).join('')}</div>`;
    const timeGroups = timeData.map((t, i) => {
      const overall = t.total.d ? t.total.w / t.total.d * 100 : null;
      const summary = `<div class="hz-time-summary"><span><b>${fmt(t.ordered.length)}</b> 个时间段</span><span><b>${fmt(t.total.n)}</b> 局出场</span><span class="hz-time-summary-wr">整体胜率 <strong>${pct(overall)}</strong></span></div>`;
      const rows = t.ordered.map(([k, g]) => {
        const wr = g.d ? g.w / g.d * 100 : null;
        const lit = Math.max(1, Math.round(g.n / t.maxN * 10));
        const voxels = Array.from({ length: 10 }, (_, j) => `<i class="${j < lit ? 'is-on' : ''}"></i>`).join('');
        const undecided = g.n > g.d ? ` · ${fmt(g.n - g.d)} 场无胜负` : '';
        return `<article class="hz-card hz-time-row">
          <div class="hz-time-label"><b>${text(k)}</b><small>${fmt(g.n)} 局 · ${fmt(g.w)} 胜 ${fmt(g.d - g.w)} 负${undecided}</small></div>
          <div class="hz-time-volume"><div class="hz-voxels">${voxels}</div><small>出场量 / ${fmt(g.n)} 局</small></div>
          <div class="hz-time-rate"><div class="hz-time-track"><i style="width:${wr == null ? 0 : Math.max(0, Math.min(100, wr))}%"></i><em></em></div><small>0 · 50 · 100% 胜率</small></div>
          <strong class="hz-time-score ${wr == null ? 'is-none' : ''}">${pct(wr)}</strong>
        </article>`;
      }).join('');
      return `<div class="hero-time-group" data-hero-time-group="${t.grain}" ${i === 0 ? '' : 'hidden'}>${summary}<div class="hz-time-list">${rows || empty('该时间粒度下暂无对局。')}</div></div>`;
    }).join('');
    const timePanel = block('时间表现', '按对局日期分组，胜率只以有胜负的局为分母；轨道上的竖线为 50% 基准。', `${timeTabs}${timeGroups}`);

    const matchupRows = ((matchup?.payload?.heroes) || (matchup?.heroes) || []).filter(x => x.ownHero === key).slice(0, 8);
    const matchupPanel = block('同位置对位', '同分路逐对交手 · 经济差为我方减对方', matchupRows.length ? `<div class="hz-matchup-grid">${matchupRows.map(x => `<article class="hz-card hz-matchup-card"><div class="hz-versus">${portrait(key)}<span>VS</span>${portrait(x.enemyHero)}</div><b class="hz-matchup-name">${text(x.enemyHero)}</b><small>${fmt(x.n)} 次交手 · 领先率 ${pct(x.aheadRate)}</small><div class="hz-matchup-metrics"><span>胜率<b>${pct(x.winRate)}</b></span><span>经济差<b class="${deltaCls(x.avgGoldDiff)}">${diff(x.avgGoldDiff)}</b></span></div>${bar(x.winRate)}</article>`).join('')}</div>` : empty('当前范围没有该英雄的同位置交手记录。'));

    const equipItems = ((equipMatrix?.payload?.items) || (equipMatrix?.items) || []).slice(0, 12);
    const equipPanel = block('常见出装', '终局六格携带率 · 按该英雄的出场样本统计', equipItems.length ? `<div class="hz-equip-grid">${equipItems.map(x => `<article class="hz-card hz-equip-card">${equipImg(x.label)}<div class="hz-equip-info"><b>${text(x.label)}</b>${voxels(x.pct)}</div><strong>${pct(x.pct)}</strong></article>`).join('')}</div>` : empty('当前范围没有该英雄的终局装备记录。'));

    const buildRows = (summary?.playerBuilds || []).map(p => `<article class="hz-card hz-build-card"><div class="hz-build-head"><span class="hz-avatar">${initial(p.name)}</span><div><b>${text(p.name)}</b><small>${fmt(p.games)} 局 · 胜率 ${pct(p.winRate)} · KDA ${fmt(p.kda, 2)}</small></div><strong>${fmt(p.gold)}<small>金</small></strong></div><div class="hz-slots">${(p.equips || []).map(e => `<div class="hz-slot">${equipImg(e.name)}<small>${pct(p.games ? e.count / p.games * 100 : null)}</small></div>`).join('') || '<span class="hz-build-none">暂无出装样本</span>'}</div><div class="hz-build-sub">${(p.first || []).length ? `<span>首件 ${(p.first || []).map(x => text(x.name)).join(' / ')}</span>` : ''}${(p.summoner || []).length ? `<span>召唤师技能 ${(p.summoner || []).map(x => text(x.name)).join(' / ')}</span>` : ''}</div></article>`).join('');
    const playerBuildPanel = block('选手出装', '每位选手使用该英雄时的终局出装与携带率', buildRows ? `<div class="hz-build-list">${buildRows}</div>` : empty('当前范围暂无逐人出装样本。'));

    const equipImpactRows = ((equipImpact?.payload?.rows) || (equipImpact?.rows) || []).slice(0, 8);
    const metricLabels = equipImpact?.payload?.metricLabels || equipImpact?.metricLabels || {};
    const impactScale = Math.max(1, ...equipImpactRows.flatMap(r => Object.values(r.deltas || {}).map(v => Math.abs(v?.delta || 0))));
    const equipImpactPanel = block('出装与表现', '携带与未携带两组的指标中位数差', equipImpactRows.length ? `<div class="hz-impact-grid">${equipImpactRows.map(r => `<article class="hz-card hz-impact-card"><div class="hz-card-top"><span class="hz-equip-mini">${equipImg(r.label)}</span><b>${text(r.label)}</b><small>${fmt(r.withN)} / ${fmt(r.withoutN)} 局</small></div>${Object.entries(r.deltas || {}).slice(0, 3).map(([k, v]) => `<div class="hz-impact-metric"><span>${text(metricLabels[k] || k)}</span>${bipole(v?.delta, impactScale)}<b class="${deltaCls(v?.delta)}">${diff(v?.delta)}</b></div>`).join('')}</article>`).join('')}</div>` : empty('当前范围没有可用的装备表现对照。'));

    const usageViz = (items) => (items || []).length ? `<div class="hz-rank-list">${items.map((x, i) => `<div class="hz-rank-row"><span class="hz-rank-no">${String(i + 1).padStart(2, '0')}</span><span class="hz-avatar small">${initial(x.name)}</span><div class="hz-rank-name"><b>${text(x.name)}</b><small>${fmt(x.games)} 局 · KDA ${fmt(x.kda, 2)} · ${fmt(x.gpm)} 金/分</small></div>${bar(x.winRate)}<strong>${pct(x.winRate)}</strong></div>`).join('')}</div>` : empty('当前范围暂无记录。');
    const playerPanel = block('选手使用榜', '按本队选手的逐局记录聚合', usageViz(summary?.players));
    const teamPanel = block('战队使用', '按逐局记录的对手战队聚合', usageViz(summary?.teams));

    const leagueNames = { kda: 'KDA', gpm: '分均经济', dpm: '分均输出', participation: '参团率', gold: '终局经济', cs: '补刀' };
    const leagueCards = Object.entries(summary?.league || {}).map(([k, v]) => {
      const hv = v?.hero, av = v?.all;
      const max = Math.max(1, Math.abs(hv || 0), Math.abs(av || 0));
      const d = (typeof hv === 'number' && typeof av === 'number' && av) ? (hv - av) / Math.abs(av) * 100 : null;
      return `<article class="hz-card hz-league-card"><b>${text(leagueNames[k] || k)}</b><div class="hz-league-nums"><strong>${fmt(hv, 2)}</strong><span>该英雄</span><em>${fmt(av, 2)}</em><span>本队均值</span></div><div class="hz-dual"><div><i style="width:${Math.min(100, Math.abs(hv || 0) / max * 100)}%"></i></div><div><i class="is-muted" style="width:${Math.min(100, Math.abs(av || 0) / max * 100)}%"></i></div></div>${d == null ? '' : `<span class="hz-diff ${d >= 0 ? 'is-pos' : 'is-neg'}">${d > 0 ? '+' : ''}${fmt(d, 1)}%</span>`}</article>`;
    }).join('');
    const leaguePanel = block('本队均值对照', '该英雄出场样本与全部本队样本的指标均值，差值以全样本为基准', leagueCards ? `<div class="hz-league-grid">${leagueCards}</div>` : empty('当前范围暂无对照样本。'));

    const growth = (summary?.growth || []).filter(p => Number.isFinite(p.t) && Number.isFinite(p.value));
    let growthBody = empty('当前范围暂无可用的分钟级时间轴。');
    if (growth.length >= 2) {
      const xs = growth.map(p => p.t), ys = growth.map(p => p.value);
      const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys);
      const X = t => 50 + (t - xmin) / (xmax - xmin || 1) * 590;
      const Y = v => 180 - (v - ymin) / (ymax - ymin || 1) * 140;
      const path = growth.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.value).toFixed(1)}`).join(' ');
      const area = `${path} L${X(xmax).toFixed(1)},${Y(0).toFixed(1)} L${X(xmin).toFixed(1)},${Y(0).toFixed(1)} Z`;
      const peak = growth.reduce((a, b) => (b.value > a.value ? b : a), growth[0]);
      const grids = [0, .5, 1].map(t => {
        const y = 40 + t * 140, v = ymax - (ymax - ymin) * t;
        return `<line x1="50" y1="${y}" x2="640" y2="${y}" class="grid-line"/><text x="44" y="${y + 3}" text-anchor="end" class="axis-text">${fmt(v, 0)}</text>`;
      }).join('');
      growthBody = `<div class="hero-growth-chart"><svg viewBox="0 0 680 210" role="img" aria-label="该英雄出场对局的团队经济差曲线">${grids}<path d="${area}" class="area"/><line x1="50" y1="${Y(0).toFixed(1)}" x2="640" y2="${Y(0).toFixed(1)}" class="zero-line"/><path d="${path}" class="curve"/>${growth.map(p => `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(p.value).toFixed(1)}" r="3" class="depth-dot"><title>${fmt(p.t / 60, 1)} 分 · ${diff(p.value)} 金</title></circle>`).join('')}<circle cx="${X(peak.t).toFixed(1)}" cy="${Y(peak.value).toFixed(1)}" r="6" class="peak-dot"/><text x="${X(peak.t).toFixed(1)}" y="${(Y(peak.value) - 13).toFixed(1)}" text-anchor="middle" class="peak-label">${fmt(peak.value)}</text><text x="50" y="202" class="axis-text">${fmt(xmin / 60, 1)} 分</text><text x="640" y="202" text-anchor="end" class="axis-text">${fmt(xmax / 60, 1)} 分</text></svg><div class="hero-growth-foot">${fmt(summary?.curveGames || 0)} 场有时间轴 · 纵轴为本队减对手的经济差 · 峰值 ${fmt(peak.t / 60, 1)} 分 ${diff(peak.value)} 金</div></div>`;
    }
    const growthPanel = block('成长曲线', '该英雄出场对局的分钟级经济差走势', growthBody);

    const anchorLabels = ['各位置', '双人搭档', '三人组合', '常见出装', '选手出装', '出装表现', '选手使用', '战队使用', '均值对照', '成长曲线', '最近出场', '时间表现', '同位置对位'];
    const anchorNav = `<nav class="hero-anchor-nav" aria-label="模块快速导航">${anchorLabels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;

    return `<div class="page hero-detail-page">
      <header class="hero-masthead"><div class="page-intro"><div>
        <a class="hero-back" href="#heroes">← 返回英雄榜</a>
        <h1>${esc(key || '英雄详情')}</h1><p>${intro}</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>
        ${kpi}</header>
      ${anchorNav}<div class="hero-detail-grid">${lanePanel}${partnerPanel}${trioPanel}${equipPanel}${playerBuildPanel}${equipImpactPanel}${playerPanel}${teamPanel}${leaguePanel}${growthPanel}${matchPanel}${timePanel}${matchupPanel}</div></div>`;
  }
  /* ===== BP 板块 =====
     照 KPL 赛研 bp.html / team-bp.html / coach.html 的对象维度组织：
     BP 概览 = 全局条件画像 + 逐局名单；战队 BP / 教练档案 = 按对象下钻。
     三页共用 /api/v2/bp-board 的全量营地终局名单。营地不含禁选先后顺序，
     所以不做逐手预测与首抢收益，只做名单类统计（与 team-bp.html 的保守口径一致）。 */
  let bpState = null;
  const bpMeta = (board, name) => (board.heroMeta || {})[name] || {};
  const bpIcon = (board, name, cls = '') => {
    const m = bpMeta(board, name);
    return m.icon
      ? `<img class="bp-ico ${cls}" src="${esc(m.icon)}" alt="">`
      : `<span class="bp-ico bp-ico-ph ${cls}">${esc(String(name || '?').slice(0, 1))}</span>`;
  };
  const bpChip = (board, name, extra = '', cls = '') =>
    `<span class="bp-chip ${cls}">${bpIcon(board, name)}<b>${esc(name)}</b>${extra ? `<em>${extra}</em>` : ''}</span>`;
  const bpCount = (games, kind, side) => {
    const out = new Map();
    for (const g of games) {
      for (const e of ((g[kind] || {})[side] || [])) {
        const r = out.get(e.name) || { name: e.name, n: 0, wins: 0, decided: 0 };
        r.n++;
        if (g.result === 'win' || g.result === 'loss') {
          r.decided++;
          if ((side === 'own' && g.result === 'win') || (side === 'enemy' && g.result === 'loss')) r.wins++;
        }
        out.set(e.name, r);
      }
    }
    return [...out.values()].sort((a, b) => b.n - a.n || String(a.name).localeCompare(String(b.name)));
  };
  const bpRate = (w, d) => d ? w / d * 100 : null;
  const bpBar = (n, max) => `<div class="bp-bar"><i style="width:${Math.max(0, Math.min(100, max ? n / max * 100 : 0))}%"></i></div>`;
  const bpVox = (n, max) => `<div class="bp-vox">${Array.from({ length: 10 }, (_, i) => `<i class="${i < Math.max(1, Math.round(n / (max || 1) * 10)) ? 'is-on' : ''}"></i>`).join('')}</div>`;
  const bpRankRows = (board, list, max) => list.map((r, i) => `<div class="bp-rank-row">
      <span class="bp-rank-no">${String(i + 1).padStart(2, '0')}</span>${bpIcon(board, r.name, 'is-lg')}
      <div class="bp-rank-body"><b>${esc(r.name)}</b><small>${esc(bpMeta(board, r.name).lane || '位置未记录')} · ${fmt(r.n)} 次</small>${bpBar(r.n, max)}</div>
      <strong>${pct(bpRate(r.wins, r.decided))}</strong></div>`).join('');
  const bpCombos = (games, size, side = 'own') => {
    const out = new Map();
    for (const g of games) {
      const names = [...new Set(((g.picks || {})[side] || []).map(e => e.name))].sort();
      if (names.length < size) continue;
      const groups = size === 2
        ? names.flatMap((a, i) => names.slice(i + 1).map(b => [a, b]))
        : names.flatMap((a, i) => names.slice(i + 1).flatMap((b, j) => names.slice(i + j + 2).map(c => [a, b, c])));
      for (const heroes of groups) {
        const k = heroes.join(' + ');
        const r = out.get(k) || { heroes, n: 0, wins: 0, decided: 0 };
        r.n++;
        if (g.result === 'win' || g.result === 'loss') { r.decided++; if (g.result === 'win') r.wins++; }
        out.set(k, r);
      }
    }
    return [...out.values()].sort((a, b) => b.n - a.n
      || (bpRate(b.wins, b.decided) || 0) - (bpRate(a.wins, a.decided) || 0)
      || a.heroes.join(' + ').localeCompare(b.heroes.join(' + '), 'zh')).slice(0, 8);
  };
  const bpSide = (board, entries, bans, label, cls) => `<div class="bp-side ${cls}">
      <div class="bp-side-hd"><b>${esc(label)}</b><span>${fmt(entries.length)} 选用 · ${fmt(bans.length)} 禁用</span></div>
      <div class="bp-picks">${entries.map(e => `<div class="bp-pick">${bpIcon(board, e.name)}<b>${esc(e.name)}</b><small>${esc(e.lane || '')}</small></div>`).join('')}</div>
      <div class="bp-bans"><span>禁用</span>${bans.map(e => `<i title="${esc(e.name)}">${bpIcon(board, e.name)}</i>`).join('')}</div>
    </div>`;
  const bpGameCard = (board, g) => `<article class="bp-game">
      <div class="bp-game-hd"><b>${esc(g.day)} ${esc((g.start || '').split(' ')[1] || '')}</b><span>对阵 ${esc(g.opponent)}</span>
        <span>${esc(g.session)}</span><em class="bp-result ${g.result === 'win' ? 'is-win' : 'is-loss'}">${g.result === 'win' ? '胜利' : '失利'}</em>
        <small>${time(g.duration)} · 本队${g.side === 'blue' ? '蓝方' : '红方'}</small></div>
      <div class="bp-versus">${bpSide(board, g.picks.own, g.bans.own, '本队', 'is-own')}<span class="bp-vs">VS</span>${bpSide(board, g.picks.enemy, g.bans.enemy, g.opponent, 'is-enemy')}</div>
    </article>`;
  const bpSelect = (key, label, options, value) => `<label>${esc(label)}<select data-bp-filter="${key}">${options.map(([v, t]) => `<option value="${esc(v)}" ${v === value ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
  function bpFiltered(board, f) {
    let games = board.games.filter(g => (!f.opponent || g.opponent === f.opponent)
      && (!f.day || g.day === f.day) && (!f.side || g.side === f.side)
      && (!f.result || g.result === f.result)
      && (!f.hero || [...(g.picks.own || []), ...(g.picks.enemy || []), ...(g.bans.own || []), ...(g.bans.enemy || [])].some(e => e.name === f.hero)));
    if (f.range) games = games.slice(0, Number(f.range));
    return games;
  }
  function bpBoardHtml() {
    const { board, f } = bpState;
    const games = bpFiltered(board, f);
    const decided = games.filter(g => g.result === 'win' || g.result === 'loss');
    const wins = decided.filter(g => g.result === 'win').length;
    const wr = bpRate(wins, decided.length);
    const ownPicks = bpCount(games, 'picks', 'own'), enemyPicks = bpCount(games, 'picks', 'enemy');
    const ownBans = bpCount(games, 'bans', 'own'), enemyBans = bpCount(games, 'bans', 'enemy');
    const maxPick = Math.max(1, ...ownPicks.map(x => x.n));
    const heroes = [...new Set(board.games.flatMap(g =>
      [...(g.picks.own || []), ...(g.picks.enemy || []), ...(g.bans.own || []), ...(g.bans.enemy || [])].map(e => e.name)))].sort((a, b) => a.localeCompare(b, 'zh'));
    const opponents = [...new Set(board.games.map(g => g.opponent))].sort((a, b) => a.localeCompare(b, 'zh'));
    const days = [...new Set(board.games.map(g => g.day))].filter(Boolean).sort().reverse();

    const kpi = `<div class="hero-kpi">${[
      ['命中对局', fmt(games.length), '当前筛选范围'],
      ['本队胜率', pct(wr), `${fmt(wins)} 胜 / ${fmt(decided.length)} 局`],
      ['本队选用', fmt(ownPicks.length), '个不同英雄'],
      ['本队禁用', fmt(ownBans.length), '个不同英雄'],
      ['对手选用', fmt(enemyPicks.length), '个不同英雄'],
      ['对手禁用', fmt(enemyBans.length), '个不同英雄'],
      ['覆盖对手', fmt(new Set(games.map(g => g.opponent)).size), '支战队'],
    ].map(([label, val, note]) => `<div class="hero-kpi-cell"><span>${label}</span><strong>${val}</strong>${label === '本队胜率' ? `<div class="hero-kpi-track"><i style="width:${wr || 0}%"></i></div>` : ''}<p>${note}</p></div>`).join('')}</div>`;
    const brief = `<div class="hero-brief">当前条件命中 <b>${fmt(games.length)} 局</b>训练赛 · <b>${fmt(new Set(games.map(g => g.opponent)).size)} 支对手</b>：<b>${fmt(wins)} 胜 ${fmt(decided.length - wins)} 负</b>，胜率 <b>${pct(wr)}</b>。本队最爱禁用「<b>${esc(ownBans[0]?.name || '—')}</b>（${fmt(ownBans[0]?.n || 0)} 次）」、最爱选「<b>${esc(ownPicks[0]?.name || '—')}</b>（${fmt(ownPicks[0]?.n || 0)} 次）」；对手最常禁用「<b>${esc(enemyBans[0]?.name || '—')}</b>（${fmt(enemyBans[0]?.n || 0)} 次）」。换对手或训练日，结论实时重算。</div>`;
    const filterBar = `<div class="hero-filterbar bp-filterbar">
      ${bpSelect('opponent', '对手', [['', '全部对手'], ...opponents.map(x => [x, x])], f.opponent)}
      ${bpSelect('day', '训练日', [['', '全部训练日'], ...days.map(x => [x, x])], f.day)}
      ${bpSelect('side', '阵营', [['', '全部阵营'], ['blue', '本队蓝方'], ['red', '本队红方']], f.side)}
      ${bpSelect('result', '赛果', [['', '全部赛果'], ['win', '胜利'], ['loss', '失利']], f.result)}
      ${bpSelect('hero', '英雄', [['', '全部英雄'], ...heroes.map(x => [x, x])], f.hero)}
      ${bpSelect('range', '范围', [['', '全部对局'], ['10', '最近 10 局'], ['5', '最近 5 局']], f.range)}
      <span class="bp-filter-count">命中 ${fmt(games.length)} 局</span></div>`;

    const imageRow = (label, list, cls) => `<div class="bp-image-row"><b>${esc(label)}</b><div class="bp-chips">${list.slice(0, 8).map(r => bpChip(board, r.name, `${fmt(r.n)} 次`, cls)).join('') || '<span class="bp-none">当前条件暂无记录</span>'}</div></div>`;
    const imagePanel = block('条件 BP 画像', '按当前筛选实时统计：谁被禁用、谁上场。换对手或训练日，结论即时重算。',
      `<div class="bp-image">${imageRow('本队禁用', ownBans, 'is-ban')}${imageRow('对手禁用 · 针对', enemyBans, 'is-against')}${imageRow('本队选用', ownPicks, 'is-pick')}${imageRow('对手选用', enemyPicks, 'is-enemy')}</div>`);
    const picksPanel = block('本队选用榜', '按选用次数排序，右侧为这些对局里的本队胜率。',
      ownPicks.length ? `<div class="bp-rank-list">${bpRankRows(board, ownPicks.slice(0, 10), maxPick)}</div>` : empty('当前条件暂无选用记录。'));
    const banCol = (label, list, cls) => `<div class="bp-ban-col ${cls}"><b>${esc(label)}</b>${list.slice(0, 8).map(r => `<div class="bp-ban-row">${bpIcon(board, r.name)}<span>${esc(r.name)}</span>${bpBar(r.n, Math.max(1, list[0]?.n || 1))}<em>${fmt(r.n)}</em></div>`).join('') || empty('暂无记录。')}</div>`;
    const banPanel = block('禁用资源', '本队主动禁用与对手针对禁用，按次数对照。',
      `<div class="bp-dual-list">${banCol('本队禁用', ownBans, 'is-own')}${banCol('对手禁用 / 针对', enemyBans, 'is-enemy')}</div>`);

    const lensName = f.lens || ownPicks[0]?.name || enemyPicks[0]?.name || '';
    const lensGames = games.filter(g => [...(g.picks.own || []), ...(g.picks.enemy || []), ...(g.bans.own || []), ...(g.bans.enemy || [])].some(e => e.name === lensName));
    const lensPanel = block('英雄透镜', '反查某个英雄出现在哪些对局、由谁选用或禁用。',
      `<div class="bp-lens">${bpSelect('lens', '英雄', [['', '默认英雄'], ...heroes.map(x => [x, x])], lensName)}<span>共 ${fmt(lensGames.length)} 局出现</span></div>
       <div class="bp-lens-grid">${lensGames.slice(0, 8).map(g => {
        const state = (g.picks.own || []).some(e => e.name === lensName) ? '本队选用'
          : (g.picks.enemy || []).some(e => e.name === lensName) ? '对手选用'
          : (g.bans.own || []).some(e => e.name === lensName) ? '本队禁用'
          : (g.bans.enemy || []).some(e => e.name === lensName) ? '对手禁用' : '名单出现';
        return `<div class="bp-lens-row"><b>${esc(g.day)}</b><span>对阵 ${esc(g.opponent)}</span><em>${state}</em><span class="bp-result ${g.result === 'win' ? 'is-win' : 'is-loss'}">${g.result === 'win' ? '胜利' : '失利'}</span></div>`;
      }).join('') || empty('当前条件没有该英雄的记录。')}</div>`);

    const combos2 = bpCombos(games, 2), combos3 = bpCombos(games, 3);
    const comboCol = (label, list) => `<div><b>${esc(label)}</b>${list.map(c => `<div class="bp-combo-row"><div class="bp-combo-heroes">${c.heroes.map(h => bpIcon(board, h)).join('')}</div><span>${esc(c.heroes.join(' + '))}</span><em>${fmt(c.n)} 局</em><strong>${pct(bpRate(c.wins, c.decided))}</strong></div>`).join('') || empty('当前条件暂无阵容记录。')}</div>`;
    const comboPanel = block('阵容组合', '同队同局共现 · 组合胜率以有胜负的局为分母。',
      `<div class="bp-combo-grid">${comboCol('双人组合', combos2)}${comboCol('三人组合', combos3)}</div>`);

    const matrixCells = [['blue', 'win', '本队蓝方 · 胜'], ['blue', 'loss', '本队蓝方 · 负'], ['red', 'win', '本队红方 · 胜'], ['red', 'loss', '本队红方 · 负']];
    const maxCell = Math.max(1, ...matrixCells.map(([s, r]) => games.filter(g => g.side === s && g.result === r).length));
    const matrixPanel = block('阵营与赛果', '按本队阵营 × 赛果交叉，方块数表示该格的对局量。',
      `<div class="bp-matrix">${matrixCells.map(([s, r, label]) => {
        const n = games.filter(g => g.side === s && g.result === r).length;
        return `<div class="bp-matrix-cell"><b>${label}</b><strong>${fmt(n)}</strong>${bpVox(n, maxCell)}<small>占有胜负局 ${pct(decided.length ? n / decided.length * 100 : null)}</small></div>`;
      }).join('')}</div>`);

    const gamePanel = block('逐局 BP 名单', `共 ${fmt(games.length)} 局 · 展示最近 ${fmt(Math.min(8, games.length))} 局的双方终局阵容与禁用。`,
      `<div class="bp-game-list">${games.slice(0, 8).map(g => bpGameCard(board, g)).join('') || empty('当前条件没有对局。')}</div>`);

    const dayMap = new Map();
    for (const g of games) {
      const x = dayMap.get(g.day) || { n: 0, w: 0, d: 0 };
      x.n++; if (g.result === 'win' || g.result === 'loss') { x.d++; if (g.result === 'win') x.w++; }
      dayMap.set(g.day, x);
    }
    const maxDay = Math.max(1, ...[...dayMap.values()].map(x => x.n));
    const dayPanel = block('训练日分布', '按训练日聚合局数与本队胜率。',
      dayMap.size ? `<div class="bp-day-list">${[...dayMap].sort((a, b) => b[0].localeCompare(a[0])).map(([d, x]) => `<div class="bp-day-row"><b>${esc(d)}</b>${bpVox(x.n, maxDay)}<span>${fmt(x.n)} 局</span><div class="bp-day-track"><i style="width:${bpRate(x.w, x.d) || 0}%"></i></div><strong>${pct(bpRate(x.w, x.d))}</strong></div>`).join('')}</div>` : empty('当前条件没有训练日记录。'));

    const panels = [imagePanel, picksPanel, banPanel, lensPanel, comboPanel, matrixPanel, gamePanel, dayPanel];
    const anchorLabels = ['条件画像', '选用榜', '禁用资源', '英雄透镜', '阵容组合', '阵营赛果', '逐局名单', '训练日'];
    const anchorNav = `<nav class="hero-anchor-nav" aria-label="模块快速导航">${anchorLabels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;
    return `<header class="hero-masthead"><div class="page-intro"><div>
        <h1>BP 概览</h1><p>选用、禁用、针对 ban 与逐局名单，按训练赛对象维度交叉查看。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>${kpi}</header>
      ${brief}${filterBar}${anchorNav}<div class="hero-detail-grid">${panels.join('')}</div>`;
  }
  function bpBoard(value) {
    bpState = { board: value, f: { opponent: '', day: '', side: '', result: '', hero: '', range: '', lens: '' } };
    return `<div class="page bp-page hero-detail-page">${bpBoardHtml()}</div>`;
  }

  let bpTeamState = null, bpCoachState = null;
  function bpSubjectData(state) {
    const board = state.board;
    const team = board.teams.find(t => t.id === state.key) || board.teams[0] || { id: '', name: '对手战队' };
    return { board, team, games: board.games.filter(g => g.teamId === team.id) };
  }
  function bpSubjectName(state, team) {
    if (state.mode !== 'coach') return team.name;
    const coach = (state.roster?.teams || []).find(t => t.id === team.id)?.coach || team.coach;
    return coach || team.name;
  }
  function bpSubjectBlocks(board, games, name) {
    const foePicks = bpCount(games, 'picks', 'enemy'), foeBans = bpCount(games, 'bans', 'enemy');
    const ownPicks = bpCount(games, 'picks', 'own'), ownBans = bpCount(games, 'bans', 'own');
    const decided = games.filter(g => g.result === 'win' || g.result === 'loss');
    const wins = decided.filter(g => g.result === 'win').length;
    const wr = bpRate(wins, decided.length);
    const total = foePicks.reduce((s, x) => s + x.n, 0);
    const hhi = foePicks.reduce((s, x) => s + Math.pow(x.n / (total || 1), 2), 0);
    const effective = hhi ? 1 / hhi : null;
    const topShare = total ? (foePicks[0]?.n || 0) / total * 100 : null;
    const kpi = `<div class="hero-kpi">${[
      ['交手局数', fmt(games.length), '与对手交手'],
      ['本队胜率', pct(wr), `${fmt(wins)} 胜 / ${fmt(decided.length)} 局`],
      ['对手选用', fmt(foePicks.length), '个不同英雄'],
      ['英雄池深度', fmt(effective, 1), '1 / HHI'],
      ['对手禁用', fmt(foeBans.length), '个不同英雄'],
      ['最高选用占比', pct(topShare), foePicks[0]?.name || '—'],
      ['名单覆盖', fmt(games.length), '含双方终局名单'],
    ].map(([label, val, note]) => `<div class="hero-kpi-cell"><span>${label}</span><strong>${val}</strong>${label === '本队胜率' ? `<div class="hero-kpi-track"><i style="width:${wr || 0}%"></i></div>` : ''}<p>${note}</p></div>`).join('')}</div>`;
    const brief = `<div class="hero-brief"><b>${esc(name)}</b> 共交手 <b>${fmt(games.length)} 局</b>，本队 <b>${fmt(wins)} 胜 ${fmt(decided.length - wins)} 负</b>（胜率 <b>${pct(wr)}</b>）。对手最常选用「<b>${esc(foePicks[0]?.name || '—')}</b>（${fmt(foePicks[0]?.n || 0)} 次）」、最常禁用「<b>${esc(foeBans[0]?.name || '—')}</b>（${fmt(foeBans[0]?.n || 0)} 次）」；本队针对禁用最多的是「<b>${esc(ownBans[0]?.name || '—')}</b>」。</div>`;
    const statCard = (label, val, note) => `<div class="bp-stat"><span>${esc(label)}</span><strong>${val}</strong><small>${esc(note)}</small></div>`;
    const stylePanel = block('风格 · 选择与禁用结构', '偏好不等于擅长，这里只描述对手的选人覆盖面。',
      `<div class="bp-stat-grid">${statCard('对手选用英雄', fmt(foePicks.length), '个不同英雄')}${statCard('英雄池深度', fmt(effective, 1), '1 / HHI · 越高越分散')}${statCard('最高选用占比', pct(topShare), foePicks[0]?.name || '—')}${statCard('对手禁用英雄', fmt(foeBans.length), `${fmt(foeBans.reduce((s, x) => s + x.n, 0))} 次禁用`)}</div>`);
    const effectPanel = block('效果 · 交手与赛果', '胜率是赛果描述，不是 BP 优势。',
      `<div class="bp-stat-grid">${statCard('交手局数', fmt(games.length), '与对手交手')}${statCard('本队胜率', pct(wr), `${fmt(wins)} 胜 / ${fmt(decided.length)} 局`)}${statCard('对手胜率', pct(bpRate(decided.length - wins, decided.length)), `${fmt(decided.length - wins)} 胜`)}${statCard('BP 名单覆盖', fmt(games.length), '局含双方终局名单')}</div>`);
    const counts = { p: 0, b: 0, op: 0, ob: 0 };
    for (const g of games) {
      counts.p += (g.picks.enemy || []).length; counts.b += (g.bans.enemy || []).length;
      counts.op += (g.picks.own || []).length; counts.ob += (g.bans.own || []).length;
    }
    const stateTotal = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    const states = [['对手选用', 'p', 'is-p'], ['对手禁用', 'b', 'is-b'], ['本队选用', 'op', 'is-op'], ['本队禁用', 'ob', 'is-ob']];
    const statePanel = block('英雄竞争状态', '四类名单在这批对局里的手数占比。',
      `<div class="bp-statebar">${states.map(([, k, c]) => `<i class="${c}" style="width:${counts[k] / stateTotal * 100}%"></i>`).join('')}</div>
       <div class="bp-state-grid">${states.map(([label, k, c]) => `<div class="bp-state-card ${c}"><b>${label}</b><strong>${fmt(counts[k])}</strong><small>${pct(counts[k] / stateTotal * 100)}</small></div>`).join('')}</div>`);
    const maxFoe = Math.max(1, ...foePicks.map(x => x.n));
    const rankPanel = block('对手选用榜', '按选用次数排序，右侧为对手在这些对局里的胜率。',
      foePicks.length ? `<div class="bp-rank-list">${bpRankRows(board, foePicks.slice(0, 10), maxFoe)}</div>` : empty('当前对象暂无选用记录。'));
    const allFoePicks = bpCount(board.games, 'picks', 'enemy');
    const allTotal = allFoePicks.reduce((s, x) => s + x.n, 0) || 1;
    const baseRate = new Map(allFoePicks.map(x => [x.name, x.n / allTotal]));
    const subTotal = foePicks.reduce((s, x) => s + x.n, 0) || 1;
    const liftRows = foePicks.slice(0, 8).map(x => {
      const own = x.n / subTotal, base = baseRate.get(x.name) || 0;
      return { name: x.name, own, base, lift: base ? own / base : null };
    });
    const liftMax = Math.max(0.01, ...liftRows.flatMap(r => [r.own, r.base]));
    const benchmarkPanel = block('全体基准对照', '把该对象的选用占比与全部训练赛对手的基准比较；Lift > 1 表示更偏好。',
      liftRows.length ? `<div class="bp-lift-list">${liftRows.map(r => `<div class="bp-lift-row">${bpIcon(board, r.name)}<b>${esc(r.name)}</b>
        <div class="bp-lift-bars"><span>该对象 <i style="width:${r.own / liftMax * 100}%"></i></span><span>全体基准 <i class="is-muted" style="width:${r.base / liftMax * 100}%"></i></span></div>
        <strong>${r.lift == null ? '—' : `${fmt(r.lift, 2)}×`}</strong></div>`).join('')}</div>` : empty('当前对象暂无选用样本。'));
    const banCol = (label, list, cls) => `<div class="bp-ban-col ${cls}"><b>${esc(label)}</b>${list.slice(0, 8).map(r => `<div class="bp-ban-row">${bpIcon(board, r.name)}<span>${esc(r.name)}</span>${bpBar(r.n, Math.max(1, list[0]?.n || 1))}<em>${fmt(r.n)}</em></div>`).join('') || empty('暂无记录。')}</div>`;
    const banPanel = block('禁用对照', '本队针对禁用与对手主动禁用。',
      `<div class="bp-dual-list">${banCol('本队禁用', ownBans, 'is-own')}${banCol('对手禁用', foeBans, 'is-enemy')}</div>`);
    const comboCol = (label, list) => `<div><b>${esc(label)}</b>${list.map(c => `<div class="bp-combo-row"><div class="bp-combo-heroes">${c.heroes.map(h => bpIcon(board, h)).join('')}</div><span>${esc(c.heroes.join(' + '))}</span><em>${fmt(c.n)} 局</em><strong>${pct(bpRate(c.wins, c.decided))}</strong></div>`).join('') || empty('当前条件暂无阵容记录。')}</div>`;
    const comboPanel = block('对手阵容组合', '同队同局共现 · 胜率为对手在这些局的胜率。',
      `<div class="bp-combo-grid">${comboCol('双人组合', bpCombos(games, 2, 'enemy'))}${comboCol('三人组合', bpCombos(games, 3, 'enemy'))}</div>`);
    const evidencePanel = block('逐局 BP 名单', `共 ${fmt(games.length)} 局 · 双方终局阵容与禁用，按时间倒序。`,
      `<div class="bp-game-list">${games.slice(0, 8).map(g => bpGameCard(board, g)).join('') || empty('当前对象暂无对局。')}</div>`);
    const labels = ['风格', '效果', '竞争状态', '选用榜', '基准对照', '禁用对照', '阵容组合', '逐局名单'];
    const anchorNav = `<nav class="hero-anchor-nav" aria-label="模块快速导航">${labels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;
    return { kpi, brief, panels: [stylePanel, effectPanel, statePanel, rankPanel, benchmarkPanel, banPanel, comboPanel, evidencePanel], anchorNav };
  }
  function bpSubjectHtml() {
    const { board, team, games } = bpSubjectData(bpTeamState);
    const b = bpSubjectBlocks(board, games, team.name);
    const choices = board.teams.map(t => `<option value="${esc(t.id)}" ${t.id === team.id ? 'selected' : ''}>${esc(t.name)} · ${fmt(t.matches)} 局</option>`).join('');
    return `<header class="hero-masthead"><div class="page-intro"><div>
        <h1>${esc(team.name)}</h1><p>按对手战队查看选用、禁用与交手结果；营地终局名单不推断禁选先后顺序。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>${b.kpi}</header>
      ${b.brief}<div class="hero-filterbar bp-filterbar"><label>对手战队<select data-bp-team>${choices}</select></label><span class="bp-filter-count">${fmt(games.length)} 局交手</span></div>
      ${b.anchorNav}<div class="hero-detail-grid">${b.panels.join('')}</div>`;
  }
  function teamBp(value) {
    bpTeamState = { mode: 'team', board: value, key: value.teams[0]?.id || '' };
    return `<div class="page bp-page hero-detail-page" data-bp-subject="team">${bpSubjectHtml()}</div>`;
  }
  function bpCoachHtml() {
    const state = bpCoachState;
    const { board, team, games } = bpSubjectData(state);
    const name = bpSubjectName(state, team);
    const b = bpSubjectBlocks(board, games, name);
    const rosterTeams = state.roster?.teams || board.teams;
    const choices = board.teams.map(t => {
      const coach = rosterTeams.find(x => x.id === t.id)?.coach || t.coach || t.name;
      return `<option value="${esc(t.id)}" ${t.id === team.id ? 'selected' : ''}>${esc(coach)} · ${esc(t.name)}</option>`;
    }).join('');
    const rosterForm = form('coach',
      select('战队', 'teamId', '<option value="">本队</option>' + board.teams.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join(''))
        + field('教练姓名', 'name', state.roster?.own?.coach || ''), '保存教练');
    const days = [...new Set(games.map(g => g.day))].filter(Boolean).sort();
    const rosterNames = (rosterTeams.find(t => t.id === team.id)?.players || []).slice(0, 6);
    const rivalRows = board.teams.map(t => {
      const gs = board.games.filter(g => g.teamId === t.id);
      const d = gs.filter(g => g.result === 'win' || g.result === 'loss');
      const w = d.filter(g => g.result === 'win').length;
      const picks = bpCount(gs, 'picks', 'enemy');
      return { name: rosterTeams.find(x => x.id === t.id)?.coach || t.coach || t.name,
               team: t.name, games: gs.length, wr: bpRate(w, d.length), top: picks.slice(0, 3).map(x => x.name) };
    }).sort((a, c) => c.games - a.games || (c.wr || 0) - (a.wr || 0));
    const maxRival = Math.max(1, ...rivalRows.map(x => x.games));
    const comparePanel = block('对手教练对照', '按交手局数排列，条形为局数，右侧为本队对这些对手的胜率。',
      `<div class="bp-rival-list">${rivalRows.slice(0, 12).map(r => `<div class="bp-rival-row"><b>${esc(r.name)}</b><small>${esc(r.team)} · ${esc(r.top.join(' / ') || '—')}</small>${bpBar(r.games, maxRival)}<span>${fmt(r.games)} 局</span><strong>${pct(r.wr)}</strong></div>`).join('')}</div>`);
    const overviewPanel = block('执教记录', '教练信息随战队档案录入；下方可以直接补录或修改。',
      `<div class="bp-stat-grid">${[['交手局数', fmt(games.length), '与对手交手'], ['训练日', fmt(days.length), days.join(' / ') || '—'],
        ['本队胜率', pct(bpRate(games.filter(g => g.result === 'win').length, games.filter(g => g.result === 'win' || g.result === 'loss').length)), `${fmt(games.filter(g => g.result === 'win').length)} 胜`],
        ['对手阵容', fmt(rosterNames.length), '名已识别选手']].map(([l, v, n]) => `<div class="bp-stat"><span>${esc(l)}</span><strong>${v}</strong><small>${esc(n)}</small></div>`).join('')}</div>
       <div class="bp-roster">${rosterNames.map(p => `<span>${esc(typeof p === 'string' ? p : p.name)}</span>`).join('') || ''}</div>${rosterForm}`);
    const tabs = [['overview', '概览'], ['style', 'BP 风格'], ['compare', '对手教练对照'], ['evidence', '逐局证据']];
    return `<header class="hero-masthead"><div class="page-intro"><div>
        <h1>${esc(name)}</h1><p>看这位对手教练带队的胜负与 BP 习惯：常用英雄、禁用资源与逐局证据。</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>${b.kpi}</header>
      ${b.brief}<div class="hero-filterbar bp-filterbar"><label>对手教练<select data-bp-coach>${choices}</select></label><span class="bp-filter-count">${fmt(games.length)} 局执教记录</span></div>
      <nav class="bp-tabs" aria-label="教练档案页内导航">${tabs.map(([id, label], i) => `<button type="button" data-bp-tab="${id}" class="${i === 0 ? 'is-active' : ''}" aria-pressed="${i === 0}">${esc(label)}</button>`).join('')}</nav>
      <div class="bp-tab-panels">
        <div data-bp-tab-panel="overview">${overviewPanel}</div>
        <div data-bp-tab-panel="style" hidden>${b.panels.slice(0, 7).join('')}</div>
        <div data-bp-tab-panel="compare" hidden>${comparePanel}</div>
        <div data-bp-tab-panel="evidence" hidden>${b.panels[7]}</div>
      </div>`;
  }
  function combos(value) {
    const show=(data,title)=>block(title,'协同加成是与单英雄基准的差值；小样本仅供观察。',`<div class="combo-grid">${capture(data.own.combos,9).map(c=>`<article class="combo-card"><div>${c.heroes.map(hero=>portrait(hero)).join('')}</div><h3>${text(c.heroes.join(' + '))}</h3><p>${fmt(c.games)} 局 · ${c.small?'样本较少':'达到样本阈值'}</p><div class="combo-values"><span>组合胜率 <b>${pct(c.winRate)}</b></span><span>基准 <b>${pct(c.expected)}</b></span></div></article>`).join('')||empty('当前没有可用组合。')}</div>`+multiTable(['组合','局数','胜率','基准','加成','样本'],capture(data.own.combos,40).map(c=>[text(c.heroes.join(' + ')),fmt(c.games),pct(c.winRate),pct(c.expected),`${diff(c.synergy)} pp`,c.small?'较少':'达到阈值'])));
    return withPage('英雄组合','观察本队双人、三人组合与协同加成。',show(value.pairs,'双人组合')+show(value.trios,'三人组合'));
  }
  function economy(value) {
    const a=value.advantage,t=value.turning;
    const buckets=a.buckets.map(b=>[text(b.bucket),fmt(b.n),`${fmt(b.wins)} 胜`,pct(b.winRate),b.ciLow==null?'—':`${pct(b.ciLow)} – ${pct(b.ciHigh)}`,b.enough?'达到 10 局':'仅供观察']);
    const largest=[...a.buckets].filter(b=>b.n).sort((x,y)=>y.n-x.n)[0];
    const observation=largest?`<div class="analysis-observation"><span>观察重点</span><p>10 分钟时处于<strong>${text(largest.bucket)}</strong>的对局最多，共 <strong>${fmt(largest.n)} 局</strong>，其中 ${fmt(largest.wins)} 局获胜（${pct(largest.winRate)}）。${largest.n<10?'该分组样本较少，请结合单局复盘。':'请结合其他对局特征一起判断。'}</p></div>`:'';
    const rows=t.rows.map(r=>[text(r.game),`${time(r.start)} – ${time(r.end)}`,`${r.ownAdvantage?'+':'−'}${fmt(Math.abs(r.delta))}`,text((r.candidates||[]).map(c=>`${c.type} ${time(c.t)}`).join('、')||'未匹配')]);
    const chart = `<div class="interval-chart" role="img" aria-label="各十分钟经济状态对应的胜率及 95% Wilson 区间，具体样本见下表"><div class="interval-axis"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>${a.buckets.map(b=>`<div class="interval-row"><span>${text(b.bucket)}</span><div class="interval-track">${b.n?`<i style="left:${b.ciLow}%;width:${b.ciHigh-b.ciLow}%"></i><b style="left:${b.winRate}%"></b>`:''}</div><strong>${b.n?pct(b.winRate):'—'}</strong><small>${b.n} 局</small></div>`).join('')}</div>`;
    return withPage('经济转折','将经济变化与附近事件放在一起观察。',gameAnchorBar()+stats([['关联回放',fmt(t.games),'营地与回放匹配'],['经济转折窗口',fmt(t.total),'阈值至少 1000 金'],['10 分钟有效局数',fmt(a.overall.n),'时长足够且有胜负'],['有效局胜率',pct(a.overall.winRate),'全部分桶合计']])+
      block('优势兑现路径',a.note,observation+chart+multiTable(['10 分钟状态','局数','胜场','胜率','95% Wilson 区间','样本'],buckets))+
      block('经济转折匹配',t.note,multiTable(['对局','近似时间窗口','本队经济差变化','附近候选事件'],rows)));
  }
  function effect(value, players) {
    const results = value.results || [];
    const metricOptions = '<option value="kda">KDA</option><option value="gpm">分均经济</option><option value="dpm">分均输出</option><option value="tpm">分均承伤</option><option value="participation">参团率</option>';
    const boundPlayers = players.players.filter((p) => p.camp_user_id);
    const fields = field('训练目标','goal','','required placeholder="如：提升前 10 分钟经济差"')+
      field('训练方法','intervention','','placeholder="如：固定开局换线演练"')+
      field('开始日期','startDate',localDate(),'type="date" required')+
      field('结束日期','endDate','','type="date"')+
      select('观察指标','metric',metricOptions)+
      field('目标值','target','','type="number" step="any" placeholder="可留空，留空只记录变化"')+
      select('适用选手（留空为全队）','playerIds','<option value="">全队</option>'+boundPlayers.map((p) => `<option value="${esc(p.camp_user_id)}">${text(p.name)}</option>`).join(''))+
      field('复盘备注','review','','placeholder="训练安排、对手、执行情况"');
    const resultCards = `<div class="effect-grid">${results.map((r) => {
      const e = r.effect || {};
      return `<article class="effect-card"><div><span>${text(r.start_date || '日期未知')}</span><small>${text(e.label || r.metric)}</small></div><h3>${text(r.goal)}</h3>${r.intervention ? `<p class="sx-effect-method">${text(r.intervention)}</p>` : ''}${e.available ? `<div class="effect-values"><span>干预前<strong>${fmt(e.preMean,2)}</strong><small>${fmt(e.nPre)} 人次</small></span><i>→</i><span>干预后<strong>${fmt(e.postMean,2)}</strong><small>${fmt(e.nPost)} 人次</small></span><span>效应量 d<strong>${fmt(e.effectSize,2)}</strong><small>描述性对比</small></span></div>` : `<p>${text(e.reason || '样本不足')}</p>`}</article>`;
    }).join('') || empty('还没有训练干预记录。')}</div>`;
    const usable = results.filter((r) => (r.effect || {}).available);
    const meanD = usable.length ? usable.reduce((s, r) => s + (r.effect.effectSize || 0), 0) / usable.length : null;
    const emptyState = `<div class="sx-empty sx-effect-empty">
      <span class="sx-empty-mark">◎</span>
      <h3>还没有训练干预</h3>
      <p>登记一次训练目标，系统会把干预前后各至少 5 条本队营地记录放在一起比较。</p>
      <ol class="sx-effect-steps"><li><b>1</b><span>写下训练目标与观察指标</span></li><li><b>2</b><span>正常打训练赛，保持同一数据口径</span></li><li><b>3</b><span>回来看干预前后的均值与效应量</span></li></ol>
      <button type="button" class="control" data-sx-jump="effect-form">登记第一条 ↓</button>
    </div>`;
    const resultsBlock = block('干预记录','仅统计本队；每侧至少 5 条有效人次，才计算 Cohen’s d。',results.length?resultCards:emptyState);
    const playerHint = boundPlayers.length ? '' : '<p class="sx-form-note">本队名单还没有绑定营地 ID，当前只能按全队对比；绑定后可按选手查看。</p>';
    const formBlock = block('新增训练干预','训练目标与观察指标为必填；目标值可留空。',form('training',fields,'添加训练')+playerHint,'','data-sx-anchor="effect-form"');
    return withPage('训练效果',`记录训练干预，对照干预前后指标 · 已登记 ${fmt(results.length)} 条，其中 ${fmt(usable.length)} 条可以对比。`,
      lede([['干预记录',`${fmt(results.length)} 条`,'训练目标'],['可对比',`${fmt(usable.length)} 条`,'两侧样本 ≥ 5 人次'],['平均效应量',meanD==null?'—':fmt(meanD,2),'Cohen’s d'],['最近一条',text(results[0]?.start_date),text(results[0]?.goal||'')]])
      +`<div class="scope-note"><span>口径</span> 只有来源包含完整年份的营地记录才参与前后对比；缺少年份不会自行补全。比较是描述性观察，不代表因果。</div>`
      +`<div class="sx-effect-layout">${resultsBlock}${formBlock}</div>`,false,
      results.length ? '<a class="control sx-head-cta" href="#effect" data-sx-jump="effect-form">新增训练</a>' : '',false,true);
  }
  function pairComparison(kind, value) {
    const items = kind === 'team' ? value.teams : kind === 'player' ? value.players.own : value.heroes.own;
    const key = kind === 'team' ? 'id' : kind === 'player' ? 'id' : 'hero';
    const label = item => kind === 'team' ? item.displayName : kind === 'player' ? item.name : item.hero;
    const metrics = kind === 'team' ? [['交手局数','matches'],['分均经济','gpm'],['分均输出','dpm'],['分均承伤','dtpm'],['KDA','kda']]
      : [['场次','games'],['胜率','winRate'],['KDA','kda'],['分均经济','gpm'],['分均输出','dpm'],['参团率','participation']];
    const raw=items.map(item=>({key:kind==='hero'?`${item.hero}|${item.lane||''}`:item[key],label:kind==='hero'?`${label(item)} · ${item.lane||'位置未知'}`:label(item),...(kind==='team'?{...item.metrics,matches:item.matches}:item)}));
    const titles={team:'战队对比',player:'选手对比',hero:'英雄对比'};
    const note=kind==='team'?'对手侧营地结算汇总，战队身份由阵容聚类；不同对手的交手样本未必相同。':'本队营地样本汇总，不同选手或英雄的对局样本未必相同。';
    const data=esc(JSON.stringify({items:raw,metrics}));
    const choices=raw.map(x=>`<option value="${esc(x.key)}">${text(x.label)}</option>`).join('');
    return withPage(titles[kind],note,block('选择两个对象','切换后可并列查看已记录指标。',`<div class="compare-widget" data-pair-data="${data}"><div class="compare-select"><label>对象 A<select data-pair="a">${choices}</select></label><span>VS</span><label>对象 B<select data-pair="b">${choices}</select></label></div><div data-pair-result></div></div>`));
  }
  function capturePage() {
    return withPage('导入表格','上传训练赛数据，先预览识别结果，再确认导入。',block('选择文件','支持 CSV、TSV、XLSX 与 XLSM，单个文件不超过 20 MB。',`<div class="upload-area"><span class="upload-icon">${icon('sources')}</span><h2>将比赛数据带入平台</h2><p>先选择文件，检查工作表、字段和数据粒度。预览文件会保留，原始文件不会被修改。</p><label class="primary upload-button">选择表格<input type="file" data-import-file accept=".csv,.tsv,.xlsx,.xlsm"></label><p data-import-status role="status"></p></div><div data-import-preview></div>`),false);
  }
  /* ─── 对局子页（智能找局 / 精选对局 / 训练纪录 / 版本对比）─────────────
     四页统一成「一行一局」的读法：编号 → 对局 → 比分 → 时长 → 金差 → 结果。
     筛选、排序、分组都在前端按已加载数据完成，不改后端口径。 */
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const matchIndex = (matches) => {
    const ordered = [...matches].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')) || String(a.key).localeCompare(String(b.key)));
    return new Map(ordered.map((m, i) => [m.key, i + 1]));
  };
  const scoreOf = (m) => {
    const s = m.scores || {}, own = m.ownCamp === 'red' ? 'red' : 'blue', foe = own === 'blue' ? 'red' : 'blue';
    return { own: s[own] ?? (own === 'blue' ? s.left : s.right), enemy: s[foe] ?? (foe === 'blue' ? s.left : s.right) };
  };
  const resCls = (r) => r === 'win' ? 'win' : r === 'loss' ? 'loss' : 'muted';
  const resLabel = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '未知';
  const lede = (items) => `<div class="fj-lede">${items.map(([label, value, note]) => `<span><small>${esc(label)}</small><b>${value}</b>${note ? `<i>${esc(note)}</i>` : ''}</span>`).join('')}</div>`;
  const heroStrip = (heroes, limit = 5) => `<span class="fj-heroes">${(heroes || []).slice(0, limit).map((x) => portrait(x)).join('')}</span>`;
  const top = (items, f, dir = 'max') => {
    const valid = items.filter((x) => isNum(f(x)));
    if (!valid.length) return null;
    return [...valid].sort((a, b) => dir === 'max' ? f(b) - f(a) : f(a) - f(b))[0];
  };
  const meanOf = (items, f) => {
    const v = items.map(f).filter(isNum);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  const matchRow = (m, no) => {
    const sc = scoreOf(m), cls = resCls(m.result);
    const meta = [m.session, m.mode].filter(Boolean).join(' · ') || '训练赛';
    return `<a class="fj-row ${cls}" href="${route('match', m.key)}" data-match-row data-no="${no}"
      data-opponent="${esc(String(m.opponent || '').toLowerCase())}"
      data-heroes="${esc((m.heroes || []).join(' ').toLowerCase())}"
      data-result="${esc(m.result || 'unknown')}"
      data-duration="${isNum(m.duration) ? m.duration : 0}"
      data-gold="${isNum(m.goldDiff) ? m.goldDiff : 0}">
      <span class="fj-no">第 ${no} 局</span>
      <span class="fj-main"><b>${esc(m.opponent ? '对阵 ' + m.opponent : '对手未标注')}</b><small>${esc(meta)}</small></span>
      <span class="fj-score">${isNum(sc.own) && isNum(sc.enemy) ? `<b class="${m.result === 'win' ? 'lead' : ''}">${fmt(sc.own)}</b><i>:</i><b class="${m.result === 'loss' ? 'lead' : ''}">${fmt(sc.enemy)}</b>` : '<em>未记录</em>'}</span>
      <span class="fj-num"><small>时长</small>${time(m.duration)}</span>
      <span class="fj-num"><small>终局金差</small>${diff(m.goldDiff)}</span>
      ${heroStrip(m.heroes)}
      <span class="fj-go" aria-hidden="true">→</span>
    </a>`;
  };

  function queryPage(value) {
    const matches = value.matches || [];
    const index = matchIndex(matches);
    const sessions = [...new Set(matches.map((m) => m.session).filter(Boolean))];
    const foes = [...new Set(matches.map((m) => m.opponent).filter(Boolean))].sort();
    const heroes = [...new Set(matches.flatMap((m) => m.heroes || []))].sort();
    const decided = matches.filter((m) => m.result === 'win' || m.result === 'loss');
    const wins = matches.filter((m) => m.result === 'win').length;
    const unlabeled = matches.length - matches.filter((m) => m.opponent).length;
    const toolbar = `<div class="fj-toolbar">
      <label class="fj-field"><span>对手</span><input data-match-filter="opponent" list="fj-foes" placeholder="输入对手，或从建议里选"></label>
      <label class="fj-field"><span>英雄</span><input data-match-filter="heroes" list="fj-heroes" placeholder="输入英雄，或从建议里选"></label>
      <div class="fj-field"><span>结果</span><div class="fj-chips">
        <button type="button" class="fj-chip" data-result-chip="" aria-pressed="true">全部</button>
        <button type="button" class="fj-chip" data-result-chip="win" aria-pressed="false">胜</button>
        <button type="button" class="fj-chip" data-result-chip="loss" aria-pressed="false">负</button>
      </div></div>
      <label class="fj-field"><span>排序</span><select data-match-sort><option value="new">最新在前</option><option value="old">最早在前</option><option value="duration">时长最长</option><option value="gold">金差最大</option></select></label>
      <p class="fj-count" data-result-count>共 ${fmt(matches.length)} 局</p>
    </div>
    <datalist id="fj-foes">${foes.map((x) => `<option value="${esc(x)}"></option>`).join('')}</datalist>
    <datalist id="fj-heroes">${heroes.map((x) => `<option value="${esc(x)}"></option>`).join('')}</datalist>`;
    const rows = [...matches].sort((a, b) => index.get(b.key) - index.get(a.key)).map((m) => matchRow(m, index.get(m.key))).join('');
    return withPage('智能找局', '按对手、英雄、结果与排序，挑出要复盘的那一局。',
      lede([['当前范围', `${fmt(matches.length)} 局`],
        ['训练组', `${fmt(sessions.length)} 个`, sessions.slice(0, 2).join(' / ')],
        ['对手', foes.length ? `${fmt(foes.length)} 个` : '未标注', unlabeled ? `${fmt(unlabeled)} 局未标注` : '全部已标注'],
        ['胜率', decided.length ? pct(wins / decided.length * 100) : '—', `${fmt(wins)} 胜 / ${fmt(decided.length)} 局有胜负`],
        ['平均时长', time(meanOf(matches, (m) => m.duration))]])
      + block('对局列表', `共 ${fmt(matches.length)} 局；筛选与排序只影响当前视图，不改变数据口径。`, `${toolbar}<div class="fj-list" data-match-results>${rows}<p class="fj-empty" data-match-empty hidden>没有符合当前条件的对局，清空筛选再试。</p>${rows ? '' : empty('当前范围暂无对局。')}</div>`), false);
  }

  function featuredPage(matchesData, tempoData) {
    const list = matchesData.matches || [];
    const byKey = new Map(list.map((m) => [m.key, m]));
    const index = matchIndex(list);
    const games = (tempoData.process?.matches || []).filter((g) => byKey.has(g.key) && Array.isArray(g.points) && g.points.length >= 2);
    const avgAbs = meanOf(games, (g) => Math.abs(g.finalDiff || 0)) || 6000;
    /* 复盘价值：反转次数 > 逆风翻盘 > 终局胶着 > 差距悬殊 > 时长 */
    const valueOf = (g) => (g.signFlips || 0) * 1.6
      + (isNum(g.diffAt?.['600']) && g.diffAt['600'] < 0 && g.win ? 2.4 : 0)
      + Math.max(0, 1 - Math.abs(g.finalDiff || 0) / Math.max(2000, avgAbs * 1.6)) * 1.4
      + Math.min(1, Math.abs(g.finalDiff || 0) / 12000) * 0.8
      + Math.min(1, (g.duration || 0) / 1200) * 0.5;
    /* 不按分数堆四张同质卡：每张回答一个不同的问题。首选被占用时顺延到下一条，
       标题里的名次按全局真实排名写，不把第二名说成「最」。 */
    const picked = [];
    const taken = new Set();
    const push = (g, reason) => {
      if (!g || taken.has(g.key) || picked.length >= 4) return;
      taken.add(g.key);
      picked.push({ g, reason });
    };
    const pickBy = (list, reason) => {
      const g = list.find((x) => !taken.has(x.key));
      if (g && picked.length < 4) push(g, reason(g));
    };
    const rankOf = (f, dir, g) => 1 + games.filter((x) => dir === 'max' ? f(x) > f(g) : f(x) < f(g)).length;
    const nth = (r, best, rest) => r === 1 ? best : `第 ${r} ${rest}`;
    const total = games.length;
    pickBy([...games].sort((a, b) => (b.signFlips || 0) - (a.signFlips || 0)),
      (g) => `经济差正负切换 ${fmt(g.signFlips || 0)} 次，${total} 局里${nth(rankOf((x) => x.signFlips || 0, 'max', g), '最多', '多')}`);
    pickBy([...games].sort((a, b) => Math.abs(a.finalDiff || 0) - Math.abs(b.finalDiff || 0)),
      (g) => `终局只差 ${diff(g.finalDiff)}，${total} 局里${nth(rankOf((x) => -Math.abs(x.finalDiff || 0), 'max', g), '最接近', '接近')}`);
    pickBy(games.filter((g) => isNum(g.diffAt?.['600']) && g.diffAt['600'] < 0 && g.win).sort((a, b) => a.diffAt['600'] - b.diffAt['600']),
      (g) => `10 分钟落后 ${diff(-g.diffAt['600'])}，最后翻了回来`);
    pickBy([...games].sort((a, b) => Math.abs(b.finalDiff || 0) - Math.abs(a.finalDiff || 0)),
      (g) => `终局经济差 ${diff(g.finalDiff)}，${total} 局里${nth(rankOf((x) => Math.abs(x.finalDiff || 0), 'max', g), '最悬殊', '大')}`);
    pickBy([...games].sort((a, b) => (b.duration || 0) - (a.duration || 0)),
      (g) => `打了 ${time(g.duration)}，${total} 局里${nth(rankOf((x) => x.duration || 0, 'max', g), '最长', '长')}`);
    for (const g of [...games].sort((a, b) => valueOf(b) - valueOf(a))) push(g, `时间轴完整，可作为同类局的对照`);
    const cards = picked.map(({ g, reason }, i) => {
      const m = byKey.get(g.key), no = index.get(g.key), cls = resCls(m.result);
      return `<article class="fj-card ${cls}">
        <div class="fj-card-top"><span class="fj-card-rank">${String(i + 1).padStart(2, '0')}</span>
          <span class="fj-card-meta">第 ${no} 局 · ${esc(m.date || '')} · ${esc(m.opponent ? '对阵 ' + m.opponent : '对手未标注')}</span>
          <span class="fj-badge ${cls}">${resLabel(m.result)}</span></div>
        <h2>${esc(reason)}</h2>
        <p>${time(g.duration)} 结束 · 10 分钟经济差 ${diff(g.diffAt?.['600'])} · 终局 ${diff(g.finalDiff)}</p>
        ${microChart(g.points, '本队经济差')}
        <div class="fj-card-foot"><span>正负切换 ${fmt(g.signFlips || 0)} 次 · 采样覆盖 ${pct(g.coverage)}</span><a href="${route('match', m.key)}">查看复盘 →</a></div>
      </article>`;
    }).join('');
    const best = picked[0], bestMatch = best && byKey.get(best.g.key);
    return withPage('精选对局', '按复盘价值排一遍，先看最值得回看的那几局。',
      lede([['有完整时间轴', `${fmt(games.length)} 局`],
        ['最值得回看', bestMatch ? `第 ${index.get(bestMatch.key)} 局` : '—', best ? best.reason : ''],
        ['平均终局金差', diff(meanOf(games, (g) => g.finalDiff)), '本队减对手'],
        ['平均正负切换', `${fmt(meanOf(games, (g) => g.signFlips || 0), 1)} 次`]])
      + `<div class="fj-cards">${cards || empty('当前范围没有可用的经济时间轴。')}</div>`, false);
  }

  function recordsPage(matchesData, tempoData) {
    const all = matchesData.matches || [];
    const index = matchIndex(all);
    const games = new Map((tempoData.process?.matches || []).map((g) => [g.key, g]));
    const duration = (m) => isNum(m.duration) && m.duration > 0 ? m.duration : null;
    const gpm = (m) => isNum(m.own?.gold) && duration(m) ? m.own.gold / (duration(m) / 60) : null;
    const flips = (m) => games.has(m.key) ? games.get(m.key).signFlips : null;
    const records = [
      ['最长对局', duration, (m) => time(m.duration), 'max', '按营地记录时长'],
      ['最短对局', duration, (m) => time(m.duration), 'min', '按营地记录时长'],
      ['最大终局金差', (m) => m.goldDiff, (m) => diff(m.goldDiff), 'max', '本队减对手'],
      ['最小终局金差', (m) => m.goldDiff, (m) => diff(m.goldDiff), 'min', '本队减对手'],
      ['最高击杀', (m) => m.own?.kills, (m) => fmt(m.own.kills), 'max', '本队五人击杀合计'],
      ['最高 KDA', (m) => m.own?.kda, (m) => fmt(m.own.kda, 1), 'max', '(击杀 + 助攻) / 死亡'],
      ['经济最反复', flips, (m) => `${fmt(flips(m))} 次`, 'max', '经济差正负切换次数'],
      ['最高分均经济', gpm, (m) => fmt(gpm(m)), 'max', '本队五人经济 ÷ 时长（金 / 分钟）'],
    ];
    const cards = records.map(([label, f, show, dir, note]) => {
      const holder = top(all, f, dir);
      if (!holder) return '';
      const mean = meanOf(all, f), value = f(holder);
      const gap = isNum(mean) && mean !== 0 ? Math.round(Math.abs((value - mean) / Math.abs(mean)) * 100) : null;
      return `<article class="fj-rec">
        <span class="fj-rec-label">${esc(label)}</span>
        <strong>${show(holder)}</strong>
        <p>${esc(note)}${isNum(gap) ? ` · ${value >= mean ? '高' : '低'}于均值 ${fmt(gap)}%` : ''}</p>
        <a href="${route('match', holder.key)}"><span>第 ${index.get(holder.key)} 局 · ${esc(holder.opponent || '对手未标注')}</span><b>查看 →</b></a>
      </article>`;
    }).join('');
    return withPage('训练纪录', '这批局的极值在哪一场，和均值差多少。',
      lede([['对局', `${fmt(all.length)} 局`],
        ['平均时长', time(meanOf(all, duration))],
        ['平均终局金差', diff(meanOf(all, (m) => m.goldDiff)), '本队减对手'],
        ['平均击杀', fmt(meanOf(all, (m) => m.own?.kills), 1), '本队五人和']])
      + `<div class="fj-recs">${cards || empty('当前范围没有可计算的记录。')}</div>`, false);
  }

  function versions(value) {
    const matches = value.matches || [];
    const covered = matches.filter((m) => m.version).length;
    const dims = [['version', '版本'], ['session', '训练组']];
    const active = covered ? 'version' : 'session';
    /* 版本按数字段排（S42 → S41 → …），不要字典序把 S9 排在 S40 后面。 */
    const versionRank = (raw) => {
      const text = String(raw || '').toUpperCase();
      const hit = /^S(\d+)$/.exec(text);
      if (hit) return [2, Number(hit[1])];
      const numbers = text.match(/\d+/g);
      return numbers ? [1, ...numbers.map(Number)] : [0];
    };
    const versionCompare = (a, b) => {
      const left = versionRank(a), right = versionRank(b);
      for (let i = 0; i < Math.max(left.length, right.length); i++) {
        const delta = (left[i] || 0) - (right[i] || 0);
        if (delta) return delta;
      }
      return String(a).localeCompare(String(b), 'zh');
    };
    const rowsOf = (dim) => {
      const keyOf = dim === 'version' ? (m) => m.version || '未记录版本' : (m) => m.session || '未标注训练组';
      const groups = new Map();
      for (const m of matches) {
        const k = keyOf(m);
        const g = groups.get(k) || { n: 0, w: 0, d: 0, seconds: 0, durs: 0, gold: 0, golds: 0 };
        g.n++;
        if (m.result === 'win' || m.result === 'loss') { g.d++; if (m.result === 'win') g.w++; }
        if (isNum(m.duration) && m.duration > 0) { g.seconds += m.duration; g.durs++; }
        if (isNum(m.goldDiff)) { g.gold += m.goldDiff; g.golds++; }
        groups.set(k, g);
      }
      const max = Math.max(1, ...[...groups.values()].map((g) => g.n));
      const ordered = [...groups.entries()].sort(dim === 'version'
        ? (a, b) => versionCompare(b[0], a[0]) || b[1].n - a[1].n
        : (a, b) => b[1].n - a[1].n);
      return ordered.map(([name, g]) => `<div class="fj-group">
        <span class="fj-group-name">${esc(name)}<small>${fmt(g.n)} 局</small></span>
        <span class="fj-group-bar"><i style="width:${(g.n / max * 100).toFixed(1)}%"></i></span>
        <span class="fj-group-stat"><small>胜率</small>${g.d ? pct(g.w / g.d * 100) : '—'}</span>
        <span class="fj-group-stat"><small>平均时长</small>${g.durs ? time(g.seconds / g.durs) : '—'}</span>
        <span class="fj-group-stat"><small>平均金差</small>${g.golds ? diff(g.gold / g.golds) : '—'}</span>
      </div>`).join('');
    };
    const note = covered ? '' : `<p class="fj-note">${fmt(matches.length)} 局都还没有记录版本，先按训练组看；在单局里补录版本后，这里会自动按版本分组。</p>`;
    const chips = dims.map(([k, label]) => `<button type="button" class="fj-chip" data-fj-dim="${k}" aria-pressed="${k === active}">${label}</button>`).join('');
    const panels = dims.map(([k]) => `<div class="fj-panel" data-fj-panel="${k}" ${k === active ? '' : 'hidden'}>${rowsOf(k)}</div>`).join('');
    return withPage('版本对比', '按版本或训练组，看局数、胜率与平均节奏。',
      lede([['对局', `${fmt(matches.length)} 局`],
        ['版本覆盖', `${fmt(covered)} / ${fmt(matches.length)}`],
        ['训练组', `${fmt(new Set(matches.map((m) => m.session).filter(Boolean)).size)} 个`]])
      + block('分组对比', '胜率只以有胜负的对局为分母；平均金差为本队减对手。', `<div class="fj-dims">${chips}</div>${note}${panels}`), false);
  }
  function setup(value, teams, players, pending, migration, clusters) {
    const o = value.overview || {}, profile = o.profile || {};
    const teamList = teams.teams || [], playerList = players.players || [];
    const clusterTeams = (clusters && clusters.teams) || [];
    const clusterIds = new Set(clusterTeams.map((t) => t.id));
    const opponentTeams = clusterIds.size
      ? teamList.filter((t) => clusterIds.has(t.id))
      : teamList.filter((t) => t.id !== 'team-own');
    const manualTeams = clusterIds.size
      ? teamList.filter((t) => t.id !== 'team-own' && !clusterIds.has(t.id))
      : [];
    const namedTeams = opponentTeams.filter((t) => !isPlaceholderTeam(t.name));
    const teamNumber = (t) => Number((String(t.name || '').match(/#(\d+)/) || [])[1] || 9999);
    const unnamedTeams = opponentTeams.filter((t) => isPlaceholderTeam(t.name)).sort((a, b) => teamNumber(a) - teamNumber(b) || String(a.name).localeCompare(String(b.name), 'zh'));
    const counts = migration.counts || {};
    const matchCount = counts.match_records || 0;
    const teamReady = opponentTeams.length ? namedTeams.length === opponentTeams.length : teamList.length > 0;
    const steps = [
      {name:'本队资料', ok:!!profile.teamName, meta:profile.teamName ? `${profile.teamName}${profile.coach ? ' · ' + profile.coach : ''}` : '填写战队名与主教练', href:'#setup', jump:'profile'},
      {name:'战队主数据', ok:teamReady, meta:opponentTeams.length ? `${namedTeams.length} / ${opponentTeams.length} 支对手已命名` : (teamList.length ? '只有本队档案' : '还没有战队主数据'), href:'#setup', jump:'teams'},
      {name:'选手主数据', ok:playerList.length > 0, meta:playerList.length ? `${playerList.length} 名已登记` : '还没有本队选手', href:'#setup', jump:'players'},
      {name:'结构化对局', ok:matchCount > 0, meta:`${matchCount} 局已迁移`, href:'#matches'},
      {name:'待确认字段', ok:pending.fields === 0, meta:pending.fields ? `${pending.fields} 项待确认` : '没有待确认字段', href:'#pending'},
    ];
    const done = steps.filter((x) => x.ok).length;
    const percent = Math.round(done / steps.length * 100);
    let next;
    if (!profile.teamName) next = {title:'先补齐本队资料', note:'战队名与主教练会进入报告署名、教练档案和平台展示。', cta:'填写本队资料', href:'#setup', jump:'profile'};
    else if (!teamList.length) next = {title:'添加第一支战队', note:'战队是选手归属、交手记录和 BP 分析的挂载点。', cta:'添加战队', href:'#setup', jump:'teams'};
    else if (!teamReady) next = {title:`给 ${unnamedTeams.length} 支对手战队命名`, note:'命名后，对局、BP、报告和对手页会显示真实队名，而不是「待命名对手 #N」。', cta:'开始命名', href:'#setup', jump:'teams'};
    else if (!playerList.length) next = {title:'登记第一名本队选手', note:'选手主数据决定个人分析能否跨局对比。', cta:'添加选手', href:'#setup', jump:'players'};
    else if (pending.fields > 0) next = {title:`核对 ${pending.fields} 项待确认字段`, note:'版本、规则与训练组确认后，复盘才会归到正确的口径。', cta:'去待确认', href:'#pending'};
    else if (migration.candidates > 0) next = {title:`迁移 ${migration.candidates} 局新增对局`, note:'只补基本信息，不覆盖既有记录，也不推测身份与 BP 手序。', cta:'迁移对局', href:'#setup', jump:'migration'};
    else next = {title:'前置数据已就绪', note:'主数据、对局和待确认字段都已处理，可以进入对局与训练分析。', cta:'查看对局', href:'#matches'};
    const nextCta = `<a class="primary sx-head-cta" href="${next.href}" ${next.jump ? `data-sx-jump="${next.jump}"` : ''}>${esc(next.cta)} →</a>`;
    const cockpit = `<section class="sx-progress-card" aria-label="建档进度">
      <div class="sx-progress-main">
        <div class="sx-ring" style="--sx-progress:${percent}" role="img" aria-label="建档完成 ${done} / ${steps.length}">
          <span><b>${done}</b><small>/${steps.length}</small></span>
        </div>
        <div class="sx-progress-copy">
          <span class="sx-eyebrow">赛训准备度</span>
          <h2>${done === steps.length ? '前置数据已就绪' : `还差 ${steps.length - done} 项，分析才完整`}</h2>
          <p>${done === steps.length ? '主数据、对局与待确认字段都已处理，可以开始复盘。' : '每完成一项，后面的对局、选手与报告就会少一层人工校正。'}</p>
          <div class="sx-bar"><i style="width:${percent}%"></i></div>
          <a class="sx-next" href="${next.href}" ${next.jump ? `data-sx-jump="${next.jump}"` : ''}>
            <span class="sx-next-kicker">下一步</span>
            <b>${esc(next.title)}</b>
            <small>${esc(next.note)}</small>
            <em>${esc(next.cta)} →</em>
          </a>
        </div>
      </div>
      <ol class="sx-checklist">${steps.map((step, i) => `<li class="sx-check ${step.ok ? 'is-done' : ''}">
        <a href="${step.href}" ${step.jump ? `data-sx-jump="${step.jump}"` : ''}>
          <span class="sx-check-dot">${step.ok ? '✓' : String(i + 1).padStart(2, '0')}</span>
          <span class="sx-check-copy"><b>${esc(step.name)}</b><small>${esc(step.meta)}</small></span>
          <span class="sx-check-state">${step.ok ? '已完成' : '待完成'}</span>
          <span class="sx-check-arrow">→</span>
        </a>
      </li>`).join('')}</ol>
    </section>`;
    const checks = (o.dataQuality && o.dataQuality.checks) || [];
    const failed = checks.filter((c) => Number(c.missing || 0) > 0);
    const qualityTarget = failed[0]?.key === 'identity' ? '#identity' : '#matches';
    const quality = checks.length ? `<section class="sx-quality ${failed.length ? 'is-warn' : 'is-ok'}">
      <div class="sx-quality-score"><b>${o.dataQuality.score ?? '—'}</b><small>数据分</small></div>
      <div class="sx-quality-copy"><b>${failed.length ? `${failed.length} 项检查未通过` : '前置检查全部通过'}</b><p>${failed.length ? `${esc(failed[0].label)} · ${esc(failed[0].hint)}${failed.length > 1 ? ` 等 ${failed.length} 项` : ''}` : '对手、时长、经济差、分路与选手绑定均可用于分析。'}</p></div>
      <a class="control" href="${qualityTarget}">${failed.length ? '去处理' : '查看数据'} →</a>
    </section>` : '';
    const legacyMembers = (profile.members || []).filter((m) => !m.archived);
    const legacyBanner = legacyMembers.length > playerList.length && !profile.rosterMigratedAt ? `<section class="sx-legacy">
      <div class="sx-legacy-copy"><b>旧档案里还有 ${legacyMembers.length} 名成员</b><p>它们还没有进入选手主数据。迁移会保留旧 id，并自动跳过同名、同战队、同位置的重复项。</p></div>
      <button type="button" class="control" data-sx-migrate-roster>迁移旧名单</button>
      <p class="sx-legacy-status" role="status"></p>
    </section>` : '';
    const profileForm = form('profile',
      field('战队名称','teamName',profile.teamName||'', 'required maxlength="50" placeholder="如：成都 AG 超玩会"')+
      field('主教练','coach',profile.coach||'', 'placeholder="如：李教练"')+
      field('赛季','season',profile.season||'', 'placeholder="如：2026 春季赛"')+
      field('组织','organization',profile.organization||'', 'placeholder="如：AG 电子竞技俱乐部"'),
      '保存本队资料');
    const profileBlock = block('本队资料','平台展示、教练档案与报告署名都会用到这一组信息。',profileForm,profile.teamName?'<span class="sx-done-badge">已保存</span>':'','data-sx-anchor="profile"');
    const quickOptions = unnamedTeams.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
    const quickForm = unnamedTeams.length ? `<div class="sx-quick">
      <div class="sx-quick-copy"><b>命名队列</b><p>${unnamedTeams.length} 支战队还是占位名。命名会同步到对局、BP、报告与对手归属。</p></div>
      ${form('sxRenameTeam',select('待命名战队','id',quickOptions)+field('真实队名','name','','required maxlength="40" placeholder="如：重庆狼队"')+field('主教练','coach','','placeholder="可留空"'),'保存命名')}
    </div>` : `<div class="sx-quick is-done"><div class="sx-quick-copy"><b>战队名都已补齐</b><p>已命名 ${namedTeams.length} 支；需要时可展开下方战队列表编辑。</p></div></div>`;
    const teamToolbar = `<div class="sx-toolbar">
      <label class="sx-search">${icon('search')}<input data-sx-team-search placeholder="搜索战队名或教练" aria-label="搜索战队"></label>
      <div class="sx-chips">
        <button type="button" class="fj-chip" data-sx-team-chip="all" aria-pressed="true">全部 ${teamList.length}</button>
        <button type="button" class="fj-chip" data-sx-team-chip="unnamed" aria-pressed="false">待命名 ${unnamedTeams.length}</button>
        <button type="button" class="fj-chip" data-sx-team-chip="named" aria-pressed="false">已命名 ${namedTeams.length}</button>
      </div>
      <span class="sx-toolbar-count" data-sx-team-count>共 ${teamList.length} 支</span>
    </div>`;
    const teamRank = (t) => t.id === 'team-own' ? 0 : isPlaceholderTeam(t.name) ? 1 : 2;
    const sortedTeams = [...teamList].sort((a, b) => teamRank(a) - teamRank(b) || teamNumber(a) - teamNumber(b) || String(a.name).localeCompare(String(b.name), 'zh'));
    const teamRows = sortedTeams.map((t, i) => {
      const own = t.id === 'team-own';
      const manual = !own && !clusterIds.has(t.id);
      const named = !isPlaceholderTeam(t.name);
      return `<details class="sx-team-item" data-sx-team data-sx-own="${own ? '1' : '0'}" data-sx-manual="${manual ? '1' : '0'}" data-sx-name="${esc((t.name + ' ' + (t.coach || '')).toLowerCase())}" data-sx-named="${named ? '1' : '0'}" ${i >= 6 ? 'hidden' : ''}>
        <summary>
          <span class="sx-team-mark ${named ? 'is-named' : ''}">${esc((t.name || '待').slice(0, 1))}</span>
          <span class="sx-team-title"><b>${text(t.name)}</b><small>${own ? '本队档案 · 所有分析的本队视角' : manual ? '手动建档 · 用于选手归属，不计入对手命名进度' : named ? (t.coach ? '主教练 ' + text(t.coach) : '教练未填') : '营地阵容聚类 · 待命名'}</small></span>
          <span class="sx-team-state ${own ? 'is-own' : manual ? 'is-manual' : named ? 'is-named' : 'is-pending'}">${own ? '本队' : manual ? '手动' : named ? '已命名' : '待命名'}</span>
          <span class="sx-team-edit">编辑</span>
        </summary>
        ${form('masterTeam',`<input type="hidden" name="id" value="${esc(t.id)}"><input type="hidden" name="status" value="${esc(t.status || 'active')}">`+field('战队名称','name',t.name,'required maxlength="40"')+field('简称','shortName',t.short_name||'')+field('教练','coach',t.coach||''),'保存修改')}
      </details>`;
    }).join('');
    const teamListHtml = `<div class="sx-team-list" data-sx-team-list>${teamRows}<p class="sx-empty" data-sx-team-empty hidden>没有符合条件的战队，换个筛选或关键词再试。</p></div>
      <button class="sx-more" type="button" data-sx-team-more ${teamList.length <= 6 ? 'hidden' : ''}>显示全部 ${teamList.length} 支</button>`;
    const bulkTeams = JSON.stringify(unnamedTeams.map((t) => ({id:t.id, name:t.name})));
    const bulkForm = `<details class="sx-manage"><summary>批量命名（粘贴名单 / CSV）</summary><div class="sx-manage-body">
      <form class="feature-form sx-bulk-form" data-feature-form="bulkRename" data-sx-teams="${esc(bulkTeams)}">
        <label class="sx-bulk-names">名单<textarea name="names" rows="6" placeholder="每行一个队名，按待命名顺序对应；也可写 #1=重庆狼队"></textarea></label>
        <div class="sx-bulk-foot"><label class="sx-bulk-file">从 CSV/TXT 读入<input type="file" data-sx-bulk-file accept=".csv,.txt"></label><p class="form-status" role="status"></p><button class="primary" type="submit">批量保存</button></div>
      </form>
      <p class="sx-form-note">按当前待命名顺序逐行对应；显式写 #1=队名 可以跳过顺序。一次最多 200 支。</p>
    </div></details>`;
    const teamManage = bulkForm + `<details class="sx-manage"><summary>新增战队 / 合并重复战队</summary><div class="sx-manage-body">
      ${form('masterTeam',field('战队名称','name','','required maxlength="40"')+field('简称','shortName')+field('教练','coach'),'添加战队')}
      ${form('masterMerge',select('来源战队','from',options(teamList))+select('合并至','into',options(teamList)),'合并主数据')}
      <div class="sx-reconcile"><p>旧版本的命名覆盖层与工作区主数据不一致时，可一次对账；只补名字和教练，不动比赛记录。</p><button type="button" class="control" data-sx-reconcile-teams>对账历史战队名</button><p class="form-status" role="status"></p></div>
    </div></details>`;
    const teamBlock = block('战队主数据','营地识别到的对手战队；本队和手动建档的战队单独标出，不计入对手命名进度。',quickForm+teamToolbar+teamListHtml+teamManage,`<span class="sx-count">${fmt(opponentTeams.length)} 支对手 · 本队 ${fmt(teamList.length - opponentTeams.length - manualTeams.length)}${manualTeams.length ? ` · 手动 ${fmt(manualTeams.length)}` : ''}</span>`,'data-sx-anchor="teams"');
    const playerForm = form('masterPlayer',
      select('所属战队','teamId',options(teamList))+
      field('选手名称','name','','required maxlength="40" placeholder="游戏内 ID 或常用名"')+
      select('位置','position','<option value="">待确认</option>'+['对抗路','打野','中路','发育路','游走'].map((x) => `<option value="${x}">${x}</option>`).join(''))+
      field('营地 ID','campUserId','','placeholder="营地用户 ID，可后补"'),
      '添加选手');
    const playerRows = playerList.map((p) => {
      const team = teamList.find((t) => t.id === p.team_id)?.name || '未指定战队';
      return `<div class="sx-player-row"><span class="sx-player-mark">${esc((p.name || '?').slice(0, 1))}</span><span class="sx-player-main"><b>${text(p.name)}</b><small>${text(team)} · ${text(p.position || '位置未填')}</small></span><span class="sx-player-state ${p.role === 'main' ? 'is-main' : ''}">${p.role === 'main' ? '主力' : '替补'}</span></div>`;
    }).join('');
    const editPlayers = playerList.map((p) => `<details class="sx-manage"><summary>${text(p.name)} · 编辑</summary><div class="sx-manage-body">${form('masterPlayer',`<input type="hidden" name="id" value="${esc(p.id)}"><input type="hidden" name="aliases" value="${esc(JSON.stringify(p.aliases||[]))}"><input type="hidden" name="role" value="${esc(p.role||'main')}">`+select('所属战队','teamId',options(teamList,p.team_id))+field('选手名称','name',p.name,'required maxlength="40"')+select('位置','position','<option value="">待确认</option>'+['对抗路','打野','中路','发育路','游走'].map((x) => `<option value="${x}" ${p.position === x ? 'selected' : ''}>${x}</option>`).join(''))+field('营地 ID','campUserId',p.camp_user_id||''),'保存修改')}</div></details>`).join('');
    const playerBlock = block('选手主数据','先有战队，再登记本队选手；营地 ID 用来把对局昵称绑定到同一个人。',playerForm+(playerRows?`<div class="sx-player-list">${playerRows}</div>`:'')+editPlayers,`<span class="sx-count">${fmt(playerList.length)} 名</span>`,'data-sx-anchor="players"');
    const migrationBlock = block('对局迁移',migration.note || '仅新增未迁移的真实对局基本信息；不覆盖现有记录，不推测选手身份、对手归属及 BP 手序。',
      `<div class="sx-migration">
        <div><span>结构化对局</span><b>${fmt(matchCount)}</b><small>局</small></div>
        <div><span>阵容记录</span><b>${fmt(counts.match_rosters)}</b><small>条</small></div>
        <div><span>BP 记录</span><b>${fmt(counts.bp)}</b><small>条</small></div>
        <div><span>待迁移</span><b>${fmt(migration.candidates)}</b><small>局</small></div>
        <button class="control" data-feature-action="migrate" ${migration.candidates?'':'disabled'}>迁移新增对局</button>
        <p class="migration-status" role="status"></p>
      </div>`,'','data-sx-anchor="migration"');
    return withPage('建档',`本队资料、战队与选手主数据是后续识别的前提 · 当前 ${done} / ${steps.length} 项已完成。`,
      cockpit+quality+legacyBanner+profileBlock+teamBlock+playerBlock+migrationBlock,false,nextCta,false,true);
  }
  function pending(value, teams, vocab) {
    const rows = value.rows || [];
    const foeTeams = (teams.teams || []).filter((t) => t.id !== 'team-own');
    const fieldCounts = {};
    for (const row of rows) for (const f of row.fields) fieldCounts[f.field] = (fieldCounts[f.field] || 0) + 1;
    const fieldChips = Object.entries(fieldCounts).map(([key, count]) => `<button type="button" class="fj-chip" data-sx-pending-chip="${esc(key)}" aria-pressed="false">${esc(mapping[key] || key)} ${count}</button>`).join('');
    const placeholderOf = (field) => ({version:'如：S40 / 1.2.3', rules:'如：KPL 全局 BP', session:'如：周中训练', pick_order:'JSON 数组，如 ["A","B"]'}[field] || '填写核实后的值');
    const controlOf = (f) => {
      if (f.field === 'enemy_team_id' || f.field === 'opponent') return `<select name="value">${options(foeTeams, f.value)}</select>`;
      if (VOCAB_KINDS[f.field] === 'sessions') return `<input name="value" list="sx-vocab-session" value="${esc(f.value ?? '')}" placeholder="${esc(placeholderOf(f.field))}" autocomplete="off">`;
      if (VOCAB_KINDS[f.field]) return vocabControl('value', vocabList(vocab, f.field), f.value ?? '', {empty: '请选择'});
      return `<input name="value" value="${esc(f.value ?? '')}" placeholder="${esc(placeholderOf(f.field))}" autocomplete="off">`;
    };
    const cards = rows.map((row) => {
      const fields = row.fields.map((f) => {
        const label = mapping[f.field] || f.field;
        return `<form class="sx-confirm" data-feature-form="confirm" data-sx-field="${esc(f.field)}">
          <input type="hidden" name="matchKey" value="${esc(row.matchKey)}"><input type="hidden" name="field" value="${esc(f.field)}">
          <label class="sx-confirm-field"><span class="sx-confirm-label"><b>${esc(label)}</b><small>${esc(sourceName(f.source))}${confidenceName(f.confidence) ? ' · ' + confidenceName(f.confidence) : ''}</small></span>${controlOf(f)}</label>
          <button class="control" type="submit">确认</button>
          <p class="form-status" role="status"></p>
        </form>`;
      }).join('');
      const shortKey = String(row.matchKey || '').replace(/^channel-/, '').slice(0, 8) || '—';
      return `<article class="sx-pending-card" data-sx-pending-card data-sx-total="${row.fields.length}" data-sx-search="${esc((row.opponent + ' ' + row.date + ' ' + row.matchKey).toLowerCase())}">
        <header><div><span>${text(row.date || '日期未知')}</span><b>${text(row.opponent || '对手未确认')}</b></div><span class="sx-pending-key" title="${esc(row.matchKey)}">${esc(shortKey)}</span><a href="#match/${encodeURIComponent(row.matchKey)}">查看对局 →</a></header>
        <div class="sx-pending-fields">${fields}</div>
        <div class="sx-pending-foot"><span data-sx-card-count>${row.fields.length} 项待确认</span><p class="sx-card-status" role="status"></p><button type="button" class="control" data-sx-confirm-card>全部确认</button></div>
      </article>`;
    }).join('');
    const toolbar = rows.length ? `<div class="sx-toolbar">
      <label class="sx-search">${icon('search')}<input data-sx-pending-search placeholder="搜索对手、日期或对局 ID" aria-label="搜索待确认对局"></label>
      <div class="sx-chips"><button type="button" class="fj-chip" data-sx-pending-chip="" aria-pressed="true">全部 ${value.fields}</button>${fieldChips}</div>
      <span class="sx-toolbar-count" data-sx-pending-count>共 ${value.total} 局 · ${value.fields} 项</span>
    </div>` : '';
    return withPage('待确认',`逐项核对预填字段，确认后写入记录与来源 · ${fmt(value.fields)} 项待确认，分布在 ${fmt(value.total)} 局。`,
      lede([['待确认对局',`${fmt(value.total)} 局`,'含至少一个待确认字段'],['待确认字段',`${fmt(value.fields)} 项`,'逐项确认'],['自动预填','系统生成','需要人工核实'],['写入方式','确认后写回','标记人工来源']])
      + vocabDatalist(vocabList(vocab, 'session'))
      + block('确认队列','版本 / 规则 / 赛制从词表里选，训练组可输入新值；保存时统一归一化，「其他」手填的新值下次自动出现。',
        toolbar+`<div class="sx-pending-grid">${cards || '<p class="sx-empty">当前没有待确认字段。</p>'}</div><p class="sx-empty" data-sx-pending-empty hidden>没有匹配的待确认字段。</p>`,
        `<button class="control" data-feature-action="prefill">重新扫描</button>`,'data-sx-scope="pending"'),false,'',false,true);
  }
  function plan(value, teams, vocab) {
    const schedules = value.schedules || [];
    const today = localDate();
    const foeTeams = (teams.teams || []).filter((t) => t.id !== 'team-own');
    const statusOptions = (current) => ['planned','confirmed','completed','cancelled'].map((v) => `<option value="${v}" ${current === v ? 'selected' : ''}>${statusLabels[v]}</option>`).join('');
    const schedFields = (x = {}) => field('日期','date',x.date||today,'type="date" required')+
      field('开始时间','startTime',x.start_time||'','type="time"')+
      select('约战对手','opponentTeamId',options(foeTeams,x.opponent_team_id))+
      vocabCombo('训练组','session',vocabList(vocab,'session'),x.session||'')+
      vocabSelect('赛制','format',vocabList(vocab,'format'),x.format||'',{empty:'待定'})+
      vocabSelect('规则','rules',vocabList(vocab,'rules'),x.rules||'',{empty:'待定'})+
      vocabSelect('版本','version',vocabList(vocab,'version'),x.version||'',{empty:'待定'})+
      field('备注','notes',x.notes||'','placeholder="训练重点、集合时间等"')+
      select('状态','status',statusOptions(x.status||'planned'));
    const ordered = [...schedules].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')) || String(a.start_time || '').localeCompare(String(b.start_time || '')));
    const upcoming = ordered.filter((x) => String(x.date || '') >= today);
    const past = ordered.filter((x) => String(x.date || '') < today).reverse();
    const next = upcoming.find((x) => x.status !== 'cancelled' && x.status !== 'completed');
    const opponentOf = (x) => teams.teams.find((t) => t.id === x.opponent_team_id)?.name || '未指定对手';
    const rowOf = (x) => {
      const status = x.status || 'planned';
      return `<details class="sx-plan-row is-${esc(status)}">
        <summary>
          <span class="sx-plan-date"><b>${text(x.date)}</b><small>${text(x.start_time || '时间未定')}</small></span>
          <span class="sx-plan-opponent"><b>${text(opponentOf(x))}</b><small>${text(x.session || '训练组未定')}</small></span>
          <span class="sx-plan-format">${text(x.format || '赛制未定')}</span>
          <span class="sx-plan-state is-${esc(status)}">${statusLabels[status] || status}</span>
          <span class="sx-plan-edit">修改</span>
        </summary>
        ${form('schedule',`<input type="hidden" name="id" value="${esc(x.id)}">`+schedFields(x),'保存修改')}
      </details>`;
    };
    const nextBanner = next ? `<div class="sx-plan-next"><span>下一场</span><b>${text(next.date)} ${text(next.start_time || '')}</b><p>对阵 ${text(opponentOf(next))} · ${text(next.session || '训练组未定')} · ${text(next.format || '赛制未定')}</p></div>` : '';
    const list = schedules.length ? `<div class="sx-plan-list">${nextBanner}${[...upcoming, ...past].map(rowOf).join('')}</div>`
      : `<div class="sx-empty sx-empty-inline"><b>还没有登记任何计划</b><p>登记今天约谁、练什么，赛后就能按对手和训练组回看。</p><button type="button" class="control" data-sx-jump="plan-form">添加第一条计划 ↓</button></div>`;
    const valid = schedules.filter((x) => x.status !== 'cancelled').length;
    const planSection = block('训练赛排期','按日期查看；点开一行可以修改时间、对手和状态。',list,`<span class="sx-count">${fmt(schedules.length)} 条</span>`,'data-sx-anchor="plan-list"');
    const formSection = block('添加计划','登记后，当天训练赛的采集与复盘会自动挂到这局上。',form('schedule',schedFields(),'添加计划'),'','data-sx-anchor="plan-form"');
    return withPage('约定计划',`登记训练赛时间、对手与赛制 · 已登记 ${fmt(schedules.length)} 条，其中 ${fmt(valid)} 条有效。`,
      lede([['已登记',`${fmt(schedules.length)} 条`,'训练赛排期'],['下一场',next?`${next.date} ${next.start_time||''}`:'—',next?'已排期':'还没有未来计划'],['有效计划',`${fmt(valid)} 条`,'未取消'],['训练组',`${fmt(new Set(schedules.map((x) => x.session).filter(Boolean)).size)} 个`,'按 session 归组']])
      + vocabDatalist(vocabList(vocab, 'session'))
      + `<div class="sx-plan-layout">${planSection}${formSection}</div>`,false,
      `<a class="control sx-head-cta" href="#plan" data-sx-jump="plan-form">添加计划</a>`,false,true);
  }
  const renders={ingest:v=>capturePageV1.render(v),capture:v=>sourcePages.render('capture',v),shots:v=>sourcePages.render('shots',v),videos:v=>sourcePages.render('videos',v),replays:v=>sourcePages.render('replays',v),review:(v,k)=>reviewPage.render(k,v),identity:v=>playerPages.identityPage(v[0]), players:v=>playerPages.playersPage(v[0]),study:(v,k)=>research.study(v[1],v[0],k),reports:v=>research.reports(v[0]),report:v=>research.report(v[1]),topic:v=>depth.topic(v[1]),hero:(v,k)=>heroDetail(v[0],v[1],v[2],v[3],v[4],v[5],v[6],k),teambp:v=>teamBp(v[0]),query:v=>queryPage(v[0]),featured:v=>featuredPage(v[0],v[1]),records:v=>recordsPage(v[0],v[1]),teamcompare:v=>pairComparison('team',v[0]),playercompare:v=>playerPages.comparePage(v[0]),playerdetail:(v,k)=>playerPages.soloPage(v[0],k),herocompare:v=>pairComparison('hero',v[0]),teams:(v,k)=>teamsPage(v[0],k),team:(v,k)=>teamsPage(v[0],k,v[1],v[2]),h2h:v=>h2h(v[0]),profiles:v=>profiles(v[0]),ownership:v=>ownership(v[0]),coach:v=>coach(v[0],v[1]),compare:v=>playerPages.lanePage(v[0]),heroes:v=>heroes(v[0]),bp:v=>bpBoard(v[0]),combos:v=>combos(v[0]),economy:v=>economy(v[0]),effect:v=>effect(v[0],v[1]),versions:v=>versions(v[0]),setup:v=>setup(...v),pending:v=>pending(v[0],v[1],v[2]),plan:v=>plan(v[0],v[1],v[2])};
  async function api(path, options={}) { const r=await fetch(API_BASE + '/api/'+path,{cache:'no-store',...options}); if(!r.ok){let detail; try {detail=(await r.json()).detail} catch {} throw new Error(typeof detail==='string'?detail:'操作失败，请检查输入或稍后重试。')} return r.json(); }
  const targets={rename:'studio/teams/rename',merge:'studio/teams/merge',assign:'studio/opponents/assign',coach:'studio/coach',training:'studio/workspace/training',profile:'studio/profile',masterTeam:'studio/workspace/teams',masterMerge:'studio/workspace/teams/merge',masterPlayer:'studio/workspace/players',confirm:'studio/workspace/pending/confirm',schedule:'studio/workspace/schedules'};
  function syncSetupTeams(root) {
    if (!root) return;
    const list = root.querySelector('[data-sx-team-list]');
    if (!list) return;
    const q = (root.querySelector('[data-sx-team-search]')?.value || '').trim().toLowerCase();
    const filter = root.dataset.sxTeamFilter || 'all';
    const expanded = root.dataset.sxTeamExpanded === '1';
    let matched = 0, visible = 0;
    list.querySelectorAll('[data-sx-team]').forEach((row) => {
      const named = row.dataset.sxNamed === '1';
      const own = row.dataset.sxOwn === '1';
      const manual = row.dataset.sxManual === '1';
      const okName = filter === 'all' || (!own && !manual && (filter === 'named' ? named : !named));
      const ok = (!q || String(row.dataset.sxName || '').includes(q)) && okName;
      const limited = !expanded && filter === 'all' && !q && visible >= 6;
      row.hidden = !ok || limited;
      if (ok) matched++;
      if (ok && !limited) visible++;
    });
    const counter = root.querySelector('[data-sx-team-count]');
    if (counter) counter.textContent = matched === Number(list.querySelectorAll('[data-sx-team]').length) ? `共 ${fmt(matched)} 支` : `找到 ${fmt(matched)} 支`;
    const more = root.querySelector('[data-sx-team-more]');
    if (more) {
      more.hidden = expanded || !!q || filter !== 'all' || matched <= 6;
      more.textContent = expanded ? '收起列表' : `显示全部 ${fmt(matched)} 支`;
    }
    const empty = root.querySelector('[data-sx-team-empty]');
    if (empty) empty.hidden = matched > 0;
  }
  function syncOwnershipGroups(root) {
    if (!root) return;
    const groups = [...root.querySelectorAll('[data-sx-own-group]')];
    if (!groups.length) return;
    const q = (root.querySelector('[data-sx-own-search]')?.value || '').trim().toLowerCase();
    const filter = root.dataset.sxOwnFilter || 'all';
    const expanded = root.dataset.sxOwnExpanded === '1';
    let matched = 0, visible = 0;
    groups.forEach((group) => {
      const named = group.dataset.sxNamed === '1';
      const unassigned = Number(group.dataset.sxUnassigned || 0);
      const okFilter = filter === 'all' || (filter === 'unnamed' && !named) || (filter === 'unassigned' && unassigned > 0);
      const hit = !q || String(group.dataset.sxName || '').includes(q);
      const limited = !expanded && filter === 'all' && !q && visible >= 5;
      group.hidden = !(okFilter && hit) || limited;
      if (okFilter && hit) matched++;
      if (okFilter && hit && !limited) visible++;
    });
    const counter = root.querySelector('[data-sx-own-count]');
    if (counter) counter.textContent = q || filter !== 'all' ? `找到 ${fmt(matched)} 组` : `共 ${fmt(matched)} 组`;
    const more = root.querySelector('[data-sx-own-more]');
    if (more) {
      more.hidden = expanded || !!q || filter !== 'all' || matched <= 5;
      more.textContent = expanded ? '收起列表' : `展开全部 ${fmt(matched)} 组`;
    }
    const empty = root.querySelector('[data-sx-own-empty]');
    if (empty) empty.hidden = matched > 0;
  }
  function syncPendingQueue(root) {
    if (!root) return;
    const cards = [...root.querySelectorAll('[data-sx-pending-card]')];
    if (!cards.length) return;
    const q = (root.querySelector('[data-sx-pending-search]')?.value || '').trim().toLowerCase();
    const field = root.dataset.sxPendingField || '';
    let shown = 0, total = 0;
    cards.forEach((card) => {
      let fields = 0;
      card.querySelectorAll('form[data-sx-field]').forEach((form) => {
        const ok = !field || form.dataset.sxField === field;
        form.hidden = !ok;
        if (ok) fields++;
      });
      const hit = !q || String(card.dataset.sxSearch || '').includes(q);
      card.hidden = !hit || fields === 0;
      const count = card.querySelector('[data-sx-card-count]');
      if (count) count.textContent = `${fields} 项待确认`;
      const batch = card.querySelector('[data-sx-confirm-card]');
      if (batch) batch.textContent = fields === Number(card.dataset.sxTotal || 0) ? '全部确认' : '确认本项';
      if (!card.hidden) { shown++; total += fields; }
    });
    const counter = root.querySelector('[data-sx-pending-count]');
    if (counter) counter.textContent = `共 ${fmt(shown)} 局 · ${fmt(total)} 项`;
    const empty = root.querySelector('[data-sx-pending-empty]');
    if (empty) empty.hidden = shown > 0;
  }
  function openSxTeamDialog(mode, data = {}) {
    const dialog = document.querySelector('#sx-team-dialog');
    if (!dialog) return;
    dialog.dataset.mode = mode;
    dialog.querySelector('[data-sx-dialog-title]').textContent = mode === 'rename' ? '命名战队' : '调整选手归属';
    const rename = dialog.querySelector('[data-sx-dialog-panel="rename"]');
    const assign = dialog.querySelector('[data-sx-dialog-panel="assign"]');
    rename.hidden = mode !== 'rename';
    assign.hidden = mode !== 'assign';
    if (mode === 'rename') {
      dialog.querySelector('[name="id"]').value = data.id || '';
      dialog.querySelector('[name="name"]').value = data.name || '';
      dialog.querySelector('[name="coach"]').value = data.coach || '';
    } else {
      dialog.querySelector('[name="playerId"]').value = data.playerId || '';
      dialog.querySelector('[name="teamId"]').value = data.teamId || '';
      dialog.querySelector('[data-sx-dialog-player]').textContent = data.playerName ? `${data.playerName} 当前归属：${data.teamName || '未归属'}` : '';
    }
    if (!dialog.open) dialog.showModal();
    setTimeout(() => dialog.querySelector(mode === 'rename' ? '[name="name"]' : '[name="teamId"]')?.focus(), 30);
  }
  function saveTeamEverywhere(f, payload, dialog = null) {
    const status = f.querySelector('.form-status');
    const button = f.querySelector('button[type=submit]');
    if (!String(payload.name || '').trim()) {
      if (status) status.textContent = '请填写战队名称。';
      return true;
    }
    button.disabled = true;
    if (status) status.textContent = '正在保存…';
    api('studio/workspace/teams', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,status:payload.status||'active'})})
      .then(() => {
        dialog?.close();
        reload();
      })
      .catch((error) => {
        if (status) status.textContent = error.message;
        button.disabled = false;
      });
    return true;
  }
  function confirmPendingCard(button) {
    const card = button.closest('[data-sx-pending-card]');
    if (!card) return;
    const status = card.querySelector('.sx-card-status');
    const forms = [...card.querySelectorAll('form[data-sx-field]')].filter((f) => !f.hidden);
    const entries = forms.map((f) => ({f, data: applyVocabValue(f, Object.fromEntries(new FormData(f)))}));
    const missing = entries.find((x) => !String(x.data.value ?? '').trim());
    if (missing) {
      status.textContent = '请先填写本局所有字段。';
      missing.f.querySelector('input,select')?.focus();
      return;
    }
    button.disabled = true;
    status.textContent = '确认中…';
    api('studio/workspace/pending/confirm-batch', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({items:entries.map(({data}) => data)}),
    }).then(() => reload()).catch((error) => {
      status.textContent = error.message;
      button.disabled = false;
    });
  }
  function bindSxDialogs(root = document) {
    root.querySelectorAll('dialog.sx-dialog').forEach((dialog) => {
      if (dialog.dataset.sxBound) return;
      dialog.dataset.sxBound = '1';
      dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
    });
  }
  function submitBulkRename(f, payload) {
    const status = f.querySelector('.form-status');
    const button = f.querySelector('button[type=submit]');
    let teams = [];
    try { teams = JSON.parse(f.dataset.sxTeams || '[]'); } catch {}
    const lines = String(payload.names || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!teams.length) { status.textContent = '当前没有待命名战队。'; return true; }
    if (!lines.length) { status.textContent = '请先粘贴或读入名单。'; return true; }
    const used = new Set();
    const items = [];
    for (let i = 0; i < lines.length; i++) {
      let left = '', right = lines[i];
      const equal = right.indexOf('=');
      const tab = right.indexOf('\t');
      const comma = right.indexOf(',');
      if (equal >= 0) {
        left = right.slice(0, equal).trim();
        right = right.slice(equal + 1).trim();
      } else if (tab >= 0) {
        left = right.slice(0, tab).trim();
        right = right.slice(tab + 1).trim();
      } else if (comma >= 0) {
        left = right.slice(0, comma).trim();
        right = right.slice(comma + 1).trim();
      }
      if (!right) continue;
      if (/^(id|编号|战队|队伍)$/i.test(left) && /^(name|队名|名称)$/i.test(right)) continue;
      let team = null;
      if (left) {
        const token = left.replace(/^#/, '').trim();
        team = teams.find((t) => t.id === left) || teams.find((t) => t.name === left);
        if (!team && /^\d+$/.test(token)) team = teams[Number(token) - 1];
      } else {
        team = teams.find((t) => !used.has(t.id));
      }
      if (!team) { status.textContent = `第 ${i + 1} 行找不到对应战队：${lines[i]}`; return true; }
      if (used.has(team.id)) { status.textContent = `第 ${i + 1} 行重复对应同一支战队。`; return true; }
      used.add(team.id);
      items.push({id:team.id, name:right});
    }
    if (!items.length) { status.textContent = '没有读到可保存的队名。'; return true; }
    button.disabled = true;
    status.textContent = `正在保存 ${items.length} 支…`;
    api('studio/teams/rename-batch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items})})
      .then(() => reload())
      .catch((error) => { status.textContent = error.message; button.disabled = false; });
    return true;
  }
  function submit(event) {
    const f=event.target.closest('[data-feature-form]'); if(!f)return false;
    event.preventDefault(); const id=f.dataset.featureForm, payload=Object.fromEntries(new FormData(f));
    /* 词表下拉选了「其他（手填）」：用手填值覆盖哨兵值，空值让后端按必填规则拦下。 */
    applyVocabValue(f, payload);
    if (id === 'bulkRename') return submitBulkRename(f, payload);
    if (id === 'sxRenameTeam' || id === 'masterTeam' || id === 'rename') return saveTeamEverywhere(f, payload);
    if (id === 'sxTeamDialog') {
      const dialog = f.closest('dialog');
      if (dialog?.dataset.mode === 'rename') return saveTeamEverywhere(f, {id:payload.id,name:payload.name,coach:payload.coach}, dialog);
      const status = f.querySelector('.form-status');
      if (!payload.playerId) { if (status) status.textContent = '缺少选手信息，请重新打开调整窗口。'; return true; }
      const button = f.querySelector('button[type=submit]');
      button.disabled = true;
      if (status) status.textContent = '正在保存…';
      api('studio/opponents/assign', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({playerId:payload.playerId,teamId:payload.teamId||null})})
        .then(() => { dialog?.close(); reload(); })
        .catch((error) => { if (status) status.textContent = error.message; button.disabled = false; });
      return true;
    }
    if((id==='merge'||id==='masterMerge')&&(!payload.from||!payload.into||payload.from===payload.into)){f.querySelector('.form-status').textContent='请选择不同的来源和目标战队。';return true}
    if((id==='merge'||id==='masterMerge')&&!window.confirm('合并会修改共享战队归属，确定合并这两支战队吗？'))return true;
    if(id==='masterPlayer'&&payload.aliases) payload.aliases=JSON.parse(payload.aliases);
    if(id==='saveReport') payload.filters=JSON.parse(payload.filters);
    if(id==='identityClaim') {const aliases=JSON.parse(f.dataset.aliases||'{}');payload.expected=aliases[payload.label]||'';if(payload.expected&&payload.expected!==payload.playerId&&!window.confirm('该昵称已绑定其他选手，确认修改认领吗？'))return true;}
    if(id==='matchbp') { const split=name=>(payload[name]||'').split(/[,，、\n]+/).map(x=>x.trim()).filter(Boolean);payload.bp={bans:{left:split('leftBans'),right:split('rightBans')},picks:{left:split('leftPicks'),right:split('rightPicks')},firstPick:payload.firstPick||'',notes:payload.notes||''}; }
    if(id==='training') { if(payload.endDate && payload.endDate<payload.startDate){f.querySelector('.form-status').textContent='结束日期不能早于开始日期。';return true} payload.target=payload.target===''?null:Number(payload.target); payload.playerIds=payload.playerIds?[payload.playerIds]:[]; }
    if(id==='confirm'&&payload.field==='pick_order'){try{payload.value=JSON.parse(payload.value);if(!Array.isArray(payload.value))throw Error()}catch{f.querySelector('.form-status').textContent='选用顺序须为 JSON 数组；未知时请保留待确认。';return true}}
    const button=f.querySelector('button[type=submit]');button.disabled=true;f.querySelector('.form-status').textContent='正在保存…';
    api(id==='matchmeta'?'v2/match-meta/'+encodeURIComponent(payload.matchKey):id==='matchbp'?'v2/match-bp/'+encodeURIComponent(payload.matchKey):id==='saveReport'?'v2/research/reports':id==='identityClaim'?'v2/identity/claim':id==='identityRoster'?'v2/identity/roster':id==='identityName'?'v2/identity/name':targets[id],{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(result=>{if(id==='saveReport')location.hash='#report/'+encodeURIComponent(result.id);else reload()}).catch(error=>{f.querySelector('.form-status').textContent=error.message;button.disabled=false});return true;
  }
  let anchorObserver = null;
  function updateAnchorNav(root = document) {
    anchorObserver?.disconnect();
    const nav = root.querySelector('.hero-anchor-nav');
    if (!nav || typeof IntersectionObserver === 'undefined') return;
    const panels = [...root.querySelectorAll('.hero-detail-grid > .section')];
    const buttons = [...nav.querySelectorAll('[data-hero-scroll]')];
    anchorObserver = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        const index = panels.indexOf(entry.target);
        buttons.forEach((button, i) => button.classList.toggle('is-active', i === index));
      }
    }, { rootMargin: '-15% 0px -75% 0px' });
    panels.forEach(panel => anchorObserver.observe(panel));
  }
  function updatePairs(root=document) {
    root.querySelectorAll('[data-pair-data]').forEach(widget=>{
      const {items,metrics}=JSON.parse(widget.dataset.pairData), a=widget.querySelector('[data-pair="a"]'),b=widget.querySelector('[data-pair="b"]');
      if (!widget.dataset.ready) { if(b.options.length>1)b.selectedIndex=1;widget.dataset.ready='1'; }
      const left=items.find(x=>String(x.key)===a.value), right=items.find(x=>String(x.key)===b.value);
      const visual=metrics.map(([label,key])=>{const a=left?.[key],b=right?.[key],max=Math.max(1,typeof a==='number'?a:0,typeof b==='number'?b:0);const show=x=>key==='winRate'||key==='participation'?pct(x):fmt(x,2);return `<div class="pair-metric"><div><b>${text(label)}</b><span>${show(a)} <i> / </i> ${show(b)}</span></div><div class="pair-tracks"><i style="width:${typeof a==='number'?Math.max(0,a/max*100):0}%"></i><i style="width:${typeof b==='number'?Math.max(0,b/max*100):0}%"></i></div></div>`}).join('');
      widget.querySelector('[data-pair-result]').innerHTML=`<div class="pair-legend"><span><i></i>${text(left?.label||'对象 A')}</span><span><i></i>${text(right?.label||'对象 B')}</span></div><div class="pair-metric-grid">${visual}</div>`+table(['指标',left?.label||'对象 A',right?.label||'对象 B'],metrics.map(([label,key])=>[text(label),key==='winRate'||key==='participation'?pct(left?.[key]):fmt(left?.[key],2),key==='winRate'||key==='participation'?pct(right?.[key]):fmt(right?.[key],2)]));
    });
  }
  async function importFile(input) {
    const file=input.files?.[0];if(!file)return;
    const root=input.closest('.section'),status=root.querySelector('[data-import-status]'),preview=root.querySelector('[data-import-preview]');
    status.textContent='正在读取与识别字段…';preview.innerHTML='';
    try {
      const response=await fetch(API_BASE + '/api/v2/import/preview?name='+encodeURIComponent(file.name),{method:'POST',body:file});
      const value=await response.json();if(!response.ok)throw Error(value.detail||'表格读取失败');
      if(!root.isConnected)return;status.textContent='请核对识别结果。';
      preview.innerHTML=`<div class="import-preview"><div class="section-heading"><div><h2>${text(value.name)}</h2><p>${value.sheets.length} 个工作表 · 请确认字段识别与粒度</p></div></div>${value.sheets.map(sheet=>`<div class="import-sheet"><h3>${text(sheet.name)} <small>${fmt(sheet.rows)} 行 · 粒度 ${text(sheet.grain||'未识别')}</small></h3><p>字段：${text((sheet.header||[]).join('、'))}</p>${sheet.unmappedColumns?.length?`<p>未映射：${text(sheet.unmappedColumns.join('、'))}</p>`:''}${sheet.warnings?.length?`<p>${text(sheet.warnings.join('；'))}</p>`:''}${table(sheet.header||[],(sheet.sample||[]).map(row=>Array.isArray(row)?row.map(text):(sheet.header||[]).map(key=>text(row[key]))))}</div>`).join('')}<div class="import-actions"><p role="status" data-import-commit-status></p><button class="primary" data-feature-action="import-commit" data-preview-id="${esc(value.previewId)}">确认导入</button></div></div>`;
    }catch(error){status.textContent=error.message}
  }
  function change(event) {
    if (event.target.matches('[data-sx-team-search]')) { syncSetupTeams(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-own-search]')) { syncOwnershipGroups(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-pending-search]')) { syncPendingQueue(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-bulk-file]')) {
      const file = event.target.files?.[0];
      const form = event.target.closest('form');
      if (file && form) {
        const textarea = form.querySelector('[name="names"]');
        const status = form.querySelector('.form-status');
        file.text().then((text) => {
          if (textarea) textarea.value = text;
          if (status) status.textContent = `已读入 ${file.name}`;
        }).catch(() => { if (status) status.textContent = '文件读取失败。'; });
      }
      return true;
    }
if(playerPages.change(event))return true;
if(sourcePages.change(event))return;
if(capturePageV1.change(event))return;
    /* 词表下拉选到「其他（手填）」时展开输入框；换回已有选项则收起。 */
    if(event.target.matches('[data-vocab-select]')) {
      const custom = event.target.parentElement.querySelector('[data-vocab-custom]');
      if (custom) {
        const open = event.target.value === '__custom__';
        custom.hidden = !open;
        if (open) custom.focus();
      }
      return;
    }
    if(event.type==='change' && event.target.matches('[data-import-file]')) importFile(event.target);
    depth.change(event);
    if(event.target.matches('[data-hero-filter]')) {
      const root = event.target.closest('.hero-board');
      if (root) {
        const name = (root.querySelector('[data-hero-filter="name"]')?.value || '').trim().toLowerCase();
        const tier = root.querySelector('[data-hero-filter="tier"]')?.value || '';
        let count = 0;
        root.querySelectorAll('[data-hero-row]').forEach(row => {
          const show = (!name || String(row.dataset.heroName || '').toLowerCase().includes(name)) && (!tier || row.dataset.heroTier === tier);
          row.hidden = !show;
          if (show) count++;
        });
        const counter = root.querySelector('[data-hero-count]');
        if (counter) counter.textContent = `共 ${fmt(count)} 个英雄`;
      }
    }
    /* 时间粒度由 click() 的胶囊按钮切换，不再使用 select。 */
    if(event.target.matches('[data-bp-filter]')) {
      const root=event.target.closest('.bp-page');
      if(root&&bpState){
        root.querySelectorAll('[data-bp-filter]').forEach(el=>{bpState.f[el.dataset.bpFilter]=el.value;});
        root.innerHTML=bpBoardHtml();
        updateAnchorNav(root);
      }
    }
    if(event.target.matches('[data-bp-team]')) {
      const root=event.target.closest('[data-bp-subject="team"]');
      if(root&&bpTeamState){bpTeamState.key=event.target.value;root.innerHTML=bpSubjectHtml();updateAnchorNav(root);}
    }
    if(event.target.matches('[data-bp-coach]')) {
      const root=event.target.closest('[data-bp-subject="coach"]');
      if(root&&bpCoachState){bpCoachState.key=event.target.value;root.innerHTML=bpCoachHtml();}
    }
    if(event.target.matches('[data-pair]')) updatePairs(event.target.closest('[data-pair-data]').parentElement);
    if(event.target.matches('[data-match-filter],[data-match-sort]')) syncMatchQuery(event.target.closest('.section'));
    if(event.target.matches('[data-team-search],[data-team-sort]')) syncTeamList(event.target.closest('.section'));
  }
  /* 找局 / 精选 / 纪录共用的前端视图控制：文本筛选 + 结果胶囊 + 排序 + 计数。 */
  function syncMatchQuery(root) {
    if (!root) return;
    const val = (sel) => (root.querySelector(sel)?.value || '').trim().toLowerCase();
    const opponent = val('[data-match-filter="opponent"]');
    const hero = val('[data-match-filter="heroes"]');
    const result = root.dataset.resultFilter || '';
    const sort = root.querySelector('[data-match-sort]')?.value || 'new';
    const list = root.querySelector('[data-match-results]');
    if (!list) return;
    const rows = [...list.querySelectorAll('[data-match-row]')];
    let shown = 0;
    for (const row of rows) {
      const ok = (!opponent || String(row.dataset.opponent || '').includes(opponent))
        && (!hero || String(row.dataset.heroes || '').includes(hero))
        && (!result || row.dataset.result === result);
      row.hidden = !ok;
      if (ok) shown++;
    }
    const num = (row, key) => Number(row.dataset[key] || 0);
    const order = {
      new: (a, b) => num(b, 'no') - num(a, 'no'),
      old: (a, b) => num(a, 'no') - num(b, 'no'),
      duration: (a, b) => num(b, 'duration') - num(a, 'duration'),
      gold: (a, b) => Math.abs(num(b, 'gold')) - Math.abs(num(a, 'gold')),
    }[sort];
    if (order) [...rows].sort(order).forEach((row) => list.append(row));
    const counter = root.querySelector('[data-result-count]');
    if (counter) counter.textContent = shown === rows.length ? `共 ${fmt(shown)} 局` : `找到 ${fmt(shown)} 局 · 共 ${fmt(rows.length)} 局`;
    const emptyHint = root.querySelector('[data-match-empty]');
    if (emptyHint) emptyHint.hidden = shown > 0;
  }
  function click(event) { /* 这三个模块的 click 是 async，返回值是 Promise（恒真），不能直接用来判断是否处理；先用选择器同步判定，再交给它们异步执行。 */
    const jump = event.target.closest('[data-sx-jump]');
    if (jump) {
      event.preventDefault();
      const target = document.querySelector(`[data-sx-anchor="${jump.dataset.sxJump}"]`);
      if (target) {
        target.scrollIntoView({behavior:'smooth', block:'start'});
        setTimeout(() => target.querySelector('input,select,button')?.focus({preventScroll:true}), 260);
      }
      return true;
    }
    if (event.target.closest('[data-sx-dialog-close]')) {
      event.target.closest('dialog')?.close();
      return true;
    }
    const migrateRoster = event.target.closest('[data-sx-migrate-roster]');
    if (migrateRoster) {
      const banner = migrateRoster.closest('.sx-legacy');
      const status = banner?.querySelector('.sx-legacy-status');
      migrateRoster.disabled = true;
      if (status) status.textContent = '正在迁移旧名单…';
      api('studio/workspace/players/migrate-profile', {method:'POST'})
        .then((result) => {
          if (status) status.textContent = `已迁移 ${result.imported || 0} 名，跳过 ${result.skipped || 0} 名。`;
          setTimeout(() => reload(), 500);
        })
        .catch((error) => {
          if (status) status.textContent = error.message;
          migrateRoster.disabled = false;
        });
      return true;
    }
    const reconcileTeams = event.target.closest('[data-sx-reconcile-teams]');
    if (reconcileTeams) {
      const box = reconcileTeams.closest('.sx-reconcile');
      const status = box?.querySelector('.form-status');
      reconcileTeams.disabled = true;
      if (status) status.textContent = '正在对账…';
      api('studio/workspace/teams/reconcile', {method:'POST'})
        .then((result) => {
          if (status) status.textContent = `已同步 ${result.count || 0} 项。`;
          setTimeout(() => reload(), 500);
        })
        .catch((error) => { if (status) status.textContent = error.message; reconcileTeams.disabled = false; });
      return true;
    }
    const setupChip = event.target.closest('[data-sx-team-chip]');
    if (setupChip) {
      const root = setupChip.closest('.section');
      if (root) {
        root.dataset.sxTeamFilter = setupChip.dataset.sxTeamChip;
        root.dataset.sxTeamExpanded = '0';
        root.querySelectorAll('[data-sx-team-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === setupChip)));
        syncSetupTeams(root);
      }
      return true;
    }
    const setupMore = event.target.closest('[data-sx-team-more]');
    if (setupMore) {
      const root = setupMore.closest('.section');
      if (root) {
        root.dataset.sxTeamExpanded = root.dataset.sxTeamExpanded === '1' ? '0' : '1';
        syncSetupTeams(root);
      }
      return true;
    }
    const ownChip = event.target.closest('[data-sx-own-chip]');
    if (ownChip) {
      const root = ownChip.closest('.section');
      if (root) {
        root.dataset.sxOwnFilter = ownChip.dataset.sxOwnChip;
        root.dataset.sxOwnExpanded = '0';
        root.querySelectorAll('[data-sx-own-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === ownChip)));
        syncOwnershipGroups(root);
      }
      return true;
    }
    const ownMore = event.target.closest('[data-sx-own-more]');
    if (ownMore) {
      const root = ownMore.closest('.section');
      if (root) {
        root.dataset.sxOwnExpanded = root.dataset.sxOwnExpanded === '1' ? '0' : '1';
        syncOwnershipGroups(root);
      }
      return true;
    }
    const renameTeam = event.target.closest('[data-sx-team-rename]');
    if (renameTeam) {
      openSxTeamDialog('rename', {id:renameTeam.dataset.sxTeamRename, name:renameTeam.dataset.teamName || ''});
      return true;
    }
    const assign = event.target.closest('[data-sx-player-assign]');
    if (assign) {
      const group = assign.closest('[data-sx-own-group]');
      const groupName = group?.querySelector('.sx-own-title b')?.textContent || '';
      openSxTeamDialog('assign', {playerId:assign.dataset.sxPlayerAssign, playerName:assign.dataset.playerName, teamId:assign.dataset.teamId, teamName:groupName});
      return true;
    }
    const pendingChip = event.target.closest('[data-sx-pending-chip]');
    if (pendingChip) {
      const root = pendingChip.closest('.section');
      if (root) {
        root.dataset.sxPendingField = pendingChip.dataset.sxPendingChip;
        root.querySelectorAll('[data-sx-pending-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === pendingChip)));
        syncPendingQueue(root);
      }
      return true;
    }
    const batch = event.target.closest('[data-sx-confirm-card]');
    if (batch) {
      confirmPendingCard(batch);
      return true;
    }
    if ((event.target.closest('[data-pl-pick]') || event.target.closest('[data-pl-name]') || event.target.closest('[data-pl-goto]')) && playerPages.click(event)) return true;
    const resultChip = event.target.closest('[data-result-chip]');
    if (resultChip) {
      const root = resultChip.closest('.section');
      if (root) {
        root.dataset.resultFilter = resultChip.dataset.resultChip;
        root.querySelectorAll('[data-result-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === resultChip)));
        syncMatchQuery(root);
      }
      return true;
    }
    const tmJump = event.target.closest('[data-tm-jump]');
    if (tmJump) {
      document.getElementById(tmJump.dataset.tmJump)?.scrollIntoView({behavior: 'smooth', block: 'start'});
      return true;
    }
    const teamChip = event.target.closest('[data-team-chip]');
    if (teamChip) {
      const root = teamChip.closest('.section');
      if (root) {
        root.dataset.teamFilter = teamChip.dataset.teamChip;
        root.querySelectorAll('[data-team-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === teamChip)));
        syncTeamList(root);
      }
      return true;
    }
    const viewChip = event.target.closest('[data-team-view-chip]');
    if (viewChip) {
      const root = viewChip.closest('.section');
      if (root) {
        root.dataset.teamView = viewChip.dataset.teamViewChip;
        root.querySelectorAll('[data-team-view-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === viewChip)));
        syncTeamList(root);
      }
      return true;
    }
    const renameBtn = event.target.closest('[data-team-rename]');
    if (renameBtn) {
      const label = renameBtn.dataset.teamLabel || '';
      const name = window.prompt('给这支对手战队命名（留空表示继续待命名）', label);
      if (name === null) return true;
      renameBtn.disabled = true;
      api('studio/teams/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: renameBtn.dataset.teamRename, name: name.trim() }) })
        .then(() => reload())
        .catch((error) => { renameBtn.disabled = false; window.alert(error.message); });
      return true;
    }
    const dimChip = event.target.closest('[data-fj-dim]');
    if (dimChip) {
      const root = dimChip.closest('.section');
      if (root) {
        const dim = dimChip.dataset.fjDim;
        root.querySelectorAll('[data-fj-dim]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === dimChip)));
        root.querySelectorAll('[data-fj-panel]').forEach((panel) => { panel.hidden = panel.dataset.fjPanel !== dim; });
      }
      return true;
    }
    const scrollBtn = event.target.closest('[data-hero-scroll]');
    if (scrollBtn) {
      const panel = document.querySelectorAll('.hero-detail-grid > .section')[Number(scrollBtn.dataset.heroScroll)];
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    }
    const timeTab = event.target.closest('[data-hero-time-tab]');
    if (timeTab) {
      const root = timeTab.closest('.hero-detail-page');
      if (root) {
        root.querySelectorAll('[data-hero-time-tab]').forEach(b => {
          const on = b === timeTab;
          b.classList.toggle('is-active', on);
          b.setAttribute('aria-pressed', String(on));
        });
        root.querySelectorAll('[data-hero-time-group]').forEach(group => {
          group.hidden = group.dataset.heroTimeGroup !== timeTab.dataset.heroTimeTab;
        });
      }
      return true;
    }
    const bpTab = event.target.closest('[data-bp-tab]');
    if (bpTab) {
      const root = bpTab.closest('.bp-page');
      if (root) {
        root.querySelectorAll('[data-bp-tab]').forEach(x => {
          const on = x === bpTab;
          x.classList.toggle('is-active', on);
          x.setAttribute('aria-pressed', String(on));
        });
        root.querySelectorAll('[data-bp-tab-panel]').forEach(p => { p.hidden = p.dataset.bpTabPanel !== bpTab.dataset.bpTab; });
      }
      return true;
    }
    if(event.target.closest('[data-review-action]')){reviewPage.click(event);return true;} if(event.target.closest('[data-source-action]')){sourcePages.click(event);return true;} if(event.target.closest('[data-capture-action]')||event.target.closest('[data-capture-form]')||event.target.closest('[data-chan-expand]')||event.target.closest('[data-chan-open]')){capturePageV1.click(event);return true;} const b=event.target.closest('[data-feature-action]');if(!b)return false;if(b.dataset.featureAction==='import-commit'){b.disabled=true;const status=b.parentElement.querySelector('[data-import-commit-status]');status.textContent='正在导入…';api('v2/import/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({previewId:b.dataset.previewId})}).then(result=>{status.textContent=`导入完成：${result.sheets.length} 个工作表。可在数据范围中启用表格来源。`;b.textContent='已导入'}).catch(error=>{status.textContent=error.message;b.disabled=false});return true;}if(b.dataset.featureAction==='migrate'){b.disabled=true;api('v2/workspace/migration',{method:'POST'}).then(()=>reload()).catch(error=>{b.disabled=false;b.parentElement.querySelector('.migration-status').textContent=error.message});return true}if(b.dataset.featureAction==='prefill'){b.disabled=true;api('studio/workspace/prefill/run',{method:'POST'}).then(()=>reload()).catch(error=>{b.disabled=false;b.textContent=error.message})}return true; }
  const gameAnalyses=new Set(['time_cross_match','time_events','time_kill_rhythm','death_point_economy','tempo','swing_windows','session_summary']);
  function analysisNavigation(group,current,key,anchor='') {
    const suffix=anchor?'?match='+encodeURIComponent(anchor):'';
    const collapse=group==='matches';
    const visible=(list)=>collapse?list.filter(([id])=>!gameAnalyses.has(id)):list;
    const items=[...visible(topicGroups[group]||[]).map(([id,title])=>({href:'#topic/'+encodeURIComponent(id)+suffix,title,active:current==='topic'&&key===id})),...visible(studyGroups[group]||[]).map(([id,title])=>({href:'#study/'+encodeURIComponent(id)+suffix,title,active:current==='study'&&key===id}))];
    if(!items.length)return '';
    return `<span class="analysis-rail-label">${esc(groupLabel[group])}分析</span>${items.map(item=>`<a href="${item.href}" ${item.active?'aria-current="page"':''}>${esc(item.title)}</a>`).join('')}`;
  }
  return {analysisNavigation,has:name=>Object.hasOwn(endpoints,name)||['ingest','shots','videos','replays','review'].includes(name),load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal):name==='capture'?sourcePages.load(name,key,signal):'review'===name?reviewPage.load(name,key,signal):['shots','videos','replays'].includes(name)?sourcePages.load(name,key,signal):Promise.all((name==='topic'?[...endpoints[name],'depth/analysis/'+encodeURIComponent(key)]:name==='study'?[...endpoints[name],'v2/research/'+encodeURIComponent(key)+currentQuery()]:name==='report'?[...endpoints[name],'v2/research/reports/'+encodeURIComponent(key)]:name==='hero'?[...endpoints[name],'studio/camp-partners?hero='+encodeURIComponent(key),'matches','depth/analysis/lane_matchup','depth/analysis/equip_matrix?hero='+encodeURIComponent(key),'depth/analysis/equip_impact?hero='+encodeURIComponent(key),'v2/hero-detail/'+encodeURIComponent(key)]:name==='team'?[...endpoints[name],'studio/camp-compare?team='+encodeURIComponent(key),'v2/team-bp']:endpoints[name]).map(p=>api(p==='matches'||p==='tempo'||p==='v2/identity'?p+currentQuery():p,{signal}))),render:(name,data,key)=>renders[name](data,key),submit,click,change,afterRender:()=>{updatePairs();updateAnchorNav();capturePageV1.afterRender();sourcePages.afterRender();reviewPage.afterRender();bindSxDialogs();const setupRoot=document.querySelector('[data-sx-anchor="teams"]');if(setupRoot)syncSetupTeams(setupRoot);const ownRoot=document.querySelector('[data-sx-scope="ownership"]');if(ownRoot)syncOwnershipGroups(ownRoot);const pendingRoot=document.querySelector('[data-sx-scope="pending"]');if(pendingRoot)syncPendingQueue(pendingRoot)}};
}
