/**
 * The optional host contract for panel mounts.
 *
 * A host that already owns a bounded panel declares a slot of its own and asks
 * the chart to fill it through the `klinePanels` service. The chart therefore
 * never learns a host's slot names, and a host that does not ask sees the
 * plugin exactly as it was before this contract existed.
 *
 * Kept free of React, like `native-sidebar-register.ts`, so the registration
 * policy is testable with fake slot services.
 */
/**
 * Turn slot services plus a body factory into the `klinePanels` service.
 * @param host - the host services a mount registers into.
 * @param body - the component body for one seat (one per mounted seat).
 * @returns the service a host calls; nothing is registered until it calls.
 */
export function createPanelMounts(host, body) {
    return {
        mount(seat, options) {
            // `slots.inject` returns the factory's disposer when the seat is already
            // declared, and the injection's own disposer otherwise — the same shape
            // the native tab registration relies on.
            const dispose = host.slots.inject(seat, () => host.slots.register({ name: seat }, body(seat, options?.chrome)));
            return () => { dispose?.(); };
        },
    };
}
