"""Chart Panel — tap_web-owned, declarative ECharts panel fed by a Search.

``Panel.config.option`` is an Apache ECharts option (JSON only). The panel runs the bound Search
(``tap_web.panels.search_rows``, the Stat Cards data path), coerces and caps the rows, injects them as
``option.dataset`` (or pivots / nests them for ``series_by`` / ``hierarchy``) and hands the result to
``chart-panel.js``, which draws it with the page's design tokens. No per-chart Python or JavaScript.

Spec: tap_web/specs/spec-web-panels-chart.md
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError

from tap_web.panels.chart.config import (
    CHART_CONFIG_SCHEMA,
    COLOR_TOKENS,
    DEFAULT_HEIGHT,
    DEFAULT_MAX_ROWS,
    validate_config,
)
from tap_web.panels.chart.transform import build_option, coerce_rows, row_urls, sort_and_limit
from tap_web.panels.search_rows import fetch_panel_rows

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

__all__ = ["CHART_CONFIG_SCHEMA", "COLOR_TOKENS", "ChartPanelType", "validate_config"]


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _table(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    """The visually hidden data table: every column of the rows, null written out as nothing."""
    columns: list[str] = []
    for row in rows:
        columns.extend(k for k in row if k not in columns)
    body = [["" if row.get(c) is None else str(row[c]) for c in columns] for row in rows]
    return columns, body


class ChartPanelType:
    """tap_web-owned chart panel type backed by Apache ECharts."""

    slug = "chart"
    label = "Chart"
    view = "tap_web/panels/chart.html"
    css: list[str] = ["tap_web/css/panel-chart.css"]
    # Order matters: the page pipeline emits scripts in this order, ECharts first.
    js: list[str] = ["tap_web/js/lib/echarts.min.js", "tap_web/js/chart-panel.js"]
    editor_view = ""
    config_defaults: dict[str, Any] = {"max_rows": DEFAULT_MAX_ROWS, "height": DEFAULT_HEIGHT}
    form_class = None

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Run the bound Search and return the chart payload (or the reason there is none)."""
        config = {**cls.config_defaults, **(panel.config or {})}
        base: dict[str, Any] = {"chart": None, "chart_error": None, "chart_empty_text": None, "chart_notices": []}

        try:
            validate_config(config)
        except ValidationError as exc:
            return {**base, "chart_error": f"Invalid chart config: {'; '.join(exc.messages)}"}

        fetched = fetch_panel_rows(panel, request, label="Chart")
        if fetched.error:
            return {**base, "chart_error": fetched.error}
        if not fetched.rows:
            return {**base, "chart_empty_text": config.get("empty_text", "No results.")}

        rows, notices = coerce_rows(fetched.rows, config.get("types") or {})
        rows, cut = sort_and_limit(rows, config)
        built = build_option(rows, config)
        columns, body = _table(rows)
        # Keyboard and screen-reader route to a click-through: the hidden data table carries a real link per
        # clickable row (the canvas itself is not focusable); `chart-panel.css` reveals it on focus.
        urls = row_urls(rows, config) if not config.get("hierarchy") else []
        link_rows = (
            [{"cells": body[i], "url": urls[i], "label": body[i][0] if body[i] else ""} for i in range(len(body))]
            if any(urls)
            else []
        )
        height = config["height"]
        color_map = config.get("color_map")
        if color_map and "field" not in color_map and config.get("series_by"):
            color_map = {**color_map, "field": config["series_by"]["series"]}
        return {
            **base,
            "chart": {
                "option_json": _compact(built.option),
                "colors_json": _compact(color_map) if color_map else "",
                "slot": height == "slot",
                "height": None if height == "slot" else height,
                "aria_label": config.get("aria_label") or panel.name,
                "summary": f"{len(rows)} row{'s' if len(rows) != 1 else ''}",
                "columns": columns,
                "body": body,
                "link_rows": link_rows,
            },
            "chart_notices": [*notices, *cut, *built.notices],
        }
