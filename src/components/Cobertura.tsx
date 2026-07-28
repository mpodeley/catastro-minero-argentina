import { c, sp } from '../theme'
import type { Agregados, TitularesDoc } from '../types'
import { fmtHa, fmtInt } from '../utils/format'

/** Coverage + the national holder ranking.
 *
 *  This view carries the project's two honesty obligations. Provinces that
 *  publish nothing are listed as an explicit absence rather than omitted, so
 *  the reader cannot mistake "no data" for "no mining". And the ranking names
 *  companies while aggregating natural persons into a count. */
export default function Cobertura({
  agg,
  tit,
}: {
  agg: Agregados | null
  tit: TitularesDoc | null
}) {
  if (!agg) return <div style={{ padding: sp.lg }}>Cargando…</div>

  const conDatos = Object.entries(agg.provincias)
    .filter(([, p]) => p.cobertura === 'completa')
    .sort((a, b) => (b[1].ha ?? 0) - (a[1].ha ?? 0))
  const sinDatos = Object.entries(agg.provincias).filter(([, p]) => p.cobertura !== 'completa')

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: sp.lg }}>
      <p style={{ maxWidth: 760, color: c.textDim, fontSize: 13, lineHeight: 1.6 }}>
        Argentina no tiene catastro minero nacional. Bajo el Código de Minería las
        provincias son dueñas del recurso, así que cada una publica —o no— su propio
        registro, con formato y campos distintos. Esto es la unión de las que sí publican
        algo legible por máquina.
      </p>

      <H>Provincias relevadas</H>
      <table style={tabla}>
        <thead>
          <tr>
            {['Provincia', 'Derechos', 'Superficie', '% provincia', 'Titulares', '% con titular', 'Mineral dominante'].map(
              (h) => (
                <th key={h} style={th}>
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {conDatos.map(([k, p]) => (
            <tr key={k}>
              <td style={td}>{nombre(k)}</td>
              <td style={tdNum}>{fmtInt(p.n_derechos ?? 0)}</td>
              <td style={tdNum}>{fmtHa(p.ha ?? 0)}</td>
              <td style={tdNum}>{p.pct_provincia?.toFixed(1) ?? '—'}%</td>
              <td style={tdNum}>{fmtInt(p.n_titulares ?? 0)}</td>
              <td style={{ ...tdNum, color: (p.pct_con_titular ?? 0) < 50 ? c.warn : c.text }}>
                {p.pct_con_titular?.toFixed(0) ?? '—'}%
              </td>
              <td style={td}>{p.mineral_dominante ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <H>Provincias sin datos abiertos</H>
      <p style={{ fontSize: 12, color: c.textDim, maxWidth: 760, lineHeight: 1.6 }}>
        Ausencia, no cero. Estas provincias tienen actividad minera —algunas, muchísima—
        pero no publican el catastro en un formato reutilizable. El mapa no las dibuja
        como territorio libre.
      </p>
      <ul style={{ fontSize: 12, lineHeight: 1.7, maxWidth: 760, color: c.textDim }}>
        {sinDatos.map(([k, p]) => (
          <li key={k}>
            <b style={{ color: c.text }}>{nombre(k)}</b> — {p.motivo ?? 'declarada, no implementada aún'}
          </li>
        ))}
      </ul>

      {tit && (
        <>
          <H>Titulares con más superficie</H>
          <p style={{ fontSize: 12, color: c.warn, maxWidth: 760, lineHeight: 1.6 }}>
            ⚠ Es un ranking de lo <i>publicado</i>, no de la realidad: las provincias
            difieren en si informan titular, y {fmtInt(tit.resumen.derechos_sin_titular)} derechos
            no lo traen. Las {fmtInt(tit.resumen.n_personas_fisicas)} personas físicas
            ({fmtHa(tit.resumen.ha_personas_fisicas)}) se agregan en este conteo y no se listan
            por nombre.
          </p>
          <table style={tabla}>
            <thead>
              <tr>
                {['#', 'Titular', 'Superficie', 'Derechos', 'Provincias', 'Minerales'].map((h) => (
                  <th key={h} style={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tit.top_empresas.map((t, i) => (
                <tr key={t.titular_norm}>
                  <td style={{ ...tdNum, color: c.textFaint }}>{i + 1}</td>
                  <td style={td}>{t.nombre}</td>
                  <td style={tdNum}>{fmtHa(t.ha)}</td>
                  <td style={tdNum}>{fmtInt(t.n_derechos)}</td>
                  <td style={{ ...td, color: c.textDim }}>{t.provincias.map(nombre).join(', ')}</td>
                  <td style={{ ...td, color: c.textDim }}>{t.minerales.join(' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <H>Nota sobre los datos</H>
      <p style={{ fontSize: 12, color: c.textDim, maxWidth: 760, lineHeight: 1.6 }}>
        Cada derecho lleva su procedencia: URL exacta de la consulta, capa, CRS de origen y
        fecha de descarga, visibles al hacer clic en el mapa. Las categorías provinciales se
        normalizan a un vocabulario común pero se conserva la palabra original de cada
        provincia — «mina» en Salta no significa lo mismo que «mina padrón» en San Juan, y
        «vigente» no tiene una definición legal compartida entre códigos provinciales.
      </p>
      <p style={{ fontSize: 12, color: c.textFaint, maxWidth: 760, lineHeight: 1.6 }}>
        {agg.nota_departamentos}
      </p>
    </div>
  )
}

const NOMBRES: Record<string, string> = {
  san_juan: 'San Juan',
  salta: 'Salta',
  catamarca: 'Catamarca',
  neuquen: 'Neuquén',
  cordoba: 'Córdoba',
  jujuy: 'Jujuy',
  santa_cruz: 'Santa Cruz',
  chubut: 'Chubut',
  rio_negro: 'Río Negro',
  mendoza: 'Mendoza',
  la_rioja: 'La Rioja',
  san_luis: 'San Luis',
}
const nombre = (k: string) => NOMBRES[k] ?? k

function H({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, color: c.accent, marginTop: sp.xl }}>
      {children}
    </h2>
  )
}

const tabla: React.CSSProperties = {
  borderCollapse: 'collapse',
  fontSize: 12,
  width: '100%',
  maxWidth: 900,
  marginBottom: sp.md,
}
const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  borderBottom: `1px solid ${c.border}`,
  color: c.textFaint,
  fontWeight: 500,
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: 0.5,
}
const td: React.CSSProperties = {
  padding: '5px 10px',
  borderBottom: `1px solid ${c.panelAlt}`,
}
const tdNum: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
