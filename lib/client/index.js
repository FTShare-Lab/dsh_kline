import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { ClassicShell } from './ClassicShell';
import { BetterSidebarBridge } from './BetterSidebarTab';
import { NativeSidebarBridgeView, registerNativeSidebar } from './native-sidebar';
import { cleanClassicTabs, isSidebarUsable } from './sidebar-integration';
import { InterfaceContext, readDisplayMode, resolveDisplayMode } from './mode-preferences';
import { captureOnboarding } from './ui-onboarding';
export const inject = ['sessions'];
export function apply(ctx) {
    let service;
    const listeners = new Set();
    const emit = () => listeners.forEach(listener => listener());
    const subscribe = (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
    const subscribeSessions = (listener) => ctx.sessions.list.subscribe(listener);
    const preference = readDisplayMode();
    captureOnboarding();
    // Registered before the router paints, so the first frame already knows
    // whether the host owns a right column this plugin can put a tab in.
    const native = registerNativeSidebar(ctx, emit);
    function Router() {
        const sidebar = useSyncExternalStore(subscribe, () => service);
        const nativeTab = useSyncExternalStore(subscribe, () => native.available());
        const conversation = useSyncExternalStore(subscribeSessions, () => ctx.sessions.list.getSnapshot().current);
        const available = nativeTab || isSidebarUsable(sidebar);
        const mode = resolveDisplayMode(preference, available);
        // A tab body lives in a Session, so before one exists the chart has no
        // tab to live in — whichever column the host owns. The classic launcher
        // covers that screen, which is what the old aria-label probe approximated
        // and only ever got right in an English UI.
        const showClassicLauncher = mode === 'classic' || conversation === undefined;
        return _jsxs(InterfaceContext.Provider, { value: { preference, mode, available }, children: [nativeTab && mode === 'better-sidebar' && _jsx(NativeSidebarBridgeView, { bridge: native, sessions: ctx.sessions }), !nativeTab && sidebar && _jsx(BetterSidebarBridge, { service: sidebar, sessions: ctx.sessions }), nativeTab && sidebar && _jsx(RetireBetterSidebarTabs, { service: sidebar }), showClassicLauncher && _jsx(ClassicShell, { sessions: ctx.sessions })] });
    }
    ctx.effect(() => {
        const host = document.createElement('div');
        host.dataset.dshKlineRouter = '';
        document.body.appendChild(host);
        const root = createRoot(host);
        root.render(_jsx(Router, {}));
        return () => { root.unmount(); host.remove(); listeners.clear(); };
    }, 'dsh-kline: interface router');
    // A separate dependency scope does not block the parent when absent.
    ctx.inject(['betterSidebar'], scoped => {
        scoped.effect(() => {
            service = scoped.get('betterSidebar');
            emit();
            return () => { service = undefined; emit(); };
        }, 'dsh-kline: optional sidebar');
    });
}
/**
 * Remove the tabs this plugin saved into Better Sidebar's workbench once the
 * native tab takes the same kind over. Better Sidebar draws a saved tab of an
 * unregistered type as "plugin not loaded", so an upgrade would otherwise
 * leave a broken-looking tab behind.
 */
function RetireBetterSidebarTabs({ service }) {
    useEffect(() => cleanClassicTabs(service), [service]);
    return null;
}
