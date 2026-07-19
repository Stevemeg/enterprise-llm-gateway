# Deployment Architectures

Both modes run the **same container images from one codebase**, differing only by configuration/profile
([ADR-0011](../../adr/0011-self-hosted-deployment-architecture.md)). Back to
[Architecture](../../Architecture.md).

| Mode | File |
|------|------|
| SaaS (cell-per-region, multi-AZ) | [01-saas.md](01-saas.md) |
| Self-hosted (single cell, air-gap-ready) | [02-self-hosted.md](02-self-hosted.md) |

Cloud-neutral by design (NFR-D04); AWS shown illustratively — GCP/Azure equivalents map directly.
