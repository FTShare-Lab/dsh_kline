import { useCallback, useContext, useEffect, useSyncExternalStore } from 'react'
import type { BetterSidebarService, TabComponentProps } from 'dsh-better-sidebar'
import type { Sessions } from './conversation'
import { useChartReference } from './chart-session-resolver'
import { NativeKlineApp, StandaloneKlineApp, standaloneWorkspaceScope } from './KlineContent'
import { InterfaceContext, readAutoOpen } from './mode-preferences'
import { KLINE_TAB_ID, KLINE_TAB_TITLE, migrateKlineTabTitle } from './sidebar-integration'
import { installDefaultKlineTabs } from './default-tab'
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
function KlineTabFrame({service, sessions, scope, tab, visible}: TabComponentProps & {service: BetterSidebarService; sessions: Sessions}) {
  useEffect(() => migrateKlineTabTitle(service, tab, scope.sessionId), [service, tab.id, tab.title, scope.sessionId])
  return (
    <div data-dsh-kline-tab="" style={{width:'100%', height:'100%', minHeight:0, overflow:'hidden'}}>
      {visible && scope.sessionId && <KlineTabContent key={scope.sessionId} conversationId={scope.sessionId} sessions={sessions} />}
    </div>
  )
}
export function BetterSidebarBridge({ service, sessions }: { service: BetterSidebarService; sessions: Sessions }) {
  const interfaceState = useContext(InterfaceContext)
  const list = useSyncExternalStore(listener => sessions.list.subscribe(listener), () => sessions.list.getSnapshot())
  useEffect(() => {
    const dispose = service.registerTab({
      id: KLINE_TAB_ID,
      title: KLINE_TAB_TITLE,
      order: 120,
      single: true,
      component: (props: TabComponentProps) => (
        <InterfaceContext.Provider value={interfaceState}>
          <KlineTabFrame {...props} service={service} sessions={sessions} />
        </InterfaceContext.Provider>
      ),
    })
    const stopDefaults = installDefaultKlineTabs(service)
    return () => { stopDefaults(); dispose() }
  }, [service, sessions, interfaceState])
  return list.current ? <AutoOpen key={list.current} service={service} sessions={sessions} conversationId={list.current} /> : null
}
