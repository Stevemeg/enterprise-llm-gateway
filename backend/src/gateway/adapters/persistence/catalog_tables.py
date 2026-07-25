"""SQLAlchemy Core table definitions for the provider catalog and price list (ADR-0003/0016 S19).

Authoritative DDL is ``Schema.sql`` / the migrations; these describe the read shape
``SqlProviderCatalog`` and ``SqlPriceTable`` use. All three tables are tenant-scoped with RLS, so
every query runs inside a tenant-bound unit of work and the isolation is the database's, not a
WHERE clause's.

Only the columns actually read are declared - the same discipline as ``rbac_tables.py``. Two
absences are deliberate rather than accidental:

* ``provider.base_url`` / ``provider.credential_secret_ref`` / ``provider.config`` are **not**
  read. Connection details and credentials belong behind the ``ProviderClient`` adapter boundary
  (ADR-0003), not on the ``ProviderDescriptor`` that travels through routing. Per-tenant provider
  endpoints and BYO credentials are a real future capability with no consumer today and no
  per-tenant secret storage to resolve them against, so they are deferred, not modelled.
* ``model.alias`` / ``quality_tier`` / ``context_window`` are not read. Choosing among a provider's
  models by alias or tier is routing intelligence, and the routing runtime's candidate vocabulary
  is provider *names* (see ``sql_provider_catalog.py``). Reading them here would imply a selection
  nothing performs.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
)

catalog_metadata = MetaData()

provider = Table(
    "provider",
    catalog_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("name", Text, nullable=False),
    Column("region", Text),
    # FR-028: runtime enable/disable without redeploy. A live query honours it immediately; a
    # snapshot taken at startup would not, which is why the catalog reads through to the database.
    Column("is_enabled", Boolean, nullable=False),
)

model = Table(
    "model",
    catalog_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("provider_id", Uuid, nullable=False),
    Column("name", Text, nullable=False),
    Column("is_enabled", Boolean, nullable=False),
)

price_table = Table(
    "price_table",
    catalog_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("model_id", Uuid, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("input_price_per_1k", Numeric(18, 8), nullable=False),
    Column("output_price_per_1k", Numeric(18, 8), nullable=False),
    # Effective dating (FR-074/075): a settled cost must be reproducible against the price that
    # was in force when the call happened, so the row is selected by time, not by "the latest".
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("effective_to", DateTime(timezone=True)),
)
