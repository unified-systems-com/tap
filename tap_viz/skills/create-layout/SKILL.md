---
name: create-layout
description: Write or change how a graph panel arranges its scene — a projection, a Layout entity, a layout_module (JavaScript), arrangements, nesting, sizing, ordering. Use before writing any JavaScript that positions Cytoscape nodes, before adding a projection to a page, and whenever a graph "needs to look different". It starts by asking whether the scene can be expressed as data on tap_viz's runtime, which it usually can.
allowed-tools: Read Write Edit Glob Grep Bash(scripts/dc *) Bash(scripts/uuid7 *) Bash(grep *) Bash(find *) Bash(ls *)
argument-hint: <plugin_slug> <page_or_projection>
---

# Create a Layout

You are changing how a TAP graph panel places its nodes. In TAP Viz a **layout** is a TAP-managed
entity (`tap_viz.models.Layout`) that owns the scene work for one node group within an elevation. It
may reference a **layout_module** (a JavaScript file whose `execute(context)` does procedural work) and
an ordered list of **arrangements** (declarative anchor-relative positioning entities). A **projection**
orchestrates layouts across zoom-driven elevations. Those three words mean exactly that here, the way
the specs use them.

The runtime already does most of the work a layout needs: nesting from graph edges, natural sizing,
two-pass measure/position, five natural inner layouts, arrangements, align-distribute, stacks, scope
boxes, parent labels, drag groups. A good layout is mostly a *configuration* of that runtime. Most of
the layout code written in plugins so far re-implements pieces of it; this skill exists so the next one
does not.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Write programmatic layouts through the layout skill** (8): this is that skill. A layout module
  configures and composes the tap_viz runtime; it does not carry its own geometry helpers.
- **Place and group from the graph** (7): nest from real edges or shared dimensions, order from
  typed fields and data-carried tags, so the view keeps working when the data changes.
- **Grow the owning plugin when a capability is missing** (2): a placement the runtime cannot express
  becomes a tap_viz runtime helper or natural layout, added once by reviewed PR, then configured from
  every plugin that needs it.
- **Name the evidence behind every claim** (12): a layout is verified in a browser by counting what
  rendered, and the PR says what was counted.

## The philosophy, and where it lives

The layout philosophy is written down as tap_viz specs. Read the ones your change touches before
writing anything; they are canon, and where this skill and a spec disagree, the spec wins.

| Spec | What it settles |
| --- | --- |
| [`spec-viz-projection.md`](../../specs/spec-viz-projection.md) | A projection orchestrates layouts across elevations; projections are self-contained. |
| [`spec-viz-elevation.md`](../../specs/spec-viz-elevation.md) | Elevations and the `USES_LAYOUT` hotlink that lists their layouts. |
| [`spec-viz-layouts.md`](../../specs/spec-viz-layouts.md) | The Layout entity (`js_file` and/or `arrangements`), the module contract, the runtime context, execution order, runtime modules. |
| [`spec-viz-nested-projection.md`](../../specs/spec-viz-nested-projection.md) | Leaves are true-sized and containers grow; bounded layers, not Cytoscape compounds; `projectNested`; the natural layouts. |
| [`spec-viz-nesting.md`](../../specs/spec-viz-nesting.md) | The single-hop `(parent)-[:EDGE]->(child)` nesting subset and hidden containment edges. |
| [`spec-viz-arrangement.md`](../../specs/spec-viz-arrangement.md) | Arrangements: declarative, anchor-relative, stackable polish after the module runs. |
| [`spec-viz-align-distribute.md`](../../specs/spec-viz-align-distribute.md) | `alignDistributeHorizontal` / `alignDistributeVertical`, gap, anchor, reactive node anchors. |
| [`spec-viz-stack.md`](../../specs/spec-viz-stack.md) | Collapsing a homogeneous group into one representative with a count. |
| [`spec-viz-panel.md`](../../specs/spec-viz-panel.md) | The graph panel that hosts all of this, including node style and click semantics. |

The graph-panel rules that bit in practice (scene searches, edge-type filters, `icon-badge`, dimension
brackets, verifying by presence) live in the
[`add-panel`](../../../tap_web/skills/add-panel/SKILL.md) skill's graph section. Read it too: most of
what goes wrong with a graph is in the scene, not the drawing.

## Step 1: Choose the least code that expresses the scene

Walk down this ladder and stop at the first rung that works. Each rung is data or configuration on
the runtime; only the last is new code, and it goes to tap_viz.

1. **A `projectNested` call with a natural layout.** Nesting from the grid's own edges, sizes from
   `baseSizes`, and one of the built-in inner layouts per container type (`req-viz-nested-projection-natural-layouts`):
   - `grid` for homogeneous children where order does not matter;
   - `flow` for mixed-size children that should stay dense (`sort: "label" | "area-desc" | "input"`);
   - `align-distribute-vertical` for a declared top-to-bottom order by entity type (`typeOrder`);
   - `tiered-rows` for rows by entity-type membership (`tiers`), such as "load balancers, then compute,
     then data";
   - `ranked` for columns by an integer stage (`_stage`) and in-column order (`_order`, with
     `sort: "order"`), which is how any data-driven row or column placement is expressed.
2. **Data-driven order.** When the order a human wants is a fact, put the fact on the node, not in the
   code: a typed field the collector or seed already fills (an availability zone, a tier, an
   environment), or a neutral `layout:*` tag for design-time intent. The module reads it and stamps
   `_stage` / `_order` for `ranked`, or chooses `typeOrder` / `tiers`. It never compares a label, a
   name substring or an id.
3. **Arrangements for polish.** When a node must sit relative to another after the broad layout
   (a legend beside a box, a row under an anchor), author an Arrangement entity and list it in the
   Layout's `definition.arrangements` (`req-viz-layout-dual-mode`). Arrangements are data: reusable,
   inspectable, and switchable off with `arrangement_control.mode = "none"`.
4. **The runtime helpers.** `alignDistributeHorizontal` / `alignDistributeVertical` for a row or column
   anchored to a live node, `applyStack` for collapsing many alike, `applyScopeBoxes` for a titled
   box around a cross-cutting group, `placeParentLabels` and `applyStandardChrome` for labels and the
   shared look.
5. **A new runtime capability, in tap_viz.** When none of the above expresses the placement, the gap is
   in tap_viz, not in your plugin. Add a natural layout (a pure `(children, opts) → {width, height,
   placements}` function) or a runtime helper under `tap_viz/static/tap_viz/js/runtime/`, with its spec
   requirement, by reviewed PR. Then configure it from your layout. The specs already name the likely
   next ones: horizontal stack, row-packed grid, header carve-outs, plugin-registered natural layouts.

## Step 2: Where the files go

- **Shared geometry lives in tap_viz**: `tap_viz/static/tap_viz/js/runtime/` for helpers and natural
  layouts (`req-viz-layout-runtime-modules`). A plugin never ships a general-purpose helper (walking
  descendants, moving a subtree, wrapping rows, stretching a box to its lane) for other plugins to
  import; that is a tap_viz module waiting to be written.
- **A plugin's layout module** lives at `<plugin>/static/<plugin>/js/projections/<scene>.js`, and it
  belongs to the plugin that owns the scene's vocabulary. It imports the runtime and configures it.
- **The Layout, Elevation and Projection entities are data** in the owning plugin's GRIFT bundle, wired
  by their hotlinks (`USES_LAYOUT`, `USES_ARRANGEMENT`). A page reaches them through its graph panel.
- **An instance or project plugin** (a demo, a customer environment) prefers a vocabulary plugin's
  layout plus its own data. When it does ship a layout module, the module holds configuration and data
  reads only: no geometry of its own.

## Step 3: The module contract

```javascript
import { projectNested } from "/static/tap_viz/js/runtime/nested-projection.js";
import { applyStandardChrome, placeParentLabels } from "/static/tap_viz/js/runtime/chrome.js";

export async function execute(context) {
    const { cy, trigger_reason } = context;          // also: projection, elevation, trigger_node

    // 1. Assert the scene this elevation needs, whatever the previous one left behind.
    // 2. Stamp order from facts on the nodes (typed fields, layout:* tags) — never labels or ids.
    // 3. Declare nesting, sizes and inner layouts; the runtime does the geometry.
    await projectNested(cy, {
        relationships: [
            { name: "vpc-contains-subnet", gryphon: "(parent:aws_core__aws_vpc)-[:PARTITIONED_INTO_SUBNET__aws_core]->(child:aws_core__aws_subnet)" },
            { name: "account-owns-resource", dimension_match: { parent_type: "aws_core__aws_account", dimension: "aws_account" } },
        ],
        baseSizes: { "aws_core__aws_subnet": { width: 160, height: 48 } },
        padding: 24,
        innerLayout: "flow",
        innerLayouts: { "aws_core__aws_vpc": { name: "ranked", sort: "order" } },
    });
    applyStandardChrome(cy);
    placeParentLabels(cy);
    if (trigger_reason === "initial_load") cy.fit(cy.nodes(":visible"), 40);
}
```

What the contract asks (`spec-viz-layouts.md`):

- Export exactly one `async function execute(context)`; the context is `cy`, `projection`,
  `elevation`, `trigger_reason`, `trigger_node` (the last three nullable).
- Assert scene invariants on entry, and be safe to run again: re-entry is the normal case, and state is
  hidden with the `tap-elevation-hidden` class rather than removed.
- Be deterministic: the same graph produces the same scene. Sort with a stable key; never use time or
  randomness.
- Report recoverable oddities as warnings, not exceptions. A thrown layout is recorded and later layouts
  still run.

## Step 4: Nesting comes from the graph

- Declare containment with the single-hop nesting pattern over an edge the grid really carries, or with
  `dimension_match` over a spine dimension (`req-viz-nested-projection-dimension-match`). The runtime
  stamps `_viewport_parent`, hides the consumed edges and couples dragging.
- Containment is positional: no Cytoscape compound parents (`req-viz-nested-projection-bounded-layer`).
- When the containment you want is not on the grid, the fix is vocabulary, not layout. Add the edge
  with [`add-edge`](../../../tap_grid/skills/add-edge/SKILL.md) in the plugin that owns the concept and
  seed or collect it. An invisible grouping box the view needs (a row, a band) is a runtime concern:
  ask for it in tap_viz rather than inventing view-only edges in a plugin.

## Step 5: Sizes, labels and look

- Give every leaf type a `baseSizes` entry; container entries are minimum floors. Never scale leaves to
  fit (`req-viz-nested-projection-no-leaf-compression`).
- Use `padding` / `paddings` for container insets and `parentLabelInset` from `chrome.js` for label room.
- The node style is `icon-badge` unless the maintainer has formally asked otherwise (the `add-panel`
  graph section). A node a module adds must carry `fill_color`, `border_color` and `label_color` in its
  data, or it renders blank.

## Step 6: Verify in a browser, by presence

Use [`drive-browser`](../../../tap_web/skills/drive-browser/SKILL.md). Count what must be there: the
nodes and edges in the panel's data, the containers that should hold children, and zero nodes that
should be gone (a retired node on screen is a finding). Take a screenshot and look at it; a blank frame
is a failed launch, not a pass. Run the layout twice (reload, then an elevation change) and confirm the
scene is the same both times. Say in the PR what you counted and what you looked at.

## Before you open the PR

- Every placement decision traces to an edge, a dimension, a typed field or a `layout:*` tag.
- The module contains no copied helper that tap_viz already provides, and no general helper that belongs
  in tap_viz.
- Any new runtime capability is a separate tap_viz PR with its spec requirement, merged or linked.
- The Layout, Elevation and Projection entities are in GRIFT with their hotlinks.
- The browser check above is in the PR body.
