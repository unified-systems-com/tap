"""Core-registered standard edge types owned by the grid itself.

Most edge types are declared by the plugin (or node) that owns the
relationship — via a plugin `edge_types` manifest or a node's
`OUTBOUND_EDGES`/`INBOUND_EDGES`. A small number of relationships are
*grid-standard*: uniform everywhere, owned by tap_grid core, not by any one
plugin or node type. Those are registered here and called from
`TapCoreConfig.ready()`.

Currently just `PRODUCED_BATCH` (`req-grid-edge-produced-batch`,
`tap_grid/specs/spec-grid-edge.md`): the canonical producer -> `Batch` edge.
Any code that generates a `Batch` (collectors, GRIFT-import callers, future
ingestion surfaces) relates the producing record to the resulting `Batch`
through this edge rather than embedding batch ids in producer-local JSON.
"""

from __future__ import annotations

from typing import Any

#: The grid-standard edge types core itself defines (no plugin suffix). The one list both
#: the boot-time edge-declaration check and validate_plugin treat as always-defined.
CORE_EDGE_TYPES: tuple[str, ...] = ("PRODUCED_BATCH",)

# disposition ∈ {imported, skipped}: imported = the producer wrote this batch
# on this run; skipped = the importer skipped it as already-present/idempotent.
# additionalProperties is left open (req-grid-edge-properties-9) so producers
# may extend with their own validated properties.
PRODUCED_BATCH_PROPERTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["imported", "skipped"]},
    },
    "required": ["disposition"],
}

# A plain key: a PRODUCED_BATCH edge is identified by (producer, batch) alone
# (req-grid-edge-produced-batch-claims-1). Not keyless: a repeat within one job is the same
# relationship and collapses to one edge, and `disposition` is state on it, never a second key.
PRODUCED_BATCH_IDENTITY: dict[str, Any] = {"discriminators": []}


def register_core_edges() -> None:
    """Register grid-standard edge types. Idempotent — safe to call repeatedly.

    Called from `TapCoreConfig.ready()`. Guarded with the registry's
    `get_*` lookups because the property-schema registry raises on a
    duplicate registration (no merge behavior), and `ready()` may run more
    than once across a process's test lifecycle.
    """
    from tap_grid.constraints import (
        get_edge_property_schema,
        get_edge_type_constraints,
        is_internal_edge_type,
        register_edge_internal_only,
        register_edge_property_schema,
        register_edge_type_constraints,
    )
    from tap_grid.edge_identity import get_edge_identity, register_edge_identity

    # PRODUCED_BATCH: producer -> batch. Target is always `batch`; source is
    # open by design (any producer entity type may originate one).
    if get_edge_type_constraints("PRODUCED_BATCH") is None:
        register_edge_type_constraints(
            "PRODUCED_BATCH",
            sources=None,  # WILDCARD — open source set
            targets=[{"type": "batch"}],
        )
    if get_edge_property_schema("PRODUCED_BATCH") is None:
        register_edge_property_schema("PRODUCED_BATCH", PRODUCED_BATCH_PROPERTY_SCHEMA)
    if get_edge_identity("PRODUCED_BATCH") is None:
        register_edge_identity(
            "PRODUCED_BATCH", PRODUCED_BATCH_IDENTITY, property_schema=PRODUCED_BATCH_PROPERTY_SCHEMA
        )
    # Bookkeeping a run writes about itself, read by reconcile: only the claims path writes it
    # (req-grid-edge-internal, req-grid-edge-produced-batch-claims-5).
    if not is_internal_edge_type("PRODUCED_BATCH"):
        register_edge_internal_only("PRODUCED_BATCH")
