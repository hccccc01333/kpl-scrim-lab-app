/* 逐项校对 —— 简单版。
 *
 * 定位：营地给的十人数据在这里核对与修改；截图 / 录屏 OCR 新录入的局也在这里
 * 核对十人数据、补「本局信息」，再标记复核、保存到正式统计。不做跨来源冲突判定 ——
 * 营地是权威来源，其它渠道本来就可能出错，没必要让教练逐条仲裁。
 *
 * 接口（工作台根路径）：
 *   GET   /api/channels/{id}
 *   PATCH /api/channels/{id}         {match:{date,session,opponent,ownSide,winner}}  OCR 录入后改本局信息
 *   PATCH /api/channels/{id}/draft   {players:[{side,slot,hero?,fields:{...}}]}
 *   POST  /api/channels/{id}/review  {reviewedBy, notes}
 *   POST  /api/channels/{id}/save
 */

const ROOT_API = '/api/';

async function api(path, { method = 'GET', body, signal } = {}) {
  const response = await fetch(ROOT_API + path, {
    method,
    cache: 'no-store',
    signal,
    ...(body === undefined ? {} : {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* 非 JSON */ }
    throw new Error(typeof detail === 'string' ? detail : '采集接口不可用。校对页需要由 server.py 提供。');
  }
  return response.json();
}

/* 十人数据表的列。前 8 个是核心字段（缺失会阻挡 complete/partial），
   后 7 个是七页截图扩展指标（营地通道来自营地面板）：只做增强，缺失不影响保存。 */
const CORE_FIELD_COUNT = 8;
const FIELDS = [
  ['kills', '击杀'], ['deaths', '死亡'], ['assists', '助攻'], ['gold', '经济'],
  ['damage', '输出'], ['taken', '承伤'], ['participation', '参团'], ['rating', '评分'],
  ['cs', '补刀'], ['jungleGold', '野怪经济'], ['control', '控制'], ['healing', '治疗'],
  ['towerDamage', '对塔'], ['damageConversion', '伤害转化'], ['takenPerDeath', '每死承伤'],
];

const COL_KEY = 'v3-review-col-widths';
/* 11 个基础列（位置/昵称/英雄 + 8 个核心字段）+ 7 个扩展指标列 = 18 列。
   旧版本存过 11 列宽度，loadColWidths 长度校验不通过会自动回退这份新默认。 */
const DEFAULT_COLS = [
  52, 130, 140, 72, 62, 62, 82, 92, 82, 62, 62,
  72, 80, 74, 74, 74, 80, 76,
];

function loadColWidths() {
  try {
    const raw = JSON.parse(localStorage.getItem(COL_KEY) || 'null');
    if (Array.isArray(raw) && raw.length === DEFAULT_COLS.length) {
      return raw.map((w) => Math.max(40, Math.min(400, Number(w) || 60)));
    }
  } catch { /* 坏数据回退默认 */ }
  return [...DEFAULT_COLS];
}

const SOURCE_LABEL = {
  official: '官方回放', camp: '营地', table: '表格',
  video: '录屏', screenshot: '截图', replay: '回放',
};

function stamp(value) {
  const text = String(value || '');
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text;
}

function seconds(n) {
  const value = Number(n || 0);
  return value ? `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')}` : '';
}

export function createReview(h) {
  const { esc, icon, empty } = h;
  const text = (v) => esc(v === null || v === undefined || v === '' ? '—' : v);

  const state = { id: '', channel: null, busy: '', notice: null, notes: '',
    colWidths: typeof localStorage === 'undefined' ? [...DEFAULT_COLS] : loadColWidths() };

  async function load(_name, key, signal) {
    const nextId = key || '';
    // 切到另一条通道时清掉上一条的提示/备注/忙碌态，避免「A 局已保存」串到 B 局。
    if (nextId !== state.id) {
      state.notice = null;
      state.notes = '';
      state.busy = '';
    }
    state.id = nextId;
    if (!state.id) return { channel: null };
    const channel = await api(`channels/${encodeURIComponent(state.id)}`, { signal });
    state.channel = channel;
    return { channel };
  }

  async function refresh() {
    state.channel = await api(`channels/${encodeURIComponent(state.id)}`);
  }

  function paint() {
    const root = document.querySelector('#content');
    if (root && state.channel) {
      root.innerHTML = view(state.id, { channel: state.channel });
      bindNotes();
      bindMatchForm();
    }
  }

  function setNotice(message, isError = false) {
    state.notice = message ? { message, isError } : null;
  }

  // ---------------- 录入模式：营地同步（camp） / 截图·录屏 OCR（ocr） ----------------

  /* 新录入的通道 entry.mode='ocr'；旧通道没有 entry，由 sourceStatus.mode 兜底，
     再没有就按营地同步处理，保持原行为。 */
  function entryMode(channel) {
    return channel?.entry?.mode || channel?.sourceStatus?.mode || 'camp';
  }

  /** 识别出来的日期文本 → <input type="date"> 认得的 YYYY-MM-DD；识别不出就留空。 */
  function dateInputValue(text) {
    const value = String(text || '').trim();
    if (!value) return '';
    const full = value.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
    if (full) {
      const month = Number(full[2]);
      const day = Number(full[3]);
      if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
        return `${full[1]}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      }
    }
    return '';
  }

  /** 胜负按「列」存（winner=left/right）；有我方在哪一列时换成胜负说法。 */
  function winnerOptions(ownSide, winner) {
    const pairs = ownSide === 'left'
      ? [['left', '我方胜（左列）'], ['right', '对方胜（右列）']]
      : ownSide === 'right'
        ? [['right', '我方胜（右列）'], ['left', '对方胜（左列）']]
        : [['left', '左列胜'], ['right', '右列胜']];
    return ['<option value="">未填</option>', ...pairs.map(([value, label]) =>
      `<option value="${value}" ${value === winner ? 'selected' : ''}>${esc(label)}</option>`)].join('');
  }

  function bindMatchForm() {
    const own = document.querySelector('[data-match-field="ownSide"]');
    if (!own || own.dataset.bound) return;
    own.dataset.bound = '1';
    // 改「我方在」时同步改胜负选项的说法：值仍是左/右两列，只换文案。
    own.addEventListener('change', () => {
      const winner = document.querySelector('[data-match-field="winner"]');
      if (!winner) return;
      const current = winner.value;
      winner.innerHTML = winnerOptions(own.value, current);
      winner.value = current;
    });
  }

  // ---------------- 组件 ----------------

  function valueCell(player, field, label, isExt = false, isExtStart = false) {
    const value = (player.fields || {})[field]?.value;
    const blank = value === null || value === undefined || value === '';
    const cellClass = `ed-num${isExt ? ' is-ext' : ''}${isExtStart ? ' is-ext-start' : ''}`;
    return `<td class="${cellClass}"><input class="ed-input is-num${blank ? ' is-blank' : ''}"
      data-draft-side="${esc(player.side)}" data-draft-slot="${player.slot}" data-draft-field="${field}"
      type="number" step="any" inputmode="decimal" value="${esc(blank ? '' : value)}"
      aria-label="${esc(`${label} · ${player.side === 'left' ? '左' : '右'}${(player.slot ?? 0) + 1}`)}"></td>`;
  }

  function table(channel) {
    const players = (channel.draft || {}).players || [];
    if (!players.length) {
      return empty(entryMode(channel) === 'ocr'
        ? '这局还没有可用的识别结果。回截图 / 录屏页重新识别并挂上，十人出来后再来核对。'
        : '这局还没有营地十人面板。先补详情，再来核对。');
    }
    let lastSide = null;
    const rows = players.map((player) => {
      const split = lastSide !== null && player.side !== lastSide;
      lastSide = player.side;
      return `<tr class="${split ? 'is-split' : ''}">
        <td class="ed-side"><i>${player.side === 'left' ? '左' : '右'}</i>${(player.slot ?? 0) + 1}</td>
        <td class="ed-name" title="${esc(player.nickname || '')}">${text(player.nickname)}</td>
        <td><input class="ed-input is-text" data-draft-side="${esc(player.side)}" data-draft-slot="${player.slot}"
          data-draft-field="hero" value="${esc(player.hero || '')}" aria-label="英雄"></td>
        ${FIELDS.map(([field, label], fieldIndex) =>
          valueCell(player, field, label, fieldIndex >= CORE_FIELD_COUNT,
            fieldIndex === CORE_FIELD_COUNT)).join('')}
      </tr>`;
    }).join('');

    const widths = state.colWidths;
    const total = widths.reduce((sum, w) => sum + w, 0);
    const labels = ['位置', '昵称', '英雄', ...FIELDS.map(([, label]) => label)];
    const grip = (index) => `<i class="col-grip" data-grip="${index}" title="拖动调整列宽"></i>`;
    // 表格前 3 列是位置/昵称/英雄，之后才是字段列；扩展指标从第 3 + 8 列开始。
    const extStart = 3 + CORE_FIELD_COUNT;
    const head = labels.map((label, index) => {
      const isExt = index >= extStart;
      const classes = [];
      if (index === 0) classes.push('ed-side-h');
      if (index > 2) classes.push('ed-num');
      if (isExt) classes.push('is-ext');
      if (index === extStart) classes.push('is-ext-start');
      const attrs = `${classes.length ? ` class="${classes.join(' ')}"` : ''}`
        + `${isExt ? ' title="七页截图扩展指标"' : ''}`;
      return `<th${attrs}>${esc(label)}${grip(index)}</th>`;
    }).join('');

    return `<div class="ed-wrap"><table class="ed-table" style="width:${total}px">
      <colgroup>${widths.map((w) => `<col style="width:${w}px">`).join('')}</colgroup>
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function header(channel) {
    const match = channel.match || {};
    const review = channel.review || {};
    const saved = channel.saved || {};
    const reviewed = review.status === 'reviewed';
    const isSaved = saved.status === 'saved';
    const hasPlayers = Boolean((channel.draft?.players || []).length);
    const left = match.scores?.left;
    const right = match.scores?.right;
    // 营地列表先建、详情还没补上的局没有比分；不要显示成 null : null。
    const score = left === null || left === undefined
      ? (right === null || right === undefined ? '比分未记录' : `— : ${right}`)
      : (right === null || right === undefined ? `${left} : —` : `${left} : ${right}`);
    const won = match.winner && match.ownSide ? match.winner === match.ownSide : null;
    const result = won === null ? '结果未知' : won ? '胜' : '负';
    const blocked = isSaved || !reviewed || state.busy;

    return `<section class="ed-top">
      <div>
        <div class="ed-meta">${text(match.date)} · ${text(match.session)} · ${text(match.mode)}${seconds(match.durationSec) ? ` · ${seconds(match.durationSec)}` : ''}</div>
        <div class="ed-score">
          <strong>${esc(score)}</strong>
          <span class="chip ${won === null ? 'is-idle' : won ? 'is-done' : 'is-warn'}">${esc(result)}</span>
          ${isSaved ? '<span class="chip is-done">已进正式统计</span>' : reviewed ? '<span class="chip is-ok">已复核</span>' : '<span class="chip is-pending">缺失值审查</span>'}
          ${entryMode(channel) === 'ocr' ? '<span class="chip is-ok" title="这局数据来自截图 / 录屏 OCR，不是营地同步">截图/录屏录入</span>' : ''}
        </div>
      </div>
      <div class="ed-top-actions">
        <button class="control" data-review-action="save-draft" ${state.busy || !hasPlayers ? 'disabled' : ''}>
          ${state.busy === 'draft' ? '正在保存…' : '保存修改'}</button>
        <button class="primary" data-review-action="save-formal" ${blocked ? 'disabled' : ''}
          title="${isSaved ? '已经进入正式统计' : reviewed ? '写入正式统计' : '需要先在右侧标记复核'}">
          ${state.busy === 'save' ? '正在写入…' : (isSaved ? '已进正式统计' : '保存到正式统计')}</button>
      </div>
    </section>`;
  }

  /** OCR 录入通道的「本局信息」卡：识别可能读错日期 / 录屏没有胜负，教练就地改。 */
  function matchInfoCard(channel) {
    const match = channel.match || {};
    const ownSide = match.ownSide === 'left' || match.ownSide === 'right' ? match.ownSide : '';
    const winner = match.winner === 'left' || match.winner === 'right' ? match.winner : '';
    const sessionValue = match.session || match.opponent || '';
    const dateValue = dateInputValue(match.date);
    const rawDate = match.date && !dateValue
      ? `<p class="ed-hint">识别到的日期「${esc(match.date)}」不完整，改成完整日期后保存。</p>`
      : '';
    return `<section class="ed-card ed-match-card">
      <h3>本局信息</h3>
      <p class="ed-hint">识别可能读错日期，或录屏没有胜负：在这里改好再保存。</p>
      <div class="ed-match-form">
        <label>比赛日期<input type="date" data-match-field="date" value="${esc(dateValue)}"></label>
        <label>训练组 / 对手<input type="text" data-match-field="session" maxlength="40" autocomplete="off"
          value="${esc(sessionValue)}" placeholder="如 0917 训练赛 / 对手名"></label>
        <label>我方在<select data-match-field="ownSide">
          <option value="" ${ownSide ? '' : 'selected'}>未知</option>
          <option value="left" ${ownSide === 'left' ? 'selected' : ''}>左列 = 我方</option>
          <option value="right" ${ownSide === 'right' ? 'selected' : ''}>右列 = 我方</option>
        </select></label>
        <label>结果<select data-match-field="winner">${winnerOptions(ownSide, winner)}</select></label>
      </div>
      ${rawDate}
      <button class="control ed-wide" data-review-action="save-match" ${state.busy ? 'disabled' : ''}>
        ${state.busy === 'match' ? '正在保存…' : '保存本局信息'}</button>
    </section>`;
  }

  function aside(channel) {
    const mode = entryMode(channel);
    const review = channel.review || {};
    const reviewed = review.status === 'reviewed';
    const ready = Boolean((channel.draft?.players || []).length) && Boolean(channel.sourceStatus?.complete);
    const counts = channel.sourceStatus?.counts || {};
    const required = channel.sourceStatus?.requiredSources || [];

    const sources = Object.keys(SOURCE_LABEL).map((key) => {
      const count = Number(counts[key] || 0);
      // OCR 新录入通道不经过营地回放 / 营地同步：这两行显示「不适用」，避免教练以为还缺。
      if (mode === 'ocr' && !count && (key === 'official' || key === 'camp')) {
        return `<li class="is-off is-na" title="截图/录屏新录入通道不经过营地"><b>${esc(SOURCE_LABEL[key])}</b><small>不适用</small></li>`;
      }
      return `<li class="${count ? '' : 'is-off'}${required.includes(key) ? ' is-required' : ''}">
        <b>${esc(SOURCE_LABEL[key])}</b><small>${count || '缺失'}</small></li>`;
    }).join('');

    const log = (channel.changeLog || []).slice(-6).reverse()
      .map((item) => `<li><span>${stamp(item.at)}</span>${esc(item.action || '')}</li>`).join('');

    return `<aside class="ed-aside">
      <section class="ed-card"><h3>素材来源</h3><ul class="ed-sources">${sources}</ul></section>
      ${mode === 'ocr' ? matchInfoCard(channel) : ''}
      <section class="ed-card">
        <h3>复核</h3>
        ${!ready
          ? (mode === 'ocr'
            ? '<p class="ed-hint is-warn">这局还没有可核对的识别结果，先回截图 / 录屏页重新识别并挂上。</p>'
            : '<p class="ed-hint is-warn">这局还没有可核对的十人面板，先补详情。</p>')
          : reviewed
            ? `<p class="ed-hint">${text(review.reviewedBy)} · ${stamp(review.reviewedAt)}${review.notes ? `<br>${esc(review.notes)}` : ''}</p>`
            : (mode === 'ocr'
              ? '<p class="ed-hint">改完识别结果后，填一句备注并标记复核，才能保存到正式统计。</p>'
              : '<p class="ed-hint">改完数据后，填一句备注并标记复核，才能保存到正式统计。</p>')}
        <textarea data-review-notes rows="2" placeholder="${mode === 'ocr'
          ? '例如：按截图识别结果核对，缺失项已人工确认'
          : '例如：按营地十人面板核对，输出以营地总伤害为准'}">${esc(state.notes)}</textarea>
        <button class="control ed-wide" data-review-action="review" ${state.busy || !ready ? 'disabled' : ''}>
          ${state.busy === 'review' ? '正在标记…' : (reviewed ? '更新复核备注' : '标记为已复核')}</button>
      </section>
      <section class="ed-card"><h3>变更记录</h3>
        <ul class="ed-log">${log || '<li class="ed-hint">还没有记录</li>'}</ul></section>
    </aside>`;
  }

  function view(id, value) {
    const channel = value?.channel;
    if (!channel) {
      return `<div class="page"><p class="capture-notice is-error">审查记录 ${esc(id)} 不存在。</p>
        <p><a class="control" href="#ingest">${icon('arrow')} 回到营地同步</a></p></div>`;
    }
    const mode = entryMode(channel);
    const ocrEntry = mode === 'ocr';
    const notice = state.notice
      ? `<div class="capture-notice${state.notice.isError ? ' is-error' : ''}" role="status">${esc(state.notice.message)}</div>`
      : '';
    const stale = channel.saved?.status === 'saved' && channel.review?.status !== 'reviewed'
      ? `<div class="capture-notice is-error" role="status">草稿已改动，但正式统计里仍是上一版。重新标记复核并保存后才会更新。</div>`
      : '';
    const missing = channel.draft?.missing || [];
    const missingText = missing.map((item) => `${item.label}缺${item.missing}/10`).join('、');
    const players = channel.draft?.players || [];
    const gameSeq = channel.official?.source?.gameSeq || channel.match?.gameSeq || '';
    const repairNote = players.length ? '' : (ocrEntry
      ? `<div class="capture-notice is-error" role="status">
          <b>这局还没有可用的十人名单。</b>回截图 / 录屏页重新识别并挂上，识别出十人后再来核对。
          <div class="notice-actions">
            <a class="control" href="#shots">去截图 OCR</a>
            <a class="control" href="#videos">去录屏 OCR</a>
          </div></div>`
      : `<div class="capture-notice is-error" role="status">
          <b>这局还没有营地十人面板。</b>先补挂本机详情，或回采集页重新拉取并同步这一局。
          <div class="notice-actions">
            ${gameSeq ? `<button class="control" data-review-action="attach-camp" ${state.busy ? 'disabled' : ''}>${state.busy === 'attach' ? '正在补挂…' : '补挂本机详情'}</button>` : ''}
            <a class="control" href="#ingest">回采集页重新同步</a>
          </div></div>`);
    const missingNote = missing.length
      ? `<div class="capture-notice is-error" role="status"><b>仍有 ${missing.length} 项缺失：</b>${esc(missingText)}。补齐后可直接保存；确认保留缺失，也可标记复核后保存。</div>`
      : '';
    const title = ocrEntry
      ? (channel.match?.session || channel.match?.date || '未命名对局')
      : `${channel.match?.session || '未命名训练组'} · 缺失值审查`;

    return `<div class="page">
      <div class="page-intro"><div><h1>${esc(title)}</h1>
        <p>${ocrEntry
          ? '数据来自截图 / 录屏 OCR；核对十人数值后标记复核并保存。'
          : '数据以营地十人面板为准，可直接修改；保存后需要重新标记复核。'}</p></div>
        <div class="intro-actions"><a class="control" href="${ocrEntry ? '#shots' : '#ingest'}">${icon('arrow')} ${ocrEntry ? '回截图 / 录屏' : '返回缺失值审查'}</a></div></div>
      ${notice}
      ${stale}
      ${repairNote}
      ${missingNote}
      ${header(channel)}
      <div class="ed-layout">
        <section class="ed-main">
          <div class="ed-panel-head"><h2>十人数据</h2>
            <span>拖表头边界可调列宽 · 改完点右上角「保存修改」</span></div>
          <p class="ed-ext-note">扩展指标来自七页截图的输出 / 生存 / 发育 / 团队页（营地通道来自营地面板）；缺失不影响保存。</p>
          ${table(channel)}
        </section>
        ${aside(channel)}
      </div>
    </div>`;
  }

  // ---------------- 交互 ----------------

  function bindNotes() {
    document.querySelectorAll('[data-review-notes]').forEach((el) => {
      if (el.dataset.bound) return;
      el.dataset.bound = '1';
      el.addEventListener('input', () => { state.notes = el.value; });
    });
  }

  function collectPlayers() {
    const map = new Map();
    document.querySelectorAll('[data-draft-field]').forEach((input) => {
      const key = `${input.dataset.draftSide}-${input.dataset.draftSlot}`;
      if (!map.has(key)) {
        map.set(key, { side: input.dataset.draftSide, slot: Number(input.dataset.draftSlot), fields: {} });
      }
      const item = map.get(key);
      if (input.dataset.draftField === 'hero') item.hero = input.value.trim();
      else item.fields[input.dataset.draftField] = input.value;
    });
    return [...map.values()];
  }

  async function saveDraft() {
    const players = collectPlayers();
    if (!players.length) { setNotice('没有可保存的数据。', true); paint(); return; }
    state.busy = 'draft';
    setNotice('正在保存…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/draft`, { method: 'PATCH', body: { players } });
      await refresh();
      setNotice('已保存。复核状态已失效，需要重新标记复核。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  /** 本局信息（日期 / 训练组 / 我方左右 / 胜负）：OCR 录入后常用，PATCH 通道即可。 */
  async function saveMatchInfo() {
    const field = (name) => document.querySelector(`[data-match-field="${name}"]`);
    const date = String(field('date')?.value || '').trim();
    const session = String(field('session')?.value || '').trim();
    const ownSide = String(field('ownSide')?.value || '').trim();
    const winner = String(field('winner')?.value || '').trim();
    const opponent = String(state.channel?.match?.opponent || '').trim();
    if (!date && !session && !opponent) {
      setNotice('至少填比赛日期或训练组 / 对手。', true);
      paint();
      return;
    }
    state.busy = 'match';
    setNotice('正在保存本局信息…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}`, {
        method: 'PATCH',
        body: { match: { date, session, opponent, ownSide, winner } },
      });
      await refresh();
      setNotice('本局信息已保存。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function attachCamp() {
    const gameSeq = state.channel?.official?.source?.gameSeq || state.channel?.match?.gameSeq || '';
    if (!gameSeq) {
      setNotice('这局没有营地对局号，请回采集页重新拉取。', true);
      paint();
      return;
    }
    state.busy = 'attach';
    setNotice('正在补挂本机营地详情…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/camp`, {
        method: 'POST', body: { gameSeq },
      });
      await refresh();
      setNotice('已补挂营地十人面板。');
    } catch (error) {
      setNotice(`${error.message} 回采集页重新同步这一局。`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function markReviewed() {
    if (!(state.channel?.draft?.players || []).length) {
      setNotice(entryMode(state.channel) === 'ocr'
        ? '这局还没有可用的十人名单，先回截图 / 录屏页重新识别并挂上。'
        : '这局还没有十人面板，先补详情。', true);
      paint();
      return;
    }
    const missing = state.channel?.draft?.missing || [];
    if (missing.length) {
      const text = missing.map((item) => `${item.label}缺${item.missing}/10`).join('、');
      if (!window.confirm(`这局仍有 ${missing.length} 项缺失：${text}。\n\n确认按当前数据标记复核吗？标记后仍可保存到正式统计。`)) return;
    }
    state.busy = 'review';
    setNotice('正在标记复核…');
    paint();
    try {
      await api(`channels/${encodeURIComponent(state.id)}/review`, {
        method: 'POST', body: { reviewedBy: '本机复核', notes: state.notes },
      });
      await refresh();
      setNotice('已标记为已复核，可以保存到正式统计。');
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function saveFormal() {
    const missing = state.channel?.draft?.missing || [];
    const text = missing.length
      ? `\n\n这局仍有 ${missing.length} 项缺失：${missing.map((item) => `${item.label}缺${item.missing}/10`).join('、')}。`
      : '';
    if (!window.confirm(`保存到正式统计？这会写入比赛记录。${text}`)) return;
    state.busy = 'save';
    setNotice('正在写入正式统计…');
    paint();
    try {
      const result = await api(`channels/${encodeURIComponent(state.id)}/save`, { method: 'POST' });
      await refresh();
      const key = result?.bundle?.key || result?.channel?.saved?.bundleKey || '';
      setNotice(key ? `已进入正式统计，比赛标识 ${key}` : '已保存到正式统计。');
    } catch (error) {
      setNotice(`保存失败：${error.message}`, true);
    } finally {
      state.busy = '';
      paint();
    }
  }

  async function click(event) {
    const button = event.target.closest('[data-review-action]');
    if (!button) return false;
    const action = button.dataset.reviewAction;
    if (action === 'save-draft') { await saveDraft(); return true; }
    if (action === 'save-match') { await saveMatchInfo(); return true; }
    if (action === 'attach-camp') { await attachCamp(); return true; }
    if (action === 'review') { await markReviewed(); return true; }
    if (action === 'save-formal') { await saveFormal(); return true; }
    return false;
  }

  function bindColResize() {
    const table = document.querySelector('.ed-table');
    if (!table) return;
    const cols = table.querySelectorAll('colgroup col');
    document.querySelectorAll('[data-grip]').forEach((grip) => {
      if (grip.dataset.bound) return;
      grip.dataset.bound = '1';
      grip.addEventListener('mousedown', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const index = Number(grip.dataset.grip);
        const startX = event.clientX;
        const startWidth = state.colWidths[index];
        const onMove = (moveEvent) => {
          const width = Math.max(40, Math.min(400, startWidth + moveEvent.clientX - startX));
          state.colWidths[index] = Math.round(width);
          if (cols[index]) cols[index].style.width = `${width}px`;
          table.style.width = `${state.colWidths.reduce((sum, w) => sum + w, 0)}px`;
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.body.classList.remove('col-resizing');
          try { localStorage.setItem(COL_KEY, JSON.stringify(state.colWidths)); } catch { /* 忽略 */ }
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.body.classList.add('col-resizing');
      });
    });
  }

  function afterRender() { bindNotes(); bindMatchForm(); bindColResize(); }

  return { load, render: view, click, afterRender };
}
