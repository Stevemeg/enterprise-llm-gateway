"""Security adapters: JWT, JWKS, API keys, key generation (crypto boundary).

The only place ``jwt``/``cryptography`` are imported (enforced by import-linter).
Low-level primitives come from ``gateway.shared.secrets``.
"""
