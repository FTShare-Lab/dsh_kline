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

/** What a host may change; every field omitted means the upstream behavior. */
export interface KlineHostOptions {
  /**
   * `'tab'` — the host owns the chart entry (its own right column), so the
   * chart must not draw the floating classic launcher. Omitted: the user's
   * stored interface preference decides, with the launcher as the fallback.
   */
  entry?: 'tab'
  /**
   * `'off'` — the host suppresses the first-run welcome and the one-time
   * interface notice. Omitted: upstream onboarding.
   */
  onboarding?: 'off'
}

let current: KlineHostOptions | undefined
const listeners = new Set<() => void>()

/** The options the active host provided, if it provided any. */
export function readHostOptions(): KlineHostOptions | undefined {
  return current
}

/** Subscribe to host option changes; the router repaints when they arrive. */
export function subscribeHostOptions(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/**
 * Take the options a host provided.
 *
 * Unknown or malformed values are dropped rather than trusted, so this stays a
 * closed contract: only the switches this build understands ever take effect.
 * @param value - the service value, or undefined when the host withdrew it.
 */
export function setHostOptions(value: unknown): void {
  const raw = (value ?? {}) as Record<string, unknown>
  const next: KlineHostOptions = {}
  if (raw.entry === 'tab') next.entry = 'tab'
  if (raw.onboarding === 'off') next.onboarding = 'off'
  current = Object.keys(next).length === 0 ? undefined : next
  for (const listener of [...listeners]) listener()
}
