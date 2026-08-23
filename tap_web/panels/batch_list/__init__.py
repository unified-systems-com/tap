"""Batch List Panel Type — `batch-list`.

A roster of every batch on the grid (collector runs, GRIFT imports, service
mutations), newest-first. Rows click through to the single-batch viewer at
`/administrivia/batch`.

Why a dedicated panel rather than the generic search-driven `table` panel:
a batch's most useful columns — `status`, `started_at`, `closed_at` — are
lifecycle fields the Batch model deliberately keeps OUT of its writeable
`FIELD_CRUD_SCHEMA`, so they never appear in the Gryphon node `data` envelope
that the generic table reads (they'd render blank). This panel reads the
`Batch` ORM rows directly, so those fields are available. It emits a `raw`
Tabulator (see panel-table.js `mode="raw"`); each row carries a `_url` for
click-through.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.http import HttpRequest

from tap_grid.models import Batch
from tap_web.models import Panel
from tap_web.panel import TABULATOR_CSS, TABULATOR_JS
from tap_web.utils import safe_json


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def build_context(panel: Any, request: Any) -> dict[str, Any]:
    """Pure function — separated from the classmethod so tests can call it directly."""
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {"open": 0, "closed": 0, "failed": 0}
    for b in Batch.objects.order_by("-started_at"):
        status_counts[b.status] = status_counts.get(b.status, 0) + 1
        rows.append(
            {
                "name": b.name or "(unnamed batch)",
                "source": b.source or "",
                "status": b.status,
                "started_at": _iso(b.started_at),
                "closed_at": _iso(b.closed_at),
                "entity_id": str(b.entity_id),
                "_url": f"/administrivia/batch?batch_entity_id={b.entity_id}",
            }
        )

    return {
        "panel_slug": "batch-list",
        "rows_json": safe_json(rows),
        "counts": {
            "total": len(rows),
            "open": status_counts.get("open", 0),
            "closed": status_counts.get("closed", 0),
            "failed": status_counts.get("failed", 0),
        },
    }


class BatchListPanelType:
    """Panel type for the batch roster."""

    slug: ClassVar[str] = "batch-list"
    label: ClassVar[str] = "Batch List"
    view: ClassVar[str] = "tap_web/panels/batch_list.html"
    css: ClassVar[list[str]] = [*TABULATOR_CSS, "tap_web/css/batch-viewer.css"]
    js: ClassVar[list[str]] = [*TABULATOR_JS]
    config_defaults: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        return build_context(panel, request)
