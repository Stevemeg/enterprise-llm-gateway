# API Versioning Strategy

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

How the API evolves without breaking enterprise integrations or generated SDKs. Complements
[`API_Deprecation_Policy.md`](API_Deprecation_Policy.md) and [`API_Changelog_Policy.md`](API_Changelog_Policy.md).

## 1. Versioning scheme
- **URL major version:** `/v1`, `/v2`, … A major version is a stable contract; breaking changes require a
  **new major version**. The OpenAPI `info.version` uses SemVer (`1.0.0`) where **major** tracks the URL
  version and **minor/patch** track additive/editorial changes.
- **One live major at a time is the norm;** when `/v2` ships, `/v1` enters the deprecation lifecycle
  (below) with a guaranteed support window — never an abrupt removal.
- **No date-based or header-based version negotiation in v1** (kept simple/predictable). Should we later
  need finer granularity, a `Gateway-Version` date header may be introduced — recorded as an ADR then.

## 2. Backward-compatibility policy (within a major version)
**Non-breaking (allowed any time, minor bump):**
- Adding a new endpoint, resource, or optional request field.
- Adding a new response field (clients must ignore unknown fields — SDKs are generated to tolerate this).
- Adding a new optional query param, a new enum **value** to an *output* enum where clients are documented
  to handle unknowns, a new error `code`, or a new webhook event type.
- Adding a new `x_gateway`/`x-` extension.
- Loosening a validation constraint.

**Breaking (requires a new major version):**
- Removing/renaming an endpoint, field, or error `code`.
- Changing a field's type, format, or semantics.
- Adding a **required** request field or tightening validation on existing inputs.
- Removing an enum value that inputs accept, or adding a value to an **input** enum that older servers
  reject.
- Changing default behavior, auth requirements, pagination shape, or the error envelope.
- Changing the OpenAI-compatible request/response shape of inference endpoints.

Enum evolution rule: **output** enums are treated as open (clients handle unknown values); **input**
enums are closed (adding accepted values is safe, removing is breaking).

## 3. Compatibility guarantees to consumers
- Clients **must ignore unknown response fields** and unknown enum values on outputs — the generated SDKs
  do this by default ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).
- The gateway **never** repurposes an existing field or `code`.
- OpenAI-compatibility of `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings` is a **stability
  guarantee** within `/v1`.

## 4. Breaking-change process
1. Propose the change with rationale + migration impact (ADR if architectural).
2. If breaking, schedule it for the **next major** (`/vN+1`); do **not** slip it into the current major.
3. Ship `/vN+1` alongside `/vN`; publish a migration guide + changelog entry.
4. Begin the deprecation lifecycle for `/vN` ([`API_Deprecation_Policy.md`](API_Deprecation_Policy.md)).

## 5. Deprecation & sunset (summary)
- Deprecated elements are announced in the changelog, marked `deprecated: true` in OpenAPI, and emit a
  `Deprecation` + `Sunset` response header and a warning event.
- **Minimum support window** for a deprecated **major version**: **12 months** (enterprise-friendly);
  individual deprecated fields/endpoints: **≥6 months**. Full policy: [`API_Deprecation_Policy.md`](API_Deprecation_Policy.md).

## 6. Self-hosted considerations
Self-hosted customers pin an image version; the API major version is tied to the release. Upgrades follow
the same compatibility rules so a customer upgrading within a major sees no breaking change (NFR-D01).
Release notes call out the minimum client/SDK version.

## 7. Versioning of related artifacts
- **OpenAPI spec** is versioned in-repo with the code; each release tags the exact spec.
- **SDKs** are versioned independently but declare the API major they target.
- **Webhooks** carry an event `version` field so payload evolution follows the same additive rules
  ([`API_Webhooks.md`](API_Webhooks.md)).
- **Error codes** are append-only (see [`API_Error_Model.md`](API_Error_Model.md)).

## 8. Traceability
Supports NFR-M06 (documented interfaces), NFR-D01 (one contract both modes), and the enterprise
expectation of stable, long-lived integrations (Personas P-01/P-04).
