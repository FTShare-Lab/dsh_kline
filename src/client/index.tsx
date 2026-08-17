import { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { mountKlineView } from './generated-view'

export const inject: string[] = []

const PANEL_MIN = 420
const PANEL_MAX = 920
const PANEL_DEFAULT = 680
const SESSION_ENDPOINT = '/dsh-kline/session'
const STORAGE_KEY = 'dsh-kline:sidebar:v1'

interface ClientContext {
  effect(callback: () => () => void, label: string): void
}

interface ChartSession {
  ok: true
  session: string
  symbol?: string
  name?: string
  published_at: number
}

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface ChartCommand {
  type?: string
  name?: string
  rows?: Candle[]
  params?: { periods?: number[] }
  from?: { price?: number }
  to?: { price?: number }
  label?: string
}

interface ChartPayload {
  symbol?: string
  name?: string
  interval?: string
  data_source?: string
  chartCommands?: ChartCommand[]
}

interface SecurityWorkspace {
  news?: Array<{ title?: string; time?: string; summary?: string; kind?: string; source_url?: string }>
  overview?: {
    company_name?: string
    market?: string
    industry?: string
    listing_date?: string
    website?: string
    description?: string
    metrics?: Array<{ label?: string; value?: string }>
    details?: Array<{ label?: string; value?: string; group?: string }>
  }
  source?: { name?: string; updated_at?: string }
}

declare global {
  interface Window {
    klinecharts?: any
    __dshKlineVendorPromise?: Promise<any>
    __dshKlineVwapRegistered?: boolean
  }
}

interface SidebarState {
  open: boolean
  width: number
}

export function apply(ctx: ClientContext): void {
  ctx.effect(() => {
    installStyles()
    const host = document.createElement('div')
    host.dataset.dshKlineSidebar = ''
    document.body.appendChild(host)
    const root = createRoot(host)
    root.render(<KlineSidebar />)
    return () => {
      root.unmount()
      host.remove()
      document.getElementById('dsh-kline-sidebar-styles')?.remove()
      document.documentElement.style.removeProperty('--dsh-kline-sidebar-width')
    }
  }, 'dsh-kline: sidebar mount')
}

function KlineSidebar() {
  const [state, setState] = useState<SidebarState>(readState)
  const [session, setSession] = useState<ChartSession>()
  const [available, setAvailable] = useState(true)
  const drag = useRef<{ startX: number; startWidth: number }>()
  const compact = useCompactLayout()
  const panelWidth = compact ? window.innerWidth : state.width
  const reservedWidth = state.open && !compact ? panelWidth : 0

  useEffect(() => {
    document.documentElement.style.setProperty('--dsh-kline-sidebar-width', `${reservedWidth}px`)
    writeState(state)
  }, [reservedWidth, state])

  useEffect(() => {
    let active = true
    let timer: number | undefined
    const refresh = async () => {
      try {
        const response = await fetch(SESSION_ENDPOINT, { cache: 'no-store' })
        const payload = await response.json() as Partial<ChartSession> & { ok?: boolean }
        if (!active) return
        if (response.ok && payload.ok === true && typeof payload.session === 'string') {
          setSession(payload as ChartSession)
          setAvailable(true)
        } else {
          setAvailable(response.ok)
        }
      } catch {
        if (active) setAvailable(false)
      } finally {
        if (active) timer = window.setTimeout(refresh, 1200)
      }
    }
    void refresh()
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [])

  const setOpen = (open: boolean) => setState(current => ({ ...current, open }))

  return (
    <>
      <button
        type="button"
        className={`dsh-kline-rail ${state.open ? 'is-open' : ''}`}
        aria-label={state.open ? '收起 K 线侧栏' : '打开 K 线侧栏'}
        aria-expanded={state.open}
        title={state.open ? '收起 K 线侧栏' : '打开 K 线侧栏'}
        onClick={() => setOpen(!state.open)}
      >
        <span aria-hidden="true">K</span>
      </button>
      <aside
        className={`dsh-kline-panel ${state.open ? '' : 'is-hidden'}`}
        style={{ width: panelWidth }}
        aria-label="K 线分析侧栏"
        aria-hidden={!state.open}
      >
        {!compact && (
          <div
            className="dsh-kline-resize"
            role="separator"
            aria-label="调整 K 线侧栏宽度"
            aria-orientation="vertical"
            aria-valuemin={PANEL_MIN}
            aria-valuemax={PANEL_MAX}
            aria-valuenow={panelWidth}
            tabIndex={0}
            onKeyDown={(event) => {
              const next = keyboardWidth(event.key, state.width)
              if (next === undefined) return
              event.preventDefault()
              setState(current => ({ ...current, width: next }))
            }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId)
              drag.current = { startX: event.clientX, startWidth: state.width }
            }}
            onPointerMove={(event) => {
              if (!event.currentTarget.hasPointerCapture(event.pointerId) || drag.current === undefined) return
              const width = clampWidth(drag.current.startWidth + drag.current.startX - event.clientX)
              setState(current => ({ ...current, width }))
            }}
            onPointerUp={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId)
              }
              drag.current = undefined
            }}
          />
        )}
        <header className="dsh-kline-header">
          <div>
            <strong>{session?.name || session?.symbol || 'K 线分析'}</strong>
            {session?.name && session.symbol && <small>{session.symbol}</small>}
          </div>
          <button type="button" aria-label="关闭 K 线侧栏" title="关闭" onClick={() => setOpen(false)}>x</button>
        </header>
        <div className="dsh-kline-content">
          {session ? (
            <NativeKlineApp key={session.session} session={session} />
          ) : (
            <div className="dsh-kline-empty" role="status">
              <strong>{available ? '暂无 K 线图' : '图表服务未连接'}</strong>
              <span>{available ? '分析完成后将在此显示' : '请检查 dsh_kline MCP 状态'}</span>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}

const INDICATORS = ['ma', 'vwap', 'vol', 'macd', 'kdj', 'boll', 'rsi', 'atr'] as const
type IndicatorName = typeof INDICATORS[number]
type SecurityTab = 'chart' | 'news' | 'overview'

function NativeKlineApp({ session }: { session: ChartSession }) {
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let dispose: (() => void) | undefined
    Promise.all([
      fetch('/dsh-kline/data', { cache: 'no-store' }).then(response => response.json()),
      loadKlinecharts(),
    ]).then(([result]) => {
      if (!active || !host.current) return
      if (!result?.ok || !result?.payload) throw new Error(result?.message || '图表会话不可用')
      const root = host.current.shadowRoot || host.current.attachShadow({ mode: 'open' })
      dispose = mountKlineView(root, result.payload)
    }).catch(reason => active && setError(String(reason?.message || reason)))
    return () => {
      active = false
      dispose?.()
    }
  }, [session.session])

  return (
    <div className="dsh-kline-native-host" ref={host}>
      {error && <div className="dsh-kline-error" role="alert">{error}</div>}
    </div>
  )
}

function SimplifiedNativeKlineApp({ session }: { session: ChartSession }) {
  const [payload, setPayload] = useState<ChartPayload>()
  const [rows, setRows] = useState<Candle[]>([])
  const [active, setActive] = useState<Set<IndicatorName>>(new Set(['ma', 'vol']))
  const [range, setRange] = useState('1Y')
  const [interval, setInterval] = useState('day')
  const [tab, setTab] = useState<SecurityTab>('chart')
  const [workspace, setWorkspace] = useState<SecurityWorkspace>()
  const [loading, setLoading] = useState(true)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let activeRequest = true
    setLoading(true)
    setError('')
    fetch('/dsh-kline/data', { cache: 'no-store' })
      .then(response => response.json())
      .then((result: { ok?: boolean; payload?: ChartPayload; message?: string }) => {
        if (!activeRequest) return
        if (!result.ok || !result.payload) throw new Error(result.message || '图表会话不可用')
        const nextPayload = result.payload
        const nextRows = chartRows(nextPayload)
        setPayload(nextPayload)
        setRows(nextRows)
        setInterval(nextPayload.interval || 'day')
        setActive(chartIndicators(nextPayload))
      })
      .catch(reason => activeRequest && setError(String(reason?.message || reason)))
      .finally(() => activeRequest && setLoading(false))
    return () => { activeRequest = false }
  }, [session.session])

  useEffect(() => {
    const symbol = payload?.symbol || session.symbol
    if (!symbol) return
    let activeRequest = true
    setWorkspaceLoading(true)
    callChartTool('fetch_security_workspace', { symbol, name: payload?.name || session.name })
      .then(result => {
        if (!activeRequest) return
        const content = result?.structuredContent || result
        setWorkspace(content?.security_workspace)
      })
      .catch(() => activeRequest && setWorkspace(undefined))
      .finally(() => activeRequest && setWorkspaceLoading(false))
    return () => { activeRequest = false }
  }, [payload?.symbol, session.symbol])

  const visibleRows = useMemo(() => cropRows(rows, range), [range, rows])
  const levels = useMemo(() => chartLevels(payload), [payload])
  const maPeriods = useMemo(() => chartMaPeriods(payload), [payload])

  const toggleIndicator = (name: IndicatorName) => {
    setActive(current => {
      const next = new Set(current)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const changeInterval = async (nextInterval: string) => {
    if (nextInterval === interval || !session.symbol) return
    setLoading(true)
    setError('')
    try {
      const result = await callChartTool('fetch_candles', {
        symbol: session.symbol,
        interval: nextInterval,
        interval_value: 1,
        limit: 1200,
        adjust: 'none',
      })
      const content = result?.structuredContent || result
      if (!content?.ok || !Array.isArray(content.rows)) throw new Error(content?.message || '周期数据获取失败')
      setRows(content.rows)
      setInterval(nextInterval)
      setRange('1Y')
    } catch (reason) {
      setError(String((reason as Error)?.message || reason))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="dsh-kline-native">
      <nav className="dsh-kline-tabs" aria-label="标的内容">
        <button type="button" className={tab === 'chart' ? 'active' : ''} onClick={() => setTab('chart')}>图表</button>
        <button type="button" className={tab === 'news' ? 'active' : ''} onClick={() => setTab('news')}>新闻{workspace?.news?.length ? ` ${workspace.news.length}` : ''}</button>
        <button type="button" className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>简况</button>
      </nav>
      {tab === 'chart' && (
        <>
          <div className="dsh-kline-toolbar" aria-label="时间范围">
            {['30D', '1Y', '5Y', 'ALL'].map(value => (
              <button type="button" className={range === value ? 'active' : ''} key={value} onClick={() => setRange(value)}>{value}</button>
            ))}
            <span className="dsh-kline-toolbar-separator" />
            {[['day', '日线'], ['week', '周线'], ['month', '月线']].map(([value, label]) => (
              <button type="button" className={interval === value ? 'active' : ''} key={value} onClick={() => void changeInterval(value)}>{label}</button>
            ))}
          </div>
          <div className="dsh-kline-toolbar dsh-kline-indicators" aria-label="技术指标">
            {INDICATORS.map(name => (
              <button
                type="button"
                aria-pressed={active.has(name)}
                className={active.has(name) ? 'active' : ''}
                key={name}
                onClick={() => toggleIndicator(name)}
              >{name.toUpperCase()}</button>
            ))}
          </div>
          {error && <div className="dsh-kline-error" role="alert">{error}</div>}
          <div className="dsh-kline-chart-shell">
            {loading && <div className="dsh-kline-loading" role="status">正在加载 K 线...</div>}
            <KlineCanvas rows={visibleRows} indicators={active} levels={levels} maPeriods={maPeriods} />
          </div>
          <LevelSummary levels={levels} />
        </>
      )}
      {tab === 'news' && <NewsPanel workspace={workspace} loading={workspaceLoading} />}
      {tab === 'overview' && <OverviewPanel workspace={workspace} loading={workspaceLoading} />}
    </section>
  )
}

function KlineCanvas({ rows, indicators, levels, maPeriods }: {
  rows: Candle[]
  indicators: Set<IndicatorName>
  levels: Array<{ price: number; label: string }>
  maPeriods: number[]
}) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    let observer: ResizeObserver | undefined
    let chart: any
    void loadKlinecharts().then(klinecharts => {
      if (disposed || !container.current || !rows.length) return
      chart = klinecharts.init(container.current, chartStyles())
      chart.applyNewData(rows.map(row => ({ ...row, timestamp: normalizeTimestamp(row.time) })))
      let priceIndicatorExists = false
      if (indicators.has('ma')) {
        chart.createIndicator({ name: 'MA', calcParams: maPeriods }, false, { id: 'candle_pane' })
        priceIndicatorExists = true
      }
      if (indicators.has('vwap')) {
        registerVwap(klinecharts)
        chart.createIndicator('DSHVWAP', priceIndicatorExists, { id: 'candle_pane' })
        priceIndicatorExists = true
      }
      if (indicators.has('boll')) {
        chart.createIndicator('BOLL', priceIndicatorExists, { id: 'candle_pane' })
      }
      if (indicators.has('vol')) chart.createIndicator('VOL', false, { id: 'vol_pane', height: 118 })
      if (indicators.has('macd')) chart.createIndicator('MACD', false, { id: 'macd_pane', height: 118 })
      if (indicators.has('kdj')) chart.createIndicator('KDJ', false, { id: 'kdj_pane', height: 112 })
      if (indicators.has('rsi')) chart.createIndicator('RSI', false, { id: 'rsi_pane', height: 104 })
      if (indicators.has('atr')) chart.createIndicator('ATR', false, { id: 'atr_pane', height: 104 })
      const timestamp = normalizeTimestamp(rows.at(-1)?.time || 0)
      for (const level of levels) {
        try {
          chart.createOverlay({
            name: 'horizontalStraightLine',
            groupId: 'analysis-levels',
            lock: true,
            points: [{ timestamp, value: level.price }],
          })
        } catch {}
      }
      chart.setOffsetRightDistance?.(72)
      observer = new ResizeObserver(() => chart?.resize?.())
      observer.observe(container.current)
    }).catch(() => {})
    return () => {
      disposed = true
      observer?.disconnect()
      if (container.current && window.klinecharts) {
        try { window.klinecharts.dispose(container.current) } catch {}
      }
    }
  }, [rows, indicators, levels, maPeriods])

  return <div className="dsh-kline-chart" ref={container} aria-label="交互式 K 线图" />
}

function NewsPanel({ workspace, loading }: { workspace?: SecurityWorkspace; loading: boolean }) {
  if (loading) return <div className="dsh-kline-pane-empty">正在加载新闻...</div>
  const news = workspace?.news || []
  if (!news.length) return <div className="dsh-kline-pane-empty">暂无可用新闻</div>
  return (
    <div className="dsh-kline-news">
      {news.map((item, index) => {
        const url = /^https:\/\//i.test(item.source_url || '') ? item.source_url : undefined
        return (
          <article key={`${item.title}-${index}`}>
            <div><span>{item.kind || '资讯'}</span>{url ? <a href={url} target="_blank" rel="noreferrer">{item.title}</a> : <strong>{item.title}</strong>}</div>
            <time>{item.time || '--'}</time>
            {item.summary && <p>{item.summary}</p>}
          </article>
        )
      })}
      <SourceLine workspace={workspace} />
    </div>
  )
}

function OverviewPanel({ workspace, loading }: { workspace?: SecurityWorkspace; loading: boolean }) {
  if (loading) return <div className="dsh-kline-pane-empty">正在加载基本面信息...</div>
  const overview = workspace?.overview
  if (!overview) return <div className="dsh-kline-pane-empty">暂无可用基本面信息</div>
  return (
    <div className="dsh-kline-overview">
      <h3>{overview.company_name || '公司简况'}</h3>
      <div className="dsh-kline-facts">
        {[['市场', overview.market], ['行业', overview.industry], ['上市日期', overview.listing_date]].filter(([, value]) => value && value !== '--').map(([label, value]) => (
          <div key={label}><span>{label}</span><strong>{value}</strong></div>
        ))}
      </div>
      {!!overview.metrics?.length && <div className="dsh-kline-metrics">{overview.metrics.map((item, index) => <div key={`${item.label}-${index}`}><span>{item.label}</span><strong>{item.value}</strong></div>)}</div>}
      {!!overview.details?.length && <dl>{overview.details.map((item, index) => <div key={`${item.label}-${index}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>}
      {overview.description && overview.description !== '--' && <p>{overview.description}</p>}
      <SourceLine workspace={workspace} />
    </div>
  )
}

function SourceLine({ workspace }: { workspace?: SecurityWorkspace }) {
  return <footer>数据源 {workspace?.source?.name || 'FTShare'}{workspace?.source?.updated_at ? ` · ${workspace.source.updated_at}` : ''}</footer>
}

function LevelSummary({ levels }: { levels: Array<{ price: number; label: string }> }) {
  if (!levels.length) return null
  return <div className="dsh-kline-levels" aria-label="支撑位和压力位">{levels.map((level, index) => <span key={`${level.price}-${index}`}>{level.label || '分析位'} {level.price.toFixed(2)}</span>)}</div>
}

function chartRows(payload?: ChartPayload): Candle[] {
  return payload?.chartCommands?.find(command => command.type === 'SET_CANDLES')?.rows || []
}

function chartIndicators(payload: ChartPayload): Set<IndicatorName> {
  const names = new Set<IndicatorName>()
  for (const command of payload.chartCommands || []) {
    const name = String(command.name || '').toLowerCase() as IndicatorName
    if (INDICATORS.includes(name)) names.add(name)
  }
  if (!names.size) ['ma', 'vol'].forEach(name => names.add(name as IndicatorName))
  return names
}

function chartMaPeriods(payload?: ChartPayload): number[] {
  const periods = payload?.chartCommands?.find(command => String(command.name).toLowerCase() === 'ma')?.params?.periods
  return periods?.filter(value => Number.isInteger(value) && value >= 2 && value <= 200).slice(0, 6) || [5, 10, 20, 30, 60]
}

function chartLevels(payload?: ChartPayload): Array<{ price: number; label: string }> {
  const seen = new Set<string>()
  const levels: Array<{ price: number; label: string }> = []
  for (const command of payload?.chartCommands || []) {
    if (!['DRAW_TREND_LINE', 'TEXT_MARKER'].includes(command.type || '')) continue
    const price = Number(command.to?.price ?? command.from?.price)
    const label = String(command.label || '')
    if (!Number.isFinite(price) || !/(支撑|压力|support|resistance)/i.test(label)) continue
    const key = price.toFixed(6)
    if (seen.has(key)) continue
    seen.add(key)
    levels.push({ price, label })
  }
  return levels
}

function cropRows(rows: Candle[], range: string): Candle[] {
  const count = range === '30D' ? 30 : range === '1Y' ? 260 : range === '5Y' ? 1300 : rows.length
  return rows.slice(-Math.min(rows.length, count))
}

function normalizeTimestamp(value: number): number {
  return value < 10_000_000_000 ? value * 1000 : value
}

async function callChartTool(name: string, args: Record<string, unknown>): Promise<any> {
  const response = await fetch(`/dsh-kline/api/tools/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload?.message || payload?.error || `${name} failed`)
  return payload
}

function loadKlinecharts(): Promise<any> {
  if (window.klinecharts) return Promise.resolve(window.klinecharts)
  if (window.__dshKlineVendorPromise) return window.__dshKlineVendorPromise
  window.__dshKlineVendorPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/dsh-kline/vendor/klinecharts.min.js'
    script.async = true
    script.onload = () => window.klinecharts ? resolve(window.klinecharts) : reject(new Error('KLineCharts 未加载'))
    script.onerror = () => reject(new Error('KLineCharts 加载失败'))
    document.head.appendChild(script)
  })
  return window.__dshKlineVendorPromise
}

function registerVwap(klinecharts: any): void {
  if (window.__dshKlineVwapRegistered) return
  klinecharts.registerIndicator({
    name: 'DSHVWAP',
    shortName: 'VWAP',
    series: 'price',
    precision: 2,
    calc: (dataList: Array<{ high: number; low: number; close: number; volume: number }>) => {
      let amount = 0
      let volume = 0
      return dataList.map(row => {
        const currentVolume = Number(row.volume) || 0
        amount += ((Number(row.high) + Number(row.low) + Number(row.close)) / 3) * currentVolume
        volume += currentVolume
        return { vwap: volume ? amount / volume : Number(row.close) }
      })
    },
    figures: [{ key: 'vwap', title: 'VWAP: ', type: 'line' }],
  })
  window.__dshKlineVwapRegistered = true
}

function chartStyles(): Record<string, unknown> {
  return {
    grid: { horizontal: { color: '#edf0f4' }, vertical: { color: '#edf0f4' } },
    candle: {
      bar: { upColor: '#ef476f', downColor: '#00a878', noChangeColor: '#7a8495' },
      priceMark: { last: { upColor: '#ef476f', downColor: '#00a878' } },
      tooltip: { showRule: 'follow_cross', showType: 'standard' },
    },
    indicator: { tooltip: { showRule: 'follow_cross', showType: 'standard' } },
    xAxis: { axisLine: { color: '#d9dde5' }, tickText: { color: '#677286' } },
    yAxis: { axisLine: { color: '#d9dde5' }, tickText: { color: '#677286' } },
    separator: { color: '#d9dde5', fill: true, activeBackgroundColor: '#eef1f5' },
    crosshair: { horizontal: { line: { color: '#7a8495' } }, vertical: { line: { color: '#7a8495' } } },
  }
}

function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(() => window.innerWidth <= 900)
  useEffect(() => {
    const update = () => setCompact(window.innerWidth <= 900)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return compact
}

function keyboardWidth(key: string, width: number): number | undefined {
  if (key === 'Home') return PANEL_MIN
  if (key === 'End') return PANEL_MAX
  if (key === 'ArrowLeft') return clampWidth(width - 20)
  if (key === 'ArrowRight') return clampWidth(width + 20)
  return undefined
}

function clampWidth(width: number): number {
  return Math.min(PANEL_MAX, Math.max(PANEL_MIN, Math.round(width)))
}

function readState(): SidebarState {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') as Partial<SidebarState>
    return {
      open: typeof value.open === 'boolean' ? value.open : true,
      width: clampWidth(typeof value.width === 'number' ? value.width : PANEL_DEFAULT),
    }
  } catch {
    return { open: true, width: PANEL_DEFAULT }
  }
}

function writeState(state: SidebarState): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // The sidebar remains functional when browser storage is unavailable.
  }
}

function installStyles(): void {
  if (document.getElementById('dsh-kline-sidebar-styles')) return
  const style = document.createElement('style')
  style.id = 'dsh-kline-sidebar-styles'
  style.textContent = `
    :root { --dsh-kline-sidebar-width: 0px; }
    #root { margin-right: calc(var(--dsh-sidebar-width, 0px) + var(--dsh-kline-sidebar-width)); transition: margin-right .2s ease; }
    .dsh-kline-panel { position: fixed; z-index: 52; top: 0; right: var(--dsh-sidebar-width, 0px); bottom: 0; display: flex; box-sizing: border-box; max-width: 100vw; flex-direction: column; overflow: hidden; border-left: 1px solid var(--dsw-alias-border-l2, #d9dde5); color: var(--dsw-alias-label-primary, #172033); background: var(--dsw-specific-sidebar-fill, #fff); box-shadow: -8px 0 24px rgb(19 32 54 / 8%); transition: transform .2s ease, visibility 0s; }
    .dsh-kline-panel.is-hidden { visibility: hidden; pointer-events: none; transform: translateX(102%); transition: transform .2s ease, visibility 0s linear .2s; }
    .dsh-kline-header { display: flex; min-height: 54px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 14px 0 18px; border-bottom: 1px solid var(--dsw-alias-border-l2, #d9dde5); background: var(--dsw-specific-sidebar-fill, #fff); }
    .dsh-kline-header > div { display: flex; min-width: 0; align-items: baseline; gap: 8px; }
    .dsh-kline-header strong { overflow: hidden; font-size: 14px; line-height: 20px; text-overflow: ellipsis; white-space: nowrap; }
    .dsh-kline-header small { color: var(--dsw-alias-label-tertiary, #7a8495); font-size: 11px; white-space: nowrap; }
    .dsh-kline-header button { display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 6px; color: inherit; background: transparent; cursor: pointer; font: 20px/1 system-ui; }
    .dsh-kline-header button:hover { background: var(--dsw-alias-interactive-bg-hover, #eef1f5); }
    .dsh-kline-content { min-height: 0; flex: 1; overflow: hidden; background: #fff; }
    .dsh-kline-native-host { display: block; width: 100%; height: 100%; overflow: hidden; background: #fff; }
    .dsh-kline-native { display: flex; height: 100%; min-width: 340px; flex-direction: column; overflow: hidden; color: #20242b; background: #fff; font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .dsh-kline-tabs, .dsh-kline-toolbar { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; padding: 7px 10px; overflow-x: auto; border-bottom: 1px solid #e7ebef; scrollbar-width: none; }
    .dsh-kline-tabs::-webkit-scrollbar, .dsh-kline-toolbar::-webkit-scrollbar { display: none; }
    .dsh-kline-tabs button, .dsh-kline-toolbar button { min-width: 42px; height: 30px; padding: 0 10px; border: 1px solid #dfe4ea; border-radius: 4px; color: #20242b; background: #f7f9fb; cursor: pointer; white-space: nowrap; }
    .dsh-kline-tabs button { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; font-weight: 600; }
    .dsh-kline-tabs button.active { border-bottom-color: #ff6b00; color: #20242b; }
    .dsh-kline-toolbar button.active { border-color: #ff6b00; color: #fff; background: #ff6b00; }
    .dsh-kline-toolbar button:focus-visible, .dsh-kline-tabs button:focus-visible { outline: 2px solid #4d6bfe; outline-offset: 1px; }
    .dsh-kline-toolbar-separator { width: 1px; height: 22px; flex: 0 0 1px; margin: 0 2px; background: #dfe4ea; }
    .dsh-kline-indicators { padding-top: 5px; padding-bottom: 5px; }
    .dsh-kline-chart-shell { position: relative; min-height: 320px; flex: 1 1 auto; overflow: hidden; }
    .dsh-kline-chart { width: 100%; height: 100%; min-height: 320px; }
    .dsh-kline-loading { position: absolute; z-index: 2; inset: 0; display: grid; place-items: center; color: #677286; background: rgb(255 255 255 / 78%); }
    .dsh-kline-error { flex: 0 0 auto; padding: 7px 12px; color: #b42318; background: #fff1f0; }
    .dsh-kline-levels { display: flex; flex: 0 0 auto; gap: 6px; padding: 6px 10px; overflow-x: auto; border-top: 1px solid #e7ebef; scrollbar-width: none; }
    .dsh-kline-levels span { padding: 2px 6px; border-radius: 3px; color: #516070; background: #f1f4f7; white-space: nowrap; }
    .dsh-kline-pane-empty { display: grid; height: 100%; place-items: center; color: #7a8495; }
    .dsh-kline-news, .dsh-kline-overview { min-height: 0; flex: 1; overflow-y: auto; padding: 12px 16px 24px; }
    .dsh-kline-news article { padding: 12px 0; border-bottom: 1px solid #e7ebef; }
    .dsh-kline-news article > div { display: flex; align-items: baseline; gap: 8px; }
    .dsh-kline-news article span { flex: 0 0 auto; padding: 1px 5px; border-radius: 3px; color: #b54708; background: #fff3e8; font-size: 11px; }
    .dsh-kline-news a, .dsh-kline-news strong { color: #20242b; font-weight: 650; text-decoration: none; }
    .dsh-kline-news a:hover { color: #ff6b00; }
    .dsh-kline-news time, .dsh-kline-news p, .dsh-kline-overview p, .dsh-kline-news footer, .dsh-kline-overview footer { color: #7a8495; }
    .dsh-kline-news time { display: block; margin-top: 5px; font-size: 11px; }
    .dsh-kline-news p { margin: 7px 0 0; }
    .dsh-kline-overview h3 { margin: 0 0 12px; font-size: 17px; }
    .dsh-kline-facts, .dsh-kline-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
    .dsh-kline-facts > div, .dsh-kline-metrics > div { min-width: 0; padding: 9px 10px; border: 1px solid #e7ebef; border-radius: 4px; }
    .dsh-kline-facts span, .dsh-kline-metrics span { display: block; color: #7a8495; font-size: 11px; }
    .dsh-kline-facts strong, .dsh-kline-metrics strong { display: block; overflow: hidden; margin-top: 3px; text-overflow: ellipsis; white-space: nowrap; }
    .dsh-kline-overview dl { margin: 0; }
    .dsh-kline-overview dl > div { display: grid; grid-template-columns: minmax(90px, 30%) 1fr; gap: 12px; padding: 8px 0; border-bottom: 1px solid #edf0f4; }
    .dsh-kline-overview dt { color: #7a8495; }
    .dsh-kline-overview dd { margin: 0; overflow-wrap: anywhere; }
    .dsh-kline-news footer, .dsh-kline-overview footer { margin-top: 14px; padding-top: 10px; border-top: 1px solid #e7ebef; font-size: 11px; }
    .dsh-kline-empty { display: flex; height: 100%; align-items: center; justify-content: center; flex-direction: column; gap: 6px; color: var(--dsw-alias-label-tertiary, #7a8495); text-align: center; }
    .dsh-kline-empty strong { color: var(--dsw-alias-label-secondary, #505b6c); font-size: 14px; }
    .dsh-kline-empty span { font-size: 12px; }
    .dsh-kline-rail { position: fixed; z-index: 53; top: 50%; right: calc(var(--dsh-sidebar-width, 0px) + var(--dsh-kline-sidebar-width) + 10px); display: inline-flex; width: 32px; height: 88px; align-items: center; justify-content: center; padding: 0; border: 1px solid var(--dsw-alias-border-l2, #d9dde5); border-radius: 6px; color: var(--dsw-alias-label-primary, #172033); background: var(--dsw-specific-sidebar-fill, #fff); box-shadow: 0 4px 14px rgb(19 32 54 / 10%); cursor: pointer; transform: translateY(-50%); transition: right .2s ease; }
    .dsh-kline-rail span { font: 700 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .dsh-kline-rail:hover { background: var(--dsw-alias-interactive-bg-hover, #eef1f5); }
    .dsh-kline-resize { position: absolute; z-index: 3; top: 0; bottom: 0; left: -4px; width: 8px; cursor: col-resize; touch-action: none; }
    .dsh-kline-resize:hover, .dsh-kline-resize:focus-visible { background: var(--dsw-alias-interactive-bg-hover-accent, #4d6bfe); outline: 0; }
    @media (max-width: 900px) {
      #root { margin-right: var(--dsh-sidebar-width, 0px); }
      .dsh-kline-panel { right: 0; width: 100vw !important; }
      .dsh-kline-rail { top: 74px; right: 10px; width: 36px; height: 36px; transform: none; }
      .dsh-kline-rail.is-open { display: none; }
      .dsh-kline-chart-shell { min-height: 280px; }
      .dsh-kline-chart { min-height: 280px; }
    }
    @media (prefers-reduced-motion: reduce) { #root, .dsh-kline-panel, .dsh-kline-rail { transition: none; } }
  `
  document.head.appendChild(style)
}
