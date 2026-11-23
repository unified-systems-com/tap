"""A type's definition, its fingerprint, and the committed record of both.

``req-grid-entity-model-version`` rules 5 and 7, and ``req-grid-entity-spine-version`` rule 7. An
authored version alone is forgotten, so a guard compares each type's definition with the one
committed beside its version: a definition that changed while its version did not fails, in the
repository that owns the type.

**What a definition covers.** What the type's owner declares, and only what bears on stored data:

- a node type: the fields the class itself adds (name, type, nullability, uniqueness, length,
  precision, choices, relation target), its model constraints, its natural key, its service schema,
  the edge rules it declares (``OUTBOUND_EDGES`` and ``INBOUND_EDGES``) and its event-time
  declaration (``EVENT_TIME``);
- an edge type: its property rules, its endpoint rules, its event-time declaration and its
  identity declaration;
- the spine: every column of ``Entity``, the columns every typed row inherits from core's base
  model, and the columns core defines on the edge table, with their constraints.

The fields a type inherits from the base model belong to the spine's definition and to no type's,
so a change core makes to one moves no type's version. Indexes, help text, defaults and display
attributes are left out: they change with no stored row changing.

**The record.** One ``<app label>.model_versions.json`` at the root of the package that owns the
types: a plugin's in the plugin's repository, core's in each core app. For each type it holds a list with
one entry per version, and it only grows. An entry stores the definition itself, which a later
comparison of two versions needs, and a fingerprint chained to the entry before it, so an edit to an
earlier entry breaks every fingerprint after it. The chain shows an edit that left the stored
fingerprints alone; it cannot show one that rewrote them all, which is for review of the file's
history to catch.

A change of meaning with no change of definition is invisible here by construction (rule 8).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from django.db import models

from tap_grid.model_version import EDGE, EDGE_VERSION_KEY, FIRST_VERSION, NODE, checked_version, declared_version

#: The record's name within its owner's file name (``<app label>.model_versions.json``, the
#: singleton form of req-tap-json-naming), at the root of the package that owns the types.
RECORD_NAME = "model_versions"
#: The version of this module's way of writing a definition. Changing what a definition covers
#: changes every fingerprint, so it is a new format and a deliberate re-record, never a silent one.
RECORD_FORMAT = 1
#: Set to 1 to make a plugin type with no committed entry fail plugin validation.
REQUIRE_RECORD_ENV = "TAP_REQUIRE_MODEL_VERSION_RECORD"

SPINE = "spine"
_SECTIONS = {NODE: "nodes", EDGE: "edges"}


# ---------------------------------------------------------------------------
# Writing a definition down
# ---------------------------------------------------------------------------


def canonical(value: Any) -> Any:
    """``value`` as plain JSON data that is the same on every machine and every run.

    No ``repr`` of an arbitrary object reaches the result: a memory address or an unordered set
    would make the fingerprint of an unchanged definition move.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return canonical(value.value)
    if isinstance(value, Mapping):
        return {str(key): canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=_sort_key)
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, models.Q):
        return {"q": value.connector, "negated": value.negated, "children": [canonical(c) for c in value.children]}
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    deconstruct = getattr(value, "deconstruct", None)
    if deconstruct is not None:
        parts = deconstruct()
        # A field deconstructs to (name, path, args, kwargs); an expression or a constraint to (path, args, kwargs).
        path, args, kwargs = parts[-3:]
        return {"class": path, "args": canonical(args), "kwargs": canonical(kwargs)}
    if callable(value):
        return f"{getattr(value, '__module__', '')}.{getattr(value, '__qualname__', type(value).__qualname__)}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return f"{type(value).__module__}.{type(value).__qualname__}:{value}"


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _unordered(values: Any) -> Any:
    """A list whose order carries no meaning, in one stable order."""
    if values is None:
        return None
    return sorted((canonical(item) for item in values), key=_sort_key)


def _field_definition(field: Any) -> dict[str, Any]:
    definition: dict[str, Any] = {"type": field.get_internal_type(), "null": bool(field.null)}
    if getattr(field, "primary_key", False):
        definition["primary_key"] = True
    elif getattr(field, "unique", False):
        definition["unique"] = True
    for attribute in ("max_length", "max_digits", "decimal_places"):
        if getattr(field, attribute, None) is not None:
            definition[attribute] = getattr(field, attribute)
    choices = getattr(field, "choices", None)
    if choices:
        definition["choices"] = _unordered([choice[0] for choice in choices])
    related = getattr(field, "related_model", None)
    if related is not None and not isinstance(related, str):
        definition["to"] = related._meta.label_lower
    elif related is not None:
        definition["to"] = related.lower()
    return definition


def _fields(model_cls: type[models.Model], *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    meta = model_cls._meta
    own = [*meta.concrete_fields, *meta.local_many_to_many]
    return {field.name: _field_definition(field) for field in own if field.name not in exclude}


def _constraints(model_cls: type[models.Model]) -> list[Any]:
    meta = model_cls._meta
    found = [canonical(constraint) for constraint in meta.constraints]
    found.extend({"unique_together": list(group)} for group in meta.unique_together)
    return sorted(found, key=_sort_key)


def inherited_field_names(base: type[models.Model]) -> frozenset[str]:
    """The fields every subclass of the abstract ``base`` inherits from it."""
    return frozenset(field.name for field in base._meta.local_fields)


def _declared_key(model_cls: type) -> Any:
    """How the type is found: its declared key columns, ``"keyless"``, or None where it has not said."""
    declared = getattr(model_cls, "NATURAL_KEY", None)
    if declared is None:
        return None
    if isinstance(declared, (tuple, list)):
        return list(declared)
    return "keyless"


def event_time_definition(declaration: Any) -> Any:
    """A node type's ``EVENT_TIME`` in plain data. Three statements stay three values: none
    declared is None, the explicit "this type has no event time" is ``{"shape": "none"}``, and a
    moment or an interval is its fields by name. No ``repr`` of the declaration is used."""
    from tap_grid.event_time import Interval, Moment, NoEventTime

    if declaration is None:
        return None
    if isinstance(declaration, NoEventTime):
        return {"shape": "none"}
    if isinstance(declaration, Moment):
        return {"shape": "moment", "field": declaration.field, "kind": declaration.kind}
    if isinstance(declaration, Interval):
        return {"shape": "interval", "start": declaration.start, "end": declaration.end, "kind": declaration.kind}
    raise TypeError(f"EVENT_TIME of type {type(declaration).__qualname__} is not an event-time declaration")


def node_definition(model_cls: type[models.Model], *, base: type[models.Model] | None = None) -> dict[str, Any]:
    """The definition of a node type: what its class declares, without what it inherits from ``base``.

    ``base`` is core's base model unless a test names another.
    """
    if base is None:
        from tap_grid.models import BaseModel

        base = BaseModel
    return {
        "fields": _fields(model_cls, exclude=inherited_field_names(base)),
        "constraints": _constraints(model_cls),
        "key": _declared_key(model_cls),
        "service_schema": {
            "fields": canonical(getattr(model_cls, "FIELD_CRUD_SCHEMA", None)),
            "validation": canonical(getattr(model_cls, "FIELD_VALIDATION_SCHEMA", None)),
            "create_required": _unordered(getattr(model_cls, "CREATE_REQUIRED", None)),
        },
        "edge_rules": {
            "outbound": _unordered(getattr(model_cls, "OUTBOUND_EDGES", None)),
            "inbound": _unordered(getattr(model_cls, "INBOUND_EDGES", None)),
        },
        "event_time": event_time_definition(getattr(model_cls, "EVENT_TIME", None)),
    }


def _endpoints(declared: Any) -> Any:
    """Endpoint rules in one form: ``"*"`` for any type, else the sorted types. A manifest lists
    slugs and a core app lists ``{"type": slug}``; both mean the same rule."""
    if declared is None:
        return "*"
    plain = [item["type"] if isinstance(item, Mapping) and set(item) == {"type"} else item for item in declared]
    return _unordered(plain)


def edge_definition(
    *, sources: Any, targets: Any, property_schema: Any, event_time: Any, identity: Any
) -> dict[str, Any]:
    """The definition of an edge type: its property rules, endpoint rules, event-time declaration
    and identity declaration (``req-grid-edge-identity-declaration``). ``identity`` is the
    declaration as authored, None where the type declares none."""
    return {
        "property_rules": canonical(property_schema),
        "endpoint_rules": {"sources": _endpoints(sources), "targets": _endpoints(targets)},
        "event_time": canonical(event_time),
        "identity": canonical(identity),
    }


def spine_definition() -> dict[str, Any]:
    """The spine's definition: the ``Entity`` row, what every typed row inherits from the base model,
    and the columns core defines on the edge table."""
    from tap_grid.models import BaseModel, Edge, Entity

    inherited = inherited_field_names(BaseModel)
    edge_fields = _fields(Edge)
    return {
        "entity": {"fields": _fields(Entity), "constraints": _constraints(Entity)},
        "base_model": {name: definition for name, definition in edge_fields.items() if name in inherited},
        "edge": {
            "fields": {name: definition for name, definition in edge_fields.items() if name not in inherited},
            "constraints": _constraints(Edge),
        },
    }


# ---------------------------------------------------------------------------
# Fingerprints and entries
# ---------------------------------------------------------------------------


def fingerprint(previous: str, version: int, definition: Any) -> str:
    """The fingerprint of one entry, chained to the entry before it (``""`` for the first)."""
    body = json.dumps(
        {"previous": previous, "version": version, "definition": definition},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(body.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class TypeState:
    """One type as the installed code defines it now."""

    kind: str  # NODE, EDGE or SPINE
    slug: str
    version: int
    definition: dict[str, Any]

    @property
    def label(self) -> str:
        return "the spine" if self.kind == SPINE else f"{self.kind} type {self.slug!r}"


def entries_for(record: Mapping[str, Any], state: TypeState) -> list[dict[str, Any]]:
    """The committed entries for a type; an empty list where the record has none."""
    if state.kind == SPINE:
        found = record.get(SPINE)
    else:
        section = record.get(_SECTIONS[state.kind])
        found = section.get(state.slug) if isinstance(section, Mapping) else None
    return list(found) if isinstance(found, list) else []


def chain_problems(label: str, entries: list[dict[str, Any]]) -> list[str]:
    """What is wrong with a type's committed entries on their own: order, gaps, and edits."""
    problems: list[str] = []
    previous = ""
    expected: int | None = None
    for entry in entries:
        version = entry.get("version") if isinstance(entry, Mapping) else None
        if isinstance(version, bool) or not isinstance(version, int) or version < FIRST_VERSION:
            problems.append(f"{label}: an entry in the committed record has no usable version ({version!r})")
            return problems
        if expected is not None and version != expected:
            problems.append(
                f"{label}: the committed record goes from version {expected - 1} to {version}; it holds one "
                "entry per version, in order"
            )
            return problems
        computed = fingerprint(previous, version, entry.get("definition"))
        if entry.get("fingerprint") != computed:
            problems.append(
                f"{label}: the committed entry for version {version} was changed after it was recorded "
                "(its fingerprint no longer matches its definition and the entries before it). A committed "
                "version does not change; a new definition is a new version"
            )
            return problems
        previous, expected = computed, version + 1
    return problems


def type_problems(state: TypeState, entries: list[dict[str, Any]]) -> list[str]:
    """What is wrong between a type as defined now and its committed entries. Empty means in step.

    A type with no entry at all is not judged here: :func:`has_record` says so and the caller
    decides what an absent record means for it.
    """
    if not entries:
        return []
    problems = chain_problems(state.label, entries)
    if problems:
        return problems
    last = entries[-1]
    if last["version"] == state.version:
        if last["definition"] != state.definition:
            changed = ", ".join(_changed_parts(last["definition"], state.definition)) or "its definition"
            problems.append(
                f"{state.label}: its definition changed ({changed}) and its version is still {state.version}. "
                "Raise the version with the change, provide the migration that moves the stored rows, and "
                "record the new version (manage.py model_versions --record)"
            )
    elif last["version"] < state.version:
        problems.append(
            f"{state.label}: version {state.version} is declared and the committed record ends at version "
            f"{last['version']}. Record it (manage.py model_versions --record)"
        )
    else:
        problems.append(
            f"{state.label}: version {state.version} is declared and the committed record already holds "
            f"version {last['version']}. A version does not go down"
        )
    return problems


def _changed_parts(before: Any, after: Any, prefix: str = "") -> list[str]:
    """The paths at which two definitions differ, to three levels: enough to say what moved."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return [prefix.rstrip(".")] if before != after else []
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}{key}"
        if key not in before:
            changed.append(f"{path} added")
        elif key not in after:
            changed.append(f"{path} removed")
        elif before[key] != after[key]:
            if prefix.count(".") < 2 and isinstance(before[key], Mapping) and isinstance(after[key], Mapping):
                changed.extend(_changed_parts(before[key], after[key], f"{path}."))
            else:
                changed.append(f"{path} changed")
    return changed


def has_record(entries: list[dict[str, Any]]) -> bool:
    return bool(entries)


def append_entry(record: dict[str, Any], state: TypeState) -> bool:
    """Add the entry for a type's declared version where the record does not hold it yet.

    Only ever appends. Returns whether it added one. Raises ``ValueError`` where adding would
    not be an append: the entries already there do not verify, the declared version would skip
    one, or the record is ahead of the code.
    """
    if state.kind == SPINE:
        entries = record.setdefault(SPINE, [])
    else:
        entries = record.setdefault(_SECTIONS[state.kind], {}).setdefault(state.slug, [])
    problems = chain_problems(state.label, entries)
    if problems:
        raise ValueError(problems[0])
    if entries:
        last = entries[-1]["version"]
        if last == state.version:
            return False
        if state.version != last + 1:
            raise ValueError(
                f"{state.label}: version {state.version} is declared and the record ends at {last}; the "
                "record holds one entry per version, so each version is recorded before the next is declared"
            )
    previous = entries[-1]["fingerprint"] if entries else ""
    entries.append(
        {
            "version": state.version,
            "definition": state.definition,
            "fingerprint": fingerprint(previous, state.version, state.definition),
        }
    )
    return True


# ---------------------------------------------------------------------------
# The record file
# ---------------------------------------------------------------------------


def load_record(path: Path) -> dict[str, Any]:
    """The committed record at ``path``; an empty one where there is no file."""
    if not path.exists():
        return {"format": RECORD_FORMAT}
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"{path}: the record must be a JSON object")
    if record.get("format") != RECORD_FORMAT:
        raise ValueError(
            f"{path}: record format {record.get('format')!r} is not the format this core writes ({RECORD_FORMAT})"
        )
    return record


def _owned_record_path(path: Path) -> Path:
    """``path`` resolved, where it is an installed app's own record file; else ``ValueError``.

    A record is written in one place only: ``<app label>.model_versions.json`` at the root of an
    installed app's package. Any other path is refused, so no caller can make this write elsewhere.
    """
    from django.apps import apps

    resolved = path.resolve()
    for config in apps.get_app_configs():
        if resolved.parent == Path(config.path).resolve() and resolved.name == record_file_name(config.label):
            return resolved
    raise ValueError(f"{path} is not the version record of an installed app; nothing was written")


def write_record(path: Path, record: Mapping[str, Any]) -> None:
    """Write ``record`` to an installed app's record file; any other path is refused."""
    path = _owned_record_path(path)
    path.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Who owns which types
# ---------------------------------------------------------------------------


def _edge_state(slug: str, definition: Mapping[str, Any]) -> TypeState:
    version = checked_version(definition.get(EDGE_VERSION_KEY, FIRST_VERSION), f"edge type {slug!r} {EDGE_VERSION_KEY}")
    return TypeState(
        EDGE,
        slug,
        version,
        edge_definition(
            sources=definition.get("sources"),
            targets=definition.get("targets"),
            property_schema=definition.get("property_schema"),
            event_time=definition.get("event_time"),
            identity=definition.get("identity"),
        ),
    )


def spine_state() -> TypeState:
    from tap_grid.spine_version import SPINE_VERSION

    return TypeState(SPINE, SPINE, SPINE_VERSION, spine_definition())


def core_states() -> dict[str, list[TypeState]]:
    """Core's types by owning app (its dotted name), the spine under ``tap_grid``."""
    from django.apps import apps

    from tap_grid.model_version import core_edge_types, core_node_types

    owned: dict[str, list[TypeState]] = {"tap_grid": [spine_state()]}
    for slug, model_cls in core_node_types().items():
        config = apps.get_containing_app_config(model_cls.__module__)
        owner = config.name if config is not None else "tap_grid"
        owned.setdefault(owner, []).append(
            TypeState(NODE, slug, declared_version(model_cls), node_definition(model_cls))
        )
    for slug, (owner, definition) in core_edge_types().items():
        owned.setdefault(owner, []).append(_edge_state(slug, definition))
    return owned


def plugin_states(manifest: Any) -> list[TypeState]:
    """A plugin's types, from its manifest. A model class that does not import is left to the
    check that owns that failure."""
    from django.utils.module_loading import import_string

    states: list[TypeState] = []
    for entry in manifest.models or []:
        try:
            model_cls = import_string(entry.class_path)
        except ImportError:
            continue
        states.append(TypeState(NODE, entry.slug, declared_version(model_cls), node_definition(model_cls)))
    for edge in manifest.edges or []:
        states.append(
            _edge_state(
                edge.slug,
                {
                    "sources": edge.sources,
                    "targets": edge.targets,
                    "property_schema": edge.property_schema,
                    "event_time": edge.event_time,
                    "identity": edge.identity,
                    **({EDGE_VERSION_KEY: edge.version} if edge.version is not None else {}),
                },
            )
        )
    return states


def record_file_name(owner_label: str) -> str:
    """The record's file name for the app or plugin with this label (a plugin's label is its slug)."""
    return f"{owner_label}.{RECORD_NAME}.json"


def app_record_path(app_name: str) -> Path:
    """Where the app or plugin with dotted name ``app_name`` keeps its record."""
    from django.apps import apps

    for config in apps.get_app_configs():
        if config.name == app_name:
            return Path(config.path) / record_file_name(config.label)
    raise LookupError(f"no installed app is named {app_name!r}")


def unrecorded(states: Iterable[TypeState], record: Mapping[str, Any]) -> list[TypeState]:
    """The types with no committed entry at all."""
    return [state for state in states if not has_record(entries_for(record, state))]
