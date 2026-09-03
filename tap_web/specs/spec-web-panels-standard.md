# Standard Panels Specification

## Philosophy

TAP Web needs a small set of built-in panel types that provide a baseline authoring experience without requiring plugin code for common cases. These standard panels live in `tap_web` and act as reference implementations for panel configuration, rendering, editor structure, and security expectations.

The first standard panel should be intentionally simple: a text panel that proves the full panel lifecycle end-to-end. That means a stored Panel object, a normal view template, an edit template, a small `config` object, standard preview/save behavior, and form-based editing with standard Django protections.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Baseline | Provide a small set of built-in panel types available without plugins |
| 2. | Reference | Establish a concrete example of panel view mode, edit mode, and config editing |
| 3. | Secure | Standard panel editors use Django's normal CSRF, validation, and escaping protections |
| 4. | Extensible | Standard panels should model the same panel object contract used by future custom panels |
| 5. | Minimal | The first panel type should be simple enough to validate the architecture without extra DSL work |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-stdpanel-base | [Standard Panel Types](#standard-panel-types) | Implemented | `tap_web/panels/` package; `TextPanelType` registered in `panel_type_registry` |
| req-web-stdpanel-text | [Text Panel](#text-panel) | Implemented | Renders title + `config.text`; description is admin metadata |
| req-web-stdpanel-text-edit | [Text Panel Editor](#text-panel-editor) | Implemented | `TextPanelEditForm`; Django Form validation; typed editor replaces generic JSON editor |

### Standard Panel Types
----
RID: `req-web-stdpanel-base`

Status: `Implemented`

Standard panel types are the built-in panel implementations that ship with `tap_web`. They provide core reusable panel behavior without relying on plugins.

#### Status Details
`tap_web/panels/` is the home for built-in panel type packages. `TextPanelType` is the first entry, registered with `panel_type_registry` in `TapWebConfig.ready()`.

#### Implementation
- Standard panel types live inside `tap_web/panels/`, one subpackage per type.
- Each panel type is a plain class (descriptor) with: `slug`, `label`, `view`, `editor_view`, `config_defaults`, and optionally `form_class`.
- Panel types are registered with `panel_type_registry` (a `ScopedRegistry[type]` in `tap_web/registry.py`) at app startup.
- Standard panels use the same `Panel` object contract defined in `spec-web-panel.md`:
  - `view`
  - optional `editor_view`
  - `config`
  - `js` / `css`
  - `editor_js` / `editor_css`
- Standard panels are intended to be readable reference implementations for future panel types.

#### Development
Keep built-in panel types small and obvious. They should prove the architecture, not compete with richer plugin panels.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-base-1 | Built-in Panels Live In tap_web | Implemented | Standard panel type implementations live in `tap_web/panels/` rather than a plugin package. | `tap_web/panels/text_panel/` |
| req-web-stdpanel-base-2 | Standard Panels Use Core Panel Contract | Implemented | Standard panels conform to the generic Panel object contract defined in `spec-web-panel.md`. | `TextPanelType` uses `view`, `editor_view`, `config`. |
| req-web-stdpanel-base-3 | Standard Panels Are Reference Implementations | Implemented | Standard panels are intended to serve as readable examples of panel rendering and editing patterns. | `TextPanelType` + `TextPanelEditForm` in `tap_web/panels/text_panel/`. |

#### Future
Add additional built-in panel types as separate standards once the text panel pattern is proven.

The Table Panel has been split into its own draft standard at `tap_web/specs/spec-web-panels-standard-table.md` so search binding, mixed-result handling, and pagination can evolve without overloading this catalog spec.

### Text Panel
----
RID: `req-web-stdpanel-text`

Status: `Implemented`

The Text Panel is the simplest standard built-in panel type. It renders a name and body text using the generic Panel object plus a small `config` payload. `description` remains backend/admin metadata rather than rendered body content.

#### Status Details
Implemented as `TextPanelType` in `tap_web/panels/text_panel/`. View template at `tap_web/panels/text_panel.html`.

#### Implementation
Text Panel data is stored as:
- `Panel.name` (canonical entity instance name)
- `Panel.description`
- `Panel.config.text`

Text Panel behavior:
- normal panel rendering displays `Panel.name` and `config.text`
- `description` is backend/admin metadata and is not part of the rendered panel body
- body text is plain text content, not trusted HTML
- Text Panel uses a normal `view` template and may omit panel-specific JS/CSS in the first implementation

The Text Panel does not require page inputs in its initial form.

#### Development
Keep the first text panel intentionally boring. The value is in proving panel object storage, normal rendering, and editor flow end-to-end.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-text-1 | Text Stored In Core Fields Plus Config | Implemented | Text Panel uses `Panel.name`, `description`, and `config.text` as its stored content model. | `description` is metadata, not rendered body content. |
| req-web-stdpanel-text-2 | Rendered Content Is Name Plus Text | Implemented | Text Panel renders `Panel.name` plus `config.text`, with body text treated as plain text rather than trusted HTML. | `tap_web/panels/text_panel.html`; auto-escaping enforced. |
| req-web-stdpanel-text-3 | No Inputs Required | Implemented | The initial Text Panel does not require `input_vars`. | `config_defaults = {"text": ""}` only. |

#### Future
Consider richer text variants later, but keep the first version plain text only.

### Text Panel Editor
----
RID: `req-web-stdpanel-text-edit`

Status: `Implemented`

The Text Panel editor is a simple HTML form that edits the panel's title, description, and body text.

#### Status Details
Implemented as `TextPanelEditForm` (Django Form) in `tap_web/panels/text_panel/`. Editor template at `tap_web/panels/text_panel_editor.html`. The `panel_edit_view` dispatches to the typed form when a `PanelType` with `form_class` is registered for the panel's `view` path.

#### Implementation
The Text Panel editor:
- uses the generic web editor shell defined in `spec-web-editor.md` and the panel edit route integration defined in `spec-web-rendering.md`
- renders a simple HTML form in `editor_view` (`tap_web/panels/text_panel_editor.html`), included inside the outer `panel_edit.html` form when a typed form is present
- edits:
  - `name`
  - `description`
  - `config.text`
- panel preview behavior follows the shared generic editor preview contract
- save is the explicit POST action

Security behavior for standard panel editors is defined in `spec-web-panel-security.md`.

#### Development
The first editor looks like normal Django form handling. `TextPanelEditForm` is a reference for future panel editors.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-text-edit-1 | Simple Form Editor | Implemented | Text Panel editor uses a simple HTML form (`TextPanelEditForm`) rather than a rich editor UI. | |
| req-web-stdpanel-text-edit-2 | Editable Fields | Implemented | Text Panel editor edits `name` (entity name), `description`, and `config.text`. | |
| req-web-stdpanel-text-edit-3 | Preview And Save | Proposed | Text Panel editor participates in the shared preview-without-save and explicit save contract. | Cross-ref `req-web-editor-preview-exec`. |
| req-web-stdpanel-text-edit-4 | Security Delegated | Implemented | Text Panel editor security behavior is governed by `spec-web-panel-security.md` (CSRF, server-side sanitization, auto-escaping). | `req-web-panel-edit-form.sec` + `req-web-panel-render-content.sec` both Implemented. |
| req-web-stdpanel-text-edit-5 | Editable Fields Persist Safely | Implemented | Text Panel editor persists `name`, `description`, and `config.text` through `form.cleaned_data` via the standard panel edit flow. | |
| req-web-stdpanel-text-edit-6 | Plain Text Saved Content | Implemented | Submitted text is stored and later rendered as plain text via Django auto-escaping. | Verified in `test_text_panel.py`. |

#### Future
If common editor patterns emerge across built-in panels, implement them through the generic editor shell and typed editor descriptor contract rather than duplicating form structure in every panel type.

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

`RID: `...``
`Status: `...``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
