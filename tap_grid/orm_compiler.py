"""ORM DSL compiler for TAP search execution — req-grid-search-orm.

Compiles declarative JSON search definitions into read-only TAP ORM queries.
The v1 DSL supports: root selection, conjunctive filters, optional one-hop
graph traversal, and deterministic ordering.

Entry point: compile_orm_query(search, db_alias, limit, offset, layer) -> dict
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tap_grid.exceptions import InvalidSearchDefinitionError
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

if TYPE_CHECKING:
    from tap_grid.models import Edge, Entity, Search


def compile_orm_query(
    search: Search,
    db_alias: str,
    limit: int | None = None,
    offset: int = 0,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Compile and execute an ORM DSL search definition.

    Args:
        search:    The Search model instance (search_type must be "orm").
        db_alias:  DB alias to use for all queries (read-only alias in production).
        limit:     Maximum number of primary-side results to return.
        offset:    Zero-based offset into the primary-side results.
        layer:     GRIFT subgraph return layer (lite, full, extended).

    Returns:
        Canonical 4-key envelope: {"nodes": [...], "edges": [...], "info": {...}, "warnings": {}}
        info contains "total_count" (count before pagination).

    Raises:
        InvalidSearchDefinitionError: definition is structurally invalid at execution time.
    """
    definition = search.definition
    filters: dict[str, Any] = definition.get("filters", {})
    hops: list[dict[str, Any]] = definition.get("hops") or []
    order_by: list[str] | None = definition.get("order_by")

    if len(hops) > 1:
        raise InvalidSearchDefinitionError("ORM search supports at most one hop.")

    if search.root == "node":
        return _execute_node_query(db_alias, filters, hops, order_by, limit, offset, layer)
    else:
        return _execute_edge_query(db_alias, filters, hops, order_by, limit, offset, layer)


# ---------------------------------------------------------------------------
# Node root
# ---------------------------------------------------------------------------


def _execute_node_query(
    db_alias: str,
    filters: dict[str, Any],
    hops: list[dict[str, Any]],
    order_by: list[str] | None,
    limit: int | None,
    offset: int,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    from tap_grid.models import Edge, Entity

    root_qs = Entity.objects.using(db_alias).live().exclude(entity_type="edge")
    if filters:
        root_qs = root_qs.filter(**filters)
    root_qs = _apply_order(root_qs, order_by, default=["id"])

    total_count = root_qs.count()

    # Apply pagination to root
    if limit is not None:
        paginated_qs = root_qs[offset : offset + limit]
    else:
        paginated_qs = root_qs

    if not hops:
        all_entities = list(paginated_qs)
        nodes = _serialize_nodes(all_entities, layer, db_alias)
        return {"nodes": nodes, "edges": [], "info": {"total_count": total_count}, "warnings": {}}

    hop = hops[0]
    direction = hop["direction"]
    edge_type = hop["edge_type"]
    root_ids = list(paginated_qs.values_list("id", flat=True))

    if direction == "out":
        hop_edge_qs = Edge.objects.using(db_alias).filter(from_entity_id__in=root_ids, edge_type=edge_type)
        endpoint_ids = list(hop_edge_qs.values_list("to_entity_id", flat=True))
        endpoint_filters = hop.get("target_filters", {})
    else:  # "in"
        hop_edge_qs = Edge.objects.using(db_alias).filter(to_entity_id__in=root_ids, edge_type=edge_type)
        endpoint_ids = list(hop_edge_qs.values_list("from_entity_id", flat=True))
        endpoint_filters = hop.get("source_filters", {})

    endpoint_qs = Entity.objects.using(db_alias).live().filter(id__in=endpoint_ids)
    if endpoint_filters:
        endpoint_qs = endpoint_qs.filter(**endpoint_filters)

    # Keep only edges where the endpoint survived filtering
    surviving_ids = set(endpoint_qs.values_list("id", flat=True))
    if direction == "out":
        hop_edge_qs = hop_edge_qs.filter(to_entity_id__in=surviving_ids)
    else:
        hop_edge_qs = hop_edge_qs.filter(from_entity_id__in=surviving_ids)

    all_entities = list(paginated_qs) + list(endpoint_qs)
    edge_list = list(hop_edge_qs.select_related("entity")) if layer != "lite" else list(hop_edge_qs)

    nodes = _serialize_nodes(all_entities, layer, db_alias)
    edges = _serialize_edges(edge_list, layer, db_alias)
    return {"nodes": nodes, "edges": edges, "info": {"total_count": total_count}, "warnings": {}}


# ---------------------------------------------------------------------------
# Edge root
# ---------------------------------------------------------------------------


def _execute_edge_query(
    db_alias: str,
    filters: dict[str, Any],
    hops: list[dict[str, Any]],
    order_by: list[str] | None,
    limit: int | None,
    offset: int,
    layer: SubgraphLayer,
) -> dict[str, Any]:
    from tap_grid.models import Edge, Entity

    edge_qs = Edge.objects.using(db_alias)
    if layer != "lite":
        edge_qs = edge_qs.select_related("entity")
    if filters:
        edge_qs = edge_qs.filter(**filters)
    edge_qs = _apply_order(edge_qs, order_by, default=["entity_id"])

    total_count = edge_qs.count()

    if limit is not None:
        paginated_qs = edge_qs[offset : offset + limit]
    else:
        paginated_qs = edge_qs

    if not hops:
        edge_list = list(paginated_qs)
        edges = _serialize_edges(edge_list, layer, db_alias)
        return {"nodes": [], "edges": edges, "info": {"total_count": total_count}, "warnings": {}}

    hop = hops[0]
    direction = hop["direction"]
    edges_list = list(paginated_qs)

    if direction == "out":
        endpoint_ids = [e.to_entity_id for e in edges_list]
        endpoint_filters = hop.get("target_filters", {})
    else:  # "in"
        endpoint_ids = [e.from_entity_id for e in edges_list]
        endpoint_filters = hop.get("source_filters", {})

    endpoint_qs = Entity.objects.using(db_alias).live().filter(id__in=endpoint_ids)
    if endpoint_filters:
        endpoint_qs = endpoint_qs.filter(**endpoint_filters)

    all_entities = list(endpoint_qs)
    nodes = _serialize_nodes(all_entities, layer, db_alias)
    edges = _serialize_edges(edges_list, layer, db_alias)
    return {"nodes": nodes, "edges": edges, "info": {"total_count": total_count}, "warnings": {}}


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def _apply_order(qs: Any, order_by: list[str] | None, default: list[str]) -> Any:
    """Apply order_by to a queryset; fall back to deterministic default."""
    return qs.order_by(*(order_by if order_by else default))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_nodes(
    entities: list[Entity],
    layer: SubgraphLayer,
    db_alias: str,
) -> list[dict[str, Any]]:
    """Serialize a list of Entity objects to node dicts at the requested layer."""
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


def _serialize_edges(
    edges: list[Edge],
    layer: SubgraphLayer,
    db_alias: str,
) -> list[dict[str, Any]]:
    """Serialize a list of Edge objects to edge dicts at the requested layer."""
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
