# Viz Nested Projection Specification

## Philosophy

The core geometric rule for nested TAP Viz scenes is simple: leaves are true-sized, containers grow to fit them. Each entity type declares a base size; leaves render at that size always, and containers (nodes that host nested children) resize to enclose their children's laid-out bounding box plus padding. A container with three subnets is visibly larger than one with one subnet — size reflects content, honestly.

This inverts a prior model in which parents had authoritative fixed sizes and children were scaled down to fit. Under the prior model, every added child made siblings smaller; at typical data densities, leaf compute nodes would shrink below legibility. Bottom-up natural sizing removes scale-to-fit compression entirely: leaves keep their declared sizes and containers adjust.

TAP nested projection does not use Cytoscape's compound-node system. All nodes remain flat peers in the Cytoscape graph. Visual containment is achieved through positional placement: children are positioned within the model-space bounding box of their parent node, rendered on top via z-index, and moved in lockstep with the parent by the runtime. Edges that express the containment relationship are hidden. This bounded-layer model avoids compound auto-sizing, compound-specific style rules, and the awkward anchor-child machinery that was needed to force compound nodes to specific dimensions.

Sizing is deterministic. Given the nesting tree, the `baseSizes` declaration, and each container's inner-layout choice, every node's size is a function of the data — the same scene rendered twice yields the same layout. Container `baseSizes` entries act as minimum floors, so sparse containers still render at a sensible minimum.

The runtime owns the geometry work via a two-pass algorithm: a measure pass resolves sizes bottom-up, then a position pass places children relative to each parent's center top-down. Layout authors declare nesting relationships, base sizes, and inner-layout choices; the runtime does the arithmetic.

This specification defines the geometry contract and the runtime projection API. It complements the projection spec (orchestration and elevation) and the nesting spec (relationship resolution and edge hiding).

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Natural Sizing | Leaves are true-sized; containers grow to fit their children plus padding. |
| 2. | Bounded Layers | Visual containment is positional, not structural. No Cytoscape compound nodes. |
| 3. | Deterministic Geometry | Sizes are a function of the nesting tree and `baseSizes`, not of runtime viewport state. |
| 4. | Two-Pass Resolution | Measure bottom-up, then position top-down — the standard flexbox-family shape. |
| 5. | Additive Elevations | Deeper elevations add nesting layers without removing higher-level structure. |
| 6. | Simpler Runtime | Scale-fit compression, hero-node anchoring, and camera compensation are retired. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-nested-projection-natural-sizing | [Natural Sizing Model](#natural-sizing-model) | Implemented | Leaves true-sized from baseSizes; containers grow to fit children + padding |
| req-viz-nested-projection-bounded-layer | [Bounded-Layer Model](#bounded-layer-model) | Implemented | No Cytoscape compounds; positional containment with z-ordering |
| req-viz-nested-projection-container-size-from-children | [Container Size From Children](#container-size-from-children) | Implemented | Container outer box derived from children's laid-out bbox plus padding |
| req-viz-nested-projection-no-leaf-compression | [No Leaf Compression](#no-leaf-compression) | Implemented | Leaves never shrink; scale-to-fit removed. Supersedes scale-to-fit. |
| req-viz-nested-projection-two-pass | [Two-Pass Measure/Position](#two-pass-measureposition) | Implemented | Measure bottom-up; position top-down. Supersedes viewport-constrained layout order. |
| req-viz-nested-projection-natural-layouts | [Natural Layouts](#natural-layouts) | Implemented | Built-in natural layouts: `grid`, `align-distribute-vertical`, `tiered-rows` |
| req-viz-nested-projection-runtime-api | [Runtime Projection API](#runtime-projection-api) | Implemented | `projectNested` runtime module owns the geometry pipeline |
| req-viz-nested-projection-dimension-match | [Dimension-Equality Relationships](#dimension-equality-relationships) | Implemented | `{dimension_match: {parent_type, dimension}}` pairs children whose dimension value matches a parent's — implicit containment via shared spine dimension, no edge required |
| req-viz-nested-projection-container-visual | [Container Visual Switch](#container-visual-switch) | Implemented | Viewport parents switch to container rendering automatically |
| req-viz-nested-projection-additive-elevations | [Additive Elevation Nesting](#additive-elevation-nesting) | Approved for Development | Deeper elevations extend the nesting chain without collapsing higher levels |
| req-viz-nested-projection-scene-activation | [Scene-Wide Elevation Activation](#scene-wide-elevation-activation) | Approved for Development | Whole-scene elevation switching remains the v1 model |
| req-viz-nested-projection-runtime-simplification | [Runtime Simplification Direction](#runtime-simplification-direction) | Approved for Development | Hero-node anchoring and camera choreography are transitional |

## Requirements

### Natural Sizing Model
----
RID: `req-viz-nested-projection-natural-sizing`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

Nodes in a nested projection scene have two roles, derived from the nesting tree: leaves are true-sized from `baseSizes`, and containers grow to fit their children plus padding.

#### Implementation

The role is structural, not declared: a node that has nested children is a container; a node that has none is a leaf. Role assignment follows from the nesting tree built by `resolveNesting`.

Leaf sizing:

- Each leaf's outer width and height come directly from `baseSizes[entity_type]`.
- Leaves are never shrunk to fit a parent. There is no scale compression.
- Shadow nodes (`_is_shadow === true`) carry their primary's `entity_type` and are sized from the same `baseSizes` lookup — no separate shadow-size config.

Container sizing:

- A container's inner bbox is the natural bounding box of its laid-out children (see Container Size From Children).
- The container's outer size is `max(inner + 2 * padding, baseSizes[entity_type])`.
- Thus `baseSizes[container_type]` acts as a minimum floor, not an authoritative outer size.

This model applies uniformly at every nesting depth. At any level, the nodes at that level have been sized (leaves directly from `baseSizes`, containers from deeper levels already measured).

#### Development

This inverts the v0 model where containers had fixed outer sizes and children were scaled down to fit. In practice, the v0 model made leaves progressively unreadable as scenes grew denser. Natural sizing makes the scene size track the data size — a larger account is a larger box.

The tradeoff is that sibling containers at the same nesting level may differ in size (e.g., a subnet with three EC2 instances is wider than one with one). This is the honest reflection of the data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-natural-sizing-1 | Leaves Use baseSizes Directly | Implemented | Each leaf's width and height equal `baseSizes[entity_type]`. | |
| req-viz-nested-projection-natural-sizing-2 | No Leaf Compression | Implemented | Leaves are not scaled to fit any parent. | |
| req-viz-nested-projection-natural-sizing-3 | Role From Tree | Implemented | A node is a container iff it has children in the resolved nesting tree. | |
| req-viz-nested-projection-natural-sizing-4 | baseSizes As Floor | Implemented | `baseSizes[container_type]` is a minimum; a container may be larger when its contents require. | |
| req-viz-nested-projection-natural-sizing-5 | Deterministic Sizes | Implemented | Given the nesting tree, `baseSizes`, padding, and inner-layout choices, every node's size is reproducible. | |

#### Future

Allow per-leaf size overrides via node data (e.g. for zoom-responsive "important" nodes).


### Bounded-Layer Model
----
RID: `req-viz-nested-projection-bounded-layer`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

TAP nested projection uses positional containment rather than Cytoscape's compound-node system.

#### Implementation

All nodes in a TAP Viz scene remain flat peers in the Cytoscape graph. No node is ever assigned as a Cytoscape compound parent via `node.move({parent: id})` or element data `parent` fields.

Visual containment is achieved through:

- **Positional placement**: children are positioned within the model-space bounding box of their parent node by the constrained layout runner.
- **Z-ordering**: children are rendered on top of their parent via z-index style rules. Deeper nesting depth = higher z-index.
- **Edge hiding**: edges that express the containment relationship are hidden via the `.tap-hidden-containment` class (same convention as before).
- **Data stamping**: children carry `_viewport_parent` in their data to identify their containing node. The runtime uses this for position coupling and containment queries.

Benefits of this model over Cytoscape compounds:

- no compound auto-sizing (parent never grows to contain children)
- no invisible anchor children needed to force minimum sizes
- no compound-specific style rules or `:parent` pseudo-selectors
- children may extend beyond parent perimeter in future layouts (ports, interfaces)
- parent node styling is trivial (it is always a regular node)
- position coupling is explicit rather than implicit

#### Position Coupling

When a viewport parent is dragged, all of its descendants (found by walking the `_viewport_parent` chain) move in lockstep. Dragging a child moves only that child — group movement is parent-only.

The runtime module `tap_viz/static/tap_viz/js/runtime/drag-group.js` implements this by:
- building a `childrenByParent` map from `_viewport_parent` stamps after layout completes
- snapshotting each parent's position for delta computation
- listening for `position` events on parent nodes and applying the delta recursively to all descendants
- using a propagation guard so descendant moves don't re-trigger the handler

Badge nodes follow automatically because `badge-nodes.js` already listens for position events on `_badge_active` hosts.

The drag-group listener is activated by `projection.js` after each elevation's layouts complete and is torn down before re-layout or on projection destroy.

#### Development

The compound-node system in Cytoscape is designed for a different use case: auto-sizing containers where the parent's size is derived from its children. TAP's use case is the opposite — the parent's size is authoritative and children must fit within it. Fighting Cytoscape's auto-sizing with anchor children and dimension overrides added complexity without solving the fundamental mismatch. The bounded-layer model sidesteps the issue entirely.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-bounded-layer-1 | No Compound Parents | Implemented | No node in a TAP nested projection scene is assigned as a Cytoscape compound parent. | |
| req-viz-nested-projection-bounded-layer-2 | Positional Containment | Implemented | Children are contained by being positioned within the parent's bbox by the position pass. | |
| req-viz-nested-projection-bounded-layer-3 | Z-Index Layering | Implemented | Children render on top of parents via z-index depth assignment. | |
| req-viz-nested-projection-bounded-layer-4 | Data Stamping | Implemented | Children carry `_viewport_parent` data identifying their containing node. | |
| req-viz-nested-projection-bounded-layer-5 | Drag Follows Parent | Implemented | Dragging a viewport parent moves all descendants in lockstep via `drag-group.js`. Child-only drag moves only the child. | |

#### Future

Consider allowing children to extend beyond parent perimeter for specialized layouts (network interfaces, ports).


### Container Size From Children
----
RID: `req-viz-nested-projection-container-size-from-children`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

A container's outer bounding box is derived from its children's laid-out bbox plus padding.

#### Implementation

A natural layout function takes an array of pre-sized children — each `{node, width, height}` — and returns `{width, height, placements}`, where:

- `width`/`height` is the tight bounding box enclosing all children as arranged by the layout
- `placements` is an array of `{node, dx, dy}` — per-child offsets from the bbox center

The runtime calls the layout function once per container during the measure pass. The returned bbox is inflated by `2 * padding` and floored against `baseSizes[container_type]` to produce the container's outer size. The placements are cached for the position pass.

This inverts the v0 model. The container no longer has an authoritative outer box that defines an inner viewport — the container's outer box is a consequence of its children plus padding.

"Model-space" coordinates still apply. Cytoscape's zoom scales the whole resolved scene uniformly on screen.

V1 provides three natural layouts — `grid`, `align-distribute-vertical`, and `tiered-rows` — specified in [Natural Layouts](#natural-layouts). Plugins may register additional natural layouts by providing a function matching the contract above.

Per-container-type layout choice is supported via `innerLayouts: {entity_type: "grid" | "align-distribute-vertical" | "tiered-rows" | {name, ...opts}}`, with a default `innerLayout` for the rest.

#### Development

Expressing layout as "measure then place" keeps each natural layout testable in isolation — a pure function from child sizes to bbox + placements. The projection runtime only orchestrates traversal; layout algorithms don't have to know about padding, floors, or the outer size contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-container-size-from-children-1 | Bbox + Padding = Size | Implemented | A container's outer width/height equals `natural_bbox + 2 * padding`, floored by `baseSizes[type]`. | |
| req-viz-nested-projection-container-size-from-children-2 | Layout Returns Placements | Implemented | Natural layout functions return per-child `{dx, dy}` offsets from the bbox center. | |
| req-viz-nested-projection-container-size-from-children-3 | Per-Type Layout Choice | Implemented | Layout algorithm is selectable per container entity_type via `innerLayouts`. | |
| req-viz-nested-projection-container-size-from-children-4 | Empty Container Falls To Floor | Implemented | A container with no visible children renders at its `baseSizes` entry. | |

#### Future

- Additional natural layouts: horizontal stack, row-packed grid, hierarchical clustering.
- Header/label carve-outs (space reserved at top of a container for label band that doesn't count against child area).


### No Leaf Compression
----
RID: `req-viz-nested-projection-no-leaf-compression`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

Leaves render at their declared `baseSizes` at every nesting depth. The runtime does not scale leaf geometry to fit a parent.

#### Implementation

Under the bottom-up model there is no scale-to-fit step. Each leaf's final width and height are taken directly from `baseSizes[entity_type]`. Shadow nodes carry their primary's `entity_type`, so the same lookup gives them the same size as their primary automatically. Because containers resize to fit their children, there is no mechanism that would require a leaf to shrink.

Scale compounding across nesting depth is also removed. A leaf at depth 3 renders at the same size as a leaf of the same type at depth 1, assuming both are visible at the same elevation.

Overfill cannot occur under this model: a container always grows to its children, so children always fit. The v0 overfill warning is retired; scene density is expressed by container size, not by warning.

On-screen sizing is still modulated by Cytoscape's zoom (users pan and zoom the whole resolved scene), but that is uniform across all elements. Per-node projection scaling is gone.

#### Development

This is the single biggest reason the new model exists. Under v0, a VPC with four subnets each containing a handful of instances produced EC2 icons too small to read. The workaround would have been to hand-tune per-type `baseSizes` for every scene density, which doesn't scale. Natural sizing eliminates the problem by making the scene grow with the data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-no-leaf-compression-1 | Leaf Size Equals baseSizes | Implemented | Every leaf's final width/height equals `baseSizes[entity_type]`. | Shadows inherit their primary's entity_type and so match its size. |
| req-viz-nested-projection-no-leaf-compression-2 | No Per-Depth Scale Factor | Implemented | The runtime does not apply a depth-dependent scale multiplier to any node. | |
| req-viz-nested-projection-no-leaf-compression-3 | No Overfill Warning | Implemented | Overfill is structurally impossible; the v0 overfill warning is removed. | |

#### Future

If a future scene wants zoom-responsive leaf sizing (e.g. "grow important nodes when the user zooms out"), that belongs in a separate layer above natural sizing rather than inside the projection runtime.


### Two-Pass Measure/Position
----
RID: `req-viz-nested-projection-two-pass`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

Projection resolves in two passes: a bottom-up measure pass that sizes every node and caches child placements, then a top-down position pass that sets absolute coordinates.

#### Implementation

**Measure pass (bottom-up).** The runtime processes containers in topological order — deepest first. At each container:

1. Collect visible children. Each child already has a size: a leaf got its size directly from `baseSizes`, a container got its size from a deeper measure iteration.
2. Call the container's natural layout function with the pre-sized children. Receive `{width, height, placements}` where placements are `{node, dx, dy}` offsets from the bbox center.
3. Compute the container's outer size: `max(width + 2 * padding, baseSizes[type])` (same for height).
4. Cache the placements keyed by container id.

After the measure pass every node has a resolved width and height, and every container has a cached placement list.

**Position pass (top-down).** The runtime places root containers using a natural layout on the root set (centered at origin). Then for each container, it walks children and applies the cached placements relative to the container's center position. Recursion handles deeper levels.

Because placements are cached during measure, the position pass does zero layout work — it just translates offsets into absolute positions.

**Why two passes.** Sizes depend on children (bottom-up), but positions depend on parents (top-down). One pass cannot satisfy both dependencies. Splitting them also keeps the layout functions pure — a natural layout only needs to know child sizes, not container positions.

#### Development

The shape mirrors HTML/flexbox's intrinsic measurement phase followed by fragment positioning. The difference is that TAP layouts always return an explicit placement list rather than mutating child positions — this keeps them side-effect-free and unit-testable.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-two-pass-1 | Topo Order Measure | Implemented | The measure pass processes containers in topological order: every child is measured before its parent. | |
| req-viz-nested-projection-two-pass-2 | Placements Cached | Implemented | The measure pass caches per-container child placements; the position pass does not re-invoke layout functions. | |
| req-viz-nested-projection-two-pass-3 | Top-Down Position | Implemented | The position pass walks roots first, then applies cached placements relative to each parent's center, recursing into children. | |
| req-viz-nested-projection-two-pass-4 | Pure Layout Functions | Implemented | Natural layout functions do not mutate cy; they read child sizes and return a value. | |

#### Future

Expose the measure pass as a standalone API for "what would the layout look like if..." tooling.


### Natural Layouts
----
RID: `req-viz-nested-projection-natural-layouts`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

The runtime ships three built-in natural layouts. Each is a pure function `(children, opts) → {width, height, placements}`, selectable via `innerLayout` and `innerLayouts`.

#### Implementation

**`grid`** (default)

Square-ish grid with uniform cell size taken from the largest child. Cells are arranged with a `spacing` multiplier (default `1.2`).

Opts: `{spacing}`.

Use when children are roughly homogeneous and visual ordering doesn't matter.

**`align-distribute-vertical`**

Children are aligned to a uniform x and distributed top-to-bottom; container width equals the widest child; height sums child heights plus `gap` between each. (Distinct from the [stack](spec-viz-stack.md) primitive, which collapses a homogeneous set into a single pile token — this layout keeps every child visible in a column.)

Opts: `{gap, typeOrder}`.

`typeOrder` is an optional array of `entity_type` strings. Children whose `entity_type` appears earlier in the array are placed higher. Unlisted entity types come after, in input order. Omitting `typeOrder` preserves input order.

Use when a container's children should be distributed in a declared order (e.g. in the AWS layout, an account's Route 53 zone on top, VPC below).

**`tiered-rows`**

Groups children into horizontal tiers by entity-type membership. Each tier renders as one row. Within a row, items matched via a descendant entity type (the "contained" side — typically subnets) come first; items matched via their own entity type (the "primary" side — typically leaves at this nesting level) come after. Items are tightly packed with `itemGap` spacing, and each row is centered horizontally within the layout's overall width. Narrower rows do not stretch to match wider rows — a small row with one primary does not push that primary to the far edge.

Membership rule per child:

1. Compute the child's effective entity types = `{self entity_type} ∪ descendant entity_types` (descendants are the child's direct nested children).
2. Walk tiers in declared order. A tier matches if `tier.entityTypes ∩ effective ≠ ∅`. First match wins.
3. If the match was via the child's own entity type, the child is a **primary** for that tier. Otherwise it's a **contained** item for that tier.

Within each row, contained items and primaries are each sorted alphabetically by label, and rendered in order `[...contained, ...primaries]`.

Children that match no tier are collected into a final row, alphabetized and centered. If some children are unassigned the projection continues — no warning is emitted in v1.

Opts:

| Key | Type | Default | Description |
| --- | --- | :---: | --- |
| `tiers` | array | required | Ordered tier declarations. Each tier is `{name, entityTypes: [string, ...]}`. Order is top-to-bottom. |
| `rowGap` | number | `20` | Vertical gap between rows. |
| `itemGap` | number | `12` | Horizontal gap between items within a row. |

Use when a container expresses a tiered architecture and the visual story is "things on the left are grouped presences; things on the right are canonical artifacts." The canonical example is the AWS layout's VPC: `[alb, ec2, backend]` tiers with shadow-hosting subnets on the left and primary ALB/RDS/cache nodes on the right.

#### Layout Function Contract

A natural layout is a pure function:

```
(children, opts) → {width, height, placements}

  children    : [{node, width, height}]  children already measured
  opts        : layout-specific config
  width/height: tight bounding box of the arrangement
  placements  : [{node, dx, dy}]  per-child offset from bbox center
```

The function must not mutate `cy` state. The runtime handles size application and position application. A layout may call `node.cy()` to read sibling or descendant data when classification depends on it (as `tiered-rows` does).

Plugins or projection authors may register additional natural layouts by extending the runtime's layout resolver. V1 supports the three built-ins listed above.

#### Development

Separating classification from placement lets authors add scene-specific layouts without needing to duplicate the bbox + padding + floor arithmetic. The primary/contained split in `tiered-rows` came out of the AWS three-tier architecture: the same shape appears in other domains (control plane vs data plane, ingress vs egress), so generalizing it was worth the 100 LoC.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-natural-layouts-1 | Grid Layout | Implemented | `grid` packs children into a square-ish grid with cells sized to the largest child. | |
| req-viz-nested-projection-natural-layouts-2 | Align-Distribute-Vertical Layout | Implemented | `align-distribute-vertical` aligns children to a uniform x and distributes them top-to-bottom with optional `typeOrder`. | |
| req-viz-nested-projection-natural-layouts-3 | Tiered-Rows Layout | Implemented | `tiered-rows` groups children by tier with contained/primary split and alphabetical sort. | |
| req-viz-nested-projection-natural-layouts-4 | Pure Function Contract | Implemented | All natural layouts are side-effect-free `(children, opts) → {width, height, placements}`. | |

#### Future

- Horizontal-stack, row-packed, circular, and force-directed natural layouts.
- Plugin-author registration API for custom natural layouts.
- Warn on unassigned children in `tiered-rows` when the projection expects full coverage.


### Dimension-Equality Relationships
----
RID: `req-viz-nested-projection-dimension-match`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

A relationship may declare containment via *shared spine dimension value* instead of a graph edge.

#### Implementation

The relationship config supports a second shape alongside `gryphon`:

```javascript
relationships: [
    // Edge-walking (existing shape):
    {name: "boundary-contains-account", gryphon: "(parent:boundary)<-[:SCOPED_TO_BOUNDARY]-(child:aws_account)"},

    // Dimension-equality (new shape):
    {name: "account-owns-resource", dimension_match: {parent_type: "aws_account", dimension: "aws_account"}},
]
```

`dimension_match` carries two fields:

- `parent_type` — the `entity_type` of nodes that act as parents under this rule.
- `dimension` — the spine `dimensions` key whose value pairs parents to children.

`resolveNesting` matches every node of `parent_type` against every other node whose `dimensions[<dimension>]` equals the parent's `dimensions[<dimension>]`. The matched node becomes a child of the matched parent. The standard single-parent / cycle-detection / hidden-edge-tracking pipeline applies just as it does for edge-walking rules; in particular a child found by both an edge rule and a dimension rule will produce a `multiple_parents` warning and be rejected, matching the existing semantics.

Children read `dimensions` from their cy data, which is populated server-side by the graph_panel projection context (`spec-grift-envelope` — spine fields flat at top of the GRIFT envelope). Layouts running outside the projection pipeline do not need to fetch dimensions separately.

#### Development

Adding an edge for every parent-child pair that's already implicit in a shared dimension value duplicates information the graph already carries. AWS resources are the originating proof: every `aws_*` node a boto3 collection produces carries `dimensions.aws_account = "<account-id>"`, and the `aws_account` singleton node carries the same value. Materializing an `OWNS_RESOURCE` edge from the account to each of its hundreds of resources would be an `O(n)` graph-noise increase per collection for no information gain — the dimension already says it. Dimension-equality is the right primitive for this kind of implicit "membership in scoping container" relationship, leaving edges for relationships whose existence is itself the assertion (e.g. `SCOPED_TO_BOUNDARY`, which encodes a compliance-meaningful decision separate from any tag).

Edge-walking and dimension-equality rules are designed to coexist in the same `relationships[]` array. A layout that nests on both — for example, `boundary→account` via edge AND `account→resource` via dimension — describes the most common "outer authored container + inner implicit membership" pattern with no compromise on either side.

#### Future

- `dimension_match` could be extended with a `value` constraint so a parent of `parent_type` only adopts children whose dimension equals an explicit literal (rather than matching the parent's own value) — useful when no parent node exists on the grid but the membership should still nest.
- A `multi_dimension_match` could pair on conjunction of dimension equalities (`aws_account` AND `aws_region`), separating per-region clusters inside an account.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-dimension-match-1 | Pairs By Dimension Value | Implemented | Children whose `dimensions[<dimension>]` equals a `parent_type` node's `dimensions[<dimension>]` are assigned as that node's children. | |
| req-viz-nested-projection-dimension-match-2 | Coexists With Edge Rules | Implemented | Edge-walking and dimension-equality relationships may appear in the same `relationships[]` array. Standard single-parent and cycle-detection apply to the union. | |
| req-viz-nested-projection-dimension-match-3 | Dimensions Available Client-Side | Implemented | Cy node data carries `dimensions` (panel-graph.js populates from the GRIFT envelope's spine fields) so the runtime can match without re-fetching. | |


### Runtime Projection API
----
RID: `req-viz-nested-projection-runtime-api`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

The `projectNested` runtime module owns the geometry pipeline for nested scenes.

#### Implementation

`projectNested` is the primary runtime API that layout authors call to declare nested scene intent. It lives at `tap_viz/static/tap_viz/js/runtime/nested-projection.js`.

Layout authors call it with a config object:

```javascript
import { projectNested } from "/static/tap_viz/js/runtime/nested-projection.js";

export async function execute(context) {
  const { cy, trigger_reason } = context;

  await projectNested(cy, {
    relationships: [
      {
        name: "realm-contains-location",
        gryphon: "(parent:realm)-[:CONTAINS]->(child:location)"
      },
      {
        name: "location-contains-character",
        gryphon: "(parent:location)<-[:LOCATED_IN]-(child:character)"
      }
    ],
    baseSizes: {
      realm:     { width: 800, height: 800 },  // minimum floor for this container
      location:  { width: 160, height: 120 },  // minimum floor for this container
      character: { width: 50, height: 50 }     // true size for this leaf
    },
    padding: 20,
    innerLayout: "grid",
    innerLayouts: {
      realm: {name: "align-distribute-vertical", gap: 12}  // per-type override
    }
  });

  if (trigger_reason === "initial_load") {
    cy.fit(cy.nodes(":visible"), 40);
  }
}
```

The runtime performs:

1. **Resolve nesting**: Parse Gryphon patterns, match edges, determine parent-child assignments. Stamps `_viewport_parent` on children and applies `.tap-hidden-containment` to consumed edges.

2. **Derive roles**: A node with children in the resolved tree is a container; all others are leaves.

3. **Measure pass (bottom-up)**:
   - Leaves: `resolvedSize[id] = baseSizes[entity_type]`. Shadow nodes inherit the primary's `entity_type` (see the shadow-nodes runtime), so the same lookup produces the shadow's size automatically.
   - Containers in topological order (deepest first): invoke the inner layout function with pre-sized children → `{width, height, placements}`. Cache placements. Set `resolvedSize[id] = max(width + 2*padding, baseSizes[type]_width)` (same for height).

4. **Apply sizes**: Set `width`/`height` styles on every non-hidden node from `resolvedSize`.

5. **Container visual switch**: Diff `.tap-viewport-parent` — add to new containers, remove from nodes that are no longer containers.

6. **Root placement**: Run the default inner layout over top-level nodes (those without a `_viewport_parent`) centered at origin.

7. **Position pass (top-down)**: For each container, apply its cached placements relative to its center. Recurse.

8. **Z-index by depth**: Depth 0 = lowest z-index, each level adds 10.

9. **Optional fit**: If `config.fit`, call `cy.fit()` after projection.

10. **Warnings**: Emit warnings for multiple-parent conflicts, cycles, and unparseable gryphon patterns. (Overfill warnings were retired — natural sizing makes overfill impossible.)

#### Config Shape

| Field | Type | Required | Description |
| --- | --- | :---: | --- |
| `relationships` | array | Yes | Ordered nesting relationship declarations with `name` and `gryphon` fields. |
| `baseSizes` | object | Yes | Map of `entity_type` → `{width, height}`. True size for leaves; minimum floor for containers. |
| `padding` | number | Yes | Default padding inflated around each container's child bbox. |
| `paddings` | object | No | Per-parent-type padding override. Map of container `entity_type` → number. |
| `innerLayout` | string or object | Yes | Default natural layout: `"grid"`, `"align-distribute-vertical"`, or an object `{name, ...opts}`. Also used for root placement. |
| `innerLayouts` | object | No | Per-entity-type layout override. Map of container `entity_type` → layout spec. |
| `fit` | boolean | No | If true, fit viewport to the scene after projection. Default: false. |

#### Development

Centralizing the geometry pipeline in one runtime module keeps layout code declarative. Layout authors express what they want (relationships + sizes + layout algorithm). New natural layouts are pure functions matching `(children) → {width, height, placements}` and plug in via the `innerLayout`/`innerLayouts` config.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-runtime-api-1 | Single Entry Point | Implemented | `projectNested(cy, config)` is the primary API layouts use for nested scene projection. | |
| req-viz-nested-projection-runtime-api-2 | Resolver Integration | Implemented | Nesting resolution uses Gryphon-subset parsing and stamps `_viewport_parent` data. | |
| req-viz-nested-projection-runtime-api-3 | Two-Pass Execution | Implemented | The runtime runs a measure pass then a position pass. | Supersedes the earlier outer-in recursion ACID. |
| req-viz-nested-projection-runtime-api-4 | Per-Type Layout Choice | Implemented | `innerLayouts` selects natural-layout algorithm per container type. | |
| req-viz-nested-projection-runtime-api-5 | Shadow Sizing | Implemented | Shadow nodes size themselves from `baseSizes[entity_type]` like any other leaf, inheriting the primary's entity_type. | |
| req-viz-nested-projection-runtime-api-6 | Warnings Emitted | Implemented | Multiple-parent conflicts, cycles, and unparseable patterns produce warnings. | |

#### Future

- Plugin-registered natural layouts (user code adds `horizontal-stack`, `packed-grid`, etc.).
- Expose the measure pass so tooling can preview layouts without applying them.


### Container Visual Switch
----
RID: `req-viz-nested-projection-container-visual`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

Nodes that host children automatically switch to a container visual style.

#### Implementation

When `projectNested` determines that a node has children positioned inside it, the runtime adds the `.tap-viewport-parent` class to that node. When children are cleared (next elevation re-asserts without that nesting level), the class is removed.

Default container visual behavior for `.tap-viewport-parent` nodes:

- background rendered as a subtle container (light fill, border)
- icon suppressed (no background-image)
- label repositioned to a header/top position (`text-valign: top`, outside or at top edge)
- node body serves as the visual frame for children inside it

When the class is removed, the node reverts to its normal leaf styling (icon, centered label, standard background).

The style rules for `.tap-viewport-parent` are defined in the graph panel's base stylesheet so they apply consistently across all projection-driven panels.

#### Development

Switching to container mode automatically means layout authors don't have to manually manage style transitions. The visual mode follows from the structural fact of having children inside you.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-container-visual-1 | Class Added Automatically | Implemented | `.tap-viewport-parent` is added by the runtime when a node has children projected inside it. | |
| req-viz-nested-projection-container-visual-2 | Class Removed On Clear | Implemented | `.tap-viewport-parent` is removed when the node no longer hosts children at the active elevation. | |
| req-viz-nested-projection-container-visual-3 | Default Container Style | Implemented | Container nodes show a subtle background, suppressed icon, and top-positioned label by default. | |
| req-viz-nested-projection-container-visual-4 | Revert On Remove | Implemented | Removing the class reverts the node to its normal leaf visual. | |

#### Future

Allow layout authors to customize container visual per entity type if different parent types need different visual treatments. Consider header bands, colored borders, or other richer chrome.


### Additive Elevation Nesting
----
RID: `req-viz-nested-projection-additive-elevations`
Status: `Approved for Development`

Deeper elevations extend the nesting chain without removing higher-level structure.

#### Implementation

Each elevation declares its full nesting chain via the `relationships` array in its `projectNested` call. Deeper elevations include all relationships from shallower elevations plus additional levels.

For the LOTR saga example:

- **Saga-level** declares: `realm → location`, `location → character` (3 levels visible)
- **Character-view** declares: `realm → location`, `location → character`, `character → artifact` (4 levels visible)

The "assert scene state on entry" invariant means each elevation's layout is a complete declaration of nesting truth. There is no incremental-add semantic — the full chain is stated each time. The runtime clears prior nesting state and re-resolves from scratch on each elevation entry.

This means:
- zooming deeper adds visual information (more levels of children become visible)
- zooming shallower hides deeper content (elevation-hidden class) without removing it
- the user never loses context about where they are in the hierarchy

#### Development

Additive elevation nesting is the "magnify and enhance" model applied to nesting structure. The user's journey is always additive — you see more as you go deeper, never less of what was already visible.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-additive-elevations-1 | Full Chain Declared | Approved for Development | Each elevation declares the complete nesting chain for its scene, not just the delta from the previous elevation. | |
| req-viz-nested-projection-additive-elevations-2 | Deeper Adds Levels | Approved for Development | Deeper elevations add nesting levels visible to the user. | |
| req-viz-nested-projection-additive-elevations-3 | Shallower Hides | Approved for Development | Shallower elevations hide deeper content via elevation-hidden class rather than removing. | |
| req-viz-nested-projection-additive-elevations-4 | Context Preserved | Approved for Development | Higher-level structure (realms, locations) remains visible at deeper elevations. | |

#### Future

Consider whether very deep nesting chains (5+ levels) need progressive disclosure to avoid multiplicative scale making deep nodes illegibly small.


### Scene-Wide Elevation Activation
----
RID: `req-viz-nested-projection-scene-activation`
Status: `Approved for Development`

Elevation switching remains scene-wide in v1 even though nested projection is local to each parent box.

#### Implementation

The active elevation is still chosen by projection runtime zoom thresholds. When the scene crosses an elevation boundary:

- the new elevation activates for the whole scene
- every eligible parent at that elevation renders its nested content
- double-tap remains a shortcut for "zoom to the next level centered on this location"
- per-node independent expansion is deferred

Nested projection changes how content is rendered inside parent boxes. It does not yet change the scene-wide activation model.

#### Development

This keeps the first implementation tractable. The geometry contract gets much cleaner without forcing TAP to solve selective per-node expansion at the same time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-scene-activation-1 | Whole Scene Activates | Approved for Development | Crossing an elevation threshold activates the deeper scene for all eligible parents. | |
| req-viz-nested-projection-scene-activation-2 | Double-Tap Remains Shortcut | Approved for Development | Double-tap remains a navigation shortcut to the next level centered on the tapped location. | |
| req-viz-nested-projection-scene-activation-3 | Per-Node Expansion Deferred | Approved for Development | Independent per-node zoom/expansion behavior is explicitly deferred. | |

#### Future

Per-node selective expansion is a plausible later refinement built on top of the stable geometry contract.


### Runtime Simplification Direction
----
RID: `req-viz-nested-projection-runtime-simplification`
Status: `Approved for Development`

Camera and focus logic that exists primarily to hide geometry discontinuities is transitional under the nested projection model.

#### Implementation

Under the current runtime, scroll-driven elevation changes use viewport-preservation logic such as cursor tracking, hero-node selection, ancestor fallback, and post-layout pan correction. Those mechanisms exist because deeper elevations currently change parent geometry in ways that would otherwise produce visible jumps.

Under this specification:

- geometry continuity is the primary fix (stable bounding box)
- camera compensation is not the primary architecture
- hero-node anchoring, focus gyrations, and similar choreography should be treated as transitional and removed once the nested projection model is implemented
- double-tap centering remains valid as a direct navigation affordance rather than a geometry patch

Code targeted for removal:

- `cytoscape-tap-dimensions.js` — anchor children, `layoutRecursive`, manual grid (replaced by `nested-projection.js`)
- Hero-node selection and cursor tracking in `projection.js`
- Ancestor-chain fallback in `projection.js`
- Post-layout pan correction in `projection.js`
- DOM parent-label overlay in `panel-graph.js` (replaced by `.tap-viewport-parent` native Cytoscape label positioning)

Code that survives:

- Zoom watcher and elevation activation in `projection.js`
- Hysteresis after commanded transitions
- Double-tap detection and pan-zoom animation
- Transition lock during animations
- `search.js` (runtime search helper)
- `layout-loader.js` (module loading)
- `nesting.js` resolver logic (relationship parsing, edge matching, cycle detection — adapted to stamp data instead of setting compound parents)

#### Development

This requirement is intentionally directional. The new geometry contract should let TAP delete more code than it adds.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-nested-projection-runtime-simplification-1 | Geometry First | Approved for Development | Nested projection treats stable geometry and local scaling as the primary solution to drilldown continuity. | |
| req-viz-nested-projection-runtime-simplification-2 | Camera Tricks Removed | Approved for Development | Hero-node anchoring and viewport choreography are removed, not just deprecated. | |
| req-viz-nested-projection-runtime-simplification-3 | Double-Tap Survives As Navigation | Approved for Development | Double-tap remains as a centering/navigation gesture. | |
| req-viz-nested-projection-runtime-simplification-4 | Tap-Dimensions Retired | Approved for Development | `cytoscape-tap-dimensions.js` is deleted entirely, replaced by `nested-projection.js`. | |

#### Future

Once the new geometry model is implemented, update the projection spec to remove the Deprecating viewport-preservation requirement entirely.
