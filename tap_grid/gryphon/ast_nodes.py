"""Frozen dataclasses representing the TAP gryphon AST.

All nodes are immutable. The transformer in parser.py builds these from the lark parse tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Field path
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DotStep:
    """Access a named field: `variable.field`."""

    name: str


@dataclass(frozen=True)
class KeyStep:
    """Access a JSON key via bracket notation: `variable["key"]`."""

    key: str


@dataclass(frozen=True)
class IndexStep:
    """Access an array element by position: `variable.field[0]`."""

    index: int


@dataclass(frozen=True)
class WildcardStep:
    """Array wildcard: `variable.field[*]` — match any array member."""


FieldStep = DotStep | KeyStep | IndexStep | WildcardStep


@dataclass(frozen=True)
class FieldPath:
    """A dot/bracket path rooted at a named variable.

    Examples::
        hub.entity_id            → FieldPath("hub", [DotStep("entity_id")])
        node.dimensions["tap.g"] → FieldPath("node", [DotStep("dimensions"), KeyStep("tap.g")])
        node.aliases[*].name     → FieldPath("node", [DotStep("aliases"), WildcardStep(), DotStep("name")])
    """

    variable: str
    steps: tuple[FieldStep, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamRef:
    """A runtime input variable reference: `$entity_id`."""

    name: str


# Scalar values that may appear in predicates and inline property maps.
# str | int | float | bool | None are plain Python types; ParamRef is TAP-specific.
GryphonValue = str | int | float | bool | None | ParamRef


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodePattern:
    """A node pattern element: `(variable:label {props})`."""

    variable: str | None
    label: str | None
    inline_props: dict[str, GryphonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgePattern:
    """An edge pattern element: `-[variable:TYPE*min..max {props}]->`."""

    variable: str | None
    edge_type: str | None
    direction: Literal["out", "in", "any"]
    min_hops: int = 1
    max_hops: int = 1
    inline_props: dict[str, GryphonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class PathPattern:
    """A single chain of nodes and edges in a MATCH clause.

    nodes and edges alternate: nodes[0] -edges[0]-> nodes[1] -edges[1]-> nodes[2] ...
    len(nodes) == len(edges) + 1 is always true.
    """

    nodes: tuple[NodePattern, ...]
    edges: tuple[EdgePattern, ...]


# ---------------------------------------------------------------------------
# WHERE predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """A single field-op-value predicate: `hub.entity_id = $entity_id`.

    `op` covers the scalar comparison operators, the substring operators
    `starts_with` / `ends_with` / `contains` (parsed from the case-insensitive
    `STARTS_WITH` / `ENDS_WITH` / `CONTAINS` keywords), and `regex` (parsed
    from the `=~` operator — anchored Postgres POSIX regex match, see
    req-grid-traversal-lang-regex). All are structurally `field_path op value`;
    the substring and regex operators expect a string value.
    """

    field_path: FieldPath
    op: Literal["=", "!=", "<", ">", "<=", ">=", "starts_with", "ends_with", "contains", "regex"]
    value: GryphonValue


@dataclass(frozen=True)
class InComparison:
    """A membership predicate: `n.kind IN ['neighbor', 'island']`.

    TAP-IMPLEMENTS: req-grid-traversal-lang-in@807260dd21df/defb9da4fcab (derivation) — the IN
        list-membership predicate's semantics live on this node.

    True when the field value equals one of `values`. `values` may mix literals
    and `ParamRef`s. An empty `values` matches nothing; a `None` element never
    matches (NULL has no defined equality).

    .. tap:capability:: Gryphon IN-list membership
       :id: cap-grid-gryphon-in-list
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:in_lists-in-matches-rows-whose-data-lane-value-is-a-listed-member

       ``WHERE field IN [v, ...]`` tests a field against a list of values
       (literals or ``$param``s). An empty list matches nothing; a ``null``
       element never matches.

       Example::

          MATCH (n:grid_fixtures__node) WHERE n.data.kind IN ["neighbor"]
          RETURN n.entity_id AS id ORDER BY id
    """

    field_path: FieldPath
    values: tuple[GryphonValue, ...]


@dataclass(frozen=True)
class IsNullComparison:
    """A null-existence predicate: `field IS NULL` or `field IS NOT NULL`.

    TAP-IMPLEMENTS: req-grid-traversal-lang-is-null@82030a287c51/db6d0fb35312 (derivation) — the
        IS [NOT] NULL predicate's semantics live on this node.

    True when the field value is NULL (`negated=False`) or non-NULL
    (`negated=True`). Lowers to Django's ``__isnull=True``/``=False`` lookup
    (SQL `IS NULL` / `IS NOT NULL`). Defends envelope ORDER BY DESC queries
    from a NULL sort-field row silently winning the cap.

    .. tap:capability:: Gryphon IS NULL / IS NOT NULL
       :id: cap-grid-gryphon-is-null
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:is_null-defensive-latest-emission-filters-null-sort-field-before-order-by-desc

       ``WHERE field IS NULL`` and ``WHERE field IS NOT NULL`` test a field
       for null-existence. The defensive shape for envelope ORDER BY DESC
       queries that must not pick up a NULL-sort-field row.

       Example::

          MATCH (a:compliance_artifact)
          WHERE a.data.kind = $kind AND a.data.fetched_at IS NOT NULL
          ORDER BY a.data.fetched_at DESC LIMIT 1
    """

    field_path: FieldPath
    negated: bool


@dataclass(frozen=True)
class ObservationComparison:
    """An observation-semantic predicate: `field IS KNOWN` or `field IS UNKNOWN`.

    TAP-IMPLEMENTS: req-grid-traversal-lang-observation@716135c5bc48/a5db8f2b48b3 (derivation) —
        the IS KNOWN / IS UNKNOWN observation-axis predicate lives on this node.

    The convention's null axis (spec-grid-node.md req-grid-node-observation)
    surfaced as intent-revealing keywords: `IS UNKNOWN` tests for unobserved
    (`kind="unknown"`), `IS KNOWN` tests for observed-of-any-kind
    (`kind="known"`, inclusive of observed-empty). Both lower to Django's
    `__isnull` lookup — `unknown` → `__isnull=True`, `known` → `__isnull=False`
    — and are type-agnostic (the null axis applies to every field type).

    `IS EMPTY` (observed-empty) is deliberately NOT here: "empty" is a
    container-type concept (`""`/`[]`/`{}`), undefined for scalar columns, so it
    requires field-type / `x-tap-absence.empty_is_meaningful`-aware lowering
    rather than a `__isnull` test. Reserved as `kind` could grow an "empty"
    member when that lands. See req-grid-traversal-lang-observation.

    .. tap:capability:: Gryphon IS KNOWN / IS UNKNOWN
       :id: cap-grid-gryphon-observation
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:observation-is-unknown-returns-only-the-unobserved-null-observed-at-row

       ``WHERE field IS UNKNOWN`` selects unobserved (null) fields and
       ``IS KNOWN`` selects observed (non-null) fields — the convention's
       observed-vs-unobserved axis as first-class query vocabulary, stable as
       the underlying representation evolves.

       Example::

          MATCH (n:network_interface) WHERE n.data.mac_address IS UNKNOWN
          RETURN n.entity_id AS id ORDER BY id
    """

    field_path: FieldPath
    kind: Literal["known", "unknown"]


@dataclass(frozen=True)
class AndPred:
    """Conjunction: both operands must be true."""

    left: Predicate
    right: Predicate


@dataclass(frozen=True)
class OrPred:
    """Disjunction: either operand must be true."""

    left: Predicate
    right: Predicate


@dataclass(frozen=True)
class NotPred:
    """Negation: operand must be false."""

    operand: Predicate


Predicate = Comparison | InComparison | IsNullComparison | ObservationComparison | AndPred | OrPred | NotPred


# ---------------------------------------------------------------------------
# Clauses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchClause:
    """A MATCH clause with optional path variable and one or more patterns."""

    path_var: str | None
    patterns: tuple[PathPattern, ...]


@dataclass(frozen=True)
class OptionalMatchClause:
    """An OPTIONAL MATCH clause — left-outer-join semantics.

    Structurally like a MatchClause's pattern list, but a non-match leaves the
    optional variables unbound rather than dropping the mandatory row. No path
    variable in v0.
    """

    patterns: tuple[PathPattern, ...]


@dataclass(frozen=True)
class WhereClause:
    """A WHERE clause with its root predicate."""

    predicate: Predicate


@dataclass(frozen=True)
class ReturnItem:
    """A RETURN item that projects a field path: `field_path [AS alias]`."""

    path: FieldPath
    alias: str | None


@dataclass(frozen=True)
class AggregateCall:
    """An aggregate function call in a RETURN projection.

    `function` is the aggregate name (currently only `"count"` is supported).
    `argument` is a FieldPath. A bare `COUNT(var)` parses as a FieldPath with
    no steps; `COUNT(var.field)` parses as a FieldPath with one or more steps.
    """

    function: Literal["count"]
    argument: FieldPath


@dataclass(frozen=True)
class AggregateReturnItem:
    """A RETURN item that's an aggregate call; alias is required."""

    aggregate: AggregateCall
    alias: str


@dataclass(frozen=True)
class ReturnClause:
    """A RETURN clause.

    items=None means the RETURN was omitted — TAP returns a graph envelope by default.
    items=[...] carries the projection list; entries may be field projections
    (ReturnItem) or aggregate projections (AggregateReturnItem).
    """

    items: tuple[ReturnItem | AggregateReturnItem, ...] | None


@dataclass(frozen=True)
class OrderByItem:
    """A single ORDER BY term.

    `path` carries the parsed term as a `FieldPath`. In row-projection mode it
    degenerates to a bare variable name (zero steps) that the executor looks up
    against the RETURN aliases — preserving the original `ORDER BY <alias>`
    surface. In envelope mode it carries a full field path
    (`ORDER BY n.data.fetched_at DESC`) that the executor resolves through the
    same type-scan ORM-path machinery used for WHERE comparisons
    (`req-grid-gryphon-order-by-envelope`).
    """

    path: FieldPath
    descending: bool = False

    @property
    def key(self) -> str:
        """The key for row-projection-mode RETURN-alias lookup.

        For a bare-name term (`ORDER BY label`) this is the variable name
        (`label`) — the original surface. For a field-path term
        (`ORDER BY n.data.fetched_at`) this is the last dot-step name
        (`fetched_at`), matching the `_return_item_key` convention used to
        derive default aliases for unaliased RETURN items. The aggregation and
        type-scan projection paths use this; the envelope path uses `path`.
        """
        steps = self.path.steps
        if not steps:
            return self.path.variable
        last = steps[-1]
        if isinstance(last, DotStep):
            return last.name
        return self.path.variable


@dataclass(frozen=True)
class OrderByClause:
    """An ORDER BY clause: one or more ordering terms, applied left-to-right."""

    items: tuple[OrderByItem, ...]


@dataclass(frozen=True)
class LimitClause:
    """A LIMIT clause: cap the number of projected rows. `count` is >= 0."""

    count: int


@dataclass(frozen=True)
class NotExistsClause:
    """A NOT EXISTS correlated subquery block.

    Contains an inner MATCH and optional WHERE. Variables declared in the outer
    query are in scope inside the block; variables declared inside are scoped
    to the block.
    """

    match_clause: MatchClause
    where_clause: WhereClause | None


# ---------------------------------------------------------------------------
# Root AST node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GryphonAST:
    """The parsed representation of a complete gryphon query."""

    match_clauses: tuple[MatchClause, ...]
    where_clause: WhereClause | None
    return_clause: ReturnClause
    not_exists_clauses: tuple[NotExistsClause, ...] = ()
    order_by: OrderByClause | None = None
    limit: LimitClause | None = None
    optional_match_clauses: tuple[OptionalMatchClause, ...] = ()

    def required_params(self) -> frozenset[str]:
        """Return the set of $var names referenced anywhere in this AST.

        TAP-IMPLEMENTS: req-grid-traversal-lang-params@c0bba69be7b8/e700411dfc3d (derivation) — the
        one derivation of which $var parameters a query requires.

        .. tap:capability:: Gryphon query parameters
           :id: cap-grid-gryphon-parameters
           :status: implemented
           :audience: external-user; agent; developer
           :affordance: querying
           :covered-by: gridkin:hub_and_spoke-one-hop-undirected-neighborhood-of-the-dense-hub

           A query carries runtime inputs as ``$var`` references, supplied
           separately from the query text and validated before execution.

           Example::

              MATCH (h)-[e]-(n) WHERE h.entity_id = $hub_id
        """
        params: set[str] = set()
        _collect_params_from_predicate(self.where_clause.predicate if self.where_clause else None, params)
        for mc in self.match_clauses:
            _collect_params_from_match(mc, params)
        for omc in self.optional_match_clauses:
            _collect_params_from_patterns(omc.patterns, params)
        for nec in self.not_exists_clauses:
            _collect_params_from_match(nec.match_clause, params)
            if nec.where_clause is not None:
                _collect_params_from_predicate(nec.where_clause.predicate, params)
        return frozenset(params)


def _collect_params_from_patterns(patterns: tuple[PathPattern, ...], out: set[str]) -> None:
    for pattern in patterns:
        for node in pattern.nodes:
            for v in node.inline_props.values():
                if isinstance(v, ParamRef):
                    out.add(v.name)
        for edge in pattern.edges:
            for v in edge.inline_props.values():
                if isinstance(v, ParamRef):
                    out.add(v.name)


def _collect_params_from_match(mc: MatchClause, out: set[str]) -> None:
    _collect_params_from_patterns(mc.patterns, out)


def _collect_params_from_predicate(pred: Predicate | None, out: set[str]) -> None:
    if pred is None:
        return
    if isinstance(pred, Comparison):
        if isinstance(pred.value, ParamRef):
            out.add(pred.value.name)
    elif isinstance(pred, InComparison):
        for v in pred.values:
            if isinstance(v, ParamRef):
                out.add(v.name)
    elif isinstance(pred, (IsNullComparison, ObservationComparison)):
        # No ParamRef can appear in an IS [NOT] NULL / IS KNOWN / IS UNKNOWN
        # predicate — these leaves are field_path-only — but the walker must
        # still recognize them so their presence in a WHERE tree doesn't escape
        # required-param collection (silent-drop footgun for any predicate
        # walker that doesn't know about a new leaf).
        pass
    elif isinstance(pred, (AndPred, OrPred)):
        _collect_params_from_predicate(pred.left, out)
        _collect_params_from_predicate(pred.right, out)
    elif isinstance(pred, NotPred):
        _collect_params_from_predicate(pred.operand, out)
