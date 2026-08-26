"""Canonical panel-entity resolution per spec-web-panel-entity-resolution-v0.

Two narrow lookup operations plus an orchestrator. The orchestrator reads
panel config (`entity_id_var` for URL deep links; `fallback.{query,
description}` for the fallback Gryphon query) and dispatches between the
two paths. Consumer panels call `resolve_entity`; they do not import Gryphon
directly.

The fallback `query` is opaque to this module — the panel author writes
whatever query expresses the panel's intent, and the helper runs it
verbatim. `LIMIT 1` queries return 0 or 1 rows; `LIMIT 2` queries detect
ambiguity by returning 0, 1, or 2. The helper reports the count; the
caller interprets it.

TAP-IMPLEMENTS: req-web-panel-entity-resolution-helper@faac477f34cb/23b1bdeb4c8e (derivation) —
    the canonical helper module the requirement locates: two narrow lookups plus
    the resolve_entity orchestrator; consumer panels import from here, never
    Gryphon directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EntityResolution:
    """Outcome of resolving an entity per the spec.

    TAP-IMPLEMENTS: req-web-panel-entity-resolution-result-shape@d91157e7f055/6824ff18e89a (derivation) —
        the stable seven-field result surface plus the `ok` property; carries no
        consumer-specific derived state.
    """

    entity_id: str
    var_name: str
    node: dict[str, Any] | None
    error: str | None
    used_fallback: bool = False
    fallback_description: str | None = None
    fallback_count: int | None = None

    @property
    def ok(self) -> bool:
        return self.node is not None and self.error is None


def _lookup_by_entity_id(entity_id: str) -> dict[str, Any] | None:
    """Gryphon labelless `MATCH (n) WHERE n.entity_id = $entity_id`.

    entity_id is a spine field uniquely indexed across registered node types,
    so this is one Entity-spine scan returning at most one row.
    """
    from tap_grid.gryphon.executor import execute_gryphon_raw

    envelope = execute_gryphon_raw(
        "MATCH (n) WHERE n.entity_id = $entity_id",
        {"entity_id": entity_id},
        layer="extended",
    )
    nodes = envelope.get("nodes", []) or []
    return nodes[0] if nodes else None


def _run_fallback_query(query: str) -> tuple[list[dict[str, Any]], int]:
    """Run the panel-supplied Gryphon query verbatim, return (nodes, count).

    The helper does not interpret or modify the query. The count is what
    the database returned (capped by whatever LIMIT the query carries).
    Transient Gryphon errors raise.
    """
    from tap_grid.gryphon.executor import execute_gryphon_raw

    envelope = execute_gryphon_raw(query, {}, layer="extended")
    nodes = envelope.get("nodes", []) or []
    return nodes, len(nodes)


def resolve_entity(
    panel: Any,
    request: Any,
    *,
    role: str | None = None,
    default_var_name: str,
) -> EntityResolution:
    """Resolve the entity for a panel — URL deep link wins, fallback query second.

    For single-entity panels, read `panel.config["entity_id_var"]` and
    `panel.config["fallback"]`. For multi-entity panels, pass `role`; the
    orchestrator then reads `panel.config["<role>_entity_id_var"]` and
    `panel.config["fallback"][role]`.
    """
    config = getattr(panel, "config", None) or {}

    if role:
        var_name_key = f"{role}_entity_id_var"
        fallback_root = config.get("fallback") or {}
        fallback_subblock = fallback_root.get(role) if isinstance(fallback_root, dict) else None
    else:
        var_name_key = "entity_id_var"
        fallback_subblock = config.get("fallback")

    var_name = config.get(var_name_key, default_var_name)
    if isinstance(fallback_subblock, dict):
        fallback_query = fallback_subblock.get("query")
        fallback_description = fallback_subblock.get("description")
    else:
        fallback_query = None
        fallback_description = None

    # Partial-fallback guard: query without description is a config error
    # (req-web-panel-entity-resolution-config-3).
    if fallback_query and not fallback_description:
        return EntityResolution(
            entity_id="",
            var_name=var_name,
            node=None,
            error="Fallback misconfigured: `description` is required when `query` is set.",
        )

    entity_id = (request.GET.get(var_name) or "").strip()

    if entity_id:
        try:
            node = _lookup_by_entity_id(entity_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[6504] Entity lookup failed for %s", entity_id)
            return EntityResolution(
                entity_id=entity_id,
                var_name=var_name,
                node=None,
                error=f"Entity lookup failed: {exc}",
            )
        if node is not None:
            return EntityResolution(
                entity_id=entity_id,
                var_name=var_name,
                node=node,
                error=None,
            )
        return EntityResolution(
            entity_id=entity_id,
            var_name=var_name,
            node=None,
            error=f"Entity not found for entity_id '{entity_id}'.",
        )

    if fallback_query:
        try:
            nodes, count = _run_fallback_query(fallback_query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ec3d] Fallback query failed: %s", fallback_query[:80])
            return EntityResolution(
                entity_id="",
                var_name=var_name,
                node=None,
                error=f"Fallback query failed: {exc}",
                fallback_description=fallback_description,
            )
        if count == 0:
            return EntityResolution(
                entity_id="",
                var_name=var_name,
                node=None,
                error=(
                    f"Fallback query returned no entities yet — {fallback_description}. "
                    f"Verify the underlying source has emitted at least one matching entity."
                ),
                fallback_description=fallback_description,
                fallback_count=0,
            )
        if count >= 2:
            return EntityResolution(
                entity_id="",
                var_name=var_name,
                node=None,
                error=(
                    f"Fallback ambiguous: query returned {count} entities — {fallback_description}. "
                    f"Refine the query (add `ORDER BY ... LIMIT 1` or tighten `WHERE`)."
                ),
                fallback_description=fallback_description,
                fallback_count=count,
            )
        node = nodes[0]
        resolved_id = node.get("entity_id") or ""
        return EntityResolution(
            entity_id=resolved_id,
            var_name=var_name,
            node=node,
            error=None,
            used_fallback=True,
            fallback_description=fallback_description,
            fallback_count=1,
        )

    return EntityResolution(
        entity_id="",
        var_name=var_name,
        node=None,
        error=f"No entity specified. Expected page variable '{var_name}' in the URL.",
    )
