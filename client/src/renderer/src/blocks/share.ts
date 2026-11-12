/**
 * 上帝模式 · 布局分享编码
 *
 * 布局包只含「模式 / 块顺序 / 显隐 / 页面」，不含任何比赛、选手或战队数据。
 * 分享 = AES-GCM 加密后的布局包（分享码）+ 独立密钥。
 * 服务端（如果以后托管）只存密文；密钥不经过服务器。
 */

export const SHARE_SCHEMA = 'kpl-layout-share-v1'

export interface SharePayload {
  schema: string
  app: string
  exportedAt: string
  mode?: string
  pages: Record<string, unknown>
}

export interface ShareContent {
  mode?: string
  pages: Record<string, unknown>
}

export interface ShareInput {
  mode?: string
  pages: Record<string, unknown>
}

const KEY_PREFIX = 'KPL1-'
const CODE_PREFIX = 'KPLG1.'

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function base64UrlToBytes(text: string): Uint8Array {
  const normalized = text.trim().replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function randomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return bytes
}

function requireCrypto(): SubtleCrypto {
  if (!crypto?.subtle) throw new Error('当前环境不支持加密分享，请更新客户端后重试。')
  return crypto.subtle
}

export function formatShareKey(raw: Uint8Array): string {
  const body = bytesToBase64Url(raw).toUpperCase()
  const groups = body.match(/.{1,5}/g) || [body]
  return KEY_PREFIX + groups.join('-')
}

export function parseShareKey(text: string): Uint8Array {
  const body = text.trim()
  if (!body) throw new Error('请填写分享密钥。')
  const normalized = body.replace(/^KPL1-?/i, '').replace(/[^A-Za-z0-9_-]/g, '')
  let bytes: Uint8Array
  try {
    bytes = base64UrlToBytes(normalized)
  } catch {
    throw new Error('分享密钥格式不对，检查是否完整复制。')
  }
  if (bytes.length !== 16) throw new Error('分享密钥长度不对，检查是否漏抄了几位。')
  return bytes
}

async function aesKey(raw: Uint8Array): Promise<CryptoKey> {
  return requireCrypto().importKey('raw', raw as BufferSource, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt'])
}

/** 布局 → { code, key }：code 给分享码，key 单独发。 */
export async function encryptLayout(input: ShareInput): Promise<{ code: string; key: string }> {
  const payload: SharePayload = {
    schema: SHARE_SCHEMA,
    app: 'kpl-scrim-desk',
    exportedAt: new Date().toISOString(),
    mode: input.mode,
    pages: input.pages
  }
  const plaintext = new TextEncoder().encode(JSON.stringify(payload))
  const keyBytes = randomBytes(16)
  const iv = randomBytes(12)
  const cipher = await requireCrypto().encrypt(
    { name: 'AES-GCM', iv: iv as BufferSource },
    await aesKey(keyBytes),
    plaintext as BufferSource
  )
  const combined = new Uint8Array(iv.length + cipher.byteLength)
  combined.set(iv, 0)
  combined.set(new Uint8Array(cipher), iv.length)
  return { code: CODE_PREFIX + bytesToBase64Url(combined), key: formatShareKey(keyBytes) }
}

/** { code, key } → 布局内容。解密失败给中文提示，不抛库内部错误。 */
export async function decryptLayout(code: string, key: string): Promise<ShareContent> {
  const trimmed = code.trim()
  if (!trimmed) throw new Error('请粘贴分享码。')
  if (!trimmed.toUpperCase().startsWith(CODE_PREFIX)) throw new Error('分享码开头不对，应以 KPLG1 开头。')
  const body = trimmed.slice(CODE_PREFIX.length).replace(/\s+/g, '')
  let combined: Uint8Array
  try {
    combined = base64UrlToBytes(body)
  } catch {
    throw new Error('分享码格式不对，检查是否完整复制。')
  }
  if (combined.length <= 12) throw new Error('分享码不完整，重新复制一次。')
  const iv = combined.subarray(0, 12)
  const cipher = combined.subarray(12)
  let plaintext: ArrayBuffer
  try {
    plaintext = await requireCrypto().decrypt(
      { name: 'AES-GCM', iv: iv as BufferSource },
      await aesKey(parseShareKey(key)),
      cipher as BufferSource
    )
  } catch {
    throw new Error('分享码和密钥对不上，确认两样都复制对了。')
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(new TextDecoder().decode(plaintext))
  } catch {
    throw new Error('分享内容损坏，重新生成一次分享码。')
  }
  const payload = parsed as Partial<SharePayload>
  if (!payload || payload.schema !== SHARE_SCHEMA || !payload.pages || typeof payload.pages !== 'object') {
    throw new Error('这不是赛训台的布局分享码。')
  }
  return {
    mode: typeof payload.mode === 'string' ? payload.mode : undefined,
    pages: payload.pages as Record<string, unknown>
  }
}

/** 复制到剪贴板；Electron 下 navigator.clipboard 可用，失败时回退旧 API。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const area = document.createElement('textarea')
      area.value = text
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(area)
      return ok
    } catch {
      return false
    }
  }
}
