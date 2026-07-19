"""Tests that the Alembic migration set is well-formed (single head, base revision)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script_directory() -> ScriptDirectory:
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    return ScriptDirectory.from_config(config)


def test_single_head() -> None:
    assert len(_script_directory().get_heads()) == 1


def test_initial_revision_is_base() -> None:
    script = _script_directory()
    initial = script.get_revision("0001_initial_schema")
    assert initial is not None
    assert initial.down_revision is None
