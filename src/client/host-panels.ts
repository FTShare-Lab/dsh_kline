/**
 * The optional host contract for panel mounts.
 *
 * A host that already owns a bounded panel declares a slot of its own and asks
 * the chart to fill it through the `klinePanels` service. The chart therefore
 * never learns a host's slot names, and a host that does not ask sees the
 * plugin exactly as it was before this contract existed.
 *
 * Kept free of React, like `native-sidebar-register.ts`, so the registration
 * policy is testable with fake slot services.
 */

import type { KlineChrome } from './embed.ts'
import type { SlotsService } from './native-sidebar-services.ts'

/** Props a host slot passes to the chart panel it mounts. */
export interface KlinePanelProps {
  /** The instrument the host currently has selected. */
  symbol?: string
  /** Display name of that instrument, when the host has one. */
  name?: string
  /** The chart's own selection, published back so the host can update its ticket. */
  onIdentity?: (symbol?: string, name?: string) => void
}

/** The optional service a host calls to fill its own panel seat with the chart. */
export interface KlinePanelsService {
  /**
   * Fill `seat` with the chart panel.
   * @param seat - a slot name the host itself declares and renders.
   * @param options.chrome - chrome the panel keeps (default `chart-search`).
   * Repeated mounts with the same chrome share one panel until all callers
   * release it. Conflicting chrome is rejected while the seat is in use.
   * @returns an idempotent disposer for this caller's mount.
   */
  mount(seat: string, options?: { chrome?: KlineChrome }): () => void
}

/** The host slice a mount needs: only the slot registry. */
export interface PanelMountHost {
  readonly slots: SlotsService
}

/** Build the body for one seat; the component side supplies the React element. */
export type PanelBodyFactory = (seat: string, chrome: KlineChrome | undefined) => unknown

/** Pending requests survive slot-service replacement; callers own separate leases. */
export interface PanelMountRegistry extends KlinePanelsService {
  connect(service: KlinePanelsService): () => void
}

/** Coordinate caller lifetimes independently of the current slot-service lifetime. */
export function createPanelMountRegistry(): PanelMountRegistry {
  const requests = new Map<string, { chrome: KlineChrome; users: number }>()
  type Connection = { service: KlinePanelsService; mounted: Map<string, () => void> }
  let current: Connection | undefined

  const disconnect = (connection: Connection) => {
    if (current === connection) current = undefined
    const disposers = [...connection.mounted.values()]
    connection.mounted.clear()
    const errors: unknown[] = []
    for (const dispose of disposers) {
      try { dispose() } catch (error) { errors.push(error) }
    }
    if (errors.length) throw new AggregateError(errors, 'Could not release host chart panels')
  }

  return {
    mount(seat, options) {
      const chrome = options?.chrome ?? 'chart-search'
      let request = requests.get(seat)
      if (request && request.chrome !== chrome) throw new Error(`Chart panel "${seat}" is already mounted with different chrome`)
      if (!request) {
        request = { chrome, users: 0 }
        requests.set(seat, request)
        try {
          if (current) current.mounted.set(seat, current.service.mount(seat, { chrome }))
        } catch (error) {
          requests.delete(seat)
          throw error
        }
      }
      const lease = request
      lease.users += 1
      let released = false
      return () => {
        if (released) return
        released = true
        if (--lease.users > 0 || requests.get(seat) !== lease) return
        requests.delete(seat)
        const dispose = current?.mounted.get(seat)
        current?.mounted.delete(seat)
        dispose?.()
      }
    },
    connect(service) {
      if (current) disconnect(current)
      const connection: Connection = { service, mounted: new Map() }
      current = connection
      try {
        for (const [seat, request] of requests) {
          connection.mounted.set(seat, service.mount(seat, { chrome: request.chrome }))
        }
      } catch (error) {
        try { disconnect(connection) } catch (cleanupError) {
          throw new AggregateError([error, cleanupError], 'Could not attach host chart panels')
        }
        throw error
      }
      return () => disconnect(connection)
    },
  }
}

/**
 * Turn slot services plus a body factory into the `klinePanels` service.
 * @param host - the host services a mount registers into.
 * @param body - the component body for one seat (one per mounted seat).
 * @returns the service a host calls; nothing is registered until it calls.
 */
export function createPanelMounts(host: PanelMountHost, body: PanelBodyFactory): KlinePanelsService {
  return {
    mount(seat, options) {
      // `slots.inject` returns the factory's disposer when the seat is already
      // declared, and the injection's own disposer otherwise — the same shape
      // the native tab registration relies on.
      const dispose = host.slots.inject(seat, () =>
        host.slots.register({ name: seat }, body(seat, options?.chrome))) as unknown as (() => void) | undefined
      let released = false
      return () => {
        if (released) return
        released = true
        dispose?.()
      }
    },
  }
}
