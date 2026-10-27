import { jsx as _jsx } from "react/jsx-runtime";
import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { useChartReference } from './chart-session-resolver';
import { KlineTabContent } from './BetterSidebarTab';
import { currentConversationId } from './conversation';
import { InterfaceContext, readAutoOpen, readDisplayMode, resolveDisplayMode } from './mode-preferences';
import { registerNativeTab } from './native-sidebar-register';
/**
 * The chart as a tab of the host's own right column.
 *
 * The registration policy lives in `native-sidebar-register.ts`; this module
 * owns the two things that need React or the client context: the tab body and
 * the auto-open trigger. The body is the same chart the Better Sidebar tab
 * draws, mounted against the tab's own conversation.
 */
/**
 * One tab body: the chart of the tab's session.
 *
 * A registered tab can still be opened while the user chose Classic mode, or
 * remain mounted while the host changes Sessions. Only the active conversation
 * in Tab mode may publish a chart; otherwise show a harmless explanation.
 * When that conversation owns the tab, visibility is passed through so a
 * collapsed column does not discard the chart's viewport.
 */
export function NativeKlineTabBody({ sessionId, sessions, useTabInfo }) {
    const visible = useTabInfo().tab.visible;
    const preference = useMemo(readDisplayMode, []);
    const mode = resolveDisplayMode(preference, true);
    const subscribe = useCallback((listener) => sessions.list.subscribe(listener), [sessions]);
    const activeConversation = useSyncExternalStore(subscribe, () => currentConversationId(sessions.list.getSnapshot()));
    return (_jsx(InterfaceContext.Provider, { value: { preference, mode, available: true }, children: _jsx("div", { "data-dsh-kline-tab": "", style: { width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }, children: mode !== 'better-sidebar'
                ? _jsx("div", { role: "status", style: { padding: 16 }, children: "\u5F53\u524D\u4F7F\u7528\u7ECF\u5178 K \u7EBF\u4FA7\u680F\uFF1B\u8BF7\u5728\u56FE\u8868\u53F3\u4E0A\u89D2\u300CUI\u300D\u5207\u6362\u4E3A Tab \u6A21\u5F0F\u3002 / Switch to Tab mode in the chart UI." })
                : activeConversation !== sessionId
                    ? _jsx("div", { role: "status", style: { padding: 16 }, children: "\u8BF7\u5148\u6253\u5F00\u6B64 Tab \u6240\u5C5E\u7684\u5BF9\u8BDD\u3002 / Open the conversation that owns this tab." })
                    : _jsx(KlineTabContent, { sessions: sessions, conversationId: sessionId, visible: visible }, sessionId) }) }));
}
/** Reveal the chart tab when an analysis result lands in the conversation on screen. */
function NativeAutoOpen({ sessions, conversationId, bridge }) {
    const onNewChart = useCallback(() => {
        if (readAutoOpen())
            bridge.open();
    }, [bridge]);
    useChartReference(sessions, conversationId, onNewChart);
    return null;
}
/**
 * Auto-open lives in the tab's own session, exactly like the Better Sidebar
 * path; the router decides whether this path is the active interface.
 */
export function NativeSidebarBridgeView({ bridge, sessions }) {
    const subscribe = useCallback((listener) => sessions.list.subscribe(listener), [sessions]);
    const list = useSyncExternalStore(subscribe, () => sessions.list.getSnapshot());
    const activeConversation = currentConversationId(list);
    return activeConversation
        ? _jsx(NativeAutoOpen, { bridge: bridge, sessions: sessions, conversationId: activeConversation }, activeConversation)
        : null;
}
/**
 * Register the chart tab into the host's native right Sidebar.
 *
 * Every host service is optional: a host without `sidebarRightTabs`,
 * `sidebarRight` or `slots` keeps `available() === false` and the plugin's
 * existing interfaces untouched.
 * @param ctx - the client context to register on.
 * @param onChange - called whenever availability changes, so the router repaints.
 * @returns the handle the router and the auto-open path share.
 */
export function registerNativeSidebar(ctx, onChange) {
    let registration;
    const bridge = {
        available: () => registration?.available() ?? false,
        open: () => registration?.open(),
    };
    ctx.inject(['sidebarRightTabs', 'sidebarRight', 'slots'], scope => {
        scope.effect(() => {
            const tabs = scope.get('sidebarRightTabs');
            const navigation = scope.get('sidebarRight');
            const slots = scope.get('slots');
            if (tabs === undefined || navigation === undefined || slots === undefined)
                return () => { };
            const next = registerNativeTab({ tabs, navigation, slots }, {
                body: NativeKlineTabBody,
                bodyProps: (sessionId) => ({ sessions: ctx.sessions, sessionId }),
                onChange,
            });
            registration = next;
            onChange();
            return () => {
                registration = undefined;
                next.dispose();
                onChange();
            };
        }, 'dsh-kline: native right sidebar tab');
    });
    return bridge;
}
