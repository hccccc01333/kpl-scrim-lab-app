import {renderCollectionGuide} from '/assets/collection-guide.js?v=7';
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PAGE_LABELS = {
  score: '战绩 · 装备型', kda: '战绩 · KDA占比', data: '数据', output: '输出',
  survival: '生存', farming: '发育', team: '团队'
};
const FIELD_LABELS = {
  kills: '击杀', deaths: '死亡', assists: '助攻', gold: '总经济',
  damageDealt: '输出伤害', damageTaken: '承受伤害', participation: '参团率',
  takenPerDeath: '每死承伤', damageConversion: '伤害转化比', jungleGold: '野怪经济',
  cs: '补刀数', control: '控制效果', healing: '治疗量', towerDamage: '对塔伤害'
};
const SHARE_LABELS = {
  killsShare: '击杀占比', deathsShare: '死亡占比', assistsShare: '助攻占比',
  outputShare: '输出占比', takenShare: '承伤占比', goldShare: '经济占比',
  jungleShare: '野怪占比', csShare: '补刀占比', controlShare: '控制占比',
  healingShare: '治疗占比', towerShare: '对塔占比'
};
const FIELD_ORDER = ['kills','deaths','assists','gold','damageDealt','damageTaken',
  'participation','takenPerDeath','damageConversion','jungleGold','cs','control','healing','towerDamage'];
const SHARE_ORDER = ['killsShare','deathsShare','assistsShare','outputShare','takenShare',
  'goldShare','jungleShare','csShare','controlShare','healingShare','towerShare'];
const SIDE = {left: '左', right: '右'};
const HERO_STATUS = {exact: '精确', 'auto-matched': '自动匹配', uncertain: '待确认', unreadable: '未识别', manual: '手工'};
let HERO_NAMES = [];
let jobPollTimer = null;

const GUIDES = [
  {key: 'score', pageType: 'score', title: '战绩 · 装备型', desc: '日期 / 时长 / 胜负 / KDA / 经济 / 装备', guide: '/assets/capture-guide/score-equipment.svg'},
  {key: 'kda', pageType: 'kda', title: '战绩 · KDA占比', desc: '击败 / 死亡 / 助攻 + 占比', guide: '/assets/capture-guide/score-kda.svg'},
  {key: 'data', pageType: 'data', title: '数据', desc: '输出 / 承伤 / 总经济 / 参团率', guide: '/assets/capture-guide/data.svg'},
  {key: 'output', pageType: 'output', title: '输出', desc: '输出伤害 / 伤害转化比', guide: '/assets/capture-guide/output.svg'},
  {key: 'survival', pageType: 'survival', title: '生存', desc: '承受伤害 / 每死承伤', guide: '/assets/capture-guide/survival.svg'},
  {key: 'farming', pageType: 'farming', title: '发育', desc: '总经济 / 野怪经济 / 补刀数', guide: '/assets/capture-guide/farming.svg'},
  {key: 'team', pageType: 'team', title: '团队', desc: '参团率 / 控制 / 治疗 / 对塔', guide: '/assets/capture-guide/team.svg'},
];

const value = (field) => {
  if (!field) return '—';
  const v = field.value;
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  return String(v);
};
const fieldText = (field) => field ? `${value(field)}${field.raw && String(field.raw) !== String(field.value) ? `（原文 ${esc(field.raw)}）` : ''}` : '—';
const clock = (seconds) => seconds == null ? '—' : `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const resultText = (result) => ({win: '胜', loss: '负'}[result] || '—');
const num = (v) => v == null ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: 1});

function pageLabel(page) {
  return PAGE_LABELS[page?.pageType] || page?.pageType || '未识别';
}

function matchText(match = {}) {
  const bits = [];
  if (match.date) bits.push(match.date);
  if (match.time) bits.push(match.time);
  if (match.durationSec != null) bits.push(`时长 ${clock(match.durationSec)}`);
  if (match.mode) bits.push(match.mode);
  if (match.result) bits.push(resultText(match.result));
  return bits.join(' · ') || '未提供日期 / 时长';
}

function scoreText(match = {}) {
  const score = match.score || {};
  if (score.left == null && score.right == null) return '比分待识别';
  return `${score.left ?? '—'} : ${score.right ?? '—'}`;
}

function pageChip(page) {
  const imageId = page.imageId;
  return `<div class="capture-page">
    ${imageId ? `<img src="/api/images/${esc(imageId)}" alt="${esc(page.imageName || page.file || '截图')}" loading="lazy">` : ''}
    <div class="capture-page-info"><strong>${esc(pageLabel(page))}</strong><small>${esc(page.imageName || page.file || '截图')}</small>
    ${imageId ? `<button class="button ghost" data-preview="${esc(imageId)}">看原图</button>` : ''}</div>
  </div>`;
}

function playerCard(player, group, groupIndex) {
  const fields = player.fields || {};
  const shares = player.shares || {};
  const hero = player.hero?.value;
  const candidates = (player.heroCandidates || []).map(item => item.name).filter(Boolean);
  const options = [`<option value="">未识别${candidates.length ? `（候选：${esc(candidates.slice(0, 2).join(' / '))}）` : ''}</option>`]
    .concat(HERO_NAMES.map(name => `<option value="${esc(name)}"${name === hero ? ' selected' : ''}>${esc(name)}</option>`)).join('');
  const present = FIELD_ORDER.filter(key => fields[key]);
  const presentShares = SHARE_ORDER.filter(key => shares[key]);
  const imageIds = group?.imageIds || [];
  return `<article class="capture-player">
    <header><div><span class="capture-slot ${player.side === 'right' ? 'right' : ''}">${SIDE[player.side] || '?'}${(player.slot ?? 0) + 1}</span>
      <strong>${esc(player.nickname?.value || '未识别昵称')}</strong></div>
      <span class="capture-rating">评分 ${value(player.rating)}</span></header>
    <div class="capture-hero"><select class="capture-hero-select" data-hero-edit data-group-index="${groupIndex}" data-side="${esc(player.side)}" data-slot="${player.slot}" aria-label="修正英雄" ${imageIds.length ? '' : 'disabled'}>${options}</select>
      ${hero ? `<span class="tag ${player.heroStatus === 'exact' ? '' : 'amber'}">${esc(HERO_STATUS[player.heroStatus] || player.heroStatus)}</span>` : ''}
      ${player.mvp ? ' <span class="tag">MVP</span>' : ''}${player.title?.value ? ` <span class="tag gray">${esc(player.title.value)}</span>` : ''}</div>
    ${present.length ? `<dl>${present.map(key => `<div><dt>${FIELD_LABELS[key]}</dt><dd>${fieldText(fields[key])}</dd></div>`).join('')}</dl>` : '<p class="helper">本页没有可读数值。</p>'}
    ${presentShares.length ? `<div class="capture-shares">${presentShares.map(key => `<span>${SHARE_LABELS[key]} ${value(shares[key])}%</span>`).join('')}</div>` : ''}
  </article>`;
}

function slotCard(guide, images) {
  const matched = images.filter(image => image.pageType === guide.pageType);
  const latest = matched[0];
  return `<article class="capture-slot-card ${matched.length ? 'filled' : ''}" data-slot-card="${guide.key}">
    <a class="capture-guide" href="${guide.guide}" target="_blank" rel="noopener" title="查看 ${esc(guide.title)} 示意图">
      <img src="${guide.guide}" alt="${esc(guide.title)} 截图示意" loading="lazy">
    </a>
    <div class="capture-slot-body"><div class="capture-slot-heading"><strong>${esc(guide.title)}</strong>
      <span class="tag ${matched.length ? '' : 'gray'}">${matched.length ? `已采集 ${matched.length} 张` : '待放入'}</span></div>
      <p>${esc(guide.desc)}</p>
      ${latest ? `<small>最近：${esc(latest.name || '截图')}</small>` : ''}
      <div class="capture-slot-actions">
        <label class="button secondary capture-slot-button">放入这张截图
          <input type="file" accept="image/png,image/jpeg,image/webp" data-slot-file="${guide.key}" hidden>
        </label>
        <a class="button ghost" href="${guide.guide}" target="_blank" rel="noopener">看示意图 ↗</a>
      </div>
    </div>
  </article>`;
}

function slotSection(images) {
  return `<section class="panel section-gap"><div class="panel-header"><div><h2>按页签放入</h2>
    <div class="panel-subtitle">战绩 / 数据 / 输出 / 生存 / 发育 / 团队，共 7 类入口</div></div><span class="helper">每张图只放一个页签；放错会自动提示</span></div>
    <div class="capture-slot-grid">${GUIDES.map(guide => slotCard(guide, images)).join('')}</div>
    <div class="capture-slot-note">示意图只说明截图范围和列头，不代表实际比分或选手数据。不同日期的截图会自动分到不同比赛组。</div>
  </section>`;
}

function teamSummary(team, side) {
  if (!team) return '';
  const complete = team.complete || {};
  const totals = team.totals || {};
  const samples = team.samples || {};
  const total = (field) => {
    const value = totals[field];
    if (value == null) return '—';
    if (!complete[field]) return `${num(value)} <small>${samples[field] || 0}/5 部分</small>`;
    return num(value);
  };
  const kda = complete.kills && complete.deaths && complete.assists
    ? `${totals.kills} / ${totals.deaths} / ${totals.assists}` : '—';
  return `<article class="capture-team">
    <header><div><h3>截图${side === 'left' ? '左方' : '右方'} · ${team.players || 0} 人</h3></div>
      ${team.kdaRatio == null ? '' : `<span class="tag">KDA 比率 ${team.kdaRatio}</span>`}</header>
    <div class="capture-team-stats">
      <div><span>K / D / A</span><strong>${kda}</strong></div>
      <div><span>总经济</span><strong>${total('gold')}</strong></div>
      <div><span>输出伤害</span><strong>${total('damageDealt')}</strong></div>
      <div><span>承受伤害</span><strong>${total('damageTaken')}</strong></div>
      <div><span>平均参团率</span><strong>${team.averages?.participation == null ? '—' : num(team.averages.participation) + '%'}</strong></div>
      <div><span>控制 / 治疗 / 对塔</span><strong>${total('control')} / ${total('healing')} / ${total('towerDamage')}</strong></div>
    </div>
  </article>`;
}

function comparisonRows(group) {
  const comparisons = group.analysis?.comparisons || {};
  const labels = {kills: '击杀', gold: '总经济', damageDealt: '输出伤害', damageTaken: '承受伤害', healing: '治疗量', towerDamage: '对塔伤害', control: '控制效果'};
  const rows = Object.keys(labels).filter(key => comparisons[key]?.complete).map(key => {
    const item = comparisons[key];
    const max = Math.max(Number(item.left) || 0, Number(item.right) || 0, 1);
    const left = Math.max(0, Math.min(100, (Number(item.left) || 0) / max * 100));
    const right = Math.max(0, Math.min(100, (Number(item.right) || 0) / max * 100));
    const diff = item.difference == null ? '—' : `${item.difference >= 0 ? '+' : ''}${num(item.difference)}`;
    return `<div class="capture-compare-row"><span>${labels[key]}</span><div class="capture-compare-bars">
      <i class="left" style="width:${left}%"></i><i class="right" style="width:${right}%"></i></div>
      <strong>${diff}</strong><small>左 ${num(item.left)} · 右 ${num(item.right)}</small></div>`;
  });
  return rows.length ? rows.join('') : '<p class="helper">还没有双方各 5 人齐全的可比字段。</p>';
}

function rankingChart(group) {
  const players = group.analysis?.players || group.players || [];
  const fields = [['damageDealt', '输出伤害'], ['gold', '总经济'], ['control', '控制效果'], ['healing', '治疗量'], ['towerDamage', '对塔伤害'], ['participation', '参团率']];
  const selected = fields.find(([field]) => players.some(player => player.fields?.[field]?.value != null));
  if (!selected) return '';
  const [field, label] = selected;
  const rows = players.filter(player => player.fields?.[field]?.value != null)
    .sort((a, b) => b.fields[field].value - a.fields[field].value);
  const max = Math.max(...rows.map(player => Number(player.fields[field].value) || 0), 1);
  return `<div class="capture-ranking"><div class="capture-ranking-head"><strong>${label}排行</strong><span>按本组 10 人显示</span></div>
    ${rows.map(player => {
      const value = player.fields[field].value;
      const width = Math.max(1, (Number(value) || 0) / max * 100);
      const nickname = player.nickname?.value || '未识别';
      const hero = player.hero?.value || '—';
      return `<div class="capture-rank-row"><span class="capture-rank-side">${SIDE[player.side] || '?'}${(player.slot ?? 0) + 1}</span>
        <strong>${esc(nickname)}</strong><small>${esc(hero)}</small><div class="capture-rank-bar"><i style="width:${width}%"></i></div><em>${num(value)}</em></div>`;
    }).join('')}</div>`;
}

function analysisBlock(group) {
  const analysis = group.analysis;
  if (!analysis) return '';
  const highlights = (analysis.highlights || []).map(item => `<span class="capture-highlight"><b>${item.label}</b> ${esc(item.player?.nickname || '未识别')} · ${num(item.value)}</span>`).join('');
  const warnings = analysis.warnings || [];
  return `<div class="capture-analysis">
    <div class="capture-analysis-title"><div><h3>分组汇总</h3></div><span class="helper">只汇总齐全字段；部分数据不冒充团队合计</span></div>
    <div class="capture-team-grid">${teamSummary(analysis.teams?.left, 'left')}${teamSummary(analysis.teams?.right, 'right')}</div>
    <div class="capture-compare"><div class="capture-analysis-subtitle"><strong>截图左右对比</strong><span>差值 = 左 - 右</span></div>${comparisonRows(group)}</div>
    ${highlights ? `<div class="capture-highlights">${highlights}</div>` : ''}
    ${rankingChart(group)}
    ${warnings.length ? `<div class="capture-analysis-warning">${warnings.map(esc).join('<br>')}</div>` : ''}
  </div>`;
}

function checklistBlock(group) {
  const checklist = group.checklist;
  if (!checklist) return '';
  const missingRequired = checklist.missingRequired || [];
  const missingRecommended = checklist.missingRecommended || [];
  return `<div class="capture-checklist ${checklist.complete ? 'ok' : 'warn'}">
    <div class="capture-checklist-head"><strong>${checklist.complete ? '七种页型齐全' : '还缺页型'}</strong>
      <span>${(checklist.present || []).map(item => `<span class="tag">${esc(item)}</span>`).join('') || '<span class="tag gray">暂无页签</span>'}</span></div>
    ${missingRequired.length ? `<div class="capture-checklist-missing">缺：${missingRequired.map(item => `<b>${esc(item.page)}</b><small>${esc(item.detail)}</small>`).join('')}</div>` : ''}
    ${missingRecommended.length ? `<div class="helper">建议补采：${missingRecommended.map(item => esc(item.page)).join(' / ')}</div>` : ''}
    ${(checklist.notes || []).length ? `<div class="helper">${checklist.notes.map(esc).join(' ')}</div>` : ''}
  </div>`;
}

function storageWarning(status) {
  const free = Number(status?.storage?.dbFreeBytes);
  if (!Number.isFinite(free) || free >= 64 * 1024 * 1024) return '';
  return `<div class="notice red"><strong>数据库所在磁盘剩余仅 ${(free / 1024 / 1024).toFixed(1)} MB。</strong>截图识别结果可能写不进去。请清理磁盘，或把 TRAINING_DB 指向空间更充足的位置后重启服务。</div>`;
}

function engineBanner(status) {
  const mimo = status?.mimo || {};
  const rapid = status?.rapid || {};
  const active = (status?.jobs || []).filter(job => ['queued', 'running'].includes(job.status)).length;
  return `<div class="capture-engine">
    <div><span>Mimo 精读</span><strong>${mimo.available ? 'mimo-ocr-0' : '未找到模型'}</strong><small>${mimo.available ? `${esc(mimo.device || 'cpu')} · 缓存 ${num(mimo.cacheFiles)} 张` : '快速识别仍可用'}</small></div>
    <div><span>快速布局</span><strong>${rapid.available ? 'RapidOCR' : '未安装'}</strong><small>页型 / 数值 / 坐标</small></div>
    <div><span>后台任务</span><strong>${num(active)}</strong><small>精读排队执行</small></div>
  </div>`;
}

function jobProgress(job) {
  if (!job || !['queued', 'running'].includes(job.status)) return '';
  return `<div class="capture-job"><span>${esc(job.stage || '精读中')}</span><div class="recording-progress"><i style="width:${Math.max(2, Math.min(100, Number(job.progress) || 0))}%"></i></div><small>${job.progress || 0}%</small></div>`;
}

function groupJobFor(group, jobs) {
  const ids = new Set(group.imageIds || []);
  return (jobs || []).find(job => job.kind === 'postgame-group' &&
    (job.meta?.imageIds || []).some(id => ids.has(id)) &&
    ['queued', 'running'].includes(job.status));
}

function groupCard(group, index, jobs = [], mimo = {}) {
  const match = group.match || {};
  const score = match.score || {};
  const missingHeroes = (group.players || []).filter(player => !player.hero).length;
  const activeJob = groupJobFor(group, jobs);
  let validation = '';
  if (score.left != null && score.right != null) {
    const checks = ['left','right'].map(side => {
      const kills = (group.players || []).filter(player => player.side === side).map(player => player.fields?.kills?.value);
      return kills.length === 5 && kills.every(v => v !== undefined && v !== null)
        ? `${SIDE[side]}击杀 ${kills.reduce((a, b) => a + b, 0)}` : null;
    }).filter(Boolean);
    if (checks.length) validation = `<span class="tag">${checks.join(' · ')} · 与比分核对</span>`;
  }
  return `<section class="capture-group">
    <div class="capture-group-head"><div>
      <h2>${esc(matchText(match))}${group.demo ? ' <span class="tag amber">示例数据</span>' : ''}${missingHeroes ? ` <span class="tag amber">${missingHeroes} 个英雄待修正</span>` : ''}</h2><p class="helper">${esc(scoreText(match))} · ${group.pages?.length || 0} 页 · ${group.players?.length || 0} 人</p></div>
      <div class="capture-group-actions">${validation}${mimo.available ? `<button class="button secondary" data-refine-group="${index}" ${activeJob ? 'disabled' : ''}>${activeJob ? '精读中…' : 'Mimo 精读整组'}</button>` : ''}<button class="button secondary" data-export-group="${index}">导出一组 JSON</button><button class="button" data-draft-group="${index}">生成比赛草稿</button></div></div>
    ${checklistBlock(group)}
    ${group.reconciliation?.kda?.length ? `<div class="notice green"><strong>KDA 已按页面占比与比分校正 ${group.reconciliation.kda.length} 项。</strong>${group.reconciliation.kda.map(esc).join('；')}。原始读数保留在字段里，可展开逐人明细核对。</div>` : ''}
    ${jobProgress(activeJob)}
    <div class="capture-pages">${(group.pages || []).map(pageChip).join('')}</div>
    ${(group.warnings || []).length ? `<div class="notice">${group.warnings.map(esc).join('<br>')}</div>` : ''}
    ${analysisBlock(group)}
    <details class="capture-player-details" ${missingHeroes ? 'open' : ''}><summary>${missingHeroes ? '英雄待修正 · ' : ''}展开 ${group.players?.length || 0} 人字段明细 · 可修正英雄</summary>
      <div class="capture-player-grid">${(group.players || []).map((player, playerIndex) => playerCard(player, group, index)).join('')}</div>
    </details>
  </section>`;
}

function imageRow(image, jobs = [], mimo = {}) {
  const match = image.match || {};
  const warnings = image.warnings || [];
  const activeJob = (jobs || []).find(job => job.kind === 'postgame-refine' &&
    job.targetId === image.id && ['queued', 'running'].includes(job.status));
  const quality = image.quality || {};
  const refined = image.mimo?.available;
  return `<tr><td><strong>${esc(image.name || image.id)}</strong><div class="helper">${esc(image.id?.slice(0, 12) || '')}</div>${jobProgress(activeJob)}</td>
    <td>${esc(pageLabel(image))}</td><td>${esc(matchText(match))}<div class="helper">${esc(scoreText(match))}</div></td>
    <td>${refined ? '<span class="tag">Mimo 已精读</span>' : '<span class="tag gray">快速识别</span>'}
      ${quality.warnings?.length ? `<span class="tag amber">${quality.warnings.length} 条质量提示</span>` : ''}
      ${warnings.length ? `<div class="helper">${warnings.length} 条识别提示</div>` : ''}</td>
    <td><div class="capture-row-actions"><button class="button ghost" data-preview="${esc(image.id)}">看原图</button>
      ${mimo.available && !activeJob && !refined ? `<button class="button ghost" data-refine-image="${esc(image.id)}">Mimo 精读</button>` : ''}
      ${activeJob ? `<button class="button ghost" data-cancel-job="${esc(activeJob.id)}">取消精读</button>` : ''}
      <button class="button ghost" data-recognize="${esc(image.id)}">重新识别</button>
      <button class="button ghost" data-delete="${esc(image.id)}">移出采集</button></div></td></tr>`;
}

function summary(data) {
  return `<div class="metrics capture-metrics">
    <div class="metric"><div class="metric-label">已采集截图</div><div class="metric-number">${data.images?.length || 0}<small>张</small></div><div class="metric-note">本机原图与识别结果</div></div>
    <div class="metric"><div class="metric-label">识别出的比赛组</div><div class="metric-number">${data.groups?.length || 0}<small>组</small></div><div class="metric-note">按比分 / 日期 / 十人阵容分组</div></div>
    <div class="metric"><div class="metric-label">固定页型</div><div class="metric-number">7<small>类</small></div><div class="metric-note">战绩两种形态 + 数据/输出/生存/发育/团队</div></div>
    <div class="metric"><div class="metric-label">数据状态</div><div class="metric-number capture-small">候选</div><div class="metric-note">不写正式比赛，不进入胜率</div></div>
  </div>`;
}

function draftFromGroup(group) {
  const match = group.match || {};
  const sourceFields = {
    kills: 'kills', deaths: 'deaths', assists: 'assists', gold: 'gold',
    damage: 'damageDealt', taken: 'damageTaken', participation: 'participation', rating: 'rating'
  };
  const players = [];
  for (const side of ['left', 'right']) {
    for (const player of (group.players || []).filter(item => item.side === side).sort((a, b) => a.slot - b.slot)) {
      const row = {side, slot: player.slot, playerId: '', hero: player.hero?.value || '',
                   position: '', equipment: '', sources: {}};
      for (const [target, source] of Object.entries(sourceFields)) {
        const field = source === 'rating' ? player.rating : player.fields?.[source];
        if (field && field.value != null) {
          row[target] = String(field.value);
          row.sources[target] = {raw: field.raw, confidence: field.confidence};
        } else {
          row[target] = '';
        }
      }
      players.push(row);
    }
  }
  if (players.length !== 10) throw Error('该组不足 10 人，无法生成比赛草稿；请先补齐截图');
  const score = match.score || {};
  const duration = match.durationSec == null ? '' : (match.durationSec / 60).toFixed(2);
  return {
    id: crypto.randomUUID(), revision: 0, status: 'draft', side: '', winner: '',
    date: match.date || '', opponent: '', version: '', session: '', duration,
    notes: '由新版分页截图采集生成；日期、比分和通用字段已带入。本队阵营、队员、英雄与团队字段请核对后确认。',
    bp: '', reviewed: false,
    scores: {left: score.left == null ? '' : String(score.left), right: score.right == null ? '' : String(score.right)},
    imageIds: group.imageIds || (group.pages || []).map(page => page.imageId).filter(Boolean),
    players,
    ocrAudit: [{type: 'postgame-capture', appliedAt: new Date().toISOString(),
                imageIds: group.imageIds || [], pages: (group.pages || []).map(page => page.pageType)}]
  };
}

export async function renderScreenshots(container, {api, toast, isCurrent}) {
  let data = {images: [], groups: []};
  let status = {mimo: {}, rapid: {}, jobs: []};
  let busy = false;
  let autoRefine = localStorage.getItem('capture-auto-refine') === '1';
  const load = async () => {
    const [collection, catalog, ocrStatus, jobsResult] = await Promise.all([
      api('/api/postgame/images?t=' + Date.now()),
      api('/api/catalog?t=' + Date.now()),
      api('/api/ocr/status?t=' + Date.now()),
      api('/api/ocr/jobs?limit=40&t=' + Date.now()),
    ]);
    data = collection;
    status = {...ocrStatus, jobs: jobsResult.jobs || []};
    HERO_NAMES = (catalog.entries || []).filter(entry => entry.kind === 'hero').map(entry => entry.name).sort((a, b) => a.localeCompare(b, 'zh'));
  };
  const draw = () => {
    if (!isCurrent()) return;
    const groups = data.groups || [];
    const images = data.images || [];
    const demoCount = images.filter(image => image.demo).length;
    container.innerHTML = `<div class="page-heading"><div><h1>截图采集</h1>
      <p class="subtitle">把新版赛后分页截图放进工作台，逐页提取固定字段，再把同一局的多页合成一组。</p></div>
      <span class="tag amber">采集通道 · 候选数据</span></div>
      ${renderCollectionGuide('screenshots')}
      ${engineBanner(status)}
      ${storageWarning(status)}
      ${!images.length ? `<div class="notice capture-demo-banner"><strong>还没有采集数据？</strong>可以先载入 7 张示例截图查看团队汇总、选手对比和字段覆盖。<button class="button secondary" id="load-demo">载入示例分析</button></div>` : ''}
      ${summary(data)}
      <div class="notice">英雄名读不清时，展开每个比赛组的“10 人字段明细”，用英雄下拉直接修正。若这一局有回放/表格名单，放进“采集通道”后会先用十人英雄名单做自动比对。</div>
      ${demoCount ? `<div class="notice capture-demo-banner"><strong>当前包含 ${demoCount} 张示例数据。</strong>示例只用于预览分析，不会进入正式统计。<button class="button ghost" id="clear-demo">清除示例数据</button></div>` : ''}
      ${slotSection(images)}
      <section class="panel section-gap"><div class="panel-header"><div><h2>自动识别 / 批量上传</h2>
        <div class="panel-subtitle">不知道页签时使用这个入口</div></div><span class="helper">识别在本机完成，不访问网络</span></div>
      <div class="form-section"><details class="capture-auto"><summary>展开批量上传</summary>
        <div class="capture-drop" id="capture-drop" tabindex="0" role="button" aria-label="上传新版分页赛后截图">
          <div class="upload-symbol"><svg viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 10.6V3.9M5.2 6.3 8 3.5l2.8 2.8"/><path d="M3.2 13h9.6"/></svg></div><strong>把新版赛后截图拖进来</strong><p>可以一次选多个页签。不同比赛会分成不同组，不会静默混在一起。</p>
          <span class="button secondary">选择截图</span><input id="capture-file" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden>
        </div>
      </details><div class="helper" id="capture-progress" role="status">识别在本机完成；英雄近似名只给候选，数值必须人工复核。</div>
      <label class="capture-auto-refine"><input id="capture-auto-refine" type="checkbox" ${autoRefine ? 'checked' : ''}> 上传后自动 Mimo 精读（每张约 1–3 分钟，后台排队）</label>
      <p class="helper">当前支持：战绩（装备型/KDA占比）、数据、输出、生存、发育、团队。日期、时长、胜负只在战绩页；数据页只有比分是正常的。</p></div></section>
      <section class="panel section-gap"><div class="panel-header"><h2>识别分组</h2><span class="tag gray">${groups.length} 组</span></div>
      ${groups.length ? `<div class="capture-groups">${groups.map((group, index) => groupCard(group, index, status.jobs, status.mimo)).join('')}</div>` : `<div class="empty"><strong>还没有可展示的分页截图</strong>先上传一张战绩页；也可以一次上传同一局的多个页签。<br><span class="helper">没有数据时，也可以用页面上方的“载入示例分析”。</span></div>`}</section>
      <section class="panel section-gap"><div class="panel-header"><h2>已采集截图</h2><span class="tag gray">${images.length} 张</span></div>
      ${images.length ? `<div class="table-wrap"><table><thead><tr><th>文件</th><th>页型</th><th>比赛信息</th><th>状态</th><th></th></tr></thead><tbody>${images.map(image => imageRow(image, status.jobs, status.mimo)).join('')}</tbody></table></div>` : '<div class="empty">上传后，原图、页型和识别结果会保存在本机。</div>'}</section>
      <p class="summary-footnote">数据只作为采集候选保存；采集本身不进入胜率。“生成比赛草稿”只带入通用字段，仍需在比赛校对页确认本队阵营、队员、英雄和正式入库。导出 JSON 可交给后续适配器或人工复核。</p>`;
    const drop = container.querySelector('#capture-drop');
    const fileInput = container.querySelector('#capture-file');
    if (fileInput) fileInput.onchange = event => { const files = [...event.target.files]; fileInput.value = ''; uploadFiles(files); };
    if (drop) {
      drop.onclick = event => { if (!event.target.closest('input')) fileInput.click(); };
      drop.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') fileInput.click(); };
      drop.ondragover = event => { event.preventDefault(); drop.classList.add('dragging'); };
      drop.ondragleave = () => drop.classList.remove('dragging');
      drop.ondrop = event => { event.preventDefault(); drop.classList.remove('dragging'); uploadFiles(event.dataTransfer.files); };
    }
    container.querySelectorAll('[data-slot-file]').forEach(input => input.onchange = event => {
      const files = [...event.target.files]; input.value = '';
      uploadFiles(files, input.dataset.slotFile);
    });
    container.querySelectorAll('[data-preview]').forEach(button => button.onclick = () => {
      const dialog = document.querySelector('#image-dialog');
      const image = dialog?.querySelector('#full-image');
      if (!dialog || !image) return;
      image.src = '/api/images/' + encodeURIComponent(button.dataset.preview);
      dialog.showModal();
    });
    container.querySelectorAll('[data-export-group]').forEach(button => button.onclick = () => {
      const group = groups[Number(button.dataset.exportGroup)];
      if (!group) return;
      download(`截图采集-${group.match?.date || '未定日期'}-${Number(button.dataset.exportGroup) + 1}.json`,
        JSON.stringify(group, null, 2));
    });
    container.querySelectorAll('[data-draft-group]').forEach(button => button.onclick = () => createDraft(groups[Number(button.dataset.draftGroup)], button));
    container.querySelectorAll('[data-hero-edit]').forEach(select => select.onchange = () => saveHero(select, groups[Number(select.dataset.groupIndex)]));
    container.querySelectorAll('[data-recognize]').forEach(button => button.onclick = () => rerun(button.dataset.recognize, button));
    container.querySelectorAll('[data-delete]').forEach(button => button.onclick = () => remove(button.dataset.delete));
    container.querySelectorAll('[data-refine-image]').forEach(button => button.onclick = () => refineImage(button.dataset.refineImage));
    container.querySelectorAll('[data-refine-group]').forEach(button => button.onclick = () => refineGroup(groups[Number(button.dataset.refineGroup)], button));
    container.querySelectorAll('[data-cancel-job]').forEach(button => button.onclick = () => cancelJob(button.dataset.cancelJob));
    const autoRefineBox = container.querySelector('#capture-auto-refine');
    if (autoRefineBox) autoRefineBox.onchange = () => {
      autoRefine = autoRefineBox.checked;
      localStorage.setItem('capture-auto-refine', autoRefine ? '1' : '0');
    };
    const loadDemoButton = container.querySelector('#load-demo');
    if (loadDemoButton) loadDemoButton.onclick = () => loadDemo(loadDemoButton);
    const clearDemoButton = container.querySelector('#clear-demo');
    if (clearDemoButton) clearDemoButton.onclick = () => clearDemo(clearDemoButton);
  };

  async function loadDemo(button) {
    if (busy) return;
    if (!confirm('载入 7 张示例截图并运行一次本机识别（约需 1 分钟），示例数据会单独标记，不进入正式统计。继续？')) return;
    busy = true; button.disabled = true;
    const progress = container.querySelector('#capture-progress');
    if (progress) progress.textContent = '正在载入示例截图并识别，首次约需 1 分钟…';
    try {
      const response = await fetch('/api/postgame/demo', {method: 'POST'});
      const value = await response.json();
      if (!response.ok) throw Error(value.detail || '示例数据载入失败');
      await load();
      if (isCurrent()) { draw(); toast('示例数据已载入，可直接查看团队汇总和选手对比'); }
    } catch (error) { toast(error.message, true); button.disabled = false; }
    finally { busy = false; }
  }

  async function clearDemo(button) {
    if (busy) return;
    if (!confirm('只清除示例采集结果，保留原图和真实采集数据。继续？')) return;
    busy = true; button.disabled = true;
    try {
      const result = await api('/api/postgame/demo', 'DELETE');
      await load();
      if (isCurrent()) { draw(); toast(`已清除 ${result.removed} 张示例结果`); }
    } catch (error) { toast(error.message, true); button.disabled = false; }
    finally { busy = false; }
  }

  async function refineImage(imageId, quiet = false) {
    try {
      const job = await api('/api/postgame/images/' + encodeURIComponent(imageId) + '/refine', 'POST');
      if (!quiet) {
        toast(`Mimo 精读已排队（${job.id}）`);
        await load();
        if (isCurrent()) draw();
        pollJobs();
      }
      return job;
    } catch (error) {
      if (!quiet) toast(error.message, true);
      else console.warn('自动 Mimo 精读未启动：', error);
      return null;
    }
  }

  async function refineGroup(group, button) {
    if (!group?.imageIds?.length || busy) return;
    busy = true;
    if (button) button.disabled = true;
    try {
      const job = await api('/api/postgame/refine', 'POST', {imageIds: group.imageIds});
      toast(`整组 Mimo 精读已排队（${job.id}）`);
      await load();
      if (isCurrent()) draw();
      pollJobs();
    } catch (error) {
      toast(error.message, true);
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  async function cancelJob(jobId) {
    try {
      await api('/api/ocr/jobs/' + encodeURIComponent(jobId) + '/cancel', 'POST');
      toast('已请求取消精读任务');
      await load();
      if (isCurrent()) draw();
    } catch (error) { toast(error.message, true); }
  }

  function pollJobs() {
    clearTimeout(jobPollTimer);
    jobPollTimer = setTimeout(async () => {
      if (!isCurrent()) return;
      try {
        await load();
        if (isCurrent()) draw();
        const active = (status.jobs || []).some(job => ['queued', 'running'].includes(job.status));
        if (active) pollJobs();
      } catch (error) { console.warn('精读任务刷新失败：', error); }
    }, 1800);
  }

  async function uploadFiles(files, expectedPageType = null) {
    if (busy || !files?.length) return;
    busy = true;
    const progress = container.querySelector('#capture-progress');
    let done = 0, errors = [], mismatches = [];
    try {
      for (const file of files) {
        if (!isCurrent()) return;
        if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { errors.push(`${file.name}: 不是支持的图片`); continue; }
        if (file.size > 12 * 1024 * 1024) { errors.push(`${file.name}: 超过 12 MB`); continue; }
        if (progress) progress.textContent = `正在上传 ${file.name}…`;
        try {
          const response = await fetch('/api/images?name=' + encodeURIComponent(file.name), {method: 'POST', body: file});
          const uploaded = await response.json();
          if (!response.ok) throw Error(uploaded.detail || '上传失败');
          if (progress) progress.textContent = `正在本机识别 ${file.name}…`;
          const recognized = await fetch('/api/postgame/images/' + encodeURIComponent(uploaded.id) + '/ocr', {method: 'POST'});
          const result = await recognized.json();
          if (!recognized.ok) throw Error(result.detail || '识别失败');
          done += 1;
          if (expectedPageType && result.pageType !== expectedPageType) {
            const expected = GUIDES.find(guide => guide.key === expectedPageType)?.title || expectedPageType;
            mismatches.push(`${file.name}: 放入“${expected}”槽，但识别为“${PAGE_LABELS[result.pageType] || result.pageType}”`);
          }
          if (autoRefine && status.mimo?.available) refineImage(uploaded.id, true);
        } catch (error) { errors.push(`${file.name}: ${error.message}`); }
      }
      await load();
      if (isCurrent()) {
        draw();
        const notes = [errors.length ? `${errors.length} 张失败` : '', mismatches.length ? `${mismatches.length} 张页签不匹配` : ''].filter(Boolean);
        toast(`已采集 ${done} 张截图${notes.length ? `；${notes.join('，')}` : ''}`, Boolean(errors.length || mismatches.length));
      }
      if (errors.length) console.warn('截图采集失败：', errors);
      if (mismatches.length) console.warn('页签不匹配：', mismatches);
      if (autoRefine) pollJobs();
    } catch (error) {
      toast(error.message, true);
    } finally { busy = false; }
  }

  async function saveHero(select, group) {
    if (busy || !group?.imageIds?.length) return;
    busy = true; select.disabled = true;
    try {
      await api('/api/postgame/images/hero', 'PATCH', {
        imageIds: group.imageIds, side: select.dataset.side, slot: Number(select.dataset.slot), hero: select.value,
      });
      await load();
      if (isCurrent()) { draw(); toast(select.value ? `英雄已修正为 ${select.value}` : '已清除该选手英雄'); }
    } catch (error) { toast(error.message, true); select.disabled = false; }
    finally { busy = false; }
  }

  async function createDraft(group, button) {
    if (!group || busy) return;
    if (!confirm('生成草稿只会带入通用字段（日期、比分、KDA、经济、输出、承伤、参团、评分）；本队阵营、队员、英雄等仍需人工确认。继续？')) return;
    busy = true; button.disabled = true;
    try {
      const draft = draftFromGroup(group);
      const saved = await api('/api/matches', 'POST', draft);
      toast('已生成比赛草稿，正在打开校对页');
      location.hash = '#edit/' + encodeURIComponent(saved.id);
    } catch (error) { toast(error.message, true); button.disabled = false; busy = false; }
  }

  async function rerun(imageId, button) {
    if (busy) return;
    busy = true; button.disabled = true;
    const progress = container.querySelector('#capture-progress');
    if (progress) progress.textContent = '正在重新识别这张截图…';
    try {
      await fetch('/api/postgame/images/' + encodeURIComponent(imageId) + '/ocr?refresh=true', {method: 'POST'})
        .then(async response => { const value = await response.json(); if (!response.ok) throw Error(value.detail || '识别失败'); });
      await load();
      if (isCurrent()) { draw(); toast('已重新识别并刷新分组'); }
    } catch (error) { toast(error.message, true); button.disabled = false; }
    finally { busy = false; }
  }

  async function remove(imageId) {
    if (!confirm('只移除这张截图的采集结果，原图和正式比赛记录不受影响。继续？')) return;
    try {
      await api('/api/postgame/images/' + encodeURIComponent(imageId), 'DELETE');
      await load();
      if (isCurrent()) { draw(); toast('已移出采集结果'); }
    } catch (error) { toast(error.message, true); }
  }

  container.innerHTML = '<div class="loading">正在读取本机截图采集结果…</div>';
  try { await load(); draw(); }
  catch (error) {
    if (isCurrent()) container.innerHTML = '<div class="notice">截图采集结果读取失败，请确认本地服务仍在运行。</div>';
    toast(error.message, true);
  }
}

function download(name, content) {
  const url = URL.createObjectURL(new Blob([content], {type: 'application/json;charset=utf-8'}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
