# Viz Layouts Specification

## Philosophy

A **layout** in TAP Viz is a TAP-managed entity (`tap_viz.models.Layout`) that owns the scene-construction work for one node group within an elevation. A layout may carry two complementary things:

1. **A `layout_module`** — a JavaScript file (referenced by `js_file`) that runs `execute(context)`, doing whatever procedural work the scene needs: fetching data, applying nesting, invoking Cytoscape built-ins, positioning nodes manually, styling. This is the executable broad-strokes pass.
2. **An ordered list of arrangements** — declarative single-anchor positioning rules (see [spec-viz-arrangement.md](spec-viz-arrangement.md)) that refine positions after the module runs. This is the declarative polish pass.

Either, both, or neither may be present. The arrangement system was conceived as an *enhancement on top of* a layout's procedural work — the JS module places everything broadly, then arrangements tweak specific rows. Layouts that don't need procedural logic can ship arrangements alone; layouts that don't need declarative polish can ship a module alone.

The terminology distinction is important and worth being precise about: **"layout"** is the entity (and the role); **"layout_module"** is the JavaScript file the entity may reference. Earlier docs and code sometimes used "tap layout" or "layout" interchangeably for the JS file; the v1 reshape pulls those apart so "layout" exclusively means the entity that composes the work.

Layouts are Cytoscape-oriented. Cytoscape remains the graph runtime that layout modules control. A layout module may call built-in Cytoscape layouts as one tool among several, but the layout-module contract is a TAP Viz runtime contract rather than a Cytoscape plugin contract.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Executable | Layouts are executable code assets rather than purely declarative database payloads. |
| 2. | Cytoscape Oriented | Layout execution is built for the Cytoscape runtime and may leverage built-in Cytoscape layouts. |
| 3. | Deterministic | Given the same context and underlying graph state, a layout should execute predictably. |
| 4. | Comprehensive | A layout may gather data, nest objects, position nodes, and refine the scene in one pass. |
| 5. | Reusable | Layouts can be reused across projections, pages, and other TAP Viz hosts. |
| 6. | File Based | Complex layout logic lives in JavaScript files shipped through TAP or plugin static assets rather than in DB code blobs. |
| 7. | Evolvable | The v0 layout contract should be minimal but strong enough to support future helpers, testing, and alternate hosts. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-layout-artifact | [Layout Artifact](#layout-artifact) | Implemented | A layout is a TAP-managed entity (`tap_viz.models.Layout`) |
| req-viz-layout-shape | [Layout Shape (v0)](#layout-shape-v0) | Deprecated | Superseded by `req-viz-layout-dual-mode`; inline `{name, js_file}` shape no longer used |
| req-viz-layout-dual-mode | [Dual-Mode Layout Definition (v1)](#dual-mode-layout-definition-v1) | Implemented | Layout `definition` carries `js_file` (layout_module) and/or `arrangements` (ordered IDs); both optional |
| req-viz-layout-arrangement-control | [Arrangement Control](#arrangement-control) | In Development | Optional `arrangement_control.mode` (`"all"` \| `"none"`) controls whether referenced arrangements execute on a given page load |
| req-viz-layout-module-contract | [Module Contract](#module-contract) | Implemented | Layout modules export a standard async execute entrypoint |
| req-viz-layout-runtime-context | [Runtime Context](#runtime-context) | Implemented | Layouts receive a locked-in minimal runtime context; `trigger_node` is an optional hint, not a core operand |
| req-viz-layout-capabilities | [Layout Capabilities](#layout-capabilities) | Implemented | Layouts may fetch, mutate, nest, and position the Cytoscape graph; assert scene invariants on entry |
| req-viz-layout-execution | [Execution Model](#execution-model) | Implemented | Layouts execute serially under a host but failures do not block later layouts |
| req-viz-layout-runtime-modules | [Runtime Modules](#runtime-modules) | Implemented | Shared TAP Viz runtime utilities live in `tap_viz/static/tap_viz/js/runtime/` and are imported directly |
| req-viz-layout-warnings-errors | [Warnings And Errors](#warnings-and-errors) | Implemented | Layout runtime distinguishes warnings from errors via `onWarning` / `onError` callbacks |
| req-viz-layout-lotr-example | [LOTR Worked Example](#lotr-worked-example) | Implemented | LOTR saga-stage layout demonstrates the v0 executable layout contract |

## Requirements

### Layout Artifact
----
RID: `req-viz-layout-artifact`

Status: `Implemented`

A tap layout is a TAP-managed layout artifact with a file-backed implementation.

#### Implementation

A tap layout is a TAP Viz concept that references a JavaScript file stored in TAP or plugin static assets. The executable code lives in the file, not in the database payload itself.

#### Development

This keeps complex layout behavior versioned, testable, and shippable through normal TAP and plugin file mechanisms.

#### Future

Define how tap layouts should later relate to graph-managed layout nodes and other reusable artifact shapes.


### Layout Shape (v0)
----
RID: `req-viz-layout-shape`

Status: `Deprecated`

The v0 tap layout object was intentionally minimal — a name + a JS file reference.

#### Status Details

The v0 inline shape (used inside the projection's `definition.elevations[].tap_layouts[]` array) is being superseded by the v1 entity-based dual-mode definition in [Dual-Mode Layout Definition (v1)](#dual-mode-layout-definition-v1). Existing v0-shaped projections continue to work until migrated.

#### Implementation

The v0 tap layout shape contains exactly:

- `name`
- `description`
- `js_file`

`js_file` references a static asset path under the TAP or plugin JavaScript tree.

#### Future

Once the v1 migration ships, this requirement becomes `Deprecated`.


### Dual-Mode Layout Definition (v1)
----
RID: `req-viz-layout-dual-mode`

Status: `Implemented`

A v1 Layout entity's `definition` JSON may carry a `layout_module` reference (the JS file), an ordered list of arrangement entity_ids, both, or neither.

#### Implementation

The v1 Layout `definition` shape:

```json
{
  "js_file": "plugins/genericom/static/genericom/js/projections/ec2-internal.js",
  "arrangements": [
    "<arrangement-entity-id-1>",
    "<arrangement-entity-id-2>",
    "<arrangement-entity-id-3>"
  ]
}
```

Top-level keys:

- `js_file` — string, optional. Path to a layout_module under the TAP or plugin JavaScript tree. When present, the runtime imports the module and runs its `execute(context)` entrypoint per [Module Contract](#module-contract).
- `arrangements` — array of UUIDs, optional. Ordered list of Arrangement entities applied via the `executeArrangements()` runtime helper. Validated by the existing `USES_ARRANGEMENT` hotlink on the Layout model.

Both `js_file` and `arrangements` are optional. Allowed combinations:

| `js_file` | `arrangements` | Behavior |
| --- | --- | --- |
| present | present | Module runs first (broad-strokes positioning); arrangements run after (declarative polish). The genericom EC2 internal layout exercises this combination. |
| present | absent | Module-only layout. The classic v0 behavior; LOTR saga-stage is an example. |
| absent | present | Arrangements-only layout. No procedural logic; declarative positioning rules alone produce the scene. |
| absent | absent | No-op layout. Legal but unusual; the runtime emits an `empty_layout` warning. |

#### Execution Order

Within a single Layout, the runtime sequence is fixed:

1. If `js_file` is present, dynamically import the module and `await module.execute(context)`.
2. If `arrangements` is present, fetch each arrangement's `definition` and call `executeArrangements(cy, [...defs], inputs)` with all of them, in array order, in a single call.

This ordering reflects the conceptual relationship: arrangements refine positions that the module has already established. Reversing the order would have arrangements snap nodes to anchors that the module then displaces.

#### Hotlink

The Layout model already declares the `USES_ARRANGEMENT` hotlink (added in migration 0009):

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

The hotlink validates exact match between `definition.arrangements` (when present) and the outbound `USES_ARRANGEMENT` edge set. When `arrangements` is absent or empty, the edge set is also empty — the hotlink validates trivially.

`js_file` is *not* a hotlink — it points to a static asset path, not an entity. It stays as plain JSON in `definition`.

#### Migration

Existing v0 projections (genericom EC2, LOTR) carry inline `tap_layouts[]` arrays inside their projection definition. Migration:

1. For each inline tap_layout, author a Layout entity with `definition.js_file` populated from the v0 entry's `js_file`.
2. For layouts whose positioning would benefit from declarative refinement (genericom EC2 internal does; LOTR saga-stage does not at this time), author the corresponding Arrangement entities and reference them via `definition.arrangements`.
3. The Elevation entity's `USES_LAYOUT` hotlink replaces the inline `tap_layouts[]` array (see [spec-viz-elevation.md](spec-viz-elevation.md)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-layout-dual-mode-1 | Schema validates dual-mode | Implemented | `FIELD_VALIDATION_SCHEMA` accepts `definition` with `js_file`, `arrangements`, both, or neither. | |
| req-viz-layout-dual-mode-2 | Module runs before arrangements | Implemented | Runtime invokes `js_file`'s `execute()` first, then `executeArrangements()`. | |
| req-viz-layout-dual-mode-3 | Arrangements hotlink validates | Implemented | `USES_ARRANGEMENT` hotlink remains exact-match against `definition.arrangements`. | Existing behavior, restated for v1. |
| req-viz-layout-dual-mode-4 | Empty layout warns | Implemented | Layout with neither `js_file` nor `arrangements` produces an `empty_layout` warning at execution. | Not an error — the layout is legal but probably a misconfiguration. |


### Arrangement Control
----
RID: `req-viz-layout-arrangement-control`

Status: `In Development`

A Layout's `definition` may carry an optional `arrangement_control` object that controls whether the layout's referenced arrangements actually execute at runtime. The hotlink-validated `arrangements` array continues to define what *can* run; `arrangement_control` defines what *does* run on a given page load. When `arrangement_control` is absent, the layout runs every arrangement in declared order (current behavior).

This requirement exists to give operators a standardized affordance for debugging, demoing, and staging arrangement work without having to delete `USES_ARRANGEMENT` edges, mutate `definition.arrangements`, or edit JS modules. The "arrangements wired up" graph (edges + array) stays stable; the "arrangements that fire today" runtime decision becomes a simple, reversible field edit.

The v0 of this requirement intentionally ships only the coarse on/off control via `mode`. Finer-grained selection (subset filtering, sequencing, conditional execution) is deferred to [Future](#future) and should be added in subsequent requirement iterations only when concrete need surfaces.

#### Implementation

The v1 Layout `definition` shape extends to:

```json
{
  "js_file": "plugins/genericom/static/genericom/js/projections/ec2-internal.js",
  "arrangements": [
    "<arrangement-entity-id-1>",
    "<arrangement-entity-id-2>",
    "<arrangement-entity-id-3>"
  ],
  "arrangement_control": {
    "mode": "all"
  }
}
```

`arrangement_control` is an optional object. When present, its only key is:

- **`mode`** — one of `"all"` | `"none"`. Default: `"all"`.
  - `"all"`: run every arrangement in `definition.arrangements`, in declared order. Equivalent to omitting `arrangement_control`.
  - `"none"`: run zero arrangements. The JS module (if any) still runs unaffected.

The `FIELD_VALIDATION_SCHEMA` on the Layout model validates the optional shape: `mode` is one of the two enum values; unknown top-level keys inside `arrangement_control` are rejected at schema time so future expansions of the field are explicit and visible.

#### Hotlink Interaction

`arrangement_control` is a runtime filter only. It does **not** participate in the `USES_ARRANGEMENT` hotlink in any direction:

- `definition.arrangements` continues to define the structural set of arrangement entities the layout depends on, and the `USES_ARRANGEMENT` edge set continues to mirror it exactly.
- Toggling `mode` requires no edge mutations and no migration; only the JSON `definition` field changes.

This separation preserves the "edges describe what is wired up; runtime decides what fires" boundary established by the dual-mode definition.

#### Runtime Behavior

The Layout runtime resolves `arrangement_control` from `definition` and produces the effective list of arrangements to dispatch:

1. If `arrangement_control` is absent, or `mode == "all"`: effective list = `definition.arrangements`.
2. If `mode == "none"`: effective list = `[]`. No arrangements run.

The runtime then resolves the arrangement definitions for the effective list and dispatches them via `executeArrangements()`.

Misconfiguration of `arrangement_control` never throws and never blocks the layout's JS module from running. The runtime context exposed to layout modules is unchanged — the control object is consumed by the Layout runtime itself, not by individual layout modules.

#### Development

Putting `arrangement_control` on Layout (rather than on Elevation or Projection) keeps it co-located with `definition.arrangements`, which is the only place the relevant arrangement IDs are declared. An Elevation that needs different arrangement behavior should reference a different Layout entity rather than reach across the boundary to override Layout internals.

`mode == "none"` is the form used during arrangement debugging and during the Anwar demo prep — it disables the declarative polish pass while leaving the broad-strokes JS module untouched.

Shipping only `"all"` and `"none"` first is a deliberate scoping call. Subset selection, sequencing, and conditional execution are all reasonable extensions, but each carries its own design questions (ID-list vs. named-group, ordering semantics, server-side gating); collapsing them into the v0 ACIDs would invite premature design lock-in. The optional-object shape keeps the door open for those extensions without committing to any of them.

#### Future

- **`mode == "include"` (subset filtering)** — run only the arrangement IDs listed in an `include` array, preserving their relative order from `definition.arrangements`. Useful when iterating on a single arrangement in a stack of three or more.
- **`mode == "exclude"`** — run every arrangement *except* those listed in an `exclude` array. Useful for "everything except this one I'm currently rewriting."
- **`delays_ms`** — array of non-negative integers, one per effective arrangement, that delays each arrangement by the specified milliseconds before execution. Smallest useful sequencing primitive for staged demos and animation prep.
- **Per-arrangement input overrides** — a key that lets the layout pass different `inputs` to specific arrangements without writing per-arrangement modules.
- **Conditional control** — a `mode: "if"` form that runs an arrangement only when a gryphon predicate matches. Powerful, but adds a server query per page load and probably wants its own RID.
- **Named arrangement groups** — when a single layout grows past ~5 arrangements, a `groups` map (name → ordered ID list) plus `mode: "groups"` becomes a more ergonomic include/exclude unit than enumerating IDs.
- **Animation timeline** — once arrangement animations land (see [spec-viz-arrangement.md](spec-viz-arrangement.md) `req-viz-arrangement-execution` Future), any sequencing primitive added here should converge with whatever timeline primitive that requirement settles on rather than diverge into a parallel system.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-layout-arrangement-control-1 | Schema validates control object | Implemented | `_LAYOUT_DEFINITION_SCHEMA` accepts an optional `arrangement_control` object whose only allowed key is `mode` (enum: `"all"` \| `"none"`); rejects unknown keys so future extensions are explicit. | `tap_viz/models.py` |
| req-viz-layout-arrangement-control-2 | Absent control runs all | Implemented | When `arrangement_control` is absent, the projection resolver returns every arrangement definition in declared order — unchanged from v1 baseline. | `tap_viz/panels/graph_panel/projection_resolver.py` |
| req-viz-layout-arrangement-control-3 | Mode `all` runs all | Implemented | When `mode == "all"`, behavior is identical to `arrangement_control` being absent. | Default branch in resolver. |
| req-viz-layout-arrangement-control-4 | Mode `none` skips arrangements | Implemented | When `mode == "none"`, the resolver emits an empty `arrangements` list for the layout. The layout's JS module (if any) is dispatched unaffected by the client runtime. | Primary debug / kludge mode. |
| req-viz-layout-arrangement-control-5 | Hotlink unaffected | Implemented | `USES_ARRANGEMENT` hotlink validation continues to mirror `definition.arrangements` exactly; `arrangement_control` is read at resolve time only and does not create, remove, or otherwise affect arrangement edges. | |


### Module Contract
----
RID: `req-viz-layout-module-contract`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/layout-loader.js

Tap layout JavaScript modules export a standard async entrypoint.

#### Implementation

The v0 tap layout module contract is:

```javascript
export async function execute(context) {
  // layout logic
}
```

Each layout module exports exactly one layout entrypoint named `execute`.

#### Development

This keeps module resolution and runtime invocation simple for the first pass.

#### Future

If multiple exports become useful later, define that explicitly rather than loosening the v0 contract implicitly.


### Runtime Context
----
RID: `req-viz-layout-runtime-context`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/layout-loader.js

Tap layouts receive a locked-in minimal runtime context.

#### Implementation

The v0 layout runtime context contains:

- `cy`
- `projection`
- `elevation`
- `trigger_reason`
- `trigger_node`

Field meanings:

- `cy`
  The active Cytoscape instance.
- `projection`
  The active projection definition when the layout is running under a projection host, otherwise `null`.
- `elevation`
  The active elevation definition when the layout is running under a projection host, otherwise `null`.
- `trigger_reason`
  Why this layout execution was initiated, such as:
  - `initial_load`
  - `zoom_transition`
  - `double_tap`
- `trigger_node`
  Optional hint passed through from the runtime when an elevation transition was triggered by a user gesture aimed at a specific node. Layouts **should not** depend on it for core operation — elevation layouts are scene-wide and must assert their target scene state for every applicable node, not just a trigger target. Carried in the context for advanced uses (e.g. highlighting) and for backward compatibility.

`projection`, `elevation`, and `trigger_node` are nullable so layouts may be reused outside projection-driven hosts.

#### Development

Keeping the context small makes the runtime contract more stable and pushes reusable functionality into shared imported modules rather than callback parameter sprawl.

#### Future

Add more context fields only when concrete runtime experience shows they are necessary.


### Layout Capabilities
----
RID: `req-viz-layout-capabilities`

Status: `Implemented`

Trace: `narrative` — an allowance, not a mechanism: nothing derives or enforces "layouts may do all scene work"; the runtime simply does not restrict, and the enforceable pieces (context shape, serial execution, warnings) live in the sibling requirements

Tap layouts may perform all scene work needed to get the desired pieces onto the Cytoscape board and put them in place.

#### Implementation

In v0, a tap layout may:

- fetch additional graph data
- add or update nodes and edges
- hide or un-hide existing nodes and edges (via the `.tap-elevation-hidden` class convention described in `spec-viz-projection.md`)
- declare nested projection via `projectNested` (see `spec-viz-nested-projection.md`)
- invoke one or more built-in Cytoscape layouts
- position nodes manually
- adjust styling or scaling
- inspect the whole active Cytoscape graph

Layouts are authoritative for nesting decisions during their execution.

Under a projection host, layouts are also responsible for **asserting scene invariants on entry**: each layout should put the scene into the state its elevation requires regardless of what the previous elevation left behind. There is no separate exit hook — teardown is handled implicitly by the next elevation's entry assertion. This keeps each layout's behavior self-contained and lets the runtime stay oblivious to elevation-specific cleanup rules.

When a layout uses nesting, it should call `projectNested` from `tap_viz/static/tap_viz/js/runtime/nested-projection.js`. That module uses the Gryphon-like nesting relationship format as the canonical expression for layout-owned nesting and handles viewport derivation, scale computation, and constrained layout execution.

If a layout changes an existing nesting relationship and re-nests an object elsewhere, the runtime must emit a `layout_nesting_override` warning.

#### Development

This requirement reflects the central design decision of the new layout model: one layout does whatever work it needs to do to make its scene real.

#### Future

- Add viewport-aware optimization helpers for very large graph scenes.


### Execution Model
----
RID: `req-viz-layout-execution`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/layout-loader.js

Tap layouts execute serially under a host runtime, but a failed layout does not block later layouts from running.

#### Implementation

Under a projection elevation or another TAP Viz host, tap layouts:

- execute serially in the order defined by the host
- mutate `cy` directly
- signal completion by promise resolution

If a layout throws or rejects:

- the runtime records an error for that layout
- the failed layout stops
- later layouts in the same host sequence still run

This behavior exists so partially successful visual progress remains visible and debuggable even when one layout fails.

#### Development

These are visuals, not mission-critical transactions. It is more valuable to preserve visible progress and inspect partial success than to abort the whole rendering pipeline at the first failure.

#### Future

Define richer runtime reporting and visualization of per-layout execution state.


### Runtime Modules
----
RID: `req-viz-layout-runtime-modules`

Status: `Implemented`

Trace: `process` — a path-namespace authoring convention (projections/ for executables, runtime/ for shared utilities); conformance is editorial, imports are authored per-module

Shared TAP Viz runtime utilities live in static JavaScript modules and are imported directly by layout files.

#### Implementation

Shared utilities are not passed in `context`. Layout implementations import them directly from TAP Viz-owned static JavaScript modules.

The v0 path namespaces are:

- `tap_viz/static/tap_viz/js/projections/`
  executable projection and layout files
- `tap_viz/static/tap_viz/js/runtime/`
  shared TAP Viz runtime modules

Plugin-shipped layout files may also live under corresponding plugin static paths while following the same conceptual split between executable layout modules and shared runtime support.

#### Development

This keeps the runtime context small and lets utility code evolve as normal JavaScript modules rather than callback payload baggage.

#### Future

Define plugin-specific path conventions more explicitly once the first plugin layouts are moved into place.


### Warnings And Errors
----
RID: `req-viz-layout-warnings-errors`

Status: `Implemented`

Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/layout-loader.js

Tap layout runtime distinguishes warnings from errors.

#### Implementation

Warnings represent recoverable issues where execution may continue.

Errors represent a thrown exception or rejected promise from a layout execution.

The runtime should support both warning and error reporting and should record them at layout granularity.

The v0 warning category `layout_nesting_override` means:

- a layout changed an existing nesting relationship for an object
- the object was re-nested elsewhere
- execution continued

#### Development

Keeping warnings and errors separate makes layout failures easier to reason about and keeps recoverable scene oddities from being treated as fatal execution failures.

#### Future

Integrate layout warnings and errors into TAP's richer runtime diagnostics once those systems are defined.


### LOTR Worked Example
----
RID: `req-viz-layout-lotr-example`

Status: `Implemented`

Trace: `external` — lotr plugin (evicted; the worked saga-stage layout example lives there)

The LOTR saga-stage layout should be the first worked example of the executable tap layout contract.

#### Implementation

Representative module shape:

```javascript
import { projectNested } from "/static/tap_viz/js/runtime/nested-projection.js";

export async function execute(context) {
  const { cy, trigger_reason } = context;

  // Hide artifacts from prior character-view (re-entry cache pattern).
  cy.nodes('[entity_type="artifact"]').addClass("tap-elevation-hidden");
  cy.edges('[edge_type="WIELDS"]').addClass("tap-elevation-hidden");

  // Declare nested projection: realm → location → character.
  // Runtime handles viewport derivation, scale, and constrained layout.
  await projectNested(cy, {
    relationships: [
      { name: "realm-contains-location", gryphon: "(parent:realm)-[:CONTAINS]->(child:location)" },
      { name: "location-contains-character", gryphon: "(parent:location)<-[:LOCATED_IN]-(child:character)" }
    ],
    baseSizes: {
      realm:     { width: 300, height: 200 },
      location:  { width: 80, height: 60 },
      character: { width: 40, height: 40 }
    },
    padding: 10,
    innerLayout: "grid"
  });

  // Fit on initial load only; scroll re-entry preserves user viewport.
  if (trigger_reason === "initial_load") {
    cy.fit(cy.nodes(":visible"), 40);
  }
}
```

This example is illustrative rather than normative in its exact module internals, but it should demonstrate:

- direct imports from TAP Viz runtime modules
- the standard `execute(context)` contract
- the `projectNested` API for declaring nesting, sizes, and layout in one call
- the `initial_load` trigger reason
- the elevation-hidden re-entry cache pattern
- whole-graph Cytoscape access

#### Development

The LOTR example is the proving ground for the v0 layout model and should be treated as the place where the contract is validated before the model grows.

#### Future

Replace illustrative placeholder paths and helper names with the real plugin-backed LOTR layout module once implementation is finalized.
