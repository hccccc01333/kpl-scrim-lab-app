/* 选手主页档案：百段 / 巅峰赛分 / 巅峰千强 / 实力 / 英雄战力。
 *
 * 为什么单独一页 UI：营地对局接口只给得出胜率、KDA、参团这些，
 * 百段和巅峰赛分只存在选手主页上。主页接口要登录态，所以这里是「能采就采、
 * 采不到就手填」：点「尝试自动采集」会先试一次营地接口，缺 Cookie 就当场要，
 * 采到什么先填进表里让人核对，最后落盘的是人确认过的数字。
 *
 * 数据走 /api/v3/player-profiles（按营地游戏名存，认领改名后仍能按 nicknames 回查）。
 */
const POSITIONS = ['对抗路', '打野', '中路', '发育路', '游走'];
const GRADES = [['S', 'S'], ['A', 'A'], ['B', 'B'], ['C', 'C']];

const maxOf = (profile, key) => Math.max(0, ...((profile && profile.lanes) || []).map((item) => Number(item[key]) || 0));

export function createProfileUI({esc, fmt, st, apiBase, refresh}) {
  const text = (value) => esc(value == null ? '' : value);

  /* ── 数据 ─────────────────────────────────────────────────────── */
  let pending = null;
  function ensure() {
    if (st.profiles) return Promise.resolve(st.profiles);
    if (!pending) {
      pending = fetch(apiBase + '/api/v3/player-profiles', {headers: {accept: 'application/json'}})
        .then((response) => (response.ok ? response.json() : {profiles: {}}))
        .then((data) => {
          st.profiles = data.profiles || {};
          st.profileMeta = {canAuto: Boolean(data.crawl && data.crawl.canAuto), hint: (data.crawl && data.crawl.hint) || ''};
          if (typeof refresh === 'function') refresh();
          return st.profiles;
        })
        .catch(() => {
          st.profiles = {};
          return st.profiles;
        });
    }
    return pending;
  }

  /* 一个号可能同时有营地名和认领后的 ID 名，两个都查一遍。 */
  function of(player) {
    const map = st.profiles || {};
    if (!player) return null;
    for (const key of [player.name, ...(player.nicknames || [])]) {
      if (key && map[key]) return map[key];
    }
    return null;
  }

  const segMax = (profile) => maxOf(profile, 'segments');
  const peakMax = (profile) => maxOf(profile, 'peak');

  /* ── 卡片上的一条 ─────────────────────────────────────────────── */
  function chips(profile) {
    const out = [];
    const seg = segMax(profile);
    const peak = peakMax(profile);
    if (seg) out.push(`<span class="pf-chip"><b>${seg}</b>段</span>`);
    if (peak) out.push(`<span class="pf-chip"><b>${peak}</b>巅峰</span>`);
    if (profile.top1000) out.push('<span class="pf-chip is-hot">千强</span>');
    if (profile.strength) out.push(`<span class="pf-grade" data-grade="${text(profile.strength)}">${text(profile.strength)}</span>`);
    return out.join('');
  }

  function cardStrip(player) {
    const profile = of(player);
    const body = profile ? chips(profile) : '<span class="pf-add">＋ 档案</span>';
    const tip = profile ? '编辑档案：百段 / 巅峰分 / 千强 / 实力' : '录百段、巅峰赛分、实力（可尝试自动采集）';
    return `<button type="button" class="pf-strip${profile ? ' is-filled' : ''}" data-pa-profile="${text(player.name)}" title="${text(tip)}">
      ${body}<i aria-hidden="true">${profile ? '编辑' : ''}</i>
    </button>`;
  }

  /* ── 详情页的一段 ─────────────────────────────────────────────── */
  function summary(player) {
    const profile = of(player);
    const lanes = (profile && profile.lanes) || [];
    const heroRows = ((profile && profile.heroPower) || []).slice(0, 4);
    const laneRows = lanes.map((item) => `<span class="pf-lane-chip${item.primary ? ' is-main' : ''}">
        <b>${text(item.lane)}</b>${item.primary ? '<i>主</i>' : ''}
        ${item.segments ? `<small>${fmt(item.segments)} 段</small>` : ''}
        ${item.peak ? `<small>巅峰 ${fmt(item.peak)}</small>` : ''}
      </span>`).join('');
    const meta = [
      profile && profile.strength ? `<span class="pf-meta"><i>实力</i><span class="pf-grade" data-grade="${text(profile.strength)}">${text(profile.strength)}</span></span>` : '',
      profile && profile.top1000 ? '<span class="pf-chip is-hot">巅峰千强</span>' : '',
      profile && profile.note ? `<span class="pf-note-text">${text(profile.note)}</span>` : '',
    ].filter(Boolean).join('');
    const heroes = heroRows.map((item) => `<span class="pf-hero"><b>${text(item.hero)}</b>${fmt(item.power)}</span>`).join('');
    return `<section class="pf-summary" data-pl-profile="${text(player.name)}">
      <header class="pf-summary-head">
        <div><h2>主页档案</h2><p>${profile ? '百段与巅峰赛分来自选手主页，采不到就手填；这里只存你确认过的数。' : '这个号还没有主页档案：百段、巅峰赛分、千强、实力都能手填。'}</p></div>
        <span class="pf-summary-acts">
          <button type="button" class="arch-btn is-primary" data-pa-profile="${text(player.name)}">${profile ? '编辑档案' : '录入档案'}</button>
        </span>
      </header>
      ${profile ? `<div class="pf-summary-body">
        <div class="pf-lane-chips">${laneRows || '<span class="pf-empty">还没有分路数据</span>'}</div>
        <div class="pf-summary-meta">${meta}</div>
        ${heroes ? `<div class="pf-heroes-list">${heroes}</div>` : ''}
      </div>` : ''}
    </section>`;
  }

  /* ── 筛选 ─────────────────────────────────────────────────────── */
  function filterRow() {
    const count = Object.keys(st.profiles || {}).length;
    const total = (st.board && (st.board.players || []).length) || 0;
    return `<div class="arch-filters" data-pa-bar>
      <span class="arch-filters-kicker">主页档案</span>
      <span class="arch-select is-narrow"><select data-pa-filter="segMin" aria-label="百段下限">
        <option value="0" ${Number(st.pa.segMin) ? '' : 'selected'}>百段不限</option>
        <option value="60" ${Number(st.pa.segMin) === 60 ? 'selected' : ''}>60 段以上</option>
        <option value="100" ${Number(st.pa.segMin) === 100 ? 'selected' : ''}>百段（100+）</option>
        <option value="120" ${Number(st.pa.segMin) === 120 ? 'selected' : ''}>120 段以上</option>
      </select></span>
      <span class="arch-select is-narrow"><select data-pa-filter="peakMin" aria-label="巅峰分下限">
        <option value="0" ${Number(st.pa.peakMin) ? '' : 'selected'}>巅峰分不限</option>
        <option value="1800" ${Number(st.pa.peakMin) === 1800 ? 'selected' : ''}>1800+</option>
        <option value="2000" ${Number(st.pa.peakMin) === 2000 ? 'selected' : ''}>2000+</option>
        <option value="2200" ${Number(st.pa.peakMin) === 2200 ? 'selected' : ''}>2200+</option>
        <option value="2400" ${Number(st.pa.peakMin) === 2400 ? 'selected' : ''}>2400+</option>
      </select></span>
      <button type="button" class="arch-chip${st.pa.top1000 ? ' is-on' : ''}" data-pa-filter-top="1" aria-pressed="${Boolean(st.pa.top1000)}">巅峰千强</button>
      <span class="arch-select is-narrow"><select data-pa-filter="strength" aria-label="实力">
        <option value="" ${st.pa.strength ? '' : 'selected'}>实力不限</option>
        ${GRADES.map(([value]) => `<option value="${value}" ${st.pa.strength === value ? 'selected' : ''}>${value} 级</option>`).join('')}
      </select></span>
      <button type="button" class="arch-chip${st.pa.hasProfile ? ' is-on' : ''}" data-pa-filter-profile="1" aria-pressed="${Boolean(st.pa.hasProfile)}">只看有档案</button>
      <span class="arch-count">已录 <b>${fmt(count)}</b> / ${fmt(total)} 个号</span>
    </div>`;
  }

  /* paRows 用的判定：没有档案的号，只要开了任何一项就被筛掉。 */
  function matches(player, state) {
    const active = state.hasProfile || Number(state.segMin) || Number(state.peakMin) || state.top1000 || state.strength;
    if (!active) return true;
    const profile = of(player);
    if (!profile) return false;
    if (Number(state.segMin) && segMax(profile) < Number(state.segMin)) return false;
    if (Number(state.peakMin) && peakMax(profile) < Number(state.peakMin)) return false;
    if (state.top1000 && !profile.top1000) return false;
    if (state.strength && profile.strength !== state.strength) return false;
    return true;
  }

  /* ── 录入 / 采集对话框 ────────────────────────────────────────── */
  const laneOptions = (value) => POSITIONS.map((lane) =>
    `<option value="${text(lane)}" ${value === lane ? 'selected' : ''}>${text(lane)}</option>`).join('');

  function laneRow(item = {}) {
    return `<div class="pf-lane" data-pf-lane>
      <span class="arch-select"><select data-lane aria-label="分路">${laneOptions(item.lane)}</select></span>
      <label class="pf-main"><input type="checkbox" data-lane-primary ${item.primary ? 'checked' : ''} aria-label="主分路"> 主</label>
      <input class="pf-input" type="number" data-lane-seg min="0" max="999" value="${item.segments == null ? '' : item.segments}" placeholder="段数" aria-label="段数" inputmode="numeric">
      <input class="pf-input" type="number" data-lane-peak min="0" max="9999" value="${item.peak == null ? '' : item.peak}" placeholder="巅峰分" aria-label="巅峰分" inputmode="numeric">
      <button type="button" class="pf-row-x" data-lane-remove aria-label="删除这条分路">×</button>
    </div>`;
  }

  function heroRow(item = {}) {
    return `<div class="pf-hero-row" data-pf-hero-row>
      <input class="pf-input" data-hero-name placeholder="英雄" value="${text(item.hero || '')}" maxlength="20">
      <input class="pf-input" data-hero-power type="number" min="0" max="100000" placeholder="战力" value="${item.power == null ? '' : item.power}" inputmode="numeric">
      <button type="button" class="pf-row-x" data-hero-remove aria-label="删除这个英雄">×</button>
    </div>`;
  }

  function dialogShell(name) {
    let dialog = document.querySelector('#pf-dialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'pf-dialog';
      dialog.className = 'pf-dialog';
      document.body.appendChild(dialog);
    }
    dialog.dataset.name = name;
    return dialog;
  }

  function open(player) {
    const name = typeof player === 'string' ? player : (player && player.name) || '';
    /* 认领后 name 是选手ID，档案仍按营地游戏名存：优先复用已有档案的键，
       否则用当前名字新建。否则认领后点「编辑档案」会读不到旧档案，
       一保存又在选手ID 名下多出一份。 */
    const profiles = st.profiles || {};
    const row = (st.board && (st.board.players || []).find((item) => item.name === name)) || null;
    const storageName = profiles[name] ? name
      : ((row && (row.nicknames || []).find((nick) => profiles[nick])) || name);
    const profile = profiles[storageName] || null;
    const dialog = dialogShell(storageName);
    /* 新建档案时默认落在本人的实际分路：省一次下拉，也少录错位置的坑。 */
    const defaultLane = (row && row.lane && POSITIONS.includes(row.lane)) ? row.lane : POSITIONS[0];
    const lanes = (profile && profile.lanes && profile.lanes.length ? profile.lanes : [{lane: defaultLane, primary: true}]).slice(0, 5);
    const heroes = (profile && profile.heroPower) || [];
    const canAuto = Boolean(st.profileMeta && st.profileMeta.canAuto);
    const hint = (st.profileMeta && st.profileMeta.hint) || '主页数据要营地网页的登录态：点「扫码登录」开一个窗口扫码即可；不想登就直接手填。';
    dialog.innerHTML = `<form>
      <div class="dialog-head"><div><h2>主页档案 · ${text(name)}</h2>
        <p>百段、巅峰赛分、英雄战力只存在选手主页上，营地对局接口给不出来。能采就采，采不到直接填。</p></div>
        <button type="button" class="head-button" data-pf-close aria-label="关闭">×</button></div>
      <div class="dialog-body">
        <div class="pf-crawl">
          <button type="button" class="control" data-pf-crawl>尝试自动采集</button>
          <button type="button" class="control is-strong" data-pf-login>扫码登录</button>
          <span class="pf-crawl-status" data-pf-status>${canAuto ? '已存登录态，可以直接试。' : hint}</span>
          <button type="button" class="link-button" data-pf-cookie-toggle>${canAuto ? '换一份 Cookie' : '手填 Cookie'}</button>
          <div class="pf-cookie" data-pf-cookie ${canAuto ? 'hidden' : 'hidden'}>
            <label>营地网页 Cookie（只存本机 data/，不会提交到别处）
              <textarea data-pf-cookie-input rows="2" placeholder="从浏览器开发者工具复制整行 Cookie"></textarea></label>
            <div><button type="button" class="control" data-pf-cookie-save>保存并重试</button></div>
          </div>
        </div>
        <fieldset class="pf-lanes">
          <legend>分路与分数（1–5 条，勾「主」的是主分路）</legend>
          <div class="pf-lane-head" aria-hidden="true"><span>分路</span><span>主</span><span>段数</span><span>巅峰分</span><span></span></div>
          <div class="pf-lane-list" data-pf-lanes>${lanes.map(laneRow).join('')}</div>
          <button type="button" class="control" data-pf-lane-add>＋ 加一条分路</button>
        </fieldset>
        <div class="pf-flags">
          <label class="pf-check"><input type="checkbox" name="top1000" ${profile && profile.top1000 ? 'checked' : ''}> 巅峰千强</label>
          <span class="pf-grades" role="radiogroup" aria-label="实力">
            <span class="pf-grades-label">实力</span>
            <label><input type="radio" name="strength" value="" ${!profile || !profile.strength ? 'checked' : ''}> 无</label>
            ${GRADES.map(([value]) => `<label><input type="radio" name="strength" value="${value}" ${profile && profile.strength === value ? 'checked' : ''}> ${value}</label>`).join('')}
          </span>
        </div>
        <fieldset class="pf-heroes">
          <legend>英雄战力（可不填，按战力从高到低存）</legend>
          <div class="pf-hero-head" aria-hidden="true"><span>英雄</span><span>战力</span><span></span></div>
          <div class="pf-hero-list" data-pf-heroes>${heroes.map(heroRow).join('')}</div>
          <button type="button" class="control" data-pf-hero-add>＋ 加一个英雄</button>
        </fieldset>
        <label class="pf-note-field">备注<input name="note" maxlength="200" value="${text((profile && profile.note) || '')}" placeholder="例如：主指挥 / 会开团 / 只会打野"></label>
        <p class="filter-error" data-pf-error></p>
      </div>
      <div class="dialog-actions">
        <button type="button" class="control" data-pf-close>取消</button>
        <button type="submit" class="primary">保存档案</button>
      </div></form>`;
    bind(dialog, name, storageName);
    dialog.showModal();
  }

  function readLanes(dialog) {
    return [...dialog.querySelectorAll('[data-pf-lane]')].map((row) => ({
      lane: row.querySelector('[data-lane]').value,
      primary: row.querySelector('[data-lane-primary]').checked,
      segments: row.querySelector('[data-lane-seg]').value,
      peak: row.querySelector('[data-lane-peak]').value,
    })).filter((item) => item.lane);
  }

  function readHeroes(dialog) {
    return [...dialog.querySelectorAll('[data-pf-hero-row]')].map((row) => ({
      hero: row.querySelector('[data-hero-name]').value.trim(),
      power: row.querySelector('[data-hero-power]').value,
    })).filter((item) => item.hero);
  }

  function bind(dialog, name, storageName) {
    const status = dialog.querySelector('[data-pf-status]');
    const error = dialog.querySelector('[data-pf-error]');
    const close = () => dialog.close();
    dialog.querySelectorAll('[data-pf-close]').forEach((button) => button.addEventListener('click', close));

    /* 主分路只能有一个：勾一个就把别的取消，省得提交时再猜哪个算主。 */
    dialog.querySelector('[data-pf-lanes]').addEventListener('change', (event) => {
      const box = event.target.closest('[data-lane-primary]');
      if (!box || !box.checked) return;
      dialog.querySelectorAll('[data-lane-primary]').forEach((other) => { if (other !== box) other.checked = false; });
    });
    dialog.querySelector('[data-pf-lanes]').addEventListener('click', (event) => {
      const remove = event.target.closest('[data-lane-remove]');
      if (!remove) return;
      if (dialog.querySelectorAll('[data-pf-lane]').length <= 1) {
        error.textContent = '至少留一条分路。';
        return;
      }
      remove.closest('[data-pf-lane]').remove();
    });
    dialog.querySelector('[data-pf-lane-add]').addEventListener('click', () => {
      const list = dialog.querySelector('[data-pf-lanes]');
      if (list.children.length >= 5) { error.textContent = '最多 5 条分路。'; return; }
      const used = new Set([...list.querySelectorAll('[data-lane]')].map((select) => select.value));
      const next = POSITIONS.find((lane) => !used.has(lane)) || POSITIONS[0];
      list.insertAdjacentHTML('beforeend', laneRow({lane: next}));
    });
    dialog.querySelector('[data-pf-hero-add]').addEventListener('click', () => {
      const list = dialog.querySelector('[data-pf-heroes]');
      if (list.children.length >= 8) { error.textContent = '最多 8 个英雄。'; return; }
      list.insertAdjacentHTML('beforeend', heroRow());
    });
    dialog.querySelector('[data-pf-heroes]').addEventListener('click', (event) => {
      const remove = event.target.closest('[data-hero-remove]');
      if (remove) remove.closest('[data-pf-hero-row]').remove();
    });
    dialog.querySelector('[data-pf-cookie-toggle]').addEventListener('click', () => {
      const box = dialog.querySelector('[data-pf-cookie]');
      box.hidden = !box.hidden;
      if (!box.hidden) box.querySelector('textarea').focus();
    });

    const post = (url, body) => fetch(apiBase + url, {
      method: 'POST',
      headers: {'content-type': 'application/json', accept: 'application/json'},
      body: JSON.stringify(body),
    }).then((response) => response.json().then((data) => ({ok: response.ok, data})));

    async function crawl() {
      status.textContent = '正在试营地接口…';
      error.textContent = '';
      const player = (st.board && (st.board.players || []).find((p) => p.name === name)) || null;
      const roleId = (player && (player.accountIds || [])[0]) || '';
      try {
        const {data} = await post('/api/v3/player-profiles/crawl', {name: storageName, roleId});
        if (data.ok) {
          const peak = data.fields && data.fields.peak && data.fields.peak[0];
          const seg = data.fields && data.fields.segments && data.fields.segments[0];
          const top = data.fields && data.fields.top1000 && data.fields.top1000.find((item) => item.value);
          const first = dialog.querySelector('[data-pf-lane]');
          if (peak && first) first.querySelector('[data-lane-peak]').value = peak.value;
          if (seg && first) first.querySelector('[data-lane-seg]').value = seg.value;
          if (top) dialog.querySelector('input[name=top1000]').checked = true;
          const got = [peak && `巅峰 ${peak.value}`, seg && `段数 ${seg.value}`, top && '千强'].filter(Boolean);
          status.textContent = got.length ? `采到：${got.join(' · ')}。已填进表里，请核对后再存。` : '接口通了，但没有可用的数值。';
        } else if (data.reason === 'no-session') {
          status.textContent = data.message;
          dialog.querySelector('[data-pf-cookie]').hidden = false;
          dialog.querySelector('[data-pf-cookie-input]').focus();
        } else {
          status.textContent = data.message || '这次没采到。';
        }
      } catch (failure) {
        status.textContent = `采集失败：${failure && failure.message ? failure.message : failure}`;
      }
    }

    /* 扫码登录：后端开一个真浏览器窗口到营地登录页，用户用手机扫，
       扫完 Cookie 落进本机，这里收到 success 就直接接着采。 */
    async function startLogin() {
      status.textContent = '正在打开浏览器窗口…';
      error.textContent = '';
      const {data} = await post('/api/v3/player-profiles/web-login', {});
      if (data.state === 'failed') { status.textContent = data.message || '打不开登录窗口。'; return; }
      for (let tries = 0; tries < 200; tries += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (!dialog.open) return;
        const state = await fetch(apiBase + '/api/v3/player-profiles/web-login', {headers: {accept: 'application/json'}})
          .then((response) => response.json()).catch(() => null);
        if (!state) continue;
        status.textContent = state.message || state.state;
        if (state.state === 'success') {
          st.profileMeta = {...(st.profileMeta || {}), canAuto: true};
          crawl();
          return;
        }
        if (['failed', 'expired', 'canceled'].includes(state.state)) return;
      }
    }

    dialog.querySelector('[data-pf-login]').addEventListener('click', startLogin);
    dialog.querySelector('[data-pf-crawl]').addEventListener('click', crawl);
    dialog.querySelector('[data-pf-cookie-save]').addEventListener('click', async () => {
      const input = dialog.querySelector('[data-pf-cookie-input]');
      const cookie = input.value.trim();
      if (!cookie) { status.textContent = '先把 Cookie 粘进来。'; return; }
      const {data} = await post('/api/v3/player-profiles/session', {cookie});
      if (data.ok) {
        st.profileMeta = {...(st.profileMeta || {}), canAuto: Boolean(data.canAuto)};
        status.textContent = 'Cookie 已存在本机，开始采集…';
        dialog.querySelector('[data-pf-cookie]').hidden = true;
        crawl();
      } else {
        status.textContent = 'Cookie 没存上。';
      }
    });

    dialog.querySelector('form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const lanes = readLanes(dialog).map((item) => ({
        lane: item.lane, primary: item.primary,
        segments: item.segments === '' ? null : Number(item.segments),
        peak: item.peak === '' ? null : Number(item.peak),
      })).filter((item) => item.segments != null || item.peak != null);
      if (!lanes.length) { error.textContent = '至少填一条分路的段数或巅峰分。'; return; }
      const strength = (dialog.querySelector('input[name=strength]:checked') || {}).value || '';
      const body = {
        name: storageName, lanes, strength,
        top1000: dialog.querySelector('input[name=top1000]').checked,
        heroPower: readHeroes(dialog).map((item) => ({hero: item.hero, power: item.power === '' ? null : Number(item.power)})).filter((item) => item.power),
        note: dialog.querySelector('input[name=note]').value,
        source: 'manual',
      };
      const {ok, data} = await post('/api/v3/player-profiles', body);
      if (!ok || !data.ok) {
        error.textContent = (data && data.detail) || '保存失败。';
        return;
      }
      st.profiles = {...(st.profiles || {}), [storageName]: data.profile};
      dialog.close();
      if (typeof refresh === 'function') refresh();
    });
  }

  return {ensure, of, cardStrip, summary, filterRow, matches, open, chips, segMax, peakMax};
}
