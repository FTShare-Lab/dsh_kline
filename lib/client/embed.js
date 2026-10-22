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
/** Exchange suffix in a symbol is optional: `600519` and `600519.SH` are the same instrument. */
export function symbolKey(value) {
    return String(value ?? '').trim().toUpperCase().replace(/\.(XSHG|XSHE|BJSE|SH|SZ|BJ|HK|US)$/, '');
}
/** Compare two instruments the way a host bus would: suffix-insensitive, empty never matches. */
export function sameSymbol(left, right) {
    const a = symbolKey(left);
    const b = symbolKey(right);
    return a !== '' && b !== '' && (a === b || a.startsWith(b) || b.startsWith(a));
}
