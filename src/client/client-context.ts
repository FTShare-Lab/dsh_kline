import type { Sessions } from './conversation'

/**
 * The client context `apply` receives (only the members this plugin uses).
 *
 * Kept in its own module so host adapters can name the context without
 * importing the plugin entry: this file has no runtime code, so it cannot
 * create an import cycle.
 */
export interface ClientContext {
  effect(callback: () => () => void, label?: string): void
  inject(deps: string[], callback: (ctx: ClientContext) => void): unknown
  get(name: string): unknown
  sessions: Sessions
}
