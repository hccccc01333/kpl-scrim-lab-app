import type { KplBridge, Settings } from '../../../preload'

declare global {
  interface Window {
    kpl: KplBridge
  }
}

export type { Settings }
