/**
 * 专业模式预设版面
 *
 * 专业模式 = 赛训组要求的默认摆法：进页就是这套块和顺序，不用自己拼。
 * 用户对专业模式做过的调整会覆盖预设（存在 layout-store 的 pro 槽）。
 * hidden 里的 '*' 表示隐藏该页所有内联旧块（仅保留预设里的超块）。
 */
import type { PageLayout } from './layout-store'

function preset(extras: string[], configs: PageLayout['configs'] = {}): PageLayout {
  return {
    order: extras.map((id) => `lib:${id}`),
    hidden: ['*'],
    extras,
    configs
  }
}

/** 在原页面内容后面追加分析块（不隐藏原块）。 */
function addBlocks(extras: string[], configs: PageLayout['configs'] = {}): PageLayout {
  return {
    order: extras.map((id) => `lib:${id}`),
    hidden: [],
    extras,
    configs
  }
}

export const PRO_PRESETS: Record<string, PageLayout> = {
  heroes: preset(['super.hero-winrate'], {
    'lib:super.hero-winrate': { side: 'own', sort: 'winRate', topN: '20', display: 'table', minGames: 1 }
  }),
  bp: preset(['super.bp-rate'], {
    'lib:super.bp-rate': { side: 'own', sort: 'total', display: 'squares', topN: '30' }
  }),
  matches: preset(['super.match-list']),
  // 决策台已拆掉：结论摘要留在概览，证据块回单局/选手页（专业模式追加在原内容之后）
  overview: addBlocks(['decision.briefing']),
  match: addBlocks(['decision.loss', 'decision.fights', 'decision.advantage', 'decision.opening']),
  players: addBlocks(['decision.resource'])
}

export function getPresetLayout(page: string): PageLayout | undefined {
  return PRO_PRESETS[page]
}

export function hasLayoutContent(layout: PageLayout | undefined): boolean {
  if (!layout) return false
  return layout.order.length > 0 || layout.hidden.length > 0 || layout.extras.length > 0 || Object.keys(layout.configs).length > 0
}
