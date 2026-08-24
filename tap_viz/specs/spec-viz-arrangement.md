# Viz Arrangement Specification

## Philosophy

Arrangements are post-layout positioning rules that reposition nodes already on the Cytoscape graph into structured formations. They solve the problem that raw Cytoscape layouts (and even tap layouts) produce functional but visually unrefined results — nodes land where the algorithm puts them, not where a human designer would place them for clarity.

An arrangement does not add, remove, or fetch nodes. It operates entirely on the current Cytoscape element set. Its job is to take nodes that are already positioned and move them into a defined spatial relationship relative to an anchor node. The anchor stays fixed; everything else moves to it.

Arrangements are designed to stack. A layout declares an ordered list of arrangement references. The first arrangement positions a set of nodes relative to an anchor. The second arrangement can then anchor against one of the nodes positioned by the first, and so on. This compositional model lets complex positional layouts be built up from simple, reusable rules.

Arrangements are TAP-managed entities stored as their own model and connected to layouts via the hotlink system. This keeps arrangement definitions reusable across layouts and inspectable as first-class graph artifacts.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Post-Layout | Arrangements run after the initial layout completes; they refine positions, not compute them from scratch. |
| 2. | Anchor-Relative | Every arrangement pivots around a single anchor node that stays fixed in place. |
| 3. | Gryphon-Identified | Both the anchor and the member nodes are identified by server-side gryphon queries, matched to cy elements by entity ID. |
| 4. | Stackable | Arrangements execute in declared order; later arrangements build on positions set by earlier ones. |
| 5. | Runtime | Arrangement positioning executes client-side against the live Cytoscape instance; node identification uses server-side gryphon. |
| 6. | Reusable | Arrangements are independent entities that layouts reference via hotlinks; one arrangement can serve multiple layouts. |
| 7. | Declarative | Arrangement definitions are pure data — no executable code — making them inspectable and portable. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-arrangement-model | [Arrangement Model](#arrangement-model) | Implemented | Arrangement as a TAP-managed BaseModel entity |
| req-viz-arrangement-definition | [Arrangement Definition](#arrangement-definition) | Implemented | JSON definition shape: anchor, members, positioning |
| req-viz-arrangement-anchor | [Anchor Resolution](#anchor-resolution) | Implemented | Single-node anchor identified by gryphon query against cy |
| req-viz-arrangement-members | [Member Resolution](#member-resolution) | Implemented | Member nodes identified by gryphon queries against cy |
| req-viz-arrangement-positioning | [Positioning](#positioning) | Implemented | Horizontal or vertical axis positioning relative to anchor |
| req-viz-arrangement-distribution | [Distribution](#distribution) | Implemented | Even distribution of members across the positioned axis |
| req-viz-arrangement-span | [Anchor-Relative Span](#anchor-relative-span) | Implemented | Optional `span_px` + `anchor_offset_px` override the dynamic min..max span with an explicit pixel budget anchored to the anchor's axis value |
| req-viz-arrangement-execution | [Execution Model](#execution-model) | Implemented | Client-side serial execution after layout completes |
| req-viz-arrangement-layout-hotlink | [Layout Hotlink Integration](#layout-hotlink-integration) | Implemented | Layouts reference arrangements via `USES_ARRANGEMENT` hotlink; canonical host path per `spec-viz-layouts.md` |
| req-viz-arrangement-tagging | [Arrangement Tagging](#arrangement-tagging) | Backlog | Tag cy elements with arrangement membership for downstream logic |

## Requirements

### Arrangement Model
----
RID: `req-viz-arrangement-model`
Status: `Implemented`

An arrangement is a TAP-managed entity that stores a declarative positioning rule.

#### Implementation

`Arrangement` is a `BaseModel` subclass in `tap_viz` with `ENTITY_TYPE = "arrangement"`.

Fields:

- `name` — `CharField(max_length=255)`, required on create.
- `description` — `TextField(blank=True, default="")`.
- `definition` — `JSONField(default=dict, blank=True)`. Stores the arrangement rule as pure data (see [Arrangement Definition](#arrangement-definition)).

The model should declare `FIELD_CRUD_SCHEMA` and `CREATE_REQUIRED` consistent with the existing Layout and Projection models.

#### Development

Keeping arrangements as their own entity type rather than inline JSON inside layouts means they can be inspected, reused, and tested independently. The definition is intentionally pure data — no `js_file` reference — because arrangement logic is a TAP Viz runtime capability, not plugin-extensible executable code.

#### Future

If arrangement logic needs plugin-extensible behavior, that should be a separate category of arrangement with its own contract, not a loosening of the declarative model.


### Arrangement Definition
----
RID: `req-viz-arrangement-definition`
Status: `Implemented`

The arrangement definition JSON describes the anchor, members, positioning axis, and distribution strategy.

#### Implementation

The v0 definition shape:

```json
{
  "anchor": {
    "gryphon": "MATCH (a:aws_ec2_instance) WHERE a.entity_id = $entity_id RETURN a"
  },
  "members": {
    "gryphon": "MATCH (a:aws_ec2_instance)-[:HOSTS]->(m:network_interface) WHERE a.entity_id = $entity_id RETURN m"
  },
  "positioning": "vertical",
  "distribution": "even"
}
```

Top-level keys:

- `anchor` — object with a `gryphon` key containing a gryphon query string. Must resolve to exactly one node.
- `members` — object with a `gryphon` key containing a gryphon query string. Returns the set of nodes to reposition.
- `positioning` — `"horizontal"` or `"vertical"`. The axis along which members are arranged.
  - `"horizontal"`: members are placed along the X axis at the anchor's Y coordinate.
  - `"vertical"`: members are placed along the Y axis at the anchor's X coordinate.
- `distribution` — v0 supports `"even"` only. Members are spaced evenly across the total span.

The `FIELD_SCHEMAS` on the Arrangement model should validate this shape.

#### Development

Gryphon queries in arrangements are executed server-side via the standard gryphon execution path, then the returned entity IDs are matched against cy elements to identify the nodes to reposition (see [Execution Model](#execution-model)).

#### Future

- Additional distribution strategies (e.g., `"packed"`, `"weighted"`) and multi-axis arrangements can be added by extending the vocabulary of `positioning` and `distribution`.
- `offset` — an `{x, y}` pixel offset applied to the positioning axis origin relative to the anchor's position, shifting the entire member group without moving the anchor. Add when practical use cases require it.


### Anchor Resolution
----
RID: `req-viz-arrangement-anchor`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

The anchor is a single node identified by a gryphon query. It stays fixed in place.

#### Implementation

The arrangement runtime executes the anchor gryphon query server-side, then matches the returned entity ID against cy elements to find the anchor node. The query must resolve to exactly one visible node on the graph.

Failure modes:

- **Zero results from gryphon**: the arrangement is skipped and an `arrangement_anchor_missing` warning is emitted.
- **Multiple results from gryphon**: the arrangement is skipped and an `arrangement_anchor_ambiguous` warning is emitted.
- **Gryphon returns one result but entity is not in cy**: the arrangement is skipped and an `arrangement_anchor_missing` warning is emitted.

The anchor node's position is read but never modified by the arrangement. All member positioning is computed relative to the anchor's current position.

#### Development

Requiring exactly one anchor keeps the positioning math unambiguous and makes failure modes clear. Using gryphon queries rather than literal entity_ids means arrangements work correctly when the same layout runs against different data sets.

#### Future

If multi-anchor arrangements become useful (e.g., "between these two nodes"), that should be a new positioning mode, not a relaxation of the single-anchor constraint.


### Member Resolution
----
RID: `req-viz-arrangement-members`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

Members are nodes identified by a gryphon query that will be repositioned.

#### Implementation

The arrangement runtime executes the members gryphon query server-side via the standard gryphon execution path. The returned nodes are then matched against cy elements by entity ID — only nodes that exist in both the gryphon result set and the current cy graph become members. Entities returned by gryphon that are not currently in the cy graph are silently ignored.

Behavior:

- **Zero matched nodes**: the arrangement is a no-op (no warning — empty member sets are legitimate for conditional arrangements).
- **One or more matched nodes**: all matched nodes are repositioned according to the positioning and distribution rules.
- If the anchor node appears in the member set, it is silently excluded — the anchor never moves.
- Members that are not currently visible (have `.tap-elevation-hidden` class) are excluded from positioning.

The order of members matters for positioning. The initial order is determined by the nodes' current positions along the arrangement axis prior to repositioning — nodes already further along the axis appear later in the sequence. This preserves the relative order established by the preceding layout.

#### Development

Preserving the pre-existing order means arrangements refine positions without scrambling spatial intent from the layout pass. Excluding the anchor from the member set prevents accidental self-movement.

#### Future

Add explicit sort keys in the definition (e.g., `"sort_by": "label"`) when ordering by something other than current position is needed.


### Positioning
----
RID: `req-viz-arrangement-positioning`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

Members are positioned along a single axis relative to the anchor.

#### Implementation

Positioning has two steps that happen in order:

**Step 1 — Axis snapping.** Each member node is moved onto the positioning axis line:

- `"vertical"`: all members get their X coordinate set to `anchor.x`. Their Y coordinates are preserved from the layout pass (not yet distributed).
- `"horizontal"`: all members get their Y coordinate set to `anchor.y`. Their X coordinates are preserved from the layout pass (not yet distributed).

This step takes nodes wherever they are on the graph and pulls them into a line aligned with the anchor's position on the cross-axis.

**Step 2 — Distribution** (see [Distribution](#distribution)) then adjusts the spacing along the axis.

The anchor does not move during either step.

#### Development

Splitting positioning into axis snap + distribution makes the behavior easy to reason about.

#### Future

Add angular positioning (`"radial"`) for spoke-and-hub layouts.


### Distribution
----
RID: `req-viz-arrangement-distribution`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

Distribution controls spacing of members along the positioning axis after they have been snapped to it.

#### Implementation

v0 supports one distribution strategy: `"even"`.

**Even distribution:**

1. Determine the span. The span runs from the first member to the last member along the positioning axis, using their current positions (after axis snapping, before redistribution). The span endpoints are the minimum and maximum axis-coordinate values among all members.
2. Compute even spacing. The gap between consecutive members is `span / (count - 1)` for 2+ members. A single member stays at its current position.
3. Reposition members. Walking the members in axis order, place each at `min + index * gap`.

The span is derived from the members' own positions, not from the anchor. This means the total spread of the members is preserved — distribution only equalizes the gaps within that spread.

#### Development

Deriving span from member positions rather than imposing a fixed size keeps arrangements responsive to different data sets. The members might span 200px or 800px depending on what the layout pass produced — even distribution works correctly either way.

#### Future

- `"packed"`: members are placed with a fixed gap between them (specified in pixels), centered on the midpoint of the current span.
- Custom gap sizes.


### Anchor-Relative Span
----
RID: `req-viz-arrangement-span`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

Two optional definition fields — `span_px` and `anchor_offset_px` — let an arrangement pin its members to a specific pixel budget along the positioning axis, measured from the anchor.

#### Implementation

```json
{
  "anchor": {...},
  "members": {...},
  "positioning": "vertical",
  "distribution": "even",
  "anchor_offset_px": 110,
  "span_px": 240
}
```

When `span_px` is present, even-distribution lays members out across exactly that many pixels along the positioning axis, starting at `anchor_axis + anchor_offset_px` (default `0`). Both fields are optional; when neither is present, the legacy behavior derives the span from members' current min..max position range.

Semantics by member count, when `span_px` is set:

- **1 member**: placed at `anchor + anchor_offset_px`. `span_px` is ignored.
- **N ≥ 2 members**: placed at `anchor + offset + k * span_px / (N - 1)` for `k ∈ [0, N - 1]`.

Setting `anchor_offset_px > 0` keeps all members on one side of the anchor — the typical "story reads below the anchor" case for vertical positioning, or "members trail to the right" for horizontal. A negative offset places members on the opposite side; an offset of zero co-locates the first member with the anchor (rarely useful).

#### Development

The legacy member-range span was sensitive to the layout pass's initial scatter — a wide initial scatter produced a wide arrangement column, even when the layout module's intent was a compact cluster. Explicit `span_px` gives the arrangement author direct control of the visual scale per-system, which is the natural tweaking surface when arrangements are per-system entities (the samsite landing's four `Component`-driven arrangements were the originating case).

`anchor_offset_px` exists separately from `span_px` because "where do members start relative to the anchor" is a different decision than "how spread out are they." The two compose: an arrangement can set the offset alone (single-member case, member at fixed distance below anchor) or both (multi-member compact column).

#### Future

- A `"justified"` mode that adapts `span_px` to viewport size at runtime, for layouts that should expand on wide screens.
- A per-member `weight` field for non-uniform spacing.


### Execution Model
----
RID: `req-viz-arrangement-execution`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/arrangement.js

Arrangements execute client-side, serially, after the layout completes.

#### Implementation

The arrangement runtime is a TAP Viz runtime module at `tap_viz/static/tap_viz/js/runtime/arrangement.js`.

The public API:

```javascript
/**
 * Execute an ordered list of arrangements against the Cytoscape instance.
 *
 * @param {cytoscape.Core} cy - The active Cytoscape instance.
 * @param {Array<Object>} arrangements - Arrangement definitions in execution order.
 * @param {Object} inputs - Runtime input variables (passed through to gryphon matching).
 * @returns {{ warnings: string[] }} - Collected warnings from all arrangements.
 */
export async function executeArrangements(cy, arrangements, inputs) { ... }
```

Execution flow:

1. The layout module calls `executeArrangements()` after its primary layout work completes.
2. Arrangements execute in array order. Each arrangement:
   a. Executes the anchor gryphon query server-side, matches the result against cy elements by entity ID.
   b. Executes the members gryphon query server-side, matches results against cy elements by entity ID.
   c. Performs axis snapping.
   d. Performs distribution.
3. If an arrangement emits a warning, it is collected and execution continues with the next arrangement.
4. Arrangements never throw — all failure modes produce warnings and skip the arrangement.

Gryphon queries are executed via the standard server-side gryphon execution path (the same path used by searches). The returned entity IDs are then used to look up corresponding nodes in the cy graph. This gives arrangements access to the full gryphon query system — multi-hop, aggregation, edge traversals — without needing a client-side gryphon implementation.

Whether the host Layout's arrangements actually dispatch on a given page load may be controlled by its `arrangement_control` field; see [`req-viz-layout-arrangement-control`](spec-viz-layouts.md#arrangement-control). Arrangements themselves remain unaware of the control field — the decision is applied by the Layout runtime before `executeArrangements()` is called, so individual arrangement definitions never need to opt in or out.

#### Development

Making the arrangement runtime a shared module means any layout — TAP-owned or plugin-shipped — can use arrangements by importing and calling `executeArrangements()`. Using server-side gryphon means arrangements get the full query language for free and stay consistent with how gryphon queries work everywhere else in TAP.

#### Future

- Animation support: transition members to their new positions over a duration rather than snapping instantly.
- Arrangement-level `onWarning` callback for richer runtime diagnostics.


### Layout Hotlink Integration
----
RID: `req-viz-arrangement-layout-hotlink`
Status: `Implemented`

Layouts reference arrangements via an array of entity IDs in their definition, validated by the hotlink system. This is the canonical host path for arrangements once the v1 reshape lands; see [Dual-Mode Layout Definition (v1)](spec-viz-layouts.md#dual-mode-layout-definition-v1).

#### Implementation

The Layout model's `definition` JSONField gains a new optional key:

```json
{
  "arrangements": [
    "<arrangement-entity-id-1>",
    "<arrangement-entity-id-2>"
  ]
}
```

The Layout model declares a HOTLINKS entry for this:

```python
HOTLINKS: ClassVar[list[dict]] = [
    {
        "name": "layout-arrangements",
        "field": "definition",
        "selector_type": "simple_path",
        "selector": "arrangements.*",
        "edge_direction": "outbound",
        "edge_type": "USES_ARRANGEMENT",
        "mode": "exact",
    },
]
```

This creates `USES_ARRANGEMENT` edges from the layout entity to each referenced arrangement entity. The hotlink system validates that every entity ID in the `arrangements` array has a corresponding edge and vice versa.

The array order is the execution order. The hotlink validates presence and completeness; the array defines sequence.

At runtime, the layout module (or the projection runtime) resolves the arrangement entity IDs, loads their definitions, and passes them to `executeArrangements()`.

#### Development

Using the existing hotlink system means arrangement references get the same consistency guarantees as page-panel references. The `exact` mode ensures the edge set and the definition array stay perfectly synchronized.

The `arrangements` key is optional in the layout definition — layouts without arrangements simply omit it, and the hotlink selector extracts an empty set, which passes validation trivially.

#### Future

If arrangements need to be shared at the projection level (applied to all layouts in an elevation), that should be a separate hotlink declaration on the Projection model rather than duplicating arrangement references across layouts.


### Arrangement Tagging
----
RID: `req-viz-arrangement-tagging`
Status: `Backlog`

Once an arrangement has run, the participating nodes should be tagged with arrangement membership metadata on the cy elements.

#### Implementation

After an arrangement positions its members, each member node (and the anchor) should receive a data tag on the cy element indicating which arrangement it participated in. This enables downstream logic to identify and operate on groups of nodes that were positioned together — for example, applying uniform styling, computing bounding boxes, or running secondary adjustments scoped to an arrangement group.

The tagging mechanism, tag format, and data property naming are deferred to implementation time.

#### Development

Arrangement tagging is a prerequisite for building higher-level layout helpers that compose multiple arrangements and need to reference the results of prior arrangements as groups rather than re-querying for the same nodes.

#### Future

Define the tag format and build layout helpers that consume arrangement tags for group-level operations (e.g., bounding box computation, group styling, group animation).


## Worked Example: EC2 Instance Layout

The current `ec2-internal.js` layout manually positions network interfaces in a vertical column left of the EC2 instance. With arrangements, the layout would:

1. Run its primary layout logic (visibility filtering, container sizing, program positioning).
2. Call `executeArrangements()` with two arrangements:

**Arrangement 1: "EC2 Network Interfaces"**
```json
{
  "anchor": {
    "gryphon": "MATCH (a:aws_ec2_instance) WHERE a.entity_id = $entity_id RETURN a"
  },
  "members": {
    "gryphon": "MATCH (a:aws_ec2_instance)-[:HOSTS]->(m:network_interface) WHERE a.entity_id = $entity_id RETURN m"
  },
  "positioning": "vertical",
  "distribution": "even"
}
```

This takes all network interfaces hosted by the EC2 instance and arranges them in a vertical column aligned with the EC2 instance's X position.

**Arrangement 2: "Interface Ports"** (per interface, anchored to the interface positioned by Arrangement 1)
```json
{
  "anchor": {
    "gryphon": "MATCH (iface:network_interface) WHERE iface.entity_id = $iface_id RETURN iface"
  },
  "members": {
    "gryphon": "MATCH (iface:network_interface)<-[:ATTACHED_TO]-(p:port) WHERE iface.entity_id = $iface_id RETURN p"
  },
  "positioning": "vertical",
  "distribution": "even"
}
```

This takes ports attached to each interface and stacks them vertically centered on the interface. Because Arrangement 1 already positioned the interfaces, the ports land in the right place.

Note: the per-interface arrangement requires iterating over interfaces and calling `executeArrangements()` once per interface with the appropriate `$iface_id` input. This pattern — a layout calling arrangements in a loop with different inputs — is a valid and expected usage pattern.
