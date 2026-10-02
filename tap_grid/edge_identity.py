"""Edge identity declarations (``req-grid-edge-identity-declaration``).

An edge's ``id`` is an assigned UUIDv7, as a node's is. How a relationship is *found again* is a
separate, declared thing, stated per edge TYPE on its edge definition in one member,
``identity``:

- ``{"discriminators": [{"path": ..., "description": ...}, ...]}`` names the properties that,
  beside the type and the two endpoints, tell one relationship from another. An EMPTY list is
  the plain key: the edge is identified by (type, source, target) alone. Plain is therefore a
  declaration, never an absence.
- ``{"keyless": {"reason": ...}}`` says the type observes no source relationship, with the
  reason a reader needs to judge whether that is still right.

Three states, never two: plain, keyless, and **undeclared**. An undeclared type is neither, and
nothing here treats it as either.

A discriminator's ``path`` is a place inside the edge's ``properties`` and uses the node natural
key's path grammar (:func:`tap_grid.natural_key.split_path`), read through the same parser, so
edge and node paths cannot drift: ``"scope"`` is ``properties.scope``, ``"rule.type"`` is
``properties.rule.type``.

One declaration per type and no merge: edge-type constraints union across apps, but two
declarations disagreeing about what makes an edge the same edge would be silent drift, so a
second registration is a configuration error (``req-grid-edge-identity-declaration-4``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

from tap.registry import Registry
from tap_grid.natural_key import split_path

__all__ = [
    "ENFORCE_EDGE_IDENTITY_DECLARED",
    "IDENTITY_PATH_ROOT",
    "Discriminator",
    "EdgeIdentity",
    "IncompleteEdgeKey",
    "KeylessEdgeExists",
    "edge_identity_values",
    "edge_lock_key",
    "find_live_edges",
    "get_edge_identity",
    "incomplete_paths",
    "list_declared_edge_types",
    "parse_edge_identity",
    "register_edge_identity",
]

#: The Edge column every discriminator path lives under: a declared ``"scope"`` is read as the
#: node-grammar path ``"properties.scope"``.
IDENTITY_PATH_ROOT: Final[str] = "properties"

#: Fail-closed switch for ``req-grid-edge-identity-6``: a ref-addressed edge of a type with no
#: identity declaration. False is warn mode (ruled 2026-10-02): the edge is created as before,
#: with no lookup, and the import reports a warning naming the type, so producers can declare
#: their types before anything refuses them. The flip to True is Issue# 928 - tap. Tests may
#: monkeypatch it to exercise both paths.
ENFORCE_EDGE_IDENTITY_DECLARED: bool = False

_IDENTITY_MEMBERS: Final[frozenset[str]] = frozenset({"discriminators", "keyless"})
_DISCRIMINATOR_MEMBERS: Final[frozenset[str]] = frozenset({"path", "description"})
_KEYLESS_MEMBERS: Final[frozenset[str]] = frozenset({"reason"})


class IncompleteEdgeKey(ValueError):
    """A declared discriminator is absent, null or empty, so the edge's key is incomplete.

    Rejected, never matched as "not found" (``req-grid-edge-identity-8``): a key with a hole
    would find nothing on every run and mint a duplicate each time. Deliberately stricter than
    the node convention, where an empty string is observed-empty and searched
    (``req-grid-entity-natural-key-16``): for an edge discriminator it distinguishes nothing.
    """

    def __init__(self, edge_type: str, paths: list[str]) -> None:
        self.edge_type = edge_type
        self.paths = list(paths)
        super().__init__(
            f"{edge_type}: declared discriminator(s) {self.paths} are absent, null or empty, so the edge's "
            "identity key is incomplete; an incomplete key is rejected, never matched as not found "
            "(req-grid-edge-identity-8)"
        )


class KeylessEdgeExists(LookupError):
    """A keyless type's (type, source, target) already has a live edge.

    A keyless type has no search, so nothing says a second submission is the same edge: the
    batch carrying it fails (``req-grid-edge-identity-5``).
    """

    def __init__(self, edge_type: str, from_id: object, to_id: object, candidates: list[object]) -> None:
        self.edge_type = edge_type
        self.candidates = list(candidates)
        super().__init__(
            f"{edge_type} is keyless and {from_id} -> {to_id} already has a live edge of it "
            f"({', '.join(str(c) for c in self.candidates[:10])}); a keyless type cannot tell a re-sent edge "
            "from a second one, so the batch fails (req-grid-edge-identity-5)"
        )


@dataclass(frozen=True)
class Discriminator:
    """One property, beside the type and the endpoints, that tells two relationships apart."""

    path: str
    description: str


@dataclass(frozen=True)
class EdgeIdentity:
    """How an edge of one type is found again: its discriminators, or the reason it has none."""

    discriminators: tuple[Discriminator, ...] = ()
    keyless_reason: str | None = None

    @property
    def keyless(self) -> bool:
        """True when the type declares that it observes no source relationship."""
        return self.keyless_reason is not None

    @property
    def paths(self) -> tuple[str, ...]:
        """The discriminator paths, in declared order, relative to ``properties``."""
        return tuple(d.path for d in self.discriminators)


_edge_identity_registry: Registry[EdgeIdentity] = Registry(
    "edge_identities",
    title="Edge Identity Declarations",
    description=(
        "Per edge type: the discriminators that, beside the type and the two endpoints, identify a "
        "relationship (empty for the plain key), or the reason the type is keyless "
        "(req-grid-edge-identity-declaration). One declaration per type; never merged."
    ),
)


def _fail(edge_type: str, message: str) -> ImproperlyConfigured:
    return ImproperlyConfigured(f"Edge type {edge_type!r} identity: {message} (req-grid-edge-identity-declaration)")


def _resolve_in_schema(edge_type: str, path: str, property_schema: Mapping[str, Any] | None) -> str | None:
    """Why ``path`` does not resolve through ``property_schema``, or None when it does.

    The top level must name the path's first key, because a discriminator the type's schema does
    not declare is a property no writer is told to fill. Below that the rule is the node natural
    key's (``req-grid-entity-natural-key-17``): each level that lists ``properties`` must list the
    next key, and a level that says nothing further is not a failure.
    """
    if property_schema is None:
        return (
            f"discriminator {path!r} needs a property_schema to resolve against, and the type declares none; "
            "a discriminator must be a declared property"
        )
    level: Any = property_schema
    for depth, key in enumerate(path.split(".")):
        properties = level.get("properties") if isinstance(level, Mapping) else None
        if not isinstance(properties, Mapping):
            if depth == 0:
                return f"discriminator {path!r}: the property_schema declares no properties"
            return None
        if key not in properties:
            return f"discriminator {path!r}: {key!r} is not among the schema's properties {sorted(properties)}"
        level = properties[key]
    return None


def parse_edge_identity(edge_type: str, raw: Any, *, property_schema: Mapping[str, Any] | None = None) -> EdgeIdentity:
    """Read one ``identity`` member into an :class:`EdgeIdentity`, refusing anything malformed.

    The shape is checked here even for definitions a JSON Schema already validated, because core
    apps register Python dicts no schema ever sees, and a declaration must mean the same thing
    whichever way it arrived.

    TAP-IMPLEMENTS: req-grid-edge-identity-declaration@24e3819f0e13/08b088116dac (derivation) — the
        one reading of an identity member: exactly one of discriminators and keyless, each
        discriminator an object with a path and a description, each path resolving through the
        type's property schema (acceptance -1, -2, -3, -6).

    Args:
        edge_type: The edge type slug the declaration belongs to.
        raw: The ``identity`` member as declared.
        property_schema: The type's property schema, against which every discriminator path must
            resolve.

    Returns:
        The parsed declaration.

    Raises:
        ImproperlyConfigured: The declaration is malformed, or a discriminator does not resolve.
    """
    if not isinstance(raw, Mapping):
        raise _fail(edge_type, f"must be an object, not {type(raw).__name__}")
    members = set(raw)
    unknown = members - _IDENTITY_MEMBERS
    if unknown:
        raise _fail(edge_type, f"unknown member(s) {sorted(unknown)}; the members are discriminators and keyless")
    if len(members) != 1:
        raise _fail(edge_type, "carries exactly one of discriminators (empty for the plain key) and keyless")

    if "keyless" in raw:
        keyless = raw["keyless"]
        if not isinstance(keyless, Mapping) or set(keyless) != _KEYLESS_MEMBERS:
            raise _fail(edge_type, 'keyless must be an object with exactly one member, "reason"')
        reason = keyless["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise _fail(edge_type, "keyless needs a non-empty reason")
        return EdgeIdentity(keyless_reason=reason)

    declared = raw["discriminators"]
    if not isinstance(declared, list):
        raise _fail(edge_type, "discriminators must be an array (empty for the plain key)")
    discriminators: list[Discriminator] = []
    seen: set[str] = set()
    for position, entry in enumerate(declared):
        if not isinstance(entry, Mapping) or set(entry) != _DISCRIMINATOR_MEMBERS:
            raise _fail(
                edge_type,
                f"discriminators[{position}] must be an object with exactly a path and a description; "
                "a bare string is not a discriminator",
            )
        path, description = entry["path"], entry["description"]
        if not isinstance(path, str) or not path:
            raise _fail(edge_type, f"discriminators[{position}].path must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise _fail(
                edge_type,
                f"discriminators[{position}] ({path!r}) needs a description: what it is, how it is set, "
                "and why it is in the key",
            )
        try:
            split_path(f"{IDENTITY_PATH_ROOT}.{path}")
        except ValueError as exc:
            raise _fail(edge_type, f"discriminators[{position}]: {exc}") from exc
        if path in seen:
            raise _fail(edge_type, f"discriminator path {path!r} is declared twice")
        seen.add(path)
        problem = _resolve_in_schema(edge_type, path, property_schema)
        if problem is not None:
            raise _fail(edge_type, problem)
        discriminators.append(Discriminator(path=path, description=description))
    return EdgeIdentity(discriminators=tuple(discriminators))


def register_edge_identity(
    edge_type: str, raw: Any, *, property_schema: Mapping[str, Any] | None = None
) -> EdgeIdentity:
    """Parse and register an edge type's identity declaration; a second one is an error.

    TAP-IMPLEMENTS: req-grid-edge-identity-declaration@24e3819f0e13/01fdbee21b58 (enforcement) — the
        one registration point every definition home calls (a plugin's .edge.json, a core app's
        edge_types list, the grid-standard edges), so a declaration is read once and refused a
        second time rather than merged (acceptance -4, -7).

    Args:
        edge_type: The edge type slug.
        raw: The ``identity`` member as declared.
        property_schema: The property schema declared beside it. When omitted, the schema
            already registered for the type is used.

    Returns:
        The registered declaration.

    Raises:
        ImproperlyConfigured: The declaration is malformed, or the type already has one.
    """
    if property_schema is None:
        from tap_grid.constraints import get_edge_property_schema

        property_schema = get_edge_property_schema(edge_type)
    identity = parse_edge_identity(edge_type, raw, property_schema=property_schema)
    _edge_identity_registry.register(edge_type, identity)
    return identity


def get_edge_identity(edge_type: str) -> EdgeIdentity | None:
    """The registered declaration for ``edge_type``, or None when the type is undeclared."""
    return _edge_identity_registry.get_optional(edge_type)


def list_declared_edge_types() -> list[str]:
    """Every edge type slug that carries an identity declaration, sorted."""
    return _edge_identity_registry.keys()


def edge_identity_values(identity: EdgeIdentity, properties: Mapping[str, Any]) -> dict[str, object]:
    """Each declared discriminator's value as an edge's ``properties`` carries it, keyed by path.

    Read through the node natural key's extraction under the ``properties`` root, so a missing
    key, an explicit JSON null and a missing or non-object parent all read as ``None``.
    """
    from tap_grid.natural_key import constituting_properties

    payload = {IDENTITY_PATH_ROOT: dict(properties)}
    values = constituting_properties([f"{IDENTITY_PATH_ROOT}.{path}" for path in identity.paths], payload)
    return {path: values[f"{IDENTITY_PATH_ROOT}.{path}"] for path in identity.paths}


def incomplete_paths(values: Mapping[str, object]) -> list[str]:
    """The discriminator paths whose value cannot be part of a key: absent, null, or empty.

    Empty means ``""`` and the empty object and array; ``0`` and ``False`` are values.
    """
    return [path for path, value in values.items() if value is None or value == "" or value == {} or value == []]


def edge_lock_key(edge_type: str, from_id: object, to_id: object, values: Mapping[str, object]) -> str:
    """The advisory-lock key two writers of one relationship both take (``req-grid-edge-identity-4``).

    Derived through the node lock helper from the type, both endpoint ids and the discriminator
    values, so it is never authored a second time. A keyless type passes no values and locks on
    (type, source, target), which is what its duplicate check reads.
    """
    from tap_grid.natural_key import identity_lock_key

    key = identity_lock_key(
        f"edge:{edge_type}",
        {"from": str(from_id), "to": str(to_id), **{f"{IDENTITY_PATH_ROOT}.{p}": v for p, v in values.items()}},
    )
    if key is None:  # pragma: no cover - incomplete keys are refused before the lock is taken
        raise IncompleteEdgeKey(edge_type, [p for p, v in values.items() if v is None])
    return key


def find_live_edges(
    edge_type: str, from_id: object, to_id: object, values: Mapping[str, object], *, limit: int = 11
) -> list[Any]:
    """Live edges of ``edge_type`` between the two endpoint ids whose discriminators equal ``values``.

    Bound to the endpoints' entity ids (``req-grid-edge-identity-1``); served by the
    ``(from_entity, edge_type)`` index; discriminators compared typed, through the same search the
    node natural key uses. Capped: a caller names candidates, it does not enumerate a grid.
    """
    from tap_grid.models import Edge
    from tap_grid.natural_key import search

    # `objects` is the LiveManager: live rows only, so a tombstoned edge is never found.
    between = Edge.objects.filter(edge_type=edge_type, from_entity_id=from_id, to_entity_id=to_id)
    matching: Any = search(between, {f"{IDENTITY_PATH_ROOT}.{p}": v for p, v in values.items()}) if values else between
    return list(matching.order_by("entity_id")[:limit])
