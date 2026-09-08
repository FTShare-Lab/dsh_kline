import { KLINE_TAB_ID } from "./sidebar-integration.js";
export const defaultTabKey = (sessionId) => `dsh-kline:default-tab:v1:${sessionId}`;
// Once per conversation, add an entry without expanding the panel or taking
// the user's active tab. A persisted receipt also respects later manual close.
export function installDefaultKlineTabs(service, storage) {
    if (!service.features?.includes('stateSubscription') || typeof service.getSnapshot !== 'function'
        || typeof service.subscribeState !== 'function' || typeof service.activateTab !== 'function'
        || typeof service.isTabEnabled !== 'function')
        return () => { };
    let stopped = false, pending = false;
    const handled = new Set();
    try {
        storage ??= globalThis.localStorage;
    }
    catch { /* In-memory fallback for blocked storage. */ }
    const schedule = () => {
        if (stopped || pending)
            return;
        pending = true;
        queueMicrotask(() => {
            pending = false;
            if (stopped)
                return;
            try {
                const { sessionId, state } = service.getSnapshot();
                if (!sessionId || !state || handled.has(sessionId) || !service.isTabEnabled(KLINE_TAB_ID))
                    return;
                const key = defaultTabKey(sessionId);
                try {
                    if (storage?.getItem(key) === '1') {
                        handled.add(sessionId);
                        return;
                    }
                }
                catch { }
                const nodes = [state.splits, state.bottomSplits];
                const seen = new Set();
                let exists = false, previous;
                while (nodes.length) {
                    const value = nodes.pop();
                    if (!value || typeof value !== 'object' || seen.has(value))
                        continue;
                    seen.add(value);
                    const node = value;
                    if (node.kind === 'split' && Array.isArray(node.children))
                        nodes.push(...node.children);
                    if (!Array.isArray(node.tabs))
                        continue;
                    exists ||= node.tabs.some((tab) => tab?.type === KLINE_TAB_ID);
                    if (node.id === state.activePane && node.tabs.some((tab) => tab?.id === node.active))
                        previous = node.active;
                }
                exists ||= Array.isArray(state.floats) && state.floats.some(frame => frame?.tab?.type === KLINE_TAB_ID);
                // Mark before notifying the host to avoid re-entrant duplicate opens.
                handled.add(sessionId);
                if (!exists) {
                    service.openTab({ type: KLINE_TAB_ID }, { sessionId });
                    // Public openTab activates the inserted tab. Restore the prior tab
                    // synchronously, before React paints, without touching panel geometry.
                    if (previous && service.getSnapshot().sessionId === sessionId)
                        service.activateTab(previous, { sessionId });
                }
                try {
                    storage?.setItem(key, '1');
                }
                catch { }
            }
            catch { /* Optional default entry must not block chart/plugin startup. */ }
        });
    };
    let unsubscribe;
    try {
        unsubscribe = service.subscribeState(schedule);
    }
    catch { }
    schedule();
    return () => { stopped = true; try {
        unsubscribe?.();
    }
    catch { } };
}
