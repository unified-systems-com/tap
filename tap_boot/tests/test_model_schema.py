"""Schema from the models (req-boot-schema-from-models, tap#1258).

The routine's decisions are tested against stand-in migration graphs, so no test has to build a
second database: what each migration carries decides refuse / replay / record. The one DB-backed
check is the test database itself, which this suite built from the models (tap.test_settings) and
which must answer exactly like a migrated one.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.postgres.operations import TrigramExtension
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from tap_boot import model_schema


def _migration(app: str, name: str, operations: list[Any], replaces: list[tuple[str, str]] | None = None) -> Any:
    return SimpleNamespace(app_label=app, name=name, operations=operations, replaces=replaces or [])


def _loader(*migrations_: Any) -> Any:
    return SimpleNamespace(graph=SimpleNamespace(nodes={(m.app_label, m.name): m for m in migrations_}))


_ADD = migrations.RunPython(migrations.RunPython.noop)


@pytest.mark.spec("req-boot-schema-from-models-1")
def test_a_squash_records_what_it_replaces_and_itself() -> None:
    """The executor's rules: record_migration writes the parts, check_replacements the squash."""
    loader = _loader(
        _migration(
            "app_a", "0001_squashed_0003", [], replaces=[("app_a", "0001_x"), ("app_a", "0002_y"), ("app_a", "0003_z")]
        ),
        _migration("app_a", "0004_after", []),
        _migration("app_b", "0001_initial", []),
    )
    assert model_schema.migrations_to_record(loader) == [
        ("app_a", "0001_squashed_0003"),
        ("app_a", "0001_x"),
        ("app_a", "0002_y"),
        ("app_a", "0003_z"),
        ("app_a", "0004_after"),
        ("app_b", "0001_initial"),
    ]


@pytest.mark.spec("req-boot-schema-from-models-3")
def test_raw_sql_is_a_hazard_even_inside_separate_database_and_state() -> None:
    hidden = migrations.SeparateDatabaseAndState(database_operations=[migrations.RunSQL("CREATE VIEW v AS SELECT 1")])
    loader = _loader(
        _migration("app_a", "0001_initial", [_ADD]),
        _migration("app_b", "0002_view", [hidden]),
    )
    assert [op.where for op in model_schema.schema_hazards(loader)] == ["app_b.0002_view"]


@pytest.mark.spec("req-boot-schema-from-models-3")
def test_run_python_is_not_a_hazard() -> None:
    """Every RunPython audited (tap#1258) transforms existing rows: none on an empty database."""
    assert model_schema.schema_hazards(_loader(_migration("app_a", "0002_rows", [_ADD]))) == []


@pytest.mark.spec("req-boot-schema-from-models-3")
def test_an_extension_a_migration_creates_is_replayed_first() -> None:
    loader = _loader(_migration("app_a", "0001_trgm", [TrigramExtension(), _ADD]))
    found = model_schema.extension_operations(loader)
    assert [(op.where, type(op.operation).__name__) for op in found] == [("app_a.0001_trgm", "TrigramExtension")]


@pytest.mark.spec("req-boot-schema-from-models-3")
def test_the_build_refuses_raw_sql_before_touching_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = _loader(_migration("app_b", "0007_trigger", [migrations.RunSQL("CREATE TRIGGER t ...")]))
    monkeypatch.setattr(model_schema, "MigrationLoader", lambda *a, **k: loader)
    touched: list[Any] = []
    monkeypatch.setattr(model_schema, "call_command", lambda *a, **k: touched.append(a))
    with pytest.raises(model_schema.SchemaFromModelsRefused, match=r"app_b\.0007_trigger"):
        model_schema.build_schema_from_models()
    assert touched == []


@pytest.mark.django_db
@pytest.mark.spec("req-boot-schema-from-models-1")
def test_an_empty_database_is_one_holding_only_the_cache_table(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "tap_cache"}}
    monkeypatch.setattr(connection.introspection, "table_names", lambda *a, **k: ["tap_cache", "django_migrations"])
    monkeypatch.setattr(MigrationRecorder, "applied_migrations", lambda self: {})
    assert model_schema.database_is_empty()
    monkeypatch.setattr(connection.introspection, "table_names", lambda *a, **k: ["tap_cache", "tap_entity"])
    assert not model_schema.database_is_empty()


@pytest.mark.django_db
@pytest.mark.spec("req-boot-schema-from-models-2")
def test_a_database_that_holds_a_schema_is_migrated_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test database holds a schema, so the routine falls through to a plain migrate."""
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(model_schema, "call_command", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(model_schema, "build_schema_from_models", lambda *a, **k: pytest.fail("rebuilt a schema"))
    assert model_schema.migrate_from_models() == model_schema.MIGRATED
    assert [args for args, _ in calls] == [("migrate",)]
    assert not calls[0][1].get("fake") and not calls[0][1].get("run_syncdb")


@pytest.mark.django_db
@pytest.mark.spec("req-boot-schema-from-models-4")
def test_the_model_built_test_database_has_every_migration_applied() -> None:
    """What a later plain `migrate` would see: nothing to apply, across every app's graph."""
    executor = MigrationExecutor(connection)
    assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []
    # And a second recording pass is refused rather than stacked on top.
    assert model_schema.record_all_migrations() is False


@pytest.mark.spec("req-boot-schema-from-models-2")
def test_the_command_names_the_road_it_took(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_boot.management.commands import migrate_from_models as command

    monkeypatch.setattr(command, "migrate_from_models", lambda *a, **k: model_schema.BUILT)
    out = io.StringIO()
    call_command("migrate_from_models", "--noinput", "--skip-checks", stdout=out)
    assert "Built the schema from the models" in out.getvalue()

    def refuse(*_a: Any, **_k: Any) -> str:
        raise model_schema.SchemaFromModelsRefused("RunSQL in app_b.0007_trigger")

    monkeypatch.setattr(command, "migrate_from_models", refuse)
    with pytest.raises(CommandError, match="app_b.0007_trigger"):
        call_command("migrate_from_models", "--noinput", "--skip-checks", stdout=out)
