# Viz Label Sizing Specification

## Philosophy

Viz labels should be readable when a scene first appears. A user should not need to zoom in merely to make primary names legible. Zoom is for spatial exploration and changing focus, not for rescuing undersized text.

At the same time, TAP Viz should not treat label size as a fixed per-node pixel constant. Good diagram behavior comes from semantic sizing and bounded responsiveness. Labels should use a small shared vocabulary of semantic size tiers, and the renderer should let those labels scale a little as the viewport zoom changes while keeping them within a readable on-screen range.

The same reasoning applies to the other things drawn at a fixed size in model units: border widths, edge widths, arrowheads and icon-node cards. When the viewer zooms, a hairline border becomes a thick bar and a legible icon becomes a billboard, because the renderer multiplies every model-unit size by the zoom. This specification therefore also defines one zoom-response policy, a single exponent, that governs labels, strokes and icons together, from fully geometric scaling (today's behavior) to strictly constant on-screen size.

This specification defines a scene-oriented label-sizing model: semantic tiers such as `large`, `normal`, and `small`; model-level defaults exposed through `DEFAULT_DISPLAY`; layout- or projection-level overrides when a scene needs them; and a renderer policy that preserves legibility for node, parent, and edge labels.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Readable On Load | Primary labels should be legible when the initial scene renders. |
| 2. | Semantic | TAP Viz should use label-size tiers rather than arbitrary per-object font values. |
| 3. | Responsive | Labels should scale gently with zoom rather than remaining perfectly fixed or shrinking into illegibility. |
| 4. | Bounded | Label sizing should respect a readable floor and a non-comical ceiling. |
| 5. | Shared | The same system should apply across leaf-node labels, parent labels, and edge labels. |
| 6. | Perspective-Stable | Borders, edge widths and icon cards follow the same zoom policy as labels, so a chosen setting keeps them a similar on-screen size at any zoom. |
| 7. | One Dial | A single exponent per element class sets how far an element scales with zoom, from fully geometric to constant on screen. |
| 8. | Layout Independent | Zoom-driven sizing changes drawing only; it never changes node sizes or layout positions. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-label-sizing-tiers | [Semantic Label Size Tiers](#semantic-label-size-tiers) | Proposed | `large`, `normal`, and `small` are the canonical v0 tiers |
| req-viz-label-sizing-default-display | [Model-Level Label Size Defaults](#model-level-label-size-defaults) | Proposed | Default label size tier may live in `DEFAULT_DISPLAY["tap_viz"]["label_size"]` |
| req-viz-label-sizing-layout-override | [Scene-Level Overrides](#scene-level-overrides) | Proposed | Layouts and projections may override label-size defaults for a rendered scene |
| req-viz-label-sizing-readable-load | [Readable Initial Scene](#readable-initial-scene) | Proposed | Initial scenes should not require zoom just to read primary labels |
| req-viz-label-sizing-zoom-response | [Bounded Zoom Response](#bounded-zoom-response) | Proposed | Labels scale gently with zoom within a readable range |
| req-viz-label-sizing-zoom-exponent | [Zoom Exponent](#zoom-exponent) | Proposed | On-screen size is `base * zoom^a`; `a` is the one dial from geometric (1) to constant (0) |
| req-viz-label-sizing-stroke-icon | [Strokes And Icons](#strokes-and-icons) | Proposed | Border widths, edge widths, arrowheads and icon cards use the same exponent policy |
| req-viz-label-sizing-draw-only | [Drawing Only, Not Layout](#drawing-only-not-layout) | Proposed | Zoom-driven sizing never alters node sizes or layout positions; overlays counter-scale |
| req-viz-label-sizing-shared-system | [Shared Label Sizing System](#shared-label-sizing-system) | Proposed | Node, parent, and edge labels use the same semantic sizing model |
| req-viz-label-sizing-settle | [Settle Mode](#settle-mode) | Implemented | The zoom exponent is applied once, after the zoom has been still for a debounce, never per frame; opt-in per panel |

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

The zoom-response curve is the one defined by [Zoom Exponent](#zoom-exponent); the `12px` to `20px` band is the clamp that policy applies to labels.

#### Development

This avoids both extremes:

- labels that shrink into illegibility when zoomed out
- labels that become cartoonishly large when zoomed in

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-zoom-response-1 | Zoom Response Exists | Proposed | Labels follow a declared zoom-response policy rather than the renderer's implicit full geometric scaling. | A policy with exponent `0` is a valid declared policy (constant on screen). |
| req-viz-label-sizing-zoom-response-2 | Shared Policy | Proposed | The zoom-response behavior is uniform across the label-sizing system. | |
| req-viz-label-sizing-zoom-response-3 | Readable Floor Defined | Proposed | Effective rendered label size does not drop below `12px`. | |
| req-viz-label-sizing-zoom-response-4 | Readable Ceiling Defined | Proposed | Effective rendered label size does not exceed `20px`. | |

#### Future

If real scenes show that the readable band should vary by renderer or display density, adjust the band carefully while preserving the semantic tier model.


### Zoom Exponent
----
RID: `req-viz-label-sizing-zoom-exponent`

Status: `Proposed`

The on-screen size of a zoom-responsive element is `base * zoom^a`, clamped to a floor and a ceiling. The exponent `a` is the single dial that sets how far the element follows the zoom.

#### Implementation

- `base` is the element's on-screen size in px at zoom `1`. For labels it comes from the semantic tier (`large`, `normal`, `small`); for strokes and icons it comes from the element class.
- `a` is a number from `0` to `1`:
  - `a = 1` is full geometric scaling: the element grows and shrinks with the scene. This is the renderer's behavior without any policy.
  - `a = 0` is strict constant size: the element has the same on-screen size at every zoom.
  - Values between give gentle scaling. A value in the range `0.2` to `0.4` is the expected default for labels.
- The renderer draws in model units and the library multiplies every model-unit size by the current zoom. To realize `base * zoom^a` on screen, the model-unit value written to the style is `base * zoom^(a - 1)`.
- The result is clamped: the on-screen size is held between a floor and a ceiling, and the model-unit value is the clamped on-screen size divided by the zoom. Labels use `12px` and `20px` per [Bounded Zoom Response](#bounded-zoom-response).
- The exponent, floor and ceiling are declared per element class (label, border, edge, arrowhead, icon). They may be set as a runtime default, and overridden by a layout or projection using the same override precedence as label tiers.
- Style values are recomputed once the zoom has stopped changing ([Settle Mode](#settle-mode)), never per frame, and only for classes whose exponent is below `1`.

#### Development

One formula replaces three separate ideas. "Labels scale gently within a band" is a small `a` with a clamp. "Everything stays the same size" is `a = 0`. "Today" is `a = 1`. A scene or a panel picks a point on the dial instead of the runtime hard-coding one answer.

Strict constant size has a cost: zoomed far out, every node still carries a full-size label and border, so labels collide and icon cards outgrow the cells they sit in. The clamp and a small non-zero default exponent are the mitigation, and [elevations](spec-viz-elevation.md) remain the mechanism that decides what is shown at each altitude.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-zoom-exponent-1 | Formula Defined | Proposed | Rendered on-screen size equals `base * zoom^a`, then clamped; the model-unit style value is the clamped on-screen size divided by the zoom. | |
| req-viz-label-sizing-zoom-exponent-2 | Exponent Range | Proposed | `a` accepts values from `0` to `1` inclusive; `1` reproduces unmodified geometric scaling and `0` yields identical on-screen size at every zoom (within the clamp). | A value outside the range is rejected, not clamped silently. |
| req-viz-label-sizing-zoom-exponent-3 | Per-Class Declaration | Proposed | Exponent, floor and ceiling are declared per element class, and an undeclared class keeps full geometric scaling. | |
| req-viz-label-sizing-zoom-exponent-4 | Override Precedence | Proposed | A layout or projection may override the runtime default exponent using the same precedence as label tiers. | |
| req-viz-label-sizing-zoom-exponent-5 | Update Only After Zoom Settles | Proposed | Style recomputation does not run per frame. It runs once, after the zoom has been still, as [Settle Mode](#settle-mode) defines, and is skipped for classes with exponent `1`. | Replaces the per-animation-frame throttle this row first proposed: per-frame writes were measured and rejected (see Settle Mode). |
| req-viz-label-sizing-zoom-exponent-6 | Smoothness Verified | Proposed | Before the policy is enabled by default, a measurement on a scene of at least several hundred nodes shows continuous wheel-zoom stays interactive. | Measured for settle mode (see Settle Mode, Measured): frames during the gesture are unchanged. A browser pass with the GPU enabled is still owed. |

#### Future

Strict mode (`a = 0`) may hide labels that collide at deep zoom-out instead of drawing them overlapped. That is a collision policy layered above this one and is not specified here.


### Strokes And Icons
----
RID: `req-viz-label-sizing-stroke-icon`

Status: `Proposed`

Border widths, edge widths, arrowheads and icon-node cards follow the same zoom-response policy as labels.

#### Implementation

- Node and parent border widths, edge line widths and arrowhead sizes are zoom-responsive element classes under [Zoom Exponent](#zoom-exponent).
- The icon-node card size ([spec-viz-icon-node.md](spec-viz-icon-node.md)) is a zoom-responsive element class. Its existing size parameter is the seam: the policy supplies the model-unit size for the current zoom. This realizes the pre-scale for zoom that the icon-node spec anticipates.
- Each class has its own base, exponent and clamp. A hairline border may use a lower floor than a label, and an icon card a larger ceiling.

#### Development

Strokes and icons are where the effect is most visible. A one-pixel border looks right at one zoom and becomes a slab or vanishes at others. Putting them under the same formula as labels keeps a scene visually even as the viewer moves through it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-stroke-icon-1 | Borders Included | Proposed | Node and parent border widths are zoom-responsive element classes. | |
| req-viz-label-sizing-stroke-icon-2 | Edges Included | Proposed | Edge line widths and arrowhead sizes are zoom-responsive element classes. | |
| req-viz-label-sizing-stroke-icon-3 | Icon Cards Included | Proposed | The icon-node card size is driven by the zoom-response policy through its existing size parameter. | |
| req-viz-label-sizing-stroke-icon-4 | Independent Classes | Proposed | Each element class carries its own base, exponent and clamp. | |

#### Future

Shadow offsets and badge sizes may join as further element classes once the first set proves out.


### Drawing Only, Not Layout
----
RID: `req-viz-label-sizing-draw-only`

Status: `Proposed`

Zoom-driven sizing changes how elements are drawn. It never changes node sizes, text-measured dimensions or layout positions.

#### Implementation

- Node dimensions that the runtime derives from measured text are computed from the base font at a reference zoom, not from the zoom-adjusted font. The zoom-adjusted font is applied only to drawing.
- Layout and projection runs use the reference sizes, so panning and zooming never trigger or perturb a layout.
- HTML overlays that are positioned with a CSS `scale(zoom)` transform (parent labels, scope boxes) apply the inverse factor to their own text and border so their on-screen size follows the same exponent as canvas-drawn elements.

#### Development

If the font changed with zoom and node sizes were derived from the font, every zoom step would resize nodes and move the layout, a feedback loop. Keeping measurement at a reference zoom breaks it. The overlays need explicit handling because they are scaled by the transform rather than by the style system.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-draw-only-1 | Layout Unaffected | Proposed | Changing zoom does not change any node's model-space width, height or position. | |
| req-viz-label-sizing-draw-only-2 | Reference-Zoom Measurement | Proposed | Text-derived node sizes are measured with the base font independent of the current zoom. | |
| req-viz-label-sizing-draw-only-3 | Overlays Follow Policy | Proposed | HTML overlay text and borders follow the same exponent as canvas-drawn elements of their class. | |

#### Future

None identified.


### Settle Mode
----
RID: `req-viz-label-sizing-settle`

Status: `Implemented`

The zoom exponent is applied once, where the viewer stops zooming. During the gesture nothing is written and the scene scales geometrically, which the renderer does for free. When the zoom has been still for a debounce, one rewrite sets fonts, borders, edge widths, arrow scales and icon-card sizes for the zoom reached. Settle mode is opt-in per panel; a panel that does not enable it renders exactly as before.

#### Implementation

Runtime: `tap_viz/static/tap_viz/js/runtime/zoom-settle.js` (`initZoomSettle`), started by `panel-graph.js` when the panel's config carries an enabled `zoom_settle` object. Schema and server-side validation: `ZOOM_SETTLE_SCHEMA` in `tap_viz/panels/graph_panel/__init__.py`.

Config key `zoom_settle` of the Graph panel (every entry is described in the schema):

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | none (required) | Must be `true`. Absent or `false` is off. |
| `debounce_ms` | `150` | Milliseconds the zoom must stay unchanged before the rewrite. Integer `0` to `5000`. |
| `exponent` | `0.3` | The `a` of [Zoom Exponent](#zoom-exponent) for every class. `0` to `1`. |
| `classes.<class>` | see below | Per-class `exponent`, `min_scale`, `max_scale`; an omitted key takes the default. Classes: `font`, `border`, `edge`, `arrow`, `icon`. |
| `texture_on_viewport` | `false` | Pass `textureOnViewport` to Cytoscape so motion frames draw from a bitmap. |

The clamp is a band around the element's own base size: `min_scale` (greater than `0`, at most `1`) and `max_scale` (`1` to `10`). Defaults: `font` `0.85` to `1.45` (the `12` to `20` px label band around the `14` px `normal` tier); `border`, `edge`, `arrow`, `icon` `0.6` to `1.7`. An out-of-range value disables settle mode for the panel (logged), it is not clamped silently.

Behaviour:

- **Base.** An element's base is its computed model-unit style value, read the first time it is written. If the value found later is not the one settle mode wrote, another writer (a layout module, an elevation) changed it and the new value becomes the base.
- **Factor.** The value written is `base * clamp(z^a, min_scale, max_scale) / z`, so the on-screen size is `base * clamp(z^a, ...)`.
- **Debounce.** Every `zoom` event restarts a timer of `debounce_ms`; nothing is written until it fires. Pan does not restart it.
- **Two batches.** The first batch, inside one `cy.batch`, covers the visible nodes (viewport plus a 40 px margin), every compound parent, and the edges touching those. The second batch, in a later task (animation frame, then a zero-delay timeout) so the first can paint, covers everything else. A new zoom supersedes an unfinished second batch, because the next pass writes every element again.
- **Bypass writes only.** Values are written with `ele.style(...)` (bypass). The append form `cy.style().selector().style().update()` is not used: it re-parses and re-applies the whole stylesheet. Cytoscape has no `hideLabelsOnViewport` option (absent in 3.34.3) and none is used.
- **Reference measurement.** On `layoutstart` every written value is put back to its base, so a layout or a text measurement sees the reference sizes; after `layoutstop` (and on added elements) a settle is scheduled. `destroy()` restores the bases.
- **Classes.** `font`: node, parent and labelled-edge `font-size`. `border`: `border-width`. `edge`: edge `width`. `arrow`: `arrow-scale`. `icon`: `width` and `height` of icon nodes only (`_is_icon_node`); an icon card is a model-space size, so it can grow into neighbours inside the clamp, which is why its band is the narrowest the scene tolerates.
- **Overlays.** The HTML parent-label overlay is scaled by a CSS transform and is not covered by this version; it keeps geometric scaling ([Drawing Only, Not Layout](#drawing-only-not-layout) `-3` stays open).

#### Measured

Headless Chromium (software rendering), scenes of 300, 600 and 1000 nodes with about 1.2 edges per node, 12 nodes per compound, 30 percent icon nodes, 48-step wheel zoom. Source: the `zoomscale-bench` harness (`settle.html`, `settle.py`, `settle_results.jsonl`), 3 repetitions per cell, means.

| Scenario | 300 | 600 | 1000 |
| --- | --- | --- | --- |
| Frame interval during zoom, no policy (ms) | 39 | 38 | 36 |
| Frame interval during zoom, settle mode (ms) | 39 | 37 | 39 |
| Settle pass, script time, both batches (ms) | 27 | 37 | 58 |
| Same policy written every frame, visible only: wheel handler (ms) | 19 | 23 | 25 |
| Same policy written every frame: frame interval (ms) | 87 | 103 | 119 |
| `textureOnViewport` frame interval (ms) | 5 | 4 | 4 |

On the real playground landing graph (609 nodes, 603 edges, default config, headless Chromium, 4 passes): the first batch took 37 to 127 ms of script and the pass was complete after 210 to 260 ms including the two frames it waits for. That is slower than the synthetic scene because a font-size bypass write leaves a node's cached label bounds at the old size and the canvas then clips the larger text, so settle mode calls `ele.dirtyBoundingBoxCache()` after every font write (without it parent labels drew as clipped glyph fragments); the invalidation accounts for most of the pass. The first (visible) batch alone is about 6 ms at 300 nodes zoomed in on the synthetic scene. Per-frame writes are therefore not acceptable (frames two to three times slower); a single class per frame, on visible elements only (border, font, icon or edge alone), still costs 4 to 12 ms per frame. `textureOnViewport` makes motion frames about ten times cheaper but draws them from a bitmap, so they are soft while moving; it is an option, default off, and its look has not been judged.

#### Development

Per-frame work was the cost the earlier design carried; moving it to the end of the gesture removes it from the path the viewer feels, and the one pass is cheap enough to be invisible after a 150 ms pause. Between pauses the scene is geometrically scaled, so the policy shows after the viewer stops, which is where reading happens.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-label-sizing-settle-1 | Opt-In | Implemented | Settle mode runs only for a panel whose `zoom_settle.enabled` is `true`; a panel without it, or with a malformed config, is rendered unchanged. | `_zoom_settle_attr`; `normalizeSettleConfig`. |
| req-viz-label-sizing-settle-2 | Config Schema | Implemented | `zoom_settle` has a JSON Schema in which the object and every key carry a description, with the defaults and ranges above. | `ZOOM_SETTLE_SCHEMA`. |
| req-viz-label-sizing-settle-3 | No Writes During Zoom | Implemented | While the zoom is changing no style is written; the rewrite starts only after `debounce_ms` without a `zoom` event. | |
| req-viz-label-sizing-settle-4 | Formula And Clamp | Implemented | The written value is `base * clamp(z^a, min_scale, max_scale) / z`; exponent `0` yields identical on-screen size at two zooms inside the band, and the band holds outside it. | `modelFactor`. |
| req-viz-label-sizing-settle-5 | Two-Batch Order | Implemented | Visible nodes, all compound parents and their edges are written in the first batch; the remaining elements are written in a later task. | |
| req-viz-label-sizing-settle-6 | Bypass Writes Only | Implemented | Writes are element bypass styles inside `cy.batch`; the stylesheet is never re-applied and `hideLabelsOnViewport` is not used. | |
| req-viz-label-sizing-settle-7 | Reference Measurement | Implemented | Layout start restores every written value to its base, and a settle is scheduled after layout stop; destroying settle mode restores the bases. | Satisfies `req-viz-label-sizing-draw-only-1` and `-2` for settle-mode writes. |
| req-viz-label-sizing-settle-8 | Texture Option | Implemented | `texture_on_viewport` defaults to `false` and, when true, is passed to Cytoscape as `textureOnViewport`. | Needs a visual check before any panel enables it. |

#### Future

The HTML overlays (parent labels, scope boxes) should follow the same factor through a CSS variable. Where a scene is very large the settle pass could be split further by depth. `textureOnViewport` needs a visual judgement on a GPU-enabled browser.


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
