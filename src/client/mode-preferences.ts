import { createContext } from 'react'
import type { KlineHostOptions } from './host-options.ts'

export type DisplayMode = 'auto' | 'classic' | 'better-sidebar'
export const DISPLAY_MODE_KEY = 'dsh-kline:display-mode:v1'
export const AUTO_OPEN_KEY = 'dsh-kline:auto-open-after-analysis:v1'
export const UI_SEEN_KEY = 'dsh-kline:ui-change-seen:v0.2.0'
export interface InterfaceState { preference: DisplayMode; mode: Exclude<DisplayMode, 'auto'>; available: boolean }
export const InterfaceContext = createContext<InterfaceState>({ preference: 'classic', mode: 'classic', available: false })
export function readDisplayMode(storage = globalThis.localStorage): DisplayMode {
  try {
    const value = storage.getItem(DISPLAY_MODE_KEY)
    return value === 'better-sidebar' ? value : 'classic'
  } catch { return 'classic' }
}
export function resolveDisplayMode(
  preference: DisplayMode,
  available: boolean,
  host?: KlineHostOptions,
): InterfaceState['mode'] {
  // A host that owns the chart entry uses its column whenever it offers one,
  // whatever the user's stored preference says: there is no floating launcher
  // left to fall back to. Omitted host options keep the upstream rule below.
  if (host?.entry === 'tab') return available ? 'better-sidebar' : 'classic'
  // A chart should be available before a new DSH conversation has created a
  // workbench session. The native tab is therefore opt-in; the classic K
  // launcher remains the dependable default.
  return preference === 'better-sidebar' && available ? 'better-sidebar' : 'classic'
}

/**
 * Whether the floating classic launcher is drawn for this frame.
 *
 * Upstream keeps it for classic mode and for screens without a Session, where
 * the tab body cannot live yet. A host that declared `entry: 'tab'` owns the
 * chart entry instead, so it never draws the launcher.
 * @param host - the host options, if the host provided any.
 * @param mode - the interface mode this frame resolved to.
 * @param hasConversation - whether a Session exists to host a tab body.
 */
export function shouldDrawClassicLauncher(
  host: KlineHostOptions | undefined,
  mode: InterfaceState['mode'],
  hasConversation: boolean,
): boolean {
  if (host?.entry === 'tab') return false
  return mode === 'classic' || !hasConversation
}
export function readAutoOpen(storage = globalThis.localStorage): boolean {
  try { return storage.getItem(AUTO_OPEN_KEY) !== 'false' } catch { return true }
}
