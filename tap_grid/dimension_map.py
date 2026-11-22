"""Writing an entity's dimensions map (req-grid-dimension-reference, req-grid-dimension-reference-3).

Stored shape (unified-systems-com/tap#711): ``{<dimension node uuid>: {"v": <string>, "src": <how>}}``
where ``src`` is ``declared`` (a caller passed it), ``default`` (a type's ``DEFAULT_DIMENSIONS`` or an
edge type's ``default_dimensions``) or ``derived`` (a trusted collector run computed it).

Every writer goes through :func:`stamp`, which is the whole provenance rule (#712, George 2026-11-12):

- a declaration or caller map may key by dimension name or node uuid; both resolve through the
  live vocabulary, the Dimension rows (never minted, aws-build Q48a; unified-systems-com/tap#1188);
- defaults are stamped ``src: default``, a caller's values ``src: declared``, and a caller value beats
  a default, including an empty one (#712);
- ``src: default`` is never accepted from a caller (Q48d); ``src: derived`` only inside
  ``collector_derivation_scope()`` (Q48e, Q54 D3), otherwise it is reset to ``declared``;
- a value outside a bounded dimension's ``values`` is refused (Q47), and so is an empty value unless
  the dimension declares ``empty_is_meaningful`` (Q46a, Q59 D5); both knobs are read from the live
  row, so an edit to them is enforced on the next write;
- null is never stored (Q46a);
- a dimension named in :data:`GRID_DERIVED` is written by the grid alone, ``src: derived``, from a
  fact the grid holds (the ``time`` dimension, from a model's event-time declaration,
  req-grid-entity-event-time). No caller, payload, envelope or declared default may supply it;
  :func:`settle` is the one place the stored map for a create or a replace is built with it.
"""

from __future__ import annotations

import contextvars
from collections.abc import Mapping
from typing import Any

from django.db.models import Func

from tap_grid.dimension_names import UnknownDimension, declared

TIME_DIMENSION = "time"
"""The dimension whose value says what a row's event time means (req-grid-entity-event-time)."""

GRID_DERIVED: frozenset[str] = frozenset({TIME_DIMENSION})
"""Dimension names only the grid writes. A value for one from any writer is refused."""

SRC_DECLARED = "declared"
SRC_DEFAULT = "default"
SRC_DERIVED = "derived"
SOURCES = frozenset({SRC_DECLARED, SRC_DEFAULT, SRC_DERIVED})


class DimensionWriteError(ValueError):
    """A dimension value a writer may not store."""


# Whether the running write may keep `src: derived` (req-grid-dimension-reference-6). Set only by
# `tap_grid.grift.collector_derivation_scope`, which only the collector runner enters; there is no
# parameter to pass trust in. A source-scan guard pins every reference to this variable and to the
# seal below (tap_grid/tests/test_dimension_migration.py::TestTheTrustHatchHasOneCaller).
_DERIVATION_TRUSTED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "dimension_derivation_trusted", default=False
)

# Only maps this module builds carry it, so a settled map cannot be forged by building the class.
_SEAL = object()


class StampedDimensions(dict[str, dict[str, str]]):
    """A map already in stored shape, with provenance settled by this module.

    Writers below the entry points (the model save, the service pipeline) take a sealed one as is, so
    a decision made at the entry point (the importer, a type's defaults) is not re-made. One built
    anywhere else is unsealed and is re-judged as an untrusted caller map: a forged `src: derived`
    becomes declared and a forged `src: default` is refused (PR# 1196 - tap review).
    """

    # Slotted, so no attribute can be added; the seal slot holds this module's private sentinel only
    # when this module built the map, and `sealed` is a read-only view of it (PR# 1196 - tap review).
    __slots__ = ("_seal",)

    def __init__(self, *args: Any, _seal: object = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._seal = _seal

    @property
    def sealed(self) -> bool:
        return self._seal is _SEAL


def _sealed(entries: Mapping[str, dict[str, str]] | None = None) -> StampedDimensions:
    return StampedDimensions(dict(entries or {}), _seal=_SEAL)


def _refuse_meaningless_empty(found: Any, value: str, where: str) -> None:
    """An empty value is observed-empty only where the dimension declares it means something
    (``empty_is_meaningful``, aws-build Q46a / Q59 D5); everywhere else it is refused."""
    if value == "" and not getattr(found, "empty_is_meaningful", False):
        raise DimensionWriteError(
            f"{where}: an empty value for {found.name!r} is refused: the dimension does not declare empty as meaningful"
        )


def _refuse_grid_derived(found: Any, where: str) -> None:
    """A dimension the grid derives is never a writer's to set, change or remove."""
    if found.name in GRID_DERIVED:
        raise DimensionWriteError(
            f"{where}: dimension {found.name!r} is written by the grid only, derived from the type's "
            "declaration; it is not accepted from a writer"
        )


def _entry(
    name_or_id: str, value: Any, *, trusted: bool, where: str, by_grid: bool = False
) -> tuple[str, dict[str, str]]:
    found = declared(name_or_id)
    if not by_grid:
        _refuse_grid_derived(found, where)
    src = SRC_DECLARED
    if isinstance(value, Mapping):
        if set(value) - {"v", "src"}:
            raise DimensionWriteError(f"{where}: a dimension value object holds only 'v' and 'src'")
        src = value.get("src", SRC_DECLARED)
        value = value.get("v")
        if src not in SOURCES:
            raise DimensionWriteError(f"{where}: src must be one of {sorted(SOURCES)}, got {src!r}")
        if src == SRC_DEFAULT:
            raise DimensionWriteError(
                f"{where}: src 'default' is stamped by the grid from a type's declared defaults, never accepted from a writer"
            )
        if src == SRC_DERIVED and not trusted:
            src = SRC_DECLARED
    if not isinstance(value, str):
        raise DimensionWriteError(f"{where}: dimension {found.name!r} needs a string value, got {type(value).__name__}")
    _refuse_meaningless_empty(found, value, where)
    if not found.accepts(value):
        raise DimensionWriteError(
            f"{where}: {value!r} is not an allowed value of the bounded dimension {found.name!r} ({list(found.values or ())})"
        )
    return found.id, {"v": value, "src": src}


def supplied(raw: Mapping[str, Any] | None, *, where: str = "dimensions") -> StampedDimensions:
    """A writer's map in stored shape, with its provenance settled.

    Keys are names or uuids. A value is a string or ``{"v": …, "src": …}``. A null value is not a
    value: it is dropped here, and only :func:`patch` reads it as a removal (Q46b).
    """
    if isinstance(raw, StampedDimensions) and raw.sealed:
        return raw
    trusted = _DERIVATION_TRUSTED.get()
    out = _sealed()
    for key, value in (raw or {}).items():
        if value is None:
            continue
        if not isinstance(key, str):
            raise DimensionWriteError(f"{where}: dimension keys are names or node ids, got {key!r}")
        dim_id, entry = _entry(key, value, trusted=trusted, where=where)
        out[dim_id] = entry
    return out


def defaults(declared_defaults: Mapping[str, str] | None) -> StampedDimensions:
    """A type's declared defaults in stored shape, each ``src: default``."""
    out = _sealed()
    for key, value in (declared_defaults or {}).items():
        found = declared(key)
        _refuse_grid_derived(found, "default dimensions")
        _refuse_meaningless_empty(found, value, "default dimensions")
        if not found.accepts(value):
            raise DimensionWriteError(
                f"default dimensions: {value!r} is not an allowed value of the bounded dimension {found.name!r}"
            )
        out[found.id] = {"v": value, "src": SRC_DEFAULT}
    return out


def stamp(
    declared_defaults: Mapping[str, str] | None,
    caller: Mapping[str, Any] | None,
    *,
    where: str = "dimensions",
) -> StampedDimensions:
    """The stored map for a create or a replace: the type's defaults, then the caller's values over
    them. The caller wins on a conflict, even with an empty value (#712)."""
    out = defaults(declared_defaults)
    out.update(supplied(caller, where=where))
    return out


def patch(stored: Mapping[str, Any] | None, changes: Mapping[str, Any]) -> StampedDimensions:
    """Apply a patch (Q46b): an omitted key is unchanged, a key set to null is removed, any other key
    is set with its provenance settled as :func:`supplied` settles it."""
    trusted = _DERIVATION_TRUSTED.get()
    out = _sealed(stored)
    for key, value in changes.items():
        if value is None:
            found = declared(key)
            _refuse_grid_derived(found, "dimensions patch")
            out.pop(found.id, None)
        else:
            dim_id, entry = _entry(key, value, trusted=trusted, where="dimensions patch")
            out[dim_id] = entry
    return out


def rederive(stored: Mapping[str, Any] | None, derived_values: Mapping[str, str]) -> StampedDimensions:
    """Write derived values (Q46c): a derived value replaces an absent or derived one, and never a
    declared or default one."""
    out = _sealed(stored)
    for key, value in derived_values.items():
        dim_id, entry = _entry(key, {"v": value, "src": SRC_DERIVED}, trusted=True, where="re-derivation")
        current = out.get(dim_id)
        if current is None or (isinstance(current, Mapping) and current.get("src") == SRC_DERIVED):
            out[dim_id] = entry
    return out


def grid_derived_ids() -> frozenset[str]:
    """The node ids of the grid-derived dimensions this grid declares. One not declared here
    (a grid whose core vocabulary has not been imported yet) has no id and is left out."""
    ids = set()
    for name in GRID_DERIVED:
        try:
            ids.add(declared(name).id)
        except UnknownDimension:
            continue
    return frozenset(ids)


def with_grid_derived(stored: Mapping[str, Any] | None, values: Mapping[str, str | None]) -> StampedDimensions:
    """A stored map with the grid's own derived values set: a string sets the entry
    (``src: derived``), ``None`` removes it. Only names in :data:`GRID_DERIVED` are taken.

    A grid-derived dimension this grid does not declare yet is skipped, not an error: the value
    is the grid's own, and the pass that re-derives it fills it in once the vocabulary lands.
    """
    out = _sealed(stored)
    for name, value in values.items():
        if name not in GRID_DERIVED:
            raise DimensionWriteError(f"{name!r} is not a dimension the grid derives")
        try:
            if value is None:
                out.pop(declared(name).id, None)
            else:
                entry_value = {"v": value, "src": SRC_DERIVED}
                dim_id, entry = _entry(name, entry_value, trusted=True, where="grid derivation", by_grid=True)
                out[dim_id] = entry
        except UnknownDimension:
            continue
    return out


class GridDerivedUpdate(Func):
    """A database expression that sets or removes grid-derived entries of ``dimensions`` and
    touches no other key: ``dimensions || {<id>: entry}`` to set, ``dimensions - <id>`` to remove.

    Built only by :func:`grid_derived_update`. Writing the key in the database, not a whole map
    computed in memory, means a writer cannot overwrite a dimension another writer changed since
    the row was read, and a write guard can admit this type and refuse any other value.
    """

    def __init__(self, *expressions: Any, seal: object = None, **extra: Any) -> None:
        if seal is not _SEAL:
            raise DimensionWriteError("a grid-derived update is built by dimension_map.grid_derived_update only")
        super().__init__(*expressions, **extra)


def grid_derived_update(values: Mapping[str, str | None]) -> GridDerivedUpdate | None:
    """The expression that applies the grid's derived values to a row's stored ``dimensions``: a
    string sets the entry (``src: derived``, the value checked against the dimension), ``None``
    removes it. None when this grid declares none of the named dimensions yet."""
    from django.db.models import F, JSONField, TextField, Value
    from django.db.models.functions import Cast

    expression: Any = F("dimensions")
    built: GridDerivedUpdate | None = None
    for name, value in values.items():
        if name not in GRID_DERIVED:
            raise DimensionWriteError(f"{name!r} is not a dimension the grid derives")
        try:
            if value is None:
                operand: Any = Cast(Value(declared(name).id), TextField())
                joiner = " - "
            else:
                entry_value = {"v": value, "src": SRC_DERIVED}
                dim_id, entry = _entry(name, entry_value, trusted=True, where="grid derivation", by_grid=True)
                operand = Value({dim_id: entry}, output_field=JSONField())
                joiner = " || "
        except UnknownDimension:
            continue
        built = GridDerivedUpdate(
            expression, operand, template="(%(expressions)s)", arg_joiner=joiner, output_field=JSONField(), seal=_SEAL
        )
        expression = built
    return built


def settle(
    declared_defaults: Mapping[str, str] | None,
    caller: Mapping[str, Any] | None,
    *,
    grid: Mapping[str, str | None] | None = None,
    persisted: Mapping[str, Any] | None = None,
    where: str = "dimensions",
) -> StampedDimensions:
    """The stored map a create or a replace settles on, built in this one place: the type's
    defaults, the caller's values over them (:func:`stamp`), then the grid's own derived values.

    ``grid`` gives the derived values where the writer has the row to derive them from (a create,
    a save). ``persisted`` is for a writer that has only the stored row (the import's comparison
    of an envelope with the spine, and the post-pass that writes what it found): the row's
    grid-derived entries are carried over as they stand, because the save in the same operation
    is what keeps them current. Without this, a map built from defaults and an envelope would
    never equal a stored map that holds a grid-derived entry, and every re-import would read as
    a change (req-grid-history-reobservation).
    """
    out = stamp(declared_defaults, caller, where=where)
    if grid is not None:
        return with_grid_derived(out, grid)
    if persisted:
        for dim_id in grid_derived_ids():
            entry = persisted.get(dim_id)
            if isinstance(entry, Mapping):
                out[dim_id] = {"v": entry["v"], "src": entry["src"]}
    return out


def without_grid_derived(stored: Mapping[str, Any] | None) -> dict[str, Any]:
    """A stored map with the grid-derived entries left out: what a document carries, since the
    receiving grid derives them itself and refuses them from a writer."""
    skip = grid_derived_ids()
    return {key: value for key, value in (stored or {}).items() if key not in skip}


def refuse_unstored_shape(stored: Any, *, where: str = "dimensions") -> None:
    """Refuse a map that is not the stored shape (req-grid-dimension-reference-1): every key a
    Dimension node id, every value exactly ``{"v": <string>, "src": declared|default|derived}``.
    The structural backstop under every writer: ``Entity.save`` calls it, so a direct ORM write of a
    name-keyed or malformed map fails instead of landing.

    A key may name a retired Dimension node: this checks shape, not resolution. A row stamped before
    its dimension was retired stays writable (a later edit to any other field saves the whole map);
    a writer cannot newly set a retired dimension, because every new value resolves live first."""
    from tap_grid.live_dimensions import vocabulary

    if not isinstance(stored, Mapping):
        raise DimensionWriteError(f"{where}: dimensions must be a map, got {type(stored).__name__}")
    if not stored:
        return
    table = vocabulary()
    for key, entry in stored.items():
        if key not in table.known_ids:
            raise DimensionWriteError(f"{where}: dimension key {key!r} is not a Dimension node id")
        if not (
            isinstance(entry, Mapping)
            and set(entry) == {"v", "src"}
            and isinstance(entry["v"], str)
            and entry["src"] in SOURCES
        ):
            raise DimensionWriteError(
                f'{where}: dimension {key!r} must be {{"v": <string>, "src": declared|default|derived}}, got {entry!r}'
            )
