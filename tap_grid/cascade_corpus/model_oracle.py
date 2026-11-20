"""A reference model of the contained cascade, independent of the service layer.

Pure Python over a scenario's declared graph — no ORM, no Django, and no queue: the
closure is a set-based reachability fixed point, and everything the implementation's
breadth-first walk makes order-dependent (which parent discovered a shared child, which
endpoint ended an edge) is stated as the SET of legitimate answers rather than one run's
choice (Issue# 586 - tap). The rules, as the spec words them
(``req-grid-service-delete-cascade``):

- the root is checked before anything: a blocked root is refused, nothing discovered;
- children are the live far nodes of a node's DECLARED containment edges; an undeclared
  edge type is a reference and is never followed (-2); an ended edge is never followed;
- discovery is what the cap bounds, the root counts, a node counts once (-11, -13);
- a blocked node anywhere in the closure refuses the whole cascade (-4);
- a scenario in which BOTH a block and an overflow are reachable is refused as
  order-dependent — which refusal the implementation reports depends on which it meets
  first, and the corpus does not author coin flips;
- every live edge incident to a retired node ends, once, whatever its type; the node it
  is a consequence of is whichever endpoint retired first — the shallower one, either at
  equal depth;
- a cascaded node's consequence_of is a containing parent one level nearer the root —
  any of them, because sibling order within a level is the database's, not the spec's.

Compound edges (``req-grid-edge-compound-5``, family ``compound``): a middle node whose type
declares ``retires_with`` an end retires when that end does — the end at the FROM side of a
live source-role edge into it, or the TO side of a live destination-role edge out of it —
by a plain delete or a cascade, as one more relation the same level-ordered walk follows.
A plain delete walks that relation only; a walk that retired anything beyond its root
records its ended edges as a cascade does. Reconcile's contradiction check reads
containment alone (``-7``).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

BLOCKED_CODE = "unsupported_operation"
CAP_CODE = "cascade_closure_too_large"
INVALID_REASON_CODE = "invalid_reason"
INVALID_CASCADE_CODE = "validation_error"
DELETE_REASONS = frozenset(
    {
        "dropped_from_observation",
        "scope_withdrawn",
        "cascaded",
        "resolved",
        "operator",
        "grift_import",
        "authority",
        "unspecified",
    }
)
CASCADE_MODES = frozenset({"none", "contained"})
#: Keys the walk writes itself on every cascaded record; an inherited value never overrides them.
RESERVED_KEYS = frozenset({"reason", "consequence_of", "cascade_root", "root_reason", "compound_end"})
#: The relation that brought a node into the closure when it was not containment.
VIA_CONTAINMENT = "containment"


class AmbiguousScenario(ValueError):
    """The outcome would depend on the order the walk meets siblings."""


@dataclass(frozen=True)
class Graph:
    node_type: dict[str, str]
    edges: tuple[tuple[str, str, str, str], ...]  # (ref, from, to, type) in creation order
    containment: dict[str, tuple[str, ...]]
    blocked_types: frozenset[str]
    pre_retired: frozenset[str]  # node refs tombstoned before the operation
    pre_retired_edges: frozenset[str] = frozenset()  # edge refs ended before the operation
    #: middle-node type → (source edge type, destination edge type, retires_with)
    compound: dict[str, tuple[str, str, tuple[str, ...]]] = field(default_factory=dict)


@dataclass
class Outcome:
    outcome: str  # success | refused
    error_code: str | None = None
    retired_nodes: list[str] = field(default_factory=list)
    retired_edges: list[str] = field(default_factory=list)
    root_reason: str | None = None
    #: node ref → the reason its delete event carries
    node_reason: dict[str, str] = field(default_factory=dict)
    #: node ref → every parent that may legitimately have discovered it (empty for the root)
    node_parents: dict[str, frozenset[str]] = field(default_factory=dict)
    #: edge ref → every endpoint that may legitimately have ended it
    edge_parents: dict[str, frozenset[str]] = field(default_factory=dict)
    #: node ref → how it may have entered the closure: "containment", "source" or "destination"
    node_via: dict[str, frozenset[str]] = field(default_factory=dict)
    #: the delete walked (a contained cascade, or a plain delete that retired a middle node):
    #: its ended edges carry unlink records
    walked: bool = False
    #: reconcile only: the one candidate the scenario yields, and the contradiction on it
    candidate: str | None = None
    contradiction: dict[str, Any] | None = None


def _live_edges(graph: Graph, live: set[str]) -> list[tuple[str, str, str, str]]:
    return [e for e in graph.edges if e[1] in live and e[2] in live and e[0] not in graph.pre_retired_edges]


def _children(
    graph: Graph, node: str, edges: list[tuple[str, str, str, str]], *, contained: bool, compound: bool
) -> list[tuple[str, str]]:
    """``(child, via)`` for every node the walk takes with ``node``: its declared contained
    children (when ``contained``) and the middle nodes it retires as a declared end (when
    ``compound``)."""
    out: list[tuple[str, str]] = []
    declared = set(graph.containment.get(graph.node_type[node], ())) if contained else set()
    for _, a, b, edge_type in edges:
        if a == node and edge_type in declared:
            out.append((b, VIA_CONTAINMENT))
        if not compound:
            continue
        if a == node and graph.node_type[b] in graph.compound:
            source, _dest, retires = graph.compound[graph.node_type[b]]
            if edge_type == source and "source" in retires:
                out.append((b, "source"))
        if b == node and graph.node_type[a] in graph.compound:
            _source, dest, retires = graph.compound[graph.node_type[a]]
            if edge_type == dest and "destination" in retires:
                out.append((a, "destination"))
    return out


def _depths(
    graph: Graph, root: str, live: set[str], *, contained: bool = True, compound: bool = True
) -> dict[str, int]:
    """Breadth-first distance from the root over the walk's relations among live nodes.
    Level order is the one thing the walk fixes; within a level, nothing is fixed."""
    edges = _live_edges(graph, live)
    depth = {root: 0}
    frontier: deque[str] = deque([root])
    while frontier:
        node = frontier.popleft()
        for child, _via in _children(graph, node, edges, contained=contained, compound=compound):
            if child not in depth:
                depth[child] = depth[node] + 1
                frontier.append(child)
    return depth


RECONCILE_REASON = "dropped_from_observation"


def surface_edge_type(graph: Graph, target: str) -> str | None:
    """The one containment edge type a reconcile scenario's surface fans out through: the type
    of the target's first containment edge in creation order, else the first declared."""
    declared = graph.containment.get(graph.node_type[target], ())
    for _ref, frm, _to, edge_type in graph.edges:
        if frm == target and edge_type in declared:
            return edge_type
    return declared[0] if declared else None


def reconcile(
    graph: Graph, target: str, *, observed: Iterable[str], dropped: Iterable[str], cap: int = 5000
) -> Outcome:
    """The outcome of the reconcile verb on a run that observed ``target`` and ``observed``, with
    the source answering ``dropped`` as gone (Issue# 662 - tap). Exactly one child of the target
    may be unobserved — the candidate — so the answer is one entry's worth.

    The order is the verb's: the candidate record refuses a contradiction before any probe
    (a node under the candidate this run observed, or a closure over the cap:
    req-grid-reconcile-candidates-6); then a candidate the source reports gone retires with a
    contained cascade carrying reason ``dropped_from_observation``; anything else is present.
    """
    seen, gone = set(observed), set(dropped)
    live = {n for n in graph.node_type if n not in graph.pre_retired}
    if target not in live:
        raise AmbiguousScenario(f"reconcile target {target!r} is not live")
    edge_type = surface_edge_type(graph, target)
    children = sorted(
        {
            to
            for ref, frm, to, et in graph.edges
            if frm == target and et == edge_type and to in live and ref not in graph.pre_retired_edges
        }
    )
    candidates = [c for c in children if c not in seen]
    if len(candidates) != 1:
        raise AmbiguousScenario(f"a reconcile scenario holds exactly one candidate; {target!r} yields {candidates}")
    [candidate] = candidates
    depth = _depths(graph, candidate, live, compound=False)  # containment alone (req-grid-edge-compound-7)
    if len(depth) > cap:
        return Outcome(
            "contradicted",
            None,
            candidate=candidate,
            contradiction={"kind": "closure_unknown", "observed_descendants": []},
        )
    hits = sorted(n for n in depth if n != candidate and n in seen)
    if hits:
        return Outcome(
            "contradicted",
            None,
            candidate=candidate,
            contradiction={"kind": "observed_descendants", "observed_descendants": hits},
        )
    if candidate not in gone:
        return Outcome("not_applicable", None, candidate=candidate)
    out = cascade(graph, candidate, mode="contained", reason=RECONCILE_REASON, cap=cap)
    out.candidate = candidate
    if out.outcome == "success":
        out.outcome = "applied"
    return out


def cascade(graph: Graph, target: str, *, mode: str = "none", reason: str | None = None, cap: int = 5000) -> Outcome:
    """The outcome of ``delete_node(target, cascade=mode, reason=reason)`` under ``cap``."""
    if mode not in CASCADE_MODES:
        return Outcome("refused", INVALID_CASCADE_CODE)
    effective_reason = "unspecified" if reason is None else reason
    if effective_reason not in DELETE_REASONS:
        return Outcome("refused", INVALID_REASON_CODE)
    if graph.node_type[target] in graph.blocked_types:
        return Outcome("refused", BLOCKED_CODE)

    live = {n for n in graph.node_type if n not in graph.pre_retired}
    if target not in live:
        # Repeat delete of a tombstoned target: idempotent and silent (tombstone-6).
        return Outcome("success", None, [], [], effective_reason)

    depth = _depths(graph, target, live, contained=mode == "contained")
    walked = mode == "contained" or len(depth) > 1
    if walked:
        blocked = [n for n in depth if graph.node_type[n] in graph.blocked_types]
        overflow = len(depth) > cap
        if blocked and overflow:
            raise AmbiguousScenario(
                f"both a blocked node ({sorted(blocked)}) and an over-cap closure ({len(depth)} > {cap}) are "
                "reachable; which refusal comes first depends on sibling order"
            )
        if overflow:
            return Outcome("refused", CAP_CODE)
        if blocked:
            return Outcome("refused", BLOCKED_CODE)

    out = Outcome("success", None, root_reason=effective_reason, walked=walked)
    retired = sorted(depth, key=lambda n: (depth[n], n))
    out.retired_nodes = retired
    out.node_reason = {n: (effective_reason if n == target else "cascaded") for n in retired}
    edges = _live_edges(graph, live)
    parents: dict[str, set[str]] = {}
    vias: dict[str, set[str]] = {}
    for parent in retired:
        for child, via in _children(graph, parent, edges, contained=mode == "contained", compound=True):
            if child in depth and depth[child] == depth[parent] + 1:
                parents.setdefault(child, set()).add(parent)
                vias.setdefault(child, set()).add(via)
    for node in retired:
        out.node_parents[node] = frozenset() if node == target else frozenset(parents.get(node, ()))
        out.node_via[node] = frozenset() if node == target else frozenset(vias.get(node, ()))
    closure = set(depth)
    for ref, a, b, _ in edges:
        if a in closure or b in closure:
            out.retired_edges.append(ref)
            inside = [n for n in (a, b) if n in closure]
            shallowest = min(depth[n] for n in inside)
            out.edge_parents[ref] = frozenset(n for n in inside if depth[n] == shallowest)
    return out
