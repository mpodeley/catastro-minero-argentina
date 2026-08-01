"""Regression tests for the normalization traps.

Every case here is drawn from live provincial data, not invented. Run with:

    ~/miniforge3/bin/mamba run -n insar python scripts/test_normalize.py

Plain asserts and a main() so this runs with no test-runner dependency, matching
the zero-dependency habit of the other pipelines in this account.
"""

import sys

import normalize as N
import crs as C


CASES: list[tuple[str, object, object]] = []


def check(label, got, want):
    CASES.append((label, got, want))


def main() -> int:
    # --- hectares (Salta ships comma decimals with a unit suffix) -------------
    check("parse_ha salta", N.parse_ha("774,7280 ha"), 774.728)
    check("parse_ha miles", N.parse_ha("1.234,56 ha"), 1234.56)
    check("parse_ha float", N.parse_ha(64.3859), 64.3859)
    check("parse_ha punto decimal", N.parse_ha("64.3859"), 64.3859)
    check("parse_ha vacio", N.parse_ha(""), None)
    check("parse_ha None", N.parse_ha(None), None)

    # --- dates ---------------------------------------------------------------
    # Salta: a date with a trailing Z, which date.fromisoformat rejects.
    check("fecha salta Z", N.parse_fecha("2013-07-29Z"), "2013-07-29")
    # San Juan: full timestamp.
    check("fecha san juan", N.parse_fecha("1968-03-18T00:00:00Z"), "1968-03-18")
    check("fecha dd/mm/yyyy", N.parse_fecha("18/03/1968"), "1968-03-18")
    check("fecha <Null>", N.parse_fecha("<Null>"), None)
    # Codigo de Mineria is 1886; anything older is a data-entry error.
    check("fecha absurda", N.parse_fecha("1200-01-01"), None)
    check("fecha futura", N.parse_fecha("2099-01-01"), None)

    # --- titular -------------------------------------------------------------
    # The join key must collapse spelling variants of the same company.
    check("titular acentos", N.norm_titular("Glencore Pachón S.A."), "GLENCORE PACHON")
    check("titular espaciado", N.norm_titular("GLENCORE PACHON S A"), "GLENCORE PACHON")
    check("titular srl", N.norm_titular("AB Construcciones S.R.L."), "AB CONSTRUCCIONES")
    check("titular sas", N.norm_titular("7 Hermanos S.A.S."), "7 HERMANOS")
    check(
        "titular sin sufijo",
        N.norm_titular("POTASIO Y LITIO DE ARGENTINA S.A"),
        "POTASIO Y LITIO DE ARGENTINA",
    )

    # This heuristic decides whether a holder is named in the public ranking or
    # aggregated into a count, so a company misread as a person is a privacy
    # *and* a correctness bug: Glencore would vanish from the top-titulares table.
    check("persona: empresa con punto", N.titular_es_persona("Glencore Pachón S.A."), False)
    check("persona: empresa espaciada", N.titular_es_persona("GLENCORE PACHON S A"), False)
    check("persona: minera sin sufijo", N.titular_es_persona("MINERA ANDES RESOURCES"), False)
    check("persona: fisica", N.titular_es_persona("Achaval Facundo Jose"), True)
    check("persona: vacio", N.titular_es_persona(""), None)

    # PII must never survive into the published dataset.
    check("pii dni", N.strip_pii("JUAN PEREZ DNI 12.345.678"), "JUAN PEREZ")
    check("pii cuit", N.strip_pii("ACME SA CUIT 30-12345678-9"), "ACME SA")

    # --- tipo / estado -------------------------------------------------------
    check("tipo mina", N.map_tipo("Mina"), "mina")
    check("tipo cateo kml", N.map_tipo("CATEO"), "cateo")
    # Salta-specific categories observed live on 2026-07-28.
    check("tipo grupo minero", N.map_tipo("Grupo Minero"), "mina")
    check("tipo zona investigacion", N.map_tipo("Zona de Investigación Geológica Minera"), "area_proteccion")
    # "Convenio" is deliberately NOT forced into a tenement bucket.
    check("tipo convenio", N.map_tipo("Convenio"), "otro")
    # When the layer IS the type (San Juan, Cordoba), the default wins.
    check("tipo por defecto", N.map_tipo(None, default="cateo"), "cateo")

    check("estado vigente", N.map_estado("Vigente"), "vigente")
    check("estado anulacion", N.map_estado("Anulación de registro sin publicar (REMSa)"), "caduco")
    check("estado hist", N.map_estado("HIST"), "caduco")
    check("estado desconocido", N.map_estado(None), "desconocido")
    # Neuquen canteras carry a boolean Vigencia column.
    check("estado vigencia SI", N.map_estado("SI"), "vigente")
    # ...and "si" must stay an exact match: as a substring it would flip
    # "sin publicar" and "desistido" to vigente.
    check("estado sin publicar", N.map_estado("Sin publicar"), "desconocido")
    check("estado desistido", N.map_estado("Desistido"), "desistido")
    check("estado sin datos", N.map_estado("Sin datos"), "desconocido")
    # Jujuy: pertenencia administered inside a grupo minero — an effective right.
    check("estado grupo minero", N.map_estado("INCLUIDA EN G. M. AGUILAR"), "vigente")
    check("estado registrada", N.map_estado("REGISTRADA"), "vigente")
    # Mendoza: the source writes these with a leading space and mixed case.
    check("estado prescripta", N.map_estado(" Prescripta"), "caduco")
    check("estado prescripta minuscula", N.map_estado(" prescripta"), "caduco")
    # Deliberately NOT mapped: these describe the file, not the right. If one of
    # them ever starts resolving to vigente/caduco, someone widened the table
    # past what the province actually says.
    check("estado archivado", N.map_estado("Archivado"), "desconocido")
    check("estado graficado con obs", N.map_estado("Graficado con observaciones."), "desconocido")
    check("estado se desconoce", N.map_estado("Se desconoce"), "desconocido")
    check("estado guion", N.map_estado("-"), "desconocido")

    # --- Jujuy shapefile specifics -------------------------------------------
    # `dom_corre` carries holder e-mail addresses; the adapter drops the column,
    # but a stray address in any free-text field must not survive either.
    check("pii email", N.strip_pii("DAJIN RESOURCES S.A. feleit@gmail.com"), "DAJIN RESOURCES S.A")
    check("pii solo email", N.strip_pii("feleit@gmail.com"), None)

    # Statuses that provinces write into the titular column, not holders.
    check("titular vacante salta", N.titular_valido("Vacancia Solicitada"), None)
    check("titular vacante neuquen", N.titular_valido("VACANTE"), None)
    check("titular ver", N.titular_valido("VER"), None)
    check("titular real pasa", N.titular_valido("HANAQ ARGENTINA S.A"), "HANAQ ARGENTINA S.A")
    check("titular vacio", N.titular_valido(""), None)

    # --- minerals ------------------------------------------------------------
    check("mineral simbolo", N.map_mineral("Li"), ["Li"])
    check("mineral nombre", N.map_mineral("Cobre"), ["Cu"])
    check("mineral catamarca", N.map_mineral("Litio"), ["Li"])
    check("mineral multiple", N.map_mineral("Au, Ag"), ["Au", "Ag"])
    check("mineral con y", N.map_mineral("Oro y Plata"), ["Au", "Ag"])
    check("mineral vacio", N.map_mineral(None), [])

    # --- expediente ----------------------------------------------------------
    check("expte san juan", N.norm_expediente("1100-000337-2020-HIST"), "1100-337-2020-HIST")
    check("expte neuquen", N.norm_expediente("2737/2005"), "2737-2005")
    check("expte salta", N.norm_expediente("22077"), "22077")

    # --- CRS -----------------------------------------------------------------
    # The false easting is faja*1e6 + 500_000, so the leading digit is the faja.
    check("faja salta", C.faja_from_easting(3498590.83), 3)
    check("faja san juan", C.faja_from_easting(2364782.8), 2)
    check("faja invalida", C.faja_from_easting(-70.4), None)
    check("epsg faja 2 posgar07", C.epsg_for_faja(2, "posgar2007"), 5344)
    check("epsg faja 3 campo inchauspe", C.epsg_for_faja(3, "campo_inchauspe"), 22193)

    # Datum identities are asserted, not assumed: 2217x / 2218x / 2219x are
    # adjacent codes for three different datums and transpose easily by eye.
    # pyproj spells POSGAR out as "Posiciones Geodesicas Argentinas <year>".
    check("cordoba 22173 es posgar 98", C.describe(22173)["datum"], "Posiciones Geodesicas Argentinas 1998")
    check("san juan 5344 es posgar 2007", C.describe(5344)["datum"], "Posiciones Geodesicas Argentinas 2007")
    check("22183 es posgar 94", C.describe(22183)["datum"], "Posiciones Geodesicas Argentinas 1994")
    # The one that actually matters: Campo Inchauspe is a different datum, and
    # its faja 3 (22193) sits one digit away from Cordoba's 22173.
    check("22193 es campo inchauspe", C.describe(22193)["datum"], "Campo Inchauspe")
    check("epsg faja 3 posgar98", C.epsg_for_faja(3, "posgar98"), 22173)

    # Guards against a source that declares 4326 and serves metres anyway.
    check(
        "projected detectado",
        C.looks_like_projected({"type": "Point", "coordinates": [3498590.0, 7389857.0]}),
        True,
    )
    check(
        "grados no son projected",
        C.looks_like_projected({"type": "Point", "coordinates": [-66.01, -23.61]}),
        False,
    )
    check("en argentina", C.in_argentina(-66.0, -24.0), True)
    check("fuera de argentina", C.in_argentina(-10.0, 40.0), False)

    # --- report --------------------------------------------------------------
    failed = [(l, g, w) for l, g, w in CASES if g != w]
    for label, got, want in failed:
        print(f"FAIL  {label}\n        esperado: {want!r}\n        obtenido: {got!r}")
    print(f"\n{len(CASES) - len(failed)}/{len(CASES)} casos OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
