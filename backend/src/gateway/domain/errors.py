"""Base exception hierarchy (Backend_Implementation_Guide.md §11).

Domain and application layers raise typed exceptions; the HTTP edge maps them to the
API error model. Nothing here builds transport responses.
"""

from __future__ import annotations


class GatewayError(Exception):
    """Root of all gateway-defined exceptions."""


class DomainError(GatewayError):
    """A domain invariant was violated (framework-free)."""
