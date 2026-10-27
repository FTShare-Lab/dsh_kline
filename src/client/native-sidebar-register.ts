import { NATIVE_TAB_ID, nativeTabDefinition } from './native-sidebar-contract.ts'
import type { SidebarRightService, SidebarRightTabsService, SlotsService } from './native-sidebar-services'
import { KLINE_TAB_ID } from './sidebar-integration.ts'

/**
 * The native right-Sidebar registration, without React and without a host
 * context: a pure function over the three host services, so the bootstrap
 * policy (both stages, their teardown order, the deferred body seat) is
 * testable with fakes.
 *
 * A DSH host that owns its right column publishes `sidebarRightTabs` (stage
 * one — what the tab type is) and a keyed `sidebar.right.pane.tab` seat
 * (stage two — the body), navigated by `sidebarRight`. A type without a body
 * makes the host draw "nothing can view this", so the two stages are one unit
 * and any failure backs the type out again.
 */

/** The seat a tab type's body registers under. */
export const BODY_SEAT = 'sidebar.right.pane.tab'

/** The host services registration needs, all of them already resolved. */
export interface NativeTabHost {
  readonly tabs: SidebarRightTabsService
  readonly navigation: SidebarRightService
  readonly slots: SlotsService
}

/** What to register, and how the caller wants to hear about it. */
export interface NativeTabOptions {
  /** The body component registered into the keyed seat. */
  readonly body: unknown
  /** Business props the body receives; the framework adds its own standard share. */
  readonly bodyProps?: (sessionId: string) => Record<string, unknown>
  /** Called whenever `available()` changes. */
  readonly onChange?: () => void
}

/** A live native tab: what the router asks, and how the auto-open path opens it. */
export interface NativeTabRegistration {
  /** Both stages are in place: the tab can actually draw. */
  available(): boolean
  /** Open (or reveal) the chart tab of the session on screen. */
  open(): void
  /** Back both stages out. Idempotent, and every teardown is failure-isolated. */
  dispose(): void
}

/**
 * Register the chart as a tab type of the host's right column.
 * @param host - the resolved host services.
 * @param options - the body, its props, and the availability callback.
 * @returns the registration, live until `dispose()`.
 */
export function registerNativeTab(host: NativeTabHost, options: NativeTabOptions): NativeTabRegistration {
  const onChange = options.onChange ?? (() => {})
  let typeDispose: (() => void) | undefined
  let seatDispose: (() => void) | undefined
  let bodyDispose: (() => void) | undefined
  let available = false
  let disposed = false

  /** One teardown step: a failing disposer must not block the rest of the rollback. */
  const runSafely = (dispose: (() => void) | undefined, what: string) => {
    if (dispose === undefined) return
    try { dispose() } catch (error) { console.error(`[dsh-kline] native tab ${what} teardown failed:`, error) }
  }
  const settle = (next: boolean) => {
    if (available === next) return
    available = next
    try { onChange() } catch (error) { console.error('[dsh-kline] native tab change handler failed:', error) }
  }
  const closeBody = () => {
    const dispose = bodyDispose
    bodyDispose = undefined
    if (dispose !== undefined) runSafely(dispose, 'body')
  }
  const release = () => {
    if (disposed) return
    disposed = true
    // The body goes first, so the type never outlives the thing that draws it.
    closeBody()
    runSafely(seatDispose, 'body seat')
    seatDispose = undefined
    runSafely(typeDispose, 'type')
    typeDispose = undefined
    settle(false)
  }
  const failed = (): NativeTabRegistration => ({ available: () => false, open: () => {}, dispose: () => {} })

  try {
    typeDispose = host.tabs.register(nativeTabDefinition())
  } catch (error) {
    console.error('[dsh-kline] native right sidebar tab type registration failed:', error)
    return failed()
  }

  // Stage two may settle after this call: a host declares the seat when its
  // sidebar mounts, which can be later than the plugin boot. A failure inside
  // the factory therefore has to roll the type back itself, once the
  // injection attempt has settled (calling our own seat disposer from inside
  // its factory would re-enter the registry).
  const mountBody = () => {
    if (disposed) return () => {}
    let dispose: (() => void) | undefined
    try {
      dispose = host.slots.register({
        name: BODY_SEAT,
        key: NATIVE_TAB_ID,
        ...options.bodyProps === undefined ? {} : { inject: options.bodyProps },
      }, options.body)
    } catch (error) {
      console.error('[dsh-kline] native right sidebar tab body registration failed:', error)
      queueMicrotask(release)
      return () => {}
    }
    let closed = false
    bodyDispose = () => {
      if (closed) return
      closed = true
      runSafely(dispose, 'body')
    }
    settle(true)
    return () => { closeBody(); settle(false) }
  }

  try {
    seatDispose = host.slots.inject(BODY_SEAT, mountBody) as unknown as (() => void) | undefined
  } catch (error) {
    console.error('[dsh-kline] native right sidebar body seat failed:', error)
    release()
    return failed()
  }

  return {
    available: () => available && !disposed,
    open: () => {
      if (!available || disposed) return
      try {
        host.navigation.openTab(KLINE_TAB_ID)
      } catch (error) {
        // Opening is a navigation request: a host with no Session on screen
        // refuses it, and the next analysis result or the guide entry retries.
        console.warn('[dsh-kline] could not open the native chart tab:', error)
      }
    },
    dispose: release,
  }
}
