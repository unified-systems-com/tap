"""Keep ``Entity.natural_key`` true to every keyed row's declared columns (req-grid-entity-natural-key-23, -25).

``BaseModel.save`` derives the spine natural key on every write (``-19``), and the guarded querysets
keep their bulk writes true. What neither sees, and how it catches up:

- **the backfill** — migration ``tap_grid/0010`` runs :func:`sync` once over every registered type,
  core and plugin, recording each type's recipe fingerprint;
- **a plugin data migration that rewrites constituting values** (a re-key) — it calls
  :func:`resync_natural_keys` for its own types afterwards, in a ``RunPython`` step;
- **a changed recipe** — a type whose ``NATURAL_KEY`` tuple changed, or a new composition — shows
  as a fingerprint that no longer matches :class:`~tap_grid.models.NaturalKeyRecipe`;
  ``manage.py sync_spine_natural_keys --changed``, run at deploy, re-derives exactly those types;
- **drift of any other kind** — ``manage.py sync_spine_natural_keys --check`` samples each type's
  rows, compares the stored value with a fresh composition, and reports.

Raw SQL, on purpose. A migration runs with no service-layer write scope and no read context, and
the historical models a migration is handed carry no ``NATURAL_KEY``, so this reads the declaration
from the registered class and the rows through a cursor. A type whose table or declared columns do
not exist yet is reported and skipped, and gets no fingerprint, so the next ``--changed`` run picks it
up.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from tap_grid.natural_key import declared_columns, recipe_fingerprint, row_natural_key

logger = logging.getLogger(__name__)

#: Rows read and written per round trip.
CHUNK = 2000


@dataclass
class SyncReport:
    """What one :func:`sync` changed, and which types it could not read."""

    types: int = 0
    rows: int = 0
    written: int = 0
    skipped: dict[str, str] = field(default_factory=dict)


@dataclass
class DriftReport:
    """What :func:`check` found: per type, sampled rows whose stored key differs, and stale recipes."""

    sampled: int = 0
    drifted: dict[str, list[tuple[str, str | None, str | None]]] = field(default_factory=dict)
    stale_recipes: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        # A skipped type was not checked, so it cannot count as clean: a gate must not pass on
        # work it did not do.
        return not self.drifted and not self.stale_recipes and not self.skipped


def _registered_models(entity_types: Iterable[str] | None) -> list[Any]:
    from tap_grid.models import BaseModel
    from tap_grid.registry import get_model_class, list_entity_types

    if entity_types is None:
        models = []
        for entity_type in sorted(list_entity_types()):
            model = get_model_class(entity_type)
            if isinstance(model, type) and issubclass(model, BaseModel):
                models.append(model)
        return models
    # A type asked for by name must exist and be keyed by the grid: a typo checking zero types
    # would report clean having done no work.
    named = []
    for entity_type in entity_types:
        try:
            model = get_model_class(entity_type)
        except KeyError:
            raise ValueError(f"unknown entity type {entity_type!r}") from None
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise ValueError(f"entity type {entity_type!r} is not a BaseModel type; it has no spine natural key")
        named.append(model)
    return named


def _decode(model: Any, columns: list[str], values: tuple[Any, ...]) -> dict[str, object]:
    """A row as the save path sees it: a JSON column decoded, every other column as the driver gives it."""
    from django.db.models import JSONField

    row: dict[str, object] = {}
    for column, value in zip(columns, values, strict=True):
        if isinstance(value, str) and isinstance(model._meta.get_field(column), JSONField):
            value = json.loads(value)
        row[column] = value
    return row


def _undeclared(model: Any) -> str | None:
    """Why this type has no spine key to derive because it never declared one. Undeclared is never
    treated as keyless (``req-grid-entity-natural-key-5``), so the type is skipped, which keeps a check
    from passing on it, instead of being published as null and recorded as in step."""
    from tap_grid.natural_key import KEYLESS

    declared = getattr(model, "NATURAL_KEY", None)
    if isinstance(declared, tuple) or declared is KEYLESS:
        return None
    return "NATURAL_KEY is undeclared; declare the constituting entries or KEYLESS with a reason"


def _readable(connection: Any, model: Any, tables: set[str]) -> str | None:
    """Why this type's rows cannot be read yet, or ``None`` when they can."""
    table = model._meta.db_table
    if table not in tables:
        return f"table {table} does not exist yet"
    with connection.cursor() as probe:
        present = {c.name for c in connection.introspection.get_table_description(probe, table)}
    missing = [
        model._meta.get_field(column).column
        for column in declared_columns(model)
        if model._meta.get_field(column).column not in present
    ]
    return f"columns {missing} do not exist yet on {table}" if missing else None


def _rows_sql(connection: Any, model: Any, *, limit: int | None = None) -> str:
    quote = connection.ops.quote_name
    selected = "".join(f", t.{quote(model._meta.get_field(c).column)}" for c in declared_columns(model))
    sql = (
        f"SELECT e.id, e.natural_key{selected} FROM {quote(model._meta.db_table)} t "  # noqa: S608  # nosec B608 - quoted names from model metadata, no values
        f"JOIN {quote('tap_entity')} e ON e.id = t.{quote('entity_id')}"
    )
    return sql if limit is None else f"{sql} ORDER BY random() LIMIT {int(limit)}"


def _record(connection: Any, entity_type: str, fingerprint: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tap_natural_key_recipe (entity_type, fingerprint, synced_at) "
            "VALUES (%s, %s, now()) ON CONFLICT (entity_type) "
            "DO UPDATE SET fingerprint = EXCLUDED.fingerprint, synced_at = EXCLUDED.synced_at",
            [entity_type, fingerprint],
        )


def _recorded(connection: Any, tables: set[str]) -> dict[str, str]:
    if "tap_natural_key_recipe" not in tables:
        return {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT entity_type, fingerprint FROM tap_natural_key_recipe")
        return dict(cursor.fetchall())


def sync(
    entity_types: Iterable[str] | None = None,
    *,
    changed_only: bool = False,
    using: str = "default",
) -> SyncReport:
    """Re-derive ``Entity.natural_key`` for every row of the named types (else every registered type)
    and write only what differs; record each type's recipe fingerprint once it is in step.

    ``changed_only`` limits the pass to types whose fingerprint differs from the recorded one, or has
    none — the deploy-time run. Idempotent; tombstoned rows are included and keep their key. A
    KEYLESS type's spine keys are set to null.
    """
    from django.db import connections, transaction

    connection = connections[using]
    report = SyncReport()
    with connection.cursor() as probe:
        tables = set(connection.introspection.table_names(probe))
    recorded = _recorded(connection, tables)
    # Conditional on the value read: a normal write that lands between the read and this update
    # has already published the fresh key, and the catch-up must not put the stale one back.
    set_spine = "UPDATE tap_entity SET natural_key = %s WHERE id = %s AND natural_key IS NOT DISTINCT FROM %s"
    for model in _registered_models(entity_types):
        entity_type = model.ENTITY_TYPE
        # Undeclared first: a type that was once recorded in step must not ride the changed-only
        # short-circuit past the guard (-5).
        undeclared = _undeclared(model)
        if undeclared is not None:
            report.skipped[entity_type] = undeclared
            continue
        fingerprint = recipe_fingerprint(model)
        if changed_only and recorded.get(entity_type) == fingerprint:
            continue
        reason = _readable(connection, model, tables)
        if reason is not None:
            report.skipped[entity_type] = reason
            continue
        report.types += 1
        columns = declared_columns(model)
        # A server-side cursor (chunked_cursor), so a large table streams in CHUNK rows instead of
        # being buffered whole by the driver.
        with transaction.atomic(using=using), connection.chunked_cursor() as reader, connection.cursor() as writer:
            reader.execute(_rows_sql(connection, model))
            while rows := reader.fetchmany(CHUNK):
                changes = []
                for entity_id, published, *values in rows:
                    report.rows += 1
                    derived = row_natural_key(model, _decode(model, columns, tuple(values))) if columns else None
                    if derived != published:
                        changes.append((derived, entity_id, published))
                if changes:
                    writer.executemany(set_spine, changes)
                    report.written += len(changes)
        if "tap_natural_key_recipe" in tables:
            _record(connection, entity_type, fingerprint)
    for entity_type, why in sorted(report.skipped.items()):
        logger.info("[32c7] spine natural key sync: skipped %s: %s", entity_type, why)
    return report


def find_by_spine_key(
    queryset: Any = None,
    *,
    equals: str | None = None,
    prefix: str | None = None,
    entity_type: str | None = None,
) -> Any:
    """Spine rows by their natural key: exactly one of ``equals`` (the full value) or ``prefix``.

    The query shape the indexes need (``req-grid-entity-natural-key-22``, ``-24``). Equality compares
    the full value, which the hash index serves. A prefix filters twice: ``left(natural_key, N) LIKE
    '<first N chars>%'``, the expression the prefix index covers, and ``natural_key LIKE
    '<prefix>%'`` on the full value, the recheck that makes a prefix longer than N exact. Both LIKE
    patterns escape ``%`` and ``_`` (Django's ``startswith``). For the leading values of a
    multi-field key, build the prefix with :func:`tap_grid.natural_key.natural_key_prefix` — it ends
    with the separator, so ``corp|10.0.1.5|`` never matches ``corp|10.0.1.50|…``. ``entity_type``
    narrows to one type; without it the search runs across types, which is the point. Tombstoned
    rows keep their key and are included; narrow with ``.live()``.
    """
    from django.db.models.functions import Left

    from tap_grid.models import Entity
    from tap_grid.natural_key import PREFIX_INDEX_CHARS

    if (equals is None) == (prefix is None):
        raise ValueError("pass exactly one of equals= or prefix=")
    rows = Entity.objects.all() if queryset is None else queryset
    if entity_type is not None:
        rows = rows.filter(entity_type=entity_type)
    if equals is not None:
        return rows.filter(natural_key=equals)
    wanted = str(prefix)
    return rows.alias(_nk_head=Left("natural_key", PREFIX_INDEX_CHARS)).filter(
        _nk_head__startswith=wanted[:PREFIX_INDEX_CHARS], natural_key__startswith=wanted
    )


def resync_natural_keys(*entity_types: str, using: str = "default") -> SyncReport:
    """Re-derive the spine natural keys of these types — THE call for a plugin data migration that
    rewrites constituting values (a re-key, ``-8``, ``-23``)::

        def rekey(apps, schema_editor):
            ...  # rewrite the key columns
            from tap_grid.spine_natural_key import resync_natural_keys
            resync_natural_keys("aws_core__aws_vpc", using=schema_editor.connection.alias)
    """
    if not entity_types:
        raise ValueError("name the entity types whose keys this migration rewrote")
    return sync(entity_types, using=using)


def check(entity_types: Iterable[str] | None = None, *, sample: int = 200, using: str = "default") -> DriftReport:
    """Sample each type's rows and compare the stored spine key with a fresh composition; list the
    types whose recorded recipe fingerprint is missing or differs. Reads only. A sample under one
    row would check nothing and could report clean, so it is refused."""
    from django.db import connections

    if sample < 1:
        raise ValueError(f"--sample must be at least 1 (got {sample}): a check of zero rows checks nothing")
    connection = connections[using]
    report = DriftReport()
    with connection.cursor() as probe:
        tables = set(connection.introspection.table_names(probe))
    recorded = _recorded(connection, tables)
    for model in _registered_models(entity_types):
        entity_type = model.ENTITY_TYPE
        if recorded.get(entity_type) != recipe_fingerprint(model):
            report.stale_recipes.append(entity_type)
        reason = _undeclared(model) or _readable(connection, model, tables)
        if reason is not None:
            report.skipped[entity_type] = reason
            continue
        columns = declared_columns(model)
        with connection.cursor() as reader:
            reader.execute(_rows_sql(connection, model, limit=sample))
            for entity_id, published, *values in reader.fetchall():
                report.sampled += 1
                derived = row_natural_key(model, _decode(model, columns, tuple(values))) if columns else None
                if derived != published:
                    report.drifted.setdefault(entity_type, []).append((str(entity_id), published, derived))
    return report


def sync_after_migrate(sender: Any, *, using: str = "default", plan: Any = None, **kwargs: Any) -> None:
    """Re-derive the spine keys of every type whose recipe changed, once ``migrate`` has applied
    every app's migrations (``-23``). Migration 0010 skips plugin tables that do not exist yet, and a
    NATURAL_KEY can change with no migration at all, so the catch-up runs here, at every migrate,
    rather than relying on a deploy step to remember it. Django sends post_migrate once the whole
    plan has applied, for every app, so plugin migrations in the same run have landed by now.
    ``flush`` sends it with no plan, and a rollback with backwards steps; both are skipped."""
    if plan is None:
        return
    # A rollback (any step applied backwards) must not be undone by the catch-up: reversing 0010
    # clears the keys on purpose.
    if any(backwards for _migration, backwards in plan):
        return
    sync(changed_only=True, using=using)
