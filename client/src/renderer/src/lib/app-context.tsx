import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from 'react'
import { api, normalizeBase } from './api'
import type { Health } from './types'
import type { Settings } from './bridge'

type ConnectionPhase = 'boot' | 'checking' | 'connected' | 'error'

interface SettingsContextValue {
  settings: Settings
  ready: boolean
  update: (patch: Partial<Settings>) => Promise<Settings>
}

interface ConnectionContextValue {
  phase: ConnectionPhase
  baseUrl: string
  health: Health | null
  error: string
  busy: boolean
  recent: string[]
  connect: (url: string) => Promise<boolean>
  disconnect: () => void
  retry: () => Promise<void>
  startLocal: (url?: string) => Promise<void>
}

const SettingsContext = createContext<SettingsContextValue | null>(null)
const ConnectionContext = createContext<ConnectionContextValue | null>(null)

const FALLBACK_SETTINGS: Settings = {
  baseUrl: 'http://127.0.0.1:8766',
  theme: 'light',
  density: 'comfortable',
  minimizeToTray: false,
  workbenchPath: ''
}

function applyDocumentPreferences(settings: Settings): void {
  document.documentElement.dataset.theme = settings.theme
  document.documentElement.dataset.density = settings.density
  try {
    localStorage.setItem('kpl-theme', settings.theme)
    localStorage.setItem('kpl-density', settings.density)
  } catch {
    /* storage can be unavailable; preferences still apply for this run */
  }
  void window.kpl?.setTitleBarTheme(settings.theme)
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(FALLBACK_SETTINGS)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let alive = true
    if (!window.kpl) {
      applyDocumentPreferences(FALLBACK_SETTINGS)
      setReady(true)
      return
    }
    window.kpl
      .getSettings()
      .then((next) => {
        if (!alive) return
        setSettings(next)
        applyDocumentPreferences(next)
      })
      .catch(() => {
        if (alive) applyDocumentPreferences(FALLBACK_SETTINGS)
      })
      .finally(() => {
        if (alive) setReady(true)
      })
    return () => { alive = false }
  }, [])

  const update = useCallback(async (patch: Partial<Settings>) => {
    const next = await window.kpl.setSettings(patch)
    setSettings(next)
    applyDocumentPreferences(next)
    return next
  }, [])

  const value = useMemo(() => ({ settings, ready, update }), [settings, ready, update])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const { settings, ready, update } = useSettings()
  const [phase, setPhase] = useState<ConnectionPhase>('boot')
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [recent, setRecent] = useState<string[]>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem('kpl-recent-connections') || '[]')
      return Array.isArray(raw) ? raw.filter((item) => typeof item === 'string').slice(0, 5) : []
    } catch {
      return []
    }
  })

  const remember = useCallback((url: string) => {
    setRecent((current) => {
      const next = [url, ...current.filter((item) => item !== url)].slice(0, 5)
      try { localStorage.setItem('kpl-recent-connections', JSON.stringify(next)) } catch {}
      return next
    })
  }, [])

  const connect = useCallback(async (value: string) => {
    const keepCurrent = phase === 'connected'
    setBusy(true)
    setError('')
    if (!keepCurrent) setPhase('checking')
    let url = ''
    try {
      url = normalizeBase(value)
      const result = await api<Health>(url, '/api/health', { timeout: 6000 })
      if (!result?.ok) throw new Error('工作台返回了异常状态')
      setBaseUrl(url)
      setHealth(result)
      setPhase('connected')
      remember(url)
      await update({ baseUrl: url })
      return true
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      setError(message.includes('fetch failed') || message.includes('Failed to fetch') || message.includes('ECONNREFUSED')
        ? '连不上这个地址。确认工作台已经启动，或检查端口和局域网地址。'
        : message)
      if (!keepCurrent) setPhase('error')
      return false
    } finally {
      setBusy(false)
    }
  }, [phase, remember, update])

  useEffect(() => {
    if (!ready) return
    if (phase !== 'boot') return
    setBaseUrl(settings.baseUrl)
    void connect(settings.baseUrl)
  }, [ready, phase, settings.baseUrl, connect])

  const retry = useCallback(async () => {
    await connect(baseUrl || settings.baseUrl)
  }, [baseUrl, settings.baseUrl, connect])

  const startLocal = useCallback(async (url?: string) => {
    setBusy(true)
    setError('')
    const target = url || settings.baseUrl
    try {
      const detected = await window.kpl.detectWorkbench(target)
      if (detected.running) {
        await connect(target)
        return
      }
      const started = await window.kpl.startWorkbench({
        baseUrl: target,
        path: settings.workbenchPath || undefined
      })
      if (!started.ok) throw new Error(started.error || '工作台没有启动')
      await connect(target)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      setPhase('error')
    } finally {
      setBusy(false)
    }
  }, [settings.baseUrl, settings.workbenchPath, connect])

  const disconnect = useCallback(() => {
    setPhase('error')
    setHealth(null)
    setError('已断开连接')
  }, [])

  const value = useMemo<ConnectionContextValue>(() => ({
    phase,
    baseUrl,
    health,
    error,
    busy,
    recent,
    connect,
    disconnect,
    retry,
    startLocal
  }), [phase, baseUrl, health, error, busy, recent, connect, disconnect, retry, startLocal])

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>
}

export function useSettings(): SettingsContextValue {
  const value = useContext(SettingsContext)
  if (!value) throw new Error('useSettings 必须在 SettingsProvider 内使用')
  return value
}

export function useConnection(): ConnectionContextValue {
  const value = useContext(ConnectionContext)
  if (!value) throw new Error('useConnection 必须在 ConnectionProvider 内使用')
  return value
}
