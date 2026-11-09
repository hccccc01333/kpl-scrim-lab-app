import type { ApiResponse } from '../../../preload'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function normalizeBase(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) throw new Error('请填写工作台地址')
  const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`
  const url = new URL(withProtocol)
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('地址必须以 http:// 或 https:// 开头')
  url.hash = ''
  url.search = ''
  return url.toString().replace(/\/+$/, '')
}

export async function api<T = unknown>(
  baseUrl: string,
  path: string,
  options: { method?: string; body?: unknown; timeout?: number } = {}
): Promise<T> {
  const response: ApiResponse<T> = await window.kpl.request<T>({
    baseUrl,
    path,
    method: options.method ?? 'GET',
    body: options.body,
    timeout: options.timeout
  })
  if (!response.ok) throw new ApiError(response.status || 0, response.error || '工作台没有返回数据')
  return response.data as T
}

export function assetUrl(baseUrl: string, path?: string | null): string {
  if (!path) return ''
  try {
    return new URL(path, baseUrl).toString()
  } catch {
    return ''
  }
}

export function isLoopback(baseUrl: string): boolean {
  try {
    const url = new URL(baseUrl)
    return ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(url.hostname)
  } catch {
    return false
  }
}

export function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
