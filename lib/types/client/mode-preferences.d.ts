import type { KlineHostOptions } from './host-options.ts';
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
export declare function resolveDisplayMode(preference: DisplayMode, available: boolean, host?: KlineHostOptions): InterfaceState['mode'];
/**
 * Whether the floating classic launcher is drawn for this frame.
 *
 * Upstream keeps it for classic mode and for screens without a Session, where
 * the tab body cannot live yet. A host that declared `entry: 'tab'` owns the
 * chart entry instead, so it never draws the launcher.
 * @param host - the host options, if the host provided any.
 * @param mode - the interface mode this frame resolved to.
 * @param hasConversation - whether a Session exists to host a tab body.
 */
export declare function shouldDrawClassicLauncher(host: KlineHostOptions | undefined, mode: InterfaceState['mode'], hasConversation: boolean): boolean;
export declare function readAutoOpen(storage?: Storage): boolean;
