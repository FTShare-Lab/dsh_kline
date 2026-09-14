import { createContext } from 'react';
export const DISPLAY_MODE_KEY = 'dsh-kline:display-mode:v1';
export const AUTO_OPEN_KEY = 'dsh-kline:auto-open-after-analysis:v1';
export const UI_SEEN_KEY = 'dsh-kline:ui-change-seen:v0.2.0';
export const InterfaceContext = createContext({ preference: 'classic', mode: 'classic', available: false });
export function readDisplayMode(storage = globalThis.localStorage) {
    try {
        const value = storage.getItem(DISPLAY_MODE_KEY);
        return value === 'better-sidebar' ? value : 'classic';
    }
    catch {
        return 'classic';
    }
}
export function resolveDisplayMode(preference, available) {
    // A chart should be available before a new DSH conversation has created a
    // workbench session. The native tab is therefore opt-in; the classic K
    // launcher remains the dependable default.
    return preference === 'better-sidebar' && available ? 'better-sidebar' : 'classic';
}
export function readAutoOpen(storage = globalThis.localStorage) {
    try {
        return storage.getItem(AUTO_OPEN_KEY) !== 'false';
    }
    catch {
        return true;
    }
}
