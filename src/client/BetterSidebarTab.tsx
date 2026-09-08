import { useCallback, useContext, useEffect, useSyncExternalStore } from 'react'
import type { BetterSidebarService, TabComponentProps } from 'dsh-better-sidebar'
import type { Sessions } from './conversation'
import { useChartReference } from './chart-session-resolver'
import { NativeKlineApp, StandaloneKlineApp, standaloneWorkspaceScope } from './KlineContent'
import { InterfaceContext, readAutoOpen } from './mode-preferences'
import { KLINE_TAB_ID } from './sidebar-integration'
function KlineTabContent({ sessions, conversationId }: { sessions: Sessions; conversationId: string }) {
  const reference = useChartReference(sessions, conversationId)
  const onIdentity = useCallback(() => {}, [])
  return reference
    ? <NativeKlineApp key={reference.session} session={{ ok: true, ...reference, published_at: reference.order }} conversationId={conversationId} onIdentity={onIdentity} />
    : <StandaloneKlineApp conversationId={standaloneWorkspaceScope(conversationId)} onIdentity={onIdentity} />
}
function AutoOpen({ service, sessions, conversationId }: { service: BetterSidebarService; sessions: Sessions; conversationId: string }) {
  const onNewChart = useCallback(() => {
    if (readAutoOpen()) service.openTab({ type: KLINE_TAB_ID }, { sessionId: conversationId })
  }, [service, conversationId])
  useChartReference(sessions, conversationId, onNewChart)
  return null
}
export function BetterSidebarBridge({ service, sessions }: { service: BetterSidebarService; sessions: Sessions }) {
  const interfaceState = useContext(InterfaceContext)
  const list = useSyncExternalStore(listener => sessions.list.subscribe(listener), () => sessions.list.getSnapshot())
  useEffect(() => service.registerTab({
    id: KLINE_TAB_ID,
    title: 'K线分析 / K-line',
    icon: <span aria-hidden="true">K</span>,
    order: 120,
    single: true,
    component: ({ scope, visible }: TabComponentProps) => (
      <InterfaceContext.Provider value={interfaceState}>
        <div data-dsh-kline-tab="" style={{ width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }}>
          {visible && scope.sessionId && <KlineTabContent key={scope.sessionId} conversationId={scope.sessionId} sessions={sessions} />}
        </div>
      </InterfaceContext.Provider>
    ),
  }), [service, sessions, interfaceState])
  return list.current ? <AutoOpen key={list.current} service={service} sessions={sessions} conversationId={list.current} /> : null
}
