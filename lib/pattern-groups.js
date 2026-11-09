/** Bounded, atomic snapshots produced by the shared Python analyses. */
const HEX = /^[a-f0-9]{64}$/;
const COLORS = new Set(['info', 'warning', 'success', 'danger']);
const TYPES = new Set(['double_top', 'double_bottom', 'head_shoulders_top', 'head_shoulders_bottom', 'platform']);
const STATUSES = new Set(['candidate', 'pending_confirmation', 'price_confirmed', 'structurally_invalid', 'breakout_failed', 'expired']);
function time(value) {
    if (!Number.isSafeInteger(value) || value <= 0)
        throw Error('invalid_pattern_time');
    return value;
}
function price(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0)
        throw Error('invalid_pattern_price');
    return value;
}
function nonnegative(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
        throw Error('invalid_pattern_ratio');
    return value;
}
function label(value, limit) {
    if (typeof value !== 'string' || value.length > limit || /[\x00-\x1f]/.test(value))
        throw Error('invalid_pattern_label');
    return value;
}
export function patternGroupObservation(raw) {
    return { geometry_hash: raw.geometry_hash, bar_count: raw.bar_count, rule_version: raw.rule_version, as_of: raw.as_of };
}
export function sanitizePatternGroupCommand(raw, interval) {
    const pattern = raw?.type === 'DRAW_AGENT_PRICE_PATTERN';
    const nine = raw?.type === 'DRAW_AGENT_NINE_COUNT';
    if (!pattern && !nine || raw.interval !== interval || !COLORS.has(raw.color)
        || typeof raw.id !== 'string' || !new RegExp(`^${pattern ? 'pattern' : 'nine'}_[a-f0-9]{24}$`).test(raw.id)
        || !HEX.test(raw.geometry_hash) || raw.rule_version !== (pattern ? 'price_patterns_v1' : 'nine_count_v1')
        || !Number.isSafeInteger(raw.bar_count) || raw.bar_count < 0 || raw.bar_count > (pattern ? 5 : 240))
        throw Error('invalid_pattern_group');
    const result = { type: raw.type, id: raw.id, interval, label: label(raw.label ?? '', 48), color: raw.color,
        geometry_hash: raw.geometry_hash, bar_count: raw.bar_count, rule_version: raw.rule_version, as_of: time(raw.as_of) };
    if (raw.create_request_id !== undefined)
        result.create_request_id = label(raw.create_request_id, 160);
    if (pattern) {
        const p = raw.pattern;
        if (!p || !TYPES.has(p.type) || !STATUSES.has(p.status)
            || !Array.isArray(p.anchors) || p.anchors.length !== (p.type === 'platform' ? 0 : p.type.startsWith('double') ? 3 : 5)
            || raw.bar_count !== p.anchors.length || !Array.isArray(p.events) || p.events.length > 128
            || !['up', 'down', null].includes(p.direction) || !['up', 'down', null].includes(p.break_direction))
            throw Error('invalid_pattern_geometry');
        const anchors = p.anchors.map((a) => ({ index: a.index, side: a.side, time: time(a.time), price: price(a.price) }));
        if (anchors.some((a, i) => !Number.isSafeInteger(a.index) || a.index < 0 || !['high', 'low'].includes(a.side)
            || i > 0 && (a.index <= anchors[i - 1].index || a.time <= anchors[i - 1].time)))
            throw Error('invalid_pattern_anchors');
        const events = p.events.map((e) => ({ type: label(e.type, 40), time: time(e.time), index: e.index }));
        if (events.some((e) => !Number.isSafeInteger(e.index) || e.index < 0))
            throw Error('invalid_pattern_events');
        const geometry = { type: p.type, anchors, status: p.status, direction: p.direction, break_direction: p.break_direction,
            atr: price(p.atr), buffer: price(p.buffer), available_at: time(p.available_at), as_of: time(p.as_of),
            confirmed_at: p.confirmed_at == null ? null : time(p.confirmed_at), invalidated_at: p.invalidated_at == null ? null : time(p.invalidated_at),
            outer: p.outer == null ? undefined : price(p.outer), events,
            volume_evidence: p.volume_evidence?.status === 'known' ? { status: 'known', relative_to_preceding_20: nonnegative(p.volume_evidence.relative_to_preceding_20), unit: label(p.volume_evidence.unit, 16) } :
                { status: 'unknown', reason: label(p.volume_evidence?.reason ?? 'unavailable', 80) } };
        if (p.type === 'platform') {
            geometry.box = { start_time: time(p.box?.start_time), end_time: time(p.box?.end_time),
                lower_price: price(p.box?.lower_price), upper_price: price(p.box?.upper_price) };
            if (geometry.box.start_time >= geometry.box.end_time || geometry.box.lower_price >= geometry.box.upper_price)
                throw Error('invalid_pattern_box');
        }
        else if (p.neckline?.type === 'horizontal')
            geometry.neckline = { type: 'horizontal', price: price(p.neckline.price) };
        else if (p.neckline?.type === 'sloped')
            geometry.neckline = { type: 'sloped', from: { index: p.neckline.from?.index, time: time(p.neckline.from?.time), price: price(p.neckline.from?.price) },
                to: { index: p.neckline.to?.index, time: time(p.neckline.to?.time), price: price(p.neckline.to?.price) } };
        else
            throw Error('invalid_pattern_neckline');
        result.pattern = geometry;
    }
    else {
        if (!Array.isArray(raw.marks) || raw.marks.length > 240 || raw.bar_count !== raw.marks.length
            || !Array.isArray(raw.events) || raw.events.length > 30)
            throw Error('invalid_nine_group');
        result.marks = raw.marks.map((m) => ({ time: time(m.time), index: m.index, direction: m.direction, count: m.count,
            label: label(m.label, 2), price: price(m.price) }));
        if (result.marks.some((m, i) => !Number.isSafeInteger(m.index) || m.index < 0 || !['up', 'down'].includes(m.direction)
            || !Number.isSafeInteger(m.count) || m.count < 1 || m.count > 9 || m.label !== String(m.count)
            || i > 0 && m.time <= result.marks[i - 1].time))
            throw Error('invalid_nine_marks');
        result.events = raw.events.map((e) => ({ time: time(e.time), direction: e.direction, label: label(e.label, 20) }));
        if (result.events.some((e) => !['up', 'down'].includes(e.direction)))
            throw Error('invalid_nine_events');
    }
    return result;
}
