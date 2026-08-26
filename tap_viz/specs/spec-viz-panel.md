# Viz Panel Specification

## Philosophy

The viz panel is the primary runtime surface for human-facing graph visualization inside TAP pages. It brings graph-native data into the existing page and panel system so people can inspect and navigate meaningful slices of the grid without leaving the broader page context.

The viz panel owns host/runtime concerns such as receiving resolved page inputs, creating the Cytoscape surface, rendering panel chrome, and handling user navigation within the panel. It does not own the definition of the graph view itself. Under the current architecture, graph view behavior belongs to the referenced projection and the tap layouts that projection orchestrates.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Hostable | Viz panels must fit cleanly into the existing TAP page and panel framework. |
| 2. | Input-Aware | Viz panels must consume resolved page inputs through the existing panel input contract. |
| 3. | Navigable | Viz panels must support core graph navigation behaviors such as pan, zoom, fit, selection, and optional popovers. |
| 4. | Projection-Hosted | Viz panels must host a referenced projection rather than embedding full graph logic directly in panel config. |
| 5. | Safe | Viz panels must fail safely and remain read-only in v1. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-panel-hosting | [Panel Hosting](#panel-hosting) | Refactoring | Viz panels are hosted by the existing TAP panel framework and are evolving toward projection runtime handoff |
| req-viz-panel-config | [Panel Configuration](#panel-configuration) | Proposed | Panel config covers projection-hosted runtime behavior |
| req-viz-panel-inputs | [Panel Inputs](#panel-inputs) | Proposed | Viz panels consume resolved page inputs and pass them into projection and layout execution |
| req-viz-panel-projection-reference | [Projection Reference](#projection-reference) | Proposed | Graph panels reference reusable projection entities through `USES_PROJECTION` |
| req-viz-panel-layout-reference | [Layout Reference](#layout-reference) | Deprecated | `USES_LAYOUT` is deprecated for graph panels in favor of `USES_PROJECTION` |
| req-viz-panel-runtime-nav | [Runtime Navigation](#runtime-navigation) | Implemented | Pan, zoom, and fit are required runtime behaviors |
| req-viz-panel-runtime-selection | [Runtime Selection](#runtime-selection) | Implemented | Selection is part of the core runtime contract |
| req-viz-panel-node-nav | [Node Navigation](#node-navigation) | Deprecated | Superseded by `req-viz-panel-click-semantics`; single click no longer navigates to the object viewer |
| req-viz-panel-click-semantics | [Click Semantics](#click-semantics) | Implemented | Formalizes single-click and double-click behavior on nodes, badges, and edges |
| req-viz-panel-runtime-popover | [Runtime Popovers](#runtime-popovers) | Proposed | Popovers are an optional but standardized runtime behavior |
| req-viz-panel-landing-default | [Landing Page Default](#landing-page-default) | Implemented | Default landing page should host a viz panel showing the graph in grid layout |
| req-viz-panel-readonly | [Read-Only Runtime](#read-only-runtime) | Implemented | Viz panel runtime is read-only in v1 |
| req-viz-panel-failure-handling | [Failure Handling](#failure-handling) | Refactoring | Viz panels fail safely within the panel shell and must distinguish panel, projection, and layout runtime failures |
| req-viz-panel-placement-per-view | [Placement Is A Per-View Choice](#placement-is-a-per-view-choice) | In Force | No system-wide layout default exists, by design — every view names its own placement deliberately |

### Panel Hosting
----
RID: `req-viz-panel-hosting`
Status: `Refactoring`

The viz panel is hosted through the normal TAP panel framework and participates in the same page composition rules as other panel types.

#### Status Details
This requirement makes viz a first-class panel citizen instead of a special page-level exception.

#### Implementation
- A viz panel is a TAP panel type rendered inside a page slot.
- It uses the generic panel lifecycle for:
  - page placement
  - asset loading
  - Cytoscape host creation
  - runtime rendering
  - panel error fallback
- Viz-specific runtime behavior may be implemented in `tap_viz`, but hosting remains owned by the general panel system.
- A graph panel may initialize with zero server-provided nodes when a referenced projection is expected to populate the scene after runtime handoff.
- The last act of graph panel bootstrap is to hand the initialized Cytoscape host and referenced projection to the TAP Viz projection runtime.

#### Development
The panel shell is the right place to standardize composition, while viz-specific logic stays inside the viz subsystem.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-hosting-1 | Existing Host Framework Used | Implemented | Viz panels render through the existing TAP panel framework rather than a separate host model. | `GraphPanel` registered via `panel_type_registry` in `tap_viz/apps.py` |
| req-viz-panel-hosting-2 | Page Slot Compatible | Implemented | Viz panels are placeable in normal TAP page slots. | Grid overview panel on landing page |
| req-viz-panel-hosting-3 | Generic Panel Error Path Preserved | Implemented | Viz panel failures still resolve through the standard panel error behavior. | Panel error fragment via `tap_web` panel view handler |

#### Future
If full-screen dedicated viz routes are needed later, define them as alternate hosts for the same panel/runtime contract.


### Panel Configuration
----
RID: `req-viz-panel-config`
Status: `Proposed`

Viz panel configuration is limited to host/runtime concerns. It does not embed projection or layout logic itself.

#### Status Details
This keeps a clean separation between panel instance concerns and reusable projection and layout definition concerns.

#### Implementation
The canonical panel config shape in v1 includes:

- `height` optional string. Drives the graph container height. Accepts `"100%"` (fill the enclosing layout slot; requires the slot to have an explicit `height` via the page layout row `height` field) or a pixel literal matching `^[1-9][0-9]{0,3}px$` (e.g. `"420px"`). Any other value is treated as unset and the panel falls back to the default `"420px"`.
- `initial_viewport` optional
- `chrome` optional object:
  - toolbar enabled
  - fullscreen enabled
  - fit control enabled
- `interaction` optional object:
  - selection enabled
  - popover enabled
  - minimum zoom
  - maximum zoom

Graph panels reference projections through graph structure rather than through panel config fields.

For graph panels, the panel instance should reference exactly one projection using:

- `USES_PROJECTION` edge to a projection node

The panel config does not define:
- search steps
- projection definition data
- placement actions
- containment rules
- styling rules

#### Development
Panel config should stay small enough that the same projection can be reused in multiple panels with different host behavior.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-config-1 | Projection Reference Not In Config | Proposed | Graph panel config stays focused on host/runtime concerns and does not embed projection definition data. | |
| req-viz-panel-config-2 | Host Behavior Only | Proposed | Viz panel config is limited to host/runtime behavior rather than embedding projection or layout logic. | |
| req-viz-panel-config-3 | Reuse Preserved | Proposed | A projection can be reused by multiple panel instances with different panel-level runtime settings. | |

#### Future
If common panel chrome patterns emerge, define shared config helpers instead of expanding the core panel config arbitrarily.


### Panel Inputs
----
RID: `req-viz-panel-inputs`
Status: `Proposed`

Viz panels consume resolved page inputs through the existing panel input contract and pass those values into projection and layout execution.

#### Status Details
This requirement aligns viz with the TAP page/panel input model from the start so viz can participate in page-level coordination rather than becoming a closed island.

#### Implementation
- Viz panels declare panel-local input names as needed.
- Pages remain responsible for mapping page variables to panel-local names.
- Viz panels receive resolved input objects through the canonical panel input event contract.
- Projection runtime and tap layouts may bind resolved panel inputs into search execution inputs and layout inputs.
- On input change, the panel reruns projection-hosted execution deterministically for the new input state.

#### Development
Input binding belongs at the panel/runtime boundary, not inside renderer-native configuration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-inputs-1 | Existing Panel Input Contract Used | Proposed | Viz panels consume resolved inputs through the existing TAP panel input model. | |
| req-viz-panel-inputs-2 | Projection And Layout Input Binding Allowed | Proposed | Projection runtime and tap layouts may bind resolved panel inputs into search and layout inputs. | |
| req-viz-panel-inputs-3 | Deterministic Rerun On Input Change | Proposed | Viz panel runtime reruns projection-hosted execution deterministically when panel inputs change. | |

#### Future
Define richer input typing and validation in the layout spec once common patterns emerge.


### Projection Reference
----
RID: `req-viz-panel-projection-reference`
Status: `Proposed`

Every graph panel references a reusable viz projection entity that defines what graph view is rendered.

#### Status Details
This requirement prevents panel instances from becoming one-off graph-definition containers and keeps projection orchestration out of panel-local config.

#### Implementation
- The panel references one default projection entity through a `USES_PROJECTION` edge.
- The projection reference is stable and reusable.
- The panel may provide runtime inputs and host settings, but the projection and its tap layouts define the graph view.
- Graph panels must support projection startup even when no server-provided nodes are present at panel initialization time.
- The panel creates the Cytoscape host surface and then hands off control to the projection runtime as the last step of bootstrap.

#### Development
The panel should be thought of as “a runtime host for a projection” rather than “the place where the graph view is authored.”

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-projection-reference-1 | Default Projection Reference Exists | Proposed | A graph panel references one default projection entity through `USES_PROJECTION`. | |
| req-viz-panel-projection-reference-2 | Projection Remains Reusable | Proposed | The referenced projection is not owned by the panel instance and may be shared elsewhere. | |
| req-viz-panel-projection-reference-3 | Zero-Node Projection Startup Allowed | Proposed | A graph panel may initialize with no server-provided nodes when the projection runtime is expected to populate the scene. | |
| req-viz-panel-projection-reference-4 | Runtime Handoff Defined | Proposed | The final act of graph panel bootstrap is to hand the initialized Cytoscape host and projection object to the projection runtime. | |

#### Future
Later work may define projection switching or adjacent projections, but that is not part of v1.


### Layout Reference
----
RID: `req-viz-panel-layout-reference`
Status: `Deprecated`

`USES_LAYOUT` as the primary graph-panel binding model is deprecated in favor of projection-owned runtime orchestration.

#### Implementation
- Graph panels should reference projections through `USES_PROJECTION`.
- Direct `USES_LAYOUT` binding may remain temporarily for compatibility during transition, but it is no longer the target architecture for graph panels.

#### Development
Tap layouts remain important, but they now run under projection orchestration rather than serving as the panel's primary referenced artifact.

#### Future
Remove graph-panel dependence on direct `USES_LAYOUT` bindings once projection runtime adoption is complete.


### Runtime Navigation
----
RID: `req-viz-panel-runtime-nav`
Status: `Implemented`

The viz panel supports core graph navigation behavior: pan, zoom, and fit.

#### Status Details
These are the minimum runtime behaviors required to make the panel feel like a serious graph surface rather than a static image.

#### Implementation
- Users may pan the graph.
- Users may zoom in and out.
- Users may fit the current scene to the viewport.
- Zoom constraints may be configured at the panel level.

#### Development
This requirement intentionally stops short of drilldown or pivots. Those are later interaction features, not part of the first runtime contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-runtime-nav-1 | Pan Supported | Implemented | The viz panel supports panning the current graph scene. | `userPanningEnabled: true` in `panel-graph.js` |
| req-viz-panel-runtime-nav-2 | Zoom Supported | Implemented | The viz panel supports zooming the current graph scene with panel-level zoom constraints. | `userZoomingEnabled: true`; `minZoom` set post-layout via `layoutstop` |
| req-viz-panel-runtime-nav-3 | Fit Supported | Implemented | The viz panel provides a fit-to-view behavior for the current graph scene. | Fit button in `_attachToolbar`; `cy.fit()` |

#### Future
If overview maps or saved viewport states become important, specify them separately rather than overloading the base navigation contract.


### Runtime Selection
----
RID: `req-viz-panel-runtime-selection`
Status: `Implemented`

Selection is part of the core runtime contract for nodes and edges shown in a viz panel.

#### Status Details
Selection is required so the panel can support meaningful inspection and future integrations without requiring editing behavior.

#### Implementation
- Nodes may be selected.
- Edges may be selected.
- The selected graph object may drive:
  - visual highlighting
  - optional popover content
  - future integrations not defined in this spec

#### Development
Selection is the minimal stateful interaction that makes inspection possible without dragging in full editing complexity.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-runtime-selection-1 | Node Selection Supported | Implemented | The panel supports selecting visible nodes. | Cytoscape `boxSelectionEnabled: true`; `userZoomingEnabled: true` |
| req-viz-panel-runtime-selection-2 | Edge Selection Supported | Implemented | The panel supports selecting visible edges. | Cytoscape default selection behavior |
| req-viz-panel-runtime-selection-3 | Selection Affects Presentation | Implemented | Selection changes visible runtime state such as highlighting or inspection context. | `:selected` style rule changes `background-color` and `line-color` |

#### Future
If multi-select becomes important, define it as a deliberate extension rather than assuming it implicitly.


### Node Navigation
----
RID: `req-viz-panel-node-nav`
Status: `Deprecated`

Single-click-to-navigate on nodes is removed in favor of in-panel inspection surfaces. Superseded by [`req-viz-panel-click-semantics`](#click-semantics).

#### Status Details

The original behavior — tap a node, go to `/object/{entity_type}/{url_id}/` — conflicts with the status badge info window, which takes single click as its open-trigger ([spec-viz-status-badge-info.md](spec-viz-status-badge-info.md)). Rather than layer conditional logic on top of the old navigation, the navigation is removed and the click slot is reclaimed.

- The `url_id` node payload field is retained. It remains usable for explicit links, row actions, or future navigation surfaces.
- The delayed-tap debounce infrastructure in `panel-graph.js` is retained; only the navigation side-effect is removed.
- Object viewer navigation is still reachable via any explicit link that carries a `url_id`-derived URL (breadcrumbs, inspector rows, etc.).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-node-nav-1 | Node Tap Navigates | Deprecated | Tapping a graph node no longer navigates to `/object/{entity_type}/{url_id}/`. | Removed in the click-semantics refactor |
| req-viz-panel-node-nav-2 | URL ID In Node Payload | Implemented | Every serialized node still carries a `url_id` field usable as the viewer URL segment. | `_serialize_entity` in `orm_compiler.py` |
| req-viz-panel-node-nav-3 | Edge Tap Does Not Navigate | Implemented | Clicking an edge does not trigger viewer navigation. | Retained — edges remain non-navigating |


### Click Semantics
----
RID: `req-viz-panel-click-semantics`
Status: `Implemented`

Formal definition of what single and double clicks do on graph objects.

#### Implementation

Single click behavior depends on the click target:

- **Status badge** (`[_is_status_badge]`): opens the info window for the host node ([spec-viz-status-badge-info.md](spec-viz-status-badge-info.md)). Clicking the same badge while the window is open closes it.
- **Node** (host body, with or without badges): no built-in action. The single-tap slot on a host body is reserved for plugins/projections to bind their own behavior on entity types they own (e.g. the Genericom AWS top-level projection navigates EC2 body taps to the per-instance page; see the EC2 top-level click requirement in `spec-genericom-ec2-projection.md`, genericom plugin repo). Default Cytoscape selection still applies.
- **Edge**: no action. Edges are not clickable for navigation or popover purposes in v0.
- **Empty canvas**: default Cytoscape behavior (deselect).

Double click behavior is unchanged and scoped to nodes in projection-hosted panels:

- **Node**: in a projection panel, a node double-tap triggers the projection's elevation transition (see [spec-viz-projection.md](spec-viz-projection.md)).
- **Node in a non-projection panel**: no action in v0.
- **Non-node targets**: no action on double-click in v0.

Manual double-tap detection in `panel-graph.js` and the Firefox native `dblclick` fallback are preserved. The host single-tap debounce timer is no longer used (host single-tap has no scheduled action), but the same-node-within-window check still runs to feed `_fireDoubleTap` on the second tap.

#### Development

- Removing navigation-on-tap gives the single-click slot a single clear purpose: in-panel inspection. That's a better use of the gesture than cross-page navigation, which is reachable via explicit links elsewhere.
- Consolidating semantics into one requirement here (rather than scattering click rules across per-feature specs) gives future interaction work a single cross-reference point.
- Host body single-tap is intentionally a no-op so plugins can claim it. The badge remains the canonical way to open the info-window — it's a precise, intent-bearing target. Hosts often have other meanings (inspect, drill down, navigate) that vary per entity type and should not be hard-coded here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-click-semantics-1 | Badge Click Opens Info Window | Implemented | Single click on a status badge opens the host's info window. | Wired in `panel-graph.js` tap handler |
| req-viz-panel-click-semantics-2 | Badged Host Click Opens Info Window | Deprecated | Single click on a badged host no longer opens the info window. The host-body tap slot is reserved for plugins/projections. | Removed in the badge-only-trigger refactor (see the EC2 top-level click requirement in `spec-genericom-ec2-projection.md`, genericom plugin repo). |
| req-viz-panel-click-semantics-3 | Unbadged Host Click Is No-Op | Implemented | Single click on a node with no active status badges takes no navigation or window action. | Default selection still applies |
| req-viz-panel-click-semantics-4 | Navigation Removed | Implemented | The previous `/object/...` navigation on node tap is fully removed. | `panel-graph.js` `go()` branch deleted |
| req-viz-panel-click-semantics-5 | Double Tap Unchanged | Implemented | Double-tap on a node in a projection panel continues to trigger the projection elevation transition. | `tap-double` event on nodes |
| req-viz-panel-click-semantics-6 | Edge Click Is No-Op | Implemented | Clicking an edge takes no action in v0. | |
| req-viz-panel-click-semantics-7 | Host Body Tap Is Plugin-Owned | Implemented | Single click on a host body has no built-in action; plugins/projections may bind their own handlers via `cy.on("tap", "node[entity_type=...]", ...)`. | First plugin user: Genericom AWS top-level projection navigating EC2 nodes to `/genericom/instance/<entity_id>`. |

#### Future

- A broader click registry (explicit binding of click → behavior per projection) would let plugins register handlers declaratively rather than wiring them in JS. The current model lets plugins claim the host-tap slot via raw `cy.on(...)` calls, which works but doesn't enforce single-binding-per-entity-type semantics.


### Runtime Popovers
----
RID: `req-viz-panel-runtime-popover`
Status: `Proposed`

Viz panels may provide popovers for selected nodes or edges, but popovers are optional in v1.

#### Status Details
The panel should support richer inspection surfaces without making them mandatory for every initial implementation.

#### Implementation
- Popovers, when enabled, are driven by selection or click behavior.
- Popover content may include summary information about the selected graph object.
- Popovers are panel/runtime behavior, not layout-definition logic.

#### Development
Keep popovers optional in the first contract so the runtime can ship without overcommitting to a detailed inspection UI too early.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-runtime-popover-1 | Popover Capability Standardized | Proposed | The spec defines optional popovers as a standard viz panel runtime behavior. | |
| req-viz-panel-runtime-popover-2 | Popovers Are Optional | Proposed | Popovers may be disabled without making the panel invalid. | |

#### Future
Define structured inspection cards, related actions, and deep-linked details in a later interaction spec.


### Landing Page Default
----
RID: `req-viz-panel-landing-default`
Status: `Implemented`

The default landing page should host a viz panel that shows all visible graph nodes and edges using a graph-wide view.

#### Status Details
This requirement captures the current high-priority product goal of making the landing page show the graph through the new panel-native architecture.

#### Implementation
- The default landing page contains a viz panel.
- That panel's initial graph view renders all nodes and edges in a graph-wide view.
- The initial placement mode for this view is grid-oriented.

#### Development
This requirement is primarily a product target, but it also serves as the reference implementation for panel-native graph rendering.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-landing-default-1 | Landing Page Uses Viz Panel | Implemented | The default landing page hosts a viz panel under the normal page/panel system. | Grid Overview panel on the seeded landing page |
| req-viz-panel-landing-default-2 | Full Graph View Used | Implemented | The panel's initial graph view renders all visible nodes and edges. | Graph-wide ORM search via graph panel |
| req-viz-panel-landing-default-3 | Grid Placement Used Initially | Implemented | The initial graph view uses grid-style placement in the initial implementation target. | `cytoscape:cose` layout (default in `_buildLayout`) |

#### Future
The landing-page layout may later become more curated or contextual, but the panel-native architecture should remain.


### Read-Only Runtime
----
RID: `req-viz-panel-readonly`
Status: `Implemented`

The viz panel runtime is read-only in v1.

#### Status Details
This keeps the runtime inspection-focused and prevents editor behavior from leaking into the panel contract before permissions and draft semantics exist.

#### Implementation
- Allowed:
  - render
  - pan
  - zoom
  - fit
  - select
  - optional popovers
- Excluded:
  - node creation
  - edge creation
  - graph mutation
  - saved drag repositioning
  - runtime layout editing

#### Development
Any future editing surface should be specified separately and should not implicitly redefine runtime panel behavior.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-readonly-1 | Runtime Navigation Allowed | Implemented | The panel permits non-mutating runtime navigation and inspection actions. | Pan, zoom, fit, select, node tap navigate |
| req-viz-panel-readonly-2 | Runtime Mutation Excluded | Implemented | The panel excludes graph and layout mutation from the v1 runtime contract. | No write paths in `panel-graph.js` |

#### Future
If inline editing is later desired, it should be gated behind a separate spec and permission model.


### Failure Handling
----
RID: `req-viz-panel-failure-handling`
Status: `Refactoring`

Viz panel failures must fail safely inside the panel shell and surface useful runtime warnings without breaking the hosting page.

#### Status Details
Graph rendering and layout execution are more complex than simple text rendering, so safe failure behavior must be explicit.

#### Implementation
- If the panel cannot bootstrap its runtime host, it fails with the standard panel error behavior.
- If the projection cannot be initialized, that failure is explicit and isolated to the panel.
- If tap layout execution produces warnings, the runtime may surface warning state while still rendering.
- If a tap layout fails, that failure is explicit and isolated to the panel, but other layouts may still run according to the layout runtime contract.

#### Development
Prefer explicit failure or warning surfaces over silent partial behavior that leaves the graph view misleading.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-failure-handling-1 | Host Page Remains Intact | Implemented | Viz panel failure does not break page rendering outside the affected panel. | Panel error fragment from `tap_web` panel view handler; HTMX swap isolates failures |
| req-viz-panel-failure-handling-2 | Warning State Allowed | Refactoring | Recoverable projection and layout warnings may be surfaced without treating the entire render as fatal. | Empty-nodes early return renders inline message in the panel container |
| req-viz-panel-failure-handling-3 | Runtime Failures Distinguished | Refactoring | Panel bootstrap failure, projection initialization failure, and layout execution failure are distinct runtime concerns. | |

#### Future
Define richer diagnostics, telemetry, and operator-facing debugging tools once the runtime matures.

## Deferred Areas

The following items are intentionally deferred:

- adjacent-layout pivots
- zoom-to-deeper-view behavior
- path overlays
- legend system
- runtime graph editing
- layout editor behavior

### Placement Is A Per-View Choice
----
RID: `req-viz-panel-placement-per-view`
Status: `In Force`

**There is no system-wide graph-placement default, by design.** Every view names its own
placement algorithm as a deliberate choice for what that particular view is meant to support.

#### Implementation

- The temptation this doctrine exists to resist: everyone defaults to `cose` because it looks
  cool, and a system that defaults to it ends up looking generic. Views are intended to be
  thoughtfully constructed, not default eye-candy — the placement is part of the thought.
- Structurally: placement values at different sites are **values, not a shared fact**. They must
  not be collapsed to a common constant or routed through a shared default — the 2026-08-14
  collapse-and-revert proved the coupling failure (changing one view's algorithm silently
  changed every fallback with it). A reviewer seeing such a collapse should point here.
- A *layout fallback* (a layout whose `presentation` names no placement) is that layout's own
  local decision, not a system default; it binds nobody else.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-panel-placement-per-view-1 | No shared default constant | In Force | No module exports a system-wide placement default; placement strings are authored per view. | Conformance expectation — doctrine, not an implementation. |

---

## Requirement Review Needed

Open questions where the code makes a choice no requirement governs. Recorded, not decided.
Indexed across all specs in
[doc-tap-requirement-review-ledger.md](../../docs/misc/doc-tap-requirement-review-ledger.md).

### Default graph placement

`"cytoscape:cose"` is written out eight times across `tap_viz/panels/graph_panel/__init__.py`,
`tap_web/synthetic.py`, and `tap_web/views.py`. No requirement owns the value: the only
mention anywhere in the specs is the evidence note on `req-viz-panel-landing-default-3`,
which scopes it to the landing page's initial view.

A 2026-08-14 attempt to collapse the eight sites to one constant was reverted, because they
are not one fact. They serve three distinct roles:

| Role | Sites | What it means |
| --- | :---: | --- |
| Layout fallback | 2 | A layout exists but its `presentation` names no placement. |
| Error-context filler | 5 | Set on an error return. **Never read** — both templates branch on `graph_error` and return before `data-placement` is emitted. |
| A view's own choice | 1 | The hub-and-spoke object-context graph, success path. No layout, no fallback — the view picks its algorithm. |

Collapsing these couples them: changing hub-and-spoke's algorithm (e.g. to `concentric`,
arguably more apt for that topology) would silently change every layout fallback with it.

**RESOLVED 2026-08-20 (George): there is no system-wide default, by design.** Placement is
always a per-view choice — defaulting to `cose` because it looks cool is how a product ends up
generic, and views are meant to be thoughtfully constructed, not default eye-candy. Canonized as
`req-viz-panel-placement-per-view` (`In Force`). The hub-and-spoke question dissolves (every
view owns its choice); the five never-read error-path assignments remain a cleanup candidate,
ungated by any requirement.

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

## Requirements Format

`RID: \`...\``
`Status: \`...\``
