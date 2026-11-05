/**
 * The host-facing contract of the embeddable chart.
 *
 * Kept free of React and of the generated view so both the component and the
 * tests can rely on it: the sidebar mount passes nothing, and every helper here
 * is a no-op for the defaults.
 */

/** Chrome an embedded host keeps: the full workspace, the chart page only, or the chart page plus symbol search. */
export type KlineChrome = 'full' | 'chart' | 'chart-search'

/** Host options for a chart that lives inside a bounded panel (a canvas panel, a rail, a card). */
export interface KlineHostProps {
  /** Bounded panel: anchor dialogs to the panel and lay the chart out for the panel height. */
  embedded?: boolean
  /** Which workspace chrome to keep. Defaults to the full sidebar workspace. */
  chrome?: KlineChrome
  /** Pin the palette instead of following the host document. */
  theme?: 'dark' | 'light'
  /** Follow an external instrument selection (the canvas `instrument` channel). */
  symbol?: string
  name?: string
}

/** The window-level bridge the view installs for an embedded mount. */
export interface KlineEmbedApi {
  ready: Promise<unknown>
  openSymbol(symbol: string, name?: string): Promise<unknown>
  currentSymbol(): string
  setTheme(theme: 'dark' | 'light' | 'host'): void
}

/**
 * The attributes an embedded host turns on. The sidebar passes the defaults and
 * gets `{}` — no attribute, so none of the embedding CSS can ever match it.
 */
export function klineHostDataset({ embedded = false, chrome = 'full' }: Pick<KlineHostProps, 'embedded' | 'chrome'> = {}): Record<string, string> {
  const dataset: Record<string, string> = {}
  if (embedded) dataset['data-embedded'] = ''
  if (chrome !== 'full') dataset['data-chrome'] = chrome
  return dataset
}

/** Normalize host identities using the chart's input conventions, retaining the market. */
export function symbolKey(value: string | undefined): string {
  const raw = String(value ?? '').trim().toUpperCase().replace(/\s+/g, '')
  const exchanges: Record<string, string> = { SH: 'XSHG', SZ: 'XSHE', BJ: 'BJSE' }
  const prefixed = raw.match(/^(SH|SZ|BJ)(\d{6})$/)
  if (prefixed) return `${prefixed[2]}.${exchanges[prefixed[1]]}`
  const suffixed = raw.match(/^(\d{1,6})\.(SH|SZ|BJ|XSHG|XSHE|BJSE|HK|HKG)$/)
  if (suffixed) {
    const market = exchanges[suffixed[2]] || (suffixed[2] === 'HKG' ? 'HK' : suffixed[2])
    return `${market === 'HK' ? suffixed[1].padStart(5, '0') : suffixed[1]}.${market}`
  }
  const us = raw.match(/^([A-Z][A-Z0-9._-]{0,15})\.(US|NASDAQ|NYSE)$/)
  if (us) return `${us[1]}.US`
  // Match normalizeSymbolInput in the chart: bare codes use its routing
  // defaults, rather than matching every exchange with the same numeric code.
  if (/^\d{6}$/.test(raw)) return `${raw}.${raw.startsWith('6') ? 'XSHG' : 'XSHE'}`
  if (/^\d{1,5}$/.test(raw)) return `${raw.padStart(5, '0')}.HK`
  if (/^[A-Z][A-Z0-9_-]{0,15}$/.test(raw)) return `${raw}.US`
  return raw
}

/** Only an exact normalized identity is the same instrument; empty never matches. */
export function sameSymbol(left: string | undefined, right: string | undefined): boolean {
  const a = symbolKey(left)
  const b = symbolKey(right)
  return a !== '' && a === b
}
