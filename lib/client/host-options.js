/**
 * The optional host contract for the chrome the chart draws itself.
 *
 * A host client plugin provides the `klineHost` service; nothing else changes
 * when it is absent, which is what keeps every upstream default intact. Only
 * the members a host may switch are modelled here, and unknown values collapse
 * to the default, so a newer host can never put the chart in a half-configured
 * state.
 *
 * The store is deliberately framework-free: the router subscribes with
 * `useSyncExternalStore`, and the onboarding classifier reads it once per open.
 */
let current;
const listeners = new Set();
/** The options the active host provided, if it provided any. */
export function readHostOptions() {
    return current;
}
/** Subscribe to host option changes; the router repaints when they arrive. */
export function subscribeHostOptions(listener) {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
}
/**
 * Take the options a host provided.
 *
 * Unknown or malformed values are dropped rather than trusted, so this stays a
 * closed contract: only the switches this build understands ever take effect.
 * @param value - the service value, or undefined when the host withdrew it.
 */
export function setHostOptions(value) {
    const raw = (value ?? {});
    const next = {};
    if (raw.entry === 'tab')
        next.entry = 'tab';
    if (raw.onboarding === 'off')
        next.onboarding = 'off';
    current = Object.keys(next).length === 0 ? undefined : next;
    for (const listener of [...listeners])
        listener();
}
