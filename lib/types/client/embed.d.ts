/**
 * The host-facing contract of the embeddable chart.
 *
 * Kept free of React and of the generated view so both the component and the
 * tests can rely on it: the sidebar mount passes nothing, and every helper here
 * is a no-op for the defaults.
 */
/** Chrome an embedded host keeps: the full workspace, the chart page only, or the chart page plus symbol search. */
export type KlineChrome = 'full' | 'chart' | 'chart-search';
/** Host options for a chart that lives inside a bounded panel (a canvas panel, a rail, a card). */
export interface KlineHostProps {
    /** Bounded panel: anchor dialogs to the panel and lay the chart out for the panel height. */
    embedded?: boolean;
    /** Which workspace chrome to keep. Defaults to the full sidebar workspace. */
    chrome?: KlineChrome;
    /** Pin the palette instead of following the host document. */
    theme?: 'dark' | 'light';
    /** Follow an external instrument selection (the canvas `instrument` channel). */
    symbol?: string;
    name?: string;
}
/** The window-level bridge the view installs for an embedded mount. */
export interface KlineEmbedApi {
    ready: Promise<unknown>;
    openSymbol(symbol: string, name?: string): Promise<unknown>;
    currentSymbol(): string;
    setTheme(theme: 'dark' | 'light' | 'host'): void;
}
/**
 * The attributes an embedded host turns on. The sidebar passes the defaults and
 * gets `{}` — no attribute, so none of the embedding CSS can ever match it.
 */
export declare function klineHostDataset({ embedded, chrome }?: Pick<KlineHostProps, 'embedded' | 'chrome'>): Record<string, string>;
/** Exchange suffix in a symbol is optional: `600519` and `600519.SH` are the same instrument. */
export declare function symbolKey(value: string | undefined): string;
/** Compare two instruments the way a host bus would: suffix-insensitive, empty never matches. */
export declare function sameSymbol(left: string | undefined, right: string | undefined): boolean;
