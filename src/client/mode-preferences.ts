import { createContext } from 'react'

export type DisplayMode = 'auto' | 'classic' | 'better-sidebar'
export const DISPLAY_MODE_KEY = 'dsh-kline:display-mode:v1'
export const AUTO_OPEN_KEY = 'dsh-kline:auto-open-after-analysis:v1'
export const UI_SEEN_KEY = 'dsh-kline:ui-change-seen:v0.2.0'
export interface InterfaceState { preference: DisplayMode; mode: Exclude<DisplayMode, 'auto'>; available: boolean }
export const InterfaceContext = createContext<InterfaceState>({ preference: 'auto', mode: 'classic', available: false })
export function readDisplayMode(storage = globalThis.localStorage): DisplayMode {
  try {
    const value = storage.getItem(DISPLAY_MODE_KEY)
    return value === 'classic' || value === 'better-sidebar' ? value : 'auto'
  } catch { return 'auto' }
}
export function resolveDisplayMode(preference: DisplayMode, available: boolean): InterfaceState['mode'] {
  return preference !== 'classic' && available ? 'better-sidebar' : 'classic'
}
export function readAutoOpen(storage = globalThis.localStorage): boolean {
  try { return storage.getItem(AUTO_OPEN_KEY) !== 'false' } catch { return true }
}
