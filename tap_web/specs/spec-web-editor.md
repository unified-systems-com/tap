# Web Editor Specification

## Philosophy

TAP Web needs a generic editor shell for graph-native objects. The editor should work for simple model-backed nodes first, remain compatible with richer objects later, and avoid forcing every editable thing into a bespoke one-off page.

The editor is graph-aware rather than form-only. Editing an object should always show the object in graph context, because meaning in TAP is carried by both the object and its immediate relationships.

The first implementation target is a simple object such as a LOTR character. More advanced artifacts such as layouts, pages, and panels should be able to extend the same editor shell with richer object-specific preview behavior.

Hotlink editing is intentionally deferred. It requires additional relationship-aware logic and should be handled as a separate backlog concern rather than folded into the first generic editor contract.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Generic | One editor shell works for simple node objects and can be extended for richer TAP artifacts |
| 2. | Graph-Aware | The edited object is always shown in immediate graph context |
| 3. | Typed | Forms should model real fields first, not default to raw JSON editing |
| 4. | Previewable | Users can apply draft changes to a preview without saving |
| 5. | Progressive | Start with simple model-backed objects; defer hotlinks and other relationship-heavy editing |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-editor-shell | [Editor Shell](#editor-shell) | Implemented | Shared editor page structure for editable TAP objects |
| req-web-editor-graph | [Graph Context Preview](#graph-context-preview) | Implemented | Cytoscape neighborhood graph of the edited object and its immediate relationships |
| req-web-editor-object-preview | [Object Preview](#object-preview) | Proposed | Type-aware preview of what the edited object looks like |
| req-web-editor-availability | [Editor Availability Contract](#editor-availability-contract) | Proposed | TAP objects may explicitly declare that no typed editor exists in v1 |
| req-web-editor-preview-exec | [Preview Execution](#preview-execution) | Backlog | Deferred: save + history-revert is the v1 undo strategy |
| req-web-editor-typed | [Typed Editor Contract](#typed-editor-contract) | Implemented | Editor descriptors provide typed forms, initial values, and save behavior |
| req-web-editor-fields | [Field Strategy](#field-strategy) | Implemented | Start with Django Forms / ModelForms; structured-object fields may layer on later |
| req-web-editor-hotlinks | [Hotlink Editing Deferral](#hotlink-editing-deferral) | Backlog | Hotlinks require more complex editor logic and are explicitly deferred |
| req-web-editor-form.sec | [Editor Form Security](#editor-form-security) | Implemented | Generic editor security contract superseding panel-only wording |

### Editor Shell
----
RID: `req-web-editor-shell`

Status: `Implemented`

TAP Web provides a standard editor shell for editable objects. The shell is generic and not owned by any one object type.

#### Implementation
- The editor page is composed of three conceptual regions:
  - graph context preview at the top
  - object preview beneath it when the edited type supports one
  - typed editor form beneath the preview regions
- The shell provides standard actions:
  - `Save`
  - `Preview` is deferred to backlog; save + history-revert is the v1 undo strategy
- The shell owns page chrome, action placement, and request lifecycle.
- Edited object types provide only typed editor content and preview behavior.

#### Development
Keep the shell stable and make object types plug into it. The shell should not need to be rewritten for each new node or edge editor.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-shell-1 | Shared Editor Shell Exists | Implemented | TAP Web defines one standard editor page shell rather than per-type page structures. | `tap_web/templates/tap_web/editor.html` |
| req-web-editor-shell-2 | Standard Actions | Implemented | The shell exposes a `Save` action. `Preview` is deferred to backlog. | |
| req-web-editor-shell-3 | Type Supplies Editor Content | Implemented | Edited object types provide typed editor fields inside the shared shell rather than replacing the shell itself. | `EditorDescriptor` + `editor_template` |

### Graph Context Preview
----
RID: `req-web-editor-graph`

Status: `Implemented`

The top of the generic editor always shows a Cytoscape representation of the edited object in immediate graph context.

#### Implementation
- The graph preview uses a Gryphon neighborhood search rendered by the graph panel.
- The edited object is the hub.
- The graph includes:
  - the edited object
  - immediate outbound edges and connected nodes
  - immediate inbound edges and connected nodes
- The preview uses TAP-managed Cytoscape assets rather than CDN assets.
- The graph preview is read-only in the first implementation.

#### Development
Make graph context mandatory in the editor shell. TAP objects should not be edited as if they were disconnected rows in a CRUD admin.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-graph-1 | Graph Region Exists | Implemented | The top region of the generic editor contains a Cytoscape graph preview. | Graph panel rendered via synthetic page builder (`req-web-page-synthetic`) using GRIFT subgraph in `tap_web/data/` |
| req-web-editor-graph-2 | Edited Object Is Hub | Implemented | The edited object is centered conceptually as the hub in the graph preview. | Gryphon neighborhood search defined in the entity editor GRIFT subgraph; executed at render time |
| req-web-editor-graph-3 | Immediate Relationships Included | Implemented | The graph preview includes immediate inbound/outbound edges and connected nodes only. | |
| req-web-editor-graph-4 | Read Only In V1 | Implemented | The first graph preview does not mutate graph structure. | |

### Object Preview
----
RID: `req-web-editor-object-preview`

Status: `Proposed`

The generic editor may show an object-specific preview beneath the graph preview when the edited type has a meaningful human-facing representation.

#### Implementation
- Simple model-backed objects may omit a rich object preview and rely on the graph preview plus form fields.
- More advanced objects such as layouts, pages, and panels should provide an object preview showing what the object looks like.
- Object preview behavior is type-aware and optional at the contract level.

#### Development
Do not force every editable type to invent a visual preview. Reserve rich object previews for artifacts whose visible output is a core part of the editing task.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-object-preview-1 | Type-Aware Preview Supported | Proposed | Edited object types may provide an object-specific preview region. | |
| req-web-editor-object-preview-2 | Rich Artifacts Show What They Look Like | Proposed | Layouts, pages, panels, and similar artifacts may render a visual object preview in the generic editor shell. | |
| req-web-editor-object-preview-3 | Simple Types May Omit Rich Preview | Proposed | Simple model-backed objects are not required to provide a second rich preview surface beyond graph context. | |

### Editor Availability Contract
----
RID: `req-web-editor-availability`

Status: `Proposed`

Not every TAP Web object or panel type needs a typed editor in the first implementation. The editor contract must therefore distinguish between "editable and has a typed editor" and "renderable object with no editor in v1" so the UI can behave intentionally rather than looking broken.

#### Implementation
- TAP Web should support explicit editor availability metadata for object and panel types.
- An object type may declare:
  - editable with a typed editor
  - no typed editor in v1
- For panel types, absence of `editor_view` should be treated as an intentional no-editor state when the panel type is defined as view-only.
- The UI should be able to suppress or disable edit affordances when no editor is available, rather than routing users into a dead-end shell.

#### Development
This is especially relevant for viewer-style standard panels such as history and FLIP inspectors. They are useful and first-class even if they do not support custom editing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-availability-1 | Explicit No-Editor State | Proposed | TAP Web can explicitly represent that a given object or panel type has no typed editor in v1. | |
| req-web-editor-availability-2 | UI Honors Availability | Proposed | Edit affordances can be hidden or disabled when no editor is available. | |
| req-web-editor-availability-3 | No Dead-End Edit Route Assumption | Proposed | The editor contract does not assume every renderable object must have a usable edit screen. | |

### Preview Execution
----
RID: `req-web-editor-preview-exec`

Status: `Backlog`

Preview is explicitly deferred. The v1 undo strategy is save + history-revert via FLIP. Once the history system is live, reverting to a prior state is the equivalent of an undo operation, making preview a less urgent concern.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-preview-exec-1 | Preview Deferred | Backlog | Preview is not part of the v1 editor shell. History-revert is the v1 undo path. | |

### Typed Editor Contract
----
RID: `req-web-editor-typed`

Status: `Implemented`

Editable object types plug into the generic editor through a typed editor descriptor rather than raw JSON by default.

#### Implementation
- A typed editor descriptor provides:
  - `entity_type` — the entity type slug this descriptor handles
  - `form_class` — Django Form or ModelForm for the typed editor
  - `get_editor_initial(obj)` — returns initial field values for an existing object
  - `handle_save(form, obj, request)` — persists validated changes
  - optional `get_extra_context(obj)` — extra template context for type-specific rendering
  - optional `editor_template` — path to a custom form field template; generic field rendering used if absent
- Typed editor descriptors are the standard extension path for node, edge, and richer object editors.
- Raw JSON editing is a fallback/debug path rather than the primary editor contract.

#### Development
This keeps TAP editors grounded in domain fields and model semantics rather than encouraging every new editor to become a generic JSON blob surface.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-typed-1 | Typed Descriptor Contract Exists | Implemented | Editable object types integrate with the shell through a typed editor descriptor contract. | `EditorDescriptor` in `tap_web/editor.py`; `CharacterEditorDescriptor` in `plugins/lotr/editors/character.py` |
| req-web-editor-typed-2 | Initial State Hook | Implemented | Typed editors can provide initial field values for an existing object. | `get_editor_initial(obj)` |
| req-web-editor-typed-3 | Save Hook | Implemented | Typed editors persist validated changes through `handle_save`. | `handle_save(form, obj, request)` |
| req-web-editor-typed-4 | Raw JSON Is Fallback | Implemented | Raw JSON editing is not the default editor mode for typed objects. | JSON fallback only shown when no descriptor is registered |

### Field Strategy
----
RID: `req-web-editor-fields`

Status: `Implemented`

The editor system starts with Django Forms / ModelForms for ordinary fields and adds more specialized structured-object controls only when needed.

#### Implementation
- The preferred first-pass field strategies are:
  - `forms.ModelForm` for simple model-backed objects
  - `forms.Form` for mixed editors that combine model fields with related-edge or config fields
- Typical scalar fields should use standard Django form fields and widgets.
- Structured embedded objects should not force immediate adoption of a full schema-form system.
- If embedded object editing becomes necessary, TAP may add a focused structured-object widget later.

#### Development
This keeps the initial editor stack aligned with TAP's server-rendered Django + HTMX approach and avoids overcommitting to schema-form tooling that often becomes awkward for authored domain objects.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-fields-1 | Django Forms First | Implemented | Standard Django Forms / ModelForms are the default field editing mechanism. | `CharacterEditForm`, `TextPanelEditForm` |
| req-web-editor-fields-2 | Scalar Fields Use Standard Widgets | Implemented | Common scalar model fields use ordinary Django form fields and widgets in v1. | |
| req-web-editor-fields-3 | Structured Objects Layer Later | Implemented | Embedded structured-object editing may be added later without redefining the base editor contract. | |

### Hotlink Editing Deferral
----
RID: `req-web-editor-hotlinks`

Status: `Backlog`

Editing hotlinks requires relationship-aware logic beyond the first generic editor pass and is explicitly deferred.

#### Implementation
Future work must define:
- how hotlink-backed relationships are surfaced in the editor
- how preview applies hotlink changes before save
- how hotlink editing interacts with graph preview and related-object mutation

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-hotlinks-1 | Hotlink Editing Deferred Explicitly | Backlog | Hotlink editing is tracked as backlog work rather than assumed by the first editor contract. | |

### Editor Form Security
----
RID: `req-web-editor-form.sec`

Status: `Implemented`

Generic editor submissions must use standard Django form security protections. This requirement generalizes the earlier panel-only wording to all TAP Web editors.

#### Implementation
- CSRF protection is provided by Django middleware and required in all editor forms.
- Submitted values are validated server-side before preview or save.
- Untrusted input is written to persisted storage only from validated form data, never directly from raw request payloads.
- Rendered preview output uses the same default Django escaping rules unless a future hardened spec explicitly allows trusted HTML.

#### Development
Editor security should be defined once at the generic editor layer and then referenced by panel, node, and edge editors.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-editor-form.sec-1 | CSRF Required | Implemented | All generic editor forms include CSRF protection. | `{% csrf_token %}` in `editor.html` |
| req-web-editor-form.sec-2 | Server Validation Required | Implemented | Save uses server-side validation before applying editor input. | `form.is_valid()` before `handle_save` |
| req-web-editor-form.sec-3 | Untrusted Input Handling | Implemented | Persisted changes originate from validated form data rather than raw request payloads. | `form.cleaned_data` in all descriptors |
| req-web-editor-form.sec-4 | Default Escaping Applies | Implemented | Rendering uses standard Django escaping by default. | |

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
