"""TAP gryphon executor — lowers a GryphonAST to ORM queries and returns a canonical envelope.

Supported patterns
------------------
Type scan (node-only):
    MATCH (c:character) RETURN c.entity_id, c.name, c.bio

Hub-and-spoke (one hop, WHERE anchor):
    MATCH (a)-[e]-(b)     WHERE a.entity_id = $var   (undirected, one hop)
    MATCH (a)-[e:T]-(b)   WHERE a.entity_id = $var   (typed edge, undirected)
    MATCH (a)-[e]->(b)    WHERE a.entity_id = $var   (outbound only)
    MATCH (a)<-[e]-(b)    WHERE a.entity_id = $var   (inbound only)

Edge-type scan (one hop, no WHERE anchor):
    MATCH (r:realm)-[e:CONTAINS]->(l:location)
    MATCH (a:character)-[e:WIELDS]->(b:artifact)

Multi-hop chain with aggregation (advanced path):
    MATCH (e)-[:HAS_FINDING]->(f:finding)-[:REFERS_TO]->(i:indicator)
    WHERE f.status = "open"
    RETURN e.entity_id AS entity_id, COUNT(f) AS count

NOT EXISTS anti-join subquery:
    MATCH (e)-[:HAS_FINDING]->(f:finding)
    NOT EXISTS { MATCH (x:exception)-[:COVERS_FINDING]->(f) WHERE x.status = "active" }
    RETURN e.entity_id AS entity_id, COUNT(f) AS count

Multiple top-level MATCH clauses are executed independently (UNION semantics) with entity_id
deduplication — advanced-path queries (NOT EXISTS, COUNT, multi-hop) require a single MATCH.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from tap.db_aliases import SEARCH_READONLY
from tap_auth.capabilities import READ_CAPABILITY
from tap_auth.enforcement import requires_capability
from tap_grid.exceptions import SearchExecutionError
from tap_grid.grift.subgraph import (
    SubgraphLayer,
    batch_resolve_display,
    batch_resolve_entity_names,
    batch_resolve_icon_urls,
    batch_resolve_typed_models,
    serialize_edge_extended,
    serialize_edge_full,
    serialize_edge_lite,
    serialize_node_extended,
    serialize_node_full,
    serialize_node_lite,
)
from tap_grid.gryphon.ast_nodes import (
    AggregateCall,
    AggregateReturnItem,
    AndPred,
    Comparison,
    DotStep,
    FieldPath,
    GryphonAST,
    InComparison,
    IsNullComparison,
    KeyStep,
    MatchClause,
    NodePattern,
    NotExistsClause,
    NotPred,
    ObservationComparison,
    OrPred,
    ParamRef,
    PathPattern,
    Predicate,
    ReturnClause,
    ReturnItem,
)
from tap_grid.gryphon.capture import capture_sql, gryphon_stage
from tap_grid.gryphon.parser import GryphonParseError, parse_gryphon

if TYPE_CHECKING:
    from tap_grid.models import Search


# The read-only, least-privilege search connection. Every raw Gryphon entrypoint
# defaults to it so a caller that omits `db_alias` cannot silently run on the
# writable `default` connection (req-grid-traversal-exec-scope.sec-5). The stored-
# Search path uses the same alias via `tap_grid.search._SEARCH_DB_ALIAS`.
READONLY_DB_ALIAS = SEARCH_READONLY


def execute_gryphon(
    search: Search,
    inputs: dict[str, Any],
    *,
    db_alias: str = READONLY_DB_ALIAS,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Execute a gryphon-type Search and return the canonical graph envelope.

    Args:
        search: A Search instance with search_type="gryphon" and definition["query"].
        inputs: Runtime $var values; must supply all required params from the query.
        db_alias: Database alias for all queries. Defaults to the read-only search alias
            (`READONLY_DB_ALIAS`); pass a writable alias only for a deliberate, reviewed reason.
        layer: GRIFT subgraph return layer (lite, full, extended).

    Returns:
        ``{"nodes": [...], "edges": [...]}`` canonical envelope.

    Raises:
        SearchExecutionError: If the query is malformed, unsupported, or execution fails.
    """
    query = search.definition.get("query", "")
    if not query:
        raise SearchExecutionError("Gryphon search definition is missing 'query'.")

    return execute_gryphon_raw(query, inputs, db_alias=db_alias, layer=layer)


@requires_capability(READ_CAPABILITY, operation="execute_gryphon_raw")
def execute_gryphon_raw(
    query: str,
    inputs: dict[str, Any],
    *,
    db_alias: str = READONLY_DB_ALIAS,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Execute a raw gryphon query string and return the canonical graph envelope.

    Read enforcement (req-tap-auth-service-boundary): this is the second graph-read
    chokepoint besides execute_search — the raw-query path used by the gryphon API,
    panels, and batch_counts. It is gated on `grid.read` (resolved from the active
    CallerContext) so a raw read cannot bypass the stored-Search gate. An
    unauthorized/absent actor fails closed.

    Unlike execute_gryphon(), this does not require a stored Search entity.
    Used by the arrangement runtime and other consumers that hold inline
    gryphon query strings.

    The gate lives on this thin wrapper rather than on the impl so the
    authorization query runs *outside* any SQL-capture window opened by a
    caller (``explain_gryphon_raw`` records the executor's SQL; the cross-cutting
    permission check is not part of the query plan and must not pollute it).

    Args:
        query: A gryphon query string.
        inputs: Runtime $var values; must supply all required params from the query.
        db_alias: Database alias for all queries. Defaults to the read-only search alias
            (`READONLY_DB_ALIAS`); pass a writable alias only for a deliberate, reviewed reason.
        layer: GRIFT subgraph return layer (lite, full, extended).

    Returns:
        ``{"nodes": [...], "edges": [...]}`` canonical envelope.

    Raises:
        SearchExecutionError: If the query is malformed, unsupported, or execution fails.
    """
    return _execute_gryphon_raw_impl(query, inputs, db_alias=db_alias, layer=layer)


def _execute_gryphon_raw_impl(
    query: str,
    inputs: dict[str, Any],
    *,
    db_alias: str = READONLY_DB_ALIAS,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Raw-query execution body, without the read gate.

    Separated from ``execute_gryphon_raw`` so authorized callers that record the
    executor's SQL (``explain_gryphon_raw``) can gate once and then run the
    executor inside their capture window without the authorization query being
    recorded as part of the query plan. Not a public entry point — every external
    caller goes through ``execute_gryphon_raw`` (gated) or ``explain_gryphon_raw``
    (gated).
    """
    if not query:
        raise SearchExecutionError("Gryphon query string is empty.")

    # The documented contract of every execute_* entry point is "malformed query
    # raises SearchExecutionError" — but parse_gryphon raises GryphonParseError,
    # which escaped here as an unhandled exception (a 500 at the API, found by the
    # authenticated api-fuzz pass). Normalize at this chokepoint so every consumer
    # (API, panels, arrangements, batch_counts) sees a caller error, not a crash.
    try:
        ast = parse_gryphon(query)
    except GryphonParseError as exc:
        raise SearchExecutionError(str(exc)) from exc

    # Validate that all required $var names are present in inputs.
    required = ast.required_params()
    missing = required - set(inputs.keys())
    if missing:
        raise SearchExecutionError(f"Gryphon query requires inputs {sorted(missing)} but they were not provided.")

    # ORDER BY / LIMIT operate on row-projection results in general; the one
    # envelope-mode carve-out is a single labelled type-scan, where ORDER BY
    # by field path returns the ordered node envelope (the "latest emission of
    # kind X" panel shape, per req-grid-gryphon-order-by-envelope). Every other
    # envelope dispatch (hub-and-spoke, edge-type scan, multi-hop, bare
    # MATCH (n), multi-clause unions, queries carrying NOT EXISTS / OPTIONAL
    # MATCH) still rejects rather than silently ignore.
    if (
        (ast.order_by is not None or ast.limit is not None)
        and _is_graph_envelope_return(ast.return_clause)
        and not _is_typescan_envelope_query(ast)
    ):
        raise SearchExecutionError(
            "ORDER BY / LIMIT require a row-projection RETURN that names field paths or "
            "aggregates. The only envelope-mode carve-out is a single labelled type-scan — "
            "e.g. MATCH (n:type) ORDER BY n.data.<field> [LIMIT n] — per "
            "req-grid-gryphon-order-by-envelope. Hub-and-spoke, edge-type scans, multi-hop, "
            "bare MATCH (n), multi-clause unions, and queries carrying NOT EXISTS or "
            "OPTIONAL MATCH each have a different 'what does row order mean here' answer "
            "and remain row-projection-only."
        )

    if ast.optional_match_clauses:
        with gryphon_stage("optional-match"):
            return _execute_optional_match(ast, inputs, db_alias=db_alias, layer=layer)

    if _has_advanced_features(ast):
        with gryphon_stage("advanced"):
            return _execute_advanced(ast, inputs, db_alias=db_alias, layer=layer)

    return _execute_ast(ast, inputs, db_alias=db_alias, layer=layer)


@requires_capability(READ_CAPABILITY, operation="explain_gryphon_raw")
def explain_gryphon_raw(
    query: str,
    inputs: dict[str, Any],
    *,
    db_alias: str = READONLY_DB_ALIAS,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Execute a raw gryphon query and return both the envelope and the SQL it ran.

    TAP-IMPLEMENTS: req-grid-traversal-exec-sql-capture@6f701679bd50/5dd1f41684bd (surface) — the
        read-only seam that records issued SQL; snapshot tests and `gryphon explain` read it.

    Returns ``{"envelope": <canonical envelope>, "sql": <SqlCapture>}``. The
    ``sql`` value is the ordered, stage-labelled sequence of SELECT statements
    the executor issued — the basis of the Gridkin expected-SQL snapshot (the
    explain-snapshot requirement of ``spec-gridkin-v0.md``, in the
    gryphon_playground plugin repo) and the future
    ``gryphon explain`` developer surface (Gryphon wishlist H3).

    The executor runs unchanged; the SQL is observed via a
    ``connection.execute_wrapper`` for the duration of the call. Because a
    multi-stage query feeds each stage from the prior stage's results, the
    capture happens during execution, not as a pure compile step.

    Args:
        query: A gryphon query string.
        inputs: Runtime $var values; must supply all required params.
        db_alias: Database alias for all queries.
        layer: GRIFT subgraph return layer (lite, full, extended).

    Returns:
        ``{"envelope": {...}, "sql": SqlCapture}``.

    Raises:
        SearchExecutionError: If the query is malformed, unsupported, or fails.

    .. tap:capability:: Gryphon explain / SQL capture
       :id: cap-grid-gryphon-explain
       :status: implemented
       :audience: agent; developer
       :affordance: debugging
       :covered-by: pytest:tap_grid/tests/test_gryphon_sql_capture.py

       ``explain_gryphon_raw`` runs a query and returns both the canonical
       envelope and the ordered, stage-labelled SQL the executor issued.
    """
    # Gate runs in this function's own decorator (above), so the authorization
    # query is already done before the capture window opens. Call the impl
    # directly — routing through the gated execute_gryphon_raw would record a
    # second, redundant authz query inside the capture.
    with capture_sql() as capture:
        envelope = _execute_gryphon_raw_impl(query, inputs, db_alias=db_alias, layer=layer)
    return {"envelope": envelope, "sql": capture}


def _has_advanced_features(ast: GryphonAST) -> bool:
    """True if the query needs the advanced row/anti-join/multi-hop executor.

    Namely: NOT EXISTS, COUNT aggregation, a multi-hop pattern, OR a row-
    projection RETURN (field paths, not a bare graph envelope) over an
    edge-bearing pattern. The last case is load-bearing: a single-hop traversal
    with a field-projection RETURN (`MATCH (a)-[:E]->(b) RETURN a.data.x AS x`)
    would otherwise fall through to the single-hop *envelope* path, which only
    emits nodes/edges and SILENTLY IGNORES the projection (returning the wrong
    shape with no rows). Routing it here sends it through `_compute_rows` so the
    projection is actually honored — apply-or-reject, never accept-and-drop.
    """
    if ast.not_exists_clauses:
        return True
    if ast.return_clause.items is not None:
        for item in ast.return_clause.items:
            if isinstance(item, AggregateReturnItem):
                return True
    for mc in ast.match_clauses:
        for pattern in mc.patterns:
            if len(pattern.edges) > 1:
                return True
    # Row-projection RETURN over an edge-bearing (single-hop) pattern. Excluded
    # when it carries ORDER BY / LIMIT: a single-hop graph-traversal pattern
    # rejects those (only type-scan projections and aggregation queries support
    # them), and that rejection lives on the `_dispatch_pattern` single-hop path —
    # so such a query is deliberately left to fall through to it rather than
    # routed here, where `_compute_rows` would silently honor the ORDER BY.
    if ast.order_by is None and ast.limit is None and not _is_graph_envelope_return(ast.return_clause):
        for mc in ast.match_clauses:
            for pattern in mc.patterns:
                if pattern.edges:
                    return True
    return False


# ---------------------------------------------------------------------------
# AST execution
# ---------------------------------------------------------------------------


def _execute_ast(
    ast: GryphonAST,
    inputs: dict[str, Any],
    *,
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Dispatch to the appropriate execution strategy based on AST shape.

    Supports multiple MATCH clauses (UNION semantics): each clause is executed
    independently and results are merged with entity_id deduplication. A single
    global WHERE is applied to each MATCH, scoped to the variables that clause
    binds (per ``_filter_predicate_for_bindings``).
    """
    all_nodes: dict[str, dict[str, Any]] = {}
    all_edges: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    all_warnings: dict[str, Any] = {}

    for mc in ast.match_clauses:
        if len(mc.patterns) != 1:
            raise SearchExecutionError("Unsupported gryphon pattern: each MATCH clause must have exactly one pattern.")
        pattern = mc.patterns[0]

        result = _dispatch_pattern(
            pattern,
            return_clause=ast.return_clause,
            where_clause=ast.where_clause,
            order_by=ast.order_by,
            limit=ast.limit,
            inputs=inputs,
            db_alias=db_alias,
            layer=layer,
        )

        for node in result.get("nodes", []):
            key = _node_key(node, layer)
            all_nodes.setdefault(key, node)
        for edge in result.get("edges", []):
            key = _edge_key(edge, layer)
            all_edges.setdefault(key, edge)
        # Projection rows (a type-scan in projection mode) are not graph-envelope
        # members — they carry RETURN aliases as keys and are not entity_id-
        # dedupable. Concatenate them straight through.
        all_rows.extend(result.get("rows", []))
        # Warnings (e.g. a hub-and-spoke anchor not found) must reach the caller.
        all_warnings.update(result.get("warnings", {}))

    envelope: dict[str, Any] = {"nodes": list(all_nodes.values()), "edges": list(all_edges.values())}
    if all_rows:
        envelope["rows"] = all_rows
    if all_warnings:
        envelope["warnings"] = all_warnings
    return envelope


def _dispatch_pattern(
    pattern: PathPattern,
    *,
    return_clause: ReturnClause,
    where_clause: Any = None,
    order_by: Any = None,
    limit: Any = None,
    inputs: dict[str, Any] | None = None,
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Route a single MATCH pattern to the appropriate execution mode."""
    # Type scan: node-only pattern (no edges). A labelless node is the bare
    # scan over every registered node type; a labelled node scans one type.
    if len(pattern.edges) == 0:
        node = pattern.nodes[0]
        if node.label is None:
            with gryphon_stage("bare-type-scan"):
                return _execute_bare_type_scan(
                    node,
                    return_clause,
                    where_clause=where_clause,
                    order_by=order_by,
                    limit=limit,
                    inputs=inputs or {},
                    db_alias=db_alias,
                    layer=layer,
                )
        with gryphon_stage("type-scan"):
            return _execute_type_scan(
                node,
                return_clause,
                where_clause=where_clause,
                order_by=order_by,
                limit=limit,
                inputs=inputs or {},
                db_alias=db_alias,
                layer=layer,
            )

    if len(pattern.edges) != 1:
        raise SearchExecutionError("Unsupported gryphon pattern: only single-hop patterns are supported.")

    # Single-hop graph traversal produces a graph envelope, not rows — ORDER BY /
    # LIMIT have nothing to act on. Reject rather than silently drop.
    if order_by is not None or limit is not None:
        raise SearchExecutionError(
            "ORDER BY / LIMIT are supported on type-scan projections and aggregation "
            "queries, not on single-hop graph-traversal patterns."
        )

    edge_pat = pattern.edges[0]
    if edge_pat.min_hops != 1 or edge_pat.max_hops != 1:
        raise SearchExecutionError("Unsupported gryphon pattern: bounded multi-hop traversal is not supported.")

    # Single-hop graph traversal. Route through the chain machinery
    # (_build_chain_queryset + _apply_predicate_to_qs + _collect_graph_envelope)
    # so the FULL WHERE is applied — every non-anchor predicate, with data-lane
    # type strictness — exactly as the multi-hop path does. This closes the
    # envelope-WHERE silent-drop defect and collapses the former hub-and-spoke
    # and edge-type-scan executors (which honored only an entity_id anchor, or no
    # WHERE at all) into one apply-or-reject code path: an entity_id anchor is now
    # an ordinary WHERE predicate, not a special dispatch case.
    with gryphon_stage("single-hop"):
        return _execute_single_hop_envelope(
            pattern,
            where_clause=where_clause,
            return_clause=return_clause,
            inputs=inputs or {},
            db_alias=db_alias,
            layer=layer,
        )


def _node_key(node: dict[str, Any], layer: SubgraphLayer) -> str:
    """Extract a dedup key from a serialized node envelope.

    Under spec-grift-envelope, entity_id is always at the top level of
    the envelope across all layers.
    """
    return str(node["entity_id"])


def _edge_key(edge: dict[str, Any], layer: SubgraphLayer) -> str:
    """Extract a dedup key from a serialized edge envelope.

    Under spec-grift-envelope, entity_id is always at the top level of
    the envelope across all layers.
    """
    return str(edge["entity_id"])


def _execute_single_hop_envelope(
    pattern: PathPattern,
    *,
    where_clause: Any,
    return_clause: ReturnClause,
    inputs: dict[str, Any],
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Execute a single-hop graph-traversal pattern as a graph envelope.

    Reuses the chain machinery that the multi-hop / aggregation path already
    uses — ``_build_chain_queryset`` + ``_filter_predicate_for_bindings`` +
    ``_apply_predicate_to_qs`` + ``_collect_graph_envelope`` — so the FULL WHERE
    is applied (every non-anchor predicate, with data-lane type strictness), not
    just an ``entity_id`` anchor. This is the fix for the envelope-WHERE
    silent-drop defect and the collapse of the former ``_execute_hub_and_spoke``
    / ``_execute_edge_type_scan`` executors into one apply-or-reject path.

    Directed hops (``->`` / ``<-``) go straight through the chain queryset. An
    undirected hop (``-[e]-``) is the one shape the chain builder rejects; it is
    handled here as the union of its two directed arms, with the WHERE applied to
    each arm independently — so an undirected single hop never silently drops a
    predicate either.
    """
    edge = pattern.edges[0]
    if edge.direction != "any":
        return _single_hop_directed(
            pattern,
            where_clause=where_clause,
            return_clause=return_clause,
            inputs=inputs,
            db_alias=db_alias,
            layer=layer,
        )

    # Undirected: union the outbound and inbound arms. Each arm is a directed
    # single hop with the same nodes; `_build_var_bindings` maps the variables to
    # the correct endpoint per direction, so the WHERE resolves correctly on both.
    out_env = _single_hop_directed(
        _redirect_single_hop(pattern, "out"),
        where_clause=where_clause,
        return_clause=return_clause,
        inputs=inputs,
        db_alias=db_alias,
        layer=layer,
    )
    in_env = _single_hop_directed(
        _redirect_single_hop(pattern, "in"),
        where_clause=where_clause,
        return_clause=return_clause,
        inputs=inputs,
        db_alias=db_alias,
        layer=layer,
    )
    return _merge_envelopes(out_env, in_env, layer)


def _single_hop_directed(
    pattern: PathPattern,
    *,
    where_clause: Any,
    return_clause: ReturnClause,
    inputs: dict[str, Any],
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Run one directed single-hop pattern through the WHERE-applying chain path."""
    bindings = _build_var_bindings(pattern)
    qs = _build_chain_queryset(pattern, db_alias, inputs)
    applicable_pred = _filter_predicate_for_bindings(
        where_clause.predicate if where_clause else None,
        bindings,
    )
    qs = _apply_predicate_to_qs(qs, applicable_pred, bindings, inputs)
    return _collect_graph_envelope(qs, pattern, return_clause, bindings, layer=layer, db_alias=db_alias)


def _redirect_single_hop(pattern: PathPattern, direction: str) -> PathPattern:
    """Return a copy of a single-hop pattern with its edge direction rewritten."""
    edge = replace(pattern.edges[0], direction=direction)
    return replace(pattern, edges=(edge,))


def _merge_envelopes(a: dict[str, Any], b: dict[str, Any], layer: SubgraphLayer) -> dict[str, Any]:
    """Union two graph envelopes, deduplicating nodes and edges by entity_id."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for env in (a, b):
        for node in env.get("nodes", []):
            nodes.setdefault(_node_key(node, layer), node)
        for edge in env.get("edges", []):
            edges.setdefault(_edge_key(edge, layer), edge)
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "rows": []}


# ---------------------------------------------------------------------------
# Type-scan ORM execution
# ---------------------------------------------------------------------------

# Fields that live on Entity rather than the domain model.
_ENTITY_FIELDS: frozenset[str] = frozenset()  # populated lazily via _spine_field_names()


def _execute_type_scan(
    node: NodePattern,
    return_clause: ReturnClause,
    *,
    where_clause: Any = None,
    order_by: Any = None,
    limit: Any = None,
    inputs: dict[str, Any] | None = None,
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Execute a node-only MATCH pattern — scan all entities of the given type.

    TAP-IMPLEMENTS: req-grid-traversal-lang-patterns@f42025b24a48/cdd96a437a62 (derivation) — the
        labelled node/edge pattern shape executes here.

    Applies a global WHERE clause filtered to predicates that reference the
    type-scan's bound variable (per ``_filter_predicate_for_bindings``).
    Predicates referencing other variables (from other MATCH clauses in a
    UNION query) are skipped.

    Args:
        node: The single node pattern; must carry a label (entity type slug).
        return_clause: Controls output shape (projected fields vs. graph envelope).
        where_clause: Optional global WHERE clause; only variable-matching
            predicates are applied.
        inputs: Runtime parameter values for ``$param`` references in WHERE.
        db_alias: Database alias to query against.
        layer: GRIFT subgraph return layer.

    Returns:
        Canonical envelope with ``nodes`` list and empty ``edges`` list.

    .. tap:capability:: Gryphon type scan
       :id: cap-grid-gryphon-type-scan
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:type_scan-scan-returns-every-pg-node-in-the-fixture

       A node-only ``MATCH (n:entity_type)`` scans every entity of one
       registered type. A labelless ``MATCH (n)`` routes instead to the bare
       scan over every registered node type (`cap-grid-gryphon-bare-match`).

       Example::

          MATCH (n:grid_fixtures__node)
    """
    if not node.label:
        # _dispatch_pattern routes a labelless node to _execute_bare_type_scan;
        # this guard only fires if _execute_type_scan is called directly.
        raise SearchExecutionError("Unsupported gryphon pattern: type scan requires a node label, e.g. (c:character).")

    from tap_grid.registry import get_model_class

    try:
        model_cls = get_model_class(node.label)
    except KeyError:
        raise SearchExecutionError(f"Unsupported gryphon pattern: unknown entity type '{node.label}'.") from None

    qs = model_cls.objects.using(db_alias).select_related("entity").order_by("entity__name")

    var = node.variable or node.label
    inputs = inputs or {}

    # Apply WHERE comparisons scoped to this variable.
    if where_clause is not None:
        scoped_pred = _filter_predicate_for_bindings(
            where_clause.predicate, {var: {"role": "typescan", "label": node.label}}
        )
        if scoped_pred is not None:
            qs = _apply_typescan_predicate(qs, scoped_pred, inputs)

    # Graph envelope mode — RETURN omitted, or RETURN names only bare variables.
    # A bare `RETURN n` requests the node itself, which is the graph envelope;
    # projection mode (projected field dicts) is for RETURN clauses that name
    # field paths. This mirrors the advanced executor's _is_graph_envelope_return
    # — without it, `MATCH (n:type) RETURN n` returned a list of empty dicts.
    if _is_graph_envelope_return(return_clause):
        qs = _apply_order_limit_typescan_envelope(qs, order_by, limit, var)
        domain_objects = list(qs)
        nodes = _serialize_typed_nodes(domain_objects, layer, db_alias)
        return {"nodes": nodes, "edges": []}

    # Projection mode — RETURN names field paths. Projected rows go in `rows`,
    # not `nodes`: they carry the RETURN aliases as keys and are row projections,
    # not graph-envelope members. This matches the advanced executor's
    # _compute_rows; putting them in `nodes` crashed _execute_ast's entity_id
    # dedup on any projection without a bare `entity_id` key.
    items = return_clause.items
    assert items is not None  # _is_graph_envelope_return is True when items is None
    from django.db.models import F

    # Build the row-materialization plan. Each projected field resolves to its ORM
    # lookup via the same `_typescan_orm_path` the WHERE clause already uses, so a
    # nested JSON scalar sub-key is projected in PostgreSQL (`data -> 'k'`) rather
    # than walked in Python — retiring the former `_project_node` tail
    # (req-grid-traversal-exec-row-materialization-4/6). Bare-variable items (no
    # dot-steps) and items bound to another variable are skipped, matching the
    # former projection.
    group_pairs: list[tuple[str, str]] = []
    annotations: dict[str, Any] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, ReturnItem) or item.path.variable != var:
            continue
        if not item.path.steps or not isinstance(item.path.steps[0], DotStep):
            continue
        if item.path.steps[0].name == _DISPLAY_LANE_PREFIX:
            # RETURN-projection context: the workaround is the extended layer,
            # which computes display values. `_typescan_orm_path` also rejects
            # display, but with the WHERE-context message (no extended hint,
            # since filtering on computed values has no workaround), so the
            # projection path names its own workaround here
            # (req-grid-traversal-lang-envelope-paths-3).
            raise SearchExecutionError(
                "Cannot use the `display` lane in RETURN paths today — display "
                "values are computed for rendering, not stored. For display data "
                "use the `extended` return layer."
            )
        # Keep RETURN projection at its v1 boundary — the shared resolver is more
        # permissive than a v1 projection should be (bracket keys, multi-step
        # spine walks), so reject those here rather than silently widen.
        _reject_non_projectable_return_path(item.path)
        internal = f"_ts_col_{idx}"
        annotations[internal] = F(_typescan_orm_path(item.path, qs.model))
        group_pairs.append((internal, _return_item_key(item)))

    plan = MaterializationPlan(
        queryset=qs,
        pre_annotations=annotations,
        group_pairs=tuple(group_pairs),
        aggregate_annotations={},
        aggregate_pairs=(),
        order_cols=_typescan_order_cols(order_by, limit, items, var, qs.model),
        limit=limit,
    )
    return {"nodes": [], "edges": [], "rows": materialize_rows(plan)}


def _return_item_key(item: Any) -> str:
    """The output key a RETURN item contributes — its alias, or default name.

    For an aggregate item the alias is mandatory. For a field projection the
    key is the explicit `AS` alias if present, else the last dot-step name
    (matching the group-pair keys `materialize_rows` projects).
    """
    if isinstance(item, AggregateReturnItem):
        return item.alias
    if item.alias is not None:
        return item.alias
    last = item.path.steps[-1] if item.path.steps else None
    return last.name if isinstance(last, DotStep) else item.path.variable


def _typescan_order_cols(
    order_by: Any,
    limit: Any,
    items: tuple,
    var: str,
    model_cls: type | None,
) -> tuple[str, ...]:
    """Resolve the type-scan projection ORDER BY convention into `.order_by()` columns.

    ORDER BY terms name RETURN outputs by key; each maps to the ORM lookup path of
    the projecting RETURN item, with `entity_id` (the per-model PK column) appended
    as a unique tiebreaker so the surviving rows under a LIMIT — and the captured
    SQL — stay deterministic across runs. A `LIMIT` with no `ORDER BY` keeps the
    default name order with the same tiebreaker. An empty result means "do not
    reorder": the type-scan queryset already carries `.order_by("entity__name")`.

    In projection mode, ORDER BY terms must be bare names (FieldPath with no steps)
    that match a RETURN alias; a multi-step field-path term is the envelope-mode
    surface (per req-grid-gryphon-order-by-envelope) and is rejected here.

    The resolved columns are carried on the `MaterializationPlan` and applied by
    the shared backend (`req-grid-traversal-exec-row-materialization`).
    """
    if order_by is not None:
        key_to_path: dict[str, str] = {}
        for item in items:
            if not isinstance(item, ReturnItem) or item.path.variable != var:
                continue
            key_to_path[_return_item_key(item)] = _typescan_orm_path(item.path, model_cls)
        cols: list[str] = []
        for ob in order_by.items:
            if ob.path.steps:
                raise SearchExecutionError(
                    f"ORDER BY field-path form '{_format_field_path(ob.path)}' is "
                    f"supported in envelope-mode RETURN only in v0 (per "
                    f"req-grid-gryphon-order-by-envelope). In projection mode, ORDER "
                    f"BY names a RETURN output by alias — e.g. ORDER BY {ob.key}."
                )
            if ob.key not in key_to_path:
                raise SearchExecutionError(
                    f"ORDER BY references '{ob.key}', which is not a RETURN output of this query."
                )
            col = key_to_path[ob.key]
            cols.append(f"-{col}" if ob.descending else col)
        cols.append("entity_id")
        return tuple(cols)
    if limit is not None:
        # LIMIT with no ORDER BY: keep the default name order, with a unique
        # tiebreaker so which rows survive the cap stays deterministic.
        return ("entity__name", "entity_id")
    return ()


def _apply_order_limit_typescan_envelope(
    qs,
    order_by: Any,
    limit: Any,
    var: str,
):
    """Apply ORDER BY / LIMIT to a type-scan queryset in graph-envelope mode.

    TAP-IMPLEMENTS: req-grid-gryphon-order-by-envelope@26c6977be171/17bd2b7a441d (derivation) —
        ORDER BY / LIMIT on a type-scan graph envelope is applied here.

    Envelope mode has no RETURN aliases, so ORDER BY terms must carry a full
    field path rooted at the bound variable (e.g. `n.data.fetched_at`). Each
    is resolved through the same `_typescan_orm_path` machinery that backs the
    WHERE compiler, so spine fields, the `data` lane, and `dimensions.<key>`
    all reach the right ORM column. `entity_id` is appended ascending as a
    deterministic tiebreaker so the surviving rows under a LIMIT — and the
    captured SQL — are stable across runs.

    A bare-name ORDER BY in envelope mode (`ORDER BY label`) is ambiguous —
    there are no aliases — and is rejected with a clear error pointing at the
    field-path form. Per req-grid-gryphon-order-by-envelope.

    .. tap:capability:: Gryphon envelope-mode ORDER BY / LIMIT
       :id: cap-grid-gryphon-order-by-envelope
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:order_by_limit_envelope-latest-emission-by-data-field-limit-1
       :limitations: Single labelled type-scan only — hub-and-spoke, edge-type scan, multi-hop, bare MATCH (n), multi-clause unions, and queries carrying NOT EXISTS / OPTIONAL MATCH keep the rejection.

       A labelled type-scan returning a graph envelope accepts
       ``ORDER BY <var>.<field-path>`` and ``LIMIT n`` so the
       "latest emission of kind X" panel shape becomes a single Gryphon query.

       Example::

          MATCH (n:compliance_artifact) WHERE n.data.kind = $kind
          ORDER BY n.data.fetched_at DESC LIMIT 1
    """
    if order_by is not None:
        order_cols: list[str] = []
        for ob in order_by.items:
            if not ob.path.steps:
                raise SearchExecutionError(
                    f"Envelope-mode ORDER BY must name a field path "
                    f"(e.g. ORDER BY {var}.data.<field>). A bare name "
                    f"'{ob.path.variable}' has no defined meaning in envelope "
                    f"mode — there are no RETURN aliases to look up against."
                )
            if ob.path.variable != var:
                raise SearchExecutionError(
                    f"ORDER BY references variable '{ob.path.variable}', which is "
                    f"not bound by this MATCH pattern (the bound variable is "
                    f"'{var}')."
                )
            col = _typescan_orm_path(ob.path, qs.model)
            order_cols.append(f"-{col}" if ob.descending else col)
        order_cols.append("entity_id")
        qs = qs.order_by(*order_cols)
    elif limit is not None:
        # LIMIT with no ORDER BY: keep the spine-name default, with the
        # entity_id tiebreaker so which rows survive the cap is deterministic.
        qs = qs.order_by("entity__name", "entity_id")

    if limit is not None:
        qs = qs[: limit.count]
    return qs


def _format_field_path(path: FieldPath) -> str:
    """Render a FieldPath as Gryphon source text for error messages."""
    out = path.variable
    for step in path.steps:
        if isinstance(step, DotStep):
            out += f".{step.name}"
        elif isinstance(step, KeyStep):
            out += f'["{step.key}"]'
    return out


def _apply_typescan_predicate(
    qs,
    predicate: Any,
    inputs: dict[str, Any],
):
    """Apply a WHERE predicate tree to a type-scan queryset as a single ``Q`` filter.

    The full AND / OR / NOT tree is compiled by :func:`_predicate_to_q`. The
    predicate reaching here is already scoped to the type-scan's variable by
    :func:`_filter_predicate_for_bindings`, so every leaf resolves through
    :func:`_typescan_orm_path`.
    """
    if predicate is None:
        return qs
    model_cls = qs.model
    return qs.filter(
        _predicate_to_q(
            predicate,
            inputs,
            lambda fp: _typescan_orm_path(fp, model_cls),
            lambda fp: _declared_data_types(model_cls, fp),
        )
    )


def _validate_data_lane_steps(model_cls: type | None, rest_steps: Sequence[Any]) -> None:
    """Allowlist the post-``data`` steps of a field path against the model's declared fields.

    The single positive rule of ``req-grid-traversal-lang-relation-guard.sec`` (the
    "Data-Lane Field-Path Allowlist"): every ``data``-lane token MUST resolve to a
    concrete declared field on the model — a scalar column, or a JSON key inside a
    declared ``JSONField``. Anything else is rejected. This one check closes the four
    confirmed manifestations of ``ROOT-1`` (the un-allowlisted ``__``-join):

    - **Relation crossing** — the first step resolving to a relation field
      (``field.is_relation``) is rejected, so ``b.data.actor.email`` /
      ``b.data.actor.password`` can no longer emit a cross-table join into ``tap_user``.
    - **Lookup / transform injection** — a Django lookup/transform token that is not a
      declared field is rejected: as a first step it is an undeclared field; after a
      scalar field it is a walk-into-scalar (``b.data.version.regex``).
    - **Undeclared field** — a token naming no declared field raises a clear
      ``SearchExecutionError`` (a 422), not an uncaught Django ``FieldError`` (a 500).
    - **Composite-token / bracket-key smuggling** — a token containing ``__``
      (``b.data.actor__password``, ``b.data["actor__password"]``) is rejected, so a
      multi-step walk cannot be smuggled through a single opaque token.

    ``rest_steps`` are the steps *after* the ``data`` prefix (dot or bracket-key), and
    the caller guarantees the list is non-empty. Called by every data-lane resolver so
    the allowlist is enforced at the shared resolution boundary, in WHERE and RETURN
    alike, before any ``__``-join reaches ``.filter()`` / ``F()``.
    """
    from django.core.exceptions import FieldDoesNotExist
    from django.db.models import JSONField

    names = [s.name if isinstance(s, DotStep) else s.key for s in rest_steps]
    for nm in names:
        if "__" in nm:
            raise SearchExecutionError(
                f"Data-lane token {nm!r} may not contain '__'. A relation/lookup separator "
                f"cannot be smuggled through a single token; address one declared field per "
                f"step (req-grid-traversal-lang-relation-guard.sec)."
            )
    first = names[0]
    if model_cls is None:
        raise SearchExecutionError(
            f"Cannot resolve data-lane path `.data.{'.'.join(names)}` without a bound model "
            f"type; add a node label so the field can be validated against the model "
            f"(req-grid-traversal-lang-relation-guard.sec)."
        )
    try:
        field = model_cls._meta.get_field(first)
    except FieldDoesNotExist:
        # `from None` deliberately suppresses the Django FieldDoesNotExist chain: converting it
        # to a clean 422 (rather than letting a FieldError surface) is manifestation 3 of the
        # fix — no error-shape/valid-field-name leak (req-grid-traversal-lang-relation-guard.sec).
        raise SearchExecutionError(
            f"{first!r} is not a declared field on {model_cls.__name__}. The data lane may only "
            f"address the model's own declared fields (req-grid-traversal-lang-relation-guard.sec)."
        ) from None
    if field.is_relation:
        raise SearchExecutionError(
            f"Data-lane path may not cross the relation {first!r} on {model_cls.__name__} into "
            f"another table. Only the entity/dimensions spine hop may cross tables "
            f"(req-grid-traversal-lang-relation-guard.sec)."
        )
    if len(names) > 1 and not isinstance(field, JSONField):
        raise SearchExecutionError(
            f"Cannot walk into the scalar field {first!r} on {model_cls.__name__}. Further steps "
            f"are valid only inside a JSON-typed field; a trailing token on a scalar is a Django "
            f"lookup/transform, which the data lane does not admit "
            f"(req-grid-traversal-lang-relation-guard.sec)."
        )


def _typescan_orm_path(field_path: FieldPath, model_cls: type | None) -> str:
    """Translate a Gryphon FieldPath to a Django ORM lookup for a type-scan queryset.

    The queryset is on the per-model class (e.g. LambdaFunction), so:

    - ``n.entity_id`` → ``entity_id`` (FK column on the per-model row)
    - ``n.<spinefield>`` → ``entity__<field>`` (cross-table join via the FK)
    - ``n.dimensions.<key>...`` → ``entity__dimensions__<key>...`` (JSON nested
      via FK; only JSON-typed spine fields can be multi-step-walked)
    - ``n.data.<x>...`` → ``<x>...`` (direct attribute on the per-model row;
      multi-step `__`-joined for JSONField nested keys)
    - ``n.display.<...>`` → rejected; computed-not-stored.

    ``model_cls`` is the bound per-model class; the ``data`` lane is validated against
    its declared fields (``_validate_data_lane_steps``, the ROOT-1 allowlist). It is
    required — a caller that cannot supply the model cannot resolve a data-lane path.
    """
    steps = field_path.steps
    if not steps or not isinstance(steps[0], DotStep):
        raise SearchExecutionError("FieldPath must start with a dot-step.")

    first = steps[0].name
    spine_fields = _spine_field_names()

    # Single-step.
    if len(steps) == 1:
        if first == "entity_id":
            return "entity_id"
        if first in spine_fields:
            return f"entity__{first}"
        if first in {_DATA_LANE_PREFIX, _DISPLAY_LANE_PREFIX}:
            raise SearchExecutionError(
                f"Bare `{first}` is not a complete path. Use `{first}.<...>` to " f"address the {first} lane."
            )
        raise SearchExecutionError(
            f"Field {first!r} is not a spine field. If it lives on the per-model "
            f"row, address it as `<var>.data.{first}` per spec-grift-envelope."
        )

    # Multi-step.
    if first == _DISPLAY_LANE_PREFIX:
        raise SearchExecutionError(
            "Cannot use the `display` lane in WHERE/RETURN paths today — display "
            "values are computed for rendering, not stored."
        )

    rest_steps = steps[1:]
    for step in rest_steps:
        if not isinstance(step, DotStep) and not isinstance(step, KeyStep):
            raise SearchExecutionError("Multi-step paths support dot-steps and bracket-key steps only.")

    def _name(step):
        return step.name if isinstance(step, DotStep) else step.key

    rest = "__".join(_name(s) for s in rest_steps)

    if first == _DATA_LANE_PREFIX:
        _validate_data_lane_steps(model_cls, rest_steps)
        return rest

    # Multi-step into a JSON-typed spine field (today: `dimensions`).
    if first in _JSON_TYPED_SPINE_FIELDS:
        return f"entity__{first}__{rest}"

    if first in spine_fields:
        raise SearchExecutionError(
            f"Spine field {first!r} is a scalar; cannot walk into it. For nested "
            f"access into JSON-typed columns, use `<var>.data.<field>...` or "
            f"`<var>.dimensions.<key>` for the dimensions spine field."
        )

    raise SearchExecutionError(
        f"Unknown field path prefix {first!r}. Use a spine field, the `data` "
        f"prefix for per-model fields, or `dimensions.<key>` for dimension "
        f"scoping."
    )


def _reject_non_projectable_return_path(field_path: FieldPath) -> None:
    """Enforce the v1 RETURN-projection boundary — deliberately stricter than WHERE.

    RETURN projection and WHERE now share `_typescan_orm_path`, which is
    intentionally permissive: it accepts bracket-key steps and multi-step walks
    into JSON-typed spine fields (e.g. `dimensions`), both valid in a WHERE
    predicate. RETURN projection is narrower in v1
    (`req-grid-traversal-lang-envelope-paths`): the `data` lane admits dot-steps
    only, and a spine field cannot be walked into. This guard reproduces the
    pre-unification `_resolve_envelope_path` acceptance set so collapsing the row
    tails onto the shared resolver does not *silently widen* what RETURN accepts.
    Widening RETURN to match WHERE is a deliberate future feature, not a side
    effect of the unification. Call it before resolving a projection item through
    `_typescan_orm_path`. (The `display` lane is rejected earlier in the
    projection loop, with the extended-layer hint.)
    """
    steps = field_path.steps
    if not steps or not isinstance(steps[0], DotStep):
        return  # the caller (projection loop) already ensures a leading dot-step
    first = steps[0].name
    if first == _DATA_LANE_PREFIX:
        rest = steps[1:]
        if not rest:
            raise SearchExecutionError(
                "Path `<var>.data` requires at least one further step (e.g. `<var>.data.<field>`)."
            )
        for step in rest:
            if not isinstance(step, DotStep):
                raise SearchExecutionError("Inside the `data` lane only dot-steps are supported in v1.")
        return
    if first == _DISPLAY_LANE_PREFIX:
        return
    # Spine field (or `entity_id`): single-step only in a RETURN projection.
    if len(steps) > 1:
        raise SearchExecutionError(
            f"Spine field {first!r} cannot be walked into. For nested access "
            f"use `<var>.data.<field>...` per spec-grift-envelope."
        )


# Spine fields that are JSON-typed and therefore support multi-step walking
# into nested keys. Today only `dimensions`; future JSON-typed spine fields
# slot in here.
_JSON_TYPED_SPINE_FIELDS: frozenset[str] = frozenset({"dimensions"})


def _predicate_field_paths(predicate: Any) -> list[FieldPath]:
    """Collect every `FieldPath` referenced anywhere in a predicate tree."""
    if predicate is None:
        return []
    if isinstance(predicate, (Comparison, InComparison, IsNullComparison, ObservationComparison)):
        return [predicate.field_path]
    if isinstance(predicate, (AndPred, OrPred)):
        return _predicate_field_paths(predicate.left) + _predicate_field_paths(predicate.right)
    if isinstance(predicate, NotPred):
        return _predicate_field_paths(predicate.operand)
    return []


def _is_pure_conjunction(predicate: Any) -> bool:
    """True if the predicate tree is only comparison leaves joined by AND."""
    if predicate is None:
        return True
    if isinstance(predicate, (Comparison, InComparison, IsNullComparison, ObservationComparison)):
        return True
    if isinstance(predicate, AndPred):
        return _is_pure_conjunction(predicate.left) and _is_pure_conjunction(predicate.right)
    return False


def _bare_spine_orm_path(field_path: FieldPath) -> str:
    """ORM lookup for a spine field path against an `Entity`-rooted queryset.

    A labelless ``MATCH (n)`` with a spine-only WHERE scans the `Entity` spine
    table directly, where spine fields are columns on the row itself — unlike a
    per-model queryset, where `_typescan_orm_path` reaches them via `entity__`.
    `entity_id` is the Entity primary-key column, `id`.
    """
    steps = field_path.steps
    if not steps or not isinstance(steps[0], DotStep):
        raise SearchExecutionError("FieldPath must start with a dot-step.")
    first = steps[0].name
    if first == "entity_id":
        if len(steps) > 1:
            raise SearchExecutionError("`entity_id` is a scalar; it cannot be walked into.")
        return "id"
    if first in _spine_field_names():
        rest = steps[1:]
        if not rest:
            return first
        if first in _JSON_TYPED_SPINE_FIELDS:
            for step in rest:
                if not isinstance(step, (DotStep, KeyStep)):
                    raise SearchExecutionError("Spine JSON access supports dot-steps and bracket-key steps only.")
            inner = "__".join(s.name if isinstance(s, DotStep) else s.key for s in rest)
            return f"{first}__{inner}"
        raise SearchExecutionError(f"Spine field {first!r} is a scalar; it cannot be walked into.")
    raise SearchExecutionError(
        f"Field {first!r} is not a spine field; address per-model fields as `<var>.data.{first}`."
    )


def _execute_bare_type_scan(
    node: NodePattern,
    return_clause: ReturnClause,
    *,
    where_clause: Any = None,
    order_by: Any = None,
    limit: Any = None,
    inputs: dict[str, Any] | None = None,
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Execute a labelless ``MATCH (n)`` — scan every registered node type, union.

    TAP-IMPLEMENTS: req-grid-traversal-lang-bare-match@aa1e2046457a/b3caafe6ca37 (derivation) —
        the labelless MATCH (n) all-types union scan executes here.

    A labelless node pattern is a wildcard over node entity types: it returns
    the entities of every registered type, so one labelless clause plus a WHERE
    replaces an N-clause per-type list.

    - **Spine-only WHERE** (or no WHERE): one scan of the `Entity` spine table,
      restricted to the registered node types (`entity_type__in`), so a
      spine-field predicate — `entity_type` especially — stays a single cheap
      query rather than a scan of every per-model table.
    - **Data-lane WHERE** (`<var>.data.<field>`): the predicate must be
      AND-joined; each registered node type is scanned, and a type that lacks a
      referenced data field contributes zero rows — silently, never an error.
      Matched entity ids are unioned and the entities bulk-fetched.

    Edges are not scanned — the `edge` type is excluded by entity_type; edges
    are matched by edge patterns. v0 returns a graph envelope only.

    .. tap:capability:: Gryphon bare (labelless) MATCH
       :id: cap-grid-gryphon-bare-match
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:bare_match-labelless-scan-filtered-by-an-entity-type-prefix
       :limitations: Graph-envelope result only; a data-lane WHERE must be AND-joined; ORDER BY / LIMIT unsupported (v0).

       ``MATCH (n)`` with no label scans every registered node type and unions
       the results. A type lacking a WHERE-referenced data field matches
       nothing rather than erroring, so a data-lane filter crosses types safely.

       Example::

          MATCH (n) WHERE n.data.tags.Project = "samsite"
    """
    from tap_grid.models import Entity
    from tap_grid.registry import get_model_class, list_entity_types

    inputs = inputs or {}
    var = node.variable or "n"

    if order_by is not None or limit is not None:
        raise SearchExecutionError(
            "ORDER BY / LIMIT on a labelless MATCH (n) are not supported yet; scope the scan to a labelled type."
        )
    if not _is_graph_envelope_return(return_clause):
        raise SearchExecutionError(
            "A labelless MATCH (n) supports graph-envelope results only (RETURN omitted or naming bare "
            "variables); row projection over a bare scan is future work."
        )

    scoped_pred = None
    if where_clause is not None:
        scoped_pred = _filter_predicate_for_bindings(where_clause.predicate, {var: {}})

    # Classify the WHERE's field paths into spine vs. data lane.
    data_lane_fields: set[str] = set()
    for field_path in _predicate_field_paths(scoped_pred):
        if not field_path.steps or not isinstance(field_path.steps[0], DotStep):
            continue
        head = field_path.steps[0].name
        if head == _DISPLAY_LANE_PREFIX:
            raise SearchExecutionError(
                "Cannot use the `display` lane in a WHERE predicate — display values are computed, not stored."
            )
        if head == _DATA_LANE_PREFIX:
            if len(field_path.steps) < 2 or not isinstance(field_path.steps[1], DotStep):
                raise SearchExecutionError("A `data` lane path needs a field, e.g. `<var>.data.<field>`.")
            data_lane_fields.add(field_path.steps[1].name)

    # Node types only. `edge` is itself a registered (BaseModel-backed) type,
    # so it must be excluded by entity_type — a labelless MATCH (n) is a node
    # pattern; edges are matched by edge patterns. `registered` is the sorted
    # (entity_type, model) list of node types.
    registered: list[tuple[str, type]] = [
        (entity_type, get_model_class(entity_type))
        for entity_type in sorted(list_entity_types())
        if entity_type != "edge"
    ]

    if not data_lane_fields:
        # Spine-only (or absent) WHERE — one Entity-spine scan, scoped to the
        # registered node types so edges and unregistered rows are excluded.
        qs = Entity.objects.using(db_alias).filter(entity_type__in=[et for et, _ in registered])
        if scoped_pred is not None:
            qs = qs.filter(_predicate_to_q(scoped_pred, inputs, _bare_spine_orm_path))
        entities = list(qs)
    else:
        # Data-lane WHERE — AND-only, so a type missing a field can be skipped
        # wholesale (an unsatisfiable AND); OR / NOT would need per-type branch
        # pruning, deferred.
        if not _is_pure_conjunction(scoped_pred):
            raise SearchExecutionError(
                "A labelless MATCH (n) with a data-lane WHERE supports only AND-joined comparisons; "
                "OR / NOT over data-lane fields is not supported yet."
            )
        matched_ids: set[Any] = set()
        for _entity_type, model_cls in registered:
            model_fields = {f.name for f in model_cls._meta.get_fields()}
            if not data_lane_fields.issubset(model_fields):
                continue  # this type lacks a referenced data field — matches nothing
            model_qs = model_cls.objects.using(db_alias).filter(
                _predicate_to_q(
                    scoped_pred,
                    inputs,
                    lambda fp, m=model_cls: _typescan_orm_path(fp, m),
                    lambda fp, m=model_cls: _declared_data_types(m, fp),
                )
            )
            matched_ids.update(model_qs.values_list("entity_id", flat=True))
        entities = list(Entity.objects.using(db_alias).filter(pk__in=sorted(matched_ids))) if matched_ids else []

    return {"nodes": _serialize_entity_nodes(entities, layer, db_alias), "edges": []}


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_entity_nodes(
    entities: list[Any],
    layer: SubgraphLayer,
    db_alias: str,
) -> list[dict[str, Any]]:
    """Serialize Entity objects to node dicts at the requested layer."""
    if layer == "lite":
        return [serialize_node_lite(e) for e in entities]

    typed_models = batch_resolve_typed_models(entities, db_alias)

    if layer == "full":
        return [serialize_node_full(e, typed_models.get(str(e.pk))) for e in entities]

    # extended
    slugs = {e.entity_type for e in entities if e.entity_type != "edge"}
    icon_map = batch_resolve_icon_urls(slugs)
    display_map = batch_resolve_display(slugs)

    return [
        serialize_node_extended(
            e,
            typed_models.get(str(e.pk)),
            icon_url=icon_map.get(e.entity_type, ""),
            tap_viz_hints=display_map.get(e.entity_type, {}),
        )
        for e in entities
    ]


def _serialize_typed_nodes(
    domain_objects: list[Any],
    layer: SubgraphLayer,
    db_alias: str,
) -> list[dict[str, Any]]:
    """Serialize typed model instances (with pre-fetched entity) to node dicts."""
    if layer == "lite":
        return [serialize_node_lite(obj.entity) for obj in domain_objects]

    if layer == "full":
        return [serialize_node_full(obj.entity, obj) for obj in domain_objects]

    # extended
    slugs = {obj.entity.entity_type for obj in domain_objects}
    icon_map = batch_resolve_icon_urls(slugs)
    display_map = batch_resolve_display(slugs)

    return [
        serialize_node_extended(
            obj.entity,
            obj,
            icon_url=icon_map.get(obj.entity.entity_type, ""),
            tap_viz_hints=display_map.get(obj.entity.entity_type, {}),
        )
        for obj in domain_objects
    ]


# ---------------------------------------------------------------------------
# v2: advanced executor (aggregation, NOT EXISTS, multi-hop)
# ---------------------------------------------------------------------------
#
# Routed to when the AST has any of:
#   - NOT EXISTS clause
#   - aggregate call in RETURN
#   - multi-hop MATCH pattern
#
# Builds a single Django queryset against Edge, applies WHERE and NOT EXISTS
# filters, and optionally performs GROUP BY + COUNT. Returns the canonical
# envelope with a `rows` field populated for aggregating queries.

# Whether a variable binds to the left, right, or edge of a hop.
# "from" = left endpoint of hop N, "to" = right endpoint, "edge" = the edge itself.


def _node_label_to_related(label: str | None) -> str | None:
    """Translate a gryphon node label (entity_type slug) to the Django reverse-relation name.

    Uses the class-name lowercase convention (BaseModel's `related_name="%(class)s"`):
    `finding` → `finding`, `exception` → `complianceexception`, etc.
    Returns None if the label is not registered.
    """
    if not label:
        return None
    from tap_grid.registry import get_model_class

    try:
        model_cls = get_model_class(label)
    except KeyError:
        return None
    return model_cls.__name__.lower()


# Entity-level (spine) field names — sourced from Entity.SPINE_FIELD_NAMES,
# the canonical surface defined by spec-grid-entity (req-grid-entity-spine-surface).
# Computed lazily because importing Entity at module top would create a circular
# import.
def _spine_field_names() -> frozenset[str]:
    from tap_grid.models import Entity

    # Exclude `entity_id` from the spine-traversal set: it's a spine field for
    # the envelope but the path resolver handles it specially via the FK column
    # (`_orm_path_for_field`'s entity_id branch) rather than through a generic
    # `__entity__<field>` JOIN.
    return frozenset(Entity.SPINE_FIELD_NAMES) - {"entity_id"}


# Envelope-aware path prefixes — see spec-grid-traversal-language
# (req-grid-traversal-lang-envelope-paths). Reserved names that must not
# collide with spine field names.
_DATA_LANE_PREFIX = "data"
_DISPLAY_LANE_PREFIX = "display"


def _compute_hop_paths(pattern: PathPattern) -> list[dict[str, str]]:
    """Compute per-hop ORM path prefixes for a chain rooted at `Edge` (hop 0).

    For a chain ``(a)-[e0:R1]->(b)-[e1:R2]->(c)``:
      - hop 0: edge_path="", from_path="from_entity", to_path="to_entity"
      - hop 1: edge_path="to_entity__edges_out",
               from_path="to_entity",
               to_path="to_entity__edges_out__to_entity"

    Each subsequent hop extends the previous hop's shared-node path by one of:
      - ``__edges_out`` when the next hop is ``->``
      - ``__edges_in``  when the next hop is ``<-``

    The shared node between hop N and hop N+1 is the variable that appears on
    the right of hop N's edge — which is hop N's ``to_entity`` for ``->`` and
    ``from_entity`` for ``<-``.
    """
    if not pattern.edges:
        return []

    paths: list[dict[str, str]] = [
        {
            "edge_path": "",
            "from_path": "from_entity",
            "to_path": "to_entity",
        }
    ]

    for k in range(1, len(pattern.edges)):
        prev = paths[k - 1]
        prev_dir = pattern.edges[k - 1].direction
        cur_dir = pattern.edges[k].direction

        # Previous hop's right side — which holds the shared node between hops.
        if prev_dir == "out":
            shared = prev["to_path"]
        else:  # "in"
            shared = prev["from_path"]

        if cur_dir == "out":
            edge_path = f"{shared}__edges_out"
            from_path = shared
            to_path = f"{edge_path}__to_entity"
        else:  # "in"
            edge_path = f"{shared}__edges_in"
            to_path = shared
            from_path = f"{edge_path}__from_entity"

        paths.append(
            {
                "edge_path": edge_path,
                "from_path": from_path,
                "to_path": to_path,
            }
        )

    return paths


def _build_var_bindings(pattern: PathPattern) -> dict[str, dict[str, Any]]:
    """Map each variable in a pattern to ORM paths from the base Edge queryset.

    Each binding carries either:
      - ``role="node"`` with ``entity_path`` (path to the Edge FK that points at
        the node's Entity — e.g. ``"from_entity"``, ``"to_entity__edges_out__to_entity"``)
      - ``role="edge"`` with ``edge_path`` (path from the Edge root to the hop's
        Edge record — ``""`` for hop 0, ``"to_entity__edges_out"`` for hop 1, etc.)

    Node-only patterns (no edges) bind the lone node with ``side="lone"`` — the
    caller handles this via a domain-model scan rather than the chained Edge qs.
    """
    bindings: dict[str, dict[str, Any]] = {}

    if not pattern.edges:
        if pattern.nodes:
            n = pattern.nodes[0]
            if n.variable:
                bindings[n.variable] = {
                    "role": "node",
                    "side": "lone",
                    "label": n.label,
                }
        return bindings

    hop_paths = _compute_hop_paths(pattern)

    for hop_idx, edge in enumerate(pattern.edges):
        left = pattern.nodes[hop_idx]
        right = pattern.nodes[hop_idx + 1]
        hp = hop_paths[hop_idx]

        if edge.direction == "out":
            left_path = hp["from_path"]
            right_path = hp["to_path"]
        else:  # "in"
            left_path = hp["to_path"]
            right_path = hp["from_path"]

        if left.variable and left.variable not in bindings:
            bindings[left.variable] = {
                "role": "node",
                "entity_path": left_path,
                "label": left.label,
            }
        if right.variable and right.variable not in bindings:
            bindings[right.variable] = {
                "role": "node",
                "entity_path": right_path,
                "label": right.label,
            }
        if edge.variable and edge.variable not in bindings:
            bindings[edge.variable] = {
                "role": "edge",
                "edge_path": hp["edge_path"],
            }

    return bindings


def _orm_path_for_field(binding: dict[str, Any], field: str) -> str:
    """Build a Django ORM lookup string for a single-step ``var.field`` access.

    Handles spine-only single-step paths. Multi-step paths (the
    `data.<...>` / `display.<...>` envelope lanes) go through
    :func:`_orm_path_for_envelope_path` instead.
    """
    spine_fields = _spine_field_names()
    role = binding["role"]

    if role == "edge":
        ep = binding["edge_path"]
        prefix = f"{ep}__" if ep else ""
        if field == "entity_id":
            return f"{prefix}entity_id" if prefix else "entity_id"
        if field in spine_fields:
            return f"{prefix}entity__{field}"
        # Reserved lane-prefix names: never resolve as a spine field.
        if field in {_DATA_LANE_PREFIX, _DISPLAY_LANE_PREFIX}:
            raise SearchExecutionError(
                f"Bare `{field}` is not a complete path. Use `{field}.<...>` to " f"address the {field} lane."
            )
        # Edge model fields (edge_type, properties, batch_id, flip_map, description)
        # live in the `data` lane and require the explicit prefix.
        raise SearchExecutionError(
            f"Field {field!r} is not a spine field. If it lives on the per-edge "
            f"row (e.g. `edge_type`, `properties`), address it as "
            f"`<var>.data.{field}` per spec-grift-envelope."
        )

    # role == "node"
    # Node-only patterns bind with side="lone" and don't participate in Edge chains.
    if binding.get("side") == "lone":
        raise SearchExecutionError(
            "Node-only patterns cannot be used in predicates or RETURN paths in the advanced executor."
        )

    ep = binding["entity_path"]

    # entity_path always terminates in `from_entity` or `to_entity` (an FK on Edge).
    # Resolve entity_id via the `_id` FK column so we avoid a redundant JOIN to
    # the Entity table and sidestep the fact that Entity's primary key is `id`,
    # not `entity_id`.
    if field == "entity_id":
        return f"{ep}_id"

    if field in spine_fields:
        return f"{ep}__{field}"

    if field in {_DATA_LANE_PREFIX, _DISPLAY_LANE_PREFIX}:
        raise SearchExecutionError(
            f"Bare `{field}` is not a complete path. Use `{field}.<...>` to " f"address the {field} lane."
        )

    raise SearchExecutionError(
        f"Field {field!r} is not a spine field. If it lives on the per-model "
        f"row, address it as `<var>.data.{field}` per spec-grift-envelope."
    )


def _orm_path_for_envelope_path(binding: dict[str, Any], steps: list[Any]) -> str:
    """Build a Django ORM lookup string for an envelope-aware multi-step path.

    Per spec-grid-traversal-language § Envelope-Aware Field Paths
    (req-grid-traversal-lang-envelope-paths):

    - ``n.data.<x>...`` → join through to the per-model row and walk
      remaining steps as Django ``__``-joined lookups. Multi-step access
      into JSONField columns (e.g. ``n.data.tags.Project``) maps to
      Django's native nested JSONField lookup syntax
      (``tags__Project``).
    - ``n.display.<x>...`` → rejected; display values are computed for
      rendering, not stored. Filter via the underlying per-model fields
      instead, or use the ``extended`` return layer for display data.
    - Any other multi-step path → rejected with a message naming the
      expected envelope-lane prefix.

    The compiler only generates dot-step components when assembling the
    Django path (key-step bracket notation and wildcards stay reserved
    for the JSONPath compiler in
    ``req-grid-traversal-lang-filters-jsonpath``).
    """
    if not steps or not isinstance(steps[0], DotStep):
        raise SearchExecutionError("Multi-step field paths must start with a dot-step.")
    head = steps[0].name

    if head == _DISPLAY_LANE_PREFIX:
        raise SearchExecutionError(
            "Cannot use the `display` lane in WHERE/RETURN paths today — "
            "display values are computed for rendering, not stored. Filter on "
            "the per-model fields under `<var>.data.<x>` instead, or use the "
            "`extended` return layer when serializing for display."
        )

    # Multi-step walking into a JSON-typed spine field — today only
    # `dimensions`. Compiles to a JSONField nested-key lookup rooted on the
    # spine.
    if head in _JSON_TYPED_SPINE_FIELDS:
        rest = steps[1:]
        for step in rest:
            if not isinstance(step, DotStep) and not isinstance(step, KeyStep):
                raise SearchExecutionError("Spine JSON access supports dot-steps and bracket-key " "steps only.")
        inner_path = "__".join(s.name if isinstance(s, DotStep) else s.key for s in rest)
        role = binding["role"]
        if role == "edge":
            ep = binding["edge_path"]
            prefix = f"{ep}__" if ep else ""
            return f"{prefix}entity__{head}__{inner_path}"
        ep = binding["entity_path"]
        return f"{ep}__{head}__{inner_path}"

    if head != _DATA_LANE_PREFIX:
        raise SearchExecutionError(
            f"Unknown envelope-lane prefix {head!r}. Use a spine field "
            f"({sorted(_spine_field_names() | {'entity_id'})}), the `data` "
            f"prefix for per-model fields, `dimensions.<key>` for dimension "
            f"scoping, or `display` for computed render values (read-only)."
        )

    rest = steps[1:]
    if not rest:
        raise SearchExecutionError(
            "Path `<var>.data` requires at least one further step " "(e.g. `<var>.data.<field>`)."
        )
    for step in rest:
        if not isinstance(step, DotStep) and not isinstance(step, KeyStep):
            raise SearchExecutionError(
                "Inside the `data` lane only dot-steps and bracket-key steps "
                "are supported in v1; indexed and wildcard access via JSONPath "
                "is tracked separately (req-grid-traversal-lang-filters-jsonpath)."
            )
    inner_path = "__".join(s.name if isinstance(s, DotStep) else s.key for s in rest)

    role = binding["role"]
    if role == "edge":
        # Edges' "data" lane is the Edge model row itself — fields are
        # already on the chained Edge queryset.
        from tap_grid.models import Edge

        _validate_data_lane_steps(Edge, rest)
        ep = binding["edge_path"]
        prefix = f"{ep}__" if ep else ""
        return f"{prefix}{inner_path}"

    # role == "node"
    if binding.get("side") == "lone":
        raise SearchExecutionError(
            "Node-only patterns cannot be used in predicates or RETURN paths in the advanced executor."
        )

    ep = binding["entity_path"]
    label = binding.get("label")
    reverse = _node_label_to_related(label)
    if reverse is None or label is None:
        raise SearchExecutionError(
            f"Cannot resolve `data.{rest[0].name}` on a variable without a "
            f"node label; add a label like `(var:entity_type)` so the "
            f"executor knows which model to traverse."
        )
    from tap_grid.registry import get_model_class

    _validate_data_lane_steps(get_model_class(label), rest)
    return f"{ep}__{reverse}__{inner_path}"


def _resolve_orm_path(binding: dict[str, Any], field_path: FieldPath) -> str:
    """Single entry point: translate a Gryphon FieldPath to an ORM path.

    TAP-IMPLEMENTS: req-grid-traversal-lang-envelope-paths@2188517c4ca3/f88ad9d8b179 (derivation)
        — envelope-shape field-path literals resolve to ORM paths here.

    Dispatches to :func:`_orm_path_for_field` for single-step spine paths
    or :func:`_orm_path_for_envelope_path` for multi-step envelope-lane
    paths. Per spec-grid-traversal-language § Envelope-Aware Field Paths.

    .. tap:capability:: Gryphon envelope-aware field paths
       :id: cap-grid-gryphon-field-paths
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:dimensions-scan-filters-pg-node-by-a-dimension-value
       :limitations: The ``display`` lane is not addressable in WHERE/RETURN; JSON access is dot/bracket-only for now.

       A field path resolves against the canonical envelope: bare spine fields,
       the ``data`` lane for per-model fields, and ``dimensions`` keys.

       Example::

          MATCH (n:grid_fixtures__node) WHERE n.dimensions.zone = "north"
    """
    steps = field_path.steps
    if not steps:
        raise SearchExecutionError("FieldPath must have at least one step.")
    if len(steps) == 1 and isinstance(steps[0], DotStep):
        return _orm_path_for_field(binding, steps[0].name)
    return _orm_path_for_envelope_path(binding, list(steps))


def _resolve_value(value: Any, inputs: dict[str, Any]) -> Any:
    """Resolve a gryphon value to a Python value (ParamRef → looked up in inputs)."""
    if isinstance(value, ParamRef):
        return inputs.get(value.name)
    return value


def _build_chain_queryset(
    pattern: PathPattern,
    db_alias: str,
    inputs: dict[str, Any] | None = None,
    *,
    predicate: Predicate | None = None,
    bindings: dict[str, dict[str, Any]] | None = None,
):
    """Build an Edge queryset that joins all hops of a (potentially multi-hop) pattern.

    TAP-IMPLEMENTS: req-grid-gryphon-multihop@71eb89405815/eb75eb5eca25 (derivation) — the
        multi-hop chain join is built here.

    TAP-IMPLEMENTS: req-grid-gryphon-multihop-envelope@4f3ae2b1e7d6/eb75eb5eca25 (derivation) —
        the multi-hop graph-envelope return rides the same chain build.

    The queryset is rooted at hop 0's Edge and each subsequent hop is reached
    via the shared-node reverse-FK relation (``edges_out`` / ``edges_in``). Edge
    types and endpoint labels are applied as filter conditions on their
    respective hop paths.

    All hop filters are collapsed into a single ``.filter(**kwargs)`` call so
    Django composes one JOIN per unique reverse-FK path — the standard trick
    for avoiding the "multi-filter spawns separate joins" behavior.

    When ``predicate`` is given, its compiled ``Q`` is folded into that SAME
    ``.filter()`` call (``bindings`` maps its variables to ORM paths). This is
    load-bearing for a multi-hop WHERE on a node BEYOND the root edge: that
    predicate resolves through a reverse-FK path (``to_entity__edges_out__…``)
    identical to a structural hop path, so applying it in a *separate*
    ``.filter()`` made Django spawn a SECOND join for that path — one carrying
    none of the structural edge-type / label filters — which the projection then
    bound to, silently returning far nodes reached by the wrong edge type (and
    inflating COUNT). Folding it into the one call reuses the structural join, so
    the predicate constrains exactly the chain's far node. Callers that cannot
    fold (the ``NOT EXISTS`` inner, whose correlation layers on afterward) apply
    it via :func:`_apply_predicate_to_qs` instead.

    Variable-length edges and undirected edges are rejected up front.

    .. tap:capability:: Gryphon multi-hop chain traversal
       :id: cap-grid-gryphon-multi-hop
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:multi_hop-anchored-two-hop-chain-returns-the-root-s-reachable-subgraph
       :limitations: Variable-length (``*m..n``) and undirected chain edges parse but the executor rejects them.

       A MATCH pattern with two or more edge hops joins each hop by its shared
       node, returning the reachable subgraph or a row projection.

       Example::

          MATCH (a:grid_fixtures__node)-[e1:PG_LINKS__grid_fixtures]->(b:grid_fixtures__node)-[e2:PG_LINKS__grid_fixtures]->(c:grid_fixtures__node)
          WHERE a.entity_id = $root_id
    """
    from tap_grid.models import Edge

    for edge in pattern.edges:
        if edge.min_hops != 1 or edge.max_hops != 1:
            raise SearchExecutionError(
                "Variable-length edge patterns (-[:E*m..n]->) are grammar-accepted but not "
                "supported by the executor; defer to a future iteration."
            )
        if edge.direction == "any":
            raise SearchExecutionError(
                "Undirected edge patterns are not supported by the aggregation executor; use -> or <-."
            )

    hop_paths = _compute_hop_paths(pattern)
    qs = Edge.objects.using(db_alias)

    filters: dict[str, Any] = {}

    for hop_idx, edge in enumerate(pattern.edges):
        hp = hop_paths[hop_idx]
        ep = hp["edge_path"]
        prefix = f"{ep}__" if ep else ""

        if edge.edge_type:
            filters[f"{prefix}edge_type"] = edge.edge_type

        # Inline edge-property map filter: `-[:T {key: "value"}]->` narrows the
        # queryset by JSON-key equality on Edge.properties. Per
        # req-grid-traversal-lang-filters-1; closes the silent-drop bug where
        # the parser accepted the map but the executor ignored it.
        for key, raw_value in edge.inline_props.items():
            value = _resolve_value(raw_value, inputs or {})
            filters[f"{prefix}properties__{key}"] = value

        left = pattern.nodes[hop_idx]
        right = pattern.nodes[hop_idx + 1]
        if edge.direction == "out":
            left_path, right_path = hp["from_path"], hp["to_path"]
        else:  # "in"
            left_path, right_path = hp["to_path"], hp["from_path"]

        if left.label:
            filters[f"{left_path}__entity_type"] = left.label
        if right.label:
            filters[f"{right_path}__entity_type"] = right.label

    from django.db.models import Q

    pred_q = _chain_predicate_q(
        predicate,
        bindings if bindings is not None else _build_var_bindings(pattern),
        inputs or {},
    )
    # Structural filters first, then the WHERE predicate — a single `.filter()`
    # so every reverse-FK path resolves to one shared join (structural + WHERE +
    # projection alike). Order matches the former structural-then-predicate chain
    # so single-valued (root-edge / anchored) predicates compile to identical SQL.
    if pred_q is not None:
        qs = qs.filter(Q(**filters), pred_q)
    elif filters:
        qs = qs.filter(**filters)

    return qs


def _binding_is_multivalued_hop(binding: dict[str, Any]) -> bool:
    """True if a binding is reached via a reverse-FK hop (a node/edge past the root edge).

    Hop-0 nodes bind to the root Edge's own forward FKs (``from_entity`` /
    ``to_entity``, single-valued); every hop ≥ 1 node/edge is reached through a
    multi-valued reverse relation (``edges_out`` / ``edges_in``).
    """
    path = binding.get("entity_path") or binding.get("edge_path") or ""
    return "edges_out" in path or "edges_in" in path


def _guard_negated_far_predicate(
    predicate: Predicate | None,
    bindings: dict[str, dict[str, Any]],
    *,
    negated: bool = False,
) -> None:
    """Reject a NEGATED equality/``IN`` predicate on a far (multi-valued-hop) node.

    A far node's field path resolves through a reverse-FK relation
    (``to_entity__edges_out__…``). Applied positively it is a per-row filter on
    the structurally-joined far node (correct — see :func:`_build_chain_queryset`).
    But Django compiles a *negated* comparison over a multi-valued relation
    (``~Q(reverse_path__field=…)``) as an existential anti-join subquery, which
    (a) crashes with ``operator does not exist: bigint = uuid`` — the subquery
    correlates on the model's bigint pk against the Entity uuid — and (b) even
    when it does not crash carries existential ("no reachable far node matches"),
    not per-binding ("this bound far node does not match"), semantics. Rather than
    emit invalid SQL or a silently-wrong answer, reject it: apply-or-reject.

    A leaf negates over its path when its EFFECTIVE parity is odd: the syntactic
    ``NOT`` nesting XOR the ``!=`` operator (which itself lowers to ``~Q`` — see
    :func:`_comparison_to_q`). So `c.x != v`, `NOT (c.x = v)`, and `NOT (c.x IN
    […])` all trip this on a far node, while `NOT (c.x != v)` (double negation)
    does not. ``IS NULL`` / ``IS KNOWN`` leaves lower to ``__isnull`` (negation
    flips cleanly, no subquery); positive / ``OR`` / non-negated ``IN`` forms and
    any negation over single-valued (root-edge) hops are unaffected. Row-level
    negation of a far-node predicate is a named deferred gap (it needs per-field
    ``F()`` annotation so the negation lands on the joined column, not the
    relation path).
    """
    if predicate is None:
        return
    if isinstance(predicate, (Comparison, InComparison)):
        # `!=` lowers to `~Q(...)`, so it flips the effective negation parity.
        effective = negated ^ (isinstance(predicate, Comparison) and predicate.op == "!=")
        if not effective:
            return
        binding = bindings.get(predicate.field_path.variable)
        if binding is not None and _binding_is_multivalued_hop(binding):
            raise SearchExecutionError(
                "A negated comparison (`!=` or `NOT (...)`) or negated IN on a node "
                "beyond the root edge of a multi-hop pattern (here on variable "
                f"'{predicate.field_path.variable}') is not supported: negating a "
                "predicate over a reverse-FK traversal would compile to an "
                "existential anti-join with the wrong (per-pattern, not "
                "per-binding) semantics. Express it positively (e.g. an `IN` of the "
                "allowed values, or `<`/`>` bounds), move the predicate onto the "
                "root edge's endpoints, or use `NOT EXISTS { ... }` for a true "
                "anti-join."
            )
        return
    if isinstance(predicate, (IsNullComparison, ObservationComparison)):
        return
    if isinstance(predicate, AndPred):
        _guard_negated_far_predicate(predicate.left, bindings, negated=negated)
        _guard_negated_far_predicate(predicate.right, bindings, negated=negated)
        return
    if isinstance(predicate, OrPred):
        _guard_negated_far_predicate(predicate.left, bindings, negated=negated)
        _guard_negated_far_predicate(predicate.right, bindings, negated=negated)
        return
    if isinstance(predicate, NotPred):
        _guard_negated_far_predicate(predicate.operand, bindings, negated=not negated)
        return


def _chain_predicate_q(
    predicate: Predicate | None,
    bindings: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
):
    """Compile a WHERE predicate over chain bindings into a Django ``Q`` (or None).

    The full AND / OR / NOT tree is compiled by :func:`_predicate_to_q`; each
    leaf's field path resolves against its bound variable, with data-lane type
    strictness consulted per bound node's ``FIELD_CRUD_SCHEMA``. Returns ``None``
    when there is nothing to apply so callers can fold-or-skip.

    Kept separate from application so a chain query can fold the predicate ``Q``
    into the SAME ``.filter()`` call as its structural hop filters — see
    :func:`_build_chain_queryset`.
    """
    if predicate is None:
        return None

    _guard_negated_far_predicate(predicate, bindings)

    from tap_grid.registry import get_model_class

    def _resolve(field_path: FieldPath) -> str:
        var = field_path.variable
        if var not in bindings:
            raise SearchExecutionError(f"Unknown variable '{var}' in WHERE predicate.")
        return _resolve_orm_path(bindings[var], field_path)

    def _declared(field_path: FieldPath) -> set[str] | None:
        # Resolve the bound node's model so data-lane type-strictness can consult
        # its FIELD_CRUD_SCHEMA. Skip when the leaf is on an unlabelled node or an
        # edge variable (edge properties carry no typed data-lane schema).
        binding = bindings.get(field_path.variable)
        if not binding or binding.get("role") != "node" or not binding.get("label"):
            return None
        return _declared_data_types(get_model_class(binding["label"]), field_path)

    return _predicate_to_q(predicate, inputs, _resolve, _declared)


def _apply_predicate_to_qs(
    qs,
    predicate: Predicate | None,
    bindings: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
):
    """Apply a WHERE predicate tree to an already-built chain queryset.

    TAP-IMPLEMENTS: req-grid-traversal-lang-filters@d6c08fa3c3ac/7b84984d6834 (derivation) —
        WHERE field filtering lowers to the queryset here.

    TAP-IMPLEMENTS: req-grid-traversal-lang-combinators@0e5170677022/7b84984d6834 (derivation) —
        AND / OR / NOT predicate combination lowers here.

    Thin wrapper over :func:`_chain_predicate_q` used where the predicate cannot
    be folded into the structural filter — the ``NOT EXISTS`` inner queryset
    (which the outer correlation is layered onto separately). The multi-hop /
    single-clause chain path instead passes the predicate straight to
    :func:`_build_chain_queryset` so it lands in one ``.filter()`` (no duplicate
    join on far-node predicates).

    .. tap:capability:: Gryphon WHERE predicates
       :id: cap-grid-gryphon-where
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:combinators-parenthesized-grouping-overrides-and-or-precedence

       WHERE filters a pattern by comparisons (``= != < > <= >=``, ``IN``) over
       field paths and inline edge-property maps, combined with ``AND``, ``OR``,
       ``NOT``, and parenthesized grouping.

       Example::

          MATCH (n:grid_fixtures__node)
          WHERE n.data.kind = "neighbor"
                AND (n.data.severity_score < 15 OR n.data.severity_score > 25)
    """
    q = _chain_predicate_q(predicate, bindings, inputs)
    return qs if q is None else qs.filter(q)


def _flatten_conjunction(
    predicate: Predicate,
) -> list[Comparison | InComparison | IsNullComparison | ObservationComparison]:
    """Flatten an AND tree into a list of comparison leaves.

    A leaf is a `Comparison`, `InComparison`, or `IsNullComparison`. OR / NOT
    are rejected. Only the OPTIONAL MATCH executor uses this now — it keeps an
    AND-only WHERE so the mandatory/optional-variable split stays well-defined;
    the type-scan and multi-hop WHERE paths compile the full tree via
    :func:`_predicate_to_q`.
    """
    if isinstance(predicate, (Comparison, InComparison, IsNullComparison, ObservationComparison)):
        return [predicate]
    if isinstance(predicate, AndPred):
        return _flatten_conjunction(predicate.left) + _flatten_conjunction(predicate.right)
    raise SearchExecutionError(
        "This WHERE clause supports only AND-joined comparisons; OR and NOT are not "
        "supported here (OPTIONAL MATCH v0 keeps an AND-only WHERE)."
    )


def _predicate_to_q(predicate: Predicate, inputs: dict[str, Any], resolve: Any, declared_types: Any = None):
    """Compile a WHERE predicate tree into a single Django ``Q`` expression.

    ``AND`` / ``OR`` / ``NOT`` and parenthesized grouping lower to ``Q`` ``&`` /
    ``|`` / ``~``; a ``Comparison`` / ``InComparison`` leaf lowers via
    :func:`_comparison_to_q`; an ``IsNullComparison`` leaf lowers directly to
    a ``__isnull`` lookup (``Q(path__isnull=True/False)``). ``resolve`` maps a
    leaf's ``FieldPath`` to its ORM lookup path — the type-scan and chain
    executors pass different resolvers because their querysets are rooted
    differently.
    """
    from django.db.models import Q

    if isinstance(predicate, (Comparison, InComparison)):
        return _comparison_to_q(predicate, resolve(predicate.field_path), inputs, declared_types)
    if isinstance(predicate, IsNullComparison):
        path = resolve(predicate.field_path)
        return Q(**{f"{path}__isnull": not predicate.negated})
    if isinstance(predicate, ObservationComparison):
        # Null axis: IS UNKNOWN -> __isnull=True, IS KNOWN -> __isnull=False.
        # Type-agnostic (req-grid-traversal-lang-observation).
        path = resolve(predicate.field_path)
        return Q(**{f"{path}__isnull": predicate.kind == "unknown"})
    if isinstance(predicate, AndPred):
        return _predicate_to_q(predicate.left, inputs, resolve, declared_types) & _predicate_to_q(
            predicate.right, inputs, resolve, declared_types
        )
    if isinstance(predicate, OrPred):
        return _predicate_to_q(predicate.left, inputs, resolve, declared_types) | _predicate_to_q(
            predicate.right, inputs, resolve, declared_types
        )
    if isinstance(predicate, NotPred):
        return ~_predicate_to_q(predicate.operand, inputs, resolve, declared_types)
    raise SearchExecutionError(f"Unsupported WHERE predicate node: {type(predicate).__name__}")


def _apply_not_exists(
    outer_qs,
    nec: NotExistsClause,
    outer_bindings: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
    db_alias: str,
):
    """Apply a NOT EXISTS clause to the outer queryset via a correlated Exists subquery.

    TAP-IMPLEMENTS: req-grid-gryphon-not-exists@3b83b2e9236b/68b3daf8df2a (derivation) — the
        correlated NOT EXISTS anti-join is applied here.

    .. tap:capability:: Gryphon NOT EXISTS anti-join
       :id: cap-grid-gryphon-not-exists
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:not_exists-not-exists-excludes-targets-that-have-a-guard-edge
       :limitations: Bare ``EXISTS`` and nested ``NOT EXISTS`` are rejected.

       ``NOT EXISTS { MATCH ... }`` keeps an outer row only when the correlated
       inner pattern has no match — a correlated anti-join.

       Example::

          MATCH (s)-[e:PG_LINKS__grid_fixtures]->(t)
          NOT EXISTS { MATCH (g)-[:PG_OPTIONAL__grid_fixtures]->(t) }
    """
    from django.db.models import Exists, F, OuterRef

    if len(nec.match_clause.patterns) != 1:
        raise SearchExecutionError("NOT EXISTS subqueries require exactly one pattern.")
    inner_pattern = nec.match_clause.patterns[0]
    if len(inner_pattern.edges) == 0:
        raise SearchExecutionError("NOT EXISTS subqueries require at least one edge in the inner pattern.")

    inner_bindings = _build_var_bindings(inner_pattern)
    inner_qs = _build_chain_queryset(inner_pattern, db_alias, inputs)

    # Correlation: for every variable shared between outer and inner bindings,
    # constrain the inner's ORM path to equal OuterRef of the outer's path.
    # sorted() so the correlation annotations and filters below are built in a
    # deterministic order — keeps the captured NOT EXISTS SQL stable across runs.
    shared = sorted(set(outer_bindings.keys()) & set(inner_bindings.keys()))
    if not shared:
        raise SearchExecutionError("NOT EXISTS subqueries must share at least one variable with the outer pattern.")

    # Pre-annotate outer qs with F-aliases for each shared variable's entity_id.
    # Without this, OuterRef on a multi-hop reverse-FK path (e.g. "to_entity__
    # edges_out__to_entity_id") causes Django to add a *second* JOIN rather than
    # reuse the chain's existing one — duplicating rows in the outer count.
    outer_alias_map: dict[str, str] = {}
    outer_annotations: dict[str, Any] = {}
    for var in shared:
        outer_bind = outer_bindings[var]
        outer_path = _orm_path_for_field(outer_bind, "entity_id")
        alias = f"_corr_{var}_id"
        outer_annotations[alias] = F(outer_path)
        outer_alias_map[var] = alias
    if outer_annotations:
        outer_qs = outer_qs.annotate(**outer_annotations)

    for var in shared:
        inner_bind = inner_bindings[var]
        inner_path = _orm_path_for_field(inner_bind, "entity_id")
        inner_qs = inner_qs.filter(**{inner_path: OuterRef(outer_alias_map[var])})

    # Apply the inner WHERE predicates.
    inner_qs = _apply_predicate_to_qs(
        inner_qs,
        nec.where_clause.predicate if nec.where_clause else None,
        inner_bindings,
        inputs,
    )

    return outer_qs.filter(~Exists(inner_qs))


def _is_typescan_envelope_query(ast: GryphonAST) -> bool:
    """True when the AST is a single labelled type-scan with envelope RETURN.

    The narrow shape that `req-grid-gryphon-order-by-envelope` extends ORDER BY
    / LIMIT to in v0: exactly one MATCH clause, exactly one pattern, node-only
    (no edges) with a label, no NOT EXISTS / OPTIONAL MATCH, and a graph-
    envelope RETURN. Anything else is rejected by the top-level guard so the
    v0 boundary is legible to readers and future authors.
    """
    if not _is_graph_envelope_return(ast.return_clause):
        return False
    if len(ast.match_clauses) != 1:
        return False
    if ast.not_exists_clauses or ast.optional_match_clauses:
        return False
    mc = ast.match_clauses[0]
    if len(mc.patterns) != 1:
        return False
    pattern = mc.patterns[0]
    if pattern.edges:
        return False
    if not pattern.nodes:
        return False
    node = pattern.nodes[0]
    return bool(node.label)


def _is_graph_envelope_return(return_clause: ReturnClause) -> bool:
    """True when the RETURN clause requests a graph envelope rather than row projection.

    TAP-IMPLEMENTS: req-grid-traversal-lang-returns@37d212f27bc0/8aab3409a23d (derivation) — the
        envelope-vs-rows default-packaging decision for RETURN is made here.

    Graph envelope is requested when:
    - RETURN is omitted (items is None) — return all bound variables, or
    - all RETURN items are bare variables (ReturnItem with no field steps or aggregates).

    .. tap:capability:: Gryphon RETURN modes
       :id: cap-grid-gryphon-return
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:type_scan-projection-return-of-aliased-field-paths

       An omitted RETURN (or one naming only bare variables) yields a graph
       envelope; a RETURN of field paths or aggregates yields a row projection.

       Example::

          MATCH (n:grid_fixtures__node) RETURN n.entity_id AS id, n.name AS label
    """
    if return_clause.items is None:
        return True
    for item in return_clause.items:
        if isinstance(item, AggregateReturnItem):
            return False
        if not isinstance(item, ReturnItem):
            return False
        if len(item.path.steps) > 0:
            return False
    return True


def _collect_graph_envelope(
    qs,
    pattern: PathPattern,
    return_clause: ReturnClause,
    bindings: dict[str, dict[str, Any]],
    *,
    layer: SubgraphLayer,
    db_alias: str,
) -> dict[str, Any]:
    """Collect a graph envelope (nodes + edges) from a multi-hop chain queryset.

    When RETURN is omitted, all bound node and edge variables are collected.
    When RETURN names bare variables, only those are collected.
    """
    # Determine which variables to collect. Order must be deterministic —
    # `bindings` is insertion-ordered (pattern order) and RETURN items keep
    # their written order — so the values_list column order, and the captured
    # SQL, are stable across runs. A set here made the advanced-envelope SQL
    # non-deterministic.
    if return_clause.items is None:
        requested_vars = list(bindings.keys())
    else:
        requested_vars = list(
            dict.fromkeys(item.path.variable for item in return_clause.items if isinstance(item, ReturnItem))
        )

    # Partition into node and edge variables and build values_list columns.
    node_columns: list[tuple[str, str]] = []  # (var_name, orm_path)
    edge_columns: list[tuple[str, str]] = []  # (var_name, orm_path)

    for var in requested_vars:
        if var not in bindings:
            raise SearchExecutionError(f"Unknown variable '{var}' in RETURN.")
        binding = bindings[var]
        if binding["role"] == "node":
            orm_path = _orm_path_for_field(binding, "entity_id")
            node_columns.append((var, orm_path))
        elif binding["role"] == "edge":
            orm_path = _orm_path_for_field(binding, "entity_id")
            edge_columns.append((var, orm_path))

    # A graph-envelope RETURN — omitted ("the whole matched subgraph") OR bare
    # variables naming only nodes — should carry the connecting edges so the
    # subgraph is useful. Collect every hop's edge via the structural hop paths,
    # which catches ANONYMOUS edges (`-[]->`, `-[:T]->`) that carry no variable
    # and so never reach `bindings`. Collecting only bound (named) edges here
    # silently dropped the connecting edge of `MATCH (a)-[]->(b) RETURN a, b`
    # (and every anonymous hop of a bare-variable multi-hop RETURN) — the model
    # oracle flagged the missing edge. The `seen_edge_paths` de-dup preserves any
    # named edge already collected from the RETURN.
    if return_clause.items is None or not edge_columns:
        seen_edge_paths = {path for _, path in edge_columns}
        for hop_idx, hop in enumerate(_compute_hop_paths(pattern)):
            edge_path = hop["edge_path"]
            orm_path = f"{edge_path}__entity_id" if edge_path else "entity_id"
            if orm_path not in seen_edge_paths:
                edge_columns.append((f"_hop{hop_idx}_edge", orm_path))
                seen_edge_paths.add(orm_path)

    all_columns = node_columns + edge_columns
    if not all_columns:
        return {"nodes": [], "edges": [], "rows": []}

    orm_paths = [path for _, path in all_columns]
    rows = qs.values_list(*orm_paths, named=False)

    # Collect distinct PKs.
    node_pks: set[str] = set()
    edge_entity_ids: set[str] = set()
    node_count = len(node_columns)

    for row in rows:
        for i, val in enumerate(row):
            if val is None:
                continue
            pk = str(val)
            if i < node_count:
                node_pks.add(pk)
            else:
                edge_entity_ids.add(pk)

    from tap_grid.models import Edge, Entity

    # Bulk-fetch entities and edges.
    # sorted() on the PK sets so the IN-list SQL is deterministic (Gridkin snapshots).
    entities = list(Entity.objects.using(db_alias).filter(pk__in=sorted(node_pks))) if node_pks else []
    edges = (
        list(Edge.objects.using(db_alias).filter(entity_id__in=sorted(edge_entity_ids)).select_related("entity"))
        if edge_entity_ids
        else []
    )

    nodes_out = _serialize_entity_nodes(entities, layer, db_alias)
    edges_out = _serialize_edge_list(edges, layer, db_alias)

    return {"nodes": nodes_out, "edges": edges_out, "rows": []}


def _filter_predicate_for_bindings(
    predicate: Predicate | None,
    bindings: dict[str, dict[str, Any]],
) -> Predicate | None:
    """Return only the parts of a predicate tree whose variables exist in bindings.

    Comparisons referencing unknown variables are dropped. AND nodes are
    reconstructed from surviving children; if both children are dropped the
    AND itself is dropped. OR and NOT predicates with unknown variables are
    dropped entirely (conservative — avoids incorrect disjunction scoping).
    """
    if predicate is None:
        return None
    if isinstance(predicate, (Comparison, InComparison, IsNullComparison, ObservationComparison)):
        if predicate.field_path.variable in bindings:
            return predicate
        return None
    if isinstance(predicate, AndPred):
        left = _filter_predicate_for_bindings(predicate.left, bindings)
        right = _filter_predicate_for_bindings(predicate.right, bindings)
        if left is not None and right is not None:
            return AndPred(left, right)
        return left or right
    # OR / NOT with unknown variables: drop to avoid incorrect semantics.
    if isinstance(predicate, OrPred):
        left = _filter_predicate_for_bindings(predicate.left, bindings)
        right = _filter_predicate_for_bindings(predicate.right, bindings)
        if left is not None and right is not None:
            return OrPred(left, right)
        return None
    if isinstance(predicate, NotPred):
        inner = _filter_predicate_for_bindings(predicate.operand, bindings)
        if inner is not None:
            return NotPred(inner)
        return None
    return None


def _build_clause_queryset(
    mc: MatchClause,
    ast: GryphonAST,
    inputs: dict[str, Any],
    db_alias: str,
) -> tuple[Any, PathPattern, dict[str, dict[str, Any]]]:
    """Build a filtered queryset for a single advanced MATCH clause.

    WHERE predicates are filtered to include only comparisons whose variables
    exist in this clause's bindings, allowing a shared WHERE to work across
    UNION multi-hop clauses with different variable sets.

    Returns (queryset, pattern, bindings).
    """
    if len(mc.patterns) != 1:
        raise SearchExecutionError("Advanced executor requires exactly one pattern per MATCH clause.")
    pattern = mc.patterns[0]
    if len(pattern.edges) == 0:
        raise SearchExecutionError("Advanced executor requires at least one edge in the MATCH pattern.")

    bindings = _build_var_bindings(pattern)

    # Filter WHERE predicate to only include comparisons on variables bound
    # in this clause. This allows UNION queries where each MATCH clause
    # declares different variables but shares a global WHERE.
    applicable_pred = _filter_predicate_for_bindings(
        ast.where_clause.predicate if ast.where_clause else None,
        bindings,
    )
    # Fold the WHERE into the chain queryset's single `.filter()` (not a separate
    # one) so a far-node predicate reuses the structural join instead of spawning
    # a duplicate — see `_build_chain_queryset`.
    qs = _build_chain_queryset(pattern, db_alias, inputs, predicate=applicable_pred, bindings=bindings)

    for nec in ast.not_exists_clauses:
        qs = _apply_not_exists(qs, nec, bindings, inputs, db_alias)

    return qs, pattern, bindings


def _execute_advanced(
    ast: GryphonAST,
    inputs: dict[str, Any],
    *,
    db_alias: str,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Route through the v2 aggregation/anti-join/multi-hop path.

    Supports multiple MATCH clauses with UNION semantics in graph envelope
    mode. Row projection (field paths / aggregates) requires a single clause.
    """
    is_envelope = _is_graph_envelope_return(ast.return_clause)

    # Row projection mode requires a single MATCH clause (bindings are clause-specific).
    if not is_envelope and len(ast.match_clauses) != 1:
        raise SearchExecutionError(
            "Row projection with field paths or aggregates requires exactly one "
            "top-level MATCH clause in the advanced executor."
        )

    # --- Graph envelope with UNION across multiple MATCH clauses ---
    if is_envelope:
        from tap_grid.models import Edge, Entity

        all_node_pks: set[str] = set()
        all_edge_entity_ids: set[str] = set()

        for mc in ast.match_clauses:
            qs, pattern, bindings = _build_clause_queryset(mc, ast, inputs, db_alias)
            envelope = _collect_graph_envelope(
                qs,
                pattern,
                ast.return_clause,
                bindings,
                layer="lite",
                db_alias=db_alias,
            )
            # Collect PKs from the lite-layer results for dedup before final serialize.
            for n in envelope["nodes"]:
                all_node_pks.add(str(n["entity_id"]))
            for e in envelope["edges"]:
                all_edge_entity_ids.add(str(e["entity_id"]))

        # Bulk-fetch and serialize at the requested layer.
        # sorted() on the PK sets so the IN-list SQL is deterministic (Gridkin snapshots).
        entities = list(Entity.objects.using(db_alias).filter(pk__in=sorted(all_node_pks))) if all_node_pks else []
        edges = (
            list(
                Edge.objects.using(db_alias).filter(entity_id__in=sorted(all_edge_entity_ids)).select_related("entity")
            )
            if all_edge_entity_ids
            else []
        )

        nodes_out = _serialize_entity_nodes(entities, layer, db_alias)
        edges_out = _serialize_edge_list(edges, layer, db_alias)

        result: dict[str, Any] = {"nodes": nodes_out, "edges": edges_out, "rows": []}

        has_unanchored_multihop = (
            any(len(mc.patterns[0].edges) > 1 for mc in ast.match_clauses if len(mc.patterns) == 1)
            and ast.where_clause is None
        )
        if has_unanchored_multihop:
            result["warnings"] = {
                "multi_hop_no_anchor": (
                    "Multi-hop MATCH has no WHERE anchor; this may scan the full graph. "
                    "Add a WHERE predicate or a LIMIT for better performance."
                )
            }
        return result

    # --- Single-clause row projection / aggregation ---
    mc = ast.match_clauses[0]
    qs, pattern, bindings = _build_clause_queryset(mc, ast, inputs, db_alias)

    rows = _compute_rows(qs, ast.return_clause, bindings, order_by=ast.order_by, limit=ast.limit)

    envelope: dict[str, Any] = {"nodes": [], "edges": [], "rows": rows}

    if len(pattern.edges) > 1 and ast.where_clause is None:
        envelope["warnings"] = {
            "multi_hop_no_anchor": (
                "Multi-hop MATCH has no WHERE anchor; this may scan the full graph. "
                "Add a WHERE predicate or a LIMIT for better performance."
            )
        }

    return envelope


def _resolve_order_cols(
    order_by: Any,
    key_to_internal: dict[str, str],
    default_internals: list[str],
) -> list[str]:
    """Translate an ORDER BY clause into Django `.order_by()` column args.

    TAP-IMPLEMENTS: req-grid-gryphon-order-by@52cc61a175d1/85313af36f80 (derivation) — ORDER BY
        columns (including aggregated ones) resolve here.

    Each ORDER BY term names a RETURN output by key; it is mapped to that
    output's internal annotation alias, with a `-` prefix for `DESC`. Any
    group-by columns the user did not name are appended as ascending
    tiebreakers, so output order (and the captured SQL) is fully deterministic
    even when the named keys have ties. With no ORDER BY, the group-by columns
    alone are the order — identical to the executor's prior behavior.

    .. tap:capability:: Gryphon ORDER BY and LIMIT
       :id: cap-grid-gryphon-order-by-limit
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:order_by_limit-count-scoreboard-capped-with-limit-highest-degree-hub-only
       :limitations: Envelope ORDER BY / LIMIT is supported for a single labelled type-scan only; other envelope dispatches keep the rejection.

       ORDER BY orders row-projection results by RETURN outputs (ascending or
       ``DESC``, multi-key, deterministic tiebreak); LIMIT caps the row count.
       A labelled type-scan returning a graph envelope additionally accepts
       ``ORDER BY <var>.<field-path>`` and ``LIMIT n`` — the "latest emission
       of kind X" panel shape compiles to a single ``SELECT ... ORDER BY ...
       LIMIT 1`` rather than a Python-side sort.

       Example::

          MATCH (h)-[:PG_LINKS__grid_fixtures]->(n)
          RETURN h.entity_id AS source_id, COUNT(n) AS out_degree
          ORDER BY out_degree DESC LIMIT 1
    """
    if order_by is None:
        return list(default_internals)
    cols: list[str] = []
    used: set[str] = set()
    for ob in order_by.items:
        # Multi-step paths are the envelope-mode surface
        # (req-grid-gryphon-order-by-envelope); aggregation queries are
        # row-projection and continue to require a RETURN-alias key.
        if ob.path.steps:
            raise SearchExecutionError(
                f"ORDER BY field-path form '{_format_field_path(ob.path)}' is "
                f"supported in envelope-mode RETURN only in v0 (per "
                f"req-grid-gryphon-order-by-envelope). Aggregation queries are "
                f"row-projection; name a RETURN alias instead — e.g. ORDER BY "
                f"{ob.key}."
            )
        if ob.key not in key_to_internal:
            raise SearchExecutionError(f"ORDER BY references '{ob.key}', which is not a RETURN output of this query.")
        internal = key_to_internal[ob.key]
        used.add(internal)
        cols.append(f"-{internal}" if ob.descending else internal)
    for g in default_internals:
        if g not in used:
            cols.append(g)
    return cols


@dataclass(frozen=True)
class MaterializationPlan:
    """A resolved plan handed by a Layer-A shape builder to the shared row backend.

    Every field is already resolved to concrete ORM expressions / columns by the
    shape-specific builder (type-scan, edge-chain, OPTIONAL MATCH), so
    :func:`materialize_rows` never inspects pattern shape, resolves a field path,
    or reads a variable binding. This is the contract that lets one backend serve
    every shape (`req-grid-traversal-exec-row-materialization`); a looser
    ``(queryset, bindings)`` pair is insufficient because OPTIONAL MATCH's
    zero-preserving ``Count(edge_path, filter=opt_q)`` and each shape's path
    prefix are local state that only the builder can resolve.
    """

    queryset: Any
    # internal_alias -> ORM expression, annotated *before* `.values()` (group-by
    # F-aliases plus any aggregate source aliases).
    pre_annotations: dict[str, Any]
    # (internal_alias, user_alias) in RETURN order — the projected / group-by columns.
    group_pairs: tuple[tuple[str, str], ...]
    # agg_internal_alias -> aggregate expression (e.g. ``Count(...)``), annotated
    # *after* `.values()` so it aggregates over the group.
    aggregate_annotations: dict[str, Any]
    # (agg_internal_alias, user_alias) in RETURN order.
    aggregate_pairs: tuple[tuple[str, str], ...]
    # Fully-resolved `.order_by()` column args (incl. shape-specific tiebreakers).
    # Empty => do not reorder (keep the queryset's inherited ordering).
    order_cols: tuple[str, ...]
    # LIMIT AST node (carries `.count`) or None.
    limit: Any = None
    # DISTINCT flag. Always False until `req-grid-gryphon-distinct` lands; the
    # backend is the single structural home for the DISTINCT rules. Until the
    # `.values().distinct()` application is wired, `materialize_rows` fails closed
    # on a set flag (reject, never silently no-op) rather than accepting it.
    distinct: bool = False


def _rows_from_values(
    raw_rows: Any,
    group_pairs: tuple[tuple[str, str], ...],
    aggregate_pairs: tuple[tuple[str, str], ...],
) -> list[dict[str, Any]]:
    """Build row dicts from `.values()` output — the one uuid-stringify site.

    Projected (group) column values are stringified when they are UUIDs
    (``hasattr(val, "hex")``); aggregate values pass through unchanged. Row-dict
    key order follows the RETURN projection order and duplicate user aliases
    collapse last-write-wins, preserved byte-identically
    (`req-grid-traversal-exec-row-materialization-15`).
    """
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row: dict[str, Any] = {}
        for internal, user in group_pairs:
            val = raw.get(internal)
            row[user] = str(val) if hasattr(val, "hex") else val
        for internal, user in aggregate_pairs:
            row[user] = raw.get(internal)
        rows.append(row)
    return rows


def materialize_rows(plan: MaterializationPlan) -> list[dict[str, Any]]:
    """The shared Layer-B row backend: a resolved plan -> the ``rows`` list.

    TAP-IMPLEMENTS: req-grid-traversal-exec-row-materialization@edbd98db287d/76105b23891f (derivation) —
        the requirement exists to forbid per-dispatch row tails; this function is the one
        backend every shape reaches, so a fifth row tail is a defect by construction.

    Shape-agnostic. It applies the plan's pre-resolved annotations, projects
    through ``.values()``, applies aggregates, ordering, and LIMIT, and builds the
    row dicts — reached identically by the type-scan, edge-chain, and OPTIONAL
    MATCH shapes. Collapsing the four former per-shape row tails here makes the
    "a path silently drops a row-flag" and "a per-tail ordering divergence" bug
    classes inexpressible (`req-grid-traversal-exec-row-materialization`,
    `GRY-ARCH-4`).
    """
    # req-grid-traversal-exec-row-materialization-14: DISTINCT over aggregate
    # returns is rejected here — the single structural home across every shape
    # (incl. OPTIONAL MATCH, whose plan always carries a Count).
    if plan.distinct and plan.aggregate_annotations:
        raise SearchExecutionError(
            "DISTINCT is not supported over aggregate returns; remove DISTINCT or the aggregate."
        )
    # Fail closed on the dormant flag. `plan.distinct` is always False today — no
    # Layer-A builder sets it and `ReturnClause` has no `distinct` field — but the
    # `.values().distinct()` application (and its ordering-clear) is not wired yet.
    # So a non-aggregate `plan.distinct=True` MUST reject rather than silently
    # return non-deduplicated rows: a silent no-op is the exact class this backend
    # exists to make impossible (`GRY-ARCH-3`). `req-grid-gryphon-distinct` replaces
    # this branch with the real `.values().distinct()`. Laying the edge now
    # (`GRY-SEC-4`) means a premature flag can never no-op.
    if plan.distinct:
        raise SearchExecutionError("DISTINCT is not implemented yet (req-grid-gryphon-distinct).")

    qs = plan.queryset
    if plan.pre_annotations:
        qs = qs.annotate(**plan.pre_annotations)

    group_internals = [internal for internal, _ in plan.group_pairs]
    qs = qs.values(*group_internals)
    if plan.aggregate_annotations:
        qs = qs.annotate(**plan.aggregate_annotations)
    if plan.order_cols:
        qs = qs.order_by(*plan.order_cols)
    if plan.limit is not None:
        qs = qs[: plan.limit.count]

    return _rows_from_values(list(qs), plan.group_pairs, plan.aggregate_pairs)


def _compute_rows(
    qs,
    return_clause: ReturnClause,
    bindings: dict[str, dict[str, Any]],
    *,
    order_by: Any = None,
    limit: Any = None,
) -> list[dict[str, Any]]:
    """Execute the queryset and produce row dicts honoring RETURN aliases and aggregates.

    TAP-IMPLEMENTS: req-grid-gryphon-count@ca056f66dee5/7c97eada462b (derivation) — COUNT
        aggregation and its implicit GROUP BY key set compute here.

    TAP-IMPLEMENTS: req-grid-gryphon-rows@577171676b4f/7c97eada462b (derivation) — the envelope's
        rows field is populated here.

    All RETURN columns are first annotated as F-aliases on the queryset, then
    referenced by alias in ``.values()`` / ``Count(...)``. This forces Django to
    reuse the JOIN aliases established by ``_build_chain_queryset`` rather than
    adding duplicate JOINs for each references — the fix for multi-hop COUNT
    inflation.

    .. tap:capability:: Gryphon COUNT aggregation
       :id: cap-grid-gryphon-count
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:aggregation-count-of-pg-node-neighbors-per-hub
       :limitations: COUNT is the only aggregate; SUM / MIN / MAX / AVG and COUNT(DISTINCT) are not implemented.

       ``COUNT(var)`` in RETURN aggregates with an implicit GROUP BY on the
       non-aggregated columns; results land in the envelope's ``rows`` list.

       Example::

          MATCH (h:grid_fixtures__hub)-[:PG_LINKS__grid_fixtures]->(n:grid_fixtures__node)
          RETURN h.entity_id AS hub_id, COUNT(n) AS neighbor_count
    """
    from django.db.models import Count, F

    items = return_clause.items
    if items is None:
        raise SearchExecutionError("Aggregation executor requires an explicit RETURN clause.")

    # Partition into field projections and aggregates.
    field_items: list[ReturnItem] = []
    aggregate_items: list[AggregateReturnItem] = []
    for item in items:
        if isinstance(item, AggregateReturnItem):
            aggregate_items.append(item)
        elif isinstance(item, ReturnItem):
            field_items.append(item)
        else:
            raise SearchExecutionError(f"Unexpected RETURN item type: {type(item).__name__}")

    # Annotations are namespaced under internal aliases so user-facing RETURN
    # aliases (which may be any NAME including model-field names like `id`)
    # cannot collide with Django-internal annotation slots or model columns.
    group_by_pairs: list[tuple[str, str]] = []  # (internal_alias, user_alias)
    aggregate_pairs: list[tuple[str, str]] = []  # (internal_agg_alias, user_alias)
    annotations: dict[str, Any] = {}

    for idx, fi in enumerate(field_items):
        fp: FieldPath = fi.path
        if fp.variable not in bindings:
            raise SearchExecutionError(f"Unknown variable '{fp.variable}' in RETURN.")
        if not fp.steps or not isinstance(fp.steps[0], DotStep):
            raise SearchExecutionError("RETURN field paths must start with a dot-step.")
        orm_path = _resolve_orm_path(bindings[fp.variable], fp)
        # Last dot-step name becomes the default user-facing alias when the
        # author didn't supply an explicit AS alias.
        last_dot_step_name = fp.steps[-1].name if isinstance(fp.steps[-1], DotStep) else fp.steps[0].name
        user_alias = fi.alias or last_dot_step_name
        internal = f"_g_col_{idx}"
        annotations[internal] = F(orm_path)
        group_by_pairs.append((internal, user_alias))

    aggregate_annotations: dict[str, Any] = {}
    for idx, ai in enumerate(aggregate_items):
        agg: AggregateCall = ai.aggregate
        if agg.function != "count":
            raise SearchExecutionError(f"Unsupported aggregate function: {agg.function}")
        arg: FieldPath = agg.argument
        if arg.variable not in bindings:
            raise SearchExecutionError(f"Unknown variable '{arg.variable}' in COUNT().")
        if len(arg.steps) == 0:
            count_col = _orm_path_for_field(bindings[arg.variable], "entity_id")
        elif len(arg.steps) == 1 and isinstance(arg.steps[0], DotStep):
            count_col = _orm_path_for_field(bindings[arg.variable], arg.steps[0].name)
        else:
            raise SearchExecutionError("COUNT argument must be a bare variable or single dot-step.")
        src_alias = f"_g_count_src_{idx}"
        agg_alias = f"_g_agg_{idx}"
        annotations[src_alias] = F(count_col)
        aggregate_annotations[agg_alias] = Count(src_alias)
        aggregate_pairs.append((agg_alias, ai.alias))

    group_by_internals = [i for i, _ in group_by_pairs]

    # Map each RETURN output key to its internal annotation alias so ORDER BY
    # terms (which name RETURN outputs) can resolve to sortable columns.
    key_to_internal: dict[str, str] = {}
    for internal, user in group_by_pairs:
        key_to_internal[user] = internal
    for internal, user in aggregate_pairs:
        key_to_internal[user] = internal

    # Resolve the edge-chain ORDER BY convention into concrete columns: aggregate
    # queries always order (group-by internals as the deterministic default /
    # tiebreak); a plain projection reorders only when ORDER BY or LIMIT is present,
    # otherwise it keeps the chain queryset's inherited order.
    if aggregate_annotations or order_by is not None or limit is not None:
        order_cols = tuple(_resolve_order_cols(order_by, key_to_internal, group_by_internals))
    else:
        order_cols = ()

    plan = MaterializationPlan(
        queryset=qs,
        pre_annotations=annotations,
        group_pairs=tuple(group_by_pairs),
        aggregate_annotations=aggregate_annotations,
        aggregate_pairs=tuple(aggregate_pairs),
        order_cols=order_cols,
        limit=limit,
    )
    return materialize_rows(plan)


def _serialize_edge_list(
    edges: list[Any],
    layer: SubgraphLayer,
    db_alias: str,
) -> list[dict[str, Any]]:
    """Serialize Edge objects to edge dicts at the requested layer."""
    if layer == "lite":
        return [serialize_edge_lite(e) for e in edges]

    if layer == "full":
        return [serialize_edge_full(e) for e in edges]

    # extended — resolve endpoint names.
    endpoint_ids: set[str] = set()
    for edge in edges:
        endpoint_ids.add(str(edge.from_entity_id))
        endpoint_ids.add(str(edge.to_entity_id))
    name_map = batch_resolve_entity_names(endpoint_ids, db_alias)

    return [
        serialize_edge_extended(
            e,
            from_label=name_map.get(str(e.from_entity_id), ""),
            to_label=name_map.get(str(e.to_entity_id), ""),
        )
        for e in edges
    ]


# ---------------------------------------------------------------------------
# Data-lane type-strictness (req-grid-traversal-lang-type-strictness)
# ---------------------------------------------------------------------------
#
# The declared schema is the type oracle. A data-lane predicate's literal must
# match the field's declared type in the model's FIELD_CRUD_SCHEMA; Gryphon does
# not coerce across types (unlike the ORM, which would silently cast "10" -> 10
# or a number -> ::text). A type mismatch on a *declared* field is rejected, not
# silently dropped — the typed lane knows its types, so a wrong-typed literal is
# an authoring bug, surfaced rather than hidden.
#
# This is the single code path for both lanes. A bare {"type": "object"} (or any
# path that bottoms out in an un-typed JSON object / container) is the schema
# declaring an OPEN blob: the walker returns None and strictness is skipped
# there — exactly today's `n.data.tags.*`. The day a JSON field's schema gains
# real `properties`, the same walker resolves a concrete type and strictness
# lights up on that sub-path with zero change here. Tolerance is schema-declared,
# never lane-special-cased. See spec-security-posture.md "Named open edges".

_TEXT_OPS: frozenset[str] = frozenset({"starts_with", "ends_with", "contains", "regex"})


def _json_type_of_value(value: Any) -> str | None:
    """Classify a resolved literal as a JSON-Schema scalar type name.

    Returns None for ``None`` — the two-valued null operand is judged by the
    null short-circuit in :func:`_comparison_to_q`, not by type-strictness.
    ``bool`` is tested before ``int`` because ``bool`` is an ``int`` subclass.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _declared_data_types(model_cls: type, field_path: FieldPath) -> set[str] | None:
    """Resolve the declared scalar type set for a data-lane field path, or None.

    Walks ``model_cls.FIELD_CRUD_SCHEMA`` (the per-field JSON Schema) to the leaf
    addressed by ``field_path``. Returns a set of JSON-Schema scalar type names
    when the leaf declares a concrete scalar type (or a union of them); returns
    ``None`` — meaning "no strictness here" — for any path that is not a typed
    data-lane scalar: spine fields, undeclared fields, or a node that bottoms out
    in an un-typed / container (``object`` / ``array``) schema (the open-blob
    case; see spec-security-posture.md "Named open edges").
    """
    steps = field_path.steps
    if not steps or not isinstance(steps[0], DotStep) or steps[0].name != _DATA_LANE_PREFIX:
        return None  # spine / dimensions / display — not the typed data lane
    if len(steps) < 2 or not isinstance(steps[1], DotStep):
        return None
    schema = getattr(model_cls, "FIELD_CRUD_SCHEMA", {}) or {}
    node = schema.get(steps[1].name)
    if not isinstance(node, dict):
        return None  # field not declared in the CRUD schema — skip
    # Walk any remaining sub-key steps into the JSON Schema `properties`. Only
    # plain dot / bracket-key steps name a static sub-key; wildcard / index steps
    # do not resolve to one declared type, so strictness stops (returns None).
    for step in steps[2:]:
        if isinstance(step, DotStep):
            key = step.name
        elif isinstance(step, KeyStep):
            key = step.key
        else:
            return None
        props = node.get("properties")
        if not isinstance(props, dict) or not isinstance(props.get(key), dict):
            return None  # open blob / undeclared sub-key — strictness stops here
        node = props[key]
    declared = node.get("type")
    if isinstance(declared, str):
        types = {declared}
    elif isinstance(declared, list):
        types = {t for t in declared if isinstance(t, str)}
    else:
        return None  # no declared type — skip
    scalar = types - {"null"}
    if not scalar or (scalar & {"object", "array"}):
        return None  # container / open — strictness does not reach inside
    return types


def _admits(literal_type: str, allowed: set[str]) -> bool:
    """Whether a literal's JSON type satisfies a field's declared type set."""
    if literal_type in allowed:
        return True
    # JSON-Schema widening: an integer literal satisfies a `number` field.
    return literal_type == "integer" and "number" in allowed


def _enforce_type_strictness(
    comp: Comparison | InComparison,
    declared_types: Any,
    inputs: dict[str, Any],
) -> None:
    """Reject a data-lane predicate whose literal type contradicts the schema.

    ``declared_types`` is a callable ``FieldPath -> set[str] | None``. No-op when
    the field is open/untyped/spine (``None``), or the operand is null (the
    two-valued path handles it). Raises :class:`SearchExecutionError` on a
    concrete type mismatch — including a text operator (STARTS_WITH / ENDS_WITH /
    CONTAINS / ``=~``) applied to a non-text field.
    """
    allowed = declared_types(comp.field_path)
    if allowed is None:
        return
    rendered = _format_field_path(comp.field_path)
    shown = ", ".join(sorted(allowed))

    if isinstance(comp, Comparison):
        if comp.op in _TEXT_OPS and "string" not in allowed:
            raise SearchExecutionError(
                f"Type mismatch: {comp.op.upper()} requires a text field, but {rendered} "
                f"is declared {{{shown}}}. Gryphon does not coerce across types."
            )
        resolved = _resolve_value(comp.value, inputs)
        lit_type = _json_type_of_value(resolved)
        if lit_type is None:  # null operand — the two-valued short-circuit owns it
            return
        if not _admits(lit_type, allowed):
            raise SearchExecutionError(
                f"Type mismatch: {rendered} is declared {{{shown}}}, but the comparison "
                f"value is {lit_type} ({resolved!r}). Gryphon does not coerce across types; "
                f"supply a matching literal type."
            )
        return

    for member in comp.values:
        resolved = _resolve_value(member, inputs)
        lit_type = _json_type_of_value(resolved)
        if lit_type is None:
            continue  # a null member is simply a non-member, never an error
        if not _admits(lit_type, allowed):
            raise SearchExecutionError(
                f"Type mismatch: {rendered} is declared {{{shown}}}, but the IN list has a "
                f"{lit_type} member ({resolved!r}). Gryphon does not coerce across types; "
                f"supply matching literal types."
            )


# ---------------------------------------------------------------------------
# OPTIONAL MATCH executor (left-outer-join semantics)
# ---------------------------------------------------------------------------


def _comparison_to_q(
    comp: Comparison | InComparison | IsNullComparison | ObservationComparison,
    orm_path: str,
    inputs: dict[str, Any],
    declared_types: Any = None,
):
    """Translate a single comparison leaf into a Django ``Q`` over ``orm_path``.

    TAP-IMPLEMENTS: req-grid-traversal-lang-string-match@252cba1f51eb/a58650d98495 (derivation) —
        STARTS_WITH / ENDS_WITH / CONTAINS lower to Q objects here.

    TAP-IMPLEMENTS: req-grid-traversal-lang-regex@27b99acd119d/a58650d98495 (derivation) — the =~
        regex predicate lowers to a Q object here.

    The shared leaf compiler for every WHERE path: :func:`_predicate_to_q` calls
    it for each `Comparison` / `InComparison`, and ``_execute_optional_match``
    folds WHERE predicates on the optional variables into the
    ``Count(filter=...)`` clause through it. `IsNullComparison` lowers to
    Django's ``__isnull`` lookup so the OPTIONAL MATCH leaf path handles it
    too — without this branch, an ``IS [NOT] NULL`` predicate on an optional
    variable would crash the leaf-by-leaf walk.

    .. tap:capability:: Gryphon string-match predicates
       :id: cap-grid-gryphon-string-match
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:string_match-starts-with-matches-a-name-prefix
       :limitations: Case-sensitive; needle is escaped (LIKE metacharacters are literal). For regex syntax or case-insensitive matching, use ``=~`` (cap-grid-gryphon-regex).

       ``STARTS_WITH`` / ``ENDS_WITH`` / ``CONTAINS`` test a string field against
       a prefix / suffix / substring. The needle is escaped, so ``LIKE``
       metacharacters (``%`` ``_``) match literally; an empty needle matches
       every string.

       Example::

          MATCH (n:grid_fixtures__node) WHERE n.name STARTS_WITH "Neighbor"
          RETURN n.entity_id AS id ORDER BY id

    .. tap:capability:: Gryphon regex match operator
       :id: cap-grid-gryphon-regex
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:regex_match-case-insensitive-search-via-inline-i-flag
       :limitations: Search semantics (substring; anchor with ``^...$``). PostgreSQL ARE/POSIX-family regex; no PCRE-only features; no catastrophic-pattern detection in v0; no statement_timeout default.

       ``field =~ pattern`` matches the pattern *anywhere* in the field value
       (search semantics, the same shape as Postgres ``~`` and ``grep``). Full-
       string matching is the explicit shape ``=~ "^...$"``. The pattern is
       passed through to Postgres unaltered — inline flags ``(?i)``, ``(?s)``,
       ``(?m)``, ``(?x)`` reach the regex engine verbatim. The needle is NOT
       escaped — metacharacters carry regex meaning, the explicit deal of
       ``=~``. Gryphon deliberately diverges from Cypher's anchored ``=~``
       semantics; see req-grid-traversal-lang-regex Background.

       Example::

          MATCH (n:grid_fixtures__node) WHERE n.name =~ "(?i)neighbor"
          RETURN n.entity_id AS id ORDER BY id
    """
    from django.db.models import Q

    # Data-lane type-strictness: reject a wrong-typed literal before lowering,
    # so the ORM never silently coerces it (req-grid-traversal-lang-type-strictness).
    if declared_types is not None and isinstance(comp, (Comparison, InComparison)):
        _enforce_type_strictness(comp, declared_types, inputs)

    if isinstance(comp, InComparison):
        members = [_resolve_value(v, inputs) for v in comp.values]
        return Q(**{f"{orm_path}__in": members})

    if isinstance(comp, IsNullComparison):
        return Q(**{f"{orm_path}__isnull": not comp.negated})

    if isinstance(comp, ObservationComparison):
        # IS UNKNOWN -> __isnull=True, IS KNOWN -> __isnull=False (null axis;
        # used here so the OPTIONAL MATCH Count(filter=...) leaf path handles it).
        return Q(**{f"{orm_path}__isnull": comp.kind == "unknown"})

    value = _resolve_value(comp.value, inputs)

    # A null LITERAL operand short-circuits to a genuine FALSE for EVERY
    # comparison operator — the two-valued "unobserved operand" rule
    # (spec-grid-traversal-language.md § null semantics;
    # req-grid-traversal-lang-type-strictness-3). This deliberately includes `=`
    # and `!=`: without it Django lowers `field = null` to `IS NULL` and
    # `field != null` to `IS NOT NULL` (a `field=None` artifact), silently
    # returning the null-field / non-null-field rows the spec says a null-literal
    # comparison NEVER matches — a silent-wrong-answer on the null boundary. The
    # observational null axis is `IS NULL` / `IS UNKNOWN`, not `= null`. The
    # tautologically-false `Q` drops the row without crashing the ORM ("Cannot
    # use None as a query value" on an ordering/substring lookup).
    if value is None:
        return ~Q(pk__isnull=True) & Q(pk__isnull=True)

    if comp.op == "!=":
        return ~Q(**{orm_path: value})
    # The regex operator (req-grid-traversal-lang-regex) always lowers to
    # Django's `__regex` lookup (Postgres `~`). Inline flags `(?i)`, `(?s)`,
    # `(?m)`, `(?x)` are passed through verbatim — the executor does NOT
    # detect, strip, or rewrite any flag.
    if comp.op == "regex":
        return Q(**{f"{orm_path}__regex": value})
    # The scalar comparison operators plus the substring operators
    # (req-grid-traversal-lang-string-match) -- all positive, single-value
    # lookups on `orm_path`.
    suffix = {
        "=": "",
        "<": "__lt",
        ">": "__gt",
        "<=": "__lte",
        ">=": "__gte",
        "starts_with": "__startswith",
        "ends_with": "__endswith",
        "contains": "__contains",
    }[comp.op]
    return Q(**{f"{orm_path}{suffix}": value})


def _execute_optional_match(
    ast: GryphonAST,
    inputs: dict[str, Any],
    *,
    db_alias: str,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    """Execute a MATCH + OPTIONAL MATCH query — left-outer-join semantics.

    TAP-IMPLEMENTS: req-grid-gryphon-optional-match@15c86aacbfad/09a3dba9dd29 (derivation) —
        OPTIONAL MATCH left-join semantics execute here.

    v0 scope: exactly one node-only mandatory MATCH (a labelled type scan
    binding ``v``), exactly one single-hop OPTIONAL MATCH anchored on ``v``, and
    a row-projection RETURN that projects ``v``'s fields and COUNTs the optional
    variable. The optional pattern compiles to a ``Count(edge, filter=Q)`` over
    a LEFT JOIN, so a mandatory row with no optional match still appears with a
    count of 0 rather than being dropped — the whole point of OPTIONAL MATCH.

    A WHERE predicate on the optional variable is folded into the ``filter=Q``,
    so it constrains the optional join and does not drop mandatory rows (the
    notorious Cypher filter-placement gotcha); a WHERE predicate on the
    mandatory variable filters the outer scan.

    .. tap:capability:: Gryphon OPTIONAL MATCH
       :id: cap-grid-gryphon-optional-match
       :status: implemented
       :audience: external-user; agent; developer
       :affordance: querying
       :covered-by: gridkin:optional_match-optional-match-keeps-zero-match-rows-count-is-0-not-absent
       :limitations: v0 -- one node-only MATCH plus one single-hop OPTIONAL MATCH; the optional variable is COUNT-only.

       OPTIONAL MATCH is a left outer join: a mandatory row with no optional
       match is kept, with ``COUNT`` of the optional variable returning 0.

       Example::

          MATCH (t:grid_fixtures__node)
          OPTIONAL MATCH (t)<-[:PG_OPTIONAL__grid_fixtures]-(g:grid_fixtures__node)
          RETURN t.entity_id AS target, COUNT(g) AS guards ORDER BY target
    """
    from django.db.models import Count, F, Q

    from tap_grid.registry import get_model_class

    # --- structural validation: the v0 OPTIONAL MATCH shape -----------------
    if len(ast.match_clauses) != 1:
        raise SearchExecutionError("OPTIONAL MATCH v0 requires exactly one mandatory MATCH clause.")
    mc = ast.match_clauses[0]
    if len(mc.patterns) != 1 or mc.patterns[0].edges:
        raise SearchExecutionError(
            "OPTIONAL MATCH v0 requires the mandatory MATCH to be a single node-only type scan, "
            "e.g. MATCH (t:grid_fixtures__node)."
        )
    anchor_node = mc.patterns[0].nodes[0]
    if not anchor_node.label:
        raise SearchExecutionError(
            "OPTIONAL MATCH v0 requires a label on the mandatory MATCH node, e.g. MATCH (t:grid_fixtures__node)."
        )
    v = anchor_node.variable or anchor_node.label

    if len(ast.optional_match_clauses) != 1:
        raise SearchExecutionError("OPTIONAL MATCH v0 supports exactly one OPTIONAL MATCH clause.")
    opt_clause = ast.optional_match_clauses[0]
    if len(opt_clause.patterns) != 1 or len(opt_clause.patterns[0].edges) != 1:
        raise SearchExecutionError(
            "OPTIONAL MATCH v0 requires a single-hop optional pattern, e.g. OPTIONAL MATCH (t)-[:E]->(w)."
        )
    opt_pat = opt_clause.patterns[0]
    opt_edge = opt_pat.edges[0]
    if opt_edge.min_hops != 1 or opt_edge.max_hops != 1:
        raise SearchExecutionError("OPTIONAL MATCH v0 does not support variable-length optional edges.")
    if opt_edge.direction not in ("out", "in"):
        raise SearchExecutionError("OPTIONAL MATCH v0 requires a directed optional edge (-> or <-).")
    if ast.not_exists_clauses:
        raise SearchExecutionError("OPTIONAL MATCH does not combine with NOT EXISTS in v0.")
    if _is_graph_envelope_return(ast.return_clause):
        raise SearchExecutionError(
            "OPTIONAL MATCH v0 requires a row-projection RETURN that projects the MATCH variable's "
            "fields and COUNTs the optional variable; graph-envelope OPTIONAL MATCH is future work."
        )

    left_node, w_node = opt_pat.nodes[0], opt_pat.nodes[1]
    if left_node.variable != v:
        raise SearchExecutionError(
            f"The OPTIONAL MATCH pattern must start from the MATCH variable '{v}', e.g. OPTIONAL MATCH ({v})-[:E]->(w)."
        )

    try:
        model_cls = get_model_class(anchor_node.label)
    except KeyError:
        raise SearchExecutionError(f"Unsupported gryphon pattern: unknown entity type '{anchor_node.label}'.") from None

    # --- ORM paths from the mandatory model, through the optional edge ------
    # `->` : v is the edge's from_entity, the optional node w is to_entity.
    # `<-` : v is to_entity, w is from_entity.
    if opt_edge.direction == "out":
        edge_path = "entity__edges_out"
        w_entity_path = f"{edge_path}__to_entity"
    else:
        edge_path = "entity__edges_in"
        w_entity_path = f"{edge_path}__from_entity"

    # Bindings for the optional variables, rooted at the mandatory-model qs, so
    # `_resolve_orm_path` can translate WHERE predicates that reference them.
    opt_bindings: dict[str, dict[str, Any]] = {}
    if w_node.variable:
        opt_bindings[w_node.variable] = {"role": "node", "entity_path": w_entity_path, "label": w_node.label}
    if opt_edge.variable:
        opt_bindings[opt_edge.variable] = {"role": "edge", "edge_path": edge_path}

    # --- the optional-join filter Q -----------------------------------------
    # The optional pattern's own constraints (edge type, w label, inline edge
    # props) and any WHERE predicate on an optional variable all become part of
    # this Q. Folded into Count(..., filter=Q), they constrain the join — they
    # never drop a mandatory row.
    opt_q = Q()
    if opt_edge.edge_type:
        opt_q &= Q(**{f"{edge_path}__edge_type": opt_edge.edge_type})
    if w_node.label:
        opt_q &= Q(**{f"{w_entity_path}__entity_type": w_node.label})
    for key, raw_value in opt_edge.inline_props.items():
        opt_q &= Q(**{f"{edge_path}__properties__{key}": _resolve_value(raw_value, inputs)})

    # --- WHERE: v-comps filter the outer scan, opt-comps join the filter Q --
    qs = model_cls.objects.using(db_alias)
    where_pred = ast.where_clause.predicate if ast.where_clause else None
    if where_pred is not None:
        # The WHERE splits by variable: comparisons on `v` filter the outer
        # scan; comparisons on an optional variable join `opt_q`. OPTIONAL MATCH
        # v0 keeps an AND-only WHERE (``_flatten_conjunction`` rejects OR/NOT)
        # so this split stays well-defined.
        v_pred = _filter_predicate_for_bindings(where_pred, {v: {}})
        if v_pred is not None:
            qs = _apply_typescan_predicate(qs, v_pred, inputs)
        for comp in _flatten_conjunction(where_pred):
            var = comp.field_path.variable
            if var == v:
                continue
            if var not in opt_bindings:
                raise SearchExecutionError(
                    f"WHERE references variable '{var}', which is bound by neither the MATCH nor the "
                    f"OPTIONAL MATCH."
                )
            orm_path = _resolve_orm_path(opt_bindings[var], comp.field_path)
            opt_strict = (lambda fp: _declared_data_types(get_model_class(w_node.label), fp)) if w_node.label else None
            opt_q &= _comparison_to_q(comp, orm_path, inputs, opt_strict)

    # --- group-by columns + Count aggregates from RETURN --------------------
    items = ast.return_clause.items
    assert items is not None  # _is_graph_envelope_return is True when items is None
    group_annotations: dict[str, Any] = {}
    agg_annotations: dict[str, Any] = {}
    group_pairs: list[tuple[str, str]] = []  # (internal_alias, user_alias)
    agg_pairs: list[tuple[str, str]] = []  # (internal_alias, user_alias)

    for idx, item in enumerate(items):
        if isinstance(item, ReturnItem):
            fp = item.path
            if fp.variable != v:
                raise SearchExecutionError(
                    "OPTIONAL MATCH v0: RETURN field paths must reference the MATCH variable; the "
                    "optional variable can only be COUNTed."
                )
            internal = f"_om_col_{idx}"
            group_annotations[internal] = F(_typescan_orm_path(fp, model_cls))
            group_pairs.append((internal, _return_item_key(item)))
        elif isinstance(item, AggregateReturnItem):
            agg = item.aggregate
            if agg.function != "count":
                raise SearchExecutionError(f"OPTIONAL MATCH v0 supports only COUNT; got {agg.function!r}.")
            arg = agg.argument
            if arg.variable not in opt_bindings or arg.steps:
                raise SearchExecutionError(
                    "OPTIONAL MATCH v0: COUNT(...) must count a bare optional variable, e.g. COUNT(g)."
                )
            # COUNT over the optional variable counts matching optional edges
            # (single hop: one edge == one optional-variable binding). The LEFT
            # JOIN means a mandatory row with no match counts 0, not NULL.
            internal = f"_om_agg_{idx}"
            agg_annotations[internal] = Count(edge_path, filter=opt_q)
            agg_pairs.append((internal, item.alias))
        else:
            raise SearchExecutionError(f"Unexpected RETURN item type: {type(item).__name__}")

    if not agg_annotations:
        raise SearchExecutionError(
            "OPTIONAL MATCH v0 requires the RETURN to COUNT the optional variable, e.g. COUNT(g) AS guards."
        )

    group_internals = [i for i, _ in group_pairs]
    key_to_internal: dict[str, str] = {user: internal for internal, user in group_pairs}
    key_to_internal.update({user: internal for internal, user in agg_pairs})

    # OPTIONAL MATCH always carries a Count, so it is an aggregate plan and always
    # orders (group-by internals as the deterministic default / tiebreak). The
    # zero-preserving Count(edge_path, filter=opt_q) built above is a fully-resolved
    # aggregate descriptor — the shape-local state the shared backend cannot derive
    # from bindings alone (req-grid-traversal-exec-row-materialization-3).
    plan = MaterializationPlan(
        queryset=qs,
        pre_annotations=group_annotations,
        group_pairs=tuple(group_pairs),
        aggregate_annotations=agg_annotations,
        aggregate_pairs=tuple(agg_pairs),
        order_cols=tuple(_resolve_order_cols(ast.order_by, key_to_internal, group_internals)),
        limit=ast.limit,
    )
    return {"nodes": [], "edges": [], "rows": materialize_rows(plan)}
