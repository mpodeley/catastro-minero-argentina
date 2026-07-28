/** Colors and spacing tokens. No inline hex codes anywhere else. */

export const c = {
  bg: '#0f172a',
  panel: '#1e293b',
  panelAlt: '#243449',
  border: '#334155',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  textFaint: '#64748b',
  accent: '#38bdf8',
  warn: '#fbbf24',
  danger: '#f87171',
  ok: '#4ade80',
}

/** Categorical palette for tenement types.
 *
 *  Hues are assigned by what the right MEANS, not arbitrarily: exploration
 *  stages (cateo, manifestacion) sit in the cool half, granted exploitation
 *  (mina, cantera) in the warm half, so the exploration-to-exploitation
 *  pipeline reads as a temperature gradient rather than a lookup exercise. */
export const COLOR_TIPO: Record<string, string> = {
  cateo: '#38bdf8',
  manifestacion_descubrimiento: '#818cf8',
  solicitud: '#a78bfa',
  mina: '#fb923c',
  cantera: '#fbbf24',
  servidumbre: '#f472b6',
  planta: '#facc15',
  area_proteccion: '#4ade80',
  otro: '#94a3b8',
}

export const LABEL_TIPO: Record<string, string> = {
  cateo: 'Cateo',
  manifestacion_descubrimiento: 'Manifestación',
  solicitud: 'Solicitud',
  mina: 'Mina',
  cantera: 'Cantera',
  servidumbre: 'Servidumbre',
  planta: 'Planta',
  area_proteccion: 'Área de protección',
  otro: 'Otro',
}

export const COLOR_ESTADO: Record<string, string> = {
  vigente: '#4ade80',
  tramite: '#fbbf24',
  caduco: '#f87171',
  desistido: '#a78bfa',
  vacante: '#38bdf8',
  desconocido: '#64748b',
}

export const LABEL_ESTADO: Record<string, string> = {
  vigente: 'Vigente',
  tramite: 'En trámite',
  caduco: 'Caduco',
  desistido: 'Desistido',
  vacante: 'Vacante',
  desconocido: 'Sin dato',
}

/** Minerals carry conventional associations (lithium/brine pale, copper
 *  orange-brown, gold yellow, silver grey) — leaning on them makes the map
 *  readable without constant legend trips. */
export const COLOR_MINERAL: Record<string, string> = {
  Li: '#22d3ee',
  Cu: '#f97316',
  Au: '#fbbf24',
  Ag: '#cbd5e1',
  Pb: '#94a3b8',
  Zn: '#a3e635',
  U: '#4ade80',
  Fe: '#f87171',
  B: '#c084fc',
  K: '#fb7185',
  sal: '#e2e8f0',
  aridos: '#a8a29e',
  caliza: '#d6d3d1',
}

export const sp = { xs: 4, sm: 8, md: 12, lg: 20, xl: 32 }
