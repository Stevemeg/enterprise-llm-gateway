# Cryptographic Architecture

**Phase:** 5 — Backend (Milestone 3) · Design for approval
**Scope:** Formalizes the cryptography behind [Authentication_Architecture.md](Authentication_Architecture.md).
Introduces **no new behavior**. Realizes ADR-0008 (auth), ADR-0011 (secret references). This document
plus [Security_Traceability.md](Security_Traceability.md) is the reference for security review /
penetration testing.

> **Single crypto boundary.** Every low-level cryptographic operation goes through the audited boundary:
> primitives (CSPRNG, hashing, timing-safe compare, zeroization) in **`shared/secrets.py`**; asymmetric
> signing/verification (JWT/JWKS) in **`adapters/security/`**. No other module may import `secrets`,
> `hmac`, `hashlib`, `jwt`, or `cryptography` directly (enforced by import-linter). This gives one place
> to audit, test, and rotate cryptography.

## 1. Keys
### 1.1 JWT signing keys
- **Algorithm:** RS256 (RSA-2048+). Asymmetric so public keys can be published (JWKS) and services verify
  without the signing secret.
- **Storage:** private keys via `SecretsPort` (KMS/Vault) — **never** in DB/plaintext (ADR-0011). Public
  keys are non-secret (served via JWKS).
- **Structure:** each key has a `kid` (key id). The active key signs; recent public keys remain published
  for verification during rotation.

### 1.2 JWKS keys
- Public keys exposed as a JWKS set at `/.well-known/jwks.json`, each entry `{kty:RSA, use:sig, alg:RS256,
  kid, n, e}`. Inbound OIDC id_tokens are verified against the **IdP's** JWKS (fetched, cached, refreshed
  on unknown `kid`).

### 1.3 Key identifiers (kid)
- Every signing/verification key carries a stable `kid`; JWT headers include `kid` so verifiers select the
  correct key deterministically. Unknown `kid` → fail closed.

### 1.4 Rotation policy
- Scheduled rotation (e.g., every 30–90 days). New keypair → new `kid` → becomes the signing key. The
  previous **public** key stays in JWKS for a grace window ≥ the max access-token TTL, then is retired.

### 1.5 Expiration policy
- Keys have a logical lifetime (active → grace → retired). Tokens are short-lived (default 10 min access),
  so a retired key can be dropped shortly after its grace window.

### 1.6 Emergency rotation
- On suspected compromise: immediately generate a new signing key, **remove the compromised `kid` from
  JWKS** (all its tokens fail closed), force re-authentication, and rotate any related secrets. Audited.

### 1.7 Algorithm agility
- An explicit **allow-list** (`{RS256}` today; `ES256`/EdDSA addable) governs both signing and
  verification. `alg:none` and symmetric algorithms are **rejected** (defeats alg-confusion). Adding an
  algorithm is a reviewed change; the verifier never trusts the token's self-declared `alg` beyond the
  allow-list.

## 2. Randomness
- **CSPRNG source:** Python `secrets` (OS CSPRNG) — the **only** randomness source for security material,
  wrapped by `shared/secrets.py`. `random`/`os.urandom` are not used for secrets.
- **Token generation:** `secrets.token_urlsafe` with ≥ 32 bytes entropy (floor enforced; < 16 bytes
  rejected).
- **API key generation:** `elg_<env>_<url-safe CSPRNG>`; ≥ 256 bits of entropy in the random part.
- **Session / refresh / jti generation:** CSPRNG tokens (`jti` unique per JWT; refresh tokens opaque
  high-entropy).

## 3. Hashing
- **API key hashing:** SHA-256 of the full key (keys are high-entropy random → a fast hash is appropriate;
  password-style KDFs are unnecessary and would only add latency to the hot auth path).
- **Refresh token hashing:** SHA-256 of the opaque token; only the hash is stored.
- **Service-account secret hashing:** SHA-256, verified in constant time.
- **Future password hashing:** **Argon2id** (memory-hard, per-user salt) — used **only if** a local
  password path is ever added (not in v1; auth is via OIDC). Documented for agility.
- **Hash migration strategy:** stored hashes are tagged with an algorithm identifier (e.g., a prefix)
  so the verifier can support multiple schemes and migrate on next successful use (verify-then-rehash).
  This lets us move SHA-256 → a stronger scheme, or introduce Argon2id for passwords, without a flag day.

## 4. Signatures
- **JWT:** RS256 over header+payload (§1). The integrity/authenticity anchor for access tokens.
- **Webhooks:** HMAC-SHA256 signature (`X-ELG-Signature: t=..., v1=...`) using a per-subscription signing
  secret resolved from `secret_reference` (see [API_Webhooks.md](API_Webhooks.md)); replay-guarded by the
  timestamp. HMAC computed inside the crypto boundary.
- **Audit chain:** append-only audit records are **hash-chained** (`entry_hash = SHA-256(prev_hash ||
  canonical(row))`) for tamper-evidence (ADR-0009, FR-113/114). Chain hashing goes through the crypto
  boundary.
- **Request signing (future):** sender-constrained tokens / signed requests (DPoP or mTLS-bound, RFC
  8705/9449) are a documented future hardening; not in v1.

## 5. Secret management
- **Secret references:** the DB stores only **pointers** (`secret_reference`: provider + path + version),
  never values (ADR-0011, NFR-SEC03).
- **KMS integration (SaaS):** cloud KMS / Secrets Manager backs the `SecretsPort`; signing keys and IdP
  client secrets live there.
- **Vault integration (self-host):** HashiCorp Vault / sealed-secrets back the same port.
- **Air-gapped deployment:** secrets sourced from the in-cluster secret store; no external calls; signing
  keys generated and stored locally (ADR-0011).
- **Self-host deployment:** identical code path; the `SecretsProvider` is selected by profile in the
  composition root (NFR-D01).

## 6. Cryptographic lifecycle
| Stage | Practice |
|-------|----------|
| **Generation** | CSPRNG / RSA keygen inside the crypto boundary; entropy floors enforced. |
| **Storage** | Private keys + client secrets in the secrets manager; API keys/refresh/SA secrets as SHA-256 hashes; no recoverable secret in DB/logs. |
| **Rotation** | Keys rotate on schedule (new `kid`, grace window); secrets rotate via new `secret_reference` version. |
| **Revocation** | Remove `kid` from JWKS (keys); mark records revoked (keys/sessions); optional `jti` denylist (break-glass). |
| **Destruction** | Retired private-key material **zeroized** (bytearray wipe) where the runtime permits; references deleted; hashes purged per retention. |

## 7. Future post-quantum considerations
Cryptographic agility is maintained (algorithm allow-lists for signatures and hashes, `kid`-based key
selection, hash-scheme tagging). This positions the system to adopt **post-quantum signature schemes**
(e.g., ML-DSA / SLH-DSA once standardized and library-supported) by adding them to the allow-list and
rotating keys — without redesign. No PQC is implemented in v1; this section is a forward-looking
placeholder to record the intent and the agility mechanisms that make it feasible.

## 8. Traceability
ADR-0008 (auth/keys/rotation), ADR-0009 (audit chain), ADR-0011 (secret references); FR-022, FR-090..097,
FR-113/114; NFR-SEC01/03/04/09. Control-level mapping: [Security_Traceability.md](Security_Traceability.md).
