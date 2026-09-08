import { useContext, useEffect, useRef, useState } from 'react'
import { mountKlineView } from './generated-view'
import { InterfaceContext } from './mode-preferences'
import { onboardingKind, acknowledgeOnboarding } from './ui-onboarding'

export interface ChartSession {
  ok: true
  session: string
  symbol?: string
  name?: string
  published_at: number
}

export interface ChartIdentity {
  symbol?: string
  name?: string
}

// The chart view can load data itself through the loopback tool proxy.  It
// therefore does not need an AI-produced chart session to present its search
// workspace; only AI-produced snapshots need the opaque session reference.
const STANDALONE_CHART_PAYLOAD = {
  ok: true,
  workspace_mode: 'launcher',
  default_symbol: '000001.XSHG',
  default_name: '上证指数',
  symbol: '',
  name: '',
  interval: 'day',
  range_key: 'ytd',
  chartCommands: [],
}

export function standaloneChartSession(conversationId?: string): string {
  return `standalone:${conversationId ?? 'global'}`
}

export function standaloneWorkspaceScope(conversationId?: string): string {
  return `direct:${conversationId ?? 'global'}`
}

export function isSymbolLikeName(value: string | undefined, symbol: string | undefined): boolean {
  const text = String(value ?? '').trim()
  const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
  if (!text) return true
  if (normalizedSymbol && text.toUpperCase() === normalizedSymbol) return true
  const bareSymbol = normalizedSymbol.split('.', 1)[0]
  return text.toUpperCase() === bareSymbol
}


declare global {
  interface Window {
    klinecharts?: any
    __dshKlineVendorPromise?: Promise<any>
    __dshKlineVwapRegistered?: boolean
  }
}

export function NativeKlineApp({ session, conversationId, onIdentity }: { session: ChartSession; conversationId: string; onIdentity: (symbol?: string, name?: string) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const interfaceMode = { ...useContext(InterfaceContext), onboardingKind, acknowledgeOnboarding }
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    let dispose: (() => void) | undefined
    Promise.all([
      fetch(`/dsh-kline/data?session=${encodeURIComponent(session.session)}`, { cache: 'no-store', signal: controller.signal }).then(response => response.json()),
      loadKlinecharts(),
    ]).then(([result, klinecharts]) => {
      if (!active || !host.current) return
      if (!result?.ok || !result?.payload) throw new Error(result?.message || '图表会话不可用')
      const root = host.current.shadowRoot || host.current.attachShadow({ mode: 'open' })
      dispose = mountKlineView(root, result.payload, { klinecharts, conversationId, chartSession: session.session, onIdentity, interfaceMode })
    }).catch(reason => active && setError(String(reason?.message || reason)))
    return () => {
      active = false
      controller.abort()
      dispose?.()
    }
  }, [session.session, conversationId])

  return (
    <div className="dsh-kline-native-host" style={{ width: '100%', height: '100%', overflow: 'hidden' }} ref={host}>
      {error && <div className="dsh-kline-error" role="alert">{error}</div>}
    </div>
  )
}

export function StandaloneKlineApp({ conversationId, onIdentity }: { conversationId: string; onIdentity: (symbol?: string, name?: string) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const interfaceMode = { ...useContext(InterfaceContext), onboardingKind, acknowledgeOnboarding }
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let dispose: (() => void) | undefined
    loadKlinecharts().then(klinecharts => {
      if (!active || !host.current) return
      const root = host.current.shadowRoot || host.current.attachShadow({ mode: 'open' })
      dispose = mountKlineView(root, STANDALONE_CHART_PAYLOAD, {
        klinecharts,
        conversationId,
        chartSession: standaloneChartSession(conversationId),
        onIdentity,
        interfaceMode,
      })
    }).catch(reason => active && setError(String(reason?.message || reason)))
    return () => {
      active = false
      dispose?.()
    }
  }, [conversationId, onIdentity])

  return (
    <div className="dsh-kline-native-host" style={{ width: '100%', height: '100%', overflow: 'hidden' }} ref={host}>
      {error && <div className="dsh-kline-error" role="alert">{error}</div>}
    </div>
  )
}

function loadKlinecharts(): Promise<any> {
  const loaded = () => typeof window.klinecharts?.init === 'function' ? window.klinecharts : undefined
  if (loaded()) return Promise.resolve(loaded())
  if (window.__dshKlineVendorPromise) return window.__dshKlineVendorPromise
  window.__dshKlineVendorPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/dsh-kline/vendor/klinecharts.min.js'
    script.async = true
    script.dataset.dshKlineVendor = 'true'
    script.onload = () => loaded() ? resolve(loaded()) : reject(new Error('KLineCharts 已下载但没有正确初始化'))
    script.onerror = () => reject(new Error('KLineCharts 加载失败'))
    document.head.appendChild(script)
  }).catch(error => {
    window.__dshKlineVendorPromise = undefined
    document.querySelector('script[data-dsh-kline-vendor="true"]')?.remove()
    throw error
  })
  return window.__dshKlineVendorPromise
}
