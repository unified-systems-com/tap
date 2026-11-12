"""Resource drawer context per spec-web-drawer.

One entity's data, grouped into the categories a list reader asks about: Overview,
Findings, Relationships, Configuration, Tags, Provenance and Raw. Every category is
derived from the entity's own fields, its live edges and its FLIP map; an entity type
adds nothing to get a drawer. A model may refine two things by declaration:

- ``DRAWER_ROLE = "finding"``: its instances count as findings of the entities they touch.
- ``DRAWER_GROUPS = {"Label": ["field", ...]}``: how Configuration groups its fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from django.urls import reverse

from tap_web.page import build_url_id

OVERVIEW_FIELDS = (
    "status",
    "state",
    "severity",
    "severity_label",
    "workflow_status",
    "compliance_status",
    "product_name",
    "finding_type",
    "resource_type",
    "resource_types",
    "resource_ids",
    "instance_id",
    "instance_type",
    "ec2_type",
    "private_ip",
    "cidr_block",
    "availability_zone",
    "region",
    "account_id",
    "arn",
    "created_at",
    "updated_at",
    "first_observed_at",
    "last_observed_at",
)
"""Scalar fields that identify an object at a glance, shown first when the model has them.

A model may declare ``DRAWER_OVERVIEW = ("field", ...)`` to put its own identifying fields first.
"""
_PLACE_EDGE = re.compile(r"(ACCOUNT|REGION)$")

RELATIONSHIP_GROUP_LIMIT = 25
SKIP_FIELDS = {"id", "entity_id", "batch_id", "flip_map"}
DEPLOYED_FROM_KEYS = ("deployed_from", "DeployedFrom", "deployed-from")
_FINDING_HOLDER = re.compile(r"^HOLDS_[A-Z0-9_]*FINDING$")


@dataclass
class Neighbour:
    name: str
    entity_type: str
    drawer_url: str
    page_url: str
    type_name: str = ""


@dataclass
class EdgeGroup:
    label: str
    direction: str
    neighbours: list[Neighbour] = field(default_factory=list)
    total: int = 0
    edge_type: str = ""


@dataclass
class FieldRow:
    label: str
    text: str
    is_block: bool


def base_edge_type(edge_type: str) -> str:
    """``CONCERNS_RESOURCE__aws_core`` -> ``CONCERNS_RESOURCE``: the plugin suffix is namespacing, not meaning."""
    return edge_type.split("__", 1)[0]


def edge_label(edge_type: str) -> str:
    return base_edge_type(edge_type).replace("_", " ").capitalize()


def is_finding_edge(edge_type: str, direction: str, neighbour_model: type | None) -> bool:
    """Whether the neighbour across this edge is a finding about the subject.

    TAP-IMPLEMENTS: req-web-drawer-categories@40439273ba3b/cb26b75d1f19 (derivation) — the one rule that
        splits Findings from Relationships: a neighbour model declaring DRAWER_ROLE="finding", an
        incoming CONCERNS_RESOURCE* edge, or an outgoing HOLDS_*FINDING edge.
    """
    if neighbour_model is not None and getattr(neighbour_model, "DRAWER_ROLE", "") == "finding":
        return True
    base = base_edge_type(edge_type)
    if direction == "in" and base.startswith("CONCERNS_RESOURCE"):
        return True
    return direction == "out" and bool(_FINDING_HOLDER.match(base))


def _format(value: Any) -> tuple[str, bool]:
    from tap_web.panels.viewer_panel import _format_value

    return _format_value(value)


def _model_class(entity_type: str) -> Any:
    from tap_grid.registry import get_model_class

    try:
        return get_model_class(entity_type)
    except KeyError:
        return None


def _type_names(slugs: set[str]) -> dict[str, str]:
    """Display names for entity types; a type without a row keeps its slug."""
    from tap_grid.models import EntityType

    return {row.slug: row.name for row in EntityType.objects.filter(slug__in=slugs) if row.name}


def context_rows(relationships: list[EdgeGroup]) -> list[FieldRow]:
    """Overview rows for what a finding concerns and where the object lives.

    A single outgoing ``CONCERNS_RESOURCE*`` edge is the "Resource" row (named with its type); a single
    outgoing edge to an account or a region is a row labelled with that type.
    """
    rows: list[FieldRow] = []
    for g in relationships:
        if g.direction != "out" or g.total != 1 or not g.neighbours:
            continue
        n, base = g.neighbours[0], base_edge_type(g.edge_type)
        type_name = n.type_name or n.entity_type
        if base.startswith("CONCERNS_RESOURCE"):
            rows.insert(0, FieldRow("Resource", f"{n.name} ({type_name})", False))
        elif _PLACE_EDGE.search(base):
            rows.append(FieldRow(type_name, n.name, False))
    return rows


def object_urls(entity_type: str, name: str, entity_id: Any) -> tuple[str, str]:
    """The drawer fragment URL and the full viewer URL for one entity."""
    url_id = build_url_id(name, entity_id)
    kwargs = {"entity_type": entity_type, "object_url_id": url_id}
    return reverse("object-drawer", kwargs=kwargs), reverse("object-view", kwargs=kwargs)


def _field_values(obj: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for f in obj._meta.get_fields():
        if f.is_relation or f.name in SKIP_FIELDS or f.name in values:
            continue
        values[f.name] = getattr(obj, f.name, None)
    return values


def _labels(obj: Any) -> dict[str, str]:
    from tap_web.panels.viewer_panel import field_label

    out: dict[str, str] = {}
    for f in obj._meta.get_fields():
        if not f.is_relation:
            out[f.name] = field_label(f)
    return out


def _tag_rows(tags: Any) -> list[tuple[str, str]]:
    if isinstance(tags, dict):
        return sorted((str(k), "" if v is None else str(v)) for k, v in tags.items())
    if isinstance(tags, list):
        rows = []
        for item in tags:
            if isinstance(item, dict):
                key = item.get("Key", item.get("key"))
                if key is not None:
                    rows.append((str(key), str(item.get("Value", item.get("value", "")) or "")))
        return sorted(rows)
    return []


def _edge_groups(entity: Any) -> tuple[list[EdgeGroup], list[EdgeGroup]]:
    """Split the entity's live edges into (findings, relationships), grouped by type and direction."""
    from tap_grid.models import Edge

    findings: dict[tuple[str, str], EdgeGroup] = {}
    related: dict[tuple[str, str], EdgeGroup] = {}
    edges: Any = Edge.objects
    queries = (
        ("out", edges.filter(from_entity=entity, to_entity__deleted_at__isnull=True).select_related("to_entity")),
        ("in", edges.filter(to_entity=entity, from_entity__deleted_at__isnull=True).select_related("from_entity")),
    )
    models: dict[str, Any] = {}
    for direction, qs in queries:
        for edge in qs.order_by("edge_type"):
            other = edge.to_entity if direction == "out" else edge.from_entity
            if other.entity_type not in models:
                models[other.entity_type] = _model_class(other.entity_type)
            bucket = findings if is_finding_edge(edge.edge_type, direction, models[other.entity_type]) else related
            key = (edge.edge_type, direction)
            group = bucket.setdefault(key, EdgeGroup(label=edge_label(edge.edge_type), direction=direction, edge_type=edge.edge_type))
            group.total += 1
            if len(group.neighbours) < RELATIONSHIP_GROUP_LIMIT:
                drawer_url, page_url = object_urls(other.entity_type, other.name, other.pk)
                group.neighbours.append(
                    Neighbour(name=other.name or str(other.pk), entity_type=other.entity_type, drawer_url=drawer_url, page_url=page_url)
                )

    def ordered(groups: dict[tuple[str, str], EdgeGroup]) -> list[EdgeGroup]:
        return sorted(groups.values(), key=lambda g: (-g.total, g.label, g.direction))

    return ordered(findings), ordered(related)


def build_drawer_context(entity_type: str, entity_id: str) -> dict[str, Any] | None:
    """Everything the drawer fragment renders for one entity, or ``None`` if it does not resolve.

    TAP-IMPLEMENTS: req-web-drawer-fragment@4bc796834185/829f38d64950 (derivation) — the drawer's
        one context: identity, the seven categories and the two links, from the entity's fields,
        edges and FLIP map, for any registered type.
    """
    from tap_web.panels.flip_panel import get_flip_context_for_entity

    model_cls = _model_class(entity_type)
    if model_cls is None:
        return None
    try:
        obj = model_cls.objects.select_related("entity").get(entity__pk=entity_id)
    except model_cls.DoesNotExist:
        return None

    entity = obj.entity
    name = entity.name or str(obj)
    values = _field_values(obj)
    labels = _labels(obj)

    overview = []
    overview_fields = tuple(dict.fromkeys((*getattr(model_cls, "DRAWER_OVERVIEW", ()), *OVERVIEW_FIELDS)))
    for key in overview_fields:
        if values.get(key) not in (None, "", [], {}):
            value = values[key]
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (str, int, float)):
                value = value[0]
            text, is_block = _format(value)
            if not is_block:
                overview.append(FieldRow(labels.get(key, key), text, False))

    tags = _tag_rows(values.get("tags"))
    declared_in = next((v for k, v in tags if k in DEPLOYED_FROM_KEYS and v), "")

    groups_decl: dict[str, list[str]] = getattr(model_cls, "DRAWER_GROUPS", {}) or {}
    shown = {"tags", "configuration", *overview_fields}
    configuration: list[tuple[str, list[FieldRow]]] = []
    grouped: set[str] = set()
    for label, names in groups_decl.items():
        rows = [FieldRow(labels.get(n, n), *_format(values[n])) for n in names if n in values]
        if rows:
            configuration.append((label, rows))
            grouped.update(names)
    rest = [
        FieldRow(labels.get(n, n), *_format(v))
        for n, v in values.items()
        if n not in grouped and n not in shown and v not in (None, "", [], {})
    ]
    if rest:
        configuration.append(("Fields", rest))

    raw_source = values.get("configuration")
    raw = json.dumps(
        raw_source if isinstance(raw_source, (dict, list)) and raw_source else values,
        indent=2,
        sort_keys=True,
        default=str,
    )

    findings, relationships = _edge_groups(entity)
    flip = get_flip_context_for_entity(str(entity.pk))

    neighbours = [n for g in (*findings, *relationships) for n in g.neighbours]
    type_names = _type_names({entity_type, *(n.entity_type for n in neighbours)})
    for n in neighbours:
        n.type_name = type_names.get(n.entity_type, n.entity_type)
    context = context_rows(relationships)
    lead = [r for r in context if r.label == "Resource"]
    overview = [*lead, *overview, *(r for r in context if r.label != "Resource")]

    type_name, icon_url = type_names.get(entity_type, entity_type), ""
    try:
        from tap_grid.icon import resolve_icon_url
        from tap_grid.models import EntityType

        et_row = EntityType.objects.filter(slug=entity_type).first()
        if et_row is not None:
            icon_url = resolve_icon_url(et_row) or ""
    except Exception:  # noqa: BLE001 — icon lookup is best-effort visual chrome
        pass

    drawer_url, page_url = object_urls(entity_type, name, entity.pk)
    return {
        "drawer_name": name,
        "drawer_entity_id": str(entity.pk),
        "drawer_entity_type": entity_type,
        "drawer_type_name": type_name,
        "drawer_icon_url": icon_url,
        "drawer_url": drawer_url,
        "drawer_page_url": page_url,
        "drawer_overview": overview,
        "drawer_findings": findings,
        "drawer_findings_total": sum(g.total for g in findings),
        "drawer_relationships": relationships,
        "drawer_relationships_total": sum(g.total for g in relationships),
        "drawer_configuration": configuration,
        "drawer_configuration_total": sum(len(rows) for _, rows in configuration),
        "drawer_tags": tags,
        "drawer_declared_in": declared_in,
        "drawer_flip_rows": flip.get("flip_rows") or [],
        "drawer_raw": raw,
    }
