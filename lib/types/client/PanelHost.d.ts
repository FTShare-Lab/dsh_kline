import type { ClientContext } from './client-context';
import type { KlineChrome } from './embed';
import { type KlinePanelProps } from './host-panels.ts';
/**
 * The chart as a host panel body.
 *
 * The host declares a slot, renders it with `{ symbol, name, onIdentity }` and
 * asks the chart to fill it through `klinePanels.mount(seat)`. The body is the
 * same chart the sidebar and the tab draw, only bounded and without the
 * workspace chrome that belongs to the sidebar.
 */
export declare function KlinePanelHost({ seat, chrome, symbol, name, onIdentity }: KlinePanelProps & {
    seat: string;
    chrome?: KlineChrome;
}): import("react").JSX.Element;
/**
 * Register the optional host panel contract.
 *
 * The `klinePanels` service exists for every host, but it registers nothing
 * until a host mounts a seat: without a caller no slot is injected, so a host
 * that does not know this contract sees the plugin exactly as before. Mounts
 * requested before the `slots` service settles are applied once it does.
 * @param ctx - the client context to register on.
 */
export declare function registerPanelHosts(ctx: ClientContext): void;
