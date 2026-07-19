"""Adapters: implement application ports (DB, providers, cache, bus, secrets, identity).

The only layer permitted to import external drivers/frameworks. Must not import
``delivery`` or ``config`` (enforced by import-linter).
"""
