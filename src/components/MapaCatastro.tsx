import { useCallback, useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { DerechoProps } from '../types'
import { COLOR_ESTADO, COLOR_MINERAL, COLOR_TIPO, c } from '../theme'
import { loadProvincia } from '../hooks/useData'
import { SIN_DATOS, quantileBins, rampColor } from '../utils/choropleth'
import type { ProvinciaAgg } from '../types'

export type ModoColor = 'tipo' | 'estado' | 'mineral'

export interface Filtros {
  tipos: Set<string>
  estados: Set<string>
  minerales: Set<string>
  soloConTitular: boolean
  texto: string
}

interface Props {
  provincias: string[]
  /** Per-province rollups, for the national choropleth below ZOOM_DETALLE. */
  agg: Record<string, ProvinciaAgg> | null
  modo: ModoColor
  filtros: Filtros
  onSelect: (p: DerechoProps | null) => void
  onCounts: (counts: { visibles: number; cargadas: string[] }) => void
}

/** Provinces are loaded when the viewport reaches them, so the map needs a
 *  cheap bbox per province before any geometry exists. Values are generous —
 *  they only decide when to start a fetch. */
const BBOX: Record<string, [number, number, number, number]> = {
  san_juan: [-70.6, -32.9, -66.9, -28.4],
  salta: [-68.6, -26.4, -62.3, -22.0],
  catamarca: [-69.1, -30.1, -64.9, -25.2],
  neuquen: [-71.9, -41.1, -68.0, -36.0],
  cordoba: [-65.8, -35.0, -61.8, -29.5],
  jujuy: [-67.3, -24.6, -64.4, -21.8],
}

const ZOOM_DETALLE = 7

function colorDe(p: DerechoProps, modo: ModoColor): string {
  if (modo === 'estado') return COLOR_ESTADO[p.estado] ?? c.textFaint
  if (modo === 'mineral') {
    const m = p.mineral?.[0]
    return (m && COLOR_MINERAL[m]) || c.textFaint
  }
  return COLOR_TIPO[p.tipo] ?? c.textFaint
}

function pasaFiltro(p: DerechoProps, f: Filtros): boolean {
  if (f.tipos.size && !f.tipos.has(p.tipo)) return false
  if (f.estados.size && !f.estados.has(p.estado)) return false
  if (f.minerales.size && !(p.mineral || []).some((m) => f.minerales.has(m))) return false
  if (f.soloConTitular && !p.titular) return false
  if (f.texto) {
    const q = f.texto.toLowerCase()
    const campos = [p.titular, p.nombre, p.expediente, p.departamento]
    if (!campos.some((v) => v && v.toLowerCase().includes(q))) return false
  }
  return true
}

export default function MapaCatastro({
  provincias,
  agg,
  modo,
  filtros,
  onSelect,
  onCounts,
}: Props) {
  const divRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const rendererRef = useRef<L.Canvas | null>(null)
  // One layer group per province, so a province can be added or restyled
  // without touching the others.
  const capasRef = useRef<Map<string, L.LayerGroup>>(new Map())
  const propsRef = useRef<Map<L.Path, DerechoProps>>(new Map())
  // Provinces whose fetch has been started. Separate from capasRef because a
  // claim must be visible to the next moveend immediately, not on resolve.
  const pedidasRef = useRef<Set<string>>(new Set())
  // Held in a ref so the per-province click handler, bound once at load time,
  // always calls the current onSelect instead of the one captured back then.
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const [cargando, setCargando] = useState<string[]>([])
  const [cargadas, setCargadas] = useState<string[]>([])
  // Tier 0: the national view. Without it the map opens empty until the user
  // guesses to zoom in, which is both a bad first impression and a misleading
  // one — an empty Argentina reads as an unconcessioned Argentina.
  const provinciasGjRef = useRef<unknown>(null)
  const coropletaRef = useRef<L.GeoJSON | null>(null)
  const aggRef = useRef(agg)
  aggRef.current = agg

  const pintarProvincias = useCallback(() => {
    const map = mapRef.current
    const gj = provinciasGjRef.current
    if (!map || !gj) return
    coropletaRef.current?.remove()

    const a = aggRef.current ?? {}
    const bins = quantileBins(
      Object.values(a).map((p) => p?.pct_provincia ?? 0).filter((v) => v > 0),
    )

    coropletaRef.current = L.geoJSON(gj as never, {
      style: (feat) => {
        const id = (feat?.properties as { id?: string } | undefined)?.id ?? ''
        const p = a[id]
        const conDatos = p?.cobertura === 'completa'
        const pct = p?.pct_provincia ?? 0
        return {
          color: conDatos ? '#0f172a' : c.textFaint,
          weight: conDatos ? 1 : 0.8,
          // Provinces with no open data are drawn hollow and dashed. They must
          // never take a colour from the ramp: absence is not zero.
          dashArray: conDatos ? undefined : '3 3',
          fillColor: conDatos ? rampColor(pct, bins) : SIN_DATOS,
          fillOpacity: conDatos ? 0.75 : 0.12,
        }
      },
      onEachFeature: (feat, layer) => {
        const id = (feat.properties as { id?: string; name?: string }).id ?? ''
        const nombre = (feat.properties as { name?: string }).name ?? id
        const p = a[id]
        layer.bindTooltip(
          p?.cobertura === 'completa'
            ? `<b>${nombre}</b><br>${(p.pct_provincia ?? 0).toFixed(1)}% bajo derecho minero` +
                `<br>${(p.n_derechos ?? 0).toLocaleString('es-AR')} derechos`
            : `<b>${nombre}</b><br><i>sin datos abiertos</i>`,
          { sticky: true },
        )
      },
    })
    // Only meaningful at the national scale; above ZOOM_DETALLE the real
    // parcels take over and the fill would just muddy them.
    if (map.getZoom() < ZOOM_DETALLE) coropletaRef.current.addTo(map)
  }, [])

  useEffect(() => {
    pintarProvincias()
  }, [agg, pintarProvincias])

  // --- init ------------------------------------------------------------------
  useEffect(() => {
    if (!divRef.current || mapRef.current) return

    const renderer = L.canvas({ padding: 0.5 })
    rendererRef.current = renderer

    const map = L.map(divRef.current, {
      // Canvas, not SVG: 18k polygons as DOM nodes would not survive a pan.
      preferCanvas: true,
      renderer,
      center: [-31.5, -67.0],
      zoom: 5,
      zoomControl: true,
      attributionControl: true,
    })
    mapRef.current = map

    const bases = {
      'IGN Argenmap': L.tileLayer(
        'https://wms.ign.gob.ar/geoserver/gwc/service/tms/1.0.0/capabaseargenmap@EPSG:3857@png/{z}/{x}/{-y}.png',
        { attribution: 'IGN Argentina', maxZoom: 18 },
      ),
      Satélite: L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Esri World Imagery', maxZoom: 18 },
      ),
      Claro: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '© OpenStreetMap, © CARTO',
        maxZoom: 19,
      }),
    }
    bases['IGN Argenmap'].addTo(map)

    // Live WMS rather than a vendored copy: it cites SEGEMAR in real time and
    // costs no storage. Note /geoserver is disabled upstream; /geoserver217 works.
    const overlays = {
      'Depósitos metalíferos (SEGEMAR)': L.tileLayer.wms(
        'https://sigam.segemar.gov.ar/geoserver217/wms',
        {
          layers: 'sigam:e250K.DepositMetalif',
          format: 'image/png',
          transparent: true,
          attribution: 'SEGEMAR SIGAM',
        },
      ),
    }
    L.control.layers(bases, overlays, { collapsed: true }).addTo(map)

    fetch('./data/provincias.geojson')
      .then((r) => r.json())
      .then((gj) => {
        provinciasGjRef.current = gj
        pintarProvincias()
      })
      .catch(() => undefined)

    return () => {
      map.remove()
      mapRef.current = null
      capasRef.current.clear()
      propsRef.current.clear()
      pedidasRef.current.clear()
    }
  }, [])

  // --- lazy province loading -------------------------------------------------
  const revisarViewport = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    if (map.getZoom() < ZOOM_DETALLE) return
    const b = map.getBounds()

    for (const prov of provincias) {
      // Claimed synchronously, before the await. `capasRef` is only populated
      // when the fetch resolves, so guarding on it alone lets a second
      // moveend slip through and build the province's layers twice — which is
      // exactly what "cordoba, cordoba, san_juan, san_juan" was.
      if (capasRef.current.has(prov) || pedidasRef.current.has(prov)) continue
      const bb = BBOX[prov]
      if (!bb) continue
      const pb = L.latLngBounds([bb[1], bb[0]], [bb[3], bb[2]])
      if (!b.intersects(pb)) continue
      pedidasRef.current.add(prov)

      setCargando((s) => (s.includes(prov) ? s : [...s, prov]))
      loadProvincia(prov)
        .then((fc) => {
          if (!mapRef.current) return
          // One L.geoJSON for the whole province, not one per feature: each
          // call allocates a layer group and re-runs option merging, which at
          // 6k features is seconds of avoidable work.
          // `smoothFactor` is a PolylineOption, and L.geoJSON forwards its
          // options to each created path at runtime, but @types/leaflet models
          // GeoJSONOptions without it. The intersection type says what Leaflet
          // actually accepts instead of casting the whole object to any.
          const opciones: L.GeoJSONOptions & L.PolylineOptions = {
            // The renderer belongs in PathOptions so every generated path joins
            // the single shared canvas instead of allocating its own.
            renderer: rendererRef.current!,
            // 0 because these are surveyed rectangles: smoothing visibly
            // deforms a 5-vertex parcel.
            smoothFactor: 0,
            style: { weight: 0.6, opacity: 0.9, fillOpacity: 0.35 },
            onEachFeature: (feat, layer) => {
              propsRef.current.set(layer as L.Path, feat.properties as DerechoProps)
            },
          }
          const capa = L.geoJSON(fc as never, opciones)
          // One handler per province (six total), not one per feature. Bound on
          // the GeoJSON group rather than the map: clicks propagate from the
          // child path up to here with `propagatedFrom` set, whereas a
          // map-level handler also fires for clicks on empty basemap and does
          // not reliably carry the originating layer.
          capa.on('click', (e: L.LeafletMouseEvent) => {
            const path = (e as unknown as { propagatedFrom?: L.Path }).propagatedFrom
            const p = path && propsRef.current.get(path)
            if (p) onSelectRef.current(p)
          })
          const grupo = L.layerGroup([capa]).addTo(mapRef.current)
          capasRef.current.set(prov, grupo)
          setCargando((s) => s.filter((x) => x !== prov))
          setCargadas((s) => [...s, prov])
        })
        .catch(() => {
          pedidasRef.current.delete(prov)   // allow a retry on the next pan
          setCargando((s) => s.filter((x) => x !== prov))
        })
    }
  }, [provincias])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const onMove = () => {
      revisarViewport()
      const cp = coropletaRef.current
      if (!cp) return
      const detalle = map.getZoom() >= ZOOM_DETALLE
      if (detalle && map.hasLayer(cp)) cp.remove()
      else if (!detalle && !map.hasLayer(cp)) cp.addTo(map)
    }
    map.on('moveend zoomend', onMove)
    onMove()
    return () => {
      map.off('moveend zoomend', onMove)
    }
  }, [revisarViewport])

  // --- styling + filtering ---------------------------------------------------
  // Restyling walks every loaded path rather than rebuilding layers: rebuilding
  // 18k canvas paths on every legend click would stall the main thread.
  useEffect(() => {
    let visibles = 0
    for (const [path, p] of propsRef.current) {
      const ok = pasaFiltro(p, filtros)
      const col = colorDe(p, modo)
      path.setStyle({
        color: col,
        fillColor: col,
        opacity: ok ? 0.9 : 0,
        fillOpacity: ok ? 0.35 : 0,
        interactive: ok,
      })
      if (ok) visibles++
    }
    onCounts({ visibles, cargadas })
  }, [modo, filtros, cargadas, onCounts])

  return (
    <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
      <div ref={divRef} style={{ position: 'absolute', inset: 0, background: c.bg }} />
      {cargando.length > 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: 12,
            left: 12,
            zIndex: 500,
            background: c.panel,
            color: c.text,
            border: `1px solid ${c.border}`,
            borderRadius: 6,
            padding: '6px 10px',
            fontSize: 12,
          }}
        >
          cargando {cargando.join(', ')}…
        </div>
      )}
      {cargadas.length === 0 && <ZoomHint />}
    </div>
  )
}

function ZoomHint() {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        right: 12,
        zIndex: 500,
        background: c.panel,
        color: c.textDim,
        border: `1px solid ${c.border}`,
        borderRadius: 6,
        padding: '6px 10px',
        fontSize: 11,
        maxWidth: 220,
      }}
    >
      Acercá a zoom {ZOOM_DETALLE}+ para ver los polígonos de cada provincia.
    </div>
  )
}
