import { lazy, Suspense, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useConnection, useSettings } from '../lib/app-context'
import { isLoopback } from '../lib/api'
import { pushToast } from '../lib/toast'
import { MODE_LABELS, getSnapshot, setMode, subscribe, type LayoutMode } from '../blocks/layout-store'
import { useHealth, useMatches, useMetadata, usePlayerBoard } from '../lib/hooks'
import { MODULE_TABS } from '../lib/routes'
import { AppMetaProvider } from '../lib/meta-context'
import { CommandPalette } from './CommandPalette'
import { ToastHost } from './ToastHost'
import { Icon } from './Icon'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { SkeletonPage } from './ui'
const OverviewPage = lazy(() => import('../pages/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const MatchesPage = lazy(() => import('../pages/MatchesPage').then((module) => ({ default: module.MatchesPage })))
const MatchPage = lazy(() => import('../pages/MatchPage').then((module) => ({ default: module.MatchPage })))
const CrossPage = lazy(() => import('../pages/CrossPage').then((module) => ({ default: module.CrossPage })))
const FeaturedPage = lazy(() => import('../pages/FeaturedPage').then((module) => ({ default: module.FeaturedPage })))
const VersionsPage = lazy(() => import('../pages/VersionsPage').then((module) => ({ default: module.VersionsPage })))
const PlayersPage = lazy(() => import('../pages/PlayersPage').then((module) => ({ default: module.PlayersPage })))
const PlayerPage = lazy(() => import('../pages/PlayerPage').then((module) => ({ default: module.PlayerPage })))
const PlayerArchivePage = lazy(() => import('../pages/PlayerArchivePage').then((module) => ({ default: module.PlayerArchivePage })))
const PlayerComparePage = lazy(() => import('../pages/PlayerComparePage').then((module) => ({ default: module.PlayerComparePage })))
const TeamsPage = lazy(() => import('../pages/TeamsPage').then((module) => ({ default: module.TeamsPage })))
const TeamPage = lazy(() => import('../pages/TeamPage').then((module) => ({ default: module.TeamPage })))
const TeamTrainingPage = lazy(() => import('../pages/TeamTrainingPage').then((module) => ({ default: module.TeamTrainingPage })))
const HeroesPage = lazy(() => import('../pages/HeroesPage').then((module) => ({ default: module.HeroesPage })))
const HeroDetailPage = lazy(() => import('../pages/HeroDetailPage').then((module) => ({ default: module.HeroDetailPage })))
const HeroComparePage = lazy(() => import('../pages/HeroComparePage').then((module) => ({ default: module.HeroComparePage })))
const CombosPage = lazy(() => import('../pages/CombosPage').then((module) => ({ default: module.CombosPage })))
const BpPage = lazy(() => import('../pages/BpPage').then((module) => ({ default: module.BpPage })))
const TeamBpPage = lazy(() => import('../pages/TeamBpPage').then((module) => ({ default: module.TeamBpPage })))
const CoachPage = lazy(() => import('../pages/CoachPage').then((module) => ({ default: module.CoachPage })))
const TrainingPage = lazy(() => import('../pages/TrainingPage').then((module) => ({ default: module.TrainingPage })))
const TrainingEffectPage = lazy(() => import('../pages/TrainingEffectPage').then((module) => ({ default: module.TrainingEffectPage })))
const TrainingSessionPage = lazy(() => import('../pages/TrainingSessionPage').then((module) => ({ default: module.TrainingSessionPage })))
const WeeklyReportPage = lazy(() => import('../pages/WeeklyReportPage').then((module) => ({ default: module.WeeklyReportPage })))
const ReportsPage = lazy(() => import('../pages/ReportsPage').then((module) => ({ default: module.ReportsPage })))
const ReportDetailPage = lazy(() => import('../pages/ReportDetailPage').then((module) => ({ default: module.ReportDetailPage })))
const SettingsPage = lazy(() => import('../pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))
const NotFoundPage = lazy(() => import('../pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })))
const CollectPage = lazy(() => import('../pages/CollectPage').then((module) => ({ default: module.CollectPage })))
const ReviewPage = lazy(() => import('../pages/ReviewPage').then((module) => ({ default: module.ReviewPage })))
const StudioPage = lazy(() => import('../pages/StudioPage').then((module) => ({ default: module.StudioPage })))

const navItems = [
  { to: '/', label: '概览', icon: 'overview' },
  { to: '/studio', label: '看板', icon: 'layout' },
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
  '/studio': '我的看板',
  '/collect': '营地采集',
  '/matches': '比赛',
  '/matches/cross': '跨局分析',
  '/matches/featured': '精选对局',
  '/matches/versions': '版本对比',
  '/players': '选手',
  '/players/archive': '选手档案',
  '/players/compare': '选手对比',
  '/teams': '战队',
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

const MODE_ORDER: LayoutMode[] = ['public', 'pro', 'custom']

export function AppShell() {
  const { baseUrl, health, disconnect, retry } = useConnection()
  const { settings, update } = useSettings()
  const layoutStore = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
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

  const cycleMode = () => {
    const next = MODE_ORDER[(MODE_ORDER.indexOf(layoutStore.mode) + 1) % MODE_ORDER.length]
    setMode(next)
    pushToast(`已切换到${MODE_LABELS[next]}模式`, 'success')
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
      <a className="client-skip" href="#workspace-content" onClick={(event) => { event.preventDefault(); workspaceRef.current?.focus() }}>跳至主要内容</a>
      <div className="app-shell">
        <header className="titlebar">
          <a className="titlebar-brand" href="#/" onClick={(event) => { event.preventDefault(); window.location.hash = '#/' }}>
            <span className="brand-mark"><i /><i /><i /></span>
            <span className="brand-copy">
              <strong>赛训台</strong>
              <small>ANALYST CLIENT</small>
              {meta.demo ? <span className="client-demo-badge">演示数据</span> : null}
            </span>
          </a>
          <nav className="client-top-nav" aria-label="主导航">
            {navItems.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => `client-top-link${isActive ? ' is-active' : ''}`}>{item.label}</NavLink>
            ))}
          </nav>
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
          <button type="button" className="titlebar-search" onClick={() => setPaletteOpen(true)} aria-label="搜索比赛、选手或命令">
            <Icon name="search" />
            <span>搜索比赛、选手或命令</span>
            <kbd>CTRL K</kbd>
          </button>
          <div className="titlebar-actions">
            <button type="button" className="mode-chip" title="切换布局模式：全面 / 专业 / 自定义" onClick={cycleMode}>
              {MODE_LABELS[layoutStore.mode]}模式
            </button>
            <button type="button" className="icon-btn" onClick={refresh} title="刷新数据" aria-label="刷新数据">
              <Icon name="refresh" />
            </button>
            <button type="button" className="icon-btn" onClick={toggleTheme} title={settings.theme === 'light' ? '切换深色主题' : '切换浅色主题'} aria-label="切换主题">
              <Icon name={settings.theme === 'light' ? 'moon' : 'sun'} />
            </button>
            <button type="button" className="icon-btn" onClick={toggleDensity} title={`界面密度：${settings.density === 'comfortable' ? '舒适' : '紧凑'}`} aria-label="切换界面密度">
              <Icon name="density" />
            </button>
            <button type="button" className="icon-btn" onClick={() => void openWorkbench()} title="打开工作台" aria-label="打开工作台"><Icon name="external" /></button>
            <NavLink to="/settings" className="icon-btn" title="设置" aria-label="设置">
              <Icon name="settings" />
            </NavLink>
          </div>
        </header>



        <main id="workspace-content" className="workspace" ref={workspaceRef} tabIndex={-1}>
          {offline ? (
            <div className="offline-bar">
              <i />
              <span>与工作台的连接中断，当前显示的是缓存数据。</span>
              <button type="button" onClick={() => { void retry(); void healthQuery.refetch(); }}>重新连接</button>
            </div>
          ) : null}
          <ModuleTabs />
          <RouteErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<SkeletonPage cards={2} />}>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/studio" element={<StudioPage />} />
            <Route path="/collect" element={<CollectPage />} />
            <Route path="/collect/:id" element={<ReviewPage />} />
            <Route path="/matches" element={<MatchesPage />} />
            <Route path="/matches/cross" element={<CrossPage />} />
            <Route path="/matches/query" element={<Navigate to="/matches" replace />} />
            <Route path="/matches/featured" element={<FeaturedPage />} />
            <Route path="/matches/records" element={<Navigate to="/matches/featured" replace />} />
            <Route path="/matches/versions" element={<VersionsPage />} />
            <Route path="/matches/:key" element={<MatchPage />} />
            <Route path="/players" element={<PlayersPage />} />
            <Route path="/players/archive" element={<PlayerArchivePage />} />
            <Route path="/players/lanes" element={<Navigate to="/players" replace />} />
            <Route path="/players/compare" element={<PlayerComparePage />} />
            <Route path="/players/:key" element={<PlayerPage />} />
            <Route path="/teams" element={<TeamsPage />} />
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
          </Suspense>
          </RouteErrorBoundary>
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
