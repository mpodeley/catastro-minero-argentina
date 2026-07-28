"""Rollups: the national titular index and the province-level choropleth.

Two outputs, both small enough to always load:

  titulares.json     one row per normalized holder, so the whole country is
                     searchable without downloading any geometry
  provincias_agg.json  per-province totals joined onto provincias.geojson

Departamento-level aggregation is emitted as a table only. IGN departamento
boundaries are not vendored yet, so there is no geometry to colour; publishing
the numbers without the polygons is better than inventing either.

Privacy: `titular` is frequently a natural person. The cadastre is a public
registry so each individual stays visible in their own feature popup, but this
file — which is what powers a public ranking — aggregates natural persons into
a count instead of naming them. See normalize.titular_es_persona.
"""

import json
import os
import sys
from collections import Counter, defaultdict

from _meta import write_json
import fuentes as F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "public", "data")
TEN = os.path.join(DATA, "tenencias")

TOP_N = 25


def cargar(provincia: str) -> list[dict]:
    path = os.path.join(TEN, f"{provincia}.geojson")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [x["properties"] for x in json.load(f).get("features") or []]


def main() -> int:
    provs = F.provincias()
    todos: list[dict] = []
    for p in provs:
        todos.extend(cargar(p))
    if not todos:
        print("sin datos; correr build.py primero", file=sys.stderr)
        return 1

    # --- titulares -----------------------------------------------------------
    acc: dict[str, dict] = {}
    for d in todos:
        key = d.get("titular_norm")
        if not key:
            continue
        e = acc.setdefault(key, {
            "titular_norm": key,
            "nombre": d.get("titular"),
            "es_persona": d.get("titular_es_persona"),
            "n_derechos": 0,
            "ha": 0.0,
            "provincias": set(),
            "minerales": Counter(),
            "tipos": Counter(),
        })
        e["n_derechos"] += 1
        e["ha"] += d.get("superficie_ha_calc") or 0.0
        e["provincias"].add(d["provincia"])
        e["minerales"].update(d.get("mineral") or [])
        e["tipos"][d.get("tipo")] += 1

    titulares = [
        {
            "titular_norm": e["titular_norm"],
            "nombre": e["nombre"],
            "es_persona": bool(e["es_persona"]),
            "n_derechos": e["n_derechos"],
            "ha": round(e["ha"], 1),
            "provincias": sorted(e["provincias"]),
            "minerales": [m for m, _ in e["minerales"].most_common(6)],
            "tipos": dict(e["tipos"]),
        }
        for e in acc.values()
    ]
    titulares.sort(key=lambda x: (-x["ha"], -x["n_derechos"]))

    empresas = [t for t in titulares if not t["es_persona"]]
    personas = [t for t in titulares if t["es_persona"]]

    write_json(
        os.path.join(DATA, "titulares.json"),
        {
            "titulares": titulares,
            "top_empresas": empresas[:TOP_N],
            "resumen": {
                "n_titulares": len(titulares),
                "n_empresas": len(empresas),
                "n_personas_fisicas": len(personas),
                "ha_empresas": round(sum(t["ha"] for t in empresas), 1),
                "ha_personas_fisicas": round(sum(t["ha"] for t in personas), 1),
                "derechos_sin_titular": sum(1 for d in todos if not d.get("titular_norm")),
                "aviso": (
                    "El ranking lista empresas por nombre y agrega a las personas "
                    "fisicas en un conteo. Es un ranking de lo PUBLICADO: las "
                    "provincias difieren en si informan titular, y los cateos de "
                    "San Juan no lo informan."
                ),
            },
        },
        source="catastros mineros provinciales",
    )

    # --- province rollup -----------------------------------------------------
    por_prov: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "ha": 0.0, "tipos": Counter(), "minerales": Counter(),
        "estados": Counter(), "titulares": set(), "con_titular": 0,
    })
    for d in todos:
        e = por_prov[d["provincia"]]
        e["n"] += 1
        e["ha"] += d.get("superficie_ha_calc") or 0.0
        e["tipos"][d.get("tipo")] += 1
        e["estados"][d.get("estado")] += 1
        e["minerales"].update(d.get("mineral") or [])
        if d.get("titular_norm"):
            e["titulares"].add(d["titular_norm"])
            e["con_titular"] += 1

    from validate import AREA_PROV_KM2

    agg = {}
    for prov, e in por_prov.items():
        km2 = AREA_PROV_KM2.get(prov)
        agg[prov] = {
            "n_derechos": e["n"],
            "ha": round(e["ha"], 1),
            "pct_provincia": round(100.0 * (e["ha"] / 100.0) / km2, 2) if km2 else None,
            "n_titulares": len(e["titulares"]),
            "pct_con_titular": round(100.0 * e["con_titular"] / e["n"], 1) if e["n"] else 0,
            "tipos": dict(e["tipos"].most_common()),
            "estados": dict(e["estados"].most_common()),
            "mineral_dominante": e["minerales"].most_common(1)[0][0] if e["minerales"] else None,
            "minerales": dict(e["minerales"].most_common(10)),
            "cobertura": "completa",
        }
    # Absence is a first-class value: a province that publishes nothing must
    # never render as zero on a ramp.
    for prov, motivo in F.SIN_DATOS_ABIERTOS.items():
        agg[prov] = {"cobertura": "sin_datos", "motivo": motivo, "n_derechos": None}
    for prov in provs:
        if prov not in agg:
            agg[prov] = {"cobertura": "declarada_no_implementada", "n_derechos": None}

    # --- departamento table (no geometry available) --------------------------
    por_depto: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "ha": 0.0, "minerales": Counter()})
    for d in todos:
        if not d.get("departamento"):
            continue
        e = por_depto[(d["provincia"], d["departamento"])]
        e["n"] += 1
        e["ha"] += d.get("superficie_ha_calc") or 0.0
        e["minerales"].update(d.get("mineral") or [])
    deptos = [
        {
            "provincia": prov, "departamento": dep, "n_derechos": e["n"],
            "ha": round(e["ha"], 1),
            "mineral_dominante": e["minerales"].most_common(1)[0][0] if e["minerales"] else None,
        }
        for (prov, dep), e in por_depto.items()
    ]
    deptos.sort(key=lambda x: -x["ha"])

    write_json(
        os.path.join(DATA, "agregados.json"),
        {
            "provincias": agg,
            "departamentos": deptos,
            "totales": {
                "n_derechos": len(todos),
                "ha": round(sum(d.get("superficie_ha_calc") or 0 for d in todos), 1),
                "n_provincias_con_datos": len(por_prov),
                "n_titulares": len(titulares),
            },
            "nota_departamentos": (
                "Tabla sin geometria: no se vendorizan aun los limites "
                "departamentales del IGN. Los nombres vienen tal cual los "
                "publica cada provincia y no estan normalizados contra INDEC."
            ),
        },
        source="catastros mineros provinciales",
    )

    print(f"titulares: {len(titulares)} ({len(empresas)} empresas, {len(personas)} personas)")
    print(f"departamentos: {len(deptos)}")
    print("\ntop 8 por hectareas (empresas):")
    for t in empresas[:8]:
        print(f"  {t['ha']:>12,.0f} ha  {t['n_derechos']:>4} derechos  "
              f"{t['nombre'][:44]:<44} {','.join(t['provincias'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
