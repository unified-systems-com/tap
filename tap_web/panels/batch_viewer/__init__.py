"""Batch Viewer Panel Type — `batch-viewer`.

Makes one GRIFT/collector/service batch legible: what it added (nodes + edges),
what it removed (deletes + purges), and the batch's own metadata. Generic —
any batch from any plugin.

Sourcing (see spec-web-batch-viewer-v0.md — `batch_id` is on the typed rows,
not the Entity spine, so cross-type questions go through Gryphon):
  nodes added  → Gryphon  n.data.batch_id == bid AND deleted_at IS NULL
  edges added  → Edge.objects.filter(batch_id=bid)  (from → type → to)
  deletes      → Gryphon  n.data.batch_id == bid AND deleted_at IS NOT NULL
  purges       → batch.metadata["removals"] (the only place hard-deleted rows
                 survive — a recorded manifest; honest empty state when absent)

Resolution contract: tap_web/specs/spec-web-panel-entity-resolution-v0.md
"""

from __future__ import annotations

from collections import Counter
from typing import Any, ClassVar

from django.http import HttpRequest

from tap_grid.gryphon.executor import execute_gryphon_raw
from tap_grid.models import Batch, Edge
from tap_web.models import Panel
from tap_web.panel import TABULATOR_CSS, TABULATOR_JS
from tap_web.panels.entity_resolution import resolve_entity
from tap_web.utils import safe_json

DEFAULT_VAR_NAME = "batch_entity_id"


def _nodes_by_batch(bid: str, *, deleted: bool) -> list[dict[str, Any]]:
    """Live (deleted=False) or tombstoned (deleted=True) nodes stamped with the batch."""
    # deleted_at is a spine field (n.deleted_at), NOT a data field — Gryphon
    # exposes it directly; n.data.deleted_at would never resolve.
    clause = "IS NOT NULL" if deleted else "IS NULL"
    query = f"MATCH (n) WHERE n.data.batch_id = $bid AND n.deleted_at {clause} RETURN n"
    envelope = execute_gryphon_raw(query, {"bid": bid}, layer="extended")
    return [
        {
            "entity_type": n.get("entity_type"),
            "name": n.get("name") or "",
            "entity_id": n.get("entity_id"),
            "deleted_at": n.get("deleted_at"),
        }
        for n in (envelope.get("nodes") or [])
        if n.get("entity_type") != "batch"  # the batch node itself isn't "added by" itself
    ]


def build_context(panel: Any, request: Any) -> dict[str, Any]:
    """Pure function — separated from the classmethod so tests can call it directly."""
    resolution = resolve_entity(panel, request, default_var_name=DEFAULT_VAR_NAME)
    base: dict[str, Any] = {
        "panel_slug": "batch-viewer",
        "entity_id": resolution.entity_id,
        "var_name": resolution.var_name,
        "used_fallback": resolution.used_fallback,
        "fallback_description": resolution.fallback_description,
        "fallback_count": resolution.fallback_count,
        "error_phase": None,
        "error_message": None,
        "batch": None,
        "counts": None,
        "nodes_json": "[]",
        "edges_json": "[]",
        "deletes_json": "[]",
        "purges_json": "[]",
        "has_manifest": False,
    }

    if not resolution.ok:
        base["error_phase"] = "load"
        base["error_message"] = resolution.error
        return base

    bid = resolution.entity_id
    batch = Batch.objects.filter(entity_id=bid).first()
    if batch is None:
        base["error_phase"] = "load"
        base["error_message"] = f"Entity {bid} is not a batch."
        return base

    base["batch"] = {
        "name": batch.name or "(unnamed batch)",
        "source": batch.source,
        "status": batch.status,
        "started_at": batch.started_at,
        "closed_at": batch.closed_at,
        "description": batch.description,
        "error_message": batch.error_message,
        "entity_id": bid,
    }

    # Nodes added (live) + deletes (tombstones).
    added = _nodes_by_batch(bid, deleted=False)
    tombstoned = _nodes_by_batch(bid, deleted=True)
    added_ids = {r["entity_id"] for r in added}

    # Edges added — from → type → to, with each endpoint flagged in-batch vs external.
    edges = Edge.objects.filter(batch_id=bid).select_related("from_entity", "to_entity")
    edge_rows = []
    for e in edges:
        fid, tid = str(e.from_entity_id), str(e.to_entity_id)
        edge_rows.append(
            {
                "from_name": (e.from_entity.name if e.from_entity else "") or fid[:12],
                "from_type": e.from_entity.entity_type if e.from_entity else "?",
                "from_scope": "in-batch" if fid in added_ids else "external",
                "edge_type": e.edge_type,
                "to_name": (e.to_entity.name if e.to_entity else "") or tid[:12],
                "to_type": e.to_entity.entity_type if e.to_entity else "?",
                "to_scope": "in-batch" if tid in added_ids else "external",
            }
        )

    # Purges — only recoverable from a persisted manifest (hard-deleted rows are gone).
    metadata = batch.metadata or {}
    removals = metadata.get("removals")
    base["has_manifest"] = isinstance(removals, list)
    purge_rows = [
        {"entity_type": r.get("entity_type"), "name": r.get("name"), "entity_id": r.get("entity_id")}
        for r in (removals or [])
        if r.get("action") == "purge"
    ]

    base["nodes_json"] = safe_json(sorted(added, key=lambda r: (r["entity_type"] or "", r["name"])))
    base["edges_json"] = safe_json(sorted(edge_rows, key=lambda r: (r["edge_type"] or "", r["from_name"])))
    base["deletes_json"] = safe_json(sorted(tombstoned, key=lambda r: (r["entity_type"] or "", r["name"])))
    base["purges_json"] = safe_json(purge_rows)
    base["counts"] = {
        "nodes": len(added),
        "edges": len(edge_rows),
        "deletes": len(tombstoned),
        "purges": len(purge_rows),
        "node_types": len(Counter(r["entity_type"] for r in added)),
    }
    return base


class BatchViewerPanelType:
    """Panel type for the batch viewer."""

    slug: ClassVar[str] = "batch-viewer"
    label: ClassVar[str] = "Batch Viewer"
    view: ClassVar[str] = "tap_web/panels/batch_viewer.html"
    css: ClassVar[list[str]] = [*TABULATOR_CSS, "tap_web/css/batch-viewer.css"]
    js: ClassVar[list[str]] = [*TABULATOR_JS]
    config_defaults: ClassVar[dict[str, Any]] = {"entity_id_var": DEFAULT_VAR_NAME}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        return build_context(panel, request)
