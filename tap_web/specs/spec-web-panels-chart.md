# tap_web Chart Panel Specification

## Philosophy

TAP needs a way to render charts on dashboard pages. There are three reasonable shapes for this:

1. **Each plugin ships its own charting code.** Worst path. Plugins re-vendor a charting library, settle on incompatible chart shapes, and the platform ends up with three different ways to render a bar chart.
2. **A single domain-specific chart panel per plugin** (e.g. `KsiViolationTrendPanel`). Better, but each new chart needs Python + a new template; the per-chart fanout grows quickly.
3. **A single generic chart panel type owned by `tap_web`** that accepts a chart specification and renders it. Plugins consume it like they already consume `viewer`, `table`, `flip`, and `history`. New chart types are GRIFT changes, not Python changes.

This spec describes (3). The panel type is owned by `tap_web` so any plugin can drop a chart on any page without taking a dependency on a domain plugin. The renderer is **Apache ECharts** (Apache 2.0 licensed, vendored locally per the same pattern as Tabulator).

v0 ships **intentionally bare**: the panel type registers, the template renders an empty mount div, the ECharts JS bundle is loaded as a panel asset. No chart definition language, no GRIFT instances, no example pages. The point of v0 is to land the engine and the slot — actual chart-rendering behavior lands in subsequent revisions when the first real consumer is scoped.

### Why ECharts

- **Apache 2.0 license** — same legal posture as the rest of TAP's vendored JS.
- **Declarative option object** — chart type, data, axes, legends, themes are all keys on a single JSON-shaped `option` object. That's the natural shape for a future GRIFT-driven chart configuration field.
- **Broad chart coverage** — line, bar, pie, scatter, heatmap, treemap, sankey, graph, radar, gauge, candlestick, all in one bundle. We don't have to swap libraries when we add a new chart shape.
- **Server-side or client-side data** — ECharts' `option.dataset` accepts inline data, and the renderer is happy to be re-initialised after an HTMX swap.

Reviewers may push back on the bundle size (ECharts full build is ~1MB minified). The alternative — a smaller subset bundle (`echarts.common.min.js`) — was considered and rejected for v0 because future chart types would force a bundle swap, which means re-vendoring and a coordinated panel update. The "ship the full bundle once, never swap it" tradeoff is more important than ~600KB of asset weight on a dashboard page.

### Cross-References

- [`tap_web/specs/spec-web-panel.md`](spec-web-panel.md) — Panel model and type-registration contract.
- [`tap_web/specs/spec-web-panels-standard.md`](spec-web-panels-standard.md) — sibling tap_web-owned panel types; the chart panel slots in alongside `viewer`, `table`, `flip`, `history`.
- [`tap_web/specs/spec-web-page.md`](spec-web-page.md) — Page model, `USES_PANEL` hotlink (relevant for future instance seeding).

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | tap_web-Owned       | The panel type lives in `tap_web` so any plugin can use it without taking a domain dependency |
| 2. | ECharts-Backed      | Renders via Apache ECharts (Apache 2.0); JS bundle vendored locally |
| 3. | Pinned Version      | ECharts version is pinned in vendoring; bundle swap is an explicit, coordinated change |
| 4. | Bare v0             | v0 lands the engine and a slot only; no chart definition language, no instances, no GRIFT seeds |
| 5. | Forward-Compatible  | The shape (panel type + asset wiring) is the natural place for a future declarative chart-spec field, without rework |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panels-chart-panel-type | [Chart Panel Type](#chart-panel-type) | Implemented | `ChartPanelType` registered under slug `chart`; loads ECharts JS as a panel asset |
| req-web-panels-chart-asset-vendor | [Vendored ECharts Asset](#vendored-echarts-asset) | Implemented | `echarts.min.js` vendored at `tap_web/static/tap_web/js/lib/echarts.min.js`, version pinned |
| req-web-panels-chart-rendering | [Empty-Mount Rendering](#empty-mount-rendering) | Implemented | v0 template renders an empty mount `<div>` with no chart; future revisions add the chart-spec layer |
| req-web-panels-chart-config | [Empty Config Shape](#empty-config-shape) | Implemented | `config_defaults = {}`; the chart-spec config field is reserved for a future revision |

---

### Chart Panel Type
----
RID: `req-web-panels-chart-panel-type`

Status: `Implemented`

The chart panel is registered as a tap_web-owned panel type alongside `viewer`, `table`, `flip`, and `history`.

#### Implementation
- Class: `ChartPanelType` at `tap_web/panels/chart/__init__.py`.
- `slug = "chart"`.
- `label = "Chart"`.
- `view = "tap_web/panels/chart.html"`.
- `css: list[str] = ["tap_web/css/panel-chart.css"]`.
- `js: list[str] = ["tap_web/js/lib/echarts.min.js"]` — vendored ECharts bundle. See `req-web-panels-chart-asset-vendor`.
- `editor_view = ""` — in-page editing is out of scope for v0.
- `config_defaults: dict[str, Any] = {}` — see `req-web-panels-chart-config`.
- `get_view_context(panel, request)` returns `{}` in v0. The template needs no data — only the mount `<div>` and the optional header.
- Registration happens in `tap_web/apps.py` `AppConfig.ready()` via `panel_type_registry.register("chart", ChartPanelType)`.

#### Development
- The class deliberately avoids defining any `option` / chart-spec field on `panel.config`. v0 is a stub. The future revision that lands the chart-spec layer will both update this spec (status flip + new requirement) and add the field through normal change-control — no preemptive schema is added here.
- A second tap_web panel type (the standard `viewer` / `table` / etc.) is the operational model: same registration call, same `view` template path shape, same CSS naming.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-panel-type-1 | Type Registration | Implemented | `ChartPanelType` is registered under slug `chart` in `tap_web` `AppConfig.ready()`. | Registry: `panel_type_registry` |
| req-web-panels-chart-panel-type-2 | Standard Class Members | Implemented | The class declares `slug`, `label`, `view`, `css`, `js`, `editor_view`, `config_defaults`, and a `get_view_context` classmethod per the panel-type contract. | Cross-ref `spec-web-panel.md` |
| req-web-panels-chart-panel-type-3 | tap_web Owned | Implemented | The panel type lives in `tap_web`, not in a domain plugin. | Goal 1 |

---

### Vendored ECharts Asset
----
RID: `req-web-panels-chart-asset-vendor`

Status: `Implemented`

The ECharts JS bundle is vendored locally and shipped as a panel asset, the same way Tabulator is vendored at `tap_web/js/lib/tabulator.min.js`.

#### Implementation
- File: `tap_web/static/tap_web/js/lib/echarts.min.js`.
- Source: the official Apache ECharts `dist/echarts.min.js` from the project's npm release (mirrored on jsDelivr).
- License: Apache 2.0 — preserved in the file's leading comment block.
- Version: pinned to **6.0.0** (current latest at time of vendoring). Version is recorded here in the spec so re-vendoring is an explicit, audited change rather than a silent drift.
- The bundle is loaded by the chart panel type via its `js` list. The page renderer injects a `<script>` tag for each entry, so any page that mounts a chart-panel instance gets ECharts available on `window.echarts` before the panel's per-instance JS runs.

#### Development
- v0 vendors the **full** ECharts build (`echarts.min.js`, ~1MB) rather than a subset (`echarts.common.min.js`, ~600KB). Rationale: the full build covers every chart type ECharts ships, so adding a new chart shape in a future revision is a GRIFT-only change, not a bundle swap. The asset-weight tradeoff is acceptable for v0 (dashboard pages already load Tabulator + Cytoscape on KSI / viz pages).
- Version bumps must be deliberate. Re-vendoring a new ECharts release follows the same rule as any vendored library: drop the new file in, update the version pin in this spec, smoke-test the affected pages before merging.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-asset-vendor-1 | Vendored At Standard Path | Implemented | `tap_web/static/tap_web/js/lib/echarts.min.js` exists and is the Apache ECharts minified build. | Same path shape as `tabulator.min.js` |
| req-web-panels-chart-asset-vendor-2 | Version Pinned | Implemented | The vendored version is recorded in this spec; updates require a coordinated re-vendor + spec edit. | v0: 6.0.0 |
| req-web-panels-chart-asset-vendor-3 | License Preserved | Implemented | The Apache 2.0 license header from the upstream bundle is present in the vendored file. | |
| req-web-panels-chart-asset-vendor-4 | Loaded By Panel Type | Implemented | The chart panel type's `js` list references the asset, so any page mounting a chart instance loads ECharts before per-instance JS runs. | Cross-ref `req-web-panels-chart-panel-type` |

#### Future
- Switch to a smaller subset build (`echarts.common.min.js`) once the set of in-use chart types is stable and the asset-weight tradeoff is worth the build coordination.
- Source-mapped vendoring (ship the source map alongside the min build) once a real chart panel surfaces enough to make debugging mid-bundle warranted.

---

### Empty-Mount Rendering
----
RID: `req-web-panels-chart-rendering`

Status: `Implemented`

The v0 template renders an empty mount `<div>` and nothing else. No chart is drawn.

#### Implementation
- Template: `tap_web/templates/tap_web/panels/chart.html`.
- The template:
  - Wraps in `<div class="tap-panel tap-panel--chart">`, matching the standard tap_web panel wrapper convention.
  - Includes `tap_web/panel_header.html` unless `panel.config.hide_header` is set.
  - Renders a single `<div class="tap-chart-mount" id="tap-chart-{{ panel.entity_id }}"></div>` as the chart container. Stable per-panel ID lets future per-instance JS find its mount.
- No JS executes per-panel in v0. ECharts is loaded by the panel type's `js` list, but no `echarts.init(...)` call is made — the bundle is present, the mount is present, and that's it.

#### Development
- The mount `<div>` sets no width / height in v0 — that's a CSS concern for the future chart-spec layer when sizing semantics are scoped. v0's CSS reserves a minimum vertical footprint so the empty mount isn't invisible-but-load-bearing on a page.
- The empty-state guidance from the add-panel skill ("never produce an empty container") is intentionally relaxed here: this panel is a *load-bearing stub*, not a real renderer. A "no chart configured" empty-state element would imply the panel does something today and is just unconfigured. That would mislead reviewers. The mount div is honest about being a slot.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-rendering-1 | Mount Div Present | Implemented | The template renders `<div class="tap-chart-mount" id="tap-chart-{entity_id}">` as the chart container. | |
| req-web-panels-chart-rendering-2 | Standard Wrapper | Implemented | The outer `<div>` carries `tap-panel tap-panel--chart` classes, matching the standard panel wrapper convention. | |
| req-web-panels-chart-rendering-3 | No v0 Chart Drawing | Implemented | v0 does not draw a chart. ECharts is loaded but never initialised on the mount. | Future revisions land the chart-spec layer |

#### Future
- Per-instance JS that reads a chart-spec field on `panel.config` and calls `echarts.init(mount).setOption(option)`.
- HTMX-aware re-init: re-binding the chart on partial-page swaps so dashboard refreshes don't leave dead chart canvases.
- Theme integration: register a TAP-flavoured ECharts theme so charts inherit the slate palette other panels use.

---

### Empty Config Shape
----
RID: `req-web-panels-chart-config`

Status: `Implemented`

`panel.config` is empty in v0. The chart-spec field is reserved for a future revision.

#### Implementation
- `config_defaults: dict[str, Any] = {}` on the panel type.
- No keys are read off `panel.config` by `get_view_context` or the template (other than the standard `hide_header` flag which is panel-wide, not chart-specific).
- A future revision will introduce a single `option` key carrying an ECharts-native `option` object (or a TAP-flavoured wrapper that compiles to one). This spec deliberately does not preempt the wrapper-vs-passthrough choice.

#### Development
- Resist scaffolding a stub `option` field "for future use." Empty placeholders accumulate migration cost and obscure which fields are real, per the same rule applied to the ComplianceContext model. The shape lands when the first real consumer is scoped.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-config-1 | Empty Defaults | Implemented | `config_defaults` is `{}` in v0. | |
| req-web-panels-chart-config-2 | No Config Reads | Implemented | The panel reads no chart-specific keys from `panel.config` in v0. | `hide_header` is panel-wide, not chart-specific |

#### Future
- `option` field on `panel.config` accepting an ECharts option object — direct passthrough or a TAP-flavoured wrapper.
- Per-chart data-source field that points at a Search entity so the chart's data is loaded via the standard search dispatch pipeline rather than inlined into the option object.

---

## Out Of Scope (v0)

- Any actual chart rendering. The mount div sits empty.
- A chart-specification language or `option` config field on `panel.config`.
- GRIFT panel instances mounted on pages. Consuming plugins will seed instances when the chart-spec layer lands.
- Editor support for in-page chart configuration.
- Theme registration / TAP-flavoured ECharts colour scheme.
- HTMX re-init binding for partial-page refresh.
- Per-chart data sources (Search / gryphon).

## Future Work

- **Chart-spec layer.** The first revision after v0 lands an `option` config key, per-instance JS that calls `echarts.init`, and at least one real consumer (e.g. a KSI violation-trend chart on the FedRAMP KSI dashboard).
- **TAP theme.** Register a TAP-flavoured ECharts theme so charts visually align with the slate palette used elsewhere.
- **Subset bundle.** Once the in-use chart types are stable, swap the full ECharts build for a smaller subset to reduce asset weight.
- **Editor integration.** A panel-editor surface for authoring / previewing chart options without round-tripping through GRIFT.
- **Search-driven data.** A `search_id` config field so the chart's data flows through the standard search-execute pipeline.

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
| Backlog | Held pending other work |

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
