"""SQLAlchemy repositories implementing the application persistence ports.

Each repository operates on the ``AsyncSession`` of the active Unit of Work (tenant/RLS bound).
Secret hashes are stored as ``bytea`` and exposed to the domain as hex strings.
"""
