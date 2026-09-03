# Panel Spec


## Philosophy

Panels are the primary unit of data display in TAP. A panel is a self-contained view of data from the grid — a query, a visualization, a form, or any other render surface — that can be embedded into one or more pages. Panels are intentionally dumb about their host page; they receive a set of inputs, render their content, and surface outputs. Pages are responsible for wiring panels together.

Because panels are first-class entities on the grid, they can be shared across pages, versioned, queried, and used as the unit of curation for a dashboard-style UI.

## Goals

|    |                  |                                                                                                      |
| :---: | ---           | ---                                                                                                  |
| 1. |   Self-Contained  | A panel renders with only its declared inputs; no hidden ambient state                              |
| 2. |   Pluggable       | Plugin authors can register new panel types without modifying tap_web core                          |
| 3. |   Grid-Native     | Panels are entities — they can be linked, traversed, and queried like any other node, stored in the web dimension                |
| 4. |   Edit Included   | Panels come with a built-in way for users to edit the construction / configuration of that panel instance | 
| 5. |   Smart           | Panels are backed by code that can implement whatever complex processing is required to get to the right visualization and edit capabilities. | 


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panel-obj | [Panel Objects](#panel-objects) | Implemented | Panel model with slug, config, view/edit template paths, asset lists, and declared input variables |
| req-web-panel-inputs | [Panel Inputs](#panel-inputs) | Proposed | Panels declare expected input variable names and consume resolved inputs from the page |
| req-web-panel-edit | [Panel Edit Mode](#panel-edit-mode) | Refactoring | Panels participate in the generic web editor shell for panel-owned configuration editing |
| req-web-panel-static | [Panel Static Assets](#panel-static-assets) | Implemented | Static assets live in Django static paths; no external URLs allowed |
| req-web-panel-registry | [Panel Registry](#panel-registry) | Implemented | Panels are registered at load time in a run-time registry |
| req-web-panel-edit-authz.sec | [Panel Edit Authorization](#panel-edit-authorization) | Backlog | Permission model for panel editor access is deferred |


## Invariants
HTMX-compliant - Designed to be looked up via htmx calls from the page 
Sanitized - Are sanitized using Django's built-in rendering functions, no unsafe html used.

---


### Panel Object
----
RID: `req-web-panel-obj`

Status: `Implemented`

A Panel object is the backing entity for a data-display component. It declares its view renderer, optional editor renderer, configuration object, and display metadata. Static assets are owned by the **panel type** (the Python class matching `view`), not the panel instance — see the Asset Ownership section below.

#### Fields

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| `slug` | CharField (kebab-case) | Yes | Human-readable label used in the panel HTMX URL alongside the entity UUID. No uniqueness constraint — the UUID disambiguates. |
| `name` | CharField | Yes | Human-readable name shown in the UI. Canonical entity metadata term per `req-grid-entity-metadata`. |
| `description` | TextField | No | What the panel is for |
| `view` | CharField | Yes | Template path string for normal panel rendering. Also identifies the panel type — the registered panel type class whose `view` attribute matches is considered the owner and is the source of static assets and editor defaults. |
| `editor_view` | CharField | No | Template path string for the panel editor UI. Optional until a panel supports editing. |
| `config` | JSONField (object) | Yes | Panel-specific configuration object. Default: `{}`. |
| `input_vars` | JSONField (list) | No | Declared panel input variable names expected by the panel at runtime. Default: `[]`. |

#### Asset Ownership

Panel instances do **not** carry `js`, `css`, `editor_js`, or `editor_css` fields. These were removed in v0 because every legitimate use case for instance-level asset overrides turned out to be duplication of the panel type's declared lists, and the dedup-based aggregator silently masked drift between the two sources.

Static assets for a panel are now resolved exclusively through the registered panel type class:

```python
class GraphPanelType:
    slug = "graph"
    view = "tap_viz/panels/graph_panel.html"
    js = ["tap_viz/js/lib/cytoscape.min.js", "tap_viz/js/panel-graph.js", ...]
    css = ["tap_viz/css/panel-graph.css"]
    editor_js: list[str] = []
    editor_css: list[str] = []
```

The page rendering aggregator (`tap_web/views.py`) walks the panels on a page, resolves each to its panel type via the `view` field, and collects the type's `js` / `css` lists. The panel editor render path similarly reads `editor_js` / `editor_css` from the type. Panel instances have no way to add, remove, or override these lists.

Panels do not define or own `panel-id`. `panel-id` is a page-local slot identity defined in the page spec and used by page layout, page-panel links, and rendering.

#### Panel URL

Panels are served via HTMX from the page template at:

```
/panel/<slug>--<entity-uuid>/
```

The `slug` portion is the Panel's `slug` field value. The UUID is the Panel's `entity_id`. Together they form a URL that is both human-readable and unambiguously unique. The view handler parses the UUID suffix to look up the Panel; the slug is decorative.

#### Status Details

#### Implementation

`Panel` model in `tap_web/models.py` declares the fields above. The generic panel view handler in `tap_web/views.py` receives a request, looks up the Panel by entity UUID extracted from the URL, and calls `django.shortcuts.render(request, panel.view)` to render the panel's declared template. Panel edit mode reads `editor_view` from the panel instance and `editor_js` / `editor_css` from the resolved panel type class. `config` stores panel-specific configuration with default `{}`. The panel error fragment is returned on any exception so the HTMX swap completes and the slot shows "Panel Error" rather than leaving the page broken.

Asset source semantics:
- Static assets are declared by the panel type class (see Asset Ownership above), not the panel instance.
- Panel-specific client behavior should live in shipped static files such as `js/panel-*.js`.
- Third-party libraries vendored into TAP should also be served as static files, for example under `js/lib/`.
- Inline JavaScript embedded directly into panel HTML is not part of the panel contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-obj-1 | Panel Fields | Implemented | Panel declares `slug`, `name`, `description`, `view`, `editor_view`, `config`, and `input_vars` as described above. | Static asset fields were removed in migration 0009. |
| req-web-panel-obj-2 | View Is Template Path | Implemented | `view` stores a template path string. The generic panel view handler renders it with `render(request, panel.view)`. | |
| req-web-panel-obj-3 | Assets From Panel Type | Implemented | Static asset lists (`js`, `css`, `editor_js`, `editor_css`) are declared by the panel type class matching the panel's `view`, not by the panel instance. | |
| req-web-panel-obj-4 | Panel URL Format | Implemented | Panel HTMX endpoint is `/panel/<slug>--<entity-uuid>/`. UUID is used for lookup; slug is decorative. | |
| req-web-panel-obj-5 | Panel Error Fragment | Implemented | If the panel view raises any exception, the endpoint returns an HTML error fragment (HTTP 200) so HTMX swap completes with a "Panel Error" slot. | |
| req-web-panel-obj-6 | Web Dimension | Implemented | Panel carries `DEFAULT_DIMENSIONS = {"tap.graph": "web"}` (already implemented). | |
| req-web-panel-obj-7 | Config Defaults Empty Object | Implemented | `config` is required and defaults to `{}`. | |
| req-web-panel-obj-8 | Editor View Optional | Implemented | `editor_view` is optional and only required when a panel supports edit mode. | |

#### Future


### Panel Inputs
----
RID: `req-web-panel-inputs`

Status: `Proposed`

Panels declare the input variable names they expect and consume resolved panel inputs provided by the owning Page. Panels do not define page-level variable names or mapping rules.

#### Status Details
This requirement formalizes the boundary between page-level coordination and panel-level input consumption.

#### Implementation
- Panels may declare expected input variable names in `input_vars`.
- `input_vars` names are panel-local input names.
- The owning Page maps `tap_page_vars` and `tap_page_persistent_vars` into these panel-local names.
- Panels receive resolved input objects from the page coordinator.
- Panels do not need to know whether an input originated from URL-backed page state or page-scoped persistent state.
- Panels update in response to browser custom events dispatched by the page coordinator.
- The canonical panel refresh event is `tap:panel-inputs-changed`.
- Event payload includes the full resolved input object for the target panel.

#### Development
Keep panels self-contained by letting them declare what inputs they need while keeping all cross-panel and page-level naming logic in the page spec. This preserves panel portability across different pages.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-inputs-1 | Panels Declare Expected Input Names | Proposed | Panels may declare expected runtime input names in `input_vars`. | |
| req-web-panel-inputs-2 | Input Names Are Panel Local | Proposed | Declared panel input names are local to the panel and are not required to match page-level variable names. | |
| req-web-panel-inputs-3 | Page Owns Mapping | Proposed | Pages map `tap_page_vars` and `tap_page_persistent_vars` into panel-local input names through `USES_PANEL.variable_map`. | Cross-references `req-web-page-params`, `req-web-page-local`, and `req-web-page-plink`. |
| req-web-panel-inputs-4 | Panels Consume Resolved Inputs | Proposed | Panels receive only resolved input objects and do not implement page-level mapping logic. | |
| req-web-panel-inputs-5 | Refresh Event Contract | Proposed | Panels update in response to `tap:panel-inputs-changed` and receive the full resolved input object for the target panel. | |

#### Future
Consider adding input schemas for panel-level input validation once a stable panel editing and configuration model exists.


### Panel Edit Mode
----
RID: `req-web-panel-edit`

Status: `Refactoring`

Panels may support edit mode through the generic TAP Web editor shell. Panel edit mode is still panel-only: it edits the Panel object itself rather than any page-specific slot binding.

#### Status Details
This requirement now formalizes only the panel-specific portion of edit mode. Shared editor-shell behavior is defined in `spec-web-editor.md`. Route and panel rendering integration details remain in `spec-web-rendering.md`.

#### Implementation
- Normal panel rendering uses the instance's `view` plus the panel type's `js` / `css` class attributes.
- Panel edit mode uses optional `editor_view` plus the panel type's `editor_js` / `editor_css` class attributes.
- Panel edit mode is hosted inside the shared generic editor shell defined in `spec-web-editor.md`.
- Panel edit mode operates on panel-owned metadata and configuration:
  - `name` (canonical entity instance metadata)
  - `description`
  - `config`
- Panels may also provide a panel-specific object preview because panels have a human-facing rendered form.
- Panels without `editor_view` do not support a custom typed panel editor in v1.
- Edit submissions target the panel edit endpoint under `/panel/<slug>--<entity-uuid>/edit/`.

#### Development
Keep panel edit mode lightweight. `config` remains the generic extension surface for panel-specific configuration so plugin authors can build richer panel editors without forcing every panel type into its own concrete Django model.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-edit-1 | Panel Uses Generic Editor Shell | Proposed | Panel edit mode is hosted inside the generic web editor shell defined in `spec-web-editor.md`. | |
| req-web-panel-edit-2 | Editor Template Declared | Implemented | Panels that support custom typed editing declare `editor_view`. | |
| req-web-panel-edit-3 | Separate Editor Assets | Implemented | Panel types declare `editor_js` / `editor_css` class attributes separately from `js` / `css`. | Declared on the panel type class, not the panel instance. |
| req-web-panel-edit-4 | Edit Mode Targets Panel Object | Implemented | Panel edit mode edits the Panel object itself, not page-specific bindings. | |
| req-web-panel-edit-5 | Panel Edit Scope | Proposed | Panel edit mode covers panel-owned fields such as `name`, `description`, and `config`. | |
| req-web-panel-edit-6 | Panel May Provide Object Preview | Proposed | Panels may render an object-specific preview showing what the panel looks like. | Cross-ref `req-web-editor-object-preview`. |
| req-web-panel-edit-7 | Preview And Save Come From Shared Contract | Proposed | Panel preview/save behavior follows the shared generic editor preview contract. | Cross-ref `req-web-editor-preview-exec`. |

#### Future
Consider defining a lightweight panel config DSL or schema system so panel edit mode can validate and describe `config` more formally.


### Panel Edit Authorization
----
RID: `req-web-panel-edit-authz.sec`

Status: `Backlog`

Panel edit mode requires an explicit permission model, but that authorization behavior is deferred.

#### Status Details
Backlog security requirement created so editor access does not silently inherit undefined permissions.

#### Implementation
Future work must define:
- who may access panel edit pages
- who may preview panel edits
- who may save panel changes
- how panel edit permissions interact with page edit permissions and broader user security models

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-edit-authz.sec-1 | Security Requirement Exists | Backlog | Panel edit authorization is tracked as a dedicated security requirement. | |

#### Future
Define panel edit access, preview access, and save permissions once the user security model is in place.


### Panel Registry
----
RID: `req-web-panel-registry`

Status: `Implemented`

Panels are registered at load time in a run-time registry similar to the node's registry.

### Panel Static Assets
----
RID: `req-web-panel-static`

Status: `Implemented`

Panel static objects live in a django-standard static asset path which will make them accessible using standard static lookups.

Directory structure will be standardized as
* /js - javascript assets
* /css - css assets

A panel is allowed to reference assets from other plugins.
A panel is NOT ALLOWED to reference assets from the Internet at this time.

`js` and related asset lists store static-relative file paths only. They do not store inline script text, bundled code blobs, or remote URLs.

---

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

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
