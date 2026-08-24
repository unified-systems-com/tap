# Viz Projection Specification

## Philosophy

A projection is TAP Viz's highest-order visual perspective on a graph domain. It defines how a person moves through a scene across multiple zoom-driven elevations, what layouts become active at each elevation, and how additional graph detail is introduced as the user descends into the view.

A projection is not a Cytoscape layout. A projection orchestrates layouts. It is the object that gives meaning to moving from a suite-level view to a product view, from a product view to a network view, and from a network view to a host or application view. It is the bridge between a human visual journey and the underlying graph data.

The first projection architecture should favor executable layout logic over attempting to encode all visual behavior in database JSON. Layouts are deterministic Cytoscape-specific functions stored as code assets and referenced by TAP-managed layout objects. This keeps complex layout behavior in code, keeps orchestration in TAP-owned projection metadata, and avoids forcing rich scene construction into an overly declarative storage format too early.

Projections should also be self-contained. A projection must be able to define a useful visual experience without requiring model-level hints or global nesting rules. Those may later exist as defaults, helpers, or optimizations, but the projection must remain capable of fully defining its own scene behavior.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Perspective | A projection defines a coherent visual perspective over a graph domain rather than a single static layout. |
| 2. | Elevation Driven | A projection organizes the visual journey into named zoom-driven elevations. |
| 3. | Layout Oriented | A projection activates one or more executable layouts at each elevation. |
| 4. | Incremental | A projection may introduce new graph data as the user moves into deeper elevations. |
| 5. | Self-Contained | A projection can define its own view behavior without depending on model-level display hints. |
| 6. | Cytoscape Native | Projection execution is built around Cytoscape runtime behavior and Cytoscape-specific layouts. |
| 7. | Evolvable | The projection contract should support future work on scaling, nesting, styling, and alternate elevation controls without redesigning the model. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-projection-artifact | [Projection Artifact](#projection-artifact) | Implemented | Projection is a first-class TAP Viz artifact (`tap_viz.models.Projection`) |
| req-viz-projection-structure | [Projection Structure](#projection-structure) | Deprecated | Superseded by `req-viz-projection-entity-structure`; v0 inline-elevation shape no longer accepted |
| req-viz-projection-entity-structure | [Projection Entity Structure (v1)](#projection-entity-structure-v1) | Implemented | Elevations referenced as entities via `USES_ELEVATION` and `USES_DEFAULT_ELEVATION` hotlinks |
| req-viz-projection-elevation | [Elevation Model](#elevation-model) | Deprecated | Inline elevation config replaced by Elevation entity per `spec-viz-elevation.md` |
| req-viz-projection-layout-orchestration | [Layout Orchestration](#layout-orchestration) | Deprecated | Inline `tap_layouts[]` replaced by Layout entities composed via `USES_LAYOUT` |
| req-viz-projection-elevation-orchestration | [Elevation Orchestration (v1)](#elevation-orchestration-v1) | Implemented | Projections compose Elevation entities; layouts are owned by Elevation per `spec-viz-elevation.md` |
| req-viz-projection-layout-runtime | [Layout Runtime](#layout-runtime) | Implemented | Runtime context (`cy`, `projection`, `elevation`, `trigger_reason`, `trigger_node`) passed to `execute(context)` |
| req-viz-projection-incremental-loading | [Incremental Loading](#incremental-loading) | Implemented | `character-view.js` demonstrates runtime sub-search via `runtime/search.js` |
| req-viz-projection-self-contained | [Self-Contained Execution](#self-contained-execution) | Implemented | LOTR saga projection defines nesting, dimensions, and layout without model-level hints |
| req-viz-projection-lotr-monolith | [LOTR Monolithic Example](#lotr-monolithic-example) | Implemented | Wired in `plugins/lotr/grift/web.grift.json` + saga-stage / character-view modules |
| req-viz-projection-viewport-preservation | [Viewport Preservation](#viewport-preservation) | Deprecating | Transitional cursor-tracked hero-node anchoring that compensates for geometry discontinuities; see `spec-viz-nested-projection.md` |
| req-viz-projection-elevation-invariants | [Elevation Invariants](#elevation-invariants) | Implemented | Layouts assert scene state on entry; elevation-hidden class lets transient content survive across transitions without re-fetching |
| req-viz-projection-viewport-scoped-expansion | [Viewport-Scoped Expansion](#viewport-scoped-expansion) | Backlog | Per-visible-viewport elevation expansion for large graphs |
| req-viz-projection-min-zoom | [Minimum Zoom](#minimum-zoom) | Implemented | Optional floor on zoom-out; `"fit"` pins to post-layout zoom level |
| req-viz-projection-lock-nodes | [Lock Nodes](#lock-nodes) | Implemented | Optional flag to freeze all node positions after layout |

## Requirements

### Projection Artifact
----
RID: `req-viz-projection-artifact`
Status: `Implemented`

A projection is a first-class TAP Viz artifact that defines a reusable visual perspective over graph data.

#### Implementation

The projection artifact should be TAP-managed and reusable. It is not just a page-local config blob and not just a raw Cytoscape options object. A projection includes human-readable metadata plus projection-specific definition data.

#### Development

Treating projections as first-class artifacts allows the same perspective to be reused in multiple panels or pages and keeps complex scene orchestration out of panel-local config.

#### Future

Define the exact storage model and relation to existing layout entities in a follow-up pass.


### Projection Structure
----
RID: `req-viz-projection-structure`
Status: `Deprecated`

A projection owns the top-level structure needed to initialize and advance a visual perspective.

#### Status Details

The v0 monolithic shape — inline elevations and inline tap-layout references — is being superseded by the entity-based shape in [Projection Entity Structure (v1)](#projection-entity-structure-v1). Existing projections (genericom EC2, LOTR saga) still use the v0 shape and continue to work; new projections should follow v1.

#### Implementation

The v0 projection shape is:

- `name`
- `description`
- `default_elevation` — string; references an elevation by `name`.
- `elevations` — array of inline elevation objects.

The shape is enforced via `FIELD_VALIDATION_SCHEMA` and `validate()` cross-field checks on the `Projection` model.

#### Development

The monolithic shape was deliberately chosen for v0 to avoid premature splitting into reusable artifacts. With the v1 reshape (elevations + layouts + arrangements as entities), the projection-to-arrangement chain becomes addressable as a graph, which v0 explicitly deferred.

#### Future

Existing v0 projections will be migrated to the v1 entity structure in a single pass once the v1 implementation lands. This requirement remains `Deprecating` until that migration ships, then becomes `Deprecated`.


### Projection Entity Structure (v1)
----
RID: `req-viz-projection-entity-structure`
Status: `Implemented`

A projection composes a set of Elevation entities and designates one as the default landing point, both via typed graph hotlinks.

#### Implementation

The v1 projection definition shape:

```json
{
  "name": "Genericom EC2 Internal Projection",
  "description": "Computing-core internal view of an EC2 instance.",
  "elevations": [
    "<elevation-entity-id-1>",
    "<elevation-entity-id-2>"
  ],
  "default_elevation_id": "<elevation-entity-id-1>",
  "node_style": { ... },
  "status_badges": { ... },
  "min_zoom": "fit",
  "lock_nodes": false
}
```

Top-level changes from v0:

- `elevations` is an array of UUIDs (not inline objects). Validated by the `USES_ELEVATION` hotlink.
- `default_elevation_id` is a single UUID. Validated by the `USES_DEFAULT_ELEVATION` hotlink.
- Inline elevation fields (`zoom`, `tap_layouts`, `double_tap_targets`) are not present at the projection level — they live on the Elevation entity per [spec-viz-elevation.md](spec-viz-elevation.md).

The Projection model declares two hotlinks for elevation composition:

```python
HOTLINKS: ClassVar[list[dict]] = [
    {
        "name": "projection-elevations",
        "field": "definition",
        "selector_type": "simple_path",
        "selector": "elevations.*",
        "edge_direction": "outbound",
        "edge_type": "USES_ELEVATION",
        "mode": "exact",
    },
    {
        "name": "projection-default-elevation",
        "field": "definition",
        "selector_type": "simple_path",
        "selector": "default_elevation_id",
        "edge_direction": "outbound",
        "edge_type": "USES_DEFAULT_ELEVATION",
        "mode": "exact",
    },
]
```

The `USES_DEFAULT_ELEVATION` edge expresses "this is THE landing elevation for this projection" as a typed graph relationship rather than a string-name reference or an edge-property flag on `USES_ELEVATION`. This makes the default queryable via gryphon (`MATCH (p:projection)-[:USES_DEFAULT_ELEVATION]->(el:elevation) ...`) and lets the same Elevation entity be the default in one projection and a non-default member in another.

#### Cross-Hotlink Invariant

The hotlink machinery validates each hotlink in isolation. Two cross-hotlink rules require an explicit `validate()` method on the Projection model:

1. `default_elevation_id` MUST appear in the `elevations` array (and equivalently, the `USES_DEFAULT_ELEVATION` target MUST also be a `USES_ELEVATION` target).
2. Every `NAVIGATES_TO` target reachable from any of this projection's elevations (via [`spec-viz-elevation.md`](spec-viz-elevation.md#navigates_to-hotlink)) MUST also appear in the projection's `elevations` set — you cannot double-tap to an elevation the projection does not compose.

These invariants are surfaced as `ValidationError`s on save with codes `default_elevation_not_in_set` and `navigates_to_target_outside_projection`.

#### Migration

Existing v0 projections (genericom EC2 internal, LOTR saga) are migrated in a single pass when the v1 implementation ships:

1. Author Elevation entities for each inline elevation, populated from the v0 `elevations[]` payload.
2. Author Layout entities for each inline tap-layout, populated with `js_file` from the v0 `tap_layouts[]` entry. Add `arrangements` if the layout's positioning would benefit (genericom EC2 internal does; see [spec-viz-arrangement.md](spec-viz-arrangement.md)).
3. Replace the projection's `definition.elevations` with the array of Elevation entity_ids and `definition.default_elevation_id` with the single UUID.
4. Update `tap-plugin.toml` to register the new arrangement / elevation / layout grift bundles.
5. Run `import_plugin_grift --force-batches` to reseat the projection definition.

Blast radius is small (two projections in the codebase at the time of this writing).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-entity-structure-1 | USES_ELEVATION hotlink | Implemented | Hotlink validates exact match between `definition.elevations` and outbound `USES_ELEVATION` edges. | |
| req-viz-projection-entity-structure-2 | USES_DEFAULT_ELEVATION hotlink | Implemented | Hotlink validates exact match between `definition.default_elevation_id` and a single outbound `USES_DEFAULT_ELEVATION` edge. | |
| req-viz-projection-entity-structure-3 | Default in set invariant | Implemented | `validate()` rejects projections whose `default_elevation_id` is not in `elevations`. | |
| req-viz-projection-entity-structure-4 | Navigates-to in set invariant | Implemented | `validate()` rejects projections where any composed elevation's `NAVIGATES_TO` target is not in the projection's `elevations`. | |
| req-viz-projection-entity-structure-5 | v0 projections migrated | Implemented | Genericom EC2 and LOTR projections updated to v1 shape in the same release. | |


### Elevation Model
----
RID: `req-viz-projection-elevation`
Status: `Deprecated`

Elevations are named zoom-driven stages within a projection.

#### Status Details

The v0 inline-elevation shape is being superseded by the Elevation entity defined in [spec-viz-elevation.md](spec-viz-elevation.md). The runtime activation behavior described below (zoom thresholds, double-tap pan-zoom, hysteresis, viewport preservation) carries forward unchanged — what's deprecating is the *config shape*, not the *runtime semantics*.

#### Implementation

Each elevation represents a meaningful visual altitude such as suite, product, network, host, application, or function.

The v0 elevation shape is:

- `name`
- `description`
- `zoom`
- `tap_layouts`
- `double_tap_targets`

Where:

- `zoom` is the zoom level at which the elevation becomes active
- `tap_layouts` is an ordered array of TAP layouts to run
- `double_tap_targets` is an array of:
  - `entity_type`
  - `target_elevation`

Elevation names must be unique within a projection.
Elevation zoom values must be unique within a projection.

There is exactly one active elevation at a time.

Elevation activation is TAP-managed and binds to Cytoscape zoom behavior through TAP-owned threshold logic rather than through a built-in Cytoscape elevation model.

Elevations may be entered by:

- projection initial load via `default_elevation`
- zoom threshold crossing (scroll-wheel)
- double-tap on an eligible node type (a convenience pan-zoom to that node)

When multiple zoom thresholds are crossed quickly, only the final target elevation is activated.

When an elevation is re-entered, its tap layouts rerun.

#### Double-Tap As Pan-Zoom Wrapper

Under v0, double-tap is a pan-zoom shortcut rather than a commanded-elevation operation. Double-tapping a node:

1. Finds the target elevation by searching every elevation's `double_tap_targets` for an entry matching the tapped node's `entity_type` — targets are keyed by entity type globally, not scoped to the source elevation.
2. Asserts the target elevation's scene state (runs its layouts) if the projection isn't already at that elevation.
3. Animates the viewport to a fit-with-padding frame around the tapped node using `cy.animate({fit: {eles: node, padding}})`. The layout runs first so the viewport lands on the node's settled post-layout position.

The runtime holds a transition lock for the duration of the animation to suppress the scroll-based zoom watcher. After the animation lands, the watcher's hysteresis anchor is set to the landing zoom so a small scroll doesn't instantly revert the commanded elevation.

Elevation activation itself is scene-wide and does not receive the tapped node as an operand. Layouts assert "what the scene should look like at my elevation" for every applicable node. The tapped node is used only to pick a target elevation and to center the viewport.

#### Hysteresis After Commanded Transitions

After a commanded pan-zoom animation lands, subsequent user scrolls within a hysteresis window (log-ratio distance ≈ 0.47, or roughly a factor of 1.6x in either direction) do not trigger elevation changes. This prevents a single scroll wheel nudge from bouncing out of a commanded elevation immediately after the user lands there. The hysteresis anchor is released when the user scrolls past the window, at which point normal zoom-threshold activation resumes.

#### Development

Elevations are the key abstraction that let a projection describe a human visual journey across multiple levels of detail. They should be treated as first-class projection concepts rather than as incidental layout options.

Double-tap behavior allows semantic navigation between elevations that may not be reached naturally by simple zooming alone. Treating it as a pan-zoom wrapper rather than a commanded operation keeps the elevation-transition path unified: the same code path activates an elevation whether you got there via scroll or via a commanded animation.

#### Future

Define elevation metadata, zoom thresholds, enter/exit semantics, and how multiple layouts are activated within an elevation.


### Layout Orchestration
----
RID: `req-viz-projection-layout-orchestration`
Status: `Deprecated`

Projections orchestrate one or more layouts at each elevation rather than replacing the layout system.

#### Status Details

The v0 inline `tap_layouts[]` shape is being superseded by the v1 elevation orchestration model in [Elevation Orchestration (v1)](#elevation-orchestration-v1). The clean layering — *projections define perspective and progression, elevations define staging, layouts do the work* — is preserved; what changes is that elevations and layouts become entities composed via hotlinks rather than inline JSON.

#### Implementation

Layouts remain deterministic Cytoscape-specific executable functions (now potentially supplemented by declarative arrangements). A projection decides when layouts run and which nodes they operate on. Multiple layouts may be active within the same elevation when they operate on different graph members or different scopes of the current scene.

In v0, a projection references inline tap layouts rather than separate layout entities.

The v0 tap layout shape is:

- `name`
- `description`
- `js_file`

`tap_layouts` run in array order.

#### Future

Once the v1 migration ships, this requirement becomes `Deprecated`.


### Elevation Orchestration (v1)
----
RID: `req-viz-projection-elevation-orchestration`
Status: `Approved for Development`

A v1 projection composes Elevation entities; each elevation owns its layout composition via the `USES_LAYOUT` hotlink defined in [spec-viz-elevation.md](spec-viz-elevation.md). Layouts are first-class entities (see [spec-viz-layouts.md](spec-viz-layouts.md)) that may carry a `layout_module` (JS file) and/or an ordered `arrangements` array.

#### Implementation

Layering responsibility:

- **Projection** — perspective and progression. Composes elevations, designates the default landing elevation, declares projection-wide chrome (status badges, node styling, min zoom, lock nodes).
- **Elevation** — staging and activation. Declares its zoom threshold, composes layouts in execution order, declares double-tap navigation targets.
- **Layout** — scene work. Runs a `layout_module` for broad-strokes positioning and/or applies arrangements for declarative refinement.
- **Arrangement** — single-anchor positioning rule. Refines positions of nodes the layout has already placed.

The runtime walks the chain at panel load:

1. Resolve the panel's `USES_PROJECTION` target.
2. Resolve the projection's `USES_DEFAULT_ELEVATION` target (or the elevation matched by current zoom).
3. Resolve the elevation's `USES_LAYOUT` targets in order.
4. For each layout, resolve `USES_ARRANGEMENT` targets in order.
5. Run the layout's `layout_module` first (if present), then its arrangements (if any).

The whole chain is fetchable in a single gryphon query at the `full` layer:

```
MATCH (p:projection)-[:USES_DEFAULT_ELEVATION]->(el:elevation)-[:USES_LAYOUT]->(l:layout)-[:USES_ARRANGEMENT]->(a:arrangement)
WHERE p.entity_id = $projection_id
RETURN el, l, a
```

This replaces the v0 path of fetching the projection's monolithic `definition` JSON and reading inline elevation/layout config from it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-elevation-orchestration-1 | Chain resolves via gryphon | Implemented | One gryphon query at `full` layer pulls projection → elevation → layouts → arrangements with definitions. | |
| req-viz-projection-elevation-orchestration-2 | Layout module runs before arrangements | Implemented | When a Layout has both `layout_module` and `arrangements`, the module runs first, arrangements second. | See `spec-viz-layouts.md` Dual-Mode Layout Definition |
| req-viz-projection-elevation-orchestration-3 | Empty-layout elevation valid | Implemented | An Elevation with `USES_LAYOUT` empty is legal (uncommon but not an error). | |


### Layout Runtime
----
RID: `req-viz-projection-layout-runtime`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/projection.js

Tap layouts execute serially with a projection-scoped runtime context and may mutate the Cytoscape scene directly.

#### Implementation

In v0, a tap layout is a deterministic executable function referenced by `js_file`.

Tap layouts:

- run serially
- may fetch additional graph data
- may add or update nodes and edges
- may apply nesting, positioning, scaling, or styling logic
- operate against the whole active Cytoscape graph for now
- resolve completion asynchronously

The v0 completion model is:

- the layout mutates `cy` directly
- the layout resolves a promise when finished

The projection-scoped runtime context should exist and should include at least:

- current `cy`
- current projection definition
- current active elevation
- trigger reason such as:
  - `initial_load`
  - `zoom_transition`
  - `double_tap`
- `trigger_node` (optional hint): carried for compatibility and passed through to layouts, but layouts do not depend on it for core operation. Elevation layouts are scene-wide — they assert the target scene state for every applicable node, not just a single target. The runtime uses the tapped node only to pick a target elevation and to center the viewport animation.

The runtime must support a transition state for double-tap-driven elevation entry so ambient zoom-threshold activation can be suspended until the commanded elevation transition is complete.

#### Development

This runtime model keeps the first implementation simple and honest. Layouts are real code, operate directly on the Cytoscape scene, and are free to perform the work needed to make an elevation real.

#### Future

- Add viewport-aware runtime helpers for large complex datasets.
- Define the helper API contract precisely once the first layouts are implemented.


### Incremental Loading
----
RID: `req-viz-projection-incremental-loading`
Status: `Implemented`
Trace: `process` — a v0 placement decision (follow-up fetch lives inside tap layouts, no separate elevation-level search contract); guidance for layout authors, no core mechanism

Deeper elevations may gather additional graph data at runtime based on what is already present in the Cytoscape scene.

#### Implementation

In v0, fetch behavior should live inside tap layouts rather than in a separate elevation-level initiating search contract.

An elevation may therefore begin with one or more tap layouts that inspect the currently rendered graph members, perform follow-up search calls, and add newly required nodes and edges to the scene.

#### Development

This keeps projections responsive and avoids front-loading the entire graph problem at projection initialization time.

#### Future

Define the search and data-fetching helpers available to layout functions and how incremental additions are merged safely into the active scene.


### Self-Contained Execution
----
RID: `req-viz-projection-self-contained`
Status: `Implemented`
Trace: `narrative` — a design principle (projections depend on no model-level display hints); the substance is distributed across the searches/elevations/layout machinery of the sibling requirements

Projections must be able to define a complete visual experience without depending on model-level display hints or global nesting declarations.

#### Implementation

A self-contained projection may define the searches, elevations, layout sequencing, and nesting behavior required for that projection's visual experience. Model-level hints may later be used as defaults or helpers, but they are not required for a projection to function.

#### Development

Starting from self-contained projections ensures TAP can always support specialized visual experiences without forcing all rendering behavior into global metadata contracts.

#### Future

Define how self-contained projection logic interacts with model-level defaults, reusable helpers, and optional shared nesting utilities.


### LOTR Monolithic Example
----
RID: `req-viz-projection-lotr-monolith`
Status: `Implemented`
Trace: `external` — lotr plugin (evicted; the worked monolithic projection lives in its grift bundle)

The LOTR plugin provides a worked monolithic projection example that exercises the v0 projection model.

#### Implementation

The worked example lives in the LOTR plugin as the "LOTR Saga Projection" node in `plugins/lotr/grift/web.grift.json`, wired to the "LOTR Saga Graph" panel via a `USES_PROJECTION` edge. The projection `definition` follows the monolithic shape from `req-viz-projection-structure` and orchestrates two elevations:

- `saga-level` (zoom 0.6) — runs the `saga-stage` tap layout at `plugins/lotr/static/lotr/js/projections/saga-stage.js`, which applies realm→location→character nesting, hides any prior-session artifacts, declares per-parent dimensions, and runs the dimensions plugin's recursive layout.
- `character-view` (zoom 0.9) — entered by scrolling past the threshold or double-tapping a character node, runs `plugins/lotr/static/lotr/js/projections/character-view.js`. Fetches WIELDS artifacts via the tap_api search endpoint on first entry and reuses the hidden-but-cached copies on re-entry.

See the grift file for the canonical definition; this spec intentionally does not duplicate the payload.

#### Development

The LOTR example should be treated as the proving ground for the v0 projection architecture before projection data is split into more reusable pieces.

#### Future

Split LOTR projection pieces into reusable referenced artifacts only after the monolithic shape proves itself in practice.


### Viewport Preservation
----
RID: `req-viz-projection-viewport-preservation`
Status: `Deprecating`

Scroll-driven elevation transitions preserve the user's visual frame of reference across the layout change that the transition triggers.

#### Status Details

This behavior is still live in the current runtime, but it is now considered compensating machinery rather than target architecture. The newer direction is defined in `tap_viz/specs/spec-viz-nested-projection.md`: stable outer node geometry plus nested viewport projection should remove much of the need for hero-node anchoring and post-layout pan correction.

#### Implementation

When the zoom watcher fires for a `zoom_transition` activation, layoutRecursive typically reshuffles most of the scene (e.g. turning leaf characters into compound parents in character-view, or hiding artifacts in saga-level). Without mitigation, the model-space point the user was looking at ends up occupied by some unrelated node after the layout completes — the user sees the viewport "jump" to an unrelated part of the scene.

The runtime mitigates this by anchoring on a **hero node** across the layout:

1. The runtime tracks the latest cursor position on the cy container via `mousemove` and `mouseleave` listeners. The cursor is the user's visual reference point — cytoscape's wheel zoom keeps the cursor-model-point fixed, so "the thing under my cursor should still be under my cursor" is the invariant we want to preserve.
2. Before a `zoom_transition` layout runs, the runtime picks a hero node as the visible leaf closest to the cursor (falling back to the viewport center when no cursor position has been observed yet). It snapshots the hero's ancestor chain.
3. After the layout runs, the runtime walks the ancestor chain and picks the first node that is still a valid anchor — not removed, not hidden via `.tap-elevation-hidden`, not a tap-dimensions anchor. The anchor chain fallback handles cases where the leaf hero becomes invalid across the transition (e.g. an artifact that was visible at character-view and gets hidden on saga-level re-entry).
4. The runtime adjusts `cy.pan` so the chosen anchor ends up at the cursor's rendered position. The math: `pan.x = cursor.x - modelNow.x * zoom` (and likewise for y).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-viewport-preservation-1 | Cursor Tracking | Implemented | Runtime tracks the latest cursor position via `mousemove` on the cy container. | |
| req-viz-projection-viewport-preservation-2 | Hero Is Cursor-Nearest Leaf | Implemented | Hero selection finds the visible leaf closest to the cursor (viewport center fallback). | |
| req-viz-projection-viewport-preservation-3 | Ancestor Fallback | Implemented | When the leaf hero becomes removed or hidden post-layout, the runtime walks the pre-layout ancestor chain for a still-valid anchor. | Handles zoom-out from character-view where the cursor-closest leaf is a transient artifact. |
| req-viz-projection-viewport-preservation-4 | Pan To Cursor | Implemented | Runtime adjusts pan so the chosen anchor ends up at the cursor's rendered position after the layout. | |

#### Future

Integrate the same viewport-preservation mechanism into commanded double-tap transitions if experience shows the two code paths benefit from unification. Today the commanded path uses a separate `cy.animate({fit: {eles, padding}})` approach because the double-tap user's focus is explicit (the tapped node), not inferred from the cursor.


### Elevation Invariants
----
RID: `req-viz-projection-elevation-invariants`
Status: `Implemented`
Trace: `process` — the entry-asserts-state authoring contract for elevation layouts; there is no exit hook to enforce, each layout author conforms at entry

Each elevation's tap layout is responsible for asserting the scene state that elevation requires, regardless of what the previous elevation left behind. There is no separate "exit" hook — the next elevation's entry covers cleanup implicitly.

#### Implementation

At entry, a layout may:

- hide, un-nest, or remove content that does not belong at this elevation
- restore previously-hidden content that the elevation wants visible again
- apply its own nesting rules via `applyNesting` with `clear_existing: true` when needed
- declare new dimensions on the nodes it cares about via the tap-dimensions plugin

The runtime provides an `tap-elevation-hidden` cytoscape class convention: layouts may mark nodes/edges with this class to hide them at the current elevation without removing them from cy. A corresponding style rule in `panel-graph.js` sets `display: none` on any element carrying that class.

The hide-don't-remove pattern supports re-entry caching: a layout that fetched data via the tap_api search endpoint on first entry can hide that data on exit, and the next entry can simply unhide rather than re-fetching. The LOTR saga projection uses this between character-view and saga-level — artifacts are hidden (not removed) when the user scrolls out, so re-entering character-view does not re-hit the API.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-elevation-invariants-1 | Layouts Assert Scene State | Implemented | Each tap layout puts the scene into the state its elevation requires on every entry, regardless of prior elevation state. | |
| req-viz-projection-elevation-invariants-2 | Hidden Class Convention | Implemented | `.tap-elevation-hidden` cytoscape class hides nodes/edges via `display: none` without removing them from cy. | Style rule in `panel-graph.js`. |
| req-viz-projection-elevation-invariants-3 | Re-entry Cache | Implemented | Layouts that fetched content on first entry can reuse the hidden copies on re-entry instead of re-fetching. | LOTR character-view demonstrates this for WIELDS artifacts. |
| req-viz-projection-elevation-invariants-4 | No Exit Hooks | Implemented | The runtime does not provide separate exit/teardown hooks. Teardown happens as part of the next elevation's entry assertion. | |

#### Future

Document the full list of runtime class conventions (`.tap-dim-anchor`, `.tap-elevation-hidden`, `.tap-hidden-containment`) in one place when there are enough of them to warrant a formal runtime reference.


### Viewport-Scoped Expansion
----
RID: `req-viz-projection-viewport-scoped-expansion`
Status: `Backlog`

Elevation expansion should eventually be scoped to what is visible in the viewport rather than operating on every applicable node in the whole graph.

#### Implementation

The v0 model runs a tap layout on entering an elevation and that layout expands every applicable node in the scene (for example, character-view expands every character in cy). This is fine for small graphs like the LOTR saga (under 100 nodes). For larger grids the expand-all fetch + layout cost becomes prohibitive.

The future model should:

- compute the set of nodes of the relevant entity type that fall within the current viewport
- expand only those nodes on elevation entry
- watch pan events and lazily expand additional nodes as they enter the viewport
- reclaim nodes that leave the viewport by a hysteresis margin

Viewport-scoped expansion should preserve the "magnify and enhance" mental model: as you zoom into a denser region, the applicable nodes there expand; panning around reveals newly-expanded neighborhoods.

#### Development

Capture the cost model in concrete numbers before designing this: what is the fetch latency per character, what is the layout cost per compound, and what is the user-visible lag threshold. Design choices flow from those numbers.

#### Future

Define an API for layouts to declare "which node type I expand" so the runtime can compute viewport membership without the layout having to.


### Minimum Zoom
----
RID: `req-viz-projection-min-zoom`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/projection.js

A projection may declare a minimum zoom level to prevent users from zooming out beyond the meaningful extent of the scene.

#### Implementation

- The `min_zoom` property is an optional field on the projection definition.
- Accepted values:
  - `"fit"` — after the initial layout and fit, the current zoom level becomes the floor. Users can zoom in but not back out past the initial view.
  - A positive number — sets an explicit minimum zoom level.
- When `min_zoom` is `"fit"`, the runtime calls `cy.minZoom(cy.zoom())` after the cascade reveal completes on initial load.
- When `min_zoom` is a number, the runtime calls `cy.minZoom(value)` after the cascade reveal completes on initial load.
- The `_PROJECTION_DEFINITION_SCHEMA` in `tap_viz/models.py` validates `min_zoom` as either `"fit"` or a positive number.
- When omitted, Cytoscape's default minimum zoom applies (no restriction).

#### Development

The `"fit"` mode is the common case: the layout computes the ideal framing, and there is no reason for the user to zoom out past it into empty space. An explicit numeric value is available for projections that need a specific floor independent of the layout result.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-min-zoom-1 | Fit Mode | Implemented | `min_zoom: "fit"` pins the minimum zoom to the post-layout zoom level. | `cy.minZoom(cy.zoom())` after cascade reveal |
| req-viz-projection-min-zoom-2 | Numeric Mode | Implemented | `min_zoom: <number>` sets the minimum zoom to the given value. | Direct `cy.minZoom(value)` call |
| req-viz-projection-min-zoom-3 | Schema Validation | Implemented | `min_zoom` is validated as `"fit"` or a positive number by the projection definition schema. | `oneOf` in `_PROJECTION_DEFINITION_SCHEMA` |
| req-viz-projection-min-zoom-4 | Optional | Implemented | Omitting `min_zoom` applies no restriction. | Cytoscape default behavior preserved |


### Lock Nodes
----
RID: `req-viz-projection-lock-nodes`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/projection.js

A projection may declare that all node positions are frozen after layout completes.

#### Implementation

- The `lock_nodes` property is an optional boolean on the projection definition, defaulting to `false`.
- When `true`, the runtime calls `cy.nodes().lock()` after layout, badges, and shadow interaction setup complete.
- When `true`, the drag-group behavior is not initialized — no dragging of any kind is permitted.
- The `_PROJECTION_DEFINITION_SCHEMA` in `tap_viz/models.py` validates `lock_nodes` as a boolean.
- Node locking applies to all nodes including badge nodes, shadow nodes, and container nodes.

#### Development

Locking nodes is appropriate for presentation-oriented projections where the layout algorithm has produced a definitive arrangement and user rearrangement would degrade the visual. It also simplifies interaction in demos and read-only dashboards where accidental drags are a distraction.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-projection-lock-nodes-1 | All Nodes Locked | Implemented | When `lock_nodes: true`, all nodes are locked after layout. | `cy.nodes().lock()` in `activate()` |
| req-viz-projection-lock-nodes-2 | No Drag Group | Implemented | When `lock_nodes: true`, drag-group behavior is not initialized. | `enableDragGroup` skipped |
| req-viz-projection-lock-nodes-3 | Schema Validation | Implemented | `lock_nodes` is validated as a boolean by the projection definition schema. | `{"type": "boolean"}` in schema |
| req-viz-projection-lock-nodes-4 | Optional Default | Implemented | Omitting `lock_nodes` defaults to unlocked (normal drag behavior). | Falsy check in runtime |
