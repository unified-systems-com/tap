# tap_grid Design

## Purpose

tap_grid defines the foundational data model and graph contracts: Entity, Edge, EntityType, BaseModel, User, graph query surfaces, and canonical graph interchange helpers.

## Key Decisions

**Entity PK = UUIDv7.** Entity's ID IS the UUID (`UUIDField(primary_key=True)`). No separate BigAutoField. UUIDv7 is time-ordered so B-tree index performance is fine. 16 bytes vs 8 bytes is worth the architectural simplicity.

**Edges are Entities.** Edge inherits BaseModel, which gives it a OneToOneField to Entity. Edges are first-class objects that can be referenced, federated, and traversed like any other entity. "No edges between edges" is enforced at the service layer, not the schema — we don't have a grounded philosophical argument to prevent it structurally.

**entity_type is a CharField, not an FK.** Entity.entity_type stores a plain string (e.g., "server"). EntityType is a separate registry table that plugins populate. The connection is logical, not relational — validated at the service layer. This decouples Entity from the plugin system at the DB level and keeps queries fast.

**display_name on Entity, icon on EntityType.** Names are per-instance ("prod-web-01"), icons are per-type (all servers share an icon).

**BaseModel includes the Entity FK.** Every domain ORM model inherits BaseModel, which provides the OneToOneField to Entity plus timestamps and originating_grid_id. The `related_name="%(class)s"` pattern enables `entity.server`, `entity.edge`, etc.

**originating_grid_id is nullable.** Allows the system to function before a Grid ID is configured. Stored as a native UUID type (16 bytes) rather than a 36-char string.

**Edge properties via JSONField.** Lightweight metadata (weight, confidence, notes) without premature schema design. Plugins can promote hot fields to columns later.

**No unique constraint on Edge.** Multiple edges of the same type between entities are valid. Uniqueness enforced at service layer if needed.

**Environment deferred.** It is a tap_flip concern (step 6). BaseModel is the extension point. Realms are retired (unified-systems-com/tap#1355): a key that needs scoping names an identity-bearing dimension (`usable_in_keys`, `req-grid-dimension-knobs-3`), never a generic realm field.

**Gryphon is the graph-native read language.** Traversal- and neighborhood-oriented read behavior should be expressed through TAP search execution, with Gryphon as the graph query surface for read-only graph retrieval.

**GRIFT is the canonical graph interchange contract.** Portable node/edge serialization, subgraph serialization, and graph interchange should converge on GRIFT-defined envelopes and member shapes rather than parallel app-specific serializers.


## Edge Constraints

Constraints define which edge types can connect which node types. They are enforced at edge creation with zero database lookups.

### Constraint Definition

Domain models define constraints as class attributes using object syntax for future extensibility:

```python
from typing import Any, ClassVar

class Concept(BaseModel):
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "concept"}, {"type": "precept"}],
            "edges": [{"type": "APPLIES_TO"}],
        },
        {
            "nodes": [{"type": "concept"}],
            "edges": [{"type": "DEPENDS_ON"}],
        },
    ]

    INBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "concept"}],
            "edges": [{"type": "APPLIES_TO"}, {"type": "DEPENDS_ON"}],
        },
    ]
```

**Naming convention:** Edge types use ALL CAPS (`APPLIES_TO`), node types use lowercase (`concept`).

### Constraint Semantics

| Definition | Meaning |
|------------|---------|
| No `OUTBOUND_EDGES` attribute | No restrictions — any edge type to any target |
| `OUTBOUND_EDGES = []` | No outbound edges allowed from this node type |
| `[{"nodes": [...], "edges": [...]}]` | Only listed edges to listed node types |
| `[{"edges": [...]}]` (no `nodes` key) | Wildcard — listed edges can connect to any node type |

Same semantics apply to `INBOUND_EDGES` for controlling what can point TO a node.

### Registration

Constraints are auto-registered via `BaseModel.__init_subclass__` when the model class is defined. They're parsed into fast lookup dicts in `tap_grid.constraints._REGISTRY`.

### Validation

`create_edge()` in `tap_grid.services` calls `validate_edge()` before any DB writes. Violations raise `InvalidEdgeError`, which the API layer catches and returns as 400 Bad Request.

### Object Syntax

The `{"type": "..."}` structure (rather than plain strings) enables future extensions without breaking changes:

```python
# Future: regex matching, metadata constraints
"nodes": [{"type": "*.continent", "match": "regex"}]
"edges": [{"type": "LIVES_ON", "metadata_match": "region_key"}]
```


## Future Features DO NOT IMPLEMENT
**Compound Nodes** Edges that have a node in between them.
**Quick-sort for outbound node lookup** Take the outbound object in the model and store it in a quick-lookup data structure like a b-tree that can make identifying which nodes and edges it can form outbound connections too faster than the lookup table I initially proposed.


## What Lives Here vs Other Apps

- **tap_grid**: Entity, Edge, EntityType, BaseModel, User, Grid identity, graph search execution, Gryphon, GRIFT canonical graph serialization/interchange
- **tap_plugins**: Type registration, plugin discovery, plugin-defined domain models
- **tap_api**: API routing, versioning, auth middleware
- **tap_web**: Templates, static assets, dashboards
- **tap_viz**: Cytoscape, graph visualization
- **tap_flip**: Provenance, history, environments
- **tap_ai**: RAG surfaces, summarization, suggestions
