import { contextBridge, ipcRenderer } from 'electron'

export interface ApiRequest {
  baseUrl: string
  path: string
  method?: string
  body?: unknown
  timeout?: number
}

export interface ApiResponse<T = unknown> {
  ok: boolean
  status: number
  data?: T
  error?: string
}

export interface Settings {
  baseUrl: string
  theme: 'light' | 'dark'
  density: 'comfortable' | 'compact'
  minimizeToTray: boolean
  workbenchPath: string
  windowBounds?: {
    x?: number
    y?: number
    width: number
    height: number
    maximized?: boolean
  }
}

export interface WorkbenchInfo {
  running: boolean
  version?: string
  paths: string[]
}

const api = {
  getSettings: (): Promise<Settings> => ipcRenderer.invoke('settings:get'),
  setSettings: (patch: Partial<Settings>): Promise<Settings> => ipcRenderer.invoke('settings:set', patch),
  request: <T = unknown>(payload: ApiRequest): Promise<ApiResponse<T>> => ipcRenderer.invoke('api:request', payload),
  detectWorkbench: (baseUrl?: string): Promise<WorkbenchInfo> => ipcRenderer.invoke('workbench:detect', baseUrl),
  startWorkbench: (payload: { baseUrl: string; path?: string }): Promise<{ ok: boolean; error?: string; path?: string }> => ipcRenderer.invoke('workbench:start', payload),
  openWorkbenchPage: (payload: { baseUrl?: string; route: string }): Promise<{ ok: boolean; error?: string }> => ipcRenderer.invoke('workbench:open-page', payload),
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('shell:openExternal', url),
  openPath: (target: string): Promise<{ ok: boolean; error?: string }> => ipcRenderer.invoke('shell:openPath', target),
  setTitleBarTheme: (theme: 'light' | 'dark'): Promise<void> => ipcRenderer.invoke('window:titlebar-theme', theme),
  openLogs: (): Promise<void> => ipcRenderer.invoke('app:openLogs'),
  notify: (payload: { title?: string; body?: string }): Promise<void> => ipcRenderer.invoke('app:notify', payload),
  appInfo: (): Promise<{ version: string; electron: string; platform: string; packaged: boolean; userData: string; settingsPath: string }> => ipcRenderer.invoke('app:info'),
  log: (message: string): void => ipcRenderer.send('log:write', message)
}

export type KplBridge = typeof api

contextBridge.exposeInMainWorld('kpl', api)
