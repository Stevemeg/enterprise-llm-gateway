"""Delivery layer: inbound entrypoints (HTTP, workers, ops).

Depends on ``application``/``domain`` via ports; never on ``config`` or concrete adapters.
"""
