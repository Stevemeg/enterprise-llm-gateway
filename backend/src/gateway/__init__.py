"""Enterprise LLM Gateway & Cost Router — backend package.

Layered per Clean/Hexagonal architecture (ADR-0001):
``domain`` < ``application`` < ``adapters`` / ``delivery``, wired by ``config``.
See ``docs/Backend_Implementation_Guide.md``.
"""

__version__ = "0.1.0"
