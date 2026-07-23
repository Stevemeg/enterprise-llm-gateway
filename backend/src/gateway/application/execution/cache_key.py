"""Deterministic cache-identity canonicalization (ADR-0016 Slice 10).

Cache identity must be reproducible across processes and over time, so it cannot use Python's
``hash()`` (process-randomized by default via ``PYTHONHASHSEED``, specifically to prevent reuse as
a stable identity) or ``repr()``/``str()`` of a dict (no canonical ordering guarantee a caller can
rely on). A canonical JSON encoding (sorted keys, no incidental whitespace) makes two
semantically-identical payloads hash identically regardless of how their caller happened to
construct the dict; SHA-256 is a deterministic cryptographic digest, not a security signature -
collision resistance is the only property this needs.

Organization, provider and model are baked into the digest itself rather than left to a caller to
remember to filter by afterwards - defence in depth alongside RLS/explicit tenant-scoped queries in
``SqlResponseCache``, and the *only* isolation layer ``InMemoryResponseCache`` has.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from gateway.application.ports.cache import CacheKey
from gateway.shared.secrets import sha256_bytes


def compute_cache_key(
    organization_id: UUID, *, provider: str, model: str, payload: Mapping[str, Any]
) -> CacheKey:
    """A deterministic identity for one cacheable request.

    Deliberately excludes ``correlation_id`` - see ``application/ports/cache.py``'s module
    docstring. Deliberately includes the entire payload verbatim: nothing here knows which fields
    (temperature, seed, tools, ...) make two requests semantically different, and guessing which
    to drop would be exactly the silent, undocumented convention Rule 3 exists to prevent. A
    request whose payload differs by even one field - including any randomness/temperature
    setting a caller sent - is, correctly, a cache miss.
    """
    canonical_payload = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    material = "\x00".join((str(organization_id), provider, model, canonical_payload))
    return CacheKey(sha256_bytes(material))
