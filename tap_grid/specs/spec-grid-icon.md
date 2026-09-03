# Grid Icon Specification

## Philosophy

Icons are a cross-cutting presentation concern used by multiple TAP surfaces such as web pages, graph visualizations, admin tools, and future clients. TAP needs one grid-level icon contract so higher-level systems can rely on consistent icon ownership, lookup, validation, and rendering behavior instead of inventing their own file conventions.

The first version should stay intentionally narrow: type-level icons only, SVG only, app/plugin-scoped static assets only, and decorative rendering only. More flexible features such as instance-level overrides or user-uploaded icons should be tracked explicitly rather than implied.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Consistent | One icon contract applies across web, viz, admin, and plugin consumers |
| 2. | Scoped | Icons resolve within the owning app or plugin rather than a global flat namespace |
| 3. | Lightweight | Key-by-convention avoids verbose per-icon path metadata |
| 4. | Safe | Icon lookup and rendering stay within validated static asset boundaries |
| 5. | Evolvable | Instance-level overrides and uploaded icons are tracked separately for future work |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-icon-type | [Type-Level Icon Ownership](#type-level-icon-ownership) | Implemented | Canonical icons belong to entity types in v1 |
| req-grid-icon-key | [Icon Key And Path Resolution](#icon-key-and-path-resolution) | Implemented | App-scoped icon keys resolve by convention into each app/plugin's static icons directory |
| req-grid-icon-format | [Icon File Format](#icon-file-format) | Implemented | SVG is the only allowed icon file format in v1 |
| req-grid-icon-render | [Icon Rendering Contract](#icon-rendering-contract) | Implemented | Icons are decorative visual cues and must not be the sole carrier of meaning |
| req-grid-icon-instance | [Instance-Level Icon Overrides](#instance-level-icon-overrides) | Backlog | Future support for per-instance icon overrides |

---

### Type-Level Icon Ownership
----
RID: `req-grid-icon-type`

Status: `Implemented`

In v1, canonical TAP icons belong to entity types rather than individual entity instances.

#### Status Details
This requirement formalizes the narrow first version: one icon per entity type, with no per-instance override behavior yet.

#### Implementation
- Every entity type may declare one canonical icon.
- Type-level icon metadata belongs with the entity type definition and catalog metadata, not with per-instance entity metadata.
- In current TAP implementation terms, this aligns naturally with the existing entity-type/icon registration surface.
- The icon contract applies to all entity types across core apps and plugins.
- Instance-level icon overrides are out of scope for v1 and tracked separately in `req-grid-icon-instance`.

#### Development
Keep canonical ownership at the type level first. This avoids making every concrete entity instance carry presentation-specific icon state before there is a clear product need.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-type-1 | Type-Level Ownership | Implemented | Canonical icons belong to entity types in v1. | `icon` metadata on entity type registration |
| req-grid-icon-type-2 | Applies Across All Entity Types | Implemented | The icon contract applies to entity types defined by TAP core apps and plugins. | Used by `tap_grid`, `tap_web`, `tap_viz`, and LOTR plugin |
| req-grid-icon-type-3 | Instance Overrides Deferred | Implemented | Per-instance icon override behavior is not part of v1. | Tracked by `req-grid-icon-instance`. |

#### Future
Allow entity instances to override their type icon without changing the type's canonical icon.

### Icon Key And Path Resolution
----
RID: `req-grid-icon-key`

Status: `Implemented`

Icons are resolved by app/plugin-scoped key convention rather than arbitrary file paths stored in metadata.

#### Status Details
This requirement formalizes key-by-convention lookup and app/plugin isolation.

#### Implementation
- The canonical icon metadata value is an icon key, not a free-form path.
- Icon keys are scoped to the app or plugin that owns the entity type.
- The icon key should use kebab-case format.
- Consumers derive the icon file location by convention from the owning app/plugin plus the icon key.
- Canonical source location inside an app or plugin is:
  - `<app>/static/<app-static-namespace>/icons/<icon-key>.svg`
- Canonical static-relative lookup path is:
  - `<app-static-namespace>/icons/<icon-key>.svg`
- For plugins, `<app-static-namespace>` is the plugin app label used by Django staticfiles resolution.
- A plugin that declares slug `grid_fixtures` and icon key `constrained-source` therefore resolves to:
  - source file: `plugins/grid_fixtures/static/grid_fixtures/icons/constrained-source.svg`
  - static-relative path: `grid_fixtures/icons/constrained-source.svg`
- Examples:
  - `tap_web/static/tap_web/icons/page.svg`
  - `tap_viz/static/tap_viz/icons/layout.svg`
  - `plugins/grid_fixtures/static/grid_fixtures/icons/constrained-source.svg`
- The icon resolver must not accept arbitrary relative paths, parent-directory traversal, or remote URLs.
- Icon validation must confirm:
  - the icon key format is valid
  - the resolved path stays within the owning app/plugin icon directory
  - the file exists
  - the file extension is allowed

#### Development
Store only the icon key and derive the path by convention. This keeps metadata small and allows apps/plugins to own their own icon namespace cleanly.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-key-1 | Key By Convention | Implemented | Icon metadata uses an icon key rather than an arbitrary path string. | `icon_key` on entity type config |
| req-grid-icon-key-2 | App Scoped Resolution | Implemented | Icon resolution is scoped to the app or plugin that owns the entity type. | `resolve_icon_url(entity_type)` in `tap_grid/icon.py` |
| req-grid-icon-key-3 | Canonical Static Icons Directory | Implemented | Icons resolve from each app/plugin's `static/.../icons/` directory by convention. | e.g. `tap_web/static/tap_web/icons/page.svg` |
| req-grid-icon-key-4 | Path Validation Required | Implemented | Icon validation rejects invalid keys, invalid resolved paths, missing files, disallowed extensions, and remote paths. | `tap_grid/icon.py` validation logic |

#### Future
If TAP later supports richer icon metadata, keep convention-based resolution as the default and add explicit path metadata only with strong justification.

### Icon File Format
----
RID: `req-grid-icon-format`

Status: `Implemented`

SVG is the only allowed icon file format in v1.

#### Status Details
This requirement intentionally narrows format support to keep the contract simple and modern.

#### Implementation
- Canonical icon files use `.svg`.
- Raster formats such as PNG, JPG, or ICO are not part of the v1 icon standard.
- TAP does not require multiple size-specific icon files in v1.
- One canonical SVG per icon key is sufficient.
- If later optimization work introduces size-specific variants, the default unsuffixed SVG remains the canonical fallback asset.

#### Development
SVG scales cleanly and keeps the first specification small. Do not introduce a large format matrix before there is a demonstrated need.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-format-1 | Svg Only | Implemented | SVG is the only allowed icon file format in v1. | `.svg` extension enforced in `icon_service.py` |
| req-grid-icon-format-2 | Single Canonical Asset Sufficient | Implemented | A single canonical SVG per icon key is sufficient; multiple size variants are not required. | |
| req-grid-icon-format-3 | Size Variants Deferred | Implemented | Size-specific icon variants are not part of the initial icon standard. | |

#### Future
Add optional size-specific variants only if there is a demonstrated need for optimized hand-tuned icon assets.

### Icon Rendering Contract
----
RID: `req-grid-icon-render`

Status: `Implemented`

Icons are decorative visual cues and must not be the sole carrier of meaning for a TAP object.

#### Status Details
This requirement sets the semantic rendering contract without dictating specific UI implementations.

#### Implementation
- Icons are not load-bearing identity for an entity type.
- Systems that render icons must also render associated textual identity elsewhere when object identity matters.
- Missing icons must not make the object unusable or uninterpretable.
- TAP-authored icons should use `currentColor` for CSS color inheritance where practical.
- Plugin icons that represent third-party branded services (e.g. AWS, GCP) may use the vendor's native brand colors rather than `currentColor`. The rendering pipeline treats SVGs as image assets, so multi-color icons display correctly.
- V1 icon rendering should treat icons as image assets rather than inline executable markup.

#### Development
Keep icon semantics conservative. They are visual affordances, not the canonical source of object meaning.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-render-1 | Decorative By Default | Implemented | Icons are decorative visual cues rather than the sole carrier of meaning. | Graph nodes always render label text alongside icon |
| req-grid-icon-render-2 | Text Identity Still Required | Implemented | Consumers that need object identity also render associated textual identity elsewhere. | `label: data(label)` always shown beneath node |
| req-grid-icon-render-3 | Missing Icon Safe Fallback | Implemented | Missing icons do not make the object unusable or uninterpretable. | Nodes without `icon_url` fall back to solid-color ellipse |
| req-grid-icon-render-4 | Theming Through Color Inheritance | Implemented | TAP-authored icons use `currentColor` for theming. Plugin icons for third-party branded services may use native brand colors. | Rendering pipeline treats SVGs as image assets; multi-color icons work correctly |

#### Future
Define more specific accessibility guidance if TAP later introduces UIs where an icon may appear without adjacent text.

### Instance-Level Icon Overrides
----
RID: `req-grid-icon-instance`

Status: `Backlog`

Per-instance icon overrides are a future capability and are not part of the initial icon standard.

#### Status Details
Tracked explicitly so the v1 type-level contract is clear and future enhancement does not require re-opening the ownership question.

#### Implementation
Future work may define:
- where instance-level icon metadata lives
- how instance icons override type icons
- whether instance icons may be uploaded, generated, or selected from a catalog
- how instance-level security and validation differ from shipped static type icons

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-instance-1 | Instance Override Backlog Exists | Backlog | Instance-level icon override behavior is tracked explicitly as future work. | |

#### Future
Define storage, resolution order, and security rules for per-instance icons once there is a concrete product need.

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
