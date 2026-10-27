import { KLINE_TAB_ID, klineTabTitle } from "./sidebar-integration.js";
/**
 * The static half of the native right-Sidebar integration.
 *
 * Kept free of JSX so the tests can import it directly: the registration itself
 * needs a host context, but what this plugin contributes — the tab kind, the
 * band it registers in, the chip title and the guide entry — is plain data.
 */
/**
 * Implementation identity of the tab type; also the key its body registers
 * under. The host only requires it to be unique across every registration, and
 * a package name is the natural value for a type shipped from another package.
 */
export const NATIVE_TAB_ID = '@ftshare-lab/dsh-kline';
/**
 * The type definition this plugin contributes.
 *
 * A page type (no address `patterns`) is opened by kind, which is what the
 * auto-open path does; the guide entry is how a person reaches the chart from
 * the host's own add-tab page. Both keep the product label separate from the
 * internal kind, exactly like the Better Sidebar title does.
 *
 * `keepMounted` matters for the chart: collapsing the right column or
 * switching tabs must not tear the chart down, because the view keeps its
 * own state (last instrument reference, zoom, drawings) that a remount loses.
 */
export function nativeTabDefinition() {
    return {
        id: NATIVE_TAB_ID,
        kind: KLINE_TAB_ID,
        keepMounted: true,
        priority: 'extension',
        title: () => klineTabTitle(),
        guide: [{
                id: NATIVE_TAB_ID,
                order: 120,
                title: () => klineTabTitle(),
                description: nativeTabDescription,
            }],
    };
}
/** One line under the guide capsule: what picking it opens, in the host language. */
export function nativeTabDescription(locale = globalThis.navigator?.language ?? '') {
    return /^zh(?:-|$)/i.test(locale) ? '行情图表与关键点位分析' : 'Market chart and key-level analysis';
}
