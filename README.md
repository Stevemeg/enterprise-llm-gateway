# Enterprise LLM Gateway & Cost Router

A production-grade, provider-agnostic gateway that sits between enterprise applications and
large language model (LLM) providers. It delivers a single OpenAI-compatible API, intelligent
cost- and latency-aware routing, semantic caching, hard budget/quota enforcement, deep
observability, and enterprise-grade security and governance.

The platform is designed for **two deployment modes from one codebase**:

- **Multi-tenant SaaS** — many organizations on shared infrastructure with strong logical isolation.
- **Single-tenant self-hosted** — deployed inside a customer's own VPC/Kubernetes cluster for data
  residency, air-gap, and compliance requirements.

> **Status:** Phase 1 — Discovery & Requirements. This repository currently contains
> **documentation only**. No application code exists yet, by design. See
> [`docs/README.md`](docs/README.md) for the requirements set and
> [Development Phases](#development-phases) below.

## Why this exists

Enterprise LLM API spend exceeded **$8.4B in 2025** and the LLM middleware/gateway layer is
growing at a **~49.6% CAGR**, with ~42% of enterprises already inserting a gateway between their
apps and model providers. Direct provider integrations no longer scale: teams need centralized
cost control, failover, governance, and observability. This project builds that layer to a
production standard.

## Tech stack (target)

| Layer            | Technology                                                        |
|------------------|-------------------------------------------------------------------|
| API / Backend    | Python 3.12, FastAPI, Pydantic v2, asyncio                        |
| Frontend         | Next.js (App Router), TypeScript, React                           |
| Data             | PostgreSQL 16 + `pgvector`, Redis                                 |
| Messaging/Async  | Redis Streams / queue (TBD Phase 7)                               |
| Infra            | Docker, Kubernetes, Helm, Terraform                               |
| CI/CD            | GitHub Actions                                                    |
| Observability    | OpenTelemetry, Prometheus, Grafana, structured logging            |
| Security         | OAuth2 / OIDC, JWT, RBAC, secrets manager, OWASP ASVS             |

## Development phases

The project is built strictly one phase at a time, each gated by explicit approval.

| #  | Phase                         | Status         |
|----|-------------------------------|----------------|
| 1  | Discovery & Requirements      | Approved       |
| 2  | Architecture                  | **In review**  |
| 3  | Database                      | Not started    |
| 4  | API Contracts                 | Not started    |
| 5  | Backend                       | Not started    |
| 6  | Frontend                      | Not started    |
| 7  | Routing Engine                | Not started    |
| 8  | Semantic Cache                | Not started    |
| 9  | Security                      | Not started    |
| 10 | Observability                 | Not started    |
| 11 | CI/CD                         | Not started    |
| 12 | Kubernetes & Terraform        | Not started    |
| 13 | Testing                       | Not started    |
| 14 | Documentation                 | Not started    |
| 15 | Production Hardening          | Not started    |

## Repository layout

```
.
├── docs/                     # All documentation (single source of truth)
│   ├── architecture/         # C4, sequence, deployment diagrams (Phase 2)
│   ├── adr/                  # Architecture Decision Records (Phase 2+)
│   └── api/                  # OpenAPI specs (Phase 4)
├── README.md
└── .gitignore
```

Application code (`backend/`, `frontend/`, `infrastructure/`, `docker/`, `tests/`, `.github/`)
is intentionally **not present yet** and will be introduced in later phases.

## License

Proprietary — All Rights Reserved (commercial product). Final license terms TBD.
