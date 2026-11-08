/* 全局 toast：右下角堆叠，支持一条操作按钮（如「撤销」）。
   用法：toast('已删除计划', {action: {label: '撤销', fn: restore}}) */
const stack = () => {
  let el = document.getElementById('toast-stack');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast-stack';
    document.body.appendChild(el);
  }
  return el;
};

export function toast(message, {type = 'info', action = null, duration = 4200} = {}) {
  const host = stack();
  const item = document.createElement('div');
  item.className = `toast ${type === 'error' ? 'is-error' : type === 'success' ? 'is-success' : ''}`;
  item.innerHTML = `<span class="toast-msg">${String(message).replace(/[&<>"]/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]))}</span>`;
  if (action?.label && typeof action.fn === 'function') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'toast-action';
    button.textContent = action.label;
    button.onclick = () => { action.fn(); dismiss(); };
    item.appendChild(button);
  }
  host.appendChild(item);
  requestAnimationFrame(() => item.classList.add('in'));
  const timer = setTimeout(dismiss, action ? duration + 3000 : duration);
  function dismiss() {
    clearTimeout(timer);
    item.classList.remove('in');
    setTimeout(() => item.remove(), 180);
  }
  return dismiss;
}

/* 便捷形态 */
toast.error = (message, options = {}) => toast(message, {...options, type: 'error', duration: 8000});
toast.success = (message, options = {}) => toast(message, {...options, type: 'success'});
