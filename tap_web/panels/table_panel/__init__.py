"""Table Panel — built-in panel type for search-backed tabular display.

Stores all behavior options in the standard Panel.config JSONField,
validated against TABLE_CONFIG_SCHEMA on every save.

Search binding:
  Panel links to a Search via a USES_SEARCH edge (Panel -> Search).
  The linked Search is executed through the shared search service layer;
  no ORM or module search logic lives in this panel.

Rendering:
  Server-side: the linked Search executes during panel fragment rendering.
  Client-side: Tabulator 6.3 initializes from an embedded JSON payload.

Pagination:
  Server-backed. Limit/offset are passed as query params on the HTMX
  panel endpoint; Tabulator local pagination is not used.

Config schema:
  See req-web-stdpanel-table-config in spec-web-panels-standard-table.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import jsonschema  # type: ignore[import-untyped]
from django import forms
from django.core.exceptions import ValidationError

from tap_web.panel import TABULATOR_CSS, TABULATOR_JS
from tap_web.utils import safe_json

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_grid.models import Search
    from tap_web.models import Panel

logger = logging.getLogger(__name__)

# JSON Schema for Panel.config on Table Panel instances.
# additionalProperties: false enforces no undeclared keys.
TABLE_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "column_mode": {
            "type": "string",
            "enum": ["common_metadata"],
        },
        "default_page_size": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
        },
        # When true, render a quick-filter search box top-right of the table that
        # live-filters the loaded rows client-side (matches across all columns).
        # Note: filters the current page's rows only — pair with a page size that
        # loads the full set when whole-table filtering is intended.
        "quick_filter": {
            "type": "boolean",
        },
        # Optional custom column specs — overrides column_mode in the JS.
        # Each spec maps to a Tabulator column; `formatter` selects one of the
        # JS preset formatters (panel-table.js) so column logic is declarable.
        "columns": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "title"],
                "properties": {
                    "field": {"type": "string", "minLength": 1},
                    "title": {"type": "string"},
                    "width": {"type": "integer", "minimum": 20, "maximum": 800},
                    "widthGrow": {"type": "integer", "minimum": 1, "maximum": 5},
                    "formatter": {
                        "type": "string",
                        "enum": [
                            "plaintext",
                            "datetime",
                            "tickCross",
                            "tickDash",
                            "ciaLevel",
                            "ellipsisSuffix",
                            "json",
                            "passFailBadge",
                            "painBadge",
                            "arrayCount",
                        ],
                    },
                    "tooltip": {"type": "string", "enum": ["full_value"]},
                    "headerSort": {"type": "boolean"},
                },
            },
        },
        # Optional declarative row grouping. The JS classifies each row into a
        # section by matching a field value against ordered {prefix, label}
        # rules; non-matches fall into default_label. Section order follows rule
        # order. Keeps the section taxonomy in the consumer's config, not in JS.
        "group_by": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "rules"],
            "properties": {
                "field": {"type": "string", "minLength": 1},
                "rules": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["prefix", "label"],
                        "properties": {
                            "prefix": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "default_label": {"type": "string", "minLength": 1},
            },
        },
    },
}

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_COLUMN_MODE = "common_metadata"

# Fixed breakpoints for page-size selector; "All" is appended dynamically.
_PAGE_SIZE_STEPS = [25, 50, 100, 200, 500]


def _validate_table_config(config: dict[str, Any]) -> None:
    """Validate a Table Panel config dict against TABLE_CONFIG_SCHEMA.

    Raises:
        ValidationError: if the config fails schema validation.
    """
    try:
        jsonschema.validate(instance=config, schema=TABLE_CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError({"config": [exc.message]}) from exc


class TablePanelEditForm(forms.Form):
    """Edit form for Table Panel fields.

    Dynamically populates the search_uuid choices from available Search objects
    so the editor shows a human-readable dropdown rather than a raw UUID input.
    Server-side validation enforces required constraints independently of
    any browser-side checks.
    """

    name = forms.CharField(max_length=255, strip=True)
    description = forms.CharField(required=False, strip=True, widget=forms.Textarea)
    search_uuid = forms.ChoiceField(required=False, label="Linked Search")
    column_mode = forms.ChoiceField(
        choices=[("common_metadata", "Common Metadata")],
        initial=_DEFAULT_COLUMN_MODE,
        label="Column Mode",
    )
    default_page_size = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        initial=_DEFAULT_PAGE_SIZE,
        label="Default Rows Per Page",
        help_text="Initial page size before user selects a different value.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Populate search choices at form instantiation so they reflect current DB state.
        from tap_grid.models import Search

        choices = [("", "— No search linked —")]
        for s in Search.objects.select_related("entity").order_by("name"):
            choices.append((str(s.entity_id), s.name or str(s.entity_id)))
        self.fields["search_uuid"].choices = choices  # type: ignore[attr-defined]


class TablePanelType:
    """Built-in table panel type descriptor.

    Implements the three optional PanelType hooks used by panel_view and
    panel_edit_view:
      - get_view_context(panel, request) -> dict
      - get_editor_initial(panel) -> dict
      - handle_save(form, panel, request) -> None
    """

    slug = "table"
    label = "Table Panel"
    view = "tap_web/panels/table_panel.html"
    editor_view = "tap_web/panels/table_panel_editor.html"
    css: list[str] = [*TABULATOR_CSS]
    js: list[str] = [*TABULATOR_JS]
    config_defaults: dict[str, Any] = {
        "column_mode": _DEFAULT_COLUMN_MODE,
        "default_page_size": _DEFAULT_PAGE_SIZE,
    }
    form_class = TablePanelEditForm

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Execute the linked Search and return results for template context.

        Returns a context dict with:
          table_nodes        - list of node dicts from the search envelope
          table_meta         - pagination / footer metadata dict
          table_search       - the linked Search instance, or None
          table_nodes_json   - JSON-encoded nodes string for safe embedding
          table_error        - error string, or None on success
        """
        from tap_web.panel import get_panel_search

        search = get_panel_search(panel)
        if search is None:
            return {
                "table_nodes": [],
                "table_meta": {},
                "table_search": None,
                "table_nodes_json": safe_json([]),
                "table_error": "No search linked to this panel.",
            }

        config = panel.config or {}
        default_ps = config.get("default_page_size", _DEFAULT_PAGE_SIZE)

        # page_size=0 means "show all" (passed by the JS selector).
        raw_ps = request.GET.get("page_size")
        if raw_ps is not None and raw_ps == "0":
            page_size = 0  # sentinel: no limit
        else:
            page_size = _safe_int(raw_ps, default_ps)

        offset = _safe_int(request.GET.get("offset"), 0)
        effective_limit = page_size if page_size > 0 else None

        try:
            from tap_grid.search import execute_search

            result = execute_search(search, limit=effective_limit, offset=offset, layer="extended")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[87dd] Table panel search execution failed for panel %s", panel.entity_id)
            return {
                "table_nodes": [],
                "table_meta": {},
                "table_search": search,
                "table_nodes_json": safe_json([]),
                "table_error": f"Search execution failed: {exc}",
            }

        # Extract nodes and total count from paginated or unpaginated envelope.
        if "results" in result:
            nodes: list[dict[str, Any]] = result["results"].get("nodes", [])
            total_count: int = result["results"].get("info", {}).get("total_count", result["count"])
        else:
            nodes = result.get("nodes", [])
            total_count = result.get("info", {}).get("total_count", len(nodes))

        showing = len(nodes)
        page_size_options = _build_page_size_options(total_count, page_size)

        meta: dict[str, Any] = {
            "total_count": total_count,
            "showing": showing,
            "page_size": page_size,
            "page_size_options": page_size_options,
            "has_prev": offset > 0,
            "has_next": effective_limit is not None and (offset + effective_limit) < total_count,
            "prev_offset": max(0, offset - (effective_limit or 0)),
            "next_offset": offset + (effective_limit or 0),
        }

        custom_columns = config.get("columns")
        group_by = config.get("group_by")
        return {
            "table_nodes": nodes,
            "table_meta": meta,
            "table_search": search,
            "table_nodes_json": safe_json(nodes),
            "table_columns_json": safe_json(custom_columns) if custom_columns else "",
            "table_group_by_json": safe_json(group_by) if group_by else "",
            "table_error": None,
        }

    @classmethod
    def get_editor_initial(cls, panel: Panel) -> dict[str, Any]:
        """Return the initial dict for TablePanelEditForm.

        Includes the currently linked search UUID so the editor dropdown
        pre-selects the right Search.
        """
        from tap_web.panel import get_panel_search

        search: Search | None = get_panel_search(panel)
        config = panel.config or {}
        return {
            "name": panel.name,
            "description": panel.description,
            "search_uuid": str(search.entity_id) if search else "",
            "column_mode": config.get("column_mode", _DEFAULT_COLUMN_MODE),
            "default_page_size": config.get("default_page_size", _DEFAULT_PAGE_SIZE),
        }

    @classmethod
    def handle_save(cls, form: TablePanelEditForm, panel: Panel, request: HttpRequest) -> None:
        """Persist panel fields, validate config, and rebind the USES_SEARCH edge.

        The whole edit is one atomic, named batch (the grift-importer idiom):
          1. Build and validate the config dict against TABLE_CONFIG_SCHEMA.
          2. Assemble the write as a single ``WriteOperation`` list — patch the
             panel node (name/description/config) + delete the existing
             USES_SEARCH edge(s) + create the new binding.
          3. ``create_batch`` opens a *named* batch ("Edit table panel: …") so the
             provenance trail records the intent, not three anonymous batches.
          4. ``write_batch`` applies every op in one transaction — a mid-edit
             failure rolls the whole thing back (no half-rebound edge).

        Authorization is the primary gate (``AuthzError`` → 403): ``authorized``
        checks ``grid.write`` and opens the service-write scope; ``grid.delete`` is
        additionally required when there are edges to remove. A direct
        ``.save()`` / ``Edge.objects`` write would bypass both the gate and the
        batch — the write backstop makes that fail closed.

        Raises:
            ValidationError: if the config fails schema validation or the batch fails.
        """
        from tap_auth import policy
        from tap_auth.capabilities import DELETE_CAPABILITY, WRITE_CAPABILITY
        from tap_auth.enforcement import authorized
        from tap_grid.batch import close_batch, create_batch, fail_batch
        from tap_grid.caller_context import CallerContext, get_caller_context
        from tap_grid.exceptions import ServiceNotFoundError, ServiceValidationError
        from tap_grid.models import Edge
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import resolve_entity, write_batch

        cleaned = form.cleaned_data

        new_config: dict[str, Any] = {
            **(panel.config or {}),  # preserve grift-seeded extras (e.g. columns) the form does not edit
            "column_mode": cleaned.get("column_mode") or _DEFAULT_COLUMN_MODE,
            "default_page_size": cleaned.get("default_page_size") or _DEFAULT_PAGE_SIZE,
        }
        _validate_table_config(new_config)

        # Assemble the atomic op list. The edge rebind needs the current bindings,
        # so read them (by entity_id — delete_edge targets the edge's Entity) first.
        ops: list[WriteOperation] = [
            WriteOperation(
                verb="patch_node",
                target=str(panel.entity.pk),
                payload={
                    "name": cleaned["name"],
                    "description": cleaned.get("description", ""),
                    "config": new_config,
                },
            )
        ]
        existing_edge_ids = list(
            Edge.objects.filter(from_entity=panel.entity, edge_type="USES_SEARCH").values_list("entity_id", flat=True)
        )
        ops += [WriteOperation(verb="delete_edge", target=str(eid)) for eid in existing_edge_ids]

        search_uuid_str: str = cleaned.get("search_uuid") or ""
        if search_uuid_str:
            try:
                search_entity = resolve_entity(search_uuid_str)
            except ServiceNotFoundError, ServiceValidationError:
                logger.warning(
                    "[6d10] Table panel editor: search entity %s not found; USES_SEARCH edge not created.",
                    search_uuid_str,
                )
            else:
                ops.append(
                    WriteOperation(
                        verb="create_edge",
                        from_target=str(panel.entity.id),
                        to_target=str(search_entity.id),
                        edge_type="USES_SEARCH",
                    )
                )

        ctx = get_caller_context()
        actor = ctx.user if ctx else None

        # One atomic, named batch. authorized() is the primary 403 gate and opens
        # the service-write scope so create_batch's rows + the pipeline pass the
        # write backstop; grid.delete is gated too when edges are being removed.
        with authorized(ctx, WRITE_CAPABILITY, operation="table_panel.handle_save"):
            if existing_edge_ids:
                policy.authorize(ctx, DELETE_CAPABILITY, operation="table_panel.handle_save")
            batch = create_batch(
                name=f"Edit table panel: {cleaned['name']}",
                description="Table panel editor: update fields and rebind USES_SEARCH.",
                source="tap_web:table_panel_editor",
                actor=actor,
            )
            result = write_batch(ops, caller_context=CallerContext(user=actor, batch_id=str(batch.entity_id)))
            if not result.success:
                fail_batch(batch, "; ".join(f"{e.code}: {e.message}" for e in result.errors) or "batch failed")
                raise ValidationError("Failed to save table panel; changes were rolled back.")
            close_batch(batch)


def _build_page_size_options(total_count: int, current_page_size: int) -> list[dict[str, Any]]:
    """Build dynamic page-size selector options based on total row count.

    Only includes step values that are less than total_count.
    Always appends an "All" option (value=0) representing the full set.
    """
    options: list[dict[str, Any]] = []
    for step in _PAGE_SIZE_STEPS:
        if step < total_count:
            options.append({"value": step, "label": str(step), "selected": current_page_size == step})

    # "All" option — selected when page_size is 0 or >= total_count.
    all_selected = current_page_size == 0 or current_page_size >= total_count
    options.append({"value": 0, "label": f"All ({total_count})", "selected": all_selected})

    # If current_page_size doesn't match any option, mark the closest as selected
    # (this handles the initial load when localStorage hasn't been set yet).
    if not any(o["selected"] for o in options) and options:
        options[0]["selected"] = True

    return options


def _safe_int(value: Any, default: int) -> int:
    """Return int(value) if convertible and non-negative, otherwise default."""
    try:
        result = int(value)
        return result if result >= 0 else default
    except TypeError, ValueError:
        return default
