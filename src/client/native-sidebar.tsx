import { useCallback, useMemo, useSyncExternalStore } from 'react'
import { useChartReference } from './chart-session-resolver'
import { KlineTabContent } from './BetterSidebarTab'
import type { ClientContext } from './client-context'
import type { Sessions } from './conversation'
import { InterfaceContext, readAutoOpen, readDisplayMode } from './mode-preferences'
import { registerNativeTab, type NativeTabRegistration } from './native-sidebar-register'
import type { NativeTabBodyProps, SidebarRightService, SidebarRightTabsService, SlotsService } from './native-sidebar-services'

/**
 * The chart as a tab of the host's own right column.
 *
 * The registration policy lives in `native-sidebar-register.ts`; this module
 * owns the two things that need React or the client context: the tab body and
 * the auto-open trigger. The body is the same chart the Better Sidebar tab
 * draws, mounted against the tab's own conversation.
 */

/**
 * One tab body: the chart of the tab's session.
 *
 * The interface state is the native-tab one: the chart view uses it only to
 * know which shell it lives in, so the tab reports `better-sidebar` (the
 * existing "native tab" value) and stays independent of the user's preference.
 * `visible` is passed through rather than unmounting the chart, because the
 * host keeps the body alive across a collapsed column or a tab switch and the
 * view's own state (instrument reference, zoom) only survives that way.
 */
export function NativeKlineTabBody({ sessionId, sessions, useTabInfo }: NativeTabBodyProps) {
  const visible = useTabInfo().tab.visible
  const preference = useMemo(readDisplayMode, [])
  return (
    <InterfaceContext.Provider value={{ preference, mode: 'better-sidebar', available: true }}>
      <div data-dsh-kline-tab="" style={{ width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }}>
        <KlineTabContent key={sessionId} sessions={sessions} conversationId={sessionId} visible={visible} />
      </div>
    </InterfaceContext.Provider>
  )
}

/** Reveal the chart tab when an analysis result lands in the conversation on screen. */
function NativeAutoOpen({ sessions, conversationId, bridge }: { sessions: Sessions; conversationId: string; bridge: NativeSidebarBridge }) {
  const onNewChart = useCallback(() => {
    if (readAutoOpen()) bridge.open()
  }, [bridge])
  useChartReference(sessions, conversationId, onNewChart)
  return null
}

/**
 * Auto-open lives in the tab's own session, exactly like the Better Sidebar
 * path; the router decides whether this path is the active interface.
 */
export function NativeSidebarBridgeView({ bridge, sessions }: { bridge: NativeSidebarBridge; sessions: Sessions }) {
  const subscribe = useCallback((listener: () => void) => sessions.list.subscribe(listener), [sessions])
  const list = useSyncExternalStore(subscribe, () => sessions.list.getSnapshot())
  return list.current
    ? <NativeAutoOpen key={list.current} bridge={bridge} sessions={sessions} conversationId={list.current} />
    : null
}

/** The host-facing handle the router polls to decide which interface to draw. */
export interface NativeSidebarBridge {
  /** Both stages registered: the host can draw the chart tab. */
  available(): boolean
  /** Open (or reveal) the chart tab of the session on screen. */
  open(): void
}

/**
 * Register the chart tab into the host's native right Sidebar.
 *
 * Every host service is optional: a host without `sidebarRightTabs`,
 * `sidebarRight` or `slots` keeps `available() === false` and the plugin's
 * existing interfaces untouched.
 * @param ctx - the client context to register on.
 * @param onChange - called whenever availability changes, so the router repaints.
 * @returns the handle the router and the auto-open path share.
 */
export function registerNativeSidebar(ctx: ClientContext, onChange: () => void): NativeSidebarBridge {
  let registration: NativeTabRegistration | undefined
  const bridge: NativeSidebarBridge = {
    available: () => registration?.available() ?? false,
    open: () => registration?.open(),
  }
  ctx.inject(['sidebarRightTabs', 'sidebarRight', 'slots'], scope => {
    scope.effect(() => {
      const tabs = scope.get('sidebarRightTabs') as SidebarRightTabsService | undefined
      const navigation = scope.get('sidebarRight') as SidebarRightService | undefined
      const slots = scope.get('slots') as SlotsService | undefined
      if (tabs === undefined || navigation === undefined || slots === undefined) return () => {}
      const next = registerNativeTab({ tabs, navigation, slots }, {
        body: NativeKlineTabBody,
        bodyProps: (sessionId: string) => ({ sessions: ctx.sessions, sessionId }),
        onChange,
      })
      registration = next
      onChange()
      return () => {
        registration = undefined
        next.dispose()
        onChange()
      }
    }, 'dsh-kline: native right sidebar tab')
  })
  return bridge
}
