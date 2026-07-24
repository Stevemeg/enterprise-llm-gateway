"""Bearer-token ``Authenticator`` over an ``AccessTokenVerifier`` (ADR-0016 Slice 17).

``AuthenticationMiddleware`` requires an ``Authenticator`` (``async authenticate(credential) ->
Principal``). ``JwtTokenService`` already satisfies ``AccessTokenVerifier`` (``verify(token) ->
Principal``, synchronous) and is already built in the composition root. This adapter is the small
piece between the two - it chooses no policy and verifies nothing itself.

## Why not ``CompositeAuthenticator``

``CompositeAuthenticator`` (Slice 1) routes ``elg_``-prefixed credentials to
``AuthenticateApiKey`` and everything else to the token verifier. It is the right shape, and it is
deliberately **not** wired yet: ``AuthenticateApiKey`` needs an ``ApiKeyRepository``, which is
request-scoped storage. Wiring durable credential storage is Slice 18's subject, and inventing a
process-lifetime repository here to avoid saying so would be the speculative infrastructure GP-1
forbids.

The consequence is stated rather than hidden: **this deployment accepts JWT bearer credentials
only.** An API key presented today fails closed with the same 401 as any other unverifiable
credential - which is the correct behaviour for a credential type the deployment cannot check,
not a silent gap. Substituting ``CompositeAuthenticator`` later changes one line in the
composition root and nothing else, because both satisfy the same port.
"""

from __future__ import annotations

from gateway.application.ports.auth import AccessTokenVerifier
from gateway.domain.auth.models import Principal


class BearerTokenAuthenticator:
    """Resolves a bearer credential by delegating to an ``AccessTokenVerifier``."""

    def __init__(self, verifier: AccessTokenVerifier) -> None:
        self._verifier = verifier

    async def authenticate(self, credential: str) -> Principal:
        """Verify the credential. Raises ``AuthError`` on any failure - the middleware turns that
        into a 401, so failing closed is preserved by not catching anything here."""
        return self._verifier.verify(credential)
