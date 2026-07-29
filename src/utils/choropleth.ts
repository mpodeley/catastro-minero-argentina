// Choropleth ramp for the national view. Ported from estado-red-gas's
// utils/choropleth.ts: a 7-step monochromatic warm ramp (dark amber → pale
// yellow) that reads over a dark basemap and avoids rainbow confusion.
//
// Binning is by quantile (rank, not value) because a handful of provinces sit
// near 80% titled while others are near 1%; linear bins would collapse
// everyone but San Juan into a single bucket.

export const HEAT_PALETTE = [
  '#b45309', '#d97706', '#ea580c', '#f97316', '#fb923c', '#fbbf24', '#fde047',
]

/** Provinces that publish nothing get their own treatment, NEVER the low end
 *  of the ramp. Rendering absence as "almost zero mining" is the one error
 *  this map must not make. */
export const SIN_DATOS = '#475569'

export function quantileBins(values: number[]): number[] {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b)
  if (sorted.length === 0) return []
  const out: number[] = []
  for (let i = 1; i < HEAT_PALETTE.length; i++) {
    const idx = Math.floor((i * sorted.length) / HEAT_PALETTE.length)
    out.push(sorted[Math.min(idx, sorted.length - 1)])
  }
  return out
}

export function rampColor(value: number, bins: number[]): string {
  if (value <= 0 || bins.length === 0) return SIN_DATOS
  let idx = 0
  while (idx < bins.length && value >= bins[idx]) idx++
  return HEAT_PALETTE[idx] ?? HEAT_PALETTE[HEAT_PALETTE.length - 1]
}

export function formatBins(bins: number[], suffix = '%'): string[] {
  const f = (v: number) => (v < 10 ? v.toFixed(1) : v.toFixed(0))
  if (!bins.length) return []
  const labels = [`< ${f(bins[0])}${suffix}`]
  for (let i = 1; i < bins.length; i++) labels.push(`${f(bins[i - 1])}${suffix}+`)
  labels.push(`≥ ${f(bins[bins.length - 1])}${suffix}`)
  return labels
}
