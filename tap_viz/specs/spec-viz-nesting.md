# Viz Nesting Specification

## Philosophy

Viz nesting is a TAP Viz runtime utility for resolving which graph entities should be visually contained inside one another. Nesting is not the core architectural source of truth for how TAP scenes are built. Under the current model, projections orchestrate, tap layouts decide, and nesting utilities assist.

Nesting is primarily a layout-time rendering tactic. A tap layout may choose to nest objects for one scene and represent the same objects differently in another scene. The nesting system therefore exists to provide reusable runtime helpers: relationship parsing, parent-child resolution, edge matching, cycle detection, and hidden containment edge handling.

Under the bounded-layer nested projection model (see `spec-viz-nested-projection.md`), resolved nesting relationships are expressed as positional containment rather than Cytoscape compound-node assignments. The resolver produces the same logical output (which nodes go inside which parents), but the runtime applies that information by positioning children within parent bounding boxes rather than setting Cytoscape `.parent()`. This change is transparent to most nesting utilities — the resolver logic and edge hiding are unchanged; only the application step differs.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Reusable | Nesting resolution is available as runtime support reusable across layouts. |
| 2. | Local | Nesting decisions are made by specific tap layouts rather than imposed globally. |
| 3. | Safe | The nesting resolver detects ambiguity and cycles and emits warnings rather than failing silently. |
| 4. | Bounded Layer Aligned | Nesting output integrates with the bounded-layer model (data stamps, not compound parents). |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-nesting-gryphon-subset | [Nesting Gryphon Subset](#nesting-gryphon-subset) | Proposed | Exact supported matcher syntax for nesting utilities |
| req-viz-nesting-layout-process | [Layout-Owned Nesting Process](#layout-owned-nesting-process) | Proposed | Tap layouts declare nesting relationships; runtime resolves and applies them |
| req-viz-nesting-resolver | [Nesting Resolver Utility](#nesting-resolver-utility) | Proposed | Resolver produces parent-child assignments from edge matching |
| req-viz-nesting-hidden-edges | [Hidden Containment Edges](#hidden-containment-edges) | Proposed | Consumed containment edges remain in Cytoscape but are hidden |
| req-viz-nesting-warnings | [Warning Categories](#warning-categories) | Proposed | Normative warning categories for nesting/runtime oddities |
| req-viz-nesting-parent-label-rendering | [Parent Label Rendering](#parent-label-rendering) | Deprecated | DOM overlay approach deprecated in favor of native Cytoscape label styling via `.tap-viewport-parent` |
| req-viz-nesting-parent-label-metadata | [Parent Label Metadata](#parent-label-metadata) | Deprecated | Model-level label hints deprecated along with DOM overlay |
| req-viz-nesting-model-hints | [Model-Level Nesting Hints](#model-level-nesting-hints) | Deprecated | Model-level nesting metadata deprecated in favor of layout-owned nesting |

## Requirements

### Nesting Gryphon Subset
----
RID: `req-viz-nesting-gryphon-subset`

Status: `Proposed`

Nesting utilities use a restricted Gryphon subset for expressing parent-child relationships.

#### Implementation

The supported matcher form is exactly one directed single-hop pattern:

```text
(parent[:label])-[:EDGE_TYPE]->(child[:label])
(parent[:label])<-[:EDGE_TYPE]-(child[:label])
```

Rules:

- exactly one pattern is allowed
- exactly one directed hop is allowed
- the node variable names `parent` and `child` are required
- the edge variable is optional
- the edge type is required
- node labels are optional
- any Gryphon outside this subset is invalid for nesting utility resolution

Accepted examples:

```text
(parent:realm)-[:CONTAINS]->(child:location)
```

```text
(parent:location)<-[:LOCATED_IN]-(child:character)
```

```text
(parent:character)-[:WIELDS]->(child:artifact)
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nesting-gryphon-subset-1 | Single-Hop Directed Pattern Only | Proposed | Nesting matchers accept exactly one directed single-hop pattern. | |
| req-viz-nesting-gryphon-subset-2 | Parent And Child Variables Required | Proposed | The node variable names must be `parent` and `child`. | |
| req-viz-nesting-gryphon-subset-3 | Edge Type Required | Proposed | The edge type must be specified for nesting resolution. | |
| req-viz-nesting-gryphon-subset-4 | Unsupported Syntax Rejected | Proposed | Any matcher outside the accepted subset is rejected and warned. | |

#### Future

Consider broader in-memory Gryphon support if layouts need richer relationship matching.


### Layout-Owned Nesting Process
----
RID: `req-viz-nesting-layout-process`

Status: `Proposed`

Tap layouts own nesting decisions and declare them through the `projectNested` runtime API or directly through the resolver.

#### Implementation

Nesting relationships are declared as part of the `projectNested` config (see `spec-viz-nested-projection.md`). The canonical relationship shape within that config is:

```javascript
{
  relationships: [
    {
      name: "realm-contains-location",
      gryphon: "(parent:realm)-[:CONTAINS]->(child:location)"
    },
    {
      name: "location-contains-character",
      gryphon: "(parent:location)<-[:LOCATED_IN]-(child:character)"
    }
  ]
}
```

Multiple nesting relationships may be declared in one call. The runtime processes them in order.

Layouts that need resolver output without the full `projectNested` geometry pipeline may call the resolver directly for inspection or custom behavior.

#### Development

This keeps nesting consistent without returning to the old model-driven architecture. Layouts stay authoritative, but they use one standard nesting expression format.

#### Future

Add additional layout-owned nesting controls only when real layouts prove they are needed.


### Nesting Resolver Utility
----
RID: `req-viz-nesting-resolver`

Status: `Proposed`

The nesting resolver resolves candidate parent-child assignments from graph edges and relationship declarations.

#### Implementation

The resolver's core behavior is:

1. parse supported nesting relationship matchers (Gryphon subset)
2. match Cytoscape graph edges against those relationships
3. collect candidate parents per child
4. accept single-parent assignments
5. reject ambiguous children (multiple candidate parents)
6. detect cycles and drop participating assignments
7. return accepted parent relationships plus hidden containment edge identities

The resolver produces:

- `parentByChildId` — map of child node id → parent node id
- `hiddenEdgeIds` — set of edge ids consumed for containment
- `warnings` — array of warning objects with `category` and `message`

Under the bounded-layer model, the resolver's output is used to:
- stamp `_viewport_parent` data on child nodes
- hide consumed edges via `.tap-hidden-containment` class
- inform the recursive-descent viewport projection

The resolver does NOT set Cytoscape compound parents (no `.parent()` calls, no `parent` data field).

#### Development

This keeps the useful parts of the nesting implementation (pattern matching, ambiguity detection, cycle prevention) while aligning with the bounded-layer model.

#### Future

Move the resolver into the `nested-projection.js` module or keep it as a standalone utility depending on whether non-projection use cases emerge.


### Hidden Containment Edges
----
RID: `req-viz-nesting-hidden-edges`

Status: `Proposed`

Edges consumed as accepted containment relationships remain in Cytoscape but are hidden from visual display.

#### Implementation

When an edge participates in an accepted parent-child assignment:

- the edge remains present in Cytoscape
- the edge is marked with the `.tap-hidden-containment` class
- the edge is not shown in the normal rendered graph (style rule: `display: none`)

Only edges consumed for accepted parent-child assignments are hidden. If an edge could have implied containment but the assignment was rejected, that edge remains visually available.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nesting-hidden-edges-1 | Consumed Edges Stay In Cytoscape | Proposed | Edges used for accepted nesting remain in the Cytoscape element set. | |
| req-viz-nesting-hidden-edges-2 | Consumed Edges Hidden By Class | Proposed | Accepted containment edges are hidden via `.tap-hidden-containment` class. | |
| req-viz-nesting-hidden-edges-3 | Rejected Assignments Leave Edges Visible | Proposed | A rejected containment assignment does not hide the edge that suggested it. | |

#### Future

Define standardized runtime affordances for temporarily showing hidden containment edges during debugging or inspection.


### Warning Categories
----
RID: `req-viz-nesting-warnings`

Status: `Proposed`

Nesting runtime utilities emit normative warning categories for invalid or ambiguous nesting behavior.

#### Implementation

The warning categories are:

- `unsupported_matcher_syntax`
- `multiple_parents`
- `cycle_detected`
- `layout_nesting_override`
- `overfill`

Category meanings:

- `unsupported_matcher_syntax`
  A nesting matcher is outside the supported Gryphon subset.
- `multiple_parents`
  More than one distinct parent was proposed for the same child.
- `cycle_detected`
  Accepted parent-child assignments would create a cycle.
- `layout_nesting_override`
  A layout changed an existing nesting relationship and re-nested an object elsewhere.
- `overfill`
  Children cannot fit within the parent viewport at any reasonable scale.

#### Future

Integrate nesting warnings into TAP's richer runtime diagnostics once those systems are defined.


### Parent Label Rendering
----
RID: `req-viz-nesting-parent-label-rendering`

Status: `Deprecated`

#### Status Details

The DOM overlay approach for parent labels (`TapParentLabelOverlay`) is deprecated. Under the bounded-layer model, parent nodes that host children receive the `.tap-viewport-parent` class and use native Cytoscape label positioning (`text-valign: top`) rather than a separate HTML overlay system.

This eliminates:
- DOM element lifecycle management
- Pan/zoom transform synchronization
- Stale wrapper cleanup
- The disconnect between Cytoscape node interaction and overlay positioning

See `req-viz-nested-projection-container-visual` in `spec-viz-nested-projection.md` for the replacement approach.


### Parent Label Metadata
----
RID: `req-viz-nesting-parent-label-metadata`

Status: `Deprecated`

#### Status Details

Model-level parent-label metadata hints are deprecated along with the DOM overlay system they were designed to configure. Label positioning for viewport parents is now controlled by the `.tap-viewport-parent` style rules in the graph panel stylesheet.


### Model-Level Nesting Hints
----
RID: `req-viz-nesting-model-hints`

Status: `Deprecated`

Model-level nesting metadata is deprecated in favor of layout-owned nesting.

#### Implementation

Model-level metadata such as:

- `DEFAULT_DISPLAY["tap_viz"]["nesting"]["parent"]`
- `DEFAULT_DISPLAY["tap_viz"]["nesting"]["child"]`

may still exist in the codebase during migration, but it is no longer the preferred or normative way to define nesting behavior. Layouts define their own nesting relationships explicitly through `projectNested`.


---

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development |  |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated |  |
