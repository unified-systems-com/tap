"""Graph Panel — built-in viz panel type for search-backed Cytoscape graph display.

Search binding:
  Panel links to a Layout via a USES_LAYOUT edge (Panel -> Layout).
  Layout links to a Search via a USES_SEARCH edge (Layout -> Search).
  Binding is pure topology — earliest-created edge wins. (The v0 role-name
  edge properties `layout-id`/`search-id` were deleted 2026-08-10 as unread
  remnants; future role-named multi-search binding rides a hotlink, see
  spec-viz-system.md.)

Rendering:
  Server-side: the linked Search executes during panel fragment rendering.
  The resulting nodes and edges are JSON-encoded and embedded in the template
  for Cytoscape to consume client-side.  Search inputs are forwarded from
  request.GET so that context parameters (e.g. entity_id) reach the search.

  Nodes and edges are returned in GRIFT extended layer format so the template
  receives icon_url, shape, url_id, from_name, to_name without additional
  panel-side enrichment.

Read-only: no graph or layout mutation occurs in this panel.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from tap_web.utils import graph_script_ids

# Accept only a narrow set of height values from panel config so the value can
# be emitted into an inline style attribute safely. Allowed:
#   - "100%"
#   - an integer-px value like "420px" (1..9999)
# Anything else falls back to the default (legacy 420px behaviour).
_ALLOWED_PANEL_HEIGHT = re.compile(r"^(100%|[1-9][0-9]{0,3}px)$")
_DEFAULT_PANEL_HEIGHT = "420px"


def _sanitize_panel_height(raw: Any) -> str:
    if isinstance(raw, str) and _ALLOWED_PANEL_HEIGHT.match(raw):
        return raw
    return _DEFAULT_PANEL_HEIGHT


if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)


# Declarative node-click navigation. A panel's config may carry a `nav_rules`
# array; graph_panel matches each rendered node against the rules and stamps a
# `nav_url` onto the node's `display.tap_viz` lane, which panel-graph.js turns
# into a single-tap navigation. Routing lives in the consumer's panel config
# (e.g. samsite's landing graph) — graph_panel only interprets this generic
# shape, so no consumer URLs leak into the platform.
#
# A rule matches by `entity_type` (and optional `where` equality against
# per-model `data` fields), then yields a URL from exactly one of:
#   - url_template: a static/internal path; "{entity_id}" is substituted.
#   - url_field:    read a per-model `data` field (e.g. github html_url).
# `external: true` opens the target in a new tab.
_NAV_RULES_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["entity_type"],
        "properties": {
            "entity_type": {"type": "string", "minLength": 1},
            "where": {"type": "object", "additionalProperties": {"type": "string"}},
            "url_template": {"type": "string", "minLength": 1},
            "url_field": {"type": "string", "minLength": 1},
            "external": {"type": "boolean"},
        },
        "oneOf": [
            {"required": ["url_template"]},
            {"required": ["url_field"]},
        ],
        "additionalProperties": False,
    },
}


def _apply_nav_rules(
    nodes: list[dict[str, Any]],
    rules: Any,
    panel_id: Any,
) -> None:
    """Stamp `display.tap_viz.nav_url` onto nodes per the panel's nav_rules.

    Mutates `nodes` in place. Navigation is a display enhancement, so invalid
    rules degrade gracefully (logged, no navigation) rather than blanking the
    graph. First matching rule wins per node.
    """
    if not rules:
        return
    try:
        import jsonschema

        jsonschema.validate(rules, _NAV_RULES_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[c3a7] graph panel %s: invalid nav_rules, skipping node navigation: %s",
            panel_id,
            exc,
        )
        return

    for node in nodes:
        entity_type = node.get("entity_type")
        data = node.get("data") or {}
        for rule in rules:
            if rule["entity_type"] != entity_type:
                continue
            where = rule.get("where") or {}
            if any(str(data.get(k)) != str(v) for k, v in where.items()):
                continue
            if "url_template" in rule:
                url = rule["url_template"].replace("{entity_id}", str(node.get("entity_id") or ""))
            else:
                field_val = data.get(rule["url_field"])
                if not field_val:
                    break  # no URL on this instance — leave it un-navigable
                url = str(field_val)
            display = node.setdefault("display", {})
            tap_viz = display.setdefault("tap_viz", {})
            tap_viz["nav_url"] = url
            if rule.get("external"):
                tap_viz["nav_external"] = True
            break


class GraphPanelType:
    """Built-in graph panel type descriptor.

    Implements get_view_context(panel, request) -> dict used by panel_view
    to resolve layout, execute the linked search, and return graph data
    for Cytoscape rendering.
    """

    slug = "graph"
    label = "Graph Panel"
    view = "tap_viz/panels/graph_panel.html"
    js: list[str] = [
        "tap_viz/js/lib/cytoscape.min.js",
        "tap_viz/js/panel-graph.js",
    ]
    css: list[str] = ["tap_viz/css/panel-graph.css"]
    config_defaults: dict[str, Any] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Resolve projection (preferred) or legacy layout, execute seed search, and
        pre-bake results for Cytoscape rendering.

        Resolution order:
          1. USES_PROJECTION edge -> Projection (new, projection-hosted panels)
          2. USES_LAYOUT edge -> Layout (legacy fallback)

        For projection-hosted panels: serializes the projection definition into
        the context so the client runtime can orchestrate elevations + layouts
        after bootstrap. The seed search (if any) is pre-baked for fast first
        paint, mirroring the legacy rendering path.
        """
        projection = _get_panel_projection(panel)
        if projection is not None:
            return cls._projection_context(panel, projection, request)

        layout = _get_panel_layout(panel)
        if layout is None:
            return _error_ctx("No projection or layout linked to this panel.")

        searches = _get_layout_searches(layout)
        if not searches:
            return _error_ctx("No search linked to this layout (USES_SEARCH edge missing).")

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        try:
            from tap_grid.search import execute_search, inputs_from_query

            # raw_inputs is what the client re-sends on badge refresh; each
            # search receives only its declared inputs, coerced by its schema.
            raw_inputs = {k: v for k, v in request.GET.items() if k not in ("limit", "offset", "page_size")}

            for search in searches:
                inputs = inputs_from_query(search, request.GET)
                result = execute_search(search, inputs=inputs or None, layer="extended")
                envelope = result.get("results", result)
                # Envelopes follow spec-grift-envelope: spine fields flat at top;
                # edge endpoint refs live in `data` for the lite-fallback key.
                for node in envelope.get("nodes", []):
                    nodes.setdefault(node["entity_id"], node)
                for edge in envelope.get("edges", []):
                    if "entity_id" in edge:
                        key = edge["entity_id"]
                    else:
                        ed = edge.get("data") or edge
                        key = f"{ed['from_entity_id']}-{ed['to_entity_id']}-{ed['edge_type']}"
                    edges.setdefault(key, edge)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[b9e0] Graph panel search execution failed for panel %s", panel.entity_id)
            return _error_ctx(f"Search execution failed: {exc}")

        presentation = layout.definition.get("presentation", {})
        placement = presentation.get("placement", "cytoscape:cose")
        nesting_enabled = presentation.get("nesting", {}).get("enabled", False)

        node_list = list(nodes.values())
        _apply_nav_rules(node_list, (panel.config or {}).get("nav_rules"), panel.entity_id)

        return {
            "graph_nodes": node_list,
            "graph_edges": list(edges.values()),
            "graph_projection": None,
            "graph_inputs": {},
            **graph_script_ids(panel.entity_id),
            "graph_placement": placement,
            "graph_nesting_enabled": nesting_enabled,
            "graph_height": _sanitize_panel_height((panel.config or {}).get("height")),
            "graph_error": None,
        }

    @classmethod
    def _projection_context(
        cls,
        panel: Panel,
        projection: Any,
        request: HttpRequest,
    ) -> dict[str, Any]:
        """Build a context dict for a projection-hosted graph panel.

        Pre-bakes the optional seed search (via USES_SEARCH on the Panel itself)
        for fast first paint; otherwise starts with an empty node/edge set. The
        client-side projection runtime takes over after handoff.
        """
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        seed_searches = _get_panel_seed_searches(panel)
        try:
            from tap_grid.search import execute_search, inputs_from_query

            raw_inputs = {k: v for k, v in request.GET.items() if k not in ("limit", "offset", "page_size")}
            for search in seed_searches:
                inputs = inputs_from_query(search, request.GET)
                result = execute_search(search, inputs=inputs or None, layer="extended")
                envelope = result.get("results", result)
                # Envelopes follow spec-grift-envelope: spine fields flat at top.
                for node in envelope.get("nodes", []):
                    nodes.setdefault(node["entity_id"], node)
                for edge in envelope.get("edges", []):
                    if "entity_id" in edge:
                        key = edge["entity_id"]
                    else:
                        ed = edge.get("data") or edge
                        key = f"{ed['from_entity_id']}-{ed['to_entity_id']}-{ed['edge_type']}"
                    edges.setdefault(key, edge)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[b601] Graph panel seed search failed for panel %s", panel.entity_id)
            return _error_ctx(f"Seed search execution failed: {exc}")

        from tap_viz.panels.graph_panel.projection_resolver import resolve_projection_definition

        resolved_definition = resolve_projection_definition(projection.definition or {})

        node_list = list(nodes.values())
        _apply_nav_rules(node_list, (panel.config or {}).get("nav_rules"), panel.entity_id)

        return {
            "graph_nodes": node_list,
            "graph_edges": list(edges.values()),
            "graph_projection": resolved_definition,
            "graph_inputs": raw_inputs,
            **graph_script_ids(panel.entity_id),
            "graph_placement": "projection",
            "graph_nesting_enabled": False,
            "graph_height": _sanitize_panel_height((panel.config or {}).get("height")),
            "graph_error": None,
        }


def _get_panel_projection(panel: Panel) -> Any | None:
    """Return the Projection linked to a Panel via USES_PROJECTION edge, or None."""
    from tap_grid.models import Edge
    from tap_viz.models import Projection

    edge = (
        Edge.objects.filter(
            from_entity=panel.entity,
            edge_type="USES_PROJECTION",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
        .first()
    )
    if edge is None:
        return None

    try:
        return Projection.objects.select_related("entity").get(entity=edge.to_entity)
    except Projection.DoesNotExist:
        logger.warning(
            "[eb52] USES_PROJECTION edge %s points to missing Projection entity %s",
            edge.pk,
            edge.to_entity_id,
        )
        return None


def _get_panel_seed_searches(panel: Panel) -> list[Any]:
    """Return any seed Searches linked directly to a Panel via USES_SEARCH edges."""
    from tap_grid.models import Edge, Search

    edges = (
        Edge.objects.filter(
            from_entity=panel.entity,
            edge_type="USES_SEARCH",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
    )

    results: list[Any] = []
    for edge in edges:
        try:
            results.append(Search.objects.select_related("entity").get(entity=edge.to_entity))
        except Search.DoesNotExist:
            logger.warning(
                "[1cbb] USES_SEARCH edge %s points to missing Search entity %s",
                edge.pk,
                edge.to_entity_id,
            )
    return results


def _get_panel_layout(panel: Panel) -> Any | None:
    """Return the Layout linked to a Panel via the earliest-created USES_LAYOUT edge, or None."""
    from tap_grid.models import Edge
    from tap_viz.models import Layout

    edge = (
        Edge.objects.filter(
            from_entity=panel.entity,
            edge_type="USES_LAYOUT",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
        .first()
    )
    if edge is None:
        return None

    try:
        return Layout.objects.select_related("entity").get(entity=edge.to_entity)
    except Layout.DoesNotExist:
        logger.warning(
            "[6f4e] USES_LAYOUT edge %s points to missing Layout entity %s",
            edge.pk,
            edge.to_entity_id,
        )
        return None


def _get_layout_searches(layout: Any) -> list[Any]:
    """Return all Searches linked to a Layout via USES_SEARCH edges, ordered by creation."""
    from tap_grid.models import Edge, Search

    edges = (
        Edge.objects.filter(
            from_entity=layout.entity,
            edge_type="USES_SEARCH",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
    )

    results = []
    for edge in edges:
        try:
            results.append(Search.objects.select_related("entity").get(entity=edge.to_entity))
        except Search.DoesNotExist:
            logger.warning(
                "[3255] USES_SEARCH edge %s points to missing Search entity %s",
                edge.pk,
                edge.to_entity_id,
            )
    return results


def _error_ctx(message: str) -> dict[str, Any]:
    return {
        "graph_nodes": [],
        "graph_edges": [],
        "graph_projection": None,
        "graph_inputs": {},
        "graph_placement": "cytoscape:cose",
        "graph_height": _DEFAULT_PANEL_HEIGHT,
        "graph_error": message,
    }
