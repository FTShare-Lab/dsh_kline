import { currentConversationId, latestChartFromEvents } from "./conversation.js";
/** Distinguish live appends from history hydration using the host's delta. */
export function observeLiveCharts(initial) {
    let revision = initial.revision;
    let previous = latestChartFromEvents(initial.entries);
    return (window) => {
        if (typeof window.revision !== 'number' || !window.change || window.revision === revision)
            return;
        revision = window.revision;
        const next = latestChartFromEvents(window.entries);
        const changed = next && (next.session !== previous?.session || next.order !== previous?.order);
        previous = next;
        return window.change.kind === 'append' && changed ? next : undefined;
    };
}
// A newly opened tab mounts after its triggering tool result. Share that live
// result within this host instance, scoped to its owning conversation. Unlike
// browser persistence, this cannot promote an old chart after a page reload.
const liveCharts = new WeakMap();
export function handoffLiveChart(sessions, conversationId, reference) {
    if (currentConversationId(sessions.list.getSnapshot()) !== conversationId)
        return;
    let charts = liveCharts.get(sessions);
    if (!charts)
        liveCharts.set(sessions, charts = new Map());
    const previous = charts.get(conversationId);
    if (!previous || reference.order >= previous.order)
        charts.set(conversationId, reference);
}
export function liveChartFor(sessions, conversationId) {
    if (!conversationId || currentConversationId(sessions.list.getSnapshot()) !== conversationId)
        return;
    return liveCharts.get(sessions)?.get(conversationId);
}
