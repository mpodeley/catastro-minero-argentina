"""Quality gate. Writes calidad.json and exits non-zero to block the deploy.

The checks are ordered by how badly a failure would mislead someone reading the
map. The two that can actually publish a wrong map without anyone noticing are
CRS misassignment (#2) and the run-over-run diff (#8), so those are hard gates;
overlaps and area outliers are reported, never fatal, because they are often
genuine properties of a cadastre rather than defects in this pipeline.

Usage:
    python scripts/validate.py            # gate
    python scripts/validate.py --report   # never exit non-zero
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

from shapely.geometry import shape
from shapely.validation import explain_validity, make_valid
from shapely.strtree import STRtree

import fuentes as F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "public", "data")
TEN = os.path.join(DATA, "tenencias")

# Thresholds. Each is a judgement about what rate stops being source noise and
# starts being a bug in this code.
MAX_INVALID_PCT = 2.0        # above this, it is a parse bug, not source noise
MAX_FUERA_PCT = 0.5          # a wrong faja displaces geometry by hundreds of km
MAX_DELTA_MEDIANA = 0.02     # 2% median area error => systematic datum problem
MAX_DIFF_PCT = 10.0          # a cadastre does not lose 10% of its rights in a week
# Beyond this, a centroid outside its declared province means a projection
# error rather than a border-adjacent tenement. A wrong faja moves geometry by
# hundreds of km, so this sits far above real cross-border cases (Salta's reach
# into Catamarca tops out at ~11 km) and far below any faja mistake.
MAX_DERIVA_KM = 30.0

# Approximate province areas (km2), for the coverage-plausibility check.
# Source: IGN. Only used to catch >100% absurdities, so precision is not critical.
AREA_PROV_KM2 = {
    "san_juan": 89_651, "salta": 155_488, "catamarca": 102_602,
    "neuquen": 94_078, "cordoba": 165_321, "jujuy": 53_219,
}


def cargar(provincia: str) -> list[dict]:
    path = os.path.join(TEN, f"{provincia}.geojson")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("features") or []


def provincia_bounds() -> dict:
    """Province outlines, for the containment check. Optional but recommended."""
    path = os.path.join(DATA, "provincias.geojson")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    out = {}
    for feat in gj.get("features") or []:
        pid = (feat.get("properties") or {}).get("id")
        if pid:
            try:
                out[pid] = shape(feat["geometry"]).buffer(0.05)  # ~5 km tolerance
            except Exception:  # noqa: BLE001
                pass
    return out


def revisar(provincia: str, bounds: dict) -> dict:
    feats = cargar(provincia)
    r: dict = {"provincia": provincia, "n": len(feats), "checks": {}, "fallas": []}
    if not feats:
        r["checks"]["sin_datos"] = True
        return r

    geoms, invalid, reparadas = [], [], 0
    fuera_bbox, fuera_prov, limitrofes = [], [], []
    deltas, sin_area = [], 0
    expedientes = Counter()
    huellas = Counter()
    ids_por_huella = defaultdict(set)
    ha_total = 0.0

    outline = bounds.get(provincia)

    for f in feats:
        p = f.get("properties") or {}
        try:
            g = shape(f["geometry"])
        except Exception as e:  # noqa: BLE001
            invalid.append(f"{p.get('id')}: {type(e).__name__}")
            continue

        # 1. geometry validity
        if not g.is_valid:
            invalid.append(f"{p.get('id')}: {explain_validity(g)[:80]}")
            g = make_valid(g)
            reparadas += 1
        geoms.append(g)

        # 2. CRS misassignment — the highest-value check.
        #
        # Graded by distance, because "outside the declared province" and
        # "wrongly projected" are not the same thing. A wrong faja displaces
        # geometry by hundreds of kilometres; Salta genuinely registers 39
        # tenements 6-11 km inside Catamarca, along a Puna border whose
        # position is itself disputed. Failing on the latter would mean
        # loosening the check until it stops catching the former.
        c = g.centroid
        if not (-74.5 <= c.x <= -52.5 and -56.5 <= c.y <= -20.5):
            fuera_bbox.append(p.get("id"))
        elif outline is not None and not outline.contains(c):
            dist_km = outline.distance(c) * 111.0
            (fuera_prov if dist_km > MAX_DERIVA_KM else limitrofes).append(
                {"id": p.get("id"), "km": round(dist_km, 1)}
            )

        # 3. declared vs computed area
        if p.get("superficie_delta") is not None:
            deltas.append(abs(p["superficie_delta"]))
        elif not p.get("superficie_ha"):
            sin_area += 1
        ha_total += p.get("superficie_ha_calc") or 0.0

        # 4. duplicate expedientes
        if p.get("expediente"):
            expedientes[p["expediente"]] += 1
        # Scope is (source layer, source's own category), and the fingerprint is
        # the real geometry rather than area+centroid.
        #
        # Both refinements are needed. Neuquen ships one KMZ whose folders are
        # the layers, so a `pertenencias` row and a `minas` row for the same
        # right share fuente_id, expediente and footprint — legitimately, since
        # the province publishes both. And area+centroid alone conflates merely
        # co-located parcels: of 55 groups it flagged in Neuquen, only 13 had
        # genuinely identical coordinates.
        huella = (
            p.get("fuente_id"), p.get("tipo_origen"), p.get("expediente"),
            json.dumps(f["geometry"]["coordinates"], separators=(",", ":")),
        )
        huellas[huella] += 1
        ids_por_huella[huella].add(p.get("source_fid"))

    n = len(feats)
    pct_invalid = 100.0 * len(invalid) / n
    pct_fuera = 100.0 * (len(fuera_bbox) + len(fuera_prov)) / n

    r["checks"]["geometria"] = {
        "invalidas": len(invalid), "reparadas": reparadas,
        "pct": round(pct_invalid, 2), "ejemplos": invalid[:5],
    }
    if pct_invalid > MAX_INVALID_PCT:
        r["fallas"].append(
            f"geometrias invalidas {pct_invalid:.1f}% > {MAX_INVALID_PCT}% "
            f"(sugiere bug de parseo, no ruido de fuente)"
        )

    r["checks"]["ubicacion"] = {
        "fuera_de_argentina": len(fuera_bbox),
        "desplazados": len(fuera_prov),
        "limitrofes": len(limitrofes),
        "limitrofes_km_max": max((x["km"] for x in limitrofes), default=0),
        "pct": round(pct_fuera, 2),
        "ejemplos": (fuera_prov + limitrofes)[:5],
        "sin_contorno_provincial": outline is None,
        "nota": (
            "'limitrofes' son derechos cuyo centroide cae hasta "
            f"{MAX_DERIVA_KM:.0f} km fuera del contorno provincial: cruces de "
            "frontera reales o efecto del contorno simplificado (~2 km). "
            "'desplazados' es lo que delata un error de faja."
        ),
    }
    if pct_fuera > MAX_FUERA_PCT:
        r["fallas"].append(
            f"{pct_fuera:.2f}% de los derechos caen a mas de {MAX_DERIVA_KM:.0f} km "
            f"de su provincia > {MAX_FUERA_PCT}% (sugiere faja/datum equivocado)"
        )

    if deltas:
        deltas.sort()
        mediana = deltas[len(deltas) // 2]
        r["checks"]["superficie"] = {
            "con_declarada": len(deltas), "sin_declarada": sin_area,
            "delta_mediana_pct": round(mediana * 100, 3),
            "delta_p90_pct": round(deltas[int(0.9 * len(deltas))] * 100, 2),
            "sobre_5pct": sum(1 for d in deltas if d > 0.05),
        }
        if mediana > MAX_DELTA_MEDIANA:
            r["fallas"].append(
                f"mediana de error de superficie {mediana*100:.2f}% > "
                f"{MAX_DELTA_MEDIANA*100:.0f}% (sesgo sistematico => problema de datum)"
            )
    else:
        r["checks"]["superficie"] = {"con_declarada": 0, "sin_declarada": sin_area}

    # Several geometries per expediente is LEGITIMATE (one mina, many
    # pertenencias). Two failure modes have to be told apart here:
    #   - same source_fid twice  => OUR pagination repeated a page. A real bug.
    #   - distinct source_fids, identical content => the province's own view
    #     fans out (San Juan's vw_minas_padron does this). Not our bug; already
    #     collapsed by build.dedupe(), so anything surviving means dedupe missed
    #     a case and is worth failing on.
    repetidos = {k: v for k, v in huellas.items() if v > 1}
    fid_repetido = sum(1 for k, v in repetidos.items() if len(ids_por_huella[k]) < v)
    r["checks"]["duplicados"] = {
        "expedientes_repetidos": sum(1 for v in expedientes.values() if v > 1),
        "geometrias_por_expediente_max": max(expedientes.values()) if expedientes else 0,
        "grupos_identicos_restantes": len(repetidos),
        "source_fid_repetido": fid_repetido,
    }
    if fid_repetido:
        r["fallas"].append(
            f"{fid_repetido} grupos con el mismo source_fid repetido => "
            f"bug de paginacion propio"
        )
    if repetidos:
        r["fallas"].append(
            f"{len(repetidos)} grupos identicos sobrevivieron a dedupe() "
            f"(mismo layer, expediente y geometria)"
        )

    # 5. overlaps — reported, never fatal.
    r["checks"]["superposiciones"] = _superposiciones(feats, geoms)

    # 6. coverage plausibility. Also the headline statistic, so it must be right.
    km2 = AREA_PROV_KM2.get(provincia)
    if km2:
        pct = 100.0 * (ha_total / 100.0) / km2
        r["checks"]["cobertura"] = {
            "ha_total": round(ha_total, 1),
            "pct_provincia": round(pct, 2),
        }
        if pct > 100.0:
            r["fallas"].append(
                f"superficie titulada = {pct:.0f}% de la provincia (>100%): "
                f"superposiciones masivas o error de CRS"
            )
    return r


def _superposiciones(feats: list[dict], geoms: list) -> dict:
    """Classify overlapping pairs.

    cateo ∩ mina is normal — a mina is granted inside a prior exploration
    permit. mina ∩ mina between DIFFERENT holders is a genuine anomaly and the
    kind of thing worth a headline, so it is counted separately.
    """
    if len(geoms) < 2:
        return {}
    tree = STRtree(geoms)
    pares = Counter()
    conflicto = []
    for i, g in enumerate(geoms):
        for j in tree.query(g):
            if j <= i:
                continue
            h = geoms[j]
            if not g.intersects(h):
                continue
            inter = g.intersection(h).area
            if inter <= 0:
                continue
            pa = feats[i].get("properties") or {}
            pb = feats[j].get("properties") or {}
            par = tuple(sorted((pa.get("tipo", "?"), pb.get("tipo", "?"))))
            pares[par] += 1
            if (
                pa.get("tipo") == "mina" and pb.get("tipo") == "mina"
                and pa.get("titular_norm") and pb.get("titular_norm")
                and pa["titular_norm"] != pb["titular_norm"]
                # ignore slivers: >10% of the smaller parcel
                and inter > 0.1 * min(g.area, h.area)
            ):
                conflicto.append([pa.get("id"), pb.get("id")])
    return {
        "pares_por_tipo": {f"{a}|{b}": n for (a, b), n in pares.most_common(10)},
        "mina_mina_distinto_titular": len(conflicto),
        "ejemplos": conflicto[:5],
    }


def diff_previo(actual: dict) -> dict:
    """Compare against the previous run — the most important guard.

    A cadastre does not lose 10% of its tenements in a week. A swing that large
    means the endpoint or the pagination changed, and publishing it would be
    worse than failing.
    """
    path = os.path.join(DATA, "calidad.json")
    if not os.path.exists(path):
        return {"primera_corrida": True}
    try:
        with open(path, encoding="utf-8") as f:
            prev = (json.load(f).get("data") or {}).get("provincias") or []
    except Exception:  # noqa: BLE001
        return {"previo_ilegible": True}

    antes = {p["provincia"]: p.get("n", 0) for p in prev}
    out, fallas = {}, []
    for p in actual["provincias"]:
        a, b = antes.get(p["provincia"]), p["n"]
        if a is None or a == 0:
            continue
        delta = 100.0 * (b - a) / a
        out[p["provincia"]] = {"antes": a, "ahora": b, "delta_pct": round(delta, 2)}
        if abs(delta) > MAX_DIFF_PCT:
            fallas.append(
                f"{p['provincia']}: {a} -> {b} features ({delta:+.1f}%), "
                f"supera +/-{MAX_DIFF_PCT}%"
            )
    return {"por_provincia": out, "fallas": fallas}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="no bloquear el deploy")
    args = ap.parse_args()

    from _meta import write_json

    bounds = provincia_bounds()
    if not bounds:
        print("  [aviso] falta public/data/provincias.geojson: se omite el "
              "chequeo de contencion provincial (solo se valida el bbox nacional)")

    provs = [p for p in F.provincias()]
    reportes = [revisar(p, bounds) for p in provs]

    payload = {"provincias": reportes}
    d = diff_previo(payload)
    payload["diff_corrida_previa"] = d

    fallas = [(r["provincia"], f) for r in reportes for f in r["fallas"]]
    fallas += [("diff", f) for f in d.get("fallas", [])]

    for r in reportes:
        c = r["checks"]
        if c.get("sin_datos"):
            print(f"[{r['provincia']}] sin datos")
            continue
        sup = c.get("superficie", {})
        print(
            f"[{r['provincia']}] n={r['n']} "
            f"invalidas={c['geometria']['pct']}% "
            f"fuera={c['ubicacion']['pct']}% "
            f"delta_med={sup.get('delta_mediana_pct', '-')}% "
            f"cobertura={c.get('cobertura', {}).get('pct_provincia', '-')}%"
        )

    write_json(os.path.join(DATA, "calidad.json"), payload, source="validate.py")

    if fallas:
        print("\nFALLAS:")
        for prov, f in fallas:
            print(f"  [{prov}] {f}")
        if not args.report:
            return 1
    else:
        print("\nSin fallas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
