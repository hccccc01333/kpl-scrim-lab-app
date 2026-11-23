/* Navigation and small interaction primitives; no business data or API ownership. */
export function createWorkbenchUI({ app, nav, labels, icon, esc, navHref, sectionFor, featureSections }) {
  const sectionLabels = Object.fromEntries(nav);
  const commands = [...new Map([
    ...nav.map(([key, label]) => [navHref(key), { href: navHref(key), label, section: key }]),
    ...Object.entries(featureSections).flatMap(([section, items]) => items.map(([key, label]) => ['#' + key, { href: '#' + key, label, section }])),
  ]).values()];
  const dialog = app.querySelector('#ui-command');
  const drawer = app.querySelector('#ui-navigation');
  const input = dialog.querySelector('input');
  const results = dialog.querySelector('[data-command-results]');
  let index = 0;
  let filtered = commands;

  function renderResults() {
    results.innerHTML = filtered.length
      ? filtered.map((item, i) => `<a id="ui-command-option-${i}" class="ui-command-result" role="option" aria-selected="${i === index}" tabindex="-1" href="${esc(item.href)}" ${i === index ? 'data-active' : ''}>
          ${icon(item.section)}<span>${esc(item.label)}<small>${esc(sectionLabels[item.section] || '工作台')}</small></span>${icon('chevron')}</a>`).join('')
      : '<div class="ui-command-empty"><b>没有找到相关页面</b><p>试试“对局”“战队”或“采集”。</p><button type="button" class="control" data-clear-command>清空搜索</button></div>';
    dialog.querySelector('[data-command-count]').textContent = `共 ${filtered.length} 个结果`;
    if (filtered.length) input.setAttribute('aria-activedescendant', `ui-command-option-${index}`);
    else input.removeAttribute('aria-activedescendant');
  }
  function openSearch() {
    // Do not put two native modals into the top layer at the same time.
    if (document.querySelector('dialog[open]')) return;
    input.value = '';
    filtered = commands;
    index = 0;
    renderResults();
    dialog.showModal();
  }
  input.addEventListener('input', () => {
    const query = input.value.trim().toLocaleLowerCase('zh-CN');
    filtered = commands.filter((item) => `${item.label} ${sectionLabels[item.section] || ''} ${item.section}`.toLocaleLowerCase('zh-CN').includes(query));
    index = 0;
    renderResults();
  });
  input.addEventListener('keydown', (event) => {
    if (event.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      index = Math.max(0, Math.min(filtered.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
      results.querySelectorAll('a').forEach((link, i) => { link.toggleAttribute('data-active', i === index); link.setAttribute('aria-selected', String(i === index)); });
      if (filtered.length) input.setAttribute('aria-activedescendant', `ui-command-option-${index}`);
      results.querySelector('[data-active]')?.scrollIntoView({ block: 'nearest' });
    }
    if (event.key === 'Enter' && filtered[index]) {
      event.preventDefault();
      dialog.close();
      location.hash = filtered[index].href;
    }
  });
  app.addEventListener('click', (event) => {
    if (event.target.closest('[data-ui-search]')) openSearch();
    if (event.target.closest('[data-ui-close]')) event.target.closest('dialog')?.close();
    if (event.target.closest('[data-clear-command]')) { input.value = ''; input.dispatchEvent(new Event('input')); input.focus(); }
    if (event.target.closest('.ui-command-result')) dialog.close();
    if (event.target.closest('#ui-navigation a, .ui-drawer-tools button')) drawer.close();
  });
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (dialog.open) dialog.close(); else openSearch();
    }
  });
  // closedby is a progressive enhancement. Older Safari keeps native Esc plus this pointer fallback.
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    for (const node of [dialog, drawer]) {
      let outsideDown = false;
      const outside = (event) => {
        const rect = node.getBoundingClientRect();
        return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
      };
      node.addEventListener('pointerdown', (event) => { outsideDown = outside(event); });
      node.addEventListener('pointerup', (event) => { if (outsideDown && outside(event)) node.close(); outsideDown = false; });
    }
  }
  app.querySelector('.desk-page-select select').addEventListener('change', (event) => {
    location.hash = event.target.value;
  });
  drawer.addEventListener('close', () => app.querySelector('.menu-button').setAttribute('aria-expanded', 'false'));
  const mobile = matchMedia('(max-width: 900px)');
  mobile.addEventListener('change', () => { if (!mobile.matches) drawer.close(); });

  return {
    closeMenu() { drawer.close(); },
    toggleMenu() {
      if (drawer.open) drawer.close();
      else { drawer.showModal(); app.querySelector('.menu-button').setAttribute('aria-expanded', 'true'); }
    },
    updateRoute(route) {
      const section = sectionFor(route.name);
      const parent = app.querySelector('[data-ui-section]');
      parent.textContent = route.name === section ? '工作台' : sectionLabels[section] || '工作台';
      parent.href = route.name === section ? '#overview' : navHref(section);
      app.querySelector('[data-ui-page]').textContent = labels[route.name] || '工作台';
      app.querySelector('#content').dataset.route = route.name;
      /* competitions 归在 setup 板块，但侧栏项的 data-nav 就是 competitions；
         直接用 section 匹配会落空，赛事页没有任何高亮。 */
      const navKey = route.name === 'competitions' ? 'competitions' : section;
      app.querySelectorAll('[data-nav]').forEach((link) => {
        if (link.dataset.nav === navKey) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
      const tabs = featureSections[section] || [];
      const secondary = app.querySelector('.secondary-wrap');
      secondary.hidden = tabs.length < 2;
      const active = { competition: 'competitions', ownership: 'setup', pending: 'setup', effect: 'reports', session: 'plan', weekly: 'reports', identity: 'players', match: 'matches', player: 'playerarchive', playerdetail: 'playerarchive', team: 'teams', hero: 'heroes', report: 'reports' }[route.name] || route.name;
      if (secondary.dataset.section === section && secondary.dataset.active === active) return;
      secondary.dataset.section = section;
      secondary.dataset.active = active;
      const picker = secondary.querySelector('select');
      picker.innerHTML = tabs.map(([key, label]) => `<option value="${esc(key)}"${key === active ? ' selected' : ''}>${esc(label)}</option>`).join('');
      secondary.classList.toggle('many-pages', tabs.length > 7);
      secondary.querySelector('nav').innerHTML = tabs.map(([key, label]) => `<a href="#${esc(key)}"${key === active ? ' aria-current="page"' : ''}>${esc(label)}</a>`).join('');
      const list = secondary.querySelector('nav');
      const selected = list.querySelector('[aria-current]');
      if (selected) list.scrollLeft += selected.getBoundingClientRect().left - list.getBoundingClientRect().left - 12;
    },
  };
}

export function loadingSkeleton(label = '正在读取赛训数据') {
  return `<div class="page ui-loading-page"><div class="ui-loading-label"><span class="ui-loading-dot"></span>${label}</div>
    <div class="ui-skeleton ui-skeleton-title" aria-hidden="true"></div>
    <div class="ui-skeleton-metrics" aria-hidden="true">${'<div class="ui-skeleton"></div>'.repeat(4)}</div>
    <div class="ui-skeleton ui-skeleton-panel" aria-hidden="true"></div></div>`;
}
