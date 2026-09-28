"""The identity declaration sentinel (``req-grid-entity-natural-key``).

Every model declares how one of its rows is *found again* from a source's facts:

- ``NATURAL_KEY = ("<field>", …)`` names the constituting properties — the source's
  stable identifiers first; a name only where the source offers nothing better; never
  a dimension value, never a timestamp. The search over those fields is generated
  from the declaration (``req-grid-entity-natural-key-12``). An entry is a concrete
  column name or — when the source's identity lives inside a JSON document — a **path**
  into a ``JSONField``: ``"location.route"`` is key ``route`` of the JSON field
  ``location`` (``req-grid-entity-natural-key-14``). The path grammar, the payload
  extraction, the ORM search term and the index expression all live in THIS module, so the
  search, the index and the advisory lock read one declaration through one parser.
- ``NATURAL_KEY = KEYLESS`` (with a ``NATURAL_KEY_REASON``) says this type observes no
  source object at all — a batch, a job, a schedule fire — so there is nothing to
  correlate. Declared on purpose, and it must say why.
- ``None`` means *nobody has declared yet*. It is a guard failure, never a synonym
  for keyless: three states, not two.

Two things this module deliberately is **not**:

- It is not identity. ``Entity.id`` is always an assigned UUIDv7. A content-derived id
  cannot coexist with a terminal tombstone (the retired object returns, recomputes
  the same id, and every write addresses the tombstone), so ids are assigned and rows
  are found by lookup.
- It is not a hash. An earlier draft derived a UUIDv8 over SHA-256 of a canonical key
  document into the placeholder column on ``Entity``; that was withdrawn on 2026-09-17 —
  tombstoning forced lookup-by-facts, not hash-of-facts, and no two-key precedent
  stores a hashed non-id key. That column is now a **text placeholder**
  that nothing reads or writes until its named consumer arrives (a per-type composed,
  readable identifier for cross-type search; see the requirement).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from django.core.exceptions import FieldDoesNotExist
from django.db.models import F, JSONField
from django.db.models.fields.json import KeyTransform

if TYPE_CHECKING:
    from django.db.models import Expression, QuerySet

__all__ = [
    "KEYLESS",
    "PATH_SEPARATOR",
    "AmbiguousIdentity",
    "Keyless",
    "constituting_properties",
    "declaration_problems",
    "identity_lock_key",
    "index_expressions",
    "is_path",
    "search",
    "split_path",
]

#: Separates a JSON field's column name from the keys under it in a NATURAL_KEY entry.
#: A Django field name can never contain ``.``, so an entry with one is unambiguously a
#: path and never a column (``req-grid-entity-natural-key-14``).
PATH_SEPARATOR: Final[str] = "."


class Keyless:
    """Sentinel: this entity type observes no source object.

    Distinct from "nobody has declared a key yet". Activity and registration types —
    a batch, a collection job, an elevation, a schedule fire — record something *we*
    did; there is no external thing for a later run to recognise, so there is nothing
    for a search to find. Declaring ``NATURAL_KEY = KEYLESS`` says that on purpose,
    and requires a reason alongside it.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return "KEYLESS"


KEYLESS: Final[Keyless] = Keyless()


class AmbiguousIdentity(LookupError):
    """More than one live row matched a type's declared constituting properties.

    The search never selects (``req-grid-entity-natural-key-12``): picking the first
    match would silently merge two observations, and minting a third would silently
    fork one. Until perspectives exist, two live rows sharing declared values is a
    defect — either two rows that should be one, or a declaration too thin to tell
    two source objects apart — and it is surfaced as one, naming the candidates.
    """

    def __init__(self, entity_type: str, properties: dict[str, object], candidates: list[object]) -> None:
        self.entity_type = entity_type
        self.properties = dict(properties)
        self.candidates = list(candidates)
        shown = ", ".join(str(c) for c in self.candidates[:10])
        more = "" if len(self.candidates) <= 10 else f" (+{len(self.candidates) - 10} more)"
        super().__init__(
            f"{entity_type}: {len(self.candidates)} live rows match {self.properties!r}: {shown}{more}. "
            "A search never selects — this is two rows that should be one, or a NATURAL_KEY "
            "declaration too thin to tell two source objects apart."
        )


def is_path(name: str) -> bool:
    """True when a declared NATURAL_KEY entry names a place inside a JSON field."""
    return PATH_SEPARATOR in name


def split_path(name: str) -> tuple[str, tuple[str, ...]]:
    """Split a declared entry into (column, keys). A plain column is ``(name, ())``.

    The one grammar every consumer shares. Refused rather than guessed at: an empty segment
    (``"location."``, ``"a..b"``) and an all-digit key segment. Django's key transform reads an
    all-digit segment as an *array index* on PostgreSQL, so ``location.123`` would search a
    different place than the payload extraction reads; a JSON object keyed by digits cannot be a
    constituting property until that changes.
    """
    column, *keys = name.split(PATH_SEPARATOR)
    if not column or any(not key for key in keys):
        raise ValueError(f"NATURAL_KEY entry {name!r} has an empty segment.")
    numeric = [key for key in keys if key.isdigit()]
    if numeric:
        raise ValueError(
            f"NATURAL_KEY entry {name!r}: segment(s) {numeric} are all digits, which Django's key transform "
            "reads as an array index rather than an object key, so the search would not look where the "
            "payload extraction does."
        )
    return column, tuple(keys)


def _extract(payload: Mapping[str, object], name: str) -> object:
    """One declared entry as the payload carries it; ``None`` for anything not there.

    A missing key, an explicit JSON ``null`` and a missing or non-object parent all read as
    ``None`` — the grid's unobserved marker — because to the search they are the same thing:
    there is nothing to find by. ``""`` stays ``""`` (observed-empty), and every scalar keeps its
    JSON type: ``123`` is never ``"123"``.
    """
    column, keys = split_path(name)
    value: object = payload.get(column)
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def constituting_properties(declared: Sequence[str], payload: Mapping[str, object]) -> dict[str, object]:
    """The declared constituting values as a node payload carries them.

    An absent field is ``None`` — a hole — which ``find_existing`` answers with "not found"
    rather than a match on nothing. For a JSON path (``"location.route"``) a missing key, an
    explicit JSON ``null`` and a missing or non-object parent are that same hole, while ``""`` is a
    value like any other (Issue# 866 - tap). This is the one place a payload is read against the
    declaration, so the search and the lock (:func:`identity_lock_key`) see the same values.
    """
    return {name: _extract(payload, name) for name in declared}


def _key_transform(name: str) -> Expression:
    """The JSON value a path names, as an expression — typed (``jsonb``), never cast to text.

    Used verbatim for both the search term and the index, so PostgreSQL can match one to the
    other. ``jsonb`` equality is type-aware (``123`` is not ``"123"``); a text cast would lose
    that, which is why this is ``KeyTransform`` and not ``KeyTextTransform``.
    """
    column, keys = split_path(name)
    expression: Any = column
    for key in keys:
        expression = KeyTransform(key, expression)
    return expression  # type: ignore[no-any-return]


def index_expressions(declared: Sequence[str]) -> list[Any]:
    """The index over a declaration, one expression per entry, in declared order."""
    return [_key_transform(name) if is_path(name) else F(name) for name in declared]


def search(queryset: QuerySet[Any], properties: Mapping[str, object]) -> QuerySet[Any]:
    """Narrow ``queryset`` to rows whose declared entries equal ``properties``: the ORM half of
    the generated search. Columns filter as themselves; each path becomes an alias of the same
    expression :func:`index_expressions` puts in the index. No value here is ``None``."""
    aliases: dict[str, Expression] = {}
    lookups: dict[str, object] = {}
    for position, (name, value) in enumerate(properties.items()):
        if is_path(name):
            alias = f"_nk_path_{position}"
            aliases[alias] = _key_transform(name)
            lookups[alias] = value
        else:
            lookups[name] = value
    return queryset.alias(**aliases).filter(**lookups) if aliases else queryset.filter(**lookups)


def declaration_problems(model: Any, declared: Sequence[str], *, check_schema: bool = True) -> list[str]:
    """Everything wrong with a declared tuple against a model, as sentences; empty when sound.

    A column entry must be a concrete field. A path entry must have a concrete
    :class:`~django.db.models.JSONField` as its root and — when ``check_schema`` and the model's
    ``FIELD_VALIDATION_SCHEMA`` gives that field a JSON Schema with ``properties`` — each key must
    be one it names, level by level. A level whose schema says nothing (no ``properties``) is not a
    reason to fail. Shared by the core guard and the startup index install, so a plugin's
    declaration is held to what core's is.
    """
    problems: list[str] = []
    for name in declared:
        try:
            column, keys = split_path(name)
            field = model._meta.get_field(column)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        except FieldDoesNotExist:
            problems.append(f"{name!r}: {column!r} is not a model field")
            continue
        if not getattr(field, "concrete", False):
            problems.append(f"{name!r}: {column!r} is not a concrete column")
            continue
        if not keys:
            continue
        if not isinstance(field, JSONField):
            problems.append(f"{name!r}: {column!r} is a {type(field).__name__}, not a JSONField, so it has no keys")
            continue
        if not check_schema:
            continue
        entry = getattr(model, "FIELD_VALIDATION_SCHEMA", {}).get(column, {})
        level: Any = entry.get("schema") if entry.get("validation") == "jsonschema" else None
        for key in keys:
            properties = level.get("properties") if isinstance(level, dict) else None
            if not isinstance(properties, dict):
                break  # the schema says nothing further down; nothing to check against
            if key not in properties:
                problems.append(f"{name!r}: {key!r} is not among the schema's properties {sorted(properties)}")
                break
            level = properties[key]
    return problems


def _canonical(value: object) -> object:
    """A value in the form the JSON search treats as equal: ``jsonb`` numbers compare by value,
    so ``1.0`` and ``1`` are one identity and must be one lock key. Recursive, because a leaf may
    be an object or an array (``{"n": 1}`` equals ``{"n": 1.0}`` under ``jsonb``); object key order
    is settled by the sorted serialisation."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    return value


def identity_lock_key(entity_type: str, properties: Mapping[str, object]) -> str | None:
    """The one string two writers resolving the same source object both lock on.

    Derived from the type and the declared values, canonically serialised, so the lock key
    is a function of the declaration and never authored a second time (``req-grid-entity-
    natural-key-13``). ``None`` when any value is a hole: nothing can be found by a hole, so
    there is nothing for two writers to serialise on. A hole is ``None`` and only ``None`` — the
    test ``find_existing`` applies. ``""`` is observed-empty and IS searched (Issue# 866 - tap), so
    it must also be locked, or two writers resolving an empty-scoped object race. JSON values keep
    their type in the key (``123`` and ``"123"`` are two identities) because the search compares
    them typed.
    """
    if any(value is None for value in properties.values()):
        return None
    canonical = {name: _canonical(value) for name, value in properties.items()}
    return f"{entity_type}\x1f" + json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
