/** Canonical AI-owned text, numeric and icon annotations anchored to exact chart bars. */
export const CHART_ANNOTATION_ICONS = ['arrow_up', 'arrow_down', 'diamond'];
export function sanitizeChartAnnotation(raw) {
    if (raw?.type !== 'DRAW_AGENT_ANNOTATION' || !['text_annotation', 'number_annotation', 'icon_annotation'].includes(raw.kind)
        || typeof raw.id !== 'string' || !raw.id || raw.id.length > 128
        || !Number.isSafeInteger(raw.time) || raw.time <= 0 || typeof raw.price !== 'number' || !Number.isFinite(raw.price) || raw.price <= 0
        || !['info', 'warning', 'success', 'danger'].includes(raw.color ?? 'info')
        || typeof (raw.interval ?? 'day') !== 'string')
        throw Error('invalid_chart_annotation');
    const result = { type: raw.type, kind: raw.kind, id: raw.id, interval: raw.interval, label: raw.label ?? '', color: raw.color ?? 'info', time: raw.time, price: raw.price };
    if (typeof result.label !== 'string' || result.label.length > 48 || /[\x00-\x1f]/.test(result.label))
        throw Error('invalid_chart_annotation');
    if (raw.kind === 'text_annotation') {
        if (typeof raw.text !== 'string' || !raw.text.trim() || raw.text.trim().length > 120 || /[\x00-\x1f]/.test(raw.text))
            throw Error('invalid_chart_annotation');
        result.text = raw.text.trim();
    }
    else if (raw.kind === 'number_annotation') {
        if (typeof raw.value !== 'number' || !Number.isFinite(raw.value))
            throw Error('invalid_chart_annotation');
        result.value = raw.value;
    }
    else {
        if (!CHART_ANNOTATION_ICONS.includes(raw.icon))
            throw Error('invalid_chart_annotation');
        result.icon = raw.icon;
    }
    return result;
}
export function chartAnnotationText(command) {
    const clean = sanitizeChartAnnotation(command);
    return clean.kind === 'text_annotation' ? clean.text : clean.kind === 'number_annotation' ? String(clean.value) : clean.icon;
}
