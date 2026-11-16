import { equipIcons } from './equipment-icons.js';
import { createResearch } from './research.js';
import { createCapture } from './capture-page.js';
import { createSources } from './sources-page.js';
import { createReview } from './review-page.js';
import { createPlayers } from './players-page.js';
import { createHeroCompare } from './hero-compare.js';
import { createLaneBoard } from './lane-viz.js';
import { createCoachBoard } from './coach-viz.js';
import { createPlayerCompare } from './player-compare.js';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
export const featureSections = {
  ingest: [['ingest','营地同步']],
  matches: [['matches','对局档案'], ['cross','跨局分析'], ['biggame','大场分析'], ['featured','精选对局'], ['versions','版本对比'], ['series-builder','系列赛编组']],
  teams: [['teams','战队分析'], ['teamtraining','战队训练']],
  players: [['playerarchive','选手档案'], ['compare','选手与位置'], ['playercompare','选手对比']],
  heroes: [['heroes','英雄榜'], ['herocompare','英雄对比'], ['combos','英雄组合']],
  bp: [['bp','BP 概览'], ['coach','教练档案']],
  setup: [['plan','比赛与训练'], ['setup','数据准备'], ['reports','复盘与报告']],
};

export function createFeatures(h) {
  const {esc, fmt, pct, diff, time, portrait, route, table, pageIntro, reload, currentQuery, icon, microChart, gameAnchorBar} = h;
  const heroCompare = createHeroCompare({esc, portrait});
  const laneBoard = createLaneBoard({esc});
  const coachBoard = createCoachBoard({esc});
  const playerCompare = createPlayerCompare({esc, portrait});
  const research = createResearch({esc,fmt,table,icon,pageIntro});
  const endpoints = {
    teams:['studio/teams'], team:['studio/teams'], teamtraining:['v3/team-training'],
    capture:['sources'], playerarchive:['v3/players-board','v3/identity/players'], ownership:['studio/opponents'], coach:['v3/bp-board','studio/coach'], compare:['v3/players-board'], playercompare:['v3/players-board'], playerdetail:['v3/players-board'], heroes:['studio/camp-compare'], hero:['studio/camp-compare'], herocompare:['studio/camp-compare'], featured:['matches','tempo'],
    combos:['studio/camp-combos?min=3'], reports:['v3/research/reports'], report:['v3/research/reports'], economy:['v3/economy'],
    effect:['v3/effect', 'studio/workspace/players'], versions:['matches','v3/versions'], session:['studio/workspace/sessions'],
    weekly:['studio/workspace/schedules','studio/workspace/matches','v3/effect','v3/workspace/overview','studio/workspace/teams'],
    setup:['v3/workspace/overview','studio/workspace/teams','studio/workspace/players','studio/workspace/pending','v3/workspace/migration','studio/teams','v3/identity/accounts'],
    pending:['studio/workspace/pending','studio/workspace/teams','v3/vocab'], plan:['studio/workspace/schedules','studio/workspace/teams','v3/vocab','studio/workspace/dashboard','studio/workspace/competitions'],
    competition:['studio/workspace/competitions','v3/players-board'],
  };
  const scope = '<div class="scope-note"><span>数据口径</span> 本页使用全部营地面板及关联回放，可能包含非训练赛；首页的日期、来源与验证数据筛选不适用于此处。</div>';
  const gmId = (title) => 'gm-' + String(title || '').replace(/[^a-z0-9\u4e00-\u9fa5]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  const block = (title, subtitle, body, right='', attrs='') => body ? `<section class="section" data-gm-id="${gmId(title)}" ${attrs}><div class="section-heading" data-gm-part="标题"><div><h2>${esc(title)}</h2><p>${esc(subtitle || '')}</p></div><div class="gm-inline-actions">${right}</div></div>${body}</section>` : '';
  const stats = (items) => `<div class="stats-band">${items.map(([label,value,detail]) => `<div><span>${esc(label)}</span><strong>${value}</strong><p>${esc(detail || '')}</p></div>`).join('')}</div>`;
  const empty = (s) => `<div class="empty">${esc(s)}</div>`;
  const form = (id, fields, button='保存') => `<form class="feature-form" data-feature-form="${id}">${fields}<div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit">${button}</button></div></form>`;
  const field = (label, name, value='', extra='') => `<label>${esc(label)}<input name="${esc(name)}" value="${esc(value ?? '')}" ${extra}></label>`;
  /* ── 赛训词表：版本 / 规则 / 赛制 / 训练组 ───────────────────────────
     选项来自 /api/v3/vocab（后端同一份词表）；「其他（手填）」会露出输入框，
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
  /* 合并预览要把两支队的当前五人带在选项上，教练不用跳页就能看清是不是同一支队。 */
  const options = (teams, value='') => `<option value="">请选择</option>${teams.map(t=>`<option value="${esc(t.id)}" data-roster="${esc((t.currentPlayers || t.players || []).map(p => p.name || p.id).join('、'))}" data-former="${esc(String((t.formerPlayers || []).length))}" ${t.id===value?'selected':''}>${esc(t.name || t.displayName)}</option>`).join('')}`;
  const select = (label, name, html) => `<label>${esc(label)}<select name="${esc(name)}">${html}</select></label>`;
  const multiTable = (head, rows) => table(head, rows);
  const sxIntro = (title, sub, right='', withFilter=true) => `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${right}${withFilter ? `<button class="control" data-action="filter">${icon('filter')} 数据范围</button>` : ''}<button class="control icon-control" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></div></div>`;
  const withPage = (title, sub, body, isScoped=true, right='', withFilter=true, sx=false) => `<div class="page feature-page${sx ? ' sx-page' : ''}">${isScoped ? `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="intro-actions">${right}<button class="control" data-action="refresh">刷新数据</button></div></div>` : sxIntro(title,sub,right,withFilter)}${isScoped ? scope : ''}${body}</div>`;
  const isPlaceholderTeam = (name) => /^待命名/.test(String(name || '').trim());
  const canonicalTeamName = (name) => String(name || '').trim().replace(/^待命名对手 #/, '待命名战队 #');
  const sxSubnav = (items, active) => `<nav class="sx-subnav" aria-label="子页面">${items.map(([key, label]) => `<a href="#${key}" ${key === active ? 'aria-current="page"' : ''}>${label}</a>`).join('')}</nav>`;
  const dataPrepNav = (active) => sxSubnav([['setup','建档'],['ownership','对手归属'],['pending','待确认']], active);
  const reviewNav = (active) => sxSubnav([['reports','报告库'],['effect','训练效果']], active);
  const isPlaceholderPlayer = (name) => {
    const value = String(name || '').trim();
    return value.startsWith('待命名选手') || ['新选手', '未命名', '未命名选手', '选手'].includes(value);
  };
  const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const statusLabels = {planned:'计划中', confirmed:'已确认', completed:'已完成', cancelled:'已取消'};
  const sourceName = (source) => ({placeholder:'自动生成', manual:'人工录入', migration:'迁移导入', import:'表格导入'}[source] || source || '来源未知');
  const confidenceName = (confidence) => ({high:'高可信', medium:'中可信', low:'低可信'}[confidence] || '');
  const text = x => esc(x ?? '—');
  const capture = (items, limit=12) => items.slice(0,limit);
  /* 采集页：读 V3 根接口，见 capture-page.js */
  const captureIngestPage = createCapture({esc, fmt, table, block, stats, empty, withPage, icon});
  /* 截图 / 录屏 / 回放三个素材页，见 sources-page.js */
  const sourcePages = createSources({esc, fmt, block, stats, empty, withPage, icon, table});
  /* 逐项校对，见 review-page.js */
  const reviewPage = createReview({esc, fmt, block, stats, empty, withPage, icon});
  /* 选手板块三页：选手档案（含认领命名） / 选手与位置 / 选手对比 */
  const playerPages = createPlayers({esc,fmt,pct,diff,portrait,block,empty,stats,reload});
  function bars(items, label, numberOf, display, limit=8) {
    const valid=items.map(item=>({item,n:numberOf(item)})).filter(x=>typeof x.n==='number'&&Number.isFinite(x.n)&&x.n>=0).slice(0,limit);
    if(!valid.length)return '';
    const max=Math.max(1,...valid.map(x=>x.n));
    return `<div class="insight-bars">${valid.map(({item,n})=>`<div><span>${text(label(item))}</span><div><i style="width:${n/max*100}%"></i></div><b>${text(display?display(item):fmt(n,1))}</b></div>`).join('')}</div>`;
  }
  /* ── 战队：对手目录卡（2026-11-14 赛训组改版）──────────────────────
     数据来自营地终局面板（studio/teams）。对手战队由阵容聚类识别，带阵容、
     选手 ID、逐局记录与同位置百分位。本分类只写对手，不混本队聚合口径。
     列表只做「身份 → 最近交手 → 数据格 → 折叠选手 → 详情 / 命名」；
     综合得分和排名下线——单局样本撑不起强弱关系，列表与详情都不再给总分。 */
  const TM_LANES = ['对抗路', '打野', '中路', '发育路', '游走'];
  const TM_NOTE = '营地终局面板 · 与「对局档案」口径不同，两边局数可能不一致。';
  const TEAM_VIEW_STORAGE = 'training-teams-view-v1';
  const TEAM_SORTS = ['recent', 'games', 'rate', 'name'];
  /* 搜索 / 状态 / 排序放 URL 和本机记忆：分享链接能复现条件，回页自动恢复。 */
  const readTeamViewState = () => {
    const fallback = {q: '', status: '', sort: 'recent'};
    const normalizeSort = (value) => TEAM_SORTS.includes(value) ? value : 'recent';
    const normalizeStatus = (value) => value === 'named' || value === 'pending' ? value : '';
    try {
      const params = new URLSearchParams(location.hash.split('?')[1] || '');
      if (params.has('q') || params.has('status') || params.has('sort')) {
        return {q: params.get('q') || '', status: normalizeStatus(params.get('status')), sort: normalizeSort(params.get('sort') || '')};
      }
      const saved = JSON.parse(localStorage.getItem(TEAM_VIEW_STORAGE) || 'null');
      if (saved && typeof saved === 'object') {
        return {q: String(saved.q || ''), status: normalizeStatus(saved.status), sort: normalizeSort(saved.sort)};
      }
    } catch {}
    return fallback;
  };
  const writeTeamViewState = (state) => {
    const q = String(state.q || '');
    const status = state.status === 'named' || state.status === 'pending' ? state.status : '';
    const sort = TEAM_SORTS.includes(state.sort) ? state.sort : 'recent';
    try {
      if (q || status || sort !== 'recent') localStorage.setItem(TEAM_VIEW_STORAGE, JSON.stringify({q, status, sort}));
      else localStorage.removeItem(TEAM_VIEW_STORAGE);
    } catch {}
    try {
      const path = location.hash.slice(1).split('?')[0];
      const params = new URLSearchParams(location.hash.split('?')[1] || '');
      if (q) params.set('q', q); else params.delete('q');
      if (status) params.set('status', status); else params.delete('status');
      if (sort !== 'recent') params.set('sort', sort); else params.delete('sort');
      const query = params.toString();
      const next = `#${path}${query ? `?${query}` : ''}`;
      if (location.hash !== next) history.replaceState(null, '', next);
    } catch {}
  };
  const byLaneTm = (players) => [...(players || [])].sort((a, b) => {
    const ia = TM_LANES.indexOf(a.lane), ib = TM_LANES.indexOf(b.lane);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  const tmCrest = (name) => `<span class="tm-crest">${esc((name || '?').slice(0, 1))}</span>`;
  const tmRecord = (t) => `${fmt(t.wins)} 胜 ${fmt(t.losses)} 负`;
  const tmResult = (g) => g.win === true ? ['win', '胜'] : g.win === false ? ['loss', '负'] : ['muted', '未知'];
  const tmTeamOf = (teams, id) => teams.find((t) => t.id === id)?.displayName || '未归属';
  const hasNum = (n) => typeof n === 'number' && Number.isFinite(n);
  const tmOppRate = (t) => {
    const decided = (t.wins || 0) + (t.losses || 0);
    return decided ? (t.losses || 0) / decided * 100 : null;
  };
  const tmK = (v) => hasNum(v) ? (Math.abs(v) >= 10000 ? fmt(v / 1000, 1) + 'k' : fmt(v)) : '—';
  const tmSignedNum = (v, digits = 0) => hasNum(v) ? (v > 0 ? '+' : '') + fmt(v, digits) : '—';
  const tmCard = (t, own) => {
    const m = t.metrics || {};
    const state = t.coach ? '教练 ' + t.coach : t.named ? '已建档' : '营地阵容聚类';
    const recentGames = [...(t.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || ''))).slice(0, 5);
    const recentWins = recentGames.filter((g) => g.win === true).length;
    const recentLosses = recentGames.filter((g) => g.win === false).length;
    const oppRate = tmOppRate(t);
    const rateBlock = `<div class="tm-rate" style="--rate:${hasNum(oppRate) ? oppRate.toFixed(1) : 0}">
      <div class="tm-ring"><span><b>${hasNum(oppRate) ? pct(oppRate) : '—'}</b><small>对手<br>胜率</small></span></div>
      <small class="tm-rate-own">本队 ${pct(t.winRate)}</small>
    </div>`;
    const figures = [
      ['交手', `${fmt(t.matches)} 局`, `本队 ${hasNum(t.wins) && hasNum(t.losses) ? `${fmt(t.wins)}-${fmt(t.losses)}` : '—'}`, `本队 ${tmRecord(t)}`],
      ['场均推塔', fmt(m.towerPerGame, 1), `本队 ${fmt(own?.metrics?.towerPerGame, 1)}`],
      [`近 ${recentGames.length || 0} 局`, `${recentWins} 胜 ${recentLosses} 负`, '本队视角'],
    ].map(([label, value, note], index) => `<span${index === 2 ? ' class="is-wide"' : ''}><small>${label}</small><b>${value}</b><small>${note}</small></span>`).join('');
    /* 卡上只放当前五人：历史出场过的人（离队 / 转会 / 轮换）不算进这套阵容。 */
    const rosterPlayers = byLaneTm(t.currentPlayers || t.players).slice(0, 5);
    const rosterRows = rosterPlayers.length
      ? TM_LANES.map((lane) => {
        const pl = rosterPlayers.find((item) => (item.lane || '') === lane);
        return pl
          ? `<span class="tm-roster-item" title="${esc(`${pl.name || '待补'} · ${lane} · ${fmt(pl.games || 0)} 局`)}"><b>${esc(pl.name || '待补')}</b><small>${esc(lane)} · ${fmt(pl.games || 0)} 局</small></span>`
          : `<span class="tm-roster-item is-missing"><b>${esc(lane)}</b><small>待补</small></span>`;
      }).join('')
      : '<span class="tm-roster-item is-empty">最近 5 局还没有识别到当前五人</span>';
    const filled = rosterPlayers.filter((pl) => pl.name).length;
    const former = (t.formerPlayers || []).length
      ? `<small class="tm-former-note">另有 ${fmt(t.formerPlayers.length)} 人曾出战，见详情页「曾效力」</small>` : '';
    const lastGame = recentGames[0];
    const lastResult = lastGame && typeof lastGame.win === 'boolean' ? `上一场：${lastGame.win ? '本队胜' : '对手胜'}` : '';
    const meta = [t.lastSeen ? `最近 ${text(t.lastSeen)}` : '', lastResult].filter(Boolean).join(' · ');
    const formDots = recentGames.map((g) => {
      const cls = g.win === true ? 'win' : g.win === false ? 'loss' : 'unknown';
      const label = `${g.start || '时间未知'} ${g.win === true ? '本队胜' : g.win === false ? '对手胜' : '结果未知'}`;
      return `<i class="is-${cls}" title="${esc(label)}"></i>`;
    }).join('');
    const formText = recentGames.map((g) => g.win === true ? '胜' : g.win === false ? '负' : '未知').join(' ');
    const thin = (t.matches || 0) < 3;
    const flag = !t.named ? '待命名' : thin ? '样本少' : '';
    const rosterId = `tm-roster-${String(t.id || '').replace(/[^a-zA-Z0-9_-]/g, '')}`;
    return `<article class="tm-card" data-team-row
      data-team-name="${esc([t.displayName, t.name, t.coach, ...(t.players || []).map((x) => x.name)].filter(Boolean).join(' ').toLowerCase())}"
      data-team-named="${t.named ? '1' : '0'}" data-team-games="${t.matches || 0}"
      data-team-rate="${t.winRate ?? ''}" data-team-last="${esc(t.lastSeen || '')}">
      <a class="tm-card-link" href="${route('team', t.id)}" aria-label="查看 ${esc(t.displayName)} 详情">
        <header class="tm-card-head">
          <span class="tm-crest is-lg">${esc((t.displayName || '?').slice(0, 1))}</span>
          <span class="tm-card-id"><b title="${esc(t.displayName)}">${text(t.displayName)}</b><small class="${t.named ? 'is-named' : ''}" title="${esc(state)}"><i class="tm-status-dot"></i>${esc(state)}</small></span>
          ${flag ? `<span class="tm-card-flag" title="${flag === '待命名' ? '在详情页命名后，全站队名同步更新' : '不足 3 局，只作参考'}">${flag}</span>` : ''}
        </header>
        ${meta || formDots ? `<div class="tm-card-meta">${meta ? `<span>${meta}</span>` : ''}${formDots ? `<span class="tm-form" role="img" aria-label="最近 ${recentGames.length} 局：${formText}" title="最近 ${recentGames.length} 局（新→旧）：${formText}">${formDots}</span>` : ''}</div>` : ''}
        <div class="tm-card-body">${rateBlock}<div class="tm-card-stats">${figures}</div></div>
      </a>
      <div class="tm-card-roster">
        <button type="button" class="tm-roster-toggle" data-team-roster-toggle aria-expanded="false" aria-controls="${rosterId}">
          <span>当前五人${filled ? ` · ${fmt(filled)}/5` : ''}</span><em>展开 ▾</em>
        </button>
        <div class="tm-roster-list" id="${rosterId}" hidden>${rosterRows}${former}</div>
      </div>
      <footer class="tm-card-foot">
        <a class="tm-card-open" href="${route('team', t.id)}">查看详情</a>
        <button type="button" class="tm-rename" data-team-rename="${esc(t.id)}" data-team-label="${esc(t.displayName)}" title="给这支战队命名">${t.named ? '改名' : '命名'}</button>
      </footer>
    </article>`;
  };
  const clearTeamSearch = (input) => {
    if (!input) return;
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  };
  /* 列表前端视图控制：搜索（队名/选手 ID）+ 状态胶囊 + 排序 + 计数。 */
  function syncTeamList(root) {
    if (!root) return;
    const rawQuery = root.querySelector('[data-team-search]')?.value || '';
    const q = rawQuery.trim().toLowerCase();
    const named = root.dataset.teamFilter || '';
    const sort = root.querySelector('[data-team-sort]')?.value || 'recent';
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
    writeTeamViewState({q: rawQuery.trim(), status: named === '1' ? 'named' : named === '0' ? 'pending' : '', sort});
  }
  function syncTeamSticky() {
    const sentinel = document.querySelector('.tm-command-sentinel');
    const command = sentinel?.nextElementSibling;
    if (!sentinel || !command || !command.classList.contains('tm-command')) return;
    command.classList.toggle('is-stuck', sentinel.getBoundingClientRect().top < 0);
  }
  const mapping = {enemy_team_id:'对手战队',session:'训练组',version:'版本',rules:'规则',pick_order:'选用顺序'};
  /* 并队前先对两套「当前五人」：对方转会 / 离队会让选手对不上，
     教练要能看出谁没再出场、谁是新加入的，再决定要不要合。 */
  function syncMergePreview(form) {
    if (!form) return;
    const box = form.querySelector('[data-merge-preview]');
    if (!box) return;
    const from = form.querySelector('select[name="from"]')?.selectedOptions?.[0];
    const into = form.querySelector('select[name="into"]')?.selectedOptions?.[0];
    const roster = (opt) => String(opt?.dataset.roster || '').split('、').map((x) => x.trim()).filter(Boolean);
    if (!from?.value || !into?.value) {
      box.innerHTML = '<p class="tm-merge-hint">选好来源和「合并至」，这里会先对一下两边的当前五人。</p>';
      return;
    }
    const a = roster(from), b = roster(into);
    const shared = a.filter((x) => b.includes(x));
    const onlyA = a.filter((x) => !b.includes(x));
    const onlyB = b.filter((x) => !a.includes(x));
    const warn = shared.length === 0
      ? '<p class="tm-merge-warn">两边没有共同选手。若只是交手过不同对手，请不要合并；确认是同一支战队大换血再继续。</p>' : '';
    box.innerHTML = `<div class="tm-merge-grid">
      <div><span>来源当前五人</span><b>${esc(a.join(' · ') || '—')}</b></div>
      <div><span>目标当前五人</span><b>${esc(b.join(' · ') || '—')}</b></div></div>
      <p class="tm-merge-hint">共同 ${fmt(shared.length)} 人 · 只在来源 ${fmt(onlyA.length)} 人（${esc(onlyA.join('、') || '无')}，可能已离队或转会）· 只在目标 ${fmt(onlyB.length)} 人（${esc(onlyB.join('、') || '无')}，新加入）</p>
      <p class="tm-merge-hint">合并只统一战队身份：当前阵容取最近 5 局各位置出场最多的人，历史选手留在「曾效力」，不会凑成 7–8 人的名单。选手真的转到别的队，请到「对手归属」改挂。</p>${warn}`;
  }
  function teamsPage(value, key, compare, bp, deep, behavior) {
    const teams = value.teams || [];
    if (key) return teamDetail(value, key, compare, bp, deep, behavior);
    const named = teams.filter((t) => t.named).length;
    const games = teams.reduce((sum, t) => sum + (t.matches || 0), 0);
    const wins = teams.reduce((sum, t) => sum + (t.wins || 0), 0);
    const losses = teams.reduce((sum, t) => sum + (t.losses || 0), 0);
    const thin = teams.filter((t) => (t.matches || 0) < 3).length;
    const latest = [...teams].sort((a, b) => String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')))[0];
    const lastSeen = latest ? String(latest.lastSeen || '') : '';
    const firstSeen = teams.map((t) => String(t.firstSeen || '')).filter(Boolean).sort()[0] || '';
    const teamDay = (value) => {
      const m = /^(\d{1,2})-(\d{1,2})/.exec(String(value || ''));
      return m ? new Date(2000, Number(m[1]) - 1, Number(m[2])).getTime() : null;
    };
    const dayStart = teamDay(firstSeen), dayEnd = teamDay(lastSeen);
    const spanDiff = dayStart != null && dayEnd != null
      ? (dayEnd < dayStart ? dayEnd + 365 * 86400000 - dayStart : dayEnd - dayStart) : null;
    const spanDays = spanDiff != null ? Math.max(1, Math.round(spanDiff / 86400000) + 1) : null;
    const span = spanDays ? `${spanDays} 天` : '—';
    const decided = wins + losses;
    const ownRate = decided ? wins / decided * 100 : null;
    const oppRate = decided ? losses / decided * 100 : null;
    const cards = [...teams].sort((a, b) => String(b.lastSeen || '').localeCompare(String(a.lastSeen || ''))
      || String(a.displayName || '').localeCompare(String(b.displayName || ''), 'zh'));
    const viewState = readTeamViewState();
    const statusValue = viewState.status === 'named' ? '1' : viewState.status === 'pending' ? '0' : '';
    const sortOptions = [['recent', '最近交手'], ['games', '交手最多'], ['rate', '本队胜率'], ['name', '队名']]
      .map(([value, label]) => `<option value="${value}"${viewState.sort === value ? ' selected' : ''}>${label}</option>`).join('');
    const toolbar = `<div class="tm-command">
      <div class="tm-search">${icon('search')}<input data-team-search value="${esc(viewState.q)}" placeholder="搜索战队名 / 选手 ID" aria-label="搜索战队" autocomplete="off" spellcheck="false"><button type="button" class="tm-search-clear" data-team-search-clear aria-label="清空搜索" title="清空搜索"${viewState.q ? '' : ' hidden'}>${icon('close')}</button></div>
      <div class="tm-seg" role="group" aria-label="命名状态">
        <button type="button" class="tm-seg-btn" data-team-chip="" aria-pressed="${statusValue === ''}">全部</button>
        <button type="button" class="tm-seg-btn" data-team-chip="1" aria-pressed="${statusValue === '1'}">已命名</button>
        <button type="button" class="tm-seg-btn" data-team-chip="0" aria-pressed="${statusValue === '0'}">待命名</button>
      </div>
      <label class="tm-sort"><span>排序</span><select data-team-sort aria-label="排序">${sortOptions}</select>${icon('chevron')}</label>
      <span class="tm-count" data-team-count aria-live="polite">共 ${fmt(teams.length)} 支</span>
    </div>`;
    const suggestions = (value.suggestions || []).map((s) => {
      const changed = s.kind === 'roster-change'
        ? ` · 换出 ${fmt(s.changedFrom || 0)} 人 / 加入 ${fmt(s.changedInto || 0)} 人（阵容更替）` : '';
      return `<li><b>${text(s.fromName || s.from || s.a)}</b> → <b>${text(s.intoName || s.toName || s.into || s.b)}</b><small>共同 ${text(s.overlap || '—')} 人${changed}</small><button type="button" class="tm-mini" data-merge-pick data-merge-from="${esc(s.from || '')}" data-merge-into="${esc(s.into || '')}">选中</button></li>`;
    }).join('');
    const mergeSection = `<section class="section tm-merge-section">
      <details class="tm-merge-fold"${suggestions ? ' open' : ''}>
        <summary>
          <span class="tm-merge-copy"><b>先合并同一支战队</b><em>对方换人、转会或离队后可能被认成几支。先并成一支，再去下面命名；改成相同名字不会自动合并。</em></span>
          <i aria-hidden="true"></i>
        </summary>
        <div class="tm-tools">${form('merge',
          select('来源战队', 'from', options(teams)) + select('合并至', 'into', options(teams))
          + '<div class="tm-merge-preview" data-merge-preview><p class="tm-merge-hint">选好来源和「合并至」，这里会先对一下两边的当前五人。</p></div>',
          '合并战队')}</div>
        ${suggestions ? `<div class="tm-suggest-wrap"><h3>可能是同一支战队</h3><ul class="tm-suggest">${suggestions}</ul></div>` : ''}
      </details>
    </section>`;
    const kpis = `<div class="tm-kpis">
      <div class="tm-kpi is-primary"><span class="tm-kpi-label">识别对手</span><strong>${fmt(teams.length)} 支</strong><span class="tm-kpi-note">已命名 ${fmt(named)} · 待命名 ${fmt(teams.length - named)}</span></div>
      <div class="tm-kpi"><span class="tm-kpi-label">交手局数</span><strong>${fmt(games)} 局</strong><div class="tm-kpi-split" aria-hidden="true"><i class="is-win" style="width:${games ? wins / games * 100 : 0}%"></i><i class="is-loss" style="width:${games ? losses / games * 100 : 0}%"></i></div><span class="tm-kpi-note">${fmt(wins)} 胜 ${fmt(losses)} 负</span></div>
      <div class="tm-kpi"><span class="tm-kpi-label">对手交手胜率</span><strong>${pct(oppRate)}</strong><span class="tm-kpi-note">本队 ${pct(ownRate)}</span></div>
      <div class="tm-kpi"><span class="tm-kpi-label">时间跨度</span><strong>${span}</strong><span class="tm-kpi-note">${firstSeen && lastSeen ? `${esc(firstSeen)} → ${esc(lastSeen)}` : '—'}</span></div>
      <div class="tm-kpi"><span class="tm-kpi-label">样本覆盖</span><strong>${thin ? `${fmt(thin)} 支偏少` : '全部 ≥3 局'}</strong><span class="tm-kpi-note">${thin ? '交手少，只作参考' : '可做队间比较'}</span></div>
    </div>`;
    return withPage('战队分析',
      '对手战队由营地阵容聚类识别 · 点卡片进详情，命名后对局档案、系列赛与跨局分析一起更新。',
      kpis
      + mergeSection
      + block('对手目录', '按最近交手排序。卡上留交手、对手胜率、场均推塔与近 5 局，不合成综合得分；「当前五人」可展开。',
        `<div class="tm-command-sentinel" aria-hidden="true"></div>${toolbar}<div class="tm-grid" data-team-results>${cards.map((t) => tmCard(t, value.own)).join('')}<p class="tm-empty" data-team-empty hidden>没有符合条件的战队。<button type="button" class="tm-empty-reset" data-team-reset>清空筛选</button></p>${teams.length ? '' : empty('当前没有识别到对手战队。')}</div>`,
        '', 'data-tm-directory data-team-filter="' + statusValue + '"'), false);
  }
  /* ── 战队详情 v3（2026-11-14）──────────────────────────────────────
     对齐首页（#overview）的设计参数：1180 容器、18px 段落标题、13px 正文、
     12px 圆角与单一阴影；内容按「总览 → 打法 → 英雄与 BP → 阵容体系 →
     对位与证据」五段整合：结论在前、图表在中、明细收进折叠。
     只消费接口字段（studio/teams、studio/camp-compare、v3/team-bp、
     v3/team-deep、v3/team-behavior），前端不另算风格分、筛选不发新请求。 */
  const TP_WINDOWS = [['7', '7 天'], ['15', '15 天'], ['30', '30 天'], ['all', '全部']];
  const TP_QUADS = [
    ['单核进攻', '经济给一个核心，由核心带前中期进攻'],
    ['多点进攻', '多个位置有威胁，找不同位置的机会'],
    ['保核运营', '围绕主要输出点发育，靠兵线与资源接团'],
    ['多线牵制', '多个位置吃资源与边线，靠转线换节奏'],
  ];
  const TD_QUAD_DESC = {
    '单核进攻': '经济集中给一个核心，由核心带动前中期进攻',
    '多点进攻': '多个位置有威胁，找不同位置的机会',
    '保核运营': '围绕主要输出点发育，靠兵线与资源找接团机会',
    '多线牵制': '多个位置承担资源与边线任务',
  };
  const TD_DUEL_METRICS = {
    '对抗路': [['分均承伤', 'dtpm'], ['参团率', 'participation'], ['场均推塔', 'towersPerGame'], ['分均经济', 'gpm']],
    '打野': [['分均经济', 'gpm'], ['参团率', 'participation'], ['场均击杀参与', 'killPart'], ['队伍控龙', 'teamDragons']],
    '中路': [['分均输出', 'dpm'], ['分均经济', 'gpm'], ['参团率', 'participation']],
    '发育路': [['分均经济', 'gpm'], ['分均输出', 'dpm'], ['参团率', 'participation']],
    '游走': [['分均承伤', 'dtpm'], ['参团率', 'participation'], ['分均控制', 'controlPerMin'], ['分均治疗', 'healPerMin']],
  };
  const LU_FAMILY_NOTES = {
    '边野': '前排职责 / 野区资源 / 切入能力', '中野': '伤害核心 / 控制配置与节奏',
    '射辅': '保人配置 / 射手输出环境', '中辅': '控制与输出衔接 / 游走职责', '野辅': '野区联动 / 反开保护',
    '中野辅': '节奏发起 / 控制与爆发衔接', '边野辅': '前排 / 切入 / 支援',
    '中射辅': '双核配置 / 保护与持续输出', '野射辅': '双核资源 / 保护分工', '边中野': '伤害结构 / 带线与核心配置',
  };
  const tdShareOf = (val, total) => hasNum(val) && hasNum(total) && total > 0 ? val / total * 100 : null;
  const tdAvgOf = (val, n) => hasNum(val) && hasNum(n) && n > 0 ? val / n : null;
  const tdGapText = (opp, own, digits = 0, unit = '') => {
    if (!hasNum(opp) || !hasNum(own)) return '证据不足';
    const gap = opp - own;
    const scale = Math.max(Math.abs(opp), Math.abs(own));
    /* 相对差 <1% 视为噪声（四舍五入后两个数字看起来一样，写「多 7」只会误导）。 */
    if (Math.abs(gap) <= (digits ? 0.05 : 0.5) || (scale > 0 && Math.abs(gap) / scale < 0.01)) return '持平';
    return `${gap > 0 ? '对手多' : '本队多'} ${fmt(Math.abs(gap), digits)}${unit}`;
  };
  const tdPoolText = (hhi) => !hasNum(hhi) ? '证据不足' : hhi <= 0.26 ? '不偏科' : hhi <= 0.42 ? '略偏科' : '很偏科';
  const tdDayNum = (day) => {
    const m = /^(\d{1,2})-(\d{1,2})/.exec(String(day || ''));
    return m ? new Date(2000, Number(m[1]) - 1, Number(m[2])).getTime() : null;
  };
  const tdInWindow = (day, anchor, days) => {
    if (days === 'all') return true;
    const d = tdDayNum(day), a = tdDayNum(anchor);
    if (d == null || a == null) return false;
    return d <= a && a - d <= days * 86400000;
  };
  const tdDuelText = (key, val) => {
    if (!hasNum(val)) return '—';
    if (key === 'participation') return pct(val);
    if (key === 'controlPerMin' || key === 'killPart' || key === 'towersPerGame') return fmt(val, 1);
    return fmt(val, 0);
  };
  const tdMetricText = (key, val) => {
    if (!hasNum(val)) return '—';
    if (key === 'participation') return pct(val);
    if (key === 'goldPerGame' || key === 'dpm' || key === 'dtpm') return tmK(val);
    if (key === 'killsPerGame' || key === 'towersPerGame' || key === 'dragonsPerGame' || key === 'killPart' || key === 'controlPerMin') return fmt(val, 1);
    return fmt(val, 0);
  };
  const kplOppRate = (hit) => hasNum(hit?.oppWinRate) ? hit.oppWinRate : (hasNum(hit?.oppGames) && hit.oppGames > 0 && hasNum(hit?.oppWins) ? hit.oppWins / hit.oppGames * 100 : null);
  const TD_STATE_KEYS = {likesLane: 'tdLikesLane', window: 'tdWindow'};
  const TP_QW = 620, TP_QH = 320, TP_QPAD = {l: 46, r: 20, t: 28, b: 44};
  const tpQx = (v) => TP_QPAD.l + Math.max(0, Math.min(100, v)) / 100 * (TP_QW - TP_QPAD.l - TP_QPAD.r);
  const tpQy = (v) => TP_QH - TP_QPAD.b - Math.max(0, Math.min(100, v)) / 100 * (TP_QH - TP_QPAD.t - TP_QPAD.b);
  const tpQuadBg = () => {
    const rect = (x1, y1, x2, y2, cls) => `<rect x="${tpQx(x1).toFixed(1)}" y="${tpQy(y2).toFixed(1)}" width="${(tpQx(x2) - tpQx(x1)).toFixed(1)}" height="${(tpQy(y1) - tpQy(y2)).toFixed(1)}" class="tp-qbg ${cls}"/>`;
    return rect(0, 50, 50, 100, 'is-tl') + rect(50, 50, 100, 100, 'is-tr') + rect(0, 0, 50, 50, 'is-bl') + rect(50, 0, 100, 50, 'is-br');
  };
  const tpQuadSvg = (inner, aria = '团队风格四象限', counts = null) => `<svg class="tp-quad" viewBox="0 0 ${TP_QW} ${TP_QH}" role="img" aria-label="${esc(aria)}">${tpQuadBg()}
    <line x1="${tpQx(50).toFixed(1)}" y1="${tpQy(100).toFixed(1)}" x2="${tpQx(50).toFixed(1)}" y2="${tpQy(0).toFixed(1)}" class="tp-qaxis"/>
    <line x1="${tpQx(0).toFixed(1)}" y1="${tpQy(50).toFixed(1)}" x2="${tpQx(100).toFixed(1)}" y2="${tpQy(50).toFixed(1)}" class="tp-qaxis"/>
    <text x="${tpQx(2).toFixed(1)}" y="${tpQy(96).toFixed(1)}" class="tp-qcorner">单核进攻${counts ? ` · ${fmt(counts['单核进攻'] || 0)}` : ''}</text>
    <text x="${tpQx(98).toFixed(1)}" y="${tpQy(96).toFixed(1)}" text-anchor="end" class="tp-qcorner">多点进攻${counts ? ` · ${fmt(counts['多点进攻'] || 0)}` : ''}</text>
    <text x="${tpQx(2).toFixed(1)}" y="${tpQy(4).toFixed(1)}" class="tp-qcorner">保核运营${counts ? ` · ${fmt(counts['保核运营'] || 0)}` : ''}</text>
    <text x="${tpQx(98).toFixed(1)}" y="${tpQy(4).toFixed(1)}" text-anchor="end" class="tp-qcorner">多线牵制${counts ? ` · ${fmt(counts['多线牵制'] || 0)}` : ''}</text>
    <text x="${(TP_QW / 2).toFixed(1)}" y="${TP_QH - 8}" class="tp-qaxis-label" text-anchor="middle">经济分配：单核 ←→ 多核</text>
    <text x="12" y="${(TP_QH / 2).toFixed(1)}" transform="rotate(-90 12 ${(TP_QH / 2).toFixed(1)})" class="tp-qaxis-label" text-anchor="middle">打架 ←→ 运营</text>
    ${inner}</svg>`;
  const tpChips = (group, items, active) => `<div class="tp-chips" role="group">${items.map(([value, label]) => `<button type="button" class="tp-chip" data-td-chip="${esc(group)}" data-td-value="${esc(value)}" aria-pressed="${value === active}">${esc(label)}</button>`).join('')}</div>`;
  const tpHeroLaneChips = () => tpChips('likesLane', [['all', '全部'], ...TM_LANES.map((lane) => [lane, lane])], 'all');
  const tpWindowChips = () => tpChips('window', TP_WINDOWS, '30');
  const tpLack = (note) => `<p class="tp-lack">证据不足 · ${esc(note)}</p>`;
  /* 页内筛选：全部在已加载数据上做，不发新请求。 */
  function syncTdChips(root, group) {
    if (!root || !group) return;
    const stateKey = TD_STATE_KEYS[group];
    const value = (stateKey && root.dataset[stateKey]) || (group === 'window' ? '30' : 'all');
    root.querySelectorAll(`[data-td-chip="${group}"]`).forEach((el) => el.setAttribute('aria-pressed', String((el.dataset.tdValue || 'all') === value)));
    if (group === 'likesLane') {
      root.querySelectorAll('[data-tp-hero-lane]').forEach((el) => { el.hidden = value !== 'all' && el.dataset.tpHeroLane !== value; });
      return;
    }
    if (group === 'window') {
      root.querySelectorAll('[data-td-window-panel]').forEach((el) => { el.hidden = el.dataset.tdWindowPanel !== value; });
      root.querySelectorAll('[data-td-window-dot]').forEach((el) => {
        const inWindow = value === 'all' || String(el.dataset.tdWindowDot || '').split(' ').includes(value);
        el.classList.toggle('is-off', !inWindow);
      });
    }
  }
  function teamDetail(value, key, compareData, bpData, deepData, behaviorData) {
    const teams = value.teams || [];
    const t = teams.find((x) => x.id === key);
    if (!t) return withPage('战队分析', '未找到这支战队。', empty('这支战队可能已被合并。'), false);
    const cmp = compareData || {};
    const deep = deepData && (deepData.team || deepData.games) ? deepData : null;
    const meta = {...t, ...(deep?.team || {})};
    const own = {...(value.own || {}), ...(deep?.own || {})};
    const oppName = meta.displayName || '对手';
    const ownName = own.name || '本队';
    const games = [...(meta.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const deepGames = [...(deep?.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const matches = meta.matches || games.length || 0;
    const thin = matches < 3;
    const durations = games.map((g) => g.duration).filter((v) => hasNum(v) && v > 0);
    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    const oppRate = tmOppRate(meta);
    const cmpGames = Math.max(1, cmp.games || games.length || 1);
    const oppStyle = deep?.style || meta.style || null;
    const ownStyle = deep?.own?.style || value.own?.style || null;
    const styleMain = oppStyle?.main || null;
    const styleWin30 = oppStyle?.windows?.['30'] || oppStyle?.windows?.all || null;
    const styleCounts = oppStyle?.windows?.['30']?.counts || oppStyle?.windows?.all?.counts || null;
    const styleAnchor = oppStyle?.anchor || String(meta.lastSeen || '').slice(0, 5);
    const bpTeam = (bpData?.teams || []).find((x) => x.id === t.id);
    const lineups = deep?.lineups || null;
    const nEff = lineups?.nEff || 0;
    const luWrText = (row) => {
      const decided = (row.wins || 0) + (row.losses || 0);
      const sample = `${fmt(row.games || decided)} 局 · ${fmt(row.wins || 0)} 胜 ${fmt(row.losses || 0)} 负`;
      if (!(nEff >= 10) || decided < 3 || row.wr == null) return `<span class="tp-wr-sample" title="${esc(sample)}">${esc(sample)}</span>`;
      return `<b title="${esc(sample)}">${pct(row.wr)}</b><span class="tp-sample">${fmt(row.games || decided)} 局</span>`;
    };
    const gameBySeq = new Map(deepGames.map((g) => [String(g.seq), g]));
    /* ── 基础聚合：队伍口径优先取逐局终局面板（deep），再用 camp-compare 兜底 ── */
    const deepStat = (side, field) => {
      if (!deepGames.length) return null;
      const values = deepGames.map((g) => g.sides?.[side]?.stats?.[field]).filter(hasNum);
      return values.length ? values.reduce((a, b) => a + b, 0) : null;
    };
    const deepPlayers = (side) => deepGames.flatMap((g) => g.sides?.[side]?.players || []);
    const deepAgg = (side) => {
      const players = deepPlayers(side);
      if (!players.length) return null;
      const sum = (key) => players.reduce((s, p) => s + (hasNum(p[key]) ? p[key] : 0), 0);
      const seconds = deepGames.reduce((s, g) => s + (hasNum(g.duration) ? g.duration : 0), 0);
      return {games: deepGames.length, seconds, gold: sum('gold'), kills: sum('kills'), deaths: sum('deaths'), assists: sum('assists'), towers: sum('towers'), heroDamage: sum('heroDamage'), taken: sum('taken')};
    };
    const laneRows = (cmp.lanes || []).filter((row) => row.own || row.enemy);
    const laneAggregate = (side) => TM_LANES.map((lane) => {
      const group = deepPlayers(side).filter((p) => (p.lane || '位置未知') === lane);
      if (!group.length) return {lane, row: null};
      const sum = (key) => group.reduce((s, p) => s + (hasNum(p[key]) ? p[key] : 0), 0);
      const parts = group.map((p) => p.participation).filter(hasNum);
      const partValue = parts.length ? parts.reduce((a, b) => a + b, 0) / parts.length * (parts[0] <= 1 ? 100 : 1) : null;
      return {lane, row: {lane, name: group[0].name, games: group.length, gold: sum('gold'), heroDamage: sum('heroDamage'), taken: sum('taken'), kills: sum('kills'), deaths: sum('deaths'), assists: sum('assists'), towers: sum('towers'), control: sum('control'), heal: sum('heal'), participation: partValue, minutes: sum('minutes')}};
    });
    const deepLaneRows = (() => {
      if (!deepGames.length) return [];
      const ownRows = laneAggregate('own'), enemyRows = laneAggregate('enemy');
      return TM_LANES.map((lane) => ({lane, own: (ownRows.find((r) => r.lane === lane) || {}).row || null, enemy: (enemyRows.find((r) => r.lane === lane) || {}).row || null})).filter((row) => row.own || row.enemy);
    })();
    /* 逐局面板覆盖的局数 ≥ camp-compare 时才用逐局口径，避免 1 局聚合冒充 25 局。 */
    const lanes = (deepLaneRows.length && deepGames.length >= cmpGames) ? deepLaneRows
      : laneRows.map((row) => ({lane: row.lane || '位置未知', own: row.own || null, enemy: row.enemy || null}));
    const laneNormal = (raw, fallbackGames = laneSourceGames) => {
      if (!raw) return null;
      const gamesN = hasNum(raw.games) && raw.games > 0 ? raw.games : fallbackGames;
      const seconds = hasNum(raw.seconds) ? raw.seconds : null;
      const minutes = seconds && seconds > 0 ? seconds / 60 : (hasNum(raw.minutes) && raw.minutes > 0 ? raw.minutes : (avgDuration ? avgDuration * gamesN / 60 : null));
      const perGame = (value) => hasNum(value) ? value / gamesN : null;
      const perMin = (value) => hasNum(value) && minutes ? value / minutes : null;
      return {
        name: raw.name, games: gamesN,
        gold: raw.gold, heroDamage: hasNum(raw.heroDamage) ? raw.heroDamage : raw.damage, taken: raw.taken,
        gpm: hasNum(raw.gpm) ? raw.gpm : perMin(raw.gold),
        dpm: hasNum(raw.dpm) ? raw.dpm : perMin(hasNum(raw.heroDamage) ? raw.heroDamage : raw.damage),
        dtpm: hasNum(raw.dtpm) ? raw.dtpm : perMin(raw.taken),
        participation: hasNum(raw.participation) ? raw.participation : null,
        towersPerGame: hasNum(raw.towersPerGame) ? raw.towersPerGame : perGame(raw.towers),
        killPart: hasNum(raw.killPart) ? raw.killPart : (hasNum(raw.kills) || hasNum(raw.assists) ? (raw.kills || 0) + (raw.assists || 0) : null),
        controlPerMin: hasNum(raw.controlPerMin) ? raw.controlPerMin : perMin(raw.control),
        healPerMin: hasNum(raw.healPerMin) ? raw.healPerMin : perMin(raw.heal),
      };
    };
    /* 分路行的局数决定「场均」分母：逐局口径用逐局局数，不能用 camp-compare 的局数。 */
    const laneSourceGames = (deepLaneRows.length && deepGames.length >= cmpGames) ? deepGames.length : cmpGames;
    const laneAgg = (side) => {
      const rows = lanes.map((row) => row[side]).filter(Boolean);
      if (!rows.length) return null;
      const sum = (key) => rows.reduce((s, r) => s + (hasNum(r[key]) ? r[key] : 0), 0);
      return {rows, games: laneSourceGames, seconds: sum('seconds'), gold: sum('gold'), kills: sum('kills'), deaths: sum('deaths'), assists: sum('assists'), towers: sum('towers'), heroDamage: rows.some((r) => hasNum(r.heroDamage)) ? sum('heroDamage') : sum('damage'), taken: sum('taken')};
    };
    const oppAgg = laneAgg('enemy') || deepAgg('enemy');
    const ownAgg = laneAgg('own') || deepAgg('own');
    const sideMetrics = (agg, side) => {
      const gamesN = hasNum(agg?.games) && agg.games > 0 ? agg.games : (deepGames.length || cmpGames);
      const minutes = hasNum(agg?.seconds) && agg.seconds > 0
        ? agg.seconds / 60
        : (deepGames.length ? deepGames.reduce((s, g) => s + (hasNum(g.duration) ? g.duration : 0), 0) / 60 : (avgDuration ? avgDuration * gamesN / 60 : null));
      const deepGold = deepStat(side, 'gold'), deepKills = deepStat(side, 'kills');
      const deepTowers = deepStat(side, 'towers'), deepDragons = deepStat(side, 'dragons');
      const gold = hasNum(deepGold) ? deepGold : agg?.gold;
      const kills = hasNum(deepKills) ? deepKills : agg?.kills;
      const towers = hasNum(deepTowers) ? deepTowers : agg?.towers;
      if (!hasNum(gold) && !hasNum(kills) && !hasNum(towers) && !agg) return null;
      return {
        games: gamesN,
        goldPerGame: tdAvgOf(gold, gamesN),
        killsPerGame: tdAvgOf(kills, gamesN),
        towersPerGame: tdAvgOf(towers, gamesN),
        dragonsPerGame: hasNum(deepDragons) ? tdAvgOf(deepDragons, gamesN) : null,
        dpm: minutes && hasNum(agg?.heroDamage) ? agg.heroDamage / minutes : null,
        dtpm: minutes && hasNum(agg?.taken) ? agg.taken / minutes : null,
      };
    };
    const oppMetrics = sideMetrics(oppAgg, 'enemy');
    const ownMetrics = sideMetrics(ownAgg, 'own');
    const shareMap = (side, field) => {
      const values = lanes.map((row) => hasNum(row[side]?.[field]) ? row[side][field] : (field === 'heroDamage' ? row[side]?.damage : null));
      const total = values.reduce((s, v) => s + (hasNum(v) ? v : 0), 0);
      const map = new Map();
      lanes.forEach((row, index) => map.set(row.lane, tdShareOf(values[index], total)));
      return map;
    };
    const heroPick = (side) => {
      const map = new Map();
      for (const g of deepGames) {
        const oppWon = g.opponentWin === true || (g.opponentWin == null && g.win === false);
        for (const p of (g.sides?.[side]?.picks || [])) {
          if (!p || !p.name) continue;
          const item = map.get(p.name + '|' + (p.lane || '')) || {hero: p.name, lane: p.lane || '', archetype: p.archetype || '', games: 0, wins: 0, icon: p.icon};
          item.games++;
          if (side === 'enemy' ? oppWon : !oppWon) item.wins++;
          map.set(p.name + '|' + (p.lane || ''), item);
        }
      }
      return [...map.values()].sort((a, b) => b.games - a.games || String(a.hero).localeCompare(String(b.hero), 'zh'));
    };
    const oppPicksDeep = heroPick('enemy');
    const ownPicksDeep = heroPick('own');
    const fallbackEnemyHeroes = [...(cmp.heroes?.enemy || [])].sort((a, b) => (b.games || 0) - (a.games || 0) || String(a.hero || '').localeCompare(String(b.hero || ''), 'zh'));
    const oppPicks = oppPicksDeep.length ? oppPicksDeep : fallbackEnemyHeroes.map((h) => ({hero: h.hero, lane: h.lane || '', archetype: '', games: h.games || 0, wins: null, icon: h.icon}));
    const ownHeroGames = new Map();
    for (const p of ownPicksDeep) ownHeroGames.set(p.hero, (ownHeroGames.get(p.hero) || 0) + p.games);
    for (const h of (cmp.heroes?.own || [])) if (!ownHeroGames.has(h.hero)) ownHeroGames.set(h.hero, h.games || 0);
    const laneArchetype = (game, side) => {
      const byLane = {};
      for (const p of (game.sides?.[side]?.picks || [])) if (p.lane && p.archetype) byLane[p.lane] = p.archetype;
      return byLane;
    };
    const comboStats = (side, laneA, laneB) => {
      const map = new Map();
      let total = 0;
      for (const g of deepGames) {
        const by = laneArchetype(g, side);
        if (!by[laneA] || !by[laneB]) continue;
        total++;
        const key = [by[laneA], by[laneB]].join(' + ');
        map.set(key, (map.get(key) || 0) + 1);
      }
      return {total, rows: [...map.entries()].map(([key, count]) => ({key, count})).sort((a, b) => b.count - a.count)};
    };
    const topLaneOf = (shares) => lanes.map((row) => ({lane: row.lane, share: shares.get(row.lane)})).filter((x) => hasNum(x.share)).sort((a, b) => b.share - a.share)[0] || null;
    const goldShareOwn = shareMap('own', 'gold');
    const goldShareOpp = shareMap('enemy', 'gold');
    const damageShareOpp = shareMap('enemy', 'heroDamage');
    const damageShareOwn = shareMap('own', 'heroDamage');
    const takenShareOpp = shareMap('enemy', 'taken');
    const takenShareOwn = shareMap('own', 'taken');
    const oppGoldTop = topLaneOf(goldShareOpp);
    const ownGoldTop = topLaneOf(goldShareOwn);
    /* ── 通用小件 ───────────────────────────────────────────────── */
    const tpCard = (title, meta2, body, cls = '') => `<article class="tp-card${cls ? ' ' + cls : ''}"><header class="tp-card-head"><h3>${title}</h3>${meta2 ? `<span>${meta2}</span>` : ''}</header>${body}</article>`;
    const isUnlabeled = (name) => !name || name === '待分类' || name === '未标注';
    const typeText = (name) => isUnlabeled(name) ? '未标注' : name;
    const tpTypeText = (types) => `<span class="tp-typetext">${(types || []).map((name) => `<span${isUnlabeled(name) ? ' class="is-unlabeled"' : ''}>${esc(typeText(name))}</span>`).join('')}</span>`;
    /* 头像数量多、体积小，直接加载；懒加载会让快速滚动时出现空白方块。 */
    const heroImg = (hero, cls) => portrait(hero, cls).replace(' loading="lazy"', '');
    const heroLink = (hero, count, cls = '') => `<a class="tp-hero${cls ? ' ' + cls : ''}" href="${route('hero', hero)}" title="打开英雄 ${esc(hero)} 详情">${heroImg(hero, 'is-hero')}<span>${esc(hero)}</span>${hasNum(count) ? `<small>${fmt(count)}</small>` : ''}</a>`;
    const heroFace = (hero, cls = '') => `<a class="tp-face${cls ? ' ' + cls : ''}" href="${route('hero', hero)}" title="${esc(hero)}">${heroImg(hero, 'is-face')}</a>`;
    const heroFaces = (heroes, cls = '') => `<span class="tp-faces${cls ? ' ' + cls : ''}">${(heroes || []).map((hero) => heroFace(hero)).join('')}</span>`;
    const tpGamesRef = (refs, limit = 8) => {
      const list = refs || [];
      if (!list.length) return '';
      if (list.length === 1) {
        const g = gameBySeq.get(String(list[0]));
        return g?.matchKey ? `<a class="tp-row-link" href="${route('match', g.matchKey)}" title="打开单局复盘">复盘 ↗</a>` : '';
      }
      const chips = list.slice(0, limit).map((seq) => {
        const g = gameBySeq.get(String(seq));
        const label = g ? `${text(g.day || g.start || `#${seq}`)}` : `#${text(seq)}`;
        return g?.matchKey ? `<a class="tp-ref-chip" href="${route('match', g.matchKey)}">${label}</a>` : `<span class="tp-ref-chip">${label}</span>`;
      }).join('');
      const more = list.length > limit ? `<span class="tp-ref-more">+${fmt(list.length - limit)}</span>` : '';
      return `<details class="tp-ref"><summary>逐局</summary><div class="tp-ref-list">${chips}${more}</div></details>`;
    };
    const tpStack = (shares, laneList = lanes) => `<div class="tp-stack">${laneList.map((row, index) => {
      const share = shares.get(row.lane);
      return `<span class="tp-seg tp-lane-${index}" style="flex:${hasNum(share) ? Math.max(share, 0.4).toFixed(2) : 0} 0 0" title="${esc(row.lane)} ${pct(share)}">${hasNum(share) && share >= 12 ? Math.round(share) + '%' : ''}</span>`;
    }).join('')}</div>`;
    const tpStackLegend = () => `<div class="tp-stack-legend">${lanes.map((row, index) => `<span><i class="tp-lane-${index}"></i>${esc(row.lane)}</span>`).join('')}</div>`;
    /* ── 头部：身份、样本、当前五人 ─────────────────────────────── */
    const tagList = [];
    const addTag = (ok, label, cls) => { if (ok) tagList.push({label, cls}); };
    addTag(thin, '样本不足', 'sample');
    addTag(matches >= 3 && (oppRate ?? -1) >= 60, '交手下风', 'weak');
    addTag(matches >= 3 && (oppRate ?? 101) <= 40, '交手占优', 'strong');
    addTag(meta.named, '已命名', 'neutral');
    addTag(!!meta.coach, '教练 ' + (meta.coach || ''), 'neutral');
    if (tagList.length === 1) tagList.push({label: '待观察', cls: 'neutral'});
    const currentPlayers = meta.currentPlayers || meta.players || [];
    const lanePlayers = byLaneTm(currentPlayers).slice(0, 5);
    const formerPlayers = meta.formerPlayers || [];
    const rotationPlayers = meta.rotationPlayers || [];
    const rosterStrip = `<div class="tp-roster" aria-label="当前五人">${TM_LANES.map((lane) => {
      const player = lanePlayers.find((p) => p.lane === lane) || currentPlayers.find((p) => p.lane === lane);
      return `<span class="tp-player${player ? '' : ' is-empty'}"><i>${esc((player?.name || '?').slice(0, 1))}</i><span><small>${esc(lane)}</small><b>${esc(player?.name || '待补')}</b></span><em>${player ? `${fmt(player.games || 0)} 局` : '—'}</em></span>`;
    }).join('')}</div>`;
    const headStats = [
      ['交手', `${fmt(matches)} 局`],
      ['本队战绩', tmRecord(meta)],
      ['对手胜率', pct(oppRate)],
      ['场均时长', time(avgDuration)],
      ['最近交手', text(meta.lastSeen)],
    ];
    if (thin) headStats[2][0] = '对手胜率（单局）';
    const head = `<header class="tp-head">
      <div class="tp-head-bar">
        <a class="tp-back" href="#teams">← 战队分析</a>
        <div class="tp-head-actions">
          <button type="button" class="tp-btn" data-team-rename="${esc(t.id)}" data-team-label="${esc(t.displayName)}">${t.named ? '改名' : '命名'}</button>
          <button type="button" class="tp-btn" data-tp-copy data-tp-summary="__TP_SUMMARY__">复制摘要</button>
          <button type="button" class="tp-btn" data-action="refresh">刷新</button>
        </div>
      </div>
      <div class="tp-id">
        <span class="tp-crest" aria-hidden="true">${esc((oppName || '?').slice(0, 1))}</span>
        <div class="tp-id-copy">
          <span class="tp-eyebrow">对手档案 / TEAM DOSSIER</span>
          <h1>${text(oppName)}</h1>
          <p>营地阵容聚类 · 首次 ${text(meta.firstSeen)} · 最近 ${text(meta.lastSeen)}</p>
        </div>
        <div class="tp-tags">${tagList.slice(0, 5).map((x) => `<span class="tp-tag is-${x.cls}">${esc(x.label)}</span>`).join('')}</div>
      </div>
      <dl class="tp-facts">${headStats.map(([label, val]) => `<div><dt>${esc(label)}</dt><dd>${val}</dd></div>`).join('')}</dl>
      ${rosterStrip}
      <div class="tp-roster-note"><span>当前五人取最近 ${fmt(meta.rosterWindow || 5)} 局各位置出场最多的人${rotationPlayers.length ? ` · 本期轮换 ${fmt(rotationPlayers.length)} 人` : ''}。</span>${formerPlayers.length ? `<details class="tp-former"><summary>曾效力 ${fmt(formerPlayers.length)} 人</summary><span>${formerPlayers.slice(0, 30).map((p) => `${esc(p.name || p.id)}（${esc(p.lane || '位置未知')}，${fmt(p.games || 0)} 局）`).join('、')}${formerPlayers.length > 30 ? ` …另有 ${fmt(formerPlayers.length - 30)} 人` : ''}</span></details>` : ''}</div>
      <p class="tp-scope">本页口径：全部营地面板，不随顶栏日期 / 来源筛选变化 · 无时间轴 · 手序含模板假设</p>
    </header>`;
    /* ── 一句话画像 ─────────────────────────────────────────────── */
    const coreLine = oppGoldTop ? `经济份额最高的是${esc(oppGoldTop.lane)}（${pct(oppGoldTop.share)}）` : '分路经济还没有可用明细';
    const quadRanked = (() => {
      if (!styleCounts) return null;
      const ranked = TP_QUADS.map(([name]) => [name, styleCounts[name] || 0]).sort((a, b) => b[1] - a[1]);
      return ranked[0][1] > 0 ? ranked[0] : null;
    })();
    const styleLine = styleMain?.quadrant
      ? `整体偏「${esc(styleMain.quadrant)}」`
      : styleMain?.sufficient && quadRanked
        ? `四象限分散，${esc(quadRanked[0])}最多（${fmt(quadRanked[1])} 局）`
        : quadRanked ? `单局落在「${esc(quadRanked[0])}」一侧` : '打法倾向证据不足';
    const pickLine = oppPicks.length ? `常拿 ${oppPicks.slice(0, 3).map((p) => esc(p.hero)).join(' / ')}` : '';
    const briefLine = `${fmt(matches)} 局样本：${coreLine}，${styleLine}${pickLine ? `；${pickLine}` : ''}。`;
    const briefNote = `对手胜率 ${pct(oppRate)} · 场均 ${time(avgDuration)} · 最近 ${text(meta.lastSeen)}。`;
    const brief = `<section class="tp-brief" aria-label="阶段性观察">
      <span class="tp-brief-label">阶段性观察</span>
      <div class="tp-brief-body"><p class="tp-brief-line">${briefLine}</p><p class="tp-brief-note">${briefNote} 只是描述汇总，不构成结论。</p></div>
    </section>`;
    /* ── 01 总览：整体对照 + 近期交手 ───────────────────────────── */
    const ovDefs = [
      ['场均经济', 'goldPerGame', 0], ['场均击杀', 'killsPerGame', 1], ['场均推塔', 'towersPerGame', 1],
      ['场均控龙', 'dragonsPerGame', 1], ['分均输出', 'dpm', 0], ['分均承伤', 'dtpm', 0],
    ];
    const cmpRows = ovDefs.map(([label, metricKey, digits]) => {
      const oppValue = oppMetrics?.[metricKey] ?? null;
      const ownValue = ownMetrics?.[metricKey] ?? null;
      const max = Math.max(1, hasNum(oppValue) ? oppValue : 0, hasNum(ownValue) ? ownValue : 0);
      return `<div class="tp-cmp-row">
        <span class="tp-cmp-label">${esc(label)}</span>
        <b class="tp-cmp-val is-opp">${tdMetricText(metricKey, oppValue)}</b>
        <span class="tp-cmp-track is-opp"><i style="width:${hasNum(oppValue) ? Math.min(100, oppValue / max * 100).toFixed(1) : 0}%"></i></span>
        <span class="tp-cmp-track is-own"><i style="width:${hasNum(ownValue) ? Math.min(100, ownValue / max * 100).toFixed(1) : 0}%"></i></span>
        <b class="tp-cmp-val is-own">${tdMetricText(metricKey, ownValue)}</b>
        <em class="tp-cmp-gap">${tdGapText(oppValue, ownValue, digits)}</em>
      </div>`;
    }).join('');
    const overviewCard = tpCard('整体对照', '同批营地面板 · 条形只表示两队相对高低', `<div class="tp-cmp-head"><span></span><span class="is-opp">对手</span><span></span><span></span><span class="is-own">本队</span><span></span></div>${cmpRows}`);
    const formGames = games.slice(0, 12).reverse();
    const formSquares = formGames.map((g) => `<i class="tp-sq ${g.win === true ? 'is-win' : g.win === false ? 'is-loss' : 'is-unknown'}" title="${esc(`${g.start || ''} · ${g.win === true ? '本队胜' : g.win === false ? '对手胜' : '结果未知'}`)}"></i>`).join('');
    const last10 = games.slice(0, 10);
    const win10 = last10.filter((g) => g.win === true).length;
    const formCard = tpCard('近期交手', `${fmt(games.length)} 局`, `<div class="tp-form-strip">${formSquares || '<span class="tp-quiet">还没有对局记录</span>'}</div>
      <div class="tp-form-legend"><span><i class="is-win"></i>本队胜</span><span><i class="is-loss"></i>对手胜</span><small>左旧 → 右新</small></div>
      <div class="tp-form-stats">
        <div><small>近 ${fmt(last10.length)} 局</small><b>${fmt(win10)} 胜 ${fmt(last10.length - win10)} 负</b></div>
        <div><small>对手胜率</small><b>${pct(oppRate)}</b></div>
        <div><small>场均时长</small><b>${time(avgDuration)}</b></div>
      </div>`);
    /* ── 02 打法画像：经济分配 / 四象限 / 结构 / 领先 ────────────── */
    const maxGoldShare = Math.max(1, ...[...goldShareOpp.values(), ...goldShareOwn.values()].filter(hasNum));
    const ecoRows = lanes.map((row) => {
      const opp = goldShareOpp.get(row.lane), own = goldShareOwn.get(row.lane);
      const isTop = row.lane === oppGoldTop?.lane;
      return `<div class="tp-bar-row${isTop ? ' is-top' : ''}">
        <span class="tp-bar-lane">${esc(row.lane)}${isTop ? '<small>队内第一</small>' : ''}</span>
        <b class="tp-bar-val is-opp">${pct(opp)}</b>
        <span class="tp-bar-track is-opp"><i style="width:${hasNum(opp) ? Math.min(100, opp / maxGoldShare * 100).toFixed(1) : 0}%"></i></span>
        <span class="tp-bar-track is-own"><i style="width:${hasNum(own) ? Math.min(100, own / maxGoldShare * 100).toFixed(1) : 0}%"></i></span>
        <b class="tp-bar-val is-own">${pct(own)}</b>
      </div>`;
    }).join('');
    const ecoRead = oppGoldTop && ownGoldTop
      ? `对手把 ${pct(oppGoldTop.share)} 的经济给了${esc(oppGoldTop.lane)}，本队 ${pct(ownGoldTop.share)} 给了${esc(ownGoldTop.lane)}。`
      : '分路经济明细不足，暂时读不出经济核心。';
    const ecoCard = tpCard('经济分配', '谁在吃钱', `<div class="tp-bar-head"><span></span><span class="is-opp">对手</span><span></span><span></span><span class="is-own">本队</span></div>${ecoRows || tpLack('还没有可用的分路经济明细。')}<p class="tp-read">${ecoRead}</p>`);
    /* x 在后端对同池分位做了 0/100 截断，直接画会全部贴边；这里做小幅确定性抖动，
       让同值点形成簇，不改变相对位置。 */
    const plotPos = (value) => 5 + Math.min(95, Math.max(5, value)) * 0.9;
    const jitterOf = (g) => {
      let seed = 0;
      const str = String(g.seq || g.start || g.day || '');
      for (let i = 0; i < str.length; i++) seed = (seed * 31 + str.charCodeAt(i)) >>> 0;
      return {x: ((seed % 9) - 4) * 0.42, y: (((seed >> 4) % 7) - 3) * 0.42};
    };
    const dots = deepGames.map((g) => {
      const st = g.style;
      if (!st || !hasNum(st.x) || !hasNum(st.y)) return '';
      const opponentWon = g.opponentWin === true || (g.opponentWin == null && g.win === false);
      const keys = TP_WINDOWS.filter(([k]) => k === 'all' || tdInWindow(g.day, styleAnchor, Number(k))).map(([k]) => k).join(' ');
      const jitter = jitterOf(g);
      const x = plotPos(st.x) + jitter.x;
      const y = plotPos(st.y) + jitter.y;
      const title = `${g.start || g.day || ''} · ${opponentWon ? '对手胜' : '本队胜'} · ${st.quadrant || '暂不归类'} · 经济集中 ${Math.round(st.x)} / 打架倾向 ${Math.round(st.y)}`;
      return `<circle cx="${tpQx(x).toFixed(1)}" cy="${tpQy(y).toFixed(1)}" r="4.2" class="tp-qdot ${opponentWon ? 'is-opp' : 'is-win'}" data-td-window-dot="${keys}"><title>${esc(title)}</title></circle>`;
    }).join('');
    const ownPoint = ownStyle?.main && hasNum(ownStyle.main.x) && hasNum(ownStyle.main.y)
      ? {x: ownStyle.main.x, y: ownStyle.main.y}
      : (() => { const w = ownStyle?.windows?.['30'] || ownStyle?.windows?.all; return w && hasNum(w.x) && hasNum(w.y) ? {x: w.x, y: w.y} : null; })();
    const ownDot = ownPoint ? `<circle cx="${tpQx(plotPos(ownPoint.x)).toFixed(1)}" cy="${tpQy(plotPos(ownPoint.y)).toFixed(1)}" r="5.4" class="tp-qdot is-own"><title>${esc(ownName)} · 经济集中 ${Math.round(ownPoint.x)} / 打架倾向 ${Math.round(ownPoint.y)}</title></circle>` : '';
    const avgPoint = hasNum(styleMain?.x) && hasNum(styleMain?.y) ? {x: styleMain.x, y: styleMain.y} : null;
    const avgLines = avgPoint ? `<line x1="${tpQx(plotPos(avgPoint.x)).toFixed(1)}" y1="${tpQy(0).toFixed(1)}" x2="${tpQx(plotPos(avgPoint.x)).toFixed(1)}" y2="${tpQy(100).toFixed(1)}" class="tp-qavg"/>
      <line x1="${tpQx(0).toFixed(1)}" y1="${tpQy(plotPos(avgPoint.y)).toFixed(1)}" x2="${tpQx(100).toFixed(1)}" y2="${tpQy(plotPos(avgPoint.y)).toFixed(1)}" class="tp-qavg"/>` : '';
    const scatter = tpQuadSvg(`${avgLines}${dots}${ownDot}`, '团队风格四象限：逐局散点', styleCounts);
    const evidenceRows = (list) => list.map((g) => {
      const st = g.style;
      const opponentWon = g.opponentWin === true || (g.opponentWin == null && g.win === false);
      const evidence = st?.evidence?.length ? st.evidence : [
        st?.top1 ? `经济第一是${st.top1.lane || '某一路'} ${pct(st.top1.share)}` : null,
        hasNum(st?.fightPerMin) ? `每分钟击杀+助攻 ${fmt(st.fightPerMin, 1)}` : null,
        hasNum(st?.macroPerMin) ? `每分钟推塔+控龙 ${fmt(st.macroPerMin, 2)}` : null,
      ].filter(Boolean);
      return `<div class="tp-ev-row">
        <span class="tp-ev-date">${text(g.day || g.start)}</span>
        <i class="tp-ev-res ${opponentWon ? 'is-loss' : 'is-win'}">${opponentWon ? '对手胜' : '本队胜'}</i>
        <span class="tp-ev-quad">${esc(st?.quadrant || '暂不归类')}</span>
        <span class="tp-ev-point">经济 ${hasNum(st?.x) ? Math.round(st.x) : '—'} · 打架 ${hasNum(st?.y) ? Math.round(st.y) : '—'}</span>
        <span class="tp-ev-lines">${evidence.map((line) => esc(line)).join(' · ') || '证据不足'}</span>
        <span class="tp-ev-dur">${time(g.duration)}</span>
      </div>`;
    }).join('');
    const windowPanel = (windowKey) => {
      const win = oppStyle?.windows?.[windowKey] || null;
      const windowGames = deepGames.filter((g) => windowKey === 'all' || tdInWindow(g.day, styleAnchor, Number(windowKey)));
      const counts = win?.counts || null;
      const sufficient = win?.sufficient === true;
      const quad = win?.quadrant || null;
      const share = hasNum(win?.share) ? win.share : null;
      const countsTop = (() => {
        if (!counts) return null;
        const ranked = TP_QUADS.map(([name]) => [name, counts[name] || 0]).sort((a, b) => b[1] - a[1]);
        return ranked[0][1] > 0 ? ranked[0][0] : null;
      })();
      const total = TP_QUADS.reduce((s, [name]) => s + (counts?.[name] || 0), 0);
      const dist = TP_QUADS.map(([name], index) => {
        const count = counts?.[name] || 0;
        return `<span class="tp-qdist"><i class="tp-qd-${index}"></i>${esc(name)}<b>${fmt(count)}</b></span>`;
      }).join('');
      return `<div class="tp-window" data-td-window-panel="${windowKey}" ${windowKey === '30' ? '' : 'hidden'}>
        <div class="tp-window-facts">
          <div><span>样本</span><b>${fmt(win?.games ?? windowGames.length)} 局</b><small>${sufficient ? '达到 3 局门槛' : '不足 3 局，只作参考'}</small></div>
          <div><span>主要倾向</span><b>${esc(quad || (sufficient && countsTop ? `分布分散：${countsTop}最多` : countsTop ? `单局参考：${countsTop}` : '证据不足'))}</b><small>${quad ? `占比 ${pct(share)}` : sufficient && countsTop ? `最多占比 ${pct(share)}，未过半` : '暂不归类'}</small></div>
          <div><span>平均点位</span><b>经济 ${hasNum(win?.x) ? Math.round(win.x) : '—'} · 打架 ${hasNum(win?.y) ? Math.round(win.y) : '—'}</b><small>${win ? '终局面板代理' : '证据不足'}</small></div>
        </div>
        <div class="tp-qdist-list">${dist}</div>
      </div>`;
    };
    const styleRead = styleMain?.quadrant
      ? `更接近「${esc(styleMain.quadrant)}」：${esc(TD_QUAD_DESC[styleMain.quadrant] || '')}。`
      : styleMain?.sufficient && quadRanked
        ? `四象限没有单一倾向：${esc(quadRanked[0])}最多 ${fmt(quadRanked[1])} 局（占 ${pct(styleMain.share)}），未过半，暂不归类。`
        : quadRanked
          ? `样本不足 3 局：最近单局落在「${esc(quadRanked[0])}」一侧，只作参考。`
          : '逐局风格证据不足，四象限先不给结论。';
    const styleCard = tpCard('团队风格四象限', '逐局识别 · 探索性', `${tpWindowChips()}<div class="tp-quad-wrap">${scatter}</div>
      <div class="tp-quad-legend"><span><i class="tp-lg-win"></i>本队胜</span><span><i class="tp-lg-opp"></i>对手胜</span><span><i class="tp-lg-own"></i>${esc(ownName)}点位</span>${avgPoint ? '<span><i class="tp-lg-avg"></i>窗口均值</span>' : ''}</div>
      ${TP_WINDOWS.map(([windowKey]) => windowPanel(windowKey)).join('')}
      <p class="tp-read">${styleRead}</p>
      <details class="tp-ref tp-detail"><summary>逐局证据 · ${fmt(deepGames.length)} 局</summary><div class="tp-ev-table">${evidenceRows(deepGames) || tpLack('还没有逐局风格证据。')}</div></details>`);
    const structCard = tpCard('输出与承伤结构', '五路占比', `<div class="tp-stack-block">
      <div class="tp-stack-line"><span>对手输出</span>${tpStack(damageShareOpp)}</div>
      <div class="tp-stack-line"><span>本队输出</span>${tpStack(damageShareOwn)}</div>
      <div class="tp-stack-line"><span>对手承伤</span>${tpStack(takenShareOpp)}</div>
      <div class="tp-stack-line"><span>本队承伤</span>${tpStack(takenShareOwn)}</div>
      ${tpStackLegend()}</div>
      <p class="tp-read">${(() => {
        const oppDmg = topLaneOf(damageShareOpp), ownDmg = topLaneOf(damageShareOwn);
        return oppDmg && ownDmg ? `对手伤害主要来自${esc(oppDmg.lane)}（${pct(oppDmg.share)}），本队来自${esc(ownDmg.lane)}（${pct(ownDmg.share)}）。` : '分路输出明细不足。';
      })()}</p>`);
    const leadGroups = ['领先（>5k）', '持平（±5k）', '落后（>5k）'];
    const leadMap = new Map();
    for (const g of deepGames) {
      const enemyGold = g.sides?.enemy?.stats?.gold, ownGold = g.sides?.own?.stats?.gold;
      if (!hasNum(enemyGold) || !hasNum(ownGold)) continue;
      const diffGold = enemyGold - ownGold;
      const key = diffGold > 5000 ? '领先（>5k）' : diffGold < -5000 ? '落后（>5k）' : '持平（±5k）';
      const enemyStats = g.sides?.enemy?.stats || {};
      const item = leadMap.get(key) || {key, games: 0, towers: 0, dragons: 0, fight: 0};
      item.games++;
      item.towers += enemyStats.towers || 0;
      item.dragons += enemyStats.dragons || 0;
      item.fight += (enemyStats.kills || 0) + (enemyStats.assists || 0);
      leadMap.set(key, item);
    }
    const leadTotal = [...leadMap.values()].reduce((s, r) => s + r.games, 0);
    const leadRows = leadGroups.filter((key) => leadMap.has(key)).map((key) => {
      const row = leadMap.get(key);
      const tone = key.startsWith('领先') ? 'is-ahead' : key.startsWith('落后') ? 'is-behind' : 'is-even';
      return `<div class="tp-lead-row ${tone}"><span>${esc(key)}</span><i><b style="width:${leadTotal ? (row.games / leadTotal * 100).toFixed(0) : 0}%"></b></i><b>${fmt(row.games)} 局</b><em>推塔 ${fmt(row.towers / row.games, 1)} · 控龙 ${fmt(row.dragons / row.games, 1)} · 击杀助攻 ${fmt(row.fight / row.games, 1)}</em></div>`;
    }).join('');
    const leadCard = tpCard('领先 / 落后', '按终局经济差分档', leadRows || tpLack('还没有可用的逐局终局经济。'));
    /* ── 03 英雄与 BP ────────────────────────────────────────────── */
    const heroLaneMap = new Map();
    for (const p of oppPicks) if (p.lane && !heroLaneMap.has(p.hero)) heroLaneMap.set(p.hero, p.lane);
    for (const h of fallbackEnemyHeroes) if (h.lane && !heroLaneMap.has(h.hero)) heroLaneMap.set(h.hero, h.lane);
    const typeMap = new Map();
    for (const p of oppPicks) {
      if (!p.archetype) continue;
      const laneMap = typeMap.get(p.lane || '其他') || new Map();
      const item = laneMap.get(p.archetype) || {type: p.archetype, games: 0, heroes: new Map()};
      item.games += p.games;
      item.heroes.set(p.hero, (item.heroes.get(p.hero) || 0) + p.games);
      laneMap.set(p.archetype, item);
      typeMap.set(p.lane || '其他', laneMap);
    }
    const totalHeroes = new Set(oppPicks.map((p) => p.hero)).size;
    const typedPicks = oppPicks.filter((p) => !isUnlabeled(p.archetype)).reduce((sum, p) => sum + p.games, 0);
    const allPicks = oppPicks.reduce((sum, p) => sum + p.games, 0);
    /* 英雄池口径：逐局 picks 有 20+ 局时用逐局分布；camp-compare 只有 1 局时不用它冒充全样本。 */
    const heroPickCount = new Map();
    for (const p of oppPicks) heroPickCount.set(p.hero, (heroPickCount.get(p.hero) || 0) + p.games);
    const pickTotal = [...heroPickCount.values()].reduce((a, b) => a + b, 0);
    const hhi = pickTotal ? [...heroPickCount.values()].reduce((sum, n) => sum + (n / pickTotal) ** 2, 0) : null;
    const effective = hasNum(hhi) && hhi > 0 ? 1 / hhi : null;
    const poolSummary = `<div class="tp-pool-summary">
      <span><small>英雄数</small><b>${fmt(totalHeroes)}</b></span>
      <span><small>有效英雄</small><b>${hasNum(effective) ? fmt(effective, 1) : '—'}</b></span>
      <span><small>英雄池</small><b>${tdPoolText(hhi)}</b></span>
      <span><small>类型覆盖</small><b>${allPicks ? pct(typedPicks / allPicks * 100) : '—'}</b></span>
    </div>`;
    const poolRows = TM_LANES.map((lane) => {
      const heroes = oppPicks.filter((p) => p.lane === lane).sort((a, b) => b.games - a.games);
      const types = [...(typeMap.get(lane) || new Map()).values()].sort((a, b) => b.games - a.games);
      const known = types.filter((item) => !isUnlabeled(item.type));
      const untypedGames = types.filter((item) => isUnlabeled(item.type)).reduce((s, item) => s + item.games, 0);
      const knownTotal = known.reduce((s, item) => s + item.games, 0);
      /* 前 3 类遇到并列时继续纳入，避免把同场次的类型藏进「其余」；最多 5 类。 */
      const top = known.slice(0, 3);
      while (top.length < known.length && top.length < 5 && known[top.length].games === top[top.length - 1].games) top.push(known[top.length]);
      const restItems = known.slice(top.length);
      const rest = restItems.reduce((s, item) => s + item.games, 0);
      const restDetail = restItems.map((item) => `${item.type} ${pct(item.games / knownTotal * 100)}`).join(' · ');
      const segs = [
        ...top.map((item, index) => ({label: item.type, games: item.games, cls: `tp-mix-${index}`})),
        ...(rest ? [{label: `其余 ${fmt(restItems.length)} 类`, games: rest, cls: 'tp-mix-rest', title: restDetail}] : []),
      ];
      const mix = knownTotal ? `<div class="tp-mixbar">${segs.map((seg) => `<i class="${seg.cls}" style="flex:${seg.games} 0 0" title="${esc(seg.title || `${seg.label} ${pct(seg.games / knownTotal * 100)}`)}"></i>`).join('')}</div>
        <div class="tp-mixlegend">${segs.map((seg) => `<span title="${esc(seg.title || `${seg.label} ${pct(seg.games / knownTotal * 100)}`)}"><i class="${seg.cls}"></i>${esc(seg.label)}<b>${pct(seg.games / knownTotal * 100)}</b></span>`).join('')}${untypedGames ? `<span class="is-untyped">未标注 ${fmt(untypedGames)} 次</span>` : ''}</div>${restDetail ? `<p class="tp-mix-extra">其余类型：${esc(restDetail)}</p>` : ''}`
        : `<p class="tp-quiet">类型证据不足${untypedGames ? ` · 未标注 ${fmt(untypedGames)} 次` : ''}</p>`;
      const shown = heroes.slice(0, 7);
      return `<div class="tp-pool-row" data-tp-hero-lane="${esc(lane)}">
        <div class="tp-pool-lane"><b>${esc(lane)}</b><small>${heroes.length ? `${fmt(heroes.length)} 个英雄 · ${fmt(heroes.reduce((s, p) => s + p.games, 0))} 次` : '暂无出场'}</small></div>
        <div class="tp-pool-main">
          ${mix}
          <div class="tp-herolinks">${shown.map((p) => heroLink(p.hero, p.games)).join('')}${heroes.length > shown.length ? `<span class="tp-more">+${fmt(heroes.length - shown.length)}</span>` : ''}</div>
        </div>
      </div>`;
    }).join('');
    const topPickHeroes = [...heroPickCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([hero, gamesN]) => heroLink(hero, gamesN)).join('');
    const heroCard = tpCard('英雄使用', `${fmt(totalHeroes)} 个英雄 · 逐局识别`, `<div class="tp-pool-head">${tpHeroLaneChips()}${poolSummary}</div><div class="tp-pool-top"><span>最常选</span><div class="tp-herolinks">${topPickHeroes || '<span class="tp-quiet">—</span>'}</div></div>${poolRows}<p class="tp-read">其余类型＝已知类型里排在前面之外的较低占比类型；未标注＝英雄分类表暂未收录，两者不能混为一谈。</p>`);
    const bpBans = (bpTeam?.bans || []).map((item) => ({hero: item.hero, count: item.count || item.games || 0}))
      .sort((a, b) => b.count - a.count).slice(0, 6);
    const ourTopHeroes = [...ownHeroGames.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
    const ourPairRows = (() => {
      const map = new Map();
      for (const g of deepGames) {
        const heroes = (g.sides?.own?.picks || []).map((p) => p.name).filter(Boolean);
        for (let i = 0; i < heroes.length; i++) for (let j = i + 1; j < heroes.length; j++) {
          const key = [heroes[i], heroes[j]].sort().join(' + ');
          const item = map.get(key) || {key, games: 0, oppWins: 0};
          item.games++;
          if (g.opponentWin === true) item.oppWins++;
          map.set(key, item);
        }
      }
      return [...map.values()].sort((a, b) => b.games - a.games).slice(0, 4).map((row) => ({heroes: row.key, games: row.games, rate: row.games ? row.oppWins / row.games * 100 : null}));
    })();
    const oppPairRows = (() => {
      const map = new Map();
      for (const g of deepGames) {
        const heroes = (g.sides?.enemy?.picks || []).map((p) => p.name).filter(Boolean);
        for (let i = 0; i < heroes.length; i++) for (let j = i + 1; j < heroes.length; j++) {
          const key = [heroes[i], heroes[j]].sort().join(' + ');
          const item = map.get(key) || {key, games: 0, wins: 0};
          item.games++;
          if (g.opponentWin === true) item.wins++;
          map.set(key, item);
        }
      }
      return [...map.values()].sort((a, b) => b.games - a.games).slice(0, 4).map((row) => ({heroes: row.key, games: row.games, rate: row.games ? row.wins / row.games * 100 : null}));
    })();
    const pairLine = (row) => `<div class="tp-pair-row"><span>${esc(row.heroes)}</span><small>${fmt(row.games)} 局</small><b>${row.games >= 3 ? pct(row.rate) : '样本'}</b></div>`;
    const pairsDetail = `<details class="tp-ref tp-detail tp-detail-wide"><summary>双人组合 · 对手 / 本队</summary><div class="tp-pair-cols">
      <div><b>对手常搭</b>${oppPairRows.map(pairLine).join('') || '<p class="tp-quiet">暂无</p>'}</div>
      <div><b>本队组合下的对手胜负</b>${ourPairRows.map(pairLine).join('') || '<p class="tp-quiet">暂无</p>'}</div>
    </div></details>`;
    /* ── 04 阵容体系（v3.2：主力体系 Top 3 + 体系库）──────────────── */
    const sigRow = (row) => `<div class="tp-sig-row">
      ${heroFaces(row.heroSets?.[0] || [])}
      ${tpTypeText(row.sig)}
      <span class="tp-games">${fmt(row.games)} 局</span>
      <span class="tp-wr">${luWrText(row)}</span>
      ${tpGamesRef(row.gamesRef)}
    </div>`;
    const completeSig = (lineups?.signature || []).filter((row) => (row.sig || []).every((name) => !isUnlabeled(name)));
    const luUnknown = lineups?.unknownRow || {};
    const sigUnknown = luUnknown.games ? `<details class="tp-ref tp-detail tp-untyped"><summary>含未标注的阵容 · ${fmt(luUnknown.games)} 局</summary>${(luUnknown.sigs || []).map((row) => `<div class="tp-sig-row is-untyped">${heroFaces([])}${tpTypeText(row.sig)}<span class="tp-games">${fmt(row.games || 1)} 局</span><span class="tp-wr"><span class="tp-wr-sample">未计入胜率</span></span><span></span></div>`).join('')}</details>` : '';
    /* 签名多为 1 局；按「打野 + 中路 + 游走」核心归并，才能看出主力体系。 */
    const sysMap = new Map();
    for (const row of completeSig) {
      const key = (row.sig || []).slice(1, 4).join(' + ');
      const item = sysMap.get(key) || {key, sig: row.sig, games: 0, wins: 0, losses: 0, heroSets: [], gamesRef: []};
      item.games += row.games || 0;
      item.wins += row.wins || 0;
      item.losses += row.losses || 0;
      if (row.heroSets?.[0]) item.heroSets.push(row.heroSets[0]);
      item.gamesRef.push(...(row.gamesRef || []));
      sysMap.set(key, item);
    }
    const systems = [...sysMap.values()].sort((a, b) => b.games - a.games || b.wins - a.wins).slice(0, 3);
    const sysWr = (item) => {
      const decided = (item.wins || 0) + (item.losses || 0);
      if (item.games < 3 || decided < 3) return `<span class="tp-wr-sample">${fmt(item.wins || 0)} 胜 ${fmt(item.losses || 0)} 负</span>`;
      return `<b>${pct(item.wins / decided * 100)}</b><span class="tp-sample">${fmt(item.games)} 局</span>`;
    };
    const systemRow = (item) => `<div class="tp-sig-row is-system">
      ${heroFaces(item.heroSets[0] || [])}
      ${tpTypeText(item.sig)}
      <span class="tp-games">${fmt(item.games)} 局</span>
      <span class="tp-wr">${sysWr(item)}</span>
      ${tpGamesRef(item.gamesRef)}
    </div>`;
    const luSide = lineups?.side || {};
    const sideBar = (key, label) => {
      const side = luSide[key] || {games: 0, wins: 0, losses: 0};
      const gamesN = (side.wins || 0) + (side.losses || 0);
      return `<div class="tp-side-row"><span>${esc(label)}</span><i><b style="width:${(side.games || 0) ? ((side.wins || 0) / (side.games || 1) * 100).toFixed(0) : 0}%"></b></i><small>${fmt(side.games || 0)} 局 · ${gamesN >= 3 && nEff >= 10 ? `胜率 ${pct(100 * (side.wins || 0) / gamesN)}` : `${fmt(side.wins || 0)} 胜 ${fmt(side.losses || 0)} 负`}</small></div>`;
    };
    const systemsCard = tpCard('主力体系', '按打野 + 中路 + 游走核心归并 · 其余进体系库', `${systems.map(systemRow).join('') || tpLack('还没有可归并的五路签名。')}<div class="tp-side">${sideBar('blue', '蓝方')}${sideBar('red', '红方')}</div>`);
    const luFamilyGroups = (rows, keyName) => {
      const families = ['边野', '中野', '射辅', '中辅', '野辅', '中野辅', '边野辅', '中射辅', '野射辅', '边中野'];
      const map = new Map();
      for (const row of rows || []) {
        if (!map.has(row.family)) map.set(row.family, []);
        map.get(row.family).push(row);
      }
      const out = families.filter((family) => map.has(family)).map((family) => {
        const items = map.get(family).slice(0, 2);
        return `<div class="tp-fam"><header><b>${esc(family)}</b><small>${esc(LU_FAMILY_NOTES[family] || '')}</small></header>${items.map((row) => `<div class="tp-fam-row">${tpTypeText(row[keyName])}<span class="tp-games">${fmt(row.games)} 局</span><span class="tp-wr">${luWrText(row)}</span>${tpGamesRef(row.gamesRef, 4)}</div>`).join('')}</div>`;
      }).join('');
      return out || tpLack('还没有可识别的组合记录；样本不足或英雄类型待分类。');
    };
    const muCells = lineups?.matchups?.cells || [];
    const muBaselines = lineups?.matchups?.rowBaselines || [];
    const MU_LEVEL = {'established': ['倾向性', 'is-established'], 'initial': ['初步观察', 'is-initial'], 'insufficient': ['证据不足', 'is-insufficient']};
    const matchupTable = muCells.length ? `<div class="tp-table-wrap"><table class="tp-table">
      <thead><tr><th>${esc(oppName)}体系</th><th>对手体系（${esc(ownName)}）</th><th>场次</th><th>胜率</th><th>相对基准</th><th>证据</th></tr></thead>
      <tbody>${muCells.map((c) => {
        const [lvLabel, lvCls] = MU_LEVEL[c.evidenceLevel] || ['', ''];
        return `<tr><td>${tpTypeText(c.row)}</td><td>${tpTypeText(c.col)}</td><td><b>${fmt(c.n)}</b></td><td>${c.wr != null ? pct(c.wr) : '<span class="tp-quiet">样本</span>'}</td><td>${c.baselineDiff != null ? `<b class="${c.baselineDiff > 0 ? 'is-up' : c.baselineDiff < 0 ? 'is-down' : ''}">${c.baselineDiff > 0 ? '+' : ''}${fmt(c.baselineDiff, 1)}</b>` : '—'}</td><td><span class="tp-level ${lvCls}">${esc(lvLabel)}</span></td></tr>`;
      }).join('')}</tbody></table></div>` : tpLack('双方体系都可识别的对局还不足。');
    const muMax = Math.max(0, ...muCells.map((c) => c.n || 0));
    const muBaselineLine = muBaselines.length ? `基准：${muBaselines.slice(0, 2).map((b) => `${b.sig.join('+')} ${fmt(b.games)} 局`).join('；')}${muBaselines.length > 2 ? ` 等 ${fmt(muBaselines.length)} 套` : ''}。` : '';
    const matchupBody = muCells.length && muMax < 2
      ? `<p class="tp-read">${fmt(muCells.length)} 组体系对位都只有 1 局样本，暂不下结论。</p><details class="tp-ref tp-detail"><summary>展开对位表</summary>${matchupTable}</details>`
      : matchupTable;

    const resRows = (lineups?.resources || []).map((row) => `<div class="tp-res-row">
      <div class="tp-res-head">${tpTypeText(row.sig)}<span>面板 ${fmt(row.panelGames)} / ${fmt(row.games)} 局</span>${row.wr != null ? `<span>该体系胜率 ${pct(row.wr)}</span>` : ''}${tpGamesRef(row.gamesRef, 4)}</div>
      <div class="tp-stack-line"><span>经济</span>${tpStack(new Map(['对抗路', '打野', '中路', '发育路', '游走'].map((l) => [l, (row.lanes[l] || {}).goldShare])))}</div>
      <div class="tp-stack-line"><span>输出</span>${tpStack(new Map(['对抗路', '打野', '中路', '发育路', '游走'].map((l) => [l, (row.lanes[l] || {}).dmgShare])))}</div>
    </div>`).join('');
    const libraryDetail = `<details class="tp-ref tp-detail tp-detail-wide tp-library"><summary>体系库 · ${fmt(completeSig.length)} 条签名 · ${fmt((lineups?.pairs || []).length)} 双人 · ${fmt((lineups?.triads || []).length)} 三人 · ${fmt(muCells.length)} 格对抗</summary>
      <div class="tp-lib-block"><header><b>五路类型签名</b><span>${fmt(completeSig.length)} 条 · 顺序 对抗 → 打野 → 中路 → 发育 → 游走</span></header>${completeSig.map(sigRow).join('')}${sigUnknown}</div>
      <div class="tp-grid is-2"><div class="tp-lib-block"><header><b>双人位置组合</b><span>同伴倾向</span></header>${luFamilyGroups(lineups?.pairs, 'pair')}</div><div class="tp-lib-block"><header><b>三人核心三角</b><span>节奏与保护配置</span></header>${luFamilyGroups(lineups?.triads, 'triad')}</div></div>
      <div class="tp-lib-block"><header><b>体系对抗</b><span>历史关联 · 不写克制因果</span></header>${matchupBody}<p class="tp-read">${muBaselineLine}样本受实力、版本与选边影响，不作为克制结论。</p></div>
      ${resRows ? `<div class="tp-lib-block"><header><b>按体系的资源分布</b><span>${fmt((lineups?.resources || []).length)} 套</span></header><div class="tp-res-list">${resRows}</div></div>` : ''}
    </details>`;
    const realSeries = (deep?.series || []).filter((x) => !/演示|demo/i.test(String(x.label || x.bo || '')) && (x.games || []).length);
    const seriesHtml = realSeries.map((s) => `<div class="tp-series">
      <header><b>${esc(s.label || s.bo || '系列赛')}</b><span>${esc(s.bo || '')} · ${fmt(s.score?.wins || 0)} 胜 ${fmt(s.score?.losses || 0)} 负</span></header>
      <div class="tp-series-track">${(s.games || []).map((r) => `<div class="tp-series-game">
        <span class="tp-series-no">G${esc(String(r.gameNo ?? '—'))}</span>
        <i class="tp-series-res ${r.win === true ? 'is-win' : r.win === false ? 'is-loss' : ''}">${r.win === true ? '胜' : r.win === false ? '负' : '—'}</i>
        <span class="tp-series-sig">${r.signature ? tpTypeText(r.signature) : '<span class="tp-quiet">含未标注</span>'}</span>
        <span class="tp-series-meta" title="剩余可组体系 ${fmt(r.legalCombos)}">新启用 ${fmt((r.newHeroes || []).length)} · 已用 ${fmt(r.usedCount)}</span>
        ${r.matchKey ? `<a href="${route('match', r.matchKey)}">复盘 ↗</a>` : ''}
      </div>`).join('')}</div>
    </div>`).join('');
    const seriesCard = realSeries.length ? tpCard('BO 系列赛', `${fmt(realSeries.length)} 个系列`, seriesHtml) : '';
    /* ── 05 分路对位 + 过程行为 + 对局证据 ───────────────────────── */
    const oppDragonsPerGame = (() => { const value = deepStat('enemy', 'dragons'); return hasNum(value) ? tdAvgOf(value, deepGames.length || cmpGames) : null; })();
    const ownDragonsPerGame = (() => { const value = deepStat('own', 'dragons'); return hasNum(value) ? tdAvgOf(value, deepGames.length || cmpGames) : null; })();
    const ownPlayerByLane = new Map();
    for (const p of (own.players || [])) if (p.lane && !ownPlayerByLane.has(p.lane)) ownPlayerByLane.set(p.lane, p);
    for (const p of deepPlayers('own')) if (p.lane && !ownPlayerByLane.has(p.lane)) ownPlayerByLane.set(p.lane, p);
    const duelCards = TM_LANES.map((lane) => {
      const row = lanes.find((item) => item.lane === lane);
      const opp = laneNormal(row?.enemy);
      const ownSide = laneNormal(row?.own);
      const ownPlayer = ownPlayerByLane.get(lane);
      const metricRows = (TD_DUEL_METRICS[lane] || []).map(([label, metricKey]) => {
        const oppValue = metricKey === 'teamDragons' ? oppDragonsPerGame : (opp?.[metricKey] ?? null);
        const ownValue = metricKey === 'teamDragons' ? ownDragonsPerGame : (ownSide?.[metricKey] ?? null);
        const digits = metricKey === 'participation' ? 1 : metricKey === 'controlPerMin' || metricKey === 'killPart' || metricKey === 'towersPerGame' ? 1 : 0;
        return `<div class="tp-duel-metric"><span class="tp-duel-label">${esc(label)}</span><span class="tp-duel-vals"><b>${tdDuelText(metricKey, oppValue)}</b><i>/</i><b>${tdDuelText(metricKey, ownValue)}</b></span><em>${tdGapText(oppValue, ownValue, digits, metricKey === 'participation' ? '%' : '')}</em></div>`;
      }).join('');
      return `<article class="tp-duel">
        <header><b>${esc(lane)}</b><small>${fmt(opp?.games || ownSide?.games || 0)} 局对位</small></header>
        <div class="tp-duel-who"><span><small>对手</small><b>${esc(opp?.name || '未记录')}</b></span><span><small>本队</small><b>${esc(ownSide?.name || ownPlayer?.name || '未记录')}</b></span></div>
        ${metricRows}
      </article>`;
    }).join('');
    const duelCard = tpCard('分路对位', '同位置对照 · 任何分路都不看击杀死亡比', `<div class="tp-duel-grid">${duelCards}</div>`);
    const behavior = ((behaviorData || {}).teams || []).find((x) => x.opponent === (t.displayName || '')) || null;
    const behaviorCP = (behavior || {}).checkpoints || {};
    const cpLine = (stamp, label) => {
      const c = behaviorCP[stamp] || {};
      return c.games
        ? `<div class="tp-cp"><span>${label}</span><b>${fmt(Math.round(c.meanDiff))}</b><small>${fmt(c.games)} 局 · 领先 ${fmt(c.leadRate, 1)}% · 兑现 ${c.leadConversion == null ? '—' : fmt(c.leadConversion, 1) + '%'}</small></div>`
        : `<div class="tp-cp is-empty"><span>${label}</span><b>—</b><small>无过程证据</small></div>`;
    };
    const hasBehaviorCP = ['240', '600'].some((stamp) => (behaviorCP[stamp]?.games || 0) > 0);
    const behaviorCard = behavior ? tpCard('对手过程行为', `${fmt(behavior.games)} 局`, `
      <div class="tp-sides"><div class="tp-side-row"><span>蓝方</span><i><b style="width:${behavior.games ? behavior.blueGames / behavior.games * 100 : 0}%"></b></i><small>${fmt(behavior.blueGames)} 局</small></div>
      <div class="tp-side-row"><span>红方</span><i><b class="is-opp" style="width:${behavior.games ? behavior.redGames / behavior.games * 100 : 0}%"></b></i><small>${fmt(behavior.redGames)} 局</small></div></div>
      ${hasBehaviorCP ? `<div class="tp-cps">${cpLine('240', '4 分钟')}${cpLine('600', '10 分钟')}</div>` : '<p class="tp-read">4 / 10 分钟过程证据还没有接上（需要 BP 记录与回放时间轴匹配）。</p>'}
      ${behavior.topPicks?.length ? `<div class="tp-herolinks">${behavior.topPicks.slice(0, 6).map((p) => heroLink(p.hero, p.games)).join('')}</div>` : ''}
      <p class="tp-read">对手视角＝本队视角取反。</p>`) : '';
    const evidenceList = (list) => list.map((g) => {
      const picks = g.sides?.enemy?.picks || [];
      return `<div class="tp-game-row">
        <span class="tp-game-date">${text((g.day || g.start || '—').slice(0, 5))}</span>
        <i class="tp-ev-res ${g.opponentWin ? 'is-loss' : 'is-win'}">${g.opponentWin ? '负' : '胜'}</i>
        ${heroFaces(picks.slice(0, 5).map((p) => p.name))}
        <span class="tp-game-time">${time(g.duration)}</span>
        ${g.matchKey ? `<a class="tp-row-link" href="${route('match', g.matchKey)}" title="打开单局复盘">↗</a>` : '<span></span>'}
      </div>`;
    }).join('');
    const evidenceCard = tpCard('对局证据', `${fmt(deepGames.length)} 局 · 对手视角`, deepGames.length
      ? `<div class="tp-game-list">${evidenceList(deepGames.slice(0, 8))}</div>${deepGames.length > 8 ? `<details class="tp-ref tp-detail"><summary>全部 ${fmt(deepGames.length)} 局</summary><div class="tp-game-list">${evidenceList(deepGames)}</div></details>` : ''}`
      : tpLack('还没有可回溯的对局明细。'));
    const kpl = deep?.kpl || null;
    const kplHits = [...(kpl?.hits || [])].sort((a, b) => (b.oppGames || 0) - (a.oppGames || 0) || (b.n || 0) - (a.n || 0)).slice(0, 8);
    const kindLabel = {pair: '双人', trio: '三人', full: '整套'};
    const kplRows = kplHits.map((hit) => `<tr>
      <td><span class="tp-kpl-combo">${heroFaces(hit.heroes)}<span>${esc((hit.heroes || []).join(' + '))}</span><small>${esc(kindLabel[hit.kind] || hit.kind || '')}</small></span></td>
      <td>${fmt(hit.n)}</td><td>${hasNum(hit.wr) ? pct(hit.wr) : '—'}</td>
      <td>${fmt(hit.oppGames || 0)}</td><td>${(hit.oppGames || 0) >= 3 ? pct(kplOppRate(hit)) : '<span class="tp-quiet">样本</span>'}</td></tr>`).join('');
    const kplTable = kplHits.length ? `<div class="tp-table-wrap"><table class="tp-table"><thead><tr><th>组合</th><th>KPL 场次</th><th>KPL 胜率</th><th>交手</th><th>对手胜率</th></tr></thead><tbody>${kplRows}</tbody></table></div>` : tpLack('这支对手还没有命中 KPL 组合表的阵容。');
    const kplLineup = (kpl?.lineup?.heroes || []).length
      ? `<div class="tp-kpl-lineup"><b>整套命中</b><span>${(kpl.lineup.heroes || []).map((h) => `<em>${esc(h)}</em>`).join('')}</span><small>KPL ${fmt(kpl.lineup.n)} 场 · 胜率 ${pct(kpl.lineup.wr)} · 交手 ${fmt(kpl.lineup.oppGames || 0)} 局</small></div>` : '';
    const kplDetail = `<details class="tp-ref tp-detail tp-detail-wide"><summary>KPL 职业参照 · ${kplHits.length ? `${fmt(kplHits.length)} 组命中` : '证据不足'}</summary>${kplTable}${kplLineup}<p class="tp-read">KPL 胜率按官方赛事口径；职业参照是外部基准，不证明这支队伍会用某套体系。</p></details>`;
    /* ── 分析层：资源对位 / 边野模式 / 关联规则 / 变化异常 ───────── */
    const bpOrder = deep?.bpOrder || null;
    const meanOf = (list) => list.length ? list.reduce((a, b) => a + b, 0) / list.length : null;
    const wilson95 = (wins, games) => {
      if (!games) return null;
      const z = 1.96, p = wins / games, den = 1 + z * z / games;
      const center = p + z * z / (2 * games);
      const margin = z * Math.sqrt(p * (1 - p) / games + z * z / (4 * games * games));
      return [Math.max(0, (center - margin) / den * 100), Math.min(100, (center + margin) / den * 100)];
    };
    const enemyPickOf = (game, lane) => (game.sides?.enemy?.picks || []).find((pick) => pick.lane === lane) || null;
    const decidedGames = deepGames.filter((game) => game.opponentWin === true || game.opponentWin === false);
    const baseWins = decidedGames.filter((game) => game.opponentWin === true).length;
    const baseRate = decidedGames.length ? baseWins / decidedGames.length * 100 : null;

    const roleResource = TM_LANES.map((lane) => {
      const shares = [], diffPm = [], winShares = [], lossShares = [];
      let top1 = 0;
      for (const game of deepGames) {
        const enemyPlayers = game.sides?.enemy?.players || [];
        const ownPlayers = game.sides?.own?.players || [];
        const opp = enemyPlayers.find((player) => player.lane === lane);
        const ownPlayer = ownPlayers.find((player) => player.lane === lane);
        const total = enemyPlayers.reduce((sum, player) => sum + (hasNum(player.gold) ? player.gold : 0), 0);
        if (opp && hasNum(opp.gold) && total) {
          const share = opp.gold / total * 100;
          shares.push(share);
          if (game.opponentWin === true) winShares.push(share);
          else if (game.opponentWin === false) lossShares.push(share);
          const max = Math.max(...enemyPlayers.map((player) => hasNum(player.gold) ? player.gold : 0));
          if (opp.gold === max) top1++;
        }
        if (opp && ownPlayer && hasNum(opp.gold) && hasNum(ownPlayer.gold) && hasNum(game.duration) && game.duration > 0) {
          diffPm.push((opp.gold - ownPlayer.gold) / (game.duration / 60));
        }
      }
      return {lane, games: shares.length, share: meanOf(shares), diffPm: meanOf(diffPm), winShare: meanOf(winShares), lossShare: meanOf(lossShares), top1};
    });
    const miniBar = (ratio, cls = '') => `<span class="tp-mini${cls ? ' ' + cls : ''}"><i style="width:${Math.max(0, Math.min(100, hasNum(ratio) ? ratio : 0)).toFixed(1)}%"></i></span>`;
    const shareCell = (value) => `<div class="tp-cell"><b>${pct(value)}</b>${miniBar(hasNum(value) ? value / 30 * 100 : 0)}</div>`;
    const diffCell = (value) => {
      if (!hasNum(value)) return '<div class="tp-cell"><b>—</b></div>';
      const width = Math.min(50, Math.abs(value) / 30 * 50);
      return `<div class="tp-cell"><b>${value > 0 ? '+' : ''}${fmt(value, 0)}</b><span class="tp-mini is-diff"><i class="${value >= 0 ? 'is-pos' : 'is-neg'}" style="width:${width}%;${value >= 0 ? 'left:50%' : 'right:50%'}"></i></span></div>`;
    };
    const stateCell = (value, cls) => `<div class="tp-cell"><b>${pct(value)}</b>${miniBar(hasNum(value) ? value / 30 * 100 : 0, cls)}</div>`;
    const countCell = (value, total) => `<div class="tp-cell"><b>${fmt(value)} 局</b>${miniBar(total ? value / total * 100 : 0)}</div>`;
    const resourceCard = tpCard('资源与对位', `份额 = 同队占比 · 对位差 = 同位置对手 − 本队 / 分钟`, `<div class="tp-table-wrap"><table class="tp-table tp-res-table">
      <thead><tr><th>位置</th><th>份额</th><th>对位差/分</th><th>胜局份额</th><th>负局份额</th><th>经济第一</th></tr></thead>
      <tbody>${roleResource.map((row) => `<tr>
        <td><b>${esc(row.lane)}</b></td>
        <td>${shareCell(row.share)}</td>
        <td>${diffCell(row.diffPm)}</td>
        <td>${stateCell(row.winShare, 'is-win')}</td>
        <td>${stateCell(row.lossShare, 'is-loss')}</td>
        <td>${countCell(row.top1, row.games)}</td>
      </tr>`).join('')}</tbody></table></div>
      <p class="tp-read">经济第一分布：${roleResource.filter((row) => row.top1).map((row) => `${row.lane} ${row.top1} 局`).join(' / ') || '—'}。份额受角色基线与比赛状态影响，本表未校正；对位差按同位置计算。</p>`);

    const edgeMap = new Map();
    let edgeGames = 0;
    for (const game of deepGames) {
      const edge = enemyPickOf(game, '对抗路');
      const jungle = enemyPickOf(game, '打野');
      if (!edge?.archetype || !jungle?.archetype || isUnlabeled(edge.archetype) || isUnlabeled(jungle.archetype)) continue;
      edgeGames++;
      const key = `${edge.archetype} + ${jungle.archetype}`;
      const item = edgeMap.get(key) || {key, games: 0};
      item.games++;
      edgeMap.set(key, item);
    }
    const edgeMatrix = new Map(edgeMap);
    const edgeMax = Math.max(1, ...edgeMatrix.values().map((row) => row.games));
    const edgeTypes = ['战边', '坦边'];
    const jungleTypes = ['刺野', '战野', '坦野'];
    const edgeCell = (edge, jungle) => {
      const item = edgeMatrix.get(`${edge} + ${jungle}`);
      if (!item) return '<div class="tp-edge-cell is-empty"><b>—</b></div>';
      const ratio = item.games / edgeMax;
      const tint = Math.round(10 + ratio * 40);
      return `<div class="tp-edge-cell" style="background:color-mix(in srgb, var(--accent) ${tint}%, var(--paper))" title="${esc(edge)} + ${esc(jungle)}：${fmt(item.games)} 局 / ${pct(item.games / edgeGames * 100)}"><b>${fmt(item.games)}</b><small>${pct(item.games / edgeGames * 100)}</small></div>`;
    };
    const edgeTop = [...edgeMatrix.values()].sort((a, b) => b.games - a.games)[0];
    const edgeCard = tpCard('边野组合', `类型已知 ${fmt(edgeGames)} 局 · 只描述选人频率`, edgeGames
      ? `<div class="tp-edge-matrix">
          <div class="tp-edge-mhead"><span></span>${jungleTypes.map((jungle) => `<b>${esc(jungle)}</b>`).join('')}</div>
          ${edgeTypes.map((edge) => `<div class="tp-edge-mrow"><span>${esc(edge)}</span>${jungleTypes.map((jungle) => edgeCell(edge, jungle)).join('')}</div>`).join('')}
        </div>
        <p class="tp-read">最常见：${edgeTop ? `${esc(edgeTop.key)} ${fmt(edgeTop.games)} 局（${pct(edgeTop.games / edgeGames * 100)}）` : '—'}。只统计对抗路与打野都有类型标注的局；组合不代表先后顺序，也不等于战术身份。</p>`
      : tpLack('还没有边路与打野类型都已知的局。'));

    const bpoLaneIndex = (lane) => Math.max(0, TM_LANES.indexOf(lane));
    const bpoBars = (rows) => rows.length
      ? `<div class="tp-bpo-bars">${rows.map((row) => `<div class="tp-bpo-bar"><span>${esc(row.key)}</span><i><b style="width:${row.share == null ? 0 : Math.min(100, row.share)}%"></b></i><em>${fmt(row.games)} 局 · ${pct(row.share)}</em></div>`).join('')}</div>`
      : '<p class="tp-quiet">—</p>';
    const bpoChips = (rows, limit = 4) => `<div class="tp-bpo-chips">${rows.slice(0, limit).map((row) => heroLink(row.key, row.games)).join('') || '<span class="tp-quiet">—</span>'}</div>`;
    const bpoLaneClass = (lane) => lane === '未标注' ? 'tp-lane-unlabeled' : `tp-lane-${bpoLaneIndex(lane)}`;
    const bpoDist = (row) => {
      const lanes = row.lanes || [];
      return `<div class="tp-bpo-dist">${lanes.map((lane) => `<i class="${bpoLaneClass(lane.key)}" style="flex:${Math.max(1, lane.games)}" title="${esc(lane.key)} ${fmt(lane.games)} 局 · ${pct(lane.share)}"></i>`).join('')}</div>
        <div class="tp-bpo-dist-legend">${lanes.map((lane) => `<span><i class="${bpoLaneClass(lane.key)}"></i>${esc(lane.key)} <b>${pct(lane.share)}</b></span>`).join('')}</div>`;
    };
    const bpoBanSlots = bpOrder?.banSlots || {own: [], enemy: []};
    const bpoSlotCount = Math.max(0, ...(bpoBanSlots.own || []).map((row) => row.slot), ...(bpoBanSlots.enemy || []).map((row) => row.slot));
    const bpoBanSeq = bpoSlotCount ? `<div class="tp-bpo-bseq">
      <div class="tp-bpo-bseq-head"><span></span><b>我方</b><b>对方</b></div>
      ${Array.from({length: bpoSlotCount}, (_, index) => {
        const slot = index + 1;
        const own = (bpoBanSlots.own || []).find((row) => row.slot === slot);
        const enemy = (bpoBanSlots.enemy || []).find((row) => row.slot === slot);
        return `<div class="tp-bpo-bseq-row"><small>第 ${slot} ban</small><div>${bpoChips(own?.heroes || [], 2)}</div><div>${bpoChips(enemy?.heroes || [], 2)}</div></div>`;
      }).join('')}
    </div>` : '<p class="tp-quiet">—</p>';
    const bpoProvenance = bpOrder?.assumedGames
      ? `显式手序 ${fmt(bpOrder.verifiedGames)} 局，按营地名单顺序套 20 手模板 ${fmt(bpOrder.assumedGames)} 局（假设，不是逐手核验）`
      : (bpOrder?.verifiedGames ? `显式手序 ${fmt(bpOrder.verifiedGames)} 局` : '顺序来源待核验');
    const bpOrderCard = bpOrder?.eventsKnown ? tpCard('BP 时序', `有顺序 ${fmt(bpOrder.knownGames)} / ${fmt(bpOrder.totalGames)} 局 · 显式 ${fmt(bpOrder.verifiedGames)}`, `<div class="tp-bpo">
      <div class="tp-bpo-block"><header><b>对手第一手</b><small>首个 Pick 分路 · ${fmt(bpOrder.knownGames)} 局</small></header>${bpoBars(bpOrder.firstPicks?.lanes || [])}${bpoChips(bpOrder.firstPicks?.heroes || [], 5)}</div>
      <div class="tp-bpo-block"><header><b>ban 顺序</b><small>每手前 2 · 5 手</small></header>${bpoBanSeq}</div>
    </div>
    <div class="tp-bpo-block"><header><b>我们 ban → 他们第一手</b><small>条件分布 · 不是因果</small></header>
      <div class="tp-bpo-rows">${(bpOrder.banResponse || []).map((row) => `<div class="tp-bpo-row"><span class="tp-bpo-ban">${esc(row.hero)}</span><small>${fmt(row.games)} 局</small><div class="tp-bpo-rowdist">${bpoDist(row)}</div></div>`).join('') || '<p class="tp-quiet">—</p>'}</div>
    </div>
    <p class="tp-read">顺序：${bpoProvenance}；ban 顺序按我方/对方各自的 ban 次序（全局交替）；第一手=对手该局第一个 Pick，不是全局一抢；分路未标注单列；ban 后第一手是条件分布，不代表因果；没有顺序的局不计入。</p>`) : '';

    const banMatchup = deep?.banMatchup || null;
    const banReplacement = deep?.banReplacement || null;
    const poolDepth = deep?.poolDepth || null;
    const tpScatLaneClass = (lane) => TM_LANES.includes(lane) ? `tp-lane-${TM_LANES.indexOf(lane)}` : 'tp-lane-unlabeled';
    const tpScatFill = (lane) => TM_LANES.includes(lane) ? `var(--tp-lane-${TM_LANES.indexOf(lane)})` : 'var(--tp-quiet)';
    const tpScatHash = (value) => {
      let hash = 0;
      for (const ch of String(value || '')) hash = (hash * 31 + ch.charCodeAt(0)) % 17;
      return hash;
    };
    const tpScatLegend = () => `<div class="tp-scatter-legend">${TM_LANES.map((lane, index) => `<span><i class="tp-lane-${index}"></i>${lane}</span>`).join('')}<span><i class="tp-lane-unlabeled"></i>未标注</span></div>`;
    const tpScatterSvg = (points, opts) => {
      const {xKey, yKey, winKey, xLabel, yLabel} = opts;
      const labelPoints = [...points].sort((a, b) => ((b[yKey] || 0) + (b[xKey] || 0)) - ((a[yKey] || 0) + (a[xKey] || 0))).slice(0, 6);
      const labelSet = new Set(labelPoints.map((point) => point.hero));
      const pos = (point) => {
        const x = Number.isFinite(point[xKey]) ? point[xKey] : 0;
        const y = Number.isFinite(point[yKey]) ? point[yKey] : 0;
        const jitter = x === 0 ? ((tpScatHash(point.hero) % 7) - 3) * 0.55 : 0;
        return {x: Math.max(4, Math.min(96, 6 + x * 0.88 + jitter)), y: Math.max(4, Math.min(96, 94 - y * 0.88))};
      };
      const ticks = [0, 20, 50, 80, 100];
      const tickX = (v) => 6 + v * 0.88;
      const tickY = (v) => 94 - v * 0.88;
      const labelYs = new Map();
      let lastLabelY = -99;
      for (const point of [...labelPoints].sort((a, b) => pos(a).y - pos(b).y)) {
        const y = Math.max(pos(point).y, lastLabelY + 4.1);
        labelYs.set(point.hero, Math.min(92, y));
        lastLabelY = y;
      }
      return `<svg class="tp-scatter-svg" viewBox="0 0 100 100" role="img" aria-label="${esc(xLabel)}与${esc(yLabel)}散点">
        <rect x="6" y="6" width="88" height="88" class="tp-scatter-frame"></rect>
        ${ticks.map((v) => `<line x1="${tickX(v)}" y1="6" x2="${tickX(v)}" y2="94" class="tp-scatter-grid"></line><text x="${tickX(v)}" y="98.4" class="tp-scatter-tick" text-anchor="middle">${v}</text>`).join('')}
        ${ticks.map((v) => `<line x1="6" y1="${tickY(v)}" x2="94" y2="${tickY(v)}" class="tp-scatter-grid"></line><text x="4" y="${tickY(v) + 1}" class="tp-scatter-tick" text-anchor="end">${v}</text>`).join('')}
        <line x1="${tickX(20)}" y1="6" x2="${tickX(20)}" y2="94" class="tp-scatter-threshold"></line>
        <line x1="6" y1="${tickY(20)}" x2="94" y2="${tickY(20)}" class="tp-scatter-threshold"></line>
        ${points.map((point) => {
          const {x, y} = pos(point);
          const wr = point[winKey];
          const radius = wr == null ? 0.55 : 0.85 + Math.max(0, Math.min(100, wr)) / 100 * 1.35;
          const rightEdge = x > 78;
          const label = labelSet.has(point.hero) ? `<text x="${rightEdge ? x - 1.5 : x + 1.5}" y="${(labelYs.get(point.hero) ?? y) - 1.3}" class="tp-scatter-label" text-anchor="${rightEdge ? 'end' : 'start'}">${esc(point.hero)}</text>` : '';
          const waste = opts.markWaste && (point.pickRate || 0) <= 8 && (point.banRate || 0) >= 8;
          const tip = `${point.hero}：${xLabel} ${pct(point[xKey])}（${fmt(point.pickGames)} 局）· ${yLabel} ${pct(point[yKey])}（${fmt(point.banGames)} 局）· 被选时胜率 ${pct(point[winKey])}`;
          return `<a href="${route('hero', point.hero)}" class="tp-scatter-point"><circle cx="${x}" cy="${y}" r="${radius}" fill="${tpScatFill(point.lane)}" class="tp-scat-dot${wr == null ? ' is-empty' : ''}${waste ? ' is-waste' : ''}"><title>${esc(tip)}</title></circle>${label}</a>`;
        }).join('')}
      </svg>`;
    };
    const tpScatterPanel = (block, opts) => {
      const allPoints = block?.points || [];
      const points = allPoints.filter((point) => (point.pickGames || 0) > 0 || (point.banGames || 0) >= 2);
      const target = block?.targeting || {};
      const shown = points.length ? points : allPoints;
      if (!shown.length) return `<div class="tp-scatter-panel">${tpLack('还没有双方都有的选人 / ban 明细。')}</div>`;
      const xKey = opts.xKey, yKey = opts.yKey;
      const q = (xHigh, yHigh) => shown.filter((point) => ((point[xKey] || 0) >= 20) === xHigh && ((point[yKey] || 0) >= 20) === yHigh).length;
      return `<div class="tp-scatter-panel">
        <header><b>${opts.title}</b><span>${opts.meta}</span></header>
        <div class="tp-target-metrics">
          <div><small>${opts.hitLabel}</small><b>${pct(target.targetRate)}</b><em>${fmt(target.hitEvents)} / ${fmt(target.banEvents)} 次 ban</em></div>
          <div><small>随机期望</small><b>${pct(target.randomRate)}</b><em>按${opts.randomLabel}频率</em></div>
          <div><small>倍数</small><b>${target.lift == null ? '—' : `${fmt(target.lift, 2)}×`}</b><em>命中 / 随机</em></div>
        </div>
        <div class="tp-scatter-axis"><span class="tp-scatter-y">${opts.yLabel}</span><div>${tpScatterSvg(shown, opts)}<span class="tp-scatter-x">${opts.xLabel}</span></div></div>
        ${tpScatLegend()}
        <div class="tp-scatter-quads">
          <span><span class="tp-quad-label">常用·高 ban<small>${opts.quadNotes?.[0] || '尊重 / 针对'}</small></span><b>${q(true, true)}</b></span>
          <span><span class="tp-quad-label">低用·高 ban<small>${opts.quadNotes?.[1] || '可能怕体系'}</small></span><b>${q(false, true)}</b></span>
          <span><span class="tp-quad-label">常用·低 ban<small>${opts.quadNotes?.[2] || '放给'}</small></span><b>${q(true, false)}</b></span>
          <span><span class="tp-quad-label">低用·低 ban<small>${opts.quadNotes?.[3] || '无关'}</small></span><b>${q(false, false)}</b></span>
        </div>
        <p class="tp-scatter-read">${opts.hitLabel} ${pct(target.targetRate)}，${target.lift == null ? '—' : target.lift < 0.85 ? '低于随机' : target.lift > 1.15 ? '高于随机' : '接近随机'}（随机 ${pct(target.randomRate)}）。</p>
        <div class="tp-scatter-top"><small>${opts.topLabel}</small>${(target.top || []).map((row) => heroLink(row.hero, row.games)).join('')}</div>
      </div>`;
    };
    const banPoolCard = banMatchup?.games ? tpCard('Ban × 英雄池', `${fmt(banMatchup.games)} 局 · 双向`, `<div class="tp-grid is-2">
      ${tpScatterPanel(banMatchup.theirBansVsOurPool, {
        title: '他们 ban × 我们常用', meta: '他们的 ban，落在我们的池里',
        xKey: 'pickRate', yKey: 'banRate', winKey: 'pickWinRate',
        xLabel: '我方出场率', yLabel: '他们 ban 率', hitLabel: '针对率',
        randomLabel: '我方选人', topLabel: '我方 top5',
        quadNotes: ['尊重 / 针对', '可能怕体系', '放给我们', '无关'],
      })}
      ${tpScatterPanel(banMatchup.ourBansVsTheirPool, {
        title: '我们 ban × 他们常用', meta: '我们的 ban，落在他们的池里',
        xKey: 'pickRate', yKey: 'banRate', winKey: 'pickWinRate',
        xLabel: '他们出场率', yLabel: '我们 ban 率', hitLabel: '命中率',
        randomLabel: '他们选人', topLabel: '他们 top5', markWaste: true,
        quadNotes: ['我们针对', '可能浪费 / 怕体系', '放给他们', '无关'],
      })}
    </div><p class="tp-read">点大小=该英雄被选时的胜率，空心=没有选过；右图红圈=我们低使用率被 ban（他们出场 ≤8%）；只画出场 ≥1 局或被 ban ≥2 次的英雄；虚线=20% 门槛；同位置点有轻微抖动。针对率=ban 事件命中对方 top5 的比例，随机期望按对方实际选人频率计算；ban 次数与出场局数不同，分母见 tooltip。</p>`) : '';

    const tpBanStack = (rows, kind = 'lane') => {
      if (!rows?.length) return '<p class="tp-quiet">—</p>';
      const color = (row, index) => kind === 'lane'
        ? {class: tpScatLaneClass(row.key)}
        : {style: `background:color-mix(in srgb, var(--accent) ${74 - Math.min(5, index) * 10}%, var(--paper))`};
      return `<div class="tp-ban-stack">${rows.map((row, index) => `<i class="${color(row, index).class || ''}" style="${color(row, index).style ? color(row, index).style + ';' : ''}flex:${Math.max(1, row.games)}" title="${esc(row.key)} ${fmt(row.games)} 次 · ${pct(row.share)}"></i>`).join('')}</div>
        <div class="tp-ban-stack-legend">${rows.map((row, index) => `<span><i class="${color(row, index).class || ''}" style="${color(row, index).style || ''}"></i>${esc(row.key)} <b>${pct(row.share)}</b></span>`).join('')}</div>`;
    };
    const tpTargetMini = (label, games, rows) => `<div class="tp-target-mini"><small>${label} · ${fmt(games)} 局</small><div>${(rows || []).map((row) => `<a href="${route('hero', row.hero)}">${esc(row.hero)} <b>${fmt(row.games)}</b></a>`).join('') || '<span class="tp-quiet">—</span>'}</div></div>`;
    const banShapeCard = banMatchup?.games ? (() => {
      const their = banMatchup.theirBansVsOurPool || {};
      const ours = banMatchup.ourBansVsTheirPool || {};
      const side = their.sideSplit || {};
      const period = their.periodSplit || {};
      return tpCard('Ban 形状', `${fmt(banMatchup.games)} 局 · 分路 / 边 / 时间`, `<div class="tp-grid is-2">
        <div class="tp-shape-panel"><header><b>他们 ban 的分路</b><small>按 ban 事件</small></header><small class="tp-stack-label">分路</small>${tpBanStack(their.laneDist)}
          <div class="tp-split-grid">
            ${['blue', 'red'].map((key) => tpTargetMini(`他们${key === 'blue' ? '蓝方' : '红方'}`, side[key]?.games, side[key]?.top)).join('')}
            ${tpTargetMini(`前 ${fmt(period.first?.games || 0)} 局`, period.first?.games, period.first?.top)}
            ${tpTargetMini(`后 ${fmt(period.last?.games || 0)} 局`, period.last?.games, period.last?.top)}
          </div>
        </div>
        <div class="tp-shape-panel"><header><b>我们 ban 的分路 / 类型</b><small>按 ban 事件</small></header><small class="tp-stack-label">分路</small>${tpBanStack(ours.laneDist)}<small class="tp-stack-label">类型</small>${tpBanStack(ours.typeDist, 'type')}
          <div class="tp-waste"><small>低使用率被 ban · 他们出场 ≤8%</small>${(ours.waste || []).slice(0, 4).map((row) => `<a href="${route('hero', row.hero)}">${esc(row.hero)}<em>我们 ban ${fmt(row.banGames)} 次 · 他们 ${fmt(row.pickGames)} 局</em></a>`).join('') || '<span class="tp-quiet">没有命中低使用率英雄</span>'}</div>
        </div>
      </div><p class="tp-read">分路/类型按 ban 事件计，重复 ban 也计入；未标注单列。低使用率被 ban 只描述“ban 了但对面很少选”，不等于 ban 错，可能是怕特定体系；条件关联，不是因果。</p>`);
    })() : '';

    const tpReplacementRow = (row) => {
      const replacements = (row.replacements || []).slice(0, 2).map((item) => heroLink(item.hero, item.games)).join('');
      const player = row.playerCount > 3
        ? `${row.lane || '同分路'} · ${fmt(row.playerCount)} 名选手轮换`
        : `${row.lane || '同分路'} · ${(row.players || []).slice(0, 2).map((item) => esc(item.name)).join(' / ') || '—'}`;
      return `<tr>
        <td data-label="我们 ban"><b>${esc(row.hero)}</b><small>${esc(row.archetype || '未标注')}</small></td>
        <td data-label="局数">${fmt(row.games)}</td>
        <td data-label="替代英雄"><b>${fmt(row.distinct)}</b><small>个英雄</small></td>
        <td data-label="有效替代"><b>${fmt(row.effective, 1)}</b><small>集中度折算</small></td>
        <td data-label="同类型 / 跨类型"><b>${pct(row.sameTypeRate)}</b><small>同类型 / 跨 ${pct(row.crossTypeRate)}</small></td>
        <td data-label="主要替代 / 吸收者"><div class="tp-repl-als">${replacements || '<span class="tp-quiet">—</span>'}<small>${esc(player)}</small></div></td>
        <td data-label="对手胜率（95%）"><b>${pct(row.oppWinRate)}</b><small>${row.wilson ? `${fmt(row.wilson[0], 0)}–${fmt(row.wilson[1], 0)}% · ` : ''}${row.delta == null ? '' : `较基线 ${row.delta > 0 ? '+' : ''}${fmt(row.delta, 1)} 个点 · `}${fmt(row.oppWins)} 胜 ${fmt((row.games || 0) - (row.oppWins || 0))} 负</small></td>
      </tr>`;
    };
    const replacementCard = banReplacement?.rows?.length ? (() => {
      const matrix = banReplacement.matrix || {};
      const rows = matrix.rows || [], columns = matrix.columns || [];
      const cells = new Map((matrix.cells || []).map((cell) => [`${cell.row}|${cell.col}`, cell.games]));
      const maxCell = Math.max(1, ...(matrix.cells || []).map((cell) => cell.games));
      const matrixHtml = rows.length ? `<div class="tp-repl-matrix-wrap"><div class="tp-repl-matrix" style="grid-template-columns:64px repeat(${columns.length}, minmax(30px, 1fr))">
        <span></span>${columns.map((col) => `<b>${esc(col)}</b>`).join('')}
        ${rows.map((row) => `<span class="tp-repl-mrow">${esc(row)}</span>${columns.map((col) => {
          const n = cells.get(`${row}|${col}`) || 0;
          const alpha = n ? 10 + Math.round(n / maxCell * 52) : 0;
          return `<i class="${n ? 'is-on' : ''}" style="${n ? `background:color-mix(in srgb, var(--accent) ${alpha}%, var(--paper))` : ''}" title="${esc(row)} → ${esc(col)}：${fmt(n)} 局">${n || ''}</i>`;
        }).join('')}`).join('')}
      </div></div>` : '';
      return tpCard('Ban 后的替代结构', `${fmt(banReplacement.games)} 局 · 同分路`, `<div class="tp-table-wrap"><table class="tp-table tp-repl-table">
        <thead><tr><th>我们 ban</th><th>局数</th><th>替代英雄</th><th>有效替代</th><th>同类型 / 跨类型</th><th>主要替代 / 吸收者</th><th>对手胜率（95%）</th></tr></thead>
        <tbody>${banReplacement.rows.slice(0, 6).map(tpReplacementRow).join('')}</tbody></table></div>
        <div class="tp-repl-bottom">
          <div class="tp-trans-list"><small>主要类型转移</small>${(matrix.top || []).slice(0, 7).map((item) => `<div><span>${esc(item.from)} → ${esc(item.to)}</span><b>${fmt(item.games)}</b></div>`).join('') || '<p class="tp-quiet">—</p>'}</div>
          <div><small class="tp-matrix-title">类型转移矩阵 · 行=我们 ban，列=他们替代</small>${matrixHtml}</div>
        </div>
        <p class="tp-read">替代=同一分路对手实际选人；有效替代=按出场集中度折算（越接近替代英雄数越分散）；同类型=替补类型与原 ban 类型相同。吸收者只列稳定选手，轮换时显示人数。对手胜率来自 Ban 与结果，条件关联，不是因果。</p>`);
    })() : '';

    const poolDepthCard = poolDepth?.lanes?.length ? tpCard('英雄池深度 · 五路', `对手 · ${fmt(poolDepth.games)} 局`, `<div class="tp-table-wrap"><table class="tp-table tp-pool-table">
      <thead><tr><th>分路</th><th>英雄 / 有效</th><th>top1 / top2</th><th>去 top1 后</th><th>替补（KPL 成阵）</th></tr></thead>
      <tbody>${poolDepth.lanes.map((row) => `<tr>
        <td data-label="分路"><b>${esc(row.lane)}</b><small>${fmt(row.games)} 次选人</small></td>
        <td data-label="英雄 / 有效"><b>${fmt(row.heroes)}</b><small>有效 ${fmt(row.effective, 1)}</small></td>
        <td data-label="top1 / top2"><div class="tp-pool-tops">${row.top1 ? `<span><b>${esc(row.top1.hero)}</b><small>${pct(row.top1.share)}</small></span>` : ''}${row.top2 ? `<span><b>${esc(row.top2.hero)}</b><small>${pct(row.top2.share)}</small></span>` : ''}</div></td>
        <td data-label="去 top1 后">${row.afterTop1 ? `<b>${fmt(row.afterTop1.heroes)}</b><small>有效 ${fmt(row.afterTop1.effective, 1)}</small>` : '—'}</td>
        <td data-label="替补（KPL 成阵）"><div class="tp-pool-backups">${(row.backups || []).slice(0, 2).map((item) => `<span>${esc(item.hero)} <b>${pct(item.share)}</b><small>KPL ${item.kplWinRate == null ? '—' : pct(item.kplWinRate)} · ${fmt(item.kplGames)} 局</small></span>`).join('') || '<span class="tp-quiet">—</span>'}</div></td>
      </tr>`).join('')}</tbody></table></div><p class="tp-read">有效英雄数=按出场集中度折算；top1/top2 是出场份额；去 top1 后看剩余池的宽度。KPL 列为五人成阵聚合的英雄出场/胜率，不是官方英雄榜；只作外部参照。</p>`) : '';

    const rules = [];
    const addRule = (kind, label, test) => {
      let games = 0, wins = 0;
      for (const game of decidedGames) {
        if (!test(game)) continue;
        games++;
        if (game.opponentWin === true) wins++;
      }
      if (games < 4) return;
      const conf = wins / games * 100;
      rules.push({kind, label, games, wins, losses: games - wins, conf, lift: baseRate ? conf / baseRate : null, ci: wilson95(wins, games)});
    };
    addRule('边', '对手蓝方', (game) => game.ownSide === 'red');
    addRule('边', '对手红方', (game) => game.ownSide === 'blue');
    const supportTypes = new Map();
    for (const game of deepGames) {
      const pick = enemyPickOf(game, '游走');
      if (pick?.archetype && !isUnlabeled(pick.archetype)) supportTypes.set(pick.archetype, (supportTypes.get(pick.archetype) || 0) + 1);
    }
    for (const [type, count] of supportTypes) {
      if (count >= 4) addRule('辅助', type, (game) => enemyPickOf(game, '游走')?.archetype === type);
    }
    for (const row of edgeMap.values()) {
      if (row.games >= 4) addRule('边野', row.key, (game) => {
        const edge = enemyPickOf(game, '对抗路'), jungle = enemyPickOf(game, '打野');
        return Boolean(edge?.archetype && jungle?.archetype && `${edge.archetype} + ${jungle.archetype}` === row.key);
      });
    }
    for (const [hero, count] of [...heroPickCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)) {
      if (count >= 4) addRule('英雄', hero, (game) => (game.sides?.enemy?.picks || []).some((pick) => pick.name === hero));
    }
    const ruleHigh = rules.filter((rule) => rule.lift != null && rule.lift >= 1).sort((a, b) => b.lift - a.lift).slice(0, 5);
    const ruleLow = rules.filter((rule) => rule.lift != null && rule.lift < 1).sort((a, b) => a.lift - b.lift).slice(0, 3);
    const ruleRow = (rule) => {
      const ci = rule.ci ? [Math.max(0, rule.ci[0]), Math.min(100, rule.ci[1])] : null;
      const lift = hasNum(rule.lift) ? Math.max(0, Math.min(2.5, rule.lift)) : null;
      return `<tr>
        <td><span class="tp-quiet">${esc(rule.kind)}</span> <b>${esc(rule.label)}</b></td>
        <td>${fmt(rule.games)}</td>
        <td>${fmt(rule.wins)}–${fmt(rule.losses)}</td>
        <td><div class="tp-wrci"><div><b>${pct(rule.conf)}</b><small>${ci ? `${fmt(ci[0], 0)}–${fmt(ci[1], 0)}%` : '—'}</small></div><span class="tp-ci"><i style="left:${ci ? ci[0] : 0}%;width:${ci ? ci[1] - ci[0] : 0}%"></i><em style="left:${rule.conf}%"></em></span></div></td>
        <td><div class="tp-lift"><span class="tp-lift-track"><em></em><i class="${rule.lift >= 1 ? 'is-up' : 'is-down'}" style="left:${lift == null ? 0 : lift / 2.5 * 100}%"></i></span><b>${rule.lift == null ? '—' : fmt(rule.lift, 2)}</b></div></td>
      </tr>`;
    };
    const bpBanOutcome = bpOrder?.banOutcome || [];
    const banOutcomeCard = bpBanOutcome.length ? tpCard('Ban 与结果', `ban 名单 ${fmt(bpOrder.banOutcomeGames ?? bpOrder.knownGames)} 局 · 基线 ${pct(bpOrder.banOutcomeBaseRate ?? bpOrder.baseRate)}`, `<div class="tp-table-wrap"><table class="tp-table">
      <thead><tr><th>我们 ban</th><th>局数</th><th>对手胜率（95% 区间）</th><th>对手相对基线</th><th>对手战绩</th></tr></thead>
      <tbody>${bpBanOutcome.map((row) => `<tr>
        <td><b>${esc(row.hero)}</b></td>
        <td>${fmt(row.games)}</td>
        <td><div class="tp-wrci"><div><b>${pct(row.rate)}</b><small>${fmt(row.wilson?.[0], 0)}–${fmt(row.wilson?.[1], 0)}%</small></div><span class="tp-ci"><i style="left:${row.wilson?.[0] ?? 0}%;width:${row.wilson ? row.wilson[1] - row.wilson[0] : 0}%"></i><em style="left:${row.rate}%"></em></span></div></td>
        <td class="${row.delta > 0 ? 'is-up' : row.delta < 0 ? 'is-down' : ''}">${row.delta > 0 ? '+' : ''}${fmt(row.delta, 1)} 个点</td>
        <td>${fmt(row.oppWins)} 胜 ${fmt(row.games - row.oppWins)} 负</td>
      </tr>`).join('')}</tbody></table></div>
      <p class="tp-read">只用终局 ban 名单，不要求手序；这是条件关联，不是因果；受我方阵容、边、选手状态影响；未做多重比较校正；样本 <4 局不展示。</p>`) : '';
    const rulesCard = tpCard('结果关联', `整体对手胜率 ${pct(baseRate)} · 只展示 ≥4 局的条件`, rules.length
      ? `<div class="tp-table-wrap"><table class="tp-table"><thead><tr><th>条件</th><th>局数</th><th>胜负</th><th>条件胜率（95% 区间）</th><th>提升（vs 整体）</th></tr></thead><tbody>
        ${ruleHigh.map(ruleRow).join('')}${ruleHigh.length && ruleLow.length ? '<tr class="is-group"><td colspan="5">低于整体</td></tr>' : ''}${ruleLow.map(ruleRow).join('')}
      </tbody></table></div><p class="tp-read">提升 = 条件内胜率 / 整体胜率，虚线 1.0 = 与整体持平；区间为 Wilson 95%。这是关联，不是因果；条件之间可能重叠，不能相加；未做多重比较校正，仅供探索。</p>`
      : tpLack('条件样本不足 4 局，暂不做关联。'));

    const chrono = [...decidedGames].sort((a, b) => String(a.start || a.day || '').localeCompare(String(b.start || b.day || '')));
    const rolling = chrono.map((game, index) => {
      const window = chrono.slice(Math.max(0, index - 4), index + 1);
      const wins = window.filter((item) => item.opponentWin === true).length;
      return {rate: window.length ? wins / window.length * 100 : null, game};
    });
    const sparkW = 600, sparkH = 110, sparkPad = 10;
    const sparkY = (rate) => sparkPad + (1 - Math.max(0, Math.min(100, rate)) / 100) * (sparkH - sparkPad * 2);
    const sparkPoints = rolling.map((row, index) => {
      const x = rolling.length <= 1 ? sparkW / 2 : index / (rolling.length - 1) * sparkW;
      return `${x.toFixed(1)},${sparkY(row.rate).toFixed(1)}`;
    }).join(' ');
    const sparkLast = rolling[rolling.length - 1];
    const spark = rolling.length > 1
      ? `<div class="tp-sparkwrap"><div class="tp-spark-head"><span>近 5 局滚动胜率</span><b>${pct(sparkLast?.rate)}</b></div><svg class="tp-spark" viewBox="0 0 ${sparkW} ${sparkH}" preserveAspectRatio="none" role="img" aria-label="近 5 局滚动胜率">
          <line x1="0" y1="${sparkH / 2}" x2="${sparkW}" y2="${sparkH / 2}" class="tp-spark-base"/>
          <polyline points="${sparkPoints}" class="tp-spark-line"/>
          <circle cx="${(sparkW - 3).toFixed(1)}" cy="${sparkY(sparkLast?.rate ?? 0).toFixed(1)}" r="3" class="tp-spark-dot"/>
        </svg><div class="tp-spark-axis"><span>${text(chrono[0]?.day || '')}</span><span>${text(chrono[chrono.length - 1]?.day || '')}</span></div></div>`
      : '';
    const changePart = (list) => {
      const wins = list.filter((game) => game.opponentWin === true).length;
      const durations = list.map((game) => game.duration).filter(hasNum);
      const goldDiffs = list.map((game) => {
        const enemyGold = game.sides?.enemy?.stats?.gold, ownGold = game.sides?.own?.stats?.gold;
        return hasNum(enemyGold) && hasNum(ownGold) ? enemyGold - ownGold : null;
      }).filter(hasNum);
      const edges = new Map();
      for (const game of list) {
        const edge = enemyPickOf(game, '对抗路'), jungle = enemyPickOf(game, '打野');
        if (!edge?.archetype || !jungle?.archetype || isUnlabeled(edge.archetype) || isUnlabeled(jungle.archetype)) continue;
        const key = `${edge.archetype}+${jungle.archetype}`;
        edges.set(key, (edges.get(key) || 0) + 1);
      }
      const topEdge = [...edges.entries()].sort((a, b) => b[1] - a[1])[0];
      return {n: list.length, wins, rate: list.length ? wins / list.length * 100 : null, duration: meanOf(durations), gold: meanOf(goldDiffs), edge: topEdge ? `${topEdge[0]}（${topEdge[1]} 局）` : '—'};
    };
    const cut = Math.ceil(chrono.length / 2);
    const early = changePart(chrono.slice(0, cut));
    const late = changePart(chrono.slice(cut));
    const deltaText = (a, b, digits = 0, unit = '') => {
      if (!hasNum(a) || !hasNum(b)) return '—';
      const diff = b - a;
      return `${diff > 0 ? '+' : ''}${fmt(diff, digits)}${unit}`;
    };
    const goldDiffs = decidedGames.map((game) => {
      const enemyGold = game.sides?.enemy?.stats?.gold, ownGold = game.sides?.own?.stats?.gold;
      return hasNum(enemyGold) && hasNum(ownGold) ? {game, value: enemyGold - ownGold} : null;
    }).filter(Boolean);
    const goldMean = meanOf(goldDiffs.map((row) => row.value));
    const goldSd = goldDiffs.length > 1 && hasNum(goldMean)
      ? Math.sqrt(goldDiffs.reduce((sum, row) => sum + (row.value - goldMean) ** 2, 0) / (goldDiffs.length - 1))
      : null;
    const outliers = goldSd
      ? goldDiffs.map((row) => ({...row, z: (row.value - goldMean) / goldSd})).sort((a, b) => Math.abs(b.z) - Math.abs(a.z)).slice(0, 3)
      : [];
    const outlierRows = outliers.map((row) => `<div class="tp-outlier"><span>${text(row.game.day || row.game.start)}</span><i class="tp-ev-res ${row.game.opponentWin ? 'is-win' : 'is-loss'}">${row.game.opponentWin ? '对手胜' : '本队胜'}</i><b>${row.value > 0 ? '+' : ''}${fmt(row.value)}</b><small>z ${fmt(row.z, 1)}</small>${row.game.matchKey ? `<a class="tp-row-link" href="${route('match', row.game.matchKey)}">复盘 ↗</a>` : ''}</div>`).join('');
    const changeCard = tpCard('变化与异常', `${fmt(early.n)} 局 / ${fmt(late.n)} 局 · 按时间对半`, spark + `<div class="tp-table-wrap"><table class="tp-table">
      <thead><tr><th>指标</th><th>前段</th><th>后段</th><th>变化</th></tr></thead>
      <tbody>
        <tr><td>对手胜率</td><td>${pct(early.rate)}</td><td>${pct(late.rate)}</td><td>${deltaText(early.rate, late.rate, 1, ' 个点')}</td></tr>
        <tr><td>场均时长</td><td>${time(early.duration)}</td><td>${time(late.duration)}</td><td>${deltaText(early.duration, late.duration, 0, ' 秒')}</td></tr>
        <tr><td>终局经济差</td><td>${hasNum(early.gold) ? `${early.gold > 0 ? '+' : ''}${fmt(early.gold)}` : '—'}</td><td>${hasNum(late.gold) ? `${late.gold > 0 ? '+' : ''}${fmt(late.gold)}` : '—'}</td><td>${deltaText(early.gold, late.gold, 0)}</td></tr>
        <tr><td>主要边野</td><td>${esc(early.edge)}</td><td>${esc(late.edge)}</td><td>—</td></tr>
      </tbody></table></div>
      ${outlierRows ? `<div class="tp-outliers"><b>经济差异常局</b>${outlierRows}</div>` : ''}
      <p class="tp-read">只描述前后差异；没有时间轴与版本标签，不判断原因。</p>`);

    /* ── 页脚：数据质量 + 命名维护 ─────────────────────────────── */
    const archetypeCount = oppPicks.filter((p) => p.archetype).length;
    const quality = [
      ['对局面板', matches ? `${fmt(matches)} 局` : '缺失', matches > 0],
      ['当前阵容', `${fmt(currentPlayers.length)} / 5 人`, currentPlayers.length >= 5],
      ['英雄明细', `${fmt(new Set(oppPicks.map((p) => p.hero)).size)} 个`, oppPicks.length > 0],
      ['BP 明细', bpTeam?.available ? '可用' : bpTeam ? '部分' : '缺失', !!bpTeam?.available],
      ['深度数据', deep ? '可用' : '缺失（页面已降级）', !!deep],
      ['英雄类型标注', archetypeCount ? `${fmt(archetypeCount)} 个英雄` : '缺失', archetypeCount > 0],
      ['KPL 命中', kplHits.length ? `${fmt((kpl?.hits || []).length)} 组` : '无命中', kplHits.length > 0],
      ['样本门槛', thin ? '不足 3 局' : '达标', !thin],
    ];
    const qualityWarnings = [...(deep?.meta?.warnings || []), ...(cmp.warnings || [])].filter(Boolean);
    const qualityLimits = [...(deep?.meta?.limits || []), ...(deep ? [] : ['深度数据未就绪：逐局风格、体系胜率、KPL 命中暂时显示「证据不足」。'])];
    const qualityPanel = `<article class="tp-card"><header class="tp-card-head"><h3>数据质量</h3><span>${fmt(quality.filter((x) => x[2]).length)} / ${fmt(quality.length)} 项</span></header>
      <div class="tp-quality">${quality.map(([label, value, ok]) => `<div class="tp-qitem ${ok ? 'is-ok' : 'is-warn'}"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div>
      ${qualityWarnings.length ? `<p class="tp-read is-warn">${esc(qualityWarnings.join('；'))}</p>` : ''}
      ${qualityLimits.length ? `<ul class="tp-limits">${qualityLimits.map((line) => `<li>${esc(line)}</li>`).join('')}</ul>` : ''}
      <p class="tp-read">数据来源：${esc(deep?.meta?.source || '营地终局面板')}${kpl ? ` + ${esc(kpl.source || 'KPL 官方赛事')}（${fmt(kpl.games)} 场）` : ''}。</p></article>`;
    const renamePanel = `<article class="tp-card"><header class="tp-card-head"><h3>命名与维护</h3><span>${t.named ? '已命名' : '待命名'}</span></header>${form('rename', `<input type="hidden" name="id" value="${esc(t.id)}">` + field('战队名称', 'name', t.name || '', 'required maxlength="40"'), '保存名称')}<p class="tp-read">命名后，对局、BP 与报告里的对手都会显示这个名字。</p></article>`;
    const footer = `<details class="tp-footer"><summary><div><b>数据质量与命名维护</b><small>覆盖情况、样本门槛、口径限制与战队主数据</small></div><span>展开</span></summary><div class="tp-footer-grid">${qualityPanel}${renamePanel}</div></details>`;
    /* ── 组装 ─────────────────────────────────────────────────────── */
    const sec = (id, no, title, sub, chip, body) => `<section class="tp-sec" id="${id}" data-no="${no}">
      <header class="tp-sec-head"><div class="tp-sec-title"><h2>${title}</h2>${chip ? `<span class="tp-sec-chip">${esc(chip)}</span>` : ''}</div><p class="tp-sec-sub">${sub}</p><button type="button" class="tp-sec-toggle" data-tp-toggle aria-expanded="false" aria-controls="${id}-body">展开</button></header>
      <div class="tp-sec-body" id="${id}-body">${body}</div>
    </section>`;
    const section01 = sec('tp-overview', '01', '样本与整体', '先看有多少局、结果如何，再看整体对照；这一层只描述样本。', thin ? '样本不足 3 局' : `${fmt(matches)} 局`, `<div class="tp-grid is-2-1">${overviewCard}${formCard}</div>`);
    const bpDetails = [bpOrderCard, banPoolCard, banShapeCard].filter(Boolean).join('');
    const section02 = sec('tp-heroes', '02', '选人模式', '他们常选什么、先抢什么、先 ban 什么，以及双方 ban 与英雄池的错位；先描述，不判断强弱。', `${fmt(totalHeroes)} 个英雄`, heroCard + edgeCard + poolDepthCard + (bpDetails ? `<details class="tp-more-fold"><summary><b>BP 与 Ban 细节</b><span>时序、Ban × 英雄池、Ban 形状</span><em></em></summary><div class="tp-more-body">${bpDetails}</div></details>` : ''));
    const section03 = sec('tp-lineups', '03', '阵容组合', '主力组合在前，完整签名 / 双人 / 三人 / 对抗 / 资源收进组合库。', nEff >= 10 ? `有效 ${fmt(nEff)} 局` : `初步分布 · ${fmt(nEff)} 局`, systemsCard + libraryDetail + pairsDetail + seriesCard);
    const section04 = sec('tp-style', '04', '打法与资源', '资源分配、同位置对位、输出承伤与节奏；图由终局面板估算。', styleMain?.quadrant || (styleMain?.sufficient ? '分布分散' : '探索性'), styleCard + `<div class="tp-grid is-2">${structCard}${leadCard}</div>` + resourceCard);
    const banDetails = [banOutcomeCard, replacementCard].filter(Boolean).join('');
    const section05 = sec('tp-matchup', '05', '对位与关联', '五路同位置对照、ban 与结果、ban 后的替代结构；关联不是因果。', `${fmt(deepGames.length)} 局证据`, duelCard + rulesCard + (banDetails ? `<details class="tp-more-fold"><summary><b>Ban 证据明细</b><span>ban 与结果、ban 后的替代结构</span><em></em></summary><div class="tp-more-body">${banDetails}</div></details>` : '') + brief);
    const section06 = sec('tp-change', '06', '变化与异常', '按时间对半看描述项的变化，并列出经济差异常局。', `${fmt(early.n)} / ${fmt(late.n)} 局`, changeCard + (behaviorCard || ''));
    const section07 = sec('tp-evidence', '07', '证据与方法', '逐局证据、KPL 参照与口径；所有结论都能回到局。', `${fmt(deepGames.length)} 局`, evidenceCard + kplDetail);
    const copyText = [
      `玩家组：${oppName}`,
      `样本：${fmt(matches)} 局（本队 ${tmRecord(meta)}，对手胜率 ${pct(oppRate)}，场均 ${time(avgDuration)}）`,
      `经济：对手 ${pct(oppGoldTop?.share)} 给${oppGoldTop?.lane || '—'}，本队 ${pct(ownGoldTop?.share)} 给${ownGoldTop?.lane || '—'}`,
      `风格：${styleMain?.quadrant ? `偏「${styleMain.quadrant}」` : styleMain?.sufficient && quadRanked ? `四象限分散，${quadRanked[0]}最多` : '证据不足'}`,
      `最常选：${[...heroPickCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([hero, n]) => `${hero}×${n}`).join(' / ') || '—'}`,
      `常禁：${bpBans.slice(0, 4).map((row) => `${row.hero}×${row.count}`).join(' / ') || '—'}`,
      `本队常拿：${ourTopHeroes.map(([hero, n]) => `${hero}×${n}`).join(' / ') || '—'}`,
      `近 ${fmt(last10.length)} 局：${fmt(win10)} 胜 ${fmt(last10.length - win10)} 负`,
      '口径：全部营地面板；分析/挖掘，不构成建议',
    ].join('\n');
    const html = `<div class="page feature-page tp-page td-page">
      ${head}
      <nav class="tm-jump tp-jump" aria-label="页面目录">
        ${[['tp-overview', '01 样本'], ['tp-heroes', '02 选人'], ['tp-lineups', '03 阵容'], ['tp-style', '04 打法'], ['tp-matchup', '05 对位'], ['tp-change', '06 变化'], ['tp-evidence', '07 证据']].map(([id, label]) => `<button type="button" data-tm-jump="${id}">${label}</button>`).join('')}
      </nav>
      ${section01}${section02}${section03}${section04}${section05}${section06}${section07}${footer}
      <nav class="tp-bottom-nav" aria-label="快速切换">${[['tp-overview', '样本'], ['tp-heroes', '选人'], ['tp-lineups', '阵容'], ['tp-style', '打法'], ['tp-matchup', '对位'], ['tp-change', '变化'], ['tp-evidence', '证据']].map(([id, label]) => `<button type="button" data-tm-jump="${id}">${label}</button>`).join('')}</nav>
    </div>`;
    return html.replace('__TP_SUMMARY__', esc(copyText));
  }
  /* ── 战队训练（2026-11-08）──────────────────────────────────────────
     2026-11-14：跨队的「战队风格」「战队阵容」两页与单支战队分析重复，已下线；
     风格四象限、阵容体系、轮换与曾效力仍在点进战队后的详情页里，
     旧链接 #teamstyle / #teamroster 由 app.js 回落到 #teams。 */
  function teamTraining(value) {
    /* 有训练课的排前，其次按最近一次训练 / 交手日期；后端已排好，这里兜底旧服务。 */
    const teams = [...(value.teams || [])].sort((a, b) => (b.planCount > 0) - (a.planCount > 0)
      || String(b.lastSession || b.lastSeen || '').localeCompare(String(a.lastSession || a.lastSeen || ''))
      || String(a.displayName || '').localeCompare(String(b.displayName || ''), 'zh'));
    const summary = value.summary || {};
    const unassigned = value.unassigned || [];
    const statusLabels = {planned: '待进行', confirmed: '已确认', completed: '已完成', cancelled: '已取消'};
    const goalLabels = {pending: '未评估', achieved: '达成', partial: '部分达成', missed: '未达成'};
    const sessionCard = (session) => {
      const plan = session.source === 'plan';
      const goals = (session.goals || []).map((goal) => `<li class="is-${esc(goal.status)}">
        <span>${text(goal.label)}</span>${goal.target ? `<em>目标 ${text(goal.target)}</em>` : ''}<i>${goalLabels[goal.status] || '未评估'}</i></li>`).join('');
      const result = (session.wins || session.losses)
        ? `${fmt(session.wins)} 胜 ${fmt(session.losses)} 负` : '结果未记录';
      return `<article class="ttn-session is-${plan ? 'plan' : 'camp'}">
        <header>
          <span class="ttn-date"><b>${text(session.date || '日期未定')}</b><small>${text(session.time || '时间未定')}</small></span>
          <span class="ttn-badge is-${plan ? 'plan' : 'camp'}">${plan ? '训练课' : '交手日'}</span>
          <span class="ttn-meta">${plan ? text(statusLabels[session.status] || session.status || '待进行') : text(session.session || '营地记录')}</span>
          <span class="ttn-result">${result}${session.duration ? ` · ${time(session.duration)}` : ''}</span>
          ${plan ? `<span class="ttn-review is-${session.reviewStatus === 'done' ? 'done' : 'pending'}">${session.reviewStatus === 'done' ? '已复盘' : '待复盘'}</span>` : ''}
        </header>
        ${goals ? `<ul class="ttn-goals">${goals}</ul>` : ''}
        <footer>
          ${plan && session.id ? `<a class="control" href="#session/${encodeURIComponent(session.id)}">打开训练课 →</a>` : ''}
        </footer>
      </article>`;
    };
    const listRows = teams.map((team, index) => {
      const plans = team.planCount || 0;
      const progress = team.goalCount
        ? `${fmt(team.goalsDone)}/${fmt(team.goalCount)} 目标达成`
        : (plans ? '还没写训练目标' : '未登记训练课');
      return `<button type="button" class="ttn-item${index === 0 ? ' is-active' : ''}"
        data-tt-select="${esc(team.id)}" data-name="${esc(String(team.displayName || '').toLowerCase())}">
        ${tmCrest(team.displayName)}
        <span class="ttn-item-main"><b>${text(team.displayName)}</b>
          <small>${fmt(team.sessionCount)} 次 · ${text(team.lastSession || team.lastSeen || '—')} · ${progress}</small></span>
        <span class="ttn-item-state is-${plans ? 'plan' : 'camp'}">${plans ? `${fmt(plans)} 课` : '交手'}</span>
      </button>`;
    }).join('');
    const panels = teams.map((team, index) => {
      const sessions = team.sessions || [];
      return `<section class="ttn-panel" data-tt-panel="${esc(team.id)}" ${index === 0 ? '' : 'hidden'}>
        <header class="ttn-panel-head">
          ${tmCrest(team.displayName)}
          <div><h3>${text(team.displayName)}</h3>
            <p>${fmt(team.matches)} 局 · 本队 ${tmRecord(team)} · 最近 ${text(team.lastSeen || '—')}</p></div>
          <a class="control" href="${route('team', team.id)}">战队分析 →</a>
        </header>
        <div class="ttn-timeline">${sessions.length ? sessions.map((session) => sessionCard(session)).join('')
          : empty('这支对手还没有训练课或交手记录。')}</div>
      </section>`;
    }).join('');
    const head = lede([
      ['训练课', `${fmt(summary.plans || 0)} 场`, `${fmt(summary.withPlans || 0)} 支对手`],
      ['训练目标', `${fmt(summary.goals || 0)} 条`, `${fmt(summary.goalsDone || 0)} 条达成`],
      ['已复盘', `${fmt(summary.reviewed || 0)} 场`, '复盘状态 = 已复盘'],
      ['交手日', `${fmt(summary.sessions || 0)} 次`, '含自动归集'],
      ['未指定对手', `${fmt(summary.unassigned || 0)} 条`, '在训练计划里补对手'],
    ]);
    const notice = (summary.plans || 0) > 0 && unassigned.length ? `<div class="ttn-notice"><b>${fmt(unassigned.length)} 条训练计划还没指定对手</b>
      <p>${unassigned.map((row) => text(row.date || '日期未定')).join('、')} 的计划挂在「未指定对手」下，补上对手后会自动归到这支战队。</p>
      <a class="control" href="#plan">去训练计划 →</a></div>` : '';
    const emptyPlans = (summary.plans || 0) === 0 ? `<div class="ttn-empty">
      <b>还没有登记训练课</b>
      <p>训练课来自「训练计划」：登记日期与约战对手后，这里会按对手汇总训练目标、复盘状态和关联对局。下面的交手日已经按营地记录自动归集，不需要手工补。</p>
      ${unassigned.length ? `<p class="ttn-empty-sub">另有 ${fmt(unassigned.length)} 条计划（${unassigned.map((row) => text(row.date || '日期未定')).join('、')}）还没指定对手；补上对手后会自动归到对应战队。</p>` : ''}
      <a class="control" href="#plan">去训练计划 →</a></div>` : '';
    return withPage('战队训练', `按对手汇总训练课与交手日 · 训练课来自训练计划，交手日从营地记录自动归集 · ${TM_NOTE}`,
      head + notice + emptyPlans
      + `<div class="ttn-layout">
        <aside class="section ttn-side">
          <div class="section-heading"><div><h2>对手训练榜</h2><p>有训练课的排前；点一支看时间线。</p></div></div>
          <div class="ttn-search"><input data-ttn-search placeholder="搜索对手" aria-label="搜索对手"></div>
          <div class="ttn-list" data-ttn-list>${listRows || empty('还没有可归集的对手。')}</div>
        </aside>
        <div class="ttn-detail" data-ttn-detail>${panels || empty('还没有可归集的对手。')}</div>
      </div>`, false);
  }
  function syncTeamTraining(root) {
    if (!root) return;
    const q = (root.querySelector('[data-ttn-search]')?.value || '').trim().toLowerCase();
    const items = [...root.querySelectorAll('[data-tt-select]')];
    let shown = 0;
    for (const item of items) {
      const ok = !q || String(item.dataset.name || '').includes(q);
      item.hidden = !ok;
      if (ok) shown++;
    }
    if (!shown) {
      root.querySelectorAll('[data-tt-panel]').forEach((panel) => { panel.hidden = true; });
    } else if (!items.some((item) => !item.hidden && item.classList.contains('is-active'))) {
      items.find((item) => !item.hidden)?.click();
    }
  }
  function ownership(value) {
    const teams = value.teams || [];
    identityTeamOptions = teams.map((t) => ({id: t.id, name: t.displayName}));
    const teamNameOf = (id) => (teams.find((t) => t.id === id) || {}).displayName || '';
    const loose = value.unassigned || [];
    const members = [...loose, ...teams.flatMap((t) => t.players || [])];
    const named = teams.filter((t) => t.named).length;
    const unassigned = members.filter((p) => !p.teamId).length;
    const manual = members.filter((p) => p.mapped).length;
    const playerLine = (p) => {
      const mapped = !!p.mapped;
      const nickname = p.nickname && p.nickname !== p.name ? `游戏ID ${p.nickname} · ` : '';
      return `<div class="sx-own-player">
      <span class="sx-own-avatar">${esc((p.name || '?').slice(0, 1))}</span>
      <span class="sx-own-pname"><b>${text(p.name)}</b><small>${nickname}${text((p.lanes || []).join(' / ') || p.position || '位置未记录')} · ${fmt(p.games)} 场</small></span>
      <span class="sx-own-source ${mapped ? 'is-manual' : 'is-pending'}">${mapped ? '已命名' : '待命名'}</span>
      <button type="button" class="control sx-own-action" data-sx-id-open="${esc(p.id)}" data-id-account="${esc(p.id)}" data-id-nickname="${esc(p.nickname || p.name)}" data-id-name="${mapped ? esc(p.name) : ''}" data-id-position="${esc(p.position || (p.lanes || [])[0] || '')}" data-id-positions="${esc((p.positions || []).join(','))}" data-id-team="${esc(p.teamId || '')}" data-id-teamname="${esc(teamNameOf(p.teamId))}" data-id-games="${fmt(p.games)}" data-id-player="${esc(p.playerId || '')}">${mapped ? '编辑' : '命名'}</button>
      ${mapped ? `<button type="button" class="control sx-own-action" data-sx-player-assign="${esc(p.id)}" data-player-name="${esc(p.name)}" data-team-id="${esc(p.teamId || '')}">调整</button>` : ''}
    </div>`;
    };
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
      dataPrepNav('ownership')
      +lede([['对手战队', `${fmt(teams.length)} 支`, `${fmt(named)} 支已命名`],
        ['对手选手', `${fmt(members.length)} 名`, `${fmt(unassigned)} 名未归属`],
        ['待命名', `${fmt(teams.length - named)} 支`, '命名后显示真实队名'],
        ['手动确认', `${fmt(manual)} 名`, '其余为阵容推断']])
      + block('战队与选手', '默认展示前 5 支战队；展开后可命名战队或调整选手，搜索会跨全部战队匹配选手昵称。',
        `${toolbar}<div class="sx-own-groups" data-sx-own-groups>${groupHtml || empty('当前没有识别到对手选手。')}<p class="sx-empty" data-sx-own-empty hidden>没有符合条件的战队或选手。</p></div>
        <button class="sx-more" type="button" data-sx-own-more ${groups.length <= 5 ? 'hidden' : ''}>展开全部 ${groups.length} 组</button>`,
        `<span class="sx-count">${fmt(teams.length)} 支</span>`,'data-sx-scope="ownership"')
      + dialog, false, nextCta, false, true);
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
     分析接口的 winRate 是 0–100 百分数，赛研是 0–1 小数，阈值按百分数写。 */
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
      block('英雄表现', '按胜率分档展示本队出场样本，点击英雄查看各位置表现。', `<div class="hero-board">${brief}${controls}${cards}</div>`, '', 'data-tour="hero-board"'));
  }
  /* 英雄详情：照 KPL 赛研 hero.html 的对象页范式 —— 顶部返回 + KPI 统计条 +
     各位置表现 / 双人搭档 / 三人组合 / 选手出装 /
     选手使用榜 / 战队使用 / 本队均值对照 / 成长曲线 / 最近出场 / 时间表现 /
     同位置对位，十一块分析，一块一行全宽。
     「选手出装」即赛研的「职业哥同款」，同一块，不另设重复模块。装备图标来自 catalog.json 本地资源 + 赛研在线映射。
     数据源 = camp-compare + camp-partners + matches + lane_matchup + v3/hero-detail。 */
  function heroDetail(value, partners, matchesData, matchup, summary, key) {
    const equipImg = (name) => equipIcons[name] ? `<img class="equip-icon" src="${esc(equipIcons[name])}" alt="" loading="lazy">` : '';
    const pctClamp = (v) => Math.max(0, Math.min(100, typeof v === 'number' && Number.isFinite(v) ? v : 0));
    const deltaCls = (v) => (typeof v === 'number' && v < 0 ? 'is-neg' : 'is-pos');
    const initial = (s) => esc(String(s || '?').slice(0, 1));
    const bar = (v, cls = '') => `<div class="hz-track"><i class="${cls}" style="width:${pctClamp(v)}%"></i></div>`;
    const bipole = (v, scale = 30) => `<div class="hz-bipole"><i class="${deltaCls(v)}" style="width:${Math.min(50, Math.abs(v || 0) / scale * 50)}%"></i></div>`;
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

    const buildRows = (summary?.playerBuilds || []).map(p => `<article class="hz-card hz-build-card"><div class="hz-build-head"><span class="hz-avatar">${initial(p.name)}</span><div><b>${text(p.name)}</b><small>${fmt(p.games)} 局 · 胜率 ${pct(p.winRate)} · KDA ${fmt(p.kda, 2)}</small></div><strong>${fmt(p.gold)}<small>金</small></strong></div><div class="hz-slots">${(p.equips || []).map(e => `<div class="hz-slot">${equipImg(e.name)}<small>${pct(p.games ? e.count / p.games * 100 : null)}</small></div>`).join('') || '<span class="hz-build-none">暂无出装样本</span>'}</div><div class="hz-build-sub">${(p.first || []).length ? `<span>首件 ${(p.first || []).map(x => text(x.name)).join(' / ')}</span>` : ''}${(p.summoner || []).length ? `<span>召唤师技能 ${(p.summoner || []).map(x => text(x.name)).join(' / ')}</span>` : ''}</div></article>`).join('');
    const playerBuildPanel = block('选手出装', '每位选手使用该英雄时的终局出装与携带率', buildRows ? `<div class="hz-build-list">${buildRows}</div>` : empty('当前范围暂无逐人出装样本。'));

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

    const anchorLabels = ['各位置', '双人搭档', '三人组合', '选手出装', '选手使用', '战队使用', '均值对照', '成长曲线', '最近出场', '时间表现', '同位置对位'];
    const anchorNav = `<nav class="hero-anchor-nav" aria-label="模块快速导航">${anchorLabels.map((label, i) => `<button type="button" data-hero-scroll="${i}">${esc(label)}</button>`).join('')}</nav>`;

    return `<div class="page hero-detail-page">
      <header class="hero-masthead"><div class="page-intro"><div>
        <a class="hero-back" href="#heroes">← 返回英雄榜</a>
        <h1>${esc(key || '英雄详情')}</h1><p>${intro}</p></div>
        <div class="intro-actions"><button class="control" data-action="refresh">刷新数据</button></div></div>
        ${kpi}</header>
      ${anchorNav}<div class="hero-detail-grid">${lanePanel}${partnerPanel}${trioPanel}${playerBuildPanel}${playerPanel}${teamPanel}${leaguePanel}${growthPanel}${matchPanel}${timePanel}${matchupPanel}</div></div>`;
  }
  /* ===== BP 板块 =====
     BP 概览已整体重建为单页十区（v3/public/bp-lab.js + /api/v3/bp-lab）；
     本文件只保留教练档案（#coach）和英雄组合页（combos，属于英雄模块）。 */
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
      reviewNav('effect')
      +lede([['干预记录',`${fmt(results.length)} 条`,'训练目标'],['可对比',`${fmt(usable.length)} 条`,'两侧样本 ≥ 5 人次'],['平均效应量',meanD==null?'—':fmt(meanD,2),'Cohen’s d'],['最近一条',text(results[0]?.start_date),text(results[0]?.goal||'')]])
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
  /* ─── 对局子页（精选对局 / 训练纪录 / 版本对比）───────────────────────
     沿用「一行一局」的读法：编号 → 对局 → 比分 → 时长 → 经济差 → 结果。
     筛选、排序、分组都在前端按已加载数据完成，不改后端口径。
     原「按条件找局」子页与对局档案的筛选重复，已下线（#query 回退到 #matches）。 */
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const matchIndex = (matches) => {
    const ordered = [...matches].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')) || String(a.key).localeCompare(String(b.key)));
    return new Map(ordered.map((m, i) => [m.key, i + 1]));
  };
  const resCls = (r) => r === 'win' ? 'win' : r === 'loss' ? 'loss' : 'muted';
  const resLabel = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '未知';
  const lede = (items) => `<div class="fj-lede">${items.map(([label, value, note]) => `<span><small>${esc(label)}</small><b>${value}</b>${note ? `<i>${esc(note)}</i>` : ''}</span>`).join('')}</div>`;
  const top = (items, f, dir = 'max') => {
    const valid = items.filter((x) => isNum(f(x)));
    if (!valid.length) return null;
    return [...valid].sort((a, b) => dir === 'max' ? f(b) - f(a) : f(a) - f(b))[0];
  };
  const meanOf = (items, f) => {
    const v = items.map(f).filter(isNum);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
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
        ['平均终局经济差', diff(meanOf(games, (g) => g.finalDiff)), '本队减对手'],
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
      ['最大终局经济差', (m) => m.goldDiff, (m) => diff(m.goldDiff), 'max', '本队减对手'],
      ['最小终局经济差', (m) => m.goldDiff, (m) => diff(m.goldDiff), 'min', '本队减对手'],
      ['最高击杀', (m) => m.own?.kills, (m) => fmt(m.own?.kills), 'max', '本队五人击杀合计'],
      ['最高 KDA', (m) => m.own?.kda, (m) => fmt(m.own?.kda, 1), 'max', '(击杀 + 助攻) / 死亡'],
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
        ['平均终局经济差', diff(meanOf(all, (m) => m.goldDiff)), '本队减对手'],
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
        <span class="fj-group-stat"><small>平均经济差</small>${g.golds ? diff(g.gold / g.golds) : '—'}</span>
      </div>`).join('');
    };
    const note = covered ? '' : `<p class="fj-note">${fmt(matches.length)} 局都还没有记录版本，先按训练组看；在单局里补录版本后，这里会自动按版本分组。</p>`;
    const chips = dims.map(([k, label]) => `<button type="button" class="fj-chip" data-fj-dim="${k}" aria-pressed="${k === active}">${label}</button>`).join('');
    const panels = dims.map(([k]) => `<div class="fj-panel" data-fj-panel="${k}" ${k === active ? '' : 'hidden'}>${rowsOf(k)}</div>`).join('');
    return withPage('版本对比', '按版本或训练组，看局数、胜率与平均节奏。',
      lede([['对局', `${fmt(matches.length)} 局`],
        ['版本覆盖', `${fmt(covered)} / ${fmt(matches.length)}`],
        ['训练组', `${fmt(new Set(matches.map((m) => m.session).filter(Boolean)).size)} 个`]])
      + block('分组对比', '胜率只以有胜负的对局为分母；平均经济差为本队减对手。', `<div class="fj-dims">${chips}</div>${note}${panels}`), false);
  }
  function setup(value, teams, players, pending, migration, clusters, identity) {
    const o = value.overview || {}, profile = o.profile || {};
    identity = identity || {};
    const identityRows = identity.rows || [];
    const identityCount = identity.counters || {};
    identityTeamOptions = (identity.teams || []).map((t) => ({id: t.id, name: t.name}));
    if (!identityTeamOptions.length) identityTeamOptions = (teams.teams || []).map((t) => ({id: t.id, name: t.name}));
    const ownTeam = identity.ownTeam || {};
    const idState = {
      all: identityRows.length,
      unmapped: identityRows.filter((r) => !r.mapped).length,
      mapped: identityRows.filter((r) => r.mapped).length,
      own: identityRows.filter((r) => r.side === 'own').length,
      enemy: identityRows.filter((r) => r.side === 'enemy').length,
    };
    const teamList = (teams.teams || []).map((t) => ({...t, name:canonicalTeamName(t.name)}));
    const playerList = [...(players.players || [])].sort((a, b) => {
      const pa = isPlaceholderPlayer(a.name) ? 0 : 1;
      const pb = isPlaceholderPlayer(b.name) ? 0 : 1;
      return pa - pb || String(a.name).localeCompare(String(b.name), 'zh', {numeric:true});
    });
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
    const realPlayers = playerList.filter((p) => !isPlaceholderPlayer(p.name));
    const placeholderPlayers = playerList.length - realPlayers.length;
    const playerReady = realPlayers.length > 0;
    const counts = migration.counts || {};
    const matchCount = counts.match_records || 0;
    const teamReady = opponentTeams.length ? namedTeams.length === opponentTeams.length : teamList.length > 0;
    const steps = [
      {name:'本队资料', ok:!!profile.teamName, meta:profile.teamName ? `${profile.teamName}${profile.coach ? ' · ' + profile.coach : ''}` : '填写战队名与主教练', href:'#setup', jump:'profile'},
      {name:'战队主数据', ok:teamReady, meta:opponentTeams.length ? `${namedTeams.length} / ${opponentTeams.length} 支对手已命名` : (teamList.length ? '只有本队档案' : '还没有战队主数据'), href:'#setup', jump:'teams'},
      {name:'游戏ID命名', ok:idState.all > 0 && idState.unmapped === 0, meta:idState.all ? `${idState.mapped} / ${idState.all} 个游戏ID已对上选手` : '还没有营地游戏ID', href:'#setup', jump:'identity'},
      {name:'选手主数据', ok:playerReady, meta:playerList.length ? (realPlayers.length ? `${realPlayers.length} 名已登记${placeholderPlayers ? ` · ${placeholderPlayers} 名待命名` : ''}` : `仅有 ${placeholderPlayers} 名占位选手`) : '还没有本队选手', href:'#setup', jump:'players'},
      {name:'结构化对局', ok:matchCount > 0, meta:`${matchCount} 局已迁移`, href:'#matches'},
      {name:'待确认字段', ok:pending.fields === 0, meta:pending.fields ? `${pending.fields} 项待确认` : '没有待确认字段', href:'#pending'},
    ];
    const done = steps.filter((x) => x.ok).length;
    const percent = Math.round(done / steps.length * 100);
    let next;
    if (!profile.teamName) next = {title:'先补齐本队资料', note:'战队名与主教练会进入报告署名、教练档案和平台展示。', cta:'填写本队资料', href:'#setup', jump:'profile'};
    else if (!teamList.length) next = {title:'添加第一支战队', note:'战队是选手归属、交手记录和 BP 分析的挂载点。', cta:'添加战队', href:'#setup', jump:'teams'};
    else if (!teamReady) next = {title:`给 ${unnamedTeams.length} 支对手战队命名`, note:'命名后，对局、BP、报告和对手页会显示真实队名，而不是「待命名战队 #N」。', cta:'开始命名', href:'#setup', jump:'teams'};
    else if (idState.unmapped > 0) next = {title:`命名 ${idState.unmapped} 个游戏ID`, note:'营地爬到的游戏ID对上选手与战队后，以后同一账号自动认人，分析按选手累计。', cta:'去命名', href:'#setup', jump:'identity'};
    else if (!playerList.length) next = {title:'登记第一名本队选手', note:'选手主数据决定个人分析能否跨局对比。', cta:'添加选手', href:'#setup', jump:'players'};
    else if (!playerReady) next = {title:`给 ${placeholderPlayers} 名占位选手改名`, note:'「待命名选手 #N」只是迁移占位，不会和战队的「待命名战队 #N」混用；改成真实 ID 后才算进入选手主数据。', cta:'去改名', href:'#setup', jump:'players'};
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
    const qualityTarget = failed[0]?.key === 'identity' ? '#playerarchive?claim=unbound' : '#matches';
    const quality = checks.length ? `<section class="sx-quality ${failed.length ? 'is-warn' : 'is-ok'}">
      <div class="sx-quality-score"><b>${o.dataQuality.score ?? '—'}</b><small>数据分</small></div>
      <div class="sx-quality-copy"><b>${failed.length ? `${failed.length} 项检查未通过` : '前置检查全部通过'}</b><p>${failed.length ? `${esc(failed[0].label)} · ${esc(failed[0].hint)}${failed.length > 1 ? ` 等 ${failed.length} 项` : ''}` : '对手、时长、经济差、分路与选手绑定均可用于分析。'}</p></div>
      <a class="control" href="${qualityTarget}">${failed.length ? '去处理' : '查看数据'} →</a>
    </section>` : '';
    const legacyMembers = (profile.members || []).filter((m) => !m.archived);
    const legacyBanner = legacyMembers.length > playerList.length && !profile.rosterMigratedAt ? `<section class="sx-legacy">
      <div class="sx-legacy-copy"><b>旧档案里还有 ${legacyMembers.length} 名成员</b><p>迁移会保留旧 id，跳过同名、同战队、同位置的重复项；旧占位名会改成「待命名选手 #N」，与战队占位名「待命名战队 #N」分开。</p></div>
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
    /* ── 身份对照：游戏ID → 选手 → 战队（一处命名，处处生效） ─────────── */
    const idChip = (key, label, count, pressed = false) =>
      `<button type="button" class="fj-chip" data-sx-id-chip="${key}" aria-pressed="${pressed}">${esc(label)} ${fmt(count)}</button>`;
    const idTeamName = (id) => (identityTeamOptions.find((t) => t.id === id) || {}).name || '';
    const idRow = (row, index) => {
      const mapped = !!row.mapped;
      const teamLabel = row.teamName || idTeamName(row.teamId) || '';
      const suggest = row.suggestTeamName || idTeamName(row.suggestTeamId) || '';
      const openAttrs = `data-sx-id-open="${esc(row.accountId)}" data-id-account="${esc(row.accountId)}" data-id-nickname="${esc(row.nickname)}" data-id-name="${esc(row.name || '')}" data-id-position="${esc(row.position || row.lane || '')}" data-id-positions="${esc((row.positions || []).join(','))}" data-id-team="${esc(row.teamId || row.suggestTeamId || '')}" data-id-teamname="${esc(teamLabel || suggest)}" data-id-games="${fmt(row.games)}" data-id-player="${esc(row.playerId || '')}"`;
      return `<div class="sx-id-row ${mapped ? 'is-mapped' : 'is-pending'}" data-sx-id-row data-side="${esc(row.side)}" data-state="${mapped ? 'mapped' : 'unmapped'}" data-search="${esc((row.nickname + ' ' + (row.name || '') + ' ' + teamLabel).toLowerCase())}" ${index >= 20 ? 'hidden' : ''}>
        <span class="sx-id-gid"><b>${text(row.nickname || '未知昵称')}</b><small>${esc(row.lane || '位置未记录')} · ${fmt(row.games)} 局${row.lastSeen ? ' · ' + esc(row.lastSeen) : ''}</small></span>
        <span class="sx-id-arrow" aria-hidden="true">→</span>
        <span class="sx-id-player">${mapped ? `<b>${text(row.name)}</b><small>${text((row.positions && row.positions.length ? row.positions.join(' / ') : (row.position || row.lane || '位置未填')))}</small>` : '<b class="is-wait">待命名</b><small>还没有选手ID</small>'}</span>
        <span class="sx-id-team">${mapped ? `<b>${text(teamLabel || '未归队')}</b>` : (suggest ? `<small>建议 ${esc(suggest)}</small>` : '<small>战队未识别</small>')}</span>
        <span class="sx-id-side">${row.side === 'own' ? '本队' : '对手'}</span>
        <span class="sx-id-actions">
          <button type="button" class="sx-inline-btn" ${openAttrs}>${mapped ? '编辑' : '命名'}</button>
          ${mapped ? `<button type="button" class="sx-inline-btn is-quiet" data-sx-id-unmap="${esc(row.accountId)}" data-id-nickname="${esc(row.nickname)}">解绑</button><button type="button" class="sx-inline-btn is-danger" data-sx-id-delete="${esc(row.playerId)}" data-id-name="${esc(row.name)}">删除</button>` : ''}
        </span>
      </div>`;
    };
    const idHead = `<div class="sx-id-row is-head" aria-hidden="true"><span>游戏ID（营地昵称）</span><span></span><span>选手ID</span><span>战队</span><span>阵营</span><span></span></div>`;
    const idToolbar = `<div class="sx-toolbar">
      <label class="sx-search">${icon('search')}<input data-sx-id-search placeholder="搜索游戏ID、选手或战队" aria-label="搜索身份"></label>
      <div class="sx-chips">${idChip('all', '全部', idState.all, true)}${idChip('unmapped', '待命名', idState.unmapped)}${idChip('mapped', '已命名', idState.mapped)}${idChip('own', '本队', idState.own)}${idChip('enemy', '对手', idState.enemy)}</div>
      <span class="sx-toolbar-count" data-sx-id-count>共 ${fmt(idState.all)} 个游戏ID</span>
    </div>`;
    const identityBlock = block('身份对照 · 游戏ID → 选手 → 战队',
      '营地爬到的每个游戏ID都在这里。命名一次，建档、对手归属、选手档案、个人页都按这个名字显示；以后同一账号自动认人。',
      `<p class="sx-id-hint">游戏ID 指营地昵称，选手ID 是你给这个人起的真名（如「小义」）。命名时顺手选战队；战队还没有就写个新队名，会一起建出来。删选手会连他的游戏ID映射一起删，那些ID回到「待命名」。</p>`
      + idToolbar
      + `<div class="sx-id-list" data-sx-id-list>${idHead}${identityRows.map(idRow).join('') || empty('还没有可命名的游戏账号。先在「采集 → 营地同步」拉一场。')}<p class="sx-empty" data-sx-id-empty hidden>没有符合条件的游戏ID。</p></div>`
      + `<button class="sx-more" type="button" data-sx-id-more ${identityRows.length <= 20 ? 'hidden' : ''}>显示全部 ${fmt(identityRows.length)} 个</button>`,
      `<span class="sx-count">${fmt(idState.unmapped)} 个待命名</span>`, 'data-sx-anchor="identity"');
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
      field('选手名称','name','','required maxlength="40" placeholder="真实 ID 或常用名，不要用占位名"')+
      select('位置','position','<option value="">待确认</option>'+['对抗路','打野','中路','发育路','游走'].map((x) => `<option value="${x}">${x}</option>`).join(''))+
      field('营地 ID','campUserId','','placeholder="营地用户 ID，可后补"'),
      '添加选手');
    const playerRows = playerList.map((p) => {
      const team = teamList.find((t) => t.id === p.team_id)?.name || '未指定战队';
      const placeholder = isPlaceholderPlayer(p.name);
      const accounts = (identityRows || []).filter((row) => row.playerId === p.id).length;
      return `<div class="sx-player-row ${placeholder ? 'is-placeholder' : ''}"><span class="sx-player-mark">${esc((p.name || '?').slice(0, 1))}</span><span class="sx-player-main"><b>${text(p.name)}</b><small>${placeholder ? '选手占位名 · ' : ''}${text(team)} · ${text(p.position || '位置未填')}${accounts ? ` · ${fmt(accounts)} 个游戏ID` : ' · 没有游戏ID'}</small></span><span class="sx-player-state ${placeholder ? 'is-pending' : p.role === 'main' ? 'is-main' : ''}">${placeholder ? '待命名' : p.role === 'main' ? '主力' : '替补'}</span><button type="button" class="sx-inline-btn is-danger" data-sx-id-delete="${esc(p.id)}" data-id-name="${esc(p.name)}">删除</button></div>`;
    }).join('');
    const editPlayers = playerList.map((p) => `<details class="sx-manage"><summary>${text(p.name)} · 编辑</summary><div class="sx-manage-body">${form('masterPlayer',`<input type="hidden" name="id" value="${esc(p.id)}"><input type="hidden" name="aliases" value="${esc(JSON.stringify(p.aliases||[]))}"><input type="hidden" name="role" value="${esc(p.role||'main')}">`+select('所属战队','teamId',options(teamList,p.team_id))+field('选手名称','name',p.name,'required maxlength="40"')+select('位置','position','<option value="">待确认</option>'+['对抗路','打野','中路','发育路','游走'].map((x) => `<option value="${x}" ${p.position === x ? 'selected' : ''}>${x}</option>`).join(''))+field('营地 ID','campUserId',p.camp_user_id||''),'保存修改')}</div></details>`).join('');
    const playerBlock = block('选手主数据','选手占位名是「待命名选手 #N」，战队占位名是「待命名战队 #N」，两者分开统计。先有战队再登记选手，营地 ID 用于绑定昵称。',playerForm+(playerRows?`<div class="sx-player-list">${playerRows}</div>`:'')+editPlayers,`<span class="sx-count">${fmt(realPlayers.length)} 名${placeholderPlayers ? ` · ${fmt(placeholderPlayers)} 待命名` : ''}</span>`,'data-sx-anchor="players"');
    const migrationBlock = block('对局迁移',migration.note || '仅新增未迁移的真实对局基本信息；不覆盖现有记录，不推测选手身份、对手归属及 BP 手序。',
      `<div class="sx-migration">
        <div><span>结构化对局</span><b>${fmt(matchCount)}</b><small>局</small></div>
        <div><span>阵容记录</span><b>${fmt(counts.match_rosters)}</b><small>条</small></div>
        <div><span>BP 记录</span><b>${fmt(counts.bp)}</b><small>条</small></div>
        <div><span>待迁移</span><b>${fmt(migration.candidates)}</b><small>局</small></div>
        <button class="control" data-feature-action="migrate" ${migration.candidates?'':'disabled'}>迁移新增对局</button>
        <p class="migration-status" role="status"></p>
      </div>`,'','data-sx-anchor="migration"');
    return withPage('数据准备',`本队资料、战队与选手主数据是后续识别的前提 · 当前 ${done} / ${steps.length} 项已完成。`,
      dataPrepNav('setup')+cockpit+quality+legacyBanner+identityBlock+profileBlock+teamBlock+playerBlock+migrationBlock,false,nextCta,false,true);
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
      dataPrepNav('pending')
      +lede([['待确认对局',`${fmt(value.total)} 局`,'含至少一个待确认字段'],['待确认字段',`${fmt(value.fields)} 项`,'逐项确认'],['自动预填','系统生成','需要人工核实'],['写入方式','确认后写回','标记人工来源']])
      + vocabDatalist(vocabList(vocab, 'session'))
      + block('确认队列','版本 / 规则 / 赛制从词表里选，训练组可输入新值；保存时统一归一化，「其他」手填的新值下次自动出现。',
        toolbar+`<div class="sx-pending-grid">${cards || '<p class="sx-empty">当前没有待确认字段。</p>'}</div><p class="sx-empty" data-sx-pending-empty hidden>没有匹配的待确认字段。</p>`,
        `<button class="control" data-feature-action="prefill">重新扫描</button>`,'data-sx-scope="pending"'),false,'',false,true);
  }
  function plan(value, teams, vocab, dashboard, competitionData) {
    const schedules = value.schedules || [];
    const competitions = (competitionData && competitionData.competitions) || [];
    const today = localDate();
    const foeTeams = (teams.teams || []).filter((t) => t.id !== 'team-own');
    const statusOptions = (current) => ['planned','confirmed','completed','cancelled'].map((v) => `<option value="${v}" ${current === v ? 'selected' : ''}>${statusLabels[v]}</option>`).join('');
    const compOptions = (current) => `<option value="">不关联比赛</option>${competitions.map((c) => `<option value="${esc(c.id)}" ${current === c.id ? 'selected' : ''}>${esc(c.name)} · ${esc(c.date || '')}</option>`).join('')}`;
    const schedFields = (x = {}) => field('日期','date',x.date||today,'type="date" required')+
      field('开始时间','startTime',x.start_time||'','type="time"')+
      select('约战对手','opponentTeamId',options(foeTeams,x.opponent_team_id))+
      `<label>比赛<select name="competitionId">${compOptions(x.competition_id)}</select></label>`+
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
    const compOf = (id) => competitions.find((c) => c.id === id) || null;
    const compName = (id) => compOf(id)?.name || '';
    const rowOf = (x) => {
      const status = x.status || 'planned';
      return `<details class="sx-plan-row is-${esc(status)}">
        <summary>
          <span class="sx-plan-date"><b>${text(x.date)}</b><small>${text(x.start_time || '时间未定')}</small></span>
          <span class="sx-plan-opponent"><b>${text(opponentOf(x))}</b><small>${text(x.session || '训练组未定')}${x.competition_id ? ' · ' + text(compName(x.competition_id)) : ''}</small></span>
          <span class="sx-plan-format">${text(x.format || '赛制未定')}</span>
          <span class="sx-plan-state is-${esc(status)}">${statusLabels[status] || status}</span>
          <span class="sx-plan-edit"><a href="#session/${encodeURIComponent(x.id)}">训练课 →</a></span>
        </summary>
        ${form('schedule',`<input type="hidden" name="id" value="${esc(x.id)}">`+schedFields(x),'保存修改')}
      </details>`;
    };
    const nextBanner = next ? `<div class="sx-plan-next"><span>下一场</span><b>${text(next.date)} ${text(next.start_time || '')}</b><p>对阵 ${text(opponentOf(next))} · ${text(next.session || '训练组未定')} · ${text(next.format || '赛制未定')}</p><a href="#session/${encodeURIComponent(next.id)}">打开训练课 →</a></div>` : '';
    const list = schedules.length ? `<div class="sx-plan-list">${nextBanner}${[...upcoming, ...past].map(rowOf).join('')}</div>`
      : `<div class="sx-empty sx-empty-inline"><b>还没有登记任何计划</b><p>登记今天约谁、练什么，赛后就能按对手和训练组回看。</p><button type="button" class="control" data-sx-jump="plan-form">添加第一条计划 ↓</button></div>`;
    const valid = schedules.filter((x) => x.status !== 'cancelled').length;
    const planSection = block('训练赛排期','按日期查看；点开一行可以修改时间、对手和状态。',list,`<span class="sx-count">${fmt(schedules.length)} 条</span>`,'data-sx-anchor="plan-list"');
    const formSection = block('添加计划','登记后，当天训练赛的采集与复盘会自动挂到这局上。',form('schedule',schedFields(),'添加计划'),'','data-sx-anchor="plan-form"');

    /* ── 比赛：赛训的中心实体。先有比赛，训练计划/训练课/对局都挂在比赛下 ── */
    const compFields = (x = {}) => field('赛事名','name',x.name||'','required maxlength="60" placeholder="如 KPL 2026 春季赛"')+
      field('比赛日期','date',x.date||today,'type="date" required')+
      select('对手','opponentTeamId',options(foeTeams,x.opponent_team_id))+
      field('赛段','stage',x.stage||'','placeholder="如 常规赛第 3 轮"')+
      vocabSelect('赛制','format',vocabList(vocab,'format'),x.format||'',{empty:'待定'})+
      field('负责教练','owner',x.owner||'','placeholder="谁负责这场比赛"')+
      select('状态','status',statusOptions(x.status||'planned'))+
      field('备注','notes',x.notes||'','placeholder="目标、重点对手等"');
    const compOrdered = [...competitions].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
    const compUpcoming = compOrdered.filter((c) => String(c.date || '') >= today);
    const compPast = compOrdered.filter((c) => String(c.date || '') < today).reverse();
    const nextComp = compUpcoming.find((c) => c.status !== 'cancelled' && c.status !== 'completed');
    const compRow = (c) => {
      const status = c.status || 'planned';
      const foe = teams.teams.find((t) => t.id === c.opponent_team_id)?.name || '对手未指定';
      return `<details class="sx-plan-row sx-comp-row is-${esc(status)}">
        <summary>
          <span class="sx-plan-date"><b>${text(c.date)}</b><small>${text(c.stage || '赛段未定')}</small></span>
          <span class="sx-plan-opponent"><b>${text(c.name)}</b><small>${text(foe)} · ${text(c.format || '赛制未定')} · ${text(c.owner ? '负责人 ' + c.owner : '未指定负责人')}</small></span>
          <span class="sx-plan-format">${fmt(c.session_count || 0)} 课 · ${fmt(c.linked_count || 0)} 局</span>
          <span class="sx-plan-state is-${esc(status)}">${statusLabels[status] || status}</span>
          <span class="sx-plan-edit"><a href="#competition/${encodeURIComponent(c.id)}">比赛详情 →</a></span>
        </summary>
        ${form('competition',`<input type="hidden" name="id" value="${esc(c.id)}">`+compFields(c),'保存修改')}
      </details>`;
    };
    const compBanner = nextComp ? `<div class="sx-plan-next"><span>下一场比赛</span><b>${text(nextComp.date)} · ${text(nextComp.name)}</b><p>对阵 ${text(teams.teams.find((t) => t.id === nextComp.opponent_team_id)?.name || '待定')} · ${text(nextComp.stage || '赛段未定')} · ${text(nextComp.owner ? '负责人 ' + nextComp.owner : '负责人未定')}</p><a href="#competition/${encodeURIComponent(nextComp.id)}">打开比赛 →</a></div>` : '';
    const compList = competitions.length
      ? `<div class="sx-plan-list">${compBanner}${[...compUpcoming, ...compPast].map(compRow).join('')}</div>`
      : `<div class="sx-empty sx-empty-inline"><b>还没有登记比赛</b><p>先添加比赛（日期 + 对手 + 赛事名），再把训练计划挂到这场比赛下；比赛详情会自动汇总训练课、对局与选手。</p><button type="button" class="control" data-sx-jump="competition-form">添加第一场比赛 ↓</button></div>`;
    const compSection = block('比赛','赛训以比赛为中心：先登记比赛，训练计划与对局都会汇总到比赛详情。',compList,`<span class="sx-count">${fmt(competitions.length)} 场</span>`,'data-sx-anchor="competition-list"');
    const compFormSection = block('添加比赛','填写比赛日期、对手与赛事名；训练计划可以在下面直接关联这场比赛。',form('competition',compFields(),'添加比赛'),'','data-sx-anchor="competition-form"');

    const dash = dashboard || {};
    const dashWeeks = dash.weeks || [];
    const dashCurrent = dash.current || dashWeeks[dashWeeks.length - 1] || {};
    const dashPrev = dashWeeks[dashWeeks.length - 2] || {};
    const goalCounts = dash.goals || {};
    const goalTotal = Object.values(goalCounts).reduce((sum, value) => sum + (Number(value) || 0), 0);
    const goalPct = dashCurrent.goalCompletion ?? (goalTotal ? (goalCounts.achieved || 0) / goalTotal * 100 : null);
    const reviewPct = dashCurrent.reviewCompletion;
    const maxGames = Math.max(1, ...dashWeeks.map((week) => Number(week.gameCount) || 0));
    const totalDashGames = dashWeeks.reduce((sum, week) => sum + (Number(week.gameCount) || 0), 0);
    const trendOf = (current, previous, suffix = '') => {
      if (current == null || previous == null) return '—';
      if (Number(current) === Number(previous)) return '持平';
      const delta = Number(current) - Number(previous);
      return `${delta > 0 ? '↑' : '↓'} ${fmt(Math.abs(delta), Number.isInteger(delta) ? 0 : 1)}${suffix}`;
    };
    const dashKpis = [
      ['训练课', fmt(dashCurrent.sessionCount || 0), trendOf(dashCurrent.sessionCount, dashPrev.sessionCount, ' 场'), '场'],
      ['训练局数', fmt(dashCurrent.gameCount || 0), trendOf(dashCurrent.gameCount, dashPrev.gameCount, ' 局'), '局'],
      ['目标达成率', goalPct != null ? pct(goalPct) : '—', trendOf(goalPct, dashPrev.goalCompletion, ' pp'), '按目标'],
      ['复盘完成率', reviewPct != null ? pct(reviewPct) : '—', trendOf(reviewPct, dashPrev.reviewCompletion, ' pp'), '本周'],
    ].map(([label, value, trend, note], index) => `<div class="dash-kpi${index === 0 ? ' is-primary' : ''}"><span>${label}</span><b>${value}</b><small>${trend} <em>${note}</em></small></div>`).join('');
    const totalSessions = dashWeeks.reduce((sum, week) => sum + (Number(week.sessionCount) || 0), 0);
    const activeWeeks = dashWeeks.filter((week) => (Number(week.sessionCount) || 0) > 0);
    const activeGameWeeks = dashWeeks.filter((week) => (Number(week.gameCount) || 0) > 0);
    const loadStripWeeks = dashWeeks.filter((week) => (Number(week.sessionCount) || 0) > 0 || (Number(week.gameCount) || 0) > 0);
    const comboW = 640;
    const comboH = 190;
    const comboLeft = 34;
    const comboRight = 12;
    const comboTop = 16;
    const comboBottom = 26;
    const comboInner = comboW - comboLeft - comboRight;
    const comboStep = comboInner / Math.max(1, dashWeeks.length);
    const comboMax = Math.max(1, ...dashWeeks.map((week) => Number(week.gameCount) || 0),
      ...dashWeeks.map((week) => Number(week.sessionCount) || 0));
    const comboY = (value) => comboH - comboBottom - (Number(value) || 0) / comboMax * (comboH - comboTop - comboBottom);
    const comboBars = dashWeeks.map((week, index) => {
      const x = comboLeft + comboStep * index + comboStep / 2;
      const width = Math.min(26, comboStep * 0.46);
      const y = comboY(week.gameCount);
      const height = Math.max(2, comboH - comboBottom - y);
      return `<g class="dash-combo-bar${index === dashWeeks.length - 1 ? ' is-current' : ''}"><rect x="${x - width / 2}" y="${y}" width="${width}" height="${height}" rx="4"></rect>${Number(week.gameCount) ? `<text x="${x}" y="${y - 5}" text-anchor="middle">${fmt(week.gameCount)}</text>` : ''}</g>`;
    }).join('');
    const comboGrid = [0, 0.5, 1].map((ratio) => {
      const y = comboY(comboMax * ratio);
      return `<line x1="${comboLeft}" y1="${y}" x2="${comboW - comboRight}" y2="${y}"></line><text x="${comboLeft - 7}" y="${y + 3}" text-anchor="end">${fmt(comboMax * ratio)}</text>`;
    }).join('');
    const comboLabels = dashWeeks.map((week, index) => {
      if (index % 2 !== 0 && index !== dashWeeks.length - 1) return '';
      const x = comboLeft + comboStep * index + comboStep / 2;
      return `<text x="${x}" y="${comboH - 7}" text-anchor="middle">${text((week.label || '').slice(0, 5))}</text>`;
    }).join('');
    const comboChart = `<div class="dash-combo"><svg viewBox="0 0 ${comboW} ${comboH}" role="img" aria-label="近 8 周训练局数"><g class="dash-combo-grid">${comboGrid}</g><g class="dash-combo-bars">${comboBars}</g><g class="dash-combo-labels">${comboLabels}</g></svg><div class="dash-combo-foot"><span>训练局数</span><em>本周 ${fmt(dashCurrent.sessionCount)} 场训练课</em></div></div>`;
    const loadStrip = loadStripWeeks.length ? `<div class="dash-week-strip">${loadStripWeeks.map((week) => `<div><span>${text((week.label || '').slice(0, 5))}</span><b>${fmt(week.sessionCount)} 场</b><small>${Number(week.gameCount) ? `${fmt(week.gameCount)} 局` : '未挂局'}</small></div>`).join('')}</div>` : '';
    const loadChart = activeGameWeeks.length >= 3 ? comboChart : (loadStrip || '<div class="dash-empty-chart">近 8 周还没有训练课。先登记计划，再把对局挂到训练课。</div>');
    const ringPct = Math.max(0, Math.min(100, Number(goalPct) || 0));
    const ring = `<div class="dash-ring"><svg viewBox="0 0 120 120" aria-hidden="true"><circle class="dash-ring-bg" cx="60" cy="60" r="47"></circle><circle class="dash-ring-value" cx="60" cy="60" r="47" pathLength="100" stroke-dasharray="${ringPct} 100"></circle></svg><div class="dash-ring-label"><b>${goalPct != null ? pct(goalPct) : '—'}</b><span>目标达成</span></div></div>`;
    const goalLegend = [['achieved', '达成'], ['partial', '部分'], ['missed', '未达成'], ['pending', '未评估']].map(([key, label]) => `<span class="dash-legend-${key}"><i></i>${label}<b>${fmt(goalCounts[key] || 0)}</b></span>`).join('');
    const heatRows = [];
    const days = dash.days || [];
    for (let i = 0; i < days.length; i += 7) {
      const row = days.slice(i, i + 7).map((day) => {
        const level = day.games ? Math.min(4, Math.max(1, Math.ceil(day.games / 2))) : (day.sessions ? 1 : 0);
        return `<i class="dash-heat-cell is-${level}" title="${esc(day.date)} · ${fmt(day.sessions)} 场训练 · ${fmt(day.games)} 局"></i>`;
      }).join('');
      heatRows.push(`<div class="dash-heat-row"><span>${text((days[i]?.date || '').slice(5))}</span>${row}</div>`);
    }
    const recentRows = (dash.recent || []).map((item) => `<a class="dash-session" href="#session/${encodeURIComponent(item.id)}">
      <span class="dash-session-date">${text(String(item.date || '').slice(5))}</span>
      <span class="dash-session-main"><b>${text(item.opponent || '未指定对手')}</b><small>${text(item.session || '训练组未定')} · ${fmt(item.games)} 局</small></span>
      <span class="dash-session-goal">${fmt(item.achieved)}/${fmt(item.goals)}</span>
      <i class="${item.reviewed ? 'is-done' : ''}" title="${item.reviewed ? '已复盘' : '待复盘'}"></i>
    </a>`).join('');
    const coverageRows = [
      ['目标绑定指标', dashCurrent.goalMetricCoverage],
      ['复盘完成', reviewPct],
      ['对局关联', dashCurrent.linkCoverage],
    ].map(([label, value]) => `<div class="dash-coverage-row"><span>${label}</span><div>${value != null ? `<i style="width:${Math.max(0, Math.min(100, Number(value)))}%"></i>` : ''}</div><b>${value != null ? pct(value) : '—'}</b></div>`).join('');
    const goalBody = goalTotal
      ? `<div class="dash-goal-body">${ring}<div class="dash-goal-legend">${goalLegend}</div></div>`
      : `<div class="dash-goal-empty"><span>${icon('space')}</span><b>本周还没有训练目标</b><p>先写 1–3 条可复盘的目标，达成环才会出现。</p><a href="#plan" data-sx-jump="plan-form">去添加训练目标 →</a></div>`;
    const heatHead = `<div class="dash-heat-head"><span></span>${['一', '二', '三', '四', '五', '六', '日'].map((day) => `<i>${day}</i>`).join('')}</div>`;
    const heatFoot = `<div class="dash-heat-foot"><span>少</span>${[0, 1, 2, 3, 4].map((level) => `<i class="dash-heat-cell is-${level}"></i>`).join('')}<span>多</span><em>训练日</em></div>`;
    const showHeat = totalSessions >= 3 || totalDashGames >= 3;
    const sparseLayout = activeGameWeeks.length < 3;
    const currentWeekDays = (dash.days || []).slice(-7);
    const activeCurrentDays = currentWeekDays.filter((day) => day.sessions || day.games);
    const compactRhythm = activeCurrentDays.length
      ? `<div class="dash-week-strip">${activeCurrentDays.map((day) => `<div><span>${text((day.date || '').slice(5))}</span><b>${fmt(day.sessions)} 场</b><small>${day.games ? `${fmt(day.games)} 局` : '未挂局'}</small></div>`).join('')}</div><p class="dash-rhythm-note">训练节奏需要更多训练课才能形成趋势；先保持每周记录。</p>`
      : '<div class="dash-empty-chart">本周还没有训练课，训练节奏暂时为空。</div>';
    const rhythmBody = showHeat
      ? `${heatHead}<div class="dash-heat">${heatRows.join('')}</div>${heatFoot}`
      : compactRhythm;
    const dashHtml = `<section class="train-dash">
      <div class="dash-hero">
        <div class="dash-hero-main"><span class="dash-eyebrow">TRAINING PULSE</span><h2>赛训看板</h2><p>${text(dashCurrent.start || '本周')} — ${text(dashCurrent.end || '')} · 只看训练过程，不把对局胜率当训练成绩。</p></div>
        <div class="dash-hero-side"><span>本周训练</span><b>${fmt(dashCurrent.sessionCount || 0)}</b><small>场 · ${fmt(dashCurrent.gameCount || 0)} 局</small></div>
        <div class="dash-hero-mark">${icon('setup')}</div>
      </div>
      <div class="dash-kpis">${dashKpis}</div>
      <div class="dash-grid${sparseLayout ? ' is-sparse' : ''}">
        <div class="dash-panel is-load"><div class="dash-panel-head"><div><span>LOAD</span><h3>近 8 周训练负荷</h3></div><small>按训练课挂接对局统计</small></div>${loadChart}</div>
        <div class="dash-panel is-goal"><div class="dash-panel-head"><div><span>GOALS</span><h3>目标达成</h3></div><small>${fmt(goalTotal)} 条目标</small></div>${goalBody}</div>
        <div class="dash-panel is-heat"><div class="dash-panel-head"><div><span>RHYTHM</span><h3>训练节奏</h3></div><small>${showHeat ? '近 8 周 · 每天' : '本周'}</small></div>${rhythmBody}<div class="dash-coverage">${coverageRows}</div></div>
        <div class="dash-panel is-recent"><div class="dash-panel-head"><div><span>RECENT</span><h3>最近训练课</h3></div><a href="#plan" data-sx-jump="plan-list">全部 →</a></div><div class="dash-recent">${recentRows || '<p class="dash-empty">还没有训练课。</p>'}</div></div>
      </div>
    </section>`;
    return withPage('比赛与训练计划',`以比赛为中心：先登记比赛，训练计划挂到比赛下 · 已登记 ${fmt(competitions.length)} 场比赛、${fmt(schedules.length)} 条训练计划（${fmt(valid)} 条有效）。`,
      lede([['比赛',`${fmt(competitions.length)} 场`,nextComp?`下一场 ${nextComp.date}`:'还没有比赛'],['已登记训练',`${fmt(schedules.length)} 条`,'训练赛排期'],['下一场训练',next?`${next.date} ${next.start_time||''}`:'—',next?'已排期':'还没有未来计划'],['训练组',`${fmt(new Set(schedules.map((x) => x.session).filter(Boolean)).size)} 个`,'按 session 归组']])
      + `<div class="sx-plan-layout">${compSection}${compFormSection}</div>`
      + dashHtml
      + vocabDatalist(vocabList(vocab, 'session'))
      + `<div class="sx-plan-layout">${planSection}${formSection}</div>`,false,
      `<a class="control sx-head-cta" href="#plan" data-sx-jump="competition-form">添加比赛</a>`,false,true);
  }
  /* 比赛详情：一名教练负责的一场比赛，把训练课、对局、选手聚合到一页。
     数据来自 /api/studio/workspace/competitions/<id>（schedules + session_matches）
     与 /api/v3/players-board（本队分路名单）。 */
  function competitionPage(value) {
    const detail = (Array.isArray(value) ? value[0] : value) || {};
    const board = (Array.isArray(value) ? value[1] : null) || {};
    const c = detail.competition || {};
    const schedules = detail.schedules || [];
    const matches = detail.matches || [];
    const teams = detail.teams || [];
    const roster = board.roster || [];
    const status = c.status || 'planned';
    const foe = teams.find((t) => t.id === c.opponent_team_id)?.name || '对手未指定';
    const resultLabel = (m) => (m.own_side && m.winner ? (m.winner === m.own_side ? 'win' : 'loss') : '');
    const scoreOf = (m) => {
      let score = m.score;
      if (typeof score === 'string') { try { score = JSON.parse(score); } catch { score = null; } }
      if (!score || typeof score !== 'object') return '';
      const own = m.own_side === 'red' ? 'red' : 'blue';
      const a = score[own], b = score[own === 'blue' ? 'red' : 'blue'];
      return Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? `${fmt(Number(a))} : ${fmt(Number(b))}` : '';
    };
    const reviewed = schedules.filter((s) => s.review_status === 'done').length;
    const kpis = stats([
      ['训练课', `${fmt(schedules.length)} 场`, reviewed ? `已复盘 ${fmt(reviewed)} 场` : '还没有复盘'],
      ['关联对局', `${fmt(matches.length)} 局`, '训练课自动归集'],
      ['本队选手', `${fmt(roster.length)} 人`, '按分路名单'],
      ['赛事状态', statusLabels[status] || status, c.owner ? `负责人 ${c.owner}` : '负责人未定'],
    ]);
    const hero = `<div class="comp-hero">
      <div><span>比赛日期</span><b>${text(c.date)}</b></div>
      <div><span>对手</span><b>${text(foe)}</b></div>
      <div><span>赛段</span><b>${text(c.stage || '未填写')}</b></div>
      <div><span>赛制</span><b>${text(c.format || '未填写')}</b></div>
      <div><span>负责教练</span><b>${text(c.owner || '未指定')}</b></div>
    </div>${c.notes ? `<p class="comp-note">${text(c.notes)}</p>` : ''}`;
    const rosterRows = roster.length ? `<div class="comp-roster">${roster.map((p) => `<article class="comp-player">
      <span class="comp-lane">${text(p.lane || '分路未定')}</span>
      <b>${text(p.member || p.player || '未命名')}</b>
      <small>${text(p.player || '—')} · ${fmt(p.games || 0)} 局 · 胜率 ${p.winRate != null ? pct(p.winRate) : '—'}${p.bound ? '' : ' · 未认领'}</small>
    </article>`).join('')}</div>` : '<div class="empty">还没有本队分路名单；先在「选手」里认领对局昵称。</div>';
    const schedRows = schedules.length ? `<div class="comp-rows">${schedules.map((s) => `<a class="comp-row" href="#session/${encodeURIComponent(s.id)}">
      <span class="comp-row-date">${text(s.date)}<small>${text(s.start_time || '时间未定')}</small></span>
      <b>${text(s.session || '训练组未定')}</b>
      <i>${text(s.format || '赛制未定')}</i>
      <em class="comp-state is-${s.review_status === 'done' ? 'done' : 'pending'}">${s.review_status === 'done' ? '已复盘' : '待复盘'}</em>
    </a>`).join('')}</div>` : '<div class="empty">这场比赛还没有关联训练课；在训练计划里把训练课的「比赛」选成本场即可。</div>';
    const matchRows = matches.length ? `<div class="comp-rows">${matches.map((m) => {
      const result = resultLabel(m);
      const score = scoreOf(m);
      return `<a class="comp-row" href="#match/${encodeURIComponent(m.match_key)}">
        <span class="comp-row-date">${text(m.date)}<small>${text(m.session || '训练赛')}</small></span>
        <b>对阵 ${text(teams.find((t) => t.id === m.enemy_team_id)?.name || '对手未标注')}</b>
        <i class="comp-result ${result}">${result === 'win' ? '胜' : result === 'loss' ? '负' : '—'}${score ? ' ' + score : ''}</i>
        <em>${m.duration ? time(Number(m.duration)) : '—'}</em>
      </a>`;
    }).join('')}</div>` : '<div class="empty">还没有归集到对局；采集后按日期/对手自动关联，或在训练课里手动挂局。</div>';
    return withPage('比赛详情', `${c.name || '比赛'} · ${c.date || ''} · 对阵 ${foe} · 训练课 ${fmt(schedules.length)} 场 / 对局 ${fmt(matches.length)} 局`,
      `<div class="page-head-actions"><a class="control" href="#plan">← 全部比赛</a></div>`
      + `<section class="section"><div class="section-heading"><div><h2>${text(c.name || '未命名比赛')}</h2><p>${text(c.stage || '赛段未填写')} · ${text(c.format || '赛制未填写')} · ${statusLabels[status] || status}</p></div></div>${hero}${kpis}</section>`
      + block('本队选手', '按分路列出本队名单与近期胜率；点「选手」可查看个人档案。', rosterRows)
      + block('训练课', '挂在这场比赛下的训练计划与训练课；点击进入训练课复盘。', schedRows, `<a class="control" href="#plan" data-sx-jump="plan-form">添加训练课</a>`)
      + block('关联对局', '训练课按「手工关联 → 日期+对手 → 日期+训练组 → 日期」归集到的对局。', matchRows),
      false,
      `<a class="control sx-head-cta" href="#plan">全部比赛</a>`, false, true);
  }

  function sessionReport(value) {
    const s = value.schedule || {};
    const team = value.team || null;
    const matches = value.matches || [];
    const players = value.players || [];
    const brief = value.opponentBrief;
    const parseList = (raw) => {
      try { const list = JSON.parse(raw || '[]'); return Array.isArray(list) ? list : []; } catch { return []; }
    };
    const goalStatusLabels = {pending:'未评估', achieved:'达成', partial:'部分达成', missed:'未达成'};
    const goals = parseList(s.goals).map((item) => typeof item === 'string'
      ? {label:item, target:'', status:'pending', actual:null}
      : {label:String(item.label || ''), target:String(item.target || ''), status:item.status || 'pending',
         metricId:String(item.metricId || ''), actual:item.actual, auto:!!item.auto});
    const metric = (id) => value.metrics?.[id] || {};
    const resultOf = (m) => m.own_side && m.winner ? (m.winner === m.own_side ? 'win' : 'loss') : null;
    const wins = metric('session.win_count').value ?? matches.filter((m) => resultOf(m) === 'win').length;
    const losses = metric('session.loss_count').value ?? matches.filter((m) => resultOf(m) === 'loss').length;
    const durations = matches.map((m) => Number(m.duration)).filter((n) => Number.isFinite(n) && n > 0);
    const localAvg = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    const avg = metric('session.avg_duration').value ?? localAvg;
    const matchCount = metric('session.match_count').value ?? matches.length;
    const winRate = metric('session.win_rate').value;
    const trainingGameCount = metric('training.session_game_count').value ?? matchCount;
    const trainingDuration = metric('training.session_duration').value;
    const goalCompletion = metric('training.session_goal_completion').value;
    const reviewCompletion = metric('training.session_review_completion').value;
    const scoreOf = (m) => {
      try {
        const score = typeof m.score === 'string' ? JSON.parse(m.score) : m.score;
        if (score && score.blue != null && score.red != null) return `${fmt(score.blue)} : ${fmt(score.red)}`;
        if (score && score.left != null) return `${fmt(score.left)} : ${fmt(score.right)}`;
      } catch {}
      return '—';
    };
    const resultLabel = (r) => r === 'win' ? '胜' : r === 'loss' ? '负' : '—';
    const teamName = team?.name || '未指定对手';
    const date = s.date || '日期未定';
    const generated = localDate();
    const attendance = parseList(s.attendance);
    const attendanceNames = players.filter((player) => attendance.includes(player.id)).map((player) => player.name);
    const matchTable = matches.map((m) => `<tr><td>${text(m.date || '—')}</td><td>${text(m.enemyName || teamName)}</td><td class="num">${scoreOf(m)}</td><td class="${resultOf(m) === 'win' ? 'win' : resultOf(m) === 'loss' ? 'loss' : ''}">${resultLabel(resultOf(m))}</td><td class="num">${time(m.duration)}</td></tr>`).join('');
    const briefHtml = brief ? `<div class="report-brief">
      <div class="report-brief-head"><b>${text(brief.name)}</b><span>${fmt(brief.matches)} 局 · 胜率 ${pct(brief.winRate)}</span></div>
      <div class="report-brief-block"><span>常用英雄</span><div class="report-hero-row">${(brief.heroes || []).map((h) => `<i>${portrait(h.hero)}<small>${fmt(h.games)}</small></i>`).join('') || '—'}</div></div>
      <div class="report-brief-block"><span>禁用习惯</span><div class="report-hero-row">${(brief.bans || []).map((h) => `<i>${portrait(h.hero)}<small>${fmt(h.games)}</small></i>`).join('') || '—'}</div></div>
      <div class="report-brief-block"><span>关键选手</span><div class="report-players">${(brief.players || []).slice(0, 5).map((p) => `<em>${text(p.lane || '位置未知')} · ${text(p.name)}</em>`).join('') || '—'}</div></div>
    </div>` : '<p class="report-muted">未指定对手，暂无对手简报。</p>';
    const toolbar = `<div class="report-toolbar"><a class="control" href="#session/${encodeURIComponent(s.id || '')}">← 返回训练课</a><div class="report-toolbar-actions"><button type="button" class="control" data-sx-report-image>导出图片</button><button type="button" class="primary" data-sx-print>打印 / 保存 PDF</button></div></div>`;
    return `<div class="report-page">${toolbar}<article class="report-sheet">
      <header class="report-brand"><span class="report-mark">${icon('setup')}</span><div><b>赛训数据</b><small>TRAINING DATA</small></div><span class="report-kind">训练课报告</span></header>
      <section class="report-title"><div><span class="report-eyebrow">SESSION REPORT</span><h1>${text(date)} · 对阵 ${text(teamName)}</h1><p>${text(s.start_time || '时间未定')} · ${text(s.format || '赛制未定')} · ${text(s.session || '训练组未定')}</p></div><div class="report-stamp"><span>生成日期</span><b>${generated}</b></div></section>
      <section class="report-kpis">${[['训练局数', fmt(trainingGameCount), '本场'], ['训练时长', trainingDuration != null ? `${fmt(trainingDuration / 3600, 1)} 小时` : '—', '累计'], ['目标达成率', goalCompletion != null ? pct(goalCompletion) : '—', '按目标'], ['复盘完成率', reviewCompletion != null ? pct(reviewCompletion) : '—', '本场']].map(([label, value, note]) => `<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('')}</section>
      <div class="report-context"><span>对局上下文</span>${fmt(matchCount)} 局 · 胜率 ${winRate != null ? pct(winRate) : '—'} · 场均 ${time(avg)} · ${wins} 胜 ${losses} 负</div>
      <section class="report-columns">
        <div class="report-main">
          <div class="report-section"><h2>训练目标</h2>${goals.length ? `<ol class="report-goals">${goals.map((goal) => `<li class="is-${esc(goal.status)}"><b>${text(goal.label)}</b>${(goal.target || goal.actual != null) ? `<em>${[goal.target ? `目标 ${text(goal.target)}` : '', goal.actual != null ? `实际 ${fmt(goal.actual)}` : ''].filter(Boolean).join(' · ')}</em>` : ''}<i>${text(goalStatusLabels[goal.status] || '未评估')}</i></li>`).join('')}</ol>` : '<p class="report-muted">本场未填写训练目标。</p>'}</div>
          <div class="report-section"><h2>关联对局</h2>${matchTable ? `<table class="report-table"><thead><tr><th>日期</th><th>对手</th><th class="num">比分</th><th>结果</th><th class="num">时长</th></tr></thead><tbody>${matchTable}</tbody></table>` : '<p class="report-muted">本场没有关联对局。</p>'}</div>
        </div>
        <aside class="report-side">
          <div class="report-section"><h2>赛后复盘</h2><div class="report-review">${esc(s.review || '还没有填写赛后复盘。').replace(/\n/g, '<br>')}</div></div>
          <div class="report-section"><h2>出勤</h2><p class="report-muted">${attendanceNames.length ? attendanceNames.map(text).join(' · ') : '本场未记录出勤，或本队名单尚未建立。'}</p></div>
          <div class="report-section"><h2>对手简报</h2>${briefHtml}</div>
        </aside>
      </section>
      <footer class="report-footer"><span>数据来源：营地面板与对局档案</span><span>赛训数据 · ${generated}</span></footer>
    </article></div>`;
  }
  function weeklyReport(data, key) {
    const schedules = data[0]?.schedules || [];
    const allMatches = data[1]?.matches || [];
    const effects = data[2]?.results || [];
    const metricData = data[5] || {};
    const metrics = metricData.metrics || {};
    const metric = (id) => metrics[id] || {};
    const overview = data[3]?.overview || {};
    const teams = data[4]?.teams || [];
    const teamName = overview.profile?.teamName || overview.teamName || '本队';
    let start = /^\d{4}-\d{2}-\d{2}$/.test(String(key || '')) ? String(key) : '';
    if (!start) {
      const now = new Date();
      now.setDate(now.getDate() - (now.getDay() + 6) % 7);
      start = localDate(now);
    }
    const endDate = new Date(start + 'T00:00:00');
    endDate.setDate(endDate.getDate() + 6);
    const end = localDate(endDate);
    const inRange = (value) => String(value || '') >= start && String(value || '') <= end;
    const weekSchedules = schedules.filter((s) => inRange(s.date));
    const weekMatches = allMatches.filter((m) => inRange(m.date));
    const weekEffects = effects.filter((e) => inRange(e.start_date));
    const prevStartDate = new Date(start + 'T00:00:00');
    prevStartDate.setDate(prevStartDate.getDate() - 7);
    const prevStart = localDate(prevStartDate);
    const prevEndDate = new Date(prevStartDate);
    prevEndDate.setDate(prevEndDate.getDate() + 6);
    const prevEnd = localDate(prevEndDate);
    const prevRange = (value) => String(value || '') >= prevStart && String(value || '') <= prevEnd;
    const prevSchedules = schedules.filter((s) => prevRange(s.date));
    const prevMatches = allMatches.filter((m) => prevRange(m.date));
    const teamOf = (id) => teams.find((t) => t.id === id)?.name || '未指定对手';
    const resultOf = (m) => m.own_side && m.winner
      ? (m.winner === m.own_side ? 'win' : 'loss')
      : (m.result === 'win' ? 'win' : m.result === 'loss' ? 'loss' : null);
    const wins = metric('week.win_count').value ?? weekMatches.filter((m) => resultOf(m) === 'win').length;
    const losses = metric('week.loss_count').value ?? weekMatches.filter((m) => resultOf(m) === 'loss').length;
    const prevWins = prevMatches.filter((m) => resultOf(m) === 'win').length;
    const prevLosses = prevMatches.filter((m) => resultOf(m) === 'loss').length;
    const currentRate = metric('week.win_rate').value ?? (wins + losses ? wins / (wins + losses) * 100 : null);
    const prevRate = prevWins + prevLosses ? prevWins / (prevWins + prevLosses) * 100 : null;
    const usableEffects = weekEffects.filter((e) => e.effect?.available);
    const meanEffect = usableEffects.length
      ? usableEffects.reduce((sum, e) => sum + (e.effect.effect_size || e.effect.effectSize || 0), 0) / usableEffects.length
      : null;
    const goalCompletionFor = (list) => {
      let total = 0;
      let achieved = 0;
      for (const schedule of list) {
        try {
          const items = JSON.parse(schedule.goals || '[]');
          for (const goal of Array.isArray(items) ? items : []) {
            if (typeof goal !== 'object' || !goal) continue;
            total += 1;
            if (goal.status === 'achieved') achieved += 1;
          }
        } catch {}
      }
      return total ? achieved / total * 100 : null;
    };
    const trainingWeekSessionCount = metric('training.week_session_count').value ?? weekSchedules.length;
    const trainingWeekGameCount = metric('training.week_game_count').value ?? weekMatches.length;
    const trainingWeekGoalCompletion = metric('training.week_goal_completion').value ?? goalCompletionFor(weekSchedules);
    const trainingWeekReviewCompletion = metric('training.week_review_completion').value
      ?? (weekSchedules.length ? weekSchedules.filter((s) => s.review_status === 'done').length / weekSchedules.length * 100 : null);
    const prevReviewCompletion = prevSchedules.length
      ? prevSchedules.filter((s) => s.review_status === 'done').length / prevSchedules.length * 100
      : null;
    const prevGoalCompletion = goalCompletionFor(prevSchedules);
    const prevEffects = effects.filter((e) => prevRange(e.start_date));
    const prevUsableEffects = prevEffects.filter((e) => e.effect?.available);
    const prevMeanEffect = prevUsableEffects.length
      ? prevUsableEffects.reduce((sum, e) => sum + (e.effect.effect_size || e.effect.effectSize || 0), 0) / prevUsableEffects.length
      : null;
    const deltaText = (value, suffix = '', digits = 0) => `${value > 0 ? '+' : ''}${fmt(value, digits)}${suffix}`;
    const compareCells = [
      ['训练课', prevSchedules.length, trainingWeekSessionCount, ' 场', false, 0],
      ['训练局数', prevMatches.length, trainingWeekGameCount, ' 局', false, 0],
      ['目标达成率', prevGoalCompletion, trainingWeekGoalCompletion, '%', true, 1],
      ['复盘完成率', prevReviewCompletion, trainingWeekReviewCompletion, '%', true, 1],
      ['平均效应量', prevMeanEffect, meanEffect, '', false, 2],
    ].map(([label, before, after, suffix, isRate, digits]) => {
      const delta = before == null || after == null ? null : after - before;
      const show = (value) => value == null ? '—' : isRate ? pct(value) : `${fmt(value, digits)}${suffix}`;
      const deltaLabel = delta == null ? '' : delta === 0 ? ' · 持平' : ` · ${delta > 0 ? '↑' : '↓'} ${deltaText(delta, isRate ? ' pp' : suffix, digits)}`;
      return `<div><span>${label}</span><b>${show(after)}</b><small>上周 ${show(before)}${deltaLabel}</small></div>`;
    }).join('');
    const durations = weekMatches.map((m) => Number(m.duration)).filter((n) => Number.isFinite(n) && n > 0);
    const avg = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    const goals = [];
    const reviews = [];
    for (const schedule of weekSchedules) {
      try {
        const list = JSON.parse(schedule.goals || '[]');
        for (const goal of Array.isArray(list) ? list : []) {
          const label = typeof goal === 'string' ? goal : String(goal?.label || '');
          if (label && !goals.includes(label)) goals.push(label);
        }
      } catch {}
      if (schedule.review) reviews.push({date:schedule.date, review:schedule.review});
    }
    const linkedFor = (schedule) => weekMatches.filter((match) => match.date === schedule.date && (
      (!schedule.opponent_team_id && !schedule.session)
      || (schedule.opponent_team_id && match.enemy_team_id === schedule.opponent_team_id)
      || (schedule.session && match.session === schedule.session)
    ));
    const sessionRows = [...weekSchedules].sort((a, b) => String(a.date).localeCompare(String(b.date))).map((schedule) => {
      const linked = linkedFor(schedule);
      const w = linked.filter((m) => resultOf(m) === 'win').length;
      const l = linked.filter((m) => resultOf(m) === 'loss').length;
      return `<tr><td>${text(schedule.date)}</td><td>${text(teamOf(schedule.opponent_team_id))}</td><td class="num">${fmt(linked.length)}</td><td class="${w ? 'win' : ''}">${w} 胜 ${l} 负</td><td>${schedule.review_status === 'done' ? '已复盘' : '待复盘'}</td></tr>`;
    }).join('');
    const scoreOf = (m) => {
      try {
        const score = typeof m.score === 'string' ? JSON.parse(m.score) : m.score;
        if (score && score.blue != null && score.red != null) return `${fmt(score.blue)} : ${fmt(score.red)}`;
        if (score && score.left != null) return `${fmt(score.left)} : ${fmt(score.right)}`;
      } catch {}
      return '—';
    };
    const matchRows = [...weekMatches].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 12).map((m) => `<tr><td>${text(m.date || '—')}</td><td>${text(teamOf(m.enemy_team_id))}</td><td class="num">${scoreOf(m)}</td><td class="${resultOf(m) === 'win' ? 'win' : resultOf(m) === 'loss' ? 'loss' : ''}">${resultOf(m) === 'win' ? '胜' : resultOf(m) === 'loss' ? '负' : '—'}</td><td class="num">${time(m.duration)}</td></tr>`).join('');
    const generated = localDate();
    return `<div class="report-page"><div class="report-toolbar"><a class="control" href="#reports">← 返回报告库</a><div class="report-toolbar-actions"><button type="button" class="control" data-sx-report-image>导出图片</button><button type="button" class="primary" data-sx-print>打印 / 保存 PDF</button></div></div><article class="report-sheet">
      <header class="report-brand"><span class="report-mark">${icon('setup')}</span><div><b>赛训数据</b><small>TRAINING DATA</small></div><span class="report-kind">训练周报</span></header>
      <section class="report-title"><div><span class="report-eyebrow">WEEKLY REPORT</span><h1>${text(teamName)} · ${text(start)} — ${text(end)}</h1><p>按训练课与对局汇总 · 共 ${fmt(weekSchedules.length)} 场训练、${fmt(weekMatches.length)} 局</p></div><div class="report-stamp"><span>生成日期</span><b>${generated}</b></div></section>
      <section class="report-kpis">${[['训练课', fmt(trainingWeekSessionCount), '场'], ['训练局数', fmt(trainingWeekGameCount), '局'], ['目标达成率', trainingWeekGoalCompletion != null ? pct(trainingWeekGoalCompletion) : '—', '本周'], ['复盘完成率', trainingWeekReviewCompletion != null ? pct(trainingWeekReviewCompletion) : '—', '本周']].map(([label, value, note]) => `<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('')}</section>
      <div class="report-context"><span>对局上下文</span>胜率 ${currentRate != null ? pct(currentRate) : '—'} · 场均 ${time(avg)} · ${wins} 胜 ${losses} 负</div>
      <section class="report-compare">${compareCells}</section>
      <section class="report-columns">
        <div class="report-main">
          <div class="report-section"><h2>本周训练课</h2>${sessionRows ? `<table class="report-table"><thead><tr><th>日期</th><th>对手</th><th class="num">对局</th><th>战绩</th><th>复盘</th></tr></thead><tbody>${sessionRows}</tbody></table>` : '<p class="report-muted">本周没有登记训练课。</p>'}</div>
          <div class="report-section"><h2>对局明细</h2>${matchRows ? `<table class="report-table"><thead><tr><th>日期</th><th>对手</th><th class="num">比分</th><th>结果</th><th class="num">时长</th></tr></thead><tbody>${matchRows}</tbody></table>` : '<p class="report-muted">本周没有对局记录。</p>'}</div>
        </div>
        <aside class="report-side">
          <div class="report-section"><h2>本周训练目标</h2>${goals.length ? `<ol class="report-goals">${goals.map((goal) => `<li>${text(goal)}</li>`).join('')}</ol>` : '<p class="report-muted">本周还没有写训练目标。</p>'}</div>
          <div class="report-section"><h2>教练复盘</h2>${reviews.length ? reviews.map((item) => `<div class="report-review-item"><b>${text(item.date)}</b><p>${esc(item.review).replace(/\n/g, '<br>')}</p></div>`).join('') : '<p class="report-muted">本周还没有赛后复盘。</p>'}</div>
          <div class="report-section"><h2>训练效果</h2>${weekEffects.length ? `<div class="report-effect"><b>${fmt(weekEffects.length)} 条干预记录</b><span>可对比 ${fmt(usableEffects.length)} 条 · 平均效应量 ${meanEffect == null ? '—' : fmt(meanEffect, 2)}</span></div>` : '<p class="report-muted">本周没有训练干预记录。</p>'}</div>
        </aside>
      </section>
      <footer class="report-footer"><span>数据来源：训练计划、对局档案与训练效果</span><span>赛训数据 · ${generated}</span></footer>
    </article></div>`;
  }
  function sessionPage(value, key) {
    if (new URLSearchParams(location.hash.split('?')[1] || '').get('report') === '1') return sessionReport(value);
    const s = value.schedule || {};
    const team = value.team || null;
    const matches = value.matches || [];
    const players = value.players || [];
    const parseList = (raw) => {
      try {
        const list = JSON.parse(raw || '[]');
        return Array.isArray(list) ? list : [];
      } catch { return []; }
    };
    const goalStatusLabels = {pending:'未评估', achieved:'达成', partial:'部分达成', missed:'未达成'};
    const goalMetricList = value.goalMetrics || [];
    const goalMetricLabel = (id) => goalMetricList.find((metric) => metric.id === id)?.label || id;
    const goalItems = parseList(s.goals).map((item) => typeof item === 'string'
      ? {label:item, target:'', status:'pending', metricId:'', actual:null}
      : {label:String(item.label || ''), target:String(item.target || ''), status:item.status || 'pending',
         metricId:String(item.metricId || ''), actual:item.actual, auto:!!item.auto,
         missingReason:item.missingReason || ''});
    const attendance = parseList(s.attendance);
    const status = statusLabels[s.status] || s.status || '计划中';
    const reviewStatus = s.review_status === 'done' ? '已复盘' : '待复盘';
    const metricValue = (id) => value.metrics?.[id]?.value;
    const sessionGameCount = metricValue('training.session_game_count') ?? matches.length;
    const sessionGoalCompletion = metricValue('training.session_goal_completion');
    const reason = {schedule:'已绑定', manual:'手动关联', date_opponent:'日期 + 对手', date_session:'日期 + 训练组', date:'同日全部', none:'未关联'}[value.matchReason] || '未关联';
    const scoreOf = (m) => {
      try {
        const score = typeof m.score === 'string' ? JSON.parse(m.score) : m.score;
        if (score && score.blue != null && score.red != null) return `${fmt(score.blue)} : ${fmt(score.red)}`;
        if (score && score.left != null) return `${fmt(score.left)} : ${fmt(score.right)}`;
      } catch {}
      return '—';
    };
    const winnerOf = (m) => m.winner === 'blue' ? '蓝方胜' : m.winner === 'red' ? '红方胜' : '结果未知';
    const matchRows = matches.map((m) => `<a class="sx-session-match" href="${route('match', m.match_key)}">
      <span class="sx-session-match-date">${text(m.date || '日期未知')}</span>
      <span class="sx-session-match-main"><b>${text(m.enemyName || team?.name || '对手未标注')}</b><small>${text(m.session || '训练组未定')}</small></span>
      <span class="sx-session-match-score">${scoreOf(m)}</span>
      <span class="sx-session-match-result">${winnerOf(m)}</span>
      <span class="sx-session-match-go">→</span>
    </a>`).join('');
    const manualKeys = value.manualMatchKeys || [];
    const available = value.availableMatches || [];
    const manualMode = !!value.manualLinks;
    const checkedKeys = new Set(manualMode ? manualKeys : matches.map((m) => m.match_key));
    const linkRows = available.map((m) => `<label class="sx-link-row">
      <input type="checkbox" name="matchKey" value="${esc(m.match_key)}" ${checkedKeys.has(m.match_key) ? 'checked' : ''}>
      <span><b>${text(m.date || '日期未知')} · ${text(m.enemyName || '对手未标注')}</b><small>${text(m.session || '训练组未定')}</small></span>
      <em>${m.winner === 'blue' ? '蓝方胜' : m.winner === 'red' ? '红方胜' : '结果未知'}</em>
    </label>`).join('');
    const linkDialog = `<dialog class="sx-dialog sx-link-dialog" id="sx-link-dialog">
      <form data-feature-form="sessionLinks">
        <input type="hidden" name="id" value="${esc(s.id)}">
        <div class="sx-dialog-head"><div><span class="sx-eyebrow">MATCH LINKS</span><h2>手动关联对局</h2></div><button type="button" class="sx-dialog-x" data-sx-dialog-close aria-label="关闭">×</button></div>
        <p class="sx-dialog-note">${manualMode ? '当前使用手动关联；取消「恢复自动」会回到按规则匹配。' : '保存后会锁成手动关联，不再被日期规则自动改写。'}</p>
        <label class="sx-search">${icon('search')}<input data-sx-link-search placeholder="搜索日期、对手或训练组" aria-label="搜索可关联对局"></label>
        <div class="sx-link-list" data-sx-link-list>${linkRows || '<p class="sx-empty">当前没有可关联的对局。</p>'}</div>
        <p class="form-status" role="status"></p>
        <div class="sx-dialog-actions"><button type="button" class="control" data-sx-dialog-close>取消</button><button type="button" class="control" data-sx-link-reset>恢复自动</button><button class="primary" type="submit">保存关联</button></div>
      </form>
    </dialog>`;
    const matchBlock = block('关联对局', `关联方式：${reason} · ${fmt(matches.length)} 局`,
      (matchRows ? `<div class="sx-session-matches">${matchRows}</div>` : `<div class="sx-empty sx-empty-inline"><b>这场训练课还没有关联对局</b><p>可以手动挂局，也可以按日期 / 对手 / 训练组自动匹配。</p><a class="control" href="#matches">去对局档案 →</a></div>`),
      `<button type="button" class="control" data-sx-link-matches>${manualMode ? '手动关联 · 已锁定' : '手动关联'}</button>`);
    const brief = value.opponentBrief;
    const recentHtml = brief ? (brief.recent || []).map((g) => `<div class="sx-brief-row"><span>${text(String(g.start || '').slice(5, 16) || '日期未知')}</span><b class="${g.win === true ? 'is-win' : g.win === false ? 'is-loss' : ''}">${g.win === true ? '胜' : g.win === false ? '负' : '—'}</b><small>${time(g.duration)}</small></div>`).join('') : '';
    const briefHtml = brief ? `<div class="sx-brief">
      <div class="sx-brief-head"><b>${text(brief.name)}</b><span>${fmt(brief.matches)} 局 · ${fmt(brief.wins)} 胜 ${fmt(brief.losses)} 负 · 胜率 ${pct(brief.winRate)}</span></div>
      <div class="sx-brief-cols">
        <div><span>最近交手</span>${recentHtml || '<em>暂无</em>'}</div>
        <div><span>常用英雄</span><div class="sx-brief-heroes">${(brief.heroes || []).map((h) => `<i>${portrait(h.hero)}<small>${fmt(h.games)}</small></i>`).join('') || '<em>暂无</em>'}</div></div>
        <div><span>禁用习惯</span><div class="sx-brief-heroes">${(brief.bans || []).map((h) => `<i>${portrait(h.hero)}<small>${fmt(h.games)}</small></i>`).join('') || '<em>暂无</em>'}</div></div>
        <div><span>关键选手</span><div class="sx-brief-players">${(brief.players || []).slice(0, 5).map((p) => `<em>${text(p.lane || '位置未知')} · ${text(p.name)}</em>`).join('') || '<em>暂无</em>'}</div></div>
      </div>
      <a class="control" href="${route('team', team?.id || brief.id)}">完整战队页 →</a>
    </div>` : '';
    const opponentBlock = block('对手简报', brief ? '最近交手、常用英雄、禁用习惯与关键选手。' : '这场比赛还没有指定对手。',
      brief ? briefHtml : `<div class="sx-empty sx-empty-inline"><b>还没有指定对手</b><p>在上方编辑计划，选择约战对手后会生成赛前简报。</p></div>`);
    const goalsHtml = goalItems.length ? `<ul class="sx-goal-list">${goalItems.map((goal, i) => `<li class="is-${esc(goal.status)}"><span>${String(i + 1).padStart(2, '0')}</span><b>${text(goal.label)}</b>${goal.metricId ? `<em>${text(goalMetricLabel(goal.metricId))}${goal.actual != null ? ` · ${fmt(goal.actual)}` : ''}</em>` : (goal.target ? `<em>目标 ${text(goal.target)}</em>` : '')}<i>${text(goalStatusLabels[goal.status] || '未评估')}</i></li>`).join('')}</ul>` : '<p class="sx-session-muted">还没有写训练目标；建议写 1–3 条可复盘的目标。</p>';
    const attendanceHtml = players.length
      ? `<div class="sx-attendance">${players.map((p) => `<label><input type="checkbox" name="attendance" value="${esc(p.id)}" ${attendance.includes(p.id) ? 'checked' : ''}>${text(p.name)}</label>`).join('')}</div>`
      : '<p class="sx-session-muted">本队选手主数据还没建立，暂时不能勾选出勤。</p>';
    const GOAL_TEMPLATES = ['前 10 分钟经济领先', '一血率', '团战开团成功率', '控龙率', '推塔节奏', '视野控制', '失误率'];
    const goalTemplates = `<div class="sx-goal-templates">${GOAL_TEMPLATES.map((goal) => `<button type="button" data-sx-goal-template="${esc(goal)}">${esc(goal)}</button>`).join('')}</div>`;
    const goalRows = Array.from({length: Math.max(3, Math.min(6, goalItems.length + 1))}, (_, i) => {
      const goal = goalItems[i] || {label:'', target:'', status:'pending', metricId:''};
      return `<div class="sx-goal-edit">
        <input name="goalLabel" value="${esc(goal.label)}" maxlength="120" placeholder="训练目标，如：前 10 分钟经济领先">
        <select name="goalMetric"><option value="">不绑定指标</option>${goalMetricList.map((metric) => `<option value="${esc(metric.id)}" ${goal.metricId === metric.id ? 'selected' : ''}>${metric.category === 'training' ? '[训练] ' : '[对局] '}${esc(metric.label)}${metric.available ? '' : ' · 未接入'}</option>`).join('')}</select>
        <input name="goalTarget" value="${esc(goal.target)}" maxlength="80" placeholder="目标值">
        <select name="goalStatus">${Object.entries(goalStatusLabels).map(([value, label]) => `<option value="${value}" ${goal.status === value ? 'selected' : ''}>${label}</option>`).join('')}</select>
      </div>`;
    }).join('');
    const reviewForm = form('sessionReview', `<input type="hidden" name="id" value="${esc(s.id)}">
      <div class="sx-goal-form"><span>训练目标</span>${goalTemplates}<div class="sx-goal-editor">${goalRows}</div></div>
      <label>赛后复盘<textarea name="review" rows="6" placeholder="今天做到了什么、没做到什么、下次改什么">${esc(s.review || '')}</textarea></label>
      <div class="sx-session-attendance"><span>出勤 / 上场</span>${attendanceHtml}</div>
      <label>复盘状态<select name="reviewStatus"><option value="pending" ${s.review_status !== 'done' ? 'selected' : ''}>待复盘</option><option value="done" ${s.review_status === 'done' ? 'selected' : ''}>已复盘</option></select></label>`, '保存训练课');
    return withPage('训练课', `${text(s.date || '日期未定')} ${text(s.start_time || '')} · 对阵 ${text(team?.name || '未指定对手')} · ${status}`,
      `<a class="depth-back" href="#plan">← 训练计划</a>`
      +lede([['日期', text(s.date || '—'), text(s.start_time || '时间未定')], ['对手', text(team?.name || '未指定'), text(s.format || '赛制未定')], ['训练局数', `${fmt(sessionGameCount)} 局`, reason], ['目标达成率', sessionGoalCompletion != null ? pct(sessionGoalCompletion) : '—', reviewStatus]])
      +`<div class="sx-session-grid">
        <div class="sx-session-main">${matchBlock}${opponentBlock}</div>
        <div class="sx-session-side">
          ${block('训练目标', '这场训练要验证什么；赛后用同一组目标回看。', goalsHtml)}
          ${block('赛后复盘', '把结论写在这里，下次计划可以直接沿用。', reviewForm)}
        </div>
      </div>`+linkDialog, false, `<a class="control" href="#session/${encodeURIComponent(s.id || '')}?report=1">导出报告</a><a class="control" href="#plan">编辑计划</a>`, false, true);
  }
  const renders={ingest:v=>captureIngestPage.render(v),capture:v=>sourcePages.render('capture',v),shots:v=>sourcePages.render('shots',v),videos:v=>sourcePages.render('videos',v),replays:v=>sourcePages.render('replays',v),review:(v,k)=>reviewPage.render(k,v),playerarchive:v=>playerPages.archivePage(v[0],v[1]),reports:v=>research.reports(v[0]),report:v=>research.report(v[1]),hero:(v,k)=>heroDetail(v[0],v[1],v[2],v[3],v[4],k),featured:v=>featuredPage(v[0],v[1]),playercompare:v=>playerCompare.render(v[0]),playerdetail:(v,k)=>playerPages.soloPage(v[0],k,v[1]),herocompare:v=>heroCompare.render(v[0]),teams:(v,k)=>teamsPage(v[0],k),team:(v,k)=>teamsPage(v[0],k,v[1],v[2],v[3],v[4]),teamtraining:v=>teamTraining(v[0]),ownership:v=>ownership(v[0]),coach:v=>coachBoard.render(v[0],v[1]),compare:v=>laneBoard.render(v[0]),heroes:v=>heroes(v[0]),combos:v=>combos(v[0]),economy:v=>economy(v[0]),effect:v=>effect(v[0],v[1]),versions:(v)=>versions(v[0],v[1]),setup:v=>setup(...v),pending:v=>pending(v[0],v[1],v[2]),plan:v=>plan(v[0],v[1],v[2],v[3],v[4]),competition:v=>competitionPage(v),session:(v,k)=>sessionPage(v[0],k),weekly:(v,k)=>weeklyReport(v,k)};
  async function api(path, options={}) {
    const r=await fetch(API_BASE + '/api/'+path,{cache:'no-store',...options});
    if(!r.ok){
      let detail; try {detail=(await r.json()).detail} catch {}
      /* 后端可能回英文 "Not Found"；教练看到的只能是能读懂的话。 */
      const usable=typeof detail==='string'&&!/^Not Found$|^Internal Server Error$/i.test(detail);
      const error=new Error(usable?detail:(r.status===404?'这一页的数据暂时读不到。':'操作没完成，请稍后重试。'));
      error.status=r.status; throw error;
    }
    return r.json();
  }
  const targets={rename:'studio/teams/rename',merge:'studio/teams/merge',assign:'studio/opponents/assign',coach:'studio/coach',training:'studio/workspace/training',profile:'studio/profile',masterTeam:'studio/workspace/teams',masterMerge:'studio/workspace/teams/merge',masterPlayer:'studio/workspace/players',confirm:'studio/workspace/pending/confirm',schedule:'studio/workspace/schedules',competition:'studio/workspace/competitions'};
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
  /* ── 身份：游戏ID → 选手 → 战队 ──────────────────────────────────────
     建档页的身份对照表、对手归属页的「命名」、选手页的「命名并归队」
     共用这一个弹窗和同一个写接口 /api/v3/identity/name：一处命名，处处生效。 */
  const POSITION_OPTIONS = ['对抗路', '打野', '中路', '发育路', '游走'];
  let identityTeamOptions = [];

  function syncIdentityTeamField(dialog) {
    if (!dialog) return;
    const select = dialog.querySelector('[data-sx-identity-team]');
    const field = dialog.querySelector('[data-sx-identity-newteam]');
    if (select && field) field.hidden = select.value !== '';
  }

  function identityDialog() {
    let dialog = document.querySelector('#sx-identity-dialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'sx-identity-dialog';
    dialog.className = 'sx-dialog sx-identity-dialog';
    dialog.innerHTML = `<form data-sx-identity-form>
      <div class="sx-dialog-head"><div><span class="sx-eyebrow">身份对照</span><h2 data-sx-identity-title>命名游戏 ID</h2></div><button type="button" class="sx-dialog-x" data-sx-identity-close aria-label="关闭">×</button></div>
      <div class="sx-dialog-panel">
        <p class="sx-dialog-subject" data-sx-identity-subject></p>
        <label>选手名称<input name="name" maxlength="40" required placeholder="真实 ID 或常用名，不要填游戏 ID"></label>
        <fieldset class="sx-pos-field"><legend>位置（可多选，第一个勾的是主位置）</legend><div class="sx-pos-chips">${POSITION_OPTIONS.map((x) => `<label class="sx-pos-chip"><input type="checkbox" name="position" value="${x}"><span>${x}</span></label>`).join('')}</div></fieldset>
        <label>所属战队<select name="teamId" data-sx-identity-team></select></label>
        <label data-sx-identity-newteam hidden>新战队名<input name="teamName" maxlength="40" placeholder="如：重庆狼队"></label>
        <p class="sx-dialog-note">保存后，这个游戏 ID 以后自动显示这名选手和这支战队；分析按选手累计，历史对局不改。</p>
      </div>
      <p class="form-status" role="status"></p>
      <div class="sx-dialog-actions"><button type="button" class="control" data-sx-identity-close>取消</button><button class="primary" type="submit">保存</button></div>
    </form>`;
    document.body.appendChild(dialog);
    dialog.querySelectorAll('[data-sx-identity-close]').forEach((button) => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.querySelector('[data-sx-identity-team]').addEventListener('change', () => syncIdentityTeamField(dialog));
    dialog.querySelector('form').addEventListener('submit', (event) => {
      event.preventDefault();
      submitIdentityDialog(dialog);
    });
    return dialog;
  }

  function openIdentityDialog(data = {}) {
    const dialog = identityDialog();
    const teams = data.teams || identityTeamOptions || [];
    const select = dialog.querySelector('[data-sx-identity-team]');
    const current = String(data.teamId || '');
    const known = teams.some((team) => team.id === current);
    select.innerHTML = '<option value="">写新队名…</option>' + teams.map((team) =>
      `<option value="${esc(team.id)}" ${team.id === current ? 'selected' : ''}>${esc(team.name || team.displayName || '未命名战队')}</option>`).join('')
      + (current && !known ? `<option value="${esc(current)}" selected>${esc(data.teamName || '当前战队')}</option>` : '');
    dialog.dataset.accountId = data.accountId || '';
    dialog.dataset.nickname = data.nickname || '';
    dialog.querySelector('[data-sx-identity-title]').textContent = data.playerId ? '调整选手身份' : '命名游戏 ID';
    dialog.querySelector('[data-sx-identity-subject]').textContent =
      `${data.nickname || '未知游戏 ID'}${data.accountId ? ' · 账号 ' + data.accountId : ''}${data.games ? ' · ' + data.games + ' 局' : ''}`;
    dialog.querySelector('[name="name"]').value = data.name || '';
    /* 位置可多选：优先用 positions；老数据只有单个 position 时也认 */
    const currentPositions = Array.isArray(data.positions) && data.positions.length
      ? data.positions
      : (POSITION_OPTIONS.includes(data.position) ? [data.position] : []);
    dialog.querySelectorAll('[name="position"]').forEach((box) => {
      box.checked = currentPositions.includes(box.value);
    });
    dialog.querySelector('[name="teamName"]').value = '';
    syncIdentityTeamField(dialog);
    dialog.querySelector('.form-status').textContent = '';
    const submit = dialog.querySelector('button[type=submit]');
    if (submit) submit.disabled = false;
    if (!dialog.open) dialog.showModal();
    setTimeout(() => dialog.querySelector('[name="name"]')?.focus(), 30);
  }

  function submitIdentityDialog(dialog) {
    const form = dialog.querySelector('form');
    const status = form.querySelector('.form-status');
    const button = form.querySelector('button[type=submit]');
    const checkedPositions = Array.from(form.querySelectorAll('[name="position"]:checked')).map((box) => box.value);
    const payload = {
      accountId: dialog.dataset.accountId || '',
      nickname: dialog.dataset.nickname || '',
      name: form.querySelector('[name="name"]').value.trim(),
      position: checkedPositions[0] || '',
      positions: checkedPositions,
    };
    const teamId = form.querySelector('[name="teamId"]').value;
    if (teamId) payload.teamId = teamId;
    else payload.team = form.querySelector('[name="teamName"]').value.trim();
    if (!payload.name) {
      status.textContent = '请填写选手名称；游戏 ID 不能直接当选手 ID。';
      return;
    }
    if (!payload.teamId && !payload.team) {
      status.textContent = '请选择战队，或写一个新队名。';
      return;
    }
    button.disabled = true;
    status.textContent = '正在保存…';
    api('v3/identity/name', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
      .then(() => { button.disabled = false; dialog.close(); reload(); })
      .catch((error) => { status.textContent = error.message; button.disabled = false; });
  }

  function syncIdentityRows(root) {
    if (!root) return;
    const rows = [...root.querySelectorAll('[data-sx-id-row]')];
    if (!rows.length) return;
    const q = (root.querySelector('[data-sx-id-search]')?.value || '').trim().toLowerCase();
    const filter = root.dataset.sxIdFilter || 'all';
    const expanded = root.dataset.sxIdExpanded === '1';
    let matched = 0, visible = 0;
    rows.forEach((row) => {
      const mapped = row.dataset.state === 'mapped';
      const side = row.dataset.side;
      const okFilter = filter === 'all' || (filter === 'unmapped' && !mapped)
        || (filter === 'mapped' && mapped) || (filter === 'own' && side === 'own')
        || (filter === 'enemy' && side === 'enemy');
      const hit = !q || String(row.dataset.search || '').includes(q);
      const limited = !expanded && filter === 'all' && !q && visible >= 20;
      row.hidden = !(okFilter && hit) || limited;
      if (okFilter && hit) matched++;
      if (okFilter && hit && !limited) visible++;
    });
    const counter = root.querySelector('[data-sx-id-count]');
    if (counter) counter.textContent = q || filter !== 'all' ? `找到 ${fmt(matched)} 个` : `共 ${fmt(matched)} 个游戏ID`;
    const more = root.querySelector('[data-sx-id-more]');
    if (more) {
      more.hidden = expanded || !!q || filter !== 'all' || matched <= 20;
      more.textContent = expanded ? '收起列表' : `显示全部 ${fmt(matched)} 个`;
    }
    const empty = root.querySelector('[data-sx-id-empty]');
    if (empty) empty.hidden = matched > 0;
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
  function submitSessionReview(f) {
    const status = f.querySelector('.form-status');
    const button = f.querySelector('button[type=submit]');
    const id = String(f.querySelector('[name="id"]')?.value || '').trim();
    if (!id) { if (status) status.textContent = '缺少训练课 id。'; return true; }
    const goalLabels = [...f.querySelectorAll('[name="goalLabel"]')].map((input) => input.value.trim());
    const goalMetrics = [...f.querySelectorAll('[name="goalMetric"]')].map((select) => select.value);
    const goalTargets = [...f.querySelectorAll('[name="goalTarget"]')].map((input) => input.value.trim());
    const goalStatuses = [...f.querySelectorAll('[name="goalStatus"]')].map((select) => select.value);
    const goals = goalLabels.map((label, i) => ({
      label, metricId:goalMetrics[i] || '', target:goalTargets[i] || '', status:goalStatuses[i] || 'pending',
    })).filter((goal) => goal.label);
    const attendance = [...f.querySelectorAll('input[name="attendance"]:checked')].map((input) => input.value);
    const review = String(f.querySelector('[name="review"]')?.value || '');
    const reviewStatus = f.querySelector('[name="reviewStatus"]')?.value || 'pending';
    button.disabled = true;
    if (status) status.textContent = '正在保存…';
    api('studio/workspace/sessions/' + encodeURIComponent(id) + '/review', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({goals, review, reviewStatus, attendance}),
    }).then(() => reload()).catch((error) => {
      if (status) status.textContent = error.message;
      button.disabled = false;
    });
    return true;
  }
  function submit(event) {
    const f=event.target.closest('[data-feature-form]'); if(!f)return false;
    event.preventDefault(); const id=f.dataset.featureForm, payload=Object.fromEntries(new FormData(f));
    /* 词表下拉选了「其他（手填）」：用手填值覆盖哨兵值，空值让后端按必填规则拦下。 */
    applyVocabValue(f, payload);
    if (id === 'sessionLinks') {
      const dialog = f.closest('dialog');
      const scheduleId = String(payload.id || '').trim();
      const keys = [...f.querySelectorAll('input[name="matchKey"]:checked')].map((input) => input.value);
      const button = f.querySelector('button[type=submit]');
      const status = f.querySelector('.form-status');
      if (!scheduleId) { if (status) status.textContent = '缺少训练课 id。'; return true; }
      button.disabled = true;
      if (status) status.textContent = '正在保存…';
      api('studio/workspace/sessions/' + encodeURIComponent(scheduleId) + '/links', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({matchKeys:keys}),
      }).then(() => { dialog?.close(); reload(); }).catch((error) => {
        if (status) status.textContent = error.message;
        button.disabled = false;
      });
      return true;
    }
    if (id === 'sessionReview') return submitSessionReview(f);
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
    if(id==='identityClaim') {const aliases=JSON.parse(f.dataset.aliases||'{}');payload.expected=aliases[payload.label]||'';if(payload.expected&&payload.expected!==payload.playerId&&!window.confirm('该昵称已绑定其他选手，确认修改认领吗？'))return true;}
    if(id==='matchbp') { const split=name=>(payload[name]||'').split(/[,，、\n]+/).map(x=>x.trim()).filter(Boolean);payload.bp={bans:{left:split('leftBans'),right:split('rightBans')},picks:{left:split('leftPicks'),right:split('rightPicks')},firstPick:payload.firstPick||'',notes:payload.notes||''}; }
    if(id==='training') { if(payload.endDate && payload.endDate<payload.startDate){f.querySelector('.form-status').textContent='结束日期不能早于开始日期。';return true} payload.target=payload.target===''?null:Number(payload.target); payload.playerIds=payload.playerIds?[payload.playerIds]:[]; }
    if(id==='confirm'&&payload.field==='pick_order'){try{payload.value=JSON.parse(payload.value);if(!Array.isArray(payload.value))throw Error()}catch{f.querySelector('.form-status').textContent='选用顺序须为 JSON 数组；未知时请保留待确认。';return true}}
    const button=f.querySelector('button[type=submit]');button.disabled=true;f.querySelector('.form-status').textContent='正在保存…';
    api(id==='matchmeta'?'v3/match-meta/'+encodeURIComponent(payload.matchKey):id==='matchbp'?'v3/match-bp/'+encodeURIComponent(payload.matchKey):id==='identityClaim'?'v3/identity/claim':id==='identityRoster'?'v3/identity/roster':id==='identityName'?'v3/identity/name':targets[id],{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(result=>{reload()}).catch(error=>{f.querySelector('.form-status').textContent=error.message;button.disabled=false});return true;
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
      const response=await fetch(API_BASE + '/api/v3/import/preview?strict=1&name='+encodeURIComponent(file.name),{method:'POST',body:file});
      const value=await response.json();if(!response.ok)throw Error(value.detail||'表格读取失败');
      if(!root.isConnected)return;status.textContent='请核对识别结果。';
      preview.innerHTML=`<div class="import-preview"><div class="section-heading"><div><h2>${text(value.name)}</h2><p>${value.sheets.length} 个工作表 · 请确认字段识别与粒度</p></div></div>${value.sheets.map(sheet=>`<div class="import-sheet"><h3>${text(sheet.name)} <small>${fmt(sheet.rows)} 行 · 粒度 ${text(sheet.grain||'未识别')}</small></h3><p>字段：${text((sheet.header||[]).join('、'))}</p>${sheet.unmappedColumns?.length?`<p>未映射：${text(sheet.unmappedColumns.join('、'))}</p>`:''}${sheet.warnings?.length?`<p>${text(sheet.warnings.join('；'))}</p>`:''}${table(sheet.header||[],(sheet.sample||[]).map(row=>Array.isArray(row)?row.map(text):(sheet.header||[]).map(key=>text(row[key]))))}</div>`).join('')}<div class="import-actions"><p role="status" data-import-commit-status></p><button class="primary" data-feature-action="import-commit" data-preview-id="${esc(value.previewId)}">确认导入</button></div></div>`;
    }catch(error){status.textContent=error.message}
  }
  function change(event) {
    if (event.target.matches('form[data-feature-form="merge"] select[name="from"], form[data-feature-form="merge"] select[name="into"]')) {
      syncMergePreview(event.target.closest('form'));
      return true;
    }
    if (event.target.matches('[data-sx-team-search]')) { syncSetupTeams(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-id-search]')) { syncIdentityRows(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-own-search]')) { syncOwnershipGroups(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-pending-search]')) { syncPendingQueue(event.target.closest('.section')); return true; }
    if (event.target.matches('[data-sx-link-search]')) {
      const q = event.target.value.trim().toLowerCase();
      event.target.closest('dialog')?.querySelectorAll('.sx-link-row').forEach((row) => {
        row.hidden = !!q && !row.textContent.toLowerCase().includes(q);
      });
      return true;
    }
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
if(captureIngestPage.change(event))return;
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
    if(event.target.matches('[data-pair]')) updatePairs(event.target.closest('[data-pair-data]').parentElement);
    if(event.target.matches('[data-team-search]')) {
      const clear = event.target.closest('.tm-search')?.querySelector('[data-team-search-clear]');
      if (clear) clear.hidden = !event.target.value;
    }
    if(event.target.matches('[data-team-search],[data-team-sort]')) syncTeamList(event.target.closest('.section'));
    if(event.target.matches('[data-ttn-search]')) syncTeamTraining(event.target.closest('.ttn-layout'));
  }
  function click(event) { /* 这三个模块的 click 是 async，返回值是 Promise（恒真），不能直接用来判断是否处理；先用选择器同步判定，再交给它们异步执行。 */
    const searchClear = event.target.closest('[data-team-search-clear]');
    if (searchClear) {
      clearTeamSearch(searchClear.closest('.tm-search')?.querySelector('[data-team-search]'));
      return true;
    }
    const searchBox = event.target.closest('.tm-search');
    if (searchBox) {
      searchBox.querySelector('[data-team-search]')?.focus();
      return true;
    }
    const teamReset = event.target.closest('[data-team-reset]');
    if (teamReset) {
      const root = teamReset.closest('.section');
      const input = root?.querySelector('[data-team-search]');
      if (root && input) {
        input.value = '';
        const clear = root.querySelector('[data-team-search-clear]');
        if (clear) clear.hidden = true;
        const sort = root.querySelector('[data-team-sort]');
        if (sort) sort.value = 'recent';
        root.dataset.teamFilter = '';
        root.querySelectorAll('[data-team-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String((chip.dataset.teamChip || '') === '')));
        syncTeamList(root);
        input.focus();
      }
      return true;
    }
    const mergePick = event.target.closest('[data-merge-pick]');
    if (mergePick) {
      const form = document.querySelector('form[data-feature-form="merge"]');
      if (form) {
        const from = form.querySelector('select[name="from"]');
        const into = form.querySelector('select[name="into"]');
        if (from) from.value = mergePick.dataset.mergeFrom || '';
        if (into) into.value = mergePick.dataset.mergeInto || '';
        syncMergePreview(form);
        form.scrollIntoView({ block: 'nearest' });
      }
      return true;
    }
    const ttSelect = event.target.closest('[data-tt-select]');
    if (ttSelect) {
      const root = ttSelect.closest('.ttn-layout') || document;
      root.querySelectorAll('[data-tt-select]').forEach((button) => button.classList.toggle('is-active', button === ttSelect));
      root.querySelectorAll('[data-tt-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.ttPanel !== ttSelect.dataset.ttSelect;
      });
      return true;
    }
    const reportImage = event.target.closest('[data-sx-report-image]');
    if (reportImage) {
      const button = reportImage;
      button.disabled = true;
      button.textContent = '导出中…';
      api('studio/workspace/reports/screenshot', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path:location.hash.slice(1)}),
      }).then((result) => {
        const link = document.createElement('a');
        link.href = result.url;
        link.download = '训练课报告.png';
        link.rel = 'noopener';
        link.click();
        button.textContent = '已导出';
        setTimeout(() => { button.disabled = false; button.textContent = '导出图片'; }, 1400);
      }).catch((error) => {
        button.disabled = false;
        button.textContent = '导出图片';
        window.alert(error.message);
      });
      return true;
    }
    if (event.target.closest('[data-sx-print]')) { window.print(); return true; }
    const weekGo = event.target.closest('[data-sx-week-go]');
    if (weekGo) {
      const value = document.querySelector('[data-sx-week-start]')?.value;
      if (value) location.hash = '#weekly/' + value;
      return true;
    }
    const goalTemplate = event.target.closest('[data-sx-goal-template]');
    if (goalTemplate) {
      const form = goalTemplate.closest('form');
      const goal = goalTemplate.dataset.sxGoalTemplate || '';
      const row = [...(form?.querySelectorAll('.sx-goal-edit') || [])]
        .find((item) => !item.querySelector('[name="goalLabel"]')?.value.trim());
      const input = row?.querySelector('[name="goalLabel"]');
      if (input && goal) {
        input.value = goal;
        input.focus();
      }
      return true;
    }
    const openLinks = event.target.closest('[data-sx-link-matches]');
    if (openLinks) {
      const dialog = document.querySelector('#sx-link-dialog');
      if (dialog && !dialog.open) dialog.showModal();
      return true;
    }
    const resetLinks = event.target.closest('[data-sx-link-reset]');
    if (resetLinks) {
      const dialog = resetLinks.closest('dialog');
      resetLinks.disabled = true;
      api('studio/workspace/sessions/' + encodeURIComponent(dialog?.querySelector('[name="id"]')?.value || '') + '/links', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({matchKeys:[]}),
      }).then(() => { dialog?.close(); reload(); }).catch((error) => {
        const status = dialog?.querySelector('.form-status');
        if (status) status.textContent = error.message;
        resetLinks.disabled = false;
      });
      return true;
    }
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
          if (status) status.textContent = `已迁移 ${result.imported || 0} 名${result.placeholders ? `（其中 ${result.placeholders} 名占位）` : ''}，跳过 ${result.skipped || 0} 名。`;
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
    /* ── 身份对照：筛 / 展开 / 命名 / 解绑 / 删选手 ───────────────────── */
    const idChipButton = event.target.closest('[data-sx-id-chip]');
    if (idChipButton) {
      const root = idChipButton.closest('.section');
      if (root) {
        root.dataset.sxIdFilter = idChipButton.dataset.sxIdChip;
        root.dataset.sxIdExpanded = '0';
        root.querySelectorAll('[data-sx-id-chip]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip === idChipButton)));
        syncIdentityRows(root);
      }
      return true;
    }
    if (event.target.closest('[data-sx-id-more]')) {
      const root = event.target.closest('.section');
      if (root) {
        root.dataset.sxIdExpanded = root.dataset.sxIdExpanded === '1' ? '0' : '1';
        syncIdentityRows(root);
      }
      return true;
    }
    const identityOpen = event.target.closest('[data-sx-id-open]');
    if (identityOpen) {
      openIdentityDialog({
        accountId: identityOpen.dataset.sxIdOpen,
        nickname: identityOpen.dataset.idNickname,
        name: identityOpen.dataset.idName,
        position: identityOpen.dataset.idPosition,
        positions: (identityOpen.dataset.idPositions || '').split(',').filter(Boolean),
        teamId: identityOpen.dataset.idTeam,
        teamName: identityOpen.dataset.idTeamname,
        games: identityOpen.dataset.idGames,
        playerId: identityOpen.dataset.idPlayer,
      });
      return true;
    }
    const identityUnmap = event.target.closest('[data-sx-id-unmap]');
    if (identityUnmap) {
      const label = identityUnmap.dataset.idNickname || identityUnmap.dataset.sxIdUnmap;
      if (!window.confirm(`把「${label}」从这名选手身上解绑？选手与战队记录都保留，这个游戏ID回到「待命名」。`)) return true;
      identityUnmap.disabled = true;
      api('v3/identity/accounts/unmap', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({accountId: identityUnmap.dataset.sxIdUnmap})})
        .then(() => reload())
        .catch((error) => { window.alert(error.message); identityUnmap.disabled = false; });
      return true;
    }
    const identityDelete = event.target.closest('[data-sx-id-delete]');
    if (identityDelete) {
      const name = identityDelete.dataset.idName || '这名选手';
      if (!window.confirm(`删除「${name}」？会连他的游戏ID映射一起删掉，那些游戏ID回到「待命名」；历史对局不改。`)) return true;
      identityDelete.disabled = true;
      api('v3/identity/players/delete', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({playerId: identityDelete.dataset.sxIdDelete})})
        .then(() => reload())
        .catch((error) => { window.alert(error.message); identityDelete.disabled = false; });
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
    if ((event.target.closest('[data-pl-pick]') || event.target.closest('[data-pl-name]') || event.target.closest('[data-pl-goto]')
      || event.target.closest('[data-pa-page]') || event.target.closest('[data-pa-view]') || event.target.closest('[data-pa-export]')
      || event.target.closest('[data-pa-compare]') || event.target.closest('[data-pa-goto]')
      || event.target.closest('[data-pa-check]') || event.target.closest('[data-pa-compare-picked]')
      || event.target.closest('[data-pl-pick-b]') || event.target.closest('[data-pl-swap]') || event.target.closest('[data-pl-recent]')
      || event.target.closest('[data-pa-drawer]')
      || event.target.closest('[data-pa-claim]') || event.target.closest('[data-pa-filter-claim]') || event.target.closest('[data-pa-add-player]')
      || event.target.closest('[data-pa-mode]') || event.target.closest('[data-pa-side]') || event.target.closest('[data-pa-unmap]')
      || event.target.closest('[data-pa-id-edit]') || event.target.closest('[data-pa-id-leave]') || event.target.closest('[data-pa-id-delete]')
      || event.target.closest('[data-pd-window]')
      || event.target.closest('a[href^="#playerdetail/"]'))
      && playerPages.click(event)) return true;
    const tmJump = event.target.closest('[data-tm-jump]');
    if (tmJump) {
      const target = document.getElementById(tmJump.dataset.tmJump);
      if (target && !target.classList.contains('is-open') && target.id !== 'tp-overview') {
        target.classList.add('is-open');
        const toggle = target.querySelector('[data-tp-toggle]');
        if (toggle) { toggle.setAttribute('aria-expanded', 'true'); toggle.textContent = '收起'; }
      }
      target?.scrollIntoView({behavior: 'smooth', block: 'start'});
      return true;
    }
    const tpToggle = event.target.closest('[data-tp-toggle]');
    if (tpToggle) {
      const section = tpToggle.closest('.tp-sec');
      if (section) {
        const open = !section.classList.contains('is-open');
        section.classList.toggle('is-open', open);
        tpToggle.setAttribute('aria-expanded', String(open));
        tpToggle.textContent = open ? '收起' : '展开';
      }
      return true;
    }
    const tpCopy = event.target.closest('[data-tp-copy]');
    if (tpCopy) {
      const text = tpCopy.dataset.tpSummary || '';
      const label = tpCopy.textContent;
      let settled = false;
      const mark = (value) => {
        if (settled) return;
        settled = true;
        tpCopy.textContent = value;
        window.setTimeout(() => { tpCopy.textContent = label; }, 1600);
      };
      const fallback = () => {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        let copied = false;
        try { copied = document.execCommand('copy'); } catch { copied = false; }
        area.remove();
        if (copied) { mark('已复制'); return; }
        const dialog = document.createElement('dialog');
        dialog.className = 'tp-copy-dialog';
        dialog.innerHTML = '<form method="dialog"><h2>复制摘要</h2><p>浏览器没有给剪贴板权限，文本已全选，按 Ctrl+C 即可。</p><textarea readonly></textarea><div class="tp-copy-actions"><button type="button" data-copy-all>重新全选</button><button value="close">关闭</button></div></form>';
        dialog.querySelector('textarea').value = text;
        document.body.appendChild(dialog);
        const selectAll = () => { const ta = dialog.querySelector('textarea'); ta.focus(); ta.select(); };
        dialog.querySelector('[data-copy-all]').addEventListener('click', selectAll);
        dialog.addEventListener('close', () => dialog.remove());
        dialog.showModal();
        selectAll();
      };
      const timer = window.setTimeout(fallback, 900);
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text)
          .then(() => { window.clearTimeout(timer); mark('已复制'); })
          .catch(() => { window.clearTimeout(timer); fallback(); });
      } else {
        window.clearTimeout(timer);
        fallback();
      }
      return true;
    }
    const tmMatchup = event.target.closest('[data-tm-matchup]');
    if (tmMatchup) {
      const root = tmMatchup.closest('.tm-matchup-panel');
      if (root) {
        root.querySelectorAll('[data-tm-matchup]').forEach((button) => button.setAttribute('aria-pressed', String(button === tmMatchup)));
        root.querySelectorAll('[data-tm-matchup-panel]').forEach((panel) => { panel.hidden = panel.dataset.tmMatchupPanel !== tmMatchup.dataset.tmMatchup; });
      }
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
    const tdChip = event.target.closest('[data-td-chip]');
    if (tdChip) {
      const root = tdChip.closest('.td-page');
      if (root) {
        const group = tdChip.dataset.tdChip;
        const stateKey = TD_STATE_KEYS[group];
        if (stateKey) {
          root.dataset[stateKey] = tdChip.dataset.tdValue || 'all';
          syncTdChips(root, group);
        }
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
    const rosterToggle = event.target.closest('[data-team-roster-toggle]');
    if (rosterToggle) {
      const list = rosterToggle.parentElement?.querySelector('.tm-roster-list');
      if (list) {
        const open = rosterToggle.getAttribute('aria-expanded') === 'true';
        rosterToggle.setAttribute('aria-expanded', String(!open));
        list.hidden = open;
        const hint = rosterToggle.querySelector('em');
        if (hint) hint.textContent = open ? '展开 ▾' : '收起 ▴';
      }
      return true;
    }
    const renameBtn = event.target.closest('[data-team-rename]');
    if (renameBtn) {
      const label = renameBtn.dataset.teamLabel || '';
      const name = window.prompt('给这支对手战队命名 / 改名（全部对局页会一起更新）', label);
      if (name === null || !name.trim()) return true;
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
    if(event.target.closest('[data-review-action]')){reviewPage.click(event);return true;} if(event.target.closest('[data-source-action]')){sourcePages.click(event);return true;} if(event.target.closest('[data-capture-action]')||event.target.closest('[data-capture-form]')||event.target.closest('[data-chan-expand]')||event.target.closest('[data-chan-open]')){captureIngestPage.click(event);return true;} const b=event.target.closest('[data-feature-action]');if(!b)return false;if(b.dataset.featureAction==='import-commit'){b.disabled=true;const status=b.parentElement.querySelector('[data-import-commit-status]');status.textContent='正在导入…';api('v3/import/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({previewId:b.dataset.previewId,strict:true})}).then(result=>{status.textContent=`导入完成：${result.sheets.length} 个工作表。可在数据范围中启用表格来源。`;b.textContent='已导入'}).catch(error=>{status.textContent=error.message;b.disabled=false});return true;}if(b.dataset.featureAction==='migrate'){b.disabled=true;api('v3/workspace/migration',{method:'POST'}).then(()=>reload()).catch(error=>{b.disabled=false;b.parentElement.querySelector('.migration-status').textContent=error.message});return true}if(b.dataset.featureAction==='prefill'){b.disabled=true;api('studio/workspace/prefill/run',{method:'POST'}).then(()=>reload()).catch(error=>{b.disabled=false;b.textContent=error.message})}return true; }
  window.addEventListener('scroll', syncTeamSticky, {passive: true});
  window.addEventListener('resize', syncTeamSticky);
  document.addEventListener('keydown', (event) => {
    const search = event.target.closest?.('[data-team-search]');
    if (search && event.key === 'Escape') {
      if (!search.value) return;
      event.preventDefault();
      clearTeamSearch(search);
      return;
    }
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    if (document.querySelector('.mf-pop, dialog[open]')) return;
    const box = document.querySelector('[data-team-search]');
    if (!box || !document.querySelector('.tm-grid')) return;
    event.preventDefault();
    box.focus();
  });
  return {has:name=>Object.hasOwn(endpoints,name)||['ingest','shots','videos','replays','review'].includes(name),load:(name,key,signal)=>name==='ingest'?captureIngestPage.load(name,key,signal):name==='capture'?sourcePages.load(name,key,signal):'review'===name?reviewPage.load(name,key,signal):['shots','videos','replays'].includes(name)?sourcePages.load(name,key,signal):Promise.all((name==='report'?[...endpoints[name],'v3/research/reports/'+encodeURIComponent(key)]:name==='hero'?[...endpoints[name],'studio/camp-partners?hero='+encodeURIComponent(key),'matches','v3/facts/lane_matchup','v3/hero-detail/'+encodeURIComponent(key)]:name==='playerdetail'?[...endpoints[name],'v3/player-detail?player='+encodeURIComponent(key)]:name==='session'?['studio/workspace/sessions/'+encodeURIComponent(key)]:name==='competition'?['studio/workspace/competitions/'+encodeURIComponent(key),'v3/players-board']:name==='team'?[...endpoints[name],'studio/camp-compare?team='+encodeURIComponent(key),'v3/team-bp','v3/team-deep?team='+encodeURIComponent(key),'v3/team-behavior']:endpoints[name]).map(p=>name==='team'&&String(p).startsWith('v3/team-deep')?api(p,{signal}).catch(()=>null):api(p==='matches'||p==='tempo'||p==='v3/identity'?p+currentQuery():p,{signal}))).then(data=>name==='weekly'?Promise.all([...data,api('studio/workspace/metrics/week?start='+encodeURIComponent(key||''),{signal})]):data),render:(name,data,key)=>renders[name](data,key),submit,click,change,afterRender:()=>{updatePairs();updateAnchorNav();const tmJumpButtons=[...document.querySelectorAll('.tm-jump [data-tm-jump]')];if(tmJumpButtons.length){const tmBasicButton=tmJumpButtons.find(b=>b.dataset.tmJump==='tm-basic');const tmGroups=[{button:tmBasicButton,target:document.getElementById('tm-score')},...tmJumpButtons.filter(b=>b.dataset.tmJump!=='tm-basic').map(b=>({button:b,target:document.getElementById(b.dataset.tmJump)}))].filter(g=>g.button&&g.target);if(tmGroups.length){if(window.__tmJumpScroll)window.removeEventListener('scroll',window.__tmJumpScroll);window.__tmJumpScroll=()=>{let active=tmGroups[0];for(const group of tmGroups){if(group.target.getBoundingClientRect().top<=180)active=group;}if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-4)active=tmGroups[tmGroups.length-1];tmJumpButtons.forEach(b=>b.setAttribute('aria-current',String(b===active.button)));};window.addEventListener('scroll',window.__tmJumpScroll,{passive:true});window.__tmJumpScroll();}}const teamRoot=document.querySelector('[data-tm-directory]');if(teamRoot){syncTeamList(teamRoot);syncTeamSticky();}const tpSecs=[...document.querySelectorAll('.tp-page .tp-sec')];if(tpSecs.length){if(window.__tmJumpScroll)window.removeEventListener('scroll',window.__tmJumpScroll);const tpButtons=[...document.querySelectorAll('.tp-jump [data-tm-jump], .tp-bottom-nav [data-tm-jump]')];if(tpButtons.length&&'IntersectionObserver'in window){window.__tpSecObserver?.disconnect();const observer=new IntersectionObserver((entries)=>{const visible=entries.filter((e)=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;tpButtons.forEach((b)=>b.setAttribute('aria-current',String(b.dataset.tmJump===visible.target.id)));},{rootMargin:'-90px 0px -55% 0px',threshold:[0,.15,.5,.8]});tpSecs.forEach((sec)=>observer.observe(sec));window.__tpSecObserver=observer;}}captureIngestPage.afterRender();sourcePages.afterRender();reviewPage.afterRender();bindSxDialogs();const setupRoot=document.querySelector('[data-sx-anchor="teams"]');if(setupRoot)syncSetupTeams(setupRoot);const ownRoot=document.querySelector('[data-sx-scope="ownership"]');if(ownRoot)syncOwnershipGroups(ownRoot);const pendingRoot=document.querySelector('[data-sx-scope="pending"]');if(pendingRoot)syncPendingQueue(pendingRoot)}};
}
