"""The full served path with a durable catalog and durable pricing (Slice 19).

Slice 18's end-to-end test asserted that a fully authorized request got a **503
no_eligible_provider**, because the container's provider catalog was empty - admission passed, but
there was nothing to route to. Slice 19 fills the catalog and the price list, so the same request
now routes, executes, is priced against the effective-dated ``price_table``, settles against the
budget, and returns **200**. The change in that one status code is the slice's headline, proven end
to end through the real ``Container`` against real PostgreSQL.

The provider client here is still ``InMemoryProviderClient``: the container selects the real HTTP
adapter only when connections are configured, and wiring a live provider into an automated test
would spend real credits. The real adapter's own behaviour is covered exhaustively by
``tests/unit/test_openai_compatible_client.py`` against a scripted ``httpx`` transport. What this
test proves is the *composition* - durable catalog + durable pricing + the existing execute/settle
path - not the SDK.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from gateway.adapters.security.api_keys import generate_api_key
from gateway.config.container import Container
from gateway.config.settings import AuthSettings, DatabaseSettings, Settings
from gateway.delivery.http.app import build_http_app
from tests.support.catalog import seed_model, seed_price, seed_provider
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_api_key, seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]

_PATH = "/v1/inference"
_BODY = {"prompt": "hello"}
_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    assert PG_URL is not None  # guarded by requires_postgres
    settings = Settings(
        database=DatabaseSettings(url=PG_URL),
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


async def _seed_routable_tenant(container: Container, org: UUID, *, priced: bool = True) -> str:
    """A tenant with an inference-scoped key, one enabled provider/model, and (optionally) a
    price. Returns the key secret."""
    await seed_organization(container.uow_factory, org)
    minted = generate_api_key()
    await seed_api_key(
        container.uow_factory,
        org,
        prefix=minted.prefix,
        key_hash=minted.key_hash,
        scopes=("inference:invoke",),
    )
    provider_id = await seed_provider(container.uow_factory, org, name="inhouse")
    model_id = await seed_model(container.uow_factory, org, provider_id, name="echo-1")
    if priced:
        await seed_price(
            container.uow_factory,
            org,
            model_id,
            input_per_1k="1.00",
            output_per_1k="1.00",
            effective_from=_LONG_AGO,
        )
    return minted.secret


async def _budget(container: Container, org: UUID, limit: str) -> None:
    async with container.uow_factory(tenant_id=org) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO org_budget (organization_id, amount_limit, currency) "
                "VALUES (:org, :limit, 'USD')"
            ),
            {"org": str(org), "limit": Decimal(limit)},
        )
        await uow.commit()


async def _cost_rows(container: Container, org: UUID) -> int:
    async with container.uow_factory(tenant_id=org) as uow:
        count = (
            await uow.session.execute(
                text("SELECT count(*) FROM cost_ledger WHERE organization_id = :org"),
                {"org": str(org)},
            )
        ).scalar_one()
    return int(count)


# ------------------------------------------------------------------ the headline


async def test_a_seeded_catalog_turns_the_slice_18_503_into_a_200(
    client: AsyncClient, container: Container
) -> None:
    """The exact request that returned 503 in Slice 18 now succeeds, because routing has a
    provider to choose and pricing can cost the call."""
    org = uuid4()
    secret = await _seed_routable_tenant(container, org)

    response = await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "inhouse"
    assert body["cached"] is False


async def test_a_successful_call_books_spend_exactly_once_against_the_durable_price(
    client: AsyncClient, container: Container
) -> None:
    """The durable price list feeds the existing settle path: a 200 leaves exactly one cost_ledger
    row, priced against price_table, not a routing estimate."""
    org = uuid4()
    secret = await _seed_routable_tenant(container, org)
    await _budget(container, org, "1000.00")

    assert await _cost_rows(container, org) == 0
    response = await client.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 200, response.text
    assert await _cost_rows(container, org) == 1, "spend must be booked exactly once"


async def test_an_unpriced_model_fails_closed_rather_than_serving_free(
    container: Container,
) -> None:
    """A routable provider with no price is a configuration defect. ReservationService raises
    UnknownPriceError (Slice 8's invariant: a config defect is never a budget outcome), so the
    request fails closed - it is not served, and no spend is booked.

    The safety counterpart to the headline: adding a provider without a price cannot open a hole
    through which calls are served at zero cost. The request currently surfaces as a generic 500
    (no provider detail reaches the client - the message is server-side only); mapping that
    configuration defect to a tailored fail-closed 5xx is recorded as known debt, because doing it
    without either importing accounting into delivery (contract-forbidden) or reversing Slice 8's
    invariant would be out of this slice's scope.
    """
    org = uuid4()
    secret = await _seed_routable_tenant(container, org, priced=False)
    # raise_app_exceptions=False so we observe the fail-closed *response* rather than the exception
    # propagating into the test - the client sees a 5xx, never the provider name.
    app = build_http_app(
        service_name="test",
        service_version="0.0.0",
        health_registry=container.health,
        authenticator=container.authenticator,
        audit_sink=container.audit_sink,
        inference_service=container.inference_service,
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(_PATH, json=_BODY, headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code != 200
    assert response.status_code >= 500  # fail closed, not served
    assert "inhouse" not in response.text, "the provider name must not reach the client"
    assert await _cost_rows(container, org) == 0
