"""Composition root: typed settings and the dependency-injection container.

This is the ONLY layer permitted to import outward and assemble concrete adapters
(ADR-0001). Nothing else imports ``gateway.config``.
"""
