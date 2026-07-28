"""Orchestrator: provincial sources -> normalized per-province GeoJSON.

Fail-soft by design. One dead provincial endpoint must never take down the whole
build: the exception is caught, the province is marked `caida` in cobertura.json
and the previously built file is left in place. Only a global failure or a
validate.py FAIL aborts the deploy. This mirrors the `blocked` source convention
in estado-del-sistema's FuentesPage.

Usage:
    python scripts/build.py                 # all sources, using the raw/ cache
    python scripts/build.py --no-cache      # force refetch
    python scripts/build.py --solo salta    # one province
"""

import argparse
import json
import os
import sys
import traceback
from collections import Counter, defaultdict

from pyproj import Geod

import fuentes as F
from _meta import write_json
from adapters import build_adapter
from esquema import Derecho

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "raw")
DATA = os.path.join(ROOT, "public", "data")
TEN = os.path.join(DATA, "tenencias")

# WGS84 ellipsoid. Geodesic area needs no equal-area projection choice, so
# there is no projection decision to get wrong.
_GEOD = Geod(ellps="WGS84")


def area_ha(geom: dict) -> float | None:
    """Geodesic area of a (Multi)Polygon in hectares.

    Ring orientation varies across sources, so the absolute value is taken;
    interior rings are subtracted by index (ring 0 is the exterior).
    """
    t = geom.get("type")
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return None

    total = 0.0
    for rings in polys:
        for i, ring in enumerate(rings):
            if len(ring) < 4:
                continue
            lons = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            a, _ = _GEOD.polygon_area_perimeter(lons, lats)
            total += abs(a) if i == 0 else -abs(a)
    return round(total / 10_000.0, 4) if total > 0 else None


def with_area(d: Derecho) -> Derecho:
    """Attach computed area and its delta against the declared figure.

    Publishing both, and flagging the gap, is the point: surfacing the QA rather
    than hiding it is what makes the dataset trustworthy.
    """
    import dataclasses

    if d.geom_kind != "poligono":
        return d
    calc = area_ha(d.geometry)
    delta = None
    if calc is not None and d.superficie_ha:
        delta = round((calc - d.superficie_ha) / d.superficie_ha, 4)
    return dataclasses.replace(d, superficie_ha_calc=calc, superficie_delta=delta)


def dedupe(ds: list[Derecho]) -> tuple[list[Derecho], int]:
    """Drop rows that are byte-identical tenements under different source ids.

    San Juan's `vw_minas_padron` view fans out: mina "PIQUE DE ORTEGA" arrives
    as 15 rows with 15 distinct GeoServer feature ids but one expediente, one
    name, one geometry and `cantidadPertenencias: 1`. That is a join in the
    published view, not pagination on our side — the count assert in the WFS
    adapter passes, because the server really does report 1,378.

    Left in, 213 of San Juan's 4,406 rows (4.8%) are redundant and inflate both
    the hectare total and the "% of the province under title" headline, so they
    are collapsed here and counted in cobertura.json rather than silently kept
    or silently dropped.

    Deliberately scoped per source layer: a manifestacion de descubrimiento and
    the mina it became legitimately share an expediente and a footprint across
    two different layers, and collapsing those would erase a real distinction.
    """
    vistos: dict[tuple, Derecho] = {}
    n_dup = 0
    for d in ds:
        clave = (
            d.fuente_id,
            d.expediente_norm,
            d.nombre,
            json.dumps(d.geometry["coordinates"], separators=(",", ":")),
        )
        if clave in vistos:
            n_dup += 1
            continue
        vistos[clave] = d
    return list(vistos.values()), n_dup


def build_provincia(provincia: str, use_cache: bool) -> dict:
    """Fetch + normalize every source for one province. Returns its report."""
    srcs = F.por_provincia(provincia)
    derechos: list[Derecho] = []
    reportes: list[dict] = []

    for f in srcs:
        rep = {
            "fuente_id": f.id, "layer": f.layer, "kind": f.kind,
            "url": f.url, "licencia": f.licencia, "notas": f.notas,
        }
        try:
            a = build_adapter(f)
            raw = a.fetch(RAW, use_cache=use_cache)
            got = [d for d in (a.normalize(r, raw) for r in a.parse(raw)) if d]
            got, n_dup = dedupe(got)
            got = [with_area(d) for d in got]
            derechos.extend(got)
            rep.update({
                "estado": "ok",
                "features": len(got),
                # Count as the SERVER reports it, before dedupe. health_check.py
                # probes the server, so it must diff against this and not
                # against the deduped total (San Juan: 1378 vs 1166).
                "features_fuente": len(got) + n_dup,
                "duplicados_fuente": n_dup,
                "fetched_at": raw.fetched_at, "sha256": raw.sha256,
                "resolved_layer": raw.resolved_layer,
                # Transfer size when the adapter knows it (a KMZ is compressed),
                # else the payload size. Must match what probe() can observe.
                "bytes": raw.meta.get("bytes_descarga", len(raw.body)),
            })
            extra = f" (+{n_dup} duplicados de origen descartados)" if n_dup else ""
            print(f"    {f.id}: {len(got)} features{extra}")
        except NotImplementedError as e:
            rep.update({"estado": "declarada_no_implementada", "error": str(e)})
            print(f"    {f.id}: declarada, no implementada")
        except Exception as e:  # noqa: BLE001 — fail-soft, one source cannot kill the build
            rep.update({"estado": "caida", "error": f"{type(e).__name__}: {e}"[:300]})
            print(f"    {f.id}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(limit=2, file=sys.stderr)
        reportes.append(rep)

    # One file per geometry kind. Mixing them would break the canvas polygon
    # renderer and the hectare statistics alike — Salta's servidumbres are
    # lines and Cordoba's minas are points, and neither has an area.
    por_kind: dict[str, list[Derecho]] = defaultdict(list)
    for d in derechos:
        por_kind[d.geom_kind].append(d)
    polis = por_kind.get("poligono", [])

    # A province with no working source gets no file at all, so the frontend
    # can tell "sin datos" apart from "cero derechos".
    if polis:
        _write_geojson(os.path.join(TEN, f"{provincia}.geojson"), polis, provincia)
    for kind, sufijo in (("punto", "puntos"), ("linea", "lineas")):
        if por_kind.get(kind):
            _write_geojson(
                os.path.join(TEN, f"{provincia}_{sufijo}.geojson"), por_kind[kind], provincia
            )

    ok = [r for r in reportes if r["estado"] == "ok"]
    return {
        "provincia": provincia,
        "provincia_nombre": srcs[0].provincia_nombre if srcs else provincia,
        "estado": "ok" if ok else "caida",
        "n_derechos": len(polis),
        "n_puntos": len(por_kind.get("punto", [])),
        "n_lineas": len(por_kind.get("linea", [])),
        "ha_total": round(sum(d.superficie_ha_calc or 0 for d in polis), 1),
        "fuentes": reportes,
        "tipos": dict(Counter(d.tipo for d in polis).most_common()),
        "estados": dict(Counter(d.estado for d in polis).most_common()),
        "minerales": dict(Counter(m for d in polis for m in d.mineral).most_common(20)),
        "completitud": _completitud(polis),
    }


def _completitud(ds: list[Derecho]) -> dict:
    """Null rate per field.

    Drives the honest coverage table — e.g. "San Juan cateos: titular 0%" — and
    is the most useful artifact for anyone deciding whether to trust this data.
    """
    if not ds:
        return {}
    campos = ("expediente", "nombre", "titular", "mineral", "estado_origen",
              "fecha_inicio", "superficie_ha", "departamento")
    out = {}
    for c in campos:
        n = sum(1 for d in ds if getattr(d, c) not in (None, "", []))
        out[c] = round(100.0 * n / len(ds), 1)
    return out


def _write_geojson(path: str, ds: list[Derecho], provincia: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "provincia": provincia,
            "n": len(ds),
            "bbox": _bbox(ds),
            "aviso": (
                "Derivado de fuentes provinciales. Licencias por fuente en "
                "cobertura.json. El catastro minero es registro publico por el "
                "Codigo de Mineria; verificar licencia antes de uso comercial."
            ),
        },
        "features": [d.to_feature(slim=True) for d in ds],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))


def _bbox(ds: list[Derecho]) -> list[float] | None:
    xs: list[float] = []
    ys: list[float] = []

    def walk(c):
        if isinstance(c, (int, float)):
            return
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
            return
        for x in c:
            walk(x)

    for d in ds:
        walk(d.geometry["coordinates"])
    if not xs:
        return None
    return [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true", help="ignorar raw/ y refetchear")
    ap.add_argument("--solo", help="construir una sola provincia (slug)")
    args = ap.parse_args()

    provs = [args.solo] if args.solo else F.provincias()
    reportes = []
    for p in provs:
        print(f"[{p}]")
        reportes.append(build_provincia(p, use_cache=not args.no_cache))

    total = sum(r["n_derechos"] for r in reportes)
    ha = sum(r["ha_total"] for r in reportes)

    write_json(
        os.path.join(DATA, "cobertura.json"),
        {
            "provincias": reportes,
            "sin_datos_abiertos": F.SIN_DATOS_ABIERTOS,
            "totales": {
                "n_derechos": total,
                "ha_total": round(ha, 1),
                "provincias_con_datos": sum(1 for r in reportes if r["estado"] == "ok"),
                "provincias_sin_datos": len(F.SIN_DATOS_ABIERTOS),
            },
        },
        source="catastros mineros provinciales",
    )

    print(f"\nTOTAL: {total} derechos, {ha:,.0f} ha, {len(provs)} provincias")
    caidas = [r["provincia"] for r in reportes if r["estado"] != "ok"]
    if caidas:
        print(f"AVISO: provincias caidas (build sigue): {caidas}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
