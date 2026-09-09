import { jsx as _jsx } from "react/jsx-runtime";
import { useCallback, useContext, useEffect, useState, useSyncExternalStore } from 'react';
import { useChartReference } from './chart-session-resolver';
import { NativeKlineApp, StandaloneKlineApp, standaloneWorkspaceScope } from './KlineContent';
import { InterfaceContext, readAutoOpen } from './mode-preferences';
import { KLINE_TAB_ID, KLINE_TAB_TITLE, migrateKlineTabTitle } from './sidebar-integration';
import { installDefaultKlineTabs } from './default-tab';
function KlineTabContent({ sessions, conversationId }) {
    // Better Sidebar preserves a tab and its previous scope on the host's
    // New Session screen. Never promote an already-present chart from that
    // scope: only an analysis result that arrives while this view is live may
    // open a chart. This makes the Market page a deterministic new-session
    // landing page even on hosts that retain a stale session id.
    const [liveReference, setLiveReference] = useState();
    const onNewChart = useCallback((reference) => {
        setLiveReference(reference);
    }, []);
    useChartReference(sessions, conversationId, onNewChart);
    const onIdentity = useCallback(() => { }, []);
    return liveReference
        ? _jsx(NativeKlineApp, { session: { ok: true, ...liveReference, published_at: liveReference.order }, conversationId: conversationId ?? '', onIdentity: onIdentity }, liveReference.session)
        : _jsx(StandaloneKlineApp, { conversationId: standaloneWorkspaceScope(conversationId), onIdentity: onIdentity });
}
function AutoOpen({ service, sessions, conversationId }) {
    const onNewChart = useCallback((reference) => {
        if (readAutoOpen())
            service.openTab({ type: KLINE_TAB_ID }, { sessionId: conversationId });
    }, [service, conversationId]);
    useChartReference(sessions, conversationId, onNewChart);
    return null;
}
function KlineTabFrame({ service, sessions, scope, tab, visible }) {
    const sidebar = useSyncExternalStore(listener => service.subscribeState(listener), () => service.getSnapshot());
    // A single-instance Better Sidebar tab retains its last scope during the
    // host's "New Session" screen.  The public sidebar snapshot deliberately
    // has no active session there, so it is the authoritative signal: start the
    // Market launcher until a real conversation becomes active.
    const conversationId = sidebar.sessionId === scope.sessionId ? scope.sessionId : undefined;
    useEffect(() => migrateKlineTabTitle(service, tab, scope.sessionId), [service, tab.id, tab.title, scope.sessionId]);
    return (_jsx("div", { "data-dsh-kline-tab": "", style: { width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }, children: visible && _jsx(KlineTabContent, { conversationId: conversationId, sessions: sessions }, conversationId ?? 'launcher') }));
}
export function BetterSidebarBridge({ service, sessions }) {
    const interfaceState = useContext(InterfaceContext);
    const list = useSyncExternalStore(listener => sessions.list.subscribe(listener), () => sessions.list.getSnapshot());
    useEffect(() => {
        const dispose = service.registerTab({
            id: KLINE_TAB_ID,
            title: KLINE_TAB_TITLE,
            order: 120,
            single: true,
            component: (props) => (_jsx(InterfaceContext.Provider, { value: interfaceState, children: _jsx(KlineTabFrame, { ...props, service: service, sessions: sessions }) })),
        });
        const stopDefaults = installDefaultKlineTabs(service);
        return () => { stopDefaults(); dispose(); };
    }, [service, sessions, interfaceState]);
    return list.current ? _jsx(AutoOpen, { service: service, sessions: sessions, conversationId: list.current }, list.current) : null;
}
