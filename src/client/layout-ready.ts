/**
 * Mount the chart only once its container has a real layout box.
 *
 * The chart runtime sizes its canvases during init. A tab body can be created
 * before the host lays it out (the first frame of a newly opened right pane),
 * and init at 0×0 leaves every canvas 0×0 until an unrelated resize. Waiting
 * for the first non-zero box removes that first-frame blank without delaying a
 * container that is already laid out.
 *
 * An element without numeric layout properties (a non-browser test double or
 * an exotic host) and a runtime without ResizeObserver cannot be observed, so
 * both keep the previous behaviour and mount immediately.
 */

type LayoutObserver = {
  observe(target: Element): void
  disconnect(): void
}

const resizeObserver = (): (new (callback: () => void) => LayoutObserver) | undefined => {
  const candidate = (globalThis as { ResizeObserver?: new (callback: () => void) => LayoutObserver }).ResizeObserver
  return typeof candidate === 'function' ? candidate : undefined
}

/**
 * Run `mount` when `element` has a non-zero box.
 * @param element - the host element the chart shadow root lives in.
 * @param mount - idempotent mount step; called at most once.
 * @returns a cancel function that does nothing after mounting.
 */
export function whenLaidOut(element: HTMLElement, mount: () => void): () => void {
  const box = () => {
    const width = Number(element.clientWidth)
    const height = Number(element.clientHeight)
    return Number.isFinite(width) && Number.isFinite(height) ? { width, height } : undefined
  }
  const now = box()
  if (now === undefined || (now.width > 0 && now.height > 0)) {
    mount()
    return () => {}
  }
  const Observer = resizeObserver()
  if (Observer === undefined) {
    mount()
    return () => {}
  }
  let mounted = false
  let cancelled = false
  const observer = new Observer(() => {
    if (cancelled || mounted) return
    const next = box()
    if (next === undefined || next.width <= 0 || next.height <= 0) return
    mounted = true
    observer.disconnect()
    mount()
  })
  observer.observe(element)
  return () => {
    cancelled = true
    if (!mounted) observer.disconnect()
  }
}
