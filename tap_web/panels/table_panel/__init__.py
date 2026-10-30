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
from tap_web.panels.row_url import ROW_URL_TEMPLATE_PATTERN, fill_row_url, is_same_origin_template

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
        # The Rows selector ends with an "All (N)" entry by default. False drops
        # it, so a table that must stay paged (a long list) cannot be asked for
        # every row at once (req-web-stdpanel-table-config-29).
        "show_all_rows": {
            "description": (
                "Whether the Rows (page size) selector offers an `All` entry. Default true. False omits it: the "
                "table stays paged, and a stored or requested `All` falls back to `default_page_size`."
            ),
            "type": "boolean",
        },
        # Shown in place of Tabulator's generic "No results." when the table has no rows
        # (req-web-stdpanel-table-config-30). Plain text, escaped.
        "empty_text": {
            "description": "Plain text shown when the table has no rows, in place of the generic `No results.`.",
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
        },
        # When true, render a quick-filter search box top-right of the table that
        # live-filters the loaded rows client-side (matches across all columns).
        # Note: filters the current page's rows only — pair with a page size that
        # loads the full set when whole-table filtering is intended.
        "quick_filter": {
            "type": "boolean",
        },
        # Fixed table height in px: Tabulator owns the scroll inside it, the
        # header stays put, and the page (not the panel) decides how tall the
        # panel is. Omit for a content-height table.
        "height": {"type": "integer", "minimum": 160, "maximum": 2400},
        # Auto-refresh: re-fetch the panel fragment every N seconds, with a
        # visible countdown and a pause toggle so a reader knows the table is
        # live and can stop it. Omit for a static table.
        "refresh_seconds": {"type": "integer", "minimum": 15, "maximum": 3600},
        # How much table furniture to draw. `full` (default): the nav bars
        # ("Showing N of M", page size, prev/next) above and below, and the
        # quick filter when asked for. `minimal`: none of it — for a table that
        # is one row of facts (an identity row) rather than a list to page
        # through; the heading and the refresh status stay (tap#356).
        "chrome": {"type": "string", "enum": ["full", "minimal"]},
        # Projection mode only (a search that RETURNs aliases, tap#432): a
        # same-origin path template whose `{alias}` placeholders fill from the
        # row, each value URL-encoded; a placeholder with no value leaves the
        # row without a link. The filled URL lands in the row's `_url`, which
        # the client's raw mode turns into a row click. Ignored in node mode,
        # whose rows already navigate to the object viewer.
        # A path, never `//host` or `/\host`, and no whitespace, control
        # characters or backslashes anywhere: a browser strips tab/CR/LF and reads
        # a backslash as `/` when it parses a URL, so `/<TAB>/host` becomes `//host`.
        # `(?![\s\S])` is a true end of string (`$` also matches before a final
        # newline), in both Python's and ECMAScript's regex dialects.
        "row_url_template": {"type": "string", "minLength": 2, "pattern": ROW_URL_TEMPLATE_PATTERN},
        # Alternating row background (a stripe on every even row), from the theme's
        # `--tap-table-stripe` tokens: light and dark values, text contrast-checked.
        "striped": {
            "description": (
                "When true, every even row gets a subtle alternating background (the `--tap-table-stripe` theme "
                "tokens, readable in light and dark). Default false: uniform rows."
            ),
            "type": "boolean",
        },
        # Optional custom column specs — overrides column_mode in the JS.
        # Each spec maps to a Tabulator column; `formatter` selects one of the
        # JS preset formatters (panel-table.js) so column logic is declarable.
        # An item is either a LEAF (field + title) or a GROUP (title + columns,
        # one level deep: Tabulator's grouped header), never both.
        "columns": {
            "type": "array",
            "minItems": 1,
            "items": {"anyOf": [{"$ref": "#/$defs/column"}, {"$ref": "#/$defs/column_group"}]},
        },
        # Optional initial sort, applied when the table first renders: the first
        # item is the primary key. A column's own `sorter` decides how its values
        # compare (see the column vocabulary).
        "initial_sort": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field"],
                "properties": {
                    "field": {"type": "string", "minLength": 1},
                    "dir": {"type": "string", "enum": ["asc", "desc"]},
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
    # The column vocabulary, defined once and referenced from `columns` — a
    # leaf column, and a one-level group of leaves (a grouped header).
    "$defs": {
        "column_group": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "columns"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "columns": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/column"}},
            },
        },
        "column": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title"],
            # Exactly one way to name the value: `field` (dotted path), `field_path` (explicit segments) or
            # `field_paths` (several explicit paths joined into one cell). `joiner` only goes with `field_paths`.
            "oneOf": [{"required": ["field"]}, {"required": ["field_path"]}, {"required": ["field_paths"]}],
            "dependentRequired": {"joiner": ["field_paths"]},
            "properties": {
                "field": {"type": "string", "minLength": 1},
                # An explicit path as an ARRAY of segments, for a key that itself contains a dot:
                # ["dimensions", "dataclass.customer"] reads row.dimensions["dataclass.customer"]. Each
                # segment is one key, never split. Use `field` instead for an ordinary dotted path.
                "field_path": {
                    "description": (
                        "The value's location as an array of path segments, each one key even if it contains a "
                        "dot (['dimensions', 'dataclass.customer']). Use instead of `field`, never with it."
                    ),
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                # Several values in ONE cell: each item is a path as an array of segments (the `field_path`
                # reading, own keys only), the non-empty values are joined with `joiner`, in the order given.
                "field_paths": {
                    "description": (
                        "Several values in one cell: an array of paths, each an array of segments exactly as "
                        "`field_path` (each one key even if it contains a dot, own keys only). The non-empty "
                        "scalar values are joined with `joiner` in the order given; null, missing, blank text, "
                        "lists and objects are skipped; when nothing is left the cell shows `empty_text`. Use "
                        "instead of `field` and `field_path`, never with them."
                    ),
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                },
                "joiner": {
                    "description": "The text between the values of a `field_paths` column. Default ', '.",
                    "type": "string",
                    "maxLength": 20,
                },
                # Text shown (plain, escaped) when the cell's value is null, missing or an empty string,
                # with any formatter. Absent: the formatter's own rendering of an empty value.
                "empty_text": {
                    "description": (
                        "Plain text shown in place of a null, missing or empty-string value, with any formatter."
                    ),
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                },
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
                        "conclusionBadge",
                        "toneBadge",
                        "toneThreshold",
                        "percent",
                        "capitalized",
                        "externalLink",
                        "link",
                        "elapsed",
                        "iconMap",
                        "entityType",
                        "baselineRatio",
                        "baselineN",
                        "sparkline",
                        "tailSegment",
                        "painBadge",
                        "arrayCount",
                        "linkList",
                    ],
                },
                # Per-formatter parameters, handed to the JS formatter as
                # Tabulator formatterParams. Free-form by design: each
                # formatter documents its own keys in the spec (link:
                # href_field | href_template | value_href_template, external;
                # elapsed: start, end; iconMap: icons, labels, show_text;
                # entityType: show, tone (types is server-owned);
                # toneThreshold: steps, zero_tone, decimals; percent: decimals).
                "formatter_params": {
                    "description": (
                        "Per-formatter parameters, handed to the formatter; each formatter documents its keys in "
                        "the spec. `style` applies to every link formatter (link, externalLink, linkList)."
                    ),
                    "type": "object",
                    "properties": {
                        "style": {
                            "description": (
                                "Link appearance. `default` (absent): accent colour, underlined, highlighted on "
                                "hover. `plain`: the cell's own text colour, no underline, no hover highlight; "
                                "still clickable, with the keyboard focus ring."
                            ),
                            "type": "string",
                            "enum": ["default", "plain"],
                        },
                        # entityType (req-web-stdpanel-table-config-32): what to show and in which tone. `types`
                        # is filled by the server from the entity-type catalog, so an author cannot supply it.
                        "show": {
                            "description": "entityType only: the type's glyph, its name as a pill, or both.",
                            "type": "string",
                            "enum": ["icon", "name", "both"],
                        },
                        "tone": {
                            "description": "entityType only: the name pill's colour. Default muted.",
                            "type": "string",
                            "enum": ["good", "bad", "warn", "muted"],
                        },
                        "types": False,
                    },
                },
                # A named sorter for the column. `severityRank` orders severity words
                # (critical, high, medium, low and the like) by rank, not alphabetically.
                "sorter": {"type": "string", "enum": ["severityRank"]},
                "tooltip": {"type": "string", "enum": ["full_value"]},
                # Explains the column to a reader: shown as the header's
                # pop-over on hover. Plain text.
                "header_tooltip": {"type": "string", "maxLength": 600},
                "headerSort": {"type": "boolean"},
                # Wrap a long text value onto several lines (the row grows) instead of an ellipsis
                # (req-web-stdpanel-table-config-31).
                "wrap": {
                    "description": (
                        "true wraps a long text value onto several lines and lets the row grow to fit it, instead of "
                        "cutting it with an ellipsis. Default false."
                    ),
                    "type": "boolean",
                },
                # Horizontal alignment of the cell AND its heading, so a value
                # sits under its title (a one-row identity table reads as
                # label-over-value). Default left; cells are always vertically
                # centred (req-web-stdpanel-table-config-25).
                "align": {
                    "description": (
                        "Horizontal alignment of the cell and its heading together, so a value sits under its "
                        "title. Default left. Every cell is vertically centred whatever this says."
                    ),
                    "type": "string",
                    "enum": ["left", "center", "right"],
                },
            },
        },
    },
}

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_COLUMN_MODE = "common_metadata"

# Fixed breakpoints for page-size selector; "All" is appended dynamically.
_PAGE_SIZE_STEPS = [25, 50, 100, 200, 500]


def _script_ids(panel: Panel) -> dict[str, str]:
    """Element ids for this panel's embedded JSON payloads.

    The grammar (``tap-table-<kind>-<panel id>``) is the contract with
    ``tap_web/static/tap_web/js/panel-table.js``, which rebuilds the same ids by
    concatenation from ``data-tap-table-panel-id``. Kept here as one dict so the
    template never string-builds an id — ``json_script`` takes the id as a filter
    argument, and Django's ``add`` filter silently yields "" on a str+UUID concat.
    """
    pid = panel.entity_id
    return {
        "table_data_script_id": f"tap-table-data-{pid}",
        "table_columns_script_id": f"tap-table-columns-{pid}",
        "table_groupby_script_id": f"tap-table-groupby-{pid}",
        "table_initial_sort_script_id": f"tap-table-initialsort-{pid}",
    }


def _validate_table_config(config: dict[str, Any]) -> None:
    """Validate a Table Panel config dict against TABLE_CONFIG_SCHEMA.

    Raises:
        ValidationError: if the config fails schema validation.
    """
    try:
        jsonschema.validate(instance=config, schema=TABLE_CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError({"config": [exc.message]}) from exc


def _column_value(row: Any, spec: dict[str, Any]) -> Any:
    """Read a column's value from a row: ``field`` (dotted) or ``field_path`` (one key per segment)."""
    segments = spec.get("field_path") or str(spec.get("field") or "").split(".")
    cur = row
    for segment in segments:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)
    return cur


def _entity_type_catalog(slugs: set[str]) -> dict[str, dict[str, str]]:
    """Display metadata for entity-type slugs, from the catalog the plugin loader writes.

    Returns ``{slug: {"name": str, "icon": str}}`` for every slug the catalog knows. ``name`` is empty when the
    model published no ``ENTITY_NAME`` (the loader then stores the slug itself), ``icon`` is empty when the type
    published no ``ENTITY_ICON`` or its file is missing. A slug the catalog does not know is simply absent.
    The icon address is the registry's own static URL (``resolve_icon_url``), never a row value.
    """
    from tap_grid.icon import resolve_icon_url
    from tap_grid.models import EntityType

    if not slugs:
        return {}
    return {
        et.slug: {
            "name": "" if et.name == et.slug else et.name,
            "icon": resolve_icon_url(et) or "",
        }
        for et in EntityType.objects.filter(slug__in=slugs)
    }


def _with_entity_types(columns: list[dict[str, Any]] | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Fill ``formatter_params.types`` on every ``entityType`` column from the entity-type catalog.

    The columns are copied, never mutated: ``columns`` is the panel's stored config. One catalog query covers
    every such column of the page of rows.
    """
    if not columns:
        return columns

    def leaves(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in specs:
            out.extend(leaves(spec["columns"]) if "columns" in spec else [spec])
        return out

    wanted = [spec for spec in leaves(columns) if spec.get("formatter") == "entityType"]
    if not wanted:
        return columns
    slugs_by_column: dict[int, set[str]] = {}
    for spec in wanted:
        values = (_column_value(row, spec) for row in rows)
        slugs_by_column[id(spec)] = {value for value in values if isinstance(value, str) and value}
    catalog = _entity_type_catalog(set().union(*slugs_by_column.values()))

    def fill(spec: dict[str, Any]) -> dict[str, Any]:
        if "columns" in spec:
            return {**spec, "columns": [fill(child) for child in spec["columns"]]}
        if spec.get("formatter") != "entityType":
            return spec
        types = {slug: catalog[slug] for slug in slugs_by_column[id(spec)] if slug in catalog}
        return {**spec, "formatter_params": {**(spec.get("formatter_params") or {}), "types": types}}

    return [fill(spec) for spec in columns]


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
          table_nodes        - the rows to render: node dicts from the search
                               envelope, or (projection mode) its ``rows``
          table_mode         - "node", or "raw" for a projection's rows
          table_meta         - pagination / footer metadata dict
          table_search       - the linked Search instance, or None
          table_error        - error string, or None on success

        The node/column/group payloads are handed to the template as PLAIN PYTHON
        objects and embedded by Django's ``json_script`` filter, which owns the
        script-context escaping (req-web-panel-json-embed.sec). ``*_script_id``
        keys carry the element ids the panel JS looks up.
        """
        from tap_web.panel import get_panel_search

        search = get_panel_search(panel)
        if search is None:
            return {
                "table_nodes": [],
                "table_meta": {},
                "table_search": None,
                "table_error": "No search linked to this panel.",
                **_script_ids(panel),
            }

        config = panel.config or {}
        default_ps = config.get("default_page_size", _DEFAULT_PAGE_SIZE)

        # page_size=0 means "show all" (passed by the JS selector).
        raw_ps = request.GET.get("page_size")
        show_all = config.get("show_all_rows", True)
        if raw_ps is not None and raw_ps == "0" and show_all:
            page_size = 0  # sentinel: no limit
        else:
            page_size = _safe_int(raw_ps, default_ps)

        offset = _safe_int(request.GET.get("offset"), 0)
        effective_limit = page_size if page_size > 0 else None

        try:
            from tap_grid.search import execute_search, inputs_from_query

            # Page parameters (?workflow_id=…) reach the search as its declared
            # inputs, coerced by the search's own schema — the same path the
            # graph panel takes, so a page can host both over one URL.
            inputs = inputs_from_query(search, request.GET)
            result = execute_search(search, inputs or None, limit=effective_limit, offset=offset, layer="extended")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[87dd] Table panel search execution failed for panel %s", panel.entity_id)
            return {
                "table_nodes": [],
                "table_meta": {},
                "table_search": search,
                "table_error": f"Search execution failed: {exc}",
                **_script_ids(panel),
            }

        # Extract nodes and total count from paginated or unpaginated envelope.
        envelope = result["results"] if "results" in result else result
        custom_columns = config.get("columns")
        table_mode = "node"
        page_limit = effective_limit
        projection = _projection_rows(envelope)
        if projection is not None:
            # Projection mode (tap#432): the search RETURNs aliases, so the
            # envelope carries `rows` and no nodes. execute_search pages only
            # the node side, and a Gryphon search executes whole, so `rows` is
            # the complete result: page it here by the same window, and its
            # length is the true total — never the node-side total_count,
            # which is 0 for a projection (tap#299).
            table_mode = "raw"
            page_limit = result["limit"] if "results" in result else None
            total_count: int = len(projection)
            nodes: list[dict[str, Any]] = (
                projection[offset : offset + page_limit] if page_limit is not None else projection[offset:]
            )
            nodes = _with_row_urls(nodes, config.get("row_url_template"))
            if not custom_columns:
                custom_columns = _alias_columns(projection)
        elif "results" in result:
            nodes = envelope.get("nodes", [])
            total_count = envelope.get("info", {}).get("total_count", result["count"])
        else:
            nodes = result.get("nodes", [])
            total_count = result.get("info", {}).get("total_count", len(nodes))

        showing = len(nodes)
        page_size_options = _build_page_size_options(total_count, page_size, show_all=show_all)

        meta: dict[str, Any] = {
            "total_count": total_count,
            "showing": showing,
            "page_size": page_size,
            "page_size_options": page_size_options,
            "has_prev": offset > 0,
            "has_next": page_limit is not None and (offset + page_limit) < total_count,
            "prev_offset": max(0, offset - (page_limit or 0)),
            "next_offset": offset + (page_limit or 0),
        }

        group_by = config.get("group_by")
        return {
            "table_nodes": nodes,
            "table_mode": table_mode,
            "table_meta": meta,
            "table_search": search,
            "table_columns": _with_entity_types(custom_columns, nodes),
            "table_height": config.get("height"),
            "table_striped": bool(config.get("striped")),
            "table_empty_text": config.get("empty_text"),
            "table_refresh_seconds": config.get("refresh_seconds"),
            "table_group_by": group_by,
            "table_initial_sort": config.get("initial_sort"),
            "table_error": None,
            **_script_ids(panel),
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


def _projection_rows(envelope: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the envelope's projection rows, or None when it is node-shaped.

    A Gryphon search that RETURNs aliases (``RETURN a.x AS col``) yields
    ``rows`` and zero ``nodes`` (req-grid-gryphon-rows); one that RETURNs
    variables yields nodes and an empty ``rows``. Rows win only when there are
    rows and no nodes, so every node-shaped envelope keeps the node path. An
    empty projection falls through to node mode, which renders the same empty
    table and a true total of 0.
    """
    rows = envelope.get("rows")
    if rows and not envelope.get("nodes"):
        return [r for r in rows if isinstance(r, dict)]
    return None


def _alias_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Default columns for a projection with no declared ``columns``.

    One column per RETURN alias, in RETURN order (the first row's key order,
    which the executor builds from the RETURN list), titled by the alias.
    """
    return [{"field": alias, "title": alias, "headerSort": True} for alias in rows[0]] if rows else []


def _with_row_urls(rows: list[dict[str, Any]], template: str | None) -> list[dict[str, Any]]:
    """Set each projection row's ``_url`` from ``row_url_template``, and from nothing else.

    ``_url`` is the key the client's raw mode navigates by, so in projection
    mode only the panel's own template may set it: a search that RETURNs
    ``… AS _url`` has that alias dropped, on every row, template or not.
    The fill and the same-origin rule are the shared ``fill_row_url``
    (``tap_web.panels.row_url``, also the Chart panel's ``click``): a
    placeholder whose value is absent or empty leaves the row with no link.
    Rows are copied, never mutated: the envelope belongs to the search layer.
    """
    # The schema is enforced only by the editor's save; a grift-seeded config
    # reaches here unvalidated, so the same-origin rule is applied again at use.
    if template and not is_same_origin_template(template):
        logger.warning("[5b1e] Table panel row_url_template is not a same-origin path; rows get no link.")
        template = None
    out: list[dict[str, Any]] = []
    for row in rows:
        row = {k: v for k, v in row.items() if k != "_url"}
        url = fill_row_url(template, row)
        if url is not None:
            row["_url"] = url
        out.append(row)
    return out


def _build_page_size_options(
    total_count: int, current_page_size: int, *, show_all: bool = True
) -> list[dict[str, Any]]:
    """Build dynamic page-size selector options based on total row count.

    Only includes step values that are less than total_count.
    Appends an "All" option (value=0) representing the full set unless ``show_all`` is false
    (``show_all_rows: false``; req-web-stdpanel-table-config-29).
    """
    options: list[dict[str, Any]] = []
    for step in _PAGE_SIZE_STEPS:
        if step < total_count:
            options.append({"value": step, "label": str(step), "selected": current_page_size == step})

    # "All" option — selected when page_size is 0 or >= total_count.
    if show_all:
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
