"""Shapefile-in-a-ZIP adapter — Jujuy's `catastro minero` download.

Jujuy publishes the whole cadastre as SHP / KMZ / XLSX behind
`download_catastrominero.php?d=<hash>&t=shp`. The shapefile is the richest of
the three (typed attributes plus geometry), so that is what this reads.

Four things worth knowing:

1. **The download link carries a rotating token** (`d=82d0ffb3...`), so the href
   is scraped off the cadastre page rather than hardcoded.

2. **The ZIP holds both a combined layer and per-type folders.** `CATASTRO_MINERO`
   sits at the archive root with all 1,784 records and a `tipo` column; the nine
   `CATEO/`, `MINACONCEDIDA/`, ... folders are the same records split up. Reading
   the combined layer means one pass and no risk of double-counting.

3. **The DBF is latin-1, not UTF-8.** pyshp defaults to UTF-8 and dies on the
   first degree sign.

4. **`dom_corre` contains e-mail addresses of title holders.** It is dropped
   outright — never parsed into the schema, never published. Jujuy is the only
   province so far that leaks contact details into its cadastre export.

Native CRS is EPSG:22183 (POSGAR 94 / Argentina faja 3), reprojected locally
since a file source has no server to ask.
"""

import io
import re
import zipfile
from typing import Iterator, Optional

import shapefile  # pyshp

from adapters.base import BaseAdapter, Probe, RawPayload, sha256_bytes, utcnow
import crs as crsmod
import normalize as N
from esquema import Derecho, validate_vocab
from fuentes import Fuente

# Jujuy's `tipo` codes, from the live data (2026-07-28).
_TIPO_JUJUY = {
    "C": "cateo",                        # cateo / permiso de exploracion
    "MC": "mina",                        # mina concedida
    "MT": "solicitud",                   # solicitud (mina en tramite)
    "CAN": "cantera",
    "MVS": "solicitud",                  # mina vacante solicitada
    "S": "servidumbre",
    "AR": "area_proteccion",             # area de reserva
    "GM": "mina",                        # grupo minero: varias minas administradas juntas
    "SGM": "solicitud",                  # solicitud de grupo minero
}

# `tipo_miner` mixes actual substances ("LITIO", "PLATA, ESTAÑO Y ZINC") with
# the Codigo de Mineria category number ("1 Y 2", "1"). The numbers are not
# minerals and must not become bogus entries in the mineral filter.
_RE_SOLO_CATEGORIA = re.compile(r"^[\s0-9]*(?:y|Y)?[\s0-9]*$")

_RE_ZIP_HREF = re.compile(r'href="([^"]*download_catastrominero\.php[^"]*t=shp[^"]*)"', re.I)


class ShpAdapter(BaseAdapter):
    def _discover_zip_url(self) -> str:
        r = self._get(self.fuente.url, timeout=90)
        m = _RE_ZIP_HREF.search(r.text)
        if not m:
            raise RuntimeError(
                f"{self.fuente.id}: no se encontro link de descarga SHP en {self.fuente.url}"
            )
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("http"):
            return href
        from urllib.parse import urljoin

        return urljoin(self.fuente.url, href)

    # --- probe ---------------------------------------------------------------

    def probe(self) -> Probe:
        f = self.fuente
        try:
            url = self._discover_zip_url()
            r = self.session.head(url, timeout=60, allow_redirects=True)
            size = int(r.headers.get("Content-Length") or 0)
            # `download_catastrominero.php` answers HEAD with a 20-byte stub
            # instead of the real Content-Length. Reporting that as the file
            # size would fire a permanent -100% drift alert, so an implausibly
            # small ZIP is treated as "size unknown" rather than as a change.
            # Liveness is still covered: the link had to be found and the HEAD
            # had to succeed.
            plausible = size if size > 50_000 else None
            return Probe(
                fuente_id=f.id, ok=r.status_code < 400, checked_at=utcnow(),
                http_status=r.status_code, srid=f.srid_declarado,
                geom_type="Polygon", elapsed_ms=self._last_elapsed_ms,
                # The token in the URL rotates, so the filename is not identity.
                resolved_layer=None,
                bytes=plausible,
            )
        except Exception as e:  # noqa: BLE001
            return Probe(
                fuente_id=f.id, ok=False, checked_at=utcnow(),
                error=f"{type(e).__name__}: {e}"[:300],
            )

    # --- fetch ---------------------------------------------------------------

    def fetch(self, cache_dir: str, use_cache: bool = True) -> RawPayload:
        if use_cache:
            cached = self._load_cache(cache_dir, ext="zip")
            if cached:
                return cached

        url = self._discover_zip_url()
        r = self._get(url, timeout=300)
        if not r.content[:2] == b"PK":
            raise RuntimeError(f"{self.fuente.id}: la descarga no es un ZIP ({r.content[:20]!r})")

        raw = RawPayload(
            fuente_id=self.fuente.id, url=url, body=r.content,
            sha256=sha256_bytes(r.content), fetched_at=utcnow(),
            resolved_layer=self.fuente.layer,
            meta={"bytes_descarga": len(r.content)},
        )
        self._save_cache(cache_dir, raw, ext="zip")
        return raw

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawPayload) -> Iterator[dict]:
        z = zipfile.ZipFile(io.BytesIO(raw.body))
        base = self.fuente.layer or "CATASTRO_MINERO"
        try:
            r = shapefile.Reader(
                shp=io.BytesIO(z.read(f"{base}.shp")),
                dbf=io.BytesIO(z.read(f"{base}.dbf")),
                shx=io.BytesIO(z.read(f"{base}.shx")),
                # latin-1: the DBF carries degree signs and accented names that
                # blow up pyshp's UTF-8 default on the first record.
                encoding="latin-1",
            )
        except KeyError as e:
            raise RuntimeError(
                f"{self.fuente.id}: falta {base}.* en el zip "
                f"(contiene {z.namelist()[:6]})"
            ) from e

        for i, sr in enumerate(r.iterShapeRecords()):
            geom = sr.shape.__geo_interface__
            if not geom or not geom.get("coordinates"):
                continue
            yield {"idx": i, "rec": sr.record.as_dict(), "geom": geom}

    # --- normalize -----------------------------------------------------------

    def normalize(self, item: dict, raw: RawPayload) -> Optional[Derecho]:
        f = self.fuente
        rec = item["rec"]

        # Local reprojection: a file has no server to ask for EPSG:4326.
        geom = crsmod.reproject_geom(
            item["geom"], int(f.srid_declarado or 22183), crsmod.WGS84
        )
        geom = N.round_coords(geom, dp=5)

        fid = str(rec.get("id") or rec.get("objectid") or item["idx"])
        tipo_raw = (rec.get("tipo") or "").strip()
        tipo = _TIPO_JUJUY.get(tipo_raw.upper()) or N.map_tipo(tipo_raw, default="otro")

        # `dom_corre` (holder e-mail) is deliberately never read.
        titular = N.strip_pii(rec.get("titular_ac"))
        nombre = (rec.get("nombre") or "").strip()
        if nombre in ("-", ""):
            nombre = None

        mineral_raw = (rec.get("tipo_miner") or "").strip()
        if _RE_SOLO_CATEGORIA.match(mineral_raw):
            mineral_raw = ""   # "1 Y 2" is a legal category, not a substance

        sup = N.parse_ha(rec.get("superficie") or rec.get("area"))

        d = Derecho(
            id=self.derecho_id(fid),
            provincia=f.provincia,
            provincia_nombre=f.provincia_nombre,
            tipo=tipo,
            estado=N.map_estado(rec.get("estado"), default="desconocido"),
            geom_kind="poligono",
            geometry=geom,
            expediente=str(rec.get("expediente") or "").strip() or None,
            expediente_norm=N.norm_expediente(rec.get("expediente")),
            tipo_origen=tipo_raw or None,
            estado_origen=(rec.get("estado") or "").strip() or None,
            nombre=nombre,
            titular=titular,
            titular_norm=N.norm_titular(titular),
            titular_es_persona=N.titular_es_persona(titular),
            mineral=N.map_mineral(mineral_raw),
            mineral_origen=mineral_raw or None,
            superficie_ha=sup,
            departamento=_title(rec.get("depto")),
            **self.provenance(raw, fid),
        )
        validate_vocab(d)
        return d


def _title(v) -> Optional[str]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    return s.title() if s.isupper() else s or None
