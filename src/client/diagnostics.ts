/**
 * One-line, once-per-page diagnostics for the native right Sidebar path.
 *
 * The chart tab can be absent for several independent reasons: the host omits
 * one of its three sidebar services, the body seat is declared later than the
 * tab type, the display preference keeps the classic launcher, or the host has
 * no Session on screen. Each of those used to be silent, so a report like
 * "chart_ready is true but no tab appears" could not be located from the page.
 * These messages name the failing condition and stay bounded: every key is
 * printed at most once per page, and the registration state is also exposed
 * through `NativeSidebarBridge.state()` for programmatic checks.
 */

const reported = new Set<string>()

/** Emit one diagnostic per key; repeated hits are counted by the caller's state. */
export function reportOnce(
  key: string,
  message: string,
  details?: unknown,
): void {
  if (reported.has(key)) return
  reported.add(key)
  try {
    if (details === undefined) console.info(message)
    else console.info(message, details)
  } catch {
    // Logging must never break the interface that is being diagnosed.
  }
}

/** Forget the once-per-page keys; only tests call this. */
export function resetDiagnostics(): void {
  reported.clear()
}
