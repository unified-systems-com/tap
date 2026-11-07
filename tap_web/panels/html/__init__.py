"""HTML Panel — tap_web-owned panel that shows untrusted markup after cleaning it (`req-web-panels-html-panel-type`).

The markup comes from ``Panel.config["html"]`` or from one field of a row of the Search the panel is bound to, and is untrusted
either way. It is cleaned on every render by ``sanitize`` against a policy built from the panel's config (a closed vocabulary of
named features the config can only narrow). The cleaned string is marked safe in exactly one place, ``_safe``, below. If cleaning
fails for any reason the panel shows a message and no content: never the original markup, never an escaped copy of it.

Spec: tap_web/specs/spec-web-panels-html.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils.safestring import mark_safe

from tap_web.panels.html import sanitize
from tap_web.panels.html.config import HTML_PANEL_CONFIG_SCHEMA, validate_config
from tap_web.panels.search_rows import fetch_panel_rows

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

__all__ = ["HTML_PANEL_CONFIG_SCHEMA", "HtmlPanelType", "html_context", "validate_config"]

logger = logging.getLogger(__name__)


def _safe(cleaned: str) -> Any:
    """The one place markup is marked safe: the output of ``sanitize.clean``, and nothing else."""
    return mark_safe(cleaned)  # noqa: S308  # nosec B308 B703  # nosemgrep - the one trusted step (req-web-panels-html-render-3): only sanitize.clean's output


def html_context(config: dict[str, Any], rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The template context. ``rows`` is the bound Search's rows (None when it failed), used only with ``field``."""
    if "html" in config:
        source: Any = config["html"]
    else:
        if rows is None:
            return {"state": "failed"}
        index = config.get("row", 0)
        row = rows[index] if 0 <= index < len(rows) else None
        source = row.get(config["field"]) if row else None
        if source is None:
            return {"state": "empty"}
        if not isinstance(source, str):
            return {"state": "not_text"}
    if not source.strip():
        return {"state": "empty"}
    try:
        cleaned = sanitize.clean(source, sanitize.Policy.from_config(config))
    except sanitize.CleanerUnavailable:
        logger.error("[8c41] html panel: the cleaner is not installed")
        return {"state": "unavailable"}
    except sanitize.HtmlRefused as exc:
        return {"state": "refused", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.error("[8c42] html panel: cleaning failed (%s)", type(exc).__name__)
        return {"state": "unavailable"}
    return {"state": "ok", "content": _safe(cleaned.html), "removed": cleaned.removed}


class HtmlPanelType:
    """tap_web-owned panel type that shows cleaned HTML."""

    slug = "html"
    label = "HTML"
    view = "tap_web/panels/html.html"
    css: list[str] = ["tap_web/css/panel-html.css"]
    js: list[str] = []
    editor_view = ""
    config_defaults: dict[str, Any] = {}
    form_class = None

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        config = panel.config if isinstance(panel.config, dict) else {}
        problem = validate_config(config)
        if problem:
            return {"state": "bad_config", "detail": problem}
        rows: list[dict[str, Any]] | None = None
        if "field" in config:
            fetched = fetch_panel_rows(panel, request, label="HTML")
            rows = None if fetched.error else fetched.rows
        return html_context(config, rows)
