/** Bounded, candle-index-aligned AI price line. No formula source or arbitrary arrays from the host. */
const COLORS = new Set(['info', 'warning', 'success', 'danger']);
const FIELDS = new Set(['open', 'high', 'low', 'close']);
const OPS = new Set(['gt', 'gte', 'lt', 'lte']);
function source(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
        throw Error('invalid_series_source');
    const keys = Object.keys(raw);
    if (FIELDS.has(raw.kind) && keys.length === 1)
        return { kind: raw.kind };
    if ((raw.kind === 'sma' || raw.kind === 'ema') && keys.length === 2 && Number.isSafeInteger(raw.period) && raw.period >= 2 && raw.period <= 200)
        return { kind: raw.kind, period: raw.period };
    throw Error('invalid_series_source');
}
function condition(raw) {
    if (raw == null)
        return null;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).length !== 3 || !OPS.has(raw.op))
        throw Error('invalid_series_condition');
    const left = source(raw.left), right = raw.right;
    if (!right || typeof right !== 'object' || Array.isArray(right) || Object.keys(right).length !== 1)
        throw Error('invalid_series_condition');
    if (right.source !== undefined)
        return { left, op: raw.op, right: { source: source(right.source) } };
    if (typeof right.constant === 'number' && Number.isFinite(right.constant) && right.constant > 0)
        return { left, op: raw.op, right: { constant: right.constant } };
    throw Error('invalid_series_condition');
}
export { source as sanitizePriceSource, condition as sanitizePriceCondition };
export function sanitizePriceSeriesCommand(raw, expectedBars, interval) {
    if (raw?.type !== 'DRAW_AGENT_SERIES_LINE' || typeof raw.id !== 'string' || !/^series_[a-f0-9]{24}$/.test(raw.id)
        || !['minute', 'day', 'week', 'month', 'quarter', 'year'].includes(raw.interval)
        || !COLORS.has(raw.color) || typeof raw.label !== 'string' || raw.label.length > 48
        || !/^[a-f0-9]{64}$/.test(raw.series_hash) || raw.row_hash != null && !/^[a-f0-9]{16}$/.test(raw.row_hash)
        || !Number.isSafeInteger(raw.bar_count)
        || raw.bar_count < 1 || raw.bar_count > 4000 || raw.interval === interval && raw.bar_count !== expectedBars
        || !Array.isArray(raw.values) || raw.values.length !== raw.bar_count
        || raw.values.some((value) => value !== null && (typeof value !== 'number' || !Number.isFinite(value) || value <= 0))
        || !raw.values.some((value) => value !== null))
        throw Error('invalid_source_series');
    return { type: 'DRAW_AGENT_SERIES_LINE', id: raw.id, interval: raw.interval, label: raw.label, color: raw.color,
        bar_count: raw.bar_count, source: source(raw.source), condition: condition(raw.condition),
        values: [...raw.values], series_hash: raw.series_hash, ...(raw.row_hash ? { row_hash: raw.row_hash } : {}) };
}
export function seriesObservation(raw) {
    return { series_hash: raw.series_hash, bar_count: raw.bar_count };
}
