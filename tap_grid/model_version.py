"""Model versions: what a type declares, what this grid's rows are at, and the rule that they agree.

``req-grid-entity-model-version`` rules 1 to 4 and 6. Two numbers exist for a type, and they are
different facts:

- the **declared** version is authored: ``MODEL_VERSION`` on a model class, ``version`` beside an
  edge type's property rules. A type that states none is at version 1;
- the **applied** version is ``EntityType.model_version``: the version this grid's stored rows are
  at. It is written by the migration that moves the rows (:func:`set_applied_version`, in the
  transaction that completes the conversion) and by the first registration of a type the grid has
  never held (:func:`register_type`). Nothing else writes it, and the catalog refuses any other
  writer (``EntityType.save`` and its queryset).

A process whose start could not read the database (unreachable, or not migrated yet) owes the
comparison: it is made before that process's first write, import or export
(:func:`complete_start_checks`), and again when migrations are applied.

Registration runs when the process starts, which is before migrations run, so it never advances the
applied version: it compares. Applied greater than declared means the code is older than the data
and registration fails (:class:`ModelVersionAhead`). Declared greater than applied means the rows
are not migrated yet: the process starts, ``migrate`` runs, and every write to the type and every
import or export that carries it is refused (:class:`ModelVersionPending`) until the migration has
set the applied version.

The adapter that applies a step to stored rows (rules 29 to 33) is not here. Until it is built, a
plugin's migration converts its rows itself and calls :func:`set_applied_version` last.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, connections

logger = logging.getLogger(__name__)

#: The class attribute a model states its version in (rule 1).
MODEL_VERSION_ATTRIBUTE = "MODEL_VERSION"
#: The key an edge type states its version under, beside ``property_schema`` (rule 1).
EDGE_VERSION_KEY = "version"
#: The version of a type that states none, and of every row written before versions existed.
FIRST_VERSION = 1

NODE = "node"
EDGE = "edge"


class ModelVersionError(Exception):
    """A version that is not one, or a use of this module outside what it is for."""


class ModelVersionAhead(ModelVersionError, ImproperlyConfigured):
    """The grid's rows are at a greater version than the code declares: the code is older than the data."""

    def __init__(self, type_slug: str, declared: int, applied: int) -> None:
        self.type_slug, self.declared, self.applied = type_slug, declared, applied
        super().__init__(
            f"{type_slug!r} is declared at version {declared} and this grid's rows are at version {applied}: "
            "the installed code is older than the data it would read. Install the release that declares "
            f"version {applied} (req-grid-entity-model-version rule 4)."
        )


class ModelVersionPending(ModelVersionError):
    """The code declares a greater version than the grid's rows are at: they are not migrated yet."""

    def __init__(self, type_slug: str, declared: int, applied: int, what: str) -> None:
        self.type_slug, self.declared, self.applied = type_slug, declared, applied
        super().__init__(
            f"{type_slug!r} is declared at version {declared} and this grid's rows are at version {applied}: "
            f"{what} is refused until migrations are applied (manage.py migrate; "
            "req-grid-entity-model-version rule 4)."
        )


@dataclass(frozen=True)
class Disagreement:
    """A type whose rows are behind its code."""

    type_slug: str
    declared: int
    applied: int

    def refusal(self, what: str) -> ModelVersionPending:
        return ModelVersionPending(self.type_slug, self.declared, self.applied, what)


def checked_version(value: Any, where: str) -> int:
    """``value`` as a version, or :class:`ModelVersionError` naming ``where`` it was stated."""
    if isinstance(value, bool) or not isinstance(value, int) or value < FIRST_VERSION:
        raise ModelVersionError(f"{where} must be a whole number, {FIRST_VERSION} or greater; got {value!r}")
    return value


# ---------------------------------------------------------------------------
# The declared version
# ---------------------------------------------------------------------------

_edge_versions: dict[str, int] = {}


def declared_version(model_cls: type) -> int:
    """The version a model class declares; 1 where it states none (rule 1)."""
    return checked_version(
        getattr(model_cls, MODEL_VERSION_ATTRIBUTE, FIRST_VERSION), f"{model_cls.__name__}.{MODEL_VERSION_ATTRIBUTE}"
    )


def register_edge_version(edge_type: str, version: Any) -> None:
    """Record the version an edge type's definition states, at startup. In memory only."""
    _edge_versions[edge_type] = checked_version(version, f"edge type {edge_type!r} {EDGE_VERSION_KEY}")


def declared_edge_version(edge_type: str) -> int:
    """The version an edge type declares; 1 where its definition states none (rule 1)."""
    return _edge_versions.get(edge_type, FIRST_VERSION)


# ---------------------------------------------------------------------------
# The applied version, and who may write it
# ---------------------------------------------------------------------------

_applied_writer: contextvars.ContextVar[bool] = contextvars.ContextVar("tap_grid_applied_version_writer", default=False)


@contextlib.contextmanager
def _writing_applied_version() -> Iterator[None]:
    token = _applied_writer.set(True)
    try:
        yield
    finally:
        _applied_writer.reset(token)


def require_applied_version_writer(operation: str) -> None:
    """Refuse a write of ``EntityType.model_version`` that is not one of the two rule 3 names."""
    if not _applied_writer.get():
        raise ModelVersionError(
            f"{operation} would change EntityType.model_version. The applied version is written by the "
            "migration that moves the rows (tap_grid.model_version.set_applied_version) and by a type's "
            "first registration, and by nothing else (req-grid-entity-model-version rule 3)."
        )


def applied_version_writer_active() -> bool:
    """Whether one of the two rule 3 writers is running in this context."""
    return _applied_writer.get()


def _holds_rows(type_slug: str, kind: str, using: str) -> bool:
    """Whether the grid holds any row of the type, retired ones included."""
    from tap_grid.models import Edge, Entity

    if kind == EDGE:
        return Edge.all_objects.using(using).filter(edge_type=type_slug).exists()  # type: ignore[misc]
    return Entity.objects.using(using).filter(entity_type=type_slug).exists()


def applied_version(type_slug: str, *, using: str = DEFAULT_DB_ALIAS) -> int | None:
    """The version this grid's rows of the type are at, or None where the catalog has no row."""
    from tap_grid.models import EntityType

    return EntityType.objects.using(using).filter(slug=type_slug).values_list("model_version", flat=True).first()


def set_applied_version(type_slug: str, version: int, *, using: str = DEFAULT_DB_ALIAS) -> None:
    """Record that this grid's rows of ``type_slug`` are now at ``version``.

    The one call a migration makes once it has converted every row of the type, in the same
    transaction as the conversion: a migration that fails afterwards rolls this back with the
    rows, so the applied version stays where it was (rule 3). It refuses to run outside a
    transaction for that reason. The migration that calls it depends on
    ``("tap_grid", "0022_model_and_spine_versions")``, which adds the column.

    A type with no catalog row yet (a database migrated from nothing, where registration found
    no table at start) gets a row holding the slug and the version; registration fills in the
    rest when the process next starts.
    """
    from tap_grid.models import EntityType

    version = checked_version(version, f"the applied version of {type_slug!r}")
    if not connections[using].in_atomic_block:
        raise ModelVersionError(
            f"set_applied_version({type_slug!r}, {version}) must run inside the transaction that converts "
            "the rows, so a failed migration leaves the applied version where it was."
        )
    with _writing_applied_version():
        if not EntityType.objects.using(using).filter(slug=type_slug).update(model_version=version):
            EntityType.objects.using(using).create(slug=type_slug, name=type_slug, model_version=version)
    logger.info("[7c1e] applied version of %s set to %s", type_slug, version)


# ---------------------------------------------------------------------------
# Registration: the comparison made at start
# ---------------------------------------------------------------------------

#: Types whose rows are behind their code, as registration found them: slug -> (declared, applied).
#: Per process. A hit is confirmed against the catalog before anything is refused, so a migration
#: applied by another process is seen without a restart.
_pending: dict[str, tuple[int, int]] = {}


# ---------------------------------------------------------------------------
# A start that could not compare
# ---------------------------------------------------------------------------

#: True while this process's start-up comparison did not complete: the database was unreachable
#: or not yet migrated when the apps were made ready. The start cannot simply fail then, because
#: an image build and ``collectstatic`` run with no database at all. So the comparison is owed,
#: and it is made before the first write, import or export this process would otherwise allow.
_start_incomplete = False


def mark_start_incomplete(where: str) -> None:
    """Record that the comparison made at start was skipped at ``where``."""
    global _start_incomplete
    if not _start_incomplete:
        logger.warning(
            "[e61f] the version comparison made at start did not complete (%s): it is made before the "
            "first write, import or export instead",
            where,
        )
    _start_incomplete = True


def start_incomplete() -> bool:
    return _start_incomplete


def complete_start_checks(*, using: str = DEFAULT_DB_ALIAS) -> bool:
    """Make the comparison a start skipped, once. True when it was made.

    Reads the spine record and the whole catalog, in a savepoint so a query that fails (the
    database is still down, or still not migrated) cannot break the caller's transaction; the
    comparison then stays owed and the caller goes on. Every installed type the catalog has a
    row for is compared as :func:`register_type` would have compared it. Data ahead of the code
    raises, and the comparison stays owed so every later write raises too. It writes nothing:
    a type with no catalog row gets one when the process next starts.

    TAP-IMPLEMENTS: req-grid-entity-model-version@a6baeffebbe0/54ccffa58876 (derivation) — rule 4: a process
        whose start could not read the database does not go on to write unchecked; the
        comparison is made before its first write, import or export.
    """
    global _start_incomplete
    from django.db import DatabaseError, ProgrammingError, transaction

    from tap_grid import spine_version
    from tap_grid.constraints import list_registered_edge_types
    from tap_grid.models import EntityType
    from tap_grid.registry import get_model_class, list_entity_types

    declared: dict[str, int] = {slug: declared_edge_version(slug) for slug in list_registered_edge_types()}
    for slug in list_entity_types():
        if slug != EDGE:
            declared[slug] = declared_version(get_model_class(slug))
    try:
        with transaction.atomic(using=using):
            recorded = spine_version.recorded_version(using=using)
            catalog = dict(EntityType.objects.using(using).values_list("slug", "model_version"))
    except ProgrammingError:
        # The version table or column is not there: the database has not been migrated to it,
        # so every row it holds was written before versions existed and is at version 1. A
        # type this code declares above 1 is therefore behind, and is refused; the comparison
        # stays owed until it can be read.
        for slug in sorted(declared):
            if declared[slug] > FIRST_VERSION:
                _pending[slug] = (declared[slug], FIRST_VERSION)
        return False
    except DatabaseError:
        return False
    if recorded is not None and recorded > spine_version.SPINE_VERSION:
        raise spine_version.SpineVersionAhead(spine_version.SPINE_VERSION, recorded)
    for slug in sorted(declared):
        applied = catalog.get(slug)
        if applied is not None:
            _compare(slug, declared[slug], applied)
    _start_incomplete = False
    logger.info("[e620] the version comparison skipped at start was made: %s type(s) behind", len(_pending))
    return True


def register_type(
    type_slug: str,
    *,
    kind: str,
    declared: int,
    defaults: Mapping[str, Any],
    using: str = DEFAULT_DB_ALIAS,
) -> None:
    """Write a type's catalog row at start, and compare its declared version with the applied one.

    ``defaults`` are the descriptive columns (name, plugin, kind, history flag), stamped on every
    load. The applied version is written here only when the catalog has never had a row for the
    type: at the declared version where the grid holds no row of the type, and at 1 where it
    does, because rows written before versions were recorded are at version 1. A row that exists
    keeps its applied version whatever the class now declares (rule 3).

    Raises :class:`ModelVersionAhead` where the applied version is greater than the declared one.

    TAP-IMPLEMENTS: req-grid-entity-model-version@a6baeffebbe0/5c34838bcadb (derivation) — rules 3 and 4: the one
        place a type's declared version meets the version applied to the grid's rows. It records
        the applied version only for a type the catalog has never held, and otherwise compares.
    """
    from tap_grid.models import EntityType

    declared = checked_version(declared, f"the declared version of {type_slug!r}")
    catalog = EntityType.objects.using(using)
    applied = applied_version(type_slug, using=using)
    if applied is None:
        first = FIRST_VERSION if _holds_rows(type_slug, kind, using) else declared
        with _writing_applied_version():
            row, created = catalog.get_or_create(slug=type_slug, defaults={**defaults, "model_version": first})
        applied = row.model_version
        if not created:
            catalog.filter(slug=type_slug).update(**defaults)
    else:
        catalog.filter(slug=type_slug).update(**defaults)
    _compare(type_slug, declared, applied)


def _compare(type_slug: str, declared: int, applied: int) -> None:
    if applied > declared:
        raise ModelVersionAhead(type_slug, declared, applied)
    if applied < declared:
        _pending[type_slug] = (declared, applied)
        logger.warning(
            "[b3d0] %s is declared at version %s and this grid's rows are at version %s: writes, imports "
            "and exports of it are refused until migrations are applied",
            type_slug,
            declared,
            applied,
        )
    else:
        _pending.pop(type_slug, None)


def disagreement(type_slug: str, *, using: str = DEFAULT_DB_ALIAS) -> Disagreement | None:
    """The type's disagreement where its rows are still behind its code, else None.

    Costs nothing for a type registration found in agreement, which is every type in ordinary
    operation. For one it found behind, the catalog is read again: a migration applied since
    clears it. A database whose catalog has no row for the type records nothing to disagree with.
    """
    if _start_incomplete:
        complete_start_checks(using=using)
    held = _pending.get(type_slug)
    if held is None:
        return None
    declared = held[0]
    applied = _applied_or_unversioned(type_slug, using)
    if applied is None:
        return None
    if applied > declared:
        # Another deployment moved the rows past what this code declares. Only equality is
        # agreement: older code must not go on to write newer data (rule 4).
        raise ModelVersionAhead(type_slug, declared, applied)
    if applied == declared:
        _pending.pop(type_slug, None)
        return None
    _pending[type_slug] = (declared, applied)
    return Disagreement(type_slug, declared, applied)


def _applied_or_unversioned(type_slug: str, using: str) -> int | None:
    """The applied version, read in a savepoint; version 1 where the schema has no version column yet.

    A database not yet migrated to the version column holds rows written before versions
    existed, which are at version 1 by definition. The savepoint keeps the failed read from
    breaking the caller's transaction.
    """
    from django.db import ProgrammingError, transaction

    try:
        with transaction.atomic(using=using):
            return applied_version(type_slug, using=using)
    except ProgrammingError:
        return FIRST_VERSION


def disagreements(type_slugs: Iterable[str], *, using: str = DEFAULT_DB_ALIAS) -> list[Disagreement]:
    """Every disagreement among ``type_slugs``, in slug order."""
    if _start_incomplete:
        complete_start_checks(using=using)
    if not _pending:
        return []
    found = (disagreement(slug, using=using) for slug in sorted(set(type_slugs)))
    return [item for item in found if item is not None]


def refuse_if_pending(type_slug: str, what: str, *, using: str = DEFAULT_DB_ALIAS) -> None:
    """Raise :class:`ModelVersionPending` where ``type_slug``'s rows are behind its code."""
    if _start_incomplete:
        complete_start_checks(using=using)
    if not _pending:
        return
    found = disagreement(type_slug, using=using)
    if found is not None:
        raise found.refusal(what)


def row_type_slug(instance: Any) -> str | None:
    """The versioned type a typed row belongs to: an edge's edge type, a node's entity type."""
    entity_type: str | None = getattr(type(instance), "ENTITY_TYPE", None)
    if entity_type == EDGE:
        return getattr(instance, "edge_type", None) or None
    return entity_type


# ---------------------------------------------------------------------------
# Core's own types (rule 6)
# ---------------------------------------------------------------------------

#: What the one core row carried before core's types were catalogued: kept as it was. Icons and
#: display names for the rest belong to req-grid-entity-core-type-catalog.
_CORE_ROW_KEPT: dict[str, dict[str, str]] = {"search": {"name": "Search", "icon": "search"}}


def core_node_types() -> dict[str, type]:
    """Core's node types: every registered model a core app defines, by slug.

    A plugin's types come from its manifest and are written by its own loader. The ``edge`` model
    is not a node type: its table belongs to the spine (``req-grid-entity-spine-version``).
    """
    from django.apps import apps

    from tap_grid.registry import get_model_class, list_entity_types
    from tap_plugins.base import TapPluginConfig

    found: dict[str, type] = {}
    for type_slug in sorted(list_entity_types()):
        if type_slug == EDGE:
            continue
        model_cls = get_model_class(type_slug)
        config = apps.get_containing_app_config(model_cls.__module__)
        if config is None or isinstance(config, TapPluginConfig):
            continue
        # A model a test module defines is registered like any other; it is not one of core's.
        if model_cls.__module__ != f"{config.name}.models":
            continue
        found[type_slug] = model_cls
    return found


def core_edge_types() -> dict[str, tuple[str, dict[str, Any]]]:
    """Core's edge types: slug -> (owning app, definition), from each core app's ``edge_types``."""
    from django.apps import apps

    from tap_grid.core_edges import CORE_EDGE_DEFINITIONS
    from tap_plugins.base import TapPluginConfig

    found: dict[str, tuple[str, dict[str, Any]]] = {
        definition["slug"]: ("tap_grid", definition) for definition in CORE_EDGE_DEFINITIONS
    }
    for config in apps.get_app_configs():
        if isinstance(config, TapPluginConfig):
            continue
        for definition in getattr(config, "edge_types", None) or []:
            found[definition["slug"]] = (config.name, definition)
    return found


def register_core_types(*, using: str = DEFAULT_DB_ALIAS) -> None:
    """Give each of core's node and edge types its catalog row and compare its versions (rule 6).

    A row and a version, which is what an export needs to state the version of a type it
    carries. Icons and descriptions for core types stay with req-grid-entity-core-type-catalog.
    """
    from django.apps import apps

    from tap_grid.models import EntityTypeKind

    for type_slug, model_cls in core_node_types().items():
        config = apps.get_containing_app_config(model_cls.__module__)
        defaults: dict[str, Any] = {
            "name": getattr(model_cls, "ENTITY_NAME", type_slug),
            "plugin_name": config.name if config is not None else "",
            "kind": EntityTypeKind.NODE,
            # Stamped from the class like a manifest model (req-grid-history-optout-8).
            "track_history": getattr(model_cls, "TRACK_HISTORY", True),
        }
        defaults.update(_CORE_ROW_KEPT.get(type_slug, {}))
        register_type(type_slug, kind=NODE, declared=declared_version(model_cls), defaults=defaults, using=using)

    for type_slug, (owner, definition) in core_edge_types().items():
        declared = checked_version(
            definition.get(EDGE_VERSION_KEY, FIRST_VERSION), f"edge type {type_slug!r} {EDGE_VERSION_KEY}"
        )
        register_type(
            type_slug,
            kind=EDGE,
            declared=declared,
            defaults={
                "name": definition.get("name", type_slug),
                "plugin_name": owner,
                "kind": EntityTypeKind.EDGE,
                "track_history": True,
            },
            using=using,
        )


# ---------------------------------------------------------------------------
# What a GRIFT document carries
# ---------------------------------------------------------------------------


def _key_form_type(endpoint: Any) -> str | None:
    """The type an endpoint names when it names its entity by type and key, not by id."""
    if isinstance(endpoint, dict) and "entity_id" not in endpoint:
        entity_type = endpoint.get("entity_type")
        return entity_type if isinstance(entity_type, str) else None
    return None


def types_carried(document: Any) -> set[str]:
    """Every versioned type a GRIFT document carries or names by key.

    The batch itself, each node record's type, each edge record's edge type, and each entity a
    record or a removal names by type and key. A removal that names its target by id carries no
    type's fields and is not counted: it is the one write rule 4 lets through. Reads a document
    of any shape without raising; validation is the importer's.
    """
    carried: set[str] = set()
    batches = document.get("batches") if isinstance(document, dict) else None
    for batch in _listed(batches):
        if not isinstance(batch, dict):
            continue
        carried.add("batch")
        for node in _listed(batch.get("nodes")):
            entity = node.get("entity") if isinstance(node, dict) else None
            if isinstance(entity, dict) and isinstance(entity.get("entity_type"), str):
                carried.add(entity["entity_type"])
        for edge in _listed(batch.get("edges")):
            carried |= _edge_record_types(edge)
        deletes = batch.get("deletes")
        for target in _listed(deletes.get("edges")) if isinstance(deletes, dict) else []:
            # An edge named by identity (no id) is found through its type's key.
            if isinstance(target, dict) and "entity_id" not in target:
                carried |= _edge_record_types(target)
    return carried


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _edge_record_types(edge: Any) -> set[str]:
    if not isinstance(edge, dict):
        return set()
    found: set[str] = set()
    inner = edge.get("edge")
    data: dict[str, Any] = inner if isinstance(inner, dict) else edge
    edge_type = data.get("edge_type")
    if isinstance(edge_type, str):
        found.add(edge_type)
    # A record names an endpoint by key under from_key / to_key; an identity removal under from / to.
    for role in ("from_key", "to_key", "from", "to"):
        named = _key_form_type(data.get(role))
        if named is not None:
            found.add(named)
    return found
