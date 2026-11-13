import { useCallback, useRef } from 'react'
import type { ClientContext } from './client-context'
import { StandaloneKlineApp } from './KlineContent'
import type { KlineChrome } from './embed'
import { createPanelMountRegistry, createPanelMounts, type KlinePanelProps, type KlinePanelsService } from './host-panels.ts'
import type { SlotsService } from './native-sidebar-services'

/**
 * The chart as a host panel body.
 *
 * The host declares a slot, renders it with `{ symbol, name, onIdentity }` and
 * asks the chart to fill it through `klinePanels.mount(seat)`. The body is the
 * same chart the sidebar and the tab draw, only bounded and without the
 * workspace chrome that belongs to the sidebar.
 */
export function KlinePanelHost({ seat, chrome = 'chart-search', symbol, name, onIdentity }:
  KlinePanelProps & { seat: string; chrome?: KlineChrome }) {
  // The host may hand over a fresh callback per render; keep the chart's effect
  // dependencies stable through a ref so a re-render never remounts it.
  const identity = useRef(onIdentity)
  identity.current = onIdentity
  const publishIdentity = useCallback((nextSymbol?: string, nextName?: string) => {
    identity.current?.(nextSymbol, nextName)
  }, [])
  return (
    <div data-symbol={symbol ?? ''} style={{ width: '100%', height: '100%', minHeight: 360 }}>
      <StandaloneKlineApp
        conversationId={'host-panel:' + seat}
        embedded
        chrome={chrome}
        symbol={symbol}
        name={name}
        onIdentity={publishIdentity}
      />
    </div>
  )
}

/**
 * Register the optional host panel contract.
 *
 * The `klinePanels` service exists for every host, but it registers nothing
 * until a host mounts a seat: without a caller no slot is injected, so a host
 * that does not know this contract sees the plugin exactly as before. Mounts
 * requested before the `slots` service settles are applied once it does.
 * @param ctx - the client context to register on.
 */
export function registerPanelHosts(ctx: ClientContext): void {
  const panels = createPanelMountRegistry()
  const panelBody = (seat: string, chrome: KlineChrome | undefined) => (props: KlinePanelProps) =>
    <KlinePanelHost seat={seat} chrome={chrome} {...props} />

  ctx.inject(['slots'], scoped => {
    scoped.effect(() => {
      const slots = scoped.get('slots') as SlotsService | undefined
      if (slots === undefined) return () => {}
      return panels.connect(createPanelMounts({ slots }, panelBody))
    }, 'dsh-kline: host panels')
  })

  ctx.provide('klinePanels', {
    mount: panels.mount,
  } satisfies KlinePanelsService)
}
