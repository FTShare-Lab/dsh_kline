import type { ClientContext } from './client-context';
import type { Sessions } from './conversation';
import type { NativeTabBodyProps } from './native-sidebar-services';
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
export declare function NativeKlineTabBody({ sessionId, sessions, useTabInfo }: NativeTabBodyProps): import("react").JSX.Element;
/**
 * Auto-open lives in the tab's own session, exactly like the Better Sidebar
 * path; the router decides whether this path is the active interface.
 */
export declare function NativeSidebarBridgeView({ bridge, sessions }: {
    bridge: NativeSidebarBridge;
    sessions: Sessions;
}): import("react").JSX.Element | null;
/** The host-facing handle the router polls to decide which interface to draw. */
export interface NativeSidebarBridge {
    /** Both stages registered: the host can draw the chart tab. */
    available(): boolean;
    /** Open (or reveal) the chart tab of the session on screen. */
    open(): void;
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
export declare function registerNativeSidebar(ctx: ClientContext, onChange: () => void): NativeSidebarBridge;
