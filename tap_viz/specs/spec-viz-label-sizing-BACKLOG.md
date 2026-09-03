# Viz Label Sizing Specification

## Philosophy

Viz labels should be readable when a scene first appears. A user should not need to zoom in merely to make primary names legible. Zoom is for spatial exploration and changing focus, not for rescuing undersized text.

At the same time, TAP Viz should not treat label size as a fixed per-node pixel constant. Good diagram behavior comes from semantic sizing and bounded responsiveness. Labels should use a small shared vocabulary of semantic size tiers, and the renderer should let those labels scale a little as the viewport zoom changes while keeping them within a readable on-screen range.

This specification therefore defines a scene-oriented label-sizing model: semantic tiers such as `large`, `normal`, and `small`; model-level defaults exposed through `DEFAULT_DISPLAY`; layout- or projection-level overrides when a scene needs them; and a renderer policy that preserves legibility for node, parent, and edge labels.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Readable On Load | Primary labels should be legible when the initial scene renders. |
| 2. | Semantic | TAP Viz should use label-size tiers rather than arbitrary per-object font values. |
| 3. | Responsive | Labels should scale gently with zoom rather than remaining perfectly fixed or shrinking into illegibility. |
| 4. | Bounded | Label sizing should respect a readable floor and a non-comical ceiling. |
| 5. | Shared | The same system should apply across leaf-node labels, parent labels, and edge labels. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-label-sizing-tiers | [Semantic Label Size Tiers](#semantic-label-size-tiers) | Proposed | `large`, `normal`, and `small` are the canonical v0 tiers |
| req-viz-label-sizing-default-display | [Model-Level Label Size Defaults](#model-level-label-size-defaults) | Proposed | Default label size tier may live in `DEFAULT_DISPLAY["tap_viz"]["label_size"]` |
| req-viz-label-sizing-layout-override | [Scene-Level Overrides](#scene-level-overrides) | Proposed | Layouts and projections may override label-size defaults for a rendered scene |
| req-viz-label-sizing-readable-load | [Readable Initial Scene](#readable-initial-scene) | Proposed | Initial scenes should not require zoom just to read primary labels |
| req-viz-label-sizing-zoom-response | [Bounded Zoom Response](#bounded-zoom-response) | Proposed | Labels scale gently with zoom within a readable range |
| req-viz-label-sizing-shared-system | [Shared Label Sizing System](#shared-label-sizing-system) | Proposed | Node, parent, and edge labels use the same semantic sizing model |

## Requirements

### Semantic Label Size Tiers
----
RID: `req-viz-label-sizing-tiers`

Status: `Proposed`

TAP Viz uses semantic label-size tiers rather than arbitrary per-label font values.

#### Implementation

The canonical v0 label-size tiers are:

- `large`
- `normal`
- `small`

These are renderer-level semantic tokens, not ad hoc one-off size declarations.

Representative baseline sizes are:

- `large = 18px`
- `normal = 14px`
- `small = 12px`

#### Development

Semantic tiers make scene design easier to reason about. A layout can say that a world name should be `large`, a location or character name should be `normal`, and a denser secondary label should be `small` without hand-tuning arbitrary font values object by object.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-tiers-1 | Canonical Tier Vocabulary | Proposed | The v0 label-size vocabulary is `large`, `normal`, and `small`. | |
| req-viz-label-sizing-tiers-2 | Semantic Not Ad Hoc | Proposed | Label sizes are specified as semantic tiers rather than free-form per-label font declarations. | |
| req-viz-label-sizing-tiers-3 | Baseline Px Mapping Exists | Proposed | The spec defines representative px baselines for the semantic tiers. | |

#### Future

Add more tiers only if real scene-design pressure proves the three-tier vocabulary insufficient.


### Model-Level Label Size Defaults
----
RID: `req-viz-label-sizing-default-display`

Status: `Proposed`

Models may expose a default label-size tier through viz display metadata.

#### Implementation

The optional hint path is:

- `DEFAULT_DISPLAY["tap_viz"]["label_size"]`

Allowed values are:

- `large`
- `normal`
- `small`

When no layout or projection override is present, the runtime may use this model-level default.

When neither a scene override nor model-level default is present, the fallback is:

- `normal`

#### Development

This lets a model carry a sensible default label emphasis without forcing every scene to restate it, while preserving layout and projection control when scene readability needs differ.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-default-display-1 | Metadata Path Defined | Proposed | Default label size may live at `DEFAULT_DISPLAY["tap_viz"]["label_size"]`. | |
| req-viz-label-sizing-default-display-2 | Allowed Values Defined | Proposed | The allowed values are `large`, `normal`, and `small`. | |
| req-viz-label-sizing-default-display-3 | Fallback Is Normal | Proposed | When no explicit hint is present, the default label size tier is `normal`. | |

#### Future

If TAP later supports richer typographic metadata, keep `label_size` as the simple common-case hint and layer more advanced controls carefully.


### Scene-Level Overrides
----
RID: `req-viz-label-sizing-layout-override`

Status: `Proposed`

Layouts and projections may override model-level label-size defaults for a specific rendered scene.

#### Implementation

- Scene-level label sizing may be assigned by layout or projection logic.
- Scene-level assignments take precedence over model-level `DEFAULT_DISPLAY` hints.
- Scene-level overrides should use the same semantic tier vocabulary:
  - `large`
  - `normal`
  - `small`

#### Development

Scene role often matters more than object type. A character name may be `normal` in one scene and become `large` in a detail-focused character scene. Layout and projection logic should be free to express that without changing the model's general default.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-layout-override-1 | Scene Overrides Allowed | Proposed | Layouts and projections may override model-level label-size defaults. | |
| req-viz-label-sizing-layout-override-2 | Scene Overrides Use Same Vocabulary | Proposed | Scene-level overrides use the same `large` / `normal` / `small` tier system. | |

#### Future

Define the exact runtime wiring for projection- and layout-driven label sizing after the first implementation proves out.


### Readable Initial Scene
----
RID: `req-viz-label-sizing-readable-load`

Status: `Proposed`

Primary labels should be legible when a scene first renders.

#### Implementation

- Initial scene composition should assign label tiers so important names are readable on first load.
- Users should not need to zoom in simply to make primary labels legible.
- Layouts and projections should treat readability as part of scene design, not as an afterthought delegated entirely to zoom behavior.

#### Development

This is the behavioral core of the requirement. A good TAP Viz scene should open with readable names for the objects that matter at that view level.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-readable-load-1 | Primary Labels Readable On Load | Proposed | Important scene labels are intended to be legible at initial render. | |
| req-viz-label-sizing-readable-load-2 | Zoom Not Required For Legibility | Proposed | The spec rejects the pattern where users must zoom in merely to make main labels readable. | |

#### Future

If TAP later formalizes projection design guidance, include label-readability checks as part of projection acceptance criteria.


### Bounded Zoom Response
----
RID: `req-viz-label-sizing-zoom-response`

Status: `Proposed`

Labels should scale gently with zoom while staying within a readable on-screen range.

#### Implementation

- Label sizing should respond to zoom changes.
- The response should be gentle rather than literal full geometric scaling.
- The renderer should use one shared zoom-response policy across label tiers.
- Effective rendered label size must remain within a bounded readable range.

The v0 target readable range is:

- minimum effective label size: `12px`
- maximum effective label size: `20px`

The exact zoom-response curve is implementation-defined as long as it preserves the intent of gentle scaling within this readable range.

#### Development

This avoids both extremes:

- labels that shrink into illegibility when zoomed out
- labels that become cartoonishly large when zoomed in

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-zoom-response-1 | Zoom Response Exists | Proposed | Labels respond to zoom rather than remaining strictly fixed. | |
| req-viz-label-sizing-zoom-response-2 | Shared Policy | Proposed | The zoom-response behavior is uniform across the label-sizing system. | |
| req-viz-label-sizing-zoom-response-3 | Readable Floor Defined | Proposed | Effective rendered label size does not drop below `12px`. | |
| req-viz-label-sizing-zoom-response-4 | Readable Ceiling Defined | Proposed | Effective rendered label size does not exceed `20px`. | |

#### Future

If real scenes show that the readable band should vary by renderer or display density, adjust the band carefully while preserving the semantic tier model.


### Shared Label Sizing System
----
RID: `req-viz-label-sizing-shared-system`

Status: `Proposed`

The semantic label-sizing system applies across node, parent, and edge labels.

#### Implementation

- Leaf-node labels participate in the shared label-sizing model.
- Parent labels participate in the shared label-sizing model.
- Edge labels participate in the shared label-sizing model.
- Different label renderers may exist internally, but they should honor the same semantic tier vocabulary and bounded zoom-response policy.

#### Development

This keeps TAP Viz from drifting into one label-sizing policy for ordinary nodes, another for compound labels, and a third for edges. The user should experience one coherent labeling system.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-shared-system-1 | Node Labels Included | Proposed | Ordinary node labels use the shared semantic label-sizing system. | |
| req-viz-label-sizing-shared-system-2 | Parent Labels Included | Proposed | Parent labels use the shared semantic label-sizing system. | |
| req-viz-label-sizing-shared-system-3 | Edge Labels Included | Proposed | Edge labels use the shared semantic label-sizing system. | |

#### Future

Define whether some edge-heavy scenes should intentionally suppress or de-emphasize edge labels without breaking the shared sizing model.
