"""Adapter registry: maps each source's `kind` onto its implementation."""

from adapters.base import Adapter, BaseAdapter, Probe, RawPayload  # noqa: F401
from adapters.wfs import WfsAdapter
from fuentes import Fuente


def build_adapter(fuente: Fuente):
    """Instantiate the adapter for a source, by kind.

    `tabular` and `manual` sources are declared in the registry before they are
    wired up, so that the coverage page can honestly report "declarada, no
    implementada" instead of pretending the province does not exist.
    """
    if fuente.kind == "wfs":
        return WfsAdapter(fuente)
    if fuente.kind == "kml":
        from adapters.kml import KmlAdapter

        return KmlAdapter(fuente)
    if fuente.kind == "shapefile":
        from adapters.shp import ShpAdapter

        return ShpAdapter(fuente)
    if fuente.kind in ("tabular", "manual", "ninguna"):
        raise NotImplementedError(
            f"{fuente.id}: fuente '{fuente.kind}' declarada pero no implementada"
        )
    raise ValueError(f"{fuente.id}: kind desconocido {fuente.kind!r}")
