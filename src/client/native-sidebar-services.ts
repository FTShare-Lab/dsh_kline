import type { Sessions } from './conversation'
import type { NativeSidebarTabDefinition } from './native-sidebar-contract'

/**
 * The slices of the host services this plugin reaches for.
 *
 * Each slice names only the members used here, so a host that ships a
 * compatible implementation works without this package depending on the
 * host's client packages. The shapes follow DSH 0.2.1's public faces:
 * `@deepseek-ai/dsh-client-ui-sidebar-right/client` (tab registry and
 * navigation), and `@deepseek-ai/dsh-client-ui-slots` (the keyed seat).
 */

/** The right-Sidebar tab registry: stage one of a tab type's registration. */
export interface SidebarRightTabsService {
  register(definition: NativeSidebarTabDefinition): () => void
}

/** The right-Sidebar navigation face: how a page type is opened. */
export interface SidebarRightService {
  openTab(kind: string, options?: { params?: unknown }): void
}

/** The host `slots` service, limited to the keyed body seat. */
export interface SlotsService {
  inject(name: string, factory: () => unknown): unknown
  register(options: SlotsRegistration, component: unknown): () => void
}

/** One keyed seat registration: the body that draws the tabs of `key`'s type. */
export interface SlotsRegistration {
  name: string
  key?: string
  /** Business props for the body; the framework adds the standard share. */
  inject?: (sessionId: string) => Record<string, unknown>
}

/** The metadata hook the host seat binds into every tab body. */
export interface NativeTabInfo {
  tab: { readonly visible: boolean }
}

/** What the body seat hands a registered body: its session and the props it needs. */
export interface NativeTabBodyProps {
  readonly sessionId: string
  readonly sessions: Sessions
  readonly useTabInfo: () => NativeTabInfo
}
