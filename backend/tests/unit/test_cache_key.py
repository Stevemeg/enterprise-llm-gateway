"""compute_cache_key tests (ADR-0016 Slice 10)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.ports.cache import CacheKey

ORG = uuid4()
OTHER_ORG = uuid4()


def test_same_semantic_request_produces_the_same_key() -> None:
    key1 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})
    key2 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})

    assert key1 == key2


def test_key_construction_is_independent_of_dict_insertion_order() -> None:
    key1 = compute_cache_key(
        ORG, provider="openai", model="gpt-4o", payload={"a": 1, "b": 2, "c": 3}
    )
    key2 = compute_cache_key(
        ORG, provider="openai", model="gpt-4o", payload={"c": 3, "a": 1, "b": 2}
    )

    assert key1 == key2


def test_different_payload_produces_a_different_key() -> None:
    key1 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})
    key2 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "bye"})

    assert key1 != key2


def test_a_field_that_looks_incidental_still_changes_the_key() -> None:
    """Nothing here knows which fields matter (e.g. temperature) - every field participates."""
    key1 = compute_cache_key(
        ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi", "temperature": 0.0}
    )
    key2 = compute_cache_key(
        ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi", "temperature": 0.9}
    )

    assert key1 != key2


def test_different_provider_produces_a_different_key() -> None:
    key1 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})
    key2 = compute_cache_key(ORG, provider="anthropic", model="gpt-4o", payload={"prompt": "hi"})

    assert key1 != key2


def test_different_model_produces_a_different_key() -> None:
    key1 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})
    key2 = compute_cache_key(ORG, provider="openai", model="gpt-4o-mini", payload={"prompt": "hi"})

    assert key1 != key2


def test_different_organization_produces_a_different_key_even_for_identical_content() -> None:
    """Tenant identity is baked into the digest itself - defence in depth beyond RLS/query
    filters, and the only isolation layer InMemoryResponseCache has."""
    key1 = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})
    key2 = compute_cache_key(OTHER_ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})

    assert key1 != key2


def test_key_is_a_sha256_digest_wrapped_in_a_typed_cache_key() -> None:
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hi"})

    assert isinstance(key, CacheKey)
    assert len(key.digest) == 32
    assert len(key.hex) == 64


def test_cache_key_rejects_a_malformed_digest_length() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        CacheKey(b"too-short")
