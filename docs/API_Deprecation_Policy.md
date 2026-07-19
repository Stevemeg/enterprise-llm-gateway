# API Deprecation & Sunset Policy

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Predictable, enterprise-friendly lifecycle for retiring API surface. Pairs with
[`API_Versioning_Strategy.md`](API_Versioning_Strategy.md) and
[`API_Changelog_Policy.md`](API_Changelog_Policy.md).

## 1. Lifecycle stages
`Active → Deprecated → Sunset (removed)`

| Stage | Meaning | Consumer impact |
|-------|---------|-----------------|
| **Active** | Fully supported | none |
| **Deprecated** | Still works; scheduled for removal | migrate before sunset |
| **Sunset** | Removed / returns `410 Gone` (or major-version drop) | must have migrated |

## 2. Minimum timelines (guarantees)
| Scope | Minimum deprecation window before sunset |
|-------|------------------------------------------|
| **Major version** (e.g., `/v1`) | **12 months** after `/v2` GA |
| **Endpoint or field** | **6 months** |
| **Error code / enum value (output)** | **6 months** |
| **Security-driven removal** | Expedited, with direct customer notice (case-by-case, minimized) |

Enterprise contracts may specify longer windows; the policy is a floor, not a ceiling.

## 3. Signaling (how consumers find out)
1. **Changelog** entry (Deprecated) with the sunset date and migration guidance.
2. **OpenAPI**: the element marked `deprecated: true`.
3. **Runtime headers** on affected responses:
   - `Deprecation: true` (or a date),
   - `Sunset: <RFC 1123 date>` (RFC 8594),
   - `Link: <migration-doc>; rel="deprecation"`.
4. **Proactive notice**: email/console banner + optional `api.deprecation` webhook to subscribed tenants,
   with usage-based targeting (tenants actually calling the deprecated surface are notified directly).
5. **Dashboards**: deprecated-usage metric so customers (and we) can track migration progress.

## 4. Sunset behavior
- After the sunset date, a removed **endpoint** returns `410 Gone` with an `Error` (`type:not_found_error`,
  `code:endpoint_sunset`, `doc_url` to migration) — never a silent 404.
- A removed **field** simply stops being sent (additive-safe for clients that ignore unknowns); removed
  **required** inputs are only possible across a major version.
- A sunset **major version** stops serving; requests get a clear error pointing to the new version.

## 5. Process
1. Propose deprecation (rationale, replacement, impact, ADR if architectural).
2. Announce (all channels §3), set `deprecated:true`, start the clock (§2).
3. Track deprecated-usage; reach out to lagging tenants.
4. At sunset: remove, update spec/changelog, return `410`/version-drop.
- Deprecations are **never** accelerated below the guaranteed window except for security, which follows a
  documented expedited path with direct notice.

## 6. Self-hosted
Self-hosted customers control upgrade timing; deprecations are announced in release notes, and a version
stays functional until the customer upgrades. Sunset applies when they move to a release that removes it —
release notes state the minimum client/SDK version (NFR-D01).

## 7. Traceability
NFR-M06, enterprise stability expectations (P-01/P-04); complements versioning/changelog policies and the
Phase-1 GitHub Release Checklist.
