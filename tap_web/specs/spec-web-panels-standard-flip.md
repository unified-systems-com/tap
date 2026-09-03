# FLIP Panel Specification

## Philosophy

The FLIP Panel is a standard read-only TAP Web panel for inspecting current field-level provenance on a canonical TAP object. Its role is to answer a practical question quickly: for the data currently shown on this object, which batch is responsible for which field paths? The first version should optimize for clarity over sophistication.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Current | The panel explains provenance for the current canonical values only |
| 2. | Read-Only | The panel is a viewer and does not edit provenance state |
| 3. | Batch-Anchored | Provenance is shown in terms of field paths and responsible batches |
| 4. | Minimal | The first version is a straightforward inspector, not a provenance workbench |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-stdpanel-flip | [FLIP Panel Type](#flip-panel-type) | Proposed | Built-in standard panel for viewing current field-level provenance |
| req-web-stdpanel-flip-input | [FLIP Subject Binding](#flip-subject-binding) | Proposed | Panel binds to exactly one canonical target object at render time |
| req-web-stdpanel-flip-render | [FLIP Rendering](#flip-rendering) | Proposed | First pass renders a field-path-to-batch inspection view |
| req-web-stdpanel-flip-edit | [FLIP Panel Editing](#flip-panel-editing) | Proposed | FLIP Panel is view-only in v1 and intentionally has no typed editor |

### FLIP Panel Type
----
RID: `req-web-stdpanel-flip`

Status: `Proposed`

The FLIP Panel is a built-in standard panel type that displays current field-level provenance for a single canonical TAP object.

#### Status Details
New proposed standard panel. Intended as the viewer counterpart to the FLIP capability defined in `spec-grid-flip.md`.

#### Implementation
- The FLIP Panel should live in `tap_web/panels/flip_panel/`.
- It should use the standard Panel object contract from `spec-web-panel.md`.
- It should render through a normal panel `view`.
- It may omit `editor_view` in v1 because the panel is intended to be read-only.
- The first implementation may be fully server-rendered.

#### Development
This panel should make FLIP tangible quickly, even before richer provenance navigation exists.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-flip-1 | Built-In FLIP Panel Exists | Proposed | TAP Web provides a built-in FLIP Panel type under `tap_web/panels/flip_panel/`. | |
| req-web-stdpanel-flip-2 | Standard Panel Contract | Proposed | The FLIP Panel uses the standard Panel contract for view rendering and optional assets. | |
| req-web-stdpanel-flip-3 | Read-Only By Default | Proposed | The first FLIP Panel standard is a viewer and does not define a typed panel editor. | Cross-ref `req-web-editor-availability` |

### FLIP Subject Binding
----
RID: `req-web-stdpanel-flip-input`

Status: `Proposed`

The FLIP Panel renders the current provenance state of exactly one canonical target object at a time.

#### Status Details
Proposed as the simplest reusable first-pass binding model.

#### Implementation
- The panel should expect one resolved input representing the canonical target object whose FLIP data will be displayed.
- The target object should be canonical, because FLIP is defined over canonical current values rather than perspective records.
- The panel should not invent its own subject through ad hoc config in v1.
- If no valid target object is provided, the panel should render a clear empty/error state.

#### Development
Binding through the shared input mechanism keeps the panel portable and lets pages decide how users navigate to the subject being inspected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-flip-input-1 | Single Canonical Target Input | Proposed | The panel renders FLIP data for one canonical target object at a time. | |
| req-web-stdpanel-flip-input-2 | Works With Resolved Inputs | Proposed | The target object is supplied through the normal resolved panel input mechanism. | Cross-ref `req-web-panel-inputs` |
| req-web-stdpanel-flip-input-3 | Graceful Empty State | Proposed | Missing or invalid subject input results in a visible empty/error state instead of a broken panel slot. | |

### FLIP Rendering
----
RID: `req-web-stdpanel-flip-render`

Status: `Proposed`

The first FLIP Panel renders a simple inspection view of tracked field paths and the batches responsible for their current values.

#### Status Details
This requirement intentionally scopes the first pass to the simplest useful viewer.

#### Implementation
- The panel should render a list or table of FLIP-tracked field paths for the target object.
- Each rendered row should include, where available:
  - field path
  - responsible batch id
  - actor from the batch
  - source from the batch
  - relevant batch timing metadata
- The panel should reflect current-state FLIP semantics only.
- The first implementation does not need:
  - provenance-over-time views
  - per-field diffing
  - direct batch drill-down navigation
  - edit or repair actions

#### Development
The first useful FLIP UI is essentially "show me the map in a human-readable form." That is enough to validate both the storage model and the web presentation contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-flip-render-1 | Field Path Inspection View | Proposed | The first FLIP Panel displays tracked field paths and their responsible batches for the current canonical object. | |
| req-web-stdpanel-flip-render-2 | Batch Context Visible | Proposed | The panel shows batch-derived provenance context such as actor, source, and timing where available. | |
| req-web-stdpanel-flip-render-3 | Current-State Only | Proposed | The panel does not attempt to show provenance-over-time in v1; those questions belong to history. | Cross-ref `req-grid-flip-separation` |

### FLIP Panel Editing
----
RID: `req-web-stdpanel-flip-edit`

Status: `Proposed`

The FLIP Panel is a view-only standard panel in v1.

#### Status Details
Proposed to keep the first panel focused on inspection and to avoid inventing unnecessary panel-configuration UI.

#### Implementation
- The FLIP Panel may omit `editor_view`.
- TAP Web should treat that omission as an intentional no-editor state.
- Any future filtering or display preferences can be added later if they prove necessary.

#### Development
The provenance data is the interesting part, not the panel configuration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-flip-edit-1 | No Typed Editor In V1 | Proposed | The FLIP Panel does not require a typed panel editor in the first implementation. | |
| req-web-stdpanel-flip-edit-2 | No-Editor State Is Intentional | Proposed | TAP Web can represent the FLIP Panel as view-only rather than treating missing editor UI as an error. | Cross-ref `req-web-editor-availability` |

#### Future
Later work may add conveniences such as filtering to tracked fields only, grouping by batch, or links into batch detail views if those prove useful.
