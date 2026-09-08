import { UI_SEEN_KEY } from "./mode-preferences.js";
export const ONBOARDING_KEY = 'dsh-kline:onboarding-version:v2';
let existingUser;
export function hasPreviousUsage(storage) {
    try {
        if (storage.getItem('dsh_kline_welcome_seen_v1') === '1')
            return true;
        for (let i = 0; i < storage.length; i++) {
            const key = storage.key(i) || '';
            if (key.startsWith('dsh-kline:conversation:') || key === 'dsh-kline.workspace.v1')
                return true;
        }
    }
    catch { }
    return false;
}
// Capture before the launcher writes any new conversation data.
export function captureOnboarding(storage = globalThis.localStorage) {
    existingUser ??= hasPreviousUsage(storage);
}
export function onboardingKind(storage = globalThis.localStorage) {
    captureOnboarding(storage);
    return classifyOnboarding(storage, existingUser === true);
}
export function classifyOnboarding(storage, previousUsage) {
    try {
        if (storage.getItem(UI_SEEN_KEY))
            return 'none';
        return previousUsage ? 'upgrade' : 'first';
    }
    catch {
        return 'none';
    }
}
export function acknowledgeOnboarding(storage = globalThis.localStorage) {
    try {
        storage.setItem(UI_SEEN_KEY, '1');
        storage.setItem(ONBOARDING_KEY, '0.2.0');
        storage.setItem('dsh_kline_welcome_seen_v1', '1');
    }
    catch { }
}
