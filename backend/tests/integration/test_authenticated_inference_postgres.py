"""The whole authenticated path, wired exactly as production wires it (Slice 18).

Every other test in this slice substitutes something. This one substitutes nothing: it builds the
real ``Container`` against real PostgreSQL, hands its real collaborators to ``build_http_app``, and
drives the real ``POST /v1/inference`` route over ASGI. That is the only way to show that the
durable resolver, the composite authenticator and the ADR-0019 bootstrap are actually *connected* -
the failure mode this project has hit at every layer is two halves that each pass their own tests
while nothing asserts they are joined.

Slices 5-17 left the endpoint unable to admit anyone: ``NullPermissionResolver`` granted nothing
and no credential type carrying an inference permission could be verified. Both ends are closed
here, and the proof is that the request now gets past 401 *and* 403.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from gateway.adapters.security.api_keys import generate_api_key
from gateway.config.container import Container
from gateway.config.settings import AuthSettings, DatabaseSettings, Settings
from gateway.delivery.http.app import build_http_app
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_api_key, seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]

_PATH = "/v1/inference"
_BODY = {"prompt": "hello"}


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    assert PG_URL is not None  # guarded by requires_postgres
    settings = Settings(
        database=DatabaseSettings(url=PG_URL),
        # No secrets manager in tests; the JWT key is generated (dev-only path, ADR-0011).
        auth=AuthSettings(allow_insecure_generated_keys=True),
    )
    built = Container.create(settings)
    try:
        yield built
    finally:
        await built.dispose()


@pytest.fixture
async def client(container: Container) -> AsyncIterator[AsyncClient]:
    app = build_http_app(
        service_name="test",
        service_version="0.0.0",
        health_registry=container.health,
        authenticator=container.authenticator,
        audit_sink=container.audit_sink,
        inference_service=container.inference_service,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _key_with(container: Container, *scopes: str) -> str:
    org = uuid4()
    await seed_organization(container.uow_factory, org)
    minted = generate_api_key()
    await seed_api_key(
        container.uow_factory,
        org,
        prefix=minted.prefix,
        key_hash=minted.key_hash,
        scopes=scopes,
    )
    return minted.secret


# ------------------------------------------------------------------ refused (first)


async def test_no_credential_is_refused(client: AsyncClient) -> None:
    assert (await client.post(_PATH, json=_BODY)).status_code == 401


async def test_an_unknown_api_key_is_refused(client: AsyncClient) -> None:
    """Fails at ADR-0019 phase 1: no active key owns that prefix, so no tenant is resolved."""
    response = await client.post(
        _PATH, json=_BODY, headers={"Authorization": "Bearer elg_live_notarealkey00000"}
    )
    assert response.status_code == 401


async def test_a_real_key_with_a_forged_secret_is_refused(
    client: AsyncClient, container: Container
) -> None:
    """Same prefix, wrong secret: the constant-time hash check refuses in phase 2."""
    secret = await _key_with(container, "inference:invoke")
    forged = secret[:16] + "0" * (len(secret) - 16)
    response = await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_a_verified_key_without_the_permission_is_denied(
    client: AsyncClient, container: Container
) -> None:
    """The first 403 in this project's history produced by durable RBAC rather than by a stub.

    403 rather than 401 is the whole point: the credential verified (so the composite authenticator
    and the bootstrap lookup both worked), and the *resolver* is what refused.
    """
    secret = await _key_with(container)  # no scopes at all
    response = await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["type"] == "permission_error"
    # A denial still names no permission, rule or threshold (Slice 17's property, kept).
    assert "inference:invoke" not in response.text


async def test_a_key_scoped_for_another_tenant_grants_nothing(
    client: AsyncClient, container: Container
) -> None:
    """Belt-and-braces on the isolation boundary: scopes are read inside the key's own tenant, so
    a scope row planted under a different organization must not be picked up."""
    org, other = uuid4(), uuid4()
    for each in (org, other):
        await seed_organization(container.uow_factory, each)
    minted = generate_api_key()
    key_id = await seed_api_key(
        container.uow_factory, org, prefix=minted.prefix, key_hash=minted.key_hash
    )
    async with container.uow_factory(tenant_id=other) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO api_key_scope (api_key_id, scope, organization_id) "
                "VALUES (:id, 'inference:invoke', :org)"
            ),
            {"id": str(key_id), "org": str(other)},
        )
        await uow.commit()

    response = await client.post(
        _PATH, json=_BODY, headers={"Authorization": f"Bearer {minted.secret}"}
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ admitted


async def test_a_scoped_key_passes_authentication_and_authorization(
    client: AsyncClient, container: Container
) -> None:
    """The slice's headline: the endpoint admits a caller for the first time.

    It still cannot be *served* - the container's provider catalog is empty, so routing yields
    NO_CANDIDATE and the route maps that to 503 ``no_eligible_provider``. That refusal is precisely
    the evidence: getting a 503 from the routing stage means admission already passed both
    authentication and authorization, which no credential could do before this slice. Populating
    the catalog is Slice 19's subject, and this assertion is what will change when it lands.
    """
    secret = await _key_with(container, "inference:invoke")
    response = await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code not in (401, 403), "admission refused a fully authorized caller"
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_eligible_provider"


async def test_the_authenticated_request_is_recorded_in_the_durable_audit_log(
    client: AsyncClient, container: Container
) -> None:
    """The composite fans out for real: the same event reaches the logging sink and the durable,
    hash-chained one, inside the tenant it belongs to."""
    org = uuid4()
    await seed_organization(container.uow_factory, org)
    minted = generate_api_key()
    await seed_api_key(
        container.uow_factory,
        org,
        prefix=minted.prefix,
        key_hash=minted.key_hash,
        scopes=("inference:invoke",),
    )

    await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {minted.secret}"})

    async with container.uow_factory(tenant_id=org) as uow:
        rows = (
            (
                await uow.session.execute(
                    text(
                        "SELECT action, result, actor_type, entry_hash FROM audit_event "
                        "WHERE organization_id = :org"
                    ),
                    {"org": str(org)},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["action"] == "request.authenticated"
    assert rows[0]["result"] == "success"
    assert rows[0]["actor_type"] == "api_key"
    assert len(bytes(rows[0]["entry_hash"])) == 32
