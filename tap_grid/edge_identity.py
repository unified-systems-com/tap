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
    "IDENTITY_PATH_ROOT",
    "Discriminator",
    "EdgeIdentity",
    "get_edge_identity",
    "list_declared_edge_types",
    "parse_edge_identity",
    "register_edge_identity",
]

#: The Edge column every discriminator path lives under: a declared ``"scope"`` is read as the
#: node-grammar path ``"properties.scope"``.
IDENTITY_PATH_ROOT: Final[str] = "properties"

_IDENTITY_MEMBERS: Final[frozenset[str]] = frozenset({"discriminators", "keyless"})
_DISCRIMINATOR_MEMBERS: Final[frozenset[str]] = frozenset({"path", "description"})
_KEYLESS_MEMBERS: Final[frozenset[str]] = frozenset({"reason"})


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

    TAP-IMPLEMENTS: req-grid-edge-identity-declaration@e48348aed4cd/08b088116dac (derivation) — the
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

    TAP-IMPLEMENTS: req-grid-edge-identity-declaration@e48348aed4cd/01fdbee21b58 (enforcement) — the
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
