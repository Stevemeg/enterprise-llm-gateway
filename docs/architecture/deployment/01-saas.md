# Deployment — SaaS (cell-per-region, multi-AZ)

Multi-region **cells**, each self-contained; tenants pinned to a **home region** (residency); per-tenant
active-passive cross-region failover. Back to [index](README.md) ·
[ADR-0010](../../adr/0010-multi-region-strategy.md).

```mermaid
flowchart TB
    U[Clients / Admins] --> GR[Global router<br/>geo + health-based DNS/anycast]

    GR --> R1
    GR --> R2

    subgraph R1[Region cell: us-east - home for Tenant set A]
      direction TB
      LB1[Ingress + WAF + TLS]
      subgraph AZ1a[AZ a]
        API1a[API pods]; WRK1a[Worker pods]
      end
      subgraph AZ1b[AZ b]
        API1b[API pods]; WRK1b[Worker pods]
      end
      PG1[(PostgreSQL primary + replica<br/>multi-AZ, pgvector)]
      RD1[(Redis HA<br/>counters/cache/streams)]
      SEC1[[Secrets/KMS]]
      OTEL1[Telemetry stack]
      LB1 --> API1a & API1b
      API1a & API1b --> RD1 & PG1
      WRK1a & WRK1b --> PG1
      API1a --> SEC1
    end

    subgraph R2[Region cell: eu-west - home for Tenant set B]
      LB2[Ingress + WAF + TLS]
      API2[API pods]; WRK2[Worker pods]
      PG2[(PostgreSQL multi-AZ + pgvector)]
      RD2[(Redis HA)]
      LB2 --> API2 --> RD2 & PG2
      WRK2 --> PG2
    end

    PG1 -. async replication (RPO<=5m) .-> PGDR1[(Standby in partner region)]
    PG2 -. async replication .-> PGDR2[(Standby)]
    API1a --> PROV[(LLM Providers)]
    API2 --> PROV
```

## Characteristics
- **HA:** stateless API/worker pods across **≥2 AZs**; HA Postgres + HA Redis; **no SPOF** (NFR-A03);
  HPA scales pods on RPS/queue depth to ≥50 replicas (NFR-S02) for ≥5k RPS steady/10k burst (NFR-S01).
- **Residency:** tenant data pinned to home-region cell (FR-116/117, NFR-C02); global router sends the
  tenant to its cell.
- **DR:** async cross-region replication (RPO ≤5 min) + documented promotion (RTO ≤30 min); **single
  writer per tenant** preserves budget atomicity ([ADR-0004](../../adr/0004-reserve-commit-cost-accounting.md)).
- **Scaling unit** is the **cell**: add regions/cells for growth and blast-radius containment.
- **Secrets** via cloud KMS/secret manager; **telemetry** to the regional OTel/Prom/Grafana stack.

**Requirements:** NFR-A01/A03/A05/A06, NFR-S01/S02, NFR-C02; FR-116/117.
