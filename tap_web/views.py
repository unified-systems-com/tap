"""TAP Web views."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from tap_auth.capabilities import READ_CAPABILITY
from tap_auth.errors import AuthzError
from tap_grid.caller_context import require_caller_context
from tap_web.models import Page
from tap_web.navigation import build_breadcrumb
from tap_web.page import build_url_id, get_landing_page, get_page_by_slug, get_page_panels, parse_panel_url_id

logger = logging.getLogger(__name__)


def _authorize_grid_read(operation: str) -> None:
    """Authorize grid.read for the active request actor (req-tap-auth-policy).

    The primary, per-route gate for tap_web read entrypoints: it raises AuthzError
    (→ 403 via CallerContextMiddleware) for an actor lacking grid.read, before any
    Page/Panel/Edge row is resolved, so existence is not leaked. The ORM read
    backstop (req-tap-auth-orm-read-backstop) sits beneath as defense-in-depth for
    any read site this gate misses; this call turns that backstop's 500-class
    `unguarded_operation` into a clean, intended 403.
    """
    from tap_auth import policy
    from tap_grid.caller_context import get_caller_context

    policy.authorize(get_caller_context(), READ_CAPABILITY, operation=operation)


# ---------------------------------------------------------------------------
# Page views
# ---------------------------------------------------------------------------


def landing_view(request: HttpRequest) -> HttpResponse:
    """Serve the root URL by redirecting to the configured LandingPage's slug.

    Redirect (not in-place render) so there is exactly one canonical URL per
    conceptual page. Otherwise `/` and the target slug both serve the same
    content with different breadcrumbs ("TAP" vs "TAP > <Name>"), since the
    breadcrumb builder keys off the request path, not the rendered Page.
    """
    _authorize_grid_read("landing_view")
    page = get_landing_page()
    if page is None:
        return _render_grid_placeholder(request)
    return redirect(page.slug)


def page_view(request: HttpRequest, page_slug: str) -> HttpResponse:
    """Render a Page by its slug."""
    _authorize_grid_read("page_view")
    slug = f"/{page_slug}"
    page = get_page_by_slug(slug)
    if page is None:
        raise Http404(f"Page '{slug}' not found.")
    return _render_page(request, page)


def parameterized_page_view(
    request: HttpRequest,
    page_slug: str,
    **kwargs: Any,
) -> HttpResponse:
    """Render a Page by slug with URL path segments injected as search inputs.

    Captures like ``entity_id`` from URL patterns are merged into query
    parameters so panel seed searches receive them as ``$entity_id`` inputs.
    """
    _authorize_grid_read("parameterized_page_view")
    slug = f"/{page_slug}"
    page = get_page_by_slug(slug)
    if page is None:
        raise Http404(f"Page '{slug}' not found.")
    extra = {k: str(v) for k, v in kwargs.items()}
    return _render_page(request, page, extra_query_params=extra)


# ---------------------------------------------------------------------------
# Panel views
# ---------------------------------------------------------------------------


def panel_view(request: HttpRequest, panel_url_id: str) -> HttpResponse:
    """Render a Panel fragment for HTMX consumption.

    URL format: /panel/<slug>--<entity-uuid>/
    On any exception returns an error fragment so the HTMX swap completes.
    """
    from tap_web.models import Panel

    # Primary grid.read gate (finding cs-tap-web-panel-001): authorize before any
    # Panel/entity resolution so a capability-less caller cannot read panel content
    # or point a ViewerPanel at an arbitrary entity via query string. AuthzError is
    # re-raised below (not swallowed into a 200 fragment) → 403.
    _authorize_grid_read("panel_view")

    entity_uuid = parse_panel_url_id(panel_url_id)
    if entity_uuid is None:
        return _panel_error(request, f"Invalid panel URL: '{panel_url_id}'")

    try:
        panel = Panel.objects.select_related("entity").get(entity__pk=entity_uuid)
    except Panel.DoesNotExist:
        return _panel_error(request, f"Panel '{entity_uuid}' not found.")

    try:
        panel_type = _get_panel_type_for_panel(panel)

        # POST dispatch: if the panel type defines handle_post, route POST there.
        if request.method == "POST" and panel_type and hasattr(panel_type, "handle_post"):
            return panel_type.handle_post(panel, request)

        extra_ctx: dict = {}
        if panel_type and hasattr(panel_type, "get_view_context"):
            extra_ctx = panel_type.get_view_context(panel, request) or {}
        return render(
            request,
            panel.view,
            {
                "panel": panel,
                "edit_url": reverse("panel-edit", kwargs={"panel_url_id": panel_url_id}),
                **extra_ctx,
            },
        )
    except AuthzError:
        # An authorization denial must NOT be swallowed into a 200 error fragment
        # (that would hide a real access denial as "panel render failed"). Let it
        # propagate to CallerContextMiddleware.process_exception → 403.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[1899] Error rendering panel %s (view=%s)", entity_uuid, panel.view)
        return _panel_error(request, str(exc))


@require_http_methods(["GET", "POST"])
def panel_edit_view(request: HttpRequest, panel_url_id: str) -> HttpResponse:
    """Editor for a Panel object — routes through the generic editor shell.

    URL format: /panel/<slug>--<entity-uuid>/edit/
    Dispatches to the panel's registered PanelType for typed form handling.
    Falls back to raw JSON config editing when no PanelType is registered.
    """
    from tap_web.models import Panel

    # Primary grid.read gate (same finding class as panel_view / object_edit_view):
    # authorize before resolving the Panel so a capability-less caller gets a clean
    # 403 rather than tripping the ORM read backstop deep in rendering. handle_save
    # additionally re-gates grid.write/grid.delete on the POST path.
    _authorize_grid_read("panel_edit_view")

    entity_uuid = parse_panel_url_id(panel_url_id)
    if entity_uuid is None:
        return _panel_error(request, f"Invalid panel URL: '{panel_url_id}'")

    try:
        panel = Panel.objects.select_related("entity").get(entity__pk=entity_uuid)
    except Panel.DoesNotExist:
        return _panel_error(request, f"Panel '{entity_uuid}' not found.")

    panel_type = _get_panel_type_for_panel(panel)
    form_class = getattr(panel_type, "form_class", None) if panel_type else None
    editor_template = getattr(panel_type, "editor_view", "") if panel_type else ""

    if request.method == "POST":
        if form_class is not None:
            form = form_class(request.POST)
            if form.is_valid():
                if panel_type and hasattr(panel_type, "handle_save"):
                    panel_type.handle_save(form, panel, request)
                else:
                    from tap_grid.services import patch_node

                    patch_node(
                        target=panel.entity.pk,
                        payload=_form_to_patch_payload(form, panel),
                        caller_context=require_caller_context(),
                    )
                return redirect("panel-edit", panel_url_id=panel_url_id)
            return render(
                request,
                "tap_web/editor.html",
                _panel_editor_context(panel_url_id, panel, form=form, editor_template=editor_template),
            )
        # Generic fallback — no registered PanelType; raw JSON config editing.
        payload: dict[str, Any] = {
            "name": request.POST.get("name", panel.name),
            "description": request.POST.get("description", panel.description),
        }
        raw_config = request.POST.get("config", "")
        if raw_config:
            try:
                payload["config"] = json.loads(raw_config)
            except json.JSONDecodeError as exc:
                return render(
                    request,
                    "tap_web/editor.html",
                    _panel_editor_context(panel_url_id, panel, config_error=str(exc)),
                )
        from tap_grid.services import patch_node

        patch_node(
            target=panel.entity.pk,
            payload=payload,
            caller_context=require_caller_context(),
        )
        return redirect("panel-edit", panel_url_id=panel_url_id)

    # GET
    form = None
    if form_class is not None:
        if panel_type and hasattr(panel_type, "get_editor_initial"):
            initial = panel_type.get_editor_initial(panel)
        else:
            initial = {"name": panel.name, "description": panel.description, **panel.config}
        form = form_class(initial=initial)

    return render(
        request,
        "tap_web/editor.html",
        _panel_editor_context(panel_url_id, panel, form=form, editor_template=editor_template),
    )


# ---------------------------------------------------------------------------
# Generic object editor + viewer
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
def object_edit_view(request: HttpRequest, entity_type: str, object_url_id: str) -> HttpResponse:
    """Generic editor for any registered TAP entity type.

    URL format: /object/<entity-type>/<slug>--<entity-uuid>/edit/
    GET renders via the synthetic page builder using the entity-editor GRIFT
    subgraph. POST is handled by the EditorPanelType via the panel endpoint
    when using persisted pages; for synthetic pages, POST falls back to the
    legacy editor path since synthetic panels are rendered inline.
    """
    from tap_auth import policy
    from tap_grid.caller_context import get_caller_context
    from tap_grid.registry import get_model_class

    # Gate the direct graph read below (req-tap-auth-service-boundary): authorize
    # before resolving the object so existence is not leaked to an unauthorized
    # caller. AuthzError is translated to 403 by CallerContextMiddleware.
    policy.authorize(get_caller_context(), READ_CAPABILITY, operation="object_edit_view")

    entity_uuid = parse_panel_url_id(object_url_id)
    if entity_uuid is None:
        raise Http404(f"Invalid object URL: '{object_url_id}'")

    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        raise Http404(f"Unknown entity type '{entity_type}'.") from None

    try:
        obj = model_cls.objects.select_related("entity").get(entity__pk=entity_uuid)
    except model_cls.DoesNotExist:
        raise Http404(f"{entity_type} '{entity_uuid}' not found.") from None

    # POST: handle form submission directly (synthetic panels render inline,
    # so the editor panel's HTMX post targets the object edit URL).
    if request.method == "POST":
        return _handle_object_edit_post(request, obj, entity_type, object_url_id)

    # GET: render via synthetic page builder.
    from tap_web.synthetic import load_subgraph, render_synthetic_page

    subgraph = load_subgraph("entity-editor")
    return render_synthetic_page(
        request,
        subgraph,
        extra_query_params={
            "entity_id": str(entity_uuid),
            "entity_type": entity_type,
            "subject_entity_id": str(entity_uuid),
        },
    )


def object_view(request: HttpRequest, entity_type: str, object_url_id: str) -> HttpResponse:
    """Generic viewer for any registered TAP entity type.

    URL format: /object/<entity-type>/<slug>--<entity-uuid>/
    Renders via the synthetic page builder using the entity-viewer GRIFT
    subgraph in tap_web/data/.
    """
    from tap_auth import policy
    from tap_grid.caller_context import get_caller_context
    from tap_grid.registry import get_model_class

    # Authorize before the direct graph read below (no existence leak); AuthzError
    # → 403 via CallerContextMiddleware (req-tap-auth-service-boundary).
    policy.authorize(get_caller_context(), READ_CAPABILITY, operation="object_view")

    entity_uuid = parse_panel_url_id(object_url_id)
    if entity_uuid is None:
        raise Http404(f"Invalid object URL: '{object_url_id}'")

    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        raise Http404(f"Unknown entity type '{entity_type}'.") from None

    try:
        model_cls.objects.select_related("entity").get(entity__pk=entity_uuid)
    except model_cls.DoesNotExist:
        raise Http404(f"{entity_type} '{entity_uuid}' not found.") from None

    from tap_web.synthetic import load_subgraph, render_synthetic_page

    subgraph = load_subgraph("entity-viewer")
    return render_synthetic_page(
        request,
        subgraph,
        extra_query_params={
            "entity_id": str(entity_uuid),
            "entity_type": entity_type,
            "subject_entity_id": str(entity_uuid),
        },
    )


def _handle_object_edit_post(
    request: HttpRequest,
    obj: Any,
    entity_type: str,
    object_url_id: str,
) -> HttpResponse:
    """Handle POST for the generic object editor — validate and save via EditorDescriptor."""
    from tap_web.registry import get_editor

    descriptor = get_editor(entity_type)
    if descriptor is None:
        raise Http404(f"No editor registered for entity type '{entity_type}'.")

    form_class = descriptor.get_form_class(obj)
    if form_class is None:
        override = descriptor.get_extra_context(obj).get("edit_url_override")
        if override:
            return redirect(override)
        raise Http404(f"No form registered for entity type '{entity_type}'.")

    form = form_class(request.POST)
    if form.is_valid():
        descriptor.handle_save(form, obj, request)
        return redirect("object-edit", entity_type=entity_type, object_url_id=object_url_id)

    # Validation failed — re-render the synthetic editor page with errors.
    # The editor panel will pick up form errors from the re-rendered context.
    from tap_web.synthetic import load_subgraph, render_synthetic_page

    subgraph = load_subgraph("entity-editor")
    return render_synthetic_page(
        request,
        subgraph,
        extra_query_params={
            "entity_id": str(obj.entity_id),
            "entity_type": entity_type,
            "subject_entity_id": str(obj.entity_id),
        },
    )


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _panel_editor_context(
    panel_url_id: str,
    panel: object,
    form: object = None,
    editor_template: str = "",
    config_error: str = "",
) -> dict:
    """Build template context for the panel editor page."""
    from tap_web.models import Panel

    assert isinstance(panel, Panel)
    graph_ctx = _get_neighborhood_context(panel.entity_id)
    # Editor assets come from the panel type, not the panel instance.
    panel_type = _get_panel_type_for_panel(panel)
    editor_css: dict[str, None] = dict.fromkeys(getattr(panel_type, "editor_css", []) or [])
    editor_js: dict[str, None] = dict.fromkeys(getattr(panel_type, "editor_js", []) or [])
    view_url = reverse(
        "object-view", kwargs={"entity_type": "panel", "object_url_id": build_url_id(panel.slug, panel.entity_id)}
    )
    return {
        "obj": panel,
        "obj_name": panel.name or panel.slug,
        "entity_type": "panel",
        "object_url_id": panel_url_id,
        "form": form,
        "editor_template": editor_template,
        "editor_css_assets": list(editor_css),
        "editor_js_assets": list(editor_js),
        "config_json": json.dumps(panel.config or {}, indent=2),
        "config_error": config_error,
        "view_url": view_url,
        **graph_ctx,
    }


def _object_editor_context(
    entity_type: str,
    object_url_id: str,
    obj: object,
    form: object,
    *,
    editor_template: str = "",
    view_url: str = "",
    extra: dict | None = None,
) -> dict:
    """Build template context for the generic object editor page."""
    graph_ctx = _get_neighborhood_context(obj.entity_id)
    return {
        "obj": obj,
        "obj_name": str(obj),
        "entity_type": entity_type,
        "object_url_id": object_url_id,
        "form": form,
        "editor_template": editor_template,
        "editor_css_assets": [],
        "editor_js_assets": [],
        "config_json": None,
        "config_error": "",
        "view_url": view_url,
        **(extra or {}),
        **graph_ctx,
    }


# ---------------------------------------------------------------------------
# Graph context helper (replaces neighborhood.py)
# ---------------------------------------------------------------------------


def _get_neighborhood_context(entity_id: object) -> dict[str, Any]:
    """Return Cytoscape graph context for the panel/object editor templates.

    Executes a transient gryphon hub-and-spoke search using the same Search
    definition as the synthetic entity page subgraph.
    """
    from tap_grid.models import Search
    from tap_grid.search import execute_search
    from tap_web.utils import safe_json

    search = Search(
        search_type="gryphon",
        root="node",
        name="hub-and-spoke",
        definition={
            "query": [
                "MATCH (hub)-[e]-(neighbor)",
                "WHERE hub.entity_id = $entity_id",
                "RETURN hub, e, neighbor",
            ]
        },
        default_limit=200,
        max_limit=500,
    )
    try:
        result = execute_search(search, inputs={"entity_id": str(entity_id)}, layer="extended")
        envelope = result.get("results", result)
        nodes_raw = envelope.get("nodes", [])
        edges_raw = envelope.get("edges", [])
    except AuthzError:
        # An authorization denial must surface as a 403/no-access (translated by
        # CallerContextMiddleware), not be swallowed into a graph-data error.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[f200] hub-and-spoke search failed for entity %s", entity_id)
        return {
            "graph_nodes_json": safe_json([]),
            "graph_edges_json": safe_json([]),
            "graph_placement": "cytoscape:cose",
            "graph_error": f"Graph context failed: {exc}",
            "graph_context_id": str(entity_id),
        }

    return {
        "graph_nodes_json": safe_json(nodes_raw),
        "graph_edges_json": safe_json(edges_raw),
        "graph_placement": "cytoscape:cose",
        "graph_error": None,
        "graph_context_id": str(entity_id),
    }


# ---------------------------------------------------------------------------
# Standard panel helpers
# ---------------------------------------------------------------------------

_STANDARD_PANEL_FIELDS = frozenset({"name", "description"})


def _form_to_patch_payload(form: object, panel: object) -> dict[str, Any]:
    """Return a patch payload dict from validated form cleaned_data for use with patch_node()."""
    from django.forms import BaseForm

    from tap_web.models import Panel

    assert isinstance(form, BaseForm)
    assert isinstance(panel, Panel)
    cleaned = form.cleaned_data
    payload: dict[str, Any] = {"name": cleaned["name"]}
    if "description" in cleaned:
        payload["description"] = cleaned["description"]
    config_updates = {k: v for k, v in cleaned.items() if k not in _STANDARD_PANEL_FIELDS}
    if config_updates:
        payload["config"] = config_updates
    return payload


def _get_panel_type_for_panel(panel: object) -> type | None:
    """Return the registered PanelType whose view matches panel.view, or None."""
    from tap_web.registry import panel_type_registry

    panel_view = getattr(panel, "view", None)
    for scope_data in panel_type_registry.all().values():
        for panel_type_cls in scope_data.values():
            if getattr(panel_type_cls, "view", None) == panel_view:
                return panel_type_cls
    return None


# ---------------------------------------------------------------------------
# Internal page rendering helpers
# ---------------------------------------------------------------------------


def _render_page(
    request: HttpRequest,
    page: object,
    extra_query_params: dict[str, str] | None = None,
) -> HttpResponse:
    """Render a Page using the page template."""
    panel_slots = get_page_panels(page)  # type: ignore[arg-type]

    panels_by_id: dict[str, str] = {}
    for panel_id, panel in panel_slots:
        panels_by_id[panel_id] = build_url_id(panel.slug, panel.entity_id)

    # Static assets come exclusively from the panel type. Panel instances do
    # not declare assets — a panel is identified by its `view` and the type
    # owns all css/js the panel needs to render.
    css: dict[str, None] = {}
    js: dict[str, None] = {}
    for _panel_id, panel in panel_slots:
        panel_type = _get_panel_type_for_panel(panel)
        for asset_path in getattr(panel_type, "css", []):
            css[asset_path] = None
        for asset_path in getattr(panel_type, "js", []):
            js[asset_path] = None

    layout = getattr(page, "layout", {}) or {}
    processed_columns = _process_layout(layout, panels_by_id)

    query_params = request.GET.copy()
    if extra_query_params:
        query_params.update(extra_query_params)

    context = {
        "page": page,
        "processed_columns": processed_columns,
        "css_assets": list(css),
        "js_assets": list(js),
        "query_params": query_params,
        # Declarative per-page opt-in (layout.full_bleed): drop the centered
        # max-width container so the page fills the viewport width. base.html
        # honors this; non-page views leave it unset and stay centered.
        "full_bleed": bool(layout.get("full_bleed", False)),
    }
    return render(request, "tap_web/page.html", context)


_NUMERIC_PREFIX_RE = re.compile(r"^[a-z]+-(\d+)")


def _extract_numeric_key(key: str) -> int:
    m = _NUMERIC_PREFIX_RE.match(key)
    return int(m.group(1)) if m else 0


def _process_layout(layout: dict, panels_by_id: dict[str, str]) -> list[dict]:
    """Convert raw layout JSON into a sorted structure the template can iterate."""
    columns_raw = layout.get("columns", {})
    columns = sorted(columns_raw.items(), key=lambda kv: _extract_numeric_key(kv[0]))

    processed: list[dict] = []
    for col_key, col_data in columns:
        rows_raw = col_data.get("rows", {})
        rows = sorted(rows_raw.items(), key=lambda kv: _extract_numeric_key(kv[0]))

        processed_rows: list[dict] = []
        for row_key, row_data in rows:
            panel_id = row_data.get("panel-id", "")
            processed_rows.append(
                {
                    "key": row_key,
                    "panel_id": panel_id,
                    "panel_url_id": panels_by_id.get(panel_id),
                    "row_span": row_data.get("row_span", 1),
                    "col_span": row_data.get("col_span", 1),
                    "height": row_data.get("height", "auto"),
                }
            )

        processed.append(
            {
                "key": col_key,
                "width": col_data.get("width", "1fr"),
                "rows": processed_rows,
            }
        )

    return processed


def _panel_error(request: HttpRequest, message: str) -> HttpResponse:
    return render(request, "tap_web/panel_error.html", {"message": message})


def _render_grid_placeholder(request: HttpRequest) -> HttpResponse:
    """Render a live all-nodes + all-edges view when no LandingPage is configured."""
    from tap_grid.models import Search
    from tap_grid.search import execute_search
    from tap_web.panels.table_panel import _safe_int
    from tap_web.utils import safe_json

    node_limit = _safe_int(request.GET.get("limit"), 100)
    node_offset = _safe_int(request.GET.get("offset"), 0)
    edge_limit = _safe_int(request.GET.get("edge_limit"), 100)
    edge_offset = _safe_int(request.GET.get("edge_offset"), 0)

    node_search = Search(
        search_type="orm",
        root="node",
        definition={"filters": {}, "order_by": ["name"]},
        default_limit=100,
        max_limit=500,
    )
    edge_search = Search(
        search_type="orm",
        root="edge",
        definition={"filters": {}, "order_by": ["edge_type"]},
        default_limit=100,
        max_limit=500,
    )

    _empty_ctx: dict[str, Any] = {
        "nodes_json": safe_json([]),
        "meta": {},
        "edges_json": safe_json([]),
        "edges_meta": {},
        "table_error": None,
    }

    try:
        node_result = execute_search(node_search, limit=node_limit, offset=node_offset, layer="extended")
        edge_result = execute_search(edge_search, limit=edge_limit, offset=edge_offset, layer="extended")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[5c03] Grid placeholder search failed")
        return render(
            request,
            "tap_web/setup_placeholder.html",
            {**_empty_ctx, "table_error": str(exc)},
        )

    # --- Nodes ---
    if "results" in node_result:
        nodes: list[dict[str, Any]] = node_result["results"].get("nodes", [])
        n_lim: int = node_result["limit"]
        n_off: int = node_result["offset"]
        n_count: int = node_result["count"]
        meta: dict[str, Any] = {
            "count": n_count,
            "limit": n_lim,
            "offset": n_off,
            "has_prev": n_off > 0,
            "has_next": n_off + n_lim < n_count,
            "prev_offset": max(0, n_off - n_lim),
            "next_offset": n_off + n_lim,
            "display_end": min(n_off + n_lim, n_count),
        }
    else:
        nodes = node_result.get("nodes", [])
        meta = {}

    # --- Edges ---
    if "results" in edge_result:
        edges: list[dict[str, Any]] = edge_result["results"].get("edges", [])
        e_lim: int = edge_result["limit"]
        e_off: int = edge_result["offset"]
        e_count: int = edge_result["results"]["info"].get("total_count", len(edges))
        edges_meta: dict[str, Any] = {
            "count": e_count,
            "limit": e_lim,
            "offset": e_off,
            "has_prev": e_off > 0,
            "has_next": e_off + e_lim < e_count,
            "prev_offset": max(0, e_off - e_lim),
            "next_offset": e_off + e_lim,
            "display_end": min(e_off + e_lim, e_count),
        }
    else:
        edges = edge_result.get("edges", [])
        edges_meta = {}

    return render(
        request,
        "tap_web/setup_placeholder.html",
        {
            "nodes_json": safe_json(nodes),
            "meta": meta,
            "edges_json": safe_json(edges),
            "edges_meta": edges_meta,
            "table_error": None,
        },
    )


# ---------------------------------------------------------------------------
# Navigation index
# ---------------------------------------------------------------------------


def nav_index_view(request: HttpRequest) -> JsonResponse:
    """Return the machine-readable nav index per req-web-nav-index-endpoint.

    Enumerates every registered Page with its canonical breadcrumb path so
    AI agents, automation, and tooling can reason about the platform's
    navigation surface without scraping HTML.

    Schema is documented in spec-web-navigation §Machine-Readable Nav Index.
    Computed on request (no caching) for v0 per `req-web-nav-index-endpoint`.

    Requires grid.read (finding cs-tap-web-page-002): the index is graph-backed
    (Page rows: names, descriptions, slugs, panel URL ids) and so is a graph read
    like any other. It already sits behind the login wall (not in
    TAP_LOGIN_EXEMPT_PREFIXES), so this only additionally requires the authenticated
    actor to hold grid.read — closing the metadata-enumeration leak to no-cap users.
    To restore a deliberately public nav index, wrap the read in
    `tap_grid.read_guard.unguarded_read()` instead of authorizing here.
    """
    _authorize_grid_read("nav_index_view")

    # Filter `discoverable=True` per req-web-nav-page-discoverable — parameterized
    # pages (e.g. /samsite/finding/<entity_id>) opt out of discovery surfaces
    # because clicking them without a parameter produces a broken render. They
    # still resolve on direct visit; only browse-style discovery is gated.
    #
    # Sort by (-nav_weight, slug) per req-web-nav-page-weight — higher weight
    # floats up; ties resolve alphabetically by slug. Consumers (palette tree,
    # chevron popovers, column view) read the index in document order and
    # therefore inherit the same sort without re-sorting client-side.
    pages_qs = Page.objects.filter(discoverable=True).order_by("-nav_weight", "slug")
    entries: list[dict[str, Any]] = []
    for page in pages_qs:
        breadcrumb = build_breadcrumb(page.slug)
        entries.append(
            {
                "url": page.slug,
                "name": page.name,
                "description": page.description or "",
                "nav_weight": page.nav_weight,
                "breadcrumb": [{"label": seg.label, "url": seg.url} for seg in breadcrumb],
            }
        )
    return JsonResponse(
        {
            "version": "0",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "pages": entries,
        },
        json_dumps_params={"indent": 2},
    )
