# Viz System Specification

## Philosophy

The viz system is the human-facing graph presentation layer for TAP. It exists to present navigable, understandable slices of the grid to people while preserving the power of the underlying graph model. Viz is not just a renderer choice or a standalone graph page. It is a TAP subsystem that connects pages, panels, searches, model display hints, icons, and renderer adapters into a coherent way to show graph-native information to humans.

The first version of this specification intentionally focuses on runtime behavior and architecture, not authoring. The goal is to establish stable system contracts for panel-native rendering and declarative layouts before defining the editor that will create and manage them.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Panel Native | Viz must integrate with the existing TAP page and panel framework rather than live as a parallel UI architecture. |
| 2. | Graph Native | Viz must operate on canonical TAP graph data and preserve graph semantics rather than flattening everything into ad hoc display blobs. |
| 3. | Declarative | Viz layouts must be TAP-owned declarative artifacts rather than raw renderer-native configuration as the primary contract. |
| 4. | Reusable | Viz layouts must be reusable across multiple panels and pages. |
| 5. | Evolvable | The runtime architecture must support future work such as editor tooling, pivots, legends, and path overlays without forcing a redesign of the core contracts. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-system-boundary | [System Boundaries](#system-boundaries) | Proposed | Defines ownership across `tap_web`, `tap_viz`, `tap_grid`, and `tap_api` |
| req-viz-system-panel-native | [Panel-Native Runtime](#panel-native-runtime) | Proposed | Viz runs through TAP panels rather than a standalone page model |
| req-viz-system-layout-entity | [Layouts As First-Class Entities](#layouts-as-first-class-entities) | Proposed | Layouts are reusable TAP entities |
| req-viz-system-search-backed | [Search-Backed Execution](#search-backed-execution) | Proposed | Layout execution is built on TAP Search entities and canonical graph envelopes |
| req-viz-system-display-hints | [Display Hints](#display-hints) | In Development | Shape and color hints via `DEFAULT_DISPLAY["tap_viz"]` implemented; label-size and layout overrides deferred |
| req-viz-system-renderer-adapter | [Renderer Adapter Model](#renderer-adapter-model) | Proposed | Cytoscape is the initial renderer adapter, not the canonical storage format |
| req-viz-system-readonly-runtime | [Read-Only Runtime](#read-only-runtime) | Proposed | The viz runtime is view-oriented and non-mutating in v1 |
| req-viz-system-legacy-layout-deprecation | [Legacy Layout Deprecation](#legacy-layout-deprecation) | Proposed | Existing raw Cytoscape layout storage is transitional |
| req-viz-system-neighborhood | [Entity Neighborhood Query](#entity-neighborhood-query) | Deprecated | Replaced by synthetic page builder; `neighborhood.py` removed |

### System Boundaries
----
RID: `req-viz-system-boundary`

Status: `Proposed`

The viz system spans multiple TAP apps, but each app has a clear ownership boundary.

#### Status Details
This requirement exists to prevent TAP from drifting into a split architecture where graph viewing, panel hosting, and graph data access each reinvent each other.

#### Implementation
- `tap_web` owns:
  - page hosting
  - panel hosting
  - panel input coordination
  - panel edit routing and generic panel shell behavior
- `tap_viz` owns:
  - viz runtime behavior
  - viz panel behavior
  - layout execution
  - renderer adapters
  - future viz-specific authoring surfaces
- `tap_grid` owns:
  - entities and edges
  - search objects and search execution
  - icon resolution services
  - model/display metadata contracts
- `tap_api` owns:
  - read APIs consumed by the viz runtime or future editor when direct service-layer execution is not used

#### Development
Keep the contracts aligned with existing TAP seams. `tap_web` should not absorb layout execution logic, and `tap_viz` should not grow a parallel page system.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-boundary-1 | Host Boundary Defined | Proposed | The spec assigns page and generic panel hosting to `tap_web`. | |
| req-viz-system-boundary-2 | Viz Runtime Boundary Defined | Proposed | The spec assigns viz runtime and layout execution ownership to `tap_viz`. | |
| req-viz-system-boundary-3 | Grid Boundary Defined | Proposed | The spec assigns graph data, search, icons, and display metadata ownership to `tap_grid`. | |
| req-viz-system-boundary-4 | API Boundary Defined | Proposed | The spec defines `tap_api` as the read API layer for viz consumers when API access is used. | |

#### Future
Define more specific service-vs-API guidance once the layout editor and preview execution contracts exist.


### Panel-Native Runtime
----
RID: `req-viz-system-panel-native`

Status: `Proposed`

Viz is a panel-native runtime. Viz content is hosted inside TAP panels on TAP pages rather than operating as a separate graph-view application model.

#### Status Details
Current TAP includes a standalone `tap_viz` graph page and a legacy graph home page. Those are transitional current-state surfaces, not the long-term architecture.

#### Implementation
- The canonical host surface for viz is a TAP panel instance embedded in a TAP page.
- Viz uses the panel contract for:
  - page placement
  - page-local slot identity
  - asset loading
  - page input delivery
  - error rendering
- A standalone graph route may continue to exist as transitional compatibility, but it is not the canonical runtime target.

#### Development
This keeps viz aligned with the rest of TAP’s human-facing surfaces and lets page-level state coordination work uniformly across tables, text panels, and graph panels.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-panel-native-1 | Canonical Host Is Panel | Proposed | The spec defines the TAP panel framework as the canonical runtime host for viz. | |
| req-viz-system-panel-native-2 | Page Integration Preserved | Proposed | Viz runtime behavior participates in normal TAP page and panel composition rather than bypassing it. | |
| req-viz-system-panel-native-3 | Standalone Graph View Is Transitional | Proposed | Existing standalone graph routes are described as transitional rather than canonical. | |

#### Future
If full-screen or dedicated graph experiences are needed later, define them as alternative hosts for the same viz runtime rather than as a separate system.


### Layouts As First-Class Entities
----
RID: `req-viz-system-layout-entity`

Status: `Proposed`

Viz layouts are first-class TAP entities. A layout is a reusable definition of how graph data is gathered, structured, and presented inside a viz panel.

#### Status Details
This requirement narrows the meaning of “layout.” A layout is not merely a Cytoscape algorithm name or a saved set of coordinates. It is the full display recipe for a graph view.

#### Implementation
- Layouts are stored as TAP entities with their own name, description, and definition payload.
- Layouts are reusable across multiple panel instances and pages.
- Panels reference layouts; panels do not own layout definitions.
- Layouts are TAP-owned artifacts independent of any one renderer’s native JSON schema.

#### Development
Keeping layouts reusable avoids coupling display semantics to page slot configuration. A “network segment layout” or “service dependency layout” should be reusable wherever it is useful.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-layout-entity-1 | Layout Is First-Class Entity | Proposed | Viz layouts are specified as their own TAP-managed artifacts. | |
| req-viz-system-layout-entity-2 | Layout Is Reusable | Proposed | A single layout may be referenced by multiple panels or pages. | |
| req-viz-system-layout-entity-3 | Panel References Layout | Proposed | Viz panels reference layout entities rather than embedding full layout logic directly in panel config. | |

#### Future
Add versioning and draft/published workflow once the editor and operational lifecycle are specified.


### Search-Backed Execution
----
RID: `req-viz-system-search-backed`

Status: `Proposed`

Viz layout execution is built on TAP Search entities and the canonical graph result envelope.

#### Status Details
This requirement aligns viz with existing TAP search architecture instead of creating a separate graph-query language inside viz definitions.

#### Implementation
- Layouts reference Search entities for graph retrieval.
- Search execution occurs through the existing TAP service-layer search contract.
- Layout steps consume canonical graph envelopes:
  - `nodes`
  - `edges`
  - `info`
  - `warnings`
- Viz does not define a parallel search execution path.

#### Development
This keeps query logic discoverable, reusable, and consistent across panels and future clients.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-search-backed-1 | Search Entities Used | Proposed | Layout definitions use TAP Search entities as the canonical retrieval substrate. | |
| req-viz-system-search-backed-2 | Canonical Graph Envelope Used | Proposed | Layout execution consumes canonical TAP graph search envelopes rather than custom viz-only result shapes. | |
| req-viz-system-search-backed-3 | No Viz-Specific Search Engine | Proposed | The spec does not define a parallel viz-only query execution system. | |

#### Future
If layouts later compose searches more richly, that composition should still be expressed in terms of Search entities and layout pipeline steps. When that binding is built, step-to-search references validate via a `USES_SEARCH` hotlink on the Layout model — the same pattern `req-viz-layout-dual-mode` proves with `USES_ARRANGEMENT` — not via role-name edge properties. (The v0 `search-id`/`layout-id` edge-property binding keys were deleted as unread remnants, 2026-08-10; see `req-grid-edge-schema-required` in spec-grid-edge.md.)


### Display Hints
----
RID: `req-viz-system-display-hints`

Status: `In Development`

Models may expose display hints that provide the smallest viz-specific default visualization guidance for node shape, color, and label size. Icon ownership remains part of TAP's canonical grid icon system. Viz-specific display metadata is namespaced under a `tap_viz` object within the broader model display metadata surface.

#### Status Details
This requirement formalizes the smallest useful set of viz-specific model-owned defaults without duplicating the canonical icon contract that already exists at the grid layer.

#### Implementation
- Display hints are model-level metadata, not panel-local metadata.
- Viz-specific display hints live under a namespaced `tap_viz` object in model display metadata so they do not interfere with non-viz consumers.
- Display hints may define:
  - `shape`
  - `colors` — a nested object with `fill`, `border`, and `label` hex color strings
  - `label` — a nested object positioning the node's text label: `valign` (`top` / `center` / `bottom`), `halign` (`left` / `center` / `right`), `position` (`outside` / `inside`)
  - `label_size`
- Icon selection does not live in viz display hints in v1.
- Icons are resolved through the canonical grid icon contract and icon service.
- Layouts may override display hints for a specific layout instance.
- Display hints do not replace layout definitions; they supply defaults.

#### Development
This lets a server, interface, or port model carry stable default node shape, color, and label-size hints while relying on the existing grid icon system for icon ownership and resolution, and it does so without polluting future display metadata consumers that may need different namespaced hints.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-display-hints-1 | Shape Hint Is Model-Level | Implemented | `DEFAULT_DISPLAY["tap_viz"]["shape"]` on `BaseModel` subclasses; graph panel enrichment reads it per node. | |
| req-viz-system-display-hints-2 | Color Hint Is Model-Level | Implemented | `DEFAULT_DISPLAY["tap_viz"]["colors"]` is a nested object with `fill`, `border`, and `label` hex color strings. Graph panel reads each value per node and applies them as the Cytoscape `background-color`, `border-color`, and text `color` respectively. Hints remain optional — nodes without `colors` fall back to default renderer styling. | |
| req-viz-system-display-hints-3 | Label Size Hint Is Model-Level | Proposed | `DEFAULT_DISPLAY["tap_viz"]["label_size"]` may provide the default label-size tier for viz rendering. | |
| req-viz-system-display-hints-8 | Label Position Hint Is Model-Level | Implemented | `DEFAULT_DISPLAY["tap_viz"]["label"]` is a nested object with `valign` (`top`/`center`/`bottom`), `halign` (`left`/`center`/`right`), and `position` (`outside`/`inside`). Graph panel reads these and applies them as Cytoscape `text-valign`, `text-halign`, and a computed `text-margin-y` (negative for outside-top, positive for inside-top, inverted for bottom). | |
| req-viz-system-display-hints-4 | Viz Hints Are Namespaced | Implemented | Viz hints live under the `tap_viz` key in `DEFAULT_DISPLAY`. | |
| req-viz-system-display-hints-5 | Icons Reuse Grid Contract | Implemented | `_enrich_nodes_with_icons` uses `resolve_icon_url(EntityType)` from `tap_grid.icon_service`. | |
| req-viz-system-display-hints-6 | Layout Overrides Allowed | Backlog | Deferred; layout-level shape, color, or label-size override wiring not yet implemented. | |
| req-viz-system-display-hints-7 | Hints Remain Defaults | Implemented | Shape defaults to `"ellipse"` when no hint is present; display hints remain defaults and do not replace the layout pipeline. | |

#### Future
Define the detailed display-hints schema in a dedicated viz sub-spec.


### Renderer Adapter Model
----
RID: `req-viz-system-renderer-adapter`

Status: `Proposed`

Cytoscape is the initial renderer adapter for viz, but renderer-native config is not the canonical persisted layout model.

#### Status Details
Current TAP stores raw Cytoscape config on the `Layout` model. This requirement marks that shape as transitional and introduces a cleaner architectural direction.

#### Implementation
- Layout definitions are TAP-owned declarative objects.
- Renderer adapters convert layout execution output into renderer-ready scene data.
- Cytoscape is the first required renderer adapter.
- Renderer-native config may exist as derived output or compatibility import/export format.

#### Development
This avoids binding TAP’s long-term visualization model to Cytoscape’s storage conventions while still using Cytoscape’s rendering power in the near term.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-renderer-adapter-1 | TAP-Owned Layout Contract | Proposed | Canonical persisted layouts are TAP-owned declarative definitions rather than raw Cytoscape config. | |
| req-viz-system-renderer-adapter-2 | Cytoscape First Adapter | Proposed | Cytoscape is the initial renderer adapter required by the spec. | |
| req-viz-system-renderer-adapter-3 | Adapter Boundary Exists | Proposed | The spec distinguishes canonical layout definitions from renderer-specific derived configuration. | |

#### Future
If future renderers are introduced, they should target the same renderer-ready scene contract rather than redefining layout storage.


### Read-Only Runtime
----
RID: `req-viz-system-readonly-runtime`

Status: `Proposed`

The v1 viz runtime is read-only. It is intended for graph viewing, navigation, and inspection rather than graph mutation.

#### Status Details
This keeps the first runtime contract narrow and prevents the viewer from silently expanding into an editing system before authoring and permissions are designed.

#### Implementation
- Viz panels allow:
  - viewing
  - pan and zoom
  - fitting
  - selection
  - optional popovers
- Viz panels do not allow:
  - node creation
  - edge creation
  - graph mutation
  - drag-to-save positioning edits
  - runtime authoring of layout definitions

#### Development
Runtime inspection and authoring are different systems with different permission and state-management needs. Keep them separate until the editor is specified.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-readonly-runtime-1 | Viewing Allowed | Proposed | The spec permits viewing and navigation actions in the viz runtime. | |
| req-viz-system-readonly-runtime-2 | Mutation Excluded | Proposed | The spec excludes graph and layout mutation from the runtime panel in v1. | |
| req-viz-system-readonly-runtime-3 | Authoring Deferred | Proposed | Layout authoring behavior is explicitly deferred from this spec package. | |

#### Future
Specify the editor and any graph authoring behavior separately, including authorization and draft handling.


### Legacy Layout Deprecation
----
RID: `req-viz-system-legacy-layout-deprecation`

Status: `Proposed`

The current raw Cytoscape layout storage model is transitional and should be deprecated as the canonical visualization contract.

#### Status Details
Current `tap_viz.Layout` stores `cytoscape_config`. That may remain temporarily for compatibility, but it should not define future architecture.

#### Implementation
- Existing persisted Cytoscape config may be:
  - read for compatibility
  - imported into the new layout definition model
  - exported from the new model when needed
- Future layout work should target TAP-owned definitions first.
- Legacy routes and templates may continue to exist during migration.

#### Development
This requirement provides a clear path away from “layout equals raw Cytoscape JSON” without demanding immediate removal of working current-state surfaces.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-legacy-layout-deprecation-1 | Current Storage Marked Transitional | Proposed | The spec marks raw Cytoscape layout storage as transitional rather than canonical. | |
| req-viz-system-legacy-layout-deprecation-2 | Compatibility Path Allowed | Proposed | The spec allows compatibility import/export behavior for existing Cytoscape data. | |
| req-viz-system-legacy-layout-deprecation-3 | Future Work Targets New Model | Proposed | The spec directs future implementation toward TAP-owned declarative layout definitions. | |

#### Future
Define an explicit migration strategy once the new layout model and editor are implemented.

### Entity Neighborhood Query
----
RID: `req-viz-system-neighborhood`

Status: `Deprecated`

A common viz need is retrieving all nodes directly connected to a given entity — its one-hop neighborhood — for rendering in object viewers and context panels.

#### Status Details
Deprecating. The `tap_web/neighborhood.py` helper was a transitional adapter that constructed a transient gryphon-backed Search to provide Cytoscape context for legacy viewer/editor shells. This is now superseded by the synthetic page builder (`req-web-page-synthetic`), which renders entity viewer and editor pages from GRIFT subgraphs that carry their own Search definitions. The neighborhood query still exists — it lives as a persisted Search node inside the entity page GRIFT subgraph — but the adapter module and legacy fallback views that consumed it are no longer needed.

#### Deprecation Path
- `tap_web/neighborhood.py` and its `get_entity_neighborhood()` function are removed.
- The legacy viewer/editor fallback views (`_legacy_object_view`, `_legacy_object_edit_view`) that called the neighborhood helper are replaced by the synthetic page builder.
- The gryphon hub-and-spoke neighborhood query is preserved as a Search node in the entity page GRIFT subgraph defined in `tap_web/data/`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-system-neighborhood-1 | Neighborhood Query Uses Search | Deprecated | Entity neighborhood retrieval was expressed as a TAP Search. Now carried as a Search node in the entity page GRIFT subgraph rather than constructed in Python code. | |
| req-viz-system-neighborhood-2 | Neighborhood Helper Is Thin Adapter | Deprecated | `tap_web/neighborhood.py` is removed; its role is replaced by the synthetic page builder. | |


## Deferred Areas

The following areas are intentionally deferred from this specification set:

- layout editor
- adjacent-layout pivoting
- zoom-to-deeper-view behavior
- path overlays
- legend system
- write-capable graph editing

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
