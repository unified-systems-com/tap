"""A reference model of the contained cascade, independent of the service layer.

Pure Python over a scenario's declared graph — no ORM, no Django. It restates the rules
of ``req-grid-service-delete-cascade`` as the spec words them and computes the outcome
every hand-authored expectation must agree with:

- the root is checked before anything (a blocked root is refused, nothing discovered);
- discovery is what the cap bounds: a node counts the moment it is found, root included,
  and the walk is refused the instant discovery exceeds the cap (-11);
- children are the live far nodes of the node's DECLARED containment edges; an undeclared
  edge type is a reference and is never followed (-2); a node already discovered is not
  discovered again (-13);
- the walk is breadth-first; a node's children are discovered before that node is
  retired; a blocked node is refused when the walk reaches it, after its children were
  discovered (that is the order the implementation has, and the loader rejects any
  scenario whose outcome would depend on sibling order);
- every edge incident to a retired node ends, whatever its type; an edge ends once;
- refusal anywhere means nothing is written (-3, -4).

It is a model, not a copy: it knows nothing about queues, LIMITs or SQL. When it and the
implementation disagree, one of them is wrong, and the corpus says so out loud.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BLOCKED_CODE = "unsupported_operation"
CAP_CODE = "cascade_closure_too_large"
INVALID_REASON_CODE = "invalid_reason"
INVALID_CASCADE_CODE = "validation_error"
DELETE_REASONS = frozenset(
    {"dropped_from_observation", "scope_withdrawn", "cascaded", "resolved", "operator", "grift_import", "unspecified"}
)
CASCADE_MODES = frozenset({"none", "contained"})


@dataclass(frozen=True)
class Graph:
    node_type: dict[str, str]
    edges: tuple[tuple[str, str, str, str], ...]  # (ref, from, to, type) in creation order
    containment: dict[str, tuple[str, ...]]
    blocked_types: frozenset[str]
    pre_retired: frozenset[str]

    def out_edges(self, node: str, *, reverse: bool = False) -> list[tuple[str, str, str, str]]:
        found = [e for e in self.edges if e[1] == node]
        return list(reversed(found)) if reverse else found

    def incident_edges(self, node: str) -> list[str]:
        return [e[0] for e in self.edges if e[1] == node or e[2] == node]


@dataclass
class Outcome:
    outcome: str  # success | refused
    error_code: str | None = None
    retired_nodes: list[str] = field(default_factory=list)
    retired_edges: list[str] = field(default_factory=list)
    # ref → (reason, consequence_of or None)
    node_events: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    edge_events: dict[str, tuple[str, str]] = field(default_factory=dict)


def _children(graph: Graph, node: str, live: set[str], *, reverse: bool) -> list[str]:
    declared = set(graph.containment.get(graph.node_type[node], ()))
    seen: list[str] = []
    for _, _, to, edge_type in graph.out_edges(node, reverse=reverse):
        if edge_type in declared and to in live and to not in seen:
            seen.append(to)
    return seen


def cascade(
    graph: Graph,
    target: str,
    *,
    mode: str = "none",
    reason: str | None = None,
    cap: int = 5000,
    reverse_siblings: bool = False,
) -> Outcome:
    """The outcome of ``delete_node(target, cascade=mode, reason=reason)`` under ``cap``."""
    if mode not in CASCADE_MODES:
        return Outcome("refused", INVALID_CASCADE_CODE)
    effective_reason = "unspecified" if reason is None else reason
    if effective_reason not in DELETE_REASONS:
        return Outcome("refused", INVALID_REASON_CODE)
    if graph.node_type[target] in graph.blocked_types:
        return Outcome("refused", BLOCKED_CODE)

    live = {n for n in graph.node_type if n not in graph.pre_retired}
    live_edges = [e for e in graph.edges if e[1] in live and e[2] in live]
    if target not in live:
        # Pending Issue# 575 - tap: a repeat delete is idempotent and silent.
        return Outcome("success", None, [], [], {}, {})

    out = Outcome("success")
    ended: set[str] = set()

    def retire(node: str, event: tuple[str, str | None], consequence: str | None) -> None:
        out.retired_nodes.append(node)
        out.node_events[node] = event
        for ref, a, b, _ in live_edges:
            if ref not in ended and (a == node or b == node):
                ended.add(ref)
                out.retired_edges.append(ref)
                if mode == "contained":
                    out.edge_events[ref] = ("cascaded", consequence or node)

    if mode == "none":
        retire(target, (effective_reason, None), None)
        return out

    discovered = {target}
    children = _children(graph, target, live, reverse=reverse_siblings)
    discovered.update(children)
    if len(discovered) > cap:
        return Outcome("refused", CAP_CODE)
    retire(target, (effective_reason, None), target)
    queue: list[tuple[str, str]] = [(c, target) for c in children]
    visited = {target}
    while queue:
        node, parent = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        grandchildren = [g for g in _children(graph, node, live, reverse=reverse_siblings) if g not in discovered]
        discovered.update(grandchildren)
        if len(discovered) > cap:
            return Outcome("refused", CAP_CODE)
        if graph.node_type[node] in graph.blocked_types:
            return Outcome("refused", BLOCKED_CODE)
        retire(node, ("cascaded", parent), node)
        queue.extend((g, node) for g in grandchildren)
    return out
