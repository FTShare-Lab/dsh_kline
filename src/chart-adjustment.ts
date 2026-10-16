/** Metadata aliases only; never transform prices or guess missing adjustment. */
export function normalizeAdjustment(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const aliases: Record<string, string> = { none: 'none', forward: 'forward', backward: 'backward', qfq: 'forward', hfq: 'backward' }
  return Object.hasOwn(aliases, value.trim().toLowerCase()) ? aliases[value.trim().toLowerCase()] : null
}
