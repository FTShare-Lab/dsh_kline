/** Browser-input snapshots. A handoff changes only source identity, never the chart. */
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { drawingInventory, observationKey, sanitizeChartContext, text } from "./chart-observation.js";
import { sourceStatus } from "./chart-source-status.js";
import { normalizeAdjustment } from "./chart-adjustment.js";
const TOKEN = /^[A-Za-z0-9_-]{32}$/;
const AI = new Set(['DRAW_HORIZONTAL_LINE', 'DRAW_AGENT_TREND_LINE', 'DRAW_AGENT_CHANNEL', 'DRAW_AGENT_RECTANGLE']);
const INTERVALS = ['minute', 'day', 'week', 'month', 'quarter', 'year'];
function finite(value, positive = false) {
    if (typeof value !== 'number' || !Number.isFinite(value) || positive && value <= 0)
        throw Error('invalid_source_number');
    return value;
}
function point(raw) {
    if (!Number.isSafeInteger(raw?.time) || raw.time <= 0)
        throw Error('invalid_source_point');
    return { time: raw.time, price: finite(raw.price, true) };
}
function color(raw) {
    if (!['info', 'warning', 'success', 'danger'].includes(raw))
        throw Error('invalid_source_color');
    return raw;
}
function canonicalAI(state) {
    return observationKey({ ...state, drawings: state.drawings.filter((d) => d.origin === 'ai') });
}
function sourceKey(state) {
    // A source can have fewer candles than the new view. Its data key must
    // not validate that new view's viewport indices against the old row count.
    const s = sanitizeChartContext({ ...state, visible_range: { available: false }, selection: null });
    s.adjust = normalizeAdjustment(s.adjust) ?? s.adjust;
    return observationKey({ ...s, name: '', range_key: '', source_interval: '', ui_interval: '', display_volume_unit: '', active_page: '',
        source_chart_session: null, visible_range: { available: false }, selection: null, selection_status: 'none', indicators: [], data_status: '',
        data_provenance: null, drawings: s.drawings.filter((d) => d.origin === 'ai') });
}
/** Keep only renderer fields; never copy arbitrary metadata, URLs or provider secrets. */
export function sanitizeSourcePayload(raw, state) {
    if (raw?.symbol !== state.symbol || raw?.interval !== state.interval || normalizeAdjustment(raw?.adjust) === null
        || normalizeAdjustment(raw?.adjust) !== normalizeAdjustment(state.adjust)
        || !Array.isArray(raw.chartCommands) || raw.chartCommands.length > 256)
        throw Error('source_payload_mismatch');
    let candleCount = 0;
    const commands = raw.chartCommands.map((c) => {
        const type = c.type;
        if (type === 'SET_CANDLES') {
            candleCount++;
            const cleaned = sanitizeChartContext({ ...state, candles: c.rows });
            if (JSON.stringify(cleaned.candles) !== JSON.stringify(state.candles))
                throw Error('source_rows_mismatch');
            return { type, rows: cleaned.candles };
        }
        if (type === 'SET_RANGE')
            return { type, start: finite(c.start, true), end: finite(c.end, true) };
        if (type === 'SET_INDICATOR_SERIES') {
            if (!['ma', 'vwap', 'vol', 'macd', 'kdj', 'boll', 'rsi', 'atr'].includes(c.name)
                || !['candle', 'vol', 'macd', 'kdj', 'rsi', 'atr'].includes(c.pane)
                || !c.data || typeof c.data !== 'object' || Array.isArray(c.data) || Object.keys(c.data).length > 32)
                throw Error('invalid_source_indicator');
            const params = {};
            for (const key of ['period', 'ma_period', 'fast', 'slow', 'signal', 'n', 'm1', 'm2', 'std_mult'])
                if (c.params?.[key] != null)
                    params[key] = finite(c.params[key], true);
            if (c.params?.periods) {
                if (!Array.isArray(c.params.periods) || c.params.periods.length > 8)
                    throw Error('invalid_source_indicator');
                params.periods = c.params.periods.map((p) => finite(p, true));
            }
            if (c.params?.anchor === 'loaded_context')
                params.anchor = 'loaded_context';
            const data = {};
            for (const [key, values] of Object.entries(c.data)) {
                if (!/^(?:ma\d{1,3}|vwap|vol_ma|dif|dea|hist|k|d|j|mid|upper|lower|rsi|atr)$/.test(key)
                    || !values || typeof values !== 'object' || Array.isArray(values) || Object.keys(values).length > 12000)
                    throw Error('invalid_source_indicator');
                data[key] = Object.fromEntries(Object.entries(values).map(([time, value]) => {
                    if (!/^[1-9]\d{0,12}$/.test(time))
                        throw Error('invalid_source_indicator_time');
                    return [time, finite(value)];
                }));
            }
            return { type, name: c.name, pane: c.pane, params, data };
        }
        if (type === 'SET_COMPARISON_SERIES') {
            if (!Array.isArray(c.series) || c.series.length > 3)
                throw Error('invalid_source_comparison');
            return { type, series: c.series.map((s) => ({ symbol: text(s.symbol, 64), name: text(s.name ?? '', 128),
                    rows: sanitizeChartContext({ ...state, candles: s.rows }).candles })) };
        }
        if (type === 'TEXT_MARKER')
            return { type, id: text(c.id ?? '', 256), text: text(c.text ?? '', 256), ...point(c), color: color(c.color ?? 'info') };
        if (type === 'DRAW_TREND_LINE')
            return { type, id: text(c.id ?? '', 256), label: text(c.label ?? '', 128),
                from: point(c.from), to: point(c.to), color: color(c.color ?? 'info') };
        if (!AI.has(type))
            throw Error('unsupported_source_command');
        const result = { type, id: text(c.id, 256), label: text(c.label ?? '', 48), color: color(c.color ?? 'info') };
        if (c.interval != null) {
            if (!INTERVALS.includes(c.interval))
                throw Error('invalid_source_interval');
            result.interval = c.interval;
        }
        if (type === 'DRAW_HORIZONTAL_LINE')
            result.price = finite(c.price, true);
        else if (type === 'DRAW_AGENT_RECTANGLE') {
            result.start_time = point({ time: c.start_time, price: c.lower_price }).time;
            result.end_time = point({ time: c.end_time, price: c.upper_price }).time;
            result.lower_price = finite(c.lower_price, true);
            result.upper_price = finite(c.upper_price, true);
            if (typeof c.show_fill !== 'boolean')
                throw Error('invalid_source_style');
            result.show_fill = c.show_fill;
        }
        else {
            result.from = point(c.from);
            result.to = point(c.to);
            if (type === 'DRAW_AGENT_CHANNEL') {
                result.parallel = point(c.parallel);
                for (const edge of ['upper', 'lower'])
                    result[edge] = { from: point(c[edge]?.from), to: point(c[edge]?.to) };
                for (const key of ['width', 'signed_offset', 'slope_per_bar'])
                    result[key] = finite(c[key], key === 'width');
                if (typeof c.show_midline !== 'boolean' || !['ascending', 'descending', 'horizontal'].includes(c.direction)
                    || c.geometry_basis !== 'candle_index_linear_price')
                    throw Error('invalid_source_channel');
                Object.assign(result, { show_midline: c.show_midline, direction: c.direction, geometry_basis: c.geometry_basis });
            }
        }
        return result;
    });
    if (candleCount !== 1)
        throw Error('invalid_source_candles');
    const meta = { source: state.data_provenance.provider, status: state.data_status };
    const zone = state.data_provenance.aggregation?.timezone ?? raw.data_meta?.exchange_timezone;
    if (typeof zone === 'string' && zone.length <= 64 && /^[A-Za-z_+-]+(?:\/[A-Za-z0-9_+-]+){0,2}$/.test(zone)) {
        try {
            new Intl.DateTimeFormat('en', { timeZone: zone });
            meta.exchange_timezone = zone;
        }
        catch { }
    }
    if (typeof raw.data_meta?.updated_at === 'number' && Number.isFinite(raw.data_meta.updated_at) && raw.data_meta.updated_at > 0)
        meta.updated_at = raw.data_meta.updated_at;
    const payload = { symbol: state.symbol, name: state.name, interval: state.interval, interval_value: state.interval_value,
        adjust: state.adjust, range_key: state.range_key, count: state.candles.length, indicators: state.indicators,
        indicators_explicit: true, data_meta: meta, chartCommands: commands };
    if (canonicalAI({ ...state, drawings: drawingInventory(payload) }) !== canonicalAI(state))
        throw Error('source_inventory_mismatch');
    return payload;
}
export class ChartSources {
    offers = new Map();
    runtime;
    now;
    constructor(runtime, now = () => Date.now()) { this.runtime = runtime; this.now = now; }
    proofPath(ref, token) {
        if (!TOKEN.test(ref) || !TOKEN.test(token))
            throw Error('invalid_source_identity');
        return join(this.runtime, 'sources', String(process.pid), ref, token + '.json');
    }
    async read(path) {
        const data = await readFile(path, 'utf8');
        if (data.length > 8 * 1024 * 1024)
            throw Error('invalid_source_size');
        return JSON.parse(data);
    }
    async write(path, value) {
        await mkdir(join(path, '..'), { recursive: true, mode: 0o700 });
        const tmp = path + '.' + randomBytes(8).toString('hex') + '.tmp';
        await writeFile(tmp, JSON.stringify(value), { mode: 0o600, flag: 'wx' });
        await rename(tmp, path);
    }
    async acknowledge(view, receipt) {
        const offer = this.offers.get(view.ref);
        if (!TOKEN.test(receipt?.chart_session ?? '') || !['bound', 'rejected'].includes(receipt.status))
            throw Error('invalid_source_receipt');
        // A view can expire/remount while a receipt is in flight. Reject and let
        // that browser restore its prior identity; never leave publication stuck.
        if (!offer || receipt.chart_session !== offer.chart_session)
            return { chart_session: receipt.chart_session, status: 'rejected' };
        if (view.conversation !== offer.conversation_id || view.view !== offer.view_id)
            return { chart_session: offer.chart_session, status: 'rejected' };
        if (offer.status !== 'offered')
            return { chart_session: offer.chart_session, status: offer.status };
        const expected = { ...offer.base_state, source_chart_session: offer.chart_session };
        offer.status = receipt.status === 'bound' && view.active && !view.ambiguous && this.now() <= offer.expires_at_ms
            && view.conversation === offer.conversation_id && view.view === offer.view_id
            && observationKey(view.state) === observationKey(expected) ? 'confirmed' : 'rejected';
        await this.write(this.proofPath(view.ref, offer.chart_session), { host_process_id: process.pid, context_ref: view.ref,
            conversation_id: offer.conversation_id, view_id: offer.view_id, chart_session: offer.chart_session, status: offer.status,
            acknowledged_at_ms: this.now() });
        return { chart_session: offer.chart_session, status: offer.status };
    }
    async offer(view, raw) {
        return (await this.assess(view, raw)).handoff;
    }
    async assess(view, raw) {
        const result = (reason, handoff) => ({ status: sourceStatus(reason), handoff });
        for (const [ref, item] of this.offers)
            if (this.now() > item.expires_at_ms + 300000)
                this.offers.delete(ref);
        if (!view.active)
            return result('view_inactive');
        if (view.ambiguous)
            return result('ambiguous_views');
        if (!view.applyCapable)
            return result('client_unsupported');
        if (view.state.state !== 'ready' || !view.state.candles.length || !view.state.symbol)
            return result('chart_not_ready');
        if (view.state.candles.length > 4000)
            return result('source_limit_exceeded');
        if (!INTERVALS.includes(view.state.interval) || normalizeAdjustment(view.state.adjust) === null
            || view.state.interval === 'minute' && view.state.interval_value === null)
            return result('source_metadata_unknown');
        // A pending drawing must finish or fail explicitly before its source can change.
        let pending;
        try {
            pending = await this.read(join(this.runtime, 'edits', String(process.pid), view.ref, 'pending.json'));
        }
        catch (error) {
            if (error?.code !== 'ENOENT')
                throw error;
        }
        if (pending) {
            if (!TOKEN.test(pending.candidate_chart_session ?? ''))
                return result('drawing_outcome_unknown');
            let app;
            try {
                app = await this.read(join(this.runtime, 'edits', String(process.pid), view.ref, 'applications', pending.candidate_chart_session + '.json'));
            }
            catch {
                return result('drawing_outcome_unknown');
            }
            if (!['applied', 'rejected', 'failed'].includes(app.status))
                return result(['queued', 'delivered'].includes(app.status) ? 'drawing_pending' : 'drawing_outcome_unknown');
        }
        const parent = view.state.source_chart_session;
        if (!TOKEN.test(parent ?? ''))
            return result('source_missing');
        const saved = await this.read(join(this.runtime, 'sessions', parent + '.json'));
        if (saved.host_process_id !== process.pid || saved.session !== parent || saved.ok !== true)
            throw Error('source_parent_unavailable');
        const source = saved.payload;
        if (source.drawing_guard) {
            const g = source.drawing_guard;
            const app = await this.read(join(this.runtime, 'edits', String(process.pid), g.context_ref, 'applications', parent + '.json'));
            if (app.status !== 'applied' || app.confirmed_chart_session !== parent || app.conversation_id !== view.conversation
                || app.host_process_id !== process.pid || app.view_id !== g.view_id || app.request_id !== g.request_id
                || g.conversation_id !== view.conversation)
                throw Error('unconfirmed_source_parent');
        }
        if (source.view_source_guard) {
            const g = source.view_source_guard, proof = await this.read(this.proofPath(g.context_ref, parent));
            if (proof.status !== 'confirmed' || proof.conversation_id !== view.conversation || proof.host_process_id !== process.pid
                || proof.chart_session !== parent || g.chart_session !== parent || proof.view_id !== g.view_id
                || g.conversation_id !== view.conversation)
                throw Error('unconfirmed_source_parent');
        }
        const rows = source.chartCommands?.find((c) => c.type === 'SET_CANDLES')?.rows;
        if (source.symbol === view.state.symbol && Array.isArray(rows)) {
            const original = { ...view.state, symbol: source.symbol, interval: source.interval, interval_value: source.interval_value ?? null,
                adjust: source.adjust ?? '', candles: rows, drawings: drawingInventory(source) };
            if (sourceKey(original) === sourceKey(view.state))
                return result('source_matches_view');
        }
        const previous = this.offers.get(view.ref);
        if (previous?.status === 'offered' && observationKey(previous.base_state) === observationKey(view.state)
            && this.now() <= previous.expires_at_ms)
            return result('source_handoff_pending', previous);
        if (!raw)
            return result('source_snapshot_mismatch');
        const payload = sanitizeSourcePayload(raw, view.state), token = randomBytes(24).toString('base64url');
        const ai = payload.chartCommands.filter((c) => AI.has(c.type));
        const old = source.symbol === view.state.symbol ? source.chartCommands.filter((c) => AI.has(c.type)) : [];
        if (ai.length !== old.length || new Set(ai.map((c) => c.id)).size !== ai.length)
            throw Error('source_inventory_mismatch');
        // The handoff may change rows/period, never existing AI definitions or geometry.
        const ordered = (x) => Array.isArray(x) ? x.map(ordered) : x && typeof x === 'object'
            ? Object.fromEntries(Object.keys(x).sort().map(k => [k, ordered(x[k])])) : x;
        for (const c of ai) {
            const parent = old.find((p) => p.id === c.id && p.type === c.type);
            if (!parent || !c.id || Object.keys(c).some(k => JSON.stringify(ordered(c[k])) !== JSON.stringify(ordered(parent[k]))))
                throw Error('source_ai_changed');
        }
        payload.view_source_guard = { protocol: 'browser-source-v1', context_ref: view.ref, conversation_id: view.conversation,
            view_id: view.view, expected_revision: view.revision, chart_session: token };
        payload.drawing_parent_session = parent;
        await this.write(join(this.runtime, 'sessions', token + '.json'), { ok: true, session: token, host_process_id: process.pid,
            symbol: payload.symbol, name: payload.name, published_at: Math.floor(this.now() / 1000), payload });
        const offer = { chart_session: token, context_ref: view.ref, conversation_id: view.conversation, view_id: view.view,
            expected_revision: view.revision, base_state: view.state, expires_at_ms: this.now() + 30000, status: 'offered' };
        await this.write(this.proofPath(view.ref, token), { host_process_id: process.pid, context_ref: view.ref,
            conversation_id: view.conversation, view_id: view.view, chart_session: token, status: 'offered' });
        this.offers.set(view.ref, offer);
        return result('source_handoff_pending', offer);
    }
}
