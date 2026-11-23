"""Applying a version to stored rows: the adapter a migration calls.

``req-grid-entity-model-version`` rules 18 and 27 to 33. A plugin's data migration does not write
the typed table itself. It calls :func:`apply_version`, which carries every stored row of one type
from version N to N+1 by the step the type's author declared, the same step an import uses.

What the adapter does, in one transaction:

1. checks first, changing nothing (rule 33): the link is a step, the applied version is the one
   the step starts from, no live edge is refused by a tightened rule (rule 32), and every history
   value of a field whose type changes can be converted (rule 27);
2. for every row the step changes: writes the typed row, moves the entity's revision, sets
   ``last_changed_batch_id`` to its own batch, writes one history row, and records one batch event
   of the ``maintenance`` type. The last-observed pointers, ``last_observed_at`` and the collection
   pair stay where they were. A row the step returns unchanged is not written (rule 30);
3. leaves each FLIP entry with the source that asserted the value, following the step's
   declaration and never the values (rule 31);
4. writes the applied version last (rule 33).

How it is called from a migration
---------------------------------
A Django data migration works on historical models, which carry a model's fields and none of its
class attributes. So the adapter takes three things from three places:

- the rows, from the historical model of ``apps`` at that point of the migration. That model has
  the columns the database has right then, which is what a chain needs: a field version 2 added
  and version 3 removed exists in the database between the two migrations and on no class;
- the step, from the type's ``model_links`` module (``tap_grid.version_links``), which never
  imports the model class;
- what the type is (its entity type, whether it keeps history, how its spine values are derived),
  from the installed class in the registry, read only for that.

The typed write goes through the historical model, so it writes the columns that exist at that
point. The spine write goes through the guarded ``Entity`` manager as the named below-pipeline
writer ``version_migration``, which may write the revision, the changed-by pointer, and the name
and event time the grid derives from a typed row, and nothing else. The stored key on the spine is
brought in step by its own catch-up, called here for the type.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import DEFAULT_DB_ALIAS, connections, models, transaction
from django.utils import timezone

from tap_grid import version_links
from tap_grid.model_version import EDGE, FIRST_VERSION, NODE

if TYPE_CHECKING:
    from tap_grid.models import Batch

logger = logging.getLogger(__name__)

BATCH_SOURCE = "grid:maintenance"
REASON = "model_version"
WRITER = "version_migration"
CHUNK = 2_000
_CHECK_NOW = "SET CONSTRAINTS ALL IMMEDIATE"
_DEFER_AGAIN = "SET CONSTRAINTS ALL DEFERRED"
SAMPLE = 10

#: The spine fields the adapter may write: the revision and its time, the batch that last changed
#: the row, and the values the grid derives from a typed row.
SPINE_FIELDS = frozenset(
    {
        "version",
        "updated_at",
        "last_changed_batch_id",
        "name",
        "event_start",
        "event_end",
        "event_precision",
        "dimensions",
    }
)


class VersionMigrationRefused(Exception):
    """The adapter will not carry the type to the version asked for. Nothing was changed."""


@dataclass
class MigrationReport:
    """What one call read and changed."""

    type_slug: str
    from_version: int
    to_version: int
    rows: int = 0
    changed: int = 0
    history_rows: int = 0
    history_discarded: dict[str, int] = field(default_factory=dict)
    batch_id: str | None = None
    applied: bool = False
    note: str = ""


@dataclass(frozen=True)
class _Target:
    """The type the adapter is carrying, as the three sources describe it."""

    slug: str
    kind: str
    live: Any  # the installed class: what the type is, never its columns
    rows: Any  # the historical model the rows are read and written through
    history: Any | None  # the historical model of its history table; None where it keeps none
    declared: int


def _actor() -> Any:
    """Who a migration's batch is recorded under: the bootloader's program actor.

    A migration has no request and no named user. The bootloader actor is the one every other
    write made while a grid is being stood up runs as.
    """
    from tap_auth.actors import BOOTLOADER, get_builtin_actor

    return get_builtin_actor(BOOTLOADER)


def _target(apps: Any, type_slug: str) -> _Target:
    from tap_grid import model_version
    from tap_grid.constraints import list_registered_edge_types
    from tap_grid.models import Edge
    from tap_grid.registry import get_model_class, list_entity_types

    if type_slug in list_entity_types() and type_slug != EDGE:
        live: Any = get_model_class(type_slug)
        kind, declared = NODE, model_version.declared_version(live)
    elif type_slug in list_registered_edge_types() or model_version.edge_version_declared(type_slug):
        live, kind, declared = Edge, EDGE, model_version.declared_edge_version(type_slug)
    else:
        raise VersionMigrationRefused(f"{type_slug!r} is not an installed node type or edge type")
    meta = live._meta
    rows = apps.get_model(meta.app_label, meta.object_name)
    history = None
    if getattr(live, "TRACK_HISTORY", True):
        try:
            history = apps.get_model(meta.app_label, f"Historical{meta.object_name}")
        except LookupError as missing:
            # A type that keeps history is never carried without writing it. The history model is
            # absent from this point of the migration only when the migration does not depend on
            # the state that has it.
            raise VersionMigrationRefused(
                f"{type_slug!r} keeps history, and the migration's state has no Historical{meta.object_name} "
                f"model in {meta.app_label!r}. The migration must depend on the migration that creates the "
                "history table, so the adapter can write a history row for every row it changes; nothing was "
                "changed"
            ) from missing
    return _Target(type_slug, kind, live, rows, history, declared)


def _own_fields(target: _Target) -> list[Any]:
    """The type's own columns at this point of the migration: not the ones every type inherits."""
    from tap_grid.model_definition import inherited_field_names
    from tap_grid.models import BaseModel

    inherited = inherited_field_names(BaseModel)
    return [f for f in target.rows._meta.concrete_fields if f.name not in inherited and not f.primary_key]


def _queryset(target: _Target, using: str) -> Any:
    rows = target.rows._default_manager.using(using)
    return rows.filter(edge_type=target.slug) if target.kind == EDGE else rows


def _held(target: _Target, using: str) -> bool:
    return bool(_queryset(target, using).exists())


# ---------------------------------------------------------------------------
# The checks made before anything is changed (rules 27, 32 and 33)
# ---------------------------------------------------------------------------


def _edge_violations(target: _Target, using: str) -> list[str]:
    """Live edges the installed rules would refuse, grouped (rule 32). Retired edges are not checked.

    For a node type: every live edge that starts or ends at a node of the type. For an edge type:
    every live edge of the type. The rules asked are the installed ones, through the same
    ``validate_edge`` a write is held to.
    """
    from django.db.models import Count, Q

    from tap_grid.constraints import validate_edge
    from tap_grid.exceptions import InvalidEdgeError
    from tap_grid.models import Edge

    # Typed as Any: the manager's stubs are the base model's, which has none of an edge's fields.
    live_edges: Any = Edge.all_objects.using(using).filter(entity__deleted_at__isnull=True)
    if target.kind == EDGE:
        live_edges = live_edges.filter(edge_type=target.slug)
    else:
        live_edges = live_edges.filter(Q(from_entity__entity_type=target.slug) | Q(to_entity__entity_type=target.slug))
    groups = (
        live_edges.values("edge_type", "from_entity__entity_type", "to_entity__entity_type")
        .annotate(held=Count("pk"))
        .order_by("edge_type", "from_entity__entity_type", "to_entity__entity_type")
    )
    found: list[str] = []
    for group in groups:
        edge_type = group["edge_type"]
        source, destination = group["from_entity__entity_type"], group["to_entity__entity_type"]
        try:
            validate_edge(source, destination, edge_type)
        except InvalidEdgeError:
            sample = live_edges.filter(
                edge_type=edge_type, from_entity__entity_type=source, to_entity__entity_type=destination
            ).values_list("entity_id", flat=True)[:SAMPLE]
            found.append(
                f"{group['held']} live {edge_type} edge(s) from {source} to {destination} "
                f"(for example {', '.join(str(entity_id) for entity_id in sample)})"
            )
    return found


def _recorded_definition(target: _Target, version: int) -> Mapping[str, Any] | None:
    """The committed definition of the type at ``version``, where its owner has recorded one."""
    from django.apps import apps as installed

    from tap_grid import model_definition as definition

    owner = installed.get_containing_app_config(target.live.__module__)
    if owner is None or target.kind != NODE:
        return None
    try:
        record = definition.load_record(definition.app_record_path(owner.name))
    except LookupError, ValueError, OSError:
        return None
    for entry in (record.get(definition._SECTIONS[NODE]) or {}).get(target.slug) or []:
        if isinstance(entry, Mapping) and entry.get("version") == version:
            found = entry.get("definition")
            return found if isinstance(found, Mapping) else None
    return None


#: Django's field classes by name: what a recorded definition's ``type`` names.
_FIELD_CLASSES: dict[str, Callable[..., models.Field[Any, Any]]] = {
    name: value for name, value in vars(models).items() if isinstance(value, type) and issubclass(value, models.Field)
}


def _field_from_definition(definition: Mapping[str, Any]) -> models.Field[Any, Any] | None:
    """A field of the recorded type, enough of it to ask the database what column type it has."""
    field_class = _FIELD_CLASSES.get(str(definition.get("type", "")))
    if field_class is None:
        return None
    options: dict[str, Any] = {"null": bool(definition.get("null"))}
    for name in ("max_length", "max_digits", "decimal_places"):
        if definition.get(name) is not None:
            options[name] = definition[name]
    try:
        return field_class(**options)
    except TypeError:
        return None


def _retyped_fields(target: _Target, to_version: int, using: str) -> dict[str, tuple[Any, str, bool]]:
    """Fields the type keeps whose column type changes at ``to_version``.

    Name -> (the field as the database has it now, the column type it is changing to, whether the
    new field can be empty). The new type is read from the committed record of ``to_version``
    where there is one, and from the installed class where ``to_version`` is the version it
    declares. Where neither says, nothing is known and nothing is returned.
    """
    connection = connections[using]
    recorded = _recorded_definition(target, to_version)
    new_fields: dict[str, tuple[str | None, bool]] = {}
    if recorded is not None:
        for name, spec in (recorded.get("fields") or {}).items():
            built = _field_from_definition(spec) if isinstance(spec, Mapping) else None
            if built is not None:
                new_fields[name] = (built.db_type(connection), bool(spec.get("null")))
    elif to_version == target.declared and target.kind == NODE:
        for live_field in target.live._meta.concrete_fields:
            new_fields[live_field.name] = (live_field.db_type(connection), bool(live_field.null))
    retyped: dict[str, tuple[Any, str, bool]] = {}
    for stored in _own_fields(target):
        new_type, can_be_empty = new_fields.get(stored.name, (None, False))
        if new_type and stored.db_type(connection) != new_type:
            retyped[stored.name] = (stored, new_type, can_be_empty)
    return retyped


def _unreadable_history(history: Any, name: str, new_type: str, using: str) -> Any:
    """The history rows whose value of field ``name`` the database could not read as ``new_type``.

    ``pg_input_is_valid(value::text, type)`` asked through the ORM on the history model, so the
    table and the column are the model's own and no SQL text is put together here.
    """
    from django.db.models import BooleanField, F, Func, TextField, Value
    from django.db.models.functions import Cast

    readable = Func(
        Cast(F(name), TextField()),
        Value(new_type),
        function="pg_input_is_valid",
        output_field=BooleanField(),
    )
    return (
        history._default_manager.using(using)
        .filter(**{f"{name}__isnull": False})
        .annotate(version_migration_readable=readable)
        .filter(version_migration_readable=False)
    )


def _unconvertible(history: Any, name: str, new_type: str, using: str) -> int:
    """How many history values of field ``name`` the database could not read as ``new_type``."""
    return int(_unreadable_history(history, name, new_type, using).count())


def _discard_unconvertible(history: Any, name: str, new_type: str, using: str) -> int:
    """Empty the history values of field ``name`` the database could not read as ``new_type``."""
    return int(_unreadable_history(history, name, new_type, using).update(**{name: None}))


def _history_plan(
    target: _Target, step: version_links.Step, to_version: int, using: str, problems: list[str]
) -> list[tuple[str, str]]:
    """What must be emptied in the history table before a field's type changes (rule 27).

    Appends a problem for every field with history values that cannot be converted and are not
    declared discarded, or are declared discarded with nowhere to leave an empty value. Returns
    (field, new type) for the fields whose unconvertible values are to be emptied.
    """
    if target.history is None or connections[using].vendor != "postgresql":
        return []
    discard: list[tuple[str, str]] = []
    for name, (_stored, new_type, can_be_empty) in sorted(_retyped_fields(target, to_version, using).items()):
        count = _unconvertible(target.history, name, new_type, using)
        if not count:
            continue
        where = version_links.describe(to_version)
        if name not in step.discards_history:
            problems.append(
                f"{count} history value(s) of {target.slug}.{name} cannot be converted to {new_type}, the type the "
                f"field takes from {where}. Convert them, or declare them discarded on the step "
                f"(discards_history) where the new field can be empty, or declare a break"
            )
        elif not can_be_empty:
            problems.append(
                f"{target.slug}.{name}: the step from {where} declares history values that cannot be converted "
                "discarded, and the new field cannot be empty, so there is nowhere truthful to leave one"
            )
        elif not target.history._meta.get_field(name).null:
            problems.append(
                f"{target.slug}.{name}: {count} history value(s) are to be discarded, and the history column "
                "cannot be empty yet. Make the field nullable in an operation before this one"
            )
        else:
            discard.append((name, new_type))
    return discard


# ---------------------------------------------------------------------------
# One row
# ---------------------------------------------------------------------------


def _record(target: _Target, row: Any, fields: list[Any]) -> dict[str, Any]:
    """What a stored row asserts, in the form an export gives a step."""
    from tap_grid.grift.subgraph import json_safe

    if target.kind == EDGE:
        return dict(row.properties) if isinstance(row.properties, dict) else {}
    return {f.name: json_safe(getattr(row, f.attname)) for f in fields}


def _carry_flip(flip: Any, step: version_links.Step) -> dict[str, Any]:
    """A row's FLIP map after the step, by the step's declaration alone (rule 31).

    A kept field keeps its entry. A renamed field's entry moves to the new name. A field built
    from one old field takes that field's entry, and so does each of several built from it. A
    dropped field's entry goes with it. A new field from no old field has none.
    """
    before: dict[str, Any] = dict(flip) if isinstance(flip, dict) else {}
    after = dict(before)
    for new_name, old_name in step.renames.items():
        if old_name in before:
            after[new_name] = before[old_name]
    for new_name, old_name in step.derived.items():
        if isinstance(old_name, str) and old_name in before:
            after[new_name] = before[old_name]
    for old_name in (*step.renames.values(), *step.drops):
        after.pop(old_name, None)
    return after


def _derived_spine(target: _Target, pk: Any, entity: Any, using: str) -> dict[str, Any]:
    """The name and event time the installed class derives from the row as now stored, where they
    differ. The stored key is brought in step for the whole type afterwards, by its own catch-up."""
    from tap_grid.dimension_map import grid_derived_update, with_grid_derived
    from tap_grid.event_time import derive_for_instance

    live = target.live.all_objects.using(using).get(pk=pk)
    updates: dict[str, Any] = {}
    name = live.get_name()
    if entity.name != name:
        updates["name"] = name
    event = derive_for_instance(live)
    for column, value in event.as_columns().items():
        if getattr(entity, column) != value:
            updates[column] = value
    stored_dims = entity.dimensions or {}
    if dict(with_grid_derived(stored_dims, event.as_dimensions())) != stored_dims:
        time_update = grid_derived_update(event.as_dimensions())
        if time_update is not None:
            updates["dimensions"] = time_update
    return updates


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


def apply_version(
    apps: Any,
    schema_editor: Any,
    type_slug: str,
    *,
    to_version: int,
) -> MigrationReport:
    """Carry every stored row of ``type_slug`` from version ``to_version - 1`` to ``to_version``.

    Called from a ``RunPython`` in the migration that ships the version, after the operations
    that add the columns the step writes and before the ones that remove the columns it reads or
    change a column's type::

        def forwards(apps, schema_editor):
            apply_version(apps, schema_editor, "widget", to_version=2)

    Raises :class:`VersionMigrationRefused`, having changed nothing, where a check fails or the
    step refuses a record. Anything it raises rolls the migration back with it, and the applied
    version stays where it was.

    A type the grid holds no rows of, in a database that has never catalogued it, is left alone:
    its first registration records the version its class declares. A type already at
    ``to_version`` or beyond is left alone too, so a migration can be run again.
    """
    from tap_auth.capabilities import WRITE_CAPABILITY
    from tap_auth.enforcement import authorized
    from tap_grid import model_version
    from tap_grid.caller_context import CallerContext

    using = getattr(getattr(schema_editor, "connection", None), "alias", DEFAULT_DB_ALIAS)
    # The batch, its events and the actor are written through helpers that use the default
    # database. A migration aimed at another one would split its work across two, so it is refused.
    if using != DEFAULT_DB_ALIAS:
        raise VersionMigrationRefused(
            f"{type_slug!r} cannot be carried to version {to_version} on the database {using!r}: the "
            f"adapter works on the {DEFAULT_DB_ALIAS!r} database only."
        )
    # The rule that a failed migration leaves the applied version where it was holds only while
    # the whole migration is one transaction. In a migration that sets ``atomic = False`` the
    # adapter's own transaction would commit, and a later operation could then fail on its own.
    if schema_editor is not None and not getattr(schema_editor, "atomic_migration", True):
        raise VersionMigrationRefused(
            f"{type_slug!r} cannot be carried to version {to_version} from a migration that sets "
            "atomic = False: the rows, the applied version and the schema operations beside them must "
            "succeed or fail together. Leave the migration atomic, which is Django's default."
        )
    target = _target(apps, type_slug)
    report = MigrationReport(type_slug, to_version - 1, to_version)

    if to_version <= FIRST_VERSION or to_version > target.declared:
        raise VersionMigrationRefused(
            f"{type_slug!r} is declared at version {target.declared}; a migration cannot carry it to version {to_version}"
        )
    link = version_links.links_for(type_slug).links.get(to_version)
    where = version_links.describe(to_version)
    if isinstance(link, version_links.Break):
        raise VersionMigrationRefused(
            f"{type_slug!r}: the link from {where} is a declared break ({link.reason}). No step carries stored "
            "rows across it"
        )
    if not isinstance(link, version_links.Step):
        raise VersionMigrationRefused(f"{type_slug!r}: no step is declared from {where}")

    with transaction.atomic(using=using):
        held = _held(target, using)
        applied = _locked_applied_version(target, held, using)
        if applied is None:
            report.note = "the grid holds no rows of the type and has not catalogued it; nothing to carry"
            return report
        if applied >= to_version:
            report.note = f"the rows are already at version {applied}"
            return report
        if applied != to_version - 1:
            raise VersionMigrationRefused(
                f"{type_slug!r}: the rows are at version {applied} and this migration starts from version "
                f"{to_version - 1}. Apply the migration to version {applied + 1} first"
            )

        # Rule 33: every check before any change.
        problems: list[str] = []
        violations = _edge_violations(target, using) if link.tightens_edges else []
        problems.extend(
            f"the edge rules of {type_slug!r} from {where} would refuse {found}. Retire or correct those edges "
            "through an ordinary batch and migrate again; retirement by id is allowed while the versions disagree"
            for found in violations
        )
        discard = _history_plan(target, link, to_version, using, problems)
        if problems:
            raise VersionMigrationRefused(
                f"The migration of {type_slug!r} from {where} is refused and nothing was changed:\n  "
                + "\n  ".join(problems)
            )

        if held:
            actor = _actor()
            with authorized(CallerContext(user=actor), WRITE_CAPABILITY, operation="apply_version"):
                _carry_rows(target, link, to_version, using, actor, report)
        # History outlives the rows it describes, so a declared discard is applied whether or not
        # the type holds a live row: a value left behind would fail the column change that follows.
        for name, new_type in discard:
            report.history_discarded[name] = _discard_unconvertible(target.history, name, new_type, using)
        if report.history_discarded and report.batch_id is None:
            logger.info(
                "[5f1b] %s: history values discarded with no row changed: %s", type_slug, report.history_discarded
            )
        model_version.set_applied_version(type_slug, to_version, using=using)
        report.applied = True
        _settle_deferred_checks(schema_editor, using)
    logger.info(
        "[5f1a] %s carried from %s: %s row(s) read, %s changed, batch %s",
        type_slug,
        where,
        report.rows,
        report.changed,
        report.batch_id,
    )
    return report


def _locked_applied_version(target: _Target, held: bool, using: str) -> int | None:
    """The version applied to the type's rows, read under a lock on its catalog row.

    The lock is held to the end of the transaction, so a second migration of the same type waits
    here, and when the first commits it reads the version the first applied and does nothing. A
    step is not run twice.

    A type the grid holds rows of and has never catalogued gets its catalog row here, at version
    1: rows written before versions were recorded are at version 1, which is what its first
    registration would record. The slug is unique, so of two callers creating it one waits for
    the other, and both then lock the same row. A type with no rows and no catalog row has
    nothing to lock and nothing to carry: None.
    """
    from tap_grid.models import EntityType, EntityTypeKind

    catalog = EntityType.objects.using(using)
    if held and not catalog.filter(slug=target.slug).exists():
        catalog.get_or_create(
            slug=target.slug,
            defaults={
                "name": target.slug,
                "kind": EntityTypeKind.EDGE if target.kind == EDGE else EntityTypeKind.NODE,
                "model_version": FIRST_VERSION,
            },
        )
    locked: int | None = (
        catalog.select_for_update().filter(slug=target.slug).values_list("model_version", flat=True).first()
    )
    return locked


def _settle_deferred_checks(schema_editor: Any, using: str) -> None:
    """Run the foreign-key checks the adapter's writes deferred, now.

    PostgreSQL refuses to alter a table that has deferred checks waiting ("pending trigger
    events"), and the operations after the adapter in the same migration alter these tables: a
    column is removed, or changes type. A history row names its user and a batch event its batch,
    and both checks are deferred to the end of the transaction unless they are run here.
    """
    connection = connections[using]
    if connection.vendor != "postgresql":
        return
    # Two constant statements, with nothing put into them. Through the migration's own schema
    # editor where there is one; a caller with none (a test) has only the connection.
    if schema_editor is not None and getattr(schema_editor, "connection", None) is connection:
        schema_editor.execute(_CHECK_NOW)
        schema_editor.execute(_DEFER_AGAIN)
        return
    with connection.cursor() as cursor:
        cursor.execute(_CHECK_NOW)
        cursor.execute(_DEFER_AGAIN)


def _open_batch(target: _Target, to_version: int, actor: Any) -> Batch:
    from tap_grid.batch import create_batch

    where = version_links.describe(to_version)
    return create_batch(
        source=BATCH_SOURCE,
        actor=actor,
        name=f"Model version: {target.slug} {where}"[:200],
        description=(
            f"Grid maintenance: the stored rows of {target.slug} carried from {where} by the step its author "
            "declared. Each changed row has a new revision and a history row; this batch observed nothing and "
            "is the source of no value."
        ),
        metadata={"reason": REASON, "type": target.slug, "from_version": to_version - 1, "to_version": to_version},
    )


def _locked_rows(target: _Target, using: str) -> Any:
    """Every row of the type in key order, a page at a time, each page locked as it is read.

    Pages by key and not a server-side cursor: a cursor does not survive a savepoint that is
    rolled back around it, and a migration runs inside whatever transaction its caller opened.
    """
    last: Any = None
    while True:
        page = _queryset(target, using).select_for_update().order_by("pk")
        if last is not None:
            page = page.filter(pk__gt=last)
        rows = list(page[:CHUNK])
        if not rows:
            return
        yield from rows
        last = rows[-1].pk


def _carry_rows(
    target: _Target, step: version_links.Step, to_version: int, using: str, actor: Any, report: MigrationReport
) -> None:
    """Every row of the type through the step: retired rows with live ones (rule 30)."""
    from tap_grid.batch import close_batch, record_batch_event
    from tap_grid.models import BatchEventType, Entity
    from tap_grid.write_guard import below_pipeline_write

    fields = _own_fields(target)
    by_name = {f.name: f for f in fields}
    final = to_version == target.declared
    where = version_links.describe(to_version)
    batch: Batch | None = None
    refused: list[str] = []
    # Locked as they are read, and held to the end of the transaction: the FLIP map and the
    # properties are written back whole, and no other writer can change the row in between.
    for row in _locked_rows(target, using):
        report.rows += 1
        before = _record(target, row, fields)
        try:
            after = step.upgrade(dict(before))
        except version_links.RecordRefused as refusal:
            refused.append(f"{row.entity_id}: {refusal}")
            continue
        except Exception as failure:  # noqa: BLE001 — a step is an author's code; its failure refuses the migration
            refused.append(f"{row.entity_id}: the step failed ({type(failure).__name__[:80]})")
            continue
        if refused:
            continue
        if not isinstance(after, dict):
            refused.append(f"{row.entity_id}: the step returned a {type(after).__name__[:80]}, not a record")
            continue

        values: dict[str, Any] = {}
        changed: list[str] = []
        if target.kind == EDGE:
            if after != before:
                values["properties"] = after
                changed = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
        else:
            unknown = sorted(name for name in after if name not in by_name)
            if unknown:
                raise VersionMigrationRefused(
                    f"{target.slug!r}: the step from {where} returned {', '.join(unknown)}, which the table has "
                    "no column for at this point of the migration. Add the field in an operation before this one"
                )
            for name, value in after.items():
                if value != before.get(name):
                    values[by_name[name].attname] = by_name[name].to_python(value)
                    changed.append(name)
        flip = _carry_flip(row.flip_map, step) if target.kind == NODE else row.flip_map
        if not values and flip == row.flip_map:
            continue  # a row the step returns unchanged is not written

        if batch is None:
            batch = _open_batch(target, to_version, actor)
            report.batch_id = str(batch.entity_id)
        now = timezone.now()
        if flip != row.flip_map:
            values["flip_map"] = flip
        values["batch_id"] = report.batch_id
        target.rows._default_manager.using(using).filter(pk=row.pk).update(**values)
        for attname, value in values.items():
            setattr(row, attname, value)

        entity = Entity.objects.using(using).get(pk=row.entity_id)
        spine: dict[str, Any] = {
            "version": models.F("version") + 1,
            "updated_at": now,
            "last_changed_batch_id": batch.entity_id,
        }
        if final:
            spine.update(_derived_spine(target, row.pk, entity, using))
        with below_pipeline_write(WRITER):
            Entity.objects.using(using).filter(pk=entity.pk).update(**spine)  # TAP-WRITE-COV: version migration

        if target.history is not None:
            target.history._default_manager.using(using).create(
                **{f.attname: getattr(row, f.attname) for f in target.rows._meta.concrete_fields},
                history_date=now,
                history_type="~",
                history_user_id=getattr(actor, "pk", None),
                history_change_reason=f"model version {where}"[:100],
            )
            report.history_rows += 1
        record_batch_event(
            entity,
            BatchEventType.MAINTENANCE,
            model_name=target.live.__name__,
            actor=actor,
            metadata={
                "reason": REASON,
                "type": target.slug,
                "from_version": to_version - 1,
                "to_version": to_version,
                "fields": sorted(changed),
            },
            batch_id=report.batch_id,
        )
        report.changed += 1

    if refused:
        shown = "\n  ".join(refused[:SAMPLE])
        more = f"\n  and {len(refused) - SAMPLE} more" if len(refused) > SAMPLE else ""
        raise VersionMigrationRefused(
            f"The migration of {target.slug!r} from {where} is refused: the step refused {len(refused)} "
            f"record(s), and nothing was changed.\n  {shown}{more}"
        )
    if final and target.kind == NODE:
        # The stored key on the spine, for every row of the type, by the catch-up a migration that
        # rewrites key values is told to call (req-grid-entity-natural-key). Always, and not only
        # where a row changed: a version can change which fields make the key and leave every
        # value as it was, and the stored keys are then stale with no row written. The catch-up
        # derives from the installed class, so it runs in the migration that arrives at the
        # version that class declares.
        from tap_grid.spine_natural_key import resync_natural_keys

        resync_natural_keys(target.slug, using=using)
    if batch is not None:
        close_batch(batch)
