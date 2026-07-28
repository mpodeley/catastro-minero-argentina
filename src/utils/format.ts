/** Spanish-Argentine number formatting: dot thousands, comma decimals. */

const NF = new Intl.NumberFormat('es-AR')

export const fmtInt = (n: number): string => NF.format(Math.round(n))

export const fmtNum = (n: number, dp = 2): string =>
  new Intl.NumberFormat('es-AR', { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n)

/** Hectares at readable magnitude. Cadastral totals run to millions, where
 *  raw hectares stop being legible. */
export function fmtHa(ha: number): string {
  if (ha >= 1_000_000) return `${fmtNum(ha / 1_000_000, 1)} M ha`
  if (ha >= 10_000) return `${fmtInt(ha)} ha`
  return `${fmtNum(ha, 1)} ha`
}

export function fmtFecha(iso?: string | null, conHora = false): string | undefined {
  if (!iso) return undefined
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso)
  if (Number.isNaN(d.getTime())) return iso
  const f = d.toISOString().slice(0, 10).split('-').reverse().join('/')
  return conHora ? `${f} ${d.toISOString().slice(11, 16)} UTC` : f
}
