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
/**
 * Run `mount` when `element` has a non-zero box.
 * @param element - the host element the chart shadow root lives in.
 * @param mount - idempotent mount step; called at most once.
 * @returns a cancel function that does nothing after mounting.
 */
export declare function whenLaidOut(element: HTMLElement, mount: () => void): () => void;
