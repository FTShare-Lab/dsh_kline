// Harness 0.1.2 moved rendered nodes out of SessionSnapshot. Consume the
// owning session's public event window, independent of Chat/Trajectory UI.
// Match results to invocation starts so a slow old call cannot steal the chart.
export function latestChartFromEvents(entries) {
    const calls = new Map();
    const nodes = [];
    for (const entry of entries) {
        if (entry.type !== 'event')
            continue;
        const event = entry.event;
        const data = event?.data;
        if (event?.type === 'tool/call' && typeof data?.callId === 'string') {
            calls.set(data.callId, { name: data.name, time: event.time });
        }
        else if (event?.type === 'tool/code-dispatch-start' && typeof data?.subCallId === 'string') {
            calls.set(data.subCallId, { name: data.name, time: event.time });
        }
    }
    for (const entry of entries) {
        if (entry.type !== 'event')
            continue;
        const event = entry.event;
        const data = event?.data;
        if (event?.type === 'tool/result') {
            for (const block of data?.message?.content ?? []) {
                if (block?.type !== 'tool-result')
                    continue;
                const call = calls.get(block.toolCallId);
                if (!call)
                    continue; // Never guess a truncated call's identity.
                nodes.push({ kind: 'tool-result', call, callTime: call.time, content: block.content, isError: block.isError || !!data.error });
            }
        }
        else if (event?.type === 'tool/code-dispatch') {
            const call = calls.get(data?.subCallId);
            if (!call || call.name !== data.name)
                continue;
            nodes.push({ kind: 'tool-result', call, callTime: call.time, content: data.content, isError: data.isError });
        }
    }
    return latestChart(nodes);
}
export function latestChart(nodes) {
    let latest;
    const visit = (node) => {
        for (const child of node.subCalls ?? [])
            visit(child);
        if (node.kind !== 'tool-result' || node.isError)
            return;
        if (!/^mcp__dsh[_-]kline__analyze_kline(?:_rows)?(?:_[a-f0-9]+)?$/.test(node.call?.name ?? ''))
            return;
        const serialized = JSON.stringify(node.content ?? []);
        const match = serialized.match(/chart_session(?:\\?"\s*:\s*\\?"|=)([A-Za-z0-9_-]{32})/);
        if (!match)
            return;
        const order = Number(node.callTime ?? node.time ?? node.seq ?? 0);
        if (!latest || order >= latest.order)
            latest = { session: match[1], order };
    };
    for (const node of nodes)
        visit(node);
    return latest;
}
export function chartStorageKey(conversationId) {
    return `dsh-kline:conversation:${encodeURIComponent(conversationId)}`;
}
