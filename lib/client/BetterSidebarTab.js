import { jsx as _jsx } from "react/jsx-runtime";
import { useCallback, useContext, useEffect, useState, useSyncExternalStore } from 'react';
import { currentConversationId } from './conversation';
import { useChartReference } from './chart-session-resolver';
import { NativeKlineApp, StandaloneKlineApp, standaloneWorkspaceScope } from './KlineContent';
import { InterfaceContext, readAutoOpen } from './mode-preferences';
import { KLINE_TAB_ID, klineTabTitle, migrateKlineTabTitle } from './sidebar-integration';
import { installDefaultKlineTabs } from './default-tab';
/** The chart itself, shared by every host tab: Better Sidebar and the native one. */
export function KlineTabContent({ sessions, conversationId, visible = true }) {
    // Better Sidebar preserves a tab and its previous scope on the host's
    // New Session screen. Never promote an already-present chart from that
    // scope: only an analysis result that arrives while this view is live may
    // open a chart. This makes the Market page a deterministic new-session
    // landing page even on hosts that retain a stale session id.
    const [liveReference, setLiveReference] = useState();
    const onNewChart = useCallback((reference) => {
        setLiveReference(reference);
    }, []);
    const reference = useChartReference(sessions, conversationId, onNewChart);
    const selectedReference = liveReference ?? (reference?.recovery ? reference : undefined);
    const onIdentity = useCallback(() => { }, []);
    return selectedReference
        ? _jsx(NativeKlineApp, { session: { ok: true, ...selectedReference, published_at: selectedReference.order }, conversationId: conversationId ?? '', ownerConversationId: conversationId, visible: visible, onIdentity: onIdentity }, selectedReference.session)
        : _jsx(StandaloneKlineApp, { conversationId: standaloneWorkspaceScope(conversationId), ownerConversationId: conversationId, visible: visible, onIdentity: onIdentity });
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
    const interfaceState = useContext(InterfaceContext);
    const sidebar = useSyncExternalStore(listener => service.subscribeState(listener), () => service.getSnapshot());
    // A single-instance Better Sidebar tab retains its last scope during the
    // host's "New Session" screen.  The public sidebar snapshot deliberately
    // has no active session there, so it is the authoritative signal: start the
    // Market launcher until a real conversation becomes active.
    const conversationId = sidebar.sessionId === scope.sessionId ? scope.sessionId : undefined;
    useEffect(() => migrateKlineTabTitle(service, tab, scope.sessionId), [service, tab.id, tab.title, scope.sessionId]);
    return (_jsx("div", { "data-dsh-kline-tab": "", style: { width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }, children: visible && interfaceState.mode === 'better-sidebar'
            ? _jsx(KlineTabContent, { conversationId: conversationId, sessions: sessions }, conversationId ?? 'launcher')
            : visible && _jsx("div", { role: "status", style: { padding: 16 }, children: "\u5F53\u524D\u4F7F\u7528\u7ECF\u5178 K \u7EBF\u4FA7\u680F\uFF1B\u5982\u9700\u5728\u6B64\u5904\u6253\u5F00\u56FE\u8868\uFF0C\u8BF7\u5728\u7ECF\u5178\u4FA7\u680F\u53F3\u4E0A\u89D2\u300CUI\u300D\u5207\u6362\u4E3A\u539F\u751F Tab\u3002" }) }));
}
export function BetterSidebarBridge({ service, sessions }) {
    const interfaceState = useContext(InterfaceContext);
    const list = useSyncExternalStore(listener => sessions.list.subscribe(listener), () => sessions.list.getSnapshot());
    const activeConversation = currentConversationId(list);
    const isNativeTabMode = interfaceState.mode === 'better-sidebar';
    useEffect(() => {
        const dispose = service.registerTab({
            id: KLINE_TAB_ID,
            title: klineTabTitle(),
            order: 120,
            single: true,
            component: (props) => (_jsx(InterfaceContext.Provider, { value: interfaceState, children: _jsx(KlineTabFrame, { ...props, service: service, sessions: sessions }) })),
        });
        // The tab is always registered so Classic mode retains a discoverable
        // native entry. Only the explicitly chosen native-tab mode may insert or
        // auto-open it for the user.
        const stopDefaults = isNativeTabMode ? installDefaultKlineTabs(service) : () => { };
        return () => { stopDefaults(); dispose(); };
    }, [service, sessions, interfaceState, isNativeTabMode]);
    return isNativeTabMode && activeConversation
        ? _jsx(AutoOpen, { service: service, sessions: sessions, conversationId: activeConversation }, activeConversation)
        : null;
}
