"""Alembic migration package.

Importable so migration scripts can share helpers (e.g. ``sql_script``). ``alembic.ini`` sets
``prepend_sys_path = src,.`` so both the application package and this one resolve.
"""
