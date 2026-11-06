"""Stat Cards Panel — built-in panel type that renders one metric card per Search row.

The panel binds to ONE Search through a USES_SEARCH edge (the same binding the
table panel uses, ``tap_web.panel.get_panel_search``) and reads the ``rows``
envelope an aggregating Gryphon search returns (req-grid-gryphon-rows): one row
per GROUP BY key combination, or one row when the RETURN is all aggregates.
Every card is one row.

Everything about a card is declared in ``Panel.config`` by FIELD NAME of the
returned row — never by value, never by a node id or tool name
(req-web-stdpanel-statcards-config). Config validates against
``STAT_CARD_CONFIG_SCHEMA``.

Rendering is server-side semantic HTML. The two formatters that depend on the
viewer (``datetime``, ``age``) emit a ``<time>`` element that the shared static
JS finishes in the browser (``localtime.js`` for ``datetime``; ``stat-cards.js``
for ``age``); with no JS the element still reads the exact ISO value.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import jsonschema
from django.core.exceptions import ValidationError

from tap_web.panels.search_rows import fetch_panel_rows

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)

TONES: tuple[str, ...] = ("neutral", "good", "warn", "bad", "muted")
FORMATTERS: tuple[str, ...] = ("text", "number", "integer", "datetime", "age", "percent", "link")
# A secondary line may also be a long prose value (`longtext`); the card's main figure may not.
LINE_FORMATTERS: tuple[str, ...] = (*FORMATTERS, "longtext", "table")
# Formatters a table column may use: the single-value ones (no longtext, no nested table).
COLUMN_FORMATTERS: tuple[str, ...] = FORMATTERS
LAYOUTS: tuple[str, ...] = ("stacked", "figure_right")
TITLE_STYLES: tuple[str, ...] = ("normal", "bold")
ALIGNS: tuple[str, ...] = ("left", "right", "center")
PLACEMENTS: tuple[str, ...] = ("body", "header")
LABEL_PLACEMENTS: tuple[str, ...] = ("beside", "above")

_DEFAULT_MAX_CARDS = 24
_DEFAULT_NULL_TEXT = "not observed"
_DEFAULT_MISSING_TEXT = "not returned by the search"
_DEFAULT_BLANK_TEXT = "(empty)"
_DEFAULT_PERCENT_DECIMALS = 2
_DEFAULT_MAX_LINES = 4
_DEFAULT_TABLE_EMPTY_TEXT = "none"
_MAX_TABLE_ROWS = 200
# Words that carry a tone in text, so colour is never the only signal. `neutral`
# and `muted` carry none: they are the absence of a verdict.
_DEFAULT_TONE_LABELS: dict[str, str] = {"good": "Good", "warn": "Warning", "bad": "Problem"}

_FIELD = {"type": "string", "minLength": 1}
_FORMATTER = {"type": "string", "enum": list(FORMATTERS)}
_LINE_FORMATTER = {"type": "string", "enum": list(LINE_FORMATTERS)}
_DECIMALS = {"type": "integer", "minimum": 0, "maximum": 6}
_LINK_TEMPLATE = {"type": "string", "minLength": 1, "maxLength": 300}
_TONE = {"type": "string", "enum": list(TONES)}

# JSON Schema for Panel.config on Stat Cards instances. Every property carries a
# description (repo rule: JSON structures describe themselves).
STAT_CARD_CONFIG_SCHEMA: dict[str, Any] = {
    "description": (
        "Config of a Stat Cards panel: how each row of the bound Search's `rows` result becomes one metric card. "
        "Fields are named by the row's RETURN alias; nothing here names a value, node or tool."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["value_field"],
    "properties": {
        "value_field": {
            **_FIELD,
            "description": "Alias of the row field shown as the card's main figure.",
        },
        "value_formatter": {
            **_FORMATTER,
            "description": (
                "How the main figure is formatted: text (default), number, integer, datetime, age, percent "
                "(a fraction 0..1 shown as a percentage) or link (see value_link_template)."
            ),
        },
        "value_decimals": {
            **_DECIMALS,
            "description": "Decimal places of the main figure when value_formatter is percent. Default 2.",
        },
        "value_link_template": {
            **_LINK_TEMPLATE,
            "description": (
                "URL template for the main figure when value_formatter is link: {value} is the figure's text "
                "(URL-encoded) and {number} the first run of digits in it (for example 79 in CWE-79). "
                "Only http(s) and same-origin paths link; otherwise the figure shows as plain text."
            ),
        },
        "unit": {
            "type": "string",
            "maxLength": 40,
            "description": "Fixed unit or label printed beside the main figure (for example 'open'). Optional.",
        },
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "description": "Fixed card title, used when title_field is absent or the row has no value for it.",
        },
        "title_field": {
            **_FIELD,
            "description": "Alias of the row field shown as the card title (one title per row, e.g. a group key).",
        },
        "lines": {
            "type": "array",
            "maxItems": 12,
            "description": "Secondary label/value lines under the figure, in order.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field"],
                "description": "One secondary line: the row field it shows and, optionally, a label for it.",
                "if": {"properties": {"formatter": {"const": "table"}}, "required": ["formatter"]},
                "then": {"required": ["columns"]},
                "properties": {
                    "label": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                        "description": "Text label. Omit it and the value is drawn as plain text with no caption.",
                    },
                    "field": {**_FIELD, "description": "Alias of the row field shown."},
                    "label_placement": {
                        "type": "string",
                        "enum": list(LABEL_PLACEMENTS),
                        "description": (
                            "Where the label sits. beside (default): a definition-list row, label left and value "
                            "right. above: a small caption directly above the value, which then spans the card's "
                            "width (for example over a table line). Ignored when the line has no label."
                        ),
                    },
                    "placement": {
                        "type": "string",
                        "enum": list(PLACEMENTS),
                        "description": (
                            "Where the line is drawn. body (default): in the card body under the figure. header: "
                            "directly under the title, in the left column of the layout figure_right header, on the "
                            "same row as the unit under the figure; only the FIRST header line is placed there (its "
                            "label is not drawn) and with any other layout the line stays in the body."
                        ),
                    },
                    "formatter": {
                        **_LINE_FORMATTER,
                        "description": (
                            "Formatter for this line; text by default. longtext shows long prose wrapped and cut "
                            "to max_lines, expandable in place. table draws an ARRAY field as a borderless "
                            "table, one row per element (see columns)."
                        ),
                    },
                    "columns": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "description": (
                            "Columns of a table line, left to right. Each names a key of the array's elements "
                            "(objects). Required when the formatter is table; ignored otherwise."
                        ),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["field"],
                            "description": "One table column: the element key it shows, and how it is drawn.",
                            "properties": {
                                "field": {**_FIELD, "description": "Key of each array element shown in this column."},
                                "formatter": {
                                    "type": "string",
                                    "enum": list(COLUMN_FORMATTERS),
                                    "description": "Formatter for this column's cells; text by default.",
                                },
                                "decimals": {
                                    **_DECIMALS,
                                    "description": "Decimal places when the column formatter is percent. Default 2.",
                                },
                                "link_template": {
                                    **_LINK_TEMPLATE,
                                    "description": (
                                        "URL template when the column formatter is link: {value} and {number} "
                                        "as for a link line."
                                    ),
                                },
                                "align": {
                                    "type": "string",
                                    "enum": list(ALIGNS),
                                    "description": "Horizontal alignment of the column's cells. Default left.",
                                },
                                "bold": {
                                    "type": "boolean",
                                    "description": "When true the column's cells are drawn in bold. Default false.",
                                },
                            },
                        },
                    },
                    "empty_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                        "description": "Text a table line shows when its array is empty. Default: 'none'.",
                    },
                    "decimals": {
                        **_DECIMALS,
                        "description": "Decimal places when the formatter is percent. Default 2.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 12,
                        "description": "Lines of a longtext value shown before the reader expands it. Default 4.",
                    },
                    "link_template": {
                        **_LINK_TEMPLATE,
                        "description": (
                            "URL template when the formatter is link: {value} is the value's text (URL-encoded) "
                            "and {number} the first run of digits in it. Only http(s) and same-origin paths link."
                        ),
                    },
                },
            },
        },
        "layout": {
            "type": "string",
            "enum": list(LAYOUTS),
            "description": (
                "Card header layout. stacked (default): title, then figure with its unit beside it. "
                "figure_right: the title at the top left and the figure at the top right, large, with the unit "
                "underneath the figure."
            ),
        },
        "title_style": {
            "type": "string",
            "enum": list(TITLE_STYLES),
            "description": "normal (default) or bold: how the card title is drawn.",
        },
        "tone": {
            "description": (
                "Card tone. Either a fixed tone name, or {field, map, default}: the tone is chosen by the row "
                "value of `field` through `map`, falling back to `default` (neutral when omitted)."
            ),
            "oneOf": [
                _TONE,
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "map"],
                    "description": "Choose the tone from a field's value.",
                    "properties": {
                        "field": {**_FIELD, "description": "Alias of the row field whose value picks the tone."},
                        "map": {
                            "type": "object",
                            "description": "Row value (as text) to tone name.",
                            "additionalProperties": _TONE,
                        },
                        "default": {**_TONE, "description": "Tone for a value the map does not list."},
                    },
                },
            ],
        },
        "tone_text": {
            "type": "boolean",
            "description": (
                "When true, the card's title, figure and unit are drawn in the card's tone colour (the "
                "tone palette, light and dark), not only its left edge. Default false."
            ),
        },
        "zero_tone": {
            **_TONE,
            "description": (
                "Tone a card takes INSTEAD of `tone` when its figure (`value_field`) is the number zero, "
                "for example `muted` to grey out a count of nothing. A null, missing or non-number figure "
                "is not zero. Absent: a zero keeps the card's tone."
            ),
        },
        "tone_labels": {
            "type": "object",
            "description": "Override the words that announce a tone (tone name to text); an empty string shows none.",
            "additionalProperties": {"type": "string", "maxLength": 40},
            "propertyNames": _TONE,
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
            "description": "Text shown for a field whose value is null (unobserved). Default: 'not observed'.",
        },
        "missing_text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Text shown when the row has no such field at all (a config/Search mismatch).",
        },
        "blank_text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Text shown for an empty-string value (observed, but empty).",
        },
        "max_cards": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "description": "Most cards drawn; further rows are counted in a notice, never dropped silently. Default 24.",
        },
        "hide_header": {
            "type": "boolean",
            "description": "When true, omit the panel's name heading above the cards.",
        },
    },
}


def _validate_config(config: dict[str, Any]) -> None:
    """Raise ``ValidationError`` when ``config`` fails ``STAT_CARD_CONFIG_SCHEMA``."""
    try:
        jsonschema.validate(instance=config, schema=STAT_CARD_CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError({"config": [exc.message]}) from exc


def _decimal(value: Any) -> Decimal | None:
    """Return ``value`` as a finite Decimal, or None when it is not a plain number."""
    if isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _parse_instant(value: Any) -> datetime | None:
    """An aware UTC-comparable instant from a datetime or an ISO-8601 string, else None.

    A typed ``DateTimeField`` reaches a Gryphon row as a ``datetime``; a collector's string
    field as text. A naive value is read as UTC, the grid's canonical zone.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_TEMPLATE_PLACEHOLDER = re.compile(r"\{([A-Za-z_]+)\}")


def percent_text(value: Any, decimals: int = _DEFAULT_PERCENT_DECIMALS) -> str | None:
    """A fraction 0..1 as a percentage (0.0004 -> "0.04%"), or None when it is not such a fraction."""
    d = _decimal(value)
    if d is None or d < 0 or d > 1:
        return None
    scaled = (d * 100).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return f"{scaled:,.{decimals}f}%"


def safe_href(href: str) -> bool:
    """True for an absolute http(s) URL or a same-origin path; never ``//host``, ``/\\host`` or another scheme."""
    if href.startswith("/"):
        return not href.startswith(("//", "/\\")) and not re.search(r"[\x00-\x20\x7f\\]", href)
    return bool(re.match(r"https?://[^\s/]", href, re.IGNORECASE)) and not re.search(r"[\x00-\x20\x7f]", href)


def identifier_href(template: str | None, value: str) -> str | None:
    """Fill an identifier link template, or None when it cannot make a safe link.

    ``{value}`` is the value, URL-encoded; ``{number}`` the first run of digits in it (79 for
    ``CWE-79``). A template naming anything else, a ``{number}`` with no digits to fill it, or
    a result that is not an http(s) URL or same-origin path yields None: the caller shows the text.
    """
    if not template:
        return None
    number = re.search(r"\d+", value)
    parts = {"value": quote(value, safe=""), "number": number.group(0) if number else None}
    unfillable = False

    def fill(match: re.Match[str]) -> str:
        nonlocal unfillable
        part = parts.get(match.group(1))
        if part is None:
            unfillable = True
            return ""
        return part

    href = _TEMPLATE_PLACEHOLDER.sub(fill, template)
    return None if unfillable or not safe_href(href) else href


def format_cell(
    row: dict[str, Any],
    field: str,
    formatter: str,
    config: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Format one row field into a template cell.

    A cell is ``{"kind", "text", ...}`` where kind is ``text`` (plain),
    ``time`` (a localized instant), ``age`` (an elapsed time the browser
    computes), ``link`` (text with an ``href``), ``longtext`` (prose the template
    clamps to ``max_lines`` and lets the reader expand) or ``state`` (null / missing /
    blank, drawn muted so it can never
    pass for a value). ``options`` carries the per-line ``decimals``, ``max_lines`` and
    ``link_template``. The three states are told apart on purpose: a field the
    row does not carry is a config mismatch, null is *unobserved*, and ``""``
    is observed-empty (the grid's null convention).
    """
    if field not in row:
        return {"kind": "state", "state": "missing", "text": config.get("missing_text", _DEFAULT_MISSING_TEXT)}
    value = row[field]
    if value is None:
        return {"kind": "state", "state": "null", "text": config.get("null_text", _DEFAULT_NULL_TEXT)}
    if value == "":
        return {"kind": "state", "state": "blank", "text": config.get("blank_text", _DEFAULT_BLANK_TEXT)}

    options = options or {}
    if formatter == "table":
        return _table_cell(value, config, options)
    if formatter == "longtext":
        text = str(value)
        if not text.strip():
            return {"kind": "state", "state": "blank", "text": config.get("blank_text", _DEFAULT_BLANK_TEXT)}
        return {"kind": "longtext", "text": text, "max_lines": options.get("max_lines") or _DEFAULT_MAX_LINES}
    if formatter == "percent":
        shown = percent_text(value, options.get("decimals", _DEFAULT_PERCENT_DECIMALS))
        if shown is None:
            return {"kind": "text", "text": str(value), "title": "not a fraction between 0 and 1"}
        return {"kind": "text", "text": shown, "title": str(value)}
    if formatter == "link":
        href = identifier_href(options.get("link_template"), str(value))
        if href is None:
            return {"kind": "text", "text": str(value)}
        return {"kind": "link", "text": str(value), "href": href}
    if formatter in ("number", "integer"):
        d = _decimal(value)
        if d is None:
            return {"kind": "text", "text": str(value), "title": "not a number"}
        if formatter == "integer":
            return {"kind": "text", "text": f"{int(d.to_integral_value()):,}"}
        whole, _, frac = f"{d:,f}".partition(".")
        frac = frac.rstrip("0")
        return {"kind": "text", "text": f"{whole}.{frac}" if frac else whole}
    if formatter in ("datetime", "age"):
        instant = _parse_instant(value)
        if instant is None:
            return {"kind": "text", "text": str(value), "title": "not a date-time"}
        iso = instant.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return {"kind": "time" if formatter == "datetime" else "age", "text": iso, "iso": iso}
    return {"kind": "text", "text": str(value)}


def _table_cell(value: Any, config: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """A borderless table cell from an ARRAY row value, one table row per element.

    Each element is an object read by the line's ``columns``; a non-object element has no keys, so its
    cells state ``missing`` rather than guessing. A value that is not an array is shown as written and
    flagged; an empty array is a stated state (the line's ``empty_text``), never an empty table. Cell
    text is plain and auto-escaped by the template. At most 200 rows are drawn; the rest are counted.
    """
    if not isinstance(value, list):
        return {"kind": "text", "text": str(value), "title": "not an array"}
    columns = options.get("columns") or []
    if not value or not columns:
        text = options.get("empty_text", _DEFAULT_TABLE_EMPTY_TEXT)
        return {"kind": "state", "state": "empty", "text": text}
    rows = []
    for element in value[:_MAX_TABLE_ROWS]:
        item = element if isinstance(element, dict) else {}
        rows.append(
            [
                {
                    "cell": format_cell(item, col["field"], col.get("formatter", "text"), config, col),
                    "align": col.get("align", "left"),
                    "bold": bool(col.get("bold")),
                }
                for col in columns
            ]
        )
    return {
        "kind": "table",
        "rows": rows,
        "omitted": max(0, len(value) - _MAX_TABLE_ROWS),
    }


def _line_groups(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs of consecutive labelled lines (a definition list each), single unlabelled lines (plain text) and
    single captioned lines (``label_placement: "above"``: a small caption over the value)."""
    groups: list[dict[str, Any]] = []
    for line in lines:
        if line["label"] and line.get("caption"):
            groups.append({"labelled": False, "captioned": True, "lines": [line]})
        elif line["label"]:
            if groups and groups[-1]["labelled"]:
                groups[-1]["lines"].append(line)
            else:
                groups.append({"labelled": True, "captioned": False, "lines": [line]})
        else:
            groups.append({"labelled": False, "captioned": False, "lines": [line]})
    return groups


def _tone_for(row: dict[str, Any], tone: Any) -> str:
    if isinstance(tone, str):
        return tone
    if isinstance(tone, dict):
        raw = row.get(tone["field"])
        key = "" if raw is None else str(raw)
        return str(tone["map"].get(key, tone.get("default", "neutral")))
    return "neutral"


def _is_zero(row: dict[str, Any], field: str) -> bool:
    """True when the row's ``field`` is the number zero (0, 0.0, "0"); null, missing and text are not."""
    if field not in row:
        return False
    d = _decimal(row[field])
    return d is not None and d == 0


def build_cards(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn search rows into template-ready cards, driven only by ``config``."""
    labels = {**_DEFAULT_TONE_LABELS, **(config.get("tone_labels") or {})}
    cards: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        title: dict[str, Any] | None = None
        if config.get("title_field"):
            cell = format_cell(row, config["title_field"], "text", config)
            if cell["kind"] == "text":
                title = cell
        if title is None and config.get("title"):
            title = {"kind": "text", "text": config["title"]}
        tone = _tone_for(row, config.get("tone", "neutral"))
        zero = bool(config.get("zero_tone")) and _is_zero(row, config["value_field"])
        if zero:
            tone = config["zero_tone"]
        lines = [
            {
                "label": line.get("label", ""),
                "caption": line.get("label_placement") == "above",
                "header": line.get("placement") == "header",
                "cell": format_cell(row, line["field"], line.get("formatter", "text"), config, line),
            }
            for line in config.get("lines", [])
        ]
        # Only the figure_right header has room for a line; the FIRST header line moves there, the rest stay.
        header_line = None
        if config.get("layout") == "figure_right":
            header_line = next((line for line in lines if line["header"]), None)
            if header_line is not None:
                lines = [line for line in lines if line is not header_line]
        cards.append(
            {
                "index": index,
                "title": title,
                "layout": config.get("layout", "stacked"),
                "title_bold": config.get("title_style") == "bold",
                "value": format_cell(
                    row,
                    config["value_field"],
                    config.get("value_formatter", "text"),
                    config,
                    {
                        "decimals": config.get("value_decimals", _DEFAULT_PERCENT_DECIMALS),
                        "link_template": config.get("value_link_template"),
                    },
                ),
                "unit": config.get("unit", ""),
                "header_line": header_line,
                "lines": lines,
                "line_groups": _line_groups(lines),
                "tone": tone,
                "zero": zero,
                "tone_text": bool(config.get("tone_text")),
                "tone_label": labels.get(tone, ""),
            }
        )
    return cards


class StatCardPanelType:
    """Built-in stat-card panel type descriptor."""

    slug = "stat-cards"
    label = "Stat Cards"
    view = "tap_web/panels/stat_card_panel.html"
    editor_view = ""
    css: list[str] = ["tap_web/css/stat-cards.css"]
    js: list[str] = ["tap_web/js/stat-cards.js"]
    config_defaults: dict[str, Any] = {"max_cards": _DEFAULT_MAX_CARDS}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Execute the bound Search and return the cards (or the reason there are none)."""
        config = {**cls.config_defaults, **(panel.config or {})}
        base: dict[str, Any] = {"cards": [], "cards_error": None, "cards_empty_text": None, "cards_omitted": 0}

        try:
            _validate_config(config)
        except ValidationError as exc:
            return {**base, "cards_error": f"Invalid stat-card config: {'; '.join(exc.messages)}"}

        fetched = fetch_panel_rows(panel, request, label="Stat cards")
        if fetched.error:
            return {**base, "cards_error": fetched.error}
        rows = fetched.rows
        if not rows:
            return {**base, "cards_empty_text": config.get("empty_text", "No results.")}

        limit = config["max_cards"]
        return {**base, "cards": build_cards(rows[:limit], config), "cards_omitted": max(0, len(rows) - limit)}
