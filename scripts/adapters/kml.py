"""KMZ adapter — Neuquen's `casminero` export.

Three things make this source awkward, all of them load-bearing:

1. **The download URL rotates.** The landing page links a storage object whose
   filename is a hash (`.../storage/uploads/sqScRIst...zip`), so the href is
   scraped from the page rather than hardcoded.

2. **No ExtendedData.** This is an ArcGIS "Map to KML" export: attributes live
   in an HTML `<table>` inside `<description><![CDATA[...]]>`, as
   label/value `<td>` pairs.

3. **The type lives in the folder tree, not in the attributes.** `<name>` holds
   the EXPEDIENTE ("2737/2005"), and the type comes from which `<Folder>` the
   Placemark sits in. The document tree, verified 2026-07-28, is:

       REGISTRO GRAFICO/
         cateos                          280
         pertenencias                  4,462
         manifestacion_de_descubrimiento 381
         minas                           662
         demasias                         30
         servidumbres                     31
         canteras                        783   -> 6,629 total

   The table row labelled "Nombre" is the *denominacion* ("EL PORVENIR",
   "DEMASIA MINA MAMA") and is present on only 2,167 of 6,629 records. It reads
   as a type on cateos purely because a cateo has no name and the field says
   "CATEO" — taking that at face value across the whole file mislabels ~83% of
   the province. The folder vocabulary is asserted instead, so a renamed or
   added folder fails loudly rather than silently collapsing into "otro".

   Attribute coverage is uneven and that is a published fact, not a bug:
   Expediente 6,629 · Nombre/Titular/Expediente_GDE 2,167 · Mineral/Categoria
   1,856 · Vigencia 783 (canteras only).
"""

import html
import io
import re
import zipfile
from typing import Iterator, Optional

from adapters.base import BaseAdapter, Probe, RawPayload, sha256_bytes, utcnow
import normalize as N
from esquema import Derecho, validate_vocab
from fuentes import Fuente

# Folder name -> normalized type. This IS the province's classification.
#
# "pertenencias" and "demasias" both map to `mina`: a pertenencia is the unit
# parcel of a mina (Cod. Mineria art. 111) and a demasia is the leftover ground
# between minas granted to an adjoining holder. Both are exploitation rights
# over a measured parcel, which is what `mina` means in this schema; the
# original word is preserved in `tipo_origen`.
_FOLDER_TIPO = {
    "cateos": "cateo",
    "pertenencias": "mina",
    "manifestacion_de_descubrimiento": "manifestacion_descubrimiento",
    "manifestaciones_de_descubrimiento": "manifestacion_descubrimiento",
    "minas": "mina",
    "demasias": "mina",
    "servidumbres": "servidumbre",
    "canteras": "cantera",
}
# Folders that carry no tenement geometry.
_FOLDER_IGNORAR = {"referencias"}

# At least five expediente shapes coexist in this source, all legitimate and
# all observed live: "11717/1985", "8812-000181/2019", "1986/02" (two-digit
# year), "2435/1902-00002/2019" (compound), and the national GDE form
# "EX-2023-02455359- -NEU-MINERIA#SEMH".
#
# Enumerating them is a losing game. What this guard is actually for is catching
# a STRUCTURAL misread — a denominacion like "EL PORVENIR" landing in the
# expediente slot — so it only asserts that the value is numeric-ish.
_RE_EXPEDIENTE = re.compile(r"\d{3}")

_KML_NS = "{http://www.opengis.net/kml/2.2}"
_RE_ZIP = re.compile(r'href="([^"]+\.(?:zip|kmz))"', re.IGNORECASE)
_RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_RE_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_RE_TAGS = re.compile(r"<[^>]+>")


class KmlAdapter(BaseAdapter):
    """Downloads a KMZ/ZIP, walks its doc.kml, parses HTML-table attributes."""

    def _discover_zip_url(self) -> str:
        r = self._get(self.fuente.url, timeout=90)
        hrefs = _RE_ZIP.findall(r.text)
        if not hrefs:
            raise RuntimeError(
                f"{self.fuente.id}: no se encontro link .zip/.kmz en {self.fuente.url}"
            )
        href = hrefs[0]
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            from urllib.parse import urljoin

            return urljoin(self.fuente.url, href)
        return href

    # --- probe ---------------------------------------------------------------

    def probe(self) -> Probe:
        f = self.fuente
        try:
            url = self._discover_zip_url()
            r = self.session.head(url, timeout=60, allow_redirects=True)
            size = int(r.headers.get("Content-Length") or 0)
            return Probe(
                fuente_id=f.id, ok=r.status_code < 400, checked_at=utcnow(),
                http_status=r.status_code, srid=f.srid_declarado,
                # Deliberately NOT the URL basename: it is a rotating storage
                # hash, so reporting it would fire a "layer changed" alert on
                # every republish. The stable identity is the .kml inside.
                resolved_layer=None,
                geom_type="Polygon", elapsed_ms=self._last_elapsed_ms,
                field_names=["Expediente", "Nombre", "Titular", "Expediente_GDE"],
                # Content-Length is the cheap drift signal for a file source;
                # a feature count would need a full download, which probes avoid.
                bytes=size or None,
            )
        except Exception as e:  # noqa: BLE001
            return Probe(
                fuente_id=f.id, ok=False, checked_at=utcnow(),
                error=f"{type(e).__name__}: {e}"[:300],
            )

    # --- fetch ---------------------------------------------------------------

    def fetch(self, cache_dir: str, use_cache: bool = True) -> RawPayload:
        if use_cache:
            cached = self._load_cache(cache_dir, ext="kml")
            if cached:
                return cached

        url = self._discover_zip_url()
        r = self._get(url, timeout=300)
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise RuntimeError(f"{self.fuente.id}: el zip no contiene .kml ({zf.namelist()[:5]})")
        body = zf.read(kml_names[0])

        raw = RawPayload(
            fuente_id=self.fuente.id, url=url, body=body,
            sha256=sha256_bytes(body), fetched_at=utcnow(),
            resolved_layer=kml_names[0],
            # `bytes_descarga` is what a HEAD on the source reports, so the
            # drift check compares transfer size against transfer size rather
            # than against the inflated .kml.
            meta={
                "bytes_descarga": len(r.content),
                "kml_bytes": len(body),
            },
        )
        self._save_cache(cache_dir, raw, ext="kml")
        return raw

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawPayload) -> Iterator[dict]:
        """Yield one record per Placemark, tagged with its enclosing folder.

        Walks the tree rather than using `root.iter(Placemark)`, because the
        folder a Placemark sits in is the only place its type is recorded.
        """
        import xml.etree.ElementTree as ET

        root = ET.fromstring(raw.body)
        seen = 0

        def descend(el, folder: Optional[str]):
            nonlocal seen
            for child in el:
                tag = child.tag
                if tag == f"{_KML_NS}Folder" or tag == f"{_KML_NS}Document":
                    name_el = child.find(f"{_KML_NS}name")
                    nm = (name_el.text or "").strip() if name_el is not None else ""
                    key = nm.strip().lower().replace(" ", "_")
                    # Only descend one meaningful level: the type folders sit
                    # under "REGISTRO GRAFICO", which is itself not a type.
                    nxt = key if key in _FOLDER_TIPO else (None if key in _FOLDER_IGNORAR else folder)
                    yield from descend(child, nxt)
                elif tag == f"{_KML_NS}Placemark":
                    geom = _placemark_geometry(child)
                    if geom is None:
                        continue  # legend stubs and style-only placemarks
                    seen += 1
                    name_el = child.find(f"{_KML_NS}name")
                    desc_el = child.find(f"{_KML_NS}description")
                    yield {
                        "fid": child.get("id") or f"pm{seen}",
                        "folder": folder,
                        "name": (name_el.text or "").strip() if name_el is not None else "",
                        "attrs": (
                            _parse_html_table(desc_el.text or "")
                            if desc_el is not None else {}
                        ),
                        "geometry": geom,
                    }

        yield from descend(root, None)

    # --- normalize -----------------------------------------------------------

    def normalize(self, rec: dict, raw: RawPayload) -> Optional[Derecho]:
        f = self.fuente
        attrs = rec["attrs"]
        folder = rec.get("folder")

        # The type comes from the folder. `attrs["Nombre"]` is the denominacion.
        self._check_folder(folder, rec["fid"])
        tipo = _FOLDER_TIPO.get(folder or "", "otro")
        expediente = attrs.get("Expediente") or rec["name"]
        self._check_expediente(expediente, rec["fid"])

        titular = N.strip_pii(attrs.get("Titular"))
        estado_raw = attrs.get("Vigencia") or attrs.get("Estado")
        mineral_raw = attrs.get("Mineral") or attrs.get("Sustancia")
        geom = N.round_coords(rec["geometry"], dp=5)

        d = Derecho(
            id=self.derecho_id(rec["fid"]),
            provincia=f.provincia,
            provincia_nombre=f.provincia_nombre,
            tipo=tipo,
            estado=N.map_estado(estado_raw, default=f.estado_fijo or "desconocido"),
            geom_kind=f.geom_kind,
            geometry=geom,
            expediente=str(expediente) if expediente else None,
            expediente_norm=N.norm_expediente(expediente),
            expediente_gde=attrs.get("Expediente_GDE"),
            # Preserve the province's own word ("pertenencias", "demasias")
            # rather than only the bucket it was mapped into.
            tipo_origen=folder,
            estado_origen=estado_raw,
            nombre=attrs.get("Nombre") or None,
            titular=titular,
            titular_norm=N.norm_titular(titular),
            titular_es_persona=N.titular_es_persona(titular),
            mineral=N.map_mineral(mineral_raw),
            mineral_origen=mineral_raw,
            superficie_ha=N.parse_ha(attrs.get("Superficie") or attrs.get("Area")),
            departamento=attrs.get("Departamento"),
            **self.provenance(raw, rec["fid"]),
        )
        validate_vocab(d)
        return d

    # --- guards --------------------------------------------------------------

    def __init__(self, fuente: Fuente):
        super().__init__(fuente)
        self._warned: set[str] = set()
        self.sin_folder = 0

    def _check_folder(self, folder: Optional[str], fid: str) -> None:
        """Report a Placemark whose folder is unknown or missing.

        The folder is the only carrier of type in this source, so an unmapped
        one silently turns a whole category into "otro". Reported once per
        distinct folder — a new provincial category is a finding, not noise.
        """
        if folder in _FOLDER_TIPO:
            return
        self.sin_folder += 1
        key = f"__folder__{folder}"
        if key not in self._warned:
            self._warned.add(key)
            print(
                f"  [aviso] {self.fuente.id}: carpeta sin mapeo de tipo: {folder!r} "
                f"(fid={fid}). Los derechos de esa carpeta caen en 'otro'; "
                f"agregar la carpeta a _FOLDER_TIPO."
            )

    def _check_expediente(self, expediente, fid: str) -> None:
        if not expediente or _RE_EXPEDIENTE.search(str(expediente)):
            return
        key = f"__expte__{str(expediente)[:12]}"
        if key not in self._warned and len(self._warned) < 40:
            self._warned.add(key)
            print(
                f"  [aviso] {self.fuente.id}: expediente con formato inesperado: "
                f"{expediente!r} (fid={fid}); se esperaba NNNN/AAAA."
            )


# --- helpers -----------------------------------------------------------------


def _parse_html_table(cdata: str) -> dict:
    """Extract label -> value pairs from the ArcGIS description table.

    Rows are two-cell (label, value); the outer wrapper rows have one cell and
    are skipped. ArcGIS writes literal "&lt;Null&gt;" for empty values.
    """
    out: dict = {}
    for tr in _RE_TR.findall(cdata or ""):
        tds = _RE_TD.findall(tr)
        if len(tds) != 2:
            continue
        label = html.unescape(_RE_TAGS.sub("", tds[0])).strip()
        value = html.unescape(_RE_TAGS.sub("", tds[1])).strip()
        if not label:
            continue
        if value in ("", "<Null>", "Null", "null"):
            value = None
        out[label.replace(" ", "_")] = value
    return out


def _coords(text: str) -> list[list[float]]:
    pts = []
    for tok in (text or "").replace("\n", " ").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                pts.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
    return pts


def _placemark_geometry(pm) -> Optional[dict]:
    """Build a (Multi)Polygon from a Placemark, honouring inner boundaries."""
    polys: list[list[list[list[float]]]] = []
    for poly in pm.iter(f"{_KML_NS}Polygon"):
        rings: list[list[list[float]]] = []
        outer = poly.find(f"{_KML_NS}outerBoundaryIs/{_KML_NS}LinearRing/{_KML_NS}coordinates")
        if outer is None or not (ring := _coords(outer.text)):
            continue
        rings.append(ring)
        for inner in poly.findall(f"{_KML_NS}innerBoundaryIs/{_KML_NS}LinearRing/{_KML_NS}coordinates"):
            if hole := _coords(inner.text):
                rings.append(hole)
        polys.append(rings)

    if not polys:
        return None
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}
