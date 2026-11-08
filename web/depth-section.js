/* 深度分析的嵌入区块：各模块页面把原本独立的 #depth/<id> 图表
   作为本节内容的一部分按需加载，不再有「深度分析」这个独立集合。 */
import {renderDepthEntry} from '/assets/depth-page.js';
import {esc} from '/assets/design/ui.js';

/* 返回区块占位 HTML；挂载后由 bindDepthSections 绑定「生成图表」。 */
export function depthSection({id, query = '', note = '按需加载，切筛选会重新计算'} = {}) {
  return `<section class="panel dp-mount" data-depth-section data-depth-id="${esc(id)}" data-depth-query="${esc(query)}">
    <h2 class="panel-title">深入图表<em>${esc(note)}</em></h2>
    <div class="dp-mount-body">
      <div class="dp-mount-placeholder">
        <button type="button" class="button" data-depth-load>生成图表</button>
      </div>
    </div>
  </section>`;
}

export function bindDepthSections(root, {api, isCurrent}) {
  root.querySelectorAll('[data-depth-section]').forEach(section => {
    const button = section.querySelector('[data-depth-load]');
    if (!button) return;
    button.onclick = async () => {
      const body = section.querySelector('.dp-mount-body');
      button.disabled = true;
      body.innerHTML = '<div class="loading">正在生成图表…</div>';
      try {
        await renderDepthEntry(body, {
          api, isCurrent,
          id: section.dataset.depthId,
          embedded: true,
          initialQuery: section.dataset.depthQuery || '',
        });
      } catch (error) {
        body.innerHTML = `<div class="block-note">图表加载失败：${esc(error.message)}</div>`;
      }
    };
  });
}

/* 页面收尾一次挂多块：insertAdjacent + 绑定 */
export function appendDepthSections(container, specs, {api, isCurrent}) {
  if (!specs.length) return;
  container.insertAdjacentHTML('beforeend', specs.map(spec => depthSection(spec)).join(''));
  bindDepthSections(container, {api, isCurrent});
}
