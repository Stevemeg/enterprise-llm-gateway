# Sequence Diagrams

Key runtime flows. Mermaid `sequenceDiagram`, rendering on GitHub. Back to
[Architecture](../../Architecture.md).

| # | Flow | File | ADR |
|---|------|------|-----|
| 1 | Inference — cache miss (happy path) | [01-inference-cache-miss.md](01-inference-cache-miss.md) | 0001/0004/0006/0012 |
| 2 | Provider failover + circuit breaking | [02-failover.md](02-failover.md) | 0012/0003 |
| 3 | Budget reserve → commit/release | [03-budget-reserve-commit.md](03-budget-reserve-commit.md) | 0004 |
| 4 | Semantic cache lookup & population | [04-semantic-cache.md](04-semantic-cache.md) | 0006/0007 |
| 5 | Admin auth (OIDC) + RBAC decision | [05-auth-oidc-rbac.md](05-auth-oidc-rbac.md) | 0008 |
| 6 | Async metering & audit pipeline | [06-async-metering-audit.md](06-async-metering-audit.md) | 0005/0004 |
