# Viz Align-Distribute Specification

## Philosophy

A scene often contains a small set of peer nodes that should simply read as a tidy line — a fan of artifacts, the steps of a deploy flow, the workflows in a repo. Hand-positioning them (pick an x, add a width, repeat) is the kind of arithmetic a layout module shouldn't carry inline. **Align-distribute** is the runtime helper for it: give it a node set and it aligns them on one axis and distributes them evenly along the other, with a configurable gap.

It is the **standalone companion** to the `align-distribute-vertical` *natural layout* (`spec-viz-nested-projection.md` § Natural Layouts). The natural layout arranges a **compound's children** and returns relative geometry the nesting runtime applies; this helper operates on **any caller-supplied node set** with no container, setting absolute positions directly — the same alignment idea exposed for layout modules that position nodes by hand (e.g. `landing-finalize.js`). The two are siblings; unifying their shared core is a future cleanup, not a contract.

Two modes, one helper:

- **Just make them pretty** — pass a node set; they're aligned + distributed. Use inside a container that already supplies its own framing (e.g. a repo's workflows, which only need clean distribution inside the repo box).
- **Give it a label** — pass `label`; a titled box is drawn around the group, reusing the scope-box overlay (`spec-viz-layouts`). Use when the group is a named region in its own right (e.g. "Signed Artifacts", "Deploy & Bootstrap").

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-align-distribute-helper | [Runtime Helper](#runtime-helper) | Implemented | `alignDistributeHorizontal(cy, opts)` / `alignDistributeVertical(cy, opts)` |
| req-viz-align-distribute-gap | [Gap](#gap) | Implemented | Edge-to-edge spacing along the main axis; `gap` (alias `spacing`), default 24 |
| req-viz-align-distribute-anchor | [Anchor](#anchor) | Implemented | `anchor` point + `anchorMode` (`start` \| `center`) |
| req-viz-align-distribute-label | [Optional Label](#optional-label) | Implemented | `label` draws a titled scope-box around the group; omit for none |
| req-viz-align-distribute-order | [Order](#order) | Implemented | Members sorted by label by default; `sort: false` preserves caller order |
| req-viz-align-distribute-step | [Staircase Step](#staircase-step) | Implemented | `step` drops each successive node on the cross axis; `stepFrom` picks the baseline end |
| req-viz-align-distribute-node-anchor | [Reactive Node Anchor](#reactive-node-anchor) | Implemented | `anchorNode` tracks a node's live bbox + re-resolves on its events; `offset` nudges from it |

## Runtime Helper

RID: `req-viz-align-distribute-helper`

Status: `Implemented`

`tap_viz/static/tap_viz/js/runtime/align-distribute.js` exports `alignDistributeHorizontal(cy, opts)` and `alignDistributeVertical(cy, opts)`, sharing one core (axis-parameterized). A layout module calls it from `execute(context)` after collecting the node set, the same way it calls `applyStack` / `applyScopeBoxes`. Returns `{destroy, members}`; `destroy()` removes the label box (if any).

`opts`: `members` (the node set), `anchor` (`{x,y}`, defaults to the first member's position), `anchorNode` + `offset` (anchor on a live node, see below), `anchorMode` (`"start"` — anchor is the leading edge, default; `"center"` — anchor is the midpoint; defaults to `"center"` when `anchorNode` is set), `gap` / `spacing` (default 24), `sort` (default true), `step` + `stepFrom` (optional staircase, see below), `reactive` (default true when `anchorNode` set), `label` (optional), `style` (optional box style).

## Gap

RID: `req-viz-align-distribute-gap`

Status: `Implemented`

`gap` (alias `spacing`) is the **edge-to-edge** distance between consecutive nodes along the main axis (the helper respects each node's own size), matching the `gap` semantics of the `align-distribute-vertical` natural layout. Cross-axis position is uniform (the alignment line).

## Anchor

RID: `req-viz-align-distribute-anchor`

Status: `Implemented`

`anchor` is the reference point. `anchorMode: "start"` (default) treats it as the leading (left/top) edge and grows the line from it; `"center"` treats it as the line's midpoint. The cross-axis component of `anchor` is the alignment line.

## Optional Label

RID: `req-viz-align-distribute-label`

Status: `Implemented`

When `label` is set, a titled box is drawn around the laid-out group by delegating to `applyScopeBoxes` (which is additive — it never clobbers other scope boxes). When `label` is omitted, only positioning happens. This is the single knob distinguishing "a named region" from "a clean row inside an existing container".

## Order

RID: `req-viz-align-distribute-order`

Status: `Implemented`

Members are ordered by their display label before layout (stable, readable). Pass `sort: false` to preserve the caller's collection order when the caller has already imposed a meaningful sequence.

## Staircase Step

RID: `req-viz-align-distribute-step`

Status: `Implemented`

By default the cross-axis position is uniform (a flat line). Set `step` to offset each successive node on the cross axis by a fixed amount — a **staircase**. For a horizontal row this is a downward drop per node, so the labels that hang below each node land at staggered heights and stop overlapping (the originating need: a row of file cards whose filename labels collided when flat).

`stepFrom` picks the **baseline** end — the un-stepped node the cascade descends *away* from: `"left"` / `"right"` for horizontal (default `"left"`), `"top"` / `"bottom"` for vertical (default `"top"`). With `stepFrom: "left"` the leftmost node sits on the anchor line and each node to the right drops one `step`, so the row reads as a gentle down-and-to-the-right cascade. `step` defaults to `0` (flat); `stepFrom` is only meaningful when `step != 0`.

A labeled group's box wraps the stepped extent (the scope-box bbox spans the staircase), so the titled box simply grows to enclose the diagonal.

## Reactive Node Anchor

RID: `req-viz-align-distribute-node-anchor`

Status: `Implemented`

A static `anchor` point is a snapshot — it's read once, at call time. But a layout module often wants to position a node *relative to a container that is still settling*: a compound's bounding box shifts after the call returns (post-layout reflows — badge overlays, stack settle — and user drags). A center computed at call time then lands a few pixels off the container's final box.

`anchorNode` solves this by anchoring on a **node's live bounding box** instead of a fixed point: the row's main-axis center tracks the node's bbox center (the cross-axis line comes from `anchor` when supplied, else the node's bbox center), and — unless `reactive: false` — the layout **re-resolves whenever that node fires `position`/`bounds`, plus on the cy `layoutstop`**. This mirrors how the scope-box overlay (`spec-viz-layouts`) tracks its members, and the stack primitive's post-layout `auto`-direction settle (`spec-viz-stack`): event-bound re-resolution is the established runtime idiom for "stay correct as the scene settles", not a one-shot pass. `offset` (`{x,y}`) nudges the resolved anchor — e.g. to drop the row below the anchor node.

Loop safety: the anchor node must not be an **ancestor** of any member — repositioning a member would change the ancestor's bbox and re-fire the handler endlessly. The helper detects this, skips the reactive bind, and warns. The returned handle's `destroy()` unbinds the listeners (Cytoscape's `node.on()` does not honor event namespaces for `position`/`bounds`, so the binding uses plain events and unbinds by handler reference).
