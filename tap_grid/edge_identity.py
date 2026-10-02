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
key's path grammar (``split_path``, beside the node declaration sentinel), read through the same parser, so
edge and node paths cannot drift: ``"scope"`` is ``properties.scope``, ``"rule.type"`` is
``properties.rule.type``.

One declaration per type and no merge: edge-type constraints union across apps, but two
declarations disagreeing about what makes an edge the same edge would be silent drift, so a
second registration is a configuration error (``req-grid-edge-identity-declaration-4``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from tap.registry import Registry
from tap_grid.edge_identity_shape import (
    IDENTITY_PATH_ROOT,
    Discriminator,
    EdgeIdentity,
    EdgeIdentityError,
    check_edge_identity,
)

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

#: Fail-closed switch for ``req-grid-edge-identity-6``: a ref-addressed edge of a type with no
#: identity declaration. False is warn mode (ruled 2026-10-02): the edge is created as before,
#: with no lookup, and the import reports a warning naming the type, so producers can declare
#: their types before anything refuses them. The flip to True is Issue# 928 - tap. Tests may
#: monkeypatch it to exercise both paths.
ENFORCE_EDGE_IDENTITY_DECLARED: bool = False


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


_edge_identity_registry: Registry[EdgeIdentity] = Registry(
    "edge_identities",
    title="Edge Identity Declarations",
    description=(
        "Per edge type: the discriminators that, beside the type and the two endpoints, identify a "
        "relationship (empty for the plain key), or the reason the type is keyless "
        "(req-grid-edge-identity-declaration). One declaration per type; never merged."
    ),
)


def parse_edge_identity(edge_type: str, raw: Any, *, property_schema: Mapping[str, Any] | None = None) -> EdgeIdentity:
    """Read one ``identity`` member, raising a configuration error for anything malformed.

    The checks are :func:`tap_grid.edge_identity_shape.check_edge_identity`'s, which runs without
    Django for plugin conformance validation; here a failure is a configuration error, because a
    declaration that does not hold is a definition boot must refuse.

    Raises:
        ImproperlyConfigured: The declaration is malformed, or a discriminator does not resolve.
    """
    try:
        return check_edge_identity(edge_type, raw, property_schema=property_schema)
    except EdgeIdentityError as exc:
        raise ImproperlyConfigured(str(exc)) from exc


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
    (type, source, target), which is what its duplicate check reads. Each endpoint id is
    canonicalised first: ``ABC…``, ``abc…`` and the hyphenless form are one entity to PostgreSQL,
    so they must be one lock, or two writers spelling one endpoint differently would each take
    their own lock and both create the edge.

    Raises:
        ValueError: An endpoint id is not a UUID.
    """
    from tap_grid.natural_key import identity_lock_key

    key = identity_lock_key(
        f"edge:{edge_type}",
        {
            "from": str(uuid.UUID(str(from_id))),
            "to": str(uuid.UUID(str(to_id))),
            **{f"{IDENTITY_PATH_ROOT}.{p}": v for p, v in values.items()},
        },
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
