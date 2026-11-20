"""Compound edges: a middle node plus ordinary binary edges (req-grid-edge-compound).

A compound edge records a fact a single binary edge cannot carry: a sender, a thing in the
middle with an identity of its own, and a receiver. It is stored as a NODE (the middle) and
ordinary edges, never as one edge with several ends (``req-grid-edge-nono`` still holds):

- the **source** edge, from the sender (always the initiator) to the middle node;
- the **destination** edge, from the middle node to the receiver;
- optionally a **carrier** edge, from the middle node to the compound edge one level down that
  carries it;
- optionally a **path** edge, from the middle node to each component the traffic passes
  through. A reference that never retires anything.

Each kind keeps its own middle-node type, owned by the plugin that owns the concept. Core adds
no base type, only this declaration on the middle node's model::

    COMPOUND_EDGE: ClassVar[dict[str, Any] | None] = {
        "source": "<KIND>_SOURCE__<plugin>",
        "destination": "<KIND>_DESTINATION__<plugin>",
        "carrier": None,                         # or "<KIND>_CARRIER__<plugin>"
        "path": "TRAVERSES_COMPONENT__<plugin>",  # or None
        "retires_with": ("source", "destination"),
    }

``retires_with`` names which ENDS retire the middle node when they retire (by a plain delete
or by a cascade); the delete walk reads it through :func:`dependents_index`. A carrier is not
an end: what a compound stack's vertical link does on delete is undecided, so naming it in
``retires_with`` is refused rather than guessed.

The declaration is a dict literal on purpose: ``tap.edge_declarations`` reads it statically at
author time (``validate_plugin``), and :func:`parse_compound_edge` is the one parser both the
class-creation guard and every runtime reader use, so a monkeypatched test declaration is held
to the same rules as a model's own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Every role a declaration may name, in the order the spec lists them.
ROLES: tuple[str, ...] = ("source", "destination", "carrier", "path")
#: The roles that are ends: only these may retire the middle node.
ENDS: tuple[str, ...] = ("source", "destination")
#: The suffix each per-kind role edge carries after its kind (the application_flow precedent).
ROLE_SUFFIX: dict[str, str] = {"source": "_SOURCE", "destination": "_DESTINATION", "carrier": "_CARRIER"}
#: The path role's one name: a real ``<ACTION>_<OBJECT>``, not a per-kind role name.
PATH_EDGE_NAME = "TRAVERSES_COMPONENT"
_KEYS = frozenset((*ROLES, "retires_with"))
_REQUIRED = frozenset({"source", "destination", "retires_with"})


class CompoundEdgeDeclarationError(ValueError):
    """A ``COMPOUND_EDGE`` declaration that does not fit the contract."""


@dataclass(frozen=True)
class CompoundEdge:
    """A parsed ``COMPOUND_EDGE`` declaration."""

    kind: str
    source: str
    destination: str
    carrier: str | None
    path: str | None
    retires_with: tuple[str, ...]

    def role_edges(self) -> dict[str, str]:
        """Role → edge type, for every role this declaration names."""
        roles = {"source": self.source, "destination": self.destination, "carrier": self.carrier, "path": self.path}
        return {role: edge for role, edge in roles.items() if edge is not None}

    def middle_is_target(self, role: str) -> bool:
        """True when the middle node is the TARGET of this role's edge (only the source edge
        points into the middle node; every other role points out of it)."""
        return role == "source"


def _split(edge_type: str) -> tuple[str, str]:
    """``REACHABILITY_SOURCE__aws_core`` → (``REACHABILITY_SOURCE``, ``aws_core``); a core edge has no owner."""
    head, sep, tail = edge_type.rpartition("__")
    return (head, tail) if sep and head and tail else (edge_type, "")


def parse_compound_edge(owner: str, value: Any) -> CompoundEdge | None:
    """Parse and check one ``COMPOUND_EDGE`` value; ``None`` means the type is not a middle node.

    The rules (``req-grid-edge-compound-2``, ``-4``): a mapping with exactly the known keys;
    ``source``, ``destination`` and ``retires_with`` present; every role a non-empty edge-type
    slug or ``None`` for the optional two; the role names follow the official exception to
    ``<ACTION>_<OBJECT>`` — ``<KIND>_SOURCE``, ``<KIND>_DESTINATION`` and ``<KIND>_CARRIER`` with
    one kind and one owning plugin, and the path role named ``TRAVERSES_COMPONENT``;
    ``retires_with`` a list of distinct ends.

    TAP-IMPLEMENTS: req-grid-edge-compound@b3210e951de5/c92d6997e59c (enforcement) — the one
        parser of the declaration, used at class creation and by every runtime reader.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CompoundEdgeDeclarationError(f"{owner}.COMPOUND_EDGE must be a dict or None, got {type(value).__name__}")
    unknown = sorted(set(value) - _KEYS)
    if unknown:
        raise CompoundEdgeDeclarationError(
            f"{owner}.COMPOUND_EDGE names unknown key(s) {unknown}; the roles are {list(ROLES)} plus 'retires_with'"
        )
    missing = sorted(_REQUIRED - set(value))
    if missing:
        raise CompoundEdgeDeclarationError(f"{owner}.COMPOUND_EDGE is missing {missing}")
    edges: dict[str, str | None] = {}
    for role in ROLES:
        edge = value.get(role)
        if edge is None and role in ("carrier", "path"):
            edges[role] = None
            continue
        if not isinstance(edge, str) or not edge:
            raise CompoundEdgeDeclarationError(f"{owner}.COMPOUND_EDGE[{role!r}] must be an edge-type slug")
        edges[role] = edge
    source_name, plugin = _split(str(edges["source"]))
    kind = source_name[: -len(ROLE_SUFFIX["source"])] if source_name.endswith(ROLE_SUFFIX["source"]) else ""
    if not kind or kind.startswith("_") or kind.endswith("_"):
        raise CompoundEdgeDeclarationError(
            f"{owner}.COMPOUND_EDGE['source'] is {edges['source']!r}; a source role edge is named <KIND>_SOURCE "
            "(req-grid-edge-compound-4)"
        )
    for role in ("destination", "carrier"):
        edge = edges[role]
        if edge is None:
            continue
        name, edge_plugin = _split(edge)
        if name != kind + ROLE_SUFFIX[role] or edge_plugin != plugin:
            raise CompoundEdgeDeclarationError(
                f"{owner}.COMPOUND_EDGE[{role!r}] is {edge!r}; with source {edges['source']!r} it must be "
                f"{kind}{ROLE_SUFFIX[role]}{'__' + plugin if plugin else ''}: one kind, one owning plugin "
                "(req-grid-edge-compound-4)"
            )
    if edges["path"] is not None and _split(edges["path"])[0] != PATH_EDGE_NAME:
        raise CompoundEdgeDeclarationError(
            f"{owner}.COMPOUND_EDGE['path'] is {edges['path']!r}; the path role edge is named {PATH_EDGE_NAME} "
            "(req-grid-edge-compound-4)"
        )
    retires = value["retires_with"]
    if isinstance(retires, str) or not isinstance(retires, (list, tuple)):
        raise CompoundEdgeDeclarationError(
            f"{owner}.COMPOUND_EDGE['retires_with'] must be a list of ends drawn from {list(ENDS)}"
        )
    bad = [end for end in retires if end not in ENDS]
    if bad:
        raise CompoundEdgeDeclarationError(
            f"{owner}.COMPOUND_EDGE['retires_with'] names {bad}; only an end ({list(ENDS)}) retires a middle node. "
            "What a carrier does on delete is undecided (req-grid-edge-compound-5)"
        )
    if len(set(retires)) != len(retires):
        raise CompoundEdgeDeclarationError(f"{owner}.COMPOUND_EDGE['retires_with'] repeats an end")
    return CompoundEdge(
        kind=kind,
        source=str(edges["source"]),
        destination=str(edges["destination"]),
        carrier=edges["carrier"],
        path=edges["path"],
        retires_with=tuple(retires),
    )


def compound_edge_of(model_cls: type) -> CompoundEdge | None:
    """The parsed declaration of a model class, or ``None`` when it is not a middle node."""
    return parse_compound_edge(getattr(model_cls, "__name__", "model"), getattr(model_cls, "COMPOUND_EDGE", None))


@dataclass(frozen=True)
class DependentsIndex:
    """Which edges retire which middle nodes, built from the registered declarations.

    ``by_source[edge_type]`` holds the middle types that retire when the node at the FROM end of
    one of their source edges retires; ``by_destination[edge_type]`` those that retire when the
    node at the TO end of one of their destination edges retires. A role absent from a type's
    ``retires_with`` is in neither map: its edge ends with its endpoint and the middle node stays.
    """

    by_source: Mapping[str, frozenset[str]]
    by_destination: Mapping[str, frozenset[str]]

    def __bool__(self) -> bool:
        return bool(self.by_source or self.by_destination)


EMPTY_INDEX = DependentsIndex(by_source={}, by_destination={})


def compound_types() -> dict[str, CompoundEdge]:
    """Every registered middle-node type and its declaration, in slug order."""
    from tap_grid.registry import get_model_class, list_entity_types

    out: dict[str, CompoundEdge] = {}
    for entity_type in sorted(list_entity_types()):
        declared = compound_edge_of(get_model_class(entity_type))
        if declared is not None:
            out[entity_type] = declared
    return out


def dependents_index() -> DependentsIndex:
    """The delete walk's map from a retiring end's edge to the middle types it retires.

    Read from the registry on each delete rather than cached at boot, so a declaration set in a
    test (the corpus monkeypatches its fixture types) is the one the walk follows; the cost is
    one pass over the registered types, and none when no type is a middle node. The walk that
    reads it is ``tap_grid.services._impl._discover_closure`` (req-grid-edge-compound-5).
    """
    by_source: dict[str, set[str]] = {}
    by_destination: dict[str, set[str]] = {}
    for entity_type, declared in compound_types().items():
        if "source" in declared.retires_with:
            by_source.setdefault(declared.source, set()).add(entity_type)
        if "destination" in declared.retires_with:
            by_destination.setdefault(declared.destination, set()).add(entity_type)
    if not by_source and not by_destination:
        return EMPTY_INDEX
    return DependentsIndex(
        by_source={k: frozenset(v) for k, v in by_source.items()},
        by_destination={k: frozenset(v) for k, v in by_destination.items()},
    )
