import { equipIcons } from './equipment-icons.js';
import { createResearch } from './research.js';
import { createCapture } from './capture-page.js';
import { createSources } from './sources-page.js';
import { createReview } from './review-page.js';
import { createPlayers } from './players-page.js';
import { createHeroCompare } from './hero-compare.js';
import { createCoachBoard } from './coach-viz.js';
import { createPlayerCompare } from './player-compare.js';
import { createTeamDossier } from './team-dossier.js?v=dossier-20261118a';

/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
/* 页签清单挪到 feature-sections.js：外壳只要这几行，不该为它 import 整个 features.js。 */
import { featureSections } from './feature-sections.js';
export { featureSections };

export function createFeatures(h) {
  const {esc, fmt, pct, diff, time, portrait, route, table, pageIntro, reload, currentQuery, icon, microChart, gameAnchorBar} = h;
  const heroCompare = createHeroCompare({esc, portrait});
  const coachBoard = createCoachBoard({esc});
  const playerCompare = createPlayerCompare({esc, portrait});
  const research = createResearch({esc,fmt,table,icon,pageIntro});
  /* 战队详情：v4 整页重做在 team-dossier.js，外壳只传工具函数与路由。 */
  const teamDossier = createTeamDossier({esc, fmt, pct, time, portrait, route});
  const endpoints = {
    teams:['studio/teams'], team:['studio/teams'], teamtraining:['v3/team-training'],
    capture:['sources'], playerarchive:['v3/players-board','v3/identity/players'], ownership:['studio/opponents'], coach:['v3/bp-board','studio/coach'], playercompare:['v3/players-board'], playerdetail:['v3/players-board'], heroes:['studio/camp-compare'], hero:['studio/camp-compare'], herocompare:['studio/camp-compare'], featured:['matches','tempo'],
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
  /* 采集页：一个页面装下营地同步 / 截图 / 录屏 / 回放 / 审查，见 capture-page.js。
     素材页与审查页在下面创建，用 getter 晚绑定，避免初始化顺序问题。 */
  const captureIngestPage = createCapture({esc, fmt, table, block, stats, empty, withPage, icon,
    sources: () => sourcePages, review: () => reviewPage});
  /* 截图 / 录屏 / 回放三个素材页，见 sources-page.js */
  const sourcePages = createSources({esc, fmt, block, stats, empty, withPage, icon, table});
  /* 逐项校对，见 review-page.js */
  const reviewPage = createReview({esc, fmt, block, stats, empty, withPage, icon});
  /* 选手板块两页：选手档案（含认领命名、分路筛选） / 选手对比 */
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
    const fallback = {q: '', status: '', sort: 'recent', team: ''};
    const normalizeSort = (value) => TEAM_SORTS.includes(value) ? value : 'recent';
    const normalizeStatus = (value) => value === 'named' || value === 'pending' ? value : '';
    const normalizeTeam = (value) => typeof value === 'string' ? value : '';
    try {
      const params = new URLSearchParams(location.hash.split('?')[1] || '');
      if (params.has('q') || params.has('status') || params.has('sort') || params.has('team')) {
        return {
          q: params.get('q') || '',
          status: normalizeStatus(params.get('status')),
          sort: normalizeSort(params.get('sort') || ''),
          team: normalizeTeam(params.get('team')),
        };
      }
      const saved = JSON.parse(localStorage.getItem(TEAM_VIEW_STORAGE) || 'null');
      if (saved && typeof saved === 'object') {
        return {q: String(saved.q || ''), status: normalizeStatus(saved.status), sort: normalizeSort(saved.sort), team: normalizeTeam(saved.team)};
      }
    } catch {}
    return fallback;
  };
  /* 搜索、命名状态、排序和「正在看哪一支」都写回 URL 与本机记忆：
     改名或刷新后不会被弹回第一支，也能把当前对手的链接直接发给别人。 */
  const writeTeamViewState = (state) => {
    const q = String(state.q || '');
    const status = state.status === 'named' || state.status === 'pending' ? state.status : '';
    const sort = TEAM_SORTS.includes(state.sort) ? state.sort : 'recent';
    const team = typeof state.team === 'string' ? state.team : '';
    try {
      if (q || status || sort !== 'recent' || team) localStorage.setItem(TEAM_VIEW_STORAGE, JSON.stringify({q, status, sort, team}));
      else localStorage.removeItem(TEAM_VIEW_STORAGE);
    } catch {}
    try {
      const path = location.hash.slice(1).split('?')[0];
      const params = new URLSearchParams(location.hash.split('?')[1] || '');
      if (q) params.set('q', q); else params.delete('q');
      if (status) params.set('status', status); else params.delete('status');
      if (sort !== 'recent') params.set('sort', sort); else params.delete('sort');
      if (team) params.set('team', team); else params.delete('team');
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
  /* ── 战队：对手情报台（2026-11-16 重做）─────────────────────────────
     数据来自营地终局面板（studio/teams）。版式换成「左索引 / 右档案」：
     左边是一条可搜索、可排序的对手索引，右边只讲当前选中的那一支。
     一屏只服务一支对手，字号才能从 10-11px 提到 13-16px、数字放到 38-42px，
     也不用把 4 支队硬塞进 3 列小卡（旧版最后一张永远是孤儿卡）。
     仍然不合成综合得分：单局样本撑不起强弱关系，只给交手、推塔、近况。 */
  const tbPad = (n) => String(n).padStart(2, '0');
  const tbDays = (first, last) => {
    const day = (value) => {
      const hit = /^(\d{1,2})-(\d{1,2})/.exec(String(value || ''));
      return hit ? new Date(2000, Number(hit[1]) - 1, Number(hit[2])).getTime() : null;
    };
    const a = day(first), b = day(last);
    if (a == null || b == null) return null;
    return Math.max(1, Math.round((b - a) / 86400000) + 1);
  };
  /* 索引行：编号、队名、最近交手、本队胜率。整行是 button，点一下换右边档案。 */
  const tbItem = (t, index, selectedId) => {
    const pending = t.named ? '' : '待命名 · ';
    const last = t.lastSeen || '还没交过手';
    return `<button type="button" class="tb-item" data-team-row data-team-select="${esc(t.id)}" data-team-id="${esc(t.id)}"
      data-team-name="${esc([t.displayName, t.name, t.coach, ...(t.currentPlayers || []).map((x) => `${x.name || ''} ${x.id || ''}`)].filter(Boolean).join(' ').toLowerCase())}"
      data-team-named="${t.named ? '1' : '0'}" data-team-games="${t.matches || 0}" data-team-rate="${t.winRate ?? ''}"
      data-team-last="${esc(t.lastSeen || '')}" aria-pressed="${t.id === selectedId ? 'true' : 'false'}" aria-controls="tb-panel-${esc(t.id)}">
      <span class="tb-item-no" data-team-no aria-hidden="true">${tbPad(index + 1)}</span>
      <span class="tb-item-main"><b title="${esc(t.displayName)}">${text(t.displayName)}</b><small>${esc(pending)}${text(last)} · ${fmt(t.matches || 0)} 局</small></span>
      <span class="tb-item-rate"><b><em>本队</em>${pct(t.winRate)}</b></span>
    </button>`;
  };
  /* 档案：头部身份 → 四个读数 → 一句话结论 → 当前五人 / 最近交手。
     数字一律从本队视角说（本队胜率、本队几胜几负），对手胜率放在注里。 */
  const tbDossier = (t, own, selectedId) => {
    const m = t.metrics || {};
    const ownM = (own && own.metrics) || {};
    const games = [...(t.games || [])].sort((a, b) => String(b.start || '').localeCompare(String(a.start || '')));
    const recent = games.slice(0, 5);
    const recentWins = recent.filter((g) => g.win === true).length;
    const recentLosses = recent.filter((g) => g.win === false).length;
    const decided = (t.wins || 0) + (t.losses || 0);
    const ownRate = decided ? (t.wins || 0) / decided * 100 : null;
    const oppRate = tmOppRate(t);
    const roster = byLaneTm(t.currentPlayers || t.players || []).slice(0, 5);
    const filled = roster.filter((pl) => pl.name).length;
    const last = recent[0];
    const thin = (t.matches || 0) < 3;
    const rateGap = hasNum(ownRate) && hasNum(own?.winRate) ? ownRate - own.winRate : null;
    const towerGap = hasNum(m.towerPerGame) && hasNum(ownM.towerPerGame) ? m.towerPerGame - ownM.towerPerGame : null;
    const chips = [
      t.named ? '<span class="tb-chip is-named">已建档</span>' : '<span class="tb-chip is-warn">待命名</span>',
      t.coach ? `<span class="tb-chip">教练 ${esc(t.coach)}</span>` : '',
      thin ? '<span class="tb-chip is-warn">样本少</span>' : '',
    ].join('');
    const meta = [
      t.lastSeen ? `最近 ${text(t.lastSeen)}` : '',
      last && typeof last.win === 'boolean' ? `上一场 ${last.win ? '本队胜' : '本队负'}` : '',
      t.firstSeen ? `首次 ${text(t.firstSeen)}` : '',
    ].filter(Boolean).map((item) => `<span>${item}</span>`).join('');
    const form = recent.length
      ? `<div class="tb-form5"><small>近 ${recent.length} 局</small><ul>${recent.map((g) => {
        const cls = g.win === true ? 'is-win' : g.win === false ? 'is-loss' : '';
        const label = g.win === true ? '胜' : g.win === false ? '负' : '—';
        const tip = `${g.start || '时间未知'} ${g.win === true ? '本队胜' : g.win === false ? '本队负' : '结果未知'}`;
        return `<li class="${cls}" title="${esc(tip)}">${label}</li>`;
      }).join('')}</ul></div>`
      : '';
    const split = hasNum(ownRate)
      ? `<div class="tb-split" role="img" aria-label="本队 ${fmt(t.wins)} 胜 ${fmt(t.losses)} 负"><i class="is-win" style="width:${ownRate.toFixed(1)}%"></i><i class="is-loss" style="width:${(100 - ownRate).toFixed(1)}%"></i></div>`
      : '';
    const figs = `<div class="tb-figs">
      <div class="tb-fig">
        <span class="tb-fig-label">本队胜率</span>
        <strong>${pct(ownRate)}</strong>${split}
        <small>${fmt(t.wins)} 胜 ${fmt(t.losses)} 负 · 对手 ${pct(oppRate)}</small>
      </div>
      <div class="tb-fig">
        <span class="tb-fig-label">交手局数</span>
        <strong>${fmt(t.matches || 0)}<em>局</em></strong>
        <small>${t.firstSeen ? `${text(t.firstSeen)} → ${text(t.lastSeen)}` : '首次交手时间未知'}</small>
      </div>
      <div class="tb-fig">
        <span class="tb-fig-label">对手场均推塔</span>
        <strong>${fmt(m.towerPerGame, 1)}</strong>
        <small>本队 ${fmt(ownM.towerPerGame, 1)}${towerGap == null || Math.abs(towerGap) < 0.05 ? '' : ` · ${towerGap > 0 ? '落后' : '领先'} ${fmt(Math.abs(towerGap), 1)}`}</small>
      </div>
      <div class="tb-fig">
        <span class="tb-fig-label">最近 ${recent.length || 0} 局</span>
        <strong>${fmt(recentWins)}<em>胜</em> ${fmt(recentLosses)}<em>负</em></strong>
        <small>${last ? `上一场 ${text(last.start)} · ${last.win === true ? '本队胜' : last.win === false ? '本队负' : '结果未知'}` : '还没有交过手'}</small>
      </div>
    </div>`;
    const read = [];
    if (hasNum(ownRate)) {
      const cmp = !hasNum(own?.winRate) ? ''
        : Math.abs(rateGap) < 0.5 ? `，与全队整体（${pct(own.winRate)}）基本持平`
          : `，比全队整体（${pct(own.winRate)}）${rateGap > 0 ? '高' : '低'} <b>${fmt(Math.abs(rateGap), 1)}</b> 个百分点`;
      read.push(`对 ${text(t.displayName)} 交手 <b>${fmt(t.matches || 0)}</b> 局，本队 <b>${fmt(t.wins)} 胜 ${fmt(t.losses)} 负</b>，胜率 <b>${pct(ownRate)}</b>${cmp}`);
    } else {
      read.push(`对 ${text(t.displayName)} 还没有可用的交手记录`);
    }
    if (towerGap != null && Math.abs(towerGap) >= 0.05) {
      read.push(`对手场均推塔 <b>${fmt(m.towerPerGame, 1)}</b>、本队 <b>${fmt(ownM.towerPerGame, 1)}</b>，本队${towerGap > 0 ? '落后' : '领先'} <b>${fmt(Math.abs(towerGap), 1)}</b>`);
    }
    if (recent.length) read.push(`最近 ${recent.length} 局 <b>${recentWins} 胜 ${recentLosses} 负</b>`);
    const rosterRows = roster.length
      ? TM_LANES.map((lane) => {
        const pl = roster.find((item) => (item.lane || '') === lane);
        if (!pl) return `<li class="is-missing"><span class="tb-lane">${esc(lane)}</span><b>待补</b><small>—</small></li>`;
        const tip = `${pl.name || '待补'} · ${lane} · ${fmt(pl.games || 0)} 局`;
        /* 对面这个 ID 是谁？点名字直接进选手页，不用回选手档案里再搜一遍。
           选手页以「营地游戏名」为键，而不是面板里的数字 ID。 */
        const name = pl.name
          ? `<a class="tb-player" href="${route('playerdetail', pl.name)}" title="${esc(`${tip} · 打开选手页`)}">${text(pl.name)}</a>`
          : '<b>待补</b>';
        return `<li><span class="tb-lane">${esc(lane)}</span>${name}<small>${fmt(pl.games || 0)} 局</small></li>`;
      }).join('')
      : '<li class="is-empty">最近 5 局还没有识别到这套五人。</li>';
    const former = (t.formerPlayers || []).length
      ? `<p class="tb-note">另有 ${fmt((t.formerPlayers || []).length)} 人曾出战，见完整档案「曾效力」。</p>` : '';
    const gameRows = recent.length
      ? recent.map((g) => {
        const state = g.win === true ? ['is-win', '本队胜'] : g.win === false ? ['is-loss', '本队负'] : ['', '未知'];
        return `<li data-team-game data-team-game-team="${esc(t.id)}" data-team-game-start="${esc(g.start || '')}" data-team-game-duration="${hasNum(g.duration) ? g.duration : ''}"><time>${text(g.start || '时间未知')}</time><span class="tb-res ${state[0]}">${state[1]}</span><span class="tb-map">${text(g.map || '')}</span><small>${hasNum(g.duration) ? time(g.duration) : '—'}</small></li>`;
      }).join('')
      : '<li class="is-empty">还没有交手记录。</li>';
    return `<article class="tb-dossier" id="tb-panel-${esc(t.id)}" data-team-panel="${esc(t.id)}"${t.id === selectedId ? '' : ' hidden'} aria-label="${esc(t.displayName)} 对手档案">
      <header class="tb-dhead">
        <span class="tb-crest" aria-hidden="true">${esc((t.displayName || '?').slice(0, 1))}</span>
        <div class="tb-id">
          <div class="tb-id-top"><h2>${text(t.displayName)}</h2>${chips}</div>
          <p class="tb-meta">${meta}</p>
        </div>
        <div class="tb-dhead-side">${form}
          <div class="tb-actions">
            <a class="tb-cta" href="${route('team', t.id)}">完整档案 <span aria-hidden="true">→</span></a>
            <button type="button" class="tb-ghost" data-team-rename="${esc(t.id)}" data-team-label="${esc(t.displayName)}">${t.named ? '改名' : '命名'}</button>
          </div>
        </div>
      </header>
      ${figs}
      <p class="tb-read"><span class="tb-read-tag">读数</span><span class="tb-read-text">${read.join('；')}。</span></p>
      <div class="tb-cols">
        <section class="tb-col">
          <div class="tb-col-head"><h3>当前五人</h3><span>${filled}/5 已识别</span></div>
          <ul class="tb-roster">${rosterRows}</ul>${former}
        </section>
        <section class="tb-col">
          <div class="tb-col-head"><h3>最近交手</h3><span data-team-game-count>${recent.length} 局</span></div>
          <ul class="tb-games">${gameRows}</ul>
        </section>
      </div>
    </article>`;
  };
  const clearTeamSearch = (input) => {
    if (!input) return;
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  };
  /* 列表前端视图控制：搜索（队名 / 选手 ID）+ 命名状态 + 排序 + 选中。
     筛掉或重排后，若当前选中的那支不再可见，就自动落到第一条可见的对手。 */
  function selectTeam(root, id) {
    if (!root) return;
    root.dataset.teamSelected = id || '';
    root.querySelectorAll('[data-team-row]').forEach((item) => item.setAttribute('aria-pressed', String(item.dataset.teamId === id)));
    root.querySelectorAll('[data-team-panel]').forEach((panel) => { panel.hidden = panel.dataset.teamPanel !== id; });
    const emptyPanel = root.querySelector('[data-team-empty-panel]');
    if (emptyPanel) emptyPanel.hidden = Boolean(id);
    /* 选中项跟着 URL 走：改名触发重渲染、或者刷新页面，都还停在这支对手上。 */
    writeTeamViewState({
      q: (root.querySelector('[data-team-search]')?.value || '').trim(),
      status: root.dataset.teamFilter === '1' ? 'named' : root.dataset.teamFilter === '0' ? 'pending' : '',
      sort: root.querySelector('[data-team-sort]')?.value || 'recent',
      team: id || '',
    });
  }
  /* 对比模式：最多选两支，右栏并排；不写 URL，退出时回到最后点的那支。 */
  function renderTeamCompare(root) {
    if (!root) return;
    const on = root.dataset.teamCompare === '1';
    const picks = (root.dataset.teamPicked || '').split(',').filter(Boolean).slice(0, 2);
    const toggle = root.querySelector('[data-team-compare-toggle]');
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(on));
      toggle.textContent = on ? '退出对比' : '对比';
    }
    const detail = root.querySelector('[data-team-detail]');
    if (detail) {
      detail.classList.toggle('is-compare', on);
      detail.dataset.picks = String(picks.length);
    }
    if (!on) return;
    root.querySelectorAll('[data-team-row]').forEach((item) => {
      const picked = picks.includes(item.dataset.teamId);
      item.classList.toggle('is-picked', picked);
      item.setAttribute('aria-pressed', String(picked));
    });
    root.querySelectorAll('[data-team-panel]').forEach((panel) => { panel.hidden = !picks.includes(panel.dataset.teamPanel); });
    const hint = root.querySelector('[data-team-compare-hint]');
    if (hint) hint.hidden = picks.length === 2;
    const empty = root.querySelector('[data-team-empty-panel]');
    if (empty) empty.hidden = true;
  }
  function setTeamCompare(root, on) {
    if (!root) return;
    if (on) {
      root.dataset.teamCompare = '1';
      root.dataset.teamPicked = root.dataset.teamSelected || '';
      renderTeamCompare(root);
      return;
    }
    const picks = (root.dataset.teamPicked || '').split(',').filter(Boolean);
    root.dataset.teamCompare = '0';
    root.dataset.teamPicked = '';
    renderTeamCompare(root);
    selectTeam(root, picks[picks.length - 1] || root.dataset.teamSelected || '');
  }
  function toggleTeamPick(root, id) {
    const picks = (root.dataset.teamPicked || '').split(',').filter(Boolean);
    const index = picks.indexOf(id);
    if (index >= 0) picks.splice(index, 1);
    else {
      if (picks.length >= 2) picks.shift();
      picks.push(id);
    }
    root.dataset.teamPicked = picks.join(',');
    renderTeamCompare(root);
  }
  function syncTeamList(root) {
    if (!root) return;
    const rawQuery = root.querySelector('[data-team-search]')?.value || '';
    const q = rawQuery.trim().toLowerCase();
    const named = root.dataset.teamFilter || '';
    const sort = root.querySelector('[data-team-sort]')?.value || 'recent';
    const list = root.querySelector('[data-team-results]');
    if (!list) return;
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
    const visible = [...list.querySelectorAll('[data-team-row]')].filter((row) => !row.hidden);
    visible.forEach((row, index) => {
      const no = row.querySelector('[data-team-no]');
      if (no) no.textContent = tbPad(index + 1);
    });
    if (root.dataset.teamCompare === '1') {
      /* 对比模式下筛掉的对手要从已选里剔除，别让右栏留着看不见的一支。 */
      const visibleIds = new Set(visible.map((row) => row.dataset.teamId));
      root.dataset.teamPicked = (root.dataset.teamPicked || '').split(',').filter((id) => visibleIds.has(id)).join(',');
      renderTeamCompare(root);
    } else {
      const current = visible.find((row) => row.dataset.teamId === root.dataset.teamSelected) || visible[0];
      selectTeam(root, current ? current.dataset.teamId : '');
    }
    const counter = root.querySelector('[data-team-count]');
    if (counter) counter.textContent = shown === rows.length ? `${fmt(shown)} 支` : `${fmt(shown)} / ${fmt(rows.length)} 支`;
    const hint = root.querySelector('[data-team-empty]');
    if (hint) hint.hidden = shown > 0;
  }
  /* 「最近交手」能不能点开？营地给的是 seq，对局档案用的是 channel-xxxx，
     两个 ID 对不上；这里用「对手战队 + 开赛时间 + 时长」做一次对齐，
     对得上的行才补复盘链接，对不上的保持只读，不硬造入口。 */
  async function linkTeamGames(root) {
    if (!root || root.dataset.gamesLinked === '1') return;
    root.dataset.gamesLinked = '1';
    let payload = null;
    try { payload = await api('matches'); } catch { return; }
    const index = new Map();
    for (const match of payload?.matches || []) {
      if (!match?.key || !match.opponentTeamId) continue;
      index.set(`${match.opponentTeamId}|${match.startTime || ''}|${match.duration ?? ''}`, match.key);
    }
    root.querySelectorAll('[data-team-game]').forEach((row) => {
      if (row.querySelector('.tb-game-hit')) return;
      const key = index.get(`${row.dataset.teamGameTeam}|${row.dataset.teamGameStart}|${row.dataset.teamGameDuration}`);
      if (!key) return;
      const link = document.createElement('a');
      link.className = 'tb-game-hit';
      link.href = '#match/' + encodeURIComponent(key);
      link.title = '查看这局复盘';
      link.setAttribute('aria-label', `查看 ${row.dataset.teamGameStart || ''} 这局的复盘`);
      row.append(link);
      row.classList.add('has-link');
    });
    /* 列头补一句「几局可复盘」，不然链接要悬停才知道。 */
    root.querySelectorAll('[data-team-panel]').forEach((panel) => {
      const label = panel.querySelector('[data-team-game-count]');
      if (!label) return;
      const total = panel.querySelectorAll('[data-team-game]').length;
      const linked = panel.querySelectorAll('.tb-game-hit').length;
      if (linked) label.textContent = `${total} 局 · ${linked} 可复盘`;
    });
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
    const pendingTeams = teams.filter((t) => !t.named);
    const games = teams.reduce((sum, t) => sum + (t.matches || 0), 0);
    const wins = teams.reduce((sum, t) => sum + (t.wins || 0), 0);
    const losses = teams.reduce((sum, t) => sum + (t.losses || 0), 0);
    const thin = teams.filter((t) => (t.matches || 0) < 3).length;
    const latest = [...teams].sort((a, b) => String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')))[0];
    const lastSeen = latest ? String(latest.lastSeen || '') : '';
    const firstSeen = teams.map((t) => String(t.firstSeen || '')).filter(Boolean).sort()[0] || '';
    const spanDays = tbDays(firstSeen, lastSeen);
    const decided = wins + losses;
    const ownRate = decided ? wins / decided * 100 : null;
    const oppRate = decided ? losses / decided * 100 : null;
    const cards = [...teams].sort((a, b) => String(b.lastSeen || '').localeCompare(String(a.lastSeen || ''))
      || String(a.displayName || '').localeCompare(String(b.displayName || ''), 'zh'));
    const viewState = readTeamViewState();
    const statusValue = viewState.status === 'named' ? '1' : viewState.status === 'pending' ? '0' : '';
    /* 上次看的那支还在就继续看它，链接里的 team 失效时退回最近交手的第一支。 */
    const initialTeam = cards.some((t) => t.id === viewState.team) ? viewState.team : (cards[0]?.id || '');
    const sortOptions = [['recent', '最近交手'], ['games', '交手最多'], ['rate', '本队胜率'], ['name', '队名']]
      .map(([option, label]) => `<option value="${option}"${viewState.sort === option ? ' selected' : ''}>${label}</option>`).join('');
    /* 顶部：标题 + 一句话口径 + 五个读数。读数不再做成五张小卡，用分隔线拉通。 */
    const readout = `<div class="tb-readout">
      <div class="tb-readout-cell is-primary"><span>识别对手</span><strong>${fmt(teams.length)}<em>支</em></strong><small>已命名 ${fmt(named)} · 待命名 ${fmt(teams.length - named)}</small></div>
      <div class="tb-readout-cell"><span>交手局数</span><strong>${fmt(games)}<em>局</em></strong><div class="tb-split" role="img" aria-label="本队 ${fmt(wins)} 胜 ${fmt(losses)} 负"><i class="is-win" style="width:${games ? wins / games * 100 : 0}%"></i><i class="is-loss" style="width:${games ? losses / games * 100 : 0}%"></i></div><small>${fmt(wins)} 胜 ${fmt(losses)} 负</small></div>
      <div class="tb-readout-cell"><span>本队胜率</span><strong>${pct(ownRate)}</strong><small>对手 ${pct(oppRate)}</small></div>
      <div class="tb-readout-cell"><span>时间跨度</span><strong>${spanDays ? `${fmt(spanDays)}<em>天</em>` : '—'}</strong><small>${firstSeen && lastSeen ? `${esc(firstSeen.slice(0, 5))} → ${esc(lastSeen.slice(0, 5))}` : '—'}</small></div>
      <div class="tb-readout-cell"><span>样本覆盖</span><strong>${fmt(teams.length - thin)}<em>支</em></strong><small>${thin ? `${fmt(thin)} 支不足 3 局，只作参考` : '全部 ≥3 局，可做队间比较'}</small></div>
    </div>`;
    const hero = `<header class="tb-hero">
      <div class="tb-hero-top">
        <div class="tb-hero-copy">
          <p class="tb-eyebrow">对手情报<span>OPPONENT SCOUT</span></p>
          <h1>战队分析</h1>
          <p class="tb-lede">营地阵容聚类识别对手。左边挑一支，右边看本队与它的交手读数；命名后，对局档案与系列赛一起更新。</p>
        </div>
        <div class="tb-hero-aside">
          <div class="tb-hero-actions">
            <button class="control" data-action="refresh" title="重新读取营地面板">${icon('refresh')} 刷新数据</button>
          </div>
          <p class="tb-hero-note">数据来自营地终局面板，与「对局档案」分开统计；两边局数可能不一致，比较强弱前先看交手局数。</p>
        </div>
      </div>
      ${readout}
    </header>`;
    /* 索引栏：搜索 / 命名状态 / 排序 + 每条对手的最近交手与本队胜率。 */
    const toolbar = `<div class="tb-rail-tools">
      <div class="tb-search">${icon('search')}<input data-team-search value="${esc(viewState.q)}" placeholder="搜队名 / 选手 ID" aria-label="搜索战队" autocomplete="off" spellcheck="false"><kbd class="tb-search-kbd" aria-hidden="true">/</kbd><button type="button" class="tb-search-clear" data-team-search-clear aria-label="清空搜索" title="清空搜索"${viewState.q ? '' : ' hidden'}>${icon('close')}</button></div>
      <div class="tb-rail-row">
        <div class="tb-seg" role="group" aria-label="命名状态">
          <button type="button" class="tb-seg-btn" data-team-chip="" aria-pressed="${statusValue === ''}">全部</button>
          <button type="button" class="tb-seg-btn" data-team-chip="1" aria-pressed="${statusValue === '1'}">已命名</button>
          <button type="button" class="tb-seg-btn" data-team-chip="0" aria-pressed="${statusValue === '0'}">待命名</button>
        </div>
        <label class="tb-sort"><span>排序</span><select data-team-sort aria-label="排序">${sortOptions}</select>${icon('chevron')}</label>
      </div>
    </div>`;
    const board = `<section class="tb-workspace" data-tm-board data-tm-directory data-team-filter="${statusValue}" data-team-selected="${esc(initialTeam)}" aria-label="对手目录">
      <aside class="tb-rail">
        <div class="tb-rail-head">
          <div class="tb-rail-title"><h2>对手索引</h2><small>共 ${fmt(games)} 局交手</small></div>
          <div class="tb-rail-head-actions">
            <span class="tb-rail-count" data-team-count aria-live="polite">${fmt(teams.length)} 支</span>
            <button type="button" class="tb-compare-btn" data-team-compare-toggle aria-pressed="false" title="并排对比两支对手">对比</button>
          </div>
        </div>
        ${toolbar}
        <div class="tb-list" data-team-results>
          ${cards.map((t, index) => tbItem(t, index, initialTeam)).join('')}
          <p class="tb-empty" data-team-empty hidden>没有符合条件的对手。<button type="button" class="tb-empty-reset" data-team-reset>清空筛选</button></p>
          ${teams.length ? '' : empty('当前没有识别到对手战队。')}
        </div>
        <div class="tb-rail-foot">
          <div class="tb-bench">
            <span>本队整体基准</span>
            <b>${pct(ownRate)}</b>
            <small>${fmt(games)} 局 · ${fmt(wins)} 胜 ${fmt(losses)} 负</small>
          </div>
          <p>同一支队被拆成几条？先合并成一条，再去命名。</p>
          <button type="button" class="tb-rail-link" data-tb-maint>合并同一支战队 <span aria-hidden="true">↓</span></button>
          <button type="button" class="tb-rail-link" data-team-bulk>批量命名${pendingTeams.length ? `（${fmt(pendingTeams.length)} 支待命名）` : ''}</button>
        </div>
      </aside>
      <div class="tb-detail" data-team-detail>${cards.map((t, index) => tbDossier(t, value.own, initialTeam)).join('')}
        <div class="tb-detail-empty" data-team-empty-panel${cards.length ? ' hidden' : ''}>
          <b>没有符合条件的对手</b>
          <small>换个关键词，或把命名状态切回「全部」。</small>
          <button type="button" class="tb-empty-reset" data-team-reset>清空筛选</button>
        </div>
        <div class="tb-compare-hint" data-team-compare-hint hidden><b>再选一支对手</b><small>在左边点第二支战队，这里并排显示两边的读数；再点一次可取消。</small></div>
      </div>
    </section>`;
    const suggestions = (value.suggestions || []).map((s) => {
      const changed = s.kind === 'roster-change'
        ? ` · 换出 ${fmt(s.changedFrom || 0)} 人 / 加入 ${fmt(s.changedInto || 0)} 人（阵容更替）` : '';
      return `<li><b>${text(s.fromName || s.from || s.a)}</b> → <b>${text(s.intoName || s.toName || s.into || s.b)}</b><small>共同 ${text(s.overlap || '—')} 人${changed}</small><button type="button" class="tb-mini" data-merge-pick data-merge-from="${esc(s.from || '')}" data-merge-into="${esc(s.into || '')}">选中</button></li>`;
    }).join('');
    const merge = `<details class="tb-maint" id="tb-merge"${suggestions ? ' open' : ''}>
      <summary>
        <span class="tb-maint-copy"><b>先合并同一支战队</b><em>对方换人、转会或离队后可能被认成几支。先并成一支，再去命名；改成相同名字不会自动合并。</em></span>
        <span class="tb-maint-more" aria-hidden="true"></span>
      </summary>
      <div class="tb-maint-body">
        <form class="feature-form tb-merge-form" data-feature-form="merge">
          ${select('来源战队', 'from', options(teams))}
          ${select('合并至', 'into', options(teams))}
          <div class="tb-merge-preview" data-merge-preview><p class="tb-merge-hint">选好来源和「合并至」，这里会先对一下两边的当前五人。</p></div>
          <div class="form-footer"><p class="form-status" role="status"></p><button class="primary" type="submit">合并战队</button></div>
        </form>
        ${suggestions ? `<div class="tb-suggest-wrap"><h3>可能是同一支战队</h3><ul class="tb-suggest">${suggestions}</ul></div>` : ''}
      </div>
    </details>`;
    const renameDialog = `<dialog class="tb-dialog" data-team-rename-dialog closedby="any" aria-labelledby="tb-rename-title">
      <form class="tb-dialog-body" data-feature-form="teamRename" novalidate>
        <header class="tb-dialog-head">
          <h2 id="tb-rename-title">给对手命名</h2>
          <p>队名会同步到对局档案、系列赛和跨局分析；留空不能保存。</p>
        </header>
        <label class="tb-dialog-field"><span>战队名</span><input name="name" maxlength="24" autocomplete="off" spellcheck="false" placeholder="例如：XX 战队" required></label>
        <p class="tb-dialog-error" data-team-rename-error role="alert" hidden></p>
        <footer class="tb-dialog-foot">
          <button type="button" class="tb-ghost" data-dialog-close>取消</button>
          <button type="submit" class="tb-cta" data-team-rename-save>保存</button>
        </footer>
      </form>
    </dialog>`;
    const bulkDialog = `<dialog class="tb-dialog tb-dialog-wide" data-team-bulk-dialog closedby="any" aria-labelledby="tb-bulk-title">
      <form class="tb-dialog-body" data-feature-form="teamBulkRename" novalidate>
        <header class="tb-dialog-head">
          <h2 id="tb-bulk-title">批量命名</h2>
          <p>只列出还没命名的对手。改好的会一次提交，没动过的行自动跳过。</p>
        </header>
        <div class="tb-bulk-list">
          ${pendingTeams.length
            ? pendingTeams.map((t) => `<label class="tb-bulk-row" data-bulk-team="${esc(t.id)}"><span class="tb-bulk-crest" aria-hidden="true">${esc((t.displayName || '?').slice(0, 1))}</span><span class="tb-bulk-id">${text(t.displayName)}</span><input name="name" value="${esc(t.displayName)}" maxlength="24" autocomplete="off" spellcheck="false" aria-label="给 ${esc(t.displayName)} 命名"></label>`).join('')
            : '<p class="tb-bulk-empty">当前没有待命名的对手，全部已建档。</p>'}
        </div>
        <p class="tb-dialog-error" data-team-bulk-error role="alert" hidden></p>
        <footer class="tb-dialog-foot">
          <button type="button" class="tb-ghost" data-dialog-close>取消</button>
          <button type="submit" class="tb-cta"${pendingTeams.length ? '' : ' disabled'}>保存</button>
        </footer>
      </form>
    </dialog>`;
    return `<div class="page feature-page tb-page" data-tm-page>${hero}${board}${merge}${renameDialog}${bulkDialog}</div>`;
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
    /* v4 页面在 team-dossier.js：时间窗 × 赛制、逐手 BP、阵容结构、英雄池与
       条件胜率森林图都在那边，这里只保留路由与数据透传。 */
    return teamDossier.render(value, key, compareData, bpData, deepData, behaviorData);
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
  const renders={ingest:v=>captureIngestPage.render(v),capture:v=>sourcePages.render('capture',v),shots:v=>sourcePages.render('shots',v),videos:v=>sourcePages.render('videos',v),replays:v=>sourcePages.render('replays',v),review:(v,k)=>reviewPage.render(k,v),playerarchive:v=>playerPages.archivePage(v[0],v[1]),reports:v=>research.reports(v[0]),report:v=>research.report(v[1]),hero:(v,k)=>heroDetail(v[0],v[1],v[2],v[3],v[4],k),featured:v=>featuredPage(v[0],v[1]),playercompare:v=>playerCompare.render(v[0]),playerdetail:(v,k)=>playerPages.soloPage(v[0],k,v[1]),herocompare:v=>heroCompare.render(v[0]),teams:(v,k)=>teamsPage(v[0],k),team:(v,k)=>teamsPage(v[0],k,v[1],v[2],v[3],v[4]),teamtraining:v=>teamTraining(v[0]),ownership:v=>ownership(v[0]),coach:v=>coachBoard.render(v[0],v[1]),heroes:v=>heroes(v[0]),combos:v=>combos(v[0]),economy:v=>economy(v[0]),effect:v=>effect(v[0],v[1]),versions:(v)=>versions(v[0],v[1]),setup:v=>setup(...v),pending:v=>pending(v[0],v[1],v[2]),plan:v=>plan(v[0],v[1],v[2],v[3],v[4]),competition:v=>competitionPage(v),session:(v,k)=>sessionPage(v[0],k),weekly:(v,k)=>weeklyReport(v,k)};
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
  /* 目录页的批量命名：只提交真正改过名的行，没动过的跳过。 */
  function submitTeamBulkRename(f) {
    const dialog = f.closest('dialog');
    const error = f.querySelector('[data-team-bulk-error]');
    const button = f.querySelector('button[type=submit]');
    const rows = [...f.querySelectorAll('[data-bulk-team]')];
    const items = rows.map((row) => {
      const id = row.dataset.bulkTeam || '';
      const name = (row.querySelector('input[name="name"]')?.value || '').trim();
      const current = (row.querySelector('.tb-bulk-id')?.textContent || '').trim();
      return id && name && name !== current ? {id, name} : null;
    }).filter(Boolean);
    const fail = (message) => {
      if (error) { error.textContent = message; error.hidden = false; }
      if (button) { button.disabled = false; button.textContent = '保存'; }
    };
    if (!rows.length) { fail('当前没有待命名的对手。'); return true; }
    if (!items.length) { fail('没有改动：至少给一支对手换个名字。'); return true; }
    if (error) { error.hidden = true; error.textContent = ''; }
    if (button) { button.disabled = true; button.textContent = `保存中…（${items.length} 支）`; }
    api('studio/teams/rename-batch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items})})
      .then(() => { dialog?.close(); reload(); })
      .catch((err) => fail(err.message || '保存失败，请重试。'));
    return true;
  }
  /* 目录页的命名对话框：提交到营地战队的改名接口，成功后关窗并重渲染。
     失败的信息留在对话框里，不用系统 alert 打断。 */
  function submitTeamRename(f, payload) {
    const dialog = f.closest('dialog');
    const error = f.querySelector('[data-team-rename-error]');
    const button = f.querySelector('button[type=submit]');
    const name = String(payload.name || '').trim();
    const id = dialog?.dataset.teamId || '';
    const fail = (message) => {
      if (error) { error.textContent = message; error.hidden = false; }
      if (button) { button.disabled = false; button.textContent = '保存'; }
    };
    if (!name) { fail('队名不能为空。'); f.querySelector('input[name="name"]')?.focus(); return true; }
    if (!id) { fail('找不到这支战队，刷新页面后再试。'); return true; }
    if (error) { error.hidden = true; error.textContent = ''; }
    if (button) { button.disabled = true; button.textContent = '保存中…'; }
    api('studio/teams/rename', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id, name})})
      .then(() => { dialog?.close(); reload(); })
      .catch((err) => fail(err.message || '改名失败，请重试。'));
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
    if (id === 'teamRename') return submitTeamRename(f, payload);
    if (id === 'teamBulkRename') return submitTeamBulkRename(f);
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
    /* 战队详情：常驻时间 / 赛制下拉。 */
    if (event.target.matches('[data-tp-select]')) {
      const root = event.target.closest('.tp-page');
      if (root) {
        teamDossier.setFilter(event.target.dataset.tpSelect, event.target.value, root);
        return true;
      }
    }
    /* 战队详情：时间窗自定义起止。日期输入在 .tp-page 内，直接交给页面模块重算。 */
    if (event.target.matches('[data-tp-date]')) {
      const root = event.target.closest('.tp-page');
      if (root) {
        const raw = String(event.target.value || '');
        const hit = /^\d{4}-(\d{2})-(\d{2})$/.exec(raw);
        teamDossier.setFilter(event.target.dataset.tpDate, hit ? `${hit[1]}-${hit[2]}` : '', root);
        return true;
      }
    }
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
      const clear = event.target.closest('.tb-search')?.querySelector('[data-team-search-clear]');
      if (clear) clear.hidden = !event.target.value;
    }
    if(event.target.matches('[data-team-search],[data-team-sort]')) syncTeamList(event.target.closest('[data-tm-board]'));
    if(event.target.matches('[data-ttn-search]')) syncTeamTraining(event.target.closest('.ttn-layout'));
  }
  function copyPlainText(text, button) {
    const label = button.textContent;
    let settled = false;
    const mark = (value) => {
      if (settled) return;
      settled = true;
      button.textContent = value;
      window.setTimeout(() => { if (button.isConnected) button.textContent = label; }, 1600);
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
      mark(copied ? '已复制' : '复制失败');
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => mark('已复制')).catch(fallback);
    } else {
      fallback();
    }
  }

  function click(event) { /* 这三个模块的 click 是 async，返回值是 Promise（恒真），不能直接用来判断是否处理；先用选择器同步判定，再交给它们异步执行。 */
    const tpDrawerClose = event.target.closest('[data-tp-drawer-close]');
    if (tpDrawerClose) {
      teamDossier.closeGames(tpDrawerClose.closest('.tp-page'));
      return true;
    }
    document.querySelectorAll('.tp-page .tp-more[open]').forEach((item) => {
      if (!item.contains(event.target)) item.removeAttribute('open');
    });
    const tpRefresh = event.target.closest('[data-tp-refresh]');
    if (tpRefresh) {
      if (tpRefresh.disabled) return true;
      tpRefresh.disabled = true;
      tpRefresh.classList.add('is-loading');
      const label = tpRefresh.innerHTML;
      tpRefresh.innerHTML = '<span class="tp-refresh-ico" aria-hidden="true">↻</span>刷新中';
      const restore = () => {
        if (!tpRefresh.isConnected) return;
        tpRefresh.disabled = false;
        tpRefresh.classList.remove('is-loading');
        tpRefresh.innerHTML = label;
      };
      window.setTimeout(() => {
        if (!tpRefresh.isConnected) return;
        Promise.resolve().then(() => reload()).catch(() => { restore(); tpRefresh.textContent = '刷新失败'; });
      }, 260);
      window.setTimeout(restore, 12000);
      return true;
    }
    const tpSectionCopy = event.target.closest('[data-tp-section-copy]');
    if (tpSectionCopy) {
      const sec = tpSectionCopy.closest('.tp-sec');
      const page = tpSectionCopy.closest('.tp-page');
      if (sec && page) {
        const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const team = clean(page.querySelector('.tp-id h1')?.innerText);
        const title = clean(sec.querySelector('.tp-sec-title h2')?.innerText);
        const sub = clean(sec.querySelector('.tp-sec-sub')?.innerText);
        const filter = clean(page.querySelector('.tp-filter-head')?.innerText);
        const scope = clean(page.querySelector('.tp-scope-strip')?.innerText);
        const body = String(sec.querySelector('.tp-sec-body')?.innerText || '').trim();
        const note = String(page.querySelector('[data-tp-note]')?.value || '').trim();
        const text = [
          `战队：${team}`,
          `节：${title}`,
          filter ? `筛选：${filter}` : '',
          scope ? `口径：${scope}` : '',
          sub,
          '',
          body,
          note ? `教练笔记：${note}` : '',
        ].filter((line) => line !== '').join('\n');
        copyPlainText(text, tpSectionCopy);
      }
      return true;
    }
    const tpGames = event.target.closest('[data-tp-games]');
    if (tpGames) {
      const root = tpGames.closest('.tp-page');
      if (root) {
        teamDossier.openGames(tpGames.dataset.tpGames, root);
        return true;
      }
    }
    const searchClear = event.target.closest('[data-team-search-clear]');
    if (searchClear) {
      clearTeamSearch(searchClear.closest('.tb-search')?.querySelector('[data-team-search]'));
      return true;
    }
    const searchBox = event.target.closest('.tb-search');
    if (searchBox) {
      searchBox.querySelector('[data-team-search]')?.focus();
      return true;
    }
    const maintJump = event.target.closest('[data-tb-maint]');
    if (maintJump) {
      const panel = document.getElementById('tb-merge');
      if (panel) {
        panel.open = true;
        panel.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
      return true;
    }
    const teamReset = event.target.closest('[data-team-reset]');
    if (teamReset) {
      const root = teamReset.closest('[data-tm-board]');
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
      || event.target.closest('[data-pa-team-more]') || event.target.closest('[data-pa-view]') || event.target.closest('[data-pa-export]')
      || event.target.closest('[data-pa-compare]') || event.target.closest('[data-pa-goto]')
      || event.target.closest('[data-pa-check]') || event.target.closest('[data-pa-compare-picked]')
      || event.target.closest('[data-pl-pick-b]') || event.target.closest('[data-pl-swap]') || event.target.closest('[data-pl-recent]')
      || event.target.closest('[data-pa-drawer]')
      || event.target.closest('[data-pa-claim]') || event.target.closest('[data-pa-filter-claim]') || event.target.closest('[data-pa-add-player]')
      || event.target.closest('[data-pa-mode]') || event.target.closest('[data-pa-side]') || event.target.closest('[data-pa-unmap]')
      || event.target.closest('[data-pa-id-edit]') || event.target.closest('[data-pa-id-leave]') || event.target.closest('[data-pa-id-delete]')
      || event.target.closest('[data-pd-window]')
      || event.target.closest('[data-pa-profile]') || event.target.closest('[data-pa-filter-top]')
      || event.target.closest('[data-pa-filter-profile]')
      || event.target.closest('[data-pdx-set]') || event.target.closest('[data-pdx-toggle]')
      || event.target.closest('[data-pdx-reset]') || event.target.closest('[data-pdx-top]')
      || event.target.closest('[data-pdx-fold]') || event.target.closest('[data-pdx-shot]')
      || event.target.closest('[data-pdx-print]')
      || event.target.closest('a[href^="#playerdetail/"]'))
      && playerPages.click(event)) return true;
    const tpTab = event.target.closest('[data-tp-tab]');
    if (tpTab) {
      const root = tpTab.closest('.tp-page');
      if (root) {
        teamDossier.setSection(tpTab.dataset.tpTab, root);
        return true;
      }
    }
    const tpBump = event.target.closest('[data-tp-bump]');
    if (tpBump) {
      const box = tpBump.closest('.tp-bump');
      if (box) {
        const key = tpBump.dataset.tpBump;
        const focus = box.dataset.focus === key ? '' : key;
        box.dataset.focus = focus;
        box.classList.toggle('has-focus', Boolean(focus));
        box.querySelectorAll('[data-tp-bump]').forEach((el) => {
          const on = Boolean(focus) && el.dataset.tpBump === focus;
          el.classList.toggle('is-focus', on);
          if (el.tagName === 'BUTTON') el.setAttribute('aria-pressed', String(on));
        });
      }
      return true;
    }
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
      const root = teamChip.closest('[data-tm-board]');
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
    /* 战队详情：时间窗 / 赛制筛选，只在已加载的数据上重算，不发新请求。 */
    const tpFilter = event.target.closest('[data-tp-filter]');
    if (tpFilter) {
      const root = tpFilter.closest('.tp-page');
      if (root) teamDossier.setFilter(tpFilter.dataset.tpFilter, tpFilter.dataset.tpValue || 'all', root);
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
    const dialogClose = event.target.closest('[data-dialog-close]');
    if (dialogClose) {
      dialogClose.closest('dialog')?.close();
      return true;
    }
    const dialogBackdrop = event.target.closest('dialog.tb-dialog');
    if (dialogBackdrop && event.target === dialogBackdrop) {
      dialogBackdrop.close();
      return true;
    }
    const compareToggle = event.target.closest('[data-team-compare-toggle]');
    if (compareToggle) {
      const root = compareToggle.closest('[data-tm-board]');
      if (root) setTeamCompare(root, root.dataset.teamCompare !== '1');
      return true;
    }
    const teamBulk = event.target.closest('[data-team-bulk]');
    if (teamBulk) {
      const dialog = document.querySelector('[data-team-bulk-dialog]');
      if (dialog) {
        const error = dialog.querySelector('[data-team-bulk-error]');
        if (error) { error.hidden = true; error.textContent = ''; }
        const save = dialog.querySelector('button[type="submit"]');
        if (save && dialog.querySelectorAll('[data-bulk-team]').length) { save.disabled = false; save.textContent = '保存'; }
        if (!dialog.open) dialog.showModal();
        const first = dialog.querySelector('input[name="name"]');
        if (first) { first.focus(); first.select(); }
      }
      return true;
    }
    const teamSelect = event.target.closest('[data-team-select]');
    if (teamSelect) {
      const root = teamSelect.closest('[data-tm-board]');
      if (root && root.dataset.teamCompare === '1') {
        toggleTeamPick(root, teamSelect.dataset.teamSelect);
        return true;
      }
      selectTeam(root, teamSelect.dataset.teamSelect);
      /* 单列版式下档案在索引下面：换人后滚到档案顶部，别让教练自己找。 */
      if (root && window.matchMedia('(max-width: 1040px)').matches) {
        const panel = [...root.querySelectorAll('[data-team-panel]')].find((item) => !item.hidden);
        if (panel) panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
      return true;
    }
    const renameBtn = event.target.closest('[data-team-rename]');
    if (renameBtn) {
      const dialog = document.querySelector('[data-team-rename-dialog]');
      if (dialog) {
        dialog.dataset.teamId = renameBtn.dataset.teamRename || '';
        const input = dialog.querySelector('input[name="name"]');
        const error = dialog.querySelector('[data-team-rename-error]');
        const save = dialog.querySelector('[data-team-rename-save]');
        if (input) input.value = renameBtn.dataset.teamLabel || '';
        if (error) { error.hidden = true; error.textContent = ''; }
        if (save) { save.disabled = false; save.textContent = '保存'; }
        if (!dialog.open) dialog.showModal();
        if (input) { input.focus(); input.select(); }
        return true;
      }
      /* 详情页等没有对话框的位置沿用系统 prompt。 */
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
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      const drawer = document.querySelector('.tp-page [data-tp-drawer]:not([hidden])');
      if (drawer) {
        teamDossier.closeGames(drawer.closest('.tp-page'));
        event.preventDefault();
        return;
      }
      const openMore = document.querySelector('.tp-page .tp-more[open]');
      if (openMore) {
        openMore.removeAttribute('open');
        event.preventDefault();
        return;
      }
    }
    const search = event.target.closest?.('[data-team-search]');
    if (search && event.key === 'Escape') {
      if (!search.value) return;
      event.preventDefault();
      clearTeamSearch(search);
      return;
    }
    if (event.key === 'Escape' && !document.querySelector('dialog[open]')) {
      const board = event.target.closest?.('[data-tm-board]');
      if (board?.dataset.teamCompare === '1') {
        setTeamCompare(board, false);
        return;
      }
    }
    /* 焦点在索引上时用 ↑/↓ 换对手，不用 Tab 一路按过去。 */
    const row = event.target.closest?.('[data-team-row]');
    if (row && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      const list = row.closest('[data-team-results]');
      const items = [...(list?.querySelectorAll('[data-team-row]:not([hidden])') || [])];
      if (items.length > 1) {
        event.preventDefault();
        const index = items.indexOf(row);
        const next = event.key === 'Home' ? 0
          : event.key === 'End' ? items.length - 1
            : event.key === 'ArrowDown' ? Math.min(items.length - 1, index + 1)
              : Math.max(0, index - 1);
        items[next].focus();
        const board = row.closest('[data-tm-board]');
        if (board?.dataset.teamCompare !== '1') selectTeam(board, items[next].dataset.teamSelect);
      }
      return;
    }
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    if (document.querySelector('.mf-pop, dialog[open]')) return;
    const box = document.querySelector('[data-team-search]');
    if (!box || !box.closest('[data-tm-board]')) return;
    event.preventDefault();
    box.focus();
  });
  return {has:name=>Object.hasOwn(endpoints,name)||['ingest','shots','videos','replays','review'].includes(name),load:(name,key,signal,fresh)=>name==='ingest'?captureIngestPage.load(name,key,signal,fresh):name==='capture'?sourcePages.load(name,key,signal):'review'===name?reviewPage.load(name,key,signal):['shots','videos','replays'].includes(name)?sourcePages.load(name,key,signal):Promise.all((name==='report'?[...endpoints[name],'v3/research/reports/'+encodeURIComponent(key)]:name==='hero'?[...endpoints[name],'studio/camp-partners?hero='+encodeURIComponent(key),'matches','v3/facts/lane_matchup','v3/hero-detail/'+encodeURIComponent(key)]:name==='playerdetail'?[...endpoints[name],'v3/player-detail?player='+encodeURIComponent(key)]:name==='session'?['studio/workspace/sessions/'+encodeURIComponent(key)]:name==='competition'?['studio/workspace/competitions/'+encodeURIComponent(key),'v3/players-board']:name==='team'?[...endpoints[name],'studio/camp-compare?team='+encodeURIComponent(key),'v3/team-bp','v3/team-deep?team='+encodeURIComponent(key),'v3/team-behavior']:endpoints[name]).map(p=>name==='team'&&String(p).startsWith('v3/team-deep')?api(p,{signal}).catch(()=>null):api(p==='matches'||p==='tempo'||p==='v3/identity'?p+currentQuery():p,{signal}))).then(data=>name==='weekly'?Promise.all([...data,api('studio/workspace/metrics/week?start='+encodeURIComponent(key||''),{signal})]):data),render:(name,data,key)=>renders[name](data,key),submit,click,change,afterRender:()=>{updatePairs();updateAnchorNav();const tmJumpButtons=[...document.querySelectorAll('.tm-jump [data-tm-jump]')];if(tmJumpButtons.length){const tmBasicButton=tmJumpButtons.find(b=>b.dataset.tmJump==='tm-basic');const tmGroups=[{button:tmBasicButton,target:document.getElementById('tm-score')},...tmJumpButtons.filter(b=>b.dataset.tmJump!=='tm-basic').map(b=>({button:b,target:document.getElementById(b.dataset.tmJump)}))].filter(g=>g.button&&g.target);if(tmGroups.length){if(window.__tmJumpScroll)window.removeEventListener('scroll',window.__tmJumpScroll);window.__tmJumpScroll=()=>{let active=tmGroups[0];for(const group of tmGroups){if(group.target.getBoundingClientRect().top<=180)active=group;}if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-4)active=tmGroups[tmGroups.length-1];tmJumpButtons.forEach(b=>b.setAttribute('aria-current',String(b===active.button)));};window.addEventListener('scroll',window.__tmJumpScroll,{passive:true});window.__tmJumpScroll();}}const teamRoot=document.querySelector('[data-tm-directory]');if(teamRoot){syncTeamList(teamRoot);linkTeamGames(teamRoot);}const tpSecs=[...document.querySelectorAll('.tp-page .tp-sec')];if(tpSecs.length){if(window.__tmJumpScroll)window.removeEventListener('scroll',window.__tmJumpScroll);const tpButtons=[...document.querySelectorAll('.tp-jump [data-tm-jump], .tp-bottom-nav [data-tm-jump]')];if(tpButtons.length&&'IntersectionObserver'in window){window.__tpSecObserver?.disconnect();const observer=new IntersectionObserver((entries)=>{const visible=entries.filter((e)=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;tpButtons.forEach((b)=>b.setAttribute('aria-current',String(b.dataset.tmJump===visible.target.id)));},{rootMargin:'-90px 0px -55% 0px',threshold:[0,.15,.5,.8]});tpSecs.forEach((sec)=>observer.observe(sec));window.__tpSecObserver=observer;}}captureIngestPage.afterRender();sourcePages.afterRender();reviewPage.afterRender();bindSxDialogs();const setupRoot=document.querySelector('[data-sx-anchor="teams"]');if(setupRoot)syncSetupTeams(setupRoot);const ownRoot=document.querySelector('[data-sx-scope="ownership"]');if(ownRoot)syncOwnershipGroups(ownRoot);const pendingRoot=document.querySelector('[data-sx-scope="pending"]');if(pendingRoot)syncPendingQueue(pendingRoot)}};
}
