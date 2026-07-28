"""Informe de Posición Territorial — the sellable deliverable.

Answers, for one title holder, the questions a provincial viewer cannot:

  * how much ground do I actually hold (union, not sum)
  * WHO is around me, and how much do they hold
  * what is still open next to my position
  * where do I overlap a third party
  * where did every one of these numbers come from, and as of when

The land layer is the part of this project that needs no geological
interpretation to be true: it is public-registry fact, verifiable against the
cited source URL. That is deliberately what this report sells.

Usage:
    python scripts/informe.py --titular "HANAQ"
    python scripts/informe.py --titular "MINERA ANGLO AMERICAN" --radio-km 15
    python scripts/informe.py --listar            # holders worth reporting on
"""

import argparse
import csv
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pyproj import CRS, Geod, Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

import fuentes as F
import normalize as N

# Human labels; the schema slugs are for joins, not for a client deliverable.
LABEL_TIPO = {
    "cateo": "cateo", "mina": "mina",
    "manifestacion_descubrimiento": "manif. de descubrimiento",
    "cantera": "cantera", "servidumbre": "servidumbre",
    "solicitud": "solicitud", "planta": "planta",
    "area_proteccion": "área de protección", "otro": "otro",
}
LABEL_ESTADO = {
    "vigente": "vigente", "tramite": "en trámite", "caduco": "caduco",
    "desistido": "desistido", "vacante": "vacante", "desconocido": "sin dato",
}
SIN_TITULAR = "(sin titular publicado)"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "public", "data")
TEN = os.path.join(DATA, "tenencias")
OUT = os.path.join(ROOT, "informes")

_GEOD = Geod(ellps="WGS84")
RADIO_KM = 10.0


# --- geometry helpers --------------------------------------------------------


def _local_crs(geom):
    """Azimuthal-equidistant CRS centred on the geometry.

    Buffering in degrees is wrong at these latitudes (1 degree of longitude is
    ~103 km at -22 and ~93 km at -33), so distances are computed in a local
    projection instead of with a fudge factor.
    """
    c = geom.centroid
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def buffer_km(geom, km: float):
    crs = _local_crs(geom)
    fwd = Transformer.from_crs(CRS.from_epsg(4326), crs, always_xy=True).transform
    inv = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True).transform
    return transform(inv, transform(fwd, geom).buffer(km * 1000.0))


def area_ha(geom) -> float:
    if geom.is_empty:
        return 0.0
    a, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(a) / 1e4


def safe(geom):
    return geom if geom.is_valid else make_valid(geom)


# --- data --------------------------------------------------------------------


def cargar_todo() -> list[dict]:
    """Every polygon tenement, with its shapely geometry attached."""
    out = []
    for prov in F.provincias():
        path = os.path.join(TEN, f"{prov}.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for feat in json.load(f).get("features") or []:
                try:
                    g = safe(shape(feat["geometry"]))
                except Exception:  # noqa: BLE001
                    continue
                if g.is_empty:
                    continue
                out.append({"p": feat["properties"], "g": g})
    return out


def buscar_titular(todos: list[dict], consulta: str) -> tuple[str, list[dict]]:
    """Match a holder by normalized substring. Returns (display name, records)."""
    q = N.norm_titular(consulta) or consulta.upper()
    cand = defaultdict(list)
    for r in todos:
        tn = r["p"].get("titular_norm")
        if tn and q in tn:
            cand[tn].append(r)
    if not cand:
        raise SystemExit(f"sin coincidencias para {consulta!r}")
    # Prefer the holder with most ground, and warn if the match was ambiguous.
    mejor = max(cand.items(), key=lambda kv: sum(area_ha(r["g"]) for r in kv[1]))
    if len(cand) > 1:
        otros = sorted(cand.keys(), key=lambda k: -len(cand[k]))[:5]
        print(f"  [aviso] {len(cand)} titulares matchean {consulta!r}: {otros}")
        print(f"          se usa {mejor[0]!r}; afiná la consulta si no es el correcto.")
    nombre = mejor[1][0]["p"].get("titular") or mejor[0]
    return nombre, mejor[1]


# --- analysis ----------------------------------------------------------------


def analizar(todos: list[dict], mios: list[dict], radio_km: float) -> dict:
    mi_union = unary_union([r["g"] for r in mios])
    zona = buffer_km(mi_union, radio_km)

    arbol = STRtree([r["g"] for r in todos])
    ids_mios = {id(r["g"]) for r in mios}

    vecinos_rec, solapes = [], []
    for idx in arbol.query(zona):
        r = todos[idx]
        if id(r["g"]) in ids_mios:
            continue
        if not r["g"].intersects(zona):
            continue
        vecinos_rec.append(r)
        # Third-party overlap with the client's own ground.
        if r["g"].intersects(mi_union):
            inter = r["g"].intersection(mi_union)
            a = area_ha(inter)
            if a > 1.0:  # ignore slivers under a hectare
                solapes.append({
                    "titular": r["p"].get("titular") or SIN_TITULAR,
                    "nombre": r["p"].get("nombre"),
                    "tipo": r["p"].get("tipo"),
                    "expediente": r["p"].get("expediente"),
                    "provincia": r["p"].get("provincia_nombre"),
                    "ha": round(a, 1),
                })

    # Open ground = the search ring minus everything anyone holds in it.
    ocupado = unary_union([r["g"] for r in vecinos_rec] + [mi_union]) if vecinos_rec else mi_union
    anillo = zona.difference(mi_union)
    libre = anillo.difference(ocupado)

    por_vecino = defaultdict(lambda: {"n": 0, "geoms": [], "tipos": Counter(),
                                      "min": Counter(), "provs": set()})
    for r in vecinos_rec:
        p = r["p"]
        key = p.get("titular") or SIN_TITULAR
        e = por_vecino[key]
        e["n"] += 1
        e["geoms"].append(r["g"])
        e["tipos"][p.get("tipo")] += 1
        e["min"].update(p.get("mineral") or [])
        e["provs"].add(p.get("provincia_nombre"))

    vecinos = sorted(
        (
            {
                "titular": k,
                "n": v["n"],
                "ha": round(area_ha(unary_union(v["geoms"])), 1),
                "tipos": dict(v["tipos"].most_common()),
                "minerales": [m for m, _ in v["min"].most_common(4)],
                "provincias": sorted(x for x in v["provs"] if x),
            }
            for k, v in por_vecino.items()
        ),
        key=lambda x: -x["ha"],
    )

    sin_tit = next((v for v in vecinos if v["titular"] == SIN_TITULAR), None)
    vecinos = [v for v in vecinos if v["titular"] != SIN_TITULAR]

    return {
        "sin_titular": sin_tit,
        "mi_union": mi_union,
        "zona": zona,
        "libre": libre,
        "ha_propia": round(area_ha(mi_union), 1),
        "ha_suma": round(sum(r["p"].get("superficie_ha_calc") or 0 for r in mios), 1),
        "ha_libre": round(area_ha(libre), 1),
        "ha_zona": round(area_ha(zona), 1),
        "vecinos": vecinos,
        "solapes": sorted(solapes, key=lambda x: -x["ha"]),
        "n_vecinos_derechos": len(vecinos_rec),
    }


def perfil(mios: list[dict]) -> dict:
    tipos, estados, minerales, provs, deptos = Counter(), Counter(), Counter(), Counter(), Counter()
    fechas = []
    for r in mios:
        p = r["p"]
        tipos[p.get("tipo")] += 1
        estados[p.get("estado")] += 1
        minerales.update(p.get("mineral") or [])
        provs[p.get("provincia_nombre")] += 1
        if p.get("departamento"):
            deptos[p["departamento"]] += 1
        for k in ("fecha_inicio", "fecha_inscripcion", "fecha_mensura"):
            if p.get(k):
                fechas.append(p[k])
    return {
        "tipos": dict(tipos.most_common()), "estados": dict(estados.most_common()),
        "minerales": dict(minerales.most_common(8)), "provincias": dict(provs.most_common()),
        "departamentos": dict(deptos.most_common(8)),
        "con_fecha": len(fechas), "fecha_min": min(fechas) if fechas else None,
        "fecha_max": max(fechas) if fechas else None,
    }


# --- output ------------------------------------------------------------------


def escribir_csv(path: str, mios: list[dict]) -> None:
    campos = ["provincia_nombre", "tipo", "estado", "nombre", "expediente",
              "mineral", "superficie_ha", "superficie_ha_calc", "departamento",
              "fecha_inicio", "fuente_id", "source_layer", "fetched_at", "source_url"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in sorted(mios, key=lambda r: -(r["p"].get("superficie_ha_calc") or 0)):
            row = dict(r["p"])
            row["mineral"] = " ".join(row.get("mineral") or [])
            w.writerow(row)


def escribir_geojson(path: str, a: dict, mios: list[dict]) -> None:
    feats = [{"type": "Feature", "properties": {**r["p"], "capa": "propio"},
              "geometry": mapping(r["g"])} for r in mios]
    if not a["libre"].is_empty:
        feats.append({"type": "Feature",
                      "properties": {"capa": "terreno_libre", "ha": a["ha_libre"]},
                      "geometry": mapping(a["libre"])})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)


def fuentes_citadas(mios: list[dict]) -> list[dict]:
    vistas = {}
    for r in mios:
        p = r["p"]
        vistas.setdefault(p["fuente_id"], {
            "fuente_id": p["fuente_id"], "capa": p.get("source_layer"),
            "srid": p.get("source_srid"), "fetched_at": p.get("fetched_at"),
            "licencia": p.get("licencia"), "url": p.get("source_url"), "n": 0,
        })
        vistas[p["fuente_id"]]["n"] += 1
    return sorted(vistas.values(), key=lambda x: -x["n"])


def _bloque_sin_titular(a: dict) -> str:
    v = a.get("sin_titular")
    if not v:
        return ""
    return (
        '<div class="nota limite">Además, <b>{n} derechos</b> del anillo '
        '({ha:,.0f} ha) no tienen titular publicado por su provincia. '
        'Tienen dueño — lo que falta es el dato. San Juan, por ejemplo, no '
        'publica el titular de ningún cateo.</div>'
    ).format(n=v["n"], ha=v["ha"])


def render_html(nombre: str, a: dict, pf: dict, mios: list[dict], radio_km: float) -> str:
    e = html.escape
    hoy = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    def fila_tipos(d, labels=None):
        lb = labels or {}
        return " · ".join(f"{lb.get(k, k)}: {v}" for k, v in d.items()) or "—"

    vecinos_rows = "".join(
        f"<tr><td>{e(v['titular'])}</td><td class=n>{v['ha']:,.0f}</td>"
        f"<td class=n>{v['n']}</td><td>{e(fila_tipos(v['tipos']))}</td>"
        f"<td>{e(' '.join(v['minerales']))}</td></tr>"
        for v in a["vecinos"][:30]
    )
    solape_rows = "".join(
        f"<tr><td>{e(s['titular'])}</td><td>{e(s['nombre'] or '—')}</td>"
        f"<td>{e(LABEL_TIPO.get(s['tipo'], s['tipo'] or ''))}</td><td>{e(s['expediente'] or '—')}</td>"
        f"<td class=n>{s['ha']:,.1f}</td></tr>"
        for s in a["solapes"][:25]
    ) or '<tr><td colspan=5 class=vacio>Sin superposiciones de terceros sobre la posición.</td></tr>'
    fuente_rows = "".join(
        f"<tr><td>{e(f['fuente_id'])}</td><td>{e(str(f['capa']))}</td>"
        f"<td class=n>{f['n']}</td><td>EPSG:{f['srid']}</td>"
        f"<td>{e((f['fetched_at'] or '')[:10])}</td><td>{e(f['licencia'] or '')}</td></tr>"
        for f in fuentes_citadas(mios)
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Posición territorial — {e(nombre)}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font: 11pt/1.5 "Georgia", serif; color: #1a1a1a; max-width: 190mm; margin: 0 auto; }}
  h1 {{ font-size: 19pt; margin: 0 0 2mm; letter-spacing: -.2pt; }}
  h2 {{ font-size: 12pt; margin: 9mm 0 2mm; padding-bottom: 1mm;
        border-bottom: 1px solid #ccc; text-transform: uppercase;
        letter-spacing: .8pt; font-family: system-ui, sans-serif; }}
  .sub {{ color: #666; font-size: 10pt; margin: 0 0 6mm; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 9.5pt;
           font-family: system-ui, sans-serif; margin: 3mm 0; }}
  th {{ text-align: left; border-bottom: 1.5px solid #333; padding: 1.5mm 2mm;
        font-size: 8pt; text-transform: uppercase; letter-spacing: .5pt; color: #555; }}
  td {{ border-bottom: .5px solid #e0e0e0; padding: 1.5mm 2mm; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .vacio {{ color: #888; font-style: italic; }}
  .kpis {{ display: flex; gap: 8mm; margin: 5mm 0; }}
  .kpi b {{ display: block; font-size: 17pt; font-family: system-ui, sans-serif; }}
  .kpi span {{ font-size: 8.5pt; color: #666; text-transform: uppercase; letter-spacing: .5pt; }}
  .nota {{ background: #f6f6f4; border-left: 3px solid #999; padding: 3mm 4mm;
           font-size: 9.5pt; margin: 4mm 0; }}
  .limite {{ border-left-color: #c47f17; }}
  footer {{ margin-top: 10mm; padding-top: 3mm; border-top: 1px solid #ccc;
            font-size: 8.5pt; color: #666; }}
</style></head><body>

<h1>Posición territorial — {e(nombre)}</h1>
<p class="sub">Derechos mineros, vecinos y terreno libre · anillo de análisis {radio_km:.0f} km ·
elaborado el {hoy} sobre catastros provinciales públicos</p>

<div class="kpis">
  <div class="kpi"><b>{a['ha_propia']:,.0f}</b><span>hectáreas (unión)</span></div>
  <div class="kpi"><b>{len(mios)}</b><span>derechos</span></div>
  <div class="kpi"><b>{len(a['vecinos'])}</b><span>vecinos</span></div>
  <div class="kpi"><b>{a['ha_libre']:,.0f}</b><span>ha libres en el anillo</span></div>
</div>

<div class="nota">La superficie es la <b>unión</b> de los polígonos: el suelo cubierto por
más de un derecho se cuenta una vez. La suma de las superficies declaradas da
{a['ha_suma']:,.0f} ha, un {100*(a['ha_suma']/a['ha_propia']-1):.0f}% más.</div>

<h2>Perfil de la posición</h2>
<table>
<tr><th>Provincias</th><td>{e(fila_tipos(pf['provincias']))}</td></tr>
<tr><th>Tipos</th><td>{e(fila_tipos(pf['tipos'], LABEL_TIPO))}</td></tr>
<tr><th>Estados</th><td>{e(fila_tipos(pf['estados'], LABEL_ESTADO))}</td></tr>
<tr><th>Minerales</th><td>{e(fila_tipos(pf['minerales'])) or '—'}</td></tr>
<tr><th>Departamentos</th><td>{e(fila_tipos(pf['departamentos']))}</td></tr>
</table>

<h2>Vecinos dentro de {radio_km:.0f} km</h2>
<p class="sub">{a['n_vecinos_derechos']} derechos de terceros tocan el anillo de análisis.
Ordenados por superficie (unión por titular).</p>
<table>
<tr><th>Titular</th><th>ha</th><th>derechos</th><th>tipos</th><th>minerales</th></tr>
{vecinos_rows}
</table>

{_bloque_sin_titular(a)}

<h2>Superposiciones de terceros sobre la posición</h2>
<table>
<tr><th>Titular</th><th>Denominación</th><th>Tipo</th><th>Expediente</th><th>ha</th></tr>
{solape_rows}
</table>

<h2>Terreno libre en el anillo</h2>
<p>De las {a['ha_zona']:,.0f} ha del anillo de {radio_km:.0f} km alrededor de la posición,
<b>{a['ha_libre']:,.0f} ha</b> ({100*a['ha_libre']/a['ha_zona']:.0f}%) no figuran bajo ningún
derecho en los catastros relevados. La geometría va en el GeoJSON adjunto.</p>
<div class="nota limite">«Libre» significa <i>sin derecho registrado en las fuentes citadas
abajo, a la fecha de descarga</i>. No contempla solicitudes en trámite no publicadas,
áreas de reserva provincial, parques nacionales, comunidades ni servidumbres de
superficie. Verificar en la autoridad minera antes de peticionar.</div>

<h2>Procedencia</h2>
<table>
<tr><th>Fuente</th><th>Capa</th><th>Derechos</th><th>CRS origen</th><th>Descargado</th><th>Licencia</th></tr>
{fuente_rows}
</table>

<h2>Qué NO contiene este dato</h2>
<div class="nota limite">
<b>No hay fechas de vencimiento.</b> Ninguna de las seis provincias publica caducidad en su
catastro. Catamarca, Neuquén, Córdoba y Jujuy no publican fecha alguna; San Juan la trae en
el 44% de los registros y Salta en el 95%. Esta posición tiene fecha en
{pf['con_fecha']} de {len(mios)} derechos.<br><br>
<b>Titular incompleto.</b> Varias provincias no publican el titular de los cateos —
San Juan no lo hace en ninguno. Un vecino que figura «sin titular publicado» tiene dueño;
lo que falta es el dato, no el derecho.<br><br>
<b>Mineral incompleto.</b> Declarado en el 55% de los derechos a nivel nacional.<br><br>
<b>Sin interpretación geológica.</b> Este informe describe tenencia, no prospectividad.
No dice dónde hay mineral.
</div>

<footer>
Elaborado con datos públicos de los catastros mineros provinciales citados arriba.
Los derechos mineros son registro público por el Código de Minería. Verificar
licencia por fuente antes de redistribuir. Este informe no es asesoramiento legal
ni de inversión; la información oficial es la de la autoridad minera provincial.<br>
Matías Podeley · podeley.ar · mpodeley@gmail.com
</footer>
</body></html>"""


# --- main --------------------------------------------------------------------


def listar(todos: list[dict], n: int = 40) -> None:
    """Holders worth reporting on: companies with exploration ground."""
    acc = defaultdict(lambda: {"ha": 0.0, "n": 0, "cateos": 0, "provs": set()})
    for r in todos:
        p = r["p"]
        if not p.get("titular") or p.get("titular_es_persona"):
            continue
        e = acc[p["titular"]]
        e["ha"] += p.get("superficie_ha_calc") or 0
        e["n"] += 1
        e["provs"].add(p["provincia"])
        if p.get("tipo") == "cateo":
            e["cateos"] += 1
    rank = sorted((v | {"t": k} for k, v in acc.items()), key=lambda x: -x["ha"])
    print(f"{'ha':>11} {'derechos':>9} {'cateos':>7}  titular")
    for v in [x for x in rank if x["cateos"] > 0][:n]:
        print(f"{v['ha']:>11,.0f} {v['n']:>9} {v['cateos']:>7}  {v['t'][:46]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titular", help="nombre o fragmento del titular")
    ap.add_argument("--radio-km", type=float, default=RADIO_KM)
    ap.add_argument("--listar", action="store_true", help="titulares candidatos")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    print("cargando catastro…")
    todos = cargar_todo()
    print(f"  {len(todos)} derechos poligonales")

    if args.listar or not args.titular:
        listar(todos)
        return 0

    nombre, mios = buscar_titular(todos, args.titular)
    print(f"titular: {nombre} — {len(mios)} derechos")

    a = analizar(todos, mios, args.radio_km)
    pf = perfil(mios)

    slug = (N.norm_titular(nombre) or nombre).lower().replace(" ", "-")[:50]
    dest = os.path.join(args.out, slug)
    os.makedirs(dest, exist_ok=True)

    with open(os.path.join(dest, "informe.html"), "w", encoding="utf-8") as f:
        f.write(render_html(nombre, a, pf, mios, args.radio_km))
    escribir_csv(os.path.join(dest, "derechos.csv"), mios)
    escribir_geojson(os.path.join(dest, "posicion.geojson"), a, mios)
    with open(os.path.join(dest, "vecinos.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["titular", "ha", "derechos", "provincias", "minerales"])
        for v in a["vecinos"]:
            w.writerow([v["titular"], v["ha"], v["n"],
                        " ".join(v["provincias"]), " ".join(v["minerales"])])

    print(f"\n  posicion : {a['ha_propia']:,.0f} ha (union) / {a['ha_suma']:,.0f} ha (suma)")
    print(f"  vecinos  : {len(a['vecinos'])} titulares, {a['n_vecinos_derechos']} derechos")
    print(f"  solapes  : {len(a['solapes'])} de terceros sobre la posicion")
    print(f"  libre    : {a['ha_libre']:,.0f} ha en el anillo de {args.radio_km:.0f} km")
    print(f"\n-> {dest}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
