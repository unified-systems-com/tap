"""The dimension vocabulary, read from live Dimension rows (req-grid-dimension-reference-9).

A dimension name resolves to the uuid of the one **live** Dimension node carrying it, and every
write-time knob (``values``, ``empty_is_meaningful``, ``usable_in_keys``) is read from that row
(ruled 2026-11-13, unified-systems-com/tap#1188). Boot imports core's and every installed plugin's
dimension bundle before anything else writes (``req-boot-phases-5``), so the rows exist before any
name needs them. A retired (tombstoned) node stops resolving, and an edit to a row's knobs is
enforced on the next write. Nothing is ever minted: a name with no live node is unknown.

**Cost.** The vocabulary is a few dozen rows, held per process as one table. Each use checks the
table is still current with one aggregate over the dimension spine rows (count, version sum, latest
update), so a node written or retired by another process is seen; a mismatch reloads the table in
one more query. Inside a :func:`scope` (an HTTP request, a GRIFT import, a ``write_batch``) that
check runs once, on first use, so a write loop over thousands of rows pays one query, not one per
dimension per row. A Dimension node written or retired in this process clears the table at once
(:func:`invalidate`, wired to the model signals and to the tombstone path), so the next use inside
the same scope reloads it, and sees the write even before it commits.

**A GRIFT document's own declarations.** A document that declares Dimension nodes may use them in
the same import: core's seed stamps ``tap.meta`` on the very node that declares ``tap.meta``. The
importer passes those declarations through :func:`declaring`; inside it they resolve over the live
table, by id, before their rows exist, and the rows land in the same transaction.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

CORE_SEED = Path(__file__).resolve().parent / "data" / "dimensions.grift.json"
"""Core's own dimension bundle, imported first by boot (``req-grid-dimension-core-vocabulary-2``)."""


class InvalidDimensionKnob(ValidationError):
    """A Dimension node's knob has the wrong type. Refused when the node is written (and when a row
    that bypassed that check is loaded), so a malformed knob never reads as open or true."""


class DuplicateDimensionName(ValidationError):
    """A Dimension node takes a name another live Dimension node already carries. Refused when the
    node is written: a name must mean one dimension, or a name lookup and the name-keyed view pick
    one silently."""


@dataclass(frozen=True)
class LiveDimension:
    """One live Dimension node: its id, its name and its knobs."""

    id: str
    name: str
    values: tuple[str, ...] | None
    usable_in_keys: bool
    empty_is_meaningful: bool = False

    def accepts(self, value: str) -> bool:
        """Any string for an open dimension; a listed one for a bounded dimension (Q47)."""
        return self.values is None or value in self.values


@dataclass(frozen=True)
class Vocabulary:
    """The live dimensions by id and by name, and every Dimension node id the grid holds."""

    by_id: Mapping[str, LiveDimension]
    by_name: Mapping[str, tuple[str, ...]]  # name -> every live id carrying it (more than one is ambiguous)
    known_ids: frozenset[str] = frozenset()  # live and retired: what a stored map may still carry

    @classmethod
    def of(cls, live: Iterable[LiveDimension], retired_ids: Iterable[str] = ()) -> Vocabulary:
        by_id = {d.id: d for d in live}
        names: dict[str, list[str]] = {}
        for ident, found in by_id.items():
            names.setdefault(found.name, []).append(ident)
        return cls(
            by_id=by_id,
            by_name={name: tuple(sorted(ids)) for name, ids in names.items()},
            known_ids=frozenset(by_id) | frozenset(retired_ids),
        )


def knob_problems(name: str, values: Any, usable_in_keys: Any, empty_is_meaningful: Any) -> list[str]:
    """Why a Dimension node's knobs are malformed, one message per knob; empty when they are sound."""
    problems: list[str] = []
    if values is not None and not (
        isinstance(values, list | tuple)
        and all(isinstance(v, str) and v for v in values)
        and len(set(values)) == len(values)
    ):
        problems.append(f"{name!r} knob 'values' must be a list of unique non-empty strings or null, got {values!r}")
    for knob, raw in (("usable_in_keys", usable_in_keys), ("empty_is_meaningful", empty_is_meaningful)):
        if not isinstance(raw, bool):
            problems.append(f"{name!r} knob {knob!r} must be true or false, got {raw!r}")
    return problems


def _live_dimension(ident: str, name: str, values: Any, usable_in_keys: Any, empty_is_meaningful: Any) -> LiveDimension:
    problems = knob_problems(name, values, usable_in_keys, empty_is_meaningful)
    if problems:
        raise InvalidDimensionKnob(f"InvalidDimensionKnob: Dimension node {ident}: " + "; ".join(problems))
    return LiveDimension(
        id=ident,
        name=name,
        values=tuple(values) if values is not None else None,
        usable_in_keys=usable_in_keys,
        empty_is_meaningful=empty_is_meaningful,
    )


# --- the per-process table ------------------------------------------------------------------------

_lock = threading.Lock()
_cache: tuple[tuple[Any, ...], Vocabulary] | None = None  # (fingerprint, table)
_pinned: Vocabulary | None = None  # a test's fixed table: no database at all


@dataclass
class _Scope:
    table: Vocabulary | None = None


_scope: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar("live_dimensions_scope", default=None)


@dataclass
class _Declared:
    entries: Mapping[str, LiveDimension]
    merged: tuple[Vocabulary, Vocabulary] | None = None  # memo: (base table, merged table)


_declared: contextvars.ContextVar[_Declared | None] = contextvars.ContextVar("live_dimensions_declared", default=None)


def _fingerprint() -> tuple[Any, ...]:
    """One aggregate over the dimension spine rows. Any create, edit, retirement or purge through
    the grid changes it: a create or purge the count, every service mutation the version sum, and
    a retirement both the version and the latest update."""
    from django.db.models import Count, Max, Sum

    from tap_grid.gryphon.capture import uncaptured
    from tap_grid.models import Dimension, Entity
    from tap_grid.read_guard import unguarded_read

    # The grid reading its own vocabulary to judge a write is internal maintenance: a writer that may
    # write a node but not read the grid must still have its dimensions judged. Not a query's plan
    # either, so a Gryphon SQL capture leaves it out (it runs or not by cache warmth).
    with unguarded_read(), uncaptured():
        row = Entity.objects.filter(entity_type=Dimension.ENTITY_TYPE).aggregate(
            n=Count("id"), v=Sum("version"), u=Max("updated_at")
        )
    return (row["n"], row["v"], row["u"])


def _load() -> Vocabulary:
    from tap_grid.gryphon.capture import uncaptured
    from tap_grid.models import Dimension
    from tap_grid.read_guard import unguarded_read

    live: list[LiveDimension] = []
    retired: list[str] = []
    with unguarded_read(), uncaptured():
        rows = Dimension.all_objects.values_list(
            "entity_id", "name", "values", "usable_in_keys", "empty_is_meaningful", "entity__deleted_at"
        )
        for entity_id, name, values, usable_in_keys, empty_is_meaningful, deleted_at in rows:
            ident = str(entity_id)
            if deleted_at is not None:
                retired.append(ident)
                continue
            live.append(_live_dimension(ident, name, values, usable_in_keys, empty_is_meaningful))
    return Vocabulary.of(live, retired)


def _live() -> Vocabulary:
    global _cache
    if _pinned is not None:
        return _pinned
    current = _scope.get()
    if current is not None and current.table is not None:
        return current.table
    fingerprint = _fingerprint()
    cached = _cache
    if cached is None or cached[0] != fingerprint:
        with _lock:
            cached = (fingerprint, _load())
            _cache = cached
    if current is not None:
        current.table = cached[1]
    return cached[1]


def vocabulary() -> Vocabulary:
    """The live vocabulary, with any declarations the running GRIFT import makes laid over it."""
    base = _live()
    pending = _declared.get()
    if pending is None or not pending.entries:
        return base
    if pending.merged is not None and pending.merged[0] is base:
        return pending.merged[1]
    live = {**base.by_id, **pending.entries}
    merged = Vocabulary.of(live.values(), base.known_ids - set(live))
    pending.merged = (base, merged)
    return merged


def invalidate(*_args: Any, **_kwargs: Any) -> None:
    """Forget the table: a Dimension node was written or retired in this process. The next use
    reloads it, inside the running scope too. Signal-receiver shaped."""
    global _cache
    with _lock:
        _cache = None
    current = _scope.get()
    if current is not None:
        current.table = None


def invalidate_entity(sender: Any, instance: Any, **_kwargs: Any) -> None:
    """``Entity`` signal receiver: invalidate when the row is a Dimension node's spine."""
    if getattr(instance, "entity_type", None) == "dimension":
        invalidate()


@contextlib.contextmanager
def scope() -> Iterator[None]:
    """Check the table is current once, on first use, for the whole block. Nested scopes share the
    outermost one. Writes in this process still invalidate it immediately."""
    if _scope.get() is not None:
        yield
        return
    token = _scope.set(_Scope())
    try:
        yield
    finally:
        _scope.reset(token)


@contextlib.contextmanager
def declaring(entries: Mapping[str, LiveDimension]) -> Iterator[None]:
    """Resolve ``entries`` (by id, over the live table) for the block: a GRIFT document's own
    Dimension declarations, usable in the import that writes them."""
    token = _declared.set(_Declared(entries=dict(entries)))
    try:
        yield
    finally:
        _declared.reset(token)


def declared_in(document: Any, *, skip_batches: Iterable[str] = ()) -> dict[str, LiveDimension]:
    """The Dimension nodes a GRIFT document declares, by id, from every batch not in
    ``skip_batches`` (a batch already imported declares nothing new: its rows are on the grid, or
    were retired since, and retired stays retired). A node without a valid id or name, or with a
    malformed knob, is left out here; the importer refuses it with its own issue."""
    found: dict[str, LiveDimension] = {}
    if not isinstance(document, Mapping):
        return found
    skipped = set(skip_batches)
    for batch in document.get("batches") or []:
        if not isinstance(batch, Mapping):
            continue
        batch_entity = batch.get("batch_entity") or {}
        batch_id = str(batch_entity.get("entity_id") or "") if isinstance(batch_entity, Mapping) else ""
        try:
            batch_id = str(uuid.UUID(batch_id))
        except ValueError:
            pass
        if batch_id in skipped:
            continue
        for node in batch.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            entity = node.get("entity") or {}
            payload = node.get("node") or {}
            if not isinstance(entity, Mapping) or not isinstance(payload, Mapping):
                continue
            if entity.get("entity_type") != "dimension" or node.get("retirement"):
                continue
            try:
                ident = str(uuid.UUID(str(entity.get("entity_id"))))
            except ValueError:
                continue
            name = payload.get("name") or entity.get("name")
            if not isinstance(name, str) or not name:
                continue
            values = payload.get("values")
            usable = payload.get("usable_in_keys", False)
            empty = payload.get("empty_is_meaningful", False)
            if knob_problems(name, values, usable, empty):
                continue
            found[ident] = LiveDimension(
                id=ident,
                name=name,
                values=tuple(values) if values is not None else None,
                usable_in_keys=usable,
                empty_is_meaningful=empty,
            )
    return found


def pin(table: Vocabulary | None) -> None:
    """Fix the vocabulary to ``table`` (no database), or unpin with ``None``. For tests only."""
    global _pinned
    with _lock:
        _pinned = table
