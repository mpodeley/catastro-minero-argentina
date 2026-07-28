import { useEffect, useState } from 'react'
import type { Agregados, Envelope, TenenciaFC, TitularesDoc } from '../types'

/** Loads a JSON written by scripts/_meta.py and unwraps its envelope.
 *  Mirrors estado-del-sistema/src/hooks/useData.ts so both projects behave
 *  the same way when a dataset is missing or stale. */
export function useJson<T>(path: string): {
  data: T | null
  loading: boolean
  error: string | null
  meta: { generated_at?: string; source?: string | null } | null
} {
  const [data, setData] = useState<T | null>(null)
  const [meta, setMeta] = useState<{ generated_at?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    fetch(path, { cache: 'no-store' })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
        return r.json()
      })
      .then((j: Envelope<T> | T) => {
        if (!alive) return
        if (j && typeof j === 'object' && 'data' in (j as object)) {
          const e = j as Envelope<T>
          setData(e.data)
          setMeta({ generated_at: e.generated_at })
        } else {
          setData(j as T)
        }
        setError(null)
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [path])

  return { data, loading, error, meta }
}

export const useAgregados = () => useJson<Agregados>('./data/agregados.json')
export const useTitulares = () => useJson<TitularesDoc>('./data/titulares.json')

/** Lazy per-province tenement loader.
 *
 *  Provinces are fetched on demand and cached for the session. This is the
 *  whole reason the app can hold ~18k parcels without a tiling pipeline: the
 *  largest single province is well under 1 MB gzipped, and a typical session
 *  touches one or two. */
const cache = new Map<string, TenenciaFC>()
const inflight = new Map<string, Promise<TenenciaFC>>()

export function loadProvincia(prov: string): Promise<TenenciaFC> {
  const hit = cache.get(prov)
  if (hit) return Promise.resolve(hit)
  const running = inflight.get(prov)
  if (running) return running

  const p = fetch(`./data/tenencias/${prov}.geojson`, { cache: 'force-cache' })
    .then((r) => {
      if (!r.ok) throw new Error(`${prov}: ${r.status}`)
      return r.json() as Promise<TenenciaFC>
    })
    .then((fc) => {
      cache.set(prov, fc)
      inflight.delete(prov)
      return fc
    })
    .catch((e) => {
      inflight.delete(prov)
      throw e
    })
  inflight.set(prov, p)
  return p
}

export const provinciaEnCache = (prov: string) => cache.has(prov)
