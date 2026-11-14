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

/* 决策分析块（资源异常等）已内联到选手页等页面，默认可见；专业模式不再重复追加，
   需要时用户仍可从「分析库」把它们加回当前页。 */
export const PRO_PRESETS: Record<string, PageLayout> = {
  heroes: preset(['super.hero-winrate'], {
    'lib:super.hero-winrate': { side: 'own', sort: 'winRate', topN: '20', display: 'table', minGames: 1 }
  }),
  bp: preset(['super.bp-rate'], {
    'lib:super.bp-rate': { side: 'own', sort: 'total', display: 'squares', topN: '30' }
  }),
  matches: preset(['super.match-list'])
}

export function getPresetLayout(page: string): PageLayout | undefined {
  return PRO_PRESETS[page]
}

export function hasLayoutContent(layout: PageLayout | undefined): boolean {
  if (!layout) return false
  return layout.order.length > 0 || layout.hidden.length > 0 || layout.extras.length > 0 || Object.keys(layout.configs).length > 0
}
