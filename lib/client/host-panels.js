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
/** Coordinate caller lifetimes independently of the current slot-service lifetime. */
export function createPanelMountRegistry() {
    const requests = new Map();
    let current;
    const disconnect = (connection) => {
        if (current === connection)
            current = undefined;
        const disposers = [...connection.mounted.values()];
        connection.mounted.clear();
        const errors = [];
        for (const dispose of disposers) {
            try {
                dispose();
            }
            catch (error) {
                errors.push(error);
            }
        }
        if (errors.length)
            throw new AggregateError(errors, 'Could not release host chart panels');
    };
    return {
        mount(seat, options) {
            const chrome = options?.chrome ?? 'chart-search';
            let request = requests.get(seat);
            if (request && request.chrome !== chrome)
                throw new Error(`Chart panel "${seat}" is already mounted with different chrome`);
            if (!request) {
                request = { chrome, users: 0 };
                requests.set(seat, request);
                try {
                    if (current)
                        current.mounted.set(seat, current.service.mount(seat, { chrome }));
                }
                catch (error) {
                    requests.delete(seat);
                    throw error;
                }
            }
            const lease = request;
            lease.users += 1;
            let released = false;
            return () => {
                if (released)
                    return;
                released = true;
                if (--lease.users > 0 || requests.get(seat) !== lease)
                    return;
                requests.delete(seat);
                const dispose = current?.mounted.get(seat);
                current?.mounted.delete(seat);
                dispose?.();
            };
        },
        connect(service) {
            if (current)
                disconnect(current);
            const connection = { service, mounted: new Map() };
            current = connection;
            try {
                for (const [seat, request] of requests) {
                    connection.mounted.set(seat, service.mount(seat, { chrome: request.chrome }));
                }
            }
            catch (error) {
                try {
                    disconnect(connection);
                }
                catch (cleanupError) {
                    throw new AggregateError([error, cleanupError], 'Could not attach host chart panels');
                }
                throw error;
            }
            return () => disconnect(connection);
        },
    };
}
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
            let released = false;
            return () => {
                if (released)
                    return;
                released = true;
                dispose?.();
            };
        },
    };
}
