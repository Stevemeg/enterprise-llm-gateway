"""The PKCE ``code_verifier`` must never escape the state store (ADR-0015 §Security considerations).

The verifier is the one value in ``oidc_login_state`` stored in plaintext (the protocol requires
presenting the original at token exchange). That is an accepted, bounded risk *only* while the value
stays confined: it must not reach logs, audit events, exception messages, tracebacks, metrics, or
API responses. This is a regression guard so a future logging or error-handling change cannot
silently start leaking it.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

import pytest

from gateway.adapters.security.oidc_provider import (
    OidcExchangeError,
    OidcProviderAdapter,
    OidcProviderConfig,
)
from gateway.adapters.security.oidc_state import generate_pkce_pair

_ISSUER = "https://idp.example.com"


class ExplodingClient:
    """Token endpoint that fails — the path most likely to spill request data into an error."""

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("upstream token endpoint exploded")


def _adapter() -> OidcProviderAdapter:
    config = OidcProviderConfig(
        issuer=_ISSUER,
        client_id="gateway-client",
        client_secret="super-secret-client-secret",
        authorization_endpoint=f"{_ISSUER}/authorize",
        token_endpoint=f"{_ISSUER}/token",
        jwks_uri=f"{_ISSUER}/jwks",
    )
    return OidcProviderAdapter(config, jwks_cache=None, client=ExplodingClient())  # type: ignore[arg-type]


async def test_verifier_absent_from_exception_message_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    verifier, _ = generate_pkce_pair()
    caplog.set_level(logging.DEBUG)

    with pytest.raises(OidcExchangeError) as exc_info:
        await _adapter().exchange_code(
            code="auth-code", code_verifier=verifier, redirect_uri="https://gw.example/callback"
        )

    rendered = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert verifier not in str(exc_info.value), "verifier leaked into the exception message"
    assert verifier not in rendered, "verifier leaked into the traceback"
    assert verifier not in caplog.text, "verifier leaked into logs"


async def test_client_secret_absent_from_exception_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same containment must hold for the IdP client secret sent alongside the verifier."""
    verifier, _ = generate_pkce_pair()
    caplog.set_level(logging.DEBUG)

    with pytest.raises(OidcExchangeError) as exc_info:
        await _adapter().exchange_code(
            code="auth-code", code_verifier=verifier, redirect_uri="https://gw.example/callback"
        )

    rendered = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert "super-secret-client-secret" not in str(exc_info.value)
    assert "super-secret-client-secret" not in rendered
    assert "super-secret-client-secret" not in caplog.text


def test_verifier_not_present_in_authorization_url() -> None:
    """Only the S256 challenge may travel to the IdP — never the verifier itself."""
    from gateway.adapters.security.jwks_cache import JwksCache

    class _NoTransport:
        async def fetch(self) -> dict[str, Any]:  # pragma: no cover - never called here
            return {"keys": []}

    class _Clock:
        def now(self) -> Any:
            from datetime import UTC, datetime

            return datetime(2026, 7, 18, tzinfo=UTC)

    config = OidcProviderConfig(
        issuer=_ISSUER,
        client_id="gateway-client",
        client_secret="s",
        authorization_endpoint=f"{_ISSUER}/authorize",
        token_endpoint=f"{_ISSUER}/token",
        jwks_uri=f"{_ISSUER}/jwks",
    )
    adapter = OidcProviderAdapter(config, JwksCache(_NoTransport(), _Clock()), client=None)  # type: ignore[arg-type]

    request = adapter.build_authorization_url(
        state="signed-state", redirect_uri="https://gw.example/callback"
    )

    assert request.code_verifier not in request.authorization_url
    assert request.code_challenge in request.authorization_url
