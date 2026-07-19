# ADR-0005: Eventing backbone

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, SRE, Database Architect
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Eventing backbone

## Context & problem
Several flows must run **off the hot path**: durable metering/ledger writes ([ADR-0004](0004-reserve-commit-cost-accounting.md)),
audit events (FR-113), usage aggregation/analytics (FR-086), budget-threshold alerts (FR-066), cache
warming, and semantic-cache embedding computation ([ADR-0006](0006-semantic-cache-architecture.md)).
The backbone must sustain **≥10k events/s** (NFR-S05), never block the request (NFR-P06), guarantee
**at-least-once** delivery with ordering where needed, and — critically — run in **air-gapped
self-hosted** deployments with minimal operational surface (NFR-D05, RISK-O03) while also scaling for
large SaaS.

## Decision drivers
- NFR-S05 (≥10k records/s), NFR-P06 (non-blocking), NFR-A05 (RPO ≤5 min → durable events),
  NFR-D01/D05 (one codebase; air-gapped self-host), NFR-M02 (pluggable).
- FR-070..077 (metering/analytics), FR-066 (alerts), FR-113 (audit), RISK-T08 (metering write path),
  RISK-O03 (self-host operational burden).

## Options considered
### Option A — Apache Kafka (or Redpanda)
- **Pros:** Best-in-class throughput/durability; partitioned ordering; huge ecosystem.
- **Cons:** Heavy to operate (brokers, ZooKeeper/KRaft, schema registry); disproportionate for a
  single-tenant self-hosted install; raises the floor cost and RISK-O03 significantly. Overkill for
  self-host; attractive only at the largest SaaS scale.

### Option B — Cloud-managed queue (SQS/SNS, PubSub, Kafka-as-a-service)
- **Pros:** No ops in SaaS; scalable.
- **Cons:** Cloud lock-in (violates NFR-D04 spirit); unavailable air-gapped (violates NFR-D05);
  breaks "one codebase, both modes" cleanly. Rejected as the default.

### Option C — **Redis Streams** as the default backbone behind an `EventBus` port, with a pluggable Kafka/Redpanda adapter for high-scale SaaS
Redis is already a required dependency (cache, reservations). Redis **Streams** provide durable,
ordered, consumer-group-based at-least-once delivery with acknowledgements and replay.
- **Pros:** Zero *new* dependency for self-host → minimal surface, air-gap-friendly (NFR-D05, RISK-O03);
  ordered consumer groups; durable enough for RPO with AOF/replication; the `EventBus` **port** lets
  large SaaS swap in Kafka/Redpanda without touching producers/consumers (NFR-M02). One codebase,
  config-selected backend (NFR-D01).
- **Cons:** Redis Streams' throughput ceiling and retention are lower than Kafka's; very large SaaS
  will need the Kafka adapter; Redis memory pressure must be managed (trim/retention).

## Decision
Adopt **Option C**: an **`EventBus` port** with **Redis Streams as the default adapter** (both
deployment modes) and a **Kafka/Redpanda adapter** available for high-scale SaaS via configuration.
Events are published fire-and-forget from the request path (non-blocking, NFR-P06) to durable streams;
**worker processes** ([Background Worker Architecture](../architecture/../Architecture.md)) consume via
consumer groups with acknowledgement, retries, and a **dead-letter stream**. Event families:
`usage.recorded`, `budget.threshold`, `audit.event`, `cache.embed_requested`, `analytics.rollup`.
Producers/consumers depend only on the port; the backend is chosen in the composition root
([ADR-0001](0001-clean-architecture-and-runtime.md)). Delivery is **at-least-once**; consumers are
**idempotent** (dedupe on event id) so replays are safe (supports FR-036 idempotency and exactly-once
*effects*).

## Consequences
- **Positive:** No extra moving parts for self-host (air-gapped works); scales to Kafka for the biggest
  SaaS without code change; durable → protects RPO; clean separation of hot path from accounting/audit.
- **Negative:** Idempotent consumers are mandatory (design discipline); Redis retention/memory must be
  monitored; a second backend (Kafka) means two adapters to test at the largest tier.
- **Follow-ups:** Phase 5/7 implement the `EventBus` port + Redis Streams adapter and workers; Phase 13
  load-tests to NFR-S05 and validates DLQ handling; Kafka adapter added when a SaaS tenant base
  demands it (future ADR to flip the default at a given scale).

## Requirements satisfied
- Functional: FR-066, FR-070, FR-072, FR-073, FR-076, FR-077, FR-086, FR-087, FR-088, FR-113.
- Non-functional: NFR-S05, NFR-P06, NFR-A05, NFR-D01, NFR-D05, NFR-M02.

## Review notes
Define a concrete RPS/retention threshold at which SaaS flips to the Kafka adapter; revisit after
Phase 13 baselines.
