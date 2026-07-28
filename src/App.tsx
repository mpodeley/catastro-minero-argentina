import { useCallback, useMemo, useState } from 'react'
import MapaCatastro, { type Filtros, type ModoColor } from './components/MapaCatastro'
import PanelDetalle from './components/PanelDetalle'
import Cobertura from './components/Cobertura'
import {
  COLOR_ESTADO,
  COLOR_MINERAL,
  COLOR_TIPO,
  LABEL_ESTADO,
  LABEL_TIPO,
  c,
  sp,
} from './theme'
import { useAgregados, useTitulares } from './hooks/useData'
import type { DerechoProps } from './types'
import { fmtHa, fmtInt } from './utils/format'

/** Provinces the map may try to fetch. Derived from agregados.json rather than
 *  hardcoded: a province declared in the registry but not yet implemented
 *  (Jujuy) has no tenencias file, and asking for it 404s on every pan. */
function provinciasConDatos(agg: import('./types').Agregados | null): string[] {
  if (!agg) return []
  return Object.entries(agg.provincias)
    .filter(([, p]) => p.cobertura === 'completa')
    .map(([k]) => k)
}

const MODOS: Array<{ k: ModoColor; label: string }> = [
  { k: 'tipo', label: 'Tipo de derecho' },
  { k: 'estado', label: 'Estado' },
  { k: 'mineral', label: 'Mineral' },
]

export default function App() {
  const { data: agg } = useAgregados()
  const { data: tit } = useTitulares()

  const [modo, setModo] = useState<ModoColor>('tipo')
  const [tipos, setTipos] = useState<Set<string>>(new Set())
  const [estados, setEstados] = useState<Set<string>>(new Set())
  const [minerales, setMinerales] = useState<Set<string>>(new Set())
  const [soloConTitular, setSolo] = useState(false)
  const [texto, setTexto] = useState('')
  const [sel, setSel] = useState<DerechoProps | null>(null)
  const [counts, setCounts] = useState({ visibles: 0, cargadas: [] as string[] })
  const [vista, setVista] = useState<'mapa' | 'cobertura'>('mapa')

  const provincias = useMemo(() => provinciasConDatos(agg), [agg])

  const filtros: Filtros = useMemo(
    () => ({ tipos, estados, minerales, soloConTitular, texto }),
    [tipos, estados, minerales, soloConTitular, texto],
  )

  const onCounts = useCallback((x: { visibles: number; cargadas: string[] }) => {
    setCounts((prev) =>
      prev.visibles === x.visibles && prev.cargadas.length === x.cargadas.length ? prev : x,
    )
  }, [])

  const toggle = (s: Set<string>, set: (v: Set<string>) => void, k: string) => {
    const n = new Set(s)
    n.has(k) ? n.delete(k) : n.add(k)
    set(n)
  }

  const tiposDisponibles = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const p of Object.values(agg?.provincias ?? {})) {
      for (const [k, v] of Object.entries(p.tipos ?? {})) acc[k] = (acc[k] ?? 0) + v
    }
    return Object.entries(acc).sort((a, b) => b[1] - a[1])
  }, [agg])

  const mineralesDisponibles = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const p of Object.values(agg?.provincias ?? {})) {
      for (const [k, v] of Object.entries(p.minerales ?? {})) acc[k] = (acc[k] ?? 0) + v
    }
    return Object.entries(acc)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
  }, [agg])

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: c.bg,
        color: c.text,
        fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <Header agg={agg} tit={tit} vista={vista} setVista={setVista} />

      {vista === 'cobertura' ? (
        <Cobertura agg={agg} tit={tit} />
      ) : (
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <aside
            style={{
              width: 260,
              flexShrink: 0,
              background: c.panel,
              borderRight: `1px solid ${c.border}`,
              overflowY: 'auto',
              padding: sp.md,
            }}
          >
            <Seccion titulo="Colorear por">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: sp.xs }}>
                {MODOS.map((m) => (
                  <button
                    key={m.k}
                    onClick={() => setModo(m.k)}
                    style={btn(modo === m.k)}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </Seccion>

            <Seccion titulo="Buscar">
              <input
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                placeholder="titular, mina o expediente"
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  background: c.bg,
                  color: c.text,
                  border: `1px solid ${c.border}`,
                  borderRadius: 4,
                  padding: '6px 8px',
                  fontSize: 12,
                }}
              />
            </Seccion>

            <Seccion titulo="Tipo">
              {tiposDisponibles.map(([k, n]) => (
                <Chip
                  key={k}
                  activo={!tipos.size || tipos.has(k)}
                  color={COLOR_TIPO[k]}
                  label={LABEL_TIPO[k] ?? k}
                  n={n}
                  onClick={() => toggle(tipos, setTipos, k)}
                />
              ))}
            </Seccion>

            <Seccion titulo="Estado">
              {Object.keys(LABEL_ESTADO).map((k) => (
                <Chip
                  key={k}
                  activo={!estados.size || estados.has(k)}
                  color={COLOR_ESTADO[k]}
                  label={LABEL_ESTADO[k]}
                  onClick={() => toggle(estados, setEstados, k)}
                />
              ))}
            </Seccion>

            <Seccion titulo="Mineral">
              {mineralesDisponibles.map(([k, n]) => (
                <Chip
                  key={k}
                  activo={!minerales.size || minerales.has(k)}
                  color={COLOR_MINERAL[k] ?? c.textFaint}
                  label={k}
                  n={n}
                  onClick={() => toggle(minerales, setMinerales, k)}
                />
              ))}
            </Seccion>

            <Seccion titulo="Otros">
              <label style={{ fontSize: 12, display: 'flex', gap: sp.sm, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={soloConTitular}
                  onChange={(e) => setSolo(e.target.checked)}
                />
                Sólo con titular conocido
              </label>
              <p style={{ fontSize: 10, color: c.textFaint, marginTop: sp.xs, lineHeight: 1.4 }}>
                Los {fmtInt(tit?.resumen.derechos_sin_titular ?? 0)} derechos sin titular
                no son un error: varias provincias no publican ese dato.
              </p>
            </Seccion>
          </aside>

          <MapaCatastro
            provincias={provincias}
            agg={agg?.provincias ?? null}
            modo={modo}
            filtros={filtros}
            onSelect={setSel}
            onCounts={onCounts}
          />

          {sel && <PanelDetalle p={sel} onClose={() => setSel(null)} />}
        </div>
      )}

      <footer
        style={{
          borderTop: `1px solid ${c.border}`,
          padding: `${sp.xs}px ${sp.md}px`,
          fontSize: 11,
          color: c.textFaint,
          display: 'flex',
          gap: sp.lg,
        }}
      >
        <span>{fmtInt(counts.visibles)} derechos visibles</span>
        <span>
          provincias cargadas: {counts.cargadas.length ? counts.cargadas.join(', ') : '—'}
        </span>
        <span style={{ marginLeft: 'auto' }}>
          Derivado de catastros provinciales · licencias por fuente en Cobertura
        </span>
      </footer>
    </div>
  )
}

function Header({
  agg,
  tit,
  vista,
  setVista,
}: {
  agg: import('./types').Agregados | null
  tit: import('./types').TitularesDoc | null
  vista: string
  setVista: (v: 'mapa' | 'cobertura') => void
}) {
  return (
    <header
      style={{
        borderBottom: `1px solid ${c.border}`,
        padding: `${sp.sm}px ${sp.md}px`,
        display: 'flex',
        alignItems: 'baseline',
        gap: sp.lg,
        flexWrap: 'wrap',
      }}
    >
      <h1 style={{ fontSize: 15, margin: 0, letterSpacing: 0.2 }}>
        Catastro Minero Argentina
      </h1>
      <span style={{ fontSize: 12, color: c.textDim }}>
        Quién tiene derechos sobre el suelo
      </span>
      {agg && (
        <span style={{ fontSize: 12, color: c.textDim, display: 'flex', gap: sp.md }}>
          <b style={{ color: c.text }}>{fmtInt(agg.totales.n_derechos)}</b> derechos
          <b style={{ color: c.text }}>{fmtHa(agg.totales.ha)}</b>
          <span>{agg.totales.n_provincias_con_datos} provincias</span>
          {tit && <span>{fmtInt(tit.resumen.n_titulares)} titulares</span>}
        </span>
      )}
      <nav style={{ marginLeft: 'auto', display: 'flex', gap: sp.xs }}>
        <button onClick={() => setVista('mapa')} style={btn(vista === 'mapa')}>
          Mapa
        </button>
        <button onClick={() => setVista('cobertura')} style={btn(vista === 'cobertura')}>
          Cobertura y titulares
        </button>
      </nav>
    </header>
  )
}

function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: sp.lg }}>
      <h2
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: 1,
          color: c.textFaint,
          margin: `0 0 ${sp.sm}px`,
        }}
      >
        {titulo}
      </h2>
      {children}
    </div>
  )
}

function Chip({
  activo,
  color,
  label,
  n,
  onClick,
}: {
  activo: boolean
  color: string
  label: string
  n?: number
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: sp.sm,
        width: '100%',
        background: 'none',
        border: 'none',
        padding: '3px 0',
        cursor: 'pointer',
        color: activo ? c.text : c.textFaint,
        textDecoration: activo ? 'none' : 'line-through',
        fontSize: 12,
        textAlign: 'left',
      }}
    >
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: 2,
          background: color,
          opacity: activo ? 1 : 0.3,
          flexShrink: 0,
        }}
      />
      <span style={{ flex: 1 }}>{label}</span>
      {n !== undefined && <span style={{ color: c.textFaint, fontSize: 11 }}>{fmtInt(n)}</span>}
    </button>
  )
}

function btn(activo: boolean): React.CSSProperties {
  return {
    background: activo ? c.accent : c.panelAlt,
    color: activo ? c.bg : c.text,
    border: `1px solid ${activo ? c.accent : c.border}`,
    borderRadius: 4,
    padding: '4px 8px',
    fontSize: 11,
    cursor: 'pointer',
    fontWeight: activo ? 600 : 400,
  }
}
