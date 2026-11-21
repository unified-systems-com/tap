# Viz Icon Node Specification

## Philosophy

An **icon node** is the top-most representation of a thing. Where the standard node is a box with its name in the middle and its type icon as a small badge in the upper-left corner, an icon node turns that around: the icon is the centre of the card and the name sits below it. It says "this thing is here", and nothing more.

The mode exists because a scene does not always want to show how a thing is built. An internet gateway, a load balancer, a database, a person, a person's computer, or a whole forge are all places where the interesting fact is that the thing exists and how it connects to its neighbours. Drawing their internals would bury the shape of the system under detail. A layout chooses, node by node, which things are shown as icons and which are opened up, so the same scene can mix the two.

An icon node is a **runtime primitive**, not a projection-level style. A layout module calls it from `execute(context)` against the nodes it selected, the same way it calls the stack, nesting and arrangement runtimes. It composes with them rather than replacing any of them: an icon node is still a real graph node with its real edges, it can sit inside a container, it can carry status badges, and a set of icon nodes can be stacked.

The card's size is a **parameter**, not a constant. A scene sets it per call and per node, and the runtime can change it later. This is deliberate: the icon form is expected to be pre-scaled so that zooming in can grow it, and to morph into the standard, opened-up view of the same node. Both of those are anticipated by the size contract here and are specified as Proposed requirements below.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Icon-Centric | The type icon is the centre of the card; the name is below it, outside the card. |
| 2. | Top-Most | An icon node is terminal: what it contains is not drawn. |
| 3. | Sizeable | Width and height are settable per call and per node, and changeable after the fact. |
| 4. | Layout-Called | A reusable runtime primitive invoked by a layout module, not bound to a projection or a domain. |
| 5. | Edge-Honest | Edges attach to the card as to any node. Edges of hidden contents are not redrawn onto it. |
| 6. | Composable | Coexists with containers, status badges and stacks without special-casing. |
| 7. | Idempotent | Safe to re-run across elevation transitions; a re-run rebuilds cleanly. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-icon-node-primitive | [Runtime Primitive](#runtime-primitive) | Implemented | `applyIconNodes(cy, opts)` returns a handle `{destroy, resize, count}` |
| req-viz-icon-node-form | [Card Form](#card-form) | Implemented | Bordered, filled card with the type icon centred |
| req-viz-icon-node-label | [Label Position](#label-position) | Implemented | The name sits outside the card, below it, wrapped to the card's width |
| req-viz-icon-node-solo | [Icon-Centric-Solo](#icon-centric-solo) | Implemented | `solo: true` drops the card: no border and no fill, only the icon and the name |
| req-viz-icon-node-size | [Settable Dimensions](#settable-dimensions) | Implemented | `width` / `height` per call, per-node override, change after the fact with `resize` |
| req-viz-icon-node-terminal | [Terminal Representation](#terminal-representation) | Implemented | Nesting treats an icon node as a leaf and hides what it would contain |
| req-viz-icon-node-edges | [Edges](#edges) | Implemented | Edges to hidden contents are dropped, never re-pointed |
| req-viz-icon-node-composes | [Composition](#composition) | Implemented | No type-icon badge on an icon node; status badges and stacks unchanged |
| req-viz-icon-node-fallback | [Missing Icon](#missing-icon) | Implemented | A node without an icon renders as a card with its name |
| req-viz-icon-node-idempotent | [Idempotent Re-Run](#idempotent-re-run) | Implemented | A re-run restores what the last pass changed before it applies |
| req-viz-icon-node-prescale | [Pre-Scaling For Zoom](#pre-scaling-for-zoom) | Proposed | Grow the card with zoom so the icon stays legible |
| req-viz-icon-node-morph | [Morph To Standard View](#morph-to-standard-view) | Proposed | Resize and morph an icon node into the standard, opened-up node |
| req-viz-icon-node-declarative | [Declarative Form](#declarative-form) | Proposed | An `icon_node` block on the Layout entity |
| req-viz-icon-node-drill | [Drill](#drill) | Proposed | Reach an icon node's contents through an elevation |

## Requirements

### Runtime Primitive
----
RID: `req-viz-icon-node-primitive`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/icon-node.js

The icon node is delivered as a client-side runtime module, `tap_viz/static/tap_viz/js/runtime/icon-node.js`, exporting `applyIconNodes(cy, opts)`. A layout module calls it from `execute(context)` before it calls `projectNested`, passing the nodes it chose. Choosing the nodes is the layout's responsibility (an entity type, a dimension, a tag, a Gryphon query); the primitive owns the form, the size and the bookkeeping.

`applyIconNodes` returns a handle `{destroy, resize, count}`. `destroy()` restores every node it changed. `resize(size)` changes the size of the whole set (see [Settable Dimensions](#settable-dimensions)). `count` is the number of nodes it applied to.

Inputs (`opts`): `members` (a Cytoscape collection, required), `width` and `height` (default 96), `iconRatio` (the icon's share of the card, default 0.6) and `iconNodeId` (a key for [Idempotent Re-Run](#idempotent-re-run), default `"default"`).

### Card Form
----
RID: `req-viz-icon-node-form`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/panel-graph.js

An icon node renders as a rounded square card with a visible border and a visible fill. The node's type icon is drawn in the centre of the card, `iconRatio` of the card's shorter side. There is no type-icon badge in the upper-left corner and the name is not drawn inside the card. The card uses a neutral fill and border and does not take the model palette, so a row of icon nodes of different types reads as one family.

### Label Position
----
RID: `req-viz-icon-node-label`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/panel-graph.js

The node's name is drawn outside the card, centred below it. Long names wrap at a multiple of the card's width (1.4 times, never under 96 model units), so the names of neighbouring icon nodes do not run together. The name belongs to the node and moves and scales with it. Whether the name later moves inside the card is left open; it is a style decision, not a structural one, and changing it touches only the style rule.

### Icon-Centric-Solo
----
RID: `req-viz-icon-node-solo`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/icon-node.js

Icon-centric-solo is the icon node without its card. `applyIconNodes` takes `solo: true` (default false), and the node then draws no border and no fill: only the type icon and the name below it. The icon fills the node's box (default `iconRatio` 1 in place of 0.6), so the node's width and height are the icon's size. Solo is a flag on the same form, not a second primitive: size, terminal contents, edges, badges, stacking, fallback and re-run behave exactly as for the card form.

The box is still there, invisible. Edges attach to its boundary and a tap on it selects the node, as for any node. A solo node with no resolved icon would draw nothing but its name, so the missing-icon fallback draws the card form for it (see [Missing Icon](#missing-icon)).

### Settable Dimensions
----
RID: `req-viz-icon-node-size`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/icon-node.js

The card's dimensions are inputs, never constants. `applyIconNodes` takes `width` and `height` for the set. Each node records its own size on its data (`_icon_w`, `_icon_h`), and nesting reads that size in place of the type's `baseSizes` entry, so a layout can size one icon node differently from another of the same type. `handle.resize({width, height})` changes the size of every node the call applied to, and a node may also be resized singly by writing its own `_icon_w` and `_icon_h` and re-running the layout.

A size is a pair of positive numbers in model units. A call that gives anything else leaves the nodes at their previous size.

### Terminal Representation
----
RID: `req-viz-icon-node-terminal`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

`projectNested` treats an icon node as a leaf. The nodes that nesting would have placed inside it, and everything inside those, are hidden for the pass (the same `tap-elevation-hidden` class an elevation uses) and take no part in sizing or placement. The icon node is sized from its own size, not grown to fit contents. An icon node that has no contents is simply a leaf. The hidden nodes come back on the next pass if the node is no longer an icon node.

### Edges
----
RID: `req-viz-icon-node-edges`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/nested-projection.js

Edges between an icon node and a node that is shown are drawn as for any node. An edge that has a hidden endpoint, because that endpoint is inside an icon node, is not drawn. It is not re-pointed onto the icon node. A drawn line is always an edge that exists in the grid between the two nodes it joins, with exactly one exception; an icon node never stands in for the lines of its contents.

**The one exception: a collapsed compound edge** (`req-viz-compound-edge`, amended on Issue# 1261 - tap). A compound edge is stored as a middle node and two or more real edges (`req-grid-edge-compound`), and a page should read it as the single arrow from sender to receiver that it means. So the compound-edge runtime draws one synthetic line between the sender and the receiver while the stored pieces are hidden. It is allowed because it stands for pieces that all exist in the grid, between exactly the two nodes it joins — its ends are the compound edge's real ends, never a node standing in for one — and because it is marked (`_is_compound_edge`, `_compound_id` naming the middle node) and expands on tap into those stored pieces, so nothing it says is unverifiable from the page. The icon-node rule still binds it: when either end is hidden or absent, no arrow is drawn and nothing is re-pointed.

### Composition
----
RID: `req-viz-icon-node-composes`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/badge-nodes.js

An icon node already shows its type icon, so the type-icon badge pass skips it. Status badges are unchanged and anchor to the card's corner as to any host. An icon node may be a child of a container, and it may be a member of a stack, in which case the stack's cards and chip follow the card's size.

### Missing Icon
----
RID: `req-viz-icon-node-fallback`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/panel-graph.js

A node with no resolved icon renders as the same card with its name below and nothing in the middle. It is never dropped and never broken. A solo node with no icon also renders as the card, because a solo node with nothing to draw would be invisible.

### Idempotent Re-Run
----
RID: `req-viz-icon-node-idempotent`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/icon-node.js

A call is keyed by `iconNodeId`. Re-invoking `applyIconNodes` with the same key first restores the nodes the previous call changed (their data flags and inline styles) and then applies afresh. Re-runs do not accumulate. Distinct keys are independent.

### Pre-Scaling For Zoom
----
RID: `req-viz-icon-node-prescale`

Status: `Proposed`

An icon node is expected to be pre-scaled so that zooming in can grow the card instead of leaving a small card in a large view. The size contract above is the seam: a layout, or the projection runtime on a zoom change, calls `handle.resize` with the size for the current zoom. The rule that maps a zoom level to a size, and whether it is declared on the projection or on the elevation, is not yet fixed.

### Morph To Standard View
----
RID: `req-viz-icon-node-morph`

Status: `Proposed`

An icon node may resize and morph into the standard view of the same node: a container that shows its contents, or a leaf with the name inside and the type-icon badge. The morph is a change of representation on one node, so it keeps the node's identity, position and edges, and animates the card growing into the box with the contents appearing as they fit. The trigger is zoom or a gesture; it is expected to use an elevation boundary the way [Drill](#drill) does. How a node stays in place while it grows, and how the surrounding layout makes room, are open.

### Declarative Form
----
RID: `req-viz-icon-node-declarative`

Status: `Proposed`

Once the procedural API has proven out against real consumers, a declarative `icon_node` block may be added to the Layout entity: member selection by Gryphon plus `width`, `height` and `iconRatio`, resolved by the runtime the way arrangements are.

### Drill
----
RID: `req-viz-icon-node-drill`

Status: `Proposed`

Revealing an icon node's contents is left to the existing elevation mechanism: a projection may target a lower elevation whose layout does not mark the node as an icon node, reached by double-tapping the card. No new interaction model is introduced by the icon node itself.
