/* 采集：唯一的采集入口。
   营地授权一次 → 每天点「拉取对局」→ 勾选 → 入库。
   手动补一局和采集通道管理收进折叠区。 */
const esc = (v = '') => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = (v, d = 0) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('zh-CN', {maximumFractionDigits: d}) : '—';
const CAMP_BATTLE_MODES = {1: '排位', 2: '匹配', 3: '大乱斗', 4: '训练', 5: '人机', 6: '巅峰赛', 7: '锦标赛'};
const modeText = v => v ? (CAMP_BATTLE_MODES[v] || `类型 ${v}`) : '—';
const winText = v => String(v) === '1' ? '蓝方胜' : String(v) === '2' ? '红方胜' : '—';
const formatStamp = value => {
  if (!value) return '—';
  if (typeof value === 'string' && value.includes('T')) {
    const date = new Date(value);
    return isNaN(date) ? value : date.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
  }
  return timeText(value);
};
const timeText = value => {
  if (!value) return '—';
  const n = Number(value);
  const date = new Date(Number.isFinite(n) && n < 1e12 ? n * 1000 : value);
  return isNaN(date) ? '—' : date.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
};

export async function renderCapture(container, {api, toast, isCurrent, workspace}) {
  let channels = [];
  let busy = false;
  const camp = {auth: {}, config: {players: []}, job: {}, detailsCount: 0, details: [],
                qrTask: null, authStatus: '', authTimer: null, syncTimer: null,
                list: [], checked: {}, checkedCount: 0, listLoading: false, syncStatus: '', listFetchedAt: ''};

  const load = async () => {
    const data = await api('/api/channels');
    channels = data.channels || [];
  };
  const loadCamp = async () => {
    try {
      const status = await api('/api/camp/sync');
      camp.auth = status.auth || {};
      camp.config = status.config || {players: []};
      camp.job = {running: !!status.running, result: status.result, error: status.error};
      camp.detailsCount = status.detailsCount || 0;
      camp.details = status.details || [];
    } catch { camp.auth = {authorized: false}; }
  };

  const ICON_CLOUD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 18a4.5 4.5 0 0 1-.62-8.96A6 6 0 0 1 18 9.5a3.75 3.75 0 0 1 .75 7.44"/><path d="M12 12v6"/><path d="m9.5 15.6 2.5 2.4 2.5-2.4"/></svg>';
  const ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  const ICON_INBOX = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 12.5h4l2 3h5l2-3h4"/><path d="M5.5 5.5h13l2 7v5a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 3.5 17.5v-5l2-7Z"/></svg>';
  const ICON_ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h13"/><path d="m13 6 6 6-6 6"/></svg>';

  const draw = () => {
    if (!isCurrent()) return;
    const auth = camp.auth || {};
    const rosterPlayers = (workspace?.profile?.members || [])
      .filter(m => !m.archived && m.campUserId)
      .map(m => ({nickname: m.label || m.name, campUserId: m.campUserId, fromRoster: true}));
    const extraPlayers = (camp.config?.players || [])
      .filter(p => !rosterPlayers.some(r => r.campUserId === p.campUserId))
      .map(p => ({nickname: p.nickname, campUserId: p.campUserId, fromRoster: false}));
    const players = [...rosterPlayers, ...extraPlayers];
    const running = camp.job?.running;
    const detailByChannel = new Map((camp.details || []).filter(d => d.channelId).map(d => [d.channelId, d]));
    const latest = (camp.job?.result?.players || []);
    const autoAttached = camp.job?.result?.autoAttached || [];
    const entries = camp.list || [];
    const importedCount = entries.filter(item => item.imported).length;
    const selectableEntries = entries.filter(item => !item.imported);
    const selectedCount = selectableEntries.filter(item => camp.checked[item.gameSeq]).length;
    const allSelected = selectableEntries.length > 0 && selectedCount === selectableEntries.length;
    const authLabel = auth.nickname || auth.userId || '已授权';
    const authInitial = String(auth.authorized ? authLabel : '营').trim().slice(0, 1).toUpperCase();
    const syncHint = camp.syncStatus
      ? esc(camp.syncStatus)
      : (running ? '正在拉取，每局约 2 秒…'
        : !auth.authorized ? '先完成营地授权'
        : !players.length ? '<button type="button" class="capture-inline-link" data-open-config>先添加营地选手 →</button>'
        : entries.length ? `已入库 ${num(importedCount)} 局` : '拉取后勾选要入库的比赛');
    const wasConfigOpen = !!container.querySelector('details.capture-config')?.open;
    const wasManualOpen = !!container.querySelector('details.capture-manual')?.open;
    const prevScroll = container.querySelector('.capture-table-scroll')?.scrollTop || 0;
    const draft = {
      link: container.querySelector('#camp-player-link')?.value || '',
      date: container.querySelector('#channel-date')?.value || '',
      opponent: container.querySelector('#channel-opponent')?.value || '',
      session: container.querySelector('#channel-session')?.value || '',
      version: container.querySelector('#channel-version')?.value || ''
    };

    container.innerHTML = `
    <div class="capture-page">
      <header class="capture-head">
        <div class="capture-head-copy">
          <span class="capture-eyebrow">COLLECT · 采集</span>
          <h1>采集</h1>
          <p class="capture-lede">营地授权一次；之后每天点「拉取对局」，勾选要入库的比赛即可。手动补一局和通道管理收在下方。</p>
          <div class="capture-facts">
            <span class="capture-fact ${auth.authorized ? 'is-ok' : 'is-warn'}"><i></i>${auth.authorized ? `营地已授权 · ${esc(authLabel)}` : '营地未授权'}</span>
            <span class="capture-fact"><b>${num(players.length)}</b> 位营地选手</span>
            <span class="capture-fact"><b>${num(camp.detailsCount)}</b> 份对局详情</span>
            <span class="capture-fact"><b>${num(channels.length)}</b> 个采集通道</span>
          </div>
        </div>
        <div class="capture-head-actions"><a class="button secondary" href="#matches">比赛档案</a></div>
      </header>

      <section class="capture-card capture-sync">
        <div class="capture-sync-head">
          <div class="capture-sync-intro">
            <span class="capture-sync-mark" aria-hidden="true">${ICON_CLOUD}</span>
            <div class="capture-sync-copy">
              <div class="capture-sync-title"><h2>营地自动同步</h2><span class="tag ${auth.authorized ? '' : 'amber'}">${auth.authorized ? '已授权' : '未授权'}</span></div>
              <p>教练微信扫码授权一次 → 拉取对局 → 勾选 → 入库；入库后自动挂到对应的采集通道。</p>
            </div>
          </div>
          <div class="capture-sync-side">
            <div class="capture-sync-actions">
              <button class="button ${entries.length ? '' : 'primary'} capture-fetch" id="camp-list-fetch"
                ${!auth.authorized || !players.length || camp.listLoading || running ? 'disabled' : ''}>
                ${camp.listLoading ? '正在拉取…' : '拉取对局'}</button>
              <button class="button ${camp.checkedCount ? 'primary' : ''}" id="camp-sync-run" ${!camp.checkedCount || running ? 'disabled' : ''}>
                ${running ? '入库进行中…' : `入库所选 ${num(camp.checkedCount)} 局`}</button>
            </div>
            <span class="capture-sync-status" id="camp-sync-status" role="status">${syncHint}</span>
          </div>
        </div>

        <div class="capture-flow">
          <div class="capture-flow-step ${auth.authorized ? 'is-done' : 'is-active'}">
            <span class="capture-flow-num">${auth.authorized ? ICON_CHECK : '1'}</span>
            <div><strong>授权营地</strong><small>${auth.authorized ? `${esc(authLabel)} · ${esc(formatStamp(auth.loginAt))}` : '等待教练微信扫码'}</small></div>
          </div>
          <div class="capture-flow-step ${entries.length ? 'is-done' : (auth.authorized ? 'is-active' : 'is-todo')}">
            <span class="capture-flow-num">${entries.length ? ICON_CHECK : '2'}</span>
            <div><strong>拉取并勾选</strong><small>${entries.length ? `${num(entries.length)} 局 · 拉取于 ${esc(camp.listFetchedAt || '—')}` : (auth.authorized ? (players.length ? '待拉取最近对局' : '先添加营地选手') : '完成授权后可拉取')}</small></div>
          </div>
          <div class="capture-flow-step ${channels.length ? 'is-done' : (importedCount ? 'is-active' : 'is-todo')}">
            <span class="capture-flow-num">${channels.length ? ICON_CHECK : '3'}</span>
            <div><strong>入库生成通道</strong><small>${channels.length ? `${num(channels.length)} 个通道已生成` : (importedCount ? '等待入库所选对局' : '入库后自动生成通道')}</small></div>
          </div>
        </div>

        ${camp.qrTask ? `<div class="capture-qr">
          <div class="capture-qr-frame"><img src="data:image/png;base64,${esc(camp.qrTask.qrcodeBase64)}" alt="扫码授权二维码"></div>
          <div class="capture-qr-copy">
            <strong>用打过训练赛的教练微信扫码</strong>
            <p>在手机上确认授权。二维码 3 分钟有效，过期会自动刷新。</p>
            <span class="capture-qr-status"><i></i><span id="camp-auth-status" role="status">${esc(camp.authStatus || '等待扫码…')}</span></span>
            <div class="capture-qr-actions"><button type="button" class="button ghost" id="camp-auth-cancel">取消扫码</button></div>
          </div>
        </div>`
        : `<div class="capture-auth ${auth.authorized ? '' : 'is-empty'}">
          <div class="capture-auth-main">
            <span class="capture-auth-avatar">${esc(authInitial)}</span>
            <div>
              <strong>${auth.authorized ? `当前授权 ${esc(authLabel)}` : '尚未授权营地账号'}</strong>
              <small>${auth.authorized ? `授权于 ${esc(formatStamp(auth.loginAt))} · 登录态失效时会提示重新扫码` : '授权一次长期使用；之后每天直接拉取，不需要再扫码。'}</small>
            </div>
          </div>
          <div class="capture-auth-actions">
            <button class="button ${auth.authorized ? '' : 'primary'}" id="camp-auth-qr">${auth.authorized ? '重新扫码授权' : '扫码授权'}</button>
            ${auth.authorized ? '<button class="button ghost" id="camp-auth-clear">删除凭证</button>' : ''}
          </div>
        </div>`}

        <div class="capture-list">
          <div class="capture-list-head">
            <div class="capture-list-title"><h3>最近对局</h3>${entries.length ? `<span class="capture-count">${num(entries.length)}</span>` : ''}</div>
            <div class="capture-list-meta">${entries.length ? `已入库 ${num(importedCount)} 局 · 拉取于 ${esc(camp.listFetchedAt || '—')}` : (auth.authorized ? '拉取营地选手的最近比赛，勾选后入库' : '完成授权并添加选手后即可拉取')}</div>
          </div>
          ${entries.length ? `<div class="capture-table-scroll"><table class="capture-table">
            <thead><tr>
              <th class="capture-check"><input type="checkbox" id="camp-list-all" aria-label="全选待入库对局" ${allSelected ? 'checked' : ''}></th>
              <th>对局</th><th>模式</th><th>时间</th><th>KDA</th><th>胜负</th><th>选手</th><th>状态</th>
            </tr></thead><tbody>
            ${entries.map(item => {
              const kda = [item.killcnt, item.deadcnt, item.assistcnt].filter(v => v != null).join('/');
              const win = String(item.winCamp);
              const winClass = win === '1' ? 'is-blue' : win === '2' ? 'is-red' : '';
              const checked = !!camp.checked[item.gameSeq];
              return `<tr class="${checked ? 'is-selected ' : ''}${item.imported ? 'is-imported' : ''}">
                <td class="capture-check"><input type="checkbox" data-list-check="${esc(item.gameSeq)}" ${checked ? 'checked' : ''} ${item.imported ? 'disabled' : ''} aria-label="选择对局 ${esc(item.gameSeq)}"></td>
                <td><span class="capture-seq">${esc(item.gameSeq)}</span><small>${esc(item.mapName || '地图未读')}</small></td>
                <td><span class="capture-mode">${esc(modeText(item.battleType))}</span></td>
                <td><span class="capture-mono">${esc(item.gametime || '—')}</span></td>
                <td><span class="capture-kda">${esc(kda || '—')}</span></td>
                <td><span class="capture-win ${winClass}"><i></i>${winText(item.winCamp)}</span></td>
                <td><span class="capture-owner"><i>${esc((item.ownerName || '?').slice(0, 1))}</i>${esc(item.ownerName || '—')}</span></td>
                <td>${item.imported ? '<span class="tag gray">已入库</span>' : '<span class="tag amber">待入库</span>'}</td></tr>`;
            }).join('')}</tbody></table></div>
            <p class="capture-list-foot">拉取时间 ${esc(camp.listFetchedAt || '—')} · 共 ${num(entries.length)} 局，其中 ${num(importedCount)} 局已入库。${camp.listHasMore ? '还有更早的对局未显示；需要拉取更早历史时用 tools/camp_sync.py --reset。' : ''}</p>`
          : `<div class="capture-empty">
            <span class="capture-empty-icon" aria-hidden="true">${ICON_INBOX}</span>
            <strong>还没有拉取对局</strong>
            <p>${players.length ? '点右上角「拉取对局」查看营地选手最近的比赛，勾选后入库。' : '先在下方「首次配置」里添加营地选手（一次性），再回来拉取。'}</p>
            ${players.length ? '' : '<button class="button primary" data-open-config>去配置营地选手</button>'}
          </div>`}
        </div>

        ${latest.length ? `<div class="capture-results">
          <div class="capture-results-head">本次同步结果</div>
          ${latest.map(item => item.ok
            ? `<div class="capture-result"><span class="capture-result-dot"></span><strong>${esc(item.nickname || item.campUserId)}</strong><span>新局 ${num(item.summary?.fetched)} · 入库 ${num(item.summary?.saved)} · 已知 ${num(item.summary?.cached)}${item.summary?.failed ? ` · 失败 ${num(item.summary.failed)}` : ''}</span></div>`
            : `<div class="capture-result is-error"><span class="capture-result-dot"></span><strong>${esc(item.nickname || item.campUserId)}</strong><span><span class="tag red">失败</span> ${esc(item.error || '')}</span></div>`).join('')}
        </div>` : ''}
        ${camp.job?.error ? `<div class="capture-notice">${esc(camp.job.error)}</div>` : ''}
        ${(autoAttached || []).length ? `<div class="capture-notice is-info">已自动挂载 ${num(autoAttached.length)} 个通道的营地十人面板；到「比赛档案」或下方通道列表里校对保存。</div>` : ''}

        <details class="capture-fold capture-config">
          <summary>首次配置：粘贴选手的营地分享链接<small>每位选手一次</small></summary>
          <div class="capture-fold-body">
            <p class="capture-helper camp-link-intro">这一步每位选手只做一次，配置的是<strong>「选手是谁」</strong>，不是某一局比赛：用选手本人分享出来的营地链接，系统解析出<strong>营地 ID</strong> 存进下方清单。之后每天点右上角「拉取对局」即可同步他最近的比赛，不用再找选手要链接。</p>
            <ol class="camp-link-steps">
              <li><span class="camp-link-num">01</span><div><strong>选手在王者营地 App 的对局结算页把战绩分享到微信</strong>
                <p>打完一局停在结算页（也可以从营地 →「战绩」→ 打开任意一局进「回顾分析」），点右上角「…」→「分享」→ 发送给朋友：发给教练，或发到「文件传输助手」自己留着。微信里会收到一张灰色的营地卡片（标题可能是战绩文案），来源标注「王者营地」。</p>
                <figure class="camp-link-shot is-wide"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-entry.jpg" target="_blank" rel="noopener" aria-label="查看分享入口大图"><img src="/assets/capture-guide/camp-share-entry.jpg" alt="王者营地对局结算页，右上角「…」是分享入口" loading="lazy"></a><figcaption>图 1 · 对局结算页右上角「…」→ 分享到微信（点击看大图）</figcaption></figure></div></li>
              <li><span class="camp-link-num">02</span><div><strong>在微信里长按卡片，点「用默认浏览器打开」</strong>
                <p>长按这张营地卡片（标题可能是战绩文案，来源标注「王者营地」）→ 选绿色的「用默认浏览器打开」（或「打开方式」里挑一个浏览器）。微信内置浏览器看不到完整地址，必须跳到外部浏览器，才能拿到下面那串链接。</p>
                <figure class="camp-link-shot is-menu"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-wechat.png" target="_blank" rel="noopener" aria-label="查看微信操作大图"><img src="/assets/capture-guide/camp-share-wechat.png" alt="微信里长按营地分享卡片，选择用默认浏览器打开" loading="lazy"></a><figcaption>图 2 · 微信长按消息 →「用默认浏览器打开」（点击看大图）</figcaption></figure></div></li>
              <li><span class="camp-link-num">03</span><div><strong>复制浏览器地址栏里的整条链接</strong>
                <p>打开后地址栏是一串 <code>https://camp.qq.com/h5/webdist/mp-redirect/index.html?</code> 开头的链接，关键参数是 <code>userId</code>（营地 ID）、<code>roleId</code> 和 <code>gameSeq</code>。页面若提示「此站点正在尝试打开 Weixin」，关掉提示即可，不影响复制。长按地址栏 → 全选 → 复制，<strong>整条都要</strong>：漏掉参数会提示「链接里没有 userId」。</p>
                <figure class="camp-link-shot is-wide"><a class="camp-link-zoom" href="/assets/capture-guide/camp-share-browser.png" target="_blank" rel="noopener" aria-label="查看地址栏链接大图"><img src="/assets/capture-guide/camp-share-browser.png" alt="浏览器地址栏里的营地分享完整链接，含 userId 等参数" loading="lazy"></a><figcaption>图 3 · 复制地址栏完整链接，含 ? 后的 userId 等全部参数（点击看大图）</figcaption></figure></div></li>
              <li><span class="camp-link-num">04</span><div><strong>粘贴到下方输入框，点「解析并保存」</strong>
                <p>整条粘进来即可，不用手抄 ID。系统会读出营地 ID；昵称先按「选手 XXXX」占位，可在下方清单里直接改。保存后这位选手长期有效。</p></div></li>
            </ol>
            <div class="form-grid capture-config-form">
              <label class="field">营地分享链接（整条）或营地 ID<input id="camp-player-link" placeholder="粘贴浏览器地址栏复制的完整链接，或填 5–15 位数字营地 ID"></label>
              <label class="field" style="align-self:end"><button class="button" id="camp-player-add">解析并保存</button></label>
            </div>
            <div id="camp-player-status" class="capture-helper" style="margin-top:6px">${esc(camp.parseStatus || '')}</div>
            ${rosterPlayers.length ? `<p class="capture-helper" style="margin-top:10px"><strong>已从录入名单带出 ${num(rosterPlayers.length)} 位选手</strong>（在「绑定 / 录入」的选手行里填营地 ID 即可，不用在这里重复加）：
              ${rosterPlayers.map(p => `<span class="tag">${esc(p.nickname)} · ${esc(p.campUserId)}</span>`).join(' ')}</p>` : ''}
            ${extraPlayers.length ? `<div class="capture-table-scroll" style="margin-top:10px"><table class="capture-table capture-table-compact"><thead><tr><th>额外选手（不在录入名单）</th><th>营地 ID</th><th></th></tr></thead><tbody>
              ${extraPlayers.map(p => `<tr><td><input class="camp-nick-input" data-camp-rename="${esc(p.campUserId)}" value="${esc(p.nickname || '')}" placeholder="昵称" style="max-width:140px"></td>
                <td><span class="capture-mono">${esc(p.campUserId)}</span></td>
                <td><button class="button ghost" data-camp-remove="${esc(p.campUserId)}">移除</button></td></tr>`).join('')}
              </tbody></table></div>` : ''}
            <p class="capture-helper camp-link-note">也可以直接填 5–15 位数字的营地 ID，或粘贴 <code>https://cu.qq.com/…</code> 这类短链（系统会自动展开）；<strong>微信小程序跳转链不能用</strong>，必须按第 02 步在浏览器里打开后再复制。链接只用来登记选手的营地 ID，<strong>对局模式不限</strong>（排位、匹配、开房间征召都行），只要地址里带 <code>userId=</code>；之后训练赛靠这个 ID 从战绩列表拉取，不需要逐局找链接。若选手战绩默认对教练不可见，请他在营地「隐私设置」里把教练加入白名单或恢复公开，否则拉取不到对局。</p>
          </div>
        </details>
      </section>

      <section class="capture-card capture-channels">
        <div class="capture-channels-head">
          <div>
            <div class="capture-channels-title"><h2>采集通道</h2><span class="capture-count">${num(channels.length)}</span></div>
            <p>每局一个通道：入库后在这里校对十人数据、审核并保存成比赛记录。</p>
          </div>
          ${channels.length ? `<span class="capture-channels-meta">最近更新 ${timeText(channels[0]?.updatedAt)}</span>` : ''}
        </div>
        ${channels.length ? `<div class="capture-channel-list">
          ${channels.slice(0, 12).map((channel, index) => {
            const detail = detailByChannel.get(channel.id);
            const officialId = String(channel.official?.id || '');
            const hasCamp = officialId.startsWith('camp-') || detail;
            const mapName = detail?.mapName && detail.mapName !== '—' ? detail.mapName : '地图未读';
            const titleLine = detail
              ? `${esc(detail.gametime || '时间未读')} <i>·</i> ${esc(mapName)}`
              : `${esc(channel.match?.date || '日期未填')}${channel.match?.opponent ? ` <i>·</i> 对阵 ${esc(channel.match.opponent)}` : ''}`;
            const metaParts = [];
            if (detail) {
              const mode = modeText(detail.battleType);
              if (mode && mode !== '—') metaParts.push(esc(mode));
              if (detail.gameSeq) metaParts.push(`对局 ${esc(detail.gameSeq)}`);
              const kdaText = (detail.kda || []).filter(v => v != null).join('/');
              if (kdaText) metaParts.push(`KDA ${esc(kdaText)}`);
              const win = winText(detail.winCamp);
              if (win && win !== '—') metaParts.push(esc(win));
              if (!metaParts.length) metaParts.push('营地十人面板已挂');
            } else {
              metaParts.push(esc(channel.match?.session || '未填写训练分组'));
              metaParts.push(esc(hasCamp || channel.official?.id ? '营地链接已挂' : '还没有挂营地链接'));
            }
            const metaLine = metaParts.join(' <i>·</i> ');
            return `<a class="capture-channel" href="#channel/${esc(channel.id)}">
              <span class="capture-channel-index">${String(index + 1).padStart(2, '0')}</span>
              <span class="capture-channel-main">
                <span class="capture-channel-title">${titleLine}</span>
                <span class="capture-channel-meta">${metaLine}</span>
              </span>
              <span class="capture-channel-tags">
                ${channel.review?.status === 'reviewed' ? '<span class="tag">已审核</span>' : '<span class="tag amber">待审核</span>'}
                ${channel.saved?.status === 'saved' ? '<span class="tag blue">已保存</span>' : ''}
              </span>
              <span class="capture-channel-time">${timeText(channel.updatedAt)}</span>
              <span class="capture-channel-open">打开通道 ${ICON_ARROW}</span>
            </a>`;
          }).join('')}
        </div>
        ${channels.length > 12 ? `<p class="capture-channels-foot">只显示最近 12 局，共 ${num(channels.length)} 局。</p>` : ''}`
        : `<div class="capture-channels-body"><div class="capture-empty">
          <span class="capture-empty-icon" aria-hidden="true">${ICON_INBOX}</span>
          <strong>还没有采集通道</strong>
          <p>营地同步入库后，这里会自动出现对应的通道。</p>
        </div></div>`}
        <details class="capture-fold capture-manual">
          <summary>手动补一局<small>列表里没有的比赛</small></summary>
          <div class="capture-fold-body">
            <div class="form-grid"><label class="field">比赛日期<input id="channel-date" type="date"></label>
            <label class="field">对手<input id="channel-opponent" placeholder="例如：周三训练对手"></label>
            <label class="field">训练分组<input id="channel-session" placeholder="例如：晚训 · 第 1 组"></label>
            <label class="field">版本<input id="channel-version" placeholder="例如：S42"></label></div>
            <div class="channel-actions"><button class="button" id="channel-create">创建采集通道</button>
            <span class="capture-helper">创建后进入通道，把本局营地回放链接挂上。</span></div>
          </div>
        </details>
      </section>
    </div>`;

    const tableScroll = container.querySelector('.capture-table-scroll');
    if (tableScroll && prevScroll) tableScroll.scrollTop = prevScroll;
    const configFold = container.querySelector('details.capture-config');
    if (configFold && wasConfigOpen) configFold.open = true;
    const manualFold = container.querySelector('details.capture-manual');
    if (manualFold && wasManualOpen) manualFold.open = true;
    const linkInput = container.querySelector('#camp-player-link');
    if (linkInput && draft.link) linkInput.value = draft.link;
    const draftInputs = {'channel-date': draft.date, 'channel-opponent': draft.opponent,
                         'channel-session': draft.session, 'channel-version': draft.version};
    for (const [id, value] of Object.entries(draftInputs)) {
      const input = container.querySelector('#' + id);
      if (input && value) input.value = value;
    }

    const updateSelectionUI = () => {
      camp.checkedCount = Object.keys(camp.checked).length;
      const runButton = container.querySelector('#camp-sync-run');
      if (runButton) {
        runButton.disabled = !camp.checkedCount || !!camp.job?.running;
        runButton.textContent = camp.job?.running ? '入库进行中…' : `入库所选 ${num(camp.checkedCount)} 局`;
        runButton.classList.toggle('primary', !!camp.checkedCount && !camp.job?.running);
      }
      const boxes = [...container.querySelectorAll('[data-list-check]')];
      for (const box of boxes) {
        const row = box.closest('tr');
        if (row) row.classList.toggle('is-selected', box.checked);
      }
      const all = container.querySelector('#camp-list-all');
      if (all) {
        const selectable = boxes.filter(box => !box.disabled);
        const picked = selectable.filter(box => box.checked).length;
        all.checked = selectable.length > 0 && picked === selectable.length;
        all.indeterminate = picked > 0 && picked < selectable.length;
      }
    };

    // —— 授权 ——
    const qrButton = container.querySelector('#camp-auth-qr');
    if (qrButton) qrButton.onclick = startCampAuth;
    const cancelQrButton = container.querySelector('#camp-auth-cancel');
    if (cancelQrButton) cancelQrButton.onclick = cancelCampAuth;
    const clearButton = container.querySelector('#camp-auth-clear');
    if (clearButton) clearButton.onclick = async () => {
      stopCampAuth();
      camp.qrTask = null;
      camp.authStatus = '';
      try { await api('/api/camp/auth/clear', 'POST'); await loadCamp(); draw(); toast('凭证已删除'); }
      catch (error) { toast(error.message, true); }
    };
    // —— 首次配置 ——
    const addButton = container.querySelector('#camp-player-add');
    if (addButton) addButton.onclick = addCampPlayer;
    container.querySelectorAll('[data-camp-rename]').forEach(input => {
      input.onchange = () => renameCampPlayer(input.dataset.campRename, input.value);
    });
    container.querySelectorAll('[data-camp-remove]').forEach(button => {
      button.onclick = () => removeCampPlayer(button.dataset.campRemove);
    });
    container.querySelectorAll('[data-open-config]').forEach(button => {
      button.onclick = () => {
        const fold = container.querySelector('details.capture-config');
        if (!fold) return;
        fold.open = true;
        fold.scrollIntoView({behavior: 'smooth', block: 'center'});
      };
    });
    // —— 拉取与入库 ——
    const fetchButton = container.querySelector('#camp-list-fetch');
    if (fetchButton) fetchButton.onclick = fetchAllLists;
    const syncButton = container.querySelector('#camp-sync-run');
    if (syncButton) syncButton.onclick = runCampSync;
    const selectAll = container.querySelector('#camp-list-all');
    if (selectAll) {
      selectAll.indeterminate = selectedCount > 0 && selectedCount < selectableEntries.length;
      selectAll.onchange = () => {
        for (const item of camp.list || []) {
          if (item.imported) continue;
          if (selectAll.checked) camp.checked[item.gameSeq] = true;
          else delete camp.checked[item.gameSeq];
        }
        container.querySelectorAll('[data-list-check]').forEach(box => {
          box.checked = !!camp.checked[box.dataset.listCheck];
        });
        updateSelectionUI();
      };
    }
    container.querySelectorAll('[data-list-check]').forEach(checkbox => {
      checkbox.onchange = () => {
        if (checkbox.checked) camp.checked[checkbox.dataset.listCheck] = true;
        else delete camp.checked[checkbox.dataset.listCheck];
        updateSelectionUI();
      };
    });
    // —— 手动建局 ——
    const createButton = container.querySelector('#channel-create');
    if (createButton) createButton.onclick = createChannel;
  };

  // —— 授权（二维码 + 轮询，过期自动刷新） ——
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
      // 固定本次 taskId：自动刷新二维码后，旧轮询不能接着读新会话。
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
          // 不再静默吞掉 500：把失败暴露出来，连续失败就退出等待态。
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
            camp.qrTask = null;
            camp.authStatus = '已在手机上取消，可重新扫码。';
            draw();
            return;
          }
          camp.qrRefreshes = (camp.qrRefreshes || 0) + 1;
          if (camp.qrRefreshes <= 3) {
            camp.qrTask = null;
            camp.authStatus = '二维码已过期，正在自动刷新…';
            busy = false;
            await startCampAuth();
            return;
          }
          camp.qrTask = null;
          camp.authStatus = '二维码已多次过期。准备好后再点「扫码授权」。';
          draw();
        }
      }, 2500);
    } catch (error) { toast(error.message, true); }
    finally { busy = false; }
  }

  // —— 主流程：拉取所有已存选手的对局，按 gameSeq 合并 ——
  async function fetchAllLists() {
    const players = camp.config?.players || [];
    if (!players.length) { toast('先在「首次配置」里添加营地选手', true); return; }
    camp.listLoading = true;
    camp.list = [];
    camp.checked = {};
    camp.checkedCount = 0;
    camp.listFetchedAt = '';
    draw();
    const merged = new Map();
    for (const player of players) {
      try {
        const result = await api('/api/camp/list', 'POST', {campUserId: player.campUserId, lastTime: 0});
        for (const entry of result.entries || []) {
          const existing = merged.get(entry.gameSeq);
          if (existing) { existing.owners.push(player.nickname || player.campUserId); continue; }
          merged.set(entry.gameSeq, {...entry,
            owners: [player.nickname || player.campUserId],
            ownerName: player.nickname || `选手 ${player.campUserId.slice(-4)}`,
            ownerCampUserId: player.campUserId});
        }
        if (result.gaming) toast(`${player.nickname || '选手'} 有一局正在进行中，列表不含对局中的比赛`);
      } catch (error) {
        const invisible = String(error.message).includes('隐藏');
        toast(`${player.nickname || '选手'}：${invisible ? '战绩对教练不可见，请其把教练加入白名单或恢复公开' : error.message}`, true);
      }
    }
    camp.list = [...merged.values()].sort((a, b) => Number(b.dtEventTime || 0) - Number(a.dtEventTime || 0));
    camp.listHasMore = false;
    for (const item of camp.list) if (!item.imported) camp.checked[item.gameSeq] = true;
    camp.checkedCount = Object.keys(camp.checked).length;
    camp.listLoading = false;
    camp.listFetchedAt = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
    draw();
  }

  // —— 入库：按选手分组顺序同步，避免后台任务互斥 ——
  async function runCampSync() {
    if (busy) return;
    const groups = new Map();
    for (const item of camp.list || []) {
      if (!camp.checked[item.gameSeq]) continue;
      const entry = {...item};
      delete entry.owners; delete entry.ownerName; delete entry.ownerCampUserId; delete entry.imported;
      const key = item.ownerCampUserId;
      if (!groups.has(key)) groups.set(key, {nickname: item.ownerName || '', entries: []});
      groups.get(key).entries.push(entry);
    }
    if (!groups.size) { toast('请先勾选要拉取的对局', true); return; }
    busy = true;
    camp.syncStatus = `已启动，共 ${[...groups.values()].reduce((sum, g) => sum + g.entries.length, 0)} 局…`;
    draw();
    const pollJob = () => new Promise(resolve => {
      clearInterval(camp.syncTimer);
      camp.syncTimer = setInterval(async () => {
        try {
          const status = await api('/api/camp/sync');
          camp.job = {running: !!status.running, result: status.result, error: status.error};
          camp.detailsCount = status.detailsCount || 0;
          camp.details = status.details || [];
          camp.syncStatus = `正在拉取，本机已有 ${num(camp.detailsCount)} 份对局详情…`;
          draw();
          if (!status.running) {
            clearInterval(camp.syncTimer);
            camp.syncTimer = null;
            resolve(status);
          }
        } catch { /* keep polling */ }
      }, 3000);
    });
    try {
      for (const [campUserId, group] of groups) {
        await api('/api/camp/sync', 'POST', {campUserId, nickname: group.nickname, entries: group.entries});
        const status = await pollJob();
        const failed = (status.result?.players || []).filter(item => !item.ok).length;
        if (failed) toast('同步完成，但有失败项，详见面板', true);
      }
      camp.syncStatus = '';
      camp.checked = {};
      camp.checkedCount = 0;
      camp.list = [];
      camp.listFetchedAt = '';
      await loadCamp(); await load();
      toast('所选对局已入库，通道已自动挂载');
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

  async function addCampPlayer() {
    const raw = container.querySelector('#camp-player-link')?.value.trim() || '';
    const statusEl = container.querySelector('#camp-player-status');
    if (!raw) { if (statusEl) statusEl.textContent = '先粘贴选手的营地分享链接，或填营地 ID。'; return; }
    let campUserId = raw;
    let nickname = '';
    try {
      if (raw.includes('://') || raw.includes('cu.qq.com')) {
        const resolved = await api('/api/camp/resolve', 'POST', {url: raw});
        campUserId = resolved.userId;
        nickname = resolved.nickname || '';
        if (resolved.gameSeq) toast('链接里还带了一局对局，入库请用「拉取对局」');
      }
    } catch (error) {
      if (statusEl) statusEl.textContent = `解析失败：${error.message || error}`;
      return;
    }
    if (!/^\d{5,15}$/.test(campUserId)) {
      if (statusEl) statusEl.textContent = '营地 ID 需为 5–15 位数字；确认粘贴的是完整分享链接。';
      return;
    }
    const rosterMember = (workspace?.profile?.members || []).find(m => m.campUserId === campUserId);
    if (rosterMember) {
      if (statusEl) statusEl.textContent = `${rosterMember.label || rosterMember.name} 已在录入名单里配了营地 ID ${campUserId}，无需重复添加。`;
      return;
    }
    const players = (camp.config?.players || []).filter(p => p.campUserId !== campUserId);
    players.push({nickname: nickname || `选手 ${campUserId.slice(-4)}`, campUserId});
    try {
      camp.config = await api('/api/camp/config', 'POST', {players});
      camp.parseStatus = `已保存：${players.find(p => p.campUserId === campUserId)?.nickname}（营地 ID ${campUserId}）。昵称可在列表里直接改。`;
      draw();
    } catch (error) { toast(error.message, true); }
  }

  async function renameCampPlayer(campUserId, nickname) {
    const players = (camp.config?.players || []).map(p =>
      p.campUserId === campUserId ? {...p, nickname: nickname.trim() || p.nickname} : p);
    try { camp.config = await api('/api/camp/config', 'POST', {players}); } catch (error) { toast(error.message, true); }
  }


  async function removeCampPlayer(campUserId) {
    const players = (camp.config?.players || []).filter(p => p.campUserId !== campUserId);
    try {
      camp.config = await api('/api/camp/config', 'POST', {players});
      draw();
    } catch (error) { toast(error.message, true); }
  }

  async function createChannel() {
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

  container.innerHTML = '<div class="loading">正在读取采集状态…</div>';
  try { await load(); await loadCamp(); draw(); }
  catch (error) { if (isCurrent()) container.innerHTML = `<div class="notice">采集状态读取失败：${esc(error.message || error)}</div>`; }
}
