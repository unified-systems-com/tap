"""Strip retired entity types out of a GRIFT document before import.

A plugin release pinned before a type was removed (tap#340 retired `landing_page`)
still ships the old node in its bundle. Failing that seed would fail the boot of
every instance on the older pin — an upgrade cliff for a node nobody reads any
more. Instead the seeding boundary drops such nodes, and every edge touching
them, and warns with the retirement reason so the plugin gets re-published
without them (req-web-page-landing-14). Everything else in the document is
untouched; the importer never sees the retired rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from tap_grid.registry import retired_entity_reason

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetiredStrip:
    """What `strip_retired_types` removed: (entity_type, entity_id) per node, and the edge count."""

    nodes: tuple[tuple[str, str], ...] = ()
    edges: int = 0

    @property
    def stripped(self) -> bool:
        return bool(self.nodes) or self.edges > 0

    @property
    def reasons(self) -> dict[str, str]:
        return {t: retired_entity_reason(t) or "" for t, _ in self.nodes}


def strip_retired_types(document: dict[str, Any]) -> tuple[dict[str, Any], RetiredStrip]:
    """Return (document without retired-type nodes and the edges touching them, what was removed).

    The input is not mutated; batches, nodes and edges lists are rebuilt as needed.
    """
    batches = document.get("batches")
    if not isinstance(batches, list):
        return document, RetiredStrip()

    stripped_nodes: list[tuple[str, str]] = []
    stripped_ids: set[str] = set()
    new_batches: list[Any] = []
    for batch in batches:
        if not isinstance(batch, dict):
            new_batches.append(batch)
            continue
        kept_nodes: list[Any] = []
        for node in batch.get("nodes", []) or []:
            entity = node.get("entity", {}) if isinstance(node, dict) else {}
            etype = entity.get("entity_type")
            if isinstance(etype, str) and retired_entity_reason(etype) is not None:
                stripped_nodes.append((etype, str(entity.get("entity_id"))))
                stripped_ids.add(str(entity.get("entity_id")))
                continue
            kept_nodes.append(node)
        new_batches.append({**batch, "nodes": kept_nodes})

    if not stripped_nodes:
        return document, RetiredStrip()

    edges_dropped = 0
    for batch in new_batches:
        if not isinstance(batch, dict):
            continue
        kept_edges: list[Any] = []
        for edge in batch.get("edges", []) or []:
            payload = edge.get("edge", {}) if isinstance(edge, dict) else {}
            if str(payload.get("from_entity_id")) in stripped_ids or str(payload.get("to_entity_id")) in stripped_ids:
                edges_dropped += 1
                continue
            kept_edges.append(edge)
        batch["edges"] = kept_edges

    return {**document, "batches": new_batches}, RetiredStrip(nodes=tuple(stripped_nodes), edges=edges_dropped)
