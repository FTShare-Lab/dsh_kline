import { useCallback, useRef } from 'react'
import type { ClientContext } from './client-context'
import { StandaloneKlineApp } from './KlineContent'
import type { KlineChrome } from './embed'
import { createPanelMounts, type KlinePanelProps, type KlinePanelsService } from './host-panels.ts'
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
  const requests = new Map<string, { chrome?: KlineChrome }>()
  const mounted = new Map<string, () => void>()
  let mounts: KlinePanelsService | undefined

  const flush = () => {
    if (mounts === undefined) return
    for (const [seat, options] of requests) {
      if (mounted.has(seat)) continue
      mounted.set(seat, mounts.mount(seat, options))
    }
  }
  const panelBody = (seat: string, chrome: KlineChrome | undefined) => (props: KlinePanelProps) =>
    <KlinePanelHost seat={seat} chrome={chrome} {...props} />

  ctx.inject(['slots'], scoped => {
    scoped.effect(() => {
      const slots = scoped.get('slots') as SlotsService | undefined
      mounts = slots === undefined ? undefined : createPanelMounts({ slots }, panelBody)
      flush()
      return () => {
        for (const dispose of mounted.values()) dispose()
        mounted.clear()
        mounts = undefined
      }
    }, 'dsh-kline: host panels')
  })

  ctx.provide('klinePanels', {
    mount(seat, options) {
      requests.set(seat, options ?? {})
      flush()
      return () => {
        mounted.get(seat)?.()
        mounted.delete(seat)
        requests.delete(seat)
      }
    },
  } satisfies KlinePanelsService)
}
