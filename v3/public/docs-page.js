/* 工作台内文档页：像库文档一样，左边目录，右边一次读一章。
   内容单一信息源来自 help-content.js（由 docs/guide/content.json 生成）。 */
import { helpContent } from './help-content.js';
import { diagnosticBlock, bindDiagnosticCopy } from './diagnostics.js';

export function createDocsPage({ esc, icon }) {
  const external = (href, label, extra = '') => `<a href="${esc(href)}"${extra}>${esc(label)}</a>`;
  const chapters = [
    ...(helpContent.sections || []).map((s) => ({ ...s, kind: 'section' })),
    { id: 'errors', title: '错误码索引', group: '设置与帮助', lead: helpContent.errorsIntro || '', kind: 'errors' },
    { id: 'feedback', title: '反馈与支持', group: '设置与帮助', lead: '', kind: 'feedback' },
    { id: 'about', title: '关于作者与项目来源', group: '设置与帮助', lead: '', kind: 'about' },
  ];
  const byId = new Map(chapters.map((c) => [c.id, c]));
  let active = chapters[0]?.id || '';
  let unbindCopy = () => {};

  function readChapterFromHash() {
    try {
      const query = new URLSearchParams(location.hash.split('?')[1] || '');
      const id = query.get('chapter') || '';
      return byId.has(id) ? id : chapters[0]?.id || '';
    } catch { return chapters[0]?.id || ''; }
  }

  function featureCard(feature) {
    const codes = (feature.errorCodes || []).map((code) =>
      `<a class="help-code" href="#errors" data-help-chapter="errors">${esc(code)}</a>`).join('');
    const list = (items, cls) => (items || []).length
      ? `<ul class="${cls}">${items.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : '';
    const steps = (feature.steps || []).length
      ? `<h4>一步一步做</h4><ol class="help-steps">${feature.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : '';
    const explain = (feature.explain || []).length
      ? `<h4>这里面的门道</h4>${list(feature.explain, 'help-explain')}` : '';
    const tips = (feature.tips || []).length
      ? `<details class="help-disclosure" open><summary>小提醒 <span>${feature.tips.length}</span></summary>${list(feature.tips, 'help-notes')}</details>` : '';
    const faq = (feature.faq || []).length
      ? `<details class="help-disclosure"><summary>常见问题 <span>${feature.faq.length}</span></summary>${feature.faq.map((item) =>
        `<div class="help-qa"><b>${esc(item.q)}</b><p>${esc(item.a)}</p></div>`).join('')}</details>` : '';
    const issues = (feature.issues || []).length
      ? `<details class="help-disclosure"><summary>已知限制 <span>${feature.issues.length}</span></summary>${list(feature.issues, 'help-notes')}</details>` : '';
    return `<article class="help-card" id="help-feature-${esc(feature.id)}">
      <div class="help-card-head"><h3>${esc(feature.title)}</h3>${external(feature.route || '#overview', '去这个页面 ↗', ' class="help-card-link"')}</div>
      ${feature.plain ? `<p class="help-plain">${esc(feature.plain)}</p>` : ''}
      ${feature.when ? `<p class="help-when"><b>什么时候用：</b>${esc(feature.when)}</p>` : ''}
      ${steps}${explain}${tips}${faq}${issues}
      ${codes ? `<div class="help-codes"><span>相关错误码</span>${codes}</div>` : ''}
    </article>`;
  }

  function sectionChapter(chapter) {
    const features = chapter.features || [];
    const mini = features.length
      ? `<nav class="help-mini" aria-label="本章小节"><span>本章内容</span>${features.map((f) =>
        `<a href="#help-feature-${esc(f.id)}" data-help-anchor="help-feature-${esc(f.id)}">${esc(f.title)}</a>`).join('')}</nav>` : '';
    return `${mini}<div class="help-card-grid">${features.map(featureCard).join('')}</div>`;
  }

  function errorsChapter() {
    const rows = Object.entries(helpContent.errors || {}).map(([code, entry]) => `<tr>
      <td><code>${esc(code)}</code></td>
      <td><b>${esc(entry.title)}</b></td>
      <td>${esc(entry.cause)}</td>
      <td>${esc(entry.action)}</td>
      <td><code>${esc(entry.owner)}</code></td>
      <td><span class="help-status ${entry.status === '已接入' ? 'is-live' : ''}">${esc(entry.status)}</span></td>
    </tr>`).join('');
    return `<div class="table-wrap"><table class="help-table"><thead><tr><th>错误码</th><th>是什么问题</th><th>常见原因</th><th>你可以怎么做</th><th>代码位置</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="help-note-line">标注「预留」的错误码已经登记好含义，但界面还没接上；界面上看到的码一定是「已接入」。</p>`;
  }

  function feedbackChapter() {
    const feedback = helpContent.feedback || {};
    return `<div class="help-feedback-card">
      <div>
        <span class="help-kicker">反馈渠道</span>
        <b>${esc(feedback.channel || '项目反馈群')}</b>
        <p>${esc(feedback.channelValue || '待公布')}</p>
      </div>
      <img class="help-qr" src="static/media/qq-group-qr.jpg" alt="赛训工具群二维码，用手机 QQ 扫一扫加入" width="220" height="220">
    </div>
    ${feedback.groupNumber ? `<div class="help-qq-row">
      <span>群号</span><code id="help-qq-group" tabindex="0">${esc(feedback.groupNumber)}</code>
      <div class="dx-copy">
        <button type="button" class="control" data-diagnostic-copy aria-controls="help-qq-group">复制群号</button>
        <span class="dx-copy-tip" role="status" aria-live="polite"></span>
      </div>
    </div>` : ''}
    <p class="help-when"><b>怎么用：</b>${esc(feedback.intro || '')}</p>
    <h3>反馈模板</h3>
    <div class="dx-block">
      <div class="dx-head"><b>复制后按实际情况填写</b><span>不要粘贴对局数据</span></div>
      <pre class="dx-text" id="help-feedback-template" tabindex="0"><code>${esc(feedback.template || '')}</code></pre>
      <div class="dx-copy">
        <button type="button" class="control" data-diagnostic-copy aria-controls="help-feedback-template">复制反馈模板</button>
        <span class="dx-copy-tip" role="status" aria-live="polite"></span>
      </div>
    </div>
    <h3>诊断信息长什么样</h3>
    ${diagnosticBlock({ code: 'E-SYS-002' })}
    <div class="help-privacy"><b>这些不要发到群里</b><ul>${(feedback.privacy || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul></div>`;
  }

  function aboutChapter() {
    const about = helpContent.about || {};
    return `<div class="help-about-card">
      <span class="help-kicker">作者</span><b>${esc(about.author || '')}</b>
      <p>${esc(about.origin || '')}</p>
      <h3>这个工具坚持的三件事</h3>
      <ul class="help-notes">${(about.principles || []).map((p) => `<li>${esc(p)}</li>`).join('')}</ul>
      <div class="help-links">${(about.links || []).map((item) =>
        external(item.url, item.label + ' ↗', ' class="help-external" target="_blank" rel="noopener noreferrer"')).join('')}</div>
    </div>`;
  }

  function chapterBody(chapter) {
    if (chapter.kind === 'errors') return errorsChapter();
    if (chapter.kind === 'feedback') return feedbackChapter();
    if (chapter.kind === 'about') return aboutChapter();
    return sectionChapter(chapter);
  }

  function crumb(chapter) {
    const items = [
      `<li><a href="#docs" data-help-chapter="${esc(chapters[0].id)}">文档首页</a></li>`,
      `<li><span>${esc(chapter.group || '文档')}</span></li>`,
      `<li><a href="#docs?chapter=${esc(chapter.id)}" data-help-chapter="${esc(chapter.id)}" aria-current="page">${esc(chapter.title)}</a></li>`,
    ];
    return `<nav class="help-crumb" aria-label="文档位置"><ol>${items.join('')}</ol></nav>`;
  }

  function pager(chapter) {
    const index = chapters.findIndex((c) => c.id === chapter.id);
    const prev = chapters[index - 1];
    const next = chapters[index + 1];
    return `<nav class="help-pager" aria-label="翻页">
      ${prev ? `<button type="button" class="control" data-help-chapter="${esc(prev.id)}">← ${esc(prev.title)}</button>` : '<span></span>'}
      ${next ? `<button type="button" class="control" data-help-chapter="${esc(next.id)}">${esc(next.title)} →</button>` : '<span></span>'}
    </nav>`;
  }

  function chapterHtml(chapter) {
    return `${crumb(chapter)}
      <header class="help-chapter-head">
        <span class="help-kicker">${esc(chapter.group || '文档')}</span>
        <h1>${esc(chapter.title)}</h1>
        ${chapter.lead ? `<p>${esc(chapter.lead)}</p>` : ''}
      </header>
      <div class="help-chapter-body">${chapterBody(chapter)}</div>
      ${pager(chapter)}`;
  }

  function toc() {
    const groups = [];
    for (const chapter of chapters) {
      const name = chapter.group || '文档';
      let group = groups.find((g) => g.name === name);
      if (!group) { group = { name, items: [] }; groups.push(group); }
      group.items.push(chapter);
    }
    return `<label class="help-search"><span>搜索章节</span><input type="search" data-help-search placeholder="输入关键词…" autocomplete="off"></label>
      <nav class="help-toc" aria-label="文档目录">${groups.map((g) => `<div class="help-toc-group" data-group="${esc(g.name)}">
        <span class="help-toc-title">${esc(g.name)}</span>
        ${g.items.map((c) => `<a href="#docs?chapter=${esc(c.id)}" data-help-chapter="${esc(c.id)}" data-help-text="${esc((c.title + ' ' + (c.lead || '')).toLowerCase())}">${esc(c.title)}</a>`).join('')}
      </div>`).join('')}</nav>`;
  }

  function render() {
    active = readChapterFromHash();
    const chapter = byId.get(active) || chapters[0];
    return `<div class="page help-page">
      <header class="help-top">
        <span class="help-kicker">${icon('docs')} 工作台文档</span>
        <div><h1>${esc(helpContent.title || '使用文档')}</h1><p>${esc(helpContent.subtitle || '')}</p></div>
        <small>版本 v${esc(helpContent.version || '')} · 内容源自 <code>docs/guide/content.json</code></small>
      </header>
      <div class="help-layout">
        <aside class="help-aside">${toc()}<p class="help-aside-note">左边选章节，右边只读这一章。遇到看不懂的词，去「名词解释」查。</p></aside>
        <section class="help-chapter" id="help-chapter" tabindex="-1">${chapterHtml(chapter)}</section>
      </div>
    </div>`;
  }

  function syncToc(root) {
    root.querySelectorAll('.help-toc a[data-help-chapter]').forEach((a) => {
      if (a.dataset.helpChapter === active) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
  }

  function mountChapter(root, chapter) {
    const pane = root.querySelector('#help-chapter');
    if (!pane) return;
    unbindCopy();
    pane.innerHTML = chapterHtml(chapter);
    unbindCopy = bindDiagnosticCopy(pane);
    syncToc(root);
    pane.scrollIntoView({ block: 'start' });
    pane.focus({ preventScroll: true });
  }

  function bind(root) {
    if (!root) return () => {};
    const pane = root.querySelector('#help-chapter');
    unbindCopy = bindDiagnosticCopy(pane);
    syncToc(root);
    const onClick = (event) => {
      const chapterLink = event.target.closest?.('[data-help-chapter]');
      if (chapterLink && root.contains(chapterLink)) {
        event.preventDefault();
        const id = chapterLink.dataset.helpChapter;
        const chapter = byId.get(id);
        if (!chapter) return;
        active = id;
        try { history.replaceState(null, '', `#docs?chapter=${encodeURIComponent(id)}`); } catch {}
        mountChapter(root, chapter);
        return;
      }
      const anchor = event.target.closest?.('[data-help-anchor]');
      if (anchor && root.contains(anchor)) {
        event.preventDefault();
        document.getElementById(anchor.dataset.helpAnchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    };
    const onSearch = (event) => {
      const term = (event.target.value || '').trim().toLowerCase();
      root.querySelectorAll('.help-toc-group').forEach((group) => {
        let visible = 0;
        group.querySelectorAll('a[data-help-text]').forEach((a) => {
          const show = !term || a.dataset.helpText.includes(term);
          a.hidden = !show;
          if (show) visible += 1;
        });
        group.hidden = visible === 0;
      });
    };
    root.addEventListener('click', onClick);
    root.querySelector('[data-help-search]')?.addEventListener('input', onSearch);
    return () => {
      root.removeEventListener('click', onClick);
      root.querySelector('[data-help-search]')?.removeEventListener('input', onSearch);
      unbindCopy();
    };
  }

  return { render, bind };
}
