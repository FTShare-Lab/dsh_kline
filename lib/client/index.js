import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { ClassicShell } from './ClassicShell';
import { BetterSidebarBridge } from './BetterSidebarTab';
import { isSidebarUsable, cleanClassicTabs } from './sidebar-integration';
import { InterfaceContext, readDisplayMode, resolveDisplayMode } from './mode-preferences';
import { captureOnboarding } from './ui-onboarding';
export const inject = ['sessions'];
export function apply(ctx) {
    let service;
    const listeners = new Set();
    const emit = () => listeners.forEach(listener => listener());
    const preference = readDisplayMode();
    captureOnboarding();
    function Router() {
        const sidebar = useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener); }; }, () => service);
        const available = isSidebarUsable(sidebar);
        const mode = resolveDisplayMode(preference, available);
        useEffect(() => {
            if (mode === 'classic' && sidebar)
                return cleanClassicTabs(sidebar);
        }, [mode, sidebar]);
        return _jsx(InterfaceContext.Provider, { value: { preference, mode, available }, children: mode === 'better-sidebar' && sidebar
                ? _jsx(BetterSidebarBridge, { service: sidebar, sessions: ctx.sessions })
                : _jsx(ClassicShell, { sessions: ctx.sessions }) });
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
