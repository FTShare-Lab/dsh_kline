import { useEffect, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import type { BetterSidebarService } from 'dsh-better-sidebar'
import type { Sessions } from './conversation'
import { ClassicShell } from './ClassicShell'
import { BetterSidebarBridge } from './BetterSidebarTab'
import { isSidebarUsable, cleanClassicTabs } from './sidebar-integration'
import { InterfaceContext, readDisplayMode, resolveDisplayMode } from './mode-preferences'
import { captureOnboarding } from './ui-onboarding'

export const inject = ['sessions']
interface ClientContext {
  effect(callback: () => () => void, label?: string): void
  inject(deps: string[], callback: (ctx: ClientContext) => void): unknown
  get(name: string): unknown
  sessions: Sessions
}
export function apply(ctx: ClientContext) {
  let service: BetterSidebarService | undefined
  const listeners = new Set<() => void>()
  const emit = () => listeners.forEach(listener => listener())
  const preference = readDisplayMode()
  captureOnboarding()
  function Router() {
    const sidebar = useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => service)
    const available = isSidebarUsable(sidebar)
    const mode = resolveDisplayMode(preference, available)
    useEffect(() => {
      if (mode === 'classic' && sidebar) return cleanClassicTabs(sidebar)
    }, [mode, sidebar])
    return <InterfaceContext.Provider value={{ preference, mode, available }}>
      {mode === 'better-sidebar' && sidebar
        ? <BetterSidebarBridge service={sidebar} sessions={ctx.sessions} />
        : <ClassicShell sessions={ctx.sessions} />}
    </InterfaceContext.Provider>
  }
  ctx.effect(() => {
    const host = document.createElement('div')
    host.dataset.dshKlineRouter = ''
    document.body.appendChild(host)
    const root = createRoot(host)
    root.render(<Router />)
    return () => { root.unmount(); host.remove(); listeners.clear() }
  }, 'dsh-kline: interface router')
  // A separate dependency scope does not block the parent when absent.
  ctx.inject(['betterSidebar'], scoped => {
    scoped.effect(() => {
      service = scoped.get('betterSidebar') as BetterSidebarService
      emit()
      return () => { service = undefined; emit() }
    }, 'dsh-kline: optional sidebar')
  })
}
