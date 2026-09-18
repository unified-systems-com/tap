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
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

BLOCKED_CODE = "unsupported_operation"
CAP_CODE = "cascade_closure_too_large"
INVALID_REASON_CODE = "invalid_reason"
INVALID_CASCADE_CODE = "validation_error"
DELETE_REASONS = frozenset(
    {"dropped_from_observation", "scope_withdrawn", "cascaded", "resolved", "operator", "grift_import", "unspecified"}
)
CASCADE_MODES = frozenset({"none", "contained"})
#: Keys the walk writes itself on every cascaded record; an inherited value never overrides them.
RESERVED_KEYS = frozenset({"reason", "consequence_of", "cascade_root", "root_reason"})


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


def _live_edges(graph: Graph, live: set[str]) -> list[tuple[str, str, str, str]]:
    return [e for e in graph.edges if e[1] in live and e[2] in live and e[0] not in graph.pre_retired_edges]


def _depths(graph: Graph, root: str, live: set[str]) -> dict[str, int]:
    """Breadth-first distance from the root over declared containment among live nodes.
    Level order is the one thing the walk fixes; within a level, nothing is fixed."""
    edges = _live_edges(graph, live)
    depth = {root: 0}
    frontier: deque[str] = deque([root])
    while frontier:
        node = frontier.popleft()
        declared = set(graph.containment.get(graph.node_type[node], ()))
        for _, a, b, edge_type in edges:
            if a == node and edge_type in declared and b not in depth:
                depth[b] = depth[node] + 1
                frontier.append(b)
    return depth


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

    if mode == "none":
        depth = {target: 0}
    else:
        depth = _depths(graph, target, live)
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

    out = Outcome("success", None, root_reason=effective_reason)
    retired = sorted(depth, key=lambda n: (depth[n], n))
    out.retired_nodes = retired
    out.node_reason = {n: (effective_reason if n == target else "cascaded") for n in retired}
    edges = _live_edges(graph, live)
    for node in retired:
        if node == target:
            out.node_parents[node] = frozenset()
            continue
        declared_parents = {
            a
            for _, a, b, edge_type in edges
            if b == node and a in depth and edge_type in set(graph.containment.get(graph.node_type[a], ()))
        }
        out.node_parents[node] = frozenset(p for p in declared_parents if depth[p] == depth[node] - 1)
    closure = set(depth)
    for ref, a, b, _ in edges:
        if a in closure or b in closure:
            out.retired_edges.append(ref)
            inside = [n for n in (a, b) if n in closure]
            shallowest = min(depth[n] for n in inside)
            out.edge_parents[ref] = frozenset(n for n in inside if depth[n] == shallowest)
    return out
