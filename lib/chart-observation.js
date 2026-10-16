/** Canonical browser observations shared by the server and live view. */
const TOKEN = /^[A-Za-z0-9_-]{32}$/;
export function text(value, max = 128) {
    if (typeof value !== 'string' || value.length > max || /[\x00-\x1f]/.test(value))
        throw Error('invalid_context_text');
    return value;
}
function number(value) {
    if (typeof value !== 'number' || !Number.isFinite(value))
        throw Error('invalid_context_number');
    return value;
}
function time(value) {
    const result = number(value);
    if (!Number.isSafeInteger(result) || result <= 0)
        throw Error('invalid_context_time');
    return result;
}
function point(value) {
    return { time: time(value?.time), price: number(value?.price) };
}
/** Describes browser input -> display only, never vendor-native history or edit authority. */
export function sanitizeDataProvenance(raw) {
    const intervals = ['minute', 'day', 'week', 'month', 'quarter', 'year'];
    const ready = raw?.state === 'ready';
    const source = ready && intervals.includes(raw.source_interval) ? raw.source_interval : null;
    const display = ready && intervals.includes(raw.interval) ? raw.interval : null;
    const input = ready ? raw.data_provenance : null;
    const provider = ['ftshare', 'eastmoney_free', 'tencent_free', 'builtin_free', 'external'].includes(input?.provider) ? input.provider : 'unknown';
    let transformation = 'unknown', aggregation = null;
    if (source && source === display && input?.transformation === 'none')
        transformation = 'none';
    if (source === 'day' && ['week', 'month', 'quarter', 'year'].includes(display) && input?.transformation === 'local_aggregation') {
        const zone = input?.aggregation?.timezone;
        if (typeof zone === 'string' && zone.length <= 64 && /^[A-Za-z_+-]+(?:\/[A-Za-z0-9_+-]+){0,2}$/.test(zone)) {
            try {
                new Intl.DateTimeFormat('en', { timeZone: zone });
                transformation = 'local_aggregation';
                aggregation = { timezone: zone, bucket: display === 'week' ? 'calendar_week_monday' : 'calendar_' + display,
                    ohlcv: 'first_open_max_high_min_low_last_close_sum_volume', timestamp: 'last_source_bar',
                    order: 'aggregate_before_range_crop', completeness: 'not_verified' };
            }
            catch { } // Unknown metadata must not invalidate otherwise valid candles.
        }
    }
    return { scope: 'browser_input_to_display', provider, source_interval: source, display_interval: display,
        transformation, aggregation };
}
export function sanitizeChartContext(raw) {
    if (!raw || !['ready', 'loading', 'empty', 'not_chart', 'error'].includes(raw.state))
        throw Error('invalid_context_state');
    const rows = raw.state === 'ready' ? raw.candles : [];
    if (!Array.isArray(rows) || rows.length > 12000)
        throw Error('invalid_context_rows');
    const candles = rows.map((row) => ({ time: time(row.time), open: number(row.open), high: number(row.high),
        low: number(row.low), close: number(row.close), volume: number(row.volume) }));
    if (raw.state === 'ready' && !candles.length)
        throw Error('invalid_context_rows');
    if (candles.some((r, i) => r.low <= 0 || r.low > Math.min(r.open, r.close) || r.high < Math.max(r.open, r.close)
        || r.volume < 0 || i > 0 && r.time <= candles[i - 1].time))
        throw Error('invalid_context_rows');
    const visible = raw.visible_range;
    let viewport = { available: false, reason: 'not_reported' };
    if (raw.state === 'ready' && visible?.available === true) {
        const from = number(visible.index_from), to = number(visible.index_to_exclusive);
        if (!Number.isSafeInteger(from) || !Number.isSafeInteger(to) || from < 0 || to < from || to > candles.length)
            throw Error('invalid_visible_range');
        viewport = { available: true, index_from: from, index_to_exclusive: to, count: to - from,
            start_time: candles[from]?.time ?? null, end_time: to > from ? candles[to - 1]?.time ?? null : null };
    }
    if (!Array.isArray(raw.drawings) || raw.drawings.length > 512)
        throw Error('invalid_context_drawings');
    const drawings = raw.state === 'ready' ? raw.drawings.map((drawing) => {
        if (!['ai', 'manual', 'automatic'].includes(drawing.origin))
            throw Error('invalid_context_drawing');
        const result = { id: text(drawing.id, 256), kind: text(drawing.kind, 64), origin: drawing.origin,
            name: text(drawing.name ?? '', 128), context_editable: false,
            edit_capability: drawing.origin === 'ai' ? 'source_snapshot_only' : 'read_only' };
        if (typeof drawing.color === 'string')
            result.color = text(drawing.color, 32);
        if (typeof drawing.interval === 'string')
            result.interval = text(drawing.interval, 32);
        if (typeof drawing.price === 'number')
            result.price = number(drawing.price);
        if (Array.isArray(drawing.points))
            result.points = drawing.points.slice(0, 8).map(point);
        for (const key of ['start_time', 'end_time'])
            if (drawing[key] != null)
                result[key] = time(drawing[key]);
        for (const key of ['lower_price', 'upper_price'])
            if (drawing[key] != null)
                result[key] = number(drawing[key]);
        for (const key of ['show_fill', 'show_midline'])
            if (typeof drawing[key] === 'boolean')
                result[key] = drawing[key];
        return result;
    }) : [];
    let selection = null;
    if (raw.state === 'ready' && raw.selection) {
        if (raw.selection.kind === 'candle')
            selection = { kind: 'candle', time: time(raw.selection.time) };
        else if (raw.selection.kind === 'range')
            selection = { kind: 'range', start_time: time(raw.selection.start_time), end_time: time(raw.selection.end_time) };
        else
            throw Error('invalid_context_selection');
    }
    const snapshot = typeof raw.source_chart_session === 'string' && TOKEN.test(raw.source_chart_session) ? raw.source_chart_session : null;
    const intervalValue = raw.interval_value ?? null;
    if (intervalValue !== null && (!Number.isSafeInteger(intervalValue) || intervalValue < 1 || intervalValue > 240))
        throw Error('invalid_interval_value');
    return { schema_version: 1, state: raw.state, symbol: text(raw.symbol ?? '', 64), name: text(raw.name ?? '', 128),
        interval: text(raw.interval ?? '', 32), interval_value: intervalValue, interval_value_status: intervalValue === null ? 'unknown' : 'reported',
        source_interval: text(raw.source_interval ?? '', 32), ui_interval: text(raw.ui_interval ?? '', 32), display_volume_unit: text(raw.display_volume_unit ?? '', 32),
        range_key: text(raw.range_key ?? '', 32), adjust: text(raw.adjust ?? '', 32), active_page: text(raw.active_page ?? '', 32),
        source_chart_session: snapshot, source_snapshot_alignment: 'not_verified', candles, visible_range: viewport,
        loaded_range: { count: candles.length, start_time: candles[0]?.time ?? null, end_time: candles.at(-1)?.time ?? null },
        drawings, selection, selection_status: selection ? 'selected' : raw.selection_status === 'not_supported' ? 'not_supported' : 'none',
        selected_drawing_id: null, selected_drawing_status: 'not_supported',
        indicators: Array.isArray(raw.indicators) ? raw.indicators.map((v) => text(v, 32)).slice(0, 16) : [],
        data_status: text(raw.data_status ?? '', 64), data_provenance: sanitizeDataProvenance(raw),
        render_verified: false, live_view_editable: false };
}
export function observationKey(raw) {
    function ordered(value) {
        if (Array.isArray(value))
            return value.map(ordered);
        if (value && typeof value === 'object')
            return Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])]));
        return value;
    }
    const state = sanitizeChartContext(raw);
    state.drawings.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    return JSON.stringify(ordered(state));
}
export function drawingInventory(payload) {
    const kinds = { DRAW_HORIZONTAL_LINE: 'horizontal_line', DRAW_AGENT_TREND_LINE: 'trend_line',
        DRAW_AGENT_CHANNEL: 'channel', DRAW_AGENT_RECTANGLE: 'rectangle' };
    return (payload.chartCommands ?? []).filter((c) => kinds[c.type]).map((c) => {
        const d = { id: c.id, kind: kinds[c.type], origin: 'ai', name: c.label ?? '', color: c.color ?? 'info', interval: c.interval ?? payload.interval };
        if (c.type === 'DRAW_HORIZONTAL_LINE')
            d.price = c.price;
        else if (c.type === 'DRAW_AGENT_RECTANGLE')
            for (const key of ['start_time', 'end_time', 'lower_price', 'upper_price', 'show_fill'])
                d[key] = c[key];
        else {
            d.points = [c.from, c.to, ...(c.parallel ? [c.parallel] : [])];
            if (c.type === 'DRAW_AGENT_CHANNEL')
                d.show_midline = c.show_midline;
        }
        return d;
    });
}
