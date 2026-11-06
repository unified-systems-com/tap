"""Config schema and safety validation of the Chart panel (req-web-panels-chart-config, -safety).

``Panel.config`` is JSON data. The ECharts ``option`` it carries is data too, never code: this module
rejects anything that could run, fetch or inject before a chart is ever drawn.
"""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema
from django.core.exceptions import ValidationError

from tap_web.panels.row_url import ROW_URL_TEMPLATE_SCHEMA, is_same_origin_template, placeholders

# Fixed value -> colour vocabulary. The names are design tokens; the colours live in panel-chart.css as
# ``--tap-chart-<token>`` with light and dark values, so a chart reuses the site palette and follows the theme.
COLOR_TOKENS: tuple[str, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "info",
    "good",
    "warn",
    "bad",
    "neutral",
    "muted",
    *(f"accent-{n}" for n in range(1, 9)),
)

# Series types the panel draws. `custom` (needs a render function), `map` / `lines` (need registered
# geography) and `graph` (layout) are outside the closed vocabulary.
SERIES_TYPES: tuple[str, ...] = (
    "bar",
    "line",
    "pie",
    "scatter",
    "treemap",
    "sunburst",
    "heatmap",
    "funnel",
    "gauge",
    "radar",
)
HIERARCHICAL_TYPES: tuple[str, ...] = ("treemap", "sunburst")
CLICKABLE: tuple[str, ...] = ("bar", "scatter")
PIVOTABLE_TYPES: tuple[str, ...] = ("bar", "line")
PIVOT_OWNED: frozenset[str] = frozenset({"name", "type", "encode", "data", "dataset"})

FIELD_TYPES: tuple[str, ...] = ("number", "time", "category")
DEFAULT_HEIGHT = 320
DEFAULT_MAX_ROWS = 500
MAX_OPTION_BYTES = 32768
MAX_DEPTH = 14

_FIELD = {"type": "string", "minLength": 1, "maxLength": 200}
_TOKEN = {"type": "string", "enum": list(COLOR_TOKENS)}

CHART_CONFIG_SCHEMA: dict[str, Any] = {
    "description": (
        "Config of a Chart panel: an Apache ECharts `option` (JSON only) drawn from the rows of the bound "
        "Search. The panel injects the rows as `option.dataset`, so series pick fields with `encode`. "
        "Fields are named by the row's RETURN alias; nothing here names a value, node or tool."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["option"],
    "properties": {
        "option": {
            "type": "object",
            "description": (
                "The ECharts option object, as JSON. Never code: function-like strings, non-template "
                "formatters, external URLs and `dataset` (the panel owns it) are rejected."
            ),
        },
        "series_by": {
            "type": "object",
            "additionalProperties": False,
            "required": ["category", "series", "value"],
            "description": (
                "Pivot rows into one series per distinct value of `series`: the single series in "
                "`option.series` is the template (bar or line). The `category` field is the other axis."
            ),
            "properties": {
                "category": {**_FIELD, "description": "Row field drawn along the category (or time) axis."},
                "series": {**_FIELD, "description": "Row field whose distinct values each become one series."},
                "value": {**_FIELD, "description": "Row field holding the number plotted; duplicates are summed."},
                "order": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "string"},
                    "description": "Series values in drawing order (stack order); values not listed follow.",
                },
                "fill": {
                    "type": ["number", "null"],
                    "description": "Value for a category with no row for a series. Default 0; null leaves a gap.",
                },
                "overrides": {
                    "type": "object",
                    "maxProperties": 50,
                    "description": (
                        "Per-series changes: series value (the line's name) -> a partial ECharts series object "
                        "deep-merged onto the template for that series only. `name`, `type`, `encode`, `data` and "
                        "`dataset` cannot be set."
                    ),
                    "additionalProperties": {
                        "type": "object",
                        "description": "Partial series options for one series value, e.g. lineStyle, z, endLabel.",
                    },
                },
            },
        },
        "hierarchy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "description": (
                "Turn rows into a tree for treemap / sunburst series: one level per `path` field, in order; "
                "the last field names the leaf."
            ),
            "properties": {
                "path": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": _FIELD,
                    "description": "Row fields, outermost level first.",
                },
                "value": {
                    **_FIELD,
                    "description": "Row field sizing each leaf; each row counts 1 when absent. Duplicates are summed.",
                },
            },
        },
        "click": {
            "type": "object",
            "additionalProperties": False,
            "required": ["row_url_template"],
            "description": (
                "Click-through for bar and scatter series: clicking a data item navigates to the URL filled "
                "from that item's row. Items whose row lacks a placeholder value are not clickable."
            ),
            "properties": {
                "row_url_template": {
                    **ROW_URL_TEMPLATE_SCHEMA,
                    "description": (
                        "A same-origin path (never `//host`) whose `{alias}` placeholders take the row's values, "
                        "each URL-encoded as one component, e.g. `/vulnerabilities/component?cid={cid}`. The same "
                        "rule and fill as the Table panel's `row_url_template`. With `series_by`, only the "
                        "`category` field may be a placeholder."
                    ),
                }
            },
        },
        "color_map": {
            "type": "object",
            "additionalProperties": False,
            "required": ["map"],
            "description": (
                "Fixed value-to-design-token colours, so the same severity is the same colour on every chart. "
                "Applies to series named by a value (series_by, or a series `name`) and to data items whose "
                "`field` (or name) is a key."
            ),
            "properties": {
                "field": {
                    **_FIELD,
                    "description": "Row field whose value picks the colour; defaults to series_by.series, else the item name.",
                },
                "map": {
                    "type": "object",
                    "maxProperties": 100,
                    "description": "Row value (as text) to colour token.",
                    "additionalProperties": _TOKEN,
                },
                "default": {
                    **_TOKEN,
                    "description": "Token for a value the map does not list; the palette when omitted.",
                },
            },
        },
        "types": {
            "type": "object",
            "maxProperties": 50,
            "description": (
                "Per-field type, so rows are coerced before ECharts sees them: `number` (a numeric string such "
                'as "8.2" becomes 8.2), `time` (any ISO-8601 text or datetime becomes a UTC instant) or '
                "`category` (text). A value that does not parse is drawn as a gap and counted in a notice, "
                "never as 0."
            ),
            "additionalProperties": {"type": "string", "enum": list(FIELD_TYPES)},
        },
        "sort": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field"],
            "description": "Order rows before drawing (and before `limit`): by `field`, nulls last.",
            "properties": {
                "field": {**_FIELD, "description": "Row field to order by; numbers and times by value, else text."},
                "order": {"type": "string", "enum": ["asc", "desc"], "description": "Direction; default desc."},
            },
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
            "description": "Keep only the first N rows after `sort` (a top-N chart). The rest are counted in a notice.",
        },
        "height": {
            "oneOf": [
                {"type": "integer", "minimum": 120, "maximum": 1200},
                {"type": "string", "enum": ["slot"]},
            ],
            "description": (
                f"Chart height in pixels (default {DEFAULT_HEIGHT}), or `slot` to fill the height of the page "
                "slot the panel sits in (at least 240px)."
            ),
        },
        "empty_text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "Text shown when the Search returns no rows. Default: 'No results.'.",
        },
        "null_text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Label for a null (unobserved) category, series or tree-level value. Default: 'not observed'.",
        },
        "blank_text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Label for an empty-string category, series or tree-level value. Default: '(empty)'.",
        },
        "aria_label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "Accessible description of what the chart shows; defaults to the panel name.",
        },
        "max_rows": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
            "description": f"Most rows drawn; further rows are counted in a notice, never dropped silently. Default {DEFAULT_MAX_ROWS}.",
        },
        "hide_header": {
            "type": "boolean",
            "description": "When true, omit the panel's name heading above the chart.",
        },
    },
}

# A string that would be (or smuggle) code.
_CODE_LIKE = re.compile(
    r"\bfunction\b\s*\w*\s*\(|=>|\beval\s*\(|\bnew\s+Function\b|\bjavascript\s*:|<\s*/?\s*script|\burl\s*\(",
    re.IGNORECASE,
)
# A string that would make the browser fetch something.
_FETCHES = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//|^\s*(?:https?|ftp|file|data|blob):|^\s*image://", re.IGNORECASE)
# ECharts keys that navigate or inject CSS.
_FORBIDDEN_KEYS = frozenset({"link", "sublink", "extraCssText", "className"})
# Template tokens: {a} {b} {c} {@dim} {@[3]} {style|text} -- no markup.
_TEMPLATE_BAD = re.compile(r"[<>]")


def _walk(node: Any, path: str, depth: int, errors: list[str]) -> None:
    if depth > MAX_DEPTH:
        errors.append(f"{path}: nested deeper than {MAX_DEPTH} levels")
        return
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key in _FORBIDDEN_KEYS:
                errors.append(f"{here}: `{key}` is not allowed (it navigates or injects CSS)")
                continue
            if key == "dataset":
                errors.append(f"{here}: `dataset` is supplied by the panel from the Search rows")
                continue
            if key.lower().endswith("formatter") and not isinstance(value, str):
                errors.append(f"{here}: a formatter must be a plain template string")
                continue
            if key.lower().endswith("formatter") and _TEMPLATE_BAD.search(value):
                errors.append(f"{here}: a formatter is a plain template (placeholders and text), not markup")
                continue
            if key == "type" and path.endswith("series") is False and isinstance(value, str) and value == "custom":
                errors.append(f"{here}: `custom` series need code and are not allowed")
                continue
            _walk(value, here, depth + 1, errors)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, f"{path}[{i}]", depth + 1, errors)
    elif isinstance(node, str):
        if _CODE_LIKE.search(node):
            errors.append(f"{path}: looks like code; the option is data, not code")
        elif _FETCHES.search(node):
            errors.append(f"{path}: external or embedded resource references are not allowed")
    elif node is not None and not isinstance(node, bool | int | float):
        errors.append(f"{path}: not JSON data")


_BARE_VALUE = re.compile(r"\{c\d*\}")


def _formatters(node: Any, path: str = "option") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if key.lower().endswith("formatter") and isinstance(value, str):
                found.append((here, value))
            else:
                found.extend(_formatters(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_formatters(value, f"{path}[{i}]"))
    return found


def _series_list(option: dict[str, Any]) -> list[dict[str, Any]]:
    series = option.get("series")
    if isinstance(series, dict):
        return [series]
    return [s for s in series or [] if isinstance(s, dict)]


def check_option(option: dict[str, Any]) -> list[str]:
    """Every reason ``option`` is not safe data (empty when it is)."""
    errors: list[str] = []
    _walk(option, "option", 0, errors)
    for i, series in enumerate(_series_list(option)):
        kind = series.get("type")
        if kind not in SERIES_TYPES:
            errors.append(f"option.series[{i}].type: `{kind}` is not one of {', '.join(SERIES_TYPES)}")
    size = len(json.dumps(option, separators=(",", ":")).encode())
    if size > MAX_OPTION_BYTES:
        errors.append(f"option is {size} bytes; the limit is {MAX_OPTION_BYTES}")
    return errors


def validate_config(config: dict[str, Any]) -> None:
    """Raise ``ValidationError`` when ``config`` fails the schema or the option safety rules."""
    try:
        jsonschema.validate(instance=config, schema=CHART_CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError({"config": [exc.message]}) from exc

    option = config["option"]
    errors = check_option(option)
    series = _series_list(option)
    kinds = [s.get("type") for s in series]
    if config.get("series_by") and config.get("hierarchy"):
        errors.append("series_by and hierarchy cannot be combined")
    overrides = (config.get("series_by") or {}).get("overrides") or {}
    for value, partial in overrides.items():
        for key in sorted(PIVOT_OWNED & partial.keys()):
            errors.append(f"series_by.overrides.{value}.{key}: `{key}` is set by the pivot and cannot be overridden")
        _walk(partial, f"series_by.overrides.{value}", 0, errors)
    if config.get("series_by"):
        if len(series) != 1 or kinds[0] not in PIVOTABLE_TYPES:
            errors.append("series_by needs exactly one template series, of type bar or line, in option.series")
    if any(isinstance(s.get("encode"), dict) for s in series) or config.get("series_by"):
        for where, text in [*_formatters(option), *_formatters(overrides, "series_by.overrides")]:
            if _BARE_VALUE.search(text):
                errors.append(
                    f"{where}: `{{c}}` is the whole row when a series reads the dataset through `encode` "
                    "(it prints [object Object]); name the field instead: `{@field}`"
                )
    click = config.get("click")
    if click:
        template = click["row_url_template"]
        if not is_same_origin_template(template):
            errors.append("click.row_url_template must be a same-origin path")
        if config.get("hierarchy"):
            errors.append("click cannot be combined with hierarchy (tree items are not rows)")
        if not any(k in CLICKABLE for k in kinds):
            errors.append(f"click needs a {' or '.join(CLICKABLE)} series in option.series")
        if config.get("series_by"):
            extra = [a for a in placeholders(template) if a != config["series_by"]["category"]]
            if extra:
                errors.append(
                    "click.row_url_template with series_by may only use the category field "
                    f"`{config['series_by']['category']}` (found {', '.join('{' + a + '}' for a in extra)})"
                )
    if config.get("hierarchy") and not any(k in HIERARCHICAL_TYPES for k in kinds):
        errors.append("hierarchy needs a treemap or sunburst series in option.series")
    if errors:
        raise ValidationError({"config": errors})
