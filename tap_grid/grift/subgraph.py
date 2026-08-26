"""GRIFT Subgraph serializers — canonical graph envelope shapes for TAP.

Implements the three subgraph return layers defined by spec-grift-subgraph
and the canonical envelope shape defined by spec-grift-envelope:

  lite      Spine-only envelope. Top-level Entity-row fields, no data lane.
  full      Spine + data lane. Per-model fields, polymorphic by entity_type.
  extended  Spine + data + display lane (consumer-namespaced under tap_viz).

The envelope is the canonical per-member shape. The same shape applies to
nodes and edges; polymorphism lives entirely inside the data lane.

Lane builders mirror the spec's vocabulary 1:1:

  build_spine_surface(entity) -> {<all Entity-row fields, flat at top>}
  build_data_lane(typed_model) -> {<all BaseModel-row fields, including
                                    universal description / batch_id /
                                    flip_map and the entity_id / name
                                    mirrors>}
  build_display_lane(...)     -> {"tap_viz": {<computed-for-render>}}

Layer serializers compose those lanes per req-grift-envelope-layer-mapping.

Entry points:
  serialize_subgraph(entities, edges, *, layer, db_alias) -> {nodes, edges}
  Individual lane builders and layer serializers for fine-grained control.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Literal

from django.utils.text import slugify

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tap_grid.models import BaseModel, Edge, Entity

SubgraphLayer = Literal["lite", "full", "extended"]


# ---------------------------------------------------------------------------
# Lane builders — one per envelope lane (spec-grift-envelope).
# ---------------------------------------------------------------------------
#
# Each builder returns a dict of *just its lane's contents*. Layer serializers
# below merge the lane dicts into the envelope per the layer's lane set.
#
# Naming intentionally mirrors the spec vocabulary so future readers can map
# code ↔ spec without translation. See spec-grift-envelope.md for the lane
# contract.


# Universal BaseModel-row fields that ride alongside per-model
# FIELD_CRUD_SCHEMA fields in the data lane. These are inherited by every
# concrete BaseModel and don't need to be redeclared per-model.
_BASEMODEL_UNIVERSAL_FIELDS: tuple[str, ...] = ("description", "batch_id", "flip_map")


def build_spine_surface(entity: Entity) -> dict[str, Any]:
    """Build the top-level spine surface for an envelope.

    Reads the canonical field set and order from
    ``Entity.SPINE_FIELD_NAMES`` (single source of truth — see
    spec-grid-entity § Canonical Spine Surface and
    req-grid-entity-spine-surface). Names are translated to their
    Django ORM attribute via ``Entity.SPINE_DJANGO_NAME`` when they
    differ (today only ``entity_id`` ↔ ``id``).

    Returned values are JSON-safe: UUIDs become strings, datetimes
    become ISO 8601, missing values stay ``None``.
    """
    from tap_grid.models import Entity as _Entity

    result: dict[str, Any] = {}
    for serialized_name in _Entity.SPINE_FIELD_NAMES:
        django_name = _Entity.SPINE_DJANGO_NAME.get(serialized_name, serialized_name)
        value = getattr(entity, django_name, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[serialized_name] = value
    return result


def build_data_lane(typed_model: BaseModel | None) -> dict[str, Any]:
    """Build the `data` lane for an envelope.

    Per spec-grift-envelope § Data Lane Rule:
    - Reads per-model FIELD_CRUD_SCHEMA fields (the typed surface the model
      declares as service-writeable).
    - Plus the universal BaseModel fields (`description`, `batch_id`,
      `flip_map`).
    - Includes the required `entity_id` and `name` mirrors of top-level
      values (req-grift-envelope-denorm-3 enforces mirror equality).
    - Excludes `entity_type` (it's a spine field, surfaces only at top).

    Returns {} when typed_model is None (rare; an envelope without a
    backing per-model row is a degenerate case the layer serializer
    should usually avoid by checking presence first).
    """
    if typed_model is None:
        return {}

    result: dict[str, Any] = {}

    # entity_id mirror (req-grift-envelope-denormalization).
    result["entity_id"] = str(typed_model.entity_id)

    # Per-model FIELD_CRUD_SCHEMA fields. Note that `name` is typically
    # declared here by the model — it surfaces as the second mirror.
    for field_name in typed_model.FIELD_CRUD_SCHEMA:
        if field_name == "entity_type":
            continue  # Spine field; never in data.
        value = getattr(typed_model, field_name, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field_name] = value

    # Universal BaseModel fields not already declared in FIELD_CRUD_SCHEMA.
    for field_name in _BASEMODEL_UNIVERSAL_FIELDS:
        if field_name in result:
            continue
        value = getattr(typed_model, field_name, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field_name] = value

    return result


def build_display_lane(
    *,
    tap_viz_hints: dict[str, Any] | None = None,
    icon_url: str = "",
    url_id: str = "",
    from_label: str | None = None,
    to_label: str | None = None,
) -> dict[str, Any]:
    """Build the `display` lane for an envelope.

    Per spec-grift-envelope § Display Lane Rule the lane is consumer-
    namespaced; v0 populates only the `tap_viz` sub-namespace. Future
    consumers (table panels, info windows, list panels) will add their
    own sibling keys.

    `tap_viz_hints` is the per-type DEFAULT_DISPLAY["tap_viz"] dict
    (shape, colors, label, nesting hints, ...). `icon_url` and `url_id`
    are computed-for-render values that fold into the same lane.
    `from_label` and `to_label` are the edge endpoint labels (replace
    the retired flat `from_name`/`to_name`).
    """
    hints = dict(tap_viz_hints or {})
    if icon_url:
        hints["icon_url"] = icon_url
    if url_id:
        hints["url_id"] = url_id
    if from_label is not None:
        hints["from_label"] = from_label
    if to_label is not None:
        hints["to_label"] = to_label
    return {"tap_viz": hints} if hints else {}


# ---------------------------------------------------------------------------
# Backwards-compat shim — keeps a few callers that still want just the
# Entity-row dict working without a code change in the same commit.
# ---------------------------------------------------------------------------


def serialize_entity_envelope(entity: Entity) -> dict[str, Any]:
    """Return the Entity-row spine surface as a flat dict.

    Alias for build_spine_surface, kept for backwards compatibility with
    callers that previously consumed serialize_entity_envelope before
    envelope-spec rework.
    """
    return build_spine_surface(entity)


# ---------------------------------------------------------------------------
# Node serializers — one per return layer.
# ---------------------------------------------------------------------------


def serialize_node_lite(entity: Entity) -> dict[str, Any]:
    """Lite layer: spine surface only — no data, no display."""
    return build_spine_surface(entity)


def serialize_node_full(
    entity: Entity,
    typed_model: BaseModel | None = None,
) -> dict[str, Any]:
    """Full layer: spine surface + data lane."""
    return {
        **build_spine_surface(entity),
        "data": build_data_lane(typed_model),
    }


def serialize_node_extended(
    entity: Entity,
    typed_model: BaseModel | None = None,
    *,
    icon_url: str = "",
    tap_viz_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extended layer: spine surface + data lane + display lane."""
    spine = build_spine_surface(entity)
    slug = slugify(entity.name) or "entity"
    url_id = f"{slug}--{spine['entity_id']}"
    display = build_display_lane(
        tap_viz_hints=tap_viz_hints,
        icon_url=icon_url,
        url_id=url_id,
    )
    envelope: dict[str, Any] = {
        **spine,
        "data": build_data_lane(typed_model),
    }
    if display:
        envelope["display"] = display
    return envelope


# ---------------------------------------------------------------------------
# Edge serializers — same envelope shape; polymorphism lives in `data`.
# ---------------------------------------------------------------------------


def _build_edge_data_lane(edge: Edge) -> dict[str, Any]:
    """Build the `data` lane for an edge envelope.

    Edges have a small fixed shape: the two endpoint FKs, the immutable
    edge_type, and the properties JSONField. Universal BaseModel fields
    (description, batch_id, flip_map) are included; mirrors of entity_id
    and name follow the same rule as node envelopes.
    """
    result: dict[str, Any] = {
        "entity_id": str(edge.entity_id),
        "name": edge.entity.name if edge.entity else "",
        "from_entity_id": str(edge.from_entity_id),
        "to_entity_id": str(edge.to_entity_id),
        "edge_type": edge.edge_type,
        "properties": edge.properties,
    }
    for field_name in _BASEMODEL_UNIVERSAL_FIELDS:
        if field_name in result:
            continue
        value = getattr(edge, field_name, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field_name] = value
    return result


def serialize_edge_lite(edge: Edge) -> dict[str, Any]:
    """Lite layer: spine surface only — no data, no display.

    Requires edge.entity to be available (use select_related("entity")).
    """
    return build_spine_surface(edge.entity)


def serialize_edge_full(edge: Edge) -> dict[str, Any]:
    """Full layer: spine surface + data lane.

    Requires edge.entity to be available (use select_related("entity")).
    """
    return {
        **build_spine_surface(edge.entity),
        "data": _build_edge_data_lane(edge),
    }


def serialize_edge_extended(
    edge: Edge,
    *,
    from_label: str = "",
    to_label: str = "",
    tap_viz_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extended layer: spine surface + data lane + display lane.

    `from_label` and `to_label` replace the retired flat `from_name`/
    `to_name` on edge envelopes. They live inside `display.tap_viz`.
    """
    display = build_display_lane(
        tap_viz_hints=tap_viz_hints,
        from_label=from_label,
        to_label=to_label,
    )
    envelope: dict[str, Any] = {
        **build_spine_surface(edge.entity),
        "data": _build_edge_data_lane(edge),
    }
    if display:
        envelope["display"] = display
    return envelope


# ---------------------------------------------------------------------------
# Batch resolution helpers — unchanged by the envelope rework.
# ---------------------------------------------------------------------------


def batch_resolve_typed_models(
    entities: Iterable[Entity],
    db_alias: str,
) -> dict[str, Any]:
    """Resolve entities to typed model instances in batch.

    Groups by entity_type and issues one query per type.
    Skips entity_type="edge" (edges are resolved separately).

    Returns:
        {entity_id_str: typed_model_instance}
    """
    from tap_grid.registry import get_model_class

    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for entity in entities:
        if entity.entity_type != "edge":
            by_type[entity.entity_type].append(entity.pk)

    result: dict[str, Any] = {}
    for entity_type, pks in by_type.items():
        try:
            model_cls = get_model_class(entity_type)
        except KeyError:
            continue
        for obj in model_cls.objects.using(db_alias).filter(entity_id__in=pks):
            result[str(obj.entity_id)] = obj
    return result


def batch_resolve_icon_urls(entity_type_slugs: set[str]) -> dict[str, str]:
    """Resolve icon URLs for a set of entity type slugs in batch.

    Returns:
        {slug: url_string} — empty string for types with no icon.
    """
    from tap_grid.icon import resolve_icon_url
    from tap_grid.models import EntityType

    if not entity_type_slugs:
        return {}
    return {et.slug: resolve_icon_url(et) or "" for et in EntityType.objects.filter(slug__in=entity_type_slugs)}


def batch_resolve_display(entity_type_slugs: set[str]) -> dict[str, dict[str, Any]]:
    """Resolve full tap_viz display metadata for a set of entity type slugs.

    Returns the complete ``DEFAULT_DISPLAY.get("tap_viz", {})`` dict per slug,
    making shape, nesting, and any future display concerns transparent.

    Returns:
        {slug: tap_viz_display_dict}
    """
    from tap_grid.registry import get_model_class

    result: dict[str, dict[str, Any]] = {}
    for slug in entity_type_slugs:
        try:
            model_cls = get_model_class(slug)
            result[slug] = model_cls.DEFAULT_DISPLAY.get("tap_viz", {})
        except KeyError:
            result[slug] = {}
    return result


def batch_resolve_entity_names(
    entity_ids: set[str],
    db_alias: str,
) -> dict[str, str]:
    """Resolve entity display names for a set of entity IDs in batch.

    Returns:
        {entity_id_str: name}
    """
    from tap_grid.models import Entity

    if not entity_ids:
        return {}
    return {str(e.pk): e.name for e in Entity.objects.using(db_alias).filter(pk__in=entity_ids).only("id", "name")}


# ---------------------------------------------------------------------------
# Subgraph convenience function
# ---------------------------------------------------------------------------


def serialize_subgraph(
    entities: list[Entity],
    edges: list[Edge],
    *,
    layer: SubgraphLayer = "full",
    db_alias: str = "default",
) -> dict[str, Any]:
    """Serialize entities and edges into a canonical GRIFT subgraph envelope.

    Handles all batch resolution internally based on the requested layer.

    Returns:
        {"nodes": [...], "edges": [...]} where each member is an envelope
        per spec-grift-envelope.
    """
    if layer == "lite":
        return {
            "nodes": [serialize_node_lite(e) for e in entities],
            "edges": [serialize_edge_lite(e) for e in edges],
        }

    # full and extended both need typed models.
    typed_models = batch_resolve_typed_models(entities, db_alias)

    if layer == "full":
        return {
            "nodes": [serialize_node_full(e, typed_models.get(str(e.pk))) for e in entities],
            "edges": [serialize_edge_full(e) for e in edges],
        }

    # extended — resolve presentation metadata.
    slugs = {e.entity_type for e in entities if e.entity_type != "edge"}
    icon_map = batch_resolve_icon_urls(slugs)
    display_map = batch_resolve_display(slugs)

    # Edge endpoint labels.
    endpoint_ids: set[str] = set()
    for edge in edges:
        endpoint_ids.add(str(edge.from_entity_id))
        endpoint_ids.add(str(edge.to_entity_id))
    name_map = batch_resolve_entity_names(endpoint_ids, db_alias)

    return {
        "nodes": [
            serialize_node_extended(
                e,
                typed_models.get(str(e.pk)),
                icon_url=icon_map.get(e.entity_type, ""),
                tap_viz_hints=display_map.get(e.entity_type, {}),
            )
            for e in entities
        ],
        "edges": [
            serialize_edge_extended(
                e,
                from_label=name_map.get(str(e.from_entity_id), ""),
                to_label=name_map.get(str(e.to_entity_id), ""),
            )
            for e in edges
        ],
    }
