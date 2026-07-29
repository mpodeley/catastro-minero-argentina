"""Adapter protocol shared by every provincial source.

Four calls, deliberately separated so that the daily health check can run
`probe()` alone — ~15 cheap requests — without downloading anything:

    probe()      cheap liveness + shape check, no full download
    fetch()      download to raw/, honouring etag + sha256 cache
    parse()      raw payload -> source-shaped dicts
    normalize()  source-shaped dict -> Derecho
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterator, Optional, Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fuentes import Fuente


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_session(headers: Optional[dict] = None) -> requests.Session:
    """Retrying HTTP session.

    Same policy as estado-red-gas/scripts/fetch_concesiones_geojson.py:
    provincial servers are small and intermittently flaky, and a 502 on one
    request should not lose a whole province.
    """
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    if headers:
        s.headers.update(headers)
    return s


@dataclass
class Probe:
    """Result of a cheap liveness check. Diffed run-over-run to detect drift."""

    fuente_id: str
    ok: bool
    checked_at: str
    http_status: Optional[int] = None
    feature_count: Optional[int] = None
    field_names: list[str] = field(default_factory=list)
    geom_type: Optional[str] = None
    srid: Optional[int] = None
    resolved_layer: Optional[str] = None
    elapsed_ms: Optional[int] = None
    error: Optional[str] = None
    # File-backed sources cannot report a feature count without downloading,
    # so they report size instead. Kept in its own field: overloading
    # feature_count with a negative number made the drift diff compare bytes
    # against features and report -7305%.
    bytes: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RawPayload:
    """A downloaded source payload plus everything needed to cite it."""

    fuente_id: str
    url: str
    body: bytes
    sha256: str
    fetched_at: str
    from_cache: bool = False
    resolved_layer: Optional[str] = None
    meta: dict = field(default_factory=dict)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Adapter(Protocol):
    fuente: Fuente

    def probe(self) -> Probe: ...
    def fetch(self, cache_dir: str) -> RawPayload: ...
    def parse(self, raw: RawPayload) -> Iterator[dict]: ...
    def normalize(self, rec: dict, raw: RawPayload): ...


class BaseAdapter:
    """Shared caching + provenance plumbing."""

    def __init__(self, fuente: Fuente):
        self.fuente = fuente
        self.session = make_session(fuente.headers)

    # --- cache ---------------------------------------------------------------

    def _cache_paths(self, cache_dir: str, ext: str = "bin") -> tuple[str, str]:
        safe = self.fuente.id.replace(":", "_")
        os.makedirs(cache_dir, exist_ok=True)
        return (
            os.path.join(cache_dir, f"{safe}.{ext}"),
            os.path.join(cache_dir, f"{safe}.meta.json"),
        )

    def _load_cache(self, cache_dir: str, ext: str = "bin") -> Optional[RawPayload]:
        body_path, meta_path = self._cache_paths(cache_dir, ext)
        if not (os.path.exists(body_path) and os.path.exists(meta_path)):
            return None
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        with open(body_path, "rb") as f:
            body = f.read()
        if sha256_bytes(body) != meta.get("sha256"):
            return None  # corrupt cache, refetch
        return RawPayload(
            fuente_id=self.fuente.id,
            url=meta.get("url", self.fuente.url),
            body=body,
            sha256=meta["sha256"],
            fetched_at=meta.get("fetched_at", utcnow()),
            from_cache=True,
            resolved_layer=meta.get("resolved_layer"),
            meta=meta.get("meta", {}),
        )

    def _save_cache(self, cache_dir: str, raw: RawPayload, ext: str = "bin") -> None:
        body_path, meta_path = self._cache_paths(cache_dir, ext)
        with open(body_path, "wb") as f:
            f.write(raw.body)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "fuente_id": raw.fuente_id,
                    "url": raw.url,
                    "sha256": raw.sha256,
                    "fetched_at": raw.fetched_at,
                    "resolved_layer": raw.resolved_layer,
                    "bytes": len(raw.body),
                    "meta": raw.meta,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    # --- http ----------------------------------------------------------------

    def _get(self, url: str, params: Optional[dict] = None, timeout: int = 120):
        t0 = time.time()
        r = self.session.get(url, params=params, timeout=timeout)
        self._last_elapsed_ms = int((time.time() - t0) * 1000)
        self._last_url = r.url
        r.raise_for_status()
        return r

    # --- provenance ----------------------------------------------------------

    def provenance(self, raw: RawPayload, source_fid: str) -> dict:
        """The provenance block every Derecho carries.

        Per-feature provenance is the differentiator over every official
        provincial viewer, none of which tell you when the data was cut.
        """
        f = self.fuente
        return {
            "fuente_id": f.id,
            "source_url": raw.url,
            "source_layer": raw.resolved_layer or f.layer or f.url,
            "source_fid": str(source_fid),
            "source_srid": int(f.srid_declarado or 4326),
            "fetched_at": raw.fetched_at,
            "source_sha256": raw.sha256,
            "licencia": f.licencia,
        }

    def derecho_id(self, source_fid: str) -> str:
        short = self.fuente.id.split(".")[-1]
        return f"{self.fuente.provincia}:{short}:{source_fid}"
