import type { BetterSidebarService } from 'dsh-better-sidebar'

export const KLINE_TAB_ID = 'ftshare-kline:chart'
export const KLINE_TAB_TITLE = '非凸K线助手 / dsh_kline'

export function migrateKlineTabTitle(service: BetterSidebarService, tab: {id: string; type: string; title?: string}, sessionId?: string): void {
  if (tab.type !== KLINE_TAB_ID || !['K线分析 / K-line', 'K线分析'].includes(tab.title ?? '')
    || !service.features?.includes('updateTab') || !service.features?.includes('stateSubscription')
    || typeof service.updateTab !== 'function' || typeof service.getSnapshot !== 'function') return
  try {
    // updateTab is current-session-only in the public API. Never mutate a
    // foreign floating tab or a user-customized title while migrating labels.
    if (sessionId && service.getSnapshot()?.sessionId === sessionId) service.updateTab(tab.id, {title:KLINE_TAB_TITLE})
  } catch { /* Older/disposed integrations keep their saved title harmlessly. */ }
}
export function isSidebarUsable(service?: BetterSidebarService): boolean {
  return Boolean(service && typeof service.registerTab === 'function' && typeof service.openTab === 'function'
    && service.features?.includes('targetedOpen'))
}

// The framework persists open tabs across reloads. In Classic mode remove only
// our old tab shells, otherwise it displays a misleading "plugin unavailable"
// placeholder. Chart/workspace storage is separate and is never deleted here.
export function cleanClassicTabs(service: BetterSidebarService): () => void {
  if (!service.features?.includes('stateSubscription') || typeof service.closeTab !== 'function'
    || typeof service.getSnapshot !== 'function' || typeof service.subscribeState !== 'function') return () => {}
  let stopped = false, pending = false
  const schedule = () => {
    if (stopped || pending) return
    pending = true
    queueMicrotask(() => {
      pending = false
      if (stopped) return
      try {
        const snapshot = service.getSnapshot()
        const { sessionId, state } = snapshot ?? {}
        if (typeof sessionId !== 'string' || !sessionId || !state) return
        const ids = new Set<string>()
        const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null
        const collect = (tab: unknown) => {
          if (record(tab) && tab.type === KLINE_TAB_ID && typeof tab.id === 'string' && tab.id) ids.add(tab.id)
        }
        // Layouts belong to another plugin and may contain older/incomplete
        // nodes. Iterate defensively, including protection against cycles.
        const pendingNodes: unknown[] = [state.bottomSplits, state.splits]
        const seen = new Set<object>()
        while (pendingNodes.length) {
          const node = pendingNodes.pop()
          if (!record(node) || seen.has(node)) continue
          seen.add(node)
          if (node.kind === 'split' && Array.isArray(node.children)) pendingNodes.push(...[...node.children].reverse())
          else if (Array.isArray(node.tabs)) node.tabs.forEach(collect)
        }
        if (Array.isArray(state.floats)) state.floats.forEach(frame => { if (record(frame)) collect(frame.tab) })
        for (const id of ids) {
          try { service.closeTab(id, { sessionId }) } catch { /* A stale tab must not block the remaining cleanup. */ }
        }
      } catch { /* Optional layout cleanup must never break the classic shell. */ }
    })
  }
  let unsubscribe: (() => void) | undefined
  try { unsubscribe = service.subscribeState(schedule) } catch { /* Still attempt one initial cleanup. */ }
  schedule()
  return () => { stopped = true; try { unsubscribe?.() } catch { /* Service may already have been disposed. */ } }
}
