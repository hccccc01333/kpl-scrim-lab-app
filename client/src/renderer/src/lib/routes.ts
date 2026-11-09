export const playerPath = (name: string) => `/players/${encodeURIComponent(name)}`
export const teamPath = (id: string) => `/teams/${encodeURIComponent(id)}`
export const heroPath = (hero: string) => `/heroes/${encodeURIComponent(hero)}`
export const matchPath = (key: string) => `/matches/${encodeURIComponent(key)}`

export const MODULE_TABS = {
  matches: [
    { to: '/matches', label: '对局档案', end: true },
    { to: '/matches/cross', label: '跨局分析' },
    { to: '/matches/query', label: '智能找局' },
    { to: '/matches/featured', label: '精选对局' },
    { to: '/matches/records', label: '训练纪录' },
    { to: '/matches/versions', label: '版本对比' }
  ],
  players: [
    { to: '/players/archive', label: '选手档案' },
    { to: '/players', label: '名单与状态', end: true },
    { to: '/players/lanes', label: '选手与位置' },
    { to: '/players/compare', label: '选手对比' }
  ],
  teams: [
    { to: '/teams', label: '战队档案', end: true },
    { to: '/teams/style', label: '战队风格' },
    { to: '/teams/roster', label: '战队阵容' },
    { to: '/teams/training', label: '战队训练' }
  ],
  heroes: [
    { to: '/heroes', label: '英雄榜', end: true },
    { to: '/heroes/compare', label: '英雄对比' },
    { to: '/heroes/combos', label: '英雄组合' }
  ],
  training: [
    { to: '/training', label: '训练计划', end: true },
    { to: '/training/reports', label: '复盘与报告' }
  ],
  bp: [
    { to: '/bp', label: 'BP 概览', end: true },
    { to: '/bp/team', label: '战队 BP' },
    { to: '/bp/coach', label: '教练档案' }
  ]
} as const
