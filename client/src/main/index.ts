import {
  app,
  BrowserWindow,
  Menu,
  Notification,
  Tray,
  ipcMain,
  nativeImage,
  screen,
  shell
} from 'electron'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'

type Theme = 'light' | 'dark'
type Density = 'comfortable' | 'compact'

interface WindowBounds {
  x?: number
  y?: number
  width: number
  height: number
  maximized?: boolean
}

interface Settings {
  baseUrl: string
  theme: Theme
  density: Density
  minimizeToTray: boolean
  workbenchPath: string
  windowBounds?: WindowBounds
}

const DEFAULT_SETTINGS: Settings = {
  baseUrl: 'http://127.0.0.1:8766',
  theme: 'light',
  density: 'comfortable',
  minimizeToTray: false,
  workbenchPath: ''
}

const APP_ID = 'com.kpl.scrimdesk'
const PROTOCOL = 'kpl-client'
const isDev = !app.isPackaged
let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let isQuitting = false
let saveBoundsTimer: NodeJS.Timeout | null = null

app.setAppUserModelId(APP_ID)
if (process.defaultApp) {
  if (process.argv.length >= 2) app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [resolve(process.argv[1])])
} else {
  app.setAsDefaultProtocolClient(PROTOCOL)
}
if (process.env.KPL_CLIENT_USER_DATA) {
  app.setPath('userData', process.env.KPL_CLIENT_USER_DATA)
}

function userDataFile(name: string): string {
  return join(app.getPath('userData'), name)
}

function log(message: string): void {
  try {
    const dir = join(app.getPath('userData'), 'logs')
    mkdirSync(dir, { recursive: true })
    const file = join(dir, 'main.log')
    if (existsSync(file) && statSync(file).size > 2 * 1024 * 1024) {
      writeFileSync(file, '', 'utf8')
    }
    writeFileSync(file, `[${new Date().toISOString()}] ${message}\n`, { flag: 'a' })
  } catch {
    /* logging must never break the app */
  }
}

function readSettings(): Settings {
  try {
    const raw = JSON.parse(readFileSync(userDataFile('settings.json'), 'utf8'))
    return {
      ...DEFAULT_SETTINGS,
      ...raw,
      theme: raw?.theme === 'dark' ? 'dark' : 'light',
      density: raw?.density === 'compact' ? 'compact' : 'comfortable',
      minimizeToTray: Boolean(raw?.minimizeToTray),
      baseUrl: typeof raw?.baseUrl === 'string' && raw.baseUrl ? raw.baseUrl : DEFAULT_SETTINGS.baseUrl,
      workbenchPath: typeof raw?.workbenchPath === 'string' ? raw.workbenchPath : ''
    }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

let settings = readSettings()

function writeSettings(patch: Partial<Settings>): Settings {
  settings = { ...settings, ...patch }
  try {
    writeFileSync(userDataFile('settings.json'), JSON.stringify(settings, null, 2), 'utf8')
  } catch (error) {
    log(`write settings failed: ${String(error)}`)
  }
  return settings
}

function assetPath(name: string): string {
  if (isDev) return join(app.getAppPath(), 'build', name)
  return join(process.resourcesPath, name)
}

function iconImage() {
  const icon = assetPath('icon.png')
  if (existsSync(icon)) return nativeImage.createFromPath(icon)
  return nativeImage.createEmpty()
}

function validBounds(bounds?: WindowBounds): WindowBounds {
  const area = screen.getPrimaryDisplay().workArea
  const fallback: WindowBounds = {
    width: Math.min(1440, Math.max(980, area.width - 40)),
    height: Math.min(900, Math.max(600, area.height - 40))
  }
  if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return fallback
  const width = Math.min(bounds.width, area.width - 24)
  const height = Math.min(bounds.height, area.height - 24)
  const x = bounds.x === undefined ? undefined : Math.max(area.x, Math.min(bounds.x, area.x + area.width - width))
  const y = bounds.y === undefined ? undefined : Math.max(area.y, Math.min(bounds.y, area.y + area.height - height))
  return { ...bounds, x, y, width, height }
}

function saveWindowBounds(): void {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const maximized = mainWindow.isMaximized()
  const bounds = maximized
    ? (settings.windowBounds || mainWindow.getNormalBounds())
    : mainWindow.getNormalBounds()
  writeSettings({ windowBounds: { ...bounds, maximized } })
}

function scheduleSaveBounds(): void {
  if (saveBoundsTimer) clearTimeout(saveBoundsTimer)
  saveBoundsTimer = setTimeout(saveWindowBounds, 350)
}

function applyTitleBarTheme(theme: Theme): void {
  if (!mainWindow || mainWindow.isDestroyed()) return
  try {
    mainWindow.setTitleBarOverlay({
      color: theme === 'dark' ? '#0e1a1e' : '#f8f3e9',
      symbolColor: theme === 'dark' ? '#e9f0e9' : '#1b2b2e',
      height: 64
    })
  } catch {
    /* Linux/macOS or older Windows: native frame still works */
  }
}

function createWindow(): void {
  const bounds = validBounds(settings.windowBounds)
  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 980,
    minHeight: 600,
    show: false,
    backgroundColor: settings.theme === 'dark' ? '#0a1316' : '#f2ebdf',
    title: '赛训台',
    icon: iconImage(),
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: settings.theme === 'dark' ? '#0e1a1e' : '#f8f3e9',
      symbolColor: settings.theme === 'dark' ? '#e9f0e9' : '#1b2b2e',
      height: 64
    },
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  if (bounds.maximized) mainWindow.maximize()
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
    applyTitleBarTheme(settings.theme)
  })
  mainWindow.on('resize', scheduleSaveBounds)
  mainWindow.on('move', scheduleSaveBounds)
  mainWindow.on('maximize', scheduleSaveBounds)
  mainWindow.on('unmaximize', scheduleSaveBounds)
  mainWindow.on('close', (event) => {
    saveWindowBounds()
    if (settings.minimizeToTray && !isQuitting) {
      event.preventDefault()
      mainWindow?.hide()
    }
  })
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const current = mainWindow?.webContents.getURL() || ''
    if (url !== current && /^https?:\/\//i.test(url)) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })
  mainWindow.webContents.on('did-fail-load', (_event, code, description) => {
    log(`did-fail-load ${code} ${description}`)
  })

  if (isDev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

function showWindow(): void {
  if (!mainWindow) {
    createWindow()
    return
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function createTray(): void {
  const image = iconImage()
  if (image.isEmpty()) return
  tray = new Tray(image.resize({ width: 20, height: 20 }))
  tray.setToolTip('赛训台')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示赛训台', click: showWindow },
    { label: '打开工作台', click: () => shell.openExternal(settings.baseUrl) },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true
        app.quit()
      }
    }
  ]))
  tray.on('click', showWindow)
}

async function ping(baseUrl: string, timeout = 2500): Promise<{ ok: boolean; version?: string; detail?: string }> {
  try {
    const url = new URL('/api/health', normalizedBase(baseUrl))
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeout)
    const response = await fetch(url, { signal: controller.signal, cache: 'no-store' })
    clearTimeout(timer)
    if (!response.ok) return { ok: false, detail: `HTTP ${response.status}` }
    const data = await response.json()
    return { ok: true, version: data?.version }
  } catch (error) {
    return { ok: false, detail: String(error) }
  }
}

function normalizedBase(baseUrl: string): string {
  const url = new URL(baseUrl)
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('工作台地址必须以 http:// 或 https:// 开头')
  url.hash = ''
  url.search = ''
  return url.toString().replace(/\/+$/, '')
}

function candidateWorkbenchPaths(): string[] {
  const local = process.env.LOCALAPPDATA || ''
  const candidates = [
    settings.workbenchPath,
    local ? join(local, 'KPL赛训工具', 'KPLScrimLab.exe') : '',
    local ? join(local, 'Programs', 'KPL赛训工具', 'KPLScrimLab.exe') : '',
    join(app.getPath('home'), 'KPL赛训工具', 'KPLScrimLab.exe')
  ]
  return [...new Set(candidates.filter((item) => item && existsSync(item)))]
}

async function startWorkbench(baseUrl: string, customPath?: string): Promise<{ ok: boolean; error?: string; path?: string }> {
  const alive = await ping(baseUrl)
  if (alive.ok) return { ok: true }
  const candidates = customPath && existsSync(customPath) ? [customPath] : candidateWorkbenchPaths()
  const target = candidates[0]
  if (!target) {
    return { ok: false, error: '没有找到本机工作台。请先安装工作台，或手动启动它后再连接。' }
  }
  log(`starting workbench: ${target}`)
  const lower = target.toLowerCase()
  const env: NodeJS.ProcessEnv = { ...process.env, KPL_LAUNCHER_NO_BROWSER: '1' }
  try {
    const parsed = new URL(normalizedBase(baseUrl))
    if (parsed.port) env.TRAINING_PORT = parsed.port
  } catch {
    /* keep the workbench default port */
  }
  let child
  if (lower.endsWith('.bat') || lower.endsWith('.cmd')) {
    child = spawn('cmd.exe', ['/c', target], { cwd: dirname(target), env, detached: true, stdio: 'ignore', windowsHide: true })
  } else if (lower.endsWith('.py')) {
    child = spawn(process.env.KPL_PYTHON || 'python', [target, '--autostart'], { cwd: dirname(target), env, detached: true, stdio: 'ignore', windowsHide: true })
  } else {
    child = spawn(target, ['--autostart'], { cwd: dirname(target), env, detached: true, stdio: 'ignore', windowsHide: false })
  }
  child.unref()
  for (let i = 0; i < 60; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    if ((await ping(baseUrl)).ok) return { ok: true, path: target }
  }
  return { ok: false, error: '工作台已经启动，但健康检查没有通过。请打开工作台日志查看原因。', path: target }
}

function registerIpc(): void {
  ipcMain.handle('settings:get', () => settings)
  ipcMain.handle('settings:set', (_event, patch: Partial<Settings>) => {
    const next = writeSettings(patch)
    if (patch.theme) applyTitleBarTheme(next.theme)
    return next
  })
  ipcMain.handle('api:request', async (_event, payload: {
    baseUrl: string
    path: string
    method?: string
    body?: unknown
    timeout?: number
  }) => {
    try {
      const base = normalizedBase(payload.baseUrl)
      if (!payload.path.startsWith('/api/')) return { ok: false, status: 0, error: '只允许访问工作台 API' }
      const url = new URL(payload.path, base)
      if (url.origin !== new URL(base).origin) return { ok: false, status: 0, error: '地址越界' }
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), payload.timeout || 20000)
      const response = await fetch(url, {
        method: payload.method || 'GET',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: payload.body === undefined ? undefined : JSON.stringify(payload.body),
        signal: controller.signal,
        cache: 'no-store'
      })
      clearTimeout(timer)
      const text = await response.text()
      let data: unknown = null
      try { data = text ? JSON.parse(text) : null } catch { data = text }
      if (!response.ok) {
        const detail = data && typeof data === 'object' && 'detail' in data ? (data as any).detail : text
        return { ok: false, status: response.status, error: String(detail || `HTTP ${response.status}`) }
      }
      return { ok: true, status: response.status, data }
    } catch (error) {
      return { ok: false, status: 0, error: String(error instanceof Error ? error.message : error) }
    }
  })
  ipcMain.handle('workbench:detect', async (_event, baseUrl?: string) => {
    const target = baseUrl || settings.baseUrl
    const alive = await ping(target)
    return { running: alive.ok, version: alive.version, paths: candidateWorkbenchPaths() }
  })
  ipcMain.handle('workbench:start', (_event, payload: { baseUrl: string; path?: string }) => startWorkbench(payload.baseUrl, payload.path))
  ipcMain.handle('workbench:open-page', async (_event, payload: { baseUrl?: string; route?: string }) => {
    try {
      const base = normalizedBase(payload?.baseUrl || settings.baseUrl)
      if (new URL(base).origin !== new URL(normalizedBase(settings.baseUrl)).origin) {
        return { ok: false, error: '只允许打开当前工作台的页面' }
      }
      const route = String(payload?.route || '')
      if (!/^#[A-Za-z0-9_./?=&%\-]+$/.test(route)) {
        return { ok: false, error: '页面地址不合法' }
      }
      const pageWindow = new BrowserWindow({
        width: 1360,
        height: 900,
        minWidth: 980,
        minHeight: 640,
        title: '赛训台 · 工作台',
        autoHideMenuBar: true,
        backgroundColor: settings.theme === 'dark' ? '#0a1316' : '#f2ebdf',
        webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
      })
      pageWindow.webContents.setWindowOpenHandler(({ url }) => {
        if (/^https?:\/\//i.test(url)) void shell.openExternal(url)
        return { action: 'deny' }
      })
      await pageWindow.loadURL(`${new URL(base).origin}/${route}`)
      return { ok: true }
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) }
    }
  })
  ipcMain.handle('shell:openExternal', async (_event, url: string) => {
    if (/^https?:\/\//i.test(url)) await shell.openExternal(url)
  })
  ipcMain.handle('shell:openPath', async (_event, target: string) => {
    if (!target) return { ok: false, error: '空路径' }
    const result = await shell.openPath(target)
    return result ? { ok: false, error: result } : { ok: true }
  })
  ipcMain.handle('window:titlebar-theme', (_event, theme: Theme) => {
    applyTitleBarTheme(theme === 'dark' ? 'dark' : 'light')
  })
  ipcMain.handle('app:openLogs', async () => {
    const dir = join(app.getPath('userData'), 'logs')
    mkdirSync(dir, { recursive: true })
    await shell.openPath(dir)
  })
  ipcMain.handle('app:notify', (_event, payload: { title?: string; body?: string }) => {
    try {
      if (Notification.isSupported()) {
        new Notification({
          title: payload?.title || '赛训台',
          body: payload?.body || '',
          icon: iconImage(),
          silent: false
        }).show()
      }
    } catch (error) {
      log(`notification failed: ${String(error)}`)
    }
  })
  ipcMain.handle('app:info', () => ({
    version: app.getVersion(),
    electron: process.versions.electron,
    platform: process.platform,
    packaged: app.isPackaged,
    userData: app.getPath('userData'),
    settingsPath: userDataFile('settings.json')
  }))
  ipcMain.on('log:write', (_event, message: string) => log(`renderer: ${message}`))
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', (_event, argv) => {
    if (argv.some((arg) => arg.startsWith(`${PROTOCOL}://`))) showWindow()
    else showWindow()
  })
  app.on('open-url', (event, url) => {
    event.preventDefault()
    if (url.startsWith(`${PROTOCOL}://`)) showWindow()
  })
  app.whenReady().then(() => {
    log(`app ready ${app.getVersion()} packaged=${app.isPackaged}`)
    registerIpc()
    Menu.setApplicationMenu(null)
    createWindow()
    createTray()
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
      else showWindow()
    })
  })
}

app.on('before-quit', () => { isQuitting = true })
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
