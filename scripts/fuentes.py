"""THE REGISTRY — every provincial source, as data rather than code.

Adding a province is adding rows here, not writing a module. The generated
coverage and sources pages read from this list, so the published documentation
cannot drift away from what the pipeline actually does.

All URLs below were probed live on 2026-07-28 unless the `verificado_el` field
says otherwise. Endpoints move: the official national index at
argentina.gob.ar/economia/mineria/siacam/otros-recursos/catastros-mineros still
points at dead links for San Juan and Salta, which is exactly why
`health_check.py` exists.
"""

from dataclasses import dataclass, field
from typing import Optional

# Some provincial servers reject non-browser agents (Catamarca 403s outright).
# Carry a contact URL so an administrator who sees the traffic can reach us.
HDRS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36 "
        "(catastro-minero-argentina; +https://github.com/mpodeley/catastro-minero-argentina)"
    ),
}


@dataclass(frozen=True)
class Fuente:
    """One fetchable layer from one provincial authority."""

    id: str                                 # "san_juan.catastrominero.minas_padron"
    provincia: str                          # slug
    provincia_nombre: str
    kind: str                               # wfs | kml | tabular | shapefile | manual | ninguna
    url: str
    layer: Optional[str] = None
    # Regex when the published layer name embeds a version/date and will change.
    layer_pattern: Optional[str] = None
    # When the source has no type column, the layer itself IS the type.
    tipo_fijo: Optional[str] = None
    estado_fijo: Optional[str] = None
    geom_kind: str = "poligono"
    srid_declarado: Optional[int] = None
    # Ask the server to reproject rather than doing the math locally.
    srs_request: Optional[str] = "EPSG:4326"
    page_size: int = 2000
    headers: dict = field(default_factory=lambda: dict(HDRS))
    licencia: str = "no_especificada"
    licencia_verificada_el: Optional[str] = None
    verificado_el: str = "2026-07-28"
    notas: str = ""


# --- San Juan ----------------------------------------------------------------
# The #1 mining province (Josemaria, Los Azules, Filo del Sol, Veladero).
# Cadastre digitised Sept 2025; endpoint extracted from the Vue bundle at
# mineria.sanjuan.gob.ar. Native CRS is EPSG:5344 (POSGAR 2007 faja 2) and
# GeoServer reprojects correctly when asked for EPSG:4326 — verified.
# The type is NOT a column here: it is which view you queried.
_SAN_JUAN_WFS = "https://catastrominero.sanjuan.gob.ar/geoserver/wfs"

SAN_JUAN = [
    Fuente(
        id="san_juan.catastrominero.minas_padron",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_minas_padron",
        tipo_fijo="mina", srid_declarado=5344,
        notas="Unica capa provincial con titular. 1.378 features al 2026-07-28.",
    ),
    Fuente(
        id="san_juan.catastrominero.manifestaciones",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_manifestaciones_padron",
        tipo_fijo="manifestacion_descubrimiento", srid_declarado=5344,
    ),
    Fuente(
        id="san_juan.catastrominero.permisos_exploracion",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_permisos_exploracion",
        tipo_fijo="cateo", srid_declarado=5344,
        notas="Atributos pobres: expte_siged, sup_reg_ha, denominacion. SIN titular.",
    ),
    Fuente(
        id="san_juan.catastrominero.canteras",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_canteras",
        tipo_fijo="cantera", srid_declarado=5344, notas="Sin titular.",
    ),
    Fuente(
        id="san_juan.catastrominero.solicitudes",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_solicitudes_poligonos",
        tipo_fijo="solicitud", estado_fijo="tramite", srid_declarado=5344,
    ),
    Fuente(
        id="san_juan.catastrominero.servidumbres",
        provincia="san_juan", provincia_nombre="San Juan", kind="wfs",
        url=_SAN_JUAN_WFS, layer="mineria:vw_servidumbres_poligonos",
        tipo_fijo="servidumbre", srid_declarado=5344,
    ),
]

# --- Salta -------------------------------------------------------------------
# GeoNode. The richest schema of the six: tipo, mineral, estado, concesionario,
# fecha_inicio and a declared area all present. Also ships `coordenadas`, the
# original Gauss-Kruger WKT — a free dual representation used by the CRS
# round-trip test, and ~40% of the payload, so it never reaches the browser.
_SALTA_WFS = "https://geoportal.salta.gob.ar/geoserver/wfs"

SALTA = [
    Fuente(
        id="salta.geonode.catastro_minero",
        provincia="salta", provincia_nombre="Salta", kind="wfs",
        url=_SALTA_WFS, layer="geonode:poligonos_adaf55f39328ff45c8c60e94eb13a7a0",
        srid_declarado=4326,
        notas="3.964 features al 2026-07-28. tipo/estado/mineral vienen como columnas.",
    ),
    Fuente(
        id="salta.geonode.servidumbres",
        provincia="salta", provincia_nombre="Salta", kind="wfs",
        url=_SALTA_WFS, layer="geonode:servidumbres_l",
        tipo_fijo="servidumbre", geom_kind="linea", srid_declarado=4326,
    ),
    Fuente(
        id="salta.geonode.provisorios",
        provincia="salta", provincia_nombre="Salta", kind="wfs",
        url=_SALTA_WFS, layer="geonode:provisorios",
        tipo_fijo="solicitud", estado_fijo="tramite", srid_declarado=4326,
        notas="Solicitudes NO revisadas por la autoridad. Marcar como provisorio en la UI.",
    ),
]

# --- Catamarca ---------------------------------------------------------------
# Alumbrera, MARA/Agua Rica, Fenix, Tres Quebradas. The layer name embeds its
# publication date (MINAS_19022026 = 19/02/2026) and WILL change on republish —
# this is the canonical reason the registry carries `layer_pattern`.
CATAMARCA = [
    Fuente(
        id="catamarca.idecat.minas",
        provincia="catamarca", provincia_nombre="Catamarca", kind="wfs",
        url="https://nodoide.catamarca.gob.ar/geoserver/wfs",
        layer="idecat:MINAS_19022026",
        layer_pattern=r"idecat:MINAS_\d{8}",
        tipo_fijo="mina", srid_declarado=4326,
        notas="403 sin User-Agent de browser. Nombre de capa versionado por fecha.",
    ),
]

# --- Neuquen -----------------------------------------------------------------
# KMZ export from an ArcGIS server. No ExtendedData: attributes live in an HTML
# <table> inside <description><![CDATA[...]]>. Two traps, both encoded in the
# adapter: <name> holds the EXPEDIENTE and the table row labelled "Nombre" holds
# the TYPE. The download filename is a rotating hash, so the adapter scrapes the
# .zip href off the landing page rather than hardcoding it.
NEUQUEN = [
    Fuente(
        id="neuquen.casminero.kmz",
        provincia="neuquen", provincia_nombre="Neuquén", kind="kml",
        url="https://hidrocarburos.energianeuquen.gob.ar/casminero",
        srid_declarado=4326, srs_request=None,
        notas="6.629 placemarks al 2026-07-28. Link .zip con hash rotativo: se scrapea.",
    ),
]

# --- Cordoba -----------------------------------------------------------------
# Low mining weight (aridos) but cheap to add. Native CRS is EPSG:22173 =
# POSGAR 98 / Argentina faja 3 (verified against pyproj — it is NOT Campo
# Inchauspe, whose faja 3 is the adjacent-looking 22193). POSGAR 98 is
# WGS84-aligned to ~1 m, so this is a benign reprojection; the risk here is
# purely that 2217x / 2218x / 2219x transpose easily by eye, which is why
# crs.py resolves and logs every datum instead of trusting the table.
_CORDOBA_WFS = "https://idecor-ws.mapascordoba.gob.ar/geoserver/wfs"

CORDOBA = [
    Fuente(
        id="cordoba.idecor.pertenencias",
        provincia="cordoba", provincia_nombre="Córdoba", kind="wfs",
        url=_CORDOBA_WFS, layer="idecor:mineria_pertenencias_mineras",
        tipo_fijo="mina", srid_declarado=22173,
    ),
    Fuente(
        id="cordoba.idecor.area_cateo",
        provincia="cordoba", provincia_nombre="Córdoba", kind="wfs",
        url=_CORDOBA_WFS, layer="idecor:mineria_area_cateo",
        tipo_fijo="cateo", srid_declarado=22173,
    ),
    Fuente(
        id="cordoba.idecor.canteras",
        provincia="cordoba", provincia_nombre="Córdoba", kind="wfs",
        url=_CORDOBA_WFS, layer="idecor:mineria_canteras",
        tipo_fijo="cantera", srid_declarado=22173,
    ),
    Fuente(
        id="cordoba.idecor.area_amparo",
        provincia="cordoba", provincia_nombre="Córdoba", kind="wfs",
        url=_CORDOBA_WFS, layer="idecor:mineria_area_amparo",
        tipo_fijo="area_proteccion", srid_declarado=22173,
    ),
    Fuente(
        id="cordoba.idecor.minas_puntos",
        provincia="cordoba", provincia_nombre="Córdoba", kind="wfs",
        url=_CORDOBA_WFS, layer="idecor:mineria_minas",
        tipo_fijo="mina", geom_kind="punto", srid_declarado=22173,
        notas="Puntos, no poligonos. Van a un archivo aparte para no mezclar geometrias.",
    ),
]

# --- Jujuy -------------------------------------------------------------------
# Olaroz, Cauchari-Olaroz, Salinas Grandes. Publishes a downloadable tabular
# registry plus a viewer; the spatial format is still being surveyed, so this
# entry is declared but not yet wired into the build.
JUJUY = [
    Fuente(
        id="jujuy.mineria.padron",
        provincia="jujuy", provincia_nombre="Jujuy", kind="tabular",
        url="https://www.mineriajujuy.gob.ar/site/jam_catastro.php",
        srs_request=None, verificado_el="2026-07-28",
        notas="A relevar: registro descargable orientado a Excel + visor. Formato espacial por confirmar.",
    ),
]


FUENTES: list[Fuente] = [*SAN_JUAN, *SALTA, *CATAMARCA, *NEUQUEN, *CORDOBA, *JUJUY]

# Provinces deliberately out of v1 scope, published on the site as an explicit
# absence. Incompleteness must read as "sin datos abiertos", never as zero —
# provinces that publish nothing would otherwise look unconcessioned.
SIN_DATOS_ABIERTOS: dict[str, str] = {
    "santa_cruz": (
        "Sólo un PDF (CATASTRO-MINERO-AGOSTO-2023.pdf) en minpro.santacruz.gob.ar. "
        "Es de las provincias más importantes por producción (Cerro Negro, Cerro "
        "Vanguardia, San José) y no publica datos estructurados."
    ),
    "chubut": "Sin geoservicio localizado. Ley 5001 restringe explotación; los derechos existen igual.",
    "rio_negro": "Sin geoservicio localizado al 2026-07-28.",
    "mendoza": "Sin geoservicio localizado. Ley 7722 restringe métodos de explotación.",
    "la_rioja": "Sin geoservicio localizado al 2026-07-28.",
    "san_luis": "Sin geoservicio localizado al 2026-07-28.",
}


def por_id(fuente_id: str) -> Fuente:
    for f in FUENTES:
        if f.id == fuente_id:
            return f
    raise KeyError(f"fuente desconocida: {fuente_id}")


def por_provincia(provincia: str) -> list[Fuente]:
    return [f for f in FUENTES if f.provincia == provincia]


def provincias() -> list[str]:
    """Distinct province slugs, in registry order."""
    return list(dict.fromkeys(f.provincia for f in FUENTES))
