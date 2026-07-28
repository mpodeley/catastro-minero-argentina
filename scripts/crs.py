"""Coordinate reference system handling for Argentine cadastral data.

Argentine cadastres are surveyed in Gauss-Kruger fajas (7 north-south bands).
Four datum families are in active use, all verified against pyproj on
2026-07-28 rather than assumed:

  * POSGAR 2007     — EPSG:5343-5349    (San Juan uses 5344, faja 2)
  * POSGAR 98       — EPSG:22171-22177  (Cordoba uses 22173, faja 3)
  * POSGAR 94       — EPSG:22181-22187
  * Campo Inchauspe — EPSG:22191-22197

The three POSGAR realisations are all WGS84-aligned to within roughly a metre,
so confusing them is survivable. Campo Inchauspe is a genuinely different datum
— mistaking it for POSGAR shifts geometry by ~100-200 m, which is far too little
for the province-containment check in validate.py to catch and far too much for
a parcel boundary.

The 2217x/2218x/2219x codes are adjacent and easy to transpose by eye, so every
EPSG is resolved through pyproj at build time and its datum logged: a surprise
shows up in CI output instead of silently shipping.

Operating rule: prefer server-side reprojection (`&srsName=EPSG:4326`, verified
working on San Juan's GeoServer) over doing the math here. This module is for
file-based sources that have no server to ask.
"""

import functools
from typing import Optional

from pyproj import CRS, Transformer

WGS84 = 4326

# Faja -> EPSG, by datum family. Verified against pyproj, not from memory.
POSGAR_2007 = {1: 5343, 2: 5344, 3: 5345, 4: 5346, 5: 5347, 6: 5348, 7: 5349}
POSGAR_98 = {1: 22171, 2: 22172, 3: 22173, 4: 22174, 5: 22175, 6: 22176, 7: 22177}
POSGAR_94 = {1: 22181, 2: 22182, 3: 22183, 4: 22184, 5: 22185, 6: 22186, 7: 22187}
CAMPO_INCHAUSPE = {1: 22191, 2: 22192, 3: 22193, 4: 22194, 5: 22195, 6: 22196, 7: 22197}

# Datums that are WGS84-aligned to ~1 m. A mix-up among these is a nuisance;
# a mix-up with Campo Inchauspe is a ~150 m error.
FAMILIAS_POSGAR = ("posgar2007", "posgar98", "posgar94")

# Rough national bounds, used as a cheap sanity gate on reprojected output.
AR_BBOX = (-74.0, -56.0, -53.0, -21.0)  # minlon, minlat, maxlon, maxlat


def faja_from_easting(easting: float) -> Optional[int]:
    """Recover the Gauss-Kruger faja from an easting.

    Argentine fajas use a false easting of faja*1_000_000 + 500_000, so the
    leading digit of the easting *is* the faja number. Salta's 3_498_590 -> 3;
    San Juan's 2_364_782 -> 2, consistent with its declared EPSG:5344.
    """
    try:
        e = float(easting)
    except (TypeError, ValueError):
        return None
    if not (1_000_000 <= e < 8_000_000):
        return None
    return int(e // 1_000_000)


def epsg_for_faja(faja: int, familia: str = "posgar2007") -> int:
    tabla = {
        "posgar2007": POSGAR_2007,
        "posgar98": POSGAR_98,
        "posgar94": POSGAR_94,
        "campo_inchauspe": CAMPO_INCHAUSPE,
    }[familia]
    if faja not in tabla:
        raise ValueError(f"faja fuera de rango 1-7: {faja}")
    return tabla[faja]


@functools.lru_cache(maxsize=64)
def describe(epsg: int) -> dict:
    """Resolve an EPSG through pyproj and report what it actually is.

    Called once per source at build time; the result is logged so that a datum
    surprise (Cordoba's Campo Inchauspe) is visible rather than assumed.
    """
    crs = CRS.from_epsg(epsg)
    datum = crs.datum
    return {
        "epsg": epsg,
        "name": crs.name,
        "datum": datum.name if datum else None,
        "unit": crs.axis_info[0].unit_name if crs.axis_info else None,
        "is_geographic": crs.is_geographic,
    }


@functools.lru_cache(maxsize=64)
def _transformer(src_epsg: int, dst_epsg: int) -> Transformer:
    # always_xy keeps everything in (lon, lat) / (easting, northing) order,
    # which is what GeoJSON expects and what avoids the classic swapped-axis bug.
    return Transformer.from_crs(
        CRS.from_epsg(src_epsg), CRS.from_epsg(dst_epsg), always_xy=True
    )


def reproject_geom(geom: dict, src_epsg: int, dst_epsg: int = WGS84) -> dict:
    """Reproject a GeoJSON geometry between EPSG codes.

    Pure coordinate walk — no shapely round-trip, so degenerate rings survive
    to be caught and reported by validate.py rather than being silently dropped.
    """
    if src_epsg == dst_epsg:
        return geom
    tf = _transformer(src_epsg, dst_epsg)

    def walk(coords, depth):
        if depth == 0:
            x, y = tf.transform(coords[0], coords[1])
            return [x, y]
        return [walk(c, depth - 1) for c in coords]

    depth = {
        "Point": 0, "LineString": 1, "MultiPoint": 1,
        "Polygon": 2, "MultiLineString": 2, "MultiPolygon": 3,
    }.get(geom["type"])
    if depth is None:
        raise ValueError(f"tipo de geometria no soportado: {geom['type']}")

    return {"type": geom["type"], "coordinates": walk(geom["coordinates"], depth)}


def looks_like_projected(geom: dict) -> bool:
    """True when coordinates are metres, not degrees.

    Guards against a source that declares EPSG:4326 and serves Gauss-Kruger
    anyway — which is exactly what Salta's `coordenadas` column contains.
    """
    c = geom.get("coordinates")
    while isinstance(c, list) and c and isinstance(c[0], list):
        c = c[0]
    if not isinstance(c, list) or len(c) < 2:
        return False
    return abs(float(c[0])) > 180.0 or abs(float(c[1])) > 90.0


def in_argentina(lon: float, lat: float, tol_deg: float = 0.5) -> bool:
    minlon, minlat, maxlon, maxlat = AR_BBOX
    return (
        minlon - tol_deg <= lon <= maxlon + tol_deg
        and minlat - tol_deg <= lat <= maxlat + tol_deg
    )


def parse_gk_wkt(wkt: str) -> Optional[dict]:
    """Parse the MULTIPOLYGON WKT that Salta ships in its `coordenadas` column.

    That column is the original Gauss-Kruger survey, i.e. a second, independent
    representation of the same parcel. It is used only by the CRS round-trip
    test — comparing it against the served EPSG:4326 geometry validates this
    whole module against real data, which is a rare gift.

    Deliberately minimal: handles the MULTIPOLYGON(((x y, ...))) form these
    sources emit, and returns None on anything else rather than guessing.
    """
    s = (wkt or "").strip()
    if not s.upper().startswith("MULTIPOLYGON"):
        return None
    body = s[s.index("(") : ].strip()

    def nums(chunk: str) -> list[list[float]]:
        pts = []
        for pair in chunk.split(","):
            parts = pair.split()
            if len(parts) >= 2:
                pts.append([float(parts[0]), float(parts[1])])
        return pts

    polys, depth, buf, rings = [], 0, "", []
    for ch in body:
        if ch == "(":
            depth += 1
            if depth == 3:
                buf = ""
            continue
        if ch == ")":
            if depth == 3:
                rings.append(nums(buf))
            elif depth == 2:
                polys.append(rings)
                rings = []
            depth -= 1
            continue
        if depth == 3:
            buf += ch
    return {"type": "MultiPolygon", "coordinates": polys} if polys else None
