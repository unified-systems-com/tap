# Viz Elevation Specification

## Philosophy

An elevation is a named zoom-driven stage within a projection — the visual altitude the viewer is at. It is the layer at which a projection chooses *what* the scene should look like for a given zoom band. Elevations compose one or more layouts that together produce the scene at that altitude.

In v0, elevation was an inline object inside a projection's `definition.elevations[]` array. v1 promotes Elevation to a first-class TAP-managed entity that a projection references via the `USES_ELEVATION` hotlink. The elevation owns its zoom threshold, its layout composition (`USES_LAYOUT`), and its navigation targets (`NAVIGATES_TO`), all as graph relationships rather than inline name-keyed config.

Elevations as entities give us three things: layouts can be addressed and reused across elevations, the default-elevation relationship is queryable as a typed edge rather than a string lookup, and double-tap targets become real entity references instead of name strings. A grift sweep, an audit, or a gryphon query can walk the entire projection-to-arrangement chain through the graph.

The runtime behavior of elevations — zoom-threshold watching, double-tap pan-zoom animation, hysteresis after commanded transitions — is orchestrated by the projection runtime (see `spec-viz-projection.md`). This spec defines the elevation entity, its definition shape, and its hotlinks; it does not redefine runtime activation semantics.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | First-Class Entity | Elevations are TAP-managed entities with their own lifecycle, addressable and reusable. |
| 2. | Zoom Driven | Each elevation declares the zoom threshold at which it becomes the active stage. |
| 3. | Layout Composing | An elevation orchestrates an ordered list of Layout entities via `USES_LAYOUT`. |
| 4. | Navigable | Double-tap targets are typed entity references via `NAVIGATES_TO`, not name strings. |
| 5. | Reusable | The same elevation entity may be referenced by multiple projections when its scene logic generalizes. |
| 6. | Validated | The hotlink system enforces consistency between the elevation's `definition` references and its outbound edges. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-elevation-model | [Elevation Model](#elevation-model) | Implemented | Elevation as a TAP-managed BaseModel entity in `tap_viz` |
| req-viz-elevation-definition | [Elevation Definition](#elevation-definition) | Implemented | JSON definition shape: zoom, description, layouts, double_tap_targets |
| req-viz-elevation-uses-layout-hotlink | [USES_LAYOUT Hotlink](#uses_layout-hotlink) | Implemented | Ordered Layout-entity references; runs in array order |
| req-viz-elevation-navigates-to-hotlink | [NAVIGATES_TO Hotlink](#navigates_to-hotlink) | Implemented | Double-tap target references resolve to Elevation entities |
| req-viz-elevation-no-default-layout | [No Default Layout Concept](#no-default-layout-concept) | Implemented | All `USES_LAYOUT` layouts compose; there is no "default layout" under an elevation |

## Requirements

### Elevation Model
----
RID: `req-viz-elevation-model`

Status: `Implemented`

An elevation is a TAP-managed entity that names a zoom-driven stage and orchestrates the layouts active at that altitude.

#### Implementation

`Elevation` is a `BaseModel` subclass in `tap_viz` with `ENTITY_TYPE = "elevation"`.

Fields:

- `name` — `CharField(max_length=255)`, required on create.
- `description` — `TextField(blank=True, default="")`.
- `definition` — `JSONField(default=dict, blank=True)`. Stores the elevation's structural payload (see [Elevation Definition](#elevation-definition)).

The model declares `FIELD_CRUD_SCHEMA`, `CREATE_REQUIRED`, and `FIELD_VALIDATION_SCHEMA` consistent with Layout, Projection, and Arrangement.

#### Development

Promoting elevation from inline projection config to an entity is the move that makes the rest of the projection-to-arrangement chain queryable as a graph. Once an elevation has its own entity_id, every USES_*  edge above and below it carries real semantic weight.

#### Future

If multiple projections start sharing the same elevation entity widely, consider per-projection override edges (e.g. `OVERRIDES_ZOOM` with edge properties) rather than forking the elevation. Hold off until real reuse pressure shows up.


### Elevation Definition
----
RID: `req-viz-elevation-definition`

Status: `Implemented`

The elevation `definition` JSON describes the zoom threshold, layout composition, and navigation targets.

#### Implementation

The v0 definition shape:

```json
{
  "zoom": 0.6,
  "description": "Inside-the-EC2-instance internal view.",
  "layouts": [
    "<layout-entity-id-1>",
    "<layout-entity-id-2>"
  ],
  "double_tap_targets": [
    {
      "entity_type": "aws_ec2_instance",
      "target_elevation_id": "<elevation-entity-id>"
    }
  ]
}
```

Top-level keys:

- `zoom` — number; the zoom level at which the elevation becomes active. Required.
- `description` — string; optional human-readable purpose.
- `layouts` — array of UUIDs; ordered list of Layout entities composed at this elevation. Validated by [USES_LAYOUT Hotlink](#uses_layout-hotlink). Empty arrays are valid (a no-layout elevation is unusual but legal).
- `double_tap_targets` — array of `{entity_type, target_elevation_id}` objects. Each `target_elevation_id` must point at an Elevation entity reachable from the same projection. Validated by [NAVIGATES_TO Hotlink](#navigates_to-hotlink).

`FIELD_VALIDATION_SCHEMA` validates this shape via JSON Schema.

#### Development

Splitting `layouts` and `double_tap_targets` into their own typed hotlinks — rather than packing both into a single `USES_*` relation — keeps each edge type semantically meaningful. A grift sweep that asks "what layouts does this elevation compose?" answers cleanly with one edge type; "where can this elevation jump to?" answers with another.

#### Future

- Add an `enter_action` hook (gryphon query, runtime callback) when projections need to react to elevation activation beyond the layouts.
- Allow elevations to declare a `min_zoom_below`/`max_zoom_above` range explicitly when threshold-only activation proves insufficient for complex projections.


### USES_LAYOUT Hotlink
----
RID: `req-viz-elevation-uses-layout-hotlink`

Status: `Implemented`

Elevations reference layouts via an ordered array of entity IDs in their `definition.layouts`, validated by the hotlink system.

#### Implementation

The Elevation model declares:

```python
HOTLINKS: ClassVar[list[dict]] = [
    {
        "name": "elevation-layouts",
        "field": "definition",
        "selector_type": "simple_path",
        "selector": "layouts.*",
        "edge_direction": "outbound",
        "edge_type": "USES_LAYOUT",
        "mode": "exact",
    },
    # NAVIGATES_TO hotlink declared in req-viz-elevation-navigates-to-hotlink
]
```

This creates `USES_LAYOUT` edges from the elevation entity to each referenced Layout entity. The hotlink system validates that every entity ID in the `layouts` array has a corresponding edge and vice versa.

The array order is the execution order. The hotlink validates presence and completeness; the array defines sequence.

At runtime, the projection runtime resolves the elevation's layouts in order and runs each via the layout-runner contract defined in [spec-viz-layouts.md](spec-viz-layouts.md).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-elevation-uses-layout-hotlink-1 | Hotlink validates exact match | Implemented | The hotlink fails save when `definition.layouts` and the `USES_LAYOUT` edge set diverge. | |
| req-viz-elevation-uses-layout-hotlink-2 | Order preserved | Implemented | Layouts run in the array order declared in `definition.layouts`, not edge insertion order. | |


### NAVIGATES_TO Hotlink
----
RID: `req-viz-elevation-navigates-to-hotlink`

Status: `Implemented`

Double-tap targets reference other elevations via typed `NAVIGATES_TO` edges, validated as a hotlink.

#### Implementation

The Elevation model declares a hotlink against the `double_tap_targets` array's `target_elevation_id` field:

```python
{
    "name": "elevation-navigates-to",
    "field": "definition",
    "selector_type": "simple_path",
    "selector": "double_tap_targets.*.target_elevation_id",
    "edge_direction": "outbound",
    "edge_type": "NAVIGATES_TO",
    "mode": "exact",
},
```

This creates `NAVIGATES_TO` edges from the elevation to each target elevation referenced by a double-tap rule. The runtime resolves these edges (or equivalently the `target_elevation_id` field) when handling a double-tap event.

The `entity_type` field of each `double_tap_targets[]` entry is data, not a graph relationship — it stays in the JSON `definition` and is read at runtime to dispatch on the tapped node's type.

#### Development

`NAVIGATES_TO` reads better than another `USES_*` here because it expresses a *runtime navigation* relationship rather than a *composition* relationship. Composition is what `USES_*` is for: "this entity is built from these other entities". Navigation is "from here you can jump to there at runtime, conditionally". Different semantics, different edge type.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-elevation-navigates-to-hotlink-1 | Hotlink validates exact match | Implemented | The hotlink fails save when `target_elevation_id` set and `NAVIGATES_TO` edge set diverge. | |
| req-viz-elevation-navigates-to-hotlink-2 | Targets reachable from same projection | Implemented | Cross-hotlink validator on the projection ensures every `NAVIGATES_TO` target also appears in the projection's `USES_ELEVATION` set. | Validator lives on `Projection.validate()`; see `spec-viz-projection.md`. |


### No Default Layout Concept
----
RID: `req-viz-elevation-no-default-layout`

Status: `Implemented`

An elevation has no "default layout". All layouts in `definition.layouts` compose; they all run in declared order on every entry.

#### Implementation

There is no `USES_DEFAULT_LAYOUT` analogue to `USES_DEFAULT_ELEVATION`. The runtime always runs every layout the elevation references. Conditional behavior (different layouts in different contexts) belongs inside an individual layout's logic, not as a default-vs-non-default selector at the elevation level.

#### Development

Default-elevation exists at the projection level because a projection has to *land somewhere* on initial load — there's a single entry point. An elevation has no analogous "single entry layout"; entering an elevation runs everything it composes. Keeping this asymmetry explicit avoids inviting the question "which of my layouts is the default?" — the answer is "all of them, in order".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-elevation-no-default-layout-1 | All layouts run | Implemented | The runtime runs every Layout in `USES_LAYOUT` order; no per-context layout selection. | |


## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
