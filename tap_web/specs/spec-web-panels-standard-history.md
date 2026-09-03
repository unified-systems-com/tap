# History Panel Specification

## Philosophy

The History Panel is a standard read-only TAP Web panel for inspecting the stored history of a grid object. Its purpose is to make history visible and useful quickly, without waiting for advanced time-travel UX or bespoke graph replay tooling. The first version should be intentionally simple: make it work, make the history inspectable, and keep the contract narrow.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Inspectable | Users can view the recorded history for a target object in a simple panel |
| 2. | Read-Only | The panel is a viewer, not an editor, and does not mutate history |
| 3. | History-Native | The panel reflects the history capability defined in `spec-grid-history.md` rather than inventing a parallel model |
| 4. | Minimal | The first implementation favors a straightforward timeline view over advanced replay controls |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-stdpanel-history | [History Panel Type](#history-panel-type) | Proposed | Built-in standard panel for viewing an object's history timeline |
| req-web-stdpanel-history-input | [History Subject Binding](#history-subject-binding) | Proposed | Panel binds to exactly one target object at render time |
| req-web-stdpanel-history-render | [History Timeline Rendering](#history-timeline-rendering) | Proposed | First pass renders a simple chronological timeline of history entries |
| req-web-stdpanel-history-edit | [History Panel Editing](#history-panel-editing) | Proposed | History Panel is view-only in v1 and intentionally has no typed editor |

### History Panel Type
----
RID: `req-web-stdpanel-history`

Status: `Proposed`

The History Panel is a built-in standard panel type that displays the recorded history of a single TAP object.

#### Status Details
New proposed standard panel. Intended as a simple reference implementation for capability-inspection panels that are primarily viewers rather than editors.

#### Implementation
- The History Panel should live in `tap_web/panels/history_panel/`.
- It should use the standard Panel object contract from `spec-web-panel.md`.
- It should render through a normal panel `view`.
- It may omit `editor_view` in v1 because the panel itself is intended to be view-only.
- Any required client behavior should ship through TAP static assets; however, the first pass may be fully server-rendered.

#### Development
This panel should prove that core capability data can be surfaced usefully without overcomplicating the first UI pass.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-history-1 | Built-In History Panel Exists | Proposed | TAP Web provides a built-in History Panel type under `tap_web/panels/history_panel/`. | |
| req-web-stdpanel-history-2 | Standard Panel Contract | Proposed | The History Panel uses the standard Panel contract for view rendering and optional assets. | |
| req-web-stdpanel-history-3 | Read-Only By Default | Proposed | The first History Panel standard is a viewer and does not define a typed panel editor. | Cross-ref `req-web-editor-availability` |

### History Subject Binding
----
RID: `req-web-stdpanel-history-input`

Status: `Proposed`

The History Panel renders the history of exactly one target object at a time.

#### Status Details
Proposed as the simplest binding model for the first pass.

#### Implementation
- The panel should expect one resolved input representing the target object whose history is to be displayed.
- The target may be a node, edge, panel, page, or other history-enabled TAP object.
- The panel should not invent its own history subject through ad hoc config in v1.
- If no valid target object is provided, the panel should render a clear empty/error state rather than failing the page.

#### Development
Keeping the subject binding simple makes the panel reusable across pages and keeps the panel aligned with the page/panel input contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-history-input-1 | Single Target Input | Proposed | The panel renders history for one target object at a time. | |
| req-web-stdpanel-history-input-2 | Works With Resolved Inputs | Proposed | The target object is supplied through the normal resolved panel input mechanism rather than bespoke page logic. | Cross-ref `req-web-panel-inputs` |
| req-web-stdpanel-history-input-3 | Graceful Empty State | Proposed | Missing or invalid subject input results in a visible empty/error state instead of a broken panel slot. | |

### History Timeline Rendering
----
RID: `req-web-stdpanel-history-render`

Status: `Proposed`

The first History Panel renders a simple chronological list of stored history entries for the target object.

#### Status Details
This is a make-it-work first pass, not the final time-travel history experience.

#### Implementation
- The panel should render a chronological timeline or table of history entries.
- Each rendered entry should include, where available:
  - recorded timestamp
  - change type
  - actor
  - record identifier
- The panel should consume history through TAP history services/adapters rather than coupling directly to a specific backend where practical.
- The first implementation does not need:
  - diff visualization
  - time-dial replay
  - historical graph reconstruction
  - in-panel revert actions

#### Development
The simplest useful UI is a clear list of "what changed, when, and by whom." That is enough to validate the history capability in the web layer before richer temporal UX is added.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-history-render-1 | Chronological Timeline View | Proposed | The first History Panel displays a chronological sequence of history entries for the subject. | |
| req-web-stdpanel-history-render-2 | Core Entry Metadata Visible | Proposed | Each entry shows timestamp, change type, actor, and record id when available. | |
| req-web-stdpanel-history-render-3 | No Advanced Replay Required In V1 | Proposed | The first implementation does not require time-dial replay, diffs, or revert actions. | |

### History Panel Editing
----
RID: `req-web-stdpanel-history-edit`

Status: `Proposed`

The History Panel is a view-only standard panel in v1.

#### Status Details
Proposed to keep the first implementation focused on inspection rather than configuration UX.

#### Implementation
- The History Panel may omit `editor_view`.
- TAP Web should treat that omission as an intentional no-editor state, not a broken panel type.
- Any future configuration, such as display filters or default window sizes, can be added later under a separate requirement if needed.

#### Development
History is the thing being inspected here; the panel itself does not need to be richly configurable to be useful.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-history-edit-1 | No Typed Editor In V1 | Proposed | The History Panel does not require a typed panel editor in the first implementation. | |
| req-web-stdpanel-history-edit-2 | No-Editor State Is Intentional | Proposed | TAP Web can represent the History Panel as view-only rather than treating missing editor UI as an error. | Cross-ref `req-web-editor-availability` |

#### Future
Later work may add filters such as bounded date windows, actor filtering, or "latest before" shortcuts once the core history panel proves useful.
