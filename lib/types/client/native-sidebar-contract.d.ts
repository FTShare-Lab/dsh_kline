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
export declare const NATIVE_TAB_ID = "@ftshare-lab/dsh-kline";
/** One tab type as DSH's own right-Sidebar registry takes it (the members this plugin sets). */
export interface NativeSidebarTabDefinition {
    /** Implementation identity, unique across registrations; the body seat dispatches by it. */
    id: string;
    /** Type discriminator — what `openTab` names and what every tab of this type is. */
    kind: string;
    /** Every opening of this type is one page per pane: the chart is a singleton. */
    multiple?: boolean;
    /** Keep a visited body mounted through hiding, Session changes and docking. */
    keepMounted?: boolean;
    /** `extension` is the band for a type shipped outside the product, which is this one. */
    priority?: 'extension' | 'builtin' | 'fallback';
    /** The chip text captured when a tab of this type opens. */
    title: (address: string) => string;
    /** Entry boxes the host's guide page offers for opening this type. */
    guide?: readonly NativeSidebarGuideEntry[];
}
/** One guide entry: a capsule that opens this tab type when picked. */
export interface NativeSidebarGuideEntry {
    id: string;
    order: number;
    title: () => string;
    description?: () => string;
}
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
export declare function nativeTabDefinition(): NativeSidebarTabDefinition;
/** One line under the guide capsule: what picking it opens, in the host language. */
export declare function nativeTabDescription(locale?: string): string;
