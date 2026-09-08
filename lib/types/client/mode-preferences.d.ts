export type DisplayMode = 'auto' | 'classic' | 'better-sidebar';
export declare const DISPLAY_MODE_KEY = "dsh-kline:display-mode:v1";
export declare const AUTO_OPEN_KEY = "dsh-kline:auto-open-after-analysis:v1";
export declare const UI_SEEN_KEY = "dsh-kline:ui-change-seen:v0.2.0";
export interface InterfaceState {
    preference: DisplayMode;
    mode: Exclude<DisplayMode, 'auto'>;
    available: boolean;
}
export declare const InterfaceContext: import("react").Context<InterfaceState>;
export declare function readDisplayMode(storage?: Storage): DisplayMode;
export declare function resolveDisplayMode(preference: DisplayMode, available: boolean): InterfaceState['mode'];
export declare function readAutoOpen(storage?: Storage): boolean;
