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

The path grammar (:func:`split_path`) imports nothing from Django, and Django is imported only
inside the functions that build ORM expressions, so a Django-free caller (plugin conformance
validation) can share the one grammar rather than keep a second copy.

Two things this module deliberately is **not**:

- It is not identity. ``Entity.id`` is always an assigned UUIDv7. A content-derived id
  cannot coexist with a terminal tombstone (the retired object returns, recomputes
  the same id, and every write addresses the tombstone), so ids are assigned and rows
  are found by lookup.
- It is not a hash. An earlier draft derived a UUIDv8 over SHA-256 of a canonical key
  document into the spine column on ``Entity``; that was withdrawn on 2026-09-17 —
  tombstoning forced lookup-by-facts, not hash-of-facts, and no two-key precedent
  stores a hashed non-id key.

Instead the spine stores each keyed row's natural key in a readable standard form
(:func:`compose_natural_key`, ``req-grid-entity-natural-key-19``): a single-field key's value
verbatim (an ARN, bare), a multi-field key's values joined in declared order with
:data:`KEY_SEPARATOR`. The values are field-coerced first, and the identity lock key is the same
string behind the type, so the lock and the stored key cannot drift. The stored key is output
only: the search reads the declared columns, never it.
"""

from __future__ import annotations

import datetime
import decimal
import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from django.db.models import Expression, QuerySet

__all__ = [
    "COMPOSITION_VERSION",
    "KEYLESS",
    "KEY_ESCAPE",
    "KEY_SEPARATOR",
    "PATH_SEPARATOR",
    "PREFIX_INDEX_CHARS",
    "AmbiguousIdentity",
    "Keyless",
    "compose_natural_key",
    "constituting_properties",
    "declared_columns",
    "declaration_problems",
    "encode_key_part",
    "identity_lock_key",
    "index_expressions",
    "is_path",
    "natural_key_prefix",
    "recipe_fingerprint",
    "row_natural_key",
    "search",
    "split_key",
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
    from django.db.models.fields.json import KeyTransform

    column, keys = split_path(name)
    expression: Any = column
    for key in keys:
        expression = KeyTransform(key, expression)
    return expression  # type: ignore[no-any-return]


def index_expressions(declared: Sequence[str]) -> list[Any]:
    """The index over a declaration, one expression per entry, in declared order."""
    from django.db.models import F

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
    from django.core.exceptions import FieldDoesNotExist
    from django.db.models import JSONField

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


#: Joins a multi-field key's values, in declared order (``req-grid-entity-natural-key-19``).
#: Ruled 2026-11-11 by George (Issue# 1178 - tap).
KEY_SEPARATOR: Final[str] = "|"

#: Escapes the separator, and itself, inside a multi-field key's values, percent-style:
#: ``%`` → ``%25`` and ``|`` → ``%7C``, so the join splits back exactly. Nothing else is
#: escaped, so an IPv6 address or a path stays readable (``corp|fe80::1|tcp|443``).
KEY_ESCAPE: Final[str] = "%"


def _escaped(char: str) -> str:
    return f"{KEY_ESCAPE}{ord(char):02X}"


def encode_key_part(text: str) -> str:
    """One value of a multi-field key, with the escape and the separator escaped (escape first)."""
    return text.replace(KEY_ESCAPE, _escaped(KEY_ESCAPE)).replace(KEY_SEPARATOR, _escaped(KEY_SEPARATOR))


def split_key(value: str) -> list[str]:
    """A multi-field key back into its values, as text, in declared order (the exact round trip)."""
    codes = {_escaped(KEY_ESCAPE): KEY_ESCAPE, _escaped(KEY_SEPARATOR): KEY_SEPARATOR}
    pattern = "|".join(re.escape(code) for code in codes)
    return [re.sub(pattern, lambda match: codes[match.group(0)], part) for part in value.split(KEY_SEPARATOR)]


def _json_text(value: object) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _scalar_text(value: object) -> str:
    """A field-coerced column value as key text — the pinned stringification (``-19``).

    Strings verbatim (an IP address arrives here already in ``GenericIPAddressField.to_python``'s
    canonical form); ``true``/``false``; integers canonical, an integral float as its integer
    (``1.0`` is ``1``); a ``Decimal`` normalised and never in exponent form (``1.50`` is ``1.5``,
    ``1E+2`` is ``100``); a UUID lower-case hyphenated; an aware datetime as ISO-8601 in UTC
    (``2026-11-11T05:00:00+00:00``), a naive one as ISO-8601 read as UTC; a date as ISO-8601; an
    object or array as compact sorted JSON; anything else by ``str()``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(_canonical(value))
    if isinstance(value, decimal.Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, uuid.UUID):
        return str(value).lower()
    if isinstance(value, datetime.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)
        return aware.astimezone(datetime.UTC).isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Mapping | list | tuple):
        return _json_text(value)
    return str(value)


def _coerced_text(model: Any, name: str, value: object) -> str | None:
    """One declared entry's value as key text, from the FIELD-COERCED value, never the raw payload.

    A column entry goes through its model field's ``to_python``, so ``"443"`` and ``443`` on an
    integer column, or two spellings of one IPv6 address on an address column, give one key. A
    value the field cannot coerce stays as given (the write's own validation refuses it). A JSON
    entry — a path into a JSON field, or a whole JSON column — keeps its JSON type, rendered as
    compact sorted JSON, because the search compares it typed: ``123`` and ``"123"`` are two
    identities there, so they must be two keys (``req-grid-entity-natural-key-15``). ``None`` when
    the coerced value is a hole (an integer column given ``""`` coerces to ``None``).
    """
    column, keys = split_path(name)
    field = None
    if model is not None:
        from django.core.exceptions import FieldDoesNotExist

        try:
            field = model._meta.get_field(column)
        except FieldDoesNotExist:
            field = None
    if keys or (field is not None and field.get_internal_type() == "JSONField"):
        return _json_text(value)
    if field is not None:
        from django.core.exceptions import ValidationError

        try:
            value = field.to_python(value)
        except ValidationError:
            pass
        if value is None:
            return None
    return _scalar_text(value)


def compose_natural_key(model: Any, properties: Mapping[str, object]) -> str | None:
    """THE natural key: the one function behind the spine key and the identity lock key.

    ``properties`` maps each declared entry to its value in declared order — what
    :func:`constituting_properties` returns for a payload, or a row read through the same grammar.
    A single-field key is its value verbatim (a type keyed on its ARN stores the ARN, bare). A
    multi-field key joins its values in declared order with :data:`KEY_SEPARATOR`, each escaped by
    :func:`encode_key_part`. ``None`` when any value is a hole — before or after coercion — never a
    partial key (null = not observed); ``""`` is a value. ``model`` supplies the fields that coerce
    each value; ``None`` (an unregistered type) coerces nothing.
    """
    if any(value is None for value in properties.values()):
        return None
    texts = [_coerced_text(model, name, value) for name, value in properties.items()]
    if any(text is None for text in texts):
        return None
    parts = [text for text in texts if text is not None]
    if len(parts) == 1:
        return parts[0]
    return KEY_SEPARATOR.join(encode_key_part(part) for part in parts)


def row_natural_key(model: Any, row: Mapping[str, object]) -> str | None:
    """:func:`compose_natural_key` for a row: ``row`` maps each declared column to its value (a JSON
    column as its decoded document). ``None`` for a type not keyed by a tuple."""
    declared = getattr(model, "NATURAL_KEY", None)
    if not isinstance(declared, tuple):
        return None
    return compose_natural_key(model, constituting_properties(declared, row))


def identity_lock_key(entity_type: str, properties: Mapping[str, object]) -> str | None:
    """The one string two writers resolving the same source object both lock on: the type, a unit
    separator, and the natural key the row will store (:func:`compose_natural_key`), so the lock and
    the stored key cannot drift (``req-grid-entity-natural-key-13``, ``-19``).

    Computed before the row exists, from the payload's declared values coerced through the
    registered model's fields. ``None`` when any value is a hole: nothing can be found by a hole, so
    there is nothing for two writers to serialise on. ``""`` is observed-empty and IS searched
    (Issue# 866 - tap), so it is locked too. JSON values keep their type in the key (``123`` and
    ``"123"`` are two identities) because the search compares them typed.
    """
    model = None
    try:
        from tap_grid.registry import get_model_class

        model = get_model_class(entity_type)
    except KeyError, ImportError:
        model = None
    # A function of the values, not of the mapping's order: the type's declared order when the
    # entries are its declaration (what constituting_properties returns), else sorted by name.
    declared = getattr(model, "NATURAL_KEY", None)
    if isinstance(declared, tuple) and set(declared) == set(properties):
        order = list(declared)
    else:
        order = sorted(properties)
    key = compose_natural_key(model, {name: properties[name] for name in order})
    return None if key is None else f"{entity_type}\x1f{key}"


def natural_key_prefix(model: Any, leading: Mapping[str, object]) -> str:
    """The prefix that finds every row of a multi-field type whose LEADING declared values are these.

    ``leading`` names the first k declared entries (k fewer than all), composed exactly as
    :func:`compose_natural_key` composes them — coerced, escaped, joined — and ends with the
    separator, so ``corp|10.0.1.5|`` matches ``corp|10.0.1.5|tcp|443`` and never
    ``corp|10.0.1.50|…`` (``req-grid-entity-natural-key-24``). Refuses a single-field type, entries
    that are not a leading run of the declaration, and a hole.
    """
    declared = getattr(model, "NATURAL_KEY", None)
    if not isinstance(declared, tuple) or len(declared) < 2:
        raise ValueError("a prefix of leading values needs a type keyed on two or more entries")
    names = list(leading)
    if not names or names != list(declared[: len(names)]) or len(names) == len(declared):
        raise ValueError(f"{names} is not a leading run (fewer than all) of NATURAL_KEY {declared}")
    texts = [None if value is None else _coerced_text(model, name, value) for name, value in leading.items()]
    if any(text is None for text in texts):
        raise ValueError("a prefix cannot contain a hole")
    return "".join(f"{encode_key_part(text)}{KEY_SEPARATOR}" for text in texts if text is not None)


#: How many leading characters of the spine key the prefix index covers. A btree index row
#: over ~2700 bytes is an error on insert; at four bytes per character in the worst UTF-8 case, 600
#: characters stay under it (2400 bytes), so no key of any length can fail a write
#: (``req-grid-entity-natural-key-22``). A longer prefix is still answered, by rechecking the full value.
PREFIX_INDEX_CHARS: Final[int] = 600


#: Bumped when the composition itself changes (separator, escape, stringification), so every type's
#: fingerprint changes with it and the deploy-time sync re-derives everything.
COMPOSITION_VERSION: Final[str] = "1"


def recipe_fingerprint(model: Any) -> str:
    """A hash of what a type's spine key is made from: its type, its ``NATURAL_KEY`` tuple and the
    composition itself (``-25``). When it changes, every stored key of that type may be stale."""
    declared = getattr(model, "NATURAL_KEY", None)
    recipe = json.dumps(
        {
            "entity_type": model.ENTITY_TYPE,
            "declared": list(declared) if isinstance(declared, tuple) else repr(declared),
            "composition": [COMPOSITION_VERSION, KEY_SEPARATOR, KEY_ESCAPE],
        },
        sort_keys=True,
    )
    return hashlib.sha256(recipe.encode("utf-8")).hexdigest()


def declared_columns(model: Any) -> list[str]:
    """The concrete columns a model's tuple declaration reads, in declared order, without repeats."""
    declared = getattr(model, "NATURAL_KEY", None)
    if not isinstance(declared, tuple):
        return []
    return list(dict.fromkeys(split_path(name)[0] for name in declared))
