"""The spine copies on every typed row, kept by the database (req-grid-entity-spine-copies).

Every typed row carries ``spine_deleted_at`` and ``spine_dimensions``: copies of its ``Entity`` row's
``deleted_at`` and ``dimensions``, so that a database policy on a typed table can decide what a reader
may see from that table's own columns (Issue# 1147 - tap; rulings on Issue# 1284 - tap; shipped with
the base-model release, Issue# 1288 - tap). No policy exists yet, and nothing in core reads a copy:
the live-rows manager keeps its join to ``Entity``.

What this module holds:

- **The triggers** (rules 4, 5, 8 and 11). A trigger on the entity table pushes both values to the
  entity's typed row when ``deleted_at`` or ``dimensions`` changes, finding the table through a map
  of entity type to table. A trigger on every typed table fills both copies from the entity row on
  every insert and update, whatever the writer supplied. On insert it reads the entity row ``FOR
  SHARE``, so an insert racing an uncommitted change of the entity waits for it and reads the
  committed result; on update it reads plainly, because the typed row is already locked and a
  concurrent push waits for it. This is the design that held in the two-writer trial (the spec's
  Status Details, 2026-11-23); locking on update as well deadlocked against the push.
- **The installer** (rule 8, rule 9). ``post_migrate`` for ``tap_grid`` installs the functions, a
  trigger on every registered typed table, the type map and then fills existing rows, in one
  transaction, for core's tables and every plugin's alike. A plugin's migration only adds the two
  columns, which ``makemigrations`` generates from the base model; it writes no SQL. It is an
  installer and not a migration operation because a migration operation would have to be written
  into every plugin's migrations (the autodetector never generates one), would freeze the SQL in
  each of them, and would not run on a database built from the models
  (``tap_boot.model_schema``, which refuses ``RunSQL`` and builds every test database). The
  natural-key catch-up runs at the same point for the same reasons (``tap_grid.spine_natural_key``).
- **The drift check and the repair** (rule 10). The check counts, per typed table, the rows whose
  copies differ from their entity row, and the tables that lack a trigger. It reports and fails
  nothing at boot (a non-critical health probe, ``grid.spine_copies``, and ``manage.py
  spine_copies``). :func:`assert_clean` is the gate rule 10 binds the policy requirement to: a
  policy that reads a copy is not enabled, and a role held by one is not served, while it raises.
- **The history values** (rules 12 and 13). A history row records both copies as they are after
  the write that adds it, from the values the write settles on, not from the typed row object
  (which the triggers wrote behind its back). A retirement writes one final history row for the row
  it retires and for each edge it ends.

PostgreSQL only (rule 18).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from django.db import DEFAULT_DB_ALIAS, connections, transaction

logger = logging.getLogger(__name__)

#: The two columns. Declared on ``BaseModel``; written by the triggers alone.
SPINE_COPY_FIELDS: frozenset[str] = frozenset({"spine_deleted_at", "spine_dimensions"})

#: The table that maps an entity type to its typed table, read by the push trigger. Not a Django
#: model, so ``flush`` (which empties every model table) leaves it alone and the triggers keep
#: working in a test database between tests.
TYPE_TABLE = "tap_spine_type_table"
PUSH_FUNCTION = "tap_spine_copies_push"
PULL_FUNCTION = "tap_spine_copies_pull"
#: Both triggers share their function's name.
PUSH_TRIGGER = PUSH_FUNCTION
PULL_TRIGGER = PULL_FUNCTION


# ---------------------------------------------------------------------------
# History values (rules 12 and 13)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def stash_history_copies(
    instance: Any, deleted_at: Any, dimensions: dict[str, Any] | None, batch_id: Any = None
) -> Iterator[None]:
    """Hold, for the save inside, the copies and the batch the history row it writes records.

    ``BaseModel.save`` opens it around ``super().save()``: the values are the entity's ``deleted_at``
    and the dimension map the write settles on, worked out before the typed row is saved. The typed
    row object cannot give them: the triggers write the typed columns inside the database, and on a
    change of dimensions the typed row is saved before the entity row is written (rule 12).
    """
    instance._spine_history = {
        "deleted_at": deleted_at,
        "dimensions": dict(dimensions or {}),
        "batch_id": "" if batch_id is None else str(batch_id),
    }
    try:
        yield
    finally:
        instance.__dict__.pop("_spine_history", None)


def fill_history_row(sender: Any, *, instance: Any, history_instance: Any, **kwargs: Any) -> None:
    """Set a history row's copies and batch before it is inserted (``pre_create_historical_record``).

    From the values the write stashed (:func:`stash_history_copies`); where it stashed none (a
    history row written by some other path), from the entity row as it stands in this transaction,
    and the batch from the caller's context. Never from the typed row object's own copies.
    """
    if not hasattr(history_instance, "spine_dimensions"):
        return  # a history model that is not a typed row's (none in core today)
    stashed = getattr(instance, "_spine_history", None)
    if stashed is None:
        from tap_grid.caller_context import get_caller_context
        from tap_grid.models import Entity

        row = Entity.objects.using(kwargs.get("using") or DEFAULT_DB_ALIAS).filter(pk=instance.entity_id)
        found = row.values("deleted_at", "dimensions").first() or {"deleted_at": None, "dimensions": {}}
        ctx = get_caller_context()
        stashed = {
            "deleted_at": found["deleted_at"],
            "dimensions": found["dimensions"] or {},
            "batch_id": str(ctx.batch_id) if ctx is not None and ctx.batch_id else "",
        }
    history_instance.spine_deleted_at = stashed["deleted_at"]
    history_instance.spine_dimensions = stashed["dimensions"]
    if hasattr(history_instance, "batch_id"):
        history_instance.batch_id = stashed["batch_id"]


def write_retirement_history(model_cls: type, entity_ids: Iterable[Any], *, reason: str, batch_id: Any) -> int:
    """Write one final history row for each typed row a retirement has just tombstoned (rule 13).

    Called by the write pipeline after the entity rows are updated, so each row records the
    retirement copy and the retirement's reason (``req-grid-service-delete-reason-2``). A type that
    keeps no history (``req-grid-history-optout``) writes none. Returns the number written.
    """
    from tap_grid.history import is_history_enabled
    from tap_grid.models import BASE_HISTORY, Entity

    ids = list(entity_ids)
    if not ids or not is_history_enabled(model_cls):
        return 0
    spine = {
        row["pk"]: row for row in Entity.objects.filter(pk__in=ids).values("pk", "deleted_at", "dimensions")
    }
    written = 0
    for row in model_cls.all_objects.filter(entity_id__in=ids).order_by("entity_id"):  # type: ignore[attr-defined]
        entity = spine.get(row.entity_id)
        if entity is None:
            continue
        row._change_reason = reason[:100]
        with stash_history_copies(row, entity["deleted_at"], entity["dimensions"], batch_id):
            BASE_HISTORY.create_historical_record(row, "~")
        written += 1
    return written


# ---------------------------------------------------------------------------
# The triggers and their installer (rules 4, 5, 8, 9, 11)
# ---------------------------------------------------------------------------


def _entity_table() -> str:
    from tap_grid.models import Entity

    return Entity._meta.db_table


def _functions_sql(quote: Any) -> list[str]:
    entity = quote(_entity_table())
    type_table = quote(TYPE_TABLE)
    return [
        f"CREATE TABLE IF NOT EXISTS {type_table} (entity_type varchar(255) PRIMARY KEY, table_name text NOT NULL)",
        # Rule 4: an entity row's deleted_at or dimensions changed -> both values to its typed row.
        # A type with no entry (its plugin is not installed) is left alone.
        f"""
CREATE OR REPLACE FUNCTION {PUSH_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE target text;
BEGIN
  SELECT table_name INTO target FROM {type_table} WHERE entity_type = NEW.entity_type;
  IF target IS NOT NULL THEN
    EXECUTE format('UPDATE %I SET spine_deleted_at = $1, spine_dimensions = $2 WHERE entity_id = $3', target)
      USING NEW.deleted_at, NEW.dimensions, NEW.id;
  END IF;
  RETURN NULL;
END
$fn$""",
        # Rules 5 and 11: a typed row inserted or updated -> both copies from its entity row. An
        # insert reads the entity row FOR SHARE: a typed row that does not exist yet cannot make a
        # concurrent push wait, so the insert waits for the entity change instead. An update reads
        # plainly: the typed row is already locked, so a concurrent push waits for this statement.
        f"""
CREATE OR REPLACE FUNCTION {PULL_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE retired timestamptz; dims jsonb;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT e.deleted_at, e.dimensions INTO retired, dims FROM {entity} e WHERE e.id = NEW.entity_id FOR SHARE;
  ELSE
    SELECT e.deleted_at, e.dimensions INTO retired, dims FROM {entity} e WHERE e.id = NEW.entity_id;
  END IF;
  NEW.spine_deleted_at := retired;
  NEW.spine_dimensions := COALESCE(dims, '{{}}'::jsonb);
  RETURN NEW;
END
$fn$""",
    ]


def _push_trigger_sql(quote: Any) -> str:
    return (
        f"CREATE OR REPLACE TRIGGER {PUSH_TRIGGER} AFTER UPDATE OF deleted_at, dimensions ON {quote(_entity_table())} "
        "FOR EACH ROW WHEN (OLD.deleted_at IS DISTINCT FROM NEW.deleted_at OR OLD.dimensions IS DISTINCT FROM "
        f"NEW.dimensions) EXECUTE FUNCTION {PUSH_FUNCTION}()"
    )


def _pull_trigger_sql(quote: Any, table: str) -> str:
    return (
        f"CREATE OR REPLACE TRIGGER {PULL_TRIGGER} BEFORE INSERT OR UPDATE ON {quote(table)} "
        f"FOR EACH ROW EXECUTE FUNCTION {PULL_FUNCTION}()"
    )


def _fill_sql(quote: Any, table: str) -> str:
    """Rule 9's one set-based statement: every row whose copies differ, brought into step."""
    return (
        f"UPDATE {quote(table)} t SET spine_deleted_at = e.deleted_at, spine_dimensions = e.dimensions "  # noqa: S608  # nosec B608 - quoted names from model metadata, no values
        f"FROM {quote(_entity_table())} e WHERE e.id = t.entity_id AND "
        "(t.spine_deleted_at IS DISTINCT FROM e.deleted_at OR t.spine_dimensions IS DISTINCT FROM e.dimensions)"
    )


def _drift_sql(quote: Any, table: str) -> str:
    return (
        f"SELECT count(*) FROM {quote(table)} t JOIN {quote(_entity_table())} e ON e.id = t.entity_id "  # noqa: S608  # nosec B608 - quoted names from model metadata, no values
        "WHERE t.spine_deleted_at IS DISTINCT FROM e.deleted_at OR t.spine_dimensions IS DISTINCT FROM e.dimensions"
    )


def typed_tables() -> dict[str, str]:
    """Every registered entity type and its typed table, from the model registry."""
    from tap_grid.models import BaseModel
    from tap_grid.registry import get_model_class, list_entity_types

    tables: dict[str, str] = {}
    for entity_type in sorted(list_entity_types()):
        model = get_model_class(entity_type)
        meta = getattr(model, "_meta", None)
        if not isinstance(model, type) or not issubclass(model, BaseModel) or meta is None:
            continue
        if meta.abstract or meta.proxy or not meta.managed:
            continue
        tables[entity_type] = meta.db_table
    return tables


def _ready_tables(connection: Any, wanted: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """The wanted tables that exist and hold both columns, and why each other one was skipped."""
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
        ready: dict[str, str] = {}
        skipped: dict[str, str] = {}
        for entity_type, table in wanted.items():
            if table not in existing:
                skipped[entity_type] = f"table {table} does not exist"
                continue
            columns = {c.name for c in connection.introspection.get_table_description(cursor, table)}
            missing = sorted(SPINE_COPY_FIELDS - columns)
            if missing:
                skipped[entity_type] = f"table {table} has no column {', '.join(missing)}; migrate its app"
                continue
            ready[entity_type] = table
    return ready, skipped


@dataclass
class InstallReport:
    """What one :func:`install` did."""

    tables: dict[str, str] = field(default_factory=dict)
    filled: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def install(*, using: str = DEFAULT_DB_ALIAS) -> InstallReport:
    """Install the functions, every typed table's trigger, the type map and the push trigger, then fill.

    Idempotent, one transaction. A registered type whose table does not exist yet or lacks the two
    columns is skipped and reported: it gets no trigger and no map entry, so the push leaves it
    alone, and the next migrate installs it. Rows are filled after the triggers are in place, so a
    row written after this commits is kept by them.

    TAP-IMPLEMENTS: req-grid-entity-spine-copies@85bf6510c873/9775d283d56b (derivation) — rules 8 and 9: the
        one installer of the triggers and the type map, for core's and every plugin's tables.
    """
    connection = connections[using]
    report = InstallReport()
    if connection.vendor != "postgresql":
        report.skipped["*"] = f"the spine copies are kept by PostgreSQL triggers; {connection.vendor} has none"
        return report
    quote = connection.ops.quote_name
    ready, report.skipped = _ready_tables(connection, typed_tables())
    with transaction.atomic(using=using), connection.cursor() as cursor:
        for statement in _functions_sql(quote):
            cursor.execute(statement)
        for table in sorted(set(ready.values())):
            cursor.execute(_pull_trigger_sql(quote, table))
        cursor.execute(f"DELETE FROM {quote(TYPE_TABLE)}")  # noqa: S608  # nosec B608 - a constant name
        for entity_type, table in sorted(ready.items()):
            cursor.execute(
                f"INSERT INTO {quote(TYPE_TABLE)} (entity_type, table_name) VALUES (%s, %s)",  # noqa: S608  # nosec B608
                [entity_type, table],
            )
        cursor.execute(_push_trigger_sql(quote))
        for table in sorted(set(ready.values())):
            cursor.execute(_fill_sql(quote, table))
            if cursor.rowcount:
                report.filled[table] = cursor.rowcount
    report.tables = ready
    for entity_type, why in sorted(report.skipped.items()):
        logger.warning("[7c31] spine copies: %s skipped: %s", entity_type, why)
    if report.filled:
        logger.info("[7c32] spine copies: filled %s", report.filled)
    return report


def install_after_migrate(sender: Any, *, using: str = DEFAULT_DB_ALIAS, plan: Any = None, **kwargs: Any) -> None:
    """Install after ``migrate`` has applied every app's migrations (rule 8).

    Connected to ``post_migrate`` for ``tap_grid``; Django sends it once the whole plan has applied,
    so plugin tables migrated in the same run are there. A build from the models sends it with an
    empty plan and is installed too. ``flush`` sends it with no plan: the triggers and the type map
    are not model tables, so a flush leaves them in place, and nothing is done. A rollback is not
    undone: its plan steps backwards, and the installer leaves the database as the reversal left it.
    """
    if plan is None or any(backwards for _migration, backwards in plan):
        return
    install(using=using)


# ---------------------------------------------------------------------------
# The drift check and the repair (rule 10)
# ---------------------------------------------------------------------------


@dataclass
class DriftReport:
    """What :func:`check` found. Clean only when every typed table was checked and agreed."""

    checked: dict[str, int] = field(default_factory=dict)  # table -> rows differing
    untriggered: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    push_trigger: bool = False

    @property
    def drifted(self) -> dict[str, int]:
        return {table: count for table, count in self.checked.items() if count}

    @property
    def clean(self) -> bool:
        # A table that was not checked cannot count as clean: a gate must not pass on work it did not do.
        return self.push_trigger and not self.drifted and not self.untriggered and not self.unmapped and not self.skipped

    def summary(self) -> str:
        if self.clean:
            return f"spine copies agree with the entity rows in {len(self.checked)} typed table(s)"
        parts = []
        if not self.push_trigger:
            parts.append(f"no {PUSH_TRIGGER} trigger on {_entity_table()}")
        if self.drifted:
            parts.append("rows out of step: " + ", ".join(f"{t}={n}" for t, n in sorted(self.drifted.items())))
        if self.untriggered:
            parts.append("tables with no trigger: " + ", ".join(sorted(self.untriggered)))
        if self.unmapped:
            parts.append("types missing from the map: " + ", ".join(sorted(self.unmapped)))
        if self.skipped:
            parts.append("not checked: " + ", ".join(f"{k} ({v})" for k, v in sorted(self.skipped.items())))
        return "; ".join(parts)


class SpineCopiesDrift(RuntimeError):
    """The copies differ from the entity rows, or are not kept on some table (rule 10)."""

    def __init__(self, report: DriftReport) -> None:
        self.report = report
        super().__init__(f"the spine copies cannot be trusted: {report.summary()} (req-grid-entity-spine-copies)")


def check(*, using: str = DEFAULT_DB_ALIAS) -> DriftReport:
    """Count, per typed table, the rows whose copies differ from their entity row. Changes nothing.

    Also reports a table with no trigger, a type missing from the map, and a missing push trigger:
    each means the copies are not being kept, which a count of zero today would hide.
    """
    connection = connections[using]
    report = DriftReport()
    if connection.vendor != "postgresql":
        report.skipped["*"] = f"{connection.vendor} keeps no spine copies"
        return report
    quote = connection.ops.quote_name
    ready, report.skipped = _ready_tables(connection, typed_tables())
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND t.tgname IN (%s, %s)",
            [PUSH_TRIGGER, PULL_TRIGGER],
        )
        triggers = {(relname, tgname) for relname, tgname in cursor.fetchall()}
        report.push_trigger = (_entity_table(), PUSH_TRIGGER) in triggers
        mapped: dict[str, str] = {}
        if TYPE_TABLE in set(connection.introspection.table_names(cursor)):
            cursor.execute(f"SELECT entity_type, table_name FROM {quote(TYPE_TABLE)}")  # noqa: S608  # nosec B608
            mapped = dict(cursor.fetchall())
        for entity_type, table in sorted(ready.items()):
            if mapped.get(entity_type) != table:
                report.unmapped.append(entity_type)
            if (table, PULL_TRIGGER) not in triggers and table not in report.untriggered:
                report.untriggered.append(table)
            if table in report.checked:
                continue
            cursor.execute(_drift_sql(quote, table))
            report.checked[table] = int(cursor.fetchone()[0])
    return report


def repair(*, using: str = DEFAULT_DB_ALIAS) -> dict[str, int]:
    """Bring every typed table's copies into step by rule 9's statement; returns rows changed per table.

    Reinstalls first, so a table that lost its trigger (a restore can drop them) is kept again.
    """
    return install(using=using).filled


def assert_clean(*, using: str = DEFAULT_DB_ALIAS) -> DriftReport:
    """Raise :class:`SpineCopiesDrift` unless the check is clean: the gate for any reader of the copies.

    Rule 10 binds the requirement that adds row-level policies: a policy that reads a copy is not
    enabled, and a role held by one is not served, while the check finds a difference, and a
    difference found then is refused, not reported. No policy exists yet, so nothing calls this in
    production; it is the one call that requirement makes.
    """
    report = check(using=using)
    if not report.clean:
        raise SpineCopiesDrift(report)
    return report
