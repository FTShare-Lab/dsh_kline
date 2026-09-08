import { jsx as _jsx } from "react/jsx-runtime";
import { useCallback, useContext, useEffect, useSyncExternalStore } from 'react';
import { useChartReference } from './chart-session-resolver';
import { NativeKlineApp, StandaloneKlineApp, standaloneWorkspaceScope } from './KlineContent';
import { InterfaceContext, readAutoOpen } from './mode-preferences';
import { KLINE_TAB_ID } from './sidebar-integration';
function KlineTabContent({ sessions, conversationId }) {
    const reference = useChartReference(sessions, conversationId);
    const onIdentity = useCallback(() => { }, []);
    return reference
        ? _jsx(NativeKlineApp, { session: { ok: true, ...reference, published_at: reference.order }, conversationId: conversationId, onIdentity: onIdentity }, reference.session)
        : _jsx(StandaloneKlineApp, { conversationId: standaloneWorkspaceScope(conversationId), onIdentity: onIdentity });
}
function AutoOpen({ service, sessions, conversationId }) {
    const onNewChart = useCallback(() => {
        if (readAutoOpen())
            service.openTab({ type: KLINE_TAB_ID }, { sessionId: conversationId });
    }, [service, conversationId]);
    useChartReference(sessions, conversationId, onNewChart);
    return null;
}
export function BetterSidebarBridge({ service, sessions }) {
    const interfaceState = useContext(InterfaceContext);
    const list = useSyncExternalStore(listener => sessions.list.subscribe(listener), () => sessions.list.getSnapshot());
    useEffect(() => service.registerTab({
        id: KLINE_TAB_ID,
        title: 'K线分析 / K-line',
        icon: _jsx("span", { "aria-hidden": "true", children: "K" }),
        order: 120,
        single: true,
        component: ({ scope, visible }) => (_jsx(InterfaceContext.Provider, { value: interfaceState, children: _jsx("div", { "data-dsh-kline-tab": "", style: { width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }, children: visible && scope.sessionId && _jsx(KlineTabContent, { conversationId: scope.sessionId, sessions: sessions }, scope.sessionId) }) })),
    }), [service, sessions, interfaceState]);
    return list.current ? _jsx(AutoOpen, { service: service, sessions: sessions, conversationId: list.current }, list.current) : null;
}
