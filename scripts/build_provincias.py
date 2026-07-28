"""Province outlines in EPSG:4326, for the map and the containment check.

Source is the copy already in estado-del-sistema, which is derived from
jazzido/Polymaps-Argentina and simplified at 0.02 degrees (~2 km). That project
stores it in EPSG:3857 because it hand-rolls a Mercator SVG projection; Leaflet
and every check in validate.py want lon/lat, so it is reprojected once here
rather than converted on every read.

Simplification note: ~2 km is far coarser than any cadastral parcel, so these
outlines are for context and for a 5 km-tolerance containment test only. They
must never be used to clip or to compute areas.

Usage:
    python scripts/build_provincias.py [ruta/al/provincias.geojson]
"""

import json
import os
import sys

from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SRC = os.path.join(
    os.path.dirname(ROOT), "estado-del-sistema", "public", "data", "provincias.geojson"
)
DST = os.path.join(ROOT, "public", "data", "provincias.geojson")

_TF = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def walk(coords):
    if coords and isinstance(coords[0], (int, float)):
        lon, lat = _TF.transform(coords[0], coords[1])
        return [round(lon, 5), round(lat, 5)]
    return [walk(c) for c in coords]


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.exists(src):
        print(f"no existe: {src}", file=sys.stderr)
        return 1

    with open(src, encoding="utf-8") as f:
        gj = json.load(f)

    for feat in gj.get("features") or []:
        feat["geometry"]["coordinates"] = walk(feat["geometry"]["coordinates"])

    gj["metadata"] = {
        "crs": "EPSG:4326",
        "origen": "jazzido/Polymaps-Argentina via estado-del-sistema",
        "simplificacion_grados": 0.02,
        "aviso": "Contorno de contexto (~2 km). No usar para recortar ni medir superficies.",
    }
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

    n = len(gj.get("features") or [])
    sample = gj["features"][0]["geometry"]["coordinates"]
    while isinstance(sample, list) and sample and isinstance(sample[0], list):
        sample = sample[0]
    print(f"{n} provincias -> {DST}")
    print(f"  muestra lon/lat: {sample}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
