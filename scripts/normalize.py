"""Field-level normalization across provincial sources.

Every function here exists because a real source does something surprising.
The comments name the source and the surprise; do not "simplify" them away
without re-checking the live data.
"""

import re
import unicodedata
from datetime import date
from typing import Optional

from esquema import TIPOS, ESTADOS

# --- hectares ----------------------------------------------------------------

_HA_RE = re.compile(r"[-+]?[\d.,]+")


def parse_ha(value) -> Optional[float]:
    """Parse a declared surface into hectares.

    Salta ships strings like "774,7280 ha" — comma decimal, unit suffix.
    San Juan ships a plain float (64.3859). Both must land on 774.728 / 64.3859.

    Separator rule: if BOTH "," and "." appear, the "." is a thousands separator
    (es-AR convention: "1.234,56"); otherwise a lone "," is the decimal mark.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)

    m = _HA_RE.search(str(value).strip())
    if not m:
        return None
    s = m.group(0)

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        ha = float(s)
    except ValueError:
        return None
    return ha if ha >= 0 else None


# --- dates -------------------------------------------------------------------


def parse_fecha(value) -> Optional[str]:
    """Parse a source date into an ISO date string, or None.

    Salta serves dates as '2013-07-29Z' — a *date* with a trailing Z, which
    `date.fromisoformat` rejects. San Juan serves full timestamps
    ('1968-03-18T00:00:00Z'). Both reduce to '1968-03-18'.

    The Codigo de Mineria is from 1886, so anything before 1850 or in the
    future is a data-entry error and is dropped rather than propagated.
    """
    if value is None or value == "":
        return None
    s = str(value).strip()
    if not s or s.lower() in ("<null>", "null", "none", "-"):
        return None

    s = s.rstrip("Z")
    if "T" in s:
        s = s.split("T", 1)[0]
    s = s[:10]

    # dd/mm/yyyy is common in the tabular sources
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            s = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

    try:
        d = date.fromisoformat(s)
    except ValueError:
        return None
    if d.year < 1850 or d > date.today():
        return None
    return d.isoformat()


# --- titular -----------------------------------------------------------------

_SUFIJOS_SOCIETARIOS = (
    "SAU", "SRL", "SCA", "SAS", "SA", "SC", "SH", "LTD", "LTDA", "INC", "CORP",
    "LLC", "PLC", "NV", "BV", "GMBH", "COOP", "UTE", "SE", "SAIC", "SACIF",
    "SAICYF", "SAMIC", "SACI", "EIRL",
)
# Tokens that mark an organisation even without a legal suffix.
_TOKENS_EMPRESA = (
    "MINERA", "MINING", "MINERALES", "COMPANIA", "COMPANY", "CIA", "GRUPO",
    "GROUP", "RESOURCES", "RECURSOS", "EXPLORACIONES", "SOCIEDAD", "COOPERATIVA",
    "MUNICIPALIDAD", "GOBIERNO", "PROVINCIA", "ESTADO", "EMPRESA", "INDUSTRIAS",
    "CANTERAS", "ARIDOS", "CEMENTOS", "CALERA", "YACIMIENTOS", "ENERGIA", "LITIO",
    "LITHIUM", "GOLD", "COPPER", "SILVER", "ORO", "PLATA", "COBRE", "HOLDING",
    "INTERNATIONAL", "ARGENTINA", "ANDES", "SUDAMERICANA",
)

# Never publish these even if a source leaks them into a free-text field.
_PII_RE = re.compile(
    r"\b(?:DNI|D\.N\.I\.|CUIT|CUIL|C\.U\.I\.T\.|LE|LC)\b[\s:.\-]*[\d.\-]{6,}",
    re.IGNORECASE,
)
# Jujuy's cadastre export carries holder e-mail addresses in `dom_corre`. That
# column is dropped at the adapter, but a stray address in a free-text field
# must not survive either.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def strip_pii(value: Optional[str]) -> Optional[str]:
    """Remove identity-document numbers from free text.

    The cadastre is a public registry and `titular` is frequently a natural
    person, which is fine to republish — a DNI or CUIT is not.
    """
    if not value:
        return value
    out = _EMAIL_RE.sub("", _PII_RE.sub("", str(value)))
    return re.sub(r"\s{2,}", " ", out).strip(" ,;.-") or None


# Values that provinces write into the `titular` column that are not holders:
# they are statuses. Salta writes "Vacancia Solicitada" (111 records) and
# Neuquen "VACANTE" (107). Left alone they become phantom companies in the
# national ranking and in the neighbour tables of client reports.
_NO_ES_TITULAR = {
    "vacante", "vacancia", "vacancia solicitada", "vacante solicitada",
    "sin titular", "sin datos", "s/d", "sd", "n/a", "na", "desconocido",
    "libre", "ver", "---", "--", "-", "xxx", "null", "none",
}


def titular_valido(value: Optional[str]) -> Optional[str]:
    """Return the holder name, or None when the field carries a status instead.

    Applied before any other titular processing, so a sentinel never reaches
    `norm_titular` and never becomes a row in a ranking.
    """
    if not value:
        return None
    k = re.sub(r"\s+", " ", _strip_accents(str(value)).lower()).strip(" .-")
    if k in _NO_ES_TITULAR:
        return None
    return str(value).strip() or None


def _tokens(value: str) -> list[str]:
    """Uppercase, unaccented tokens with legal suffixes collapsed but kept.

    Periods collapse BEFORE other punctuation becomes whitespace, so "S.A."
    survives as the single token "SA" and matches the suffix list. Splitting it
    into "S" and "A" is what previously made `titular_es_persona` report
    "Glencore Pachon S.A." as a natural person.
    """
    s = _strip_accents(str(value)).upper().replace(".", "")
    s = re.sub(r"[^\w\s]", " ", s)
    return [t for t in s.split() if t]


def norm_titular(value: Optional[str]) -> Optional[str]:
    """Canonical join key for a title holder.

    Uppercase, unaccented, legal suffixes and punctuation removed, whitespace
    collapsed — so "Glencore Pachón S.A." and "GLENCORE PACHON S A" collapse to
    the same key and stop being two rows in the national ranking.
    """
    if not value:
        return None
    tokens = [t for t in _tokens(strip_pii(value) or "") if t not in _SUFIJOS_SOCIETARIOS]
    # Trailing single letters are a spaced-out legal suffix ("S R L", "S A S").
    while len(tokens) > 1 and len(tokens[-1]) == 1:
        tokens.pop()
    out = " ".join(tokens).strip()
    return out or None


def titular_es_persona(value: Optional[str]) -> Optional[bool]:
    """Heuristic: is this title holder a natural person rather than a company?

    Drives the privacy policy — companies are named in the national top-titulares
    ranking, natural persons are aggregated into a count. Individuals stay
    visible in their own feature popup, which is the registry's own publicity.

    Returns None when there is no name to judge.
    """
    if not value:
        return None
    tokens = _tokens(value)
    if not tokens:
        return None
    if any(t in _SUFIJOS_SOCIETARIOS for t in tokens):
        return False
    if any(t in _TOKENS_EMPRESA for t in tokens):
        return False
    # A spaced-out legal suffix ("GLENCORE PACHON S A") arrives as trailing
    # single letters. Without this, a 4-token company reads as a personal name
    # and gets aggregated out of the public top-titulares ranking.
    core = list(tokens)
    trailing_initials = 0
    while len(core) > 1 and len(core[-1]) == 1:
        core.pop()
        trailing_initials += 1
    if trailing_initials >= 2:
        return False
    # A personal name is typically 2-4 tokens, all alphabetic.
    if 2 <= len(core) <= 4 and all(t.isalpha() for t in core):
        return True
    return False


# --- tipo / estado -----------------------------------------------------------

_TIPO_MAP = {
    "mina": "mina",
    "minas": "mina",
    "pertenencia": "mina",
    "pertenencias": "mina",
    "cateo": "cateo",
    "cateos": "cateo",
    "permiso de exploracion": "cateo",
    "permisos de exploracion": "cateo",
    "exploracion": "cateo",
    "manifestacion": "manifestacion_descubrimiento",
    "manifestacion de descubrimiento": "manifestacion_descubrimiento",
    "descubrimiento": "manifestacion_descubrimiento",
    "cantera": "cantera",
    "canteras": "cantera",
    "arido": "cantera",
    "aridos": "cantera",
    "servidumbre": "servidumbre",
    "servidumbres": "servidumbre",
    "solicitud": "solicitud",
    "solicitudes": "solicitud",
    "provisorio": "solicitud",
    "provisorios": "solicitud",
    "planta": "planta",
    "plantas": "planta",
    "amparo": "area_proteccion",
    "area de amparo": "area_proteccion",
    "reserva": "area_proteccion",
    # Salta-specific categories found in live data (2026-07-28):
    # a "grupo minero" is several pertenencias administered as one unit.
    "grupo minero": "mina",
    "zona de investigacion geologica minera": "area_proteccion",
    # "Convenio" (202 records in Salta) is an agreement with the province, not
    # a tenement category — it stays "otro" deliberately rather than being
    # forced into a bucket it does not belong in.
}

_ESTADO_MAP = {
    "vigente": "vigente",
    "vigentes": "vigente",
    "activo": "vigente",
    "activa": "vigente",
    "concedida": "vigente",
    "otorgada": "vigente",
    "tramite": "tramite",
    "en tramite": "tramite",
    "provisorio": "tramite",
    "solicitado": "tramite",
    "pendiente": "tramite",
    "caduco": "caduco",
    "caduca": "caduco",
    "caducado": "caduco",
    "caducada": "caduco",
    "vencido": "caduco",
    "desistido": "desistido",
    "desistida": "desistido",
    "renunciado": "desistido",
    "vacante": "vacante",
    "libre": "vacante",
    "hist": "caduco",
    # Salta live data (2026-07-28): a registration annulled before publication
    # never became an effective right.
    "anulacion": "caduco",
    "anulado": "caduco",
    "anulada": "caduco",
    # Neuquen canteras carry a boolean "Vigencia" column rather than a status.
    "si": "vigente",
    "no": "caduco",
    # Jujuy: a mina "INCLUIDA EN G. M. AGUILAR" is administered as part of a
    # grupo minero (Aguilar is a working Pb-Zn-Ag mine). It is an effective
    # right, not an unknown state — 283 of 1.784 records, so leaving them
    # "desconocido" would misreport 16% of the province.
    "incluida": "vigente",
    "registrada": "vigente",
    # Mendoza live data (2026-08-01): prescription extinguishes the right, so it
    # is unambiguously caduco. The province's other labels are NOT mapped on
    # purpose — "Archivado", "Borrado", "Perdido" and "Graficado con
    # observaciones" describe the state of the file, not of the right, and
    # forcing them into a bucket would overstate what the source says.
    "prescripta": "caduco",
    "prescripto": "caduco",
}


def _key(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", _strip_accents(str(value or "")).lower()).strip()


# Fragments shorter than this are matched exactly and never as substrings.
# Without the guard, the two-letter "si" (Neuquen's boolean Vigencia column)
# would match inside "sin publicar" and "desistido" and silently mark caduco
# records as vigente.
_MIN_FRAG = 4


def _lookup(k: str, tabla: dict[str, str]) -> Optional[str]:
    if k in tabla:
        return tabla[k]
    for frag, target in tabla.items():
        if len(frag) >= _MIN_FRAG and frag in k:
            return target
    return None


def map_tipo(value: Optional[str], default: Optional[str] = None) -> str:
    """Map a local type label onto the controlled vocabulary.

    `default` is the registry's `tipo_fijo` for sources where the layer itself
    is the type (San Juan, Cordoba) rather than a column.
    """
    hit = _lookup(_key(value), _TIPO_MAP)
    if hit:
        return hit
    if default in TIPOS:
        return default
    return "otro"


def map_estado(value: Optional[str], default: Optional[str] = None) -> str:
    hit = _lookup(_key(value), _ESTADO_MAP)
    if hit:
        return hit
    if default in ESTADOS:
        return default
    return "desconocido"


# --- minerals ----------------------------------------------------------------

# Sources mix chemical symbols (Salta: "Li") with Spanish names (San Juan:
# "Cobre", Catamarca: "Litio"). Normalize to symbols where one exists.
_MINERAL_MAP = {
    "li": "Li", "litio": "Li", "lithium": "Li",
    "cu": "Cu", "cobre": "Cu", "copper": "Cu",
    "au": "Au", "oro": "Au", "gold": "Au",
    "ag": "Ag", "plata": "Ag", "silver": "Ag",
    "pb": "Pb", "plomo": "Pb",
    "zn": "Zn", "zinc": "Zn", "cinc": "Zn",
    "sn": "Sn", "estano": "Sn",
    "u": "U", "uranio": "U",
    "fe": "Fe", "hierro": "Fe",
    "mo": "Mo", "molibdeno": "Mo",
    "mn": "Mn", "manganeso": "Mn",
    "b": "B", "boro": "B", "borato": "B", "boratos": "B",
    "k": "K", "potasio": "K",
    "arido": "aridos", "aridos": "aridos", "arena": "aridos", "canto rodado": "aridos",
    "caliza": "caliza", "calcareo": "caliza", "cal": "caliza",
    "yeso": "yeso", "sal": "sal", "halita": "sal",
    "marmol": "marmol", "granito": "granito", "cuarzo": "cuarzo",
    "bentonita": "bentonita", "arcilla": "arcilla", "talco": "talco",
    "diatomita": "diatomita", "perlita": "perlita", "mica": "mica",
    "travertino": "travertino", "onix": "onix", "feldespato": "feldespato",
}

_SPLIT_RE = re.compile(r"[,;/|+]| y | e |-")


def map_mineral(value: Optional[str]) -> list[str]:
    """Split a mineral field into a list of normalized codes.

    Sources put several substances in one string ("Au, Ag", "Oro y Plata").
    Unrecognised substances are kept verbatim (title-cased) rather than dropped —
    an unknown mineral is information, not noise.
    """
    if not value:
        return []
    out: list[str] = []
    for part in _SPLIT_RE.split(str(value)):
        k = _key(part)
        if not k:
            continue
        code = _MINERAL_MAP.get(k)
        if code is None:
            # try a contained match for things like "mineral de cobre"
            for frag, c in _MINERAL_MAP.items():
                if len(frag) > 2 and frag in k:
                    code = c
                    break
        if code is None:
            code = part.strip().title()
        if code and code not in out:
            out.append(code)
    return out


# --- expediente --------------------------------------------------------------

def norm_expediente(value: Optional[str]) -> Optional[str]:
    """Canonicalise an expediente for joins and duplicate detection.

    Formats vary wildly: "2737/2005" (Neuquen), "1100-000337-2020-HIST"
    (San Juan), bare integers (Salta). Reduce to digits and dashes, uppercase,
    with leading zeros in each numeric group stripped so that "000337" and
    "337" match.
    """
    if value is None or value == "":
        return None
    s = _strip_accents(str(value)).upper().strip()
    s = re.sub(r"[^\w/\-]", "", s)
    s = s.replace("/", "-")
    groups = [g for g in re.split(r"-+", s) if g]
    norm = "-".join(g.lstrip("0") or "0" if g.isdigit() else g for g in groups)
    return norm or None


def round_coords(geom: dict, dp: int = 5) -> dict:
    """Round GeoJSON coordinates in place-ish, returning a new geometry.

    5 dp is ~1.1 m at these latitudes — right for cadastral boundaries.
    4 dp (11 m) would be visibly wrong on a parcel corner. This is the single
    biggest lever on payload size after dropping unused fields.
    """
    def _round(c):
        if isinstance(c, (int, float)):
            return round(c, dp)
        return [_round(x) for x in c]

    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
