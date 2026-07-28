"""Daily drift detector. Probes every source without downloading anything.

Provincial endpoints move, and the national index of them is already stale.
This runs ~15 cheap requests, diffs the result against the last known probe in
public/data/cobertura.json, and reports what changed. It is deliberately
separate from build.py so the expensive weekly refresh does not have to run
just to notice that an endpoint died.

Exit codes: 0 sin cambios · 2 hay deriva (el workflow abre/actualiza un issue).

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --json    # machine-readable, for the workflow
"""

import argparse
import json
import os
import sys

import fuentes as F
from _meta import write_json
from adapters import build_adapter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "public", "data")

# A count that moves more than this without an announced republish means the
# endpoint or the pagination changed, not the cadastre.
UMBRAL_PCT = 10.0
# A source whose bytes have not changed in this long is frozen, not stable.
DIAS_ESTANCADA = 180


def previos() -> dict:
    path = os.path.join(DATA, "cobertura.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for prov in (doc.get("data") or {}).get("provincias") or []:
        for src in prov.get("fuentes") or []:
            out[src["fuente_id"]] = src
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    antes = previos()
    filas, derivas = [], []

    for f in F.FUENTES:
        try:
            a = build_adapter(f)
        except NotImplementedError:
            filas.append({"fuente_id": f.id, "estado": "no_implementada"})
            continue

        p = a.probe()
        fila = p.to_dict()
        prev = antes.get(f.id, {})
        fila["estado"] = "ok" if p.ok else "caida"

        if not p.ok:
            derivas.append(f"**{f.id}**: no responde — `{p.error}`")
        else:
            # count swing
            n_antes = prev.get("features_fuente", prev.get("features"))
            if isinstance(n_antes, int) and n_antes > 0 and p.feature_count:
                delta = 100.0 * (p.feature_count - n_antes) / n_antes
                fila["delta_pct"] = round(delta, 2)
                if abs(delta) > UMBRAL_PCT:
                    derivas.append(
                        f"**{f.id}**: features {n_antes} → {p.feature_count} "
                        f"({delta:+.1f}%), supera ±{UMBRAL_PCT:.0f}%"
                    )
            # file sources: size is the drift signal, since counting features
            # would mean downloading the whole payload
            b_antes, b_ahora = prev.get("bytes"), fila.get("bytes")
            if isinstance(b_antes, int) and b_antes > 0 and b_ahora:
                d = 100.0 * (b_ahora - b_antes) / b_antes
                if abs(d) > UMBRAL_PCT:
                    derivas.append(
                        f"**{f.id}**: el archivo pasó de {b_antes} a {b_ahora} bytes "
                        f"({d:+.1f}%)"
                    )
            # versioned layer adopted a new name
            if prev.get("resolved_layer") and p.resolved_layer and p.resolved_layer != prev["resolved_layer"]:
                derivas.append(
                    f"**{f.id}**: la capa cambió de `{prev['resolved_layer']}` "
                    f"a `{p.resolved_layer}` (adoptada automáticamente vía layer_pattern)"
                )
            # schema change
            if f.kind == "wfs" and p.field_names:
                prev_fields = prev.get("field_names")
                if prev_fields and set(prev_fields) != set(p.field_names):
                    faltan = sorted(set(prev_fields) - set(p.field_names))
                    nuevos = sorted(set(p.field_names) - set(prev_fields))
                    derivas.append(
                        f"**{f.id}**: cambió el esquema — faltan {faltan}, nuevos {nuevos}"
                    )

        filas.append(fila)
        print(
            f"[{'ok ' if p.ok else 'ERR'}] {f.id:<48} "
            f"n={p.feature_count if p.feature_count is not None else '-':<8} "
            f"{p.elapsed_ms or '-'}ms"
        )

    write_json(
        os.path.join(DATA, "health.json"),
        {"probes": filas, "derivas": derivas, "umbral_pct": UMBRAL_PCT},
        source="health_check.py",
    )

    if args.json:
        print(json.dumps({"derivas": derivas}, ensure_ascii=False))

    if derivas:
        print("\nDERIVA DETECTADA:")
        for d in derivas:
            print(f"  - {d}")
        return 2
    print("\nSin deriva.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
