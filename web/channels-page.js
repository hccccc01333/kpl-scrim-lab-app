import {bpEditorHtml,bindBpEditor} from '/assets/bp-editor.js?v=6';
import {renderCollectionGuide} from '/assets/collection-guide.js?v=7';
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v) => v == null ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: 1});
const clock = (seconds) => seconds == null ? '—' : `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const SIDE = {left: '左', right: '右'};
const SOURCE_LABELS = {official:'王者营地', camp: '营地十人面板', table: '表格', video: '录像', screenshot: '截图', replay: '回放'};
const CAMP_BATTLE_MODES = {'16': '排位', '12': '排位（双排样本）'};
// collection-v3：官方链接唯一必采；营地面板（推荐）或 七图+录屏（兜底）任一齐备即可审核。
const SOURCE_HINTS = {official:'唯一必采 · 本局网页回放链接', camp: '推荐主路径 · 同步后一键导入 BP 与十人面板', table:'选填 · 标准十人表',video:'兜底路径 · 与七图一起凑齐审核门槛',screenshot:'兜底路径 · 与录屏一起凑齐审核门槛',replay:'选填 · .abc / .ope'};
// 后 7 项是营地十人面板自动带入的 B 组增强字段；草稿表格只校对前 8 项必填，
// 但冲突/变更提示必须能显示中文名，否则会露出英文键。
const FIELD_LABELS = {kills: '击杀', deaths: '死亡', assists: '助攻', gold: '总经济', damage: '输出', taken: '承伤', participation: '参团率', rating: '评分', cs: '补刀', jungleGold: '野怪经济', control: '控制效果', healing: '治疗量', towerDamage: '对塔伤害', damageConversion: '伤害转化比', takenPerDeath: '每死承伤'};
const SOURCE_NAMES = {screenshot: '截图', table: '表格', source: '来源', video: '录像', replay: '回放', manual: '手工'};
const HERO_STATUS = {table:'表格原值',exact: '精确', 'roster-candidate': '名单候选', 'roster-elimination': '名单排除', uncertain: '待确认', unreadable: '未识别', manual: '手工'};
const ACTION_NAMES = {create: '创建', 'update-match': '修改本局信息', 'attach-screenshot': '关联截图', 'attach-table': '关联表格', 'attach-video': '关联录像报告', 'attach-replay': '关联回放', 'attach-official': '关联官方回放', review: '完成审核', 'review-invalidated': '来源变更，审核失效', save: '保存本局数据'};
const STATUS_LABELS = {missing: '缺失', parsed: '已完成', completed: '已完成', partial: '部分', failed: '失败'};

function statusTag(status) {
  const label = STATUS_LABELS[status] || status || '缺失';
  const cls = status === 'missing' ? 'gray' : status === 'partial' ? 'amber' : '';
  return `<span class="tag ${cls}">${label}</span>`;
}
function timeText(value) {
  if (!value) return '—';
  return String(value).replace('T', ' ').replace(/(?:\.\d+)?\+00:00$/, '').slice(0, 16);
}
function latestTime(source = {}) {
  const values = [source.attachedAt, source.uploadedAt, source.parsedAt, ...(source.files || []).flatMap(file => [file.uploadedAt, file.parsedAt])];
  return values.filter(Boolean).sort().at(-1) || '';
}
function sourceName(value) {
  return String(value || '').split('/').map(item => SOURCE_NAMES[item] || item).join(' / ');
}
function matchTitle(match = {}) {
  return [match.date || '日期待定', match.session || '日常训练', match.opponent ? `vs ${match.opponent}` : '对手待定'].join(' · ');
}
function heading(title, subtitle, extra = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${extra}</div>`;
}
function sourceRows(channel) {
  const status = channel.sourceStatus || {};
  const sources = channel.sources || {};
  return ['official', 'camp', 'screenshot', 'video', 'table', 'replay'].map(key => {
    const source = key==='official' ? channel.official || {} : key==='camp' ? channel.sources?.camp || {} : sources[key] || {};
    const count = (status.counts || {})[key] || 0;
    const required = (status.required || {})[key] || 0;
    return `<tr><td><strong>${SOURCE_LABELS[key]}</strong><div class="helper">${SOURCE_HINTS[key]}</div></td>
      <td>${required?`${count} / ${required}`:`${count}（选填）`}${key === 'screenshot' ? ' 张' : key === 'official' ? ' 条' : ' 份'}</td>
      <td>${statusTag((status.statuses || {})[key])}</td>
      <td>${timeText(latestTime(source))}</td>
      <td>${timeText(source.parsedAt || latestTime(source))}</td>
      <td>${source.summary?.warnings?.length ? `<span class="tag amber">${source.summary.warnings.length} 条</span>` : '—'}</td></tr>`;
  }).join('');
}
function missingText(channel) {
  const missing = channel.draft?.missing || [];
  return missing.length ? missing.map(item => `${item.label} ${item.missing}/10`).join(' · ') : '核心字段齐全';
}
function draftInput(player, key, value, type = 'text') {
  return `<input class="channel-draft-input" data-draft-side="${esc(player.side)}" data-draft-slot="${player.slot}" data-draft-field="${key}" type="${type}" value="${esc(value ?? '')}"${type === 'number' ? ' inputmode="decimal"' : ''}>`;
}
function draftRows(channel) {
  const players = channel.draft?.players || [];
  return players.map(player => {
    const fields = player.fields || {};
    const conflict = (player.conflicts || []).length;
    const source = player.heroSource || [...new Set(Object.values(fields).map(field => field.source).filter(Boolean))].join('/');
    const status = player.heroStatus && player.heroStatus !== 'exact' ? ` <span class="tag amber">${esc(HERO_STATUS[player.heroStatus] || player.heroStatus)}</span>` : '';
    return `<tr><td>${SIDE[player.side] || '?'}${(player.slot ?? 0) + 1}</td>
      <td>${esc(player.nickname || '—')}</td>
      <td>${draftInput(player, 'hero', player.hero)}${status}</td>
      <td>${draftInput(player, 'kills', fields.kills?.value, 'number')} / ${draftInput(player, 'deaths', fields.deaths?.value, 'number')} / ${draftInput(player, 'assists', fields.assists?.value, 'number')}</td>
      <td>${draftInput(player, 'gold', fields.gold?.value, 'number')}</td>
      <td>${draftInput(player, 'damage', fields.damage?.value, 'number')}</td>
      <td>${draftInput(player, 'taken', fields.taken?.value, 'number')}</td>
      <td>${draftInput(player, 'participation', fields.participation?.value, 'number')}</td>
      <td>${draftInput(player, 'rating', fields.rating?.value, 'number')}</td>
      <td>${esc(sourceName(source) || '—')}${conflict ? ' <span class="tag amber">冲突</span>' : ''}</td></tr>`;
  }).join('');
}
function logDetail(item) {
  const detail = item.detail || {};
  if (detail.changes?.length) {
    return detail.changes.slice(0, 4).map(change =>
      `${SIDE[change.side] || '?'}${(change.slot ?? 0) + 1} ${FIELD_LABELS[change.field] || change.field}: ${num(change.before)} → ${num(change.after)}`).join('；')
      + (detail.changes.length > 4 ? `；另 ${detail.changes.length - 4} 处` : '');
  }
  if (detail.file) return detail.file;
  if (detail.replayId) return `回放 ${detail.replayId.slice(0, 12)}`;
  if (detail.officialId) return `官方回放 ${detail.officialId}`;
  if (detail.imageIds) return `${detail.imageIds.length} 张截图`;
  return '';
}
function logRows(channel) {
  return (channel.changeLog || []).slice().reverse().map(item =>
    `<div class="channel-log"><span>${timeText(item.at)}</span><strong>${esc(ACTION_NAMES[item.action] || item.action)}</strong><small>${esc(item.actor || 'local')}</small><em>${esc(logDetail(item))}</em></div>`).join('');
}
function reviewBlock(channel) {
  const review = channel.review || {};
  return `<section class="panel section-gap"><div class="panel-header"><div><h2>人工审核</h2>
    <div class="panel-subtitle">审核人、时间、前后值都会写入修改日志</div></div>${review.status === 'reviewed' ? `<span class="tag">已审核 · ${esc(review.reviewedBy)}</span>` : '<span class="tag amber">待审核</span>'}</div>
    <div class="form-section"><div class="form-grid"><label class="field">复核人<input id="channel-reviewer" value="${esc(review.reviewedBy || '')}" placeholder="例如：教练甲"></label>
    <label class="field">审核备注<input id="channel-review-notes" value="${esc(review.notes || '')}" placeholder="可选"></label></div>
    ${!channel.sourceStatus?.complete?`<div class="notice collection-required-warning">审核门槛未满足：${esc((channel.sourceStatus?.missing||['先关联本局营地回放链接，再导入营地十人面板，或补齐七张截图与一段录屏']).join('；'))}。表格与回放文件始终选填。</div>`:''}
    <div class="helper">审核时间：${timeText(review.reviewedAt)} · 审核完成后才能保存本局数据。</div>
    <div class="channel-actions"><button class="button secondary" id="channel-review" ${channel.sourceStatus?.complete?'':'disabled'}>完成审核</button>
    <button class="button" id="channel-save" ${review.status === 'reviewed' && channel.sourceStatus?.complete ? '' : 'disabled'}>保存本局数据</button>
    ${channel.saved?.status === 'saved' ? `<a class="button ghost" href="#match/${encodeURIComponent(channel.saved.bundleKey || 'channel-' + channel.id)}">开始本局复盘 →</a><span class="helper">已保存 ${timeText(channel.saved.savedAt)}</span>` : ''}</div></div></section>`;
}

function officialBlock(channel) {
  const official = channel.official;
  if (!official) return '';
  const match = official.match || {};
  const teams = (match.teams || []).map(team => team.name).filter(Boolean);
  const gold = match.teamGold || {};
  const kind = {personal: '个人回放', kpl: 'KPL', beta: 'Beta'}[official.kind] || official.kind || '官方';
  const win = String(match.winCamp) === '1' ? '蓝方胜' : String(match.winCamp) === '2' ? '红方胜' : '胜负未读';
    const banNames = channel.sources?.camp?.banNames || {};
    const banText = ['blue', 'red'].map(camp => (banNames[camp] || []).length
      ? `${camp === 'blue' ? '蓝方禁' : '红方禁'}：${banNames[camp].join('、')}` : '').filter(Boolean).join(' · ');
    return `<div class="notice">已关联官方回放：${esc(kind)}${teams.length ? ' · ' + esc(teams.join(' vs ')) : ''} · ${esc(win)}</div>
    <div class="replay-facts">
      <div><span>团队金币</span><strong>${num(gold.blue)} : ${num(gold.red)}</strong></div>
      <div><span>金币点</span><strong>${num(match.goldPoints)} 个 · 约30秒</strong></div>
      <div><span>事件</span><strong>${num(match.keyEvents)} + ${num(match.extendedEvents)}</strong></div>
      <div><span>逐秒位置</span><strong>${official.positions?.perSecond ? '有' : '无'} · ${num(official.positions?.pointsPerPlayer)} 点/人</strong></div>
    </div>
    ${banText ? `<p class="helper">禁用：${esc(banText)}</p>` : ''}
    <div class="channel-actions"><button class="button secondary" id="camp-detail-import">导入营地十人面板（BP / 数值）</button>
      <span class="helper">${(channel.sources?.camp?.players || []).length ? '已导入，草稿与冲突已更新' : '把本机同步的营地详情映射进草稿；数值来源标“营地”，与截图互校'}</span></div>
    <div class="helper">官方金币是约30秒一个点；1秒只有位置，没有1秒金币。终局字段仍以截图/回放为准。</div>`;
}

export async function renderChannels(container, {api, toast, isCurrent}) {
  let data = {channels: []};
  let busy = false;
  const batch = {text: '', items: [], created: new Set(), summary: ''};
  const camp = {auth: {}, config: {players: []}, job: {}, detailsCount: 0,
                qrTask: null, authStatus: '', syncStatus: '', authTimer: null, syncTimer: null};
  const load = async () => { data = await api('/api/channels'); };
  const loadCamp = async () => {
    try {
      const status = await api('/api/camp/sync');
      camp.auth = status.auth || {};
      camp.config = status.config || {players: []};
      camp.job = {running: !!status.running, result: status.result, error: status.error};
      camp.detailsCount = status.detailsCount || 0;
    } catch { camp.auth = {authorized: false}; }
  };
  const draw = () => {
    if (!isCurrent()) return;
    const channels = data.channels || [];
    container.innerHTML = heading('采集通道', '一局一个通道：唯一必采是本局营地回放链接；营地自动同步导入十人面板，或按兜底路径补齐七图与录屏，任一齐备即可审核。',
      '<span class="tag amber">采集 · 审核 · 入库</span>') + `
      <section class="panel"><div class="panel-header"><div><h2>新建一局通道</h2><div class="panel-subtitle">先建局并关联营地链接，再导入营地十人面板；表格与回放文件选填，七图与录屏可作为兜底</div></div></div>
      <div class="form-section"><div class="form-grid"><label class="field">比赛日期<input id="channel-date" type="date"></label>
      <label class="field">对手<input id="channel-opponent" placeholder="例如：周三训练对手"></label>
      <label class="field">训练分组<input id="channel-session" placeholder="例如：晚训 · 第 1 组"></label>
      <label class="field">版本<input id="channel-version" placeholder="例如：S42"></label></div>
      <div class="channel-actions"><button class="button" id="channel-create">创建采集通道</button></div></div></section>
      ${campPanel()}
      <section class="panel section-gap"><div class="panel-header"><div><h2>批量导入营地分享链接</h2><div class="panel-subtitle">选手在营地分享到微信后，把复制出来的链接粘到这里；cu.qq.com 短链和 camp.qq.com 网页链接都可以，一行一条</div></div>
      <span class="tag gray">一次最多 20 条</span></div>
      <div class="form-section">${renderCollectionGuide('camp-sync')}
      <textarea id="camp-batch-text" rows="5" placeholder="https://cu.qq.com/xxxxx&#10;https://camp.qq.com/h5/webdist/mp-redirect/index.html?...">${esc(batch.text)}</textarea>
      <div class="channel-actions"><button class="button" id="camp-batch-run">解析并导入</button><span id="camp-batch-status" class="helper"></span></div>
      <div id="camp-batch-result">${batchRows()}</div>
      </div></section>
      <section class="panel section-gap"><div class="panel-header"><h2>本机通道</h2><span class="tag gray">${channels.length} 局</span></div>
      ${channels.length ? `<div class="table-wrap"><table><thead><tr><th>比赛</th><th>来源状态</th><th>草稿缺失</th><th>审核 / 保存</th><th>更新时间</th><th></th></tr></thead><tbody>
      ${channels.map(channel => `<tr><td><strong>${esc(matchTitle(channel.match))}</strong><div class="helper">${esc(channel.id.slice(0, 12))}</div></td>
        <td><div class="channel-source-tags">${Object.entries(channel.sourceStatus?.statuses || {}).map(([key, status]) => `<span class="tag ${status === 'missing' ? 'gray' : status === 'partial' ? 'amber' : ''}">${SOURCE_LABELS[key]} ${STATUS_LABELS[status] || status}</span>`).join('')}</div></td>
        <td>${esc(missingText(channel))}</td>
        <td>${channel.review?.status === 'reviewed' ? `<span class="tag">已审核 · ${esc(channel.review.reviewedBy)}</span>` : '<span class="tag amber">待审核</span>'}
          ${channel.saved?.status === 'saved' ? '<span class="tag">已保存</span>' : ''}</td>
        <td>${timeText(channel.updatedAt)}</td><td><a class="button ghost" href="#channel/${esc(channel.id)}">打开通道 →</a></td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty"><strong>还没有采集通道</strong>先创建一局，再把表格、录像 OCR 报告、截图组和回放文件挂进来。</div>'}</section>`;
    container.querySelector('#channel-create').onclick = create;
    const batchText = container.querySelector('#camp-batch-text');
    if (batchText) {
      batchText.oninput = () => { batch.text = batchText.value; };
      container.querySelector('#camp-batch-run').onclick = runBatch;
      container.querySelectorAll('[data-camp-create]').forEach(button => {
        button.onclick = () => createFromCampItem(button.dataset.campCreate, button);
      });
    }
    const campQr = container.querySelector('#camp-auth-qr');
    if (campQr) campQr.onclick = startCampAuth;
    const campCancel = container.querySelector('#camp-auth-cancel');
    if (campCancel) campCancel.onclick = cancelCampAuth;
    const campClear = container.querySelector('#camp-auth-clear');
    if (campClear) campClear.onclick = async () => {
      stopCampAuth();
      camp.qrTask = null;
      camp.authStatus = '';
      try { await api('/api/camp/auth/clear', 'POST'); await loadCamp(); draw(); toast('凭证已删除'); }
      catch (error) { toast(error.message, true); }
    };
    const campAdd = container.querySelector('#camp-player-add');
    if (campAdd) campAdd.onclick = addCampPlayer;
    container.querySelectorAll('[data-camp-share]').forEach(button => {
      button.onclick = () => addCampPlayerById(button.dataset.campShare);
    });
    container.querySelectorAll('[data-camp-remove]').forEach(button => {
      button.onclick = () => removeCampPlayer(button.dataset.campRemove);
    });
    const campSyncRun = container.querySelector('#camp-sync-run');
    if (campSyncRun) campSyncRun.onclick = runCampSync;
    const campSelect = container.querySelector('#camp-player-select');
    if (campSelect) campSelect.onchange = () => {
      camp.selectedPlayer = campSelect.value;
      camp.list = [];
      camp.checked = {};
      camp.checkedCount = 0;
      draw();
    };
    const campListFetch = container.querySelector('#camp-list-fetch');
    if (campListFetch) campListFetch.onclick = fetchCampList;
    const campListAll = container.querySelector('#camp-list-all');
    if (campListAll) campListAll.onchange = () => {
      for (const item of camp.list || []) {
        if (item.imported) continue;
        if (campListAll.checked) camp.checked[item.gameSeq] = true;
        else delete camp.checked[item.gameSeq];
      }
      camp.checkedCount = Object.keys(camp.checked).length;
      draw();
    };
    container.querySelectorAll('[data-list-check]').forEach(checkbox => {
      checkbox.onchange = () => toggleListCheck(checkbox.dataset.listCheck, checkbox.checked);
    });
  };
  function batchRows() {
    if (!batch.items.length) return '';
    const rows = batch.items.map(item => {
      if (!item.ok) return `<tr><td colspan="6"><span class="tag amber">失败</span> ${esc(item.error || '')} <code>${esc(item.url.slice(0, 90))}</code></td></tr>`;
      const win = String(item.winCamp) === '1' ? '蓝方胜' : String(item.winCamp) === '2' ? '红方胜' : '—';
      const mode = item.battleType ? (CAMP_BATTLE_MODES[item.battleType] || `类型 ${item.battleType}`) : '—';
      const gold = item.teamGold || {};
      const created = batch.created.has(item.id);
      return `<tr><td><strong>${esc(item.gameSeq || '—')}</strong><div class="helper">${item.cached ? '本地缓存' : '新导入'}</div></td>
        <td>${esc(mode)}${item.pvpType ? ` <span class="tag gray">pvp ${esc(item.pvpType)}</span>` : ''}</td>
        <td>${win}</td>
        <td>${clock(item.durationSec)}</td>
        <td>${num(gold.blue)} : ${num(gold.red)}</td>
        <td>${created ? '<span class="tag">已建局</span>' : `<button class="button ghost" data-camp-create="${esc(item.id)}">创建本局</button>`}
          ${item.shareUserId ? `<button class="button ghost" data-camp-share="${esc(item.shareUserId)}" title="把分享者的营地 ID 加入同步清单">清单+</button>` : ''}</td></tr>`;
    }).join('');
    return `<div class="table-wrap"><table><thead><tr><th>对局</th><th>模式</th><th>胜方</th><th>时长</th><th>团队金币</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      ${batch.summary ? `<div class="helper">${esc(batch.summary)} · 导入后打开本局通道，补日期、对手，并按需导入营地十人面板。</div>` : ''}`;
  }
  async function runBatch() {
    if (busy) return;
    busy = true;
    const status = container.querySelector('#camp-batch-status');
    if (status) status.textContent = '解析中：短链展开并请求营地接口，每条约 1–2 秒…';
    try {
      const result = await api('/api/official/replays/batch', 'POST', {text: batch.text});
      batch.items = result.items || [];
      batch.summary = `共 ${result.total} 条：成功 ${result.imported}，失败 ${result.failed}`;
      if (status) status.textContent = '';
    } catch (error) {
      if (status) status.textContent = `批量导入失败：${error.message || error}`;
    }
    busy = false;
    draw();
  }
  async function createFromCampItem(itemId, button) {
    if (busy || batch.created.has(itemId)) return;
    busy = true;
    button.disabled = true;
    button.textContent = '创建中…';
    try {
      const channel = await api('/api/channels', 'POST', {'match': {
        date: new Date().toISOString().slice(0, 10), session: '营地导入'}});
      await api(`/api/channels/${channel.id}/official`, 'POST', {officialId: itemId});
      batch.created.add(itemId);
      await load();
    } catch (error) {
      button.disabled = false;
      button.textContent = '重试';
      if (toast) toast(`建局失败：${error.message || error}`, true);
    }
    busy = false;
    draw();
  }
  async function create() {
    if (busy) return;
    busy = true;
    try {
      const channel = await api('/api/channels', 'POST', {'match': {
        date: container.querySelector('#channel-date').value,
        opponent: container.querySelector('#channel-opponent').value,
        session: container.querySelector('#channel-session').value,
        version: container.querySelector('#channel-version').value,
      }});
      location.hash = '#channel/' + encodeURIComponent(channel.id);
    } catch (error) { toast(error.message, true); }
    finally { busy = false; }
  }
  function campPanel() {
    const auth = camp.auth || {};
    const players = camp.config?.players || [];
    const running = camp.job?.running;
    const rows = players.map(player => `<tr><td><strong>${esc(player.nickname || '未命名')}</strong><div class="helper">${esc(player.campUserId)}</div></td>
      <td><button class="button ghost" data-camp-remove="${esc(player.campUserId)}">移除</button></td></tr>`).join('');
    const syncResult = camp.job?.result?.players || [];
    const resultRows = syncResult.map(item => item.ok
      ? `<tr><td>${esc(item.nickname || item.campUserId)}</td><td>新局 ${num(item.summary?.fetched)} · 入库 ${num(item.summary?.saved)} · 已知 ${num(item.summary?.cached)}${item.summary?.failed ? ` · 失败 ${item.summary.failed}` : ''}</td></tr>`
      : `<tr><td>${esc(item.nickname || item.campUserId)}</td><td><span class="tag amber">失败</span> ${esc(item.error || '')}</td></tr>`);
    const autoAttached = camp.job?.result?.autoAttached || [];
    const authExpiresNote = auth.authorized
      ? `授权于 ${esc(auth.loginAt || '—')}；营地未提供有效期，接口报登录态失效时此处会提示重新扫码。`
      : '还没有授权。扫码后即可按选手清单自动同步。';
    return `<section class="panel section-gap"><div class="panel-header"><div><h2>营地自动同步</h2>
      <div class="panel-subtitle">教练号授权 → 选选手 → 勾选要拉取的对局 → 一键入库；当前本机已有 ${num(camp.detailsCount)} 份对局详情</div></div>
      <span class="tag ${auth.authorized ? '' : 'amber'}">${auth.authorized ? '已授权' : '未授权'}</span></div>
      <div class="form-section">
      ${camp.qrTask ? `<div class="recording-upload" style="grid-template-columns:auto minmax(0,1fr)">
        <img class="camp-qr" style="width:180px;border:1px solid var(--line);border-radius:8px" src="data:image/png;base64,${esc(camp.qrTask.qrcodeBase64)}" alt="扫码授权二维码">
        <div><p class="helper">用<strong>打过训练赛的教练微信</strong>扫码，并在手机上确认。</p>
        <p class="helper" id="camp-auth-status">${esc(camp.authStatus || '等待扫码…')}</p>
        <button class="button ghost" id="camp-auth-cancel" style="margin-top:8px">取消扫码</button></div></div>`
      : `<div class="recording-upload" style="grid-template-columns:auto minmax(0,1fr)">
        <div class="recording-engine ${auth.authorized ? 'ok' : 'bad'}" style="padding:14px 18px"><span>教练授权</span><strong>${auth.authorized ? esc(auth.nickname || auth.userId) : '未授权'}</strong><small>${esc(authExpiresNote)}</small></div>
        <div><div class="channel-actions"><button class="button secondary" id="camp-auth-qr">${auth.authorized ? '重新扫码授权' : '扫码授权'}</button>
        ${auth.authorized ? '<button class="button ghost" id="camp-auth-clear">删除凭证</button>' : ''}</div>
        <p class="helper">授权一次长期使用；二维码 3 分钟有效，过期会自动刷新。</p></div></div>`}
      <div class="form-grid">
        <label class="field">选择选手<select id="camp-player-select"><option value="">${players.length ? '选择选手' : '尚无选手（先在下方加入清单）'}</option>${players.map(player => `<option value="${esc(player.campUserId)}" ${camp.selectedPlayer === player.campUserId ? 'selected' : ''}>${esc(player.nickname || player.campUserId)}</option>`).join('')}</select></label>
        <button class="button secondary" id="camp-list-fetch" ${!auth.authorized || !camp.selectedPlayer || camp.listLoading ? 'disabled' : ''}>${camp.listLoading ? '获取中…' : '获取对局列表'}</button>
      </div>
      <label class="field">选手昵称 / 营地 ID / 分享链接<input id="camp-player-nickname" placeholder="昵称可选" style="max-width:180px"><input id="camp-player-id" placeholder="userId= 后的数字，或直接粘贴 cu.qq.com/… 链接"><button class="button ghost" id="camp-player-add" style="margin-top:8px">加入清单</button></label>
      ${players.length ? `<div class="table-wrap"><table><thead><tr><th>选手</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
        : '<div class="empty">还没有选手。把选手分享链接里 <code>userId=</code> 的数字或整条链接填进来；一个稳定上场的选手即可覆盖全队每局。</div>'}
      <div class="channel-actions"><button class="button" id="camp-sync-run" ${!camp.checkedCount ? 'disabled' : ''}>${running ? '拉取进行中…' : `拉取选中的 ${camp.checkedCount || 0} 局`}</button>
        <span id="camp-sync-status" class="helper">${esc(camp.syncStatus || (running ? '正在拉取，每局约 2 秒…' : ''))}</span></div>
      ${resultRows.length ? `<div class="table-wrap"><table><thead><tr><th>选手</th><th>结果</th></tr></thead><tbody>${resultRows.join('')}</tbody></table></div>` : ''}
      ${(camp.list || []).length ? `<div class="table-wrap"><table><thead><tr><th><input type="checkbox" id="camp-list-all" ${camp.list.every(item => camp.checked[item.gameSeq]) ? 'checked' : ''}></th><th>对局</th><th>模式</th><th>时间</th><th>KDA</th><th>胜负</th><th>状态</th></tr></thead><tbody>
        ${camp.list.map(item => {
          const win = String(item.winCamp) === '1' ? '蓝方胜' : String(item.winCamp) === '2' ? '红方胜' : '—';
          const kda = [item.killcnt, item.deadcnt, item.assistcnt].filter(v => v != null).join('/');
          return `<tr><td><input type="checkbox" data-list-check="${esc(item.gameSeq)}" ${camp.checked[item.gameSeq] ? 'checked' : ''} ${item.imported ? 'disabled' : ''}></td>
            <td><strong>${esc(item.gameSeq)}</strong></td><td>${esc(item.mapName || '—')}</td><td>${esc(item.gametime || '—')}</td>
            <td>${esc(kda || '—')}</td><td>${win}</td>
            <td>${item.imported ? '<span class="tag">已入库</span>' : '<span class="tag amber">待拉取</span>'}</td></tr>`;
        }).join('')}</tbody></table></div>
        ${camp.listHasMore ? '<p class="helper">还有更早的对局未显示；如需拉取更早历史，用 tools/camp_sync.py --reset 重拉。</p>' : ''}` : ''}
      ${(camp.details || []).length ? `<details class="recording-check"><summary>已入库对局（${camp.details.length}）</summary>
        <div class="table-wrap"><table><thead><tr><th>对局</th><th>模式</th><th>时间</th><th>KDA</th><th>胜负</th><th>通道</th></tr></thead><tbody>
        ${(camp.details || []).map(item => {
          const win = String(item.winCamp) === '1' ? '蓝方胜' : String(item.winCamp) === '2' ? '红方胜' : '—';
          const kda = (item.kda || []).filter(v => v != null).join('/');
          return `<tr><td><strong>${esc(item.gameSeq)}</strong></td><td>${esc(item.mapName || '—')}</td>
            <td>${esc(item.gametime || '—')}</td><td>${esc(kda || '—')}</td><td>${win}</td>
            <td>${item.channelId ? `<a class="button ghost" href="#channel/${esc(item.channelId)}">打开通道 →</a>` : '<span class="tag gray">未建局</span>'}</td></tr>`;
        }).join('')}</tbody></table></div></details>` : ''}
      ${camp.job?.error ? `<div class="notice">${esc(camp.job.error)}</div>` : ''}
      ${(autoAttached || []).length ? `<div class="notice">已自动挂载 ${autoAttached.length} 个通道的营地十人面板。</div>` : ''}
      </div></section>`;
  }
  function stopCampTimers() {
    clearInterval(camp.authTimer);
    clearInterval(camp.syncTimer);
    camp.authTimer = camp.syncTimer = null;
  }
  function stopCampAuth() {
    clearInterval(camp.authTimer);
    camp.authTimer = null;
    camp.authFailures = 0;
  }
  function showAuthStatus(message) {
    camp.authStatus = message;
    const el = container.querySelector('#camp-auth-status');
    if (el) el.textContent = message;
  }
  async function cancelCampAuth() {
    const taskId = camp.qrTask?.taskId;
    stopCampAuth();
    camp.qrTask = null;
    camp.authStatus = '';
    if (taskId) {
      try { await api('/api/camp/auth/cancel?taskId=' + encodeURIComponent(taskId), 'POST'); }
      catch { /* 会话会自行过期，不阻塞退出 */ }
    }
    draw();
  }
  async function startCampAuth() {
    if (busy || camp.authTimer) return;
    busy = true;
    stopCampAuth();
    try {
      camp.qrTask = await api('/api/camp/auth/qr', 'POST');
      camp.authStatus = '等待扫码…';
      camp.qrRefreshes = 0;
      draw();
      const taskId = camp.qrTask.taskId;
      camp.authTimer = setInterval(async () => {
        if (!isCurrent() || !camp.qrTask || camp.qrTask.taskId !== taskId) {
          stopCampAuth();
          return;
        }
        let result;
        try {
          result = await api('/api/camp/auth/poll?taskId=' + encodeURIComponent(taskId));
        } catch (error) {
          camp.authFailures = (camp.authFailures || 0) + 1;
          showAuthStatus(`连接中断（${camp.authFailures}/3）：${error.message}`);
          if (camp.authFailures >= 3) {
            stopCampAuth();
            camp.qrTask = null;
            camp.authStatus = '';
            draw();
            toast('授权轮询中断，请重新扫码', true);
          }
          return;
        }
        camp.authFailures = 0;
        if (result.status === 'scanned') { showAuthStatus('已扫码，等待手机上确认…'); return; }
        if (result.status === 'waiting') return;
        if (result.status === 'success') {
          stopCampAuth();
          camp.qrTask = null;
          camp.authStatus = '';
          toast(`已授权：${result.nickname || result.userId}`);
          await loadCamp(); draw();
          return;
        }
        if (result.status === 'error') {
          stopCampAuth();
          camp.qrTask = null;
          camp.authStatus = '';
          draw();
          toast(result.message || '授权确认失败，请重新扫码', true);
          return;
        }
        if (result.status === 'expired' || result.status === 'canceled') {
          stopCampAuth();
          if (result.status === 'canceled') {
            camp.authStatus = '已在手机上取消，可重新扫码。';
            camp.qrTask = null;
            draw();
            return;
          }
          // 二维码过期自动刷新（最多 3 次，避免无人扫码时空转）
          camp.qrRefreshes = (camp.qrRefreshes || 0) + 1;
          if (camp.qrRefreshes <= 3) {
            camp.authStatus = '二维码已过期，正在自动刷新…';
            camp.qrTask = null;
            busy = false;
            await startCampAuth();
            return;
          }
          camp.authStatus = '二维码已多次过期。准备好后再点「扫码授权」。';
          camp.qrTask = null;
          draw();
        }
      }, 2500);
    } catch (error) { toast(error.message, true); }
    finally { busy = false; }
  }
  async function fetchCampList() {
    if (!camp.selectedPlayer) { toast('请先选择选手', true); return; }
    camp.listLoading = true;
    camp.list = [];
    camp.checked = {};
    draw();
    try {
      const player = (camp.config?.players || []).find(p => p.campUserId === camp.selectedPlayer) || {};
      const result = await api('/api/camp/list', 'POST',
        {campUserId: camp.selectedPlayer, lastTime: 0});
      camp.list = result.entries || [];
      camp.listHasMore = !!result.hasMore;
      for (const item of camp.list) if (!item.imported) camp.checked[item.gameSeq] = true;
      camp.checkedCount = Object.keys(camp.checked).length;
      camp.listLoading = false;
      if (result.gaming) toast('该选手有一局正在进行中，列表不含对局中的比赛');
      draw();
    } catch (error) {
      camp.listLoading = false;
      camp.list = [];
      draw();
      if (String(error.message).includes('隐藏')) toast('选手战绩对教练不可见：请其把教练加入白名单或恢复公开', true);
      else toast(error.message, true);
    }
  }
  function toggleListCheck(gameSeq, checked) {
    if (checked) camp.checked[gameSeq] = true;
    else delete camp.checked[gameSeq];
    camp.checkedCount = Object.keys(camp.checked).length;
    const button = container.querySelector('#camp-sync-run');
    if (button) button.textContent = `拉取选中的 ${camp.checkedCount} 局`;
  }
  async function addCampPlayer() {
    const nickname = container.querySelector('#camp-player-nickname')?.value.trim() || '';
    const raw = container.querySelector('#camp-player-id')?.value.trim() || '';
    if (!raw) { toast('请填营地 ID，或直接粘贴选手的分享链接', true); return; }
    let campUserId = raw;
    if (raw.includes('://') || raw.includes('cu.qq.com')) {
      try {
        const resolved = await api('/api/camp/resolve', 'POST', {url: raw});
        campUserId = resolved.userId;
        camp.syncStatus = `识别到营地 ID ${campUserId}${resolved.gameSeq ? `（对局 ${resolved.gameSeq}）` : ''}`;
      } catch (error) { toast(error.message, true); return; }
    }
    if (!/^\d{5,15}$/.test(campUserId)) { toast('营地 ID 是 5–15 位数字，或直接粘贴分享链接', true); return; }
    const players = (camp.config?.players || []).filter(p => p.campUserId !== campUserId);
    players.push({nickname: nickname || `选手 ${campUserId.slice(-4)}`, campUserId});
    try {
      camp.config = await api('/api/camp/config', 'POST', {players});
      draw(); toast('已加入选手清单');
    } catch (error) { toast(error.message, true); }
  }
  async function addCampPlayerById(campUserId) {
    const players = (camp.config?.players || []).filter(p => p.campUserId !== campUserId);
    players.push({nickname: `选手 ${campUserId.slice(-4)}`, campUserId});
    try {
      camp.config = await api('/api/camp/config', 'POST', {players});
      draw(); toast(`营地 ID ${campUserId} 已加入同步清单`);
    } catch (error) { toast(error.message, true); }
  }
  async function removeCampPlayer(campUserId) {
    const players = (camp.config?.players || []).filter(p => p.campUserId !== campUserId);
    try {
      camp.config = await api('/api/camp/config', 'POST', {players});
      draw();
    } catch (error) { toast(error.message, true); }
  }
  async function runCampSync() {
    if (busy) return;
    const entries = (camp.list || []).filter(item => camp.checked[item.gameSeq]);
    if (!entries.length) { toast('请先勾选要拉取的对局', true); return; }
    busy = true;
    camp.syncStatus = `已启动，正在拉取选中的 ${entries.length} 局…`;
    try {
      const player = (camp.config?.players || []).find(p => p.campUserId === camp.selectedPlayer) || {};
      await api('/api/camp/sync', 'POST', {campUserId: camp.selectedPlayer,
        nickname: player.nickname || '', entries});
      clearInterval(camp.syncTimer);
      camp.syncTimer = setInterval(async () => {
        try {
          const status = await api('/api/camp/sync');
          camp.job = {running: !!status.running, result: status.result, error: status.error};
          camp.detailsCount = status.detailsCount || 0;
          const statusEl = container.querySelector('#camp-sync-status');
          if (status.running && statusEl) status.textContent = `正在拉取，本机已有 ${camp.detailsCount} 份对局详情…`;
          if (!status.running) {
            clearInterval(camp.syncTimer);
            camp.syncTimer = null;
            busy = false;
            camp.syncStatus = '';
            camp.checked = {};
            camp.checkedCount = 0;
            const failed = (status.result?.players || []).filter(item => !item.ok).length;
            if (failed) toast(`同步完成，但有失败项，详见面板`, true);
            await loadCamp(); draw();
          }
        } catch { /* keep polling */ }
      }, 3000);
      draw();
    } catch (error) {
      busy = false;
      camp.syncStatus = '';
      if (String(error.message).includes('登录态')) {
        camp.auth = {authorized: false};
        toast('登录态已失效，请重新扫码授权', true);
      } else toast(error.message, true);
      draw();
    }
  }
  container.innerHTML = '<div class="loading">正在读取本机采集通道…</div>';
  try { await load(); await loadCamp(); draw(); } catch (error) { if (isCurrent()) container.innerHTML = '<div class="notice">采集通道读取失败。</div>'; toast(error.message, true); }
}

export async function renderChannel(container, {api, toast, isCurrent, id}) {
  let channel = null, groups = [], replays = [];
  let busy = false;
  const load = async () => {
    const [channelValue, postgame, replayValue] = await Promise.all([
      api('/api/channels/' + encodeURIComponent(id)), api('/api/postgame/images'), api('/api/replays')]);
    channel = channelValue;
    groups = postgame.groups || [];
    replays = replayValue.replays || [];
  };
  const draw = () => {
    if (!isCurrent()) return;
    const status = channel.sourceStatus || {};
    const draft = channel.draft || {};
    const groupOptions = groups.map((group, index) => `<option value="${index}">${esc(matchTitle(group.match))} · ${group.pages?.length || 0} 页 · ${group.players?.length || 0} 人</option>`).join('');
    const replayOptions = replays.map(replay => `<option value="${esc(replay.id)}">${esc(replay.abcFileName)} · ${esc((replay.header?.versions || []).join('/'))}</option>`).join('');
    const replaySource = channel.sources.replay || {};
    const replayResult = replaySource.result || {};
    const winMvp = replayResult.winMvp || {};
    const loseMvp = (replayResult.loseMvp || [])[0] || {};
    const replayResultText = replayResult.winningCamp
      ? `${replayResult.winningCamp === 'blue' ? '蓝方' : '红方'}胜 · MVP ${winMvp.nickname || ''}${winMvp.hero ? '（' + winMvp.hero + '）' : ''}${winMvp.rating != null ? ' ' + Number(winMvp.rating).toFixed(2) : ''}${loseMvp.nickname ? ' · SVP ' + loseMvp.nickname : ''}`
      : '';
    container.innerHTML = `<a href="#channels" class="back-link">← 返回采集通道</a>` + heading(matchTitle(channel.match),
      '唯一必采：本局营地回放链接。审核门槛二选一：导入营地十人面板，或补齐七张截图与一段录屏；表格与回放文件选填。', `<span class="tag ${status.complete ? '' : 'amber'}">${status.complete ? '来源齐全' : '来源未齐'}</span>`) + `
      <section class="panel section-gap"><div class="panel-header"><div><h2>王者营地链接（唯一必采）</h2><div class="panel-subtitle">粘贴 camp.qq.com 回放链接，提取官方经济、事件和逐秒位置</div></div><span class="tag amber">唯一必采</span></div>
      <div class="form-section">${renderCollectionGuide('official')}${officialBlock(channel)}
      <div class="recording-upload" style="grid-template-columns:minmax(0,1fr) auto">
        <label class="field">营地回放链接<input id="channel-official-url" placeholder="https://camp.qq.com/h5/webdist/battle-replay/...?gameseq=..." autocomplete="off"></label>
        <button class="button secondary" id="attach-official">提取并关联</button>
      </div>
      <p class="helper">官方公开接口提供约30秒团队金币、秒级事件和1秒位置；没有1秒金币。提取结果只作为过程数据，不覆盖截图终局字段。</p></div></section>
      <section class="panel"><div class="panel-header"><h2>本局信息</h2><span class="helper">修改会写入修改日志</span></div>
      <div class="form-section"><div class="form-grid"><label class="field">日期<input id="meta-date" type="date" value="${esc(channel.match.date || '')}"></label>
      <label class="field">对手<input id="meta-opponent" value="${esc(channel.match.opponent || '')}"></label>
      <label class="field">训练分组<input id="meta-session" value="${esc(channel.match.session || '')}"></label>
      <label class="field">版本<input id="meta-version" value="${esc(channel.match.version || '')}"></label></div>
      <div class="channel-actions"><button class="button secondary" id="save-meta">保存本局信息</button><span class="helper">${channel.id}</span></div></div></section>
      ${bpEditorHtml(channel.match.bp||{})}
      <section class="panel section-gap"><div class="panel-header"><h2>来源状态</h2><span class="tag gray">${status.complete ? '审核门槛已满足' : '审核门槛未满足'}</span></div>
      <div class="table-wrap"><table><thead><tr><th>来源</th><th>已放入 / 需要</th><th>状态</th><th>最近上传</th><th>解析完成</th><th>提示</th></tr></thead><tbody>${sourceRows(channel)}</tbody></table></div></section>
      <div class="channel-grid">
        <section class="panel"><div class="panel-header"><h2>表格（选填）</h2><a class="text-link" href="/assets/collection-guide.html?section=table" target="_blank" rel="noopener">下载模板 / 字段示例 ↗</a></div><div class="form-section"><label class="mini-upload">＋ 放入赛训表<input id="channel-table" type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm" hidden></label><p class="helper">${channel.sources.table.summary ? `粒度 ${esc(channel.sources.table.summary.grain || '未识别')} · ${channel.sources.table.summary.rows || 0} 行 · ${channel.sources.table.summary.files || 0} 份` : '使用项目模板：一局十行、双方各五人；不接收聚合表。未知字段留空，冲突保留待核对。'}</p></div></section>
        <section class="panel"><div class="panel-header"><h2>录屏（兜底路径）</h2><a class="text-link" href="/assets/collection-guide.html?section=video" target="_blank" rel="noopener">起止位置 / 面板示例 ↗</a></div><div class="form-section"><a class="button secondary" href="#recordings">先上传完整视频 →</a><label class="mini-upload">＋ 关联识别后的 JSON 报告<input id="channel-video" type="file" accept=".json" hidden></label><p class="helper">${channel.sources.video.summary ? `${channel.sources.video.summary.files || 0}/1 份 · 英雄 ${channel.sources.video.summary.heroes || 0}` : '当前接收回放录屏 OCR 生成的 JSON 报告；一局只需一段完整视频对应的一份报告。'}</p></div></section>
        <section class="panel"><div class="panel-header"><h2>截图（兜底路径）</h2><a class="text-link" href="/assets/collection-guide.html?section=screenshots" target="_blank" rel="noopener">七张清单 / 示意图 ↗</a></div><div class="form-section"><select class="control" id="channel-shot-group"><option value="">${groups.length ? '选择截图组' : '尚无截图组'}</option>${groupOptions}</select><button class="button secondary" id="attach-shot" ${groups.length ? '' : 'disabled'}>关联截图组</button><p class="helper">${channel.sources.screenshot.summary ? `已关联 ${channel.sources.screenshot.imageIds?.length || 0} 张 · ${channel.sources.screenshot.summary.pageTypes?.join(' / ') || ''}` : '截图组提供终局 KDA、经济、输出、承伤、参团。'}</p></div></section>
        <section class="panel"><div class="panel-header"><h2>回放文件（选填）</h2><span class="helper">.abc / .ope</span></div><div class="form-section"><select class="control" id="channel-replay"><option value="">${replays.length ? '选择回放记录' : '尚无回放记录'}</option>${replayOptions}</select><button class="button secondary" id="attach-replay" ${replays.length ? '' : 'disabled'}>关联回放</button><p class="helper">${replaySource.summary ? `已关联 · 英雄块 ${replaySource.summary.blocks || 0}${replayResultText ? ' · ' + esc(replayResultText) : ''}${replaySource.summary.totalFrameNum ? ' · ' + num(replaySource.summary.totalFrameNum) + ' 帧' : ''}` : '回放补十人名单、胜负、MVP、评分和同局元数据；KDA/经济/输出/承伤/参团仍以截图/表格/录像为准。'}</p></div></section>
      </div>
      <section class="panel section-gap"><div class="panel-header"><div><h2>跨来源数据草稿</h2><div class="panel-subtitle">字段来源、冲突和缺失都保留；可直接修改</div></div><div class="channel-actions">${(() => { const count = (channel.draft?.players || []).filter(player => ['roster-candidate', 'roster-elimination'].includes(player.heroStatus)).length; return count ? `<span class="tag">名单比对 ${count}</span>` : ''; })()}<span class="tag gray">${missingText(channel)}</span><button class="button secondary" id="save-draft-edits">保存草稿修订</button></div></div>
      <div class="table-wrap"><table class="channel-draft-table"><thead><tr><th>位置</th><th>昵称</th><th>英雄</th><th>K / D / A</th><th>经济</th><th>输出</th><th>承伤</th><th>参团</th><th>评分</th><th>来源</th></tr></thead><tbody>${draftRows(channel)}</tbody></table></div>
      ${(draft.conflicts || []).length ? `<div class="notice">冲突 ${draft.conflicts.length} 处：${draft.conflicts.map(item => `${item.side}${item.slot + 1} ${FIELD_LABELS[item.field] || item.field} 截图 ${item.screenshot ?? '—'} / 表格 ${item.table ?? '—'}${item.camp != null ? ' / 营地 ' + item.camp : ''}`).join('；')}</div>` : ''}</section>
      ${reviewBlock(channel)}
      <section class="panel section-gap"><div class="panel-header"><h2>修改日志</h2><span class="tag gray">${(channel.changeLog || []).length} 条</span></div><div class="form-section">${logRows(channel) || '<div class="empty">还没有修改记录。</div>'}</div></section>`;
    bind();
  };
  function bind() {
    bindBpEditor(container, async bp=>{
      channel=await api('/api/channels/'+encodeURIComponent(id),'PATCH',{match:{bp}});
      if(channel.saved?.bundleKey)await api('/api/studio/bp/'+encodeURIComponent(channel.saved.bundleKey),'POST',{bp});
      await fetch('/api/analysis/reload',{method:'POST'});
      window.dispatchEvent(new Event('platform-data-changed'));
    },toast,{channelId:id});
    container.querySelector('#save-meta').onclick = async () => {
      try {
        channel = await api('/api/channels/' + encodeURIComponent(id), 'PATCH', {match: {
          date: container.querySelector('#meta-date').value,
          opponent: container.querySelector('#meta-opponent').value,
          session: container.querySelector('#meta-session').value,
          version: container.querySelector('#meta-version').value,
        }});
        draw(); toast('本局信息已保存');
      } catch (error) { toast(error.message, true); }
    };
    container.querySelector('#channel-table').onchange = async event => {
      const file = event.target.files[0];
      if (!file) return;
      await upload(`/api/channels/${encodeURIComponent(id)}/table?name=${encodeURIComponent(file.name)}`, file, '表格已解析');
    };
    container.querySelector('#channel-video').onchange = async event => {
      const files = [...event.target.files];
      for (const file of files) await upload(`/api/channels/${encodeURIComponent(id)}/video?name=${encodeURIComponent(file.name)}`, file, '录像报告已解析');
    };
    container.querySelector('#attach-shot').onclick = async () => {
      const index = Number(container.querySelector('#channel-shot-group').value);
      const group = groups[index];
      if (!group?.imageIds?.length) { toast('请选择截图组', true); return; }
      try {
        channel = await api(`/api/channels/${encodeURIComponent(id)}/screenshot`, 'POST', {imageIds: group.imageIds});
        draw(); toast('截图组已关联，草稿已更新');
      } catch (error) { toast(error.message, true); }
    };
    container.querySelector('#attach-replay').onclick = async () => {
      const replayId = container.querySelector('#channel-replay').value;
      if (!replayId) { toast('请选择回放记录', true); return; }
      try {
        channel = await api(`/api/channels/${encodeURIComponent(id)}/replay`, 'POST', {replayId});
        draw(); toast('回放已关联，英雄名单已用于校验');
      } catch (error) { toast(error.message, true); }
    };
    container.querySelector('#attach-official').onclick = async event => {
      const input = container.querySelector('#channel-official-url');
      const url = input?.value.trim();
      if (!url) { toast('请粘贴王者营地回放链接', true); return; }
      const button = event.currentTarget;
      button.disabled = true;
      const old = button.textContent;
      button.textContent = '正在提取…';
      try {
        const imported = await api('/api/official/replay', 'POST', {url});
        channel = await api(`/api/channels/${encodeURIComponent(id)}/official`, 'POST',
          {officialId: imported.id});
        draw();
        toast(imported.cached ? '官方回放已存在，已关联本局' : '官方回放已提取并关联本局');
      } catch (error) {
        button.disabled = false;
        button.textContent = old;
        toast(error.message, true);
      }
    };
    const campImport = container.querySelector('#camp-detail-import');
    if (campImport) campImport.onclick = async () => {
      const button = campImport;
      button.disabled = true;
      const old = button.textContent;
      button.textContent = '导入中…';
      try {
        channel = await api(`/api/channels/${encodeURIComponent(id)}/camp`, 'POST',
          {gameSeq: (channel.official?.id || '').slice(5)});
        draw(); toast('营地十人面板已导入，草稿与冲突已更新');
      } catch (error) {
        button.disabled = false;
        button.textContent = old;
        toast(error.message, true);
      }
    };
    container.querySelector('#save-draft-edits').onclick = async () => {
      const players = [];
      const map = new Map();
      container.querySelectorAll('[data-draft-field]').forEach(input => {
        const key = `${input.dataset.draftSide}-${input.dataset.draftSlot}`;
        if (!map.has(key)) map.set(key, {side: input.dataset.draftSide, slot: Number(input.dataset.draftSlot), fields: {}});
        const item = map.get(key);
        if (input.dataset.draftField === 'hero') item.hero = input.value.trim();
        else item.fields[input.dataset.draftField] = input.value;
      });
      players.push(...map.values());
      try {
        channel = await api(`/api/channels/${encodeURIComponent(id)}/draft`, 'PATCH', {players});
        draw(); toast('草稿修订已保存，审核状态已重置');
      } catch (error) { toast(error.message, true); }
    };
    container.querySelector('#channel-review').onclick = async () => {
      try {
        channel = await api(`/api/channels/${encodeURIComponent(id)}/review`, 'POST', {
          reviewedBy: container.querySelector('#channel-reviewer').value,
          notes: container.querySelector('#channel-review-notes').value,
        });
        draw(); toast('审核完成，时间与复核人已记录');
      } catch (error) { toast(error.message, true); }
    };
    container.querySelector('#channel-save').onclick = async () => {
      try {
        const result = await api(`/api/channels/${encodeURIComponent(id)}/save`, 'POST');
        channel = result.channel;
        await fetch('/api/analysis/reload', {method: 'POST'});
        window.dispatchEvent(new Event('platform-data-changed'));
        draw(); toast('已保存，点击“开始本局复盘”查看比赛');
      } catch (error) { toast(error.message, true); }
    };
  }
  async function upload(url, file, success) {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(url, {method: 'POST', body: file});
      const value = await response.json();
      if (!response.ok) throw Error(value.detail || '上传失败');
      channel = value;
      draw(); toast(success);
    } catch (error) { toast(error.message, true); }
    finally { busy = false; }
  }
  container.innerHTML = '<div class="loading">正在打开采集通道…</div>';
  try { await load(); draw(); } catch (error) { if (isCurrent()) container.innerHTML = '<div class="notice">采集通道读取失败。</div>'; toast(error.message, true); }
}
