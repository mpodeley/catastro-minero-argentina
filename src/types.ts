/** Shapes emitted by scripts/build.py, aggregate.py and validate.py.
 *  Keep in sync with scripts/esquema.py — that file is the source of truth. */

export type TipoDerecho =
  | 'cateo'
  | 'mina'
  | 'manifestacion_descubrimiento'
  | 'cantera'
  | 'servidumbre'
  | 'solicitud'
  | 'planta'
  | 'area_proteccion'
  | 'otro'

export type Estado =
  | 'vigente'
  | 'tramite'
  | 'caduco'
  | 'desistido'
  | 'vacante'
  | 'desconocido'

/** Properties on a tenement feature. Slim: build.py drops null/empty fields,
 *  so almost everything is optional and the UI must degrade gracefully.
 *  Missing attributes are the normal case, not an error — see cobertura. */
export interface DerechoProps {
  id: string
  provincia: string
  provincia_nombre: string
  tipo: TipoDerecho
  estado: Estado
  geom_kind: 'poligono' | 'punto' | 'linea'

  expediente?: string
  expediente_gde?: string
  tipo_origen?: string
  estado_origen?: string
  nombre?: string

  titular?: string
  titular_norm?: string
  titular_es_persona?: boolean
  mineral?: string[]
  mineral_origen?: string

  fecha_inicio?: string
  fecha_resolucion?: string
  fecha_inscripcion?: string
  fecha_mensura?: string

  superficie_ha?: number
  superficie_ha_calc?: number
  superficie_delta?: number
  cantidad_pertenencias?: number

  departamento?: string
  municipio?: string
  lugar?: string

  /** Provenance — always present. This is what the popup cites. */
  fuente_id: string
  source_url: string
  source_layer: string
  source_fid: string
  source_srid: number
  fetched_at: string
  licencia: string
}

export interface TenenciaFC {
  type: 'FeatureCollection'
  metadata?: { provincia: string; n: number; bbox?: number[]; aviso?: string }
  features: Array<{
    type: 'Feature'
    geometry: { type: string; coordinates: unknown }
    properties: DerechoProps
  }>
}

export interface Titular {
  titular_norm: string
  nombre: string
  es_persona: boolean
  n_derechos: number
  ha: number
  provincias: string[]
  minerales: string[]
  tipos: Record<string, number>
}

export interface ProvinciaAgg {
  cobertura: 'completa' | 'sin_datos' | 'declarada_no_implementada'
  n_derechos: number | null
  ha?: number
  pct_provincia?: number | null
  n_titulares?: number
  pct_con_titular?: number
  tipos?: Record<string, number>
  estados?: Record<string, number>
  mineral_dominante?: string | null
  minerales?: Record<string, number>
  motivo?: string
}

export interface Agregados {
  provincias: Record<string, ProvinciaAgg>
  departamentos: Array<{
    provincia: string
    departamento: string
    n_derechos: number
    ha: number
    mineral_dominante: string | null
  }>
  totales: {
    n_derechos: number
    ha: number
    n_provincias_con_datos: number
    n_titulares: number
  }
  nota_departamentos: string
}

export interface TitularesDoc {
  titulares: Titular[]
  top_empresas: Titular[]
  resumen: {
    n_titulares: number
    n_empresas: number
    n_personas_fisicas: number
    ha_empresas: number
    ha_personas_fisicas: number
    derechos_sin_titular: number
    aviso: string
  }
}

/** Envelope written by scripts/_meta.py write_json(). */
export interface Envelope<T> {
  generated_at: string
  source: string | null
  source_date: string | null
  data: T
}
