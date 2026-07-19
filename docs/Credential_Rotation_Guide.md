# Credential Rotation Guide

**Phase:** 5 — Backend · Operations runbook
**Last updated:** 2026-07-15

Operational counterpart to [Cryptographic_Architecture.md](Cryptographic_Architecture.md) (design) and
[Authentication_Architecture.md](Authentication_Architecture.md) (flows). Covers **how to rotate**
credentials safely — schedules, grace periods, rollback, failure handling, and step-by-step runbooks —
for API keys, service-account credentials, and JWT signing keys / JWKS. Realizes FR-093/096/097,
ADR-0008/0011/0013.

## 0. Principles
- **Rotate without downtime:** issue-new → both valid (grace) → retire-old. Never break live clients.
- **Only hashes/references move:** secrets are shown once (FR-097) and stored hashed / by reference
  (ADR-0011); rotation never exposes a stored secret.
- **Everything audited:** each rotation writes an audit event (actor, reason, timestamps) — the
  credential tables carry `last_rotated_at`, `rotation_reason`, `created_by`, `revoked_by`.
- **Fail closed on ambiguity:** if a rotation's new credential can't be confirmed, keep the old one
  active and alert — never end up with zero valid credentials.

## 1. API key rotation (`api_key`)
**When:** on schedule (policy), on suspected exposure, or on personnel/offboarding changes.
**Steps**
1. `POST /api-keys/{id}/rotate` → issues a **new** key (new `key_prefix` + hash); the old key stays
   `active` during a **grace window** (config, e.g., 24–72h) so callers can migrate.
2. Update the consuming application(s) with the new secret (shown once).
3. After the grace window (or once traffic on the old prefix is zero), the old key is `revoked`.
**Grace:** overlap window bounded by config; monitor `last_used_at` on the old key to confirm cut-over.
**Rollback:** if the new key is misconfigured, keep the old key active (do not revoke) and re-issue.
**Failure handling:** rotation is idempotent via `Idempotency-Key`; a failed issue leaves the old key
untouched (fail-safe).

## 2. Service-account credential rotation (`service_account_credential`)
**When:** schedule, compromise, or automation re-key.
**Steps**
1. `POST /service-accounts/{id}/credentials` → issues a **new** `client_id` + secret (shown once);
   `rotation_reason` recorded (`scheduled|compromise|manual`), `created_by` set.
2. Reconfigure the automation to use the new credential.
3. `DELETE /service-accounts/{id}/credentials/{old}` after cut-over (sets `status=revoked`,
   `revoked_at`, `revoked_by`).
**Grace:** multiple credentials may be `active` simultaneously (dedicated table supports overlap —
ADR-0013), so there is **no outage** during rotation.
**Rollback:** keep the previous credential active until the new one is verified in production.
**Failure handling:** if issuing fails, the account keeps its existing credential(s); alert on the
failed job.

## 3. JWT signing-key rotation (`KeyProvider`)
**When:** scheduled (e.g., every 30–90 days) or emergency (compromise).
**Steps**
1. Generate a new RSA keypair with a **new `kid`** (`KeyProvider.rotate(new_kid)`); it becomes the
   **signing** key. The previous **public** key is retained in `verification_keys()` / JWKS.
2. New access tokens are signed with the new `kid`; tokens signed by the old key **still validate**
   during the grace window (≥ max access-token TTL, default 10 min → short window).
3. After the grace window, drop the retired public key from JWKS; **zeroize** the retired private key
   material where the runtime permits (Cryptographic_Architecture §6).
**Grace:** ≥ max access-token TTL so no valid token is orphaned.
**Rollback:** if the new key is bad, revert `current` to the previous signing key (still retained) and
re-issue; because both public keys are published, verification continues either way.

## 4. JWKS rotation
JWKS is a **projection** of the signing keys — it updates automatically when keys rotate (§3). The
document always contains **current + previous** public keys during the grace window. Consumers
(and the gateway's own verifier for OIDC id_tokens) **refresh JWKS on an unknown `kid`**, so a new key
is picked up without a restart. Cache TTL is short; a forced refresh endpoint/flush is available for
emergencies.

## 5. Emergency rotation (compromise)
1. **Immediately** generate a new signing key and **remove the compromised `kid` from JWKS** → every
   token signed with it fails closed at once (no grace).
2. Revoke affected API keys / service-account credentials (`status=revoked`), and (break-glass) add
   affected access-token `jti`s to the Redis denylist until they expire.
3. Force re-authentication for impacted principals; rotate any related secret-manager entries.
4. Record `rotation_reason='compromise'`, notify security, and open an incident.
Emergency rotation **intentionally skips grace** — availability is sacrificed to contain the breach.

## 6. Grace-period summary
| Credential | Normal grace | Emergency |
|-----------|--------------|-----------|
| API key | config (e.g., 24–72h) | none (revoke now) |
| Service-account credential | overlap until cut-over confirmed | none (revoke now) |
| JWT signing key | ≥ max access-token TTL (~10 min) | none (drop kid now) |

## 7. Rollback strategy (general)
- Keep the **previous** credential/key **valid** until the new one is confirmed in production.
- Never revoke the old credential in the same step that issues the new one.
- Because verification accepts current **and** previous keys (JWT) and multiple active credentials
  (keys/service accounts), rollback is a **no-op on the data path** — just point clients back.

## 8. Failure handling
- Issuance failure → no change to existing credentials (fail-safe); alert + retry (idempotent).
- Secret-manager unreachable during signing-key load → **fail fast at startup** (FR-146); do not run
  with no keys.
- Reconciliation: a scheduled job flags credentials past `expires_at` still `active`, and
  never-rotated credentials older than policy (`last_rotated_at`), for hygiene.

## 9. Runbooks (operator quick reference)
- **Scheduled key rotation:** trigger rotate → verify JWKS shows both kids → monitor error rate →
  after grace, drop old kid → confirm JWKS shows one kid.
- **Compromised API key:** `DELETE /api-keys/{id}` → confirm 401 for old key → issue replacement →
  notify owner.
- **Compromised signing key:** emergency §5 → verify old-kid tokens now 401 → confirm new tokens OK →
  incident review.
- **Service-account re-key:** issue new credential → deploy to automation → confirm traffic on new
  `client_id` → revoke old.

## 10. Traceability
FR-093 (key rotation), FR-096 (revocation), FR-097 (hashed/show-once); ADR-0008/0011/0013; NFR-SEC03/05.
Design: [Cryptographic_Architecture.md](Cryptographic_Architecture.md); checklist:
[Authentication_Review_Checklist.md](Authentication_Review_Checklist.md).
