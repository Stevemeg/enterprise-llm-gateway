"""Typed identifiers used across layers.

Using ``NewType`` keeps ids distinct at type-check time (a ``RequestId`` cannot be
passed where an ``OrganizationId`` is expected) with zero runtime cost.
"""

from __future__ import annotations

from typing import NewType

RequestId = NewType("RequestId", str)
"""Correlation id for a single request (echoed as the ``X-Request-Id`` header)."""
