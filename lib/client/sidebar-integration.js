export const KLINE_TAB_ID = 'ftshare-kline:chart';
export const KLINE_TAB_TITLE_ZH = 'FT K-Line · 非凸K线助手';
export const KLINE_TAB_TITLE_EN = 'FT K-Line · 非凸K线助手';
// The tab belongs to the host interface. Keep its product label separate from
// the internal package id, and follow the host/browser language.
export function klineTabTitle(locale = globalThis.navigator?.language ?? '') {
    return /^zh(?:-|$)/i.test(locale) ? KLINE_TAB_TITLE_ZH : KLINE_TAB_TITLE_EN;
}
export function migrateKlineTabTitle(service, tab, sessionId) {
    if (tab.type !== KLINE_TAB_ID || !['K线分析 / K-line', 'K线分析', '非凸K线助手 / dsh_kline', '非凸 K 线助手', 'FtAI K-Line', KLINE_TAB_TITLE_ZH, KLINE_TAB_TITLE_EN].includes(tab.title ?? '')
        || !service.features?.includes('updateTab') || !service.features?.includes('stateSubscription')
        || typeof service.updateTab !== 'function' || typeof service.getSnapshot !== 'function')
        return;
    try {
        // updateTab is current-session-only in the public API. Never mutate a
        // foreign floating tab or a user-customized title while migrating labels.
        if (sessionId && service.getSnapshot()?.sessionId === sessionId)
            service.updateTab(tab.id, { title: klineTabTitle() });
    }
    catch { /* Older/disposed integrations keep their saved title harmlessly. */ }
}
export function isSidebarUsable(service) {
    return Boolean(service && typeof service.registerTab === 'function' && typeof service.openTab === 'function'
        && service.features?.includes('targetedOpen'));
}
// The framework persists open tabs across reloads. In Classic mode remove only
// our old tab shells, otherwise it displays a misleading "plugin unavailable"
// placeholder. Chart/workspace storage is separate and is never deleted here.
export function cleanClassicTabs(service) {
    if (!service.features?.includes('stateSubscription') || typeof service.closeTab !== 'function'
        || typeof service.getSnapshot !== 'function' || typeof service.subscribeState !== 'function')
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
            try {
                const snapshot = service.getSnapshot();
                const { sessionId, state } = snapshot ?? {};
                if (typeof sessionId !== 'string' || !sessionId || !state)
                    return;
                const ids = new Set();
                const record = (value) => typeof value === 'object' && value !== null;
                const collect = (tab) => {
                    if (record(tab) && tab.type === KLINE_TAB_ID && typeof tab.id === 'string' && tab.id)
                        ids.add(tab.id);
                };
                // Layouts belong to another plugin and may contain older/incomplete
                // nodes. Iterate defensively, including protection against cycles.
                // Since Better Sidebar 0.19, DSH owns the right-sidebar layout.
                // Our registered tab can only be in Better Sidebar's workbench.
                const pendingNodes = [state.bottomSplits];
                const seen = new Set();
                while (pendingNodes.length) {
                    const node = pendingNodes.pop();
                    if (!record(node) || seen.has(node))
                        continue;
                    seen.add(node);
                    if (node.kind === 'split' && Array.isArray(node.children))
                        pendingNodes.push(...[...node.children].reverse());
                    else if (Array.isArray(node.tabs))
                        node.tabs.forEach(collect);
                }
                for (const id of ids) {
                    try {
                        service.closeTab(id, { sessionId });
                    }
                    catch { /* A stale tab must not block the remaining cleanup. */ }
                }
            }
            catch { /* Optional layout cleanup must never break the classic shell. */ }
        });
    };
    let unsubscribe;
    try {
        unsubscribe = service.subscribeState(schedule);
    }
    catch { /* Still attempt one initial cleanup. */ }
    schedule();
    return () => { stopped = true; try {
        unsubscribe?.();
    }
    catch { /* Service may already have been disposed. */ } };
}
