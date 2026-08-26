"""Synthetic page builder — renders pages from GRIFT subgraphs without persisting to the grid.

A synthetic page is defined by a GRIFT subgraph containing Page, Panel, Layout,
and Search nodes connected by USES_PANEL, USES_LAYOUT, and USES_SEARCH edges.
The builder parses the subgraph, resolves the composition chain in memory,
executes searches through the standard search service, renders each panel
inline (server-side), and assembles the final page response.

See req-web-page-synthetic in spec-web-page.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from tap_web.page import build_url_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight wrappers — quack like Django model instances for templates
# ---------------------------------------------------------------------------


class SyntheticNode:
    """Base wrapper for a GRIFT node envelope (entity + node payload)."""

    def __init__(self, envelope: dict[str, Any]) -> None:
        entity = envelope.get("entity", {})
        node = envelope.get("node", {})
        self._entity = entity
        self._node = node
        self.entity_id: str = entity.get("entity_id", "")
        self.entity_type: str = entity.get("entity_type", "")
        self.name: str = node.get("name", entity.get("name", ""))

    def __str__(self) -> str:
        return self.name or self.entity_id


class SyntheticPage(SyntheticNode):
    """In-memory Page — provides slug and layout for template rendering."""

    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(envelope)
        self.slug: str = self._node.get("slug", "")
        self.layout: dict = self._node.get("layout", {})
        self.description: str = self._node.get("description", "")


class SyntheticPanel(SyntheticNode):
    """In-memory Panel — provides view, config, and editor hooks for panel
    rendering. Static assets come from the panel type, not the instance."""

    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(envelope)
        self.slug: str = self._node.get("slug", "")
        self.view: str = self._node.get("view", "")
        self.config: dict = self._node.get("config", {})
        self.editor_view: str = self._node.get("editor_view", "")
        self.description: str = self._node.get("description", "")


class SyntheticLayout(SyntheticNode):
    """In-memory Layout — provides definition for graph panel rendering."""

    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(envelope)
        self.definition: dict = self._node.get("definition", {})
        self.description: str = self._node.get("description", "")


class SyntheticSearch(SyntheticNode):
    """In-memory Search — provides all attributes expected by execute_search()."""

    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(envelope)
        self.search_type: str = self._node.get("search_type", "")
        self.root: str = self._node.get("root", "")
        self.definition: dict = self._node.get("definition", {})
        self.input_schema: dict = self._node.get("input_schema", {})
        self.default_limit: int = self._node.get("default_limit", 100)
        self.max_limit: int = self._node.get("max_limit", 500)
        self.description: str = self._node.get("description", "")


# ---------------------------------------------------------------------------
# SyntheticGraph — in-memory graph index
# ---------------------------------------------------------------------------

_NODE_CLASSES: dict[str, type[SyntheticNode]] = {
    "page": SyntheticPage,
    "panel": SyntheticPanel,
    "layout": SyntheticLayout,
    "search": SyntheticSearch,
}


class SyntheticGraph:
    """In-memory index of a GRIFT subgraph.

    Provides fast lookup by entity_id and edge traversal without DB queries.
    """

    def __init__(self, subgraph: dict[str, Any]) -> None:
        self.nodes: dict[str, SyntheticNode] = {}
        self.edges_from: dict[str, list[dict]] = {}

        raw_nodes = subgraph.get("nodes", [])
        raw_edges = subgraph.get("edges", [])

        # If this is a batched GRIFT file, flatten the first batch.
        if not raw_nodes and "batches" in subgraph:
            batch = subgraph["batches"][0] if subgraph["batches"] else {}
            raw_nodes = batch.get("nodes", [])
            raw_edges = batch.get("edges", [])

        for envelope in raw_nodes:
            entity = envelope.get("entity", {})
            entity_type = entity.get("entity_type", "")
            entity_id = entity.get("entity_id", "")
            cls = _NODE_CLASSES.get(entity_type, SyntheticNode)
            self.nodes[entity_id] = cls(envelope)

        for envelope in raw_edges:
            edge = envelope.get("edge", {})
            from_id = edge.get("from_entity_id", "")
            self.edges_from.setdefault(from_id, []).append(edge)

    def get_page(self, slug: str | None = None) -> SyntheticPage | None:
        """Return the first Page node, optionally filtered by slug."""
        for node in self.nodes.values():
            if isinstance(node, SyntheticPage):
                if slug is None or node.slug == slug:
                    return node
        return None

    def get_panels_for_page(self, page: SyntheticPage) -> dict[str, SyntheticPanel]:
        """Return {panel_id: SyntheticPanel} for all USES_PANEL edges from page."""
        result: dict[str, SyntheticPanel] = {}
        for edge in self.edges_from.get(page.entity_id, []):
            if edge.get("edge_type") != "USES_PANEL":
                continue
            hotlink = edge.get("properties", {}).get("hotlink", {})
            panel_id = hotlink.get("value", "")
            target = self.nodes.get(edge.get("to_entity_id", ""))
            if isinstance(target, SyntheticPanel) and panel_id:
                result[panel_id] = target
        return result

    def get_layout_for_panel(self, panel: SyntheticPanel) -> SyntheticLayout | None:
        """Follow USES_LAYOUT edge from panel to its Layout."""
        for edge in self.edges_from.get(panel.entity_id, []):
            if edge.get("edge_type") != "USES_LAYOUT":
                continue
            target = self.nodes.get(edge.get("to_entity_id", ""))
            if isinstance(target, SyntheticLayout):
                return target
        return None

    def get_searches_for_layout(self, layout: SyntheticLayout) -> list[SyntheticSearch]:
        """Follow USES_SEARCH edges from layout to its Searches."""
        results: list[SyntheticSearch] = []
        for edge in self.edges_from.get(layout.entity_id, []):
            if edge.get("edge_type") != "USES_SEARCH":
                continue
            target = self.nodes.get(edge.get("to_entity_id", ""))
            if isinstance(target, SyntheticSearch):
                results.append(target)
        return results


# ---------------------------------------------------------------------------
# Synthetic panel rendering
# ---------------------------------------------------------------------------


def _render_graph_panel_context(
    panel: SyntheticPanel,
    graph: SyntheticGraph,
    request: HttpRequest,
) -> dict[str, Any]:
    """Build graph panel context by resolving Layout→Search from the in-memory graph."""
    from tap_web.utils import safe_json

    layout = graph.get_layout_for_panel(panel)
    if layout is None:
        return {
            "graph_nodes_json": safe_json([]),
            "graph_edges_json": safe_json([]),
            "graph_placement": "cytoscape:cose",
            "graph_error": "No layout linked to this panel (USES_LAYOUT edge missing).",
        }

    searches = graph.get_searches_for_layout(layout)
    if not searches:
        return {
            "graph_nodes_json": safe_json([]),
            "graph_edges_json": safe_json([]),
            "graph_placement": "cytoscape:cose",
            "graph_error": "No search linked to this layout (USES_SEARCH edge missing).",
        }

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    try:
        from tap_grid.search import execute_search

        raw_inputs = {k: v for k, v in request.GET.items() if k not in ("limit", "offset")}
        for search in searches:
            result = execute_search(search, inputs=raw_inputs or None, layer="extended")
            envelope = result.get("results", result)
            # Envelopes follow spec-grift-envelope: spine fields flat at top.
            for node in envelope.get("nodes", []):
                nodes.setdefault(node["entity_id"], node)
            for edge_data in envelope.get("edges", []):
                if "entity_id" in edge_data:
                    key = edge_data["entity_id"]
                else:
                    ed = edge_data.get("data") or edge_data
                    key = f"{ed['from_entity_id']}-{ed['to_entity_id']}-{ed['edge_type']}"
                edges.setdefault(key, edge_data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[240a] Synthetic graph panel search failed for panel %s", panel.entity_id)
        return {
            "graph_nodes_json": safe_json([]),
            "graph_edges_json": safe_json([]),
            "graph_placement": "cytoscape:cose",
            "graph_error": f"Search execution failed: {exc}",
        }

    placement = layout.definition.get("presentation", {}).get("placement", "cytoscape:cose")

    # Pass through panel.config.height so the graph_panel template gets the
    # same sizing affordance synthetic pages would otherwise lose. Uses the
    # same sanitizer as the regular graph panel path.
    from tap_viz.panels.graph_panel import _sanitize_panel_height

    return {
        "graph_nodes_json": safe_json(list(nodes.values())),
        "graph_edges_json": safe_json(list(edges.values())),
        "graph_placement": placement,
        "graph_height": _sanitize_panel_height((panel.config or {}).get("height")),
        "graph_error": None,
    }


def _get_panel_type_for_view(view: str) -> type | None:
    """Return the registered PanelType whose view matches, or None."""
    from tap_web.registry import panel_type_registry

    for scope_data in panel_type_registry.all().values():
        for panel_type_cls in scope_data.values():
            if getattr(panel_type_cls, "view", None) == view:
                return panel_type_cls
    return None


def _render_synthetic_panel(
    panel: SyntheticPanel,
    graph: SyntheticGraph,
    request: HttpRequest,
) -> str:
    """Render a single synthetic panel to an HTML string."""
    from tap_viz.panels.graph_panel import GraphPanelType

    panel_type = _get_panel_type_for_view(panel.view)

    # Graph panels need special handling — resolve Layout→Search from in-memory graph.
    if panel_type is GraphPanelType or (panel_type and issubclass(panel_type, GraphPanelType)):
        extra_ctx = _render_graph_panel_context(panel, graph, request)
    elif panel_type and hasattr(panel_type, "get_view_context"):
        # Non-graph panels (viewer, editor, flip) read subject from request.GET
        # and resolve from DB — they work as-is with synthetic panels.
        extra_ctx = panel_type.get_view_context(panel, request) or {}

        # For editor panels rendered inline, route form POST to the object edit
        # URL instead of the (non-existent) synthetic panel endpoint.
        from tap_web.panels.editor_panel import EditorPanelType

        if panel_type is EditorPanelType or (isinstance(panel_type, type) and issubclass(panel_type, EditorPanelType)):
            entity_id = request.GET.get("entity_id", "")
            entity_type = request.GET.get("entity_type", "")
            editor_obj = extra_ctx.get("editor_obj")
            if editor_obj and entity_id and entity_type:
                slug = getattr(editor_obj, "slug", "") or getattr(editor_obj, "name", "") or ""
                object_url_id = build_url_id(slug, entity_id)
                extra_ctx["editor_form_action"] = reverse(
                    "object-edit", kwargs={"entity_type": entity_type, "object_url_id": object_url_id}
                )
    else:
        extra_ctx = {}

    ctx = {"panel": panel, **extra_ctx}

    try:
        return render_to_string(panel.view, ctx, request=request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[ac97] Failed to render synthetic panel %s (view=%s)", panel.entity_id, panel.view)
        return f'<div class="text-red-600 text-sm p-4">Panel render error: {exc}</div>'


# ---------------------------------------------------------------------------
# Synthetic page assembly
# ---------------------------------------------------------------------------


def render_synthetic_page(
    request: HttpRequest,
    subgraph: dict[str, Any],
    *,
    page_slug: str | None = None,
    extra_query_params: dict[str, str] | None = None,
) -> HttpResponse:
    """Render a full page from a GRIFT subgraph without persisting anything.

    Args:
        request: The current HTTP request.
        subgraph: A GRIFT subgraph dict with nodes and edges.
        page_slug: Optional slug to select a specific Page node if the
            subgraph contains multiple pages.
        extra_query_params: Additional query params to inject (e.g. entity_id,
            entity_type for viewer/editor pages). These are merged into
            request.GET for panel rendering.

    Returns:
        An HttpResponse with the fully rendered page.
    """
    import re

    graph = SyntheticGraph(subgraph)
    page = graph.get_page(slug=page_slug)
    if page is None:
        from django.http import Http404

        raise Http404("Synthetic page not found in subgraph.")

    # Inject extra query params so panels can read them from request.GET.
    if extra_query_params:
        request.GET = request.GET.copy()
        request.GET.update(extra_query_params)

    panels_by_id = graph.get_panels_for_page(page)

    # Collect CSS/JS assets across all panels.
    # Panel type assets (from the registered PanelType class) are included first
    # so infrastructure scripts (e.g. cytoscape-grid-guide) are loaded
    # automatically without requiring each GRIFT panel to declare them.
    from tap_web.views import _get_panel_type_for_panel

    # Panel types are authoritative for static assets; panel instances do
    # not declare js/css.
    css: dict[str, None] = {}
    js: dict[str, None] = {}
    for panel in panels_by_id.values():
        panel_type = _get_panel_type_for_panel(panel)
        for path in getattr(panel_type, "css", []):
            css[path] = None
        for path in getattr(panel_type, "js", []):
            js[path] = None

    # Process layout into sorted columns and rows, then render each panel inline.
    layout = page.layout or {}
    columns_raw = layout.get("columns", {})

    numeric_re = re.compile(r"^[a-z]+-(\d+)")

    def _sort_key(key: str) -> int:
        m = numeric_re.match(key)
        return int(m.group(1)) if m else 0

    columns = sorted(columns_raw.items(), key=lambda kv: _sort_key(kv[0]))

    processed_columns: list[dict] = []
    for col_key, col_data in columns:
        rows_raw = col_data.get("rows", {})
        rows = sorted(rows_raw.items(), key=lambda kv: _sort_key(kv[0]))

        processed_rows: list[dict] = []
        for row_key, row_data in rows:
            panel_id = row_data.get("panel-id", "")
            panel = panels_by_id.get(panel_id)

            rendered_html = ""
            if panel is not None:
                rendered_html = _render_synthetic_panel(panel, graph, request)

            processed_rows.append(
                {
                    "key": row_key,
                    "panel_id": panel_id,
                    "rendered_html": rendered_html,
                    "has_panel": panel is not None,
                    "row_span": row_data.get("row_span", 1),
                    "col_span": row_data.get("col_span", 1),
                }
            )

        processed_columns.append(
            {
                "key": col_key,
                "width": col_data.get("width", "1fr"),
                "rows": processed_rows,
            }
        )

    context = {
        "page": page,
        "processed_columns": processed_columns,
        "css_assets": list(css),
        "js_assets": list(js),
    }
    return render(request, "tap_web/synthetic_page.html", context)


# ---------------------------------------------------------------------------
# Subgraph loading
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent / "data"
_subgraph_cache: dict[str, dict[str, Any]] = {}


def load_subgraph(name: str) -> dict[str, Any]:
    """Load a GRIFT subgraph JSON file from tap_web/data/.

    Args:
        name: Filename without extension, e.g. "entity-viewer".

    Returns:
        Parsed GRIFT subgraph dict.

    Raises:
        FileNotFoundError: If the data file does not exist.
    """
    if name in _subgraph_cache:
        return _subgraph_cache[name]

    path = _DATA_DIR / f"{name}.grift.json"
    with open(path) as f:
        data = json.load(f)
    _subgraph_cache[name] = data
    return data
