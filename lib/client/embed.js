/**
 * The host-facing contract of the embeddable chart.
 *
 * Kept free of React and of the generated view so both the component and the
 * tests can rely on it: the sidebar mount passes nothing, and every helper here
 * is a no-op for the defaults.
 */
/**
 * The attributes an embedded host turns on. The sidebar passes the defaults and
 * gets `{}` — no attribute, so none of the embedding CSS can ever match it.
 */
export function klineHostDataset({ embedded = false, chrome = 'full' } = {}) {
    const dataset = {};
    if (embedded)
        dataset['data-embedded'] = '';
    if (chrome !== 'full')
        dataset['data-chrome'] = chrome;
    return dataset;
}
/** Normalize host identities using the chart's input conventions, retaining the market. */
export function symbolKey(value) {
    const raw = String(value ?? '').trim().toUpperCase().replace(/\s+/g, '');
    const exchanges = { SH: 'XSHG', SZ: 'XSHE', BJ: 'BJSE' };
    const prefixed = raw.match(/^(SH|SZ|BJ)(\d{6})$/);
    if (prefixed)
        return `${prefixed[2]}.${exchanges[prefixed[1]]}`;
    const suffixed = raw.match(/^(\d{1,6})\.(SH|SZ|BJ|XSHG|XSHE|BJSE|HK|HKG)$/);
    if (suffixed) {
        const market = exchanges[suffixed[2]] || (suffixed[2] === 'HKG' ? 'HK' : suffixed[2]);
        return `${market === 'HK' ? suffixed[1].padStart(5, '0') : suffixed[1]}.${market}`;
    }
    const us = raw.match(/^([A-Z][A-Z0-9._-]{0,15})\.(US|NASDAQ|NYSE)$/);
    if (us)
        return `${us[1]}.US`;
    // Match normalizeSymbolInput in the chart: bare codes use its routing
    // defaults, rather than matching every exchange with the same numeric code.
    if (/^\d{6}$/.test(raw))
        return `${raw}.${raw.startsWith('6') ? 'XSHG' : 'XSHE'}`;
    if (/^\d{1,5}$/.test(raw))
        return `${raw.padStart(5, '0')}.HK`;
    if (/^[A-Z][A-Z0-9_-]{0,15}$/.test(raw))
        return `${raw}.US`;
    return raw;
}
/** Only an exact normalized identity is the same instrument; empty never matches. */
export function sameSymbol(left, right) {
    const a = symbolKey(left);
    const b = symbolKey(right);
    return a !== '' && a === b;
}
