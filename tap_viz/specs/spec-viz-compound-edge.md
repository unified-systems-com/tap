# Viz Compound Edge Specification

## Philosophy

A **compound edge** is stored on the grid as a middle node and two or more ordinary edges: a source edge from the sender into the middle node, a destination edge from the middle node to the receiver, and optionally a carrier edge and path edges out of it (`req-grid-edge-compound`, `tap_grid/specs/spec-grid-edge.md`). That is the right shape for storing it, because the middle has an identity, fields and its own edges. It is the wrong shape for reading a page: someone looking at a system wants to see that the internet can reach this interface, as one arrow, and to open the detail only when they ask.

So the viz layer draws a compound edge as **one arrow from sender to receiver**, and expands it into the stored pieces on tap. The arrow is the one line on a TAP page that is not itself an edge in the grid. That is allowed, as an amendment to the icon-node rule (`req-viz-icon-node-edges`), because it stands for pieces that all exist, between exactly the two real ends it joins, and because it is marked and can be opened.

Like the stack, it is a **runtime primitive**, not a projection-level style: a layout module calls `applyCompoundEdges(cy, opts)` from `execute(context)` after it has positioned the scene, and the call composes with nesting, icon nodes and stacks rather than replacing them.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Arrow | A compound edge reads as one arrow from sender to receiver. |
| 2. | Honest | The arrow joins the compound edge's real ends, is marked as synthetic, and never stands in for a hidden end. |
| 3. | Expandable | A tap opens the stored pieces; a tap on the opened middle node closes them. |
| 4. | Declared Once | The role edges come from the middle type's `COMPOUND_EDGE` declaration, not from the layout. |
| 5. | Idempotent | Safe to re-run across elevation transitions; `destroy()` restores the scene. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-compound-edge | [Compound Edge As One Arrow](#compound-edge-as-one-arrow) | Implemented | `applyCompoundEdges(cy, opts)` in `runtime/compound-edge.js`: hide the middle node and its role edges, draw one synthetic arrow, expand on tap |

## Requirements

### Compound Edge As One Arrow
----
RID: `req-viz-compound-edge`

Status: `Implemented`

`tap_viz/static/tap_viz/js/runtime/compound-edge.js` exports `applyCompoundEdges(cy, opts)` and the class name `tap-compound-collapsed`, which the graph panel's stylesheet hides with its other hidden classes.

#### Implementation

**Which nodes.** A node is a middle node when its data carries `compound_edge`, the role → edge-type map (`source`, `destination`, and `carrier` / `path` when declared). The graph panel copies it from the envelope's display lane, where the server computes it from the type's `COMPOUND_EDGE` declaration (`req-viz-system-display-hints-11`), so a layout never restates the roles. `opts.types` narrows the pass to listed middle-node entity types; omitted, every middle node in the scene is a candidate. A middle node that is already hidden (by an elevation, a stack, nesting or an icon node) is left alone.

**Collapse.** For each candidate whose sender and receiver are both drawn, the middle node and its role edges get `tap-compound-collapsed`. A role edge is recognised by type and direction: the source edge points into the middle node, every other role points out of it. One synthetic edge is added from each drawn sender to each drawn receiver (one pair in practice), with `_is_compound_edge: true`, `_compound_id` (the middle node's id), `_compound_handle`, and the middle node's label as its label. The panel styles it heavier than a plain edge, so it reads as marked.

**An end that is not drawn.** When the sender or the receiver is absent from the scene or hidden, nothing is drawn in its place and nothing is re-pointed onto a node that stands in for it (the icon-node rule). The compound edge is left expanded: the middle node shows as the ordinary node it is, with whatever real edges are drawable. The handle lists such middle nodes in `skipped`.

**Expand and collapse.** A tap on the synthetic arrow removes it and shows the middle node and its role edges. A tap on a middle node that this handle expanded collapses it again. The handle also exposes `expand(id)` and `collapse(id)`. The panel's click semantics name this as the one edge tap that acts (`req-viz-panel-click-semantics-6`).

**Re-run and destroy.** A call tears down any earlier pass with the same handle id (`opts.id`, default `compound`) before applying, so re-running across elevation transitions never adds a second arrow. `destroy()` removes the synthetic arrows, the handle's tap listeners and the class it set, and leaves classes set by anything else in place.

#### Development
Modelled on the stack runtime (`runtime/stack.js`, `spec-viz-stack.md`), which already collapses members and re-points their edges as synthetic `stackedge:` edges and removes them on `destroy()`. Zoom-driven expansion, through the elevation hidden-class convention (`spec-viz-projection.md`), is a later step; nothing needs it yet.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-compound-edge-1 | Collapsed into one arrow | Implemented | A middle node with both ends drawn is hidden with its role edges, and exactly one synthetic arrow joins sender to receiver, marked `_is_compound_edge`, naming the middle node in `_compound_id` and labelled with its label. | `tap_viz/tests/test_compound_edge_runtime.py` (Node harness) |
| req-viz-compound-edge-2 | No arrow for an end that is not drawn | Implemented | When either end is hidden or absent, no arrow is drawn, nothing is re-pointed, and the middle node stays shown; the handle reports it as skipped. | Node harness |
| req-viz-compound-edge-3 | Tap expands, tap collapses | Implemented | A tap on the arrow removes it and shows the middle node and its role edges; a tap on that middle node collapses it again. | Node harness |
| req-viz-compound-edge-4 | Idempotent and restorable | Implemented | A re-run with the same handle id leaves one arrow per compound edge; `destroy()` removes every arrow and listener and the class it set, and no other class. | Node harness |
| req-viz-compound-edge-5 | Roles come from the declaration | Implemented | The runtime reads the role edges from the node's `compound_edge` data, which the panel copies from the display lane; `opts.types` only narrows which middle-node types are collapsed. | Node harness; panel source check |

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`
