/** Metadata aliases only; never transform prices or guess missing adjustment. */
export function normalizeAdjustment(value) {
    if (typeof value !== 'string')
        return null;
    const aliases = { none: 'none', forward: 'forward', backward: 'backward', qfq: 'forward', hfq: 'backward' };
    return Object.hasOwn(aliases, value.trim().toLowerCase()) ? aliases[value.trim().toLowerCase()] : null;
}
