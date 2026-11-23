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
    moment or an interval is its fields by name. No ``repr`` of the declaration is used.

    A reader function is recorded by its name, the import path that reaches it, and only where
    the declaration names one: a type that names none has the definition it had before readers
    existed. The function's code is not part of the definition (req-grid-entity-event-time rule 28)."""
    from tap_grid.event_time import Interval, Moment, NoEventTime, reader_name

    if declaration is None:
        return None
    if isinstance(declaration, NoEventTime):
        return {"shape": "none"}
    if isinstance(declaration, Moment):
        moment: dict[str, Any] = {"shape": "moment", "field": declaration.field, "kind": declaration.kind}
        if declaration.reader is not None:
            moment["reader"] = reader_name(declaration.reader)
        if declaration.member is not None:
            moment["member"] = list(declaration.member)
        return moment
    if isinstance(declaration, Interval):
        interval: dict[str, Any] = {
            "shape": "interval",
            "start": declaration.start,
            "end": declaration.end,
            "kind": declaration.kind,
        }
        if declaration.reader is not None:
            interval["reader"] = reader_name(declaration.reader)
        if declaration.end_reader is not None:
            interval["end_reader"] = reader_name(declaration.end_reader)
        if declaration.member is not None:
            interval["member"] = list(declaration.member)
        if declaration.end_member is not None:
            interval["end_member"] = list(declaration.end_member)
        return interval
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


# ---------------------------------------------------------------------------
# The chain between versions (rules 15 and 16)
# ---------------------------------------------------------------------------


def _narrowed(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Why a kept field takes fewer values than it did, or ``""`` where it does not."""
    if before.get("type") != after.get("type"):
        return f"its type changed from {before.get('type')} to {after.get('type')}"
    for limit in ("max_length", "max_digits", "decimal_places"):
        old, new = before.get(limit), after.get(limit)
        if isinstance(old, int) and isinstance(new, int) and new < old:
            return f"{limit} went from {old} to {new}"
    old_choices, new_choices = before.get("choices"), after.get("choices")
    if new_choices is not None and (
        old_choices is None or not set(map(str, old_choices)) <= set(map(str, new_choices))
    ):
        return "its allowed values were reduced"
    if not before.get("null") and after.get("null") is False and before.get("unique") is None and after.get("unique"):
        return "it became unique"
    return ""


def _allowed_edges(rules: Any) -> dict[str, Any] | None:
    """A node type's edge rules in one direction as edge type -> the endpoint types it allows.

    None where the type states no rule (any edge is allowed); ``"*"`` for an edge type allowed to
    any endpoint type. The recorded form is the declared list of ``{"edges": [...], "nodes":
    [...]}`` entries, read the way ``tap_grid.constraints`` reads it.
    """
    if rules is None:
        return None
    allowed: dict[str, Any] = {}
    for entry in rules if isinstance(rules, list) else []:
        if not isinstance(entry, Mapping):
            continue
        edge_types = [str(item.get("type")) for item in entry.get("edges") or [] if isinstance(item, Mapping)]
        nodes = entry.get("nodes")
        for edge_type in edge_types:
            if nodes is None or allowed.get(edge_type) == "*":
                allowed[edge_type] = "*"
            else:
                held = allowed.setdefault(edge_type, set())
                held |= {item.get("type") for item in nodes if isinstance(item, Mapping)}
    return allowed


def _tightened_node_rules(before: Any, after: Any) -> list[str]:
    """What a node type allowed in one direction before and no longer allows (rule 32)."""
    old, new = _allowed_edges(before), _allowed_edges(after)
    if new is None:
        return []
    if old is None:
        return ["a rule is stated where none was, so only the listed edges are allowed"]
    found: list[str] = []
    for edge_type in sorted(old):
        if edge_type not in new:
            found.append(f"{edge_type} is no longer allowed")
        elif new[edge_type] != "*":
            lost = "any type" if old[edge_type] == "*" else ", ".join(sorted(old[edge_type] - new[edge_type]))
            if lost:
                found.append(f"{edge_type} is no longer allowed with {lost}")
    return found


def _tightened_endpoints(before: Any, after: Any) -> str:
    """What an edge type's endpoint rule on one side allowed before and no longer allows."""
    if after == "*" or before == after:
        return ""
    if before == "*":
        return "any type was allowed and now only the listed ones are"
    lost = sorted(set(before or ()) - set(after or ()))
    return f"{', '.join(map(str, lost))} no longer allowed" if lost else ""


def _history_discard_problems(label: str, where: str, new_fields: Mapping[str, Any], step: Any) -> list[str]:
    """Rule 27: history values may be declared discarded only for a field that can be empty."""
    problems: list[str] = []
    for name in sorted(getattr(step, "discards_history", ()) or ()):
        spec = new_fields.get(name)
        if not isinstance(spec, Mapping):
            problems.append(
                f"{label}: the step from {where} declares history values of {name!r} discarded, and that is "
                "not a field of the new version"
            )
        elif not spec.get("null"):
            problems.append(
                f"{label}: the step from {where} declares history values of {name!r} that cannot be converted "
                "discarded, and the new field cannot be empty. There is no truthful value to leave in its "
                "place: make the field nullable, convert every value, or declare a break"
            )
    return problems


def _node_step_problems(
    label: str, where: str, before: Mapping[str, Any], after: Mapping[str, Any], step: Any
) -> list[str]:
    problems: list[str] = []
    old_fields: Mapping[str, Any] = before.get("fields") or {}
    new_fields: Mapping[str, Any] = after.get("fields") or {}
    # A rename or a derivation accounts for a removed field only where it is real: the old field
    # is one the old version had and the new field is one the new version has. A declaration
    # naming a field that does not exist accounts for nothing, and is itself a problem below.
    accounted = set(step.drops)
    accounted |= {old for new, old in step.renames.items() if old in old_fields and new in new_fields}
    for new_name, source in sorted(step.derived.items()):
        sources = [source] if isinstance(source, str) else list(source)
        missing = sorted(str(name) for name in sources if name not in old_fields)
        if new_name not in new_fields or missing:
            reasons = []
            if new_name not in new_fields:
                reasons.append(f"{new_name!r} is not a field of the new version")
            if missing:
                reasons.append(f"{', '.join(map(repr, missing))} is not a field of the old version")
            problems.append(
                f"{label}: the step from {where} declares {new_name!r} derived from "
                f"{', '.join(map(repr, sources))}, and {' and '.join(reasons)}. A derivation that names no "
                "real field accounts for nothing"
            )
            continue
        accounted |= set(sources)
    for name in sorted(set(old_fields) - set(new_fields) - accounted):
        problems.append(
            f"{label}: field {name!r} is removed from {where} and the step does not declare it. Name it in "
            "the step's drops, or as the old field of a rename, or declare a break"
        )
    for name in sorted(set(step.drops) & set(new_fields)):
        problems.append(f"{label}: the step from {where} declares {name!r} dropped and the new version still has it")
    for new_name, old_name in sorted(step.renames.items()):
        if old_name not in old_fields or new_name not in new_fields:
            problems.append(
                f"{label}: the step from {where} declares {old_name!r} renamed to {new_name!r}, and that is not "
                "a field of the old version becoming a field of the new one"
            )
    refusable: list[str] = []
    for name in sorted(set(old_fields) & set(new_fields)):
        reason = _narrowed(old_fields[name], new_fields[name])
        if reason:
            refusable.append(f"field {name!r} is narrowed ({reason})")
        if old_fields[name].get("null") and not new_fields[name].get("null"):
            refusable.append(f"field {name!r} can no longer be empty")
    old_required = set((before.get("service_schema") or {}).get("create_required") or ())
    new_required = set((after.get("service_schema") or {}).get("create_required") or ())
    for name in sorted((new_required - old_required) & set(old_fields)):
        refusable.append(f"field {name!r} is made required")
    if refusable and not step.may_refuse:
        problems.extend(
            f"{label}: from {where} {reason}, so some records of the old version cannot be carried, and the "
            "step does not say it may refuse records (may_refuse, with the reason), nor is a break declared"
            for reason in refusable
        )
    if before.get("key") != after.get("key") and step.key is None and not step.key_refused:
        problems.append(
            f"{label}: the natural key changes from {where} ({before.get('key')} to {after.get('key')}) and the "
            "step declares neither how a key is carried across (key) nor that it cannot be (key_refused)"
        )
    # Rule 32: a version that allows fewer edges says so on its link, because edges written under
    # the old rules stay on the grid and a migration to it must look for them first.
    old_rules: Mapping[str, Any] = before.get("edge_rules") or {}
    new_rules: Mapping[str, Any] = after.get("edge_rules") or {}
    tightened = [
        f"{direction}: {found}"
        for direction in ("outbound", "inbound")
        for found in _tightened_node_rules(old_rules.get(direction), new_rules.get(direction))
    ]
    if tightened and not getattr(step, "tightens_edges", ""):
        problems.extend(
            f"{label}: from {where} the edge rules are tightened ({found}) and the step does not declare it "
            "(tightens_edges, with the reason), nor is a break declared"
            for found in tightened
        )
    problems.extend(_history_discard_problems(label, where, new_fields, step))
    return problems


def _edge_step_problems(
    label: str, where: str, before: Mapping[str, Any], after: Mapping[str, Any], step: Any
) -> list[str]:
    problems: list[str] = []
    old_rules, new_rules = before.get("property_rules"), after.get("property_rules")
    old_properties = set((old_rules or {}).get("properties") or ()) if isinstance(old_rules, Mapping) else set()
    new_properties = set((new_rules or {}).get("properties") or ()) if isinstance(new_rules, Mapping) else set()
    accounted = set(step.drops)
    for new_name, old_name in sorted(step.renames.items()):
        if old_name in old_properties and new_name in new_properties:
            accounted.add(old_name)
        else:
            problems.append(
                f"{label}: the step from {where} declares {old_name!r} renamed to {new_name!r}, and that is not "
                "a property of the old version becoming a property of the new one"
            )
    for new_name, source in sorted(step.derived.items()):
        sources = [source] if isinstance(source, str) else list(source)
        if new_name in new_properties and all(name in old_properties for name in sources):
            accounted |= set(sources)
        else:
            problems.append(
                f"{label}: the step from {where} declares {new_name!r} derived from "
                f"{', '.join(map(repr, sources))}, and that is not a property of the new version built from "
                "properties of the old one"
            )
    for name in sorted(old_properties - new_properties - accounted):
        problems.append(
            f"{label}: property {name!r} is removed from {where} and the step does not declare it dropped or renamed"
        )
    old_required = set((old_rules or {}).get("required") or ()) if isinstance(old_rules, Mapping) else set()
    new_required = set((new_rules or {}).get("required") or ()) if isinstance(new_rules, Mapping) else set()
    if (new_required - old_required) and not step.may_refuse:
        named = ", ".join(sorted(new_required - old_required))
        problems.append(
            f"{label}: from {where} the properties {named} are made required and the step does not say it may "
            "refuse records (may_refuse)"
        )
    # Rule 32 for an edge type: its own endpoint rules narrowed.
    old_ends: Mapping[str, Any] = before.get("endpoint_rules") or {}
    new_ends: Mapping[str, Any] = after.get("endpoint_rules") or {}
    narrowed = [
        f"{side}: {found}"
        for side in ("sources", "targets")
        if (found := _tightened_endpoints(old_ends.get(side, "*"), new_ends.get(side, "*")))
    ]
    if narrowed and not getattr(step, "tightens_edges", ""):
        problems.extend(
            f"{label}: from {where} the endpoint rules are narrowed ({found}) and the step does not declare it "
            "(tightens_edges, with the reason), nor is a break declared"
            for found in narrowed
        )
    # How an edge of the type is found again is its key (rule 15): a change is declared like a
    # node type's key change, as a function that carries a key across or as a refusal.
    if before.get("identity") != after.get("identity") and step.key is None and not step.key_refused:
        problems.append(
            f"{label}: the identity declaration changes from {where} and the step declares neither how a key is "
            "carried across (key) nor that it cannot be (key_refused)"
        )
    if getattr(step, "discards_history", ()):
        problems.append(
            f"{label}: the step from {where} declares history values discarded, which applies to a node type's "
            "fields; an edge type's properties are one JSON column whose type does not change"
        )
    return problems


def link_problems(state: TypeState, entries: list[dict[str, Any]]) -> list[str]:
    """What is wrong between a type's consecutive versions and the links declared for them.

    Rule 16: a version after the first with no link is a problem, whether or not the type has a
    committed record. Rule 15: where two consecutive entries are recorded and the link between
    them is a step, a field removed, a type narrowed, a field made required and a natural key
    changed must each be declared on the step. A declared break excuses any difference. The
    spine's chain is checked for its links only: its definition is three tables, not one list of
    fields, and a change to it is core's own to review. An edge rule a version tightens (rule 32)
    and history values declared discarded (rule 27) are checked here too; what the declarations
    then do to stored rows is ``tap_grid.version_migration``'s.
    """
    from tap_grid import version_links

    slug = version_links.SPINE if state.kind == SPINE else state.slug
    problems = version_links.declaration_problems(state.label, slug, state.version)
    if problems or state.kind == SPINE or chain_problems(state.label, entries):
        return problems
    by_version = {entry["version"]: entry["definition"] for entry in entries}
    by_version.setdefault(state.version, state.definition)
    chain = version_links.links_for(slug)
    for version in range(FIRST_VERSION + 1, state.version + 1):
        link = chain.links.get(version)
        before, after = by_version.get(version - 1), by_version.get(version)
        if not isinstance(link, version_links.Step) or before is None or after is None:
            continue
        where = version_links.describe(version)
        compare = _node_step_problems if state.kind == NODE else _edge_step_problems
        problems.extend(compare(state.label, where, before, after, link))
    return problems
