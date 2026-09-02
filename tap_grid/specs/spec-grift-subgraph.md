# GRIFT Subgraph Specification

## Philosophy

GRIFT v0 defines a batch-oriented interchange document for moving graph data between files and grids. Many TAP systems, however, need to exchange graph data without a batch wrapper: searches, gryphon traversals, viewer graph context, graph panels, and future graph-native APIs.

GRIFT Subgraph defines that common contract.

> **Note:** [`spec-grift-envelope.md`](spec-grift-envelope.md) defines
> the canonical per-member envelope shape (spine surface, `data` lane,
> `display` lane). Section "Canonical Member Shape" and "Presentation
> Separation" below cross-reference it. This spec retains ownership of
> the outer `{nodes: [], edges: []}` container, the `lite` / `full` /
> `extended` return layer concept, wrapper envelopes, ordering, and the
> canonical implementation home in `tap_grid.grift`.

A GRIFT subgraph is the canonical batchless graph shape for TAP: a simple `nodes` and `edges` envelope whose members use the same full canonical node and edge shapes defined by GRIFT v0. This gives TAP one portable object contract for graph data while still allowing higher-level systems to add their own outer result metadata or presentation adapters.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Canonical     | TAP defines one standard node/edge member contract              |
| 2. | Reusable      | Searches, gryphon, web viewer context, and viz can share it     |
| 3. | Lightweight   | Subgraphs omit batch wrappers while preserving full object data |
| 4. | Strict        | Subgraph structure is schema-backed and stable                  |
| 5. | Layered       | Presentation metadata remains outside the canonical contract    |

## Terminology

- GRIFT subgraph: the canonical batchless graph envelope defined by this specification
- node member: one canonical node object in a subgraph `nodes` array
- edge member: one canonical edge object in a subgraph `edges` array
- full member shape: the canonical GRIFT-style nested member shape
- wrapper envelope: a higher-level result object that contains a subgraph plus other keys such as `info`, `warnings`, pagination metadata, or rendering metadata
- presentation adapter: a consumer-specific transform that derives UI-oriented fields from a canonical subgraph without redefining the underlying graph contract

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grift-subgraph-shape | [Subgraph Shape](#subgraph-shape) | Implemented | Canonical `nodes` / `edges` envelope |
| req-grift-subgraph-layers | [Return Layers](#return-layers) | Implemented | `lite`, `full`, and `extended` graph member layers |
| req-grift-subgraph-members | [Canonical Member Shape](#canonical-member-shape) | Implemented | Members reuse GRIFT node and edge objects |
| req-grift-subgraph-order | [Ordering](#ordering) | Implemented | Array order expresses graph member order |
| req-grift-subgraph-wrap | [Wrapper Envelopes](#wrapper-envelopes) | Implemented | Search/web/viz may wrap subgraphs without redefining members |
| req-grift-subgraph-present | [Presentation Separation](#presentation-separation) | Implemented | UI/view metadata is out of canonical scope |
| req-grift-subgraph-impl | [Implementation Home](#implementation-home) | Implemented | Canonical serializers and validators live in `tap_grid.grift` |

## JSON Schema

The canonical GRIFT subgraph schema is:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:tap:grift:v0:subgraph",
  "type": "object",
  "additionalProperties": false,
  "required": ["nodes", "edges"],
  "properties": {
    "nodes": {
      "type": "array",
      "items": {
        "$ref": "urn:tap:grift:v0:document#/$defs/GriftNodeObject"
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "$ref": "urn:tap:grift:v0:document#/$defs/GriftEdgeObject"
      }
    }
  }
}
```

This schema reuses the canonical GRIFT v0 node and edge member definitions.

## Subgraph Shape
----
RID: `req-grift-subgraph-shape`

Status: `Implemented`

A GRIFT subgraph is a JSON object with exactly these keys:

- `nodes`
- `edges`

Unknown keys are invalid at the canonical subgraph level.

Both arrays are always present, even when empty.

### Example

```json
{
  "nodes": [],
  "edges": []
}
```

## Return Layers
----
RID: `req-grift-subgraph-layers`

Status: `Implemented`

TAP should support three intentional subgraph return layers.

### `lite`

The `lite` layer carries only lightweight graph identity and relationship structure.

Intended use cases:

- fast neighborhood and traversal responses
- graph scans where full typed payloads are unnecessary
- lightweight intermediate graph contexts

In `lite` mode:

- node members carry entity-envelope data only
- edge members carry edge relationship data sufficient to describe the graph connection
- omitted canonical payload sections are not inferred

### `full`

The `full` layer carries the complete canonical GRIFT member shape.

Intended use cases:

- canonical subgraph responses
- interchange-oriented service responses
- any consumer that needs complete typed object data

In `full` mode:

- node members are full GRIFT node objects
- edge members are full GRIFT edge objects

`full` is the default and canonical subgraph return layer.

### `extended`

The `extended` layer carries `full` canonical graph data plus derived presentation or display metadata.

Intended use cases:

- web graph viewers
- graph panels
- table and navigation-oriented display helpers

Examples of extended fields:

- `icon_url`
- `shape`
- `url_id`
- display hints
- derived human-friendly endpoint labels

### Layering Rule

The layers are cumulative:

- `lite` is the smallest graph return layer
- `full` extends `lite`
- `extended` extends `full`

No layer may redefine the meaning of the fields provided by a lower layer.

## Canonical Member Shape
----
RID: `req-grift-subgraph-members`

Status: `Implemented`

Subgraph members are **envelopes** defined by
[`spec-grift-envelope`](spec-grift-envelope.md). Each entry in `nodes`
and each entry in `edges` is a canonical envelope: spine fields flat at
top, per-model fields in `data`, consumer-namespaced computed-for-render
in `display`. The same envelope shape applies to nodes and edges;
polymorphism lives entirely inside `data`.

### Node Members

Each item in `nodes` is a canonical envelope per
[req-grift-envelope-shape](spec-grift-envelope.md#envelope-shape). The
spec details the lane structure, ordering, and acceptance criteria.
Example (`full` layer):

```json
{
  "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
  "entity_type": "character",
  "name": "Frodo Baggins",
  "dimensions": {},
  "created_at": "2026-04-06T15:00:00Z",
  "updated_at": "2026-04-06T15:00:00Z",
  "deleted_at": null,
  "version": 1,
  "originating_grid_id": null,
  "data": {
    "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
    "name": "Frodo Baggins",
    "description": "",
    "bio": "A hobbit of the Shire who inherits the One Ring.",
    "batch_id": "...",
    "flip_map": {}
  }
}
```

### Edge Members

Each item in `edges` is a canonical envelope with the same lane
structure; `entity_type` is `"edge"` and the per-edge fields
(`from_entity_id`, `to_entity_id`, `edge_type`, `properties`) live in
`data`. See
[req-grift-envelope-edge-uniformity](spec-grift-envelope.md#edge-uniformity)
for the complete contract.

### Lite Member Guidance

In the `lite` layer, envelopes contain only the top-level spine surface
— no `data` or `display` lanes. The shape is the canonical envelope
with absent lanes. See [Layer Mapping in
spec-grift-envelope](spec-grift-envelope.md#layer-mapping).

## Ordering
----
RID: `req-grift-subgraph-order`

Status: `Implemented`

Member order is represented directly by JSON array order.

### Rules

- `nodes` array order expresses node ordering
- `edges` array order expresses edge ordering
- no secondary ordering structure is required in the canonical subgraph contract

Examples:

- alphabetized node results are represented by the order of `nodes`
- edge results ordered by type or creation time are represented by the order of `edges`

## Wrapper Envelopes
----
RID: `req-grift-subgraph-wrap`

Status: `Implemented`

Higher-level TAP systems may wrap a canonical subgraph in their own result envelope.

Examples:

- search may return:

```json
{
  "nodes": [...],
  "edges": [...],
  "info": {},
  "warnings": {}
}
```

- paginated search may return:

```json
{
  "count": 0,
  "limit": 25,
  "offset": 0,
  "results": {
    "nodes": [...],
    "edges": [...]
  }
}
```

### Rule

Wrapper envelopes may add outer metadata, but they must not redefine the canonical shape of node members or edge members.

## Presentation Separation
----
RID: `req-grift-subgraph-present`

Status: `Implemented`

Canonical graph data and presentation metadata are separate concerns.

The canonical envelope places presentation values in the **`display`
lane**, namespaced under consumer keys (`display.tap_viz.{...}` today;
future `display.tap_web_table`, `display.info_window`, etc.). The
`display` lane is opt-in via the `extended` return layer; the
canonical `full` layer carries only spine + `data`.

Computed-for-render values (icons, shapes, computed labels, URL slugs,
endpoint labels) are NOT promoted to the top level of the envelope.
They live inside `display.tap_viz.*`. See
[req-grift-envelope-display-lane](spec-grift-envelope.md#display-lane-rule).

The `extended` return layer may include such fields for runtime responses, but that does not make them part of the canonical `full` interchange contract.

### Rule

Systems that need presentation-friendly graph payloads should derive them from a canonical GRIFT subgraph rather than inventing a separate canonical graph serialization.

## Implementation Home
----
RID: `req-grift-subgraph-impl`

Status: `Implemented`

The canonical implementation home for GRIFT subgraph serialization and validation is `tap_grid.grift`.

Responsibilities that belong in `tap_grid.grift`:

- entity envelope serialization
- node member serialization
- edge member serialization
- subgraph serialization
- subgraph structural validation
- reuse of GRIFT member validators across file import and service/search graph responses

Responsibilities that do not belong in `tap_grid.grift`:

- search pagination metadata
- search execution timing or warnings packaging
- web viewer context assembly
- graph-panel Cytoscape shaping
- table-oriented flattening or row navigation helpers

### Development

This keeps TAP's canonical graph interchange logic in one place. Search, gryphon, web, and viz should call into `tap_grid.grift` for canonical graph data rather than maintaining parallel serializers.

## Future

- **Layer naming: `lite` / `full` / `extended`.** The names date from
  before the envelope shape work and don't strongly communicate what
  changes between them (e.g. `lite` could be "lightweight" or
  "low-detail"; `extended` is "extended beyond what?"). Worth a
  revisit. They define the boundaries in `tap_grid.grift.subgraph`'s
  `SubgraphLayer` type and the `layer` parameter on `execute_search`
  and `serialize_subgraph`. If renamed, the affected surface is small
  and localized: that type, those parameters, and the layer mapping
  table in [`spec-grift-envelope`
  § Layer Mapping](spec-grift-envelope.md#layer-mapping). The current
  names are kept for now (no demand signal to rename mid-stream); this
  note marks them as candidates for a future pass.
