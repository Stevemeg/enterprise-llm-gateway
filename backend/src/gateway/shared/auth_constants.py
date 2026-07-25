"""Auth-related constants shared across layers (no logic, no crypto)."""

from __future__ import annotations

API_KEY_PREFIX_LENGTH = 16
"""Non-secret prefix length used to look up an API key before hash verification."""

API_KEY_PREFIX = "elg_"
"""Credential-shape marker for a gateway-issued virtual API key.

Shared because three layers branch on it and they must agree: ``adapters/security/api_keys.py``
mints it, ``application/auth/authenticate_request.py`` routes on it, and the authentication
middleware labels its metrics by it. Slice 18 found the middleware still testing for an older
``gw_`` marker, so an API-key rejection was being reported as a JWT rejection - harmless until
API keys became verifiable, and invisible for as long as the constant was written out three times.
"""
