import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useConnection, useSettings } from '../lib/app-context'
import { isLoopback } from '../lib/api'
import { pushToast } from '../lib/toast'
import { useHealth, useMatches, useMetadata, usePlayerBoard } from '../lib/hooks'
import { MODULE_TABS } from '../lib/routes'
import { AppMetaProvider } from '../lib/meta-context'
import { CommandPalette } from './CommandPalette'
import { ToastHost } from './ToastHost'
import { Icon } from './Icon'
import { OverviewPage } from '../pages/OverviewPage'
import { MatchesPage } from '../pages/MatchesPage'
import { MatchPage } from '../pages/MatchPage'
import { CrossPage } from '../pages/CrossPage'
import { QueryPage } from '../pages/QueryPage'
import { FeaturedPage } from '../pages/FeaturedPage'
import { RecordsPage } from '../pages/RecordsPage'
import { VersionsPage } from '../pages/VersionsPage'
import { PlayersPage } from '../pages/PlayersPage'
import { PlayerPage } from '../pages/PlayerPage'
import { PlayerArchivePage } from '../pages/PlayerArchivePage'
import { PlayerComparePage } from '../pages/PlayerComparePage'
import { LaneBoardPage } from '../pages/LaneBoardPage'
import { TeamsPage } from '../pages/TeamsPage'
import { TeamPage } from '../pages/TeamPage'
import { TeamStylePage } from '../pages/TeamStylePage'
import { TeamRosterPage } from '../pages/TeamRosterPage'
import { TeamTrainingPage } from '../pages/TeamTrainingPage'
import { HeroesPage } from '../pages/HeroesPage'
import { HeroDetailPage } from '../pages/HeroDetailPage'
import { HeroComparePage } from '../pages/HeroComparePage'
import { CombosPage } from '../pages/CombosPage'
import { BpPage } from '../pages/BpPage'
import { TeamBpPage } from '../pages/TeamBpPage'
import { CoachPage } from '../pages/CoachPage'
import { TrainingPage } from '../pages/TrainingPage'
import { TrainingEffectPage } from '../pages/TrainingEffectPage'
import { TrainingSessionPage } from '../pages/TrainingSessionPage'
import { WeeklyReportPage } from '../pages/WeeklyReportPage'
import { ReportsPage } from '../pages/ReportsPage'
import { ReportDetailPage } from '../pages/ReportDetailPage'
import { SettingsPage } from '../pages/SettingsPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { CollectPage } from '../pages/CollectPage'
import { ReviewPage } from '../pages/ReviewPage'

const navItems = [
  { to: '/', label: '概览', icon: 'overview' },
  { to: '/collect', label: '采集', icon: 'ingest' },
  { to: '/matches', label: '比赛', icon: 'matches' },
  { to: '/players', label: '选手', icon: 'players' },
  { to: '/teams', label: '战队', icon: 'teams' },
  { to: '/heroes', label: '英雄', icon: 'heroes' },
  { to: '/bp', label: 'BP', icon: 'bp' },
  { to: '/training', label: '赛训', icon: 'training' },
  { to: '/settings', label: '设置', icon: 'settings' }
] as const

const pageTitles: Record<string, string> = {
  '/': '概览',
  '/collect': '营地采集',
  '/matches': '比赛',
  '/matches/cross': '跨局分析',
  '/matches/query': '智能找局',
  '/matches/featured': '精选对局',
  '/matches/records': '训练纪录',
  '/matches/versions': '版本对比',
  '/players': '选手',
  '/players/archive': '选手档案',
  '/players/lanes': '选手与位置',
  '/players/compare': '选手对比',
  '/teams': '战队',
  '/teams/style': '战队风格',
  '/teams/roster': '战队阵容',
  '/teams/training': '战队训练',
  '/heroes': '英雄',
  '/heroes/compare': '英雄对比',
  '/heroes/combos': '英雄组合',
  '/bp': 'BP 概览',
  '/bp/team': '战队 BP',
  '/bp/coach': '教练档案',
  '/training': '训练计划',
  '/training/effect': '训练效果',
  '/training/reports': '复盘与报告',
  '/settings': '设置'
}

export function AppShell() {
  const { baseUrl, health, disconnect, retry } = useConnection()
  const { settings, update } = useSettings()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const workspaceRef = useRef<HTMLElement | null>(null)
  const lastPathRef = useRef(location.pathname)
  const lastScrollRef = useRef(0)
  const healthQuery = useHealth(baseUrl)
  const metadataQuery = useMetadata(baseUrl)
  const matchesQuery = useMatches(baseUrl)
  const playersQuery = usePlayerBoard(baseUrl)

  const meta = useMemo(() => ({
    baseUrl,
    teamName: metadataQuery.data?.teamName || '本队',
    icons: metadataQuery.data?.icons || {},
    demo: Boolean(metadataQuery.data?.demo || health?.demo)
  }), [baseUrl, metadataQuery.data, health])

  const liveHealth = healthQuery.data || health
  const offline = healthQuery.isError

  useEffect(() => {
    const base = location.pathname.startsWith('/collect/') ? '缺失值审查'
      : pageTitles[location.pathname]
      || (location.pathname.startsWith('/matches/') ? '比赛复盘'
        : location.pathname.startsWith('/players/') ? '选手详情'
          : location.pathname.startsWith('/teams/') ? '战队详情'
            : location.pathname.startsWith('/heroes/') ? '英雄详情'
            : location.pathname.startsWith('/training/sessions/') ? '训练课'
              : location.pathname.startsWith('/training/reports/') ? '报告详情'
                : location.pathname.startsWith('/training/weekly') ? '训练周报'
                  : '赛训台')
    document.title = `赛训台 · ${base}`
    try { localStorage.setItem('kpl-last-route', location.hash || '#/') } catch {}
  }, [location.pathname, location.hash])

  useEffect(() => {
    const element = workspaceRef.current
    if (!element) return
    let saveTimer = 0
    const onScroll = () => {
      lastScrollRef.current = element.scrollTop
      window.clearTimeout(saveTimer)
      saveTimer = window.setTimeout(() => {
        try { localStorage.setItem(`kpl-scroll:${lastPathRef.current}`, String(lastScrollRef.current)) } catch {}
      }, 120)
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      element.removeEventListener('scroll', onScroll)
      window.clearTimeout(saveTimer)
    }
  }, [])

  useEffect(() => {
    const element = workspaceRef.current
    if (!element) return
    if (lastPathRef.current !== location.pathname) {
      try { localStorage.setItem(`kpl-scroll:${lastPathRef.current}`, String(lastScrollRef.current)) } catch {}
      lastPathRef.current = location.pathname
      lastScrollRef.current = 0
    }
    let saved = 0
    try { saved = Number(localStorage.getItem(`kpl-scroll:${location.pathname}`) || 0) } catch {}
    const restore = () => {
      if (element.scrollTop <= 2 && saved > 0) element.scrollTop = saved
    }
    const first = window.setTimeout(restore, 120)
    const second = window.setTimeout(restore, 500)
    return () => {
      window.clearTimeout(first)
      window.clearTimeout(second)
    }
  }, [location.pathname])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const toggleTheme = () => {
    void update({ theme: settings.theme === 'light' ? 'dark' : 'light' })
  }

  const toggleDensity = () => {
    void update({ density: settings.density === 'comfortable' ? 'compact' : 'comfortable' })
  }

  const refresh = () => {
    void queryClient.invalidateQueries()
    void healthQuery.refetch()
  }

  const openWorkbench = async () => {
    try {
      const info = await window.kpl.detectWorkbench(baseUrl)
      if (!info.running && isLoopback(baseUrl)) {
        const started = await window.kpl.startWorkbench({ baseUrl, path: settings.workbenchPath || undefined })
        if (!started.ok) {
          pushToast(started.error || '工作台没有启动', 'error')
          return
        }
      }
      await window.kpl.openExternal(baseUrl)
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '打开工作台失败', 'error')
    }
  }

  return (
    <AppMetaProvider value={meta}>
      <div className="app-shell">
        <header className="titlebar">
          <a className="titlebar-brand" href="#/" onClick={(event) => { event.preventDefault(); window.location.hash = '#/' }}>
            <span className="brand-mark"><i /><i /><i /></span>
            <span className="brand-copy">
              <strong>赛训台</strong>
              <small>ANALYST CLIENT</small>
            </span>
          </a>
          <span className="titlebar-divider" />
          <button
            type="button"
            className={`connection-chip${offline ? ' is-offline' : ''}`}
            title={offline ? '与工作台的连接中断' : `工作台 ${baseUrl}`}
            onClick={refresh}
          >
            <i />
            {offline ? '工作台离线' : `工作台${liveHealth?.version ? ` · v${liveHealth.version}` : ''}`}
            {meta.demo ? ' · DEMO' : ''}
          </button>
          <button type="button" className="titlebar-search" onClick={() => setPaletteOpen(true)}>
            <Icon name="search" />
            <span>搜索比赛、选手或命令</span>
            <kbd>CTRL K</kbd>
          </button>
          <div className="titlebar-actions">
            <button type="button" className="icon-btn" onClick={refresh} title="刷新数据" aria-label="刷新数据">
              <Icon name="refresh" />
            </button>
            <button type="button" className="icon-btn" onClick={toggleTheme} title={settings.theme === 'light' ? '切换到比赛房' : '切换到纸本'} aria-label="切换主题">
              <Icon name={settings.theme === 'light' ? 'moon' : 'sun'} />
            </button>
            <button type="button" className="icon-btn" onClick={toggleDensity} title={`界面密度：${settings.density === 'comfortable' ? '舒适' : '紧凑'}`} aria-label="切换界面密度">
              <Icon name="density" />
            </button>
            <NavLink to="/settings" className="icon-btn" title="设置" aria-label="设置">
              <Icon name="settings" />
            </NavLink>
          </div>
        </header>

        <aside className="rail">
          <nav className="rail-nav" aria-label="主导航">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) => `rail-link${isActive ? ' is-active' : ''}`}
              >
                <Icon name={item.icon} />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="rail-foot">
            <button type="button" className="rail-link rail-workbench" onClick={() => void openWorkbench()} title="打开工作台">
              <Icon name="external" />
              <span>工作台</span>
            </button>
            <span className="rail-version">LOCAL · v{liveHealth?.version || '—'}</span>
          </div>
        </aside>

        <main className="workspace" ref={workspaceRef}>
          {offline ? (
            <div className="offline-bar">
              <i />
              <span>与工作台的连接中断，当前显示的是缓存数据。</span>
              <button type="button" onClick={() => { void retry(); void healthQuery.refetch(); }}>重新连接</button>
            </div>
          ) : null}
          <ModuleTabs />
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/collect" element={<CollectPage />} />
            <Route path="/collect/:id" element={<ReviewPage />} />
            <Route path="/matches" element={<MatchesPage />} />
            <Route path="/matches/cross" element={<CrossPage />} />
            <Route path="/matches/query" element={<QueryPage />} />
            <Route path="/matches/featured" element={<FeaturedPage />} />
            <Route path="/matches/records" element={<RecordsPage />} />
            <Route path="/matches/versions" element={<VersionsPage />} />
            <Route path="/matches/:key" element={<MatchPage />} />
            <Route path="/players" element={<PlayersPage />} />
            <Route path="/players/archive" element={<PlayerArchivePage />} />
            <Route path="/players/lanes" element={<LaneBoardPage />} />
            <Route path="/players/compare" element={<PlayerComparePage />} />
            <Route path="/players/:key" element={<PlayerPage />} />
            <Route path="/teams" element={<TeamsPage />} />
            <Route path="/teams/style" element={<TeamStylePage />} />
            <Route path="/teams/roster" element={<TeamRosterPage />} />
            <Route path="/teams/training" element={<TeamTrainingPage />} />
            <Route path="/teams/:id" element={<TeamPage />} />
            <Route path="/heroes" element={<HeroesPage />} />
            <Route path="/heroes/compare" element={<HeroComparePage />} />
            <Route path="/heroes/combos" element={<CombosPage />} />
            <Route path="/heroes/:hero" element={<HeroDetailPage />} />
            <Route path="/bp" element={<BpPage />} />
            <Route path="/bp/team" element={<TeamBpPage />} />
            <Route path="/bp/coach" element={<CoachPage />} />
            <Route path="/training" element={<TrainingPage />} />
            <Route path="/training/effect" element={<TrainingEffectPage />} />
            <Route path="/training/reports" element={<ReportsPage />} />
            <Route path="/training/reports/:id" element={<ReportDetailPage />} />
            <Route path="/training/sessions/:id" element={<TrainingSessionPage />} />
            <Route path="/training/weekly" element={<WeeklyReportPage />} />
            <Route path="/training/weekly/:start" element={<WeeklyReportPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>

      <ToastHost />

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        matches={matchesQuery.data || []}
        players={playersQuery.data?.roster || []}
        onTheme={toggleTheme}
        onDensity={toggleDensity}
        onRefresh={refresh}
        onOpenWorkbench={openWorkbench}
        onDisconnect={disconnect}
      />
    </AppMetaProvider>
  )
}

function ModuleTabs() {
  const { pathname } = useLocation()
  const tabs = pathname.startsWith('/matches')
    ? MODULE_TABS.matches
    : pathname.startsWith('/players')
    ? MODULE_TABS.players
    : pathname.startsWith('/teams')
      ? MODULE_TABS.teams
      : pathname.startsWith('/heroes')
        ? MODULE_TABS.heroes
        : pathname.startsWith('/bp')
          ? MODULE_TABS.bp
          : pathname.startsWith('/training')
            ? MODULE_TABS.training
            : null
  if (!tabs) return null
  return (
    <nav className="module-tabs" aria-label="模块子页面">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={'end' in tab ? tab.end : false}
          className={({ isActive }) => `module-tab${isActive ? ' is-active' : ''}`}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
