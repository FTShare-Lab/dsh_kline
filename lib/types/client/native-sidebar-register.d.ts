import type { SidebarRightService, SidebarRightTabsService, SlotsService } from './native-sidebar-services';
/**
 * The native right-Sidebar registration, without React and without a host
 * context: a pure function over the three host services, so the bootstrap
 * policy (both stages, their teardown order, the deferred body seat) is
 * testable with fakes.
 *
 * A DSH host that owns its right column publishes `sidebarRightTabs` (stage
 * one — what the tab type is) and a keyed `sidebar.right.pane.tab` seat
 * (stage two — the body), navigated by `sidebarRight`. A type without a body
 * makes the host draw "nothing can view this", so the two stages are one unit
 * and any failure backs the type out again.
 */
/** The seat a tab type's body registers under. */
export declare const BODY_SEAT = "sidebar.right.pane.tab";
/** The host services registration needs, all of them already resolved. */
export interface NativeTabHost {
    readonly tabs: SidebarRightTabsService;
    readonly navigation: SidebarRightService;
    readonly slots: SlotsService;
}
/** What to register, and how the caller wants to hear about it. */
export interface NativeTabOptions {
    /** The body component registered into the keyed seat. */
    readonly body: unknown;
    /** Business props the body receives; the framework adds its own standard share. */
    readonly bodyProps?: (sessionId: string) => Record<string, unknown>;
    /** Called whenever `available()` changes. */
    readonly onChange?: () => void;
}
/** A live native tab: what the router asks, and how the auto-open path opens it. */
export interface NativeTabRegistration {
    /** Both stages are in place: the tab can actually draw. */
    available(): boolean;
    /** Open (or reveal) the chart tab of the session on screen. */
    open(): void;
    /** Back both stages out. Idempotent, and every teardown is failure-isolated. */
    dispose(): void;
}
/**
 * Register the chart as a tab type of the host's right column.
 * @param host - the resolved host services.
 * @param options - the body, its props, and the availability callback.
 * @returns the registration, live until `dispose()`.
 */
export declare function registerNativeTab(host: NativeTabHost, options: NativeTabOptions): NativeTabRegistration;
