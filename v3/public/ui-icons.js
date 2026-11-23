/* 白金转播视觉 · UI 语义图标 + 装饰件统一入口（2026-11-22）
 *
 * 两类资产：
 *   1) 语义图标（kpl-ui-icons/，48×48 金色渐变描边）：用 <img src>，避免多实例 SVG id 冲突。
 *   2) 年总装饰件（kpl-svg/）：分隔线 / 角饰 / 标题字标，用 CSS background 或 <img>。
 *
 * 用法：import { glyph, deco } from './ui-icons.js';
 *   ${glyph('book', { label: '笔记', size: 18 })}   // 按钮内图标
 *   ${deco('divider-title')}                        // 装饰分隔线
 *
 * 无障碍：glyph 默认 role="img" aria-hidden="true"（装饰性）；若图标本身要表意，
 * 传 label 会改成 role="img" aria-label。按钮的文字标签仍由调用方保留。
 */

const ICON_BASE = new URL('./kpl-ui-icons/', import.meta.url).href;
const SVG_BASE = new URL('./kpl-svg/', import.meta.url).href;

/** 语义图标文件名白名单——只认这批，避免路径注入。 */
const ICONS = new Set([
  'arrow-up', 'ban', 'book', 'bp', 'calendar', 'capture', 'chart', 'clock',
  'coach', 'compare', 'export', 'edit', 'heatmap', 'hero-pool', 'heroes', 'home',
  'matches', 'opponent', 'pick', 'players', 'refresh', 'shield', 'sources',
  'trash', 'victory', 'warning',
]);

/** 装饰件：name -> { path, aria } */
const DECO = {
  'divider-title': { path: 'decor/divider-title-gold.svg' },
  'divider-thin': { path: 'decor/divider-thin.svg' },
  'divider-light': { path: 'decor/divider-light.svg' },
  'divider-vertical-gold': { path: 'decor/divider-vertical-gold.svg' },
  'section-triangle': { path: 'decor/section-triangle.svg' },
  'corner-tl': { path: 'decor/corner-top-left.svg' },
  'corner-tr': { path: 'decor/corner-top-right.svg' },
  'corner-bl': { path: 'decor/corner-bottom-left.svg' },
  'corner-br': { path: 'decor/corner-bottom-right.svg' },
  'event-title': { path: 'broadcast/event-title-compact.svg' },
  'swatch-gold': { path: 'decor/swatch-gold.svg' },
  'swatch-teal': { path: 'decor/swatch-teal.svg' },
};

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

/**
 * 生成一个语义图标 <img>。
 * @param {string} name  ICONS 白名单内的名字
 * @param {object} opt   { label, size=18, cls='', title }
 */
export function glyph(name, opt = {}) {
  if (!ICONS.has(name)) {
    if (typeof console !== 'undefined' && console.warn) console.warn(`[ui-icons] 未知图标名: ${name}`);
    return '';
  }
  const { label = '', size = 18, cls = '', title = '' } = opt;
  const dimension = Number(size) > 0 ? Number(size) : 18;
  const aria = label
    ? `role="img" aria-label="${esc(label)}"`
    : 'role="img" aria-hidden="true"';
  const tip = title ? `<title>${esc(title)}</title>` : '';
  return `<img src="${ICON_BASE}${name}.svg" class="ui-glyph ${esc(cls)}" width="${dimension}" height="${dimension}" ${aria} alt="" ${tip} loading="lazy" decoding="async">`;
}

/** 生成一个装饰件 <img>（纯装饰，aria-hidden）。 */
export function deco(name, opt = {}) {
  const item = DECO[name];
  if (!item) return '';
  const { cls = '', title = '' } = opt;
  const tip = title ? `<title>${esc(title)}</title>` : '';
  return `<img src="${SVG_BASE}${item.path}" class="ui-deco ui-deco-${esc(name)} ${esc(cls)}" role="img" aria-hidden="true" alt="" ${tip} loading="lazy" decoding="async">`;
}

/** CSS 渐变「＋」新增图标（套件无 plus，用 token 画，避免灰描边不搭）。 */
export function plus(opt = {}) {
  const { size = 16, cls = '' } = opt;
  return `<span class="ui-plus ${esc(cls)}" style="--ui-plus-size:${Number(size) > 0 ? Number(size) : 16}px" aria-hidden="true"></span>`;
}

export const glyphNames = [...ICONS];
export default { glyph, deco, plus };
