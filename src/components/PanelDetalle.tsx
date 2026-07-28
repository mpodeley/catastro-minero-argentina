import { COLOR_ESTADO, COLOR_MINERAL, COLOR_TIPO, LABEL_ESTADO, LABEL_TIPO, c, sp } from '../theme'
import type { DerechoProps } from '../types'
import { fmtFecha, fmtNum } from '../utils/format'

/** Detail for one tenement.
 *
 *  Two things here are deliberate. Declared and computed hectares are shown
 *  side by side with a warning when they disagree — surfacing the QA rather
 *  than hiding it is the point. And every record carries a provenance footer
 *  with the exact request URL and fetch timestamp, which is the one thing no
 *  official provincial viewer gives you. */
export default function PanelDetalle({ p, onClose }: { p: DerechoProps; onClose: () => void }) {
  const delta = p.superficie_delta
  const discrepa = delta !== undefined && Math.abs(delta) > 0.05

  return (
    <aside
      style={{
        width: 320,
        flexShrink: 0,
        background: c.panel,
        borderLeft: `1px solid ${c.border}`,
        overflowY: 'auto',
        padding: sp.md,
        fontSize: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'start', gap: sp.sm }}>
        <h2 style={{ fontSize: 14, margin: 0, flex: 1, lineHeight: 1.3 }}>
          {p.nombre || p.expediente || 'Sin denominación'}
        </h2>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: c.textFaint,
            cursor: 'pointer',
            fontSize: 16,
            lineHeight: 1,
          }}
          aria-label="Cerrar"
        >
          ×
        </button>
      </div>

      <div style={{ display: 'flex', gap: sp.xs, flexWrap: 'wrap', margin: `${sp.sm}px 0` }}>
        <Badge color={COLOR_TIPO[p.tipo]} label={LABEL_TIPO[p.tipo] ?? p.tipo} />
        <Badge color={COLOR_ESTADO[p.estado]} label={LABEL_ESTADO[p.estado] ?? p.estado} />
        {(p.mineral ?? []).map((m) => (
          <Badge key={m} color={COLOR_MINERAL[m] ?? c.textFaint} label={m} />
        ))}
      </div>

      <Fila k="Titular" v={p.titular} vacio="no publicado por la provincia" />
      <Fila k="Provincia" v={p.provincia_nombre} />
      <Fila k="Departamento" v={p.departamento} />
      <Fila k="Municipio" v={p.municipio} />
      <Fila k="Lugar" v={p.lugar} />

      <Sep />

      <div style={{ display: 'flex', gap: sp.md }}>
        <div style={{ flex: 1 }}>
          <Etiqueta>Superficie declarada</Etiqueta>
          <div style={{ fontSize: 13 }}>
            {p.superficie_ha !== undefined ? `${fmtNum(p.superficie_ha)} ha` : '—'}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <Etiqueta>Calculada</Etiqueta>
          <div style={{ fontSize: 13, color: discrepa ? c.warn : c.text }}>
            {p.superficie_ha_calc !== undefined ? `${fmtNum(p.superficie_ha_calc)} ha` : '—'}
          </div>
        </div>
      </div>
      {delta !== undefined && (
        <div style={{ fontSize: 11, color: discrepa ? c.warn : c.textFaint, marginTop: sp.xs }}>
          {discrepa ? '⚠ ' : ''}
          diferencia {(delta * 100).toFixed(2)}% respecto de lo declarado
        </div>
      )}
      {p.cantidad_pertenencias !== undefined && (
        <Fila k="Pertenencias" v={String(p.cantidad_pertenencias)} />
      )}

      <Sep />

      <Fila k="Expediente" v={p.expediente} />
      <Fila k="Expediente GDE" v={p.expediente_gde} />
      <Fila k="Categoría de origen" v={p.tipo_origen} />
      <Fila k="Estado de origen" v={p.estado_origen} />
      <Fila k="Inicio" v={fmtFecha(p.fecha_inicio)} />
      <Fila k="Inscripción" v={fmtFecha(p.fecha_inscripcion)} />
      <Fila k="Mensura" v={fmtFecha(p.fecha_mensura)} />

      <Sep />

      <Etiqueta>Procedencia</Etiqueta>
      <div style={{ fontSize: 10, color: c.textDim, lineHeight: 1.6, wordBreak: 'break-all' }}>
        <div>
          <b>Fuente:</b> {p.fuente_id}
        </div>
        <div>
          <b>Capa:</b> {p.source_layer}
        </div>
        <div>
          <b>CRS de origen:</b> EPSG:{p.source_srid}
        </div>
        <div>
          <b>Descargado:</b> {fmtFecha(p.fetched_at, true)}
        </div>
        <div>
          <b>Licencia:</b> {p.licencia}
        </div>
        <a
          href={p.source_url}
          target="_blank"
          rel="noreferrer"
          style={{ color: c.accent, display: 'inline-block', marginTop: sp.xs }}
        >
          ver consulta original ↗
        </a>
      </div>
    </aside>
  )
}

function Fila({ k, v, vacio }: { k: string; v?: string | null; vacio?: string }) {
  if (!v && !vacio) return null
  return (
    <div style={{ display: 'flex', gap: sp.sm, padding: '2px 0' }}>
      <span style={{ color: c.textFaint, minWidth: 110, flexShrink: 0 }}>{k}</span>
      <span style={{ color: v ? c.text : c.textFaint, fontStyle: v ? 'normal' : 'italic' }}>
        {v || vacio}
      </span>
    </div>
  )
}

function Etiqueta({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: 1,
        color: c.textFaint,
        marginBottom: 2,
      }}
    >
      {children}
    </div>
  )
}

function Badge({ color, label }: { color: string; label: string }) {
  return (
    <span
      style={{
        background: color,
        color: c.bg,
        borderRadius: 3,
        padding: '1px 6px',
        fontSize: 10,
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  )
}

function Sep() {
  return <hr style={{ border: 0, borderTop: `1px solid ${c.border}`, margin: `${sp.md}px 0` }} />
}
