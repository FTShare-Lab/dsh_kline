export const KLINE_TAB_ID = 'ftshare-kline:chart';
export function isSidebarUsable(service) {
    return Boolean(service && typeof service.registerTab === 'function' && typeof service.openTab === 'function'
        && service.features?.includes('targetedOpen'));
}
// The framework persists open tabs across reloads. In Classic mode remove only
// our old tab shells, otherwise it displays a misleading "plugin unavailable"
// placeholder. Chart/workspace storage is separate and is never deleted here.
export function cleanClassicTabs(service) {
    if (!service.features?.includes('stateSubscription') || typeof service.closeTab !== 'function')
        return () => { };
    let stopped = false, pending = false;
    const schedule = () => {
        if (stopped || pending)
            return;
        pending = true;
        queueMicrotask(() => {
            pending = false;
            if (stopped)
                return;
            const { sessionId, state } = service.getSnapshot();
            if (!sessionId || !state)
                return;
            const ids = new Set();
            const visit = (node) => {
                if (node.kind === 'split')
                    node.children.forEach(visit);
                else
                    node.tabs.forEach(tab => { if (tab.type === KLINE_TAB_ID)
                        ids.add(tab.id); });
            };
            visit(state.splits);
            visit(state.bottomSplits);
            state.floats?.forEach(frame => { if (frame.tab.type === KLINE_TAB_ID)
                ids.add(frame.tab.id); });
            ids.forEach(id => service.closeTab(id, { sessionId }));
        });
    };
    const unsubscribe = service.subscribeState(schedule);
    schedule();
    return () => { stopped = true; unsubscribe(); };
}
