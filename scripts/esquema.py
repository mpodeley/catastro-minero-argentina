"""Normalized schema for one Argentine mining right (derecho minero).

Argentina has no national mining cadastre: under the Codigo de Mineria the
provinces own the mineral resource, so each runs its own registry with its own
access mechanism and field names. Everything this pipeline ingests is coerced
into the `Derecho` record below so that ten heterogeneous provincial sources
can be queried, mapped and downloaded as one dataset.

Provenance fields are mandatory, never null: the differentiator of this project
over every official provincial viewer is that each feature can say exactly where
it came from and when it was cut.
"""

from dataclasses import dataclass, asdict, field
from typing import Literal, Optional

# --- controlled vocabularies -------------------------------------------------

# Categories of mining right. Provincial sources use dozens of local labels;
# `tipo_origen` always preserves the untranslated original.
TipoDerecho = Literal[
    "cateo",                        # permiso de exploracion
    "mina",                         # mina / pertenencia (Cod. Mineria art. 111)
    "manifestacion_descubrimiento",
    "cantera",                      # 3ra categoria / aridos
    "servidumbre",
    "solicitud",                    # pedido no resuelto / provisorio
    "planta",                       # beneficio / elaboracion
    "area_proteccion",              # reserva, amparo, zona de proteccion
    "otro",
]

# NOTE: "Vigente" has no shared legal definition across ten provincial mining
# codes. Never publish a national KPI over `estado` without a caveat, and always
# carry `estado_origen` through to the UI.
Estado = Literal[
    "vigente", "tramite", "caduco", "desistido", "vacante", "desconocido",
]

GeomKind = Literal["poligono", "punto", "linea"]

# Default is `no_especificada` until a licence is actually verified per source.
Licencia = Literal[
    "cc-by", "odbl", "dominio_publico", "no_especificada", "restringida",
]

TIPOS: tuple[str, ...] = (
    "cateo", "mina", "manifestacion_descubrimiento", "cantera", "servidumbre",
    "solicitud", "planta", "area_proteccion", "otro",
)
ESTADOS: tuple[str, ...] = (
    "vigente", "tramite", "caduco", "desistido", "vacante", "desconocido",
)


@dataclass(frozen=True)
class Derecho:
    """One mining right. Immutable — adapters build it once and hand it off."""

    # --- identity ------------------------------------------------------------
    id: str                                 # "{provincia}:{fuente_short}:{source_fid}"
    provincia: str                          # slug, matches provincias.geojson
    provincia_nombre: str
    tipo: str                               # TipoDerecho
    estado: str                             # Estado

    # --- geometry ------------------------------------------------------------
    geom_kind: str                          # GeomKind
    geometry: dict                          # GeoJSON, EPSG:4326, lon/lat, 5 dp

    # --- provenance (mandatory, never null) ----------------------------------
    fuente_id: str                          # registry key
    source_url: str                         # exact request URL behind this record
    source_layer: str                       # typeName / filename / sheet
    source_fid: str                         # the source's own identifier
    source_srid: int                        # EPSG of the *source* geometry
    fetched_at: str                         # UTC ISO-8601
    source_sha256: str                      # checksum of the raw payload
    licencia: str                           # Licencia

    # --- optional identity ---------------------------------------------------
    expediente: Optional[str] = None        # as printed by the source
    expediente_norm: Optional[str] = None   # canonicalised, for joins/dedupe
    expediente_gde: Optional[str] = None    # national GDE/SIGED expte

    # --- classification ------------------------------------------------------
    tipo_origen: Optional[str] = None       # raw source string, untranslated
    estado_origen: Optional[str] = None
    nombre: Optional[str] = None            # denominacion de la mina / cateo

    # --- parties & substance -------------------------------------------------
    titular: Optional[str] = None
    titular_norm: Optional[str] = None      # the join key
    titular_es_persona: Optional[bool] = None   # drives the privacy policy
    mineral: list[str] = field(default_factory=list)   # normalized codes
    mineral_origen: Optional[str] = None

    # --- dates ---------------------------------------------------------------
    fecha_inicio: Optional[str] = None      # ISO date strings, or None
    fecha_resolucion: Optional[str] = None
    fecha_inscripcion: Optional[str] = None
    fecha_mensura: Optional[str] = None

    # --- area ----------------------------------------------------------------
    superficie_ha: Optional[float] = None        # DECLARED by the source
    superficie_ha_calc: Optional[float] = None   # COMPUTED geodesically
    superficie_delta: Optional[float] = None     # (calc - declarada) / declarada
    cantidad_pertenencias: Optional[int] = None

    # --- administrative geography --------------------------------------------
    departamento: Optional[str] = None
    departamento_id: Optional[str] = None   # INDEC code, when matched
    municipio: Optional[str] = None
    lugar: Optional[str] = None

    def to_feature(self, slim: bool = True) -> dict:
        """Emit as a GeoJSON Feature.

        `slim=True` drops the fields the browser never reads, which is what gets
        shipped to the client; the full record still goes into the SIG exports
        and the monthly snapshot.
        """
        props = asdict(self)
        geom = props.pop("geometry")
        if slim:
            for k in ("source_sha256", "expediente_norm", "departamento_id"):
                props.pop(k, None)
            props = {k: v for k, v in props.items() if v is not None and v != []}
        return {"type": "Feature", "geometry": geom, "properties": props}


def validate_vocab(d: Derecho) -> None:
    """Fail loudly on an out-of-vocabulary classification.

    Adapters map local labels onto the controlled lists above; a miss here means
    a provincial source introduced a category we have not seen, which is a
    finding worth surfacing rather than silently bucketing into "otro".
    """
    if d.tipo not in TIPOS:
        raise ValueError(f"{d.id}: tipo fuera de vocabulario: {d.tipo!r}")
    if d.estado not in ESTADOS:
        raise ValueError(f"{d.id}: estado fuera de vocabulario: {d.estado!r}")
    if d.geom_kind not in ("poligono", "punto", "linea"):
        raise ValueError(f"{d.id}: geom_kind invalido: {d.geom_kind!r}")
