"""GRIFT — Grid Interchange Format for TAP.

This package provides:
  - **Importer** (``tap_grid.grift.importer``): parse, validate, and import
    GRIFT v0 documents into the local TAP grid.
  - **Subgraph** (``tap_grid.grift.subgraph``): canonical serializers for
    GRIFT subgraph envelopes (lite / full / extended layers).

Re-exports from importer keep existing ``from tap_grid.grift import ...``
call sites working without changes.
"""

# Importer re-exports (backward compatible).
# Envelope parse-and-split (write path; spec-grift-envelope § Envelope Validation).
from tap_grid.grift.envelope import (
    EnvelopeValidationError,
    SplitPayload,
    parse_envelope_for_write,
)
from tap_grid.grift.importer import (
    GRIFT_VERSION,
    IMPORT_MODE,
    GriftCounts,
    GriftImportedBatch,
    GriftImportResult,
    GriftIssue,
    GriftSkippedBatch,
    collector_derivation_scope,
    grift_import,
    validate_grift_document,
)

# Subgraph public API — envelope shape per spec-grift-envelope.
from tap_grid.grift.subgraph import (
    SubgraphLayer,
    batch_resolve_display,
    batch_resolve_entity_names,
    batch_resolve_icon_urls,
    batch_resolve_typed_models,
    build_data_lane,
    build_display_lane,
    build_spine_surface,
    serialize_edge_extended,
    serialize_edge_full,
    serialize_edge_lite,
    serialize_entity_envelope,  # alias for build_spine_surface (back-compat)
    serialize_node_extended,
    serialize_node_full,
    serialize_node_lite,
    serialize_subgraph,
)

__all__ = [
    # Importer
    "GRIFT_VERSION",
    "IMPORT_MODE",
    "GriftCounts",
    "GriftImportedBatch",
    "GriftImportResult",
    "GriftIssue",
    "GriftSkippedBatch",
    "collector_derivation_scope",
    "grift_import",
    "validate_grift_document",
    # Envelope parse / write-path
    "EnvelopeValidationError",
    "SplitPayload",
    "parse_envelope_for_write",
    # Subgraph / envelope
    "SubgraphLayer",
    "batch_resolve_display",
    "batch_resolve_entity_names",
    "batch_resolve_icon_urls",
    "batch_resolve_typed_models",
    "build_data_lane",
    "build_display_lane",
    "build_spine_surface",
    "serialize_edge_extended",
    "serialize_edge_full",
    "serialize_edge_lite",
    "serialize_entity_envelope",
    "serialize_node_extended",
    "serialize_node_full",
    "serialize_node_lite",
    "serialize_subgraph",
]
