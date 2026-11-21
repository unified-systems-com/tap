"""Build a database schema from the models instead of replaying every migration (tap#1258).

TAP-IMPLEMENTS: req-boot-schema-from-models@2191f7a9019c/350ccb67d4ad (derivation) — the one
    build-from-models routine the boot entrypoint, the cold-boot gate, the test-DB template and
    the per-run test database all use.

Replaying TAP's migrations from zero costs about twenty minutes once ``aws_core`` is installed;
creating the same tables straight from the models costs seconds. Before 0.5 TAP supports no
upgrade path, so a NEW database never needs the history, only its end state. This module builds
that end state the way Django's own ``TEST.MIGRATE = False`` does — ``migrate --run-syncdb`` with
every app's migrations switched off — and then records every migration as applied
(``migrate --fake``), so the database is indistinguishable from a migrated one to everything that
asks: a later plain ``migrate`` applies only migrations that are genuinely new, and the health
probe's pending-migration check reads none pending.

Only on an EMPTY database. A database that already holds a schema is migrated normally, because
syncdb never alters an existing table and faking would then mark unapplied changes as done.

What the models cannot carry is not silently dropped (``req-boot-schema-from-models-3``):

* an extension a migration creates (``django.contrib.postgres.operations.CreateExtension`` and its
  subclasses) is created first, since a model's index or field may need it;
* raw SQL (``RunSQL``) is refused by name. It can create a trigger, a view or a seed row that no
  model describes, and replaying it out of order is not safe, so the build stops and says which
  migration to run for real.

``RunPython`` is allowed: an audit (tap#1258) found every one in core and the installed plugins,
and in Django, allauth and the other third-party apps, transforms rows that already exist, which
on an empty database is none. A future ``RunPython`` that SEEDS rows would be lost here, and that
is what the nightly parity job (``tap.schema_parity``) exists to catch, with the real migrations
from zero that nothing else runs any more.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import RunSQL, SeparateDatabaseAndState
from django.db.migrations.recorder import MigrationRecorder

logger = logging.getLogger(__name__)

BUILT = "built"
MIGRATED = "migrated"


class SchemaFromModelsRefused(RuntimeError):
    """A migration carries something a model cannot describe, so the build would lose it."""


@dataclass(frozen=True)
class MigrationOp:
    """One database operation, named by the migration that carries it."""

    app_label: str
    migration: str
    operation: Any

    @property
    def where(self) -> str:
        return f"{self.app_label}.{self.migration}"


def _database_operations(operations: list[Any]) -> Iterator[Any]:
    """Every operation that touches the database, looking inside SeparateDatabaseAndState."""
    for operation in operations:
        if isinstance(operation, SeparateDatabaseAndState):
            yield from _database_operations(list(operation.database_operations))
        else:
            yield operation


def planned_operations(loader: MigrationLoader) -> Iterator[MigrationOp]:
    """The database operations of every migration in the graph, in no particular order.

    The graph, not the files on disk: a squashed migration and the ones it replaces are both on
    disk, and only the graph knows which of them a migrate from zero would actually run.
    """
    for key in loader.graph.nodes:
        migration = loader.graph.nodes[key]
        for operation in _database_operations(list(migration.operations)):
            yield MigrationOp(key[0], key[1], operation)


def _is_extension(operation: Any) -> bool:
    try:
        from django.contrib.postgres.operations import CreateExtension
    except ImportError:  # psycopg missing; then no migration can carry one either
        return False
    return isinstance(operation, CreateExtension)


def schema_hazards(loader: MigrationLoader) -> list[MigrationOp]:
    """Operations whose effect no model describes and which cannot be replayed out of order."""
    return [op for op in planned_operations(loader) if isinstance(op.operation, RunSQL)]


def extension_operations(loader: MigrationLoader) -> list[MigrationOp]:
    """``CreateExtension`` operations, which the build runs before it creates any table."""
    return sorted(
        (op for op in planned_operations(loader) if _is_extension(op.operation)),
        key=lambda op: (op.app_label, op.migration),
    )


def _cache_tables() -> set[str]:
    """The DatabaseCache tables, which the entrypoint creates BEFORE the schema (createcachetable)."""
    return {
        str(cache["LOCATION"])
        for cache in settings.CACHES.values()
        if cache.get("BACKEND", "").endswith("DatabaseCache") and cache.get("LOCATION")
    }


def database_is_empty(using: str = DEFAULT_DB_ALIAS) -> bool:
    """True when the database holds no schema yet: no table but the cache's and no applied migration.

    The cache table is ignored because ``createcachetable`` must run before ``migrate`` (the
    tap_health E001 check), so a brand-new stack already has it by the time this is asked.
    """
    connection = connections[using]
    recorder = MigrationRecorder(connection)
    tables = set(connection.introspection.table_names())
    if tables - _cache_tables() - {recorder.Migration._meta.db_table}:
        return False
    return not (recorder.has_table() and recorder.applied_migrations())


def _no_migrations() -> dict[str, None]:
    """``MIGRATION_MODULES`` with every app switched off, the form Django's TEST.MIGRATE=False uses."""
    return {app.label: None for app in apps.get_app_configs()}


def _create_extensions(loader: MigrationLoader, using: str) -> None:
    ops = extension_operations(loader)
    if not ops:
        return
    connection = connections[using]
    with connection.schema_editor() as editor:
        for op in ops:
            logger.info("[38f8] schema-from-models: creating extension from %s", op.where)
            # CreateExtension reads nothing from the states; it issues CREATE EXTENSION IF NOT EXISTS.
            op.operation.database_forwards(op.app_label, editor, None, None)


def build_schema_from_models(using: str = DEFAULT_DB_ALIAS, *, verbosity: int = 0) -> None:
    """Create every table from the models, then record every migration as applied.

    Assumes an empty database; :func:`migrate_from_models` is the entry point that checks.
    Raises :class:`SchemaFromModelsRefused` before touching the database when a migration carries
    raw SQL.
    """
    loader = MigrationLoader(connections[using], ignore_no_migrations=True)
    hazards = schema_hazards(loader)
    if hazards:
        names = ", ".join(sorted({op.where for op in hazards}))
        raise SchemaFromModelsRefused(
            f"cannot build the schema from the models: RunSQL in {names} creates something no model "
            "describes. Migrate this database for real (unset TAP_BOOT_INSTALL__SCHEMA_FROM_MODELS), "
            "or move that SQL somewhere a model-built database also runs it."
        )
    _create_extensions(loader, using)

    saved = settings.MIGRATION_MODULES
    settings.MIGRATION_MODULES = _no_migrations()
    try:
        # Verbosity 0, whatever the caller asked for: at 1 or above, `migrate` follows "No
        # migrations to apply" with the autodetector's "your models have changes" check, which
        # with every migration switched off diffs an empty state against every model and
        # optimises the result pairwise — measured at minutes, not seconds, with aws_core's
        # ~1,000 models. (pytest-django's --nomigrations forces 0 for the same reason.)
        call_command("migrate", database=using, run_syncdb=True, interactive=False, verbosity=0)
    finally:
        settings.MIGRATION_MODULES = saved
    record_all_migrations(using, verbosity=verbosity)
    logger.info("[993c] schema-from-models: built %s from the models and recorded every migration", using)


def migrations_to_record(loader: MigrationLoader) -> list[tuple[str, str]]:
    """The (app, name) rows a migrate from zero leaves in ``django_migrations``.

    The executor's own rules: applying a squashed migration records every migration it replaces
    (``MigrationExecutor.record_migration``), and at the end of the run ``check_replacements``
    records the squash itself once all of those are applied. So a squash leaves its parts and
    itself, and every other migration leaves its own row. (The parity check, ``tap.schema_parity``,
    caught a first version of this that left the squash out: aws_core's ``0001_squashed_0048``.)
    """
    rows: set[tuple[str, str]] = set()
    for key in loader.graph.nodes:
        rows.add(key)
        rows.update(loader.graph.nodes[key].replaces or [])
    return sorted(rows)


def record_all_migrations(using: str = DEFAULT_DB_ALIAS, *, verbosity: int = 0) -> bool:
    """Mark every migration applied without running it, once.

    The rows ``migrate --fake`` would write, written directly: ``migrate --fake`` renders the
    project state of every migration on its way, which with aws_core's graph costs minutes and
    is exactly the cost this module exists to avoid. The post_migrate handlers already ran in the
    syncdb pass, over the real models.

    Only when nothing is recorded yet: a database that already records migrations was either
    migrated or built here, and faking on top of it would mark a migration done whose schema
    change never ran. Returns whether it recorded.
    """
    connection = connections[using]
    recorder = MigrationRecorder(connection)
    if recorder.has_table() and recorder.applied_migrations():
        return False
    rows = migrations_to_record(MigrationLoader(connection, ignore_no_migrations=True))
    recorder.ensure_schema()
    with transaction.atomic(using=using):
        for app_label, name in rows:
            recorder.record_applied(app_label, name)
    if verbosity:
        logger.info("[9be3] schema-from-models: recorded %d migration(s) as applied on %s", len(rows), using)
    return True


def migrate_from_models(using: str = DEFAULT_DB_ALIAS, *, verbosity: int = 0) -> str:
    """Build an empty database from the models; migrate any other database normally.

    Returns :data:`BUILT` or :data:`MIGRATED`, so the caller can say which path it took.
    """
    if database_is_empty(using):
        build_schema_from_models(using, verbosity=verbosity)
        return BUILT
    logger.info("[3e11] schema-from-models: %s already holds a schema, so it is migrated normally", using)
    call_command("migrate", database=using, interactive=False, verbosity=verbosity)
    return MIGRATED
