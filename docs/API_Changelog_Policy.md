# API Changelog Policy

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

How API changes are recorded and communicated. Pairs with
[`API_Versioning_Strategy.md`](API_Versioning_Strategy.md) and
[`API_Deprecation_Policy.md`](API_Deprecation_Policy.md).

## 1. Principles
- **Every** externally-visible API change is recorded in a public changelog **before or at** release.
- Entries are **classified** so consumers can assess impact at a glance.
- The changelog is **generated/verified from the OpenAPI spec diff** in CI, then human-annotated — no
  silent contract drift.

## 2. Change classes
| Class | Examples | SemVer | Notice |
|-------|----------|--------|--------|
| **Added** | new endpoint/field/param/error code/event | minor | changelog |
| **Changed (non-breaking)** | loosened validation, new optional behavior, docs | minor/patch | changelog |
| **Deprecated** | endpoint/field/version marked for removal | minor | changelog + `Deprecation` header + notice |
| **Breaking** | removal/rename/type change/required field | **major (/v2)** | advance notice + migration guide |
| **Security** | auth/behavior fix with security impact | patch/minor | changelog + advisory |
| **Fixed** | bug fix not changing contract | patch | changelog |

## 3. Entry format
```
## [1.3.0] - 2026-09-01
### Added
- `GET /usage` now supports `group_by=provider`. (#123)
### Deprecated
- `X-Cache-Status` header → use `X-Cache`. Sunset: 2027-03-01. (#130)
### Fixed
- `budget_exceeded` now returns `retry_after_seconds: null` consistently. (#128)
```
Each entry links the PR/issue and, for deprecations, the sunset date and migration note.

## 4. Generation & enforcement (CI, Phase 11)
- CI computes the **spec diff** vs the last release; classifies changes; **fails the build** if a
  breaking change is detected without a major-version bump, or if a change lacks a changelog entry.
- The generated draft is reviewed and annotated by the owning team before publish.

## 5. Distribution
- Published at the docs site and in-repo (`CHANGELOG` for the API). Notable changes also emit the
  `api.changelog` internal event and may notify subscribed webhooks/dashboards.
- SDK changelogs are derived from the API changelog + generator diff
  ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).

## 6. Self-hosted
Release notes for each image version embed the applicable API changelog window so self-hosted operators
know exactly what changed on upgrade (NFR-D01).

## 7. Traceability
NFR-M06 (documented interfaces), supports enterprise change management (P-01/P-03). Ties to Phase-1
GitHub Release Checklist (spec §10) and Quality Gates (§12).
