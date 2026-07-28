"""Generic OGC WFS adapter — covers San Juan, Salta, Catamarca and Cordoba.

Four of the six v1 sources are this one class parameterized by the registry;
per-province code is a ~20-line entry in fuentes.py, not a module. That is the
maintenance lever: ten provinces must not mean ten codebases.

Two behaviours here are load-bearing:

1. **Pagination with a hard assert.** GeoServer silently caps responses at its
   configured maxFeatures on many installs. Salta happens to return all 3,964
   in one shot; relying on that would be how a province quietly ships at half
   size. Silent truncation is the #1 correctness risk in this project, so the
   collected count is asserted against `numberMatched` and a mismatch raises.

2. **Versioned layer resolution.** Catamarca publishes `idecat:MINAS_19022026`
   — the publication date is in the layer name and will change. `layer_pattern`
   resolves the newest match against GetCapabilities and reports the change.
"""

import re
import xml.etree.ElementTree as ET
from typing import Iterator, Optional

from adapters.base import BaseAdapter, Probe, RawPayload, sha256_bytes, utcnow
import crs as crsmod
import normalize as N
from esquema import Derecho, validate_vocab
from fuentes import Fuente

_WFS_NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "xsd": "http://www.w3.org/2001/XMLSchema",
}


class WfsAdapter(BaseAdapter):
    def __init__(self, fuente: Fuente):
        super().__init__(fuente)
        self._resolved_layer: Optional[str] = None

    # --- layer resolution ----------------------------------------------------

    def resolve_layer(self) -> str:
        """Return the live layer name, following `layer_pattern` when set."""
        f = self.fuente
        if not f.layer_pattern:
            self._resolved_layer = f.layer
            return f.layer

        r = self._get(
            f.url,
            {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
        )
        names = re.findall(r"<Name>([^<]+)</Name>", r.text)
        matches = sorted(n for n in names if re.fullmatch(f.layer_pattern, n))
        if not matches:
            raise RuntimeError(
                f"{f.id}: ninguna capa matchea {f.layer_pattern!r} en {f.url}"
            )
        # Names carry a date suffix, so lexical max is the newest publication.
        resolved = matches[-1]
        if resolved != f.layer:
            print(
                f"  [drift] {f.id}: capa versionada cambio "
                f"{f.layer!r} -> {resolved!r} (adoptando la nueva)"
            )
        self._resolved_layer = resolved
        return resolved

    # --- probe ---------------------------------------------------------------

    def probe(self) -> Probe:
        f = self.fuente
        try:
            layer = self.resolve_layer()
            r = self._get(
                f.url,
                {
                    "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                    "typeNames": layer, "resultType": "hits",
                },
            )
            m = re.search(r'numberMatched="(\d+)"', r.text)
            count = int(m.group(1)) if m else None

            fields, geom_type = self._describe(layer)
            return Probe(
                fuente_id=f.id, ok=True, checked_at=utcnow(),
                http_status=200, feature_count=count, field_names=fields,
                geom_type=geom_type, srid=f.srid_declarado,
                resolved_layer=layer, elapsed_ms=self._last_elapsed_ms,
            )
        except Exception as e:  # noqa: BLE001 — a probe must never raise
            return Probe(
                fuente_id=f.id, ok=False, checked_at=utcnow(),
                error=f"{type(e).__name__}: {e}"[:300],
            )

    def _describe(self, layer: str) -> tuple[list[str], Optional[str]]:
        """Field names and geometry type, from DescribeFeatureType."""
        try:
            r = self._get(
                self.fuente.url,
                {
                    "service": "WFS", "version": "2.0.0",
                    "request": "DescribeFeatureType", "typeNames": layer,
                },
                timeout=60,
            )
            root = ET.fromstring(r.content)
            fields, geom = [], None
            for el in root.iter("{http://www.w3.org/2001/XMLSchema}element"):
                name, typ = el.get("name"), el.get("type") or ""
                if not name:
                    continue
                if "gml:" in typ:
                    geom = typ.split(":")[-1]
                else:
                    fields.append(name)
            return fields, geom
        except Exception:  # noqa: BLE001
            return [], None

    # --- fetch ---------------------------------------------------------------

    def _count(self, layer: str) -> int:
        r = self._get(
            self.fuente.url,
            {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": layer, "resultType": "hits",
            },
        )
        m = re.search(r'numberMatched="(\d+)"', r.text)
        if not m:
            raise RuntimeError(f"{self.fuente.id}: GetFeature hits sin numberMatched")
        return int(m.group(1))

    def _page_params(self, layer: str, count: int, start: Optional[int]) -> dict:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "application/json",
            "count": count,
        }
        if start is not None:
            params["startIndex"] = start
        if self.fuente.srs_request:
            # Server-side reprojection. Verified working on San Juan's GeoServer
            # (native EPSG:5344 -> correct lon/lat) and always preferable to
            # doing the datum math locally.
            params["srsName"] = self.fuente.srs_request
        return params

    def _collect(self, layer: str, expected: int) -> tuple[list[dict], list[str]]:
        """Fetch every feature, paginating only when it is both needed and supported.

        San Juan publishes database views (`vw_*`) with no primary key, and its
        GeoServer answers any request carrying `startIndex` with a 400. Paging
        is therefore skipped when the layer fits in one page, and falls back to
        a single unpaginated request when the server rejects the offset. The
        count assert in fetch() holds either way, so dropping pagination never
        weakens the truncation guarantee.
        """
        f = self.fuente
        urls: list[str] = []

        def single() -> list[dict]:
            # count is padded so that a server which grew between the hits call
            # and this one still trips the assert instead of silently truncating.
            r = self._get(f.url, self._page_params(layer, max(expected + 1, 1), None), timeout=300)
            urls.append(r.url)
            return r.json().get("features") or []

        if expected <= f.page_size:
            return single(), urls

        features: list[dict] = []
        start = 0
        while start < expected:
            try:
                r = self._get(f.url, self._page_params(layer, f.page_size, start), timeout=300)
            except Exception as e:  # noqa: BLE001
                if start == 0:
                    print(f"  [aviso] {f.id}: el servidor rechaza startIndex ({e}); "
                          f"reintentando sin paginar")
                    return single(), urls
                raise
            urls.append(r.url)
            got = r.json().get("features") or []
            if not got:
                break
            features.extend(got)
            start += len(got)
        return features, urls

    def fetch(self, cache_dir: str, use_cache: bool = True) -> RawPayload:
        import json as _json

        f = self.fuente
        if use_cache:
            cached = self._load_cache(cache_dir, ext="geojson")
            if cached:
                return cached

        layer = self.resolve_layer()
        expected = self._count(layer)
        features, seen_urls = self._collect(layer, expected)

        # THE assert. A half-fetched province publishes a map that is wrong in a
        # way nobody notices, so this is a hard failure, never a warning.
        if len(features) != expected:
            raise RuntimeError(
                f"{f.id}: truncado {len(features)}/{expected} features "
                f"(capa {layer}, page_size={f.page_size})"
            )

        fc = {"type": "FeatureCollection", "features": features}
        body = _json.dumps(fc, ensure_ascii=False).encode("utf-8")
        raw = RawPayload(
            fuente_id=f.id,
            url=seen_urls[0] if seen_urls else f.url,
            body=body,
            sha256=sha256_bytes(body),
            fetched_at=utcnow(),
            resolved_layer=layer,
            meta={"expected": expected, "pages": len(seen_urls)},
        )
        self._save_cache(cache_dir, raw, ext="geojson")
        return raw

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawPayload) -> Iterator[dict]:
        import json as _json

        fc = _json.loads(raw.body.decode("utf-8"))
        yield from (fc.get("features") or [])

    # --- normalize -----------------------------------------------------------

    def normalize(self, feat: dict, raw: RawPayload) -> Optional[Derecho]:
        f = self.fuente
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if not geom or not geom.get("coordinates"):
            return None

        # If the server ignored srsName and handed back projected metres, fall
        # back to local reprojection rather than shipping nonsense coordinates.
        src_srid = int(f.srid_declarado or 4326)
        if crsmod.looks_like_projected(geom):
            geom = crsmod.reproject_geom(geom, src_srid, crsmod.WGS84)
        geom = N.round_coords(geom, dp=5)

        fid = str(
            feat.get("id")
            or props.get("fid")
            or props.get("gid")
            or props.get("id")
            or ""
        )
        if not fid:
            return None

        def pick(*names):
            for n in names:
                v = props.get(n)
                if v not in (None, "", "<Null>"):
                    return v
            return None

        expediente = pick("expediente", "expte_siged", "exp", "expte")
        titular_raw = pick("titular", "concesionario", "concsrio", "propietario")
        titular = N.titular_valido(N.strip_pii(titular_raw))
        mineral_raw = pick("mineral", "minerales", "sustancia", "sustancias")
        tipo_raw = pick("tipo", "tipo_derecho", "categoria")
        estado_raw = pick("estado", "situacion")

        # San Juan flags historic records with a -HIST expediente suffix.
        if estado_raw is None and expediente and str(expediente).upper().endswith("-HIST"):
            estado_raw = "HIST"

        nombre = pick("nombre", "denominacion", "nombre_mina", "mina", "denominacio")
        sup = N.parse_ha(pick("area", "sup_reg_ha", "superficie", "sup_ha", "hectareas"))

        d = Derecho(
            id=self.derecho_id(fid),
            provincia=f.provincia,
            provincia_nombre=f.provincia_nombre,
            tipo=N.map_tipo(tipo_raw, default=f.tipo_fijo),
            estado=N.map_estado(estado_raw, default=f.estado_fijo or "desconocido"),
            geom_kind=f.geom_kind,
            geometry=geom,
            expediente=str(expediente) if expediente else None,
            expediente_norm=N.norm_expediente(expediente),
            expediente_gde=(
                str(pick("exptedgtl", "expediente_gde")) if pick("exptedgtl", "expediente_gde") else None
            ),
            tipo_origen=str(tipo_raw) if tipo_raw else None,
            estado_origen=str(estado_raw) if estado_raw else None,
            nombre=str(nombre) if nombre else None,
            titular=titular,
            titular_norm=N.norm_titular(titular),
            titular_es_persona=N.titular_es_persona(titular),
            mineral=N.map_mineral(mineral_raw),
            mineral_origen=str(mineral_raw) if mineral_raw else None,
            fecha_inicio=N.parse_fecha(pick("fecha_inicio", "fechaInscripcion", "fecha")),
            fecha_resolucion=N.parse_fecha(pick("fechaResolucion", "fecha_resolucion")),
            fecha_inscripcion=N.parse_fecha(pick("fechaInscripcion", "fecha_inscripcion")),
            fecha_mensura=N.parse_fecha(
                pick("fechaResolucionMensura", "fechaInscripcionMensura", "fecha_mensura")
            ),
            superficie_ha=sup,
            cantidad_pertenencias=_as_int(pick("cantidadPertenencias", "pertenencias")),
            departamento=_title(pick("departamento", "dpto", "depto")),
            municipio=_title(pick("municipio", "muni")),
            lugar=_title(pick("lugar", "paraje")),
            **self.provenance(raw, fid),
        )
        validate_vocab(d)
        return d


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _title(v) -> Optional[str]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    return s.title() if s.isupper() else s
